"""The operator's configured R3 delegation of the final task (N1: CHECK-IN 3 with no human prompt).

By default an R3 final-task action waits for renewed attested operator authority. An operator who configures
``r3_delegation: [final_task]`` (with ``final`` among the machine check-ins) lets the machine accept that exact
action in autonomous mode; the record keeps the machine label and names the delegation, the R3 class, the exact
action digest and the frozen mode. Nothing else at R3 is delegated, a child cannot widen the delegation, and a
record of another action, a lower class or another mode never passes.
"""
from copy import deepcopy
import sys

import pytest

from test_p06_support import autonomous, operator_home, view  # noqa: F401
from test_rdj_approval import Approval, DERIVE
from ravel.controller.authority import AuthorityRefused, common, freeze_mode, mode, request, service
from ravel.controller.authority import operator
from ravel.controller.authority import rdj as authority_rdj
from ravel.workflow import rdj_loop


def _case(tmp_path, monkeypatch, **configuration):
    fixture = Approval(tmp_path, monkeypatch)
    monkeypatch.setattr(type(fixture.store), 'run_dir', property(lambda _: fixture.root))
    fixture.run.stage('cost', 'inputs/cost_preflight.json', {'points': 1, 'walltime_h': [0.1, 0.2]},
                      command=[sys.executable, '-m', 'ravel.workflow.cost_preflight'])
    autonomous(**configuration)
    freeze_mode(fixture.store, {'prompt': 'Derive the fictional quantity.'})
    fixture.plan_doc = fixture.plan([DERIVE])
    fixture.review(fixture.plan_doc)
    plan_pins = fixture.action(fixture.plan_doc['sha256'])['view_pins']
    approval = request(fixture.store, 'approve_plan', {'view': view(fixture.store, 'approve_plan', **plan_pins)}, {})
    assert approval['label'] == common.MACHINE
    fixture.final_pins = {**plan_pins, 'approve_plan': approval['id']}
    fixture.exact_action = authority_rdj.final_action(fixture.final_pins)
    fixture.subject = {'view': view(fixture.store, 'final', **fixture.final_pins)}
    assert authority_rdj.classification(fixture.store, fixture.final_pins, 'final_task')[0] == 'R3'
    return fixture


def _decide(case):
    return case.review(case.plan_doc, 'rdj-critic', subject=case.exact_action['digest'], step_id='final-task-rdj-case')


def test_by_default_an_R3_final_task_waits_for_attested_operator_authority(tmp_path, monkeypatch, operator_home):
    case = _case(tmp_path, monkeypatch)
    held = request(case.store, 'final', case.subject, {})
    assert 'pending' in held and 'final-task action requires renewed attested operator authority' in \
        held['pending']['reason']


def test_the_configured_delegation_accepts_the_exact_action_with_the_machine_label(tmp_path, monkeypatch,
                                                                                   operator_home):
    case = _case(tmp_path, monkeypatch, r3_delegation=['final_task'])
    _decide(case)
    record = request(case.store, 'final', case.subject, {})
    assert 'pending' not in record, record
    frozen = mode.frozen(case.store)
    assert record['label'] == common.MACHINE and record['decision'] == 'accept'
    assert record['human_identity_authenticated'] is False
    assert record['evidence']['r3_delegation'] == 'final_task'
    assert record['evidence']['final_task_class'] == 'R3'
    assert record['evidence']['final_task_digest'] == case.exact_action['digest']
    assert record['evidence']['mode_record'] == frozen['id'] == record['mode_record']
    assert service.disposition(case.store, record['id'], kind='final', subject=case.final_pins)['id'] == record['id']
    assert rdj_loop.gate_errors(case.root, 'final_task', case.exact_action) == []
    evidence = rdj_loop.gate_evidence(case.root, 'final_task', case.exact_action)
    assert evidence['action_case']['authority_label'] == common.MACHINE


def test_the_delegation_needs_final_among_the_machine_checkins(tmp_path, monkeypatch, operator_home):
    case = _case(tmp_path, monkeypatch, r3_delegation=['final_task'],
                 machine_checkins=['approve_plan', 'go', 'deviation'])
    held = request(case.store, 'final', case.subject, {})
    assert 'pending' in held and 'keeps final for a human' in held['pending']['reason']


def test_other_R3_decisions_still_escalate_under_the_delegation(tmp_path, monkeypatch, operator_home):
    case = _case(tmp_path, monkeypatch, r3_delegation=['final_task'])
    subject = {'view': view(case.store, 'r3_action', action_sha256='f' * 64), 'gate': 'unblind'}
    held = request(case.store, 'r3_action', subject, {})
    assert 'pending' in held and 'R3 decision' in held['pending']['reason']


def test_a_child_cannot_widen_the_delegation(operator_home):
    parent = {'mode': 'autonomous', 'delegation': 'operator_configured', 'budgets': deepcopy(operator.DEFAULT_BUDGETS),
              'bounds': deepcopy(operator.DEFAULT_BOUNDS), 'machine_checkins': list(operator.MACHINE_CHECKINS),
              'r3_policy': 'escalate_and_wait', 'wait_bound_seconds': 60, 'notify_command': None,
              'allow_unconfined': False, 'r3_delegation': []}
    with pytest.raises(AuthorityRefused, match='R3 decisions beyond its parent'):
        mode.narrow(parent, {'r3_delegation': ['final_task']})
    assert mode.narrow(parent)['r3_delegation'] == []
    delegated = {**parent, 'r3_delegation': ['final_task']}
    assert mode.narrow(delegated)['r3_delegation'] == ['final_task']
    assert mode.narrow(delegated, {'r3_delegation': []})['r3_delegation'] == []
    with pytest.raises(ValueError):
        operator.init(mode='autonomous', r3_delegation=['approve_plan'])  # a closed vocabulary


def test_a_reused_or_mismatched_machine_record_is_refused(tmp_path, monkeypatch, operator_home):
    case = _case(tmp_path, monkeypatch, r3_delegation=['final_task'])
    _decide(case)
    record = request(case.store, 'final', case.subject, {})
    assert service.delegated_final(case.store, record)
    # Another action (a changed pin) never reuses the record.
    changed = {**case.final_pins, 'reading_sha256': 'f' * 64}
    with pytest.raises(AuthorityRefused):
        service.disposition(case.store, record['id'], kind='final', subject=changed)
    assert not service.delegated_final(case.store, {**record, 'subject': {**record['subject'], 'pins': changed}})
    # A forged digest, a lower class, another mode or a missing delegation name never passes.
    for evidence in ({'final_task_digest': '0' * 64}, {'final_task_class': 'R2'}, {'mode_record': 'mode-other'},
                     {'r3_delegation': None}):
        assert not service.delegated_final(case.store, {**record, 'evidence': {**record['evidence'], **evidence}})
    prepared = deepcopy(service._prepare(case.store, 'final', case.subject, {}))
    forged = service._record(case.store, 'final', prepared, mode.frozen(case.store), decision='accept',
                             label=common.MACHINE, source='operator_ledger',
                             evidence={'mode_record': mode.frozen(case.store)['id'], 'r3_delegation': 'final_task'})
    forged_evidence = {**forged['evidence'], 'final_task_digest': '1' * 64}
    assert not service.delegated_final(case.store, {**forged, 'evidence': forged_evidence})
