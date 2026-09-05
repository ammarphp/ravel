"""Real short processes exercise interruption, stale dependencies and output integrity."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from ravel.workflow import execution
from ravel.workflow.stage_supervisor import supervise


def run(root, name, code, *, inputs=(), outputs=(), parents=(), **kwargs):
    return supervise(name, root, 1, f"logs/{name}.log", [sys.executable, "-c", code],
                     inputs=list(inputs), outputs=list(outputs), depends_on=list(parents),
                     cwd=str(root), resume=True, poll=0.02, grace=0.1, kill_secs=4, **kwargs)


def test_resume_uses_valid_receipts_and_invalidates_descendants(tmp_path):
    (tmp_path / "input.json").write_text('{"value": 2}')
    first = "import shutil; shutil.copyfile('input.json', 'selected.json')"
    second = "import json; x=json.load(open('selected.json')); json.dump({'value':x['value']*3},open('result.json','w'))"
    assert run(tmp_path, "select", first, inputs=["input.json"], outputs=["selected.json"]) == 0
    assert run(tmp_path, "fit", second, inputs=["selected.json"], outputs=["result.json"], parents=["select"]) == 0
    state = execution.load_execution(tmp_path)
    attempt = state["stages"]["fit"]["attempt_id"]
    assert run(tmp_path, "fit", second, inputs=["selected.json"], outputs=["result.json"], parents=["select"]) == 0
    assert execution.load_execution(tmp_path)["stages"]["fit"]["attempt_id"] == attempt
    (tmp_path / "input.json").write_text('{"value": 7}')
    assert any("inputs changed" in e for e in execution.validate_execution(tmp_path))
    with pytest.raises(ValueError, match="inputs changed"):
        run(tmp_path, "fit", second, inputs=["selected.json"], outputs=["result.json"], parents=["select"])
    assert run(tmp_path, "select", first, inputs=["input.json"], outputs=["selected.json"]) == 0
    assert execution.stage_errors(tmp_path, "fit")
    assert run(tmp_path, "fit", second, inputs=["selected.json"], outputs=["result.json"], parents=["select"]) == 0
    assert json.loads((tmp_path / "result.json").read_text()) == {"value": 21}
    assert execution.validate_execution(tmp_path) == []
    prior = list((tmp_path / "logs/execution/fit").glob("*/prior_outputs/0/result.json"))
    assert len(prior) == 1 and json.loads(prior[0].read_text()) == {"value": 6}


@pytest.mark.parametrize("contents", ['{"x":', '{"x":NaN}', '{"x":1e999}', '{"x":1,"x":2}', ''])
def test_successful_exit_with_invalid_output_is_failed(tmp_path, contents):
    assert run(tmp_path, "fit", f"open('result.json','w').write({contents!r})", outputs=["result.json"]) == 3
    state = execution.load_execution(tmp_path)["stages"]["fit"]
    assert state["status"] == "failed"
    assert execution.validate_execution(tmp_path)
    assert (tmp_path / "result.json").read_text() == contents


def test_failed_child_retry_preserves_partial_evidence(tmp_path):
    bad = "import sys; open('result.json','w').write('{'); sys.exit(17)"
    assert run(tmp_path, "fit", bad, outputs=["result.json"]) == 17
    failed = execution.load_execution(tmp_path)["stages"]["fit"]
    good = "open('result.json','w').write('{\"limit\":1}')"
    assert run(tmp_path, "fit", good, outputs=["result.json"]) == 0
    assert json.loads((tmp_path / failed["attempt_record"]).read_text())["status"] == "failed"
    assert any(p.read_text() == "{" for p in (tmp_path / "logs/execution/fit").glob("*/prior_outputs/0/result.json"))
    assert json.loads((tmp_path / "logs/fit.failure.json").read_text())["status"] == "resolved"
    assert list((tmp_path / "logs/execution/fit").glob("*/prior.failure.json"))


def test_input_change_during_execution_prevents_success(tmp_path):
    (tmp_path / "input.txt").write_text("before")
    code = "open('input.txt','w').write('after'); open('result.json','w').write('{}')"
    assert run(tmp_path, "fit", code, inputs=["input.txt"], outputs=["result.json"]) == 3
    assert "inputs changed" in execution.load_execution(tmp_path)["stages"]["fit"]["error"]


def test_changed_output_or_command_is_not_reused(tmp_path):
    code = "open('result.json','w').write('{\"a\":1}')"
    assert run(tmp_path, "fit", code, outputs=["result.json"]) == 0
    old = execution.load_execution(tmp_path)["stages"]["fit"]["attempt_id"]
    (tmp_path / "result.json").write_text('{"a":999}')
    assert execution.stage_errors(tmp_path, "fit")
    assert run(tmp_path, "fit", code, outputs=["result.json"]) == 0
    assert execution.load_execution(tmp_path)["stages"]["fit"]["attempt_id"] != old
    assert run(tmp_path, "fit", code.replace(":1", ":2"), outputs=["result.json"]) == 0
    assert json.loads((tmp_path / "result.json").read_text()) == {"a": 2}


def test_quiet_valid_work_is_not_a_default_stall(tmp_path):
    code = "import time; time.sleep(.15); open('result.json','w').write('{}')"
    assert run(tmp_path, "analysis", code, outputs=["result.json"]) == 0


def test_different_stage_cannot_steal_an_output(tmp_path):
    code = "open('result.json','w').write('{}')"
    assert run(tmp_path, "first", code, outputs=["result.json"]) == 0
    with pytest.raises(ValueError, match="already owned"):
        run(tmp_path, "other", code, outputs=["result.json"])
    assert execution.stage_errors(tmp_path, "first") == []


def test_nested_outputs_and_directory_input_mutation_are_rejected(tmp_path):
    (tmp_path / "source").mkdir()
    (tmp_path / "source/in.txt").write_text("original")
    with pytest.raises(ValueError, match="overlap"):
        run(tmp_path, "stage", "print('never')", outputs=["out", "out/file.json"])
    with pytest.raises(ValueError, match="overwrite"):
        run(tmp_path, "stage", "print('never')", inputs=["source"], outputs=["source/result.json"])


def test_directory_symlink_cannot_hide_from_fingerprint(tmp_path):
    (tmp_path / "source").mkdir()
    (tmp_path / "source/in.txt").write_text("original")
    (tmp_path / "outside").mkdir()
    (tmp_path / "source/link").symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        execution.snapshot(tmp_path, ["source"])


def test_runtime_change_invalidates_receipt(tmp_path, monkeypatch):
    assert run(tmp_path, "fit", "open('result.json','w').write('{}')", outputs=["result.json"]) == 0
    monkeypatch.setenv("OMP_NUM_THREADS", "123")
    assert any("runtime changed" in e for e in execution.stage_errors(tmp_path, "fit"))


def test_leader_exit_does_not_certify_while_descendant_can_write(tmp_path):
    child = "import time; time.sleep(.4); open('result.json','w').write('{\"changed\":true}')"
    code = f"import subprocess,sys; subprocess.Popen([sys.executable,'-c',{child!r}]); open('result.json','w').write('{{}}')"
    assert run(tmp_path, "fit", code, outputs=["result.json"]) == 3
    state = execution.load_execution(tmp_path)["stages"]["fit"]
    assert "descendants" in state["error"]
    assert execution.process_group_members(state["child_pid"]) == []
    assert (tmp_path / "result.json").read_text() == '{}'


@pytest.mark.parametrize("log", ["result.json", "inputs/request.log", "run_state.json", "logs/state/control.log"])
def test_log_cannot_overwrite_science_or_control_files(tmp_path, log):
    (tmp_path / "result.json").write_text('{}')
    with pytest.raises(ValueError, match="stage log"):
        supervise("other", tmp_path, 1, log, [sys.executable, "-c", "print('changed')"], cwd=str(tmp_path))
    assert (tmp_path / "result.json").read_text() == '{}'


def test_log_paths_are_owned_across_stages(tmp_path):
    assert run(tmp_path, "fit", "print('retained')") == 0
    before = (tmp_path / "logs/fit.log").read_bytes()
    with pytest.raises(ValueError, match="already owned"):
        supervise("other", tmp_path, 1, "logs/fit.log", [sys.executable, "-c", "print('changed')"], cwd=str(tmp_path))
    assert (tmp_path / "logs/fit.log").read_bytes() == before


def wait_for(path, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size:
            return
        time.sleep(.02)
    raise AssertionError(f"process did not create {path}")


def spawn_supervisor(root):
    from ravel.paths import module_command
    code = ("import os,time; open('child.pid','w').write(str(os.getpid())); "
            "open('partial.txt','w').write('started'); time.sleep(60)")
    child_env = dict(os.environ)
    child_env.pop("PYTHONPATH", None)
    return subprocess.Popen(module_command("ravel.workflow.stage_supervisor",
        "--stage", "fit", "--rundir", str(root), "--cwd", str(root),
        "--log", "logs/fit.log", "--output", "partial.txt", "--kill-secs", "30", "--resume",
        "--", sys.executable, "-c", code), env=child_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def test_concurrent_same_stage_is_rejected_and_term_records_failure(tmp_path):
    proc = spawn_supervisor(tmp_path)
    try:
        wait_for(tmp_path / "child.pid")
        with pytest.raises(ValueError, match="another process"):
            run(tmp_path, "fit", "print('must not run')")
        proc.terminate()
        proc.communicate(timeout=5)
        assert proc.returncode == 130
        assert execution.load_execution(tmp_path)["stages"]["fit"]["status"] == "failed"
    finally:
        if proc.poll() is None:
            proc.kill(); proc.wait()


def test_hard_killed_supervisor_recovers_owned_orphan_on_resume(tmp_path):
    proc = spawn_supervisor(tmp_path)
    child = None
    try:
        wait_for(tmp_path / "child.pid")
        child = int((tmp_path / "child.pid").read_text())
        deadline = time.monotonic() + 5
        while not execution.load_execution(tmp_path)["stages"]["fit"].get("child_identity"):
            assert time.monotonic() < deadline
            time.sleep(.02)
        proc.kill(); proc.wait(timeout=5)
        assert run(tmp_path, "fit", "open('partial.txt','w').write('recovered')", outputs=["partial.txt"]) == 0
        statuses = [json.loads(p.read_text())["status"] for p in (tmp_path / "logs/execution/fit").glob("*/record.json")]
        assert sorted(statuses) == ["interrupted", "succeeded"]
        assert any(p.read_text() == "started" for p in (tmp_path / "logs/execution/fit").glob("*/prior_outputs/0/partial.txt"))
    finally:
        if proc.poll() is None:
            proc.kill(); proc.wait()
        if child:
            try: os.killpg(child, signal.SIGKILL)
            except ProcessLookupError: pass


def test_missing_or_cyclic_parent_fails_before_launch(tmp_path):
    with pytest.raises(ValueError, match="no receipt"):
        run(tmp_path, "fit", "print('not run')", parents=["missing"])
    with pytest.raises(ValueError, match="dependencies"):
        run(tmp_path, "fit", "print('not run')", parents=["fit"])
    assert not (tmp_path / "execution_state.json").exists()


def test_output_cannot_overwrite_input_or_escape_run(tmp_path):
    (tmp_path / "input.txt").write_text("original")
    with pytest.raises(ValueError, match="overwrite"):
        run(tmp_path, "fit", "print('not run')", inputs=["input.txt"], outputs=["input.txt"])
    with pytest.raises(ValueError, match="inside"):
        run(tmp_path, "fit", "print('not run')", outputs=["../outside.json"])
    assert (tmp_path / "input.txt").read_text() == "original"


def test_malformed_ledger_never_disappears_into_legacy_mode(tmp_path):
    (tmp_path / "execution_state.json").write_text('{"schema_version":')
    assert execution.validate_execution(tmp_path)
    with pytest.raises(ValueError):
        run(tmp_path, "fit", "print('not run')")
