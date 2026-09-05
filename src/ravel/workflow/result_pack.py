#!/usr/bin/env python3
"""Assemble a run's RESULT-PACK: result.json (thin headline/verdict) + figures.json.

A run's answer is today scattered across sr_yields.json (raw per-SR yields),
pyhf_exclusion/exclusion.json (the limit), provenance.json (prose), the cert json
(A*e verdict), and a plots INDEX -- with TWO different on-disk layout conventions
between runs. The benchmark gate + audit then reconstruct the headline by re-deriving
the physics and reading prose. This tool emits ONE machine-checkable, versioned shape
so a reader parses the headline directly instead of reconstructing it.

  result.json  -- the THIN headline + verdict layer. It POINTS at (does not re-store)
                  sr_yields.json / exclusion.json / provenance.json / the cert json;
                  it carries the headline fields the gate's score_* functions compute
                  (driving_sr, mu95_obs/exp + band, s95, best_sr, sigma reference,
                  cert verdict + A*e tier, the mu95-stability anchor) plus the two
                  REQUIRED enums (stat_mode, detector_mode) and a keyed limitations[].
  figures.json -- per-figure {filename, what_it_shows, source_ref/hepdata_table,
                  criteria_pass}, promoted from the plots/named INDEX.md (or, where no
                  INDEX exists, discovered from the standardized plot filenames).

RESULT.md stays the human narrative and should be GENERATED-FROM / cross-checked
against result.json (the numbers in the prose are the numbers in the pack).

This is a stdlib-only assembler: it READS already-computed artifacts and normalizes
them; it does not re-run any physics. Fail-loud -- a missing REQUIRED source artifact
is a hard error (the run is not packable), matching the other _infrastructure tools.

Usage:
  result_pack.py --rundir <run> --stat-mode <enum> --detector-mode <enum>
                 [--limitations '<key>:<text>;<key>:<text>;...']
                 [--analysis-id ID] [--routine NAME] [--model STR]
                 [--m-parent M] [--m-lsp M] [--lumi-fb L] [--driving-sr SR]
                 [--sigma-lo-pb X] [--out <dir>]

  stat-mode    one of: published-likelihood | simplified-likelihood |
               best-sr-counting | combined-counting | stability-only |
               blocked-shape-fit | sensitivity-expected-only | none-survey
  detector-mode one of: rivet-smearing | simpleanalysis-delphes | particle-level |
               effmap-folded | delphes-custom-uncertified

Most identity fields (analysis_id, routine, model, m_parent/m_lsp, driving_sr, ...)
are inferred from the run's provenance.json + the cert json + exclusion.json; pass the
--<field> flags only to override an inference or fill a gap the artifacts don't carry.
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.workflow"

import argparse
import datetime
import json
import os
import re
import sys

SCHEMA_VERSION = 1

# The two REQUIRED enums on the pack (the folded-in ADOPT item).
# stat_mode: how the 95% CLs limit was set. The spec enum is extended with
# 'combined-counting' for the multi-SR counting combination (e.g. C1N2's scored
# 2l+3l fit), which the original 5-member enum could not express (recon flag to
# the spec owner); the original five remain valid.
STAT_MODES = (
    "published-likelihood",
    "simplified-likelihood",
    "best-sr-counting",
    "combined-counting",
    "stability-only",
    # (CR-027 / Option B) the scoped binned-template shape-fit engine result; blocked-shape-fit is
    # now only the fallback when the engine cannot represent the fit or its R5 gate will not close.
    "shape-fit",
    "blocked-shape-fit",
    # (CR-009 / trial gap G-AD-11) the sensitivity-study class: EXPECTED-only comparisons
    # (S/sqrt(B), expected-CLs reach) with no observed-data exclusion claimed -- both 2026-07-04
    # generality trials shipped without a result.json because no enum fit. And the survey class:
    # a summary/survey deliverable that quotes OTHER analyses' published limits, none of its own.
    "sensitivity-expected-only",
    "none-survey",
)
DETECTOR_MODES = (
    "rivet-smearing",
    "simpleanalysis-delphes",
    "particle-level",
    "effmap-folded",
    # (CR-134) Delphes fast-sim + custom uncertified selection (Option-C detector variant):
    # proxy-labeled, no exclusion of record until the acc*eff certification closes
    "delphes-custom-uncertified",
)

EXP_MEDIAN_IDX = 2  # exp_limits = [-2σ, -1σ, median, +1σ, +2σ]; mirror run_benchmark


class PackError(Exception):
    """A required source artifact is missing/malformed, or the inputs are invalid."""


def die(msg):
    raise PackError(msg)


def load_json(path, what):
    if not os.path.isfile(path):
        die(f"required {what} not found: {path}")
    if os.path.getsize(path) == 0:
        die(f"required {what} is empty: {path}")
    try:
        with open(path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        die(f"{what} is not valid JSON ({path}): {e}")


def normalize_sr(name):
    """pyhf channel names may carry the cutflow SR in brackets: 'SR3L[SR3L_Low]'."""
    return name.split("[", 1)[1].rstrip("]") if "[" in name else name


# --------------------------------------------------------------------------- #
#  Source-artifact discovery (normalizes the two on-disk layout conventions)
# --------------------------------------------------------------------------- #

def find_cert(rundir, routine, analysis_id):
    """The cert json lives in-run (outputs/cutflow_cert.json) for validate_cutflow
    runs, OR under evidence/validation/studies/<id>.json for the run-local certify_axe
    path. Return (abs_path, pointer_repo_relative_or_abs)."""
    in_run = os.path.join(rundir, "outputs", "cutflow_cert.json")
    if os.path.isfile(in_run):
        return in_run
    # framework/validation sibling: walk up to the repo root, try <routine>/<id>.
    repo = _repo_root(rundir)
    if repo:
        valdir = os.path.join(repo, "evidence", "validation", "studies")
        cands = []
        if routine:
            cands.append(os.path.join(valdir, f"{routine.lower().replace('_', '-')}.json"))
            # certify_axe stamps a lowercase-suffixed name, e.g. *_c1n2.json
            base = routine.replace("ATLAS_", "").replace("CMS_", "")
            cands += _glob(valdir, base)
        if analysis_id:
            cands += _glob(valdir, analysis_id.replace("ins", ""))
        for c in cands:
            if c and os.path.isfile(c):
                return c
    return None


def _repo_root(rundir):
    """Walk up from the run dir to the repo root (the dir holding DIRECTORY.md)."""
    d = os.path.abspath(rundir)
    for _ in range(8):
        if os.path.isfile(os.path.join(d, "DIRECTORY.md")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def _glob(directory, needle):
    if not os.path.isdir(directory):
        return []
    out = []
    for fn in os.listdir(directory):
        if fn.endswith(".json") and needle and needle.lower().replace("_", "-") in fn.lower().replace("_", "-"):
            out.append(os.path.join(directory, fn))
    return sorted(out)


def find_index_md(rundir):
    """Locate the plots INDEX.md. Layout A (gluino-merged) has none; layout B has
    plots/named/INDEX.md; the unmerged sibling has plots/<routine>/named/INDEX.md.
    Return its abs path or None."""
    plots = os.path.join(rundir, "plots")
    if not os.path.isdir(plots):
        return None
    for root, _dirs, files in os.walk(plots):
        if "INDEX.md" in files:
            return os.path.join(root, "INDEX.md")
    return None


def discover_plots(rundir):
    """Every deliverable image under plots/ (png/pdf), keyed by basename-without-ext.
    Returns {stem: {png?, pdf?}} with repo-relative-ish (run-relative) pointers."""
    plots = os.path.join(rundir, "plots")
    found = {}
    if not os.path.isdir(plots):
        return found
    for root, _dirs, files in os.walk(plots):
        for fn in files:
            stem, ext = os.path.splitext(fn)
            if ext.lower() not in (".png", ".pdf"):
                continue
            rel = os.path.relpath(os.path.join(root, fn), rundir)
            found.setdefault(stem, {})[ext.lower().lstrip(".")] = rel
    return found


def rel_to_run(rundir, abspath):
    """Pointer the pack stores: path relative to the run dir when inside it, else
    relative to the repo root (so evidence/validation/studies/<id>.json stays meaningful)."""
    if abspath is None:
        return None
    abspath = os.path.abspath(abspath)
    inside = os.path.relpath(abspath, os.path.abspath(rundir))
    if not inside.startswith(".."):
        return inside
    repo = _repo_root(rundir)
    if repo:
        return os.path.relpath(abspath, repo)
    return abspath


# --------------------------------------------------------------------------- #
#  figures.json  (promoted from the plots/named INDEX.md)
# --------------------------------------------------------------------------- #

def parse_index_table(index_path):
    """Parse the INDEX.md markdown table:
       | File | orig id | shows | region / definition | source |
    Returns a list of dicts. Tolerates the stub (header only -> [])."""
    rows = []
    if not index_path or not os.path.isfile(index_path):
        return rows
    with open(index_path) as f:
        lines = f.read().splitlines()
    in_table = False
    for line in lines:
        s = line.strip()
        if not s.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        low = [c.lower() for c in cells]
        if "file" in low and "orig id" in "".join(low):
            in_table = True            # header row
            continue
        if set("".join(cells)) <= set("-: "):
            continue                   # separator row
        if not in_table:
            continue
        # pad/truncate to the 5 known columns
        cells = (cells + [""] * 5)[:5]
        fname, orig_id, shows, defn, source = cells
        rows.append({
            "filename": fname.strip("`"),
            "orig_id": orig_id.strip("`"),
            "what_it_shows": shows,
            "region_definition": defn,
            "source": source,
        })
    return rows


def split_source(source):
    """Pull a HEPData table id / REF id out of the free-text source column."""
    if not source:
        return None, None
    hep = None
    m = re.search(r"HEPData[^)\]]*?(Table\s*\d+|ins\d+|data\d+\.yaml|d\d+-x\d+)", source, re.I)
    if m:
        hep = m.group(0)
    ref = None
    m = re.search(r"\bREF\s+(d\d+-x\d+(?:-y\d+)?)", source)
    if m:
        ref = "REF " + m.group(1)
    else:
        m = re.search(r"\b(d\d+-x\d+(?:-y\d+)?)\b", source)
        if m:
            ref = m.group(1)
    return ref, hep


def orig_id_from_filename(stem):
    """The naming scheme is <routine>__<origID>__<label>; recover origID."""
    parts = stem.split("__")
    return parts[1] if len(parts) >= 3 else None


def load_figure_target(rundir):
    """The FIGURE CONTRACT (<rundir>/inputs/figure_target.json, written by figure_target.py):
    which specific published figure this run reproduces + the generated counterpart. Optional --
    older runs carry none; when present it is embedded top-level in figures.json, and a target
    that was DECLARED but never FULFILLED (generated_counterpart null) is WARNed loudly."""
    path = os.path.join(rundir, "inputs", "figure_target.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            doc = json.load(f)
    except json.JSONDecodeError as e:
        print(f"WARN (result_pack): {path} is not valid JSON ({e}); figure_target omitted",
              file=sys.stderr)
        return None
    for tgt in doc.get("targets", []):
        if not tgt.get("generated_counterpart"):
            print(f"WARN (result_pack): figure target {tgt.get('figure_id') or '(description-only)'} "
                  f"(role {tgt.get('role')}) was DECLARED but has no generated counterpart -- "
                  f"the contract is unfulfilled (figure_target.py attach-generated)",
                  file=sys.stderr)
    return doc


def build_figures(rundir, index_path, plot_files):
    """figures.json: one entry per deliverable figure, promoted from the INDEX
    when it exists+is populated, else discovered from the standardized filenames.
    criteria_pass is NEW (the INDEX doesn't carry it) -- left null = unrecorded,
    to be set by the plot-criteria check (docs/workflow/checklists/plot-criteria.md).
    When the run declares a figure contract (inputs/figure_target.json), it is
    embedded top-level as 'figure_target'."""
    index_rows = parse_index_table(index_path)
    by_name = {r["filename"]: r for r in index_rows}
    figures = []
    seen = set()

    # 1) every PNG deliverable (the primary, paper-facing raster), enriched by INDEX.
    for stem in sorted(plot_files):
        files = plot_files[stem]
        png = files.get("png")
        if not png:
            continue
        fname = os.path.basename(png)
        row = by_name.get(fname) or by_name.get(stem + ".png") or {}
        ref, hep = split_source(row.get("source", ""))
        figures.append({
            "filename": rel_to_run(rundir, os.path.join(rundir, png)),
            "pdf": rel_to_run(rundir, os.path.join(rundir, files["pdf"])) if files.get("pdf") else None,
            "orig_id": row.get("orig_id") or orig_id_from_filename(stem),
            "what_it_shows": row.get("what_it_shows") or None,
            "region_definition": row.get("region_definition") or None,
            "source_ref": ref,
            "hepdata_table": hep,
            "criteria_pass": None,   # set by plot-criteria.md check; null = unrecorded
        })
        seen.add(fname)

    # 2) INDEX rows whose file we did not find on disk (record, flag missing).
    for r in index_rows:
        if r["filename"] in seen:
            continue
        ref, hep = split_source(r.get("source", ""))
        figures.append({
            "filename": r["filename"],
            "pdf": None,
            "orig_id": r.get("orig_id") or orig_id_from_filename(os.path.splitext(r["filename"])[0]),
            "what_it_shows": r.get("what_it_shows") or None,
            "region_definition": r.get("region_definition") or None,
            "source_ref": ref,
            "hepdata_table": hep,
            "criteria_pass": None,
            "_note": "listed in INDEX.md but file not found on disk",
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "rundir": os.path.basename(os.path.normpath(rundir)),
        "index_source": rel_to_run(rundir, index_path) if index_path else None,
        "figure_target": load_figure_target(rundir),   # the figure contract (null = undeclared)
        "n_figures": len(figures),
        "figures": figures,
    }


# --------------------------------------------------------------------------- #
#  result.json  (the thin headline / verdict layer)
# --------------------------------------------------------------------------- #

def parse_limitations(raw):
    """'key:text; key2:text2' -> [{key, note}], keyed by the SPEC's limitations[].

    Split only on a ';' that PRECEDES a 'word-key:' token, so a free-text note may
    itself contain semicolons (e.g. 'fast-sim-floor:soft-lepton under-count; intrinsic
    10-20% floor'). A bare entry with no key becomes key 'note'. Accept '|' as an
    explicit unambiguous separator too.
    """
    out = []
    if not raw:
        return out
    raw = raw.strip()
    # split on the explicit '|' first if present (caller opted into it)
    if "|" in raw:
        chunks = [c for c in (s.strip() for s in raw.split("|")) if c]
    else:
        # else split a ';' only when the next non-space token is 'key:' (key = word-like)
        chunks = [c.strip() for c in re.split(r";\s*(?=[\w.-]+\s*:)", raw) if c.strip()]
    for chunk in chunks:
        m = re.match(r"([\w.-]+)\s*:\s*(.*)", chunk, re.S)
        if m:
            out.append({"key": m.group(1).strip(), "note": m.group(2).strip()})
        else:
            out.append({"key": "note", "note": chunk.strip()})
    return out


def cert_driving_row(cert, driving_sr):
    """Find the cert row for the driving SR (matched by name)."""
    rows = cert.get("rows", [])
    if driving_sr:
        for r in rows:
            if normalize_sr(r.get("sr", "")) == driving_sr:
                return r
    return None


def resolve_driving_sr(cert, excl, override):
    """The driving SR, resolved the way the benchmark gate consumes it.

    Priority: explicit --driving-sr override > the cert json's own driving_sr key
    (certify_axe stamps one; e.g. C1N2) > the SR matching exclusion.json best_sr
    (the most-sensitive single SR the limit is driven by; validate_cutflow certs
    carry no driving_sr key and mark SEVERAL rows role=driving, so best_sr is the
    correct single disambiguator) > a lone role=driving cert row.
    """
    if override:
        return override
    if cert and cert.get("driving_sr"):
        return cert["driving_sr"]
    best = normalize_sr(excl["best_sr"]) if excl.get("best_sr") else None
    if best:
        # prefer best_sr when it is present as a cert row (it always should be)
        if cert is None:
            return best
        names = {normalize_sr(r.get("sr", "")) for r in cert.get("rows", [])}
        if best in names:
            return best
        return best
    if cert:
        drv = [r for r in cert.get("rows", []) if r.get("role") == "driving"]
        if len(drv) == 1:
            return normalize_sr(drv[0]["sr"])
    return None


def build_result(args, rundir, prov, excl, cert, cert_ptr,
                 sr_yields, ptr):
    """Assemble the thin headline. Identity fields prefer the explicit flag, then
    the cert json, then provenance prose; numbers come from exclusion.json."""

    # --- identity (cert json carries the cleanest discrete fields) ---
    routine = args.routine or cert.get("routine") if cert else args.routine
    routine = routine or _routine_from_prov(prov)
    analysis_id = args.analysis_id or _analysis_id_from_routine(routine)
    model = args.model or (prov.get("model") if prov else None)

    # driving SR (resolved the way the benchmark gate consumes it).
    best_sr = normalize_sr(excl["best_sr"]) if excl.get("best_sr") else None
    driving_sr = resolve_driving_sr(cert, excl, args.driving_sr)

    # --- limit headline (from exclusion.json) ---
    mu95_obs = excl.get("obs_limit")
    band = excl.get("exp_limits")
    if not isinstance(band, list) or len(band) != 5:
        die(f"exclusion.json exp_limits must be a 5-entry band; got {band!r}")
    mu95_exp = band[EXP_MEDIAN_IDX]
    excluded_obs = (mu95_obs < 1.0) if mu95_obs is not None else None

    # driving-SR s95 in events (per_sr µ * s); the pack POINTS at per_sr but carries
    # the driving-SR headline directly so the gate need not re-derive it.
    per_sr = excl.get("per_sr", {})
    dentry = None
    for k, v in per_sr.items():
        if normalize_sr(k) == driving_sr:
            dentry = v
            break
    s95_obs = s95_exp = driving_s = None
    if dentry:
        driving_s = dentry.get("s")
        if dentry.get("obs_limit") is not None and driving_s is not None:
            s95_obs = dentry["obs_limit"] * driving_s
        if dentry.get("exp_median") is not None and driving_s is not None:
            s95_exp = dentry["exp_median"] * driving_s

    # --- sigma reference / k-factor ---
    k = excl.get("sigma_scale_k")
    if k is None and prov:
        k = prov.get("sigma_scale_k")
    sigma_lo_pb = args.sigma_lo_pb
    if sigma_lo_pb is None and prov:
        sigma_lo_pb = prov.get("sigma_pb")
    sigma_ref_fb = (sigma_lo_pb * 1000.0 * k
                    if (sigma_lo_pb is not None and k is not None) else None)
    sigma_ul_ours_fb = (mu95_obs * sigma_ref_fb
                        if (mu95_obs is not None and sigma_ref_fb is not None) else None)
    sigma_source = prov.get("sigma_source") if prov else None

    # --- per-SR yields summary (POINTER + thin summary, not a re-store) ---
    yields_summary = []
    for row in sr_yields:
        yields_summary.append({
            "name": normalize_sr(row.get("name", "")),
            "n": row.get("n"),
            "b": row.get("b"),
            "db": row.get("db"),
            "s": row.get("s"),
        })

    # --- cert (A*e) verdict + driving residual ---
    cert_block = None
    if cert:
        drow = cert_driving_row(cert, driving_sr)
        ratio = drow.get("ratio") if drow else None
        residual = abs(ratio - 1.0) if ratio is not None else None
        cert_block = {
            "verdict": cert.get("verdict"),
            "tier": tier_of(residual),
            "driving_sr": driving_sr,
            "driving_ratio": ratio,
            "driving_residual": residual,
            "worst_driving_mu95_impact": cert.get("worst_driving_mu95_impact"),
            "n_attributed": sum(1 for r in cert.get("rows", []) if r.get("attribution")),
            "pointer": cert_ptr,
        }

    # --- fidelity verdict: derived from the cert verdict + the attribution rows.
    # The cert is the selection-level fidelity gate; surface its verdict as the
    # pack's fidelity headline (PASS/WARN/FAIL), with the attributed cause classes.
    fidelity = None
    if cert:
        causes = sorted({a["cause_class"]
                         for r in cert.get("rows", [])
                         if (a := r.get("attribution")) and a.get("cause_class")})
        fidelity = {
            "verdict": cert.get("verdict"),
            "attributed_causes": causes,
            "source": "selection-level cutflow A*e cert (validate_cutflow / certify_axe)",
        }

    result = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": datetime.datetime.now(datetime.timezone.utc)
                                  .replace(microsecond=0).isoformat(),
        "generator": "result_pack.py",
        "rundir": os.path.basename(os.path.normpath(rundir)),

        # identity
        "analysis_id": analysis_id,
        "routine": routine,
        "model": model,
        "m_parent": args.m_parent,
        "m_lsp": args.m_lsp,
        "lumi_fb": args.lumi_fb if args.lumi_fb is not None
                   else (prov.get("lumi_fb") if prov else None),

        # the two REQUIRED enums (validated below)
        "stat_mode": args.stat_mode,
        "detector_mode": args.detector_mode,
        "detector_path": args.detector_mode,   # spec alias (SPEC names it detector_path)

        # limit headline
        "driving_sr": driving_sr,
        "best_sr": best_sr,
        "best_sr_matches": (best_sr == driving_sr) if (best_sr and driving_sr) else None,
        "mu95_obs": mu95_obs,
        "mu95_exp": mu95_exp,
        "mu95_exp_band": band,        # [-2σ,-1σ,median,+1σ,+2σ]
        "excluded_obs": excluded_obs,
        "s95_obs": s95_obs,
        "s95_exp": s95_exp,
        "driving_sr_s": driving_s,

        # sigma reference / k-factor (sigma-source headline)
        "sigma_lo_pb": sigma_lo_pb,
        "sigma_scale_k": k,
        "sigma_ref_fb": sigma_ref_fb,
        "sigma_ul_ours_fb": sigma_ul_ours_fb,
        "sigma_source": sigma_source,

        # stability anchor (the mu95-regression baseline the gate checks)
        "mu95_baseline": mu95_obs,    # this run's mu95_obs IS its own stability anchor

        # per-SR yields summary (thin) + POINTERS (not re-stored raw artifacts)
        "n_srs": len(yields_summary),
        "sr_yields_summary": yields_summary,
        "exclusion_mode": excl.get("mode"),
        "cert": cert_block,
        "fidelity": fidelity,
        "pointers": ptr,

        # keyed limitations
        "limitations": parse_limitations(args.limitations),
    }
    return result


def tier_of(residual):
    """A*e tier ladder (Ideal 0.05 / Good 0.1 / Acceptable 0.3), mirroring cases.json."""
    if residual is None:
        return None
    for tier, thr in (("Ideal", 0.05), ("Good", 0.1), ("Acceptable", 0.3)):
        if residual <= thr:
            return tier
    return "BELOW"


def _routine_from_prov(prov):
    if not prov:
        return None
    r = prov.get("routine", "")
    # "ATLAS_2016_I1458270 (Rivet 4.1.3)" -> "ATLAS_2016_I1458270"
    m = re.match(r"\s*([A-Za-z0-9_]+)", r)
    return m.group(1) if m else None


def _analysis_id_from_routine(routine):
    if not routine:
        return None
    m = re.search(r"I(\d+)", routine)
    if m:
        return "ins" + m.group(1)
    return routine.lower()


# --------------------------------------------------------------------------- #
#  main
# --------------------------------------------------------------------------- #

def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rundir", required=True, help="the run directory to pack")
    ap.add_argument("--stat-mode", required=True, choices=STAT_MODES,
                    help="REQUIRED enum: how the 95%% CLs limit was set")
    ap.add_argument("--detector-mode", required=True, choices=DETECTOR_MODES,
                    help="REQUIRED enum: the detector/fast-sim path")
    ap.add_argument("--limitations", default="",
                    help="keyed list 'key:text; key2:text2; ...'")
    ap.add_argument("--analysis-id", help="override (else inferred from routine)")
    ap.add_argument("--routine", help="override (else from cert/provenance)")
    ap.add_argument("--model", help="override (else from provenance.model)")
    ap.add_argument("--m-parent", type=float, help="parent mass [GeV]")
    ap.add_argument("--m-lsp", type=float, help="LSP mass [GeV]")
    ap.add_argument("--lumi-fb", type=float, help="override (else provenance.lumi_fb)")
    ap.add_argument("--driving-sr", help="override (else cert driving_sr / best SR)")
    ap.add_argument("--sigma-lo-pb", type=float, help="override (else provenance.sigma_pb)")
    ap.add_argument("--out", help="output dir (default: --rundir)")
    args = ap.parse_args(argv)

    rundir = os.path.abspath(args.rundir)
    if not os.path.isdir(rundir):
        die(f"--rundir is not a directory: {rundir}")
    out_dir = os.path.abspath(args.out) if args.out else rundir
    os.makedirs(out_dir, exist_ok=True)

    # --- locate + load the REQUIRED source artifacts (fail loud) ---
    sr_path = os.path.join(rundir, "outputs", "sr_yields.json")
    excl_path = os.path.join(rundir, "outputs", "pyhf_exclusion", "exclusion.json")
    prov_path = os.path.join(rundir, "provenance.json")

    sr_yields = load_json(sr_path, "sr_yields.json")
    if not isinstance(sr_yields, list) or not sr_yields:
        die(f"sr_yields.json must be a non-empty array of SR objects: {sr_path}")
    excl = load_json(excl_path, "exclusion.json")
    prov = load_json(prov_path, "provenance.json")

    cert_path = find_cert(rundir, args.routine or _routine_from_prov(prov),
                          args.analysis_id)
    if cert_path is None:
        die("cert json not found (looked for outputs/cutflow_cert.json and "
            "evidence/validation/studies/<routine|id>.json) -- a run must carry an A*e "
            "cert to be packed; pass --routine/--analysis-id if the name differs")
    cert = load_json(cert_path, "cert json")

    # --- pointers (NOT re-stores): the require_files the gate already checks ---
    pointers = {
        "sr_yields": rel_to_run(rundir, sr_path),
        "exclusion": rel_to_run(rundir, excl_path),
        "provenance": rel_to_run(rundir, prov_path),
        "cert": rel_to_run(rundir, cert_path),
    }

    # --- assemble result.json ---
    result = build_result(args, rundir, prov, excl, cert,
                          pointers["cert"], sr_yields, pointers)

    # validate the two REQUIRED enums are populated (argparse already constrains
    # the value set; assert non-empty so a future programmatic caller can't slip a
    # blank through).
    if result["stat_mode"] not in STAT_MODES:
        die(f"stat_mode {result['stat_mode']!r} not in {STAT_MODES}")
    if result["detector_mode"] not in DETECTOR_MODES:
        die(f"detector_mode {result['detector_mode']!r} not in {DETECTOR_MODES}")

    # --- assemble figures.json ---
    index_path = find_index_md(rundir)
    plot_files = discover_plots(rundir)
    figures = build_figures(rundir, index_path, plot_files)
    result["pointers"]["figures"] = "figures.json"
    result["n_figures"] = figures["n_figures"]

    # --- write ---
    res_out = os.path.join(out_dir, "result.json")
    fig_out = os.path.join(out_dir, "figures.json")
    with open(res_out, "w") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    with open(fig_out, "w") as f:
        json.dump(figures, f, indent=2)
        f.write("\n")

    # --- console summary ---
    print(f"RESULT-PACK written (schema_version={SCHEMA_VERSION}):")
    print(f"  result.json  -> {res_out}")
    print(f"  figures.json -> {fig_out}  ({figures['n_figures']} figure(s))")
    print(f"  stat_mode={result['stat_mode']}  detector_mode={result['detector_mode']}")
    print(f"  driving_sr={result['driving_sr']}  best_sr={result['best_sr']}  "
          f"mu95_obs={result['mu95_obs']}  mu95_exp={result['mu95_exp']}")
    print(f"  cert={result['cert']['verdict'] if result['cert'] else '-'}  "
          f"A*e tier={result['cert']['tier'] if result['cert'] else '-'}  "
          f"limitations={len(result['limitations'])}")
    if index_path is None:
        print("  NOTE: no plots INDEX.md found -- figures discovered from filenames "
              "(criteria_pass left null; run the plot-criteria check to set it)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PackError as e:
        print(f"ERROR (result_pack): {e}", file=sys.stderr)
        sys.exit(1)
