#!/usr/bin/env python3
"""G27 DETACH-DRIVE (N6): a detached long job whose compute_launched entry lacks
logfile/done_condition/next_action -> Stop 'detach' branch refuses turn-end (exit 2 + DETACH)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_detach"); os.makedirs(rd)
        # bg_kind=detached with NONE of the required durable fields (per SHARED-CONVENTIONS §C N6)
        L.write_run_state(rd, compute_launched=[{"cmd": "nohup run-scan &", "bg_kind": "detached",
                          "bg_id": "12345", "utc": "2026-07-09T00:00:00Z"}])
        cp = L.drive_stop(rd, "detach", last_message="ok")
        L.assert_block(cp, L.STOP_TOKENS["detach"])

if __name__ == "__main__":
    sys.exit(run())
