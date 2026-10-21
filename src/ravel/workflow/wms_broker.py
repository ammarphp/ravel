"""Controller submission broker for a confined external-workflow child.

The confined child cannot read or append to the run store, so it cannot verify a launch
capability and never holds one. Its brokered site profile instead asks this broker, over a
controller-owned Unix socket, to submit one job script, observe one job or cancel jobs. The
broker holds everything: it re-enters the trusted launch captured when it was built, applies
every per-submission check of ``site.require_capability`` against the run store, submits the
admitted frozen bytes through the pinned site profile from its own context, journals the
returned handle and replies with only that handle.

Wire protocol: one request per connection, a JSON object terminated by a newline and at most
64 KiB; the reply is one JSON object and a newline.

    {"op": "submit", "jobscript": "<absolute path>"} -> {"ok": true, "job": "<cluster>.<proc>"}
    {"op": "status", "job": "<cluster>.<proc>"}      -> {"ok": true, "state": "running|success|failed"}
    {"op": "cancel", "jobs": ["<cluster>.<proc>", ...]} -> {"ok": true, "cancelled": [...]}

A refusal is ``{"ok": false, "error": "<reason>"}`` and submits nothing. Status and cancel
accept only handles this launch journalled. Every request is journalled (``wms-broker``) with
its outcome; the capability token never appears in a request, reply or journal row. The broker
never executes a job script and never reads the run store on the child's behalf.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import socket
import struct
import tempfile
import threading

from .wms_broker_client import BROKER_ENV, MESSAGE_LIMIT, PYTHON_ENV

JOURNAL = 'wms-broker'
JOB = re.compile(r'[0-9]+\.[0-9]+\Z')
CONNECTION_SECONDS = 30
BACKLOG = 16
MAX_CANCEL = 10000
SOCKET_NAME = 's'
# sockaddr_un holds 104 bytes on macOS and 108 on Linux, including the terminator.
SOCKET_PATH_LIMIT = 100

__all__ = ['BROKER_ENV', 'PYTHON_ENV', 'JOURNAL', 'SubmissionBroker', 'from_parameters']


def _profile_digest(profile):
    return hashlib.sha256(json.dumps(profile, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _no_constants(value):
    raise ValueError('non-finite number in broker request')


def _socket_base():
    """A short private base for the socket directory: /tmp, or TMPDIR when that is shorter."""
    candidate = os.environ.get('TMPDIR', '').rstrip('/')
    if candidate and os.path.isabs(candidate) and len(candidate) < len('/tmp') and os.path.isdir(candidate):
        return candidate
    return '/tmp'


class SubmissionBroker:
    """One controller-owned submission channel for one trusted launch.

    Built inside the trusted launch: the bound launch is captured here because a context
    variable does not cross into the serving thread, which re-enters exactly that scope.
    """

    def __init__(self, *, profile, store, profile_dir=None, publish_dir=None):
        from ravel.controller.routes.study import site
        from .site_profiles.htcondor import workflow_dir
        from .site_profiles.options import unpack
        bound = site._launch.get() or site._durable_launch()
        if bound is None:
            raise ValueError('a submission broker requires a bound trusted launch')
        if getattr(store, 'run_id', None) != bound['run_id']:
            raise ValueError('the broker journal store differs from the trusted launch run')
        self._bound = {'store': bound['store'], 'launch_id': bound['launch_id'],
                       'token': bound['token'], 'scope': deepcopy(bound['scope'])}
        self.store = store
        self.profile_dir = None
        self._pin = None
        if profile_dir is not None:
            from . import wms_site
            folder = Path(profile_dir)
            if not folder.is_absolute():
                raise ValueError('the broker site profile directory must be absolute')
            self._pin = wms_site.profile_pin(folder)
            pinned = json.loads((folder / 'profile.json').read_bytes())
            if profile is not None and profile != pinned:
                raise ValueError('the broker profile differs from its pinned profile directory')
            profile, self.profile_dir = pinned, folder
        if not isinstance(profile, dict) or profile.get('name') != 'htcondor':
            raise ValueError('the submission broker serves a pinned HTCondor site profile')
        _, options = unpack(profile)
        if options.get('submission') != 'broker':
            raise ValueError('the submission broker serves only a brokered site profile')
        if not options['workflow_dir'] or not os.path.isabs(options['workflow_dir']):
            raise ValueError('a brokered site profile names its absolute workflow directory')
        self.profile = deepcopy(profile)
        self.options = options
        self.profile_sha256 = _profile_digest(self.profile)
        # The site profile client publishes admitted bytes here; a different location is refused.
        published = workflow_dir(options).resolve().parent / '.ravel-controller-submissions'
        if publish_dir is not None and Path(publish_dir).absolute().resolve() != published:
            raise ValueError('the broker publication directory must be the site profile publication root '
                             + str(published))
        self.publish_dir = str(published)
        self.socket_path = None
        self._directory = None
        self._listener = None
        self._thread = None
        self._stopping = threading.Event()

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        if self._listener is not None:
            raise ValueError('the submission broker is already serving')
        directory = tempfile.mkdtemp(prefix='rwb-', dir=_socket_base())
        os.chmod(directory, 0o700)
        path = os.path.join(directory, SOCKET_NAME)
        if len(os.fsencode(path)) > SOCKET_PATH_LIMIT:
            os.rmdir(directory)
            raise ValueError('the broker socket path exceeds the Unix socket address limit')
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(path)
            os.chmod(path, 0o600)
            listener.listen(BACKLOG)
            listener.setblocking(False)
        except BaseException:
            listener.close()
            shutil.rmtree(directory, ignore_errors=True)
            raise
        self._directory, self.socket_path, self._listener = directory, path, listener
        self._stopping.clear()
        self._thread = threading.Thread(target=self._serve, name='ravel-wms-broker', daemon=True)
        self._thread.start()
        return self.socket_path

    def stop(self):
        self._stopping.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        if self.socket_path is not None:
            try:
                os.unlink(self.socket_path)
            except FileNotFoundError:
                pass
        if self._directory is not None:
            shutil.rmtree(self._directory, ignore_errors=True)
            self._directory = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False

    def environment(self, python):
        """The channel variables a confined child receives; never the capability."""
        if self.socket_path is None:
            raise ValueError('the submission broker is not serving')
        return {BROKER_ENV: self.socket_path, PYTHON_ENV: python}

    # ------------------------------------------------------------------ serving
    def _serve(self):
        with selectors.DefaultSelector() as selector:
            selector.register(self._listener, selectors.EVENT_READ)
            while not self._stopping.is_set():
                if not selector.select(0.2):
                    continue
                try:
                    connection, _ = self._listener.accept()
                except (BlockingIOError, InterruptedError):
                    continue
                except OSError:
                    if self._stopping.is_set():
                        return
                    continue
                with connection:
                    try:
                        self._connection(connection)
                    except Exception:  # one broken connection never stops the broker
                        pass

    def _peer_allowed(self, connection):
        option = getattr(socket, 'SO_PEERCRED', None)
        if option is None:
            return True  # the private 0700 directory is the access control on this host
        raw = connection.getsockopt(socket.SOL_SOCKET, option, struct.calcsize('3i'))
        _, uid, _ = struct.unpack('3i', raw)
        return uid == os.geteuid()

    def _connection(self, connection):
        connection.setblocking(True)
        connection.settimeout(CONNECTION_SECONDS)
        if not self._peer_allowed(connection):
            return
        received = bytearray()
        while b'\n' not in received and len(received) <= MESSAGE_LIMIT:
            chunk = connection.recv(8192)
            if not chunk:
                break
            received.extend(chunk)
        line, newline, _ = bytes(received).partition(b'\n')
        request = None
        if len(line) + len(newline) > MESSAGE_LIMIT:
            reply = {'ok': False, 'error': 'broker request exceeds 64 KiB'}
        elif not newline:
            reply = {'ok': False, 'error': 'a broker request is one newline-terminated JSON object'}
        else:
            try:
                request = json.loads(line.decode(), parse_constant=_no_constants)
            except ValueError:
                request = None
            reply = self.handle(request) if isinstance(request, dict) else {
                'ok': False, 'error': 'a broker request is one newline-terminated JSON object'}
        connection.sendall((json.dumps(reply, sort_keys=True, allow_nan=False) + '\n').encode())

    # ------------------------------------------------------------------ requests
    def handle(self, request):
        """The reply to one decoded request; journalled with its outcome."""
        op = request.get('op') if isinstance(request, dict) else None
        handlers = {'submit': self._submit, 'status': self._status, 'cancel': self._cancel}
        try:
            if op not in handlers:
                raise ValueError('unknown broker operation; use submit, status or cancel')
            reply = handlers[op](request)
        except Exception as exc:  # every refusal is typed; nothing is submitted
            reply = {'ok': False, 'error': str(exc) or type(exc).__name__}
        row = {'op': op if isinstance(op, str) else None,
               'request': request if isinstance(request, dict) else None, 'reply_ok': reply['ok']}
        if not reply['ok']:
            row['error'] = reply['error']
        try:
            self.store.append(JOURNAL, row)
        except Exception:
            pass  # a scheduler handle is already in study-site-job; the reply still reaches the child
        return reply

    def _owned(self, job):
        from ravel.controller.routes.study.contracts import records
        if not isinstance(job, str) or not JOB.fullmatch(job):
            raise ValueError('an HTCondor job handle is <cluster>.<proc>')
        launch = self._bound['launch_id']
        if not any(r.get('launch_id') == launch and r.get('job') == job
                   for r in records(self._bound['store'], 'study-site-job')):
            raise ValueError('job ' + job + ' is not a submission of this launch')
        return job

    def _current_profile_sha256(self):
        """The pinned profile digest, revalidated at each submission."""
        if self.profile_dir is None:
            return None
        from . import wms_site
        current = wms_site.profile_pin(self.profile_dir)
        if current != self._pin or json.loads((self.profile_dir / 'profile.json').read_bytes()) != self.profile:
            raise ValueError('the pinned site profile changed after the broker started; nothing was submitted')
        return current['sha256']

    def _submit(self, request):
        from ravel.controller import authority
        from ravel.controller.routes.study import site
        from .site_profiles import htcondor
        jobscript = request.get('jobscript')
        if (set(request) != {'op', 'jobscript'} or not isinstance(jobscript, str)
                or not os.path.isabs(jobscript) or '\x00' in jobscript):
            raise ValueError('submit names exactly one absolute job script; nothing was submitted')
        state = authority.stop_state(self._bound['store'])
        if state != 'running':
            raise ValueError('scheduler submission refused: operator state: ' + str(state))
        profile_sha256 = self._current_profile_sha256()
        bound = self._bound
        with site.trusted_launch(bound['store'], bound['launch_id'], bound['token'], bound['scope']):
            htcondor.check_credential(self.profile)
            admission = site.require_capability(
                Path(jobscript), profile_sha256=profile_sha256,
                resource_defaults={key: self.options[key] for key in ('mem_mb', 'runtime')})
            admitted = {**admission, 'submission_profile_sha256': self.profile_sha256}
            # One admission: the profile client publishes the admitted snapshot and submits it.
            job = htcondor.submit(jobscript, profile=deepcopy(self.profile), _admission={'admission': admitted})
            if not isinstance(job, str) or not JOB.fullmatch(job):
                raise ValueError('the scheduler returned no valid job handle')
            try:
                site.record_submission(admission, job)
            except Exception as exc:
                raise ValueError('the scheduler accepted job ' + job + ' but its handle could not be journalled: '
                                 + str(exc)) from exc
        return {'ok': True, 'job': job}

    def _status(self, request):
        from . import wms_site
        if set(request) != {'op', 'job'}:
            raise ValueError('status names exactly one job handle')
        job = self._owned(request.get('job'))
        observation = wms_site.observe_job(job)
        state = observation.get('state')
        if state in ('pending', 'running', 'held'):
            answer = 'running'
        elif state == 'exited':
            fields = str(observation.get('raw') or '').split()
            answer = 'success' if len(fields) > 1 and fields[1] == '0' else 'failed'
        else:  # cancelled, unknown or unreadable: never success
            answer = 'failed'
        return {'ok': True, 'state': answer}

    def _cancel(self, request):
        from . import wms_site
        jobs = request.get('jobs')
        if set(request) != {'op', 'jobs'} or type(jobs) is not list or not 1 <= len(jobs) <= MAX_CANCEL:
            raise ValueError('cancel names a non-empty list of job handles')
        owned = [self._owned(job) for job in jobs]
        cancelled, failed = [], []
        for job in dict.fromkeys(owned):
            result = wms_site.cancel_job(job)
            (cancelled if result.get('returncode') == 0 else failed).append(job)
        reply = {'ok': True, 'cancelled': cancelled}
        if failed:
            reply['failed'] = failed
        return reply


def from_parameters(store, binding):
    """A broker for a step's ``site_broker`` binding: its pinned profile and publication root."""
    if type(binding) is not dict or set(binding) != {'profile_dir', 'publish_dir'}:
        raise ValueError('site_broker names exactly profile_dir and publish_dir')
    for key in ('profile_dir', 'publish_dir'):
        if not isinstance(binding[key], str) or not os.path.isabs(binding[key]):
            raise ValueError('site_broker ' + key + ' must be an absolute path')
    return SubmissionBroker(profile=None, store=store, profile_dir=binding['profile_dir'],
                            publish_dir=binding['publish_dir'])
