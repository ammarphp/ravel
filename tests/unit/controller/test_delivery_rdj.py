"""Delivery and report decisions use observed exact-action credit and renewed authority."""
import pytest

from test_p01_final_rdj import case, decide, attest  # noqa: F401
from test_p06_support import operator_home  # noqa: F401
from ravel.workflow import rdj_loop


@pytest.mark.parametrize('gate', ['delivery', 'report_integrity'])
def test_exact_final_review_and_renewed_authority_cover_delivery_decisions(case, capfd, gate):
    credit = decide(case)
    authority = attest(case, capfd)
    assert rdj_loop.compute_class(case.root, gate, case.exact_action)[0] == 'R3'
    assert rdj_loop.gate_errors(case.root, gate, case.exact_action) == []
    evidence = rdj_loop.gate_evidence(case.root, gate, case.exact_action)
    assert evidence['mechanism'] == f'rdj_{gate}.mapping'
    assert evidence['action_case']['credit'] == credit
    assert evidence['action_case']['authority'] == authority['id']


@pytest.mark.parametrize('gate', ['delivery', 'report_integrity'])
@pytest.mark.parametrize('options', [
    {'observed': False}, {'session_role': 'plan-critic'}, {'role': 'rdj-verifier'},
    {'subject': 'f' * 64}, {'verdict': 'revise'}, {'credited': False},
])
def test_unobserved_wrong_or_revising_review_refuses(case, capfd, gate, options):
    decide(case, **options)
    attest(case, capfd)
    assert rdj_loop.gate_errors(case.root, gate, case.exact_action)
    assert rdj_loop.gate_evidence(case.root, gate, case.exact_action) is None


@pytest.mark.parametrize('gate', ['delivery', 'report_integrity'])
def test_plan_authority_does_not_supply_final_authority(case, gate):
    decide(case)
    errors = rdj_loop.gate_errors(case.root, gate, case.exact_action)
    assert errors and 'renewed attested operator authority' in ' '.join(e.message for e in errors)
    assert rdj_loop.gate_evidence(case.root, gate, case.exact_action) is None


@pytest.mark.parametrize('gate', ['delivery', 'report_integrity'])
@pytest.mark.parametrize('mutation', ['kind', 'pins', 'digest'])
def test_changed_action_refuses(case, capfd, gate, mutation):
    decide(case)
    attest(case, capfd)
    action = dict(case.exact_action)
    if mutation == 'kind':
        action['kind'] = 'controller.approve_plan'
    elif mutation == 'pins':
        action['view_pins'] = {**action['view_pins'], 'reading_sha256': 'f' * 64}
    else:
        action['digest'] = 'f' * 64
    assert rdj_loop.gate_errors(case.root, gate, action)
    assert rdj_loop.gate_evidence(case.root, gate, action) is None


def test_sink_carries_the_reviewed_action_and_report_occurrence(tmp_path, monkeypatch):
    import sys
    from p07_support import Run
    from ravel.controller import sink
    run = Run(tmp_path, monkeypatch).complete()
    exact = {'kind': 'controller.final_task', 'digest': 'e' * 64, 'view_pins': {'plan_sha256': 'd' * 64}}
    monkeypatch.setattr(sys.modules['ravel.controller.authority'], 'final_task_action', lambda store: exact,
                        raising=False)
    sink.deliver(run.store, run.plan_doc)
    actions = {row[1]: row[2] for row in run.ledger.calls if row[0] == 'decide'}
    for gate in ('delivery', 'final_task', 'report_integrity'):
        assert actions[gate]['kind'] == exact['kind'] and actions[gate]['digest'] == exact['digest']
        assert actions[gate]['view_pins'] == exact['view_pins']
        assert 'outputs' in actions[gate] and 'descoped' in actions[gate]
    assert actions['report_integrity']['event'].startswith('report:')
