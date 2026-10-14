"""Merged decision control: real review gate -> RDJ -> custody; no network or physics tools."""
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

# Also collectable as an explicit file without the unit suite in the invocation.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unit'))
from rdj_fixtures import (Run, Roles, PROPOSER, add, node, prepare_case, escalate,
                          critic, verifier, record_decision)
from test_review_points import receipt
from ravel.workflow import review_points as rp, decision_gate as dg, rdj_loop as rdj, rdj_custody as custody
from ravel.workflow import run_ceilings


def guard():
    src = Path(__file__).resolve().parents[2] / 'src'
    assert all(Path(m.__file__).resolve().is_relative_to(src) for m in (rdj, custody))
    assert not any(isinstance(sys.modules.get(m.__name__), SimpleNamespace) for m in (rdj, custody))


@pytest.fixture
def joined(tmp_path, monkeypatch):
    guard()  # First assertion: the real modules from this integration tree.
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path/'custody'))
    r = Run(tmp_path/'run', snapshot=False)
    plan = {'nodes': [
        {'id': 'N1', 'tuning_to_observed': True, 'calibration': {'non_overlap': {'regions': ['calibration', 'inference']}}},
        {'id': 'N2', 'observed_statistic': True}],
        'claims': [{'id': 'C1', 'absolute_yield': True}], 'edges': []}
    pin = r.put('inputs/plan.json', plan)
    c = json.loads((r.root/'inputs/task_contract.json').read_text())
    r.put('inputs/task_contract.json', {**c, 'delegated': True, 'request_plan': pin})
    r.put(run_ceilings.RECORD, run_ceilings.default('analysis'))
    rp.approve(r.root)
    custody.record_input_snapshot(r.root, 'run_init')
    r.put(custody.CI1_RESPONSE, (r.root/run_ceilings.RECORD).read_bytes())
    custody.record_user_text(r.root, 'checkin1_response', custody.CI1_RESPONSE)
    custody.record_input_snapshot(r.root, 'checkin1')
    custody.register_host(r.root, {'fixture': 'decision-control'})
    return r


def action(r):
    pins = [r.action_pin, r.pin('inputs/plan.json')]
    return r.action('tuning_change', claim_id='C1', pins=pins, digest=rdj.action_digest(pins))


def staff(root):
    """Independent, registered receipts for every derived staffing row that holds CHECK-IN 2."""
    from ravel.workflow import spawn_rows
    facts = rp._facts(root)
    for p in spawn_rows.pending(root):
        if p['gate'] != 'checkin2_accept':
            continue
        for role in p['roles']:
            for n in range(role['count']):
                ident = f"{p['id'].replace(':', '-')}-{role['role']}-{n}"
                final = root/'agent-work'/ident/'1/final.json'
                final.parent.mkdir(parents=True, exist_ok=True)
                final.write_text('{"findings": []}')
                rec = {'schema_version': 2, 'kind': 'agent-worker-receipt', 'node_id': ident, 'attempt': 1,
                       'review_point_id': p['id'], 'role': {'id': role['role']}, 'status': 'ok',
                       'execution_mode': 'transport_attested_cli', 'attestation': 'transport_attested',
                       'review_subject': rp.review_subject(facts, p),
                       'session_id': ident, 'actor_id': ident, 'model': {'family': ident},
                       'run_tree': {'modified': False}, 'final_record': {'valid': True, 'path': 'final.json',
                       'sha256': hashlib.sha256(final.read_bytes()).hexdigest()}}
                path = final.parent/'receipt.json'
                path.write_text(json.dumps(rec))
                custody.register_worker_receipt(root, path.relative_to(root).as_posix(),
                                                verified_label='transport_attested')


def reviews(r, **kwargs):
    for p in rp.derive(rp._facts(r.root)):
        if p['row'] in {4, 5}:
            receipt(r.root, p['id'], p['roles'][0]['role'], **kwargs)
    staff(r.root)


def authorize(r):
    reviews(r)
    cid = prepare_case(r, 'checkin2_accept', cls='R2', tuning='calibration', action=action(r), roles=Roles())
    value = rdj.authorize(r.root, cid)
    return value


def test_l1_missing_reviews_and_rdj(joined):
    errors = dg.check(joined.root, 'checkin2_accept', action(joined))
    assert {'review_point_pending', 'rdj_receipt_missing'} <= {e.code for e in errors}
    assert all(e.pins for e in errors)
    assert any('RP5:' in pin for e in errors for pin in e.pins)
    assert {e.provider for e in errors if e.code == 'rdj_receipt_missing'} == {'review_points', 'rdj'}


def test_l2_forged_transport_receipts(joined):
    reviews(joined, register=False)
    errors = dg.check(joined.root, 'checkin2_accept', action(joined))
    assert len([e for e in errors if e.code == 'review_point_pending' and any('RP4:' in p for p in e.pins)]) == 3
    assert any(e.code == 'rdj_receipt_missing' for e in errors)


def test_l3_registered_self_attested(joined):
    reviews(joined, execution_mode='relay_schema_2', verified_label=None)
    assert any(e.code == 'review_point_pending' for e in dg.check(joined.root, 'checkin2_accept', action(joined)))
    assert all(not rec['independent'] for p in rp.pending(joined.root) for rec in p['receipts'])


def test_l4_real_authorization_and_same_receipt(joined):
    value = authorize(joined)
    assert dg.check(joined.root, 'checkin2_accept', action(joined)) == []
    accepted = rdj.authorizing_receipt(joined.root, 'checkin2_accept', {**action(joined), 'floor': 'R2'})
    assert accepted['receipt']['receipt_id'] == value['receipt_id']
    point = next(p for p in rp.derive(rp._facts(joined.root)) if p['row'] == 16)
    assert rp._rdj_errors(joined.root, point, 'checkin2_accept', action(joined)) == []


def test_l5_unknown_node(joined):
    authorize(joined)
    assert 'action_scope_invalid' in {e.code for e in dg.check(joined.root, 'checkin2_accept', {**action(joined), 'node_id': 'N9'})}


def test_l6_changed_claim(joined):
    authorize(joined)
    a = action(joined)
    plan = json.loads((joined.root/'inputs/plan.json').read_text())
    plan['claims'][0]['absolute_yield'] = False
    joined.put('inputs/plan.json', plan)
    errors = dg.check(joined.root, 'checkin2_accept', a)
    assert {'gate_inputs_invalid', 'review_point_pending'} <= {e.code for e in errors}
    assert any(e.provider == 'rdj' for e in errors)


def test_l7_removed_calibration_separation(joined):
    authorize(joined)
    plan = json.loads((joined.root/'inputs/plan.json').read_text())
    plan['nodes'][0]['calibration'].clear()
    joined.put('inputs/plan.json', plan)
    assert 'obligations_changed' in {e.code for e in dg.check(joined.root, 'delivery', action(joined))}


def test_l8_unblind_needs_recorded_human(joined):
    a = joined.action('unblind', node_id='N2')
    cid = prepare_case(joined, 'unblind', cls='R3', action=a)
    assert 'rdj_receipt_missing' in {e.code for e in dg.check(joined.root, 'unblind', a)}
    with pytest.raises(rdj.OpenItems):
        rdj.authorize(joined.root, cid)
    record_decision(joined, 'approve', case_id=cid)
    rdj.authorize(joined.root, cid)
    assert dg.check(joined.root, 'unblind', a) == []


def test_l9_negated_steering_does_not_reopen(joined):
    _, digest = escalate(joined)
    joined.steering('Do not reopen ' + digest[:12])
    with pytest.raises(ValueError, match='escalat'):
        rdj.open_case(joined.root, 'launch', joined.action(), PROPOSER)
    assert dg.check(joined.root, 'launch', joined.action())


def test_l10_empty_write_log_cannot_vouch(tmp_path, monkeypatch):
    guard()
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path/'custody'))
    r = Run(tmp_path/'run')
    r.put('agent-audit/writes.jsonl', '')
    pin = r.put('inputs/x.json', {'checked': True})
    custody.record_input_snapshot(r.root, 'checkin1')
    cid = rdj.open_case(r.root, 'launch', r.action(), PROPOSER)
    add(r, cid, 'action', node('A', 'The input supports this action', anchors=[
        {'kind': 'input_artifact', 'binding': pin, 'locator': '/checked'}]))
    rdj.run_roles(r.root, cid, Roles())
    assert r.case(cid)['anchors'][0]['verified'] == 'generated'
    with pytest.raises(rdj.OpenItems): rdj.authorize(r.root, cid)
    assert dg.check(r.root, 'launch', r.action())


def test_l11_epoch_downgrade(joined):
    c = json.loads((joined.root/'inputs/task_contract.json').read_text()); c.pop('agent_layer_epoch')
    joined.put('inputs/task_contract.json', c)
    for g in ('launch', 'delivery', 'export'):
        assert 'gate_inputs_invalid' in {e.code for e in dg.check(joined.root, g, action(joined))}


def test_l12_executor_active(joined):
    """The executor provider is active: a launch without a worker rung is the host's own, and a full-rung
    launch of a node without a sealed work order is refused."""
    errors = dg.check(joined.root, 'launch', joined.action(node_id='N1'))
    assert [e.code for e in errors if e.provider == 'executor'] == []
    errors = dg.check(joined.root, 'launch', joined.action(node_id='N1', rung='full'))
    assert [e.code for e in errors if e.provider == 'executor'] == ['executor_order_invalid']


def test_l12_executor_decides_worker_rungs(joined):
    """R2/R3 leg: the registered executor refuses a full launch without the node's worker receipt
    or waiver, and leaves a smoke launch to the other providers."""
    full = dg.check(joined.root, 'launch', joined.action(node_id='N1', rung='full'))
    assert [e.code for e in full if e.provider == 'executor'] in (['executor_order_invalid'], ['executor_receipt_missing'])
    smoke = dg.check(joined.root, 'launch', joined.action(node_id='N1', rung='smoke'))
    assert not [e for e in smoke if e.provider == 'executor']


def test_l13_file_is_not_code_check(joined):
    f = {'id': 'F1', 'code': 'missing_evidence', 'targets': ['L1'], 'materiality': 'A',
         'evidence_class': 'code_check', 'evidence_locators': ['inputs/cards/settings.json'], 'request': None}
    roles = Roles(critic=critic([f]), verifier=verifier(resolved='no'))
    cid = prepare_case(joined, 'checkin2_accept', cls='R2', tuning='calibration', action=action(joined), roles=roles)
    state = json.loads((joined.root/f'rdj/state/{cid}.json').read_text())
    assert state['finding_basis']['F1'] != 'verified'
    assert not rp.blocking_finding(joined.root, f)
    assert rdj.authorize(joined.root, cid)['outcome'] == 'authorize'
    reviews(joined)
    assert dg.check(joined.root, 'checkin2_accept', action(joined)) == []
