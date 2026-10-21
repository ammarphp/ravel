"""P01 command policy: state-writing commands are refused for controller-owned runs, before dispatch.

Rows: SW13 (hidden focused commands are checked before dispatch), C25 (aliases, option values and
the working directory reach the owning run), and the policy side of SW01-SW05 and SW11 (the
authority package records the decisions; these commands never write them for a controller run).
Every refused command keeps working for a legacy run.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ravel import cli
from ravel.controller import command_policy
from ravel.controller.store import RunStore

TABLE = command_policy.policy()


@pytest.fixture
def runs(tmp_path):
    store = RunStore.create(tmp_path / "runs" / "owned", root=tmp_path / "store")
    (store.run_dir / "inputs").mkdir()
    (store.run_dir / "inputs" / "task_contract.json").write_text("{}")
    legacy = tmp_path / "runs" / "legacy"
    (legacy / "inputs").mkdir(parents=True)
    (legacy / "inputs" / "task_contract.json").write_text("{}")
    return store, legacy


def _argv(row, run_dir, scope):
    command = row["command"]
    words = list(row.get("subcommands", [])[:1])
    flags = []
    if "flags" in row:
        flags = [row["flags"][0]] + ([] if row["flags"][0] in ("--rundir",) else [])
    target = ["--scope-root", str(scope)] if command in ("graph", "graph_substrate") else ["--rundir", str(run_dir)]
    argv = [command, *words, *target]
    for flag in flags:
        if flag not in argv:
            argv += [flag, "1"]
    return argv


REFUSED = [row for row in TABLE["refused"] if "command" in row]


@pytest.mark.parametrize("row", REFUSED, ids=[f"{r['command']}-{'-'.join(r.get('subcommands', []) or r.get('flags', [])[:1])}"
                                               for r in REFUSED])
def test_each_listed_command_is_refused_for_a_controller_run_and_allowed_for_a_legacy_run(runs, row):
    store, legacy = runs
    owned = command_policy.check(_argv(row, store.run_dir, store.graph_scope()))
    assert owned and store.run_id in owned
    assert _switch(_argv(row, store.run_dir, store.graph_scope())) == row["switch"]
    assert command_policy.check(_argv(row, legacy, legacy)) is None


def test_SW05_clear_stop_is_refused_on_any_command_that_targets_a_controller_run(runs):
    store, legacy = runs
    for argv in (["graph", "run", "--scope-root", str(store.graph_scope()), "--clear-stop"],
                 ["research-cycle", "run", "--cycle", str(store.run_dir), "--clear-stop"],
                 ["review", "run", "--rundir", str(store.run_dir), "--clear-stop"]):
        assert command_policy.check(argv) and _switch(argv) in ("SW05", "SW13")
    assert _switch(["research-cycle", "--clear-stop", "--rundir", str(store.run_dir)]) == "SW05"
    assert command_policy.check(["graph", "run", "--scope-root", str(legacy), "--clear-stop"]) is None


@pytest.mark.parametrize("argv", [
    ["status", "--rundir", "{run}"], ["doctor"], ["knowledge", "find", "anything"], ["modes", "list"],
    ["validate", "{run}/inputs/task_contract.json"], ["graph", "status", "--scope-root", "{scope}"],
    ["graph", "events", "--scope-root", "{scope}"], ["lifecycle", "check", "--rundir", "{run}"],
    ["checkin", "validate", "{run}/CHECKIN1.json"], ["transport", "list"], ["approve", "--help"],
    ["mode", "show", "--rundir", "{run}"],
])
def test_read_only_commands_and_help_stay_available(runs, argv):
    store, _ = runs
    argv = [a.replace("{run}", str(store.run_dir)).replace("{scope}", str(store.graph_scope())) for a in argv]
    assert command_policy.check(argv) is None


@pytest.mark.parametrize("argv", [
    ["ask", "a fictional question"], ["operator", "stop", "--run", "run-x"], ["drive", "--resume", "run-x"],
    ["drive", "--request-file", "request.txt", "--rundir", "{run}"], ["status", "--run", "run-x"],
])
def test_controller_entries_are_never_refused_here(runs, argv):
    store, _ = runs
    assert command_policy.check([a.replace("{run}", str(store.run_dir)) for a in argv]) is None


def _switch(argv):
    found = command_policy.refusal(argv)
    return found and found["switch"]


def test_status_write_and_unlisted_commands_are_refused_by_default(runs):
    store, legacy = runs
    reason = command_policy.check(["status", "--rundir", str(store.run_dir), "--write"])
    assert reason and "read-only" in reason
    assert _switch(["status", "--rundir", str(store.run_dir), "--write"]) == "SW13"
    assert _switch(["xsec", "lookup", "--request", str(store.run_dir / "x.json")]) == "SW13"
    assert command_policy.check(["xsec", "lookup", "--request", str(legacy / "x.json")]) is None


def test_SW13_abbreviated_options_count_as_the_options_they_expand_to(runs):
    store, legacy = runs
    # argparse expands an unambiguous prefix (`--wri` is `--write`); the policy reads it the same way.
    for argv in (["status", "--rundir", str(store.run_dir), "--wri"],
                 ["status", "--rundir", str(store.run_dir), "--notif", "[]"],
                 ["status", f"--rundir={store.run_dir}", "--write=1"]):
        assert _switch(argv) == "SW13", argv
    assert _switch(["research-cycle", "--clear", "--rundir", str(store.run_dir)]) == "SW05"
    assert _switch(["drive", "--rund", str(store.run_dir)]) == "SW04"
    # Positive controls: a read-only abbreviation, and the same commands on a legacy run.
    assert command_policy.check(["status", "--rundir", str(store.run_dir), "--retained"]) is None
    assert command_policy.check(["status", "--rundir", str(legacy), "--wri"]) is None
    # A controller entry is recognised only by its exact option: an abbreviation is not the controller's form.
    assert _switch(["drive", "--res", "run-x", "--rundir", str(store.run_dir)]) == "SW04"


def test_refusal_text_names_the_run_and_the_way_forward_without_internal_row_labels(runs):
    store, _ = runs
    for row in REFUSED:
        argv = _argv(row, store.run_dir, store.graph_scope())
        found = command_policy.refusal(argv)
        assert found["switch"] == row["switch"] and found["run_id"] == store.run_id
        assert found["reason"] == command_policy.check(argv)
        assert row["switch"] not in found["reason"] and "[SW" not in found["reason"]
        assert f"ravel drive --resume {store.run_id}" in found["reason"]


def test_C25_aliases_option_values_and_the_working_directory_reach_the_owning_run(runs, tmp_path, monkeypatch):
    store, legacy = runs
    os.symlink(store.run_dir, tmp_path / "alias")
    assert _switch(["approve", "--rundir", str(tmp_path / "alias"), "--quote", "q"]) == "SW01"
    assert _switch(["approve", f"--rundir={store.run_dir}", "--quote", "q"]) == "SW01"
    assert _switch(["figure", "draw", "--out", str(store.run_dir / "new" / "f.pdf")]) == "SW13"
    monkeypatch.chdir(store.run_dir)
    assert _switch(["approve", "--rundir", ".", "--quote", "q"]) == "SW01"
    assert _switch(["cost", "record", "--out", str(tmp_path / "outside.json")]) == "SW13"
    assert command_policy.check(["doctor"]) is None
    monkeypatch.chdir(legacy)
    assert command_policy.check(["cost", "record", "--out", str(tmp_path / "outside.json")]) is None
    assert command_policy.check(["approve", "--rundir", str(legacy), "--quote", "q"]) is None


def test_module_entry_points_use_the_pseudo_commands(runs):
    store, legacy = runs
    with pytest.raises(PermissionError, match="refused for the controller-owned run"):
        command_policy.require(["workflow_state", "approve", "--rundir", str(store.run_dir)])
    assert _switch(["workflow_state", "approve", "--rundir", str(store.run_dir)]) == "SW01"
    with pytest.raises(PermissionError, match="refused for the controller-owned run"):
        command_policy.require(["active_run", "release", "--rundir", str(store.run_dir)])
    assert _switch(["active_run", "release", "--rundir", str(store.run_dir)]) == "SW11"
    assert command_policy.require(["workflow_state", "approve", "--rundir", str(legacy)]) is None


def test_SW13_the_cli_checks_the_policy_before_any_dispatch(runs, monkeypatch, capsys):
    store, legacy = runs
    from importlib import import_module
    imported = []
    real = import_module

    def watching(name, *args, **kwargs):
        imported.append(name)
        return real(name, *args, **kwargs)
    monkeypatch.setattr("importlib.import_module", watching)
    monkeypatch.setattr(cli, "_approve", lambda args: pytest.fail("the approval handler ran for a controller run"))
    assert cli.main(["approve", "--rundir", str(store.run_dir), "--quote", "q"]) == 2
    assert "refused" in capsys.readouterr().err
    released = set(cli.released_commands())
    hidden = sorted(set(cli.FOCUSED_COMMANDS) - released) or ["research-preregister"]
    for command in hidden[:5]:
        before = len(imported)
        assert cli.main([command, "record", "--rundir", str(store.run_dir)]) == 2
        assert not [n for n in imported[before:] if n == "ravel." + cli.FOCUSED_COMMANDS[command][0]]
        assert "refused for the controller-owned run" in capsys.readouterr().err
        assert _switch([command, "record", "--rundir", str(store.run_dir)]) == "SW13"
    for argv in (["graph", "run", "--scope-root", str(store.graph_scope()), "--graph", "x", "--instance", "{}"],
                 ["mode", "set", "autonomous", "--rundir", str(store.run_dir)]):
        assert cli.main(argv) == 2
        assert "refused" in capsys.readouterr().err
    calls = []
    monkeypatch.setattr(cli, "_approve", lambda args: calls.append(args) or 0)
    assert cli.main(["approve", "--rundir", str(legacy), "--quote", "q"]) == 0 and calls


def test_the_policy_table_names_every_switch_it_closes():
    switches = {row["switch"] for row in TABLE["refused"]} | {TABLE["default"]["switch"]}
    assert {"SW01", "SW02", "SW03", "SW04", "SW05", "SW11", "SW13"} <= switches
    for row in TABLE["refused"] + TABLE["read_only"] + TABLE["controller_entries"]:
        assert set(row) <= {"command", "subcommands", "flags", "flag", "unless_flags", "switch", "reason"}
    json.dumps(TABLE)
