#!/usr/bin/env python3
"""G4 DRIVE (D4): a turn that narrates a next step, launches no compute, has no live bg, and is not
at a human gate -> Stop dispatcher 'drive' branch blocks (exit 2 + DRIVE)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_drive"); os.makedirs(rd)
        L.write_run_state(rd, compute_launched=[], armed_watchers=[],
                          next_required={"kind": "command", "what": "run-point",
                                         "why": "generation stage pending"})
        cp = L.drive_stop(rd, "drive", last_message="Next I'll generate the events.")
        L.assert_block(cp, L.STOP_TOKENS["drive"])

if __name__ == "__main__":
    sys.exit(run())
