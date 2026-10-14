"""Current state is derived, retains blockers, and never reuses a cached green view."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ravel import cli
from ravel.paths import module_command
from ravel.workflow import current_state, workflow_state, stop_dispatch
from ravel.workflow.state_io import atomic_json, read_json


def initiate(root):
    assert cli.main(["initiate", "--prompt", "Survey ATLAS searches.", "--out", str(root)]) == 0


def test_packet_does_not_trust_cached_next_action_or_authority(tmp_path):
    root = tmp_path / "run"
    initiate(root)
    atomic_json(root / "current_state.json", {"approval": {"valid": True}, "next_required": None})
    state, _ = workflow_state.load_state(root)
    state["next_required"] = None
    workflow_state.write_state(root, state)
    packet = current_state.write_packet(root)
    assert packet["approval"]["valid"] is False
    assert packet["next_required"] is not None
    assert packet["execution"]["status"] == "absent"
    assert packet["sources"]["run_state_revision"] == 2


def test_malformed_execution_is_an_explicit_blocker(tmp_path):
    root = tmp_path / "run"
    initiate(root)
    (root / "execution_state.json").write_text('{"partial":')
    packet = current_state.build_packet(root)
    assert packet["next_required"]["kind"] == "execution"
    assert packet["execution"]["status"] == "invalid"
    assert cli.main(["status", "--rundir", str(root)]) == 1


def test_stale_writer_rejected_and_forced_reset_archived(tmp_path):
    root = tmp_path / "run"
    initiate(root)
    first, _ = workflow_state.load_state(root)
    second, _ = workflow_state.load_state(root)
    first["session_id"] = "retained"
    workflow_state.write_state(root, first)
    with pytest.raises(workflow_state.StateConflict):
        workflow_state.write_state(root, second)
    assert read_json(root / "run_state.json")["session_id"] == "retained"
    assert workflow_state.main(["init", "--rundir", str(root), "--force"]) == 0
    archives = list((root / "logs/state").glob("revision-*.json"))
    assert len(archives) == 1
    assert read_json(archives[0])["state"]["session_id"] == "retained"


def test_concurrent_cli_records_do_not_lose_updates(tmp_path):
    root = tmp_path / "run"
    initiate(root)
    child_env = dict(os.environ)
    child_env.pop("PYTHONPATH", None)
    processes = [subprocess.Popen(module_command("ravel.workflow.workflow_state", "record",
        "--rundir", str(root), "--kind", "edit", "--payload", json.dumps({"path": f"input-{i}.dat"})),
        env=child_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(12)]
    for process in processes:
        out, err = process.communicate(timeout=20)
        assert process.returncode == 0, (out, err)
    state = read_json(root / "run_state.json")
    assert len(state["edits"]) == 12
    assert {e["path"] for e in state["edits"]} == {f"input-{i}.dat" for i in range(12)}
    assert state["revision"] == 13


@pytest.mark.parametrize("value", [{"x": float("nan")}, {"x": float("inf")}, {"x": object()}])
def test_failed_atomic_serialization_preserves_prior_bytes(tmp_path, value):
    target = tmp_path / "state.json"
    target.write_bytes(b'{"retained": true}\n')
    with pytest.raises((ValueError, TypeError)):
        atomic_json(target, value)
    assert target.read_bytes() == b'{"retained": true}\n'


@pytest.mark.parametrize("branch", [stop_dispatch.branch_d18, stop_dispatch.branch_recipe_search,
                                    stop_dispatch.branch_armed_watcher, stop_dispatch.branch_open_defect])
def test_unavailable_applicable_validator_holds_and_records_failure(tmp_path, monkeypatch, branch):
    def unavailable(*args, **kwargs):
        raise OSError("validator runtime unavailable")
    monkeypatch.setattr(stop_dispatch.subprocess, "run", unavailable)
    ctx = {"rundir": str(tmp_path), "repo": str(tmp_path), "last_message": "CHECK-IN 1", "is_delivery": True}
    blocked, reason = branch(ctx)
    assert blocked and "unavailable" in reason
    files = list((tmp_path / "logs").glob("gate-*.failure.json"))
    assert len(files) == 1 and read_json(files[0])["status"] == "open"


def test_archived_failures_are_not_live_failures(tmp_path):
    atomic_json(tmp_path / "logs/execution/fit/old/prior.failure.json", {"status": "open"})
    assert stop_dispatch.branch_catch({"rundir": str(tmp_path)}) == (False, "")


def test_recent_log_does_not_prove_current_process_liveness(tmp_path):
    from ravel.workflow.execution import process_identity
    log = tmp_path / "recent.log"
    log.write_text('finished')
    ctx = {"rundir": str(tmp_path), "run_state": {"compute_launched": [{"logfile": str(log)}]},
           "last_message": "The simulation is running in the background."}
    assert stop_dispatch.branch_phantom(ctx)[0] is True
    proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        ctx['run_state']['compute_launched'][0].update(pid=proc.pid, process_identity=process_identity(proc.pid))
        assert stop_dispatch.branch_phantom(ctx)[0] is False
        ctx['run_state']['compute_launched'][0]['process_identity'] = 'different start identity'
        assert stop_dispatch.branch_phantom(ctx)[0] is True
    finally:
        proc.terminate(); proc.wait()
    assert stop_dispatch.branch_phantom(ctx)[0] is True
