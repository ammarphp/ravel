#!/usr/bin/env python3
"""G16 PLAUSIBILITY (D14): all-zero SR yields -> degenerate huge mu95 -> check_statistics must FAIL
(the statistics stage), not PASS a vacuous 'not excluded'."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_plausible")
        L.write_contract(rd, task_mode="reproduce", stat_mode="best-sr-counting",
                         compute_plan="smoke", detector_mode="simpleanalysis-delphes-native")
        L.write_json(rd, "outputs/sr_yields.json",
                     [{"name": "SR1", "n": 0, "b": 0.0, "db": 0.0, "s": 0.0}])   # all-zero yields
        L.write_json(rd, "outputs/pyhf_exclusion/exclusion.json", {"schema_version": 1,
                     "stat_mode": "best-sr-counting", "obs_limit": 9.9e9,
                     "exp_limits": [9e9, 9e9, 9.9e9, 1e10, 1.1e10], "per_sr": {}, "best_sr": "SR1"})
        # implausible plausibility artifact: check_statistics folds it via pdoc.get("verdict") -- the
        # REAL enforcement reads "verdict"/"reasons"/"generated_by" (mirror p4a _fixture_implausible_stats).
        L.write_json(rd, "outputs/sr_plausibility.json",
                     {"schema_version": 1, "generated_by": "sr_plausibility.py", "input_fingerprint": "x",
                      "verdict": "implausible",
                      "reasons": ["nontrivial-sr: 0 SR(s) carry signal>0 of 1",
                                  "mu95-in-band: mu95_obs=9900000000.0 out of band"]})
        res, _ = L.run_validate(rd)
        st = L.stage_status(res, "statistics")
        L.gate_fired(st == "FAIL", f"statistics stage={st!r}, expected FAIL (plausibility)")

if __name__ == "__main__":
    sys.exit(run())
