#!/usr/bin/env python3
"""G12 VALIDATE (D10): a scan whose varied-parameter validations are PENDING must FAIL inv
param-validated-before-scan."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_validate")
        L.write_contract(rd, task_mode="scan", stat_mode="best-sr-counting", compute_plan="scan",
                         detector_mode="simpleanalysis-delphes-native")
        L.write_json(rd, "scan.json", {"schema_version": 1, "n_planned": 1, "n_done": 1,
                     "n_missing": 0, "points": [{"tag": "p1"}], "missing_tags": []})
        # a validations manifest whose varied-param obligation is still PENDING. The invariant reads
        # doc["params"] (role=="varied"/trap), NOT "obligations" -- so the PENDING-not-PASS path fires
        # (mirror p3 _fixture_scan_param_pending).
        L.write_json(rd, "inputs/validations.json", {"schema_version": 1,
                     "generated_by": "validate_parameters.py", "input_fingerprint": "deadbeef",
                     "params": [{"name": "m_slepton", "kind": "param_validation", "role": "varied",
                                 "trap": None, "check": "mass in grid", "status": "PENDING"}]})
        res, _ = L.run_validate(rd)
        st = L.invariant_status(res, "param-validated-before-scan")
        L.gate_fired(st == "FAIL", f"inv param-validated-before-scan={st!r}, expected FAIL")

if __name__ == "__main__":
    sys.exit(run())
