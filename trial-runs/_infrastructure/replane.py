#!/usr/bin/env python
"""replane -- REPLANE a published simplified-model exclusion into a new parameter plane (CR-025, G2d).

The P7 second half: "reinterpret the exclusion limits in Figure 3 in the µ-M2 plane, under the
simplified higgsino model, assuming M1=M2 and tanbeta=50." A published search sets an UPPER LIMIT
on sigma*BR versus one physical mass, ASSUMING a pure simplified model (e.g. pure higgsino). To
re-express that limit in a different SUSY parameter plane we must, at every target-plane point:
  1. compute the physical spectrum + gauge composition (spectrum_mix.py -- the BUILT spectrum leg);
  2. pick the state the search actually targets (--target-state, e.g. C1 or N2) -> its MASS;
  3. predict the model's sigma*BR at that point. Production sigma depends on the gauge content
     (wino-like pairs are produced far more than higgsino-like at equal mass), so with pure-state
     reference cross-sections we weight by the composition fractions -- THIS is where trap T3 bites:
     the target plane generally BREAKS the published pure-state assumption, so the composition
     reweighting (and its effect on sigma AND on acceptance) must be applied or explicitly bounded;
  4. r(point) = sigma*BR_model / sigma_UL(mass); EXCLUDED where r >= 1.
The output is the r-grid + the r=1 exclusion contour in the NEW plane, lint-gated (CR-016).

This is the DIRECT fold of ONE published limit. The SModelS-database fold (many analyses at once,
topology-mappable) is Option D1 -- `reinterpret_db.py --data-select efficiencyMap`; use that when
the question is "which published analyses exclude this point", this when the question is "re-express
THIS paper's Figure-N limit in a new plane".

VALIDATION GATE (ladder R5, non-negotiable -- printed on every real run): round-trip the paper's OWN
plane. With the published pure-state sigma model and the published mass on both sides, replane must
reproduce the published contour (transform -> invert = identity). `--selftest` proves the identity +
monotonicity + composition-weighting numerically. TREE-LEVEL spectrum (spectrum_mix caveat): quote
SPheno/SuSpect when intra-multiplet mass precision matters; DECLARE it.

Usage:
  replane.py fold --grid <spectrum_mix --plane .json> --ul-curve <ul.json|2col.txt>
      --target-state C1|C2|N1|N2 --sigma-model <model.json>
      [--x mu --y M2] [--out DIR] [--experiment ATLAS] [--no-lint]
  replane.py --selftest

sigma-model.json:
  {"mode":"pure",                       # composition-weighted from pure-state sigma(mass) refs
   "refs":{"higgsino":"hino_sigma.json","wino":"wino_sigma.json"},  # each {"mass":[...],"sigma_fb":[...]}
   "br":1.0}                            # optional constant BR into the searched final state
  {"mode":"direct","sigma_xbr_fb":{"mass":[...],"value":[...]}}     # sigma*BR(mass) given outright
                                        # (round-trip / when the model prediction is tabulated)
ul-curve.json: {"mass":[...],"sigma_ul_fb":[...]}  (or a 2-column "mass sigma_ul_fb" text file).

2-D UL SURFACE mode (compressed-spectrum searches limit sigma vs BOTH a mass and a mass
splitting): give --ul-curve a JSON carrying a "dm" list ({"mass":[...],"dm":[...],
"sigma_ul_fb":[...]}, one triplet per published grid point). The fold then evaluates the
surface at each target-plane point's OWN (mass, dm): dm = m(C1) - m(N1) from the spectrum
point (tree level), plus an optional additive term interpolated from --dm-extra-curve
({"mass":[...],"value":[...]}; e.g. the one-loop intra-multiplet splitting, which is absent
at tree level and dominates for heavy gauginos -- DECLARE its formula). Interpolation is
triangulated-linear in (mass, dm) on log(UL); a point OUTSIDE the published convex hull is
'covered': false (r null, NOT excluded, NOT allowed) -- coverage is first-class (trap T4),
never extrapolated.
"""
import argparse
import json
import os
import sys

import numpy as np


def die(msg):
    print(f"ERROR (replane): {msg}", file=sys.stderr)
    sys.exit(1)


def _interp(x, xs, ys, kind="log"):
    """Interpolate ys(xs) at x. UL/sigma curves are ~exponential in mass -> interpolate in log-y
    (a linear interp of a steep falling curve badly overshoots between sparse published points)."""
    xs = np.asarray(xs, float); ys = np.asarray(ys, float)
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    if kind == "log" and np.all(ys > 0):
        return float(np.exp(np.interp(x, xs, np.log(ys), left=np.log(ys[0]), right=np.log(ys[-1]))))
    return float(np.interp(x, xs, ys, left=ys[0], right=ys[-1]))


def _load_curve(spec, xkey="mass", ykey=None):
    """Load {mass:[...], <ykey>:[...]} from a JSON object, a JSON file path, or a 2-column text file."""
    if isinstance(spec, dict):
        d = spec
    elif os.path.isfile(spec) and spec.lower().endswith(".json"):
        with open(spec) as f:
            d = json.load(f)
    elif os.path.isfile(spec):                       # 2-column text
        arr = np.loadtxt(spec)
        return arr[:, 0].tolist(), arr[:, 1].tolist()
    else:
        die(f"curve not found / not JSON: {spec}")
    ys = None
    for k in ([ykey] if ykey else ["sigma_ul_fb", "value", "sigma_fb"]):
        if k and k in d:
            ys = d[k]; break
    if ys is None or xkey not in d:
        die(f"curve must carry '{xkey}' and one of sigma_ul_fb/value/sigma_fb; got {list(d)}")
    return d[xkey], ys


def _gauge_fractions(st):
    """Return (bino, wino, higgsino) production-relevant fractions for any state. Neutralinos carry
    them directly; charginos carry the U and V mixing weights (wino_U/V, higgsino_U/V, no bino --
    charginos have no bino component) -> use the U/V average, the natural single measure of the
    chargino's gauge content for production."""
    if "wino" in st or "higgsino" in st:
        return float(st.get("bino", 0.0)), float(st.get("wino", 0.0)), float(st.get("higgsino", 0.0))
    if "wino_U" in st:                               # chargino: average the two mixing matrices
        w = 0.5 * (float(st.get("wino_U", 0.0)) + float(st.get("wino_V", 0.0)))
        h = 0.5 * (float(st.get("higgsino_U", 0.0)) + float(st.get("higgsino_V", 0.0)))
        return 0.0, w, h
    return 0.0, 0.0, 0.0


def _state(point, name):
    """Pull one state dict (C1/C2/N1..N4) out of a spectrum_mix point."""
    for coll in ("charginos", "neutralinos"):
        for st in point.get(coll, []):
            if st.get("state") == name:
                return st
    die(f"target-state {name!r} not in spectrum point (have "
        f"{[s.get('state') for s in point.get('charginos', []) + point.get('neutralinos', [])]})")


def sigma_model_at(state, model):
    """sigma*BR (fb) for one state under the given sigma model. Pure mode: composition-weighted
    over pure-state references, using the state's fraction as the production-mode weight (winos
    dominate at equal mass -> a wino-fraction point predicts the wino sigma). Direct mode: tabulated
    sigma*BR(mass)."""
    m = state["mass"]
    br = float(model.get("br", 1.0))
    if model["mode"] == "direct":
        xs, ys = _load_curve(model["sigma_xbr_fb"], ykey="value")
        return _interp(m, xs, ys) * br
    if model["mode"] == "pure":
        refs = model["refs"]
        # gauge-content weights (charginos: U/V average; neutralinos: direct)
        fb, fw, fh = _gauge_fractions(state)
        sig = 0.0
        wsum = 0.0
        for key, frac in (("wino", fw), ("higgsino", fh), ("bino", fb)):
            if key in refs and frac > 0:
                xs, ys = _load_curve(refs[key], ykey="sigma_fb")
                sig += frac * _interp(m, xs, ys)
                wsum += frac
        if wsum <= 0:
            die(f"state {state.get('state')} has no composition overlap with the provided refs "
                f"{list(refs)} (bino/wino/higgsino fractions all ~0 or unref'd)")
        # renormalize by the referenced fraction sum so an unref'd component (e.g. pure-bino, which
        # is not EW-pair-produced in these searches) does not dilute the prediction silently
        return (sig / wsum) * br
    die(f"unknown sigma-model mode {model.get('mode')!r} (pure|direct)")


def _load_surface(spec):
    """Load a 2-D UL surface {mass:[...], dm:[...], sigma_ul_fb:[...]} (dict or JSON path).
    Returns None when the spec has no 'dm' key (caller falls back to the 1-D curve path)."""
    d = spec
    if not isinstance(d, dict):
        if os.path.isfile(str(spec)) and str(spec).lower().endswith(".json"):
            with open(spec) as f:
                d = json.load(f)
        else:
            return None
    if "dm" not in d:
        return None
    if not ("mass" in d and "sigma_ul_fb" in d):
        die(f"2-D UL surface must carry mass/dm/sigma_ul_fb; got {list(d)}")
    m, dm, ul = (np.asarray(d["mass"], float), np.asarray(d["dm"], float),
                 np.asarray(d["sigma_ul_fb"], float))
    if not (len(m) == len(dm) == len(ul)) or len(m) < 3:
        die("2-D UL surface needs >=3 equal-length mass/dm/sigma_ul_fb triplets")
    if np.any(ul <= 0):
        die("2-D UL surface: sigma_ul_fb must be positive (log interpolation)")
    import matplotlib.tri as mtri                    # lazy: only the 2-D path needs it
    tri = mtri.Triangulation(m, dm)
    lin = mtri.LinearTriInterpolator(tri, np.log(ul))
    tol_m = 1e-6 * (m.max() - m.min())
    tol_d = 1e-6 * (dm.max() - dm.min())

    def query(qm, qdm):
        """log(UL) at (qm, qdm), or None outside the hull. Hull-edge float guard: a
        query within ~1e-6 of the hull (published grid corners land EXACTLY on the
        edge; tree+loop dm sums carry float noise) is snapped in, never a real
        extrapolation."""
        v = lin(qm, qdm)
        if not np.ma.is_masked(v):
            return float(v)
        for em, ed in ((0, tol_d), (0, -tol_d), (tol_m, 0), (-tol_m, 0),
                       (tol_m, tol_d), (-tol_m, -tol_d), (tol_m, -tol_d), (-tol_m, tol_d)):
            v = lin(qm + em, qdm + ed)
            if not np.ma.is_masked(v):
                return float(v)
        return None
    return query


def _dm_of_point(pt, dm_extra):
    """Target-plane point's own splitting: m(C1) - m(N1) (tree, from the spectrum point)
    + the optional additive dm_extra(mass) curve (e.g. the declared one-loop term)."""
    c1 = _state(pt, "C1")
    n1 = _state(pt, "N1")
    n1m = abs(n1.get("signed_mass", n1["mass"]))
    dm = c1["mass"] - n1m
    if dm_extra is not None:
        dm += _interp(c1["mass"], dm_extra[0], dm_extra[1], kind="linear")
    return dm


def fold(grid, ul_spec, model, target_state, xkey="mu", ykey="M2", dm_extra=None):
    """Return per-point rows [{x,y,mass,comp,sigma_xbr_fb,sigma_ul_fb,r,excluded,covered}].

    1-D mode (default): UL interpolated in the target state's mass. 2-D mode (the ul_spec
    carries a 'dm' list): UL evaluated at the point's own (mass, dm) -- see module docstring;
    outside the published hull the point is covered=False (r None, excluded False)."""
    surf = _load_surface(ul_spec)
    if surf is None:
        ul_x, ul_y = _load_curve(ul_spec, ykey="sigma_ul_fb")
    rows = []
    for pt in grid["points"]:
        st = _state(pt, target_state)
        m = st["mass"]
        sig = sigma_model_at(st, model)
        covered, dm_pt = True, None
        if surf is None:
            ul = _interp(m, ul_x, ul_y)
        else:
            dm_pt = _dm_of_point(pt, dm_extra)
            v = surf(m, dm_pt)
            if v is None:
                covered, ul = False, None
            else:
                ul = float(np.exp(v))
        if covered:
            r = sig / ul if ul > 0 else float("inf")
        else:
            r = None
        params = pt.get("params", {})
        # spectrum_mix stores params lowercase (m1/m2/mu); accept M2/MU too (case-insensitive)
        plc = {k.lower(): v for k, v in params.items()}
        fb, fw, fh = _gauge_fractions(st)
        row = {
            "x": plc.get(xkey.lower()), "y": plc.get(ykey.lower()), "mass": m,
            "wino": fw, "higgsino": fh, "bino": fb,
            "sigma_xbr_fb": sig, "sigma_ul_fb": ul, "r": r,
            "excluded": bool(r is not None and r >= 1.0), "covered": covered,
        }
        if dm_pt is not None:
            row["dm"] = dm_pt
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- selftest
def _selftest():
    fails = []
    # a falling published UL(mass) and a pure-state model
    mass = [100, 200, 300, 400, 500]
    ul = [1000.0, 200.0, 50.0, 15.0, 5.0]            # fb, steeply falling
    hino = {"mass": mass, "sigma_fb": [800.0, 160.0, 40.0, 12.0, 4.0]}   # ~0.8 x UL -> r~0.8
    wino = {"mass": mass, "sigma_fb": [2400.0, 480.0, 120.0, 36.0, 12.0]}  # 3x higgsino

    # (1) ROUND-TRIP IDENTITY: direct model = the published sigma*BR that SET the limit. If the
    #     model sigma*BR equals k x UL, then r == k exactly at every published mass (transform ->
    #     invert). Use k=1 (on-contour) -> r==1 everywhere.
    grid_id = {"points": [
        {"params": {"mu": m, "M2": m}, "charginos": [{"state": "C1", "mass": float(m),
         "wino": 0.0, "higgsino": 1.0, "bino": 0.0}]} for m in mass]}
    model_id = {"mode": "direct", "sigma_xbr_fb": {"mass": mass, "value": ul}}   # == UL
    rows = fold(grid_id, {"mass": mass, "sigma_ul_fb": ul}, model_id, "C1")
    if not all(abs(r["r"] - 1.0) < 1e-9 for r in rows):
        fails.append(f"round-trip identity: r != 1 on the published contour ({[round(r['r'],4) for r in rows]})")
    else:
        print("[selftest] 1 round-trip identity: r == 1 at every published mass  ok")

    # (2) MONOTONICITY: a pure-higgsino model at 0.8x UL -> r ~ 0.8 < 1 (allowed) everywhere;
    #     scaling the model up must raise r monotonically and eventually exclude.
    grid_h = {"points": [
        {"params": {"mu": m, "M2": 9999}, "charginos": [{"state": "C1", "mass": float(m),
         "wino": 0.0, "higgsino": 1.0, "bino": 0.0}]} for m in mass]}
    r_lo = [x["r"] for x in fold(grid_h, {"mass": mass, "sigma_ul_fb": ul},
                                 {"mode": "pure", "refs": {"higgsino": hino}}, "C1")]
    r_hi = [x["r"] for x in fold(grid_h, {"mass": mass, "sigma_ul_fb": ul},
                                 {"mode": "pure", "refs": {"higgsino": hino}, "br": 2.0}, "C1")]
    if not (all(a < 1 for a in r_lo) and all(b > a for a, b in zip(r_lo, r_hi)) and any(b >= 1 for b in r_hi)):
        fails.append(f"monotonicity: r_lo={[round(a,3) for a in r_lo]} r_hi={[round(b,3) for b in r_hi]}")
    else:
        print(f"[selftest] 2 monotonicity: pure-higgsino r~{np.mean(r_lo):.2f}<1; x2 BR raises all + excludes some  ok")

    # (3) COMPOSITION WEIGHTING: at fixed mass, a wino-like state predicts ~3x the higgsino sigma,
    #     so its r is ~3x. A 50/50 mix sits between.
    def r_at(w, h):
        g = {"points": [{"params": {"mu": 300, "M2": 300}, "charginos": [{"state": "C1",
             "mass": 300.0, "wino": w, "higgsino": h, "bino": 0.0}]}]}
        return fold(g, {"mass": mass, "sigma_ul_fb": ul},
                    {"mode": "pure", "refs": {"higgsino": hino, "wino": wino}}, "C1")[0]["r"]
    rh, rw, rm = r_at(0.0, 1.0), r_at(1.0, 0.0), r_at(0.5, 0.5)
    if not (abs(rw / rh - 3.0) < 0.05 and rh < rm < rw):
        fails.append(f"composition weighting: r_higgsino={rh:.3f} r_mix={rm:.3f} r_wino={rw:.3f} (want wino~3x, mix between)")
    else:
        print(f"[selftest] 3 composition: r_higgsino={rh:.2f} < r_mix={rm:.2f} < r_wino={rw:.2f} (~3x)  ok")

    # (4) LOG-INTERP sanity: UL between published nodes must not overshoot linearly.
    v = _interp(250, mass, ul)                        # between 200(=200) and 300(=50)
    if not (50 < v < 200 and abs(v - np.sqrt(200 * 50)) / v < 0.02):    # geometric mean ~100
        fails.append(f"log-interp: UL(250)={v:.1f}, expected ~{np.sqrt(200*50):.1f} (geo mean)")
    else:
        print(f"[selftest] 4 log-interp: UL(250)={v:.1f} ~ geometric mean 100  ok")

    # (5) 2-D UL SURFACE: log-planar surface (linear triangulated interp reproduces a plane
    #     EXACTLY, so any covered query round-trips) tested at interior points AND at a hull
    #     corner (exercises the float-edge snap guard: tree+extra dm sums carry cancellation
    #     noise and published grid points sit exactly on the hull).
    nodes = [(m, d) for m in (100.0, 200.0, 300.0) for d in (0.3, 0.65, 1.0)]

    def ul_plane(m, d):                              # log(UL) planar in (m, dm)
        return float(np.exp(6.0 - 0.012 * m + 0.8 * d))
    surf_spec = {"mass": [n[0] for n in nodes], "dm": [n[1] for n in nodes],
                 "sigma_ul_fb": [ul_plane(*n) for n in nodes]}

    def pt2d(mass, dm_tree):
        return {"params": {"mu": mass, "M2": 5000},
                "charginos": [{"state": "C1", "mass": float(mass) + dm_tree,
                               "wino_U": 0.0, "higgsino_U": 1.0,
                               "wino_V": 0.0, "higgsino_V": 1.0}],
                "neutralinos": [{"state": "N1", "mass": float(mass),
                                 "signed_mass": float(mass),
                                 "bino": 0.0, "wino": 0.0, "higgsino": 1.0}]}
    # queries: two interior + one exact hull corner (m=100 node, dm=0.3 edge via 0.1+0.2)
    queries = [(150.0, 0.2), (250.0, 0.45), (99.9, 0.1)]        # tree dm; +0.2 extra below
    grid2d = {"points": [pt2d(m, t) for m, t in queries]}
    # direct sigma*BR == the planar UL evaluated at each point's own (mass, dm) -> r == 1
    sig_vals = [ul_plane(m + t, t + 0.2) for m, t in queries]
    model2d = {"mode": "direct",
               "sigma_xbr_fb": {"mass": [m + t for m, t in queries], "value": sig_vals}}
    rows2d = fold(grid2d, surf_spec, model2d, "C1", dm_extra=([50, 400], [0.2, 0.2]))
    if not all(r["covered"] and r["r"] is not None and abs(r["r"] - 1.0) < 1e-3 for r in rows2d):
        fails.append("2-D round-trip: "
                     f"{[(None if r['r'] is None else round(r['r'], 5), r['covered']) for r in rows2d]}")
    else:
        print("[selftest] 5 2-D surface: planar round-trip r == 1 (interior + snapped hull corner)  ok")
    rows_out = fold({"points": [pt2d(200, 5.0)]}, surf_spec, model2d, "C1")  # dm=5.2 >> hull
    if not (rows_out[0]["covered"] is False and rows_out[0]["r"] is None
            and rows_out[0]["excluded"] is False):
        fails.append(f"2-D hull honesty: {rows_out[0]}")
    else:
        print("[selftest] 6 2-D hull honesty: off-hull point covered=False, not excluded/allowed  ok")

    if fails:
        for f in fails:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("replane selftest: PASS (round-trip identity, monotonicity, composition weighting, "
          "log-interp, 2-D surface, hull honesty)")
    return 0


# --------------------------------------------------------------------------- render
_TEX_LABEL = {"mu": r"$\mu$ [GeV]", "m2": r"$M_2$ [GeV]", "m1": r"$M_1$ [GeV]",
              "tanb": r"$\tan\beta$", "m_parent": r"$m$ [GeV]", "dm": r"$\Delta m$ [GeV]"}


def render(rows, out_stem, xlabel, ylabel, experiment, no_lint):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mplhep_style as house
    hep = house.apply_style(experiment)
    xlabel = _TEX_LABEL.get(xlabel.lower(), xlabel)
    ylabel = _TEX_LABEL.get(ylabel.lower(), ylabel)
    xs = np.array([r["x"] for r in rows], float)
    ys = np.array([r["y"] for r in rows], float)
    rr = np.array([(r["r"] if r.get("r") is not None else np.nan) for r in rows], float)
    fig, ax = plt.subplots(figsize=(7, 6))
    ux, uy = np.unique(xs), np.unique(ys)
    if len(ux) > 1 and len(uy) > 1:                  # a real grid -> filled r-map + r=1 contour
        R = np.full((len(uy), len(ux)), np.nan)
        for r in rows:
            if r.get("r") is not None:               # uncovered stays NaN -> drawn as 'bad' grey
                R[np.searchsorted(uy, r["y"]), np.searchsorted(ux, r["x"])] = np.log10(max(r["r"], 1e-6))
        cmap = plt.get_cmap("RdBu_r").copy()
        cmap.set_bad("0.85")                         # T4: no-coverage is first-class, not blank
        pcm = ax.pcolormesh(ux, uy, np.ma.masked_invalid(R), cmap=cmap, vmin=-1, vmax=1,
                            shading="nearest")
        fig.colorbar(pcm, ax=ax, label=r"$\log_{10}\, r=\sigma\!\times\!\mathrm{BR}/\sigma_{95}$")
        try:
            cs = ax.contour(ux, uy, 10 ** R, levels=[1.0], colors="k", linewidths=2)
            ax.clabel(cs, fmt={1.0: "excluded (r=1)"}, fontsize=9)
        except Exception:
            pass
    else:
        sc = ax.scatter(xs, ys, c=np.log10(np.clip(rr, 1e-6, None)), cmap="RdBu_r", vmin=-1, vmax=1)
        fig.colorbar(sc, ax=ax, label=r"$\log_{10}\, r$")
    ax.set_xlabel(xlabel); ax.set_ylabel(ylabel)
    if hep is not None:
        try:
            getattr(hep, experiment.lower()).label(ax=ax, data=False, label="reinterpretation", loc=0)
        except Exception:
            pass
    n_exc = int(np.sum(rr[np.isfinite(rr)] >= 1))
    n_cov = int(np.sum(np.isfinite(rr)))
    lines = ["replane (tree-level spectrum + composition fold)",
             "95% CL, CLs; NOT a discovery",
             f"{n_exc}/{n_cov} covered points excluded"]
    if n_cov < len(rr):
        lines.append(f"{len(rr) - n_cov} points outside the published (mass, dm) hull: grey")
    house.smart_annotate(ax, lines, fontsize=9)
    house.tick_hygiene(ax, axr=None)
    house.enforce_lint(fig, where=os.path.basename(out_stem), allow=no_lint)
    for ext in (".pdf", ".png"):
        fig.savefig(out_stem + ext, dpi=200, bbox_inches="tight")
        print(f"wrote {out_stem + ext}")


def cmd_fold(args):
    with open(args.grid) as f:
        grid = json.load(f)
    if "points" not in grid:
        die("--grid must be a spectrum_mix --plane JSON with a 'points' list")
    with open(args.sigma_model) as f:
        model = json.load(f)
    dm_extra = None
    if args.dm_extra_curve:
        dm_extra = _load_curve(args.dm_extra_curve, ykey="value")
    rows = fold(grid, args.ul_curve, model, args.target_state, xkey=args.x, ykey=args.y,
                dm_extra=dm_extra)
    outdir = args.out or os.path.dirname(os.path.abspath(args.grid))
    os.makedirs(outdir, exist_ok=True)
    res = {"tool": "replane", "target_state": args.target_state, "sigma_model_mode": model["mode"],
           "x": args.x, "y": args.y, "n_excluded": int(sum(r["excluded"] for r in rows)),
           "n_covered": int(sum(r.get("covered", True) for r in rows)),
           "n_points": len(rows), "dm_extra_curve": args.dm_extra_curve, "rows": rows,
           "caveats": ["TREE-LEVEL spectrum (spectrum_mix): quote SPheno/SuSpect if mass precision matters",
                       "T3: composition reweighting applied to sigma; acceptance effect NOT re-simulated -- bound or escalate",
                       "R5 validation gate: reproduce >=1 published point before shipping"]}
    outjson = os.path.join(outdir, "replane.json")
    with open(outjson, "w") as f:
        json.dump(res, f, indent=1)
    print(f"replane: {res['n_excluded']}/{res['n_points']} points excluded (r>=1); target={args.target_state}")
    print(f"wrote {outjson}")
    print("R5 GATE (non-negotiable): before shipping, round-trip the paper's own plane / reproduce "
          ">=1 published point within its stated accuracy; record the map + composition caveat (T3).")
    if args.out is not None or args.render:
        render(rows, os.path.join(outdir, "replane"),
               args.x, args.y, args.experiment, args.no_lint)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fold", help="fold a published UL into a new plane via spectrum compositions")
    p.add_argument("--grid", required=True, help="spectrum_mix --plane JSON (the target plane)")
    p.add_argument("--ul-curve", required=True,
                   help="published UL: {mass, sigma_ul_fb} json/2-col, or a 2-D surface "
                        "{mass, dm, sigma_ul_fb} (see docstring)")
    p.add_argument("--dm-extra-curve", default=None,
                   help="2-D mode: additive dm(mass) curve {mass, value} (e.g. the declared "
                        "one-loop intra-multiplet splitting)")
    p.add_argument("--sigma-model", required=True, help="sigma-model.json (pure|direct)")
    p.add_argument("--target-state", required=True, help="C1|C2|N1|N2|... the state the search targets")
    p.add_argument("--x", default="mu"); p.add_argument("--y", default="M2")
    p.add_argument("--out", default=None, help="output dir (also triggers the plot)")
    p.add_argument("--render", action="store_true", help="render even without --out")
    p.add_argument("--experiment", default="ATLAS", choices=["ATLAS", "CMS"])
    p.add_argument("--no-lint", action="store_true")
    p.set_defaults(fn=cmd_fold)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
