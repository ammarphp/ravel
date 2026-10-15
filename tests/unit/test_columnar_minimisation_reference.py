"""Independent lab-frame numerical controls; no product helpers in the references.

MT2W: absolute 0.03 GeV plus relative 2e-4. Topness minimum: absolute
1e-8 plus relative 2e-5; ln(min S) is checked with a declared 1e-8 floor
and absolute 2e-3. Each population has 2,000 fixed-seed random configurations.
The floor avoids assigning significance to numerical noise at exact zero.
"""
import inspect

import numpy as np
import pytest
from scipy.optimize import minimize

from ravel.physics.columnar import mt2 as product


def configurations(n=2000):
    rng = np.random.default_rng(14285)
    def vector(low, high, mass):
        pt = rng.uniform(low, high, n)
        eta, phi = rng.uniform(-1.5, 1.5, n), rng.uniform(-np.pi, np.pi, n)
        xyz = np.column_stack((pt * np.cos(phi), pt * np.sin(phi), pt * np.sinh(eta)))
        return np.column_stack((xyz, np.sqrt((xyz ** 2).sum(1) + np.asarray(mass) ** 2)))
    lep = vector(20, 350, 0.105)
    b1 = vector(100, 400, 5.0)
    b2 = vector(20, 100, rng.uniform(5, 30, n))
    met = rng.normal(0, 250, (n, 2))
    met[::10] = 0                         # zero MET
    # Transversely collinear objects, with distinct rapidities and physical masses.
    for i in range(1, n, 10):
        direction = lep[i, :2] / np.linalg.norm(lep[i, :2])
        b1[i, :2] = direction * np.linalg.norm(b1[i, :2])
        b1[i, 3] = np.sqrt(b1[i, :3] @ b1[i, :3] + 25)
    for i in range(2, n, 10):             # heavy other-side candidate: one-sided floor
        b2[i, 3] = np.sqrt(b2[i, :3] @ b2[i, :3] + 210 ** 2)
    b1[3::10], b2[3::10] = b2[3::10].copy(), b1[3::10].copy()  # assignment ambiguity
    # Construct a known W-shell neutrino witness independently in the laboratory.
    # Rescale the other candidate only when necessary to admit this witness, so
    # a numerical failure cannot be mistaken for proof of an infeasible event.
    phi = np.arctan2(lep[:, 1], lep[:, 0]) + np.pi
    etl = np.sqrt(lep[:, 3] ** 2 - lep[:, 2] ** 2)
    rapidity = np.arctanh(lep[:, 2] / lep[:, 3])
    pt = (80.4 ** 2 - .105 ** 2) / (2 * (etl + np.linalg.norm(lep[:, :2], axis=1)))
    nu = np.column_stack((pt * np.cos(phi), pt * np.sin(phi), pt * np.sinh(rapidity), pt * np.cosh(rapidity)))
    total = lep + b1 + nu
    first = total[:, 3] ** 2 - (total[:, :3] ** 2).sum(1)
    q = met - nu[:, :2]
    for _ in range(30):
        mb2 = np.maximum(b2[:, 3] ** 2 - (b2[:, :3] ** 2).sum(1), 0)
        other = mb2 + 80.4 ** 2 + 2 * (np.sqrt(mb2 + (b2[:, :2] ** 2).sum(1))
                 * np.sqrt(80.4 ** 2 + (q ** 2).sum(1)) - (b2[:, :2] * q).sum(1))
        bad = other >= first
        if not bad.any():
            break
        b2[bad] *= .8
    assert np.all(other < first)
    return lep, b1, b2, met


def reference_mt2w(lep, b1, b2, met, mw=80.4):
    """Constrained minimisation on the lab-frame on-shell W surface.

    Parameterise the massless neutrino by azimuth and rapidity relative to
    the lepton. Its pT follows directly from (l+nu)^2=mW^2. Minimise
    (l+b1+nu)^2 subject to it being >= mT(b2, W)^2. This uses neither the
    product's lb-rest-frame circle nor its feasibility-window bisection.
    """
    ml2 = max(0., lep[3] ** 2 - lep[:3] @ lep[:3])
    mb2 = max(0., b2[3] ** 2 - b2[:3] @ b2[:3])
    etl = np.sqrt(lep[3] ** 2 - lep[2] ** 2)
    yl = np.arctanh(lep[2] / lep[3])
    etb = np.sqrt(mb2 + b2[:2] @ b2[:2])
    scale = max(100., np.linalg.norm(met), np.linalg.norm(b1[:2]))
    def sides(x):
        phi, delta = np.asarray(x)[..., 0], np.asarray(x)[..., 1]
        cs, sn = np.cos(phi), np.sin(phi)
        den = 2 * (etl * np.cosh(delta) - lep[0] * cs - lep[1] * sn)
        pt = (mw ** 2 - ml2) / np.maximum(den, 1e-12)
        nu = np.stack((pt * cs, pt * sn, pt * np.sinh(yl + delta), pt * np.cosh(yl + delta)), axis=-1)
        top = lep + b1 + nu
        first = top[..., 3] ** 2 - (top[..., :3] ** 2).sum(-1)
        q = met - nu[..., :2]
        other = mb2 + mw ** 2 + 2 * (etb * np.sqrt(mw ** 2 + (q * q).sum(-1)) - (b2[:2] * q).sum(-1))
        return first / scale ** 2, (first - other) / scale ** 2
    phi, delta = np.meshgrid(np.linspace(-np.pi, np.pi, 49), np.linspace(-8, 8, 49))
    grid = np.column_stack((phi.ravel(), delta.ravel()))
    first, margin = sides(grid)
    # Start from both feasible minima and least-infeasible grid points, spread in rapidity.
    starts = []
    for sign in (-1, 1):
        half = grid[:, 1] * sign >= 0
        for score in (np.where((margin >= 0) & half, first, np.inf),
                      np.where(half, np.maximum(-margin, 0) + first * 1e-3, np.inf)):
            starts.append(grid[np.argmin(score)])
    candidates = [float(np.min(first[margin >= 0]))] if (margin >= 0).any() else []
    for start in starts:
        result = minimize(lambda x: sides(x)[0], start, method='SLSQP',
                          constraints=[{'type': 'ineq', 'fun': lambda x: sides(x)[1]}],
                          bounds=[(-3 * np.pi, 3 * np.pi), (-16, 16)],
                          options={'ftol': 1e-11, 'maxiter': 300})
        value, gap = sides(result.x)
        if result.success and gap >= -1e-8:
            candidates.append(float(value))
    assert candidates, 'independent reference could not establish a feasible solution'
    return np.sqrt(max(0., min(candidates))) * scale


def reference_topness(lep, b, met, mw=80.4, mt=173., sw=5., st=15.):
    """Profile longitudinal momenta by their invariant-mass ranges, then grid + Powell.

    For each transverse split either longitudinal root can set an invariant mass
    to its target when mT is below target; otherwise the residual starts at mT.
    """
    ml2 = max(0., lep[3] ** 2 - lep[:3] @ lep[:3])
    mb2 = max(0., b[3] ** 2 - b[:3] @ b[:3])
    etl, etb = np.sqrt(lep[3] ** 2 - lep[2] ** 2), np.sqrt(b[3] ** 2 - b[2] ** 2)
    scale = max(100., np.linalg.norm(met), np.linalg.norm(lep[:2]), np.linalg.norm(b[:2]))
    def objective(x):
        nu = np.asarray(x) * scale
        w = met - nu
        a = ml2 + 2 * (etl * np.linalg.norm(nu, axis=-1) - (lep[:2] * nu).sum(-1))
        c = mb2 + mw ** 2 + 2 * (etb * np.sqrt(mw ** 2 + (w * w).sum(-1)) - (b[:2] * w).sum(-1))
        return np.maximum(a - mw ** 2, 0) ** 2 / sw ** 4 + np.maximum(c - mt ** 2, 0) ** 2 / st ** 4
    gx, gy = np.meshgrid(np.linspace(-4, 4, 41), np.linspace(-4, 4, 41))
    grid = np.column_stack((gx.ravel(), gy.ravel()))
    start = grid[np.argmin(objective(grid))]
    starts = [start, met / scale / 2, met / scale, -met / scale]
    values = [float(minimize(objective, x, method='Powell',
                           options={'xtol': 1e-10, 'ftol': 1e-12, 'maxiter': 500}).fun) for x in starts]
    return min(values)


def assert_mt2w(actual, expected):
    np.testing.assert_allclose(actual, expected, atol=0.03, rtol=2e-4)


def assert_topness(actual, expected):
    np.testing.assert_allclose(actual, expected, atol=1e-8, rtol=2e-5)


@pytest.mark.parametrize('batch', range(20))
def test_mt2w_independent_random_population(batch):
    arrays = [x[batch * 100:(batch + 1) * 100] for x in configurations()]
    expected = np.array([reference_mt2w(*row) for row in zip(*arrays)])
    assert_mt2w(product.mt2w(*arrays, w_mass=80.4), expected)


@pytest.mark.parametrize('batch', range(20))
def test_topness_independent_random_population(batch):
    lep, _, b, met = [x[batch * 100:(batch + 1) * 100] for x in configurations()]
    expected = np.array([reference_topness(*row) for row in zip(lep, b, met)])
    kwargs = dict(m_w=80.4, m_top=173., sigma_w=5., sigma_top=15.)
    assert_topness(product.topness_minimum(lep, b, met, **kwargs), expected)
    np.testing.assert_allclose(product.modified_topness(lep, b, met, floor=1e-8, **kwargs),
                               np.log(np.maximum(expected, 1e-8)), atol=2e-3, rtol=0)


def test_reference_catches_planted_wrong_w_mass_in_other_branch():
    source = inspect.getsource(product.mt2w)
    changed = source.replace('np.sqrt(w2 + qx * qx + qy * qy)', 'np.sqrt(1.5 * w2 + qx * qx + qy * qy)')
    assert changed != source
    namespace = dict(product.__dict__)
    exec(compile(changed, '<mutated mt2w>', 'exec'), namespace)
    arrays = [x[:8] for x in configurations()]
    expected = [reference_mt2w(*row) for row in zip(*arrays)]
    with pytest.raises(AssertionError):
        assert_mt2w(namespace['mt2w'](*arrays, w_mass=80.4), expected)


def test_reference_catches_planted_wrong_top_mass_resolution():
    source = inspect.getsource(product.topness_minimum)
    changed = source.replace('float(sigma_top) ** 4', '(2 * float(sigma_top)) ** 4')
    assert changed != source
    namespace = dict(product.__dict__)
    exec(compile(changed, '<mutated topness>', 'exec'), namespace)
    exec(compile(inspect.getsource(product.modified_topness), '<copied modified_topness>', 'exec'), namespace)
    lep, _, b, met = [x[:8] for x in configurations()]
    expected = np.log(np.maximum([reference_topness(*row) for row in zip(lep, b, met)], 1e-8))
    with pytest.raises(AssertionError):
        np.testing.assert_allclose(namespace['modified_topness'](lep, b, met, m_w=80.4, m_top=173.,
                                    sigma_w=5., sigma_top=15., floor=1e-8), expected, atol=2e-3, rtol=0)


def test_fully_collinear_objects_with_zero_met():
    rng = np.random.default_rng(828)
    pt, eta = rng.uniform(30, 120, 16), rng.uniform(-1, 1, 16)
    xyz = np.column_stack((pt, np.zeros(16), pt * np.sinh(eta)))
    lep = np.column_stack((xyz, np.sqrt((xyz ** 2).sum(1) + .105 ** 2)))
    bxyz = xyz * rng.uniform(.5, 3, 16)[:, None]
    b1 = np.column_stack((bxyz, np.sqrt((bxyz ** 2).sum(1) + 25)))
    b2 = np.tile([0., 0., 0., 5.], (16, 1))
    met = np.zeros((16, 2))
    expected = [reference_mt2w(*row) for row in zip(lep, b1, b2, met)]
    assert_mt2w(product.mt2w(lep, b1, b2, met, w_mass=80.4), expected)


def test_one_sided_topness_has_an_analytic_minimum():
    lep = np.array([[50., 0., 0., 50.]])
    b = np.array([[0., 0., 0., 210.]])
    met = np.zeros((1, 2))
    expected = (((210 + 80.4) ** 2 - 173. ** 2) / 15. ** 2) ** 2
    assert reference_topness(lep[0], b[0], met[0]) == pytest.approx(expected, rel=1e-10)
    assert_topness(product.topness_minimum(lep, b, met, m_w=80.4, m_top=173., sigma_w=5., sigma_top=15.), [expected])


def test_observable_candidate_assignment_minima_use_independent_references(tmp_path):
    from test_columnar_inputs import write_delphes
    from ravel.physics.columnar import engine, formats
    from ravel.physics.columnar.recipe import compile_recipe
    rng = np.random.default_rng(951)
    pts = rng.uniform(30, 100, 12).astype('f4')
    jets = rng.uniform(80, 220, (12, 2)).astype('f4')
    events, expected_w, expected_t = [], [], []
    for pt, bs in zip(pts, jets):
        pt, bs = float(pt), [float(b) for b in bs]
        # Exactly opposite in phi to the lepton; both assignments are admissible.
        phi = float(np.float32(np.pi))
        events.append({'MET': 0., 'METPhi': 0., 'Weight': 1.,
                       'Electron': [{'PT': float(pt), 'Eta': 0., 'Phi': 0., 'Charge': -1}],
                       'Jet': [{'PT': float(b), 'Eta': 0., 'Phi': phi, 'Mass': 5., 'BTag': 1} for b in bs]})
        lep = np.array([pt, 0., 0., np.hypot(pt, .00051099895)])
        candidates = [np.array([b * np.cos(phi), b * np.sin(phi), 0., np.hypot(b, 5.)]) for b in bs]
        expected_w.append(min(reference_mt2w(lep, candidates[0], candidates[1], np.zeros(2)),
                              reference_mt2w(lep, candidates[1], candidates[0], np.zeros(2))))
        expected_t.append(np.log(max(1e-8, min(reference_topness(lep, b, np.zeros(2)) for b in candidates))))
    doc = {'schema_version': 1, 'kind': 'columnar-analysis-recipe', 'name': 'synthetic candidate assignments',
           'weights': {'generator': 'weight', 'factors': []},
           'objects': [{'name': 'leptons', 'from': 'Electron'}, {'name': 'candidates', 'from': 'Jet'}],
           'observables': [{'name': 'w', 'op': 'mt2w', 'lepton': 'leptons[0]', 'candidates': 'candidates',
                            'max_objects': 2, 'w_mass': 80.4, 'source': 'synthetic observable definition'},
                           {'name': 't', 'op': 'modified_topness', 'lepton': 'leptons[0]', 'candidates': 'candidates',
                            'max_objects': 2, 'w_mass': 80.4, 'top_mass': 173., 'w_resolution': 5.,
                            'top_resolution': 15., 'floor': 1e-8, 'source': 'synthetic observable definition'}],
           'regions': [{'name': 'all', 'cuts': []}], 'histograms': [],
           'event_record': {'max_events': 12, 'observables': ['w', 't']}}
    path = tmp_path / 'events.root'
    write_delphes(path, events)
    plan = compile_recipe(doc, formats.load_descriptor('delphes'), tmp_path)
    records = engine.analyse({'inputs': [{'path': str(path)}], 'chunk_size': 12}, plan)['event_record']
    assert_mt2w([r['w'] for r in records], expected_w)
    np.testing.assert_allclose([r['t'] for r in records], expected_t, atol=2e-3, rtol=0)
