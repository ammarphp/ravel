#!/usr/bin/env python3
"""tests/adversarial/_case_lib.py -- the shared toolkit every spine_sim case imports.

Builds throwaway rundir/session fixtures, drives hooks + infra tools as subprocesses, and asserts
a gate FIRED. stdlib-only. Contracts are built via validate_run_state._base_contract so they always
pass validate_task_contract. A case is a tiny script:

    import _case_lib as L
    @L.case_main
    def run():
        with L.tempdir() as td:
            rd = ...; L.write_contract(rd, task_mode="scan", ...)
            res, rc = L.run_validate(rd)
            L.gate_fired(L.invariant_status(res, "ladder-order") == "FAIL", "...")
    if __name__ == "__main__":
        import sys; sys.exit(run())
"""
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))          # tests/adversarial -> tests -> repo
SOURCE = os.path.join(REPO, "src")
for _p in (SOURCE, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ravel.validation import validate_task_contract  # noqa: E402
from ravel.validation import validate_run_state as vrs  # noqa: E402

VRS_PY = os.path.join(SOURCE, "ravel", "validation", "validate_run_state.py")

# logical name -> hook script relpath (produced by Phases 0/2/3/4; drive by relpath so a branch
# moving files touches ONE line here, not every case).
HOOKS = {
    "cards": ".claude/hooks/protect-original-cards.sh",
    "stop": ".claude/hooks/stop-dispatcher.sh",
    "router": ".claude/hooks/userpromptsubmit-router.sh",
    "pretooluse_skill": ".claude/hooks/pretooluse-skill.sh",
    "pre_generate": ".claude/hooks/pre-generate-guard.sh",
    "deviations": ".claude/hooks/deviations-guard.sh",
}
# Stop-dispatch branch -> the UPPERCASE token its BLOCK reason carries on stderr. The first six are
# Phase 2's branches (p2 contract); the last three are the D-4 NON-invariant branches Phase 4b appends
# to stop_dispatch.py's BRANCHES (recipe-search/G8, armed-watcher/G24, open-defect/G26).
STOP_TOKENS = {"d18": "D18", "catch": "CATCH", "phantom": "PHANTOM", "drive": "DRIVE",
               "skill-coverage": "SKILL-COVERAGE", "detach": "DETACH",
               "recipe-search": "G8-RECIPE-SEARCH", "armed-watcher": "G24-ARMED-WATCHER",
               "open-defect": "G26-OPEN-DEFECT"}


class CaseSetupError(Exception):
    """The fixture could not be built / an enforcing tool is not on disk -> case ERROR (exit 2)."""


class GateDidNotFire(AssertionError):
    """The seeded trigger did NOT make the gate fire -> case FAIL (exit 1)."""


def case_main(fn):
    def wrapper():
        try:
            fn()
        except CaseSetupError as e:
            print(f"[SETUP-ERROR] {e}", file=sys.stderr)
            return 2
        except GateDidNotFire as e:
            print(f"[GATE-DID-NOT-FIRE] {e}", file=sys.stderr)
            return 1
        except Exception as e:  # any unexpected explosion is a setup error, not a silent pass
            print(f"[SETUP-ERROR] unexpected {type(e).__name__}: {e}", file=sys.stderr)
            return 2
        print("[FIRED] gate fired as expected")
        return 0
    return wrapper


def gate_fired(cond, msg):
    if not cond:
        raise GateDidNotFire(msg)


def assert_block(cp, token):
    out = ((cp.stderr or "") + (cp.stdout or "")).upper()
    gate_fired(cp.returncode == 2 and token.upper() in out,
               f"expected exit 2 + {token!r} on stderr, got rc={cp.returncode} out={out[:200]!r}")


@contextlib.contextmanager
def tempdir():
    d = tempfile.mkdtemp(prefix="spine_sim_case_")
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def write_json(rundir, rel, obj):
    p = os.path.join(rundir, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(obj, f, indent=2)
    return p


def write_text(rundir, rel, text):
    p = os.path.join(rundir, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)
    return p


def write_contract(rundir, **over):
    c = vrs._base_contract(**over)
    # full/scan compute plans require a cost_estimate to pass validate_task_contract; backfill a
    # smoke-sized placeholder when the caller didn't supply one so a fixture contract always
    # validates (the toolkit's promise: write_contract -> a valid task_contract.json).
    if c.get("compute_plan") in ("full", "scan") and c.get("cost_estimate") in (None, {}):
        c["cost_estimate"] = {"mode": c["compute_plan"], "points": 1, "walltime_h": [1, 2]}
    errs = validate_task_contract.validate(c)
    if errs:
        raise CaseSetupError(f"fixture contract invalid: {errs}")
    write_json(rundir, "inputs/task_contract.json", c)
    return c


def write_run_state(rundir, **over):
    st = {
        "schema_version": 1, "generated_by": "workflow_state.py", "input_fingerprint": "deadbeef",
        "session_id": "spine-sim", "task_mode": "reproduce", "stat_mode": "best-sr-counting",
        "detector_mode": "simpleanalysis-delphes-native", "compute_plan": "smoke",
        "current_step": "03-generate", "ladder_rung": "smoke", "cursor_utc": "2026-07-09T00:00:00Z",
        "routed": True, "skills_invoked": [], "compute_launched": [], "subagents": [], "edits": [],
        "obligations": [], "open_failure_records": [], "open_defect_notes": [], "armed_watchers": [],
        "next_required": None, "checkins": [],
    }
    st.update(over)
    return write_json(rundir, "run_state.json", st)


def run_validate(rundir, extra=()):
    cmd = [sys.executable, VRS_PY, "--rundir", rundir, "--json"] + list(extra)
    p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    if p.returncode in (2, 3) or not (p.stdout or "").strip():
        raise CaseSetupError(f"validate_run_state exit {p.returncode}: "
                             f"{(p.stderr or '').strip()[:300]}")
    try:
        res = json.loads(p.stdout)
    except json.JSONDecodeError as e:
        raise CaseSetupError(f"validate_run_state non-JSON stdout: {e}")
    return res, p.returncode


def invariant_status(res, name):
    for i in res.get("invariants", []):
        if i.get("name") == name:
            return i.get("status")
    return None


def stage_status(res, name):
    for s in res.get("stages", []):
        if s.get("name") == name:
            return s.get("status")
    return None


def tool_path(name):
    for base in [os.path.join(SOURCE, "ravel", domain)
                 for domain in ("workflow", "validation", "physics", "plotting")] + [
                     os.path.join(REPO, "scripts"), HERE]:
        p = os.path.join(base, name)
        if os.path.isfile(p):
            return p
    raise CaseSetupError(f"tool not on disk (owning phase not landed?): {name}")


def run_tool(name, args, timeout=120):
    p = tool_path(name)
    return subprocess.run([sys.executable, p] + list(args), cwd=REPO,
                          capture_output=True, text=True, timeout=timeout)


def drive_hook(hook_rel, stdin_obj, extra_env=None):
    hook = os.path.join(REPO, hook_rel)
    if not os.path.isfile(hook):
        raise CaseSetupError(f"hook not on disk (owning phase not landed?): {hook_rel}")
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = REPO
    if extra_env:
        env.update(extra_env)
    return subprocess.run(["bash", hook], input=json.dumps(stdin_obj), text=True,
                          capture_output=True, cwd=REPO, env=env, timeout=120)


def drive_stop(rundir, branch, last_message="", extra=()):
    dp = tool_path("stop_dispatch.py")
    cmd = [sys.executable, dp, "--rundir", rundir, "--last-message", last_message,
           "--branch", branch] + list(extra)
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=120)


def spike_check(spk):
    art = os.path.join(REPO, "tests", "fixtures", "hook-probes", f"{spk.lower()}.json")
    if not os.path.isfile(art):
        raise CaseSetupError(f"spike attestation missing (Phase 0 not landed?): {art}")
    p = run_tool("spike_probe.py", ["--spike", spk, "--check", art])
    gate_fired(p.returncode == 0,
               f"spike_probe --spike {spk} --check exit {p.returncode}: {(p.stderr or '')[:200]}")


def attest(rel_under_repo, expect="PASS"):
    art = os.path.join(REPO, rel_under_repo)
    if not os.path.isfile(art):
        raise CaseSetupError(f"attestation artifact missing: {rel_under_repo}")
    try:
        doc = json.loads(open(art, encoding="utf-8").read())
    except (OSError, ValueError) as e:
        raise CaseSetupError(f"attestation unreadable {rel_under_repo}: {e}")
    gate_fired(doc.get("verdict") == expect,
               f"{rel_under_repo} verdict={doc.get('verdict')!r}, expected {expect!r}")
