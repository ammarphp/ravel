#!/usr/bin/env python3
"""framework/spine_sim/clean_room.py -- the clean-room un-hinted self-drive launcher (G21/D17).

Launches a FRESH claude -p agent from the DSRLab PARENT cwd with NO project settings/CLAUDE.md
auto-load (that parent-cwd routing gap is the whole point of D17) and asserts it autonomously reaches
CHECK-IN 1 (and, with --checkin 2, CHECK-IN 2 on a cheap/dry analysis) with ZERO nudges: a valid
task_contract.json emitted, no repo survey before the route, no generation before CHECK-IN 1.

The LIVE run is slow/costed/non-deterministic -> the deterministic core is evaluate_transcript(payload),
a PURE verdict engine over a captured claude --output-format json blob (what the tests drive). --live
actually shells claude and records framework/spine_sim/self_drive/last_verdict.json (the artifact the
spine_sim G21 case attests). stdlib-only.

AUTH NOTE (EXECUTION ADJUSTMENT, D17): headless `claude -p` is NOT authenticated in this environment,
so the LIVE round-trip cannot run here -- the honest design is an AUTHENTICATED in-harness subagent (or
an authenticated interactive claude) driving the un-hinted prompt from PARENT_CWD, whose captured
--output-format json transcript is scored offline by --replay/evaluate_transcript. run_live() is kept
for a host where claude -p IS authenticated; on this host G21 is SKIP by default (run_spine_sim.py
skips it unless --with-self-drive) and never fakes a PASS.

Usage:
  clean_room.py --live [--checkin 1|2] [--out <path>] [--json]   # real launch, writes the verdict
  clean_room.py --replay <payload.json> [--json]                 # verdict from a captured payload
  clean_room.py --selftest                                       # fabricated payloads

Exit codes: 0 verdict PASS * 1 verdict FAIL * 2 usage / claude not found / launch error.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PARENT_CWD = os.path.dirname(REPO)                 # the DSRLab workspace root (the D17 launch cwd)
SELF_DRIVE_DIR = os.path.join(HERE, "self_drive")
DEFAULT_OUT = os.path.join(SELF_DRIVE_DIR, "last_verdict.json")

DRY_PROMPT = ("Initiate: reinterpret the ATLAS EWK-compressed search (ANA-SUSY-2018-16) for a single "
              "slepton point m=200, dm=50. Keep it a DRY/cheap pass -- do the routing, the survey, "
              "and the cost estimate, then stop for approval. Do not launch heavy compute.")

_SURVEY_RE = re.compile(r"\b(DIRECTORY\.md|framework/STATUS\.md|PLAN-OF-RECORD|survey the repo|"
                        r"let me (?:first )?survey|read the repo)\b", re.I)
_GENERATE_RE = re.compile(r"\b(mg5_aMC|generate_events|madgraph|pythia_shower|DelphesHepMC3|"
                          r"run-pipeline)\b", re.I)
_CHECKIN1_RE = re.compile(r"CHECK-?IN\s*1\b", re.I)
_CHECKIN2_RE = re.compile(r"CHECK-?IN\s*2\b", re.I)
_CONTRACT_RE = re.compile(r"task_contract\.json")


def build_launch_cmd(prompt, parent_cwd, session_id, add_dir):
    claude = shutil.which("claude") or "claude"
    return [claude, "-p", prompt,
            "--output-format", "json",
            "--setting-sources", "user",        # do NOT auto-load project CLAUDE.md/settings
            "--strict-mcp-config",              # no ambient MCP
            "--add-dir", add_dir,               # grant read into the repo
            "--permission-mode", "bypassPermissions",
            "--allowedTools", "Bash Read Grep Glob Skill",
            "--no-session-persistence", "--session-id", session_id]


def _tool_names(payload):
    out = []
    for u in payload.get("tool_uses", []) or []:
        n = u.get("name") if isinstance(u, dict) else None
        if n:
            out.append(n)
    return out


def _files(payload):
    return list(payload.get("files_written", []) or [])


def evaluate_transcript(payload, require_checkin2=False):
    """Pure verdict engine. PASS iff: a valid task_contract.json was written AND CHECK-IN 1 was
    reached AND no repo survey preceded the route AND no generation happened before CHECK-IN 1
    (and, if require_checkin2, CHECK-IN 2 was reached)."""
    text = payload.get("result") or ""
    files = _files(payload)
    names = _tool_names(payload)
    reached, violations = [], []

    contract_written = any(_CONTRACT_RE.search(f) for f in files)
    if contract_written:
        reached.append("task_contract.json")
    else:
        violations.append("no task_contract.json was emitted (route never produced a contract)")

    if _CHECKIN1_RE.search(text):
        reached.append("CHECKIN1")
    else:
        violations.append("CHECK-IN 1 was never reached")

    # a dev-repo survey (reading DIRECTORY.md/STATUS.md/PLAN-OF-RECORD) is the D3/N1 failure signature
    if _SURVEY_RE.search(text) and not contract_written:
        violations.append("surveyed the repo instead of routing to a task_contract first")

    # generation must never precede CHECK-IN 1
    if _GENERATE_RE.search(text):
        violations.append("attempted generation before the CHECK-IN 1 go-ahead")

    if require_checkin2:
        if _CHECKIN2_RE.search(text):
            reached.append("CHECKIN2")
        else:
            violations.append("CHECK-IN 2 was never reached")

    verdict = "PASS" if not violations else "FAIL"
    return {"generator": "clean_room.py", "verdict": verdict, "reached": reached,
            "violations": violations, "require_checkin2": require_checkin2}


def run_live(prompt, require_checkin2=False, timeout=1800):
    if shutil.which("claude") is None:
        return {"verdict": "FAIL", "reached": [], "violations": ["claude CLI not on PATH"],
                "generator": "clean_room.py"}
    sid = str(uuid.uuid4())
    cmd = build_launch_cmd(prompt, PARENT_CWD, sid, REPO)
    try:
        r = subprocess.run(cmd, cwd=PARENT_CWD, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"verdict": "FAIL", "reached": [], "violations": [f"claude -p TIMEOUT {timeout}s"],
                "generator": "clean_room.py"}
    try:
        payload = json.loads(r.stdout)
    except json.JSONDecodeError:
        payload = {"result": r.stdout, "tool_uses": [], "files_written": []}
    v = evaluate_transcript(payload, require_checkin2=require_checkin2)
    v["session_id"] = sid
    v["returncode"] = r.returncode
    return v


def _selftest():
    fails = []
    good = {"result": "CHECK-IN 1 with the task_contract and the survey.",
            "tool_uses": [{"name": "Skill"}], "files_written": ["inputs/task_contract.json"]}
    bad = {"result": "Let me first survey framework/STATUS.md.", "tool_uses": [{"name": "Read"}],
           "files_written": []}
    for label, payload, want in (("good->PASS", good, "PASS"), ("survey->FAIL", bad, "FAIL")):
        got = evaluate_transcript(payload)["verdict"]
        ok = got == want
        print(f"[selftest] {label}: {got}  {'ok' if ok else 'FAIL'}")
        if not ok:
            fails.append(label)
    cmd = build_launch_cmd("x", PARENT_CWD, "sid", REPO)
    ok = "-p" in cmd and "--setting-sources" in cmd and "--strict-mcp-config" in cmd
    print(f"[selftest] launch cmd un-hinted+headless: {ok}  {'ok' if ok else 'FAIL'}")
    if not ok:
        fails.append("launch cmd")
    if fails:
        for f in fails:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("clean_room selftest: PASS (2 payloads + launch cmd)")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--replay", help="a captured claude --output-format json payload to score")
    ap.add_argument("--checkin", choices=("1", "2"), default="1")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    req2 = args.checkin == "2"
    if args.replay:
        if not os.path.isfile(args.replay):
            print(f"clean_room: no such payload: {args.replay}", file=sys.stderr)
            return 2
        v = evaluate_transcript(json.loads(open(args.replay).read()), require_checkin2=req2)
    elif args.live:
        v = run_live(DRY_PROMPT, require_checkin2=req2)
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(v, f, indent=2)
    else:
        print(__doc__, file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(v, indent=2))
    else:
        print(f"clean_room: verdict={v['verdict']} reached={v['reached']} "
              f"violations={v['violations']}")
    return 0 if v["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
