#!/usr/bin/env python3
"""G0a hooks fire (SPK-1): re-verify the RECORDED SPK-1 probe state. The recorded probe could not
run a full agent turn, so SPK-1 is recorded verdict=unproven /
decision=fallback-primary -- the HONEST recorded state. `_probe_check.py --spike SPK-1 --check` on that
record re-derives the same (consistent) not-PASS verdict and exits 1 (a consistent recorded-not-PASS,
NOT an edited record/exit-3). The gate FIRES when the checker faithfully re-reports that state (exit 1);
tests/unit/test_probe_check.py separately proves the checker is not vacuous (seeded-FAIL and
edited-record cases). The recorded evidence is loaded from tests/fixtures/hook-probes/."""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    probe = os.path.join(L.REPO, "tests", "adversarial", "_probe_check.py")
    art = os.path.join(L.REPO, "tests", "fixtures", "hook-probes", "spk-1.json")
    for p in (probe, art):
        if not os.path.isfile(p):
            raise L.CaseSetupError(f"recorded hook probe or its checker missing: {p}")
    p = subprocess.run([sys.executable, probe, "--spike", "SPK-1", "--check", art],
                       cwd=L.REPO, capture_output=True, text=True, timeout=120)
    L.gate_fired(p.returncode == 1,
                 f"_probe_check --spike SPK-1 --check exit {p.returncode}, expected 1 "
                 f"(consistent recorded-not-PASS); out={((p.stdout or '')+(p.stderr or ''))[:200]!r}")

if __name__ == "__main__":
    sys.exit(run())
