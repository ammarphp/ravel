"""Waypoint policy credit binds the exact current round and accepted output subject."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

import fakes
from ravel.controller import graph
from ravel.controller.engagement import policy as engagement
from ravel.controller.routes import compiler
from ravel.controller.step import custody
from ravel.workflow import rdj_approval, request_plan, review_dispatch, review_points as policy, spawn_rows


def point(role='normalization-auditor', **over):
    return {'id': 'P1', 'row': 9, 'gate': 'checkin2_accept', 'blocking': True,
            'mode': 'specialist', 'roles': [{'role': role, 'count': 1}], **over}


def staffing(monkeypatch, points, checkins):
    monkeypatch.setattr(request_plan, 'draft', lambda *args: {'nodes': [], 'claims': []})
    monkeypatch.setattr(policy, 'derive', lambda facts: deepcopy(points))
    monkeypatch.setattr(spawn_rows, 'derive', lambda facts: [])
    return compiler._policy_checkins(checkins, {}, {'agent_layer_epoch': 2})


def test_waypoint_staffing_preserves_order_aliases_and_final_policy(monkeypatch):
    checkins = [{'id': 'checkin2', 'sections': ['executed'], 'seats': ['physics-reviewer']},
                {'id': 'checkin3', 'sections': ['results'], 'seats': ['physics-reviewer']}]
    original = deepcopy(checkins)
    points = [point('physics-critic'), point(), point('figure-critic'), point(),
              point('trap-auditor', blocking=False), point('analysis-author', mode='producer'),
              point('plan-critic', gate='approve_plan'), point('integrity-auditor', gate='delivery')]
    result = staffing(monkeypatch, points, checkins)
    waypoint = next(row for row in result if row['id'] == 'checkin2')
    assert waypoint == {'id': 'checkin2', 'sections': ['executed'],
                        'seats': ['physics-reviewer', 'normalization-auditor', 'figure-critic'],
                        'review_points': points[:4]}
    final = next(row for row in result if row['id'] == 'checkin3')
    assert final['seats'] == ['physics-reviewer', 'normalization-auditor', 'figure-critic', 'integrity-auditor']
    assert checkins == original


def test_missing_waypoint_checkin_keeps_default_seats(monkeypatch):
    result = staffing(monkeypatch, [point()], [])
    waypoint = next(row for row in result if row['id'] == 'checkin2')
    assert waypoint == {'id': 'checkin2', 'sections': [],
                        'seats': list(graph.CI2_SEATS) + ['normalization-auditor'],
                        'review_points': [point()]}


def test_new_waypoint_checkin_precedes_existing_final_without_reordering_existing_rows(monkeypatch):
    checkins = [{'id': 'checkin1', 'seats': ['plan-critic']},
                {'id': 'checkin3', 'sections': ['results'], 'seats': ['physics-reviewer']}]
    result = staffing(monkeypatch, [point()], checkins)
    assert [row['id'] for row in result] == ['checkin1', 'checkin2', 'checkin3']
    assert result[-1]['sections'] == ['results']
    assert checkins == [{'id': 'checkin1', 'seats': ['plan-critic']},
                        {'id': 'checkin3', 'sections': ['results'], 'seats': ['physics-reviewer']}]


def test_epoch_one_keeps_declared_checkins_without_policy_derivation(monkeypatch):
    def forbidden(*args):
        raise AssertionError('epoch one must not derive policy staffing')
    monkeypatch.setattr(request_plan, 'draft', forbidden)
    checkins = [{'id': 'checkin2', 'seats': ['physics-reviewer']}]
    assert compiler._policy_checkins(checkins, {}, {'agent_layer_epoch': 1}) == checkins


@pytest.mark.parametrize('tier', ['lean', 'standard', 'full'])
def test_compiled_waypoint_specialists_keep_duties_without_classifying_unlisted_roles(monkeypatch, tier):
    request = {'nodes': [], 'inputs': [], 'edges': [], 'claims': [{
        'id': 'C1', 'kind': 'prediction', 'basis_declared': ['generated_prediction'],
        'deliverable': {'artifact': 'table'}}]}
    monkeypatch.setattr(request_plan, 'draft', lambda *args: deepcopy(request))
    route = fakes._spec('analysis', 6, {'field': 'task_mode', 'eq': 'calculate'},
                        [fakes.make_step('s1', waypoint=True, outputs=['outputs/result.json'])], [])
    plan = compiler.compile(route, {}, {'agent_layer_epoch': 2})
    checkin = next(row for row in plan['checkins'] if row['id'] == 'checkin2')
    assert 'normalization-auditor' in checkin['seats']
    roster = engagement.seat_plan(plan, tier)
    key = 'checkin:checkin2:normalization-auditor'
    assert not roster['errors']
    seat, = [row for row in roster['seats'] if row['key'] == key]
    assert seat['rule'] == 'keep'
    bad = deepcopy(plan)
    next(row for row in bad['checkins'] if row['id'] == 'checkin2')['seats'].append('baseline-producer')
    refused = engagement.seat_plan(bad, tier)
    assert 'unclassified seat kept: checkin:checkin2:baseline-producer' in refused['errors']


def test_phase_mapping_keeps_default_and_delivery_final():
    p = point('physics-reviewer')
    assert policy._controller_step(p) == 'final_review'
    assert policy._controller_step(p, gate='delivery', role='physics-reviewer') == 'final_review'
    assert policy._controller_step(p, gate='checkin2_accept', role='physics-reviewer') == 'waypoint_review.physics-critic'


@pytest.fixture
def current_round(tmp_path, monkeypatch):
    plan = {'sha256': 'a' * 64, 'waypoints': ['measure']}
    output = {'artifact': 'measure:outputs/value.json', 'path': 'outputs/value.json',
              'sha256': 'b' * 64, 'artifact_id': 'value-id', 'attempt': 1, 'record_id': 'custody-1'}
    outcomes = {'measure': {'step_id': 'measure', 'status': 'completed', 'outputs': [output]}}
    subject = graph.waypoint_subject(plan['waypoints'], outcomes)
    role, step_id = 'normalization-auditor', 'waypoint_review.normalization-auditor'
    records = {
        'review': [{'id': 'round-2', 'record': {
            'purpose': 'waypoint', 'plan_sha256': plan['sha256'], 'attempt': 2,
            'subject_sha256': subject['sha256'], 'subject': deepcopy(subject['pins']),
            'seats': {role: {'status': 'completed', 'credited': True, 'verdict': 'accept', 'step': step_id}}}}],
        'review-session': [{'id': 'review-session-2', 'record': {
            'session_id': 'worker-session:fictional:session-2', 'transport_id': 'fictional',
            'role': role, 'step_id': step_id}}],
        'worker-session': [{'id': 'worker-session-2', 'record': {
            'run_id': 'run', 'session_id': 'session-2', 'step': step_id, 'attempt': 2,
            'receipt_sha256': 'c' * 64, 'step_spec': {
                'id': step_id, 'role': role, 'parameters': {'purpose': 'waypoint',
                    'subject_plan_sha256': plan['sha256'], 'subject_sha256': subject['sha256']}}}}],
        'step-credit': [{'id': 'credit-2', 'record': {'step_id': step_id, 'attempt': 2,
            'own': {'query': {'role': role}}}}],
    }
    class Store:
        run_id = 'run'
        run_dir = tmp_path

        def scan(self, kind):
            return records.get(kind, [])

        def read(self, kind, identifier):
            return next(row for row in self.scan(kind) if row['id'] == identifier)

    store = Store()
    accepted = {output['artifact']: {**{key: value for key, value in output.items() if key != 'record_id'},
                                    '_record_id': output['record_id'], 'step_id': 'measure', 'status': 'accepted'}}
    calls = []

    def seat_review(actual_store, actual_step, actual_role, actual_plan, **kwargs):
        calls.append((actual_step, actual_role, actual_plan))
        assert actual_store is store
        if actual_step not in (step_id, 'final_review') or actual_role != role or actual_plan != plan['sha256']:
            return None, 'no matching observed seat'
        return {'role': role, 'credit': 'credit-2', 'session_record': 'review-session-2',
                'session': 'worker-session:fictional:session-2'}, None

    monkeypatch.setattr(rdj_approval, 'controller_plan', lambda directory: (store, plan))
    monkeypatch.setattr(rdj_approval, 'seat_review', seat_review)
    monkeypatch.setattr(custody, 'outcomes', lambda actual: outcomes)
    monkeypatch.setattr(custody, 'custody_index', lambda actual: accepted)
    # Byte/chain verification is a separate external boundary; retain its explicit result.
    monkeypatch.setattr(custody, '_verify', lambda *args: [])
    pins = {'plan_sha256': plan['sha256'], 'checkin2_review': 'round-2', **subject['pins']}
    action = {'digest': policy.jdigest(pins), 'view_pins': pins}
    return SimpleNamespace(store=store, plan=plan, records=records, accepted=accepted,
                           outcomes=outcomes, action=action, calls=calls, role=role, step_id=step_id)


def test_exact_current_waypoint_round_credits_matching_observed_seat(current_round):
    fixture = current_round
    missing, evidence = policy._controller_missing(fixture.store.run_dir, [point()],
                                                   gate='checkin2_accept', action=fixture.action)
    assert missing == {'P1': []}
    assert evidence['P1'][0]['step_id'] == fixture.step_id
    assert fixture.calls == [(fixture.step_id, fixture.role, fixture.plan['sha256'])]


@pytest.mark.parametrize('fault', ['changedsubject', 'wrongplan', 'missinground', 'wrongpins',
    'revised', 'otherrole', 'earlierround', 'oldcredit', 'oldsession', 'wrongstep',
    'unaccepted', 'custodychanged', 'duplicateoutput', 'byteschanged', 'wrongpurpose', 'roundsubject',
    'waypointpins', 'pinplan', 'missingoutput', 'duplicatesession', 'wrongworkerrole',
    'wrongsession', 'roundattempt', 'uncompleted'])
def test_waypoint_credit_refuses_stale_or_unmatched_subject(current_round, monkeypatch, fault):
    fixture = current_round
    row = fixture.records['review'][0]['record']
    worker = fixture.records['worker-session'][0]['record']
    if fault == 'changedsubject': worker['step_spec']['parameters']['subject_sha256'] = 'd' * 64
    if fault == 'wrongplan': worker['step_spec']['parameters']['subject_plan_sha256'] = 'd' * 64
    if fault == 'missinground': fixture.records['review'].clear()
    if fault == 'wrongpins': fixture.action['digest'] = 'd' * 64
    if fault == 'revised': row['seats'][fixture.role]['verdict'] = 'revise'
    if fault == 'otherrole': row['seats'] = {'figure-critic': row['seats'][fixture.role]}
    if fault == 'earlierround':
        latest = deepcopy(fixture.records['review'][0]); latest['id'] = 'round-3'; latest['record']['attempt'] = 3
        fixture.records['review'].append(latest)
    if fault == 'oldcredit': fixture.records['step-credit'][0]['record']['attempt'] = 1
    if fault == 'oldsession': worker['attempt'] = 1
    if fault == 'wrongstep': row['seats'][fixture.role]['step'] = 'final_review'
    if fault == 'unaccepted': next(iter(fixture.accepted.values()))['status'] = 'rejected'
    if fault == 'custodychanged': next(iter(fixture.accepted.values()))['sha256'] = 'd' * 64
    if fault == 'duplicateoutput': fixture.outcomes['measure']['outputs'] *= 2
    if fault == 'byteschanged': monkeypatch.setattr(custody, '_verify', lambda *args: [{'code': 'changed'}])
    if fault == 'wrongpurpose': row['purpose'] = 'final'
    if fault == 'roundsubject': row['subject_sha256'] = 'd' * 64
    if fault in ('waypointpins', 'pinplan'):
        key = 'waypoint:measure' if fault == 'waypointpins' else 'plan_sha256'
        fixture.action['view_pins'][key] = 'd' * 64
        fixture.action['digest'] = policy.jdigest(fixture.action['view_pins'])
    if fault == 'missingoutput': fixture.outcomes['measure']['outputs'] = []
    if fault == 'duplicatesession': fixture.records['worker-session'] *= 2
    if fault == 'wrongworkerrole': worker['step_spec']['role'] = 'figure-critic'
    if fault == 'wrongsession': worker['session_id'] = 'another-session'
    if fault == 'roundattempt': row['attempt'] = 1
    if fault == 'uncompleted': row['seats'][fixture.role]['status'] = 'held'
    missing, evidence = policy._controller_missing(fixture.store.run_dir, [point()],
                                                   gate='checkin2_accept', action=fixture.action)
    assert missing['P1']
    assert evidence['P1'] == []


def test_delivery_still_requires_final_review(current_round):
    fixture = current_round
    missing, evidence = policy._controller_missing(fixture.store.run_dir, [point()],
                                                   gate='delivery', action=fixture.action)
    assert missing == {'P1': []}
    assert evidence['P1'][0]['step_id'] == 'final_review'
    assert fixture.calls[0][0] == 'final_review'


@pytest.mark.parametrize('method', ['gate_errors', 'gate_evidence'])
def test_gate_interfaces_forward_exact_phase_and_action(current_round, monkeypatch, method):
    fixture = current_round
    contract = fixture.store.run_dir / 'inputs/task_contract.json'
    contract.parent.mkdir(); contract.write_text('{}')
    monkeypatch.setattr(rdj_approval, 'applies', lambda directory: True)
    monkeypatch.setattr(policy, '_facts', lambda directory: {'agent_layer_epoch': 2, 'plan': {}})
    monkeypatch.setattr(policy, 'derive', lambda facts: [point()])
    calls = []

    def missing(directory, points, *, gate=None, action=None):
        calls.append((gate, action))
        return {'P1': []}, {'P1': []}

    monkeypatch.setattr(policy, '_controller_missing', missing)
    getattr(policy, method)(fixture.store.run_dir, 'checkin2_accept', fixture.action)
    assert calls == [('checkin2_accept', fixture.action)]


def test_compiled_route_without_a_waypoint_keeps_specialists_at_final_review(monkeypatch):
    request = {'nodes': [], 'inputs': [], 'edges': [], 'claims': [{
        'id': 'C1', 'kind': 'prediction', 'basis_declared': ['generated_prediction'],
        'deliverable': {'artifact': 'table'}}]}
    monkeypatch.setattr(request_plan, 'draft', lambda *args: deepcopy(request))
    route = fakes._spec('bounded', 6, {'field': 'task_mode', 'eq': 'calculate'},
                       [fakes.make_step('s1', outputs=['outputs/result.json'])], [])
    plan = compiler.compile(route, {}, {'agent_layer_epoch': 2})
    assert plan['waypoints'] == []
    assert not any(row['id'] == 'checkin2' for row in plan['checkins'])
    final = next(row for row in plan['checkins'] if row['id'] == 'checkin3')
    assert 'normalization-auditor' in final['seats']
