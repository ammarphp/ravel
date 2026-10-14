"""Board seasons on the substrate: sealed commits, reveal barrier, sealing, channels and board tools.

Producers are synthetic stubs registered through the producer seam; crashes are real
process deaths (``os._exit``) in a child running the season graph, and recovery runs in
this process against the same scope root. Synthetic data only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest

from ravel.workflow import effect_ledger, graph_nodes, graph_substrate as gs
from ravel.workflow import hypothesis_board as board
from ravel.workflow import research_board as rb

HERE = Path(__file__).resolve()
CRASH = "RAVEL_TEST_SEASON_CRASH"
NO_COMMIT = "RAVEL_TEST_SEASON_NO_COMMIT"
NO_COMMIT_DELAY = "RAVEL_TEST_SEASON_NO_COMMIT_DELAY"
COUNTS = "RAVEL_TEST_SEASON_COUNTS"
ACTORS = ("p0", "p1", "p2")
STUB = "synthetic-stub"
INSTANCE = {"season": "season-1", "producer": STUB}


def bump(name):
    path = Path(os.environ[COUNTS]) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write("x")


def count(scope, name):
    path = Path(scope) / "counts" / name
    return len(path.read_text()) if path.exists() else 0


def submission(actor, packet, shape="up"):
    return {"schema_version": 1, "actor_id": actor, "session_id": f"session-{actor}",
            "nonce": f"initial-nonce-for-{actor}", "hypotheses": [
                {"id": "H1", "statement": f"Synthetic conjecture with a {shape} shape.",
                 "predictions": {key: (shape if key == "shape" else None) for key in packet["prediction_keys"]},
                 "artifact_refs": [], "contradicts": []}]}


def stub(packet):
    """A sealed producer: it sees only its own projected packet and returns its submission."""
    actor = packet["actor"]["actor_id"]
    bump("dispatch-" + actor)
    seen = Path(os.environ[COUNTS]).parent / "seen" / f"{actor}-{time.time_ns()}.json"
    seen.parent.mkdir(parents=True, exist_ok=True)
    seen.write_text(json.dumps(packet, sort_keys=True))
    if actor in os.environ.get(NO_COMMIT, "").split(","):
        time.sleep(float(os.environ.get(NO_COMMIT_DELAY, "0")))
        raise rb.NoCommit("synthetic supervisor reported no commit")
    # p0 and p2 make the same prediction vector: p2 earns no diversity credit.
    return {"submission": submission(actor, packet, shape="down" if actor == "p1" else "up"), "receipt": None}


def charter_request(actors=ACTORS, *, max_wall_seconds=600, opened_utc=None):
    return {"board_id": "synthetic-board", "season": "season-1", "mode": "production",
            "participants": [{"actor_id": a, "model_id": f"declared-model-{a}", "session_id": f"session-{a}",
                              "fresh_generation": True, "broker": {"node_id": f"proposer-{a}", "attempt": 1}}
                             for a in actors],
            "prediction_keys": ["acceptance", "shape"], "limits": dict(board.DEFAULT_LIMITS), "artifact_pins": [],
            "max_wall_seconds": max_wall_seconds, "opened_utc": opened_utc}


def _barrier(scope, actor):
    """Crash ``actor`` before its dispatch, once both siblings' map writes are checkpointed."""
    if os.environ.get(CRASH) != actor:
        return
    deadline = time.monotonic() + 60
    db = Path(scope) / gs.DB
    while time.monotonic() < deadline:
        try:
            with sqlite3.connect(str(db)) as connection:
                rows = connection.execute("SELECT count(*) FROM writes WHERE channel = 'results'").fetchone()[0]
        except sqlite3.Error:
            rows = 0
        if rows >= len(ACTORS) - 1:
            os._exit(9)
        time.sleep(0.02)
    raise AssertionError("siblings never checkpointed their sealed writes")


def install():
    rb.register_producer(STUB, stub, replace=True)
    original = rb.producer_identity

    def identity(state):
        bump("entry-" + state["actor"]["actor_id"])
        _barrier(state["meta"]["scope_root"], state["actor"]["actor_id"])
        return original(state)
    rb.producer_identity = identity
    return original


def _drive(scope, extra):
    install()
    extra = json.loads(extra)
    gs.run(scope, rb.SEASON_GRAPH, INSTANCE, input=extra.get("input"), workers=3)


def run_crashing(scope, crash, extra):
    env = {**os.environ, CRASH: crash, COUNTS: str(Path(scope) / "counts")}
    code = "import runpy,sys; m=runpy.run_path(sys.argv[1]); m['_drive'](sys.argv[2], sys.argv[3])"
    done = subprocess.run([sys.executable, "-c", code, str(HERE), str(scope), json.dumps(extra)], env=env,
                          capture_output=True, text=True, timeout=180)
    assert done.returncode == 9, done.stderr[-3000:]


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("RAVEL_WORK_ROOT", str(tmp_path / "work"))
    scope = tmp_path / "run"
    scope.mkdir()
    monkeypatch.setenv(COUNTS, str(scope / "counts"))
    original = install()
    yield scope
    rb.producer_identity = original
    rb.PRODUCERS.pop(STUB, None)


def values(scope, observation):
    ctx = gs._context(scope, rb.SEASON_GRAPH, INSTANCE)
    with gs.saver(scope) as checkpointer:
        app = gs.build(rb.SEASON_GRAPH, ctx, checkpointer=checkpointer)
        return app.get_state({"configurable": {"thread_id": observation["thread_id"]}}).values


def mentions(value, word):
    if isinstance(value, dict):
        return any(word in str(k) or mentions(v, word) for k, v in value.items())
    if isinstance(value, list):
        return any(mentions(v, word) for v in value)
    return isinstance(value, str) and word in value


# ---- acceptance 1: Q3 on the substrate -------------------------------------------------------

def test_sealed_season_crash_reruns_only_the_crashed_proposer_without_peer_visibility(run):
    run_crashing(run, "p2", {"input": {"charter": charter_request()}})
    assert {a: count(run, "dispatch-" + a) for a in ACTORS} == {"p0": 1, "p1": 1, "p2": 0}
    observation = gs.run(run, rb.SEASON_GRAPH, INSTANCE, workers=3)
    assert observation["next"] == [] and observation["terminal"] is None, observation
    # Only the crashed proposer re-entered; no peer's producer effect was dispatched twice.
    assert {a: count(run, "entry-" + a) for a in ACTORS} == {"p0": 1, "p1": 1, "p2": 2}
    assert {a: count(run, "dispatch-" + a) for a in ACTORS} == {"p0": 1, "p1": 1, "p2": 1}
    producers = [r for r in effect_ledger.receipts(run) if "/map:producers/" in r["path"]]
    assert len(producers) == 3 and all(r["status"] == "completed" and r["attempt"] == 1 for r in producers)
    # Each producer saw only its own packet: no peer identity, commit or payload.
    for path in (run / "seen").glob("*.json"):
        actor, packet = path.stem.split("-")[0], json.loads(path.read_text())
        text = json.dumps(packet)
        assert all(peer not in text for peer in ACTORS if peer != actor)
        assert not mentions(packet, "board_sealed") and not mentions(packet, "board_commits")
    state = values(run, observation)
    assert state["board_sealed"] == {}
    assert sorted(state["board_commits"]) == list(ACTORS)
    view = rb.season(rb.journal_root(run, "season-1"), rundir=run)
    assert view["snapshot"]["phase"] == "followups_open"
    assert state["board_head"] == view["head"]["sha256"]
    events = [e["event"] for e in view["entries"]]
    assert events == ["commit"] * 3 + ["reveal"] * 3
    duplicates = [p for p in state["board_posts"]["entries"] if p.get("duplicate_of")]
    assert [p["actor"] for p in duplicates] == ["p2"]


def test_producer_view_excludes_every_board_channel_and_peer_participants(run):
    ctx = gs._context(run, rb.PRODUCER_GRAPH, INSTANCE)
    keys = graph_nodes._view_keys(gs.build(rb.PRODUCER_GRAPH, ctx))
    assert keys == {"meta", "actor", "packet"}
    packet = rb.producer_packet({"board_charter": rb.freeze_charter(charter_request())},
                                rb.freeze_charter(charter_request())["participants"][0])
    assert packet["actor"]["actor_id"] == "p0" and "participants" not in json.dumps(packet["packet"])


# ---- acceptance 2: undeclared kinds; sealed-phase peer reads ---------------------------------

def _posts(entries, limits=None):
    return {"charter_sha256": "0" * 64, "limits": limits or dict(board.DEFAULT_LIMITS), "entries": entries}


def _envelope(kind, previous, n, predictions=None, actor="p0"):
    body = {"kind": kind, "predictions": predictions} if predictions else {"kind": kind}
    entry = {"id": f"e{n}", "kind": kind, "actor": actor, "season": "season-1", "sequence": n,
             "previous_sha256": previous, "body_pin": effect_ledger.digest(body), "fields": body}
    return {**entry, "sha256": effect_ledger.digest(entry)}


@pytest.mark.parametrize("kind", ["verdict", "agree", "summary", "priority", "approval", "gossip"])
def test_posts_channel_refuses_undeclared_and_absent_by_design_kinds(kind):
    first = _envelope("hypothesis", "0" * 64, 1, {"shape": "up"})
    with pytest.raises(ValueError, match="undeclared|absent by design"):
        rb.posts_reducer(_posts([first]), _posts([_envelope(kind, first["sha256"], 2)]))


def test_posts_channel_refuses_a_broken_chain_and_enforces_charter_caps():
    first = _envelope("hypothesis", "0" * 64, 1, {"shape": "up"})
    with pytest.raises(ValueError, match="chain"):
        rb.posts_reducer(_posts([first]), _posts([_envelope("question", "f" * 64, 2)]))
    tight = {**board.DEFAULT_LIMITS, "max_records": 1}
    with pytest.raises(ValueError, match="record bound"):
        rb.posts_reducer(_posts([first], tight), _posts([_envelope("question", first["sha256"], 2)], tight))
    small = {**board.DEFAULT_LIMITS, "max_payload_bytes": 8}
    with pytest.raises(ValueError, match="byte bound"):
        rb.posts_reducer({}, _posts([first], small))


def test_commit_channel_refuses_a_changed_sealed_submission():
    left = rb.commits_reducer({}, {"p0": "a" * 64})
    assert rb.commits_reducer(left, {"p0": "a" * 64}) == {"p0": "a" * 64}
    with pytest.raises(ValueError, match="sealed submission changed after commit"):
        rb.commits_reducer(left, {"p0": "b" * 64})


def _tools(run, card, actor="p0", *, allowed=("board read", "board find", "board post")):
    from ravel.workflow.broker import Broker, work_root
    workspace = work_root(run) / f"proposer-{actor}" / "1"
    for name in ("inputs", "outputs", "scratch", "calls"):
        (workspace / name).mkdir(parents=True, exist_ok=True)
    broker = Broker(run, workspace, node_id=f"proposer-{actor}", attempt=1, allowed_actions=list(allowed),
                    max_calls=50, actor_id=actor)
    rb.register_tools(broker, rb.journal_root(run, "season-1"), card)
    return broker


WORKSPACE = {"sees": {"profile": "workspace", "forbidden_inputs": []}}
CRITIC = {"sees": {"profile": "spec-denied", "forbidden_inputs": []}}
BLIND = {"sees": {"profile": "blind", "forbidden_inputs": []}}


def test_peer_read_in_the_sealed_phase_is_denied_and_logged(run):
    from ravel.workflow.broker import ledger
    rb.open_season(run, rb.freeze_charter(charter_request()))  # charter frozen; nothing revealed
    broker = _tools(run, WORKSPACE)
    for n, (action, args) in enumerate((("board read", {}), ("board find", {"query": "conjecture"}))):
        reply = broker.call({"call_id": f"sealed-{n}", "action": action, "args": args})
        assert reply["status"] == "refused" and reply["error"]["code"] == "peer_read_denied"
    denials = [r["record"] for r in ledger(run, "peer-denials")]
    assert len(denials) == 2 and {d["code"] for d in denials} == {"peer_read_denied"}
    assert all(d["actor_id"] == "p0" and d["season"] == "season-1" for d in denials)


# ---- acceptance 3: reveal barrier -------------------------------------------------------------

def test_reveal_before_all_commits_or_the_timeout_is_refused():
    # The open time is code-stamped; this pure barrier check fixes it for the arithmetic.
    charter = {**rb.freeze_charter(charter_request(max_wall_seconds=60)), "opened_utc": "2026-01-01T00:00:00Z"}
    commits = {"p0": "a" * 64, "p1": "b" * 64}
    with pytest.raises(rb.RevealRefused, match="every participant"):
        rb.check_reveal(charter, commits, no_commit=[], now="2026-01-01T00:00:30Z")
    with pytest.raises(rb.RevealRefused, match="before"):
        rb.check_reveal(charter, commits, no_commit=["p2"], now="2026-01-01T00:00:30Z")
    assert rb.check_reveal(charter, commits, no_commit=["p2"], now="2026-01-01T00:01:01Z") == ["p2"]
    assert rb.check_reveal(charter, {**commits, "p2": "c" * 64}, no_commit=[], now="2026-01-01T00:00:01Z") == []


def test_season_with_an_early_no_commit_holds_without_revealing(run, monkeypatch):
    monkeypatch.setenv(NO_COMMIT, "p1")
    observation = gs.run(run, rb.SEASON_GRAPH, INSTANCE, input={"charter": charter_request()}, workers=3)
    assert observation["terminal"]["status"] == "hold"
    assert observation["terminal"]["reason"] == "reveal_before_commits"
    assert not rb.journal_root(run, "season-1").exists()


def test_season_after_the_timeout_excludes_no_commit_and_reveals_the_rest(run, monkeypatch):
    monkeypatch.setenv(NO_COMMIT, "p1")
    monkeypatch.setenv(NO_COMMIT_DELAY, "2.1")  # the supervisor observes no commit after the timeout
    request = charter_request(max_wall_seconds=1)
    observation = gs.run(run, rb.SEASON_GRAPH, INSTANCE, input={"charter": request}, workers=3)
    assert observation["terminal"] is None, observation
    state = values(run, observation)
    assert state["board_snapshot"]["no_commit"] == ["p1"]
    view = rb.season(rb.journal_root(run, "season-1"), rundir=run)
    assert sorted(p["actor_id"] for p in view["charter"]["participants"]) == ["p0", "p2"]


# ---- acceptance 4: sealing ----------------------------------------------------------------------

def _receipt(run, actor, *, session, attestation="transport_attested", confirmed=True):
    from ravel.workflow.broker import append_ledger, sha
    path = run / "agent-receipts" / f"{actor}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"attestation": attestation, "session_id": session, "isolation": {
        "user_configuration_loaded": False, "evidence": {"confirmed": confirmed}}}))
    pin = {"path": f"agent-receipts/{actor}.json", "sha256": sha(path)}
    append_ledger(run, "worker-receipts", {"pin": pin, "node_id": f"proposer-{actor}", "attempt": 1})
    return pin


def test_participant_without_an_attested_distinct_session_marks_the_season_unsealed(run):
    participants = rb.freeze_charter(charter_request(("p0", "p1")))["participants"]
    good = {"p0": _receipt(run, "p0", session="session-p0"), "p1": _receipt(run, "p1", session="session-p1")}
    sealed = rb.sealing(run, participants, good)
    assert sealed["status"] == "sealed" and sealed["independence"] == "attested_distinct_sessions"
    for receipts in ({"p0": good["p0"], "p1": None},
                     {"p0": good["p0"], "p1": _receipt(run, "p1", session="session-p0")},
                     {"p0": good["p0"], "p1": _receipt(run, "p1", session="s9", attestation="self_attested")},
                     {"p0": good["p0"], "p1": _receipt(run, "p1", session="s8", confirmed=False)}):
        result = rb.sealing(run, participants, receipts)
        assert result["status"] == "unsealed" and not mentions(result, "independence")


def test_stub_season_without_attested_sessions_is_unsealed_with_no_independence_label(run):
    observation = gs.run(run, rb.SEASON_GRAPH, INSTANCE, input={"charter": charter_request()}, workers=3)
    assert observation["terminal"] is None, observation
    state = values(run, observation)
    assert state["board_snapshot"]["unsealed"] is True
    assert not mentions(state["board_snapshot"], "independence")
    assert not mentions(state["results"], "independence")
    assert state["results"]["season"]["unsealed"] is True


# ---- board tools and projections ---------------------------------------------------------------

def _revealed(run):
    observation = gs.run(run, rb.SEASON_GRAPH, INSTANCE, input={"charter": charter_request()}, workers=3)
    assert observation["terminal"] is None, observation
    return observation


def test_blind_roles_are_refused_all_three_board_tools(run):
    _revealed(run)
    broker = _tools(run, BLIND)
    for n, (action, args) in enumerate((("board read", {}), ("board find", {"query": "x"}),
                                        ("board post", {"post": {}}))):
        reply = broker.call({"call_id": f"blind-{n}", "action": action, "args": args})
        assert reply["status"] == "refused" and reply["error"]["code"] == "board_prose_forbidden"


def test_read_and_find_honour_the_caller_projection(run):
    _revealed(run)
    workspace = _tools(run, WORKSPACE)
    read = json.loads(workspace.call({"call_id": "r", "action": "board read", "args": {}})["stdout_tail"])
    assert read["profile"] == "workspace" and len(read["entries"]) == 6
    critic = _tools(run, CRITIC, actor="p1")
    seen = json.loads(critic.call({"call_id": "r", "action": "board read", "args": {}})["stdout_tail"])
    assert seen["profile"] == "spec-denied" and not mentions(seen, "actor_id")
    found = json.loads(critic.call({"call_id": "f", "action": "board find",
                                    "args": {"query": "conjecture"}})["stdout_tail"])
    assert found["rows"] and all(row["profile"] == "spec-denied" for row in found["rows"])
    assert not any(peer in json.dumps(found) for peer in ACTORS)
    post = critic.call({"call_id": "p", "action": "board post", "args": {"post": {}}})
    assert post["status"] == "refused" and post["error"]["code"] == "board_post_refused"


def test_store_index_is_rebuilt_from_the_journal(run):
    _revealed(run)
    root = rb.journal_root(run, "season-1")
    first = rb.index_season(run, root)
    (run / gs.STORE).unlink()
    assert rb.index_season(run, root) == first and first["rows"] > 0


# ---- board_sync, resumed reveal and meetings as seasons -----------------------------------------

def test_sync_replays_a_verified_extension_and_holds_on_divergence(run):
    observation = _revealed(run)
    state = values(run, observation)
    root = rb.journal_root(run, "season-1")
    assert rb.sync_update(run, "season-1", state["board_head"]) == {}
    post = {"kind": "question", "actor_sequence": 1, "parents": [], "fields": {
        "missing_observation": "synthetic control yield", "permitted_source": "synthetic source"}}
    reply = _tools(run, WORKSPACE).call({"call_id": "q", "action": "board post", "args": {"post": post}})
    assert reply["status"] == "ok", reply
    update = rb.sync_update(run, "season-1", state["board_head"])
    assert update["board_head"] == rb.season(root, rundir=run)["head"]["sha256"]
    merged = rb.posts_reducer(state["board_posts"], update["board_posts"])
    retained = state["board_posts"]["entries"]
    assert [e["kind"] for e in retained] == ["hypothesis"] * 3
    assert merged["entries"][:3] == retained and [e["kind"] for e in merged["entries"][3:]] == ["question"]
    with pytest.raises(graph_nodes.RecoveryHold, match="board_divergence"):
        rb.sync_update(run, "season-1", "e" * 64)


def test_resumed_reveal_appends_no_duplicate_entries_and_keeps_its_record(run):
    observation = _revealed(run)
    state = values(run, observation)
    again = rb.reveal_season(run, state["board_charter"], state["board_commits"],
                             {a: {"path": f"framework/board/season-1/sealed/{a}.json",
                                  "sha256": __import__("hashlib").sha256(
                                      (run / f"framework/board/season-1/sealed/{a}.json").read_bytes()).hexdigest()}
                              for a in ACTORS}, {}, [])
    view = rb.season(rb.journal_root(run, "season-1"), rundir=run)
    assert len(view["entries"]) == 6 and again["head"] == state["board_head"]


def test_a_meeting_binds_its_season_and_an_unsealed_season_has_no_independence_label(run):
    from ravel.workflow import research_board_discussion as meeting
    with pytest.raises(ValueError):
        meeting.season_binding(run / "missing")
    _revealed(run)
    binding = meeting.season_binding(rb.journal_root(run, "season-1"))
    assert binding["season"] == "season-1" and binding["unsealed"] is True
    assert binding["head_sha256"] == rb.season(rb.journal_root(run, "season-1"), rundir=run)["head"]["sha256"]
    assert not mentions(binding, "independence")
    (run / "research/board/season-1.reveal.json").unlink()
    with pytest.raises(ValueError, match="revealed through the board.season graph"):
        meeting.season_binding(rb.journal_root(run, "season-1"))


def test_a_version_one_board_meeting_has_no_season(tmp_path):
    from ravel.workflow import research_board_discussion as meeting
    charter = {"schema_version": 1, "board_id": "synthetic-board", "participants": [
        {"actor_id": "p0", "model_id": "declared-model", "session_id": "s0", "fresh_generation": True}],
        "prediction_keys": ["shape"], "limits": dict(board.DEFAULT_LIMITS), "artifact_pins": []}
    board.create(tmp_path / "board", charter)
    assert meeting.season_binding(tmp_path / "board") is None
