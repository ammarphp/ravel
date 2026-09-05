#!/usr/bin/env python3
"""scripts/green_board.py -- the ONE aggregate 'make green' board for the workflow-adherence spine.

Runs, from the repo root, the whole green stack in one exit code:
  spine_sim           python3 tests/adversarial/run_suite.py --require-all   (every G0-G27 fires)
  check_agent_surface python3 scripts/run.py ravel.validation.check_agent_surface    (routing/docs coherent)
  validate_run_state  python3 scripts/run.py ravel.validation.validate_run_state --selftest  (the 19 lifecycle/invariant cases)
  audit               python3 scripts/audit.py                                   (readiness report, informational)

These are the REAL as-built L6 checks for the workflow-adherence spine. The legacy CR-030..043 board
`scripts/verify_fixes.py` is intentionally NOT a rung here: its CR-039 line hard-validates the frozen
trial-run `trial-runs/sleptonscan_fig3_SCAN`, which predates and therefore FAILs the invariants this
spine ADDED (ladder-order/certify-before-limit/trap-obligations, D11/D12/D13) — a known consequence, not
a spine regression. `verify_fixes.py` still runs standalone for the audit-and-fix batch.
The DEFAULT board SKIPs the self-drive gate (G21) -- it depends on the live clean_room artifact, which
a plain `make green` does not produce. With --with-self-drive it FIRST runs clean_room.py --live
(recording the verdict), then runs spine_sim with --with-self-drive so the G21 case actually asserts a
fresh PASS.

A rung marked informational never sinks the board (audit is a report, not a gate). Exit 0 iff every
non-informational rung passed.

Usage:
  green_board.py                 # human board, exit 0/1
  green_board.py --json          # machine board on stdout
  green_board.py --with-self-drive
  green_board.py --rungs-json F  # override the rung list (test hook)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMEOUT_S = 1800

# (name, command, informational)
RUNGS = [
    ("spine_sim", "python3 tests/adversarial/run_suite.py --require-all", False),
    ("check_agent_surface", "python3 scripts/run.py ravel.validation.check_agent_surface", False),
    ("validate_run_state", "python3 scripts/run.py ravel.validation.validate_run_state --selftest", False),
    ("audit", "python3 scripts/audit.py", True),
]
SELF_DRIVE_RUNG = ("self_drive", "python3 tests/adversarial/clean_room.py --live --checkin 2", False)


def run_rung(name, cmd, informational, timeout=DEFAULT_TIMEOUT_S):
    try:
        r = subprocess.run(cmd, shell=True, cwd=REPO_ROOT, capture_output=True, text=True,
                           timeout=timeout)
        rc = r.returncode
        tail = (r.stderr or r.stdout)[-2000:] if rc != 0 else ""
    except subprocess.TimeoutExpired:
        rc, tail = None, f"TIMEOUT after {timeout}s"
    passed = (rc == 0) or informational
    return {"name": name, "cmd": cmd, "informational": informational,
            "status": "PASS" if passed else "FAIL", "returncode": rc, "tail": tail}


def build_board(rungs):
    return [run_rung(*r) for r in rungs]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--with-self-drive", action="store_true")
    ap.add_argument("--rungs-json", default=None, help="override rungs (test hook): [[name,cmd,info],...]")
    args = ap.parse_args(argv)

    if args.rungs_json:
        rungs = [tuple(x) for x in json.loads(Path(args.rungs_json).read_text())]
    elif args.with_self_drive:
        # 1) produce the live verdict first, 2) run spine_sim WITH --with-self-drive so the self-drive
        #    gate (G21) actually runs against that fresh verdict instead of SKIPping.
        rungs = [SELF_DRIVE_RUNG] + [
            ("spine_sim", "python3 tests/adversarial/run_suite.py --require-all --with-self-drive",
             False) if name == "spine_sim" else (name, cmd, info)
            for (name, cmd, info) in RUNGS]
    else:
        rungs = list(RUNGS)      # default: spine_sim SKIPs G21 (no live artifact) -> board stays green

    results = build_board(rungs)
    all_pass = all(r["status"] == "PASS" for r in results)
    n_pass = sum(1 for r in results if r["status"] == "PASS")
    n_fail = sum(1 for r in results if r["status"] != "PASS")

    if args.json:
        print(json.dumps({"results": results, "n_pass": n_pass, "n_fail": n_fail,
                          "all_pass": all_pass}, indent=2))
    else:
        for r in results:
            tag = "  (informational)" if r["informational"] else ""
            print(f"{r['name']:20s} | {r['status']}{tag}")
        print(f"\ngreen_board: {n_pass} PASS / {n_fail} FAIL of {len(results)} rung(s)")
        for r in results:
            if r["status"] != "PASS":
                print(f"  FAIL {r['name']} (exit {r['returncode']}): {(r['tail'] or '').strip()[-400:]}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
