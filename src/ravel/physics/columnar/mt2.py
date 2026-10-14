"""Vectorised MT2, MT2W and modified topness.

``mt2`` is the bisection of Lester and Nachman (arXiv:1411.4312) for asymmetric
invisible masses, evaluated for all events at once. Its ellipse-disjointness test is
the same as the per-event reference in ``ravel.physics.sa_native_core`` and the tests
compare the two.

``mt2w`` follows the definition of Bai, Cheng, Gallicchio and Gu (arXiv:1203.4813): the
smallest common top-candidate mass m_y for which the lepton-side neutrino (massless,
with the lepton forming an on-shell W) and the other-side invisible W (on shell)
can share the measured missing transverse momentum. For a trial m_y the lepton-side
neutrino lies on a circle in the rest frame of the lepton plus its b jet; the other
side is feasible when the transverse mass of the second b jet with the remaining
missing momentum does not exceed m_y. m_y is bisected.

``modified_topness`` is ln(min S) with
S = (m_W^2 - (p_nu + p_l)^2)^2 / a_W^4 + (m_t^2 - (p_b + p_W)^2)^2 / a_t^4,
p_T(nu) + p_T(W) = missing p_T, the neutrino massless and the W on shell. The
longitudinal momenta are profiled analytically, which leaves a convex function of
p_T(nu) that is minimised by damped Newton iterations.

Every mass and width parameter is supplied by the caller; nothing is assumed here.
"""
import numpy as np

from .kinematics import minkowski


# ---------------------------------------------------------------- MT2
def _ellipse(m_sq, mt_sq, tx, ty, mq_sq, pxmiss, pymiss):
    tx2, ty2 = tx * tx, ty * ty
    c_xx = 4.0 * mt_sq + 4.0 * ty2
    c_yy = 4.0 * mt_sq + 4.0 * tx2
    c_xy = -4.0 * tx * ty
    c_x = (-4.0 * mt_sq * pxmiss - 2.0 * mq_sq * tx + 2.0 * m_sq * tx - 2.0 * mt_sq * tx
           + 4.0 * pymiss * tx * ty - 4.0 * pxmiss * ty2)
    c_y = (-4.0 * mt_sq * pymiss - 4.0 * pymiss * tx2 - 2.0 * mq_sq * ty + 2.0 * m_sq * ty
           - 2.0 * mt_sq * ty + 4.0 * pxmiss * tx * ty)
    c = (-mq_sq * mq_sq + 2 * mq_sq * m_sq - m_sq * m_sq + 2 * mq_sq * mt_sq + 2 * m_sq * mt_sq - mt_sq * mt_sq
         + 4.0 * mt_sq * pxmiss ** 2 + 4.0 * mt_sq * pymiss ** 2 + 4.0 * mq_sq * pxmiss * tx
         - 4.0 * m_sq * pxmiss * tx + 4.0 * mt_sq * pxmiss * tx + 4.0 * mq_sq * tx2
         + 4.0 * pymiss ** 2 * tx2 + 4.0 * mq_sq * pymiss * ty - 4.0 * m_sq * pymiss * ty
         + 4.0 * mt_sq * pymiss * ty - 8.0 * pxmiss * pymiss * tx * ty + 4.0 * mq_sq * ty2
         + 4.0 * pxmiss ** 2 * ty2)
    det = 2.0 * c_x * c_xy * c_y + c * c_xx * c_yy - c_yy * c_x * c_x - c * c_xy * c_xy - c_xx * c_y * c_y
    return (c_xx, c_yy, c_xy, c_x, c_y, c, det)


def _lester_factor(e1, e2):
    a_xx, a_yy, a_xy, a_x, a_y, a, _ = e1
    b_xx, b_yy, b_xy, b_x, b_y, b, _ = e2
    return (a_xx * a_yy * b + 2.0 * a_xy * a_y * b_x - 2.0 * a_x * a_yy * b_x + a * a_yy * b_xx
            - 2.0 * a * a_xy * b_xy + 2.0 * a_x * a_y * b_xy + 2.0 * a_x * a_xy * b_y - 2.0 * a_xx * a_y * b_y
            + a * a_xx * b_yy - b_yy * a_x ** 2 - b * a_xy ** 2 - b_xx * a_y ** 2)


def _disjoint(e1, e2):
    """(disjoint, singular) for arrays of ellipse pairs."""
    equal = np.ones(np.shape(e1[0]), bool)
    for x, y in zip(e1[:6], e2[:6]):
        equal &= x == y
    c3, c2, c1, c0 = e1[6], _lester_factor(e1, e2), _lester_factor(e2, e1), e2[6]
    swap = np.abs(c3) < np.abs(c0)
    k3, k2, k1, k0 = (np.where(swap, c0, c3), np.where(swap, c1, c2), np.where(swap, c2, c1), np.where(swap, c3, c0))
    singular = (k3 == 0) & ~equal
    with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
        a, b, c = k2 / k3, k1 / k3, k0 / k3
        thing1 = -3.0 * b + a * a
        thing2 = -27.0 * c * c + 18.0 * c * a * b + a * a * b * b - 4.0 * a * a * a * c - 4.0 * b * b * b
        result = (thing1 > 0) & (thing2 > 0) & (((a >= 0) & (3.0 * a * c + b * a * a - 4.0 * b * b < 0)) | (a < 0))
    return result & ~equal & ~singular, singular


def mt2(m_vis_a, px_a, py_a, m_vis_b, px_b, py_b, px_miss, py_miss, m_inv_a, m_inv_b,
        *, rel_precision=1e-10, max_iterations=400):
    """MT2 for every event; NaN where the bracketing fails or an input is not finite."""
    args = [np.asarray(x, float) for x in (m_vis_a, px_a, py_a, m_vis_b, px_b, py_b, px_miss, py_miss, m_inv_a, m_inv_b)]
    args = np.broadcast_arrays(*args)
    ma, pxa, pya, mb, pxb, pyb, pxm, pym, ca, cb = [a.copy() for a in args]
    swap = ma + ca > mb + cb
    for x, y in ((ma, mb), (pxa, pxb), (pya, pyb), (ca, cb)):
        x[swap], y[swap] = y[swap], x[swap].copy()
    n = ma.shape
    out = np.full(n, np.nan)
    finite = np.all([np.isfinite(a) for a in (ma, pxa, pya, mb, pxb, pyb, pxm, pym, ca, cb)], axis=0)
    m_min = mb + cb
    ms_sq, mt_sq, mp_sq, mq_sq = ma * ma, mb * mb, ca * ca, cb * cb
    scale_sq = (ms_sq + mt_sq + mp_sq + mq_sq + pxa ** 2 + pya ** 2 + pxb ** 2 + pyb ** 2 + pxm ** 2 + pym ** 2) / 8.0
    zero = finite & (scale_sq == 0)
    out[zero] = 0.0
    live = finite & ~zero
    lower = m_min.copy()
    upper = m_min + np.sqrt(np.where(live, scale_sq, 0.0))

    def test(trial, idx):
        s1 = _ellipse(trial[idx] ** 2, ms_sq[idx], -pxa[idx], -pya[idx], mp_sq[idx], 0.0, 0.0)
        s2 = _ellipse(trial[idx] ** 2, mt_sq[idx], pxb[idx], pyb[idx], mq_sq[idx], pxm[idx], pym[idx])
        return _disjoint(s1, s2)

    # Expand the upper bound until the ellipses intersect.
    pending = np.flatnonzero(live)
    for _ in range(200):
        if not pending.size:
            break
        disjoint, singular = test(upper, pending)
        live[pending[singular]] = False
        grow = pending[disjoint & ~singular]
        upper[grow] *= 2.0
        pending = grow
    live[pending] = False                      # never bracketed: undefined

    go_low = np.ones(n, bool)
    pending = np.flatnonzero(live)
    for _ in range(max_iterations):
        if not pending.size:
            break
        lo, hi = lower[pending], upper[pending]
        trial = np.where(go_low[pending], (lo * 15.0 + hi) / 16.0, (lo + hi) / 2.0)
        exhausted = (trial <= lo) | (trial >= hi)
        out[pending[exhausted]] = trial[exhausted]
        converged = ~exhausted & ((hi - lo) <= rel_precision * hi)
        out[pending[converged]] = (lo[converged] + hi[converged]) / 2.0
        keep = ~exhausted & ~converged
        pending, trial = pending[keep], trial[keep]
        if not pending.size:
            break
        holder = np.empty(n); holder[pending] = trial
        disjoint, singular = test(holder, pending)
        out[pending[singular]] = lower[pending[singular]]
        up = pending[disjoint & ~singular]
        lower[up] = holder[up]; go_low[up] = False
        down = pending[~disjoint & ~singular]
        upper[down] = holder[down]
        pending = pending[~singular]
    unresolved = pending
    out[unresolved] = (lower[unresolved] + upper[unresolved]) / 2.0
    return out


# ---------------------------------------------------------------- MT2W
def _boost(v, beta):
    """Boost (..., 4) vectors by velocity beta (..., 3) (active boost)."""
    b2 = (beta ** 2).sum(axis=-1)
    gamma = 1.0 / np.sqrt(1.0 - b2)
    bp = (beta * v[..., :3]).sum(axis=-1)
    with np.errstate(invalid='ignore', divide='ignore'):
        g2 = np.where(b2 > 0, (gamma - 1.0) / np.where(b2 > 0, b2, 1.0), 0.0)
    space = v[..., :3] + (g2 * bp)[..., None] * beta + (gamma * v[..., 3])[..., None] * beta
    return np.concatenate([space, (gamma * (v[..., 3] + bp))[..., None]], axis=-1)


def _orthonormal(a):
    """Two unit vectors orthogonal to each unit vector in a (n, 3)."""
    trial = np.where(np.abs(a[:, :1]) < 0.9, np.array([[1.0, 0.0, 0.0]]), np.array([[0.0, 1.0, 0.0]]))
    u = np.cross(a, trial)
    u /= np.linalg.norm(u, axis=1, keepdims=True)
    v = np.cross(a, u)
    return u, v


def mt2w(lepton, b_lepton_side, b_other_side, met, *, w_mass, samples=72, rel_precision=1e-7,
         scan_ratio=1.03, search_ceiling=20000.0):
    """MT2W for one lepton-side and one other-side b candidate per event (GeV).

    The feasible top-candidate masses form a window: very large m_y push the lepton-side
    neutrino along the lepton and the other side becomes infeasible again. The window is
    located on a geometric grid (ratio ``scan_ratio``) of the feasibility margin
    min_t [m_T(other side) - m_y], refined around its minimum, and its lower edge is
    bisected. Events without a feasible m_y below ``search_ceiling`` are NaN.
    """
    lep, b1, b2 = (np.asarray(x, float).reshape(-1, 4) for x in (lepton, b_lepton_side, b_other_side))
    met = np.asarray(met, float).reshape(-1, 2)
    n = len(lep)
    out = np.full(n, np.nan)
    ok = np.isfinite(lep).all(1) & np.isfinite(b1).all(1) & np.isfinite(b2).all(1) & np.isfinite(met).all(1)
    idx = np.flatnonzero(ok)
    if not idx.size:
        return out
    lep, b1, b2, met = lep[idx], b1[idx], b2[idx], met[idx]
    w2 = float(w_mass) ** 2
    a_const = (w2 - np.maximum(minkowski(lep), 0.0)) / 2.0
    system = lep + b1
    m_lb = np.sqrt(np.maximum(minkowski(system), 0.0))
    m_b1 = np.sqrt(np.maximum(minkowski(b1), 0.0))
    m_b2sq = np.maximum(minkowski(b2), 0.0)
    et_b2 = np.sqrt(m_b2sq + b2[:, 0] ** 2 + b2[:, 1] ** 2)
    beta = system[:, :3] / system[:, 3:4]
    rest = _boost(lep, -beta)
    a0 = rest[:, 3]
    a_norm = np.linalg.norm(rest[:, :3], axis=1)
    a_hat = rest[:, :3] / a_norm[:, None]
    u, v = _orthonormal(a_hat)
    angles = np.linspace(0.0, 2 * np.pi, samples, endpoint=False)
    ratio = (np.sqrt(5.0) - 1.0) / 2.0

    # The boost to the laboratory is linear, so the neutrino transverse momentum on the
    # rest-frame circle is E* (c0 + cos(theta) ca + sin(theta) (cos t cu + sin t cv)).
    b2_beta = (beta ** 2).sum(1)
    gamma = 1.0 / np.sqrt(1.0 - b2_beta)
    with np.errstate(invalid='ignore', divide='ignore'):
        g2 = np.where(b2_beta > 0, (gamma - 1.0) / np.where(b2_beta > 0, b2_beta, 1.0), 0.0)

    def transverse(w):
        return w[:, :2] + (g2 * (beta * w).sum(1))[:, None] * beta[:, :2]
    c0 = gamma[:, None] * beta[:, :2]
    ca, cu, cv = transverse(a_hat), transverse(u), transverse(v)

    def side2(t, sel, e_star, cos_t, sin_t):
        """Other-side transverse mass for neutrino azimuth t (shape (m, k))."""
        cos, sin = np.cos(t), np.sin(t)
        es, ct, st = e_star[:, None], cos_t[:, None], sin_t[:, None]
        px = es * (c0[sel, 0:1] + ct * ca[sel, 0:1] + st * (cos * cu[sel, 0:1] + sin * cv[sel, 0:1]))
        py = es * (c0[sel, 1:2] + ct * ca[sel, 1:2] + st * (cos * cu[sel, 1:2] + sin * cv[sel, 1:2]))
        qx = met[sel, 0:1] - px
        qy = met[sel, 1:2] - py
        mt_sq = m_b2sq[sel][:, None] + w2 + 2.0 * (et_b2[sel][:, None] * np.sqrt(w2 + qx * qx + qy * qy)
                                                    - b2[sel, 0:1] * qx - b2[sel, 1:2] * qy)
        return np.sqrt(np.maximum(mt_sq, 0.0))

    def margin(m_y, sel, refine=True):
        """min over the lepton-side circle of m_T(other side) - m_y; +inf where the circle is empty.

        Without refinement the minimum over the sampled azimuths is returned; it can only
        overestimate the true margin, so a non-positive coarse margin is always feasible.
        """
        result = np.full(len(sel), np.inf)
        b_const = (m_y * m_y - m_lb[sel] ** 2) / 2.0
        with np.errstate(invalid='ignore', divide='ignore'):
            e_star = b_const / m_lb[sel]
            cos_t = (a0[sel] - a_const[sel] / e_star) / a_norm[sel]
        good = (m_lb[sel] > 0) & (e_star > 0) & (np.abs(cos_t) <= 1.0)
        if not good.any():
            return result
        g = sel[good]
        ct, st, es = cos_t[good], np.sqrt(1.0 - cos_t[good] ** 2), e_star[good]
        values = side2(np.broadcast_to(angles, (len(g), samples)), g, es, ct, st)
        k = np.argmin(values, axis=1)
        best = values[np.arange(len(g)), k]
        if not refine:
            result[good] = best - m_y[good]
            return result
        step = 2 * np.pi / samples
        lo, hi = angles[k] - step, angles[k] + step
        x1, x2 = hi - ratio * (hi - lo), lo + ratio * (hi - lo)
        f1 = side2(x1[:, None], g, es, ct, st)[:, 0]
        f2 = side2(x2[:, None], g, es, ct, st)[:, 0]
        for _ in range(28):
            left = f1 < f2
            lo, hi = np.where(left, lo, x1), np.where(left, x2, hi)
            x1, x2, f1, f2 = (np.where(left, hi - ratio * (hi - lo), x2), np.where(left, x1, lo + ratio * (hi - lo)),
                              np.where(left, np.nan, f2), np.where(left, f1, np.nan))
            fill1, fill2 = np.isnan(f1), np.isnan(f2)
            if fill1.any():
                f1[fill1] = side2(x1[fill1][:, None], g[fill1], es[fill1], ct[fill1], st[fill1])[:, 0]
            if fill2.any():
                f2[fill2] = side2(x2[fill2][:, None], g[fill2], es[fill2], ct[fill2], st[fill2])[:, 0]
        result[good] = np.minimum(best, np.minimum(f1, f2)) - m_y[good]
        return result

    m = len(idx)
    floor = np.maximum.reduce([m_lb, w_mass + m_b1, w_mass + np.sqrt(m_b2sq)]) * (1.0 + 1e-12) + 1e-12
    result = np.full(m, np.nan)
    below = np.full(m, np.nan)           # largest scanned infeasible mass under the feasible point
    above = np.full(m, np.nan)           # a feasible mass
    best_m = floor.copy(); best_margin = np.full(m, np.inf)
    previous = np.full(m, np.nan)
    pending = np.arange(m)
    trial = floor.copy()
    first = margin(floor, pending)
    result[first <= 0] = floor[first <= 0]
    best_margin = np.where(first <= 0, best_margin, first)
    pending = pending[first > 0]
    previous[pending] = floor[pending]
    while pending.size:
        trial[pending] = trial[pending] * scan_ratio
        pending = pending[trial[pending] <= search_ceiling]
        if not pending.size:
            break
        value = margin(trial[pending], pending, refine=False)
        better = value < best_margin[pending]
        best_margin[pending[better]] = value[better]; best_m[pending[better]] = trial[pending[better]]
        hit = value <= 0
        above[pending[hit]] = trial[pending[hit]]
        below[pending[hit]] = previous[pending[hit]]
        previous[pending] = trial[pending]
        pending = pending[~hit]
    # A narrow window between grid points: refine the margin around its smallest value.
    missing = np.flatnonzero(np.isnan(result) & np.isnan(above) & np.isfinite(best_margin))
    if missing.size:
        lo = np.maximum(best_m[missing] / scan_ratio, floor[missing]); hi = best_m[missing] * scan_ratio
        x1, x2 = hi - ratio * (hi - lo), lo + ratio * (hi - lo)
        f1, f2 = margin(x1, missing), margin(x2, missing)
        for _ in range(60):
            left = f1 < f2
            lo, hi = np.where(left, lo, x1), np.where(left, x2, hi)
            x1, x2 = np.where(left, hi - ratio * (hi - lo), x2), np.where(left, x1, lo + ratio * (hi - lo))
            f1, f2 = np.where(left, margin(x1, missing), f2), np.where(left, f1, margin(x2, missing))
            hit = (f1 <= 0) | (f2 <= 0)
            if hit.all():
                break
        point = np.where(f1 <= f2, x1, x2)
        found = np.minimum(f1, f2) <= 0
        above[missing[found]] = point[found]
        below[missing[found]] = np.maximum(best_m[missing[found]] / scan_ratio, floor[missing[found]])
    # The coarse scan may report an infeasible lower grid point that is in fact feasible;
    # step down with the refined margin until the lower bracket is genuinely infeasible.
    rows = np.flatnonzero(np.isnan(result) & np.isfinite(above))
    check = rows
    for _ in range(400):
        if not check.size:
            break
        fine = margin(below[check], check) <= 0
        moved = check[fine]
        above[moved] = below[moved]
        below[moved] = np.maximum(below[moved] / scan_ratio, floor[moved])
        at_floor = moved[below[moved] <= floor[moved]]
        if at_floor.size:
            ok_floor = margin(floor[at_floor], at_floor) <= 0
            result[at_floor[ok_floor]] = floor[at_floor[ok_floor]]
            moved = np.setdiff1d(moved, at_floor[ok_floor])
        check = moved
    rows = rows[np.isnan(result[rows])]
    lo, hi = below[rows], above[rows]
    for _ in range(200):
        active = (hi - lo) > rel_precision * hi
        if not active.any():
            break
        sub = np.flatnonzero(active)
        mid = (lo[sub] + hi[sub]) / 2.0
        feasible = margin(mid, rows[sub]) <= 0
        hi[sub[feasible]] = mid[feasible]
        lo[sub[~feasible]] = mid[~feasible]
    result[rows] = hi
    out[idx] = result
    return out


# ---------------------------------------------------------------- modified topness
def _topness_terms(x, lep_pt, et_l, ml2, b_pt, et_b, mb2, met, w2, t2, inv_w4, inv_t4, need_hessian):
    r = np.maximum(np.hypot(x[:, 0], x[:, 1]), 1e-12)
    u = ml2 + 2.0 * (et_l * r - (lep_pt * x).sum(1)) - w2
    q = met - x
    s = np.sqrt(w2 + (q * q).sum(1))
    v = mb2 + w2 + 2.0 * (et_b * s - (b_pt * q).sum(1)) - t2
    up, vp = np.maximum(u, 0.0), np.maximum(v, 0.0)
    value = up * up * inv_w4 + vp * vp * inv_t4
    if not need_hessian:
        return value, None, None
    gu = 2.0 * (et_l[:, None] * x / r[:, None] - lep_pt)
    gv = -2.0 * (et_b[:, None] * q / s[:, None] - b_pt)
    grad = 2.0 * up[:, None] * gu * inv_w4 + 2.0 * vp[:, None] * gv * inv_t4
    eye = np.eye(2)[None]
    hu = 2.0 * et_l[:, None, None] * (eye / r[:, None, None] - np.einsum('ni,nj->nij', x, x) / r[:, None, None] ** 3)
    hv = 2.0 * et_b[:, None, None] * (eye / s[:, None, None] - np.einsum('ni,nj->nij', q, q) / s[:, None, None] ** 3)
    hess = (2.0 * inv_w4 * (u > 0)[:, None, None] * (np.einsum('ni,nj->nij', gu, gu) + up[:, None, None] * hu)
            + 2.0 * inv_t4 * (v > 0)[:, None, None] * (np.einsum('ni,nj->nij', gv, gv) + vp[:, None, None] * hv))
    return value, grad, hess


def topness_minimum(lepton, b, met, *, m_w, m_top, sigma_w, sigma_top, iterations=200):
    """min S for each event (see module docstring); NaN for non-finite inputs."""
    lep = np.asarray(lepton, float).reshape(-1, 4)
    b = np.asarray(b, float).reshape(-1, 4)
    met = np.asarray(met, float).reshape(-1, 2)
    n = len(lep)
    out = np.full(n, np.nan)
    ok = np.isfinite(lep).all(1) & np.isfinite(b).all(1) & np.isfinite(met).all(1)
    idx = np.flatnonzero(ok)
    if not idx.size:
        return out
    lep, b, met = lep[idx], b[idx], met[idx]
    ml2 = np.maximum(minkowski(lep), 0.0); mb2 = np.maximum(minkowski(b), 0.0)
    lep_pt, b_pt = lep[:, :2], b[:, :2]
    et_l = np.sqrt(ml2 + (lep_pt ** 2).sum(1)); et_b = np.sqrt(mb2 + (b_pt ** 2).sum(1))
    w2, t2 = float(m_w) ** 2, float(m_top) ** 2
    inv_w4, inv_t4 = 1.0 / float(sigma_w) ** 4, 1.0 / float(sigma_top) ** 4
    per_event = (lep_pt, et_l, ml2, b_pt, et_b, mb2, met)
    constants = (w2, t2, inv_w4, inv_t4)

    def evaluate(x, rows, need_hessian):
        return _topness_terms(x, *(a[rows] for a in per_event), *constants, need_hessian)
    met_norm = np.hypot(met[:, 0], met[:, 1])[:, None]
    lep_dir = lep_pt / np.maximum(np.hypot(lep_pt[:, 0], lep_pt[:, 1]), 1e-12)[:, None]
    starts = [0.5 * met + 1e-3, 0.9 * met + 1e-3, lep_dir * (0.5 * met_norm + 1.0)]
    best = np.full(len(idx), np.inf)
    for x in starts:
        x = x.copy()
        value, grad, hess = evaluate(x, slice(None), True)
        active = value > 0
        for _ in range(iterations):
            if not active.any():
                break
            a = np.flatnonzero(active)
            h = hess[a]
            ridge = 1e-10 * (np.abs(h[:, 0, 0]) + np.abs(h[:, 1, 1])) + 1e-300
            h = h + ridge[:, None, None] * np.eye(2)[None]
            det = h[:, 0, 0] * h[:, 1, 1] - h[:, 0, 1] * h[:, 1, 0]
            g = grad[a]
            with np.errstate(divide='ignore', invalid='ignore'):
                step = -np.stack([(h[:, 1, 1] * g[:, 0] - h[:, 0, 1] * g[:, 1]) / det,
                                  (-h[:, 1, 0] * g[:, 0] + h[:, 0, 0] * g[:, 1]) / det], axis=1)
            descent = (step * g).sum(1)
            bad = ~np.isfinite(step).all(1) | (descent >= 0)
            step[bad] = -g[bad] / np.maximum(np.abs(g[bad]).max(1, keepdims=True), 1e-300)
            descent = (step * g).sum(1)
            t = np.ones(len(a))
            accepted = np.zeros(len(a), bool)
            new_x = x[a].copy(); new_value = value[a].copy()
            for _ in range(60):
                trial = x[a] + t[:, None] * step
                tv, _, _ = evaluate(trial, a, False)
                good = ~accepted & (tv <= value[a] + 1e-4 * t * descent)
                new_x[good] = trial[good]; new_value[good] = tv[good]
                accepted |= good
                if accepted.all():
                    break
                t = np.where(accepted, t, t * 0.5)
            moved = np.abs(new_x - x[a]).max(1)
            change = value[a] - new_value
            x[a] = new_x
            value[a] = new_value
            done = (~accepted) | (new_value <= 0) | ((change <= 1e-15 * np.maximum(new_value, 1e-300)) & (moved < 1e-9))
            active[a[done]] = False
            if active.any():
                sel = np.flatnonzero(active)
                v2, g2, h2 = evaluate(x[sel], sel, True)
                value[sel], grad[sel], hess[sel] = v2, g2, h2
        best = np.minimum(best, value)
    out[idx] = best
    return out


def modified_topness(lepton, b, met, *, m_w, m_top, sigma_w, sigma_top, floor=None):
    """ln(min S); -inf when a consistent configuration exists, unless ``floor`` is given."""
    s = topness_minimum(lepton, b, met, m_w=m_w, m_top=m_top, sigma_w=sigma_w, sigma_top=sigma_top)
    if floor is not None:
        s = np.where(np.isfinite(s), np.maximum(s, float(floor)), s)
    with np.errstate(divide='ignore'):
        return np.log(s)
