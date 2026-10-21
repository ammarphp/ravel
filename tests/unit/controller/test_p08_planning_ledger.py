"""Judgment planning plans on the real obligation ledger and run store.

A planning phase binds its own plan so the governed step finds each planning step's plan-stage
rows, and a plan the run already holds is the ledger's current plan again afterwards, whether the
phase completed or failed. Only the governed step is scripted.
"""
from __future__ import annotations

import pytest

from ravel.controller import ledger
from ravel.controller.judgment import graph, planning, services, steps
from ravel.controller.ledger import state as ledger_state
from ravel.controller.store import RunStore

RUN = 'run-planning-ledger-fixture'
READING = {'deliverables': [{'id': 'd1', 'description': 'A fictional value with its uncertainty.'}]}
PINS = {'reading_sha256': '0' * 64, 'contract_sha256': '1' * 64}


@pytest.fixture
def run(tmp_path):
    store = RunStore(RUN, root=tmp_path / 'store')
    state = {'context': {'run_id': RUN, 'run_dir': str(tmp_path / 'run'), 'store_root': str(store.store_root),
                         'mode': {'mode': 'autonomous', 'bounds': {}}, 'unattended': True}}
    ledger.materialise(store, 'intake', {'run_id': RUN, 'task_mode': None, 'deliverables': ['d1']})
    try:
        yield store, state
    finally:
        ledger_state.forget(store)


def _current(store):
    return (ledger_state.load(store, full=True).plan or {}).get('plan_sha256')


def _held(store, state):
    """A route plan the run holds (bound the way the route binds its approved plan)."""
    held = steps.planning_plan([{'id': 'held-step', 'kind': 'derive', 'role': 'calculation', 'inputs': [],
                                 'outputs': [], 'depends_on': [], 'review': [], 'obligations': []}],
                               run_id=RUN, reading=READING, request=PINS, phase='held')
    graph._bind(store, state, held, source='judgment-route')
    return held


def _frame_step():
    return steps.planner_step('frame', 1, inputs=[], purpose='Frame the fictional request.', output='frame',
                              obligations=['JR01', 'JR02'])


def test_a_planning_step_runs_under_its_materialised_plan_and_the_held_plan_returns(run):
    store, state = run
    held = _held(store, state)
    assert _current(store) == held['sha256']
    seen = []

    def step_run(store_, step, context):
        seen.append({'current': _current(store_), 'bound': context['plan_sha256'],
                     'keys': set(ledger_state.load(store_, full=True).plan_keys)})
        return {'step_id': step['id'], 'status': 'completed', 'outputs': [], 'receipts': []}

    step = _frame_step()
    with services.overridden(step_run=step_run):
        graph._run_planning_steps(store, state, {'reading': READING, **PINS}, 'frame', [step])
    assert len(seen) == 1 and seen[0]['current'] == seen[0]['bound'] != held['sha256']
    # The governed step's plan-stage rows of the planning step exist while it runs.
    assert ledger.instance_key('CF07', RUN, {'step': step['id']}) in seen[0]['keys']
    # The route's own rows are in the planning population, so a judgment node can record them.
    assert {ledger.instance_key(row, RUN, {}) for row in planning.ROUTE_ROWS} <= seen[0]['keys']
    assert _current(store) == held['sha256']
    assert graph.services.records(store, 'plan')[-1][1]['plan_sha256'] == held['sha256']


def test_a_failed_planning_phase_still_returns_the_held_plan(run):
    store, state = run
    held = _held(store, state)

    def step_run(store_, step, context):
        raise RuntimeError('the scripted governed step fails')

    with services.overridden(step_run=step_run), pytest.raises(RuntimeError):
        graph._run_planning_steps(store, state, {'reading': READING, **PINS}, 'frame', [_frame_step()])
    assert _current(store) == held['sha256']


def test_without_a_held_plan_the_planning_plan_stays_current_and_rebinding_appends_nothing(run):
    store, state = run
    with services.overridden(step_run=lambda store_, step, context: {'step_id': step['id'], 'status': 'completed'}):
        graph._run_planning_steps(store, state, {'reading': READING, **PINS}, 'start', [])
    first = _current(store)
    events = ledger_state.load(store, full=True).events
    records = len(graph.services.records(store, 'plan'))
    plan_doc = graph.services.blob_json(store, graph.services.records(store, 'plan')[-1][1]['blob'])
    graph._bind(store, state, plan_doc, source=graph.PLANNING_SOURCE)
    assert first == plan_doc['sha256'] and _current(store) == first
    assert ledger_state.load(store, full=True).events == events
    assert len(graph.services.records(store, 'plan')) == records
