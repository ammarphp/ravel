"""Lineage and artifact claim checks on synthetic sibling controls."""
from copy import deepcopy
import importlib
import json

import pytest

from ravel.validation import validate_request_plan as rp
from ravel.workflow import physics_review


# Payloads contain raw observations and declared bounds, never a supplied verdict.
CASES = {
    'generation_cut_consistency': ({'generator_cuts': [{'object': 'jet', 'variable': 'pt', 'unit': 'GeV', 'lower': 12}], 'analysis_cuts': [{'object': 'jet', 'variable': 'pt', 'unit': 'GeV', 'lower': 20}]}, 'generator_cuts', [{'object': 'jet', 'variable': 'pt', 'unit': 'GeV', 'lower': 25}]),
    'downstream_settings_after_transforms': ({'required_downstream': {'shower_pdf_species': [1, 2]}, 'effective_downstream': {'shower_pdf_species': [1, 2, 3]}}, 'effective_downstream', {'shower_pdf_species': [1]}),
    'interference_size': ({'declared_powers': [2], 'terms': [{'power': 1, 'value': .01}, {'power': 2, 'value': 1}], 'max_lower_order_fraction': .1, 'sm_amplitude_on': True, 'sigma_probe': {'path': 'probe.json', 'sha256': 'a' * 64}}, 'terms', [{'power': 1, 'value': .5}, {'power': 2, 'value': 1}]),
    'measurement_applicability': ({'signal_shape': [.4, .6], 'validity_envelope': [[.3, .5], [.5, .7]]}, 'signal_shape', [.1, .9]),
    'agreement_correlation_range': ({'correlation_range': [-.5, .5], 'verdicts': [{'correlation': -.5, 'residual': .1, 'tolerance': .2}, {'correlation': .5, 'residual': .1, 'tolerance': .2}]}, 'verdicts', [{'correlation': 0, 'residual': .1, 'tolerance': .2}]),
    'per_bin_mc_precision': ({'relative_target': .2, 'reference_yields': {'bin-a': 10}, 'bins': [{'id': 'bin-a', 'sumw': 10, 'sumw2': 1, 'reference_yield': 10}]}, 'bins', [{'id': 'bin-a', 'sumw': 10, 'sumw2': 9, 'reference_yield': 10}]),
    'eft_validity': ({'cutoff': 500, 'bins': [{'id': 'bin-a', 'energy_reach': 100}], 'truncation': None, 'results': {'linear': [1], 'quadratic': [1.1]}}, 'bins', [{'id': 'bin-a', 'energy_reach': 600}]),
    'learned_selection_sculpting': ({'before': [10, 10], 'after': [5, 5], 'max_shape_distance': .05, 'independent_sample': {'path': 'sample.json', 'sha256': 'b' * 64}}, 'after', [9, 1]),
    'agreement_target_declared': ({'target': {'reference_kind': 'published_reproduction', 'pins': [{'path': 'reference.json', 'sha256': 'c' * 64}], 'quantity': 'yield', 'family': 'expected', 'nodes': ['node-a'], 'tolerance_rule': {'relative': .2}, 'noise_model_reference': {'path': 'noise.json', 'sha256': 'd' * 64}, 'recipe_pins': [{'path': 'recipe.json', 'sha256': 'e' * 64}]}}, 'target', None),
    'comparison_family_match': ({'prediction': {'quantity': 'yield', 'family': 'expected'}, 'reference': {'quantity': 'yield', 'family': 'expected'}}, 'reference', {'quantity': 'yield', 'family': 'observed'}),
    'attribution_above_noise': ({'residual': 2, 'noise_sigma': .1, 'minimum_sigma': 3}, 'residual', .1),
    'signal_model_complete_before_calibration': ({'required_components': ['sr', 'cr'], 'components': ['sr', 'cr'], 'completeness_sequence': 2, 'calibration_sequence': 3}, 'components', ['sr']),
}


def module():
    return importlib.import_module('ravel.validation.claim_checks')


@pytest.mark.parametrize('check_id', CASES)
def test_planted_violation_fires(check_id):
    clean, key, value = CASES[check_id]
    broken = deepcopy(clean)
    broken[key] = value
    result = module().evaluate_check(check_id, broken)
    assert result['status'] == 'fail'
    assert result['computed'] is True
    assert result['detail']


@pytest.mark.parametrize('check_id', CASES)
def test_clean_sibling_passes(check_id):
    clean = CASES[check_id][0]
    assert module().evaluate_check(check_id, deepcopy(clean))['status'] == 'pass'


def plan(operation='search-statistics'):
    return {'inputs': [], 'nodes': [{'id': 'N1', 'kind': 'operation', 'operation': operation, 'status': 'available', 'fields': [], 'rung': 'none'}], 'edges': [{'from': {'ref': 'N1', 'slot': 'out'}, 'to': {'ref': 'C1', 'slot': 'deliverable'}, 'kind': 'inference', 'require': {'limits': True}}], 'claims': [{'id': 'C1', 'kind': 'finding', 'deliverable': {'artifact': 'inference'}, 'level': 'expected', 'statistic': {'definition': '95% CLs'}, 'comparison': {'target': 'none'}, 'inherits': []}]}


def test_every_registered_route_resolves():
    assert module().conformance() == []
    for name in rp.registry():
        resolved = module().resolve(plan(name))
        assert set(rp.registry()[name]['review']['checks']) <= set(resolved['nodes']['N1'])


def test_unresolved_route_fails_conformance():
    reg = deepcopy(rp.registry())
    reg['search-statistics']['review']['checks'].append('missing_machine_check')
    assert any('missing_machine_check' in e for e in module().conformance(registry=reg))
    with pytest.raises(ValueError, match='unresolved'):
        module().resolve(plan(), registry=reg)


def test_unknown_route_is_not_an_empty_success():
    with pytest.raises(ValueError, match='unresolved'):
        module().resolve(plan('unregistered-operation'))


@pytest.mark.parametrize('check_id', ['per_bin_mc_precision', 'check:per_bin_mc_precision', 'fit_alarms', 'regression/closure', 'closure@x'])
def test_host_asserted_computed_status_is_refused(tmp_path, check_id):
    evidence = tmp_path / 'values.json'
    evidence.write_text(json.dumps({'value': 1}))
    path = tmp_path / 'checks.json'
    path.write_text(json.dumps({'schema_version': 1, 'checks': [{'id': check_id, 'status': 'pass', 'evidence': [{'path': str(evidence), 'location': '/value'}], 'attempt_ids': ['attempt-a']}]}))
    with pytest.raises(ValueError, match='computed'):
        physics_review._checks(tmp_path, str(path), {'required_checks': [{'id': check_id}]}, [{'attempt_id': 'attempt-a'}])


def test_claim_kind_does_not_remove_artifact_checks():
    p = plan()
    one = module().resolve(p)['claims']['C1']
    p['claims'][0]['kind'] = 'document'
    assert module().resolve(p)['claims']['C1'] == one
    assert {'fit_alarms', 'limit_status'} <= set(one)


def test_inherited_claim_keeps_checks_and_scopes_evidence():
    p = plan()
    p['claims'].append({'id': 'C2', 'kind': 'document', 'deliverable': {'artifact': 'document'}, 'level': 'not_applicable', 'inherits': ['C1']})
    resolved = module().resolve(p)
    assert set(resolved['claims']['C1']) <= set(resolved['claims']['C2'])
    assert 'prose' in resolved['claims']['C2']


@pytest.mark.parametrize('check_id', CASES)
def test_missing_evidence_cannot_supply_a_pass(check_id):
    assert module().evaluate_check(check_id, {})['status'] != 'pass'


def test_declared_eft_truncation_is_required_when_one_result_is_missing():
    payload = deepcopy(CASES['eft_validity'][0])
    del payload['results']['quadratic']
    assert module().evaluate_check('eft_validity', payload)['status'] == 'fail'


def test_mc_precision_reports_every_failing_bin():
    payload = deepcopy(CASES['per_bin_mc_precision'][0])
    payload['bins'] *= 2
    payload['reference_yields']['bin-b'] = 1
    payload['bins'][1] = {'id': 'bin-b', 'sumw': 0, 'sumw2': 1, 'reference_yield': 1}
    result = module().evaluate_check('per_bin_mc_precision', payload)
    assert result['failing_bins'] == ['bin-b']


def test_science_envelope_refuses_planted_artifact_check(tmp_path):
    payload = deepcopy(CASES['per_bin_mc_precision'][0])
    payload['bins'][0]['sumw2'] = 9
    artifact = {'kind': 'binned_values', 'claim_evidence': {'per_bin_mc_precision': payload}}
    out = tmp_path / 'outputs'
    out.mkdir()
    (out / 'values.json').write_text(json.dumps(artifact))
    assert any('per_bin_mc_precision' in e for e in module().science_errors(tmp_path, 'quantities', [out]))


def test_per_bin_precision_cannot_hide_an_unreported_reference_bin():
    payload = deepcopy(CASES['per_bin_mc_precision'][0])
    payload['reference_yields']['bin-b'] = 1
    assert module().evaluate_check('per_bin_mc_precision', payload)['status'] == 'fail'


def test_review_journal_computes_raw_payload(tmp_path):
    payload = deepcopy(CASES['per_bin_mc_precision'][0])
    payload['bins'][0]['sumw2'] = 9
    output = tmp_path / 'values.json'
    output.write_text(json.dumps({'claim_evidence': {'per_bin_mc_precision': payload}}))
    host = tmp_path / 'checks.json'
    host.write_text(json.dumps({'schema_version': 1, 'checks': []}))
    checks, evidence = physics_review._checks(tmp_path, str(host), {'required_checks': [{'id': 'per_bin_mc_precision'}]}, [{'attempt_id': 'attempt-a', 'outputs': [str(output)]}])
    assert checks[0]['status'] == 'fail'
    assert checks[0]['attempt_ids'] == ['attempt-a']
    assert evidence


def test_artifact_payloads_cannot_be_rescued_by_an_unrelated_clean_node():
    p = plan()
    p['nodes'].append({'id': 'N2', 'kind': 'operation', 'operation': 'quantities', 'fields': []})
    broken = deepcopy(CASES['per_bin_mc_precision'][0])
    broken['bins'][0]['sumw2'] = 9
    artifacts = {'N1': {'claim_evidence': {'per_bin_mc_precision': broken}}, 'N2': {'claim_evidence': {'per_bin_mc_precision': CASES['per_bin_mc_precision'][0]}}}
    found = [r for r in module().evaluate(p, artifacts=artifacts) if r['id'] == 'per_bin_mc_precision']
    assert found and all(r['status'] == 'fail' and r['source_ref'] == 'N1' for r in found)


def test_later_clean_artifact_does_not_hide_a_planted_violation():
    p = plan()
    broken = deepcopy(CASES['attribution_above_noise'][0])
    broken['residual'] = .1
    artifacts = {'N1': [{'claim_evidence': {'attribution_above_noise': broken}}, {'claim_evidence': {'attribution_above_noise': CASES['attribution_above_noise'][0]}}]}
    found = [r for r in module().evaluate(p, artifacts=artifacts) if r['id'] == 'attribution_above_noise']
    assert [r['status'] for r in found] == ['fail', 'pass']


def test_target_validator_interface_dependency():
    import importlib.util
    if importlib.util.find_spec('ravel.validation.agreement_target') is None:
        pytest.xfail('awaits agreement targets')
    assert callable(importlib.import_module('ravel.validation.agreement_target').validate)


def schema_target(**overrides):
    row = {'claim_id': 'C1',
           'reference': {'kind': 'supplied', 'locator': 'supplied reference table',
                         'pins': [{'locator': 'inputs/reference.json', 'sha256': 'c' * 64}], 'recipe_pins': [], 'claim_id': None},
           'quantity': {'result': {'name': 'mu95', 'basis': 'signal_strength', 'unit': '1'},
                        'reference': {'name': 'mu95', 'basis': 'signal_strength', 'unit': '1'}},
           'conversion': None, 'family': {'reference': 'expected'},
           'nodes': {'coordinates': ['x', 'y'], 'reference_lattice': [[1.0, 1.0], [2.0, 1.0]], 'compared': [[1.0, 1.0]]},
           'tolerance_rule': {'metric': 'relative difference', 'threshold': 0.2, 'aggregation': 'per_node',
                              'definition': 'relative difference at every compared node'},
           'noise_model': {'definition': 'per-node replica spread', 'pin': None}}
    row.update(overrides)
    return row


def schema_claim(**comparison):
    return {'id': 'C1', 'kind': 'agreement', 'level': 'expected',
            'comparison': {'target': 'supplied', 'metric': 'relative difference', 'tolerance': {'max_abs': 0.2}, **comparison}}


def test_schema_shaped_target_delegates_to_the_agreement_target_validator():
    check = module().evaluate_check
    assert check('agreement_target_declared', {'target': schema_target(), 'claim': schema_claim(),
                                               'claims': [schema_claim()]})['status'] == 'pass'
    # Semantic refusal from the provider: a plan claim with no comparison target.
    refused = check('agreement_target_declared', {'target': schema_target(), 'claim': schema_claim(target='none'),
                                                  'claims': [schema_claim(target='none')]})
    assert refused['status'] == 'fail' and 'comparison target' in refused['detail']
    # Schema refusal and a record without its plan claim both fail.
    assert check('agreement_target_declared', {'target': schema_target(family={}), 'claim': schema_claim(),
                                               'claims': [schema_claim()]})['status'] == 'fail'
    assert check('agreement_target_declared', {'target': schema_target()})['status'] == 'fail'


def certificate_fixture(root, kind, report=False):
    from ravel.validation import certificates as c
    def write(name, value):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    def pinned(name):
        return {'path': name, 'sha256': c.digest(root / name)}
    context = {'analysis_id': 'synthetic-channel', 'quantity': 'yield', 'units': 'dimensionless', 'basis': {'normalization': 'selected/generated'}}
    references, comparisons = [], []
    for i, mass in enumerate((10, 20)):
        point = {**context, 'point_id': 'point-' + str(i), 'parameters': {'mass_gev': mass}, 'reference_id': 'reference-' + str(i)}
        references.append(c.measurement(point, 1, quantity='yield'))
        write('outputs/pred-' + str(i) + '.json', {'validation_point': c.measurement(point, 1, quantity='yield')})
        comparisons.append({'point_id': point['point_id'], 'parameters': point['parameters'], 'reference_id': point['reference_id'], 'prediction': {'path': 'outputs/pred-' + str(i) + '.json', 'record_pointer': '/validation_point'}, 'reference': {'path': 'inputs/reference.json', 'record_pointer': '/points/' + str(i)}})
    write('inputs/reference.json', {'points': references})
    for row in comparisons:
        row['reference']['sha256'] = c.digest(root / 'inputs/reference.json')
    write('inputs/selection.json', {'selection': 'frozen'})
    write('outputs/subject.json', {'quantity': 'yield', 'value': 1})
    subjects = ['outputs/subject.json']
    if report:
        # A synthetic per-run acceptance report; the caller stubs its approval binding.
        write('outputs/acceptance-report.json', {'rows': [], 'grid': 'toy', 'splitting': 10, 'driving_tol': .1,
              'certification_tolerances': {'effective': {'driving_tol': .1}}})
        subjects.append('outputs/acceptance-report.json')
    plan_path = 'inputs/' + kind + '-plan.json'
    write(plan_path, {'schema_version': 1, 'kind': kind, **context, 'policy': {'claim': 'central-value', 'relative_tolerance': .1}, 'dependencies': [pinned('inputs/selection.json')], 'subjects': subjects, 'comparisons': comparisons})
    c.create_certificate(root, plan_path, 'outputs/' + kind + '-certificate.json')
    contract = {'targets': {'analysis': ['synthetic-channel']}, 'certification_plans': {kind: pinned(plan_path)}}
    from ravel.workflow import execution
    proposal = {'stage_binding': {'input_snapshot': execution.snapshot(root, [plan_path, 'inputs/reference.json', 'inputs/selection.json'])}}
    return contract, proposal


@pytest.mark.parametrize('kind', ['acceptance', 'r5'])
def test_science_certificate_rejects_an_unapproved_comparison_plan(tmp_path, monkeypatch, kind):
    from ravel.validation import certificates as c
    from ravel.workflow import science
    contract, proposal = certificate_fixture(tmp_path, kind)
    proposal['stage_binding']['input_snapshot'].pop(str(tmp_path / ('inputs/' + kind + '-plan.json')))
    monkeypatch.setattr(science, 'verify_plan', lambda *a, **kw: proposal)
    checked = c.validate_certificate(tmp_path, 'outputs/' + kind + '-certificate.json', kind=kind, contract=contract, required_subjects=['outputs/subject.json'], live=True, science_envelope=True)
    assert checked['status'] == 'FAIL' and 'pinned science input' in str(checked['errors'])


@pytest.mark.parametrize('kind', ['acceptance', 'r5'])
def test_science_certificate_clean_pinned_sibling(tmp_path, monkeypatch, kind):
    from ravel.validation import certificates as c
    from ravel.workflow import science
    contract, proposal = certificate_fixture(tmp_path, kind)
    monkeypatch.setattr(science, 'verify_plan', lambda *a, **kw: proposal)
    checked = c.validate_certificate(tmp_path, 'outputs/' + kind + '-certificate.json', kind=kind, contract=contract, required_subjects=['outputs/subject.json'], live=True, science_envelope=True)
    assert checked['status'] == 'PASS', checked


def test_review_acceptance_recomputes_undeclared_artifact_failure(tmp_path):
    payload = deepcopy(CASES['learned_selection_sculpting'][0])
    payload['after'] = [9, 1]
    output = tmp_path / 'values.json'
    output.write_text(json.dumps({'claim_evidence': {'learned_selection_sculpting': payload}}))
    checks = physics_review.computed_checks({'receipts': [{'outputs': [str(output)]}]})
    assert any(c['id'] == 'learned_selection_sculpting' and c['status'] == 'fail' for c in checks)


@pytest.mark.parametrize('check_id', CASES)
def test_invalid_numeric_aliases_and_missing_payload_do_not_pass(check_id):
    assert module().evaluate_check(check_id, {'status': 'pass', 'computed': True})['status'] == 'fail'


def test_delivery_cannot_relax_declared_precision_bounds():
    p = plan()
    p['nodes'][0]['fields'] = [{'pointer': '/task/claim_checks/per_bin_mc_precision', 'value': {'relative_target': .1}}]
    raw = deepcopy(CASES['per_bin_mc_precision'][0])
    raw['bins'][0]['sumw2'] = 4
    artifacts = {'N1': {'claim_evidence': {'per_bin_mc_precision': raw}}}
    rows = [r for r in module().evaluate(p, artifacts=artifacts) if r['id'] == 'per_bin_mc_precision']
    assert rows[0]['status'] == 'fail' and 'approved plan' in rows[0]['detail']


def test_completed_science_packet_refuses_a_planted_row(tmp_path, monkeypatch):
    from ravel.workflow import science, execution, review_enforcement
    from ravel.validation import validate_checkin
    out = tmp_path / 'outputs'
    out.mkdir()
    (tmp_path / 'inputs').mkdir()
    proposal = {'mode': 'quantities', 'max_seconds': 1, 'stages': [{'outputs': ['outputs']}]}
    (tmp_path / science.PLAN).write_text(json.dumps(proposal))
    (tmp_path / science.APPROVAL).write_text('{}')
    (tmp_path / 'execution_attempt.json').write_text(json.dumps({'attempt': 1, 'plan_sha256': execution.file_hash(tmp_path / science.PLAN), 'budget_seconds': 1}))
    payload = deepcopy(CASES['per_bin_mc_precision'][0])
    payload['bins'][0]['sumw2'] = 9
    result = {'status': 'passed', 'physics_validated': False, 'claim_evidence': {'per_bin_mc_precision': payload}}
    (out / 'result.json').write_text(json.dumps(result))
    (out / 'verification.json').write_text(json.dumps({'passed': True, 'scope': 'quantities', 'physics_validated': False, 'expert_review': False, 'result_sha256': execution.file_hash(out / 'result.json')}))
    (out / 'checkin2.json').write_text('{}')
    monkeypatch.setattr(science, 'verify_plan', lambda *a, **kw: proposal)
    monkeypatch.setattr(execution, 'load_execution', lambda *a, **kw: {'stages': {}})
    monkeypatch.setattr(execution, 'validate_completed_execution', lambda *a, **kw: [])
    monkeypatch.setattr(validate_checkin, 'validate', lambda *a, **kw: [])
    monkeypatch.setattr(review_enforcement, 'delivery_errors', lambda *a, **kw: [])
    packet = science._packet_v1(tmp_path)
    assert packet['lifecycle_verdict'] == 'FAIL'
    assert any('per_bin_mc_precision' in e for e in packet['errors'])


def selection_plan(level='detector', origin='published'):
    p = plan()
    p['inputs'] = [{'id': 'I1', 'source': 'published', 'provides': {'kind': 'selection', 'require': {'origin': origin}}}, {'id': 'I2', 'source': 'requester', 'provides': {'kind': 'event_sample', 'require': {'level': level}}}]
    p['nodes'].insert(0, {'id': 'N2', 'kind': 'operation', 'operation': 'analyze', 'fields': []})
    p['edges'] += [{'from': {'ref': 'I1', 'slot': 'out'}, 'to': {'ref': 'N2', 'slot': 'routine'}, 'kind': 'selection', 'require': {'origin': origin}}, {'from': {'ref': 'I2', 'slot': 'out'}, 'to': {'ref': 'N2', 'slot': 'events'}, 'kind': 'event_sample', 'require': {'level': level}}, {'from': {'ref': 'N2', 'slot': 'histograms'}, 'to': {'ref': 'N1', 'slot': 'signal'}, 'kind': 'binned_values', 'require': {}}]
    return p


def test_withheld_reference_replaces_certificate_in_shadow_derivation():
    from ravel.workflow import intake_v2_shadow as shadow
    p = selection_plan()
    reading = {'constraints': [{'type': 'blinding', 'value': {}}], 'facts': [], 'ambiguities': []}
    nodes, _, claims = rp._index(p)
    bases = rp.computed_bases(p)
    lineage = {cid: sorted(rp.ancestors(p, cid)) for cid in claims}
    checks = shadow._checks(p, rp.registry(), nodes, claims, bases, lineage, reading=reading)[1]['C1']
    assert 'reference_withheld' in checks and 'acceptance_certificate' not in checks


def test_detector_certificate_predicate_is_independent_of_claim_kind():
    p = selection_plan()
    artifacts = {'N2': {'acceptance_anchor': {'path': 'anchor.json', 'sha256': 'f' * 64}}}
    for kind in ('finding', 'prediction', 'document', 'exclusion'):
        p['claims'][0]['kind'] = kind
        assert 'acceptance_certificate' in module().resolve(p, artifacts=artifacts)['claims']['C1']


def test_no_anchor_requires_proxy_bundle_and_particle_level_requires_routine_check():
    checks = module().resolve(selection_plan())['claims']['C1']
    assert {'designed_selection_bundle', 'per_bin_mc_precision'} <= set(checks)
    assert 'acceptance_certificate' not in checks
    particle = module().resolve(selection_plan(level='particle'))['claims']['C1']
    assert 'routine_validation' in particle and 'acceptance_certificate' not in particle


def test_missing_operation_refuses_resolution():
    p = plan()
    del p['nodes'][0]['operation']
    with pytest.raises(ValueError, match='unresolved'):
        module().resolve(p)


def test_signed_cancellation_preserves_reference_scale_precision():
    payload = deepcopy(CASES['per_bin_mc_precision'][0])
    payload['bins'][0]['sumw'] = 0
    assert module().evaluate_check('per_bin_mc_precision', payload)['status'] == 'pass'


def test_species_boolean_alias_does_not_supply_a_required_parton():
    payload = {'required_downstream': {'shower_pdf_species': [1]}, 'effective_downstream': {'shower_pdf_species': [True]}}
    assert module().evaluate_check('downstream_settings_after_transforms', payload)['status'] == 'fail'


def test_temporal_sites_are_available_to_plan_admission():
    assert module().registry()['generation_cut_consistency']['sites'] == ['before_full']
    assert module().registry()['signal_model_complete_before_calibration']['sites'] == ['before_calibration']


@pytest.mark.parametrize('kind,check_id', [('acceptance', 'acceptance_certificate'), ('r5', 'r5')])
def test_review_journal_computes_clean_bound_certificate(tmp_path, monkeypatch, kind, check_id):
    from ravel.validation import certificates as c
    from ravel.workflow import workflow_state
    from ravel.validation import certification_tolerances
    from ravel.validation.claim_checks.envelope import review_checks
    monkeypatch.setattr(certification_tolerances, 'verify_report', lambda root, document: [])
    contract, _ = certificate_fixture(tmp_path, kind, report=kind == 'acceptance')
    (tmp_path / 'inputs/task_contract.json').write_text(json.dumps(contract))
    subject = tmp_path / 'outputs/subject.json'
    subject.write_text(json.dumps({'kind': 'inference', 'claim_evidence': {check_id: {'path': 'outputs/' + kind + '-certificate.json'}}}))
    c.create_certificate(tmp_path, 'inputs/' + kind + '-plan.json', 'outputs/' + kind + '-certificate.json')
    monkeypatch.setattr(workflow_state, 'verify_approval', lambda *a, **kw: [])
    result = review_checks(tmp_path, [check_id], [{'attempt_id': 'attempt-a', 'outputs': [str(subject)]}])
    assert result[0]['status'] == 'pass'


def test_delivered_non_json_artifact_does_not_break_claim_census(tmp_path):
    from ravel.validation.claim_checks.envelope import _outputs
    image = tmp_path / 'view.png'
    image.write_bytes(b'synthetic image sibling')
    record = tmp_path / 'values.json'
    record.write_text(json.dumps({'value': 1}))
    assert _outputs([image, record]) == [(str(record), {'value': 1})]
    with pytest.raises(ValueError, match='missing'):
        _outputs([tmp_path / 'missing.png'])


@pytest.mark.parametrize('mode', ['ml-training', 'lhe-transform'])
def test_legacy_envelope_route_alone_does_not_demand_unproduced_evidence(tmp_path, mode):
    out = tmp_path / 'outputs'
    out.mkdir()
    (out / 'result.json').write_text(json.dumps({'kind': 'table', 'value': 1}))
    assert module().science_errors(tmp_path, mode, [out]) == []


@pytest.mark.parametrize('declared,check_id', [({'selection_origin': 'learned'}, 'learned_selection_sculpting'), ({'required_downstream': {'pdf': 1}}, 'downstream_settings_after_transforms')])
def test_legacy_envelope_declared_context_still_requires_evidence(tmp_path, declared, check_id):
    out = tmp_path / 'outputs'
    out.mkdir()
    (out / 'result.json').write_text(json.dumps({'kind': 'table', **declared}))
    assert any(check_id in e for e in module().science_errors(tmp_path, 'quantities', [out]))
