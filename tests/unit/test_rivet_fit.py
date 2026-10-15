"""Synthetic selected-stage polynomial transport; no native physics execution."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest
from scipy import optimize

from amplitude_fixtures import PARTICLES, points
from interference_chain_fixtures import case, runners, write
from test_weighted_events import _yoda
from ravel.physics import amplitude_basis as ab, amplitude_predictions as ap, amplitude_store as store
from ravel.physics import amplitude_polynomial as polynomial, rivet_fit, weighted_events as we
from ravel.physics.inference.differential import Model

pytestmark = pytest.mark.usefixtures('in_process_backend_seam')

EDGES = [0., 300., 800., 2000.]
MIGRATION = np.array([[.8, .1, 0.], [.2, .7, .3], [0., .2, .7]])
AMPLITUDES = np.array([[3., -.6, .4], [4., .7, -.3], [5., .2, .8]])


def toy(base, *, showered, representation='integrated', max_streams=4):
    """A three-bin amplitude A0 + x A1 + y A2 with four independent blocks."""
    basis = ab.Basis(['fixed', 'component-x', 'component-y'])
    baseline = {'id': 'baseline', 'constant': {'fixed': 1}, 'states': []}
    model = {'id': 'model', 'constant': {'fixed': 1}, 'states': [
        {'mass_gev': 10., 'width_gev': 2., 'propagator': 'fixed-width', 'couplings': {'component-x': 1}},
        {'mass_gev': 20., 'width_gev': 3., 'propagator': 'fixed-width', 'couplings': {'component-y': 1}}]}
    masses = np.array([100., 500., 1200.])
    momenta = points(70, 3)
    original_mass = np.sqrt(np.sum(momenta[:, :2, :], axis=1)[:, 3] ** 2
                            - np.sum(np.sum(momenta[:, :2, :3], axis=1) ** 2, axis=1))
    momenta *= (masses / original_mass)[:, None, None]
    coefficients = ab.coefficients(model, basis, masses ** 2)
    amplitudes = AMPLITUDES / coefficients
    grams = np.einsum('ni,nj->nij', np.conj(amplitudes), amplitudes)
    schedule = {'schema_version': 1, 'max_operation_seconds': 10, 'blocks': [
        {'id': f'b{k}', 'cohort': 'toy', 'seed': k + 1, 'draws': 5, 'max_seconds': 1} for k in range(4)]}

    def produce(block, writer):
        writer.append(gram=grams, factor=np.full(3, [.8, .9, 1.1, 1.2][block['seed'] - 1]),
                      observables=np.stack([masses ** 2, masses, masses / 2], axis=1), momenta=momenta)
        return {'attempted': 5, 'accepted': 3, 'rejected': 2, 'failed': 0}

    store.run_schedule(base / 'store', schedule, produce,
                       header={'basis': list(basis.members), 'factor_unit': 'pb', 'particles': PARTICLES,
                               'observables': ['s', 'mass', 'scale']})
    couplings = {'parameters': [{'name': p, 'unit': '', 'label': p} for p in ('x', 'y')],
                 'components': [{'states': [i], 'powers': {p: 1}} for i, p in enumerate(('x', 'y'))]}
    common = {'schema_version': 1, 'store': 'store', 'hypotheses': [baseline, model],
              'reference': 'baseline', 'reference_description': 'Synthetic baseline', 'coupling_polynomial': couplings}
    event_doc = {**common, 'kind': 'weighted-events', 'operation': 'rivet', 'invariant': 's', 'scale': 'scale',
                 'beams': {'pdg': 2212, 'sqrt_s_gev': 13000.}, 'max_streams': max_streams,
                 'format': 'lhe' if showered else 'hepmc3', 'unit': 'pb',
                 'rivet': {'program': '/inert/selection', 'analyses': ['SYN'], 'options': [],
                           'histograms': [{'path': '/SYN/toy', 'label': 'Synthetic mass', 'unit': 'GeV',
                                           'representation': representation}]},
                 'backend': {'kind': 'native', 'resources': {'cpus': 1, 'memory_mib': 64, 'wall_seconds': 10}}}
    if showered:
        event_doc['shower'] = {'program': '/inert/shower', 'settings': []}
    born_doc = {**common, 'kind': 'amplitude-predictions', 'selection': [], 'binning': {'edges': EDGES},
                'observable': {'name': 'mass', 'invariant': 's', 'unit': 'GeV', 'label': 'Synthetic mass'},
                'normalization': {'unit': 'pb', 'representation': representation}}
    write(base / 'events-input.json', event_doc)
    write(base / 'born-input.json', born_doc)
    return event_doc, born_doc


class SelectionBackend:
    """In-process event reader and RAW filler with a supplied migration matrix."""
    def __init__(self, edges, reference, migration):
        self.edges, self.reference, self.migration = edges, reference, np.asarray(migration)
        self.calls = []

    def prepare(self, spec, *, base=None):
        self.calls.append(spec['stage'])
        return {'spec': spec, 'plan_sha256': 'a' * 64, 'backend': {'local': True}}

    def submit(self, plan, attempt_dir):
        spec = plan['spec']
        stage = Path(spec['inputs'][0]['path']).parent
        if spec['stage'].startswith('shower-'):
            population = we.read_lhe(stage / 'events.lhe')
            events = []
            for e in population['events']:
                momenta = [(-np.asarray(p['momentum']) if p['status'] == -1 else p['momentum']) for p in e['particles']]
                events.append((momenta, e['scale'], e['weights']))
            we.write_hepmc3(stage / 'events.hepmc', events, particles=PARTICLES,
                           weight_names=population['weight_names'], sqrt_s_gev=13000., beam_pdg=2212, attempted=5)
            return {}
        population = we.read_hepmc3(stage / 'events.hepmc')
        text = ''
        for name in population['weight_names']:
            rows = np.zeros((len(self.edges) + 1, 2))
            for event in population['events']:
                p = np.sum([q['momentum'] for q in event['particles'] if q['status'] == 1], axis=0)
                mass = np.sqrt(p[3] ** 2 - p[:3] @ p[:3])
                index = np.searchsorted(self.edges, mass, side='right') - 1
                if 0 <= index < len(self.edges) - 1:
                    weights = self.migration[:, index] * event['weights'][name]
                    rows[1:-1, 0] += weights
                    rows[1:-1, 1] += weights ** 2
                else:
                    index = 0 if index < 0 else -1
                    weight = event['weights'][name]
                    rows[index] += (weight, weight ** 2)
            text += _yoda(we.raw_path('/SYN/toy', name, self.reference), self.edges, rows.tolist())
        (stage / 'rivet.yoda').write_text(text)
        return {}

    def observe(self, plan, handle):
        return {'state': 'succeeded'}

    def fetch(self, plan, handle, base):
        return {}


def selected_case(base, *, showered, representation='integrated', migration=MIGRATION, max_streams=4):
    doc, _ = toy(base, showered=showered, representation=representation, max_streams=max_streams)
    backend = SelectionBackend(EDGES, 'baseline', migration)
    we.run({'input': str(base / 'events-input.json')}, base, base / 'selected', backend=backend)
    ctx = ap.load({'input': str(base / 'born-input.json')}, base)
    born = ap.predict(ctx)
    ap.run({'input': str(base / 'born-input.json')}, base, base / 'born')
    raw = json.loads((base / 'selected/predictions.json').read_text())['/SYN/toy']
    selected = rivet_fit.selected_prediction(doc, ctx['hypotheses'], raw, edges=EDGES)
    fragment = json.loads((base / 'selected/binned/SYN--toy/differential-likelihood-input.json').read_text())
    diagnostic = rivet_fit.born_diagnostic(json.loads((base / 'born/predictions.json').read_text()), selected,
                                           declared_tolerance={'rtol': 1e-9, 'atol': 1e-12,
                                                               'covariance_rtol': 1e-8, 'covariance_atol': 1e-14})
    return doc, ctx, born, raw, selected, fragment, diagnostic, backend


@pytest.mark.parametrize('representation', ['integrated', 'differential'])
def test_two_coupling_migration_supplies_terms_covariance_and_injected_fit(tmp_path, representation):
    doc, ctx, born, raw, selected, fragment, diagnostic, backend = selected_case(
        tmp_path, showered=True, representation=representation)
    row = fragment['hypotheses'][0]
    roster = polynomial.terms(doc, ctx['hypotheses'])['model']
    assert [t['powers'] for t in row['terms']] == [{}, {'x': 1}, {'y': 1}, {'x': 2}, {'x': 1, 'y': 1}, {'y': 2}]
    divide = selected['divide']
    baseline, x, y = AMPLITUDES.T
    expected_born = [np.zeros(3), 2 * baseline * x, 2 * baseline * y, x ** 2, 2 * x * y, y ** 2]
    for term, descriptor, coefficient in zip(row['terms'], roster, expected_born):
        np.testing.assert_allclose(born['streams'][descriptor['stream']]['values'], coefficient / divide, atol=1e-12)
        expected = MIGRATION @ (np.asarray(born['streams'][descriptor['stream']]['values']) * divide) / divide
        np.testing.assert_allclose(term['values'], expected, rtol=1e-11, atol=1e-12)
    assert min(row['terms'][1]['values']) < 0
    names = [n for n, _ in born['definitions']]
    indices = [names.index(t['stream']) * 5 + i for t in roster for i in range(3)]
    projection = np.kron(np.eye(len(roster)), MIGRATION)
    cov = projection @ born['joint']['covariance'][np.ix_(indices, indices)] @ projection.T
    full_divide = np.tile(divide, len(roster))
    cov /= np.outer(full_divide, full_divide)
    np.testing.assert_allclose(row['mc_covariance'], cov, rtol=1e-10, atol=1e-13)
    assert np.any(cov[3:6, 6:9] != 0)
    assert diagnostic['status'] == 'outside-tolerance' and diagnostic['gate'] is False
    assert fragment['provenance']['stage'] == 'rivet-selected' and fragment['provenance']['showered'] is True
    assert any(c.startswith('shower-') for c in backend.calls)
    assert [b['attempted'] for b in raw['blocks']] == [5] * 4
    assert [b['events'] for b in raw['blocks']] == [3] * 4
    injected = {'x': .65, 'y': .9}
    monomials = np.array([np.prod([injected[p] ** k for p, k in t['powers'].items()]) for t in row['terms']])
    measured = np.asarray(fragment['reference_prediction']['values']) + monomials @ np.array([t['values'] for t in row['terms']])
    experimental = np.diag([.02, .03, .04]) / np.outer(divide, divide)
    model = Model(measured=measured, reference=fragment['reference_prediction']['values'], terms=row['terms'],
                  components=[{'law': 'fixed', 'matrix': experimental}], parameters=['x', 'y'],
                  mc_covariance=row['mc_covariance'], nuisances=[{'name': 'offset', 'applies_to': 'absolute',
                                                                'shift': np.array([.01, .02, .03]) / divide}])
    fit = optimize.minimize(lambda p: model.twice_nll(dict(zip(('x', 'y'), p))), [.4, .7], method='Nelder-Mead',
                            options={'xatol': 1e-10, 'fatol': 1e-12})
    assert fit.success
    np.testing.assert_allclose(fit.x, list(injected.values()), atol=1e-7)
    J = np.hstack([v * np.eye(3) for v in monomials])
    np.testing.assert_allclose(model.covariance(injected), experimental + J @ cov @ J.T, rtol=1e-10, atol=1e-12)
    assert abs(model.profile_nuisances(injected)['offset']) < 1e-10


def test_unshowered_identity_selection_matches_born_store(tmp_path):
    _, _, born, _, selected, fragment, diagnostic, backend = selected_case(tmp_path, showered=False, migration=np.eye(3))
    assert diagnostic['status'] == 'within-tolerance' and diagnostic['tolerance_source'] == 'caller'
    assert fragment['provenance']['showered'] is False
    assert not any(c.startswith('shower-') for c in backend.calls)
    for name, stream in selected['streams'].items():
        np.testing.assert_allclose(stream['values'], born['streams'][name]['values'], rtol=1e-11, atol=1e-12)
    np.testing.assert_allclose(selected['joint']['covariance'], born['joint']['covariance'], rtol=1e-10, atol=1e-12)


def test_chain_fits_and_delivers_selected_terms_when_born_equality_fails(tmp_path, monkeypatch):
    from ravel.physics import amplitude_chain
    request, integration_backend, _ = case(tmp_path, monkeypatch)
    # A declared unshowered selection also may migrate the stored observable.
    backend = SelectionBackend([0., 300., 2000.], 'reference', [[.8, .15], [.2, .85]])
    # Use the requested histogram path with the same inert RAW filler.
    original_submit = backend.submit
    def submit(plan, attempt_dir):
        result = original_submit(plan, attempt_dir)
        stage = Path(plan['spec']['inputs'][0]['path']).parent
        path = stage / 'rivet.yoda'
        path.write_text(path.read_text().replace('/SYN/toy', request['histogram']))
        return result
    backend.submit = submit
    request['born_comparison'] = {'rtol': 1e-9, 'atol': 1e-15, 'covariance_rtol': 1e-8, 'covariance_atol': 1e-20}
    parent = amplitude_chain.prepare(request, tmp_path / 'parent')
    result = amplitude_chain.run(parent, runners=runners(integration_backend, backend))
    assert result['status'] == 'passed'
    delivery = json.loads(Path(result['deliverable']['path']).read_text())
    assert delivery['born_comparison']['status'] == 'outside-tolerance'
    assert delivery['fitted_stage']['stage'] == 'rivet-selected'
    raw = json.loads(Path(delivery['fitted_prediction']['path']).read_text())[request['histogram']]
    fit_input = json.loads((Path(delivery['inference']['path']).parent / 'input.json').read_text())
    for term, suffix in zip(fit_input['hypotheses'][0]['terms'], ('constant', 'interference', 'pure-signal')):
        assert term['values'] == raw['streams']['candidate--' + suffix]['values']
    signed = json.loads(Path(delivery['signed_binned'][0]['path']).read_text())
    assert [b['value'] for b in signed['bins']] == raw['streams']['candidate--interference']['values']
    assert delivery['three_columns']['reproduced_reference']['values'] == raw['streams']['reference']['values']


@pytest.mark.parametrize('fault', ['term', 'layout', 'asymmetry', 'indefinite', 'nan', 'exposure', 'stage', 'unit',
                                 'stream_covariance', 'representation', 'histogram'])
def test_raw_integrity_is_still_required(tmp_path, fault):
    doc, ctx, _, raw, _, _, _, _ = selected_case(tmp_path, showered=False)
    raw = deepcopy(raw)
    if fault == 'term': raw['streams'].pop('model--term-1')
    elif fault == 'layout': raw['joint_layout']['streams'].reverse()
    elif fault == 'asymmetry': raw['joint_covariance'][0][1] += 1.
    elif fault == 'indefinite': raw['joint_covariance'][0][0] = -1.
    elif fault == 'nan': raw['joint_covariance'][0][0] = float('nan')
    elif fault == 'exposure': raw['blocks'][0]['attempted'] = 0
    elif fault == 'stage': raw['provenance']['stage'] = 'Born'
    elif fault == 'unit': raw['provenance']['unit'] = 'fb'
    elif fault == 'representation': raw['provenance']['representation'] = 'differential'
    elif fault == 'histogram': raw['provenance']['histogram'] = '/SYN/other'
    else: raw['streams']['model--term-1']['mc_covariance'][0][0] += 1.
    with pytest.raises(ValueError, match='RAW'):
        rivet_fit.selected_prediction(doc, ctx['hypotheses'], raw)


def test_polynomial_state_groups_cannot_overlap_or_scale_reference(tmp_path):
    doc, _ = toy(tmp_path, showered=False)
    doc['coupling_polynomial']['components'][1]['states'] = [0]
    with pytest.raises(ValueError, match='disjoint'):
        polynomial.contract(doc, doc['hypotheses'])
    doc['coupling_polynomial']['components'][1]['states'] = [1]
    doc['hypotheses'][0]['states'] = [deepcopy(doc['hypotheses'][1]['states'][0])]
    with pytest.raises(ValueError, match='reference'):
        polynomial.contract(doc, doc['hypotheses'])
