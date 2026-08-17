#!/usr/bin/env python3
"""G23 IN-TREE OUTPUTS (N2): a scan_manifest point whose evidence resolves under /tmp must FAIL
inv outputs-in-tree."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _case_lib as L

@L.case_main
def run():
    with L.tempdir() as td:
        rd = os.path.join(td, "2026-07-09_intree")
        L.write_contract(rd, task_mode="scan", stat_mode="best-sr-counting", compute_plan="scan",
                         detector_mode="simpleanalysis-delphes-native")
        L.write_json(rd, "scan.json", {"schema_version": 1, "n_planned": 1, "n_done": 1,
                     "n_missing": 0, "points": [{"tag": "p1"}], "missing_tags": []})
        # inv_outputs_in_tree reads each scan_manifest point's run_dir (it SKIPS points with no
        # run_dir); an absolute /tmp run_dir is the N2 failure (mirror p4a _fixture_scan_output_in_tmp)
        L.write_json(rd, "scan_manifest.json", {"schema_version": 1, "n_points": 1,
                     "points": [{"tag": "p1", "run_dir": "/tmp/rogue_scan_point_p1"}]})
        res, _ = L.run_validate(rd)
        st = L.invariant_status(res, "outputs-in-tree")
        L.gate_fired(st == "FAIL", f"inv outputs-in-tree={st!r}, expected FAIL")

if __name__ == "__main__":
    sys.exit(run())
