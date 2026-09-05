#!/usr/bin/env python3
"""G18 CHECK-IN schema: a CHECK-IN 1 artifact missing a required section -> validate_checkin.py FAILs
(exit 1)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as td:
        bad = os.path.join(td, "checkin1.json")
        # a deliberately thin CHECK-IN 1 (no gallery / numbered flags / waypoint / validations manifest)
        with open(bad, "w") as f:
            f.write('{"id": "CHECKIN1", "prompt": "reinterpret X"}')
        p = L.run_tool("validate_checkin.py", [bad])
        L.gate_fired(p.returncode == 1, f"validate_checkin exit {p.returncode}, expected 1")

if __name__ == "__main__":
    sys.exit(run())
