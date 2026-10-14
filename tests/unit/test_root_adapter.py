"""Independent finite adapter witnesses; synthetic arithmetic, no native calls."""
import hashlib
import json

import pytest
from test_cr_signal_study import fixture
from ravel.validation import cr_signal_study as s


def test_unmodified_complete_delivery_is_self_consistent(fixture, tmp_path):
    out = tmp_path / "out"
    result = s.run(fixture[0], tmp_path, out)
    assert result["status"] == "passed"
    rows = [json.loads(line) for line in (out / "progress.jsonl").read_text().splitlines()]
    assert rows[-1]["state_sha256"] == result["checkpoint_sha256"]
    assert hashlib.sha256((out / "checkpoint.json").read_bytes()).hexdigest() == result["checkpoint_sha256"]
    assert len(json.loads((out / "checkpoint.json").read_text())["calls"]) == 45


@pytest.mark.parametrize("target", ["checkpoint.json", "progress.jsonl"])
def test_late_diagnostic_output_change_cannot_be_delivered_as_passed(fixture, tmp_path, monkeypatch, target):
    out = tmp_path / "out"
    def ending_import_observation(inventory):
        # Simulate an output changing after the last numerical persistence, but
        # before the adapter's ending custody and claimed successful delivery.
        (out / target).write_text('{"unrelated": true}\n')
        return [{"module": "explicit synthetic observation"}]
    monkeypatch.setattr(s, "observed_imports", ending_import_observation)
    result = s.run(fixture[0], tmp_path, out)
    assert result["status"] == "failed", result
    assert (out / target).read_text() == '{"unrelated": true}\n'


def test_late_source_change_cannot_be_delivered_as_passed(fixture, tmp_path, monkeypatch):
    def ending_import_observation(inventory):
        from pathlib import Path
        Path(fixture[0]["input"]).write_text('{"unrelated": true}\n')
        return [{"module": "explicit synthetic observation"}]
    monkeypatch.setattr(s, "observed_imports", ending_import_observation)
    result = s.run(fixture[0], tmp_path, tmp_path / "out")
    assert result["status"] == "failed"
    assert result["ending_errors"]
