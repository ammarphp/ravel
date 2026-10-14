#!/usr/bin/env python3
"""G0b completion re-invoke (SPK-2): re-verify the recorded harness bg-completion re-invocation. SPK-2
is recorded verdict=PASS (an unguessable token round-tripped through the harness run_in_background
completion channel), so `_probe_check.py --spike SPK-2 --check` re-derives PASS and exits 0. Drive
_probe_check.py against its recorded tests/fixtures/hook-probes/ record."""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    probe = os.path.join(L.REPO, "tests", "adversarial", "_probe_check.py")
    art = os.path.join(L.REPO, "tests", "fixtures", "hook-probes", "spk-2.json")
    for p in (probe, art):
        if not os.path.isfile(p):
            raise L.CaseSetupError(f"recorded hook probe or its checker missing: {p}")
    p = subprocess.run([sys.executable, probe, "--spike", "SPK-2", "--check", art],
                       cwd=L.REPO, capture_output=True, text=True, timeout=120)
    L.gate_fired(p.returncode == 0,
                 f"_probe_check --spike SPK-2 --check exit {p.returncode}, expected 0 (recorded PASS); "
                 f"out={((p.stdout or '')+(p.stderr or ''))[:200]!r}")

if __name__ == "__main__":
    sys.exit(run())
