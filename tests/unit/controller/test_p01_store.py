"""P01 store: placement, permissions, the hash chain, the controller clock and run ownership.

Rows: SW20 (environment never relocates the store), CT03 (the store lies outside the run directory
and every sandbox mount; tampering is detected), C25 (aliases resolve to the owning run), C41
(a copied run keeps its owner and is never resumed), R11 (checkpoints resume from the store).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import time

import pytest

from ravel.controller import store as st


def _create(tmp_path, name="r1"):
    return st.RunStore.create(tmp_path / "runs" / name, root=tmp_path / "store")


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_CT03_store_lies_outside_the_run_directory_with_private_modes(tmp_path):
    store = _create(tmp_path)
    run_dir = store.run_dir
    assert not str(store.root).startswith(str(run_dir) + os.sep)
    assert not str(run_dir).startswith(str(store.store_root) + os.sep)
    assert _mode(store.store_root) == 0o700 and _mode(store.root) == 0o700
    store.append("ledger", {"entry_id": "X", "status": "pending"})
    assert _mode(store.root / st.JOURNAL) == 0o600 and _mode(store.root / st.HEAD) == 0o600
    assert _mode(store.root / st.RUN) == 0o600
    digest = store.put_blob(b"bytes")
    assert _mode(store.root / "blobs" / digest) == 0o600
    # Checkpoints, events and the stop flag live in the store's graph scope, not the run directory.
    assert store.graph_scope().is_relative_to(store.root)
    saver = store.checkpointer()
    assert (store.graph_scope() / st.CHECKPOINTS).is_file() and type(saver).__name__ == "SqliteSaver"
    store.close()
    assert not (run_dir / "framework").exists()
    # A store path cannot point into the run directory or outside the store.
    for parts in (("..", "x"), ("/abs",), ("a/b",), ("",)):
        with pytest.raises(st.StoreError):
            store.path(*parts)
    assert store.path("graph", "framework") == store.root / "graph" / "framework"
    assert store.path() == store.root and not store.path().is_relative_to(run_dir)


def test_CT03_a_store_inside_the_run_directory_and_a_widened_store_are_refused(tmp_path):
    with pytest.raises(st.StoreError, match="contain each other"):
        st.RunStore.create(tmp_path / "runs" / "r1", root=tmp_path / "runs" / "r1" / "store")
    with pytest.raises(st.StoreError, match="contain each other"):
        st.RunStore.create(tmp_path / "store" / "inside", root=tmp_path / "store")
    store = _create(tmp_path)
    os.chmod(store.root, 0o770)
    with pytest.raises(st.StoreError, match="readable or writable by others"):
        st.RunStore(store.run_id, root=tmp_path / "store")


def test_CT03_hostile_edits_to_the_journal_are_detected(tmp_path):
    store = _create(tmp_path)
    ids = [store.append("ledger", {"n": n}) for n in range(4)]
    journal = store.root / st.JOURNAL
    original = journal.read_bytes()
    lines = original.decode().splitlines()

    def reopened():
        return st.RunStore(store.run_id, root=tmp_path / "store")

    edited = json.loads(lines[2]); edited["record"]["n"] = 99
    journal.write_text("\n".join(lines[:2] + [json.dumps(edited, sort_keys=True, separators=(",", ":"))]
                                 + lines[3:]) + "\n")
    assert reopened().verify() and "does not match its content" in reopened().verify()[0]
    journal.write_text("\n".join([lines[0], lines[2], lines[1], *lines[3:]]) + "\n")
    assert "chain breaks" in reopened().verify()[0]
    journal.write_text("\n".join(lines[:-1]) + "\n")
    assert "head does not match" in reopened().verify()[0] or "truncated" in reopened().verify()[0]
    journal.write_bytes(original)
    assert reopened().verify() == []
    assert [reopened().read("ledger", i)["record"]["n"] for i in ids] == [0, 1, 2, 3]
    with pytest.raises(st.StoreTampered):
        store_copy = reopened()
        journal.write_text("\n".join(lines[:2]) + "\n")
        store_copy.append("ledger", {"n": 5})


def test_a_partial_line_and_a_missed_head_update_recover_without_losing_records(tmp_path):
    store = _create(tmp_path)
    store.append("ledger", {"n": 1})
    head = (store.root / st.HEAD).read_bytes()
    store.append("ledger", {"n": 2})
    (store.root / st.HEAD).write_bytes(head)  # the process died between the record and its head
    with (store.root / st.JOURNAL).open("ab") as stream:
        stream.write(b'{"partial":')  # an append that never completed
    fresh = st.RunStore(store.run_id, root=tmp_path / "store")
    fresh.append("ledger", {"n": 3})
    assert [r["record"]["n"] for r in fresh.scan("ledger")] == [1, 2, 3]
    assert fresh.verify() == []


def test_records_are_envelopes_stamped_by_the_controller_clock(tmp_path, monkeypatch):
    for name in ("WORKFLOW_STATE_UTC", "GATE_TIMESTAMP", "RAVEL_LAUNCH_UTC"):
        monkeypatch.setenv(name, "2001-01-01T00:00:00Z")
    store = _create(tmp_path)
    before = time.time_ns()
    record_id = store.append("authority", {"kind": "approve_plan"})
    entry = store.read("authority", record_id)
    assert set(entry) == {"schema_version", "seq", "kind", "time_ns", "prev", "record", "id", "digest"}
    assert before <= entry["time_ns"] <= time.time_ns()
    assert entry["id"].startswith("authority-") and entry["record"] == {"kind": "approve_plan"}
    with pytest.raises(st.StoreError):
        store.read("ledger", record_id)
    for bad in (float("nan"), object(), {1: 2}):
        with pytest.raises(st.StoreError):
            store.append("ledger", {"x": bad})
    with pytest.raises(st.StoreError):
        store.append("Bad Kind", {})


def test_SW20_environment_never_relocates_the_store(tmp_path, monkeypatch):
    expected = st.store_root()
    for name in ("RAVEL_STATE_DIR", "RAVEL_WORK_ROOT", "XDG_STATE_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "worker-writable" / name))
    monkeypatch.setenv("HOME", str(tmp_path / "other-home"))
    assert st.store_root() == expected
    assert not str(st.store_root()).startswith(str(tmp_path))
    assert st.protected_roots() == [expected]


def test_SW20_the_operator_configuration_alone_places_the_store(tmp_path, monkeypatch):
    class Authority:
        @staticmethod
        def operator_config():
            return {"store_root": str(tmp_path / "operator-store")}
    import sys
    import types
    module = types.ModuleType("ravel.controller.authority")
    module.operator_config = Authority.operator_config
    monkeypatch.setitem(sys.modules, "ravel.controller.authority", module)
    assert st.store_root() == Path(os.path.realpath(tmp_path / "operator-store"))
    module.operator_config = lambda: {"store_root": "relative/path"}
    with pytest.raises(st.StoreError, match="absolute"):
        st.store_root()


def test_C25_ownership_resolves_paths_inside_the_run_aliases_and_the_store(tmp_path, monkeypatch):
    store = _create(tmp_path)
    run_dir = store.run_dir
    (run_dir / "inputs").mkdir()
    assert st.controller_owned(run_dir) == store.run_id
    assert st.controller_owned(run_dir / "inputs" / "not-yet-written.json") == store.run_id
    os.symlink(run_dir, tmp_path / "alias")
    assert st.controller_owned(tmp_path / "alias" / "inputs") == store.run_id
    assert st.controller_owned(store.graph_scope() / "framework") == store.run_id
    assert st.controller_owned(tmp_path / "runs") is None
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    assert st.controller_owned(legacy) is None
    # Deleting the marker in place does not shed ownership: the store index binds the directory.
    (run_dir / st.RUN_MARKER).unlink()
    assert st.controller_owned(run_dir) is None  # the index lives in the configured store root
    monkeypatch.setattr(st, "store_root", lambda: Path(os.path.realpath(tmp_path / "store")))
    assert st.controller_owned(run_dir) == store.run_id
    # A directory later recreated at that path, without the marker, is not the run.
    shutil.rmtree(run_dir)
    run_dir.mkdir()
    assert st.controller_owned(run_dir) is None


def test_C25_a_recreated_directory_is_not_the_run_when_the_filesystem_reuses_its_inode(tmp_path, monkeypatch):
    store = _create(tmp_path)
    run_dir = store.run_dir
    monkeypatch.setattr(st, "store_root", lambda: Path(os.path.realpath(tmp_path / "store")))
    entry_path = store.store_root / st.INDEX / f"path-{st._path_key(run_dir)}.json"
    recorded = json.loads(entry_path.read_text())
    assert "birth" in recorded  # the index binds the directory's creation time as well as device and inode
    (run_dir / st.RUN_MARKER).unlink()
    assert st.controller_owned(run_dir) == store.run_id
    shutil.rmtree(run_dir)
    time.sleep(0.05)  # coarse filesystem clocks
    run_dir.mkdir()
    # Some filesystems give a removed directory's inode number to the next directory created. Put the
    # old device and inode on the new directory's record: only the creation time tells them apart.
    current = st.directory_identity(run_dir)
    entry_path.write_text(json.dumps({**recorded, "dev": current["dev"], "ino": current["ino"]}))
    assert st.controller_owned(run_dir) is None


def test_C41_a_copied_run_keeps_its_owner_and_never_binds(tmp_path):
    store = _create(tmp_path)
    store.append("budget", {"spent": {"wall_seconds": 120}})
    copy = tmp_path / "runs" / "copy"
    shutil.copytree(store.run_dir, copy)
    assert st.controller_owned(copy) == store.run_id
    assert any("not the run's directory" in p for p in store.check_binding(copy))
    assert store.check_binding() == []
    # Replace the original by the copy: the inode differs, resume is refused, custody stays put.
    shutil.move(str(store.run_dir), str(tmp_path / "moved-away"))
    shutil.move(str(copy), str(store.run_dir))
    assert any("not the run's original directory" in p for p in store.check_binding())
    assert [r["record"] for r in store.scan("budget")] == [{"spent": {"wall_seconds": 120}}]
    with pytest.raises(st.StoreError, match="must be new"):
        st.RunStore.create(store.run_dir, root=tmp_path / "store")


def test_R11_checkpoints_resume_from_the_store_after_the_run_directory_loses_its_files(tmp_path):
    from langgraph.graph import END, START, StateGraph
    from typing import TypedDict

    class State(TypedDict, total=False):
        n: int

    store = _create(tmp_path)
    builder = StateGraph(State)
    builder.add_node("step", lambda s: {"n": s.get("n", 0) + 1})
    builder.add_edge(START, "step")
    builder.add_edge("step", END)
    config = {"configurable": {"thread_id": "t"}}
    app = builder.compile(checkpointer=store.checkpointer())
    app.invoke({"n": 41}, config)
    store.close()
    for path in store.run_dir.iterdir():
        if path.name != st.RUN_MARKER:
            shutil.rmtree(path) if path.is_dir() else path.unlink()
    reopened = st.RunStore(store.run_id, root=tmp_path / "store")
    app = builder.compile(checkpointer=reopened.checkpointer())
    assert app.get_state(config).values == {"n": 42}
    reopened.close()


def test_store_for_follows_the_marker_and_new_runs_refuse_existing_directories(tmp_path):
    store = _create(tmp_path)
    assert st.store_for(store.run_dir, root=tmp_path / "store").run_id == store.run_id
    with pytest.raises(st.StoreError):
        st.store_for(tmp_path, root=tmp_path / "store")
    (tmp_path / "existing").mkdir()
    with pytest.raises(st.StoreError, match="must be new"):
        st.RunStore.create(tmp_path / "existing", root=tmp_path / "store")
    with pytest.raises(st.StoreError, match="invalid run id"):
        st.RunStore("../escape", root=tmp_path / "store")


def test_a_damaged_marker_makes_ownership_unknown_and_every_caller_fails_closed(tmp_path):
    from ravel.controller import command_policy
    store = _create(tmp_path)
    marker = store.run_dir / st.RUN_MARKER
    for damage in ("{not json", '{"run_id": "../escape"}', "[]"):
        marker.write_text(damage)
        with pytest.raises(st.ControllerOwnershipUnknown):
            st.controller_owned(store.run_dir / "inputs")
        reason = command_policy.check(["approve", "--rundir", str(store.run_dir), "--quote", "q"])
        assert reason and "damaged controller-run marker" in reason
    marker.unlink()
    marker.mkdir()
    with pytest.raises(st.ControllerOwnershipUnknown):
        st.controller_owned(store.run_dir)
    with pytest.raises(st.StoreError):
        st.store_for(store.run_dir, root=tmp_path / "store")
