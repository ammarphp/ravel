"""Synthetic event bytes through ordinary generation export, selection and inference."""
from copy import deepcopy
import io
import json
import math
from pathlib import Path
import tarfile

import pytest

from ravel.physics import model_events, model_event_weights, model_event_commitment
from ravel.physics import columnar_analysis, signal_templates, published_model
from ravel.physics import event_inference_contract as chain
from ravel.workflow import science


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, (dict, list)) else value)
    return chain.file_pin(path)


def events(repetitions=100):
    records = []
    for pt in (10, 30, 40) * repetitions:
        records.append(f'<event>\n3 1 1 100 .007 .1\n'
                       f'1 -1 0 0 0 0 0 0 50 50 0 0 9\n'
                       f'-1 -1 0 0 0 0 0 0 -50 50 0 0 9\n'
                       f'22 1 1 2 0 0 {pt} 0 0 {pt} 0 0 9\n</event>')
    return ('<LesHouchesEvents version="3.0"><header></header>\n<init>\n'
            '2212 2212 6500 6500 0 0 0 0 3 1\n.006 .0001 1 1\n</init>\n'
            + '\n'.join(records) + '\n</LesHouchesEvents>\n')


def generate(tmp_path, monkeypatch, repetitions=100):
    from test_model_events import config
    from ravel.physics import model_event_process, model_event_phases, model_event_source, reinterpret_db
    from ravel.validation import science_shower_guard, lhe_check
    c = config(tmp_path / 'source')
    c['generation']['events'] = 3 * repetitions
    run_path = Path(c['cards']['run']['path'])
    c['cards']['run'] = write(run_path, run_path.read_text().replace('3 = nevents', f'{3 * repetitions} = nevents'))
    config_pin = write(tmp_path / 'config.json', c)
    task = {'config': config_pin['path'], 'composition': {
        'sampling_model': 'independent_poisson_events',
        'normalization_model': 'fixed_cross_section_luminosity_and_sumw',
        'quantity': {'included_factors': [],
                     'applicability': {'id': 'supplied-domain', 'parameters': {},
                                       'assumptions': ['Independent event counts; supplied source model.']}}}}
    modules = (model_event_process, model_event_phases, science_shower_guard, lhe_check)
    monkeypatch.setattr(model_events, '_approved', lambda task, output: (tmp_path, {'max_seconds': 60}))
    monkeypatch.setattr(model_events, 'inputs', lambda task, base: [Path(config_pin['path']),
                        *[Path(m.__file__).resolve() for m in modules]])
    monkeypatch.setattr(model_event_source, 'prepare', lambda request, out: None)
    calls = []

    def inert(command, out, config, **kwargs):
        calls.append(command)
        request = json.loads((out / 'native-input.json').read_text())
        process = Path(request['process'])
        event_file = process / config['outputs']['lhe_relative']
        write(event_file, events(repetitions))
        population = model_event_weights.scan(event_file, expected_events=3 * repetitions, expected_groups=[],
                        maximum_bytes=100000, journal_path=out / 'weights.jsonl')
        result = {'status': 'passed', 'status_scope': model_events.SCOPE, 'physics_validated': False,
                  'generated_events': 3 * repetitions, 'population': population, 'intended': config,
                  'generated_member_commitment': model_event_commitment.snapshot(process)}
        write(out / 'model-events-native.json', result)
        return {'fixture': 'inert-native-boundary'}

    monkeypatch.setattr(reinterpret_db, 'execute_native', inert)
    result = science.adapter({'mode': 'model-events', 'task': task}).run(task, tmp_path, tmp_path / 'generation')
    assert len(calls) == 1
    return result, task


def selection(tmp_path, generated):
    sample = json.loads(Path(generated['generated_sample']['path']).read_text())
    descriptor = {'schema_version': 1, 'kind': 'columnar-format', 'name': 'synthetic event view',
                  'source': 'synthetic bytes', 'format': 'lhe',
                  'collections': {'Photon': {'pdg': [22], 'status': [1]}},
                  'event': {'weight': 'nominal'}}
    recipe = {'schema_version': 1, 'kind': 'columnar-analysis-recipe', 'name': 'synthetic selection',
              'weights': {'generator': 'weight', 'factors': []},
              'objects': [{'name': 'photons', 'from': 'Photon', 'select': 'pt > 0'}],
              'observables': [{'name': 'leading', 'op': 'field', 'object': 'photons[0]', 'field': 'pt', 'unit': 'GeV'}],
              'regions': [{'name': 'selected', 'cuts': [{'name': 'accept', 'expr': 'leading > 0'}]}],
              'histograms': [{'name': 'spectrum', 'region': 'selected', 'observable': 'leading',
                              'edges': [0, 20, 50], 'unit': 'GeV', 'label': 'Transverse momentum',
                              'normalization': 'yield'}]}
    write(tmp_path / 'format.json', descriptor)
    write(tmp_path / 'recipe.json', recipe)
    return {'recipe': 'recipe.json', 'format': 'format.json', 'inputs': [p['path'] for p in sample['events']],
            'normalization': {'mode': 'cross-section', 'cross_section_pb': {'lhe_init': True},
                              'cross_section_source': 'generated init block', 'sum_of_weights': 'all-input-events',
                              'luminosity_ifb': 1, 'luminosity_source': 'supplied exposure'},
            'generated_sample': generated['generated_sample']}


def template_input(tmp_path, prediction_pin, *, shared_mc=False, fixed_mc=False):
    from test_signal_templates import source_document
    prediction = json.loads(Path(prediction_pin['path']).read_text())
    values, variances = [b['value'] for b in prediction['bins']], prediction['sumw2']
    background = {'version': '1.0.0', 'channels': [{'name': 'selected', 'samples': [
        {'name': 'background', 'data': [10, 20], 'modifiers': []}]}],
        'observations': [{'name': 'selected', 'data': [10, 20]}],
        'measurements': [{'name': 'measurement', 'config': {'poi': 'mu', 'parameters': []}}]}
    if shared_mc:
        background['channels'][0]['samples'][0]['modifiers'] = [
            {'name': 'mc', 'type': 'staterror', 'data': [1, 2]}]
    if fixed_mc:
        background['measurements'][0]['config']['parameters'] = [{'name': 'mc', 'fixed': True}]
    signal = {'name': 'signal', 'data': values, 'modifiers': [
        {'name': 'mu', 'type': 'normfactor', 'data': None},
        {'name': 'mc', 'type': 'staterror', 'data': [math.sqrt(v) for v in variances]}]}
    patchset = {'version': '1.0.0', 'metadata': {'analysis_id': 'synthetic', 'description': 'synthetic source',
        'references': {'hepdata': 'synthetic'}, 'labels': ['coordinate'],
        'digests': {'sha256': published_model.canonical_background_digest(background)}},
        'patches': [{'metadata': {'name': 'point', 'values': [1]},
                    'patch': [{'op': 'add', 'path': '/channels/0/samples/0', 'value': signal}]}]}
    raw, patches = json.dumps(background).encode(), json.dumps(patchset).encode()
    archive = tmp_path / 'source-model.tar.gz'
    with tarfile.open(archive, 'w:gz') as stream:
        for name, data in (('background.json', raw), ('patchset.json', patches)):
            member = tarfile.TarInfo(name); member.size = len(data)
            stream.addfile(member, io.BytesIO(data))
    doc = source_document(archive, raw, patches, {'coordinate': 1})
    doc['inference']['witness_limits'].update(evaluations=500, minimizations=5000, bytes=16777216)
    source = published_model.load_published_model(doc)
    template = signal_templates.identity_template(source, 'supplied-template')
    sample = template['channels'][0]['samples'][0]
    sample.update(prediction=prediction_pin, prediction_requirements={key: deepcopy(prediction['quantity'][key]) for key in
                  ('selection', 'model_point', 'included_factors', 'exposure', 'event_population', 'luminosity', 'applicability')})
    sample['provenance'] = {'kind': 'supplied_prediction', 'description': 'Synthetic selection output',
                            'evidence': [prediction_pin], 'normalization_shape': 'source_decomposition'}
    sample['mc_stat'] = {'mode': 'supplied', 'description': 'Supplied independent event model',
                         'weight_model': 'nonnegative', 'sumw': values, 'sumw2': variances}
    source_pin = write(tmp_path / 'source-model.json', doc)
    template_pin = write(tmp_path / 'template.json', template)
    bridge = write(tmp_path / 'bridge.json', {'schema_version': 1, 'published_model': source_pin, 'template': template_pin})
    return {'input': bridge['path']}, source, template


@pytest.fixture
def selected(tmp_path, monkeypatch):
    generated, _ = generate(tmp_path, monkeypatch)
    task = selection(tmp_path, generated)
    adapter = science.adapter({'mode': 'columnar-analysis', 'task': task})
    adapter.inputs(task, tmp_path)
    result = adapter.run(task, tmp_path, tmp_path / 'selection')
    return generated, task, result


def test_real_chain_constructs_likelihood_and_resolved_expected_limits(tmp_path, selected):
    generated, _, result = selected
    artifact = result['quantity_artifacts']['spectrum']
    q = json.loads(Path(artifact['path']).read_text())
    assert [b['value'] for b in q['bins']] == pytest.approx([2, 4])
    assert q['covariance'][0] == pytest.approx([.04, 0])
    assert q['covariance'][1] == pytest.approx([0, .08])
    task, _, template = template_input(tmp_path, artifact)
    adapter = science.adapter({'mode': 'signal-template', 'task': task})
    adapter.inputs(task, tmp_path)
    outcome = adapter.run(task, tmp_path, tmp_path / 'inference')
    assert outcome['status'] == 'passed', outcome
    assert outcome['quantity_artifact'] == chain.file_pin(tmp_path / 'inference/inference-quantity-contract.json')
    inferred = json.loads((tmp_path / 'inference/inference-quantity-contract.json').read_text())
    assert inferred['limit_status']['expected'] == ['resolved'] * 5
    assert len(inferred['expected_limits']) == 5
    assert all(math.isfinite(x) and x > 0 for x in inferred['expected_limits'])
    assert inferred['expected_limits'] == sorted(inferred['expected_limits'])
    assert inferred['input_quantities'][0]['quantity'] == q['quantity']
    assert inferred['input_quantities'][0]['requirements'] == template['channels'][0]['samples'][0]['prediction_requirements']
    assert inferred['quantity']['model_point'] == q['quantity']['model_point']
    assert inferred['physics_validated'] is False


def test_insufficient_sample_keeps_unresolved_limit_refusal(tmp_path, monkeypatch):
    generated, _ = generate(tmp_path, monkeypatch, repetitions=1)
    task = selection(tmp_path, generated)
    result = columnar_analysis.run(task, tmp_path, tmp_path / 'selection')
    task, _, _ = template_input(tmp_path, result['quantity_artifacts']['spectrum'])
    outcome = signal_templates.run(task, tmp_path, tmp_path / 'inference')
    assert outcome['status'] == 'failed'
    assert 'all six resolved roots' in outcome['error']['message']
    assert (tmp_path / 'inference/inference_failure.json').is_file()
    assert not (tmp_path / 'inference/inference-quantity-contract.json').exists()


@pytest.mark.parametrize('field', ['included_factors', 'applicability'])
def test_missing_producer_facts_are_located_obligations(tmp_path, monkeypatch, field):
    generated, _ = generate(tmp_path, monkeypatch)
    pin = generated['generated_sample']; path = Path(pin['path']); doc = json.loads(path.read_text())
    del doc['quantity'][field]
    generated['generated_sample'] = write(path, doc)
    task = selection(tmp_path, generated)
    with pytest.raises(chain.QuantityObligations) as error:
        columnar_analysis.inputs(task, tmp_path)
    assert any(row['field'].startswith(field) and row['location'] == 'columnar-analysis.events'
               for row in error.value.obligations)


@pytest.mark.parametrize('fault,field', [('scale', 'scale'), ('unit', 'unit'), ('factor', 'normalization.factor'),
    ('group', 'event_population.id'), ('revision', 'exposure.revision'), ('rate', 'cross_section_pb'),
    ('moments', 'events.sum_generator'), ('signed-census', 'events.negative')])
def test_generation_to_selection_faults(tmp_path, monkeypatch, fault, field):
    generated, _ = generate(tmp_path, monkeypatch)
    task = selection(tmp_path, generated)
    pin = generated['generated_sample']; path = Path(pin['path']); doc = json.loads(path.read_text())
    if fault == 'scale': doc['cross_section']['quantity']['scale'] = 1000
    elif fault == 'unit': doc['cross_section']['quantity']['unit'] = 'fb'
    elif fault == 'group': doc['quantity']['event_population']['id'] = 'unrelated'
    elif fault == 'revision': doc['quantity']['exposure']['revision'] = 'stale'
    elif fault == 'rate': doc['cross_section']['value'] *= 2
    elif fault in ('moments', 'signed-census'):
        key, value = ('sumw', 1) if fault == 'moments' else ('negative_events', 1)
        for quantity in (doc['quantity'], doc['cross_section']['quantity']):
            quantity['event_population'][key] = value
    else: task['normalization']['factor'] = {'value': .5, 'source': 'already included'}
    task['generated_sample'] = write(path, doc)
    with pytest.raises(ValueError, match=field):
        columnar_analysis.run(task, tmp_path, tmp_path / 'selection')


@pytest.mark.parametrize('fault,field', [('bin', 'bin_ids'), ('covariance', 'covariance'),
    ('selection', 'selection'), ('exposure', 'exposure'), ('luminosity', 'luminosity'),
    ('domain', 'applicability'), ('value', 'template.data'), ('missing', 'requirements')])
def test_selection_to_template_faults(tmp_path, selected, fault, field):
    _, _, result = selected
    pin = result['quantity_artifacts']['spectrum']
    task, source, template = template_input(tmp_path, pin)
    sample = template['channels'][0]['samples'][0]
    if fault == 'value': sample['data'][0] *= 2
    elif fault == 'missing': del sample['prediction_requirements']['applicability']
    elif fault in ('exposure', 'luminosity', 'domain'):
        key, member, value = {'exposure': ('exposure', 'revision', 'stale'),
                              'luminosity': ('luminosity', 'value', 2),
                              'domain': ('applicability', 'id', 'other-domain')}[fault]
        sample['prediction_requirements'][key][member] = value
    else:
        path = Path(pin['path']); doc = json.loads(path.read_text())
        if fault == 'bin': doc['quantity']['bin_ids'].reverse()
        elif fault == 'selection': doc['quantity']['selection'] = 'unrelated'
        else: doc['quantity']['covariance']['matrix'][0][1] = 1
        sample['prediction'] = write(path, doc)
        sample['provenance']['evidence'] = [sample['prediction']]
    with pytest.raises(ValueError, match=field):
        signal_templates.build_signal_template(source, template)


def test_model_identity_cannot_be_relabelled(tmp_path, monkeypatch):
    generated, task = generate(tmp_path, monkeypatch)
    result = json.loads((tmp_path / 'generation/model-events.json').read_text())
    declaration = deepcopy(task['composition'])
    declaration['quantity']['model_point'] = {'mass': 999}
    path = json.loads(Path(generated['generated_sample']['path']).read_text())['events'][0]['path']
    with pytest.raises(ValueError, match='model_point'):
        chain.generated_sample(result, declaration, path)


@pytest.mark.parametrize('fault', ['extra-factor', 'missing-generator'])
def test_weight_recipe_requires_original_nominal_weight(tmp_path, monkeypatch, fault):
    generated, _ = generate(tmp_path, monkeypatch)
    task = selection(tmp_path, generated)
    path = tmp_path / 'recipe.json'
    recipe = json.loads(path.read_text())
    if fault == 'extra-factor':
        recipe['weights']['factors'] = ['weight']
    else:
        recipe['weights']['generator'] = None
    write(path, recipe)
    with pytest.raises(ValueError, match='columnar-analysis.weights'):
        columnar_analysis.run(task, tmp_path, tmp_path / 'selection')


def test_changed_format_is_a_changed_selection(tmp_path, selected):
    _, _, result = selected
    prediction_pin = result['quantity_artifacts']['spectrum']
    _, source, template = template_input(tmp_path, prediction_pin)
    prediction_path = Path(prediction_pin['path'])
    prediction = json.loads(prediction_path.read_text())
    descriptor_path = Path(prediction['provenance']['selection_format']['path'])
    descriptor = json.loads(descriptor_path.read_text())
    descriptor['collections']['Photon']['pdg'] = [11]
    prediction['provenance']['selection_format'] = write(descriptor_path, descriptor)
    template['channels'][0]['samples'][0]['prediction'] = write(prediction_path, prediction)
    with pytest.raises(ValueError, match='template.prediction.selection'):
        signal_templates.build_signal_template(source, template)


def test_explicit_event_groups_cannot_claim_independent_sampling(tmp_path, monkeypatch):
    original = events
    monkeypatch.setitem(globals(), 'events', lambda repetitions: original(repetitions).replace(
        '</init>', '</init><eventgroup>').replace('</LesHouchesEvents>', '</eventgroup></LesHouchesEvents>'))
    with pytest.raises(ValueError, match='event_population.grouping'):
        generate(tmp_path, monkeypatch)


def test_signed_population_reaches_specialized_likelihood_refusal(tmp_path, monkeypatch):
    original = events
    monkeypatch.setitem(globals(), 'events', lambda repetitions: original(repetitions).replace(
        '3 1 1 100', '3 1 -1 100', 1))
    generated, _ = generate(tmp_path, monkeypatch)
    task = selection(tmp_path, generated)
    result = columnar_analysis.run(task, tmp_path, tmp_path / 'selection')
    _, source, template = template_input(tmp_path, result['quantity_artifacts']['spectrum'])
    with pytest.raises(ValueError, match='negative_events'):
        signal_templates.build_signal_template(source, template)


@pytest.mark.parametrize('option', ['shared_mc', 'fixed_mc'])
def test_likelihood_must_retain_declared_signal_covariance(tmp_path, selected, option):
    _, _, result = selected
    _, source, template = template_input(tmp_path, result['quantity_artifacts']['spectrum'], **{option: True})
    with pytest.raises(ValueError, match='template.prediction.covariance'):
        signal_templates.build_signal_template(source, template)


def test_prediction_region_must_match_consumer_channel(tmp_path, selected):
    _, _, result = selected
    pin = result['quantity_artifacts']['spectrum']
    task, _, template = template_input(tmp_path, pin)
    document = json.loads(Path(pin['path']).read_text())
    document['quantity']['regional_exposures'] = {
        'other': document['quantity']['exposure']}
    sample = template['channels'][0]['samples'][0]
    sample['prediction'] = write(Path(pin['path']), document)
    sample['provenance']['evidence'] = [sample['prediction']]
    bridge = json.loads((tmp_path / 'bridge.json').read_text())
    bridge['template'] = write(tmp_path / 'template.json', template)
    write(tmp_path / 'bridge.json', bridge)
    with pytest.raises(ValueError, match='regional_exposures'):
        science.adapter({'mode': 'signal-template', 'task': task}).inputs(task, tmp_path)


@pytest.mark.parametrize('field,value', [
    ('sampling_model', 'correlated_events'),
    ('normalization_model', 'variable_normalization'),
    ('sampling_model_origin', 'measured')])
def test_prediction_retains_generation_sampling_assumptions(tmp_path, selected, field, value):
    _, _, result = selected
    pin = result['quantity_artifacts']['spectrum']
    task, _, template = template_input(tmp_path, pin)
    document = json.loads(Path(pin['path']).read_text())
    source_pin = document['provenance']['generated_sample']
    generation = json.loads(Path(source_pin['path']).read_text())
    generation[field] = value
    document['provenance']['generated_sample'] = write(Path(source_pin['path']), generation)
    sample = template['channels'][0]['samples'][0]
    sample['prediction'] = write(Path(pin['path']), document)
    sample['provenance']['evidence'] = [sample['prediction']]
    bridge = json.loads((tmp_path / 'bridge.json').read_text())
    bridge['template'] = write(tmp_path / 'template.json', template)
    write(tmp_path / 'bridge.json', bridge)
    with pytest.raises(ValueError, match=field):
        science.adapter({'mode': 'signal-template', 'task': task}).inputs(task, tmp_path)


@pytest.mark.parametrize('fault,field', [
    ('schema', 'schema_version'), ('kind', 'kind'), ('grouping', 'grouping'),
    ('population', 'event_population.id'), ('exposure', 'exposure.id'),
    ('multiple', 'inputs'), ('missing', 'included_factors'),
    ('events_null', 'inputs'), ('events_scalar', 'inputs'),
    ('events_object', 'inputs'), ('events_empty', 'inputs')])
def test_prediction_requires_admissible_generated_sample(tmp_path, selected, fault, field):
    _, _, result = selected
    pin = result['quantity_artifacts']['spectrum']
    task, _, template = template_input(tmp_path, pin)
    document = json.loads(Path(pin['path']).read_text())
    source_pin = document['provenance']['generated_sample']
    generation = json.loads(Path(source_pin['path']).read_text())
    sample = template['channels'][0]['samples'][0]
    quantities = (generation['quantity'], generation['cross_section']['quantity'],
                  document['quantity'], sample['prediction_requirements'])
    if fault == 'schema':
        generation['schema_version'] = 2
    elif fault == 'kind':
        generation['kind'] = 'other-sample'
    elif fault == 'multiple':
        generation['events'] *= 2
    elif fault.startswith('events_'):
        generation['events'] = {'events_null': None, 'events_scalar': 1,
                                'events_object': {}, 'events_empty': []}[fault]
    elif fault == 'missing':
        del generation['quantity']['included_factors']
    else:
        key, member, value = {
            'grouping': ('event_population', 'grouping', 'group'),
            'population': ('event_population', 'id', 'unrelated'),
            'exposure': ('exposure', 'id', 'unrelated')}[fault]
        for quantity in quantities:
            quantity[key][member] = value
        if fault == 'exposure':
            document['quantity']['regional_exposures']['selected']['id'] = value
    document['provenance']['generated_sample'] = write(Path(source_pin['path']), generation)
    sample['prediction'] = write(Path(pin['path']), document)
    sample['provenance']['evidence'] = [sample['prediction']]
    bridge = json.loads((tmp_path / 'bridge.json').read_text())
    bridge['template'] = write(tmp_path / 'template.json', template)
    write(tmp_path / 'bridge.json', bridge)
    with pytest.raises(ValueError, match=field) as error:
        science.adapter({'mode': 'signal-template', 'task': task}).inputs(task, tmp_path)
    if fault == 'missing':
        assert isinstance(error.value, chain.QuantityObligations)
        assert any(row['field'] == 'included_factors' and row['location'] ==
                   'template.prediction.generated_sample.events' for row in error.value.obligations)
