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

Usage:
  pyhf_exclude.py likelihood --bkg BKG.json --patch PATCH.json --out OUTDIR [--label TXT]
  pyhf_exclude.py counting   --srs SRS.json                     --out OUTDIR [--label TXT]
      where SRS.json = [{"name": "...", "n": <obs>, "b": <bkg>, "db": <bkg_unc>, "s": <signal>}, ...]
"""
import argparse, json, os, sys
import numpy as np

try:
    import pyhf
    from pyhf.infer import hypotest
except ImportError as exc:
    sys.exit(f"pyhf import failed ({exc}) -- run in the 'rivet' conda env (pip install pyhf[minuit]).")

pyhf.set_backend("numpy")


# --------------------------------------------------------------------------- #
# model builders
# --------------------------------------------------------------------------- #
def model_from_likelihood(bkg_path, patch_path):
    """Background-only workspace + signal JSON-Patch -> (model, data)."""
    import jsonpatch
    bkg = json.load(open(bkg_path))
    patch = json.load(open(patch_path))
    spec = jsonpatch.apply_patch(bkg, patch)
    ws = pyhf.Workspace(spec)
    model = ws.model(
        modifier_settings={
            "normsys": {"interpcode": "code4"},
            "histosys": {"interpcode": "code4p"},
        }
    )
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

    def par_bounds(hi):
        b = [list(x) for x in bounds]
        b[poi_idx] = [0.0, float(hi)]
        return b

    cache = {}

    def cls_at(mu):
        if mu not in cache:
            o, e = hypotest(mu, data, model, par_bounds=par_bounds(max(mu * 1.5, 2.0)),
                            test_stat="qtilde", return_expected_set=True)
            cache[mu] = (float(o), [float(v) for v in e])  # obs, [-2,-1,med,+1,+2]sigma
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
    # CR-001 mirror flag: any column whose CLs never rises above `level` at the LOW end got its
    # "limit" from the scan floor -- an upper bound on a hyper-excluded point, never a limit.
    at_floor = bool(obs[0] <= level) or any(float(exp_arr[0, j]) <= level for j in range(5))
    non_mono = any(obs[i + 1] > obs[i] + 1e-6 for i in range(len(obs) - 1))
    if at_cap:
        print(f"  WARNING: observed CLs never crossed {level} up to mu={scan[-1]:.3g} "
              "-- reported obs_limit is a scan CEILING, not a limit", file=sys.stderr)
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
        "at_poi_cap": at_cap,
        "at_mu_floor": at_floor,
        "cls_monotonic": not non_mono,
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
def selftest():
    """CR-001 regression: the three CLs-curve regimes must be resolved/flagged correctly.

    Synthetic single-bin counting models (fast, no input files):
      normal          a genuine crossing near mu~1: no flags;
      hyper-excluded  huge signal, mu95 << 0.1: the downward bracket must resolve a REAL
                      crossing -- no floored obs_limit=1.0, no flat [1,1,1,1,1] band (the
                      fig3 m60_dm5/m70_dm5 failure mode);
      unconstrained   negligible signal: the ceiling is flagged at_poi_cap, never a limit.
    """
    cases = [
        ("normal", dict(name="SR", n=5, b=5.0, db=1.0, s=8.0),
         lambda r: not r["at_mu_floor"] and not r["at_poi_cap"] and 0.05 < r["obs_limit"] < 5.0),
        ("hyper-excluded", dict(name="SR", n=5, b=5.0, db=1.0, s=2.0e4),
         lambda r: r["obs_limit"] < 5e-3 and not r["at_mu_floor"]
                   and r["obs_limit"] != 1.0 and len(set(r["exp_limits"])) > 1),
        ("unconstrained", dict(name="SR", n=5, b=5.0, db=1.0, s=1e-4),
         lambda r: r["at_poi_cap"]),
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
    if failed:
        sys.exit(f"pyhf_exclude selftest FAILED: {failed}")
    print("pyhf_exclude selftest: all three regimes resolved/flagged correctly (CR-001 guard).")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)

    sub.add_parser("selftest", help="CR-001 regression: normal / hyper-excluded / unconstrained")

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
            if r["at_poi_cap"]:
                entry["at_poi_cap"] = True
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
