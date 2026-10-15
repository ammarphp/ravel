"""Synthetic coverage and independent, explicit two-body amplitude sums."""
import cmath
import itertools
import json
import math
from pathlib import Path

import pytest

from ravel.physics import resonance_lineshape as rl


FREE_SENTENCE = 'The total width is a free parameter of this study and is not derived from couplings.'


def request(spin=0, parity='scalar', channels=None, width=None):
    return {'schema_version': 1, 'state': {'spin': spin, 'parity': parity, 'mass_GeV': 300.0},
            'channels': channels if channels is not None else [
                {'id': 'v', 'kind': 'vv_sm_like', 'boson': 'Z', 'boson_mass_GeV': 30.0}],
            'constants': {'fermi_constant': 1e-5}, 'width': width or {'source': 'computed'}}


def test_pseudoscalar_tree_width_is_refused_before_constants():
    r = request(parity='pseudoscalar')
    r['constants'] = {}
    with pytest.raises(ValueError, match='CP-odd.*vv_odd_effective'):
        rl.evaluate(r)


@pytest.mark.parametrize('kind', ['photons_effective', 'gg_effective'])
def test_mixed_massless_couplings_cannot_be_ambiguous(kind):
    r = request(parity='mixed', channels=[{'id': 'v', 'kind': kind, 'coupling_per_GeV': 0.003}])
    with pytest.raises(ValueError, match='explicit'):
        rl.evaluate(r)


@pytest.mark.parametrize('kind', ['photons_effective', 'gg_effective'])
def test_explicit_and_legacy_massless_couplings_cannot_be_combined(kind):
    c = {'id': 'v', 'kind': kind, 'coupling_per_GeV': 0.003, 'coupling_odd_per_GeV': 0.002}
    with pytest.raises(ValueError, match='either'):
        rl.evaluate(request(channels=[c]))


def test_cp_odd_channel_kind_does_not_admit_a_tree_tensor_in_mixed_state():
    c = {'id': 'v', 'kind': 'vv_odd_effective', 'boson': 'Z', 'boson_mass_GeV': 30.0,
         'coupling_odd_per_GeV': 0.002, 'tree_coupling_GeV': 1.0}
    with pytest.raises(ValueError, match='vv_odd_effective'):
        rl.evaluate(request(parity='mixed', channels=[c]))


def test_massive_vector_channel_needs_positive_daughter_mass():
    c = {'id': 'v', 'kind': 'vv_even_effective', 'boson': 'Z', 'boson_mass_GeV': 0.0,
         'coupling_per_GeV': 0.002}
    with pytest.raises(ValueError, match='positive'):
        rl.evaluate(request(channels=[c]))


def test_spin2_declared_partial_needs_a_channel_class():
    c = {'id': 's', 'kind': 'declared', 'width_GeV': 2.0, 'source': 'synthetic declared input'}
    with pytest.raises(ValueError, match='channel_class'):
        rl.evaluate(request(2, 'even', [c]))


def test_pure_fermion_class_cannot_silently_drop_the_other_yukawa():
    c = {'id': 'f', 'kind': 'ff', 'fermion_mass_GeV': 2.0,
         'coupling_scalar': 0.2, 'coupling_pseudoscalar': 0.1}
    with pytest.raises(ValueError, match='mixed'):
        rl.evaluate(request(channels=[c]))


def test_enumeration_has_exactly_one_disposition_and_regenerates_table():
    table = rl.channel_table()
    keys = [(r['spin'], r['parity'], r['channel']) for r in table['rows']]
    expected = {(s, p, c) for s, ps in rl.PARITY_CLASSES.items() for p in ps for c in rl.CHANNEL_CLASSES}
    assert len(keys) == len(set(keys)) == 77
    assert set(keys) == expected
    for row in table['rows']:
        assert row['disposition'] in ('formula', 'forbidden', 'free')
        if row['disposition'] == 'formula':
            assert callable(getattr(rl, row['function']))
            assert row['lagrangian'] and row['formula']
            assert not {'selection_rule', 'free_reason'} & set(row)
        elif row['disposition'] == 'forbidden':
            assert row['selection_rule'] and 'function' not in row
        else:
            assert row['checkin_sentence'] == FREE_SENTENCE
            assert row['free_reason'] and 'function' not in row
    assert json.loads(rl.TABLE_PATH.read_text()) == table
    assert rl.TABLE_PATH.read_text() == rl.table_json()


def sample_channel(row, mass=300.0, daughter=30.0):
    c = row['channel']
    if c.startswith('ff_'):
        result = {'id': 'f', 'kind': 'ff', 'n_colour': int(c[-1]),
                  'fermion_mass_GeV': 0.0 if 'massless' in c else daughter}
        if row['spin'] == 0:
            if row['parity'] == 'mixed':
                result.update(coupling_scalar=0.2, coupling_pseudoscalar=-0.13)
            else:
                result['coupling'] = 0.2
        else:
            result.update(g_vector=0.0 if row['parity'] == 'axial-vector' else 0.2,
                          g_axial=0.0 if row['parity'] == 'vector' else -0.13)
        return result
    if c in ('ww', 'zz'):
        if row['spin'] == 0:
            return {'id': 'v', 'kind': 'vv_effective', 'boson': 'W' if c == 'ww' else 'Z',
                    'boson_mass_GeV': daughter,
                    'coupling_even_per_GeV': 0.0 if row['parity'] == 'CP-odd' else 0.003,
                    'coupling_odd_per_GeV': 0.002 if row['parity'] in ('CP-odd', 'mixed') else 0.0,
                    'tree_coupling_GeV': 0.0 if row['parity'] == 'CP-odd' else -0.7}
        if c == 'ww':
            return {'id': 'v', 'kind': 'ww', 'boson_mass_GeV': daughter, 'coupling': 0.03}
        return {'id': 'v', 'kind': 'zz', 'boson_mass_GeV': daughter, 'g4': 0.03, 'g5': -0.02}
    if c in ('photons', 'gluons'):
        kind = 'photons_effective' if c == 'photons' else 'gg_effective'
        if row['parity'] == 'mixed':
            return {'id': 'v', 'kind': kind, 'coupling_even_per_GeV': 0.003, 'coupling_odd_per_GeV': -0.002}
        return {'id': 'v', 'kind': kind, 'coupling_per_GeV': 0.003}
    return {'id': 'other', 'kind': c}


def test_every_forbidden_row_refuses_with_its_rule_even_with_free_width():
    for row in rl.channel_table()['rows']:
        if row['disposition'] != 'forbidden':
            continue
        for source in ('computed', 'declared_free', 'free'):
            r = request(row['spin'], row['parity'], [sample_channel(row)],
                        {'source': source, 'total_width_GeV': 2.0})
            with pytest.raises(ValueError) as error:
                rl.evaluate(r)
            assert row['selection_rule'] in str(error.value)


def test_every_free_row_refuses_computation_and_accepts_explicit_free_sources():
    for row in rl.channel_table()['rows']:
        if row['disposition'] != 'free':
            continue
        r = request(row['spin'], row['parity'], [sample_channel(row)])
        with pytest.raises(ValueError, match="free.*declared_free"):
            rl.evaluate(r)
        for source in ('free', 'declared_free'):
            r['width'] = {'source': source, 'total_width_GeV': 2.0}
            result = rl.evaluate(r)
            assert result['total_width_GeV'] == 2.0
            assert result['channels'][0]['disposition'] == 'free'
            assert 'width_GeV' not in result['channels'][0]


@pytest.mark.parametrize('spec', [{'source': 'free', 'total_width_GeV': 0.01},
                                 {'source': 'free', 'width_over_mass': 0.01 / 300.0}])
def test_free_total_is_independent_of_partial_sum(spec):
    r = request(channels=[{'id': 'f', 'kind': 'ff', 'fermion_mass_GeV': 2.0, 'coupling': 0.5}], width=spec)
    result = rl.evaluate(r)
    assert result['width_source'] == 'free'
    assert result['total_width_GeV'] == pytest.approx(0.01)
    assert result['partial_sum_GeV'] > result['total_width_GeV']
    assert result['width_check']['consistency_claim'] is False
    assert result['width_check']['reason'] == FREE_SENTENCE
    assert 'branching_fraction' not in result['channels'][0]
    assert 'implied_other_branching_fraction' not in result['width_check']


@pytest.mark.parametrize('spec', [
    {'source': 'free'}, {'source': 'free', 'total_width_GeV': -1.0},
    {'source': 'free', 'width_over_mass': 0.0},
    {'source': 'free', 'total_width_GeV': 1.0, 'width_over_mass': 0.1}])
def test_free_width_requires_exactly_one_positive_total(spec):
    with pytest.raises(ValueError):
        rl.evaluate(request(channels=[], width=spec))


def test_plan_reads_rows_and_discloses_free_width(tmp_path, monkeypatch):
    from ravel.physics import declared_study
    captured = {}
    def prepare(args, *, mode, assumptions):
        captured.update(mode=mode, assumptions=assumptions)
        return 0
    monkeypatch.setattr(declared_study, 'prepare', prepare)
    path = tmp_path / 'r.json'
    path.write_text(json.dumps(request(2, 'even', [{'id': 's', 'kind': 'scalar_pair'}],
                                      {'source': 'free', 'width_over_mass': 0.03})))
    assert rl.main(['plan', '--request', str(path), '--rundir', str(tmp_path / 'run'),
                    '--review-policy', 'policy.json', '--source', 'synthetic couplings']) == 0
    assert FREE_SENTENCE in captured['assumptions']
    assert any('spin 2' in a and 'scalar_pair' in a for a in captured['assumptions'])


def test_free_width_sentence_reaches_real_unapproved_checkin(tmp_path):
    policy = {'schema_version': 1, 'policy': {
        'schema_version': 1, 'actors': {'proposer': 'worker', 'executor': 'worker',
            'physics_decider': 'decider', 'skeptical_verifier': 'skeptic', 'physics_critic': 'critic'},
        'max_redos': 0, 'allowed_changed_paths': [], 'allowed_stages': ['science'],
        'required_checks': [{'id': 'integrity', 'kind': 'integrity'}],
        'claim_scopes': {'diagnostic': {'checks': ['integrity'], 'actions': ['delivery']}}},
        'correction_contract': {'input_slots': [], 'task_fields': []}}
    rp, pp, run = tmp_path / 'r.json', tmp_path / 'policy.json', tmp_path / 'run'
    rp.write_text(json.dumps(request(2, 'even', [{'id': 's', 'kind': 'scalar_pair'}],
                                    {'source': 'free', 'width_over_mass': 0.03})))
    pp.write_text(json.dumps(policy))
    assert rl.main(['plan', '--request', str(rp), '--rundir', str(run), '--review-policy', str(pp),
                    '--source', 'synthetic declared couplings']) == 0
    checkin = json.loads((run / 'inputs/checkin1.json').read_text())
    assert FREE_SENTENCE in [r['assumption'] for r in checkin['sections']['v']]
    from ravel.workflow import science
    assert not (run / science.APPROVAL).exists()


def test_formula_plan_names_the_convention_and_computed_source():
    r = request(channels=[{'id': 'v', 'kind': 'vv_odd_effective', 'boson': 'W',
                          'boson_mass_GeV': 30.0, 'coupling_per_GeV': 0.003}], parity='CP-odd')
    assumptions = rl.study_assumptions(r)
    assert FREE_SENTENCE not in assumptions
    assert any('Leading-order formula' in a and 'CP-odd' in a and 'GeV^-1' in a for a in assumptions)
    assert any('computed' in a for a in assumptions)


def test_table_command_and_generated_doc_region(tmp_path, capsys):
    out = tmp_path / 'channels.json'
    assert rl.main(['table', '--write', str(out)]) == 0
    assert out.read_text() == rl.table_json()
    capsys.readouterr()
    assert rl.main(['table']) == 0
    assert json.loads(capsys.readouterr().out) == rl.channel_table()
    text = (Path(rl.__file__).resolve().parents[3] / 'docs/reference/models-and-normalization.md').read_text()
    assert rl.table_markdown() in text


def same_result(actual, expected, path='result'):
    """Exact structure, key order, strings and flags; floats to 1e-12 relative.

    The last float digit of the propagator values depends on the platform's
    complex arithmetic, so a byte hash of the result is not portable.
    """
    assert type(actual) is type(expected), path
    if isinstance(expected, dict):
        assert list(actual) == list(expected), path
        for key in expected:
            same_result(actual[key], expected[key], f'{path}.{key}')
    elif isinstance(expected, list):
        assert len(actual) == len(expected), path
        for index, (a, e) in enumerate(zip(actual, expected)):
            same_result(a, e, f'{path}[{index}]')
    elif isinstance(expected, float):
        assert actual == pytest.approx(expected, rel=1e-12, abs=0.0), path
    else:
        assert actual == expected, path


def test_legacy_results_are_unchanged():
    state = {'spin': 1, 'mass_GeV': 300.0}
    r = {'schema_version': 1, 'state': state,
         'channels': [{'id': 'f', 'kind': 'ff', 'fermion_mass_GeV': 3.0, 'g_vector': 0.2,
                       'g_axial': 0.1, 'n_colour': 3}], 'width': {'source': 'computed'},
         'propagator': {'scheme': 'running', 'sqrt_s_GeV': [270.0, 300.0, 330.0]}}
    # Captured on the unmodified base in Step 0. No reference refresh from the implementation.
    for source, expected in LEGACY_RESULTS.items():
        r['width'] = {'source': source}
        if source == 'declared_free':
            r['width'].update(total_width_GeV=4.0, rel_tol=0.01)
        same_result(rl.evaluate(r), {'schema_version': 1, 'state': state, **expected})


LEGACY_FORMULA = 'Gamma = Nc M beta / (12 pi) [gV^2 (1+2r) + gA^2 (1-4r)]'
LEGACY_RESULTS = {
    'computed': {
        'channels': [{'id': 'f', 'kind': 'ff', 'width_GeV': 1.1935187907619118,
                      'formula': LEGACY_FORMULA, 'branching_fraction': 1.0}],
        'partial_sum_GeV': 1.1935187907619118, 'total_width_GeV': 1.1935187907619118,
        'width_source': 'computed', 'width_over_mass': 0.003978395969206372,
        'width_check': {'status': 'computed', 'passed': True},
        'propagator': {'scheme': 'running', 'parameters': 'on_shell', 'mass_GeV': 300.0,
                       'width_GeV': 1.1935187907619118, 'values': [
            {'sqrt_s_GeV': 270.0, 're': -5.8462714803514634e-05, 'im': -9.9155863909349e-07,
             'abs2': 3.4188722107318505e-09},
            {'sqrt_s_GeV': 300.0, 're': 0.0, 'im': -0.0027928620471952673, 'abs2': 7.80007841466374e-06},
            {'sqrt_s_GeV': 330.0, 're': 5.2882264851168096e-05, 'im': -1.212227490880634e-06,
             'abs2': 2.798003431278735e-09}]}},
    'declared_free': {
        'channels': [{'id': 'f', 'kind': 'ff', 'width_GeV': 1.1935187907619118,
                      'formula': LEGACY_FORMULA, 'branching_fraction': 0.29837969769047795}],
        'partial_sum_GeV': 1.1935187907619118, 'total_width_GeV': 4.0,
        'width_source': 'declared_free', 'width_over_mass': 0.013333333333333334,
        'width_check': {'declared_total_width_GeV': 4.0, 'partial_sum_GeV': 1.1935187907619118,
                        'ratio_declared_to_sum': 3.3514344566343213, 'relative_tolerance': 0.01,
                        'status': 'implied_additional_decays', 'passed': True,
                        'implied_other_branching_fraction': 0.701620302309522,
                        'reason': 'the declared total width implies decays outside the listed channels'},
        'propagator': {'scheme': 'running', 'parameters': 'on_shell', 'mass_GeV': 300.0,
                       'width_GeV': 4.0, 'values': [
            {'sqrt_s_GeV': 270.0, 're': -5.8291191869569096e-05, 'im': -3.3133940641649804e-06,
             'abs2': 3.408841629799362e-09},
            {'sqrt_s_GeV': 300.0, 're': 0.0, 'im': -0.0008333333333333334, 'abs2': 6.944444444444446e-07},
            {'sqrt_s_GeV': 330.0, 're': 5.2599602607497555e-05, 'im': -4.040985343179177e-06,
             'abs2': 2.7830477570104532e-09}]}},
}


# All amplitude calculations below are independent of the production width functions.
# Metric (+---), epsilon determinant convention; external states have unit norm.
def dot(a, b):
    return a[0] * b[0] - sum(a[i] * b[i] for i in range(1, 4))


def epsilon(a, b, c, d):
    vectors = (a, b, c, d)
    total = 0j
    for perm in itertools.permutations(range(4)):
        sign = (-1) ** sum(perm[i] > perm[j] for i in range(4) for j in range(i + 1, 4))
        total += sign * math.prod(vectors[i][perm[i]] for i in range(4))
    return total


def kinematics(mass, daughter, tilted=False):
    energy = mass / 2
    momentum = math.sqrt((energy - daughter) * (energy + daughter))
    # An orthonormal triad; the tilted frame exercises all spacetime components.
    tx, ty, axis = ((0.8, 0, -0.6), (0, 1, 0), (0.6, 0, 0.8)) if tilted else (
        (1, 0, 0), (0, 1, 0), (0, 0, 1))
    q1 = (energy, *(momentum * x for x in axis))
    q2 = (energy, *(-momentum * x for x in axis))
    final1 = [(0, *tx), (0, *ty)]
    final2 = [(0, *tx), (0, *ty)]
    if daughter:
        final1.append((momentum / daughter, *(energy * x / daughter for x in axis)))
        final2.append((momentum / daughter, *(-energy * x / daughter for x in axis)))
    initial = [(0, *tx), (0, *ty), (0, *axis)]
    return q1, q2, final1, final2, initial, momentum


def scalar_vector_sum(mass, daughter, even, odd, tree=0.0, *, identical=True, colour=1, tilted=False):
    q1, q2, pol1, pol2, _, p = kinematics(mass, daughter, tilted)
    total = 0.0
    for e1, e2 in itertools.product(pol1, pol2):
        amplitude = (tree * dot(e1, e2)
                     + even * (dot(q1, q2) * dot(e1, e2) - dot(q1, e2) * dot(q2, e1))
                     + odd * epsilon(e1, e2, q1, q2))
        total += abs(amplitude) ** 2
    return total * colour * p / (8 * math.pi * mass**2) * (0.5 if identical else 1.0)


def vector_vector_sum(mass, daughter, coupling=0.0, g4=0.0, g5=0.0, *, identical, tilted=False):
    q1, q2, pol1, pol2, initial, p = kinematics(mass, daughter, tilted)
    parent = tuple(q1[i] + q2[i] for i in range(4))
    difference = tuple(q1[i] - q2[i] for i in range(4))
    total = 0.0
    for ex, e1, e2 in itertools.product(initial, pol1, pol2):
        amplitude = coupling * (dot(ex, difference) * dot(e1, e2)
                                + 2 * dot(q2, e1) * dot(ex, e2) - 2 * dot(q1, e2) * dot(ex, e1))
        amplitude += g4 * (dot(parent, e1) * dot(ex, e2) + dot(parent, e2) * dot(ex, e1))
        amplitude += g5 * epsilon(ex, e1, e2, difference)
        total += abs(amplitude) ** 2
    return total / 3 * p / (8 * math.pi * mass**2) * (0.5 if identical else 1.0)


IDENTITY = [[complex(i == j) for j in range(4)] for i in range(4)]
G0 = [[complex((1 if i < 2 else -1) if i == j else 0) for j in range(4)] for i in range(4)]
PAULI = (((0, 1), (1, 0)), ((0, -1j), (1j, 0)), ((1, 0), (0, -1)))
GAMMA = [G0]
for sigma in PAULI:
    g = [[0j] * 4 for _ in range(4)]
    for i, j in itertools.product(range(2), repeat=2):
        g[i][j + 2], g[i + 2][j] = sigma[i][j], -sigma[i][j]
    GAMMA.append(g)


def matmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


G5 = [[1j * v for v in row] for row in matmul(matmul(matmul(GAMMA[0], GAMMA[1]), GAMMA[2]), GAMMA[3])]


def bilinear(u, vertex, v):
    ubar = [u[i].conjugate() * (1 if i < 2 else -1) for i in range(4)]
    return sum(ubar[i] * vertex[i][j] * v[j] for i in range(4) for j in range(4))


def fermion_sum(mass, daughter, spin, scalar=0.0, pseudo=0.0, vector=0.0, axial=0.0, colour=1):
    q1, q2, _, _, polarizations, p = kinematics(mass, daughter)
    norm = math.sqrt(mass / 2 + daughter)
    def spinors(q, antiparticle):
        result = []
        for chi in ((1, 0), (0, 1)):
            lower = [sum(q[k + 1] * PAULI[k][i][j] * chi[j] for k in range(3) for j in range(2))
                     / (q[0] + daughter) for i in range(2)]
            result.append([norm * x for x in ((*lower, *chi) if antiparticle else (*chi, *lower))])
        return result
    vertices = []
    if spin == 0:
        vertices.append([[scalar * IDENTITY[i][j] + 1j * pseudo * G5[i][j] for j in range(4)] for i in range(4)])
    else:
        chiral = [[vector * IDENTITY[i][j] - axial * G5[i][j] for j in range(4)] for i in range(4)]
        for pol in polarizations:
            slash = [[sum((1 if k == 0 else -1) * pol[k] * GAMMA[k][i][j] for k in range(4))
                      for j in range(4)] for i in range(4)]
            vertices.append(matmul(slash, chiral))
    total = sum(abs(bilinear(u, vtx, v))**2 for vtx, u, v in itertools.product(
        vertices, spinors(q1, False), spinors(q2, True)))
    return colour * total / (2 * spin + 1) * p / (8 * math.pi * mass**2)


@pytest.mark.parametrize('mass', [60.006, 75.0, 140.0, 300.0])
@pytest.mark.parametrize('tilted', [False, True])
def test_every_formula_row_against_independent_amplitude(mass, tilted):
    checked = set()
    for row in rl.channel_table()['rows']:
        if row['disposition'] != 'formula':
            continue
        c = sample_channel(row, mass)
        r = request(row['spin'], row['parity'], [c])
        r['state']['mass_GeV'] = mass
        actual = rl.evaluate(r)['channels'][0]['width_GeV']
        if c['kind'] == 'ff':
            scalar = c.get('coupling_scalar', c.get('coupling', 0) if row['parity'] == 'CP-even' else 0)
            pseudo = c.get('coupling_pseudoscalar', c.get('coupling', 0) if row['parity'] == 'CP-odd' else 0)
            expected = fermion_sum(mass, c['fermion_mass_GeV'], row['spin'], scalar, pseudo,
                                   c.get('g_vector', 0), c.get('g_axial', 0), c['n_colour'])
        elif c['kind'] == 'vv_effective':
            expected = scalar_vector_sum(mass, 30.0, c['coupling_even_per_GeV'],
                                         c['coupling_odd_per_GeV'], c['tree_coupling_GeV'],
                                         identical=c['boson'] == 'Z', tilted=tilted)
        elif c['kind'] in ('photons_effective', 'gg_effective'):
            even = c.get('coupling_even_per_GeV', c.get('coupling_per_GeV', 0) if row['parity'] == 'CP-even' else 0)
            odd = c.get('coupling_odd_per_GeV', c.get('coupling_per_GeV', 0) if row['parity'] == 'CP-odd' else 0)
            expected = scalar_vector_sum(mass, 0.0, even, odd, colour=8 if c['kind'] == 'gg_effective' else 1,
                                         tilted=tilted)
        else:
            expected = vector_vector_sum(mass, 30.0, c.get('coupling', 0), c.get('g4', 0), c.get('g5', 0),
                                         identical=c['kind'] == 'zz', tilted=tilted)
        assert actual == pytest.approx(expected, rel=1e-10, abs=0.0), row
        checked.add((row['spin'], row['parity'], row['channel']))
    assert len(checked) == 42


@pytest.mark.parametrize('mass', [60.006, 75.0, 140.0, 300.0])
def test_threshold_powers_and_interference_are_derived_from_polarizations(mass):
    m, ge, go, a = 30.0, 0.003, -0.002, -0.7
    beta, x = math.sqrt(1 - 4 * m**2 / mass**2), m**2 / mass**2
    # TT: T_even = -d; LL: T_even = m^2. The sum is 2*d^2 + m^4.
    # T_odd has only the two orthogonal transverse pairs: +/- M*p.
    # Phase space adds beta; these sums derive beta*(1-4x+6x^2) and beta^3.
    even = scalar_vector_sum(mass, m, ge, 0)
    odd = scalar_vector_sum(mass, m, 0, go)
    tree = scalar_vector_sum(mass, m, 0, 0, a)
    assert even == pytest.approx(ge**2 * mass**3 / (64 * math.pi) * beta * (1 - 4*x + 6*x*x), rel=1e-10)
    assert odd == pytest.approx(go**2 * mass**3 / (64 * math.pi) * beta**3, rel=1e-10)
    combined = scalar_vector_sum(mass, m, ge, go, a)
    same_cp = scalar_vector_sum(mass, m, ge, 0, a)
    assert combined == pytest.approx(same_cp + odd, rel=1e-12)
    cross = same_cp - even - tree
    assert cross == pytest.approx(3 * a * ge * beta * (mass**2 / 2 - m**2) / (16 * math.pi * mass), rel=1e-10)
    assert abs(cross) > 0
    assert rl.width_scalar_to_vv_effective(mass, m, ge, go, tree_coupling=a) == pytest.approx(combined, rel=1e-10)
    assert vector_vector_sum(mass, m, g4=0.03, g5=-0.02, identical=True) == pytest.approx(
        vector_vector_sum(mass, m, g4=0.03, identical=True)
        + vector_vector_sum(mass, m, g5=-0.02, identical=True), rel=1e-12)
    assert fermion_sum(mass, m, 0, scalar=0.2, pseudo=0.13) == pytest.approx(
        fermion_sum(mass, m, 0, scalar=0.2) + fermion_sum(mass, m, 0, pseudo=0.13), rel=1e-12)


def test_massless_limits_and_identical_factor():
    mass, g = 140.0, 0.003
    for even, odd in ((g, 0), (0, g)):
        aa = rl.width_scalar_to_photons_effective(mass, g)
        assert rl.width_scalar_to_vv_effective(mass, 0.0, even, odd) == pytest.approx(aa, rel=1e-12)
        assert rl.width_scalar_to_vv_effective(mass, 0.0, even, odd, identical=False) == pytest.approx(2*aa)
        assert rl.width_scalar_to_vv_effective(mass, 1e-6, even, odd) == pytest.approx(aa, rel=1e-12)
    for parity in ('scalar', 'pseudoscalar'):
        assert rl.width_scalar_to_fermions(mass, 1e-6, g, parity=parity) == pytest.approx(
            rl.width_scalar_to_fermions(mass, 0, g, parity=parity), rel=1e-12)


def test_zz_tensor_bose_symmetry_and_on_shell_massless_selection_rule():
    q1, q2, pol1, pol2, initial, _ = kinematics(140.0, 30.0, True)
    parent = tuple(q1[i]+q2[i] for i in range(4))
    diff = tuple(q1[i]-q2[i] for i in range(4))
    for ex, e1, e2 in itertools.product(initial, pol1, pol2):
        a4 = dot(parent, e1)*dot(ex, e2)+dot(parent, e2)*dot(ex, e1)
        assert a4 == dot(parent, e2)*dot(ex, e1)+dot(parent, e1)*dot(ex, e2)
        assert epsilon(ex, e1, e2, diff) == pytest.approx(epsilon(ex, e2, e1, tuple(-x for x in diff)), abs=1e-12)
    # Both structures vanish on transverse massless external states. Longitudinal
    # polarizations do not have a massless limit; there is no limit of the massive width.
    assert vector_vector_sum(140.0, 0.0, g4=0.03, g5=0.02, identical=True) == 0


def test_spin1_boson_tensors_have_the_stated_cp_signs():
    # CP reflects every spatial component and exchanges the two daughters; the
    # field phases are common to all three tensors. The gauge tensor and g5
    # change sign together; g4 does not, so g4 alone violates CP.
    flip = lambda v: (v[0], -v[1], -v[2], -v[3])
    q1, q2, pol1, pol2, initial, _ = kinematics(140.0, 30.0, True)

    def tensors(ex, e1, e2, k1, k2):
        total = tuple(k1[i] + k2[i] for i in range(4))
        diff = tuple(k1[i] - k2[i] for i in range(4))
        gauge = dot(ex, diff) * dot(e1, e2) + 2 * dot(k2, e1) * dot(ex, e2) - 2 * dot(k1, e2) * dot(ex, e1)
        return (gauge, dot(total, e1) * dot(ex, e2) + dot(total, e2) * dot(ex, e1),
                epsilon(ex, e1, e2, diff))

    seen = [0.0, 0.0, 0.0]
    for ex, e1, e2 in itertools.product(initial, pol1, pol2):
        direct = tensors(ex, e1, e2, q1, q2)
        mirrored = tensors(flip(ex), flip(e2), flip(e1), flip(q2), flip(q1))
        for index, sign in enumerate((-1, 1, -1)):
            assert mirrored[index] == pytest.approx(sign * direct[index], abs=1e-9)
            seen[index] += abs(direct[index])
    assert all(seen)
    for row in rl.channel_table()['rows']:
        if row['spin'] == 1 and row['channel'] == 'ww':
            assert 'conserves CP for every spin-1 coupling class' in row['lagrangian']
            assert 'CP violation' not in row['lagrangian']
        if row['spin'] == 1 and row['channel'] == 'zz':
            assert 'g4 violates CP and g5 conserves CP for every spin-1 coupling class' in row['lagrangian']


def test_pure_spin1_classes_take_the_absent_coupling_as_zero():
    def width(parity, channel):
        return rl.evaluate(request(1, parity, [channel]))['channels'][0]['width_GeV']
    ff = {'id': 'f', 'kind': 'ff', 'fermion_mass_GeV': 30.0}
    assert width('vector', {**ff, 'g_vector': 0.2}) == width('vector', {**ff, 'g_vector': 0.2, 'g_axial': 0.0})
    assert width('axial-vector', {**ff, 'g_axial': 0.2}) == width(
        'axial-vector', {**ff, 'g_vector': 0.0, 'g_axial': 0.2})
    for parity, channel in (('vector', ff), ('axial-vector', ff), ('mixed chiral', {**ff, 'g_vector': 0.2}),
                            ('mixed chiral', {**ff, 'g_axial': 0.2})):
        with pytest.raises(ValueError, match='g_vector|g_axial'):
            rl.evaluate(request(1, parity, [channel]))
    zz = {'id': 'v', 'kind': 'zz', 'boson_mass_GeV': 30.0}
    assert width('vector', {**zz, 'g4': 0.03}) == width('vector', {**zz, 'g4': 0.03, 'g5': 0.0})
    assert width('vector', {**zz, 'g5': 0.03}) == width('vector', {**zz, 'g4': 0.0, 'g5': 0.03})
    with pytest.raises(ValueError, match='g4.*g5'):
        rl.evaluate(request(1, 'vector', [zz]))


@pytest.mark.parametrize('mass', [60.006, 140.0, 300.0, 400.0])
def test_legacy_tree_and_loop_vertices_against_explicit_polarizations(mass):
    m, gf, kappa, alpha, alpha_s = 30.0, 1e-5, -0.7, 0.007, 0.1
    a = 2 * kappa * m*m * math.sqrt(math.sqrt(2)*gf)
    for kind in ('W', 'Z'):
        assert rl.width_scalar_to_vv(mass, m, gf, kind=kind, kappa=kappa) == pytest.approx(
            scalar_vector_sum(mass, m, 0, 0, a, identical=kind == 'Z'), rel=1e-10)
    # Independently matched one-loop form factors become local on-shell transverse
    # vertices. This checks tensor/phase-space normalization, not a loop integration.
    tau = mass*mass/(4*170.0**2)
    if tau <= 1:
        f = math.asin(math.sqrt(tau))**2
    else:
        root = math.sqrt(1 - 1/tau)
        f = -0.25 * (cmath.log((1+root)/(1-root)) - 1j*math.pi)**2
    half = 2*(tau+(tau-1)*f)/(tau*tau)
    one = -(2*tau*tau+3*tau+3*(2*tau-1)*f)/(tau*tau)
    v = 1/math.sqrt(math.sqrt(2)*gf)
    g_aa = alpha/(2*math.pi*v)*(3*(2/3)**2*half + kappa*one)
    g_gg = alpha_s/(3*math.pi*v)*(0.75*half)
    assert rl.width_scalar_to_photons(mass, alpha, gf,
        fermions=[{'mass': 170.0, 'charge': 2/3, 'n_colour': 3}],
        w_boson={'mass': 170.0, 'kappa': kappa}) == pytest.approx(
            scalar_vector_sum(mass, 0, g_aa, 0), rel=1e-10)
    assert rl.width_scalar_to_gluons(mass, alpha_s, gf, quarks=[{'mass': 170.0}]) == pytest.approx(
        scalar_vector_sum(mass, 0, g_gg, 0, colour=8), rel=1e-10)
