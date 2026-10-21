"""Route evidence cannot replace the controller's canonical authority subjects."""
from copy import deepcopy

import pytest

from ravel.controller import graph


def test_route_evidence_adds_pins_without_replacing_current_controller_scope():
    current = {'plan_sha256': 'a' * 64, 'waypoint:p': 'b' * 64}
    before = deepcopy(current)
    result = graph._merge_checkin_pins(current, {'waypoint_document:p': 'c' * 64,
                                                'plan_sha256': current['plan_sha256']})
    assert result == {**before, 'waypoint_document:p': 'c' * 64}
    assert current == before


@pytest.mark.parametrize('key', ['plan_sha256', 'approve_plan', 'waypoint:p', 'checkin2_review',
                                'request_sha256', 'contract_sha256', 'applied_sha256'])
def test_adapter_conflicting_with_a_controller_pin_is_a_typed_refusal(key):
    original = {key: 'a' * 64}
    with pytest.raises(graph.nodes.RecoveryHold) as held:
        graph._merge_checkin_pins(original, {key: 'b' * 64})
    assert held.value.reason == 'checkin_pin_conflict'
    assert original == {key: 'a' * 64}
