"""Captured facility jobs retain confinement on the execution host (T08/SW12)."""
import hashlib
import json
from pathlib import Path
import shlex
import socket
import subprocess
import sys

import pytest

from test_p05_support import FakeStore, operator, sandboxed  # noqa: F401
from test_p05_submission import controller, inert_scheduler, MAXIMA  # noqa: F401
from test_p05_capability import EXPORTS
from ravel.controller.confine import CapabilityRefused, mint_capability, verify_capability
from ravel.controller.confine import job
from ravel.workflow import wms_policy
from ravel.workflow.site_profiles import htcondor


def descriptor(tmp_path):
    script = tmp_path / 'captured.sh'
    script.write_text('exit 0\n')
    return {'schema_version': 1, 'script_path': str(script.resolve()),
            'script_sha256': hashlib.sha256(script.read_bytes()).hexdigest(),
            'reads': {}, 'output_dir': str(tmp_path.resolve() / 'outputs'),
            'resources': {'cpus': 1, 'memory_mib': 1024, 'wall_seconds': 30}}


def test_captured_job_digest_drift_refuses_before_output_creation(tmp_path):
    document = descriptor(tmp_path)
    Path(document['script_path']).write_text('changed\n')
    with pytest.raises(ValueError, match='digest changed'):
        job.run(document)
    assert not Path(document['output_dir']).exists()


def test_captured_job_never_uses_operator_unconfined_fallback(tmp_path, monkeypatch):
    from ravel.controller import confine
    document = descriptor(tmp_path)
    monkeypatch.setattr(confine, 'prepare', lambda spec: type('Plan', (), {'kind': confine.UNCONFINED})())
    monkeypatch.setattr(confine, 'start', lambda *a, **kw: pytest.fail('unconfined payload started'))
    with pytest.raises(confine.LaunchHeld, match='never run unconfined'):
        job.run(document)
    assert not Path(document['output_dir']).exists()


def test_job_input_files_are_pinned_at_mint_and_drift_refuses(tmp_path):
    workflow = tmp_path / 'workflow'
    workflow.mkdir()
    script = workflow / 'script.sh'
    script.write_text('# properties = {"rule": "task_alpha"}\nexit 0\n')
    source = tmp_path / 'data.txt'
    source.write_text('approved\n')
    store = FakeStore('run-input', root=tmp_path / 'store')
    token = mint_capability(store, 'launch-input', {'workflow_dir': str(workflow), 'reads': [str(source)]})
    admitted = verify_capability(token, script, store=store)
    assert admitted['input_digests'] == {str(source): hashlib.sha256(source.read_bytes()).hexdigest()}
    source.write_text('changed\n')
    with pytest.raises(CapabilityRefused, match='changed after minting'):
        verify_capability(token, script, store=store)
    assert len(store.scan('wms-submission')) == 1


@pytest.mark.parametrize('kind', ['directory', 'symlink', 'hardlink', 'relative', 'store'])
def test_declared_job_reads_never_grant_directories_links_or_store(tmp_path, kind):
    workflow = tmp_path / 'workflow'
    workflow.mkdir()
    store = FakeStore('run-input', root=tmp_path / 'store')
    source = tmp_path / 'data'
    source.write_text('data')
    candidate = source
    if kind == 'directory':
        candidate = workflow
    elif kind == 'symlink':
        candidate = tmp_path / 'alias'
        candidate.symlink_to(source)
    elif kind == 'hardlink':
        import os
        candidate = tmp_path / 'hardlink'
        os.link(source, candidate)
    elif kind == 'relative':
        candidate = Path('relative')
    elif kind == 'store':
        candidate = store.path('secret')
        candidate.write_text('secret')
    with pytest.raises(ValueError):
        mint_capability(store, 'launch-input', {'workflow_dir': str(workflow), 'reads': [str(candidate)]})
    assert store.scan('wms-capability') == []


def test_linux_scheduler_wrapper_confines_hostile_payload_to_output(
        tmp_path, monkeypatch, inert_scheduler, sandboxed):
    if sys.platform != 'linux':
        pytest.skip('Linux execution-host qualification control')
    workflow, script, profile, store = controller(tmp_path, monkeypatch)
    operator(monkeypatch, {'store_root': str(store.path().parent)})
    store.append('journal', {'preserve': True})
    store_file = store.path('journal.jsonl')
    outside = tmp_path / 'outside.txt'
    outside.write_text('original')
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    listener.settimeout(.2)
    port = listener.getsockname()[1]
    source = f'''
import json, os, pathlib, socket
result = {{}}
def attempt(name, action):
    try:
        action()
        result[name] = 'ALLOWED'
    except OSError:
        result[name] = 'denied'
attempt('outside', lambda: pathlib.Path({str(outside)!r}).write_text('hostile'))
attempt('store_write', lambda: pathlib.Path({str(store_file)!r}).write_text('hostile'))
attempt('store_read', lambda: pathlib.Path({str(store_file)!r}).read_text())
def connect():
    with socket.socket() as channel:
        channel.settimeout(1)
        channel.connect(('127.0.0.1', {port}))
attempt('socket', connect)
output = pathlib.Path(os.environ['RAVEL_OUTPUT_DIR'])
(output / 'positive.txt').write_text('approved output')
(output / 'result.json').write_text(json.dumps(result))
'''
    script.write_text('#!/bin/sh\n# properties = ' + json.dumps({'rule': 'task_alpha', 'threads': 1}) +
                      '\nexec ' + shlex.quote(sys.executable) + " -I - <<'PYCODE'\n" + source + '\nPYCODE\n')
    token = mint_capability(store, 'launch-hostile', {'workflow_dir': str(workflow), 'tasks': ['alpha'],
                                                     'max_jobs': 1, 'resource_maxima': MAXIMA})
    try:
        with wms_policy.launch_authorization(workflow, 'alpha', 1, EXPORTS,
                                             capability=token, controller_run=store.run_id):
            assert htcondor.submit_main(['--profile', str(profile), str(script)]) == 0
        call = inert_scheduler()[0]
        done = subprocess.run(['/bin/sh', call['wrapper_path']], capture_output=True, text=True, timeout=90)
        assert done.returncode == 0, done.stderr
        output = Path(call['job']['output_dir'])
        assert json.loads((output / 'result.json').read_text()) == {
            'outside': 'denied', 'store_write': 'denied', 'store_read': 'denied', 'socket': 'denied'}
        assert (output / 'positive.txt').read_text() == 'approved output'
        assert outside.read_text() == 'original'
        assert store.scan('journal')[0]['record'] == {'preserve': True}
        receipt = json.loads((output / 'receipt.json').read_text())
        assert receipt['exit_code'] == 0 and receipt['confinement']['kind'] == 'confined'
        assert receipt['confinement']['network'] == 'none'
        assert receipt['confinement']['declared_outputs'] == [str(output)]
        assert str(store.path()) not in json.dumps(receipt)
        with pytest.raises(socket.timeout):
            listener.accept()
    finally:
        listener.close()
