"""Lensed CMB power spectra and CAMB/CLASS cross-engine comparison."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from ravel.physics import cosmology_solver as c

PLANCK_LIKE = {'H0': 67.4, 'omega_b': .0224, 'omega_cdm': .12, 'A_s': 2.1e-9, 'n_s': .965, 'tau': .054,
               'T_CMB': 2.7255, 'YHe': .245, 'N_eff': 3.046, 'mnu_ev': .06, 'num_massive_nu': 1}


def document(engine='camb', ell_max=40, spectra=('TT', 'EE', 'TE'), points=1):
    engines = 2 if engine == 'camb+class' else 1
    return {'schema_version': 1, 'engine': engine, 'source': 'supplied engineering control',
            'profile': 'lensed-cmb-cl', 'points': [{'id': 'p' + str(i), 'parameters': deepcopy(PLANCK_LIKE)} for i in range(points)],
            'grid': {'ell_max': ell_max, 'spectra': list(spectra)}, 'model': None, 'components': None,
            'runtime': {'python': {}, 'manifest': {}}, 'trusted_runtime': True,
            'operation_resources': {'schema_version': 1, 'kind': 'solver', 'generated_events': 0,
                                    'solver_evaluations': points * engines, 'max_seconds': 120},
            'max_ram_mib': 1024, 'measurement': None}


def camb_rows(lmax, scale=1.0):
    # Columns TT, EE, BB, TE in muK^2, rows ell = 0..lmax.
    return [[0., 0., 0., 0.]] * 2 + [[scale * 1000. / l, 10. / l, .01 / l, 30. / l] for l in range(2, lmax + 1)]


def api_camb(scale=1.0):
    seen = {}

    class Params:
        def __init__(self):
            self.InitPower = NS(set_params=lambda **k: seen.update(initial_power=k))

        def set_cosmology(self, **k): seen['cosmology'] = k

        def set_for_lmax(self, lmax, **k): seen['lmax'] = (lmax, k)

    class Data:
        def get_cmb_power_spectra(self, pars, **k):
            seen['spectra'] = k
            return {'total': camb_rows(k['lmax'], scale)}
    return NS(CAMBparams=Params, get_results=lambda p: Data()), seen


def api_class(scale=1.0):
    seen = {'cleaned': []}
    factor = (PLANCK_LIKE['T_CMB'] * 1e6) ** 2

    class Class:
        def set(self, settings): seen['settings'] = settings

        def compute(self, level=None): seen['compute'] = level

        def lensed_cl(self, lmax):
            rows = camb_rows(lmax, scale)
            return {'ell': list(range(lmax + 1)), 'tt': [r[0] / factor for r in rows], 'ee': [r[1] / factor for r in rows],
                    'bb': [r[2] / factor for r in rows], 'te': [r[3] / factor for r in rows]}

        def struct_cleanup(self): seen['cleaned'].append('struct')

        def empty(self): seen['cleaned'].append('empty')
    return NS(Class=Class), seen


def execute(d, api):
    writes = []
    value = c.execute_points(d, api, lambda r: writes.append(r))
    return value, writes


def native(d, value):
    return {**value, 'engine': d['engine'], 'version': c.VERSIONS[d['engine']],
            'operation_resources': d['operation_resources'], 'physics_validated': False}


def test_profile_validation():
    c.validate_document(document())
    c.validate_document(document('camb+class', ell_max=2500))
    for change in ('ell', 'spectrum', 'duplicate', 'neutrinos', 'count', 'measurement', 'cobaya'):
        d = document()
        if change == 'ell': d['grid']['ell_max'] = 6000
        if change == 'spectrum': d['grid']['spectra'] = ['TT', 'PP']
        if change == 'duplicate': d['grid']['spectra'] = ['TT', 'TT']
        if change == 'neutrinos': d['points'][0]['parameters']['num_massive_nu'] = 0
        if change == 'count': d['operation_resources']['solver_evaluations'] = 2
        if change == 'measurement': d['measurement'] = {'path': 'x', 'sha256': '0' * 64}
        if change == 'cobaya': d['engine'] = 'cobaya'
        with pytest.raises(ValueError):
            c.validate_document(d)


def test_camb_lensed_cells_settings_and_complete_result():
    api, seen = api_camb()
    d = document()
    value, writes = execute(d, api)
    assert seen['lmax'] == (40, {'lens_potential_accuracy': 1})
    assert seen['cosmology']['mnu'] == .06 and seen['cosmology']['num_massive_neutrinos'] == 1
    assert seen['spectra']['CMB_unit'] == 'muK' and seen['spectra']['raw_cl'] is True
    cells = value['points'][0]['cells']
    assert [x['quantity'] for x in cells] == ['lensed_cl_TT', 'lensed_cl_EE', 'lensed_cl_TE']
    assert cells[0]['unit'] == 'muK^2' and cells[0]['ell_min'] == 2 and cells[0]['ell_max'] == 40
    assert cells[0]['values'][0] == 500. and len(cells[0]['values']) == 39
    assert cells[2]['values'][-1] == pytest.approx(30. / 40)
    assert writes[-1]['status'] == 'passed'
    c.complete_result(d, native(d, value))


def test_class_lensing_neutrinos_and_unit_conversion():
    api, seen = api_class()
    d = document('class')
    value, _ = execute(d, api)
    s = seen['settings']
    assert s['lensing'] == 'yes' and 'lCl' in s['output'] and s['l_max_scalars'] >= 40
    assert s['N_ncdm'] == 1 and s['m_ncdm'] == .06 and s['N_ur'] == pytest.approx(3.046 - 1.0132)
    assert seen['cleaned'] == ['struct', 'empty']
    assert value['points'][0]['cells'][0]['values'][0] == pytest.approx(500.)
    c.complete_result(d, native(d, value))


def test_cross_engine_comparison_quantity():
    camb, _ = api_camb()
    klass, _ = api_class(scale=1.01)
    d = document('camb+class')
    value, _ = execute(d, {'camb': camb, 'class': klass})
    result = c.complete_result(d, native(d, value))
    rows = {r['spectrum']: r for r in result['comparison'][0]['spectra']}
    assert rows['TT']['max_abs_relative_difference'] == pytest.approx(.01 / 1.01)
    assert rows['EE']['max_abs_relative_difference'] == pytest.approx(0, abs=1e-12)
    assert rows['TE']['normalization'] == 'sqrt(C_TT C_EE) of the reference engine'
    assert result['comparison'][0]['reference_engine'] == 'class'
    assert {cell['engine'] for cell in value['points'][0]['cells']} == {'camb', 'class'}


@pytest.mark.parametrize('fault', ['value', 'count', 'unit'])
def test_tampered_cmb_delivery_refuses(fault):
    api, _ = api_camb()
    d = document()
    value, _ = execute(d, api)
    result = json.loads(json.dumps(native(d, value)))
    if fault == 'value':
        result['points'][0]['cells'][0]['values'][3] *= 2
    elif fault == 'count':
        result['points'][0]['cells'][1]['values'].pop()
    else:
        result['points'][0]['cells'][2]['unit'] = 'K^2'
    with pytest.raises(ValueError):
        c.complete_result(d, result)


@pytest.mark.skipif(importlib.util.find_spec('camb') is None or importlib.util.find_spec('classy') is None,
                    reason='CAMB and CLASS are not installed')
def test_real_camb_and_class_lensed_spectra_agree_at_the_per_mille_level():
    import camb
    import classy
    d = document('camb+class', ell_max=1500)
    value, _ = execute(d, {'camb': camb, 'class': classy})
    result = c.complete_result(d, native(d, value))
    rows = {r['spectrum']: r for r in result['comparison'][0]['spectra']}
    assert all(0 < rows[k]['max_abs_relative_difference'] < .02 for k in ('TT', 'EE', 'TE'))
    tt = next(x for x in value['points'][0]['cells'] if x['engine'] == 'camb' and x['quantity'] == 'lensed_cl_TT')
    first_peak = max(range(len(tt['values'])), key=lambda i: tt['values'][i] * (i + 2) * (i + 3))
    assert 180 < first_peak + 2 < 260


def test_runtime_manifest_is_the_engine_dependency_closure(tmp_path):
    site = tmp_path / 'site'
    for name, version, requires in (('camb', '1.6.5', ['numpy']), ('classy', '3.4.1.0', ['numpy']), ('numpy', '2.0', []),
                                    ('other', '1.0', [])):
        info = site / f'{name}-{version}.dist-info'
        info.mkdir(parents=True)
        (info / 'METADATA').write_text(f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n'
                                       + ''.join(f'Requires-Dist: {r}\n' for r in requires))
        (site / name).mkdir()
        (site / name / '__init__.py').write_text('#\n')
        (info / 'RECORD').write_text(f'{name}/__init__.py,,\n{info.name}/METADATA,,\n{info.name}/RECORD,,\n')
    m = c.runtime_manifest('camb+class', '/usr/bin/python3', [site])
    assert m['engine'] == 'camb+class' and m['version'] == c.VERSIONS['camb+class']
    names = {Path(f['path']).relative_to(site).parts[0] for f in m['files']}
    assert 'other' not in names and {'camb', 'classy', 'numpy'} <= names
    with pytest.raises(ValueError):
        c.runtime_manifest('camb', '/usr/bin/python3', [tmp_path / 'empty'])
