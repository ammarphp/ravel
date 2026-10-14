"""Measurement predictions from a Gram store: the measurement is supplied data."""
import json
from pathlib import Path

import numpy as np
import pytest

from amplitude_fixtures import build_store, hypotheses
from ravel.physics import amplitude_basis as ab
from ravel.physics import amplitude_predictions as ap
from ravel.physics import amplitude_store as store
from ravel.workflow.result_templates import Result

REPO = Path(__file__).resolve().parents[2]


def _table(path, edges, name='Synthetic mass'):
    rows = '\n'.join(f'  - {{low: {lo}, high: {hi}}}' for lo, hi in zip(edges[:-1], edges[1:]))
    values = '\n'.join(f'  - value: {1.0 + i}' for i in range(len(edges) - 1))
    path.write_text(f"independent_variables:\n- header: {{name: '{name}', units: GEV}}\n  values:\n{rows}\n"
                    f"dependent_variables:\n- header: {{name: 'Cross section', units: FB GEV-1}}\n  values:\n{values}\n")
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _document(tmp_path, **changes):
    build_store(tmp_path / 'store')
    doc = {'schema_version': 1, 'kind': 'amplitude-predictions', 'store': 'store', 'hypotheses': hypotheses(),
           'reference': 'SM', 'reference_description': 'synthetic reference',
           'observable': {'name': 'mass_gev', 'label': 'Synthetic mass', 'unit': 'GeV', 'invariant': 's_gev2'},
           'binning': {'edges': [0.0, 150.0, 300.0, 600.0]}, 'selection': [],
           'normalization': {'unit': 'pb', 'representation': 'integrated'}}
    doc.update(changes)
    (tmp_path / 'doc.json').write_text(json.dumps(doc))
    return {'input': str(tmp_path / 'doc.json')}


def _direct(tmp_path, edges, *, cut=None, unit_scale=1e-3):
    manifest = store.load_manifest(tmp_path / 'store')
    basis = ab.Basis(manifest['header']['basis'])
    hyps = {h['id']: ab.hypothesis(h, basis) for h in hypotheses()}
    cohorts = {}
    for row in manifest['blocks']:
        b = store.read_block(tmp_path / 'store' / row['path'])
        s, m = b['observables'][:, 0], b['observables'][:, 1]
        keep = np.ones(len(s), dtype=bool) if cut is None else m >= cut
        w = {k: b['factor'] * ab.evaluate(b['gram'], ab.coefficients(h, basis, s)) * unit_scale for k, h in hyps.items()}
        cohorts.setdefault(row['cohort'], []).append({k: ab.histogram(m[keep], v[keep], edges) for k, v in w.items()})
    total = {k: sum(np.mean([blk[k] for blk in blocks], axis=0) for blocks in cohorts.values()) for k in hyps}
    return total


def test_predictions_equal_direct_recombination(tmp_path):
    task = _document(tmp_path)
    result = ap.run(task, tmp_path, tmp_path / 'out')
    assert result['status'] == 'passed' and result['physics_validated'] is False
    record = json.loads((tmp_path / 'out/predictions.json').read_text())
    direct = _direct(tmp_path, np.array([0.0, 150.0, 300.0, 600.0]))
    for k in ('SM', 'H400', 'A400'):
        np.testing.assert_allclose(record['streams'][k]['values'], direct[k][:3], rtol=1e-12)
        assert record['streams'][k]['underflow'] == pytest.approx(direct[k][3], rel=1e-12, abs=1e-300)
        assert record['streams'][k]['overflow'] == pytest.approx(direct[k][4], rel=1e-12)
    np.testing.assert_allclose(record['streams']['H400-minus-SM']['values'], (direct['H400'] - direct['SM'])[:3], rtol=1e-9)
    assert len(record['blocks']) == 4 and all(b['attempted'] == 12 for b in record['blocks'])


def test_binned_values_results_are_accepted_by_the_result_reader(tmp_path):
    ap.run(_document(tmp_path), tmp_path, tmp_path / 'out')
    for path in (tmp_path / 'out/binned').glob('*.json'):
        parsed = Result(path.read_bytes())
        assert parsed.unit == 'pb' and len(parsed.values) == 3


def test_differential_representation_divides_bins_but_not_flows(tmp_path):
    ap.run(_document(tmp_path, normalization={'unit': 'fb', 'representation': 'differential'}), tmp_path, tmp_path / 'out')
    record = json.loads((tmp_path / 'out/predictions.json').read_text())
    direct = _direct(tmp_path, np.array([0.0, 150.0, 300.0, 600.0]), unit_scale=1.0)
    np.testing.assert_allclose(record['streams']['SM']['values'], direct['SM'][:3] / np.array([150, 150, 300]), rtol=1e-12)
    assert record['streams']['SM']['overflow'] == pytest.approx(direct['SM'][4], rel=1e-12)
    doc = json.loads((tmp_path / 'out/binned/SM.json').read_text())
    assert doc['unit'] == 'fb/GeV' and doc['representation'] == 'differential'


@pytest.mark.parametrize('edges', [[0.0, 150.0, 300.0, 600.0], [50.0, 100.0, 200.0, 250.0, 400.0, 1000.0]])
def test_hepdata_binning_of_any_table(tmp_path, edges):
    sha = _table(tmp_path / 'table.yaml', edges)
    task = _document(tmp_path, binning={'hepdata': {'path': 'table.yaml', 'sha256': sha}})
    ap.run(task, tmp_path, tmp_path / 'out')
    record = json.loads((tmp_path / 'out/predictions.json').read_text())
    assert record['edges'] == edges
    direct = _direct(tmp_path, np.array(edges))
    np.testing.assert_allclose(record['streams']['H400']['values'], direct['H400'][:-2], rtol=1e-12)
    assert any(p['path'].endswith('table.yaml') for p in record['inputs'])


def test_changed_table_is_refused(tmp_path):
    sha = _table(tmp_path / 'table.yaml', [0.0, 1.0, 2.0])
    task = _document(tmp_path, binning={'hepdata': {'path': 'table.yaml', 'sha256': sha}})
    _table(tmp_path / 'table.yaml', [0.0, 1.0, 3.0])
    with pytest.raises(ValueError):
        ap.run(task, tmp_path, tmp_path / 'out')


def test_selection_cuts_use_stored_observables(tmp_path):
    task = _document(tmp_path, selection=[{'observable': 'mass_gev', 'min': 200.0, 'max': None}])
    ap.run(task, tmp_path, tmp_path / 'out')
    record = json.loads((tmp_path / 'out/predictions.json').read_text())
    direct = _direct(tmp_path, np.array([0.0, 150.0, 300.0, 600.0]), cut=200.0)
    np.testing.assert_allclose(record['streams']['SM']['values'], direct['SM'][:3], rtol=1e-12)
    assert record['streams']['SM']['values'][0] == 0.0


def test_coupling_scaling_is_an_exact_polynomial(tmp_path):
    scaling = {'parameter': 'kappa', 'power': 1, 'states': [1], 'mc_covariance_at': 1.0}
    hyps = hypotheses()
    doubled = json.loads(json.dumps(hyps[1]))
    doubled['id'] = 'H400x2'
    doubled['states'][1]['couplings'] = {'scalar': 1.0}
    task = _document(tmp_path, hypotheses=[*hyps, doubled], coupling_scaling=scaling)
    ap.run(task, tmp_path, tmp_path / 'out')
    record = json.loads((tmp_path / 'out/predictions.json').read_text())
    s = record['streams']
    c, i, p = (np.array(s[f'H400:{t}']['values']) for t in ('constant', 'interference', 'pure-signal'))
    np.testing.assert_allclose(c + i + p, s['H400-minus-SM']['values'], rtol=1e-9, atol=1e-12 * np.abs(p).max())
    np.testing.assert_allclose(c + 2 * i + 4 * p, s['H400x2-minus-SM']['values'], rtol=1e-9, atol=1e-12 * np.abs(p).max())
    fragment = json.loads((tmp_path / 'out/differential-likelihood-input.json').read_text())
    row = next(h for h in fragment['hypotheses'] if h['id'] == 'H400')
    assert [t['powers'] for t in row['terms']] == [{}, {'kappa': 1}, {'kappa': 2}]
    assert [t['kind'] for t in row['terms']] == ['other', 'interference', 'pure-signal']
    assert fragment['signal']['convention'] == 'difference-to-reference'
    assert np.array(row['mc_covariance']).shape == (3, 3)


def test_failed_draws_and_incomplete_stores_are_refused(tmp_path):
    task = _document(tmp_path)
    manifest = json.loads((tmp_path / 'store/manifest.json').read_text())
    manifest['status'] = 'incomplete'
    (tmp_path / 'store/manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='incomplete'):
        ap.run(task, tmp_path, tmp_path / 'out')


def test_document_refusals(tmp_path):
    with pytest.raises(ValueError, match='not stored'):
        ap.run(_document(tmp_path, observable={'name': 'pt', 'label': 'x', 'unit': 'GeV', 'invariant': 's_gev2'}),
               tmp_path, tmp_path / 'out')
    with pytest.raises(ValueError, match='source'):
        ap.run(_document(tmp_path, normalization={'unit': 'fb', 'representation': 'integrated', 'factor': {'value': 2.0}}),
               tmp_path, tmp_path / 'out')
    with pytest.raises(ValueError, match='reference hypothesis'):
        ap.run(_document(tmp_path, coupling_scaling={'parameter': 'k', 'power': 1, 'states': [0], 'mc_covariance_at': 1.0}),
               tmp_path, tmp_path / 'out')


SPECTRUM = REPO / 'tests/fixtures/synthetic_spectrum/table.yaml'


def _fixture_identifiers():
    import hashlib
    import yaml
    document = yaml.safe_load(SPECTRUM.read_text())
    return [hashlib.sha256(SPECTRUM.read_bytes()).hexdigest(),
            *[str(q['value']) for q in document['dependent_variables'][0]['qualifiers']
              if q['name'] in ('fictional_record', 'fictional_routine')]]


def _assert_no_fixture_identity(product):
    identifiers = _fixture_identifiers()
    offenders = [p.relative_to(product).as_posix() for p in product.rglob('*.py')
                 if any(term in p.read_text(errors='ignore') for term in identifiers)]
    assert offenders == []


def test_no_measurement_identity_is_built_into_the_package():
    _assert_no_fixture_identity(REPO / 'src/ravel')


@pytest.mark.parametrize('index', [0, 1, 2])
def test_measurement_identity_guard_detects_a_planted_identifier(tmp_path, index):
    (tmp_path / 'product.py').write_text(repr(_fixture_identifiers()[index]))
    with pytest.raises(AssertionError):
        _assert_no_fixture_identity(tmp_path)


def test_binning_from_a_synthetic_table_fixture(tmp_path):
    import hashlib
    import shutil
    shutil.copyfile(SPECTRUM, tmp_path / 'table.yaml')
    sha = hashlib.sha256((tmp_path / 'table.yaml').read_bytes()).hexdigest()
    task = _document(tmp_path, binning={'hepdata': {'path': 'table.yaml', 'sha256': sha}},
                     normalization={'unit': 'fb', 'representation': 'differential'})
    ap.run(task, tmp_path, tmp_path / 'out')
    record = json.loads((tmp_path / 'out/predictions.json').read_text())
    assert record['edges'] == [20.0, 65.0, 145.0, 310.0, 760.0]
    doc = json.loads((tmp_path / 'out/binned/SM.json').read_text())
    assert doc['unit'] == 'fb/GeV' and len(doc['bins']) == 4
