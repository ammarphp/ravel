#!/usr/bin/env python3
"""Readiness audit for the reinterpretation pipeline.

Scans the repo + the trial runs and scores each requirement (R1..R8 in STATUS.md) as
pass/warn/fail with evidence, then prints a readiness %. Pure stdlib so it runs anywhere.
Run from anywhere: `python framework/audit.py`.

Each check is evidence-based (it reads real files / counts real runs), so the score moves
only when the pipeline actually improves — it is the "are we on track" signal, not decoration.

Read-only by default: with no flags this only computes + prints (writes nothing). Pass
`--write [--out PATH]` to regenerate the report on disk (default PATH is framework/AUDIT.md).
A readiness board is DESIGNED to move as the pipeline improves, so this is write-suppression
only — not a diff-and-fail gate; content drift is not asserted here.
"""
import argparse, os, re, glob, json, datetime, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
# PRODUCT-CONTRACT stat modes none-survey / sensitivity-expected-only) must not be scored as
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
    scratch underscore family. (The old '20*' glob made undated dirs like the flagship
    sleptonscan_fig3_SCAN invisible to the audit — widened 2026-07-06.)"""
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
        pyhf results punishes correct PRODUCT-CONTRACT behavior."""
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
    certs = glob.glob(p("framework", "validation", "*.md")) + glob.glob(p("framework", "validation", "*.json"))
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
            [os.path.relpath(c, ROOT) for c in certs] or ["framework/validation/ is empty"])

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
              + glob.glob(p("trial-runs", "20*", "outputs", "hepdata", "*.yaml")) \
              + glob.glob(p("framework", "data", "**", "*.yaml"), recursive=True)
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
    route = "full-table route" in read("workflow/checklists/data-acquisition.md").lower() \
            or exists("framework", "DATA-ROUTES.md")
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
    note = exists("framework", "validation", "complex.md") or exists("workflow", "checklists", "complex-analysis.md")
    score = (0.6 if hits else 0.0) + (0.4 if note else 0.0)
    return ("R4", "Complex-analysis support (first-class)", score, status_from(score),
            f"complex run(s): {hits or 'none'}; complex-handling doc: {bool(note)}",
            hits or ["no complex analysis run end-to-end yet"])

def c_fidelity():
    verdicts = glob.glob(p("trial-runs", "20*", "**", "*fidelity*"), recursive=True) \
               + glob.glob(p("framework", "validation", "*fidelity*"))
    score = min(len(verdicts) / 1.0, 1.0) if verdicts else 0.0
    return ("R6", "Visual fidelity vs published figures", score, status_from(score),
            f"{len(verdicts)} recorded figure-overlay fidelity verdict(s)",
            [os.path.relpath(v, ROOT) for v in verdicts[:4]] or ["no published-figure comparison recorded yet"])

def c_crosscheck():
    cc = glob.glob(p("framework", "crosscheck", "*.md")) \
         + glob.glob(p("framework", "crosscheck", "*.smodels")) \
         + glob.glob(p("trial-runs", "20*", "outputs", "**", "*smodels*"), recursive=True) \
         + glob.glob(p("framework", "validation", "*crosscheck*"))
    score = 1.0 if cc else 0.0
    return ("R7", "Independent recasting cross-check", score, status_from(score),
            f"{len(cc)} recorded cross-check(s) (SModelS/MA5/CheckMATE vs our pyhf)",
            [os.path.relpath(c, ROOT) for c in cc[:4]] or ["no independent cross-check recorded yet"])

def c_docs():
    need = ["workflow/WORKFLOW.md", "workflow/SESSION-MANUAL.md", "README.md", "DIRECTORY.md",
            "pedagogical/pipeline-guide.pdf", "workflow/checklists/validation.md"]
    steps = glob.glob(p("workflow", "steps", "*.md"))
    have = [n for n in need if exists(*n.split("/"))]
    score = (len(have) / len(need)) * (1.0 if len(steps) >= 7 else 0.7)
    return ("R8", "Documentation", score, status_from(score),
            f"{len(have)}/{len(need)} core docs present; {len(steps)} step files",
            [n for n in need if not exists(*n.split('/'))] or ["all core docs present"])

def c_deps():
    manifest = exists("framework", "ENVIRONMENT.md") or glob.glob(p("framework", "*environment*.yml")) \
               or glob.glob(p("framework", "*.lock"))
    score = 1.0 if manifest else 0.0
    return ("R8", "Dependency / version manifest", score, status_from(score),
            f"environment manifest present: {bool(manifest)}",
            ["framework/ENVIRONMENT.md"] if manifest else ["no pinned environment manifest yet"])

def c_limits():
    t = read("framework/KNOWN-LIMITATIONS.md")
    score = 1.0 if len(t) > 200 else (0.5 if t else 0.0)
    return ("R8", "Known-limitations registry", score, status_from(score),
            f"KNOWN-LIMITATIONS.md present ({len(t)} chars)",
            ["framework/KNOWN-LIMITATIONS.md"] if t else ["missing"])

def c_plotcriteria():
    # publication-grade plotting: the criteria checklist + at least one mplhep overlay produced
    crit = exists("workflow", "checklists", "plot-criteria.md")
    overlays = glob.glob(p("trial-runs", "20*", "plots", "**", "*overlay*.p*"), recursive=True)
    mplhep = "mplhep" in read("trial-runs/_infrastructure/overlay_on_data.py")
    score = (0.4 if crit else 0.0) + (0.3 if overlays else 0.0) + (0.3 if mplhep else 0.0)
    return ("R6", "Publication-grade plots (mplhep + criteria)", score, status_from(score),
            f"plot-criteria.md: {bool(crit)}; mplhep overlay tool: {mplhep}; overlays produced: {len(overlays)}",
            [os.path.relpath(o, ROOT) for o in overlays[:3]] or ["no mplhep overlay produced yet"])

def c_merging():
    # ME/PS merging available + applied where colored SRs need it
    doc = exists("workflow", "checklists", "merging.md")
    applied = []
    for r in trial_runs():
        t = read(os.path.relpath(os.path.join(r, "RESULT.md"), ROOT)).lower()
        if re.search(r"merg|ckkw|\bmlm\b|xqcut|jetmatching", t): applied.append(os.path.basename(r))
    score = (0.5 if doc else 0.0) + (0.5 if applied else 0.0)
    return ("R1", "ME/PS merging (multi-jet fidelity)", score, status_from(score),
            f"merging.md: {bool(doc)}; run(s) recording merging: {applied or 'none'}",
            applied or ["no merged run recorded yet"])

def c_hygiene():
    # distribution hygiene: the criteria doc + no trial-run references in the agent-facing distributable
    dist = exists("workflow", "DISTRIBUTION.md")
    pat = re.compile(r"gluino-pair|squark-pair|slepton_200|2026-06")
    refs = []
    scan = glob.glob(p("workflow", "**", "*.md"), recursive=True) + [p("README.md"), p("workflow", "SESSION-MANUAL.md")]
    for f in scan:
        if os.path.basename(f) == "DISTRIBUTION.md":  # the doc that *defines* the pattern is exempt
            continue
        if pat.search(read(os.path.relpath(f, ROOT))): refs.append(os.path.relpath(f, ROOT))
    clean = not refs
    score = (0.5 if dist else 0.0) + (0.5 if clean else 0.0)
    return ("R8", "Distribution hygiene (no trial-run refs)", score, status_from(score),
            f"DISTRIBUTION.md: {bool(dist)}; agent-facing trial-run references: {len(refs)}",
            refs or ["distributable is clean of trial-run references"])

_GREEN_WHEN_RE = re.compile(r"^\s*([\w.]+)\s*==\s*(\S+)\s*$")


def _gate_verdict(gate, _cache={}):
    """Resolve one prompt's `gate` object to (green: bool, why: str). NEVER raises — every
    failure mode (missing artifact, unparseable predicate, a selftest that can't even import)
    is caught and reported as NOT green, per PRODUCT-CONTRACT section 5 (CR-035): a served
    claim defaults to distrusted, not trusted, when its evidence can't be checked.

    kind==artifact: the artifact JSON must exist and its `green_when` field==VALUE predicate
    (a dotted path into the JSON, e.g. 'verdict' or 'a.b.verdict') must hold.
    kind==selftest: `python3 <ref> --selftest` must exit 0.
    kind in (decision, deferred): can NEVER be green — these gate PARTIAL prompts only; a
    served/served-with-refusal status riding a decision/deferred gate is illegitimate by
    construction (the anti-gaming point of this whole reconciler).
    Cached by (kind, ref-or-artifact) within one process so a shared gate (or a repeat call)
    doesn't re-run a subprocess or re-read a file twice."""
    if not gate:
        return False, "no gate field"
    kind = gate.get("kind")
    if kind in ("decision", "deferred"):
        return False, f"gate kind '{kind}' can never credit a served status"
    if kind == "artifact":
        art = gate.get("artifact")
        key = ("artifact", art)
        if key in _cache:
            return _cache[key]
        if not art:
            result = (False, "gate has no 'artifact' path")
        else:
            path = p(art)
            if not os.path.exists(path):
                result = (False, f"artifact missing: {art}")
            else:
                try:
                    with open(path) as f:
                        data = json.load(f)
                except Exception as e:
                    result = (False, f"artifact unreadable/invalid JSON: {e}")
                else:
                    gw = gate.get("green_when", "")
                    gm = _GREEN_WHEN_RE.match(gw)
                    if not gm:
                        result = (False, f"unparseable green_when: {gw!r}")
                    else:
                        field, expect = gm.groups()
                        val = data
                        for part in field.split("."):
                            if isinstance(val, dict) and part in val:
                                val = val[part]
                            else:
                                val = None
                                break
                        ok = (str(val) == expect)
                        result = (ok, f"{field}={val!r} (want {expect!r}) in {art}")
        _cache[key] = result
        return result
    if kind == "selftest":
        ref = gate.get("ref")
        key = ("selftest", ref)
        if key in _cache:
            return _cache[key]
        if not ref:
            result = (False, "gate has no 'ref' script")
        else:
            try:
                r = subprocess.run([sys.executable, p(ref), "--selftest"],
                                    cwd=ROOT, capture_output=True, text=True, timeout=120)
                result = (r.returncode == 0, f"`{ref} --selftest` exit={r.returncode}")
            except Exception as e:
                # a selftest that can't even run (missing script, ImportError inside it that
                # somehow escapes as a launch failure, etc.) is a RED gate, not an audit crash.
                result = (False, f"selftest could not run: {e}")
        _cache[key] = result
        return result
    return False, f"unknown gate kind: {kind!r}"


def c_capability():
    """R9 (audit v2, CR-019): CAPABILITY COVERAGE against the demand-side board — now a
    STATUS-RATIFYING RECONCILER (Task 5, PRODUCT-CONTRACT section 5 / CR-035), not a verbatim
    reader of the matrix's self-attested `status` string. Reads
    framework/capability-matrix.json (maintained by the census/roadmap work, C8) and hands the
    parsed dict to _score_capability() (the pure, independently-testable reconciler)."""
    t = read("framework/capability-matrix.json")
    if not t:
        return ("R9", "Capability coverage (7-prompt board)", 0.0, "FAIL",
                "capability-matrix.json missing — run the census (CR-019)",
                ["framework/capability-matrix.json missing"])
    return _score_capability(json.loads(t))


def _score_capability(m):
    """Pure reconciler: takes an already-parsed capability-matrix.json dict and returns the R9
    check tuple. Split out from c_capability() so tests can hand it a mutated matrix (e.g. a
    partial prompt hand-flipped to 'served') without touching the file on disk — the anti-
    gaming property under test is a property of THIS function, not of file I/O.

    A served / served-with-refusal prompt earns its 1.0 credit ONLY while its named gate is
    actually green (an artifact's verdict field, or a selftest's exit code); a red or
    illegitimate (decision/deferred) gate demotes that prompt to 0.5 credit — as if it had
    self-reported partial — and a FAIL line names the discrepancy. partial keeps its 0.5
    (a decision/deferred gate is the correct, honest shape there); unbuilt/decision-pending
    stay 0.0. This is what makes R9 non-gameable: editing one JSON string from 'partial' to
    'served' no longer moves the needle unless the underlying evidence is actually green."""
    prompts = m.get("prompts", {})
    served_statuses = ("served", "served-with-refusal")
    base_credit = {"served": 1.0, "served-with-refusal": 1.0, "partial": 0.5,
                   "unbuilt": 0.0, "decision-pending": 0.0}

    derived, ev, fails, warns = {}, [], [], []
    for key, v in sorted(prompts.items()):
        status = v.get("status")
        gate = v.get("gate")
        if status in served_statuses:
            if gate is None:
                # migration-safe: a served prompt with no gate at all is a WARN, not a hard
                # red, during rollout — credit it as claimed but flag it loudly. After Part A
                # every prompt in the matrix carries a gate, so this branch should not fire.
                derived[key] = base_credit[status]
                warns.append(f"R9 WARN: prompt {key} claims '{status}' but has no gate field "
                              f"(migration) — credited as claimed; add a gate")
                ev.append(f"{key}: {status} [NO GATE — migration WARN, credited {derived[key]:.1f}]")
            else:
                green, why = _gate_verdict(gate)
                if green:
                    derived[key] = 1.0
                    ev.append(f"{key}: {status} [gate {gate.get('kind')} GREEN — {why}]")
                else:
                    derived[key] = 0.5
                    fail_line = (f"R9: prompt {key} claims '{status}' but its gate is RED "
                                 f"({why}) — credited as partial; fix the run or downgrade the matrix")
                    fails.append(fail_line)
                    ev.append(fail_line)
        else:
            derived[key] = base_credit.get(status, 0.0)
            extra = f" (flip_when: {gate.get('flip_when')})" if gate and gate.get("flip_when") else ""
            ev.append(f"{key}: {status}{extra}")

    score = (sum(derived.values()) / len(prompts)) if prompts else 0.0
    n = {s: sum(1 for v in prompts.values() if v.get("status") == s)
         for s in ("served", "served-with-refusal", "partial", "unbuilt", "decision-pending")}
    full = n["served"] + n["served-with-refusal"]
    detail = (f"{full}/{len(prompts)} prompts fully served "
              f"({n['served-with-refusal']} as designed refusals); {n['partial']} partial; "
              f"{n['unbuilt']} unbuilt — the capability layer is the open half "
              f"(CAPABILITY-ROADMAP W3); credits gate-RATIFIED (schema_version 2)")
    if fails:
        detail += f"; {len(fails)} claimed-served-but-gate-RED (downgraded to partial credit)"
    if warns:
        detail += f"; {len(warns)} gate-missing WARN(s)"
    st = "PASS" if score >= 0.99 else ("WARN" if score >= 0.5 else "FAIL")
    if fails and st == "PASS":
        st = "WARN"   # a red-gated served claim can never look fully clean, even if score rounds high
    return ("R9", "Capability coverage (7-prompt board)", score, st, detail, ev)


CHECKS = [c_validation, c_merging, c_statmodel, c_completedata, c_complexity, c_provenance,
          c_fidelity, c_plotcriteria, c_crosscheck, c_docs, c_deps, c_limits, c_hygiene,
          c_capability]


def render():
    """Build the full AUDIT.md text (no file I/O). Pure function of the repo's current state."""
    rows = [f() for f in CHECKS]
    readiness = round(100 * sum(r[2] for r in rows) / len(rows))
    stamp = os.environ.get("AUDIT_DATE", "")  # Date.now() unavailable in some contexts; allow override
    if not stamp:
        try: stamp = datetime.date.today().isoformat()
        except Exception: stamp = "(date unset)"
    cap = next((r for r in rows if r[0] == "R9"), None)
    cap_line = cap[4] if cap else "capability board missing — run the census (CR-019)"
    lines = [f"# AUDIT — pipeline readiness  ·  {readiness}%", "",
             f"_Generated by `framework/audit.py` ({stamp}). Requirements R1–R8 are defined in `STATUS.md`;_",
             f"_R9 = audit-v2 DEMAND-side capability coverage (CR-019): {cap_line}._",
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
                     help="write path when --write is given (default: framework/AUDIT.md)")
    args = ap.parse_args()

    text = render()
    if args.write:
        out = args.out if args.out else p("framework", "AUDIT.md")
        open(out, "w").write(text)
        print(_summary_line(text))
        print(f"written -> {out}")
    else:
        print(_summary_line(text))


if __name__ == "__main__":
    main()
