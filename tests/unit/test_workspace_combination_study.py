import hashlib
import json
from pathlib import Path

import pytest

from ravel.physics import workspace_combination_study as study


def write(path, value):
    path.write_text(json.dumps(value))
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def captured(tmp_path, monkeypatch):
    model = tmp_path / "model.json"
    model_pin = write(model, {"measurement": "m"})
    archive = tmp_path / "archive.bin"; archive.write_bytes(b"source")
    workspace_pin = write(tmp_path / "workspace.json", {"observations": []})
    policy_pin = write(tmp_path / "policy.json", {"measurement": "combined"})
    grounding = write(tmp_path / "grounding.json", {"source_prescribed_independence": True})
    document = {"schema_version": 1, "protocol": study.PROTOCOL,
                "components": [{"id": name, "published_model": model_pin,
                                "prepared_workspace": workspace_pin, "parameter_map": {"mu": "mu"}}
                               for name in ("a", "b")],
                "policy": policy_pin, "grounding": [grounding]}
    path = tmp_path / "input.json"; write(path, document)
    monkeypatch.setattr(study.pm, "validate_document", lambda x: x)
    monkeypatch.setattr(study.pm, "inputs", lambda *args: [model, archive])
    class Contract:
        def workspace(self): return {"observations": []}
        def manifest(self): return {"literal_source": "retained", "inference": False}
    monkeypatch.setattr(study.pm, "load_published_model", lambda *args: Contract())
    import pyhf
    monkeypatch.setattr(pyhf, "set_backend", lambda *args, **kwargs: None)
    monkeypatch.setattr(study.pm, "run", lambda *args: pytest.fail("inference route invoked"))
    return path, document, archive


def state(passed=True, calls=20, status="completed"):
    return {"status": status, "passed": passed, "calls": calls, "points": [],
            "journal": [{"status": "returned", "value": [1.25, 0.75]}]}


def install(monkeypatch, value):
    def qualify(*args, **kwargs):
        assert kwargs["max_calls"] == 20 and kwargs["max_seconds"] == 60.
        assert kwargs["mean_atol"] == 1e-9 and kwargs["density_atol"] == 1e-7
        kwargs["record"](value)
        return value
    monkeypatch.setattr(study.witness, "qualify", qualify)


def test_complete_fake_return_is_recorded_and_successful(captured, tmp_path, monkeypatch):
    install(monkeypatch, state())
    result = study.run({"input": str(captured[0])}, tmp_path, tmp_path / "out")
    assert result["status"] == "passed" and result["fits"] == 0
    assert json.loads((tmp_path / "out/combination-checkpoint.json").read_text()) == state()
    assert len((tmp_path / "out/combination-progress.jsonl").read_text().splitlines()) == 1


@pytest.mark.parametrize("value", [state(False), state(calls=19), state(status="running")])
def test_incomplete_or_false_comparison_cannot_pass(captured, tmp_path, monkeypatch, value):
    install(monkeypatch, value)
    result = study.run({"input": str(captured[0])}, tmp_path, tmp_path / "out")
    assert result["status"] == "failed" and result["error"]
    assert json.loads((tmp_path / "out/combination-checkpoint.json").read_text()) == value


def test_late_failure_preserves_previous_actual_serialization(captured, tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        kwargs["record"](state(status="running", calls=1))
        raise TimeoutError("after returned evaluation")
    monkeypatch.setattr(study.witness, "qualify", fail)
    result = study.run({"input": str(captured[0])}, tmp_path, tmp_path / "out")
    assert result["status"] == "failed" and result["error"]["type"] == "TimeoutError"
    assert json.loads((tmp_path / "out/combination-checkpoint.json").read_text())["journal"][0]["value"] == [1.25, .75]


def test_ending_changed_source_refuses_even_complete_return(captured, tmp_path, monkeypatch):
    def change(*args, **kwargs):
        captured[2].write_bytes(b"changed")
        value = state(); kwargs["record"](value); return value
    monkeypatch.setattr(study.witness, "qualify", change)
    result = study.run({"input": str(captured[0])}, tmp_path, tmp_path / "out")
    assert result["status"] == "failed" and result["ending_input_errors"] == [str(captured[2])]


def test_fresh_directory_refuses_before_capture(tmp_path, monkeypatch):
    out = tmp_path / "out"; out.mkdir(); (out / "old.json").write_text("old")
    monkeypatch.setattr(study, "_capture", lambda *args: pytest.fail("capture reached"))
    with pytest.raises((ValueError, FileExistsError)):
        study.run({"input": "unused"}, tmp_path, out)
    assert (out / "old.json").read_text() == "old"


def test_source_inputs_include_full_import_dependencies(captured, tmp_path):
    result = study.inputs({"input": str(captured[0])}, tmp_path)
    assert captured[0] in result and captured[2] in result and len(result) == 6


def test_unauthorized_tolerance_and_source_hash_changes_refuse(captured, tmp_path):
    path, document, _ = captured
    document["protocol"] = dict(study.PROTOCOL, density_atol=1e-4)
    write(path, document)
    with pytest.raises(ValueError, match="exact reviewed"):
        study.inputs({"input": str(path)}, tmp_path)
    document["protocol"] = study.PROTOCOL
    document["components"][0]["published_model"]["sha256"] = "0"*64
    write(path, document)
    with pytest.raises(ValueError, match="hash differs"):
        study.inputs({"input": str(path)}, tmp_path)


def test_import_must_match_prepared_complete_workspace(captured, tmp_path, monkeypatch):
    class Wrong:
        def workspace(self): return {"observations": [{"dropped": True}]}
    monkeypatch.setattr(study.pm, "load_published_model", lambda *args: Wrong())
    monkeypatch.setattr(study.witness, "qualify", lambda *args, **kwargs: pytest.fail("numerics reached"))
    result = study.run({"input": str(captured[0])}, tmp_path, tmp_path / "out")
    assert result["status"] == "failed" and "prepared complete" in result["error"]["message"]


def test_checkpoint_tampering_and_nonfinite_snapshot_keep_last_good(tmp_path):
    recorder = study.Recorder(tmp_path)
    recorder(state())
    good = (tmp_path / "combination-checkpoint.json").read_bytes()
    with pytest.raises(ValueError): recorder({"value": float("nan")})
    assert (tmp_path / "combination-checkpoint.json").read_bytes() == good
    (tmp_path / "combination-checkpoint.json").write_text("{}")
    with pytest.raises(ValueError, match="checkpoint changed"): recorder(state())
