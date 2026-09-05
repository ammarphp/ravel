#!/usr/bin/env python3
"""stop_dispatch.py -- the Stop-hook dispatcher brain (one dispatcher, many branches).
Reads the Stop-hook JSON on stdin (session_id, cwd, transcript_path), resolves the active rundir
(the run_state.json whose session_id matches, else the newest), evaluates the branches in priority
order, and exits 2 (blocking turn-end; stderr = reason fed back to the agent) on the first BLOCK,
else 0. Reuses validate_run_state.py for the D18 umbrella; reads run_state.json (SHARED-CONVENTIONS
§C) for the ledger branches. stdlib-only. The .sh shim pipes stdin here.
EXIT MAPPING (a hook, not a validator): 2 = BLOCK * 0 = allow OR fail-open (a crash never blocks the
live agent -- the step-doc FALLBACK covers it) * 3 = usage."""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.workflow"

from pathlib import Path
from ravel.paths import repository_root

import argparse, json, os, re, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_DEFAULT = str(repository_root() or Path.cwd())

DELIVERY_RE = re.compile(
    r"(?i)(check[-\s]?in\s*[12]?\b|results?\s+deck|final\s+check[-\s]?in|"
    r"verification[-\s]panel\s+verdict|result\.md)")

RUNNING_RE = re.compile(
    r"(?i)(running in the background|in the background|kicked off|backgrounded|now running|"
    r"still running|is running|launched .{0,40}background|monitoring the (?:run|job|scan)|"
    r"will (?:ping|notify|update|let you know) .{0,30}(?:done|complete|finish))")
PHANTOM_WINDOW_SECS = 180.0
DRIVE_RECENT_SECS = 600.0
DETACH_HEARTBEAT_SECS = 600.0
_PIPE_PROCS = ("run-pipeline-native", "mg5_aMC", "DelphesHepMC", "pythia_shower",
               "native_simpleanalysis", "delphes2sa", "scan_orchestrator")

def _read_stdin_json():
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}

def resolve_rundir(session_id, repo, explicit=None):
    if explicit:
        return explicit
    import glob
    best, best_m = None, -1.0
    for p in glob.glob(os.path.join(repo, "trial-runs", "*", "run_state.json")):
        try:
            obj = json.load(open(p))
        except Exception:
            continue
        rd = os.path.dirname(p)
        if session_id and obj.get("session_id") == session_id:
            return rd
        m = os.path.getmtime(p)
        if m > best_m:
            best, best_m = rd, m
    return best

def load_run_state(rundir):
    try:
        return json.load(open(os.path.join(rundir, "run_state.json")))
    except Exception:
        return {}

def read_last_assistant_message(transcript_path):
    if not transcript_path or not os.path.isfile(transcript_path):
        return ""
    text = ""
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if (obj.get("role") or obj.get("type")) != "assistant":
                    continue
                content = (obj.get("message", obj)).get("content")
                parts = []
                if isinstance(content, str):
                    parts.append(content)
                elif isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "text":
                            parts.append(b.get("text", ""))
                        elif isinstance(b, str):
                            parts.append(b)
                if parts:
                    text = "\n".join(parts)
    except OSError:
        return ""
    return text

DELIVERY_ARTIFACTS = ("inputs/checkin2.json", "outputs/results_deck.html",
                      "outputs/results_deck.md", "RESULT.md")
DELIVERY_FRESH_SECS = 1800


def _delivery_artifacts_fresh(rundir, window_s=DELIVERY_FRESH_SECS):
    """H7 (R3): delivery detection keys on DISK FACTS, not only the last message -- a freshly
    written checkin2/deck/RESULT means this IS a delivery turn whatever the prose said."""
    import time as _time
    now = _time.time()
    for rel in DELIVERY_ARTIFACTS:
        p = os.path.join(rundir or "", rel)
        try:
            if os.path.isfile(p) and (now - os.path.getmtime(p)) <= window_s:
                return True
        except OSError:
            pass
    return False


def branch_d18(ctx):
    if not DELIVERY_RE.search(ctx.get("last_message") or ""):
        return False, ""
    validator = [sys.executable,
                 os.path.join(ctx["repo"], "src/ravel/validation/validate_run_state.py")]
    try:
        r = subprocess.run(validator + ["--rundir", ctx["rundir"]],
                           capture_output=True, text=True, timeout=120)
    except Exception:
        return False, ""                      # fail-open on a validator crash
    if r.returncode != 0:
        tail = (r.stdout or r.stderr or "").strip().splitlines()
        tail = tail[-1] if tail else f"exit {r.returncode}"
        return True, ("D18: this is a CHECK-IN/RESULT delivery turn but validate_run_state.py "
                      f"--rundir exits {r.returncode}: {tail}. Fix the failing stage/invariant "
                      "before delivering.")
    return False, ""

def branch_catch(ctx):
    unresolved = []
    for root, _d, files in os.walk(ctx["rundir"]):
        for f in files:
            if not f.endswith(".failure.json"):
                continue
            p = os.path.join(root, f)
            try:
                rec = json.load(open(p))
            except Exception:
                rec = {}
            status = (rec.get("status") or "").lower()
            if not rec.get("handled") and status not in ("resolved", "handled", "closed"):
                unresolved.append(os.path.relpath(p, ctx["rundir"]))
    if unresolved:
        return True, ("CATCH/D6: unhandled failure record(s): " + ", ".join(unresolved[:5]) +
                      '. Resolve each (diagnose+fix or reset the point), then set its '
                      '"status":"resolved", before ending the turn.')
    return False, ""

def _bg_liveness(run_state, rundir, window_secs):
    """True if any compute_launched entry looks live within window_secs (its logfile mtime is
    recent), OR a pipeline process for this rundir is in ps. logfile-mtime is the robust signal
    (the DRIVE `workflow_state.py record --kind compute` command writes logfile onto the entry, per
    RECONCILE D-2 -- the observer does NOT); ps is a best-effort backstop for un-recorded jobs."""
    now = time.time()
    for e in run_state.get("compute_launched", []):
        lf = e.get("logfile")
        if not lf:
            continue
        p = lf if os.path.isabs(lf) else os.path.join(rundir, lf)
        try:
            if (now - os.path.getmtime(p)) <= window_secs:
                return True
        except OSError:
            pass
    try:
        out = subprocess.run(["ps", "ax", "-o", "command"], capture_output=True, text=True).stdout
    except Exception:
        out = ""
    base = os.path.basename(os.path.normpath(rundir))
    for line in out.splitlines():
        if base and base in line and any(k in line for k in _PIPE_PROCS):
            return True
    return False

def branch_phantom(ctx):
    if not RUNNING_RE.search(ctx.get("last_message") or ""):
        return False, ""
    if _bg_liveness(ctx["run_state"], ctx["rundir"], PHANTOM_WINDOW_SECS):
        return False, ""
    return True, ("PHANTOM/D5-signature: the turn claims a background job is running, but no live "
                  "job was found (no recent logfile, no matching process). Launch it via the "
                  "harness-tracked run_in_background, or correct the claim.")

def branch_drive(ctx):
    if ctx.get("is_delivery"):
        return False, ""                      # a CHECK-IN/RESULT turn is a legitimate human-gate stop
    nr = ctx["run_state"].get("next_required")
    if not nr:
        return False, ""
    if _bg_liveness(ctx["run_state"], ctx["rundir"], DRIVE_RECENT_SECS):
        return False, ""                      # compute launched/finished this turn (live or just-done)
    what = nr.get("what") if isinstance(nr, dict) else nr
    why = (nr.get("why") if isinstance(nr, dict) else "") or ""
    return True, (f"DRIVE/D4: next_required is '{what}' ({why}) but this turn launched no compute "
                  "and no live/recent background job exists. Execute the next step NOW "
                  "(run_in_background for long jobs) instead of narrating it.")

# stage -> the governing skill whose invocation the turn must not skip (SKILL-COVERAGE/G2).
# Keyed on the STAGE_ORDER stage names that workflow_state.py `advance` actually writes into
# run_state.current_step ('route'/'analysis'/'verification') -- NOT the step-doc filenames. There is
# no 'scan' STAGE_ORDER stage: scan is a task_mode, so its run-scan requirement is driven off
# task_mode below, at the 'statistics' stage where the step-8 outer loop produces the exclusion
# contour. Exact-match lookup (a bare stage name is never a substring of another).
REQUIRED_SKILL_FOR_STEP = {
    "route": "route-analysis",
    "generation": "run-stage",     # A5 (trial QE.8): bespoke generation lost lhe_check/supervisor
    "analysis": "certify",
    "verification": "verification-panel",
}

def branch_skill_coverage(ctx):
    rs = ctx["run_state"]
    step = rs.get("current_step") or ""
    need = REQUIRED_SKILL_FOR_STEP.get(step)
    if need is None and rs.get("task_mode") == "scan" and step == "statistics":
        need = "run-scan"                     # 'scan' is a task_mode, not a STAGE_ORDER stage
    if not need:
        return False, ""
    invoked = {s.get("skill") for s in rs.get("skills_invoked", [])
               if isinstance(s, dict)}
    if need in invoked:
        return False, ""
    return True, (f"SKILL-COVERAGE/G2: current step {step} requires the '{need}' skill but "
                  "run_state.skills_invoked has no such entry. Invoke it before advancing.")

def branch_detach(ctx):
    bad = []
    for e in ctx["run_state"].get("compute_launched", []):
        if e.get("bg_kind") != "detached":
            continue
        missing = [k for k in ("logfile", "done_condition", "next_action") if not e.get(k)]
        heartbeat = False
        lf = e.get("logfile")
        if lf:
            p = lf if os.path.isabs(lf) else os.path.join(ctx["rundir"], lf)
            try:
                heartbeat = (time.time() - os.path.getmtime(p)) <= DETACH_HEARTBEAT_SECS
            except OSError:
                heartbeat = False
        if missing or not heartbeat:
            tag = e.get("bg_id") or (e.get("cmd", "?")[:40])
            bad.append(f"{tag} (missing {missing or 'live-heartbeat'})")
    if bad:
        return True, ("DETACH/N6: detached job(s) without a durable run_state+heartbeat: " +
                      "; ".join(bad) + ". Use the harness-tracked run_in_background, or record "
                      "logfile+done_condition+next_action AND keep a live heartbeat.")
    return False, ""

# BRANCHES is a deliberate append-point (RECONCILE D-4): Phase 4b appends its predicate-CLI branches
# after 'drive', keeping this Phase-2 prefix order intact. Every branch here shells only Phase-1/2
# instruments (validate_run_state.py, run_state.json, ps), so --selftest and the per-branch tests
# pass before any Phase-4b tool lands.
BRANCHES = [
    ("d18", branch_d18),
    ("catch", branch_catch),
    ("detach", branch_detach),
    ("phantom", branch_phantom),
    ("skill-coverage", branch_skill_coverage),
    ("drive", branch_drive),
]

def branch_recipe_search(ctx):
    """G8 (D8 RESOLVE): refuse turn-end while an OPEN generator-model failure lacks a recipe_search.json.
    Non-invariant -> wired here as its own branch, not under the D18 umbrella."""
    census = os.path.join(ctx["repo"], "src/ravel/workflow/resource_census.py")
    try:
        r = subprocess.run([sys.executable, census, "--assert-recipe-search", "--rundir", ctx["rundir"]],
                           capture_output=True, text=True, timeout=120)
    except Exception:
        return False, ""                      # fail-open on a predicate crash (a hook never wedges the agent)
    if r.returncode == 1:
        tail = (r.stdout or r.stderr or "").strip().splitlines()
        tail = tail[-1] if tail else "open generator-model failure without inputs/recipe_search.json"
        return True, ("G8-RECIPE-SEARCH: " + tail + " Run `resource_census.py --debug recipe-search` "
                      "CO-PRIMARY before closing the failure (D8 RESOLVE).")
    return False, ""

# disk-derived stage index (H2/R3): the cursor is NOT optional. Local mirror of the STAGE_ORDER
# indices this branch can cheaply detect from artifacts (coarser than validate_run_state -- it only
# needs ORDER, not completeness).
_DRIFT_STAGES = ("generation", "statistics", "result_pack")
_DRIFT_IDX = {"task_contract": 0, "resource_census": 1, "trap_sweep": 2, "route": 3,
              "figure_contract": 4, "basis_manifest": 5, "generation": 6, "analysis": 7,
              "statistics": 8, "result_pack": 9, "verification": 10}


def _disk_stage_idx(rundir):
    """The furthest STAGE_ORDER index the on-disk artifacts attest. -1 = none."""
    import glob as _glob
    idx = -1
    if _glob.glob(os.path.join(rundir, "outputs", "**", "sr_yields*.json"), recursive=True)             or _glob.glob(os.path.join(rundir, "outputs", "sr_yields*.json")):
        idx = max(idx, _DRIFT_IDX["generation"])
    for nm in ("exclusion.json", "shape_fit.json", "sensitivity.json", "scan.json"):
        if _glob.glob(os.path.join(rundir, "**", nm), recursive=True):
            idx = max(idx, _DRIFT_IDX["statistics"])
            break
    for nm in ("result.json", "figures.json", "projection.json"):
        if os.path.isfile(os.path.join(rundir, nm)):
            idx = max(idx, _DRIFT_IDX["result_pack"])
            break
    if os.path.isfile(os.path.join(rundir, "outputs", "survey.json")):
        idx = max(idx, _DRIFT_IDX["result_pack"])
    return idx


def branch_stage_drift(ctx):
    """H2+H8 (R3): BLOCK when the disk is ahead of run_state.current_step (the state machine was
    bypassed) or when the run progressed with an EMPTY ledger (the observer may be dead)."""
    rs = ctx.get("run_state") or {}
    if not rs:
        return False, ""
    rundir = ctx.get("rundir") or ""
    disk = _disk_stage_idx(rundir)
    if disk < 0:
        return False, ""
    stage_name = next((n for n, i in _DRIFT_IDX.items() if i == disk), "?")
    cursor = rs.get("current_step") or ""
    cursor_idx = _DRIFT_IDX.get(cursor, -1)
    if disk > cursor_idx:
        return True, (f"STAGE-DRIFT: the disk shows the run at '{stage_name}' but "
                      f"run_state.current_step={cursor!r} -- the state cursor is NOT optional. Run "
                      f"`python3 src/ravel/workflow/workflow_state.py advance --rundir "
                      f"{rundir} --to {stage_name}` (it enforces the stage preconditions).")
    if disk >= _DRIFT_IDX["generation"] and not rs.get("skills_invoked")             and not rs.get("compute_launched"):
        return True, (f"LEDGER-EMPTY: the run progressed to '{stage_name}' but skills_invoked and "
                      "compute_launched are BOTH empty -- the PostToolUse observer may be dead. "
                      "Record via the fallback (`workflow_state.py record --kind skill|compute ...`) "
                      "and verify the .claude/settings.json hook wiring.")
    return False, ""


BRANCHES.append(("stage-drift", branch_stage_drift))


BRANCHES.append(("recipe-search", branch_recipe_search))

def branch_armed_watcher(ctx):
    """G24/N3: refuse turn-end while an armed completion-watcher lacks a passing preflight.
    Non-invariant -> wired here as its own branch, not under the D18 umbrella."""
    pf = os.path.join(ctx["repo"], "src/ravel/workflow/preflight_watcher.py")
    try:
        r = subprocess.run([sys.executable, pf, "--assert-all", "--rundir", ctx["rundir"]],
                           capture_output=True, text=True, timeout=120)
    except Exception:
        return False, ""                      # fail-open on a predicate crash
    if r.returncode == 1:
        tail = (r.stdout or r.stderr or "").strip().splitlines()
        tail = tail[-1] if tail else "an armed watcher lacks a passing preflight"
        return True, ("G24-ARMED-WATCHER: " + tail + " Arm every completion-watcher with "
                      "`preflight_watcher.py --arm` (a passing preflight) before backgrounding it (N3).")
    return False, ""

BRANCHES.append(("armed-watcher", branch_armed_watcher))

def branch_open_defect(ctx):
    """G26/N5, DELIVERY-only: a helper with an OPEN defect note must not feed a delivery. Gated on
    ctx['is_delivery'] so ordinary mid-run turns are never blocked. Non-invariant -> wired here."""
    if not ctx.get("is_delivery"):
        return False, ""
    vp = os.path.join(ctx["repo"], "src/ravel/validation/verify_pack.py")
    try:
        r = subprocess.run([sys.executable, vp, ctx["rundir"]],
                           capture_output=True, text=True, timeout=120)
    except Exception:
        return False, ""                      # fail-open on a predicate crash
    out = ((r.stdout or "") + (r.stderr or "")).lower()
    if r.returncode == 1 and "open defect note" in out:
        return True, ("G26-OPEN-DEFECT: a helper with an OPEN defect note feeds this delivery -- resolve "
                      "the note (set run_state.open_defect_notes[].status=fixed) or substitute the "
                      "blessed tool (N5) before delivering.")
    return False, ""

BRANCHES.append(("open-defect", branch_open_defect))

def dispatch(ctx, only=None):
    for name, fn in BRANCHES:
        if only and name != only:
            continue
        block, reason = fn(ctx)
        if block:
            return name, reason
    return None, ""

# ---- selftest ---------------------------------------------------------------
def _mk_run(tmp, **state):
    os.makedirs(os.path.join(tmp, "logs"), exist_ok=True)
    st = {"schema_version": 1, "session_id": "SELFTEST"}; st.update(state)
    json.dump(st, open(os.path.join(tmp, "run_state.json"), "w"))
    return tmp

def _ctx(tmp, last_message="", **over):
    c = {"repo": REPO_DEFAULT, "rundir": tmp, "session": "SELFTEST",
         "run_state": load_run_state(tmp), "last_message": last_message,
         "is_delivery": bool(DELIVERY_RE.search(last_message or ""))
                        or _delivery_artifacts_fresh(tmp)}
    c.update(over); return c

def _selftest_d18(fails):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        _mk_run(tmp)
        b, _ = branch_d18(_ctx(tmp, "Here is CHECK-IN 1 for your approval."))
        p, _ = branch_d18(_ctx(tmp, "Working on the analysis."))
        ok = (b is True) and (p is False)
        print(f"[selftest] d18 block/pass: {b}/{p}  {'ok' if ok else 'FAIL'}")
        if not ok: fails.append("d18 branch block/pass wrong")

def _selftest_catch(fails):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        _mk_run(tmp)
        json.dump({"stage": "pythia", "status": "open"},
                  open(os.path.join(tmp, "logs", "pythia.failure.json"), "w"))
        b, _ = branch_catch(_ctx(tmp))
        os.remove(os.path.join(tmp, "logs", "pythia.failure.json"))
        json.dump({"stage": "pythia", "status": "resolved"},
                  open(os.path.join(tmp, "logs", "pythia.failure.json"), "w"))
        p, _ = branch_catch(_ctx(tmp))
        ok = (b is True) and (p is False)
        print(f"[selftest] catch block/pass: {b}/{p}  {'ok' if ok else 'FAIL'}")
        if not ok: fails.append("catch branch block/pass wrong")

def _selftest_phantom(fails):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        _mk_run(tmp)
        b, _ = branch_phantom(_ctx(tmp, "The scan is now running in the background."))
        lf = os.path.join(tmp, "logs", "x.log"); open(lf, "w").write("run")
        ctx = _ctx(tmp, "The scan is now running in the background.")
        ctx["run_state"] = {"compute_launched": [{"bg_kind": "harness", "logfile": lf}]}
        p, _ = branch_phantom(ctx)
        ok = (b is True) and (p is False)
        print(f"[selftest] phantom block/pass: {b}/{p}  {'ok' if ok else 'FAIL'}")
        if not ok: fails.append("phantom branch block/pass wrong")

def _selftest_drive(fails):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        _mk_run(tmp, next_required={"what": "run-stage madgraph", "why": "generation"})
        b, _ = branch_drive(_ctx(tmp, "Next I'll generate the events."))
        lf = os.path.join(tmp, "logs", "m.log"); open(lf, "w").write("run")
        ctx = _ctx(tmp, "Next I'll generate the events.")
        ctx["run_state"] = {"next_required": {"what": "x"},
                            "compute_launched": [{"logfile": lf}]}
        p, _ = branch_drive(ctx)
        d, _ = branch_drive(_ctx(tmp, "Here is CHECK-IN 1."))   # delivery -> pass
        ok = (b is True) and (p is False) and (d is False)
        print(f"[selftest] drive block/pass/delivery: {b}/{p}/{d}  {'ok' if ok else 'FAIL'}")
        if not ok: fails.append("drive branch block/pass wrong")

def _selftest_skill(fails):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        _mk_run(tmp, current_step="verification", skills_invoked=[{"skill": "run-scan"}])
        b, _ = branch_skill_coverage(_ctx(tmp))
        _mk_run(tmp, current_step="verification", skills_invoked=[{"skill": "verification-panel"}])
        p, _ = branch_skill_coverage(_ctx(tmp))
        # 'scan' is a task_mode, not a stage: exercise the task_mode-driven run-scan requirement too.
        _mk_run(tmp, current_step="statistics", task_mode="scan", skills_invoked=[])
        sb, _ = branch_skill_coverage(_ctx(tmp))
        _mk_run(tmp, current_step="statistics", task_mode="scan",
                skills_invoked=[{"skill": "run-scan"}])
        sp, _ = branch_skill_coverage(_ctx(tmp))
        ok = (b is True) and (p is False) and (sb is True) and (sp is False)
        print(f"[selftest] skill-coverage block/pass/scan-block/scan-pass: "
              f"{b}/{p}/{sb}/{sp}  {'ok' if ok else 'FAIL'}")
        if not ok: fails.append("skill-coverage branch block/pass wrong")

def _selftest_stage_drift(fails):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "outputs"))
        json.dump({"srs": {"SR1": 1.0}}, open(os.path.join(tmp, "outputs", "sr_yields.json"), "w"))
        json.dump({"schema_version": 1, "session_id": "S", "current_step": "route",
                   "skills_invoked": [{"skill": "physicist-intake"}],
                   "compute_launched": [{"cmd": "x"}]},
                  open(os.path.join(tmp, "run_state.json"), "w"))
        ctx = {"rundir": tmp, "run_state": json.load(open(os.path.join(tmp, "run_state.json"))),
               "last_message": "", "is_delivery": False, "repo": REPO_DEFAULT}
        b1, r1 = branch_stage_drift(ctx)
        ctx["run_state"]["current_step"] = "generation"
        b2, _ = branch_stage_drift(ctx)
        ctx["run_state"]["skills_invoked"] = []
        ctx["run_state"]["compute_launched"] = []
        b3, r3 = branch_stage_drift(ctx)
        ok = b1 and "STAGE-DRIFT" in r1 and not b2 and b3 and "LEDGER-EMPTY" in r3
        print(f"[selftest] stage-drift block/aligned/ledger-empty: {b1}/{not b2}/{b3}  "
              f"{'ok' if ok else 'FAIL'}")
        if not ok:
            fails.append("stage-drift selftest")


def _selftest_detach(fails):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        _mk_run(tmp, compute_launched=[{"bg_kind": "detached", "logfile": "logs/j.log"}])
        b, _ = branch_detach(_ctx(tmp))
        lf = os.path.join(tmp, "logs", "j.log"); open(lf, "w").write("beat")
        ctx = _ctx(tmp)
        ctx["run_state"] = {"compute_launched": [{"bg_kind": "detached", "logfile": lf,
                            "done_condition": "excl exists", "next_action": "harvest"}]}
        p, _ = branch_detach(ctx)
        ok = (b is True) and (p is False)
        print(f"[selftest] detach block/pass: {b}/{p}  {'ok' if ok else 'FAIL'}")
        if not ok: fails.append("detach branch block/pass wrong")

def _selftest_recipe_search(fails):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        _mk_run(tmp, open_failure_records=["logs/madgraph.failure.json"])
        json.dump({"stage": "madgraph", "failure_class": "tool_generator_model"},
                  open(os.path.join(tmp, "logs", "madgraph.failure.json"), "w"))
        b, _ = branch_recipe_search(_ctx(tmp))
        os.makedirs(os.path.join(tmp, "inputs"), exist_ok=True)
        json.dump({"schema_version": 1, "mode": "recipe-search"},
                  open(os.path.join(tmp, "inputs", "recipe_search.json"), "w"))
        p, _ = branch_recipe_search(_ctx(tmp))
        ok = (b is True) and (p is False)
        print(f"[selftest] recipe-search block/pass: {b}/{p}  {'ok' if ok else 'FAIL'}")
        if not ok: fails.append("recipe-search branch block/pass wrong")

def _selftest_armed_watcher(fails):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        _mk_run(tmp, armed_watchers=[{"name": "ghost", "preflight": "logs/ghost.preflight.json"}])
        b, _ = branch_armed_watcher(_ctx(tmp))
        _mk_run(tmp, armed_watchers=[])       # no watcher armed -> assert-all clean
        p, _ = branch_armed_watcher(_ctx(tmp))
        ok = (b is True) and (p is False)
        print(f"[selftest] armed-watcher block/pass: {b}/{p}  {'ok' if ok else 'FAIL'}")
        if not ok: fails.append("armed-watcher branch block/pass wrong")

def _selftest_open_defect(fails):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        _mk_run(tmp, open_defect_notes=[{"helper": "read_yoda.py", "note": "A x e reads 956%",
                                         "status": "open"}])
        b, _ = branch_open_defect(_ctx(tmp, "Here is the results deck."))     # delivery -> block
        n, _ = branch_open_defect(_ctx(tmp, "still working on it"))           # non-delivery -> pass
        _mk_run(tmp, open_defect_notes=[{"helper": "read_yoda.py", "note": "fixed", "status": "fixed"}])
        p, _ = branch_open_defect(_ctx(tmp, "Here is the results deck."))     # fixed -> pass
        ok = (b is True) and (n is False) and (p is False)
        print(f"[selftest] open-defect block/nondelivery/pass: {b}/{n}/{p}  {'ok' if ok else 'FAIL'}")
        if not ok: fails.append("open-defect branch block/nondelivery/pass wrong")

def selftest():
    fails = []
    _selftest_d18(fails)
    _selftest_catch(fails)
    _selftest_phantom(fails)
    _selftest_drive(fails)
    _selftest_skill(fails)
    _selftest_detach(fails)
    _selftest_stage_drift(fails)
    _selftest_recipe_search(fails)
    _selftest_armed_watcher(fails)
    _selftest_open_defect(fails)
    if fails:
        for f in fails: print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("stop_dispatch selftest: PASS")
    return 0

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rundir"); ap.add_argument("--session"); ap.add_argument("--transcript")
    ap.add_argument("--last-message"); ap.add_argument("--branch"); ap.add_argument("--repo")
    args = ap.parse_args(argv)
    repo = args.repo or os.environ.get("CLAUDE_PROJECT_DIR") or REPO_DEFAULT
    session, transcript, last_message = args.session, args.transcript, args.last_message
    if session is None or transcript is None:
        data = _read_stdin_json()
        session = session or data.get("session_id")
        transcript = transcript or data.get("transcript_path")
    rundir = resolve_rundir(session, repo, explicit=args.rundir)
    if not rundir or not os.path.isdir(rundir):
        return 0                              # nothing to gate -> fail-open
    if last_message is None:
        last_message = read_last_assistant_message(transcript)
    last_message = last_message or ""
    ctx = {"repo": repo, "rundir": rundir, "session": session, "run_state": load_run_state(rundir),
           "last_message": last_message,
           "is_delivery": bool(DELIVERY_RE.search(last_message))
                          or _delivery_artifacts_fresh(rundir)}
    name, reason = dispatch(ctx, only=args.branch)
    if name:
        print(reason, file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    sys.exit(main())
