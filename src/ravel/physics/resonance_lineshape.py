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

SCHEMES = ('fixed', 'running', 'complex-pole')
SCOPE = 'Declared-coupling leading-order partial widths, propagator schemes and width consistency'
LIMITATIONS = [
    'Partial widths are leading order in the declared couplings; QCD and electroweak corrections are not applied.',
    'Couplings, masses and constants are taken from the request; they are not derived from a model or fit.',
    'A declared total width larger than the computed partial sum implies decays outside the listed channels; '
    'those channels are not identified.',
]


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


def width_scalar_to_vv(mass, boson_mass, fermi_constant, *, kind, kappa=1.0):
    """SM-like h V V coupling scaled by kappa; kind W (W+W-) or Z (ZZ, identical bosons)."""
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


def width_scalar_to_photons_effective(mass, coupling):
    """L = -(g/4) phi F F (or a F Ftilde); Gamma = g^2 m^3 / (64 pi). coupling in GeV^-1."""
    mass = _finite(mass, 'mass', positive=True)
    coupling = _finite(coupling, 'coupling')
    return coupling * coupling * mass ** 3 / (64.0 * math.pi)


def width_scalar_to_gluons_effective(mass, coupling):
    """L = -(g/4) phi G^a G^a (or G Gtilde); eight gluon colour states."""
    return 8.0 * width_scalar_to_photons_effective(mass, coupling)


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
    """Neutral vector to W+W- through an SM-like triple-gauge structure with coupling g_VWW."""
    mass = _finite(mass, 'mass', positive=True)
    w_mass = _finite(w_mass, 'W mass', positive=True)
    coupling = _finite(coupling, 'coupling')
    x = w_mass * w_mass / (mass * mass)
    if 4.0 * x >= 1.0:
        return 0.0
    return (coupling ** 2 * mass / (192.0 * math.pi) * (mass / w_mass) ** 4
            * (1.0 - 4.0 * x) ** 1.5 * (1.0 + 20.0 * x + 12.0 * x * x))


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


def evaluate_channel(channel, state, constants):
    kind, spin, mass = channel.get('kind'), state.get('spin'), state.get('mass_GeV')
    parity = state.get('parity', 'scalar')
    if kind == 'declared':
        if not isinstance(channel.get('source'), str) or not channel['source'].strip():
            raise ValueError('a declared partial width needs its source')
        return _finite(channel['width_GeV'], 'declared partial width', nonnegative=True), 'declared with source'
    if kind == 'vv_massless':
        if spin == 1:
            raise ValueError('a spin-1 state cannot decay to two massless vectors (Landau-Yang theorem)')
        raise ValueError('use photons_loop, photons_effective, gg_loop or gg_effective for spin 0')
    if spin == 0:
        if kind == 'ff':
            colours = channel.get('n_colour', 1)
            if 'coupling' in channel:
                coupling = channel['coupling']
            else:
                kappa = _finite(channel.get('kappa', 1.0), 'kappa')
                vev = 1.0 / math.sqrt(math.sqrt(2.0) * _constant(constants, 'fermi_constant'))
                coupling = kappa * _finite(channel['fermion_mass_GeV'], 'fermion mass', nonnegative=True) / vev
            return (width_scalar_to_fermions(mass, channel['fermion_mass_GeV'], coupling, n_colour=colours, parity=parity),
                    'Gamma = Nc y^2 M beta^p / (8 pi), p = 3 (scalar) or 1 (pseudoscalar)')
        if kind == 'vv_sm_like':
            return (width_scalar_to_vv(mass, channel['boson_mass_GeV'], _constant(constants, 'fermi_constant'),
                                       kind=channel.get('boson'), kappa=channel.get('kappa', 1.0)),
                    'Gamma = kappa^2 delta_V GF M^3 / (16 sqrt2 pi) sqrt(1-4x) (1-4x+12x^2)')
        if kind == 'gg_loop':
            return (width_scalar_to_gluons(mass, _constant(constants, 'alpha_s'), _constant(constants, 'fermi_constant'),
                                           quarks=channel.get('quarks', []), parity=parity),
                    'Gamma = GF as^2 M^3 / (36 sqrt2 pi^3) |3/4 sum kappa_q A_1/2|^2')
        if kind == 'photons_loop':
            return (width_scalar_to_photons(mass, _constant(constants, 'alpha'), _constant(constants, 'fermi_constant'),
                                            fermions=channel.get('fermions', []), w_boson=channel.get('w_boson'), parity=parity),
                    'Gamma = GF a^2 M^3 / (128 sqrt2 pi^3) |sum Nc Q^2 kappa A_1/2 + kappa_W A_1|^2')
        if kind == 'gg_effective':
            return width_scalar_to_gluons_effective(mass, channel['coupling_per_GeV']), 'Gamma = 8 g^2 M^3 / (64 pi)'
        if kind == 'photons_effective':
            return width_scalar_to_photons_effective(mass, channel['coupling_per_GeV']), 'Gamma = g^2 M^3 / (64 pi)'
    if spin == 1:
        if kind == 'ff':
            return (width_vector_to_fermions(mass, channel['fermion_mass_GeV'], channel['g_vector'], channel['g_axial'],
                                             n_colour=channel.get('n_colour', 1)),
                    'Gamma = Nc M beta / (12 pi) [gV^2 (1+2r) + gA^2 (1-4r)]')
        if kind == 'ww':
            return (width_vector_to_ww(mass, channel['boson_mass_GeV'], channel['coupling']),
                    'Gamma = g^2 M / (192 pi) (M/MW)^4 (1-4x)^(3/2) (1+20x+12x^2)')
    raise ValueError(f'unsupported channel kind {kind!r} for spin {spin!r}')


def evaluate(request):
    if not isinstance(request, dict) or request.get('schema_version') != 1:
        raise ValueError('resonance lineshape request schema_version 1 required')
    allowed = {'schema_version', 'state', 'constants', 'channels', 'width', 'propagator', 'source'}
    if set(request) - allowed or not {'state', 'channels', 'width'} <= set(request):
        raise ValueError('request keys: ' + ', '.join(sorted(allowed)))
    state = request['state']
    if not isinstance(state, dict) or state.get('spin') not in (0, 1):
        raise ValueError('state needs spin 0 or 1')
    _finite(state.get('mass_GeV'), 'state mass', positive=True)
    if state.get('parity', 'scalar') not in ('scalar', 'pseudoscalar'):
        raise ValueError('state parity must be scalar or pseudoscalar')
    constants = request.get('constants', {})
    channels = request['channels']
    if not isinstance(channels, list) or not channels:
        raise ValueError('at least one decay channel is required')
    rows, seen = [], set()
    for channel in channels:
        identity = channel.get('id')
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError('each channel needs a unique id')
        seen.add(identity)
        width, formula = evaluate_channel(channel, state, constants)
        rows.append({'id': identity, 'kind': channel['kind'], 'width_GeV': width, 'formula': formula})
    partial_sum = math.fsum(r['width_GeV'] for r in rows)
    spec = request['width']
    source = spec.get('source') if isinstance(spec, dict) else None
    if source == 'computed':
        if partial_sum <= 0:
            raise ValueError('computed total width is zero; every listed channel is closed')
        total, check = partial_sum, {'status': 'computed', 'passed': True}
    elif source == 'declared_free':
        total = _finite(spec.get('total_width_GeV'), 'declared total width', positive=True)
        check = width_consistency(total, {r['id']: r['width_GeV'] for r in rows}, rel_tol=spec.get('rel_tol', 0.01))
    else:
        raise ValueError("width source must be 'computed' or 'declared_free'")
    for row in rows:
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
    ev = sub.add_parser('evaluate', help='compute widths, branching fractions and propagator values; no approval needed')
    ev.add_argument('--request', required=True, type=Path)
    ev.add_argument('--out', type=Path, help='new JSON file (default: print)')
    from ravel.physics import declared_study
    declared_study.plan_arguments(sub.add_parser('plan', help='prepare an approvable resonance-lineshape study'))
    args = parser.parse_args(argv)
    if args.command == 'plan':
        return declared_study.prepare(args, mode='resonance-lineshape',
                                      assumptions=['Couplings, masses and constants are declared inputs.',
                                                   'Widths are leading order; the propagator scheme is declared.'])
    result = evaluate(json.loads(args.request.read_text()))
    return declared_study.emit(result, args.out)


if __name__ == '__main__':
    raise SystemExit(main())
