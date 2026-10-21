"""Controller-derived intake remains bound inside a native launch without its store."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ravel.controller.routes.study import runtime
from ravel.workflow import execution, review_independence, science
from ravel.workflow.state_io import atomic_json
from test_p04_support import FakeStore
from test_p05_support import sandboxed  # noqa: F401


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    from method_decision_fixture import admit_method
    from test_science_review_envelope import specification
    for key in execution.RUNTIME_ENVIRONMENT_KEYS:
        monkeypatch.delenv(key, raising=False)
    parent = tmp_path / 'parent'
    (parent / 'inputs').mkdir(parents=True)
    child = parent / 'children' / 'ordinary'
    source = tmp_path / 'spec.json'
    atomic_json(source, specification(tmp_path))
    science.plan(child, source)
    admit_method(child)
    unbound_fingerprint = science._approval_fingerprint(science.approval_input_paths(child))
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
    runtime.approve_ordinary_child(store, {'id': 'operate'}, child, ordinary,
                                  {'id': 'verified-decision', 'decision': 'approve', 'authorizes_effects': True},
                                  {'run_dir': str(parent), 'plan_sha256': 'a' * 64, 'contract': contract})
    secret = store.root / 'protected-proof.txt'
    secret.write_text('not a child input')
    monkeypatch.setattr(review_independence, 'controller_store', lambda root: None)
    return child, secret, unbound_fingerprint


def test_full_child_verification_uses_approval_without_controller_store(prepared):
    child, _, _ = prepared
    assert review_independence.controller_store(child) is None
    assert science.verify_plan(child, approved=True)['schema_version'] == 2


@pytest.mark.parametrize('change', ['none', 'contract', 'unbound', 'missing_contract'])
def test_retained_child_authorization_without_store_or_live_inputs(prepared, change):
    from ravel.workflow import launch_authorization, physics_review
    from test_science_review_envelope import token
    child, _, unbound_fingerprint = prepared
    token(child)
    proposal = science.verify_plan(child, approved=True)
    stage, binding, seconds = science._selected(child, proposal)
    context = {'kind': 'science-stage', 'stage': 'science', 'review_action': 'bulk', 'max_seconds': seconds,
               'events': 0, 'plan_sha256': execution.file_hash(child / science.PLAN),
               'stage_spec': physics_review._stage_spec(child, {**stage, 'inputs': binding['inputs']})}
    snapshot = launch_authorization._capture(child, 'science', command=stage['command'], context=context)
    if change == 'contract':
        pin = next(p for p in snapshot['approval_inputs'] if p['path'] == str(child / 'inputs/task_contract.json'))
        pin['text'] = pin['text'].replace('supplied quantity', 'changed quantity')
        pin['sha256'] = hashlib.sha256(pin['text'].encode()).hexdigest()
    elif change == 'unbound':
        pin = snapshot['approval']
        receipt = json.loads(pin['text'])
        receipt['input_fingerprint'] = unbound_fingerprint
        pin['text'] = json.dumps(receipt)
        pin['sha256'] = hashlib.sha256(pin['text'].encode()).hexdigest()
    elif change == 'missing_contract':
        snapshot['approval_inputs'] = [p for p in snapshot['approval_inputs']
                                      if p['path'] != str(child / 'inputs/task_contract.json')]
    for name in ('inputs/task_contract.json', 'inputs/request_plan.json', science.APPROVAL):
        (child / name).unlink()
    event = {'authorization': snapshot, 'command': stage['command'], 'context': context,
             'utc': launch_authorization.operational_utc()}
    errors = science.validate_authorization_snapshot(snapshot, event)
    assert bool(errors) is (change != 'none'), errors


PROGRAM = '''
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[3])
from ravel.workflow import review_independence, science
from ravel.controller.routes.study import child_contract
child, secret = Path(sys.argv[1]), Path(sys.argv[2])
result = {'controller_store': review_independence.controller_store(child) is not None,
          'approval_readable': (child / science.APPROVAL).is_file(),
          'code_sha256': hashlib.sha256(Path(child_contract.__file__).read_bytes()).hexdigest()}
try:
    secret.read_bytes()
    result['store_readable'] = True
except OSError:
    result['store_readable'] = False
try:
    result['paths'] = science._research_contract_paths(child)
    result['accepted'] = True
except (OSError, ValueError, KeyError, TypeError) as exc:
    result.update(accepted=False, error=str(exc))
print(json.dumps(result))
'''


@pytest.mark.parametrize('change', ['none', 'contract', 'request_plan', 'unbound', 'missing_approval', 'link'])
def test_native_capsule_checks_approval_bound_child_inputs(prepared, sandboxed, tmp_path, change):
    from ravel.controller import confine
    from ravel.controller.routes.study import child_contract
    child, secret, unbound_fingerprint = prepared
    contract = child / 'inputs/task_contract.json'
    if change == 'contract':
        value = json.loads(contract.read_bytes())
        value['prompt'] = 'Changed request.'
        atomic_json(contract, value)
    elif change == 'request_plan':
        raw = b'{"nodes": [], "edges": [], "claims": [], "trap_sweep": true}'
        (child / 'inputs/request_plan.json').write_bytes(raw)
        value = json.loads(contract.read_bytes())
        value['request_plan']['sha256'] = hashlib.sha256(raw).hexdigest()
        atomic_json(contract, value)
    elif change == 'unbound':
        approval = child / science.APPROVAL
        value = json.loads(approval.read_bytes())
        value['input_fingerprint'] = unbound_fingerprint
        atomic_json(approval, value)
    elif change == 'missing_approval':
        (child / science.APPROVAL).unlink()
    elif change == 'link':
        target = child / 'inputs/alternate.json'
        target.write_bytes(contract.read_bytes())
        contract.unlink()
        contract.symlink_to(target)
    out = tmp_path / 'capsule-output'
    out.mkdir()
    source_root = Path(science.__file__).resolve().parents[2]
    probe = child / 'inputs/capsule_probe.py'
    probe.write_text(PROGRAM)
    # Native runtime adapters use module invocation. Arbitrary -c programs hide
    # the framework package and cannot exercise this installed native path.
    process = confine.popen({'argv': [sys.executable, '-m', 'capsule_probe', str(child), str(secret), str(source_root)],
                             'env': {'PYTHONPATH': os.pathsep.join([str(source_root), str(probe.parent)])},
                             'reads': [str(child / 'inputs'), str(source_root)], 'writes': [str(out)], 'cwd': str(out),
                             'withheld': [str(secret.parent)], 'limits': {'wall_seconds': 60}},
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate(timeout=90)
    confine.finish(process)
    assert process.returncode == 0, stderr.decode()
    result = json.loads(stdout.decode().strip().splitlines()[-1])
    assert result['code_sha256'] == execution.file_hash(child_contract.__file__), result
    assert result['controller_store'] is False and result['store_readable'] is False, result
    assert result['approval_readable'] is (change != 'missing_approval'), result
    assert result['accepted'] is (change == 'none'), result
    if change == 'none':
        assert result['paths'] == [str(contract), str(child / 'inputs/request_plan.json')]
    else:
        assert result.get('error'), result
