"""The curation record (evidence/curation.json): curated wording in hash-pinned and historical records.

A curated record keeps its original identity traceable: its entry maps the original sha256 and size
to the curated ones, names the records that pinned the original digest, and says what wording
changed and why. A check that pinned the original digest accepts the file only as exactly that
curated copy.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("ravel_layout_under_test", REPO / "src/ravel/evidence_layout.py")
layout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(layout)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _write(root, relative, text):
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode() if isinstance(text, str) else text)
    return path


def _entry(original, curated, pinned_by=(), change="a citation is reworded", reason="public wording"):
    return {"original_sha256": _sha(original), "original_bytes": len(original),
            "curated_sha256": _sha(curated), "curated_bytes": len(curated),
            "pinned_by": list(pinned_by), "change": change, "reason": reason}


def _record(root, records):
    _write(root, layout.CURATION_RECORD, json.dumps({"schema_version": 1, "purpose": "test",
                                                     "records": records}))


def _registry(root, collections=None):
    distribution = {"files": ["README.md"], "extra_files": [], "trees": ["docs", "evidence", "src"],
                    "exclude": []}
    registry = {"schema_version": 1, "collections": collections or [{
        "source": "trial-runs/run_a", "destination": "evidence/scans/run-a", "source_run_id": "run_a",
        "title": "Run A", "kind": "scan", "include": ["RESULT.md"], "exclude": []}],
        "distribution": distribution}
    _write(root, layout.REGISTRY, json.dumps(registry))


ORIGINAL = b'{"source": "control; inputs kept beside the Secret Plan", "events": 100}\n'
CURATED = b'{"source": "control", "events": 100}\n'
EDITS = [{"old": "control; inputs kept beside the Secret Plan\"", "new": "control\""}]


# --------------------------------------------------------------------------- the shipped record

def test_the_shipped_curation_record_verifies_in_this_tree():
    # A tree whose settings name a layout module verifies the record with it; otherwise the shipped
    # module does.
    assert (layout.source_module(REPO) or layout).curation_errors(REPO) == []
    record = layout.load_curation_record(REPO)
    assert record, "the distribution carries curated records"
    for relative, entry in record.items():
        assert layout.resolve(REPO, relative).is_file(), relative
        assert entry["original_sha256"] != entry["curated_sha256"]
        # Every pin that recorded the original digest still carries it.
        for pin in entry["pinned_by"]:
            assert entry["original_sha256"] in layout.resolve(REPO, pin).read_text(), (relative, pin)


def test_audit_checks_accept_curated_records_through_the_record():
    record = layout.load_curation_record(REPO)
    for relative, entry in record.items():
        data = layout.resolve(REPO, relative).read_bytes()
        assert layout.pin_matches(REPO, relative, entry["original_sha256"], _sha(data), record)


# --------------------------------------------------------------------------- a distributed tree

def test_public_tree_accepts_exactly_the_curated_identity(tmp_path):
    _registry(tmp_path)
    _write(tmp_path, "evidence/audit/spec.json", CURATED)
    _write(tmp_path, "evidence/audit/hashes.json", json.dumps({"spec": _sha(ORIGINAL)}))
    _record(tmp_path, {"evidence/audit/spec.json": _entry(ORIGINAL, CURATED, ["evidence/audit/hashes.json"])})
    assert layout.curation_errors(tmp_path) == []
    _write(tmp_path, "evidence/audit/spec.json", CURATED.replace(b"100", b"101"))
    assert any("curated identity" in e for e in layout.curation_errors(tmp_path))


def test_the_original_identity_must_stay_pinned(tmp_path):
    _registry(tmp_path)
    _write(tmp_path, "evidence/audit/spec.json", CURATED)
    _write(tmp_path, "evidence/audit/hashes.json", json.dumps({"spec": "0" * 64}))
    _record(tmp_path, {"evidence/audit/spec.json": _entry(ORIGINAL, CURATED, ["evidence/audit/hashes.json"])})
    assert any("does not carry its original digest" in e for e in layout.curation_errors(tmp_path))


@pytest.mark.parametrize("mutate, message", [
    (lambda e: e.update(curated_sha256="ABC"), "lower-case sha256"),
    (lambda e: e.update(curated_bytes=-1), "byte count"),
    (lambda e: e.update(change=" "), "what changed"),
    (lambda e: e.update(curated_sha256=e["original_sha256"]), "must change"),
    (lambda e: e.pop("reason"), "exactly"),
    (lambda e: e.update(pinned_by=["a.json", "a.json"]), "unique"),
])
def test_malformed_record_entries_are_rejected(tmp_path, mutate, message):
    entry = _entry(ORIGINAL, CURATED)
    mutate(entry)
    _record(tmp_path, {"evidence/audit/spec.json": entry})
    with pytest.raises(ValueError, match=message):
        layout.load_curation_record(tmp_path)


def test_pin_matches_only_the_recorded_curated_copy(tmp_path):
    record = {"benchmarks/cases.json": _entry(ORIGINAL, CURATED)}
    _record(tmp_path, record)
    original, curated = _sha(ORIGINAL), _sha(CURATED)
    assert layout.pin_matches(tmp_path, "benchmarks/cases.json", original, original)
    assert layout.pin_matches(tmp_path, "benchmarks/cases.json", original, curated)
    assert not layout.pin_matches(tmp_path, "benchmarks/cases.json", original, _sha(b"other"))
    assert not layout.pin_matches(tmp_path, "benchmarks/cases.json", "0" * 64, curated)
    assert not layout.pin_matches(tmp_path, "benchmarks/other.json", original, curated)
    assert not layout.pin_matches(tmp_path / "absent", "benchmarks/cases.json", original, curated)


def test_pin_matches_a_pin_recorded_under_the_source_path(tmp_path):
    # Audit records may pin a historical file by its original (source) path; the record uses public paths.
    _registry(tmp_path)
    _record(tmp_path, {"evidence/scans/run-a/RESULT.md": _entry(ORIGINAL, CURATED)})
    assert layout.pin_matches(tmp_path, "trial-runs/run_a/RESULT.md", _sha(ORIGINAL), _sha(CURATED))
    assert not layout.pin_matches(tmp_path, "trial-runs/run_a/RESULT.md", _sha(ORIGINAL), _sha(b"other"))


# --------------------------------------------------------------------------- the audit checks

def _load_script(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retained_audit_check_accepts_only_the_recorded_curated_script(tmp_path):
    checker = _load_script("check_rrr_audits")
    audit = "evidence/audits/2026-09-05-rrr-diagnosis"
    shutil.copytree(REPO / audit, tmp_path / audit)
    records = {k: v for k, v in layout.load_curation_record(REPO).items() if k.startswith(audit + "/")}
    script = tmp_path / audit / "diagnose.py"
    provenance = json.loads((tmp_path / audit / "provenance.json").read_text())
    original_bytes = records.get(f"{audit}/diagnose.py", {}).get("original_bytes", len(script.read_bytes()))
    curated = script.read_bytes() + b"\n# reworded comment\n"
    script.write_bytes(curated)
    assert any("diagnostic code changed" in e for e in checker.check(tmp_path))
    records[f"{audit}/diagnose.py"] = {
        "original_sha256": provenance["script_sha256"], "original_bytes": original_bytes,
        "curated_sha256": _sha(curated), "curated_bytes": len(curated),
        "pinned_by": [], "change": "a comment", "reason": "test"}
    _record(tmp_path, records)
    assert checker.check(tmp_path) == []
    script.write_bytes(curated + b"# a further change\n")
    assert any("diagnostic code changed" in e for e in checker.check(tmp_path))


def test_evidence_check_accepts_a_curated_manifest_artifact_only_as_its_curated_copy(tmp_path):
    """A historical record curated for the distribution keeps its original digest in the evidence
    manifest; check_evidence accepts the shipped file only as the exact copy the record maps from it."""
    checker = _load_script("check_evidence")
    _registry(tmp_path)
    path = "evidence/scans/run-a/RESULT.md"
    original, curated = b"see the Secret Plan\n", b"see the plan\n"
    _write(tmp_path, path, curated)
    artifact = {"path": path, "shipped": True, "sha256": _sha(original), "bytes": len(original)}
    assert not checker._present_matching(artifact, tmp_path)[0]
    _record(tmp_path, {path: _entry(original, curated, ["evidence/manifest.json"])})
    assert checker._present_matching(artifact, tmp_path) == (True, "ok (curated copy)")
    _write(tmp_path, path, curated + b"x")
    assert not checker._present_matching(artifact, tmp_path)[0]
