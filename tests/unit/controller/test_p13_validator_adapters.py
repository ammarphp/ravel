"""P13, CF12: the validator adapters behind the ``must_check`` ids of the registered cards.

Executable document adapters have positive, defect and unresolved controls. ML observation
readers retain failure findings but cannot authenticate a successful computation; claimed success
and unresolved evidence stay inconclusive. Items no code computes are always inconclusive. Synthetic, fictional inputs only: no model call, network, native job or
generator process. Test names carry the coverage row they close.
"""
import copy
import functools
import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/unit holds the shared fixtures

from ravel.validation import higgs_checks  # noqa: E402
from ravel.workflow import review_projection_checks as rpc, role_registry, run_validator_checks as rvc  # noqa: E402
from test_detector_calibration import acquired, parity, spec  # noqa: E402, F401
from test_higgs_owner_interfaces import engines  # noqa: E402
from test_model_authoring import UFO_FILES, gauge_record, scalar_lq, ufo_spec, zprime  # noqa: E402
from test_worker_broker import make  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[2] / 'fixtures' / 'higgs'

UFO = 'check:physics.ufo_check.check'
CHARGES = 'check:physics.model_authoring.charge_census'
GAUGE = 'check:physics.model_authoring.adjudicate_gauge_checks'
ASSUMPTIONS = 'check:validation.assumption_audit.check'
CERTIFY = 'check:validation.certify_acceptance'
PLOT = 'check:validation.plot_lint'
BUNDLE = 'check:higgs.measurement_bundle'
CLOSURE = 'check:higgs.parameterization_closure'
CROSS = 'check:higgs.cross_engine'
FIGURES, FIGURE_CONTRACT, CENSUS = rvc.FIGURES_CHECK, rvc.FIGURE_CONTRACT_CHECK, rvc.CENSUS_CHECK

MODEL_DOCUMENT_CHECKS = (UFO, CHARGES, GAUGE, ASSUMPTIONS, CERTIFY, PLOT)
HIGGS_DOCUMENT_CHECKS = (BUNDLE, CLOSURE, CROSS)
RUN_CHECKS = (*rvc.CALIBRATION_SPEC_CHECKS, *rvc.CALIBRATION_RECEIPT_CHECKS, FIGURES, FIGURE_CONTRACT, CENSUS)
REVIEWER_ITEMS = (*rpc.ML_REVIEWER_ITEMS, *higgs_checks.REVIEWER_ITEMS)
DOCUMENT_CHECKS = (*MODEL_DOCUMENT_CHECKS, *HIGGS_DOCUMENT_CHECKS, *rpc.ML_RESULT_CHECKS, *REVIEWER_ITEMS)


# ---- documents ---------------------------------------------------------------------------------

def ufo(**over):
    return {'files': dict(UFO_FILES), 'spec': ufo_spec(), **over}


def ufo_python2():
    return ufo(files={**UFO_FILES, 'function_library.py': 'def f():\n    raise UFOError, "bad"\n'}, spec=None)


def ufo_field_absent():
    model = ufo_spec()
    model['fields'][0]['pdg'] = 9000099  # a field the carried UFO does not declare
    return ufo(spec=model)


def ufo_without_vertices():
    return ufo(files={k: v for k, v in UFO_FILES.items() if k != 'vertices.py'}, spec=None)


def charge_nonneutral():
    model = scalar_lq()
    model['lagrangian_terms'][0]['fields'][1] = {'field': 'vl'}
    return model


def charge_decimal():
    model = zprime()
    model['fields'][0]['hypercharge'] = 0.3333  # the census takes exact rationals
    return model


def charge_unknown_field():
    model = zprime()
    model['lagrangian_terms'][0]['fields'][0] = {'field': 'Undeclared'}
    return model


def gauge_mixing_with_a_new_field():
    return gauge_record(feynman_quad=False, pairs=[('G0', 'Z'), ('Zp', 'Z')], printed='Non diagonal')


def gauge_goldstone_mixing():
    return gauge_record(feynman_quad=False, pairs=[('GPbar', 'W'), ('GP', 'Wbar'), ('G0', 'Z')],
                        printed='Non diagonal quadratic term found')


def audit(reported=('A1',), **over):
    record = {'kind': 'assumption-audit', 'schema_version': 1, 'items': [
        {'id': 'A1', 'statement': 'first', 'severity': 9, 'controlled': False, 'locators': []},
        {'id': 'A2', 'statement': 'second', 'severity': 3, 'controlled': False, 'locators': []},
        {'id': 'A3', 'statement': 'third', 'severity': 9, 'controlled': True, 'locators': ['inputs/check.json']}]}
    return {'audit': record, 'result': {'assumptions_reported': list(reported)}, **over}


def figure_spec(**over):
    return {'figure_spec': {'x_range': [0, 10], 'y_scale': 'log', 'x_label': 'mass [GeV]', **over}}


def measurements():
    return json.loads((FIXTURES / 'measurements.json').read_text())


def parameterization():
    return json.loads((FIXTURES / 'parameterization.json').read_text())


def changed(document, edit):
    edit(document)
    return document


def without(document, key):
    del document[key]
    return document


VALID = {UFO: ufo, CHARGES: zprime, GAUGE: gauge_record, ASSUMPTIONS: audit, PLOT: figure_spec,
         BUNDLE: measurements, CLOSURE: parameterization, CROSS: engines}
# (label, check, factory): a planted defect the check must refuse, and evidence it cannot read.
DEFECT = [
    ('ufo-python2-source', UFO, ufo_python2), ('ufo-field-absent-from-model', UFO, ufo_field_absent),
    ('ufo-vertices-missing', UFO, ufo_without_vertices),
    ('charges-nonneutral-term', CHARGES, charge_nonneutral), ('charges-decimal-charge', CHARGES, charge_decimal),
    ('gauge-hermiticity-fails', GAUGE, lambda: gauge_record(feynman_herm=False)),
    ('gauge-mixing-with-a-new-field', GAUGE, gauge_mixing_with_a_new_field),
    ('assumption-left-out-of-the-result', ASSUMPTIONS, lambda: audit(reported=())),
    ('plot-malformed-spec', PLOT, lambda: figure_spec(x_range=[5, 1], y_scale='cubic')),
    ('bundle-unit-mismatch', BUNDLE, lambda: changed(measurements(), lambda d: d['rows'][0].update(unit='pb'))),
    ('bundle-mixed-masses', BUNDLE, lambda: changed(measurements(), lambda d: d['rows'][1].update(mass_gev=126.0))),
    ('bundle-duplicate-rows', BUNDLE, lambda: changed(measurements(), lambda d: d['rows'][1].update(id='R-0001'))),
    ('bundle-asymmetric-correlation', BUNDLE,
     lambda: changed(measurements(), lambda d: d.update(correlation=[[1, 0.2], [0.3, 1]]))),
    ('closure-off-the-held-out-point', CLOSURE,
     lambda: changed(parameterization(), lambda d: d['closure']['points'][0].update(values=[50.0, 50.0]))),
    ('engines-disagree', CROSS, lambda: engines(primary=2.0, independent=9.0)),
]
UNREAD = [
    ('ufo-no-sources', UFO, dict), ('ufo-empty-sources', UFO, lambda: {'files': {}}),
    ('ufo-unsafe-file-name', UFO, lambda: ufo(files={'../escape.py': 'x = 1\n'})),
    ('ufo-spec-is-no-modelspec', UFO, lambda: ufo(spec={'fields': 'oops'})),
    ('charges-no-spec', CHARGES, dict), ('charges-no-terms', CHARGES, lambda: {'fields': [], 'lagrangian_terms': []}),
    ('charges-unknown-field', CHARGES, charge_unknown_field),
    ('gauge-no-record', GAUGE, dict), ('gauge-no-verdicts', GAUGE, lambda: {'feynman': {}, 'unitary': {}}),
    ('gauge-receipt-without-record', GAUGE, lambda: {'status': 'provider_load_failed'}),
    ('assumptions-no-audit', ASSUMPTIONS, dict), ('assumptions-no-result', ASSUMPTIONS, lambda: {'audit': audit()['audit']}),
    ('assumptions-invalid-record', ASSUMPTIONS, lambda: audit(audit={'kind': 'other'})),
    ('plot-no-spec', PLOT, dict), ('plot-empty-spec', PLOT, lambda: {'figure_spec': {}}),
    ('bundle-empty', BUNDLE, dict), ('bundle-schema-invalid', BUNDLE, lambda: without(measurements(), 'rows')),
    ('bundle-correlation-unresolved', BUNDLE, lambda: changed(measurements(), lambda d: d.update(
        correlation={'path': 'correlation.json', 'format': 'json', 'bin_ids': ['R-0001', 'R-0002']}))),
    ('closure-no-held-out-points', CLOSURE, lambda: without(parameterization(), 'closure')),
    ('closure-empty', CLOSURE, dict), ('engines-empty', CROSS, dict),
]
ML_UNVERIFIED = []
for _id in rpc.ML_RESULT_CHECKS:
    _name = _id.split(':', 1)[1]
    for _verdict in ('fail', 'failed'):
        DEFECT.append((_name + '-reported-' + _verdict, _id,
                       functools.partial(lambda i, v: {'checks': {i: {'verdict': v}}}, _id, _verdict)))
    for _verdict in ('pass', 'passed', 'asserted_by_construction'):
        ML_UNVERIFIED.append((_name + '-forged-' + _verdict, _id,
                              functools.partial(lambda i, v: {'checks': {i: {'verdict': v}}}, _id, _verdict)))
    UNREAD += [(_name + '-no-verdict', _id, dict),
               (_name + '-unresolved', _id, functools.partial(lambda i: {'checks': {i: {'verdict': 'unresolved'}}}, _id)),
               (_name + '-diagnostic', _id, functools.partial(lambda i: {'checks': {i: 'diagnostic'}}, _id))]


# ---- the registry reaches every must_check id ----------------------------------------------------

def card_check_ids():
    return {(card['id'], i) for card in role_registry.all_cards()
            for i in [*card.get('must_check', []), *card.get('tools', {}).get('validators', [])]}


def test_CF12_every_card_check_id_is_allowlisted_with_an_adapter_or_a_knowledge_reference():
    rows = {row['id'] for row in rpc.allowlist()['validators']}
    runnable = set(rpc.CHECKS) | set(rvc.ADAPTERS)
    # The exact remaining set: a card naming a check no adapter runs would show up here.
    assert {i for _, i in card_check_ids() if not (i in rows and i in runnable) and not i.startswith('trap:T')} == set()


def test_CF12_every_runnable_card_check_is_permitted_for_the_card_that_names_it():
    runnable = set(rpc.CHECKS) | set(rvc.ADAPTERS)
    cards = {card['id']: card for card in role_registry.all_cards()}
    for role, check_id in sorted(card_check_ids()):
        if check_id in runnable:
            assert rpc.permitted(cards[role], check_id), (role, check_id)


@pytest.mark.parametrize('check_id', sorted({*DOCUMENT_CHECKS, *RUN_CHECKS}))
def test_CF12_each_adapter_has_one_allowlist_row_naming_the_function_that_runs(check_id):
    rows = {row['id']: row for row in rpc.allowlist()['validators']}
    assert (check_id in rpc.CHECKS) != (check_id in rvc.ADAPTERS), 'a document check and a run check never share an id'
    row = rows[check_id]
    assert row['description'].strip() and isinstance(row['roles'], list)
    function = getattr(importlib.import_module(row['module']), row['function'])
    assert callable(function)
    adapter = rpc.CHECKS.get(check_id, rvc.ADAPTERS.get(check_id))
    if not isinstance(adapter, functools.partial):
        assert function is adapter


def test_CF12_executable_document_controls_and_unverified_ml_observations_cover_their_adapters():
    executable = {*MODEL_DOCUMENT_CHECKS, *HIGGS_DOCUMENT_CHECKS} - {CERTIFY}
    observations = set(rpc.ML_RESULT_CHECKS)
    assert set(VALID) == executable
    assert {check for _, check, _ in DEFECT} == executable | observations
    assert {check for _, check, _ in UNREAD} == executable | observations
    assert {check for _, check, _ in ML_UNVERIFIED} == observations
    assert not set(VALID) & observations


# ---- document checks: valid, defective, unresolved -----------------------------------------------

@pytest.mark.parametrize('check_id', sorted(VALID))
def test_CF12_a_valid_document_passes_with_diagnostics(check_id):
    result = rpc.run_check(check_id, VALID[check_id]())
    assert result['status'] == 'passed' and result['findings'] == []
    assert result['diagnostics'], 'a pass without diagnostics earns no credit'
    assert (result['kind'], result['check_id'], result['producer']) == (rpc.CHECK_RESULT_KIND, check_id, rpc.PRODUCER)


@pytest.mark.parametrize('check_id,factory', [pytest.param(c, f, id=label) for label, c, f in DEFECT])
def test_CF12_a_planted_defect_is_refused_with_a_blocking_finding(check_id, factory):
    result = rpc.run_check(check_id, factory())
    assert result['status'] == 'failed' and result['outcome'] == 'flagged_conflict'
    assert result['findings'] and all(f['materiality'] in ('A', 'B') and f['summary'] for f in result['findings'])


@pytest.mark.parametrize('check_id,factory', [pytest.param(c, f, id=label) for label, c, f in UNREAD])
def test_CF12_missing_or_unresolved_evidence_is_never_a_pass(check_id, factory):
    result = rpc.run_check(check_id, factory())
    assert result['status'] == 'inconclusive' and result['outcome'] != 'passed'
    assert result['findings'] == [] and result['diagnostics']


@pytest.mark.parametrize('check_id', [GAUGE, CHARGES, UFO, ASSUMPTIONS, PLOT, CERTIFY, BUNDLE, CLOSURE, CROSS])
@pytest.mark.parametrize('document', [None, [], 'text', 7])
def test_CF12_a_document_of_the_wrong_kind_is_inconclusive(check_id, document):
    assert rpc.run_check(check_id, document)['status'] == 'inconclusive'


def test_CF12_the_gauge_check_accepts_a_native_receipt_and_waives_reported_goldstone_mixing():
    record = gauge_goldstone_mixing()
    waived = rpc.run_check(GAUGE, record)
    assert waived['status'] == 'passed' and waived['diagnostics']['waived']
    assert rpc.run_check(GAUGE, {'status': 'completed', 'gauge_checks': record})['status'] == 'passed'
    assert rpc.run_check(GAUGE, {'native': gauge_record(), 'extra_goldstones': ['Zp']})['status'] == 'passed'
    assert rpc.run_check(GAUGE, {'native': gauge_record(), 'extra_goldstones': 'G0'})['status'] == 'inconclusive'


def test_CF12_the_ufo_check_compares_with_the_spec_only_when_one_is_carried():
    assert rpc.run_check(UFO, ufo())['diagnostics']['spec_compared'] is True
    assert rpc.run_check(UFO, ufo(spec=None))['diagnostics']['spec_compared'] is False


def test_CF12_the_ufo_check_never_executes_the_carried_sources(tmp_path):
    marker = tmp_path / 'executed'
    source = f"open({str(marker)!r}, 'w').write('x')\n"
    rpc.run_check(UFO, ufo(files={**UFO_FILES, 'payload.py': source}, spec=None))
    assert not marker.exists()


def test_CF12_the_charge_census_takes_the_spec_bare_or_wrapped():
    bare, wrapped = rpc.run_check(CHARGES, zprime()), rpc.run_check(CHARGES, {'spec': zprime()})
    assert bare['status'] == wrapped['status'] == 'passed'
    assert {row['term'] for row in bare['diagnostics']['terms']} == {t['id'] for t in zprime()['lagrangian_terms']}


def test_CF12_an_assumption_below_the_floor_or_controlled_need_not_be_reported():
    result = rpc.run_check(ASSUMPTIONS, audit(reported=('A1',)))
    assert result['status'] == 'passed' and result['diagnostics']['uncontrolled'] == 2
    refused = rpc.run_check(ASSUMPTIONS, audit(reported=()))
    assert [f['code'] for f in refused['findings']] == ['assumption_unreported'] and 'A1' in refused['findings'][0]['summary']


def test_CF12_the_figure_spec_pass_claims_the_specification_only():
    result = rpc.run_check(PLOT, figure_spec())
    assert result['status'] == 'passed' and 'layout gate is not re-run' in result['diagnostics']['scope']


def test_CF12_the_crossfit_assertion_by_construction_leaves_computation_unverified():
    check_id = 'check:ml-crossfit-audit'
    result = rpc.run_check(check_id, {'checks': {check_id: 'asserted_by_construction'}})
    assert result['status'] == 'inconclusive' and result['outcome'] == 'computation_unverified'
    assert result['findings'] == [] and result['diagnostics']['verdict'] == 'asserted_by_construction'


@pytest.mark.parametrize('check_id,factory', [pytest.param(c, f, id=label) for label, c, f in ML_UNVERIFIED])
def test_CF12_a_claimed_ml_success_leaves_computation_unverified(check_id, factory):
    result = rpc.run_check(check_id, factory())
    assert result['status'] == 'inconclusive' and result['outcome'] == 'computation_unverified'
    assert result['findings'] == [] and result['diagnostics']


@pytest.mark.parametrize('check_id', rpc.ML_RESULT_CHECKS)
@pytest.mark.parametrize('verdict', [[], {}, 7], ids=['list', 'mapping', 'number'])
@pytest.mark.parametrize('wrapped', [False, True], ids=['direct-row', 'verdict-field'])
def test_CF12_malformed_ml_verdicts_leave_computation_unresolved(check_id, verdict, wrapped):
    row = {'verdict': verdict} if wrapped else verdict
    result = rpc.run_check(check_id, {'checks': {check_id: row}})
    assert result['status'] == 'inconclusive' and result['outcome'] != 'passed'
    assert result['findings'] == [] and result['diagnostics']


# ---- reviewer items ---------------------------------------------------------------------------------

def perfect(check_id):
    return {'checks': {check_id: {'verdict': 'pass'}}, 'status': 'passed', 'verdict': 'pass', **parameterization()}


@pytest.mark.parametrize('check_id', REVIEWER_ITEMS)
def test_CF12_reviewer_items_are_always_inconclusive_even_for_a_perfect_document(check_id):
    for document in (perfect(check_id), {}, None, []):
        result = rpc.run_check(check_id, document)
        assert result['status'] == 'inconclusive' and result['outcome'] == 'reviewer_item'
        assert result['findings'] == [] and result['diagnostics']['reason']


def test_CF12_the_higgs_reviewer_items_have_no_delegate_and_say_so_in_their_rows():
    rows = {row['id']: row for row in rpc.allowlist()['validators']}
    assert higgs_checks.REVIEWER_ITEMS == ('check:higgs.scalar_basis', 'check:higgs.theory_constraints')
    assert not set(higgs_checks.REVIEWER_ITEMS) & set(higgs_checks.DELEGATES)
    for check_id in REVIEWER_ITEMS:
        assert rows[check_id]['description'].startswith('Reviewer must_check item'), check_id
    assert all('no implementation exists' in rows[i]['description'] for i in higgs_checks.REVIEWER_ITEMS)


def test_CF12_every_remaining_higgs_delegate_resolves_to_an_existing_interface():
    assert set(higgs_checks.DELEGATES) == {BUNDLE, CLOSURE, CROSS}
    for identity, (module, function) in higgs_checks.DELEGATES.items():
        assert callable(getattr(importlib.import_module(module), function)), identity


def test_CF12_the_measurement_bundle_check_reports_the_refusal_it_read():
    result = rpc.run_check(BUNDLE, changed(measurements(), lambda d: d['rows'][0].update(unit='pb')))
    assert result['findings'][0]['summary'] == 'measurement quantity and unit differ'
    passed = rpc.run_check(BUNDLE, measurements())
    assert passed['diagnostics']['operation_check']['row_ids'] == ['R-0001', 'R-0002']


# ---- acceptance certification: recomputed from the producer's own report ------------------------------

CELLS = {'PASS': {'sra': (0.100, 100, 0.100), 'srb': (0.098, 60, 0.100)},
         'WARN': {'sra': (0.112, 100, 0.100), 'srb': (0.098, 60, 0.100)},
         'FAIL': {'sra': (0.133, 100, 0.100), 'srb': (0.098, 60, 0.100)}}
GRID_NODE = 'grid node (m_parent=100, split=10)'


def produced_report(tmp_path, monkeypatch, cells, node=GRID_NODE, off_grid=False):
    """The report the producer writes in diagnostic mode for {region: (acceptance, events, published)}."""
    from ravel.validation import certify_acceptance as producer
    acceptance = tmp_path / 'acceptance.json'
    acceptance.write_text(json.dumps({sr: {'acceptance': a, 'events': n} for sr, (a, n, _) in cells.items()}))
    monkeypatch.setattr(producer, 'published_acceff', lambda tables, region, *a, **k: (cells[region][2], node, off_grid))
    out = tmp_path / 'certification.md'
    monkeypatch.setattr(sys, 'argv', [
        'certify_acceptance', '--acceptance', str(acceptance), '--tables-dir', str(tmp_path), '--grid', 'toy_grid',
        '--m-parent', '100', '--dm', '10', '--srs', ','.join(cells), '--region-map',
        ','.join(f'{sr}={sr}' for sr in cells), '--out', str(out), '--diagnostic'])
    producer.main()
    return json.loads(out.with_suffix('.json').read_text())


def governed(report):
    """The report as an approved run records it: approved and effective controls bound beside each other."""
    effective = report['certification_tolerances']['effective']
    binding = {'schema_version': 1, 'approved': dict(effective), 'effective': dict(effective),
               'checkin1_sha256': 'a' * 64, 'approval_sha256': 'b' * 64, 'input_fingerprint': 'c' * 64, 'deviations': []}
    return {**report, 'certification_tolerances': binding}


@pytest.mark.parametrize('verdict,status', [('PASS', 'passed'), ('WARN', 'inconclusive'), ('FAIL', 'failed')])
def test_CF12_certify_acceptance_recomputes_the_verdict_the_producer_wrote(tmp_path, monkeypatch, verdict, status):
    report = governed(produced_report(tmp_path, monkeypatch, CELLS[verdict]))
    assert report['verdict'] == verdict
    result = rpc.run_check(CERTIFY, report)
    assert result['status'] == status and result['diagnostics']['verdict'] == verdict
    assert bool(result['findings']) == (status == 'failed') and result['diagnostics']['regions']


@pytest.mark.parametrize('label,cells,options', [
    ('unmatched-mass-point', CELLS['PASS'], {'node': 'NEAREST grid node (m_parent=200, split=10)'}),
    ('off-the-published-grid', CELLS['PASS'], {'off_grid': True}),
    ('dead-simulation', {'sra': (0.0, 0, 0.1)}, {}),
    ('unevaluated-driving-region', {'sra': (0.1, 100, 0.0)}, {})])
def test_CF12_certify_acceptance_fails_what_the_producer_fails(tmp_path, monkeypatch, label, cells, options):
    report = governed(produced_report(tmp_path, monkeypatch, cells, **options))
    assert report['verdict'] == 'FAIL'
    result = rpc.run_check(CERTIFY, report)
    assert result['status'] == 'failed' and result['findings'], label


def test_CF12_certify_acceptance_decides_nothing_on_a_diagnostic_report(tmp_path, monkeypatch):
    report = produced_report(tmp_path, monkeypatch, CELLS['PASS'])
    assert report['certification_tolerances']['governance'] == 'diagnostic' and report['verdict'] == 'PASS'
    result = rpc.run_check(CERTIFY, report)
    assert result['status'] == 'inconclusive' and result['outcome'] == 'diagnostic_report'


TAMPERED = {
    'yield-changed-label-kept': lambda r: r['rows'][0].update(mine=0.2, ratio=2.0),
    'ratio-changed': lambda r: r['rows'][0].update(ratio=1.5),
    'stored-verdict-flipped': lambda r: r.update(verdict='FAIL'),
    'tolerance-looser-than-approved': lambda r: r['certification_tolerances']['approved'].update(driving_tol=0.05),
    'region-demoted-to-tail': lambda r: r['rows'][1].update(role='tail'),
    'headline-tolerance-changed': lambda r: r.update(driving_tol=0.5),
    'stored-residual-changed': lambda r: r.update(worst_driving_residual=0.5),
}
UNRESOLVED_REPORT = {
    'no-binding': lambda r: r.pop('certification_tolerances'),
    'no-approved-controls': lambda r: r['certification_tolerances'].pop('approved'),
    'invalid-control': lambda r: r['certification_tolerances']['effective'].update(driving_tol=-1),
    'no-rows': lambda r: r.update(rows=[]),
    'unreadable-yield': lambda r: r['rows'][0].update(mine='x'),
    'row-without-role': lambda r: r['rows'][0].pop('role'),
}


@pytest.mark.parametrize('tamper', list(TAMPERED.values()), ids=list(TAMPERED))
def test_CF12_certify_acceptance_refuses_a_report_its_own_rows_contradict(tmp_path, monkeypatch, tamper):
    report = governed(produced_report(tmp_path, monkeypatch, CELLS['PASS']))
    assert rpc.run_check(CERTIFY, report)['status'] == 'passed'
    tamper(report)
    result = rpc.run_check(CERTIFY, report)
    assert result['status'] == 'failed' and result['findings']


@pytest.mark.parametrize('damage', list(UNRESOLVED_REPORT.values()), ids=list(UNRESOLVED_REPORT))
def test_CF12_certify_acceptance_without_its_evidence_is_never_a_pass(tmp_path, monkeypatch, damage):
    report = governed(produced_report(tmp_path, monkeypatch, CELLS['PASS']))
    damage(report)
    result = rpc.run_check(CERTIFY, report)
    assert result['status'] == 'inconclusive' and result['findings'] == []


# ---- run checks: detector calibration ----------------------------------------------------------------

def execute(root, check_id, **parameters):
    order = {'check_inputs': {check_id: parameters}} if parameters else {}
    return rvc.run(check_id, rvc.RunCheckInput(root, order, root / 'workspace'))


def write_spec(root, document, name='cal-spec.json'):
    (root / 'inputs').mkdir(exist_ok=True)
    (root / 'inputs' / name).write_text(json.dumps(document, sort_keys=True))
    return 'inputs/' + name


def target_overlap(model, root):
    pin = model['agreement_target']['reference']['pins'][0]
    model['calibration_nodes'][0]['observable'] = {'path': pin['locator'], 'sha256': pin['sha256']}


def shared_seed(model, root):
    model['held_out_nodes'][0]['seed'] = model['calibration_nodes'][0]['seed']


def unanchored_bounds(model, root):
    model['knobs'][0]['bounds'] = [0., 2.]


def imported_from_held_out(model, root):
    model['imported_calibration'] = {'source': acquired(root, 'imported-source.json', {'source': 'synthetic'}),
                                     'fitted_on': ['n4'],
                                     'response': acquired(root, 'imported.json', {'parameters': [1.2, .8]})}


def global_scalar(model, root):
    model['signal_scale'] = 1.1


def incomplete_signal_model(model, root):
    model['signal_model']['patch_parity'] = parity(root, status='failed', missing=['control'], name='checks/bad-parity.json')


CALIBRATION_DEFECT = {
    'check:calibration_target_disjoint': target_overlap, 'check:confirmation_separation': shared_seed,
    'check:anchored_bounds': unanchored_bounds, 'check:imported_calibration': imported_from_held_out,
    'check:calibration_no_global_scalar': global_scalar,
    'check:signal_model_complete_before_calibration': incomplete_signal_model}
RECEIPT = {'before': {'loss': 2.0}, 'after': {'loss': 1.0}, 'held_out_scores': [{'node': 'n4', 'loss': 1.1}],
           'response': {'parameters': [1.2, .8]}, 'n_trials': 3, 'study_trials': [{'trial': 1}, {'trial': 2}, {'trial': 3}]}


def receipt_pin(root, document, name='receipt.json'):
    """A receipt registered in custody (as an acquisition: custody reads either kind) and pinned run-relative."""
    return {'path': 'inputs/' + name, 'sha256': acquired(root, name, document)['sha256']}


def test_CF12_every_calibration_spec_check_has_a_defect_control():
    assert set(CALIBRATION_DEFECT) == set(rvc.CALIBRATION_SPEC_CHECKS)


@pytest.mark.parametrize('check_id', rvc.CALIBRATION_SPEC_CHECKS)
def test_CF12_a_valid_calibration_spec_passes_every_spec_check(spec, tmp_path, check_id):
    result = execute(tmp_path, check_id, spec=write_spec(tmp_path, spec))
    assert result['status'] == 'passed' and result['diagnostics'] and result['validator_executed'] is True


@pytest.mark.parametrize('check_id', sorted(CALIBRATION_DEFECT))
def test_CF12_a_planted_calibration_defect_is_refused(spec, tmp_path, check_id):
    CALIBRATION_DEFECT[check_id](spec, tmp_path)
    result = execute(tmp_path, check_id, spec=write_spec(tmp_path, spec))
    assert result['status'] == 'failed' and result['validator_executed'] is True
    assert result['diagnostics']['error'] == 'ValueError'


def test_CF12_candidates_outside_the_anchored_band_stay_inconclusive_until_authorised(spec, tmp_path):
    spec['knobs'][0]['values'] = [2.]
    result = execute(tmp_path, 'check:anchored_bounds', spec=write_spec(tmp_path, spec))
    assert result['status'] == 'inconclusive' and 'R3 authority' in result['diagnostics']['reason']


def test_CF12_a_scoped_approximation_is_inconclusive_until_authorised(spec, tmp_path):
    spec['signal_model'] = {'patch_parity': None, 'approximation_action': 'scoped'}
    result = execute(tmp_path, 'check:signal_model_complete_before_calibration', spec=write_spec(tmp_path, spec))
    assert result['status'] == 'inconclusive' and result['diagnostics']['approximation_pending_authority'] is True


@pytest.mark.parametrize('check_id', rvc.CALIBRATION_RECEIPT_CHECKS)
def test_CF12_a_registered_calibration_receipt_passes(spec, tmp_path, check_id):
    result = execute(tmp_path, check_id, receipt=receipt_pin(tmp_path, RECEIPT))
    assert result['status'] == 'passed' and result['diagnostics'] == {'errors': []}


@pytest.mark.parametrize('check_id', rvc.CALIBRATION_RECEIPT_CHECKS)
@pytest.mark.parametrize('missing', ['held_out_scores', 'study_trials', 'response'])
def test_CF12_a_receipt_without_its_scores_or_trials_is_refused(spec, tmp_path, check_id, missing):
    result = execute(tmp_path, check_id, receipt=receipt_pin(tmp_path, without(copy.deepcopy(RECEIPT), missing)))
    assert result['status'] == 'failed' and result['diagnostics']['error'] == 'ValueError'


@pytest.mark.parametrize('check_id', rvc.CALIBRATION_RECEIPT_CHECKS)
def test_CF12_a_receipt_the_agent_wrote_is_not_in_custody(spec, tmp_path, check_id):
    (tmp_path / 'inputs/unregistered.json').write_text(json.dumps(RECEIPT))
    pin = {'path': 'inputs/unregistered.json',
           'sha256': hashlib.sha256((tmp_path / 'inputs/unregistered.json').read_bytes()).hexdigest()}
    result = execute(tmp_path, check_id, receipt=pin)
    assert result['status'] == 'failed' and 'registered' in result['diagnostics']['detail']
    assert result['validator_executed'] is False


@pytest.mark.parametrize('check_id', [*rvc.CALIBRATION_SPEC_CHECKS, *rvc.CALIBRATION_RECEIPT_CHECKS])
def test_CF12_calibration_checks_without_their_pinned_inputs_are_never_a_pass(tmp_path, check_id):
    result = execute(tmp_path, check_id)
    assert result['status'] != 'passed' and result['validator_executed'] is False


# ---- run checks: the run-state stages and the figures ------------------------------------------------------

def run_tree(tmp_path):
    root = tmp_path / 'run'
    (root / 'inputs').mkdir(parents=True)
    (root / 'inputs/task_contract.json').write_text('{}')
    return root


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value))


def census(**rungs):
    return {'rungs': rungs}


def test_CF12_a_resource_census_with_a_succeeding_rung_passes(tmp_path):
    root = run_tree(tmp_path)
    write(root, 'inputs/resource_census.json', census(catalogue={'status': 'OK'}, archive={'status': 'EMPTY'}))
    result = execute(root, CENSUS)
    assert result['status'] == 'passed' and result['diagnostics']['status'] == 'PASS' and result['validator_executed']


@pytest.mark.parametrize('content', [None, '{not json', census(), []], ids=['absent', 'invalid-json', 'no-rungs', 'not-an-object'])
def test_CF12_a_missing_or_malformed_resource_census_is_refused(tmp_path, content):
    root = run_tree(tmp_path)
    if content is not None:
        write(root, 'inputs/resource_census.json', content)
    result = execute(root, CENSUS)
    assert result['status'] == 'failed' and result['diagnostics']['status'] == 'FAIL'


def test_CF12_the_validator_s_declared_warning_is_kept_as_its_success(tmp_path):
    root = run_tree(tmp_path)
    write(root, 'inputs/resource_census.json', census(catalogue={'status': 'EMPTY'}))
    result = execute(root, CENSUS)
    assert result['status'] == 'passed' and result['diagnostics']['status'] == 'WARN'


def test_CF12_figure_targets_are_refused_when_generation_ran_without_their_counterparts(tmp_path):
    root = run_tree(tmp_path)
    write(root, 'inputs/figure_target.json', {'targets': [{'figure_id': 'F1'}]})
    assert execute(root, FIGURE_CONTRACT)['status'] == 'passed', 'fulfilment is not yet expected before generation'
    write(root, 'outputs/sr_yields_a.json', {})
    refused = execute(root, FIGURE_CONTRACT)
    assert refused['status'] == 'failed' and 'unfulfilled target' in json.dumps(refused['diagnostics'])
    write(root, 'inputs/figure_target.json', {'targets': [{'figure_id': 'F1', 'generated_counterpart': {'path': 'plots/f1.png'}}]})
    assert execute(root, FIGURE_CONTRACT)['status'] == 'passed'


def test_CF12_a_run_without_a_figure_target_fails_the_figure_contract(tmp_path):
    result = execute(run_tree(tmp_path), FIGURE_CONTRACT)
    assert result['status'] == 'failed' and result['diagnostics']['path'] is None


@pytest.mark.parametrize('check_id,function', [(CENSUS, 'check_resource_census'), (FIGURE_CONTRACT, 'check_figure_contract')])
@pytest.mark.parametrize('status', ['N/A', 'waived-legacy'])
def test_CF12_a_run_state_status_that_decides_nothing_is_inconclusive(tmp_path, monkeypatch, check_id, function, status):
    from ravel.validation import validate_run_state
    monkeypatch.setattr(validate_run_state, function, lambda *a: (status, None, []))
    result = execute(run_tree(tmp_path), check_id)
    assert result['status'] == 'inconclusive' and result['diagnostics']['status'] == status


def figures_run(tmp_path, **over):
    root = run_tree(tmp_path)
    write(root, 'outputs/f1.png', 'png')
    write(root, 'outputs/f1.pdf', 'pdf')
    entry = {'filename': 'outputs/f1.png', 'pdf': 'outputs/f1.pdf', 'what_it_shows': 'a caption', **over}
    write(root, 'figures.json', {'n_figures': 1, 'figures': [entry]})
    return root


def test_CF12_declared_captioned_figures_that_exist_pass(tmp_path):
    result = execute(figures_run(tmp_path), FIGURES)
    assert result['status'] == 'passed' and result['diagnostics']['figures_declared'] == 1


@pytest.mark.parametrize('over', [{'filename': 'outputs/absent.png'}, {'pdf': 'outputs/absent.pdf'}],
                         ids=['png-missing', 'pdf-missing'])
def test_CF12_a_declared_figure_file_that_is_not_on_disk_is_refused(tmp_path, over):
    result = execute(figures_run(tmp_path, **over), FIGURES)
    assert result['status'] == 'failed' and 'NOT on disk' in json.dumps(result['diagnostics'])


def test_CF12_a_miscounted_figure_pack_is_refused(tmp_path):
    root = figures_run(tmp_path)
    write(root, 'figures.json', {'n_figures': 3, 'figures': [{'filename': 'outputs/f1.png', 'what_it_shows': 'caption'}]})
    assert execute(root, FIGURES)['status'] == 'failed'


def test_CF12_an_uncaptioned_figure_or_an_empty_pack_is_inconclusive(tmp_path):
    assert execute(figures_run(tmp_path, what_it_shows=None), FIGURES)['status'] == 'inconclusive'
    root = run_tree(tmp_path / 'other')
    assert execute(root, FIGURES)['status'] == 'inconclusive', 'a run with no figures.json decides nothing'
    write(root, 'figures.json', {'n_figures': 0, 'figures': []})
    assert execute(root, FIGURES)['status'] == 'inconclusive'


def test_CF12_a_named_figures_file_is_read_and_a_missing_one_is_refused(tmp_path):
    root = figures_run(tmp_path)
    write(root, 'outputs/pack.json', {'n_figures': 1, 'figures': [{'filename': 'outputs/f1.png', 'what_it_shows': 'caption'}]})
    named = execute(root, FIGURES, figures='outputs/pack.json')
    assert named['status'] == 'passed' and named['diagnostics']['figures_json'] == ['outputs/pack.json']
    absent = execute(root, FIGURES, figures='outputs/nothing.json')
    assert absent['status'] == 'failed' and absent['validator_executed'] is False
    write(root, 'outputs/list.json', [1])
    assert execute(root, FIGURES, figures='outputs/list.json')['status'] == 'failed'


# ---- through the broker: a card runs the checks it names ---------------------------------------------------

def populate_run(run):
    write(run, 'inputs/task_contract.json', {})
    write(run, 'inputs/resource_census.json', census(catalogue={'status': 'OK'}))
    write(run, 'inputs/figure_target.json', {'targets': [{'figure_id': 'F1'}]})
    write(run, 'outputs/f1.png', 'png')
    write(run, 'figures.json', {'n_figures': 1, 'figures': [{'filename': 'outputs/f1.png', 'what_it_shows': 'caption'}]})


@pytest.mark.parametrize('role,check_id', [('literature-scout', CENSUS), ('figure-critic', FIGURE_CONTRACT),
                                          ('figure-critic', FIGURES)])
def test_CF12_a_role_without_a_work_order_runs_the_run_checks_that_read_only_the_run_tree(
        tmp_path, monkeypatch, role, check_id):
    target = make(tmp_path, monkeypatch)
    target.allowed_actions.add('check run')
    populate_run(target.rundir)
    rpc.register(target, role_registry.load(role))
    reply = target.call({'call_id': 'run-check', 'action': 'check run', 'args': {'check_id': check_id}})
    assert reply['status'] == 'ok', reply
    assert json.loads((target.workspace / json.loads(reply['stdout_tail'])['result']).read_text())['status'] == 'passed'
    assert target.verify_ledger()[-1]['validator_id'] == check_id


def test_CF12_a_check_the_card_does_not_name_is_refused(tmp_path, monkeypatch):
    target = make(tmp_path, monkeypatch)
    target.allowed_actions.add('check run')
    populate_run(target.rundir)
    rpc.register(target, role_registry.load('figure-critic'))
    reply = target.call({'call_id': 'wrong-role', 'action': 'check run', 'args': {'check_id': CENSUS}})
    assert reply['status'] == 'refused' and target.verify_ledger()[-1]['validator_id'] is None


@pytest.mark.parametrize('role,check_id,factory,reply_status,written_status', [
    ('model-critic', CHARGES, zprime, 'ok', 'passed'), ('model-critic', CHARGES, charge_nonneutral, 'failed', 'failed'),
    ('model-critic', GAUGE, gauge_record, 'ok', 'passed'), ('model-critic', UFO, ufo, 'ok', 'passed'),
    ('assumption-auditor', ASSUMPTIONS, audit, 'ok', 'passed'),
    ('assumption-auditor', ASSUMPTIONS, lambda: audit(reported=()), 'failed', 'failed'),
    ('figure-critic', PLOT, figure_spec, 'ok', 'passed'), ('figure-critic', PLOT, dict, 'failed', 'inconclusive')])
def test_CF12_a_reviewer_runs_its_document_checks_through_the_broker(
        tmp_path, monkeypatch, role, check_id, factory, reply_status, written_status):
    target = make(tmp_path, monkeypatch)
    target.allowed_actions.add('check run')
    rpc.register(target, role_registry.load(role))
    (target.workspace / 'inputs/subject.json').write_text(json.dumps(factory()))
    reply = target.call({'call_id': 'document-check', 'action': 'check run',
                         'args': {'check_id': check_id, 'paths': ['inputs/subject.json']}})
    # An inconclusive result exits nonzero like a failure; the written result says which one it was.
    assert reply['status'] == reply_status, reply
    written = json.loads((target.workspace / json.loads(reply['stdout_tail'])['result']).read_text())
    assert written['status'] == written_status
    assert target.verify_ledger()[-1]['validator_id'] == check_id


def test_CF12_the_normalization_check_reads_a_pinned_ledger_and_refuses_changed_bytes(tmp_path):
    ledger = {'schema_version': 1, 'sample': 'toy', 'bin_convention': 'per-bin',
              'luminosity': {'value': 1.0, 'unit': 'pb^-1', 'source': 'the toy model'},
              'sigma': {'value': 2.0, 'unit': 'pb', 'order': 'LO', 'tool': 'toy', 'pdf': 'none', 'scales': 'none',
                        'process_basis': 'toy process', 'source': 'the toy model'},
              'generated': {'sumw': 100.0, 'sumw2': 100.0}, 'selected': {'r': {'sumw': [50.0], 'sumw2': [25.0]}}}
    pins = {}
    for name, value in (('ledger', ledger), ('delivered', {'r': [1.0]})):
        raw = json.dumps(value).encode()
        (tmp_path / 'steps').mkdir(exist_ok=True)
        (tmp_path / 'steps' / f'{name}.json').write_bytes(raw)
        pins[name] = {'path': f'steps/{name}.json', 'sha256': hashlib.sha256(raw).hexdigest()}
    check = 'check:physics.normalization_ledger.check'

    def run(options):
        return rvc.run(check, rvc.RunCheckInput(tmp_path, {'check_inputs': {check: options}}, tmp_path / 'scratch'))
    assert run(pins)['status'] == 'passed'
    assert run({k: v['path'] for k, v in pins.items()})['status'] == 'passed'   # a run-relative path still reads
    (tmp_path / 'steps' / 'delivered.json').write_text(json.dumps({'r': [2.0]}))
    changed = run(pins)
    assert changed['status'] == 'failed' and changed['validator_executed'] is False
    assert 'pin changed' in json.dumps(changed['diagnostics'])
