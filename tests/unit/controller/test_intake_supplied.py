"""Supplied input files are staged at intake as the run inputs plan steps read (``inputs/<name>``)."""
import hashlib
import os
from pathlib import Path

import pytest

from ravel.controller import graph
from ravel.workflow.graph_nodes import RecoveryHold


def _row(path):
    return {"kind": "measurement", "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size}


@pytest.fixture
def supplied(tmp_path):
    source = tmp_path / "supplied"
    source.mkdir()
    table = source / "toy_table.csv"
    table.write_text("g,n\n0.5,25\n")
    script = source / "toy_script.py"
    script.write_text("print('inert')\n")
    run = tmp_path / "run"
    run.mkdir()
    return run, table, script


def test_supplied_files_are_staged_once_by_their_recorded_digest(supplied):
    run, table, script = supplied
    rows = [_row(table), _row(script), {"kind": "directory", "path": str(table.parent), "sha256": None, "size": None}]
    staged = graph.stage_supplied_inputs(run, rows)
    assert [(s["name"], s["artifact"]) for s in staged] == [("toy_table.csv", "inputs/toy_table.csv"),
                                                            ("toy_script.py", "inputs/toy_script.py")]
    assert (run / "inputs" / "toy_table.csv").read_bytes() == table.read_bytes()
    assert staged[0]["sha256"] == rows[0]["sha256"] and not (run / "inputs" / "supplied").exists()
    # The directory row (a legacy or controller run) is classified by the entry, never staged.
    assert sorted(p.name for p in (run / "inputs").iterdir()) == ["toy_script.py", "toy_table.csv"]
    # A second intake (a resumed run) finds the copies unchanged and copies nothing again.
    before = (run / "inputs" / "toy_table.csv").stat().st_mtime_ns
    assert graph.stage_supplied_inputs(run, rows) == staged
    assert (run / "inputs" / "toy_table.csv").stat().st_mtime_ns == before


def test_a_changed_staged_copy_or_source_holds(supplied):
    run, table, script = supplied
    rows = [_row(table)]
    graph.stage_supplied_inputs(run, rows)
    (run / "inputs" / "toy_table.csv").write_text("g,n\n0.5,22\n")
    with pytest.raises(RecoveryHold) as held:
        graph.stage_supplied_inputs(run, rows)
    assert held.value.reason == "supplied_input_changed"
    # The entry's record pins the source bytes: a source changed after the entry recorded it is not staged.
    other = tmp = run.parent / "run2"
    tmp.mkdir()
    table.write_text("g,n\n0.5,99\n")
    with pytest.raises(RecoveryHold) as held:
        graph.stage_supplied_inputs(other, rows)
    assert held.value.reason == "supplied_input_changed" and not (other / "inputs" / "toy_table.csv").exists()


def test_name_collisions_and_links_are_refused(supplied):
    run, table, script = supplied
    twin = table.parent / "twin"
    twin.mkdir()
    (twin / "toy_table.csv").write_text("g,n\n")
    with pytest.raises(RecoveryHold) as held:
        graph.stage_supplied_inputs(run, [_row(table), _row(twin / "toy_table.csv")])
    assert held.value.reason == "supplied_input_collision"
    reading = table.parent / "reading.json"
    reading.write_text("{}")
    with pytest.raises(RecoveryHold) as held:
        graph.stage_supplied_inputs(run, [_row(reading)])
    assert held.value.reason == "supplied_input_collision"
    linked = run / "inputs" / "toy_script.py"
    linked.parent.mkdir(exist_ok=True)
    os.symlink(script, linked)
    with pytest.raises(RecoveryHold) as held:
        graph.stage_supplied_inputs(run, [_row(script)])
    assert held.value.reason == "supplied_input_linked"
