"""Constructed HistFactory models: cabinetry builder, native-builder parity, per-region correlated
magnitudes, the published-total remainder and the constructed-likelihood command.

Every number is synthetic."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from ravel.physics.inference import constructed, model_construction, search, systematics

REPO = Path(__file__).resolve().parents[2]
PYHF_EXCLUDE = REPO / 'src' / 'ravel' / 'physics' / 'pyhf_exclude.py'


def registry(sources):
    return {'schema_version': 1, 'absent': [], 'sources': sources}


def cited(**row):
    return {'origin': 'cited', 'citation': 'synthetic note, table 1', **row}


def document(sources=None, *, mc_statistics='staterror', builder='cabinetry'):
    return {'regions': [{'name': 'SRa', 'role': 'SR', 'observed': [11.0, 5.0]},
                        {'name': 'SRb', 'role': 'SR', 'observed': [7.0]},
                        {'name': 'CRx', 'role': 'CR', 'observed': [200.0]}],
            'backgrounds': [{'name': 'bkg', 'normfactor': 'mu_b', 'yields': {
                'SRa': {'values': [10.0, 4.0], 'sumw2': [1.0, 0.4]}, 'SRb': {'values': [6.0], 'sumw2': [0.5]},
                'CRx': {'values': [190.0], 'sumw2': [20.0]}}}],
            'signal_points': [{'id': 'p', 'coordinates': {}, 'yields': {
                'SRa': {'values': [3.0, 2.0], 'sumw2': [0.1, 0.1]}, 'SRb': {'values': [1.5], 'sumw2': [0.05]},
                'CRx': {'values': [0.2], 'sumw2': [0.01]}}}],
            'mc_statistics': mc_statistics,
            'systematics': None if sources is None else registry(sources),
            'data': {'mode': 'observed', 'injections': {}},
            'computations': {'discovery': False, 'cls_at_nominal': True, 'cls_limits': False, 'background_only_fit': False},
            'asimov_source': 'nominal', 'cls_level': 0.05,
            'mc_adequacy': {'max_relative_uncertainty': 1.0, 'min_effective_entries': 1}, 'contours': None,
            'model_construction': {'builder': builder}}


NORMSYS = [cited(name='lumi', kind='normsys', relative=0.02, applies_to={'samples': 'all', 'regions': 'all'},
                 correlation='correlated'),
           cited(name='jes', kind='normsys', relative_by_region={'SRa': 0.05, 'SRb': 0.08},
                 applies_to={'samples': ['bkg'], 'regions': ['SRa', 'SRb']}, correlation='correlated')]
HISTOSYS = [cited(name='gen', kind='histosys', construction='one-sided-symmetrised',
                  applies_to={'samples': ['bkg'], 'regions': ['SRa']}, correlation='correlated',
                  alternative={'SRa': [11.0, 3.5]})]


def test_relative_by_region_is_one_correlated_parameter_with_per_region_magnitudes():
    reg = systematics.Registry(registry(NORMSYS))
    a = {m['name']: m for m in reg.modifiers('bkg', 'SRa', [10.0, 4.0])}
    b = {m['name']: m for m in reg.modifiers('bkg', 'SRb', [6.0])}
    assert a['jes']['data'] == {'hi': 1.05, 'lo': 0.95} and b['jes']['data'] == {'hi': 1.08, 'lo': 0.92}
    assert reg.summary()['sources'][1]['by_region'] == {'SRa': [1.05, 0.95], 'SRb': [1.08, 0.92]}
    with pytest.raises(ValueError, match='exactly the regions'):
        systematics.Registry(registry([{**NORMSYS[1], 'applies_to': {'samples': ['bkg'], 'regions': 'all'}}]))
    with pytest.raises(ValueError, match='alone'):
        systematics.Registry(registry([{**NORMSYS[1], 'relative': 0.1}]))
    with pytest.raises(ValueError, match='100%'):
        systematics.Registry(registry([{**NORMSYS[1], 'relative_by_region': {'SRa': 1.0, 'SRb': 0.1}}]))


def test_cabinetry_and_native_builders_agree_exactly_for_normalisation_registries(tmp_path):
    result = search.run(document(NORMSYS), construction_folder=tmp_path / 'mc')
    records = result['model_construction']['records']
    assert records and all(r['status'] == 'identical' and r['identical_spec'] for r in records)
    assert all(c['status'] == 'pass' for r in records for c in r['checks'])
    assert result['model_construction']['builder'] == 'cabinetry'
    assert records[0]['cabinetry_version'] == model_construction.CABINETRY_VERSION
    folder = Path(records[0]['histograms']['folder'])
    assert folder.exists() and all((folder / f).exists() for f in records[0]['histograms']['files'])


def test_shape_systematics_agree_at_one_sigma_and_record_the_representation_difference(tmp_path):
    result = search.run(document(NORMSYS + HISTOSYS), construction_folder=tmp_path / 'mc')
    record = result['model_construction']['records'][0]
    assert record['status'] == 'equivalent-at-one-sigma' and not record['identical_spec']
    names = {c['name']: c['status'] for c in record['checks']}
    assert names['one-sigma-templates'] == 'pass' and names['parameters'] == 'pass'
    cls = record['cls_at_unit_signal_on_background_asimov']
    assert 0 < cls['native'] < 1 and 0 < cls['cabinetry'] < 1 and cls['relative_difference'] < 1e-2
    assert 'NormPlusShape' in record['representation']['cabinetry']


def test_native_builder_result_is_unchanged_by_the_construction_block(tmp_path):
    plain = document(NORMSYS)
    del plain['model_construction']
    reference = search.run(plain)['points'][0]['cls_at_nominal']['expected']
    native = search.run(document(NORMSYS, builder='native'), construction_folder=tmp_path / 'mc')
    assert native['points'][0]['cls_at_nominal']['expected'] == pytest.approx(reference, rel=1e-9)
    assert native['model_construction']['builder'] == 'native'
    assert all(r['status'] == 'identical' for r in native['model_construction']['records'])


def test_a_parity_mismatch_refuses_the_model(tmp_path, monkeypatch):
    original = model_construction.cabinetry_channels

    def tampered(*args, **kwargs):
        channels, config, written = original(*args, **kwargs)
        channels[0]['samples'][0]['data'][0] *= 1.01
        return channels, config, written

    monkeypatch.setattr(model_construction, 'cabinetry_channels', tampered)
    with pytest.raises(ValueError, match='parity failed: nominal-yields'):
        search.run(document(NORMSYS), construction_folder=tmp_path / 'mc')


def test_shapesys_cannot_be_built_through_cabinetry(tmp_path):
    with pytest.raises(ValueError, match='staterror or none'):
        search.run(document(NORMSYS, mc_statistics='shapesys'), construction_folder=tmp_path / 'mc')
    with pytest.raises(ValueError, match='output folder'):
        search.run(document(NORMSYS))
    with pytest.raises(ValueError, match='builder'):
        search.SearchModel({**document(NORMSYS), 'model_construction': {'builder': 'other'}})


SRS = [{'name': 'SR1', 'n': 12, 'b': 10.0, 'db': 2.0, 's': 4.0},
       {'name': 'SR2', 'n': 3, 'b': 4.0, 'db': 1.0, 's': 2.5}]
BREAKDOWN = [cited(name='lumi', kind='normsys', relative=0.02, applies_to={'samples': 'all', 'regions': 'all'},
                   correlation='correlated'),
             cited(name='jes', kind='normsys', relative_by_region={'SR1': 0.1, 'SR2': 0.15},
                   applies_to={'samples': ['background'], 'regions': ['SR1', 'SR2']}, correlation='correlated')]


def test_constructed_model_preserves_the_published_total_uncertainty(tmp_path):
    model, data, record, doc = constructed.build(SRS, registry(BREAKDOWN), folder=tmp_path, regions_exclusive=True)
    for row, sr in zip(record['residuals'], SRS):
        declared = sr['b'] * np.hypot(0.02, {'SR1': 0.1, 'SR2': 0.15}[sr['name']])
        assert row['declared_quadrature'] == pytest.approx(declared)
        assert np.hypot(row['declared_quadrature'], row['remainder']) == pytest.approx(sr['db'])
    names = {s['name'] for s in doc['systematics']['sources']}
    assert names == {'lumi', 'jes', 'residual_SR1', 'residual_SR2'}
    assert set(model.config.par_order) == {'mu', 'lumi', 'jes', 'residual_SR1', 'residual_SR2'}
    assert record['parity']['status'] == 'identical' and record['mutual_exclusivity'].startswith('declared')
    assert list(data[:2]) == [12.0, 3.0]


def test_constructed_model_matches_an_independent_hand_built_pyhf_model(tmp_path):
    import pyhf
    from ravel.physics import pyhf_exclude
    model, data, record, _ = constructed.build(SRS, registry(BREAKDOWN), folder=tmp_path, regions_exclusive=True)
    channels = []
    for sr in SRS:
        r_res = next(row['relative'] for row in record['residuals'] if row['region'] == sr['name'])
        jes = {'SR1': 0.1, 'SR2': 0.15}[sr['name']]
        channels.append({'name': sr['name'], 'samples': [
            {'name': 'background', 'data': [sr['b']], 'modifiers': [
                {'name': 'lumi', 'type': 'normsys', 'data': {'hi': 1.02, 'lo': 0.98}},
                {'name': 'jes', 'type': 'normsys', 'data': {'hi': 1 + jes, 'lo': 1 - jes}},
                {'name': 'residual_' + sr['name'], 'type': 'normsys', 'data': {'hi': 1 + r_res, 'lo': 1 - r_res}}]},
            {'name': 'signal', 'data': [sr['s']], 'modifiers': [
                {'name': 'mu', 'type': 'normfactor', 'data': None},
                {'name': 'lumi', 'type': 'normsys', 'data': {'hi': 1.02, 'lo': 0.98}}]}]})
    reference = pyhf.Model({'channels': channels}, poi_name='mu', modifier_settings=pyhf_exclude.MODIFIER_SETTINGS)
    ref_data = [12.0, 3.0] + list(reference.config.auxdata)
    ours = float(pyhf.infer.hypotest(1.0, data, model, test_stat='qtilde'))
    theirs = float(pyhf.infer.hypotest(1.0, ref_data, reference, test_stat='qtilde'))
    assert ours == pytest.approx(theirs, rel=1e-9)


def test_constructed_model_refusals(tmp_path):
    with pytest.raises(ValueError, match='regions_exclusive'):
        constructed.build(SRS, registry(BREAKDOWN), folder=tmp_path, regions_exclusive=False)
    too_large = [cited(name='big', kind='normsys', relative=0.5, applies_to={'samples': 'all', 'regions': 'all'},
                       correlation='correlated')]
    with pytest.raises(ValueError, match='exceed the published total'):
        constructed.build(SRS, registry(too_large), folder=tmp_path, regions_exclusive=True)
    with pytest.raises(ValueError, match='absent from the yield record'):
        constructed.build(SRS, registry([{**BREAKDOWN[1], 'relative_by_region': {'SR1': 0.1, 'SR9': 0.1},
                                          'applies_to': {'samples': ['background'], 'regions': ['SR1', 'SR9']}}]),
                          folder=tmp_path, regions_exclusive=True)
    with pytest.raises(ValueError, match='100%'):
        constructed.build([{'name': 'SR1', 'n': 1, 'b': 0.5, 'db': 0.6, 's': 1.0}], registry([]), folder=tmp_path,
                          regions_exclusive=True)
    with pytest.raises(ValueError, match='"all" or'):
        constructed.build(SRS, registry([{**BREAKDOWN[0], 'applies_to': {'samples': ['other'], 'regions': 'all'}}]),
                          folder=tmp_path, regions_exclusive=True)


def test_constructed_command_writes_a_typed_exclusion_record(tmp_path):
    from ravel.limits import read_limits
    srs, reg = tmp_path / 'srs.json', tmp_path / 'systematics.json'
    srs.write_text(json.dumps(SRS))
    reg.write_text(json.dumps(registry(BREAKDOWN)))
    out = tmp_path / 'out'
    base = [sys.executable, str(PYHF_EXCLUDE), 'constructed', '--srs', str(srs), '--systematics', str(reg),
            '--out', str(out), '--label', 'synthetic']
    refused = subprocess.run(base, capture_output=True, text=True, cwd=tmp_path)
    assert refused.returncode != 0 and 'regions-exclusive' in refused.stderr
    # SR2 is a small-count region, so the automatic policy would run toys; the explicit
    # asymptotic request keeps the test fast and must still record the trigger.
    run = subprocess.run(base + ['--regions-exclusive', '--cls-calculator', 'asymptotic'],
                         capture_output=True, text=True, cwd=tmp_path)
    assert run.returncode == 0, run.stdout + run.stderr
    res = json.loads((out / 'exclusion.json').read_text())
    assert res['calculator']['applied'] == 'asymptotic' and res['calculator']['reason'] == 'requested'
    assert res['calculator']['triggers'] and res['calculator']['toys'] is None
    assert res['mode'] == 'constructed' and res['stat_mode'] == 'constructed-likelihood'
    assert res['construction']['builder'] == 'cabinetry' and res['construction']['parity']['status'] == 'identical'
    assert {r['region'] for r in res['construction']['residuals']} == {'SR1', 'SR2'}
    assert res['per_sr']['SR2']['low_count_flags'] == ['b<5', 'n<5']
    limits = read_limits(res)
    assert limits.observed.status == 'resolved' and limits.observed.value == pytest.approx(res['obs_limit'])
    assert res['model_scope']['mutual_exclusivity'].startswith('declared')
    assert (out / 'exclusion.png').exists() and (out / 'model_construction').is_dir()
    assert res['computed_check_summary']
