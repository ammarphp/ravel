"""Adversarial review-credit controls. No physics/native/model/network execution."""

from method_decision_fixture import admit_method
import hashlib
import json
from pathlib import Path

import pytest
from ravel import cli
from ravel.workflow import (review_points as rp, rdj_custody as custody,
                            run_ceilings as ceilings, scientific_judgment as judgment,
                            workflow_state as ws, evidence_queue as queue)
from test_review_points import run as point_run, receipt, write
from test_physics_review import run
from test_scientific_judgment import cycle, FakeHost, prepare
from inert_dispatch import inert_dispatch  # noqa: F401
from rdj_fixtures import Run, prepare_case


def test_real_initiate_plan_approve(tmp_path):
    root = tmp_path/'run'
    assert cli.main(['initiate', '--prompt', 'Compute a likelihood-only control for a supplied synthetic counting model.', '--out', str(root)]) == 0
    # Exercise fresh consumers before any fixture can supply a contract or plan pin.
    assert judgment.next_step(root)['phase'] == 'review_points'
    ceilings.charge(root, 'worker')
    spec = {'schema_version': 1, 'mode': 'likelihood', 'source': 'synthetic software control',
            'assumptions': ['Synthetic counting data; no physics inference is executed'],
            'max_seconds': 10, 'approval_mode': 'scripted_yes',
            'likelihood': {'counting': {'observed': 3, 'background': 4, 'background_uncertainty': 1, 'signal': 1},
                           'poi_cap': 32, 'normalization': {'kind': 'signal_events', 'luminosity_fb': 1}}}
    write(tmp_path/'spec.json', spec)
    assert cli.main(['plan', '--rundir', str(root), '--spec', str(tmp_path/'spec.json')]) == 0
    # The full launch is approved only once the run holds an admitted method decision.
    assert cli.main(['approve', '--rundir', str(root), '--quote', 'Approve this synthetic plan only.', '--scripted']) != 0
    assert ws.verify_approval(str(root)) != []
    admit_method(root)
    assert cli.main(['approve', '--rundir', str(root), '--quote', 'Approve this synthetic plan only.', '--scripted']) == 0
    assert ws.verify_approval(str(root)) == []
    contract = json.loads((root/'inputs/task_contract.json').read_text())
    for key in ('reading', 'request_plan'):
        pin = contract[key]
        assert not Path(pin['path']).is_absolute()
        assert hashlib.sha256((root/pin['path']).read_bytes()).hexdigest() == pin['sha256']
    assert not (root/'execution_state.json').exists()


@pytest.mark.parametrize('mode,registered', [
    ('human_manual', None), ('human_manual', 'self_attested'),
    ('human_manual', 'host_attested'), ('human_manual', 'transport_attested'),
    ('host_attested_external', 'self_attested'),
    ('remote_transport_observed', 'self_attested'), ('remote_transport_observed', 'host_attested'),
    ('local_transport_observed', 'self_attested'), ('local_transport_observed', 'host_attested')])
def test_receipt_body_cannot_raise_registered_strength(tmp_path, mode, registered):
    point_run(tmp_path, delegated=False, claims=[{'id': 'C1', 'kind': 'prediction'}])
    point = next(p for p in rp.pending(tmp_path) if p['row'] == 4)
    receipt(tmp_path, point['id'], point['roles'][0]['role'], execution_mode=mode, verified_label=registered)
    report = next(rp._receipt_records(tmp_path, rp._facts(tmp_path)))
    expected = 'self_attested' if mode == 'human_manual' else registered
    assert report['_label'] == expected
    if expected == 'self_attested':
        assert not rp.satisfied(tmp_path, point['id'])


@pytest.mark.parametrize('mutation', ['done', 'withdrawn', 'deleted', 'unregistered_pin'])
def test_queue_edits_cannot_disarm_registered_finding(tmp_path, mutation):
    point_run(tmp_path, delegated=False, claims=[{'id': 'C1', 'kind': 'prediction'}])
    item = queue.enqueue(tmp_path, 'case', source='critic_finding', target='F1',
                         request={'kind': 'evidence', 'description': 'Resolve the missing input'})
    finding = {'materiality': 'A', 'evidence_class': 'evidence_request', 'evidence_locators': [item['item_id']]}
    for p in rp.pending(tmp_path):
        if p['row'] != 4: continue
        role = p['roles'][0]['role']
        if role == 'physics-critic':
            write(tmp_path/'agent-work'/f'{role}1'/'1/final.json', {'findings': [finding]})
        receipt(tmp_path, p['id'], role)
    assert any(e.code == 'blocking_finding' for e in rp.gate_errors(tmp_path, 'checkin2_accept', {}))
    path = tmp_path/'rdj/queue'/f"{item['item_id']}.json"
    if mutation == 'deleted':
        path.unlink()
    else:
        item['status'] = 'withdrawn' if mutation == 'withdrawn' else 'done'
        item['resolution'] = {'pins': []}
        if mutation == 'unregistered_pin':
            pin = write(tmp_path/'outputs/answer.json', {'claim': 'resolved'})
            item['resolution']['pins'] = [pin]
        write(path, item)
    assert any(e.code == 'blocking_finding' for e in rp.gate_errors(tmp_path, 'checkin2_accept', {}))


def test_checkin_snapshot_never_vouches_planted_ceiling(tmp_path):
    point_run(tmp_path)
    custody.record_input_snapshot(tmp_path, 'run_init')
    value = ceilings.default('analysis'); value.update(source='checkin1_response', max_invocations=10**9)
    write(tmp_path/ceilings.RECORD, value)
    custody.record_input_snapshot(tmp_path, 'checkin1')
    assert ceilings.RECORD in custody.rows(tmp_path, 'inputs')[-1]['record']['unvouched']
    assert ceilings.resolve(tmp_path)['max_invocations'] == 72
    assert any('ceiling:checkin1_response' in e.pins for e in ceilings.gate_errors(tmp_path, 'launch', {}))


@pytest.mark.parametrize('gate', ['delivery', 'final_task', 'export'])
def test_calibration_acceptance_replayed_with_own_action(tmp_path, gate, inert_dispatch):
    from ravel.workflow import rdj_loop as rdj
    r = Run(tmp_path/'run', snapshot=False)
    plan = {'nodes': [{'id': 'N1', 'tuning_to_observed': True,
                      'calibration': {'non_overlap': {'regions': ['calibration', 'inference']}}}],
            'claims': [{'id': 'C1', 'kind': 'prediction'}], 'edges': []}
    pin = r.put('inputs/plan.json', plan)
    contract = json.loads((r.root/'inputs/task_contract.json').read_text())
    r.put('inputs/task_contract.json', {**contract, 'request_plan': pin})
    custody.record_input_snapshot(r.root, 'run_init')
    custody.register_host(r.root, {'fixture': 'review-credit'})
    pins = [r.action_pin, pin]
    action = r.action('tuning_change', node_id='N1', claim_id='C1', pins=pins, digest=rdj.action_digest(pins))
    cid = prepare_case(r, 'checkin2_accept', cls='R2', tuning='calibration', action=action)
    rdj.authorize(r.root, cid)
    for p in rp.pending(r.root):
        if p['roles']: receipt(r.root, p['id'], p['roles'][0]['role'], number=p['row'])
    assert rp.gate_errors(r.root, 'checkin2_accept', action) == []
    delivery = r.action('delivery', digest='d'*64)
    assert custody.rows(r.root, 'review_acceptances') == []
    assert any(e.code == 'rdj_receipt_missing' for e in rp.gate_errors(r.root, gate, delivery))
    accepted = rp.accept_checkin2(r.root, action)
    assert accepted['record']['action'] == action
    assert rp.gate_errors(r.root, gate, delivery) == []
    # The old authorization is replayed, not just looked up in a local marker.
    (r.root/f'rdj/cases/{cid}.json').write_text('{}')
    assert any(e.code == 'rdj_receipt_missing' for e in rp.gate_errors(r.root, gate, delivery))


@pytest.mark.parametrize('attestation', ['self_attested', 'transport_attested'])
def test_control_vote_never_enters_ordinary_journal(cycle, tmp_path, monkeypatch, attestation):
    from ravel.workflow import agent_graph, physics_review
    binding = prepare(cycle, tmp_path/'role', 'critic')
    judgment.execute_role(binding, FakeHost())
    original = agent_graph.role_receipt
    def observed(*args, **kwargs):
        result = original(*args, **kwargs)
        return {**result, 'execution_observation': 'control_only', 'attestation': attestation}
    monkeypatch.setattr(agent_graph, 'role_receipt', observed)
    before = physics_review._read(cycle)[1]
    with pytest.raises(ValueError, match='self-attested|control transport'):
        judgment.consume(cycle, binding, allow_control=True)
    assert physics_review._read(cycle)[1] == before
    assert physics_review.status(cycle)['state'] == 'awaiting_review'
    assert physics_review.gate_errors(cycle, 'delivery')


def test_science_v2_status_and_open_do_not_require_forbidden_contract(tmp_path):
    from test_science_workflow import fixture
    from ravel.workflow import science
    root, spec = fixture(tmp_path)
    science.plan(root, spec); admit_method(root)
    assert not (root/'inputs/task_contract.json').exists()
    assert judgment.next_step(root)['phase'] == 'open_cycle'
    science.approve(root, 'Approve synthetic preparation only', scripted=True)
    with pytest.raises(ValueError, match='FAILED work'):
        judgment.open_cycle(root, check_results='inputs/checks.json')


def test_registered_external_answer_clears_request_and_rechecks_bytes(tmp_path):
    point_run(tmp_path)
    answer = write(tmp_path/'inputs/answer.json', {'measurement': 1})
    answer['path'] = 'inputs/answer.json'
    custody.record_input_snapshot(tmp_path, 'run_init')
    item = queue.enqueue(tmp_path, 'case', source='critic_finding', target='F1',
                         request={'kind': 'evidence', 'description': 'Supply the measurement'})
    finding = {'materiality': 'A', 'evidence_class': 'evidence_request', 'evidence_locators': [item['item_id']]}
    assert rp.blocking_finding(tmp_path, finding)
    queue.resolve(tmp_path, item['item_id'], status='done', note='Original external measurement', pins=[answer])
    assert not rp.blocking_finding(tmp_path, finding)
    (tmp_path/answer['path']).write_text('{}')
    assert rp.blocking_finding(tmp_path, finding)


@pytest.mark.parametrize('mode', ['transport_attested_cli', 'remote_transport_observed', 'local_transport_observed',
                                  'host_attested_external', 'relay_schema_1', 'relay_schema_2', 'control_only'])
@pytest.mark.parametrize('registered', [None, 'self_attested', 'host_attested', 'transport_attested'])
def test_all_mode_labels_respect_custody_ceiling(mode, registered):
    from ravel.workflow.decision_case import ATTESTATION_RANK
    label = rp.attestation_label({'execution_mode': mode, 'attestation': 'transport_attested'}, registered)
    assert ATTESTATION_RANK[label] <= ATTESTATION_RANK[registered or 'self_attested']
    if mode in {'relay_schema_1', 'relay_schema_2', 'control_only'}:
        assert label == 'self_attested'


def test_positive_launch_unblind_uses_same_launch_action(tmp_path, inert_dispatch):
    from ravel.workflow import rdj_loop as rdj
    from rdj_fixtures import record_decision
    r = Run(tmp_path/'run', snapshot=False)
    pin = r.put('inputs/plan.json', {'nodes': [{'id': 'N1', 'observed_statistic': True}], 'claims': []})
    contract = json.loads((r.root/'inputs/task_contract.json').read_text())
    r.put('inputs/task_contract.json', {**contract, 'request_plan': pin})
    custody.record_input_snapshot(r.root, 'run_init')
    custody.register_host(r.root, {'fixture': 'same launch action at unblind'})
    action = r.action('bulk_launch', node_id='N1')
    cid = prepare_case(r, 'unblind', cls='R3', action=action)
    record_decision(r, 'approve', case_id=cid)
    rdj.authorize(r.root, cid)
    assert rp.gate_errors(r.root, 'launch', action) == []
    from ravel.workflow import decision_gate
    # The row-17 proof does not stand in for launch authorization or executor.
    errors = decision_gate.check(r.root, 'launch', action)
    assert any(e.provider == 'rdj' for e in errors)
    # The registered executor provider passes a launch that names no worker rung and refuses
    # the same launch at the full rung, whose node has no sealed work order.
    assert all(p['active'] for p in decision_gate.providers('launch') if p['id'] == 'executor')
    assert not any(e.provider == 'executor' for e in errors)
    full = decision_gate.check(r.root, 'launch', {**action, 'rung': 'full'})
    assert any(e.provider == 'rdj' for e in full)
    assert [e.code for e in full if e.provider == 'executor'] == ['executor_order_invalid']


def test_unicode_intake_pins_match_canonical_reading_bytes(tmp_path):
    from ravel.validation.validate_task_contract import validate_pins
    root = tmp_path/'run'
    assert cli.main(['initiate', '--prompt', 'Summarize published ATLAS limits for Z′ → WW.', '--out', str(root)]) == 0
    contract = json.loads((root/'inputs/task_contract.json').read_text())
    assert 'request_plan' in contract
    assert validate_pins(root, contract) == []


def test_failed_draft_cannot_create_legacy_run(tmp_path, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, 'ravel.workflow.request_plan', None)
    root = tmp_path/'run'
    assert cli.main(['initiate', '--prompt', 'Summarize published ATLAS limits.', '--out', str(root)]) == 2
    assert not root.exists()
