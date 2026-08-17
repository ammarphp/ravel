# framework/tests/test_spine_sim_stop.py
"""The Stop-dispatch + watchdog spine_sim cases (Task 6.4). Integration check: needs Phase 2's
stop_dispatch.py/stage_supervisor.py + Phase 4's resource_census --assert-recipe-search on disk.
"""
import json, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "framework" / "spine_sim" / "run_spine_sim.py"
GATES = ["G2", "G4", "G5", "G6", "G8", "G11", "G27"]


def test_stop_family_all_fire():
    r = subprocess.run([sys.executable, str(ENGINE), "--only", ",".join(GATES), "--json"],
                       cwd=REPO, capture_output=True, text=True)
    payload = json.loads(r.stdout)
    statuses = {x["gate"]: x["status"] for x in payload["results"]}
    assert r.returncode == 0, json.dumps(payload["results"], indent=2)
    for g in GATES:
        assert statuses.get(g) == "PASS", (g, statuses.get(g))
