"""Fictional cost observations only; no scientific or provider launches."""
from copy import deepcopy
import json

import pytest
from ravel.workflow import cost_preflight as preflight, pilot_cost

DIMS = ('wall_hours', 'cpu_hours', 'peak_ram_gb', 'disk_gb', 'events', 'model_calls', 'model_tokens', 'queue_hours')


def profile():
    return {'process': 'fictional-process', 'configuration': 'fictional-config', 'machine': pilot_cost.machine_identity()}


def test_unknown_never_zero_and_rendered_unknown():
    from ravel.workflow.cost_records import render, resource_vector
    value = preflight.estimate('full', 2, 10, 'native', 1)
    assert value['status'] == 'uncalibrated'
    assert value['resource_vector'] == resource_vector(events=20)
    assert value['wall_hours'] is None
    assert 'wall_hours: unknown' in render(value)
    assert set(value['resource_vector']) == set(DIMS)


def test_historical_is_not_calibration():
    value = preflight.historical_reference_estimate('full', 1, 100, 'native', 1)
    assert value['status'] == 'historical'
    assert value['profile']['machine'] is None
    assert value['resource_vector']['cpu_hours'] is None


@pytest.mark.parametrize('family,method,rung', [
    ('explanation', 'direct_explanation', 0),
    ('reinterpretation', 'existing_result', 0),
    ('estimate_theory', 'analytic_estimate', 1),
    ('supplied_events', 'new_generation', 4),
    ('reinterpretation', 'justified_scan', 4),
    ('open_research', 'small_prospective_experiment', 2),
])
def test_six_request_shapes_and_cheaper_alternatives(family, method, rung):
    from ravel.workflow.cost_records import make_record
    p = profile()
    fictional = make_record(method, 'historical', p, 'Fictional measured reference.', wall_hours=2, cpu_hours=5)
    cheaper = {'explanation': 'direct_explanation', 'reinterpretation': 'existing_result',
               'estimate_theory': 'standard_value', 'supplied_events': 'reuse_derived_quantities',
               'open_research': 'source_assessment'}[family]
    decision = {'family': family, 'selected': {'method': method, 'rung': rung},
                'alternatives': [{'method': cheaper, 'rung': 0}] if rung else []}
    study = {'cost_profiles': {method: p, cheaper: p},
             'cost_records': {method: fictional, cheaper: make_record(cheaper, 'historical', p, 'Fictional.', wall_hours=1)}}
    study['cost_records'][method] = fictional
    result = preflight.forecast_for(decision, study)
    assert result['cost_class'] == method
    assert result['status'] == 'historical'
    assert result['wall_hours'] == 2 and result['cpu_hours'] == 5
    assert 'total' not in result and 'total' not in result['resource_vector']
    assert len(result['alternatives']) == bool(rung)


@pytest.mark.parametrize('key', ['process', 'configuration', 'machine'])
def test_forecast_refuses_mismatched_profile(key):
    from ravel.workflow.cost_records import make_record
    p = profile(); other = deepcopy(p); other[key] = 'different'
    decision = {'family': 'explanation', 'selected': {'method': 'direct_explanation', 'rung': 0}, 'alternatives': []}
    with pytest.raises(ValueError, match='profile'):
        preflight.forecast_for(decision, {'cost_profiles': {'direct_explanation': p},
            'cost_records': {'direct_explanation': make_record('direct_explanation', 'historical', other, 'Fictional.', wall_hours=1)}})


def test_missing_forecast_stays_unknown():
    decision = {'family': 'fit_measurement', 'selected': {'method': 'native_likelihood', 'rung': 2}, 'alternatives': []}
    result = preflight.forecast_for(decision, {'max_seconds': 99})
    assert result['status'] == 'unknown'
    assert all(v is None for v in result['resource_vector'].values())


def observed(tmp_path, units, wall):
    rd = tmp_path / str(units); rd.mkdir()
    receipt = rd / 'receipt.json'
    receipt.write_text(json.dumps({'status': 'succeeded', 'started_utc': '2026-01-01T00:00:00+00:00',
                                 'finished_utc': f'2026-01-01T00:00:{wall:02d}+00:00'}))
    return {'kind': 'supervised_pilot_observation', 'rundir': str(rd), 'route': 'scoped', 'mode': 'generate',
            'unit': 'events', 'units': units, 'profile_sha256': 'f' * 64, 'wall_seconds': wall,
            'output_bytes': 1000, 'machine': pilot_cost.machine_identity(), 'plan_sha256': '0' * 64,
            'receipts': [pilot_cost._pin(receipt)]}


def test_catalogue_appends_completed_receipts_and_reads_for_forecast(tmp_path, monkeypatch):
    from ravel.workflow import cost_records
    monkeypatch.setattr(pilot_cost, 'scaling', lambda *a: ('events', 30, 'f' * 64, 'Fictional events.'))
    path = tmp_path / 'catalogue.jsonl'
    one, two = observed(tmp_path, 10, 20), observed(tmp_path, 20, 30)
    cost_records.append_observation(path, one)
    cost_records.append_observation(path, two)
    cost_records.append_observation(path, one)
    assert len(path.read_text().splitlines()) == 2
    result = pilot_cost.forecast_from_catalogue(path, {'mode': 'generate'}, route='scoped', margin=1.5)
    assert result['status'] == 'calibrated'
    assert result['uncertainty']['wall_hours'] == pytest.approx([40/3600, 90/3600])
    assert result['resource_vector']['cpu_hours'] is None
    one['receipts'][0]['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='receipt'):
        cost_records.append_observation(path, one)
    monkeypatch.setattr(pilot_cost, 'scaling', lambda *a: ('events', 30, 'x' * 64, 'Fictional.'))
    with pytest.raises(ValueError, match='profile'):
        pilot_cost.forecast_from_catalogue(path, {}, route='scoped', margin=1.5)


def test_dimensions_are_independent_and_missing_measurements_stay_unknown():
    from ravel.workflow.cost_records import aggregate_resources, resource_vector
    result = aggregate_resources([resource_vector(wall_hours=2, cpu_hours=8, peak_ram_gb=3),
                                  resource_vector(wall_hours=4, cpu_hours=9, peak_ram_gb=2)])
    assert result['wall_hours'] == 6 and result['cpu_hours'] == 17 and result['peak_ram_gb'] == 3
    assert result['model_calls'] is None and result['disk_gb'] is None
    assert aggregate_resources([]) == resource_vector()


def test_research_metrics_resource_vector_and_avoidance_remain_unknown(tmp_path):
    from test_research_outcome_metrics import fixture
    from ravel.workflow import research_cycle
    value = research_cycle.outcome_metrics(fixture(tmp_path))
    assert set(value['resource_use']['resource_vector']) == set(DIMS)
    assert value['resource_use']['resource_vector']['cpu_hours'] is None
    assert value['resource_use']['avoided_native_launches'] is None
    assert value['resource_use']['avoided_model_calls'] is None
    assert value['interventions']['human_interventions'] is None


def test_none_contract_accepts_unknown_cost_record():
    from ravel.workflow.route_prompt import route
    from ravel.validation.validate_task_contract import validate
    assert validate(route('Explain a fictional conserved quantity.')) == []


def test_avoidance_requires_evidence_and_never_infers_calls():
    from ravel.workflow.research_outcome_metrics import avoided_work
    decision = {'selected': {'rung': 0}}
    comparison = {'compared_rung': 3, 'native_launches': 4, 'model_calls': None,
                  'evidence': ['synthetic-comparison']}
    assert avoided_work(decision, comparison) == {'avoided_native_launches': 4, 'avoided_model_calls': None}
    comparison['evidence'] = []
    with pytest.raises(ValueError, match='evidenced comparison'):
        avoided_work(decision, comparison)


def test_catalogue_refuses_machine_and_receipt_mutation(tmp_path, monkeypatch):
    from ravel.workflow.cost_records import append_observation, catalogue_observations
    obs = observed(tmp_path, 10, 20); path = tmp_path / 'costs.jsonl'
    append_observation(path, obs)
    with pytest.raises(ValueError, match='another machine'):
        catalogue_observations(path, obs['profile_sha256'], {**obs['machine'], 'hostname': 'fictional-other'})
    receipt = obs['receipts'][0]['path']
    from pathlib import Path
    Path(receipt).write_text('{}')
    with pytest.raises(ValueError, match='receipt changed'):
        catalogue_observations(path, obs['profile_sha256'], obs['machine'])


def test_forecast_contract_projection_has_exact_shared_keys():
    from ravel.workflow.cost_records import make_record, contract_forecast
    result = contract_forecast(make_record('analytic_estimate', 'unknown', None, 'Unmeasured.'))
    assert set(result) == {'status', 'wall_hours', 'cpu_hours', 'disk_gb', 'events', 'model_calls', 'basis'}


def test_forecast_rejects_zero_pilot_units(monkeypatch):
    monkeypatch.setattr(pilot_cost, 'scaling', lambda *a: ('events', 30, 'f' * 64, 'Fictional.'))
    obs = {'kind': 'supervised_pilot_observation', 'rundir': '/fictional', 'profile_sha256': 'f' * 64,
           'unit': 'events', 'units': 0, 'wall_seconds': 1, 'output_bytes': 1, 'machine': pilot_cost.machine_identity()}
    with pytest.raises(ValueError, match='positive'):
        pilot_cost.forecast([obs], {}, route='scoped', margin=1.5)


def test_observe_retains_resources_and_catalogue_receipts(tmp_path, monkeypatch):
    from pathlib import Path
    from ravel.workflow.cost_records import resource_vector
    obs = observed(tmp_path, 10, 20); rd = Path(obs['rundir'])
    receipt = json.loads(Path(obs['receipts'][0]['path']).read_text())
    receipt['runtime'] = {'platform': pilot_cost.machine_identity()['platform']}
    receipt['attempt_record'] = 'receipt.json'
    receipt['resource_vector'] = resource_vector(cpu_hours=3, peak_ram_gb=2, model_calls=4)
    Path(obs['receipts'][0]['path']).write_text(json.dumps(receipt))
    (rd / 'inputs').mkdir(); (rd / 'inputs/scoped-plan.json').write_text('{}')
    (rd / 'out').write_bytes(b'fictional')
    monkeypatch.setattr(pilot_cost, '_route', lambda rd: 'scoped')
    monkeypatch.setattr(pilot_cost, '_completed', lambda *a: ({'stages': [{'stage': 'fake', 'outputs': ['out']}]}, {'mode': 'generate'}, rd))
    monkeypatch.setattr(pilot_cost, 'scaling', lambda *a: ('events', 10, 'f' * 64, 'Fictional.'))
    monkeypatch.setattr(pilot_cost.execution, 'load_execution', lambda rd: {'stages': {'fake': receipt}})
    result = pilot_cost.observe(rd, catalogue=tmp_path / 'catalogue.jsonl')
    assert result['resource_vector']['cpu_hours'] == 3
    assert result['resource_vector']['peak_ram_gb'] == 2
    assert result['resource_vector']['model_calls'] == 4
    assert result['resource_vector']['queue_hours'] is None


def test_avoidance_is_read_from_retained_decision(tmp_path):
    from test_research_outcome_metrics import fixture, add_attempts
    from ravel.workflow import research_cycle
    root = fixture(tmp_path); rd = add_attempts(tmp_path, root)
    path = rd / 'inputs/method_decision.json'
    path.write_text(json.dumps({'selected': {'rung': 0}}))
    (rd / 'inputs/method_choice_comparison.json').write_text(json.dumps({'schema_version': 1,
        'kind': 'method-choice-comparison', 'method_decision': pilot_cost._pin(path),
        'compared_rung': 2, 'native_launches': 3, 'model_calls': 1, 'evidence': ['fictional comparison']}))
    use = research_cycle.outcome_metrics(root)['resource_use']
    assert use['avoided_native_launches'] == 3 and use['avoided_model_calls'] == 1
    assert len(use['method_choice_comparisons']) == 1


def test_forecast_for_consumes_profile_matched_catalogue(tmp_path, monkeypatch):
    from ravel.workflow.cost_records import append_observation
    one = observed(tmp_path, 10, 20); catalogue = tmp_path / 'cost.jsonl'; append_observation(catalogue, one)
    monkeypatch.setattr(pilot_cost, 'scaling', lambda *a: ('events', 30, 'f' * 64, 'Fictional events.'))
    p = {'process': 'generate', 'configuration': 'f' * 64, 'machine': pilot_cost.machine_identity()}
    decision = {'family': 'reinterpretation', 'selected': {'method': 'single_point_chain', 'rung': 3}, 'alternatives': []}
    result = preflight.forecast_for(decision, {'observed_cost_catalogue': str(catalogue),
        'cost_profiles': {'single_point_chain': p},
        'cost_targets': {'single_point_chain': {'spec': {'mode': 'generate'}, 'route': 'scoped', 'margin': 1.5}}})
    assert result['status'] == 'calibrated' and result['cost_class'] == 'single_point_chain'
    assert result['wall_hours'] == pytest.approx(20/3600)


def test_failed_completed_attempt_is_retained_but_cannot_calibrate(tmp_path):
    from pathlib import Path
    from ravel.workflow.cost_records import append_observation, catalogue_observations
    one = observed(tmp_path, 10, 20)
    receipt = Path(one['receipts'][0]['path']); value = json.loads(receipt.read_text()); value['status'] = 'failed'
    receipt.write_text(json.dumps(value)); one['receipts'] = [pilot_cost._pin(receipt)]
    path = tmp_path / 'cost.jsonl'; append_observation(path, one)
    assert len(path.read_text().splitlines()) == 1
    with pytest.raises(ValueError, match='successful'):
        catalogue_observations(path, one['profile_sha256'], one['machine'])


def test_record_verification_refuses_changed_resource_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot_cost, 'scaling', lambda *a: ('events', 30, 'f' * 64, 'Fictional.'))
    obs = observed(tmp_path, 10, 20)
    result = pilot_cost.forecast([obs], {'mode': 'generate'}, route='scoped', margin=1.5)
    path = tmp_path / 'forecast.json'; path.write_text(json.dumps(result))
    rec = pilot_cost.record(path, mode='full', events_per_point=30)
    rec['profile']['configuration'] = 'another-profile'
    assert any('profile' in error for error in pilot_cost.verify_record(rec))


@pytest.mark.parametrize('status', ['calibrated', 'uncalibrated'])
def test_historical_reference_cannot_be_relabelled_in_a_contract(status):
    from ravel.workflow.route_prompt import route
    from ravel.validation.validate_task_contract import validate
    contract = route('Explain a fictional conserved quantity.')
    contract['cost_estimate']['status'] = status
    assert any('legacy calibration status' in error for error in validate(contract))
