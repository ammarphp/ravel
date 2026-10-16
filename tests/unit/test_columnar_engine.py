"""The columnar analysis engine: recipes, partitions, merging and governed outputs."""
import json
import math

import numpy as np
import pytest
import uproot

from columnar_fixtures import RECIPE, Z_MASS, random_events, recipe, reference_event, write_delphes
from ravel.physics.columnar import engine, formats
from ravel.physics.columnar.recipe import compile_recipe


@pytest.fixture
def sample(tmp_path):
    events = random_events(400, seed=3)
    path = write_delphes(tmp_path / 'sample.root', events)
    return tmp_path, path, events


def plan_for(doc, base):
    return compile_recipe(doc, formats.load_descriptor('delphes'), base)


def whole(path, plan, chunk=97):
    return engine.analyse({'inputs': [{'path': str(path), 'file_index': 0}], 'chunk_size': chunk}, plan)


def test_selection_matches_an_independent_per_event_calculation(sample):
    base, path, events = sample
    plan = plan_for(RECIPE, base)
    partial = whole(path, plan)
    refs = [reference_event(ev) for ev in events]
    flows = partial['variations']['nominal']['cutflows']
    two = flows['two leptons']
    assert two[0][0] == len(events)
    assert two[0][1] == pytest.approx(sum(r['weight'] for r in refs))
    assert two[1][0] == sum(r['two'] for r in refs)
    three = flows['three leptons on Z']
    assert [row[0] for row in three][:2] == [len(events), sum(r['two'] for r in refs)]
    assert three[-1][0] == sum(r['three'] for r in refs) > 0
    assert three[-1][1] == pytest.approx(sum(r['weight'] for r in refs if r['three']))
    hist = partial['variations']['nominal']['histograms']['met in three-lepton region']
    expected = np.zeros(3); over = 0.0
    for r in refs:
        if r['three']:
            if r['met'] >= 200:
                over += r['weight']
            else:
                expected[np.searchsorted([30, 60, 120, 200], r['met'], side='right') - 1] += r['weight']
    np.testing.assert_allclose(hist['sumw'], expected)
    assert hist['overflow'][1] == pytest.approx(over)
    mll = partial['variations']['nominal']['histograms']['dilepton mass']
    defined = [r for r in refs if r['two'] and r['mll'] is not None]
    assert sum(mll['entries']) + mll['overflow'][0] == len(defined)
    assert mll['undefined'][0] == sum(1 for r in refs if r['two'] and r['mll'] is None)


def test_partitions_merge_to_the_whole_result(sample):
    base, path, events = sample
    doc = recipe()
    doc['efficiency_maps'] = {'jet tagging': {'source': {'format': 'json-grid', 'path': 'eff.json'},
                                              'axes': [{'name': 'jet transverse momentum', 'unit': 'GeV'}],
                                              'out_of_range': 'clamp', 'citation': 'synthetic test map', 'semantics': 'absolute'}}
    (base / 'eff.json').write_text(json.dumps({'axes': [{'name': 'jet transverse momentum', 'unit': 'GeV', 'edges': [20, 50, 1000]}],
                                               'values': [0.6, 0.8]}))
    doc['objects'] = doc['objects'][:8] + [{'efficiency': {'name': 'b tagging', 'object': 'bjets', 'map': 'jet tagging',
                                                           'coordinates': ['pt'], 'application': 'select', 'seed': 17,
                                                           'card_efficiency': 'the synthetic sample has no card tagging efficiency'}}] + doc['objects'][8:]
    plan = plan_for(doc, base)
    full = whole(path, plan, chunk=1000)
    parts = [engine.analyse({'inputs': [{'path': str(path), 'file_index': 0, 'entry_start': a, 'entry_stop': b}],
                             'chunk_size': 33}, plan) for a, b in ((0, 150), (150, 151), (151, 400))]
    merged = engine.merge(parts)
    for key in ('cutflows', 'histograms'):
        assert json.dumps(_rounded(merged['variations']['nominal'][key])) == json.dumps(_rounded(full['variations']['nominal'][key]))
    assert merged['variations']['nominal']['efficiency']['b tagging']['objects'] == \
        full['variations']['nominal']['efficiency']['b tagging']['objects'] > 0
    with pytest.raises(ValueError, match='different'):
        engine.merge([full, whole(path, plan_for(RECIPE, base))])


def _rounded(value):
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_rounded(v) for v in value]
    return round(value, 9) if isinstance(value, float) else value


def test_finalize_writes_template_ready_results_cutflow_and_provenance(sample, tmp_path):
    from ravel.workflow import result_templates as rt
    base, path, events = sample
    plan = plan_for(RECIPE, base)
    partial = whole(path, plan)
    normalization = {'mode': 'cross-section', 'cross_section_pb': 0.5, 'cross_section_source': 'synthetic value',
                     'luminosity_ifb': 100.0, 'luminosity_source': 'synthetic value', 'sum_of_weights': 'all-input-events'}
    out = tmp_path / 'out'
    result = engine.finalize(partial, plan, normalization, out_dir=out, input_files=[path])
    scale = 0.5 * 1000 * 100.0 / sum(np.float32(ev['Weight']) for ev in events)
    assert result['normalization']['scale'] == pytest.approx(scale)
    hist = json.loads((out / 'histograms' / 'met-in-three-lepton-region.json').read_text())
    assert hist['kind'] == 'binned_values' and hist['unit'] == 'events' and hist['axes'] == [{'name': 'Missing transverse momentum', 'unit': 'GeV'}]
    assert hist['quantity'] == {'weight_convention': 'signed'}
    raw = partial['variations']['nominal']['histograms']['met in three-lepton region']
    assert [b['value'] for b in hist['bins']] == pytest.approx([scale * x for x in raw['sumw']])
    assert [b['uncertainty'] for b in hist['bins']] == pytest.approx([scale * math.sqrt(x) for x in raw['sumw2']])
    assert hist['overflow'] == pytest.approx(scale * raw['overflow'][1])
    parsed = rt.Result((out / 'histograms' / 'met-in-three-lepton-region.json').read_bytes())
    template = {'schema_version': 1, 'kind': 'result_template', 'axes': [{'name': 'MET', 'unit': 'GeV'}], 'unit': 'events',
                'overflow': 'last-bin', 'description': 'last bin includes overflow',
                'bins': [{'low': [30], 'high': [60], 'value': None}, {'low': [60], 'high': [120], 'value': None},
                         {'low': [120], 'high': [200], 'value': None}]}
    (tmp_path / 'template.json').write_text(json.dumps(template))
    # The engine delivers underflow separately. A template that is silent about it cannot be
    # filled; the convention is declared with a sentence the template itself carries.
    silent = rt.Template(tmp_path / 'template.json', (tmp_path / 'template.json').read_bytes())
    assert parsed.underflow is not None and silent.conventions == {'overflow': 'last-bin', 'underflow': None}
    with pytest.raises(ValueError, match='separate underflow but no convention is declared'):
        rt._bind(silent, parsed, None)
    evidence = 'underflow stays outside the first bin'
    template['description'] = 'last bin includes overflow; ' + evidence
    (tmp_path / 'template.json').write_text(json.dumps(template))
    with pytest.raises(ValueError, match='mentions underflow'):
        rt.Template(tmp_path / 'template.json', (tmp_path / 'template.json').read_bytes())
    shape = rt.Template(tmp_path / 'template.json', (tmp_path / 'template.json').read_bytes(),
                        underflow='excluded', flow_evidence=evidence)
    assert shape.conventions == {'overflow': 'last-bin', 'underflow': 'excluded'}
    assert shape.convention_provenance['source'] == 'cli-declaration' and shape.convention_provenance['evidence'] == evidence
    rows, _, _ = rt._bind(shape, parsed, None)
    rt._values(shape, parsed, rows)
    assert rows[-1]['value'] == pytest.approx(scale * (raw['sumw'][-1] + raw['overflow'][1]))
    assert rows[0]['value'] == pytest.approx(scale * raw['sumw'][0])
    cutflow = json.loads((out / 'cutflow.json').read_text())
    assert cutflow['quantity'] == {'weight_convention': 'signed'}
    assert cutflow['kind'] == 'cutflow' and cutflow['regions'][1]['cuts'][-1]['name'] == 'missing momentum'
    assert cutflow['regions'][1]['cuts'][-1]['raw'] == partial['variations']['nominal']['cutflows']['three leptons on Z'][-1][0]
    summary = json.loads((out / 'analysis-result.json').read_text())
    assert summary['provenance']['recipe_sha256'] == plan.recipe_sha256
    assert summary['provenance']['inputs'][0]['sha256']
    assert summary['physics_validated'] is False
    assert {f['path'] for f in summary['files']} >= {'cutflow.json', 'histograms/met-in-three-lepton-region.json'}


def test_coverage_is_required_for_generated_weight_sums(sample, tmp_path):
    base, path, _ = sample
    plan = plan_for(RECIPE, base)
    part = engine.analyse({'inputs': [{'path': str(path), 'file_index': 0, 'entry_start': 0, 'entry_stop': 100}],
                           'chunk_size': 50}, plan)
    norm = {'mode': 'cross-section', 'cross_section_pb': 1.0, 'cross_section_source': 's', 'luminosity_ifb': 1.0,
            'luminosity_source': 's', 'sum_of_weights': 'all-input-events'}
    with pytest.raises(ValueError, match='every entry'):
        engine.finalize(part, plan, norm, out_dir=tmp_path / 'a')
    with pytest.raises(ValueError, match='overlap'):
        engine.merge([part, part])
    declared = dict(norm, sum_of_weights=1234.0, sum_of_weights_source='production receipt')
    result = engine.finalize(part, plan, declared, out_dir=tmp_path / 'b')
    assert result['normalization']['scale'] == pytest.approx(1000.0 / 1234.0)


def test_fraction_density_flow_conventions_and_precision(sample, tmp_path):
    base, path, _ = sample
    doc = recipe(histograms=[
        {'name': 'met fraction', 'region': 'two leptons', 'observable': 'met', 'edges': [0, 50, 100], 'unit': 'GeV',
         'label': 'Missing transverse momentum', 'normalization': 'fraction', 'overflow': 'last-bin',
         'fraction_denominator': 'all', 'mc_precision_target': 0.05},
        {'name': 'met density', 'region': 'two leptons', 'observable': 'met', 'edges': [0, 50, 100], 'unit': 'GeV',
         'label': 'Missing transverse momentum', 'normalization': 'density', 'fraction_denominator': 'in-range'},
        {'name': 'mll versus met', 'region': 'two leptons', 'observable': ['mll', 'met'], 'edges': [[0, 100, 200], [0, 50, 100]],
         'unit': ['GeV', 'GeV'], 'label': ['Dilepton mass', 'Missing transverse momentum'], 'normalization': 'raw'}])
    plan = plan_for(doc, base)
    partial = whole(path, plan)
    result = engine.finalize(partial, plan, {'mode': 'none'}, out_dir=tmp_path / 'o')
    raw = partial['variations']['nominal']['histograms']['met fraction']
    fraction = json.loads((tmp_path / 'o/histograms/met-fraction.json').read_text())
    total = sum(raw['sumw']) + raw['overflow'][1] + raw['underflow'][1]
    assert fraction['overflow_in_last_bin'] is True and 'overflow' not in fraction
    assert [b['value'] for b in fraction['bins']] == pytest.approx([raw['sumw'][0] / total, (raw['sumw'][1] + raw['overflow'][1]) / total])
    assert fraction['unit'] == 'fraction of events'
    density = json.loads((tmp_path / 'o/histograms/met-density.json').read_text())
    in_range = sum(raw['sumw'])
    assert density['representation'] == 'differential' and density['unit'] == '1/GeV'
    assert [b['value'] for b in density['bins']] == pytest.approx([x / in_range / 50 for x in raw['sumw']])
    two_d = json.loads((tmp_path / 'o/histograms/mll-versus-met.json').read_text())
    assert len(two_d['bins']) == 4 and two_d['unit'] == 'sum of event weights'
    precision = result['histograms']['met fraction']['nominal']['mc_precision']
    assert precision['target'] == 0.05 and len(precision['relative_uncertainty']) == 2


def test_weight_mode_efficiency_and_systematic_variations(sample, tmp_path):
    base, path, events = sample
    (base / 'eff.json').write_text(json.dumps({'axes': [{'name': 'photon pt', 'unit': 'GeV', 'edges': [0, 50, 10000]}], 'values': [0.5, 0.9]}))
    (base / 'eff-up.json').write_text(json.dumps({'axes': [{'name': 'photon pt', 'unit': 'GeV', 'edges': [0, 50, 10000]}], 'values': [0.6, 1.0]}))
    maps = {name: {'source': {'format': 'json-grid', 'path': f}, 'axes': [{'name': 'photon pt', 'unit': 'GeV'}],
                   'out_of_range': 'refuse', 'citation': 'synthetic', 'semantics': 'absolute'} for name, f in (('photon id', 'eff.json'), ('photon id up', 'eff-up.json'))}
    doc = recipe(efficiency_maps=maps,
                 objects=[{'name': 'photons', 'from': 'Photon', 'select': 'pt > 20'},
                          {'efficiency': {'name': 'photon identification', 'object': 'photons', 'map': 'photon id',
                                          'coordinates': ['pt'], 'application': 'all-required-weight',
                                          'card_efficiency': 'the detector card applies no photon identification efficiency'}}],
                 observables=[{'name': 'n_photons', 'op': 'count', 'collection': 'photons'},
                              {'name': 'st', 'op': 'scalar_sum', 'collections': ['photons'], 'include_met': True, 'unit': 'GeV'}],
                 regions=[{'name': 'one photon', 'cuts': [{'name': 'one photon', 'expr': 'n_photons >= 1'}]}],
                 histograms=[{'name': 'photon st', 'region': 'one photon', 'observable': 'st', 'edges': [0, 100, 1000],
                              'unit': 'GeV', 'label': 'Photon scalar sum with missing momentum', 'normalization': 'raw'}],
                 systematics=[{'name': 'photon identification up', 'kind': 'efficiency-map', 'step': 'photon identification', 'map': 'photon id up'},
                              {'name': 'weight squared', 'kind': 'weight-factor', 'multiply': ['weight']}])
    plan = plan_for(doc, base)
    partial = whole(path, plan)
    expected = 0.0; expected_up = 0.0; squared = 0.0
    for ev in events:
        photons = [p for p in ev['Photon'] if np.float32(p['PT']) > 20]
        if photons:
            w = float(np.float32(ev['Weight']))
            eff = math.prod(0.5 if np.float32(p['PT']) < 50 else 0.9 for p in photons)
            eff_up = math.prod(0.6 if np.float32(p['PT']) < 50 else 1.0 for p in photons)
            expected += w * eff; expected_up += w * eff_up; squared += w * w * eff
    variations = partial['variations']
    assert variations['nominal']['cutflows']['one photon'][-1][1] == pytest.approx(expected)
    assert variations['photon identification up']['cutflows']['one photon'][-1][1] == pytest.approx(expected_up)
    assert variations['weight squared']['cutflows']['one photon'][-1][1] == pytest.approx(squared)
    result = engine.finalize(partial, plan, {'mode': 'none'}, out_dir=tmp_path / 'o')
    assert (tmp_path / 'o/histograms/photon-st__photon-identification-up.json').is_file()
    assert result['histograms']['photon st']['variations'] == ['photon identification up', 'weight squared']


def test_event_record_and_undefined_counts(sample, tmp_path):
    base, path, events = sample
    doc = recipe(event_record={'max_events': 5, 'observables': ['met', 'mll'], 'regions': ['two leptons']})
    plan = plan_for(doc, base)
    parts = [engine.analyse({'inputs': [{'path': str(path), 'file_index': 0, 'entry_start': a, 'entry_stop': b}],
                             'chunk_size': 40}, plan) for a, b in ((0, 2), (2, 400))]
    merged = engine.merge(parts)
    rows = merged['event_record']
    assert [r['entry'] for r in rows] == [0, 1, 2, 3, 4]
    assert rows[0]['met'] == pytest.approx(float(np.float32(events[0]['MET'])))
    engine.finalize(merged, plan, {'mode': 'none'}, out_dir=tmp_path / 'o')
    lines = (tmp_path / 'o/event-record.jsonl').read_text().splitlines()
    assert len(lines) == 5
    assert [json.loads(x)['regions'] for x in lines] == [['two leptons'] if reference_event(ev)['two'] else [] for ev in events[:5]]
    undefined = merged['variations']['nominal']['undefined_observables']
    assert undefined['mll'] == sum(1 for ev in events if reference_event(ev)['mll'] is None)


def test_lhe_parton_level_selection_with_fraction_normalisation(tmp_path):
    import gzip
    from test_columnar_inputs import LHE
    with gzip.open(tmp_path / 'events.lhe.gz', 'wt') as stream:
        stream.write(LHE)
    descriptor = formats.Descriptor({
        'schema_version': 1, 'kind': 'columnar-format', 'name': 'parton level', 'format': 'lhe', 'source': 'synthetic',
        'collections': {'photons': {'pdg': [22]}, 'leptons': {'pdg': [11, -11], 'charge_from_pdg_sign': -1}},
        'invisible': {'pdg': [12, -12, 14, -14, 16, -16], 'source': 'neutrinos'}, 'event': {'weight': 'nominal'}})
    doc = {'schema_version': 1, 'kind': 'columnar-analysis-recipe', 'name': 'parton-level photon selection',
           'weights': {'generator': 'weight', 'factors': []},
           'objects': [{'name': 'photons', 'from': 'photons', 'select': 'pt > 20 and abs(eta) < 2.5'},
                       {'name': 'leptons', 'from': 'leptons', 'select': 'pt > 20'}],
           'observables': [{'name': 'n_photons', 'op': 'count', 'collection': 'photons'},
                           {'name': 'met', 'op': 'met', 'unit': 'GeV'}],
           'regions': [{'name': 'photon', 'cuts': [{'name': 'one photon', 'expr': 'n_photons >= 1'}]}],
           'histograms': [{'name': 'missing momentum', 'region': 'photon', 'observable': 'met',
                           'binning': {'uniform': {'low': 0, 'high': 1000, 'bins': 50}}, 'unit': 'GeV',
                           'label': 'Missing transverse momentum', 'normalization': 'fraction', 'fraction_denominator': 'all'}]}
    plan = compile_recipe(doc, descriptor, tmp_path)
    partial = engine.analyse({'inputs': [{'path': str(tmp_path / 'events.lhe.gz'), 'file_index': 0}], 'chunk_size': 10}, plan)
    result = engine.finalize(partial, plan, {'mode': 'cross-section', 'cross_section_pb': {'lhe_init': True},
                                             'cross_section_source': 'generator', 'luminosity_ifb': 1.0,
                                             'luminosity_source': 'synthetic', 'sum_of_weights': 'all-input-events'},
                             out_dir=tmp_path / 'o', input_files=[tmp_path / 'events.lhe.gz'])
    assert result['normalization']['cross_section_pb'] == pytest.approx(0.25)
    hist = json.loads((tmp_path / 'o/histograms/missing-momentum.json').read_text())
    assert sum(b['value'] for b in hist['bins']) == pytest.approx(1.0)
    assert hist['bins'][1]['value'] == pytest.approx(1.0)


@pytest.mark.parametrize('mutate, message', [
    (lambda d: d['observables'].append({'name': 'bad', 'op': 'mt', 'object': 'nothing[0]'}), 'unknown object'),
    (lambda d: d['observables'].append({'name': 'bad', 'op': 'mt2', 'assignments': [[['leptons[0]'], ['leptons[1]']]],
                                        'invisible_mass': 0.0}), 'source'),
    (lambda d: d['regions'].append({'name': 'r', 'cuts': [{'name': 'c', 'expr': 'unknown > 1'}]}), 'unknown name'),
    (lambda d: d['histograms'].append({'name': 'h', 'region': 'two leptons', 'observable': 'met', 'edges': [10, 5],
                                       'unit': 'GeV', 'label': 'x', 'normalization': 'yield'}), 'increase'),
    (lambda d: d['histograms'].append({'name': 'h', 'region': 'two leptons', 'observable': 'met', 'edges': [0, 5],
                                       'unit': 'GeV', 'label': 'met_raw', 'normalization': 'yield'}), 'label'),
    (lambda d: d['objects'].append({'name': 'jets', 'from': 'Jet'}), 'twice'),
    (lambda d: d['objects'].append({'name': 'x', 'from': 'Jet', 'select': 'nosuchfield > 1'}), 'unknown name'),
    (lambda d: d.update(weights={'generator': 'no such field', 'factors': []}), 'event field'),
])
def test_recipe_validation_refuses_malformed_declarations(tmp_path, mutate, message):
    doc = recipe()
    mutate(doc)
    with pytest.raises(ValueError, match=message):
        plan_for(doc, tmp_path)


def test_observable_library_on_a_constructed_event(tmp_path):
    events = [{'Electron': [{'PT': 50.0, 'Eta': 0.0, 'Phi': 0.0, 'Charge': -1, 'IsolationVar': 0.0},
                            {'PT': 40.0, 'Eta': 0.0, 'Phi': math.pi, 'Charge': 1, 'IsolationVar': 0.0}],
               'Jet': [{'PT': 100.0, 'Eta': 0.0, 'Phi': math.pi / 2, 'Mass': 0.0, 'BTag': 1, 'TauTag': 0, 'Charge': 0},
                       {'PT': 60.0, 'Eta': 0.0, 'Phi': -math.pi / 2 + 0.1, 'Mass': 0.0, 'BTag': 0, 'TauTag': 1, 'Charge': 1}],
               'EFlowTrack': [{'PT': 30.0, 'Eta': 0.0, 'Phi': 0.05, 'Mass': 0.0, 'Charge': 1, 'PID': 211},
                              {'PT': 3.0, 'Eta': 0.0, 'Phi': 0.1, 'Mass': 0.0, 'Charge': 1, 'PID': 211}],
               'MET': 80.0, 'METPhi': math.pi / 2, 'Weight': 1.0}]
    path = write_delphes(tmp_path / 'one.root', events)
    doc = {'schema_version': 1, 'kind': 'columnar-analysis-recipe', 'name': 'observable checks',
           'weights': {'generator': None, 'factors': []},
           'objects': [{'name': 'electrons', 'from': 'Electron'}, {'name': 'jets', 'from': 'Jet'},
                       {'name': 'tracks', 'from': 'EFlowTrack'},
                       {'isolation': {'object': 'tracks', 'against': 'tracks', 'cone': 0.3, 'field': 'iso', 'relative': True}},
                       {'name': 'isolated_tracks', 'from_object': 'tracks', 'select': 'pt > 10 and iso < 0.2'},
                       {'name': 'taus', 'from_object': 'jets', 'select': 'tautag == 1'},
                       {'name': 'light', 'from_object': 'jets', 'select': 'btag == 0'}],
           'observables': [
               {'name': 'mee', 'op': 'mass', 'objects': ['electrons[0]', 'electrons[1]'], 'unit': 'GeV'},
               {'name': 'mt_e', 'op': 'mt', 'object': 'electrons[0]', 'unit': 'GeV'},
               {'name': 'dphi_j_met', 'op': 'delta_phi', 'a': 'jets[0]', 'b': 'met'},
               {'name': 'dr_ee', 'op': 'delta_r', 'a': 'electrons[0]', 'b': 'electrons[1]'},
               {'name': 'min_dphi', 'op': 'min_delta_phi_met', 'collection': 'jets', 'max_objects': 2},
               {'name': 'ht', 'op': 'scalar_sum', 'collections': ['jets']},
               {'name': 'st', 'op': 'scalar_sum', 'collections': ['electrons', 'jets'], 'include_met': True},
               {'name': 'mjj_phi', 'op': 'pair_mass', 'collection': 'jets', 'choose': 'closest-in-phi'},
               {'name': 'min_m_ej', 'op': 'min_pair_mass', 'object': 'electrons[0]', 'candidates': 'jets', 'max_objects': 2},
               {'name': 'n_iso', 'op': 'count', 'collection': 'isolated_tracks'},
               {'name': 'tau_mt', 'op': 'mt', 'object': 'taus[0]', 'massless': False},
               {'name': 'isr_pt', 'op': 'field', 'object': 'light[0]', 'field': 'pt'},
               {'name': 'ee_sum', 'op': 'mass_sum', 'assignments': [[['electrons[0]', 'jets[0]'], ['electrons[1]', 'jets[1]']],
                                                                     [['electrons[0]', 'jets[1]'], ['electrons[1]', 'jets[0]']]]},
               {'name': 'nu_pz', 'op': 'neutrino_pz', 'lepton': 'electrons[0]', 'w_mass': 100.0, 'source': 'synthetic W mass'},
               {'name': 'vec', 'op': 'vector_sum_pt', 'collections': ['electrons'], 'include_met': False},
               {'name': 'only_some', 'op': 'mt', 'object': 'electrons[0]', 'only_if': 'ht > 1000'},
           ],
           'regions': [{'name': 'all', 'cuts': []}],
           'histograms': [],
           'event_record': {'max_events': 1, 'observables': ['mee', 'mt_e', 'dphi_j_met', 'dr_ee', 'min_dphi', 'ht', 'st',
                                                             'mjj_phi', 'min_m_ej', 'n_iso', 'tau_mt', 'isr_pt', 'ee_sum',
                                                             'nu_pz', 'vec', 'only_some']}}
    plan = compile_recipe(doc, formats.load_descriptor('delphes'), tmp_path)
    row = engine.analyse({'inputs': [{'path': str(path), 'file_index': 0}], 'chunk_size': 10}, plan)['event_record'][0]
    me = 0.00051099895
    e1 = 50.0 ** 2 + me ** 2; e2 = 40.0 ** 2 + me ** 2
    assert row['mee'] == pytest.approx(math.sqrt(2 * me ** 2 + 2 * (math.sqrt(e1) * math.sqrt(e2) + 50 * 40)), rel=1e-6)
    assert row['mt_e'] == pytest.approx(math.sqrt(2 * 50 * 80), rel=1e-6)
    assert row['dphi_j_met'] == pytest.approx(0.0, abs=1e-6)
    assert row['dr_ee'] == pytest.approx(math.pi, rel=1e-6)
    assert row['min_dphi'] == pytest.approx(0.0, abs=1e-6)
    assert row['ht'] == pytest.approx(160.0) and row['st'] == pytest.approx(330.0)
    assert row['mjj_phi'] == pytest.approx(math.sqrt(2 * 100 * 60 * (1 - math.cos(math.pi - 0.1))), rel=1e-5)
    assert row['min_m_ej'] == pytest.approx(min(math.sqrt(2 * 50 * 100 * (1 - math.cos(math.pi / 2))),
                                                math.sqrt(2 * 50 * 60 * (1 - math.cos(math.pi / 2 - 0.1)))), rel=1e-5)
    assert row['n_iso'] == 1
    tau_et = math.hypot(60.0, 0.0)
    assert row['tau_mt'] == pytest.approx(math.sqrt(2 * 60 * 80 * (1 - math.cos(math.pi - 0.1))), rel=1e-5)
    assert row['isr_pt'] == pytest.approx(60.0)
    assert row['vec'] == pytest.approx(10.0, rel=1e-5)
    assert row['only_some'] is None
    nu = row['nu_pz']
    lep = (50.0, 0.0, 0.0, math.sqrt(e1)); pnu = (0.0, 80.0, nu, math.hypot(80.0, nu))
    tot = [a + b for a, b in zip(lep, pnu)]
    assert math.sqrt(tot[3] ** 2 - tot[0] ** 2 - tot[1] ** 2 - tot[2] ** 2) == pytest.approx(100.0, rel=1e-6)
