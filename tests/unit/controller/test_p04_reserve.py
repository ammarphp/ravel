"""Budget reservations of the governed step (M17): atomic, conservative, never refunded by a worker's word."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import sys
import threading

import pytest

from ravel.controller.ledger import population_equality as _population_equality
from ravel.controller.step import budget, graph, services, spec
from ravel.controller.step.services import StepHold

from test_p04_support import (FakeAuthority, FakeStore, context, install, install_plan, make_step,  # noqa: F401
                              records, run_env, services_installed)

CEILINGS = {'wall_seconds': 100, 'model_calls': 10, 'tokens': 1000, 'cost_usd': None, 'core_hours': 1,
            'events': 100, 'children': 3}


def amounts(**values):
    base = {'wall_seconds': 10, 'model_calls': 1, 'tokens': 10, 'cost_usd': None, 'core_hours': 0, 'events': 0,
            'children': 1}
    return {**base, **values}


@pytest.fixture
def store(tmp_path):
    return FakeStore(tmp_path / 'store')


def test_B01_children_retries_and_ambiguous_starts_are_charged_until_the_ceiling(store):
    budget.reserve(store, step_id='s1', attempt=1, amounts=amounts(), ceilings=CEILINGS)
    budget.settle(store, 's1/1/producer', status='settled', measured={'wall_seconds': 2, 'children': 1})
    budget.reserve(store, step_id='s1', attempt=2, amounts=amounts(), ceilings=CEILINGS)   # a retry: new reservation
    budget.settle(store, 's1/2/producer', status='ambiguous')                                # no refund
    budget.reserve(store, step_id='s1', attempt=3, amounts=amounts(), ceilings=CEILINGS, seat='seat:x:1')
    totals = budget.totals(store, CEILINGS)
    assert totals['children']['charged'] == 3
    assert totals['wall_seconds']['charged'] == 2 + 10 + 10   # measured where observed, reserved where not
    with pytest.raises(StepHold) as refused:
        budget.reserve(store, step_id='s2', attempt=1, amounts=amounts(), ceilings=CEILINGS)
    assert refused.value.reason == 'budget_exhausted'
    assert refused.value.evidence['refused'][0]['dimension'] == 'children'


def test_B01_a_reservation_survives_a_restart_and_the_same_key_is_not_charged_twice(store):
    first = budget.reserve(store, step_id='s1', attempt=1, amounts=amounts(), ceilings=CEILINGS)
    again = budget.reserve(store, step_id='s1', attempt=1, amounts=amounts(), ceilings=CEILINGS)
    assert again['record_id'] == first['record_id'] and len(records(store, 'budget-reservation')) == 1
    with pytest.raises(StepHold) as changed:
        budget.reserve(store, step_id='s1', attempt=1, amounts=amounts(wall_seconds=99), ceilings=CEILINGS)
    assert changed.value.reason == 'reservation_changed'


def test_B02_two_reservations_racing_for_the_last_unit_one_is_denied(store):
    ceilings = {**CEILINGS, 'children': 1}
    barrier = threading.Barrier(2)

    def take(name):
        barrier.wait()
        try:
            budget.reserve(store, step_id=name, attempt=1, amounts=amounts(), ceilings=ceilings)
            return 'granted'
        except StepHold as exc:
            return exc.reason
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(take, ['a', 'b']))
    assert results == ['budget_exhausted', 'granted']
    assert len(records(store, 'budget-reservation')) == 1


def test_G07_a_child_reservation_above_a_finite_ceiling_is_refused_under_the_lock(store):
    with pytest.raises(StepHold) as refused:
        budget.reserve(store, step_id='s1', attempt=1, amounts=amounts(wall_seconds=101), ceilings=CEILINGS)
    assert refused.value.evidence['refused'][0] == {'dimension': 'wall_seconds', 'reason': 'ceiling',
                                                    'ceiling': 100, 'charged': 0, 'requested': 101}


def test_C12_unknown_amounts_stay_unknown_and_never_pass_a_finite_prepaid_ceiling(store):
    with pytest.raises(StepHold) as refused:
        budget.reserve(store, step_id='s1', attempt=1, amounts=amounts(events=None), ceilings=CEILINGS)
    assert refused.value.reason == 'budget_unknown_request'
    # A measured-after dimension admits an unknown request only while its charged total is below the ceiling.
    budget.reserve(store, step_id='s2', attempt=1, amounts=amounts(tokens=None), ceilings=CEILINGS)
    budget.settle(store, 's2/1/producer', status='settled', measured={'tokens': None, 'children': 1})
    totals = budget.totals(store, CEILINGS)
    assert totals['tokens']['unknown'] == 2 and totals['tokens']['charged'] == 0   # unknown, never zero-summed
    budget.reserve(store, step_id='s3', attempt=1, amounts=amounts(tokens=1000), ceilings=CEILINGS)
    with pytest.raises(StepHold):
        budget.reserve(store, step_id='s4', attempt=1, amounts=amounts(tokens=None), ceilings=CEILINGS)


@pytest.mark.parametrize('route_id', ['analysis', 'analysis.scan'])
def test_census_launch_reserves_zero_events_without_relaxing_the_ceiling(store, route_id):
    from ravel.controller import routes
    from p09_support import contract, reading

    scan = route_id == 'analysis.scan'
    plan = routes.compile(routes.find(route_id), reading(scan=scan), contract('scan' if scan else 'reproduce'))
    census = next(step for step in plan['steps'] if step['id'] == 'inputs.census')
    assert spec.launch(census) is not None
    ceilings = {dimension: None for dimension in budget.DIMENSIONS}
    ceilings['events'] = 0
    requested = graph._amounts(census, None, 'launch')
    assert requested['events'] == 0
    reservation = budget.reserve(store, step_id=census['id'], attempt=1, amounts=requested, ceilings=ceilings)
    assert reservation['amounts']['events'] == 0

    for attempt, events, reason in ((2, None, 'budget_unknown_request'), (3, 1, 'budget_exhausted')):
        changed = deepcopy(census)
        if events is None:
            del changed['budget']['events']
        else:
            changed['budget']['events'] = events
        with pytest.raises(StepHold) as refused:
            budget.reserve(store, step_id=census['id'], attempt=attempt,
                           amounts=graph._amounts(changed, None, 'launch'), ceilings=ceilings)
        assert refused.value.reason == reason
        assert refused.value.evidence['refused'][0]['dimension'] == 'events'
        assert refused.value.evidence['refused'][0]['ceiling'] == 0
    assert ceilings['events'] == 0
    assert len(records(store, 'budget-reservation')) == 1


def test_a_dimension_without_a_configured_ceiling_is_reported_unbounded(store, monkeypatch):
    fake = FakeAuthority(budgets={'cost_usd': None})
    monkeypatch.setitem(__import__('sys').modules, services.INTERFACES['authority'],
                        type('m', (), {'effective_bounds': staticmethod(fake.effective_bounds)}))
    ceilings = budget.envelope(store)
    assert ceilings['cost_usd'] is None and ceilings['children'] == 1000
    fake.budgets['children'] = None
    with pytest.raises(StepHold) as missing:
        budget.envelope(store)
    assert missing.value.reason == 'budget_ceiling_missing' and 'children' in missing.value.would_make_possible


def test_A07_a_pilot_requesting_more_events_than_its_approved_rung_is_refused():
    step = make_step('p1', kind='operate', role='generator', operation='event-production', rung='pilot',
                     budget={'events': 5000}, parameters={'rung_ceiling': {'events': 1000}})
    assert budget.rung_errors(step) == [{'code': 'rung_ceiling_exceeded', 'rung': 'pilot', 'requested': 5000,
                                         'approved': 1000}]
    step['budget']['events'] = 1000
    assert budget.rung_errors(step) == []


def _top_step(**parameters):
    return make_step('f1', kind='operate', role='generator', operation='event-production', rung='full',
                     budget={'events': 100, 'wall_seconds': 50}, parameters={'process_sha256': 'a' * 64, **parameters})


def test_C13_only_a_succeeded_pilot_of_the_same_process_on_this_machine_calibrates(store):
    step = _top_step()
    assert budget.calibration_errors(store, step)[0]['code'] == 'uncalibrated_top_rung_cost'
    pilot = dict(step, rung='pilot')
    budget.record_calibration(store, pilot, status='failed', measured={'wall_seconds': 1.0, 'events': 10})
    assert budget.calibration_errors(store, step)[0]['code'] == 'uncalibrated_top_rung_cost'
    other = dict(pilot, parameters={'process_sha256': 'b' * 64})
    budget.record_calibration(store, other, status='succeeded', measured={'wall_seconds': 1.0, 'events': 10})
    assert budget.calibration_errors(store, step)[0]['code'] == 'uncalibrated_top_rung_cost'
    store.append(budget.CALIBRATION, {'operation': 'event-production', 'process_sha256': budget.process_pin(step),
                                      'machine_sha256': '0' * 64, 'status': 'succeeded',
                                      'measured': {'wall_seconds': 1.0, 'events': 10}})
    assert budget.calibration_errors(store, step)[0]['code'] == 'uncalibrated_top_rung_cost'   # another machine
    budget.record_calibration(store, pilot, status='succeeded', measured={'wall_seconds': 1.0, 'events': 10})
    assert budget.calibration_errors(store, step) == []
    step['budget']['wall_seconds'] = 5   # the matched forecast (10 s) exceeds the reservation
    assert budget.calibration_errors(store, step)[0]['code'] == 'forecast_exceeds_reservation'


def _reserve_state(env, step, **extra):
    plan_sha = install_plan(env.store, [step])
    return {'step': step, 'context': context(env.store, env.run_dir, plan_sha, **extra)}


def _bounded_task(monkeypatch, **share):
    monkeypatch.setattr(graph.operations, 'signatures', lambda: {
        'fixture-task': {'cost': {'unit': 'task'}, 'effects': []}})
    return make_step('bounded.task', kind='operate', role=None, operation='fixture-task', rung='full',
                     budget={'wall_seconds': 900, 'attempts': 1, **share},
                     parameters={'launch': {'argv': [sys.executable, '-c', 'pass']}})


def test_bounded_task_top_rung_records_upper_estimate_without_cost_question(run_env, monkeypatch):
    state = _reserve_state(run_env, _bounded_task(monkeypatch), unattended=False)
    with services.bound(run_env.store):
        update = graph.reserve(state)
        gate = graph.cost_authority({**state, **update})
    assert gate['gates']['cost_authority']['errors'] == []
    reservation = records(run_env.store, budget.RESERVATION)[0]
    bound = reservation['basis']['upper_bound']
    assert bound['kind'] == 'conservative-cost-bound' and bound['schema_version'] == 1
    assert bound['basis'] == 'approved-reservation' and bound['cost_unit'] == 'task'
    assert bound['amounts'] == reservation['amounts']
    assert bound['amounts']['wall_seconds'] == 900 and bound['amounts']['events'] == 0
    assert bound['mechanism']['wall_seconds'] == 'controller-watchdog'
    assert bound['mechanism']['children'] == 'one-governed-attempt'
    fact = next(row for row in records(run_env.store, 'step-fact')
                if row['mechanism'] == 'rung-cost-admitted')
    assert fact['upper_bound'] == bound
    assert update['evaluations']['C02']['status'] == update['evaluations']['C13']['status'] == 'satisfied'
    assert not [call for call in run_env.fakes['authority'].calls
                if call[0] == 'request' and call[1] == 'r3_action']
    assert records(run_env.store, budget.CALIBRATION) == []


@pytest.mark.parametrize('case', ['wall', 'tokens', 'cost', 'input', 'batch', 'unit', 'events'])
def test_a_task_with_an_unknown_or_unenforced_consumable_still_asks(run_env, monkeypatch, case):
    shares = {'wall': {'wall_seconds': None}, 'tokens': {'tokens': 1}, 'cost': {'cost_usd': 1},
              'input': {'input_bytes': 1}, 'batch': {'batch_cpu_hours': 1}, 'unit': {}, 'events': {'events': 1}}
    step = _bounded_task(monkeypatch, **shares[case])
    if case == 'wall':
        del step['budget']['wall_seconds']
    if case == 'unit':
        monkeypatch.setattr(graph.operations, 'signatures', lambda: {
            'fixture-task': {'cost': {'unit': 'unknown'}, 'effects': []}})
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        graph.reserve(_reserve_state(run_env, step))
    assert held.value.reason == 'awaiting_authority'
    assert records(run_env.store, budget.RESERVATION) == []


def test_a_bounded_task_above_the_operator_envelope_refuses_before_asking(run_env, monkeypatch):
    state = _reserve_state(run_env, _bounded_task(monkeypatch))
    run_env.fakes['authority'].budgets['wall_seconds'] = 899
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        graph.reserve(state)
    assert held.value.reason == 'budget_exhausted'
    assert records(run_env.store, budget.RESERVATION) == []


def test_the_cost_bound_is_rechecked_before_packet_creation(run_env, monkeypatch):
    state = _reserve_state(run_env, _bounded_task(monkeypatch))
    with services.bound(run_env.store):
        update = graph.reserve(state)
        run_env.fakes['authority'].budgets['wall_seconds'] = 899
        gate = graph.cost_authority({**state, **update})
    assert gate['gates']['cost_authority']['errors']


@pytest.mark.parametrize('dimension', budget.DIMENSIONS)
@pytest.mark.parametrize('value', [None, float('inf'), float('nan')])
def test_a_nonfinite_reservation_is_never_a_conservative_bound(monkeypatch, dimension, value):
    step = _bounded_task(monkeypatch)
    requested = {d: 0 for d in budget.DIMENSIONS}
    requested.update(wall_seconds=900, core_hours=900 / 3600, children=1)
    requested[dimension] = value
    assert budget.reservation_bound(step, requested, {d: None for d in budget.DIMENSIONS}, branch='launch',
                                    signature={'cost': {'unit': 'task'}, 'effects': []}) is None


def test_cooperative_cpu_settings_cannot_establish_a_core_hour_bound(monkeypatch):
    step = _bounded_task(monkeypatch)
    requested = {d: 0 for d in budget.DIMENSIONS}
    requested.update(wall_seconds=900, core_hours=900 / 3600, children=1)
    monkeypatch.setattr(budget.sys, 'platform', 'unsupported')
    assert budget.reservation_bound(step, requested, {d: None for d in budget.DIMENSIONS}, branch='launch',
                                    signature={'cost': {'unit': 'task'}, 'effects': []}) is None


def test_event_step_without_a_derivable_pilot_or_upper_bound_still_asks(run_env):
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        graph.reserve(_reserve_state(run_env, _top_step()))
    assert held.value.reason == 'awaiting_authority'
    assert records(run_env.store, budget.RESERVATION) == []


def _scan_state(env, monkeypatch, *, ceiling=21600, events=50000, supplied=False, event_bound=False):
    from p09_support import compile_plan, contract, reading
    monkeypatch.setattr(services.module('ledger'), 'population_equality', _population_equality, raising=False)
    plan = compile_plan('analysis.scan', reading(scan=True), contract('scan'))
    step = next(row for row in plan['steps'] if row.get('template_id') == 'scan.point')
    assert {'inputs.cost', 'recast.smoke'} <= {row['id'] for row in plan['steps']}
    if ceiling is None:
        del step['parameters']['task']['max_seconds']
    else:
        step['parameters']['task']['max_seconds'] = ceiling
    step['budget']['events'] = events
    if supplied:
        step['budget']['input_files'] = 1
    if event_bound:
        step['parameters']['launch'] = {'argv': [sys.executable, '-c', 'pass', '@events']}
    plan['sha256'] = graph.digest({k: v for k, v in plan.items() if k != 'sha256'})
    blob = env.store.put_blob(json.dumps(plan, sort_keys=True).encode())
    env.store.append('plan', {'plan_sha256': plan['sha256'], 'blob': blob, 'revision': plan['revision']})
    return {'step': step, 'context': context(env.store, env.run_dir, plan['sha256'], plan=plan)}


@pytest.mark.parametrize('ceiling', [900, 21600])
def test_fixed_plan_scan_records_its_enforced_operation_ceiling(run_env, monkeypatch, ceiling):
    state = _scan_state(run_env, monkeypatch, ceiling=ceiling)
    assert budget.pilot_step(state['step']) == (None, 'launch_not_declared')
    with services.bound(run_env.store):
        update = graph.reserve(state)
        gate = graph.cost_authority({**state, **update})
    assert gate['gates']['cost_authority']['errors'] == []
    reservation = records(run_env.store, budget.RESERVATION)[0]
    bound = reservation['basis']['upper_bound']
    assert bound['kind'] == 'conservative-cost-bound'
    assert bound['basis'] == 'declared-operation-ceiling' and bound['cost_unit'] == 'points'
    assert bound['ceiling_pointer'] == '/max_seconds'
    assert bound['amounts']['wall_seconds'] == reservation['amounts']['wall_seconds'] == ceiling
    assert reservation['amounts']['events'] == 50000
    assert bound['mechanism']['wall_seconds'] == 'controller-watchdog'
    assert not [call for call in run_env.fakes['authority'].calls
                if call[0] == 'request' and call[1] == 'r3_action']
    assert records(run_env.store, budget.CALIBRATION) == []


@pytest.mark.parametrize('ceiling', [None, 0, 21601])
def test_scan_without_a_resolvable_enforced_ceiling_still_asks(run_env, monkeypatch, ceiling):
    from test_p04_support import accepted_artifact
    state = _scan_state(run_env, monkeypatch, ceiling=ceiling)
    accepted_artifact(run_env.store, run_env.run_dir, 'inputs.cost', 'outputs/cost_preflight.json',
                      {'mode': 'scan', 'walltime_h': [0.1, 0.2], 'calibration_status': 'uncalibrated'},
                      kind='table')
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        graph.reserve(state)
    assert held.value.reason == 'awaiting_authority'
    assert records(run_env.store, budget.RESERVATION) == []


@pytest.mark.parametrize('supplied', [False, True])
def test_positive_scan_event_reservation_refuses_before_a_cost_question(run_env, monkeypatch, supplied):
    state = _scan_state(run_env, monkeypatch, supplied=supplied)
    run_env.fakes['authority'].budgets['events'] = 0
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        graph.reserve(state)
    assert held.value.reason == 'budget_exhausted'
    assert held.value.evidence['refused'][0]['dimension'] == 'events'
    assert not [call for call in run_env.fakes['authority'].calls if call[0] == 'request']
    assert records(run_env.store, budget.RESERVATION) == []


def test_zero_generated_events_with_supplied_inputs_can_use_the_wall_bound(run_env, monkeypatch):
    state = _scan_state(run_env, monkeypatch, events=0, supplied=True)
    run_env.fakes['authority'].budgets['events'] = 0
    with services.bound(run_env.store):
        update = graph.reserve(state)
    assert update['reservation']['amounts']['events'] == 0
    assert update['reservation']['amounts']['input_files'] == 1
    assert records(run_env.store, budget.RESERVATION)[0]['basis']['upper_bound']['basis'] \
        == 'declared-operation-ceiling'


def test_scan_bound_above_the_operator_wall_envelope_refuses(run_env, monkeypatch):
    state = _scan_state(run_env, monkeypatch)
    run_env.fakes['authority'].budgets['wall_seconds'] = 21599
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        graph.reserve(state)
    assert held.value.reason == 'budget_exhausted'
    assert records(run_env.store, budget.RESERVATION) == []


def test_scan_reservation_replay_does_not_charge_its_own_bound_twice(run_env, monkeypatch):
    state = _scan_state(run_env, monkeypatch)
    run_env.fakes['authority'].budgets.update(wall_seconds=21600, events=50000)
    with services.bound(run_env.store):
        first = graph.reserve(state)
        second = graph.reserve(state)
    assert first['reservation'] == second['reservation']
    assert len(records(run_env.store, budget.RESERVATION)) == 1


def test_scan_known_overage_includes_previously_charged_events(run_env, monkeypatch):
    state = _scan_state(run_env, monkeypatch)
    budget.reserve(run_env.store, step_id='earlier', attempt=1,
                   amounts=amounts(wall_seconds=1, model_calls=0, tokens=0, cost_usd=0, events=1),
                   ceilings={d: None for d in budget.DIMENSIONS})
    budget.settle(run_env.store, 'earlier/1/producer', status='settled',
                  measured={'wall_seconds': 1, 'events': 1})
    run_env.fakes['authority'].budgets['events'] = 50000
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        graph.reserve(state)
    assert held.value.reason == 'budget_exhausted'
    assert held.value.evidence['refused'][0]['charged'] == 1
    assert not [call for call in run_env.fakes['authority'].calls if call[0] == 'request']


@pytest.mark.parametrize('unproven', ['unit', 'runtime'])
def test_scan_unknown_unit_or_custom_runtime_retains_the_cost_question(run_env, monkeypatch, unproven):
    state = _scan_state(run_env, monkeypatch)
    if unproven == 'unit':
        signatures = deepcopy(graph.operations.signatures())
        signatures[state['step']['operation']]['cost']['unit'] = 'unknown'
        monkeypatch.setattr(graph.operations, 'signatures', lambda: signatures)
    else:
        from ravel.controller.step.launch_gate import STUDY_ADAPTER
        state['step']['parameters']['adapter'] = STUDY_ADAPTER
        plan = state['context']['plan']
        plan['sha256'] = graph.digest({k: v for k, v in plan.items() if k != 'sha256'})
        blob = run_env.store.put_blob(json.dumps(plan, sort_keys=True).encode())
        run_env.store.append('plan', {'plan_sha256': plan['sha256'], 'blob': blob})
        state['context']['plan_sha256'] = plan['sha256']
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        graph.reserve(state)
    assert held.value.reason == 'awaiting_authority'
    assert records(run_env.store, budget.RESERVATION) == []


def test_a_matched_pilot_forecast_must_fit_the_narrowed_wall_reservation(run_env, monkeypatch):
    state = _scan_state(run_env, monkeypatch, ceiling=900, event_bound=True)
    step = state['step']
    budget.record_calibration(run_env.store, dict(step, rung='pilot'), status='succeeded',
                              measured={'wall_seconds': 12, 'events': 500})
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        graph.reserve(state)
    assert held.value.reason == 'forecast_exceeds_reservation'
    assert held.value.evidence['errors'][0]['forecast_wall_seconds'] == 1200
    assert held.value.evidence['errors'][0]['reserved_wall_seconds'] == 900
    assert records(run_env.store, budget.RESERVATION) == []


def test_materialized_scan_capsule_enforces_the_smaller_declared_wall(run_env, monkeypatch):
    from ravel.controller.routes import analysis
    state = _scan_state(run_env, monkeypatch, ceiling=900)
    step = state['step']
    state['reservation'] = {'record_id': 'fixture-reservation',
                            'amounts': {'wall_seconds': 21600}}
    # Exercise capsule construction only; no scientific process or authority effect is launched.
    monkeypatch.setattr(analysis, 'materialize_launch', lambda *a: {
        'argv': ['/bin/true'], 'env': {}, 'reads': [], 'stage': 'analyze'})
    monkeypatch.setattr(graph, '_authorize', lambda *a, **k: {})
    monkeypatch.setattr(graph.native_checks, 'source_admission', lambda *a, **k: {})
    monkeypatch.setattr(graph, '_probe', lambda *a: {})
    with services.bound(run_env.store):
        prepared = graph._launch_preflight(state, run_env.store, state['context'], run_env.run_dir,
                                           step, None, [], [], {})
    assert prepared['capsule']['limits']['wall_seconds'] == 900
    assert step['budget']['wall_seconds'] == 21600


def test_C02_an_uncalibrated_top_rung_needs_the_physicists_own_signoff(run_env, monkeypatch):
    step = _top_step()
    state = _reserve_state(run_env, step)
    authority = run_env.fakes['authority']
    verified = []
    def verify(store, identifier, *, kind, subject):
        record = store.read('authority', identifier)['record']
        assert kind == 'r3_action' and record['label'] == 'operator_command'
        assert record['decision'] == 'approve' and record['option'] == 'admit'
        assert subject == record['subject']['view']['pins']
        verified.append(identifier)
        return {**record, 'id': identifier, 'source': 'operator_cli', 'authorizes_effects': True,
                'subject': {'pins': deepcopy(subject)}}
    monkeypatch.setattr(sys.modules['ravel.controller.authority'], 'verify', verify, raising=False)
    with services.bound(run_env.store):
        with pytest.raises(StepHold) as pending:
            graph.reserve(state)
        assert pending.value.reason == 'awaiting_authority'
        authority.answers['r3_action'] = ('approve', FakeAuthority.MACHINE)
        with pytest.raises(StepHold) as machine:
            graph.reserve(state)
        assert machine.value.reason == 'uncalibrated_top_rung_cost'
        authority.answers['r3_action'] = ('default', FakeAuthority.MACHINE, 'pilot_first')
        with pytest.raises(StepHold) as default:
            graph.reserve(state)
        assert default.value.reason == 'uncalibrated_top_rung_cost'   # the conservative default takes no effect
        authority.answers['r3_action'] = ('approve', 'operator_command', 'admit')
        update = graph.reserve(state)
    assert update['reservation']['amounts']['events'] == 100
    assert update['evaluations']['C02']['status'] == 'satisfied'
    requests = [c for c in authority.calls if c[0] == 'request']
    assert [c[1] for c in requests] == ['r3_action'] * 4
    view = requests[0][2]['view']
    retained = [c for c in authority.calls if c[0] == 'retain']
    assert len(retained) == 4 and retained[0][2]['sha256'] == state['context']['plan_sha256']
    assert view['items']['steps'] == retained[0][2]['steps']
    assert view['flags'] == retained[0][3]['flags']
    assert view['run_id'] == run_env.store.run_id and view['pins']['step_sha256'] == spec.step_sha256(step)
    assert [o['id'] for o in view['options']] == ['admit', 'pilot_first'] and requests[0][2]['conservative_default'] \
        == 'pilot_first' and [o['effect'] for o in view['options']] == [True, False]

    assert len(verified) == 1


def test_C02_a_cost_request_the_authority_cannot_render_is_a_typed_hold_without_a_reservation(run_env, monkeypatch):
    step = _top_step()
    state = _reserve_state(run_env, step)
    authority = sys.modules['ravel.controller.authority']
    for result, reason in (
            (ValueError('a r3_action request carries the run-state view it is decided on'), 'authority_request_invalid'),
            ({'pending': {'reason': 'check-in incomplete', 'errors': ['section action is empty']}},
             'authority_request_invalid')):
        def request(store, kind, subject, bounds, result=result):
            if isinstance(result, Exception):
                raise result
            return result
        monkeypatch.setattr(authority, 'request', request)
        with services.bound(run_env.store), pytest.raises(StepHold) as held:
            graph.reserve(state)
        assert held.value.reason == reason
    assert records(run_env.store, 'budget-reservation') == []


def test_E30_an_unsettled_earlier_attempt_is_reconciled_never_redispatched(run_env):
    step = make_step('s1')
    budget.reserve(run_env.store, step_id='s1', attempt=1, amounts=amounts(), ceilings=CEILINGS)
    budget.settle(run_env.store, 's1/1/producer', status='ambiguous')
    state = _reserve_state(run_env, step, attempt=2)
    with services.bound(run_env.store), pytest.raises(StepHold) as refused:
        graph.reserve(state)
    assert refused.value.reason == 'prior_attempt_unreconciled'
    assert refused.value.evidence['prior'] == [{'key': 's1/1/producer', 'status': 'ambiguous'}]
    budget.settle(run_env.store, 's1/1/producer', status='reconciled')
    with services.bound(run_env.store):
        assert graph.reserve(state)['reservation']['key'] == 's1/2/producer'
    charged = budget.totals(run_env.store)['children']['charged']
    assert charged == 2   # the reconciled attempt keeps its full reservation


def test_an_unfrozen_operating_mode_is_a_typed_hold_never_a_failed_step(run_env, monkeypatch):
    from test_p04_support import AuthorityRefused
    with services.bound(run_env.store):
        assert budget.envelope(run_env.store)['children'] == 1000   # a frozen envelope is read
    authority = sys.modules[services.INTERFACES['authority']]

    def unfrozen(store):
        raise AuthorityRefused('the operating mode was not frozen at intake; no authority can be granted')
    monkeypatch.setattr(authority, 'effective_bounds', unfrozen)
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        budget.envelope(run_env.store)
    assert held.value.reason == 'operating_mode_unavailable' and 'not frozen' in held.value.would_make_possible
    assert records(run_env.store, 'budget-reservation') == []


def test_a_hold_before_dispatch_releases_its_reservation(run_env):
    budget.reserve(run_env.store, step_id='s1', attempt=1, amounts=amounts(), ceilings=CEILINGS)
    state = {'step': make_step('s1'), 'context': context(run_env.store, run_env.run_dir, 'x' * 64),
             'reservation': {'key': 's1/1/producer'}, 'status': {'phase': 'handler', 'terminal': 'hold',
                                                                'reason': 'parent_incomplete'}}
    with services.bound(run_env.store):
        graph.hold_node('controller.step').function(state)
    assert records(run_env.store, 'budget-settlement')[0]['status'] == 'released'
    assert records(run_env.store, 'step-outcome')[0]['status'] == 'held'


def test_the_run_tree_aggregate_ledger_is_refused_for_a_controller_owned_run(tmp_path, monkeypatch):
    from ravel.workflow import agent_worker, completion_budget
    limits = {'max_seconds': 10, 'max_events': 10, 'max_children': 1}
    completion_budget.reserve(tmp_path / 'legacy', 'child', {'max_seconds': 1, 'max_events': 1}, limits)
    monkeypatch.setattr(agent_worker, 'controller_run', lambda root: 'run-p04-fixture')
    with pytest.raises(ValueError, match='run store'):
        completion_budget.reserve(tmp_path / 'owned', 'child', {'max_seconds': 1, 'max_events': 1}, limits)
    assert not (tmp_path / 'owned/inputs/delegation_reservations.json').exists()
