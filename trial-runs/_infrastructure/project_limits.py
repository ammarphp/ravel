#!/usr/bin/env python
"""project_limits -- LUMINOSITY PROJECTION of counting limits (G2c, CR-024; roadmap W3/C12).

The forum-standard product ("what would this analysis exclude with Run-3 / HL-LHC data?"),
EXPECTED-ONLY by construction. This tool never invents statistics: it transforms the per-SR
inputs and delegates every limit to the house engine (`pyhf_exclude.py counting`) on the
projected background-Asimov — one statistical engine in this repo, ever.

Scaling, per SR, with f = L2/L1: s' = s*f, b' = b*f, obs' := b' (Asimov ⇒ expected-only), and
the background uncertainty under a DECLARED scenario:
    stat    δb' = δb·sqrt(f)   (uncertainty is statistics-dominated and improves)
    syst    δb' = δb·f         (relative systematic floor is constant — usually the honest one)
    frozen  δb' = δb           (absolute uncertainty unchanged — the optimistic bound)
The three scenarios BRACKET reality; default reports ALL THREE (the spread IS the honest band).
Labels on every output: `projection, expected-only, bkg-scaling=<scenario>`.

Identity gate (run --selftest): at f=1 the projected expected limit must equal the engine's
expected limit on the ORIGINAL inputs (same Asimov construction) — tolerance 3% (measured
bracket-grid resolution). The selftest uses the benchmark squark case's committed sr_yields.

LIKELIHOOD mode (the second half of the spec, `workflow/reference/projection-replane.md`):
the published HistFactory workspace is the paper's own statistical model; project it by
transforming the PATCHED workspace (signal applied first — patch yields are absolute and
must scale with f too) and delegating, unchanged, to `pyhf_exclude.py likelihood` (the
projected workspace passes as --bkg with an EMPTY patch). Per-modifier handling, with
g_sys = {stat: 1/sqrt(f), syst: 1, frozen: 1/f} and g_stat = {stat,syst: 1/sqrt(f), frozen: 1/f}
acting on RELATIVE uncertainties:
    sample data, observations   x f          (yields and data grow with luminosity)
    histosys hi/lo              f*(nom + (orig-nom)*g_sys)   (absolute template shifts)
    normsys hi/lo               1 + (orig-1)*g_sys           (relative by construction)
    staterror / shapesys        x f*g_stat   (MC-template stats assumed to grow with lumi
                                             except 'frozen': absolute unchanged)
    lumi sigmas                 x g_sys      (relative; inert when the param is fixed)
    normfactor / shapefactor    untouched    (free parameters)
Observations scale as f*data: with CR templates and CR data scaled together the profiled
background normalizations reproduce the Run-2 fit, which is the likelihood-mode analog of
the counting mode's obs := b Asimov; only the EXPECTED (median + bands) limit is quoted —
at f != 1 the 'observed' output is a scaled-data proxy and is labeled as such, never
delivered. Identity gate: at f=1 the transform is the exact identity (g(1)=1 for every
modifier), asserted bit-for-bit in --selftest.

Usage:
  project_limits.py counting --srs sr_yields.json --lumi-factor 2.88 \
      [--bkg-scaling all|stat|syst|frozen] [--sigma-scale K] [--combined] --out DIR
  project_limits.py likelihood --bkg bkg_only.json --patchset patchset.json \
      --lumi-factor 2.857 [--bkg-scaling all|stat|syst|frozen] \
      [--patch-name NAME ... | --all-patches] [--workers N] --out DIR
  project_limits.py --selftest
"""
import argparse
import copy
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
CONDA = os.path.join(REPO, "stages/01-event-generation/build/tools/miniforge3/bin/conda")

SCENARIOS = {"stat": lambda db, f: db * (f ** 0.5),
             "syst": lambda db, f: db * f,
             "frozen": lambda db, f: db}


def project_srs(srs, f, scenario):
    out = []
    for r in srs:
        q = copy.deepcopy(r)
        q["s"] = r["s"] * f
        q["b"] = r["b"] * f
        q["db"] = SCENARIOS[scenario](r["db"], f)
        q["n"] = q["b"]                     # Asimov: observed := projected background
        q["_projection"] = {"lumi_factor": f, "bkg_scaling": scenario,
                            "note": "expected-only; obs set to the projected background"}
        out.append(q)
    return out


def run_engine(srs_path, outdir, sigma_scale=None, combined=False):
    cmd = [CONDA, "run", "-n", "rivet", "python", os.path.join(HERE, "pyhf_exclude.py"),
           "counting", "--srs", srs_path, "--out", outdir, "--label", "projection"]
    if sigma_scale:
        cmd += ["--sigma-scale", str(sigma_scale)]
    if combined:
        cmd += ["--combined"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        sys.exit(f"project_limits: engine failed:\n{r.stderr[-800:]}")
    return json.load(open(os.path.join(outdir, "exclusion.json")))


def _limits(excl):
    """The engine's exclusion.json: exp_limits = the 5-point band [-2s,-1s,med,+1s,+2s];
    the projection quotes the MEDIAN expected. obs_limit exists but on an Asimov input it
    coincides with the median by construction (we still prefer the explicit expected)."""
    if "exp_limits" in excl and len(excl["exp_limits"]) == 5:
        return float(excl["exp_limits"][2])
    if "obs_limit" in excl:
        return float(excl["obs_limit"])
    raise KeyError(f"no expected limit in exclusion.json keys={list(excl)[:8]}")


def cmd_counting(args):
    srs = json.load(open(args.srs))
    os.makedirs(args.out, exist_ok=True)
    scenarios = list(SCENARIOS) if args.bkg_scaling == "all" else [args.bkg_scaling]
    results = {"schema_version": 1, "mode": "counting-projection",
               "inputs": os.path.relpath(args.srs, REPO) if args.srs.startswith(REPO) else args.srs,
               "lumi_factor": args.lumi_factor, "stat_mode": "projection-expected-only",
               "scenarios": {}}
    for sc in scenarios:
        proj = project_srs(srs, args.lumi_factor, sc)
        p = os.path.join(args.out, f"sr_yields_proj_{sc}.json")
        json.dump(proj, open(p, "w"), indent=1)
        excl = run_engine(p, os.path.join(args.out, f"pyhf_{sc}"),
                          sigma_scale=args.sigma_scale, combined=args.combined)
        mu = _limits(excl)
        results["scenarios"][sc] = {"mu95_expected": mu, "engine_output": f"pyhf_{sc}/exclusion.json"}
        print(f"  scenario {sc:6s}: projected expected mu95 = {mu:.4g}")
    json.dump(results, open(os.path.join(args.out, "projection.json"), "w"), indent=1)
    print(f"wrote {os.path.join(args.out, 'projection.json')}")
    print("LABEL (binding): projection, EXPECTED-ONLY, bracketing scenarios "
          f"{scenarios} — never quote a single scenario without the spread.")


# --------------------------------------------------------------------------- #
# likelihood mode (HistFactory workspace projection)
# --------------------------------------------------------------------------- #
GSYS = {"stat": lambda f: f ** -0.5, "syst": lambda f: 1.0, "frozen": lambda f: 1.0 / f}
GSTAT = {"stat": lambda f: f ** -0.5, "syst": lambda f: f ** -0.5, "frozen": lambda f: 1.0 / f}


def project_workspace(spec, f, scenario):
    """Transform a (PATCHED) HistFactory workspace to luminosity L2 = f*L1.

    Per-modifier handling per the module docstring; the signal sample (already patched
    in) is transformed by the same rules — its nominal scales with f, mu_SIG (normfactor)
    stays free, so mu95 keeps meaning 'multiples of the nominal model cross-section'."""
    g_sys, g_stat = GSYS[scenario](f), GSTAT[scenario](f)
    ws = copy.deepcopy(spec)
    for ch in ws["channels"]:
        for s in ch["samples"]:
            nom = list(s["data"])
            s["data"] = [v * f for v in nom]
            for m in s.get("modifiers", []):
                t, d = m["type"], m.get("data")
                if t == "histosys":
                    for k in ("hi_data", "lo_data"):
                        d[k] = [f * (n + (o - n) * g_sys) for n, o in zip(nom, d[k])]
                elif t == "normsys":
                    d["hi"] = 1.0 + (d["hi"] - 1.0) * g_sys
                    d["lo"] = 1.0 + (d["lo"] - 1.0) * g_sys
                elif t in ("staterror", "shapesys"):
                    m["data"] = [v * f * g_stat for v in d]
                # lumi: measurement-level sigmas below; normfactor/shapefactor: free
    for obs in ws.get("observations", []):
        obs["data"] = [v * f for v in obs["data"]]
    for meas in ws.get("measurements", []):
        for par in meas["config"].get("parameters", []):
            if par.get("name") == "lumi" and "sigmas" in par:
                par["sigmas"] = [sg * g_sys for sg in par["sigmas"]]
    return ws


_PATCH_EXTRACT = r"""
import json, sys
import jsonpatch
bkg, patchset_path, outdir = sys.argv[1], sys.argv[2], sys.argv[3]
names = sys.argv[4:]
bkg = json.load(open(bkg))
ps = json.load(open(patchset_path))
wrote = []
for p in ps["patches"]:
    name = p["metadata"]["name"]
    if names and name not in names:
        continue
    spec = jsonpatch.apply_patch(bkg, p["patch"])
    out = f"{outdir}/patched_{name}.json"
    json.dump(spec, open(out, "w"))
    wrote.append(name)
print(json.dumps(wrote))
"""


def extract_patched(bkg_path, patchset_path, outdir, names=None):
    """Apply signal patches (jsonpatch lives in the rivet env) -> patched_<name>.json."""
    os.makedirs(outdir, exist_ok=True)
    helper = os.path.join(outdir, "_extract_patches.py")
    open(helper, "w").write(_PATCH_EXTRACT)
    cmd = [CONDA, "run", "-n", "rivet", "python", helper,
           bkg_path, patchset_path, outdir] + (names or [])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        sys.exit(f"project_limits: patch extraction failed:\n{r.stderr[-800:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def _point_meta(name):
    """MGPy8EG_A14N23LO_HH_dM0p5_150p0 -> (dM=0.5, mH=150.0); None where unparseable."""
    import re
    m = re.search(r"dM(\d+(?:p\d+)?)_(\d+(?:p\d+)?)$", name)
    if not m:
        return None, None
    return (float(m.group(1).replace("p", ".")), float(m.group(2).replace("p", ".")))


def run_engine_likelihood(ws_path, nopatch_path, outdir, label):
    cmd = [CONDA, "run", "-n", "rivet", "python", os.path.join(HERE, "pyhf_exclude.py"),
           "likelihood", "--bkg", ws_path, "--patch", nopatch_path,
           "--out", outdir, "--label", label]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        return {"error": r.stderr[-500:]}
    return json.load(open(os.path.join(outdir, "exclusion.json")))


def cmd_likelihood(args):
    from concurrent.futures import ThreadPoolExecutor
    os.makedirs(args.out, exist_ok=True)
    names = None if args.all_patches else args.patch_name
    patched_dir = os.path.join(args.out, "patched")
    wrote = extract_patched(args.bkg, args.patchset, patched_dir, names)
    if not wrote:
        sys.exit("project_limits: no patches matched")
    nopatch = os.path.join(args.out, "nopatch.json")
    json.dump([], open(nopatch, "w"))
    scenarios = list(SCENARIOS) if args.bkg_scaling == "all" else [args.bkg_scaling]
    f = args.lumi_factor

    jobs = []
    for name in wrote:
        spec = json.load(open(os.path.join(patched_dir, f"patched_{name}.json")))
        for sc in scenarios:
            ws = project_workspace(spec, f, sc)
            wsp = os.path.join(args.out, f"ws_{name}_{sc}.json")
            json.dump(ws, open(wsp, "w"))
            jobs.append((name, sc, wsp))

    def one(job):
        name, sc, wsp = job
        excl = run_engine_likelihood(
            wsp, nopatch, os.path.join(args.out, f"pyhf_{name}_{sc}"),
            f"projection f={f:g} {sc}")
        dm, mh = _point_meta(name)
        rec = {"name": name, "dM_GeV": dm, "mH_GeV": mh, "scenario": sc,
               "lumi_factor": f}
        if "error" in excl:
            rec["error"] = excl["error"]
            print(f"  ENGINE FAIL {name} {sc}: {excl['error'][:120]}", flush=True)
        else:
            rec["exp_limits"] = excl["exp_limits"]
            rec["mu95_expected"] = float(excl["exp_limits"][2])
            rec["obs_limit_scaled_data_proxy"] = excl.get("obs_limit")
            print(f"  {name} {sc}: expected mu95 = {rec['mu95_expected']:.4g}", flush=True)
        return rec

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        points = list(ex.map(one, jobs))

    results = {"schema_version": 1, "mode": "likelihood-projection",
               "inputs": {"bkg": args.bkg, "patchset": args.patchset},
               "lumi_factor": f, "stat_mode": "projection-expected-only",
               "bkg_scaling": scenarios, "n_points": len(wrote),
               "modifier_handling": "see module docstring (g_sys/g_stat per scenario)",
               "points": points}
    outp = os.path.join(args.out, "projection.json")
    json.dump(results, open(outp, "w"), indent=1)
    n_err = sum(1 for p in points if "error" in p)
    print(f"wrote {outp}  ({len(points)} point-scenario records, {n_err} engine failures)")
    print(f"LABEL (binding): projection, EXPECTED-ONLY, f={f:g}, bracketing scenarios "
          f"{scenarios} — never quote a single scenario without the spread; the "
          f"'observed' field is a scaled-data proxy, never deliverable.")
    if n_err:
        sys.exit(1)


def _toy_spec():
    """Hermetic 1-channel toy workspace exercising every handled modifier type."""
    return {
        "channels": [{"name": "SR", "samples": [
            {"name": "bkg", "data": [50.0, 30.0], "modifiers": [
                {"name": "lumi", "type": "lumi", "data": None},
                {"name": "staterror_SR", "type": "staterror", "data": [2.0, 1.5]},
                {"name": "norm_bkg", "type": "normsys",
                 "data": {"hi": 1.10, "lo": 0.90}},
                {"name": "shape_bkg", "type": "histosys",
                 "data": {"hi_data": [55.0, 31.0], "lo_data": [46.0, 29.0]}}]},
            {"name": "sig", "data": [8.0, 6.0], "modifiers": [
                {"name": "lumi", "type": "lumi", "data": None},
                {"name": "mu_SIG", "type": "normfactor", "data": None}]}]}],
        "observations": [{"name": "SR", "data": [50.0, 30.0]}],
        "measurements": [{"name": "meas", "config": {"poi": "mu_SIG", "parameters": [
            {"name": "lumi", "auxdata": [1.0], "sigmas": [0.02],
             "bounds": [[0.9, 1.1]], "inits": [1.0]}]}}],
        "version": "1.0.0",
    }


def _selftest_likelihood():
    """f=1 exact identity + f=4 scenario ordering on the hermetic toy (engine-backed)."""
    import tempfile
    spec = _toy_spec()
    if project_workspace(spec, 1.0, "stat") != spec or \
       project_workspace(spec, 1.0, "syst") != spec or \
       project_workspace(spec, 1.0, "frozen") != spec:
        print("[selftest-lh] f=1 identity: FAIL (transform not exact at f=1)")
        return 1
    print("[selftest-lh] f=1 identity: ok (bit-exact for all three scenarios)")
    # spot-check the documented algebra at f=4
    w4 = project_workspace(spec, 4.0, "syst")
    b = w4["channels"][0]["samples"][0]
    checks = [
        abs(b["data"][0] - 200.0) < 1e-12,                        # nominal x f
        abs(b["modifiers"][1]["data"][0] - 4.0) < 1e-12,          # staterror x f/sqrt(f)=x2
        abs(b["modifiers"][2]["data"]["hi"] - 1.10) < 1e-12,      # normsys unchanged (syst)
        abs(b["modifiers"][3]["data"]["hi_data"][0] - 220.0) < 1e-12,  # histosys f*(nom+dev)
        abs(w4["observations"][0]["data"][0] - 200.0) < 1e-12,
    ]
    w4s = project_workspace(spec, 4.0, "stat")
    checks += [
        abs(w4s["channels"][0]["samples"][0]["modifiers"][2]["data"]["hi"]
            - (1.0 + 0.10 * 0.5)) < 1e-12,                        # normsys tightened sqrt(f)
        abs(w4s["measurements"][0]["config"]["parameters"][0]["sigmas"][0]
            - 0.01) < 1e-12,                                      # lumi sigma x 1/sqrt(f)
    ]
    w4f = project_workspace(spec, 4.0, "frozen")
    checks += [
        abs(w4f["channels"][0]["samples"][0]["modifiers"][1]["data"][0] - 2.0) < 1e-12,
    ]                                                             # staterror abs unchanged
    if not all(checks):
        print(f"[selftest-lh] algebra spot-checks: FAIL ({checks})")
        return 1
    print("[selftest-lh] algebra spot-checks: ok (9 documented-transform assertions)")
    with tempfile.TemporaryDirectory() as td:
        nopatch = os.path.join(td, "nopatch.json")
        json.dump([], open(nopatch, "w"))
        mus = {}
        for sc in SCENARIOS:
            ws = project_workspace(spec, 4.0, sc)
            wsp = os.path.join(td, f"ws_{sc}.json")
            json.dump(ws, open(wsp, "w"))
            excl = run_engine_likelihood(wsp, nopatch, os.path.join(td, sc), f"toy {sc}")
            if "error" in excl:
                print(f"[selftest-lh] engine FAIL ({sc}): {excl['error'][:200]}")
                return 1
            mus[sc] = float(excl["exp_limits"][2])
        ok = mus["frozen"] <= mus["stat"] <= mus["syst"] * 1.001
        print(f"[selftest-lh] f=4 ordering: frozen={mus['frozen']:.4g} "
              f"stat={mus['stat']:.4g} syst={mus['syst']:.4g}  {'ok' if ok else 'FAIL'}")
        return 0 if ok else 1


def _selftest():
    import tempfile
    srs_path = os.path.join(
        REPO, "trial-runs/2026-06-08_ATLAS_2016_I1458270_squark-pair/outputs/sr_yields_fitted.json")
    if not os.path.exists(srs_path):
        print(f"SELFTEST SKIP: benchmark inputs not on disk ({srs_path})", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as td:
        # reference: the engine's own expected limit on the ORIGINAL inputs
        ref = run_engine(srs_path, os.path.join(td, "ref"), sigma_scale=0.862)
        mu_ref = _limits(ref)
        # f=1 projection must reproduce it (same Asimov construction)
        ns = argparse.Namespace(srs=srs_path, out=os.path.join(td, "proj"),
                                lumi_factor=1.0, bkg_scaling="syst",
                                sigma_scale=0.862, combined=False)
        srs = json.load(open(srs_path))
        proj = project_srs(srs, 1.0, "syst")
        p = os.path.join(td, "proj_srs.json")
        os.makedirs(os.path.join(td, "proj"), exist_ok=True)
        json.dump(proj, open(p, "w"), indent=1)
        excl = run_engine(p, os.path.join(td, "proj"), sigma_scale=0.862)
        mu_f1 = _limits(excl)
        rel = abs(mu_f1 - mu_ref) / mu_ref
        # identity holds ANALYTICALLY (pyhf's expected band is built from the bkg-only Asimov,
        # independent of obs); the residual is the engine's mu-bracketing grid landing on
        # different scan points when obs changes -> interpolation noise, measured 2.3% on the
        # benchmark case. Tolerance 3% = bracket resolution, not statistics.
        print(f"[selftest] f=1 identity: projected {mu_f1:.4g} vs engine expected {mu_ref:.4g} "
              f"(rel {100*rel:.2f}%, bracket-grid resolution)  {'ok' if rel < 0.03 else 'FAIL'}")
        # monotonicity: f=4 must improve the limit; the three scenarios must order
        # frozen <= stat <= syst (more uncertainty growth = weaker limit)
        mus = {}
        for sc in SCENARIOS:
            proj4 = project_srs(srs, 4.0, sc)
            p4 = os.path.join(td, f"proj4_{sc}.json")
            json.dump(proj4, open(p4, "w"), indent=1)
            mus[sc] = _limits(run_engine(p4, os.path.join(td, f"p4_{sc}"), sigma_scale=0.862))
        print(f"[selftest] f=4: frozen={mus['frozen']:.4g} stat={mus['stat']:.4g} "
              f"syst={mus['syst']:.4g} (all < f=1 {mu_ref:.4g})")
        ok2 = (mus["frozen"] <= mus["stat"] <= mus["syst"] * 1.001) and all(
            m < mu_ref for m in mus.values())
        print(f"[selftest] ordering + improvement: {'ok' if ok2 else 'FAIL'}")
        if rel < 0.03 and ok2:
            print("project_limits selftest: PASS (identity, ordering, improvement)")
            return 0
        return 1


def main():
    if "--selftest" in sys.argv:
        rc_lh = _selftest_likelihood()
        rc_ct = _selftest()
        sys.exit(rc_lh or rc_ct)
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("counting")
    p.add_argument("--srs", required=True)
    p.add_argument("--lumi-factor", type=float, required=True, help="f = L2/L1")
    p.add_argument("--bkg-scaling", choices=["all"] + list(SCENARIOS), default="all")
    p.add_argument("--sigma-scale", type=float, default=None)
    p.add_argument("--combined", action="store_true")
    p.add_argument("--out", required=True)
    q = sub.add_parser("likelihood")
    q.add_argument("--bkg", required=True, help="background-only HistFactory JSON")
    q.add_argument("--patchset", required=True, help="pyhf patchset JSON (signal points)")
    q.add_argument("--patch-name", action="append", default=[],
                   help="project only these patch names (repeatable)")
    q.add_argument("--all-patches", action="store_true")
    q.add_argument("--lumi-factor", type=float, required=True, help="f = L2/L1")
    q.add_argument("--bkg-scaling", choices=["all"] + list(SCENARIOS), default="all")
    q.add_argument("--workers", type=int, default=6)
    q.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.cmd == "likelihood":
        if not args.all_patches and not args.patch_name:
            ap.error("likelihood: give --patch-name (repeatable) or --all-patches")
        cmd_likelihood(args)
    else:
        cmd_counting(args)


if __name__ == "__main__":
    main()
