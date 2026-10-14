"""Private synthetic custody controls; no actual scientific run or role vote."""
import hashlib
import json
from pathlib import Path

import pytest

from ravel.workflow import execution, physics_review, review_context as context


CURRENT = "1" * 32
HISTORICAL = "2" * 32


def event(cycle=HISTORICAL):
    value = {
        "schema_version": 1, "sequence": 2, "previous_sha256": "a" * 64,
        "run_id": "historical-run" if cycle == HISTORICAL else "current-run",
        "utc": "2026-10-07T12:00:00+00:00", "event": "review", "cycle_id": cycle,
        "role": "physics_critic", "actor_id": "synthetic-critic", "verdict": "accept",
        "summary": "SYNTHETIC-REVIEW-VERDICT", "findings": [], "closes": [],
        "claim_scope": "synthetic_delivery", "attestation": physics_review.ATTESTATION,
    }
    value["sha256"] = execution.digest(value)
    return value


def frozen(root, identity, value):
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    digest = hashlib.sha256(raw).hexdigest()
    relative = f"logs/physics_review/snapshots/{digest}.blob"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(raw)
    return {"path": identity, "sha256": digest, "size": len(raw), "snapshot": relative}


def opened(monkeypatch, root, pins, *, current_reviews=()):
    cycle = {"event": "cycle", "cycle_id": CURRENT, "sha256": "b" * 64,
             "snapshots": pins, "checks": [], "inherited_findings": []}
    reg = {"run_id": "current-run", "policy": {
        "claim_scopes": {"synthetic_delivery": {"checks": [], "actions": ["delivery"]}},
        "required_checks": []}}
    monkeypatch.setattr(physics_review, "_read", lambda value, **kwargs: (reg, [cycle, *current_reviews]))


@pytest.mark.parametrize("role", ["critic", "verifier", "synthesizer"])
def test_absolute_historical_journal_omitted_without_decoding(monkeypatch, tmp_path, role):
    root = tmp_path / "current"
    root.mkdir()
    source = str(tmp_path / "past" / "logs/physics_review/events/00000002.json")
    row = frozen(root, source, event())
    opened(monkeypatch, root, [row])
    monkeypatch.setattr(context, "_frozen_bytes", lambda *args: pytest.fail("journal text was decoded"))
    manifest = context.create(root, role, tmp_path / role)
    assert manifest["artifacts"] == []
    omitted = manifest["omissions"][0]
    assert omitted["source_path"] == source and omitted["source_sha256"] == row["sha256"]
    assert omitted["source_size"] == row["size"]
    assert omitted["review_custody"]["run_root"] == str(tmp_path / "past")
    assert omitted["review_custody"]["relation"] == "historical_run"
    assert "SYNTHETIC-REVIEW-VERDICT" not in json.dumps(manifest)


@pytest.mark.parametrize("identity", [
    "logs/physics_review/events/00000002.json", "logs/physics_review/registration.json",
    "logs/physics_review/snapshots/abc.blob", "logs/physics_review/nested/report.json",
])
def test_current_journal_ancestor_recognized(tmp_path, identity):
    root = tmp_path / "current"
    result = context._review_journal_custody(root, identity)
    assert result["relation"] == "current_run" and result["run_root"] == str(root)


@pytest.mark.parametrize("identity", [
    "logs/science/record.json", "inputs/physics_review_calibration.json",
    "inputs/review-vote.json", "outputs/analysis-review/events.json",
    "data/logs/physics_review_source/calibration.json", "logs/physics_reviewish/plot.json",
])
def test_scientific_names_and_near_prefixes_not_classified(tmp_path, identity):
    assert context._review_journal_custody(tmp_path, identity) is None


def test_sibling_run_prefix_is_historical_not_current(tmp_path):
    root = tmp_path / "run"
    sibling = tmp_path / "run-old" / "logs/physics_review/head.json"
    assert context._review_journal_custody(root, str(sibling))["relation"] == "historical_run"


def test_symlink_ancestor_refused_without_output(monkeypatch, tmp_path):
    root = tmp_path / "current"
    root.mkdir()
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(real, target_is_directory=True)
    row = frozen(root, str(link / "logs/physics_review/events/x.json"), event())
    opened(monkeypatch, root, [row])
    out = tmp_path / "packet"
    with pytest.raises(ValueError, match="symlinks"):
        context.create(root, "critic", out)
    assert not out.exists()


@pytest.mark.parametrize("role", ["critic", "verifier", "synthesizer"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_explicit_historical_vote_record_omitted(monkeypatch, tmp_path, role, wrapped):
    root = tmp_path / "current"
    root.mkdir()
    value = {"action": "submit", "review_event": event(), "native_calls": 0} if wrapped else event()
    row = frozen(root, "inputs/prerequisite-own-vote.json", value)
    opened(monkeypatch, root, [row])
    manifest = context.create(root, role, tmp_path / "packet")
    assert manifest["artifacts"] == [] and len(manifest["omissions"]) == 1
    omitted = manifest["omissions"][0]
    assert omitted["review_custody"]["cycle_id"] == HISTORICAL
    assert omitted["source_sha256"] == row["sha256"] and omitted["source_size"] == row["size"]
    assert "SYNTHETIC-REVIEW-VERDICT" not in json.dumps(manifest)


@pytest.mark.parametrize("change", ["partial", "changed_hash", "extra_scientific_field", "wrong_kind", "bool_schema"])
def test_non_event_documents_are_not_silently_discarded(change):
    value = event()
    if change == "partial":
        value = {"verdict": "accept", "summary": "measured spectrum", "nll": 0.125}
    elif change == "changed_hash":
        value["sha256"] = "0" * 64
    elif change == "extra_scientific_field":
        value["independent_nll"] = -2.25
    elif change == "wrong_kind":
        value["event"] = "source_comparison"
        value["sha256"] = execution.digest({k: v for k, v in value.items() if k != "sha256"})
    else:
        value["schema_version"] = True
        value["sha256"] = execution.digest({k: v for k, v in value.items() if k != "sha256"})
    assert context._review_event_identity(value) is None
    assert context._review_record_custody(value, CURRENT, "critic") is None


def test_numerical_evidence_and_failed_witness_preserved(monkeypatch, tmp_path):
    root = tmp_path / "current"
    root.mkdir()
    documents = {
        "inputs/settings.cfg": b"mu bounds=-15,15\n",
        "outputs/attempt-1/native-ward-checks.json": {"helicities": [[-1, -1, -1, -1]], "m2": 0.6},
        "logs/execution/science/a/record.json": {"status": "succeeded", "exit_code": 0},
        "inputs/numerical-witness.json": {"kind": "numerical_witness_receipt", "status": "failed", "delta": 0.25},
        "inputs/review-vote.json": {"verdict": "accept", "data": [1, -2, 0]},
        "inputs/calibration.json": {"action": "calculate", "review_event": event(), "means": [2, 3]},
    }
    pins = [frozen(root, identity, value) for identity, value in documents.items()]
    opened(monkeypatch, root, pins)
    manifest = context.create(root, "critic", tmp_path / "packet")
    assert not manifest["omissions"]
    observed = {entry["source_path"]: context.read_artifact(
        tmp_path / "packet", entry["id"], expected_manifest_sha256=manifest["sha256"])
        for entry in manifest["artifacts"]}
    for identity, original in documents.items():
        assert observed[identity] == (original if isinstance(original, bytes) else json.dumps(original).encode())


def test_current_synthesis_preserves_own_cycle_reviews(monkeypatch, tmp_path):
    root = tmp_path / "current"
    root.mkdir()
    current = event(CURRENT)
    row = frozen(root, "inputs/current-review-copy.json", current)
    opened(monkeypatch, root, [row], current_reviews=[current])
    synth = context.create(root, "synthesizer", tmp_path / "synth")
    critic = context.create(root, "critic", tmp_path / "critic")
    assert synth["reviews"] == [current] and len(synth["artifacts"]) == 1
    assert critic["reviews"] == [] and not critic["artifacts"]
    raw = context.read_artifact(tmp_path / "synth", synth["artifacts"][0]["id"],
                                expected_manifest_sha256=synth["sha256"])
    assert json.loads(raw) == current


def test_existing_repair_obligation_remains(monkeypatch, tmp_path):
    root = tmp_path / "current"
    root.mkdir()
    finding = {"id": "SYNTHETIC-F1", "summary": "Need independent endpoint witness",
               "evidence": [{"path": "outputs/raw.json", "location": "/nll"}],
               "check_ids": ["endpoint"], "required_paths": [], "required_stages": []}
    current = event(CURRENT)
    current["findings"] = [finding]
    current["sha256"] = execution.digest({k: v for k, v in current.items() if k != "sha256"})
    opened(monkeypatch, root, [], current_reviews=[current])
    verifier = context.create(root, "verifier", tmp_path / "verifier")
    assert verifier["findings"] == [finding] and verifier["reviews"] == []


def test_frozen_source_hash_and_external_packet_digest_still_enforced(monkeypatch, tmp_path):
    root = tmp_path / "current"
    root.mkdir()
    row = frozen(root, "inputs/observations.json", {"nll": -2.25})
    opened(monkeypatch, root, [row])
    packet = tmp_path / "packet"
    manifest = context.create(root, "critic", packet)
    with pytest.raises(ValueError, match="manifest changed"):
        context.read_artifact(packet, "a0000", expected_manifest_sha256="0" * 64)
    (packet / manifest["artifacts"][0]["path"]).write_bytes(b"different data")
    with pytest.raises(ValueError, match="changed"):
        context.read_artifact(packet, "a0000", expected_manifest_sha256=manifest["sha256"])


def test_explicit_vote_hash_is_checked_before_classification(monkeypatch, tmp_path):
    root = tmp_path / "current"
    root.mkdir()
    row = frozen(root, "inputs/prerequisite-vote.json", event())
    opened(monkeypatch, root, [row])
    (root / row["snapshot"]).write_bytes(b"different review content")
    with pytest.raises(ValueError, match="frozen context evidence changed"):
        context.create(root, "critic", tmp_path / "packet")
    assert not (tmp_path / "packet").exists()


def test_submission_with_scientific_payload_is_not_discarded():
    value = {"action": "submit", "review_event": event(), "observations": [1, -2, 0],
             "independent_nll": -2.25}
    assert context._review_record_custody(value, CURRENT, "critic") is None


def test_synthesis_deep_scientific_json_keeps_exact_bytes(monkeypatch, tmp_path):
    root = tmp_path / "current"
    root.mkdir()
    raw = b'{"measurements":' + b'[' * 1500 + b'0' + b']' * 1500 + b'}'
    row = frozen(root, "inputs/deep-scientific-data.json", raw)
    opened(monkeypatch, root, [row])
    packet = tmp_path / "packet"
    manifest = context.create(root, "synthesizer", packet)
    assert not manifest["omissions"]
    assert context.read_artifact(packet, "a0000", expected_manifest_sha256=manifest["sha256"]) == raw


def test_frozen_non_journal_evidence_does_not_follow_replaced_original_alias(monkeypatch, tmp_path):
    root = tmp_path / "current"
    root.mkdir()
    original = tmp_path / "original-observations.json"
    original.write_bytes(b'{"nll": -2.25}')
    row = frozen(root, str(original), original.read_bytes())
    substitute = tmp_path / "substitute.json"
    substitute.write_bytes(b'{"nll": 99}')
    original.unlink()
    original.symlink_to(substitute)
    opened(monkeypatch, root, [row])
    packet = tmp_path / "packet"
    manifest = context.create(root, "critic", packet)
    assert not manifest["omissions"]
    assert context.read_artifact(packet, "a0000", expected_manifest_sha256=manifest["sha256"]) == b'{"nll": -2.25}'
