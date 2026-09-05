#!/usr/bin/env python3
"""G15 TRAP-OBLIGATION (D13): a T8 trap hit (validly flagged) with NO discharged obligation must
FAIL inv trap-obligations-discharged."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L
import validate_run_state as vrs

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_trapobl")
        L.write_contract(rd, task_mode="reproduce", stat_mode="best-sr-counting",
                         compute_plan="smoke", detector_mode="simpleanalysis-delphes-native")
        L.write_json(rd, "inputs/resource_census.json", vrs._resource_census_doc())
        # T8 hit with an EXPLICIT PENDING obligation. obligations=None would AUTO-EMIT a PASS obligation
        # (so the invariant would pass) -- pass the pending entry explicitly (mirror p4a
        # _fixture_trap_obligation_pending).
        L.write_json(rd, "inputs/trap_sweep.json",
                     vrs._trap_sweep_doc(traps_hit=["T8"], escalations=[{"id": "T8"}], obligations=[
                         {"trap": "T8", "obligation_kind": "per-width-regen",
                          "artifact": "inputs/validations.json#T8", "status": "PENDING"}]))
        L.write_json(rd, "logs/ladder.json", {"schema_version": 1, "generated_by": "cost_preflight.py",
                     "rungs": [{"rung": "smoke", "status": "PASS"}]})
        # a generation artifact so facts["generation_hits"] is non-empty -> the D13 gate is live
        L.write_json(rd, "outputs/sr_yields.json",
                     [{"name": "SR1", "n": 5, "b": 4.0, "db": 1.0, "s": 3.0}])
        res, _ = L.run_validate(rd)
        st = L.invariant_status(res, "trap-obligations-discharged")
        L.gate_fired(st == "FAIL", f"inv trap-obligations-discharged={st!r}, expected FAIL")

if __name__ == "__main__":
    sys.exit(run())
