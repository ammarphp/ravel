"""Handbook static source census and UFO inspection, without model runtimes."""
import pytest

from ravel.physics import model_authoring as author

SKILL = 'model-authoring'


def spec():
    return {'schema_version': 1, 'name': 'SyntheticScalar', 'extends': 'SM',
            'fields': [{'name': 'ScalarX', 'kind': 'scalar', 'self_conjugate': True,
                        'su3': '1', 'hypercharge': '0', 'pdg': 9900001,
                        'mass': {'symbol': 'MassX', 'value': 100.},
                        'width': {'symbol': 'WidthX', 'value': 0.}}],
            'parameters': [{'symbol': 'CouplingX', 'nature': 'external', 'value': .1,
                            'block': 'NEWPARAM', 'index': [1], 'description': 'Synthetic quartic coupling'}],
            'lagrangian_terms': [{'id': 'quartic', 'operator': '-(CouplingX/24) ScalarX^4',
                                  'fields': [{'field': 'ScalarX'} for _ in range(4)],
                                  'couplings': ['CouplingX'], 'hc': False, 'kind': 'interaction'}],
            'required_couplings': ['CouplingX']}


def test_record_lists_tested_blocks(handbook):
    assert handbook.listed(SKILL) == ['static-model-census', 'inspect-ufo']


def test_static_census_renders_without_native_calls(handbook):
    census = handbook.load(SKILL, 'static-model-census')['static_model_census']
    source, checks = census(spec())
    assert 'LFull := LSM + LNew;' in source
    assert all(r['passed'] for r in checks.values())


def test_unsupported_weak_multiplet_is_refused(handbook):
    census = handbook.load(SKILL, 'static-model-census')['static_model_census']
    bad = spec(); bad['fields'][0]['su2'] = 2
    with pytest.raises(author.UnsupportedModel):
        census(bad)


def test_non_neutral_real_field_is_refused(handbook):
    census = handbook.load(SKILL, 'static-model-census')['static_model_census']
    bad = spec(); bad['fields'][0]['hypercharge'] = '1/3'
    with pytest.raises(ValueError, match='self-conjugate'):
        census(bad)


def test_ufo_is_parsed_without_importing_its_python(handbook, tmp_path):
    inspect = handbook.load(SKILL, 'inspect-ufo')['inspect_ufo']
    marker = tmp_path / 'side-effect.txt'
    (tmp_path / 'particles.py').write_text(f'from pathlib import Path\nPath({str(marker)!r}).write_text("executed")\n')
    report = inspect(tmp_path)
    assert not marker.exists()
    assert not report['passed']
