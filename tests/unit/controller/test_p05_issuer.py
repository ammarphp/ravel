"""Throwaway authority canaries under the production confinement boundary."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_p05_support import sandboxed  # noqa: F401


@pytest.fixture
def issuer_world(tmp_path, monkeypatch):
    from ravel.controller.authority import issuer
    from ravel.workflow.approval_authority import AGENT_MARKERS
    root = (tmp_path / 'runtime' / 'authority').resolve()
    for name in AGENT_MARKERS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(issuer, 'home', lambda: root)
    issuer.initialize()
    return root


def planned(monkeypatch, **spec):
    from ravel.controller.confine import launcher
    monkeypatch.setattr(launcher.worker_sandbox, 'available', lambda: 'linux')
    monkeypatch.setattr(launcher, 'qualify', lambda kind: {'confirmed': True})
    return launcher.prepare({'argv': [sys.executable, '-c', 'pass'], **spec})


@pytest.mark.parametrize('surface', ['reads', 'writes', 'runtime', 'channels', 'work'])
def test_final_effective_surfaces_cannot_expose_issuer(tmp_path, monkeypatch, issuer_world, surface):
    from ravel.controller.confine import launcher, locations
    parent = issuer_world.parent
    spec = {}
    if surface == 'runtime':
        monkeypatch.setattr(locations, 'interpreter_roots', lambda: [parent])
    elif surface == 'work':
        run = tmp_path / 'run'
        run.mkdir()
        monkeypatch.setattr(importlib.import_module('ravel.controller.authority.issuer'), 'home',
                            lambda: run / 'work' / 'inert' / 'authority')
        spec.update(run_dir=str(run), stage='inert')
    else:
        spec[surface] = [str(parent)]
    with pytest.raises(ValueError):
        planned(monkeypatch, **spec)


def test_explicit_resolved_issuer_denial_and_residual_risk(monkeypatch, issuer_world):
    from ravel.controller.authority import issuer
    plan = planned(monkeypatch)
    assert issuer_world in plan.hidden
    assert issuer_world in plan.unwritable
    assert plan.record['issuer_protection']['confinement_required'] is True
    assert plan.record['issuer_protection']['same_user_risk'] == issuer.receipt()['same_user_risk']


def test_mutated_plan_and_inherited_key_descriptor_refuse_before_spawn(tmp_path, monkeypatch, issuer_world):
    from ravel.controller.confine import launcher
    plan = planned(monkeypatch)
    plan.reads.append(issuer_world.parent)
    calls = []
    with pytest.raises(ValueError):
        launcher.start(plan, popen=lambda *a, **k: calls.append(a))
    assert not calls and plan.scratch is None
    plan = planned(monkeypatch)
    with (issuer_world / 'issuer.key').open('rb') as stream:
        with pytest.raises(ValueError):
            launcher.start(plan, stdin=stream, popen=lambda *a, **k: calls.append(a))
    assert not calls and plan.scratch is None


@pytest.mark.parametrize('claim', ['explicit', 'controller', 'owned'])
def test_unavailable_backend_cannot_claim_issuer_protection(tmp_path, monkeypatch, claim):
    from ravel.controller.confine import launcher
    monkeypatch.setattr(launcher.worker_sandbox, 'available', lambda: None)
    monkeypatch.setattr(launcher.runs, 'allow_unconfined', lambda: True)
    monkeypatch.setattr(launcher.runs, 'owner_of', lambda path: ('run-inert', tmp_path) if claim == 'owned' else None)
    extra = {'issuer_protected': True} if claim == 'explicit' else {'controller': {'run_id': 'run-inert'}} if claim == 'controller' else {'run_dir': str(tmp_path)}
    with pytest.raises(ValueError):
        launcher.prepare({'argv': [sys.executable, '-c', 'pass'], **extra})


def test_legacy_unconfined_diagnostic_remains_explicit(monkeypatch):
    from ravel.controller.confine import launcher
    monkeypatch.setattr(launcher.worker_sandbox, 'available', lambda: None)
    monkeypatch.setattr(launcher.runs, 'allow_unconfined', lambda: True)
    plan = launcher.prepare({'argv': [sys.executable, '-c', 'pass']})
    assert plan.kind == 'unconfined' and plan.record['label_text'] == 'UNCONFINED EXECUTION'
    assert plan.record['architecture_complete'] is False


def test_real_launch_denies_key_and_preserves_declared_work(tmp_path, monkeypatch, issuer_world, sandboxed):
    from ravel.controller.confine import launcher
    output = (tmp_path / 'output').resolve()
    output.mkdir()
    program = r'''
import json, os, pathlib, sys
root, output = map(pathlib.Path, sys.argv[1:])
seen = {}
for name, action in [('read', lambda: (root/'issuer.key').read_bytes()),
                     ('replace', lambda: os.replace(output/'replacement', root/'issuer.key'))]:
 try: action(); seen[name] = 'allowed'
 except OSError: seen[name] = 'denied'
(output/'result').write_text('valid confined work')
print(json.dumps(seen))
'''
    (output / 'replacement').write_bytes(b'x' * 32)
    before = (issuer_world / 'issuer.key').read_bytes()
    process = launcher.popen({'argv': [sys.executable, '-I', '-S', '-B', '-c', program, str(issuer_world), str(output)],
                              'writes': [str(output)]}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        out, err = process.communicate(timeout=30)
        assert process.returncode == 0, err
        assert json.loads(out) == {'read': 'denied', 'replace': 'denied'}
    finally:
        launcher.finish(process)
    assert (issuer_world / 'issuer.key').read_bytes() == before
    assert (output / 'result').read_text() == 'valid confined work'


def test_real_worker_cannot_initialize_or_issue_authority(tmp_path, issuer_world, sandboxed):
    from ravel.controller.confine import worker
    from ravel.workflow import sandbox
    workspace = (tmp_path / 'worker').resolve()
    for part in ('inputs', 'outputs', 'scratch'):
        (workspace / part).mkdir(parents=True)
    program = r'''
import json, os, pathlib, sys
sys.path.insert(0, sys.argv[1])
from ravel.controller.authority import issuer, operator
issuer.home = lambda: pathlib.Path(sys.argv[2])
operator.controller_home = lambda: pathlib.Path(sys.argv[3])
checks = {}
for name, action in [('read', lambda: (issuer.home()/'issuer.key').read_bytes()),
                     ('replace', lambda: os.replace('scratch/replacement', issuer.home()/'issuer.key')),
                     ('initialize', lambda: operator.init(mode='autonomous')),
                     ('issue', lambda: issuer.seal({'approved': True}, 'approval'))]:
 try: action(); checks[name] = 'allowed'
 except (OSError, ValueError): checks[name] = 'denied'
pathlib.Path('outputs/result').write_text('valid worker')
print(json.dumps(checks))
'''
    (workspace / 'scratch' / 'replacement').write_bytes(b'x' * 32)
    import ravel
    argv = [sys.executable, '-I', '-S', '-B', '-c', program, str(Path(ravel.__file__).resolve().parent.parent),
            str(issuer_world), str(workspace / 'scratch' / 'operator')]
    before = (issuer_world / 'issuer.key').read_bytes()
    command = worker.command(workspace, argv, read_paths=sandbox.runtime_paths(argv))
    done = subprocess.run(command, cwd=workspace, env={'PATH': '/usr/bin:/bin'}, capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == dict.fromkeys(('read', 'replace', 'initialize', 'issue'), 'denied')
    assert (issuer_world / 'issuer.key').read_bytes() == before
    assert (workspace / 'outputs' / 'result').read_text() == 'valid worker'


def test_worker_runtime_mount_cannot_include_issuer(tmp_path, issuer_world, sandboxed):
    from ravel.controller.confine import probe
    workspace = (tmp_path / 'worker').resolve()
    for part in ('inputs', 'outputs', 'scratch'):
        (workspace / part).mkdir(parents=True)
    from ravel.workflow import sandbox
    with pytest.raises(ValueError):
        probe('worker', {'workspace': str(workspace),
                         'read_paths': [*sandbox.runtime_paths([sys.executable]), str(issuer_world.parent)]})


@pytest.mark.parametrize('kind', ['launch', 'worker'])
def test_real_inventory_contains_issuer_negative_probes(tmp_path, issuer_world, sandboxed, kind):
    from ravel.controller.confine import probe
    target = {}
    if kind == 'worker':
        workspace = (tmp_path / 'worker').resolve()
        for part in ('inputs', 'outputs', 'scratch'):
            (workspace / part).mkdir(parents=True)
        target['workspace'] = str(workspace)
    seen = probe(kind, target)
    assert seen['issuer_read_denied'] is True
    assert seen['issuer_replace_denied'] is True
