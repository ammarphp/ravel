"""Output facts govern producer checks; physical products retain every obligation."""
from copy import deepcopy
import hashlib
import json

import pytest

from ravel.controller.step import validate
from ravel.workflow import operation_check_policy as policy, review_points, role_registry


def step(kind=None):
    task = {'schema_version': 1, 'operation': 'run', 'snakefile': 'inputs/workflow',
            'targets': ['all'], 'cores': 1}
    if kind:
        task.update(outputs=['result.bin'], output_contract={'result.bin': kind})
    return {'id': 'compute', 'operation': 'external-workflow', 'parameters': {'task': task}}


def facts(root, plan):
    folder = root / 'inputs'
    folder.mkdir(parents=True)
    raw = json.dumps(plan).encode()
    (folder / 'request_plan.json').write_bytes(raw)
    (folder / 'task_contract.json').write_text(json.dumps({
        'agent_layer_epoch': 2, 'delegated': False,
        'request_plan': {'path': str(folder / 'request_plan.json'), 'sha256': hashlib.sha256(raw).hexdigest()}}))


def test_receipt_scope_records_typed_not_applicable_for_producer_inputs(tmp_path):
    facts(tmp_path, {'nodes': [], 'claims': [], 'edges': []})
    node = step()
    classified = review_points.check_classification(tmp_path, policy.CHECKS, step=node)['checks']
    assert set(classified) == policy.CHECKS
    assert all(row['applies'] is False and row['reason'] == 'no_declared_physical_outputs'
               and row['evidence']['products']['source'] == 'operation_signature.produces'
               for row in classified.values())
    card = role_registry.load('analysis-author')
    node['parameters']['check_inputs'] = {check: {'missing': {'source': 'output'}} for check in policy.CHECKS}
    report = validate.run_validators(card, node, run_dir=tmp_path, scratch=tmp_path / 'validation',
        owed=policy.CHECKS, exempt={check: {'record': 'protected-classification', **row}
                                   for check, row in classified.items()})
    results = {row['check_id']: row for row in report['results']}
    assert all(results[check]['status'] == 'not_applicable' for check in policy.CHECKS)
    assert not list(tmp_path.rglob('*ledger*')), 'classification creates no normalization ledger'


@pytest.mark.parametrize('kind', ['event_sample', 'binned_values', 'cutflow'])
def test_physical_workflow_outputs_retain_producer_checks(tmp_path, kind):
    facts(tmp_path, {'nodes': [], 'claims': [], 'edges': []})
    node = step(kind)
    classified = review_points.check_classification(tmp_path, policy.CHECKS, step=node)['checks']
    assert all(row['applies'] is True for row in classified.values())
    card = role_registry.load('analysis-author')
    assert policy.CHECKS <= set(validate.validator_ids(card)[0])
    report = validate.run_validators(card, node, run_dir=tmp_path, scratch=tmp_path / 'validation',
                                     owed=policy.CHECKS, exempt={})
    results = {row['check_id']: row for row in report['results']}
    assert all(results[check]['status'] not in ('passed', 'not_applicable') for check in policy.CHECKS)
    assert report['passed'] is False


def test_executor_follows_declared_products_and_unknown_operations_are_unchanged():
    from ravel.controller.step.operations import executor_errors
    assert policy.executor('external-workflow', step()['parameters']['task'], 'analysis-author') == 'calculation'
    assert policy.executor('external-workflow', step('event_sample')['parameters']['task'], 'calculation') == 'analysis-author'
    assert policy.executor('unregistered', {}, 'generator') == 'generator'
    for node, role in [(step(), 'calculation'), (step('event_sample'), 'analysis-author')]:
        assert executor_errors({**node, 'role': role}) == []
        assert executor_errors({**node, 'role': 'inference'})[0]['code'] == 'executor_role_mismatch'


def test_operation_disposition_cannot_remove_a_run_level_physics_obligation(tmp_path):
    facts(tmp_path, {'nodes': [], 'claims': [{'id': 'yield', 'absolute_yield': True}], 'edges': []})
    row = review_points.check_classification(tmp_path, [policy.NORMALIZATION], step=step())['checks'][policy.NORMALIZATION]
    assert row['applies'] is True and row['points']


def test_input_closure_is_disposed_only_for_a_card_that_owes_it_and_only_without_a_certified_value(tmp_path):
    facts(tmp_path, {'nodes': [], 'claims': [], 'edges': []})
    node = step()
    # A producer card that does not owe the check never gains it from the operation policy.
    assert policy.INPUT_CLOSURE not in policy.classify(node, list(policy.CHECKS))
    card = role_registry.load('calculation')
    assert policy.INPUT_CLOSURE in validate.validator_ids(card)[0]
    row = review_points.check_classification(tmp_path, [policy.INPUT_CLOSURE], step=node)['checks'][policy.INPUT_CLOSURE]
    assert row['applies'] is False and row['reason'] == 'no_declared_certified_value'
    assert row['evidence']['policy'] == 'declared_certified_values_require_input_closure'
    node['parameters']['check_inputs'] = {policy.INPUT_CLOSURE: {'fit': {'source': 'output'},
                                                                 'reference': {'source': 'output'}}}
    report = validate.run_validators(card, node, run_dir=tmp_path, scratch=tmp_path / 'validation',
                                     owed=[policy.INPUT_CLOSURE],
                                     exempt={policy.INPUT_CLOSURE: {'record': 'protected-classification', **row}})
    [result] = [r for r in report['results'] if r['check_id'] == policy.INPUT_CLOSURE]
    assert result['status'] == 'not_applicable' and result['reason'] == 'policy_not_applicable'


@pytest.mark.parametrize('kind', ['parameter_point', 'binned_values', 'event_sample'])
def test_a_declared_value_that_may_be_certified_keeps_input_closure(tmp_path, kind):
    facts(tmp_path, {'nodes': [], 'claims': [], 'edges': []})
    row = review_points.check_classification(tmp_path, [policy.INPUT_CLOSURE], step=step(kind))['checks'][policy.INPUT_CLOSURE]
    assert row['applies'] is True and row['reason'] == 'certified_or_unclassified_outputs'


def registered(operation):
    return {'id': 'render', 'kind': 'operate', 'operation': operation, 'parameters': {}}


def test_registered_documents_only_operation_owes_no_physical_checks(tmp_path):
    facts(tmp_path, {'nodes': [], 'claims': [], 'edges': []})
    node = registered('manuscript-note-sources')
    classified = review_points.check_classification(tmp_path, policy.CHECKS, step=node)['checks']
    assert set(classified) == policy.CHECKS
    for row in classified.values():
        assert row['applies'] is False and row['reason'] == 'no_declared_physical_outputs'
        assert row['evidence']['policy'] == 'registered_nonphysical_products_owe_no_physical_checks'
        assert row['evidence']['products']['source'] == 'operation_signature.produces'
        assert set(row['evidence']['products']['kinds']) == {'document'}
    report = validate.run_validators(role_registry.load('analysis-author'), node, run_dir=tmp_path,
        scratch=tmp_path / 'validation', owed=policy.CHECKS,
        exempt={check: {'record': 'protected-classification', **row} for check, row in classified.items()})
    assert {row['check_id']: row['status'] for row in report['results'] if row['check_id'] in policy.CHECKS} == \
        dict.fromkeys(policy.CHECKS, 'not_applicable')


def test_registered_physical_or_unknown_operation_keeps_its_checks(tmp_path):
    facts(tmp_path, {'nodes': [], 'claims': [], 'edges': []})
    for operation in ('published-classifier', 'unregistered-operation', None):
        node = registered(operation)
        assert policy.classify(node, policy.CHECKS) == {} and policy.dispositions(node, policy.CHECKS) == {}
        assert review_points.check_classification(tmp_path, policy.CHECKS, step=node) == \
            review_points.check_classification(tmp_path, policy.CHECKS)
    assert policy.registered_products('published-classifier')['kinds'] == ['table', 'binned_values']


def test_registered_dispositions_never_add_a_check_to_the_producer():
    """Only an adopted workflow's declared outputs add checks (``classify``); a registered operation's
    not-applicable rows only decide checks its producer already owes (``dispositions``)."""
    node = registered('manuscript-note-sources')
    assert policy.classify(node, policy.CHECKS) == {}
    assert set(policy.dispositions(node, policy.CHECKS)) == policy.CHECKS


def test_registered_products_never_change_the_executor_role():
    for operation in ('manuscript-note-sources', 'manuscript-note-pdf', 'published-classifier'):
        assert policy.executor(operation, {}, 'analysis-author') == 'analysis-author'


def test_a_run_level_obligation_survives_a_documents_only_operation(tmp_path):
    facts(tmp_path, {'nodes': [], 'claims': [{'id': 'yield', 'absolute_yield': True}], 'edges': []})
    row = review_points.check_classification(tmp_path, [policy.NORMALIZATION],
                                             step=registered('manuscript-note-pdf'))['checks'][policy.NORMALIZATION]
    assert row['applies'] is True and row['points']


def test_certificate_check_applies_only_to_certificate_relevant_claims(tmp_path, monkeypatch):
    certificate = review_points.CERTIFICATE_CHECK
    facts(tmp_path, {'nodes': [], 'claims': [], 'edges': []})
    row = review_points.certificate_classification(tmp_path)['checks'][certificate]
    assert row['applies'] is False and row['reason'] == 'no_certificate_relevant_claim'
    assert row['points'] == [] and row['evidence']['derived_points_sha256']
    derived = review_points.derive
    def with_relevant_claim(found):
        return derived(found) + [{'id': 'RP5:yield', 'row': 5, 'requires_certificate': True},
                                 {'id': 'RP5:other', 'row': 5, 'requires_certificate': False}]
    monkeypatch.setattr(review_points, 'derive', with_relevant_claim)
    row = review_points.certificate_classification(tmp_path)['checks'][certificate]
    assert row == {'applies': True, 'rows': [5], 'points': ['RP5:yield']}
    # The reviewer-check classification never decides the certificate check: no specialist reviewer owes it.
    assert certificate not in review_points.check_classification(tmp_path, [certificate, *policy.CHECKS])['checks']


@pytest.mark.parametrize('kinds, applies', [(['document'], False), (['document', 'figure'], False),
                                            (['document', 'table'], None), (['document', None], None), ([], None)])
def test_a_step_without_an_operation_is_decided_by_its_declared_output_kinds(tmp_path, kinds, applies):
    facts(tmp_path, {'nodes': [], 'claims': [], 'edges': []})
    node = {'id': 'decide', 'kind': 'author', 'parameters': {},  # an author step carries no operation key
            'outputs': [{'path': f'outputs/o{i}.json', 'kind': kind, 'required': True} for i, kind in enumerate(kinds)]}
    rows = policy.dispositions(node, policy.CHECKS)
    assert policy.classify(node, policy.CHECKS) == {}, 'output kinds never add a check'
    if applies is None:
        assert rows == {}
        return
    assert set(rows) == policy.CHECKS and all(row['applies'] is False for row in rows.values())
    evidence = next(iter(rows.values()))['evidence']
    assert evidence['policy'] == 'declared_nonphysical_outputs_owe_no_physical_checks'
    assert evidence['products']['source'] == 'step.outputs' and evidence['products']['kinds'] == kinds
    classified = review_points.check_classification(tmp_path, policy.CHECKS, step=node)['checks']
    assert all(classified[check]['applies'] is False for check in policy.CHECKS)


def certificate_step(root, monkeypatch, *, relevant, owner, supplied=False):
    from ravel.controller.step import custody, graph
    from ravel.workflow import review_independence
    from p09_support import Store

    plan = {'nodes': [], 'claims': [], 'edges': []}
    if relevant:
        plan.update(nodes=[{'id': 'selection', 'operation': 'columnar-analysis', 'rung': 'smoke',
                            'fields': [{'pointer': '/selection_origin', 'value': 'reimplemented'}]}],
                    claims=[{'id': 'value', 'kind': 'agreement', 'inherits': ['selection']}])
    facts(root, plan)
    certificate = review_points.CERTIFICATE_CHECK
    role = 'integrity-auditor' if owner else 'spec-author'
    card = role_registry.load(role)
    role = card['id']
    node = {'id': 'audit', 'kind': 'review' if owner else 'author', 'role': role,
            'review': [] if owner else ['integrity-auditor'], 'depends_on': [], 'inputs': [],
            'outputs': [{'path': 'outputs/report.json', 'kind': 'findings', 'required': True}],
            'parameters': {'check_inputs': {certificate: {}}, 'validator_exports': {'outputs/report.json': {}}}}
    for key, kind in [('kind', 'string'), ('path', 'path')]:
        field = '/validator_inputs/' + certificate + '/' + key
        node['parameters']['check_inputs'][certificate][key] = {
            'source': 'output', 'step': node['id'], 'path': 'outputs/report.json', 'field': field, 'type': kind}
        node['parameters']['validator_exports']['outputs/report.json'][field] = kind
    document = {'verdict': 'PASS', 'numbers': [], 'findings': []}
    if supplied:
        document['validator_inputs'] = {certificate: {'path': 'outputs/certificate.json', 'kind': 'r5'}}
        target = root / 'outputs/certificate.json'
        target.parent.mkdir(parents=True)
        target.write_text('{}')  # A supplied invalid certificate must still execute and fail.
    destination = custody.attempt_destination(node['id'], 'outputs/report.json', 1)
    target = root / destination
    target.parent.mkdir(parents=True)
    raw = json.dumps(document).encode()
    target.write_bytes(raw)
    adopted = {'schema_version': 1, 'artifact': 'audit:outputs/report.json', 'step_id': node['id'],
               'attempt': 1, 'path': 'outputs/report.json', 'destination': destination,
               'sha256': hashlib.sha256(raw).hexdigest(), 'status': 'staged'}
    store = Store()
    adopted['record_id'] = store.append('custody', adopted)
    controller_plan = {'steps': [node]}
    controller_plan['sha256'] = graph.digest(controller_plan)
    blob = store.put_blob(json.dumps(controller_plan).encode())
    store.append('plan', {'plan_sha256': controller_plan['sha256'], 'blob': blob})
    state = {'step': node, 'acting': node, 'context': {'plan_sha256': controller_plan['sha256']},
             'adoption': {'adopted': [adopted]},
             'card': {'id': role, 'sha256': role_registry.card_sha256(role),
                      'registry_sha256': role_registry.registry_sha256()}}
    monkeypatch.setattr(graph, '_store', lambda state: store)
    monkeypatch.setattr(graph, '_run_dir', lambda state: root)
    monkeypatch.setattr(review_independence, 'controller_store', lambda run: store)
    return graph, store, state


@pytest.mark.parametrize('owner', [False, True], ids=['reviewer-owed', 'own-card'])
@pytest.mark.parametrize('relevant', [False, True], ids=['no-relevant-claim', 'relevant-claim'])
def test_missing_certificate_input_uses_the_same_policy_for_own_and_review_checks(
        tmp_path, monkeypatch, owner, relevant):
    graph, store, state = certificate_step(tmp_path, monkeypatch, relevant=relevant, owner=owner)
    certificate = review_points.CERTIFICATE_CHECK
    classification = review_points.certificate_classification(tmp_path)
    assert classification['checks'][certificate]['applies'] is relevant
    result = graph.checks(state)
    row, = [r for r in result['checks']['results'] if r['check_id'] == certificate]
    if relevant:
        assert row['status'] == 'inconclusive' and row['reason'] == 'validator_source_unresolved'
        assert row['detail'] == 'field /validator_inputs/' + certificate + '/path is unavailable'
        assert 'classification' not in row and result['checks']['passed'] is False
        assert result['evaluations']['I09']['status'] == 'violated'
        assert not any(certificate in r['record']['checks'] for r in store.scan(graph.CLASSIFICATION))
    else:
        assert row['status'] == 'not_applicable' and row['reason'] == 'policy_not_applicable'
        cited = row['classification']
        assert cited == {'record': cited['record'], **classification['checks'][certificate]}
        recorded = store.read(graph.CLASSIFICATION, cited['record'])['record']
        assert recorded == {'schema_version': 1, 'card': state['card']['id'], **classification}
        assert cited['reason'] == 'no_certificate_relevant_claim'
        assert cited['evidence']['policy'] == 'certificates_are_owed_for_certificate_relevant_claims'
        if owner:
            assert result['checks']['passed'] is True
            assert result['evaluations']['I09']['status'] == 'satisfied'
            duty = result['evaluations']['ROLE-integrity-auditor-must_check-1']
            assert duty['status'] == 'not_applicable' and duty['evidence']['classification'] == cited


@pytest.mark.parametrize('owner', [False, True], ids=['reviewer-owed', 'own-card'])
def test_a_supplied_certificate_is_still_validated_without_relevant_claims(tmp_path, monkeypatch, owner):
    graph, store, state = certificate_step(tmp_path, monkeypatch, relevant=False, owner=owner, supplied=True)
    result = graph.checks(state)
    row, = [r for r in result['checks']['results'] if r['check_id'] == review_points.CERTIFICATE_CHECK]
    assert row['status'] == 'failed' and row['result_sha256']
    assert 'classification' not in row and result['checks']['passed'] is False
    assert not any(review_points.CERTIFICATE_CHECK in r['record']['checks']
                   for r in store.scan(graph.CLASSIFICATION))


@pytest.mark.parametrize('owner', [False, True], ids=['reviewer-owed', 'own-card'])
def test_unreadable_certificate_policy_never_exempts_a_missing_input(tmp_path, monkeypatch, owner):
    graph, store, state = certificate_step(tmp_path, monkeypatch, relevant=False, owner=owner)
    (tmp_path / 'inputs/request_plan.json').write_text('{}')  # Break the authenticated policy input pin.
    result = graph.checks(state)
    row, = [r for r in result['checks']['results'] if r['check_id'] == review_points.CERTIFICATE_CHECK]
    assert row['status'] == 'inconclusive' and row['reason'] == 'validator_source_unresolved'
    assert 'classification' not in row and result['checks']['passed'] is False
    assert not any(review_points.CERTIFICATE_CHECK in r['record']['checks']
                   for r in store.scan(graph.CLASSIFICATION))


@pytest.mark.parametrize('kinds', [['comparison'], ['comparison', 'judgment-record'], ['inference', 'figure']])
def test_a_step_without_event_level_outputs_disposes_cutflow_and_acceptance(kinds):
    step = {'id': 'compare', 'outputs': [{'path': f'outputs/{i}.json', 'kind': k} for i, k in enumerate(kinds)]}
    rows = policy.dispositions(step, [policy.CUTFLOW, policy.ACCEPTANCE, policy.NORMALIZATION])
    assert {c: r['applies'] for c, r in rows.items() if c in policy.EVENT_CHECKS} == {
        policy.CUTFLOW: False, policy.ACCEPTANCE: False}
    row = rows[policy.ACCEPTANCE]
    assert row['reason'] in ('no_declared_event_level_outputs', 'no_declared_physical_outputs')
    assert row['evidence']['products']['kinds'] == kinds


@pytest.mark.parametrize('kinds', [['comparison', 'cutflow'], ['table'], ['comparison', 'binned_values'],
                                   ['comparison', 'unclassified-kind']])
def test_declared_event_level_or_unclassified_outputs_keep_cutflow_and_acceptance(kinds):
    step = {'id': 'compare', 'outputs': [{'path': f'outputs/{i}.json', 'kind': k} for i, k in enumerate(kinds)]}
    rows = policy.dispositions(step, [policy.CUTFLOW, policy.ACCEPTANCE])
    assert rows == {}, rows   # no row: the checks stay owed, and no check is ever added
