"""Custody of a confined worker: the launch's secret, not its process identity.

Inside a launch sandbox a RAVEL worker cannot prove the pid-based custody chain: on Linux the
sandbox interposes its own process and gives the worker its own PID namespace, and on macOS
the profile denies signalling the supervisor and running the setuid ``ps``. The confined
launcher instead gives the launch a secret (``RAVEL_STAGE_CUSTODY``) and the supervisor
records its sha256 in the attempt record before the child starts. A process that presents a
secret whose digest is the current running attempt's has that attempt's custody; a process
that presents another secret is refused rather than tried by pid.

These records are files of the controller's user: the secret separates cooperating RAVEL
processes and confined launches from each other, not the controller from itself.
"""
from __future__ import annotations

import hmac
import math
import os
from pathlib import Path
import time

from .environment import CUSTODY
from .launcher import custody_digest


def _matches(token, expected):
    return (isinstance(token, str) and isinstance(expected, str) and len(expected) == 64
            and hmac.compare_digest(custody_digest(token), expected))


def confined_worker(rundir, stage, record=None, *, timeout=5.0):
    """The custody proof of this confined worker of ``stage``'s running attempt, or None without a secret.

    ``record`` is the attempt record when the caller has already read it; otherwise the ledger
    is read (and re-read until the supervisor has registered its child, at most ``timeout`` s).
    """
    token = os.environ.get(CUSTODY)
    if not token:
        return None
    from ravel.workflow import execution
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 5.0:
        raise ValueError('worker registration timeout must be positive and at most five seconds')
    rd = Path(rundir).resolve()
    deadline = time.monotonic() + timeout
    while True:
        current = record if record is not None else execution.load_execution(rd)['stages'].get(stage, {})
        expected = (current.get('confinement') or {}).get('custody_sha256')
        if current.get('status') != 'running' or not _matches(token, expected):
            raise ValueError('confined worker requires its current running attempt (custody secret differs)')
        # The token is delivered only to the admitted process at spawn. It was pinned in
        # this running attempt before spawn, so custody does not depend on a later PID
        # update (a read-only bind of an atomically replaced ledger keeps its old inode).
        return {'mode': 'confined', 'supervisor_pid': current.get('supervisor_pid'),
                'launcher_pid': current.get('child_pid'), 'worker_pid': os.getpid(), 'custody_sha256': expected,
                'attempt_id': current.get('attempt_id')}


def confined_payload(job):
    """True when this process presents the custody secret the native launcher recorded for ``job``'s payload."""
    from ravel.workflow.state_io import read_json
    token = os.environ.get(CUSTODY)
    path = Path(job) / 'payload.json'
    if not token or not path.is_file():
        return False
    return _matches(token, read_json(path).get('confinement_custody_sha256'))


def for_run(rundir):
    """True when this process presents the custody secret of a running attempt of ``rundir``."""
    token = os.environ.get(CUSTODY)
    if not token:
        return _broker_for_run(rundir)
    from ravel.workflow import execution
    try:
        stages = execution.load_execution(Path(rundir).resolve())['stages']
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return any(isinstance(r, dict) and r.get('status') == 'running'
               and _matches(token, (r.get('confinement') or {}).get('custody_sha256')) for r in stages.values())


def _broker_for_run(rundir):
    """A trusted broker retains the ordinary parent/child proof outside the sandbox.

    An environment marker or a registered command name alone cannot confer custody. The
    process must be the supervisor's exact registered child of that running attempt.
    """
    from ravel.workflow import execution
    from .brokers import entry_point
    deadline = time.monotonic() + 5
    while True:
        try:
            stages = execution.load_execution(Path(rundir).resolve())['stages']
        except (OSError, ValueError, KeyError, TypeError):
            return False
        pending = False
        for stage, record in stages.items():
            if (not isinstance(record, dict) or record.get('status') != 'running'
                    or record.get('supervisor_pid') != os.getppid()
                    or record.get('confinement', {}).get('class') != 'controller-side'):
                continue
            command = record.get('command')
            if not isinstance(command, list) or entry_point(rundir, command) != record['confinement']:
                continue
            if record.get('child_pid') is None:
                pending = True
                continue
            try:
                proof = execution.worker_custody(rundir, stage, record)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if proof.get('mode') == 'direct' and proof.get('worker_pid') == os.getpid():
                return True
        if not pending or time.monotonic() >= deadline:
            return False
        time.sleep(.025)
