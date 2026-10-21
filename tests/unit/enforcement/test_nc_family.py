"""Family-removal rows: independence rests on separate sessions, actors and packets, never on a model family.

The adversary (here the retired rule itself) would refuse a same-family reviewer, keep a card's
family list, flip the RDJ verifier flag, or deliver an instruction that mandates a second family.
Oracles: the effective cards, the label functions (which never refuse), the RDJ policy and the
installed instruction catalogue; positive controls show the session and actor separation that
replaces the family rule still refuses what it should.
"""
from __future__ import annotations

import json
import re

import pytest

from nc_cases import CONTROLLER, case, require_controller
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register

SAME = 'separate session, same model family'
# A sentence that makes a second model family a requirement (the XF08 rewrite removes every one):
# an obligation verb followed by a family that must differ, unless the sentence negates it.
_OTHER_FAMILY = (r'(\b(different|second|distinct|another|other|cross)[- ]((model|provider|transport)[- ])?famil(y|ies)\b'
                 r'|\bfamil(y|ies)\b[^.]{0,20}?\b(distinct|different)\s+from\b)')
MANDATE = re.compile(r'(?i)\b(must|required?|requires|needs?|shall|has to|have to|runs? in|comes? from)\b'
                     r'[^.]{0,120}?' + _OTHER_FAMILY)
NEGATED = re.compile(r"(?i)\b(never|not|no longer|without)\b|n't\b")
CARD_FAMILY = re.compile(r'"distinct_family_from"\s*:\s*\[\s*"')


def mandates(text):
    """The sentences of one instruction unit that require a second model family."""
    if CARD_FAMILY.search(text):
        return [text]
    sentences = re.split(r'(?<=[.;:])\s+', ' '.join(text.split()))
    return [s for s in sentences if MANDATE.search(s) and not NEGATED.search(s)]


def _session(session_id, role, kind, actor, *, fresh=True):
    return {'session_id': session_id, 'seat': role, 'step_id': 's04', 'role': role, 'card_id': role,
            'role_kind': kind, 'actor_id': actor, 'model': 'claude-opus-5-5', 'transport_id': 'claude-cli-worker',
            'transport_kind': 'cli-worker', 'fresh': fresh, 'parent_transcript_supplied': False}


@case('XF01', binding=CONTROLLER)
def test_XF01_the_ml_reviewer_card_keeps_session_and_actor_separation_without_a_family_list(nc):
    require_controller()
    from ravel.workflow import review_independence as independence, role_registry
    card = role_registry.load('ml-reviewer')
    assert card['model']['distinct_family_from'] == [], card['model']
    assert 'ml-trainer' in card['independence']['distinct_actor_from'] and card['independence']['fresh_session']
    trainer = _session('session-trainer', 'ml-trainer', 'producer', 'actor-trainer')
    same_family = _session('session-reviewer', 'ml-reviewer', 'reviewer', 'actor-reviewer')
    assert independence.seat_refusal(card, same_family, [trainer, same_family]) is None
    # Positive control: the trainer's own actor still cannot hold the reviewer seat.
    trainer_actor = _session('session-other', 'ml-reviewer', 'reviewer', 'actor-trainer')
    assert independence.seat_refusal(card, trainer_actor, [trainer, trainer_actor]) == 'actor_not_distinct:ml-trainer'


@case('XF03', binding=CONTROLLER)
def test_XF03_the_receipt_time_family_check_labels_and_never_refuses(nc):
    require_controller()
    from ravel.workflow import transport_registry as tr
    card = {'id': 'fictional-reviewer', 'model': {'distinct_family_from': ['fictional-producer']}}
    same = tr.check_distinct_families(card, {'fictional-reviewer': 'claude-opus-5-5',
                                             'fictional-producer': 'claude-sonnet-5-5'})
    assert same == 'same', same
    different = tr.check_distinct_families(card, {'fictional-reviewer': 'claude-opus-5-5',
                                                  'fictional-producer': 'gpt-fictional'})
    assert different == 'different'  # positive control: the relation is computed, as a label
    unknown = tr.check_distinct_families(card, {'fictional-reviewer': 'fictional-model'})
    assert unknown == 'unknown'


register(Mutation('M20', 'ravel.workflow.review_independence:family_relation',
                  lambda original: lambda models: 'unknown', ('XF03',), binding=MUTATION_CONTROLLER,
                  why='the family label is never computed'))


def _r3_case():
    node = {'id': 'action', 'kind': 'action', 'assertion': 'Deliver the fictional result.', 'rationale': 'It is fictional.',
            'material': True, 'confidence': 'high', 'assumptions': [], 'unknowns': [], 'recommends_choice': None,
            'anchors': []}
    return {'case_id': 'case-nc-r3', 'risk': {'class': 'R3'}, 'revisions': [], 'critique': {'findings': []},
            'nodes': [node], 'anchors': [], 'edges': [], 'decision_point': {'action': {'digest': 'c' * 64}}}


def _actor(name):
    return {'actor_id': f'actor-{name}', 'session_receipt': f'receipt-{name}', 'attestation': 'transport_attested'}


@case('XF05', binding=CONTROLLER)
def test_XF05_a_same_family_seat_is_credited_by_session_independence_with_its_label(nc):
    require_controller('store')
    from ravel.workflow import review_independence as independence, review_points
    from test_nc_review_credit import _recorded
    store, run_dir, query = _recorded(nc)
    decision = independence.decide(query)
    receipt = {'_path': 'agent-work/nc/1/receipt.json', '_label': 'transport_attested', '_eligible': True,
               '_advisory': None, '_independence': decision}
    report = review_points._receipt_report(receipt)
    assert report['independent'] is True, (decision, report)
    assert report['family_relation'] == 'same' and report['label'] == SAME
    # Positive control: a self-attested receipt is not independent and carries no family label.
    unattested = review_points._receipt_report({**receipt, '_label': 'self_attested',
                                                '_independence': independence.advisory('self_attested')})
    assert unattested['independent'] is False and 'label' not in unattested


def _same_family_refused(original):
    """The retired rule: a reviewer of the producer's family is not credited."""
    def decide(query):
        decision = original(query)
        if decision.get('family_relation') == 'same':
            return {**decision, 'independent': False, 'advisory': 'same_model_family'}
        return decision
    return decide


register(Mutation('M16', 'ravel.workflow.review_independence:decide', _same_family_refused, ('XF05',),
                  binding=MUTATION_CONTROLLER, why='credit refused to a same-family reviewer session'))


@case('XF07', binding=CONTROLLER)
def test_XF07_the_rdj_r3_verifier_is_never_refused_for_its_family(nc):
    require_controller()
    from ravel.paths import package_data_path
    from ravel.workflow import rdj_loop
    policy = json.loads(package_data_path('rdj', 'policy.json').read_text())
    assert policy['r3_distinct_family'] is False
    critic, verifier = _actor('critic'), _actor('verifier')
    families = {'receipt-critic': 'family-a'}
    output = {'per_finding': [], 'outcome': 'authorize'}
    case_, state = _r3_case(), {'authors': [_actor('author')], 'reviewer_sessions': [], 'critic_sessions': [critic],
                                'blocking': {}}
    try:
        rdj_loop._record_verification(nc.root, case_, state, output, verifier, 'family-a', families)
    except rdj_loop.IndependenceError as refused:
        pytest.fail(f'a separate-session verifier was refused for sharing the critic family: {refused}')
    assert case_['verification']['outcome'] == 'authorize' and state['verified_digest']
    # Positive control: the verifier still cannot share the critic's session (at R3 and at every other class).
    shared = {**_actor('verifier'), 'session_receipt': 'receipt-critic'}
    case_, state = _r3_case(), {'authors': [_actor('author')], 'reviewer_sessions': [], 'critic_sessions': [critic],
                                'blocking': {}}
    with pytest.raises(rdj_loop.IndependenceError, match='different sessions and actors at every class'):
        rdj_loop._record_verification(nc.root, case_, state, output, shared, 'family-b', families)
    assert 'verification' not in case_


def _every_session_shared(original):
    # Independence at R3 is session and actor identity, never model family (the legacy family flag no longer
    # vetoes): treating every pair as one session is the mechanism failure that refuses a separate verifier.
    return lambda a, b: True


register(Mutation('M20', 'ravel.workflow.rdj_loop:_same', _every_session_shared, ('XF07',), binding=MUTATION_CONTROLLER,
                  why='the RDJ verifier is refused although it is a separate session and actor'))


@case('XF08', binding=CONTROLLER)
def test_XF08_no_delivered_instruction_mandates_a_second_model_family(nc):
    instructions = require_controller('instructions')
    catalogue = instructions.installed()
    assert catalogue.units, 'the installed instruction catalogue is not empty'
    planted = ('Every critic must come from a different model family than the producer.',
               'The reviewer is blind, and runs in a model family distinct from the\ntrainer\'s.',
               'A role entry that names it needs a registered\ntransport family different from each named role.',
               '{"distinct_family_from": ["fictional-producer"], "tier": "judgment"}')
    assert all(mandates(text) for text in planted), 'positive control: the detector finds each planted mandate'
    allowed = ('Independent review never requires a different model family.', SAME,
               'The label reads separate session, different model family.', '{"distinct_family_from": []}')
    assert not any(mandates(text) for text in allowed), 'negative control: labels and negations are not mandates'
    found = {uid: mandates(unit.get('text', '')) for uid, unit in catalogue.units.items()}
    found = {uid: hits[0][:160] for uid, hits in sorted(found.items()) if hits}
    assert found == {}, found


@case('CF14', binding=CONTROLLER)
def test_CF14_a_same_family_reviewer_session_is_independent_and_labelled_as_such(nc):
    require_controller()
    from ravel.workflow import review_independence as independence, role_registry
    relation = independence.family_relation({'reviewer': 'claude-opus-5-5', 'author': 'claude-sonnet-5-5'})
    assert relation == 'same' and independence.family_label(relation) == SAME
    assert all(role_registry.load(c['id'])['model']['distinct_family_from'] == []
               for c in role_registry.all_cards()), 'no card keeps a family requirement'
    reviewer = role_registry.load('physics-critic')
    producer = _session('session-producer', 'analysis-author', 'producer', 'actor-producer')
    seat = _session('session-reviewer', 'physics-critic', 'reviewer', 'actor-reviewer')
    assert independence.seat_refusal(reviewer, seat, [producer, seat]) is None
    reused = _session('session-producer', 'physics-critic', 'reviewer', 'actor-reviewer')
    assert independence.seat_refusal(reviewer, reused, [producer, reused]) == 'session_reused'  # positive control
