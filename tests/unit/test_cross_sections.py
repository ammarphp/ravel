"""Cross-section registry: explicit conventions, state bases, interpolation and refusals."""
import json
import math

import pytest

from ravel.physics import cross_sections as xs


def request(basis, sqrt_s=13000, order='NLO+NLL', pdf='as-published', scale='as-published', **extra):
    return {'schema_version': 1, 'basis': basis, 'sqrt_s_GeV': sqrt_s,
            'convention': {'order': order, 'pdf': pdf, 'scale': scale}, **extra}


def node(table_id, key):
    table = xs.load_table(xs.table_entry(table_id))
    return table['data'][key]


def test_every_pinned_table_matches_its_recorded_sha256():
    report = xs.verify_registry()
    assert report['passed'] and report['tables'] == len(xs.registry()['tables'])


def test_exact_nodes_are_returned_unchanged():
    result = xs.lookup(request('gluino_pair', order='aNNLO+NNLL', masses={'mass': 2050}))
    assert result['sigma_pb'] == node('pp13-gluino-nnlo-nnll', '2050')['xsec_pb']
    assert result['interpolation'] == 'exact node'
    assert result['table']['sha256'] == xs.table_entry('pp13-gluino-nnlo-nnll')['sha256']
    assert result['convention']['order'] == 'aNNLO+NNLL'


def test_log_log_interpolation_between_nodes():
    entry = next(t for t in xs.registry()['tables'] if t['id'] == 'pp13-slep-l-nlo-nll-pdf4lhc')
    data = xs.load_table(entry)['data']
    result = xs.lookup(request('slepton_L_pair', pdf='PDF4LHC15', masses={'mass': 110}, state_count=1))
    lo, hi = data['100']['xsec_pb'], data['120']['xsec_pb']
    f = math.log(110 / 100) / math.log(120 / 100)
    assert result['sigma_pb'] == pytest.approx(math.exp(math.log(lo) + f * (math.log(hi) - math.log(lo))), rel=1e-12)
    assert lo > result['sigma_pb'] > hi
    assert result['interpolation'].startswith('log-log')


def test_order_must_be_selected_and_switching_convention_follows_the_tables():
    with pytest.raises(ValueError, match='order'):
        xs.lookup({'schema_version': 1, 'basis': 'gluino_pair_with_squarks', 'sqrt_s_GeV': 13000,
                   'convention': {'pdf': 'as-published', 'scale': 'as-published'},
                   'masses': {'m_gluino': 1500, 'm_squark': 4000}, 'state_count': 8})
    masses = {'m_gluino': 1500, 'm_squark': 4000}
    nlo = xs.lookup(request('gluino_pair_with_squarks', masses=masses, state_count=8))
    nnlo = xs.lookup(request('gluino_pair_with_squarks', order='aNNLO+NNLL', masses=masses, state_count=8))
    a = node('pp13-sgmodel-ggxsec-nlo-nll', '1500')['4000']['xsec_pb']
    b = node('pp13-sgmodel-ggxsec-nnlo-nnll', '1500')['4000']['xsec_pb']
    assert nnlo['sigma_pb'] / nlo['sigma_pb'] == pytest.approx(b / a, rel=1e-12)
    assert nlo['table']['id'] != nnlo['table']['id']


def test_unavailable_convention_is_refused_with_alternatives_and_no_fallback():
    with pytest.raises(xs.ConventionUnavailable) as excinfo:
        xs.lookup(request('gluino_pair', sqrt_s=13600, order='NLO+NLL', masses={'mass': 1000}))
    assert 'aNNLO+NNLL' in str(excinfo.value)
    with pytest.raises(xs.ConventionUnavailable, match='PDF'):
        xs.lookup(request('wino_C1C1', pdf='NNPDF31', masses={'mass': 300}))


def test_ambiguous_pdf_must_be_narrowed():
    with pytest.raises(xs.ConventionUnavailable, match='ambiguous'):
        xs.lookup(request('slepton_L_pair', masses={'mass': 300}, state_count=1))
    ct10 = xs.lookup(request('slepton_L_pair', pdf='CT10', masses={'mass': 300}, state_count=1))
    pdf4lhc = xs.lookup(request('slepton_L_pair', pdf='PDF4LHC15', masses={'mass': 300}, state_count=1))
    assert ct10['table']['id'] != pdf4lhc['table']['id']


def test_charge_sum_is_about_twice_one_state_and_charge_is_required():
    masses = {'mass': 300}
    plus = xs.lookup(request('wino_C1N2', charge='plus', masses=masses))
    minus = xs.lookup(request('wino_C1N2', charge='minus', masses=masses))
    total = xs.lookup(request('wino_C1N2', charge='sum', masses=masses))
    assert total['sigma_pb'] == pytest.approx(plus['sigma_pb'] + minus['sigma_pb'], rel=0.02)
    # C1+ N2 exceeds C1- N2 at a pp collider (more u than d valence quarks).
    assert plus['sigma_pb'] > minus['sigma_pb']
    assert 1.3 < total['sigma_pb'] / plus['sigma_pb'] < 2.0 < total['sigma_pb'] / minus['sigma_pb'] < 4.0
    with pytest.raises(ValueError, match='charge'):
        xs.lookup(request('wino_C1N2', masses=masses))


def test_charge_sum_is_computed_from_charge_tables_when_no_sum_is_published():
    masses = {'mass': 200}
    plus = xs.lookup(request('wino_C1N2', sqrt_s=13600, order='aNNLO+NNLL', charge='plus', masses=masses))
    minus = xs.lookup(request('wino_C1N2', sqrt_s=13600, order='aNNLO+NNLL', charge='minus', masses=masses))
    total = xs.lookup(request('wino_C1N2', sqrt_s=13600, order='aNNLO+NNLL', charge='sum', masses=masses))
    assert total['sigma_pb'] == pytest.approx(plus['sigma_pb'] + minus['sigma_pb'], rel=1e-12)
    assert total['charge_combination']['rule'].startswith('sum of')


def test_state_count_rescaling_is_explicit_and_recorded():
    base = xs.lookup(request('squark_antisquark', order='NNLO+NNLL', masses={'mass': 2050}, state_count=10))
    one = xs.lookup(request('squark_antisquark', order='NNLO+NNLL', masses={'mass': 2050}, state_count=1))
    assert one['sigma_pb'] == pytest.approx(base['sigma_pb'] / 10)
    assert one['state_rescaling']['factor'] == pytest.approx(0.1)
    with pytest.raises(ValueError, match='state_count'):
        xs.lookup(request('squark_antisquark', order='NNLO+NNLL', masses={'mass': 2050}))
    with pytest.raises(ValueError, match='rescal'):
        xs.lookup(request('gluino_squark_equal_mass', order='aNNLO+NNLL', masses={'mass': 2050}, state_count=4))


def test_slepton_flavour_count():
    one = xs.lookup(request('slepton_LR_pair', pdf='PDF4LHC15', masses={'mass': 300}, state_count=1))
    two = xs.lookup(request('slepton_LR_pair', pdf='PDF4LHC15', masses={'mass': 300}, state_count=2))
    assert two['sigma_pb'] == pytest.approx(2 * one['sigma_pb'])


def test_alias_records_its_rule():
    result = xs.lookup(request('wino_C1N1', charge='plus', masses={'mass': 300}))
    direct = xs.lookup(request('wino_C1N2', charge='plus', masses={'mass': 300}))
    assert result['sigma_pb'] == direct['sigma_pb']
    assert result['alias']['target'] == 'wino_C1N2' and 'wino' in result['alias']['rule']


def test_out_of_range_and_unknown_basis_refused():
    with pytest.raises(ValueError, match='range'):
        xs.lookup(request('gluino_pair', order='aNNLO+NNLL', masses={'mass': 50}))
    with pytest.raises(ValueError, match='basis'):
        xs.lookup(request('mystery_pair', masses={'mass': 300}))


def test_declared_gap_is_reported():
    with pytest.raises(xs.ConventionUnavailable, match='gap'):
        xs.lookup(request('higgsino_C1C1', masses={'mass': 300}))


def test_two_dimensional_grid_interpolation_at_nodes_and_between():
    masses = {'m_gluino': 1750, 'm_squark': 3500}
    exact = xs.lookup(request('gluino_pair_with_squarks', sqrt_s=13600, order='aNNLO+NNLL', masses=masses, state_count=8))
    assert exact['sigma_pb'] == node('pp13600-sgmodel-ggxsec-nnloa-nnll', '1750')['3500']['xsec_pb']
    mid = xs.lookup(request('gluino_pair_with_squarks', sqrt_s=13600, order='aNNLO+NNLL',
                            masses={'m_gluino': 1900, 'm_squark': 3700}, state_count=8))
    corners = [node('pp13600-sgmodel-ggxsec-nnloa-nnll', g)[s]['xsec_pb'] for g in ('1750', '2250') for s in ('3500', '4000')]
    assert min(corners) < mid['sigma_pb'] < max(corners)
    with pytest.raises(ValueError, match='grid'):
        xs.lookup(request('gluino_pair_with_squarks', sqrt_s=13600, order='aNNLO+NNLL',
                          masses={'m_gluino': 1600, 'm_squark': 2000}, state_count=8))


def test_uncertainties_are_reported():
    result = xs.lookup(request('slepton_L_pair', pdf='PDF4LHC15', masses={'mass': 100}, state_count=1))
    entry = node('pp13-slep-l-nlo-nll-pdf4lhc', '100')
    assert result['uncertainty']['up_pb'] == pytest.approx(entry['unc_up_pb'])
    assert result['uncertainty']['down_pb'] == pytest.approx(abs(entry['unc_down_pb']))


def test_mg5_source_is_separate_and_k_factor_requires_matching_basis(tmp_path):
    banner = tmp_path / 'banner.txt'
    banner.write_text('<MGGenerationInfo>\n#  Number of Events        :       100\n'
                      '#  Integrated weight (pb)  :       0.0123\n</MGGenerationInfo>\n')
    lo = xs.mg5_record(basis='slepton_L_pair', sqrt_s_GeV=13000, masses={'mass': 300}, state_count=1,
                       convention={'order': 'LO', 'pdf': 'NNPDF23_lo', 'scale': 'MG5 dynamical default'},
                       banner=banner)
    assert lo['sigma_pb'] == pytest.approx(0.0123) and lo['source']['kind'] == 'mg5'
    assert lo['source']['sha256']
    high = xs.lookup(request('slepton_L_pair', pdf='PDF4LHC15', masses={'mass': 300}, state_count=1))
    k = xs.k_factor(high, lo)
    assert k['k_factor'] == pytest.approx(high['sigma_pb'] / 0.0123)
    mismatched = dict(lo, state_count=2)
    with pytest.raises(ValueError, match='like-for-like'):
        xs.k_factor(high, mismatched)
    with pytest.raises(ValueError, match='order'):
        xs.mg5_record(basis='slepton_L_pair', sqrt_s_GeV=13000, masses={'mass': 300}, state_count=1,
                      convention={'order': 'NLO+NLL', 'pdf': 'x', 'scale': 'y'}, sigma_pb=1.0)


def test_fetch_fails_loudly_offline(monkeypatch, tmp_path):
    def offline(*_args, **_kwargs):
        raise OSError('network unreachable')
    monkeypatch.setattr(xs, '_download', offline)
    with pytest.raises(RuntimeError, match='network unreachable'):
        xs.fetch('pp13-gluino-nnlo-nnll', tmp_path / 'copy.json')
    assert not (tmp_path / 'copy.json').exists()


def test_fetch_refuses_changed_bytes(monkeypatch, tmp_path):
    monkeypatch.setattr(xs, '_download', lambda url: b'{"data": {}}')
    with pytest.raises(RuntimeError, match='sha256'):
        xs.fetch('pp13-gluino-nnlo-nnll', tmp_path / 'copy.json')


def test_cli_lookup_writes_result(tmp_path, capsys):
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(request('stop_pair', order='aNNLO+NNLL', masses={'mass': 1000})))
    assert xs.main(['lookup', '--request', str(path), '--out', str(tmp_path / 'out.json')]) == 0
    result = json.loads((tmp_path / 'out.json').read_text())
    assert result['basis'] == 'stop_pair' and result['sigma_pb'] > 0
    assert xs.main(['list', '--basis', 'stop_pair']) == 0
    assert 'pp13-stopsbottom' in capsys.readouterr().out


def test_nlo_xsec_has_no_silent_k_factor_fallback(tmp_path):
    from ravel.physics import nlo_xsec
    out = tmp_path / 'nlo.json'
    with pytest.raises(SystemExit) as excinfo:
        nlo_xsec.main_args(['--process', 'gluino', '--mass', '1000', '--sigma-lo-pb', '0.2', '--out', str(out)])
    assert excinfo.value.code not in (0, None)
    assert not out.exists()
    assert not hasattr(nlo_xsec, 'K_FALLBACK')


def test_different_spectrum_requires_a_declared_assumption(monkeypatch):
    entry = dict(xs.table_entry('pp13-gluino-nnlo-nnll'),
                 decoupling='eight degenerate partners at a fixed mass of 2200 GeV')
    monkeypatch.setattr(xs, '_REGISTRY', {'tables': [entry], 'aliases': [], 'gaps': []})
    monkeypatch.setattr(xs, 'load_table', lambda entry: {'data': {'700': {'xsec_pb': 0.6}}})
    req = request('gluino_pair', order='aNNLO+NNLL', masses={'mass': 700},
                  spectrum={'decoupling': 'partners decoupled'})
    with pytest.raises(ValueError, match='spectrum_assumption'):
        xs.lookup(req)
    req['spectrum_assumption'] = 'Use the fixed-partner spectrum table as a declared approximation.'
    result = xs.lookup(req)
    assert result['sigma_pb'] == 0.6
    assert result['spectrum_assumption']['requested']['decoupling'] == 'partners decoupled'
    assert result['spectrum_assumption']['tables'][0]['decoupling'] == entry['decoupling']
    assert result['spectrum_assumption']['statement'] == req['spectrum_assumption']
    req['spectrum']['decoupling'] = entry['decoupling']
    del req['spectrum_assumption']
    assert xs.lookup(req)['spectrum_assumption'] is None


def test_different_unrescalable_state_count_requires_an_assumption(monkeypatch):
    entry = dict(xs.table_entry('pp13-gluino-nnlo-nnll'), state_count=8, state_rescaling=None)
    monkeypatch.setattr(xs, '_REGISTRY', {'tables': [entry], 'aliases': [], 'gaps': []})
    monkeypatch.setattr(xs, 'load_table', lambda entry: {'data': {'700': {'xsec_pb': 0.6}}})
    req = request('gluino_pair', order='aNNLO+NNLL', masses={'mass': 700}, state_count=4)
    with pytest.raises(ValueError, match='spectrum_assumption'):
        xs.lookup(req)
    req['spectrum_assumption'] = 'Approximate four partners using the eight-partner table without rescaling.'
    result = xs.lookup(req)
    assert result['sigma_pb'] == 0.6 and result['state_rescaling'] is None
    assert result['spectrum_assumption']['requested']['state_count'] == 4


def test_empty_spectrum_assumption_is_not_a_declaration():
    with pytest.raises(ValueError, match='spectrum_assumption'):
        xs.lookup(request('gluino_pair', order='aNNLO+NNLL', masses={'mass': 700},
                          spectrum={'decoupling': 'synthetic different spectrum'}, spectrum_assumption=' '))
