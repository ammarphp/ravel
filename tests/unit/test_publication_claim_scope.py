"""Authored, NOT RUN: canonical scope through real ordinary review/planning.

The inherited fixture supplies inert runtime bytes and isolates author
authentication. Review policy, adapter scope, science.plan, verify_plan and
approval absence are real. No provider, compiler, worker or native run occurs.
The root native courier separately retains the actual writer/collection chain.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from ravel.physics import manuscript_build as mb
from ravel.workflow import physics_review, science
from test_publication_prepare_build import preparation_inputs, prepare


def test_exported_scope_connects_review_identifier_and_delivery_contract(tmp_path, monkeypatch):
    config, goal, review, calls = preparation_inputs(tmp_path, monkeypatch)
    assert mb.SCOPE == 'manuscript_pdf_delivery'
    assert physics_review.ID.fullmatch(mb.SCOPE)
    assert physics_review.validate_policy(review['policy']) == []
    spec = {'schema_version': 2, 'max_attempts': 1, 'review_policy': review}
    mb.validate_scope(spec)
    assert review['policy']['claim_scopes'] == {
        mb.SCOPE: {'checks': ['integrity'], 'actions': ['delivery']}}
    assert config['max_seconds'] == 30 and goal['assignment_id'] == 'publication-build'
    assert calls == []


@pytest.mark.parametrize('malformed', [
    'Source-bound portable manuscript PDF rendering and page census only',
    'manuscript pdf delivery', 'manuscript/pdf/delivery', 'x' * 101])
def test_malformed_scope_identifiers_remain_refused(tmp_path, monkeypatch, malformed):
    _, _, review, calls = preparation_inputs(tmp_path, monkeypatch)
    policy = deepcopy(review['policy'])
    policy['claim_scopes'] = {malformed: policy['claim_scopes'][mb.SCOPE]}
    assert physics_review.validate_policy(policy) == ['claim scope needs distinct identifiers']
    assert calls == []


@pytest.mark.parametrize('member', ['checks', 'actions'])
def test_duplicate_declared_scope_members_remain_refused(tmp_path, monkeypatch, member):
    _, _, review, calls = preparation_inputs(tmp_path, monkeypatch)
    policy = deepcopy(review['policy'])
    scope = policy['claim_scopes'][mb.SCOPE]
    scope[member] = scope[member] + scope[member]
    errors = physics_review.validate_policy(policy)
    assert len(errors) == 1 and 'distinct identifiers' in errors[0]
    assert calls == []


def test_other_valid_identifier_cannot_relabel_delivery_as_science(tmp_path, monkeypatch):
    _, _, review, calls = preparation_inputs(tmp_path, monkeypatch)
    policy = deepcopy(review['policy'])
    policy['claim_scopes'] = {'manuscript_scientific_inference': policy['claim_scopes'][mb.SCOPE]}
    assert physics_review.validate_policy(policy) == []
    with pytest.raises(ValueError, match='exact one-attempt delivery-only'):
        mb.validate_scope({'schema_version': 2, 'max_attempts': 1,
            'review_policy': {'policy': policy}})
    assert calls == []
