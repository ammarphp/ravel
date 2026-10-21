"""One test per P07 coverage row (named by its id): mutation, refusal or label, and a positive control."""
from __future__ import annotations

from copy import deepcopy
import io
import json
import tarfile

import pytest
from PIL import Image

from ravel.controller import sink
from p07_support import READING, REPORT, VALUE, Run, run, sha, statuses  # noqa: F401  (run fixture)

FIGURE_READING = deepcopy(READING)
FIGURE_READING['deliverables'].append({'id': 'd-figure', 'claim_kind': None, 'artifact': {'kind': 'figure'}})


def _figure_png():
    output = io.BytesIO()
    Image.new('RGB', (32, 24), (30, 90, 160)).save(output, format='PNG')
    return output.getvalue()


PNG = _figure_png()


def labels(receipt):
    return receipt['labels']


def refusal_codes(receipt):
    return {r['code'] for r in receipt['work']['current_refusals']}


# ---- execution / custody ----------------------------------------------------------------------------

def test_A12_results_of_a_refused_attempt_are_never_delivered(run):
    run.complete()
    run.store.append('step-refusal', {'schema_version': 1, 'marker': 'm', 'step_id': 's1', 'attempt': 1, 'seat': None,
                                      'reason': 'confined_launch_refused', 'detail': 'fictional'})
    receipt = run.deliver()
    assert statuses(run, 'A12')[None][0] == 'violated' and receipt['label'] == 'diagnostic'
    assert receipt['work']['refused_count'] >= 1


def test_A12_positive_control_a_later_attempt_after_a_refusal(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    run.add_step('s1', ['outputs/value.json'], deliverables=[('d-value', 'outputs/value.json')])
    run.add_step('s2', ['outputs/report.md'], deliverables=[('d-report', 'outputs/report.md')])
    run.pin_plan()
    run.store.append('step-refusal', {'schema_version': 1, 'marker': 'm', 'step_id': 's1', 'attempt': 1, 'seat': None,
                                      'reason': 'confined_launch_refused', 'detail': 'fictional'})
    run.adopt('s1', 'outputs/value.json', VALUE, attempt=2)
    run.adopt('s2', 'outputs/report.md', REPORT, producer='worker')
    run.authority_record('approve_plan', 'approve')
    run.authority_record('final', 'accept', authorizes=False)
    run.review_round('final', {'physics-critic': (True, 'accept')})
    run.satisfy_upstream()
    receipt = run.deliver()
    assert statuses(run, 'A12')[None][0] == 'satisfied' and receipt['label'] == 'accepted'


def test_T10_a_receipt_minted_outside_the_controller_confers_nothing(run):
    run.complete()
    # The adopted bytes claim a launch journal the controller never wrote (a script that minted its own receipt).
    for entry in run.store.entries:
        if entry['kind'] == 'custody' and entry['record']['artifact'] == 's1:outputs/value.json':
            entry['record']['producer'] = {'kind': 'launch', 'journal_id': 'step-launch-999999-forged', 'exit_status': 0}
    run.write('steps/s1/outputs/receipt.json', json.dumps({'kind': 'ravel-production-receipt', 'accepted': True}))
    receipt = run.deliver()
    assert statuses(run, 'T10')[None][0] == 'violated' and receipt['label'] == 'diagnostic'
    assert not receipt['architecture_complete']


def test_T10_positive_control(run):
    run.complete()
    run.deliver()
    status, evidence = statuses(run, 'T10')[None]
    assert status == 'satisfied' and set(evidence['record']) == {'s1:outputs/value.json', 's2:outputs/report.md'}


def test_C27_undeclared_extra_is_excluded_and_a_missing_declared_output_refuses(run):
    run.complete()
    run.write('steps/s1/outputs/extra.json', json.dumps({'value': 7}))
    receipt = run.deliver()
    assert receipt['label'] == 'accepted'
    inventory = json.loads(run.delivered('INVENTORY.json').read_text())['classification']
    assert any(e['path'] == 'steps/s1/outputs/extra.json' for e in inventory['excluded'])
    assert not run.delivered('artifacts/s1/outputs/extra.json').exists()
    assert 'steps/s1/outputs/extra.json' in run.delivered('DELIVERY.md').read_text()
    (run.dir / 'steps/s2/outputs/report.md').unlink()
    receipt = run.deliver()
    assert statuses(run, 'C27')['s2:outputs/report.md'][0] == 'violated' and receipt['label'] == 'diagnostic'


def test_C27_reviewed_extra_is_distinguished_and_not_delivered(run):
    run.complete()
    run.adopt('s1', 'outputs/diagnostic-plot-data.json', {'value': 41.7})
    run.store.append('step-credit', {'schema_version': 1, 'step_id': 's1', 'attempt': 1, 'own': None, 'credited': True,
                                     'seats': [{'seat': 'critic-1', 'role': 'physics-critic', 'credited': True,
                                                'verdict': 'accept', 'decision': {'label': 'separate session, same '
                                                                                  'model family'}}]})
    receipt = run.deliver()
    extras = json.loads(run.delivered('INVENTORY.json').read_text())['classification']['extras']
    assert extras == [{'path': 'steps/s1/outputs/diagnostic-plot-data.json',
                       'artifact': 's1:outputs/diagnostic-plot-data.json', 'size': extras[0]['size'],
                       'custody': 'accepted', 'reviewed': True}]
    assert receipt['label'] == 'accepted' and len(receipt['delivery']['artifacts']) == 2


def test_D07_a_worker_supplied_artifact_list_is_ignored(run):
    run.complete()
    # A worker's own list names an undeclared file and omits a declared one.
    run.write('steps/s2/outputs/deliverables.json', json.dumps({'artifacts': ['steps/s1/outputs/forged.json']}))
    run.write('steps/s1/outputs/forged.json', json.dumps({'value': 1e9}))
    receipt = run.deliver()
    delivered = sorted(f['artifact'] for f in receipt['delivery']['artifacts'])
    assert delivered == ['s1:outputs/value.json', 's2:outputs/report.md']
    excluded = {e['path'] for e in json.loads(run.delivered('INVENTORY.json').read_text())['classification']['excluded']}
    assert {'steps/s2/outputs/deliverables.json', 'steps/s1/outputs/forged.json'} <= excluded
    assert all(statuses(run, 'D07')[a][0] == 'satisfied' for a in delivered)


def _diagnostic_twin(run, data):
    """A rejected adopted artifact (a diagnostic output) whose bytes are ``data``."""
    run.add_step('s9', ['outputs/smoke.json'])
    run.adopt('s9', 'outputs/smoke.json', data, status='rejected', outcome='failed')


def test_D08_diagnostic_bytes_copied_or_renamed_into_the_accepted_set_are_refused(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    _diagnostic_twin(run, VALUE)
    run.complete()  # value.json is byte-identical to the rejected smoke output: a copy under a declared name
    receipt = run.deliver()
    assert statuses(run, 'D08')['s1:outputs/value.json'][0] == 'violated'
    assert receipt['label'] == 'diagnostic' and not run.delivered('artifacts/s1/outputs/value.json').exists()


def test_D08_a_self_declared_diagnostic_document_is_refused(run):
    run.complete(value=dict(VALUE, delivery_label='diagnostic'))
    receipt = run.deliver()
    assert statuses(run, 'D08')['s1:outputs/value.json'][0] == 'violated' and receipt['label'] == 'diagnostic'


def test_D08_diagnostic_bytes_nested_in_a_pack_or_archive_are_refused(tmp_path, monkeypatch):
    smoke = {'value': 3.0, 'note': 'smoke rung'}
    raw = json.dumps(smoke, sort_keys=True).encode()
    run = Run(tmp_path, monkeypatch)
    _diagnostic_twin(run, smoke)
    run.complete(value=dict(VALUE, nested={'sha256': sha(raw)}))
    receipt = run.deliver()
    assert statuses(run, 'D08')['s1:outputs/value.json'][0] == 'violated' and receipt['label'] == 'diagnostic'
    archive_run = Run(tmp_path / 'archive', monkeypatch)
    _diagnostic_twin(archive_run, smoke)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as tar:
        info = tarfile.TarInfo('pack/smoke.json')
        info.size = len(raw)
        tar.addfile(info, io.BytesIO(raw))
    archive_run.add_step('s1', ['outputs/pack.tar'], deliverables=[('d-value', 'outputs/pack.tar')])
    archive_run.add_step('s2', ['outputs/report.md'], deliverables=[('d-report', 'outputs/report.md')])
    archive_run.pin_plan()
    archive_run.adopt('s1', 'outputs/pack.tar', buffer.getvalue())
    archive_run.adopt('s2', 'outputs/report.md', 'A pack of results.\n', producer='worker')
    receipt = archive_run.deliver()
    assert statuses(archive_run, 'D08')['s1:outputs/pack.tar'][0] == 'violated'


def test_D08_positive_control(run):
    run.complete()
    run.deliver()
    assert all(s == 'satisfied' for s, _ in statuses(run, 'D08').values())


def test_C33_a_certificate_from_outside_the_run_supplies_nothing(run, tmp_path):
    run.complete(value=dict(VALUE, certification={'status': 'certified', 'kind': 'acceptance-certificate',
                                                  'rundir': str(tmp_path / 'another-run')}, kind='certification'))
    value = json.loads((run.dir / 'steps/s1/outputs/value.json').read_text())
    assert value['kind'] == 'certification'
    receipt = run.deliver()
    assert statuses(run, 'C33')[None][0] == 'violated' and receipt['label'] == 'diagnostic'


def test_C33_positive_control_certificate_of_this_run(run):
    run.complete(value=dict(VALUE, kind='certification', rundir=str(run.dir / 'steps')))
    receipt = run.deliver()
    assert statuses(run, 'C33')[None][0] == 'satisfied' and receipt['label'] == 'accepted'


def test_E27_environment_is_recorded_from_launch_journals_and_the_code_identity(run):
    run.complete()
    receipt = run.deliver()
    status, evidence = statuses(run, 'E27')[None]
    assert status == 'satisfied' and evidence['record']['identity'] == 'record:' + '1' * 64
    assert receipt['confinement']['launches'][0]['backend'] == 'linux'
    assert receipt['host']['code_identity']['digest'] == 'record:' + '1' * 64


@pytest.mark.parametrize('recorded,claimed,exported,accepted', [
    ({'python': '3.12.0'}, {'python': '3.12.0'}, {'python': '3.12.0'}, True),
    ({'python': '3.12.0'}, {'python': '3.12.0'}, {'python': '3.13.0'}, False),
    ({'python': '3.12.0'}, {'python': '3.13.0'}, {'python': '3.13.0'}, False),
    (None, {'python': '3.13.0'}, {'python': '3.13.0'}, False),
    (None, {'python': None}, {'python': None}, True),
    (None, {'python': None}, {'python': '3.13.0'}, False),
    ({'python': '3.12.0'}, {'python': None}, {'python': None}, False),
    ({'python': '3.12.0'}, {'python': '3.12.0'}, ['3.12.0'], False),
    ({'python': '3.12.0'}, {'python': float('nan')}, {'python': '3.12.0'}, False),
])
def test_runtime_export_uses_the_controller_launch_record(run, recorded, claimed, exported, accepted):
    run.complete(value=dict(VALUE, runtime=claimed, exported_runtime=exported))
    finished = run.store.scan('step-launch')[-1]['record']
    assert finished['phase'] == 'finished' and finished['step_id'] == 's1'
    if recorded is not None:
        run.store.append('step-launch', dict(finished, runtime=recorded))
    receipt = run.deliver()
    status, evidence = statuses(run, 'E27')[None]
    assert (status == 'satisfied') is accepted
    assert receipt['accepted'] is accepted
    if not accepted:
        assert status == 'violated' and 'runtime' in evidence['reason']
        assert 'unsupported_runtime_pin' in refusal_codes(receipt)


def test_runtime_evidence_from_another_attempt_cannot_authorize_export(run):
    runtime = {'python': '3.12.0'}
    run.complete(value=dict(VALUE, runtime=runtime, exported_runtime=runtime))
    finished = run.store.scan('step-launch')[-1]['record']
    run.store.append('step-launch', dict(finished, attempt=2, runtime=runtime))
    receipt = run.deliver()
    assert statuses(run, 'E27')[None][0] == 'violated'
    assert 'unsupported_runtime_pin' in refusal_codes(receipt)


@pytest.mark.parametrize('ending', [False, True])
@pytest.mark.parametrize('variant,code', [
    ('clean', None),
    ('breach', 'engagement_breach_recorded'),
    ('missing', 'engagement_broker_unavailable'),
    ('stale', 'engagement_broker_unavailable'),
    ('sanitized', 'engagement_breach_recorded'),
])
def test_sink_retains_recorded_broker_accounting(run, ending, variant, code):
    run.complete()
    recorded = run.engagement.check_envelope(run.store, 'deliver')
    body = {k: v for k, v in recorded.items() if k not in ('schema', 'sha256', 'record_id')}
    body['broker'] = {'available': True, 'requests': 2, 'controller_calls': 2}
    if variant in ('breach', 'sanitized'):
        body.update(status='below_floor', accepted_allowed=False, labels=['ENGAGEMENT BELOW FLOOR'],
                    failures=[{'floor': 'H5', 'reason': 'unattributed broker request'}])
    run.engagement.append(run.store, 'envelope-check', body)
    if variant in ('missing', 'sanitized'):
        clean = dict(body, failures=[], labels=[], status='ok', accepted_allowed=True)
        clean['broker'] = {'available': variant == 'sanitized'}
        run.engagement.append(run.store, 'envelope-check', clean)
    if variant == 'stale':
        run.store.append('budget-settlement', {'key': 'later', 'status': 'released'})
    count = len(run.store.scan('envelope-check'))
    receipt = sink.bounded_end(run.store, 'resource limit') if ending else run.deliver()
    assert len(run.store.scan('envelope-check')) == count
    assert receipt['engagement']['accepted_allowed'] is (code is None)
    assert receipt['engagement']['architecture_complete_allowed'] is (code is None)
    if code:
        assert not receipt['accepted'] and not receipt['architecture_complete']
        assert code in refusal_codes(receipt)
        label = 'ENGAGEMENT BELOW FLOOR' if 'breach' in code else 'USAGE UNKNOWN'
        status = 'below_floor' if 'breach' in code else 'unknown'
        assert receipt['engagement']['envelope_status'] == status
        assert label in receipt['engagement']['labels']
        assert label in run.delivered('DELIVERY.md').read_text()


# ---- numbers, statistic, figures -------------------------------------------------------------------

def test_D01_an_unreceipted_table_number_is_refused(run):
    run.complete(report=REPORT + '| fictional extra | 99.9 |\n')
    receipt = run.deliver()
    status, evidence = statuses(run, 'D01')['s2:outputs/report.md']
    assert status == 'violated' and 'REFUSED: UNTRACED TABLE NUMBER' in labels(receipt)
    assert receipt['label'] == 'diagnostic' and '99.9' in evidence['reason']


def test_D01_an_unmatched_prose_number_is_labelled_not_refused(run):
    run.complete(report=REPORT + '\nThe widget efficiency was 63.2 percent in a cross-check.\n')
    receipt = run.deliver()
    status, evidence = statuses(run, 'D01')['s2:outputs/report.md']
    assert status == 'violated' and evidence['label'] == sink.UNVERIFIED and receipt['label'] == 'accepted'
    assert sink.UNVERIFIED in labels(receipt)
    header = run.delivered('artifacts/s2/outputs/report.md').read_text().split('<!-- END RAVEL SINK NOTICE -->')[0]
    assert sink.UNVERIFIED in header


def test_D01_positive_control_rounded_numbers_trace(run):
    run.complete(report='# Result\n\nThe yield is 42 events (41.7 before rounding), uncertainty 2.3.\n\n'
                        '| yield | 41.7 |\n|---|---|\n| rounded | 42 |\n')
    receipt = run.deliver()
    assert statuses(run, 'D01')['s2:outputs/report.md'][0] == 'satisfied' and receipt['label'] == 'accepted'


def test_E20_a_rendered_table_that_differs_from_the_machine_artifact_is_refused(run):
    run.complete(report=REPORT.replace('| yield | 41.7 |', '| yield | 43.1 |'))
    receipt = run.deliver()
    assert statuses(run, 'E20')['s2:outputs/report.md'][0] == 'violated' and receipt['label'] == 'diagnostic'


def test_E20_a_figure_rendered_from_no_accepted_artifact_is_refused(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch, reading=FIGURE_READING)
    run.complete()
    run.add_step('s3', ['outputs/figure.png'], deliverables=[('d-figure', 'outputs/figure.png')])
    plan = run.pin_plan()
    run.adopt('s3', 'outputs/figure.png', PNG)
    run.review_round('final', {'physics-critic': (True, 'accept')})
    receipt = sink.deliver(run.store, plan)
    assert statuses(run, 'E20')['s3:outputs/figure.png'][0] == 'violated' and receipt['label'] == 'diagnostic'


def figure_run(tmp_path, monkeypatch, *, panels=None, census=None, seats=None):
    run = Run(tmp_path, monkeypatch, reading=FIGURE_READING)
    run.add_step('s1', ['outputs/value.json'], deliverables=[('d-value', 'outputs/value.json')])
    run.add_step('s2', ['outputs/report.md'], deliverables=[('d-report', 'outputs/report.md')])
    outputs = ['outputs/figure.png'] + (['outputs/figure.panels.json'] if census is not None else [])
    run.add_step('s3', outputs, inputs=['s1:outputs/value.json'], deliverables=[('d-figure', 'outputs/figure.png')],
                 parameters={'panels': panels} if panels else None)
    run.pin_plan()
    run.adopt('s1', 'outputs/value.json', VALUE)
    run.adopt('s2', 'outputs/report.md', REPORT, producer='worker')
    run.adopt('s3', 'outputs/figure.png', PNG, inputs=['s1:outputs/value.json'])
    if census is not None:
        run.adopt('s3', 'outputs/figure.panels.json', {'panels': census}, inputs=['s1:outputs/value.json'])
    run.authority_record('approve_plan', 'approve')
    run.authority_record('final', 'accept', authorizes=False)
    run.review_round('final', seats or {'physics-critic': (True, 'accept')})
    run.satisfy_upstream()
    return run


def test_D03_a_figure_needs_a_credited_review_seat(tmp_path, monkeypatch):
    run = figure_run(tmp_path, monkeypatch, seats={'physics-critic': (False, 'accept')})
    receipt = run.deliver()
    assert statuses(run, 'D03')['s3:outputs/figure.png'][0] == 'pending'
    assert receipt['label'] == 'diagnostic' and sink.REVIEW_INCOMPLETE in labels(receipt)


def test_D03_a_dropped_panel_is_refused(tmp_path, monkeypatch):
    run = figure_run(tmp_path, monkeypatch, panels=['left', 'right'], census=['left'])
    receipt = run.deliver()
    status, evidence = statuses(run, 'D03')['s3:outputs/figure.png']
    assert status == 'violated' and 'right' in evidence['reason'] and receipt['label'] == 'diagnostic'


def test_D03_positive_control_reviewed_figure_with_every_panel(tmp_path, monkeypatch):
    run = figure_run(tmp_path, monkeypatch, panels=['left', 'right'], census=['left', 'right'])
    receipt = run.deliver()
    status, evidence = statuses(run, 'D03')['s3:outputs/figure.png']
    assert status == 'satisfied' and evidence['credit'] and receipt['label'] == 'accepted'
    assert statuses(run, 'D03')['s1:outputs/value.json'][0] == 'not_applicable'


PRESCRIBED = deepcopy(READING)
PRESCRIBED['constraints'] = [{'id': 'c1', 'type': 'prescribed_statistic',
                              'value': {'statistic': 'S/sqrt(B + dB^2)', 'verbatim': True}}]


def test_D02_a_statistic_that_differs_from_the_pin_gets_no_accepted_label(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch, reading=PRESCRIBED)
    run.complete(value=dict(VALUE, statistic='95% CLs upper limit'))
    receipt = run.deliver()
    status, evidence = statuses(run, 'D02')['s1:outputs/value.json']
    assert status == 'violated' and evidence['label'] and receipt['label'] == 'qualified'
    assert receipt['accepted'] is False and sink.QUALIFIED_DELIVERY in labels(receipt)


def test_D02_a_result_that_omits_the_prescribed_statistic_is_refused(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch, reading=PRESCRIBED)
    run.complete(value={k: v for k, v in VALUE.items() if k != 'statistic'})
    assert run.deliver()['label'] == 'qualified'


def test_D02_a_physicist_waiver_naming_the_row_allows_acceptance(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch, reading=PRESCRIBED)
    run.complete(value=dict(VALUE, statistic='95% CLs upper limit'))
    run.authority_record('deviation', 'approve', label='physicist_terminal_response', obligations=['D02'])
    receipt = run.deliver()
    assert statuses(run, 'D02')['s1:outputs/value.json'][0] == 'waived'
    assert receipt['label'] == 'accepted' and 'WAIVED D02' in labels(receipt)


def test_D02_a_machine_decision_cannot_waive_the_statistic(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch, reading=PRESCRIBED)
    run.complete(value=dict(VALUE, statistic='95% CLs upper limit'))
    run.authority_record('deviation', 'approve', label='operator_configured_machine', obligations=['D02'])
    assert run.deliver()['label'] == 'qualified'


def test_D02_discovery_language_in_an_exclusion_result_is_labelled(tmp_path, monkeypatch):
    reading = deepcopy(READING)
    reading['deliverables'][0]['claim_kind'] = 'exclusion'
    run = Run(tmp_path, monkeypatch, reading=reading)
    run.complete(value=dict(VALUE, statistic='CLs'),
                 report=REPORT + '\nWe report the discovery of a fictional particle. No significant excess is seen.\n')
    receipt = run.deliver()
    status, evidence = statuses(run, 'D02')['s2:outputs/report.md']
    assert status == 'violated' and evidence['label'] == 'DISCOVERY LANGUAGE IN AN EXCLUSION RESULT'
    assert 'excess' not in evidence['reason'] and receipt['label'] == 'accepted'


def test_D02_positive_control_matching_statistic(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch, reading=PRESCRIBED)
    run.complete(value=dict(VALUE, statistic='S / sqrt(B + dB^2)'))
    receipt = run.deliver()
    assert statuses(run, 'D02')['s1:outputs/value.json'][0] == 'satisfied' and receipt['label'] == 'accepted'


@pytest.mark.parametrize('pinned, prescribed, delivered, matches', [
    ('S/sqrt(B + dB^2)', True, 'S / sqrt(B + dB^2)', True),
    ('S/sqrt(B + dB^2)', True, 'S/sqrt(B)', False),  # a term of the prescribed formula dropped
    ('95% CLs', False, 'CLs', True),  # the exclusion default: an unstated level is the default's
    ('95% CLs', False, '95% CLs upper limit (observed)', True),
    ('95% CLs', False, '95% CLs+b', False),  # CL_{s+b} is a different statistic
    ('95% CLs', False, '90% CLs', False),
    ('90% CLs', True, 'CLs', False),  # a prescribed level must be stated
])
def test_D02_statistic_comparison_is_equality_not_containment(pinned, prescribed, delivered, matches):
    from ravel.controller.sink import checks
    assert checks.statistic_matches(pinned, delivered, level_optional=not prescribed) is matches


def test_D02_a_result_that_drops_a_term_of_the_prescribed_statistic_gets_no_accepted_label(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch, reading=PRESCRIBED)
    run.complete(value=dict(VALUE, statistic='S/sqrt(B)'))
    receipt = run.deliver()
    assert statuses(run, 'D02')['s1:outputs/value.json'][0] == 'violated' and receipt['label'] == 'qualified'


def fidelity_module(levels, wanted):
    """The analysis route's fidelity helpers (requested, planned, below) over fictional levels."""
    import types
    order = ('parton', 'particle', 'smeared', 'fast-response', 'full-simulation')
    module = types.ModuleType('ravel.controller.routes.analysis.fidelity')
    module.requested = lambda reading, contract: {'level': wanted, 'evidence': []}
    module.planned = lambda plan: dict(levels)
    module.below = lambda actual, want: actual is None or order.index(actual) < order.index(want)
    return module


def test_D02_C26_a_result_below_the_requested_fidelity_gets_no_accepted_label(run, monkeypatch):
    import sys
    run.complete()
    monkeypatch.setitem(sys.modules, 'ravel.controller.routes.analysis.fidelity',
                        fidelity_module({'s1': 'particle'}, 'fast-response'))
    receipt = run.deliver()
    status, evidence = statuses(run, 'D02')['s1:outputs/value.json']
    assert status == 'violated' and 'fast-response' in evidence['reason'] and receipt['label'] == 'qualified'
    assert receipt['statistic']['fidelity'] == {'requested': 'fast-response', 'planned': {'s1': 'particle'},
                                                'checked': True}


def test_D02_C26_positive_control_the_planned_fidelity_meets_the_request(run, monkeypatch):
    import sys
    run.complete()
    monkeypatch.setitem(sys.modules, 'ravel.controller.routes.analysis.fidelity',
                        fidelity_module({'s1': 'full-simulation'}, 'fast-response'))
    receipt = run.deliver()
    assert statuses(run, 'D02')['s1:outputs/value.json'][0] == 'satisfied' and receipt['label'] == 'accepted'


# ---- labels -------------------------------------------------------------------------------------------

def test_B04_unmeasured_usage_stays_unknown_never_zero(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    run.add_step('s1', ['outputs/value.json'], deliverables=[('d-value', 'outputs/value.json')])
    run.add_step('s2', ['outputs/report.md'], deliverables=[('d-report', 'outputs/report.md')])
    run.pin_plan()
    run.adopt('s1', 'outputs/value.json', VALUE)
    run.adopt('s2', 'outputs/report.md', REPORT, producer='worker', measured=False)
    receipt = run.deliver()
    assert receipt['costs']['model_calls'] is None and receipt['costs']['tokens'] is None
    assert receipt['costs']['total'] is None and 'model_calls' in receipt['costs']['unknown']
    assert sink.USAGE_UNKNOWN in labels(receipt) and statuses(run, 'B04')[None][0] == 'satisfied'


def test_C06_an_uncertified_claim_without_its_limitation_fields_is_labelled(run):
    run.complete(value=dict(VALUE, certification={'status': 'uncertified', 'fidelity': 'fast-response'}))
    receipt = run.deliver()
    status, evidence = statuses(run, 'C06')[None]
    assert status == 'violated' and 'certifiable_route' in evidence['reason']
    assert 'UNCERTIFIED CLAIM WITHOUT ITS LIMITATION FIELDS' in labels(receipt)


def test_C06_positive_control_uncertified_claim_with_every_field(run):
    run.complete(value=dict(VALUE, certification={'status': 'uncertified', 'fidelity': 'fast-response',
                                                  'explanation': 'no acceptance certificate', 'flag': 'F3',
                                                  'certifiable_route': 'detector-level reproduction'}))
    run.deliver()
    assert statuses(run, 'C06')[None][0] == 'satisfied'


def test_E11_a_low_statistics_tail_region_stays_report_only(run):
    run.complete(value=dict(VALUE, regions=[{'name': 'tail-region', 'tier': 'tail', 'certified': True}]))
    receipt = run.deliver()
    assert statuses(run, 'E11')[None][0] == 'violated' and 'LOW-STATISTICS REGION IS REPORT-ONLY' in labels(receipt)


def test_E15_an_uncertified_custom_analysis_keeps_no_exclusion_of_record(run):
    run.complete(value=dict(VALUE, fidelity='delphes-custom-uncertified', exclusion_of_record=True))
    receipt = run.deliver()
    assert statuses(run, 'E15')[None][0] == 'violated'
    assert 'UNCERTIFIED FIDELITY: NO EXCLUSION OF RECORD' in labels(receipt)


def test_E15_positive_control_the_same_fidelity_without_an_exclusion_of_record(run):
    run.complete(value=dict(VALUE, fidelity={'mode': 'delphes-custom-uncertified'}))
    run.deliver()
    assert statuses(run, 'E15')[None][0] == 'satisfied'


def test_E19_a_scan_cap_is_never_a_resolved_crossing(run):
    run.complete(value=dict(VALUE, limit={'id': 'mu95', 'median_at_cap': True, 'status': 'resolved', 'value': 2.0}))
    receipt = run.deliver()
    assert statuses(run, 'E19')[None][0] == 'violated'
    assert 'SCAN CAP IS A BOUND, NOT A RESOLVED CROSSING' in labels(receipt)


def test_E19_positive_control_an_honest_bound_is_only_noted(run):
    run.complete(value=dict(VALUE, limit={'id': 'mu95', 'median_at_cap': True, 'status': 'bound', 'value': 2.0}))
    receipt = run.deliver()
    assert statuses(run, 'E19')[None][0] == 'satisfied' and 'LIMIT IS A BOUND AT THE SCAN CAP' in labels(receipt)


# ---- delivery and claims ------------------------------------------------------------------------------

def test_C22_every_adopted_delegated_default_is_rendered(run):
    run.complete()
    run.store.append('judgment-record', {'schema_version': 1, 'kind': 'judgment-record', 'id': 'j1', 'step': 's1',
                                         'question': 'which fictional binning', 'chosen': 'coarse',
                                         'default_option': 'coarse', 'options': [{'id': 'coarse'}, {'id': 'fine'}],
                                         'rationale': 'the conservative default at the wait bound',
                                         'default': {'expected_sign': 'wider interval'}, 'class': 'R1'})
    run.authority_record('r3_action', 'default', option='hold-blinded')
    receipt = run.deliver()
    defaults = receipt['judgments']['adopted_defaults']
    assert {d['source'] for d in defaults} == {'judgment', 'authority'}
    text = run.delivered('DELIVERY.md').read_text()
    assert 'the conservative default at the wait bound' in text and 'hold-blinded' in text
    assert all(s == 'satisfied' for s, _ in statuses(run, 'C22').values())


def test_D05_partial_completion_never_claims_complete_resolution(run):
    run.complete()
    run.ledger.covered = {'d-value'}
    receipt = run.deliver()
    assert receipt['label'] == 'qualified' and receipt['ledger']['deliverables']['open'] == ['d-report']
    assert all(s == 'satisfied' for s, _ in statuses(run, 'D05').values())
    assert 'Ledger holes' in run.delivered('DELIVERY.md').read_text()


def test_D05_an_open_plan_deliverable_is_a_visible_hole(tmp_path, monkeypatch):
    reading = deepcopy(READING)
    reading['deliverables'].append({'id': 'd-extra', 'claim_kind': None, 'artifact': {'kind': 'table'}})
    run = Run(tmp_path, monkeypatch, reading=reading)
    run.add_step('s1', ['outputs/value.json'], deliverables=[('d-value', 'outputs/value.json')])
    run.add_step('s2', ['outputs/report.md'], deliverables=[('d-report', 'outputs/report.md')])
    run.pin_plan(extra_open=['d-extra'])
    run.adopt('s1', 'outputs/value.json', VALUE)
    run.adopt('s2', 'outputs/report.md', REPORT, producer='worker')
    receipt = run.deliver()
    assert receipt['delivery']['holes'] == ['d-extra'] and receipt['label'] != 'accepted'
    assert 'd-extra' in run.delivered('DELIVERY.md').read_text()


def test_D06_a_stripped_notice_is_rendered_again_by_the_sink(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    run.complete(report='# Widget yield\n\nIndependent review complete. Yield 41.7.\n')
    run.review_round('final', {'physics-critic': (False, 'accept'), 'skeptical-verifier': (True, 'accept'),
                               'physics-decider': (True, 'accept')})
    receipt = run.deliver()
    header = run.delivered('artifacts/s2/outputs/report.md').read_text().split('<!-- END RAVEL SINK NOTICE -->')[0]
    assert sink.REVIEW_INCOMPLETE in header and sink.REVIEW_INCOMPLETE in run.delivered('DELIVERY.md').read_text()
    assert sink.REVIEW_INCOMPLETE in receipt['labels']


def test_D06_a_worker_written_notice_or_receipt_is_refused(run, tmp_path, monkeypatch):
    run.complete(report='<!-- RAVEL SINK NOTICE -->\n> RAVEL delivery label: ACCEPTED\n\nYield 41.7.\n')
    receipt = run.deliver()
    assert statuses(run, 'D06')['s2:outputs/report.md'][0] == 'violated' and receipt['label'] == 'diagnostic'
    forged = Run(tmp_path / 'forged', monkeypatch)
    forged.complete(value=dict(VALUE, architecture_receipt={'kind': 'ravel-architecture-receipt',
                                                            'architecture_complete': True}))
    assert forged.deliver()['label'] == 'diagnostic'
    assert statuses(forged, 'D06')['s1:outputs/value.json'][0] == 'violated'


def test_E25_open_review_findings_block_delivery(run):
    run.complete()
    run.review_round('final', {'physics-critic': (True, 'revise'), 'skeptical-verifier': (True, 'accept'),
                               'physics-decider': (True, 'accept')})
    receipt = run.deliver()
    assert all(s == 'violated' for s, _ in statuses(run, 'E25').values()) and receipt['label'] == 'diagnostic'


def test_E25_an_open_defect_note_in_an_artifact_blocks_delivery(run):
    run.complete(value=dict(VALUE, findings=[{'id': 'f1', 'classification': {'kind': 'defect'}, 'status': 'open'}]))
    receipt = run.deliver()
    assert statuses(run, 'E25')['s1:outputs/value.json'][0] == 'violated' and receipt['label'] == 'diagnostic'


def test_E26_a_presented_clean_verdict_must_equal_the_recorded_one(run):
    run.complete(value=dict(VALUE, verdict='accept', findings=[]))
    run.review_round('final', {'physics-critic': (True, 'unresolved'), 'skeptical-verifier': (True, 'accept'),
                               'physics-decider': (True, 'accept')})
    receipt = run.deliver()
    assert statuses(run, 'E26')['s1:outputs/value.json'][0] == 'violated' and receipt['label'] == 'diagnostic'


def test_E26_positive_control_and_findings_are_rendered(run):
    run.complete(value=dict(VALUE, verdict='accept', findings=[]))
    run.adopt('final_review', 'outputs/review-final-physics-critic.json',
              {'items': [{'id': 'i1', 'severity': 'C', 'summary': 'a fictional minor finding'}],
               'item_verdicts': [{'item': 'i1', 'verdict': 'pass'}]}, producer='worker')
    receipt = run.deliver()
    assert statuses(run, 'E26')['s1:outputs/value.json'][0] == 'satisfied'
    assert 'a fictional minor finding' in run.delivered('DELIVERY.md').read_text()


def test_claims_from_the_disposition_package_keep_their_visible_reasons(run, monkeypatch):
    package = {'plan': {'claim_map': [{'id': 'c1'}]},
               'rows': [{'planned_claim_id': 'c1', 'disposition': 'withdrawn', 'reason': 'bounded by a limitation'}],
               'value': {'paragraphs': [], 'figures': []}, 'evidence': {}}
    run.add_step('s4', ['outputs/claims.json'])
    run.complete()
    run.deliverables.append({'id': 'd-claims', 'status': 'mapped', 'step': 's4', 'output': 'outputs/claims.json',
                             'claim_kind': None, 'artifact_kind': None})
    plan = run.pin_plan()
    run.authority_record('approve_plan', 'approve')
    run.authority_record('final', 'accept', authorizes=False)
    run.adopt('s4', 'outputs/claims.json', package, producer='worker')
    import types
    validator = types.ModuleType('ravel.workflow.manuscript_claim_disposition')
    seen = []
    validator.validate = lambda *a, **k: seen.append(k) or a[1]
    monkeypatch.setitem(__import__('sys').modules, 'ravel.workflow.manuscript_claim_disposition', validator)
    run.review_round('final', {'physics-critic': (True, 'accept')})
    receipt = sink.deliver(run.store, plan)
    assert seen and seen[0]['final'] is True
    assert 'bounded by a limitation' in run.delivered('DELIVERY.md').read_text()
    assert receipt['label'] == 'accepted'
    validator.validate = lambda *a, **k: (_ for _ in ()).throw(ValueError('withdrawn claim lacks its reason'))
    receipt = sink.deliver(run.store, plan)
    assert receipt['label'] == 'qualified' and 'claims_invalid' in refusal_codes(receipt)


# ---- decision gates -----------------------------------------------------------------------------------

@pytest.mark.parametrize('gate', ['delivery', 'final_task'])
def test_GATE_delivery_and_final_task_refusal_withholds_the_accepted_label(run, gate):
    run.complete()
    run.ledger.refuse[gate] = [{'code': 'provider_refused', 'message': f'fictional {gate} provider refusal'}]
    receipt = run.deliver()
    assert receipt['label'] == 'diagnostic' and statuses(run, f'GATE-{gate}')[None][0] == 'pending'
    assert receipt['ledger']['decisions'][gate]['errors']


def test_GATE_delivery_positive_control_decisions_are_taken_through_the_ledger(run):
    run.complete()
    run.deliver()
    decided = [c[1] for c in run.ledger.calls if c[0] == 'decide']
    assert decided == ['delivery', 'final_task', 'report_integrity']
    assert all(c[2]['plan_sha256'] == run.plan_doc['sha256'] for c in run.ledger.calls if c[0] == 'decide')


def test_GATE_delivery_ledger_refusals_the_gate_does_not_show_are_diagnostic():
    from ravel.controller.sink import checks
    from ravel.controller.sink.deliver import decide_label
    ledger_error = {'code': 'obligation_unmet', 'provider': 'ledger', 'message': 'fictional unmet row'}
    state = {'available': True, 'unmet': [], 'decisions': {'delivery': {'errors': [ledger_error]}}}
    findings = checks.Findings()
    findings.refuse('qualified', code='d02', row='D02', message='fictional waivable refusal')
    assert decide_label(findings, state) == 'diagnostic'
    state['unmet'] = [{'id': 'D02', 'consequence': 'qualified'}]  # positive control: the gate shows the waivable row
    assert decide_label(findings, state) == 'qualified'


def test_GATE_report_integrity_refusal_withholds_the_accepted_label(run):
    run.complete()
    run.ledger.refuse['report_integrity'] = [{'code': 'integrity', 'message': 'fictional integrity refusal'}]
    receipt = run.deliver()
    assert receipt['label'] == 'diagnostic'
    event = next(i for i in run.ledger.instances.values() if i['id'] == 'GATE-report_integrity')
    assert event['status'] == 'pending' and event['scope']['event'].startswith('report:')


def test_GATE_export_refusal_keeps_the_results_file_untouched(run, tmp_path):
    run.complete()
    run.ledger.refuse['export'] = [{'code': 'export', 'message': 'fictional export refusal'}]
    target = tmp_path / 'results.json'
    receipt = run.deliver(results_file={'path': str(target), 'deliverable': 'd-value'})
    assert receipt['label'] == 'diagnostic' and not target.exists()
    assert receipt['delivery']['results_file']['status'] == 'untouched'


def test_the_manuscript_route_check_refuses_an_unreceipted_manuscript(run, monkeypatch):
    import sys
    import types
    run.complete()
    manuscript = types.ModuleType('ravel.controller.routes.manuscript')
    calls = []
    manuscript.delivery_errors_from_store = lambda store, plan: calls.append(plan['sha256']) or [
        {'code': 'manuscript_unreceipted', 'step': 's2', 'deliverable': 'd-report'}]
    monkeypatch.setitem(sys.modules, 'ravel.controller.routes.manuscript', manuscript)
    receipt = run.deliver()
    assert calls == [run.plan_doc['sha256']] and receipt['label'] == 'diagnostic'
    refusal = next(r for r in receipt['work']['current_refusals'] if r['code'] == 'manuscript')
    assert refusal['message'] == 'manuscript_unreceipted: step s2, deliverable d-report'


def test_every_labelled_violation_in_the_ledger_is_rendered_whoever_recorded_it(run):
    run.complete()
    # A labelled violation another node recorded (an L row of the review validators, say).
    from p07_support import CLASSES
    key = run.ledger._add('X-LABELLED', {}, 'intake')
    CLASSES['X-LABELLED'] = 'L'
    try:
        run.ledger.record(run.store, key, 'violated', {'reason': 'a fictional method check is unverified',
                                                       'label': 'METHOD INDEPENDENCE UNVERIFIED'})
        receipt = run.deliver()
    finally:
        CLASSES.pop('X-LABELLED')
    assert 'METHOD INDEPENDENCE UNVERIFIED' in receipt['labels'] and receipt['label'] == 'accepted'
    assert 'METHOD INDEPENDENCE UNVERIFIED' in run.delivered('DELIVERY.md').read_text()


def test_D02_C26_a_combining_step_inherits_the_fidelity_of_its_inputs(tmp_path, monkeypatch):
    import sys
    run = Run(tmp_path, monkeypatch)
    run.add_step('s0', ['outputs/point.json'])
    run.add_step('s1', ['outputs/value.json'], inputs=['s0:outputs/point.json'],
                 deliverables=[('d-value', 'outputs/value.json')])
    run.add_step('s2', ['outputs/report.md'], deliverables=[('d-report', 'outputs/report.md')])
    run.pin_plan()
    run.adopt('s0', 'outputs/point.json', {'point': 1, 'value': 41.7})
    run.adopt('s1', 'outputs/value.json', VALUE, inputs=['s0:outputs/point.json'])
    run.adopt('s2', 'outputs/report.md', REPORT, producer='worker')
    run.authority_record('approve_plan', 'approve')
    run.authority_record('final', 'accept', authorizes=False)
    run.review_round('final', {'physics-critic': (True, 'accept')})
    run.satisfy_upstream()
    monkeypatch.setitem(sys.modules, 'ravel.controller.routes.analysis.fidelity',
                        fidelity_module({'s0': 'full-simulation'}, 'fast-response'))
    assert run.deliver()['label'] == 'accepted'  # s1 assembles points simulated at the requested fidelity
    monkeypatch.setitem(sys.modules, 'ravel.controller.routes.analysis.fidelity',
                        fidelity_module({'s0': 'particle'}, 'fast-response'))
    receipt = run.deliver()
    status, evidence = statuses(run, 'D02')['s1:outputs/value.json']
    assert receipt['label'] == 'qualified' and 'particle' in evidence['reason']


def test_C22_an_adopted_default_shows_the_option_it_chose(run):
    run.complete()
    run.store.append('judgment-record', {'schema_version': 1, 'kind': 'judgment-record', 'id': 'j1', 'step': 's1',
                                         'question': 'which fictional binning', 'chosen': 'coarse',
                                         'default_option': 'coarse', 'rationale': 'the conservative default',
                                         'options': [{'id': 'coarse', 'description': 'four wide fictional bins',
                                                      'predicted_consequences': 'a wider interval'},
                                                     {'id': 'fine', 'description': 'twelve bins',
                                                      'predicted_consequences': 'sparse bins'}],
                                         'default': {'expected_sign': 'wider'}, 'class': 'R1'})
    receipt = run.deliver()
    default = receipt['judgments']['adopted_defaults'][0]
    assert default['option'] == 'four wide fictional bins' and default['predicted'] == 'a wider interval'



# ---- the receipt's architecture predicates: each is false when any of its evidence is removed ------------

def _completed(remove, **complete):
    def case(run, mp):
        run.complete(**complete)
        if remove is not None:
            remove(run, mp)
        return run.deliver()
    return case


def _drop(kind, keep=lambda record: False):
    def remove(run, mp):
        run.store.entries[:] = [e for e in run.store.entries if e['kind'] != kind or keep(e['record'])]
    return remove


def _edit(kind, change):
    def remove(run, mp):
        for entry in run.store.entries:
            if entry['kind'] == kind:
                change(entry['record'])
    return remove


def _finished_launch(change):
    return _edit('step-launch', lambda record: change(record) if record.get('phase') == 'finished' else None)


def _ledger_chain_unverified(run, mp):
    import sys
    module = sys.modules['ravel.controller.ledger']
    summary = module.summary
    mp.setattr(module, 'summary', lambda store: dict(summary(store), chain={'verified': False,
                                                                           'error': 'a fictional broken link'}))


def _owner(value):
    def remove(run, mp):
        import sys
        mp.setattr(sys.modules['ravel.controller.store'], 'controller_owned', lambda path: value)
    return remove


def _governance_fails(run, mp):
    from ravel.workflow import host_governance

    def broken(rundir, project=None, environ=None):
        raise OSError('fictional unreadable host ledger')
    mp.setattr(host_governance, 'governance_label', broken)


def _engagement_absent(run, mp):
    import sys
    mp.setitem(sys.modules, 'ravel.controller.engagement', None)


def _observed(run, mp):
    run.complete()
    return sink.observe_store(run.store)


ALL_CREDITED = {'physics-critic': (True, 'accept'), 'skeptical-verifier': (True, 'accept'),
                'physics-decider': (True, 'accept')}

# (predicate, evidence removed, case, predicates that read the same evidence)
PREDICATE_EVIDENCE = [
    ('controller_mode', 'code identity not governed', _completed(lambda run, mp: setattr(run.confine, 'kind', 'checkout')), ()),
    ('controller_mode', 'run marker names another run', _completed(
        lambda run, mp: (run.dir / 'controller-run.json').write_text(json.dumps({'run_id': 'run-fictional-other'}))), ()),
    ('controller_mode', 'request record missing', _completed(_drop('request')), ()),
    ('controller_mode', 'host governance: not controller owned', _completed(_owner(None)), ()),
    ('controller_mode', 'host governance: owned by another run', _completed(_owner('run-fictional-other')), ()),
    ('controller_mode', 'host governance unknown', _completed(_governance_fails), ()),
    ('confinement_qualified', 'launch ran unconfined', _completed(_finished_launch(lambda r: r.update(
        backend=None, plan={'kind': 'unconfined', 'label_text': 'UNCONFINED EXECUTION'}))), ()),
    ('confinement_qualified', 'denial probe qualification missing', _completed(_finished_launch(
        lambda r: r['plan'].pop('qualification'))), ()),
    ('confinement_qualified', 'denial probe not confirmed', _completed(_finished_launch(
        lambda r: r['plan']['qualification'].update(confirmed=False))), ()),
    ('confinement_qualified', 'confinement finish errors', _completed(_finished_launch(
        lambda r: r.update(confinement={'errors': ['a fictional quarantine failure']}))), ()),
    ('confinement_qualified', 'worker tool inventory missing', _completed(_edit(
        'step-observation', lambda r: r.update(tool_inventory=None))), ()),
    ('custody_chain', 'store chain does not verify', _completed(
        lambda run, mp: run.store.tampered.append('a fictional edited journal entry')), ()),
    ('custody_chain', 'ledger chain does not verify', _completed(_ledger_chain_unverified), ()),
    ('ledger_result_path', 'an obligation left pending', _completed(lambda run, mp: run.ledger.instances[next(
        k for k, i in run.ledger.instances.items() if i['id'] == 'X-UPSTREAM')].update(status='pending', evidence=None)), ()),
    ('ledger_result_path', 'the final-task decision refused', _completed(lambda run, mp: run.ledger.refuse.__setitem__(
        'final_task', [{'code': 'final_task_refused', 'provider': 'decision_gate', 'message': 'a fictional refusal'}])), ()),
    # Without the credited final review, the review-gated D03 rows stay pending in the ledger as well.
    ('review_complete', 'a final seat not credited', _completed(lambda run, mp: run.review_round(
        'final', dict(ALL_CREDITED, **{'skeptical-verifier': (False, 'accept')}))), ('ledger_result_path',)),
    ('review_complete', 'the final review round missing', _completed(
        _drop('review', keep=lambda r: r['purpose'] != 'final')), ('ledger_result_path',)),
    ('review_complete', 'review evidence in same-user state', _completed(lambda run, mp: run.review_round(
        'final', ALL_CREDITED, boundary='same_user_state')), ()),
    ('instructions_acknowledged', 'an instruction unit not acknowledged', _completed(
        lambda run, mp: run.store.append('step-validation', {
            'schema_version': 1, 'step_id': 's2', 'seat': None, 'attempt': 1, 'receipt_sha256': 'f' * 64,
            'errors': [{'code': 'instruction_ack', 'errors': ['a duty unit has no checklist row']}], 'held': [],
            'labels': [], 'escalations': []})), ()),
    # The engagement envelope reads the same delivery receipt for its packet floor.
    ('instructions_acknowledged', 'the instruction delivery receipt missing', _completed(_drop('instruction-delivery')),
     ('engagement_complete',)),
    ('authority_recorded', 'the final authority record missing', _completed(
        _drop('authority', keep=lambda r: r['kind'] != 'final')), ()),
    ('authority_recorded', 'the plan approval missing', _completed(
        _drop('authority', keep=lambda r: r['kind'] != 'approve_plan')), ()),
    ('authority_recorded', 'the operating mode record missing', _completed(_drop('mode')), ()),
    ('engagement_complete', 'the engagement decision missing', _completed(_drop('engagement-decision')), ()),
    ('engagement_complete', 'a dispatched seat without its session', _completed(lambda run, mp: run.store.append(
        'step-dispatch', {'schema_version': 1, 'step_id': 'final_review', 'seat': 'physics-critic', 'attempt': 1,
                          'node_id': 'controller:final_review:physics-critic', 'packet_sha256': 'c' * 64,
                          'packet_tokens': 100})), ('instructions_acknowledged',)),
    ('engagement_complete', 'transport usage unreported', _completed(_edit(
        'step-observation', lambda r: r.update(usage={'reported': False}))), ()),
    ('engagement_complete', 'no ready envelope projection', _completed(
        lambda run, mp: run.engagement.decide(run.store, expected={'status': 'stale'})), ()),
    ('engagement_complete', 'the engagement policy absent', _completed(_engagement_absent), ()),
    # An observation renders nothing, decides nothing and checks no envelope.
    ('sink_rendered', 'no delivery was rendered', _observed, ('ledger_result_path', 'engagement_complete')),
    ('accepted_delivery', 'an untraced table number', _completed(None, report=REPORT + '| fictional extra | 99.9 |\n'), ()),
]


@pytest.mark.parametrize('predicate, evidence, case, shared', PREDICATE_EVIDENCE,
                         ids=[f'{p}: {e}' for p, e, *_ in PREDICATE_EVIDENCE])
def test_every_receipt_predicate_is_false_when_its_evidence_is_removed(run, monkeypatch, predicate, evidence, case,
                                                                       shared):
    from ravel.controller.sink import receipts
    receipt = case(run, monkeypatch)
    predicates = receipt['architecture_predicates']
    assert set(predicates) == set(receipts.PREDICATES)
    assert predicates[predicate] is False, (evidence, predicates)
    assert receipt['architecture_complete'] is False and receipt['accepted'] is False
    assert receipt['label'] != 'accepted', receipt['work']['current_refusals']
    others = {k: v for k, v in predicates.items() if k not in (predicate, 'accepted_delivery', *shared)}
    assert all(others.values()), (evidence, others)


def test_every_receipt_predicate_has_its_evidence_cases():
    from ravel.controller.sink import receipts
    assert {p for p, *_ in PREDICATE_EVIDENCE} == set(receipts.PREDICATES)


def test_the_full_evidence_run_meets_every_predicate(run):
    run.complete()
    receipt = run.deliver()
    assert all(receipt['architecture_predicates'].values()), receipt['architecture_predicates']
    assert receipt['architecture_complete'] is True and receipt['label'] == 'accepted' and receipt['accepted'] is True
