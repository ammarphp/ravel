"""Typed analysis specification: spans, the ambiguity oracle and recipe coverage."""
import copy
import json

import numpy as np
import pytest

from columnar_fixtures import RECIPE, random_events, write_delphes
from ravel.physics.columnar import engine, formats
from ravel.physics.columnar.recipe import compile_recipe
from ravel.workflow import analysis_spec, spec_ambiguity

PAPER = b"""Electrons have pT > 10 GeV and |eta| < 2.47.
Muons have pT > 10 GeV and |eta| < 2.5.
Jets have pT > 20 GeV; jets within 0.2 of an electron are removed.
Events have at least two leptons.
Signal events have three leptons with a same-flavour opposite-charge pair within 15 GeV of the Z mass.
The missing transverse momentum exceeds 30 GeV.
The missing transverse momentum distribution is shown in events per GeV after all cuts.
The dilepton mass distribution is normalised to unit area.
"""


def _span(line):
    return analysis_spec.span_for(PAPER, 'paper', line, line)


def _explicit(value, line, unit=None):
    out = {'value': value, 'status': 'explicit', 'span': _span(line)}
    if unit:
        out['unit'] = unit
    return out


def _spec():
    return {'schema_version': 1, 'kind': 'typed-analysis-spec', 'analysis': 'generic three-lepton selection',
            'sources': [{'id': 'paper', 'path': 'paper.txt'}],
            'items': [
                {'id': 'electrons', 'role': 'object', 'family': 'electron', 'fields': {'pt_min': _explicit(10, 1, 'GeV')}},
                {'id': 'muons', 'role': 'object', 'family': 'muon', 'fields': {'pt_min': _explicit(10, 2, 'GeV')}},
                {'id': 'jets', 'role': 'object', 'family': 'jet', 'fields': {'pt_min': _explicit(20, 3, 'GeV')}},
                {'id': 'tracks', 'role': 'object', 'family': 'track',
                 'fields': {'pt_min': {'value': 5, 'status': 'inferred', 'note': 'detector tracking threshold'}}},
                {'id': 'jet-electron-overlap', 'role': 'overlap',
                 'fields': {'remove': _explicit('jets', 3), 'near': _explicit('electrons', 3), 'dr': _explicit(0.2, 3)}},
                {'id': 'lepton-cleaning', 'role': 'overlap',
                 'fields': {'dr': {'value': 0.4, 'status': 'inferred', 'note': 'standard lepton-jet cleaning'}}},
                {'id': 'derived-objects', 'role': 'object', 'family': 'derived',
                 'fields': {'note': {'value': 'b-jets, leptons and the Z pair', 'status': 'inferred', 'note': 'bookkeeping'}}},
                {'id': 'observables', 'role': 'observable', 'fields': {'name': {'value': 'all', 'status': 'inferred', 'note': 'all'}}},
                {'id': 'two-leptons', 'role': 'cut', 'region': 'two leptons', 'order': 1, 'fields': {'n': _explicit(2, 4)}},
                {'id': 'three-leptons', 'role': 'cut', 'region': 'three leptons on Z', 'order': 2, 'fields': {'n': _explicit(3, 5)}},
                {'id': 'on-z', 'role': 'cut', 'region': 'three leptons on Z', 'order': 3, 'fields': {'window': _explicit(15, 5, 'GeV')}},
                {'id': 'met-cut', 'role': 'cut', 'region': 'three leptons on Z', 'order': 4, 'fields': {'threshold': _explicit(30, 6, 'GeV')}},
                {'id': 'met-hist', 'role': 'histogram', 'region': 'three leptons on Z',
                 'fields': {'normalization_basis': _explicit('xsec', 7), 'fill_after': _explicit('met-cut', 7)}},
                {'id': 'mll-hist', 'role': 'histogram', 'region': 'two leptons',
                 'fields': {'normalization_basis': _explicit('in_range_N', 8),
                            'fill_after': {'value': 'two-leptons', 'status': 'inferred', 'note': 'region definition'}}},
            ]}


def _recipe_with_ids():
    doc = copy.deepcopy(RECIPE)
    ids = ['electrons', 'muons', 'jets', 'tracks', 'jet-electron-overlap', 'lepton-cleaning', 'lepton-cleaning',
           'derived-objects', 'derived-objects', 'derived-objects']
    for step, item in zip(doc['objects'], ids):
        step['spec_item'] = item
    for obs in doc['observables']:
        obs['spec_item'] = 'observables'
    doc['regions'][0]['cuts'][0]['spec_item'] = 'two-leptons'
    for cut, item in zip(doc['regions'][1]['cuts'], ['three-leptons', 'on-z', 'met-cut']):
        cut['spec_item'] = item
    doc['histograms'][0].update(spec_item='met-hist', normalization='yield-per-width')
    doc['histograms'][0]['overflow'] = doc['histograms'][0]['underflow'] = 'separate'
    doc['histograms'][1].update(spec_item='mll-hist', normalization='fraction', fraction_denominator='in-range')
    return doc


@pytest.fixture
def base(tmp_path):
    (tmp_path / 'paper.txt').write_bytes(PAPER)
    return tmp_path


def _plan(base, doc):
    return compile_recipe(doc, formats.load_descriptor('delphes', base), base)


def test_spans_are_checked_byte_exactly(base):
    spec = analysis_spec.load(_spec(), base)
    assert spec['items']['electrons']['fields']['pt_min']['excerpt'].startswith('Electrons have pT > 10 GeV')
    bad = _spec()
    bad['items'][0]['fields']['pt_min']['span']['line_start'] = 2
    bad['items'][0]['fields']['pt_min']['span']['line_end'] = 2
    with pytest.raises(ValueError, match='differ'):
        analysis_spec.load(bad, base)
    unspanned = _spec()
    del unspanned['items'][0]['fields']['pt_min']['span']
    with pytest.raises(ValueError, match='explicit field needs a span'):
        analysis_spec.load(unspanned, base)
    vague = _spec()
    vague['items'][3]['fields']['pt_min'].pop('note')
    with pytest.raises(ValueError, match='inferred'):
        analysis_spec.load(vague, base)


def test_ambiguity_oracle_names_seeded_ambiguities(base):
    doc = _spec()
    doc['items'] += [
        {'id': 'baseline-jets', 'role': 'object', 'family': 'jet', 'fields': {}},
        {'id': 'two-leading-jets', 'role': 'cut', 'region': 'jets', 'order': 1,
         'collection': {'value': 'jet', 'status': 'inferred', 'note': 'the paper says "two leading jets"'}, 'fields': {}},
        {'id': 'b-veto', 'role': 'cut', 'region': 'jets', 'order': 2,
         'collection': {'value': 'jets', 'status': 'inferred', 'note': 'raw or cleaned is not stated'},
         'fields': {'kind': {'value': 'veto', 'status': 'inferred', 'note': 'no b-tagged jets'}}},
        {'id': 'unordered', 'role': 'cut', 'region': 'loose', 'impact_estimate': 0.2, 'fields': {}},
        {'id': 'open-hist', 'role': 'histogram', 'region': 'loose', 'fields': {}}]
    result = spec_ambiguity.find(analysis_spec.load(doc, base))
    blocking = {(b['item'], b['category']) for b in result['blocking']}
    assert ('two-leading-jets', 'collection_scope') in blocking
    assert ('b-veto', 'veto_scope') in blocking
    assert ('open-hist', 'normalization_basis') in blocking
    assert ('unordered', 'cut_ordering') in blocking  # above the 10 per cent impact threshold
    assert ('baseline-jets', 'object_reuse') not in blocking
    assumptions = {(a['item'], a['category']) for a in result['assumptions']}
    assert ('mll-hist', 'fill_timing') in assumptions and ('baseline-jets', 'object_reuse') in assumptions
    assert result['categories_version'] == 1


def test_ambiguities_are_capped_per_group(base):
    doc = _spec()
    doc['items'] += [{'id': f'h{k}', 'role': 'histogram', 'region': 'many',
                      'fields': {'normalization_basis': _explicit('xsec', 7)}} for k in range(8)]
    result = spec_ambiguity.find(analysis_spec.load(doc, base))
    group = [a for a in result['ambiguities'] if a.get('item', '').startswith('h') and a['category'] == 'fill_timing']
    assert len(group) == spec_ambiguity.CAP
    assert any(a['category'] == 'cap' and a['omitted'] == 3 for a in result['ambiguities'])


def test_recipe_coverage_in_both_directions(base):
    spec = analysis_spec.load(_spec(), base)
    report = analysis_spec.coverage(spec, _plan(base, _recipe_with_ids()))
    assert report['passed'], report
    doc = _recipe_with_ids()
    del doc['observables'][0]['spec_item']
    doc['regions'][1]['cuts'][2].pop('spec_item')
    report = analysis_spec.coverage(spec, _plan(base, doc))
    assert 'observable n_leptons' in report['nodes_without_spec_item']
    assert report['unimplemented_spec_items'] == ['met-cut'] and not report['passed']
    doc = _recipe_with_ids()
    doc['histograms'][1]['fraction_denominator'] = 'all'
    report = analysis_spec.coverage(spec, _plan(base, doc))
    assert any('in_range_N' in e for e in report['normalization_basis_errors'])
    rows = analysis_spec.admission_definitions(spec, 'paper')
    assert {tuple(sorted(r)) for r in rows} == {('artifact', 'definition', 'id', 'locator', 'role')}
    assert rows[0]['locator'] == 'paper lines 1-1'


def test_slice_area_normalisation(base, tmp_path):
    doc = _spec()
    doc['items'].append({'id': 'slice', 'role': 'histogram', 'region': 'two leptons',
                         'slice': {'variable': 'leading lepton transverse momentum', 'low': 20, 'high': 40},
                         'fields': {'normalization_basis': {'value': 'bin_width_area_2D', 'status': 'inferred',
                                                            'note': 'double-differential table'}}})
    spec = analysis_spec.load(doc, base)
    recipe = _recipe_with_ids()
    hist = {'name': 'mll slice', 'region': 'two leptons', 'observable': 'mll', 'edges': [0, 100, 200], 'unit': 'GeV',
            'label': 'Same-flavour opposite-charge dilepton mass', 'normalization': 'yield-per-width', 'spec_item': 'slice'}
    recipe['histograms'].append(hist)
    report = analysis_spec.coverage(spec, _plan(base, recipe))
    assert any('slice width 20' in e for e in report['normalization_basis_errors'])
    hist['slice_width'] = {'value': 20, 'unit': 'GeV', 'variable': 'leading lepton transverse momentum'}
    plan = _plan(base, recipe)
    assert analysis_spec.coverage(spec, plan)['passed']
    # The engine divides by the slice width as well as the bin width.
    path = write_delphes(tmp_path / 'e.root', random_events(80, seed=3))
    partial = engine.analyse({'inputs': [{'path': str(path), 'file_index': 0}]}, plan)
    result = engine.finalize(partial, plan, {'mode': 'none'}, out_dir=tmp_path / 'out')
    doc_slice = json.loads((tmp_path / 'out' / result['histograms']['mll slice']['nominal']['file']).read_text())
    sumw = partial['variations']['nominal']['histograms']['mll slice']['sumw']
    np.testing.assert_allclose([b['value'] for b in doc_slice['bins']], np.asarray(sumw) / (100 * 20))


def test_columnar_study_refuses_open_ambiguities_and_reports_assumptions(base):
    from ravel.physics import columnar_analysis as mode
    write_delphes(base / 'a.root', random_events(40, seed=8))
    (base / 'recipe.json').write_text(json.dumps(_recipe_with_ids()))
    task = {'recipe': 'recipe.json', 'format': 'delphes', 'inputs': ['a.root'], 'normalization': {'mode': 'none'},
            'analysis_spec': 'spec.json'}
    (base / 'spec.json').write_text(json.dumps(_spec()))
    files = mode.inputs(task, base)
    assert {p.name for p in files} >= {'spec.json', 'paper.txt', 'recipe.json', 'a.root'}
    result = mode.run(task, base, base / 'out')
    assert result['specification']['coverage_passed'] is True
    assert any(a['category'] == 'fill_timing' for a in result['specification']['assumptions'])
    blocked = _spec()
    blocked['items'][-1]['fields']['normalization_basis'] = {'value': 'in_range_N', 'status': 'inferred', 'note': 'guess'}
    (base / 'spec.json').write_text(json.dumps(blocked))
    with pytest.raises(ValueError, match='normalization_basis'):
        mode.inputs(task, base)
