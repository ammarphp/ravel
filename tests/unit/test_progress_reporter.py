import subprocess, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "src/ravel/workflow/progress_reporter.py"

def test_selftest_passes():
    r = subprocess.run([sys.executable, str(SCRIPT), "--selftest"], cwd=REPO,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

def test_reports_done_count(tmp_path):
    import json, os
    (tmp_path / "logs").mkdir()
    pt = tmp_path / "pt_m150_dm10"; (pt / "output").mkdir(parents=True)
    (pt / "output" / "exclusion.json").write_text("{}")
    man = {"points": [{"tag": "m150_dm10", "run_dir": str(pt)}]}
    (tmp_path / "scan_manifest.json").write_text(json.dumps(man))
    r = subprocess.run([sys.executable, str(SCRIPT), "--rundir", str(tmp_path)], cwd=REPO,
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "done=1/1" in r.stdout
