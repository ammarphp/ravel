#!/usr/bin/env python3
"""Phase-1 benchmark regression gate (see DESIGN.md / BENCHMARK.md).

Re-scores the registered known-answer cases (cases.json) against published ground
truth by CALLING the existing helpers — pyhf_exclude.py (fresh 95% CLs limit) and
the case's A×ε cert engine (validate_cutflow.py or the run-local certify_axe.py) —
then gates: exit 0 = all registered floors hold, exit 1 = gate breach or case
error, exit 2 = registry/usage error. 95% CLs exclusion fidelity, NOT 5σ discovery.

Stdlib-only orchestrator: the physics runs inside the `rivet` conda env via
subprocess; this script needs only python3. Run from anywhere:

    python3 framework/benchmark/run_benchmark.py --fast     # one case, minutes
    python3 framework/benchmark/run_benchmark.py --full     # all cases
    python3 framework/benchmark/run_benchmark.py --case ID [--case ID2]
"""
import argparse
import json
import math
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BENCH = Path(__file__).resolve().parent
WORK = BENCH / ".work"
DEFAULT_OUT = str(WORK / "results.latest.json")  # gitignored scratch — see --update-baseline
TRACKED_OUT = str(BENCH / "results.json")
CONDA = REPO / "stages/01-event-generation/build/tools/miniforge3/bin/conda"
INFRA = REPO / "trial-runs/_infrastructure"
ENV = "rivet"


def _py_invoke():
    """Interpreter prefix for the physics sub-calls. Dev repo: the pinned rivet conda env
    (unchanged behavior). Fresh clone / public export / CI (no toolchain on disk): fall back to
    the CURRENT interpreter — the fast gate needs only pyhf+numpy+scipy (requirements-replay.txt),
    which is exactly the REPLAY-MODE contract in the README quickstart."""
    if CONDA.exists():
        return [str(CONDA), "run", "-n", ENV, "python"]
    return [sys.executable]
EXP_MEDIAN_IDX = 2          # exp_limits = [-2σ, -1σ, median, +1σ, +2σ]
TIER_RANK = {"Ideal": 3, "Good": 2, "Acceptable": 1, "BELOW": 0}
STEP_TIMEOUT_S = 1800       # no `timeout` binary on this host: python-level ceiling
REFETCH_HINT = ("missing HEPData tables — refetch with: <conda> run -n reinterp python "
                "trial-runs/_infrastructure/hepdata_fetch.py (see BENCHMARK.md §fresh-clone)")


class RegistryError(Exception):
    """Malformed cases.json / usage — exit 2, nothing was scored."""


class StepError(Exception):
    """A case's pipeline step failed — case status ERROR, gate breach."""


def normalize_sr(name):
    """pyhf channel names may carry the cutflow SR in brackets: 'SR3L[SR3L_Low]'."""
    return name.split("[", 1)[1].rstrip("]") if "[" in name else name


def tier_of(value, ladder):
    """Map a non-negative deviation onto the tier ladder (smaller is better)."""
    if value is None:
        return "BELOW"
    for tier in ("Ideal", "Good", "Acceptable"):
        if value <= ladder[tier]:
            return tier
    return "BELOW"


def round_floats(obj, sig=6):
    if isinstance(obj, float):
        return float(f"{obj:.{sig}g}") if math.isfinite(obj) else obj
    if isinstance(obj, dict):
        return {k: round_floats(v, sig) for k, v in obj.items()}
    if isinstance(obj, list):
        return [round_floats(v, sig) for v in obj]
    return obj


def load_registry(path):
    try:
        reg = json.load(open(path))
    except (OSError, json.JSONDecodeError) as e:
        raise RegistryError(f"cannot load {path}: {e}")
    if reg.get("schema_version") != 1:
        raise RegistryError("schema_version != 1")
    for key in ("fast_case", "tier_ladders", "cases"):
        if key not in reg:
            raise RegistryError(f"missing top-level key: {key}")
    for ladder in ("axe", "limit"):
        lad = reg["tier_ladders"].get(ladder, {})
        if not all(t in lad for t in ("Ideal", "Good", "Acceptable")):
            raise RegistryError(f"tier_ladders.{ladder} must define Ideal/Good/Acceptable")
    ids = [c.get("case_id") for c in reg["cases"]]
    if len(ids) != len(set(ids)):
        raise RegistryError("duplicate case_id")
    if reg["fast_case"] not in ids:
        raise RegistryError(f"fast_case {reg['fast_case']!r} is not a registered case")
    for c in reg["cases"]:
        cid = c.get("case_id", "<no id>")
        for key in ("routine", "run_dir", "sigma_lo_pb", "sigma_scale_k", "lumi_fb",
                    "srs", "driving_sr", "inputs", "cert", "published", "required",
                    "gates", "provenance", "m_parent", "m_lsp"):
            if key not in c:
                raise RegistryError(f"{cid}: missing key {key}")
        for key in ("m_parent", "m_lsp", "sigma_lo_pb", "sigma_scale_k", "lumi_fb"):
            if not isinstance(c[key], (int, float)):
                raise RegistryError(f"{cid}: {key} must be a number")
        if c["inputs"].get("pyhf_mode") not in (None, "counting", "combined"):
            raise RegistryError(f"{cid}: inputs.pyhf_mode must be 'counting' or 'combined'")
        eng = c["cert"].get("engine")
        if eng == "validate_cutflow":
            need = ("grid", "tables_dir")
        elif eng == "certify_axe":
            need = ("script", "axe_json")
        elif eng == "none":
            # no published acc*eff exists for this analysis (e.g. CONF notes):
            # the A*eff metric is unscorable; required.axe_tier must be null.
            need = ()
            if c["required"].get("axe_tier") is not None:
                raise RegistryError(f"{cid}: cert.engine 'none' requires required.axe_tier null")
        else:
            raise RegistryError(f"{cid}: unknown cert.engine {eng!r}")
        for k in need:
            if k not in c["cert"]:
                raise RegistryError(f"{cid}: cert.engine={eng} needs cert.{k}")
        if eng == "validate_cutflow" and not c["inputs"].get("yoda"):
            raise RegistryError(f"{cid}: validate_cutflow needs inputs.yoda")
        req = c["required"]
        for tk in ("axe_tier", "limit_tier"):
            t = req.get(tk)
            if t is not None and t not in ("Ideal", "Good", "Acceptable"):
                raise RegistryError(f"{cid}: required.{tk}={t!r} not a valid tier")
        st = req.get("mu95_stability")
        if not isinstance(st, dict) or "rtol" not in st or "baseline_mu95_obs" not in st:
            raise RegistryError(f"{cid}: required.mu95_stability needs baseline_mu95_obs+rtol")
        if not isinstance(c["gates"].get("verdict_pipeline"), bool):
            raise RegistryError(f"{cid}: gates.verdict_pipeline must be a bool")
        if c["published"].get("excluded_obs") is None:
            raise RegistryError(f"{cid}: published.excluded_obs is required")
    return reg


def sh(cmd, log_path, step):
    """Run a helper; tee output to a log; raise StepError on rc!=0/timeout."""
    t0 = time.time()
    try:
        p = subprocess.run([str(x) for x in cmd], cwd=str(REPO),
                           capture_output=True, text=True, timeout=STEP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise StepError(f"{step}: timed out after {STEP_TIMEOUT_S}s")
    log_path.write_text(f"$ {' '.join(str(x) for x in cmd)}\n--- stdout ---\n{p.stdout}"
                        f"\n--- stderr ---\n{p.stderr}\n--- rc={p.returncode} ---\n")
    if p.returncode != 0:
        tail = (p.stderr or p.stdout).strip().splitlines()[-3:]
        raise StepError(f"{step}: rc={p.returncode} ({' | '.join(tail)}) — see {log_path}")
    return time.time() - t0


def preflight(case):
    """Input paths the steps need; missing → StepError (gate breach with reason)."""
    need = [case["inputs"]["sr_yields"]]
    if case["inputs"].get("yoda"):
        need.append(case["inputs"]["yoda"])
    e = case["cert"]
    need += [e[k] for k in ("tables_dir", "script", "axe_json") if k in e]
    for rel in need:
        p = REPO / rel
        if not p.exists():
            hint = f" ({REFETCH_HINT})" if "hepdata" in rel else ""
            raise StepError(f"preflight: missing input {rel}{hint}")


def run_pyhf(case, wdir):
    out = wdir / "pyhf"
    cmd = _py_invoke() + [INFRA / "pyhf_exclude.py", "counting",
           "--srs", REPO / case["inputs"]["sr_yields"], "--out", out,
           "--label", case["case_id"], "--sigma-scale", case["sigma_scale_k"]]
    if case["inputs"].get("pyhf_mode") == "combined":
        cmd.append("--combined")
    # staleness = "was the artifact produced by THIS step": compare against the step START,
    # never against the work-dir mtime (the dir's mtime moves when the log lands AFTER the
    # subprocess returns — >1 s under full-core load, a race that breached the gate while a
    # 4-parallel scan was running; the artifact itself was fresh and correct).
    import time as _time
    t0 = _time.time()
    secs = sh(cmd, wdir / "pyhf.log", "pyhf_exclude")
    path = out / "exclusion.json"
    if not path.exists() or path.stat().st_mtime < t0 - 1:
        raise StepError("pyhf_exclude: exclusion.json missing or stale")
    return json.load(open(path)), secs


def _cached_axe(case_id):
    """Replay-mode cert fallback: the case's axe metrics from the TRACKED baseline results.json,
    annotated as cached (see the call site for the rationale). None if unavailable."""
    try:
        baseline = json.load(open(TRACKED_OUT))
        for row in baseline.get("cases", []):
            if row.get("case_id") == case_id:
                axe = (row.get("metrics") or {}).get("axe")
                if axe:
                    axe = dict(axe)
                    axe["cached_replay"] = True
                    return axe
    except (OSError, json.JSONDecodeError):
        pass
    return None


def run_cert(case, wdir, fresh_exclusion):
    e, out = case["cert"], wdir / "cert.md"
    if e["engine"] == "validate_cutflow":
        cmd = _py_invoke() + [INFRA / "validate_cutflow.py",
               "--signal", REPO / case["inputs"]["yoda"], "--routine", case["routine"],
               "--sigma-pb", case["sigma_lo_pb"], "--lumi-fb", case["lumi_fb"],
               "--tables-dir", REPO / e["tables_dir"], "--grid", e["grid"],
               "--m-parent", case["m_parent"], "--m-lsp", case["m_lsp"],
               "--srs", ",".join(case["srs"]), "--label", case["case_id"],
               "--exclusion", fresh_exclusion,
               "--driving-tol", e["driving_tol"], "--contributing-tol", e["contributing_tol"],
               "--mu95-bound", e["mu95_bound"], "--out", out]
    else:  # certify_axe (run-local adapter, same output schema)
        cmd = _py_invoke() + [REPO / e["script"],
               "--axe", REPO / e["axe_json"], "--exclusion", fresh_exclusion,
               "--sr-yields", REPO / case["inputs"]["sr_yields"],
               "--driving-tol", e["driving_tol"], "--contributing-tol", e["contributing_tol"],
               "--mu95-bound", e["mu95_bound"], "--label", case["case_id"], "--out", out]
    secs = sh(cmd, wdir / "cert.log", f"cert[{e['engine']}]")
    path = Path(str(out).replace(".md", ".json"))
    if not path.exists():
        raise StepError(f"cert[{e['engine']}]: {path.name} not written")
    cert = json.load(open(path))
    for key in ("verdict", "rows"):
        if key not in cert:
            raise StepError(f"cert[{e['engine']}]: output missing {key!r}")
    return cert, secs


def score_axe(cert, case, ladders):
    drow = next((r for r in cert["rows"]
                 if normalize_sr(r["sr"]) == case["driving_sr"]), None)
    residual = (abs(drow["ratio"] - 1.0)
                if drow and drow.get("ratio") is not None else None)
    return {
        "driving_sr": case["driving_sr"],
        "residual": residual,
        "tier": tier_of(residual, ladders["axe"]),
        "cert_verdict": cert["verdict"],
        "worst_driving_mu95_impact": cert.get("worst_driving_mu95_impact"),
        "n_attributed": sum(1 for r in cert["rows"] if r.get("attribution")),
    }


def score_limit(excl, case, ladders):
    pub = case["published"]
    mu_obs, mu_exp = excl["obs_limit"], excl["exp_limits"][EXP_MEDIAN_IDX]
    sigma_ref_fb = case["sigma_lo_pb"] * 1000.0 * case["sigma_scale_k"]
    entry = next((v for k, v in excl.get("per_sr", {}).items()
                  if normalize_sr(k) == case["driving_sr"]), None)
    if entry is None:
        raise StepError(f"limit: driving SR {case['driving_sr']} not in pyhf per_sr")

    # driving-SR s95 in events (per_sr µ and s share the same σ reference → k-free)
    s95_obs = entry["obs_limit"] * entry["s"]
    s95_exp = entry["exp_median"] * entry["s"]
    m = {
        "mu95_obs": mu_obs, "mu95_exp": mu_exp,
        "sigma_ul_ours_fb": mu_obs * sigma_ref_fb,
        "s95_obs": s95_obs, "s95_exp": s95_exp,
        "best_sr": normalize_sr(excl["best_sr"]),
        "best_sr_matches": normalize_sr(excl["best_sr"]) == case["driving_sr"],
        "our_excluded_obs": mu_obs < 1.0,
        "verdict_pipeline_match": (mu_obs < 1.0) == pub["excluded_obs"],
    }

    def dev(ours, theirs):
        r = ours / theirs
        return max(r, 1.0 / r) - 1.0

    # accuracy vs published model-independent S95 (when comparable)
    if pub.get("s95_obs"):
        m["s95_ratio_obs"] = s95_obs / pub["s95_obs"]
        m["s95_ratio_exp"] = (s95_exp / pub["s95_exp"]) if pub.get("s95_exp") else None
        worst = max(dev(s95_obs, pub["s95_obs"]),
                    dev(s95_exp, pub["s95_exp"]) if pub.get("s95_exp") else 0.0)
        m["tier"] = tier_of(worst, ladders["limit"])
    else:
        m["s95_ratio_obs"] = m["s95_ratio_exp"] = None
        m["tier"] = None  # no comparable published per-SR limit (see case notes)

    # accuracy vs published model-dependent σ-UL (informational where it exists)
    if pub.get("sigma_ul_obs_fb"):
        m["sigma_ul_ratio_obs"] = m["sigma_ul_ours_fb"] / pub["sigma_ul_obs_fb"]
        m["sigma_ul_tier_info"] = tier_of(dev(m["sigma_ul_ours_fb"], pub["sigma_ul_obs_fb"]),
                                          ladders["limit"])
    else:
        m["sigma_ul_ratio_obs"] = m["sigma_ul_tier_info"] = None

    # registry self-check: do the transcribed numbers imply the transcribed verdict?
    if pub.get("sigma_ul_obs_fb"):
        implied = sigma_ref_fb > pub["sigma_ul_obs_fb"]
    elif pub.get("eps_sigma_obs_fb"):
        implied = (entry["s"] / case["lumi_fb"]) > pub["eps_sigma_obs_fb"]
    else:
        implied = None
    m["selfcheck_ok"] = None if implied is None else implied == pub["excluded_obs"]

    # regression-vs-self: µ95 stability against the locked baseline
    st = case["required"]["mu95_stability"]
    base = st.get("baseline_mu95_obs")
    m["mu95_baseline"] = base
    m["stability_ok"] = (None if base is None
                         else abs(mu_obs - base) / base <= st["rtol"])
    return m


def score_provenance(case):
    failures = []
    run_dir = REPO / case["run_dir"]
    if not run_dir.is_dir():
        failures.append(f"run_dir missing: {case['run_dir']}")
    for rel in case["provenance"]["require_files"]:
        p = run_dir / rel
        if not p.is_file() or p.stat().st_size == 0:
            failures.append(f"deliverable missing/empty: {rel}")
    for chk in case["provenance"].get("sigma_checks", []):
        p = run_dir / chk["file"]
        try:
            val = json.load(open(p))
            for part in chk["field"].split("."):
                val = val[part]
            if abs(val - chk["expect"]) > chk["rtol"] * abs(chk["expect"]):
                failures.append(f"{chk['file']}:{chk['field']}={val} != {chk['expect']} "
                                f"(rtol {chk['rtol']})")
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as e:
            failures.append(f"sigma_check {chk['file']}:{chk['field']} unreadable: {e}")
    return {"ok": not failures, "failures": failures}


def gate_case(case, status, error, axe, limit, prov):
    reasons = []
    if status == "ERROR":
        reasons.append(f"case error: {error}")
    if prov and not prov["ok"]:
        reasons += [f"provenance: {f}" for f in prov["failures"]]
    req = case["required"]
    if axe and req.get("axe_tier"):
        if TIER_RANK[axe["tier"]] < TIER_RANK[req["axe_tier"]]:
            reasons.append(f"A×ε tier {axe['tier']} < required {req['axe_tier']}")
    if limit:
        if req.get("limit_tier"):
            if limit["tier"] is None:
                reasons.append("limit tier required but not scorable (no published S95)")
            elif TIER_RANK[limit["tier"]] < TIER_RANK[req["limit_tier"]]:
                reasons.append(f"limit tier {limit['tier']} < required {req['limit_tier']}")
        if case["gates"]["verdict_pipeline"] and not limit["verdict_pipeline_match"]:
            reasons.append(f"pipeline verdict (µ95_obs={limit['mu95_obs']:.3g} → "
                           f"excluded={limit['our_excluded_obs']}) != published "
                           f"excluded_obs={case['published']['excluded_obs']}")
        if limit["selfcheck_ok"] is False:
            reasons.append("registry self-check failed: transcribed σ/UL numbers "
                           "contradict transcribed verdict")
        if limit["stability_ok"] is False:
            reasons.append(f"µ95_obs={limit['mu95_obs']:.3g} drifted >"
                           f"{req['mu95_stability']['rtol']:.0%} from baseline "
                           f"{limit['mu95_baseline']:.3g}")
        if not limit["best_sr_matches"]:
            reasons.append(f"pyhf best SR {limit['best_sr']} != registered "
                           f"driving SR {case['driving_sr']}")
    return (not reasons, reasons)


def fmt(x, spec=".3g"):
    return "-" if x is None else f"{x:{spec}}"


def print_table(results):
    hdr = (f"{'CASE':34} {'AxE%':>5} {'AxE tier(req)':>16} {'s95 o/e':>11} "
           f"{'lim tier(req)':>16} {'σUL o/p':>8} {'verd':>4} {'stab':>4} "
           f"{'prov':>4} {'cert':>4}  GATE")
    print("\n" + hdr + "\n" + "-" * len(hdr))
    for r in results:
        c, axe, lim = r["case"], r["metrics"].get("axe"), r["metrics"].get("limit")
        req = c["required"]
        axe_s = (f"{axe['residual']*100:5.1f} {axe['tier']:>10}({req['axe_tier'] or '-'})"
                 if axe and axe["residual"] is not None else f"{'-':>5} {'-':>13}")
        if lim:
            s95 = f"{fmt(lim['s95_ratio_obs'],'.2f')}/{fmt(lim['s95_ratio_exp'],'.2f')}"
            lim_s = f"{lim['tier'] or '-':>10}({req['limit_tier'] or '-'})"
            ul = fmt(lim["sigma_ul_ratio_obs"], ".2f")
            verd = "ok" if lim["verdict_pipeline_match"] else "MISS"
            if not c["gates"]["verdict_pipeline"]:
                verd += "*"
            stab = {True: "ok", False: "DRIFT", None: "-"}[lim["stability_ok"]]
        else:
            s95, lim_s, ul, verd, stab = "-", f"{'-':>13}", "-", "-", "-"
        prov = "ok" if r["metrics"]["provenance"]["ok"] else "FAIL"
        cert = axe["cert_verdict"] if axe else "-"
        gate = "OK" if r["gate"]["ok"] else "BREACH"
        print(f"{c['case_id']:34} {axe_s} {s95:>11} {lim_s:>16} {ul:>8} "
              f"{verd:>4} {stab:>4} {prov:>4} {cert:>4}  {gate}")
        for reason in r["gate"]["reasons"]:
            print(f"{'':36}!! {reason}")
    n_breach = sum(1 for r in results if not r["gate"]["ok"])
    print("-" * len(hdr))
    print(f"GATE: {'OK' if n_breach == 0 else f'BREACH ({n_breach} case(s))'}   "
          f"[verd '*' = informational, not gated]\n")
    return n_breach


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sel = ap.add_mutually_exclusive_group(required=True)
    sel.add_argument("--fast", action="store_true", help="the registry's fast_case only")
    sel.add_argument("--full", action="store_true", help="all registered cases")
    sel.add_argument("--case", action="append", help="specific case_id (repeatable)")
    ap.add_argument("--cases", default=str(BENCH / "cases.json"),
                    help="registry path (override for gate self-tests)")
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="results path — defaults to a gitignored scratch file so a routine/"
                         "verification run never dirties the tracked baseline; pass "
                         "--update-baseline (or this flag explicitly pointed at "
                         "framework/benchmark/results.json) to refresh the committed baseline")
    ap.add_argument("--update-baseline", action="store_true",
                    help="write the TRACKED framework/benchmark/results.json baseline instead "
                         "of the gitignored scratch default (the deliberate, explicit way to "
                         "refresh it; has no effect if --out was also given explicitly)")
    ap.add_argument("--keep-work", action="store_true",
                    help="do not wipe .work/<case>/ first (debugging)")
    return ap


def resolve_out(args):
    """Map parsed args to the actual write path. --update-baseline redirects the *default*
    scratch target to the tracked baseline; an explicit --out is left untouched either way."""
    if args.update_baseline and args.out == DEFAULT_OUT:
        return TRACKED_OUT
    return args.out


def main():
    args = build_parser().parse_args()

    if not CONDA.exists():
        print(f"note: dev toolchain not found ({CONDA}); replay mode — using the current "
              f"interpreter ({sys.executable}) for the statistics layer "
              f"(pip install -r requirements-replay.txt)", file=sys.stderr)
    try:
        reg = load_registry(args.cases)
    except RegistryError as e:
        print(f"REGISTRY ERROR: {e}", file=sys.stderr)
        return 2
    by_id = {c["case_id"]: c for c in reg["cases"]}
    if args.fast:
        selected, selection = [by_id[reg["fast_case"]]], "fast"
    elif args.full:
        selected, selection = reg["cases"], "full"
    else:
        unknown = [i for i in args.case if i not in by_id]
        if unknown:
            print(f"REGISTRY ERROR: unknown case id(s): {unknown}", file=sys.stderr)
            return 2
        selected, selection = [by_id[i] for i in args.case], args.case

    ladders = reg["tier_ladders"]
    results = []
    for case in selected:
        cid = case["case_id"]
        wdir = WORK / cid
        if wdir.exists() and not args.keep_work:
            shutil.rmtree(wdir)
        wdir.mkdir(parents=True, exist_ok=True)
        print(f"[{cid}] scoring …", flush=True)
        t0 = time.time()
        prov = score_provenance(case)
        axe = limit = None
        status, error, timing = "OK", None, {}
        try:
            preflight(case)
            excl, timing["pyhf_s"] = run_pyhf(case, wdir)
            if case["cert"]["engine"] == "none":
                axe = None  # unscorable by design (no published acc*eff); gate skips axe
            else:
                try:
                    cert, timing["cert_s"] = run_cert(case, wdir, wdir / "pyhf" / "exclusion.json")
                    axe = score_axe(cert, case, ladders)
                except StepError as cert_err:
                    # REPLAY-MODE cert fallback: the A*eff certification re-run needs the yoda
                    # reader (Rivet stack, not pip-installable; the PyPI 'yoda' is an UNRELATED
                    # package — never install it). Outside the dev toolchain the cert is scored
                    # from the TRACKED baseline (results.json, sha-covered by the export gates)
                    # and labeled cached — the LIVE re-validation in replay mode is the pyhf
                    # limit + provenance + gate layers, per the README's replay contract.
                    if CONDA.exists() or "No module named 'yoda'" not in str(cert_err):
                        raise
                    axe = _cached_axe(case["case_id"])
                    if axe is None:
                        raise
                    print(f"    !! cert: cached-replay (yoda unavailable outside the dev "
                          f"toolchain; A*eff tier from the tracked baseline)")
            limit = score_limit(excl, case, ladders)
        except StepError as e:
            status, error = "ERROR", str(e)
        timing["total_s"] = time.time() - t0
        gate_ok, reasons = gate_case(case, status, error, axe, limit, prov)
        results.append({"case": case, "status": status, "error": error,
                        "metrics": {"axe": axe, "limit": limit, "provenance": prov},
                        "timing": timing, "gate": {"ok": gate_ok, "reasons": reasons}})

    n_breach = print_table(results)
    out = {
        "schema_version": 1,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cases_file": str(args.cases),
        "selection": selection,
        "cases": sorted(
            ({"case_id": r["case"]["case_id"], "status": r["status"], "error": r["error"],
              "required": r["case"]["required"], "metrics": r["metrics"],
              "timing": r["timing"], "gate": r["gate"]} for r in results),
            key=lambda x: x["case_id"]),
        "summary": {"n_cases": len(results), "n_breach": n_breach,
                    "gate_ok": n_breach == 0},
    }
    out_path = Path(resolve_out(args))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(round_floats(out), indent=2, sort_keys=True) + "\n")
    print(f"wrote {out_path}")
    return 0 if n_breach == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
