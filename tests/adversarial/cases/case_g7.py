#!/usr/bin/env python3
"""G7 30-min reporter: the progress reporter emits one progress line for a running job (its wired
selftest is the seeded 'long job running' trigger)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    p = L.run_tool("progress_reporter.py", ["--selftest"], timeout=60)
    L.gate_fired(p.returncode == 0 and (p.stdout or "").strip(),
                 f"progress_reporter --selftest exit {p.returncode}: {(p.stderr or '')[:200]}")

if __name__ == "__main__":
    sys.exit(run())
