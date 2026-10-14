"""Board journal: typed posts, broker-authenticated actors, projections, replay and recovery."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ravel.workflow import hypothesis_board as board
from ravel.workflow import research_board as rb

ACTORS = ("alpha", "beta")
STATEMENTS = {"alpha": "Synthetic rising-shape conjecture.", "beta": "Synthetic falling-shape alternative."}


def charter(actors=ACTORS, *, mode="production", season="season-1"):
    return {"schema_version": 2, "board_id": "synthetic-board", "season": season, "mode": mode,
            "participants": [{"actor_id": actor, "model_id": f"declared-model-{actor}",
                              "session_id": f"session-{actor}", "fresh_generation": True,
                              "broker": {"node_id": f"proposer-{actor}", "attempt": 1}} for actor in actors],
            "prediction_keys": ["acceptance", "shape"], "limits": dict(board.DEFAULT_LIMITS), "artifact_pins": []}


def submission(actor, *, shape="up", hypothesis_id="H1", statement=None):
    return {"schema_version": 1, "actor_id": actor, "session_id": f"session-{actor}",
            "nonce": f"initial-nonce-for-{actor}", "hypotheses": [
                {"id": hypothesis_id, "statement": statement or STATEMENTS[actor],
                 "predictions": {"shape": shape, "acceptance": None}, "artifact_refs": [], "contradicts": []}]}


class Run:
    """A synthetic run with one broker per participant and a board season under the run tree."""

    def __init__(self, tmp_path, monkeypatch, *, mode="production", reveal=True):
        from ravel.workflow.broker import Broker, work_root
        monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))
        monkeypatch.setenv("RAVEL_WORK_ROOT", str(tmp_path / "work"))
        self.rundir = tmp_path / "run"
        (self.rundir / "research/board").mkdir(parents=True)
        self.root = self.rundir / "research/board/season-1"
        self.charter = charter(mode=mode)
        rb.create(self.root, self.charter)
        # Version 2 commits and reveals are written by the code reveal path for this season record.
        rb.open_season(self.rundir, {"season": "season-1", "participants": self.charter["participants"]})
        self.brokers = {}
        for actor in ACTORS:
            workspace = work_root(self.rundir) / f"proposer-{actor}" / "1"
            for name in ("inputs", "outputs", "scratch", "calls"):
                (workspace / name).mkdir(parents=True, exist_ok=True)
            broker = Broker(self.rundir, workspace, node_id=f"proposer-{actor}", attempt=1,
                            allowed_actions=["write", "board post"], max_calls=50, actor_id=actor)
            broker.register("board post", rb.post_action(broker, self.root))
            self.brokers[actor] = broker
        self.calls = 0
        if reveal:
            auth = rb.code_auth(self.rundir, "season-1")
            for actor in ACTORS:
                board.commit(self.root, actor, board.submission_digest(self.charter, submission(actor)),
                             auth=auth, rundir=self.rundir)
            for actor in ACTORS:
                board.reveal(self.root, submission(actor), auth=auth, rundir=self.rundir)

    def call(self, actor, action, args):
        self.calls += 1
        return self.brokers[actor].call({"call_id": f"call-{self.calls}", "action": action, "args": args})

    def post(self, actor, body):
        return self.call(actor, "board post", {"post": body})

    def receipt(self, actor, name="outputs/result.txt"):
        """A real broker receipt pin from an ordinary write call."""
        from ravel.workflow.broker import logical, sha
        reply = self.call(actor, "write", {"path": name, "content": f"synthetic output {self.calls}"})
        assert reply["status"] == "ok"
        broker = self.brokers[actor]
        path = sorted((broker.workspace / "calls").glob("*.json"), key=lambda p: int(p.stem))[-1]
        return {"path": logical(self.rundir, path), "sha256": sha(path)}

    def season(self):
        return rb.season(self.root, rundir=self.rundir)

    def hypothesis_ref(self, actor="alpha"):
        return next(row["ref"] for row in rb.register(self.season())["hypotheses"] if row["actor_id"] == actor)


def request_body(sequence=1, **changes):
    fields = {"observable": "yield_ratio", "conditions": ["synthetic selection"], "discriminates": [],
              "admissible_operation": "counting_check", "prerequisites": [], "cost_class": "cheap",
              "feasibility": "feasible", "rationale": "Private reasoning that critics must not read."}
    fields.update(changes)
    return {"kind": "evidence_request", "actor_sequence": sequence, "parents": [], "fields": fields}


def finding_body(pin, affects, sequence=1):
    return {"kind": "finding", "actor_sequence": sequence, "parents": [], "fields": {
        "receipt_pin": pin, "evidence_class": "new_receipt", "statement": "Interpretive finding prose for review.",
        "affects": affects, "rationale": "Why the author believes it."}}


def refutation_body(pin, target, sequence=1, key="shape"):
    return {"kind": "refutation", "actor_sequence": sequence, "parents": [], "fields": {
        "target": {"hypothesis": target, "key": key}, "receipt_pin": pin, "comparator": "category_equal",
        "sensitivity": "insensitive to the synthetic binning", "held_fixed_inputs": [], "domain": "synthetic domain"}}


# 1. Register replay -------------------------------------------------------------------------

def test_register_recomputed_from_the_journal_is_byte_identical(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    pin = run.receipt("alpha")
    assert run.post("alpha", request_body())["status"] == "ok"
    assert run.post("beta", finding_body(pin, [run.hypothesis_ref("alpha")]))["status"] == "ok"
    # Evidence-bound transitions and their replay: test_board_integrity.py.
    first = rb.register_bytes(run.season())
    second = rb.register_bytes(rb.season(run.root, rundir=run.rundir))
    assert first == second and json.loads(first)["hypotheses"]
    states = {row["actor_id"]: row["status"] for row in json.loads(first)["hypotheses"]}
    assert states == {"alpha": "proposed", "beta": "proposed"}


def test_one_byte_change_in_the_journal_fails_register_replay(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    assert run.post("alpha", request_body())["status"] == "ok"
    rb.register_bytes(run.season())
    record = sorted((run.root / "records").glob("*.json"))[-1]
    raw = bytearray(record.read_bytes())
    raw[raw.index(b"yield_ratio")] = ord("Y")
    record.write_bytes(bytes(raw))
    with pytest.raises(ValueError, match="digest or hash chain"):
        rb.register_bytes(rb.season(run.root, rundir=run.rundir))


def test_register_transitions_are_code_written_and_typed(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    pin, ref = run.receipt("alpha"), run.hypothesis_ref("alpha")
    with pytest.raises(ValueError, match="register state"):
        rb.record_transition(run.root, rundir=run.rundir, hypothesis=ref, to="true", rule_id="r", receipt_pin=pin)
    with pytest.raises(ValueError, match="broker"):
        rb.record_transition(run.root, rundir=run.rundir, hypothesis=ref, to="survived_test",
                             rule_id="comparator_matches", receipt_pin={"path": pin["path"], "sha256": "0" * 64})
    assert run.post("alpha", {"kind": "transition", "actor_sequence": 1, "parents": [],
                              "fields": {"hypothesis": ref, "to": "survived_test"}})["status"] == "refused"


def test_board_register_events_feed_the_cycle_register_replay(tmp_path, monkeypatch):
    """Undeclared hypotheses emit no cycle event; the declared round trip is in test_board_integrity.py."""
    from ravel.workflow import research_cycle
    run = Run(tmp_path, monkeypatch)
    assert research_cycle.replay_register(rb.cycle_events(run.season())) == {}


# 2. Closed kinds and control fields ---------------------------------------------------------

@pytest.mark.parametrize("kind", ["verdict", "agree", "summary", "priority", "approval", "undeclared"])
def test_undeclared_and_absent_by_design_kinds_are_refused(tmp_path, monkeypatch, kind):
    run = Run(tmp_path, monkeypatch)
    before = board.journal(run.root)["head"]
    reply = run.post("alpha", {"kind": kind, "actor_sequence": 1, "parents": [], "fields": {"statement": "x"}})
    assert reply["status"] == "refused" and reply["error"]["code"] == "board_post_refused"
    assert board.journal(run.root)["head"] == before


@pytest.mark.parametrize("field", ["status", "accepted", "verdict", "actor_id", "authorized", "approval"])
def test_a_control_field_anywhere_in_a_post_is_refused(tmp_path, monkeypatch, field):
    run = Run(tmp_path, monkeypatch)
    top = request_body()
    top["fields"][field] = "accepted"
    nested_kind = {"kind": "rival", "actor_sequence": 1, "parents": [], "fields": {
        "world_a": "a" * 64, "world_b": "b" * 64, "visible_agreement_pins": [],
        "separator": {"observable": "shape", "feasible": True, "cost_class": "cheap", field: True}}}
    for body in (top, nested_kind):
        reply = run.post("alpha", body)
        assert reply["status"] == "refused" and "control field" in reply["error"]["message"], body
    with pytest.raises(ValueError, match="control field"):
        rb.validate_post(run.charter, top)


def test_pre_mortem_is_refused_in_production_and_admitted_in_evaluation(tmp_path, monkeypatch):
    body = {"kind": "pre_mortem", "actor_sequence": 1, "parents": [], "fields": {"risk": "synthetic risk", "affects": []}}
    with pytest.raises(ValueError, match="evaluation"):
        rb.validate_post(charter(), body)
    rb.validate_post(charter(mode="evaluation"), body)


def test_posts_wait_for_every_initial_reveal(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch, reveal=False)
    assert run.post("alpha", request_body())["status"] == "refused"


# Broker authentication ----------------------------------------------------------------------

def test_the_actor_is_the_broker_identity_and_a_direct_post_is_refused(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    assert run.post("beta", request_body())["status"] == "ok"
    entry = board.journal(run.root)["entries"][-1]
    assert entry["actor_id"] == "beta" and entry["auth"]["node_id"] == "proposer-beta"
    # A caller outside the broker cannot name an actor: no custody reservation authorises it.
    with pytest.raises(ValueError, match="broker"):
        board.post(run.root, request_body(2), actor_id="beta", rundir=run.rundir,
                   auth={"node_id": "proposer-beta", "attempt": 1, "action": "board post",
                         "args_sha256": "0" * 64, "reservation": "proposer-beta/1/99"})
    # A broker bound to another node cannot speak for a participant.
    with pytest.raises(ValueError, match="broker identity"):
        board.post(run.root, request_body(1), actor_id="alpha", rundir=run.rundir, auth=entry["auth"])


def test_a_post_replayed_with_a_used_reservation_is_refused(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    assert run.post("alpha", request_body())["status"] == "ok"
    entry = board.journal(run.root)["entries"][-1]
    # Another body under a used reservation: the reservation authorised other request bytes.
    with pytest.raises(ValueError, match="broker request does not match"):
        board.post(run.root, request_body(2), actor_id="alpha", rundir=run.rundir, auth=entry["auth"])


# 3. Receipts as admission -------------------------------------------------------------------

def test_finding_and_refutation_without_a_broker_index_receipt_are_refused(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    real, target = run.receipt("alpha"), run.hypothesis_ref("beta")
    forged = {"path": real["path"], "sha256": "f" * 64}
    stray = run.rundir / "research/unindexed-receipt.json"
    stray.write_text(json.dumps({"kind": "broker-receipt"}))
    from ravel.workflow.broker import sha
    unindexed = {"path": "research/unindexed-receipt.json", "sha256": sha(stray)}
    for bad in (forged, unindexed):
        assert run.post("alpha", finding_body(bad, [target]))["status"] == "refused"
        assert run.post("alpha", refutation_body(bad, target))["status"] == "refused"
    assert run.post("alpha", refutation_body(real, target, key="undeclared_key"))["status"] == "refused"
    assert run.post("alpha", finding_body(real, [target]))["status"] == "ok"
    assert run.post("alpha", refutation_body(real, target, sequence=2))["status"] == "ok"
    kinds = [row["event"] for row in board.journal(run.root)["entries"]]
    assert kinds.count("post") == 2


# 4. Projections -----------------------------------------------------------------------------

def card(profile, forbidden=()):
    return {"id": "synthetic-role", "sees": {"profile": profile, "forbidden_inputs": list(forbidden)}}


def test_critic_projection_strips_actor_chronology_and_rationale(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    pin = run.receipt("alpha")
    assert run.post("alpha", request_body())["status"] == "ok"
    assert run.post("beta", finding_body(pin, [run.hypothesis_ref("alpha")]))["status"] == "ok"
    view = rb.project(card("spec-denied"), run.season())
    text = json.dumps(view)
    for leak in ("alpha", "beta", "proposer-", "session-", "Private reasoning", "Interpretive finding",
                 "Why the author", "previous_sha256", "actor_sequence", "\"sequence\""):
        assert leak not in text, leak
    assert {row["kind"] for row in view["receipts"]} == {"finding"}
    assert view["receipts"][0]["receipt_sha256"] == pin["sha256"] and "receipt_pin" not in view["receipts"][0]
    assert view["open_requests"][0]["observable"] == "yield_ratio"
    assert len(view["hypotheses"]) == 2 and all("predictions" in row for row in view["hypotheses"])
    # Chronology is absent: the projection is invariant to publication order of equal content.
    assert view == rb.project(card("spec-denied"), rb.season(run.root, rundir=run.rundir))


def test_blind_roles_receive_nothing_and_a_bundle_with_board_prose_is_refused(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    assert run.post("alpha", request_body())["status"] == "ok"
    season = run.season()
    with pytest.raises(rb.BoardAccessRefused) as refused:
        rb.project(card("blind"), season)
    assert refused.value.code == "board_prose_forbidden"
    with pytest.raises(rb.BoardAccessRefused):
        rb.project(card("workspace", forbidden=["board_prose"]), season)
    assert "board_prose" in rb.forbidden_inputs(card("blind"))
    clean = [{"path": "inputs/primary/table.json", "content": "{\"bins\": [1, 2]}"}]
    assert rb.check_bundle(card("blind"), clean, season) == clean
    prose = deepcopy(clean) + [{"path": "inputs/notes.txt",
                                "content": "copied: Private reasoning that critics must not read."}]
    by_path = deepcopy(clean) + [{"path": "inputs/board/view.json", "content": "{}"}]
    statement = deepcopy(clean) + [{"path": "inputs/x.txt", "content": "Synthetic falling-shape alternative."}]
    for bundle in (prose, by_path, statement):
        with pytest.raises(rb.BoardAccessRefused, match="board prose"):
            rb.check_bundle(card("blind"), bundle, season)
    assert rb.check_bundle(card("spec-denied"), prose, season) == prose


def test_workspace_sees_its_season_after_reveal_and_coordinator_only_the_snapshot(tmp_path, monkeypatch):
    sealed = Run(tmp_path / "sealed", monkeypatch, reveal=False)
    assert rb.project(card("workspace"), sealed.season())["entries"] == []
    run = Run(tmp_path / "open", monkeypatch)
    assert run.post("alpha", request_body())["status"] == "ok"
    view = rb.project(card("workspace"), run.season())
    assert [row["event"] for row in view["entries"]].count("post") == 1
    snapshot = rb.project({"id": "coordinator", "sees": {"profile": "full", "forbidden_inputs": []}}, run.season())
    assert set(snapshot) == {"profile", "season", "snapshot"}
    assert "Private reasoning" not in json.dumps(snapshot)
    with pytest.raises(rb.BoardAccessRefused):
        rb.project({"id": "x", "sees": {"profile": "undeclared"}}, run.season())


# 5. Recovery of the publish-before-head window ----------------------------------------------

def test_crash_between_publish_and_head_recovers_on_next_open_without_duplicates(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    original = board._write
    def crash(directory, name, content, **kwargs):
        if name == "head.json":
            raise OSError("simulated crash after record publication")
        return original(directory, name, content, **kwargs)
    monkeypatch.setattr(board, "_write", crash)
    reply = run.post("alpha", request_body())
    assert reply["status"] == "failed"
    monkeypatch.setattr(board, "_write", original)
    head = json.loads((run.root / "head.json").read_text())
    assert len(list((run.root / "records").glob("*.json"))) == head["sequence"] + 1
    view = run.season()  # the next open rolls the verified record forward
    assert view["head"]["sequence"] == head["sequence"] + 1
    # The resumed post (same actor sequence and body) returns the retained entry.
    entry = board.post(run.root, request_body(), actor_id="alpha", rundir=run.rundir,
                       auth=view["entries"][-1]["auth"])
    assert entry == view["entries"][-1]
    assert [row["event"] for row in run.season()["entries"]].count("post") == 1


def test_resumed_reveal_crashed_between_entries_appends_only_missing_entries(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch, reveal=False)
    auth = {"auth": rb.code_auth(run.rundir, "season-1"), "rundir": run.rundir}
    for actor in ACTORS:
        board.commit(run.root, actor, board.submission_digest(run.charter, submission(actor)), **auth)
    board.reveal(run.root, submission("alpha"), **auth)
    original = board._write
    monkeypatch.setattr(board, "_write", lambda d, name, c, **k: (_ for _ in ()).throw(OSError("crash"))
                        if name == "head.json" else original(d, name, c, **k))
    with pytest.raises(OSError):
        board.reveal(run.root, submission("beta"), **auth)
    monkeypatch.setattr(board, "_write", original)
    for actor in ACTORS:  # the reveal effect resumes from the start
        board.reveal(run.root, submission(actor), **auth)
        board.commit(run.root, actor, board.submission_digest(run.charter, submission(actor)), **auth)
    kinds = [row["event"] for row in board.journal(run.root, rundir=run.rundir)["entries"]]
    assert kinds == ["commit", "commit", "reveal", "reveal"]
    with pytest.raises(ValueError, match="idempotent key"):
        board.reveal(run.root, submission("beta", shape="down"), **auth)


def test_killed_writer_between_publish_and_head_leaves_a_lock_that_the_next_open_recovers(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch, reveal=False)
    digest = board.submission_digest(run.charter, submission("alpha"))
    script = (
        "import os, sys\n"
        "from ravel.workflow import hypothesis_board as board\n"
        "original = board._write\n"
        "def crash(directory, name, content, **kwargs):\n"
        "    if name == 'head.json':\n"
        "        os._exit(9)\n"
        "    return original(directory, name, content, **kwargs)\n"
        "board._write = crash\n"
        "import json, pathlib\n"
        "board.commit(sys.argv[1], 'alpha', sys.argv[2], auth=json.loads(sys.argv[3]), rundir=pathlib.Path(sys.argv[4]))\n")
    env = {**os.environ, "PYTHONPATH": str(Path(board.__file__).parents[2])}
    auth = json.dumps(rb.code_auth(run.rundir, "season-1"))
    process = subprocess.run([sys.executable, "-c", script, str(run.root), digest, auth, str(run.rundir)],
                             env=env, timeout=120)
    assert process.returncode == 9
    assert (run.root / ".lock").exists()
    view = board.journal(run.root, rundir=run.rundir)
    assert [row["event"] for row in view["entries"]] == ["commit"] and not (run.root / ".lock").exists()
    assert board.commit(run.root, "alpha", digest) == view["entries"][0]
    assert len(board.journal(run.root)["entries"]) == 1


def test_a_live_or_foreign_lock_is_never_broken(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch, reveal=False)
    (run.root / ".lock").write_text(json.dumps({"pid": os.getpid(), "token": "a" * 32}))
    with pytest.raises(ValueError, match="locked"):
        board.journal(run.root)
    (run.root / ".lock").write_text("external lock")
    with pytest.raises(ValueError, match="locked"):
        board.journal(run.root)


# Extension verification ---------------------------------------------------------------------

def test_verified_extension_divergence_and_chain_break(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    channel = board.journal(run.root)["head"]["sha256"]
    assert rb.verify_extension(channel, run.root, rundir=run.rundir)["status"] == "current"
    assert run.post("alpha", request_body())["status"] == "ok"
    assert run.post("beta", request_body())["status"] == "ok"
    result = rb.verify_extension(channel, run.root, rundir=run.rundir)
    assert result["status"] == "extension" and [row["event"] for row in result["entries"]] == ["post", "post"]
    assert rb.verify_extension("e" * 64, run.root, rundir=run.rundir)["status"] == "divergence"
    record = sorted((run.root / "records").glob("*.json"))[-1]
    document = json.loads(record.read_text())
    document["previous_sha256"] = "d" * 64
    record.write_text(json.dumps(document))
    broken = rb.verify_extension(channel, run.root, rundir=run.rundir)
    assert broken["status"] == "divergence" and "chain" in broken["reason"]


def test_extension_without_its_broker_reservation_is_divergence(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    channel = board.journal(run.root)["head"]["sha256"]
    assert run.post("alpha", request_body())["status"] == "ok"
    from ravel.workflow.broker import custody
    ledger = custody(run.rundir) / "broker-reservations.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows if row["record"]["action"] != "board post"))
    result = rb.verify_extension(channel, run.root, rundir=run.rundir)
    assert result["status"] == "divergence"


def test_version_one_boards_keep_their_snapshot(tmp_path):
    legacy = {**charter(), "schema_version": 1}
    for key in ("season", "mode"):
        legacy.pop(key)
    for row in legacy["participants"]:
        row.pop("broker")
    root = tmp_path / "legacy"
    view = board.create(root, legacy)
    assert view["kind"] == "advisory_hypothesis_board" and "season" not in view
    with pytest.raises(ValueError, match="version 2"):
        board.post(root, request_body(), actor_id="alpha", rundir=tmp_path, auth={})
