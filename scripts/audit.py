#!/usr/bin/env python3
"""Readiness audit for the reinterpretation pipeline.

A diagnostic readiness report: scans the repository and the run records it carries and scores
each requirement (the readiness dimensions R1..R8) as pass/warn/fail with evidence, then prints
a readiness %. Pure stdlib so it runs anywhere. Run from anywhere: `python scripts/audit.py`.

Each check is evidence-based (it reads real files / counts real runs), so the score moves
only when the repository's evidence changes.

Read-only by default: with no flags this only computes + prints (writes nothing). Pass
`--write [--out PATH]` to regenerate the report on disk (default PATH: `local-runs/audit.md`,
which is gitignored, unless an optional settings file names another report).
A readiness board is DESIGNED to move as the pipeline improves, so this is write-suppression
only — not a diff-and-fail gate; content drift is not asserted here.
"""
import argparse, os, re, glob, json, datetime, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from ravel.evidence_layout import load_registry, is_public_tree, source_settings
PUBLIC_TREE = is_public_tree(ROOT)
# An optional settings file may name a policy document and a report path.
SOURCE_SETTINGS = source_settings(ROOT)
def p(*a): return os.path.join(ROOT, *a)
def exists(*a): return os.path.exists(p(*a))
def read(path):
    try:
        return open(p(path), errors="replace").read()
    except Exception:
        return ""

_INPROGRESS_RE = re.compile(
    r"PARTIAL\(|no (?:physics )?result is claimed|status:[* ]*prepared|"
    r"not yet (?:been )?(?:run|executed)|has not been (?:run|executed)", re.I)

def _has_result(d):
    """A recorded HEADLINE run carries a non-trivial RESULT.md (the trial-runs/README
    convention). Scan SUB-POINTS and bare native/intermediate dirs have NO RESULT.md."""
    try:
        return os.path.getsize(os.path.join(d, "RESULT.md")) > 200
    except OSError:
        return False

def _inprogress(d):
    try:
        return bool(_INPROGRESS_RE.search(open(os.path.join(d, "RESULT.md"), errors="replace").read()))
    except OSError:
        return False

# Survey/sensitivity-mode exemption (2026-07-06, stricter-not-inflating): a run whose
# DELIVERABLE is not a limit (survey / summary plot / expected-only sensitivity study —
# docs/reference/scope.md stat modes none-survey / sensitivity-expected-only) must not be scored as
# "missing its pyhf result". Exemption requires ALL of: (a) an explicit machine-readable
# declaration line in RESULT.md ("Deliverable: survey|summary|sensitivity ... no exclusion
# claimed" — absence means scored as before), (b) NO statistical artifact on disk, and
# (c) NO own-limit claim in the prose (obs_limit / mu95 / µ₉₅) — an artifact or claim VETOES.
_SURVEY_DECL_RE = re.compile(r"^Deliverable:\s*(survey|summary|sensitivity)[^\n]*no exclusion claimed",
                             re.I | re.M)
_OWN_LIMIT_RE = re.compile(r"obs_limit|mu95|µ₉₅")

def _stat_artifact(r):
    """A run's statistical deliverable on disk: a per-point pyhf exclusion (standard or native
    layout) OR a scan's aggregated scan.json. Shared by R2 scoring and the survey exemption."""
    std = os.path.join(r, "outputs", "pyhf_exclusion", "exclusion.json")
    if os.path.exists(std): return std
    for g in (glob.glob(os.path.join(r, "**", "exclusion.json"), recursive=True),
              glob.glob(os.path.join(r, "**", "scan.json"), recursive=True)):
        if g: return g[0]
    return None

def _survey_exempt(d):
    try:
        t = open(os.path.join(d, "RESULT.md"), errors="replace").read()
    except OSError:
        return False
    return bool(_SURVEY_DECL_RE.search(t)) and _stat_artifact(d) is None \
        and not _OWN_LIMIT_RE.search(t)

def _run_dirs():
    """Every candidate run dir — ANY trial-runs/* directory except the infrastructure/archive/
    scratch underscore family, so an undated run dir such as sleptonscan_fig3_SCAN is included."""
    return [d for d in glob.glob(p("trial-runs", "*"))
            if os.path.isdir(d) and not os.path.basename(d).startswith("_")]

def trial_runs():
    """The HEADLINE-run set that the per-run dimensions (R2 statistical model, R5 provenance)
    score. A headline run carries a non-trivial RESULT.md AND does not self-declare in-progress
    AND is not a declared survey/sensitivity deliverable (see _survey_exempt).
    Deliberately EXCLUDES, because counting them mismeasures readiness:
      * scan SUB-POINTS and bare native/intermediate dirs (no RESULT.md) — grid points harvested
        into a parent scan; the scan's statistical deliverable is its scan.json (the contour),
        not a standalone per-point exclusion+provenance, so each is not an independent result;
      * runs that self-declare PARTIAL / PREPARED-not-yet-run / "no result is claimed" — work in
        progress, not a finished output to be scored (surfaced via in_progress_runs()); and
      * declared no-limit deliverables (surveyed via survey_runs()) — scoring them as missing
        pyhf results punishes correct product-contract behavior (docs/reference/scope.md)."""
    return sorted(d for d in _run_dirs()
                  if _has_result(d) and not _inprogress(d) and not _survey_exempt(d))

def in_progress_runs():
    """RESULT-bearing dirs that self-declare in-progress (PARTIAL / PREPARED). Present and listed
    transparently in the audit evidence, but deliberately NOT scored (they claim no result)."""
    return sorted(os.path.basename(d) for d in _run_dirs()
                  if _has_result(d) and _inprogress(d))

def survey_runs():
    """Declared survey/summary/sensitivity deliverables (no limit claimed, none on disk).
    Listed transparently in R2/R5 details, deliberately not scored there."""
    return sorted(os.path.basename(d) for d in _run_dirs()
                  if _has_result(d) and not _inprogress(d) and _survey_exempt(d))

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
def status_from(score):
    return PASS if score >= 0.85 else (WARN if score >= 0.4 else FAIL)


# ---- the checks: each returns (req, title, score 0..1, status, detail, evidence[]) ----
def c_validation():
    certs = glob.glob(p("trial-runs", "*", "outputs", "cutflow_cert.json"))
    runs = trial_runs()
    routines = set()
    for r in runs:
        m = re.search(r"ATLAS_\d+_I\d+|ATLAS-SUSY-[\d-]+", read(os.path.relpath(os.path.join(r, "RESULT.md"), ROOT)))
        if m: routines.add(m.group(0))
    n_routines = max(len(routines), 1)
    # verdict-based: a cert only counts fully if it carries an explicit tiered verdict AND the
    # driving-SR tolerance language — file existence alone is not certification (the old logic
    # masked the squark deficit). A bare/legacy cert is worth a quarter.
    graded, fails = 0.0, []
    for c in certs:
        t = read(os.path.relpath(c, ROOT))
        verdict = re.search(r"\b(PASS|WARN|FAIL)\b", t)
        tiered = re.search(r"driving|contributing|attribution|acceptance|a.?.?ε|cause_class", t, re.I)
        if verdict and tiered:
            graded += 1.0
            if verdict.group(1) == "FAIL": fails.append(os.path.basename(c))
        elif verdict or tiered:
            graded += 0.5
        else:
            graded += 0.25
    score = min(graded / n_routines, 1.0)
    if fails: score = min(score, 0.6)   # an un-remediated FAIL caps the dimension
    return ("R1", "Physics validation (tiered cutflow verdict)", score, status_from(score),
            f"{len(certs)} cert(s) for ~{len(routines)} routine(s); graded by verdict+tiering"
            + (f"; UNREMEDIATED FAIL: {fails}" if fails else ""),
            [os.path.relpath(c, ROOT) for c in certs] or ["validation studies are empty"])

def c_provenance():
    runs = trial_runs()
    if not runs: return ("R5", "Provenance capture", 0.0, FAIL, "no runs", [])
    stamps = [os.path.join(r, "provenance.json") for r in runs
              if os.path.exists(os.path.join(r, "provenance.json"))]   # among headline runs only
    ok = 0
    src = 0.0
    lo_only = []
    for r in runs:
        t = read(os.path.relpath(os.path.join(r, "RESULT.md"), ROOT))
        markers = [bool(re.search(k, t, re.I)) for k in (r"cross.?section|σ|sigma|pb", r"madgraph|rivet|pythia|pyhf",
                                                          r"hepdata|bundled|likelihood|REF", r"ATLAS|CMS")]
        if all(markers): ok += 1
        # σ-source: full credit only for a CONSISTENT higher-order normalisation — an NLO/NNLL/
        # k-factor statement in RESULT.md, or a provenance.json carrying sigma_scale_k != 1.0.
        # Pure-LO runs get half credit with an explicit 'LO-only' note (honest, not punitive).
        nlo_stmt = bool(re.search(r"k.?factor|NLO|NLL|nnll|hepi|x-?sec\s*wg|sigma_scale", t, re.I))
        k_prov = None
        try:
            k_prov = json.load(open(os.path.join(r, "provenance.json"))).get("sigma_scale_k")
        except Exception:
            pass
        if nlo_stmt or (isinstance(k_prov, (int, float)) and k_prov != 1.0):
            src += 1.0
        else:
            src += 0.5
            lo_only.append(os.path.basename(r))
    base = ok / len(runs)
    score = 0.5 * base + 0.3 * (len(stamps) / len(runs)) + 0.2 * (src / len(runs))  # +σ-source field
    ip = in_progress_runs()
    sv = survey_runs()
    return ("R5", "Provenance + σ-source capture", score, status_from(score),
            f"{ok}/{len(runs)} headline RESULT.md carry σ+tool+source+analysis; σ-source credit {src:g}/{len(runs)} "
            f"(LO-only at half credit: {lo_only or 'none'}); {len(stamps)} enforced provenance.json"
            + (f"; {len(ip)} in-progress run(s) not scored: {ip}" if ip else "")
            + (f"; {len(sv)} declared survey/sensitivity run(s) not scored (no MC σ to source): {sv}" if sv else ""),
            [os.path.relpath(s, ROOT) for s in stamps]
            + ([f"LO-only (half σ-source credit): {', '.join(lo_only)}"] if lo_only else [])
            or ["no provenance.json stamps yet"])

def c_statmodel():
    runs = trial_runs()
    if not runs: return ("R2", "Statistical rigour (pyhf)", 0.0, FAIL, "no runs", [])
    hits, modes, ev = [], [], []
    for r in runs:
        s = _stat_artifact(r)   # per-point exclusion.json or a scan's scan.json (module-level)
        if s:
            hits.append(r); ev.append(os.path.relpath(s, ROOT))
            if s.endswith("exclusion.json"):
                try: modes.append(json.load(open(s)).get("mode", "?"))
                except Exception: pass
            else: modes.append("scan")
    score = len(hits) / len(runs)
    ip = in_progress_runs()
    sv = survey_runs()
    return ("R2", "Statistical rigour (analysis's own model via pyhf)", score, status_from(score),
            f"{len(hits)}/{len(runs)} headline runs have a pyhf statistical result "
            f"(modes: {','.join(sorted(set(modes))) or '-'})"
            + (f"; {len(ip)} in-progress run(s) not scored: {ip}" if ip else "")
            + (f"; {len(sv)} declared survey/sensitivity run(s) not scored: {sv}" if sv else ""),
            ev or ["no statistical result found"])

def c_completedata():
    # a documented working full-table route + at least one fetched complete table set that VERIFIES:
    # every found HEPData submission.yaml must parse (yaml.safe_load_all) and declare tables;
    # unparseable sets are NOT counted and surface as WARN evidence (no silent corruption).
    fetched = glob.glob(p("trial-runs", "20*", "outputs", "hepdata", "tables", "*")) \
              + glob.glob(p("trial-runs", "20*", "outputs", "hepdata", "*.yaml"))
    subs = glob.glob(p("trial-runs", "20*", "outputs", "hepdata", "tables", "**", "submission.yaml"),
                     recursive=True)
    parsed, bad, n_tables = [], [], 0
    try:
        import yaml
        for s in subs:
            rel = os.path.relpath(s, ROOT)
            try:
                docs = list(yaml.safe_load_all(open(s, errors="replace")))
                n = sum(1 for d in docs if isinstance(d, dict) and d.get("name") and d.get("data_file"))
                if n == 0:
                    raise ValueError("parses but declares no tables")
                parsed.append(f"{rel} ({n} tables)")
                n_tables += n
            except Exception as e:
                bad.append(f"WARN unparseable (not counted): {rel}: {e}")
        if subs and not parsed:
            fetched = []   # every fetched set is corrupt -> no complete-data credit
    except ImportError:
        bad.append("WARN: PyYAML unavailable in this python — submission.yaml parse check skipped")
    route = "full-table route" in read("docs/workflow/checklists/data-acquisition.md").lower()
    score = (0.5 if route else 0.0) + (0.5 if fetched else 0.0)
    return ("R3", "Complete published data (full tables)", score, status_from(score),
            f"working full-table route documented: {bool(route)}; fetched table files: {len(fetched)}; "
            f"submission.yaml verified: {len(parsed)}/{len(subs)} parse ({n_tables} tables)"
            + (f"; {len(bad)} problem(s)" if bad else ""),
            (parsed[:4] + bad) or ["no complete tables fetched yet"])

def c_complexity():
    # a run/record on a multi-bin / multi-region / jigsaw analysis handled end-to-end
    hits = []
    for r in trial_runs():
        t = read(os.path.relpath(os.path.join(r, "RESULT.md"), ROOT)).lower()
        if re.search(r"multi-?bin|multi-?region|jigsaw|control region|per-bin|combined likelihood", t):
            hits.append(os.path.basename(r))
    note = exists("docs", "workflow", "checklists", "complex-analysis.md")
    score = (0.6 if hits else 0.0) + (0.4 if note else 0.0)
    return ("R4", "Complex-analysis support (first-class)", score, status_from(score),
            f"complex run(s): {hits or 'none'}; complex-handling doc: {bool(note)}",
            hits or ["no complex analysis run end-to-end yet"])

def c_fidelity():
    verdicts = glob.glob(p("trial-runs", "*", "**", "*fidelity*"), recursive=True)
    score = min(len(verdicts) / 1.0, 1.0) if verdicts else 0.0
    return ("R6", "Visual fidelity vs published figures", score, status_from(score),
            f"{len(verdicts)} recorded figure-overlay fidelity verdict(s)",
            [os.path.relpath(v, ROOT) for v in verdicts[:4]] or ["no published-figure comparison recorded yet"])

def c_crosscheck():
    cc = glob.glob(p("trial-runs", "*", "outputs", "**", "*smodels*"), recursive=True)
    score = 1.0 if cc else 0.0
    return ("R7", "Independent recasting cross-check", score, status_from(score),
            f"{len(cc)} recorded cross-check(s) (SModelS/MA5/CheckMATE vs our pyhf)",
            [os.path.relpath(c, ROOT) for c in cc[:4]] or ["no independent cross-check recorded yet"])

def c_docs():
    # The documentation index: check_repository resolves every page it links.
    need = ["docs/workflow/README.md", "docs/workflow/session-guide.md", "README.md", "DIRECTORY.md",
            "docs/README.md", "docs/workflow/checklists/validation.md"]
    steps = glob.glob(p("workflow", "steps", "*.md"))
    have = [n for n in need if exists(*n.split("/"))]
    score = (len(have) / len(need)) * (1.0 if len(steps) >= 7 else 0.7)
    return ("R8", "Documentation", score, status_from(score),
            f"{len(have)}/{len(need)} core docs present; {len(steps)} step files",
            [n for n in need if not exists(*n.split('/'))] or ["all core docs present"])

def c_deps():
    manifest = exists("docs", "reference", "environment.md") or exists("requirements-replay.lock")
    score = 1.0 if manifest else 0.0
    return ("R8", "Dependency / version manifest", score, status_from(score),
            f"environment manifest present: {bool(manifest)}",
            ["docs/reference/environment.md"] if manifest else ["no pinned environment manifest yet"])

def c_limits():
    t = read("docs/reference/limitations.md")
    score = 1.0 if len(t) > 200 else (0.5 if t else 0.0)
    return ("R8", "Known-limitations registry", score, status_from(score),
            f"docs/reference/limitations.md present ({len(t)} chars)",
            ["docs/reference/limitations.md"] if t else ["missing"])

def c_plotcriteria():
    # publication-grade plotting: the criteria checklist + at least one mplhep overlay produced
    crit = exists("docs", "workflow", "checklists", "plot-criteria.md")
    overlays = glob.glob(p("trial-runs", "20*", "plots", "**", "*overlay*.p*"), recursive=True)
    mplhep = "mplhep" in read("src/ravel/plotting/overlay_on_data.py")
    score = (0.4 if crit else 0.0) + (0.3 if overlays else 0.0) + (0.3 if mplhep else 0.0)
    return ("R6", "Publication-grade plots (mplhep + criteria)", score, status_from(score),
            f"plot-criteria.md: {bool(crit)}; mplhep overlay tool: {mplhep}; overlays produced: {len(overlays)}",
            [os.path.relpath(o, ROOT) for o in overlays[:3]] or ["no mplhep overlay produced yet"])

def c_merging():
    # ME/PS merging available + applied where colored SRs need it
    doc = exists("docs", "workflow", "checklists", "merging.md")
    applied = []
    for r in trial_runs():
        t = read(os.path.relpath(os.path.join(r, "RESULT.md"), ROOT)).lower()
        if re.search(r"merg|ckkw|\bmlm\b|xqcut|jetmatching", t): applied.append(os.path.basename(r))
    score = (0.5 if doc else 0.0) + (0.5 if applied else 0.0)
    return ("R1", "ME/PS merging (multi-jet fidelity)", score, status_from(score),
            f"merging.md: {bool(doc)}; run(s) recording merging: {applied or 'none'}",
            applied or ["no merged run recorded yet"])

def _distribution_policy():
    """The machine-readable distribution registry loads, and any policy document that an optional
    settings file names is present."""
    try:
        load_registry(ROOT)
    except (ValueError, OSError):
        return False
    policy = SOURCE_SETTINGS.get("distribution_policy")
    return PUBLIC_TREE or not policy or exists(*policy.split("/"))

def c_hygiene():
    # distribution hygiene: the distribution policy + no trial-run references in the agent-facing distributable
    dist = _distribution_policy()
    pat = re.compile(r"gluino-pair|squark-pair|slepton_200|2026-06")
    refs = []
    scan = glob.glob(p("docs", "workflow", "**", "*.md"), recursive=True) + [p("README.md"), p("docs", "workflow", "session-guide.md")]
    for f in scan:
        if os.path.basename(f) == "DISTRIBUTION.md":  # the doc that *defines* the pattern is exempt
            continue
        if pat.search(read(os.path.relpath(f, ROOT))): refs.append(os.path.relpath(f, ROOT))
    clean = not refs
    score = (0.5 if dist else 0.0) + (0.5 if clean else 0.0)
    return ("R8", "Distribution hygiene (no trial-run refs)", score, status_from(score),
            f"distribution policy: {bool(dist)}; agent-facing trial-run references: {len(refs)}",
            refs or ["distributable is clean of trial-run references"])


CHECKS = [c_validation, c_merging, c_statmodel, c_completedata, c_complexity, c_provenance,
          c_fidelity, c_plotcriteria, c_crosscheck, c_docs, c_deps, c_limits, c_hygiene]


def render():
    """Build the full audit report text (no file I/O). Pure function of the repo's current state."""
    rows = [f() for f in CHECKS]
    readiness = round(100 * sum(r[2] for r in rows) / len(rows))
    stamp = os.environ.get("AUDIT_DATE", "")  # Date.now() unavailable in some contexts; allow override
    if not stamp:
        try: stamp = datetime.date.today().isoformat()
        except Exception: stamp = "(date unset)"
    lines = [f"# AUDIT — pipeline readiness  ·  {readiness}%", "",
             f"_Generated by `scripts/audit.py` ({stamp}). Requirements R1–R8 are the readiness dimensions below._",
             "", "| Req | Dimension | Status | Score | Evidence / detail |", "|---|---|---|---|---|"]
    for req, title, score, st, detail, ev in rows:
        badge = {"PASS": "🟢 PASS", "WARN": "🟡 WARN", "FAIL": "🔴 FAIL"}[st]
        lines.append(f"| {req} | {title} | {badge} | {score:.2f} | {detail} |")
    lines += ["", "## Evidence", ""]
    for req, title, score, st, detail, ev in rows:
        lines.append(f"- **{req} {title}** ({st}): " + "; ".join(ev))
    lines += ["", f"**Readiness: {readiness}%** "
              f"({sum(r[3]==PASS for r in rows)} pass / {sum(r[3]==WARN for r in rows)} warn / "
              f"{sum(r[3]==FAIL for r in rows)} fail of {len(rows)} dimensions)."]
    return "\n".join(lines) + "\n"


def _summary_line(text):
    """The one-line readiness summary (first heading line of render()'s output), e.g.
    '# AUDIT — pipeline readiness  ·  96%' -> 'readiness 96%', plus the per-dimension lines."""
    readiness_pct = re.search(r"pipeline readiness\s+·\s+(\d+)%", text)
    pct = readiness_pct.group(1) if readiness_pct else "?"
    out_lines = [f"readiness {pct}%"]
    for m in re.finditer(r"^\| (R\d+) \| (.+?) \| (?:🟢|🟡|🔴) (PASS|WARN|FAIL) \| ([\d.]+) \|", text, re.M):
        req, title, st, score = m.groups()
        out_lines.append(f"  {st:4s} {req} {title} ({float(score):.2f})")
    return "\n".join(out_lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true",
                     help="regenerate the report on disk (default: read-only --check)")
    ap.add_argument("--out", default=None,
                     help="write path when --write is given (default: local-runs/audit.md, or the "
                          "report that an optional settings file names)")
    args = ap.parse_args()

    text = render()
    if args.write:
        report = None if PUBLIC_TREE else SOURCE_SETTINGS.get("audit_report")
        default = p(*report.split("/")) if report else p("local-runs", "audit.md")
        out = args.out if args.out else default
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        open(out, "w").write(text)
        print(_summary_line(text))
        print(f"written -> {out}")
    else:
        print(_summary_line(text))


if __name__ == "__main__":
    main()
