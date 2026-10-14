"""Host governance: `ravel gate`, the run registry, hookless records and the status packet.

Synthetic runs only. Every subprocess runs with a temporary RAVEL_STATE_DIR and no host session
variables, so a test never registers or reads the session of the agent that runs it.
"""

from method_decision_fixture import admit_method
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

VERDICT_KEYS = {"schema_version", "kind", "rundir", "run_id", "session_id", "action", "gate",
                "command_sha256", "decision", "errors", "providers", "pre_execution_guards",
                "enforcement_surface_sha256", "checked_utc"}
ERROR_KEYS = {"code", "gate", "provider", "message", "fix", "pins"}
GATES = ("approve_plan", "launch", "failed_stage_feedback", "checkin2_accept", "correction", "deviation",
         "research_choice", "delivery", "final_task", "report_integrity", "export", "unblind",
         "spend_above_ceiling")
GEN_COMMAND = "bash native/scripts/run-pipeline-native.sh run cfg.toml"


def _env(tmp_path, **extra):
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDE_CODE_SESSION_ID", "RAVEL_SESSION_ID", "CLAUDECODE", "CLAUDE_PROJECT_DIR",
                        "RAVEL_PRE_EXECUTION_GUARDS", "RAVEL_HOST")}
    env.update(PYTHONPATH=str(REPO / "src"), RAVEL_STATE_DIR=str(tmp_path / "state"), RAVEL_PYTHON=sys.executable)
    env.update(extra)
    return env


def _ravel(tmp_path, *args, cwd=None, **extra):
    return subprocess.run([sys.executable, "-m", "ravel", *map(str, args)], cwd=cwd or tmp_path,
                          env=_env(tmp_path, **extra), capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)


def _contract(**over):
    from ravel.validation.validate_run_state import _base_contract
    return _base_contract(**over)


def _run(base, name="run", session=None, **over):
    """A hookless fixture run: a contract and a run_state, no hook table anywhere."""
    rd = base / name
    (rd / "inputs").mkdir(parents=True)
    (rd / "inputs/task_contract.json").write_text(json.dumps(_contract(**over)))
    (rd / "run_state.json").write_text(json.dumps({"schema_version": 1, "session_id": session or ""}))
    return rd


# --------------------------------------------------------------------------- acceptance 1

@pytest.mark.parametrize("action", GATES + ("tool_call",))
def test_gate_returns_the_ai11_verdict_on_a_hookless_fixture(tmp_path, action):
    rd = _run(tmp_path / "project", compute_plan="smoke", task_mode="reproduce")
    args = ["gate", "--rundir", rd, "--action", action, "--json"]
    if action == "tool_call":
        args += ["--command", GEN_COMMAND]
    r = _ravel(tmp_path, *args, cwd=tmp_path / "project")
    assert r.returncode in (0, 2), r.stderr
    verdict = json.loads(r.stdout)
    assert set(verdict) == VERDICT_KEYS
    assert verdict["kind"] == "gate-verdict" and verdict["schema_version"] == 1
    assert verdict["action"] == action and verdict["run_id"] == "run"
    assert verdict["gate"] == ("launch" if action == "tool_call" else action)
    assert verdict["decision"] in ("allow", "deny")
    assert r.returncode == (2 if verdict["decision"] == "deny" else 0)
    assert verdict["pre_execution_guards"] == "none"            # no hook table on this host
    assert len(verdict["enforcement_surface_sha256"]) == 64
    assert all(set(e) == ERROR_KEYS for e in verdict["errors"])
    assert all({"id", "active"} <= set(p) for p in verdict["providers"])


def test_gate_tool_call_classes(tmp_path):
    rd = _run(tmp_path, compute_plan="smoke", task_mode="reproduce")
    r = _ravel(tmp_path, "gate", "--rundir", rd, "--action", "tool_call", "--command", "ls -la", "--json")
    assert r.returncode == 0 and json.loads(r.stdout)["gate"] == "none"
    r = _ravel(tmp_path, "gate", "--rundir", rd, "--action", "tool_call", "--command", GEN_COMMAND, "--json")
    verdict = json.loads(r.stdout)
    assert r.returncode == 2 and verdict["decision"] == "deny"
    assert any(e["provider"] == "launch_approval" and "UNAPPROVED" in e["message"] for e in verdict["errors"])
    assert verdict["command_sha256"] and len(verdict["command_sha256"]) == 64
    from ravel.workflow import host_gate
    assert host_gate.classify("ravel approve --rundir x --quote y") == "approve_plan"
    assert host_gate.classify("ravel result-pack --rundir x") == "delivery"
    assert host_gate.classify("python3 scan_orchestrator.py launch s --go") == "launch"


def test_gate_usage_errors(tmp_path):
    assert _ravel(tmp_path, "gate", "--action", "nonsense", "--json").returncode == 1
    assert _ravel(tmp_path, "gate", "--action", "tool_call", "--json").returncode == 1
    # A gated action with no run for this session or directory is a missing run, not an allow.
    assert _ravel(tmp_path, "gate", "--action", "delivery", "--json").returncode == 1


def test_gate_resolves_the_registered_run_never_the_newest(tmp_path):
    import time
    mine = _run(tmp_path / "elsewhere", "mine", compute_plan="smoke", task_mode="reproduce")
    time.sleep(0.01)
    _run(tmp_path / "project" / "trial-runs", "newest", compute_plan="smoke", task_mode="reproduce")
    reg =subprocess.run([sys.executable, "-m", "ravel.workflow.active_run", "register", "--rundir", mine,
                          "--session", "S-A", "--by", "test"], env=_env(tmp_path), capture_output=True, text=True)
    assert reg.returncode == 0, reg.stderr
    r = _ravel(tmp_path, "gate", "--action", "delivery", "--session", "S-A", "--json",
               cwd=tmp_path / "project", CLAUDE_PROJECT_DIR=str(tmp_path / "project"))
    assert json.loads(r.stdout)["rundir"] == str(mine)
    r = _ravel(tmp_path, "gate", "--action", "delivery", "--session", "S-OTHER", "--json",
               cwd=tmp_path / "project", CLAUDE_PROJECT_DIR=str(tmp_path / "project"))
    assert r.returncode == 1 and json.loads(r.stdout)["rundir"] is None


# --------------------------------------------------------------------------- acceptance 2

def _journal_bound(rd, outputs):
    """Append an authorized+launched pair bound to an approval pin, as the supervised path does."""
    from ravel.workflow import launch_authorization as la
    (rd / "inputs/checkin1_approval.json").write_text("{}")
    approval = {"path": str(rd / "inputs/checkin1_approval.json"), "sha256": "0" * 64}
    auth = la._append(rd, {"event": "authorized", "command": ["stage"], "context": {
        "stage": "madgraph", "stage_spec": {"outputs": [str(rd / o) for o in outputs]}},
        "authorization": {"required_plan": "smoke", "approval": approval}})
    la._append(rd, {"event": "launched", "authorization_sequence": auth["sequence"],
                    "authorization_sha256": auth["sha256"], "pid": 4242})


def test_raw_generation_output_refuses_delivery_on_a_hookless_host(tmp_path):
    rd = _run(tmp_path, compute_plan="smoke", task_mode="reproduce", agent_layer_epoch=2)
    (rd / "stages/madgraph").mkdir(parents=True)
    (rd / "stages/madgraph/unweighted_events.lhe.gz").write_bytes(b"raw")
    r = _ravel(tmp_path, "gate", "--rundir", rd, "--action", "delivery", "--json")
    verdict = json.loads(r.stdout)
    assert r.returncode == 2
    # Epoch-one decisions remain legacy; the delivery invariant is separately mandatory.
    from ravel.workflow import host_governance
    raw = host_governance.raw_launch_errors(rd)
    assert raw and raw[0]["provider"] == "raw_launch"
    assert raw[0]["code"] in ("raw_launch", "provider_inactive")
    from ravel.workflow import host_governance
    assert host_governance.enforcement_record(rd, project=tmp_path)["raw_launch"] == "fail"


def test_invalid_journal_approval_refuses_the_raw_launch_invariant(tmp_path):
    rd = _run(tmp_path, compute_plan="smoke", task_mode="reproduce", agent_layer_epoch=2)
    (rd / "stages/madgraph").mkdir(parents=True)
    (rd / "stages/madgraph/unweighted_events.lhe.gz").write_bytes(b"supervised")
    _journal_bound(rd, ["stages/madgraph/unweighted_events.lhe.gz"])
    from ravel.workflow import host_governance, host_gate
    errors = host_governance.raw_launch_errors(rd)
    assert errors and errors[0]["provider"] == "raw_launch"
    assert errors[0]["code"] in ("raw_launch", "provider_inactive")
    result = host_gate.verdict(rd, "delivery", project=tmp_path)
    assert result["decision"] == "deny"


def _real_raw_launch():
    import importlib
    try:
        provider = importlib.import_module("ravel.workflow.raw_launch")
    except ImportError:
        pytest.skip("the raw_launch provider is absent from this tree")
    assert Path(provider.__file__).resolve().is_relative_to(REPO / "src")
    return provider


def test_hookless_tool_call_refuses_raw_launch_before_intake(tmp_path):
    project = tmp_path / "project"
    (project / "logs").mkdir(parents=True)
    (project / "logs/.route-pending-S-P").write_text("")
    r = _ravel(tmp_path, "gate", "--action", "tool_call", "--command", GEN_COMMAND, "--session", "S-P",
               "--json", cwd=project, CLAUDE_PROJECT_DIR=str(project))
    verdict = json.loads(r.stdout)
    assert r.returncode == 2 and verdict["errors"][0]["code"] == "pre_intake"


def _packable(rd):
    (rd / "outputs/pyhf_exclusion").mkdir(parents=True)
    (rd / "outputs/sr_yields.json").write_text(json.dumps([{"name": "SR1", "n": 3, "b": 2.5, "db": 0.5, "s": 1.0}]))
    (rd / "outputs/pyhf_exclusion/exclusion.json").write_text(json.dumps({
        "obs_limit": .8, "exp_limits": [.4, .7, 1.2, 2., 2.], "best_sr": "SR1",
        "at_mu_floor": False, "at_poi_cap": False, "median_at_cap": False,
        "limit_status": {"observed": "resolved", "expected": ["resolved"] * 3 + ["above_scan"] * 2},
        "limit_brackets": {"observed": [.79, .81], "expected": [[.39, .41], [.69, .71], [1.19, 1.21],
                                                                [2., None], [2., None]]},
        "fit_diagnostics": {"available": True, "covariance": None},
        "inference": {"coverage_validated": False},
        "numerical_evidence": {"coverage_validated": False, "observed": {"status": "resolved"}}}))
    (rd / "provenance.json").write_text(json.dumps({"model": "synthetic", "sigma_pb": 1.0, "lumi_fb": 139.0}))
    (rd / "outputs/cutflow_cert.json").write_text(json.dumps({"routine": "SYNTHETIC_ROUTINE", "verdict": "PASS"}))
    from test_normalization_ledger import ledger, exact_yields
    doc = ledger()
    (rd / "outputs/normalization-ledger.json").write_text(json.dumps(ledger(delivered=exact_yields(doc))))
    return rd


def _pack(tmp_path, rd, *extra, ledger="outputs/normalization-ledger.json"):
    pin = ("--normalization-ledger", ledger) if ledger else ()
    return subprocess.run([sys.executable, "-m", "ravel", "result-pack", "--rundir", str(rd),
                           "--stat-mode", "best-sr-counting", *pin, *extra], cwd=tmp_path,
                          env=_env(tmp_path), capture_output=True, text=True)


def test_result_pack_refuses_absolute_yields_without_a_normalization_ledger(tmp_path):
    rd = tmp_path / "run"
    rd.mkdir()
    _packable(rd)
    r = _pack(tmp_path, rd, "--detector-mode", "particle-level", ledger=None)
    assert r.returncode == 1 and "normalization_ledger" in r.stderr
    assert not (rd / "result.json").exists()


def test_result_pack_pins_the_declared_normalization_ledger(tmp_path):
    rd = tmp_path / "run"
    rd.mkdir()
    _packable(rd)
    assert _pack(tmp_path, rd, "--detector-mode", "particle-level").returncode == 0
    result = json.loads((rd / "result.json").read_text())
    import hashlib
    raw = (rd / "outputs/normalization-ledger.json").read_bytes()
    assert result["normalization_ledger"] == {"path": "outputs/normalization-ledger.json",
                                              "sha256": hashlib.sha256(raw).hexdigest()}
    checks = json.loads((rd / "outputs/delivery-checks.json").read_text())
    rows = checks.get("check_results") or checks.get("findings")
    assert any(r["check"] == "normalization_ledger" and r["status"] == "pass" for r in rows)


def test_result_pack_refuses_a_ledger_outside_the_run(tmp_path):
    rd = tmp_path / "run"
    rd.mkdir()
    _packable(rd)
    outside = tmp_path / "ledger.json"
    outside.write_bytes((rd / "outputs/normalization-ledger.json").read_bytes())
    r = _pack(tmp_path, rd, "--detector-mode", "particle-level", ledger=str(outside))
    assert r.returncode == 1 and "normalization" in r.stderr


def test_result_pack_records_enforcement_and_refuses_raw_launch(tmp_path):
    _real_raw_launch()
    rd = tmp_path / "run"
    rd.mkdir()
    _packable(rd)
    r = _pack(tmp_path, rd, "--detector-mode", "simpleanalysis-delphes-native")
    assert r.returncode == 0, r.stdout + r.stderr
    result = json.loads((rd / "result.json").read_text())
    assert result["detector_mode"] == "simpleanalysis-delphes"               # R-51 item 7 alias
    assert result["detector_mode_requested"] == "simpleanalysis-delphes-native"
    record = result["enforcement"]
    assert set(record) == {"pre_execution_guards", "enforcement_surface_sha256", "host", "raw_launch",
                           "declared_host", "declared_pre_execution_guards"}
    assert record["raw_launch"] == "pass" and record["pre_execution_guards"] == "none"
    (rd / "outputs/events.hepmc").write_bytes(b"raw")
    (rd / "outputs/claims").mkdir()
    r = _pack(tmp_path, rd, "--detector-mode", "container")
    assert r.returncode == 1 and "raw_launch" in r.stderr


def test_result_pack_stamps_delivered_claims(tmp_path):
    _real_raw_launch()
    rd = tmp_path / "run"
    rd.mkdir()
    _packable(rd)
    (rd / "outputs/claims").mkdir()
    (rd / "outputs/claims/c1.json").write_text(json.dumps({"id": "c1"}))
    assert _pack(tmp_path, rd, "--detector-mode", "particle-level").returncode == 0
    assert json.loads((rd / "outputs/claims/c1.json").read_text())["enforcement"]["raw_launch"] == "pass"


def test_result_pack_calls_the_va03_helper_and_refuses_a_severity_a_fail(tmp_path, monkeypatch):
    _real_raw_launch()
    import types
    rd = tmp_path / "run"
    rd.mkdir()
    _packable(rd)
    helper = types.ModuleType("ravel.validation.delivery_checks")
    calls = []

    def check_delivery(rundir, pack):
        calls.append((rundir, pack["stat_mode"]))
        return [{"check": "normalization_ledger", "deliverable": "result.json", "status": "fail",
                 "severity": "A", "detail": "planted mismatch", "receipt": None}]
    helper.check_delivery = check_delivery
    monkeypatch.setitem(sys.modules, "ravel.validation.delivery_checks", helper)
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))
    from ravel.workflow import result_pack
    with pytest.raises(result_pack.PackError, match="planted mismatch"):
        result_pack.main(["--rundir", str(rd), "--stat-mode", "best-sr-counting",
                          "--detector-mode", "particle-level"])
    assert calls and calls[0][1] == "best-sr-counting"
    assert json.loads((rd / "outputs/delivery-checks.json").read_text())["findings"][0]["status"] == "fail"


def test_checkin1_enforcement_surface_is_fingerprinted(tmp_path):
    from ravel.workflow import host_governance
    rd = _run(tmp_path)
    first = host_governance.record_checkin1_surface(rd, project=tmp_path)
    assert first["enforcement_surface_sha256"] == host_governance.enforcement_surface_sha256(tmp_path)
    (tmp_path / ".claude/hooks").mkdir(parents=True)
    (tmp_path / ".claude/hooks/x.sh").write_text("exit 0\n")
    host_governance.record_checkin1_surface(rd, project=tmp_path)
    rows = host_governance.checkin1_surface_rows(rd)
    assert len(rows) == 2 and rows[0] == first and rows[0] != rows[1]


def test_pre_execution_guards_reflect_the_host(tmp_path):
    from ravel.workflow import host_governance
    assert host_governance.pre_execution_guards(tmp_path, environ={}) == "none"
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "bash .claude/hooks/pretooluse-bash.sh"}]}]}}))
    assert host_governance.pre_execution_guards(tmp_path, environ={"CLAUDECODE": "1"}) == "host-hooks"
    assert host_governance.pre_execution_guards(tmp_path, environ={}) == "none"
    assert host_governance.pre_execution_guards(tmp_path, environ={"RAVEL_PRE_EXECUTION_GUARDS": "broker"}) == "none"
    assert host_governance.pre_execution_guards(REPO, environ={"CLAUDECODE": "1"}) == "host-hooks"


# --------------------------------------------------------------------------- KV-7 and the registry

def test_initiate_records_the_host_session_and_registers_the_run(tmp_path):
    out = tmp_path / "outside" / "run"
    r = _ravel(tmp_path, "initiate", "--prompt", "Summarize published limits on a synthetic heavy resonance.",
               "--out", out, CLAUDE_CODE_SESSION_ID="S-KV7")
    assert r.returncode in (0, 1), r.stderr
    assert json.loads((out / "run_state.json").read_text())["session_id"] == "S-KV7"
    found = subprocess.run([sys.executable, "-m", "ravel.workflow.active_run", "resolve", "--session", "S-KV7"],
                           env=_env(tmp_path), capture_output=True, text=True)
    assert found.stdout.strip() == str(out.absolute())
    r = _ravel(tmp_path, "initiate", "--prompt", "Summarize published limits on a synthetic heavy resonance.",
               "--out", tmp_path / "flag", "--session-id", "S-FLAG")
    assert json.loads((tmp_path / "flag/run_state.json").read_text())["session_id"] == "S-FLAG"


def test_registry_never_falls_back_to_the_newest_run(tmp_path, monkeypatch):
    from ravel.workflow import active_run
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))
    _run(tmp_path / "trial-runs", "newest", session="SOMEONE-ELSE")
    assert active_run.resolve("S-NONE", cwd=str(tmp_path), repo=tmp_path) is None
    own = _run(tmp_path / "away", "own")
    active_run.register(own, "S-OWN", by="test")
    assert active_run.resolve("S-OWN", cwd=str(tmp_path), repo=tmp_path) == own
    assert active_run.resolve(None, cwd=str(own / "inputs"), repo=tmp_path) == own
    assert active_run.release("S-OWN") and active_run.lookup("S-OWN") is None


def test_stop_dispatch_never_gates_on_another_sessions_run(tmp_path, monkeypatch):
    from ravel.workflow import stop_dispatch
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))
    _run(tmp_path / "trial-runs", "other", session="OTHER")
    assert stop_dispatch.resolve_rundir("MINE", str(tmp_path)) is None
    assert stop_dispatch.resolve_rundir("OTHER", str(tmp_path)) == str(tmp_path / "trial-runs/other")


# --------------------------------------------------------------------------- acceptance 5

def test_status_packet_resumable_from_records(tmp_path):
    from ravel.validation import check_status_packet
    out = tmp_path / "run"
    r = _ravel(tmp_path, "initiate", "--prompt", "Summarize published limits on a synthetic heavy resonance.",
               "--out", out)
    assert (out / "current_state.json").is_file(), r.stdout + r.stderr
    report = check_status_packet.check(out)
    assert report["status"] == "pass", report
    assert report["regenerated_next_sha256"] == report["recorded_next_sha256"]


def test_status_packet_check_fails_when_the_recorded_packet_differs(tmp_path):
    from ravel.validation import check_status_packet
    out = tmp_path / "run"
    _ravel(tmp_path, "initiate", "--prompt", "Summarize published limits on a synthetic heavy resonance.",
           "--out", out)
    packet = json.loads((out / "current_state.json").read_text())
    packet["next_required"] = {"kind": "stage", "what": "planted"}
    (out / "current_state.json").write_text(json.dumps(packet))
    report = check_status_packet.check(out)
    assert report["status"] == "fail" and "next work item" in report["detail"]
    assert check_status_packet.main([str(out)]) == 1


# --------------------------------------------------------------------------- R-50 item 2: hook sites

def _hook(name, payload, project, tmp_path):
    env = _env(tmp_path, CLAUDE_PROJECT_DIR=str(project))
    return subprocess.run(["bash", str(REPO / ".claude/hooks" / name)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env)


def _registered(tmp_path, session, **over):
    rd = _run(tmp_path / "outside", "run", session=session, **over)
    reg = subprocess.run([sys.executable, "-m", "ravel.workflow.active_run", "register", "--rundir", str(rd),
                          "--session", session, "--by", "test"], env=_env(tmp_path), capture_output=True, text=True)
    assert reg.returncode == 0, reg.stderr
    return rd


def test_skill_hook_lets_a_routed_session_spawn_agents_once_its_run_has_a_contract(tmp_path):
    """KV-7: the run created by initiate is found from the session, so subagents unblock."""
    project = tmp_path / "project"
    (project / "logs").mkdir(parents=True)
    marker = project / "logs/.route-pending-S-K"
    marker.write_text("")
    blocked = _hook("pretooluse-skill.sh", {"tool_name": "Agent", "tool_input": {}, "session_id": "S-K",
                                            "cwd": str(project)}, project, tmp_path)
    assert blocked.returncode == 2
    _registered(tmp_path, "S-K", compute_plan="smoke", task_mode="reproduce")
    allowed = _hook("pretooluse-skill.sh", {"tool_name": "Agent", "tool_input": {}, "session_id": "S-K",
                                            "cwd": str(project)}, project, tmp_path)
    assert allowed.returncode == 0, allowed.stderr
    assert not marker.exists()
    skill = _hook("pretooluse-skill.sh", {"tool_name": "Skill", "tool_input": {"skill": "run-stage"},
                                          "session_id": "S-K", "cwd": str(project)}, project, tmp_path)
    assert skill.returncode == 0, skill.stderr


def test_bash_hook_finds_a_run_outside_trial_runs_from_session_and_cwd(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    rd = _registered(tmp_path, "S-B", compute_plan="smoke", task_mode="reproduce")
    payload = {"tool_name": "Bash", "tool_input": {"command": GEN_COMMAND}, "session_id": "S-B",
               "cwd": str(project)}
    r = _hook("pretooluse-bash.sh", payload, project, tmp_path)
    assert r.returncode == 2 and ("UNAPPROVED" in r.stderr or "decision_gate is inactive" in r.stderr)
    r = _hook("pretooluse-bash.sh", {**payload, "session_id": "S-UNKNOWN", "cwd": str(rd / "inputs")},
              project, tmp_path)
    assert r.returncode == 2 and ("UNAPPROVED" in r.stderr or "decision_gate is inactive" in r.stderr)
    r = _hook("pretooluse-bash.sh", {**payload, "session_id": "S-UNKNOWN"}, project, tmp_path)
    assert r.returncode == 2 and "BEFORE intake" in r.stderr  # parity refuses hookless launches without a run


def test_protect_and_orient_hooks_use_the_registry(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    rd = _registered(tmp_path, "S-E")
    edit = {"tool_name": "Edit", "session_id": "S-E",
            "tool_input": {"file_path": str(project / "src/ravel/workflow/host_gate.py")}}
    assert _hook("protect-enforcement.sh", edit, project, tmp_path).returncode == 2
    assert _hook("protect-enforcement.sh", {**edit, "session_id": "S-DEV"}, project, tmp_path).returncode == 0
    orient = _hook("sessionstart-orient.sh", {"session_id": "S-E"}, project, tmp_path)
    assert str(rd) in orient.stdout and "ACTIVE RUN" in orient.stdout
    assert _hook("sessionstart-orient.sh", {"session_id": "S-DEV"}, project, tmp_path).stdout.strip() == ""


# --------------------------------------------------------------------------- R-51 items 1-2, R-50 item 4

VALID_CHECKIN1 = {"schema_version": 1, "kind": "checkin1", "sections": {
    "i": "req", "i-b": "census", "ii": "gallery prose",
    "iii": {"plan": "x", "waypoint": "wp"}, "iv": "budget",
    "v": [{"id": "F1", "text": "assume"}], "vi": ["answer", "ask", "propose"]}}


def test_approve_go_and_advance_dispatch_by_run_kind(tmp_path):
    rd = _run(tmp_path, compute_plan="smoke", task_mode="reproduce")
    (rd / "inputs/checkin1.json").write_text(json.dumps(VALID_CHECKIN1))
    (rd / "inputs/cost_preflight.json").write_text(json.dumps(
        {"schema_version": 1, "generated_by": "cost_preflight.py", "mode": "smoke", "walltime_h": [0.5, 1]}))
    r = _ravel(tmp_path, "approve", "--rundir", rd, "--quote", "GO, approved")
    assert r.returncode == 0, r.stdout + r.stderr
    approval = json.loads((rd / "inputs/checkin1_approval.json").read_text())
    assert approval["approved_plan"] == "smoke" and approval["generated_by"] == "workflow_state.py approve"
    assert (rd / "logs/enforcement-surface.jsonl").is_file()            # fingerprinted at CHECK-IN 1
    r = _ravel(tmp_path, "go", "--rundir", rd, "--quote", "GO")
    assert "scoped" not in r.stderr and "science" not in r.stderr     # native: workflow_state go decides
    scoped = _run(tmp_path, "scoped")
    (scoped / "inputs/scoped-plan.json").write_text("{}")
    for args in (["go", "--rundir", scoped, "--quote", "GO"], ["advance", "--rundir", scoped, "--to", "route"]):
        r = _ravel(tmp_path, *args)
        assert r.returncode == 2 and "scoped run" in r.stderr


def test_lifecycle_commands_are_registered(tmp_path):
    from ravel import cli
    for name in ("gate", "stage", "cost", "trap-sweep"):
        assert name in cli.FOCUSED_COMMANDS
    for name in ("lifecycle", "checkin", "result-pack", "scan", "certify"):
        assert name in cli.LIFECYCLE_COMMANDS
    rd = _run(tmp_path)
    assert _ravel(tmp_path, "lifecycle", "--rundir", rd).returncode == 2        # the sub-command word is required
    r = _ravel(tmp_path, "lifecycle", "check", "--rundir", rd)
    assert r.returncode in (0, 1) and "Traceback" not in r.stderr
    r = _ravel(tmp_path, "checkin", "validate", "--schema")
    assert r.returncode == 0 and json.loads(r.stdout)
    r = _ravel(tmp_path, "scan", "--help")
    assert r.returncode == 0 and "plan" in r.stdout


def test_stop_drive_takes_the_pending_action_from_the_status_packet(tmp_path, monkeypatch):
    from ravel.workflow import current_state, stop_dispatch
    ctx = {"rundir": str(tmp_path), "run_state": {"next_required": {"what": "stale ledger item"}},
           "last_message": "", "is_delivery": False}
    science_child = {"next_required": "Run the first supervised attempt", "execution": {"status": "approved"}}
    monkeypatch.setattr(current_state, "build_packet", lambda rundir: science_child)
    blocked, reason = stop_dispatch.branch_drive(ctx)
    assert blocked and "Run the first supervised attempt" in reason and "stale ledger" not in reason
    monkeypatch.setattr(current_state, "build_packet", lambda rundir: {
        "next_required": "Review and approve exact CHECK-IN 1", "execution": {"status": "planned"}})
    assert stop_dispatch.branch_drive(ctx) == (False, "")             # waiting on a person
    monkeypatch.setattr(current_state, "build_packet", lambda rundir: {
        "next_required": {"kind": "checkin", "what": "CHECK-IN 1"}, "execution": {"status": "absent"}})
    assert stop_dispatch.branch_drive(ctx) == (False, "")
    monkeypatch.setattr(current_state, "build_packet", lambda rundir: {
        "next_required": {"kind": "stage", "what": "generation"}, "execution": {"status": "absent"}})
    assert stop_dispatch.branch_drive(ctx)[0]

    def underivable(rundir):
        raise ValueError("no contract")
    monkeypatch.setattr(current_state, "build_packet", underivable)
    blocked, reason = stop_dispatch.branch_drive(ctx)
    assert blocked and "stale ledger item" in reason                    # fallback: the ledger's item


def test_explicit_launch_of_an_unrecognized_command_still_needs_approval(tmp_path):
    rd = _run(tmp_path, compute_plan="smoke", task_mode="reproduce")
    r = _ravel(tmp_path, "gate", "--rundir", rd, "--action", "launch", "--command", "./my_generator --n 1000", "--json")
    verdict = json.loads(r.stdout)
    assert r.returncode == 2 and any(e["provider"] == "launch_approval" for e in verdict["errors"])

# fail closed, source-backed guards and the B4 merged seam.
@pytest.mark.parametrize('gate', ['checkin2_accept', 'approve_plan', 'correction', 'deviation',
    'research_choice', 'report_integrity', 'unblind', 'spend_above_ceiling', 'launch', 'delivery'])
def test_missing_decision_provider_denies(tmp_path, monkeypatch, capsys, gate):
    from ravel.workflow import host_gate
    monkeypatch.setitem(sys.modules, 'ravel.workflow.decision_gate', None)
    rd = _run(tmp_path)
    assert host_gate.main(['--rundir', str(rd), '--action', gate, '--json']) == 2
    result = json.loads(capsys.readouterr().out)
    error = next(e for e in result['errors'] if e['provider'] == 'decision_gate')
    assert result['decision'] == 'deny' and error['code'] == 'provider_inactive'
    assert error['fix'] == 'install the decision-gate module'

@pytest.mark.parametrize('action,command,code', [
    ('launch', 'python calculate.py', 'no_active_run'),
    ('launch', None, 'no_active_run'), ('delivery', None, 'no_active_run'),
    ('tool_call', GEN_COMMAND, 'pre_intake'),
])
def test_no_run_never_allows_a_gated_action(tmp_path, monkeypatch, action, command, code):
    from ravel.workflow import host_gate
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    result = host_gate.verdict(None, action, command, session_id='absent', cwd=tmp_path, project=tmp_path)
    assert result['decision'] == 'deny'
    assert result['errors'][0]['code'] == code
    assert host_gate.exit_code(result) == (1 if code == 'no_active_run' else 2)


def test_declared_guards_and_host_do_not_establish_evidence(tmp_path, monkeypatch):
    from ravel.workflow import host_governance as hg
    monkeypatch.setenv('RAVEL_PRE_EXECUTION_GUARDS', 'host-hooks')
    monkeypatch.setenv('RAVEL_HOST', 'claude-code')
    for key in ('CLAUDECODE', 'CLAUDE_CODE_SESSION_ID', 'RAVEL_SESSION_ID'):
        monkeypatch.delenv(key, raising=False)
    record = hg.enforcement_record(_run(tmp_path), project=tmp_path)
    assert record['pre_execution_guards'] == 'none' and record['host'] == 'unknown'
    assert record['declared_pre_execution_guards'] == 'host-hooks'
    assert record['declared_host'] == 'claude-code'


def test_missing_raw_launch_provider_is_a_failure(tmp_path, monkeypatch):
    from ravel.workflow import host_governance as hg
    monkeypatch.setitem(sys.modules, 'ravel.workflow.raw_launch', None)
    rd = _run(tmp_path)
    errors = hg.raw_launch_errors(rd)
    assert len(errors) == 1 and errors[0]['code'] == 'provider_inactive'
    assert errors[0]['provider'] == 'raw_launch'
    assert hg.enforcement_record(rd, project=tmp_path)['raw_launch'] == 'fail'

@pytest.mark.parametrize('rel', ['data/transports/claude-cli-oneshot.json',
                                 'workflow/transport_receipt.py'])
def test_package_authority_changes_digest(tmp_path, monkeypatch, rel):
    from ravel.workflow import host_governance as hg
    monkeypatch.setattr(hg, '_package_dir', lambda: tmp_path / 'package')
    path = tmp_path / 'package' / rel
    path.parent.mkdir(parents=True)
    path.write_text('first')
    first = hg.enforcement_surface_sha256(tmp_path)
    path.write_text('second')
    assert hg.enforcement_surface_sha256(tmp_path) != first


def test_shims_and_extension_authority_change_digest(tmp_path, monkeypatch):
    from ravel.workflow import host_governance as hg
    shim = tmp_path / '.codex/ravel-gate.sh'; shim.parent.mkdir(); shim.write_text('first')
    extension = tmp_path / 'roles/card.json'; extension.parent.mkdir(); extension.write_text('first')
    monkeypatch.setattr(hg, 'SURFACE_EXTENSIONS', (lambda project: {'roles/card.json': extension},))
    first = hg.enforcement_surface_sha256(tmp_path)
    shim.write_text('second')
    second = hg.enforcement_surface_sha256(tmp_path)
    assert second != first
    extension.write_text('second')
    assert hg.enforcement_surface_sha256(tmp_path) != second


def test_surface_record_is_append_only_and_middle_tamper_refuses(tmp_path):
    from ravel.workflow import host_governance as hg
    rd = _run(tmp_path)
    source = tmp_path / '.claude/hooks/x.sh'; source.parent.mkdir(parents=True)
    path = rd / hg.CHECKIN1_SURFACE
    for content in ('first', 'second', 'third'):
        old = path.read_bytes() if path.exists() else b''
        source.write_text(content)
        hg.record_checkin1_surface(rd, project=tmp_path)
        assert path.read_bytes().startswith(old)
    rows = hg.checkin1_surface_rows(rd)
    assert len(rows) == 3 and rows[1]['prev_sha256'] == rows[0]['sha256']
    lines = path.read_text().splitlines(); row = json.loads(lines[1]); row['host'] = 'tampered'
    lines[1] = json.dumps(row); path.write_text('\n'.join(lines) + '\n')
    with pytest.raises(ValueError, match='chain'):
        hg.checkin1_surface_rows(rd)
    with pytest.raises(ValueError, match='chain'):
        hg.record_checkin1_surface(rd, project=tmp_path)


def test_science_approval_uses_existing_verifier(tmp_path):
    from test_science_review_envelope import specification
    from ravel.workflow import host_gate, science
    rd, spec = tmp_path / 'run', tmp_path / 'spec.json'
    spec.write_text(json.dumps(specification(tmp_path)))
    science.plan(rd, spec); admit_method(rd); science.approve(rd, 'authorized synthetic software fixture', scripted=True)
    assert (rd / science.APPROVAL).is_file() and not (rd / 'inputs/checkin1_approval.json').exists()
    assert host_gate._approval_errors(rd, None) == []
    assert host_gate._approval_errors(rd, 'scan') == []  # science verifier owns its approved scope
    result = host_gate.verdict(rd, 'launch', 'python calculate.py', project=tmp_path)
    assert not any(e['provider'] == 'launch_approval' for e in result['errors'])


def _real_decision_gate():
    import importlib
    try:
        gate = importlib.import_module('ravel.workflow.decision_gate')
    except ImportError:
        pytest.skip('decision_gate/providers.json is absent from this tree')
    assert Path(gate.__file__).resolve().is_relative_to(REPO / 'src')
    assert (REPO / 'src/ravel/data/gates/providers.json').is_file()
    return gate


def test_real_decision_gate_contractless_run_denies(tmp_path):
    from ravel.workflow import host_gate
    _real_decision_gate()
    rd = tmp_path / 'contractless'; rd.mkdir()
    result = host_gate.verdict(rd, 'delivery', project=tmp_path)
    assert result['decision'] == 'deny'
    assert any(e['code'] == 'gate_inputs_invalid' for e in result['errors'])


def test_epoch_one_native_launch_preserves_legacy_decision(tmp_path, monkeypatch):
    from ravel.workflow import host_gate, workflow_state
    decision_gate = _real_decision_gate()
    rd = _run(tmp_path, compute_plan='smoke', task_mode='reproduce')
    contract = json.loads((rd / 'inputs/task_contract.json').read_text()); contract.pop('agent_layer_epoch', None)
    (rd / 'inputs/task_contract.json').write_text(json.dumps(contract))
    (rd / 'inputs/checkin1.json').write_text(json.dumps(VALID_CHECKIN1))
    (rd / 'inputs/cost_preflight.json').write_text(json.dumps({'schema_version': 1,
        'generated_by': 'cost_preflight.py', 'mode': 'smoke', 'walltime_h': [.5, 1]}))
    assert workflow_state.main(['approve', '--rundir', str(rd), '--quote', 'authorized test fixture']) == 0
    assert decision_gate.check(rd, 'launch', {'kind': 'launch'}) == []
    result = host_gate.verdict(rd, 'launch', 'python calculate.py', project=tmp_path)
    assert result['decision'] == 'allow', result


def test_provider_rows_keep_inactive_and_action_shape(tmp_path, monkeypatch, capsys):
    from ravel.workflow import host_gate
    decision_gate = _real_decision_gate()
    rd = _run(tmp_path)
    original = decision_gate.check; seen = []
    def observe(*args):
        seen.append(args[2]); return original(*args)
    monkeypatch.setattr(decision_gate, 'check', observe)
    for floor in (None, 'R2'):
        args = ['--rundir', str(rd), '--action', 'delivery', '--json']
        if floor: args += ['--floor', floor]
        host_gate.main(args); result = json.loads(capsys.readouterr().out)
        external = decision_gate.providers('delivery')
        assert result['providers'] == external
        assert 'rung' not in seen[-1]
        assert seen[-1].get('floor') == floor
        assert ('floor' in seen[-1]) == (floor is not None)


def test_classified_science_stage_launch_uses_science_approval(tmp_path):
    from test_science_review_envelope import specification
    from ravel.workflow import host_gate, science
    rd, spec = tmp_path / 'run', tmp_path / 'spec.json'
    spec.write_text(json.dumps(specification(tmp_path)))
    science.plan(rd, spec); admit_method(rd)
    science.approve(rd, 'authorized synthetic engineering fixture', scripted=True)
    assert not (rd / 'inputs/task_contract.json').exists()
    for command in ('ravel stage run --rundir run --stage science',
                    'python3 -m ravel.workflow.stage_supervisor --rundir run --stage science'):
        assert host_gate.classify(command) == 'launch'
        assert host_gate.launch_errors(command, rundir=rd, project=tmp_path) == []
        result = host_gate.verdict(rd, 'launch', command, project=tmp_path)
        assert not any(e['provider'] == 'launch_approval' for e in result['errors'])
    assert 'UNSUPERVISED' in host_gate.launch_errors('./bin/generate_events', rundir=rd, project=tmp_path)[0]
    approval = rd / science.APPROVAL
    receipt = json.loads(approval.read_text()); receipt['quote'] = ''
    approval.write_text(json.dumps(receipt))
    assert 'invalid approval' in host_gate.launch_errors('ravel stage run', rundir=rd, project=tmp_path)[0]


def test_missing_provider_is_reported_even_for_nonexistent_run(tmp_path, monkeypatch):
    from ravel.workflow import host_gate
    monkeypatch.setitem(sys.modules, 'ravel.workflow.decision_gate', None)
    result = host_gate.verdict(tmp_path / 'absent', 'launch', project=tmp_path)
    assert {e['code'] for e in result['errors']} == {'no_active_run', 'provider_inactive'}
    assert host_gate.exit_code(result) == 1
