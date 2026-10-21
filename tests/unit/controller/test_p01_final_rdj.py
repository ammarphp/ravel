"""Final-task acceptance needs observed exact-action critic credit and renewed authority."""
from copy import deepcopy
import re
import sys

import pytest

from test_p06_support import autonomous, operator_home, view  # noqa: F401
from test_rdj_approval import Approval, DERIVE
from ravel.controller.authority import common, freeze_mode, request, answer, AuthorityRefused
from ravel.controller.authority import rdj as authority_rdj
from ravel.controller.authority import service, mode
from ravel.workflow import rdj_loop


@pytest.fixture
def case(tmp_path, monkeypatch, operator_home):
    fixture = Approval(tmp_path, monkeypatch)
    # Bind the real store to the run journal used by the observed-review fixture.
    monkeypatch.setattr(type(fixture.store), 'run_dir', property(lambda _: fixture.root))
    fixture.run.stage('cost', 'inputs/cost_preflight.json', {'points': 1, 'walltime_h': [0.1, 0.2]},
                      command=[sys.executable, '-m', 'ravel.workflow.cost_preflight'])
    autonomous()
    freeze_mode(fixture.store, {'prompt': 'Derive the fictional quantity.'})
    fixture.plan_doc = fixture.plan([DERIVE])
    fixture.review(fixture.plan_doc)
    plan_pins = fixture.action(fixture.plan_doc['sha256'])['view_pins']
    assert authority_rdj.classification(fixture.store, plan_pins)[0] == 'R2'
    approval = request(fixture.store, 'approve_plan', {'view': view(fixture.store, 'approve_plan', **plan_pins)}, {})
    assert approval['label'] == common.MACHINE
    fixture.final_pins = {**plan_pins, 'approve_plan': approval['id']}
    fixture.exact_action = authority_rdj.final_action(fixture.final_pins)
    fixture.subject = {'view': view(fixture.store, 'final', **fixture.final_pins)}
    assert authority_rdj.classification(fixture.store, fixture.final_pins, 'final_task')[0] == 'R3'
    return fixture


def attest(case, capfd):
    held = request(case.store, 'final', case.subject, {})
    assert 'pending' in held, held
    code = re.findall(r'--code (\S+)', capfd.readouterr().err)[-1]
    record = answer(case.store, held['pending']['request'], code, 'accept')
    assert record['label'] == common.OPERATOR_COMMAND
    assert record['evidence']['final_task_class'] == 'R3'
    assert record['evidence']['final_task_digest'] == case.exact_action['digest']
    assert service.disposition(case.store, record['id'], kind='final', subject=case.final_pins)['id'] == record['id']
    return record


def decide(case, **options):
    return case.review(case.plan_doc, options.pop('role', 'rdj-critic'),
                       subject=options.pop('subject', case.exact_action['digest']),
                       step_id='final-task-rdj-case', **options)


def gate(case, action=None):
    return rdj_loop.gate_errors(case.root, 'final_task', action or case.exact_action)


@pytest.mark.parametrize('session_role', [None, 'rdj_critic'])
def test_observed_exact_action_critic_and_renewed_final_authority_pass(case, capfd, session_role):
    credit = decide(case, session_role=session_role)
    authority = attest(case, capfd)
    assert gate(case) == []
    evidence = rdj_loop.gate_evidence(case.root, 'final_task', case.exact_action)
    assert evidence['mechanism'] == 'rdj_final_task.mapping'
    assert evidence['action_digest'] == case.exact_action['digest']
    assert evidence['action_case']['credit'] == credit
    assert evidence['action_case']['authority'] == authority['id']
    assert evidence['action_case']['subject_sha256'] == case.exact_action['digest']
    assert evidence['action_case']['class'] == 'R3'


@pytest.mark.parametrize('options, expected', [
    ({'observed': False}, 'unobserved'),
    ({'session_role': 'plan-critic'}, 'uncredited'),
    ({'role': 'rdj-verifier'}, 'not decided by the RDJ critic'),
    ({'role': 'skeptical-verifier'}, 'not by an RDJ role'),
    ({'subject': 'f' * 64}, 'no RDJ case'),
    ({'verdict': 'revise'}, 'revise'),
    ({'credited': False}, 'uncredited'),
])
def test_invalid_final_action_case_refuses_despite_authority(case, capfd, options, expected):
    decide(case, **options)
    attest(case, capfd)
    errors = gate(case)
    assert errors and all(e.provider == 'rdj' for e in errors), errors
    message = ' '.join(e.message for e in errors)
    if expected == 'unobserved':
        assert 'uncredited' in message or 'observed' in message, message
    else:
        assert expected in message, message
    assert rdj_loop.gate_evidence(case.root, 'final_task', case.exact_action) is None


def test_observed_final_case_without_final_authority_refuses(case):
    decide(case)
    assert 'attested operator authority' in ' '.join(e.message for e in gate(case))
    assert rdj_loop.gate_evidence(case.root, 'final_task', case.exact_action) is None


def test_later_revise_supersedes_accept(case, capfd):
    decide(case)
    attest(case, capfd)
    assert gate(case) == []
    decide(case, verdict='revise', n=2)
    assert 'revise' in ' '.join(e.message for e in gate(case))
    assert rdj_loop.gate_evidence(case.root, 'final_task', case.exact_action) is None


@pytest.mark.parametrize('recompute_digest', [False, True])
def test_final_pin_mutation_refuses(case, capfd, recompute_digest):
    decide(case)
    authority = attest(case, capfd)
    assert gate(case) == []
    changed = {**case.final_pins, 'reading_sha256': 'f' * 64}
    with pytest.raises(AuthorityRefused, match='pin reading_sha256 changed'):
        service.disposition(case.store, authority['id'], kind='final', subject=changed)
    action = authority_rdj.final_action(changed) if recompute_digest else {
        **case.exact_action, 'view_pins': changed}
    assert gate(case, action)
    assert rdj_loop.gate_evidence(case.root, 'final_task', action) is None


def test_issuer_sealed_operator_accept_without_final_evidence_needs_renewal(case, capfd):
    decide(case)
    prepared = deepcopy(service._prepare(case.store, 'final', case.subject, {}))
    # Model a genuine pre-final-task issuer record, rather than corrupting a sealed journal.
    for key in ('final_task_class', 'final_task_digest'):
        prepared['material'].pop(key)
    prepared['subject_sha256'] = common.digest(prepared['material'])
    old = service._record(case.store, 'final', prepared, mode.frozen(case.store),
                          decision='accept', label=common.OPERATOR_COMMAND, source='operator_cli', evidence={})
    assert 'final_task_class' not in old['evidence']
    assert 'final_task_digest' not in old['evidence']
    with pytest.raises(AuthorityRefused, match='renewed attested operator authority'):
        service.disposition(case.store, old['id'], kind='final', subject=case.final_pins)
    assert gate(case)
    assert rdj_loop.gate_evidence(case.root, 'final_task', case.exact_action) is None
    renewed = attest(case, capfd)
    assert renewed['id'] != old['id']
    assert renewed['subject_sha256'] != old['subject_sha256']
    assert gate(case) == []


def test_dispatch_uses_final_digest_and_never_duplicates_a_failed_or_revising_seat(case, monkeypatch):
    from ravel.controller.judgment import graph as judgment_graph
    dispatched, materials = [], []
    monkeypatch.setattr(judgment_graph, '_request', lambda state, store: {})
    monkeypatch.setattr(judgment_graph, '_inputs', lambda *args: {})
    monkeypatch.setattr(judgment_graph, '_base_inputs', lambda *args: [])

    def material(state, name, document):
        materials.append((name, document))
        return {'artifact': name, 'sha256': 'a' * 64}

    def run(store, state, request_, phase, steps):
        dispatched.extend(steps)
        store.append('step-outcome', {'step_id': steps[0]['id'], 'status': 'failed'})
        return {}

    monkeypatch.setattr(judgment_graph, '_context_file', material)
    monkeypatch.setattr(judgment_graph, '_run_planning_steps', run)
    authority_rdj.dispatch(case.store, {}, case.exact_action, {})
    authority_rdj.dispatch(case.store, {}, case.exact_action, {})
    assert len(dispatched) == len(materials) == 1
    assert dispatched[0]['id'] == 'authority-rdj-' + case.exact_action['digest'][:40]
    assert dispatched[0]['role'] == 'rdj-critic'
    assert materials[0][0] == 'final-task-action'
    assert materials[0][1]['action'] == case.exact_action
    assert materials[0][1]['approval_view']['pins'] == case.final_pins
    assert gate(case), 'dispatch or failed outcomes are not review credit'
