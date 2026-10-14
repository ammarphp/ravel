"""Board integrity: evidence-bound transitions, the register round trip, v2 actor
authentication, participant-bound sealing, custody-only recovery, projections and the
blind-bundle guard. Synthetic seasons and brokers only; no model or physics process."""
import json
from pathlib import Path

import pytest

from ravel.workflow import broker as broker_module, hypothesis_board as board, research_board as rb
from ravel.workflow import research_board_discussion as discussion, research_cycle
from test_research_board import ACTORS, Run, card, request_body, submission

REGISTER = {"identity_signature": {"observable": "shape", "scope": "synthetic scope", "prediction": "up"},
            "kill_condition": {"comparison": "differs", "observable": "shape"},
            "reopening_trigger": {"kind": "new_evidence", "field": "status", "op": "eq", "value": "new"},
            "operator": "limitation_fix", "what_is_new": None}


def declared(actor, shape):
    value = submission(actor, shape=shape)
    value["hypotheses"][0]["register"] = {**REGISTER, "identity_signature": {**REGISTER["identity_signature"],
                                                                            "prediction": shape}}
    return value


class DeclaredRun(Run):
    """A season whose hypotheses carry register declarations, with a registered comparator action."""

    def __init__(self, tmp_path, monkeypatch):
        super().__init__(tmp_path, monkeypatch, reveal=False)
        allowlist = tmp_path / "pkg/data/validators/allowlist.json"
        allowlist.parent.mkdir(parents=True)
        allowlist.write_text(json.dumps({"validators": [{"id": "synthetic-comparator"}]}))
        monkeypatch.setattr(broker_module, "__file__", str(tmp_path / "pkg/workflow/broker.py"))
        for actor, b in self.brokers.items():
            b.allowed_actions = [*b.allowed_actions, "compare"]
            b.register("compare", self._compare(b), derivation="registered_validator",
                       validator_id="synthetic-comparator")
        auth = rb.code_auth(self.rundir, "season-1")
        payloads = {"alpha": declared("alpha", "up"), "beta": declared("beta", "down")}
        for actor in ACTORS:
            board.commit(self.root, actor, board.submission_digest(self.charter, payloads[actor]),
                         auth=auth, rundir=self.rundir)
        for actor in ACTORS:
            board.reveal(self.root, payloads[actor], auth=auth, rundir=self.rundir)

    @staticmethod
    def _compare(b):
        def handler(args):
            outputs = []
            for name, value in args["records"].items():
                path = b.workspace / "outputs" / name
                path.write_text(json.dumps(value))
                outputs.append(f"outputs/{name}")
            # The registered comparator reports that it ran and its outcome; a receipt without both is not ok.
            return {"output_paths": outputs, "validator_executed": True, "exit_status": 0}
        return handler

    def comparator(self, actor, ref, comparison, *, sensitivity=None, status="success"):
        from ravel.workflow.broker import logical, sha
        signature = REGISTER["identity_signature"]
        records = {f"compare-{self.calls}.json": {
            "kind": "prediction-comparison", "hypothesis_id": rb.cycle_id(ref), "comparison": comparison,
            "execution_status": status, "experiment_id": "e1", "scope": signature["scope"],
            "observable": signature["observable"],
            "residual": {"observable": signature["observable"], "predicted": "up", "measured": "down",
                         "interval": None, "sign": "different", "constraint_violated": None}}}
        if sensitivity:
            records[f"sensitivity-{self.calls}.json"] = {
                "kind": "sensitivity-check", "status": sensitivity, "scope": signature["scope"],
                "observable": signature["observable"], "experiment_id": "e1"}
        reply = self.call(actor, "compare", {"records": records})
        assert reply["status"] == "ok", reply
        b = self.brokers[actor]
        path = sorted((b.workspace / "calls").glob("*.json"), key=lambda p: int(p.stem))[-1]
        return {"path": logical(self.rundir, path), "sha256": sha(path)}


@pytest.fixture
def declared_run(tmp_path, monkeypatch):
    return DeclaredRun(tmp_path, monkeypatch)


def refs(run):
    return {row["actor_id"]: row["ref"] for row in rb.register(run.season())["hypotheses"]}


# D8 -- transitions need their rule's evidence and a permitted edge.

def test_an_ordinary_write_receipt_cannot_move_the_register(declared_run):
    run = declared_run
    pin, ref = run.receipt("alpha"), refs(run)["alpha"]
    for rule, to in (("comparator_matches", "survived_test"), ("scoped_exclusion", "rejected_in_scope")):
        with pytest.raises(ValueError, match="registered comparator"):
            rb.record_transition(run.root, rundir=run.rundir, hypothesis=ref, to=to, rule_id=rule, receipt_pin=pin)
    assert rb.register(run.season())["hypotheses"][0]["status"] == "proposed"


def test_rules_bind_edges_outcomes_and_the_named_hypothesis(declared_run):
    run = declared_run
    alpha, beta = refs(run)["alpha"], refs(run)["beta"]
    with pytest.raises(ValueError, match="registered register rule"):
        rb.record_transition(run.root, rundir=run.rundir, hypothesis=alpha, to="active", rule_id="synthetic_rule",
                             receipt_pin=run.comparator("alpha", alpha, "matches"))
    with pytest.raises(ValueError, match="does not permit"):
        rb.record_transition(run.root, rundir=run.rundir, hypothesis=alpha, to="rejected_in_scope",
                             rule_id="comparator_matches", receipt_pin=run.comparator("alpha", alpha, "matches"))
    with pytest.raises(ValueError, match="another hypothesis"):
        rb.record_transition(run.root, rundir=run.rundir, hypothesis=alpha, to="survived_test",
                             rule_id="comparator_matches", receipt_pin=run.comparator("alpha", beta, "matches"))
    with pytest.raises(ValueError, match="successful matches"):
        rb.record_transition(run.root, rundir=run.rundir, hypothesis=alpha, to="survived_test",
                             rule_id="comparator_matches", receipt_pin=run.comparator("alpha", alpha, "differs"))
    with pytest.raises(ValueError, match="passed sensitivity"):
        rb.record_transition(run.root, rundir=run.rundir, hypothesis=beta, to="rejected_in_scope",
                             rule_id="scoped_exclusion", receipt_pin=run.comparator("beta", beta, "differs"))
    pin = run.comparator("beta", beta, "differs", sensitivity="passed")
    rb.record_transition(run.root, rundir=run.rundir, hypothesis=beta, to="rejected_in_scope",
                         rule_id="scoped_exclusion", receipt_pin=pin)
    # Reopening needs a receipt that satisfies the declared predicate, not any receipt.
    with pytest.raises(ValueError):
        rb.record_transition(run.root, rundir=run.rundir, hypothesis=beta, to="reopened", rule_id="reopening",
                             receipt_pin=run.receipt("beta"))
    with pytest.raises(ValueError, match="does not permit"):
        rb.record_transition(run.root, rundir=run.rundir, hypothesis=beta, to="active", rule_id="rdj_admission",
                             receipt_pin=pin)


# D9 -- the board register and the research-cycle register agree on the same evidence.

def test_board_events_replay_strictly_in_the_cycle_register(declared_run):
    run = declared_run
    alpha, beta = refs(run)["alpha"], refs(run)["beta"]
    rb.record_transition(run.root, rundir=run.rundir, hypothesis=alpha, to="survived_test",
                         rule_id="comparator_matches", receipt_pin=run.comparator("alpha", alpha, "matches"))
    rb.record_transition(run.root, rundir=run.rundir, hypothesis=beta, to="rejected_in_scope", rule_id="scoped_exclusion",
                         receipt_pin=run.comparator("beta", beta, "differs", sensitivity="passed"))
    events = rb.cycle_events(rb.season(run.root, rundir=run.rundir))
    assert [e["kind"] for e in events] == ["hypothesis", "hypothesis", "test", "transition", "test", "transition"]
    register = research_cycle.replay_register(events)
    a, b = rb.cycle_id(alpha), rb.cycle_id(beta)
    assert register[a]["status"] == "survived_test" and register[b]["status"] == "refuted"
    assert register[b]["scope_of_negative"] == REGISTER["identity_signature"]["scope"]
    states = {row["ref"]: row["status"] for row in rb.register(run.season())["hypotheses"]}
    assert states == {alpha: "survived_test", beta: "rejected_in_scope"}
    from ravel.validation import check_research_board as check
    assert check.validate("check:board_replay", {"season_root": "research/board/season-1"},
                          base_dir=run.rundir) == {"valid": True, "errors": []}


def test_board_checks_are_registered_for_their_protocols():
    from ravel.workflow import research_protocol as p
    missing = {row["id"] for row in p.protocol_producers_present()["missing"]}
    assert not {"P01", "P02"} & missing


# D10 -- version 2 commits, reveals and appends carry actor authentication.

def test_v2_commit_reveal_and_append_without_authentication_are_refused(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch, reveal=False)
    digest = board.submission_digest(run.charter, submission("alpha"))
    with pytest.raises(ValueError, match="code reveal path"):
        board.commit(run.root, "alpha", digest, rundir=run.rundir)
    forged = {"producer": board.SEASON_PRODUCER, "season_record_sha256": "0" * 64}
    with pytest.raises(ValueError, match="frozen record"):
        board.commit(run.root, "alpha", digest, auth=forged, rundir=run.rundir)
    auth = rb.code_auth(run.rundir, "season-1")
    for actor in ACTORS:
        board.commit(run.root, actor, board.submission_digest(run.charter, submission(actor)), auth=auth, rundir=run.rundir)
    with pytest.raises(ValueError, match="code reveal path"):
        board.reveal(run.root, submission("alpha"), rundir=run.rundir)
    for actor in ACTORS:
        board.reveal(run.root, submission(actor), auth=auth, rundir=run.rundir)
    followup = {**submission("beta", hypothesis_id="H2"), "nonce": "followup-nonce-for-beta"}
    with pytest.raises(ValueError, match="broker authentication"):
        board.append(run.root, followup, rundir=run.rundir)
    for argv in (["append", "--board", str(run.root), "--submission", str(_write(tmp_path, followup))],
                 ["commit", "--board", str(run.root), "--actor", "alpha", "--digest", "0" * 64]):
        with pytest.raises(SystemExit) as stopped:
            board.main(argv)
        assert stopped.value.code == 2


def _write(tmp_path, value):
    path = tmp_path / "followup.json"
    path.write_text(json.dumps(value))
    return path


def test_a_broker_append_is_attributed_to_its_own_participant(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    b = run.brokers["beta"]
    b.allowed_actions = [*b.allowed_actions, "board append"]
    b.register("board append", rb.append_action(b, run.root))
    followup = {**submission("beta", hypothesis_id="H2"), "nonce": "followup-nonce-for-beta"}
    assert run.call("beta", "board append", {"append": followup})["status"] == "ok"
    as_alpha = {**submission("alpha", hypothesis_id="H3"), "nonce": "followup-nonce-for-alpha"}
    assert run.call("beta", "board append", {"append": as_alpha})["status"] == "refused"
    origins = {(row["actor_id"], row["hypothesis_id"]) for row in rb.register(run.season())["hypotheses"]}
    assert ("beta", "H2") in origins and ("alpha", "H3") not in origins


# D11 -- sealing is bound to the participant; reveal checks its barrier; the label is recomputed.

def _receipt(run, actor, *, session, node=None):
    from ravel.workflow.broker import append_ledger, sha
    path = run / "agent-receipts" / f"{actor}-{session}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"attestation": "transport_attested", "session_id": session, "isolation": {
        "user_configuration_loaded": False, "evidence": {"confirmed": True}}}))
    pin = {"path": f"agent-receipts/{actor}-{session}.json", "sha256": sha(path)}
    append_ledger(run, "worker-receipts", {"pin": pin, "node_id": node or f"proposer-{actor}", "attempt": 1})
    return pin


def seasons_request():
    from test_board_seasons import charter_request
    return charter_request(("p0", "p1"))


def test_unrelated_or_swapped_worker_receipts_do_not_seal(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))
    rundir = tmp_path / "run"
    rundir.mkdir()
    participants = rb.freeze_charter(seasons_request())["participants"]
    good = {"p0": _receipt(rundir, "p0", session="session-p0"), "p1": _receipt(rundir, "p1", session="session-p1")}
    assert rb.sealing(rundir, participants, good)["status"] == "sealed"
    unrelated = {"p0": _receipt(rundir, "x", session="session-x", node="unrelated-worker"),
                 "p1": _receipt(rundir, "y", session="session-y", node="other-worker")}
    swapped = {"p0": good["p1"], "p1": good["p0"]}
    for receipts in (unrelated, swapped):
        result = rb.sealing(rundir, participants, receipts)
        assert result["status"] == "unsealed" and "independence" not in result


def test_reveal_season_checks_its_barrier(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))
    rundir = tmp_path / "run"
    rundir.mkdir()
    charter = rb.freeze_charter(seasons_request())
    rb.open_season(rundir, charter)
    with pytest.raises(rb.RevealRefused):
        rb.reveal_season(rundir, charter, {"p0": "a" * 64}, {}, {}, {})
    assert not rb.journal_root(rundir, "season-1").exists()


def test_an_edited_reveal_record_cannot_claim_independence(tmp_path, monkeypatch):
    import test_board_seasons as seasons
    from ravel.workflow import graph_substrate as gs
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("RAVEL_WORK_ROOT", str(tmp_path / "work"))
    scope = tmp_path / "run"
    scope.mkdir()
    monkeypatch.setenv(seasons.COUNTS, str(scope / "counts"))
    original = seasons.install()
    try:
        observation = gs.run(scope, rb.SEASON_GRAPH, seasons.INSTANCE,
                             input={"charter": seasons.charter_request()}, workers=3)
        assert observation["terminal"] is None, observation
    finally:
        rb.producer_identity = original
        rb.PRODUCERS.pop(seasons.STUB, None)
    path = scope / "research/board/season-1.reveal.json"
    record = json.loads(path.read_text())
    record["sealing"] = {"status": "sealed", "participants": [], "independence": "attested_distinct_sessions"}
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="worker receipts"):
        discussion.season_binding(rb.journal_root(scope, "season-1"))


# D15 -- a planted record never rolls forward without custody.

def test_a_planted_record_is_quarantined_not_rolled_forward(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    head = json.loads((run.root / "head.json").read_text())
    body = request_body()
    event = {"schema_version": 2, "sequence": head["sequence"] + 1, "previous_sha256": head["sha256"],
             "event": "post", "actor_id": "beta", "submission_sha256": board._digest(body), "payload": body,
             "season": "season-1", "auth": {"node_id": "proposer-beta", "attempt": 1, "action": board.POST_ACTION,
                                             "args_sha256": board._digest({"post": body}),
                                             "reservation": "forged-reservation"}}
    event["sha256"] = board._digest(event)
    (run.root / "records" / f"{event['sequence']:08d}.json").write_bytes(board._bytes(event))
    with pytest.raises(ValueError):
        board.snapshot(run.root)  # structural: no roll-forward without custody
    assert json.loads((run.root / "head.json").read_text()) == head
    view = run.season()  # custody open: the unverifiable record is moved aside
    assert view["head"] == head and list((run.root / "quarantine").iterdir())
    assert run.post("alpha", request_body())["status"] == "ok"


# D16/D22 -- projections strip identities and lineage paths; a prose-denied critic still reads structure.

def test_full_projection_carries_no_actor_or_session_identity(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    view = rb.project(card("full"), run.season())
    text = json.dumps(view)
    assert "session-alpha" not in text and '"actor_id"' not in text
    assert all(set(m) == {"hypothesis_sha256", "phase"} for g in view["snapshot"]["prediction_groups"]
               for m in g["members"])


def test_prose_denied_critic_reads_the_structural_projection(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    view = rb.project(card("spec-denied", ("board_prose",)), run.season())
    assert view["hypotheses"] and "Synthetic" not in json.dumps(view)
    with pytest.raises(rb.BoardAccessRefused):
        rb.project(card("blind"), run.season())


def test_critic_refs_cannot_be_recomputed_from_actor_and_hypothesis(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    view = rb.project(card("spec-denied"), run.season())
    raw = {board.hypothesis_ref(actor, submission(actor)["hypotheses"][0]) for actor in ACTORS}
    assert not raw & {row["ref"] for row in view["hypotheses"]}


# D14 -- the blind guard normalizes text and covers short values.

@pytest.mark.parametrize("transform", [
    str.lower, lambda s: json.dumps({"note": s.replace(" ", "  ")}), lambda s: s.replace(" ", " "),
    lambda s: s.replace("-", "‑"), lambda s: "Context before. " + s.upper() + " Context after."])
def test_blind_bundle_variants_of_board_text_are_refused(tmp_path, monkeypatch, transform):
    run = Run(tmp_path, monkeypatch)
    statement = "Synthetic rising-shape conjecture."
    with pytest.raises(rb.BoardAccessRefused):
        rb.check_bundle(card("blind"), [{"path": "context.json", "content": transform(statement)}], run.season())


def test_blind_bundle_short_prediction_values_are_refused_when_quoted(tmp_path, monkeypatch):
    run = Run(tmp_path, monkeypatch)
    season = run.season()
    with pytest.raises(rb.BoardAccessRefused):
        rb.check_bundle(card("blind"), [{"path": "context.json", "content": json.dumps({"shape": "up"})}], season)
    ordinary = [{"path": "notes.txt", "content": "Set up the synthetic run and read the inputs."}]
    assert rb.check_bundle(card("blind"), ordinary, season) == ordinary


# D18 -- the open time is code-stamped and an exclusion needs its own late observation.

def test_season_open_time_is_code_stamped_and_early_no_commit_is_refused():
    request = seasons_request()
    with pytest.raises(ValueError, match="stamped by code"):
        rb.freeze_charter({**request, "opened_utc": "2020-01-01T00:00:00Z"})
    charter = rb.freeze_charter(request)
    early = {"p1": {"reason": "synthetic", "observed_utc": charter["opened_utc"]}}
    with pytest.raises(rb.RevealRefused, match="before its"):
        rb.check_reveal(charter, {"p0": "a" * 64}, no_commit=early, now="2999-01-01T00:00:00Z")
