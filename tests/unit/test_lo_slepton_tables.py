"""The three locally computed leading-order slepton tables are registered under explicit conventions."""
import hashlib
import json

import pytest

from ravel.paths import package_data_path
from ravel.physics import cross_sections as xs

LO = {'mg5-lo-slepton-l-pair-cteq6l1': ('slepton_selL_lo_cteq6l1.json', 'slepton_L_pair', 1,
                                        'be9b882cd8689b986d77fab861c50427c5ea908049ad014015eb1b00f3e464a2'),
      'mg5-lo-slepton-lr-pair-2gen-cteq6l1': ('slepton_incl4_lo_cteq6l1.json', 'slepton_LR_pair', 2,
                                              '956a98684a88ba08d5f88ebac886e17b535fd3962cffcdb8301c2363beb0f095'),
      'mg5-lo-slepton-lr-pair-with-stau-cteq6l1': ('slepton_incl6_lo_cteq6l1.json', 'slepton_LR_pair_with_stau', 3,
                                                   '3caac283fd339cc38e30be560b109da9dfa00874d267f3ccd257f377f24fa269')}


def request(basis, order='LO', pdf='cteq6l1', scale='as-published', mass=200, **extra):
    return {'schema_version': 1, 'basis': basis, 'sqrt_s_GeV': 13000,
            'convention': {'order': order, 'pdf': pdf, 'scale': scale}, 'masses': {'mass': mass}, **extra}


def data(table_id):
    return xs.load_table(xs.table_entry(table_id))['data']


@pytest.mark.parametrize('table_id', sorted(LO))
def test_registered_with_basis_order_pdf_and_recorded_generator(table_id):
    name, basis, count, digest = LO[table_id]
    entry = xs.table_entry(table_id)
    assert entry['file'] == name and entry['basis'] == basis and entry['state_count'] == count
    assert entry['source_kind'] == 'mg5-computed' and entry['source_url'] is None
    assert entry['convention']['order'] == 'LO' and entry['convention']['pdf'] == 'cteq6l1'
    assert 'dynamical_scale_choice=-1' in entry['convention']['scale']
    assert entry['generator']['program'].startswith('MG5_aMC') and entry['generator']['nevents'] == 2000
    assert entry['sqrt_s_GeV'] == 13000 and entry['charge'] is None
    for path in ('process_card', 'param_template', 'run_template'):
        assert package_data_path(*entry['generator'][path].removeprefix('src/ravel/data/').split('/')).is_file()
    nodes = json.loads(package_data_path('cross_sections', name).read_text())['data']
    assert hashlib.sha256(json.dumps(nodes, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == digest
    assert sorted(map(int, nodes)) == [50, 60, 70, 90, 100, 125, 150, 175, 200, 225, 250, 300]
    assert all(node['xsec_pb'] > 0 and node['unc_pb'] > 0 for node in nodes.values())


def test_the_registry_verifies_and_a_local_table_has_nothing_to_download(tmp_path):
    report = xs.verify_registry()
    assert report['passed'] and report['tables'] == len(xs.registry()['tables'])
    with pytest.raises(RuntimeError, match='no download URL'):
        xs.fetch('mg5-lo-slepton-l-pair-cteq6l1', tmp_path/'x.json')
    assert not (tmp_path/'x.json').exists()


def test_exact_node_and_interpolation_under_the_lo_convention():
    node = xs.lookup(request('slepton_L_pair', mass=175, state_count=1))
    assert node['sigma_pb'] == data('mg5-lo-slepton-l-pair-cteq6l1')['175']['xsec_pb']
    assert node['interpolation'] == 'exact node' and node['source'] == {'kind': 'mg5-computed'}
    assert node['convention']['pdf'] == 'cteq6l1' and node['table']['generator']['order'] == 'LO'
    between = xs.lookup(request('slepton_L_pair', mass=160, state_count=1))
    nodes = data('mg5-lo-slepton-l-pair-cteq6l1')
    assert nodes['175']['xsec_pb'] < between['sigma_pb'] < nodes['150']['xsec_pb']
    assert between['interpolation'].startswith('log-log')
    assert between['uncertainty']['relative_up'] > 0


def test_two_generation_table_is_twice_one_generation_and_rescales_exactly():
    two = xs.lookup(request('slepton_LR_pair', mass=150, state_count=2))
    one = xs.lookup(request('slepton_LR_pair', mass=150, state_count=1))
    assert two['sigma_pb'] == data('mg5-lo-slepton-lr-pair-2gen-cteq6l1')['150']['xsec_pb']
    assert one['sigma_pb'] == pytest.approx(two['sigma_pb']/2, rel=1e-12)
    assert one['state_rescaling']['table_state_count'] == 2
    # Cross-check against the published tables: the right-handed pair adds to the left-handed one
    # in the same proportion (here 1 + sigma_R/sigma_L, order and PDF aside).
    left = xs.lookup(request('slepton_L_pair', mass=150, state_count=1))
    published_lr = xs.lookup(request('slepton_LR_pair', order='NLO+NLL', pdf='PDF4LHC15', mass=150, state_count=1))
    published_l = xs.lookup(request('slepton_L_pair', order='NLO+NLL', pdf='PDF4LHC15', mass=150, state_count=1))
    lo_ratio = two['sigma_pb']/(2*left['sigma_pb'])
    assert 1.0 < lo_ratio < 2.0
    assert lo_ratio == pytest.approx(published_lr['sigma_pb']/published_l['sigma_pb'], rel=0.06)


def test_four_state_over_six_state_is_two_thirds_at_every_node():
    four, six = data('mg5-lo-slepton-lr-pair-2gen-cteq6l1'), data('mg5-lo-slepton-lr-pair-with-stau-cteq6l1')
    assert set(four) == set(six)
    for key in four:
        assert four[key]['xsec_pb']/six[key]['xsec_pb'] == pytest.approx(2/3, abs=0.002), key
    rescaled = xs.lookup(request('slepton_LR_pair_with_stau', mass=125, state_count=2))
    assert rescaled['sigma_pb'] == pytest.approx(four['125']['xsec_pb'], rel=0.002)


def test_like_for_like_correction_between_a_published_table_and_the_lo_denominator():
    numerator = xs.lookup(request('slepton_L_pair', order='NLO+NLL', pdf='PDF4LHC15', mass=200, state_count=1))
    denominator = xs.lookup(request('slepton_L_pair', mass=200, state_count=1))
    ratio = xs.k_factor(numerator, denominator)
    assert ratio['k_factor'] == pytest.approx(numerator['sigma_pb']/data('mg5-lo-slepton-l-pair-cteq6l1')['200']['xsec_pb'])
    assert ratio['numerator']['convention']['order'] == 'NLO+NLL'
    assert ratio['denominator']['convention']['pdf'] == 'cteq6l1'
    assert 1.0 < ratio['k_factor'] < 2.0
    # A different state basis is never divided into it.
    other = xs.lookup(request('slepton_LR_pair', mass=200, state_count=2))
    with pytest.raises(ValueError, match='like-for-like'):
        xs.k_factor(numerator, other)


@pytest.mark.parametrize('bad,error', [
    (request('slepton_L_pair', pdf='NNPDF31', state_count=1), xs.ConventionUnavailable),
    (request('slepton_L_pair', order='NLO', state_count=1), xs.ConventionUnavailable),
    (request('gluino_pair', mass=1000), xs.ConventionUnavailable),
    (request('stau_L_pair', state_count=1), xs.ConventionUnavailable),
    (request('slepton_L_pair', mass=400, state_count=1), ValueError),
    (request('slepton_L_pair', mass=40, state_count=1), ValueError),
    (request('slepton_L_pair', mass=200), ValueError),
])
def test_no_guessed_fallback_for_another_basis_order_pdf_or_mass(bad, error):
    with pytest.raises(error):
        xs.lookup(bad)


def test_the_published_tables_and_their_lookups_are_unchanged():
    published = [t for t in xs.registry()['tables'] if t.get('source_kind', 'published-table') == 'published-table']
    assert all(t['source_url'] for t in published)
    # The bundled published tables are unchanged; acquired rows hold no numbers and are fetched at install time.
    bundled = [t for t in published if t.get('bundled', True) is not False]
    assert len(bundled) == 58
    assert all(t.get('acquisition') for t in published if t not in bundled)
    single = xs.lookup(request('slepton_L_pair', order='NLO+NLL', pdf='CT10', mass=300, state_count=1))
    assert single['table']['id'] == 'pp13-slep-l-nlo-nll' and single['source'] == {'kind': 'published-table'}
