"""Resonance propagators, leading-order partial widths and width consistency.

Every coupling, mass and electroweak constant comes from the request. The module
evaluates textbook tree-level and one-loop (heavy-quark and W loop) formulas; it
does not choose couplings, running schemes or higher-order corrections.

Propagator schemes for an s-channel state of mass M and width G:

* ``fixed``: 1 / (s - M^2 + i M G)
* ``running``: 1 / (s - M^2 + i s G / M)
* ``complex-pole``: 1 / (s - mu^2 + i mu gamma), with (mu, gamma) the pole
  parameters. On-shell (M, G) map to mu = M / sqrt(1 + G^2/M^2) and
  gamma = G / sqrt(1 + G^2/M^2); the running-width and complex-pole forms then
  differ by the constant factor (1 + i G / M).
"""
from __future__ import annotations

import argparse
import cmath
import json
import math
from pathlib import Path

from ravel.paths import package_data_path

SCHEMES = ('fixed', 'running', 'complex-pole')
SCOPE = 'Neutral colour-singlet spin-0, spin-1 and spin-2 channel coverage, declared LO widths and explicit free widths'
LIMITATIONS = [
    'Partial widths are leading order in the declared couplings; QCD and electroweak corrections are not applied.',
    'Couplings, masses and constants are taken from the request; they are not derived from a model or fit.',
    'A declared total width larger than the computed partial sum implies decays outside the listed channels; '
    'those channels are not identified.',
]

# This is the only enumeration used by dispatch, the JSON table and its docs.
PARITY_CLASSES = {0: ('CP-even', 'CP-odd', 'mixed'),
                  1: ('vector', 'axial-vector', 'mixed chiral'), 2: ('even',)}
CHANNEL_CLASSES = ('ff_massless_colour_1', 'ff_massless_colour_3',
                   'ff_massive_colour_1', 'ff_massive_colour_3',
                   'ww', 'zz', 'zgamma', 'photons', 'gluons', 'vector_scalar', 'scalar_pair')
FREE_SENTENCE = 'The total width is a free parameter of this study and is not derived from couplings.'
LANDAU_YANG = ('A colour-singlet spin-1 state cannot decay to two identical on-shell massless vectors '
               '(Landau-Yang theorem).')
TABLE_PATH = package_data_path('lineshape/channels.json')


def parity_class(state):
    """Canonical classes; legacy spin-1 scalar/pseudoscalar labels retain both chiral couplings."""
    spin = state.get('spin')
    if type(spin) is not int or spin not in PARITY_CLASSES:
        raise ValueError('state needs spin 0, 1 or 2')
    raw = state.get('parity', 'even' if spin == 2 else 'scalar')
    aliases = {0: {'scalar': 'CP-even', 'pseudoscalar': 'CP-odd', 'even': 'CP-even',
                   'odd': 'CP-odd', 'cp-even': 'CP-even', 'cp-odd': 'CP-odd'},
               1: {'scalar': 'mixed chiral', 'pseudoscalar': 'mixed chiral', 'mixed': 'mixed chiral',
                   'mixed_chiral': 'mixed chiral', 'axial': 'axial-vector'},
               2: {'CP-even': 'even', 'cp-even': 'even'}}
    parity = aliases[spin].get(raw, raw)
    if parity not in PARITY_CLASSES[spin]:
        raise ValueError(f'state parity for spin {spin} must be ' + ', '.join(PARITY_CLASSES[spin]))
    return parity


def _disposition(spin, parity, channel):
    row = {'spin': spin, 'parity': parity, 'channel': channel}
    if spin == 1 and channel in ('photons', 'gluons'):
        return {**row, 'disposition': 'forbidden', 'selection_rule': LANDAU_YANG}
    if spin == 2 or channel in ('zgamma', 'vector_scalar', 'scalar_pair'):
        reason = ('No spin-2 partial-width formula is implemented here, including for minimal universal '
                  'couplings to the energy-momentum tensor.' if spin == 2 else
                  f'No {channel} partial-width formula or coupling convention is implemented here.')
        return {**row, 'disposition': 'free', 'free_reason': reason, 'checkin_sentence': FREE_SENTENCE}
    if channel.startswith('ff_'):
        if spin == 0:
            function = 'width_scalar_to_fermions_mixed'
            convention = ('L = -phi fbar (y_s + i y_p gamma5) f; y_s and y_p are real dimensionless '
                          'couplings. CP-even sets y_p=0; CP-odd sets y_s=0; mixed admits both. '
                          'The legacy kappa input means y=kappa m_f/v, v=(sqrt(2) GF)^(-1/2).')
            formula = 'Gamma = Nc M/(8 pi) (y_s^2 beta^3 + y_p^2 beta)'
        else:
            function = 'width_vector_to_fermions'
            convention = ('L = X_mu fbar gamma^mu (g_V - g_A gamma5) f; real dimensionless couplings. '
                          'Vector sets g_A=0; axial-vector sets g_V=0; mixed chiral admits both.')
            formula = 'Gamma = Nc M beta/(12 pi) [g_V^2 (1+2x) + g_A^2 (1-4x)]'
    elif spin == 0 and channel in ('ww', 'zz'):
        function = 'width_scalar_to_vv_effective'
        convention = ('L = (a/2) phi Z_mu Z^mu - (g_e/4) phi Z_mn Z^mn - (g_o/4) phi Z_mn Ztilde^mn '
                      'for ZZ; for W+W- replace 1/2,1/4,1/4 by 1,1/2,1/2 and use charged conjugate '
                      'fields. a is real in GeV; g_e and g_o are real in GeV^-1; '
                      'Vtilde^mn = epsilon^mnrs V_rs/2. Metric +---. The vertex is '
                      'a e1.e2 + g_e [(q1.q2)(e1.e2)-(q1.e2)(q2.e1)] + g_o epsilon(e1,e2,q1,q2). '
                      'CP-even sets g_o=0; CP-odd sets a=g_e=0. The optional tree convention is '
                      'a=2 kappa m_V^2/v, v=(sqrt(2) GF)^(-1/2).')
        formula = ('Gamma = S beta/(16 pi M) [2(a+g_e d)^2 + (a d/m_V^2+g_e m_V^2)^2 '
                   '+ g_o^2 M^4 beta^2/2], d=M^2/2-m_V^2; S=1 (WW), 1/2 (ZZ)')
    elif spin == 0:
        function = 'width_scalar_to_gluons_effective' if channel == 'gluons' else 'width_scalar_to_photons_effective'
        convention = ('L = -(phi/4) [g_e F_mn F^mn + g_o F_mn Ftilde^mn]; real g_e,g_o in GeV^-1. '
                      'For gluons replace F by G^a and sum eight colour states. CP-even sets g_o=0; '
                      'CP-odd sets g_e=0; mixed admits both. The CP-even loop kinds match this '
                      'on-shell vertex: g_e=alpha/(2 pi v) [sum Nc Q^2 kappa_f A_1/2(tau_f) '
                      '+ kappa_W A_1(tau_W)] for photons; g_e=alpha_s/(3 pi v) '
                      '[3/4 sum kappa_q A_1/2(tau_q)] for gluons; v=(sqrt(2) GF)^(-1/2), '
                      'tau_i=M^2/(4 m_i^2). Each kappa scales the corresponding SM-like coupling. '
                      'Loop form factors can be complex; use |g_e|^2 for their squared amplitude.')
        formula = 'Gamma = N (g_e^2+g_o^2) M^3/(64 pi), N=1 (photons), 8 (gluons)'
    elif channel == 'ww':
        function = 'width_vector_to_ww'
        convention = ('L = -i g [X_mn W+^m W-^n + X^m (W-_mn W+^n - W+_mn W-^n)]; '
                      'real dimensionless g; V_mn=partial_m V_n-partial_n V_m. Vertex: '
                      'g [(eX.(q1-q2))(e1.e2)+2(q2.e1)(eX.e2)-2(q1.e2)(eX.e1)]. '
                      'Vector, axial-vector and mixed chiral labels specify fermion currents. In the '
                      'neutral-current CP convention X_mu(t,x) -> -X^mu(t,-x) this operator '
                      'conserves CP for every spin-1 coupling class; with an axial-vector parent it '
                      'violates P and C separately.')
        formula = 'Gamma = g^2 M/(192 pi x^2) beta^3 (1+20x+12x^2)'
    else:
        function = 'width_vector_to_identical_vv'
        convention = ('L = g4 X_mu Z_nu partial^nu Z^mu + g5 epsilon^munurs X_mu Z_nu partial_r Z_s; '
                      'g4,g5 are real dimensionless couplings. Metric +---, epsilon convention fixed '
                      'by vertex g4 [(P.e1)(eX.e2)+(P.e2)(eX.e1)] + g5 epsilon(eX,e1,e2,q1-q2), '
                      'P=q1+q2. Both tensors are Bose symmetric. In the neutral-current CP convention '
                      'X_mu(t,x) -> -X^mu(t,-x) and Z_mu(t,x) -> -Z^mu(t,-x), g4 violates CP '
                      'and g5 conserves CP for every spin-1 coupling class. Vector/axial labels specify '
                      'fermion currents, not a restriction to CP-conserving bosonic couplings. Includes the ZZ factor 1/2 '
                      'and initial polarization average 1/3; no off-shell or massless extrapolation.')
        formula = 'Gamma = M^3/(96 pi m_V^2) beta^3 (g4^2 + g5^2 beta^2)'
    return {**row, 'disposition': 'formula', 'function': function, 'lagrangian': convention,
            'formula': formula}


def channel_table():
    """All 77 combinations, each with exactly one disposition; no model-specific inputs."""
    return {'schema_version': 1, 'scope': 'Colour-singlet, electrically neutral s-channel resonance; on-shell two-body decays.',
            'kinematics': 'M is the parent mass; x=m_daughter^2/M^2; beta=sqrt(1-4x); closed channels have zero width.',
            'rows': [_disposition(s, p, c) for s, ps in PARITY_CLASSES.items() for p in ps for c in CHANNEL_CLASSES]}


def table_json():
    return json.dumps(channel_table(), indent=2, allow_nan=False) + '\n'


def table_markdown(table=None):
    """Render the documentation region from the generated JSON, without another coverage table."""
    table = table if table is not None else json.loads(TABLE_PATH.read_text())
    lines = ['<!-- BEGIN GENERATED LINESHAPE CHANNELS -->',
             '| Spin | Parity or CP class | ' + ' | '.join(CHANNEL_CLASSES) + ' |',
             '|---|---|' + '---|' * len(CHANNEL_CLASSES)]
    for spin, parities in PARITY_CLASSES.items():
        for parity in parities:
            rows = [r for r in table['rows'] if r['spin'] == spin and r['parity'] == parity]
            by_channel = {r['channel']: r['disposition'] for r in rows}
            lines.append(f'| {spin} | {parity} | ' + ' | '.join(by_channel[c] for c in CHANNEL_CLASSES) + ' |')
    return '\n'.join([*lines, '<!-- END GENERATED LINESHAPE CHANNELS -->'])


def _finite(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    if positive and value <= 0:
        raise ValueError(f'{name} must be positive')
    if nonnegative and value < 0:
        raise ValueError(f'{name} must be nonnegative')
    return float(value)


def _beta(mass, daughter):
    r = 4.0 * daughter * daughter / (mass * mass)
    return math.sqrt(1.0 - r) if r < 1.0 else 0.0


# ----------------------------------------------------------------- propagators

def complex_pole_from_on_shell(mass, width):
    mass, width = _finite(mass, 'mass', positive=True), _finite(width, 'width', nonnegative=True)
    norm = math.sqrt(1.0 + (width / mass) ** 2)
    return mass / norm, width / norm


def on_shell_from_complex_pole(mu, gamma):
    mu, gamma = _finite(mu, 'pole mass', positive=True), _finite(gamma, 'pole width', nonnegative=True)
    norm = math.sqrt(1.0 + (gamma / mu) ** 2)
    return mu * norm, gamma * norm


def propagator(s, mass, width, scheme):
    """Complex s-channel propagator (GeV^-2) in the declared scheme."""
    if scheme not in SCHEMES:
        raise ValueError('unknown propagator scheme; choose one of ' + ', '.join(SCHEMES))
    s = _finite(s, 's', nonnegative=True)
    mass, width = _finite(mass, 'mass', positive=True), _finite(width, 'width', nonnegative=True)
    if scheme == 'running':
        return 1.0 / complex(s - mass * mass, s * width / mass)
    return 1.0 / complex(s - mass * mass, mass * width)


def lineshape(s, mass, width, scheme):
    value = propagator(s, mass, width, scheme)
    return (value * value.conjugate()).real


# --------------------------------------------------------------- loop functions

def _f(tau):
    if tau <= 1.0:
        return complex(math.asin(math.sqrt(tau)) ** 2, 0.0)
    root = math.sqrt(1.0 - 1.0 / tau)
    return -0.25 * (cmath.log((1.0 + root) / (1.0 - root)) - 1j * math.pi) ** 2


def _real_if_possible(value):
    return value.real if abs(value.imag) == 0.0 else value


def loop_a_half(tau):
    """Spin-1/2 loop amplitude A_1/2(tau), tau = M^2 / (4 m^2); tends to 4/3 for heavy fermions."""
    tau = _finite(tau, 'tau', positive=True)
    if tau < 1e-4:
        return 4.0 / 3.0 + 14.0 * tau / 45.0
    return _real_if_possible(2.0 * (tau + (tau - 1.0) * _f(tau)) / (tau * tau))


def loop_a_one(tau):
    """Spin-1 (W) loop amplitude A_1(tau); tends to -7 for a heavy W."""
    tau = _finite(tau, 'tau', positive=True)
    if tau < 1e-4:
        return -(7.0 + 22.0 * tau / 15.0)
    return _real_if_possible(-(2.0 * tau * tau + 3.0 * tau + 3.0 * (2.0 * tau - 1.0) * _f(tau)) / (tau * tau))


# ------------------------------------------------------------- partial widths

def width_scalar_to_fermions(mass, fermion_mass, coupling, *, n_colour=1, parity='scalar'):
    """L = -y phi fbar f (scalar) or -i y phi fbar g5 f (pseudoscalar)."""
    mass = _finite(mass, 'mass', positive=True)
    fermion_mass = _finite(fermion_mass, 'fermion mass', nonnegative=True)
    coupling = _finite(coupling, 'coupling')
    if parity not in ('scalar', 'pseudoscalar'):
        raise ValueError('parity must be scalar or pseudoscalar')
    beta = _beta(mass, fermion_mass)
    power = 3 if parity == 'scalar' else 1
    return n_colour * coupling * coupling * mass * beta ** power / (8.0 * math.pi)


def width_scalar_to_fermions_mixed(mass, fermion_mass, coupling_scalar, coupling_pseudoscalar, *, n_colour=1):
    """L = -phi fbar (y_s + i y_p gamma5) f; real dimensionless y_s,y_p; no CP cross term."""
    return (width_scalar_to_fermions(mass, fermion_mass, coupling_scalar, n_colour=n_colour)
            + width_scalar_to_fermions(mass, fermion_mass, coupling_pseudoscalar,
                                       n_colour=n_colour, parity='pseudoscalar'))


def width_scalar_to_vv_effective(mass, boson_mass, coupling_even, coupling_odd=0.0, *,
                                  tree_coupling=0.0, identical=True):
    """L = a phi Z.Z/2 - g_e phi Z_mn Z^mn/4 - g_o phi Z_mn Ztilde^mn/4.

    For W+W- the factors are 1,1/2,1/2. Real a is in GeV; real g_e,g_o
    are in GeV^-1. Ztilde^mn=epsilon^mnrs Z_rs/2; metric +---. With outgoing
    momenta and polarization vectors the vertex is a e1.e2 + g_e T + g_o U,
    T=(q1.q2)(e1.e2)-(q1.e2)(q2.e1), U=epsilon(e1,e2,q1,q2).
    The default identical-particle factor is 1/2; use identical=False for WW.

    In the parent rest frame d=q1.q2=M^2/2-m^2: the two equal transverse
    amplitudes are -(a+g_e d), the longitudinal amplitude is a d/m^2+g_e m^2,
    and the two CP-odd transverse amplitudes are +/- g_o M|p|. Their squared
    sum derives beta*(1-4x+6x^2) for pure g_e and beta^3 for pure g_o.
    The tree/even interference is 6 a g_e d before phase space; opposite CP
    has orthogonal transverse tensors and no total-width interference.
    """
    mass = _finite(mass, 'mass', positive=True)
    m = _finite(boson_mass, 'boson mass', nonnegative=True)
    ge, go = _finite(coupling_even, 'coupling_even'), _finite(coupling_odd, 'coupling_odd')
    a = _finite(tree_coupling, 'tree_coupling')
    if m == 0 and a != 0:
        raise ValueError('a tree-like massive-vector coupling has no massless limit')
    beta = _beta(mass, m)
    if beta == 0.0:
        return 0.0
    d = mass * mass / 2.0 - m * m
    longitudinal = a * d / (m * m) + ge * m * m if m else 0.0
    squared = 2.0 * (a + ge * d)**2 + longitudinal**2 + go**2 * mass**4 * beta**2 / 2.0
    return (0.5 if identical else 1.0) * beta * squared / (16.0 * math.pi * mass)


def width_scalar_to_vv(mass, boson_mass, fermi_constant, *, kind, kappa=1.0):
    """L = a phi Z.Z/2 or a phi W+.W-; a=2 kappa m_V^2/v, v=(sqrt(2) GF)^(-1/2).

    kappa is real and dimensionless. kind W is W+W-; kind Z includes the ZZ factor 1/2.
    """
    if kind not in ('W', 'Z'):
        raise ValueError('kind must be W or Z')
    mass = _finite(mass, 'mass', positive=True)
    boson_mass = _finite(boson_mass, 'boson mass', positive=True)
    fermi_constant = _finite(fermi_constant, 'fermi_constant', positive=True)
    kappa = _finite(kappa, 'kappa')
    x = boson_mass * boson_mass / (mass * mass)
    if 4.0 * x >= 1.0:
        return 0.0
    delta = 2.0 if kind == 'W' else 1.0
    return (kappa * kappa * delta * fermi_constant * mass ** 3 / (16.0 * math.sqrt(2.0) * math.pi)
            * math.sqrt(1.0 - 4.0 * x) * (1.0 - 4.0 * x + 12.0 * x * x))


def width_scalar_to_gluons(mass, alpha_s, fermi_constant, *, quarks, parity='scalar'):
    """Quark-loop scalar decay to gluons, SM-like Yukawas scaled by each quark's kappa."""
    mass = _finite(mass, 'mass', positive=True)
    alpha_s = _finite(alpha_s, 'alpha_s', positive=True)
    fermi_constant = _finite(fermi_constant, 'fermi_constant', positive=True)
    if parity != 'scalar':
        raise ValueError('the loop formula is implemented for a CP-even scalar; use gg_effective otherwise')
    if not quarks:
        raise ValueError('at least one loop quark is required')
    amplitude = 0j
    for quark in quarks:
        m = _finite(quark['mass'], 'loop quark mass', positive=True)
        amplitude += _finite(quark.get('kappa', 1.0), 'kappa') * loop_a_half(mass * mass / (4.0 * m * m))
    amplitude *= 0.75
    return (fermi_constant * alpha_s ** 2 * mass ** 3 / (36.0 * math.sqrt(2.0) * math.pi ** 3)
            * abs(amplitude) ** 2)


def width_scalar_to_photons(mass, alpha, fermi_constant, *, fermions, w_boson=None, parity='scalar'):
    """Fermion- and W-loop scalar decay to photons with SM-like couplings scaled by kappa."""
    mass = _finite(mass, 'mass', positive=True)
    alpha = _finite(alpha, 'alpha', positive=True)
    fermi_constant = _finite(fermi_constant, 'fermi_constant', positive=True)
    if parity != 'scalar':
        raise ValueError('the loop formula is implemented for a CP-even scalar; use photons_effective otherwise')
    amplitude = 0j
    for fermion in fermions or []:
        m = _finite(fermion['mass'], 'loop fermion mass', positive=True)
        charge = _finite(fermion['charge'], 'loop fermion charge')
        colours = fermion.get('n_colour', 1)
        if colours not in (1, 3):
            raise ValueError('loop fermion colour multiplicity must be 1 or 3')
        amplitude += (colours * charge * charge * _finite(fermion.get('kappa', 1.0), 'kappa')
                      * loop_a_half(mass * mass / (4.0 * m * m)))
    if w_boson is not None:
        m = _finite(w_boson['mass'], 'W mass', positive=True)
        amplitude += _finite(w_boson.get('kappa', 1.0), 'kappa') * loop_a_one(mass * mass / (4.0 * m * m))
    if amplitude == 0:
        raise ValueError('at least one charged loop particle is required')
    return (fermi_constant * alpha ** 2 * mass ** 3 / (128.0 * math.sqrt(2.0) * math.pi ** 3)
            * abs(amplitude) ** 2)


def width_scalar_to_photons_effective(mass, coupling, coupling_odd=0.0):
    """L = -phi (g_e F F + g_o F Ftilde)/4; real couplings in GeV^-1; Gamma=(g_e^2+g_o^2) M^3/(64 pi)."""
    mass = _finite(mass, 'mass', positive=True)
    coupling = _finite(coupling, 'coupling')
    odd = _finite(coupling_odd, 'coupling_odd')
    # Preserve the legacy arithmetic path and its serialized result exactly.
    return (coupling * coupling + odd * odd) * mass ** 3 / (64.0 * math.pi)


def width_scalar_to_gluons_effective(mass, coupling, coupling_odd=0.0):
    """L = -phi (g_e G^a G^a + g_o G^a Gtilde^a)/4; real GeV^-1 couplings; eight colours."""
    return 8.0 * width_scalar_to_photons_effective(mass, coupling, coupling_odd)


def width_vector_to_fermions(mass, fermion_mass, g_vector, g_axial, *, n_colour=1):
    """L = V_mu fbar gamma^mu (g_V - g_A gamma5) f."""
    mass = _finite(mass, 'mass', positive=True)
    fermion_mass = _finite(fermion_mass, 'fermion mass', nonnegative=True)
    g_vector, g_axial = _finite(g_vector, 'g_vector'), _finite(g_axial, 'g_axial')
    beta = _beta(mass, fermion_mass)
    if beta == 0.0:
        return 0.0
    r = fermion_mass * fermion_mass / (mass * mass)
    return (n_colour * mass * beta / (12.0 * math.pi)
            * (g_vector ** 2 * (1.0 + 2.0 * r) + g_axial ** 2 * (1.0 - 4.0 * r)))


def width_vector_to_ww(mass, w_mass, coupling):
    """L = -i g [X_mn W+^m W-^n + X^m (W-_mn W+^n - W+_mn W-^n)].

    Real dimensionless g_VWW; V_mn=partial_m V_n-partial_n V_m.
    Vertex g [(eX.(q1-q2))(e1.e2)+2(q2.e1)(eX.e2)-2(q1.e2)(eX.e1)].
    Includes initial polarization average 1/3; W+ and W- are distinguishable.
    """
    mass = _finite(mass, 'mass', positive=True)
    w_mass = _finite(w_mass, 'W mass', positive=True)
    coupling = _finite(coupling, 'coupling')
    x = w_mass * w_mass / (mass * mass)
    if 4.0 * x >= 1.0:
        return 0.0
    return (coupling ** 2 * mass / (192.0 * math.pi) * (mass / w_mass) ** 4
            * (1.0 - 4.0 * x) ** 1.5 * (1.0 + 20.0 * x + 12.0 * x * x))


def width_vector_to_identical_vv(mass, boson_mass, g4, g5):
    """L = g4 X_mu Z_nu partial^nu Z^mu + g5 epsilon^munurs X_mu Z_nu partial_r Z_s.

    Real dimensionless g4,g5; metric +---. The on-shell vertex is
    g4 [(P.e1)(eX.e2)+(P.e2)(eX.e1)] + g5 epsilon(eX,e1,e2,q1-q2).
    Both structures are Bose symmetric. In the neutral-current CP convention
    X_mu(t,x)->-X^mu(t,-x), Z_mu(t,x)->-Z^mu(t,-x), g4 violates CP and g5
    conserves CP. Both vector and axial fermion currents have this CP law;
    the coupling classes do not require parity conservation in the bosonic decay.
    Each contributes only longitudinal/transverse pairs: the summed squares
    before the initial 1/3 average are 4 g4^2 M^2 p^2/m^2 and
    16 g5^2 p^4/m^2, with zero interference. Includes identical factor 1/2.
    Requires massive, on-shell identical vectors; no massless extrapolation.
    """
    mass = _finite(mass, 'mass', positive=True)
    m = _finite(boson_mass, 'boson mass', positive=True)
    g4, g5 = _finite(g4, 'g4'), _finite(g5, 'g5')
    beta = _beta(mass, m)
    return mass**3 * beta**3 * (g4*g4 + g5*g5 * beta*beta) / (96.0 * math.pi * m*m)


# -------------------------------------------------------------- consistency

def width_consistency(declared_total, partials, *, rel_tol):
    declared_total = _finite(declared_total, 'declared total width', positive=True)
    rel_tol = _finite(rel_tol, 'relative tolerance', positive=True)
    if not isinstance(partials, dict) or not partials:
        raise ValueError('at least one partial width is required')
    total = math.fsum(_finite(v, 'partial width ' + str(k), nonnegative=True) for k, v in partials.items())
    report = {'declared_total_width_GeV': declared_total, 'partial_sum_GeV': total,
              'ratio_declared_to_sum': declared_total / total if total > 0 else math.inf,
              'relative_tolerance': rel_tol}
    if total > declared_total * (1.0 + rel_tol):
        report.update(status='below_partial_sum', passed=False,
                      reason='the declared total width is smaller than the sum of the computed partial widths')
    elif declared_total > total * (1.0 + rel_tol):
        report.update(status='implied_additional_decays', passed=True,
                      implied_other_branching_fraction=1.0 - total / declared_total,
                      reason='the declared total width implies decays outside the listed channels')
    else:
        report.update(status='consistent', passed=True)
    return report


# --------------------------------------------------------------- requests

def _constant(constants, name):
    if name not in constants:
        raise ValueError(f'constant {name} must be declared in the request')
    return _finite(constants[name], name, positive=True)


def _channel_class(channel):
    kind = channel.get('kind')
    if kind == 'declared':
        # Preserve the legacy sourced-input path; explicit class declarations are gated.
        return channel.get('channel_class')
    if kind == 'ff':
        colours = channel.get('n_colour', 1)
        if type(colours) is not int or colours not in (1, 3):
            raise ValueError('fermion colour multiplicity must be 1 or 3')
        m = _finite(channel.get('fermion_mass_GeV'), 'fermion mass', nonnegative=True)
        return f'ff_{"massless" if m == 0 else "massive"}_colour_{colours}'
    if kind in ('vv_sm_like', 'vv_effective', 'vv_even_effective', 'vv_odd_effective'):
        if channel.get('boson') not in ('W', 'Z'):
            raise ValueError('boson must be W or Z')
        return 'ww' if channel['boson'] == 'W' else 'zz'
    aliases = {'ww': 'ww', 'zz': 'zz', 'zz_bose': 'zz', 'gg_loop': 'gluons',
               'gg_effective': 'gluons', 'photons_loop': 'photons', 'photons_effective': 'photons',
               'vv_massless': 'gluons' if channel.get('final_state') == 'gluons' else 'photons',
               'z_photon': 'zgamma'}
    return aliases.get(kind, kind)


def channel_row(channel, state):
    """Resolve the request to the same disposition used to generate the table."""
    parity = parity_class(state)
    cls = _channel_class(channel)
    if cls is None and channel.get('kind') == 'declared':
        if state['spin'] == 2:
            raise ValueError('a spin-2 declared partial width requires channel_class; use free or declared_free')
        return None
    if cls not in CHANNEL_CLASSES:
        raise ValueError(f'unsupported channel class {cls!r}; choose from ' + ', '.join(CHANNEL_CLASSES))
    return _disposition(state['spin'], parity, cls)


def _check_coupling_class(parity, even, odd):
    even, odd = _finite(even, 'CP-even coupling'), _finite(odd, 'CP-odd coupling')
    if parity == 'CP-even' and odd != 0:
        raise ValueError('a CP-even state cannot use a CP-odd coupling; declare parity mixed')
    if parity == 'CP-odd' and even != 0:
        raise ValueError('a CP-odd state cannot use a CP-even coupling; declare parity mixed')
    return even, odd


def _effective_couplings(channel, parity):
    if 'coupling_per_GeV' in channel:
        if {'coupling_even_per_GeV', 'coupling_odd_per_GeV'} & set(channel):
            raise ValueError('declare either coupling_per_GeV or explicit even/odd couplings')
        if channel.get('kind') == 'vv_odd_effective' or parity == 'CP-odd':
            even, odd = 0.0, channel['coupling_per_GeV']
        elif parity == 'mixed':
            raise ValueError('mixed parity requires explicit coupling_even_per_GeV and coupling_odd_per_GeV')
        else:
            even, odd = channel['coupling_per_GeV'], 0.0
    else:
        if not {'coupling_even_per_GeV', 'coupling_odd_per_GeV'} & set(channel):
            raise ValueError('declare coupling_even_per_GeV or coupling_odd_per_GeV')
        even, odd = channel.get('coupling_even_per_GeV', 0.0), channel.get('coupling_odd_per_GeV', 0.0)
    if channel.get('kind') == 'vv_even_effective' and odd != 0:
        raise ValueError('vv_even_effective requires a zero CP-odd coupling; use vv_effective for mixed')
    if channel.get('kind') == 'vv_odd_effective' and even != 0:
        raise ValueError('vv_odd_effective requires a zero CP-even coupling; use vv_effective for mixed')
    return _check_coupling_class(parity, even, odd)


def evaluate_channel(channel, state, constants):
    kind, spin, mass = channel.get('kind'), state.get('spin'), state.get('mass_GeV')
    cls = parity_class(state)
    row = channel_row(channel, state)
    if row and row['disposition'] == 'forbidden':
        raise ValueError(row['selection_rule'])
    if row and row['disposition'] == 'free':
        raise ValueError(row['free_reason'] + " Use width source 'free' or 'declared_free'.")
    parity = 'scalar' if cls == 'CP-even' else 'pseudoscalar' if cls == 'CP-odd' else cls
    if kind == 'declared':
        if not isinstance(channel.get('source'), str) or not channel['source'].strip():
            raise ValueError('a declared partial width needs its source')
        return _finite(channel['width_GeV'], 'declared partial width', nonnegative=True), 'declared with source'
    if kind == 'vv_massless':
        raise ValueError('use photons_loop, photons_effective, gg_loop or gg_effective for spin 0')
    if spin == 0:
        if kind == 'ff':
            colours = channel.get('n_colour', 1)
            if {'coupling_scalar', 'coupling_pseudoscalar'} & set(channel):
                if {'coupling', 'kappa'} & set(channel):
                    raise ValueError('declare either scalar/pseudoscalar Yukawas or coupling/kappa')
                ys, yp = _check_coupling_class(cls, channel.get('coupling_scalar', 0.0),
                                             channel.get('coupling_pseudoscalar', 0.0))
                return (width_scalar_to_fermions_mixed(mass, channel['fermion_mass_GeV'], ys, yp,
                        n_colour=colours), row['formula'])
            if cls == 'mixed':
                raise ValueError('mixed parity requires explicit coupling_scalar and coupling_pseudoscalar')
            if 'coupling' in channel:
                coupling = channel['coupling']
            else:
                kappa = _finite(channel.get('kappa', 1.0), 'kappa')
                vev = 1.0 / math.sqrt(math.sqrt(2.0) * _constant(constants, 'fermi_constant'))
                coupling = kappa * _finite(channel['fermion_mass_GeV'], 'fermion mass', nonnegative=True) / vev
            return (width_scalar_to_fermions(mass, channel['fermion_mass_GeV'], coupling, n_colour=colours, parity=parity),
                    'Gamma = Nc y^2 M beta^p / (8 pi), p = 3 (scalar) or 1 (pseudoscalar)')
        if kind == 'vv_sm_like':
            if cls == 'CP-odd':
                raise ValueError('a CP-odd state cannot use vv_sm_like; use vv_odd_effective')
            return (width_scalar_to_vv(mass, channel['boson_mass_GeV'], _constant(constants, 'fermi_constant'),
                                       kind=channel.get('boson'), kappa=channel.get('kappa', 1.0)),
                    'Gamma = kappa^2 delta_V GF M^3 / (16 sqrt2 pi) sqrt(1-4x) (1-4x+12x^2)')
        if kind in ('vv_effective', 'vv_even_effective', 'vv_odd_effective'):
            _finite(channel['boson_mass_GeV'], 'boson mass', positive=True)
            even, odd = _effective_couplings(channel, cls)
            if 'tree_coupling_GeV' in channel and 'kappa' in channel:
                raise ValueError('declare either tree_coupling_GeV or kappa, not both')
            tree = _finite(channel.get('tree_coupling_GeV', 0.0), 'tree coupling')
            if 'kappa' in channel:
                tree = (2.0 * _finite(channel['kappa'], 'kappa') * channel['boson_mass_GeV']**2
                        * math.sqrt(math.sqrt(2.0) * _constant(constants, 'fermi_constant')))
            if kind == 'vv_odd_effective' and tree != 0:
                raise ValueError('vv_odd_effective requires zero tree coupling; use vv_effective for mixed')
            _check_coupling_class(cls, tree, 0.0)
            return (width_scalar_to_vv_effective(mass, channel['boson_mass_GeV'], even, odd,
                    tree_coupling=tree, identical=channel['boson'] == 'Z'), row['formula'])
        if kind == 'gg_loop':
            return (width_scalar_to_gluons(mass, _constant(constants, 'alpha_s'), _constant(constants, 'fermi_constant'),
                                           quarks=channel.get('quarks', []), parity=parity),
                    'Gamma = GF as^2 M^3 / (36 sqrt2 pi^3) |3/4 sum kappa_q A_1/2|^2')
        if kind == 'photons_loop':
            return (width_scalar_to_photons(mass, _constant(constants, 'alpha'), _constant(constants, 'fermi_constant'),
                                            fermions=channel.get('fermions', []), w_boson=channel.get('w_boson'), parity=parity),
                    'Gamma = GF a^2 M^3 / (128 sqrt2 pi^3) |sum Nc Q^2 kappa A_1/2 + kappa_W A_1|^2')
        if kind == 'gg_effective':
            even, odd = _effective_couplings(channel, cls)
            if 'coupling_per_GeV' not in channel:
                return width_scalar_to_gluons_effective(mass, even, odd), row['formula']
            return width_scalar_to_gluons_effective(mass, channel['coupling_per_GeV']), 'Gamma = 8 g^2 M^3 / (64 pi)'
        if kind == 'photons_effective':
            even, odd = _effective_couplings(channel, cls)
            if 'coupling_per_GeV' not in channel:
                return width_scalar_to_photons_effective(mass, even, odd), row['formula']
            return width_scalar_to_photons_effective(mass, channel['coupling_per_GeV']), 'Gamma = g^2 M^3 / (64 pi)'
    if spin == 1:
        if kind == 'ff':
            # A pure class fixes the other coupling to zero; its own coupling stays a required input.
            required = {'vector': ('g_vector',), 'axial-vector': ('g_axial',)}.get(cls, ('g_vector', 'g_axial'))
            if any(name not in channel for name in required):
                raise ValueError(f'{cls} parity requires ' + ' and '.join(required))
            g_vector, g_axial = channel.get('g_vector', 0.0), channel.get('g_axial', 0.0)
            if cls == 'vector' and _finite(g_axial, 'g_axial') != 0:
                raise ValueError('vector parity requires g_axial=0; use mixed chiral')
            if cls == 'axial-vector' and _finite(g_vector, 'g_vector') != 0:
                raise ValueError('axial-vector parity requires g_vector=0; use mixed chiral')
            return (width_vector_to_fermions(mass, channel['fermion_mass_GeV'], g_vector, g_axial,
                                             n_colour=channel.get('n_colour', 1)),
                    'Gamma = Nc M beta / (12 pi) [gV^2 (1+2r) + gA^2 (1-4r)]')
        if kind == 'ww':
            return (width_vector_to_ww(mass, channel['boson_mass_GeV'], channel['coupling']),
                    'Gamma = g^2 M / (192 pi) (M/MW)^4 (1-4x)^(3/2) (1+20x+12x^2)')
        if kind in ('zz', 'zz_bose'):
            if not {'g4', 'g5'} & set(channel):
                raise ValueError('declare g4 (CP-violating) or g5 (CP-conserving); an absent one is zero')
            return (width_vector_to_identical_vv(mass, channel['boson_mass_GeV'], channel.get('g4', 0.0),
                                                 channel.get('g5', 0.0)), row['formula'])
    raise ValueError(f'unsupported channel kind {kind!r} for spin {spin!r}')


def evaluate(request):
    if not isinstance(request, dict) or request.get('schema_version') != 1:
        raise ValueError('resonance lineshape request schema_version 1 required')
    allowed = {'schema_version', 'state', 'constants', 'channels', 'width', 'propagator', 'source'}
    if set(request) - allowed or not {'state', 'channels', 'width'} <= set(request):
        raise ValueError('request keys: ' + ', '.join(sorted(allowed)))
    state = request['state']
    if not isinstance(state, dict):
        raise ValueError('state must be an object')
    parity_class(state)
    _finite(state.get('mass_GeV'), 'state mass', positive=True)
    constants = request.get('constants', {})
    if not isinstance(constants, dict):
        raise ValueError('constants must be an object')
    spec = request['width']
    source = spec.get('source') if isinstance(spec, dict) else None
    if source not in ('computed', 'declared_free', 'free'):
        raise ValueError("width source must be 'computed', 'declared_free' or 'free'")
    channels = request['channels']
    if not isinstance(channels, list) or (not channels and source != 'free'):
        raise ValueError('at least one decay channel is required')
    rows, seen = [], set()
    for channel in channels:
        if not isinstance(channel, dict):
            raise ValueError('each channel must be an object')
        identity = channel.get('id')
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError('each channel needs a unique id')
        seen.add(identity)
        disposition = channel_row(channel, state)
        if disposition and disposition['disposition'] == 'forbidden':
            raise ValueError(disposition['selection_rule'])
        if disposition and disposition['disposition'] == 'free':
            if source == 'computed':
                raise ValueError(disposition['free_reason'] + " Use width source 'free' or 'declared_free'.")
            rows.append({'id': identity, 'kind': channel['kind'], 'disposition': 'free',
                         'reason': disposition['free_reason'], 'checkin_sentence': disposition['checkin_sentence']})
            continue
        if source == 'free' and channel.get('kind') == 'declared':
            rows.append({'id': identity, 'kind': 'declared', 'disposition': 'free',
                         'reason': 'A declared partial width is an input, not a formula evaluation.'})
            continue
        width, formula = evaluate_channel(channel, state, constants)
        rows.append({'id': identity, 'kind': channel['kind'], 'width_GeV': width, 'formula': formula})
    partials = {r['id']: r['width_GeV'] for r in rows if 'width_GeV' in r}
    partial_sum = math.fsum(partials.values())
    if source == 'computed':
        if partial_sum <= 0:
            raise ValueError('computed total width is zero; every listed channel is closed')
        total, check = partial_sum, {'status': 'computed', 'passed': True}
    elif source == 'declared_free':
        total = _finite(spec.get('total_width_GeV'), 'declared total width', positive=True)
        check = (width_consistency(total, partials, rel_tol=spec.get('rel_tol', 0.01)) if partials else
                 {'status': 'no_computed_partials', 'passed': True, 'consistency_claim': False,
                  'reason': 'No partial-width consistency check is available.'})
    else:
        if ('total_width_GeV' in spec) == ('width_over_mass' in spec):
            raise ValueError('free width requires exactly one of total_width_GeV or width_over_mass')
        total = (_finite(spec['total_width_GeV'], 'free total width', positive=True) if 'total_width_GeV' in spec else
                 _finite(spec['width_over_mass'], 'free width_over_mass', positive=True) * state['mass_GeV'])
        _finite(total, 'free total width', positive=True)
        check = {'status': 'free', 'passed': True, 'consistency_claim': False, 'reason': FREE_SENTENCE}
    for row in rows:
        if source != 'free' and 'width_GeV' in row:
            row['branching_fraction'] = row['width_GeV'] / total
    result = {'schema_version': 1, 'state': state, 'channels': rows, 'partial_sum_GeV': partial_sum,
              'total_width_GeV': total, 'width_source': source, 'width_over_mass': total / state['mass_GeV'],
              'width_check': check}
    if 'propagator' in request:
        p = request['propagator']
        scheme = p.get('scheme')
        parameters = p.get('parameters', 'on_shell')
        if parameters not in ('on_shell', 'pole'):
            raise ValueError("propagator parameters must be 'on_shell' or 'pole'")
        mass, width = state['mass_GeV'], total
        if scheme == 'complex-pole' and parameters == 'on_shell':
            mass, width = complex_pole_from_on_shell(mass, width)
        points = p.get('sqrt_s_GeV')
        if not isinstance(points, list) or not points or len(points) > 10000:
            raise ValueError('propagator needs 1..10000 sqrt(s) points')
        values = []
        for root_s in points:
            value = propagator(_finite(root_s, 'sqrt(s)', positive=True) ** 2, mass, width, scheme)
            values.append({'sqrt_s_GeV': root_s, 're': value.real, 'im': value.imag, 'abs2': abs(value) ** 2})
        result['propagator'] = {'scheme': scheme, 'parameters': parameters, 'mass_GeV': mass,
                                'width_GeV': width, 'values': values}
    return result


def study_assumptions(request):
    """CHECK-IN 1 states the chosen row and the source of the total width before approval."""
    evaluate(request)
    assumptions = ['Couplings, masses and constants are declared inputs.',
                   'Widths are leading order; the propagator scheme is declared.']
    source = request['width']['source']
    if source == 'computed':
        assumptions.append('The total width is computed as the sum of the listed partial widths.')
    if source == 'free':
        assumptions.append(FREE_SENTENCE)
    for channel in request['channels']:
        row = channel_row(channel, request['state'])
        if row is None:
            assumptions.append(f"Channel {channel['id']}: partial width declared with source {channel['source']}.")
            continue
        prefix = f"Channel {channel['id']}: spin {row['spin']}, {row['parity']}, {row['channel']}. "
        if row['disposition'] == 'formula':
            assumptions.append(prefix + 'Leading-order formula: ' + row['formula'] + '. ' + row['lagrangian'])
        elif row['disposition'] == 'free':
            assumptions.append(prefix + row['free_reason'])
            if row['checkin_sentence'] not in assumptions:
                assumptions.append(row['checkin_sentence'])
    if source == 'declared_free':
        assumptions.append('The declared total width is checked against available partial widths; '
                           'unlisted decays are not identified.')
    return assumptions


# ------------------------------------------------------- science-mode adapter

def validate(task):
    from ravel.physics import declared_study
    return declared_study.validate_task(task)


def inputs(task, base):
    from ravel.physics import declared_study
    path, request = declared_study.load_request(task, base)
    evaluate(request)
    return declared_study.inputs(path, [__file__])


def run(task, base, output):
    from ravel.physics import declared_study
    path, request = declared_study.load_request(task, base)
    result = evaluate(request)
    passed = result['width_check']['passed']
    return declared_study.deliver(output, 'resonance-lineshape.json', {
        'status': 'passed' if passed else 'failed', 'physics_validated': False, 'scope': SCOPE,
        'request': {'path': str(path), 'sha256': declared_study.sha256(path)},
        'lineshape': result, 'limitations': LIMITATIONS})


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel lineshape', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    table = sub.add_parser('table', help='generate the complete channel disposition table')
    table.add_argument('--write', nargs='?', const=TABLE_PATH, type=Path,
                       help='write JSON to this path (default: packaged channels.json)')
    ev = sub.add_parser('evaluate', help='compute widths, branching fractions and propagator values; no approval needed')
    ev.add_argument('--request', required=True, type=Path)
    ev.add_argument('--out', type=Path, help='new JSON file (default: print)')
    from ravel.physics import declared_study
    declared_study.plan_arguments(sub.add_parser('plan', help='prepare an approvable resonance-lineshape study'))
    args = parser.parse_args(argv)
    if args.command == 'table':
        if args.write is None:
            print(table_json(), end='')
        else:
            args.write.parent.mkdir(parents=True, exist_ok=True)
            args.write.write_text(table_json())
        return 0
    if args.command == 'plan':
        from ravel.workflow.state_io import read_json
        return declared_study.prepare(args, mode='resonance-lineshape',
                                      assumptions=study_assumptions(read_json(Path(args.request).expanduser())))
    result = evaluate(json.loads(args.request.read_text()))
    return declared_study.emit(result, args.out)


if __name__ == '__main__':
    raise SystemExit(main())
