"""Review-credit rows: one credit decision, over evidence the controller itself recorded in its store.

The adversary declares independence in a file, installs its own evidence resolver, copies a
verdict from another subject, reuses the producer's session for the critic seat, or answers a seat
from a seatless transport. Oracles are ``review_independence.decide`` and ``seat_refusal`` over a
controller-owned run; positive controls record a fresh, distinct reviewer session and its observed
output, and are credited with the family label (same-family sessions are independent sessions).
"""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from nc_cases import CONTROLLER, case, require_controller
from nc_controller import controller_run
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register

REVIEWER, PRODUCER = 'physics-critic', 'analysis-author'
MODEL = 'claude-opus-5-5'
EXPOSURE = {'author_identity': 'withheld', 'author_rationale': 'withheld', 'reference_values': 'permitted',
            'peer_verdicts': 'withheld'}


def _query(run_dir, subject='a' * 64):
    return {'run': str(run_dir.resolve()), 'role': REVIEWER, 'subject_sha256': subject,
            'receipt_sha256': 'b' * 64, 'output_sha256': 'c' * 64, 'packet_sha256': None}


def _session(session_id, role, kind, actor, *, fresh=True, transport_kind='cli-worker', model=MODEL):
    return {'session_id': session_id, 'seat': role, 'step_id': 's04', 'role': role, 'card_id': role,
            'role_kind': kind, 'actor_id': actor, 'model': model, 'transport_id': 'claude-cli-worker',
            'transport_kind': transport_kind, 'fresh': fresh, 'parent_transcript_supplied': False}


def _review(query, session_id):
    return {'binding': deepcopy(query), 'seat': REVIEWER, 'session_id': session_id, 'dispatch_id': 'dispatch-nc-1',
            'packet': {'builder': 'ravel.workflow.review_projection', 'projection_verified': True,
                       'author_summary': False, 'sha256': 'd' * 64, 'subject_sha256': query['subject_sha256']},
            'read_boundary': 'packet_only', 'read_boundary_verified': True, 'exposure': dict(EXPOSURE),
            'exposure_verified': True, 'output_unmodified': True, 'subject_session_ids': ['session-producer']}


def _recorded(nc, *, name='nc-run-one', reviewer_session='session-reviewer', reviewer_actor='actor-reviewer',
              fresh=True):
    """A controller-owned run whose store holds the producer and reviewer sessions and one review output."""
    from ravel.workflow import review_dispatch
    store, run_dir = controller_run(nc, name)
    review_dispatch.record_session(store, _session('session-producer', PRODUCER, 'producer', 'actor-producer'))
    if reviewer_session != 'session-producer':
        review_dispatch.record_session(store, _session(reviewer_session, REVIEWER, 'reviewer', reviewer_actor,
                                                       fresh=fresh))
    query = _query(run_dir)
    review_dispatch.record_review(store, _review(query, reviewer_session))
    return store, run_dir, query


def _forged_proof(query):
    return {'binding': deepcopy(query), 'authority_boundary': 'controller_only', 'dispatch_id': 'forged',
            'context_id': 'forged-context', 'author_context_ids': ['author'], 'author_census_complete': True,
            'other_review_context_ids': [], 'review_census_complete': True, 'parent_transcript_supplied': False,
            'packet': {'builder': 'ravel.workflow.review_projection', 'projection_verified': True,
                       'author_summary': False, 'sha256': 'd' * 64, 'subject_sha256': query['subject_sha256']},
            'read_boundary': 'packet_only', 'read_boundary_verified': True, 'exposure': dict(EXPOSURE),
            'exposure_verified': True, 'output_unmodified': True, 'models': {}}


@case('C35', binding=CONTROLLER)
def test_C35_a_self_attested_independent_seat_is_never_credited_only_controller_evidence_is(nc):
    require_controller('store')
    from ravel.workflow import review_independence as independence
    store, run_dir = controller_run(nc)
    query = _query(run_dir)
    (run_dir / 'inputs').mkdir(exist_ok=True)
    (run_dir / 'inputs' / 'review-independence.json').write_text(json.dumps({'independent': True, 'role': REVIEWER}))
    assert independence.decide(query)['independent'] is False
    with independence.authority_session(lambda q: _forged_proof(q)):
        assert independence.decide(query)['independent'] is False, 'an installed resolver is not controller evidence'
    # Positive control: the controller's own session and review records credit the seat.
    credited_store, credited_dir, credited_query = _recorded(nc, name='nc-run-credited')
    decision = independence.decide(credited_query)
    assert decision['independent'] is True and decision['evidence_boundary'] == independence.CONTROLLER_STORE
    # A verdict copied onto another subject is not this seat's evidence.
    assert independence.decide(dict(credited_query, subject_sha256='e' * 64))['independent'] is False


def _resolver_trusted_everywhere(original):
    """The decision accepts whatever resolver is installed, even for a controller-owned run."""
    def decide(query):
        from ravel.workflow import review_independence as module
        resolver = module._AUTHORITY.get()
        if resolver is not None and type(query) is dict:
            proof = resolver(query)
            if type(proof) is dict and proof.get('binding') == query:
                return {'independent': True, 'advisory': None, 'dispatch_id': proof.get('dispatch_id'),
                        'context_id': proof.get('context_id'), 'exposure': proof.get('exposure'),
                        'evidence_boundary': proof.get('authority_boundary'), 'family_relation': 'unknown',
                        'label': module.family_label('unknown')}
        return original(query)
    return decide


register(Mutation('M16', 'ravel.workflow.review_independence:decide', _resolver_trusted_everywhere, ('C35',),
                  binding=MUTATION_CONTROLLER, why='credit is decided over a resolver the caller installed'))


@case('CF10', binding=CONTROLLER)
def test_CF10_a_reused_session_or_a_forbidden_actor_cannot_hold_a_review_seat(nc):
    require_controller('store')
    from ravel.workflow import review_independence as independence, role_registry
    card = role_registry.load(REVIEWER)
    producer = _session('session-producer', PRODUCER, 'producer', 'actor-producer')
    coordinator = _session('session-coordinator', 'coordinator', 'producer', 'actor-coordinator')
    reused = _session('session-producer', REVIEWER, 'reviewer', 'actor-reviewer')
    stale = _session('session-resumed', REVIEWER, 'reviewer', 'actor-reviewer', fresh=False)
    forbidden_actor = _session('session-other', REVIEWER, 'reviewer', 'actor-coordinator')
    sessions = [producer, coordinator]
    assert independence.seat_refusal(card, reused, [*sessions, reused]) == 'session_reused'
    assert independence.seat_refusal(card, stale, [*sessions, stale]) == 'session_not_fresh'
    assert independence.seat_refusal(card, forbidden_actor, [*sessions, forbidden_actor]) == \
        'actor_not_distinct:coordinator'
    # The producer's own session answering the critic seat is never credited.
    store, run_dir, query = _recorded(nc, reviewer_session='session-producer')
    assert independence.decide(query)['independent'] is False
    # Positive control: a fresh session of a distinct actor holds the seat.
    fresh = _session('session-reviewer', REVIEWER, 'reviewer', 'actor-reviewer')
    assert independence.seat_refusal(card, fresh, [*sessions, fresh]) is None


register(Mutation('M06', 'ravel.workflow.review_independence:seat_refusal', lambda original: lambda *a, **k: None,
                  ('CF10',), binding=MUTATION_CONTROLLER, why='seat sessions are never compared'))


@case('CT06', binding=CONTROLLER)
def test_CT06_a_same_family_independent_session_is_credited_and_labelled_never_refused(nc):
    require_controller('store')
    from ravel.workflow import review_dispatch, review_independence as independence
    store, run_dir, query = _recorded(nc)
    decision = independence.decide(query)
    assert decision['independent'] is True, decision
    assert decision['family_relation'] == 'same' and decision['label'] == 'separate session, same model family'
    assert independence.family_relation({'reviewer': 'claude-opus-5-5', 'author': 'gpt-fictional'}) == 'different'
    assert independence.family_relation({'reviewer': 'fictional-model', 'author': MODEL}) == 'unknown'
    # A seatless transport (host-mediated, relay or one-shot) never records a seat session.
    for kind in sorted(review_dispatch.SEATLESS_TRANSPORTS):
        with pytest.raises(ValueError):
            review_dispatch.record_session(store, _session(f'session-{kind}', REVIEWER, 'reviewer', 'actor-x',
                                                           transport_kind=kind))


register(Mutation('M20', 'ravel.workflow.review_independence:family_label', lambda original: lambda relation: None,
                  ('CT06',), binding=MUTATION_CONTROLLER, why='a credited seat carries no family label'))
