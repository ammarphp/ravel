# framework/tests/test_spine_sim_invariants.py
"""The 8 validate_run_state-enforced spine_sim cases (Task 6.3): each seeds a bad fixture and
asserts the named invariant/stage FAILs. This is the INTEGRATION check -- it requires the Phase 3/4
invariants on disk (this phase runs last). Import the engine by file path; run from /tmp.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "framework" / "spine_sim" / "run_spine_sim.py"
GATES = ["G10", "G12", "G13", "G14", "G15", "G16", "G23", "G25"]


def test_invariant_family_all_fire():
    r = subprocess.run([sys.executable, str(ENGINE), "--only", ",".join(GATES), "--json"],
                       cwd=REPO, capture_output=True, text=True)
    payload = json.loads(r.stdout)
    statuses = {x["gate"]: x["status"] for x in payload["results"]}
    assert r.returncode == 0, json.dumps(payload["results"], indent=2)
    for g in GATES:
        assert statuses.get(g) == "PASS", (g, statuses.get(g))
