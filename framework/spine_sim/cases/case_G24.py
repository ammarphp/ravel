#!/usr/bin/env python3
"""G24 ARMED-COMMAND PREFLIGHT (N3/D-4): a turn-end left with an armed watcher whose preflight
artifact is missing (never passed preflight) -> the NON-invariant armed-watcher Stop branch refuses.
Per RECONCILE D-4, drive stop_dispatch.py --branch armed-watcher (which shells
preflight_watcher.py --assert-all) and assert exit 2 + the G24-ARMED-WATCHER token, not the bare
--arm predicate (mirror p4b test_armed_watcher_stop_branch)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_armed")
        # an armed watcher whose preflight artifact does NOT exist on disk -> --assert-all fails
        L.write_run_state(rd, session_id="T",
                          armed_watchers=[{"name": "ghost", "preflight": "logs/ghost.preflight.json"}])
        cp = L.drive_stop(rd, "armed-watcher", last_message="ok")
        L.assert_block(cp, L.STOP_TOKENS["armed-watcher"])

if __name__ == "__main__":
    sys.exit(run())
