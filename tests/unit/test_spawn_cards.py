"""Synthetic contract controls for independent numerical reviewers."""
import pytest
from ravel.workflow import role_registry


@pytest.mark.parametrize('identity', ['re-deriver', 'comparative-reviewer', 'normalization-auditor'])
def test_review_cards_are_registered_and_blind(identity):
    card = role_registry.load(identity)
    assert card['family'] == 'specialist-review'
    assert card['requires']['blind'] and card['requires']['tools'] == 'broker-readonly'
    assert card['stop']['max_wall_seconds'] <= 1200
    assert 'other_verdicts' in card['sees']['forbidden_inputs']
    assert any('independ' in text.lower() for text in card['protocol'])
    assert not role_registry.validate_card(card)
