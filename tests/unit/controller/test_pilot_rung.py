"""The unattended cost default: an uncalibrated top-rung cost runs a governed pilot rung first.

The conservative default of the cost check-in (``pilot_first``) leads to a pilot launch of the same
operation and process at a bounded event count, under the same reservation, authority, confinement
and validation as any launch. Only a succeeded, validated pilot calibrates; the full rung is then
admitted from that matched calibration alone. A failed pilot holds the step; an operator's verified
admission still admits without a pilot, and a machine or unattested answer still admits nothing.
"""
from __future__ import annotations

import json
import sys

import pytest

from ravel.controller.step import budget, graph, operations, services, spec
from ravel.controller.step.services import StepHold
from test_p04_support import (FakeAuthority, graphs, inert_worker, make_step, records, run_env, run_step,  # noqa: F401
                              services_installed)
from test_p04_reserve import _reserve_state
from test_cost_authority import verified_interface


def _signature():
    return {'summary': 'fixture', 'implementation': {'kind': 'command', 'module': 'pilot_fixture_tool'},
            'consumes': [], 'produces': [{'slot': 'grid', 'kind': 'table'}], 'effects': [],
            'cost': {'unit': 'events', 'forecast': None, 'ceiling_pointer': None}, 'critical_fields': ['/points'],
            'basis': {'adds': [], 'passes': []}, 'tools': [], 'stages': [], 'review': {'checks': []}, 'fidelity_rank': 1}


TOOLS = {
    'ok': 'Path("grid.json").write_text(json.dumps({"events": int(sys.argv[1])}))\n',
    'exit': 'sys.exit(3)\n',
    'missing': 'pass\n',
}


def _tool(root, behaviour='ok'):
    module = root / 'tools' / 'pilot_fixture_tool.py'
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text('import json, sys\nfrom pathlib import Path\n' + TOOLS[behaviour])
    return module.parent


def _top(tools, *, events=200, token=True, process='a' * 64, operation='fixture-operation'):
    argv = [sys.executable, '-B', '-m', 'pilot_fixture_tool', '@events' if token else str(events)]
    return make_step('g1', kind='operate', role=None, operation=operation, rung='full',
                     outputs=(('grid.json', 'table'),), budget={'wall_seconds': 60, 'events': events},
                     parameters={'task': {'points': 3}, 'process_sha256': process,
                                 'launch': {'argv': argv, 'env': {'PYTHONPATH': str(tools)}}})


@pytest.fixture
def signed(monkeypatch):
    monkeypatch.setattr(operations, 'signatures', lambda: {'fixture-operation': _signature(),
                                                           'other-operation': _signature()})


def _argv_events(env):
    return [spec_['argv'][-1] for spec_ in env.fakes['confine'].launched]


def test_derived_pilot_shares_the_process_pin_and_carries_a_documented_bound(run_env):
    step = _top(_tool(run_env.root))
    pilot, reason = budget.pilot_step(step)
    assert reason is None and pilot['rung'] == budget.PILOT_RUNG and pilot['id'] != step['id']
    assert budget.process_pin(pilot) == budget.process_pin(step) and pilot['operation'] == step['operation']
    assert pilot['budget']['events'] == 2 and pilot['budget']['wall_seconds'] == 60   # ceil(1% of 200)
    assert pilot['parameters']['pilot_of'] == {'step_sha256': spec.step_sha256(step), 'rung': 'full',
                                               'events': 200, 'bound': 2, 'rule': 'fraction'}
    declared = _top(_tool(run_env.root))
    declared['parameters']['pilot'] = {'events': 7}
    assert budget.pilot_step(declared)[0]['budget']['events'] == 7
    declared['parameters']['pilot'] = {'events': 500}
    assert budget.pilot_step(declared) == (None, 'pilot_declaration_invalid')
    assert budget.pilot_step(_top(_tool(run_env.root), token=False)) == (None, 'launch_event_count_unbound')
    assert budget.pilot_step(pilot)[1] == 'not_top_rung'


def test_unattended_uncalibrated_full_rung_runs_the_pilot_then_the_calibrated_full_rung(run_env, inert_worker,
                                                                                        graphs, signed):
    step = _top(_tool(run_env.root))
    outcome = run_step(run_env, step)
    assert outcome['status'] == 'completed', outcome
    store = run_env.store
    assert _argv_events(run_env) == ['2', '200']          # the pilot's bound, then the full rung's count
    launched = run_env.fakes['confine'].launched          # both confined, each in its own attempt outputs
    assert [s['writes'] for s in launched] == [[str(run_env.run_dir / 'steps/g1.pilot/attempts/1/outputs')],
                                               [str(run_env.run_dir / 'steps/g1/attempts/1/outputs')]]
    journal = records(store, 'step-launch')
    assert [(r['step_id'], r['phase']) for r in journal] == [('g1.pilot', 'started'), ('g1.pilot', 'finished'),
                                                             ('g1', 'started'), ('g1', 'finished')]
    reserved = records(store, 'budget-reservation')
    assert [r['key'] for r in reserved] == ['g1/1/pilot', 'g1/1/producer']
    assert reserved[0]['amounts']['events'] == 2 and reserved[1]['amounts']['events'] == 200
    settled = {r['key']: r['status'] for r in records(store, 'budget-settlement')}
    assert settled['g1/1/pilot'] == 'settled'
    calibration = services.records(store, budget.CALIBRATION)
    assert len(calibration) == 1 and calibration[0]['status'] == 'succeeded'
    assert calibration[0]['process_sha256'] == budget.process_pin(step)
    assert calibration[0]['measured']['events'] == 2 and calibration[0]['measured']['wall_seconds'] >= 0
    assert reserved[1]['basis']['signoff'] is None and reserved[1]['basis']['pilot'] == calibration[0]['_record_id']
    pilots = services.records(store, budget.PILOT_LAUNCH)
    assert [p['phase'] for p in pilots] == ['started', 'finished']
    assert pilots[0]['step_id'] == 'g1' and pilots[0]['attempt'] == 1 and pilots[0]['bound'] == 2
    assert pilots[0]['trigger'] == 'unattended' and pilots[0]['label'] == 'controller_machine_default'
    assert pilots[1]['status'] == 'completed' and pilots[1]['calibration'] == calibration[0]['_record_id']
    # The governed default selects the pilot without leaving an operator question pending.
    requests = [c for c in run_env.fakes['authority'].calls if c[0] == 'request' and c[1] == 'r3_action']
    assert requests == []
    assert records(store, 'authority') == []
    # The pilot effect was admitted by the authority at its own rung; its outputs were not adopted.
    rungs = [c[1]['rung'] for c in run_env.fakes['authority'].calls if c[0] == 'authorize_effect']
    assert 'pilot' in rungs and 'full' in rungs
    assert json.loads((run_env.run_dir / 'steps/g1/grid.json').read_text()) == {'events': 200}
    assert not [r for r in records(store, 'custody') if r['artifact'].startswith(budget.pilot_id('g1'))]
    outcomes = [r for r in records(store, 'step-outcome') if r['step_id'] == 'g1']
    assert [r['status'] for r in outcomes] == ['completed']


def test_the_conservative_default_answer_on_an_attended_poll_leads_to_the_pilot(run_env, inert_worker, graphs,
                                                                               signed):
    run_env.fakes['authority'].answers['r3_action'] = ('default', FakeAuthority.MACHINE, 'pilot_first')
    outcome = run_step(run_env, _top(_tool(run_env.root)), unattended=False)
    assert outcome['status'] == 'completed', outcome
    assert _argv_events(run_env) == ['2', '200']
    assert records(run_env.store, budget.PILOT_LAUNCH)[0]['trigger'] == 'conservative_default'


def test_an_attended_event_step_keeps_the_operator_question(run_env, signed):
    state = _reserve_state(run_env, _top(_tool(run_env.root)), unattended=False)
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        graph.reserve(state)
    assert held.value.reason == 'awaiting_authority'
    assert records(run_env.store, budget.PILOT_LAUNCH) == []


def test_unattended_bound_scan_point_selects_the_governed_pilot(run_env, signed):
    from ravel.controller.routes.analysis.execution import bind_launches
    from ravel.controller.routes.compiler import plan_sha256
    step = _top(_tool(run_env.root), events=50000)
    launch = step['parameters'].pop('launch')
    step.update(id='scan.point.p0', template_id='scan.point', rung='scan')
    step['budget']['wall_seconds'] = 21600
    step['parameters'].update(point_id='p0', item={'id': 'p0', 'parameters': {'x': 1}})
    plan = {'steps': [step]}
    plan['sha256'] = plan_sha256(plan)
    bound = bind_launches(plan, {'launches': {step['id']: launch}})['steps'][0]
    state = _reserve_state(run_env, bound)
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        graph.reserve(state)
    assert graph._pilot_trigger(state, held.value) == 'unattended'
    pilot, reason = budget.pilot_step(bound)
    assert reason is None and pilot['budget']['events'] == 500
    assert pilot['parameters']['point_id'] == 'p0'
    assert budget.resolve_events(pilot['parameters']['launch']['argv'], pilot)[-1] == '500'
    assert not [call for call in run_env.fakes['authority'].calls
                if call[0] == 'request' and call[1] == 'r3_action']


def test_a_plan_backed_scan_without_event_binding_does_not_fabricate_a_pilot(run_env, monkeypatch):
    step = _top(_tool(run_env.root), events=50000)
    step['parameters'].pop('launch')
    step.update(id='scan.point.p0', template_id='scan.point', rung='scan')
    step['budget']['wall_seconds'] = 21600
    step['parameters'].update(point_id='p0', item={'id': 'p0', 'parameters': {'x': 1}})
    signature = _signature()
    signature['cost']['unit'] = 'points'
    monkeypatch.setattr(operations, 'signatures', lambda: {'fixture-operation': signature})
    state = _reserve_state(run_env, step)
    assert budget.pilot_step(step) == (None, 'launch_not_declared')
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        graph.reserve(state)
    assert held.value.reason == 'awaiting_authority' and graph._pilot_trigger(state, held.value) is None
    assert records(run_env.store, budget.PILOT_LAUNCH) == records(run_env.store, budget.CALIBRATION) == []


@pytest.mark.parametrize('behaviour', ['exit', 'missing'])
def test_a_failed_pilot_holds_the_step_without_calibration_or_full_launch(run_env, inert_worker, graphs, signed,
                                                                         behaviour):
    outcome = run_step(run_env, _top(_tool(run_env.root, behaviour)))
    assert outcome['status'] == 'held' and outcome['reason'] == 'pilot_failed', outcome
    store = run_env.store
    assert _argv_events(run_env) == ['2']
    assert records(store, budget.CALIBRATION) == []
    assert [r['key'] for r in records(store, 'budget-reservation')] == ['g1/1/pilot']
    finished = [p for p in records(store, budget.PILOT_LAUNCH) if p['phase'] == 'finished']
    assert len(finished) == 1 and finished[0]['status'] != 'completed' and finished[0]['calibration'] is None


def test_a_launch_without_a_bounded_pilot_keeps_waiting_for_the_operator_and_runs_nothing(run_env, inert_worker,
                                                                                          graphs, signed):
    outcome = run_step(run_env, _top(_tool(run_env.root), token=False))
    assert outcome['status'] == 'held' and outcome['reason'] == 'awaiting_authority', outcome
    assert run_env.fakes['confine'].launched == [] and records(run_env.store, 'budget-reservation') == []
    assert records(run_env.store, budget.PILOT_LAUNCH) == [] and records(run_env.store, budget.CALIBRATION) == []
    with services.bound(run_env.store), pytest.raises(StepHold) as held:   # the derived nested attempt itself
        graph.reserve(_reserve_state(run_env, _top(_tool(run_env.root), token=False), pilot={'trigger': 'unattended'}))
    assert held.value.reason == 'pilot_underivable'


@pytest.mark.parametrize('mismatch', ['process', 'operation', 'machine'])
def test_a_mismatched_pilot_does_not_calibrate(run_env, inert_worker, graphs, signed, mismatch):
    step = _top(_tool(run_env.root))
    other = _top(_tool(run_env.root), process='b' * 64 if mismatch == 'process' else 'a' * 64,
                 operation='other-operation' if mismatch == 'operation' else 'fixture-operation')
    pilot, _ = budget.pilot_step(other)
    if mismatch == 'machine':
        run_env.store.append(budget.CALIBRATION, {
            'schema_version': 1, 'kind': budget.CALIBRATION, 'step_id': pilot['id'], 'operation': step['operation'],
            'process_sha256': budget.process_pin(step), 'machine_sha256': '0' * 64, 'rung': 'pilot',
            'status': 'succeeded', 'measured': {'wall_seconds': 0.1, 'events': 2}})
    else:
        budget.record_calibration(run_env.store, pilot, status='succeeded', measured={'wall_seconds': 0.1, 'events': 2})
    assert budget.calibration(run_env.store, step) is None
    assert budget.calibration_errors(run_env.store, step)[0]['code'] == 'uncalibrated_top_rung_cost'
    outcome = run_step(run_env, step)
    assert outcome['status'] == 'completed', outcome
    assert _argv_events(run_env) == ['2', '200']          # its own matched pilot ran first
    matched = budget.calibration(run_env.store, step)
    assert matched is not None and matched['step_id'] == budget.pilot_id('g1')


def test_a_verified_operator_admission_admits_without_a_pilot(run_env, monkeypatch, signed):
    calls = verified_interface(run_env, monkeypatch)
    state = _reserve_state(run_env, _top(_tool(run_env.root)), unattended=False)
    with services.bound(run_env.store):
        result = graph.reserve_point(state)
    assert len(calls) == 1 and result['reservation']['key'] == 'g1/1/producer'
    assert records(run_env.store, budget.PILOT_LAUNCH) == [] and run_env.fakes['confine'].launched == []
    assert records(run_env.store, budget.CALIBRATION) == []


@pytest.mark.parametrize('label', [FakeAuthority.MACHINE, FakeAuthority.TERMINAL])
def test_a_machine_or_unattested_admission_neither_admits_nor_pilots(run_env, monkeypatch, signed, label):
    calls = verified_interface(run_env, monkeypatch)
    run_env.fakes['authority'].answers['r3_action'] = ('approve', label, 'admit')
    state = _reserve_state(run_env, _top(_tool(run_env.root)), unattended=False)
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        graph.reserve_point(state)
    assert held.value.reason == 'uncalibrated_top_rung_cost' and calls == []
    assert records(run_env.store, 'budget-reservation') == [] and records(run_env.store, budget.PILOT_LAUNCH) == []
    assert run_env.fakes['confine'].launched == []
