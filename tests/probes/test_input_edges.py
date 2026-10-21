"""Bounded supplied-event probes at the actual pre-shower boundary."""
import gzip
import hashlib
import json
from types import SimpleNamespace

import pytest

import production_fixtures as fixtures
from ravel.validation.lhe_check import guard_shower


def staged(tmp_path):
    # Reuse the existing fictional event fixture; no event generator runs.
    fixtures.production_task(tmp_path)
    raw = (tmp_path / "events.lhe").read_bytes()
    event = tmp_path / "process/Events/sample/events.lhe.gz"
    event.parent.mkdir(parents=True)
    event.write_bytes(gzip.compress(raw, mtime=0))
    calls = []
    report = tmp_path / "pre-shower.json"
    def invoke(**policy):
        guarded = guard_shower(lambda self: calls.append("shower"), process=tmp_path / "process",
                               run_name="sample", output=report, **policy)
        return guarded(SimpleNamespace(me_dir=str(tmp_path / "process")))
    return event, raw, calls, report, invoke


def test_truncated_compressed_events_leave_diagnostic_before_shower(tmp_path):
    event, raw, calls, report, invoke = staged(tmp_path)
    event.write_bytes(event.read_bytes()[:-6])
    with pytest.raises(ValueError, match='Restore the complete event file'):
        invoke()
    assert calls == []
    assert report.is_file(), "Truncated compressed input needs a persisted pre-shower refusal for resume."
    record = json.loads(report.read_text())
    assert record["verdict"] == "FAIL" and record["failures"]
    assert record["lhe"]["sha256"] == hashlib.sha256(event.read_bytes()).hexdigest()
    assert record['input_diagnostic']['error_type'] == 'EOFError'
    assert 'rerun the pre-shower check' in record['input_diagnostic']['remedy']


def test_signed_weight_in_compressed_input_requires_declared_scheme(tmp_path):
    event, raw, calls, report, invoke = staged(tmp_path)
    # Alter only the first event's nominal weight; retain valid framing and all later events.
    prefix, body = raw.split(b"<event>", 1)
    lines = body.splitlines()
    first = next(i for i, line in enumerate(lines) if line.strip())
    fields = lines[first].split()
    fields[2] = b"-1.0"
    lines[first] = b" ".join(fields)
    changed = prefix + b"<event>" + b"\n".join(lines) + b"\n"
    event.write_bytes(gzip.compress(changed, mtime=0))
    with pytest.raises(ValueError, match="negative weights"):
        invoke(allow_negative=False)
    assert calls == [] and json.loads(report.read_text())["verdict"] == "FAIL"
    invoke(allow_negative=True)
    record = json.loads(report.read_text())
    assert calls == ["shower"] and record["verdict"] == "PASS" and record["allow_negative"] is True
    assert gzip.decompress(event.read_bytes()) == changed


def test_automatic_width_with_missing_mass_block_refuses_before_shower(tmp_path):
    event, raw, calls, report, invoke = staged(tmp_path)
    card = tmp_path / "supplied-card.dat"
    card.write_text("DECAY 9000001 Auto\n 1.0 2 11 -11\n")
    before = card.read_bytes()
    with pytest.raises(ValueError, match="no parsable Block MASS"):
        invoke(param_card=card)
    assert calls == [] and card.read_bytes() == before
    record = json.loads(report.read_text())
    assert record["verdict"] == "FAIL" and any("Block MASS" in cause for cause in record["failures"])
