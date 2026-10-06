#!/usr/bin/env python3
"""G11 INTEGRITY waypoint (D5): a CHECK-IN-2 delivery turn whose primary figure target has no
composed side_by_side makes validate_run_state FAIL, so the Stop 'd18' umbrella blocks the turn
(exit 2 + D18). Only figure_target's composed output would satisfy it."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L
import validate_run_state as vrs

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_waypoint")
        L.write_contract(rd, task_mode="reproduce", stat_mode="best-sr-counting",
                         compute_plan="smoke", detector_mode="simpleanalysis-delphes-native")
        L.write_json(rd, "inputs/resource_census.json", vrs._resource_census_doc())
        L.write_json(rd, "inputs/trap_sweep.json", vrs._trap_sweep_doc())
        # a hand-rolled plot instead of the contracted compose: primary declared, side_by_side null
        L.write_json(rd, "inputs/figure_target.json", {"schema_version": 1, "targets": [
            {"figure_id": "Figure 3", "role": "primary", "primary": True,
             "declared_at_checkin": True, "counterpart": None, "side_by_side": None}]})
        L.write_json(rd, "result.json", {"schema_version": 1})
        L.write_json(rd, "figures.json", {"schema_version": 1, "n_figures": 0, "figures": []})
        cp = L.drive_stop(rd, "d18",
                          last_message="Here is CHECK-IN 2 (the waypoint) for your approval.")
        L.assert_block(cp, L.STOP_TOKENS["d18"])

if __name__ == "__main__":
    sys.exit(run())
