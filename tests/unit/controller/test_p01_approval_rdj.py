"""Consequential approval actions need observed critic credit and separate attested authority."""
import re
import sys

import pytest

from test_p06_support import autonomous, operator_home, view  # noqa: F401
from test_rdj_approval import Approval, DERIVE
from ravel.controller.authority import common, freeze_mode, request, answer, verify, AuthorityRefused
from ravel.controller.authority import rdj as approval_rdj
from ravel.workflow import rdj_loop


@pytest.fixture
def case(tmp_path, monkeypatch, operator_home):
    fixture = Approval(tmp_path, monkeypatch)
    # The existing observed-review fixture models the ownership index, not a bound run journal.
    monkeypatch.setattr(type(fixture.store), 'run_dir', property(lambda _: fixture.root))
    fixture.run.stage('cost', 'inputs/cost_preflight.json', {'points': 50, 'walltime_h': [0.1, 0.2]},
                      command=[sys.executable, '-m', 'ravel.workflow.cost_preflight'])
    autonomous()
    freeze_mode(fixture.store, {'prompt': 'Derive the fictional quantity.'})
    fixture.plan_doc = fixture.plan([DERIVE])
    fixture.review(fixture.plan_doc)
    fixture.exact_action = fixture.action(fixture.plan_doc['sha256'])
    fixture.subject = {'view': view(fixture.store, 'approve_plan', **fixture.exact_action['view_pins'])}
    assert approval_rdj.classification(fixture.store, fixture.exact_action['view_pins'])[0] == 'R3'
    return fixture


def attest(case, capfd):
    held = request(case.store, 'approve_plan', case.subject, {})
    assert 'R3' in held['pending']['reason'], held
    code = re.findall(r'--code (\S+)', capfd.readouterr().err)[-1]
    record = answer(case.store, held['pending']['request'], code, 'approve')
    assert record['label'] == common.OPERATOR_COMMAND
    assert verify(case.store, record['id'], kind='approve_plan')['id'] == record['id']
    return record


def decide(case, **options):
    return case.review(case.plan_doc, options.pop('role', 'rdj-critic'),
                       subject=options.pop('subject', case.exact_action['digest']),
                       step_id='authority-rdj-case', **options)


def gate(case):
    return rdj_loop.gate_errors(case.root, 'approve_plan', case.exact_action)


@pytest.mark.parametrize('session_role', [None, 'rdj_critic'])
def test_observed_exact_action_critic_and_attested_authority_pass(case, capfd, session_role):
    credit = decide(case, session_role=session_role)
    authority = attest(case, capfd)
    assert gate(case) == []
    evidence = rdj_loop.gate_evidence(case.root, 'approve_plan', case.exact_action)
    assert evidence['action_case']['credit'] == credit
    assert evidence['action_case']['authority'] == authority['id']
    assert evidence['action_case']['subject_sha256'] == case.exact_action['digest']
    assert evidence['action_case']['class'] == 'R3'


@pytest.mark.parametrize('options, expected', [
    ({'observed': False}, 'unobserved'),
    ({'session_role': 'plan-critic'}, 'uncredited'),
    ({'role': 'skeptical-verifier'}, 'not by an RDJ role'),
    ({'role': 'rdj-verifier'}, 'not decided by the RDJ critic'),
    ({'subject': 'f' * 64}, 'no RDJ case'),
    ({'verdict': 'revise'}, 'revise'),
    ({'credited': False}, 'uncredited'),
])
def test_invalid_action_case_refuses_despite_attested_authority(case, capfd, options, expected):
    decide(case, **options)
    attest(case, capfd)
    errors = gate(case)
    assert errors and all(e.provider == 'rdj' for e in errors), errors
    message = ' '.join(e.message for e in errors)
    if expected == 'unobserved':
        assert 'uncredited' in message or 'observed' in message, message
    else:
        assert expected in message, message
    assert rdj_loop.gate_evidence(case.root, 'approve_plan', case.exact_action) is None


def test_observed_case_without_r3_authority_refuses(case):
    decide(case)
    assert 'attested operator authority' in ' '.join(e.message for e in gate(case))
    assert rdj_loop.gate_evidence(case.root, 'approve_plan', case.exact_action) is None


def test_later_revise_supersedes_accept(case, capfd):
    decide(case)
    attest(case, capfd)
    assert gate(case) == []
    decide(case, verdict='revise', n=2)
    assert 'revise' in ' '.join(e.message for e in gate(case))


def test_machine_approval_is_not_r3_authority(case):
    from ravel.controller.authority import mode, service
    decide(case)
    prepared = service._prepare(case.store, 'approve_plan', case.subject, {})
    # A genuinely issuer-sealed machine record still cannot meet the R3 authority requirement.
    record = service._record(case.store, 'approve_plan', prepared, mode.frozen(case.store),
                             decision='approve', label=common.MACHINE, source='operator_ledger', evidence={})
    with pytest.raises(AuthorityRefused, match='attested operator authority'):
        verify(case.store, record['id'], kind='approve_plan')
    assert gate(case)


@pytest.mark.parametrize('prior_operator', [False, True])
def test_class_rise_renews_authority_even_when_view_pins_are_unchanged(case, capfd, prior_operator):
    from ravel.controller.authority import service, mode
    case.run.stage('cost', 'inputs/cost_preflight.json', {'points': 1, 'walltime_h': [0.1, 0.2]},
                   command=[sys.executable, '-m', 'ravel.workflow.cost_preflight'])
    if prior_operator:
        prepared = service._prepare(case.store, 'approve_plan', case.subject, {})
        old = service._record(case.store, 'approve_plan', prepared, mode.frozen(case.store),
                              decision='approve', label=common.OPERATOR_COMMAND, source='operator_cli', evidence={})
    else:
        old = request(case.store, 'approve_plan', case.subject, {})
    assert old['evidence']['approval_class'] == 'R2'
    case.run.stage('cost', 'inputs/cost_preflight.json', {'points': 50, 'walltime_h': [0.1, 0.2]},
                   command=[sys.executable, '-m', 'ravel.workflow.cost_preflight'])
    decide(case)
    with pytest.raises(AuthorityRefused, match='attested'):
        verify(case.store, old['id'], kind='approve_plan')
    assert gate(case)
    renewed = attest(case, capfd)
    assert renewed['subject_sha256'] != old['subject_sha256']
    assert renewed['evidence']['approval_class'] == 'R3'
    assert gate(case) == []


def test_irreversible_approval_keeps_its_additional_human_requirement(case, capfd):
    decide(case)
    attest(case, capfd)
    # This raising-only fact cannot turn operator uid attestation into proof of human identity.
    action = {**case.exact_action, 'facts': {'irreversible': True}}
    errors = rdj_loop.gate_errors(case.root, 'approve_plan', action)
    assert errors and 'recorded human approval' in ' '.join(e.message for e in errors)
