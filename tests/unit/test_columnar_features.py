"""Synthetic bounded populations, weight policies and held-out frozen scores."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import uproot

from ravel.physics import ml_backends, ml_crossfit as cf, ml_custody
from ravel.physics.columnar import engine, features, formats
from ravel.physics.columnar.recipe import compile_recipe


def descriptor():
    return formats.load_descriptor({'schema_version': 1, 'kind': 'columnar-format', 'name': 'synthetic events',
        'source': 'synthetic fixture', 'format': 'root', 'tree': 'Events', 'collections': {},
        'met': {'magnitude': 'magnitude', 'phi': 'angle'},
        'event': {'generator': 'generator', 'identifier': 'identifier', 'group': 'group'}})


def recipe():
    return {'schema_version': 1, 'kind': 'columnar-analysis-recipe', 'name': 'synthetic population',
        'weights': {'generator': 'generator', 'factors': []}, 'objects': [],
        'observables': [{'name': 'magnitude', 'op': 'met'}, {'name': 'angle', 'op': 'met_phi'}],
        'regions': [{'name': 'selected', 'cuts': [{'name': 'threshold', 'expr': 'magnitude >= 2'}]}],
        'histograms': [],
        'features': {'region': 'selected', 'observables': ['magnitude', 'angle'], 'label': 'simulation',
            'event_id': 'identifier', 'group_id': 'group', 'max_events': 100, 'sampling_seed': 71,
            'weight_policy': {'negative': 'refuse', 'unequal': 'refuse'}, 'folds': {'k': 3, 'salt': 'synthetic'}}}


def population(tmp_path, n=18, weights=None, identifiers=None, groups=None):
    path = tmp_path / 'events.root'
    arrays = {'magnitude': np.arange(n, dtype=float), 'angle': np.zeros(n),
        'generator': np.ones(n) if weights is None else np.asarray(weights, float),
        'identifier': np.arange(n, dtype=np.int64) if identifiers is None else np.asarray(identifiers),
        'group': np.arange(n, dtype=np.int64) // 2 if groups is None else np.asarray(groups)}
    with uproot.recreate(path) as f:
        f.mktree('Events', {k: v.dtype for k, v in arrays.items()})
        f['Events'].extend(arrays)
    return path, arrays


def analyse(path, doc, tmp_path, *, start=0, stop=None, chunk=4):
    plan = compile_recipe(doc, descriptor(), tmp_path)
    partial = engine.analyse({'inputs': [{'path': str(path), 'file_index': 0, 'entry_start': start,
                                          'entry_stop': stop}], 'chunk_size': chunk}, plan)
    # Ordinary partition workers serialize JSON; feature partials must survive it.
    return json.loads(json.dumps(partial)), plan


def export(partial, plan, directory):
    result = engine.finalize(engine.merge([partial]), plan, {'mode': 'none'}, out_dir=directory)
    meta = json.loads((directory / 'features.json').read_text())
    loaded = cf.load_events(meta['population'], directory, len(plan.features['observables']),
                            allow_sampling_weights=meta['requires_weighted_qualification'])
    return loaded, meta, result


@pytest.mark.parametrize('field,value', [('weight_policy', None), ('event_id', 'missing'),
    ('group_id', 'missing'), ('observables', ['missing']), ('max_events', 100001),
    ('max_events', True), ('sampling_seed', 1.5), ('label', ''), ('region', 'missing'),
    ('folds', {'k': 1, 'salt': 'synthetic'})])
def test_invalid_feature_contract_refused(tmp_path, field, value):
    doc = recipe()
    if value is None:
        del doc['features'][field]
    else:
        doc['features'][field] = value
    with pytest.raises(ValueError):
        compile_recipe(doc, descriptor(), tmp_path)


def test_export_matches_exact_five_array_loader_contract_and_group_folds(tmp_path):
    path, arrays = population(tmp_path)
    part, plan = analyse(path, recipe(), tmp_path)
    loaded, meta, result = export(part, plan, tmp_path / 'output')
    assert set(loaded) == {'x', 'region', 'weight', 'event_id', 'group_id'}
    assert meta['counts'] == {'selected': 16, 'negative': 0, 'dropped_negative': 0, 'eligible': 16}
    assert meta['spec']['label'] == 'simulation'
    assert meta['region_encoding'] == {'selected': 0}
    for x, eid, gid in zip(loaded['x'], loaded['event_id'], loaded['group_id']):
        assert x.tolist() == [float(eid), 0.]
        assert int(gid) == int(eid) // 2
    expected = cf.fold_map(loaded['group_id'], 3, 'synthetic')
    assert expected.tolist() == [meta['fold_by_group'][g] for g in loaded['group_id']]
    assert {'features.npz', 'features.json'} <= {r['path'] for r in result['files']}
    assert meta['inputs'][0]['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert meta['expanded_bytes'] < 64 * 1024**2
    with np.load(tmp_path / 'output/features.npz', allow_pickle=False) as z:
        assert set(z.files) == set(loaded)


def test_sampling_is_identical_across_chunks_partitions_order_and_merge_trees(tmp_path):
    path, _ = population(tmp_path, n=77)
    doc = recipe(); doc['features']['max_events'] = 9
    whole, plan = analyse(path, doc, tmp_path, chunk=3)
    a, _ = analyse(path, doc, tmp_path, stop=21, chunk=6)
    b, _ = analyse(path, doc, tmp_path, start=21, stop=47, chunk=7)
    c, _ = analyse(path, doc, tmp_path, start=47, chunk=11)
    combined = engine.merge([c, engine.merge([b, a])])
    assert whole['features'] == combined['features']
    x, meta, _ = export(whole, plan, tmp_path / 'whole')
    y, _, _ = export(combined, plan, tmp_path / 'combined')
    for key in x:
        np.testing.assert_array_equal(x[key], y[key])
    expected = sorted(range(2, 77), key=lambda n: hashlib.sha256(f'71:{n}'.encode()).hexdigest())[:9]
    assert x['event_id'].tolist() == list(map(str, expected))
    assert meta['sampling']['sampled_out'] == 66
    doc['features']['sampling_seed'] += 1
    changed, _ = analyse(path, doc, tmp_path)
    assert changed['features']['rows'] != whole['features']['rows']


@pytest.mark.parametrize('choice', ['refuse', 'drop', 'absolute'])
def test_signed_weights_require_and_record_declared_policy(tmp_path, choice):
    weights = np.ones(18); weights[[3, 6, 9]] = -1
    path, _ = population(tmp_path, weights=weights)
    doc = recipe(); doc['features']['weight_policy']['negative'] = choice
    if choice == 'refuse':
        with pytest.raises(ValueError, match='negative'):
            analyse(path, doc, tmp_path)
        return
    part, plan = analyse(path, doc, tmp_path)
    loaded, meta, _ = export(part, plan, tmp_path / 'output')
    assert np.all(loaded['weight'] == 1)
    assert meta['counts']['negative'] == 3
    assert meta['dropped_negative_fraction'] == (3 / 16 if choice == 'drop' else 0.)
    assert len(loaded['x']) == (13 if choice == 'drop' else 16)
    assert meta['spec']['weight_policy']['negative'] == choice


def test_unequal_weights_are_preserved_only_for_weighted_qualification(tmp_path):
    weights = np.ones(18); weights[4] = -3
    path, _ = population(tmp_path, weights=weights)
    doc = recipe(); doc['features']['weight_policy']['negative'] = 'absolute'
    with pytest.raises(ValueError, match='unequal'):
        analyse(path, doc, tmp_path)
    doc['features']['weight_policy']['unequal'] = 'weighted-qualification'
    part, plan = analyse(path, doc, tmp_path)
    loaded, meta, _ = export(part, plan, tmp_path / 'output')
    assert meta['requires_weighted_qualification'] is True
    assert sorted(loaded['weight']) == [1.] * 15 + [3.]
    with pytest.raises(ValueError, match='weighted training unqualified'):
        cf.load_events(meta['population'], tmp_path, 2)


def test_unequal_weights_across_partitions_are_refused(tmp_path):
    weights = np.ones(18); weights[9:] = 2
    path, _ = population(tmp_path, weights=weights)
    doc = recipe()
    a, _ = analyse(path, doc, tmp_path, stop=9)
    b, _ = analyse(path, doc, tmp_path, start=9)
    with pytest.raises(ValueError, match='unequal'):
        engine.merge([a, b])


@pytest.mark.parametrize('what', ['zero', 'nonfinite', 'duplicate', 'too-small'])
def test_loader_invalid_populations_fail_closed(tmp_path, what):
    path, arrays = population(tmp_path)
    if what == 'zero':
        arrays['generator'][3] = 0
    elif what == 'nonfinite':
        arrays['angle'][3] = np.nan
    elif what == 'duplicate':
        arrays['identifier'][3] = 4
    else:
        arrays['magnitude'][:] = 0
    with uproot.recreate(path) as f:
        f.mktree('Events', {k: v.dtype for k, v in arrays.items()}); f['Events'].extend(arrays)
    with pytest.raises(ValueError):
        part, plan = analyse(path, recipe(), tmp_path)
        export(part, plan, tmp_path / 'output')
    assert not (tmp_path / 'output/features.npz').exists()


def test_raw_integer_identities_keep_uint64_precision(tmp_path):
    ids = np.arange(18, dtype=np.uint64) + np.uint64(2**63 + 17)
    path, _ = population(tmp_path, identifiers=ids, groups=ids)
    part, plan = analyse(path, recipe(), tmp_path)
    loaded, _, _ = export(part, plan, tmp_path / 'output')
    assert set(loaded['event_id']) == set(map(str, ids[2:]))
    assert set(loaded['group_id']) == set(map(str, ids[2:]))


def test_byte_ceiling_samples_deterministically(tmp_path, monkeypatch):
    path, _ = population(tmp_path, n=180)
    doc = recipe(); doc['features']['max_events'] = 100
    part, plan = analyse(path, doc, tmp_path)
    monkeypatch.setattr(features, 'MAX_BYTES', 8192)
    loaded, meta, _ = export(part, plan, tmp_path / 'output')
    assert 3 <= len(loaded['x']) < 100
    assert meta['expanded_bytes'] <= 8192
    assert (tmp_path / 'output/features.npz').stat().st_size <= 8192


def pin_json(path, doc):
    path.write_text(json.dumps(doc))
    return pin(path)


def pin(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def frozen(tmp_path, *, sealed=False, transform=None):
    """The existing ML selected-checkpoint format; no fitting or training jobs."""
    state = {'architecture': np.array('logistic'), 'layers': np.array(1),
        'w0': np.array([[.2], [-.4]]), 'b0': np.array([.1])}
    checkpoint = tmp_path / 'checkpoint.npz'
    np.savez(checkpoint, **state)
    checkpoint_pin = ml_custody.put(state, arrays=True) if sealed else pin(checkpoint)
    transform = transform or {'kind': 'standardize', 'mean': [2., 0.], 'scale': [3., 1.]}
    transform_pin = ml_custody.put(transform) if sealed else pin_json(tmp_path / 'transform.json', transform)
    groups = [str(n) for n in range(18)]
    folds = cf.fold_map(groups, 3, 'synthetic')
    scope = {'train_groups': [g for g, f in zip(groups, folds) if f == 1],
        'validation_groups': [g for g, f in zip(groups, folds) if f == 2],
        'preprocessing_groups': [g for g, f in zip(groups, folds) if f == 1],
        'test_groups': [g for g, f in zip(groups, folds) if f == 0]}
    scope_pin = pin_json(tmp_path / 'scope.json', scope)
    history_pin = pin_json(tmp_path / 'history.json', {'checkpoint': checkpoint_pin,
        'transform': transform_pin, 'group_scope': scope_pin, 'fold': 0, 'salt': 'synthetic'})
    freeze_pin = pin_json(tmp_path / 'freeze.json', {'models': [checkpoint_pin], 'histories': [history_pin]})
    record = {'schema_version': 1, 'kind': 'columnar-frozen-model', 'features': ['magnitude', 'angle'],
        'checkpoint': checkpoint_pin, 'transform': transform_pin, 'group_scope': scope_pin,
        'folds': {'k': 3, 'salt': 'synthetic', 'test_fold': 0}, 'freeze': freeze_pin}
    model_pin = pin_json(tmp_path / 'model.json', record)
    return model_pin, record, state, transform, scope


def score_recipe(model_pin):
    doc = recipe(); del doc['features']
    doc['observables'].append({'name': 'score', 'op': 'model_score', 'model': model_pin,
        'features': ['magnitude', 'angle'], 'group_id': 'group'})
    doc['event_record'] = {'max_events': 100, 'observables': ['score']}
    return doc


@pytest.mark.parametrize('sealed', [False, True])
def test_model_score_equals_frozen_backend_on_held_out_groups(tmp_path, sealed):
    model_pin, record, state, transform, scope = frozen(tmp_path, sealed=sealed)
    groups = list(map(int, scope['test_groups']))
    path, arrays = population(tmp_path, n=len(groups), groups=groups)
    part, plan = analyse(path, score_recipe(model_pin), tmp_path, chunk=2)
    expected = ml_backends.predict_selected(state, cf.apply_transform(transform,
        np.column_stack([arrays['magnitude'], arrays['angle']]), np.zeros(len(groups), int)))
    np.testing.assert_array_equal([r['score'] for r in part['event_record']], expected)
    if sealed:
        ml_custody.discard([record['checkpoint'], record['transform']])
        with pytest.raises(ValueError, match='unavailable'):
            compile_recipe(score_recipe(model_pin), descriptor(), tmp_path)


@pytest.mark.parametrize('change', ['features', 'record-hash', 'checkpoint-hash', 'scope-hash',
    'freeze-membership', 'history-scope', 'history-fold', 'wrong-width'])
def test_pinned_model_contract_mutations_are_refused(tmp_path, change):
    model_pin, record, state, transform, scope = frozen(tmp_path)
    if change == 'features':
        record['features'].reverse()
    elif change == 'record-hash':
        Path(model_pin['path']).write_text('{}')
    elif change == 'checkpoint-hash':
        with Path(record['checkpoint']['path']).open('ab') as f:
            f.write(b'changed')
    elif change == 'scope-hash':
        Path(record['group_scope']['path']).write_text('{}')
    elif change == 'freeze-membership':
        record['freeze'] = pin_json(tmp_path / 'other-freeze.json', {'models': []})
    elif change == 'history-scope':
        record['group_scope'] = pin_json(tmp_path / 'other-scope.json', scope)
    elif change == 'history-fold':
        record['folds']['test_fold'] = 1
    elif change == 'wrong-width':
        state['w0'] = np.zeros((1, 1))
        np.savez(tmp_path / 'wrong.npz', **state)
        record['checkpoint'] = pin(tmp_path / 'wrong.npz')
        history_pin = pin_json(tmp_path / 'other-history.json', {'checkpoint': record['checkpoint'],
            'transform': record['transform'], 'group_scope': record['group_scope'], 'fold': 0, 'salt': 'synthetic'})
        record['freeze'] = pin_json(tmp_path / 'other-freeze.json', {'models': [record['checkpoint']], 'histories': [history_pin]})
    if change != 'record-hash':
        model_pin = pin_json(tmp_path / 'model.json', record)
    with pytest.raises(ValueError):
        compile_recipe(score_recipe(model_pin), descriptor(), tmp_path)


@pytest.mark.parametrize('role', ['train_groups', 'validation_groups', 'unknown'])
def test_model_score_refuses_in_fold_validation_and_unknown_groups(tmp_path, role):
    model_pin, _, _, _, scope = frozen(tmp_path)
    group = 999 if role == 'unknown' else int(scope[role][0])
    path, _ = population(tmp_path, groups=[group] * 18)
    with pytest.raises(ValueError, match='in-fold or unknown'):
        analyse(path, score_recipe(model_pin), tmp_path)


def test_model_score_refuses_heldout_group_with_wrong_fold(tmp_path):
    model_pin, _, _, _, scope = frozen(tmp_path)
    doc = score_recipe(model_pin)
    plan = compile_recipe(doc, descriptor(), tmp_path)
    model = plan.observables[-1].model
    model.folds['test_fold'] = 1
    with pytest.raises(ValueError, match='held-out fold'):
        model.predict(np.zeros((1, 2)), [scope['test_groups'][0]])


def test_only_if_scores_only_held_out_events(tmp_path):
    model_pin, _, _, _, scope = frozen(tmp_path)
    groups = [int(scope['train_groups'][0])] * 3 + [int(scope['test_groups'][0])] * 3
    path, _ = population(tmp_path, n=6, groups=groups)
    doc = score_recipe(model_pin); doc['observables'][-1]['only_if'] = 'magnitude >= 3'
    part, _ = analyse(path, doc, tmp_path)
    assert [r['score'] for r in part['event_record']][:3] == [None] * 3
    assert all(r['score'] is not None for r in part['event_record'][3:])


def test_planning_includes_transitive_model_pins(tmp_path):
    from ravel.physics.columnar_analysis import compile_task
    model_pin, record, _, _, _ = frozen(tmp_path)
    path, _ = population(tmp_path)
    (tmp_path / 'recipe.json').write_text(json.dumps(score_recipe(model_pin)))
    (tmp_path / 'format.json').write_text(json.dumps(descriptor().doc))
    _, _, files, _ = compile_task({'recipe': 'recipe.json', 'format': 'format.json',
        'inputs': [str(path)], 'normalization': {'mode': 'none'}}, tmp_path)
    expected = {tmp_path / n for n in ('model.json', 'checkpoint.npz', 'transform.json', 'scope.json',
                                       'freeze.json', 'history.json')}
    assert expected <= set(files)


def test_features_survive_raw_skim_replay(tmp_path):
    path, _ = population(tmp_path)
    doc = recipe(); doc['skim'] = {'region': 'selected', 'branches': 'all-declared', 'format': 'root'}
    plan = compile_recipe(doc, descriptor(), tmp_path)
    first = engine.analyse({'inputs': [{'path': str(path)}]}, plan, skim_dir=tmp_path / 'skim-output')
    del doc['skim']
    plan = compile_recipe(doc, descriptor(), tmp_path)
    second = engine.analyse({'inputs': [{'path': first['skims'][0]['path']}], 'chunk_size': 3}, plan)
    assert first['features'] == second['features']


def test_region_quantile_scores_use_frozen_transform(tmp_path):
    transform = {'kind': 'region_quantile', 'features': [0], 'references': {'0:0': [0., 4., 8., 12.]}}
    model_pin, _, state, _, scope = frozen(tmp_path, transform=transform)
    group = int(scope['test_groups'][0])
    path, arrays = population(tmp_path, groups=[group] * 18)
    doc = score_recipe(model_pin)
    doc['observables'].insert(2, {'name': 'region_index', 'op': 'expr', 'expr': 'angle * 0'})
    doc['observables'][-1]['region'] = 'region_index'
    part, _ = analyse(path, doc, tmp_path)
    expected = ml_backends.predict_selected(state, cf.apply_transform(transform,
        np.column_stack([arrays['magnitude'], arrays['angle']]), np.zeros(18, int)))
    # Integer and float region encodings must address the same frozen region.
    np.testing.assert_array_equal([r['score'] for r in part['event_record']], expected)


def test_object_checkpoint_is_refused_without_unpickling(tmp_path):
    model_pin, record, _, _, _ = frozen(tmp_path)
    np.savez(tmp_path / 'object.npz', payload=np.array([{'value': 1}], dtype=object))
    record['checkpoint'] = pin(tmp_path / 'object.npz')
    record['freeze'] = pin_json(tmp_path / 'other-freeze.json', {'models': [record['checkpoint']], 'histories': []})
    model_pin = pin_json(tmp_path / 'model.json', record)
    with pytest.raises(ValueError, match='Object arrays cannot be loaded'):
        compile_recipe(score_recipe(model_pin), descriptor(), tmp_path)
