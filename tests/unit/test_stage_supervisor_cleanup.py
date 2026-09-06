"""No live signals: exercise durable failures against a fully mocked process group."""
import errno
import json
import signal
import subprocess
import sys

import pytest

from ravel.workflow import execution, stage_supervisor as supervisor


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        self.now += .01
        return self.now

    def sleep(self, duration):
        assert 0 < duration <= .1
        self.now += duration


class Child:
    pid = 34567

    def __init__(self, code=None):
        self.returncode = code
        self.waits = []
        self.wait_error = None

    def poll(self):
        return self.returncode

    def wait(self, *, timeout):
        assert 0 < timeout <= .2  # No unbounded or accidentally extended wait.
        self.waits.append(timeout)
        if self.wait_error:
            raise self.wait_error
        if self.returncode is None:
            raise subprocess.TimeoutExpired("mock-child", timeout)
        return self.returncode


@pytest.fixture
def controls(monkeypatch):
    clock, child = Clock(), Child()
    monkeypatch.setattr(supervisor.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(supervisor.time, "sleep", clock.sleep)
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *a, **k: child)
    monkeypatch.setattr(supervisor.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(supervisor.signal, "signal", lambda *a: signal.SIG_DFL)
    monkeypatch.setattr(execution.platform, "platform", lambda: "mock-platform")
    monkeypatch.setattr(execution, "process_identity", lambda pid: "mock-owned-identity")
    monkeypatch.setattr(execution, "process_group_members", lambda pid: [child.pid])
    monkeypatch.setattr(supervisor.os, "getpgid", lambda pid: pid)

    def no_unmocked_signal(*args):
        pytest.fail("test attempted an unconfigured signal")

    monkeypatch.setattr(supervisor.os, "killpg", no_unmocked_signal)
    return clock, child


def launch(root, **kwargs):
    options = {"cwd": str(root), "kill_secs": .05, "poll": .02, "grace": .2}
    options.update(kwargs)
    return supervisor.supervise("fit", root, 1, "logs/fit.log",
        [sys.executable, "-c", "print('mocked, never executed')"],
        **options)


def record(root):
    value = execution.load_execution(root)["stages"]["fit"]
    assert json.loads((root / value["attempt_record"]).read_text()) == value
    if "cleanup" in value:
        assert value["cleanup"]["census_scope"] == supervisor.CLEANUP_CENSUS_SCOPE
    return value


@pytest.mark.parametrize("denied", [signal.SIGTERM, signal.SIGKILL])
@pytest.mark.parametrize("leader_exits", [False, True])
def test_timeout_signal_denial_still_finalizes_original_failure(tmp_path, monkeypatch, controls, denied, leader_exits):
    clock, child = controls
    signals = []

    def kill(pid, sig):
        signals.append(sig)
        if leader_exits:
            child.returncode = 0
        if sig == denied:
            raise PermissionError(errno.EPERM, "mock permission denied")

    monkeypatch.setattr(supervisor.os, "killpg", kill)
    assert launch(tmp_path) == 124
    result = record(tmp_path)
    assert result["status"] == "failed" and result["error"] == "wall-clock"
    assert "receipt_sha256" not in result and "output_snapshot" not in result
    assert signals == ([signal.SIGTERM] if denied == signal.SIGTERM else [signal.SIGTERM, signal.SIGKILL])
    assert result["cleanup"]["signals"][-1]["outcome"] == "error"
    assert any(e["type"] == "PermissionError" for e in result["cleanup"]["errors"])
    assert result["cleanup"]["requires_recovery"] is True
    failure = json.loads((tmp_path / "logs/fit.failure.json").read_text())
    assert failure["reason"] == "wall-clock" and failure["cleanup"] == result["cleanup"]
    assert clock.now < 1 and child.waits == [.2]


def test_not_found_signal_requires_observation_not_assumed_success(tmp_path, monkeypatch, controls):
    clock, child = controls
    queried = 0

    def members(pid):
        nonlocal queried
        queried += 1
        return [pid] if queried == 1 else []

    monkeypatch.setattr(execution, "process_group_members", members)
    def vanished(pid, sig):
        child.returncode = -15
        raise ProcessLookupError(errno.ESRCH, "gone")
    monkeypatch.setattr(supervisor.os, "killpg", vanished)
    assert launch(tmp_path) == 124
    result = record(tmp_path)
    assert result["error"] == "wall-clock"
    assert result["cleanup"]["signals"] == [{"signal": "SIGTERM", "outcome": "not_found"}]
    assert result["cleanup"]["group_state"] == "empty"
    assert result["cleanup"]["requires_recovery"] is False


@pytest.mark.parametrize("cleanup_error", [PermissionError("unexpected cleanup"), KeyboardInterrupt("second signal")])
def test_cleanup_exception_is_not_recursively_retried(tmp_path, monkeypatch, controls, cleanup_error):
    calls = []
    def cleanup(proc, grace):
        calls.append(proc.pid)
        raise cleanup_error
    monkeypatch.setattr(supervisor, "_terminate_group", cleanup)
    assert launch(tmp_path) == 124
    result = record(tmp_path)
    assert calls == [controls[1].pid]
    assert result["error"] == "wall-clock"
    assert result["cleanup"]["group_state"] == "unknown"
    assert result["cleanup"]["errors"][0]["type"] == type(cleanup_error).__name__


def test_clean_child_with_query_failure_cannot_be_certified(tmp_path, monkeypatch, controls):
    controls[1].returncode = 0
    def unreadable(pid):
        raise PermissionError("process census denied")
    monkeypatch.setattr(execution, "process_group_members", unreadable)
    assert launch(tmp_path) == 2
    result = record(tmp_path)
    assert result["status"] == "failed" and "census denied" in result["error"]
    assert result["cleanup"]["group_state"] == "unknown"
    assert result["cleanup"]["signals"] == []
    assert result["cleanup"]["requires_recovery"] is True


def test_zero_exit_with_live_descendants_is_failed_even_if_cleanup_works(tmp_path, monkeypatch, controls):
    child = controls[1]
    child.returncode = 0
    members = [child.pid + 1]
    monkeypatch.setattr(execution, "process_group_members", lambda pid: list(members))
    def kill(pid, sig):
        members.clear()
    monkeypatch.setattr(supervisor.os, "killpg", kill)
    assert launch(tmp_path) == 3
    result = record(tmp_path)
    assert "descendants" in result["error"]
    assert result["cleanup"]["leader_returncode"] == 0
    assert result["cleanup"]["group_state"] == "empty"


def test_successful_group_signal_is_not_proof_of_empty_group(tmp_path, monkeypatch, controls):
    monkeypatch.setattr(supervisor.os, "killpg", lambda pid, sig: None)
    assert launch(tmp_path) == 124
    result = record(tmp_path)
    assert [a["outcome"] for a in result["cleanup"]["signals"]] == ["sent", "sent"]
    assert result["cleanup"]["group_state"] == "active"
    assert result["cleanup"]["requires_recovery"] is True
    assert controls[0].now < 1


@pytest.mark.parametrize("error", [OSError("wait failed"), KeyboardInterrupt("wait interrupted")])
def test_wait_error_preserves_failure_and_requires_recovery(tmp_path, monkeypatch, controls, error):
    monkeypatch.setattr(execution, "process_group_members", lambda pid: [])
    controls[1].wait_error = error
    assert launch(tmp_path) == 124
    result = record(tmp_path)
    assert result["error"] == "wall-clock" and result["cleanup"]["requires_recovery"]
    assert result["cleanup"]["errors"][-1]["operation"] == "wait_for_leader"


@pytest.mark.parametrize("code, expected", [(0, 0), (17, 17), (-15, 143)])
def test_exited_child_control_preserves_status(tmp_path, monkeypatch, controls, code, expected):
    controls[1].returncode = code
    monkeypatch.setattr(execution, "process_group_members", lambda pid: [])
    assert launch(tmp_path) == expected
    result = record(tmp_path)
    assert result["status"] == ("succeeded" if code == 0 else "failed")
    if code:
        assert result["error"] == f"exit-{expected}"
        assert result["cleanup"]["signals"] == []
        assert not result["cleanup"]["requires_recovery"]
    else:
        assert "cleanup" not in result and result["receipt_sha256"]


def test_interruption_is_retained_even_when_cleanup_is_denied(tmp_path, monkeypatch, controls):
    def interrupt():
        raise KeyboardInterrupt("primary")
    controls[1].poll = interrupt
    def denied(pid, sig):
        raise PermissionError("cleanup")
    monkeypatch.setattr(supervisor.os, "killpg", denied)
    assert launch(tmp_path) == 130
    assert record(tmp_path)["error"] == "interrupted"


def test_stall_reason_survives_cleanup_failure(tmp_path, monkeypatch, controls):
    monkeypatch.setattr(supervisor.time, "time", lambda: 1e12)
    def denied(pid, sig):
        raise PermissionError("cleanup")
    monkeypatch.setattr(supervisor.os, "killpg", denied)
    assert launch(tmp_path, kill_secs=10, stall_secs=.1) == 124
    assert record(tmp_path)["error"] == "progress-stall"


def test_launch_exception_finalizes_without_cleanup(tmp_path, monkeypatch, controls):
    def refused(*args, **kwargs):
        raise PermissionError("launch denied")
    monkeypatch.setattr(supervisor.subprocess, "Popen", refused)
    assert launch(tmp_path) == 2
    result = record(tmp_path)
    assert result["error"] == "launch denied" and "cleanup" not in result


def test_second_interrupt_during_grace_retains_first_signal(tmp_path, monkeypatch, controls):
    monkeypatch.setattr(supervisor.os, "killpg", lambda pid, sig: None)
    def interrupted_wait(duration):
        raise KeyboardInterrupt("second signal during grace")
    monkeypatch.setattr(supervisor.time, "sleep", interrupted_wait)
    # Enter cleanup with the primary timeout already determined, independent of polling.
    def expired():
        controls[0].now = max(10, controls[0].now)
        return None
    controls[1].poll = expired
    assert launch(tmp_path) == 124
    cleanup = record(tmp_path)["cleanup"]
    assert cleanup["signals"] == [{"signal": "SIGTERM", "outcome": "sent"}]
    assert cleanup["requires_recovery"]
    assert cleanup["errors"][-1]["operation"] == "wait_for_group"


@pytest.mark.parametrize("descendants", [False, True])
def test_reap_owned_leader_before_escalating_but_still_check_descendants(tmp_path, monkeypatch, controls, descendants):
    child = controls[1]
    sent, terminated, reaped = [], False, False
    def poll():
        nonlocal reaped
        if terminated:
            reaped = True
            child.returncode = 0
        return child.returncode
    child.poll = poll
    def members(pid):
        if not reaped:
            return [pid]
        return [pid + 1] if descendants else []
    monkeypatch.setattr(execution, "process_group_members", members)
    def kill(pid, sig):
        nonlocal terminated
        sent.append(sig)
        terminated = True
        if sig == signal.SIGKILL:
            raise PermissionError("descendant signal denied")
    monkeypatch.setattr(supervisor.os, "killpg", kill)
    assert launch(tmp_path) == 124
    cleanup = record(tmp_path)["cleanup"]
    assert sent == ([signal.SIGTERM, signal.SIGKILL] if descendants else [signal.SIGTERM])
    assert cleanup["requires_recovery"] is descendants
    assert cleanup["remaining_group_members"] == ([child.pid + 1] if descendants else [])


def test_final_wait_refreshes_empty_group_without_erasing_signal_error(tmp_path, monkeypatch, controls):
    child = controls[1]
    members = [child.pid]
    monkeypatch.setattr(execution, "process_group_members", lambda pid: list(members))
    def denied(pid, sig):
        raise PermissionError("not evidence of successful delivery")
    monkeypatch.setattr(supervisor.os, "killpg", denied)
    def wait(*, timeout):
        assert timeout == .2
        members.clear()
        return 0
    child.wait = wait
    assert launch(tmp_path) == 124
    cleanup = record(tmp_path)["cleanup"]
    assert cleanup["group_state"] == "empty" and not cleanup["requires_recovery"]
    assert cleanup["signals"] == [{"signal": "SIGTERM", "outcome": "error"}]
    assert cleanup["errors"][0]["type"] == "PermissionError"


@pytest.mark.parametrize("state", ["active", "unknown", "empty"])
def test_failed_cleanup_holds_retry_until_group_observed_empty(tmp_path, monkeypatch, controls, state):
    def denied(pid, sig):
        raise PermissionError("cleanup")
    monkeypatch.setattr(supervisor.os, "killpg", denied)
    assert launch(tmp_path) == 124
    before = (tmp_path / "execution_state.json").read_bytes()
    def members(pid):
        if state == "unknown":
            raise PermissionError("census")
        return [] if state == "empty" else [pid]
    monkeypatch.setattr(execution, "process_group_members", members)
    monkeypatch.setattr(supervisor.os, "killpg", lambda *a: pytest.fail("recovery must not signal failed attempt"))
    if state == "empty":
        supervisor._recover_orphan(tmp_path, "fit", .2)
    else:
        with pytest.raises(ValueError, match="held"):
            supervisor._recover_orphan(tmp_path, "fit", .2)
    assert (tmp_path / "execution_state.json").read_bytes() == before


@pytest.mark.parametrize("outcome", ["denied", "interrupted", "empty"])
def test_running_orphan_cleanup_finalizes_or_holds(tmp_path, monkeypatch, controls, outcome):
    spec = execution.plan_stage(tmp_path, "fit", [sys.executable, "-c", "pass"], [], [], [], str(tmp_path))
    previous = execution.begin_attempt(tmp_path, "fit", spec, "logs/fit.log")
    execution.record_process(tmp_path, previous, controls[1].pid)
    members = [controls[1].pid]
    monkeypatch.setattr(execution, "process_group_members", lambda pid: list(members))
    def signal_outcome(pid, sig):
        if outcome == "denied":
            raise PermissionError("orphan cleanup denied")
        if outcome == "interrupted":
            raise KeyboardInterrupt("orphan cleanup interrupted")
        members.clear()
    monkeypatch.setattr(supervisor.os, "killpg", signal_outcome)
    if outcome == "empty":
        supervisor._recover_orphan(tmp_path, "fit", .2)
        assert record(tmp_path)["status"] == "interrupted"
    else:
        with pytest.raises(ValueError, match="held"):
            supervisor._recover_orphan(tmp_path, "fit", .2)
        result = record(tmp_path)
        assert result["status"] == "failed" and result["exit_code"] == 130
        assert result["cleanup"]["requires_recovery"]
