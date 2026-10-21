"""Review seats, reviewer items and the evidence log.

The adversary plans a producer without the reviewer its card names, credits a review that skips
an item or gives a verdict without evidence, and claims knowledge it never queried. Oracles are
seat derivation, the item-verdict check and the evidence-log labels; positive controls hold the
seat, answer every item with evidence and query what they claim.
"""
from __future__ import annotations

from nc_cases import CONTROLLER, case, require_controller
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register


def _producer_with_reviewer():
    from ravel.workflow import role_registry
    card = next(c for c in role_registry.all_cards() if c.get('reviewed_by'))
    return card, list(card['reviewed_by'])


@case('CF08', binding=CONTROLLER)
def test_CF08_a_plan_without_the_card_reviewer_seat_still_owes_it_before_delivery(nc):
    require_controller()
    from ravel.workflow import review_points
    card, reviewers = _producer_with_reviewer()
    owed = review_points.reviewed_by_seats(card['id'], seats=[])
    assert [seat['role'] for seat in owed] == reviewers
    assert all(seat['blocking'] and seat['gate'] == 'delivery' for seat in owed)
    # A caller-supplied seat list can add seats but never remove the card's reviewers.
    owed_again = review_points.reviewed_by_seats(card['id'], seats=['fictional-extra-seat'])
    assert [seat['role'] for seat in owed_again] == reviewers
    step_graph = require_controller('step.graph')
    roles = step_graph._seat_roles(None, {'review': []}, card, {})
    assert set(reviewers) <= set(roles), roles
    # Positive control: once the reviewer seats are held, nothing more is owed.
    assert review_points.reviewed_by_seats(card['id'], seats=reviewers) == []


register(Mutation('M15', 'ravel.workflow.review_points:reviewed_by_seats', lambda original: lambda *a, **k: [],
                  ('CF08',), binding=MUTATION_CONTROLLER, why='the card reviewer seat is not derived'))


def _items(instructions, role='physics-critic'):
    from ravel.workflow import role_registry
    card = role_registry.load(role)
    items = instructions.reviewer_items({'units': []}, card)
    assert items and all(i['kind'] == 'must_check' for i in items)
    return items


@case('CF12', binding=CONTROLLER)
def test_CF12_credit_needs_one_verdict_with_evidence_for_every_reviewer_item(nc):
    instructions = require_controller('instructions')
    items = _items(instructions)
    complete = {'item_verdicts': [{'item': i['id'], 'verdict': 'pass', 'evidence': ['outputs/review.json#/checks'],
                                   'note': None} for i in items]}
    assert instructions.check_item_verdicts(items, complete) == []  # positive control
    skipped = {'item_verdicts': complete['item_verdicts'][1:]}
    assert any(e.startswith('missing:') and items[0]['id'] in e
               for e in instructions.check_item_verdicts(items, skipped))
    bare = {'item_verdicts': [dict(row, evidence=[]) for row in complete['item_verdicts']]}
    assert any(e.startswith('evidence:') for e in instructions.check_item_verdicts(items, bare))
    forged = {'item_verdicts': [*complete['item_verdicts'], {'item': 'must_check:fictional', 'verdict': 'pass',
                                                             'evidence': ['x']}]}
    assert any(e.startswith('unknown:') for e in instructions.check_item_verdicts(items, forged))
    assert instructions.check_item_verdicts(items, {'completed': True}) == ['item_verdicts[] is missing']


register(Mutation('M14', ('ravel.controller.instructions.ack:check_item_verdicts',
                          'ravel.controller.instructions:check_item_verdicts'),
                  lambda original: lambda *a, **k: [], ('CF12',), binding=MUTATION_CONTROLLER,
                  why='a review is credited without a verdict per item'))


@case('I07', binding=CONTROLLER)
def test_I07_knowledge_claimed_without_a_query_that_reached_it_is_labelled_unsupported(nc):
    evidence = require_controller('step.evidence')
    final = {'completed': True, 'summary': 'fictional', 'knowledge_used': ['hb:fictional-handbook']}
    no_query = [{'action': 'read', 'status': 'ok', 'knowledge': None}]
    labels = evidence.knowledge_labels(final, no_query)
    assert labels == [{'label': 'knowledge_use_unsupported', 'id': 'hb:fictional-handbook', 'queried': False}]
    other_query = [{'action': 'knowledge query', 'status': 'ok', 'knowledge': ['hb:another-handbook']}]
    assert [l['id'] for l in evidence.knowledge_labels(final, other_query)] == ['hb:fictional-handbook']
    refused = [{'action': 'knowledge query', 'status': 'refused', 'knowledge': ['hb:fictional-handbook']}]
    assert [l['id'] for l in evidence.knowledge_labels(final, refused)] == ['hb:fictional-handbook']
    reached = [{'action': 'knowledge query', 'status': 'ok', 'knowledge': ['hb:fictional-handbook']}]
    assert evidence.knowledge_labels(final, reached) == []  # positive control


register(Mutation('M25', 'ravel.controller.step.evidence:knowledge_labels', lambda original: lambda *a, **k: [],
                  ('I07',), binding=MUTATION_CONTROLLER, why='claimed knowledge use is never checked against the log'))
