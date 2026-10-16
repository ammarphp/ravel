"""Small synthetic fixtures for the amplitude-basis tests: phase-space points and Gram stores."""
import math

import numpy as np

from ravel.physics import amplitude_basis as ab
from ravel.physics import amplitude_store as store
from ravel.physics import spin0_amplitudes as sp

# Illustrative numbers for the algebra only; physical studies supply their own.
CONSTANTS = {'alpha_s': 0.11, 'vev_gev': 250.0, 'z_mass_gev': 90.0, 'z_width_gev': 2.5,
             'lepton_z_couplings': {'left': -0.4, 'right': 0.3}}
PARTICLES = {'pdg': [21, 21, 11, -11, 13, -13], 'status': [-1, -1, 1, 1, 1, 1]}
OBSERVABLES = ['s_gev2', 'mass_gev', 'scale_gev']
SPIN0 = [{'id': 'scalar', 'quark_mass_gev': 173.0, 'production': 'even', 'decay': 'g1'},
         {'id': 'pseudoscalar', 'quark_mass_gev': 173.0, 'production': 'odd', 'decay': 'g4'}]
BASIS = ['continuum', 'scalar', 'pseudoscalar']


def massless(rng, n):
    v = rng.normal(size=(n, 3)) * 100.0
    return np.concatenate([v, np.linalg.norm(v, axis=1)[:, None]], axis=1)


def points(seed=0, n=6):
    """Random gg -> 4 lepton momenta, all outgoing (gluons with negative energy)."""
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n):
        leptons = massless(rng, 4)
        total = leptons.sum(axis=0)
        beta = -total[:3] / total[3]
        b2 = beta @ beta
        g = 1.0 / math.sqrt(1 - b2)
        boosted = []
        for p in leptons:
            bp = beta @ p[:3]
            boosted.append([*(p[:3] + ((g - 1) * bp / b2 + g * p[3]) * beta), g * (p[3] + bp)])
        leptons = np.array(boosted)
        bz = rng.uniform(-0.6, 0.6)
        gz = 1.0 / math.sqrt(1 - bz ** 2)
        z, e = leptons[:, 2].copy(), leptons[:, 3].copy()
        leptons[:, 2], leptons[:, 3] = gz * (z + bz * e), gz * (e + bz * z)
        total = leptons.sum(axis=0)
        a, b = (total[3] + total[2]) / 2, (total[3] - total[2]) / 2
        rows.append(np.concatenate([np.array([[0, 0, -a, -a], [0, 0, b, -b]]), leptons]))
    return np.array(rows)


def hypotheses():
    return [
        {'id': 'SM', 'constant': {'continuum': 1}, 'states': [
            {'mass_gev': 125.0, 'width_gev': 0.004, 'propagator': 'fixed-width', 'couplings': {'scalar': 1}}]},
        {'id': 'H400', 'constant': {'continuum': 1}, 'states': [
            {'mass_gev': 125.0, 'width_gev': 0.004, 'propagator': 'fixed-width', 'couplings': {'scalar': 1}},
            {'mass_gev': 400.0, 'width_gev': 40.0, 'propagator': 'running-width', 'couplings': {'scalar': 0.5}}]},
        {'id': 'A400', 'constant': {'continuum': 1}, 'states': [
            {'mass_gev': 125.0, 'width_gev': 0.004, 'propagator': 'fixed-width', 'couplings': {'scalar': 1}},
            {'mass_gev': 400.0, 'width_gev': 20.0, 'propagator': 'fixed-width', 'couplings': {'pseudoscalar': [0, 0.7]}}]},
    ]


def chunk(rng, n, seed):
    p = points(seed, n)
    spin0 = sp.amplitudes(p, SPIN0, CONSTANTS)
    continuum = 1e-6 * (rng.normal(size=(n, 16)) + 1j * rng.normal(size=(n, 16)))
    a = np.concatenate([continuum[:, :, None], spin0], axis=2)
    s = sp.dot(p[:, 0] + p[:, 1], p[:, 0] + p[:, 1])
    return {'gram': ab.point_grams(a), 'factor': rng.uniform(0.5, 1.5, size=n) * 1e9,
            'observables': np.stack([s, np.sqrt(s), np.sqrt(s) / 2], axis=1), 'momenta': p}, a


def header(**extra):
    return {'basis': BASIS, 'observables': OBSERVABLES, 'particles': PARTICLES, 'factor_unit': 'fb', **extra}


def schedule(blocks=4, draws=12, cohorts=('mixed', 'same')):
    return {'schema_version': 1, 'max_operation_seconds': 1000,
            'blocks': [{'id': f'b{i}', 'cohort': cohorts[i % len(cohorts)], 'seed': 100 + i, 'draws': draws,
                        'max_seconds': 10} for i in range(blocks)]}


def build_store(directory, *, blocks=4, points_per_block=10, draws=12):
    """A complete store; ``draws - points_per_block`` draws of each block are rejections."""
    def produce(block, writer):
        rng = np.random.default_rng(block['seed'])
        values, _ = chunk(rng, points_per_block, block['seed'])
        writer.append(**values)
        return {'attempted': draws, 'accepted': points_per_block, 'rejected': draws - points_per_block, 'failed': 0}
    return store.run_schedule(directory, schedule(blocks, draws), produce, header=header())


# ---------------------------------------------------------------- synthetic add-on program output
CHANNELS = ['up', 'down', 'bottom', 'top', 'hbottom', 'htop']
HELICITIES = [(a, b, c, d) for a in (1, 2) for b in (1, 2) for c in (1, 2) for d in (1, 2)]


def _square(m, s, identical, direct, norm):
    """Independent loop implementation of the program's pairing-partitioned square."""
    total = 0.0
    for i, (_, _, h34, h56) in enumerate(HELICITIES):
        if not identical:
            total += abs(m[i]) ** 2
            continue
        ratio = 1.0
        if h34 == h56:
            ratio = 1 - 2 * (m[i].conjugate() * s[i]).real / (abs(m[i]) ** 2 + abs(s[i]) ** 2)
        total += 2 * abs(m[i] if direct else s[i]) ** 2 * ratio
    return total * norm


# The synthetic program declares the same safety cuts as the MCFM manifest and applies them per draw.
Z_CUT = {'id': 'z-candidate-pt', 'kind': 'pair_pt_min', 'min_gev': 0.1, 'pairs': [[3, 4], [5, 6]],
         'identical_pairs': [[3, 6], [5, 4]], 'excluded_weight': 'measured',
         'reason': 'Synthetic program: amplitudes unreliable below the cut.', 'source': 'Synthetic fixture'}
SMALL_CUT = {'id': 'small-invariants', 'kind': 'normalized_invariant_min', 'minimum': 1e-9, 'particles': [3, 4, 5, 6],
             'beams': [1, 2], 'reference_energy_gev': 100.0, 'excluded_weight': 'unmeasured',
             'reason': 'Synthetic program: discards nearly collinear or soft leptons before weighting.',
             'source': 'Synthetic fixture'}
DECLARED_CUTS = [Z_CUT, SMALL_CUT]


def point_with_pair_pt(seed, pt):
    """One gg -> 4 lepton point (all outgoing) whose pairs (3,4) and (5,6) have transverse momentum ``pt``."""
    rng = np.random.default_rng(seed)
    q, r = rng.normal(size=2) * 30.0, rng.normal(size=2) * 30.0
    transverse = [np.array([pt / 2, 0]) + q, np.array([pt / 2, 0]) - q, np.array([-pt / 2, 0]) + r, np.array([-pt / 2, 0]) - r]
    leptons = []
    for v in transverse:
        z = rng.normal() * 80.0
        leptons.append([v[0], v[1], z, float(np.sqrt(v @ v + z * z))])
    leptons = np.array(leptons)
    e, pz = leptons[:, 3].sum(), leptons[:, 2].sum()
    a, b = (e + pz) / 2, (e - pz) / 2
    return np.concatenate([np.array([[0, 0, -a, -a], [0, 0, b, -b]]), leptons])


def collinear_point(seed):
    """One gg -> 4 lepton point (all outgoing) whose leptons 3 and 4 are exactly collinear."""
    rng = np.random.default_rng(seed)
    a = rng.normal(size=3) * 40.0
    c = 0.5
    r = rng.normal(size=2) * 30.0
    t5, t6 = -(1 + c) * a[:2] / 2 + r, -(1 + c) * a[:2] / 2 - r
    leptons = [a, c * a, np.array([*t5, rng.normal() * 80.0]), np.array([*t6, rng.normal() * 80.0])]
    leptons = np.array([[*v, float(np.linalg.norm(v))] for v in leptons])
    e, pz = leptons[:, 3].sum(), leptons[:, 2].sum()
    return np.concatenate([np.array([[0, 0, -(e + pz) / 2, -(e + pz) / 2], [0, 0, (e - pz) / 2, -(e - pz) / 2]]), leptons])


def below_cut(p, identical, cut):
    """Independent loop evaluation of a declared cut on one point."""
    if cut['kind'] == 'pair_pt_min':
        pt = lambda i, j: float(np.hypot(*(p[i - 1, :2] + p[j - 1, :2])))
        pairs = cut['pairs'] + (cut['identical_pairs'] if identical else [])
        return min(pt(i, j) for i, j in pairs) < cut['min_gev']
    dot = lambda i, j: p[i - 1, 3] * p[j - 1, 3] - p[i - 1, :3] @ p[j - 1, :3]
    values = []
    for n, j in enumerate(cut['particles']):
        values.append(abs(p[j - 1, 3] / cut['reference_energy_gev']))
        values += [abs(dot(j, k) / p[j - 1, 3] / p[k - 1, 3]) for k in cut['beams'] + cut['particles'][n + 1:]]
    return min(values) < cut['minimum']


def reference_square(p):
    """A deterministic stand-in for the program's own squared amplitude at an excluded draw."""
    return float(1e-6 * (1 + np.abs(p[2:, 3]).sum()))


def reference_norm(p):
    """A deterministic stand-in for the coupling normalization of that square."""
    return float(0.5 + 1e-3 * np.abs(p[2, 3]))


def program_output(operation, draws, seed, channel, *, reject=(), fail=(), corrupt=False, higgs=None, exclude=(),
                   leak=(), cuts=None, momenta=None, low_pt=0.04, weights=None, small=(), declared=DECLARED_CUTS):
    """Text output of the add-on program for ``draws`` draws (synthetic amplitudes).

    ``higgs(momenta) -> (direct, swap)`` (each (16,) complex, propagator-free) replaces
    the random scalar numerators, for closure tests. Draws in ``exclude`` and ``leak`` get a
    Z candidate of transverse momentum ``low_pt``; the program excludes every draw below its
    cut at sampling, except ``leak`` draws, which it stores as points (a program that does
    not apply its cut). Draws in ``small`` have two exactly collinear leptons (below the small
    invariant cut). The program applies the ``declared`` cuts in order (the small cut first, as
    MCFM's lowint does). ``cuts`` replaces the applied cuts it reports; ``momenta`` supplies
    the momenta of each draw; ``weights(draw, momenta, square)`` returns the nine weight
    fields of a draw from the program's own squared amplitude there.
    """
    rng = np.random.default_rng(seed)
    identical = channel != 1
    order = sorted(range(len(declared)), key=lambda k: declared[k]['kind'] != 'normalized_invariant_min')
    applied = ([(c['kind'], c['min_gev'] if c['kind'] == 'pair_pt_min' else c['minimum']) for c in declared]
               if cuts is None else cuts)
    lines = [f' RAVEL_MCFM_3 {operation} {draws} {seed} {channel}',
             ' DOMAIN 0 1.69e8 0 1.69e8 0 13000 0 0', f' SAFETY {len(applied)}']
    lines += [f' CUT {i} {kind} {value!r}' for i, (kind, value) in enumerate(applied, 1)]
    accepted = rejected = failed = excluded = 0
    for draw in range(1, draws + 1):
        if draw in reject:
            lines.append(f' REJECT {draw}')
            rejected += 1
            continue
        if draw in fail:
            lines.append(f' FAIL {draw} 3')
            failed += 1
            continue
        if momenta is not None:
            p = np.asarray(momenta[draw - 1], float)
        elif draw in exclude or draw in leak:
            p = point_with_pair_pt(seed * 1000 + draw, low_pt)
        elif draw in small:
            p = collinear_point(seed * 1000 + draw)
        else:
            p = points(seed * 1000 + draw, 1)[0]
        weight = [float(rng.uniform(0.1, 1.0)) * 1e-3, 2.0, 3.0, 0.5, 1.0, 0.1, 0.2, 100.0, 1e4]
        hit = next((k for k in order if below_cut(p, identical, declared[k])), None) if draw not in leak else None
        if hit is not None:
            excluded += 1
            measured = declared[hit]['excluded_weight'] == 'measured'
            if weights is not None:
                weight = list(weights(draw, p, reference_square(p)))
            lines.append(f' EXCLUDE {draw} {hit + 1} {int(identical)} {int(measured)}')
            if measured:
                lines.append(' WEIGHT ' + ' '.join(f'{v:.17e}' for v in weight))
                lines.append(f' REFERENCE {reference_square(p):.17e} {reference_norm(p):.17e}')
            for j in range(6):
                lines.append(f' P {j + 1} ' + ' '.join(f'{v:.17e}' for v in p[j]))
            lines.append(f' ENDEXCLUDE {draw}')
            continue
        accepted += 1
        s = float(sp.dot(p[0] + p[1], p[0] + p[1]))
        mass, width = 125.0, 0.004
        prop = 1 / complex(s - mass ** 2, mass * width)
        amps = (rng.normal(size=(2, 16, 6)) + 1j * rng.normal(size=(2, 16, 6))) * 1e-3
        if higgs is not None:
            d, w = higgs(p)
            amps[0, :, 4], amps[0, :, 5] = 0.0, d * prop
            amps[1, :, 4], amps[1, :, 5] = 0.0, w * prop
        else:
            amps[:, :, 4:] *= prop * 1e4
        norm = float(rng.uniform(0.5, 2.0))
        direct = bool(rng.integers(0, 2))
        cont = 2 * amps[:, :, 0] + 2 * amps[:, :, 1] + amps[:, :, 2] + amps[:, :, 3]
        full = cont + amps[:, :, 4] + amps[:, :, 5]
        f = _square(full[0], full[1], identical, direct, norm)
        c = _square(cont[0], cont[1], identical, direct, norm)
        if corrupt:
            f *= 1.001
        weight[7:] = [np.sqrt(s) / 2, s / 4]
        if weights is not None:
            weight = list(weights(draw, p, f))
        lines.append(f' POINT {draw} {int(identical)} {int(direct)}')
        lines.append(' META ' + ' '.join(f'{v:.17e}' for v in [s, mass, width, prop.real, prop.imag, norm, f, f - c, c]))
        lines.append(' WEIGHT ' + ' '.join(f'{v:.17e}' for v in weight))
        lines.append(' COORD ' + ' '.join(['0.5'] * 12))
        for j in range(6):
            lines.append(f' P {j + 1} ' + ' '.join(f'{v:.17e}' for v in p[j]))
        for pair in (1, 2):
            for ch in range(1, 7):
                for h, hel in enumerate(HELICITIES):
                    a = amps[pair - 1, h, ch - 1]
                    lines.append(f' A {pair} {ch} {" ".join(map(str, hel))} {a.real:.17e} {a.imag:.17e}')
        lines.append(f' ENDPOINT {draw}')
    lines.append(f' COMPLETE {draws} {accepted} {rejected} {failed} {excluded} 0.5')
    return ('\n'.join(lines) + '\n').encode()
