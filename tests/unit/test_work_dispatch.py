"""CHECK-IN-pinned adoption, without execution or custody credit."""
import json
from pathlib import Path

import pytest

from ravel.workflow import role_registry as rr, work_dispatch as wd
from ravel.workflow.work_order_fidelity import digest


def fixture(root, *, node='N3.author', legacy=False, declared_outputs=None):
    (root / 'inputs/work-orders').mkdir(parents=True)
    from ravel.validation import validate_run_state
    from test_approval_chain import VALID_CHECKIN1
    (root / 'inputs/task_contract.json').write_text(json.dumps(validate_run_state._base_contract(task_mode='reproduce', compute_plan='smoke')))
    (root / 'inputs/checkin1.json').write_text(json.dumps(VALID_CHECKIN1))
    (root / 'inputs/cost_preflight.json').write_text(json.dumps({'schema_version': 1, 'generated_by': 'cost_preflight.py', 'mode': 'smoke', 'walltime_h': [0.5, 1]}))
    order = {'node_id': node, 'role': 'generator', 'review_points': [
        {'id': 'RP1', 'statement': 'Δφ cut'}],
        'declared_outputs': declared_outputs or [{'path': 'outputs/result.json', 'kind': 'result', 'required': True}]}
    order['obligations'] = wd.derive_obligations(order)
    assert order['obligations']
    order['order_sha256'] = digest(order)
    (root / f'inputs/work-orders/{node}.json').write_text(json.dumps(order, ensure_ascii=False))
    wd.pin_obligations(root)
    # Actual ordinary approval writer, with no physics execution or worker credit.
    from ravel.workflow import workflow_state
    from argparse import Namespace
    assert workflow_state.cmd_approve(Namespace(rundir=str(root), plan='smoke', quote='Synthetic test GO')) == 0
    workspace = root / ('work' if legacy else 'agent-work') / node / ('attempt-1' if legacy else '1')
    (workspace / 'outputs').mkdir(parents=True)
    contents = {o['id']: {'statement': 'checked', 'evidence': ['receipt:check']} for o in order['obligations']}
    sidecar = order['obligations'][0]['output']
    (workspace / sidecar).write_text(json.dumps({'obligations': contents, 'value': 0}))
    for output in order['declared_outputs']:
        if output['path'] != sidecar:
            (workspace / output['path']).write_text('Synthetic scientific output bytes\n')
    return order, workspace


def rewrite_order(root, order):
    order['order_sha256'] = digest(order)
    (root / f"inputs/work-orders/{order['node_id']}.json").write_text(json.dumps(order))


@pytest.mark.parametrize('fault', ['both_empty', 'subset', 'edited_pin', 'legacy'])
def test_n8_adoption_refuses(fault, tmp_path):
    order, _ = fixture(tmp_path, legacy=fault == 'legacy')
    if fault == 'both_empty':
        order['obligations'] = []
        path = tmp_path / 'inputs/work-obligations.json'
        pinned = json.loads(path.read_text())
        pinned['nodes'][order['node_id']]['obligations'] = []
        path.write_text(json.dumps(pinned))
        checkin_path = tmp_path / 'inputs/checkin1.json'
        checkin = json.loads(checkin_path.read_text())
        checkin['work_obligations_sha256'] = __import__('hashlib').sha256(path.read_bytes()).hexdigest()
        checkin_path.write_text(json.dumps(checkin))
        from ravel.workflow import workflow_state
        from argparse import Namespace
        assert workflow_state.cmd_approve(Namespace(rundir=str(tmp_path), plan='smoke', quote='Synthetic malformed-obligation approval')) == 0
    elif fault == 'subset':
        order['obligations'] = order['obligations'][:-1]
    elif fault == 'edited_pin':
        path = tmp_path / 'inputs/work-obligations.json'
        path.write_text(path.read_text() + '\n')
    rewrite_order(tmp_path, order)
    with pytest.raises(ValueError):
        wd.adopt(tmp_path, 'N3.author', 1)
    assert not (tmp_path / 'outputs').exists()


def test_p2_n9_adoption_never_registers_custody(tmp_path, monkeypatch):
    order, workspace = fixture(tmp_path)
    import importlib
    import sys
    from types import ModuleType
    try:
        rdj_custody = importlib.import_module('ravel.workflow.rdj_custody')
    except ModuleNotFoundError:
        rdj_custody = ModuleType('ravel.workflow.rdj_custody')
        monkeypatch.setitem(sys.modules, rdj_custody.__name__, rdj_custody)
    def forbidden(*args, **kwargs):
        raise AssertionError('adopt grants no worker credit')
    monkeypatch.setattr(rdj_custody, 'register_worker_receipt', forbidden, raising=False)
    before = set(tmp_path.rglob('*'))
    result = wd.adopt(tmp_path, 'N3.author', 1)
    assert result['node_id'] == 'N3.author'
    assert (tmp_path / 'outputs/result.json').read_bytes() == (workspace / 'outputs/result.json').read_bytes()
    assert not [p for p in set(tmp_path.rglob('*')) - before if 'rdj-custody' in str(p)]


def test_p1_unicode_digest_matches_canonical_form():
    from ravel.workflow.role_registry import _digest
    order = {'statement': 'Δφ cut', 'order_sha256': 'ignored'}
    assert digest(order) == _digest({'statement': 'Δφ cut'})
    try:
        from ravel.workflow import host_governance
    except ImportError:
        return  # exact governance parity also runs on the merged tree
    assert digest(order) == host_governance.digest({'statement': 'Δφ cut'})


def test_pin_is_write_once(tmp_path):
    fixture(tmp_path)
    with pytest.raises(ValueError, match='already pinned'):
        wd.pin_obligations(tmp_path)


def test_non_json_scientific_output_uses_required_obligation_sidecar(tmp_path):
    outputs = [
        {'path': 'outputs/analysis.cpp', 'kind': 'routine', 'required': True},
        {'path': 'outputs/checks.json', 'kind': 'obligations', 'required': True}]
    order, workspace = fixture(tmp_path, declared_outputs=outputs)
    derived = wd.derive_obligations(order)
    assert derived and {o['output'] for o in derived} == {'outputs/checks.json'}
    wd.adopt(tmp_path, 'N3.author', 1)
    assert (tmp_path / 'outputs/analysis.cpp').read_bytes() == (workspace / 'outputs/analysis.cpp').read_bytes()


def test_approval_binds_obligation_sidecar_and_checkin(tmp_path):
    fixture(tmp_path)
    from ravel.workflow import workflow_state
    pin = tmp_path / 'inputs/work-obligations.json'
    assert str(pin) in workflow_state.approval_input_paths(str(tmp_path))
    assert not workflow_state.verify_approval(str(tmp_path))
    pin.write_text(pin.read_text() + '\n')
    assert workflow_state.verify_approval(str(tmp_path))
    with pytest.raises(ValueError):
        wd.adopt(tmp_path, 'N3.author', 1)


def test_self_claimed_fingerprint_is_not_approval(tmp_path):
    fixture(tmp_path)
    (tmp_path / 'inputs/checkin1_approval.json').write_text('{"work_obligations_sha256":"self-claim"}')
    with pytest.raises(ValueError, match='approval'):
        wd.adopt(tmp_path, 'N3.author', 1)


def test_science_approval_errors_are_not_discarded(tmp_path, monkeypatch):
    fixture(tmp_path)
    (tmp_path / 'inputs/checkin1_approval.json').unlink()
    (tmp_path / 'inputs/science-approval.json').write_text('{}')
    from ravel.workflow import science
    monkeypatch.setattr(science, 'verify_approval_envelope', lambda _: ['stale science approval'])
    with pytest.raises(ValueError, match='stale science approval'):
        wd.adopt(tmp_path, 'N3.author', 1)


@pytest.mark.parametrize('node', ['N..author', 'N/author', '..', 'N3.author/..'])
def test_unsafe_node_refused(tmp_path, node):
    with pytest.raises(ValueError, match='identity'):
        wd.adopt(tmp_path, node, 1)
