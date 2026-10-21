"""The ordinary custody entry points accept a confined worker's secret (integration fragment of P05).

``execution.await_worker_registration`` and ``execution.worker_custody`` are outside P05's
paths; ``tests/fixtures/peer_contracts/execution-custody.patch`` carries their exact change. The fixture applies only the delivered execution.py hunks to an in-memory module;
no production source is edited. Native hooks use the current source unchanged.
"""
import json
from pathlib import Path
import re
import sys
import types

import pytest

from ravel.workflow import execution

def _apply_execution_fragment(source, fragment):
    """Apply only execution.py hunks, requiring unique exact old text and valid counts."""
    files = re.split(r'(?=^diff --git )', fragment, flags=re.MULTILINE)
    selected = [part for part in files if part.startswith(
        'diff --git a/src/ravel/workflow/execution.py b/src/ravel/workflow/execution.py\n')]
    if len(selected) != 1:
        raise ValueError('F1 must contain exactly one execution.py diff')
    lines = selected[0].splitlines(keepends=True)
    if lines[1:3] != ['--- a/src/ravel/workflow/execution.py\n',
                      '+++ b/src/ravel/workflow/execution.py\n']:
        raise ValueError('execution.py diff has unexpected file headers')
    index, hunks = 3, 0
    while index < len(lines):
        header = re.fullmatch(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n?', lines[index])
        if header is None:
            raise ValueError('invalid execution.py unified hunk header')
        old_count = int(header[2] or 1)
        new_count = int(header[4] or 1)
        index += 1
        before, after = [], []
        while index < len(lines) and not lines[index].startswith('@@ '):
            line = lines[index]
            if not line or line[0] not in ' +-':
                raise ValueError('invalid execution.py unified hunk body')
            if line[0] in ' -':
                before.append(line[1:])
            if line[0] in ' +':
                after.append(line[1:])
            index += 1
        if len(before) != old_count or len(after) != new_count or not before:
            raise ValueError('execution.py unified hunk counts do not match')
        old_text = ''.join(before)
        if source.count(old_text) != 1:
            raise ValueError('execution.py old hunk must match exactly once')
        source = source.replace(old_text, ''.join(after), 1)
        hunks += 1
    if hunks == 0:
        raise ValueError('execution.py fragment contains no hunks')
    return source, hunks


@pytest.fixture(autouse=True)
def execution_custody_fragment(monkeypatch):
    """Exercise exact F1 delivery without changing unowned production source files."""
    from ravel import workflow
    real_execution = execution
    path = Path(real_execution.__file__)
    source = path.read_text()
    native = 'CONFINED_CUSTODY_ENV' in source
    hunks = 0
    if not native:
        repository = Path(__file__).resolve().parents[3]
        fragment = (repository / 'tests/fixtures/peer_contracts/execution-custody.patch').read_text()
        source, hunks = _apply_execution_fragment(source, fragment)
    patched = types.ModuleType(real_execution.__name__)
    patched.__file__ = real_execution.__file__
    patched.__package__ = real_execution.__package__
    monkeypatch.setitem(sys.modules, real_execution.__name__, patched)
    monkeypatch.setattr(workflow, 'execution', patched)
    monkeypatch.setattr(sys.modules[__name__], 'execution', patched)
    exec(compile(source, patched.__file__, 'exec'), patched.__dict__)
    return {'native_hook': native, 'applied_hunks': hunks, 'module': patched}


def test_exact_fragment_applied_or_native_hook_present(execution_custody_fragment):
    evidence = execution_custody_fragment
    assert evidence['native_hook'] or evidence['applied_hunks'] > 0
    assert execution is evidence['module']
    assert execution is sys.modules['ravel.workflow.execution']
    from ravel import workflow
    assert workflow.execution is execution
    assert execution.CONFINED_CUSTODY_ENV == 'RAVEL_STAGE_CUSTODY'


def ledger(run, **record):
    base = {'status': 'running', 'supervisor_pid': 11, 'child_pid': 12, 'attempt_id': 'a1'}
    (run / execution.STATE_NAME).write_text(json.dumps({'schema_version': 1, 'revision': 1,
                                                       'stages': {'science': {**base, **record}}}))


def test_SW36_confined_registration_and_custody_take_secret_and_refuse_another(tmp_path, monkeypatch):
    from ravel.controller.confine import custody_digest
    token = 'a' * 64
    ledger(tmp_path, confinement={'custody_sha256': custody_digest(token)})
    monkeypatch.delenv(execution.BACKEND_JOB_ENV, raising=False)
    monkeypatch.setenv(execution.CONFINED_CUSTODY_ENV, token)
    assert execution.await_worker_registration(tmp_path, 'science')['mode'] == 'confined'
    assert execution.worker_custody(tmp_path, 'science')['mode'] == 'confined'
    monkeypatch.setenv(execution.CONFINED_CUSTODY_ENV, 'b' * 64)
    with pytest.raises(ValueError):
        execution.await_worker_registration(tmp_path, 'science')
    with pytest.raises(ValueError):
        execution.worker_custody(tmp_path, 'science')


def test_without_a_secret_the_pid_chain_still_decides(tmp_path, monkeypatch):
    ledger(tmp_path)
    monkeypatch.delenv(execution.CONFINED_CUSTODY_ENV, raising=False)
    monkeypatch.delenv(execution.BACKEND_JOB_ENV, raising=False)
    with pytest.raises(ValueError):
        execution.worker_custody(tmp_path, 'science')


def test_SW36_backend_custody_uses_pre_spawn_ack_and_frozen_dispatch_record(tmp_path, monkeypatch):
    from ravel.controller.confine import custody_digest
    token = 'c' * 64
    job = tmp_path / 'logs/execution/science/a1/backend/job'
    job.mkdir(parents=True)
    plan = job.parent / 'plan.json'
    plan.write_text(json.dumps({'plan_sha256': 'pinned-plan'}))
    digest = execution.file_hash(plan)
    (job.parent / 'backend-handle.json').write_text(json.dumps({
        'backend': 'native', 'job_dir': str(job), 'state': 'dispatching',
        'plan_file_sha256': digest, 'plan_sha256': 'pinned-plan'}))
    (job / 'payload.json').write_text(json.dumps({'confinement_custody_sha256': custody_digest(token)}))
    ledger(tmp_path, input_snapshot={str(plan): {'kind': 'file', 'files': [{'sha256': digest}]}},
           confinement={'custody_sha256': custody_digest('outer-launch')})
    monkeypatch.setattr(execution, 'process_identity', lambda pid: None)
    monkeypatch.setenv(execution.CONFINED_CUSTODY_ENV, token)
    monkeypatch.setenv(execution.BACKEND_JOB_ENV, str(job))
    result = execution.worker_custody(tmp_path, 'science')
    assert result['mode'] == 'backend' and result['confined'] is True
    assert result['launcher_pid'] is None
    monkeypatch.setenv(execution.CONFINED_CUSTODY_ENV, 'wrong')
    with pytest.raises(ValueError, match='did not acknowledge'):
        execution.worker_custody(tmp_path, 'science')
