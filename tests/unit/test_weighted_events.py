"""Weighted points as events with named weights; Rivet RAW absolute normalization."""
import json
from pathlib import Path

import numpy as np
import pytest

from amplitude_fixtures import BASIS, PARTICLES, build_store, hypotheses
from ravel.physics import amplitude_basis as ab
from ravel.physics import amplitude_store as store
from ravel.physics import weighted_events as we


def _events(tmp_path):
    manifest = build_store(tmp_path / 'store', blocks=4, points_per_block=5, draws=8)
    path = tmp_path / 'store' / manifest['blocks'][0]['path']
    basis = ab.Basis(BASIS)
    hyps = [ab.hypothesis(h, basis) for h in hypotheses()]
    names = we.stream_names([h['id'] for h in hyps], 'SM')
    events = list(we.block_events(path, basis, hyps, 'SM', s_observable='s_gev2', scale_observable='scale_gev', names=names))
    return path, basis, hyps, names, events


def test_stream_names_and_passes():
    names = we.stream_names(['SM', 'H400', 'A400'], 'SM')
    assert names == ['SM', 'H400', 'A400', 'H400-minus-SM', 'A400-minus-SM']
    chunks = we.passes(names, 'SM', max_streams=3)
    assert chunks == [['SM', 'H400', 'A400'], ['SM', 'H400-minus-SM', 'A400-minus-SM']]
    with pytest.raises(ValueError, match='hypothesis id'):
        we.stream_names(['SM', 'H 400'], 'SM')


def test_event_weights_are_absolute_and_average_to_the_cross_section(tmp_path):
    path, basis, hyps, names, events = _events(tmp_path)
    block = store.read_block(path)
    attempted = block['marker']['summary']['attempted']
    s = block['observables'][:, 0]
    direct = {h['id']: block['factor'] * ab.evaluate(block['gram'], ab.coefficients(h, basis, s)) for h in hyps}
    for name in ('SM', 'H400'):
        weights = np.array([e[2][name] for e in events])
        np.testing.assert_allclose(weights, direct[name] * attempted * 1e-3, rtol=1e-12)
        assert weights.sum() / attempted == pytest.approx(direct[name].sum() * 1e-3, rel=1e-12)
    diff = np.array([e[2]['A400-minus-SM'] for e in events])
    np.testing.assert_allclose(diff, (direct['A400'] - direct['SM']) * attempted * 1e-3, rtol=1e-9, atol=1e-15)


def test_lhe_round_trip_of_momenta_and_weights(tmp_path):
    path, basis, hyps, names, events = _events(tmp_path)
    receipt = we.write_lhe(tmp_path / 'block.lhe.gz', events, particles=PARTICLES, weight_names=names, nominal='SM',
                           beams=((2212, 6500.0), (2212, 6500.0)), attempted=8)
    back = we.read_lhe(tmp_path / 'block.lhe.gz')
    assert back['weight_names'] == names and back['idwtup'] == -4 and len(back['events']) == receipt['events'] == 5
    assert back['cross_section_pb'] == pytest.approx(receipt['cross_section_pb']['SM'], rel=1e-15)
    for (momenta, scale, weights), event in zip(events, back['events']):
        assert event['scale'] == pytest.approx(scale, rel=1e-9)
        assert event['weight'] == pytest.approx(weights['SM'], rel=1e-15)
        assert event['weights'] == pytest.approx(weights, rel=1e-15)
        incoming = [-np.array(p) for p in momenta[:2]]
        got = [np.array(p['momentum']) for p in event['particles']]
        np.testing.assert_allclose(got[:2], incoming, rtol=1e-15)
        np.testing.assert_allclose(got[2:], np.array(momenta[2:]), rtol=1e-15)
        assert [p['pdg'] for p in event['particles']] == PARTICLES['pdg']
        assert [p['status'] for p in event['particles']] == PARTICLES['status']


def test_hepmc3_round_trip(tmp_path):
    path, basis, hyps, names, events = _events(tmp_path)
    xs = {n: sum(e[2][n] for e in events) / 8 for n in names}
    we.write_hepmc3(tmp_path / 'block.hepmc', events, particles=PARTICLES, weight_names=names, sqrt_s_gev=13000.0,
                    beam_pdg=2212, attempted=8, cross_sections=xs)
    back = we.read_hepmc3(tmp_path / 'block.hepmc')
    assert back['weight_names'] == names and len(back['events']) == 5
    for (momenta, _, weights), event in zip(events, back['events']):
        assert event['weights'] == pytest.approx(weights, rel=1e-15)
        beams = [p for p in event['particles'] if p['status'] == 4]
        assert [b['momentum'][3] for b in beams] == [6500.0, 6500.0]
        final = [p['momentum'] for p in event['particles'] if p['status'] == 1]
        np.testing.assert_allclose(final, np.array(momenta[2:]), rtol=1e-15)
    assert 'GenCrossSection' in (tmp_path / 'block.hepmc').read_text()


def test_colour_flow_needs_a_colour_singlet_final_state(tmp_path):
    with pytest.raises(ValueError, match='initial states'):
        we.write_lhe(tmp_path / 'x.lhe', [], particles={'pdg': [21, 2, 11, -11], 'status': [-1, -1, 1, 1]},
                     weight_names=['SM'], nominal='SM', beams=((2212, 1.0), (2212, 1.0)), attempted=1)


def _yoda(path, edges, rows):
    lines = [f'BEGIN YODA_HISTO1D_V3 {path}', f'Path: {path}', 'Title: ', 'Type: Histo1D', '---',
             'Edges(A1): [' + ', '.join(f'{e:.6e}' for e in edges) + ']',
             '# sumW       \tsumW2        \tsumW(A1)     \tsumW2(A1)    \tnumEntries']
    lines += ['\t'.join(f'{v:.12e}' for v in (r[0], r[1], 0.0, 0.0, 1.0)) for r in rows]
    return '\n'.join(lines + ['END YODA_HISTO1D_V3', ''])


def test_raw_normalization_is_absolute_for_signed_streams():
    edges = [0.0, 1.0, 3.0]
    attempted = 4
    weights = {'SM': [(0.5, 2.0), (2.0, 1.0)], 'H400-minus-SM': [(0.5, -3.0), (2.0, 1.0)]}
    text = ''
    for stream, fills in weights.items():
        rows = [[0.0, 0.0] for _ in range(4)]
        for x, w in fills:
            i = 1 + int(np.searchsorted(edges, x, side='right') - 1)
            rows[i][0] += w
            rows[i][1] += w * w
        text += _yoda(we.raw_path('/ANA/m', stream, 'SM'), edges, rows)
    histos = we.read_yoda(text)
    out = we.normalize_raw(histos, histogram='/ANA/m', streams=['SM', 'H400-minus-SM'], nominal='SM',
                           attempted=attempted, weight_unit='pb', unit='fb')
    assert out['streams']['SM']['values'] == pytest.approx([2.0e3 / 4, 1.0e3 / 4])
    assert out['streams']['H400-minus-SM']['values'] == pytest.approx([-3.0e3 / 4, 1.0e3 / 4])
    # A routine scales each stream by crossSection()/sumOfWeights(). With one shower
    # cross section shared by every weight, a signed stream is rescaled to the
    # nominal cross section: wrong size and, here, wrong sign.
    nominal = np.array(histos['/RAW/ANA/m']['sumw'])
    signed = np.array(histos['/RAW/ANA/m[H400-minus-SM]']['sumw'])
    routine = we.routine_scaled(signed, cross_section=nominal.sum() / attempted, sum_of_weights=signed.sum())
    assert not np.allclose(routine * 1e3, out['streams']['H400-minus-SM']['values'])


def test_raw_normalization_refuses_missing_streams_and_mixed_edges():
    text = _yoda('/RAW/ANA/m', [0.0, 1.0], [[0, 0], [1, 1], [0, 0]])
    histos = we.read_yoda(text)
    with pytest.raises(ValueError, match='missing'):
        we.normalize_raw(histos, histogram='/ANA/m', streams=['SM', 'X'], nominal='SM', attempted=1)
    text += _yoda('/RAW/ANA/m[X]', [0.0, 2.0], [[0, 0], [1, 1], [0, 0]])
    with pytest.raises(ValueError, match='edges'):
        we.normalize_raw(we.read_yoda(text), histogram='/ANA/m', streams=['SM', 'X'], nominal='SM', attempted=1)


def test_block_covariance_from_raw_vectors_matches_numpy():
    rng = np.random.default_rng(3)
    vectors = []
    for _ in range(5):
        v = {'streams': {s: {'values': rng.normal(size=3).tolist(), 'underflow': 0.0, 'overflow': float(rng.normal())}
                         for s in ('SM', 'H400-minus-SM')}}
        vectors.append(we.block_vector(v, ['SM', 'H400-minus-SM']))
    joint = ab.centered_blocks({'all': vectors})
    np.testing.assert_allclose(joint['covariance'], np.cov(np.array(vectors).T) / 5, rtol=1e-12)


def test_pythia_card_keeps_frame_and_file_under_ravel_control():
    card = we.pythia_card('/data/b0.lhe.gz', ['PartonLevel:MPI = off', 'TimeShower:QEDshowerByL = on'])
    assert card.splitlines()[:2] == ['Beams:frameType = 4', 'Beams:LHEF = /data/b0.lhe.gz']
    with pytest.raises(ValueError, match='beams:lhef'):
        we.pythia_card('/data/b0.lhe.gz', ['Beams:LHEF = other.lhe'])


class _RivetBackend:
    """Fills /RAW/ histograms of the final-state mass for every weight, like a routine would."""

    def __init__(self, edges):
        self.edges, self.specs = edges, []

    def prepare(self, spec, *, base=None):
        self.specs.append(spec)
        return {'spec': spec, 'plan_sha256': 'a' * 64, 'backend': {'local': True}}

    def submit(self, plan, attempt_dir):
        spec = plan['spec']
        stage = Path(spec['inputs'][0]['path']).parent
        events = we.read_hepmc3(stage / 'events.hepmc')
        text = ''
        for name in events['weight_names']:
            rows = np.zeros((len(self.edges) + 1, 2))
            for e in events['events']:
                p = np.sum([q['momentum'] for q in e['particles'] if q['status'] == 1], axis=0)
                m = np.sqrt(p[3] ** 2 - p[0] ** 2 - p[1] ** 2 - p[2] ** 2)
                i = ab.bin_index([m], self.edges)[0]
                row = 0 if i == len(self.edges) - 1 else (len(self.edges) if i == len(self.edges) else i + 1)
                w = e['weights'][name]
                rows[row] += (w, w * w)
            text += _yoda(we.raw_path('/ANA/m', name, 'SM'), self.edges, rows.tolist())
        (stage / 'rivet.yoda').write_text(text)
        return {}

    def observe(self, plan, handle):
        return {'state': 'succeeded'}

    def fetch(self, plan, handle, base):
        return {}


def _mode_document(tmp_path, **changes):
    build_store(tmp_path / 'store')
    doc = {'schema_version': 1, 'kind': 'weighted-events', 'operation': 'rivet', 'store': 'store',
           'hypotheses': hypotheses(), 'reference': 'SM', 'reference_description': 'synthetic reference',
           'invariant': 's_gev2', 'scale': 'scale_gev', 'beams': {'pdg': 2212, 'sqrt_s_gev': 13000.0},
           'max_streams': 3, 'format': 'hepmc3', 'unit': 'fb',
           'rivet': {'program': 'rivet', 'analyses': ['ANA'], 'options': ['--ignore-beams'],
                     'histograms': [{'path': '/ANA/m', 'label': 'Final-state mass', 'unit': 'GeV', 'representation': 'integrated'}]},
           'backend': {'kind': 'native', 'resources': {'cpus': 1, 'memory_mib': 512, 'wall_seconds': 60}}}
    doc.update(changes)
    (tmp_path / 'events.json').write_text(json.dumps(doc))
    return {'input': str(tmp_path / 'events.json')}


@pytest.mark.usefixtures('in_process_backend_seam')
def test_rivet_raw_predictions_equal_direct_recombination(tmp_path):
    from ravel.physics import amplitude_predictions as ap
    edges = [0.0, 150.0, 300.0, 600.0]
    backend = _RivetBackend(edges)
    result = we.run(_mode_document(tmp_path), tmp_path, tmp_path / 'out', backend=backend)
    assert result['status'] == 'passed' and result['physics_validated'] is False
    assert backend.specs[0]['argv'] == ['rivet', '-a', 'ANA', '--ignore-beams', '-o', 'rivet.yoda', 'events.hepmc']
    assert len(backend.specs) == 4 * 2  # four blocks, two passes of at most three streams
    rivet = json.loads((tmp_path / 'out/predictions.json').read_text())['/ANA/m']
    doc = {'schema_version': 1, 'kind': 'amplitude-predictions', 'store': 'store', 'hypotheses': hypotheses(),
           'reference': 'SM', 'reference_description': 'synthetic reference', 'selection': [],
           'observable': {'name': 'mass_gev', 'label': 'Final-state mass', 'unit': 'GeV', 'invariant': 's_gev2'},
           'binning': {'edges': edges}, 'normalization': {'unit': 'fb', 'representation': 'integrated'}}
    (tmp_path / 'pred.json').write_text(json.dumps(doc))
    ap.run({'input': str(tmp_path / 'pred.json')}, tmp_path, tmp_path / 'pred')
    direct = json.loads((tmp_path / 'pred/predictions.json').read_text())['streams']
    for name in ('SM', 'H400', 'A400-minus-SM'):
        np.testing.assert_allclose(rivet['streams'][name]['values'], direct[name]['values'], rtol=1e-9)
        np.testing.assert_allclose(rivet['streams'][name]['uncertainty'], direct[name]['uncertainty'], rtol=1e-6)
    fragment = json.loads((tmp_path / 'out/binned/ANA--m/differential-likelihood-input.json').read_text())
    assert [h['id'] for h in fragment['hypotheses']] == ['H400', 'A400']


def test_lhe_events_need_a_declared_shower(tmp_path):
    with pytest.raises(ValueError, match='shower'):
        we.load(_mode_document(tmp_path, format='lhe'), tmp_path)
    with pytest.raises(ValueError, match='skip-weights'):
        doc = _mode_document(tmp_path)
        raw = json.loads(Path(doc['input']).read_text())
        raw['rivet']['options'] = ['--skip-weights']
        Path(doc['input']).write_text(json.dumps(raw))
        we.load(doc, tmp_path)


def test_export_only_writes_event_files(tmp_path):
    task = _mode_document(tmp_path, operation='export', format='lhe')
    del_rivet = json.loads(Path(task['input']).read_text())
    del del_rivet['rivet'], del_rivet['backend']
    Path(task['input']).write_text(json.dumps(del_rivet))
    result = we.run(task, tmp_path, tmp_path / 'out')
    assert result['files'] == 8
    files = json.loads((tmp_path / 'out/events.json').read_text())['files']
    back = we.read_lhe(files[0]['path'])
    assert back['weight_names'] == files[0]['streams']
