#!/usr/bin/env python3
"""G13 LADDER (D11): a full/scan run with NO smoke-rung PASS artifact must FAIL inv ladder-order."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_ladder")
        L.write_contract(rd, task_mode="scan", stat_mode="best-sr-counting", compute_plan="scan",
                         detector_mode="simpleanalysis-delphes-native")
        L.write_json(rd, "scan.json", {"schema_version": 1, "n_planned": 2, "n_done": 2,
                     "n_missing": 0, "points": [{"tag": "p1"}, {"tag": "p2"}], "missing_tags": []})
        # deliberately NO smoke-rung PASS artifact -> the ladder invariant must FAIL
        res, _ = L.run_validate(rd)
        st = L.invariant_status(res, "ladder-order")
        L.gate_fired(st == "FAIL", f"inv ladder-order={st!r}, expected FAIL")

if __name__ == "__main__":
    sys.exit(run())
