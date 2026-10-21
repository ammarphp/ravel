"""Facility submission needs the per-launch capability of a live governed launch (SW12, T08).

The scheduler is an inert ``condor_submit`` stub on ``PATH`` whose call log is the effect
counter; no real submission is ever made.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from test_p05_support import FakeStore, own

from ravel.workflow import wms_policy
from ravel.workflow.site_profiles import render


@pytest.fixture
def scheduler(tmp_path, monkeypatch):
    folder = tmp_path / 'bin'
    folder.mkdir()
    calls = tmp_path / 'condor-calls.jsonl'
    tool = folder / 'condor_submit'
    tool.write_text(f'#!{sys.executable}\nimport json, sys\n'
                    f'open({str(calls)!r}, "a").write(json.dumps(sys.argv) + "\\n")\nprint("12.0")\n')
    tool.chmod(0o755)
    monkeypatch.setenv('PATH', str(folder) + os.pathsep + os.environ['PATH'])
    monkeypatch.delenv(wms_policy.CAPABILITY_ENV, raising=False)
    return lambda: [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []


def setup(tmp_path, rule='task_alpha', name='job.sh'):
    workflow = tmp_path / 'workflow'
    workflow.mkdir(exist_ok=True)
    (workflow / 'run-keys.json').write_text(json.dumps({'alpha': '012abc', 'beta': '345def'}))
    script = workflow / name
    script.write_text('#!/bin/sh\n# properties = ' + json.dumps({'threads': 1, 'rule': rule}) + '\nexit 0\n')
    profile = render('htcondor', project_id='project-a', options={'workflow_dir': str(workflow)})
    profile_path = tmp_path / 'profile.json'
    profile_path.write_text(json.dumps(profile))
    return workflow, script, profile_path


def console(script, profile_path):
    code = ('import sys\nfrom ravel.workflow.site_profiles.htcondor import submit_main\n'
            'raise SystemExit(submit_main(sys.argv[1:]))\n')
    return subprocess.run([sys.executable, '-c', code, '--profile', str(profile_path), str(script)],
                          capture_output=True, text=True, timeout=120, env=dict(os.environ))


def submissions(workflow):
    return sorted(p.name for p in workflow.rglob('submit-*'))


EXPORTS = {'alpha': 'a' * 64}


def test_a_direct_invocation_without_a_capability_submits_nothing(tmp_path, scheduler):
    workflow, script, profile_path = setup(tmp_path)
    done = console(script, profile_path)
    assert done.returncode == 1 and 'no launch capability was presented' in done.stderr
    assert scheduler() == [] and submissions(workflow) == []
    module = subprocess.run([sys.executable, '-m', 'ravel.workflow.site_profiles.htcondor', 'submit',
                             '--profile', str(profile_path), str(script)], capture_output=True, text=True, timeout=120)
    assert module.returncode == 1 and scheduler() == []


def test_a_child_of_the_governed_launch_submits_exactly_its_approved_job(tmp_path, scheduler):
    workflow, script, profile_path = setup(tmp_path)
    with wms_policy.launch_authorization(workflow, 'alpha', 1, EXPORTS) as record:
        assert wms_policy.CAPABILITY_ENV in os.environ
        live = json.loads(Path(record).read_text())
        assert os.environ[wms_policy.CAPABILITY_ENV] not in json.dumps(live), 'the record keeps only the digest'
        done = console(script, profile_path)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == '12.0' and len(scheduler()) == 1
    assert wms_policy.CAPABILITY_ENV not in os.environ, 'the capability ends with its launch'


def test_a_stolen_capability_outside_the_launch_process_tree_submits_nothing(tmp_path, scheduler, monkeypatch):
    workflow, script, profile_path = setup(tmp_path)
    holder = subprocess.Popen([sys.executable, '-c',
                               'import os, sys, time\nfrom pathlib import Path\nfrom ravel.workflow import wms_policy\n'
                               'with wms_policy.launch_authorization(Path(sys.argv[1]), "alpha", 1, {"alpha": "a" * 64}):\n'
                               '    print(os.environ[wms_policy.CAPABILITY_ENV], flush=True)\n    time.sleep(120)\n',
                               str(workflow)], stdout=subprocess.PIPE, text=True)
    try:
        token = holder.stdout.readline().strip()
        monkeypatch.setenv(wms_policy.CAPABILITY_ENV, token)
        done = console(script, profile_path)
        assert done.returncode == 1 and 'descends from' in done.stderr
        assert scheduler() == [] and submissions(workflow) == []
    finally:
        holder.kill()
        holder.wait()


def test_a_capability_whose_launch_ended_or_another_workflow_submits_nothing(tmp_path, scheduler, monkeypatch):
    workflow, script, profile_path = setup(tmp_path)
    with wms_policy.launch_authorization(workflow, 'alpha', 1, EXPORTS):
        token = os.environ[wms_policy.CAPABILITY_ENV]
    monkeypatch.setenv(wms_policy.CAPABILITY_ENV, token)
    assert console(script, profile_path).returncode == 1
    monkeypatch.delenv(wms_policy.CAPABILITY_ENV)
    other = tmp_path / 'other-workflow'
    other.mkdir()
    with wms_policy.launch_authorization(other, 'alpha', 1, EXPORTS):
        done = console(script, profile_path)
    assert done.returncode == 1 and scheduler() == [] and submissions(workflow) == []


def test_a_job_of_a_task_outside_the_launch_submits_nothing(tmp_path, scheduler):
    workflow, script, profile_path = setup(tmp_path, rule='task_beta')
    with wms_policy.launch_authorization(workflow, 'alpha', 1, EXPORTS):
        done = console(script, profile_path)
    assert done.returncode == 1 and "task 'beta'" in done.stderr
    assert scheduler() == [] and submissions(workflow) == []


def test_a_changed_site_profile_after_the_launch_froze_it_submits_nothing(tmp_path, scheduler):
    from ravel.workflow import wms_site
    workflow, script, _ = setup(tmp_path)
    folder = tmp_path / 'frozen' / 'htcondor'
    folder.mkdir(parents=True)
    profile = render('htcondor', project_id='project-a', options={'workflow_dir': str(workflow)})
    (folder / 'profile.json').write_text(json.dumps(profile))
    (folder / 'config.yaml').write_text('jobs: 1\n')
    for name in ('ravel-submit.sh', 'ravel-status.sh'):
        (folder / name).write_text('#!/bin/sh\n')
        (folder / name).chmod(0o755)
    pin = wms_site.profile_pin(folder)
    with wms_policy.launch_authorization(workflow, 'alpha', 1, EXPORTS, site_profile=pin):
        assert console(script, folder / 'profile.json').returncode == 0
        (folder / 'config.yaml').write_text('jobs: 1000\n')
        done = console(script, folder / 'profile.json')
    assert done.returncode == 1 and 'frozen site profile' in done.stderr
    assert len(scheduler()) == 1


def test_a_controller_capability_is_checked_against_the_run_store(tmp_path, scheduler, monkeypatch):
    from ravel.controller.confine import CapabilityRefused, mint_capability, revoke_capability, verify_capability
    workflow, script, profile_path = setup(tmp_path)
    run = tmp_path / 'run'
    run.mkdir()
    stores = own(monkeypatch, tmp_path / 'store', {run: 'run-cap'})
    store = stores['run-cap']
    token = mint_capability(store, 'launch-1', {'workflow_dir': str(workflow), 'tasks': ['alpha'],
                                                'rules': ['task_alpha'], 'max_jobs': 1})
    assert token.startswith('rwc1.run-cap.launch-1.')
    stored = json.dumps(store.scan('wms-capability'))
    assert token not in stored and 'launch-1' in stored
    admitted = verify_capability(token, script, task='alpha')
    assert admitted['rule'] == 'task_alpha' and admitted['submissions'] == 1
    with pytest.raises(CapabilityRefused, match='admits 1 job'):
        verify_capability(token, script, task='alpha')
    for bad in ('', 'rwc1.run-cap.launch-1.' + 'x' * 43, token.replace('launch-1', 'launch-2')):
        with pytest.raises(CapabilityRefused):
            verify_capability(bad, script)
    second = mint_capability(store, 'launch-2', {'workflow_dir': str(workflow), 'rules': ['task_alpha']})
    other_rule = setup(tmp_path, rule='task_beta', name='beta.sh')[1]
    with pytest.raises(CapabilityRefused, match='outside the capability'):
        verify_capability(second, other_rule)
    outside = tmp_path / 'elsewhere.sh'
    outside.write_text(script.read_text())
    with pytest.raises(CapabilityRefused, match='outside the capability workflow'):
        verify_capability(second, outside)
    revoke_capability(store, 'launch-2')
    with pytest.raises(CapabilityRefused, match='revoked'):
        verify_capability(second, script)
    # A controller launch passes its minted token and run id; the submit gate then also asks the store.
    from ravel.workflow.site_profiles import htcondor
    third = mint_capability(store, 'launch-3', {'workflow_dir': str(workflow), 'tasks': ['alpha']})
    with wms_policy.launch_authorization(workflow, 'alpha', 1, EXPORTS, capability=third, controller_run='run-cap'):
        record = htcondor.bind_submission(script, json.loads(profile_path.read_text()), profile_path)
        assert record['controller_run'] == 'run-cap'
        # A submitter that cannot read the run's store (here: a child without it) submits nothing.
        done = console(script, profile_path)
        assert done.returncode == 1 and 'the capability is not one this run minted' in done.stderr
    assert scheduler() == []
    assert [row['record']['task'] for row in store.scan('wms-submission')] == ['alpha', 'alpha']
    with pytest.raises(ValueError):
        with wms_policy.launch_authorization(workflow, 'alpha', 2, EXPORTS, capability=third):
            pass


def test_mint_refuses_scopes_and_stores_it_cannot_bind(tmp_path):
    from ravel.controller.confine import mint_capability
    store = FakeStore('run-x', root=tmp_path / 'store')
    for scope in ({}, {'workflow_dir': 'relative'}, {'workflow_dir': str(tmp_path), 'max_jobs': 0},
                  {'workflow_dir': str(tmp_path), 'extra': 1}, {'workflow_dir': str(tmp_path), 'rules': 'task_a'}):
        with pytest.raises(ValueError):
            mint_capability(store, 'launch-1', scope)
    with pytest.raises(ValueError):
        mint_capability(object(), 'launch-1', {'workflow_dir': str(tmp_path)})
    with pytest.raises(ValueError):
        mint_capability(store, 'bad id', {'workflow_dir': str(tmp_path)})
    # The store never lies in (or holds) the workflow its batch jobs read from the shared filesystem.
    with pytest.raises(ValueError, match='overlaps the workflow'):
        mint_capability(store, 'launch-1', {'workflow_dir': str(tmp_path)})
    inside = FakeStore('run-y', root=tmp_path / 'workflow' / '.store')
    with pytest.raises(ValueError, match='overlaps the workflow'):
        mint_capability(inside, 'launch-1', {'workflow_dir': str(tmp_path / 'workflow')})
    assert store.scan('wms-capability') == [] and inside.scan('wms-capability') == []


def test_a_capability_bound_to_a_site_profile_refuses_any_other_profile(tmp_path, scheduler, monkeypatch):
    from ravel.controller.confine import CapabilityRefused, mint_capability, verify_capability
    from ravel.workflow import wms_site
    from ravel.workflow.site_profiles import htcondor
    workflow, script, _ = setup(tmp_path)
    folder = tmp_path / 'frozen' / 'htcondor'
    folder.mkdir(parents=True)
    profile = render('htcondor', project_id='project-a', options={'workflow_dir': str(workflow)})
    (folder / 'profile.json').write_text(json.dumps(profile))
    (folder / 'config.yaml').write_text('jobs: 1\n')
    for name in ('ravel-submit.sh', 'ravel-status.sh'):
        (folder / name).write_text('#!/bin/sh\n')
        (folder / name).chmod(0o755)
    pin = wms_site.profile_pin(folder)
    run = tmp_path / 'run'
    run.mkdir()
    store = own(monkeypatch, tmp_path / 'store', {run: 'run-profile'})['run-profile']
    token = mint_capability(store, 'launch-p', {'workflow_dir': str(workflow), 'profile_sha256': pin['sha256']})
    with pytest.raises(CapabilityRefused, match='site profile differs'):
        verify_capability(token, script)
    with pytest.raises(CapabilityRefused, match='site profile differs'):
        verify_capability(token, script, profile_sha256='0' * 64)
    assert verify_capability(token, script, profile_sha256=pin['sha256'])['launch_id'] == 'launch-p'
    # Through the submit gate: a profile changed after minting refuses by digest.
    with wms_policy.launch_authorization(workflow, 'alpha', 1, EXPORTS, capability=token, controller_run='run-profile'):
        assert htcondor.bind_submission(script, profile, folder / 'profile.json')['controller_run'] == 'run-profile'
        (folder / 'config.yaml').write_text('jobs: 1000\n')
        with pytest.raises(CapabilityRefused, match='site profile differs'):
            htcondor.bind_submission(script, profile, folder / 'profile.json')
    assert scheduler() == []


def test_a_profile_without_a_project_admits_only_jobs_whose_rule_names_a_launch_task(tmp_path, scheduler):
    from ravel.workflow.site_profiles import htcondor
    workflow, script, _ = setup(tmp_path)
    options = {'options': render('htcondor', project_id='project-a', options={'workflow_dir': str(workflow)})['options']}
    other = setup(tmp_path, rule='task_beta', name='beta.sh')[1]
    unnamed = setup(tmp_path, rule='summary', name='summary.sh')[1]
    with wms_policy.launch_authorization(workflow, 'alpha', 1, EXPORTS):
        assert htcondor.bind_submission(script, options)['task'] == 'alpha'
        for job in (other, unnamed):
            with pytest.raises(ValueError, match='outside the live launch'):
                htcondor.bind_submission(job, options)
    assert scheduler() == []


def test_T08_SW12_symlink_parent_escape_and_workflow_alias_are_refused(tmp_path):
    from ravel.controller.confine import CapabilityRefused, mint_capability, verify_capability
    workflow, script, _ = setup(tmp_path)
    store = FakeStore('run-links', root=tmp_path / 'store')
    token = mint_capability(store, 'launch-links', {'workflow_dir': str(workflow)})
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'job.sh').write_bytes(script.read_bytes())
    (workflow / 'escape').symlink_to(outside, target_is_directory=True)
    alias = tmp_path / 'workflow-alias'
    alias.symlink_to(workflow, target_is_directory=True)
    # Also refuse an internal symlink parent even when its resolved target stays inside.
    inner = workflow / 'inner'
    inner.mkdir()
    (inner / 'job.sh').write_bytes(script.read_bytes())
    (workflow / 'inner-alias').symlink_to(inner, target_is_directory=True)
    for candidate in (workflow / 'escape' / 'job.sh', alias / 'job.sh',
                      workflow / 'inner-alias' / 'job.sh'):
        with pytest.raises(CapabilityRefused):
            verify_capability(token, candidate, store=store)
    assert store.scan('wms-submission') == []


def test_T08_SW12_wrong_store_run_id_refuses_even_copied_mint_record(tmp_path):
    from ravel.controller.confine import CapabilityRefused, mint_capability, verify_capability
    workflow, script, _ = setup(tmp_path)
    store = FakeStore('run-first', root=tmp_path / 'store-first')
    token = mint_capability(store, 'launch-a', {'workflow_dir': str(workflow)})
    other = FakeStore('run-second', root=tmp_path / 'store-second')
    other.append('wms-capability', store.scan('wms-capability')[0]['record'])
    with pytest.raises(CapabilityRefused, match='different controller run store'):
        verify_capability(token, script, store=other)
    assert other.scan('wms-submission') == []


def test_T08_SW12_missing_unknown_and_explicit_none_tasks_cannot_bypass_scope(tmp_path):
    from ravel.controller.confine import CapabilityRefused, mint_capability, verify_capability
    workflow, script, _ = setup(tmp_path)
    store = FakeStore('run-tasks', root=tmp_path / 'store')
    token = mint_capability(store, 'launch-tasks', {'workflow_dir': str(workflow), 'tasks': ['alpha']})
    unnamed = setup(tmp_path, rule='summary', name='summary.sh')[1]
    unknown = setup(tmp_path, rule='task_beta', name='beta.sh')[1]
    for candidate, arguments in ((unnamed, {}), (unknown, {}),
                                 (script, {'task': 'beta'}), (script, {'task': None})):
        with pytest.raises(CapabilityRefused, match='outside the capability'):
            verify_capability(token, candidate, store=store, **arguments)
    assert store.scan('wms-submission') == []
    assert verify_capability(token, script, store=store)['task'] == 'alpha'
    verifier = setup(tmp_path, rule='ravel_verify_alpha', name='verify.sh')[1]
    assert verify_capability(token, verifier, store=store)['task'] == 'alpha'


def test_T08_SW12_duplicate_launch_mint_preserves_the_original_token(tmp_path):
    from ravel.controller.confine import CapabilityRefused, mint_capability, verify_capability
    workflow, script, _ = setup(tmp_path)
    store = FakeStore('run-duplicate', root=tmp_path / 'store')
    scope = {'workflow_dir': str(workflow)}
    token = mint_capability(store, 'launch-a', scope)
    with pytest.raises(CapabilityRefused, match='already minted'):
        mint_capability(store, 'launch-a', scope)
    assert len(store.scan('wms-capability')) == 1
    assert verify_capability(token, script, store=store)['launch_id'] == 'launch-a'


def test_T08_SW12_concurrent_submissions_consume_max_jobs_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from ravel.controller.confine import CapabilityRefused, mint_capability, verify_capability
    workflow, script, _ = setup(tmp_path)
    store = FakeStore('run-concurrent', root=tmp_path / 'store')
    token = mint_capability(store, 'launch-a', {'workflow_dir': str(workflow), 'max_jobs': 1})
    ready = Barrier(2)

    def submit():
        ready.wait(timeout=10)
        try:
            return verify_capability(token, script, store=store)['submissions']
        except CapabilityRefused as exc:
            assert 'admits 1 job' in str(exc)
            return 'refused'

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(submit) for _ in range(2)]
        outcomes = [future.result(timeout=15) for future in pending]
    assert outcomes.count(1) == 1 and outcomes.count('refused') == 1
    assert len(store.scan('wms-submission')) == 1


@pytest.mark.parametrize('run_id,launch_id', [('run.a', 'launch-a'), ('run-a', 'launch.a')])
def test_T08_SW12_ambiguous_dotted_identifiers_are_not_minted(tmp_path, run_id, launch_id):
    from ravel.controller.confine import mint_capability
    workflow, _, _ = setup(tmp_path)
    store = FakeStore(run_id, root=tmp_path / 'store')
    with pytest.raises(ValueError, match='without dots'):
        mint_capability(store, launch_id, {'workflow_dir': str(workflow)})
    assert store.scan('wms-capability') == []


def test_T08_SW12_verification_parses_and_hashes_one_captured_script(tmp_path, monkeypatch):
    import hashlib
    from ravel.controller.confine import mint_capability, verify_capability
    workflow, script, _ = setup(tmp_path)
    store = FakeStore('run-capture', root=tmp_path / 'store')
    token = mint_capability(store, 'launch-a', {'workflow_dir': str(workflow), 'rules': ['task_alpha']})
    original = script.read_bytes()
    read_bytes = Path.read_bytes
    reads = []

    def capture(path):
        if path == script:
            reads.append(str(path))
            # A subsequent read would see a different rule and different bytes.
            return original if len(reads) == 1 else b'# properties = {"rule": "task_beta"}\n'
        return read_bytes(path)

    monkeypatch.setattr(Path, 'read_bytes', capture)
    assert verify_capability(token, script, store=store)['rule'] == 'task_alpha'
    assert reads == [str(script)]
    row = store.scan('wms-submission')[0]['record']
    assert row['jobscript_sha256'] == hashlib.sha256(original).hexdigest()


@pytest.mark.parametrize('extra', [
    {'jobscript_sha256': 'invalid'}, {'jobscript_sha256': 7},
    {'resource_maxima': {}}, {'resource_maxima': {'threads': True}},
    {'resource_maxima': {'mem_mb': 0}}, {'resource_maxima': {'runtime': 1.5}},
    {'resource_maxima': {'disk_mb': float('inf')}}, {'resource_maxima': {'unknown': 1}},
    {'resource_maxima': []},
])
def test_T08_SW12_digest_and_resource_scope_validation_is_strict(tmp_path, extra):
    from ravel.controller.confine import mint_capability
    workflow, _, _ = setup(tmp_path)
    store = FakeStore('run-strict', root=tmp_path / 'store')
    with pytest.raises(ValueError):
        mint_capability(store, 'launch-strict', {'workflow_dir': str(workflow), **extra})
    assert store.scan('wms-capability') == []


def test_T08_SW12_scope_is_detached_and_snapshot_bytes_are_private_read_only(tmp_path):
    from ravel.controller.confine import mint_capability, verify_capability
    workflow, script, _ = setup(tmp_path)
    store = FakeStore('run-snapshot', root=tmp_path / 'store')
    maxima = {'threads': 1}
    token = mint_capability(store, 'launch-a', {'workflow_dir': str(workflow), 'resource_maxima': maxima})
    maxima['threads'] = 900
    result = verify_capability(token, script, store=store)
    snapshot = Path(result['snapshot_path'])
    assert snapshot.is_relative_to(store.path()) and not snapshot.is_relative_to(workflow)
    assert snapshot.read_bytes() == script.read_bytes()
    assert result['scope']['resource_maxima'] == {'threads': 1}
    assert snapshot.stat().st_mode & 0o777 == 0o400
    assert snapshot.parent.stat().st_mode & 0o777 == 0o500
    script.write_text('mutated original\n')
    assert snapshot.read_bytes() != script.read_bytes()
