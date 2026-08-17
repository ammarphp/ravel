#!/usr/bin/env python3
"""G17 DEVIATIONS-at-change (D15): an Edit to a CHECK-IN-1-baselined inputs/ file with no DEVIATIONS
row -> the edit-time PostToolUse deviations guard blocks (exit 2). edit_guard keys on the
BASELINED_INPUTS constant (task_contract.json / resource_census.json / trap_sweep.json / ...) resolved
from the edited path + the rundir's DEVIATIONS.md -- param_card.dat is NOT baselined, so it would be
allowed. Edit the baselined inputs/task_contract.json (mirror p3
test_edit_guard_blocks_baselined_edit_without_deviation)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_devguard")
        # write_contract creates inputs/task_contract.json -- a BASELINED input. NO DEVIATIONS.md.
        L.write_contract(rd, task_mode="reproduce", stat_mode="best-sr-counting",
                         compute_plan="smoke", detector_mode="simpleanalysis-delphes-native")
        edited = os.path.join(rd, "inputs", "task_contract.json")
        stdin = {"hook_event_name": "PostToolUse", "tool_name": "Edit", "cwd": rd,
                 "tool_input": {"file_path": edited}}
        cp = L.drive_hook(L.HOOKS["deviations"], stdin)
        L.gate_fired(cp.returncode == 2, f"deviations guard exit {cp.returncode}, expected 2")

if __name__ == "__main__":
    sys.exit(run())
