#!/usr/bin/env python3
"""G19 PROVENANCE: a hand-written REQUIRED lifecycle artifact (outputs/sr_plausibility.json with no
generated_by) -> validate_run_state.py --verify-provenance rejects it (exit 1). sr_plausibility.json
is the ONLY artifact LIFECYCLE_REQUIRED_PROVENANCE covers, so seed IT (with its declared inputs
present), NOT trap_sweep.json. The --verify-provenance branch prints `PROVENANCE FAIL:` to stderr and
exits 1 (NOT JSON), so drive it as a RAW subprocess and assert the EXIT CODE -- run_validate's --json
path would raise on the non-JSON stdout (mirror p4a test_verify_provenance_rejects_handwritten_artifact)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_prov")
        L.write_contract(rd, task_mode="reproduce", stat_mode="best-sr-counting",
                         compute_plan="smoke", detector_mode="simpleanalysis-delphes-native")
        # the declared inputs of sr_plausibility.json, present
        L.write_json(rd, "outputs/sr_yields.json",
                     [{"name": "SR1", "n": 5, "b": 4.0, "db": 1.0, "s": 3.0}])
        L.write_json(rd, "outputs/pyhf_exclusion/exclusion.json",
                     {"obs_limit": 0.7, "exp_limits": [0.4, 0.55, 0.7, 0.95, 1.3], "per_sr": {},
                      "best_sr": "SR1"})
        # hand-written: NO generated_by -> the lifecycle provenance check rejects it
        L.write_json(rd, "outputs/sr_plausibility.json", {"schema_version": 1, "verdict": "plausible"})
        p = L.run_tool("validate_run_state.py", ["--rundir", rd, "--verify-provenance"])
        L.gate_fired(p.returncode == 1,
                     f"--verify-provenance exit {p.returncode}, expected 1 (hand-written artifact); "
                     f"stderr={(p.stderr or '')[:200]!r}")

if __name__ == "__main__":
    sys.exit(run())
