"""Refusals and holds of the confined launcher happen before any effect (no process, directory or event).

Each case has a positive control. None needs a real sandbox: planning refuses before the
backend is asked, and backend availability is substituted where a case is about it.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_p05_support import operator, own


@pytest.fixture
def counters(tmp_path, monkeypatch):
    """Effect counters: processes started and scratch directories created by the launcher."""
    started = []
    real_popen = subprocess.Popen

    def counting(*args, **kwargs):
        started.append(args[0] if args else kwargs.get('args'))
        return real_popen(*args, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', counting)
    scratch = tmp_path / 'scratch-parent'
    scratch.mkdir()
    monkeypatch.setenv('TMPDIR', str(scratch.resolve()))
    from ravel.controller.confine import launcher
    from ravel.workflow import sandbox
    # Planning never starts the backend; these cases hold on any host, sandbox or not.
    monkeypatch.setattr(sandbox, 'available', lambda: 'macos' if sys.platform == 'darwin' else 'linux')
    monkeypatch.setattr(launcher, 'qualify', lambda kind: {'backend': kind, 'confirmed': True, 'checks': {}})
    return {'started': started, 'scratch': scratch}


def run_tree(tmp_path):
    run = (tmp_path / 'run').resolve()
    (run / 'inputs').mkdir(parents=True)
    (run / 'inputs' / 'checkin1_approval.json').write_text('{}')
    (run / 'logs' / 'authorization').mkdir(parents=True)
    (run / 'outputs').mkdir()
    return run


def spec(run, **extra):
    return {'argv': [sys.executable, '-c', 'pass'], 'run_dir': str(run), 'stage': 'stage', 'cwd': str(run),
            'reads': [str(run)], 'writes': [str(run / 'outputs')], **extra}


def assert_no_effect(counters, run):
    assert counters['started'] == []
    assert list(counters['scratch'].iterdir()) == []
    assert not (run / 'work').exists()
    assert sorted(p.name for p in (run / 'logs' / 'authorization').iterdir()) == []


@pytest.mark.parametrize('output', ['inputs/checkin1_approval.json', 'inputs/new.json', 'logs/authorization/x.json',
                                    'logs/execution/x.json', 'execution_state.json', 'task_contract.json',
                                    'logs/stage.failure.json', '.claude/settings.local.json', 'workflow/policy.json',
                                    'ravel/__init__.py', 'sitecustomize.py', 'review/verdict.json', 'delivery'])
def test_a_declared_output_over_a_governed_record_is_refused_before_any_effect(tmp_path, counters, output):
    from ravel.controller.confine import ConfinementRefused, prepare
    run = run_tree(tmp_path)
    with pytest.raises(ConfinementRefused):
        prepare(spec(run, writes=[str(run / output)]))
    assert_no_effect(counters, run)


def test_outputs_outside_the_run_or_over_install_custody_or_credentials_are_refused(tmp_path, counters, monkeypatch):
    from ravel.controller.confine import ConfinementRefused, prepare, locations
    run = run_tree(tmp_path)
    monkeypatch.setenv('HOME', str((tmp_path / 'home').resolve()))
    (tmp_path / 'home' / '.ssh').mkdir(parents=True)
    monkeypatch.setenv('RAVEL_STATE_DIR', str((tmp_path / 'state').resolve()))
    for target in (tmp_path / 'outside.json', locations.package_root() / 'planted.py',
                   tmp_path / 'state' / 'custody.json', tmp_path / 'home' / '.ssh' / 'id', tmp_path / 'home'):
        with pytest.raises(ConfinementRefused):
            prepare(spec(run, writes=[str(target)]))
    with pytest.raises(ConfinementRefused):
        prepare({'argv': [sys.executable, '-c', 'pass'], 'writes': [str(locations.package_root() / 'x')]})
    assert_no_effect(counters, run)


def test_a_symlinked_output_and_a_read_that_exposes_home_or_custody_are_refused(tmp_path, counters, monkeypatch):
    from ravel.controller.confine import ConfinementRefused, prepare
    run = run_tree(tmp_path)
    (run / 'linked').symlink_to(tmp_path)
    home = (tmp_path / 'home').resolve()
    (home / '.config').mkdir(parents=True)
    monkeypatch.setenv('HOME', str(home))
    with pytest.raises(ConfinementRefused):
        prepare(spec(run, writes=[str(run / 'linked' / 'x.json')]))
    for read in (home, home / '.config', tmp_path.resolve()):
        with pytest.raises(ConfinementRefused):
            prepare(spec(run, reads=[str(run), str(read)]))
    assert_no_effect(counters, run)


def test_a_changed_committed_input_is_refused_by_its_exact_path(tmp_path, counters):
    from ravel.controller.confine import ConfinementRefused, prepare
    run = run_tree(tmp_path)
    helper = run / 'helper'
    helper.write_text('approved bytes')
    approved = hashlib.sha256(b'approved bytes').hexdigest()
    plan = prepare(spec(run, input_digests={str(helper): approved}))
    assert plan.kind == 'confined'
    helper.write_text('changed after approval')
    with pytest.raises(ConfinementRefused, match=str(helper)):
        prepare(spec(run, input_digests={str(helper): approved}))
    assert_no_effect(counters, run)


def test_E06_more_cpus_than_the_live_grant_refuse_before_process_creation(tmp_path, counters, monkeypatch):
    from ravel.controller.confine import ConfinementRefused, launcher, prepare
    from ravel.workflow import machine_lease
    run = run_tree(tmp_path)
    monkeypatch.setattr(machine_lease, 'cpu_grant', lambda: [3])
    with pytest.raises(ConfinementRefused, match='live machine grant has 1'):
        prepare(spec(run, limits={'cpus': 2}))
    plan = prepare(spec(run, limits={'cpus': 1}))
    assert plan.limits['cpu_set'] == [3] and plan.record['limits'] == {'cpus': 1}
    assert launcher.machine_grant() == [3]
    assert_no_effect(counters, run)


def test_no_sandbox_holds_with_a_typed_reason_and_no_effect(tmp_path, counters, monkeypatch):
    from ravel.controller.confine import LaunchHeld, popen
    from ravel.workflow import sandbox
    run = run_tree(tmp_path)
    monkeypatch.setattr(sandbox, 'available', lambda: None)
    with pytest.raises(LaunchHeld) as held:
        popen(spec(run))
    assert held.value.reason == 'sandbox_unavailable' and 'allow_unconfined' in str(held.value)
    assert_no_effect(counters, run)


def test_E06_unsupported_process_limit_holds_before_launch(tmp_path, counters):
    from ravel.controller.confine import LaunchHeld, prepare
    run = run_tree(tmp_path)
    with pytest.raises(LaunchHeld) as held:
        prepare(spec(run, limits={'processes': 2}))
    assert held.value.reason == 'resource_limit_unsupported'
    assert_no_effect(counters, run)


def test_the_operator_may_allow_labelled_unconfined_execution(tmp_path, counters, monkeypatch):
    from ravel.controller.confine import UNCONFINED_LABEL, finish, popen
    from ravel.workflow import sandbox
    run = run_tree(tmp_path)
    monkeypatch.setattr(sandbox, 'available', lambda: None)
    operator(monkeypatch, {'allow_unconfined': True})
    monkeypatch.setenv('GH_TOKEN', 'x')
    monkeypatch.setenv('WORKFLOW_STATE_UTC', '2001-01-01T00:00:00Z')
    process = popen(spec(run, argv=[sys.executable, '-c', 'import os, json; print(json.dumps(sorted(os.environ)))']),
                    stdout=subprocess.PIPE)
    names = json.loads(process.communicate(timeout=60)[0])
    record = process.ravel_confinement.record
    assert record['kind'] == 'unconfined' and record['label_text'] == UNCONFINED_LABEL
    assert record['architecture_complete'] is False
    assert 'GH_TOKEN' not in names and 'WORKFLOW_STATE_UTC' not in names, 'the environment stays allowlisted'
    assert finish(process)['outputs'][0]['path'] == str(run / 'outputs')


def test_a_sandbox_that_fails_its_probe_holds_even_when_unconfined_is_allowed(tmp_path, counters, monkeypatch):
    from ravel.controller.confine import LaunchHeld, launcher, prepare
    from ravel.workflow import sandbox
    run = run_tree(tmp_path)
    operator(monkeypatch, {'allow_unconfined': True})
    monkeypatch.setattr(sandbox, 'available', lambda: 'linux')

    def failed(kind):
        raise sandbox.SandboxProbeFailed('launch sandbox probe did not confirm [write_governed_record]')
    monkeypatch.setattr(launcher, 'qualify', failed)
    with pytest.raises(LaunchHeld) as held:
        prepare(spec(run))
    assert held.value.reason == 'sandbox_unqualified'
    assert_no_effect(counters, run)


def test_backend_selection_refuses_unknown_and_absent_backends(tmp_path, counters, monkeypatch):
    from ravel.controller.confine import ConfinementRefused, LaunchHeld, prepare
    from ravel.workflow import sandbox
    run = run_tree(tmp_path)
    monkeypatch.setattr(sandbox, 'available', lambda: 'linux')
    with pytest.raises(LaunchHeld):
        prepare(spec(run, backend='sandbox-exec'))
    with pytest.raises(ConfinementRefused, match='oci-local'):
        prepare(spec(run, backend='oci-local'))
    with pytest.raises(ConfinementRefused, match='unknown launch backend'):
        prepare(spec(run, backend='chroot'))
    assert prepare(spec(run, backend='bwrap')).record['backend'] == 'bwrap'
    assert_no_effect(counters, run)


def test_a_spec_with_unknown_keys_or_bad_values_is_refused(tmp_path, counters):
    from ravel.controller.confine import ConfinementRefused, prepare
    run = run_tree(tmp_path)
    for bad in ({'argv': []}, {**spec(run), 'shell': True}, {**spec(run), 'tcp_ports': [0]},
                {**spec(run), 'limits': {'cpus': 0}}, {**spec(run), 'limits': {'gpus': 1}},
                {**spec(run), 'env': {'A': 1}}, {**spec(run), 'reads': [str(run / 'absent')]},
                {**spec(run), 'channels': ['relative.sock']}):
        with pytest.raises(ConfinementRefused):
            prepare(bad)
    assert_no_effect(counters, run)


def test_SW16_SW37_environment_scrub_removes_forbidden_classes():
    from ravel.controller.confine import environment as env
    capsule = {'PATH': '/usr/bin', 'LANG': 'C.UTF-8', 'WORKFLOW_STATE_UTC': 'x', 'GATE_TIMESTAMP': 'x',
               'SHAPE_FIT_UTC': 'x', 'RAVEL_ROOT': '/x', 'RAVEL_STATE_DIR': '/x', 'RAVEL_NATIVE_BIN': '/x',
               'HTTPS_PROXY': 'x', 'no_proxy': 'x', 'GH_TOKEN': 'x', 'MY_API_KEY': 'x', 'DB_PASSWORD': 'x',
               'CLAUDECODE': '1', 'CODEX_THREAD_ID': 'x', 'ANTHROPIC_MODEL': 'x', 'SSH_AUTH_SOCK': 'x',
               'LD_PRELOAD': 'x', 'BASH_ENV': 'x', 'AWS_ACCESS_KEY_ID': 'x', 'GIT_DIR': 'x', 'HOME': '/account/x',
               'RAVEL_JOB_TOKEN': 'job', 'RAVEL_OUTPUT_DIR': '/out', 'RAVEL_STAGE_CUSTODY': 'secret'}
    scrubbed, removed = env.scrub(capsule)
    assert scrubbed == {'PATH': '/usr/bin', 'LANG': 'C.UTF-8', 'RAVEL_JOB_TOKEN': 'job', 'RAVEL_OUTPUT_DIR': '/out',
                        'RAVEL_STAGE_CUSTODY': 'secret'}
    assert set(removed) == set(capsule) - set(scrubbed)
    launched, _ = env.launch_environment(capsule, '/scratch')
    assert launched['HOME'] == '/scratch/home' and launched['TMPDIR'] == '/scratch/tmp'
    with pytest.raises(ValueError):
        env.launch_environment({}, '/scratch', {'RAVEL_ROOT': '/x'})
    assert env.capsule_from({'PATH': '/usr/bin', 'GH_TOKEN': 'x', 'RAVEL_JOB_TOKEN': 'j'}) == {
        'PATH': '/usr/bin', 'RAVEL_JOB_TOKEN': 'j'}


def test_a_confined_launch_needs_its_working_directory_declared(tmp_path, counters):
    from ravel.controller.confine import ConfinementRefused, prepare, start
    run = run_tree(tmp_path)
    plan = prepare({k: v for k, v in spec(run).items() if k != 'cwd'})
    with pytest.raises(ConfinementRefused, match='working directory'):
        start(plan, cwd=str(run))
    assert counters['started'] == []
