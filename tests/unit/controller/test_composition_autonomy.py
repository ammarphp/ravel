"""Autonomous mode on the real controller composition: inert negative runs of an unattended run.

Each case configures one inert autonomous run through the operator's own channel and drives it unattended with every
in-process seam of the controller refused, on the wave-A gate's harness (its inert worker, its operator channel and
its live transport qualification, imported, never copied). The worker never calls a model and no native science runs.

1. A widened operator configuration (the ledger rewritten without the operator's key) is refused at intake: no worker
   starts and the run ends in a qualified ending.
2. A dispatch to a worker family the project's data classification does not admit is refused before any process
   starts.
3. An exhausted bound (the deadline margin) stops new work and ends in a qualified ending that names it.
4. An operator pause issued while the run is driven makes it wait at its next boundary, notifies the operator once
   with the run name and a state code only (no notification on a status poll), and the operator's resume continues it.
5. An operator stop issued while the run is driven drains it to a qualified ending at its next boundary, with nothing
   it owns still alive.
6. A driver that stops between supersteps (a lost terminal) resumes the same run without dispatching any step twice.
"""
from __future__ import annotations

import contextlib
import functools
import importlib
import io
import json
import os
from pathlib import Path
import time

import pytest

from ravel.controller import entry, graph, testing
from ravel.controller.ledger import state as ledger_state
import test_composition_wave_a as wave_a


def _environment(tmp_path, monkeypatch, *operator_flags, project_policy=None, worker=None, supplied=None,
                 supplied_classification=None):
    """The wave-A gate's process environment and operator configuration; returns ``(root, store)``.

    ``worker`` replaces the inert executable's text (a variant built from the wave-A gate's own script) and
    ``supplied`` maps file names to the documents the operator supplies with the request."""
    from ravel.workflow import sandbox
    if sandbox.available() is None:
        pytest.fail("a composed autonomous run needs the OS worker sandbox; this host offers none")
    root = Path(os.path.realpath(tmp_path))
    for name in ("state", "home", "claude-login", "bin", "operator", "runs"):
        (root / name).mkdir(exist_ok=True)
    monkeypatch.setenv("RAVEL_STATE_DIR", str(root / "state"))
    monkeypatch.setenv("HOME", str(root / "home"))
    for name in ("RAVEL_WORK_ROOT", "RAVEL_TRANSPORT_PATH", "RAVEL_AGENT_TRIPWIRE", "RAVEL_OPERATING_MODE",
                 "RAVEL_RESTRICTED_SOURCES"):
        monkeypatch.delenv(name, raising=False)
    from ravel.workflow import agent_tripwire
    monkeypatch.setattr(agent_tripwire, "_DECLARED", [])
    from ravel.workflow.approval_authority import AGENT_MARKERS
    for name in AGENT_MARKERS:
        monkeypatch.delenv(name, raising=False)
    from ravel.controller.authority import issuer, operator
    monkeypatch.setattr(issuer, "home", lambda: operator.controller_home() / "issuer")
    confine = importlib.import_module("ravel.controller.confine")
    identity = importlib.import_module("ravel.controller.confine.identity")
    for holder in (identity, confine):
        monkeypatch.setattr(holder, "code_identity", lambda **_: dict(wave_a.INSTALLED))
    sources = root / "operator" / "restricted-sources.json"
    sources.write_text(json.dumps({"kind": "restricted-sources", "fingerprints": ["fictional private example"]}))
    if worker is not None:
        monkeypatch.setattr(wave_a, "WORKER", worker)
    preferences = wave_a._install_worker(root, monkeypatch)
    status, output = wave_a._operator("init", "--mode", "autonomous", "--store-root", str(root / "store"),
                                      "--machine-checkins", ",".join(wave_a.MACHINE_CHECKINS),
                                      "--allow-unconfined", "false", "--restricted-sources", str(sources),
                                      "--agent-preferences", json.dumps(preferences), *operator_flags)
    assert status == 0, output
    if project_policy is not None:
        (root / "runs" / ".ravel").mkdir()
        (root / "runs" / ".ravel" / "data_classification.json").write_text(json.dumps(project_policy))
    rows = []
    for name, document in (supplied or {}).items():
        (root / "operator" / "supplied").mkdir(parents=True, exist_ok=True)
        (root / "operator" / "supplied" / name).write_text(json.dumps(document))
        rows.append(str(root / "operator" / "supplied" / name))
    store = entry.start(wave_a.REQUEST, channel="operator-file", rundir=root / "runs" / "r1", unattended=True,
                        supplied=entry._supplied(rows, str(root), data_classification=supplied_classification) if rows else (),
                        origin={"entry": "drive", "source": "request-file", "channel": "operator-file"})
    wave_a._qualify(root, store)
    return root, store


def _drive(store, *, sleep=lambda seconds: None, resume=False):
    err = io.StringIO()
    with testing.seams(False, controller=True), contextlib.redirect_stderr(err):
        observation = entry.drive(store, unattended=True, resume=resume, sleep=sleep, poll_seconds=0)
    return observation, err.getvalue()


def _receipt(store):
    from ravel.controller import sink
    return sink.receipt(store)


def _qualified(store):
    """The run ended through the sink's qualified ending, accepting nothing; returns the ending record."""
    receipt = _receipt(store)
    assert receipt.get("accepted") is not True and receipt.get("qualified") is True, receipt
    assert "QUALIFIED ENDING" in (receipt.get("labels") or []), receipt.get("labels")
    assert "NOT GOVERNED" not in (receipt.get("labels") or [])
    endings = wave_a._records(store, "qualified-ending")
    assert endings, wave_a._where(store)
    return endings[-1]


def _dispatches(store):
    return wave_a._records(store, "step-dispatch")


def _notifier(root):
    log = root / "operator" / "notified.log"
    (root / "operator").mkdir(parents=True, exist_ok=True)
    script = root / "operator" / "notify.py"
    script.write_text('import sys\nopen(sys.argv[1], "a").write(" | ".join(sys.argv[2:]) + "\\n")\n')
    import sys
    return json.dumps([sys.executable, str(script), str(log)]), log


@contextlib.contextmanager
def _after(name, action):
    """Run ``action(state)`` once after the controller node ``name`` (the wrapper keeps the node's name)."""
    original = getattr(graph, name)
    done = []

    @functools.wraps(original)
    def wrapped(state):
        update = original(state)
        if not done:
            done.append(True)
            action(state)
        return update
    setattr(graph, name, wrapped)
    try:
        yield done
    finally:
        setattr(graph, name, original)


def test_a_widened_operator_configuration_is_refused_at_intake(tmp_path, monkeypatch):
    root, store = _environment(tmp_path, monkeypatch)
    try:
        from ravel.controller.authority import operator
        path = operator.ledger_path()
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[-1]["record"]["config"]["budgets"]["wall_seconds"] = 10 ** 9  # widened without the operator's key
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        try:
            _drive(store)
        except entry.EntryError as exc:  # refused at the driver's own admission, before intake
            assert "operator ledger" in str(exc), exc
        else:
            _qualified(store)  # or refused at intake, ending qualified
        assert _dispatches(store) == [], "a worker started under a widened configuration"
        with pytest.raises(entry.EntryError) as refused:  # and no further run starts under it
            entry.start(b"Another fictional request.", channel="operator-file", rundir=root / "runs" / "r2",
                        unattended=True)
        assert refused.value.code == "authority_invalid"
    finally:
        ledger_state.forget(store)


def test_a_dispatch_to_a_family_the_project_does_not_admit_starts_no_process(tmp_path, monkeypatch):
    policy = {"level": "restricted", "allowed_providers": [{"transport_id": "fictional-admitted-worker",
                                                            "account_class": "login:subscription"}]}
    root, store = _environment(tmp_path, monkeypatch, project_policy=policy)
    try:
        _drive(store)
        assert _dispatches(store) == [], "a worker of a non-admitted family was dispatched"
        assert wave_a._records(store, "step-observation") == []
        held = [r for r in wave_a._records(store, "step-outcome") if "provider_policy_refused" in json.dumps(r)]
        refused = [r for r in wave_a._records(store, "step-refusal") if "provider_policy_refused" in json.dumps(r)]
        assert held or refused or "provider_policy_refused" in json.dumps(wave_a._records(store, "judgment-event")), \
            wave_a._where(store)
        _qualified(store)
    finally:
        ledger_state.forget(store)


def test_an_exhausted_bound_ends_qualified_and_names_it(tmp_path, monkeypatch):
    soon = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
    root, store = _environment(tmp_path, monkeypatch, "--deadline", soon, "--deadline-margin", "7200",
                               "--budget", "max_redos=0")
    try:
        _drive(store)
        assert _dispatches(store) == [], "new work started past the deadline margin"
        ending = _qualified(store)
        assert ending["code"] == "deadline" and "deadline_margin" in ending["reason"], ending
    finally:
        ledger_state.forget(store)


def test_a_pause_waits_notifies_once_and_a_resume_continues(tmp_path, monkeypatch):
    command, log = _notifier(Path(os.path.realpath(tmp_path)))
    root, store = _environment(tmp_path, monkeypatch, "--notify-command", command, "--wait-bound", "120")
    polls = []

    def pause(state):
        status, output = wave_a._operator("pause", "--run", store.run_id, "--reason", "operator inspection")
        assert status == 0, output

    def operator_poll(seconds):
        # The operator reads the status (never a notification) and resumes once the wait was notified.
        status, output = wave_a._operator("status", "--run", store.run_id)
        assert status == 0, output
        polls.append(json.loads(output))
        if [w["code"] for w in polls[-1]["waits"]] == ["paused"]:
            status, output = wave_a._operator("resume", "--run", store.run_id, "--reason", "inspection done")
            assert status == 0, output
        time.sleep(min(seconds, 1.0))
    try:
        with _after("approved", pause) as done:
            observation, err = _drive(store, sleep=operator_poll)
        assert done, wave_a._where(store)
        lines = log.read_text().splitlines() if log.exists() else []
        paused = [line for line in lines if line.endswith("WAITING_FOR_HUMAN paused")]
        assert paused == [f"{store.run_id} | WAITING_FOR_HUMAN paused"], lines
        assert all(line.split(" | ")[1].split()[0] in ("WAITING_FOR_HUMAN", "QUALIFIED", "DEVIATION_RECORDED")
                   for line in lines), lines  # a state code, never reason text
        assert polls and any(p["waits"] for p in polls)
        waits = wave_a._records(store, "autonomy-wait")
        assert [w["phase"] for w in waits if w["code"] == "paused"] == ["open", "resolved"], waits
        resumed = max(r["time_ns"] for r in waits if r["code"] == "paused")
        assert [d for d in store.scan("step-dispatch") if d["time_ns"] > resumed], \
            ("the run did not continue after the resume", wave_a._where(store))
    finally:
        ledger_state.forget(store)


def test_an_operator_stop_drains_to_a_qualified_ending(tmp_path, monkeypatch):
    root, store = _environment(tmp_path, monkeypatch)
    stopped_at = []

    def stop(state):
        stopped_at.append(time.time_ns())
        status, output = wave_a._operator("stop", "--run", store.run_id, "--reason", "operator stop")
        assert status == 0, output
        assert json.loads(output)["state"] == "stop_requested"
    try:
        with _after("approved", stop) as done:
            _drive(store)
        assert done, wave_a._where(store)
        assert not [d for d in store.scan("step-dispatch") if d["time_ns"] > stopped_at[0]], \
            "a step was dispatched after the stop"
        ending = _qualified(store)
        assert ending["code"] == "stopped", ending
        status, output = wave_a._operator("status", "--run", store.run_id)
        assert status == 0 and json.loads(output)["alive"] == [], output
    finally:
        ledger_state.forget(store)


def test_a_restarted_driver_continues_without_dispatching_any_step_twice(tmp_path, monkeypatch):
    root, store = _environment(tmp_path, monkeypatch, "--wait-bound", "0")

    def lost_terminal(state):
        from ravel.workflow import graph_substrate
        graph_substrate._CONTROLS[-1].request_drain("fictional lost terminal")
    try:
        with _after("join", lost_terminal) as done:
            first, _ = _drive(store)
        assert done and (first.get("terminal") or {}).get("reason") == "fictional lost terminal", first
        before = len(_dispatches(store))
        resumed = entry.open_for_resume(store.run_id)
        _drive(resumed, resume=True)
        keys = [(d["node_id"], d["attempt"]) for d in _dispatches(store)]
        assert len(keys) == len(set(keys)) and len(keys) >= before, keys
        launches = [(r["step_id"], r["attempt"]) for r in wave_a._records(store, "step-launch")
                    if r.get("phase") == "started"]
        assert len(launches) == len(set(launches)), launches
        assert wave_a._records(store, "ending") or wave_a._records(store, "receipt"), wave_a._where(store)
    finally:
        ledger_state.forget(store)


def test_a_delegated_final_task_completes_without_any_human_prompt(tmp_path, monkeypatch):
    """N1's pass path: intake, CHECK-IN 1, every later check-in and a fresh CHECK-IN 3 on the exact R3 final-task
    action, all resolved by the operator's configured machine authority (``--r3-delegation final_task``)."""
    root, store = _environment(tmp_path, monkeypatch, "--r3-delegation", "final_task", "--wait-bound", "0")
    try:
        observation, err = _drive(store)
        assert not entry._pending(observation), wave_a._pending_diagnostic(store, observation, err)
        authority = wave_a._records(store, "authority")
        assert authority and {r["label"] for r in authority} == {"operator_configured_machine"}, \
            [(r["kind"], r["label"]) for r in authority]
        finals = [r for r in authority if r["kind"] == "final"]
        assert finals and finals[-1]["decision"] == "accept", wave_a._where(store)
        assert finals[-1]["evidence"]["r3_delegation"] == "final_task"
        assert finals[-1]["evidence"]["final_task_class"] == "R3"
        assert wave_a._records(store, "authority-request") == []  # nothing waited for a human
        wave_a._assert_honest_receipt(store)
    finally:
        ledger_state.forget(store)
