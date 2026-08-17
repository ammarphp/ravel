#!/usr/bin/env python3
"""G10 INTEGRITY primary (D9): a declared PRIMARY figure target with a null counterpart/side_by_side
must hard-FAIL inv figure-contract-fulfilled (primary-aware, all modes)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L
import validate_run_state as vrs

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_primary")
        # scan mode: figure_contract is level O here -- the primary-aware D9 gate must STILL fire
        L.write_contract(rd, task_mode="scan", stat_mode="best-sr-counting", compute_plan="scan",
                         detector_mode="simpleanalysis-delphes-native")
        L.write_json(rd, "inputs/resource_census.json", vrs._resource_census_doc())
        L.write_json(rd, "inputs/trap_sweep.json", vrs._trap_sweep_doc())
        # PRIMARY target echoed at check-in: generated_counterpart present, side_by_side NULL -> FAIL.
        # The invariant reads primary.get("generated_counterpart")/("side_by_side") (mirror p3
        # _fixture_primary_unfulfilled), NOT a "counterpart" key.
        L.write_json(rd, "inputs/figure_target.json", {"schema_version": 1, "targets": [
            {"primary": True, "role": "summary", "figure_id": "Figure 3", "declared_at_checkin": True,
             "generated_counterpart": {"path": "plots/fig3.png", "step": "08-scan"},
             "side_by_side": None, "verified_by_physicist": None}]})
        # a generation artifact so facts["generation_hits"] is non-empty -- else the primary-aware
        # FAIL block is SKIPPED and the invariant never inspects the target
        L.write_json(rd, "outputs/sr_yields.json",
                     [{"name": "SR", "n": 1, "b": 1.0, "db": 0.2, "s": 0.5}])
        res, _ = L.run_validate(rd)
        st = L.invariant_status(res, "figure-contract-fulfilled")
        L.gate_fired(st == "FAIL", f"inv figure-contract-fulfilled={st!r}, expected FAIL")

if __name__ == "__main__":
    sys.exit(run())
