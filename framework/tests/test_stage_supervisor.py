import subprocess, sys, importlib.util
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "trial-runs/_infrastructure/stage_supervisor.py"

def _load():
    spec = importlib.util.spec_from_file_location("stage_supervisor_uut", SCRIPT)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

def test_selftest_passes():
    r = subprocess.run([sys.executable, str(SCRIPT), "--selftest"], cwd=REPO,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

def test_stage_budget_from_cost_preflight():
    mod = _load()
    # MadGraph scales linearly with events; flat stages sit at NATIVE_FLAT_MIN (12 min).
    assert round(mod.stage_budget_min("madgraph", 20000)) == 38   # (50-12)*1.0
    assert mod.stage_budget_min("pythia", 20000) == 12.0
    assert round(mod.stage_budget_min("madgraph", 40000)) == 76   # (50-12)*2.0
