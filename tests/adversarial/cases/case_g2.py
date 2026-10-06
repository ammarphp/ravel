#!/usr/bin/env python3
"""G2 skill observable+covered: a step-advancing turn whose run_state shows the step's required
skill was never invoked -> Stop 'skill-coverage' branch blocks (exit 2 + SKILL-COVERAGE).

NOTE (as-built alignment): branch_skill_coverage keys the run-scan requirement on the STAGE_ORDER
stage that workflow_state.py writes into current_step -- 'scan' is a task_mode, so its run-scan
obligation is driven off task_mode=='scan' at the 'statistics' stage (the step-8 outer loop). The
brief's placeholder current_step='08-scan' matches no branch key; 'statistics' is the as-built one."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_skill"); os.makedirs(rd)
        # at the scan step but run-scan never invoked (skills_invoked empty)
        L.write_run_state(rd, current_step="statistics", task_mode="scan", skills_invoked=[])
        cp = L.drive_stop(rd, "skill-coverage", last_message="step done")
        L.assert_block(cp, L.STOP_TOKENS["skill-coverage"])

if __name__ == "__main__":
    sys.exit(run())
