#!/usr/bin/env python3
"""G0a hooks fire (SPK-1): re-verify the RECORDED SPK-1 spike state. Per the recorded artifact this
harness could not auth `claude -p` for a full-turn probe, so SPK-1 is recorded verdict=unproven /
decision=fallback-primary -- the HONEST recorded state. `spike_probe.py --spike SPK-1 --check` on that
artifact re-derives the same (consistent) not-PASS verdict and exits 1 (a consistent recorded-not-PASS,
NOT a tamper/exit-3). The gate FIRES when the recorder faithfully re-reports that state (exit 1); the
recorder-is-not-vacuous property is separately proven by `spike_probe.py --selftest`'s seeded-FAIL
cases. The recorded evidence is loaded from tests/fixtures/hook-probes/."""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    probe = os.path.join(L.REPO, "tests", "adversarial", "spike_probe.py")
    art = os.path.join(L.REPO, "tests", "fixtures", "hook-probes", "spk-1.json")
    for p in (probe, art):
        if not os.path.isfile(p):
            raise L.CaseSetupError(f"spike artifact/tool missing (Phase 0 not landed?): {p}")
    p = subprocess.run([sys.executable, probe, "--spike", "SPK-1", "--check", art],
                       cwd=L.REPO, capture_output=True, text=True, timeout=120)
    L.gate_fired(p.returncode == 1,
                 f"spike_probe --spike SPK-1 --check exit {p.returncode}, expected 1 "
                 f"(consistent recorded-not-PASS); out={((p.stdout or '')+(p.stderr or ''))[:200]!r}")

if __name__ == "__main__":
    sys.exit(run())
