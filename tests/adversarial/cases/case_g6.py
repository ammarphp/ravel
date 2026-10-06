#!/usr/bin/env python3
"""G6 CATCH (D6): (a) stage_supervisor's own selftest seeds a 100%-CPU hang -> kill -> failure.json
(exit 0); (b) with an unhandled *.failure.json under the rundir, the Stop 'catch' branch blocks
(exit 2 + CATCH). Two halves: the watchdog kills, the umbrella catches the residue."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    # (a) the wired watchdog selftest is the seeded hang->kill->failure.json trigger
    sup = L.run_tool("stage_supervisor.py", ["--selftest"], timeout=120)
    L.gate_fired(sup.returncode == 0,
                 f"stage_supervisor --selftest exit {sup.returncode}: {(sup.stderr or '')[:200]}")
    # (b) an open failure record must make the Stop catch branch refuse turn-end
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_catch"); os.makedirs(rd)
        L.write_json(rd, "logs/gen.failure.json", {"schema_version": 1, "stage": "generation",
                     "error": "seeded hang killed by supervisor", "resolved": False})
        L.write_run_state(rd, open_failure_records=["logs/gen.failure.json"])
        cp = L.drive_stop(rd, "catch", last_message="continuing")
        L.assert_block(cp, L.STOP_TOKENS["catch"])

if __name__ == "__main__":
    sys.exit(run())
