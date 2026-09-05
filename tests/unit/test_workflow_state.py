"""workflow_state.py -- the live per-run state machine / keystone ledger (Phase 1).

Import by file path (repo-root py.py shadows the real py package on sys.path). Run from /tmp:
    cd /tmp && python3 -m pytest <abspath> -q
Later Phase-1 tasks (1.3 record, 1.4 advance, 1.5 status/next/require) APPEND test functions
to this file.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKFLOW_STATE_PY = REPO / "src" / "ravel" / "workflow" / "workflow_state.py"

_SURVEY_CONTRACT = {
    "schema_version": 1,
    "prompt": "selftest", "task_mode": "survey", "detector_mode": "particle-level",
    "stat_mode": "none-survey", "required_user_inputs": [], "assumptions": ["fixture"],
    "compute_plan": "none", "approval_required": True,
}


def _load():
    spec = importlib.util.spec_from_file_location("workflow_state_under_test", WORKFLOW_STATE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_run(tmp_path, contract=None):
    rd = tmp_path / "run"
    (rd / "inputs").mkdir(parents=True)
    (rd / "inputs" / "task_contract.json").write_text(json.dumps(contract or _SURVEY_CONTRACT))
    return rd


def test_selftest_passes():
    r = subprocess.run([sys.executable, str(WORKFLOW_STATE_PY), "--selftest"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "selftest:" in r.stdout
    assert "SELFTEST FAIL" not in r.stderr
    assert r.stdout.count("  FAIL\n") == 0


def test_init_writes_full_schema(tmp_path):
    mod = _load()
    rd = _make_run(tmp_path)
    assert mod.main(["init", "--rundir", str(rd), "--session-id", "S1"]) == 0
    state = json.loads((rd / "run_state.json").read_text())
    assert state["schema_version"] == 1
    assert state["generated_by"] == "workflow_state.py"
    assert len(state["input_fingerprint"]) == 64
    assert state["session_id"] == "S1"
    assert state["task_mode"] == "survey" and state["compute_plan"] == "none"
    assert state["routed"] is False and state["current_step"] is None
    for k in mod.LIST_KEYS:
        assert state[k] == [], k
    assert state["next_required"] is None


def test_init_refuses_to_clobber(tmp_path):
    mod = _load()
    rd = _make_run(tmp_path)
    assert mod.main(["init", "--rundir", str(rd)]) == 0
    assert mod.main(["init", "--rundir", str(rd)]) == 3          # already exists
    assert mod.main(["init", "--rundir", str(rd), "--force"]) == 0


def test_init_bad_contract_exits_3(tmp_path):
    mod = _load()
    rd = tmp_path / "run"
    (rd / "inputs").mkdir(parents=True)
    (rd / "inputs" / "task_contract.json").write_text(json.dumps({"task_mode": "survey"}))  # invalid
    assert mod.main(["init", "--rundir", str(rd)]) == 3


def test_init_not_a_dir_exits_2(tmp_path):
    mod = _load()
    assert mod.main(["init", "--rundir", str(tmp_path / "nope")]) == 2


def test_record_appends_each_kind(tmp_path):
    mod = _load()
    rd = _make_run(tmp_path)
    assert mod.main(["init", "--rundir", str(rd)]) == 0
    assert mod.main(["record", "--rundir", str(rd), "--kind", "skill",
                     "--payload", json.dumps({"skill": "physicist-intake"})]) == 0
    assert mod.main(["record", "--rundir", str(rd), "--kind", "compute",
                     "--payload", json.dumps({"cmd": "mg5_aMC run.mg5", "bg_kind": "harness",
                                              "bg_id": "bg7", "supervised": True})]) == 0
    assert mod.main(["record", "--rundir", str(rd), "--kind", "edit",
                     "--payload", json.dumps({"path": "inputs/param_card.dat"})]) == 0
    assert mod.main(["record", "--rundir", str(rd), "--kind", "subagent",
                     "--payload", json.dumps({"agent_type": "physics-reviewer"})]) == 0
    st = json.loads((rd / "run_state.json").read_text())
    assert [e["skill"] for e in st["skills_invoked"]] == ["physicist-intake"]
    c = st["compute_launched"][0]
    assert c["cmd"] == "mg5_aMC run.mg5" and c["bg_kind"] == "harness" and c["supervised"] is True
    assert set(("logfile", "done_condition", "next_action")) <= set(c)      # N6 fields present (null ok)
    assert st["edits"][0]["path"] == "inputs/param_card.dat"
    assert st["subagents"][0]["agent_type"] == "physics-reviewer"
    assert all("utc" in e for e in st["skills_invoked"] + st["compute_launched"])


def test_record_bad_payload_exits_2(tmp_path):
    mod = _load()
    rd = _make_run(tmp_path)
    assert mod.main(["init", "--rundir", str(rd)]) == 0
    assert mod.main(["record", "--rundir", str(rd), "--kind", "skill", "--payload", "not-json"]) == 2
    assert mod.main(["record", "--rundir", str(rd), "--kind", "edit",
                     "--payload", json.dumps({"nopath": 1})]) == 2       # missing required field


def test_record_missing_state_exits_3(tmp_path):
    mod = _load()
    rd = _make_run(tmp_path)                       # no init -> no run_state.json
    assert mod.main(["record", "--rundir", str(rd), "--kind", "skill",
                     "--payload", json.dumps({"skill": "x"})]) == 3


def test_find_active_rundir_picks_newest(tmp_path):
    mod = _load()
    proj = tmp_path / "proj"
    (proj / "trial-runs").mkdir(parents=True)
    assert mod.find_active_rundir(str(proj)) is None
    a = proj / "trial-runs" / "runA"
    (a / "inputs").mkdir(parents=True)
    (a / "inputs" / "task_contract.json").write_text(json.dumps(_SURVEY_CONTRACT))
    assert mod.main(["init", "--rundir", str(a)]) == 0
    _live_lock(a)                                    # CR-135: resolution requires the ownership mark
    assert mod.find_active_rundir(str(proj)) == str(a)


def test_record_project_dir_noop_when_no_run(tmp_path):
    mod = _load()
    proj = tmp_path / "proj"
    (proj / "trial-runs").mkdir(parents=True)
    # observer path: no active run yet -> record must never error (would block the tool)
    assert mod.main(["record", "--project-dir", str(proj), "--kind", "skill",
                     "--payload", json.dumps({"skill": "x"})]) == 0


def test_record_route_and_failure_mutate_state(tmp_path):
    mod = _load()
    rd = _make_run(tmp_path)
    assert mod.main(["init", "--rundir", str(rd)]) == 0
    st0 = json.loads((rd / "run_state.json").read_text())
    assert st0["routed"] is False and st0["open_failure_records"] == []
    # route (state-mutator): flips `routed` and leaves an audit entry. --what carries the route id.
    assert mod.main(["record", "--rundir", str(rd), "--kind", "route", "--what", "reproduce"]) == 0
    # failure (state-mutator): appends the failure.json relpath; a repeat is de-duped.
    assert mod.main(["record", "--rundir", str(rd), "--kind", "failure",
                     "--what", "logs/gen.failure.json"]) == 0
    assert mod.main(["record", "--rundir", str(rd), "--kind", "failure",
                     "--what", "logs/gen.failure.json"]) == 0
    st = json.loads((rd / "run_state.json").read_text())
    assert st["routed"] is True
    assert st["open_failure_records"] == ["logs/gen.failure.json"]
    assert [a.get("what") for a in st["routes"]] == ["reproduce"]
    # a failure record with no relpath is a usage error (exit 2), never a silent pass
    assert mod.main(["record", "--rundir", str(rd), "--kind", "failure", "--payload", "{}"]) == 2
    # a bare `record --kind route` is a silent NO-OP -- see test_record_route_without_content_is_noop


def test_record_route_without_content_is_noop(tmp_path):
    """CR-135 regression (the {"utc": ""} noise class): a route record whose payload carries no
    routing content (no route/next/what) must not touch the ledger AT ALL -- no routed flip, no
    audit row, no rewrite (a rewrite refreshes mtime and feeds the stale-'active' loop)."""
    mod = _load()
    rd = _make_run(tmp_path)
    assert mod.main(["init", "--rundir", str(rd)]) == 0
    before = (rd / "run_state.json").read_bytes()
    assert mod.main(["record", "--rundir", str(rd), "--kind", "route"]) == 0
    assert mod.main(["record", "--rundir", str(rd), "--kind", "route", "--payload", "{}"]) == 0
    after = (rd / "run_state.json").read_bytes()
    assert after == before                        # byte-identical: nothing recorded, nothing rewritten
    st = json.loads(after)
    assert st["routed"] is False and "routes" not in st


def _project_with_init_run(tmp_path, name="runA"):
    proj = tmp_path / "proj"
    rd = proj / "trial-runs" / name
    (rd / "inputs").mkdir(parents=True)
    (rd / "inputs" / "task_contract.json").write_text(json.dumps(_SURVEY_CONTRACT))
    mod = _load()
    assert mod.main(["init", "--rundir", str(rd)]) == 0
    return mod, proj, rd


def _live_lock(rd, owner="T"):
    import datetime as _dt
    now = _dt.datetime.now().isoformat(timespec="seconds")
    (rd / "SESSION.lock").write_text(json.dumps(
        {"owner": owner, "acquired": now, "renewed": now, "history": []}))


def test_find_active_rundir_requires_live_lock(tmp_path):
    """CR-135: --project-dir auto-resolution requires the CR-022 ownership mark -- a run without a
    live SESSION.lock is never auto-resolved, however fresh its ledger's mtime. (An mtime-freshness
    rule is unsound: ANY maintenance write to a stale ledger -- even the noise-scrub itself --
    resurrects it, and each misdirected append then keeps it fresh forever.)"""
    mod, proj, rd = _project_with_init_run(tmp_path)
    assert mod.find_active_rundir(str(proj)) is None                 # fresh ledger, no lock -> None
    before = (rd / "run_state.json").read_bytes()
    assert mod.main(["record", "--project-dir", str(proj), "--kind", "route",
                     "--what", "reproduce"]) == 0                    # best-effort no-op, never an error
    assert (rd / "run_state.json").read_bytes() == before
    _live_lock(rd)
    assert mod.find_active_rundir(str(proj)) == str(rd)              # live lock -> resolves


def test_find_active_rundir_skips_closed_runs(tmp_path):
    """CR-135: a rundir with a RESULT.md is CLOSED -- never auto-resolved, even if a live
    SESSION.lock was left behind (e.g. a close that forgot the release)."""
    mod, proj, rd = _project_with_init_run(tmp_path)
    _live_lock(rd)
    (rd / "RESULT.md").write_text("# closed\n")
    assert mod.find_active_rundir(str(proj)) is None


def test_find_active_rundir_stale_lock_is_dead(tmp_path):
    """CR-135: a SESSION.lock with no heartbeat past session_lock's staleness window counts as
    dead (crash-tolerant, same rule as session_lock itself) -- the run is not auto-resolved."""
    import datetime as _dt
    mod, proj, rd = _project_with_init_run(tmp_path)
    old = (_dt.datetime.now() - _dt.timedelta(hours=48)).isoformat(timespec="seconds")
    (rd / "SESSION.lock").write_text(json.dumps(
        {"owner": "T", "acquired": old, "renewed": old, "history": []}))
    assert mod.find_active_rundir(str(proj)) is None


def test_find_active_rundir_live_lock_beats_stale_mtime(tmp_path):
    """CR-135: a live SESSION.lock marks the run active even when the ledger itself is quiet
    (e.g. a long compute stage with no ledger appends)."""
    import os as _os
    import time as _time
    mod, proj, rd = _project_with_init_run(tmp_path)
    old = _time.time() - 48 * 3600.0
    _os.utime(str(rd / "run_state.json"), (old, old))
    _live_lock(rd)
    assert mod.find_active_rundir(str(proj)) == str(rd)


def test_find_active_rundir_prefers_cwd_rundir(tmp_path, monkeypatch):
    """CR-135: a session whose cwd is INSIDE a trial-runs rundir means THAT run, even if closed
    (e.g. backfilling a closed run's records) and even when another run holds a live lock."""
    mod, proj, rd_a = _project_with_init_run(tmp_path, "runA")
    (rd_a / "RESULT.md").write_text("# closed\n")
    rd_b = proj / "trial-runs" / "runB"
    (rd_b / "inputs").mkdir(parents=True)
    (rd_b / "inputs" / "task_contract.json").write_text(json.dumps(_SURVEY_CONTRACT))
    assert mod.main(["init", "--rundir", str(rd_b)]) == 0
    _live_lock(rd_b)                                                 # runB is the live run
    sub = rd_a / "outputs"
    sub.mkdir()
    monkeypatch.chdir(sub)
    assert mod.find_active_rundir(str(proj)) == str(rd_a)


def test_advance_allows_first_precondition_and_refuses_out_of_order(tmp_path):
    mod = _load()
    rd = _make_run(tmp_path)                        # survey; only inputs/task_contract.json present
    assert mod.main(["init", "--rundir", str(rd)]) == 0
    # resource_census's predecessor prefix (task_contract) PASSes -> advance allowed
    assert mod.main(["advance", "--rundir", str(rd), "--to", "resource_census"]) == 0
    st = json.loads((rd / "run_state.json").read_text())
    assert st["current_step"] == "resource_census"
    assert st["next_required"] is not None and "what" in st["next_required"]
    # route's predecessor prefix requires resource_census + trap_sweep (both R, both missing) -> REFUSE
    assert mod.main(["advance", "--rundir", str(rd), "--to", "route"]) == 1


def test_advance_json_reports_blockers(tmp_path):
    mod = _load()
    rd = _make_run(tmp_path)
    assert mod.main(["init", "--rundir", str(rd)]) == 0
    # capture the --json refusal payload
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main(["advance", "--rundir", str(rd), "--to", "route", "--json"])
    assert rc == 1
    payload = json.loads(buf.getvalue())
    assert payload["advanced"] is False and payload["target"] == "route"
    assert any("resource_census" in b for b in payload["blockers"])


def test_advance_missing_state_exits_3(tmp_path):
    mod = _load()
    rd = _make_run(tmp_path)                        # no init
    assert mod.main(["advance", "--rundir", str(rd), "--to", "resource_census"]) == 3


def test_require_skill_gate(tmp_path):
    mod = _load()
    rd = _make_run(tmp_path)
    assert mod.main(["init", "--rundir", str(rd)]) == 0
    assert mod.main(["require", "--rundir", str(rd), "--kind", "skill",
                     "--what", "physicist-intake"]) == 1                 # not yet invoked
    assert mod.main(["record", "--rundir", str(rd), "--kind", "skill",
                     "--payload", json.dumps({"skill": "physicist-intake"})]) == 0
    assert mod.main(["require", "--rundir", str(rd), "--kind", "skill",
                     "--what", "physicist-intake"]) == 0                 # now satisfied


def test_require_artifact_and_command(tmp_path):
    mod = _load()
    rd = _make_run(tmp_path)
    assert mod.main(["init", "--rundir", str(rd)]) == 0
    assert mod.main(["require", "--rundir", str(rd), "--kind", "artifact",
                     "--what", "inputs/task_contract.json"]) == 0
    assert mod.main(["require", "--rundir", str(rd), "--kind", "artifact",
                     "--what", "inputs/nope.json"]) == 1
    assert mod.main(["record", "--rundir", str(rd), "--kind", "compute",
                     "--payload", json.dumps({"cmd": "mg5_aMC run.mg5"})]) == 0
    assert mod.main(["require", "--rundir", str(rd), "--kind", "command", "--what", "mg5_aMC"]) == 0
    assert mod.main(["require", "--rundir", str(rd), "--kind", "command", "--what", "rivet"]) == 1


def test_require_stage_gate(tmp_path):
    mod = _load()
    rd = _make_run(tmp_path)
    assert mod.main(["init", "--rundir", str(rd)]) == 0
    assert mod.main(["require", "--rundir", str(rd), "--kind", "stage",
                     "--what", "task_contract"]) == 0                    # prefix passes
    assert mod.main(["require", "--rundir", str(rd), "--kind", "stage", "--what", "route"]) == 1


def test_status_and_next_json(tmp_path):
    mod = _load()
    rd = _make_run(tmp_path)
    assert mod.main(["init", "--rundir", str(rd)]) == 0
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert mod.main(["status", "--rundir", str(rd), "--json"]) == 0
    assert json.loads(buf.getvalue())["task_mode"] == "survey"
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        assert mod.main(["next", "--rundir", str(rd), "--json"]) == 0
    nxt = json.loads(buf2.getvalue())
    assert nxt is None or nxt["what"] in ("resource_census", "trap_sweep", "route", "basis_manifest")
