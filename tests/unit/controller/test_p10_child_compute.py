"""An ordinary child carries only an explicit, effect-authorized compute rung."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ravel.controller.routes.study import child_contract, runtime
from ravel.controller.routes.compiler import plan_sha256
from ravel.workflow import execution, review_independence, science, stage_supervisor
from ravel.workflow.state_io import atomic_json
from test_p04_support import FakeStore
from test_p05_support import sandboxed  # noqa: F401


@pytest.fixture
def child_factory(tmp_path, monkeypatch):
    from method_decision_fixture import admit_method
    from test_science_review_envelope import specification
    from ravel.controller import authority
    for key in execution.RUNTIME_ENVIRONMENT_KEYS:
        monkeypatch.delenv(key, raising=False)
    calls = []

    def authorize(store, effect):
        calls.append(deepcopy(effect))
        if calls[-1].get('requires_go') and effect['rung'] in ('full', 'scan') and not effect['go_pins']:
            raise authority.AuthorityRefused('no current GO')
        return {'approve_plan': 'verified-decision', 'go': 'verified-go' if effect['go_pins'] else None}

    monkeypatch.setattr(authority, 'authorize_effect', authorize)

    def make(rung, *, ceiling='scan', go=True, changed_step=False):
        parent = tmp_path / 'parent'
        (parent / 'inputs').mkdir(parents=True)
        child = parent / 'children' / 'ordinary'
        source = tmp_path / 'spec.json'
        atomic_json(source, specification(tmp_path))
        science.plan(child, source)
        admit_method(child)
        raw = b'{"nodes": [], "edges": [], "claims": []}'
        (parent / 'inputs/request_plan.json').write_bytes(raw)
        contract = {'prompt': 'Compute a supplied quantity.', 'agent_layer_epoch': 2,
                    'request_plan': {'path': 'inputs/request_plan.json', 'sha256': hashlib.sha256(raw).hexdigest()}}
        atomic_json(parent / 'inputs/task_contract.json', contract)
        store = FakeStore(tmp_path / 'store', run_dir=parent)
        store.append('intake', {'contract_blob': store.put_blob((parent / 'inputs/task_contract.json').read_bytes())})
        monkeypatch.setattr(review_independence, 'controller_store', lambda root: store if Path(root) == child else None)
        ordinary = {'kind': 'science', 'child_rundir': 'children/ordinary',
                    'plan_sha256': execution.file_hash(child / science.PLAN),
                    'specification_sha256': execution.file_hash(child / science.SPEC)}
        step = {'id': 'operate', 'rung': rung, 'operation': 'domain',
                'budget': {'wall_seconds': 45, 'events': 0}, 'parameters': {'ordinary': ordinary}}
        plan = {'steps': [deepcopy(step)]}
        plan['sha256'] = plan_sha256(plan)
        store.append('plan', {'plan_sha256': plan['sha256'],
                             'blob': store.put_blob(json.dumps(plan).encode())})
        context = {'run_dir': str(parent), 'plan_sha256': plan['sha256'], 'contract': contract,
                   'requires_go': True, 'go_pins': {'waypoint': 'pinned'} if go else {}}
        if changed_step:
            step['rung'] = 'scan' if rung == 'full' else 'full'
        decision = {'id': 'verified-decision', 'decision': 'approve', 'authorizes_effects': True,
                    'bounds': {'rung': ceiling}}
        runtime.approve_ordinary_child(store, step, child, ordinary, decision, context)
        monkeypatch.setattr(review_independence, 'controller_store', lambda root: None)
        return child, store, calls, context

    return make


@pytest.mark.parametrize('rung', ['smoke', 'full', 'scan'])
def test_approved_rung_reaches_actual_science_supervision_without_store(child_factory, monkeypatch, rung):
    child, store, calls, context = child_factory(rung)
    assert review_independence.controller_store(child) is None
    assert child_contract.compute_rung(child, max_seconds=45) == rung
    assert calls and calls[0]['rung'] == rung
    assert calls[0]['pins']['plan_sha256'] == context['plan_sha256']
    assert calls[0]['budget'] == {'wall_seconds': 45, 'events': 0}
    assert calls[0]['go_pins'] == context['go_pins']
    assert store.scan(child_contract.RECORD)[0]['record']['files'][child_contract.COMPUTE]

    class AdmissionReached(Exception):
        pass

    original = stage_supervisor.supervise
    def supervised(*args, **kwargs):
        assert kwargs['science_rung'] == rung
        assert kwargs.get('required_plan') is None and kwargs.get('authorization_plan') is None
        return original(*args, **kwargs)

    monkeypatch.setattr(stage_supervisor, 'supervise', supervised)
    monkeypatch.setattr(stage_supervisor, '_machine_lease', lambda *a, **k: (_ for _ in ()).throw(AdmissionReached()))
    monkeypatch.setattr(stage_supervisor.subprocess, 'Popen', lambda *a, **k: pytest.fail('inert admission launched'))
    with pytest.raises(AdmissionReached):
        science.run(child)


@pytest.mark.parametrize('rung,ceiling,go,changed_step', [
    ('full', 'smoke', True, False), ('full', 'scan', False, False),
    ('full', 'scan', True, True), (['smoke', 'full'], 'scan', True, False),
    ('pilot', 'scan', True, False),
])
def test_unapproved_or_ambiguous_rung_refuses_before_child_approval(child_factory, rung, ceiling, go, changed_step):
    with pytest.raises(ValueError, match='compute rung|GO|approved step'):
        child_factory(rung, ceiling=ceiling, go=go, changed_step=changed_step)


def test_missing_rung_is_not_inferred_from_approval_ceiling(child_factory):
    child, _, calls, _ = child_factory(None)
    assert calls == []
    with pytest.raises(ValueError, match='compute rung') as refused:
        science.run(child)
    assert refused.value.code == 'ordinary_compute_rung_unavailable'
    assert not (child / 'execution_attempt.json').exists()


@pytest.mark.parametrize('change', ['rung', 'remove', 'ceiling'])
def test_changed_or_missing_capsule_compute_binding_refuses(child_factory, change):
    child, _, _, _ = child_factory('full')
    path = child / child_contract.COMPUTE
    if change == 'remove':
        path.unlink()
    else:
        value = json.loads(path.read_bytes())
        value['required_plan' if change == 'rung' else 'max_seconds'] = 'scan' if change == 'rung' else 90
        atomic_json(path, value)
    with pytest.raises(ValueError):
        child_contract.compute_rung(child, max_seconds=45)


def test_supervision_cannot_borrow_another_rung_or_exceed_bound_time(child_factory):
    child, _, _, _ = child_factory('smoke')
    for rung, seconds in [('full', 45), ('smoke', 46)]:
        proposal = science.verify_plan(child, approved=True)
        stage = proposal['stages'][0]
        with pytest.raises(ValueError, match='compute rung|ceiling'):
            stage_supervisor.supervise('science', child, 0, stage['log'], stage['command'],
                kill_secs=seconds, inputs=stage['inputs'], outputs=stage['outputs'], cwd=str(child), science_rung=rung)


def test_store_without_run_directory_owns_no_controller_child(tmp_path, monkeypatch):
    monkeypatch.setattr(review_independence, 'controller_store', lambda child: SimpleNamespace())
    assert child_contract.paths(tmp_path / 'child') is None


def test_compute_binding_still_requires_the_childs_own_approval(child_factory, monkeypatch):
    child, store, _, _ = child_factory('full')
    monkeypatch.setattr(review_independence, 'controller_store', lambda root: store)
    (child / science.APPROVAL).unlink()
    with pytest.raises(child_contract.ComputeRungUnavailable):
        child_contract.compute_rung(child, max_seconds=45)


@pytest.mark.parametrize('changed', [False, True])
def test_native_capsule_reads_only_its_bound_compute_rung(child_factory, sandboxed, tmp_path, changed):
    from ravel.controller import confine
    child, store, _, _ = child_factory('full')
    if changed:
        binding = child / child_contract.COMPUTE
        value = json.loads(binding.read_bytes())
        value['required_plan'] = 'scan'
        atomic_json(binding, value)
    secret = store.root / 'withheld-proof.txt'
    secret.write_text('protected input')
    source_root = Path(science.__file__).resolve().parents[2]
    probe = child / 'inputs/compute_probe.py'
    probe.write_text('''import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[3])
from ravel.controller.routes.study import child_contract
from ravel.workflow import review_independence
child,secret=Path(sys.argv[1]),Path(sys.argv[2])
result={'store':review_independence.controller_store(child) is not None,
        'code':hashlib.sha256(Path(child_contract.__file__).read_bytes()).hexdigest()}
try:
    secret.read_bytes()
    result['store_readable']=True
except OSError:
    result['store_readable']=False
try:
    result['rung']=child_contract.compute_rung(child,max_seconds=45)
except ValueError as exc:
    result.update(rung=None,error=str(exc),code_name=getattr(exc,'code',None))
print(json.dumps(result))
''')
    out = tmp_path / 'capsule-output'
    out.mkdir()
    process = confine.popen({'argv': [sys.executable, '-m', 'compute_probe', str(child), str(secret), str(source_root)],
        'env': {'PYTHONPATH': os.pathsep.join([str(source_root), str(probe.parent)])},
        'reads': [str(child / 'inputs'), str(source_root)], 'writes': [str(out)], 'cwd': str(out),
        'withheld': [str(store.root)], 'limits': {'wall_seconds': 60}},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate(timeout=90)
    confine.finish(process)
    assert process.returncode == 0, stderr.decode()
    result = json.loads(stdout.decode().strip().splitlines()[-1])
    assert result['code'] == execution.file_hash(child_contract.__file__), result
    assert result['store'] is False and result['store_readable'] is False, result
    assert result['rung'] == (None if changed else 'full'), result
    if changed:
        assert result['code_name'] == 'ordinary_compute_rung_unavailable', result
