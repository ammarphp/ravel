"""Inert controller controls: no network, model calls or scientific execution."""
from copy import deepcopy

import pytest

from ravel.workflow import review_independence as ri


def query(**changes):
    return {'run': '/fictional/run', 'role': 'critic', 'subject_sha256': 'a' * 64,
            'receipt_sha256': 'b' * 64, 'output_sha256': 'c' * 64,
            'packet_sha256': 'd' * 64, **changes}


def evidence(binding, **changes):
    """Test controller response, installed only inside this test's scoped seam."""
    return {'binding': deepcopy(binding), 'authority_boundary': 'controller_only',
            'dispatch_id': 'dispatch-' + binding['receipt_sha256'],
            'context_id': 'child-' + binding['receipt_sha256'],
            'author_context_ids': ['author-one', 'author-two'], 'author_census_complete': True,
            'other_review_context_ids': [], 'review_census_complete': True,
            'parent_transcript_supplied': False,
            'packet': {'builder': 'ravel.workflow.review_projection', 'projection_verified': True,
                       'author_summary': False, 'sha256': binding['packet_sha256'] or 'd' * 64,
                       'subject_sha256': binding['subject_sha256']},
            'read_boundary': 'packet_only', 'read_boundary_verified': True,
            'exposure': {'author_identity': 'withheld', 'author_rationale': 'withheld',
                         'reference_values': 'permitted', 'peer_verdicts': 'withheld'},
            'exposure_verified': True, 'output_unmodified': True, **changes}


def test_forged_perfect_verdict_and_context_flags_have_no_authority():
    q = query()
    assert not ri.decide(q)['independent']
    assert not ri.decide({**q, 'proof': evidence(q), 'independent': True})['independent']
    with ri.authority_session(lambda _: None):
        assert not ri.decide(q)['independent']
    with ri.authority_session(evidence):
        result = ri.decide(q)
        assert result['independent'] and result['advisory'] is None
    assert not ri.decide(q)['independent']  # no process-global or saved flag leakage


@pytest.mark.parametrize('field,value,reason', [
    ('authority_boundary', 'same_user_files', 'dispatch_authority_unprotected'),
    ('context_id', None, 'context_unknown'),
    ('context_id', 'author-one', 'author_context_review'),
    ('context_id', 'author-two', 'author_context_review'),
    ('author_context_ids', [], 'author_context_unknown'),
    ('author_context_ids', ['author-one', None], 'author_context_unknown'),
    ('author_census_complete', False, 'author_context_unknown'),
    ('review_census_complete', False, 'review_context_unknown'),
    ('other_review_context_ids', ['child-' + 'b' * 64], 'review_context_reused'),
    ('parent_transcript_supplied', True, 'inherited_or_unknown_transcript'),
    ('parent_transcript_supplied', None, 'inherited_or_unknown_transcript'),
    ('read_boundary', 'shared_workspace', 'packet_only_access_unverified'),
    ('read_boundary_verified', False, 'packet_only_access_unverified'),
    ('exposure_verified', False, 'permitted_exposure_unverified'),
    ('exposure', {'reference_values': 'permitted'}, 'permitted_exposure_unverified'),
    ('output_unmodified', False, 'review_output_changed'),
])
def test_unknown_or_unsafe_context_always_advisory(field, value, reason):
    with ri.authority_session(lambda q: evidence(q, **{field: value})):
        result = ri.decide(query())
    assert result['independent'] is False and result['advisory'] == reason


@pytest.mark.parametrize('field', ['run', 'role', 'subject_sha256', 'receipt_sha256', 'output_sha256', 'packet_sha256'])
def test_signed_invocation_cannot_be_rebound(field):
    q = query()
    proof = evidence(q)
    changed = {**q, field: 'e' * 64 if field.endswith('sha256') else 'different'}
    with ri.authority_session(lambda _: proof):
        assert not ri.decide(changed)['independent']


@pytest.mark.parametrize('field,value', [('builder', 'author-summary'), ('author_summary', True),
    ('projection_verified', False), ('sha256', 'e' * 64), ('subject_sha256', 'e' * 64)])
def test_author_framing_or_changed_packet_receives_no_credit(field, value):
    q = query(); proof = evidence(q); proof['packet'][field] = value
    with ri.authority_session(lambda _: proof):
        assert not ri.decide(q)['independent']


def test_fresh_same_model_child_allowed_but_previous_phase_session_refused():
    q = query(); proof = evidence(q)
    proof['model_family'] = proof['author_model_family'] = 'fictional-family'
    with ri.authority_session(lambda _: proof):
        assert ri.decide(q)['independent']
        proof['other_review_context_ids'] = [proof['context_id']]
        assert ri.decide(q)['advisory'] == 'review_context_reused'


def test_authority_failure_is_advice_and_scopes_restore():
    def unavailable(_):
        raise OSError('controller unavailable')
    with ri.authority_session(evidence):
        with ri.authority_session(unavailable):
            assert not ri.decide(query())['independent']
        assert ri.decide(query())['independent']


def test_persisted_credit_flag_is_not_an_authority(tmp_path):
    from ravel.workflow import execution
    import json
    event = {'role': 'physics_critic', 'verdict': 'accept', 'summary': 'Synthetic response',
             'findings': [], 'closes': [], 'claim_scope': 'diagnostic', 'independent': True,
             'cycle_id': 'cycle'}
    assert ri.journal_decision(tmp_path, event)['advisory'] == 'declared_name_advice'
    request = tmp_path / 'request.json'
    request.write_text(json.dumps({'rundir': str(tmp_path), 'role': 'critic', 'cycle_id': 'cycle',
                                   'phase': 'result_review'}))
    subject = execution.file_hash(request)
    value = {k: v for k, v in event.items() if k not in {'role', 'independent', 'cycle_id'}}
    value['subject_sha256'] = subject
    q = query(run=str(tmp_path.resolve()), output_sha256=ri.digest(value), subject_sha256=subject)
    event['independence_evidence'] = {'query': q, 'response': value,
                                    'request': {'path': str(request), 'sha256': subject}}
    with ri.authority_session(evidence):
        assert ri.journal_decision(tmp_path, event)['independent']
        event['cycle_id'] = 'other-cycle'
        assert not ri.journal_decision(tmp_path, event)['independent']
        event['cycle_id'] = 'cycle'
        event['closes'] = ['unreviewed-objection']
        assert not ri.journal_decision(tmp_path, event)['independent']
    assert not ri.journal_decision(tmp_path, event)['independent']


def test_retained_advice_never_claims_authority(tmp_path):
    response = {'verdict': 'accept', 'independent': True, 'closes': ['objection']}
    result = ri.retain_advice(tmp_path, response, ri.advisory('unverified'))
    assert result['independent'] is False and result['execution_authorized'] is False
    assert result['value'] == response
    assert ri.retain_advice(tmp_path, response, ri.advisory('unverified')) == result


def test_old_external_meta_resolution_never_clears_objections():
    from ravel.workflow import research_protocol as protocol
    objection = {'kind': 'protocol_meta_review_applied', 'action': 'additional_evidence',
                 'revision': 1, 'affected_claim_ids': ['claim'], 'resolves_meta_revisions': []}
    resolution = {'kind': 'protocol_meta_review_applied', 'action': 'resolve_objections',
                  'revision': 2, 'affected_claim_ids': ['claim'], 'resolves_meta_revisions': [1],
                  'role_receipt': {'attestation': 'host_attested', 'independent': True}}
    assert protocol._active_holds({'events': [objection, resolution]}, 'claim') == [objection]
    assert not ri.meta_decision(resolution)['independent']
