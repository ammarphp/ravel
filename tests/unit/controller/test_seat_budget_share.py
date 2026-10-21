import pytest

from ravel.controller.step import cards, graph
from ravel.controller.step.services import StepHold


def _parent(budget, minimum=None):
    parameters = {}
    if minimum is not None:
        parameters['budget_minimum'] = minimum
    return {'id': 'parent', 'budget': budget, 'parameters': parameters,
            'depends_on': [], 'protocols': [], 'outputs': []}


def _seat():
    return {'purpose': 'review', 'role': 'review-role', 'n': 1, 'key': 'review-1',
            'subject': {'sha256': 'a' * 64, 'artifacts': []}}


def _card(wall=120, calls=8):
    return {'stop': {'max_wall_seconds': wall, 'max_turns': 4, 'max_broker_calls': calls,
                     'max_cost_usd': None, 'max_rounds': 4}}


def test_seat_inherits_session_shares_and_amounts_reserve_narrowed_card_budget():
    parent = _parent({'wall_seconds': 30, 'broker_calls': 5, 'tokens': 300, 'cost_usd': 2.0,
                      'core_hours': 1.0, 'events': 12, 'attempts': 4, 'review_rounds': 2,
                      'children': 3})
    derived = graph.seat_step(parent, _seat())

    # A seat starts one model session; its parent's launch share (events, core-hours) is never re-reserved.
    assert derived['budget'] == {'wall_seconds': 30, 'broker_calls': 5, 'tokens': 300, 'cost_usd': 2.0}
    assert graph._amounts(derived, _card(), 'worker') == {
        'wall_seconds': 30, 'model_calls': 4, 'tokens': 300, 'cost_usd': 2.0,
        'core_hours': 0, 'events': 0, 'children': 1}


def test_a_review_seat_of_a_launch_that_filled_the_event_ceiling_still_reserves(tmp_path):
    from ravel.controller.step import budget
    from test_p04_support import FakeStore

    store = FakeStore(tmp_path)
    parent = _parent({'wall_seconds': 30, 'cost_usd': 2.0, 'events': 12})
    ceilings = {d: None for d in budget.DIMENSIONS}
    ceilings.update(wall_seconds=3600, events=12, core_hours=1.0)
    launch = {**{d: 0 for d in budget.DIMENSIONS}, 'wall_seconds': 30, 'events': 12, 'core_hours': 1.0, 'children': 1}
    budget.reserve(store, step_id='parent', attempt=1, amounts=launch, ceilings=ceilings)
    amounts = graph._amounts(graph.seat_step(parent, _seat()), _card(), 'worker')
    seat = budget.reserve(store, step_id='parent', attempt=1, seat='review-role:1', amounts=amounts, ceilings=ceilings)
    assert seat['amounts']['events'] == 0 and seat['amounts']['core_hours'] == 0


def test_wider_parent_share_cannot_widen_card_wall_ceiling():
    derived = graph.seat_step(_parent({'wall_seconds': 900}), _seat())
    budgets, _ = cards.worker_budgets(_card(wall=45), derived)
    assert budgets['max_wall_seconds'] == 45


def test_explicit_minimum_that_exceeds_effective_card_share_holds():
    parent = _parent({'wall_seconds': 40}, {'wall_seconds': 35})
    derived = graph.seat_step(parent, _seat())
    with pytest.raises(StepHold) as caught:
        cards.worker_budgets(_card(wall=30), derived)
    assert caught.value.reason == 'seat_budget_infeasible'
    assert caught.value.evidence == {'dimension': 'wall_seconds', 'minimum': 35, 'ceiling': 30}


def test_zero_wall_share_holds_instead_of_rounding_up_to_one():
    with pytest.raises(StepHold) as caught:
        graph.seat_step(_parent({'wall_seconds': 0}), _seat())
    assert caught.value.reason == 'seat_budget_infeasible'
    assert caught.value.evidence == {'dimension': 'wall_seconds', 'minimum': 1, 'ceiling': 0}


def test_zero_card_cost_cannot_satisfy_a_positive_declared_minimum():
    derived = graph.seat_step(_parent({'wall_seconds': 40, 'cost_usd': 2}, {'cost_usd': 1}), _seat())
    card = _card()
    card['stop']['max_cost_usd'] = 0
    with pytest.raises(StepHold) as caught:
        cards.worker_budgets(card, derived)
    assert caught.value.reason == 'seat_budget_infeasible'
    assert caught.value.evidence == {'dimension': 'cost_usd', 'minimum': 1, 'ceiling': 0}


def test_empty_toolbelt_keeps_worker_compatibility_but_cannot_meet_a_broker_minimum():
    derived = graph.seat_step(_parent({'wall_seconds': 40, 'broker_calls': 2}, {'broker_calls': 1}), _seat())
    with pytest.raises(StepHold) as caught:
        cards.worker_budgets(_card(calls=0), derived)
    assert caught.value.reason == 'seat_budget_infeasible'
    assert caught.value.evidence == {'dimension': 'broker_calls', 'minimum': 1, 'ceiling': 0}
