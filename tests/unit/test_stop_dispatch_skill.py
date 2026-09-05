import json, os, subprocess, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "src/ravel/workflow/stop_dispatch.py"

def _mk_run(tmp, **state):
    os.makedirs(os.path.join(tmp, "logs"), exist_ok=True)
    st = {"schema_version": 1, "session_id": "SELFTEST"}; st.update(state)
    json.dump(st, open(os.path.join(tmp, "run_state.json"), "w"))
    return str(tmp)

def _run(rundir):
    return subprocess.run([sys.executable, str(SCRIPT), "--rundir", str(rundir),
                           "--last-message", "step done", "--branch", "skill-coverage"],
                          cwd=REPO, capture_output=True, text=True)

# current_step values below are the STAGE_ORDER stage names workflow_state.py `advance` actually
# writes ('route'/'analysis'/'verification'/'statistics'/'generation') -- the production shape.

def test_blocks_missing_required_skill(tmp_path):
    rd = _mk_run(tmp_path, current_step="verification", skills_invoked=[{"skill": "run-scan"}])
    r = _run(rd)
    assert r.returncode == 2 and "SKILL-COVERAGE" in r.stderr

def test_passes_when_skill_present(tmp_path):
    rd = _mk_run(tmp_path, current_step="verification",
                 skills_invoked=[{"skill": "verification-panel"}])
    assert _run(rd).returncode == 0

def test_passes_step_without_required_skill(tmp_path):
    # A5 mapped 'generation' -> run-stage, so the unmapped exemplar is now basis_manifest
    rd = _mk_run(tmp_path, current_step="basis_manifest", skills_invoked=[])
    assert _run(rd).returncode == 0

def test_route_stage_requires_route_analysis(tmp_path):
    rd = _mk_run(tmp_path, current_step="route", skills_invoked=[{"skill": "certify"}])
    r = _run(rd)
    assert r.returncode == 2 and "route-analysis" in r.stderr

def test_analysis_stage_passes_with_certify(tmp_path):
    rd = _mk_run(tmp_path, current_step="analysis", skills_invoked=[{"skill": "certify"}])
    assert _run(rd).returncode == 0

def test_scan_mode_blocks_missing_run_scan(tmp_path):
    # 'scan' is a task_mode, not a stage: at the statistics stage a scan run must have run-scan.
    rd = _mk_run(tmp_path, current_step="statistics", task_mode="scan", skills_invoked=[])
    r = _run(rd)
    assert r.returncode == 2 and "run-scan" in r.stderr

def test_scan_mode_passes_with_run_scan(tmp_path):
    rd = _mk_run(tmp_path, current_step="statistics", task_mode="scan",
                 skills_invoked=[{"skill": "run-scan"}])
    assert _run(rd).returncode == 0

def test_statistics_stage_non_scan_has_no_requirement(tmp_path):
    rd = _mk_run(tmp_path, current_step="statistics", task_mode="reproduce", skills_invoked=[])
    assert _run(rd).returncode == 0


def test_generation_step_requires_run_stage(tmp_path):
    """A5: the bespoke-generation path is where lhe_check/supervisor idioms were lost (trial QE.8)."""
    rd = _mk_run(tmp_path, current_step="generation", task_mode="reproduce", skills_invoked=[])
    r = _run(rd)
    assert r.returncode == 2 and "run-stage" in r.stderr
