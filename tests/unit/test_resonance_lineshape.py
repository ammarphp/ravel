"""Analytic checks of propagator schemes, LO partial widths and width consistency."""
import cmath
import math

import pytest

from ravel.physics import resonance_lineshape as rl

GF = 1.1663787e-5
MZ = 91.1876
MW = 80.379
MH = 125.0


def test_vector_to_massless_neutrinos_matches_textbook_z_width():
    # L = (g / 2 cw) Z nubar gamma (v - a g5) nu with v = a = 1/2; g^2/cw^2 = 8 GF MZ^2 / sqrt(2)
    g_over_cw = math.sqrt(8 * GF * MZ**2 / math.sqrt(2))
    gv = ga = g_over_cw / 2 * 0.5
    width = rl.width_vector_to_fermions(MZ, 0.0, gv, ga, n_colour=1)
    assert width == pytest.approx(GF * MZ**3 / (12 * math.sqrt(2) * math.pi), rel=1e-12)
    assert width == pytest.approx(0.1659, abs=5e-4)


def test_vector_to_quarks_has_colour_factor_and_mass_suppression():
    massless = rl.width_vector_to_fermions(1000.0, 0.0, 0.3, 0.1, n_colour=3)
    assert massless == pytest.approx(3 * 1000.0 * (0.09 + 0.01) / (12 * math.pi))
    massive = rl.width_vector_to_fermions(1000.0, 172.5, 0.3, 0.1, n_colour=3)
    r = 172.5**2 / 1000.0**2
    beta = math.sqrt(1 - 4 * r)
    assert massive == pytest.approx(3 * 1000.0 * beta * (0.09 * (1 + 2 * r) + 0.01 * (1 - 4 * r)) / (12 * math.pi))
    assert rl.width_vector_to_fermions(300.0, 172.5, 0.3, 0.1, n_colour=3) == 0.0


def test_scalar_to_top_pair_matches_sm_textbook_formula():
    mt, m = 172.5, 400.0
    vev = 1 / math.sqrt(math.sqrt(2) * GF)
    width = rl.width_scalar_to_fermions(m, mt, mt / vev, n_colour=3, parity='scalar')
    beta = math.sqrt(1 - 4 * mt**2 / m**2)
    assert width == pytest.approx(3 * GF * mt**2 * m * beta**3 / (4 * math.sqrt(2) * math.pi), rel=1e-12)
    pseudo = rl.width_scalar_to_fermions(m, mt, mt / vev, n_colour=3, parity='pseudoscalar')
    assert pseudo == pytest.approx(width / beta**2, rel=1e-12)


def test_scalar_to_zz_and_ww_match_textbook_formula():
    m = 300.0
    for kind, mv, delta in (('Z', MZ, 1), ('W', MW, 2)):
        x = mv**2 / m**2
        expected = delta * GF * m**3 / (16 * math.sqrt(2) * math.pi) * math.sqrt(1 - 4 * x) * (1 - 4 * x + 12 * x * x)
        assert rl.width_scalar_to_vv(m, mv, GF, kind=kind, kappa=1.0) == pytest.approx(expected, rel=1e-12)
        assert rl.width_scalar_to_vv(m, mv, GF, kind=kind, kappa=0.5) == pytest.approx(expected / 4, rel=1e-12)
    assert rl.width_scalar_to_vv(150.0, MZ, GF, kind='Z') == 0.0


def test_gluon_and_photon_widths_reach_heavy_mass_limits():
    alpha_s, alpha = 0.118, 1 / 137.036
    heavy = 1.0e6
    gg = rl.width_scalar_to_gluons(MH, alpha_s, GF, quarks=[{'mass': heavy, 'kappa': 1.0}])
    assert gg == pytest.approx(GF * alpha_s**2 * MH**3 / (36 * math.sqrt(2) * math.pi**3), rel=1e-6)
    aa = rl.width_scalar_to_photons(MH, alpha, GF, fermions=[{'mass': heavy, 'charge': 2 / 3, 'n_colour': 3, 'kappa': 1.0}],
                                    w_boson={'mass': heavy, 'kappa': 1.0})
    amplitude = 3 * (2 / 3)**2 * 4 / 3 - 7
    assert aa == pytest.approx(GF * alpha**2 * MH**3 / (128 * math.sqrt(2) * math.pi**3) * amplitude**2, rel=1e-6)
    # Realistic light Higgs: the W loop dominates and interferes destructively with the top loop.
    real = rl.width_scalar_to_photons(MH, alpha, GF, fermions=[{'mass': 172.5, 'charge': 2 / 3, 'n_colour': 3}],
                                      w_boson={'mass': MW})
    assert 7e-6 < real < 1.2e-5


def test_loop_functions_continue_above_threshold():
    assert rl.loop_a_half(1e-8) == pytest.approx(4 / 3, rel=1e-6)
    assert rl.loop_a_one(1e-8) == pytest.approx(-7, rel=1e-6)
    above = rl.loop_a_half(4.0)
    assert isinstance(above, complex) and above.imag != 0


def test_effective_operator_widths():
    # L = -(g/4) a F Ftilde -> Gamma = g^2 m^3 / (64 pi); gluons carry eight colours.
    assert rl.width_scalar_to_photons_effective(1.0, 1e-3) == pytest.approx(1e-6 / (64 * math.pi))
    assert rl.width_scalar_to_gluons_effective(1.0, 1e-3) == pytest.approx(8e-6 / (64 * math.pi))


def test_vector_to_ww_and_landau_yang():
    m, g = 2000.0, 1e-3
    x = MW**2 / m**2
    expected = g**2 * m / (192 * math.pi) * (m / MW)**4 * (1 - 4 * x)**1.5 * (1 + 20 * x + 12 * x * x)
    assert rl.width_vector_to_ww(m, MW, g) == pytest.approx(expected, rel=1e-12)
    with pytest.raises(ValueError, match='Landau-Yang'):
        rl.evaluate_channel({'kind': 'vv_massless', 'final_state': 'photons'}, {'spin': 1, 'mass_GeV': 500.0}, {})


def test_fixed_and_running_agree_on_shell_and_pole_mapping_is_exact():
    m, w = 750.0, 45.0
    s = m * m
    assert rl.propagator(s, m, w, 'fixed') == pytest.approx(rl.propagator(s, m, w, 'running'))
    mu, gamma = rl.complex_pole_from_on_shell(m, w)
    assert rl.on_shell_from_complex_pole(mu, gamma) == pytest.approx((m, w))
    for sqrt_s in (600.0, 700.0, 800.0, 950.0):
        s = sqrt_s**2
        running = rl.propagator(s, m, w, 'running')
        pole = rl.propagator(s, mu, gamma, 'complex-pole')
        assert running * (1 + 1j * w / m) == pytest.approx(pole, rel=1e-12)


def test_narrow_width_limit_integral():
    m, w = 100.0, 1e-3
    lo, hi, n = (m - 400 * w)**2, (m + 400 * w)**2, 200001
    step = (hi - lo) / (n - 1)
    total = sum(rl.lineshape(lo + i * step, m, w, 'fixed') for i in range(n)) * step
    assert total == pytest.approx(math.pi / (m * w), rel=5e-3)


def test_unknown_scheme_refused():
    with pytest.raises(ValueError, match='scheme'):
        rl.propagator(1.0, 1.0, 0.1, 'guess')


@pytest.mark.parametrize('declared,status,passed', [
    (1.0, 'consistent', True), (2.0, 'implied_additional_decays', True), (0.5, 'below_partial_sum', False)])
def test_width_consistency(declared, status, passed):
    report = rl.width_consistency(declared, {'a': 0.6, 'b': 0.4}, rel_tol=0.01)
    assert report['status'] == status and report['passed'] is passed
    if status == 'implied_additional_decays':
        assert report['implied_other_branching_fraction'] == pytest.approx(0.5)


def test_evaluate_request_with_computed_and_declared_free_widths():
    request = {
        'schema_version': 1,
        'state': {'name': "Neutral vector", 'spin': 1, 'mass_GeV': 1000.0},
        'constants': {},
        'channels': [
            {'id': 'uu', 'kind': 'ff', 'fermion_mass_GeV': 0.0, 'n_colour': 3, 'g_vector': 0.2, 'g_axial': 0.0},
            {'id': 'mumu', 'kind': 'ff', 'fermion_mass_GeV': 0.0, 'n_colour': 1, 'g_vector': 0.1, 'g_axial': 0.1}],
        'width': {'source': 'computed'},
        'propagator': {'scheme': 'running', 'sqrt_s_GeV': [900.0, 1000.0, 1100.0]},
    }
    result = rl.evaluate(request)
    total = sum(c['width_GeV'] for c in result['channels'])
    assert result['total_width_GeV'] == pytest.approx(total)
    assert sum(c['branching_fraction'] for c in result['channels']) == pytest.approx(1.0)
    assert len(result['propagator']['values']) == 3
    request['width'] = {'source': 'declared_free', 'total_width_GeV': 3 * total, 'rel_tol': 0.01}
    result = rl.evaluate(request)
    assert result['width_check']['status'] == 'implied_additional_decays'
    assert result['total_width_GeV'] == pytest.approx(3 * total)
    request['width'] = {'source': 'declared_free', 'total_width_GeV': 0.5 * total, 'rel_tol': 0.01}
    assert rl.evaluate(request)['width_check']['passed'] is False


def test_evaluate_refuses_missing_constants():
    request = {'schema_version': 1, 'state': {'name': 'Scalar', 'spin': 0, 'mass_GeV': 300.0}, 'constants': {},
               'channels': [{'id': 'zz', 'kind': 'vv_sm_like', 'boson': 'Z', 'boson_mass_GeV': MZ}],
               'width': {'source': 'computed'}}
    with pytest.raises(ValueError, match='fermi_constant'):
        rl.evaluate(request)
