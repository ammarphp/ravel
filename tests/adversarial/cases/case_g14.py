#!/usr/bin/env python3
"""G14 CERTIFY (D12): a limit-shipping run with NO non-FAIL cert must FAIL inv certify-before-limit."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_certify")
        L.write_contract(rd, task_mode="scan", stat_mode="best-sr-counting", compute_plan="scan",
                         detector_mode="simpleanalysis-delphes-native")
        # a limit ships (scan.json present with exclusion data) but NO acc x eff cert exists
        L.write_json(rd, "scan.json", {"schema_version": 1, "n_planned": 1, "n_done": 1,
                     "n_missing": 0, "missing_tags": [],
                     "points": [{"tag": "p1", "mu95_obs": 0.8, "mu95_exp": 0.9, "excluded_obs": True}]})
        res, _ = L.run_validate(rd)
        st = L.invariant_status(res, "certify-before-limit")
        L.gate_fired(st == "FAIL", f"inv certify-before-limit={st!r}, expected FAIL")

if __name__ == "__main__":
    sys.exit(run())
