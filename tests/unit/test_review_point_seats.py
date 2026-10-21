"""A controller run's review points are filled only by the seats the controller itself dispatches and credits, and its
final-task and delivery decisions map every original requirement to a delivered output or a recorded descope.

Real records throughout, as in the plan-approval tests (``test_rdj_approval``): a controller run store holding the
installed plan, its reading and custody, and each review's credit, observed seat session and review output as the
controller writes them. The stand-ins are the dispatcher-custody lookup of the packet a review read (it returns the
authenticated manifest of a real RAVEL projection built for the seat's card) and the intake seam ``_facts`` (the
request plan's claims). Inert controls only: no model call, network or native job.
"""
from __future__ import annotations

import json

import pytest

from ravel.controller.routes import plan_sha256
from ravel.workflow import rdj_approval, review_points

from test_rdj_approval import Approval, canonical

PROMPT = 'Estimate the fictional quantity and report it with its uncertainty. Also tabulate the toy spectrum.'
REQUIREMENTS = [{'id': 'quantity', 'evidence': [{'start': 0, 'end': 71, 'text': PROMPT[:71]}]},
                {'id': 'spectrum', 'evidence': [{'start': 72, 'end': len(PROMPT), 'text': PROMPT[72:]}]}]
PREDICTION = {'id': 'C1', 'kind': 'prediction', 'statement': 'The toy prediction.', 'obligation_ids': ['quantity'],
              'deliverable': {'artifact': 'binned_values', 'template': None}, 'basis_declared': ['unclassified']}
TRIAD = ('physics-critic', 'skeptical-verifier', 'physics-decider')


class Seats(Approval):
    """A controller run at its final review: an installed plan, its reading, an accepted output and a facts seam."""

    def __init__(self, tmp_path, monkeypatch, claims=(PREDICTION,)):
        super().__init__(tmp_path, monkeypatch)
        plan = {'nodes': [], 'claims': list(claims), 'edges': []}
        self.facts = {**plan, 'agent_layer_epoch': 2, 'delegated': False, 'plan': plan,
                      'contract': {'prompt': PROMPT, 'task_requirements': {'obligations': REQUIREMENTS}}}
        monkeypatch.setattr(review_points, '_facts', lambda root: self.facts)

    def install(self, deliverables, reading_deliverables):
        reading = {'kind': 'reading', 'deliverables': reading_deliverables}
        plan = {'schema_version': 1, 'kind': 'controller-plan', 'run_id': 'run-rdj-approval', 'revision': 0,
                'route': {'id': 'judgment', 'version': 1, 'spec_sha256': None},
                'steps': [{'id': 'derive', 'kind': 'derive'}], 'deliverables': deliverables,
                'checkins': [{'id': 'checkin3', 'seats': list(TRIAD)}],
                'reading_sha256': self.store.put_blob(canonical(reading))}
        plan['sha256'] = plan_sha256(plan)
        # A planning seat's candidate (no revision number) never stands for the installed plan.
        self.store.append('plan', {'plan_sha256': 'c' * 64, 'blob': self.store.put_blob(b'{}'), 'revision': None,
                                   'source': 'judgment-planning'})
        self.store.append('plan', {'plan_sha256': plan['sha256'], 'blob': self.store.put_blob(canonical(plan)),
                                   'source': 'judgment', 'revision': 0, 'route': 'judgment'})
        self.run.put('inputs/controller-plan.json', json.dumps(plan, indent=2, sort_keys=True))
        return plan

    def accept(self, artifact, destination, data):
        pin = self.run.put(destination, data)
        self.store.append('custody', {'artifact': artifact, 'destination': destination, 'sha256': pin['sha256'],
                                      'status': 'accepted'})
        return pin


@pytest.fixture
def seats(tmp_path, monkeypatch):
    return Seats(tmp_path, monkeypatch)


MAPPED = [{'id': 'D1', 'status': 'mapped', 'step': 'derive', 'output': 'outputs/result.json'}]
READING = [{'id': 'D1', 'obligation_ids': ['quantity', 'spectrum']}]


def _pending(errors):
    return sorted(i for e in errors if e.code == 'review_point_pending' for i in e.pins)


def test_the_final_review_seats_every_role_the_policy_owes_the_final_task(seats):
    seats.install(MAPPED, READING)
    # The delivery assumption audit (K8) applies to this request too: its auditor is seated at the final review.
    assert review_points.controller_seats(seats.root) == [*TRIAD, 'normalization-auditor', 'assumption-auditor']


def test_the_final_task_review_points_are_credited_from_the_controllers_own_final_review_seats(seats):
    plan = seats.install(MAPPED, READING)
    seats.accept('derive:outputs/result.json', 'steps/derive/outputs/result.json', {'value': 1.0})
    action = review_points.delivery_action(seats.root)
    for role in TRIAD:
        seats.review(plan, role, step_id='final_review')
    errors = review_points.gate_errors(seats.root, 'final_task', action)
    assert _pending(errors) == ['RP5:C1:normalization-auditor:1']
    [missing] = [e for e in errors if e.code == 'review_point_pending']
    assert 'no final review by normalization-auditor of plan' in missing.message
    seats.review(plan, 'normalization-auditor', step_id='final_review')
    assert review_points.gate_errors(seats.root, 'final_task', action) == []
    evidence = review_points.gate_evidence(seats.root, 'final_task', action)
    assert sorted(evidence['points']) == ['RP11:parent:physics-critic', 'RP11:parent:physics-decider',
                                          'RP11:parent:skeptical-verifier', 'RP4:C1:physics-critic',
                                          'RP4:C1:physics-decider', 'RP4:C1:skeptical-verifier', 'RP5:C1']
    decider = evidence['points']['RP4:C1:physics-decider'][0]
    assert decider['profile'] == 'full' and decider['step_id'] == 'final_review'   # the profile its card declares


@pytest.mark.parametrize('options, reason', [
    ({'step_id': 'plan_review'}, 'no final review by physics-critic'),
    ({'step_id': 'final_review', 'subject': 'f' * 64}, 'covers plan ffffffffffff, not the approved plan'),
    ({'step_id': 'final_review', 'credited': False}, 'is uncredited (author_context_review)'),
    ({'step_id': 'final_review', 'verdict': 'revise'}, "has verdict 'revise', not approve"),
    ({'step_id': 'final_review', 'observed': False}, 'was not credited from an observed seat session'),
])
def test_a_seat_that_is_not_the_credited_observed_final_review_of_this_plan_fills_no_point(seats, options, reason):
    plan = seats.install(MAPPED, READING)
    for role in TRIAD[1:] + ('normalization-auditor',):
        seats.review(plan, role, step_id='final_review')
    seats.review(plan, 'physics-critic', **options)
    errors = review_points.gate_errors(seats.root, 'final_task', review_points.delivery_action(seats.root))
    assert _pending(errors) == ['RP11:parent:physics-critic:physics-critic:1', 'RP4:C1:physics-critic:physics-critic:1']
    assert all(reason in e.message for e in errors if e.code == 'review_point_pending'), errors


def test_a_seat_reads_the_projection_its_card_declares_and_check_in_1_still_needs_a_blind_one(seats):
    plan = seats.install(MAPPED, READING)
    seats.review(plan, 'integrity-auditor', step_id='final_review')   # a full-profile card
    found, reason = rdj_approval.seat_review(seats.store, 'final_review', 'integrity-auditor', plan['sha256'],
                                             label='final review', blind=False)
    assert reason is None and found['profile'] == 'full'
    found, reason = rdj_approval.seat_review(seats.store, 'final_review', 'integrity-auditor', plan['sha256'],
                                             label='final review')
    assert found is None and "projection profile 'full' is not blind" in reason


def test_a_point_no_review_seat_fills_is_refused_by_name(tmp_path, monkeypatch):
    authored = {**PREDICTION, 'basis_declared': ['authored_code']}
    seats = Seats(tmp_path, monkeypatch, claims=(authored,))
    plan = seats.install(MAPPED, READING)
    assert 'object-selection-mapper' in review_points.controller_seats(seats.root)
    assert 'analysis-author' not in review_points.controller_seats(seats.root)   # a producer comparison, not a seat
    for role in (*TRIAD, 'normalization-auditor', 'object-selection-mapper'):
        seats.review(plan, role, step_id='final_review')
    errors = review_points.gate_errors(seats.root, 'final_task', review_points.delivery_action(seats.root))
    assert _pending(errors) == ['RP6:C1:divergence:analysis-author:1', 'RP6:C1:divergence:analysis-author:2']
    assert all('no controller seat fills a producer point' in e.message for e in errors if e.pins[0].startswith('RP6'))


def test_without_an_installed_plan_nothing_is_credited(seats):
    seats.plan()   # a plan record without a revision number: not installed by the controller
    errors = review_points.gate_errors(seats.root, 'final_task', {})
    assert len(_pending(errors)) == 7
    assert all('binds no verifiable plan' in e.message for e in errors if e.code == 'review_point_pending')


# ---- request fidelity: delivered outputs and recorded descopes (D-R5c) --------------------------------------------

OPEN = [*MAPPED, {'id': 'D2', 'status': 'open', 'reason': 'the toy spectrum needs a generator this run does not have'}]
SPLIT = [{'id': 'D1', 'obligation_ids': ['quantity']}, {'id': 'D2', 'obligation_ids': ['spectrum']}]


def _fidelity(seats, action):
    return [e for e in review_points._fidelity(seats.facts, action, 'final_task', seats.root)]


def test_each_requirement_maps_to_its_accepted_output_or_the_descope_the_approved_plan_records(seats):
    plan = seats.install(OPEN, SPLIT)
    pin = seats.accept('derive:outputs/result.json', 'steps/derive/outputs/result.json', {'value': 1.0})
    action = review_points.delivery_action(seats.root)
    assert action == {'outputs': [{'artifact': pin, 'requirement_ids': ['quantity'], 'deliverable': 'D1'}],
                      'descoped': [{'requirement_id': 'spectrum', 'deliverable': 'D2', 'plan_sha256': plan['sha256'],
                                    'reason': 'the toy spectrum needs a generator this run does not have'}]}
    assert _fidelity(seats, action) == []
    assert [e.pins for e in _fidelity(seats, {**action, 'descoped': []})] == [('requirement:spectrum',)]
    claimed = {**action, 'outputs': [{**action['outputs'][0], 'requirement_ids': ['quantity', 'spectrum']}],
               'descoped': []}
    assert [e.pins for e in _fidelity(seats, claimed)] == [('requirement:quantity',), ('requirement:spectrum',)]
    invented = {**action, 'descoped': [{**action['descoped'][0], 'reason': 'not needed'}]}
    assert [e.pins for e in _fidelity(seats, invented)] == [('requirement:spectrum',)]


def test_an_output_whose_bytes_changed_or_were_never_accepted_maps_nothing(seats):
    seats.install(MAPPED, READING)
    assert review_points.delivery_action(seats.root) == {'outputs': [], 'descoped': []}   # nothing accepted yet
    seats.accept('derive:outputs/result.json', 'steps/derive/outputs/result.json', {'value': 1.0})
    action = review_points.delivery_action(seats.root)
    assert _fidelity(seats, action) == []
    (seats.root / 'steps/derive/outputs/result.json').write_text('{"value": 2.0}')
    assert [e.pins for e in _fidelity(seats, action)] == [('requirement:quantity',), ('requirement:spectrum',)]


def test_a_mapped_deliverable_without_an_accepted_output_descopes_nothing(seats):
    seats.install(MAPPED, READING)
    seats.store.append('custody', {'artifact': 'derive:outputs/result.json', 'status': 'rejected',
                                   'destination': 'steps/derive/outputs/result.json', 'sha256': '0' * 64})
    assert review_points.delivery_action(seats.root) == {'outputs': [], 'descoped': []}
    assert len(_fidelity(seats, {'outputs': [], 'descoped': []})) == 2


def test_the_review_policy_classifies_a_check_by_the_specialist_rows_that_owe_it(seats):
    value = review_points.check_classification(seats.root, ['check:physics.normalization_ledger.check',
                                                            'check:validation.validate_task_contract.validate'])
    assert value['checks'] == {'check:physics.normalization_ledger.check': {
        'applies': True, 'rows': [5], 'points': ['RP5:C1'],
        'evidence': {'claim_dispositions': [{
            'claim_id': 'C1', 'applicable': True, 'disposition': 'applicable',
            'reason': 'binned_lineage_not_proven_pure_analytic',
            'evidence': {'ancestor_node_ids': [], 'ancestor_ids': [], 'computed_basis': [],
                         'signature_checks': [], 'normalization_facts': [], 'triggers': [],
                         'unresolved_lineage': [
                             {'ref': 'C1', 'reason': 'no_computed_analytic_basis'},
                             {'ref': 'C1', 'reason': 'unclassified_basis'}]}}]}}}
    # A check no specialist reviewer owes is unclassified; no claims means no disposition evidence.
    seats.facts = {**seats.facts, 'claims': [], 'plan': {'nodes': [], 'claims': [], 'edges': []}}
    value = review_points.check_classification(seats.root, ['check:physics.normalization_ledger.check'])
    assert value['checks'] == {'check:physics.normalization_ledger.check': {'applies': False, 'rows': [5],
                                                                             'points': []}}
    assert 'evidence' not in value['checks']['check:physics.normalization_ledger.check']
    assert value['derived_points_sha256'] == review_points.jdigest(review_points.derive(seats.facts))
