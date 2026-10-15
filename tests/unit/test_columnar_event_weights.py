"""Synthetic event-observable scale factors, failures, variations and moments."""
import copy
import json

import numpy as np
import pytest

from test_columnar_inputs import write_delphes
from ravel.physics.columnar import engine, formats
from ravel.physics.columnar.recipe import compile_recipe


def recipe(base, policy='refuse', two_axes=False):
    axes = [{'name': 'multiplicity', 'unit': '1'}]
    edges = [[0, 1, 3]]
    values = [0.5, 2.0]
    if two_axes:
        axes.append({'name': 'recoil', 'unit': 'GeV'})
        edges.append([0, 50, 100])
        values = [[0.5, 1.0], [2.0, 3.0]]
    maps = {}
    for name, scale in [('central', 1), ('upper', 1.2), ('lower', 0.8)]:
        path = name + '.json'
        (base / path).write_text(json.dumps({'axes': [{**a, 'edges': e} for a, e in zip(axes, edges)],
                                             'values': (np.asarray(values) * scale).tolist()}))
        maps[name] = {'source': {'format': 'json-grid', 'path': path}, 'axes': axes,
                      'out_of_range': 'refuse', 'semantics': 'scale_factor', 'allow_above_one': True,
                      'citation': 'synthetic correction map'}
    return {'schema_version': 1, 'kind': 'columnar-analysis-recipe', 'name': 'synthetic event correction',
            'weights': {'generator': 'weight', 'factors': []}, 'efficiency_maps': maps,
            'objects': [{'name': 'radiation', 'from': 'Jet', 'select': 'pt > 20 and btag == 0'}],
            'observables': [{'name': 'n', 'op': 'count', 'collection': 'radiation', 'unit': '1'},
                            {'name': 'recoil', 'op': 'met', 'unit': 'GeV'}],
            'event_weights': [{'name': 'radiation correction', 'map': 'central',
                               'observables': ['n', 'recoil'] if two_axes else ['n'], 'out_of_range': policy,
                               'variations': {'correction up': 'upper', 'correction down': 'lower'}}],
            'regions': [{'name': 'selected', 'cuts': [{'name': 'accept', 'expr': 'recoil >= 0'}]}],
            'histograms': [{'name': 'recoil distribution', 'region': 'selected', 'observable': 'recoil',
                            'edges': [0, 50, 1000], 'unit': 'GeV', 'label': 'Recoil transverse momentum',
                            'normalization': 'raw'}]}


def events(counts=(0, 1, 2, 3)):
    return [{'MET': met, 'METPhi': 0, 'Weight': w,
             'Jet': [{'PT': 30, 'Eta': 0, 'Phi': 0, 'Mass': 5, 'BTag': 0, 'TauTag': 0, 'Charge': 0}
                     for _ in range(n)]} for n, met, w in zip(counts, (20, 60, 150, 30), (2, -1, 3, 4))]


def run(base, doc, sample, chunk=10):
    path = base / 'events.root'
    write_delphes(path, sample)
    plan = compile_recipe(doc, formats.load_descriptor('delphes'), base)
    part = engine.analyse({'inputs': [{'path': str(path), 'file_index': 7}], 'chunk_size': chunk}, plan)
    return plan, part, path


def test_undeclared_event_observable_is_refused_before_reading(tmp_path):
    doc = recipe(tmp_path)
    doc['event_weights'][0]['observables'] = ['pt']
    with pytest.raises(ValueError, match="undeclared event observable 'pt'"):
        compile_recipe(doc, formats.load_descriptor('delphes'), tmp_path)


def test_refuse_reports_original_event_index_after_chunk_boundary(tmp_path):
    with pytest.raises(ValueError, match='file_index 7, event index 3.*policy refuse'):
        run(tmp_path, recipe(tmp_path), events(), chunk=2)


@pytest.mark.parametrize('policy,expected', [('clamp', 13.), ('one', 9.)])
def test_policy_counts_hand_yield_and_variations(tmp_path, policy, expected):
    plan, part, _ = run(tmp_path, recipe(tmp_path, policy), events(), chunk=2)
    # central: 2*.5 - 1*2 + 3*2 + 4*(2 if clamp else 1)
    nominal = part['variations']['nominal']
    assert nominal['cutflows']['selected'][-1][1] == pytest.approx(expected)
    assert nominal['events']['sum_generator'] == 8
    assert nominal['cutflows']['selected'][-1][2] == pytest.approx(105 if policy == 'clamp' else 57)
    counts = nominal['event_weights']['radiation correction']
    assert counts['rows'] == 4
    assert counts['axes']['multiplicity'] == {'below': 0, 'above': 1, 'clamped': int(policy == 'clamp'),
                                             'one': int(policy == 'one')}
    summary = engine.finalize(part, plan, {'mode': 'none'}, out_dir=tmp_path / 'output')
    for name, factor in [('correction up', 1.2), ('correction down', .8)]:
        # The out-of-range unit correction remains one in every variation.
        varied = expected * factor if policy == 'clamp' else (expected - 4) * factor + 4
        assert summary['cutflows'][name][0]['cuts'][-1]['yield'] == pytest.approx(varied)
    assert [s['name'] for s in summary['systematics']] == ['correction up', 'correction down']
    assert summary['event_weights']['nominal'] == nominal['event_weights']
    assert summary['histograms']['recoil distribution']['variations'] == ['correction up', 'correction down']
    assert summary['provenance']['efficiency_maps']['central']['sha256']


def test_two_axes_and_partition_merge(tmp_path):
    doc = recipe(tmp_path, 'one', two_axes=True)
    plan, part, path = run(tmp_path, doc, events())
    # (n,recoil)=(0,20),(1,60),(2,150),(3,30) => .5,3,1,1
    assert part['variations']['nominal']['cutflows']['selected'][-1][1] == 5
    parts = [engine.analyse({'inputs': [{'path': str(path), 'file_index': 7, 'entry_start': a,
                                        'entry_stop': b}], 'chunk_size': 1}, plan) for a, b in [(0, 2), (2, 4)]]
    assert engine.merge(parts)['variations'] == part['variations']


@pytest.mark.parametrize('mutate,message', [
    (lambda d: d['event_weights'][0].update(out_of_range='zero'), 'refuse, clamp or one'),
    (lambda d: d['event_weights'][0].update(observables=[]), 'one or two'),
    (lambda d: d['event_weights'][0].update(observables=['n', 'recoil']), 'one observable per map axis'),
    (lambda d: d['efficiency_maps']['central'].update(semantics='absolute', allow_above_one=False), 'between 0 and 1'),
    (lambda d: d['event_weights'][0].update(variations={'nominal': 'upper'}), 'not nominal'),
    (lambda d: d['event_weights'].append(copy.deepcopy(d['event_weights'][0])), 'defined twice'),
    (lambda d: d.update(systematics=[{'name': 'correction up', 'kind': 'weight-factor', 'multiply': ['weight']}]), 'unique'),
])
def test_invalid_event_weight_declarations(tmp_path, mutate, message):
    doc = recipe(tmp_path)
    mutate(doc)
    with pytest.raises(ValueError, match=message):
        compile_recipe(doc, formats.load_descriptor('delphes'), tmp_path)


def test_event_weights_follow_enumerated_objects_and_keep_correlated_moments(tmp_path):
    doc = recipe(tmp_path, 'clamp')
    (tmp_path / 'eff.json').write_text(json.dumps({'axes': [{'name': 'pt', 'unit': 'GeV', 'edges': [0, 100]}],
                                                  'values': [.5]}))
    doc['efficiency_maps']['id'] = {'source': {'format': 'json-grid', 'path': 'eff.json'},
                                    'axes': [{'name': 'pt', 'unit': 'GeV'}], 'out_of_range': 'refuse',
                                    'semantics': 'absolute', 'citation': 'synthetic'}
    doc['objects'].append({'efficiency': {'name': 'id', 'object': 'radiation', 'map': 'id', 'coordinates': ['pt'],
                                         'application': 'enumerate', 'card_efficiency': 'synthetic sample'}})
    _, part, _ = run(tmp_path, doc, events((1,)))
    rows = part['variations']['nominal']['cutflows']['selected']
    # One event, generator weight 2, half weight in n=0 and half in n=1.
    assert rows[-1] == pytest.approx([1, 2 * (.5 * .5 + .5 * 2), (2 * (.5 * .5 + .5 * 2)) ** 2])
    assert part['variations']['nominal']['event_weights']['radiation correction']['rows'] == 2


def test_undefined_coordinate_refuses_even_with_one_policy(tmp_path):
    doc = recipe(tmp_path, 'one')
    doc['observables'].append({'name': 'leading', 'op': 'field', 'object': 'radiation[0]', 'field': 'pt', 'unit': '1'})
    doc['event_weights'][0]['observables'] = ['leading']
    with pytest.raises(ValueError, match='event index 0.*undefined'):
        run(tmp_path, doc, events((0,)))


def test_event_correction_nodes_retain_typed_specification_mapping(tmp_path):
    doc = recipe(tmp_path)
    plan = compile_recipe(doc, formats.load_descriptor('delphes'), tmp_path)
    assert plan.spec_nodes['event weight radiation correction'] == []
    doc['event_weights'][0]['spec_item'] = 'correction-item'
    plan = compile_recipe(doc, formats.load_descriptor('delphes'), tmp_path)
    assert plan.spec_nodes['event weight radiation correction'] == ['correction-item']
