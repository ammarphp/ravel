#!/usr/bin/env python3
"""G21 SELF-DRIVE (D17): the recorded clean-room verdict (from clean_room.py --live via
`make green-self-drive`) must be PASS -- a fresh un-hinted agent reached CHECK-IN 1/2 nudge-free.

This case ATTESTS the live artifact framework/spine_sim/self_drive/last_verdict.json. When that
artifact is absent (the default on a host where headless `claude -p` is not authenticated), the engine
SKIPs G21 unless --with-self-drive is passed -- so the board stays green WITHOUT ever faking a PASS.
When the artifact IS present, this case asserts its verdict == PASS."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    L.attest("framework/spine_sim/self_drive/last_verdict.json", expect="PASS")

if __name__ == "__main__":
    sys.exit(run())
