#!/usr/bin/env python
"""Outer loop over a GRID of model points -> the exclusion CONTOUR (what RRR actually produces).

THE CORRECTED MENTAL MODEL (read workflow/steps/08-scan.md). The mapyde paper (arXiv:2306.11055) never
reports a single tested point as a result. Every headline figure -- Fig 3 (slepton-bino), Fig 6/7
(slepton-wino-bino), Fig 8 (Higgsino), Fig 10 (pMSSM) -- is a GRID SCAN: a regular lattice of model
points, each run through the full pipeline, whose per-point 95% CL limits mu95 are interpolated into an
exclusion CONTOUR in the mass plane. The paper's own words: "we generate a grid of Higgsino model
points to reproduce the ATLAS results ... the mapyde exclusion contour follows the corresponding ATLAS
contour" (Sec. 3.3); the validation figure is "the relative difference in the limits on the SUSY signal
strength mu_SUSY, between mapyde and ATLAS results" (Fig 3/8 caption).

TWO SPACES, do not conflate them (this was the conceptual error this tool fixes):
  * kinematic-observable space -- WITHIN one model point, the generated events ARE a distribution
    (m_T2, M_ll, MET, ...). steps 3-4 bin that distribution into signal regions. The pipeline is needed
    precisely to turn the per-event distribution into per-SR yields. (This answers "shouldn't there be
    a distribution?" -- yes, here.)
  * model-parameter (mass) space -- ONE pipeline run = ONE point here, collapsing to ONE number: mu95,
    the 95% CL upper limit on the signal strength. excluded iff mu95 < 1.
This orchestrator is the layer ABOVE the steps-1..7 pipeline: it materializes the grid in mass space,
runs/harvests each point, and assembles `scan.json` -- the (m_parent, m_lsp, Delta m, mu95_obs,
mu95_exp, excluded) table that `scan_contour.py` interpolates into the contour. A single-point run
(e.g. mass_plane_overlay.py's star-on-published-contour) is a UNIT within a scan / a sanity check, NOT
the deliverable. For a model ATLAS already published, the published contour answers a single point with
no pipeline at all; the harness earns its keep by (a) REPRODUCING that contour (validation) or
(b) producing a NEW contour for a model ATLAS never considered (reinterpretation).

Subcommands (stdlib only; fail-loud; resumable):
  plan      <spec.json>                 enumerate points; write each point's run-dir skeleton + TOML;
                                        write <scandir>/scan_manifest.json; print the launch plan
  status    <scandir>                   per-point status (done/running/failed/pending) from run dirs
  assemble  <scandir> [--out PATH]      harvest each done point's result.json -> scan.json (+ coverage)
            [--nlo-renorm slepton]      ... and re-normalize the limits from the flat LO k-factor to
                                        the per-mass NLO+NLL k(m) (post-hoc, no regeneration): each
                                        point stores mu95_obs_lo + k_nlo; mu95_obs/exp/band are
                                        replaced by mu95 x flat_k/k(m); sigma_ref_fb is scaled by
                                        k(m)/flat_k so sigma_UL = mu95 x sigma_ref (the difference
                                        map's input) is INVARIANT. Fails loud if k is unavailable.
  rebase    <scandir> --process slepton rebase the assembled+renormed scan.json onto the PUBLISHED
                                        inclusive model-sigma basis (mu95 -> mu_SUSY; sigma_ref_fb :=
                                        sigma_model^WG). REQUIRED before any sigma-UL comparison with
                                        the experiment's per-point UL grid: the sample sigma_ref is
                                        the TAGGED-SUBSET sigma, the published UL is on the INCLUSIVE
                                        model sigma -- different bases (see cmd_rebase docstring).
  launch    <scandir> --max N [--go]    background up to N pending runs via run-pipeline.sh (dry without --go)

GRID SPEC (JSON). Exactly one of points/line/grid:
  {
    "name": "slepton-bino-fig3-coarse",
    "model": "slepton-bino",
    "analysis_id": "ins1767649",
    "template_toml": "trial-runs/.../config/sleptons_template.toml",  # has MSLEP=/MN1= lines
    "subst": {"MSLEP": "m_parent", "MN1": "m_lsp"},   # TOML mass key <- spec variable
    "plane": "dm",                                     # dm (m vs Delta m) | mass (m_parent vs m_lsp)
    "run_root": "trial-runs",
    "run_prefix": "2026-06-15_sleptonscan",
    "points": [[150,140],[150,135]],                  # explicit (m_parent, m_lsp)
    "line":  {"m_parent":150, "dm":[5,10,15,20,25,30,35,40]},  # m_lsp = m_parent - dm
    "grid":  {"m_parent":[100,150,200], "dm":[5,10,20,30,40]}
  }

See workflow/steps/08-scan.md and workflow/checklists/scan-and-contour.md.
"""
import argparse
import json
import os
import re
import subprocess
import sys

import os as _os
REPO = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # repo root (location-relative; repo is relocatable)
SCHEMA_VERSION = 1


def die(msg):
    sys.exit(f"scan_orchestrator: {msg}")


def load_spec(path):
    if not os.path.exists(path):
        die(f"grid spec not found: {path}")
    with open(path) as fh:
        try:
            spec = json.load(fh)
        except json.JSONDecodeError as e:
            die(f"grid spec {path}: invalid JSON ({e})")
    for req in ("name", "template_toml", "subst", "run_prefix"):
        if req not in spec:
            die(f"grid spec missing required key '{req}'")
    modes = [k for k in ("points", "line", "grid") if k in spec]
    if len(modes) != 1:
        die(f"grid spec must have EXACTLY ONE of points/line/grid, found {modes or 'none'}")
    if not isinstance(spec["subst"], dict) or not spec["subst"]:
        die("grid spec 'subst' must be a non-empty {TOML_KEY: spec_var} map")
    for k, v in spec["subst"].items():
        if v not in ("m_parent", "m_lsp", "dm"):
            die(f"subst[{k}] = {v!r}: spec var must be m_parent/m_lsp/dm")
    return spec


def enumerate_points(spec):
    """Return ordered list of point dicts {m_parent, m_lsp, dm}. Plane-agnostic; dm = m_parent - m_lsp."""
    pts = []
    if "points" in spec:
        for i, p in enumerate(spec["points"]):
            if not (isinstance(p, (list, tuple)) and len(p) == 2):
                die(f"points[{i}] = {p!r}: must be [m_parent, m_lsp]")
            mpar, mlsp = float(p[0]), float(p[1])
            pts.append({"m_parent": mpar, "m_lsp": mlsp, "dm": mpar - mlsp})
    elif "line" in spec:
        ln = spec["line"]
        if "m_parent" not in ln or "dm" not in ln:
            die("line spec needs 'm_parent' (scalar) and 'dm' (list)")
        mpar = float(ln["m_parent"])
        for d in ln["dm"]:
            d = float(d)
            pts.append({"m_parent": mpar, "m_lsp": mpar - d, "dm": d})
    else:  # grid
        g = spec["grid"]
        if "m_parent" not in g or "dm" not in g:
            die("grid spec needs 'm_parent' (list) and 'dm' (list)")
        for mpar in g["m_parent"]:
            for d in g["dm"]:
                mpar, d = float(mpar), float(d)
                pts.append({"m_parent": mpar, "m_lsp": mpar - d, "dm": d})
    if not pts:
        die("grid spec enumerated zero points")
    # kinematic sanity: a slepton cannot be lighter than its LSP child
    for p in pts:
        if p["m_lsp"] >= p["m_parent"]:
            die(f"point m_parent={p['m_parent']} m_lsp={p['m_lsp']}: LSP not lighter than parent "
                f"(Delta m={p['dm']} <= 0) -- kinematically forbidden")
    return pts


def point_tag(p):
    """Deterministic, filesystem-safe per-point tag, e.g. m150_dm10 (dm rounded to 0.1)."""
    return f"m{p['m_parent']:g}_dm{p['dm']:g}".replace(".", "p")


def substitute_toml(template_text, spec, p):
    """Keyed line substitution of the mass keys (never a greedy sed -- see .claude/rules/madgraph-pythia.md).

    Replaces each `^<KEY> = ...` line named in spec['subst'] with the point's value. Verifies every key
    was actually found (a missing key would silently scan the template's frozen mass = wrong spectrum).
    """
    lines = template_text.splitlines()
    want = dict(spec["subst"])  # TOML_KEY -> spec_var
    found = set()
    for i, line in enumerate(lines):
        for key, var in want.items():
            if re.match(rf"\s*{re.escape(key)}\s*=", line):
                val = p[var]
                # integers stay integers (mapyde mass keys are ints); preserve indentation
                indent = line[: len(line) - len(line.lstrip())]
                vstr = f"{val:g}"
                lines[i] = f"{indent}{key} = {vstr}"
                found.add(key)
    missing = set(want) - found
    if missing:
        die(f"template TOML has no line for mass key(s) {sorted(missing)} -- refusing to write a "
            f"point with the template's frozen mass (silent wrong-spectrum trap)")
    return "\n".join(lines) + "\n"


def cmd_plan(args):
    spec = load_spec(args.spec)
    pts = enumerate_points(spec)
    template_path = spec["template_toml"]
    if not os.path.isabs(template_path):
        template_path = os.path.join(REPO, template_path)
    if not os.path.exists(template_path):
        die(f"template_toml not found: {template_path}")
    template_text = open(template_path).read()
    # sanity: the template must contain every mass key we intend to substitute
    for key in spec["subst"]:
        if not re.search(rf"(?m)^\s*{re.escape(key)}\s*=", template_text):
            die(f"template {template_path} has no '{key} =' line to substitute")

    run_root = os.path.join(REPO, spec.get("run_root", "trial-runs"))
    scandir = os.path.join(run_root, f"{spec['run_prefix']}_SCAN")
    if getattr(args, "dry_run", False):
        print(f"[DRY-RUN] would enumerate {len(pts)} points under "
              f"{os.path.relpath(run_root, REPO)}/{spec['run_prefix']}_* (no run dirs / manifest written):")
        for p in pts:
            print(f"  {point_tag(p):14}  m={p['m_parent']:g} dm={p['dm']:g} (m_lsp={p['m_lsp']:g})")
        print("Re-run without --dry-run to materialize the run dirs + scan_manifest.json.")
        return
    os.makedirs(scandir, exist_ok=True)

    manifest_points = []
    for p in pts:
        tag = point_tag(p)
        run_dir = os.path.join(run_root, f"{spec['run_prefix']}_{tag}")
        cfg_dir = os.path.join(run_dir, "config")
        os.makedirs(cfg_dir, exist_ok=True)
        cfg_name = f"{spec.get('model','model')}_{tag}.toml"
        cfg_path = os.path.join(cfg_dir, cfg_name)
        with open(cfg_path, "w") as fh:
            fh.write(substitute_toml(template_text, spec, p))
        manifest_points.append({
            "tag": tag,
            "m_parent": p["m_parent"], "m_lsp": p["m_lsp"], "dm": p["dm"],
            "run_dir": os.path.relpath(run_dir, REPO),
            "config": os.path.relpath(cfg_path, run_dir),  # relative to run dir (run-pipeline.sh arg)
        })

    manifest = {
        "schema_version": SCHEMA_VERSION, "name": spec["name"], "model": spec.get("model"),
        "analysis_id": spec.get("analysis_id"), "plane": spec.get("plane", "dm"),
        "subst": spec["subst"], "template_toml": os.path.relpath(template_path, REPO),
        "n_points": len(manifest_points), "points": manifest_points,
    }
    mpath = os.path.join(scandir, "scan_manifest.json")
    with open(mpath, "w") as fh:
        json.dump(manifest, fh, indent=2)
    print(f"planned {len(manifest_points)} points -> {os.path.relpath(scandir, REPO)}/scan_manifest.json")
    print(f"  plane={manifest['plane']}  model={manifest['model']}  analysis={manifest['analysis_id']}")
    for mp in manifest_points:
        print(f"  {mp['tag']:14}  m={mp['m_parent']:g} dm={mp['dm']:g}  -> {mp['run_dir']}")
    print("\nLaunch (native backend = default, points run in PARALLEL; container = ~9h/pt, sequential):")
    print(f"  python trial-runs/_infrastructure/scan_orchestrator.py launch "
          f"{os.path.relpath(scandir, REPO)} --backend native --max 4 --go")
    print(f"Then assemble when points are done:")
    print(f"  python trial-runs/_infrastructure/scan_orchestrator.py assemble "
          f"{os.path.relpath(scandir, REPO)}")


def load_manifest(scandir):
    if not os.path.isabs(scandir):
        scandir = os.path.join(REPO, scandir)
    mpath = os.path.join(scandir, "scan_manifest.json")
    if not os.path.exists(mpath):
        die(f"no scan_manifest.json in {scandir} -- run `plan` first")
    with open(mpath) as fh:
        return scandir, json.load(fh)


def sigma_ref_fb(mp):
    """Per-point reference cross-section (fb) the signal was normalized to = σ_LO(MadGraph) × kfactor.
    This bridges mapyde's dimensionless µ95 to an ABSOLUTE σ upper-limit (σ_UL = µ95 × σ_ref), which is
    what the (mapyde−ATLAS)/ATLAS difference map compares against the published per-point σ-UL grid (the
    σ_theory cancels in the relative difference). Reads logs/madgraph.log + the run's TOML kfactor;
    returns None if unavailable (the contour overlay still works, only the difference map needs it)."""
    run_dir = os.path.join(REPO, mp["run_dir"])
    log = os.path.join(run_dir, "logs", "madgraph.log")
    sigma_pb = None
    if os.path.exists(log):
        try:
            for line in open(log, errors="ignore"):
                m = re.search(r"Cross-section\s*:\s*([0-9.eE+-]+)", line)
                if m:
                    sigma_pb = float(m.group(1))   # last match = the final result
        except OSError:
            sigma_pb = None
    if sigma_pb is None:
        # Fallback for RE-RUN / healed points whose madgraph.log lacks the "Cross-section :" summary
        # line (MadGraph reused a cached refine and did not re-print it): the σ that was actually fed
        # downstream is recorded in analysis.log as "Using cross section X" (pb). Same number, so the
        # σ_ref is faithful. Without this a healed point has sigma_ref_fb=None and BREAKS the rebase.
        alog = os.path.join(run_dir, "logs", "analysis.log")
        if os.path.exists(alog):
            try:
                for line in open(alog, errors="ignore"):
                    m = re.search(r"Using cross section\s+([0-9.eE+-]+)", line)
                    if m:
                        sigma_pb = float(m.group(1))
            except OSError:
                sigma_pb = None
    if sigma_pb is None:
        return None
    kf = 1.0
    try:
        import tomllib
        cfg = tomllib.load(open(os.path.join(run_dir, mp["config"]), "rb"))
        kf = float(cfg.get("analysis", {}).get("kfactor", 1.0)) or 1.0
    except Exception:
        kf = 1.0
    return sigma_pb * kf * 1000.0   # pb -> fb


def point_kfactor(mp):
    """The FLAT k-factor this point's sigma_ref was normalized with (the TOML analysis.kfactor --
    the same value sigma_ref_fb() folded in). None if the TOML is unreadable: the NLO re-norm must
    then fail loud rather than guess what normalization it is replacing."""
    try:
        import tomllib
        cfg = tomllib.load(open(os.path.join(REPO, mp["run_dir"], mp["config"]), "rb"))
        return float(cfg.get("analysis", {}).get("kfactor", 1.0)) or 1.0
    except Exception:
        return None


def apply_nlo_renorm(rows, process, man):
    """Post-hoc NLO+NLL re-normalization of an assembled scan (no event regeneration).

    Context: each point's signal was normalized to sigma_ref = sigma_LO(sample, cteq6l1) x FLAT k
    (the TOML analysis.kfactor; 1.18 for the slepton scans). ATLAS/RRR normalize to NLO+NLL. The
    fix is multiplicative on the normalization assumption alone:
        mu'95 = mu95 x flat_k / k(m),   k(m) = sigma_NLO+NLL(m) / sigma_LO(m)
    with k(m) the per-mass like-for-like ratio from nlo_xsec.slepton_k (HEPi selL-pair NNLL over
    MG5 selL-pair cteq6l1 LO -- single state over single state; the HEPi slepton file is ONE
    flavour x ONE chirality, so an inclusive-sample LO in the denominator would fake k~0.5).
    Our sample is the ISR-tagged subset (explicit `... j` in the ME); the INCLUSIVE k(m) is still
    the right multiplicative fix to the normalization assumption because both sides of k are
    inclusive and QCD k-factors are ~flat across the ISR subset.

    sigma_ref_fb is scaled by k(m)/flat_k so sigma_UL = mu95 x sigma_ref is INVARIANT: the
    (mapyde-ATLAS)/ATLAS sigma-UL difference map does not move -- only the mu95=1 contour does.
    Per point this stores mu95_obs_lo (the original), k_nlo (the k used), sigma_ref_fb_lo, and
    REPLACES mu95_obs / mu95_exp / mu95_exp_band (+ recomputes excluded_obs). Fails loud if the
    reference grids are unavailable, k(m) is unphysical, or the flat k is not uniform."""
    if process != "slepton":
        die(f"--nlo-renorm {process}: only 'slepton' is wired (it needs a like-for-like LO "
            f"reference table -- see nlo_xsec.LO_REF)")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import nlo_xsec
    try:
        grid = nlo_xsec.hepi_grid(process)
        lo_ref = nlo_xsec.load_lo_ref(process)
    except Exception as e:
        die(f"--nlo-renorm {process}: cannot load the reference grids ({e}) -- NOT falling back "
            f"to a flat k; fix the network/LO-table and re-assemble")
    kf_by_tag = {mp["tag"]: point_kfactor(mp) for mp in man["points"]}
    flats = {kf_by_tag.get(r["tag"]) for r in rows}
    if None in flats:
        bad = [r["tag"] for r in rows if kf_by_tag.get(r["tag"]) is None]
        die(f"--nlo-renorm: cannot read the flat TOML kfactor for {bad} -- refusing to guess "
            f"what normalization is being replaced")
    if len(flats) != 1:
        die(f"--nlo-renorm: non-uniform flat kfactors across points ({sorted(flats)}) -- "
            f"a single flat_k_replaced would be a lie; investigate the TOMLs")
    flat_k = flats.pop()
    ks = {}
    for r in rows:
        m = r["m_parent"]
        if m not in ks:
            try:
                ks[m] = nlo_xsec.slepton_k(m, grid, lo_ref)
            except Exception as e:
                die(f"--nlo-renorm: k(m={m:g}) failed: {e}")
        k = ks[m]["k_factor"]
        fac = flat_k / k
        r["mu95_obs_lo"] = r["mu95_obs"]
        r["k_nlo"] = round(k, 4)
        r["mu95_obs"] = r["mu95_obs"] * fac
        if r.get("mu95_exp") is not None:
            r["mu95_exp"] = r["mu95_exp"] * fac
        if isinstance(r.get("mu95_exp_band"), (list, tuple)):
            r["mu95_exp_band"] = [b * fac for b in r["mu95_exp_band"]]
        if r.get("sigma_ref_fb"):
            r["sigma_ref_fb_lo"] = r["sigma_ref_fb"]
            r["sigma_ref_fb"] = r["sigma_ref_fb"] / fac   # x k/flat_k: mu x sigma_ref invariant
        r["excluded_obs"] = bool(r["mu95_obs"] < 1.0)
    print(f"NLO+NLL re-normalization ({process}): mu'95 = mu95 x {flat_k:g}/k(m)")
    print(f"  {'m':>6}  {'sigma_LO_pb':>12}  {'sigma_NNLL_pb':>13}  {'k':>6}  {'mu-scale':>8}")
    for m in sorted(ks):
        v = ks[m]
        print(f"  {m:6g}  {v['sigma_lo_pb']:12.6g}  {v['sigma_nlo_nll_pb']:13.6g}  "
              f"{v['k_factor']:6.3f}  {flat_k / v['k_factor']:8.3f}")
    return {"process": process, "flat_k_replaced": flat_k,
            "mu_formula": "mu95_nlo = mu95_lo * flat_k_replaced / k_nlo(m_parent)",
            "k_numerator": "HEPi 13000_sleptons_1000011_-1000011_NNLL.json "
                           "(NNLOapprox+NNLL, PDF4LHC21_40, Resummino)",
            "k_interp": "k computed exactly at the masses both tables tabulate, then interpolated "
                        "in k (nearly flat) -- see nlo_xsec.slepton_k",
            "k_denominator": "trial-runs/_infrastructure/slepton_selL_lo_cteq6l1.json "
                             "(MG5_aMC 2.9.27 LO selL pair, cteq6l1 -- like-for-like single state)",
            "k_by_mass": {f"{m:g}": round(ks[m]["k_factor"], 4) for m in sorted(ks)}}


def cmd_rebase(args):
    """Rebase an assembled+NLO-renormed scan.json onto the PUBLISHED MODEL sigma basis, so
    mu95 and sigma_UL = mu95 x sigma_ref are directly comparable to the experiment's per-point
    sigma-UL grid (a mu_SUSY comparison, RRR Fig 3 style).

    THE COMPARISON-BASIS RULE (the bug this fixes): a sigma-UL comparison is only meaningful when
    both ULs are quoted on the SAME model sigma. Before this step, sigma_ref_fb is the TAGGED
    SAMPLE sigma (the isrslep 6-state ISR-tagged sigma from logs/madgraph.log x k) -- so
    mu95 x sigma_ref was the UL on the tagged-sample sigma, while ATLAS Fig 44ab quotes the UL on
    the INCLUSIVE fourfold-degenerate eLR+muLR model sigma (verified: on the published exclusion
    contour, UL/(2 sigma_LR^WG) = 1 (median 1.10); staus are not part of that model). The ratio of
    the two bases is sigma_tag6/sigma_incl4 = 0.56 (m=50) .. 1.01 (m=300) -- a mass-dependent
    apples-to-oranges tilt baked into the old difference map.

    The rebase (slepton): the 95% UL on the number of signal events is basis-free, and the yield
    was predicted as sigma_tag6_LO x k(m) x lumi x A(sample). The SAME simulated model, quoted
    inclusively, predicts the SAME yield with the tag + state fractions moved into the acceptance,
    so the UL on the inclusive 4-state model sigma is
        UL(sigma_incl4) = mu95 x sigma_incl4_assumed,
        sigma_incl4_assumed(m) = sigma_incl4_LO(cteq6l1, m) x k_nlo(m)
    (slepton_incl4_lo_cteq6l1.json -- same cards/PDF as the samples; k_nlo from the nlo-renorm
    step). Tau-slepton SR contamination ~0 (ee/mumu SRs, soft taus) is the one approximation.
    mu95 is then re-expressed against the experiment's OWN model sigma
        mu95_model = UL(sigma_incl4) / sigma_model(m),
        sigma_model(m) = 2 x sigma_LR^WG(m)   (slepton_flavLR_nlonll_pdf4lhc15.json,
                                               Resummino NLO+NLL -- what ATLAS normalized to)
    and sigma_ref_fb := sigma_model so sigma_UL = mu95 x sigma_ref is the UL on the inclusive
    model sigma. excluded_obs is recomputed on this basis (mu95_model < 1 -- the same statement
    ATLAS's contour makes). Idempotent-guarded; fails loud if the tables or k_nlo are missing."""
    if args.process != "slepton":
        die(f"rebase --process {args.process}: only 'slepton' is wired (needs the inclusive-LO "
            f"and WG model-sigma tables)")
    scan_path = args.scan or os.path.join(args.scandir, "scan.json")
    if not os.path.exists(scan_path):
        die(f"scan.json not found: {scan_path} (run `assemble --nlo-renorm slepton` first)")
    scan = json.load(open(scan_path))
    if scan.get("model_basis"):
        die(f"{scan_path} already carries model_basis (rebase is one-shot; re-assemble to redo)")
    if not scan.get("nlo_renorm"):
        die("rebase requires the NLO-renormed assembly (k_nlo per point) -- run "
            "`assemble --nlo-renorm slepton` first; rebasing the flat-LO assembly would mix bases")
    infra = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, infra)
    import nlo_xsec
    def table(name):
        p = os.path.join(infra, name)
        if not os.path.exists(p):
            die(f"rebase: reference table missing: {p}")
        d = json.load(open(p)).get("data", {})
        if not d:
            die(f"rebase: reference table {p} has no 'data'")
        return d
    incl4 = table("slepton_incl4_lo_cteq6l1.json")
    incl6 = table("slepton_incl6_lo_cteq6l1.json")          # diagnostics only
    wg_lr = table("slepton_flavLR_nlonll_pdf4lhc15.json")   # one flavour L+R, NLO+NLL
    flat_k = scan["nlo_renorm"].get("flat_k_replaced")
    by_mass = {}
    for r in scan["points"]:
        m = r["m_parent"]
        if r.get("k_nlo") is None or r.get("sigma_ref_fb") is None:
            die(f"rebase: point {r['tag']} lacks k_nlo/sigma_ref_fb -- re-assemble with --nlo-renorm")
        if m not in by_mass:
            s4_lo, how4 = nlo_xsec.lookup(incl4, m, loglog=True)
            s6_lo, _ = nlo_xsec.lookup(incl6, m, loglog=True)
            s_lr, howm = nlo_xsec.lookup(wg_lr, m, loglog=True)
            if "interp" in how4:
                die(f"rebase: m={m:g} is not a node of slepton_incl4_lo_cteq6l1.json ({how4}) -- "
                    f"extend the MG reference run instead of interpolating the LO table")
            s4a = s4_lo * r["k_nlo"] * 1000.0          # assumed inclusive 4-state sigma, fb
            smod = 2.0 * s_lr * 1000.0                 # ATLAS model sigma (2 flavours of L+R), fb
            by_mass[m] = dict(sigma_incl4_lo_fb=s4_lo * 1000.0, sigma_incl6_lo_fb=s6_lo * 1000.0,
                              sigma_incl4_assumed_fb=s4a, sigma_model_fb=smod,
                              frac4_lo=s4_lo / s6_lo, model_lookup=howm)
        bm = by_mass[m]
        fac = bm["sigma_incl4_assumed_fb"] / bm["sigma_model_fb"]
        r["mu95_obs_tagged6"] = r["mu95_obs"]
        r["sigma_ref_fb_tagged6"] = r["sigma_ref_fb"]
        r["mu95_obs"] = r["mu95_obs"] * fac
        if r.get("mu95_exp") is not None:
            r["mu95_exp"] = r["mu95_exp"] * fac
        if isinstance(r.get("mu95_exp_band"), (list, tuple)):
            r["mu95_exp_band"] = [b * fac for b in r["mu95_exp_band"]]
        r["sigma_ref_fb"] = bm["sigma_model_fb"]
        r["sigma_incl4_assumed_fb"] = bm["sigma_incl4_assumed_fb"]
        r["excluded_obs"] = bool(r["mu95_obs"] < 1.0)
        # per-mass diagnostics need the tagged-sample LO sigma (sigma_ref_fb_lo = MG sigma x flat_k)
        if flat_k and r.get("sigma_ref_fb_lo") and "f_tag_lo" not in bm:
            bm["sigma_tag6_lo_fb"] = r["sigma_ref_fb_lo"] / flat_k
            bm["f_tag_lo"] = bm["sigma_tag6_lo_fb"] / bm["sigma_incl6_lo_fb"]
            bm["old_over_new_basis"] = (r["sigma_ref_fb_tagged6"] / bm["sigma_incl4_assumed_fb"])
    scan["model_basis"] = {
        "process": "slepton",
        "basis": ("inclusive fourfold-mass-degenerate eL,eR,muL,muR production sigma "
                  "(ATLAS-SUSY-2018-16 'direct slepton' simplified model; staus NOT in the model "
                  "-- arXiv:1911.12606 Fig 16 caption)"),
        "mu_formula": ("mu95_model = mu95_tagged6 x sigma_incl4_assumed / sigma_model; "
                       "sigma_incl4_assumed = sigma_incl4_LO(cteq6l1) x k_nlo(m); "
                       "sigma_model = 2 x sigma_LR^WG(m) (Resummino NLO+NLL, PDF4LHC15); "
                       "sigma_ref_fb := sigma_model so sigma_UL = mu95 x sigma_ref = UL on the "
                       "inclusive model sigma"),
        "verification": ("UL/(2 sigma_LR) = 1.10 (median, n=151) on the published observed "
                         "exclusion contour -- the Fig 44ab UL grid is on THIS basis "
                         "(2x eL-NNLL gives 1.47, 4x eL gives 0.74)"),
        "approximations": ["tau-slepton SR contamination ~0 (ee/mumu SRs, soft taus): the "
                           "tagged-6-state sample's accepted yield is attributed entirely to the "
                           "4-state subset",
                           "k_nlo(m) (eL-pair NNLL/LO) applied to the full 4-state LO sigma; the "
                           "eR-state k is ~1.22 vs eL ~1.40 at m=200, so sigma_incl4_assumed sits "
                           "~4-7% above the best NNLL 4-state prediction -- a normalization "
                           "assumption of the SAMPLE, kept for consistency with its yields",
                           "WG grid loglog-interpolated at m=60,70,90 (non-node masses)"],
        "tables": {"incl4_lo": "slepton_incl4_lo_cteq6l1.json",
                   "incl6_lo": "slepton_incl6_lo_cteq6l1.json",
                   "model": "slepton_flavLR_nlonll_pdf4lhc15.json"},
        "by_mass": {f"{m:g}": {k: (round(v, 4) if isinstance(v, float) else v)
                               for k, v in bm.items()} for m, bm in sorted(by_mass.items())},
    }
    n_exc = sum(1 for r in scan["points"] if r["excluded_obs"])
    out = args.out or scan_path
    with open(out, "w") as fh:
        json.dump(scan, fh, indent=2)
    print(f"rebased {len(scan['points'])} points onto the inclusive model-sigma basis -> "
          f"{os.path.relpath(out, REPO)}")
    print(f"  {'m':>6} {'sig_tag6_LO':>12} {'sig_incl4_LO':>13} {'f_tag':>6} {'frac4':>6} "
          f"{'sig4_assumed':>13} {'sig_model':>10} {'old/new':>8}")
    for m, bm in sorted(by_mass.items()):
        print(f"  {m:6g} {bm.get('sigma_tag6_lo_fb', float('nan')):12.4g} "
              f"{bm['sigma_incl4_lo_fb']:13.4g} {bm.get('f_tag_lo', float('nan')):6.3f} "
              f"{bm['frac4_lo']:6.4f} {bm['sigma_incl4_assumed_fb']:13.4g} "
              f"{bm['sigma_model_fb']:10.4g} {bm.get('old_over_new_basis', float('nan')):8.3f}")
    print(f"  excluded (obs mu95_model<1): {n_exc}/{len(scan['points'])}")


def harvest_point(mp):
    """Read a finished point's limit -> dict(mu95_obs, mu95_exp, mu95_exp_band, m_parent, m_lsp,
    sigma_ref_fb, source) or None. Prefers result.json (the RESULT-PACK headline); falls back to the
    native driver's output/exclusion.json (obs_limit + the 5-entry exp_limits band), keyed to the
    manifest masses. Lets the scan harvest either the container path (result_pack) or the native
    path (run-pipeline-native.sh ends at pyhf -> exclusion.json)."""
    run_dir = os.path.join(REPO, mp["run_dir"])
    sref = sigma_ref_fb(mp)
    res = os.path.join(run_dir, "result.json")
    if os.path.exists(res):
        try:
            d = json.load(open(res))
        except (json.JSONDecodeError, OSError):
            return None
        if d.get("mu95_obs") is not None:
            return dict(mu95_obs=float(d["mu95_obs"]),
                        mu95_exp=(float(d["mu95_exp"]) if d.get("mu95_exp") is not None else None),
                        mu95_exp_band=d.get("mu95_exp_band"),
                        m_parent=float(d.get("m_parent", mp["m_parent"])),
                        m_lsp=float(d.get("m_lsp", mp["m_lsp"])),
                        sigma_ref_fb=(float(d["sigma_ref_fb"]) if d.get("sigma_ref_fb") is not None else sref),
                        source="result.json")
    exc = os.path.join(run_dir, "output", "exclusion.json")
    if os.path.exists(exc):
        try:
            d = json.load(open(exc))
        except (json.JSONDecodeError, OSError):
            return None
        obs = d.get("obs_limit")
        if obs is None:
            return None
        band = d.get("exp_limits")
        exp = float(band[2]) if isinstance(band, list) and len(band) == 5 else None
        # CR-001 propagation guard: a floored/capped "limit" is an upper bound / scan ceiling,
        # NOT a measurement -- tag it so assemble/render refuse to color it as one.
        quality = None
        if d.get("at_mu_floor"):
            quality = "floored"
        elif d.get("at_poi_cap"):
            quality = "capped"
        elif float(obs) == 1.0 and isinstance(band, list) and band and len(set(band)) == 1:
            # pre-fix artifacts carry no flag; the CR-001 READING RULE identifies them:
            # obs_limit == 1.0 exactly + a flat expected band = floored, hyper-excluded.
            quality = "floored-legacy"
        out = dict(mu95_obs=float(obs), mu95_exp=exp, mu95_exp_band=band,
                   m_parent=float(mp["m_parent"]), m_lsp=float(mp["m_lsp"]),
                   sigma_ref_fb=sref, source="exclusion.json")
        if quality:
            out["quality"] = quality
        return out
    return None


def point_status(mp):
    """Return (state, mu95_obs_or_None) for one manifest point by inspecting its run dir."""
    h = harvest_point(mp)
    if h is not None:
        return "done", h["mu95_obs"]
    status_txt = os.path.join(REPO, mp["run_dir"], "logs", "STATUS.txt")
    if os.path.exists(status_txt):
        tail = open(status_txt).read().strip().splitlines()
        last = tail[-1] if tail else ""
        if "FAIL" in last or "STOPPED" in last:
            return "failed", None
        if any(k in last for k in ("START", "pipeline start", "PASS", "ALL_STAGES_COMPLETE")):
            return "running", None
    return "pending", None


def cmd_status(args):
    scandir, man = load_manifest(args.scandir)
    counts = {"done": 0, "running": 0, "failed": 0, "pending": 0}
    print(f"scan {man['name']}  ({man['n_points']} points)")
    for mp in man["points"]:
        st, mu = point_status(mp)
        counts[st] += 1
        mus = f"  mu95_obs={mu:.3f}" if mu is not None else ""
        print(f"  {mp['tag']:14}  m={mp['m_parent']:g} dm={mp['dm']:g}  [{st}]{mus}")
    print("  " + "  ".join(f"{k}={v}" for k, v in counts.items()))


def cmd_assemble(args):
    scandir, man = load_manifest(args.scandir)
    rows = []
    missing = []
    for mp in man["points"]:
        h = harvest_point(mp)
        if h is None or h["mu95_obs"] is None:
            missing.append(mp["tag"])
            continue
        rows.append({
            "tag": mp["tag"], "m_parent": h["m_parent"], "m_lsp": h["m_lsp"],
            "dm": h["m_parent"] - h["m_lsp"],
            "mu95_obs": h["mu95_obs"], "mu95_exp": h["mu95_exp"],
            "mu95_exp_band": h.get("mu95_exp_band"),
            "sigma_ref_fb": h.get("sigma_ref_fb"),   # σ the signal was normalized to → σ_UL = µ95×σ_ref
            "excluded_obs": bool(h["mu95_obs"] < 1.0),
            "source": h["source"],
            # CR-001: the harvest quality tag (floored/capped/floored-legacy) MUST survive into
            # scan.json — a floored µ is a bound, and the renderer keys on this field.
            **({"quality": h["quality"]} if h.get("quality") else {}),
        })
    if not rows:
        die("no completed points (no result.json / exclusion.json yet) -- nothing to assemble")
    rows.sort(key=lambda r: (r["m_parent"], r["dm"]))
    nlo_meta = None
    if getattr(args, "nlo_renorm", None):
        nlo_meta = apply_nlo_renorm(rows, args.nlo_renorm, man)
    out = args.out or os.path.join(scandir, "scan.json")
    scan = {
        "schema_version": SCHEMA_VERSION, "name": man["name"], "model": man.get("model"),
        "analysis_id": man.get("analysis_id"), "plane": man.get("plane", "dm"),
        "n_planned": man["n_points"], "n_done": len(rows), "n_missing": len(missing),
        "missing_tags": missing, "points": rows,
    }
    if nlo_meta:
        scan["nlo_renorm"] = nlo_meta
    with open(out, "w") as fh:
        json.dump(scan, fh, indent=2)
    cov = 100.0 * len(rows) / man["n_points"]
    print(f"assembled {len(rows)}/{man['n_points']} points ({cov:.0f}% coverage) -> "
          f"{os.path.relpath(out, REPO)}")
    if missing:
        print(f"  PENDING (not yet in the contour): {', '.join(missing)}")
    excl = [r for r in rows if r["excluded_obs"]]
    print(f"  excluded (obs mu95<1): {len(excl)}/{len(rows)}")
    if scan["plane"] == "dm" and len({r['m_parent'] for r in rows}) == 1 and excl:
        dms = sorted(r["dm"] for r in excl)
        print(f"  excluded Delta m (obs): {dms[0]:g}..{dms[-1]:g} GeV at m={rows[0]['m_parent']:g}")


def _toml_nevents(run_dir, config_rel):
    """Read madgraph.run.nevents from a point's TOML so the prep + driver agree on event count."""
    import tomllib
    path = os.path.join(run_dir, config_rel)
    with open(path, "rb") as fh:
        cfg = tomllib.load(fh)
    return int(cfg["madgraph"]["run"]["nevents"])


def cmd_launch(args):
    scandir, man = load_manifest(args.scandir)
    native = (args.backend == "native")
    # SEQUENTIAL-ONLY SAFETY GATE applies ONLY to the container/VM backend: the shared podman VM uses
    # FIXED per-stage container names and run-pipeline.sh `podman rm -f`s all containers at startup, so a
    # concurrent launch would clobber the in-flight point. The NATIVE backend (run-pipeline-native.sh)
    # has NO shared VM and NO fixed container names -- each point is independent processes -- so native
    # points may run in PARALLEL (one of the payoffs of going VM-free; --max sets the concurrency).
    if not native:
        running = [mp["tag"] for mp in man["points"] if point_status(mp)[0] == "running"]
        if running and not args.force:
            die(f"point(s) {running} are RUNNING (container backend). The shared VM + fixed container "
                f"names mean a concurrent launch would CLOBBER the in-flight run -- wait, re-check with "
                f"`status`, then launch the next. (--force only if each point has an isolated VM.)")
    pending = [mp for mp in man["points"] if point_status(mp)[0] in ("pending",)]
    if not pending:
        print("no pending points (all done/running/failed)")
        return
    todo = pending[: args.max]
    backend_name = "NATIVE (parallel-ok)" if native else "container (sequential)"
    runner = os.path.join(REPO, "trial-runs/_infrastructure/run-pipeline-native.sh" if native
                          else "trial-runs/_infrastructure/run-pipeline.sh")
    prep = os.path.join(REPO, "trial-runs/_infrastructure/prepare_native_slepton.py")
    print(f"{len(pending)} pending; launching {len(todo)} [{backend_name}, max={args.max}]"
          f"{' [DRY]' if not args.go else ''}:")
    for mp in todo:
        run_dir = os.path.join(REPO, mp["run_dir"])
        if native:
            # materialize this point's native inputs (run.mg5/shower.cfg/cards) from its masses +
            # the TOML's nevents (single source of truth), via the stdlib-only prep helper.
            nev = _toml_nevents(run_dir, mp["config"])
            prep_cmd = [sys.executable, prep, "--rundir", run_dir,
                        "--m-parent", str(mp["m_parent"]), "--m-lsp", str(mp["m_lsp"]),
                        "--nevents", str(nev),
                        "--pdf", getattr(args, "pdf", "cteq6l1"),
                        # CR-002: the point's own TOML supplies [madgraph.run.options]
                        # (ptj1min=50 etc.) so native and container samples share one
                        # tag/phase-space definition.
                        "--toml", os.path.join(run_dir, mp["config"])]
            print(f"  {mp['tag']}: prep ({mp['m_parent']:g},{mp['m_lsp']:g}) nevents={nev}  +  "
                  f"bash run-pipeline-native.sh")
            if args.go:
                pr = subprocess.run(prep_cmd, capture_output=True, text=True)
                if pr.returncode != 0:
                    print(f"    PREP FAILED: {pr.stderr.strip()[:200]}"); continue
        else:
            print(f"  {mp['tag']}: bash run-pipeline.sh {mp['config']}")
        cmd = ["bash", runner, run_dir, mp["config"]]
        if args.go:
            os.makedirs(os.path.join(run_dir, "logs"), exist_ok=True)
            log = open(os.path.join(run_dir, "logs", "orchestrator_launch.log"), "a")
            subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
            print(f"    -> backgrounded ({backend_name})")
    if not args.go:
        print("  (dry run; pass --go to actually launch these)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan"); p.add_argument("spec")
    p.add_argument("--dry-run", action="store_true",
                   help="enumerate the grid points WITHOUT writing run dirs / TOMLs / manifest")
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("status"); p.add_argument("scandir"); p.set_defaults(fn=cmd_status)
    p = sub.add_parser("assemble"); p.add_argument("scandir")
    p.add_argument("--out", default=None)
    p.add_argument("--nlo-renorm", default=None, metavar="PROCESS", choices=["slepton"],
                   help="re-normalize the assembled limits from the flat LO k-factor to the "
                        "per-mass NLO+NLL k(m) (post-hoc; stores mu95_obs_lo + k_nlo per point; "
                        "sigma_UL = mu95 x sigma_ref stays invariant). Fails loud on any k error.")
    p.set_defaults(fn=cmd_assemble)
    p = sub.add_parser("rebase"); p.add_argument("scandir")
    p.add_argument("--process", required=True, choices=["slepton"],
                   help="rebase the assembled+NLO-renormed scan.json onto the PUBLISHED inclusive "
                        "model-sigma basis (mu95 -> mu_SUSY vs the WG NLO+NLL model sigma; "
                        "sigma_ref_fb := sigma_model). REQUIRED before comparing sigma-ULs / "
                        "rendering the difference map against --atlas-limit: the sample sigma_ref "
                        "(tagged subset) and the published UL (inclusive model) are DIFFERENT bases.")
    p.add_argument("--scan", default=None, help="scan.json path (default <scandir>/scan.json)")
    p.add_argument("--out", default=None, help="output path (default: in-place)")
    p.set_defaults(fn=cmd_rebase)
    p = sub.add_parser("launch"); p.add_argument("scandir")
    p.add_argument("--backend", choices=["native", "container"], default="native",
                   help="native = run-pipeline-native.sh (VM-free, parallel-ok; preps each point's "
                        "inputs from its masses); container = run-pipeline.sh (shared VM, sequential)")
    p.add_argument("--max", type=int, default=1,
                   help="max points to launch this call (native points run in parallel)")
    p.add_argument("--go", action="store_true")
    p.add_argument("--pdf", choices=["cteq6l1", "nn23nlo", "nnpdf30"], default="cteq6l1",
                   help="proton PDF passed to the native prep (nnpdf30 = LHAPDF lhaid 260000, "
                        "the CR-004 rescan basis); native backend only")
    p.add_argument("--force", action="store_true",
                   help="override the container sequential-only gate (ONLY with isolated VMs per point)")
    p.set_defaults(fn=cmd_launch)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
