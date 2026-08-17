#!/usr/bin/env python
"""spectrum_mix -- TREE-LEVEL EWK-ino masses + COMPOSITIONS (replane spectrum leg, G2d/CR-025).

The spectrum leg of the replane track (workflow/reference/projection-replane.md §Replane): per
target-plane point, the neutralino/chargino masses AND gauge-eigenstate compositions from the
tree-level mixing matrices. Trap T3 is the whole game — a published simplified-model limit
assumes a PURE state (pure higgsino, pure wino); the requested plane (the eval-subject-#7 class:
mu--M2 with M1=M2, tanb=50) breaks that purity, and the per-point wino/bino/higgsino fractions
computed here decide whether the published sigma and A*eps still apply or must be re-weighted.

SCOPE — TREE LEVEL ONLY, and plainly so: loop corrections shift these masses by O(few GeV)
(and the splitting inside a pure wino/higgsino multiplet is ENTIRELY loop-level, ~0.16 GeV for
winos — invisible here). A production replane quotes SPheno/SuSpect (DECLARED, per the spec)
whenever mass precision matters. This tool's job is COMPOSITION + the T3 mixed-state check +
fast per-plane grids, nothing more. Fail-loud; stdlib + numpy only.

Conventions (Martin hep-ph/9709356 §8.2 = the SLHA standard; real CP-conserving parameters):
  mZ = 91.1876, sin2thetaW = 0.2312, mW = mZ*cosW (tree-consistent, 79.95 — NOT the on-shell
  80.377; consistency inside the tree-level matrices beats matching PDG here).
  Neutralinos: basis (bino, wino, higgsino_d, higgsino_u); M_N is real symmetric, so
  numpy.linalg.eigh gives SIGNED eigenvalues directly (a negative eigenvalue = relative CP
  phase of that state; report |m| + the sign) with a real orthogonal N, N M_N N^T = diag.
  Charginos: X = [[M2, sqrt2 mW sin_beta], [sqrt2 mW cos_beta, mu]]; bi-unitary
  diagonalization via SVD (masses = singular values, always >= 0); U mixes the NEGATIVE states
  (wino-, higgsino_d-), V the POSITIVE (wino+, higgsino_u+) — both compositions reported.

Usage:
  spectrum_mix.py --m1 250 --m2 250 --mu 300 --tanb 50 [--json [OUT]]   # one point -> table/JSON
  spectrum_mix.py --plane mu:M2 --m1eqm2 --tanb 50 \\
      --grid "mu=100:500:50,M2=100:500:50" --json out.json   # per-point spectra for a replane grid
  spectrum_mix.py --selftest   # pure-bino/wino/higgsino limits, the T3 mixed point, unitarity
"""
import argparse
import itertools
import json
import math
import sys

try:
    import numpy as np
except ImportError:
    sys.exit("spectrum_mix: numpy not found — run inside the rivet env "
             "(<conda> run -n rivet python spectrum_mix.py ...)")

MZ = 91.1876
SIN2THETAW = 0.2312
SW = math.sqrt(SIN2THETAW)
CW = math.sqrt(1.0 - SIN2THETAW)
MW = MZ * CW                      # tree-consistent W mass, ~79.95 GeV (see docstring)
PARAM_KEYS = ("m1", "m2", "mu", "tanb")


def neutralino_sector(m1, m2, mu, tanb):
    """4x4 tree-level neutralino sector. Returns (states, N) — states sorted by |mass|,
    N the real mixing matrix (rows = mass states) with N M N^T = diag(signed masses)."""
    beta = math.atan(tanb)
    sb, cb = math.sin(beta), math.cos(beta)
    M = np.array([
        [m1,          0.0,         -MZ * SW * cb,  MZ * SW * sb],
        [0.0,         m2,           MZ * CW * cb, -MZ * CW * sb],
        [-MZ * SW * cb, MZ * CW * cb, 0.0,         -mu],
        [MZ * SW * sb, -MZ * CW * sb, -mu,          0.0]])
    vals, vecs = np.linalg.eigh(M)            # signed eigenvalues, orthonormal columns
    order = np.argsort(np.abs(vals))
    vals = vals[order]
    N = vecs[:, order].T                      # rows = mass eigenstates
    resid = np.max(np.abs(N @ M @ N.T - np.diag(vals)))
    scale = max(1.0, float(np.max(np.abs(vals))))
    if resid > 1e-8 * scale:
        sys.exit(f"spectrum_mix: neutralino diagonalization residual {resid:.3e} "
                 f"exceeds 1e-8*{scale:.0f} — refusing to report")
    states = []
    for i in range(4):
        states.append({
            "state": f"N{i + 1}",
            "mass": float(abs(vals[i])),
            "sign": int(math.copysign(1, vals[i])) if vals[i] != 0 else 1,
            "signed_mass": float(vals[i]),
            "bino": float(N[i, 0] ** 2),
            "wino": float(N[i, 1] ** 2),
            "higgsino": float(N[i, 2] ** 2 + N[i, 3] ** 2),
            "N_row": [float(x) for x in N[i]],
        })
    return states, N


def chargino_sector(m2, mu, tanb):
    """2x2 chargino sector via SVD. Returns (states, U, Vh) — states sorted light->heavy;
    U columns / Vh rows (numpy convention) reindexed so index i = mass state i."""
    beta = math.atan(tanb)
    sb, cb = math.sin(beta), math.cos(beta)
    X = np.array([[m2, math.sqrt(2.0) * MW * sb],
                  [math.sqrt(2.0) * MW * cb, mu]])
    U, s, Vh = np.linalg.svd(X)               # s descending
    order = np.argsort(s)                     # ascending: C1 = lighter
    s = s[order]
    U = U[:, order]                           # column i  = negative-state mixing of C_{i+1}
    Vh = Vh[order, :]                         # row i     = positive-state mixing of C_{i+1}
    resid = np.max(np.abs(U.T @ X @ Vh.T - np.diag(s)))
    scale = max(1.0, float(np.max(np.abs(s))))
    if resid > 1e-8 * scale:
        sys.exit(f"spectrum_mix: chargino SVD residual {resid:.3e} "
                 f"exceeds 1e-8*{scale:.0f} — refusing to report")
    states = []
    for i in range(2):
        states.append({
            "state": f"C{i + 1}",
            "mass": float(s[i]),
            "wino_U": float(U[0, i] ** 2), "higgsino_U": float(U[1, i] ** 2),
            "wino_V": float(Vh[i, 0] ** 2), "higgsino_V": float(Vh[i, 1] ** 2),
        })
    return states, U, Vh


def compute_point(m1, m2, mu, tanb):
    if tanb <= 0:
        sys.exit(f"spectrum_mix: tanb must be > 0 (got {tanb})")
    neut, N = neutralino_sector(m1, m2, mu, tanb)
    char, U, Vh = chargino_sector(m2, mu, tanb)
    return {"params": {"m1": m1, "m2": m2, "mu": mu, "tanb": tanb},
            "neutralinos": neut, "charginos": char,
            "_matrices": {"N": N, "U": U, "Vh": Vh}}


def strip_matrices(point):
    return {k: v for k, v in point.items() if k != "_matrices"}


def unitarity_deviation(point):
    """Max deviation from 1 of sum_states |mixing|^2 per GAUGE eigenstate (columns of N;
    U and Vh are orthogonal 2x2 so their columns/rows get the same check)."""
    m = point["_matrices"]
    devs = [np.max(np.abs(np.sum(m["N"] ** 2, axis=0) - 1.0)),
            np.max(np.abs(np.sum(m["U"] ** 2, axis=1) - 1.0)),
            np.max(np.abs(np.sum(m["Vh"] ** 2, axis=0) - 1.0))]
    return float(max(devs))


def format_table(point):
    p = point["params"]
    lines = []
    lines.append(f"tree-level EWK-ino spectrum   mZ={MZ}  sin2thetaW={SIN2THETAW}  mW=mZ*cW={MW:.3f}")
    lines.append(f"params: M1={p['m1']:g}  M2={p['m2']:g}  mu={p['mu']:g}  tanb={p['tanb']:g}"
                 "   [TREE LEVEL — loops shift masses O(few GeV); SPheno/SuSpect when precision matters]")
    lines.append("")
    lines.append(f"  {'state':<6}{'|m| [GeV]':>10}  {'sign':>4}  {'bino':>7}  {'wino':>7}  {'higgsino':>8}")
    for n in point["neutralinos"]:
        lines.append(f"  {n['state']:<6}{n['mass']:>10.2f}  {'+' if n['sign'] > 0 else '-':>4}"
                     f"  {n['bino']:>7.4f}  {n['wino']:>7.4f}  {n['higgsino']:>8.4f}")
    lines.append("")
    lines.append(f"  {'state':<6}{'m [GeV]':>10}  {'wino(U)':>8} {'higgsino(U)':>11}  {'wino(V)':>8} {'higgsino(V)':>11}")
    for c in point["charginos"]:
        lines.append(f"  {c['state']:<6}{c['mass']:>10.2f}  {c['wino_U']:>8.4f} {c['higgsino_U']:>11.4f}"
                     f"  {c['wino_V']:>8.4f} {c['higgsino_V']:>11.4f}")
    return "\n".join(lines)


# ---------------------------------------------------------------- grid mode
def parse_grid(spec):
    """'mu=100:500:50,M2=100:500:50' -> [('mu', [100..500]), ('m2', [100..500])] (stop inclusive)."""
    axes = []
    for part in spec.split(","):
        name, eq, rng = part.partition("=")
        key = name.strip().lower()
        if not eq or key not in PARAM_KEYS:
            sys.exit(f"spectrum_mix: bad grid axis '{part}' — want one of {PARAM_KEYS} as name=start:stop:step")
        try:
            start, stop, step = (float(x) for x in rng.split(":"))
        except ValueError:
            sys.exit(f"spectrum_mix: bad grid range '{rng}' — want start:stop:step")
        if step <= 0 or stop < start:
            sys.exit(f"spectrum_mix: bad grid range '{part}' — need step > 0 and stop >= start")
        n = int(math.floor((stop - start) / step + 1e-9)) + 1
        axes.append((key, [start + k * step for k in range(n)]))
    if len({k for k, _ in axes}) != len(axes):
        sys.exit("spectrum_mix: duplicate axis in --grid")
    return axes


def run_grid(args):
    axes = parse_grid(args.grid)
    axis_names = [k for k, _ in axes]
    plane = None
    if args.plane:
        px, colon, py = args.plane.partition(":")
        px, py = px.strip().lower(), py.strip().lower()
        if not colon or px not in axis_names or py not in axis_names:
            sys.exit(f"spectrum_mix: --plane '{args.plane}' must be x:y with both axes in --grid ({axis_names})")
        plane = {"x": px, "y": py}
    fixed = {}
    for key in PARAM_KEYS:
        flag = getattr(args, key)
        if flag is not None:
            if key in axis_names:
                sys.exit(f"spectrum_mix: {key} is both a grid axis and a fixed flag — pick one")
            fixed[key] = flag
    if args.m1eqm2:
        if "m1" in axis_names or "m1" in fixed:
            sys.exit("spectrum_mix: --m1eqm2 conflicts with an explicit m1 (flag or grid axis)")
    missing = [k for k in PARAM_KEYS
               if k not in axis_names and k not in fixed and not (k == "m1" and args.m1eqm2)]
    if missing:
        sys.exit(f"spectrum_mix: unresolved parameter(s) {missing} — supply as flag, grid axis, or --m1eqm2")
    points = []
    for combo in itertools.product(*[vals for _, vals in axes]):
        params = dict(fixed)
        params.update(dict(zip(axis_names, combo)))
        if args.m1eqm2:
            params["m1"] = params["m2"]
        points.append(strip_matrices(compute_point(**params)))
    out = {"meta": {"tool": "spectrum_mix", "scope": "TREE-LEVEL (see docstring)",
                    "mZ": MZ, "sin2thetaW": SIN2THETAW, "mW": MW,
                    "plane": plane, "grid": args.grid, "m1eqm2": bool(args.m1eqm2),
                    "fixed": fixed, "n_points": len(points),
                    "ordering": "itertools.product over --grid axes as declared (last axis fastest)"},
           "points": points}
    if args.json is None or args.json == "-":
        print(json.dumps(out, indent=1))
    else:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=1)
        print(f"spectrum_mix: wrote {len(points)} points -> {args.json}")


# ---------------------------------------------------------------- selftest
def selftest():
    print(f"spectrum_mix --selftest   (mZ={MZ}, sin2thetaW={SIN2THETAW}, mW=mZ*cW={MW:.4f}, tree level)")
    failures = []

    def check(label, cond, detail):
        print(f"  [{'PASS' if cond else 'FAIL'}] {label}: {detail}")
        if not cond:
            failures.append(label)

    # (a) PURE-BINO limit
    print("\n(a) PURE-BINO: M1=100, M2=mu=10000, tanb=10")
    pa = compute_point(100.0, 10000.0, 10000.0, 10.0)
    n1 = pa["neutralinos"][0]
    check("m(N1)=M1 within 1%", abs(n1["mass"] - 100.0) <= 1.0,
          f"|m|={n1['mass']:.4f} GeV vs 100 (tol 1.0)")
    check("bino fraction > 99%", n1["bino"] > 0.99,
          f"bino={n1['bino']:.6f} wino={n1['wino']:.2e} higgsino={n1['higgsino']:.2e}")

    # (b) PURE-WINO multiplet
    print("\n(b) PURE-WINO: M2=150, M1=mu=10000, tanb=10")
    pb = compute_point(10000.0, 150.0, 10000.0, 10.0)
    n1, c1 = pb["neutralinos"][0], pb["charginos"][0]
    check("m(C1)=M2 within 1%", abs(c1["mass"] - 150.0) <= 1.5,
          f"m={c1['mass']:.4f} GeV vs 150 (tol 1.5)")
    check("m(N1)=M2 within 1%", abs(n1["mass"] - 150.0) <= 1.5,
          f"|m|={n1['mass']:.4f} GeV vs 150 (tol 1.5)")
    check("wino multiplet near-degenerate", abs(c1["mass"] - n1["mass"]) < 1.0,
          f"|m(C1)-m(N1)|={abs(c1['mass'] - n1['mass']):.4f} GeV (tol 1.0; the true splitting is loop-level)")
    check("N1 wino fraction > 99%", n1["wino"] > 0.99, f"wino={n1['wino']:.6f}")
    check("C1 wino fraction > 99% (U and V)", min(c1["wino_U"], c1["wino_V"]) > 0.99,
          f"wino_U={c1['wino_U']:.6f} wino_V={c1['wino_V']:.6f}")

    # (c) PURE-HIGGSINO multiplet
    print("\n(c) PURE-HIGGSINO: mu=200, M1=M2=10000, tanb=10")
    pc = compute_point(10000.0, 10000.0, 200.0, 10.0)
    n1, n2, c1 = pc["neutralinos"][0], pc["neutralinos"][1], pc["charginos"][0]
    check("m(N1)=mu within 1%", abs(n1["mass"] - 200.0) <= 2.0,
          f"|m|={n1['mass']:.4f} (sign {n1['sign']:+d}) vs 200 (tol 2.0)")
    check("m(N2)=mu within 1%", abs(n2["mass"] - 200.0) <= 2.0,
          f"|m|={n2['mass']:.4f} (sign {n2['sign']:+d}) vs 200 (tol 2.0)")
    check("m(C1)=mu within 1%", abs(c1["mass"] - 200.0) <= 2.0,
          f"m={c1['mass']:.4f} vs 200 (tol 2.0)")
    check("N1,N2 higgsino fractions > 99%", min(n1["higgsino"], n2["higgsino"]) > 0.99,
          f"h(N1)={n1['higgsino']:.6f} h(N2)={n2['higgsino']:.6f}")
    check("C1 higgsino fraction > 99% (U and V)", min(c1["higgsino_U"], c1["higgsino_V"]) > 0.99,
          f"higgsino_U={c1['higgsino_U']:.6f} higgsino_V={c1['higgsino_V']:.6f}")

    # (d) the P7 point class — the T3 trap-catalogue claim, checked with numbers
    print("\n(d) P7/T3 MIXED point: M1=M2=250, mu=300, tanb=50 "
          "(eval subject #7's plane class: mu--M2, M1=M2, tanb=50)")
    pd = compute_point(250.0, 250.0, 300.0, 50.0)
    print("\n" + format_table(strip_matrices(pd)) + "\n")
    light = [pd["neutralinos"][0], pd["neutralinos"][1]]
    for n in light:
        fmax = max(n["bino"], n["wino"], n["higgsino"])
        check(f"{n['state']} MIXED (no composition > 90%)", fmax < 0.90,
              f"max fraction={fmax:.4f} (bino={n['bino']:.4f} wino={n['wino']:.4f} higgsino={n['higgsino']:.4f})")
    c1 = pd["charginos"][0]
    cmax = max(c1["wino_U"], c1["higgsino_U"], c1["wino_V"], c1["higgsino_V"])
    check("C1 MIXED (no composition > 90%)", cmax < 0.90,
          f"max fraction={cmax:.4f} (wino_U={c1['wino_U']:.4f} higgsino_U={c1['higgsino_U']:.4f} "
          f"wino_V={c1['wino_V']:.4f} higgsino_V={c1['higgsino_V']:.4f})")

    # (e) unitarity trace check per gauge eigenstate, on every point above
    print("\n(e) unitarity: sum over mass states of |mixing|^2 = 1 per gauge eigenstate (tol 1e-6)")
    for tag, pt in (("a", pa), ("b", pb), ("c", pc), ("d", pd)):
        dev = unitarity_deviation(pt)
        check(f"point ({tag}) gauge-eigenstate trace", dev < 1e-6, f"max |sum-1| = {dev:.2e}")

    print()
    if failures:
        print(f"SELFTEST FAIL — {len(failures)} check(s) failed: {failures}")
        return 1
    print("SELFTEST PASS — all checks passed (pure limits, T3 mixed point, unitarity)")
    return 0


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(
        description="tree-level EWK-ino spectrum + composition (replane leg; see module docstring)")
    ap.add_argument("--m1", type=float, default=None)
    ap.add_argument("--m2", type=float, default=None)
    ap.add_argument("--mu", type=float, default=None)
    ap.add_argument("--tanb", type=float, default=None)
    ap.add_argument("--json", nargs="?", const="-", default=None, metavar="OUT",
                    help="JSON output; no value = stdout, value = file path")
    ap.add_argument("--plane", default=None, metavar="X:Y",
                    help="grid mode: name the plane axes, e.g. mu:M2 (both must be --grid axes)")
    ap.add_argument("--grid", default=None, metavar="SPEC",
                    help='grid mode: "mu=100:500:50,M2=100:500:50" (stop inclusive)')
    ap.add_argument("--m1eqm2", action="store_true", help="tie M1 := M2 at every point")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())
    if args.grid:
        run_grid(args)
        return
    if args.plane:
        sys.exit("spectrum_mix: --plane only makes sense with --grid")
    # single point
    if args.m1eqm2:
        if args.m1 is not None:
            sys.exit("spectrum_mix: --m1eqm2 conflicts with an explicit --m1")
        if args.m2 is None:
            sys.exit("spectrum_mix: --m1eqm2 needs --m2")
        args.m1 = args.m2
    missing = [k for k in PARAM_KEYS if getattr(args, k) is None]
    if missing:
        sys.exit(f"spectrum_mix: missing required parameter(s): {missing} (or use --grid / --selftest)")
    point = compute_point(args.m1, args.m2, args.mu, args.tanb)
    dev = unitarity_deviation(point)
    if dev > 1e-6:
        sys.exit(f"spectrum_mix: unitarity violated (max dev {dev:.2e}) — refusing to report")
    out = strip_matrices(point)
    if args.json is not None:
        payload = {"meta": {"tool": "spectrum_mix", "scope": "TREE-LEVEL (see docstring)",
                            "mZ": MZ, "sin2thetaW": SIN2THETAW, "mW": MW}, **out}
        if args.json == "-":
            print(json.dumps(payload, indent=1))
        else:
            with open(args.json, "w") as f:
                json.dump(payload, f, indent=1)
            print(f"spectrum_mix: wrote 1 point -> {args.json}")
    else:
        print(format_table(out))


if __name__ == "__main__":
    main()
