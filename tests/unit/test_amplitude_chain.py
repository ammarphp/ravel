"""Mock parent composition and adversarial signed-term custody controls."""
from copy import deepcopy
import importlib
import json
from pathlib import Path

import numpy as np
import pytest

from interference_chain_fixtures import case, pin, runners, write

# Every chain here drives in-process backend doubles through the explicit test seam.
pytestmark = pytest.mark.usefixtures('in_process_backend_seam')


def module():
    return importlib.import_module('ravel.physics.amplitude_chain')


def execute(base, monkeypatch):
    request, integration_backend, raw_backend = case(base, monkeypatch)
    parent = module().prepare(request, base / 'parent')
    result = module().run(parent, runners=runners(integration_backend, raw_backend))
    return request, parent, result, integration_backend, raw_backend


def test_missing_native_runner_holds_before_any_effect(tmp_path, monkeypatch):
    request, _, _ = case(tmp_path, monkeypatch)
    parent = module().prepare(request, tmp_path / 'parent')
    result = module().run(parent)
    assert result['status'] == 'held' and result['held_stage'] == 'integration'
    assert result['execution_authorized'] is False
    assert not (tmp_path / 'store').exists()
    assert not (tmp_path / 'parent/deliverable.json').exists()


def test_question_to_deliverable_has_real_component_operations_and_receipts(tmp_path, monkeypatch):
    request, parent, result, integration_backend, raw_backend = execute(tmp_path, monkeypatch)
    assert result['status'] == 'passed' and not result['physics_validated'] and not result['parent_task_accepted']
    record = json.loads(Path(result['deliverable']['path']).read_text())
    assert record['question'] == request['question'] and record['goal_binding'] == request['goal_binding']
    assert [r['id'] for r in record['stages']] == [r['id'] for r in module().instances()[0]['stages']]
    for stage in record['stages']:
        receipt = json.loads(Path(stage['receipt']['path']).read_text())
        assert receipt['operation'] == stage['operation'] and receipt['goal_binding'] == request['goal_binding']
        assert receipt['outputs'] and all(pin(p['path']) == p for p in receipt['outputs'])
    assert integration_backend.specs and raw_backend.calls
    assert record['three_columns']['published']['source'].startswith('Synthetic')
    assert record['three_columns']['reproduced_reference']['values']
    assert record['interference']['hypotheses']['candidate']['signs']
    assert record['inference'] != record['ablation']
    for field in ('inference', 'ablation'):
        inference = json.loads(Path(record[field]['path']).read_text())
        assert inference['mode'] == 'differential-likelihood' and inference['statistic']['origin'] == 'prescribed'
    assert record['yield_checks'] and (tmp_path / 'parent/outputs/delivery-checks.json').exists()
    projection = json.loads(Path(record['signed_binned'][0]['path']).read_text())
    assert projection['kind'] == 'binned_values'
    # The original scientific methodology remains pending without role reviews.
    assert all(s['status'] == 'pending' for s in json.loads((tmp_path / 'parent/research/protocol.json').read_text())['stages'])


@pytest.mark.parametrize('cell', ['values', 'underflow', 'overflow'])
def test_planted_interference_sign_flip_is_caught(tmp_path, monkeypatch, cell):
    _, _, result, _, _ = execute(tmp_path, monkeypatch)
    record = json.loads(Path(result['deliverable']['path']).read_text())
    prediction = Path(record['prediction']['path'])
    document = json.loads(prediction.read_text())
    term = document['streams']['candidate:interference']
    if cell == 'values':
        term[cell] = (-np.asarray(term[cell])).tolist()
    else:
        # Force a nonzero corruption even if this fixture has empty flow bins.
        term[cell] = -term[cell] if term[cell] else -1.
    altered = write(tmp_path / 'flipped.json', document)
    task = {'input': str(tmp_path / 'predictions-input.json')}
    with pytest.raises(ValueError, match='interference sign or size'):
        module().audit_interference(task, tmp_path, altered)


@pytest.mark.parametrize('fault', ['question', 'conventions', 'input', 'parent'])
def test_stale_or_incomplete_parent_cannot_dispatch(tmp_path, monkeypatch, fault):
    request, backend, raw = case(tmp_path, monkeypatch)
    if fault == 'question':
        request['question'] = 'Replace the original question.'
        with pytest.raises(ValueError, match='original question'):
            module().prepare(request, tmp_path / 'parent')
        return
    if fault == 'conventions':
        document = json.loads(Path(request['conventions']['path']).read_text())
        document['phase_convention'] = ''
        request['conventions'] = write(tmp_path / 'conventions.json', document)
        with pytest.raises(ValueError, match='phase_convention'):
            module().prepare(request, tmp_path / 'parent')
        return
    parent = module().prepare(request, tmp_path / 'parent')
    Path(request['integration' if fault == 'input' else 'goal_binding']['path'] if fault == 'input'
         else request['goal_binding']['contract']['path']).write_text('{}\n')
    with pytest.raises(ValueError):
        module().run(parent, runners=runners(backend, raw))
    assert backend.specs == [] and raw.calls == []


def test_registered_parent_lists_stages_and_component_signatures(tmp_path, monkeypatch, capsys):
    from ravel.physics import amplitude_cli
    assert amplitude_cli.main(['research-parents']) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows == module().instances()
    row = rows[0]
    assert row['kind'] == 'research-parent-instance' and row['id'] == 'interference-measurement'
    assert {'amplitude-integration', 'weighted-events', 'amplitude-predictions', 'differential-likelihood'} <= {
        s['operation'] for s in row['stages']}
    assert row['execution_authorized'] is False and row['methodology_stages']


@pytest.mark.parametrize('fault', ['units', 'edges', 'statistic', 'reference', 'states'])
def test_chain_refuses_incompatible_quantity_contract(tmp_path, monkeypatch, fault):
    request, backend, raw = case(tmp_path, monkeypatch)
    field = 'measurement' if fault in ('units', 'edges') else 'comparison' if fault == 'statistic' else 'predictions'
    doc = json.loads(Path(request[field]['path']).read_text())
    if fault == 'units': doc['measurement']['unit'] = 'pb'
    elif fault == 'edges': doc['measurement']['bin_edges'] = [0., 200., 2000.]
    elif fault == 'statistic': doc['statistic']['threshold'] = 4.
    elif fault == 'reference': doc['reference'] = 'foreign'
    else: doc['coupling_scaling']['states'] = [9]
    request[field] = write(Path(request[field]['path']), doc)
    with pytest.raises(ValueError):
        parent = module().prepare(request, tmp_path / 'parent')
        module().run(parent, runners=runners(backend, raw))
    assert not (tmp_path / 'parent/deliverable.json').exists()


@pytest.mark.parametrize('fault', ['receipt', 'output', 'source', 'block'])
def test_completed_stage_drift_does_not_replay_or_certify(tmp_path, monkeypatch, fault):
    _, parent, result, backend, raw = execute(tmp_path, monkeypatch)
    before = len(backend.specs), len(raw.calls)
    record = json.loads(Path(result['deliverable']['path']).read_text())
    stage = record['stages'][1]
    receipt = json.loads(Path(stage['receipt']['path']).read_text())
    target = stage['receipt']['path'] if fault == 'receipt' else receipt['outputs'][0]['path'] if fault == 'output' else None
    if target:
        Path(target).write_text('{}\n')
    elif fault == 'source':
        # Change only the expected source seal in the prepared manifest.
        manifest = json.loads(Path(parent['path']).read_text())
        manifest['source_pins'][0]['sha256'] = '0' * 64
        parent = write(Path(parent['path']), manifest)
    else:
        block = next((tmp_path / 'store').glob('*.ravg'))
        block.write_bytes(block.read_bytes() + b'changed')
    with pytest.raises(ValueError):
        module().run(parent, runners=runners(backend, raw))
    assert before == (len(backend.specs), len(raw.calls))


def test_finished_parent_resumes_by_verifying_receipts_only(tmp_path, monkeypatch):
    _, parent, result, backend, raw = execute(tmp_path, monkeypatch)
    before = len(backend.specs), len(raw.calls)
    again = module().run(parent, runners=runners(backend, raw))
    assert again == result and before == (len(backend.specs), len(raw.calls))


def test_program_record_signed_oracle_flip_is_caught(tmp_path, monkeypatch):
    from amplitude_fixtures import program_output
    from ravel.physics import amplitude_integration, amplitude_records
    request, _, _ = case(tmp_path, monkeypatch)
    protocol = amplitude_integration.load({'input': request['integration']['path']}, tmp_path)['protocol']
    lines = program_output(2, 3, 37, 1).decode().splitlines()
    flipped = []
    for line in lines:
        if line.lstrip().startswith('META '):
            fields = line.split()
            fields[8] = str(-float(fields[8]))
            line = ' '.join(fields)
        flipped.append(line)
    parsed = amplitude_records.parse(('\n'.join(flipped) + '\n').encode(), operation=2, draws=3, seed=37,
                                      channel=1, protocol=protocol)
    verdict = amplitude_records.oracle_check(parsed, protocol)
    assert not verdict['passed']
    assert verdict['max_relative_residual']['signal_plus_interference'] > 1.


def test_likelihood_transports_term_cross_covariances_and_actual_ablation(tmp_path, monkeypatch):
    from ravel.physics import amplitude_predictions
    from ravel.physics.inference import differential_likelihood
    _, _, result, _, _ = execute(tmp_path, monkeypatch)
    record = json.loads(Path(result['deliverable']['path']).read_text())
    ctx = amplitude_predictions.load({'input': str(tmp_path / 'predictions-input.json')}, tmp_path)
    prediction = amplitude_predictions.predict(ctx)
    parameter = ctx['doc']['coupling_scaling']['parameter']
    for name, suffixes in [('inference', ['constant', 'interference', 'pure-signal']),
                           ('ablation', ['constant', 'pure-signal'])]:
        stage = Path(record[name]['path']).parent
        _, spec = differential_likelihood.load({'input': str(stage / 'input.json')}, tmp_path)
        hypothesis, model = spec['models'][0]
        nb = len(ctx['edges']) - 1
        names = [n for n, _ in prediction['definitions']]
        indices = [names.index('candidate:' + suffix) * (nb + 2) + i for suffix in suffixes for i in range(nb)]
        expected = prediction['joint']['covariance'][np.ix_(indices, indices)]
        np.testing.assert_allclose(model.mc, expected)
        coefficients = np.array([0.7 ** next(iter(t['powers'].values())) if t['powers'] else 1. for t in hypothesis['terms']])
        projection = np.concatenate([np.eye(nb) * v for v in coefficients], axis=1)
        experimental = np.array([[1., .1], [.1, .5]])
        np.testing.assert_allclose(model.covariance({parameter: 0.7}), experimental + projection @ expected @ projection.T)
        assert len(hypothesis['terms']) == len(suffixes)


def test_unreceipted_stage_effect_is_not_replayed(tmp_path, monkeypatch):
    request, backend, raw = case(tmp_path, monkeypatch)
    parent = module().prepare(request, tmp_path / 'parent')
    held = module().run(parent)
    assert held['status'] == 'held'
    (tmp_path / 'parent/stages/integration').mkdir()
    with pytest.raises(ValueError, match='unreceipted'):
        module().run(parent, runners=runners(backend, raw))
    assert backend.specs == []


def test_file_backed_measurement_is_bound_before_integration(tmp_path, monkeypatch):
    request, backend, raw = case(tmp_path, monkeypatch)
    measured = write(tmp_path / 'data/values.json', [1., 0.6])
    write(tmp_path / 'data/covariance.json', [[1., .1], [.1, .5]])
    document = json.loads(Path(request['measurement']['path']).read_text())
    document['measurement']['values'] = {'path': 'data/values.json', 'format': 'json'}
    document['covariance'][0]['matrix'] = {'path': 'data/covariance.json', 'format': 'json'}
    request['measurement'] = write(Path(request['measurement']['path']), document)
    parent = module().prepare(request, tmp_path / 'parent')
    Path(measured['path']).write_text('[2., 0.6]\n')
    with pytest.raises(ValueError):
        module().run(parent, runners=runners(backend, raw))
    assert not backend.specs and not raw.calls


@pytest.mark.parametrize('fault', ['roster', 'cross_covariance'])
def test_incomplete_raw_roster_or_joint_covariance_cannot_be_delivered(tmp_path, monkeypatch, fault):
    request, backend, raw = case(tmp_path, monkeypatch)
    parent = module().prepare(request, tmp_path / 'parent')
    dispatch = runners(backend, raw)
    original = dispatch['weighted-events']
    def flawed(stage, **kwargs):
        result = original(stage, **kwargs)
        path = kwargs['output_dir'] / 'predictions.json'
        output = json.loads(path.read_text())
        histogram = output[request['histogram']]
        if fault == 'roster':
            histogram['streams'].pop('candidate-minus-reference')
        else:
            histogram['joint_covariance'][0][4] += .1
            histogram['joint_covariance'][4][0] += .1
        write(path, output)
        return result
    dispatch['weighted-events'] = flawed
    with pytest.raises(ValueError, match='RAW'):
        module().run(parent, runners=dispatch)
    assert not (tmp_path / 'parent/deliverable.json').exists()


def test_unprescribed_exclusion_requires_95_percent_cls(tmp_path, monkeypatch):
    request, _, _ = case(tmp_path, monkeypatch)
    measurement = json.loads(Path(request['measurement']['path']).read_text())
    measurement['statistic'].pop('verbatim')
    measurement['statistic']['toys'] = {'method': 'cls', 'n': 8, 'seed': 17, 'confidence_level': .9, 'null': 0.}
    request['measurement'] = write(Path(request['measurement']['path']), measurement)
    comparison = json.loads(Path(request['comparison']['path']).read_text())
    comparison['statistic'] = measurement['statistic']
    request['comparison'] = write(Path(request['comparison']['path']), comparison)
    with pytest.raises(ValueError, match='95% CLs'):
        module().prepare(request, tmp_path / 'parent')
