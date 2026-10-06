#!/usr/bin/env python3
"""tests/adversarial/run_suite.py -- the per-gate verification board.

For every workflow-adherence gate in EXPECTED_GATES a sibling `cases/case_<GATE>.py`
script SEEDS a throwaway fixture that trips the trigger and asserts the matching gate FIRES.
This engine discovers those case scripts, runs each as a
subprocess FROM THE REPO ROOT, and prints one board:

    G13 | case_g13.py | PASS

Case exit convention: 0 = gate FIRED (PASS) * 1 = gate did NOT fire (FAIL/regression) *
2 = fixture/setup error (ERROR, e.g. the enforcing tool is not yet on disk).

Usage:
  run_suite.py                 # human board over cases/, exit 0/1
  run_suite.py --json          # machine board on stdout, same exit code
  run_suite.py --only G13,G16  # run just these gates
  run_suite.py --require-all   # ALSO fail if any EXPECTED gate has no case file
  run_suite.py --cases DIR     # override the cases dir (test hook)
  run_suite.py --selftest      # fabricated PASS/FAIL cases prove the aggregator

Exit codes: 0 all PASS (and, under --require-all, all 29 present) * 1 any FAIL/ERROR/MISSING *
2 usage / cases dir missing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = Path(__file__).resolve().parent / "cases"
DEFAULT_TIMEOUT_S = 180

EXPECTED_GATES = (
    "G0a", "G0b", "G0c", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10",
    "G11", "G12", "G13", "G14", "G15", "G16", "G17", "G18", "G19", "G20", "G22",
    "G23", "G24", "G25", "G26", "G27",
)
_CASE_RE = re.compile(r"^case_g([0-9]+[a-z]?)\.py$")


def _gate_key(gate):
    m = re.match(r"^G(\d+)([a-z]?)$", gate)
    return (int(m.group(1)), m.group(2)) if m else (999, gate)


def discover_cases(cases_dir: Path) -> dict:
    out = {}
    if not cases_dir.is_dir():
        return out
    for p in sorted(cases_dir.iterdir()):
        m = _CASE_RE.match(p.name)
        if m:
            out["G" + m.group(1)] = p
    return out


def run_case(gate: str, path: Path, timeout: int = DEFAULT_TIMEOUT_S) -> dict:
    try:
        r = subprocess.run([sys.executable, str(path)], cwd=REPO_ROOT,
                           capture_output=True, text=True, timeout=timeout)
        rc = r.returncode
        tail = (r.stderr or r.stdout)[-2000:] if rc != 0 else ""
    except subprocess.TimeoutExpired:
        rc, tail = None, f"TIMEOUT after {timeout}s"
    status = {0: "PASS", 1: "FAIL", 2: "ERROR"}.get(rc, "FAIL")
    return {"gate": gate, "case": path.name, "status": status, "returncode": rc, "tail": tail}


def build_board(cases_dir: Path, only=None, require_all=False) -> list:
    found = discover_cases(cases_dir)
    gates = [g for g in EXPECTED_GATES if g in found]
    extra = [g for g in found if g not in EXPECTED_GATES]
    gates += sorted(extra, key=_gate_key)
    if only:
        gates = [g for g in gates if g in only]
    results = []
    for g in sorted(gates, key=_gate_key):
        results.append(run_case(g, found[g]))
    if require_all and not only:
        for g in EXPECTED_GATES:
            if g not in found:
                results.append({"gate": g, "case": f"case_{g.lower()}.py", "status": "MISSING",
                                "returncode": None, "tail": "no case script for this gate"})
    results.sort(key=lambda r: _gate_key(r["gate"]))
    return results


def _print_board(results):
    for r in results:
        print(f"{r['gate']} | {r['case']} | {r['status']}")
    n_pass = sum(1 for r in results if r["status"] == "PASS")
    n_fail = sum(1 for r in results if r["status"] != "PASS")
    print(f"\nadversarial board: {n_pass} PASS / {n_fail} FAIL of {len(results)} case(s)")
    for r in results:
        if r["status"] != "PASS":
            print(f"  {r['status']} {r['gate']} ({r['case']}, exit {r['returncode']}):"
                  f" {(r['tail'] or '').strip()[-300:]}")


def _selftest():
    with tempfile.TemporaryDirectory(prefix="adversarial_selftest_") as td:
        cases = Path(td) / "cases"; cases.mkdir()
        (cases / "case_g0a.py").write_text("import sys; sys.exit(0)\n")
        (cases / "case_g1.py").write_text("import sys; sys.exit(1)\n")
        (cases / "case_g2.py").write_text("import sys; sys.exit(2)\n")
        res = build_board(cases)
        by = {r["gate"]: r["status"] for r in res}
        ok = by == {"G0a": "PASS", "G1": "FAIL", "G2": "ERROR"}
        print(f"[selftest] aggregate PASS/FAIL/ERROR: {by}  {'ok' if ok else 'FAIL'}")
        req = build_board(cases, require_all=True)
        miss = any(r["status"] == "MISSING" for r in req)
        print(f"[selftest] --require-all flags missing gates: {miss}  {'ok' if miss else 'FAIL'}")
    if not (ok and miss):
        print("SELFTEST FAIL: adversarial board aggregator", file=sys.stderr)
        return 1
    print("run_suite selftest: PASS (3 fabricated cases judged correctly)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--cases", default=str(DEFAULT_CASES))
    ap.add_argument("--only", default=None, help="comma list of gate ids")
    ap.add_argument("--require-all", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    cases_dir = Path(args.cases)
    if not cases_dir.is_dir():
        print(f"run_suite: cases dir not found: {cases_dir}", file=sys.stderr)
        return 2
    only = set(s.strip() for s in args.only.split(",") if s.strip()) if args.only else None
    results = build_board(cases_dir, only=only, require_all=args.require_all)
    if not results:
        print(f"run_suite: no case scripts in {cases_dir}", file=sys.stderr)
        return 2
    all_pass = all(r["status"] == "PASS" for r in results)
    if args.json:
        print(json.dumps({"cases_dir": str(cases_dir), "results": results,
                          "n_pass": sum(1 for r in results if r["status"] == "PASS"),
                          "n_fail": sum(1 for r in results if r["status"] != "PASS"),
                          "all_pass": all_pass}, indent=2))
    else:
        _print_board(results)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
