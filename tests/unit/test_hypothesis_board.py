"""Advisory sealing, conservative prediction equivalence and local custody."""
from copy import deepcopy
import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ravel.workflow import hypothesis_board as board


def charter(actors=("alpha", "beta", "gamma"), **changes):
    result = {"schema_version": 1, "board_id": "bounded-study",
              "participants": [{"actor_id": actor, "model_id": f"declared-model-{actor}",
                                "session_id": f"session-{actor}", "fresh_generation": True} for actor in actors],
              "prediction_keys": ["shape", "acceptance"],
              "limits": dict(board.DEFAULT_LIMITS), "artifact_pins": []}
    result.update(changes)
    return result


def payload(actor="alpha", *, hypothesis_id="H1", shape="up", acceptance=None,
            statement="A bounded speculative hypothesis.", nonce=None, contradicts=None, refs=None):
    return {"schema_version": 1, "actor_id": actor, "session_id": f"session-{actor}",
            "nonce": nonce or f"initial-nonce-for-{actor}", "hypotheses": [
                {"id": hypothesis_id, "statement": statement,
                 "predictions": {"shape": shape, "acceptance": acceptance},
                 "artifact_refs": refs or [], "contradicts": contradicts or []}]}


def opened(tmp_path, *, actors=("alpha", "beta", "gamma"), submissions=None, name="board", policy=None):
    root = tmp_path / name
    policy = policy or charter(actors)
    submissions = submissions or [payload(actor) for actor in actors]
    board.create(root, policy)
    for submission in submissions:
        board.commit(root, submission["actor_id"], board.submission_digest(policy, submission))
    return root, policy, submissions


def revealed(tmp_path, **kwargs):
    root, policy, submissions = opened(tmp_path, **kwargs)
    for submission in submissions:
        board.reveal(root, submission)
    return root, policy, submissions


def read(path):
    return json.loads(path.read_bytes())


def write(path, document):
    path.write_text(json.dumps(document))


def test_sealed_commit_has_no_payload_and_premature_reveal_cannot_write(tmp_path):
    root, policy = tmp_path / "board", charter()
    board.create(root, policy)
    submission = payload()
    event = board.commit(root, "alpha", board.submission_digest(policy, submission))
    assert event["payload"] is None
    assert "bounded speculative" not in (root / "records/00000001.json").read_text()
    before = read(root / "head.json")
    with pytest.raises(ValueError, match="every participant to commit"):
        board.reveal(root, submission)
    assert read(root / "head.json") == before
    view = board.snapshot(root)
    assert view["phase"] == "sealed_commits" and view["hypotheses"] == []


def test_commit_binds_entire_payload_nonce_and_charter(tmp_path):
    root, policy, submissions = opened(tmp_path)
    for field in ("statement", "predictions", "nonce"):
        mutation = deepcopy(submissions[0])
        if field == "nonce":
            mutation[field] = "replacement-nonce-1234"
        elif field == "predictions":
            mutation["hypotheses"][0][field]["shape"] = "down"
        else:
            mutation["hypotheses"][0][field] = "A changed scientific statement."
        with pytest.raises(ValueError, match="sealed commit digest"):
            board.reveal(root, mutation)
    changed = deepcopy(policy)
    changed["participants"][0]["model_id"] = "another-declared-model"
    assert board.submission_digest(changed, submissions[0]) != board.submission_digest(policy, submissions[0])
    reordered = deepcopy(submissions[0])
    reordered["hypotheses"][0]["predictions"] = {"acceptance": None, "shape": "up"}
    board.reveal(root, reordered)
    assert board.snapshot(root)["counts"]["initial_revealed"] == 1


def test_all_six_publication_orders_have_identical_canonical_views(tmp_path):
    policy = charter()
    submissions = [payload("alpha", shape="up"), payload("beta", shape="down"),
                   payload("gamma", shape=None)]
    views, heads = [], []
    for index, order in enumerate(itertools.permutations(range(3))):
        root = tmp_path / f"order-{index}"
        board.create(root, policy)
        for position in reversed(order):
            item = submissions[position]
            board.commit(root, item["actor_id"], board.submission_digest(policy, item))
        for position in order:
            board.reveal(root, submissions[position])
        views.append(board.snapshot(root))
        heads.append(read(root / "head.json")["sha256"])
    assert all(view == views[0] for view in views)
    assert len(set(heads)) == 6  # Chronology remains in the journal, outside the canonical view.
    assert views[0]["counts"]["known_conflicts"] == 1


def test_exact_prediction_clones_preserve_provenance_and_add_zero_signature_novelty(tmp_path):
    root, _, _ = revealed(tmp_path, actors=("alpha",), submissions=[payload()])
    initial = board.snapshot(root)
    clone = payload(hypothesis_id="clone", statement="Different prose and hypothesis name.", nonce="clone-nonce-12345678")
    board.append(root, clone)
    view = board.snapshot(root)
    assert view["counts"]["prediction_groups"] == initial["counts"]["prediction_groups"] == 1
    assert view["counts"]["duplicate_predictions"] == 1
    assert len(view["prediction_groups"][0]["members"]) == 2
    assert {row["id"] for row in view["hypotheses"]} == {"H1", "clone"}
    assert len(view["submissions"]) == 2


def test_conflicting_known_predictions_are_retained_despite_duplicate_support(tmp_path):
    submissions = [payload("alpha", shape="up"), payload("beta", shape="up"), payload("gamma", shape="down")]
    root, _, _ = revealed(tmp_path, submissions=submissions)
    before = board.snapshot(root)
    target = next(row["hypothesis_sha256"] for row in before["hypotheses"] if row["actor_id"] == "alpha")
    dissent = payload("gamma", hypothesis_id="H2", shape="down", acceptance="lower",
                      nonce="dissent-nonce-123456", contradicts=[target])
    board.append(root, dissent)
    view = board.snapshot(root)
    assert len(view["hypotheses"]) == 4
    assert {row["predictions"]["shape"] for row in view["hypotheses"]} == {"up", "down"}
    assert view["counts"]["known_conflicts"] == 2
    assert next(row for row in view["hypotheses"] if row["id"] == "H2")["contradicts"] == [target]
    assert view["hypotheses"][:3] == before["hypotheses"]
    assert "winner" not in view and "majority" not in view


def test_unknown_is_retained_without_artificial_contradiction(tmp_path):
    root, _, _ = revealed(tmp_path, actors=("alpha", "beta"),
                          submissions=[payload("alpha", shape=None), payload("beta", shape="up")])
    view = board.snapshot(root)
    assert view["known_conflicts"] == []
    assert view["counts"]["prediction_groups"] == 2
    assert view["counts"]["informative_prediction_groups"] == 1


def test_prediction_equality_uses_content_even_if_report_signatures_collide(tmp_path, monkeypatch):
    root, _, _ = revealed(tmp_path, actors=("alpha", "beta"),
                          submissions=[payload("alpha", shape="down"), payload("beta", shape="up")])
    monkeypatch.setattr(board, "prediction_signature", lambda predictions: "0" * 64)
    view = board.snapshot(root)
    assert view["counts"]["prediction_groups"] == 2
    assert view["counts"]["duplicate_predictions"] == 0
    assert view["counts"]["known_conflicts"] == 1


def test_interrupted_head_update_rolls_forward_one_verified_record_only(tmp_path, monkeypatch):
    policy = charter(("alpha",))
    root = tmp_path / "board"
    board.create(root, policy)
    original = board._write
    def interrupted(directory, name, content, **kwargs):
        if name == "head.json":
            raise OSError("simulated interruption after record publication")
        return original(directory, name, content, **kwargs)
    monkeypatch.setattr(board, "_write", interrupted)
    item = payload()
    with pytest.raises(OSError, match="simulated interruption"):
        board.commit(root, "alpha", board.submission_digest(policy, item))
    monkeypatch.setattr(board, "_write", original)
    assert (root / "records/00000001.json").is_file()
    assert read(root / "head.json")["sequence"] == 0
    assert board.snapshot(root)["counts"]["committed"] == 1
    assert read(root / "head.json")["sequence"] == 1
    # A record beyond the head that does not verify is never adopted.
    forged = read(root / "records/00000001.json")
    forged.update(sequence=2, previous_sha256=forged["sha256"])
    write(root / "records/00000002.json", forged)
    with pytest.raises(ValueError, match="manual inspection"):
        board.snapshot(root)
    assert read(root / "head.json")["sequence"] == 1
    # Nor is a record that does not extend the retained head, even when its own chain is consistent.
    (root / "records/00000002.json").unlink()
    write(root / "head.json", {"schema_version": 1, "sequence": 0, "sha256": "c" * 64})
    with pytest.raises(ValueError, match="does not extend"):
        board.snapshot(root)


def test_followup_before_complete_initial_reveals_and_identity_reuse_are_refused(tmp_path):
    root, _, submissions = opened(tmp_path)
    board.reveal(root, submissions[0])
    followup = payload(hypothesis_id="H2", nonce="fresh-followup-123456")
    with pytest.raises(ValueError, match="every initial submission"):
        board.append(root, followup)
    with pytest.raises(ValueError, match="duplicate initial reveal"):
        board.reveal(root, submissions[0])
    with pytest.raises(ValueError, match="duplicate initial commit"):
        board.commit(root, "alpha", "0" * 64)
    for item in submissions[1:]:
        board.reveal(root, item)
    with pytest.raises(ValueError, match="identity is immutable"):
        board.append(root, payload(nonce="new-nonce-for-old-id"))
    with pytest.raises(ValueError, match="nonce has already"):
        board.append(root, payload(hypothesis_id="H3"))
    with pytest.raises(ValueError, match="previously retained"):
        board.append(root, payload(hypothesis_id="H4", nonce="fresh-unknown-target", contradicts=["0" * 64]))


@pytest.mark.parametrize("mutation", ["payload", "digest", "delete", "head", "charter"])
def test_on_disk_tampering_is_refused(tmp_path, mutation):
    root, _, _ = revealed(tmp_path, actors=("alpha",))
    record = root / "records/00000002.json"
    if mutation in {"payload", "digest"}:
        document = read(record)
        if mutation == "payload":
            document["payload"]["hypotheses"][0]["predictions"]["shape"] = "down"
        else:
            document["sha256"] = "0" * 64
        write(record, document)
    elif mutation == "delete":
        record.unlink()
    elif mutation == "head":
        document = read(root / "head.json")
        document["sha256"] = "0" * 64
        write(root / "head.json", document)
    else:
        document = read(root / "charter.json")
        document["charter"]["board_id"] = "rewritten-board"
        write(root / "charter.json", document)
    with pytest.raises(ValueError, match="changed|removed|checkpoint"):
        board.snapshot(root)


def test_externally_retained_pins_detect_valid_coordinated_local_replacement(tmp_path):
    root, policy, _ = revealed(tmp_path, actors=("alpha",))
    expected = board.snapshot(root)["charter_sha256"]
    expected_head = read(root / "head.json")["sha256"]
    assert board.snapshot(root, expected_charter_sha256=expected, expected_head_sha256=expected_head)
    replacement = tmp_path / "replacement"
    changed = deepcopy(policy)
    changed["board_id"] = "replacement-board"
    board.create(replacement, changed)
    item = payload()
    board.commit(replacement, "alpha", board.submission_digest(changed, item))
    board.reveal(replacement, item)
    with pytest.raises(ValueError, match="externally retained charter"):
        board.snapshot(replacement, expected_charter_sha256=expected)
    with pytest.raises(ValueError, match="externally retained head"):
        board.snapshot(replacement, expected_head_sha256=expected_head)


def test_declared_and_frozen_artifact_custody_are_distinct_and_frozen_bytes_checked(tmp_path):
    content = b"bounded measurement bytes\n"
    digest = hashlib.sha256(content).hexdigest()
    source = tmp_path / "source.txt"
    source.write_bytes(content)
    pins = [{"id": identity, "kind": "measurement", "sha256": digest,
             "size": len(content), "custody": custody} for identity, custody in
            (("declared", "declared_digest"), ("frozen", "frozen_bytes"))]
    policy = charter(("alpha",), artifact_pins=pins)
    with pytest.raises(ValueError, match="exactly the frozen_bytes"):
        board.create(tmp_path / "missing-frozen", policy)
    root = tmp_path / "board"
    view = board.create(root, policy, artifacts={"frozen": source})
    assert view["artifact_pins"] == pins
    assert not (root / "artifacts/declared.bin").exists()
    refs = [{key: pins[0][key] for key in ("id", "kind", "sha256")}]
    item = payload(refs=refs)
    board.commit(root, "alpha", board.submission_digest(policy, item))
    board.reveal(root, item)
    (root / "artifacts/frozen.bin").write_bytes(b"changed")
    with pytest.raises(ValueError, match="custody changed"):
        board.snapshot(root)


def test_artifact_attribution_does_not_manufacture_prediction_novelty(tmp_path):
    pin = {"id": "evidence", "kind": "narrative", "sha256": "0" * 64,
           "size": 100, "custody": "declared_digest"}
    policy = charter(("alpha", "beta"), artifact_pins=[pin])
    refs = [{key: pin[key] for key in ("id", "kind", "sha256")}]
    root, _, _ = revealed(tmp_path, actors=("alpha", "beta"), policy=policy,
                          submissions=[payload("alpha"), payload("beta", refs=refs)])
    view = board.snapshot(root)
    assert view["counts"]["prediction_groups"] == 1
    assert len(view["prediction_groups"][0]["members"]) == 2
    assert any(row["artifact_refs"] for row in view["hypotheses"])


@pytest.mark.parametrize("location", ["root", "parent", "record", "charter", "head", "records", "artifacts", "source"])
def test_symlink_paths_are_refused_without_following_target(tmp_path, location):
    actual = tmp_path / "actual"
    actual.mkdir()
    if location in {"root", "parent"}:
        link = tmp_path / "alias"
        link.symlink_to(actual, target_is_directory=True)
        with pytest.raises((ValueError, FileExistsError)):
            if location == "root":
                board.create(link, charter(("alpha",)))
            else:
                board.create(link / "board", charter(("alpha",)))
        assert list(actual.iterdir()) == []
        return
    if location == "source":
        target = actual / "source.txt"
        target.write_bytes(b"data")
        link = tmp_path / "source-link"
        link.symlink_to(target)
        pin = {"id": "A1", "kind": "source", "sha256": hashlib.sha256(b"data").hexdigest(),
               "size": 4, "custody": "frozen_bytes"}
        with pytest.raises(ValueError, match="symlink"):
            board.create(tmp_path / "board", charter(("alpha",), artifact_pins=[pin]), artifacts={"A1": link})
        return
    root, _, _ = revealed(tmp_path, actors=("alpha",))
    path = root / {"record": "records/00000001.json", "charter": "charter.json",
                   "head": "head.json", "records": "records", "artifacts": "artifacts"}[location]
    original = actual / path.name
    path.rename(original)
    path.symlink_to(original, target_is_directory=original.is_dir())
    with pytest.raises(ValueError, match="symlink"):
        board.snapshot(root)
    assert original.exists()


def test_bounds_exclusive_creation_and_lock_refusal(tmp_path):
    policy = charter(("alpha",))
    policy["limits"]["max_records"] = 3
    policy["limits"]["max_hypotheses"] = 2
    root, _, _ = revealed(tmp_path, actors=("alpha",), policy=policy)
    with pytest.raises(FileExistsError):
        board.create(root, policy)
    board.append(root, payload(hypothesis_id="H2", nonce="second-submission-123"))
    with pytest.raises(ValueError, match="record bound"):
        board.append(root, payload(hypothesis_id="H3", nonce="third-submission-1234"))
    (root / ".lock").write_text("external lock")
    with pytest.raises(ValueError, match="locked"):
        board.snapshot(root)
    assert (root / ".lock").read_text() == "external lock"


def test_total_hypothesis_bound_is_enforced(tmp_path):
    policy = charter(("alpha",))
    policy["limits"]["max_hypotheses"] = 1
    root, _, _ = revealed(tmp_path, actors=("alpha",), policy=policy)
    with pytest.raises(ValueError, match="total hypothesis bound"):
        board.append(root, payload(hypothesis_id="H2", nonce="second-submission-123"))


@pytest.mark.parametrize("mutation", ["numeric", "bool", "missing_key", "extra_key", "session", "nonce", "path_ref"])
def test_strict_payload_schema_refuses_ambiguous_or_untrusted_fields(mutation):
    item = payload()
    if mutation in {"numeric", "bool"}:
        item["hypotheses"][0]["predictions"]["shape"] = 1.2 if mutation == "numeric" else True
    elif mutation == "missing_key":
        del item["hypotheses"][0]["predictions"]["acceptance"]
    elif mutation == "extra_key":
        item["approval"] = "GO"
    elif mutation == "session":
        item["session_id"] = "undeclared-session"
    elif mutation == "nonce":
        item["nonce"] = "short"
    else:
        item["hypotheses"][0]["artifact_refs"] = [{"path": "/arbitrary/authority.txt"}]
    with pytest.raises(ValueError):
        board.submission_digest(charter(), item)


def test_rehashed_invalid_state_is_rejected_by_replay(tmp_path):
    root, _, _ = revealed(tmp_path, actors=("alpha",))
    event_path = root / "records/00000002.json"
    event = read(event_path)
    event["event"] = "commit"
    event["payload"] = None
    event["sha256"] = board._digest({key: value for key, value in event.items() if key != "sha256"})
    write(event_path, event)
    head = read(root / "head.json")
    head["sha256"] = event["sha256"]
    write(root / "head.json", head)
    with pytest.raises(ValueError, match="duplicate initial commit"):
        board.snapshot(root)


def test_never_emits_gate_or_scientific_authority(tmp_path):
    root, _, _ = revealed(tmp_path, actors=("alpha",))
    view = board.snapshot(root)
    assert view["authority"] == "ADVISORY"
    assert "no execution/check-in approval or scientific validity" in view["limitations"]
    assert "out-of-band reading" in view["limitations"] and "OS sandboxing/privacy" in view["limitations"]
    assert all(key not in view for key in ("approved", "can_execute", "checkin1", "checkin2_go", "scientifically_valid"))


def test_module_cli_uses_the_same_fail_closed_protocol(tmp_path):
    root = tmp_path / "board"
    policy_path, submission_path = tmp_path / "charter.json", tmp_path / "submission.json"
    policy, item = charter(("alpha", "beta")), payload()
    write(policy_path, policy)
    write(submission_path, item)
    source = Path(__file__).resolve().parents[2] / "src"
    environment = {**os.environ, "PYTHONPATH": str(source)}
    def command(*args):
        return subprocess.run([sys.executable, "-m", "ravel.workflow.hypothesis_board", *args],
                              capture_output=True, text=True, env=environment, timeout=10)
    assert command("create", "--board", str(root), "--charter", str(policy_path)).returncode == 0
    digest = json.loads(command("digest", "--board", str(root), "--submission", str(submission_path)).stdout)["submission_sha256"]
    assert command("commit", "--board", str(root), "--actor", "alpha", "--digest", digest).returncode == 0
    rejected = command("reveal", "--board", str(root), "--submission", str(submission_path))
    assert rejected.returncode == 2 and "every participant to commit" in rejected.stderr
    visible = command("snapshot", "--board", str(root))
    assert visible.returncode == 0 and json.loads(visible.stdout)["authority"] == "ADVISORY"
