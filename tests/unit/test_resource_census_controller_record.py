"""The controller's census of a reading that names no analysis or topic is a typed record, not a usage error."""
import json

import pytest

from ravel.validation import validate_run_state
from ravel.workflow import resource_census


def _reading(facts):
    return {"schema_version": 1, "facts": facts, "deliverables": []}


def test_no_target_reading_writes_an_absent_rung_and_consults_no_source(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("no public source may be consulted for a reading that names no target")
    monkeypatch.setattr(resource_census, "census_one", refuse)
    monkeypatch.setattr(resource_census, "keyword_search", refuse)
    reading = tmp_path / "reading.json"
    reading.write_text(json.dumps(_reading([{"type": "supplied_file", "value": {"path": "inputs/toy.py"}},
                                            {"type": "parameter_value", "value": {"symbol": "g", "value": "0.5"}}])))
    out = tmp_path / "run" / "inputs" / "resource_census.json"
    out.parent.mkdir(parents=True)
    assert resource_census.main(["--reading", str(reading), "--controller-output", str(out)]) == 0
    record = json.loads(out.read_text())
    assert record["records"] == [] and record["targets"] == {"analyses": [], "keywords": []}
    [(name, rung)] = record["rungs"].items()
    assert name == "reading/targets" and rung["status"] == "ABSENT" and "no public source" in rung["reason"]
    # The run-state validator reads it as a walked sweep with no successful public rung: WARN, never PASS or FAIL.
    status, path, checks = validate_run_state.check_resource_census(
        str(tmp_path / "run"), {}, {"resource_census_path": "inputs/resource_census.json"}, "R", False)
    assert status == "WARN", checks


def test_hand_typed_invocations_without_a_target_still_refuse(tmp_path, capsys):
    reading = tmp_path / "reading.json"
    reading.write_text(json.dumps(_reading([])))
    with pytest.raises(SystemExit) as stopped:
        resource_census.main(["--reading", str(reading)])
    assert stopped.value.code == 2
    with pytest.raises(SystemExit) as stopped:
        resource_census.main(["--reading", str(reading), "--rundir", str(tmp_path / "run")])
    assert stopped.value.code == 2
    assert "names an analysis or topic" in capsys.readouterr().err
