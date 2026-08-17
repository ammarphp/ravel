#!/usr/bin/env python3
"""framework/spine_sim/run_spine_sim.py -- the per-gate verification board (L6).

For every gate in the workflow-adherence spine (G0a..G27) a sibling `cases/case_<GATE>.py`
script SEEDS a throwaway fixture that trips the trigger and asserts the matching gate FIRES.
This engine (modeled on framework/verify_fixes.py) discovers those case scripts, runs each as a
subprocess FROM THE REPO ROOT, and prints one board:

    G13 | case_G13.py | PASS

Case exit convention: 0 = gate FIRED (PASS) * 1 = gate did NOT fire (FAIL/regression) *
2 = fixture/setup error (ERROR, e.g. the enforcing tool is not yet on disk).

Usage:
  run_spine_sim.py                 # human board over cases/, exit 0/1
  run_spine_sim.py --json          # machine board on stdout, same exit code
  run_spine_sim.py --only G13,G16  # run just these gates
  run_spine_sim.py --require-all   # ALSO fail if any EXPECTED gate has no case file
  run_spine_sim.py --with-self-drive  # actually run the self-drive gate(s) (needs clean_room --live)
  run_spine_sim.py --cases DIR     # override the cases dir (test hook)
  run_spine_sim.py --selftest      # fabricated PASS/FAIL cases prove the aggregator

A SELF-DRIVE gate (G21) attests the live clean-room artifact (clean_room.py --live). When that
artifact is absent AND --with-self-drive was not passed, it is reported SKIP (never sinks the board)
so the default `make green` is green; `make green-self-drive` produces the artifact and asserts it.

Exit codes: 0 all PASS/SKIP (and, under --require-all, all 30 present) * 1 any FAIL/ERROR/MISSING *
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

# Gates whose case ATTESTS a live clean-room artifact (clean_room.py --live). They are SKIP (never a
# FAIL/ERROR) when that artifact is absent AND --with-self-drive was not passed -- so the default
# `make green` stays green; `make green-self-drive` writes the artifact and forces them to run.
SELF_DRIVE_GATES = frozenset({"G21"})
SELF_DRIVE_ARTIFACT = Path(__file__).resolve().parent / "self_drive" / "last_verdict.json"

EXPECTED_GATES = (
    "G0a", "G0b", "G0c", "G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10",
    "G11", "G12", "G13", "G14", "G15", "G16", "G17", "G18", "G19", "G20", "G21", "G22",
    "G23", "G24", "G25", "G26", "G27",
)
_CASE_RE = re.compile(r"^case_(G[0-9]+[a-z]?)\.py$")


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
            out[m.group(1)] = p
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


def _self_drive_skip(gate, with_self_drive) -> bool:
    """A self-drive-dependent gate is SKIP'd ONLY when its live artifact is absent AND self-drive was
    not requested. When the artifact IS present (e.g. after clean_room.py --live) or --with-self-drive
    forces it, the case runs and must PASS -- so the gate is never silently weakened."""
    return (gate in SELF_DRIVE_GATES and not with_self_drive
            and not SELF_DRIVE_ARTIFACT.is_file())


def build_board(cases_dir: Path, only=None, require_all=False, with_self_drive=False) -> list:
    found = discover_cases(cases_dir)
    gates = [g for g in EXPECTED_GATES if g in found]
    extra = [g for g in found if g not in EXPECTED_GATES]
    gates += sorted(extra, key=_gate_key)
    if only:
        gates = [g for g in gates if g in only]
    results = []
    for g in sorted(gates, key=_gate_key):
        if _self_drive_skip(g, with_self_drive):
            results.append({"gate": g, "case": found[g].name, "status": "SKIP", "returncode": None,
                            "tail": "self-drive artifact absent; run `make green-self-drive` "
                                    "(clean_room.py --live) to assert this gate"})
        else:
            results.append(run_case(g, found[g]))
    if require_all and not only:
        for g in EXPECTED_GATES:
            if g not in found:
                results.append({"gate": g, "case": f"case_{g}.py", "status": "MISSING",
                                "returncode": None, "tail": "no case script for this gate"})
    results.sort(key=lambda r: _gate_key(r["gate"]))
    return results


def _print_board(results):
    for r in results:
        print(f"{r['gate']} | {r['case']} | {r['status']}")
    n_pass = sum(1 for r in results if r["status"] == "PASS")
    n_skip = sum(1 for r in results if r["status"] == "SKIP")
    n_fail = sum(1 for r in results if r["status"] not in ("PASS", "SKIP"))
    skip_note = f" / {n_skip} SKIP" if n_skip else ""
    print(f"\nspine_sim: {n_pass} PASS / {n_fail} FAIL{skip_note} of {len(results)} case(s)")
    for r in results:
        if r["status"] not in ("PASS", "SKIP"):
            print(f"  {r['status']} {r['gate']} ({r['case']}, exit {r['returncode']}):"
                  f" {(r['tail'] or '').strip()[-300:]}")


def _selftest():
    with tempfile.TemporaryDirectory(prefix="spine_sim_selftest_") as td:
        cases = Path(td) / "cases"; cases.mkdir()
        (cases / "case_G0a.py").write_text("import sys; sys.exit(0)\n")
        (cases / "case_G1.py").write_text("import sys; sys.exit(1)\n")
        (cases / "case_G2.py").write_text("import sys; sys.exit(2)\n")
        res = build_board(cases)
        by = {r["gate"]: r["status"] for r in res}
        ok = by == {"G0a": "PASS", "G1": "FAIL", "G2": "ERROR"}
        print(f"[selftest] aggregate PASS/FAIL/ERROR: {by}  {'ok' if ok else 'FAIL'}")
        req = build_board(cases, require_all=True)
        miss = any(r["status"] == "MISSING" for r in req)
        print(f"[selftest] --require-all flags missing gates: {miss}  {'ok' if miss else 'FAIL'}")
    if not (ok and miss):
        print("SELFTEST FAIL: spine_sim aggregator", file=sys.stderr)
        return 1
    print("run_spine_sim selftest: PASS (3 fabricated cases judged correctly)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--cases", default=str(DEFAULT_CASES))
    ap.add_argument("--only", default=None, help="comma list of gate ids")
    ap.add_argument("--require-all", action="store_true")
    ap.add_argument("--with-self-drive", action="store_true",
                    help="run the self-drive gate(s) instead of SKIPping them (needs the live artifact)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    cases_dir = Path(args.cases)
    if not cases_dir.is_dir():
        print(f"run_spine_sim: cases dir not found: {cases_dir}", file=sys.stderr)
        return 2
    only = set(s.strip() for s in args.only.split(",") if s.strip()) if args.only else None
    results = build_board(cases_dir, only=only, require_all=args.require_all,
                          with_self_drive=args.with_self_drive)
    if not results:
        print(f"run_spine_sim: no case scripts in {cases_dir}", file=sys.stderr)
        return 2
    # SKIP (a self-drive gate whose live artifact is absent) never sinks the board
    all_pass = all(r["status"] in ("PASS", "SKIP") for r in results)
    if args.json:
        print(json.dumps({"cases_dir": str(cases_dir), "results": results,
                          "n_pass": sum(1 for r in results if r["status"] == "PASS"),
                          "n_skip": sum(1 for r in results if r["status"] == "SKIP"),
                          "n_fail": sum(1 for r in results if r["status"] not in ("PASS", "SKIP")),
                          "all_pass": all_pass}, indent=2))
    else:
        _print_board(results)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
