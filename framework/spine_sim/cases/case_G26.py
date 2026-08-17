#!/usr/bin/env python3
"""G26 OPEN-DEFECT (N5/D-4): a DELIVERY turn-end with an unresolved open_defect_note (e.g.
read_yoda.py) -> the NON-invariant open-defect Stop branch refuses. Per RECONCILE D-4, drive
stop_dispatch.py --branch open-defect (which shells verify_pack.py, gated on ctx['is_delivery']) and
assert exit 2 + the G26-OPEN-DEFECT token -- so the last message must read as a delivery (mirror p4b
test_open_defect_stop_branch)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_defect")
        L.write_run_state(rd, session_id="T", open_defect_notes=[{"helper": "read_yoda.py",
                          "note": "A x eff reads 956% -- clearly wrong", "status": "open"}])
        cp = L.drive_stop(rd, "open-defect", last_message="Here is the results deck.")
        L.assert_block(cp, L.STOP_TOKENS["open-defect"])

if __name__ == "__main__":
    sys.exit(run())
