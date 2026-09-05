#!/usr/bin/env python3
"""validate_run_state.py -- the lifecycle ORDERING + COMPLETENESS + INVARIANT gate.

Sits between validate_task_contract.py (schema of ONE artifact, the contract) and
verify_pack.py (INTERNAL consistency of whatever artifacts happen to exist, exits 0 on a
run with none). Neither asserts "the declared mode produced its REQUIRED artifacts, in
order, with its cross-stage invariants satisfied" -- this is that gate.

Composition, not duplication: this tool imports validate_task_contract.validate() and runs
it FIRST (a run on an invalid contract cannot mean anything downstream); at the
verification stage it shells out to verify_pack.py and folds its exit into that stage's
result. It does not re-implement either tool's per-artifact shape checks.

Canonical stage order: task_contract, resource_census, trap_sweep, route, figure_contract,
basis_manifest, generation, analysis, statistics, result_pack, verification. Which stages
are REQUIRED/OPTIONAL/N-A/CONDITIONAL for a given task_mode is STAGE_MATRIX (below), and the
cross-stage INVARIANTS enforce things a per-stage presence check cannot see (R5-before-
limit-ships, resource-census-before-route, the likelihood<->selection pairing gate, ...).

GRANDFATHER (GATE_EPOCH="2026-07-08"): a run dated before the epoch, or lacking an inputs/
dir, is LEGACY -- missing trap_sweep.json / verification.json / resource_census.json
downgrade FAIL to WARN (status "waived-legacy") rather than retro-failing good historical
work. Every VALUE check that CAN run still runs at full severity; new runs get no waiver.

Stdlib-only, read-only, fail-loud.

Usage:
  validate_run_state.py --rundir <dir> [--stage <name>] [--contract <path>] [--strict] [--json]
  validate_run_state.py --rundir <dir> --backfill-plan     # print (don't write) what's missing
  validate_run_state.py --selftest

Exit codes: 0 PASS (WARNs allowed) * 1 required-stage-missing/out-of-order or invariant FAIL
            2 usage / rundir not a directory * 3 contract invalid (validate_task_contract)
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.validation"

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from ravel.validation import validate_task_contract  # noqa: E402
from ravel.workflow import result_pack             # noqa: E402
from ravel.workflow import provenance              # noqa: E402
from ravel.limits import claim_errors, read_limits, prose_errors, source_errors  # noqa: E402

GATE_EPOCH = "2026-07-08"
SKIP_DIRS = {"build", "logs", "__pycache__", ".git", "Events"}

STAGE_ORDER = (
    "task_contract", "resource_census", "trap_sweep", "route", "figure_contract",
    "basis_manifest", "generation", "analysis", "statistics", "result_pack", "verification",
)
TRAP_IDS = tuple(f"T{i}" for i in range(1, 13))

# STAGE_MATRIX[task_mode][stage] -> R | O | N/A | C2 | C6 | C9  (conditional footnotes below)
STAGE_MATRIX = {
    "survey":         dict(zip(STAGE_ORDER, ["R", "R", "R", "R", "O", "R", "N/A", "N/A", "N/A", "R", "R"])),
    # figure_contract=O (not R): a none-survey summary synthesizes MANY published limits into one
    # overlay -- it does not reproduce a single published figure, so figure_target.json is
    # genuinely optional here; completeness is carried by basis_manifest[R] + the separate
    # summary_audit.py gate (Task 4.2 fix, 2026-07-08).
    "summary_plot":   dict(zip(STAGE_ORDER, ["R", "R", "R", "R", "O", "R", "N/A", "N/A", "N/A", "R", "R"])),
    "reproduce":      dict(zip(STAGE_ORDER, ["R", "R", "R", "R", "R", "O", "C2", "R", "R", "R", "R"])),
    "reinterpret":    dict(zip(STAGE_ORDER, ["R", "R", "R", "R", "O", "C6", "C2", "R", "R", "R", "R"])),
    "projection":     dict(zip(STAGE_ORDER, ["R", "R", "R", "R", "R", "O", "O", "O", "R", "R", "R"])),
    "scan":           dict(zip(STAGE_ORDER, ["R", "R", "R", "R", "R", "O", "C2", "R", "R", "R", "R"])),
    "anomaly_search": dict(zip(STAGE_ORDER, ["R", "R", "R", "R", "O", "O", "C2", "O", "R", "R", "R"])),
    "no_routine":     dict(zip(STAGE_ORDER, ["R", "R", "R", "R", "O", "O", "C2", "O", "C9", "R", "R"])),
    "unsupported":    dict(zip(STAGE_ORDER, ["R", "N/A", "N/A", "R", "N/A", "N/A", "N/A", "N/A", "N/A", "N/A", "N/A"])),
}

# The three NEW-schema artifacts this task grandfathers for legacy (pre-epoch) runs.
WAIVABLE_ARTIFACTS = {"resource_census", "trap_sweep", "verification"}

R5_STATUSES = ("checked-pass", "checked-fail", "unavailable-published", "not-checked")


# --------------------------------------------------------------------------- #
#  migration / legacy
# --------------------------------------------------------------------------- #

def is_legacy(rundir):
    """A run is LEGACY (grandfathered) iff (its dirname carries a parseable YYYY-MM-DD prefix
    AND that date < GATE_EPOCH), OR it lacks an inputs/ dir entirely. A dirname with NO
    parseable date prefix but WITH an inputs/ dir is NOT legacy -- a missing date prefix is
    not itself a waiver, and the repo carries 60+ non-date-prefixed ACTIVE run dirs that must
    still be held to the full new-run requirements (resource_census/trap_sweep/verification)."""
    base = os.path.basename(os.path.normpath(rundir))
    if not os.path.isdir(os.path.join(rundir, "inputs")):
        return True
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", base)
    if not m:
        return False
    return m.group(1) < GATE_EPOCH


def missing_required_status(stage_key, legacy):
    if legacy and stage_key in WAIVABLE_ARTIFACTS:
        return "waived-legacy"
    return "FAIL"


# --------------------------------------------------------------------------- #
#  discovery helpers (reuse the on-disk conventions verify_pack/result_pack already know)
# --------------------------------------------------------------------------- #

def find_first_existing(rundir, *rels):
    for rel in rels:
        if os.path.isfile(os.path.join(rundir, rel)):
            return rel
    return None


def find_anywhere(rundir, filename):
    """Shallow candidates first (rundir/, outputs/, output/), else a full walk -- mirrors the
    'support BOTH outputs/ and native output/ and scan/survey layouts' requirement."""
    for d in ("", "outputs", "output"):
        p = os.path.join(rundir, d, filename) if d else os.path.join(rundir, filename)
        if os.path.isfile(p):
            return os.path.relpath(p, rundir)
    for root, dirs, files in os.walk(rundir):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and x != "execution" and not x.startswith(".")]
        if filename in files:
            return os.path.relpath(os.path.join(root, filename), rundir)
    return None


def find_all_anywhere(rundir, filename):
    hits = []
    for root, dirs, files in os.walk(rundir):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and x != "execution" and not x.startswith(".")]
        if filename in files:
            hits.append(os.path.relpath(os.path.join(root, filename), rundir))
    return sorted(hits)


def find_all_matching(rundir, pattern):
    """find_all_anywhere for a glob PATTERN (fnmatch on basenames) -- walking INTO Events/
    and logs/ like locate_lhe_gz does (pruning only build/__pycache__/.git): shower products
    and lhe_check sidecars live next to the LHE inside MadGraph procdirs, which the
    SKIP_DIRS-pruned walks would never see."""
    hits = []
    for root, dirs, files in os.walk(rundir):
        dirs[:] = [d for d in dirs if d not in ("build", "__pycache__", ".git", "execution")]
        for f in files:
            if fnmatch.fnmatch(f, pattern):
                hits.append(os.path.relpath(os.path.join(root, f), rundir))
    return sorted(hits)


def load_json_safe(rundir, rel):
    if rel is None:
        return None, None
    try:
        with open(os.path.join(rundir, rel)) as f:
            return json.load(f), None
    except (OSError, json.JSONDecodeError) as e:
        return None, str(e)


def generation_artifacts(rundir):
    """Presence-only (heavy artifacts are gitignored): outputs/**/sr_yields*.json,
    **/output/*_patch.json, logs/** (any file), output/native_objects.txt."""
    hits = []
    outputs = os.path.join(rundir, "outputs")
    if os.path.isdir(outputs):
        for root, dirs, files in os.walk(outputs):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                if re.match(r"sr_yields.*\.json$", f):
                    hits.append(os.path.relpath(os.path.join(root, f), rundir))
    for root, dirs, files in os.walk(rundir):
        dirs[:] = [d for d in dirs if d != "execution"]
        if os.path.basename(root) == "output":
            for f in files:
                if f.endswith("_patch.json"):
                    hits.append(os.path.relpath(os.path.join(root, f), rundir))
    logs = os.path.join(rundir, "logs")
    if os.path.isdir(logs):
        for root, dirs, files in os.walk(logs):
            dirs[:] = [d for d in dirs if d not in ("execution", "state")]
            if any(f.endswith(".log") for f in files):
                hits.append(os.path.relpath(root, rundir))
                break
    nat = os.path.join(rundir, "output", "native_objects.txt")
    if os.path.isfile(nat):
        hits.append(os.path.relpath(nat, rundir))
    return sorted(set(hits))


def locate_lhe_gz(rundir):
    """First *.lhe.gz under the rundir (walking INTO Events/, where MadGraph writes it)."""
    for root, dirs, files in os.walk(rundir):
        dirs[:] = [d for d in dirs if d not in ("build", "__pycache__", ".git", "execution")]
        for f in files:
            if f.endswith(".lhe.gz"):
                return os.path.join(root, f)
    return None


def lhe_producer_complete(rundir, lhe_path):
    """N4 barrier. An on-disk .lhe.gz is a COMPLETE MadGraph product iff (1) a logs/*.log carries the
    terminal 'Cross-section :' line, (2) the gzip decompresses to EOF (not a mid-write truncation),
    and (3) the banner nevents == the counted <event> records. Returns (ok, reason)."""
    import gzip
    xsec_seen = False
    logs_dir = os.path.join(rundir, "logs")
    if os.path.isdir(logs_dir):
        for root, dirs, files in os.walk(logs_dir):
            dirs[:] = [d for d in dirs if d != "execution"]
            for f in files:
                if not f.endswith(".log"):
                    continue
                try:
                    with open(os.path.join(root, f), encoding="utf-8", errors="replace") as fh:
                        if any("Cross-section :" in line for line in fh):
                            xsec_seen = True
                            break
                except OSError:
                    pass
            if xsec_seen:
                break
    nevents_banner = None
    n_events = 0
    try:
        with gzip.open(lhe_path, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if nevents_banner is None:
                    m = re.search(r"(\d+)\s*=\s*nevents", line)
                    if m:
                        nevents_banner = int(m.group(1))
                s = line.lstrip()
                if s.startswith("<event>") or s.startswith("<event "):
                    n_events += 1
    except (OSError, EOFError, gzip.BadGzipFile) as e:
        return False, f"LHE gzip truncated/mid-write ({type(e).__name__}: {e})"
    if not xsec_seen:
        return False, ("LHE present but no MadGraph 'Cross-section :' completion line in logs/ "
                       "(producer still running / mid-write)")
    if nevents_banner is not None and n_events != nevents_banner:
        return False, (f"LHE event count mismatch: banner nevents={nevents_banner} but counted "
                       f"{n_events} <event> records (consumed mid-write)")
    return True, f"producer complete: Cross-section line + gzip EOF, {n_events} events (banner {nevents_banner})"


def locate_signal_patch(rundir):
    hits = []
    for root, dirs, files in os.walk(rundir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        if os.path.basename(root) == "output":
            for f in files:
                if f.endswith("_patch.json"):
                    hits.append(os.path.join(root, f))
    return sorted(hits)[0] if hits else None


def locate_bkg_workspace(rundir, facts):
    """From provenance/exclusion pointer fields, else a bkg-only-named file anywhere."""
    for src_rel, keys in (
        (facts.get("statistics_path") if facts.get("statistics_artifact_name") == "exclusion.json"
         else find_anywhere(rundir, "exclusion.json"),
         ("bkg_workspace", "bkgonly", "workspace", "bkg")),
        (find_anywhere(rundir, "provenance.json"),
         ("bkg_workspace", "bkgonly_path", "workspace")),
    ):
        if not src_rel:
            continue
        doc, err = load_json_safe(rundir, src_rel)
        if err or not isinstance(doc, dict):
            continue
        for key in keys:
            v = doc.get(key)
            if isinstance(v, str):
                p = v if os.path.isabs(v) else os.path.join(rundir, v)
                if os.path.isfile(p):
                    return p
    for root, dirs, files in os.walk(rundir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            if re.search(r"bkg.?only.*\.json$", f, re.I):
                return os.path.join(root, f)
    return None


def traps_hit_ids(contract, trap_sweep_doc):
    """Union of trap_sweep.json's traps_hit[] (list[str] per the schema this task defines) and
    any legacy contract-embedded traps_hit[] (list[{id,...}], the pre-standalone-schema shape
    seen in existing task_contract.json files) -- a cheap, safe-default fallback."""
    ids = set()
    if isinstance(trap_sweep_doc, dict):
        for h in trap_sweep_doc.get("traps_hit", []) or []:
            if isinstance(h, str):
                ids.add(h)
            elif isinstance(h, dict) and h.get("id"):
                ids.add(h["id"])
    for h in (contract.get("traps_hit") or []):
        if isinstance(h, dict) and h.get("id"):
            ids.add(h["id"])
        elif isinstance(h, str):
            ids.add(h)
    return ids


# CHECK-IN-1-baselined inputs: the contract-fingerprinted files whose post-checkin change requires a
# DEVIATIONS.md row (D15). Shared by inv_deviations_on_change (post-hoc) and --edit-guard (moment-of).
BASELINED_INPUTS = ("task_contract.json", "resource_census.json", "trap_sweep.json",
                    "figure_target.json", "basis_manifest.json", "validations.json")


def load_run_state(rundir):
    """The Phase-1 L1 ledger, or None. Read locally (NOT via discover_facts) to keep the shared facts
    sweep untouched and to degrade safely when no run_state.json exists yet."""
    if not os.path.isfile(os.path.join(rundir, "run_state.json")):
        return None
    doc, err = load_json_safe(rundir, "run_state.json")
    return None if err or not isinstance(doc, dict) else doc


def baselined_inputs_changed(rundir):
    """Basenames of CHECK-IN-1-baselined inputs/ files that run_state.json.edits[] records an edit to,
    once a CHECK-IN 1 is on record. Empty (no trigger) unless the observer logged such an edit."""
    rs = load_run_state(rundir)
    if not rs:
        return []
    if not any(isinstance(c, dict) and c.get("id") == "CHECKIN1" for c in (rs.get("checkins") or [])):
        return []
    changed = set()
    for e in (rs.get("edits") or []):
        path = e.get("path") if isinstance(e, dict) else None
        if not path:
            continue
        norm = str(path).replace("\\", "/")
        if os.path.basename(norm) in BASELINED_INPUTS and ("/inputs/" in norm
                                                           or norm.startswith("inputs/")):
            changed.add(os.path.basename(norm))
    return sorted(changed)


def edit_guard(changed_path):
    """PostToolUse moment-of-change guard (D15): a just-edited CHECK-IN-1-baselined inputs/ file needs
    a DEVIATIONS.md row NAMING it. Returns 0 (allow) unless PATH is a baselined inputs/<file> whose
    rundir's DEVIATIONS.md does not name it -> 1 (block). The hook maps 1 -> its blocking exit 2."""
    ap_path = os.path.abspath(changed_path)
    base = os.path.basename(ap_path)
    parent = os.path.dirname(ap_path)
    if base not in BASELINED_INPUTS or os.path.basename(parent) != "inputs":
        print(f"edit-guard: {base} is not a baselined inputs/ file; allow", file=sys.stderr)
        return 0
    rundir = os.path.dirname(parent)
    dev = os.path.join(rundir, "DEVIATIONS.md")
    text = ""
    if os.path.isfile(dev):
        try:
            text = open(dev, encoding="utf-8", errors="replace").read()
        except OSError:
            text = ""
    if base in text:
        print(f"edit-guard: DEVIATIONS.md names {base}; allow", file=sys.stderr)
        return 0
    print(f"BLOCKED (edit-guard, D15): {base} is a CHECK-IN-1-baselined input; an edit to it requires "
          f"a DEVIATIONS.md row NAMING {base} in {rundir}. Record what changed + why, then proceed.",
          file=sys.stderr)
    return 1


def select_statistics_artifact_name(task_mode, stat_mode):
    """None-survey/blocked-shape-fit -> must be ABSENT (caller checks the forbidden set)."""
    if stat_mode in ("none-survey", "blocked-shape-fit"):
        return None
    if task_mode == "scan":
        return "scan.json"
    if stat_mode == "shape-fit":
        return "shape_fit.json"
    if stat_mode == "sensitivity-expected-only":
        return "sensitivity.json"
    return "exclusion.json"   # published/simplified-likelihood, best/combined-sr-counting, stability-only


def analysis_artifact(rundir, contract):
    p = os.path.join(rundir, "outputs", "cutflow_cert.json")
    if os.path.isfile(p):
        return os.path.relpath(p, rundir), "cutflow_cert"
    routine = None
    targets = contract.get("targets") or {}
    an = targets.get("analysis") or []
    if an:
        routine = str(an[0])
    try:
        found = result_pack.find_cert(rundir, routine, None)
    except Exception:
        found = None
    if found:
        absf, absr = os.path.abspath(found), os.path.abspath(rundir)
        return (os.path.relpath(absf, rundir) if absf.startswith(absr) else absf), "cert"
    fr = find_anywhere(rundir, "fold_result.json")
    if fr:
        return fr, "fold_result"
    return None, None


def result_pack_paths(rundir, task_mode):
    if task_mode == "scan":
        p = find_anywhere(rundir, "scan.json")
        return {"scan.json": p} if p else {}
    if task_mode in ("survey", "summary_plot"):
        if os.path.isfile(os.path.join(rundir, "outputs", "survey.json")):
            return {"outputs/survey.json": "outputs/survey.json"}
        alt = find_anywhere(rundir, "survey.json")
        return {"survey.json": alt} if alt else {}
    if task_mode == "projection":
        p = find_anywhere(rundir, "projection.json")
        return {"projection.json": p} if p else {}
    if task_mode == "anomaly_search":
        p = find_anywhere(rundir, "sensitivity.json")
        return {"sensitivity.json": p} if p else {}
    out = {}
    rp, fp = find_anywhere(rundir, "result.json"), find_anywhere(rundir, "figures.json")
    if rp:
        out["result.json"] = rp
    if fp:
        out["figures.json"] = fp
    return out


def parse_r5_row(ladder_text):
    """Parse the VERIFICATION-LADDER.md markdown table for the R5 row's status token. Row
    shapes vary ('| R5 | checked-pass | ... |' and '| R5 their-limit... | checked-pass | ...
    |') so match the leading cell starting with 'R5' and scan the remaining cells for a known
    status token."""
    for line in ladder_text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not cells or not re.match(r"^R5\b", cells[0]):
            continue
        for c in cells[1:]:
            for token in R5_STATUSES:
                if token in c:
                    return token
    return None


def run_verify_pack(rundir):
    vp = os.path.join(HERE, "verify_pack.py")
    try:
        out = subprocess.run([sys.executable, vp, rundir], capture_output=True, text=True, timeout=60)
    except Exception as e:
        return -1, f"could not run verify_pack.py: {e}"
    lines = out.stdout.strip().splitlines()
    tail = lines[-1] if lines else (out.stderr.strip().splitlines() or [""])[-1]
    return out.returncode, tail


# --------------------------------------------------------------------------- #
#  facts (one on-disk sweep, shared by every stage + invariant check)
# --------------------------------------------------------------------------- #

def discover_facts(rundir, contract):
    f = {
        "task_contract_path": find_first_existing(rundir, "inputs/task_contract.json", "task_contract.json"),
        "resource_census_path": find_first_existing(rundir, "inputs/resource_census.json"),
        "trap_sweep_path": find_first_existing(rundir, "inputs/trap_sweep.json"),
        "figure_target_path": find_first_existing(rundir, "inputs/figure_target.json"),
        "cost_preflight_path": find_first_existing(rundir, "inputs/cost_preflight.json"),
        "approval_path": find_first_existing(rundir, "inputs/checkin1_approval.json"),
        "basis_manifest_path": find_first_existing(rundir, "inputs/basis_manifest.json"),
        "generation_hits": generation_artifacts(rundir),
        "scan_manifest_path": find_anywhere(rundir, "scan_manifest.json"),
        "replane_path": find_anywhere(rundir, "replane.json"),
        "fold_result_path": find_anywhere(rundir, "fold_result.json"),
        "verification_json_path": "verification.json" if os.path.isfile(os.path.join(rundir, "verification.json")) else None,
        "ladder_path": "VERIFICATION-LADDER.md" if os.path.isfile(os.path.join(rundir, "VERIFICATION-LADDER.md")) else None,
        "deviations_path": "DEVIATIONS.md" if os.path.isfile(os.path.join(rundir, "DEVIATIONS.md")) else None,
        "result_md_path": "RESULT.md" if os.path.isfile(os.path.join(rundir, "RESULT.md")) else None,
    }
    f["trap_sweep_doc"] = None
    if f["trap_sweep_path"]:
        f["trap_sweep_doc"], _ = load_json_safe(rundir, f["trap_sweep_path"])

    f["scan_manifest_doc"] = None
    if f["scan_manifest_path"]:
        f["scan_manifest_doc"], _ = load_json_safe(rundir, f["scan_manifest_path"])

    task_mode, stat_mode = contract.get("task_mode"), contract.get("stat_mode")
    stat_name = select_statistics_artifact_name(task_mode, stat_mode)
    f["statistics_artifact_name"] = stat_name
    if stat_name is None:
        present = []
        for nm in ("exclusion.json", "scan.json", "shape_fit.json", "sensitivity.json"):
            present += find_all_anywhere(rundir, nm)
        f["statistics_path"], f["statistics_forbidden_present"] = None, present
    else:
        f["statistics_path"], f["statistics_forbidden_present"] = find_anywhere(rundir, stat_name), []

    f["scan_doc"] = None
    if stat_name == "scan.json" and f["statistics_path"]:
        f["scan_doc"], _ = load_json_safe(rundir, f["statistics_path"])

    f["analysis_path"], f["analysis_kind"] = analysis_artifact(rundir, contract)
    f["result_pack_paths"] = result_pack_paths(rundir, task_mode)
    f["hepmc_hits"] = find_all_matching(rundir, "*.hepmc") + find_all_matching(rundir, "*.hepmc.gz")
    f["lhe_check_artifacts"] = find_all_matching(rundir, "*.lhe_check.json")
    f["lhe_gz_path"] = locate_lhe_gz(rundir)
    f["ladder_record_path"] = find_first_existing(rundir, "logs/ladder.json", "inputs/ladder.json")
    return f


def resolve_level(stage, task_mode, contract, facts):
    base = STAGE_MATRIX[task_mode][stage]
    if base == "C2":     # generation R iff compute_plan in {smoke,full,scan}, else N/A
        return "R" if contract.get("compute_plan") in ("smoke", "full", "scan") else "N/A"
    if base == "C6":      # basis_manifest R for reinterpret if replane.json present or T3/T9 hit
        hit_ids = traps_hit_ids(contract, facts.get("trap_sweep_doc"))
        return "R" if (facts.get("replane_path") or "T3" in hit_ids or "T9" in hit_ids) else "O"
    if base == "C9":      # no_routine statistics keyed by stat_mode
        sm = contract.get("stat_mode")
        if sm == "sensitivity-expected-only":
            return "R"
        if sm == "blocked-shape-fit":
            return "N/A"
        return "O"
    return base


# --------------------------------------------------------------------------- #
#  per-stage checks -- each returns (status, artifact_display, checks[{name,level,msg}])
# --------------------------------------------------------------------------- #

def check_task_contract(rundir, contract, facts, level, legacy):
    path = facts["task_contract_path"]
    if path is None:
        return "FAIL", None, [{"name": "presence", "level": "FAIL",
                                "msg": "no task_contract.json found (inputs/ or run root)"}]
    return "PASS", path, [{"name": "schema", "level": "PASS",
                            "msg": "validated by validate_task_contract.validate() at gate entry"}]


def check_resource_census(rundir, contract, facts, level, legacy):
    path = facts["resource_census_path"]
    if path is None:
        if level != "R":
            return "N/A", None, [{"name": "presence", "level": "INFO", "msg": "optional, not present"}]
        st = missing_required_status("resource_census", legacy)
        waived = st == "waived-legacy"
        return st, None, [{"name": "presence", "level": "WARN" if waived else "FAIL",
                            "msg": "inputs/resource_census.json not found"
                                   + (" (legacy run predating GATE_EPOCH; waived)" if waived else "")}]
    doc, err = load_json_safe(rundir, path)
    if err:
        return "FAIL", path, [{"name": "parse", "level": "FAIL", "msg": f"invalid JSON: {err}"}]
    rungs = doc.get("rungs") if isinstance(doc, dict) else None
    if not isinstance(rungs, dict) or not rungs:
        return "FAIL", path, [{"name": "rungs", "level": "FAIL", "msg": "rungs section missing or empty"}]
    ok = [k for k, v in rungs.items() if isinstance(v, dict) and v.get("status") == "OK"]
    if not ok:
        return "WARN", path, [{"name": "rungs", "level": "WARN",
                                "msg": f"{len(rungs)} rung(s) recorded but none succeeded (status OK)"}]
    return "PASS", path, [{"name": "rungs", "level": "PASS", "msg": f"{len(rungs)} rung(s), {len(ok)} OK"}]


def check_trap_sweep(rundir, contract, facts, level, legacy):
    path = facts["trap_sweep_path"]
    if path is None:
        if level != "R":
            return "N/A", None, [{"name": "presence", "level": "INFO", "msg": "optional, not present"}]
        st = missing_required_status("trap_sweep", legacy)
        waived = st == "waived-legacy"
        return st, None, [{"name": "presence", "level": "WARN" if waived else "FAIL",
                            "msg": "inputs/trap_sweep.json not found"
                                   + (" (legacy run predating GATE_EPOCH; waived)" if waived else "")}]
    doc, err = load_json_safe(rundir, path)
    if err:
        return "FAIL", path, [{"name": "parse", "level": "FAIL", "msg": f"invalid JSON: {err}"}]
    checks, status = [], "PASS"
    checked = set(doc.get("traps_checked") or [])
    if checked != set(TRAP_IDS):
        checks.append({"name": "traps_checked", "level": "FAIL",
                        "msg": f"traps_checked != T1..T12 (missing {sorted(set(TRAP_IDS) - checked)}, "
                               f"extra {sorted(checked - set(TRAP_IDS))})"})
        status = "FAIL"
    else:
        checks.append({"name": "traps_checked", "level": "PASS", "msg": "all T1..T12 recorded"})
    verdicts = doc.get("verdicts") or []
    esc_ids = {e.get("id") for e in (doc.get("escalations") or []) if isinstance(e, dict)}
    bad = []
    hits = doc.get("traps_hit") or []
    for h in hits:
        hid = h if isinstance(h, str) else (h.get("id") if isinstance(h, dict) else None)
        if hid is None:
            continue
        row = next((v for v in verdicts if isinstance(v, dict) and v.get("id") == hid), None)
        if row is None:
            bad.append(f"{hid}: no verdict row")
        elif not (row.get("flag_number") or hid in esc_ids):
            bad.append(f"{hid}: no flag_number and no escalations[] entry")
    if bad:
        checks.append({"name": "traps_hit_disposition", "level": "FAIL", "msg": "; ".join(bad)})
        status = "FAIL"
    elif hits:
        checks.append({"name": "traps_hit_disposition", "level": "PASS",
                        "msg": f"{len(hits)} hit(s), each verdicted + flagged/escalated"})
    return status, path, checks


ROUTE_FIELD_SYNONYMS = {
    "detector_mode": ("detector_mode", "detector-mode", "detector mode"),
    "stat_mode": ("stat_mode", "stat-mode", "stat mode", "statistics mode", "statistical mode"),
}


def check_route(rundir, contract, facts, level, legacy):
    dm, sm = contract.get("detector_mode"), contract.get("stat_mode")
    escalate = [str(e) for e in (contract.get("escalate") or [])]
    escalate_lower = [e.lower() for e in escalate]
    checks, ok, warn = [], True, False
    for label, val in (("detector_mode", dm), ("stat_mode", sm)):
        if val == "TBD-judgment":
            synonyms = ROUTE_FIELD_SYNONYMS[label]
            named = any(any(syn in e for syn in synonyms) for e in escalate_lower)
            if named:
                checks.append({"name": label, "level": "WARN",
                                "msg": f"{label}=TBD-judgment, deferred via escalate[]"})
            else:
                checks.append({"name": label, "level": "FAIL",
                                "msg": f"{label}=TBD-judgment with no escalate[] entry naming the "
                                       "deferred decision"})
                ok = False
        elif label == "detector_mode" and val == "delphes-custom-uncertified":
            # CR-134 (adjudication §II.4 item 6): the route itself declares the fidelity debt —
            # the gate surfaces it instead of letting it hide in a free-text assumption
            checks.append({"name": label, "level": "WARN",
                            "msg": "detector_mode=delphes-custom-uncertified: Delphes drives a "
                                   "custom selection with NO acc*eff certification — results are "
                                   "uncertified fast-sim proxy, no exclusion of record until "
                                   "certify_acceptance closes vs the published anchors (CR-134)"})
            warn = True
        else:
            checks.append({"name": label, "level": "PASS", "msg": f"{label}={val}"})
    if contract.get("task_mode") == "unsupported":
        compute_present = bool(facts["generation_hits"] or facts["statistics_path"]
                                or facts["statistics_forbidden_present"] or facts["result_pack_paths"])
        if compute_present:
            checks.append({"name": "unsupported-no-compute", "level": "FAIL",
                            "msg": "task_mode=unsupported (refused) but compute artifacts exist on disk"})
            ok = False
        else:
            checks.append({"name": "unsupported-no-compute", "level": "PASS",
                            "msg": "no compute artifacts present, consistent with the refusal"})
    return ("FAIL" if not ok else ("WARN" if warn else "PASS")), None, checks


def check_figure_contract(rundir, contract, facts, level, legacy):
    path = facts["figure_target_path"]
    if path is None:
        if level != "R":
            return "N/A", None, [{"name": "presence", "level": "INFO", "msg": "optional, not present"}]
        return "FAIL", None, [{"name": "presence", "level": "FAIL",
                                "msg": "inputs/figure_target.json not found"}]
    doc, err = load_json_safe(rundir, path)
    if err:
        return "FAIL", path, [{"name": "parse", "level": "FAIL", "msg": f"invalid JSON: {err}"}]
    targets = doc.get("targets") or []
    if not targets:
        return "WARN", path, [{"name": "targets", "level": "WARN", "msg": "no targets[] declared"}]
    checks = [{"name": "targets", "level": "PASS", "msg": f"{len(targets)} target(s) declared"}]
    if not facts["generation_hits"]:
        checks.append({"name": "fulfilment", "level": "INFO",
                        "msg": "generation not (yet) complete; fulfilment not yet expected"})
        return "PASS", path, checks
    unfulfilled = []
    for t in targets:
        fid = t.get("figure_id") or "(description-only)"
        if not t.get("generated_counterpart"):
            unfulfilled.append(fid)
        elif contract.get("task_mode") == "reproduce" and not t.get("side_by_side"):
            unfulfilled.append(f"{fid} (missing side_by_side)")
    if unfulfilled:
        checks.append({"name": "fulfilment", "level": "FAIL",
                        "msg": "unfulfilled target(s): " + ", ".join(unfulfilled)})
        return "FAIL", path, checks
    checks.append({"name": "fulfilment", "level": "PASS", "msg": "every target has a generated "
                    "counterpart" + (" + side_by_side" if contract.get("task_mode") == "reproduce" else "")})
    return "PASS", path, checks


def check_basis_manifest(rundir, contract, facts, level, legacy):
    path = facts["basis_manifest_path"]
    if path is None:
        if level != "R":
            return "N/A", None, [{"name": "presence", "level": "INFO", "msg": "optional, not present"}]
        return "FAIL", None, [{"name": "presence", "level": "FAIL",
                                "msg": "inputs/basis_manifest.json not found"}]
    doc, err = load_json_safe(rundir, path)
    if err:
        return "FAIL", path, [{"name": "parse", "level": "FAIL", "msg": f"invalid JSON: {err}"}]
    curves = doc.get("curves") or []
    if not curves:
        return "FAIL", path, [{"name": "curves", "level": "FAIL", "msg": "curves[] is empty"}]
    bad = [c.get("source", "?") for c in curves
           if "transformation" not in c or "identity_check" not in c]
    if bad:
        return "FAIL", path, [{"name": "curves", "level": "FAIL",
                                "msg": "curve(s) missing transformation/identity_check: " + ", ".join(bad)}]
    return "PASS", path, [{"name": "curves", "level": "PASS",
                            "msg": f"{len(curves)} curve(s), each carries transformation+identity_check"}]


def scan_json_ok(facts):
    """scan.json was located as the statistics artifact and parses. Used to gate the scan-mode
    generation/analysis attestation below -- an unparseable or absent scan.json means the
    aggregate has nothing to attest, so the ordinary per-run-artifact checks apply instead."""
    return (facts.get("statistics_artifact_name") == "scan.json"
            and bool(facts.get("statistics_path"))
            and isinstance(facts.get("scan_doc"), dict))


def scan_manifest_ok(facts):
    """scan_manifest.json exists with a non-empty points[] (or n_done>0). Together with a valid
    scan.json (scan_json_ok) this ATTESTS that every point ran the full native generation+analysis
    chain and the results were aggregated -- per-point intermediates in the manifest's run_dir[]
    siblings are routinely cleaned/regenerable and are deliberately NOT required on disk here."""
    doc = facts.get("scan_manifest_doc")
    if not isinstance(doc, dict):
        return False
    points = doc.get("points")
    if isinstance(points, list) and points:
        return True
    n_done = doc.get("n_done")
    return isinstance(n_done, (int, float)) and n_done > 0


def scan_manifest_spotcheck(facts):
    """Best-effort BONUS only (never required): if the first manifest point's run_dir sibling
    happens to still be on disk, note it: informational either way, never gates PASS/FAIL."""
    doc = facts.get("scan_manifest_doc")
    points = doc.get("points") if isinstance(doc, dict) else None
    if not points or not isinstance(points[0], dict):
        return None
    tag, run_dir = points[0].get("tag", "?"), points[0].get("run_dir")
    if not run_dir:
        return None
    if os.path.isdir(run_dir):
        return {"name": "sibling-spotcheck", "level": "INFO",
                "msg": f"bonus: point {tag} run_dir sibling ({run_dir}) found on disk (not required)"}
    return {"name": "sibling-spotcheck", "level": "INFO",
            "msg": f"bonus: point {tag} run_dir sibling ({run_dir}) not on disk -- expected, "
                   "per-point intermediates are routinely cleaned and are NOT required"}


def scan_points_carry_exclusion(scan_doc):
    """scan.json points[] carrying mu95/exclusion values ATTEST the per-point analysis (each
    point's cutflow was already certified when the point ran; the aggregator re-derives nothing).
    Returns (satisfied, n_carrying)."""
    if not isinstance(scan_doc, dict):
        return False, 0
    points = scan_doc.get("points")
    if not isinstance(points, list) or not points:
        return False, 0
    n = sum(1 for p in points if isinstance(p, dict)
            and any(k in p for k in ("mu95_obs", "mu95_exp", "excluded_obs")))
    return n > 0, n


def check_generation(rundir, contract, facts, level, legacy):
    hits = facts["generation_hits"]
    if not hits and contract.get("task_mode") == "scan" and scan_json_ok(facts) and scan_manifest_ok(facts):
        # scan mode: per-point generation/analysis artifacts live in SIBLING directories named by
        # scan_manifest.json:points[].run_dir, never under this aggregator --rundir. A valid
        # scan.json + a scan_manifest.json with a non-empty points[]/n_done ATTEST that every
        # point ran the full native chain and the results were aggregated here.
        checks = [{"name": "scan-attestation", "level": "PASS",
                    "msg": f"{facts['statistics_path']} + {facts['scan_manifest_path']} attest "
                           "per-point generation (each point ran the full native chain; results "
                           "are aggregated) -- per-point intermediates not required under the "
                           "aggregator rundir"}]
        spot = scan_manifest_spotcheck(facts)
        if spot:
            checks.append(spot)
        return "PASS", facts["statistics_path"], checks
    if not hits:
        if level == "R":
            msg = "no generation artifacts found (sr_yields*.json / *_patch.json / logs/ / native_objects.txt)"
            if contract.get("task_mode") == "scan":
                reason = ("no valid scan.json" if not scan_json_ok(facts)
                           else "scan_manifest.json missing or has no points[]/n_done")
                msg += f"; scan-mode attestation also unavailable ({reason})"
            return "FAIL", None, [{"name": "presence", "level": "FAIL", "msg": msg}]
        return "N/A", None, [{"name": "presence", "level": "INFO", "msg": "none found"}]
    return "PASS", hits[0], [{"name": "presence", "level": "PASS",
                               "msg": f"{len(hits)} generation artifact path(s) found"}]


def check_analysis(rundir, contract, facts, level, legacy):
    if contract.get("task_mode") == "scan":
        # scan mode: no per-point cutflow cert lives under the aggregator (see check_generation) --
        # scan.json points[] carrying exclusion/mu95 data attest the per-point analysis instead.
        if scan_json_ok(facts):
            carries, n = scan_points_carry_exclusion(facts["scan_doc"])
            if carries:
                return "PASS", facts["statistics_path"], [{"name": "scan-attestation", "level": "PASS",
                        "msg": f"scan.json points[] carry exclusion/mu95 data for {n} point(s); "
                               "per-point analysis is aggregated here, no per-point cutflow cert "
                               "required under the aggregator"}]
            if level == "R":
                return "FAIL", facts["statistics_path"], [{"name": "presence", "level": "FAIL",
                        "msg": "scan.json points[] carry no exclusion/mu95 values "
                               "(mu95_obs/mu95_exp/excluded_obs)"}]
            return "N/A", None, [{"name": "presence", "level": "INFO", "msg": "optional, not present"}]
        if level == "R":
            return "FAIL", None, [{"name": "presence", "level": "FAIL",
                    "msg": "no valid scan.json found for scan-mode analysis"}]
        return "N/A", None, [{"name": "presence", "level": "INFO", "msg": "optional, not present"}]
    path, kind = facts["analysis_path"], facts["analysis_kind"]
    if path is None:
        if level == "R":
            return "FAIL", None, [{"name": "presence", "level": "FAIL",
                                    "msg": "no analysis cert found (outputs/cutflow_cert.json, "
                                           "evidence/validation/studies/<id>.json, or fold_result.json)"}]
        return "N/A", None, [{"name": "presence", "level": "INFO", "msg": "optional, not present"}]
    checks = [{"name": "presence", "level": "PASS", "msg": f"{kind} at {path}"}]
    if kind in ("cutflow_cert", "cert"):
        doc, err = load_json_safe(rundir, path)
        if err:
            checks.append({"name": "parse", "level": "FAIL", "msg": f"invalid JSON: {err}"})
            return "FAIL", path, checks
        if isinstance(doc, dict) and doc.get("verdict") == "FAIL":
            checks.append({"name": "verdict", "level": "WARN",
                            "msg": "cert verdict=FAIL; pointer recorded, delivery is the panel's call"})
            return "WARN", path, checks
    return "PASS", path, checks


def check_statistics(rundir, contract, facts, level, legacy):
    name, stat_mode = facts["statistics_artifact_name"], contract.get("stat_mode")
    if name is None:
        forbidden = facts["statistics_forbidden_present"]
        if forbidden:
            return "FAIL", None, [{"name": "absence", "level": "FAIL",
                                    "msg": f"stat_mode={stat_mode} requires NO statistics artifact, "
                                           f"but found: {', '.join(forbidden)}"}]
        return "N/A", None, [{"name": "absence", "level": "PASS",
                               "msg": f"stat_mode={stat_mode}: correctly absent"}]
    path = facts["statistics_path"]
    if path is None:
        if level == "R":
            return "FAIL", None, [{"name": "presence", "level": "FAIL",
                                    "msg": f"{name} not found for stat_mode={stat_mode}"}]
        return "N/A", None, [{"name": "presence", "level": "INFO", "msg": "optional, not present"}]
    doc, err = load_json_safe(rundir, path)
    if err:
        return "FAIL", path, [{"name": "parse", "level": "FAIL", "msg": f"invalid JSON: {err}"}]
    checks = [{"name": "presence", "level": "PASS", "msg": f"{name} present"}]
    doc_mode = (doc.get("stat_mode") or doc.get("mode")) if isinstance(doc, dict) else None
    if doc_mode and stat_mode and doc_mode != stat_mode:
        checks.append({"name": "mode-consistency", "level": "WARN",
                        "msg": f"artifact mode={doc_mode!r} vs contract stat_mode={stat_mode!r} "
                               "(the known detector-name skew is WARN, not FAIL)"})
        return "WARN", path, checks
    status = "PASS"
    # A7 (trial QM.4): a sensitivity-expected-only artifact must be produced by the pyhf engine --
    # an A*eff-scale borrow of a published absolute limit is NOT an expected limit. Post-epoch FAIL;
    # legacy (pre-epoch) runs WARN.
    if stat_mode == "sensitivity-expected-only" and isinstance(doc, dict):
        method = str(doc.get("method") or "")
        if "pyhf" not in method.lower():
            lvl = "WARN" if legacy else "FAIL"
            checks.append({"name": "method", "level": lvl,
                           "msg": ("sensitivity-expected-only must record a pyhf method "
                                   f"(method={method!r}); a 1/A*eff borrow of a published limit "
                                   "is not an expected limit (trial QM.4)")})
            if lvl == "FAIL":
                return "FAIL", path, checks
            status = "WARN"
    # D14 PLAUSIBILITY fold (single-point limit modes only; scan.json points are attested elsewhere)
    if name in ("exclusion.json", "shape_fit.json"):
        # (a) scalar thresholding is insufficient for censored/unverified limits.
        if isinstance(doc, dict):
            numerical_errors = claim_errors(doc, allow_legacy=legacy)
            if numerical_errors:
                checks.append({"name": "excluded-obs-consistency", "level": "FAIL",
                    "msg": "; ".join(numerical_errors)})
                return "FAIL", path, checks
        # (b) fold the sr_plausibility.json verdict (all-zero yields / degenerate mu95 / accxeff)
        plaus_rel = find_anywhere(rundir, "sr_plausibility.json")
        if plaus_rel:
            pdoc, perr = load_json_safe(rundir, plaus_rel)
            if perr:
                checks.append({"name": "sr-plausibility", "level": "FAIL",
                    "msg": f"sr_plausibility.json invalid JSON: {perr}"})
                return "FAIL", path, checks
            if isinstance(pdoc, dict) and pdoc.get("verdict") == "implausible":
                checks.append({"name": "sr-plausibility", "level": "FAIL",
                    "msg": "sr_plausibility.json verdict=implausible: "
                           + "; ".join(pdoc.get("reasons") or ["(no reasons recorded)"])})
                return "FAIL", path, checks
            checks.append({"name": "sr-plausibility", "level": "PASS",
                "msg": f"sr_plausibility.json verdict={pdoc.get('verdict') if isinstance(pdoc, dict) else '?'}"})
        elif level == "R":
            checks.append({"name": "sr-plausibility", "level": "INFO",
                "msg": "no sr_plausibility.json (run sr_plausibility.py to gate all-zero yields / "
                       "degenerate mu95); advisory, not gating"})
    return status, path, checks


def check_result_pack(rundir, contract, facts, level, legacy):
    paths = facts["result_pack_paths"]
    expected = {
        "scan": ["scan.json"], "survey": ["outputs/survey.json"], "summary_plot": ["outputs/survey.json"],
        "projection": ["projection.json"], "anomaly_search": ["sensitivity.json"],
    }.get(contract.get("task_mode"), ["result.json", "figures.json"])
    if not paths:
        if level == "R":
            return "FAIL", None, [{"name": "presence", "level": "FAIL",
                                    "msg": f"no result-pack artifact found (expected: {', '.join(expected)})"}]
        return "N/A", None, [{"name": "presence", "level": "INFO", "msg": "optional, not present"}]
    checks, all_ok = [], True
    for name, rel in paths.items():
        doc, err = load_json_safe(rundir, rel)
        if err:
            checks.append({"name": name, "level": "FAIL", "msg": f"invalid JSON: {err}"})
            all_ok = False
        elif isinstance(doc, dict) and "schema_version" not in doc:
            checks.append({"name": name, "level": "WARN", "msg": "no schema_version key"})
        else:
            checks.append({"name": name, "level": "PASS", "msg": "present, parses, schema_version recorded"})
    if len(expected) > 1 and len(paths) < len(expected):
        checks.append({"name": "completeness", "level": "FAIL",
                        "msg": f"expected {expected}, found {sorted(paths)}"})
        all_ok = False
    return ("PASS" if all_ok else "FAIL"), ", ".join(sorted(paths.values())), checks


def check_verification(rundir, contract, facts, level, legacy, strict):
    vj, ladder, dev = facts["verification_json_path"], facts["ladder_path"], facts["deviations_path"]
    if vj is None:
        if level != "R":
            return "N/A", None, [{"name": "presence", "level": "INFO", "msg": "optional, not present"}]
        st = missing_required_status("verification", legacy)
        waived = st == "waived-legacy"
        return st, None, [{"name": "presence", "level": "WARN" if waived else "FAIL",
                            "msg": "verification.json (+ VERIFICATION-LADDER.md + DEVIATIONS.md) not found"
                                   + (" (legacy run predating GATE_EPOCH; waived)" if waived else "")}]
    checks, status = [], "PASS"
    for label, p in (("VERIFICATION-LADDER.md", ladder), ("DEVIATIONS.md", dev)):
        if p is None:
            checks.append({"name": label, "level": "FAIL", "msg": f"{label} missing alongside verification.json"})
            status = "FAIL"
        else:
            checks.append({"name": label, "level": "PASS", "msg": "present"})
    doc, err = load_json_safe(rundir, vj)
    if err:
        checks.append({"name": "parse", "level": "FAIL", "msg": f"verification.json invalid JSON: {err}"})
        return "FAIL", vj, checks
    ta, tb = (doc.get("tier_a") or {}), (doc.get("tier_b") or {})
    overall = doc.get("overall_verdict")
    ta_pass, tb_pass = ta.get("verdict") == "pass", tb.get("verdict") == "PASS"
    no_undisp = not tb.get("findings")
    expected = ("FAIL" if (ta.get("verdict") == "fail" or tb.get("verdict") == "FAIL")
                else ("PASS" if (ta_pass and tb_pass and no_undisp) else "CONCERNS"))
    if overall != expected:
        checks.append({"name": "overall_verdict", "level": "FAIL",
                        "msg": f"overall_verdict={overall!r} but tier_a/tier_b imply {expected!r}"})
        status = "FAIL"
    else:
        checks.append({"name": "overall_verdict", "level": "PASS", "msg": f"overall_verdict={overall} consistent"})
    vp_exit, vp_tail = run_verify_pack(rundir)
    if vp_exit == 0:
        checks.append({"name": "verify_pack", "level": "PASS", "msg": "verify_pack.py exit 0"})
    else:
        lvl = "FAIL" if (strict and vp_exit == 1) else "WARN"
        checks.append({"name": "verify_pack", "level": lvl, "msg": f"verify_pack.py exit {vp_exit}: {vp_tail}"})
        if lvl == "FAIL":
            status = "FAIL"
        elif status == "PASS":
            status = "WARN"
    return status, vj, checks


STAGE_CHECKERS = {
    "task_contract": check_task_contract,
    "resource_census": check_resource_census,
    "trap_sweep": check_trap_sweep,
    "route": check_route,
    "figure_contract": check_figure_contract,
    "basis_manifest": check_basis_manifest,
    "generation": check_generation,
    "analysis": check_analysis,
    "statistics": check_statistics,
    "result_pack": check_result_pack,
}


# --------------------------------------------------------------------------- #
#  the cross-stage invariants
# --------------------------------------------------------------------------- #

def inv_resource_census_before_route(rundir, contract, facts, legacy, strict):
    triggered = bool(facts["generation_hits"] or facts["statistics_path"] or facts["statistics_forbidden_present"])
    if not triggered:
        return "PASS", "no generation/statistics artifacts yet; nothing to gate"
    ok = facts["resource_census_path"] is not None
    if ok:
        doc, err = load_json_safe(rundir, facts["resource_census_path"])
        ok = (not err) and isinstance(doc, dict) and bool(doc.get("rungs"))
    if ok:
        return "PASS", "resource_census.json present with non-empty rungs before route/generation/statistics"
    if legacy:
        return "waived-legacy", "resource_census.json missing/empty but run predates GATE_EPOCH"
    return "FAIL", "generation/statistics artifacts exist but resource_census.json is absent or empty"


def inv_trap_sweep_recorded(rundir, contract, facts, legacy, strict):
    triggered = bool(facts["generation_hits"] or facts["result_pack_paths"])
    if not triggered:
        return "PASS", "generation not yet reached; nothing to gate"
    if facts["trap_sweep_path"] is None:
        if legacy:
            return "waived-legacy", "trap_sweep.json missing but run predates GATE_EPOCH"
        return "FAIL", "generation/result_pack artifacts exist but trap_sweep.json is absent"
    doc, err = load_json_safe(rundir, facts["trap_sweep_path"])
    if err:
        return "FAIL", f"trap_sweep.json invalid: {err}"
    hits = traps_hit_ids(contract, doc)
    escalate_text = " ".join(str(e) for e in (contract.get("escalate") or []))
    dev_text = ""
    if facts["deviations_path"]:
        try:
            dev_text = open(os.path.join(rundir, facts["deviations_path"]),
                             encoding="utf-8", errors="replace").read()
        except OSError:
            pass
    undisp = sorted(h for h in hits if h not in escalate_text and h not in dev_text)
    if undisp:
        return "WARN", f"trap hit(s) not referenced in escalate[]/DEVIATIONS.md: {undisp}"
    return "PASS", "trap_sweep.json present; every hit disposed via escalate[]/DEVIATIONS.md"


def inv_basis_manifest_before_comparison(rundir, contract, facts, legacy, strict):
    hit_ids = traps_hit_ids(contract, facts["trap_sweep_doc"])
    triggered = (contract.get("task_mode") == "summary_plot") or bool(facts["replane_path"]) \
        or "T3" in hit_ids or "T9" in hit_ids
    if not triggered:
        return "PASS", "no summary_plot/replane/T3/T9 trigger"
    if not facts["result_pack_paths"]:
        return "PASS", "trigger present but result_pack not yet reached"
    if facts["basis_manifest_path"] is None:
        return "FAIL", ("basis comparison triggered (summary_plot/replane/T3/T9) and result_pack "
                         "exists, but basis_manifest.json is absent")
    return "PASS", "basis_manifest.json present before result_pack"


def inv_figure_contract_fulfilled(rundir, contract, facts, legacy, strict):
    task_mode = contract["task_mode"]
    level = resolve_level("figure_contract", task_mode, contract, facts)
    # PRIMARY-aware hard gate (D5/D9): in ANY mode, once generation is complete, the single primary
    # target -- once echoed at check-in -- must carry BOTH a generated_counterpart AND a composed
    # side_by_side. This fires even where figure_contract is level O (scan/reinterpret), which the
    # STAGE checker does NOT gate on side_by_side.
    path = facts["figure_target_path"]
    if path and facts["generation_hits"]:
        doc, err = load_json_safe(rundir, path)
        if not err and isinstance(doc, dict):
            primaries = [t for t in (doc.get("targets") or []) if t.get("primary")]
            if len(primaries) > 1:            # hand-edited / declare-twice contract: enforce single-
                names = ", ".join(t.get("figure_id") or t.get("role") or "?" for t in primaries)
                return "FAIL", (f"{len(primaries)} figure targets marked primary ({names}) -- exactly "
                                "one must be primary (run `figure_target.py primary --figure-id ID`)")
            primary = primaries[0] if primaries else None
            if primary and primary.get("declared_at_checkin"):
                fid = primary.get("figure_id") or "(description-only)"
                if not primary.get("generated_counterpart"):
                    return "FAIL", (f"PRIMARY target {fid} declared at check-in but has no generated "
                                    "counterpart (headline artifact not bound to the approved target)")
                if not primary.get("side_by_side"):
                    return "FAIL", (f"PRIMARY target {fid} has a generated counterpart but no composed "
                                    "side_by_side (run `figure_target.py compose`)")
                # A2 (trial QI.2): the field alone is forgeable -- the trial hand-populated the
                # primary's side_by_side path with no producing script. Require the FILE on disk
                # AND the compose provenance stamp; legacy (pre-epoch) runs downgrade to WARN.
                sbs = primary["side_by_side"]
                sbs_path = sbs if os.path.isabs(sbs) else os.path.join(rundir, sbs)
                probs = []
                if not os.path.isfile(sbs_path):
                    probs.append("side_by_side path is not on disk")
                if not primary.get("composed_by"):
                    probs.append("no composed_by stamp -- hand-populated? (run `figure_target.py "
                                 "compose`; it stamps provenance)")
                if probs:
                    sev = "WARN" if legacy else "FAIL"
                    return sev, f"PRIMARY target {fid}: " + "; ".join(probs)
    # legacy delegation for the required-level (reproduce/projection) figure-reproducing modes
    if level != "R":
        return "N/A", f"figure_contract level={level} for task_mode={task_mode}"
    _status, _artifact, checks = check_figure_contract(rundir, contract, facts, level, legacy)
    fail = next((c for c in checks if c["name"] == "fulfilment" and c["level"] == "FAIL"), None)
    if fail:
        return "FAIL", fail["msg"]
    return "PASS", "figure-contract targets fulfilled (or generation not yet complete)"


def inv_r5_before_limit(rundir, contract, facts, legacy, strict):
    triggered = (contract.get("stat_mode") == "shape-fit") or bool(facts["fold_result_path"]) \
        or bool(facts["replane_path"])
    if not triggered:
        return "PASS", "no shape-fit/fold/replane trigger"
    if not (facts["result_pack_paths"] or facts["verification_json_path"]):
        return "PASS", "trigger present but result_pack/verification not yet reached"
    if legacy and not strict:
        return "waived-legacy", "historical R5 claim retained as unverified archive evidence; no live closure"
    from ravel.validation.certificates import validate_certificate
    subject = (facts.get("statistics_path") or facts.get("fold_result_path") or facts.get("replane_path"))
    if not subject:
        return "FAIL", "R5 has no current scientific output to bind"
    sf_path = (facts.get("statistics_path") if facts.get("statistics_artifact_name") == "shape_fit.json"
               else find_anywhere(rundir, "shape_fit.json"))
    doc, _ = load_json_safe(rundir, sf_path) if sf_path else ({}, None)
    cert = (doc.get("r5_certificate") if isinstance(doc, dict) else None) or "outputs/r5-certificate.json"
    checked = validate_certificate(rundir, cert, kind="r5", contract=contract,
                                   required_subjects=[subject], live=True)
    if checked["status"] == "PASS":
        return "PASS", "R5 recomputed from the approved artifact-bound plan: " + checked["evidence"]["scope"]
    return "FAIL", "R5 not closed: " + "; ".join(checked["errors"]) + "; legacy booleans and ladder checkmarks cannot grant closure"


def inv_likelihood_pairing(rundir, contract, facts, legacy, strict):
    if contract.get("stat_mode") != "published-likelihood":
        return "PASS", "stat_mode != published-likelihood; not applicable"
    ws, patch = locate_bkg_workspace(rundir, facts), locate_signal_patch(rundir)
    if not ws or not patch:
        missing = [n for n, v in (("bkg-only workspace", ws), ("signal patch (**/output/*_patch.json)", patch)) if not v]
        return ("FAIL" if strict else "WARN"), f"pairing inputs unlocatable: {', '.join(missing)}"
    pc = os.path.join(HERE, "pairing_check.py")
    try:
        out = subprocess.run([sys.executable, pc, "--bkg", ws, "--patch", patch],
                              capture_output=True, text=True, timeout=60)
    except Exception as e:
        return "FAIL", f"pairing_check.py could not run: {e}"
    ws_disp = os.path.relpath(ws, rundir) if os.path.abspath(ws).startswith(os.path.abspath(rundir)) else ws
    if out.returncode == 0:
        return "PASS", f"pairing_check.py PASS (bkg={ws_disp}, patch={os.path.relpath(patch, rundir)})"
    tail = (out.stdout + out.stderr).strip()
    return "FAIL", f"pairing_check.py exit {out.returncode}: {tail[-500:]}"


def inv_blocked_shape_fit_refusal_recorded(rundir, contract, facts, legacy, strict):
    """footnote C9: stat_mode=blocked-shape-fit makes the statistics stage N/A, but the refusal
    itself must be RECORDED -- either the contract's blocking[] names it, or DEVIATIONS.md
    carries a refusal note. Neither existing means the refusal only lives in someone's head."""
    if contract.get("stat_mode") != "blocked-shape-fit":
        return "PASS", "stat_mode != blocked-shape-fit; not applicable"
    blocking = contract.get("blocking") or []
    if blocking:
        return "PASS", f"blocking[] names the refusal ({len(blocking)} entry/entries)"
    if facts["deviations_path"]:
        try:
            text = open(os.path.join(rundir, facts["deviations_path"]),
                        encoding="utf-8", errors="replace").read()
        except OSError:
            text = ""
        if re.search(r"\brefus", text, re.I):
            return "PASS", "DEVIATIONS.md present with a refusal note"
        return "FAIL", ("DEVIATIONS.md present but carries no refusal note "
                         "(stat_mode=blocked-shape-fit requires one)")
    return "FAIL", ("stat_mode=blocked-shape-fit but the refusal is undocumented: "
                     "blocking[] is empty and no DEVIATIONS.md is present")


def inv_deviations_on_change(rundir, contract, facts, legacy, strict):
    hits = traps_hit_ids(contract, facts["trap_sweep_doc"])
    stat_mismatch = False
    for name, rel in (facts["result_pack_paths"] or {}).items():
        if name == "result.json" or (rel and rel.endswith("result.json")):
            doc, err = load_json_safe(rundir, rel)
            if not err and isinstance(doc, dict) and doc.get("stat_mode") \
                    and doc.get("stat_mode") != contract.get("stat_mode"):
                stat_mismatch = True
    changed_inputs = baselined_inputs_changed(rundir)          # D15 broaden
    triggered = bool(hits) or stat_mismatch or bool(contract.get("escalate")) or bool(changed_inputs)
    if not triggered:
        return "PASS", ("no traps hit / stat_mode change / escalate entries / baselined-input change "
                        "-- DEVIATIONS.md not required")
    dev_path = facts["deviations_path"]
    if not dev_path:
        return "FAIL", ("trap hit(s)/stat_mode change/escalate[]/baselined-input change recorded but "
                        "DEVIATIONS.md is absent")
    if changed_inputs:            # moment-of-change discipline: the row must NAME each changed input
        try:
            text = open(os.path.join(rundir, dev_path), encoding="utf-8", errors="replace").read()
        except OSError:
            text = ""
        undoc = [b for b in changed_inputs if b not in text]
        if undoc:
            return "FAIL", ("baselined input(s) changed after CHECK-IN 1 with no DEVIATIONS.md row "
                            "naming them: " + ", ".join(undoc))
    return "PASS", "DEVIATIONS.md present" + (" and names each changed baselined input"
                                              if changed_inputs else "")


MU_RE = re.compile(r"(?:µ|mu)\s*95\s*[_ ]?(obs|exp)?\D{0,15}?([0-9]+\.?[0-9]*)", re.I)
COVERAGE_RE = re.compile(r"\b(\d+)\s*(?:of|/)\s*(\d+)\b")
# Unanchored, COVERAGE_RE alone matches incidental ratios in physics prose (e.g. "1.47/0.74"
# tokenizes as "47/0"). Require a coverage-context word within ~30 chars of the match before
# treating "N of M" / "N/M" as a grid-coverage claim.
COVERAGE_CONTEXT_RE = re.compile(r"\b(?:grid|points?|scan|cells?|coverage|done|complete)\b", re.I)
COVERAGE_CONTEXT_WINDOW = 30


def inv_result_prose_matches(rundir, contract, facts, legacy, strict):
    """Targeted, NOT full prose tracing: at most the mu95_obs/exp, verdict-word, and coverage
    anchors, each compared to result.json/scan.json within printed precision."""
    if not facts["result_md_path"]:
        return "N/A", "no RESULT.md to trace"
    text = open(os.path.join(rundir, facts["result_md_path"]), encoding="utf-8", errors="replace").read()
    ref = {}
    problems, oks = [], []
    for _name, rel in (facts["result_pack_paths"] or {}).items():
        if rel and rel.endswith(".json"):
            doc, err = load_json_safe(rundir, rel)
            if not err and isinstance(doc, dict):
                if any(k in doc for k in ("limits", "mu95_obs", "obs_limit")):
                    try:
                        problems.extend(prose_errors(text, doc))
                    except (ValueError, TypeError) as exc:
                        problems.append(str(exc))
                for k in ("mu95_obs", "mu95_exp", "excluded_obs", "n_done", "n_planned"):
                    if k in doc and k not in ref:
                        ref[k] = doc[k]
    for m in MU_RE.finditer(text):
        kind = m.group(1)
        if not kind:
            continue
        key, val = f"mu95_{kind.lower()}", float(m.group(2))
        if key in ref and ref[key] is not None:
            if abs(val - float(ref[key])) > max(1e-3, 0.01 * abs(float(ref[key]))):
                problems.append(f"prose {key}={val} vs artifact {ref[key]}")
            else:
                oks.append(key)
    if "excluded_obs" in ref:
        word = False if re.search(r"\bnot excluded\b", text, re.I) else True if re.search(r"\bexcluded\b", text, re.I) else (
            False if re.search(r"\ballowed\b", text, re.I) else None)
        if word is not None and (ref["excluded_obs"] is None or ref["excluded_obs"] != word):
            problems.append(f"prose says {'excluded' if word else 'allowed'} vs artifact "
                             f"excluded_obs={ref['excluded_obs']}")
        elif word is not None:
            oks.append("verdict-word")
    m = None
    for cand in COVERAGE_RE.finditer(text):
        lo = max(0, cand.start() - COVERAGE_CONTEXT_WINDOW)
        hi = min(len(text), cand.end() + COVERAGE_CONTEXT_WINDOW)
        if COVERAGE_CONTEXT_RE.search(text[lo:hi]):
            m = cand
            break
    if m and "n_done" in ref and "n_planned" in ref:
        pd, pn = int(m.group(1)), int(m.group(2))
        if (pd, pn) != (ref["n_done"], ref["n_planned"]):
            problems.append(f"prose coverage {pd}/{pn} vs artifact n_done={ref['n_done']}/n_planned={ref['n_planned']}")
        else:
            oks.append("coverage")
    if problems:
        return "FAIL", "; ".join(problems)
    if not ref:
        return "N/A", "no headline artifact to trace against"
    if not oks:
        return "WARN", "no headline anchor (mu95/verdict-word/coverage) found in RESULT.md prose"
    return "PASS", f"{len(oks)} headline anchor(s) match artifact values"


def inv_param_validated_before_scan(rundir, contract, facts, legacy, strict):
    """D10: a scan must not SHIP its varied physics until inputs/validations.json says every
    varied-param/trap obligation is PASS. Gates ONLY scan mode, and only once the scan is actually
    shipping (scan.json / scan_manifest present) so an in-progress scan is not prematurely blocked."""
    if contract.get("task_mode") != "scan":
        return "PASS", "param-validation gate applies to scan mode only"
    shipping = bool(facts.get("scan_manifest_path")) or (
        facts.get("statistics_artifact_name") == "scan.json" and bool(facts.get("statistics_path")))
    if not shipping:
        return "PASS", "scan not yet shipping (no scan.json/scan_manifest.json yet); nothing to gate"
    vpath = find_first_existing(rundir, "inputs/validations.json")
    if vpath is None:
        if legacy:
            return "waived-legacy", "validations.json missing but run predates GATE_EPOCH"
        return "FAIL", ("scan is shipping but inputs/validations.json is absent -- run "
                        "`validate_parameters.py emit` and validate the scan's varied params first")
    doc, err = load_json_safe(rundir, vpath)
    if err:
        return "FAIL", f"validations.json invalid: {err}"
    obligations = [p for p in (doc.get("params") or [])
                   if isinstance(p, dict) and (p.get("role") == "varied" or p.get("trap"))]
    if not obligations:
        return "FAIL", "validations.json carries no varied-parameter/trap obligation before a scan ships"
    not_pass = sorted(f"{p.get('name')}={p.get('status')}" for p in obligations
                      if p.get("status") != "PASS")
    if not_pass:
        return "FAIL", "parameter validation not PASS before scan ships: " + ", ".join(not_pass)
    return "PASS", f"{len(obligations)} scan parameter-validation obligation(s) all PASS"


def inv_ladder_order(rundir, contract, facts, legacy, strict):
    """D11: a full/scan compute reaching generation MUST have a recorded smoke-rung PASS (the
    dry->smoke->full->scan ladder must not be skipped). The smoke rung's PASS is a logs/ladder.json
    rungs[] entry {rung:'smoke', status:'PASS'}."""
    if contract.get("compute_plan") not in ("full", "scan"):
        return "PASS", f"compute_plan={contract.get('compute_plan')} does not require a prior smoke rung"
    reached = bool(facts["generation_hits"]) or bool(facts["result_pack_paths"]) \
        or (contract.get("task_mode") == "scan" and scan_json_ok(facts) and scan_manifest_ok(facts))
    if not reached:
        return "PASS", "full/scan not yet at generation; smoke-rung gate not yet active"
    if legacy:
        return "waived-legacy", "ladder-order waived: run predates GATE_EPOCH"
    rel = facts.get("ladder_record_path")
    doc = None
    if rel:
        doc, _err = load_json_safe(rundir, rel)
    rungs = (doc.get("rungs") if isinstance(doc, dict) else None) or []
    smoke_ok = any(isinstance(r, dict) and r.get("rung") == "smoke" and r.get("status") == "PASS"
                   for r in rungs)
    if smoke_ok:
        return "PASS", f"smoke-rung PASS recorded in {rel} (dry->smoke->full->scan honored)"
    return "FAIL", ("full/scan compute reached generation without a smoke-rung PASS artifact "
                    "(logs/ladder.json rungs[] with rung=smoke,status=PASS) -- the "
                    "dry->smoke->full->scan ladder was skipped")


CERT_REQUIRED_STAT_MODES = ("published-likelihood", "simplified-likelihood",
                            "best-sr-counting", "combined-counting", "stability-only",
                            # A8 (trial QM.2): a sensitivity claim depends on A*eff exactly
                            # as a limit does -- the trial shipped sensitivity numbers with
                            # ZERO certification ("the biggest physics gap").
                            "sensitivity-expected-only")


def _find_limit_cert(rundir, contract, facts):
    """Discover a verdict-bearing acc*eff cert for a limit-shipping run. Non-scan: the analysis-stage
    cert pointer (facts). Scan / anything else: find_cert on the routine/id. scan.json point
    attestation deliberately does NOT count (D12 'incl. scan'). Returns a relpath|abspath|None."""
    path, kind = facts.get("analysis_path"), facts.get("analysis_kind")
    if path and kind in ("cutflow_cert", "cert"):
        return path
    routine = None
    targets = contract.get("targets") or {}
    an = targets.get("analysis") or []
    if an:
        routine = str(an[0])
    try:
        absf = result_pack.find_cert(rundir, routine, None)
    except Exception:
        absf = None
    if absf and os.path.isfile(absf):
        absr = os.path.abspath(rundir)
        return os.path.relpath(absf, rundir) if absf.startswith(absr) else absf
    return None


def inv_certify_before_limit(rundir, contract, facts, legacy, strict):
    """D12: live limits require recomputed, approved, artifact-bound acceptance evidence.

    Historical diagnostic reports remain readable; their PASS/WARN labels do not authorize
    current serving. The detached certificate binds the current statistics and report.
    """
    if contract.get("stat_mode") not in CERT_REQUIRED_STAT_MODES:
        return "PASS", f"stat_mode={contract.get('stat_mode')} ships no acc*eff-certified limit"
    reached = bool(facts["statistics_path"]) or bool(facts["result_pack_paths"]) \
        or (contract.get("task_mode") == "scan" and scan_json_ok(facts))
    if not reached:
        return "PASS", "cert-required mode but the limit stage is not yet reached"
    if legacy and not strict:
        return "waived-legacy", "historical acceptance report retained as unverified archive evidence; no live certification"
    for path in (facts.get("result_pack_paths") or {}).values():
        if os.path.basename(path) != "result.json":
            continue
        pack, error = load_json_safe(rundir, path)
        errors = [error] if error else source_errors(pack, rundir, required=True,
                                                    expected_path=facts.get("statistics_path"))
        if errors:
            return "FAIL", "served result is not bound to certified statistics: " + "; ".join(errors)
    from ravel.validation.certificates import validate_certificate
    report_path = _find_limit_cert(rundir, contract, facts)
    report, _ = load_json_safe(rundir, report_path) if report_path and not os.path.isabs(report_path) else ({}, None)
    cert = (report.get("certification") if isinstance(report, dict) else None) or "outputs/acceptance-certificate.json"
    subjects = [p for p in (facts.get("statistics_path"), report_path) if p]
    if not subjects:
        return "FAIL", "no current acceptance/statistical output to bind; scan point attestation is insufficient"
    checked = validate_certificate(rundir, cert, kind="acceptance", contract=contract,
                                   required_subjects=subjects, live=True)
    if checked["status"] == "PASS":
        return "PASS", "acceptance comparison recomputed from the approved artifact-bound plan: " + checked["evidence"]["scope"]
    return "FAIL", "acceptance certificate invalid: " + "; ".join(checked["errors"]) + "; report verdict/scan attestation is insufficient"


def inv_trap_obligations(rundir, contract, facts, legacy, strict):
    """D13: every obligation-bearing trap hit needs a trap_sweep.json obligations[] entry with
    status==PASS before the gated stage. T3/T9 are already driven by the basis-manifest gate
    (inv_basis_manifest_before_comparison) -- excluded here to avoid duplication."""
    triggered = bool(facts["generation_hits"]) or bool(facts["result_pack_paths"]) \
        or (contract.get("task_mode") == "scan" and scan_json_ok(facts))
    if not triggered:
        return "PASS", "generation not yet reached; nothing to gate"
    hits = traps_hit_ids(contract, facts["trap_sweep_doc"])
    gated = sorted(h for h in hits if h not in ("T3", "T9"))
    if not gated:
        return "PASS", "no obligation-bearing trap hit (T3/T9 handled by the basis-manifest gate)"
    if legacy:
        return "waived-legacy", f"trap hits {gated} but run predates GATE_EPOCH"
    if facts["trap_sweep_path"] is None:
        return "FAIL", f"trap hit(s) {gated} but trap_sweep.json is absent"
    doc = facts["trap_sweep_doc"] or {}
    obligations = doc.get("obligations") or []
    undischarged = []
    for h in gated:
        entries = [o for o in obligations if isinstance(o, dict) and o.get("trap") == h]
        if not entries or not any(o.get("status") == "PASS" for o in entries):
            worst = "; ".join(f"{o.get('obligation_kind', '?')}={o.get('status', 'MISSING')}"
                              for o in entries) or "no obligations[] entry"
            undischarged.append(f"{h} ({worst})")
    if undischarged:
        return "FAIL", ("trap route-consequence obligation(s) not PASS before the gated stage: "
                        + ", ".join(undischarged))
    return "PASS", f"every obligation-bearing trap hit discharged (status==PASS): {gated}"


def _path_is_within(child_real, parent_real):
    if not parent_real:
        return False
    parent_real = os.path.realpath(parent_real)
    return child_real == parent_real or child_real.startswith(parent_real.rstrip(os.sep) + os.sep)


def inv_outputs_in_tree(rundir, contract, facts, legacy, strict):
    """N2: every generation output (non-scan) and every scan_manifest point's evidence must
    resolve UNDER the rundir or the repo tree -- never /tmp / /private/tmp / a session scratchpad
    (invisible to verify_pack / directory-keeper / .gitignore, which all key on the rundir)."""
    triggered = bool(facts["generation_hits"]) or isinstance(facts.get("scan_manifest_doc"), dict)
    if not triggered:
        return "PASS", "no generation outputs / scan manifest on disk yet"
    rundir_real = os.path.realpath(rundir)
    try:
        repo_root = result_pack._repo_root(rundir)
    except Exception:
        repo_root = None
    repo_real = os.path.realpath(repo_root) if repo_root else None

    def _in_tree(p):
        pr = os.path.realpath(p)
        return (_path_is_within(pr, rundir_real) or (repo_real and _path_is_within(pr, repo_real))), pr

    violations = []
    for rel in facts["generation_hits"]:
        ok, pr = _in_tree(os.path.join(rundir, rel))
        if not ok:
            violations.append(f"{rel} -> {pr}")
    doc = facts.get("scan_manifest_doc")
    points = doc.get("points") if isinstance(doc, dict) else None
    for mp in (points or []):
        if not isinstance(mp, dict) or not mp.get("run_dir"):
            continue
        run_dir = mp["run_dir"]
        base = run_dir if os.path.isabs(run_dir) else os.path.join(
            repo_root or os.path.dirname(rundir_real), run_dir)
        ok, pr = _in_tree(base)
        if not ok:
            violations.append(f"point {mp.get('tag', '?')} run_dir -> {pr}")
        for sub in ("output/exclusion.json", "output/sr_yields.json", "logs/STATUS.txt"):
            sp = os.path.join(base, sub)
            if os.path.exists(sp):
                ok2, pr2 = _in_tree(sp)
                if not ok2:
                    violations.append(f"point {mp.get('tag', '?')} {sub} -> {pr2}")
    if violations:
        return "FAIL", ("primary compute evidence resolves OUTSIDE the run/repo tree (N2 "
                        "/tmp-scratchpad class; invisible to verify_pack/directory-keeper/.gitignore): "
                        + "; ".join(violations[:8]))
    return "PASS", "all generation outputs / scan points resolve under the run/repo tree"


def inv_producer_complete(rundir, contract, facts, legacy, strict):
    """N4: any .lhe.gz on disk must be a COMPLETE MadGraph product before a downstream stage
    consumes it. No LHE on disk (consumed+cleaned) -> nothing to barrier."""
    lhe = facts.get("lhe_gz_path")
    if not lhe:
        return "PASS", "no .lhe.gz on disk (consumed+cleaned, or not a generation run)"
    ok, reason = lhe_producer_complete(rundir, lhe)
    if ok:
        return "PASS", reason
    return "FAIL", f"producer-barrier (N4): {os.path.relpath(lhe, rundir)} is not complete -- {reason}"


def inv_approval_before_compute(rundir, contract, facts, legacy, strict):
    """H1 (R3): the CHECK-IN 1 go-ahead is an ARTIFACT (inputs/checkin1_approval.json, written only
    by `workflow_state.py approve`, which itself requires a valid checkin1 + a recorded budget).
    Heavy compute with no approval artifact is the F1/F5 spend-before-approval class."""
    if contract.get("compute_plan") not in ("smoke", "full", "scan"):
        return "PASS", f"compute_plan={contract.get('compute_plan')} needs no recorded approval"
    if not facts.get("generation_hits"):
        return "PASS", "approval-required plan but generation not yet reached"
    path = facts.get("approval_path")
    if path is None:
        if legacy:
            return "waived-legacy", "no approval artifact (pre-epoch run; waived)"
        return "FAIL", ("compute ran with NO recorded CHECK-IN 1 go-ahead -- record it via "
                        "`workflow_state.py approve --rundir <rd> --quote '<the physicist reply>'`")
    from ravel.workflow import workflow_state
    errors = workflow_state.verify_approval(rundir)
    if errors:
        # This historical reporting concession is never used by the live Bash verifier.
        sev = "WARN" if legacy and not strict else "FAIL"
        return sev, "; ".join(errors)
    return "PASS", "v2 approval binds the current task contract, check-in, and cost inputs"


def inv_cost_preflight_recorded(rundir, contract, facts, legacy, strict):
    """H4 (trial QD.5): the budget must be an ARTIFACT before compute -- the trial ran
    cost_preflight but recorded nothing; the budget lived only in the hand-editable contract."""
    if contract.get("compute_plan") not in ("smoke", "full", "scan"):
        return "PASS", f"compute_plan={contract.get('compute_plan')} needs no recorded budget"
    if not facts.get("generation_hits"):
        return "PASS", "budget-required plan but generation not yet reached"
    if facts.get("cost_preflight_path"):
        return "PASS", "inputs/cost_preflight.json recorded"
    if legacy:
        return "waived-legacy", "no cost_preflight artifact (pre-epoch run; waived)"
    return "FAIL", ("compute ran with no recorded budget -- run `cost_preflight.py --mode <plan> "
                    "--rundir <rd>` (writes inputs/cost_preflight.json) BEFORE generation")


def inv_lhe_check_before_shower(rundir, contract, facts, legacy, strict):
    """A1 (trial QM.2): shower products on disk imply lhe_check ran and PASSED on the consumed
    LHE. The trial showered base+matched+anchors with logs/ empty -- ungated because lhe_check
    left no artifact. The sidecar (*.lhe_check.json) is now default-on; this gates on it."""
    if not facts.get("hepmc_hits"):
        return "PASS", "no shower products on disk"
    arts = facts.get("lhe_check_artifacts") or []
    if not arts:
        if legacy:
            return "waived-legacy", "shower products but no lhe_check sidecar (pre-epoch run; waived)"
        return "FAIL", ("shower products exist but lhe_check never ran (no *.lhe_check.json "
                        "sidecar) -- run src/ravel/validation/lhe_check.py on the LHE "
                        "BEFORE showering (madgraph-pythia rule)")
    docs = [load_json_safe(rundir, a)[0] for a in arts]
    verdicts = [d.get("verdict") for d in docs if isinstance(d, dict)]
    if any(v == "FAIL" for v in verdicts):
        return "FAIL", "a shower consumed an LHE whose lhe_check verdict is FAIL"
    if not any(v == "PASS" for v in verdicts):
        return "FAIL", "lhe_check sidecar(s) present but none records verdict=PASS"
    return "PASS", f"{len(arts)} lhe_check sidecar(s), all consumed LHEs guarded"


HANDWRITTEN_GENERATORS = {"", "hand-written", "handwritten", "manual", "human"}


def _canonical_bytes(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def recompute_input_fingerprint(rundir, input_rels):
    """sha256 over the canonical JSON of an artifact's declared inputs, in fixed order -- the SAME
    p4a-local formula sr_plausibility.compute_input_fingerprint uses (a plausibility-domain
    canonicalization, deliberately NOT p1's provenance.py fingerprint -- separate domains, D-7).
    Returns None if any input is unreadable."""
    import hashlib
    h = hashlib.sha256()
    for rel in input_rels:
        doc, err = load_json_safe(rundir, rel)
        if err or doc is None:
            return None
        h.update(_canonical_bytes(doc))
        h.update(b"\x00")
    return h.hexdigest()


# (display, expected_generator, finder(rundir,facts)->relpath|None, input_rels for the fingerprint)
LIFECYCLE_REQUIRED_PROVENANCE = (
    ("sr_plausibility.json", "sr_plausibility.py",
     lambda rundir, facts: find_anywhere(rundir, "sr_plausibility.json"),
     ("outputs/sr_yields.json", "outputs/pyhf_exclusion/exclusion.json")),
)


def verify_provenance_lifecycle(rundir, contract, facts):
    """Reject a REQUIRED physics-lifecycle artifact that was hand-written/backfilled: generated_by
    absent/empty/handwritten (or != the tool that must produce it) => not tool-produced. Returns a
    list[str] of violation lines (empty == clean). Task 4.9 adds the input_fingerprint-mismatch check."""
    violations = []
    for name, expected_gen, finder, input_rels in LIFECYCLE_REQUIRED_PROVENANCE:
        rel = finder(rundir, facts)
        if rel is None:
            continue   # not present -> presence is gated elsewhere, not a provenance concern
        doc, err = load_json_safe(rundir, rel)
        if err or not isinstance(doc, dict):
            violations.append(f"{name}: unreadable/not-an-object ({err})")
            continue
        gen_by = doc.get("generated_by")
        if not isinstance(gen_by, str) or gen_by in HANDWRITTEN_GENERATORS:
            violations.append(f"{name}: generated_by absent/hand-written ({gen_by!r}) -- not tool-produced")
        elif gen_by != expected_gen:
            violations.append(f"{name}: generated_by={gen_by!r} != expected {expected_gen!r} (backfilled)")
        stored_fp = doc.get("input_fingerprint")
        recomputed = recompute_input_fingerprint(rundir, input_rels)
        if recomputed is None:
            violations.append(f"{name}: declared inputs {list(input_rels)} unreadable -- cannot verify input_fingerprint")
        elif not isinstance(stored_fp, str) or stored_fp != recomputed:
            violations.append(f"{name}: input_fingerprint mismatch (stored {stored_fp!r} != recompute "
                              f"{recomputed[:12]}...) -- inputs changed after emission (backfill)")
    return violations


def inv_limit_transport(rundir, contract, facts, legacy, strict):
    """Validate declared results recursively without conflating collection with roots."""
    paths = set((facts.get("result_pack_paths") or {}).values())
    if facts.get("statistics_path"):
        paths.add(facts["statistics_path"])
    problems, legacy_count, checked = [], 0, 0
    def inspect(doc, label):
        nonlocal legacy_count, checked
        if not isinstance(doc, dict):
            return
        if any(key in doc for key in ("limits", "obs_limit", "mu95_obs", "mu95_expected")):
            checked += 1
            errors = claim_errors(doc, allow_legacy=legacy)
            problems.extend(f"{label}: {error}" for error in errors)
            if not errors:
                result = read_limits(doc)
                legacy_count += any(c.status == "legacy_reported" for c in [result.observed, *result.expected])
        for key in ("points", "scenarios"):
            children = doc.get(key, [])
            if isinstance(children, dict):
                children = list(children.values())
            if isinstance(children, list):
                for i, child in enumerate(children):
                    inspect(child, f"{label}:{key}[{i}]")
    for path in sorted(p for p in paths if p and p.endswith(".json")):
        doc, err = load_json_safe(rundir, path)
        if err:
            problems.append(f"{path}: {err}")
        else:
            inspect(doc, path)
            if os.path.basename(path) == "result.json" or isinstance(doc, dict) and "limit_source" in doc:
                problems.extend(f"{path}: {error}" for error in source_errors(doc, rundir,
                    required=(not legacy or strict), expected_path=facts.get("statistics_path")))
    if problems:
        return "FAIL", "; ".join(problems)
    if legacy_count:
        return "WARN", f"{legacy_count} historical reported result(s); no numerical crossing certification"
    return ("PASS" if checked else "N/A"), f"{checked} limit representations checked; status retained independently of completion"


def inv_execution_current(rundir, contract, facts, legacy, strict):
    from ravel.workflow.execution import STATE_NAME, validate_execution
    if not os.path.exists(os.path.join(rundir, STATE_NAME)):
        return "N/A", "no durable execution ledger; no stage-reuse certification claimed"
    errors = validate_execution(rundir)
    return ("FAIL", "; ".join(errors)) if errors else ("PASS", "stage inputs, dependencies and outputs match current receipts")


INVARIANTS = (
    ("execution-current", "generation", inv_execution_current),
    ("limit-status-preserved", "statistics", inv_limit_transport),
    ("producer-complete", "generation", inv_producer_complete),
    ("lhe-check-before-shower", "generation", inv_lhe_check_before_shower),
    ("cost-preflight-recorded", "generation", inv_cost_preflight_recorded),
    ("approval-before-compute", "generation", inv_approval_before_compute),
    ("outputs-in-tree", "generation", inv_outputs_in_tree),
    ("trap-obligations-discharged", "generation", inv_trap_obligations),
    ("certify-before-limit", "statistics", inv_certify_before_limit),
    ("ladder-order", "generation", inv_ladder_order),
    ("resource-census-before-route", "route", inv_resource_census_before_route),
    ("trap-sweep-recorded", "generation", inv_trap_sweep_recorded),
    ("basis-manifest-before-comparison", "result_pack", inv_basis_manifest_before_comparison),
    ("figure-contract-fulfilled", "figure_contract", inv_figure_contract_fulfilled),
    ("param-validated-before-scan", "analysis", inv_param_validated_before_scan),
    ("R5-before-limit-ships", "result_pack", inv_r5_before_limit),
    ("likelihood-selection-pairing", "statistics", inv_likelihood_pairing),
    ("blocked-shape-fit-refusal-recorded", "statistics", inv_blocked_shape_fit_refusal_recorded),
    ("DEVIATIONS-on-change", "result_pack", inv_deviations_on_change),
    ("result-prose-matches-artifacts", "result_pack", inv_result_prose_matches),
)


# --------------------------------------------------------------------------- #
#  evaluate / backfill-plan / CLI
# --------------------------------------------------------------------------- #

def evaluate(rundir, contract, stage_limit=None, strict=False):
    # Library callers (workflow_state advance/require) must pass the same strict gate as
    # the CLI. A task_contract stage must never claim validation just because a file exists.
    contract_errors = validate_task_contract.validate(contract)
    if contract_errors:
        fields = contract if type(contract) is dict else {}
        return {
            "rundir": rundir, "task_mode": fields.get("task_mode"),
            "stat_mode": fields.get("stat_mode"), "compute_plan": fields.get("compute_plan"),
            "legacy": is_legacy(rundir),
            "stages": [{"name": "task_contract", "required": "R", "status": "FAIL",
                        "artifact": None, "checks": [
                            {"name": "schema", "level": "FAIL", "msg": e}
                            for e in contract_errors]}],
            "invariants": [], "verdict": "FAIL", "exit": 3,
        }
    facts = discover_facts(rundir, contract)
    legacy = is_legacy(rundir)
    task_mode = contract["task_mode"]
    order = STAGE_ORDER[:STAGE_ORDER.index(stage_limit) + 1] if stage_limit else STAGE_ORDER

    stages_out = []
    for stage in order:
        level = resolve_level(stage, task_mode, contract, facts)
        if stage == "verification":
            status, artifact, checks = check_verification(rundir, contract, facts, level, legacy, strict)
        elif level == "N/A":
            status, artifact, checks = "N/A", None, [{"name": "applicability", "level": "INFO",
                                                        "msg": f"N/A for task_mode={task_mode}"}]
        else:
            status, artifact, checks = STAGE_CHECKERS[stage](rundir, contract, facts, level, legacy)
        stages_out.append({"name": stage, "required": level, "status": status,
                            "artifact": artifact, "checks": checks})

    prefix_idx = STAGE_ORDER.index(order[-1]) if order else -1
    inv_out = []
    for name, target, fn in INVARIANTS:
        if STAGE_ORDER.index(target) > prefix_idx:
            inv_out.append({"name": name, "status": "N/A",
                             "detail": f"not evaluated: beyond the --stage {order[-1]} prefix"})
            continue
        status, detail = fn(rundir, contract, facts, legacy, strict)
        inv_out.append({"name": name, "status": status, "detail": detail})

    any_fail = any(s["status"] == "FAIL" for s in stages_out) or any(i["status"] == "FAIL" for i in inv_out)
    any_warn = any(s["status"] in ("WARN", "waived-legacy") for s in stages_out) \
        or any(i["status"] in ("WARN", "waived-legacy") for i in inv_out)
    verdict = "FAIL" if any_fail else ("WARN" if any_warn else "PASS")
    return {
        "rundir": rundir, "task_mode": task_mode, "stat_mode": contract.get("stat_mode"),
        "compute_plan": contract.get("compute_plan"), "legacy": legacy,
        "stages": stages_out, "invariants": inv_out,
        "verdict": verdict, "exit": (1 if any_fail else 0),
    }


def backfill_plan(rundir, contract):
    facts = discover_facts(rundir, contract)
    task_mode = contract["task_mode"]
    lines = [f"backfill plan for {rundir} (task_mode={task_mode}) -- PRINTS ONLY, writes nothing"]

    def want(stage):
        return resolve_level(stage, task_mode, contract, facts) == "R"

    if want("resource_census") and not facts["resource_census_path"]:
        lines.append("- inputs/resource_census.json: python3 src/ravel/workflow/resource_census.py "
                      f"--inspire <id> --arxiv <id> --analysis-id <id> --rundir {rundir}")
    if want("trap_sweep") and not facts["trap_sweep_path"]:
        lines.append("- inputs/trap_sweep.json: run judgment-protocols P3 (trap-sweep) and hand-write the "
                      "artifact per the trap_sweep.json schema (traps_checked=T1..T12, verdicts[], traps_hit[], "
                      "obligations[] {trap,obligation_kind,artifact,status} PASS per non-T3/T9 hit).")
    if want("figure_contract") and not facts["figure_target_path"]:
        lines.append("- inputs/figure_target.json: python3 src/ravel/plotting/figure_target.py "
                      f"--rundir {rundir} ...")
    if want("basis_manifest") and not facts["basis_manifest_path"]:
        lines.append("- inputs/basis_manifest.json: hand-write per docs/workflow/checklists/summary-plot.md §3 "
                      "(target_basis + curves[] each with transformation/identity_check).")
    if want("verification") and not facts["verification_json_path"]:
        lines.append("- verification.json + VERIFICATION-LADDER.md + DEVIATIONS.md: run the "
                      "verification-panel skill (step 9) and hand-write verification.json per its schema.")
    if len(lines) == 1:
        lines.append("(nothing REQUIRED is missing)")
    return "\n".join(lines)


def print_human(result):
    for s in result["stages"]:
        print(f"[{s['status']:>13}] {s['name']:<16} required={s['required']:<4} artifact={s['artifact']}")
        for c in s["checks"]:
            print(f"    ({c['level']:<4}) {c['name']}: {c['msg']}")
    print()
    for i in result["invariants"]:
        print(f"[{i['status']:>13}] INVARIANT {i['name']}: {i['detail']}")
    print(f"\nvalidate_run_state: verdict={result['verdict']}  (legacy={result['legacy']})  "
          f"task_mode={result['task_mode']} stat_mode={result['stat_mode']} compute_plan={result['compute_plan']}")


def load_contract_for(rundir, contract_override):
    if contract_override:
        path = contract_override
    else:
        rel = find_first_existing(rundir, "inputs/task_contract.json", "task_contract.json")
        if rel is None:
            return None, None, "no task_contract.json found under inputs/ or the run root"
        path = os.path.join(rundir, rel)
    try:
        contract = validate_task_contract.load_contract(path)
    except (OSError, ValueError, UnicodeError, RecursionError) as e:
        return None, path, f"cannot read/parse contract: {e}"
    return contract, path, None


def _prov_inputs_task_contract(rundir, contract):
    rel = find_first_existing(rundir, "inputs/task_contract.json", "task_contract.json")
    if rel is None:
        return [os.path.join(rundir, "inputs", "task_contract.json")]
    return [os.path.abspath(os.path.join(rundir, rel))]


# (artifact_relpath, generated_by tool_id, inputs-resolver). Later phases APPEND their
# LIFECYCLE-required emitters here; presence alone never satisfies -- input_fingerprint must
# recompute against provenance.fingerprint (design §5). Domain-specific artifacts that own a
# SEPARATE input_fingerprint over a different canonicalization (e.g. sr_plausibility.json, Phase 4a)
# are deliberately NOT registered here and are NOT verified against provenance.fingerprint (D-7).
PROVENANCE_TARGETS = (
    ("run_state.json", "workflow_state.py", _prov_inputs_task_contract),
)


def verify_provenance(rundir, contract):
    """Reject any PRESENT required artifact whose generated_by is absent/handwritten or whose
    input_fingerprint does not recompute. Absent targets are N/A (not a FAIL) -- provenance only
    judges artifacts that exist. Returns {"checks", "verdict", "exit"}."""
    checks, any_fail = [], False
    for rel, tool_id, resolver in PROVENANCE_TARGETS:
        path = os.path.join(rundir, rel)
        if not os.path.isfile(path):
            checks.append({"artifact": rel, "status": "N/A", "detail": "not present"})
            continue
        try:
            with open(path) as fh:
                doc = json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            checks.append({"artifact": rel, "status": "FAIL", "detail": f"unreadable: {e}"})
            any_fail = True
            continue
        ok, reason = provenance.verify_pair(doc, tool_id, resolver(rundir, contract))
        checks.append({"artifact": rel, "status": "PASS" if ok else "FAIL", "detail": reason})
        any_fail = any_fail or not ok
    return {"rundir": rundir, "mode": "verify-provenance", "checks": checks,
            "verdict": "FAIL" if any_fail else "PASS", "exit": 1 if any_fail else 0}


# --------------------------------------------------------------------------- #
#  --selftest  (TDD fixtures: good/bad run-dirs in temp dirs)
# --------------------------------------------------------------------------- #

def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)


def _write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def _base_contract(**over):
    c = {
        "schema_version": 1,
        "prompt": "selftest fixture", "task_mode": "survey", "detector_mode": "particle-level",
        "stat_mode": "none-survey", "required_user_inputs": [], "assumptions": ["fixture assumption"],
        "compute_plan": "none", "approval_required": True,
    }
    c.update(over)
    return c


def _trap_sweep_doc(traps_hit=(), escalations=(), obligations=None):
    verdicts = [{"id": t, "status": ("hit" if t in traps_hit else "clear"), "evidence": "-",
                 "consequence": "-", "flag_number": (f"F{i+1}" if t in traps_hit else None)}
                for i, t in enumerate(TRAP_IDS)]
    if obligations is None:
        # default: a discharged (PASS) obligation for every obligation-bearing hit (T3/T9 defer to
        # the basis-manifest gate) so existing hit-fixtures stay green.
        obligations = [{"trap": t, "obligation_kind": "route-consequence-discharged",
                        "artifact": "DEVIATIONS.md", "status": "PASS"}
                       for t in traps_hit if t not in ("T3", "T9")]
    return {"schema_version": 1, "generated_utc": "", "generator": "judgment-protocols P3 (trap-sweep)",
            "analysis_id": "TEST", "model": "TEST", "traps_checked": list(TRAP_IDS),
            "verdicts": verdicts, "traps_hit": list(traps_hit), "escalations": list(escalations),
            "obligations": list(obligations), "notes": ""}


def _resource_census_doc():
    return {"schema_version": 1, "analysis_id": "TEST", "inspire": "0", "arxiv": None,
            "rungs": {"R1_hepdata": {"status": "OK"}, "R2_routines": {"status": "OK"}},
            "manual_rungs": [], "rungs_ok": ["R1_hepdata", "R2_routines"]}


def _basis_manifest_doc():
    return {"schema_version": 1,
            "target_basis": {"quantity": "sigma x BR [pb]", "model": "TEST", "sqrt_s": "13 TeV", "notes": ""},
            "curves": [{"source": "TEST-analysis Table 1", "kind": "observed",
                        "native_basis": "sigma x BR", "transformation": "identity",
                        "identity_check": "NONE"}]}


def _verification_doc(overall="PASS"):
    return {"schema_version": 1, "generated_utc": "", "generator": "verification-panel (step 9)",
            "rundir": "", "tier_a": {"verify_pack_exit": 0, "number_tracing": "pass",
                                      "ladder_present": True, "verdict": "pass"},
            "tier_b": {"verdict": "PASS", "fresh_context": True, "attack_lists_used": [], "findings": []},
            "overall_verdict": overall, "delivered": False}


def _fixture_survey_pass(td):
    rd = os.path.join(td, "2026-07-08_survey_pass")
    contract = _base_contract(task_mode="survey", stat_mode="none-survey", compute_plan="none")
    _write_json(os.path.join(rd, "inputs", "task_contract.json"), contract)
    _write_json(os.path.join(rd, "inputs", "resource_census.json"), _resource_census_doc())
    _write_json(os.path.join(rd, "inputs", "trap_sweep.json"), _trap_sweep_doc())
    _write_json(os.path.join(rd, "inputs", "figure_target.json"),
                {"schema_version": 1, "targets": [{"figure_id": "Figure 1", "role": "summary"}]})
    _write_json(os.path.join(rd, "inputs", "basis_manifest.json"), _basis_manifest_doc())
    _write_json(os.path.join(rd, "outputs", "survey.json"), {"schema_version": 1, "candidates": []})
    _write_json(os.path.join(rd, "verification.json"), _verification_doc())
    _write_text(os.path.join(rd, "VERIFICATION-LADDER.md"),
                "| Rung | Checkpoint |\n|---|---|\n| R6 | checked-pass |\n")
    _write_text(os.path.join(rd, "DEVIATIONS.md"), "# Deviations\nnone\n")
    return rd, contract


def _fixture_scan_missing_census(td):
    rd = os.path.join(td, "2026-07-08_scan_missing_census")
    contract = _base_contract(
        task_mode="scan", stat_mode="best-sr-counting", compute_plan="scan",
        detector_mode="simpleanalysis-delphes-native",
        cost_estimate={"mode": "scan", "points": 4, "walltime_h": [1, 2]})
    _write_json(os.path.join(rd, "inputs", "task_contract.json"), contract)
    _write_json(os.path.join(rd, "scan.json"),
                {"schema_version": 1, "n_planned": 2, "n_done": 2, "n_missing": 0,
                 "points": [{"tag": "p1"}, {"tag": "p2"}], "missing_tags": []})
    # deliberately NO inputs/resource_census.json
    return rd, contract


def _fixture_shape_fit_r5_held(td):
    rd = os.path.join(td, "2026-07-08_shape_fit_r5_held")
    contract = _base_contract(
        task_mode="reinterpret", stat_mode="shape-fit", compute_plan="none",
        detector_mode="particle-level")
    _write_json(os.path.join(rd, "inputs", "task_contract.json"), contract)
    _write_json(os.path.join(rd, "shape_fit.json"), {
        "schema_version": 1, "generator": "shape_fit.py", "stat_mode": "shape-fit",
        "mu95_obs": 1.2, "mu95_exp": 1.1, "mu95_exp_band": [0.7, 0.9, 1.1, 1.3, 1.6],
        "excluded_obs": False, "r5_status": "held",
        "r5_evidence": "reproduction not yet closed: 0/1 recorded reference point(s) in tolerance",
        "r5_reference_points": [{"mass_gev": 20, "in_tolerance": False}], "caveats": [],
    })
    _write_json(os.path.join(rd, "result.json"), {"schema_version": 1})
    _write_json(os.path.join(rd, "figures.json"), {"schema_version": 1, "n_figures": 0, "figures": []})
    _write_text(os.path.join(rd, "VERIFICATION-LADDER.md"),
                "| Rung | Checkpoint | Status | Notes |\n|---|---|---|---|\n"
                "| R5 | their-limit-from-their-inputs | not-checked | not yet run |\n")
    return rd, contract


def _fixture_legacy(td):
    rd = os.path.join(td, "2026-06-01_legacy_anomaly")
    # anomaly_search: figure_contract/basis_manifest/analysis are all O, generation is C2-with-
    # compute_plan=none (-> N/A) -- so a fully legit run needs NO inputs/ dir at all, letting this
    # fixture honor BOTH legacy signals (date<GATE_EPOCH AND no inputs/) at once.
    contract = _base_contract(
        task_mode="anomaly_search", stat_mode="best-sr-counting", compute_plan="none",
        detector_mode="particle-level")
    # task_contract.json lives at the run root (legacy layout; no inputs/ dir at all)
    _write_json(os.path.join(rd, "task_contract.json"), contract)
    _write_json(os.path.join(rd, "outputs", "pyhf_exclusion", "exclusion.json"),
                {"obs_limit": 0.5, "exp_limits": [0.2, 0.3, 0.4, 0.5, 0.6], "per_sr": {}})
    # anomaly_search's result-pack artifact is sensitivity.json (not result.json/figures.json)
    _write_json(os.path.join(rd, "sensitivity.json"), {"schema_version": 1, "windows": {}})
    # deliberately NO resource_census.json / trap_sweep.json / verification.json (the waivable set)
    return rd, contract


def _fixture_in_progress_scan(td):
    rd = os.path.join(td, "2026-07-08_in_progress_scan")
    contract = _base_contract(
        task_mode="scan", stat_mode="best-sr-counting", compute_plan="scan",
        detector_mode="simpleanalysis-delphes-native",
        cost_estimate={"mode": "scan", "points": 4, "walltime_h": [1, 2]})
    _write_json(os.path.join(rd, "inputs", "task_contract.json"), contract)
    _write_json(os.path.join(rd, "inputs", "resource_census.json"), _resource_census_doc())
    _write_json(os.path.join(rd, "inputs", "trap_sweep.json"), _trap_sweep_doc())
    _write_json(os.path.join(rd, "inputs", "figure_target.json"),
                {"schema_version": 1, "targets": [{"figure_id": "Figure 3"}]})
    # deliberately no generation/analysis/statistics/result_pack/verification yet
    return rd, contract


def _fixture_primary_unfulfilled(td):
    rd = os.path.join(td, "2026-07-08_primary_unfulfilled")
    contract = _base_contract(
        task_mode="scan", stat_mode="best-sr-counting", compute_plan="scan",
        detector_mode="simpleanalysis-delphes-native",
        cost_estimate={"mode": "scan", "points": 4, "walltime_h": [1, 2]})
    _write_json(os.path.join(rd, "inputs", "task_contract.json"), contract)
    _write_json(os.path.join(rd, "inputs", "resource_census.json"), _resource_census_doc())
    _write_json(os.path.join(rd, "inputs", "trap_sweep.json"), _trap_sweep_doc())
    # PRIMARY target: counterpart present, side_by_side NULL, echoed at check-in
    _write_json(os.path.join(rd, "inputs", "figure_target.json"), {
        "schema_version": 1, "targets": [
            {"primary": True, "role": "summary", "figure_id": "Figure 3",
             "declared_at_checkin": True,
             "generated_counterpart": {"path": "plots/fig3.png", "step": "08-scan"},
             "side_by_side": None, "verified_by_physicist": None},
        ]})
    # a generation artifact so facts["generation_hits"] is non-empty (fulfilment is now expected)
    _write_json(os.path.join(rd, "outputs", "sr_yields.json"),
                [{"name": "SR", "n": 1, "b": 1.0, "db": 0.2, "s": 0.5}])
    return rd, contract



def _fixture_smoke_without_cost_preflight(td):
    """H4: a smoke run that generated with no recorded budget artifact (all siblings satisfied)."""
    rd, contract = _fixture_primary_unfulfilled(td)
    ft = os.path.join(rd, "inputs", "figure_target.json")
    doc = json.load(open(ft))
    sbs = os.path.join(rd, "plots", "fig3_sbs.png")
    os.makedirs(os.path.dirname(sbs), exist_ok=True)
    open(sbs, "wb").write(b"\x89PNG\r\n\x1a\n")
    doc["targets"][0]["side_by_side"] = sbs
    doc["targets"][0]["composed_by"] = {"tool": "figure_target.py compose", "utc": ""}
    _write_json(ft, doc)
    _write_json(os.path.join(rd, "logs", "ladder.json"),
                {"rungs": [{"rung": "smoke", "status": "PASS"}]})
    _write_json(os.path.join(rd, "inputs", "validations.json"),
                {"schema_version": 1, "generated_by": "validate_parameters.py",
                 "input_fingerprint": "", "params": [
                     {"name": "m", "kind": "param_validation", "role": "varied",
                      "trap": None, "check": "grid", "status": "PASS"}]})
    _write_json(os.path.join(rd, "inputs", "checkin1_approval.json"),
                {"schema_version": 1, "generated_by": "workflow_state.py approve",
                 "approved_plan": "scan", "quote": "GO"})
    return rd, contract


def _fixture_sensitivity_borrow(td):
    """A7 (trial QM.4): a post-epoch sensitivity artifact with NO pyhf method (the borrow)."""
    rd = os.path.join(td, "2026-08-03_sens_borrow")
    contract = _base_contract(task_mode="anomaly_search", stat_mode="sensitivity-expected-only",
                              compute_plan="none", detector_mode="particle-level")
    _write_json(os.path.join(rd, "inputs", "task_contract.json"), contract)
    _write_json(os.path.join(rd, "inputs", "resource_census.json"), _resource_census_doc())
    _write_json(os.path.join(rd, "inputs", "trap_sweep.json"), _trap_sweep_doc())
    _write_json(os.path.join(rd, "sensitivity.json"), {"schema_version": 1, "windows": {}})
    return rd, contract


def _fixture_primary_handpopulated(td):
    """A2 (trial QI.2): primary side_by_side PATH set by hand -- file absent, no composed_by."""
    rd, contract = _fixture_primary_unfulfilled(td)
    ft = os.path.join(rd, "inputs", "figure_target.json")
    doc = json.load(open(ft))
    doc["targets"][0]["side_by_side"] = "plots/fig3_side_by_side.png"   # never created on disk
    _write_json(ft, doc)
    return rd, contract

def _fixture_scan_param_pending(td):
    rd = os.path.join(td, "2026-07-08_scan_param_pending")
    contract = _base_contract(
        task_mode="scan", stat_mode="best-sr-counting", compute_plan="scan",
        detector_mode="simpleanalysis-delphes-native",
        cost_estimate={"mode": "scan", "points": 2, "walltime_h": [1, 2]})
    _write_json(os.path.join(rd, "inputs", "task_contract.json"), contract)
    _write_json(os.path.join(rd, "inputs", "resource_census.json"), _resource_census_doc())
    _write_json(os.path.join(rd, "inputs", "trap_sweep.json"), _trap_sweep_doc())
    _write_json(os.path.join(rd, "inputs", "figure_target.json"),
                {"schema_version": 1, "targets": [{"figure_id": "Figure 3", "role": "summary"}]})
    # scan is SHIPPING: a valid scan.json (points carry mu95) + a scan_manifest attest per-point runs
    _write_json(os.path.join(rd, "scan.json"), {
        "schema_version": 1, "n_planned": 2, "n_done": 2, "n_missing": 0, "missing_tags": [],
        "points": [
            {"tag": "p1", "m_parent": 50.0, "m_lsp": 48.0, "mu95_obs": 0.09, "mu95_exp": 0.09,
             "mu95_exp_band": [0.08, 0.085, 0.09, 0.095, 0.1], "excluded_obs": True},
            {"tag": "p2", "m_parent": 60.0, "m_lsp": 58.0, "mu95_obs": 1.5, "mu95_exp": 1.4,
             "mu95_exp_band": [1.2, 1.3, 1.4, 1.5, 1.6], "excluded_obs": False}]})
    _write_json(os.path.join(rd, "scan_manifest.json"), {
        "schema_version": 1, "name": "test-scan", "n_points": 2,
        "points": [{"tag": "p1", "run_dir": os.path.join(td, "sib_p1"), "config": "config/p1.toml"},
                   {"tag": "p2", "run_dir": os.path.join(td, "sib_p2"), "config": "config/p2.toml"}]})
    # validations.json exists but the varied-param obligation is still PENDING
    _write_json(os.path.join(rd, "inputs", "validations.json"), {
        "schema_version": 1, "generated_by": "validate_parameters.py", "input_fingerprint": "",
        "params": [{"name": "m_slepton", "kind": "param_validation", "role": "varied", "trap": None,
                    "check": "mass in grid", "status": "PENDING"}]})
    return rd, contract


def _fixture_baselined_edit_no_deviation(td):
    rd = os.path.join(td, "2026-07-08_baselined_edit")
    contract = _base_contract(task_mode="survey", stat_mode="none-survey", compute_plan="none")
    _write_json(os.path.join(rd, "inputs", "task_contract.json"), contract)
    _write_json(os.path.join(rd, "inputs", "resource_census.json"), _resource_census_doc())
    _write_json(os.path.join(rd, "inputs", "trap_sweep.json"), _trap_sweep_doc())
    _write_json(os.path.join(rd, "inputs", "figure_target.json"),
                {"schema_version": 1, "targets": [{"figure_id": "Figure 1", "role": "summary"}]})
    _write_json(os.path.join(rd, "inputs", "basis_manifest.json"), _basis_manifest_doc())
    _write_json(os.path.join(rd, "outputs", "survey.json"), {"schema_version": 1, "candidates": []})
    _write_json(os.path.join(rd, "verification.json"), _verification_doc())
    _write_text(os.path.join(rd, "VERIFICATION-LADDER.md"),
                "| Rung | Checkpoint |\n|---|---|\n| R6 | checked-pass |\n")
    # DEVIATIONS.md present but generic -- does NOT name the changed input (isolates the new FAIL:
    # the verification stage still PASSes on DEVIATIONS.md presence)
    _write_text(os.path.join(rd, "DEVIATIONS.md"), "# Deviations\nnone\n")
    _write_json(os.path.join(rd, "run_state.json"), {
        "schema_version": 1, "generated_by": "workflow_state.py",
        "checkins": [{"id": "CHECKIN1", "artifact": "inputs/checkin1.json", "valid": True}],
        "edits": [{"path": "inputs/task_contract.json", "utc": ""}]})
    return rd, contract


def _fixture_scan_no_smoke_ladder(td):
    rd = os.path.join(td, "2026-07-09_scan_no_smoke_ladder")
    contract = _base_contract(
        task_mode="scan", stat_mode="best-sr-counting", compute_plan="scan",
        detector_mode="simpleanalysis-delphes-native",
        cost_estimate={"mode": "scan", "points": 2, "walltime_h": [1, 2]})
    _write_json(os.path.join(rd, "inputs", "task_contract.json"), contract)
    _write_json(os.path.join(rd, "inputs", "resource_census.json"), _resource_census_doc())
    _write_json(os.path.join(rd, "inputs", "trap_sweep.json"), _trap_sweep_doc())
    _write_json(os.path.join(rd, "scan.json"),
                {"schema_version": 1, "n_planned": 2, "n_done": 2, "n_missing": 0,
                 "points": [{"tag": "p1", "mu95_obs": 0.5, "excluded_obs": True},
                            {"tag": "p2", "mu95_obs": 1.4, "excluded_obs": False}], "missing_tags": []})
    _write_json(os.path.join(rd, "scan_manifest.json"),
                {"schema_version": 1, "n_points": 2,
                 "points": [{"tag": "p1", "run_dir": os.path.join(rd, "p1_run")},
                            {"tag": "p2", "run_dir": os.path.join(rd, "p2_run")}]})
    # deliberately NO logs/ladder.json smoke-rung PASS artifact -> inv_ladder_order FAILs
    return rd, contract


def _fixture_reproduce_cert_fail(td):
    rd = os.path.join(td, "2026-07-09_reproduce_cert_fail")
    contract = _base_contract(
        task_mode="reproduce", stat_mode="best-sr-counting", compute_plan="full",
        detector_mode="simpleanalysis-delphes-native",
        cost_estimate={"mode": "full", "points": 1, "walltime_h": [1, 2]})
    _write_json(os.path.join(rd, "inputs", "task_contract.json"), contract)
    _write_json(os.path.join(rd, "inputs", "resource_census.json"), _resource_census_doc())
    _write_json(os.path.join(rd, "inputs", "trap_sweep.json"), _trap_sweep_doc())
    _write_json(os.path.join(rd, "logs", "ladder.json"),
                {"schema_version": 1, "generated_by": "cost_preflight.py",
                 "rungs": [{"rung": "smoke", "status": "PASS"}]})
    _write_json(os.path.join(rd, "outputs", "sr_yields.json"),
                [{"name": "SR1", "n": 5, "b": 4.0, "db": 1.0, "s": 3.0}])
    _write_json(os.path.join(rd, "outputs", "pyhf_exclusion", "exclusion.json"),
                {"obs_limit": 0.8, "exp_limits": [0.4, 0.6, 0.8, 1.1, 1.5], "per_sr": {}, "best_sr": "SR1"})
    # cert PRESENT but verdict=FAIL -> analysis stage only WARNs; inv_certify_before_limit hard-FAILs
    _write_json(os.path.join(rd, "outputs", "cutflow_cert.json"),
                {"routine": "TEST", "label": "t", "verdict": "FAIL",
                 "driving_tol": 0.15, "mu95_bound": 0.2, "rows": []})
    return rd, contract


def _fixture_scan_cert_attestation_only(td):
    """A COMPLETE scan whose ONLY exclusion evidence is scan.json per-point attestation and NO
    acc*eff cert -- inv_certify_before_limit must still FAIL. This is D12's whole reason for saying
    'incl. scan': a per-point/aggregate acc*eff cert verdict is required; scan.json point
    attestation does NOT substitute (_find_limit_cert never reads scan.json as a cert)."""
    rd = os.path.join(td, "2026-07-09_scan_cert_attestation_only")
    contract = _base_contract(
        task_mode="scan", stat_mode="best-sr-counting", compute_plan="scan",
        detector_mode="simpleanalysis-delphes-native",
        cost_estimate={"mode": "scan", "points": 2, "walltime_h": [1, 2]})
    _write_json(os.path.join(rd, "inputs", "task_contract.json"), contract)
    _write_json(os.path.join(rd, "inputs", "resource_census.json"), _resource_census_doc())
    _write_json(os.path.join(rd, "inputs", "trap_sweep.json"), _trap_sweep_doc())
    _write_json(os.path.join(rd, "logs", "ladder.json"),
                {"schema_version": 1, "generated_by": "cost_preflight.py",
                 "rungs": [{"rung": "smoke", "status": "PASS"}]})
    # a COMPLETE scan.json (n_done==n_planned) with per-point excluded_obs attestation ...
    _write_json(os.path.join(rd, "scan.json"),
                {"schema_version": 1, "n_planned": 2, "n_done": 2, "n_missing": 0,
                 "points": [{"tag": "p1", "mu95_obs": 0.5, "excluded_obs": True},
                            {"tag": "p2", "mu95_obs": 1.4, "excluded_obs": False}], "missing_tags": []})
    _write_json(os.path.join(rd, "scan_manifest.json"),
                {"schema_version": 1, "n_points": 2,
                 "points": [{"tag": "p1", "run_dir": os.path.join(rd, "p1_run")},
                            {"tag": "p2", "run_dir": os.path.join(rd, "p2_run")}]})
    # ... but deliberately NO aggregate/per-point acc*eff cert JSON -> _find_limit_cert returns None -> FAIL
    return rd, contract


def _fixture_trap_obligation_pending(td):
    rd = os.path.join(td, "2026-07-09_trap_obligation_pending")
    contract = _base_contract(
        task_mode="reproduce", stat_mode="best-sr-counting", compute_plan="full",
        detector_mode="simpleanalysis-delphes-native",
        cost_estimate={"mode": "full", "points": 1, "walltime_h": [1, 2]})
    _write_json(os.path.join(rd, "inputs", "task_contract.json"), contract)
    _write_json(os.path.join(rd, "inputs", "resource_census.json"), _resource_census_doc())
    _write_json(os.path.join(rd, "logs", "ladder.json"),
                {"schema_version": 1, "generated_by": "cost_preflight.py",
                 "rungs": [{"rung": "smoke", "status": "PASS"}]})
    trap = _trap_sweep_doc(traps_hit=["T8"], escalations=[{"id": "T8"}], obligations=[
        {"trap": "T8", "obligation_kind": "per-width-regen",
         "artifact": "inputs/validations.json#T8", "status": "PENDING"}])
    _write_json(os.path.join(rd, "inputs", "trap_sweep.json"), trap)
    _write_text(os.path.join(rd, "DEVIATIONS.md"), "# Deviations\nT8 wide-resonance per-width regen pending\n")
    _write_json(os.path.join(rd, "outputs", "sr_yields.json"),
                [{"name": "SR1", "n": 5, "b": 4.0, "db": 1.0, "s": 3.0}])
    return rd, contract


def _fixture_implausible_stats(td):
    rd = os.path.join(td, "2026-07-09_implausible_stats")
    contract = _base_contract(
        task_mode="reproduce", stat_mode="best-sr-counting", compute_plan="full",
        detector_mode="simpleanalysis-delphes-native",
        cost_estimate={"mode": "full", "points": 1, "walltime_h": [1, 2]})
    _write_json(os.path.join(rd, "inputs", "task_contract.json"), contract)
    _write_json(os.path.join(rd, "inputs", "resource_census.json"), _resource_census_doc())
    _write_json(os.path.join(rd, "inputs", "trap_sweep.json"), _trap_sweep_doc())
    _write_json(os.path.join(rd, "logs", "ladder.json"),
                {"schema_version": 1, "generated_by": "cost_preflight.py",
                 "rungs": [{"rung": "smoke", "status": "PASS"}]})
    _write_json(os.path.join(rd, "outputs", "sr_yields.json"),
                [{"name": "SR1", "n": 0, "b": 0.0, "db": 0.0, "s": 0.0}])
    _write_json(os.path.join(rd, "outputs", "pyhf_exclusion", "exclusion.json"),
                {"obs_limit": 1e9, "exp_limits": [1, 1, 1, 1, 1], "per_sr": {}, "best_sr": "SR1"})
    _write_json(os.path.join(rd, "outputs", "cutflow_cert.json"),
                {"routine": "TEST", "label": "t", "verdict": "PASS", "rows": []})
    # all-zero yields + runaway mu95 -> an implausible sr_plausibility.json folds to a statistics FAIL
    _write_json(os.path.join(rd, "outputs", "sr_plausibility.json"),
                {"schema_version": 1, "generated_by": "sr_plausibility.py", "input_fingerprint": "x",
                 "verdict": "implausible", "reasons": ["nontrivial-sr: 0 SR(s) carry signal>0 of 1",
                                                       "mu95-in-band: mu95_obs=1000000000.0 out of band"]})
    return rd, contract


def _fixture_scan_output_in_tmp(td):
    rd = os.path.join(td, "2026-07-09_scan_tmp_outputs")
    contract = _base_contract(
        task_mode="scan", stat_mode="best-sr-counting", compute_plan="scan",
        detector_mode="simpleanalysis-delphes-native",
        cost_estimate={"mode": "scan", "points": 2, "walltime_h": [1, 2]})
    _write_json(os.path.join(rd, "inputs", "task_contract.json"), contract)
    _write_json(os.path.join(rd, "inputs", "resource_census.json"), _resource_census_doc())
    _write_json(os.path.join(rd, "inputs", "trap_sweep.json"), _trap_sweep_doc())
    _write_json(os.path.join(rd, "logs", "ladder.json"),
                {"schema_version": 1, "generated_by": "cost_preflight.py",
                 "rungs": [{"rung": "smoke", "status": "PASS"}]})
    _write_json(os.path.join(rd, "scan.json"),
                {"schema_version": 1, "n_planned": 2, "n_done": 2, "n_missing": 0,
                 "points": [{"tag": "p1", "mu95_obs": 0.5, "excluded_obs": True},
                            {"tag": "p2", "mu95_obs": 1.4, "excluded_obs": False}], "missing_tags": []})
    _write_json(os.path.join(rd, "scan_manifest.json"),
                {"schema_version": 1, "n_points": 2, "points": [
                    {"tag": "p1", "run_dir": os.path.join(rd, "p1_run")},        # in-tree
                    {"tag": "p2", "run_dir": "/tmp/rogue_scan_point_p2"}]})       # OUT-OF-TREE (N2)
    return rd, contract


def _fixture_lhe_mid_write(td):
    import gzip
    rd = os.path.join(td, "2026-07-09_lhe_mid_write")
    contract = _base_contract(
        task_mode="reproduce", stat_mode="best-sr-counting", compute_plan="full",
        detector_mode="simpleanalysis-delphes-native",
        cost_estimate={"mode": "full", "points": 1, "walltime_h": [1, 2]})
    _write_json(os.path.join(rd, "inputs", "task_contract.json"), contract)
    _write_json(os.path.join(rd, "inputs", "resource_census.json"), _resource_census_doc())
    _write_json(os.path.join(rd, "inputs", "trap_sweep.json"), _trap_sweep_doc())
    _write_json(os.path.join(rd, "logs", "ladder.json"),
                {"schema_version": 1, "generated_by": "cost_preflight.py",
                 "rungs": [{"rung": "smoke", "status": "PASS"}]})
    _write_json(os.path.join(rd, "outputs", "sr_yields.json"),
                [{"name": "SR1", "n": 5, "b": 4.0, "db": 1.0, "s": 3.0}])
    _write_text(os.path.join(rd, "logs", "madgraph.log"),
                "Cross-section :   1.234e+00 pb  +- 1.2e-02 pb\n")
    lhe_dir = os.path.join(rd, "Events", "run_01")
    os.makedirs(lhe_dir, exist_ok=True)
    # banner says 3 events but only 2 <event> records were written -> grabbed mid-write
    body = ("<LesHouchesEvents version=\"3.0\">\n<header>\n<MGGenerationInfo>\n"
            "  3 = nevents\n</MGGenerationInfo>\n</header>\n<init>\n</init>\n"
            "<event>\n1 1\n</event>\n<event>\n1 1\n</event>\n</LesHouchesEvents>\n")
    with gzip.open(os.path.join(lhe_dir, "unweighted_events.lhe.gz"), "wt", encoding="utf-8") as fh:
        fh.write(body)
    return rd, contract


def _fixture_shower_without_lhe_check(td):
    """A1: a shower product on disk with NO *.lhe_check.json sidecar anywhere -- the trial's
    ungated-shower hole (QM.2). Post-epoch dir + inputs/ so no legacy waiver applies."""
    rd = os.path.join(td, "2026-08-01_shower_without_lhe_check")
    contract = _base_contract(task_mode="reproduce", compute_plan="smoke")
    _write_json(os.path.join(rd, "inputs", "task_contract.json"), contract)
    os.makedirs(os.path.join(rd, "outputs"), exist_ok=True)
    with open(os.path.join(rd, "outputs", "x.hepmc.gz"), "wb") as fh:
        fh.write(b"\x1f\x8b")
    return rd, contract


def _selftest_case(label, build_fn, expect_verdict, expect_exit, extra_check=None, stage_limit=None):
    with tempfile.TemporaryDirectory(prefix="validate_run_state_selftest_") as td:
        rd, contract = build_fn(td)
        errs = validate_task_contract.validate(contract)
        if errs:
            return False, f"{label}: fixture contract itself failed validate_task_contract: {errs}"
        result = evaluate(rd, contract, stage_limit=stage_limit)
        ok = (result["verdict"] == expect_verdict) and (result["exit"] == expect_exit)
        detail = f"verdict={result['verdict']} exit={result['exit']}"
        if ok and extra_check:
            ok, why = extra_check(result)
            if not ok:
                detail += f"  ({why})"
        print(f"[selftest] {label}: {detail}  {'ok' if ok else 'FAIL'}")
        if not ok:
            for s in result["stages"]:
                print(f"    stage {s['name']}: {s['status']} ({s['required']})")
            for i in result["invariants"]:
                print(f"    inv {i['name']}: {i['status']} -- {i['detail']}")
        return ok, (None if ok else f"{label}: expected verdict={expect_verdict} exit={expect_exit}, got {detail}")


def selftest():
    fails = []

    ok, why = _selftest_case("1 survey PASS (census+trap_sweep+figure_contract+basis_manifest+"
                              "survey.json+verification)", _fixture_survey_pass, "PASS", 0)
    if not ok:
        fails.append(why)

    def _census_missing_check(result):
        for i in result["invariants"]:
            if i["name"] == "resource-census-before-route" and i["status"] == "FAIL":
                return True, ""
        for s in result["stages"]:
            if s["name"] == "resource_census" and s["status"] == "FAIL":
                return True, ""
        return False, "expected resource-census-before-route (or the stage) to FAIL"

    ok, why = _selftest_case("2 scan missing resource_census while scan.json exists -> FAIL",
                              _fixture_scan_missing_census, "FAIL", 1, _census_missing_check)
    if not ok:
        fails.append(why)

    def _r5_held_check(result):
        for i in result["invariants"]:
            if i["name"] == "R5-before-limit-ships" and i["status"] == "FAIL":
                return True, ""
        return False, "expected R5-before-limit-ships to FAIL"

    ok, why = _selftest_case("3 shape-fit r5_status=held with result_pack present -> FAIL (R5-before-limit)",
                              _fixture_shape_fit_r5_held, "FAIL", 1, _r5_held_check)
    if not ok:
        fails.append(why)

    def _legacy_waived_check(result):
        waived = [s["name"] for s in result["stages"] if s["status"] == "waived-legacy"]
        if not waived:
            return False, "expected at least one waived-legacy stage"
        if any(s["status"] == "FAIL" for s in result["stages"]):
            return False, "no stage should hard-FAIL on a legacy run missing only the waivable set"
        return True, ""

    ok, why = _selftest_case("4 legacy fixture (dir date<GATE_EPOCH, no inputs/) missing new "
                              "artifacts -> WARN not FAIL (waived-legacy)",
                              _fixture_legacy, "WARN", 0, _legacy_waived_check)
    if not ok:
        fails.append(why)

    ok, why = _selftest_case("5 --stage figure_contract on in-progress fixture (no statistics yet) "
                              "-> PASS on the prefix", _fixture_in_progress_scan, "PASS", 0,
                              stage_limit="figure_contract")
    if not ok:
        fails.append(why)

    def _primary_unfulfilled_check(result):
        for i in result["invariants"]:
            if i["name"] == "figure-contract-fulfilled" and i["status"] == "FAIL":
                return True, ""
        return False, "expected figure-contract-fulfilled to FAIL (primary has no side_by_side)"

    ok, why = _selftest_case("8 scan primary target with counterpart but null side_by_side -> FAIL "
                              "(figure-contract-fulfilled, D9)", _fixture_primary_unfulfilled,
                              "FAIL", 1, _primary_unfulfilled_check, stage_limit="figure_contract")
    if not ok:
        fails.append(why)

    def _param_pending_check(result):
        for i in result["invariants"]:
            if i["name"] == "param-validated-before-scan" and i["status"] == "FAIL":
                return True, ""
        return False, "expected param-validated-before-scan to FAIL"

    ok, why = _selftest_case("9 scan shipping with a PENDING param validation -> FAIL "
                              "(param-validated-before-scan, D10)", _fixture_scan_param_pending,
                              "FAIL", 1, _param_pending_check, stage_limit="analysis")
    if not ok:
        fails.append(why)

    def _baselined_edit_check(result):
        for i in result["invariants"]:
            if i["name"] == "DEVIATIONS-on-change" and i["status"] == "FAIL":
                return True, ""
        return False, "expected DEVIATIONS-on-change to FAIL on a baselined-input edit"

    ok, why = _selftest_case("10 baselined input edited post-CHECK-IN-1 with no DEVIATIONS row -> "
                              "FAIL (DEVIATIONS-on-change, D15)", _fixture_baselined_edit_no_deviation,
                              "FAIL", 1, _baselined_edit_check)
    if not ok:
        fails.append(why)

    def _ladder_order_check(result):
        for i in result["invariants"]:
            if i["name"] == "ladder-order" and i["status"] == "FAIL":
                return True, ""
        return False, "expected ladder-order to FAIL"

    ok, why = _selftest_case("12 full/scan reaches generation without a smoke-rung PASS -> FAIL "
                              "(ladder-order)", _fixture_scan_no_smoke_ladder, "FAIL", 1, _ladder_order_check)
    if not ok:
        fails.append(why)

    def _certify_check(result):
        # primary: a reproduce run whose acc*eff cert verdict is FAIL hard-blocks the limit
        if not any(i["name"] == "certify-before-limit" and i["status"] == "FAIL"
                   for i in result["invariants"]):
            return False, "expected certify-before-limit to FAIL on a FAIL reproduce cert"
        # D12 raison d'etre: a COMPLETE scan whose only evidence is scan.json point-attestation
        # (no acc*eff cert) must ALSO FAIL -- the attestation does not satisfy the cert.
        with tempfile.TemporaryDirectory(prefix="vrs_scan_cert_") as _std:
            srd, scon = _fixture_scan_cert_attestation_only(_std)
            si = {i["name"]: i for i in evaluate(srd, scon)["invariants"]}.get("certify-before-limit")
            if not si or si["status"] != "FAIL":
                return False, f"expected certify-before-limit to FAIL for a cert-less complete scan; got {si}"
            if "attestation" not in si["detail"]:
                return False, "scan certify FAIL detail should call out scan.json attestation insufficiency"
        return True, ""

    ok, why = _selftest_case("13 FAIL acc*eff cert (reproduce) AND scan.json point-attestation only "
                             "(scan) -> FAIL (certify-before-limit)", _fixture_reproduce_cert_fail,
                             "FAIL", 1, _certify_check)
    if not ok:
        fails.append(why)

    def _trap_obl_check(result):
        for i in result["invariants"]:
            if i["name"] == "trap-obligations-discharged" and i["status"] == "FAIL":
                return True, ""
        return False, "expected trap-obligations-discharged to FAIL"

    ok, why = _selftest_case("14 T8 hit with a PENDING obligation -> FAIL (trap-obligations-discharged)",
                              _fixture_trap_obligation_pending, "FAIL", 1, _trap_obl_check)
    if not ok:
        fails.append(why)

    def _plausibility_check(result):
        for s in result["stages"]:
            if s["name"] == "statistics" and s["status"] == "FAIL" and \
                    any(c["name"] == "sr-plausibility" and c["level"] == "FAIL" for c in s["checks"]):
                return True, ""
        return False, "expected check_statistics to FAIL on an implausible sr_plausibility.json"

    ok, why = _selftest_case("15 all-zero yields + implausible sr_plausibility.json -> statistics FAIL "
                              "(D14)", _fixture_implausible_stats, "FAIL", 1, _plausibility_check)
    if not ok:
        fails.append(why)

    def _in_tree_check(result):
        for i in result["invariants"]:
            if i["name"] == "outputs-in-tree" and i["status"] == "FAIL":
                return True, ""
        return False, "expected outputs-in-tree to FAIL"

    ok, why = _selftest_case("16 scan point OUTDIR under /tmp -> FAIL (outputs-in-tree, N2)",
                              _fixture_scan_output_in_tmp, "FAIL", 1, _in_tree_check)
    if not ok:
        fails.append(why)

    def _producer_check(result):
        for i in result["invariants"]:
            if i["name"] == "producer-complete" and i["status"] == "FAIL":
                return True, ""
        return False, "expected producer-complete to FAIL"

    ok, why = _selftest_case("17 LHE banner nevents != counted <event> records -> FAIL "
                              "(producer-complete, N4)", _fixture_lhe_mid_write, "FAIL", 1, _producer_check)
    if not ok:
        fails.append(why)

    def _lhe_check_gate_check(result):
        for i in result["invariants"]:
            if i["name"] == "lhe-check-before-shower" and i["status"] == "FAIL":
                return True, ""
        return False, "expected lhe-check-before-shower to FAIL"

    ok, why = _selftest_case("20 shower without lhe_check sidecar -> FAIL "
                              "(lhe-check-before-shower, A1)", _fixture_shower_without_lhe_check,
                              "FAIL", 1, _lhe_check_gate_check)
    if not ok:
        fails.append(why)

    def _handpopulated_check(result):
        row = next((i for i in result["invariants"] if i["name"] == "figure-contract-fulfilled"), None)
        if row is None or row["status"] != "FAIL":
            return False, "expected figure-contract-fulfilled to FAIL (hand-populated primary)"
        if "composed_by" not in row["detail"] and "not on disk" not in row["detail"]:
            return False, f"unexpected detail: {row['detail']}"
        return True, ""
    ok, why = _selftest_case("21 hand-populated primary side_by_side -> FAIL "
                              "(figure-contract-fulfilled, A2)", _fixture_primary_handpopulated,
                              "FAIL", 1, _handpopulated_check)
    if not ok:
        fails.append(why)

    def _sens_borrow_check(result):
        st = next((s for s in result["stages"] if s["name"] == "statistics"), None)
        if st is None or st["status"] != "FAIL":
            return False, "expected the statistics stage to FAIL (sensitivity borrow)"
        if not any(c["name"] == "method" for c in st["checks"]):
            return False, "expected a method check on the statistics stage"
        return True, ""
    ok, why = _selftest_case("22 sensitivity artifact without a pyhf method -> FAIL "
                              "(check_statistics, A7)", _fixture_sensitivity_borrow,
                              "FAIL", 1, _sens_borrow_check)
    if not ok:
        fails.append(why)

    def _cost_check(result):
        row = next((i for i in result["invariants"] if i["name"] == "cost-preflight-recorded"), None)
        if row is None or row["status"] != "FAIL":
            return False, "expected cost-preflight-recorded to FAIL"
        return True, ""
    ok, why = _selftest_case("23 smoke compute without a cost_preflight artifact -> FAIL "
                              "(cost-preflight-recorded, H4)", _fixture_smoke_without_cost_preflight,
                              "FAIL", 1, _cost_check)
    if not ok:
        fails.append(why)

    def _fixture_unapproved_compute(td):
        rd, contract = _fixture_smoke_without_cost_preflight(td)
        # give it the budget (isolating the approval gate) and REMOVE the approval artifact
        _write_json(os.path.join(rd, "inputs", "cost_preflight.json"),
                    {"schema_version": 1, "generated_by": "cost_preflight.py",
                     "mode": "scan", "walltime_h": [1, 2]})
        os.remove(os.path.join(rd, "inputs", "checkin1_approval.json"))
        return rd, contract

    def _approval_check(result):
        row = next((i for i in result["invariants"] if i["name"] == "approval-before-compute"), None)
        if row is None or row["status"] != "FAIL":
            return False, "expected approval-before-compute to FAIL"
        return True, ""
    ok, why = _selftest_case("24 compute without a recorded CHECK-IN 1 go-ahead -> FAIL "
                              "(approval-before-compute, H1)", _fixture_unapproved_compute,
                              "FAIL", 1, _approval_check)
    if not ok:
        fails.append(why)

    # a couple of cheap CLI-level checks (usage / contract-invalid exit codes)
    with tempfile.TemporaryDirectory(prefix="validate_run_state_selftest_") as td:
        not_a_dir = os.path.join(td, "does-not-exist")
        rc = main(["--rundir", not_a_dir])
        ok = rc == 2
        print(f"[selftest] 6 --rundir not a directory -> exit 2  {'ok' if ok else 'FAIL'}")
        if not ok:
            fails.append(f"expected exit 2 for a missing rundir, got {rc}")

        rd = os.path.join(td, "2026-07-08_bad_contract")
        _write_json(os.path.join(rd, "inputs", "task_contract.json"),
                    _base_contract(approval_required=False))   # invalid: approval_required must be True
        rc = main(["--rundir", rd])
        ok = rc == 3
        print(f"[selftest] 7 invalid contract -> exit 3  {'ok' if ok else 'FAIL'}")
        if not ok:
            fails.append(f"expected exit 3 for an invalid contract, got {rc}")

    with tempfile.TemporaryDirectory(prefix="validate_run_state_selftest_") as td:
        eg_rd = os.path.join(td, "run", "inputs")
        os.makedirs(eg_rd)
        eg_tc = os.path.join(eg_rd, "task_contract.json")
        _write_text(eg_tc, "{}")
        ok = edit_guard(eg_tc) == 1                                   # baselined edit, no DEVIATIONS
        _write_text(os.path.join(td, "run", "DEVIATIONS.md"), "- task_contract.json changed\n")
        ok = ok and edit_guard(eg_tc) == 0                            # named -> allow
        print(f"[selftest] 11 --edit-guard blocks a baselined edit lacking a DEVIATIONS row, allows "
              f"when named  {'ok' if ok else 'FAIL'}")
        if not ok:
            fails.append("edit_guard did not block/allow as expected")

    # provenance verification (G19): a hand-written required artifact is rejected
    with tempfile.TemporaryDirectory(prefix="validate_run_state_selftest_") as td:
        rd = os.path.join(td, "2026-07-09_prov_handwritten")
        _write_json(os.path.join(rd, "outputs", "sr_yields.json"),
                    [{"name": "SR1", "n": 5, "b": 4.0, "db": 1.0, "s": 3.0}])
        _write_json(os.path.join(rd, "outputs", "pyhf_exclusion", "exclusion.json"),
                    {"obs_limit": 0.7, "exp_limits": [0.4, 0.55, 0.7, 0.95, 1.3], "per_sr": {}, "best_sr": "SR1"})
        _write_json(os.path.join(rd, "outputs", "sr_plausibility.json"),
                    {"schema_version": 1, "verdict": "plausible"})   # hand-written: no generated_by
        contract = _base_contract(task_mode="reproduce", stat_mode="best-sr-counting", compute_plan="full",
                                  detector_mode="simpleanalysis-delphes-native",
                                  cost_estimate={"mode": "full", "points": 1, "walltime_h": [1, 2]})
        v = verify_provenance_lifecycle(rd, contract, discover_facts(rd, contract))
        ok = any("generated_by" in x for x in v)
        print(f"[selftest] 18 hand-written sr_plausibility.json rejected by --verify-provenance  {'ok' if ok else 'FAIL'}")
        if not ok:
            fails.append("expected verify_provenance_lifecycle to reject a hand-written sr_plausibility.json")

    # provenance verification (G19): an input_fingerprint that no longer matches the inputs is rejected
    with tempfile.TemporaryDirectory(prefix="validate_run_state_selftest_") as td:
        rd = os.path.join(td, "2026-07-09_prov_fingerprint")
        _write_json(os.path.join(rd, "outputs", "sr_yields.json"),
                    [{"name": "SR1", "n": 5, "b": 4.0, "db": 1.0, "s": 3.0}])
        _write_json(os.path.join(rd, "outputs", "pyhf_exclusion", "exclusion.json"),
                    {"obs_limit": 0.7, "exp_limits": [0.4, 0.55, 0.7, 0.95, 1.3], "per_sr": {}, "best_sr": "SR1"})
        good_fp = recompute_input_fingerprint(rd, ("outputs/sr_yields.json",
                                                   "outputs/pyhf_exclusion/exclusion.json"))
        _write_json(os.path.join(rd, "outputs", "sr_plausibility.json"),
                    {"schema_version": 1, "generated_by": "sr_plausibility.py",
                     "input_fingerprint": good_fp, "verdict": "plausible"})
        contract = _base_contract(task_mode="reproduce", stat_mode="best-sr-counting", compute_plan="full",
                                  detector_mode="simpleanalysis-delphes-native",
                                  cost_estimate={"mode": "full", "points": 1, "walltime_h": [1, 2]})
        clean = verify_provenance_lifecycle(rd, contract, discover_facts(rd, contract)) == []
        _write_json(os.path.join(rd, "outputs", "sr_yields.json"),
                    [{"name": "SR1", "n": 999, "b": 4.0, "db": 1.0, "s": 3.0}])   # tamper an input
        tampered = verify_provenance_lifecycle(rd, contract, discover_facts(rd, contract))
        ok = clean and any("input_fingerprint" in x for x in tampered)
        print(f"[selftest] 19 sr_plausibility.json input_fingerprint mismatch rejected  {'ok' if ok else 'FAIL'}")
        if not ok:
            fails.append("expected verify_provenance_lifecycle to accept a faithful artifact and reject a tampered one")

    if fails:
        for f in fails:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print(f"validate_run_state selftest: {21 + 3} case(s) judged correctly.")
    return 0


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rundir", help="the run directory to validate")
    ap.add_argument("--stage", choices=STAGE_ORDER,
                     help="validate only the PREFIX up to & including this stage")
    ap.add_argument("--contract", help="override the task_contract.json path")
    ap.add_argument("--strict", action="store_true",
                     help="escalate soft WARNs (unlocatable pairing inputs, verify_pack FAIL) to FAIL")
    ap.add_argument("--json", action="store_true", help="emit the machine JSON report")
    ap.add_argument("--selftest", action="store_true", help="run the embedded fixture selftest")
    ap.add_argument("--backfill-plan", action="store_true",
                     help="PRINT the exact missing artifacts + commands to produce them; writes nothing")
    ap.add_argument("--edit-guard", metavar="PATH",
                     help="moment-of-change guard: exit 1 (block) if PATH is a CHECK-IN-1-baselined "
                          "input edited without a DEVIATIONS.md row naming it (else 0)")
    ap.add_argument("--verify-provenance", action="store_true",
                     help="reject a PRESENT required artifact whose generated_by/input_fingerprint "
                          "does not prove its tool produced it (closes the backfill loophole)")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()

    if args.edit_guard:
        return edit_guard(args.edit_guard)

    if not args.rundir:
        print(__doc__, file=sys.stderr)
        return 2
    rundir = args.rundir.rstrip("/")
    if not os.path.isdir(rundir):
        print(f"validate_run_state: not a directory: {rundir}", file=sys.stderr)
        return 2

    contract, cpath, err = load_contract_for(rundir, args.contract)
    if err:
        print(f"validate_run_state: {err}", file=sys.stderr)
        return 2

    errs = validate_task_contract.validate(contract)
    if errs:
        print(f"INVALID task contract ({cpath}):", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 3

    if args.backfill_plan:
        print(backfill_plan(rundir, contract))
        return 0

    if args.verify_provenance:
        pv = verify_provenance(rundir, contract)
        facts = discover_facts(rundir, contract)
        lifecycle_violations = verify_provenance_lifecycle(rundir, contract, facts)
        if args.json:
            print(json.dumps(pv, indent=2))
        else:
            for c in pv["checks"]:
                print(f"[{c['status']}] {c['artifact']}: {c['detail']}")
            print(f"verify-provenance: {pv['verdict']}")
        for v in lifecycle_violations:
            print(f"PROVENANCE FAIL: {v}", file=sys.stderr)
        return 1 if (lifecycle_violations or pv["exit"] == 1) else 0

    result = evaluate(rundir, contract, stage_limit=args.stage, strict=args.strict)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_human(result)
    return result["exit"]


if __name__ == "__main__":
    sys.exit(main())
