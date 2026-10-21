"""Budget rows: every effect is reserved in the store before it starts, and nothing is refunded by word.

The adversary races two children for the last unit, retries after an ambiguous start, resumes
after a crash hoping for fresh counters, and asks for more than its rung allows. Oracles are the
store's reservations and the refusals of the reservation node; positive controls reserve within
the ceiling.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from nc_cases import CONTROLLER, ROOT, case, require_controller
from nc_controller import controller_run, store_root
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register

DIMENSIONS = ('wall_seconds', 'model_calls', 'tokens', 'cost_usd', 'core_hours', 'events', 'children')
CEILINGS = {'wall_seconds': 100, 'model_calls': 10, 'tokens': None, 'cost_usd': None, 'core_hours': None,
            'events': 1000, 'children': 4}


def amounts(**values):
    base = {d: 0 for d in DIMENSIONS}
    base.update(children=1, model_calls=1)
    base.update(values)
    return base


def _budget(nc):
    budget = require_controller('step.budget')
    store, _ = controller_run(nc, mode='autonomous')
    return budget, store


def _hold_type(budget):
    return getattr(budget, 'StepHold', Exception)


RACE = '''
import json, sys
sys.path.insert(0, sys.argv[1])
from ravel.controller import store as st
from ravel.controller.step import budget
store = st.RunStore(sys.argv[3], root=sys.argv[2])
try:
    budget.reserve(store, step_id=sys.argv[4], attempt=1, amounts=json.loads(sys.argv[5]), ceilings=json.loads(sys.argv[6]))
    print("granted")
except Exception as exc:
    print("refused:" + getattr(exc, "reason", type(exc).__name__))
'''


@case('B02', binding=CONTROLLER)
def test_B02_two_children_racing_for_the_last_reservation_cannot_both_pass(nc):
    budget, store = _budget(nc)
    budget.reserve(store, step_id='s01', attempt=1, amounts=amounts(wall_seconds=60), ceilings=CEILINGS)
    with pytest.raises(_hold_type(budget)):
        budget.reserve(store, step_id='s02', attempt=1, amounts=amounts(wall_seconds=41), ceilings=CEILINGS)
    procs = [subprocess.Popen([sys.executable, '-B', '-c', RACE, str(ROOT / 'src'), str(store_root(nc)),
                               store.run_id, f's-race-{n}', json.dumps(amounts(wall_seconds=30)),
                               json.dumps(CEILINGS)], stdout=subprocess.PIPE, text=True) for n in range(2)]
    outcomes = sorted(p.communicate(timeout=120)[0].strip() for p in procs)
    assert outcomes[0] == 'granted' and outcomes[1].startswith('refused:'), outcomes
    rows = store.scan('budget-reservation')
    charged = sum((row.get('record', row))['amounts']['wall_seconds'] for row in rows)
    assert charged <= CEILINGS['wall_seconds'] and len(rows) == 2


@case('A07', binding=CONTROLLER)
def test_A07_a_pilot_asking_more_events_than_its_rung_allows_is_refused_before_launch(nc):
    budget, store = _budget(nc)
    with pytest.raises(_hold_type(budget)) as refused:
        budget.reserve(store, step_id='s-pilot', attempt=1, amounts=amounts(events=5000), ceilings=CEILINGS)
    assert getattr(refused.value, 'reason', '') == 'budget_exhausted'
    with pytest.raises(_hold_type(budget)):
        budget.reserve(store, step_id='s-pilot-unknown', attempt=1, amounts=amounts(events=None), ceilings=CEILINGS)
    assert store.scan('budget-reservation') == []
    budget.reserve(store, step_id='s-pilot', attempt=2, amounts=amounts(events=500), ceilings=CEILINGS)  # positive


register(Mutation('M17', 'ravel.controller.step.budget:reserve',
                  lambda original: lambda store, **kw: original(store, **dict(kw, ceilings={d: None for d in DIMENSIONS})),
                  ('A07', 'B02', 'B01'), binding=MUTATION_CONTROLLER, why='reservations ignore the ceilings'))


@case('B01', binding=CONTROLLER)
def test_B01_children_retries_and_ambiguous_starts_stay_charged_across_a_resume(nc):
    budget, store = _budget(nc)
    first = budget.reserve(store, step_id='s01', attempt=1, amounts=amounts(wall_seconds=40), ceilings=CEILINGS)
    budget.settle(store, first['key'], status='ambiguous', evidence={'reason': 'fictional timeout before a receipt'})
    budget.reserve(store, step_id='s01', attempt=2, amounts=amounts(wall_seconds=40), ceilings=CEILINGS)
    # The controller restarts: a fresh store object over the same run has the same charges.
    store_module = require_controller('store')
    resumed = store_module.RunStore(store.run_id)
    totals = budget.totals(resumed, CEILINGS)
    assert totals['wall_seconds']['charged'] == 80, totals['wall_seconds']
    with pytest.raises(_hold_type(budget)):
        budget.reserve(resumed, step_id='s02', attempt=1, amounts=amounts(wall_seconds=21), ceilings=CEILINGS)
    budget.reserve(resumed, step_id='s02', attempt=1, amounts=amounts(wall_seconds=20), ceilings=CEILINGS)  # positive


@case('E30', binding=CONTROLLER)
def test_E30_an_ambiguous_start_is_reconciled_never_redispatched_as_a_new_charge(nc):
    budget, store = _budget(nc)
    first = budget.reserve(store, step_id='s-rdj', attempt=1, amounts=amounts(wall_seconds=30), ceilings=CEILINGS)
    budget.settle(store, first['key'], status='ambiguous', evidence={'reason': 'started; no receipt'})
    with pytest.raises(_hold_type(budget)):
        budget.reserve(store, step_id='s-rdj', attempt=1, amounts=amounts(wall_seconds=10), ceilings=CEILINGS)
    again = budget.reserve(store, step_id='s-rdj', attempt=1, amounts=amounts(wall_seconds=30), ceilings=CEILINGS)
    assert again['key'] == first['key'] and len(store.scan('budget-reservation')) == 1
    assert budget.unsettled_prior(store, 's-rdj', 2), 'a second attempt waits for the first to be reconciled'
    budget.settle(store, first['key'], status='reconciled', measured=amounts(wall_seconds=12),
                  evidence={'receipt': 'fictional-reconciled-receipt'})
    assert not budget.unsettled_prior(store, 's-rdj', 2)  # positive control
