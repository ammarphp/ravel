"""Native backend: run the stage argv on this machine.

The payload runs under a small launcher in its own process group. Before the
launcher exists, ``submit`` reserves the lease's one computation (machine_lease)
and locks the job log as the job's hold; the launcher and every process it starts
inherit that log as their output and ``RAVEL_JOB_TOKEN`` in their environment.
Before the payload starts, the launcher records its identity (``launcher.json``)
and completes the reservation with its process group; if either step fails the
payload never starts. The launcher writes the payload's exit code atomically
when it ends, so a later observer (or a recovery after the worker died) can tell
success, failure and cancellation apart without being the parent.
A job is finished only when nothing ties a live process to it: its process
group, its hold and its token. A payload that exits while a descendant still
runs (in its group, or in a new session or after a double fork) is reported as
running, and then as failed; the lease stays fenced until that process is gone.
The executable pinned in the plan (path and sha256) is re-verified, under the
job's effective ``PATH``, immediately before dispatch, and that resolved file is
what the launcher runs. The payload still sees the name it was invoked by as its
``argv[0]``: an interpreter reached through a symbolic link (every virtual
environment on Linux) finds its environment from that name, not from the file.
Outputs are written to ``RAVEL_OUTPUT_DIR`` inside the attempt and fetched from
there. Memory is not limited by the operating system on macOS; the wall-clock
ceiling is enforced by the worker and thread counts are set from ``cpus``. A
RAVEL scientific payload declares ``inherit_runtime_environment``: it keeps the
approved runtime environment (thread counts and ``PYTHONPATH``), which its own
registration verifies, and sets its own thread counts.

A job of a run the controller owns gets the allowlisted environment capsule instead of the
worker's whole environment, and the launcher starts its payload through the confined
launcher (``ravel.controller.confine``): writes only to the job's ``output`` and ``work``
directories, reads of the system runtime, the toolchain and the plan's inputs and read-only
trees, no network. ``payload.json`` then also records the payload's custody digest.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time

from ravel.workflow import execution_backend as eb
from ravel.workflow.state_io import atomic_json, read_json

_PACKAGE_PARENT = str(Path(__file__).resolve().parents[3])
_THREAD_VARIABLES = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')


def _process_identity(pid):
    from ravel.workflow.execution import process_identity
    return process_identity(pid)


def _group_members(pgid):
    from ravel.workflow.execution import process_group_members
    return process_group_members(pgid)


def _log_holders(path, pids):
    """Those of ``pids`` that have ``path`` open (``lsof``); None when that cannot be determined."""
    lsof = shutil.which('lsof') or ('/usr/sbin/lsof' if os.path.exists('/usr/sbin/lsof') else None)
    if lsof is None or not pids:
        return None
    try:
        result = subprocess.run([lsof, '-t', '-a', '-p', ','.join(map(str, sorted(pids))), '--', path],
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode not in (0, 1):
        return None
    return [int(line) for line in result.stdout.split() if line.isdigit()]


def _exists(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _group_alive(pgid):
    return bool(_group_members(pgid))


def _locate(executable, path_value):
    """The name the job invokes: the absolute path as written, or the ``PATH`` entry that provides it."""
    return executable if os.path.isabs(executable) else shutil.which(executable, path=path_value)


def _resolve(executable, path_value):
    located = _locate(executable, path_value)
    return Path(located).resolve() if located else None


def verify_executable(plan, env=None):
    """The argv[0] the job will run is the pinned executable with the pinned bytes."""
    pinned = plan['backend'].get('executable') or {}
    env = environment(plan) if env is None else env
    resolved = _resolve(plan['spec']['argv'][0], env.get('PATH', os.defpath))
    if resolved is None or str(resolved) != pinned.get('path'):
        raise ValueError(f"native executable {plan['spec']['argv'][0]} does not resolve to the pinned "
                         f"{pinned.get('path')} under the job environment")
    if eb.file_sha256(resolved) != pinned.get('sha256'):
        raise ValueError(f'native executable {resolved} changed since the plan was prepared')
    return str(resolved)


def _controller_job(job):
    from ravel.controller.confine import runs
    return job is not None and runs.owner_of(Path(job)) is not None


def environment(plan, job=None):
    spec = plan['spec']
    controller = _controller_job(job)
    if controller:
        from ravel.controller.confine import capsule_from
        env = capsule_from(spec.get('env', {}))
    else:
        env = dict(os.environ)
    env.update(spec.get('env', {}))
    if controller:
        # Even an explicitly supplied plan environment cannot restore selectors/secrets.
        from ravel.controller.confine.environment import scrub
        env, _ = scrub(env)
    for fact in plan['readonly_trees']:
        if 'env' in fact:
            env[fact['env']] = fact['path']
    inherit = spec.get('inherit_runtime_environment', False)
    if not inherit:
        for name in _THREAD_VARIABLES:
            env[name] = str(spec['resources']['cpus'])
        env['PYTHONPATH'] = _PACKAGE_PARENT + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    if job is not None:
        env['RAVEL_OUTPUT_DIR'] = str(job / 'output')
        # Names the job whose custody chain a RAVEL payload proves at registration;
        # it grants nothing by itself (execution.worker_custody).
        env['RAVEL_BACKEND_JOB'] = str(job)
    if controller:
        env, _ = scrub(env)
    return env


LAUNCH_WAIT_SECONDS = 20.0
_pause = threading.Event().wait  # a short wait that leaves time.sleep to the caller's own loop
DISPATCH_MARKER = 'dispatch.json'


class NativeBackend(eb.Backend):
    kind = 'native'
    local = True

    def validate(self, spec):
        if {'processes', 'disk_mib'}.intersection(spec['resources']):
            raise ValueError('resource_limit_unsupported: native backend cannot enforce aggregate process '
                             'count or retained disk; select a qualified execution adapter')
        if 'image' in spec:
            raise ValueError('the native backend runs host executables; use oci-local for an image')
        resolved = _resolve(spec['argv'][0], {**os.environ, **spec.get('env', {})}.get('PATH', os.defpath))
        if resolved is None or not resolved.is_file():
            raise ValueError(f"native executable not found: {spec['argv'][0]}")
        return spec

    def describe(self, spec):
        resolved = _resolve(spec['argv'][0], {**os.environ, **spec.get('env', {})}.get('PATH', os.defpath))
        return {'kind': self.kind, 'local': True, 'system': platform.system(), 'machine': platform.machine(),
                'executable': {'path': str(resolved), 'sha256': eb.file_sha256(resolved)},
                'limits_enforced': {'wall_seconds': 'worker',
                                    'cpus': ('payload (approved runtime environment kept)' if spec.get('inherit_runtime_environment')
                                             else 'thread environment'),
                                    'memory_mib': False},
                'resource_enforcement': {'status': 'partial', 'label': 'RESOURCE PROTECTION INCOMPLETE',
                    'aggregate_memory_mib': 'unsupported', 'processes': 'unsupported', 'disk_mib': 'unsupported',
                    'filesystem_receipt_headroom': 'not reserved'}}

    def doctor(self):
        checks = [{'name': 'python', 'ok': True, 'detail': sys.version.split()[0]},
                  {'name': 'platform', 'ok': True, 'detail': f'{platform.system()} {platform.machine()}'}]
        return {'backend': self.kind, 'ready': True, 'checks': checks}

    def verify(self, plan):
        verify_executable(plan)

    def submit(self, plan, handle):
        from ravel.workflow import machine_lease
        lease = machine_lease.working()
        if lease is None:
            raise ValueError('a native job runs only under the machine lease of an approved stage')
        job = Path(handle['job_dir'])
        (job / 'output').mkdir(parents=True)
        (job / 'work').mkdir()
        env = environment(plan, job)
        executable = verify_executable(plan, env)
        # The verified file is executed; the payload keeps the name it was invoked by.
        invoked = _locate(plan['spec']['argv'][0], env.get('PATH', os.defpath))
        launcher = [sys.executable, '-m', 'ravel.workflow.backends.native', 'launch', '--job', str(job),
                    '--argv0', os.path.abspath(invoked), '--', executable, *plan['spec']['argv'][1:]]
        with (job / 'job.log').open('ab') as log:
            # The hold and the reservation exist before any job process does.
            machine_lease.take_hold(log)
            token = machine_lease.reserve(lease.lease_id, hold=job / 'job.log', label=f"native job {handle['tag']}",
                                          handle_dir=handle['attempt_dir'])
            env[machine_lease.ENV] = lease.lease_id
            env[machine_lease.JOB_ENV] = token
            if _controller_job(job):
                from ravel.controller.confine import brokers
                env = brokers.environment(env)
            # Evidence that a launch may have started, for recovery when no identity is recorded.
            atomic_json(job / DISPATCH_MARKER, {'tag': handle['tag'], 'utc': eb.utc_now(), 'job_token': token})
            try:
                proc = subprocess.Popen(launcher, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                        cwd=job / 'work', env=env, start_new_session=True)
            except OSError as exc:
                proc, failure = None, exc
        if proc is None:
            # Nothing started; the hold closed with the log above, so the reservation can go.
            (job / DISPATCH_MARKER).unlink()
            machine_lease.unreserve(token)
            raise failure
        # The launcher records its own identity and fence before it starts the payload.
        try:
            return self._await_launcher(plan, handle, proc, token)
        except BaseException:
            # Interrupted or failed while waiting: stop our own unreaped launcher (its pid cannot
            # have been reused), so either its recorded identity or nothing of it remains.
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
            raise

    def _await_launcher(self, plan, handle, proc, token):
        from ravel.workflow import machine_lease
        job = Path(handle['job_dir'])
        deadline = time.monotonic() + LAUNCH_WAIT_SECONDS
        while True:
            remote = self.find(plan, handle)
            if remote is not None:
                if remote.get('pid') != proc.pid:
                    raise ValueError('launcher record names another process')
                return remote
            if proc.poll() is not None and self.find(plan, handle) is None:
                # The launcher starts the payload only after recording itself: nothing ran.
                (job / DISPATCH_MARKER).unlink()
                machine_lease.unreserve(token)
                raise ValueError(f'native launcher refused to start the payload (exit {proc.returncode}); see job.log')
            if time.monotonic() >= deadline:
                # Our own unreaped child: stop its group, then record whatever it managed to record.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                remote = self.find(plan, handle)
                if remote is not None and remote.get('pid') == proc.pid:
                    return remote
                machine_lease.unreserve(token)
                raise ValueError('native launcher did not record its identity in time; it was stopped')
            _pause(0.02)

    def _ties(self, handle):
        """What ties live processes outside the launcher's group to this job: its hold and its token."""
        from ravel.workflow import machine_lease
        token = (handle.get('remote') or {}).get('job_token')
        entry = {'hold': str(Path(handle['job_dir']) / 'job.log'), 'token': token}
        return machine_lease.job_processes(entry)

    def observe(self, plan, handle):
        job = Path(handle['job_dir'])
        exit_file = job / 'exit.json'
        remote = handle['remote']
        leader_alive = bool(remote['identity']) and _process_identity(remote['pid']) == remote['identity']
        if exit_file.is_file():
            record = read_json(exit_file)
            code = record['exit_code']
            others = [pid for pid in _group_members(remote['pgid']) if not (leader_alive and pid == remote['pid'])]
            if others:
                return {'state': 'running', 'exit_code': code, 'payload_exited': True,
                        'detail': f'payload exited {code}; its process group still has live members {others}'}
            ties = {} if leader_alive else self._ties(handle)
            if ties:
                return {'state': 'running', 'exit_code': code, 'payload_exited': True,
                        'detail': f'payload exited {code}; a descendant outside its process group still runs '
                                  f'(it holds {", ".join(sorted(ties))}); the machine stays fenced until it ends'}
            if record.get('descendants'):
                return {'state': 'failed', 'exit_code': code,
                        'detail': f"payload descendants {record['descendants']} remained after the payload exited"}
            if leader_alive:
                return {'state': 'running', 'exit_code': None, 'detail': 'launcher is finishing'}
            state = 'succeeded' if code == 0 else ('cancelled' if handle.get('cancel_requested') else 'failed')
            return {'state': state, 'exit_code': code}
        if leader_alive:
            return {'state': 'running', 'exit_code': None}
        if _group_alive(remote['pgid']):
            return {'state': 'running', 'exit_code': None, 'detail': 'launcher ended; process group still active'}
        ties = self._ties(handle)
        if ties:
            return {'state': 'running', 'exit_code': None, 'payload_exited': True,
                    'detail': f'launcher ended; a job process still holds {", ".join(sorted(ties))}'}
        if handle.get('cancel_requested'):
            return {'state': 'cancelled', 'exit_code': None}
        return {'state': 'failed', 'exit_code': None, 'detail': 'launcher ended without an exit record'}

    def logs(self, plan, handle):
        path = Path(handle['job_dir']) / 'job.log'
        return path.read_text(errors='replace') if path.is_file() else ''

    def _owned(self, handle):
        """True when the recorded group is provably this job's: its leader or its payload still has its
        recorded identity, or (leader gone) the job's hold is still held and a live member of the group
        carries the job's token or has the job's log open. A held log alone does not prove a reused
        group is this job's."""
        remote = handle['remote']
        if remote.get('identity') and _process_identity(remote['pid']) == remote['identity']:
            return True
        payload = Path(handle['job_dir']) / 'payload.json'
        if payload.is_file():
            row = read_json(payload)
            if row.get('identity') and _process_identity(row['pid']) == row['identity'] \
                    and row['pid'] in _group_members(remote['pgid']):
                return True
        if _process_identity(remote['pid']) is not None:
            return False  # the leader pid names another process now
        from ravel.workflow import machine_lease
        log = str(Path(handle['job_dir']) / 'job.log')
        if not machine_lease.hold_busy(log):
            return False
        members = set(_group_members(remote['pgid']))
        token = remote.get('job_token')
        carriers = (machine_lease.token_census() or {}).get(token, []) if token else []
        # A system binary's environment is hidden from ps on macOS: holding the job's log also proves it.
        return bool(members & set(carriers)) or bool(members & set(_log_holders(log, members) or []))

    def cancel(self, plan, handle, grace=5.0):
        """Signal the job's group only while it is provably this job's (``_owned``).

        A group whose leader id now names another process, or whose ownership cannot
        be proven, is not signalled; the job stays unresolved and fenced for recovery.
        Ownership is checked again before escalating to SIGKILL. A descendant outside
        the group (a new session) is not signalled: it keeps the machine fenced and is
        reported by observation for the operator.
        """
        remote = handle['remote']
        pgid = remote['pgid']
        if not _group_alive(pgid):
            return {'signalled': False}
        if not self._owned(handle):
            return {'signalled': False, 'unresolved': 'the recorded process group cannot be proven to be this job'}
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return {'signalled': False}
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline and _group_alive(pgid):
            time.sleep(0.05)
        if _group_alive(pgid) and self._owned(handle):
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        return {'signalled': True}

    def find(self, plan, handle):
        """The launcher's recorded identity; else the identity its completed fence recorded.

        The launcher fences its group before writing launcher.json and starts the payload
        only after both, so a fence row of this job's token names the launcher.
        """
        job = Path(handle['job_dir'])
        path = job / 'launcher.json'
        if path.is_file():
            return read_json(path)
        token = self._dispatch_token(handle)
        if token:
            from ravel.workflow import machine_lease
            document = machine_lease._fence_document() or {'groups': []}
            for row in document['groups']:
                if machine_lease._valid_row(row) and row.get('token') == token and row.get('pgid') \
                        and row.get('identity'):
                    return {'pid': row['pid'], 'pgid': row['pgid'], 'identity': row['identity'], 'job_token': token,
                            'recorded_by': 'fence'}
        return None

    def _dispatch_token(self, handle):
        marker = Path(handle['job_dir']) / DISPATCH_MARKER
        try:
            return read_json(marker).get('job_token') if marker.is_file() else None
        except (OSError, ValueError):
            return None

    def settle_unidentified(self, plan, handle):
        """'never-started' when the launch left no identity and nothing of it lives.

        The launcher starts the payload only after recording launcher.json, so with no
        launcher record and no live tie (hold, job token, recorded group) no payload ran.
        An unavailable token census leaves it unknown.
        """
        from ravel.workflow import machine_lease
        job = Path(handle['job_dir'])
        if (job / 'launcher.json').exists() or (job / 'payload.json').exists() or (job / 'exit.json').exists():
            return None
        token = self._dispatch_token(handle)
        if not token:
            return None
        ties = machine_lease.job_processes({'hold': str(job / 'job.log'), 'token': token})
        if ties:
            return None
        machine_lease.unreserve(token)
        return 'never-started'

    def dispatch_evidence(self, plan, handle):
        job = Path(handle['job_dir'])
        return any((job / name).exists() for name in (DISPATCH_MARKER, 'payload.json', 'exit.json'))

    def retrieve(self, plan, handle, staging):
        output = Path(handle['job_dir']) / 'output'
        for row in plan['spec']['outputs']:
            source = output / row['name']
            if 'destination' not in row or not source.exists():
                continue
            target = staging / row['name']
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, symlinks=True)
            else:
                shutil.copy2(source, target, follow_symlinks=False)


def launch(job, argv, argv0=None):
    """Record the launcher, fence its group, run the payload, then record its exit.

    ``argv[0]`` is the verified file to execute; ``argv0`` is the name the payload
    is invoked by (default: that file).

    The launcher records its own pid, group and start identity and fences its
    group under the machine lease it runs under before the payload starts; if
    either fails, nothing runs. The payload stays in the launcher's process group.
    payload.json names its pid and start identity so a RAVEL payload can prove its
    custody chain. Descendants still alive when the payload exits are recorded.
    """
    from ravel.workflow import machine_lease
    job = Path(job)
    me = os.getpid()
    try:
        handle = read_json(job.parent / eb.HANDLE_NAME)
        if handle.get('job_dir') != str(job) or handle.get('state') != 'dispatching' or handle.get('backend') != 'native':
            raise ValueError('the launcher runs only for a native backend handle that is dispatching this job')
        authority = handle.get('authority') or {}
        token = os.environ.get(machine_lease.JOB_ENV)
        if not token or authority.get('lease_id') != os.environ.get(machine_lease.ENV):
            raise ValueError('the launcher runs only for a job dispatched under its approved stage lease')
        # Completes the dispatcher's reservation of this token; refused when there is none.
        machine_lease.fence_inherited(os.getpgid(0), label=f"native job {handle['tag']}", token=token)
        atomic_json(job / 'launcher.json', {'pid': me, 'pgid': os.getpgid(0), 'identity': _process_identity(me),
                                            'job_token': token})
    except (OSError, ValueError, KeyError) as exc:
        print(f'native launcher: refused before the payload started: {exc}', file=sys.stderr, flush=True)
        return 125
    confined = None
    try:
        if _controller_job(job):
            confined = _confined_payload(job, argv, argv0)
            atomic_json(job / 'payload.json', {'confinement_custody_sha256': confined.record['custody_sha256']})
            # Pin the token before spawn; this file remains visible through a read-only
            # bind even after the parent atomically publishes the process identity.
            confined.reads.append(job / 'payload.json')
            from ravel.controller.confine import start
            proc = start(confined)
        else:
            proc = subprocess.Popen([argv0 or argv[0], *argv[1:]], executable=argv[0])
    except (OSError, ValueError) as exc:
        print(f'native launcher: {exc}', file=sys.stderr, flush=True)
        code = 127
    else:
        try:
            row = {'pid': proc.pid, 'identity': _process_identity(proc.pid)}
            if confined is not None:
                row['confinement_custody_sha256'] = confined.record['custody_sha256']
            atomic_json(job / 'payload.json', row)
        finally:
            code = proc.wait()
            if confined is not None:
                from ravel.controller.confine import finish
                atomic_json(job / 'confinement.json', {'launch': confined.record, 'finish': finish(proc)})
    # The ps that lists the group is itself a member while it runs; keep only pids still alive after it.
    descendants = [pid for pid in _group_members(os.getpgid(0)) if pid != me and _exists(pid)]
    record = {'exit_code': code if code >= 0 else 128 - code}
    if descendants:
        record['descendants'] = descendants
    atomic_json(job / 'exit.json', record)
    return 0


def _confined_payload(job, argv, argv0):
    """Prepare from the verified native plan and exact custody files, never ambient state."""
    from ravel.controller.confine import prepare, runs, capsule_from
    from ravel.controller.confine.environment import channels, scrub
    job = Path(job)
    plan_path = job.parent / 'plan.json'
    if not plan_path.is_file():
        raise ValueError('a confined native payload requires its pinned plan.json')
    plan = eb.load_plan(plan_path, verify_inputs=True)
    owner = runs.owner_of(job)
    reads = [str(fact['path']) for fact in [*plan.get('inputs', []), *plan.get('readonly_trees', [])]
             if isinstance(fact, dict) and fact.get('path')]
    custody_files = [job / 'payload.json', job / 'launcher.json',
                     job.parent / 'backend-handle.json', plan_path]
    if owner:
        custody_files.append(Path(owner[1]) / 'execution_state.json')
    reads += [str(path) for path in custody_files if path.is_file()]
    # Runtime values must come from the approved spec; only supervisor channels may
    # come from the current launcher. Never copy its full process environment.
    env, _ = scrub(plan['spec'].get('env', {}))
    for fact in plan.get('readonly_trees', []):
        if 'env' in fact:
            env[fact['env']] = fact['path']
    env.update({name: os.environ[name] for name in channels() if name in os.environ})
    env, _ = scrub(env)
    resources = plan['spec'].get('resources', {})
    limits = {name: resources[name] for name in ('cpus', 'wall_seconds', 'memory_mib') if name in resources}
    digests = {}
    for fact in [*plan.get('inputs', []), *plan.get('readonly_trees', [])]:
        path = Path(fact['path'])
        # Recheck the complete manifest around collecting individual-file pins; the
        # launcher captures exactly those bytes before the payload starts.
        before = eb.identity(path)
        if fact.get('sha256') is not None and before['sha256'] != fact['sha256']:
            raise ValueError(f'native input changed before confinement: {path}')
        files = sorted(p for p in path.rglob('*') if p.is_file()) if path.is_dir() else [path]
        digests.update({str(p): eb.file_sha256(p) for p in files})
        if eb.identity(path) != before:
            raise ValueError(f'native input changed while pinned: {path}')
    return prepare({'argv': [argv0 or argv[0], *argv[1:]], 'env': env, 'reads': sorted(set(reads)),
                    'input_digests': digests,
                    'writes': [str(job / 'output'), str(job / 'work')], 'cwd': str(job / 'work'),
                    'attempt_dir': str(job), 'label': 'native-backend-payload',
                    **({'controller': {'run_id': owner[0]}} if owner else {}),
                    **({'limits': limits} if limits else {})})


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    named = len(argv) > 5 and argv[3] == '--argv0'
    rest = argv[5:] if named else argv[3:]
    if len(argv) < 4 or argv[0] != 'launch' or argv[1] != '--job' or len(rest) < 2 or rest[0] != '--':
        print('usage: native launch --job DIR [--argv0 NAME] -- argv...', file=sys.stderr)
        return 2
    return launch(argv[2], rest[1:], argv[4] if named else None)


if __name__ == '__main__':
    sys.exit(main())
