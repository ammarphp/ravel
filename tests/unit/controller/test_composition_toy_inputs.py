"""Declared composition toy files pass real adapters and expose planted defects."""
import builtins
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import subprocess

import pytest

from composition_toy_inputs import SCRIPT
from ravel.workflow import run_validator_checks as checks


NORMALIZATION = 'check:physics.normalization_ledger.check'
CUTFLOW = 'check:validation.validate_cutflow'


@pytest.fixture
def toy_run(tmp_path, monkeypatch):
    namespace = {}
    exec(SCRIPT, namespace)
    metadata, files = namespace['toy_inputs']('toy-selection', 'prepare', 1)
    root = tmp_path / 'run'
    prefix = root / 'steps/prepare/attempts/1/outputs'
    for relative, content in files.items():
        target = prefix / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content)
    original = builtins.__import__

    def forbid_yoda(name, *args, **kwargs):
        if name == 'yoda' or name.startswith('yoda.'):
            raise AssertionError('The measured JSON composition fixture must not import YODA')
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', forbid_yoda)
    return root, metadata, tmp_path / 'workspace'


def run_adapter(toy_run, check_id):
    root, metadata, workspace = toy_run
    value = checks.RunCheckInput(root, {'check_inputs': metadata['validator_inputs']}, workspace)
    return checks.run(check_id, value)


def input_path(toy_run, check_id, key):
    root, metadata, _ = toy_run
    return root / metadata['validator_inputs'][check_id][key]


def test_declared_toy_inputs_pass_real_normalization_and_cutflow_adapters(toy_run):
    normalization = run_adapter(toy_run, NORMALIZATION)
    cutflow = run_adapter(toy_run, CUTFLOW)
    assert normalization['status'] == cutflow['status'] == 'passed'
    assert normalization['validator_executed'] is True
    assert cutflow['validator_executed'] is True
    assert normalization['diagnostics']['passed'] is True
    assert normalization['diagnostics']['failures'] == []
    report = cutflow['diagnostics']
    assert report['verdict'] == 'PASS'
    assert report['comparison_counts'] == {'requested': 1, 'evaluated': 1, 'missing': 0}
    row, = report['rows']
    assert row['mine'] == row['pub'] == pytest.approx(.5)
    assert row['ratio'] == pytest.approx(1)
    assert row['role'] == 'driving' and row['ok'] is True
    assert row['node'].startswith('grid node')


def test_changed_delivered_yield_fails_real_normalization_recomputation(toy_run):
    path = input_path(toy_run, NORMALIZATION, 'delivered')
    delivered = json.loads(path.read_text())
    assert delivered == {'X': [1.0]}
    path.write_text(json.dumps({'X': [.5]}))
    result = run_adapter(toy_run, NORMALIZATION)
    assert result['status'] == 'failed'
    assert result['validator_executed'] is True
    assert result['diagnostics']['passed'] is False
    assert any(row['code'] == 'yield_recomputation' for row in result['diagnostics']['failures'])
    assert run_adapter(toy_run, CUTFLOW)['status'] == 'passed'


def test_consistent_changed_selection_fails_against_unchanged_reference(toy_run):
    signal = input_path(toy_run, CUTFLOW, 'signal')
    tables = input_path(toy_run, CUTFLOW, 'tables_dir')
    reference_bytes = (tables / 'grid.yaml').read_bytes()
    document = json.loads(signal.read_text())
    selected = document['regions'][0]['cuts'][-1]
    selected.update(raw=25, sumw=25, sumw2=25,
                    **{'yield': document['normalization_scale'] * 25,
                       'yield_uncertainty': document['normalization_scale'] * math.sqrt(25)})
    signal.write_text(json.dumps(document))
    result = run_adapter(toy_run, CUTFLOW)
    assert result['status'] == 'failed'
    assert result['validator_executed'] is True
    report = result['diagnostics']
    assert report['verdict'] == 'FAIL'
    assert report.get('status') != 'refused'
    row, = report['rows']
    assert row['mine'] == pytest.approx(.25)
    assert row['pub'] == pytest.approx(.5)
    assert row['ratio'] == pytest.approx(.5)
    assert row['ok'] is False
    assert report['worst_driving_mu95_impact'] == pytest.approx(.5)
    assert (tables / 'grid.yaml').read_bytes() == reference_bytes
    assert run_adapter(toy_run, NORMALIZATION)['status'] == 'passed'


@pytest.mark.parametrize(('check_id', 'key'), [
    (NORMALIZATION, 'ledger'), (NORMALIZATION, 'delivered'), (CUTFLOW, 'signal'),
])
def test_missing_declared_artifact_fails_before_validator_execution(toy_run, check_id, key):
    input_path(toy_run, check_id, key).unlink()
    result = run_adapter(toy_run, check_id)
    assert result['status'] == 'failed'
    assert result['validator_executed'] is False
    assert result['diagnostics']['error'] == 'ValueError'
    assert 'missing' in result['diagnostics']['detail']


@pytest.mark.parametrize('check_id', [NORMALIZATION, CUTFLOW])
def test_invalid_measured_artifact_cannot_pass(toy_run, check_id):
    key = 'ledger' if check_id == NORMALIZATION else 'signal'
    input_path(toy_run, check_id, key).write_text('{}')
    result = run_adapter(toy_run, check_id)
    assert result['status'] == 'failed'
    assert result['validator_executed'] is True
    if check_id == CUTFLOW:
        assert result['diagnostics']['status'] == 'refused'
        assert result['diagnostics']['reason'] == 'cutflow_input_invalid'
        assert result['diagnostics']['verdict'] == 'FAIL'
        assert result['diagnostics']['rows'] == []
    else:
        assert result['diagnostics']['error'] == 'ValueError'


def test_missing_reference_cannot_certify_changed_or_unchanged_selection(toy_run):
    (input_path(toy_run, CUTFLOW, 'tables_dir') / 'submission.yaml').unlink()
    result = run_adapter(toy_run, CUTFLOW)
    assert result['status'] == 'failed'
    report = result['diagnostics']
    assert report['verdict'] == 'FAIL'
    assert report['comparison_counts'] == {'requested': 1, 'evaluated': 0, 'missing': 1}
    row, = report['rows']
    assert row['pub'] is None and row['ratio'] is None
    assert row['ok'] is False


@pytest.fixture
def waypoint_attempts(tmp_path):
    """Exercise the declared launch argv in the same attempt/output layout as the controller."""
    import test_composition_wave_b as wave_b

    root = tmp_path / 'waypoint-run'
    attempts = []
    document = {'kind': 'inert-waypoint', 'expectation': 'half of the fictional signal passes'}
    for attempt in (1, 2):
        outputs = root / f'steps/{wave_b.WAYPOINT}/attempts/{attempt}/outputs'
        outputs.mkdir(parents=True)
        launch = wave_b._launch(wave_b.WAYPOINT, {'outputs/waypoint.json': document})
        subprocess.run(launch['argv'], cwd=outputs, check=True, capture_output=True, text=True,
                       timeout=30)
        source = outputs / 'waypoint.json'
        attempts.append((source, json.loads(source.read_text())))
    return root, attempts


def test_waypoint_writer_corrects_uncertainty_from_real_enumerated_rows(waypoint_attempts):
    root, attempts = waypoint_attempts
    first, corrected = [document for _, document in attempts]
    assert 'uncertainty' not in first and 'uncertainty_basis' not in first
    assert [document['attempt'] for _, document in attempts] == [1, 2]
    assert first['execution'] != corrected['execution']
    for source, document in attempts:
        ledger = json.loads((source.parent / 'validation/normalization-ledger.json').read_text())
        cutflow = json.loads((source.parent / 'validation/cutflow.json').read_text())
        assert ledger['generated'] == {'sumw': 100, 'sumw2': 100}
        assert ledger['selected']['X'] == {'sumw': [50], 'sumw2': [50]}
        cuts = cutflow['regions'][0]['cuts']
        assert [row['raw'] for row in cuts] == [100, 50]
        assert (root / document['validator_inputs'][CUTFLOW]['signal']).is_file()
    fraction = cuts[-1]['raw'] / cuts[0]['raw']
    assert corrected['uncertainty'] == pytest.approx(math.sqrt(fraction * (1 - fraction) / cuts[0]['raw']))
    assert corrected['uncertainty_basis'] == 'binomial standard error for 50 selected of 100 unit-weight rows'


@pytest.fixture
def waypoint_reviews(waypoint_attempts):
    import test_composition_wave_b as wave_b
    from ravel.controller import instructions
    from ravel.workflow import review_projection, role_registry

    root, attempts = waypoint_attempts
    card = role_registry.load(wave_b.CI2_SEAT)
    step = {'id': wave_b.CI2_STEP, 'kind': 'review'}
    instruction_manifest = instructions.manifest(step, card)
    schema_id, schema = instructions.output_schema(card, instruction_manifest)
    assert schema_id == 'findings.v3'
    captured = []

    def capture_envelope(argv, record, *args, **kwargs):
        captured.append(deepcopy(record))
        return record

    namespace = {'json': json, 'Path': Path, 'content': lambda *args: None,
                 'envelope': capture_envelope}
    exec(wave_b.LAYER % (json.dumps({}), wave_b.CI2_STEP), namespace)
    reviews = []
    for source, document in attempts:
        relative = source.relative_to(root).as_posix()
        projection, files = review_projection.build(root, card, subjects=[relative])
        subject, = [row for row in projection['artifacts'] if row['source_path'] == relative]
        projected = dict(files)[subject['path']]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == subject['source_sha256']
        assert hashlib.sha256(projected).hexdigest() == subject['sha256']
        review = namespace['content']('outputs/review.json', step, [document, projection], [])
        record = {'schema_version': 3, 'kind': 'findings', 'items': [], 'handoff': None,
                  'instruction_ack': {'manifest_sha256': instruction_manifest['sha256']},
                  'checklist': [{'unit': unit['id'], 'status': 'done',
                                 'evidence': 'final_record#/kind', 'note': None}
                                for unit in instruction_manifest['units'] if unit['kind'] == 'duty'],
                  'escalation': [], 'item_verdicts': [
                      {'item': 'uncertainty-control', 'verdict': 'pass',
                       'evidence': ['final_record#/kind'], 'note': None}]}
        namespace['envelope']([], record)
        reviews.append((source, review, captured[-1]))
    return schema, reviews


def test_waypoint_review_pins_full_severity_a_finding_and_accepts_correction(waypoint_reviews):
    from jsonschema import Draft202012Validator
    from ravel.controller import instructions

    schema, reviews = waypoint_reviews
    first_source, first_review, first_record = reviews[0]
    second_source, second_review, second_record = reviews[1]
    assert first_review['verdict'] == 'revise'
    finding, = first_review['findings']
    assert first_record['items'] == [finding]
    assert finding['severity'] == 'A'
    assert finding['code'] == 'uncertainty_missing'
    assert finding['location'] == {'path': first_source.relative_to(first_source.parents[5]).as_posix(),
                                   'pointer': '/expectation', 'line': None}
    pin = hashlib.sha256(first_source.read_bytes()).hexdigest()
    assert finding['evidence'] == ['pin:' + pin]
    assert finding['classification'] == {
        'kind': 'defect', 'artifact_sha256': pin, 'target': 'visualize.waypoint',
        'rework_evidence': 'the 50 of 100 row fraction requires its binomial standard error'}
    assert finding['classification']['artifact_sha256'] != hashlib.sha256(second_source.read_bytes()).hexdigest()
    assert first_record['item_verdicts'][0]['verdict'] == 'fail'
    assert second_review['verdict'] == 'accept'
    assert second_review['findings'] == second_record['items'] == []
    assert second_record['item_verdicts'][0]['verdict'] == 'pass'
    for _, _, record in reviews:
        assert list(Draft202012Validator(schema).iter_errors(record)) == []
        assert instructions.validate_record('findings.v3', record) == []


@pytest.mark.parametrize('missing', ['classification', 'location', 'evidence_class'])
def test_waypoint_finding_required_fields_are_enforced_by_installed_card_schema(waypoint_reviews, missing):
    from jsonschema import Draft202012Validator

    schema, reviews = waypoint_reviews
    record = deepcopy(reviews[0][2])
    del record['items'][0][missing]
    assert list(Draft202012Validator(schema).iter_errors(record))


ACCEPTANCE = 'check:validation.certify_acceptance'


@pytest.fixture(scope='module')
def installed_toy_export_step():
    """Select an installed declaration by the checks it owes, without naming its producer."""
    import test_composition_wave_b as wave_b
    from ravel.cli import _draft_route
    from ravel.controller import routes
    from ravel.controller.routes import validator_inputs as bindings

    contract, reading, _ = _draft_route(wave_b.REQUEST.decode(), None, None)
    for spec in wave_b.selection.installed_specs():
        plan = routes.compile(spec, reading, contract)
        for step in plan['steps']:
            parameters = step.get('parameters') or {}
            inputs = parameters.get('check_inputs') or {}
            exports = parameters.get('validator_exports') or {}
            refs = [inputs.get(check, {}).get(key) for check in (ACCEPTANCE, CUTFLOW)
                    for key in bindings.requirements(check)]
            if not all(isinstance(ref, dict) and ref.get('source') == 'output'
                       and ref.get('step') == step['id'] and ref.get('field')
                       and exports.get(ref.get('path'), {}).get(ref['field']) == ref.get('type')
                       for ref in refs):
                continue
            paths = {ref['path'] for ref in refs}
            if len(paths) == 1:
                assert routes.plan_errors(plan) == []
                return deepcopy(step), paths.pop()
    pytest.fail('No installed compiled producer declares the required acceptance and cutflow exports')


@pytest.fixture
def declared_layer_output(tmp_path, monkeypatch, installed_toy_export_step):
    """Run the actual inert layer and retain its files for ordinary RunStore custody."""
    import test_composition_wave_b as wave_b
    from ravel.controller.routes import validator_inputs as bindings
    from ravel.controller.step import custody
    from ravel.controller.store import RunStore

    def produce(kind, phase, renamed, *, missing=None):
        step, report_path = deepcopy(installed_toy_export_step)
        parameters = step['parameters']
        parameters['check_inputs'] = {check: parameters['check_inputs'][check]
                                      for check in (ACCEPTANCE, CUTFLOW)}
        if renamed:
            step['id'] = 'toy.export-producer'
            replacement = 'outputs/renamed-report.json'
            for fields in parameters['check_inputs'].values():
                for ref in fields.values():
                    if isinstance(ref, dict) and ref.get('source') == 'output':
                        ref.update(step=step['id'], path=replacement)
            parameters['validator_exports'] = {replacement: parameters['validator_exports'][report_path]}
            step['outputs'] = [dict(row, path=replacement) for row in step['outputs']
                               if row['path'] == report_path]
            report_path = replacement
        step['kind'] = kind
        parameters['phase'] = phase
        assert bindings.declaration_errors(step, [step], [ACCEPTANCE, CUTFLOW]) == []
        root = tmp_path / 'declared-run'
        store = RunStore.create(root, root=tmp_path / 'protected', run_id='toy-export-bindings')
        workspace = root / 'agent-work' / step['id'] / '1'
        workspace.mkdir(parents=True)
        monkeypatch.chdir(workspace)
        namespace = {'json': json, 'Path': Path, 'content': lambda *args: None,
                     'envelope': lambda *args: None}
        exec(wave_b.TOY_INPUTS, namespace)
        documents = {step['id']: {report_path: {'kind': 'inert-export-report'}}}
        exec(wave_b.LAYER % (json.dumps(documents), wave_b.CI2_STEP), namespace)
        document = namespace['content'](report_path, step, [], [])
        for relative, content in namespace['_toy_files'].items():
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        if missing is not None:
            check, key = missing
            del document['validator_inputs'][check][key]
        destination = custody.attempt_destination(step['id'], report_path, 1)
        source = root / destination
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(json.dumps(document, sort_keys=True))
        record = {'schema_version': 1, 'artifact': step['id'] + ':' + report_path,
                  'step_id': step['id'], 'attempt': 1, 'path': report_path,
                  'destination': destination, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                  'kind': 'artifact', 'owner_role': step['role'], 'producer': {'kind': 'controller'},
                  'inputs': [], 'status': 'staged'}
        record['record_id'] = store.append(custody.CUSTODY, record)
        return root, workspace, step, document, source, store, record

    return produce


def accepted_export_consumer(step, store, record):
    from ravel.controller.step import custody

    custody.accept(store, [record], 'accepted')
    consumer = deepcopy(step)
    consumer['id'] = 'toy.export-consumer'
    consumer['depends_on'] = [step['id']]
    consumer['inputs'] = [{'artifact': record['artifact']}]
    return consumer


@pytest.mark.parametrize('custody_status', ['staged', 'accepted'])
@pytest.mark.parametrize('kind,phase,renamed', [
    pytest.param('compare', 'execute', False, id='compare-execute-original'),
    pytest.param('derive', 'prepare', True, id='derive-prepare-renamed'),
    pytest.param('review', 'prepare', True, id='review-prepare-renamed'),
    pytest.param('verify', 'execute', True, id='verify-execute-renamed'),
])
def test_layer_declared_exports_resolve_and_pass_real_adapters(
        declared_layer_output, kind, phase, renamed, custody_status):
    from ravel.controller.routes import validator_inputs as bindings
    from ravel.workflow import review_projection_checks

    root, workspace, step, document, _, store, record = declared_layer_output(kind, phase, renamed)
    if custody_status == 'accepted':
        step = accepted_export_consumer(step, store, record)
    resolved, errors = bindings.resolve_inputs(step['parameters']['check_inputs'], step,
                                                run_dir=root, store=store)
    assert errors == {}
    for check in (ACCEPTANCE, CUTFLOW):
        for key in bindings.requirements(check):
            ref = step['parameters']['check_inputs'][check][key]
            assert resolved[check][key] == bindings.pointer(document, ref['field'])
            if ref['type'] == 'path':
                assert (root / resolved[check][key]).exists()
    acceptance = review_projection_checks.run_check(
        ACCEPTANCE, json.loads((root / resolved[ACCEPTANCE]['document']).read_text()))
    cutflow = checks.run(CUTFLOW, checks.RunCheckInput(root, {'check_inputs': resolved}, workspace))
    assert acceptance['status'] == cutflow['status'] == 'passed'
    assert acceptance['diagnostics']['verdict'] == cutflow['diagnostics']['verdict'] == 'PASS'
    assert cutflow['validator_executed'] is True
    assert cutflow['diagnostics']['comparison_counts'] == {'requested': 1, 'evaluated': 1, 'missing': 0}


@pytest.mark.parametrize('custody_status', ['staged', 'accepted'])
@pytest.mark.parametrize('check,key', [
    pytest.param(ACCEPTANCE, 'document', id='acceptance-document'),
    pytest.param(CUTFLOW, 'tables_dir', id='cutflow-tables-dir'),
])
def test_layer_missing_declared_field_remains_unresolved(declared_layer_output, check, key, custody_status):
    from ravel.controller.routes import validator_inputs as bindings

    root, _, step, _, _, store, record = declared_layer_output(
        'compare', 'execute', True, missing=(check, key))
    if custody_status == 'accepted':
        step = accepted_export_consumer(step, store, record)
    _, errors = bindings.resolve_inputs(step['parameters']['check_inputs'], step, run_dir=root, store=store)
    assert set(errors) == {check}
    assert errors[check]['reason'] == 'validator_source_unresolved'


@pytest.mark.parametrize('custody_status', ['staged', 'accepted'])
def test_layer_changed_declared_report_remains_byte_bound(declared_layer_output, custody_status):
    from ravel.controller.routes import validator_inputs as bindings

    root, _, step, _, source, store, record = declared_layer_output('compare', 'execute', True)
    if custody_status == 'accepted':
        step = accepted_export_consumer(step, store, record)
    _, errors = bindings.resolve_inputs(step['parameters']['check_inputs'], step, run_dir=root, store=store)
    assert errors == {}
    source.write_bytes(source.read_bytes() + b'\n')
    _, errors = bindings.resolve_inputs(step['parameters']['check_inputs'], step, run_dir=root, store=store)
    assert set(errors) == {ACCEPTANCE, CUTFLOW}
    assert all(error['reason'] == 'validator_source_changed' for error in errors.values())


def test_toy_acceptance_report_is_recomputed_with_exact_default_tolerances(toy_run):
    from ravel.validation.certification_tolerances import DEFAULTS
    from ravel.workflow import review_projection_checks

    report = json.loads(input_path(toy_run, ACCEPTANCE, 'document').read_text())
    row, = report['rows']
    assert row == {'sr': 'X', 'role': 'driving', 'mine': .5, 'pub': .5, 'events': 50,
                   'node': 'grid node (100, 1)', 'off_grid': False, 'ratio': .5 / .5}
    assert report['certification_tolerances'] == {'approved': DEFAULTS, 'effective': DEFAULTS}
    assert report['worst_driving_residual'] == abs(1 - row['mine'] / row['pub'])
    result = review_projection_checks.certify_acceptance(report)
    assert result['status'] == 'passed'
    assert result['diagnostics']['verdict'] == report['verdict']
    assert result['diagnostics']['worst_driving_residual'] == 0
    assert result['diagnostics']['regions'] == [{'sr': 'X', 'role': 'driving', 'ratio': 1., 'residual': 0., 'ok': True}]


@pytest.mark.parametrize('damage', ['mine', 'stored-ratio', 'off-grid', 'stored-verdict', 'looser-tolerance'])
def test_changed_acceptance_report_cannot_pass_recomputation(toy_run, damage):
    from ravel.workflow import review_projection_checks

    path = input_path(toy_run, ACCEPTANCE, 'document')
    report = json.loads(path.read_text())
    if damage == 'mine':
        report['rows'][0]['mine'] = .25
    elif damage == 'stored-ratio':
        report['rows'][0]['ratio'] = .5
    elif damage == 'off-grid':
        report['rows'][0]['off_grid'] = True
    elif damage == 'stored-verdict':
        report['verdict'] = 'FAIL'
    else:
        report['certification_tolerances']['effective']['driving_tol'] = .5
        report['driving_tol'] = .5
    path.write_text(json.dumps(report))
    result = review_projection_checks.certify_acceptance(json.loads(path.read_text()))
    assert result['status'] == 'failed'
    assert result['findings']
    if damage == 'mine':
        assert result['diagnostics']['verdict'] == 'FAIL'
        assert result['diagnostics']['worst_driving_residual'] == pytest.approx(.5)


def test_actual_role_declares_acceptance_document_export_and_toy_path_exists(waypoint_attempts):
    from ravel.controller.routes import validator_inputs

    root, attempts = waypoint_attempts
    step = {'id': 'visualize.waypoint', 'role': 'discrepancy-attributor', 'review': [],
            'outputs': [{'path': 'outputs/waypoint.json', 'required': True}], 'parameters': {}}
    validator_inputs.declare_role_inputs(step)
    pointer = '/validator_inputs/' + ACCEPTANCE + '/document'
    assert step['parameters']['validator_exports']['outputs/waypoint.json'][pointer] == 'path'
    assert step['parameters']['check_inputs'][ACCEPTANCE]['document'] == {
        'source': 'output', 'step': 'visualize.waypoint', 'path': 'outputs/waypoint.json',
        'field': pointer, 'type': 'path'}
    for _, document in attempts:
        target = root / document['validator_inputs'][ACCEPTANCE]['document']
        report = json.loads(target.read_text())
        assert report['rows'][0]['events'] == 50
        assert report['rows'][0]['mine'] == .5


def test_scientific_descriptors_are_derived_from_toy_rows_and_match_independent_expected(toy_run):
    import test_composition_wave_b as wave_b
    from ravel.controller.routes.study import contracts, evidence

    root, metadata, _ = toy_run
    descriptors = metadata['scientific_descriptors']
    cutflow = json.loads(input_path(toy_run, CUTFLOW, 'signal').read_text())
    selected = cutflow['regions'][0]['cuts'][-1]
    assert descriptors['P05']['covariance'] == [[selected['sumw2']]]
    assert descriptors['P05']['basis'] == ['selected_sumw:X']
    assert descriptors['P05']['population'] == ['X']
    assert descriptors['E07']['generation_settings'] == {
        'kind': 'finite_enumeration', 'rows': cutflow['regions'][0]['cuts'][0]['raw'], 'selected_rows': selected['raw']}
    assert descriptors['E13'] == {'weight_names': ['nominal'], 'reentrant': False, 'merged': False, 'single_weight': True}
    route = wave_b._documents({'steps': []})['inputs.route']['outputs/route_analysis.json']
    assert descriptors == route['scientific_expected']
    expected_rows = {'recast.smoke': set(descriptors), 'run.full': set(descriptors),
                     'visualize.waypoint': {'P05'}, 'visualize.final': {'P05'}}
    for identifier, bindings in route['scientific_bindings'].items():
        assert {binding['row'] for binding in bindings} == expected_rows[identifier]
        for binding in bindings:
            assert binding['expected'] == 'inputs.route:outputs/route_analysis.json'
            assert binding['observed'].startswith(identifier + ':outputs/')
            assert 'review' not in binding and 'entry_ids' not in binding
            row = binding['row']
            expected = evidence._projection(route, binding['expected_fields'])
            observed = evidence._projection({'scientific_descriptors': descriptors}, binding['observed_fields'])
            evidence._descriptor(expected, row)
            evidence._descriptor(observed, row)
            assert contracts.execution_errors(expected, observed) == []
    changed = deepcopy(descriptors['P05'])
    changed['covariance'] = [[25.]]
    assert contracts.quantity_errors(route['scientific_expected']['P05'], changed)


@pytest.fixture
def inert_discovery(monkeypatch):
    import test_composition_wave_b as wave_b
    requested = []
    wave_b._discovery(monkeypatch, requested)
    return wave_b, requested


@pytest.mark.parametrize('url', ['https://www.hepdata.net/search/',
                                 'https://inspirehep.net/api/literature',
                                 'https://zenodo.org/api/records'])
def test_inert_discovery_dns_passes_unmodified_public_destination_validation(inert_discovery, url):
    import ipaddress
    from ravel.workflow import acquisition_http
    destination = acquisition_http._destination(url)
    assert destination.host in url
    assert ipaddress.ip_address(destination.sockaddr[0]).is_global


@pytest.mark.parametrize('host', ['localhost', '127.0.0.1', '[::1]'])
def test_inert_discovery_preserves_production_loopback_destination_refusal(inert_discovery, host):
    from ravel.workflow import acquisition_http
    with pytest.raises(acquisition_http.DestinationRefused):
        acquisition_http._destination('https://' + host + '/private')


def test_inert_discovery_unknown_dns_is_blocked_before_any_connection(inert_discovery):
    import socket
    from ravel.workflow import acquisition_http
    with pytest.raises(socket.gaierror, match='resolves no public name'):
        socket.getaddrinfo('unserved.invalid', 443)
    with pytest.raises(acquisition_http.DestinationRefused, match='resolution failed'):
        acquisition_http._destination('https://unserved.invalid/data')


@pytest.mark.parametrize('method', ['connect', 'connect_ex'])
@pytest.mark.parametrize('family,address', [
    pytest.param('AF_INET', ('93.184.216.34', 443), id='raw-public-ipv4'),
    pytest.param('AF_INET6', ('2606:4700:4700::1111', 443), id='raw-public-ipv6'),
    pytest.param('AF_INET', ('www.hepdata.net', 443), id='served-hostname'),
])
def test_inert_discovery_blocks_all_nonloopback_socket_connection_methods(inert_discovery, family, address, method):
    import socket
    with socket.socket(getattr(socket, family), socket.SOCK_STREAM) as client:
        with pytest.raises(OSError, match='blocks nonloopback socket connections'):
            getattr(client, method)(address)


@pytest.mark.parametrize('method', ['connect', 'connect_ex'])
def test_inert_discovery_delegates_loopback_connections(inert_discovery, method):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            result = getattr(client, method)(listener.getsockname())
            assert result == (0 if method == 'connect_ex' else None)
            accepted, _ = listener.accept()
            accepted.close()


@pytest.mark.parametrize('method', ['connect', 'connect_ex'])
def test_inert_discovery_delegates_unix_connections(inert_discovery, tmp_path, method):
    import socket
    address = str(tmp_path / 'discovery.sock')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(address)
        listener.listen(1)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            result = getattr(client, method)(address)
            assert result == (0 if method == 'connect_ex' else None)
            accepted, _ = listener.accept()
            accepted.close()


def test_inert_discovery_fake_http_returns_its_declared_payload(inert_discovery):
    from ravel.workflow import acquisition_http, discovery_http
    wave_b, requested = inert_discovery
    url = f'https://www.hepdata.net/record/{wave_b.RECID}'
    acquisition_http._destination(url)
    assert discovery_http.get_json(url) == wave_b.PUBLISHED
    assert requested == [url]
