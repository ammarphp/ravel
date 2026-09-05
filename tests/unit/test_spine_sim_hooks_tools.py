# tests/unit/test_spine_sim_hooks_tools.py
"""The hook + tool spine_sim cases (Task 6.5). Integration check across Phases 0-4.
"""
import json, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "tests" / "adversarial" / "run_suite.py"
GATES = ["G0a", "G0b", "G0c", "G1", "G3", "G7", "G9", "G17", "G18", "G19", "G20", "G22", "G24", "G26"]


def test_hook_tool_family_all_fire():
    r = subprocess.run([sys.executable, str(ENGINE), "--only", ",".join(GATES), "--json"],
                       cwd=REPO, capture_output=True, text=True)
    payload = json.loads(r.stdout)
    statuses = {x["gate"]: x["status"] for x in payload["results"]}
    assert r.returncode == 0, json.dumps(payload["results"], indent=2)
    for g in GATES:
        assert statuses.get(g) == "PASS", (g, statuses.get(g))
