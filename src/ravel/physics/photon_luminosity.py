# SPDX-License-Identifier: Apache-2.0
"""Independent Born photon-photon -> charged-lepton-pair convolution.

For shat=M**2, beta=sqrt(1-4*m**2/shat), z=cos(theta), unit lepton charge:
 d sigma/dz = 2*pi*alpha**2*beta/shat *
 [1+2*beta**2*(1-beta**2)*(1-z**2)-beta**4*z**4]/(1-beta**2*z**2)**2.
The inclusive integral is 4*pi*alpha**2/shat *
 [(3-beta**4)*atanh(beta)-beta*(2-beta**2)].
The hadronic result is integral d tau d y f(x1,Q) f(x2,Q) sigma_hat,
where tau=M**2/s, x1,2=sqrt(tau)*exp(+-y), |y|<=log(1/sqrt(tau)).
A provider has one callable method (x,Q)->x*f_gamma(x,Q).

Domain: equal-energy collinear proton/antiproton beams, unpolarized on-shell
photons, one opposite-charge same-flavour stable lepton pair, finite positive
mass and supplied fixed alpha. Only pair mass, pair |rapidity|, and minimum
individual lepton pT are supported. No other amplitudes, radiation, survival
factor, elastic-only selection, detector effects, or higher-order corrections.
Q is fixed or a supplied multiple of pair mass. Energies/masses/scales are GeV;
outputs are pb. QUADPACK errors estimate quadrature only, excluding density
interpolation and PDF uncertainty. A tabulated density supplies its nodes as
quadrature breakpoints. No generator is launched or imported here.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from copy import deepcopy
import json
import math
import numbers
from pathlib import Path
import subprocess

from scipy.integrate import quad

GEV2_TO_PB = 389379372.1


def _keys(value, required, allowed=None, label='record'):
    if not isinstance(value, dict) or set(value) - set(allowed or required) or set(required) - set(value):
        raise ValueError(f'{label}: missing or unsupported field')


def _number(value, label, *, positive=False):
    if type(value) not in (float, int) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f'{label} must be finite and {"positive" if positive else "nonnegative"}')
    return float(value)


def require_photon_density(flavours):
    """Require an explicit installed/supplied flavour census with PDG 22."""
    if not isinstance(flavours, list) or any(type(v) is not int for v in flavours) or 22 not in flavours:
        raise ValueError('PDF set has no photon density (PDG 22) in its supplied flavour census')


def specification(spec):
    """Validate and copy every supplied input; unknown fields are refused."""
    fields = {'energy_gev', 'beams', 'process', 'pdf', 'scale', 'lepton_mass_gev', 'alpha', 'cuts'}
    _keys(spec, fields, fields | {'integration'}, 'specification')
    s = deepcopy(spec)
    _number(s['energy_gev'], 'energy', positive=True)
    if not isinstance(s['beams'], list) or len(s['beams']) != 2 or any(type(b) is not int or abs(b) != 2212 for b in s['beams']):
        raise ValueError('two equal-energy proton or antiproton beams required')
    _keys(s['process'], {'initial', 'final'}, label='process')
    initial, final = s['process']['initial'], s['process']['final']
    if initial != [22, 22] or not isinstance(final, list) or len(final) != 2 or any(type(v) is not int for v in final) or abs(final[0]) not in (11,13,15) or final[1] != -final[0]:
        raise ValueError('formula covers only photon-photon to one charged-lepton pair')
    _number(s['lepton_mass_gev'], 'lepton mass', positive=True)
    _number(s['alpha'], 'alpha', positive=True)
    _keys(s['pdf'], {'name', 'member', 'flavours'}, label='PDF')
    if not isinstance(s['pdf']['name'], str) or not s['pdf']['name'].strip():
        raise ValueError('PDF set name required')
    if type(s['pdf']['member']) is not int or s['pdf']['member'] < 0:
        raise ValueError('PDF member must be a nonnegative integer')
    require_photon_density(s['pdf']['flavours'])
    scale = s['scale']
    if not isinstance(scale, dict) or scale.get('kind') not in ('fixed', 'pair_mass'):
        raise ValueError('scale rule must be fixed or pair_mass')
    key = 'q_gev' if scale['kind'] == 'fixed' else 'factor'
    _keys(scale, {'kind', key}, label='scale')
    _number(scale[key], 'scale ' + key, positive=True)
    cuts = s['cuts']
    _keys(cuts, {'mass_window_gev'}, {'mass_window_gev','pair_abs_rapidity_max','lepton_pt_min_gev'}, 'cut')
    window = cuts['mass_window_gev']
    if not isinstance(window, list) or len(window) != 2:
        raise ValueError('mass window must contain two endpoints')
    lo, hi = [_number(v, 'mass window', positive=True) for v in window]
    if lo >= hi or hi > s['energy_gev']:
        raise ValueError('mass window must be ordered and below collider energy')
    for key in ('pair_abs_rapidity_max','lepton_pt_min_gev'):
        if key in cuts: _number(cuts[key], 'cut ' + key)
    if 'integration' in s:
        _keys(s['integration'], {'epsrel','epsabs_pb'}, label='integration')
        rel = _number(s['integration']['epsrel'], 'integration epsrel', positive=True)
        _number(s['integration']['epsabs_pb'], 'integration epsabs_pb', positive=True)
        if not 1e-12 <= rel < 1:
            raise ValueError('integration epsrel must lie between 1e-12 and 1')
    return s


def partonic_cross_section(shat, mass, alpha, pt_min=0.):
    """Massive Born kernel integrated over the pT-admitted symmetric z interval, pb."""
    shat = _number(shat, 'partonic energy squared', positive=True)
    mass = _number(mass, 'lepton mass', positive=True)
    alpha = _number(alpha, 'alpha', positive=True)
    pt_min = _number(pt_min, 'lepton pT cut')
    if shat <= 4*(mass*mass + pt_min*pt_min): return 0.
    delta = 4*mass*mass/shat
    beta = math.sqrt(1-delta)
    c = math.sqrt(max(0., 1-4*pt_min*pt_min/(shat-4*mass*mass)))
    # Use delta, rather than 1-beta**2, to retain the mass regulator at high energy.
    denominator = delta + (1-delta)*(1-c*c)
    atanh = .5*math.log((1+beta*c)**2/denominator)
    primitive = -c - delta*delta*c/denominator + (3-(1-delta)**2)*atanh/beta
    return 4*math.pi*alpha*alpha*beta/shat*primitive*GEV2_TO_PB


def _density_value(value):
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError('photon density provider must return a real number')
    return _number(float(value), 'photon density')


def _integral(function, lo, hi, rel, absolute, points=()):
    # Interior slope changes of a tabulated density are supplied as breakpoints.
    inside = sorted({p for p in points if lo < p < hi})
    result = quad(function, lo, hi, epsrel=rel, epsabs=absolute, limit=200+2*len(inside),
                  points=inside or None, full_output=1)
    if len(result) != 3 or not all(math.isfinite(v) for v in result[:2]):
        raise ValueError('numerical integration did not converge')
    return result[:2]


def cross_section(spec, density):
    """Return a JSON-ready result with inputs, pb cross section and quadrature estimate."""
    s = specification(spec)
    if not callable(density): raise ValueError('density provider must be callable (x,Q)')
    if isinstance(density, DensityTable):
        for k, requested in [('set',s['pdf']['name']), ('member',s['pdf']['member'])]:
            if density.table[k] != requested: raise ValueError(f'density table {k} differs from setup')
    settings = s.get('integration', {'epsrel': 1e-7, 'epsabs_pb': 1e-9})
    rel, absolute = settings['epsrel'], settings['epsabs_pb']
    lo, hi = s['cuts']['mass_window_gev']
    m, energy = s['lepton_mass_gev'], s['energy_gev']
    pt = s['cuts'].get('lepton_pt_min_gev', 0.)
    lo = max(lo, 2*math.hypot(m,pt))
    max_inner_error = 0.
    log_x, log_q = density.log_nodes() if isinstance(density, DensityTable) else ((), ())

    def integrand(log_mass):
        nonlocal max_inner_error
        pair_mass = math.exp(log_mass)
        bound = math.log(energy/pair_mass)
        bound = min(bound, s['cuts'].get('pair_abs_rapidity_max', bound))
        if bound <= 0: return 0.
        rule = s['scale']
        q = rule['q_gev'] if rule['kind'] == 'fixed' else rule['factor']*pair_mass
        kernel = partonic_cross_section(pair_mass*pair_mass, m, s['alpha'], pt)

        def rapidity(y):
            x1 = pair_mass/energy*math.exp(y)
            x2 = pair_mass/energy*math.exp(-y)
            v1 = _density_value(density(x1,q))
            v2 = _density_value(density(x2,q))
            # d tau = 2 tau d log(M); x1*x2=tau cancels the two x*f factors.
            return 2*v1*v2*kernel
        # x1 or x2 crosses a table node at y = +-(log(x_node)+log(E/M)).
        offset = math.log(energy/pair_mass)
        nodes = [sign*(v+offset) for v in log_x for sign in (1,-1)]
        value, error = _integral(rapidity, -bound, bound, rel, absolute, nodes)
        max_inner_error = max(max_inner_error, error)
        return value

    if lo >= hi:
        value, error = 0., 0.
    else:
        left, right = math.log(lo), math.log(hi)
        rule = s['scale']
        nodes = [v-math.log(rule['factor']) for v in log_q] if rule['kind'] == 'pair_mass' else ()
        value, outer_error = _integral(integrand, left, right, rel, absolute, nodes)
        error = outer_error + max_inner_error*(right-left)
    result = {'schema_version': 1, 'kind': 'photon-luminosity-check', 'spec': s,
              'cross_section_pb': value, 'integration_error_pb': error,
              'integration': dict(settings, method='nested-adaptive-quadrature',
                                  error_scope='quadrature only; excludes density interpolation and PDF uncertainty'),
              'formula': 'massive-unpolarized-born-unit-charge', 'units': 'pb'}
    if isinstance(density, DensityTable):
        result['density_table'] = deepcopy(density.table)
    return result


def _basis(spec, *, omit_member=False):
    s = specification(spec)
    s.pop('integration', None)
    s['pdf'].pop('flavours')
    if omit_member: s['pdf'].pop('member')
    return s


def _check_result(check):
    if check.get('schema_version') != 1 or check.get('kind') != 'photon-luminosity-check' or check.get('units') != 'pb' or check.get('formula') != 'massive-unpolarized-born-unit-charge':
        raise ValueError('checker result schema, formula and pb units required')
    _basis(check['spec'])
    _number(check['cross_section_pb'], 'checker cross section')
    _number(check['integration_error_pb'], 'integration error')


def with_pdf_uncertainty(check, member_checks, prescription):
    """Attach a caller-requested replica or paired symmetric Hessian uncertainty.

    The caller supplies the full error-member list, confidence level and explicit
    rescaling; the code never guesses a set's prescription or its confidence level.
    """
    _check_result(check)
    _keys(prescription, {'kind','members','confidence_level','rescale'}, label='PDF uncertainty prescription')
    p = deepcopy(prescription)
    ids = p['members']
    if not isinstance(ids,list) or len(ids) < 2 or any(type(v) is not int or v < 0 for v in ids) or len(set(ids)) != len(ids) or check['spec']['pdf']['member'] in ids:
        raise ValueError('distinct complete PDF error members required')
    if p['kind'] not in ('replicas','symmetric_hessian') or (p['kind']=='symmetric_hessian' and len(ids)%2):
        raise ValueError('replicas or paired symmetric_hessian PDF prescription required')
    cl = _number(p['confidence_level'], 'PDF confidence level', positive=True)
    if cl >= 1: raise ValueError('PDF confidence level must lie below one')
    _number(p['rescale'], 'PDF uncertainty rescale', positive=True)
    if len(member_checks) != len(ids) or [c['spec']['pdf']['member'] for c in member_checks] != ids:
        raise ValueError('PDF checks must cover all declared members in order')
    for c in member_checks:
        _check_result(c)
        if _basis(c['spec'],omit_member=True) != _basis(check['spec'],omit_member=True):
            raise ValueError('PDF member check setup differs')
    values = [c['cross_section_pb'] for c in member_checks]
    if p['kind']=='replicas':
        mean = math.fsum(values)/len(values)
        error = math.sqrt(math.fsum((v-mean)**2 for v in values)/(len(values)-1))
    else:
        error = .5*math.sqrt(math.fsum((values[i]-values[i+1])**2 for i in range(0,len(values),2)))
    result = deepcopy(check)
    result['pdf_uncertainty'] = {'error_pb': p['rescale']*error, 'prescription': p,
                                 'member_results': deepcopy(member_checks)}
    return result


def compare(check, generator_result, tolerance):
    """Compare finished results with exact setup equality and a supplied relative tolerance.

    Pass requires |generator-check|/check <= tolerance and the quadrature error
    <= tolerance*check. Uncertainties are recorded; they do not widen the tolerance.
    This record grants neither launch authority nor broad generator qualification.
    """
    _check_result(check)
    _keys(generator_result, {'spec','cross_section_pb','statistical_error_pb'}, label='generator result')
    tol = _number(tolerance, 'relative tolerance', positive=True)
    if tol >= 1: raise ValueError('relative tolerance must lie below one')
    if _basis(check['spec']) != _basis(generator_result['spec']):
        raise ValueError('checker and generator setup differ (set, member, energy, beams, process, mass, alpha, cuts or scale rule)')
    reference = check['cross_section_pb']
    observed = _number(generator_result['cross_section_pb'], 'generator cross section')
    stat = _number(generator_result['statistical_error_pb'], 'generator statistical uncertainty')
    delta = abs(observed-reference)
    agreement = delta <= tol*reference
    resolved = check['integration_error_pb'] <= tol*reference
    result = {'schema_version':1, 'kind':'photon-luminosity-comparison',
              'status':'pass' if agreement and resolved else 'fail',
              'relative_difference': delta/reference if reference else None,
              'tolerance':tol, 'cross_section_pb':reference, 'generator_cross_section_pb':observed,
              'statistical_error_pb':stat, 'integration_error_pb':check['integration_error_pb'],
              'agreement':agreement, 'quadrature_resolved':resolved,
              'check':deepcopy(check), 'generator_result':deepcopy(generator_result)}
    if 'pdf_uncertainty' in check: result['pdf_uncertainty'] = deepcopy(check['pdf_uncertainty'])
    return result


def density_request(request):
    """Validate the bounded rectangular worker grid before starting a subprocess."""
    _keys(request, {'set','member','x','q_gev'}, label='worker request')
    r = deepcopy(request)
    if not isinstance(r['set'],str) or not r['set'].strip(): raise ValueError('PDF set required')
    if type(r['member']) is not int or r['member'] < 0: raise ValueError('nonnegative PDF member required')
    for key in ('x','q_gev'):
        values = r[key]
        if not isinstance(values,list) or len(values)<2: raise ValueError('grid needs at least two nodes per axis')
        for v in values: _number(v, 'grid '+key, positive=True)
        if any(a>=b for a,b in zip(values,values[1:])) or (key=='x' and values[-1]>1):
            raise ValueError('grid must be strictly increasing, with 0 < x <= 1')
    if len(r['x'])*len(r['q_gev']) > 100000:
        raise ValueError('density grid exceeds 100000 points; split the request')
    return r


class DensityTable:
    """Bilinear interpolation of x*f in log(x), log(Q); no extrapolation.

    Interpolation error is not inferred from one grid. The caller must compare
    independently refined grids and preserve both results before qualification.
    """
    def __init__(self, table):
        _keys(table, {'schema_version','set','member','x','q_gev','values','flavours','lhapdf_version'}, label='density table')
        r = density_request({k:table[k] for k in ('set','member','x','q_gev')})
        if table['schema_version'] != 1: raise ValueError('density table schema version differs')
        require_photon_density(table['flavours'])
        if not isinstance(table['lhapdf_version'],str) or not table['lhapdf_version'].strip():
            raise ValueError('LHAPDF version required')
        values = table['values']
        if not isinstance(values,list) or len(values)!=len(r['x']) or any(not isinstance(row,list) or len(row)!=len(r['q_gev']) for row in values):
            raise ValueError('density values do not match grid shape')
        for row in values:
            for v in row: _number(v,'density values')
        self.table = deepcopy(table)
        self._lx = [math.log(x) for x in r['x']]
        self._lq = [math.log(q) for q in r['q_gev']]

    def log_nodes(self):
        """Log(x) and log(Q) nodes, where the interpolant changes slope."""
        return list(self._lx), list(self._lq)

    def __call__(self,x,q):
        x = _number(x,'density grid x',positive=True)
        q = _number(q,'density grid Q',positive=True)
        if not self.table['x'][0] <= x <= self.table['x'][-1] or not self.table['q_gev'][0] <= q <= self.table['q_gev'][-1]:
            raise ValueError('density query outside supplied grid; extrapolation refused')
        lx,lq = math.log(x),math.log(q)
        i = min(len(self._lx)-2,max(0,bisect_right(self._lx,lx)-1))
        j = min(len(self._lq)-2,max(0,bisect_right(self._lq,lq)-1))
        u = (lx-self._lx[i])/(self._lx[i+1]-self._lx[i])
        v = (lq-self._lq[j])/(self._lq[j+1]-self._lq[j])
        a,b = self.table['values'][i],self.table['values'][i+1]
        return (1-u)*((1-v)*a[j]+v*a[j+1])+u*((1-v)*b[j]+v*b[j+1])


def density_from_worker(interpreter_argv, request, *, timeout=120):
    """Use a separate generator-environment Python process; never import its binding.

    Production argv is [runtime['python'], '-B'], using generator_versions' paired
    interpreter. Tests supply a fake interpreter script. The only appended entry
    point is the density worker, which launches no scientific generator.
    """
    r = density_request(request)
    if not isinstance(interpreter_argv,list) or not interpreter_argv or any(not isinstance(v,str) or not v for v in interpreter_argv):
        raise ValueError('interpreter argument list required')
    _number(timeout,'worker timeout',positive=True)
    worker = Path(__file__).with_name('photon_density_worker.py')
    try:
        reply = subprocess.run([*interpreter_argv,str(worker)], input=json.dumps(r), text=True,
                               capture_output=True, timeout=timeout, check=False)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise ValueError('photon density worker failed to start or timed out') from exc
    if reply.returncode:
        reason = (reply.stderr or '').strip().splitlines()[-1:]
        raise ValueError(f'photon density worker exit {reply.returncode}' + (f': {reason[0][:200]}' if reason else ''))
    try: table = json.loads(reply.stdout)
    except (ValueError,TypeError) as exc: raise ValueError('worker returned malformed JSON') from exc
    if not isinstance(table,dict): raise ValueError('worker JSON must be a table object')
    for key in ('set','member','x','q_gev'):
        if table.get(key) != r[key]: raise ValueError(f'worker {key} differs from requested set, member or grid')
    return DensityTable(table)


def main(argv=None):
    """Read a supplied density table and a completed generator result; launch nothing."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--spec',required=True,type=Path)
    parser.add_argument('--density-table',required=True,type=Path)
    parser.add_argument('--generator-result',required=True,type=Path)
    parser.add_argument('--tolerance',required=True,type=float)
    parser.add_argument('--output',required=True,type=Path)
    args = parser.parse_args(argv)
    try:
        read = lambda p: json.loads(p.read_text())
        check = cross_section(read(args.spec), DensityTable(read(args.density_table)))
        result = compare(check,read(args.generator_result),args.tolerance)
        args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    except (ValueError,KeyError,OSError) as exc:
        parser.error(str(exc))
    return 0 if result['status']=='pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
