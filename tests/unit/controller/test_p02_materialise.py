"""P02 materialisation: each stage instantiates exactly the obligations that apply, with its instance keys."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from ravel.controller import ledger
from ravel.controller.ledger import state as state_module
from p02_support import (INTAKE, PLAN, RUN, FakeStore, fixture_catalogue, fixture_store,  # noqa: F401
                              use_catalogue)

SCHEMA = Path(ledger.__file__).resolve().parents[2] / 'data' / 'controller' / 'schemas' / 'ledger-entry.v1.json'


def ids(keys):
    return sorted(keys)


def k(row, **scope):
    return ledger.instance_key(row, RUN, scope)


def started(store, intake=INTAKE, plan=PLAN, route='analysis'):
    ledger.materialise(store, 'intake', intake)
    return ledger.materialise(store, 'plan', {'plan': plan, 'route': route})


# ---- intake ---------------------------------------------------------------------------------------------

def test_p02_intake_instantiates_run_rows_and_one_entry_per_original_obligation(fixture_store):
    keys = ledger.materialise(fixture_store, 'intake', INTAKE)
    assert ids(keys) == ids([k('X-INTAKE'), k('X-ROUTE'), k('X-STANDING'), k('X-LABEL'),
                             k('X-KEEP', deliverable='D1'), k('X-KEEP', deliverable='D2')])


@pytest.mark.parametrize('task_mode,included', [('scan', True), ('reproduce', False), (None, True)])
def test_p02_intake_task_mode_rows_follow_the_reading_and_stay_when_unknown(fixture_store, task_mode, included):
    keys = ledger.materialise(fixture_store, 'intake', {'run_id': RUN, 'task_mode': task_mode})
    assert (k('X-MODE-scan') in keys) is included


def test_p02_intake_is_pinned_once(fixture_store):
    first = ledger.materialise(fixture_store, 'intake', INTAKE)
    events = len(fixture_store.scan('ledger'))
    assert ledger.materialise(fixture_store, 'intake', dict(INTAKE)) == first
    assert len(fixture_store.scan('ledger')) == events
    with pytest.raises(ledger.LedgerError) as raised:
        ledger.materialise(fixture_store, 'intake', {**INTAKE, 'deliverables': ['D1']})
    assert raised.value.code == 'intake_repeated'


def test_p02_intake_refuses_a_provider_registry_the_catalogue_does_not_pin(tmp_path, monkeypatch):
    use_catalogue(monkeypatch, fixture_catalogue(registry_sha256='e' * 64))
    store = FakeStore(RUN, root=tmp_path)
    with pytest.raises(ledger.LedgerError) as raised:
        ledger.materialise(store, 'intake', INTAKE)
    assert raised.value.code == 'provider_registry_unpinned'
    assert store.scan('ledger') == []


def test_p02_later_stages_need_the_intake_pin(fixture_store):
    with pytest.raises(ledger.LedgerError) as raised:
        ledger.materialise(fixture_store, 'plan', {'plan': PLAN})
    assert raised.value.code == 'not_materialised'
    with pytest.raises(ledger.LedgerError) as raised:
        ledger.materialise(fixture_store, 'audit', {})
    assert raised.value.code == 'stage_unknown'


# ---- plan -------------------------------------------------------------------------------------------------

def test_p02_plan_instantiates_step_waypoint_point_check_in_and_gate_rows(fixture_store):
    keys = started(fixture_store)
    assert ids(keys) == ids([
        k('X-CI1'), k('CHECKIN-1'), k('CHECKIN-3'), k('X-CI3'), k('GATE-approve_plan'),
        k('X-OP-alpha', step='s1'), k('X-STEPDOC', step='s1'),
        k('X-SEATDERIV', step='s1'), k('X-SEATDERIV', step='s2'),
        k('GATE-launch', step='s1'), k('GATE-launch', step='s2'),
        k('X-CI2', step='s1'), k('CHECKIN-2', step='s1'), k('GATE-checkin2_accept', step='s1'),
        k('X-POINT', step='s2', point='p1'), k('X-POINT', step='s2', point='p2'),
        k('X-KEEP', deliverable='D1'), k('X-KEEP', deliverable='D2')])


@pytest.mark.parametrize('route,frame', [('analysis', 'absent'), ('judgment', 'run'), (None, 'run')])
def test_p02_route_rows_follow_the_selected_route_and_stay_when_it_is_unknown(fixture_store, route, frame):
    plan = {**PLAN, 'route': None}
    keys = started(fixture_store, plan=plan, route=route)
    assert (k('X-FRAME') in keys) is (frame == 'run')


def test_p02_route_rows_follow_a_child_route_step(fixture_store):
    plan = copy.deepcopy(PLAN)
    plan['steps'].append({'id': 's3', 'kind': 'route', 'route': 'judgment', 'instruction_sources': []})
    keys = started(fixture_store, plan=plan, route='analysis')
    assert k('X-FRAME', step='s3') in keys and k('X-FRAME') not in keys


def test_p02_declared_obligations_add_rows_and_unknown_ones_are_refused(fixture_store):
    plan = copy.deepcopy(PLAN)
    plan['obligations'] = ['X-OP-*']
    plan['steps'][1]['obligations'] = ['X-FRAME']
    plan['steps'][1]['gates'] = ['deviation']
    keys = started(fixture_store, plan=plan)
    assert k('X-OP-alpha', step='s2') in keys     # a plan-level pattern reaches every step
    assert k('X-FRAME') in keys                    # a step-declared run row
    assert k('GATE-deviation', step='s2', event='deviation') in keys
    bad = copy.deepcopy(PLAN)
    bad['steps'][0]['obligations'] = ['NO-SUCH-ROW']
    with pytest.raises(ledger.LedgerError) as raised:
        ledger.materialise(fixture_store, 'plan', {'plan': bad})
    assert raised.value.code == 'obligation_unknown'


def test_p02_plan_accepts_the_compiled_plan_shapes(fixture_store):
    ledger.materialise(fixture_store, 'intake', INTAKE)
    flat = {'run_id': RUN, 'plan_sha256': 'a' * 64, 'route': 'analysis',
            'steps': [{'id': 's1', 'kind': 'operate', 'operation': 'alpha', 'role': 'maker', 'obligations': [],
                       'graph': {'id': 'research.loop'}, 'waypoint': True, 'depends_on': [], 'review': [],
                       'instruction_sources': [], 'deliverables': ['D1']}],
            'deliverables': [{'id': 'D1', 'status': 'mapped', 'step': 's1', 'output': 'outputs/a.json'},
                             {'id': 'D2', 'status': 'open', 'step': None, 'reason': 'no step produces it'}],
            'open_obligations': [{'kind': 'deliverable', 'id': 'D2', 'reason': 'no step produces it'},
                                 {'kind': 'parameter', 'id': 'parameter:energy', 'name': 'energy'}]}
    keys = ledger.materialise(fixture_store, 'plan', flat)
    plan = state_module.load(fixture_store, full=True).plan
    assert plan['plan_sha256'] == 'a' * 64 and plan['route'] == 'analysis'
    assert plan['deliverables'] == [{'id': 'D1', 'steps': ['s1'], 'open': False},
                                    {'id': 'D2', 'steps': [], 'open': True}]
    assert plan['steps'][0]['graph'] == 'research.loop'
    assert plan['open_obligations'][1] == {'kind': 'parameter', 'id': 'parameter:energy', 'reason': None}
    assert k('X-CI2', step='s1') in keys and k('X-OP-alpha', step='s1') in keys


@pytest.mark.parametrize('mutate,message', [
    (lambda p: p['steps'].append(dict(p['steps'][0])), 'not unique'),
    (lambda p: p.update(waypoints=['s9']), 'not plan steps'),
    (lambda p: p['steps'][1].update(depends_on=['s9']), 'unknown steps'),
    (lambda p: p['deliverables'].append({'id': 'D1', 'steps': ['s1']}), 'mapped twice'),
    (lambda p: p['deliverables'].append({'id': 'D3', 'steps': ['s9']}), 'unknown steps'),
    (lambda p: p['steps'][0].update(review=['checker', 'checker'], seats=[{'seat': 'a'}, {'seat': 'a'}]), 'repeats a seat'),
    (lambda p: p.pop('steps'), 'steps list'),
])
def test_p02_plan_context_is_validated(fixture_store, mutate, message):
    ledger.materialise(fixture_store, 'intake', INTAKE)
    plan = copy.deepcopy(PLAN)
    mutate(plan)
    with pytest.raises(ledger.LedgerError, match=message):
        ledger.materialise(fixture_store, 'plan', {'plan': plan})


def test_p02_replan_is_a_new_revision_and_an_identical_plan_appends_nothing(fixture_store):
    first = started(fixture_store)
    events = len(fixture_store.scan('ledger'))
    assert ledger.materialise(fixture_store, 'plan', {'plan': PLAN, 'route': 'analysis'}) == first
    assert len(fixture_store.scan('ledger')) == events
    replan = copy.deepcopy(PLAN)
    replan['steps'] = replan['steps'][:1]
    replan['deliverables'] = [{'id': 'D1', 'steps': ['s1']}, {'id': 'D2', 'open': True}]
    second = ledger.materialise(fixture_store, 'plan', {'plan': replan, 'route': 'analysis'})
    state = state_module.load(fixture_store, full=True)
    assert state.plan_revision == 2 and k('GATE-launch', step='s2') not in second
    assert k('X-KEEP', deliverable='D2') in state.current_keys()   # conserved across the replan


# ---- seats ---------------------------------------------------------------------------------------------------

def test_p02_dispatch_selects_seat_rows_by_seat_kind_and_role(fixture_store):
    started(fixture_store)
    worker = ledger.materialise(fixture_store, 'dispatch', {'step': 's1', 'seat': 'maker', 'attempt': 1,
                                                            'seat_kind': 'worker'})
    assert ids(worker) == ids([k('X-SEAT', step='s1', seat='maker', attempt=1),
                               k('X-ROLE-maker', step='s1', seat='maker', attempt=1)])
    launch = ledger.materialise(fixture_store, 'dispatch', {'step': 's2', 'seat': 'maker', 'attempt': 1,
                                                            'seat_kind': 'launch', 'point': 'p1'})
    assert ids(launch) == ids([k('X-LAUNCH', step='s2', point='p1', seat='maker', attempt=1),
                               k('X-ROLE-maker', step='s2', point='p1', seat='maker', attempt=1)])
    unknown = ledger.materialise(fixture_store, 'dispatch', {'step': 's2', 'seat': 'other', 'attempt': 1,
                                                             'point': 'p2'})
    assert {key.split('@')[0] for key in unknown} == {'X-SEAT', 'X-LAUNCH'}  # unknown seat kind keeps both


def test_p02_review_rows_belong_to_review_seats_only(fixture_store):
    started(fixture_store)
    review = ledger.materialise(fixture_store, 'review', {'step': 's1', 'seat': 'checker', 'attempt': 1})
    assert ids(review) == ids([k('X-SEAT', step='s1', seat='checker', attempt=1),
                               k('X-REVIEW', step='s1', seat='checker', attempt=1)])
    dispatch = ledger.materialise(fixture_store, 'dispatch', {'step': 's1', 'seat': 'checker', 'attempt': 2,
                                                              'seat_kind': 'worker'})
    assert not any(key.startswith('X-REVIEW@') for key in dispatch)


def test_p02_a_retry_is_a_new_attempt_and_attempts_never_go_back(fixture_store):
    started(fixture_store)
    seat = {'step': 's1', 'seat': 'maker', 'attempt': 1, 'seat_kind': 'worker'}
    first = ledger.materialise(fixture_store, 'dispatch', seat)
    assert ledger.materialise(fixture_store, 'dispatch', dict(seat)) == first
    with pytest.raises(ledger.LedgerError) as raised:
        ledger.materialise(fixture_store, 'dispatch', {**seat, 'seat_kind': 'launch'})
    assert raised.value.code == 'attempt_reused'
    second = ledger.materialise(fixture_store, 'dispatch', {**seat, 'attempt': 2})
    assert set(first).isdisjoint(second)
    with pytest.raises(ledger.LedgerError) as raised:
        ledger.materialise(fixture_store, 'dispatch', {**seat, 'attempt': 1, 'seat_kind': 'review'})
    assert raised.value.code in ('attempt_reused', 'attempt_stale')
    state = state_module.load(fixture_store, full=True)
    assert set(second) <= set(state.current_keys()) and not set(first) & set(state.current_keys())
    with pytest.raises(ledger.LedgerError, match='attempt'):
        ledger.materialise(fixture_store, 'dispatch', {**seat, 'attempt': 0})


# ---- delivery and events ---------------------------------------------------------------------------------

def test_p02_delivery_rows_are_per_artifact_and_per_delivery(fixture_store):
    started(fixture_store)
    keys = ledger.materialise(fixture_store, 'deliver', {'artifacts': ['a1', 'a2'], 'claims': ['c1']})
    assert ids(keys) == ids([k('X-SINK'), k('GATE-delivery'), k('X-ART', artifact='a1'), k('X-ART', artifact='a2')])


def test_p02_events_instantiate_their_occurrence_rows(fixture_store):
    started(fixture_store)
    keys = ledger.materialise(fixture_store, 'event', {'kind': 'deviation', 'id': 'dev-1'})
    assert ids(keys) == ids([k('CHECKIN-deviation', event='dev-1'), k('GATE-deviation', event='dev-1')])
    assert ledger.materialise(fixture_store, 'event', {'kind': 'deviation', 'id': 'dev-1'}) == keys
    with pytest.raises(ledger.LedgerError) as raised:
        ledger.materialise(fixture_store, 'event', {'kind': 'unblind', 'id': 'dev-1'})
    assert raised.value.code in ('event_reused', 'event_unknown')
    with pytest.raises(ledger.LedgerError) as raised:
        ledger.materialise(fixture_store, 'event', {'kind': 'nothing-of-the-sort', 'id': 'e9'})
    assert raised.value.code == 'event_unknown'


def test_p02_an_escalation_occurrence_instantiates_the_escalating_role_duties_only(fixture_store, monkeypatch):
    from p02_support import fixture_rows, row
    rows = fixture_rows() + [
        row('CHECKIN-escalation', 'controller.escalation', 'event', 'event', select={'checkin': 'escalation'}),
        row('CF01', 'step.escalation', 'event', 'event', cls='I', waivability='never',
            select={'checkin': 'escalation'}),
        row('ROLE-maker-escalation-0', 'step.escalation[maker]', 'event', 'event', cls='I', waivability='never',
            select={'checkin': 'escalation', 'role': 'maker'}),
        row('ROLE-checker-escalation-0', 'step.escalation[checker]', 'event', 'event', cls='I', waivability='never',
            select={'checkin': 'escalation', 'role': 'checker'})]
    use_catalogue(monkeypatch, fixture_catalogue(rows))
    started(fixture_store)
    # No escalation, no escalation duty: a seat materialises none of them.
    seat = ledger.materialise(fixture_store, 'dispatch', {'step': 's1', 'seat': 'maker', 'attempt': 1,
                                                          'seat_kind': 'worker'})
    assert not [key for key in seat if key.split('@', 1)[0] in ('CF01', 'ROLE-maker-escalation-0')]
    keys = ledger.materialise(fixture_store, 'event', {'kind': 'escalation', 'id': 'e1', 'step': 's1', 'role': 'maker'})
    assert ids(keys) == ids([k('CHECKIN-escalation', event='e1'), k('CF01', event='e1'),
                             k('ROLE-maker-escalation-0', event='e1')])
    with pytest.raises(ledger.LedgerError) as refused:
        ledger.record(fixture_store, k('CF01', event='e1'), 'satisfied', {'mechanism': 'fixture'})
    assert refused.value.code == 'ack_missing'   # an instructed duty is never satisfied without its acknowledgement


def test_p02_every_written_event_is_a_valid_ledger_entry(fixture_store):
    started(fixture_store)
    ledger.materialise(fixture_store, 'dispatch', {'step': 's1', 'seat': 'maker', 'attempt': 1, 'seat_kind': 'worker'})
    ledger.materialise(fixture_store, 'event', {'kind': 'deviation', 'id': 'dev-1'})
    ledger.record(fixture_store, k('X-INTAKE'), 'satisfied', {'mechanism': 'fixture'})
    from ravel.validation.validate_task_contract import _schema_errors  # the controller's schema subset
    schema = json.loads(SCHEMA.read_text())
    assert '$ref' not in SCHEMA.read_text()   # the controller inlines named references only
    validator = Draft202012Validator(schema)
    events = [e['record'] for e in fixture_store.scan('ledger')]
    assert len(events) == 5
    for event in events:
        errors = sorted(validator.iter_errors(event), key=str)
        assert not errors, errors[0].message
        assert _schema_errors(event, schema, '$') == []
    assert _schema_errors({**events[-1], 'seq': -1}, schema, '$')


# ---- the installed catalogue ----------------------------------------------------------------------------

def installed_plan(catalogue):
    roles = sorted({r['applicability']['select']['role'] for r in catalogue.rows.values() if r['id'].startswith('ROLE-')})
    ops = sorted(r[5:] for r in catalogue.rows if r.startswith('TOOL-') and f'EXEC-{r[5:]}' in catalogue.rows)
    return roles, ops, {
        'sha256': 'b' * 64,
        'steps': [
            {'id': 'gen', 'kind': 'operate', 'operation': ops[0], 'role': roles[0], 'waypoint': True,
             'instruction_sources': ['docs/workflow/steps/03-generate.md'], 'review': [roles[1]], 'rung': 'smoke'},
            {'id': 'scan', 'kind': 'operate', 'operation': ops[1], 'role': roles[0], 'depends_on': ['gen'],
             'points': ['p1', 'p2', 'p3'], 'instruction_sources': ['docs/workflow/steps/08-scan.md'], 'rung': 'scan'},
            {'id': 'decide-basis', 'kind': 'decide', 'role': roles[2], 'depends_on': ['gen'],
             'instruction_sources': ['docs/workflow/steps/02-inputs.md',
                                     'docs/workflow/checklists/judgment-protocols.md']},
        ],
        'deliverables': [{'id': 'D1', 'steps': ['scan']}, {'id': 'D2', 'steps': ['gen']}],
    }


def test_p02_installed_catalogue_materialises_every_stage(tmp_path):
    catalogue = ledger.load_catalogue()
    roles, ops, plan = installed_plan(catalogue)
    store = FakeStore('run-installed', root=tmp_path)
    try:
        intake = ledger.materialise(store, 'intake', {'run_id': 'run-installed', 'task_mode': 'scan',
                                                      'deliverables': ['D1', 'D2']})
        ids_at = {key.split('@')[0] for key in intake}
        assert 'ROUTE-scan' in ids_at and 'ROUTE-reproduce' not in ids_at
        assert {'R01', 'CT01', 'SW01', 'SW13', 'JR10'} <= ids_at
        assert sum(key.startswith('R05@') for key in intake) == 2       # one conservation entry per deliverable
        planned = ledger.materialise(store, 'plan', {'plan': plan, 'route': 'analysis'})
        at_plan = {key.split('@')[0] for key in planned}
        assert {f'TOOL-{ops[0]}', f'EXEC-{ops[0]}', 'STEP-03-generate', 'STEP-08-scan', 'GATE-approve_plan',
                'GATE-launch', 'GATE-checkin2_accept', 'CHECKIN-1', 'CHECKIN-2', 'CHECKIN-3', 'CHECKIN-final',
                'A01', 'A08', 'R07', 'C01', 'E03'} <= at_plan
        assert 'R06' not in at_plan and 'JR01' not in at_plan                 # other routes' rows
        assert 'E04' in at_plan                         # the analysis route's inputs rows: a step reads 02-inputs
        assert 'E12' not in at_plan                     # a recovery judgment applies to generation decisions only
        assert sum(key.startswith('P04@') for key in planned) == 3           # one row per scan point
        seat = ledger.materialise(store, 'dispatch', {'step': 'gen', 'seat': roles[0], 'attempt': 1,
                                                      'seat_kind': 'worker'})
        role_rows = {rid for rid, row in catalogue.rows.items() if rid.startswith(f'ROLE-{roles[0]}-')
                     and row['applicability']['stage'] == 'seat'}
        assert role_rows and role_rows <= {key.split('@')[0] for key in seat}
        assert not any(key.startswith(f'ROLE-{roles[1]}-') for key in seat)
        review = ledger.materialise(store, 'review', {'step': 'gen', 'seat': roles[1], 'attempt': 1,
                                                      'review_kind': 'critic'})
        at_review = {key.split('@')[0] for key in review}
        assert {'V02', 'V04'} <= at_review and 'V05' not in at_review          # RDJ rows need an RDJ seat
        delivered = ledger.materialise(store, 'deliver', {'artifacts': ['outputs/limits.json']})
        at_delivery = {key.split('@')[0] for key in delivered}
        assert {'D01', 'D07', 'C22', 'C27', 'GATE-delivery', 'GATE-final_task'} <= at_delivery
        assert 'E20' not in at_delivery                 # no step of this plan renders figures
        assert sum(key.startswith('D01@') for key in delivered) == 1         # one per delivered artifact
        summary = ledger.summary(store)
        assert summary['chain']['verified'] and summary['by_status']['pending'] == summary['instances']
    finally:
        state_module.forget(store)
