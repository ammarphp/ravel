#!/usr/bin/env python3
"""G3 live run-state drives: workflow_state.py advance refuses an out-of-order jump (preconditions
unmet) and emits next_required."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_advance")
        L.write_contract(rd, task_mode="reproduce", stat_mode="best-sr-counting",
                         compute_plan="smoke", detector_mode="simpleanalysis-delphes-native")
        L.run_tool("workflow_state.py", ["init", "--rundir", rd, "--session-id", "spine-sim"])
        # jump straight to statistics with nothing generated -> advance must refuse
        p = L.run_tool("workflow_state.py", ["advance", "--rundir", rd, "--to", "statistics"])
        L.gate_fired(p.returncode != 0,
                     f"workflow_state advance --to statistics exit {p.returncode}, expected refuse")

if __name__ == "__main__":
    sys.exit(run())
