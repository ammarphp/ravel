"""The rdj requirement of a controller run's plan approval is discharged only by the run's independent review evidence.

Real records throughout: a controller run store under a test root holding the plan, and each review's credit,
observed seat session and review output as the controller writes them (the independence decision reads only that
store). The CHECK-IN 1 review and an RDJ case are the same kind of evidence: a governed review seat, the RDJ case
by a card of the RDJ family on a step's exact spec digest. The one stand-in is the dispatcher-custody lookup of the
packet a review read: it returns the authenticated manifest of a real RAVEL projection built for the seat's card.
Inert controls only: no model call, network or native job.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ravel.controller import store as controller_store
from ravel.controller.routes import plan_sha256
from ravel.workflow import rdj_approval, rdj_loop as rdj, review_dispatch, review_independence, review_projection

from rdj_fixtures import Run

RUN_ID = 'run-rdj-approval'
SEAT = 'plan_review-node:1'
EXPOSURE = {'author_identity': 'permitted', 'author_rationale': 'withheld', 'reference_values': 'permitted',
            'peer_verdicts': 'withheld'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


class Approval:
    """One controller run awaiting CHECK-IN 1: its run directory, its store and the plan it is asked to approve."""

    def __init__(self, tmp_path, monkeypatch):
        monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
        self.run = Run(tmp_path / 'run', cost=None)
        self.root = self.run.root.resolve()
        real = controller_store.RunStore
        monkeypatch.setattr(controller_store, 'RunStore', lambda run_id, *, root=None: real(
            run_id, root=root or tmp_path / 'controller'))
        monkeypatch.setattr(controller_store, 'controller_owned',
                            lambda run_dir: RUN_ID if Path(run_dir).resolve() == self.root else None)
        self.store = controller_store.RunStore(RUN_ID)
        self.packets = {}
        monkeypatch.setattr(review_dispatch, 'observed_projection',
                            lambda query: review_dispatch._manifest(self.packets.get(query['role'])))

    def plan(self, steps=(), seats=('plan-critic',)):
        plan = {'schema_version': 1, 'kind': 'controller-plan', 'run_id': RUN_ID,
                'route': {'id': 'judgment', 'version': 1, 'spec_sha256': None}, 'steps': list(steps),
                'deliverables': [], 'checkins': [{'id': 'checkin1', 'seats': list(seats)}]}
        plan['sha256'] = plan_sha256(plan)
        self.store.append('plan', {'plan_sha256': plan['sha256'], 'blob': self.store.put_blob(canonical(plan)),
                                   'source': 'judgment-route'})
        self.run.put('inputs/controller-plan.json', json.dumps(plan, indent=2, sort_keys=True))
        return plan

    def review(self, plan, role='plan-critic', *, subject=None, verdict='accept', credited=True, n=1,
               step_id='plan_review', observed=True, session_role=None):
        """A review of ``subject`` (``plan``'s digest by default) by ``role`` as the controller observes and credits
        it. ``observed=False`` leaves out the observed seat session and review output; ``session_role`` records the
        observed session under another role name."""
        subject = subject or plan['sha256']
        packet = review_projection.project(self.root, role, key=f'{step_id}-{role}-{n}',
                                           subjects=['inputs/controller-plan.json'])
        self.packets[role] = packet
        session = f'worker-session:claude-cli-worker:{step_id}-{role}-{n}'
        seat = f'{SEAT}-{step_id}-{n}'
        query = {'run': str(self.root), 'role': role, 'subject_sha256': subject,
                 'receipt_sha256': hashlib.sha256(f'receipt-{step_id}-{role}-{n}'.encode()).hexdigest(),
                 'output_sha256': hashlib.sha256(f'output-{step_id}-{role}-{n}'.encode()).hexdigest(),
                 'packet_sha256': None}
        if observed:
            named = session_role or role
            review_dispatch.record_session(self.store, {
                'session_id': session, 'seat': seat, 'step_id': step_id, 'role': named, 'card_id': named,
                'role_kind': 'reviewer', 'actor_id': f'actor-{step_id}-{role}-{n}', 'model': 'claude-fixture-model',
                'transport_id': 'claude-cli-worker', 'transport_kind': 'cli-worker', 'fresh': True,
                'parent_transcript_supplied': False})
            review_dispatch.record_review(self.store, {
                'binding': query, 'seat': seat, 'session_id': session, 'dispatch_id': f'worker:{step_id}/{n}#token',
                'packet': {'builder': review_dispatch.PROJECTION, 'projection_verified': True, 'author_summary': False,
                           'sha256': packet['manifest_sha256'], 'subject_sha256': subject},
                'read_boundary': 'packet_only', 'read_boundary_verified': True, 'exposure': EXPOSURE,
                'exposure_verified': True, 'output_unmodified': True})
        decision = review_independence.decide(dict(query))
        if not credited:
            decision = {'independent': False, 'advisory': 'author_context_review'}
        elif not observed:
            # As credited when the review ran; the observation is not in the store now.
            decision = {'independent': True, 'advisory': None, 'evidence_boundary': review_independence.CONTROLLER_STORE,
                        'context_id': session, 'dispatch_id': f'worker:{step_id}/{n}#token'}
        own = {'credited': decision.get('independent') is True, 'decision': decision,
               'family_relation': decision.get('family_relation'), 'label': decision.get('label'),
               'evidence_boundary': decision.get('evidence_boundary'), 'query': query, 'verdict': verdict}
        return self.store.append('step-credit', {'schema_version': 1, 'step_id': step_id, 'attempt': n,
                                                 'seats': [], 'own': own, 'credited': own['credited']})

    def rdj_case(self, plan, spec_sha256, role='rdj-critic', **options):
        """The RDJ case seat of one plan step: a governed review of its exact spec digest."""
        return self.review(plan, role, subject=spec_sha256, step_id='judgment-rdj-choose-method-0-1', **options)

    def action(self, plan_sha):
        pins = {'plan_sha256': plan_sha, 'request_sha256': '1' * 64, 'reading_sha256': '2' * 64,
                'contract_sha256': '3' * 64, 'route': 'judgment'}
        return {'kind': 'controller.approve_plan', 'digest': hashlib.sha256(canonical(pins)).hexdigest(),
                'summary': 'controller approve_plan', 'pins': [], 'node_id': None, 'rung': None, 'scope': None,
                'view_pins': pins}


@pytest.fixture
def approval(tmp_path, monkeypatch):
    return Approval(tmp_path, monkeypatch)


def errors(approval, action):
    return rdj.gate_errors(approval.root, 'approve_plan', action)


DERIVE = {'id': 'derive', 'kind': 'derive', 'consequence_class': 'R0'}
SPEC = hashlib.sha256(b'the exact spec of the decide step').hexdigest()


def decide_step(cls='R2', spec=SPEC):
    return {'id': 'choose-method', 'kind': 'decide', 'consequence_class': cls,
            'parameters': {'judgment': {'spec_sha256': spec}}}


def test_the_credited_blind_approving_reviews_discharge_the_approval(approval):
    # Positive control: the CHECK-IN 1 review covers this exact plan, and the R2 decide step's RDJ case is an
    # RDJ-card review of its exact spec, credited from its observed blind seat session.
    plan = approval.plan([DERIVE, decide_step()])
    credit = approval.review(plan)
    case_credit = approval.rdj_case(plan, SPEC)
    action = approval.action(plan['sha256'])
    assert errors(approval, action) == []
    assert rdj.authorizing_receipt(approval.root, 'approve_plan', action) is None  # no receipt; the mapping decided
    evidence = rdj.gate_evidence(approval.root, 'approve_plan', action)
    assert evidence['mechanism'] == 'rdj_approval.mapping' and evidence['plan_sha256'] == plan['sha256']
    assert evidence['action_digest'] == action['digest']
    [review] = evidence['reviews']
    assert review['credit'] == credit and review['verdict'] == 'accept' and review['profile'] == 'spec-denied'
    [case] = evidence['rdj_cases']
    assert case['step'] == 'choose-method' and case['class'] == 'R2' and case['subject_sha256'] == SPEC
    assert case['credit'] == case_credit and case['role'] == 'rdj-critic' and case['profile'] == 'blind', case
    assert case['step_id'] == 'judgment-rdj-choose-method-0-1'


def test_an_uncredited_checkin1_review_refuses(approval):
    plan = approval.plan([DERIVE])
    approval.review(plan, credited=False)
    action = approval.action(plan['sha256'])
    found = errors(approval, action)
    assert [e.code for e in found] == ['rdj_receipt_missing']
    assert 'is uncredited (author_context_review)' in found[0].message
    assert rdj.gate_evidence(approval.root, 'approve_plan', action) is None


def test_a_checkin1_review_with_verdict_revise_refuses(approval):
    plan = approval.plan([DERIVE])
    approval.review(plan, verdict='revise')
    found = errors(approval, approval.action(plan['sha256']))
    assert [e.code for e in found] == ['rdj_receipt_missing']
    assert "has verdict 'revise', not approve" in found[0].message


def test_a_checkin1_review_of_a_different_plan_digest_refuses(approval):
    reviewed = approval.plan()
    asked = approval.plan([DERIVE])
    approval.review(reviewed)
    found = errors(approval, approval.action(asked['sha256']))
    assert [e.code for e in found] == ['rdj_receipt_missing']
    assert f"covers plan {reviewed['sha256'][:12]}, not the approved plan {asked['sha256'][:12]}" in found[0].message


@pytest.mark.parametrize('kind, cls', [('decide', 'R2'), ('operate', 'R3')])
def test_an_r2_or_r3_step_without_its_rdj_case_refuses(approval, kind, cls):
    step = {**decide_step(cls), 'kind': kind}
    plan = approval.plan([DERIVE, step])
    approval.review(plan)
    found = errors(approval, approval.action(plan['sha256']))
    assert [e.code for e in found] == ['rdj_receipt_missing']
    assert (f'step choose-method (class {cls}) has no credited RDJ case on its spec {SPEC[:12]}: no RDJ case decided it'
            in found[0].message)


def test_an_rdj_case_on_another_spec_digest_does_not_count(approval):
    plan = approval.plan([DERIVE, decide_step()])
    approval.review(plan)
    approval.rdj_case(plan, hashlib.sha256(b'other bytes of the step').hexdigest())
    found = errors(approval, approval.action(plan['sha256']))
    assert [e.code for e in found] == ['rdj_receipt_missing'] and 'no RDJ case decided it' in found[0].message


def test_a_review_of_the_spec_by_a_role_outside_the_rdj_family_does_not_count(approval):
    plan = approval.plan([DERIVE, decide_step()])
    approval.review(plan)
    approval.rdj_case(plan, SPEC, role='plan-critic')
    found = errors(approval, approval.action(plan['sha256']))
    assert [e.code for e in found] == ['rdj_receipt_missing']
    assert 'reviewed only by plan-critic, not by an RDJ role' in found[0].message


def test_an_rdj_case_observed_under_another_role_does_not_count(approval):
    plan = approval.plan([DERIVE, decide_step()])
    approval.review(plan)
    approval.rdj_case(plan, SPEC, session_role='rdj-verifier')   # the observed session is another card's
    found = errors(approval, approval.action(plan['sha256']))
    assert [e.code for e in found] == ['rdj_receipt_missing'] and 'is uncredited' in found[0].message


def test_an_rdj_case_without_its_observed_session_does_not_count(approval):
    plan = approval.plan([DERIVE, decide_step()])
    approval.review(plan)
    approval.rdj_case(plan, SPEC, observed=False)
    found = errors(approval, approval.action(plan['sha256']))
    assert [e.code for e in found] == ['rdj_receipt_missing']
    assert 'was not credited from an observed blind seat session' in found[0].message


@pytest.mark.parametrize('options, expected', [({'credited': False}, 'its RDJ case is uncredited'),
                                               ({'verdict': 'revise'}, "its RDJ case has verdict 'revise'")])
def test_an_uncredited_or_revising_rdj_case_does_not_count(approval, options, expected):
    plan = approval.plan([DERIVE, decide_step()])
    approval.review(plan)
    approval.rdj_case(plan, SPEC, **options)
    found = errors(approval, approval.action(plan['sha256']))
    assert [e.code for e in found] == ['rdj_receipt_missing'] and expected in found[0].message


def test_an_observed_session_named_by_the_underscore_spelling_is_the_same_card(approval):
    # RDJ role calls name their role rdj_critic: the one name-to-card mapping makes it the rdj-critic card.
    plan = approval.plan([DERIVE, decide_step()])
    approval.review(plan)
    approval.rdj_case(plan, SPEC, session_role='rdj_critic')
    assert errors(approval, approval.action(plan['sha256'])) == []


def test_a_review_read_from_a_projection_that_is_not_blind_refuses(approval):
    plan = approval.plan([DERIVE], seats=('integrity-auditor',))  # a full-profile card that does not require blindness
    approval.review(plan, role='integrity-auditor')
    found = errors(approval, approval.action(plan['sha256']))
    assert [e.code for e in found] == ['rdj_receipt_missing']
    assert "projection profile 'full' is not blind" in found[0].message


def test_an_action_that_does_not_commit_to_its_view_pins_refuses(approval):
    plan = approval.plan([DERIVE])
    approval.review(plan)
    action = approval.action(plan['sha256'])
    assert errors(approval, action) == []
    for broken in ({**action, 'view_pins': {**action['view_pins'], 'plan_sha256': 'f' * 64}},
                   {k: v for k, v in action.items() if k != 'view_pins'}):
        assert [e.code for e in errors(approval, broken)] == ['rdj_receipt_missing'], broken


def test_an_approval_raised_above_r2_also_needs_an_rdj_case_on_its_exact_action(approval):
    plan = approval.plan([DERIVE])
    approval.review(plan)
    action = approval.action(plan['sha256'])
    assert errors(approval, action) == []
    found = errors(approval, {**action, 'floor': 'R3'})
    assert [e.code for e in found] == ['rdj_receipt_missing']
    assert 'no decision-justification receipt at approve_plan for this exact action' in found[0].message


def test_a_run_the_controller_does_not_own_keeps_the_receipt_rule(approval, tmp_path):
    other = Run(tmp_path / 'legacy', cost=None)
    found = rdj.gate_errors(other.root, 'approve_plan', other.action())
    assert [e.code for e in found] == ['rdj_receipt_missing'] and 'receipt' in found[0].message
    assert rdj.gate_evidence(other.root, 'approve_plan', other.action()) is None
    assert rdj_approval.applies(other.root) is False
