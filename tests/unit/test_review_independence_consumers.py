"""Consumer controls use actual receipt readers and inert transport fixtures."""
from copy import deepcopy
import hashlib

import pytest

from ravel.workflow import review_independence as ri, review_points as rp
from ravel.workflow import physics_review, scientific_judgment, research_protocol, research_cycle
from test_review_independence import evidence
from test_review_points import run as point_run, receipt as point_receipt
from test_physics_review import run, opened
from test_scientific_judgment import prepare, FakeHost, observed_role_boundary


@pytest.fixture(autouse=True)
def private_state(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'machine-state'))


@pytest.mark.parametrize('phase', ['plan', 'claim', 'final'])
def test_checkin_consumers_require_controller_evidence(tmp_path, phase):
    root = tmp_path / 'study'
    point_run(root, nodes=[{'id': 'N', 'operation': 'fictional_operation'}],
              claims=[{'id': 'C', 'kind': 'exclusion'}])
    points = rp.derive(rp._facts(root))
    selected = next(p for p in points if p['row'] == {'plan': 1, 'claim': 4, 'final': 11}[phase])
    for seat in selected['roles']:
        point_receipt(root, selected['id'], seat['role'])
    assert not rp.satisfied(root, selected['id'])
    records = list(rp._receipt_records(root, rp._facts(root)))
    assert all(not rp._receipt_report(r)['independent'] for r in records)
    with ri.authority_session(evidence):
        assert rp.satisfied(root, selected['id'])
    with ri.authority_session(lambda q: evidence(q, context_id='author-one')):
        assert not rp.satisfied(root, selected['id'])


def test_legacy_submission_retains_advice_without_journal_or_closure(run):
    root, _ = run; opened(run)
    before = physics_review._read(root)[1]
    result = physics_review.submit_review(root, role='physics_critic', actor_id='critic',
        verdict='accept', summary='Synthetic declared-name verdict', claim_scope='reproduction')
    assert result['independent'] is False and result['advisory'] == 'declared_name_advice'
    assert physics_review._read(root)[1] == before
    assert physics_review.gate_errors(root, 'delivery')


def dispatch_record(event):
    from ravel.workflow import review_dispatch
    return review_dispatch._store() / (event['independence_evidence']['query']['receipt_sha256'] + '.json')


def test_scientific_vote_requires_context_authority(run, tmp_path, observed_role_boundary):
    root, _ = run; opened(run)
    binding = prepare(root, tmp_path, 'critic')
    scientific_judgment.execute_role(binding, FakeHost())
    # A controller that vouches for nothing, or for an author's own context, leaves the vote advisory.
    for refusing in (lambda _: None, lambda q: evidence(q, context_id='author-one')):
        with ri.authority_session(refusing):
            with pytest.raises(ValueError, match='no independent credit'):
                scientific_judgment.consume(root, binding, allow_control=True)
    # By default the evidence is the graph runner's own record of this observed dispatch.
    result = scientific_judgment.consume(root, binding, allow_control=True)
    assert ri.journal_decision(root, result)['independent']
    with ri.authority_session(lambda _: None):
        assert not ri.journal_decision(root, result)['independent']
    # The recorded journal vote keeps no credit of its own once that record is gone.
    dispatch_record(result).unlink()
    assert not ri.journal_decision(root, result)['independent']


def test_control_transport_vote_has_no_dispatch_authority(run, tmp_path):
    root, _ = run; opened(run)
    binding = prepare(root, tmp_path, 'critic')
    scientific_judgment.execute_role(binding, FakeHost())
    with ri.authority_session(evidence):
        with pytest.raises(ValueError, match='self-attested|control transport'):
            scientific_judgment.consume(root, binding, allow_control=True)
    from ravel.workflow import agent_graph
    receipt = agent_graph.role_receipt(binding['graph_root'], binding['node_id'],
        expected_subject_sha256=binding['subject_sha256'], allowed_roles={'critic'})
    assert not ri.graph_decision(root, receipt)['independent']


@pytest.mark.parametrize('action', ['report_only', 'candidate_revision', 'resolve_objections'])
def test_untrusted_meta_cannot_change_protocol_or_clear_objections(tmp_path, monkeypatch, action):
    from test_research_protocol import make, meta
    root, _ = make(tmp_path, monkeypatch)
    result = meta(tmp_path, root, monkeypatch, action, stages=['new-full'], transport='control')
    assert result['independent'] is False
    assert result['value']['response']['action'] == action
    assert not any(e['kind'] == 'protocol_meta_review_applied' for e in research_cycle._load(root)[1]['events'])


def test_trusted_meta_action_and_later_authority_loss(tmp_path, monkeypatch):
    from test_research_protocol import make, meta
    root, _ = make(tmp_path, monkeypatch)
    with ri.authority_session(evidence):
        result = meta(tmp_path, root, monkeypatch, 'candidate_revision', stages=['new-full'], transport='control')
    event = result['events'][-1]
    assert event['independence']['independent'] and event['invalidated_stage_ids']
    assert not ri.graph_decision(root, event['role_receipt'])['independent']


def test_observed_meta_action_applies_from_the_runner_record(tmp_path, monkeypatch):
    from test_research_protocol import make, meta
    root, _ = make(tmp_path, monkeypatch)
    result = meta(tmp_path, root, monkeypatch, 'candidate_revision', stages=['new-full'])
    event = result['events'][-1]
    assert event['independence']['independent'] and event['invalidated_stage_ids']
    assert ri.meta_decision(event)['independent']
    with ri.authority_session(lambda _: None):
        assert not ri.meta_decision(event)['independent']


def test_rdj_human_authorization_does_not_upgrade_independence(tmp_path):
    from rdj_fixtures import Run
    from test_rdj_authority import full_r2
    from ravel.workflow import rdj_loop
    run = Run(tmp_path / 'rdj-study')
    with ri.authority_session(evidence):
        case_id = full_r2(run)
        case, state, _ = rdj_loop._load(run.root, case_id)
        assert rdj_loop._attestation_summary(run.root, case, state)['independent']
    summary = rdj_loop._attestation_summary(run.root, case, state)
    assert not summary['independent']
    assert all(a == 'self_attested' for a in summary['edge_reviewers'])
    run.approve(case_id)
    summary = rdj_loop._attestation_summary(run.root, case, state)
    assert summary['human_approver'] and not summary['independent']


def test_repair_design_uses_same_author_separation_decision(run, tmp_path, observed_role_boundary):
    from test_scientific_judgment import complete, repair
    root, _ = run; opened(run)
    with ri.authority_session(evidence):
        complete(root, prepare(root, tmp_path / 'result', 'critic'), FakeHost(verdict='send_back'))
        improver = prepare(root, tmp_path / 'proposal', 'improver', scope=None)
        complete(root, improver, FakeHost(proposal=repair()))
        scientific_judgment.apply_proposal(root, improver, allow_control=True)
        skeptic = prepare(root, tmp_path / 'skeptic', 'verifier', scope=None, proposal_binding=improver)
        scientific_judgment.execute_role(skeptic, FakeHost())
        with ri.authority_session(lambda q: evidence(q, context_id='author-one')
                                 if q['role'] == 'verifier' else evidence(q)):
            with pytest.raises(ValueError, match='author_context_review'):
                scientific_judgment.verify_binding(skeptic, allow_control=True)
        assert scientific_judgment.verify_binding(skeptic, allow_control=True)['review_independence']['independent']
        assert physics_review.status(root)['redos_used'] == 0


def test_final_output_mutation_cannot_keep_credit(tmp_path):
    root = tmp_path / 'study'
    point_run(root, claims=[{'id': 'C', 'kind': 'exclusion'}])
    point = next(p for p in rp.derive(rp._facts(root)) if p['row'] == 4)
    role = point['roles'][0]['role']
    point_receipt(root, point['id'], role)
    with ri.authority_session(evidence):
        assert rp.satisfied(root, point['id'])
        final = next(root.glob('agent-work/*/1/final.json'))
        final.write_text('{"findings": [], "verdict": "accept"}')
        assert not rp.satisfied(root, point['id'])


def test_detached_acceptance_rechecks_all_three_dispatches(run, tmp_path, observed_role_boundary):
    from test_scientific_judgment import complete
    root, _ = run; opened(run)
    events = [complete(root, prepare(root, tmp_path / 'roles', role)) for role in ('critic', 'verifier', 'synthesizer')]
    snapshot = physics_review.snapshot(root, action='delivery')
    assert physics_review.validate_snapshot(snapshot) == []
    assert all(r['independent'] for r in physics_review.status(root)['review_independence'])
    with ri.authority_session(lambda _: None):
        errors = physics_review.validate_snapshot(snapshot)
        assert any('no independent credit' in error for error in errors)
    # Detached admission rechecks every dispatch: one lost record withdraws the credit.
    dispatch_record(events[1]).unlink()
    errors = physics_review.validate_snapshot(snapshot)
    assert any('no independent credit' in error for error in errors)
    # The same bytes remain readable as historical advice.
    assert physics_review.validate_snapshot(snapshot, require_admission=False) == []


def test_current_rdj_authority_does_not_relabel_old_receipt_independence(tmp_path):
    from rdj_fixtures import Run
    from test_rdj_authority import full_r2
    from ravel.workflow import rdj_loop
    run = Run(tmp_path / 'rdj-study')
    with ri.authority_session(evidence):
        case_id = full_r2(run)
        receipt = rdj_loop.authorize(run.root, case_id)
        assert receipt['attestation_summary']['independent']
    run.approve(case_id)
    case, _, _ = rdj_loop._load(run.root, case_id)
    accepted = rdj_loop.authorizing_receipt(run.root, case['decision_point']['gate'], run.action())
    assert accepted is not None
    assert accepted['receipt'] == receipt  # original scientific record remains intact
    assert accepted['review_independence']['independent'] is False
    assert accepted['review_independence']['human_approver']


@pytest.mark.parametrize('mutation', ['done', 'withdrawn', 'deleted', 'unregistered_pin'])
def test_advisory_downgrade_preserves_registered_blocking_findings(tmp_path, mutation):
    from test_review_credit_regressions import test_queue_edits_cannot_disarm_registered_finding
    test_queue_edits_cannot_disarm_registered_finding(tmp_path, mutation)
    records = list(rp._receipt_records(tmp_path, rp._facts(tmp_path)))
    assert any(r.get('findings') for r in records)
    assert all(not rp._receipt_report(r)['independent'] for r in records)
