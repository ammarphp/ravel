#!/usr/bin/env python3
"""G5 phantom-background: the last message claims a job is running but no live bg exists ->
Stop 'phantom' branch blocks (exit 2 + PHANTOM)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_phantom"); os.makedirs(rd)
        # a claimed launch with NO live process / no readable logfile -> liveness probe returns false
        L.write_run_state(rd, compute_launched=[{"cmd": "run-scan", "bg_kind": "harness",
                          "bg_id": "deadbeef", "supervised": True, "logfile": "logs/none.log",
                          "done_condition": "SCAN-DONE", "next_action": "assemble",
                          "utc": "2026-07-09T00:00:00Z"}])
        cp = L.drive_stop(rd, "phantom",
                          last_message="The scan is now running in the background.")
        L.assert_block(cp, L.STOP_TOKENS["phantom"])

if __name__ == "__main__":
    sys.exit(run())
