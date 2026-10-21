"""22 bespoke delivery/budget contracts with adversarial and clean observations.

Every case enters the public installed sink with real store records and producer
bytes. Unrelated unfinished run obligations remain explicitly diagnostic. This is
synthetic sink-entry coverage and does not establish scientific acceptance.
"""
from __future__ import annotations

import json

from nc_cases import CONTROLLER, case
from nc_sink_entry import SinkHarness, payload, assert_svg_presentation
from nc_mutations import PEER, CONTROLLER as MUTATION_CONTROLLER, Mutation, register


def _harness(nc):
    return SinkHarness(nc)


ROWS = dict(refusal='A12', origin='T10', rounds='B03', usage='B04', prose='D01',
            statistic='D02', panels='D03', review='D04', completion='D05', inventory='D07',
            lineage='D08', certificate='C06', defaults='C22', population='C27',
            certificate_origin='C33', tail='E11', fidelity='E15', crossing='E19',
            render='E20', defect='E25', verdict='E26', environment='E27')


def _assert(out, *, errors=(), notices=(), reason=None):
    """Assert the intended row against real sink decisions, never a peer verdict.

    Clean controls require this check to accept its specific artifact, while the
    complete fixture stays visibly diagnostic for unrelated unfinished obligations.
    """
    row_id = ROWS[out.kind]
    receipt = out.receipt
    assert out.observer['starts'] == 1 and out.observer['exits'] == [0]
    assert out.observer['published'] == len(out.published)
    assert not receipt['accepted'] and not receipt['architecture_complete']
    assert receipt['label'] in ('qualified', 'diagnostic')
    rows = [r for r in out.rows if r.id == row_id]
    refusals = receipt['work']['current_refusals']
    report = (out.directory / 'DELIVERY.md').read_text()
    stored = json.loads((out.directory / 'RECEIPT.json').read_bytes())
    assert stored['work']['current_refusals'] == refusals
    assert f"Delivery label: {receipt['label'].upper()}" in report
    assert 'Architecture complete: no' in report
    assert not any(r['code'] in ('ledger_record', 'ledger_materialise', 'ledger_absent') for r in refusals), refusals
    target = 's:report.md' if out.kind in ('prose', 'render') else 's:result.svg' if out.kind == 'panels' else 's:result.json'
    if out.kind == 'rounds' and errors:
        assert rows and all(r.status == 'satisfied' for r in rows)
        assert receipt['delivery']['status'] == 'qualified ending' and reason in report
        ending = json.loads((out.directory / 'qualified-delivery.json').read_bytes())
        assert ending['scientific_claims_adopted'] == [] and ending['parent_task_accepted'] is False
        assert ending['reason'] == reason and ending['ledger_listing_error'] is None
        return
    if out.kind == 'review':
        refused = [r for r in refusals if r['code'] == 'review_incomplete']
        assert bool(refused) is bool(errors), ('SOURCE-GAP D04 sink/review owner', refused)
        seats = receipt['review']['rounds']['final']['seats']
        assert all(v['credited'] for v in seats.values()) is (not bool(errors))
        if errors:
            assert seats['tier_b']['credited'] is False
            assert all(r['message'] in report for r in refused)
        assert target in out.published and out.published[target] == out.raw['result.json']
        return
    assert rows, ('SOURCE-GAP', row_id, 'sink/ledger owner', receipt)
    selected = [r for r in rows if r.scope.get('artifact') in (None, target)]
    assert selected, (row_id, rows)
    if out.kind == 'usage':
        assert all(r.status == 'satisfied' for r in selected)
        assert ('tokens' in receipt['costs']['unknown']) is bool(notices)
        assert (receipt['costs']['tokens'] is None) is bool(notices)
        if notices:
            assert any('USAGE' in label.upper() and 'UNKNOWN' in label.upper() for label in receipt['labels'])
    else:
        expected = ('satisfied' if out.kind == 'completion' else 'violated' if errors or notices
                    else 'not_applicable' if out.kind == 'rounds' else 'satisfied')
        assert any(r.status == expected and r.evidence for r in selected), (
            'SOURCE-GAP', row_id, 'sink check owner', expected,
            [(r.status, r.evidence) for r in selected])
        if notices:
            labels = [d['label'] for d in receipt['label_details'] if d.get('row') == row_id]
            assert labels and all(label in report for label in labels)
            if target.endswith(('.md', '.txt')):
                assert all(label.encode() in out.published[target] for label in labels)
        if errors and out.kind != 'completion':
            assert any(r.get('row') == row_id for r in refusals), ('SOURCE-GAP', row_id, 'missing case-specific refusal', refusals)
    if errors:
        # These contracts withhold accepted status; diagnostic retained bytes are
        # explicitly permitted by the canonical test ideas (e.g. A12).
        relevant = [r for r in refusals if r.get('row') == row_id]
        if out.kind == 'completion':
            assert target not in out.published
            assert any(r.id == 'C27' and r.status == 'violated' for r in out.rows)
            assert any(h['step_id'] == 's' and h['status'] == 'diagnostic' for h in receipt['work']['holds'])
            assert 'd-result.json' in report and 'step_not_completed' in report
            assert 'All requested work is complete' in out.raw['result.json'].decode()
        else:
            assert relevant and all(r in stored['work']['current_refusals'] for r in relevant)
        if out.kind == 'refusal':
            assert any(r.get('step_id') == 's' and r.get('attempt') == 1 for r in receipt['work']['refused'])
        if out.kind == 'verdict':
            seats = receipt['review']['rounds']['final']['seats']
            assert {v['verdict'] for v in seats.values()} == {'FAIL'} and 'FAIL' in report
        labels = [d['label'] for d in receipt['label_details'] if d.get('row') == row_id]
        assert all(label in report for label in labels)
        if target.endswith(('.md', '.txt')) and target in out.published:
            assert all(label.encode() in out.published[target] for label in labels)
    else:
        assert target in out.published, (row_id, receipt)
        if out.kind == 'panels':
            assert_svg_presentation(out.published[target], out.raw['result.svg'], receipt)
        else:
            assert out.published[target].endswith(out.raw[target.split(':', 1)[1]])
    if out.kind == 'inventory':
        assert set(out.published) == {'s:result.json', 's:appendix.txt'}
        assert b'RAVEL SINK NOTICE' in out.published['s:appendix.txt']
    if out.kind == 'defaults':
        assert [d['chosen'] for d in receipt['judgments']['adopted_defaults']] == ['conservative']
        assert 'conservative' in report


@case('A12', binding=CONTROLLER)
def test_A12_refusal_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('refusal')
    hostile = dict(clean, refused=True)
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, errors=('refused_attempt',),
            reason='refused_attempt')

@case('T10', binding=CONTROLLER)
def test_T10_origin_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('origin')
    hostile = dict(clean, producer_journal=False)
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, errors=('receipt_origin',),
            reason='receipt_origin')

@case('B03', binding=CONTROLLER)
def test_B03_rounds_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('rounds')
    hostile = dict(clean, review_history=['unchanged-subject-sha','unchanged-subject-sha'])
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, errors=('review_rounds_exhausted',),
            reason='review_rounds_exhausted')

@case('B04', binding=CONTROLLER)
def test_B04_usage_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('usage')
    hostile = dict(clean, tokens=None)
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, notices=('tokens_unknown',),
            reason='tokens_unknown')

@case('D01', binding=CONTROLLER)
def test_D01_prose_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('prose')
    hostile = dict(clean, prose=[9.75])
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, notices=('unverified_prose',),
            reason='unverified_prose')

@case('D02', binding=CONTROLLER)
def test_D02_statistic_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('statistic')
    hostile = dict(clean, statistic='95% CLs')
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, errors=('statistic_mismatch',),
            reason='statistic_mismatch')

@case('D03', binding=CONTROLLER)
def test_D03_panels_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('panels')
    hostile = dict(clean, panels=['left'])
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, errors=('missing_panel',),
            reason='missing_panel')

@case('D04', binding=CONTROLLER)
def test_D04_review_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('review')
    hostile = dict(clean, seats={'tier_a': True, 'tier_b': False})
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, errors=('review_incomplete',),
            reason='review_incomplete')

@case('D05', binding=CONTROLLER)
def test_D05_completion_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('completion')
    hostile = dict(clean, ledger_status='diagnostic')
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, errors=('incomplete_ledger',),
            reason='incomplete_ledger')

@case('D08', binding=CONTROLLER)
def test_D08_lineage_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('lineage')
    hostile = dict(clean, lineage=['accepted', 'diagnostic'])
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, errors=('diagnostic_lineage',),
            reason='diagnostic_lineage')

@case('C06', binding=CONTROLLER)
def test_C06_certificate_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('certificate')
    hostile = dict(clean, certification={'status':'uncertified','fidelity':'proxy','certifiable_route':'native detector validation','flag':'uncertified'})
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, notices=('uncertified_limitation_missing',),
            reason='uncertified_limitation_missing')

@case('C27', binding=CONTROLLER)
def test_C27_population_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('population')
    hostile = dict(clean, offered=['extra.json'])
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, errors=('population_mismatch',),
            reason='population_mismatch')

@case('C33', binding=CONTROLLER)
def test_C33_certificate_origin_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('certificate_origin')
    hostile = dict(clean, certificate_run='other-run')
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, errors=('certificate_origin',),
            reason='certificate_origin')

@case('E11', binding=CONTROLLER)
def test_E11_tail_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('tail', tier='tail')
    hostile = dict(clean, certified=True)
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, notices=('report_only_tail',),
            reason='report_only_tail')

@case('E15', binding=CONTROLLER)
def test_E15_fidelity_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('fidelity')
    hostile = dict(clean, exclusion_of_record=True)
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, notices=('uncertified_fidelity',),
            reason='uncertified_fidelity')

@case('E19', binding=CONTROLLER)
def test_E19_crossing_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('crossing', at_poi_cap=True)
    hostile = dict(clean, resolved=True)
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, notices=('uncrossed_bound',),
            reason='uncrossed_bound')

@case('E20', binding=CONTROLLER)
def test_E20_render_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('render')
    hostile = dict(clean, rendered=[9.75])
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, errors=('render_mismatch',),
            reason='render_mismatch')

@case('E25', binding=CONTROLLER)
def test_E25_defect_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('defect')
    hostile = dict(clean, defects=[{'kind':'defect','id':'required-note','status':'open'}])
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, errors=('open_defect',),
            reason='open_defect')

@case('E26', binding=CONTROLLER)
def test_E26_verdict_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('verdict')
    hostile = dict(clean, presented_verdict='PASS')
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, errors=('verdict_mismatch',),
            reason='verdict_mismatch')

@case('E27', binding=CONTROLLER)
def test_E27_environment_evidence_controls_delivery(nc):
    harness = _harness(nc)
    clean = payload('environment')
    hostile = dict(clean, exported_runtime={'numpy':'current-exporter-version'})
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed, errors=('unsupported_runtime_pin',),
            reason='unsupported_runtime_pin')

@case('D07', binding=CONTROLLER)
def test_D07_truncated_worker_list_cannot_hide_actual_output_bytes(nc):
    harness = _harness(nc)
    clean = payload('inventory', files={'result.json':'1.25','appendix.txt':'retained'},
                    worker_files=['appendix.txt','result.json'])
    hostile = dict(clean, worker_files=['result.json'])
    observed = harness.run(hostile)
    control = harness.run(clean)
    _assert(control)
    _assert(observed)
    assert set(observed.published) == {'s:appendix.txt', 's:result.json'}
    clean['worker_files'] = ['appendix.txt','result.json']
    control = harness.run(clean)
    _assert(control)
    assert set(control.published) == {'s:appendix.txt', 's:result.json'}


@case('C22', binding=CONTROLLER)
def test_C22_omitted_delegated_default_is_restored_from_evidence(nc):
    harness = _harness(nc)
    clean = payload('defaults')
    observed = harness.run(dict(clean, presented_defaults=[]))
    _assert(observed)
    assert observed.receipt['judgments']['adopted_defaults'][0]['chosen'] == 'conservative'
    control = harness.run(clean)
    _assert(control)
    assert control.receipt['judgments']['adopted_defaults'][0]['chosen'] == 'conservative'


# Guard mutation replaces production-shaped fake validation, never an oracle.
# It catches refusal and detect/label paths; installed real probes remain mandatory.
register(Mutation('M19', 'nc_delivery_peer:guard',
                  lambda original: lambda evidence: {'errors': [], 'notices': [], 'disclosures': []},
                  ('A12','T10','D01','D02','D03','D04','D05','D07','D08','C06','C22','C27','C33','E11','E15','E19','E20','E25','E26','E27'),
                  binding=PEER, why='remove evidence validation from fake sink contract'))
register(Mutation('M17', 'nc_delivery_peer:guard',
                  lambda original: lambda evidence: {'errors': [], 'notices': [], 'disclosures': []},
                  ('B03','B04'), binding=PEER, why='remove round and unknown usage guards from fake budget contract'))


# Installed variants disable production checks reached by the original case IDs.
# The peer registrations above remain explicitly excluded from adequacy credit.
def _without_sink_evidence(original):
    def evaluate(*args, **kwargs):
        found = original(*args, **kwargs)
        guarded = {'D01', 'E20', 'C06', 'E11', 'E15', 'E19'}
        for (row, artifact), value in found.rows.items():
            if row in guarded and value['status'] == 'violated':
                value.update(status='satisfied', evidence={'mechanism': 'disabled_sink_check'})
        found.labels = [r for r in found.labels if r.get('row') not in guarded]
        found.refusals = [r for r in found.refusals if r.get('row') not in guarded]
        return found
    return evaluate


def _unknown_usage_is_zero(original):
    def budget(*args, **kwargs):
        result = original(*args, **kwargs)
        result['dimensions']['tokens']['unknown_attempts'] = 0
        return result
    return budget


def _no_bounded_ending(original):
    def deliver_instead(store, reason):
        from ravel.controller import sink
        return sink.deliver(store, None)
    return deliver_instead


register(Mutation('M19', 'ravel.controller.sink.checks:evaluate', _without_sink_evidence,
                  ('D01', 'C06', 'E11', 'E15', 'E19'), binding=MUTATION_CONTROLLER,
                  why='suppress real sink evidence violations and their notices'))
register(Mutation('M17', 'ravel.controller.sink.evidence:_budget', _unknown_usage_is_zero,
                  ('B04',), binding=MUTATION_CONTROLLER,
                  why='report unmeasured token usage as known zero in the actual sink'))
register(Mutation('M17', ('ravel.controller.sink:bounded_end',
                          'ravel.controller.sink.deliver:bounded_end'), _no_bounded_ending,
                  ('B03',), binding=MUTATION_CONTROLLER,
                  why='replace the real qualified bounded ending with ordinary delivery'))
