"""Role names resolve to card ids through one mapping generated from the role-card registry.

``role_registry.card_ids`` lists every registered card under its id and the id's underscore spelling (the form the
RDJ loop's agent-role names take); nothing else is listed and nothing is written by hand. Every comparison of
role identities (worker receipts, observed sessions, review packets, RDJ role calls) goes through it.
"""
from __future__ import annotations

import pytest

from ravel.workflow import rdj_loop, role_registry


def test_every_rdj_capable_role_resolves_through_the_generated_mapping():
    ids = role_registry.card_ids()
    rdj_cards = {card['id'] for card in role_registry.all_cards() if card['family'] == 'rdj'}
    assert rdj_cards, 'the registry holds the RDJ family'
    # Every agent-role name the RDJ loop dispatches resolves to an RDJ card, and together they cover the family.
    assert {ids[name] for name in rdj_loop.AGENT_ROLES.values()} == rdj_cards
    for card in rdj_cards:
        assert ids[card] == card and ids[card.replace('-', '_')] == card
        assert role_registry.same_card(card, card.replace('-', '_'))


def test_the_mapping_is_generated_from_the_card_ids_alone():
    document = role_registry.registry_document()
    expected = {}
    for card in document['roles']:
        expected[card] = card
        expected[card.replace('-', '_')] = card
    assert role_registry.card_ids() == expected
    # Where the registry's own alias list names a card by its underscore spelling, the two agree.
    for alias, target in document['aliases'].items():
        if alias == target.replace('-', '_'):
            assert role_registry.card_id(alias) == target


def test_colliding_spellings_refuse_the_whole_mapping():
    with pytest.raises(ValueError, match='would name two cards'):
        role_registry.card_ids(document={'roles': {'a-b': {}, 'a_b': {}}, 'aliases': {}})


def test_a_name_the_mapping_does_not_list_matches_only_itself():
    assert role_registry.same_card('unlisted-role', 'unlisted-role')
    assert not role_registry.same_card('unlisted-role', 'rdj-critic')
    assert not role_registry.same_card('rdj_critic', 'rdj-verifier')
    assert not role_registry.same_card(None, None) and not role_registry.same_card('', '')
    assert role_registry.card_id('unlisted-role') is None and role_registry.card_id(None) is None
