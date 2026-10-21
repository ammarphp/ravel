"""Installed final-review specialists keep their duties in an applied plan."""
import pytest

from test_p18_policy import fakes
from ravel.controller.engagement import policy


@pytest.mark.parametrize('tier', ['lean', 'standard', 'full'])
@pytest.mark.parametrize('role', ['assumption-auditor', 'normalization-auditor'])
def test_policy_specialist_is_kept_on_a_fixed_route(tier, role):
    plan = fakes.fictional_plan()
    cards = policy.role_cards()
    installed = fakes.policy_for(plan, cards)
    plan['checkins'][-1]['seats'].append(role)
    derived = policy.seat_plan(plan, tier, installed, cards=cards, instructions=fakes.FakeInstructions)
    assert not derived['errors'], derived['errors']
    [seat] = [s for s in derived['seats'] if s['key'] == f'checkin:checkin3:{role}']
    assert seat['conditional'] is None and seat['source_seats'] == [f'checkin:checkin3:{role}']
    assert seat['items'], 'the specialist must retain its duties'


def test_unregistered_final_policy_role_stays_unclassified():
    plan = fakes.fictional_plan()
    cards = policy.role_cards()
    installed = fakes.policy_for(plan, cards)
    plan['checkins'][-1]['seats'].append('model-author')
    derived = policy.seat_plan(plan, 'full', installed, cards=cards, instructions=fakes.FakeInstructions)
    assert 'unclassified seat kept: checkin:checkin3:model-author' in derived['errors']
