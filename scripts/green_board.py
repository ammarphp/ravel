#!/usr/bin/env python3
"""scripts/green_board.py -- the ONE aggregate 'make green' board for the workflow-adherence gates.

Runs, from the repo root, the whole green stack in one exit code:
  adversarial         python3 tests/adversarial/run_suite.py --require-all   (every board gate fires)
  check_agent_surface python3 scripts/run.py ravel.validation.check_agent_surface    (routing/docs coherent)
  validate_run_state  python3 scripts/run.py ravel.validation.validate_run_state --selftest  (the 19 lifecycle/invariant cases)
  audit               python3 scripts/audit.py                                   (readiness report, informational)

These are the gating checks of the workflow-adherence gates. The historical slepton scan record
(`evidence/scans/slepton-bino-figure-3`) is not a rung: it predates, and therefore FAILs, the
invariants these gates added (ladder-order/certify-before-limit/trap-obligations, D11/D12/D13) — a
known consequence, not a regression.
`make green` never launches an agent.

A rung marked informational never sinks the board (audit is a report, not a gate). Exit 0 iff every
non-informational rung passed.

Usage:
  green_board.py                 # human board, exit 0/1
  green_board.py --json          # machine board on stdout
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
    ("adversarial", "python3 tests/adversarial/run_suite.py --require-all", False),
    ("check_agent_surface", "python3 scripts/run.py ravel.validation.check_agent_surface", False),
    ("validate_run_state", "python3 scripts/run.py ravel.validation.validate_run_state --selftest", False),
    ("audit", "python3 scripts/audit.py", True),
]


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
    ap.add_argument("--rungs-json", default=None, help="override rungs (test hook): [[name,cmd,info],...]")
    args = ap.parse_args(argv)

    if args.rungs_json:
        rungs = [tuple(x) for x in json.loads(Path(args.rungs_json).read_text())]
    else:
        rungs = list(RUNGS)

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
