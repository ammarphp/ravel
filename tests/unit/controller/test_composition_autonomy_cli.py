"""The autonomy proof through the public CLI: one unattended composed inert run, operator-configured, accepted.

The operator configures autonomous mode from their own channel (``ravel operator init`` with every check-in
delegated to machine authority and the R3 final task delegated), qualifies the inert worker transport once for every
later run (``ravel transport qualify --for-operator``), and starts the run with the public entry
``ravel drive --unattended --request-file``. No human answers anything: the run goes from intake to
``deliver[accepted]`` with every check-in resolved by the operator's configured machine authority and labelled
``operator_configured_machine`` (never human, never an operator command), the qualification adopted at intake with its
provenance, no notification sent (nothing waited for a human) and the controller's decisions in the audit trail.

The harness is the wave-A gate's (its inert worker, operator channel and process environment, imported, never
copied); the worker calls no model and no native science runs. The negative runs (stop, exhausted bound, escalation,
restart) are in ``test_composition_autonomy``.
"""
from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import sys

import pytest

from ravel import cli as ravel_cli
from ravel.controller import testing
from ravel.controller.ledger import state as ledger_state
import test_composition_wave_a as wave_a


def _cli(*argv):
    """``ravel <argv>`` through the public entry; returns (status, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        status = ravel_cli.main(list(argv))
    return status, out.getvalue(), err.getvalue()


def _environment(tmp_path, monkeypatch):
    """The wave-A gate's process environment (no run started); returns ``(root, preferences)``."""
    from ravel.workflow import sandbox
    if sandbox.available() is None:
        pytest.fail("the composed autonomy proof needs the OS worker sandbox; this host offers none")
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
    for name in AGENT_MARKERS:  # the operator's own terminal is not an agent session
        monkeypatch.delenv(name, raising=False)
    from ravel.controller.authority import issuer, operator
    monkeypatch.setattr(issuer, "home", lambda: operator.controller_home() / "issuer")
    confine = importlib.import_module("ravel.controller.confine")
    identity = importlib.import_module("ravel.controller.confine.identity")
    for holder in (identity, confine):
        monkeypatch.setattr(holder, "code_identity", lambda **_: dict(wave_a.INSTALLED))
    sources = root / "operator" / "restricted-sources.json"
    sources.write_text(json.dumps({"kind": "restricted-sources", "fingerprints": ["fictional private example"]}))
    return root, sources, wave_a._install_worker(root, monkeypatch)


def _notifier(root):
    log = root / "operator" / "notified.log"
    script = root / "operator" / "notify.py"
    script.write_text('import sys\nopen(sys.argv[1], "a").write(" | ".join(sys.argv[2:]) + "\\n")\n')
    return json.dumps([sys.executable, str(script), str(log)]), log


def test_an_unattended_cli_run_is_accepted_by_operator_configured_machine_authority(tmp_path, monkeypatch):
    root, sources, preferences = _environment(tmp_path, monkeypatch)
    command, log = _notifier(root)
    # 1. The operator configures autonomy once, from their own channel: every check-in and the R3 final task delegated.
    status, out, err = _cli("operator", "init", "--mode", "autonomous", "--store-root", str(root / "store"),
                            "--machine-checkins", ",".join(wave_a.MACHINE_CHECKINS), "--r3-delegation", "final_task",
                            "--wait-bound", "0", "--allow-unconfined", "false", "--restricted-sources", str(sources),
                            "--agent-preferences", json.dumps(preferences), "--notify-command", command)
    assert status == 0, out + err
    # 2. The operator qualifies the worker transport once, before any run exists (adopted by every later run).
    status, out, err = _cli("transport", "qualify", wave_a.TRANSPORT, "--rundir", str(root / "qualification"),
                            "--model", wave_a.MODEL, "--for-operator")
    assert status == 0, out + err
    # 3. The public unattended start: no terminal, no human, no in-process seam.
    request = root / "operator" / "request.txt"
    request.write_bytes(wave_a.REQUEST)
    with testing.seams(False, controller=True):
        status, out, err = _cli("drive", "--unattended", "--request-file", str(request),
                                "--rundir", str(root / "runs" / "r1"))
    assert status == 0, out + err
    summary = json.loads(out)
    run_id = summary.get("run_id") or summary.get("run")
    assert run_id, summary
    from ravel.controller.authority import common as authority_common
    store = authority_common.open_store(run_id)
    try:
        # 4. Nothing waited for a human and nothing was notified: every authority record is the operator's configured
        # machine authority, on CHECK-IN 1, every later check-in and the fresh R3 final task.
        assert summary.get("waiting_for") == [] and not summary.get("waiting_for_human"), summary
        assert summary.get("resume") is None, summary
        assert wave_a._records(store, "authority-request") == [], wave_a._where(store)
        authority = wave_a._records(store, "authority")
        assert authority, wave_a._where(store)
        assert {r["label"] for r in authority} == {"operator_configured_machine"}, \
            [(r["kind"], r["label"]) for r in authority]
        assert "human" not in json.dumps([r["label"] for r in authority])
        # The approval authorizes effects; the final disposition never does (it installs nothing), so it is read by kind.
        assert {"approve_plan", "final"} <= {r["kind"] for r in authority}, sorted(r["kind"] for r in authority)
        assert [r for r in authority if r["kind"] == "approve_plan" and r.get("authorizes_effects") is True], authority
        final = [r for r in authority if r["kind"] == "final"][-1]
        assert final["decision"] == "accept" and final["evidence"]["r3_delegation"] == "final_task", final
        assert final["evidence"]["final_task_class"] == "R3", final["evidence"]
        assert not log.exists() or not [line for line in log.read_text().splitlines()
                                        if "WAITING_FOR_HUMAN" in line], log.read_text()
        # 5. The operator's qualification was adopted at intake with its provenance, and the seat selected it.
        adoptions = [r for r in wave_a._records(store, "transport-qualification-adoption") if r.get("status") == "adopted"]
        assert adoptions and adoptions[0]["provenance"]["source"] == "operator_area", \
            wave_a._records(store, "transport-qualification-adoption")
        # 6. The sole sink accepted the delivery: no row of deliver[accepted] unmet, the architecture complete.
        from ravel.controller import sink
        receipt = sink.receipt(store)
        assert receipt.get("accepted") is True and receipt.get("architecture_complete") is True, json.dumps({
            "unmet": wave_a._unmet(store, "deliver[accepted]"), "labels": receipt.get("labels"),
            "predicates": receipt.get("architecture_predicates")}, sort_keys=True, default=str)
        wave_a._assert_honest_receipt(store)
        # 7. The audit trail names each machine approval with its rule and evidence (N10), and the operator's own
        # status read reports nothing alive and no open wait.
        from ravel.controller.authority import autonomy
        audit = autonomy.audit_rows(store)
        approvals = [r for r in audit if r.get("event") == "authority" and r.get("label") == "operator_configured_machine"]
        assert approvals and all(r.get("rule") and r.get("evidence_sha256") for r in approvals), audit[:5]
        status, out, err = _cli("operator", "status", "--run", run_id)
        assert status == 0, out + err
        view = json.loads(out)
        assert view["alive"] == [] and view["waits"] == [] and view["pending"] == [], view
        # 8. The public status entry reads the same run.
        status, out, err = _cli("status", "--run", run_id)
        assert status == 0, out + err
    finally:
        ledger_state.forget(store)
