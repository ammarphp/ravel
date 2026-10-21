"""Custody of a confined worker is its launch's secret, never its process identity.

Inside a sandbox the pid chain cannot be proven (Linux interposes the sandbox and a PID
namespace; macOS denies signalling the supervisor and the setuid ``ps``), so the supervisor
records the digest of a per-launch secret before the child starts.
"""
import json
import os
from pathlib import Path
import sys

import pytest


def ledger(run, stage='science', **record):
    from ravel.workflow import execution
    base = {'status': 'running', 'supervisor_pid': 11, 'child_pid': 12, 'attempt_id': 'a1'}
    (run / execution.STATE_NAME).write_text(json.dumps({'schema_version': 1, 'revision': 1,
                                                       'stages': {stage: {**base, **record}}}))


def test_a_worker_with_its_attempts_secret_has_custody(tmp_path, monkeypatch):
    from ravel.controller.confine import custody, custody_digest
    token = 'a' * 64
    ledger(tmp_path, confinement={'custody_sha256': custody_digest(token)})
    monkeypatch.setenv('RAVEL_STAGE_CUSTODY', token)
    proof = custody.confined_worker(tmp_path, 'science')
    assert proof['mode'] == 'confined' and proof['launcher_pid'] == 12 and proof['attempt_id'] == 'a1'
    assert custody.for_run(tmp_path) is True


def test_another_secret_or_a_finished_attempt_is_refused(tmp_path, monkeypatch):
    from ravel.controller.confine import custody, custody_digest
    token = 'b' * 64
    monkeypatch.setenv('RAVEL_STAGE_CUSTODY', 'c' * 64)
    ledger(tmp_path, confinement={'custody_sha256': custody_digest(token)})
    with pytest.raises(ValueError, match='custody secret differs'):
        custody.confined_worker(tmp_path, 'science')
    assert custody.for_run(tmp_path) is False
    monkeypatch.setenv('RAVEL_STAGE_CUSTODY', token)
    ledger(tmp_path, status='succeeded', confinement={'custody_sha256': custody_digest(token)})
    with pytest.raises(ValueError):
        custody.confined_worker(tmp_path, 'science')
    ledger(tmp_path, child_pid=None, confinement={'custody_sha256': custody_digest(token)})
    assert custody.confined_worker(tmp_path, 'science', timeout=0.1)['launcher_pid'] is None
    with pytest.raises(ValueError):
        custody.confined_worker(tmp_path, 'science', timeout=60)


def test_without_a_secret_the_ordinary_custody_chain_applies(tmp_path, monkeypatch):
    from ravel.controller.confine import custody
    monkeypatch.delenv('RAVEL_STAGE_CUSTODY', raising=False)
    assert custody.confined_worker(tmp_path, 'science') is None
    assert custody.for_run(tmp_path) is False


def test_a_confined_backend_payload_is_matched_by_the_launchers_record(tmp_path, monkeypatch):
    from ravel.controller.confine import custody, custody_digest
    job = tmp_path / 'job'
    job.mkdir()
    token = 'd' * 64
    (job / 'payload.json').write_text(json.dumps({'pid': 5, 'identity': None,
                                                 'confinement_custody_sha256': custody_digest(token)}))
    monkeypatch.setenv('RAVEL_STAGE_CUSTODY', token)
    assert custody.confined_payload(job) is True
    monkeypatch.setenv('RAVEL_STAGE_CUSTODY', 'e' * 64)
    assert custody.confined_payload(job) is False
    (job / 'payload.json').write_text(json.dumps({'pid': 5, 'identity': 'x'}))
    assert custody.confined_payload(job) is False


def test_SW41_registered_broker_requires_actual_supervisor_child_proof(tmp_path, monkeypatch):
    from ravel.controller.confine import custody, brokers
    from ravel.workflow import execution
    command = [sys.executable, '-m', 'ravel.workflow.execution_backend', 'worker']
    record = {'status': 'running', 'supervisor_pid': os.getppid(), 'child_pid': os.getpid(),
              'command': command, 'confinement': brokers.entry_point(tmp_path, command)}
    monkeypatch.delenv('RAVEL_STAGE_CUSTODY', raising=False)
    monkeypatch.setattr(execution, 'load_execution', lambda root: {'stages': {'worker': record}})
    monkeypatch.setattr(execution, 'worker_custody', lambda *a: {'mode': 'direct', 'worker_pid': os.getpid()})
    assert custody.for_run(tmp_path)
    record['command'] = [sys.executable, '-c', 'pass']
    assert not custody.for_run(tmp_path)
    record['command'] = command
    record['supervisor_pid'] = -1
    assert not custody.for_run(tmp_path)
