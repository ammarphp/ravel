"""Fictional controls for executed reviewer checks and limited method separation."""
import copy
import json

import pytest

from ravel.workflow import (agent_worker, broker, review_points as points, review_projection,
                            review_projection_checks as checks, review_rubric as rubric, role_registry, rdj_custody)
from inert_dispatch import inert_dispatch  # noqa: F401
from test_review_actor_identity import spec, registered
from test_review_points import receipt, run, write
from test_search_review_rubric import complete


@pytest.fixture(autouse=True)
def custody(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))


def test_actor_review_credit_alone_records_no_executed_method_check(tmp_path, inert_dispatch):
    run(tmp_path, claims=[{"id": "C1", "kind": "calculation", "inherits": []}])
    point = "RP4:C1:physics-critic"
    receipt(tmp_path, point, "physics-critic", methodological_independence={"different_route": True})
    assert points.satisfied(tmp_path, point)
    records = list(points._receipt_records(tmp_path, points._facts(tmp_path)))
    credited = next(r for r in records if r["review_point_id"] == point)
    assert credited["_eligible"]
    assert not credited.get("_executable_checks")


POINT = "RP4:C1:physics-critic"


def check_broker(root, node, role, workspace):
    for name in ('inputs', 'outputs', 'scratch', 'calls'):
        (workspace / name).mkdir(parents=True, exist_ok=True)
    value = broker.Broker(root, workspace, node_id=node, attempt=1, allowed_actions=['check run'], max_calls=10)
    checks.register(value, role_registry.load(role))
    return value


def fixture(tmp_path, *, producer_check='review.normalization_recompute', require_distinct=False,
            with_producer=True, packet=True, document=None):
    root = tmp_path / 'run'; root.mkdir()
    run(root, claims=[{'id': 'C1', 'kind': 'calculation', 'inherits': []}])
    doc = document if document is not None else {'packet': complete(), 'cross_section_pb': 2.0,
        'luminosity_ifb': 3.0, 'branching_ratio': 1.0, 'efficiency': 0.5, 'reported_yield': 3000.0}
    subject = write(root / 'inputs/check.json', doc); subject['path'] = 'inputs/check.json'
    producer = None
    if with_producer:
        workspace = broker.work_root(root) / 'producer' / '1'
        target = check_broker(root, 'producer', 'normalization-auditor' if producer_check != 'review.rubric'
                              else 'physics-critic', workspace)
        (workspace / 'inputs/source.json').write_bytes((root / subject['path']).read_bytes())
        target.call({'call_id': 'check', 'action': 'check run', 'args': {
            'check_id': producer_check, 'paths': ['inputs/source.json']}})
        p = workspace / 'calls/1.json'
        producer = {'path': broker.logical(root, p), 'sha256': broker.sha(p)}
    contract = {'id': 'independent-check', 'roles': ['physics-critic'], 'check_id': 'review.rubric',
                'subject': subject, 'producer_receipt': producer, 'require_distinct_method': require_distinct}
    overlay = {'schema_version': 1, 'kind': rubric.OVERLAY_KIND, 'id': 'fictional-check-overlay',
               'rubric': 'search-analysis-review', 'executable_checks': [contract]}
    pin = write(tmp_path / 'overlay.json', overlay)
    rubric.select(root, 'search-analysis-review', pin['path'])
    points.approve(root)
    projected = review_projection.project(root, 'physics-critic', key='check-subject', subjects=[subject['path']])
    s = spec(node='physics-critic1', point_id=POINT,
             subject=points.review_subject(points._facts(root), next(p for p in points.derive(points._facts(root))
                 if p['id'] == POINT)))
    s['role'] = registered('physics-critic')
    ws = agent_worker.materialize(root, s, packet=projected if packet else None)
    target = check_broker(root, s['node_id'], 'physics-critic', ws)
    manifest, _ = review_projection.load(projected)
    artifact = next(row for row in manifest['artifacts'] if row['source_path'] == subject['path'])
    input_path = 'inputs/packet/' + artifact['path']
    return root, target, contract, input_path, projected


def run_check(target, input_path, call_id='check'):
    return target.call({'call_id': call_id, 'action': 'check run', 'args': {
        'check_id': 'review.rubric', 'paths': [input_path]}})


def record(root):
    return next(r for r in points._receipt_records(root, points._facts(root)) if r['review_point_id'] == POINT)


def test_selected_check_is_visible_in_packet_and_actor_claim_cannot_replace_execution(tmp_path):
    root, _, contract, _, packet = fixture(tmp_path)
    _, contents = review_projection.load(packet)
    selected = next(json.loads(raw) for path, raw in contents.items() if path.startswith('ravel:review-rubric/'))
    assert selected['executable_checks'] == [contract]
    receipt(root, POINT, 'physics-critic', methodological_independence={'different_engine': True})
    assert not points.satisfied(root, POINT)
    assert record(root)['_advisory'] == 'executable_check_missing'


def test_actual_own_check_earns_credit_and_reports_callable_separation_only(tmp_path, inert_dispatch):
    root, target, _, path, _ = fixture(tmp_path)
    assert run_check(target, path)['status'] == 'ok'
    receipt(root, POINT, 'physics-critic')
    assert points.satisfied(root, POINT)
    report = points._receipt_report(record(root))['executable_checks'][0]
    assert report['execution'] == 'completed' and report['status'] == 'passed'
    assert report['executed'] is True
    assert report['method_separation'] == 'distinct_callable'
    assert report['scientific_independence_proven'] is False
    assert len(target.verify_ledger()) == 1
    assert points.checkin3_section(root)['review_receipts'][0]['executable_checks'][0] == report


@pytest.mark.parametrize('with_producer,producer_check,expected', [
    (False, 'review.normalization_recompute', 'unknown'), (True, 'review.rubric', 'same_callable')])
def test_unknown_or_same_callable_cannot_satisfy_distinct_method_requirement(tmp_path, with_producer, producer_check, expected):
    root, target, _, path, _ = fixture(tmp_path, with_producer=with_producer, producer_check=producer_check,
                                      require_distinct=True)
    run_check(target, path); receipt(root, POINT, 'physics-critic')
    assert not points.satisfied(root, POINT)
    assert record(root)['_advisory'] == 'method_separation_unverified'
    assert record(root)['_executable_checks'][0]['method_separation'] == expected


@pytest.mark.parametrize('wrapper', [False, True])
def test_callable_difference_cannot_establish_an_independent_method(tmp_path, monkeypatch, wrapper):
    root, target, _, path, _ = fixture(tmp_path, require_distinct=True)
    if wrapper:
        # A differently registered wrapper still executes the producer's arithmetic.
        monkeypatch.setitem(checks.CHECKS, 'review.rubric', lambda doc, check_id:
                            checks.normalization_recompute(doc, check_id=check_id))
    assert run_check(target, path)['status'] == 'ok'
    receipt(root, POINT, 'physics-critic')
    assert len(broker.ledger(root, 'broker')) == 2
    assert not points.satisfied(root, POINT)
    report = record(root)['_executable_checks'][0]
    assert report['execution'] == 'completed' and report['executed'] is True
    assert report['method_separation'] == 'distinct_callable'
    assert report['method_independence'] == 'unverified'
    assert record(root)['_advisory'] == 'method_separation_unverified'
    assert len(target.verify_ledger()) == 1


@pytest.mark.parametrize('producer_status', ['failed', 'inconclusive'])
def test_unsuccessful_producer_result_cannot_establish_method_separation(tmp_path, producer_status):
    document = {'packet': complete()} if producer_status == 'inconclusive' else {
        'packet': complete(), 'cross_section_pb': 2.0, 'luminosity_ifb': 3.0,
        'branching_ratio': 1.0, 'efficiency': 0.5, 'reported_yield': 1.0}
    root, target, _, path, _ = fixture(tmp_path, document=document)
    assert run_check(target, path)['status'] == 'ok'
    receipt(root, POINT, 'physics-critic')
    report = record(root)['_executable_checks'][0]
    assert report['execution'] == 'completed'
    assert report['method_separation'] == 'unknown' and report['producer_method'] is None


@pytest.mark.parametrize('fault', ['empty', 'material_finding', 'wrong_identity'])
def test_pinned_producer_output_must_be_a_substantive_matching_pass(tmp_path, monkeypatch, fault):
    def producer(doc, check_id):
        return checks.result('review.rubric' if fault == 'wrong_identity' else check_id,
            [checks._finding(check_id, 'planted', 'Supplied result conflicts with its input.')]
                if fault == 'material_finding' else [], status='passed',
            diagnostics={} if fault == 'empty' else {'checked': True})
    monkeypatch.setitem(checks.CHECKS, 'review.normalization_recompute', producer)
    root, target, _, path, _ = fixture(tmp_path)
    assert run_check(target, path)['status'] == 'ok'
    receipt(root, POINT, 'physics-critic')
    assert record(root)['_executable_checks'][0]['method_separation'] == 'unknown'


def test_pass_label_with_material_finding_cannot_earn_review_credit(tmp_path, monkeypatch):
    root, target, _, path, _ = fixture(tmp_path)
    monkeypatch.setitem(checks.CHECKS, 'review.rubric', lambda doc, check_id:
        checks.result(check_id, [checks._finding(check_id, 'planted', 'Supplied result conflicts with its input.')],
                      status='passed'))
    assert run_check(target, path)['status'] == 'ok'
    receipt(root, POINT, 'physics-critic')
    assert not points.satisfied(root, POINT)
    assert record(root)['_executable_checks'][0]['execution'] == 'conflicting_result'


def test_optional_method_requirement_preserves_unknown_without_claiming_independence(tmp_path, inert_dispatch):
    root, target, _, path, _ = fixture(tmp_path, with_producer=False, require_distinct=False)
    run_check(target, path); receipt(root, POINT, 'physics-critic')
    assert points.satisfied(root, POINT)
    assert record(root)['_executable_checks'][0]['method_separation'] == 'unknown'


def test_inconclusive_check_is_executed_but_cannot_earn_review_credit(tmp_path):
    root, target, _, path, _ = fixture(tmp_path, document={})
    run_check(target, path); receipt(root, POINT, 'physics-critic')
    assert not points.satisfied(root, POINT)
    assert record(root)['_advisory'] == 'executable_check_missing'
    report = record(root)['_executable_checks'][0]
    assert report['executed'] is True and report['execution'] == 'inconclusive'


def test_pass_label_from_a_noop_check_cannot_earn_credit(tmp_path, monkeypatch):
    root, target, _, path, _ = fixture(tmp_path)
    monkeypatch.setitem(checks.CHECKS, 'review.rubric', lambda doc, check_id: checks.result(check_id, []))
    run_check(target, path); receipt(root, POINT, 'physics-critic')
    assert not points.satisfied(root, POINT)
    assert record(root)['_advisory'] == 'executable_check_missing'
    assert record(root)['_executable_checks'][0]['execution'] == 'no_substantive_result'


def test_materialized_packet_binding_is_required_even_with_a_genuine_check_receipt(tmp_path):
    root, target, _, path, _ = fixture(tmp_path)
    run_check(target, path); receipt(root, POINT, 'physics-critic')
    private = agent_worker._record_path(root, 'physics-critic1', 1)
    value = json.loads(private.read_text()); value['packet'] = None
    private.write_text(json.dumps(value))
    assert not points.satisfied(root, POINT)


def test_later_inconclusive_result_cannot_reuse_an_earlier_pass(tmp_path, monkeypatch):
    root, target, _, path, _ = fixture(tmp_path)
    run_check(target, path)
    monkeypatch.setitem(checks.CHECKS, 'review.rubric', lambda doc, check_id:
                        checks.result(check_id, [], status='inconclusive'))
    run_check(target, path, 'later'); receipt(root, POINT, 'physics-critic')
    assert not points.satisfied(root, POINT)


@pytest.mark.parametrize('changed', ['receipt', 'output'])
def test_later_broken_check_custody_cannot_reuse_an_earlier_pass(tmp_path, monkeypatch, changed, inert_dispatch):
    root, target, _, path, _ = fixture(tmp_path)
    assert run_check(target, path)['status'] == 'ok'
    original = checks.CHECKS['review.rubric']

    def repeated(doc, check_id):
        value = original(doc, check_id=check_id)
        value['diagnostics']['repeated'] = True
        return value

    monkeypatch.setitem(checks.CHECKS, 'review.rubric', repeated)
    assert run_check(target, path, 'later')['status'] == 'ok'
    receipt(root, POINT, 'physics-critic')
    calls = target.verify_ledger()
    assert len(calls) == 2 and len(broker.ledger(root, 'broker')) == 3
    assert points.satisfied(root, POINT)
    broken = (target.workspace / 'calls/2.json' if changed == 'receipt' else
              broker.locate(root, calls[-1]['output_pins'][0]['path']))
    broken.chmod(0o600)
    broken.write_text('{}')
    assert not points.satisfied(root, POINT)
    assert record(root)['_advisory'] == 'executable_check_missing'


def test_later_raised_check_cannot_reuse_an_earlier_pass(tmp_path, monkeypatch):
    root, target, _, path, _ = fixture(tmp_path)
    assert run_check(target, path)['status'] == 'ok'

    def raised(doc, check_id):
        raise ValueError('Supplied check cannot complete.')

    monkeypatch.setitem(checks.CHECKS, 'review.rubric', raised)
    assert run_check(target, path, 'later')['status'] == 'failed'
    receipt(root, POINT, 'physics-critic')
    calls = target.verify_ledger()
    assert len(calls) == 2 and len(broker.ledger(root, 'broker')) == 3
    assert calls[-1]['validator_id'] == 'review.rubric' and calls[-1]['output_pins'] == []
    assert not points.satisfied(root, POINT)
    report = record(root)['_executable_checks'][0]
    assert report['executed'] is True and report['execution'] == 'not_verified'
    assert report['reviewer_method'] is None and 'output' not in report


@pytest.mark.parametrize('alias', ['dot', 'separator'])
def test_later_failed_check_of_a_subject_path_alias_cannot_reuse_a_pass(tmp_path, monkeypatch, alias):
    root, target, _, path, _ = fixture(tmp_path)
    assert run_check(target, path)['status'] == 'ok'
    monkeypatch.setitem(checks.CHECKS, 'review.rubric', lambda doc, check_id:
        checks.result(check_id, [checks._finding(check_id, 'planted', 'Supplied record fails its check.')]))
    copied = './' + path if alias == 'dot' else path.replace('inputs/packet/', 'inputs//packet/')
    assert run_check(target, copied, 'later')['status'] == 'failed'
    receipt(root, POINT, 'physics-critic')
    calls = target.verify_ledger()
    assert len(calls) == 2 and len(broker.ledger(root, 'broker')) == 3
    assert calls[0]['input_pins'] == calls[1]['input_pins']
    assert not points.satisfied(root, POINT)
    report = record(root)['_executable_checks'][0]
    assert report['execution'] == 'completed' and report['status'] == 'failed'


def test_completed_failed_check_of_another_subject_preserves_the_exact_subject_pass(tmp_path, monkeypatch,
                                                                                    inert_dispatch):
    root, target, _, path, _ = fixture(tmp_path)
    assert run_check(target, path)['status'] == 'ok'
    (target.workspace / 'inputs/other.json').write_text('{}')
    monkeypatch.setitem(checks.CHECKS, 'review.rubric', lambda doc, check_id:
        checks.result(check_id, [checks._finding(check_id, 'planted', 'Supplied record fails its check.')]))
    assert run_check(target, 'inputs/other.json', 'other')['status'] == 'failed'
    receipt(root, POINT, 'physics-critic')
    calls = target.verify_ledger()
    assert len(calls) == 2 and len(broker.ledger(root, 'broker')) == 3
    assert calls[0]['input_pins'] != calls[1]['input_pins'] and calls[1]['input_pins']
    assert points.satisfied(root, POINT)


@pytest.mark.parametrize('subject', ['dot', 'separator', 'other'])
def test_raised_check_without_subject_pins_cannot_prove_an_unrelated_subject(tmp_path, monkeypatch, subject):
    root, target, _, path, _ = fixture(tmp_path)
    assert run_check(target, path)['status'] == 'ok'
    (target.workspace / 'inputs/other.json').write_text('{}')
    copied = ('./' + path if subject == 'dot' else path.replace('inputs/packet/', 'inputs//packet/')
              if subject == 'separator' else 'inputs/other.json')

    def raised(doc, check_id):
        raise ValueError('Supplied check cannot complete.')

    monkeypatch.setitem(checks.CHECKS, 'review.rubric', raised)
    assert run_check(target, copied, 'later')['status'] == 'failed'
    receipt(root, POINT, 'physics-critic')
    calls = target.verify_ledger()
    assert len(calls) == 2 and len(broker.ledger(root, 'broker')) == 3
    assert calls[1]['input_pins'] == [] and calls[1]['output_pins'] == []
    assert not points.satisfied(root, POINT)
    report = record(root)['_executable_checks'][0]
    assert report['executed'] is True and report['execution'] == 'not_verified'
    assert 'no authenticated subject pin' in report['reason']


@pytest.mark.parametrize('target_file', ['input', 'output', 'source', 'receipt'])
def test_changed_check_input_output_source_or_receipt_reopens_obligation(tmp_path, target_file, inert_dispatch):
    root, target, contract, path, _ = fixture(tmp_path)
    run_check(target, path); receipt(root, POINT, 'physics-critic')
    assert points.satisfied(root, POINT)
    call = target.verify_ledger()[0]
    changed = (target.workspace / path if target_file == 'input' else
               broker.locate(root, call['output_pins'][0]['path']) if target_file == 'output' else
               root / contract['subject']['path'] if target_file == 'source' else target.workspace / 'calls/1.json')
    changed.chmod(0o600); changed.write_text('{}')
    assert not points.satisfied(root, POINT)


def test_other_worker_check_does_not_satisfy_the_reviewers_obligation(tmp_path):
    root, target, _, path, _ = fixture(tmp_path)
    own = check_broker(root, 'other', 'physics-critic', broker.work_root(root) / 'other' / '1')
    (own.workspace / 'inputs/source.json').write_bytes((target.workspace / path).read_bytes())
    run_check(own, 'inputs/source.json')
    receipt(root, POINT, 'physics-critic')
    assert not points.satisfied(root, POINT)


def test_changed_producer_input_cannot_claim_verified_method_separation(tmp_path):
    root, target, contract, path, _ = fixture(tmp_path, require_distinct=True)
    run_check(target, path); receipt(root, POINT, 'physics-critic')
    producer = broker.verify_broker_receipt(root, contract['producer_receipt'])
    broker.locate(root, producer['input_pins'][0]['path']).write_text('{}')
    assert not points.satisfied(root, POINT)
    assert record(root)['_executable_checks'][0]['method_separation'] == 'unknown'


def test_failed_check_is_preserved_and_holds_review_credit(tmp_path):
    doc = {'packet': complete()}; doc['packet']['note']['pages'] = 100
    root, target, _, path, _ = fixture(tmp_path, document=doc)
    assert run_check(target, path)['status'] == 'failed'
    receipt(root, POINT, 'physics-critic')
    assert not points.satisfied(root, POINT)
    assert record(root)['_advisory'] == 'executable_check_failed'
    assert record(root)['_executable_checks'][0]['status'] == 'failed'


def test_overlay_contract_cannot_be_weakened_or_assert_execution(tmp_path):
    root, _, contract, _, _ = fixture(tmp_path)
    selected = rubric.selected(root)
    checked = rubric.evaluate({'kind': selected['packet']['kind']}, selected)
    assert checked['diagnostics']['executable_checks'][0]['execution'] == 'not_verified'
    weakened = copy.deepcopy(selected); weakened['executable_checks'][0]['check_id'] = 'unregistered'
    assert rubric.extension_errors(weakened)
    contract['roles'] = ['physics-critic']; contract['check_id'] = 'review.normalization_recompute'
    assert rubric.executable_check_errors([contract])


def test_approved_executable_obligation_cannot_be_removed_by_changing_selection(tmp_path):
    root, _, _, _, _ = fixture(tmp_path)
    rubric.select(root, 'search-analysis-review')
    with pytest.raises(ValueError, match='approved executable review rubric'):
        points.pending(root)


def normalization_review(tmp_path, changes=None, *, document=None, role='normalization-auditor',
                         check_id='review.normalization_recompute', point_id='RP5:C1'):
    """Supply numerical source bytes before any reviewer, then use the real checker.

    The fixture establishes input custody and arithmetic only. Neither the input
    values' scientific applicability nor the producing method is authenticated.
    """
    root = tmp_path / 'run'; root.mkdir()
    run(root, claims=[{'id': 'C1', 'kind': 'calculation', 'inherits': [], 'absolute_yield': True}])
    document = document if document is not None else {'cross_section_pb': 2.0, 'luminosity_ifb': 3.0, 'branching_ratio': 0.25,
                'k_factor': 1.2, 'efficiency': 0.5, 'reported_yield': 900.0, 'tolerance': 1e-12,
                **(changes or {})}
    source = write(root / 'inputs/independent-normalization.json', document)
    source['path'] = 'inputs/independent-normalization.json'
    rdj_custody.record_input_snapshot(root, 'run_init')
    assert rdj_custody.input_snapshot(root)[source['path']] == source['sha256']
    node = role + '1'
    contract = {'id': 'source-normalization', 'roles': [role], 'check_id': check_id,
                'subject': source, 'producer_receipt': None, 'require_distinct_method': False}
    overlay = {'schema_version': 1, 'kind': rubric.OVERLAY_KIND, 'id': 'numerical-source-overlay',
               'rubric': 'search-analysis-review', 'executable_checks': [contract]}
    overlay_pin = write(tmp_path / 'normalization-overlay.json', overlay)
    rubric.select(root, 'search-analysis-review', overlay_pin['path']); points.approve(root)
    packet = review_projection.project(root, role, key='numerical-source', subjects=[source['path']])
    manifest, contents = review_projection.load(packet)
    assert json.loads(contents[source['path']]) == document
    point = next(p for p in points.derive(points._facts(root)) if p['id'] == point_id)
    worker_spec = spec(node=node, point_id=point_id, subject=points.review_subject(points._facts(root), point))
    worker_spec['role'] = registered(role)
    workspace = agent_worker.materialize(root, worker_spec, packet=packet)
    target = check_broker(root, node, role, workspace)
    artifact = next(row for row in manifest['artifacts'] if row['source_path'] == source['path'])
    copied = 'inputs/packet/' + artifact['path']
    reply = target.call({'call_id': 'recompute', 'action': 'check run', 'args': {
        'check_id': contract['check_id'], 'paths': [copied]}})
    receipt(root, point_id, role)
    body = target.verify_ledger()[0]
    result = json.loads(broker.locate(root, body['output_pins'][0]['path']).read_text())
    record = next(r for r in points._receipt_records(root, points._facts(root)) if r['review_point_id'] == point_id)
    return root, target, source, copied, reply, result, record


def test_numerical_reviewer_independently_recomputes_the_supplied_normalization(tmp_path, inert_dispatch):
    root, target, _, _, reply, result, record = normalization_review(tmp_path)
    assert reply['status'] == 'ok' and points.satisfied(root, 'RP5:C1')
    # 2 pb * 1000 * 3 /fb * 0.25 * 1.2 * 0.5 = 900 events.
    assert result['diagnostics']['expected_yield'] == 900.0
    assert result['diagnostics']['reported_yield'] == 900.0 and result['diagnostics']['ratio'] == 1.0
    executed = record['_executable_checks'][0]
    assert executed['reviewer_method'] == ['ravel.workflow.review_projection_checks', 'normalization_recompute']
    assert executed['method_separation'] == 'unknown' and executed['producer_method'] is None
    assert executed['scientific_independence_proven'] is False
    assert len(target.verify_ledger()) == 1


@pytest.mark.parametrize('changes,expected,cause', [
    ({'reported_yield': 1000.0}, 900.0, 'normalization_mismatch'),
    ({'reported_yield': 750.0}, 900.0, 'k_factor_omitted'),
    ({'reported_yield': 1080.0}, 900.0, 'k_factor_applied_twice'),
    ({'reported_yield': 3600.0}, 900.0, 'branching_ratio_omitted'),
    ({'cross_section_pb': 4.0}, 1800.0, 'normalization_mismatch'),
])
def test_numerical_wrong_value_and_modifier_siblings_refuse_credit(tmp_path, changes, expected, cause):
    root, _, _, _, reply, result, record = normalization_review(tmp_path, changes)
    assert reply['status'] == 'failed' and not points.satisfied(root, 'RP5:C1')
    assert result['diagnostics']['expected_yield'] == expected
    assert result['findings'][0]['code'] == cause
    assert record['_advisory'] == 'executable_check_failed'
    assert record['_executable_checks'][0]['executed'] is True


@pytest.mark.parametrize('source_or_copy', ['source', 'copy'])
def test_changed_numerical_source_or_copy_cannot_reuse_review_credit(tmp_path, source_or_copy, inert_dispatch):
    root, target, source, copied, _, _, _ = normalization_review(tmp_path)
    assert points.satisfied(root, 'RP5:C1')
    path = root / source['path'] if source_or_copy == 'source' else target.workspace / copied
    value = json.loads(path.read_text()); value['k_factor'] = 2.4
    path.chmod(0o600); path.write_text(json.dumps(value))
    assert not points.satisfied(root, 'RP5:C1')


def test_missing_numerical_source_value_remains_inconclusive(tmp_path):
    root, _, _, _, _, result, record = normalization_review(tmp_path, {'efficiency': None})
    assert result['status'] == 'inconclusive' and result['diagnostics']['missing'] == ['efficiency']
    assert not points.satisfied(root, 'RP5:C1')
    assert record['_executable_checks'][0]['executed'] is True
    assert record['_executable_checks'][0]['execution'] == 'inconclusive'


@pytest.mark.parametrize('change,status', [(None, 'passed'), ('value', 'failed'), ('subject', 'inconclusive')])
def test_registered_likelihood_comparison_runs_through_selected_rubric(tmp_path, change, status):
    from test_higgs_owner_interfaces import engines
    document = engines()
    if change == 'value':
        document['likelihood']['delta_chi2'] = 9.0
    elif change == 'subject':
        document['likelihood']['comparison_input_sha256'] = 'b' * 64
    role, check_id = 'higgs-combination-reviewer', 'check:higgs.cross_engine'
    point_id = POINT
    root, target, _, _, _, result, record = normalization_review(tmp_path, document=document,
        role=role, check_id=check_id, point_id=point_id)
    assert result['status'] == status
    # A specialized comparison executes through the rubric, but fills no other role's seat.
    assert not points.satisfied(root, point_id)
    report = record['_executable_checks'][0]
    assert report['executed'] is True and report['scientific_independence_proven'] is False
    assert report['status'] == status
    assert report['execution'] == ('inconclusive' if status == 'inconclusive' else 'completed')
    assert report['method_independence'] == 'unverified'
    assert len(target.verify_ledger()) == 1
    assert len(broker.ledger(root, 'broker')) == 1


def test_run_only_cut_check_cannot_be_misdeclared_as_a_projected_document_check(tmp_path):
    _, _, contract, _, _ = fixture(tmp_path)
    contract['check_id'] = 'check:validation.validate_cutflow'
    contract['roles'] = ['detector-calibrator']
    assert any('.check_id: an existing document check' in error
               for error in rubric.executable_check_errors([contract]))
