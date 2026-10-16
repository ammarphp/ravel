"""Read per-point helicity-amplitude records written by an amplitude program and turn them into Gram blocks.

An separate program (for example the separately licensed MCFM overlay) writes one
text record per integration draw. The record grammar and the meaning of its
amplitude channels are declared by the program's ``addon.json`` under
``protocol``::

    {"format": "RAVEL_MCFM_3",
     "channels": {"1": {"pdg": [21, 21, 11, -11, 13, -13]}, ...},
     "amplitude_channels": ["up", "down", "bottom", "top", "hbottom", "htop"],
     "members": {"continuum": {"sum": {"up": 2, "down": 2, "bottom": 1, "top": 1}},
                 "scalar_bottom": {"sum": {"hbottom": 1}, "per_reference_propagator": true}, ...},
     "factor": ["grid_weight_over_n", "phase_space", "flux", "pdf_product"],
     "factor_divisor": "branching_ratio", "factor_unit": "fb",
     "safety_cuts": [{"id": "z-candidate-pt", "kind": "pair_pt_min", "min_gev": 0.1,
                      "pairs": [[3, 4], [5, 6]], "identical_pairs": [[3, 6], [5, 4]],
                      "excluded_weight": "measured", "reason": "...", "source": "..."},
                     {"id": "small-invariants", "kind": "normalized_invariant_min", "minimum": 1e-9,
                      "particles": [3, 4, 5, 6], "beams": [1, 2], "reference_energy_gev": 100.0,
                      "excluded_weight": "unmeasured", "reason": "...", "source": "..."}]}

Members marked ``per_reference_propagator`` are divided by the propagator the
program applied, so they become propagator-free numerators. Each record also
carries the program's own squared amplitudes (the point oracle); ``oracle_check``
recomputes them from the captured amplitudes.

A program's phase-space safety cuts are declared under ``safety_cuts`` and
applied by the program when a draw is made: a draw below a cut is written as an
``EXCLUDE`` record (its momenta and, where the cut declares a measured excluded
weight, its weight fields and the program's own squared amplitude with that
square's coupling normalization, as in ``META``), stays in the
draw census and contributes zero, so every integral covers exactly the
restricted phase space. ``pair_pt_min`` bounds the transverse momentum of declared
particle pairs; ``normalized_invariant_min`` bounds E_j / E_ref and
|p_j.p_k| / |E_j E_k| over the declared particles and beams. The program repeats the cuts it
applies in its ``SAFETY`` header; a cut it applies but does not declare is
refused. ``check_safety`` recomputes every cut from the momenta and
``safety_census`` measures the excluded exposure and weight.

Points with identical leptons are integrated by the program with a pairing
partition. The Gram matrices use a hypothesis-independent partition built from
the program's own reference amplitude, so every hypothesis stays a quadratic
form and the estimator stays unbiased.
"""
from __future__ import annotations

import itertools

import numpy as np

from . import amplitude_basis as ab

META = ('s_gev2', 'reference_mass_gev', 'reference_width_gev', 'propagator_re', 'propagator_im', 'normalization',
        'oracle_full', 'oracle_signal_plus_interference', 'oracle_continuum')
WEIGHT = ('grid_weight_over_n', 'phase_space', 'flux', 'pdf_product', 'branching_ratio', 'x1', 'x2',
          'factorization_scale_gev', 'renormalization_scale2_gev2')
HELICITY_INDICES = tuple(itertools.product((1, 2), repeat=4))
OBSERVABLES = ('s_gev2', 'mass_gev', 'factorization_scale_gev', 'x1', 'x2')


FORMAT = 'RAVEL_MCFM_3'
_COMMON = {'id', 'kind', 'excluded_weight', 'reason', 'source'}
CUT_FIELDS = {'pair_pt_min': _COMMON | {'min_gev', 'pairs', 'identical_pairs'},
              'normalized_invariant_min': _COMMON | {'minimum', 'particles', 'beams', 'reference_energy_gev'}}
CUT_KINDS = tuple(CUT_FIELDS)


def _pairs(value, label):
    ab.require(type(value) is list and value and all(
        type(p) is list and len(p) == 2 and all(type(i) is int and 1 <= i <= 6 for i in p) and p[0] != p[1]
        for p in value), f'{label} must list pairs of particle positions 1-6')
    return value


def validate_safety_cuts(cuts):
    """The producer's declared phase-space safety cuts (possibly none)."""
    ab.require(type(cuts) is list, 'safety_cuts must be a list')
    ids = set()
    for cut in cuts:
        ab.require(type(cut) is dict and cut.get('kind') in CUT_KINDS, 'safety cut kind must be one of ' + ', '.join(CUT_KINDS))
        fields = CUT_FIELDS[cut['kind']]
        ab.require(set(cut) == fields, 'each safety cut needs ' + ', '.join(sorted(fields)))
        ab.require(isinstance(cut['id'], str) and cut['id'] and cut['id'] not in ids, 'safety cut ids must be unique names')
        ids.add(cut['id'])
        ab.require(threshold(cut) > 0, 'safety cut threshold must be positive')
        ab.require(cut['excluded_weight'] in ('measured', 'unmeasured'), 'excluded_weight must be measured or unmeasured')
        if cut['kind'] == 'pair_pt_min':
            _pairs(cut['pairs'], f'safety cut {cut["id"]} pairs')
            _pairs(cut['identical_pairs'], f'safety cut {cut["id"]} identical_pairs')
        else:
            for key in ('particles', 'beams'):
                ab.require(type(cut[key]) is list and cut[key] and len(set(cut[key])) == len(cut[key])
                           and all(type(i) is int and 1 <= i <= 6 for i in cut[key]), f'safety cut {key} must list positions 1-6')
            ab.require(not set(cut['particles']) & set(cut['beams']), 'safety cut particles and beams must differ')
            ab.require(ab.real(cut['reference_energy_gev'], 'reference_energy_gev') > 0, 'reference_energy_gev must be positive')
        ab.text(cut['reason'], 'safety cut reason')
        ab.text(cut['source'], 'safety cut source')
    return cuts


def threshold(cut):
    return ab.real(cut['min_gev'] if cut['kind'] == 'pair_pt_min' else cut['minimum'], 'safety cut threshold')


def validate_protocol(protocol):
    ab.require(type(protocol) is dict and protocol.get('format') == FORMAT, f'program protocol {FORMAT} required')
    validate_safety_cuts(protocol.get('safety_cuts', []))
    channels = protocol['amplitude_channels']
    ab.require(type(channels) is list and channels and len(set(channels)) == len(channels), 'amplitude_channels must be unique')
    for name, member in protocol['members'].items():
        ab.require(type(member) is dict and set(member) <= {'sum', 'per_reference_propagator'} and member['sum']
                   and all(ch in channels for ch in member['sum']), f'member {name} must sum declared channels')
    for key in protocol['factor'] + [protocol['factor_divisor']]:
        ab.require(key in WEIGHT, f'factor field {key} is not a record weight field')
    ab.require(protocol['factor_unit'] in ('fb', 'pb', 'nb'), 'factor_unit must be fb, pb or nb')
    for channel in protocol['channels'].values():
        ab.require(type(channel.get('pdg')) is list and len(channel['pdg']) == 6, 'each channel declares six PDG ids')
    return protocol


def _numbers(parts):
    return [float(x.replace('D', 'E').replace('d', 'e')) for x in parts]


def parse(raw, *, operation, draws, seed, channel, protocol):
    """Parse one program output into arrays; every draw must be accounted for exactly once."""
    validate_protocol(protocol)
    nch = len(protocol['amplitude_channels'])
    lines = iter(raw.decode('ascii').splitlines())

    def take(tag, count):
        try:
            parts = next(lines).split()
        except StopIteration as exc:
            raise ValueError('truncated amplitude record') from exc
        ab.require(parts and parts[0] == tag and len(parts) == count + 1, f'expected a {tag} record with {count} fields')
        return parts[1:]

    header = [int(x) for x in take(protocol['format'], 4)]
    ab.require(header == [operation, draws, seed, channel], 'program control (operation, draws, seed, channel) differs')
    domain = _numbers(take('DOMAIN', 8))
    declared = protocol.get('safety_cuts', [])
    count = take('SAFETY', 1)
    ab.require(count[0].isdigit(), 'SAFETY needs the number of applied cuts')
    applied = []
    for i in range(1, int(count[0]) + 1):
        v = take('CUT', 3)
        ab.require(int(v[0]) == i, 'CUT records must be ordered')
        applied.append((v[1], _numbers(v[2:])[0]))
    ab.require(applied == [(c['kind'], threshold(c)) for c in declared],
               'the program applies safety cuts ' + repr(applied) + ' but its manifest declares '
               + repr([(c['kind'], threshold(c)) for c in declared]) + '; an undeclared cut is refused')
    rows, outcomes, summary, expected = [], [], None, 1
    excluded = []
    while True:
        try:
            parts = next(lines).split()
        except StopIteration as exc:
            raise ValueError('missing COMPLETE record') from exc
        ab.require(bool(parts), 'blank record')
        if parts[0] == 'COMPLETE':
            ab.require(len(parts) == 7, 'COMPLETE record needs six fields')
            counts = [int(x) for x in parts[1:6]]
            summary = dict(zip(('attempted', 'accepted', 'rejected', 'failed', 'excluded'), counts))
            summary['cpu_seconds'] = _numbers(parts[6:])[0]
            break
        ab.require(parts[0] in ('POINT', 'REJECT', 'FAIL', 'EXCLUDE') and int(parts[1]) == expected,
                   'draws must be complete and ordered')
        expected += 1
        if parts[0] == 'EXCLUDE':
            ab.require(len(parts) == 5 and parts[2].isdigit() and 1 <= int(parts[2]) <= len(declared)
                       and parts[3] in ('0', '1') and parts[4] in ('0', '1'),
                       'EXCLUDE needs a declared cut index, the identical flag and the measured flag')
            measured = parts[4] == '1'
            ab.require(measured == (declared[int(parts[2]) - 1]['excluded_weight'] == 'measured'),
                       'an EXCLUDE record must carry exactly the excluded weight its cut declares')
            weight, (reference, normalization) = ((_numbers(take('WEIGHT', 9)), _numbers(take('REFERENCE', 2))) if measured
                                                  else ([float('nan')] * 9, (float('nan'), float('nan'))))
            momenta = []
            for j in range(1, 7):
                v = take('P', 5)
                ab.require(int(v[0]) == j, 'momentum rows must be ordered')
                momenta.append(_numbers(v[1:]))
            ab.require(take('ENDEXCLUDE', 1) == [parts[1]], 'ENDEXCLUDE must close its EXCLUDE')
            excluded.append({'draw': int(parts[1]), 'cut': int(parts[2]) - 1, 'identical': parts[3] == '1',
                             'measured': measured, 'weight': weight, 'reference': reference,
                             'normalization': normalization, 'momenta': momenta})
            outcomes.append('EXCLUDE')
            continue
        if parts[0] != 'POINT':
            ab.require(len(parts) == (2 if parts[0] == 'REJECT' else 3), f'{parts[0]} record fields')
            outcomes.append(parts[0])
            continue
        ab.require(len(parts) == 4 and all(v in ('0', '1') for v in parts[2:]), 'POINT flags must be 0 or 1')
        meta, weight, coords = _numbers(take('META', 9)), _numbers(take('WEIGHT', 9)), _numbers(take('COORD', 12))
        momenta = []
        for j in range(1, 7):
            v = take('P', 5)
            ab.require(int(v[0]) == j, 'momentum rows must be ordered')
            momenta.append(_numbers(v[1:]))
        amps = np.zeros((2, 16, nch), dtype=complex)
        for pair in (1, 2):
            for ch in range(1, nch + 1):
                for h, hel in enumerate(HELICITY_INDICES):
                    v = take('A', 8)
                    ab.require([int(x) for x in v[:6]] == [pair, ch, *hel], 'amplitude rows must follow pairing, channel, helicity order')
                    re_, im_ = _numbers(v[6:])
                    amps[pair - 1, h, ch - 1] = complex(re_, im_)
        ab.require(take('ENDPOINT', 1) == [parts[1]], 'ENDPOINT must close its POINT')
        rows.append({'flags': [v == '1' for v in parts[2:]], 'meta': meta, 'weight': weight, 'coords': coords,
                     'momenta': momenta, 'amplitudes': amps})
        outcomes.append('POINT')
    ab.require(expected == draws + 1 and not any(x.strip() for x in lines), 'records must cover exactly the declared draws')
    ab.require(summary['attempted'] == draws and summary['accepted'] == len(rows)
               and summary['rejected'] == outcomes.count('REJECT') and summary['failed'] == outcomes.count('FAIL')
               and summary['excluded'] == len(excluded),
               'COMPLETE census differs from the records')
    n = len(rows)
    arr = lambda key, shape: np.array([r[key] for r in rows], dtype=float).reshape((n, *shape))
    flags = np.array([r['flags'] for r in rows], dtype=bool).reshape(n, 2)
    m = len(excluded)
    out = {'meta': arr('meta', (9,)), 'weight': arr('weight', (9,)), 'coords': arr('coords', (12,)),
           'momenta': arr('momenta', (6, 4)),
           'amplitudes': np.array([r['amplitudes'] for r in rows], dtype=complex).reshape(n, 2, 16, nch),
           'identical': flags[:, 0], 'selected_direct': flags[:, 1],
           'excluded': {'draw': np.array([e['draw'] for e in excluded], dtype=int),
                        'cut': np.array([e['cut'] for e in excluded], dtype=int),
                        'identical': np.array([e['identical'] for e in excluded], dtype=bool),
                        'measured': np.array([e['measured'] for e in excluded], dtype=bool),
                        'weight': np.array([e['weight'] for e in excluded], dtype=float).reshape(m, 9),
                        'reference': np.array([e['reference'] for e in excluded], dtype=float),
                        'normalization': np.array([e['normalization'] for e in excluded], dtype=float),
                        'momenta': np.array([e['momenta'] for e in excluded], dtype=float).reshape(m, 6, 4)},
           'summary': summary, 'domain': domain, 'channel': channel}
    return out


def pair_pt(momenta, pairs):
    """Transverse momentum of each declared pair, shape (points, pairs); positions count from 1."""
    p = np.asarray(momenta, float)
    out = [np.hypot(*(p[:, i - 1, :2] + p[:, j - 1, :2]).T) for i, j in pairs]
    return np.stack(out, axis=1) if out else np.zeros((len(p), 0))


def _dot(p, i, j):
    """Minkowski product in the program's own operation order (E E - px px - py py - pz pz)."""
    return p[:, i, 3] * p[:, j, 3] - p[:, i, 0] * p[:, j, 0] - p[:, i, 1] * p[:, j, 1] - p[:, i, 2] * p[:, j, 2]


def normalized_invariants(momenta, cut):
    """Smallest of E_j / E_ref and |p_j.p_k| / |E_j E_k| over the declared particles j and partners k."""
    p = np.asarray(momenta, float)
    if not len(p):
        return np.zeros(0)
    parts = [i - 1 for i in cut['particles']]
    beams = [i - 1 for i in cut['beams']]
    values = []
    for n, j in enumerate(parts):
        values.append(np.abs(p[:, j, 3] / cut['reference_energy_gev']))
        for k in beams + parts[n + 1:]:
            values.append(np.abs(_dot(p, j, k) / p[:, j, 3] / p[:, k, 3]))
    return np.min(np.stack(values, axis=1), axis=1)


def _cut_values(cut, momenta, identical):
    """The cut variable per point: the smallest declared pair pT (identical-lepton points also use the
    exchanged pairs) or the smallest normalized invariant."""
    if cut['kind'] == 'normalized_invariant_min':
        return normalized_invariants(momenta, cut)
    direct = pair_pt(momenta, cut['pairs']).min(axis=1)
    swapped = pair_pt(momenta, cut['identical_pairs']).min(axis=1)
    return np.where(identical, np.minimum(direct, swapped), direct)


# A value recomputed from printed momenta can differ from the program's own by rounding (a small
# invariant is a cancellation); only points within this relative distance of a cut are given the
# benefit of that doubt.
CUT_RTOL = {'pair_pt_min': 1e-9, 'normalized_invariant_min': 1e-6}


def check_safety(records, protocol):
    """Recompute every declared cut: stored points lie above it and each excluded draw below its cut."""
    cuts = protocol.get('safety_cuts', [])
    ex = records['excluded']
    rows = []
    for k, cut in enumerate(cuts):
        lo, rtol = threshold(cut), CUT_RTOL[cut['kind']]
        stored = _cut_values(cut, records['momenta'], records['identical'])
        mine = ex['cut'] == k
        below = _cut_values(cut, ex['momenta'][mine], ex['identical'][mine])
        rows.append({'id': cut['id'], 'threshold': lo,
                     'stored_below': int(np.count_nonzero(stored < lo * (1 - rtol))),
                     'excluded_above': int(np.count_nonzero(below >= lo * (1 + rtol))),
                     'excluded': int(mine.sum()),
                     'smallest_stored': float(stored.min()) if len(stored) else None})
    unknown = int(np.count_nonzero((ex['cut'] < 0) | (ex['cut'] >= len(cuts))))
    passed = unknown == 0 and all(r['stored_below'] == 0 and r['excluded_above'] == 0 for r in rows)
    return {'passed': passed, 'cuts': rows, 'undeclared_exclusions': unknown,
            'scope': 'every declared cut recomputed from the recorded momenta'}


def safety_census(records, protocol):
    """Measured share of the draws, of the integration factor and of the program's own weight that the cuts exclude.

    The weight is the program's own squared amplitude times the integration factor, summed over
    stored and excluded draws; it is what the program would have integrated without the cut. Draws
    excluded by a cut that declares an unmeasured weight count in the exposure share and are listed
    as ``weight_unmeasured``; the factor and weight shares cover the measured exclusions only.
    """
    ex = records['excluded']
    s = records['summary']
    kept_factor = factor(records, protocol)
    measured = ex['measured']
    lost_factor = factor({'weight': ex['weight'][measured]}, protocol)
    cuts = protocol.get('safety_cuts', [])
    kept_weight = kept_factor * records['meta'][:, 6]
    lost_weight = lost_factor * ex['reference'][measured]
    share = lambda lost, kept: float(lost / (lost + kept)) if lost + kept else 0.0
    return {'attempted': s['attempted'], 'excluded': s['excluded'], 'stored': s['accepted'],
            'by_cut': {c['id']: int(np.count_nonzero(ex['cut'] == k)) for k, c in enumerate(cuts)},
            'weight_unmeasured': int(np.count_nonzero(~measured)),
            'exposure_fraction': s['excluded'] / s['attempted'] if s['attempted'] else 0.0,
            'factor_excluded': float(lost_factor.sum()), 'factor_stored': float(kept_factor.sum()),
            'factor_fraction': share(lost_factor.sum(), kept_factor.sum()),
            'weight_excluded': float(lost_weight.sum()), 'weight_stored': float(kept_weight.sum()),
            'weight_fraction': share(lost_weight.sum(), kept_weight.sum()),
            'weight_unit': protocol['factor_unit']}


def member_names(protocol):
    return list(protocol['members'])


def reference_propagator(records):
    return records['meta'][:, 3] + 1j * records['meta'][:, 4]


def members(records, protocol):
    """Basis amplitudes a[n, pairing, h, k] for the protocol members."""
    channels = protocol['amplitude_channels']
    prop = reference_propagator(records)
    ab.require(np.all(prop != 0), 'the reference propagator must not vanish')
    out = []
    for name, member in protocol['members'].items():
        total = sum(weight * records['amplitudes'][..., channels.index(ch)] for ch, weight in member['sum'].items())
        if member.get('per_reference_propagator'):
            total = total / prop[:, None, None]
        out.append(total)
    return np.stack(out, axis=-1)


def reference_coefficients(records, protocol):
    """Coefficients that reproduce the program's own amplitude at every point."""
    prop = reference_propagator(records)
    return np.stack([prop if m.get('per_reference_propagator') else np.ones_like(prop)
                     for m in protocol['members'].values()], axis=1)


EXCHANGE = np.array([h[2] == h[3] for h in HELICITY_INDICES])


def grams(basis_amplitudes, records):
    a = basis_amplitudes
    return ab.point_grams(a[:, 0], a[:, 1], identical=records['identical'], selected_direct=records['selected_direct'],
                          exchange=EXCHANGE, reference=records['reference'], normalization=records['meta'][:, 5])


def factor(records, protocol):
    w = dict(zip(WEIGHT, records['weight'].T))
    value = np.prod([w[k] for k in protocol['factor']], axis=0) / w[protocol['factor_divisor']]
    ab.require(np.isfinite(value).all(), 'integration factors must be finite')
    return value


def observables(records):
    s = records['meta'][:, 0]
    w = dict(zip(WEIGHT, records['weight'].T))
    return np.stack([s, np.sqrt(s), w['factorization_scale_gev'], w['x1'], w['x2']], axis=1)


def _program_square(direct, swap, records):
    """The program's own estimator: per-amplitude pairing partition."""
    n = direct.shape[0]
    out = np.zeros(n)
    for i in range(n):
        m, s = direct[i], swap[i]
        if not records['identical'][i]:
            out[i] = np.sum(np.abs(m) ** 2)
            continue
        chosen = m if records['selected_direct'][i] else s
        denom = np.abs(m) ** 2 + np.abs(s) ** 2
        ratio = np.where(EXCHANGE, 1 - 2 * (np.conj(m) * s).real / np.where(denom > 0, denom, 1), 1.0)
        out[i] = np.sum(2 * np.abs(chosen) ** 2 * ratio)
    return out * records['meta'][:, 5]


def oracle_check(records, protocol, *, rtol=1e-10):
    """Recompute the program's squared amplitudes from the captured ones."""
    a = members(records, protocol)
    ref = reference_coefficients(records, protocol)
    G = grams(a, {**records, 'reference': ref})
    full_direct = np.einsum('nhk,nk->nh', a[:, 0], ref)
    full_swap = np.einsum('nhk,nk->nh', a[:, 1], ref)
    checks = {'full': (_program_square(full_direct, full_swap, records), records['meta'][:, 6]),
              'gram_full': (ab.evaluate(G, ref), records['meta'][:, 6])}
    continuum = protocol.get('oracle_continuum_member')
    if continuum is not None:
        k = member_names(protocol).index(continuum)
        continuum_square = _program_square(a[:, 0, :, k], a[:, 1, :, k], records)
        checks['continuum'] = (continuum_square, records['meta'][:, 8])
        checks['signal_plus_interference'] = (checks['full'][0] - continuum_square, records['meta'][:, 7])
    residual, raw_residual, roundoff = {}, {}, {}
    for name, (calc, oracle) in checks.items():
        scale = np.maximum(np.abs(oracle), 1e-300)
        error = np.abs(calc - oracle)
        raw_residual[name] = float(np.max(error / scale)) if len(oracle) else 0.0
        if name == 'signal_plus_interference':
            # This recorded oracle is a subtraction of two sums of 16
            # helicity squares. Retain an absolute arithmetic allowance tied
            # to those sums; a tiny difference has no useful relative error
            # below their floating-point resolution. No physics tolerance is
            # enlarged, and the raw residual and unresolved signs stay visible.
            allowance = 64 * np.finfo(float).eps * (np.abs(checks['full'][0]) + np.abs(continuum_square))
            roundoff[name] = {'max_absolute_allowance': float(np.max(allowance)) if len(oracle) else 0.,
                             'unresolved_sign_points': int(np.count_nonzero(np.abs(oracle) <= allowance))}
            error = np.maximum(0., error - allowance)
        residual[name] = float(np.max(error / scale)) if len(oracle) else 0.0
    return {'passed': all(v <= rtol for v in residual.values()), 'max_relative_residual': residual, 'rtol': rtol,
            'raw_max_relative_residual': raw_residual, 'subtraction_roundoff': roundoff,
            'scope': "consistency of the captured amplitudes with the program's own squares, not an accuracy certificate"}


def to_block(records, protocol, *, spin0=None):
    """Gram block contents (gram, factor, observables, momenta, audit amplitudes) for accepted points."""
    safety = check_safety(records, protocol)
    ab.require(safety['passed'], 'a stored point lies below a declared safety cut, or an excluded draw above it: '
               + repr(safety['cuts']))
    a = members(records, protocol)
    records = {**records, 'reference': reference_coefficients(records, protocol)}
    closure = None
    if spin0 is not None:
        extra, closure = spin0_members(records, a, protocol, spin0)
        a = np.concatenate([a, extra], axis=-1)
        records['reference'] = np.concatenate([records['reference'], np.zeros((len(a), extra.shape[-1]))], axis=1)
    G = grams(a, records)
    return {'gram': G, 'factor': factor(records, protocol), 'observables': observables(records),
            'momenta': records['momenta'], 'amplitudes': a}, records, closure


def spin0_members(records, a, protocol, spin0):
    """Spin-0 numerators aligned to the program's CP-even ones by a per-helicity closure fit.

    The fit uses every point's direct pairing and the swapped pairing of points
    with identical leptons; one factor per helicity must reproduce both.
    """
    from . import spin0_amplitudes as sp
    p = records['momenta']
    swapped = p[:, [0, 1, 2, 5, 4, 3]]
    mine = sp.amplitudes(p, spin0['members'], spin0['constants'])
    mine_swap = sp.amplitudes(swapped, spin0['members'], spin0['constants'])
    ids = [m['id'] for m in spin0['members']]
    names = member_names(protocol)
    same = records['identical']
    target = sum(a[:, :, :, names.index(n)] for n in spin0['closure']['program_members'])
    even = sum(mine[:, :, ids.index(i)] for i in spin0['closure']['members'])
    even_swap = sum(mine_swap[:, :, ids.index(i)] for i in spin0['closure']['members'])
    result = sp.closure(np.concatenate([even, even_swap[same]]), np.concatenate([target[:, 0], target[same, 1]]),
                        rtol=spin0['closure']['rtol'])
    aligned = np.stack([sp.align(mine, result), sp.align(mine_swap, result)], axis=1)
    return aligned, result
