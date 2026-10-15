"""The machine lease: one native scientific job on this machine at a time.

Location. The lease lives in one fixed per-user directory on this machine,
``<home of the uid>/.local/state/ravel/machine``, resolved from the password
database rather than ``HOME`` or ``RAVEL_STATE_DIR``. A relocated state directory,
worktree or placement environment therefore cannot create a second lease.
``machine_state_root()`` is that per-user directory; user-wide stores (an exposure
ledger, a custody store) live there.

Lease scope. On a cluster the home directory is shared by every node, so a lease in
the state root would be one lease for the whole cluster. The lease root
(``machine_dir()``, used by ``machine_lock()`` and every lease record) is therefore
scoped by facts of the process, never by a setting:

- inside a Slurm allocation (``SLURM_JOB_ID``, proven by the job's own cgroup in
  ``/proc/self/cgroup``) the allocation is the machine:
  ``<state root>/scopes/slurm-<cluster>-<job id>``. Every process of the job, its
  steps included, shares that lease; a variable without the cgroup selects nothing;
- on Linux with the home on a network file system (NFS, Lustre, GPFS and the like)
  the host is the machine: ``<state root>/scopes/host-<host name>``;
- otherwise (a laptop, a workstation with a local home) the state root itself.

Within one scope the rule is unchanged: one native scientific job at a time.

Test lock domain. A test lock domain is a marked directory (``ravel-test-machine-domain``)
that ``holder()`` reports as ``test``. Only code running in this process selects it: the
test harness (``tests/conftest.py``) or a selftest calls ``test_domain_grants().enter``.
A child process works in its parent's test domain only through a grant the parent's
process validates while the child asks: ``RAVEL_TEST_DOMAIN_GRANT`` names the issuing
process's private socket and a random token, and the child asks that process which
domain the token stands for. No variable, marker file or argument selects the domain by
itself. A process whose environment carries the retired ``RAVEL_TEST_MACHINE_DIR``, a
grant that cannot be validated, or the test runner's ``PYTEST_CURRENT_TEST`` without a
grant is refused: it uses neither a test domain nor the machine directory, so a probe
with forged variables and a test child that lost its grant write nothing anywhere.

Approval. A fresh lease in the machine domain needs the binding of an approved
stage (``execution_backend.approved_binding``): the run, the stage and the
approval route, re-verified here. A process without one gets no lease, so it can
neither start a native job nor dispatch a backend job. The test lock domain admits
unbound holders, so mechanism tests need no approved run.

Lock and record. The holder takes an exclusive ``flock`` on ``native-job.lock``
and writes ``native-job.json``. After locking, the lock file's inode is compared
with the path's, so a deleted and recreated lock file is never trusted.

Job fence. A job outlives the process that holds the lock when that process is
killed, and its descendants can leave its process group (a new session, a double
fork, a daemon). Every computation under the lease is therefore recorded in
``native-job-fence.json`` before it starts, with three ties to its processes:

- the *hold*: a file (the job's log) opened and locked before the first job
  process exists. Every job process inherits that open file as its standard
  output; the lock stays held while any of them keeps it, whatever its session
  or process group;
- the *job token*: ``RAVEL_JOB_TOKEN`` in the environment of every job process;
- the *process group* and its leader's start identity, recorded when known.

An entry is live while its hold is locked, while a process carries its token or
while its group has a member (a reused leader pid removes only that pid from the
census). ``acquire`` refuses while any entry is live, even when the flock is free.
An unreadable fence record and a malformed row block. An entry that cannot be
proven live or dead (a group of unknown identity, or a token while the process
census is unavailable) also blocks; it is cleared only by a recorded operator
action (``clear-fence``), which refuses an entry whose hold is locked or whose
token a live process carries, and resolves the backend handle the entry names.

macOS boundary (a known limit). macOS has no process containment for an
unprivileged user. A descendant that leaves its group, replaces both standard
streams and drops the job token (or runs a system binary, whose environment macOS
hides from ``ps``) is outside the fence; it cannot be detected without kernel
containment. ``preflight`` lists, read-only, the live processes RAVEL can still
tie to recorded jobs; the operator runs it before each native job.

Linux. The process census reads ``/proc/<pid>/environ`` (the Linux ``ps`` cannot
print an environment). A process whose environment this user cannot read counts
as one without a token; without a readable process table the census is unknown.

One computation per lease. ``reserve`` admits a computation under a lease only
when every live entry of that lease is its own ancestor job (through the job
token chain), so a second concurrent submission under one lease is refused.

Delegation. A process that holds the lease exports its id in
``RAVEL_MACHINE_LEASE``. A descendant may work under that lease only with proof:
the record carries the same id, the holder is the recorded live process and an
ancestor of the caller, and the request names the lease's own job:

- a *handoff* asks for the same ``(rundir, node_id)`` as the innermost owner
  (the stage worker of the holder's supervised stage, or the worker of a nested
  stage); each owner hands off once;
- a *nested* request (``nested=True``) starts a sub-stage under the innermost
  worker's job (for example an amplitude stage driven by the scientific worker),
  inside the owner's run directory, a declared output of its stage, or an
  existing store that belongs to no run; never inside another run.

Delegations form one chain: every live delegate must be an ancestor of the
caller. A sibling, a second request from a delegate, a request for another run
and an unproven request are refused at once. The environment variable alone
grants nothing.

Boundary. The records are ordinary files of this user. They prevent confusion
between cooperating RAVEL processes; they do not defend against a hostile
process of the same user. Such a process could also run its own grant server
and answer a forged token; setting variables or writing a marker cannot.

Remote backends take ``execution_backend.remote_slot``, not this lease.
"""
from __future__ import annotations

import atexit
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import socket
import stat as st
import subprocess
import sys
import tempfile
import threading
import time
import re
from typing import Iterator
import uuid

from .state_io import atomic_json, read_json

ENV = 'RAVEL_MACHINE_LEASE'
JOB_ENV = 'RAVEL_JOB_TOKEN'
WAIT_ENV = 'RAVEL_LEASE_WAIT_SECONDS'
TEST_ENV = 'RAVEL_TEST_MACHINE_DIR'  # retired selector: its presence is refused, it selects nothing
GRANT_ENV = 'RAVEL_TEST_DOMAIN_GRANT'
RUNNER_ENV = 'PYTEST_CURRENT_TEST'
TEST_MARKER = 'ravel-test-machine-domain'
LOCK_NAME = 'native-job.lock'
RECORD_NAME = 'native-job.json'
FENCE_NAME = 'native-job-fence.json'
MUTEX_NAME = 'native-job.mutex'
ACTIONS_NAME = 'native-job-fence-actions.jsonl'
DEFAULT_WAIT_SECONDS = 86400.0
MIN_PROBE_WAIT = 0.5  # a no-wait acquirer still outlasts a concurrent holder() probe
_MAX_ANCESTRY = 64
_OPEN = {}  # lease_id -> open lock stream of a lease this process acquired
_LOCATION = None  # test seam (in process): machine-domain rules at another location
_TEST_DOMAIN = None  # in-process test lock domain (the test harness or a selftest); never from the environment
_GRANTED = None  # (grant, directory) this process validated with the issuing process
_GRANTS = None  # the grant server of this process, started by ``test_domain_grants``
_TOKEN = re.compile(JOB_ENV + r'=([0-9a-f]{32})(?![0-9a-f])')
_PROCFS = '/proc' if sys.platform.startswith('linux') else None  # Linux process table; None: ask ``ps -E``


@dataclass(frozen=True)
class Lease:
    lease_id: str
    holder: str
    pid: int
    since_utc: str
    rundir: str | None
    node_id: str | None
    inherited: bool = False


class LeaseBusy(ValueError):
    def __init__(self, message, held):
        super().__init__(message)
        self.held = held


# ---------------------------------------------------------------- location
_PROC_CGROUP = '/proc/self/cgroup'  # seam: the cgroup membership that proves a Slurm allocation
_PROC_MOUNTS = '/proc/self/mounts'  # seam: the mount table that shows a shared home
SLURM_JOB_ENV = 'SLURM_JOB_ID'
SHARED_FILESYSTEMS = frozenset({
    'nfs', 'nfs4', 'lustre', 'gpfs', 'cifs', 'smb3', 'smbfs', 'beegfs', 'fuse.beegfs', 'ceph', 'cephfs',
    'fuse.ceph', 'glusterfs', 'fuse.glusterfs', 'panfs', 'afs', 'fuse.sshfs', 'wekafs', 'orangefs', 'pvfs2'})


def _name(text):
    """A file-name-safe rendering of a host or cluster name."""
    return re.sub(r'[^A-Za-z0-9._-]', '_', text)[:64].lstrip('.') or 'unnamed'


def slurm_allocation(environ=None, cgroup_text=None):
    """``{'cluster', 'job_id'}`` of the Slurm allocation this process runs in, or None.

    ``SLURM_JOB_ID`` alone proves nothing: the process's cgroup must name ``job_<id>``
    (Slurm's cgroup plugins, v1 and v2), so a copied variable on a laptop or login
    node selects no allocation scope.
    """
    environ = os.environ if environ is None else environ
    job = environ.get(SLURM_JOB_ENV, '')
    if not re.fullmatch(r'[0-9]{1,12}', job):
        return None
    if cgroup_text is None:
        try:
            cgroup_text = Path(_PROC_CGROUP).read_text()
        except OSError:
            return None
    member = any(f'job_{job}' in line.partition(':')[2].partition(':')[2].split('/')
                 for line in cgroup_text.splitlines())
    if not member:
        return None
    cluster = environ.get('SLURM_CLUSTER_NAME')
    return {'cluster': _name(cluster) if cluster else None, 'job_id': job}


def allocation_key(allocation):
    """``slurm-<cluster>-<job id>``, or ``slurm-<job id>`` where the site names no cluster."""
    return '-'.join(['slurm'] + ([allocation['cluster']] if allocation.get('cluster') else []) + [allocation['job_id']])


def _unescape_mount(field):
    return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m.group(1), 8)), field)


def shared_filesystem(path, mounts_text=None):
    """The file-system type of ``path`` when it is a network file system shared between hosts, else None."""
    if mounts_text is None:
        if not sys.platform.startswith('linux'):
            return None
        try:
            mounts_text = Path(_PROC_MOUNTS).read_text()
        except OSError:
            return None
    target = os.path.realpath(path)
    best, kind = '', None
    for line in mounts_text.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        point = _unescape_mount(fields[1])
        inside = target == point or target.startswith(point.rstrip('/') + '/')
        if inside and len(point) >= len(best):
            best, kind = point, fields[2]
    return kind if kind in SHARED_FILESYSTEMS else None


def lease_scope(state_root=None, *, environ=None, cgroup_text=None, mounts_text=None, host=None):
    """``{'kind', 'key', ...}``: the machine a lease stands for (``slurm-job``, ``host`` or ``machine``)."""
    allocation = slurm_allocation(environ, cgroup_text)
    if allocation is not None:
        return {'kind': 'slurm-job', 'key': allocation_key(allocation), **allocation}
    root = state_root if state_root is not None else _state_root_path()
    filesystem = shared_filesystem(root, mounts_text)
    if filesystem is not None:
        name = _name(host if host is not None else socket.gethostname())
        return {'kind': 'host', 'key': f'host-{name}', 'host': name, 'filesystem': filesystem}
    return {'kind': 'machine', 'key': None}


def allocation_identity():
    """The host or Slurm allocation a cluster lease stands for, for receipts; None outside a cluster scope."""
    current = scope()
    if current['kind'] not in ('slurm-job', 'host'):
        return None
    identity = {'scope': current['key'], 'kind': current['kind'], 'host': socket.gethostname()}
    if current['kind'] == 'slurm-job':
        identity.update(cluster=current['cluster'], job_id=current['job_id'])
        for key, name in (('nodelist', 'SLURM_JOB_NODELIST'), ('partition', 'SLURM_JOB_PARTITION'),
                          ('account', 'SLURM_JOB_ACCOUNT'), ('cpus_per_task', 'SLURM_CPUS_PER_TASK'),
                          ('array_job_id', 'SLURM_ARRAY_JOB_ID'), ('array_task_id', 'SLURM_ARRAY_TASK_ID')):
            if os.environ.get(name):
                identity[key] = os.environ[name]
    else:
        identity['filesystem'] = current['filesystem']
    try:
        identity['cpus_usable'] = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        pass
    return identity


def _state_root_path():
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / '.local/state/ravel/machine'


def _resolve():
    """``(directory, domain)`` of this process's machine locks and records."""
    if _LOCATION is not None:
        return Path(_LOCATION), 'machine'
    if _TEST_DOMAIN is not None:
        return Path(_TEST_DOMAIN), 'test'
    if os.environ.get(TEST_ENV):
        raise ValueError(f'{TEST_ENV} no longer selects a lock domain and is refused; unset it. A test lock '
                         'domain is chosen by the test harness in its own process, never by a variable')
    grant = os.environ.get(GRANT_ENV)
    if grant:
        return _granted(grant), 'test'
    if os.environ.get(RUNNER_ENV):
        raise ValueError(f'this process carries the test runner variable {RUNNER_ENV} but no test lock domain '
                         'grant; it uses neither a test domain nor the machine directory')
    root = _state_root_path()
    scope = lease_scope(root)
    return (root / 'scopes' / scope['key'] if scope['key'] else root), 'machine'


def _resolve_state_root():
    path, kind = _resolve()
    if kind == 'test' or _LOCATION is not None:
        return path
    return _state_root_path()


def machine_dir():
    """The lease root: the fixed per-user directory, scoped to the host or allocation (``lease_scope``)."""
    return _resolve()[0]


def machine_state_root():
    """The fixed per-user directory for user-wide stores; never scoped by host or allocation."""
    path = _resolve_state_root()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    stat = os.lstat(path)
    if not st.S_ISDIR(stat.st_mode) or stat.st_uid != os.getuid():
        raise ValueError(f'machine state root {path} must be a directory owned by this user, not a symlink')
    return path


def domain():
    return _resolve()[1]


def scope():
    """The lease scope of this process: ``test``, a relocated ``machine`` location, or ``lease_scope()``."""
    path, kind = _resolve()
    if kind == 'test' or _LOCATION is not None:
        return {'kind': kind, 'key': None, 'directory': str(path)}
    return lease_scope(_state_root_path()) | {'directory': str(path)}


def _checked_test_domain(path):
    path = Path(path)
    try:
        info = os.lstat(path)
    except OSError:
        info = None
    if (not path.is_absolute() or info is None or not st.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or not (path / TEST_MARKER).is_file()):
        raise ValueError(f'a test lock domain must be an absolute directory of this user holding {TEST_MARKER}')
    return path


def _granted(grant):
    """The test lock domain a grant stands for, as the process that issued it answers now."""
    global _GRANTED
    if _GRANTED is not None and _GRANTED[0] == grant:
        return _GRANTED[1]
    address, _, token = grant.rpartition('#')
    refused = f'{GRANT_ENV} is not a test lock domain grant this process can validate; nothing is used'
    if not address or not re.fullmatch(r'[0-9a-f]{64}', token):
        raise ValueError(refused)
    try:
        # The issuing process listens in a private directory of this user.
        holder, entry = os.lstat(os.path.dirname(address)), os.lstat(address)
    except OSError:
        raise ValueError(refused) from None
    if (not st.S_ISDIR(holder.st_mode) or holder.st_uid != os.getuid() or holder.st_mode & 0o077
            or not st.S_ISSOCK(entry.st_mode) or entry.st_uid != os.getuid()):
        raise ValueError(refused)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(30)
            conn.connect(address)
            conn.sendall(json.dumps({'token': token}).encode() + b'\n')
            reply = b''
            while not reply.endswith(b'\n') and len(reply) < 8192:
                chunk = conn.recv(8192)
                if not chunk:
                    break
                reply += chunk
        answer = json.loads(reply)
    except (OSError, ValueError):
        raise ValueError(refused) from None
    if type(answer) is not dict or type(answer.get('domain')) is not str:
        raise ValueError(refused)
    path = _checked_test_domain(answer['domain'])
    _GRANTED = (grant, path)
    return path


class _GrantServer:
    """Issues test lock domain grants and answers, while this process lives, which domain a token names."""

    def __init__(self):
        base = '/tmp' if os.path.isdir('/tmp') else None  # a short socket path on every platform
        self.directory = tempfile.mkdtemp(prefix='ravel-grant-', dir=base)
        os.chmod(self.directory, 0o700)
        self.address = os.path.join(self.directory, 'grant.sock')
        self.pid = os.getpid()
        self._grants = {}
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.bind(self.address)
        self._socket.listen(64)
        self._socket.settimeout(0.5)
        threading.Thread(target=self._serve, name='ravel-test-domain-grants', daemon=True).start()
        atexit.register(self.close)

    def issue(self, path):
        path = _checked_test_domain(path)
        token = secrets.token_hex(32)
        with self._lock:
            self._grants[token] = str(path)
        return f'{self.address}#{token}'

    def enter(self, path):
        """Make ``path`` this process's test lock domain and its children's; returns the previous state."""
        global _TEST_DOMAIN
        previous = (_TEST_DOMAIN, os.environ.get(GRANT_ENV))
        grant = self.issue(path)
        _TEST_DOMAIN = str(path)
        os.environ[GRANT_ENV] = grant
        return previous

    def _serve(self):
        while not self._closed.is_set():
            try:
                conn, _ = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(5)
                    request = b''
                    while not request.endswith(b'\n') and len(request) < 8192:
                        chunk = conn.recv(8192)
                        if not chunk:
                            break
                        request += chunk
                    token = json.loads(request).get('token')
                    with self._lock:
                        path = self._grants.get(token) if type(token) is str else None
                    conn.sendall(json.dumps({'domain': path} if path else {'refused': 'unknown grant'}).encode() + b'\n')
                except (OSError, ValueError, AttributeError):
                    continue

    def close(self):
        global _GRANTS
        if os.getpid() != self.pid:
            return
        if _GRANTS is self:
            _GRANTS = None
        self._closed.set()
        self._socket.close()
        shutil.rmtree(self.directory, ignore_errors=True)


def test_domain_grants():
    """This process's grant server (started on first use): the test harness and selftests only."""
    global _GRANTS
    if _GRANTS is None or _GRANTS.pid != os.getpid():
        _GRANTS = _GrantServer()
    return _GRANTS


def leave_test_domain(previous):
    """Restore the state ``_GrantServer.enter`` returned."""
    global _TEST_DOMAIN
    _TEST_DOMAIN, grant = previous
    if grant is None:
        os.environ.pop(GRANT_ENV, None)
    else:
        os.environ[GRANT_ENV] = grant


def child_env():
    """Variables a RAVEL child process needs to work in this process's lock domain.

    The machine domain needs none. A test lock domain is handed on only as this process's own
    validated grant; a domain this process cannot hand on refuses the child instead of letting
    it fall back to the machine directory.
    """
    path, kind = _resolve()
    if kind != 'test' and _LOCATION is None:
        return {}
    grant = os.environ.get(GRANT_ENV)
    if kind != 'test' or not grant or _granted(grant) != path:
        raise ValueError('this lock domain cannot be handed to a child process; nothing was started')
    return {GRANT_ENV: grant}


def ensure_machine_dir():
    path = machine_dir()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    stat = os.lstat(path)
    if not st.S_ISDIR(stat.st_mode) or stat.st_uid != os.getuid():
        raise ValueError(f'machine lease directory {path} must be a directory owned by this user, not a symlink')
    return path


def state_dir():
    """The configurable RAVEL state directory (records only; never a lock domain)."""
    configured = os.environ.get('RAVEL_STATE_DIR')
    return Path(configured).expanduser() if configured else Path.home() / '.local/state/ravel'


def leases_dir():
    return machine_dir()


def _lock_stream(path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    return os.fdopen(fd, 'a+b')


def _same_file(stream, path):
    try:
        current = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return False
    mine = os.fstat(stream.fileno())
    return (mine.st_dev, mine.st_ino) == (current.st_dev, current.st_ino)


@contextmanager
def machine_lock(name, *, wait_seconds=30.0, poll=0.05):
    """Exclusive lock ``name`` in the fixed machine directory, with the inode check.

    For machine-wide stores that must not split by ``RAVEL_STATE_DIR``.
    """
    if not isinstance(name, str) or not name or '/' in name or name.startswith('.'):
        raise ValueError('machine lock name must be a plain file name')
    path = ensure_machine_dir() / name
    deadline = time.monotonic() + wait_seconds
    while True:
        stream = _lock_stream(path)
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            stream.close()
            if time.monotonic() >= deadline:
                raise LeaseBusy(f'machine lock {name} is busy; another RAVEL process holds it', None) from None
            time.sleep(poll)
            continue
        if _same_file(stream, path):
            break
        stream.close()
    try:
        yield path
    finally:
        fcntl.flock(stream, fcntl.LOCK_UN)
        stream.close()


@contextmanager
def _mutex():
    with machine_lock(MUTEX_NAME, wait_seconds=60.0, poll=0.01):
        yield


# ---------------------------------------------------------------- processes
def _utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _identity(pid):
    from .execution import process_identity
    return process_identity(pid)


def _group_members(pgid):
    from .execution import process_group_members
    return process_group_members(pgid)


def _parent(pid):
    try:
        value = subprocess.check_output(['ps', '-p', str(pid), '-o', 'ppid='], text=True, timeout=5).strip()
        return int(value) if value else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def is_ancestor(ancestor, pid=None):
    """True when ``ancestor`` is a strict ancestor of ``pid`` (default: this process)."""
    current = os.getpid() if pid is None else pid
    for _ in range(_MAX_ANCESTRY):
        current = os.getppid() if current == os.getpid() else _parent(current)
        if current is None or current <= 1:
            return False
        if current == ancestor:
            return True
    return False


def _alive(entry):
    return type(entry.get('pid')) is int and entry.get('identity') is not None and _identity(entry['pid']) == entry['identity']


# ---------------------------------------------------------------- job ties: hold, token census
def hold_busy(path):
    """True while some process keeps the locked open file of a job's hold.

    The lock belongs to the open file description that every job process
    inherited, so it is held until the last of them closes it.
    """
    if not path:
        return False
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return False
    except OSError:
        return True  # cannot be checked: keep the job fenced
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def take_hold(stream, *, wait_seconds=5.0):
    """Lock ``stream``'s open file description as a job hold, before any job process starts."""
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise LeaseBusy(f'the job hold {getattr(stream, "name", "")} is still held by an earlier job', None) from None
            time.sleep(0.02)


def _ps_environments():
    """``(pid, job tokens)`` rows from the BSD ``ps`` (command and environment); None when it fails."""
    try:
        proc = subprocess.Popen(['ps', '-E', '-ww', '-axo', 'pid=,command='], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, errors='replace')
        output, _ = proc.communicate(timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode:
        return None
    rows = []
    for line in output.splitlines():
        fields = line.split(None, 1)
        if len(fields) == 2 and fields[0].isdigit() and int(fields[0]) != proc.pid:
            rows.append((int(fields[0]), _TOKEN.findall(fields[1])))
    return rows


def _proc_environments(root):
    """``(pid, job tokens)`` rows from the Linux process table; None when it cannot be listed.

    The Linux ``ps`` has no ``-E``; the environment of a process is the file
    ``<root>/<pid>/environ``. A table that does not list this process is not
    this machine's process table, so it proves nothing.
    """
    try:
        names = [name for name in os.listdir(root) if name.isdigit()]
    except OSError:
        return None
    if str(os.getpid()) not in names:
        return None
    rows = []
    for name in names:
        try:
            with open(os.path.join(root, name, 'environ'), 'rb') as stream:
                data = stream.read()
        except OSError:
            continue  # another user's process, or one that has ended: nothing is proven
        tokens = [match.group(1) for match in map(_TOKEN.match, data.decode('ascii', 'replace').split('\0')) if match]
        rows.append((int(name), tokens))
    return rows


def token_census():
    """Live pids by job token, read from process environments; None when they cannot be listed.

    Linux reads ``/proc/<pid>/environ``; elsewhere ``ps -E`` prints the
    environment. An environment that cannot be read (macOS hides that of system
    binaries, Linux that of another user's process) proves nothing by itself;
    the hold and the process group are checked as well.
    """
    rows = _proc_environments(_PROCFS) if _PROCFS else _ps_environments()
    if rows is None:
        return None
    seen = {}
    for pid, tokens in rows:
        if pid == os.getpid():
            continue
        for token in tokens:
            seen.setdefault(token, []).append(pid)
    return seen


class _Census:
    def __init__(self):
        self._value = False

    def pids(self, token):
        if self._value is False:
            self._value = token_census()
        return None if self._value is None else self._value.get(token, [])


def job_processes(entry, census=None):
    """What still ties live processes to a fence entry: hold, token pids and group members."""
    census = census or _Census()
    found = {}
    if entry.get('unreadable'):
        found['unreadable'] = True
        return found
    if hold_busy(entry.get('hold')):
        found['hold'] = entry['hold']
    token = entry.get('token')
    if token:
        pids = census.pids(token)
        if pids is None:
            # Unknown is not live: it still blocks a new job, but an operator may clear it.
            found['token_unknown'] = 'census unavailable'
        elif pids:
            found['token'] = pids
    pgid = entry.get('pgid')
    if type(pgid) is int and pgid > 1:
        members = _group_members(pgid)
        if entry.get('identity') is not None and _identity(pgid) not in (None, entry['identity']):
            # The leader pid now names another process; only that pid is someone else's.
            members = [pid for pid in members if pid != pgid]
        if members:
            found['group'] = members
    elif isinstance(entry.get('starter'), dict) and _alive(entry['starter']):
        found['starter'] = entry['starter']['pid']  # dispatching: no group recorded yet
    return found


def _fence_live(entry, census=None):
    """True while anything ties a live process to the fenced job."""
    return bool(job_processes(entry, census))


# ---------------------------------------------------------------- records
def _read(name):
    try:
        value = read_json(machine_dir() / name)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _read_record():
    return _read(RECORD_NAME)


def _lock_free():
    """Probe with a shared lock, which never blocks another prober."""
    path = machine_dir() / LOCK_NAME
    if not path.exists():
        return True
    with path.open('rb') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(stream, fcntl.LOCK_UN)
        return True


UNREADABLE = {'label': 'unreadable fence record', 'unreadable': True}
_HEX32 = re.compile(r'[0-9a-f]{32}')


def _valid_row(row):
    """A fence row RAVEL wrote: a lease id and at least one tie (a job token or a process group)."""
    if not isinstance(row, dict) or not isinstance(row.get('lease_id'), str) or not row['lease_id']:
        return False
    token, pgid = row.get('token'), row.get('pgid')
    token_ok = token is None or (isinstance(token, str) and _HEX32.fullmatch(token))
    pgid_ok = pgid is None or (type(pgid) is int and pgid > 1)
    return bool(token_ok and pgid_ok and (token or pgid))


def _malformed(row):
    return {'label': 'malformed fence row', 'malformed': True, 'raw': row}


def _rows(document):
    """The fence rows, a malformed one wrapped so that it blocks and is kept until an operator clears it."""
    return [row if _valid_row(row) else _malformed(row) for row in document['groups']]


def _fence_document():
    """The fence rows; None when the record exists but cannot be read (it then blocks)."""
    path = machine_dir() / FENCE_NAME
    if not path.exists() and not path.is_symlink():
        return {'groups': []}
    try:
        value = read_json(path)
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get('groups'), list):
        return None
    return value


def _write_fence(rows):
    rows = [row['raw'] if isinstance(row, dict) and row.get('malformed') else row for row in rows]
    atomic_json(ensure_machine_dir() / FENCE_NAME, {'groups': rows})


def live_fences(*, prune=False):
    """Fenced jobs that still have live processes; ``prune`` drops ended ones.

    An unreadable fence record is reported as one live entry and never overwritten.
    """
    document = _fence_document()
    if document is None:
        return [dict(UNREADABLE)]
    rows = _rows(document)
    census = _Census()
    live = [row for row in rows if row.get('malformed') or _fence_live(row, census)]
    if prune and len(live) != len(rows):
        _write_fence(live)
    return live


def _chain(rows, token):
    by_token = {row.get('token'): row for row in rows if row.get('token')}
    seen = set()
    while token and token not in seen:
        seen.add(token)
        token = (by_token.get(token) or {}).get('parent_token')
    return seen


def _admit(lease_id, rows, parent):
    """One computation per lease: every live entry of the lease is an ancestor job of the new one."""
    if any(row.get('unreadable') for row in rows):
        raise LeaseBusy('the machine fence record is unreadable; an operator clears it with '
                        '"python -m ravel.workflow.machine_lease clear-fence --unreadable"; nothing was started', None)
    if any(row.get('malformed') for row in rows):
        raise LeaseBusy('the machine fence record holds a malformed row; an operator clears it with '
                        '"python -m ravel.workflow.machine_lease clear-fence --malformed"; nothing was started', None)
    allowed = _chain(rows, parent)
    others = [row for row in rows if row.get('lease_id') == lease_id and row.get('token') not in allowed]
    if others:
        names = ', '.join(str(row.get('label') or row.get('pgid')) for row in others)
        raise LeaseBusy(f'this machine lease already runs a computation ({names}); one computation runs under '
                        'one lease at a time; nothing was started', None)


def _held_lease(lease_id):
    record = _read_record()
    if record is None or record.get('lease_id') != lease_id:
        raise LeaseBusy('the machine lease this job was started under is no longer held; the payload does not start',
                        None)
    return record


def reserve(lease_id, *, token=None, parent_token=None, hold=None, label='', handle_dir=None):
    """Reserve the one computation of ``lease_id`` before anything starts; return its job token.

    ``parent_token`` defaults to this process's own job token: a computation started
    by a job process nests in that job. ``hold`` names the file whose open
    description the job's processes will inherit, already locked by the caller.
    ``handle_dir`` names the backend attempt whose handle an operator clearing
    resolves (``clear_fence``).
    """
    token = token or uuid.uuid4().hex
    parent = os.environ.get(JOB_ENV) if parent_token is None else parent_token
    me = os.getpid()
    identity = _identity(me)
    if identity is None:
        raise ValueError(f'the identity of process {me} cannot be read; nothing was started')
    with _mutex():
        record = _held_lease(lease_id)
        rows = live_fences()
        _admit(lease_id, rows, parent)
        rows.append({'lease_id': lease_id, 'token': token, 'parent_token': parent, 'hold': hold and str(hold),
                     'starter': {'pid': me, 'identity': identity}, 'pgid': None, 'pid': None, 'identity': None,
                     'label': label, 'rundir': record.get('rundir'), 'node_id': record.get('node_id'),
                     'handle_dir': handle_dir and str(handle_dir), 'since_utc': _utc()})
        _write_fence(rows)
    return token


def unreserve(token):
    """Drop a reservation whose computation never started (nothing holds its ties)."""
    with _mutex():
        document = _fence_document()
        if document is None:
            return False
        rows = _rows(document)
        target = [row for row in rows if not row.get('malformed') and row.get('token') == token]
        if not target or any(set(job_processes(row)) - {'starter', 'token_unknown'} for row in target):
            return False
        _write_fence([row for row in rows if row.get('token') != token])
        return True


def fence(lease_id, pgid, *, pid=None, label='', token=None):
    """Record the process group of a computation under ``lease_id``; refuse when that lease is gone.

    With ``token`` the call completes that job's reservation (the backend launcher
    fencing itself before its payload); without one it admits a new computation
    under the one-computation rule. A leader whose identity cannot be read is
    refused: the payload does not start without a verifiable record.
    """
    if type(pgid) is not int or pgid <= 1:
        raise ValueError('a fenced job needs its process group id')
    leader = pgid if pid is None else pid
    identity = _identity(leader)
    if identity is None:
        raise ValueError(f'the identity of process {leader} cannot be read; the payload does not start')
    with _mutex():
        record = _held_lease(lease_id)
        rows = live_fences()
        row = next((r for r in rows if token and r.get('token') == token), None)
        if row is None:
            if token:
                raise LeaseBusy('this job has no dispatch reservation under the machine lease; the payload does not start',
                                None)
            parent = os.environ.get(JOB_ENV)
            _admit(lease_id, rows, parent)
            row = {'lease_id': lease_id, 'token': None, 'parent_token': parent, 'hold': None,
                   'rundir': record.get('rundir'), 'node_id': record.get('node_id'), 'since_utc': _utc()}
            rows.append(row)
        elif row.get('lease_id') != lease_id:
            raise LeaseBusy('this job was reserved under another machine lease; the payload does not start', None)
        row.update(pgid=pgid, pid=leader, identity=identity, label=label or row.get('label', ''), fenced_utc=_utc())
        _write_fence(rows)


def fence_inherited(pgid, *, label='', token=None):
    """Fence a group under the lease this process works under (from ``RAVEL_MACHINE_LEASE``)."""
    lease_id = os.environ.get(ENV)
    if not lease_id:
        raise LeaseBusy('this job does not run under a machine lease; the payload does not start', holder())
    fence(lease_id, pgid, label=label, token=token if token is not None else os.environ.get(JOB_ENV))


def _record_action(row):
    path = ensure_machine_dir() / ACTIONS_NAME
    with open(path, 'a', encoding='utf-8') as stream:
        stream.write(__import__('json').dumps(row, sort_keys=True, default=str) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def clear_fence(*, pgid=None, token=None, unreadable=False, malformed=False, reason, operator):
    """Operator action: clear one fence entry that cannot be proven live, or set an unreadable record aside.

    The action is appended to ``native-job-fence-actions.jsonl``. An entry whose
    hold is locked or whose job token a live process carries is proven live and is
    not cleared; stop its job. An unavailable token census is unknown, not live: an
    entry with an unlocked hold and an empty group is cleared with that observation
    recorded. ``malformed`` removes every row RAVEL did not write. A cleared entry
    that names a backend attempt resolves that attempt's handle as operator-cleared,
    so a later worker is not blocked by it.
    """
    if not isinstance(reason, str) or not reason.strip() or not isinstance(operator, str) or not operator.strip():
        raise ValueError('an operator action needs a reason and the operator')
    row = {'utc': _utc(), 'uid': os.getuid(), 'operator': operator, 'reason': reason}
    with _mutex():
        path = machine_dir() / FENCE_NAME
        document = _fence_document()
        if unreadable:
            if document is not None:
                raise ValueError('the fence record is readable; clear a named entry instead')
            aside = path.with_name(f'{FENCE_NAME}.unreadable-{_utc().replace(":", "")}')
            os.replace(path, aside)
            _record_action({**row, 'action': 'set-aside-unreadable-fence', 'moved_to': str(aside)})
            return {'moved_to': str(aside)}
        if document is None:
            raise ValueError('the fence record is unreadable; pass --unreadable')
        rows = _rows(document)
        if malformed:
            bad = [r['raw'] for r in rows if r.get('malformed')]
            if not bad:
                raise ValueError('the fence record holds no malformed row')
            _write_fence([r for r in rows if not r.get('malformed')])
            _record_action({**row, 'action': 'clear-malformed-fence-rows', 'rows': bad})
            return {'cleared_malformed': bad}
        target = [r for r in rows if not r.get('malformed')
                  and ((pgid is not None and r.get('pgid') == pgid) or (token and r.get('token') == token))]
        if len(target) != 1:
            raise ValueError('name exactly one fence entry (by --pgid or --token)')
        ties = job_processes(target[0])
        if {'hold', 'token'} & set(ties):
            raise ValueError(f'this fence entry is proven live ({sorted(ties)}); stop its job instead of clearing it')
        # Journalled in order: intent, the handle's resolution, then the fence removal and completion.
        # A failure before the removal keeps the fence and records a partial action; the same
        # command completes it.
        action = {**row, 'action': 'clear-fence-entry', 'entry': target[0], 'observed': ties}
        _record_action({**action, 'phase': 'intent'})
        try:
            resolved = _resolve_cleared_handle(target[0], operator, reason)
        except Exception as exc:
            _record_action({**action, 'phase': 'partial', 'error': f'{type(exc).__name__}: {exc}'})
            raise ValueError(f'the backend handle of this entry could not be resolved ({exc}); the fence entry '
                             'is kept and the partial action recorded; run the same command again') from exc
        _write_fence([r for r in rows if r is not target[0]])
        _record_action({**action, 'phase': 'completed', 'resolved_handle': resolved})
        return {'cleared': target[0], 'observed': ties, 'resolved_handle': resolved}


def _resolve_cleared_handle(entry, operator, reason):
    """Mark the backend handle of a cleared entry as resolved by the operator; None when there is none."""
    directory = entry.get('handle_dir')
    if not directory:
        return None
    from . import execution_backend as eb
    try:
        handle = eb.read_handle(directory)
    except (OSError, ValueError):
        return None
    if handle.get('resolution') is not None:
        return str(directory)
    handle['resolution'] = 'operator-cleared'
    handle['operator_action'] = {'utc': _utc(), 'operator': operator, 'reason': reason, 'job_token': entry.get('token')}
    eb.write_handle(handle)
    return str(directory)


def preflight():
    """Read-only: live processes that carry a recorded job token or belong to a recorded process group.

    The recorded jobs are the current fence rows and every entry an operator cleared.
    Nothing is signalled. Run it before each native job: a listed process is an
    earlier job's process that RAVEL can still see. A descendant that left its group,
    replaced its standard streams and dropped its job token is invisible to it.
    """
    document = _fence_document()
    rows = [] if document is None else _rows(document)
    recorded = [r for r in rows if not r.get('malformed')]
    malformed = sum(1 for r in rows if r.get('malformed'))
    path = machine_dir() / ACTIONS_NAME
    if path.is_file():
        import json
        for line in path.read_text(errors='replace').splitlines():
            try:
                action = json.loads(line)
            except ValueError:
                continue
            if isinstance(action, dict) and _valid_row(action.get('entry')) and action['entry'] not in recorded:
                recorded.append(action['entry'])
    census = token_census()
    processes = {}
    for row in recorded:
        token, pgid = row.get('token'), row.get('pgid')
        if token and census:
            for pid in census.get(token, []):
                processes.setdefault(pid, set()).add(f'job token {token[:8]}')
        if type(pgid) is int and pgid > 1:
            for pid in _group_members(pgid):
                if pid != os.getpid():
                    processes.setdefault(pid, set()).add(f'process group {pgid}')
    listed = [{'pid': pid, 'ties': sorted(ties), 'command': _command(pid)} for pid, ties in sorted(processes.items())]
    return {'unreadable_fence': document is None, 'malformed_rows': malformed, 'token_census': census is not None,
            'recorded_jobs': len(recorded), 'processes': listed}


def _command(pid):
    try:
        return subprocess.check_output(['ps', '-p', str(pid), '-o', 'command='], text=True, timeout=5).strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def holder():
    """The current lease record with ``alive``, or None when no record and no live job exist."""
    record = _read_record()
    fences = live_fences()
    if record is None and not fences:
        return None
    record = record or {}
    alive = bool(fences) or (record.get('lease_id') in _OPEN) or (not _lock_free() and _alive(record))
    keys = ('lease_id', 'holder', 'pid', 'since_utc', 'rundir', 'node_id', 'wait_seconds', 'binding')
    return ({key: record.get(key) for key in keys}
            | {'alive': alive, 'domain': domain(), 'directory': str(machine_dir()), 'scope': scope(),
               'fenced_groups': [{k: f.get(k) for k in ('pgid', 'label', 'rundir', 'node_id', 'unreadable', 'malformed')}
                                 for f in fences]})


_current = holder  # acquire's parameter is also named holder


def _busy(message=None):
    held = _current()
    text = message or 'another native scientific job holds this machine'
    if held and not message:
        if held.get('holder'):
            text += f" ({held.get('holder')}, since {held.get('since_utc')})"
        for group in held.get('fenced_groups', []):
            if group.get('unreadable'):
                text += ('; the machine fence record is unreadable: an operator sets it aside with '
                         '"python -m ravel.workflow.machine_lease clear-fence --unreadable"')
            elif group.get('malformed'):
                if 'malformed row' in text:
                    continue
                text += ('; the machine fence record holds a malformed row: an operator clears it with '
                         '"python -m ravel.workflow.machine_lease clear-fence --malformed"')
            else:
                text += f"; job process group {group.get('pgid')} ({group.get('label')}) is still running"
    return LeaseBusy(text + '; wait for it to finish or stop it through its supervisor', held)


# ---------------------------------------------------------------- delegation
def _run_root(path):
    """The run directory that contains ``path`` (it carries a task contract or a CHECK-IN 1 approval), or None."""
    for candidate in (path, *path.parents):
        if any((candidate / 'inputs' / name).is_file() for name in ('task_contract.json', 'checkin1_approval.json')):
            return candidate
    return None


def _within_custody(rundir, owner):
    """A nested sub-stage stays in the owner's custody, never in another run.

    Admitted: the owner's run directory or a path inside it, a declared output of
    the owner's running stage, or an existing store that is not part of any run
    (for example a persistent amplitude store). Refused: a directory inside another
    run, and a path that does not exist.
    """
    if rundir is None:
        return True
    base = owner.get('rundir')
    if base is None:
        return False
    path, base = Path(rundir).resolve(), Path(base).resolve()
    if path == base or path.is_relative_to(base):
        return True
    try:
        from .execution import load_execution, resolve_path
        record = load_execution(base)['stages'][owner.get('node_id')]
        if record.get('status') == 'running':
            outputs = [Path(resolve_path(base, value, output=True)).resolve() for value in record.get('outputs', [])]
            if any(path == out or path.is_relative_to(out) for out in outputs):
                return True
    except (OSError, KeyError, ValueError, TypeError):
        pass
    return path.is_dir() and _run_root(path) is None


def _delegate(holder_name, rundir, node_id, nested):
    """The lease this process may work under through a proven holder ancestor.

    Returns None when no lease is proven (the caller then competes for the lock);
    raises LeaseBusy when the proven lease belongs to another job.
    """
    token = os.environ.get(ENV)
    if not token:
        return None
    record = _read_record()
    if record is None or record.get('lease_id') != token or not _alive(record) or not is_ancestor(record['pid']):
        return None
    with _mutex():
        record = _read_record()
        if record is None or record.get('lease_id') != token:
            return None
        chain = [row for row in record.get('delegates', []) if _alive(row)]
        me = os.getpid()
        if any(row['pid'] == me for row in chain):
            raise _busy('this process already runs a native scientific job under the machine lease')
        if not all(is_ancestor(row['pid']) for row in chain):
            raise _busy('another process already runs a native scientific job under this machine lease')
        owner = chain[-1] if chain else {'rundir': record.get('rundir'), 'node_id': record.get('node_id'),
                                         'kind': 'holder'}
        scope = (str(rundir) if rundir is not None else None, node_id)
        if nested:
            allowed = owner['kind'] in ('holder', 'handoff') and _within_custody(scope[0], owner)
            if scope[0] is None:
                scope = (owner.get('rundir'), node_id)
            kind = 'nested'
        else:
            allowed = owner['kind'] in ('holder', 'nested') and scope == (owner.get('rundir'), owner.get('node_id'))
            kind = 'handoff'
        if not allowed:
            raise _busy(f"this process works under the machine lease of {owner.get('rundir')}:{owner.get('node_id')}; "
                        f'a native scientific job for {scope[0]}:{scope[1]} would be a second job')
        row = {'pid': me, 'identity': _identity(me), 'holder': holder_name, 'rundir': scope[0], 'node_id': scope[1],
               'kind': kind, 'since_utc': _utc()}
        record['delegates'] = [*chain, row]
        atomic_json(machine_dir() / RECORD_NAME, record)
    return Lease(record['lease_id'], record['holder'], me, row['since_utc'], scope[0], scope[1], inherited=True)


def working():
    """The lease this process works under: one it acquired, or a live delegation it holds; else None."""
    record = _read_record()
    if record is None:
        return None
    if record.get('lease_id') in _OPEN:
        return _lease(record)
    if os.environ.get(ENV) != record.get('lease_id'):
        return None
    me = os.getpid()
    for row in record.get('delegates', []):
        if row.get('pid') == me and _alive(row):
            return Lease(record['lease_id'], record['holder'], me, row['since_utc'], row.get('rundir'),
                         row.get('node_id'), inherited=True)
    return None


def inherited():
    """The proven lease of a holder ancestor this process could work under, or None (no claim is made)."""
    token = os.environ.get(ENV)
    if not token or token in _OPEN:
        return None
    record = _read_record()
    if record is None or record.get('lease_id') != token or not _alive(record) or not is_ancestor(record['pid']):
        return None
    return _lease(record, inherited=True)


def _lease(record, *, inherited=False):
    return Lease(record['lease_id'], record['holder'], record['pid'], record['since_utc'],
                 record.get('rundir'), record.get('node_id'), inherited)


def default_wait_seconds():
    value = os.environ.get(WAIT_ENV)
    if value is None:
        return DEFAULT_WAIT_SECONDS
    seconds = float(value)
    if not 0 <= seconds <= 30 * 86400:
        raise ValueError(f'{WAIT_ENV} must be between 0 and 30 days')
    return seconds


# ---------------------------------------------------------------- acquire / release
def _check_binding(binding, rundir, node_id):
    """The approved stage a fresh lease is taken for (machine domain); the test domain admits none."""
    if binding is None:
        if domain() == 'test':
            return {'route': 'test-domain'}
        raise LeaseBusy('a native scientific job takes the machine lease only for an approved stage: run it as a '
                        'supervised stage of an approved run; nothing was started', None)
    if not isinstance(binding, dict) or binding.get('rundir') != (None if rundir is None else str(rundir)) \
            or binding.get('node_id') != node_id:
        raise ValueError('the stage binding names another run or stage; nothing was started')
    from .execution_backend import verify_stage_binding
    verify_stage_binding(binding)
    return binding


def acquire(holder: str, *, rundir: str | None = None, node_id: str | None = None, nested: bool = False,
            binding: dict | None = None, wait_seconds: float = 0.0, poll: float = 0.2, on_wait=None) -> Lease:
    """Take the lease, waiting up to ``wait_seconds``; raise LeaseBusy after that.

    A proven descendant of the holder receives a delegated lease for the same
    job (see the module text). Otherwise a fresh lease in the machine domain needs
    ``binding``, the approved stage it is taken for. ``on_wait(record)`` is called
    once if the call has to wait. A process that already holds a lease is refused
    at once.
    """
    if not isinstance(holder, str) or not holder:
        raise ValueError('lease holder must be a nonempty string')
    if type(wait_seconds) not in (int, float) or not 0 <= wait_seconds <= 30 * 86400:
        raise ValueError('lease wait must be between 0 seconds and 30 days')
    if _OPEN:
        raise _busy('this process already holds the lease of a native scientific job; a second job in one process is a second job')
    delegated = _delegate(holder, rundir, node_id, nested)
    if delegated is not None:
        return delegated
    binding = _check_binding(binding, rundir, node_id)
    directory = ensure_machine_dir()
    path = directory / LOCK_NAME
    deadline = time.monotonic() + max(wait_seconds, MIN_PROBE_WAIT)
    announced = False
    stream = None
    try:
        while True:
            stream = _lock_stream(path)
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = _same_file(stream, path)
            except BlockingIOError:
                locked = False
            if locked:
                with _mutex():
                    # A live recorded holder or a live fenced group keeps the machine even when this
                    # lock is free (a deleted lock file, or a killed holder whose job still runs).
                    previous = _read_record()
                    busy = live_fences(prune=True) or (previous is not None and _alive(previous))
                    if not busy:
                        record = {'lease_id': uuid.uuid4().hex, 'holder': holder, 'pid': os.getpid(),
                                  'identity': _identity(os.getpid()), 'since_utc': _utc(), 'rundir': rundir,
                                  'node_id': node_id, 'wait_seconds': wait_seconds, 'domain': domain(),
                                  'binding': binding, 'delegates': []}
                        atomic_json(directory / RECORD_NAME, record)
                        break
            stream.close()
            stream = None
            if time.monotonic() >= deadline:
                raise _busy()
            if not announced and on_wait is not None and wait_seconds > 0:
                on_wait(_read_record())
                announced = True
            time.sleep(max(0.01, min(poll, deadline - time.monotonic())))
    except BaseException:
        if stream is not None:
            stream.close()
        raise
    _OPEN[record['lease_id']] = stream
    return _lease(record)


def release(lease: Lease) -> None:
    """Idempotent. The acquiring process releases the lock; a delegate ends its delegation.

    Fenced job groups keep the machine until they are observed empty.
    """
    if lease.inherited:
        if lease.pid != os.getpid():
            return
        with _mutex():
            record = _read_record()
            if record is not None and record.get('lease_id') == lease.lease_id:
                record['delegates'] = [row for row in record.get('delegates', [])
                                       if row.get('pid') != lease.pid and _alive(row)]
                atomic_json(machine_dir() / RECORD_NAME, record)
        return
    if lease.pid != os.getpid():
        return
    stream = _OPEN.pop(lease.lease_id, None)
    if stream is None:
        return
    try:
        with _mutex():
            record = _read_record()
            if record is not None and record.get('lease_id') == lease.lease_id:
                try:
                    (machine_dir() / RECORD_NAME).unlink()
                except FileNotFoundError:
                    pass
    finally:
        fcntl.flock(stream, fcntl.LOCK_UN)
        stream.close()


def _after_fork_in_child():
    # A forked child neither holds nor can release its parent's lease.
    for stream in _OPEN.values():
        try:
            stream.close()
        except OSError:
            pass
    _OPEN.clear()


os.register_at_fork(after_in_child=_after_fork_in_child)


@contextmanager
def held(holder: str, **kwargs) -> Iterator[Lease]:
    """Hold the lease for a block and export its id to child processes."""
    lease = acquire(holder, **kwargs)
    previous = os.environ.get(ENV)
    os.environ[ENV] = lease.lease_id
    try:
        yield lease
    finally:
        if previous is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = previous
        release(lease)


def main(argv=None):
    """``python -m ravel.workflow.machine_lease`` prints the current holder record.

    ``clear-fence --pgid N|--token T|--unreadable|--malformed --reason TEXT --operator NAME``
    records an operator action that clears one fence entry that cannot be proven live.
    ``preflight`` (also ``ravel lease preflight``) lists live processes of recorded
    jobs, read-only; it exits 1 when it lists any or cannot take the census.
    """
    import argparse
    import json
    parser = argparse.ArgumentParser(prog='ravel lease')
    sub = parser.add_subparsers(dest='command')
    clear = sub.add_parser('clear-fence', help='operator action: clear a fence entry that cannot be proven live')
    which = clear.add_mutually_exclusive_group(required=True)
    which.add_argument('--pgid', type=int)
    which.add_argument('--token')
    which.add_argument('--unreadable', action='store_true')
    which.add_argument('--malformed', action='store_true')
    clear.add_argument('--reason', required=True)
    clear.add_argument('--operator', required=True)
    sub.add_parser('preflight', help='read-only: list live processes of recorded jobs (run before each native job)')
    args = parser.parse_args(argv)
    try:
        if args.command == 'clear-fence':
            print(json.dumps(clear_fence(pgid=args.pgid, token=args.token, unreadable=args.unreadable,
                                         malformed=args.malformed, reason=args.reason, operator=args.operator),
                             indent=2, default=str))
            return 0
        if args.command == 'preflight':
            report = preflight()
            print(json.dumps(report, indent=2))
            return 1 if (report['processes'] or report['unreadable_fence'] or report['malformed_rows']
                         or not report['token_census']) else 0
        print(json.dumps(holder(), indent=2))
        return 0
    except ValueError as exc:
        print(f'machine lease: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
