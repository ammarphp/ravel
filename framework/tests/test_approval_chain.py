"""The approval chain (R3 T2, H1): workflow_state approve + the pre-exec Bash guard + invariant.

Run from OUTSIDE the repo: cd /tmp && python3 -m pytest <abspath> -q
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WS = REPO / "trial-runs" / "_infrastructure" / "workflow_state.py"
VRS = REPO / "trial-runs" / "_infrastructure" / "validate_run_state.py"
GUARD = REPO / ".claude" / "hooks" / "pretooluse-bash.sh"


def _vrs():
    spec = importlib.util.spec_from_file_location("vrs_r3t2", VRS)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _ws(*args):
    return subprocess.run([sys.executable, str(WS), *args], cwd=REPO,
                          capture_output=True, text=True)


VALID_CHECKIN1 = {"schema_version": 1, "kind": "checkin1", "sections": {
    "i": "req", "i-b": "census", "ii": "gallery prose",
    "iii": {"plan": "x", "waypoint": "wp"}, "iv": "budget",
    "v": [{"id": "F1", "text": "assume"}], "vi": ["answer", "ask", "propose"]}}


def _rundir(tmp_path, with_checkin=True, with_cost=True):
    rd = tmp_path / "2026-08-05_TEST_approve"
    (rd / "inputs").mkdir(parents=True)
    (rd / "inputs" / "task_contract.json").write_text(json.dumps(
        _vrs()._base_contract(task_mode="reproduce", compute_plan="smoke")))
    if with_checkin:
        (rd / "inputs" / "checkin1.json").write_text(json.dumps(VALID_CHECKIN1))
    if with_cost:
        (rd / "inputs" / "cost_preflight.json").write_text(json.dumps(
            {"schema_version": 1, "generated_by": "cost_preflight.py",
             "mode": "smoke", "walltime_h": [0.5, 1]}))
    return rd


def test_approve_refuses_without_checkin1(tmp_path):
    rd = _rundir(tmp_path, with_checkin=False)
    r = _ws("approve", "--rundir", str(rd), "--quote", "GO ahead")
    assert r.returncode == 1 and "checkin1" in (r.stderr + r.stdout)


def test_approve_refuses_without_cost_artifact(tmp_path):
    rd = _rundir(tmp_path, with_cost=False)
    r = _ws("approve", "--rundir", str(rd), "--quote", "GO ahead")
    assert r.returncode == 1 and "cost_preflight" in (r.stderr + r.stdout)


def test_approve_writes_artifact(tmp_path):
    rd = _rundir(tmp_path)
    r = _ws("approve", "--rundir", str(rd), "--quote", "GO — approved, F1 answered", "--plan", "smoke")
    assert r.returncode == 0, r.stderr
    doc = json.loads((rd / "inputs" / "checkin1_approval.json").read_text())
    assert doc["schema_version"] == 2
    assert len(doc["input_fingerprint"]) == 64
    assert doc["generated_by"] == "workflow_state.py approve"
    assert doc["approved_plan"] == "smoke" and "GO" in doc["quote"]


def _guard(command, project_dir, cwd, session=None):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project_dir))
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
    if session is not None:
        payload["session_id"] = session
    return subprocess.run(["bash", str(GUARD)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env)


def _skel(tmp_path, plan="smoke", approved=False, recipe=True):
    """A project skeleton with one session-scoped run."""
    proj = tmp_path
    rd = proj / "trial-runs" / "run1"
    (rd / "inputs").mkdir(parents=True)
    infra = proj / "trial-runs" / "_infrastructure"
    infra.mkdir()
    for name in ("validate_task_contract.py", "workflow_state.py", "validate_run_state.py",
                 "provenance.py", "session_lock.py", "validate_checkin.py", "result_pack.py"):
        (infra / name).symlink_to(REPO / "trial-runs" / "_infrastructure" / name)
    (rd / "run_state.json").write_text(json.dumps({"schema_version": 1, "session_id": "S1"}))
    (rd / "inputs" / "task_contract.json").write_text(json.dumps(
        _vrs()._base_contract(task_mode="reproduce", compute_plan=plan,
                             targets={"model": "svj-tchannel"})))
    (rd / "inputs" / "generation_recipe.json").write_text("{}") if recipe else None
    if approved:
        if plan in ("smoke", "full", "scan"):
            (rd / "inputs" / "checkin1.json").write_text(json.dumps(VALID_CHECKIN1))
            (rd / "inputs" / "cost_preflight.json").write_text(json.dumps(
                {"schema_version": 1, "generated_by": "cost_preflight.py",
                 "mode": plan, "walltime_h": [0.5, 1]}))
            result = _ws("approve", "--rundir", str(rd), "--quote", "GO", "--plan", plan)
            assert result.returncode == 0, result.stderr
        else:
            (rd / "inputs" / "checkin1_approval.json").write_text("{}")
    return proj, rd


def test_guard_blocks_detached_gen():
    r = _guard("nohup ./bin/generate_events &", REPO, REPO, session="NOSESSION-X")
    assert r.returncode == 2 and "nohup" in r.stderr.lower() or "detach" in r.stderr.lower()


def test_guard_blocks_unapproved_smoke_gen(tmp_path):
    proj, rd = _skel(tmp_path, approved=False)
    r = _guard("bash trial-runs/_infrastructure/run-pipeline-native.sh trial-runs/run1 cfg.toml",
               proj, rd, session="S1")
    assert r.returncode == 2 and "approve" in r.stderr


def test_guard_allows_approved_supervised_gen(tmp_path):
    proj, rd = _skel(tmp_path, approved=True)
    r = _guard("bash trial-runs/_infrastructure/run-pipeline-native.sh trial-runs/run1 cfg.toml",
               proj, rd, session="S1")
    assert r.returncode == 0, r.stderr


def test_guard_blocks_unsupervised_gen(tmp_path):
    proj, rd = _skel(tmp_path, approved=True)
    r = _guard("./bin/mg5_aMC run.mg5", proj, rd, session="S1")
    assert r.returncode == 2 and ("wrap" in r.stderr.lower() or "supervis" in r.stderr.lower())


def test_guard_passes_non_gen_bash(tmp_path):
    proj, rd = _skel(tmp_path, approved=False)
    r = _guard("ls -la && git status", proj, rd, session="S1")
    assert r.returncode == 0


def test_guard_passes_dev_session(tmp_path):
    (tmp_path / "trial-runs").mkdir()
    r = _guard("./bin/mg5_aMC run.mg5", tmp_path, tmp_path, session="DEV1")
    assert r.returncode == 0


def test_invariant_fails_without_approval(tmp_path):
    vrs = _vrs()
    rd = tmp_path / "2026-08-05_TEST_inv"
    (rd / "inputs").mkdir(parents=True); (rd / "outputs").mkdir()
    contract = vrs._base_contract(task_mode="reproduce", compute_plan="smoke")
    vrs._write_json(str(rd / "inputs" / "task_contract.json"), contract)
    vrs._write_json(str(rd / "outputs" / "sr_yields.json"), {"srs": {"SR1": 1.0}})
    facts = vrs.discover_facts(str(rd), contract)
    status, detail = vrs.inv_approval_before_compute(str(rd), contract, facts, False, False)
    assert status == "FAIL" and "approve" in detail


@pytest.mark.parametrize("change", [{"schema_version": True}, {"approval_required": False},
                                  {"targets": {"lumi_fb": -139}}])
def test_approve_revalidates_contract_before_writing(tmp_path, change):
    rd = _rundir(tmp_path)
    path = rd / "inputs" / "task_contract.json"
    value = json.loads(path.read_text())
    value.update(change)
    path.write_text(json.dumps(value))
    result = _ws("approve", "--rundir", str(rd), "--quote", "GO")
    assert result.returncode == 1
    assert "invalid task_contract" in result.stderr
    assert not (rd / "inputs" / "checkin1_approval.json").exists()


@pytest.mark.parametrize("raw", ['{"mode": "smoke", "mode": "smoke"}',
                              '{"mode": "smoke", "walltime_h": [0, NaN]}',
                              '{"mode": "scan", "points": 1, "walltime_h": [1, 2]}', '{}'])
def test_approval_rejects_invalid_or_mismatched_recorded_budget(tmp_path, raw):
    rd = _rundir(tmp_path)
    (rd / "inputs" / "cost_preflight.json").write_text(raw)
    result = _ws("approve", "--rundir", str(rd), "--quote", "GO")
    assert result.returncode == 1
    assert "cost_preflight" in result.stderr
    assert not (rd / "inputs" / "checkin1_approval.json").exists()


def test_approval_cannot_increase_the_contract_compute_scope(tmp_path):
    rd = _rundir(tmp_path)
    result = _ws("approve", "--rundir", str(rd), "--quote", "GO", "--plan", "scan")
    assert result.returncode == 1
    assert "exceeds" in result.stderr
    assert not (rd / "inputs" / "checkin1_approval.json").exists()


@pytest.mark.parametrize("raw", ['{}', 'null', '[1]',
                              '{"compute_plan": "smoke", "compute_plan": "none"}'])
def test_guard_rejects_malformed_contract_even_with_approval(tmp_path, raw):
    proj, rd = _skel(tmp_path, approved=True)
    (rd / "inputs" / "task_contract.json").write_text(raw)
    result = _guard("bash trial-runs/_infrastructure/run-pipeline-native.sh trial-runs/run1 cfg.toml", proj, rd, session="S1")
    assert result.returncode == 2
    assert "invalid task_contract" in result.stderr


@pytest.mark.parametrize("plan", ["none", "dry"])
def test_guard_rejects_generation_outside_contract_compute_scope(tmp_path, plan):
    proj, rd = _skel(tmp_path, plan=plan, approved=True)
    result = _guard("bash trial-runs/_infrastructure/run-pipeline-native.sh trial-runs/run1 cfg.toml", proj, rd, session="S1")
    assert result.returncode == 2
    assert "outside task_contract" in result.stderr


def test_guard_fails_closed_when_validator_is_missing_in_a_physics_run(tmp_path):
    proj, rd = _skel(tmp_path, approved=True)
    (proj / "trial-runs" / "_infrastructure" / "validate_task_contract.py").unlink()
    result = _guard("bash trial-runs/_infrastructure/run-pipeline-native.sh trial-runs/run1 cfg.toml", proj, rd, session="S1")
    assert result.returncode == 2
    assert "validator is unavailable" in result.stderr


@pytest.mark.parametrize("raw", ['{}', 'not JSON', 'null',
                              '{"schema_version": 2, "schema_version": 2}',
                              '{"schema_version": 1, "generated_by": "workflow_state.py approve", "approved_plan": "smoke", "quote": "GO"}'])
def test_guard_rejects_malformed_or_unbound_approval_file(tmp_path, raw):
    proj, rd = _skel(tmp_path, approved=True)
    (rd / "inputs" / "checkin1_approval.json").write_text(raw)
    result = _guard("bash trial-runs/_infrastructure/run-pipeline-native.sh trial-runs/run1 cfg.toml", proj, rd, session="S1")
    assert result.returncode == 2
    assert "invalid approval" in result.stderr


@pytest.mark.parametrize("source", ["task_contract.json", "checkin1.json", "cost_preflight.json"])
def test_source_changes_invalidate_approval_until_rerecorded(tmp_path, source):
    proj, rd = _skel(tmp_path, approved=True)
    ap = rd / "inputs" / "checkin1_approval.json"
    original = json.loads(ap.read_text())["input_fingerprint"]
    path = rd / "inputs" / source
    doc = json.loads(path.read_text())
    if source == "task_contract.json":
        doc["prompt"] += " Updated target scope."
    elif source == "checkin1.json":
        doc["sections"]["iv"] = "Updated budget explanation."
    else:
        doc["walltime_h"][1] += 1
    path.write_text(json.dumps(doc))
    command = "bash trial-runs/_infrastructure/run-pipeline-native.sh trial-runs/run1 cfg.toml"
    result = _guard(command, proj, rd, session="S1")
    assert result.returncode == 2
    assert "stale or unbound approval" in result.stderr
    # The post-hoc lifecycle gate calls the SAME verifier as the live Bash guard.
    vrs = _vrs()
    contract = json.loads((rd / "inputs" / "task_contract.json").read_text())
    facts = {"generation_hits": ["output/events.lhe"], "approval_path": "inputs/checkin1_approval.json"}
    status, why = vrs.inv_approval_before_compute(str(rd), contract, facts, False, False)
    assert status == "FAIL" and "stale or unbound approval" in why
    refreshed = _ws("approve", "--rundir", str(rd), "--quote", "GO for revised inputs")
    assert refreshed.returncode == 0, refreshed.stderr
    assert json.loads(ap.read_text())["input_fingerprint"] != original
    assert _guard(command, proj, rd, session="S1").returncode == 0


def test_planned_scan_can_have_a_bound_smoke_approval(tmp_path):
    proj, rd = _skel(tmp_path, approved=True)
    path = rd / "inputs" / "task_contract.json"
    doc = json.loads(path.read_text())
    doc["compute_plan"] = "scan"
    doc["cost_estimate"] = {"mode": "scan", "points": 12, "walltime_h": [1, 2]}
    path.write_text(json.dumps(doc))
    result = _ws("approve", "--rundir", str(rd), "--quote", "GO smoke first", "--plan", "smoke")
    assert result.returncode == 0, result.stderr
    guarded = _guard("bash trial-runs/_infrastructure/run-pipeline-native.sh trial-runs/run1 cfg.toml", proj, rd, session="S1")
    assert guarded.returncode == 0, guarded.stderr


@pytest.mark.parametrize("change", [{"schema_version": True}, {"quote": " "},
                                  {"approved_plan": "scan"}, {"input_fingerprint": "0" * 64},
                                  {"task_contract": "../different-run/inputs/task_contract.json"}])
def test_approval_content_cannot_bypass_binding_or_scope(tmp_path, change):
    proj, rd = _skel(tmp_path, approved=True)
    path = rd / "inputs" / "checkin1_approval.json"
    doc = json.loads(path.read_text())
    doc.update(change)
    path.write_text(json.dumps(doc))
    result = _guard("bash trial-runs/_infrastructure/run-pipeline-native.sh trial-runs/run1 cfg.toml", proj, rd, session="S1")
    assert result.returncode == 2 and "invalid approval" in result.stderr


def test_approve_rejects_blank_user_quote(tmp_path):
    rd = _rundir(tmp_path)
    result = _ws("approve", "--rundir", str(rd), "--quote", " ")
    assert result.returncode == 1 and "quote" in result.stderr
    assert not (rd / "inputs" / "checkin1_approval.json").exists()


def test_approve_rejects_duplicate_checkin_fields(tmp_path):
    rd = _rundir(tmp_path)
    path = rd / "inputs" / "checkin1.json"
    path.write_text(path.read_text().replace('"kind": "checkin1"', '"kind": "checkin1", "kind": "checkin1"'))
    result = _ws("approve", "--rundir", str(rd), "--quote", "GO")
    assert result.returncode == 1 and "duplicate" in result.stderr


def test_live_guard_never_uses_the_archive_approval_concession(tmp_path):
    proj, rd = _skel(tmp_path, approved=True)
    path = rd / "inputs" / "checkin1_approval.json"
    doc = json.loads(path.read_text())
    doc["schema_version"] = 1
    del doc["input_fingerprint"]
    path.write_text(json.dumps(doc))
    contract = json.loads((rd / "inputs" / "task_contract.json").read_text())
    facts = {"generation_hits": ["output/events.lhe"], "approval_path": "inputs/checkin1_approval.json"}
    # Archival reporting can explain missing historical evidence; strict/live checks fail.
    assert _vrs().inv_approval_before_compute(str(rd), contract, facts, True, False)[0] == "WARN"
    assert _vrs().inv_approval_before_compute(str(rd), contract, facts, True, True)[0] == "FAIL"
    guarded = _guard("bash trial-runs/_infrastructure/run-pipeline-native.sh trial-runs/run1 cfg.toml", proj, rd, session="S1")
    assert guarded.returncode == 2


def test_bound_approval_supports_the_existing_root_contract_layout(tmp_path):
    proj, rd = _skel(tmp_path, approved=True)
    (rd / "inputs" / "task_contract.json").rename(rd / "task_contract.json")
    result = _ws("approve", "--rundir", str(rd), "--quote", "GO for this contract")
    assert result.returncode == 0, result.stderr
    approval = json.loads((rd / "inputs" / "checkin1_approval.json").read_text())
    assert approval["task_contract"] == "task_contract.json"
    guarded = _guard("bash trial-runs/_infrastructure/run-pipeline-native.sh trial-runs/run1 cfg.toml", proj, rd, session="S1")
    assert guarded.returncode == 0, guarded.stderr


def test_inputs_changed_during_approval_are_not_silently_bound(tmp_path, monkeypatch):
    rd = _rundir(tmp_path)
    spec = importlib.util.spec_from_file_location("approval_race_under_test", WS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import validate_checkin
    original = validate_checkin.validate

    def update_cost_during_validation(*args, **kwargs):
        errors = original(*args, **kwargs)
        path = rd / "inputs" / "cost_preflight.json"
        budget = json.loads(path.read_text())
        budget["walltime_h"][1] += 1
        path.write_text(json.dumps(budget))
        return errors

    monkeypatch.setattr(validate_checkin, "validate", update_cost_during_validation)
    assert module.main(["approve", "--rundir", str(rd), "--quote", "GO"]) == 1
    assert not (rd / "inputs" / "checkin1_approval.json").exists()


@pytest.mark.parametrize("command", [
    "python3 trial-runs/_infrastructure/scan_orchestrator.py launch trial-runs/run1 --go",
    "python3 trial-runs/_infrastructure/scan_babysitter.py trial-runs/run1 --once",
    "python3 trial-runs/_infrastructure/scan_orchestrator.py launch trial-runs/run1 --go; echo --help",
    "python3 trial-runs/_infrastructure/scan_orchestrator.py launch trial-runs/run1 --go\necho --help",
    "python3 trial-runs/_infrastructure/scan_orchestrator.py launch trial-runs/run1 --go # --help",
    "python3 trial-runs/_infrastructure/scan_orchestrator.py launch trial-runs/run1 --go # note\necho --help",
    "python3 trial-runs/_infrastructure/scan_orchestrator.py launch trial-runs/run1 " + chr(92) + "\n --go; echo --help",
])
def test_explicit_bulk_launch_requires_scan_approval(tmp_path, command):
    proj, rd = _skel(tmp_path, approved=True)
    path = rd / "inputs" / "task_contract.json"
    contract = json.loads(path.read_text())
    contract["compute_plan"] = "scan"
    contract["cost_estimate"] = {"mode": "scan", "points": 12, "walltime_h": [1, 2]}
    path.write_text(json.dumps(contract))
    smoke = _ws("approve", "--rundir", str(rd), "--quote", "GO smoke first", "--plan", "smoke")
    assert smoke.returncode == 0, smoke.stderr
    result = _guard(command, proj, rd, session="S1")
    assert result.returncode == 2
    assert "explicit scan launch exceeds approved_plan=smoke" in result.stderr
    (rd / "inputs" / "cost_preflight.json").write_text(json.dumps(
        {"schema_version": 1, "generated_by": "cost_preflight.py", "mode": "scan",
         "points": 12, "walltime_h": [1, 2]}))
    scan = _ws("approve", "--rundir", str(rd), "--quote", "GO scan", "--plan", "scan")
    assert scan.returncode == 0, scan.stderr
    assert _guard(command, proj, rd, session="S1").returncode == 0


@pytest.mark.parametrize("command", [
    "python3 trial-runs/_infrastructure/scan_orchestrator.py launch trial-runs/run1",
    "python3 trial-runs/_infrastructure/scan_orchestrator.py status trial-runs/run1",
    "python3 trial-runs/_infrastructure/scan_orchestrator.py launch --help",
    "python3 trial-runs/_infrastructure/scan_babysitter.py --help",
    "echo python3 trial-runs/_infrastructure/scan_orchestrator.py launch trial-runs/run1 --go",
])
def test_bulk_driver_queries_and_dry_runs_need_no_scan_approval(tmp_path, command):
    proj, rd = _skel(tmp_path, approved=False)
    result = _guard(command, proj, rd, session="S1")
    assert result.returncode == 0, result.stderr
