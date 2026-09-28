"""Signal ownership on paths a live run relies on outside the harness modules (the 2026-09-27 reviews): the stage
supervisor's orphan recovery runs on the broker's stage path during paid runs, and must fail closed when the recorded
process's identity cannot be read while some process holds its pid (that pid may now lead an unrelated group of this
user), and when no process holds it but a group of that id is active (after pid reuse that group may be another's:
nothing proves it is the stage's, E-98). Mocks only: every "signal" here is a recording function, and the existence
probe is replaced too."""
from __future__ import annotations

import pytest

from ravel.workflow import execution
from ravel.workflow import stage_supervisor as supervisor

PID = 424242


@pytest.fixture
def recorded(monkeypatch):
    """A SYNTHETIC running attempt whose child identity was recorded, and a cleanup that must never be reached."""
    old = {"child_pid": PID, "status": "running", "child_identity": "SYNTHETIC lstart", "stage": "fit"}
    monkeypatch.setattr(execution, "load_execution", lambda rundir: {"stages": {"fit": dict(old)}})
    monkeypatch.setattr(execution, "process_identity", lambda pid: None)   # ps failed or timed out
    monkeypatch.setattr(execution, "process_group_members", lambda pid: [PID + 1])
    signalled = []
    monkeypatch.setattr(supervisor, "_terminate_owned_group",
                        lambda pid, grace: signalled.append(pid) or {"requires_recovery": False})
    updates = []
    monkeypatch.setattr(execution, "_update", lambda rundir, stage, record: updates.append(record))
    return signalled, updates


@pytest.mark.parametrize("probe", ["exists", "not_permitted"])
def test_an_unreadable_identity_of_a_held_pid_holds_the_stage(tmp_path, monkeypatch, recorded, probe):
    signalled, updates = recorded

    def existence(pid, sig):
        assert sig == 0, "only the existence probe may run here"
        if probe == "not_permitted":
            raise PermissionError(1, "SYNTHETIC: another user's process holds the pid")
    monkeypatch.setattr(supervisor.os, "kill", existence)
    with pytest.raises(ValueError, match="cannot establish ownership of previous process"):
        supervisor._recover_orphan(tmp_path, "fit", .2)
    assert signalled == [] and updates == []


def gone(pid, sig):
    assert sig == 0, "only the existence probe may run here"
    raise ProcessLookupError(3, "SYNTHETIC: no process holds the pid")


def test_a_recorded_group_whose_leader_is_gone_is_held_and_never_signalled(tmp_path, monkeypatch, recorded):
    """E-98 (changes the former behaviour, which signalled this group): with no leader to compare, the group's identity
    is unprovable, so its members are recorded for a human and the stage is held until the group is seen empty."""
    signalled, updates = recorded
    monkeypatch.setattr(supervisor.os, "kill", gone)
    monkeypatch.setattr(supervisor.os, "killpg", lambda *a: pytest.fail("a leaderless group is never signalled"))
    with pytest.raises(ValueError, match="nothing was signalled; stage fit held"):
        supervisor._recover_orphan(tmp_path, "fit", .2)
    assert signalled == [] and len(updates) == 1
    held = updates[0]
    assert held["status"] == "failed" and held["exit_code"] == 130
    assert held["cleanup"]["requires_recovery"] is True and held["cleanup"]["signals"] == []
    assert held["cleanup"]["remaining_group_members"] == [PID + 1] and held["cleanup"]["group_state"] == "active"


def test_a_leaderless_group_with_no_active_member_needs_nothing(tmp_path, monkeypatch, recorded):
    signalled, updates = recorded
    monkeypatch.setattr(supervisor.os, "kill", gone)
    monkeypatch.setattr(execution, "process_group_members", lambda pid: [])
    supervisor._recover_orphan(tmp_path, "fit", .2)
    assert signalled == [] and updates == []
