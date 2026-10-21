"""T08/SW12: controller CLI schedules only captured bytes through an inert scheduler.

These controls establish local software custody. A real site's shared filesystem and
worker read-only mounts need independent qualification; no remote jobs are launched.
"""
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from test_p05_support import own
from test_p05_capability import setup, EXPORTS
from ravel.controller.confine import CapabilityRefused, mint_capability, verify_capability
from ravel.workflow import wms_policy
from ravel.workflow.site_profiles import htcondor

MAXIMA = {'threads': 1, 'mem_mb': 1024, 'runtime': 60}


@pytest.fixture
def inert_scheduler(tmp_path, monkeypatch):
    folder = tmp_path / 'bin'
    folder.mkdir()
    calls = tmp_path / 'scheduled.jsonl'
    executable = folder / 'condor_submit'
    executable.write_text(f'''#!{sys.executable}
import json, os, pathlib, shlex, sys
text = pathlib.Path(sys.argv[-1]).read_text()
argument = next(line.split(' = ', 1)[1] for line in text.splitlines() if line.startswith('arguments = '))
script = pathlib.Path(shlex.split(shlex.split(argument)[0])[0])
wrapper = script.read_text()
job_descriptor = pathlib.Path(shlex.split(wrapper.splitlines()[1])[-1])
job = json.loads(job_descriptor.read_text())
payload = pathlib.Path(job['script_path'])
record = {{'argv': sys.argv, 'descriptor': text, 'wrapper_path': str(script), 'wrapper': wrapper,
          'script_path': str(payload), 'job': job, 'job_descriptor': str(job_descriptor),
          'script': payload.read_text(), 'secret_present': 'RAVEL_WMS_CAPABILITY' in os.environ}}
with open({str(calls)!r}, 'a') as stream:
    stream.write(json.dumps(record) + '\\n')
print('12.0')
''')
    executable.chmod(0o755)
    monkeypatch.setenv('PATH', str(folder) + os.pathsep + os.environ['PATH'])
    monkeypatch.delenv(wms_policy.CAPABILITY_ENV, raising=False)
    return lambda: [json.loads(row) for row in calls.read_text().splitlines()] if calls.exists() else []


def controller(tmp_path, monkeypatch):
    workflow, script, profile = setup(tmp_path)
    run = tmp_path / 'run'
    run.mkdir()
    store = own(monkeypatch, tmp_path / 'store', {run: 'run-submit'})['run-submit']
    return workflow, script, profile, store


def test_T08_SW12_controller_cli_submits_one_captured_script_and_no_store_or_secret(
        tmp_path, monkeypatch, inert_scheduler, capsys):
    from ravel.controller import confine
    workflow, script, profile, store = controller(tmp_path, monkeypatch)
    captured = script.read_bytes()
    token = mint_capability(store, 'launch-one', {
        'workflow_dir': str(workflow), 'tasks': ['alpha'], 'rules': ['task_alpha'],
        'max_jobs': 1, 'resource_maxima': MAXIMA,
        'jobscript_sha256': hashlib.sha256(captured).hexdigest()})
    verify = confine.verify_capability

    def mutate_after_verification(*args, **kwargs):
        admitted = verify(*args, **kwargs)
        script.write_text('#!/bin/sh\n# properties = {"rule": "task_beta", "threads": 900}\nexit 99\n')
        return admitted

    monkeypatch.setattr(confine, 'verify_capability', mutate_after_verification)
    with wms_policy.launch_authorization(workflow, 'alpha', 1, EXPORTS,
                                         capability=token, controller_run=store.run_id):
        assert htcondor.submit_main(['--profile', str(profile), str(script)]) == 0
        with pytest.raises(SystemExit):
            htcondor.submit_main(['--profile', str(profile), str(script)])
    assert len(inert_scheduler()) == 1
    call = inert_scheduler()[0]
    published = Path(call['script_path'])
    assert call['script'].encode() == captured
    assert not published.is_relative_to(store.path()) and not published.is_relative_to(workflow)
    assert published.stat().st_nlink == 1 and published.stat().st_mode & 0o777 == 0o400
    assert published.parent.stat().st_mode & 0o777 == 0o500
    assert published.parent.parent.stat().st_mode & 0o777 == 0o700
    assert not call['secret_present']
    assert str(store.path()) not in call['descriptor']
    output = capsys.readouterr()
    assert token not in json.dumps(call) + output.out + output.err
    rows = store.scan('wms-submission')
    assert len(rows) == 1 and rows[0]['record']['jobscript_sha256'] == hashlib.sha256(captured).hexdigest()
    receipt = next(workflow.rglob('script.json'))
    record = json.loads(receipt.read_text())
    assert record['captured_script_path'] == str(published)
    assert record['path'] == call['wrapper_path']
    assert ' -I ' in call['wrapper'] and 'ravel.controller.confine.job' in call['wrapper']
    assert call['job']['reads'] == {}
    assert call['job']['resources'] == {'cpus': 1, 'memory_mib': 1024, 'wall_seconds': 3600}
    assert Path(call['job']['output_dir']).is_relative_to(workflow / '.ravel-job-output')
    assert token not in receipt.read_text()


@pytest.mark.parametrize('drift', ['digest', 'resource', 'profile'])
def test_T08_SW12_controller_cli_drift_refuses_before_scheduler(tmp_path, monkeypatch, inert_scheduler, drift):
    workflow, script, profile, store = controller(tmp_path, monkeypatch)
    scope = {'workflow_dir': str(workflow), 'tasks': ['alpha'], 'resource_maxima': MAXIMA}
    if drift == 'digest':
        scope['jobscript_sha256'] = '0' * 64
    elif drift == 'resource':
        document = json.loads(profile.read_text())
        document['options']['mem_mb'] = 1025
        profile.write_text(json.dumps(document))
    else:
        scope['profile_sha256'] = '0' * 64
    token = mint_capability(store, 'launch-drift', scope)
    with wms_policy.launch_authorization(workflow, 'alpha', 1, EXPORTS,
                                         capability=token, controller_run=store.run_id):
        with pytest.raises(SystemExit):
            htcondor.submit_main(['--profile', str(profile), str(script)])
    assert inert_scheduler() == [] and store.scan('wms-submission') == []
    assert not (tmp_path / '.ravel-controller-submissions').exists()


def test_T08_SW12_controller_cli_without_authorization_has_zero_effects(tmp_path, monkeypatch, inert_scheduler):
    workflow, script, profile, store = controller(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        htcondor.submit_main(['--profile', str(profile), str(script)])
    assert inert_scheduler() == [] and store.scan('wms-submission') == []
    assert list(workflow.rglob('submit-*')) == []


def test_T08_SW12_controller_launch_adapter_mints_and_revokes_and_never_downgrades(tmp_path, monkeypatch):
    workflow, script, _, store = controller(tmp_path, monkeypatch)
    # The actual project's index associates the workflow with its controller-owned run.
    run = tmp_path / 'run'
    (workflow / 'index.json').write_text(json.dumps({'tasks': [{'id': 'alpha', 'rundir': str(run)}]}))
    with pytest.raises(ValueError, match='controller-owned workflow'):
        with wms_policy.launch_authorization(workflow, 'alpha', 1, EXPORTS):
            pytest.fail('no controller scope supplied')
    with pytest.raises(ValueError, match='resource_maxima'):
        with wms_policy.launch_authorization(workflow, 'alpha', 1, EXPORTS,
                                             capability_scope={'max_jobs': 1}):
            pytest.fail('no approved resources supplied')
    with wms_policy.launch_authorization(workflow, 'alpha', 1, EXPORTS,
                                         capability_scope={'max_jobs': 1, 'resource_maxima': MAXIMA}) as live:
        token = os.environ[wms_policy.CAPABILITY_ENV]
        assert token.startswith('rwc1.run-submit.wms-alpha-000001.')
        assert token not in Path(live).read_text()
        assert verify_capability(token, script)['launch_id'] == 'wms-alpha-000001'
    with pytest.raises(CapabilityRefused, match='revoked'):
        verify_capability(token, script)
    assert len(store.scan('wms-capability')) == 1


def test_T08_SW12_controller_adapter_revokes_even_when_executor_raises(tmp_path, monkeypatch):
    workflow, script, _, store = controller(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match='executor failed'):
        with wms_policy.launch_authorization(workflow, 'alpha', 1, EXPORTS, controller_run=store.run_id,
                                             capability_scope={'max_jobs': 1, 'resource_maxima': MAXIMA}):
            token = os.environ[wms_policy.CAPABILITY_ENV]
            raise RuntimeError('executor failed')
    with pytest.raises(CapabilityRefused, match='revoked'):
        verify_capability(token, script)


def test_T08_SW12_changed_private_snapshot_refuses_before_scheduler(tmp_path, monkeypatch, inert_scheduler):
    workflow, script, profile, store = controller(tmp_path, monkeypatch)
    token = mint_capability(store, 'launch-snapshot', {'workflow_dir': str(workflow), 'tasks': ['alpha']})
    with wms_policy.launch_authorization(workflow, 'alpha', 1, EXPORTS,
                                         capability=token, controller_run=store.run_id):
        admitted = htcondor.bind_submission(script, json.loads(profile.read_text()), profile)
        snapshot = Path(admitted['admission']['snapshot_path'])
        snapshot.chmod(0o600)  # Simulate trusted-side corruption, outside worker permissions.
        snapshot.write_text('different bytes\n')
        snapshot.chmod(0o400)
        with pytest.raises(ValueError, match='digest changed'):
            htcondor.submit(script, profile=json.loads(profile.read_text()), _admission=admitted)
    assert inert_scheduler() == []


def test_T08_SW12_submission_publication_refuses_a_symlink(tmp_path, monkeypatch, inert_scheduler):
    workflow, script, profile, store = controller(tmp_path, monkeypatch)
    destination = tmp_path / 'untrusted'
    destination.mkdir(mode=0o700)
    (tmp_path / '.ravel-controller-submissions').symlink_to(destination, target_is_directory=True)
    token = mint_capability(store, 'launch-link', {'workflow_dir': str(workflow), 'tasks': ['alpha']})
    with wms_policy.launch_authorization(workflow, 'alpha', 1, EXPORTS,
                                         capability=token, controller_run=store.run_id):
        with pytest.raises(SystemExit):
            htcondor.submit_main(['--profile', str(profile), str(script)])
    assert inert_scheduler() == [] and list(destination.iterdir()) == []


def test_T08_SW12_direct_python_submit_of_controller_index_cannot_use_legacy_bypass(
        tmp_path, monkeypatch, inert_scheduler):
    workflow, script, profile, store = controller(tmp_path, monkeypatch)
    (workflow / 'index.json').write_text(json.dumps({'tasks': [
        {'id': 'alpha', 'rundir': str(tmp_path / 'run')}]}))
    with pytest.raises(ValueError, match='no launch capability'):
        htcondor.submit(script, profile=json.loads(profile.read_text()))
    assert inert_scheduler() == [] and store.scan('wms-submission') == []
