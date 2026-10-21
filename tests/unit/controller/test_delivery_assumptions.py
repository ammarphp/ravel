"""Delivery staffing credits only current observed audits of located assumptions and results."""
import hashlib
import json

import pytest

from test_p01_final_rdj import case  # noqa: F401
from test_p06_support import operator_home  # noqa: F401
from ravel.controller import graph
from ravel.workflow import spawn_rows


@pytest.fixture(autouse=True)
def installed_plan(case, monkeypatch):
    from ravel.workflow import agent_worker
    # The observed-review fixture has no dispatcher file tree. Keep parsed and
    # published receipt identities distinct in its custody interface too.
    case.audit_receipts = {}
    monkeypatch.setattr(agent_worker, 'load_receipt',
        lambda root, node, attempt: case.audit_receipts[node, attempt]['document'])
    monkeypatch.setattr(agent_worker, '_record',
        lambda root, node, attempt: {'receipt': {'sha256': case.audit_receipts[node, attempt]['published']}})
    case.store.append('plan', {'plan_sha256': case.plan_doc['sha256'], 'revision': 0,
        'source': 'compile', 'blob': case.store.put_blob(json.dumps(case.plan_doc).encode())})


def _adopt(case, step, path, document, *, producer=None):
    raw = json.dumps(document, sort_keys=True).encode()
    destination = f'steps/{step}/{path}'
    target = case.root / destination
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    case.store.append('custody', {'artifact': f'{step}:{path}', 'step_id': step, 'path': path,
        'destination': destination, 'sha256': hashlib.sha256(raw).hexdigest(), 'inputs': [], 'status': 'accepted',
        'producer': producer})
    return target


@pytest.fixture
def audit(case, monkeypatch):
    record = {'assumptions': [{'number': 1, 'statement': 'The fictional input is exact.'}]}
    case.store.append('intake', {'contract_blob': case.store.put_blob(json.dumps(record).encode())})
    _adopt(case, 'derive', 'outputs/value.json', {'value': 1.0, 'assumptions_reported': []})
    subject = graph.delivery_assumption_subject(case.store, case.plan_doc)
    [source] = subject['assumptions']
    document = {'audit': {'schema_version': 1, 'kind': 'assumption-audit', 'items': [
        {'id': source['id'], 'statement': source['statement'], 'locators': [source['locator']],
         'severity': 1, 'controlled': False}]}, 'result': {'assumptions_reported': []}}
    return case, subject, document


def _review(audit, **options):
    case, subject, document = audit
    credit = case.review(case.plan_doc, 'assumption-auditor', step_id='final_review', **options)
    own = case.store.read('step-credit', credit)['record']['own']
    context = own['decision'].get('context_id')
    node, attempt = 'audit-worker', options.get('n', 1)
    receipt = {'node_id': node, 'attempt': attempt, 'session_id': context.split(':', 2)[-1] if context else None}
    case.audit_receipts[node, attempt] = {'document': receipt, 'published': own['query']['receipt_sha256']}
    target = _adopt(case, 'final_review', graph.assumption_audit_path(subject['sha256']), document,
        producer={'kind': 'worker', 'session_id': receipt['session_id'], 'role': 'assumption-auditor',
                  'node_id': node, 'attempt': attempt, 'receipt_sha256': graph._digest(receipt)})
    return credit, target


def test_observed_audit_credits_every_located_assumption(audit):
    case, subject, _ = audit
    credit, _ = _review(audit)
    found = graph.delivery_assumption_evidence(case.root)
    assert found['status'] == 'satisfied', found
    assert found['evidence']['credit'] == credit and found['evidence']['session']
    assert found['evidence']['assumptions'] == [subject['assumptions'][0]['id']]


@pytest.mark.parametrize('options', [
    {'observed': False}, {'session_role': 'physics-critic'}, {'verdict': 'revise'},
    {'credited': False}, {'subject': 'f' * 64},
])
def test_missing_wrong_stale_or_revising_session_is_violated(audit, options):
    case, _, _ = audit
    _review(audit, **options)
    assert graph.delivery_assumption_evidence(case.root)['status'] == 'violated'


@pytest.mark.parametrize('mutation', ['missing_item', 'statement', 'locator', 'high_severity', 'invalid_severity'])
def test_coverage_and_delivered_result_are_checked_from_current_bytes(audit, mutation):
    case, _, document = audit
    item = document['audit']['items'][0]
    if mutation == 'missing_item':
        document['audit']['items'] = []
    elif mutation == 'statement':
        item['statement'] = 'A different premise.'
    elif mutation == 'locator':
        item['locators'] = []
    elif mutation == 'high_severity':
        item['severity'] = 9
        document['result']['assumptions_reported'] = [item['id']]  # caller claim cannot report it in the real result
    else:
        item['severity'] = 0
    _review(audit)
    assert graph.delivery_assumption_evidence(case.root)['status'] == 'violated'


def test_changed_audit_bytes_cannot_reuse_old_review(audit):
    case, _, _ = audit
    _, target = _review(audit)
    assert graph.delivery_assumption_evidence(case.root)['status'] == 'satisfied'
    target.write_text('{}')
    assert graph.delivery_assumption_evidence(case.root)['status'] == 'violated'


def test_new_assumption_cannot_reuse_old_review(audit):
    case, _, _ = audit
    _review(audit)
    assert graph.delivery_assumption_evidence(case.root)['status'] == 'satisfied'
    case.store.append('assumptions', {'assumptions': ['A second premise.']})
    assert graph.delivery_assumption_evidence(case.root)['status'] == 'violated'


@pytest.mark.parametrize('field, value', [('session_id', 'another-session'),
    ('receipt_sha256', 'f' * 64), ('role', 'physics-critic')])
def test_audit_output_must_belong_to_the_credited_session(audit, field, value):
    case, _, _ = audit
    _review(audit)
    assert graph.delivery_assumption_evidence(case.root)['status'] == 'satisfied'
    row = case.store.scan('custody')[-1]['record']
    row['producer'][field] = value
    case.store.append('custody', row)
    found = graph.delivery_assumption_evidence(case.root)
    assert found['status'] == 'violated' and 'credited observed assumption seat' in found['reason']


def test_trigger_without_any_assumption_record_is_violated(case):
    _adopt(case, 'derive', 'outputs/value.json', {'value': 1.0})
    found = graph.delivery_assumption_evidence(case.root)
    assert found['status'] == 'violated' and found['reason'] == 'assumption_record_missing'


def _staffing(monkeypatch):
    monkeypatch.setattr(spawn_rows.reviews, '_facts', lambda root: {
        'agent_layer_epoch': 2, 'plan': {'nodes': [], 'inputs': [], 'edges': [],
            'claims': [{'id': 'C1', 'kind': 'calculation', 'basis_declared': []}]}})


def test_staffing_gate_uses_the_observed_controller_session(audit, monkeypatch):
    case, _, _ = audit
    _review(audit)
    _staffing(monkeypatch)
    [row] = [r for r in spawn_rows.report(case.root) if r['row'] == 'K8']
    assert row['pending'] is False and row['status'] == 'satisfied' and row['roles'] == []
    assert row['evidence']['session'] and row['evidence']['credit']
    assert not [r for r in spawn_rows.gate_errors(case.root, 'delivery', {}) if 'K8' in r.message]


def test_trigger_without_records_stays_violated_at_the_staffing_gate(case, monkeypatch):
    _staffing(monkeypatch)
    [row] = [r for r in spawn_rows.report(case.root) if r['row'] == 'K8']
    assert row['pending'] is True and row['status'] == 'violated'
    assert row['reason'] == 'assumption_record_missing'
    assert any('K8' in r.message for r in spawn_rows.gate_errors(case.root, 'delivery', {}))


def test_repeated_identical_plan_pins_preserve_assumption_source_identity(audit):
    from ravel.controller.routes import plan_sha256
    case, _, _ = audit
    plan = {**case.plan_doc, 'parameters': {'assumptions': [{'statement': 'A located plan premise.'}]}}
    plan['sha256'] = plan_sha256(plan)
    record = {'plan_sha256': plan['sha256'], 'revision': 1,
              'blob': case.store.put_blob(json.dumps(plan).encode())}
    first = case.store.append('plan', record)
    before = graph.delivery_assumption_subject(case.store, plan)
    case.store.append('plan', record)
    after = graph.delivery_assumption_subject(case.store, plan)
    assert before == after
    assert any(a['locator'].startswith(first + '#') for a in after['assumptions'])


def test_high_severity_is_accepted_when_reported_in_current_result_bytes(audit):
    case, _, document = audit
    item = document['audit']['items'][0]
    item['severity'] = 9
    _adopt(case, 'derive', 'outputs/value.json', {'value': 1.0, 'assumptions_reported': [item['id']]})
    subject = graph.delivery_assumption_subject(case.store, case.plan_doc)
    document['result']['assumptions_reported'] = [item['id']]
    _review((case, subject, document))
    assert graph.delivery_assumption_evidence(case.root)['status'] == 'satisfied'


@pytest.mark.parametrize('changed', [False, True])
def test_validator_reads_the_bound_output_of_a_later_attempt(audit, changed):
    from ravel.controller.step import graph as step_graph, validate
    case, _, document = audit
    step = graph._seat_step('assumption-auditor', purpose='final', plan=case.plan_doc,
        subject={'sha256': 'a' * 64, 'assumption_audit': True, 'artifacts': [], 'steps': []})
    path = step['outputs'][0]['path']
    destination = 'steps/final_review.attempt-2/' + path
    target = case.root / destination
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(document).encode()
    target.write_bytes(raw)
    parameters = step_graph._bound_check_inputs(step, [{'path': path, 'destination': destination,
        'sha256': hashlib.sha256(raw).hexdigest()}])
    if changed:
        target.write_text('{}')
    result, executed = validate._run_check('check:validation.assumption_audit.check', parameters,
        run_dir=case.root, scratch=case.root / 'scratch')
    if changed:
        # Changed bytes never reach the validator: a typed, unexecuted refusal names the cause.
        assert not executed and result['status'] == 'inconclusive', result
        assert result['reason'] == 'validator_input_changed', result
    else:
        assert executed and result['status'] == 'passed', result
