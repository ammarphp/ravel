#!/usr/bin/env python3
"""G1 route forced: a physics prompt to the UserPromptSubmit router injects the INITIATE reminder +
names physicist-intake (the deterministic proxy for 'route forced before generation')."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as td:
        stdin = {"hook_event_name": "UserPromptSubmit", "session_id": "spine-sim", "cwd": td,
                 "prompt": "Initiate: reinterpret ATLAS SUSY-2018-16 for a 200/150 slepton point."}
        cp = L.drive_hook(L.HOOKS["router"], stdin)
        blob = ((cp.stdout or "") + (cp.stderr or "")).lower()
        L.gate_fired("physicist-intake" in blob and ("initiate" in blob or "routing" in blob),
                     f"router did not inject the route reminder; rc={cp.returncode} out={blob[:200]!r}")

if __name__ == "__main__":
    sys.exit(run())
