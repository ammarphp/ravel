"""What a final record must satisfy before adoption (M10, M11, M13, CF01, CF06, I07, I09)."""
from __future__ import annotations

import hashlib
import json
import sys

import pytest

from ravel.controller.step import evidence, validate
from ravel.controller.step.services import StepHold
from ravel.controller import instructions as REAL_INSTRUCTIONS
from ravel.workflow import review_projection_checks, role_registry, run_validator_checks

from test_p04_support import install, output_schema, task_contract, FakeLedger, FakeInstructions, FakeAuthority, \
    FakeConfine, FakeIndependence  # noqa: F401

CARD = role_registry.load('baseline-producer')


def _escalation(*rows):
    return {'escalation': list(rows)}


def test_CF01_the_escalation_field_is_required_and_each_value_must_be_the_cards():
    assert validate.escalation({}, CARD) == ([], [{'code': 'escalation_field_missing'}])
    assert validate.escalation(_escalation(), CARD) == ([], [])
    found, errors = validate.escalation(_escalation({'kind': 'stop', 'statement': 'halt', 'evidence': ['x']},
                                                    {'kind': 'checkin_flag', 'statement': 'flag', 'evidence': []}), CARD)
    assert errors == [] and [f['kind'] for f in found] == ['stop', 'checkin_flag']
    assert validate.primary(found) == 'stop'
    assert validate.escalation({'escalation': 'decision_block'}, CARD)[0][0]['kind'] == 'decision_block'
    assert validate.escalation({'escalation': None}, CARD) == ([], [])
    assert validate.escalation(_escalation({'kind': 'invent'}), CARD)[1] == [{'code': 'escalation_invalid',
                                                                            'value': 'invent'}]
    narrow = {**CARD, 'escalation': ['stop']}
    assert validate.escalation(_escalation({'kind': 'checkin_flag', 'statement': 's', 'evidence': []}), narrow)[1] == [
        {'code': 'escalation_not_declared', 'value': 'checkin_flag', 'declared': ['stop']}]


@pytest.mark.parametrize('kinds, expected', [(['checkin_flag'], 'checkin_flag'),
                                              (['checkin_flag', 'new_experiment_required'], 'new_experiment_required'),
                                              (['new_experiment_required', 'decision_block'], 'decision_block'),
                                              (['decision_block', 'stop'], 'stop'), ([], None)])
def test_the_outcome_reports_the_most_consequential_escalation(kinds, expected):
    assert validate.primary([{'kind': k} for k in kinds]) == expected


def test_M13_blocked_checklist_rows_hold_and_every_other_fault_fails():
    holding, failing = validate.split_ack(['blocked: u1: input absent', 'missing: u2: no row', 'manifest: other'])
    assert holding == ['blocked: u1: input absent'] and failing == ['missing: u2: no row', 'manifest: other']


def test_acknowledgement_reads_the_observed_completion_and_retained_output_bytes(tmp_path, monkeypatch):
    from ravel.controller.store import RunStore
    monkeypatch.setitem(sys.modules, 'ravel.controller.instructions', REAL_INSTRUCTIONS)
    store = RunStore('run-acknowledgement', root=tmp_path / 'protected')
    step = {'id': 's1', 'kind': 'author', 'role': CARD['id']}
    manifest = REAL_INSTRUCTIONS.manifest(step, CARD)
    packet = REAL_INSTRUCTIONS.packet(manifest, CARD, step, [])
    binding = {'run_id': store.run_id, 'step': step['id'], 'attempt': 1,
               'manifest_sha256': manifest['sha256'], 'packet_sha256': packet['sha256']}
    session = store.append('worker-session', {**binding, 'packet': packet, 'step_spec': step,
                                               'card': CARD, 'inputs': [], 'session_id': 'observed-session'})
    store.append('step-attempt', {**binding, 'session': session})
    target = store.path('instruction-artifacts', session, 'outputs', 'value.json')
    target.parent.mkdir(parents=True)
    target.write_bytes(b'{"value": 1}')
    final = {'kind': 'result', 'instruction_ack': {'manifest_sha256': manifest['sha256']},
             'checklist': [{'unit': u['id'], 'status': 'done', 'evidence': 'outputs/value.json#/value', 'note': None}
                           for u in manifest['units'] if u['kind'] == 'duty']}
    completion = store.append('worker-completion', {**binding, 'session': session, 'final_record': final,
        'artifacts': [{'path': 'outputs/value.json', 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}]})
    args = {'store': store, 'session': session, 'completion_id': completion}
    assert validate.ack_errors(manifest, final, ['outputs/value.json'], **args) == []
    assert validate.ack_errors(manifest, final, ['outputs/value.json'], store=store, session=None)
    assert any(e.startswith('manifest:') for e in validate.ack_errors(
        manifest, {**final, 'kind': 'changed'}, ['outputs/value.json'], **args))
    target.write_bytes(b'{"value": 2}')
    assert any('bytes changed' in e for e in validate.ack_errors(manifest, final, ['outputs/value.json'], **args))


def test_CF06_a_record_valid_for_the_legacy_schema_but_not_the_cards_controller_schema_is_refused(monkeypatch):
    install(monkeypatch, {'ledger': FakeLedger(), 'instructions': FakeInstructions(), 'authority': FakeAuthority(),
                          'confine': FakeConfine(), 'independence': FakeIndependence()})
    legacy = {'schema_version': 1, 'kind': 'producer-result', 'outputs': [{'path': 'outputs/a', 'kind': 'k'}],
              'decisions': [], 'knowledge_used': [], 'handoff': None}
    assert role_registry.validate_output('producer.v1', legacy) == []
    errors = validate.card_schema_errors(CARD, legacy, 'producer.v2')
    assert errors and any('instruction_ack' in e or 'schema_version' in e for e in errors)
    current = {**legacy, 'schema_version': 2, 'instruction_ack': {'manifest_sha256': '0' * 64}, 'checklist': [],
               'escalation': []}
    assert validate.card_schema_errors(CARD, current, 'producer.v2') == []


def test_the_packet_schema_is_inline_or_a_registered_id():
    schema = output_schema('producer')
    assert validate.schema_document({'schema': schema}) == schema
    with pytest.raises(StepHold) as missing:
        validate.schema_document({})
    assert missing.value.reason == 'output_schema_unavailable'


def test_I09_a_producer_owes_the_union_of_its_reviewers_self_checks():
    card = role_registry.load('analysis-author')
    runnable, reviewer_only = validate.validator_ids(card)
    owed = role_registry.self_checks('analysis-author')
    assert set(owed) <= set(runnable) | set(reviewer_only)
    assert run_validator_checks.TRAP_CHECK in runnable   # a reviewer's trap reference resolves to the full sweep


def test_M10_the_controller_runs_the_cards_validators_itself_and_a_defect_fails(tmp_path):
    run = tmp_path / 'run'
    (run / 'inputs').mkdir(parents=True)
    report = validate.run_validators(CARD, {'id': 's1'}, run_dir=run, scratch=tmp_path / 'scratch')
    assert [r['check_id'] for r in report['results']] == ['check:validation.validate_task_contract.validate']
    assert report['passed'] is False   # no contract: the validator fails, it is never skipped
    task_contract(run)
    report = validate.run_validators(CARD, {'id': 's1'}, run_dir=run, scratch=tmp_path / 'scratch')
    assert report['passed'] is True and report['results'][0]['status'] == 'passed'
    broken = json.loads((run / 'inputs/task_contract.json').read_text())
    broken['task_mode'] = 'not-a-mode'
    (run / 'inputs/task_contract.json').write_text(json.dumps(broken))
    assert validate.run_validators(CARD, {'id': 's1'}, run_dir=run, scratch=tmp_path / 'scratch')['passed'] is False


def test_M10_a_document_check_without_its_named_document_is_inconclusive_never_passed(tmp_path):
    card = {**CARD, 'must_check': ['review.rubric'], 'independence': {**CARD['independence'], 'kind': 'specialist'},
            'family': 'specialist-review'}
    report = validate.run_validators(card, {'id': 's1'}, run_dir=tmp_path, scratch=tmp_path / 'scratch')
    assert report['results'] == [{'check_id': 'review.rubric', 'status': 'inconclusive',
                                  'reason': 'validator_input_missing'}]
    assert report['passed'] is False


def test_M10_a_reviewers_check_without_a_subject_fails_unless_the_review_policy_classifies_it_not_applicable(tmp_path):
    from ravel.controller.step import graph as step_graph
    card = role_registry.load('normalization-auditor')
    checks = ('check:physics.normalization_ledger.check', 'check:validation.input_closure.check')
    report = validate.run_validators(card, {'id': 'r1'}, run_dir=tmp_path, scratch=tmp_path / 'scratch', subjects={})
    assert [(r['check_id'], r['status'], r['reason']) for r in report['results']] == [
        (c, 'inconclusive', 'no_subject') for c in checks] and report['passed'] is False
    rows = step_graph.must_check_rows(card, report['results'], 'step-validation-000001-x')
    assert {k: v['status'] for k, v in rows.items()} == {'ROLE-normalization-auditor-must_check-0': 'violated',
                                                          'ROLE-normalization-auditor-must_check-1': 'violated'}
    cited = {'record': 'review-classification-000001-x', 'rows': [5], 'points': []}
    report = validate.run_validators(card, {'id': 'r1'}, run_dir=tmp_path, scratch=tmp_path / 'scratch', subjects={},
                                     exempt={checks[0]: cited})
    found = {r['check_id']: r for r in report['results']}
    assert found[checks[0]]['status'] == 'not_applicable' and found[checks[0]]['classification'] == cited
    assert found[checks[0]]['reason'] == 'policy_not_applicable' and found[checks[1]]['status'] == 'inconclusive'
    assert report['passed'] is False
    rows = step_graph.must_check_rows(card, report['results'], 'step-validation-000002-x')
    exempted = rows['ROLE-normalization-auditor-must_check-0']
    assert exempted['status'] == 'not_applicable' and exempted['evidence']['classification'] == cited
    assert exempted['evidence']['reason'] == 'not_applicable:policy_not_applicable'


RUNNABLE = sorted({check for card in role_registry.all_cards() for check in validate.validator_ids(card)[0]})


def _plant(run, check_id):
    """A planted defect: missing evidence, or for the deviation ledger an adjustment without its ledger."""
    if check_id == 'check:validation.verify_pack.check_deviations_ledger':
        (run / 'outputs').mkdir(parents=True, exist_ok=True)
        (run / 'outputs/adjusted.json').write_text(json.dumps({'deviations': [{'what': 'a mid-run adjustment'}]}))


@pytest.mark.parametrize('check_id', RUNNABLE)
def test_M10_each_runnable_validator_refuses_a_planted_defect(tmp_path, check_id):
    card = {**CARD, 'must_check': [check_id], 'reviewed_by': [], 'independence': {**CARD['independence'],
                                                                                 'kind': 'specialist'},
            'family': 'specialist-review'}
    _plant(tmp_path, check_id)
    report = validate.run_validators(card, {'id': 's1'}, run_dir=tmp_path, scratch=tmp_path / 'scratch')
    assert [r['check_id'] for r in report['results']] == [check_id]
    assert report['passed'] is False and report['results'][0]['status'] in ('failed', 'inconclusive')


def test_I07_a_knowledge_id_claimed_without_a_query_that_reached_it_is_labelled():
    rows = [{'action': 'knowledge query', 'status': 'ok', 'knowledge': ['handbook:a']},
            {'action': 'write', 'status': 'ok', 'knowledge': None}]
    labels = evidence.knowledge_labels({'knowledge_used': ['handbook:a', 'handbook:b']}, rows)
    assert labels == [{'label': 'knowledge_use_unsupported', 'id': 'handbook:b', 'queried': True}]
    assert evidence.knowledge_labels({'knowledge_used': []}, rows) == []
    assert evidence.knowledge_labels({'knowledge_used': ['handbook:a']}, []) == [
        {'label': 'knowledge_use_unsupported', 'id': 'handbook:a', 'queried': False}]


def test_the_reviewer_verdict_is_derived_from_item_verdicts_and_blocking_findings():
    from ravel.controller.step.graph import _verdict
    items = [{'id': 'i1'}, {'id': 'i2'}]
    passed = {'item_verdicts': [{'item': 'i1', 'verdict': 'pass'}, {'item': 'i2', 'verdict': 'pass'}], 'items': []}
    assert _verdict(passed, items) == 'accept'
    assert _verdict({**passed, 'items': [{'severity': 'A'}]}, items) == 'revise'
    assert _verdict({'item_verdicts': [{'item': 'i1', 'verdict': 'fail'}], 'items': []}, items) == 'revise'
    assert _verdict({'item_verdicts': [{'item': 'i1', 'verdict': 'pass'}], 'items': []}, items) == 'unresolved'
    assert _verdict(None, items) == 'unresolved'


def test_a_reviewer_item_the_review_package_marks_is_owed_as_a_verdict_never_run(monkeypatch):
    card = {**CARD, 'must_check': ['check:validation.validate_task_contract.validate', 'review.rubric']}
    assert 'review.rubric' in validate.validator_ids(card)[0]
    monkeypatch.setattr(review_projection_checks, 'computes', lambda check: check != 'review.rubric', raising=False)
    runnable, reviewer_only = validate.validator_ids(card)
    assert 'review.rubric' in reviewer_only and 'review.rubric' not in runnable
    assert 'check:validation.validate_task_contract.validate' in runnable


@pytest.mark.parametrize('change', ['unchanged', 'changed', 'outside', 'symlink'])
def test_bound_document_checks_require_the_accepted_bytes(tmp_path, monkeypatch, change):
    from ravel.workflow import review_projection_checks
    invoked = []
    original = review_projection_checks.run_check
    def checked(check, document):
        invoked.append((check, document))
        return original(check, document)
    monkeypatch.setattr(review_projection_checks, 'run_check', checked)
    from hashlib import sha256
    run = tmp_path / 'run'; run.mkdir()
    target = run / 'report.json'
    raw = json.dumps({'figure_spec': {'x_scale': 'linear', 'y_scale': 'linear',
                     'x_range': [0, 1], 'y_range': [0, 1],
                     'x_label': 'fraction', 'y_label': 'acceptance'}}).encode()
    target.write_bytes(raw)
    pin = {'path': 'report.json', 'sha256': sha256(raw).hexdigest()}
    if change == 'changed':
        target.write_bytes(raw + b' ')
    elif change in ('outside', 'symlink'):
        outside = tmp_path / 'external.json'; outside.write_bytes(raw)
        if change == 'outside':
            pin['path'] = str(outside)
        else:
            target.unlink(); target.symlink_to(outside)
    check = 'check:validation.plot_lint'
    result, executed = validate._run_check(check, {check: {'document': pin}},
                                           run_dir=run, scratch=tmp_path / 'scratch')
    assert executed is (change == 'unchanged')
    assert result['status'] == ('passed' if change == 'unchanged' else 'inconclusive')
    assert len(invoked) == (1 if change == 'unchanged' else 0)


@pytest.mark.parametrize('subject,expected', [
    ('valid', 'passed'), ('missing', 'inconclusive'), ('malformed', 'failed'), ('unfulfilled', 'failed')])
def test_declared_figure_contract_uses_its_custody_path(tmp_path, subject, expected):
    from ravel.controller.step import validate
    check = 'check:validation.validate_run_state.check_figure_contract'
    run = tmp_path / 'run'
    (run / 'inputs').mkdir(parents=True)
    (run / 'inputs/task_contract.json').write_text(json.dumps({'task_mode': 'reproduce'}))
    # The canonical file is a decoy: the declared current source decides the check.
    (run / 'inputs/figure_target.json').write_text(json.dumps({'targets': [{'figure_id': 'decoy'}]}))
    target = 'steps/prepare/outputs/figure_target.json'
    path = run / target
    path.parent.mkdir(parents=True)
    if subject != 'missing':
        path.write_text('{bad' if subject == 'malformed' else json.dumps({'targets': [{'figure_id': 'F1'}]}))
    if subject == 'unfulfilled':
        (run / 'outputs').mkdir()
        (run / 'outputs/sr_yields_actual.json').write_text('{}')
    row, executed = validate._run_check(check, {check: {'target': target}},
        run_dir=run, scratch=tmp_path / 'scratch', step={'id': 'review', 'depends_on': []})
    assert row['status'] == expected, row
    if subject == 'valid':
        assert executed is True
        assert json.loads(row['diagnostics'])['path'] == target
    elif subject != 'missing':
        assert executed is True


@pytest.mark.parametrize('malformed', [False, True])
def test_producer_runs_the_checks_of_its_explicit_review_seats(tmp_path, monkeypatch, malformed):
    from copy import deepcopy
    from ravel.controller.step import graph
    from p09_support import Store
    card = role_registry.load('analysis-author')
    original = deepcopy(card)
    check = 'check:validation.plot_lint'
    # This required seat adds checks beyond the role's default reviewing cards.
    assert check not in validate.validator_ids(card)[0]
    path = tmp_path / 'plot.json'
    path.write_text(json.dumps({'figure_spec': {
        'x_scale': 'linear', 'y_scale': 'linear',
        'x_range': [1, 0] if malformed else [0, 1], 'y_range': [0, 1],
        'x_label': 'fraction', 'y_label': 'acceptance'}}))
    step = {'id': 'derive', 'kind': 'derive', 'role': card['id'], 'review': ['figure-critic'],
            'depends_on': [], 'inputs': [], 'outputs': [],
            'parameters': {'check_inputs': {check: {'document': 'plot.json'}}}}
    pinned = role_registry.registry_sha256()
    state = {'step': step, 'acting': step, 'context': {},
             'card': {'id': card['id'], 'sha256': role_registry.card_sha256(card['id']),
                      'registry_sha256': pinned}}
    store = Store()
    monkeypatch.setattr(graph, '_store', lambda state: store)
    monkeypatch.setattr(graph, '_run_dir', lambda state: tmp_path)
    result = graph.checks(state)
    reports = [r['record']['report'] for r in store.scan('step-validation')]
    found = [r for r in reports[-1]['results'] if r['check_id'] == check]
    assert len(found) == 1, reports
    assert found[0]['status'] == ('failed' if malformed else 'passed'), found
    assert role_registry.load(card['id']) == original
    # The extra seat never suppresses the producer's own mandatory checks.
    assert set(validate.validator_ids(card)[0]) <= {r['check_id'] for r in reports[-1]['results']}
    assert result['checks']['passed'] is False  # other declared subjects are intentionally absent
