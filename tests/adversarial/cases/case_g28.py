#!/usr/bin/env python3
"""G28 CHECK-IN 2 GATE: a run that recorded a full-size native generation with a valid CHECK-IN 1
approval but no CHECK-IN 2 GO makes validate_run_state's checkin2-go-before-bulk-compute invariant FAIL.
Only `workflow_state.py go`, bound to the CHECK-IN 2 artefact and the current approval, satisfies it."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

CHECKIN1 = {"schema_version": 1, "kind": "checkin1", "sections": {
    "i": "req", "i-b": "census", "ii": "gallery prose", "iii": {"plan": "x", "waypoint": "SR1 background"},
    "iv": "budget", "v": [{"id": "F1", "text": "assume"}], "vi": ["answer", "ask", "propose"]}}
CHECKIN2 = {"schema_version": 1, "kind": "checkin2", "sections": {
    "waypoint": "SR1 background beside the published one", "expectation": "agreement at smoke statistics",
    "ask": {"options": [{"name": "GO"}, {"name": "ADJUST"}]}}}

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-10-07_checkin2_gate")
        budget = {"schema_version": 1, "generated_by": "cost_preflight.py", "mode": "full",
                  "points": 1, "events_per_point": 10000, "backend": "native", "walltime_h": [0.5, 1]}
        L.write_contract(rd, task_mode="reproduce", compute_plan="full", cost_estimate=budget)
        L.write_json(rd, "inputs/checkin1.json", CHECKIN1)
        L.write_json(rd, "inputs/cost_preflight.json", budget)
        cp = L.run_tool("workflow_state.py", ["approve", "--rundir", rd, "--quote", "Yes, run it", "--plan", "full"])
        if cp.returncode != 0:
            raise L.CaseSetupError("approve refused: " + cp.stderr.strip()[:300])
        # The smoke waypoint was shown, then a full sample ran with no recorded GO.
        L.write_json(rd, "inputs/checkin2.json", CHECKIN2)
        L.write_json(rd, "inputs/native_execution_plan.json", {"required_compute_plan": "full"})
        L.write_json(rd, "outputs/sr_yields.json", {"srs": {"SR1": 1.0}})
        res, _rc = L.run_validate(rd)
        L.gate_fired(L.invariant_status(res, "checkin2-go-before-bulk-compute") == "FAIL",
                     "checkin2-go-before-bulk-compute did not FAIL a full run with no CHECK-IN 2 go")

if __name__ == "__main__":
    sys.exit(run())
