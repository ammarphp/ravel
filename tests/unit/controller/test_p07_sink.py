"""The sole sink end to end on fictional controller runs: delivery, receipt, bounded ending, results file."""
from __future__ import annotations

import json
import shutil
import sys

import pytest

from ravel.controller import sink
from ravel.controller.sink import receipts
from p07_support import REPORT, VALUE, Run, run, statuses  # noqa: F401  (the run fixture)


def test_full_evidence_run_is_accepted_and_architecture_complete(run):
    run.complete()
    receipt = run.deliver()
    assert receipt['label'] == 'accepted' and receipt['accepted'] is True
    assert receipt['architecture_complete'] is True
    assert all(receipt['architecture_predicates'].values())
    assert receipt['host']['mode'] == 'controller' and receipt['host']['whole_host_enforcement'] == 'controller'
    assert receipt['work']['refusal_history_completeness'] == 'complete'
    assert receipt['costs']['model_calls'] == 2 and receipt['costs']['total'] == pytest.approx(0.02)
    assert receipt['instructions']['acknowledgement'] == 'complete'
    assert receipt['confinement']['status'] == 'qualified'
    # The delivery: report, receipt, inventory and the two artifacts, with the store record pointing at them.
    names = sorted(p.name for p in run.delivered('').iterdir())
    assert names == ['DELIVERY.md', 'INVENTORY.json', 'RECEIPT.json', 'artifacts']
    saved = json.loads(run.delivered('RECEIPT.json').read_text())
    assert saved['sha256'] == receipt['sha256'] == run.store.latest('receipt')['record']['receipt_sha256']
    receipts.verify_saved(saved)
    assert json.loads(run.delivered('artifacts/s1/outputs/value.json').read_text()) == VALUE
    report = run.delivered('artifacts/s2/outputs/report.md').read_text()
    assert report.startswith('<!-- RAVEL SINK NOTICE -->') and report.endswith(REPORT)
    # Every delivery obligation was recorded; the bounded-ending rows do not apply to a delivered run.
    assert not [k for k, i in run.ledger.instances.items() if i['status'] == 'pending']
    assert statuses(run, 'GATE-delivery')[None][0] == 'satisfied'
    assert statuses(run, 'GATE-final_task')[None][0] == 'satisfied'
    assert statuses(run, 'B03')[None][0] == 'not_applicable' and statuses(run, 'JR10')[None][0] == 'not_applicable'
    assert receipt['id'] == run.store.latest('receipt')['id']


PREDICATE_CASES = {
    'controller_mode': lambda run, mp: setattr(run.confine, 'kind', 'checkout'),
    'confinement_qualified': lambda run, mp: run.store.entries.__setitem__(slice(None), [
        e if not (e['kind'] == 'step-launch' and e['record'].get('phase') == 'finished') else
        {**e, 'record': {**e['record'], 'backend': None,
                         'plan': {'kind': 'unconfined', 'label_text': 'UNCONFINED EXECUTION'}}}
        for e in run.store.entries]),
    'custody_chain': lambda run, mp: run.store.tampered.append('the record journal was edited'),
    'ledger_result_path': lambda run, mp: run.ledger.instances.__getitem__(
        next(k for k, i in run.ledger.instances.items() if i['id'] == 'X-UPSTREAM')).update(status='pending',
                                                                                             evidence=None),
    'review_complete': lambda run, mp: run.review_round('final', {'physics-critic': (True, 'accept'),
                                                                  'skeptical-verifier': (False, 'accept'),
                                                                  'physics-decider': (True, 'accept')}),
    'instructions_acknowledged': lambda run, mp: run.store.append('step-validation', {
        'schema_version': 1, 'step_id': 's2', 'seat': None, 'attempt': 1, 'receipt_sha256': 'f' * 64,
        'errors': [{'code': 'instruction_ack', 'errors': ['a duty unit has no checklist row']}], 'held': [],
        'labels': [], 'escalations': []}),
    'authority_recorded': lambda run, mp: run.store.entries.__setitem__(slice(None), [
        e for e in run.store.entries if not (e['kind'] == 'authority' and e['record']['kind'] == 'final')]),
    'engagement_complete': lambda run, mp: run.store.entries.__setitem__(slice(None), [
        e for e in run.store.entries if e['kind'] != 'engagement-decision']),
    'accepted_delivery': None,  # an untraced table number in the report (an L row: labelled, ledger still met)
}


@pytest.mark.parametrize('predicate', sorted(PREDICATE_CASES))
def test_architecture_complete_false_when_one_predicate_is_removed(run, monkeypatch, predicate):
    if predicate == 'accepted_delivery':
        run.complete(report=REPORT + '| fictional extra | 99.9 |\n')
    else:
        run.complete()
        PREDICATE_CASES[predicate](run, monkeypatch)
    receipt = run.deliver()
    assert receipt['architecture_predicates'][predicate] is False, receipt['architecture_predicates']
    assert receipt['architecture_complete'] is False and receipt['label'] != 'accepted'
    if predicate == 'accepted_delivery':
        others = {k: v for k, v in receipt['architecture_predicates'].items() if k != predicate}
        assert all(others.values()), others


def test_predicate_list_is_the_one_the_sink_derives():
    assert set(PREDICATE_CASES) | {'sink_rendered'} == set(receipts.PREDICATES)


def test_sink_rendered_predicate_needs_an_actual_delivery(run, monkeypatch):
    run.complete()
    observed = sink.observe_store(run.store)
    assert observed['architecture_predicates']['sink_rendered'] is False
    assert observed['architecture_complete'] is False and observed['delivery']['status'] == 'not delivered'
    from ravel.controller.sink import render

    def fail(*args, **kwargs):
        raise OSError('disk full (fictional)')
    monkeypatch.setattr(render, 'copy_artifacts', fail)
    with pytest.raises(OSError):
        run.deliver()
    assert not run.delivered('').exists() and not list(run.dir.glob('delivery.staging-*'))
    assert not any(r['record'].get('architecture_complete') for r in run.store.scan('receipt'))


def test_no_field_of_the_receipt_is_a_constant(tmp_path, monkeypatch):
    good = Run(tmp_path / 'good', monkeypatch).complete().deliver()
    poor_run = Run(tmp_path / 'poor', monkeypatch)
    poor_run.add_step('s1', ['outputs/value.json'], deliverables=[('d-value', 'outputs/value.json')])
    poor_run.add_step('s2', ['outputs/report.md'], kind='synthesize', deliverables=[('d-report', 'outputs/report.md')])
    poor_run.pin_plan()
    poor_run.adopt('s1', 'outputs/value.json', VALUE, unconfined=True, measured=False)
    poor_run.adopt('s2', 'outputs/report.md', REPORT, producer='worker', inventory=False, measured=False)
    poor_run.store.append('step-refusal', {'schema_version': 1, 'step_id': 's3', 'attempt': 1, 'seat': None,
                                           'reason': 'tool_not_admitted', 'detail': 'a fictional refusal'})
    poor_run.store.append('step-validation', {'schema_version': 1, 'step_id': 's2', 'seat': None, 'attempt': 1,
                                              'receipt_sha256': 'e' * 64, 'held': [], 'labels': [], 'escalations': [],
                                              'errors': [{'code': 'instruction_ack', 'errors': ['missing row']}]})
    poor_run.store.tampered.append('a truncated journal')
    poor_run.store.entries[:] = [e for e in poor_run.store.entries if e['kind'] != 'request']
    poor = poor_run.deliver()
    for path in (('host', 'mode'), ('host', 'tool_inventory'), ('host', 'whole_host_enforcement'),
                 ('work', 'refused'), ('work', 'refusal_history_completeness'), ('costs', 'total'),
                 ('costs', 'model_calls'), ('architecture_complete',), ('confinement', 'status'),
                 ('instructions', 'acknowledgement'), ('ledger', 'by_status'), ('authority', 'records')):
        a, b = good, poor
        for key in path:
            a, b = a[key], b[key]
        assert a != b, path
    assert poor['costs']['model_calls'] is None and poor['costs']['total'] is None
    assert sink.USAGE_UNKNOWN in poor['labels'] and sink.UNCONFINED in poor['labels']


def test_given_plan_must_equal_the_pinned_plan(run):
    run.complete()
    altered = dict(run.plan_doc, deliverables=run.plan_doc['deliverables'][:1])
    receipt = sink.deliver(run.store, altered)
    assert receipt['label'] == 'diagnostic' and not receipt['architecture_complete']
    assert any(r['code'] == 'plan_integrity' for r in receipt['work']['current_refusals'])


def test_absent_ledger_is_diagnostic_never_accepted(run, monkeypatch):
    run.complete()
    monkeypatch.setitem(sys.modules, 'ravel.controller.ledger', None)
    receipt = run.deliver()
    assert receipt['label'] == 'diagnostic' and receipt['ledger']['available'] is False
    assert receipt['architecture_complete'] is False


def test_receipt_rechecks_the_delivered_bytes(run):
    run.complete()
    delivered = run.deliver()
    fresh = sink.receipt(run.store)
    assert fresh['verification']['delivery_intact'] and fresh['architecture_complete'] and fresh['accepted']
    assert fresh['sha256'] == delivered['sha256']
    run.delivered('artifacts/s1/outputs/value.json').write_text('{"value": 99}')
    changed = sink.receipt(run.store)
    assert changed['accepted'] is False and changed['architecture_complete'] is False
    assert 'DELIVERY CHANGED AFTER RECEIPT' in changed['labels']


def test_receipt_before_delivery_is_an_observation(run):
    run.complete()
    observed = sink.receipt(run.store)
    assert observed['delivery']['status'] == 'not delivered' and 'NOT DELIVERED' in observed['labels']
    assert not run.store.scan('receipt') and not run.ledger.deliver_keys


def test_redelivery_keeps_the_previous_delivery(run):
    run.complete()
    first = run.deliver()
    second = run.deliver()
    kept = sorted(p.name for p in run.dir.glob('delivery.superseded-*'))
    assert len(kept) == 1 and second['delivery']['superseded'] == kept[0]
    assert json.loads((run.dir / kept[0] / 'RECEIPT.json').read_text())['sha256'] == first['sha256']


def test_results_file_is_filled_only_for_an_accepted_delivery(tmp_path, monkeypatch):
    accepted = Run(tmp_path / 'a', monkeypatch).complete()
    target = tmp_path / 'trusted' / 'results.json'
    target.parent.mkdir()
    receipt = accepted.deliver(results_file={'path': str(target), 'deliverable': 'd-value'})
    assert receipt['delivery']['results_file']['status'] == 'written'
    assert json.loads(target.read_text()) == VALUE
    assert statuses(accepted, 'GATE-export')[None][0] == 'satisfied'
    held = Run(tmp_path / 'h', monkeypatch).complete()
    held.review_round('final', {'physics-critic': (False, 'accept'), 'skeptical-verifier': (True, 'accept'),
                                'physics-decider': (True, 'accept')})
    other = tmp_path / 'trusted' / 'held.json'
    receipt = held.deliver(results_file=str(other))
    assert receipt['label'] != 'accepted' and receipt['delivery']['results_file']['status'] == 'untouched'
    assert not other.exists()


def test_results_file_refuses_a_location_inside_the_run(run):
    run.complete()
    receipt = run.deliver(results_file={'path': str(run.dir / 'results.json'), 'deliverable': 'd-value'})
    assert receipt['label'] == 'accepted' and receipt['delivery']['results_file']['status'] == 'failed'
    assert not (run.dir / 'results.json').exists()


def test_results_file_must_match_the_target_pinned_at_intake(run, tmp_path):
    run.complete()
    run.store.append('delivery-target', {'path': str(tmp_path / 'pinned.json'), 'deliverable': 'd-value'})
    receipt = run.deliver(results_file={'path': str(tmp_path / 'other.json'), 'deliverable': 'd-value'})
    assert receipt['label'] == 'diagnostic'
    assert not (tmp_path / 'other.json').exists() and not (tmp_path / 'pinned.json').exists()


def partial_run(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    run.add_step('s1', ['outputs/value.json'], deliverables=[('d-value', 'outputs/value.json')])
    run.add_step('s2', ['outputs/report.md'], kind='synthesize', inputs=['s1:outputs/value.json'],
                 deliverables=[('d-report', 'outputs/report.md')])
    run.pin_plan()
    run.adopt('s1', 'outputs/value.json', VALUE)
    run.store.append('step-outcome', {'schema_version': 1, 'step_id': 's2', 'attempt': 1, 'status': 'budget_exhausted',
                                      'reason': 'budget_exhausted'})
    run.authority_record('approve_plan', 'approve')
    run.satisfy_upstream()
    run.ledger.covered = {'d-value'}
    return run


def test_JR10_budget_exhaustion_ends_in_a_qualified_delivery_with_every_obligation(tmp_path, monkeypatch):
    run = partial_run(tmp_path, monkeypatch)
    receipt = sink.bounded_end(run.store, 'budget exhausted: tokens; the step graph held s2')
    assert receipt['label'] == 'qualified' and receipt['qualified'] is True
    assert receipt['accepted'] is False and receipt['architecture_complete'] is False
    assert sink.QUALIFIED in receipt['labels']
    ending = json.loads(run.delivered('qualified-delivery.json').read_text())
    states = {o['id']: o['state'] for o in ending['obligations']}
    assert states == {'d-value': 'satisfied', 'd-report': 'blocked'}
    assert ending['ledger_listing_error'] is None
    assert sorted(o['key'] for o in ending['ledger_obligations'] if o['status'] == 'pending') == \
        sorted(run.ledger.pending(run.store))
    assert ending['ledger_counts'] == run.ledger.summary(run.store)['by_status']
    assert statuses(run, 'B03')[None][0] == 'satisfied'
    assert statuses(run, 'JR10')[None][0] == 'satisfied'
    assert ending['scientific_claims_adopted'] == [] and ending['parent_task_accepted'] is False
    assert receipt['delivery']['results_file']['status'] == 'untouched'
    assert 'Qualified ending' in run.delivered('DELIVERY.md').read_text()
    assert json.loads(run.delivered('artifacts/s1/outputs/value.json').read_text()) == VALUE


def test_B03_bounded_ending_discharges_its_rows_and_notifies_once_without_the_reason(tmp_path, monkeypatch):
    run = partial_run(tmp_path, monkeypatch)
    secret = 'restricted fictional material quoted in a hold reason'
    first = sink.bounded_end(run.store, f'deadline margin reached ({secret})')
    assert statuses(run, 'B03')[None][0] == 'satisfied' and statuses(run, 'JR10')[None][0] == 'satisfied'
    assert statuses(run, 'B03')[None][1]['record'] == first['delivery']['ending_record']
    assert run.authority.notified == ['QUALIFIED ENDING deadline']
    assert secret not in run.authority.notified[0]
    second = sink.bounded_end(run.store, 'deadline margin reached again')
    assert second['notification'] == {'status': 'already sent'} and len(run.authority.notified) == 1


def test_bounded_end_never_raises(tmp_path, monkeypatch):
    run = partial_run(tmp_path, monkeypatch)
    shutil.rmtree(run.dir)
    receipt = sink.bounded_end(run.store, 'stop requested by the operator')
    assert receipt['qualified'] and not receipt['accepted'] and receipt['id']
    assert any(label.startswith('NOT DELIVERED') for label in receipt['labels'])

    class Broken:
        run_id = 'run-broken'

        def scan(self, kind):
            raise OSError('store unreadable (fictional)')

        def append(self, kind, record):
            raise OSError('store unwritable (fictional)')
    receipt = sink.bounded_end(Broken(), 'hold')
    assert receipt['id'] is None and receipt['qualified'] and receipt['architecture_complete'] is False


def test_bounded_end_uses_public_pending_and_summary_without_private_state(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch, listing=False)
    run.add_step('s1', ['outputs/value.json'], deliverables=[('d-value', 'outputs/value.json')])
    run.pin_plan()
    import types
    state = types.ModuleType('ravel.controller.ledger.state')

    def private_load(*args, **kwargs):
        raise AssertionError('the sink must use the public pending and summary APIs')
    state.load = private_load
    monkeypatch.setitem(sys.modules, 'ravel.controller.ledger.state', state)
    sys.modules['ravel.controller.ledger'].state = state
    receipt = sink.bounded_end(run.store, 'escalation unanswered at the wait bound')
    ending = json.loads(run.delivered('qualified-delivery.json').read_text())
    assert ending['ledger_listing_error'] is None
    pending = [o for o in ending['ledger_obligations'] if o['status'] == 'pending']
    assert sorted(o['key'] for o in pending) == sorted(run.ledger.pending(run.store))
    assert any(o['id'] == 'X-UPSTREAM' for o in pending)
    assert ending['ledger_counts'] == run.ledger.summary(run.store)['by_status']
    assert statuses(run, 'B03')[None][0] == 'satisfied'
    assert statuses(run, 'JR10')[None][0] == 'satisfied'
    assert receipt['notification'] == {'status': 'sent'} and run.authority.notified == ['QUALIFIED ENDING escalation']


def test_ending_syntheses_recorded_by_a_route_are_rendered(tmp_path, monkeypatch):
    run = partial_run(tmp_path, monkeypatch)
    record = run.store.append('ending-synthesis', {'source': 'fictional route',
                                                   'result': {'completed_stages': 3, 'open_stages': ['validate']}})
    sink.bounded_end(run.store, 'history bound reached')
    ending = json.loads(run.delivered('qualified-delivery.json').read_text())
    assert ending['syntheses'] == [{'kind': 'ending-synthesis', 'source': 'fictional route', 'record': record,
                                    'result': {'completed_stages': 3, 'open_stages': ['validate']}}]
    assert 'Unfinished work recorded by fictional route' in run.delivered('DELIVERY.md').read_text()


def test_a_store_without_its_run_directory_is_refused_not_observed(run):
    run.complete()
    import shutil
    shutil.rmtree(run.dir)
    with pytest.raises(sink.SinkRefused, match='no run directory'):
        sink.observe_store(run.store)
    receipt = run.deliver()
    assert receipt['label'] == 'diagnostic' and not receipt['accepted'] and receipt['id']


def test_an_internal_planning_plan_bound_later_is_never_the_runs_plan(run):
    run.complete()
    planning = dict(run.plan_doc, deliverables=[], revision=None)
    planning['sha256'] = 'f' * 64
    blob = run.store.put_blob(json.dumps(planning, sort_keys=True).encode())
    run.store.append('plan', {'plan_sha256': planning['sha256'], 'blob': blob, 'source': 'judgment-planning',
                              'revision': None, 'route': 'judgment'})
    receipt = run.deliver()
    assert receipt['label'] == 'accepted' and receipt['plan']['sha256'] == run.plan_doc['sha256']
    assert sink.deliver(run.store, planning)['label'] == 'diagnostic'  # a planning plan is refused as the plan


def test_the_observed_family_relation_comes_from_the_independence_decision(run):
    run.complete()
    for entry in run.store.entries:
        if entry['kind'] == 'step-credit' and entry['record'].get('own'):
            entry['record']['own']['family_relation'] = 'unknown'  # the step's own field, from a one-model call
    receipt = run.deliver()
    relations = {s['family_relation'] for s in receipt['review']['seats']}
    assert relations == {'same'} and 'REVIEW: separate session, same model family' in receipt['labels']

