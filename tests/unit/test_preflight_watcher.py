# tests/unit/test_preflight_watcher.py
import json, os, subprocess, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "src/ravel/workflow/preflight_watcher.py"

def test_preflight_selftest_passes():
    r = subprocess.run([sys.executable, str(SCRIPT), "--selftest"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

def test_arm_arity_mismatch_refuses(tmp_path):
    target = tmp_path / "wait_and_assemble.py"
    target.write_text("#!/usr/bin/env python3\nimport argparse\n"
                      "ap=argparse.ArgumentParser()\n"
                      "for n in ('scandir','manifest','backend','pdf','out'):\n"
                      "    ap.add_argument(n)\n"
                      "ap.parse_args()\n")
    rd = tmp_path / "run"; rd.mkdir()
    r = subprocess.run([sys.executable, str(SCRIPT), "--arm", "--rundir", str(rd),
                        "--name", "wait_and_assemble",
                        "--fire", f"python3 {target} a b c", "--target", str(target)],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    pf = rd / "logs" / "wait_and_assemble.preflight.json"
    assert pf.is_file() and json.loads(pf.read_text())["verdict"] == "fail"

def test_assert_all_missing_preflight(tmp_path):
    rd = tmp_path / "run"; (rd / "logs").mkdir(parents=True)
    (rd / "run_state.json").write_text(json.dumps(
        {"armed_watchers": [{"name": "ghost", "preflight": "logs/ghost.preflight.json"}]}))
    r = subprocess.run([sys.executable, str(SCRIPT), "--assert-all", "--rundir", str(rd)],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr

def test_assert_all_passing_preflight(tmp_path):
    target = tmp_path / "w.py"
    target.write_text("#!/usr/bin/env python3\nimport argparse\n"
                      "ap=argparse.ArgumentParser()\nap.add_argument('a')\nap.parse_args()\n")
    rd = tmp_path / "run"; rd.mkdir()
    subprocess.run([sys.executable, str(SCRIPT), "--arm", "--rundir", str(rd), "--name", "w",
                    "--fire", f"python3 {target} x", "--target", str(target)], cwd=REPO)
    (rd / "run_state.json").write_text(json.dumps(
        {"armed_watchers": [{"name": "w", "preflight": "logs/w.preflight.json"}]}))
    r = subprocess.run([sys.executable, str(SCRIPT), "--assert-all", "--rundir", str(rd)],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

def test_armed_watcher_stop_branch(tmp_path):
    # D-4/G24: the branch THIS task registers in stop_dispatch.py must BLOCK (exit 2 + token) a turn-end
    # left with an armed watcher whose preflight is missing, and clear once no watcher is armed.
    STOP = REPO / "src/ravel/workflow/stop_dispatch.py"
    rd = tmp_path / "run"; (rd / "logs").mkdir(parents=True)
    (rd / "run_state.json").write_text(json.dumps(
        {"session_id": "T",
         "armed_watchers": [{"name": "ghost", "preflight": "logs/ghost.preflight.json"}]}))
    blocked = subprocess.run([sys.executable, str(STOP), "--rundir", str(rd),
                              "--last-message", "ok", "--branch", "armed-watcher"],
                             cwd=REPO, capture_output=True, text=True)
    assert blocked.returncode == 2 and "G24-ARMED-WATCHER" in blocked.stderr, blocked.stdout + blocked.stderr
    (rd / "run_state.json").write_text(json.dumps({"session_id": "T", "armed_watchers": []}))
    allowed = subprocess.run([sys.executable, str(STOP), "--rundir", str(rd),
                              "--last-message", "ok", "--branch", "armed-watcher"],
                             cwd=REPO, capture_output=True, text=True)
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr
