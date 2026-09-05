#!/usr/bin/env python
"""Compute a 95% CL upper limit on the signal strength mu with pyhf.

Two model-building modes, matching what a search actually publishes:

  likelihood : a full serialized statistical model (background-only workspace +
               a JSON-Patch that adds the signal). This is the ATLAS-preferred
               reinterpretation input. Used as-is -- no hand-rolled model.
  counting   : no serialized likelihood available, so build a simple
               single-bin-per-SR counting model from each signal region's
               (observed, background, background-uncertainty, signal) numbers.
               The limit is quoted from the single most-sensitive SR (best
               EXPECTED CLs), which is the standard prescription when the SRs
               overlap and cannot be statistically combined.

Both modes report the OBSERVED and EXPECTED (+/-1,2 sigma) 95% CL upper limit on
mu via pyhf.infer.intervals.upper_limit (a real root-find -- no fixed grid that
could truncate the scan), plus a CLs-vs-mu curve that is guaranteed to reach the
0.05 crossing.

Every minimization runs through `robust_optimizer` (CR-005, 2026-08-28): scipy/SLSQP
first (bit-identical to stock on clean surfaces), with a NaN-guarded iminuit-MIGRAD
fallback plus sticky per-model escalation the moment a fit is distrusted -- published
histosys workspaces can carry NaN pockets on which SLSQP silently returns its init
vector claiming success. `exclusion.json` records the guard's activity under
"optimizer", and flags `median_at_cap` (CR-124) and `band_degenerate` (CR-132) mark
a ceiling-pinned median and an unusable expected band. Regressions: `selftest`.

Usage:
  pyhf_exclude.py likelihood --bkg BKG.json --patch PATCH.json --out OUTDIR [--label TXT]
  pyhf_exclude.py counting   --srs SRS.json                     --out OUTDIR [--label TXT]
      where SRS.json = [{"name": "...", "n": <obs>, "b": <bkg>, "db": <bkg_unc>, "s": <signal>}, ...]
"""

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.physics"

import argparse, json, os, sys
import numpy as np
from ..paths import package_data_path

try:
    import pyhf
    from pyhf.infer import hypotest
    from pyhf.optimize.opt_scipy import scipy_optimizer
except ImportError as exc:
    raise ImportError("pyhf is required; install ravel-hep[replay] or use the rivet environment.") from exc


class robust_optimizer(scipy_optimizer):
    """scipy/SLSQP with a convergence guard + NaN-guarded iminuit-MIGRAD fallback.

    CR-005 routine cert (2026-08-28): on the ATLAS-SUSY-2018-06 published likelihood
    (ins1771533) the -2lnL surface has NaN pockets (histosys interpolation drives bins
    negative) and pyhf 0.7.6's scipy/SLSQP backend SILENTLY returned the init vector
    claiming success (free fit -2lnL 302.52 vs the true 271.79, mu_hat==init==1.0),
    which shipped mu95_obs=1.192 with obs==exp -- no error raised. pyhf's own minuit
    backend also aborts there (no NaN guard; EDM blow-up). CR-132 had already
    registered the same silent-SLSQP class on tightly-constrained projected workspaces.

    Policy (validated against the published 2018-06 point (300,100): mu95 0.826/0.584
    vs ATLAS sigma95/sigma_theory 0.828/0.587; case-9 Gbb Mode-A 0.174 unchanged):
      1. run SLSQP first, WATCHING the objective -- on a NaN-free surface the result
         is bit-identical to the stock backend (benchmark baselines cannot move);
      2. distrust it if the minimization raised, reported failure, returned a
         non-finite minimum, drifted a fixed parameter (scipy fixes via equality
         constraints), or the objective EVER evaluated non-finite during the run
         (the line search touched a NaN pocket -- the observed stuck-at-init mode
         moves 57/69 params slightly, so "did it move" cannot catch it);
      3. re-minimize with iminuit MIGRAD on a NaN-guarded objective (non-finite ->
         1e10), parameters fixed NATIVELY in Minuit, strategy 1 then 2, and RAISE
         on an invalid minimum -- nothing ever silently returns init;
      4. keep whichever valid minimum is lower, so the fallback can only improve;
      5. ESCALATE stickily: one distrusted fit marks the model's surface NaN-pocketed
         and every later minimization goes straight to guarded MIGRAD. Measured on
         2018-06: SLSQP is silently stuck even in minimizations that never evaluate
         a non-finite point (fixed-poi fits ~9 units high with zero NaN sightings),
         so per-fit signals alone leave a corrupt, non-monotonic CLs curve -- trust
         of that surface, once lost, cannot be regained fit-by-fit. compute() resets
         the flag per model and recomputes any CLs points cached before the flip.
    """

    n_fits = 0          # minimizations attempted
    n_fallback = 0      # minimizations re-run through guarded MIGRAD after SLSQP distrust
    n_escalated = 0     # minimizations sent straight to MIGRAD (post-escalation)
    n_nan_flagged = 0   # fallbacks triggered by a non-finite objective evaluation
    escalated = False   # sticky: this process' current model surface is distrusted
    _announced = False

    def _minimize(self, minimizer, func, x0, do_grad=False, bounds=None, fixed_vals=None, options={}):
        if do_grad:
            # autodiff backends carry exact gradients; the finite-difference NaN
            # line-search failure class does not apply -- delegate untouched.
            return super()._minimize(minimizer, func, x0, do_grad=do_grad, bounds=bounds,
                                     fixed_vals=fixed_vals, options=options)
        robust_optimizer.n_fits += 1
        if robust_optimizer.escalated:
            robust_optimizer.n_escalated += 1
            return self._migrad(func, x0, bounds, fixed_vals)
        nan_seen = [0]

        def watched(x):
            v = func(x)
            if not np.all(np.isfinite(np.asarray(v, dtype=float))):
                nan_seen[0] += 1
            return v

        result, why = None, None
        try:
            result = super()._minimize(minimizer, watched, x0, do_grad=do_grad, bounds=bounds,
                                       fixed_vals=fixed_vals, options=options)
        except Exception as exc:
            why = f"scipy raised {type(exc).__name__}"
        scipy_clean = (result is not None and bool(getattr(result, "success", False))
                       and np.isfinite(float(result.fun)))
        if why is None and not scipy_clean:
            why = "scipy reported failure or a non-finite minimum"
        if why is None and fixed_vals:
            for i, v in fixed_vals:
                if abs(float(result.x[i]) - float(v)) > 1e-6 * max(1.0, abs(float(v))):
                    why, scipy_clean = f"fixed parameter {i} drifted", False
                    break
        if why is None and nan_seen[0]:
            why = f"objective non-finite {nan_seen[0]}x during the minimization"
        if why is None:
            return result

        if nan_seen[0]:
            robust_optimizer.n_nan_flagged += 1
        robust_optimizer.n_fallback += 1
        robust_optimizer.escalated = True
        if not robust_optimizer._announced:
            robust_optimizer._announced = True
            print(f"  note: SLSQP result untrusted ({why}) -- re-minimizing with NaN-guarded "
                  "iminuit MIGRAD and ESCALATING: all further fits on this model go straight "
                  "to MIGRAD (CR-005; totals in exclusion.json 'optimizer')",
                  file=sys.stderr, flush=True)
        fallback = self._migrad(func, x0, bounds, fixed_vals)
        if scipy_clean and float(result.fun) <= float(fallback.fun):
            return result
        return fallback

    @staticmethod
    def _migrad(func, x0, bounds, fixed_vals):
        try:
            from iminuit import Minuit
        except ImportError as exc:
            raise RuntimeError(f"robust_optimizer needs iminuit for its fallback ({exc}) -- "
                               "pip install pyhf[minuit] in the 'rivet' env") from exc
        import scipy.optimize as so
        x0 = np.asarray(x0, dtype=float).copy()
        fixed_vals = list(fixed_vals or [])
        for i, v in fixed_vals:
            x0[i] = v

        def f(*z):
            v = float(np.asarray(func(np.asarray(z, dtype=float))).ravel()[0])
            return v if np.isfinite(v) else 1e10  # the NaN guard: MIGRAD backs off the cliff

        m = Minuit(f, *x0)
        if bounds is not None:
            for i, b in enumerate(bounds):
                m.limits[i] = b
        for i, _v in fixed_vals:
            m.fixed[i] = True
        m.errordef = 1.0  # func is -2lnL
        m.strategy = 1
        m.migrad(ncall=200000)
        if not m.valid:
            m.strategy = 2
            m.migrad(ncall=200000)
        if not m.valid:
            raise RuntimeError("robust_optimizer: guarded MIGRAD found no valid minimum "
                               f"(fval={m.fval}, edm={m.fmin.edm}) -- the likelihood surface is "
                               "sick; refusing to report a limit from an unconverged fit (CR-005)")
        return so.OptimizeResult(x=np.asarray(m.values, dtype=float), fun=float(m.fval),
                                 success=True, message="migrad-fallback ok", nfev=m.nfcn)


pyhf.set_backend("numpy", robust_optimizer(maxiter=200000))


# --------------------------------------------------------------------------- #
# model builders
# --------------------------------------------------------------------------- #
# HistFactory-standard interpolation (ROOT parity) for every likelihood-mode model.
MODIFIER_SETTINGS = {
    "normsys": {"interpcode": "code4"},
    "histosys": {"interpcode": "code4p"},
}


def model_from_likelihood(bkg_path, patch_path):
    """Background-only workspace + signal JSON-Patch -> (model, data)."""
    import jsonpatch
    bkg = json.load(open(bkg_path))
    patch = json.load(open(patch_path))
    spec = jsonpatch.apply_patch(bkg, patch)
    ws = pyhf.Workspace(spec)
    model = ws.model(modifier_settings=MODIFIER_SETTINGS)
    data = ws.data(model)
    return model, data


def model_from_counting(sr):
    """One SR's (n,b,db,s) -> (model, data) single-bin counting experiment."""
    model = pyhf.simplemodels.uncorrelated_background(
        signal=[float(sr["s"])], bkg=[float(sr["b"])], bkg_uncertainty=[float(sr["db"])]
    )
    data = [float(sr["n"])] + model.config.auxdata
    return model, data


def model_from_counting_combined(srs):
    """All SRs -> ONE multi-channel counting model (statistical combination).

    An N-bin uncorrelated_background model is exactly N independent single-bin
    channels (independent Poissons + independent constraints) fit simultaneously
    -- valid only when the SRs are mutually EXCLUSIVE (e.g. by lepton count).
    Published correlations are not available for a counting input, so background
    constraints are taken uncorrelated; document this with the result.
    """
    model = pyhf.simplemodels.uncorrelated_background(
        signal=[float(sr["s"]) for sr in srs],
        bkg=[float(sr["b"]) for sr in srs],
        bkg_uncertainty=[max(float(sr["db"]), 1e-6) for sr in srs],
    )
    data = [float(sr["n"]) for sr in srs] + model.config.auxdata
    return model, data


def low_count_flags(sr):
    """Honesty metadata: where the Gaussian-constraint approximation is strained."""
    flags = []
    if float(sr["b"]) < 5:
        flags.append("b<5")
    if float(sr["b"]) > 0 and float(sr["db"]) / float(sr["b"]) > 0.5:
        flags.append("db/b>0.5")
    if float(sr["n"]) < 5:
        flags.append("n<5")
    return flags


# --------------------------------------------------------------------------- #
# limit + scan
# --------------------------------------------------------------------------- #
def _cross(mu, cls, level=0.05):
    """First mu where the (decreasing) CLs curve crosses `level`, by linear interp."""
    mu = np.asarray(mu, float)
    cls = np.asarray(cls, float)
    for i in range(len(mu) - 1):
        if (cls[i] - level) * (cls[i + 1] - level) <= 0 and cls[i] != cls[i + 1]:
            f = (cls[i] - level) / (cls[i] - cls[i + 1])
            return float(mu[i] + f * (mu[i + 1] - mu[i]))
    # No crossing anywhere in the scan: the two ends mean OPPOSITE things (CR-001).
    if cls[0] <= level:
        return float(mu[0])   # whole curve below level (hyper-excluded): the lowest scanned mu
                              # is an upper BOUND on the limit, not a limit (at_mu_floor flags it)
    return float(mu[-1])      # whole curve above level: report the ceiling (at_poi_cap flags it)


def compute(model, data, level=0.05, n_curve=11, poi_cap=128.0):
    """Observed+expected 95% CL UL on mu plus a CLs-vs-mu curve, sharing ONE scan.

    Each fit is expensive on a full likelihood (~40 s for a 191-parameter ATLAS
    workspace), so we do a single bracket+scan and INTERPOLATE both the observed
    and expected limits from the same hypotest calls -- not a separate dense
    upper_limit() scan on top of the curve.
    """
    bounds = model.config.suggested_bounds()
    poi_idx = model.config.poi_index
    # optimizer-guard provenance (CR-005): snapshot the robust_optimizer counters so the
    # result can report how many minimizations in THIS computation needed the fallback.
    # Escalation is a property of one model's surface, so it is scoped per compute():
    # a NaN-pocketed SR must not tax later clean models in the same process.
    opt0 = (robust_optimizer.n_fits, robust_optimizer.n_fallback,
            robust_optimizer.n_nan_flagged, robust_optimizer.n_escalated)
    robust_optimizer.escalated = False

    def par_bounds(hi):
        b = [list(x) for x in bounds]
        b[poi_idx] = [0.0, float(hi)]
        return b

    cache = {}

    def cls_at(mu):
        if mu not in cache:
            esc_before = robust_optimizer.escalated
            o, e = hypotest(mu, data, model, par_bounds=par_bounds(max(mu * 1.5, 2.0)),
                            test_stat="qtilde", return_expected_set=True)
            if robust_optimizer.escalated and not esc_before:
                # This hypotest just flipped escalation: the model's surface is NaN-pocketed,
                # so every CLs point computed BEFORE the flip mixed now-untrusted SLSQP minima
                # (2018-06 evidence: partially-trusted curves come out non-monotonic with
                # cliff artifacts and a factor-3 wrong limit). Recompute them -- and the
                # triggering point itself, whose pre-flip sub-fits are equally untrusted.
                stale = sorted(cache)
                cache.clear()
                if stale:
                    print(f"  note: optimizer escalated mid-scan -- recomputing {len(stale)} "
                          "earlier CLs point(s) with the guarded-MIGRAD path (CR-005)",
                          file=sys.stderr, flush=True)
                for m2 in stale:
                    o2, e2 = hypotest(m2, data, model, par_bounds=par_bounds(max(m2 * 1.5, 2.0)),
                                      test_stat="qtilde", return_expected_set=True)
                    cache[m2] = (float(o2), [float(v) for v in e2])
                    print(f"  [cls scan] recompute mu={m2:.6g} CLs_obs={cache[m2][0]:.4g}",
                          file=sys.stderr, flush=True)
                o, e = hypotest(mu, data, model, par_bounds=par_bounds(max(mu * 1.5, 2.0)),
                                test_stat="qtilde", return_expected_set=True)
            cache[mu] = (float(o), [float(v) for v in e])  # obs, [-2,-1,med,+1,+2]sigma
            # heartbeat (stall-guard interop): one line per fresh hypotest so the redirected log's
            # mtime advances during the multi-minute CLs scan -- stage_supervisor.py's progress-stall
            # watchdog keys on log writes and killed silent-but-progressing pyhf fits at 12 min
            # (first seen: 2026-08-28 fresh-flagship smoke rung, pyhf.failure.json reason
            # 'progress-stall'). stderr: line-buffered under redirection, and kept out of stdout
            # parsing. Numerics untouched.
            print(f"  [cls scan] mu={mu:.6g} CLs_obs={cache[mu][0]:.4g} ({len(cache)} pts)",
                  file=sys.stderr, flush=True)
        return cache[mu]

    # bracket: double mu from 1 until BOTH the observed AND the +2sigma-EXPECTED CLs are < level.
    # The +2sigma expected limit is the largest of the five; bracketing on the observed alone leaves
    # the upper expected band pinned at the ceiling (the half-resolved-band bug). e=[-2,-1,med,+1,+2].
    hi = 1.0
    while hi < poi_cap:
        o, e = cls_at(hi)
        if o <= level and e[4] <= level:
            break
        hi *= 2.0

    # CR-001: bracket DOWN as well. On a hyper-excluded point CLs(mu=1) is already << level, the
    # upward loop exits immediately at hi=1.0, and the whole CLs curve sits below `level`: _cross
    # then has no low-side anchor and the reported "limit" is a scan-edge artifact (the fig3
    # m60_dm5/m70_dm5 dark-red diff-map cells). Halve mu until EVERY column rises above `level`
    # (observed + all five expected bands -- then every crossing is bracketed) or the floor is
    # hit (truly hyper-excluded: flagged at_mu_floor below, never reported as a limit).
    lo, mu_floor = 1.0, 1e-6
    while lo > mu_floor:
        o, e = cls_at(lo)
        if o > level and all(v > level for v in e):
            break
        lo /= 2.0

    # shared scan over [~0, hi]; reuse the bracket points already in the cache. If the downward
    # bracket ran (lo < 1), add geometric points across the low decades so the interpolation near
    # a low crossing has resolution comparable to the linear grid near mu~1 (CR-001).
    base = set(np.linspace(1e-3, hi, n_curve))
    if lo < 1.0:
        base |= set(np.geomspace(max(lo / 2.0, 1e-7), 1.0, n_curve))
    scan = sorted(base.union(k for k in cache))
    for mu in scan:
        cls_at(mu)
    # qtilde at mu~0 can return NaN; drop any non-finite obs/expected points so _cross stays defined
    def _finite(m):
        o, e = cache[m]
        return np.isfinite(o) and all(np.isfinite(v) for v in e)
    scan_all = sorted(cache)
    scan = [m for m in scan_all if _finite(m)]
    n_dropped = len(scan_all) - len(scan)
    if n_dropped:
        print(f"  note: dropped {n_dropped} non-finite CLs point(s) (e.g. qtilde at mu~0) from the scan",
              file=sys.stderr)
    if len(scan) < 2:
        sys.exit("pyhf_exclude: <2 finite CLs points -- cannot interpolate a limit")
    obs = [cache[m][0] for m in scan]
    exp = [cache[m][1] for m in scan]  # list of 5-vectors
    exp_arr = np.array(exp)

    obs_limit = _cross(scan, obs, level)
    exp_limits = [_cross(scan, exp_arr[:, j], level) for j in range(5)]  # [-2,-1,med,+1,+2]

    # robustness honesty: a ceiling is NOT a limit, and interpolation assumes a
    # decreasing CLs curve -- flag violations instead of silently reporting.
    at_cap = bool(obs[-1] > level) or hi >= poi_cap  # never crossed within the bracket / hit the cap
    # CR-124 (catalogue N9): at_poi_cap above also fires on mere bracket GRANULARITY (the doubling
    # bracket reached the cap chasing the +2sigma band while the median crossed far below it) --
    # consumers drew finite medians as ">cap" arrows. median_at_cap is true only when the MEDIAN
    # expected CLs itself never dropped below `level` anywhere in the scan, i.e. the reported
    # median limit really is the scan ceiling.
    median_at_cap = bool(exp_arr[:, 2].min() > level)
    # CR-001 mirror flag: any column whose CLs never rises above `level` at the LOW end got its
    # "limit" from the scan floor -- an upper bound on a hyper-excluded point, never a limit.
    at_floor = bool(obs[0] <= level) or any(float(exp_arr[0, j]) <= level for j in range(5))
    non_mono = any(obs[i + 1] > obs[i] + 1e-6 for i in range(len(obs) - 1))
    # CR-132 (catalogue B4): at weakly-constrained points the five expected quantiles can come
    # back (near-)identical -- a band spanning x1.005 where healthy qtilde bands span x2.5-4.
    # The median then looks plausible but the band is unusable: flag it, quote as a bound only.
    band_degenerate = bool(exp_limits[4] / max(exp_limits[0], 1e-12) < 1.5)
    if at_cap:
        print(f"  WARNING: observed CLs never crossed {level} up to mu={scan[-1]:.3g} "
              "-- reported obs_limit is a scan CEILING, not a limit", file=sys.stderr)
    if median_at_cap:
        print(f"  WARNING: the MEDIAN expected CLs never crossed {level} in the scan -- the "
              "reported median expected limit is the scan ceiling, not a limit (CR-124)",
              file=sys.stderr)
    if band_degenerate:
        print("  WARNING: expected band is DEGENERATE (+2sigma/-2sigma limit ratio < 1.5 where "
              "healthy qtilde bands span ~2.5-4x) -- the band is unusable; quote the result as "
              "a bound only (CR-132)", file=sys.stderr)
    if at_floor:
        print(f"  WARNING: CLs at the lowest scanned mu={scan[0]:.3g} is still <= {level} for the "
              "observed and/or an expected band -- that reported value is a scan FLOOR (an upper "
              "bound on a hyper-excluded point), not a limit (CR-001)", file=sys.stderr)
    if non_mono:
        print("  WARNING: observed CLs curve is not monotonically decreasing in mu; "
              "the interpolated crossing may be inaccurate -- inspect scan_cls_obs",
              file=sys.stderr)

    return {
        "obs_limit": obs_limit,
        "exp_limits": exp_limits,  # [-2,-1,med,+1,+2] sigma
        "scan_mu": [float(m) for m in scan],
        "scan_cls_obs": obs,
        "scan_cls_exp": exp,
        "n_fits": len(cache),
        "at_poi_cap": at_cap,          # bracket reached the cap (granularity -- see median_at_cap)
        "median_at_cap": median_at_cap,  # CR-124: the median limit itself is the scan ceiling
        "at_mu_floor": at_floor,
        "band_degenerate": band_degenerate,  # CR-132: expected band unusable, quote as bound only
        "cls_monotonic": not non_mono,
        "optimizer": {  # CR-005 provenance: which fits needed the guarded-MIGRAD fallback
            "primary": "scipy.SLSQP",
            "fallback": "iminuit.MIGRAD nan-guarded",
            "escalated": bool(robust_optimizer.escalated),
            "n_minimizations": robust_optimizer.n_fits - opt0[0],
            "n_fallback": robust_optimizer.n_fallback - opt0[1],
            "n_nan_flagged": robust_optimizer.n_nan_flagged - opt0[2],
            "n_escalated": robust_optimizer.n_escalated - opt0[3],
        },
    }


def plot(res, out_png, title, sr_label=None):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mu = np.array(res["scan_mu"])
    obs = np.array(res["scan_cls_obs"])
    exp = np.array(res["scan_cls_exp"])  # (N,5)

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.fill_between(mu, exp[:, 0], exp[:, 4], color="gold", alpha=0.5, label=r"expected $\pm2\sigma$")
    ax.fill_between(mu, exp[:, 1], exp[:, 3], color="limegreen", alpha=0.6, label=r"expected $\pm1\sigma$")
    ax.plot(mu, exp[:, 2], "k--", lw=1.4, label="expected median")
    ax.plot(mu, obs, "ko-", ms=3, lw=1.6, label="observed")
    ax.axhline(0.05, color="red", lw=1.3, label=r"95% CL ($\mathrm{CL}_s=0.05$)")
    ax.axvline(res["obs_limit"], color="navy", ls=":", lw=1.4,
               label=rf"$\mu^{{95}}_{{obs}}={res['obs_limit']:.2f}$")
    ax.set_xlabel(r"signal strength $\mu$")
    ax.set_ylabel(r"$\mathrm{CL}_s$")
    ax.set_ylim(0, 1.05)
    # zoom the x-axis around the crossing when the limit is small vs the scan range
    obs_lim = res["obs_limit"]
    xhi = mu.max() if obs_lim >= 0.4 * mu.max() else max(1.0, 2.5 * obs_lim)
    ax.set_xlim(0, xhi)
    sub = f"\n(most-sensitive SR: {sr_label})" if sr_label else ""
    ax.set_title(title + sub, fontsize=10)
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_png, dpi=140)
    print(f"  wrote {out_png}")


# --------------------------------------------------------------------------- #
def _nanpocket_model():
    """Synthetic likelihood-mode workspace whose -2lnL surface has NaN pockets.

    Each histosys nuisance's 'lo' template drives every bin NEGATIVE (code4p
    extrapolates linearly beyond |alpha|=1, so alpha pulled low -> negative
    Poisson rates -> NaN), and the data sit well below nominal so the fit is
    pulled toward the cliffs. Miniature of the ATLAS-SUSY-2018-06 published
    likelihood (ins1771533) on which pyhf 0.7.6's scipy/SLSQP backend returned
    the init vector claiming success (CR-005 routine cert, 2026-08-28).
    """
    nominal = [40.0, 30.0, 20.0]
    mods = [{"name": f"np{k}", "type": "histosys",
             "data": {"hi_data": [v * 1.10 for v in nominal],
                      "lo_data": [v * -1.5 for v in nominal]}}
            for k in range(6)]
    spec = {"channels": [{"name": "SR", "samples": [
        {"name": "signal", "data": [18.0, 15.0, 12.0],
         "modifiers": [{"name": "mu", "type": "normfactor", "data": None}]},
        {"name": "bkg", "data": list(nominal), "modifiers": mods},
    ]}]}
    model = pyhf.Model(spec, poi_name="mu", modifier_settings=MODIFIER_SETTINGS)
    data = [20.0, 14.0, 9.0] + model.config.auxdata
    return model, data


def selftest():
    """Regression pack: CLs regimes (CR-001), cap/band flags (CR-124/CR-132), optimizer guard (CR-005).

    Synthetic single-bin counting models (fast, no input files):
      normal          a genuine crossing near mu~1: no flags;
      hyper-excluded  huge signal, mu95 << 0.1: the downward bracket must resolve a REAL
                      crossing -- no floored obs_limit=1.0, no flat [1,1,1,1,1] band (the
                      fig3 m60_dm5/m70_dm5 failure mode);
      unconstrained   negligible signal: the ceiling is flagged at_poi_cap, never a limit --
                      and its ceiling-pinned median/band carry median_at_cap + band_degenerate.
    Silent-optimizer-failure regressions (CR-005, 2026-08-28):
      nan-pocket      synthetic likelihood model with histosys NaN pockets: the guard must
                      fire, escalate, and still land on the guarded-MIGRAD reference limit;
      2018-06-freefit the real observed failure, from the committed fixture
                      (testdata/susy-2018-06): free fit must reach the true minimum 271.79,
                      not SLSQP's stuck-at-init 302.52.
    """
    cases = [
        # CR-124: a healthy crossing must NOT carry the cap/degeneracy flags; the
        # unconstrained regime's median sits at the scan ceiling -> median_at_cap,
        # and its five cap-pinned quantiles are a degenerate band (CR-132).
        ("normal", dict(name="SR", n=5, b=5.0, db=1.0, s=8.0),
         lambda r: not r["at_mu_floor"] and not r["at_poi_cap"] and 0.05 < r["obs_limit"] < 5.0
                   and not r.get("median_at_cap", True) and not r.get("band_degenerate", True)),
        ("hyper-excluded", dict(name="SR", n=5, b=5.0, db=1.0, s=2.0e4),
         lambda r: r["obs_limit"] < 5e-3 and not r["at_mu_floor"]
                   and r["obs_limit"] != 1.0 and len(set(r["exp_limits"])) > 1),
        ("unconstrained", dict(name="SR", n=5, b=5.0, db=1.0, s=1e-4),
         lambda r: r["at_poi_cap"] and r.get("median_at_cap", False)
                   and r.get("band_degenerate", False)),
    ]
    failed = []
    for label, sr, ok in cases:
        model, data = model_from_counting(sr)
        r = compute(model, data, poi_cap=32.0)
        verdict = "PASS" if ok(r) else "FAIL"
        print(f"  selftest {label:15s} obs_limit={r['obs_limit']:.4g}  "
              f"at_mu_floor={r['at_mu_floor']} at_poi_cap={r['at_poi_cap']}  -> {verdict}")
        if verdict == "FAIL":
            failed.append(label)

    # --- CR-005/CR-132 (2026-08-28) silent-optimizer-failure regressions ------- #
    # nan-pocket: the hardened optimizer must (a) survive the NaN pockets, (b) match
    # the guarded-MIGRAD reference limit (pyhf_tnc_exclude lineage, 2026-08-28), and
    # (c) REPORT that the fallback actually fired -- (c) keeps the case honest: if the
    # surface ever stops exercising the guard, the case fails instead of testing nothing.
    model, data = _nanpocket_model()
    r = compute(model, data, poi_cap=32.0)
    ref = 2.4359
    # `escalated` must be reported: one distrusted fit taints the whole model (2018-06
    # showed SLSQP silently stuck even in minimizations that never evaluated NaN, so a
    # per-fit NaN signal alone is NOT sufficient -- the computation must go MIGRAD-first).
    ok = (np.isfinite(r["obs_limit"]) and abs(r["obs_limit"] - ref) / ref < 0.02
          and not r["at_poi_cap"] and not r["at_mu_floor"]
          and r.get("optimizer", {}).get("n_fallback", 0) >= 1
          and r.get("optimizer", {}).get("escalated") is True)
    verdict = "PASS" if ok else "FAIL"
    print(f"  selftest {'nan-pocket':15s} obs_limit={r['obs_limit']:.4g} (ref {ref})  "
          f"n_fallback={r.get('optimizer', {}).get('n_fallback', 0)} "
          f"escalated={r.get('optimizer', {}).get('escalated')}  -> {verdict}")
    if not ok:
        failed.append("nan-pocket")

    # 2018-06 free fit: the exact observed failure -- on the ATLAS-SUSY-2018-06
    # published likelihood + ERJR_300p0_100p0 patch, stock SLSQP returned the init
    # vector claiming success (-2lnL 302.52, mu_hat==1.0) vs the true minimum
    # 271.79 / mu_hat 0.2446. Runs from the committed fixture (testdata/susy-2018-06).
    fx = str(package_data_path("fixtures", "susy-2018-06"))
    bkg_p, patch_p = os.path.join(fx, "BkgOnly.json"), os.path.join(fx, "patch_ERJR_300p0_100p0.json")
    if os.path.exists(bkg_p) and os.path.exists(patch_p):
        model, data = model_from_likelihood(bkg_p, patch_p)
        robust_optimizer.escalated = False  # exercise the SLSQP-distrust path itself,
        # not escalation left over from the nan-pocket case above
        pars, nll = pyhf.infer.mle.fit(data, model, return_fitted_val=True)
        nll, mu_hat = float(nll), float(pars[model.config.poi_index])
        ok = nll < 272.0 and abs(mu_hat - 0.2446) < 0.02
        verdict = "PASS" if ok else "FAIL"
        print(f"  selftest {'2018-06-freefit':15s} twice_nll={nll:.4f} (true 271.79; stuck-SLSQP 302.52) "
              f"mu_hat={mu_hat:.4f}  -> {verdict}")
        if not ok:
            failed.append("2018-06-freefit")
    else:
        print(f"  selftest {'2018-06-freefit':15s} SKIPPED (fixture missing: {fx})")

    if failed:
        sys.exit(f"pyhf_exclude selftest FAILED: {failed}")
    print("pyhf_exclude selftest: CLs regimes (CR-001), cap/band flags (CR-124/CR-132), and "
          "NaN-pocket optimizer guard (CR-005) all PASS.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)

    sub.add_parser("selftest", help="regressions: CLs regimes (CR-001), cap/band flags "
                                    "(CR-124/CR-132), NaN-pocket optimizer guard (CR-005)")

    a = sub.add_parser("likelihood")
    a.add_argument("--bkg", required=True)
    a.add_argument("--patch", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--label", default="serialized likelihood")
    a.add_argument("--sigma-scale", type=float, default=1.0, help="NLO+NLL k-factor (µ₉₅ on NLO σ = µ₉₅/k)")

    c = sub.add_parser("counting")
    c.add_argument("--srs", required=True, help="JSON list of {name,n,b,db,s}")
    c.add_argument("--out", required=True)
    c.add_argument("--label", default="counting model")
    c.add_argument("--sigma-scale", type=float, default=1.0, help="NLO+NLL k-factor (µ₉₅ on NLO σ = µ₉₅/k)")
    c.add_argument("--combined", action="store_true",
                   help="headline limit from the SIMULTANEOUS multi-channel fit of all SRs "
                        "(valid only for mutually exclusive SRs); per-SR limits + best_sr "
                        "are still computed and reported")

    args = ap.parse_args()
    if args.mode == "selftest":
        selftest()
        return
    os.makedirs(args.out, exist_ok=True)

    if args.mode == "likelihood":
        model, data = model_from_likelihood(args.bkg, args.patch)
        print(f"likelihood model: {model.config.nmaindata} bins, {len(model.config.par_order)} parameters")
        res = compute(model, data)
        res["mode"] = "likelihood"
        best_label = None
    else:
        srs = json.load(open(args.srs))
        # per-SR limits always computed: they feed best_sr (best EXPECTED sensitivity)
        # and the per_sr record consumers (cert engines, the benchmark gate).
        best, best_res = None, None
        per_sr = {}
        for sr in srs:
            entry = {"n": sr["n"], "b": sr["b"], "db": sr["db"], "s": sr["s"]}
            flags = low_count_flags(sr)
            if flags:
                entry["low_count_flags"] = flags
            if float(sr["s"]) <= 0.0:
                # a zero-signal SR puts NO constraint on mu: the bracket would run to
                # the poi cap and record a ceiling that is not a limit. Skip honestly.
                entry["skipped"] = "zero signal (s<=0): no constraint on mu"
                per_sr[sr["name"]] = entry
                print(f"  SR {sr['name']:6s}: s=0 -> SKIPPED (no constraint on mu)")
                continue
            model, data = model_from_counting(sr)
            r = compute(model, data, n_curve=25)  # counting fits are instant -> fine grid
            entry.update({"obs_limit": r["obs_limit"], "exp_median": r["exp_limits"][2]})
            for flag in ("at_poi_cap", "median_at_cap", "band_degenerate"):
                if r[flag]:
                    entry[flag] = True
            per_sr[sr["name"]] = entry
            print(f"  SR {sr['name']:6s}: s={sr['s']:.2f} b={sr['b']:.1f}+-{sr['db']:.1f} n={sr['n']:.0f}"
                  f"  -> mu_obs={r['obs_limit']:.2f} (exp {r['exp_limits'][2]:.2f})")
            if best is None or r["exp_limits"][2] < best_res["exp_limits"][2]:
                best, best_res = sr["name"], r
        if best is None:
            sys.exit("counting: no SR with s>0 -- nothing constrains mu")
        per_sr[best]["is_best"] = True
        if getattr(args, "combined", False):
            # headline = simultaneous fit of all constraining channels (exclusive SRs);
            # zero-signal channels are inert for mu and omitted from the fit.
            fit_srs = [sr for sr in srs if float(sr["s"]) > 0.0]
            model, data = model_from_counting_combined(fit_srs)
            res = compute(model, data, n_curve=25)
            res["mode"] = "counting-combined"
            res["combined_channels"] = [sr["name"] for sr in fit_srs]
            res["mode_notes"] = ("simultaneous multi-channel counting fit; background "
                                 "constraints uncorrelated (no published correlations); "
                                 "valid for mutually exclusive SRs only")
            print(f"  COMBINED ({len(fit_srs)} ch): mu_obs={res['obs_limit']:.2f} "
                  f"(exp {res['exp_limits'][2]:.2f})")
        else:
            res = best_res
            res["mode"] = "counting"
        res["best_sr"] = best
        res["per_sr"] = per_sr
        best_label = best

    res["label"] = args.label
    # apply the NLO+NLL k-factor: a stronger nominal σ scales the signal-strength limit by 1/k.
    k = getattr(args, "sigma_scale", 1.0)
    if k and k != 1.0:
        res["sigma_scale_k"] = k
        res["obs_limit_lo"] = res["obs_limit"]
        res["exp_limits_lo"] = list(res["exp_limits"])
        res["obs_limit"] = res["obs_limit"] / k
        res["exp_limits"] = [x / k for x in res["exp_limits"]]
        print(f"  applied NLO+NLL k={k}: µ₉₅(LO)={res['obs_limit_lo']:.3f} -> µ₉₅(NLO)={res['obs_limit']:.3f}")
    json.dump(res, open(os.path.join(args.out, "exclusion.json"), "w"), indent=2)
    plot(res, os.path.join(args.out, "exclusion.png"), args.label, sr_label=best_label)

    print("\n=== 95% CL upper limit on mu ===")
    print(f"  observed : {res['obs_limit']:.3f}")
    el = res["exp_limits"]
    print(f"  expected : {el[2]:.3f}  (+1s {el[3]:.3f} / -1s {el[1]:.3f})")
    verdict = "EXCLUDED (mu=1 disfavoured)" if res["obs_limit"] < 1.0 else "NOT excluded (mu=1 allowed)"
    print(f"  nominal signal (mu=1): {verdict}")


if __name__ == "__main__":
    main()
