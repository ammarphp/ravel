#!/usr/bin/env python3
"""G0c ScheduleWakeup (SPK-3): re-verify the recorded scheduled-wake re-fire. SPK-3 is recorded
verdict=PASS (a de-facto timed wake on the SPK-2-confirmed run_in_background completion re-invoke fired
within tolerance), so `spike_probe.py --spike SPK-3 --check` re-derives PASS and exits 0. Drive
spike_probe.py against its recorded tests/fixtures/hook-probes/ artifact."""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    probe = os.path.join(L.REPO, "tests", "adversarial", "spike_probe.py")
    art = os.path.join(L.REPO, "tests", "fixtures", "hook-probes", "spk-3.json")
    for p in (probe, art):
        if not os.path.isfile(p):
            raise L.CaseSetupError(f"spike artifact/tool missing (Phase 0 not landed?): {p}")
    p = subprocess.run([sys.executable, probe, "--spike", "SPK-3", "--check", art],
                       cwd=L.REPO, capture_output=True, text=True, timeout=120)
    L.gate_fired(p.returncode == 0,
                 f"spike_probe --spike SPK-3 --check exit {p.returncode}, expected 0 (recorded PASS); "
                 f"out={((p.stdout or '')+(p.stderr or ''))[:200]!r}")

if __name__ == "__main__":
    sys.exit(run())
