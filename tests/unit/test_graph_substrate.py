"""Graph substrate kernel: crash recovery, fan-out, interrupts, errors, drain and the CLI.

Crashes are real process deaths (``os._exit``) in a child running a fixture graph;
the recovery runs in this process against the same scope root. Synthetic data only.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Annotated, Any, TypedDict

import pytest

from ravel.workflow import effect_ledger, graph_nodes, graph_registry, graph_substrate as gs
from ravel.workflow.state_io import file_lock

HERE = Path(__file__).resolve()
CRASH = "RAVEL_TEST_GRAPH_CRASH"
ATLAS = "RAVEL_TEST_ATLAS_SHA256"
VARIANT = "RAVEL_TEST_VARIANT"


def row(graph_id, version=1, keys=("case",), gates=None, subgraphs=(), roles=()):
    return {"id": graph_id, "version": version, "kernel_version": 1, "module": "ravel.workflow.graph_substrate",
            "builder": "selftest", "scope": "case", "instance_keys": list(keys), "roles": list(roles),
            "gates": gates or {}, "subgraphs": [{"id": s, "version": 1} for s in subgraphs], "interrupts": [],
            "structure_sha256": graph_registry.PIN, "owner": "graph-substrate"}


def bump(scope, name):
    path = Path(scope) / "counts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write("x")


def count(scope, name):
    path = Path(scope) / "counts" / name
    return len(path.read_text()) if path.exists() else 0


def crash_point(name):
    if os.environ.get(CRASH) == name:
        os._exit(9)


def _state_class(**channels):
    from typing import TypedDict
    return TypedDict("FixtureState", {**graph_nodes.BaseState.__annotations__, **channels}, total=False)


def _builder(state=None):
    from langgraph.graph import StateGraph
    return StateGraph(state or _state_class(results=Annotated[dict, graph_nodes.write_once], extra=Any,
                                            join=str, n=int, seen=Annotated[dict, graph_nodes.write_once]))


# ---- fixture graphs -----------------------------------------------------------------------

def standard(builder, graph_id, subsystem="fixture"):
    """The decision_turn, reconcile and hold every builder owns (§1.8)."""
    graph_nodes.add(builder, "decision_turn", graph_nodes.decision_turn(subsystem), graph_id=graph_id)
    graph_nodes.add(builder, "reconcile", graph_nodes.reconcile_node(), graph_id=graph_id)
    graph_nodes.add(builder, "hold", graph_nodes.hold("fixture_hold"), graph_id=graph_id)
    return builder


def keyed(name, run, *, kind="model", to_state=None, **kwargs):
    return graph_nodes.effect(name, kind=kind, run=run, segment=lambda s: {"step": name},
                              identity=lambda s: {"step": name},
                              to_state=to_state or (lambda s, r: {"results": {name: r}}), **kwargs)


def effects_graph(ctx):
    """first -> second, each a keyed effect; crash points before, inside and after receipts."""
    from langgraph.graph import END, START
    builder = _builder()
    scope = ctx.scope_root

    def make(name, downstream=False):
        def run(state, identity):
            bump(scope, name)
            if downstream:
                saved = effect_ledger.latest(state["meta"]["scope_root"], graph_nodes.invocation(
                    state["meta"], {"step": name}))
                target = Path(scope) / "worker" / f"{name}.json"
                target.parent.mkdir(exist_ok=True)
                target.write_text(json.dumps({"status": "completed", "result": {"done": name},
                                              "identity_sha256": saved["identity_sha256"],
                                              "epoch": saved["epoch"]}))
            crash_point("inside:" + name)
            return {"done": name}
        def to_state(state, result):
            crash_point("after:" + name)
            return {"results": {name: result}}
        return keyed(name, run, to_state=to_state, downstream=(
            lambda s: {"kind": "worker_receipt", "path": f"worker/{name}.json"}) if downstream else None)
    add = lambda name, node: graph_nodes.add(builder, name, node, graph_id=ctx.graph_id)
    add("first", make("first"))
    add("second", make("second", downstream=ctx.instance["case"] == "downstream"))
    standard(builder, ctx.graph_id)
    builder.add_edge(START, "first")
    builder.add_edge("first", "second")
    builder.add_edge("second", END)
    return builder


class ItemView(TypedDict, total=False):
    meta: dict
    item: dict


def item_graph(ctx):
    """One map item: a keyed effect; item 'c' can crash, 'f' fails, 'h' holds."""
    from langgraph.graph import END, START, StateGraph
    builder = StateGraph(_state_class(item=dict), input_schema=ItemView)
    scope = ctx.scope_root

    def entry(state):
        item = state["item"]
        bump(scope, "entry-" + item["id"])
        if item["id"] == os.environ.get(CRASH, "").removeprefix("item:"):
            time.sleep(1.5)  # siblings checkpoint their writes first (Q3)
            os._exit(9)
        return {"item": item["id"], "value": item["value"]}

    def run(state, identity):
        if identity["item"] == "f":
            raise effect_ledger.NotDispatched("synthetic item failure")
        if identity["item"] == "h":
            raise graph_nodes.RecoveryHold("synthetic_hold", "provide the synthetic input")
        return {"item": identity["item"], "square": identity["value"] ** 2}
    node = graph_nodes.effect("item", kind="model", run=run, segment=lambda s: {"work": "square"}, identity=entry,
                              to_state=lambda s, r: {"results": {"square": r}})
    graph_nodes.add(builder, "work", node, graph_id=ctx.graph_id)
    standard(builder, ctx.graph_id)
    builder.add_edge(START, "work")
    builder.add_edge("work", END)
    return builder


def fanout_graph(ctx):
    from langgraph.graph import END, START
    builder = _builder()
    child = gs.BuildContext(scope_root=ctx.scope_root, graph_id="t.item", version=1, instance={"case": "x"})
    target = gs.build("t.item", child)
    edge, node = graph_nodes.map_node(lambda s: s["items"], lambda item: item["id"], target,
                                      lambda s, item: {"item": item}, name="items")

    def join(state):
        return {"join": effect_ledger.digest(graph_nodes.joined(state))}
    graph_nodes.add(builder, "items", node, graph_id=ctx.graph_id)
    graph_nodes.add(builder, "join", graph_nodes.Node("effect", join), graph_id=ctx.graph_id)
    standard(builder, ctx.graph_id)
    graph_nodes.connect(builder, START, edge)
    builder.add_edge("items", "join")
    builder.add_edge("join", END)
    return builder


class BranchView(TypedDict, total=False):
    meta: dict
    n: int


def branch_graph(ctx):
    """One branch: a typed interrupt, then a gate that needs an approval record."""
    from langgraph.graph import END, START, StateGraph
    builder = StateGraph(_state_class(results=Annotated[dict, graph_nodes.write_once], n=int,
                                      seen=Annotated[dict, graph_nodes.write_once]), input_schema=BranchView)
    add = lambda name, node: graph_nodes.add(builder, name, node, graph_id=ctx.graph_id)
    add("ask", graph_nodes.interrupt("checkin1_response", lambda s: {"branch": s["n"]}))
    add("approve", graph_nodes.gate("approve_plan", lambda s: {"kind": "plan", "digest": effect_ledger.digest(s["n"]),
                                                                "summary": "synthetic", "pins": []}))
    add("apply", graph_nodes.effect("apply", kind="external", run=lambda s, r: r, segment=lambda s: {"branch": s["n"]},
                                    identity=lambda s: {"branch": s["n"]},
                                    to_state=lambda s, r: {"results": {str(r["branch"]): True}}))
    add("refused", graph_nodes.hold("approval_record_missing", "record an approval for the exact plan digest"))
    standard(builder, ctx.graph_id)
    builder.add_edge(START, "ask")
    builder.add_edge("ask", "approve")
    graph_nodes.connect(builder, "approve", graph_nodes.gate_route("approve_plan", passed="apply", refused="refused"))
    builder.add_edge("apply", END)
    return builder


def ask_graph(ctx):
    """Two parallel branches (map into a subgraph), each pausing on a typed interrupt."""
    from langgraph.graph import END, START
    builder = _builder()
    child = gs.BuildContext(scope_root=ctx.scope_root, graph_id="t.branch", version=1, instance={"case": "x"})
    edge, node = graph_nodes.map_node(lambda s: [1, 2], str, gs.build("t.branch", child),
                                      lambda s, n: {"n": n}, name="branch")
    graph_nodes.add(builder, "branch", node, graph_id=ctx.graph_id)
    standard(builder, ctx.graph_id)
    graph_nodes.connect(builder, START, edge)
    builder.add_edge("branch", END)
    return builder


def misc_graph(ctx):
    """case: loop | boom | refusal | unsafe | tripwire | gated | stopmid | command | nested | version."""
    from langgraph.graph import END, START
    builder = _builder()
    case = ctx.instance["case"]
    add = lambda name, node: graph_nodes.add(builder, name, node, graph_id=ctx.graph_id)
    standard(builder, ctx.graph_id)
    if case == "stopmid":
        def work(state):
            if state.get("n", 0) == 1:
                (Path(state["meta"]["scope_root"]) / gs.STOP).write_text('{"reason": "synthetic"}')
            return {"n": state.get("n", 0) + 1}
        add("guard", graph_nodes.guard(lambda s: "go" if s.get("n", 0) < 3 else "exhausted",
                                       routes={"go": "work", "exhausted": "done"}))
        add("work", graph_nodes.Node("effect", work))
        add("done", graph_nodes.hold("stopmid_complete"))
        builder.add_edge(START, "guard")
        builder.add_edge("work", "guard")
        return builder
    if case == "loop":
        add("spin", graph_nodes.Node("effect", lambda s: {"n": s.get("n", 0) + 1}))
        builder.add_edge(START, "spin")
        builder.add_edge("spin", "spin")
        return builder
    def body(state):
        from langgraph.types import Command
        if case == "boom":
            raise KeyError("synthetic failure")
        if case == "command":
            return Command(goto="hold")
        if case == "refusal":
            from ravel.workflow.transport_registry import TransportRefusal
            raise TransportRefusal("no transport meets the card", ["tool_calling"])
        if case == "unsafe":
            from datetime import datetime
            return {"extra": datetime(2026, 1, 1)}
        if case == "tripwire":
            return {"seen": {"tripwire": graph_nodes.TRIPWIRE.get()}}
        if case == "nested":
            gs.run(state["meta"]["scope_root"], "t.effects", {"case": "plain"})
        if case == "forge":
            return {"gates": {"launch": {"action_digest": "0" * 64, "errors": [], "sequence": 2 ** 62}}}
        return {}
    if case in {"gated", "gated_unbound"}:
        bound = {"action_bytes_sha256": hashlib.sha256(b"synthetic launch argv").hexdigest()} \
            if case == "gated" else {}
        node = graph_nodes.effect("gated", kind="external", run=lambda s, r: pytest.fail("acted without gate"),
                                  segment=lambda s: {"gated": 1}, identity=lambda s: {"gated": 1, **bound},
                                  to_state=lambda s, r: {}, gate="launch")
    elif case == "version":
        def run(state, identity):
            bump(ctx.scope_root, "version")
            return {"variant": identity["variant"]}
        node = graph_nodes.effect("versioned", kind="model", run=run, segment=lambda s: {"fixed": 1},
                                  identity=lambda s: {"variant": os.environ.get(VARIANT, "a")},
                                  provisioning=lambda s: {"atlas_sha256": os.environ.get(ATLAS, "a")},
                                  to_state=lambda s, r: {"results": {"v": r}})
    else:
        node = graph_nodes.Node("effect", body)
    add("work", node)
    builder.add_edge(START, "work")
    builder.add_edge("work", END)
    return builder


def parent_graph(ctx):
    from langgraph.graph import END, START
    builder = _builder()
    child = gs.BuildContext(scope_root=ctx.scope_root, graph_id="t.effects", version=1, instance={"case": "plain"})
    graph_nodes.add(builder, "child", graph_nodes.subgraph("t.effects", child), graph_id=ctx.graph_id)
    standard(builder, ctx.graph_id)
    builder.add_edge(START, "child")
    builder.add_edge("child", END)
    return builder


ROWS = {"t.effects": effects_graph, "t.fanout": fanout_graph, "t.ask": ask_graph, "t.branch": branch_graph,
        "t.misc": misc_graph, "t.parent": parent_graph, "t.item": item_graph}
SUBGRAPHS = {"t.fanout": ("t.item",), "t.ask": ("t.branch",), "t.parent": ("t.effects",)}
GATES = {"t.branch": {"approve_plan": {"required_providers": []}}, "t.misc": {"launch": {"required_providers": []}}}


def worker_receipt(root, receipt, document):
    return {"status": document["status"], "result": document["result"]}


def fixtures(version=1):
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(graph_registry.registered(
        *(row(g, version if g == "t.misc" else 1, gates=GATES.get(g), subgraphs=SUBGRAPHS.get(g, ()))
          for g in ROWS), builders=ROWS))
    stack.enter_context(effect_ledger.registrations(validators={"worker_receipt": worker_receipt}))
    return stack


def _drive(scope, graph_id, instance, extra):
    with fixtures():
        extra = json.loads(extra)
        gs.run(scope, graph_id, json.loads(instance), input=extra.get("input"), workers=extra.get("workers"))


def run_crashing(scope, graph_id, instance, crash, extra=None):
    env = {**os.environ, CRASH: crash}
    code = ("import runpy,sys; m=runpy.run_path(sys.argv[1]); "
            "m['_drive'](sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])")
    done = subprocess.run([sys.executable, "-c", code, str(HERE), str(scope), graph_id, json.dumps(instance),
                           json.dumps(extra or {})], env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == 9, done.stderr[-3000:]


# ---- acceptance 1: Q1 -----------------------------------------------------------------------

NONE_OPEN = {"started": 0, "ambiguous": 0, "reserving": 0}


def test_q1_crash_after_receipt_reruns_node_and_effect_count_stays_one(tmp_path):
    run_crashing(tmp_path, "t.effects", {"case": "plain"}, "after:first")
    assert count(tmp_path, "first") == 1
    with fixtures():
        observation = gs.run(tmp_path, "t.effects", {"case": "plain"})
    assert observation["next"] == [] and observation["terminal"] is None
    assert count(tmp_path, "first") == 1 and count(tmp_path, "second") == 1
    assert observation["effects"] == {"completed": 2, **NONE_OPEN}


# ---- acceptance 2: Q2 ------------------------------------------------------------------------

def test_q2_reservation_without_outcome_routes_to_reconcile_never_redispatched(tmp_path):
    run_crashing(tmp_path, "t.effects", {"case": "plain"}, "inside:second")
    assert count(tmp_path, "second") == 1
    with fixtures():
        observation = gs.run(tmp_path, "t.effects", {"case": "plain"})
        assert count(tmp_path, "second") == 1
        assert [i["kind"] for i in observation["interrupts"]] == ["reconcile_evidence"]
        identifier = observation["interrupts"][0]["payload"]["payload"]["call_id"]
        assert effect_ledger.read(tmp_path, identifier)["status"] == "started"
        again = gs.run(tmp_path, "t.effects", {"case": "plain"})
        assert count(tmp_path, "second") == 1 and again["interrupts"]
        evidence = tmp_path / "evidence.json"
        evidence.write_text('{"observed": "synthetic"}')
        pin = {"path": "evidence.json", "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}
        done = gs.respond(tmp_path, "t.effects", {"case": "plain"}, {again["interrupts"][0]["id"]: {
            "call_id": identifier, "outcome": "completed", "evidence": [pin], "reason": "synthetic attestation",
            "result": {"done": "second"}}})
    assert done["next"] == [] and done["interrupts"] == []
    assert count(tmp_path, "second") == 1
    assert effect_ledger.read(tmp_path, identifier)["reconciliation"]["evidence"] == [pin]


def test_q2_auto_reconcile_closes_from_downstream_receipt_through_its_validator(tmp_path):
    run_crashing(tmp_path, "t.effects", {"case": "downstream"}, "inside:second")
    with fixtures():
        observation = gs.run(tmp_path, "t.effects", {"case": "downstream"})
    assert observation["interrupts"] == [] and observation["next"] == []
    assert count(tmp_path, "second") == 1
    receipt = [r for r in effect_ledger.receipts(tmp_path) if r["path"].endswith("/step:second")][0]
    assert receipt["status"] == "completed" and receipt["reconciliation"]["auto"] is True


def test_q2_downstream_receipt_without_a_registered_validator_is_not_credited(tmp_path):
    run_crashing(tmp_path, "t.effects", {"case": "downstream"}, "inside:second")
    with graph_registry.registered(*(row(g, subgraphs=SUBGRAPHS.get(g, ()), gates=GATES.get(g)) for g in ROWS),
                                   builders=ROWS):
        observation = gs.run(tmp_path, "t.effects", {"case": "downstream"})
    assert [i["kind"] for i in observation["interrupts"]] == ["reconcile_evidence"]
    assert count(tmp_path, "second") == 1


# ---- acceptance 3: map fan-out ----------------------------------------------------------------

ITEMS = [{"id": "a", "value": 2}, {"id": "b", "value": 3}, {"id": "c", "value": 5}, {"id": "d", "value": 7}]


def _values(scope, graph_id, instance, tid):
    ctx = gs._context(scope, graph_id, instance)
    with gs.saver(scope) as cp:
        return gs.build(graph_id, ctx, checkpointer=cp).get_state({"configurable": {"thread_id": tid}}).values


def test_map_crash_dispatches_no_completed_item_again_and_join_is_order_invariant(tmp_path):
    first = tmp_path / "forward"
    run_crashing(first, "t.fanout", {"case": "x"}, "item:c", {"input": {"items": ITEMS}, "workers": 4})
    with fixtures():
        observation = gs.run(first, "t.fanout", {"case": "x"}, workers=4)
        reordered = gs.run(tmp_path / "reverse", "t.fanout", {"case": "x"}, input={"items": ITEMS[::-1]}, workers=4)
        forward = _values(first, "t.fanout", {"case": "x"}, observation["thread_id"])
        reverse = _values(tmp_path / "reverse", "t.fanout", {"case": "x"}, reordered["thread_id"])
    assert observation["next"] == []
    receipts = effect_ledger.receipts(first)
    assert len(receipts) == 4 and all(r["status"] == "completed" and r["attempt"] == 1 for r in receipts)
    assert count(first, "entry-c") == 2
    assert forward["join"] == reverse["join"]
    assert {k: v["outcome"] for k, v in forward["results"].items()} == {"a": "ok", "b": "ok", "c": "ok", "d": "ok"}
    # Every item's effect sits under its own map path, never under a task id.
    assert sorted(r["path"].split("/map:items/item:")[1].split("/")[0] for r in receipts) == ["a", "b", "c", "d"]


def test_map_item_failure_and_hold_are_contained_as_item_outcomes(tmp_path):
    items = [{"id": "a", "value": 1}, {"id": "f", "value": 2}, {"id": "h", "value": 3}]
    with fixtures():
        observation = gs.run(tmp_path, "t.fanout", {"case": "x"}, input={"items": items}, workers=3)
        values = _values(tmp_path, "t.fanout", {"case": "x"}, observation["thread_id"])
    assert observation["next"] == [] and observation["terminal"] is None
    assert {k: v["outcome"] for k, v in values["results"].items()} == {"a": "ok", "f": "failed", "h": "held"}
    assert values["results"]["h"]["status"]["reason"] == "synthetic_hold"


def test_map_packet_outside_the_target_view_is_refused_before_send(tmp_path):
    with fixtures():
        child = gs.BuildContext(scope_root=tmp_path, graph_id="t.item", version=1, instance={"case": "x"})
        target = gs.build("t.item", child)
        edge, _ = graph_nodes.map_node(lambda s: [1], str, target, lambda s, i: {"item": {}, "secret": "x"},
                                       name="items")
        state = {"meta": {"graph_id": "t.fanout", "version": 1, "instance": {"case": "x"},
                          "scope_root": str(tmp_path), "path": None}}
        with pytest.raises(ValueError, match="outside the target's view"):
            edge.router(state)
        with pytest.raises(ValueError, match="compiled substrate graph"):
            graph_nodes.map_node(lambda s: [], str, object(), lambda s, i: {}, name="x")


# ---- acceptance 4 and 15: typed interrupts, gates and ledgered responses ------------------

def test_mixed_resume_map_with_invalid_value_is_refused_before_any_resume(tmp_path):
    with fixtures():
        observation = gs.run(tmp_path, "t.ask", {"case": "x"}, workers=2)
        pending = [i["id"] for i in observation["interrupts"]]
        assert len(pending) == 2 and {i["schema_id"] for i in observation["interrupts"]} == {"checkin1_response"}
        with pytest.raises(ValueError, match="refused before resume"):
            gs.respond(tmp_path, "t.ask", {"case": "x"}, {pending[0]: {"decision": "approve"},
                                                           pending[1]: {"decision": "yes please"}})
        with pytest.raises(ValueError, match="not a pending interrupt"):
            gs.respond(tmp_path, "t.ask", {"case": "x"}, {"0" * 32: {"decision": "approve"}})
        assert len(gs.status(tmp_path, "t.ask", {"case": "x"})["interrupts"]) == 2


def needs_record(scope_root, gate, action):
    record = Path(scope_root) / "approvals" / (action["digest"] + ".json")
    return [] if record.exists() else [{"code": "approval_missing", "gate": gate, "provider": "fixture",
                                        "message": "no approval record", "fix": "approve", "pins": []}]


def test_resume_never_passes_a_gate_and_responses_are_ledgered_as_data(tmp_path):
    with fixtures():
        observation = gs.run(tmp_path, "t.ask", {"case": "x"}, workers=2, gate_check=needs_record)
        done = gs.respond(tmp_path, "t.ask", {"case": "x"},
                          {i["id"]: {"decision": "approve"} for i in observation["interrupts"]},
                          gate_check=needs_record, workers=2)
        values = _values(tmp_path, "t.ask", {"case": "x"}, done["thread_id"])
    assert {k: (v["outcome"], v["status"]["reason"]) for k, v in values["results"].items()} == {
        "1": ("held", "approval_record_missing"), "2": ("held", "approval_record_missing")}
    assert effect_ledger.receipts(tmp_path) == []
    responses = list((tmp_path / "framework" / "responses").rglob("*.json"))
    assert len(responses) == 2
    assert all(json.loads(p.read_text())["approval_from_resume"] is False for p in responses)


def test_answered_interrupt_replays_on_a_new_thread_and_the_gate_still_refuses(tmp_path):
    """N5: a version bump starts a new thread; the recorded response is reused, never asked again."""
    def bumped(version):
        rows = [row(g, version if g in {"t.ask", "t.branch"} else 1, gates=GATES.get(g),
                    subgraphs=SUBGRAPHS.get(g, ())) for g in ROWS]
        for r in rows:
            if r["id"] == "t.ask":
                r["subgraphs"] = [{"id": "t.branch", "version": version}]
        return graph_registry.registered(*rows, builders=ROWS)
    with bumped(1), effect_ledger.registrations(validators={"worker_receipt": worker_receipt}):
        observation = gs.run(tmp_path, "t.ask", {"case": "x"}, workers=2, gate_check=needs_record)
        first = gs.respond(tmp_path, "t.ask", {"case": "x"},
                           {i["id"]: {"decision": "approve"} for i in observation["interrupts"]},
                           gate_check=needs_record, workers=2)
    with bumped(2):
        again = gs.run(tmp_path, "t.ask", {"case": "x"}, workers=2, gate_check=needs_record)
        values = _values(tmp_path, "t.ask", {"case": "x"}, again["thread_id"])
    assert again["thread_id"] != first["thread_id"]
    assert again["interrupts"] == [] and again["next"] == []
    assert {v["outcome"] for v in values["results"].values()} == {"held"}


# ---- acceptance 6 and errors as decision turns ------------------------------------------------

def test_recursion_limit_becomes_terminal_budget_exhausted(tmp_path):
    with fixtures():
        observation = gs.run(tmp_path, "t.misc", {"case": "loop"}, max_steps=5)
    assert observation["terminal"]["status"] == "budget_exhausted"


def test_node_exception_becomes_a_typed_decision_turn_not_an_abort(tmp_path):
    with fixtures():
        observation = gs.run(tmp_path, "t.misc", {"case": "boom"})
        values = _values(tmp_path, "t.misc", {"case": "boom"}, observation["thread_id"])
    assert observation["terminal"] == {"status": "decision_required", "reason": "exception", "would_make_possible": None}
    (failure,) = values["failures"].values()
    assert failure["kind"] == "graph-failure" and failure["error_type"] == "KeyError" and failure["node"] == "work"


def test_transport_refusal_names_missing_capabilities(tmp_path):
    with fixtures():
        observation = gs.run(tmp_path, "t.misc", {"case": "refusal"})
        values = _values(tmp_path, "t.misc", {"case": "refusal"}, observation["thread_id"])
    assert observation["terminal"]["reason"] == "transport_refusal"
    assert list(values["failures"].values())[0]["missing"] == ["tool_calling"]


def test_effect_gate_recheck_refuses_before_reserving(tmp_path):
    with fixtures():
        observation = gs.run(tmp_path, "t.misc", {"case": "gated"})
        values = _values(tmp_path, "t.misc", {"case": "gated"}, observation["thread_id"])
    failure = list(values["failures"].values())[0]
    assert failure["failure_kind"] == "gate_refused"
    # The installed decision gate refuses a scope without a pinned contract and plan.
    assert failure["gate_errors"][0]["code"] == "gate_inputs_invalid"
    assert effect_ledger.receipts(tmp_path) == []


def test_a_body_returning_command_is_refused_and_routed_to_the_decision_turn(tmp_path):
    with fixtures():
        observation = gs.run(tmp_path, "t.misc", {"case": "command"})
        values = _values(tmp_path, "t.misc", {"case": "command"}, observation["thread_id"])
    assert observation["terminal"]["reason"] == "control_flow_refused"
    assert list(values["failures"].values())[0]["error_type"] == "ControlFlowRefused"


# ---- acceptance 9: version bump; framework step; acceptance 8: one runner per scope --------

def test_version_bump_keeps_call_ids_and_reuses_receipts_with_provisioning_drift(tmp_path, monkeypatch):
    instance = {"case": "version"}
    with fixtures(version=1):
        v1 = gs.run(tmp_path, "t.misc", instance)
    assert count(tmp_path, "version") == 1
    monkeypatch.setenv(ATLAS, "refreshed")
    with fixtures(version=2):
        v2 = gs.run(tmp_path, "t.misc", instance)
    assert v2["thread_id"] != v1["thread_id"] and v2["next"] == [] and count(tmp_path, "version") == 1
    assert [d["keys"] for d in v2["provisioning_drift"]] == [["atlas_sha256"]]
    assert v2["effects"]["completed"] == 1
    # An identity change with a declared version change (the receipt is v1, the graph v3): new attempt.
    monkeypatch.setenv(VARIANT, "b")
    with fixtures(version=3):
        changed = gs.run(tmp_path, "t.misc", instance)
    statuses = sorted(r["status"] for r in effect_ledger.receipts(tmp_path) if r["path"].endswith("/fixed:1"))
    assert changed["terminal"] is None and count(tmp_path, "version") == 2
    assert statuses == ["completed", "superseded"]
    # An identity change with no declared change (the receipt is now v3): held, not dispatched.
    monkeypatch.setenv(VARIANT, "c")
    with fixtures(version=3):
        undeclared = _fresh_thread_run(tmp_path, instance)
    assert undeclared["terminal"]["reason"] == "version_bump_required" and count(tmp_path, "version") == 2


def _fresh_thread_run(scope, instance):
    """Re-enter the same path on a new thread without a version change (a new instance digest is
    not allowed, so drop this thread's checkpoints)."""
    import sqlite3
    tid = gs.thread_id("t.misc", instance)
    with sqlite3.connect(Path(scope) / gs.DB) as db:
        for table in ("checkpoints", "writes"):
            db.execute(f"DELETE FROM {table} WHERE thread_id = ?", (tid,))
    return gs.run(scope, "t.misc", instance)


def test_every_receipt_links_its_framework_step(tmp_path):
    with fixtures():
        observation = gs.run(tmp_path, "t.effects", {"case": "plain"})
    for receipt in effect_ledger.receipts(tmp_path):
        step = receipt["framework_step"]
        assert step["thread_id"] == observation["thread_id"]
        assert step["task_id"] and step["checkpoint_id"] is not None and step["node_attempt"] == 1
        assert set(step["kernel_module_sha256"]) >= {"graph_substrate.py", "effect_ledger.py", "graph_nodes.py"}
        assert receipt["epoch"]["runner"] >= 1


def test_thread_id_binds_the_subgraph_closure_and_kernel_version_not_module_digests(tmp_path):
    with fixtures():
        base = gs.thread_id("t.parent", {"case": "x"})
        assert gs.closure("t.parent") == [["t.effects", 1], ["t.parent", 1]]
        assert set(gs.identity()) == {"kernel_version", "versions"}
    rows = [row(g, 2 if g == "t.effects" else 1, subgraphs=SUBGRAPHS.get(g, ())) for g in ROWS]
    for r in rows:
        if r["id"] == "t.parent":
            r["subgraphs"] = [{"id": "t.effects", "version": 2}]
    with graph_registry.registered(*rows, builders=ROWS):
        assert gs.thread_id("t.parent", {"case": "x"}) != base
    stale = [row(g, 2 if g == "t.effects" else 1, subgraphs=SUBGRAPHS.get(g, ())) for g in ROWS]
    with graph_registry.registered(*stale, builders=ROWS):
        with pytest.raises(ValueError, match="declares t.effects v1"):
            gs.thread_id("t.parent", {"case": "x"})


def test_one_runner_per_scope_refuses_a_second_runner_graph_and_child_entry(tmp_path):
    with fixtures():
        with gs.scope_runner(tmp_path, "t.misc", "f" * 64):
            for graph_id, instance in (("t.effects", {"case": "plain"}), ("t.misc", {"case": "boom"})):
                with pytest.raises(gs.ScopeLocked) as refused:
                    gs.run(tmp_path, graph_id, instance)
                assert refused.value.holder["graph_id"] == "t.misc" and refused.value.holder["pid"] == os.getpid()
                assert "ravel graph stop" in str(refused.value)
        assert count(tmp_path, "first") == 0
        observation = gs.run(tmp_path, "t.misc", {"case": "nested"})
        values = _values(tmp_path, "t.misc", {"case": "nested"}, observation["thread_id"])
    assert list(values["failures"].values())[0]["error_type"] == "ScopeLocked"
    assert count(tmp_path, "first") == 0
    assert effect_ledger.epoch(tmp_path)["runner"] == 2


def test_strict_msgpack_holds_whatever_the_import_order_and_environment_refuses_late_flags(tmp_path):
    """R4: with LangGraph imported before the variable is set, both flags stay false;
    ``environment()`` refuses, and the explicit saver still blocks a Pydantic value."""
    code = r"""
import os, sys, json
os.environ.pop("LANGGRAPH_STRICT_MSGPACK", None)
import langgraph.checkpoint.serde._msgpack as m
from langgraph._internal import _serde
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from ravel.workflow import graph_substrate as gs
class Card(BaseModel):
    name: str
try:
    gs.environment(); refused = False
except ValueError:
    refused = True
serde = gs.strict_serializer()
card = serde.loads_typed(serde.dumps_typed({"card": Card(name="x")}))["card"]
message = serde.loads_typed(serde.dumps_typed({"m": HumanMessage(content="hi")}))["m"]
print(json.dumps({"flags": [m.STRICT_MSGPACK_ENABLED, _serde.STRICT_MSGPACK_ENABLED], "refused": refused,
                  "card_type": type(card).__name__, "message_type": type(message).__name__}))
"""
    env = {k: v for k, v in os.environ.items() if k != "LANGGRAPH_STRICT_MSGPACK"}
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=env)
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result == {"flags": [False, False], "refused": True, "card_type": "dict", "message_type": "HumanMessage"}


def test_environment_is_strict_and_offline(tmp_path, monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "false")
    attempts = []
    def refuse(*args, **kwargs):
        attempts.append(args)
        raise OSError("network disabled in test")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    observation = gs.run(tmp_path, "substrate.selftest", {"label": "s", "steps": 2, "delay_ms": 0, "ask": False})
    assert os.environ["LANGSMITH_TRACING"] == "false" and os.environ["LANGCHAIN_TRACING_V2"] == "false"
    assert os.environ["LANGGRAPH_STRICT_MSGPACK"] == "true"
    serde = gs.strict_serializer()
    assert serde._allowed_msgpack_modules is None and serde.pickle_fallback is False
    assert observation["terminal"]["reason"] == "selftest_complete" and attempts == []


def test_non_json_safe_state_value_fails_the_state_lint(tmp_path):
    with fixtures():
        observation = gs.run(tmp_path, "t.misc", {"case": "unsafe"})
    assert observation["terminal"]["reason"] == "state_not_json_safe"
    assert graph_nodes.lint_state({"a": [1, "x", {"b": None}]}) == []
    assert graph_nodes.lint_state({"a": {1, 2}})


# ---- acceptance 13: redacted events; tripwire -------------------------------------------------

EVENT_KEYS = {"type", "ns", "graph_id", "thread_id", "task_id", "node", "keys_written", "value_sha256",
              "receipt_ids", "utc"}


def test_events_are_redacted_namespaced_lines(tmp_path):
    with fixtures():
        observation = gs.run(tmp_path, "t.parent", {"case": "x"})
    assert observation["next"] == []
    lines = gs.events(tmp_path)
    assert {"updates", "tasks"} <= {e["type"] for e in lines}
    assert all(set(e) == EVENT_KEYS for e in lines)
    assert any(e["ns"] and e["ns"][0].startswith("child:") for e in lines)
    assert any(e["receipt_ids"] for e in lines)
    text = (tmp_path / gs.EVENTS).read_text()
    assert '"done"' not in text and str(tmp_path) not in text
    assert count(tmp_path, "first") == 1
    child = [r for r in effect_ledger.receipts(tmp_path) if r["path"].endswith("/step:first")][0]
    assert child["path"].startswith("t.parent[") and "/node:child/t.effects[" in child["path"]
    assert child["graph"] == {"id": "t.effects", "version": 1}


def test_tripwire_is_set_only_inside_substrate_nodes(tmp_path):
    assert graph_nodes.TRIPWIRE.get() is None
    with fixtures():
        observation = gs.run(tmp_path, "t.misc", {"case": "tripwire"})
        values = _values(tmp_path, "t.misc", {"case": "tripwire"}, observation["thread_id"])
    assert values["seen"]["tripwire"]["ravel_kind"] == "effect" and values["seen"]["tripwire"]["node"] == "work"


# ---- acceptance 5 and 14: stop and drain ------------------------------------------------------

SELFTEST = {"label": "d", "steps": 6, "delay_ms": 300, "ask": False}


def _wait(predicate, timeout=60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _cleanup(scope):
    for entry in gs.processes(scope):
        if entry.get("state") == "running":
            gs._terminate(Path(scope), entry)


def test_stop_drains_no_new_dispatch_inflight_completes_status_stopped(tmp_path):
    try:
        detached = gs.run(tmp_path, "substrate.selftest", SELFTEST, detach=True)
        assert detached["detached"]["pgid"] == detached["detached"]["pid"]
        assert _wait(lambda: (tmp_path / "selftest" / "step-1.json").exists())
        held = gs.status(tmp_path)
        assert held["holder"]["graph_id"] == "substrate.selftest" and held["holder"]["pid"] == detached["detached"]["pid"]
        gs.stop(tmp_path, reason="synthetic drain")
        assert _wait(lambda: gs.processes(tmp_path)[0]["state"] == "exited")
        status = gs.status(tmp_path, "substrate.selftest", SELFTEST)
        assert status["state"] == "stopped" and status["terminal"]["status"] == "stopped"
        assert status["effects"]["started"] == 0 and status["effects"]["ambiguous"] == 0
        done = len(list((tmp_path / "selftest").glob("*.json")))
        assert 2 <= done < 6 and status["effects"]["completed"] == done
        time.sleep(1.0)
        assert len(list((tmp_path / "selftest").glob("*.json"))) == done
        refused = gs.run(tmp_path, "substrate.selftest", SELFTEST)
        assert refused["terminal"]["status"] == "stopped"
        resumed = gs.run(tmp_path, "substrate.selftest", SELFTEST, clear_stop=True)
        assert resumed["terminal"]["reason"] == "selftest_complete"
        assert resumed["effects"] == {"completed": 6, **NONE_OPEN}
    finally:
        _cleanup(tmp_path)


def test_guard_seeing_the_stop_file_drains_and_stays_resumable(tmp_path, monkeypatch):
    monkeypatch.setattr(gs, "STOP_POLL_SECONDS", 3600.0)  # only the guard can notice the stop
    with fixtures():
        stopped = gs.run(tmp_path, "t.misc", {"case": "stopmid"})
        assert stopped["terminal"]["status"] == "stopped" and stopped["next"]
        resumed = gs.run(tmp_path, "t.misc", {"case": "stopmid"}, clear_stop=True)
    assert resumed["terminal"]["reason"] == "stopmid_complete"


def test_stop_now_terminates_only_registered_groups_raises_the_cancellation_epoch_and_reconciles(tmp_path):
    bystander = subprocess.Popen(["/bin/sleep", "30"], start_new_session=True)
    slow = {"label": "n", "steps": 2, "delay_ms": 20000, "ask": False}
    try:
        gs.run(tmp_path, "substrate.selftest", slow, detach=True)
        assert _wait(lambda: effect_ledger.counts(tmp_path)["started"] == 1)
        result = gs.stop(tmp_path, reason="synthetic stop now", now=True)
        assert result["all_gone"] and [t["signal"] for t in result["terminated"]] == ["SIGKILL"]
        assert result["cancellation_epoch"] == 1 and effect_ledger.epoch(tmp_path)["cancellation"] == 1
        assert gs.processes(tmp_path)[0]["state"] == "terminated"
        assert bystander.poll() is None
        original = gs.run(tmp_path, "substrate.selftest", slow, clear_stop=True)
        assert [i["kind"] for i in original["interrupts"]] == ["reconcile_evidence"]
        assert original["effects"]["started"] == 1 and not (tmp_path / "selftest" / "step-0.json").exists()
    finally:
        bystander.kill()
        bystander.wait()
        _cleanup(tmp_path)


# ---- acceptance 11: registry and build refusals; handoff routing; gates ------------------

def test_registry_rows_validate_and_build_with_g8_metadata_and_their_structure_digest(tmp_path):
    rows = graph_registry.load()
    assert any(r["id"] == "substrate.selftest" for r in rows)
    for r in rows:
        assert callable(graph_registry.builder(r))
    for ask in (True, False):
        ctx = gs._context(tmp_path, "substrate.selftest", {"label": "x", "steps": 1, "delay_ms": 0, "ask": ask})
        compiled = gs.build("substrate.selftest", ctx)
        assert gs.lint_graph(compiled) == []
        assert compiled.structure_sha256 == graph_registry.get("substrate.selftest")["structure_sha256"]
    for schema_id in ("checkin1_response", "checkin2_response", "checkin3_response", "external_delivery",
                      "proposer_answers", "reconcile_evidence", "requirement_clarification", "host_waiver"):
        assert graph_registry.response_schema(schema_id)["type"] == "object"
    with pytest.raises(graph_registry.RegistryError):
        with graph_registry.registered({**row("t.bad"), "version": 0}):
            pass


def _bare(graph_id="t.x", *, standard_nodes=True):
    from langgraph.graph import START
    builder = _builder()
    graph_nodes.add(builder, "work", graph_nodes.Node("effect", lambda s: {}), graph_id=graph_id)
    builder.add_edge(START, "work")
    if standard_nodes:
        standard(builder, graph_id)
    return builder


def test_build_refuses_each_nonconforming_structure():
    from langgraph.graph import END, START
    builder = _bare()
    builder.add_node("raw", lambda s: {})
    with pytest.raises(ValueError, match="substrate node factory"):
        gs.finish(builder, "t.x")
    builder = _bare()
    builder.add_conditional_edges("work", lambda s: "hold", {"hold": "hold"})
    with pytest.raises(ValueError, match="not made by route or map_node"):
        gs.finish(builder, "t.x")
    builder = _bare()
    raw = graph_nodes._edge_function(graph_nodes.Edge(lambda s: "hold", {"hold": "hold"}), {"hold": "hold"})
    builder.add_conditional_edges("work", raw)
    with pytest.raises(ValueError, match="no path_map"):
        gs.finish(builder, "t.x")
    with pytest.raises(ValueError, match="non-empty path_map"):
        graph_nodes.route(lambda s: "x", {})
    with pytest.raises(ValueError, match="needs its own decision_turn"):
        gs.finish(_bare(standard_nodes=False), "t.x")
    builder = _bare()
    builder.add_node("own", lambda s: {}, metadata={"ravel_kind": "effect", "graph_id": "t.x"},
                     error_handler=lambda s, e: {})
    with pytest.raises(ValueError, match="own error handler"):
        gs.finish(builder, "t.x")
    with pytest.raises(ValueError, match="builder's own"):
        graph_nodes.add(_bare(), "h", graph_nodes.Node("effect", lambda s: {}, options={"error_handler": print}),
                        graph_id="t.x")
    builder = _bare()
    graph_nodes.add(builder, "ask", graph_nodes.interrupt("host_waiver", {}), graph_id="t.x")
    graph_nodes.add(builder, "after", graph_nodes.hold("x"), graph_id="t.x")
    builder.add_edge("ask", "after")
    with pytest.raises(ValueError, match="followed by a gate"):
        gs.finish(builder, "t.x")
    builder = _bare()
    graph_nodes.add(builder, "dangling", graph_nodes.interrupt("host_waiver", {}), graph_id="t.x")
    with pytest.raises(ValueError, match="followed by a gate"):
        gs.finish(builder, "t.x")
    with pytest.raises(ValueError, match="differs from the registry row"):
        gs.finish(_bare(), "t.x", expected_structure="0" * 64)


def test_consequential_sink_seed_list_names_existing_callables_and_declared_gates():
    from importlib import import_module
    document = json.loads((Path(gs.__file__).parents[1] / "data" / "graphs" / "consequential_sinks.json").read_text())
    assert document["kind"] == "consequential-sinks" and document["sinks"]
    for sink in document["sinks"]:
        assert {"sink", "gates", "action_digest_of"} <= set(sink) <= {"sink", "gates", "action_digest_of", "broker_actions"}
        assert sink["gates"] and all(type(a) is str and a for a in sink.get("broker_actions", []))
        module, qualname = sink["sink"].split(":")
        target = import_module(module)
        for part in qualname.split("."):
            target = getattr(target, part)
        assert callable(target)


def test_routes_refuse_keys_outside_the_path_map_and_send_outside_map_node():
    from langgraph.types import Send
    edge = graph_nodes.route(lambda s: s["to"], {"a": "a"})
    decide = graph_nodes._edge_function(edge, edge.path_map)
    assert decide({"to": "a"}) == "a"
    with pytest.raises(graph_nodes.ControlFlowRefused, match="not in the declared path_map"):
        decide({"to": "b"})
    with pytest.raises(graph_nodes.ControlFlowRefused, match="only map_node"):
        decide({"to": Send("a", {})})
    with pytest.raises(graph_nodes.ControlFlowRefused, match="only map_node"):
        decide({"to": [Send("a", {})]})


def test_error_handler_goto_is_confined_to_its_builder():
    with pytest.raises(ValueError, match="needs its own"):
        graph_nodes.error_handler({"work", "decision_turn", "hold"})
    from langgraph.errors import NodeError
    handler = graph_nodes.error_handler({"work", "decision_turn", "reconcile", "hold"})
    routed = handler({"failures": {}}, NodeError(node="work", error=KeyError("x")))
    assert routed.goto == "decision_turn"
    assert {graph_nodes.error_handler({"decision_turn", "reconcile", "hold"})(
        {"failures": {}}, NodeError(node="n", error=e)).goto for e in (
            KeyError("x"), effect_ledger.Ambiguous("a", "0" * 64), graph_nodes.RecoveryHold("r"))} <= set(
        graph_nodes.REQUIRED_NODES)


def test_handoff_is_a_final_record_field_routed_by_the_parent_path_map():
    """R1: no Command.PARENT; the handing-off role's record exists before the parent routes."""
    edge = graph_nodes.handoff("agent", ["role_b"], none="next", refuse="decision_turn")
    decide = graph_nodes._edge_function(edge, edge.path_map)
    record = lambda handoff: {"results": {"agent": {"outcome": "ok", "handoff": handoff}}}
    assert decide(record({"role": "role_b", "reason": "synthetic"})) == "role_b"
    assert edge.path_map["role_b"] == "role_b"
    assert edge.path_map[decide(record({"role": "unregistered", "reason": "x"}))] == "decision_turn"
    assert edge.path_map[decide(record(None))] == "next"


def test_gate_requires_declared_gates_and_active_required_providers(tmp_path):
    node = graph_nodes.gate("launch", lambda s: {"kind": "launch", "digest": "a" * 64})
    gates = {"launch": {"required_providers": ["review_points", "ceilings"]}}
    state = {"meta": {"graph_id": "t.gated", "version": 1, "instance": {}, "scope_root": str(tmp_path)}}
    with graph_registry.registered({**row("t.gated"), "gates": gates}, builders={"t.gated": misc_graph}):
        verdict = node.function(state)["gates"]["launch"]
        codes = [e["code"] for e in verdict["errors"]]
        assert verdict["action_digest"] == "a" * 64
        # The installed decision gate refuses the contract-less scope; both providers are active.
        assert codes == ["gate_inputs_invalid"]
        with graph_nodes.gate_checker(lambda root, gate, action: [], providers=lambda gate: {"review_points": True}):
            partial = node.function(state)
        assert [e["provider"] for e in partial["gates"]["launch"]["errors"]] == ["ceilings"]
        with graph_nodes.gate_checker(lambda root, gate, action: [],
                                      providers=lambda gate: {"review_points": True, "ceilings": True}):
            passed = node.function(state)
        assert graph_nodes.gate_passed("launch")(passed) == "pass"
        other = graph_nodes.gate("undeclared", lambda s: {"kind": "x", "digest": "b" * 64})
        with graph_nodes.gate_checker(lambda root, gate, action: [], providers=lambda gate: {}):
            refused = other.function(state)["gates"]["undeclared"]["errors"]
        assert [e["code"] for e in refused] == ["gate_not_declared"]
    assert graph_nodes.gate_passed("launch")({"gates": {}}) == "refuse"


def test_gate_reads_decision_gate_provider_rows(tmp_path):
    # decision_gate.providers returns registry rows; an inactive row is not an active provider.
    node = graph_nodes.gate("launch", lambda s: {"kind": "launch", "digest": "a" * 64})
    gates = {"launch": {"required_providers": ["review_points", "ceilings"]}}
    state = {"meta": {"graph_id": "t.gated", "version": 1, "instance": {}, "scope_root": str(tmp_path)}}
    rows = [{"id": "review_points", "active": True}, {"id": "ceilings", "active": False}]
    with graph_registry.registered({**row("t.gated"), "gates": gates}, builders={"t.gated": misc_graph}):
        with graph_nodes.gate_checker(lambda root, gate, action: [], providers=lambda gate: rows):
            errors = node.function(state)["gates"]["launch"]["errors"]
    assert [(e["code"], e["provider"]) for e in errors] == [("provider_inactive", "ceilings")]


def test_gate_errors_from_decision_gate_are_json_state():
    from ravel.workflow import decision_gate
    error = decision_gate.GateError("c", "launch", "p", "m", "f", ("inputs:x",))
    plain = graph_nodes._plain(error)
    assert plain["pins"] == ["inputs:x"] and json.loads(json.dumps(plain)) == plain


def test_compile_spec_builds_dependency_edges_with_substrate_nodes(tmp_path):
    from langgraph.checkpoint.memory import InMemorySaver
    def node(i, deps):
        return {"id": i, "kind": "tool", "role": "executor", "depends_on": deps, "inputs": [], "packet": None,
                "action": "synthetic", "parameters": {}, "max_attempts": 1}
    spec = {"schema_version": 1, "graph_id": "spec-fixture", "nodes": [node("one", []), node("two", ["one"])],
            "budget": {"max_nodes": 4, "max_calls": 4, "max_output_tokens": 0, "max_wall_seconds": 60, "max_reworks": 0}}
    order = []
    ctx = gs.BuildContext(scope_root=tmp_path, graph_id="x", version=0, instance={},
                          node_runner=lambda node_id, host: order.append(node_id) or {"ref": node_id})
    ctx.checkpointer = InMemorySaver()
    app = gs.compile_spec(spec, None, ctx)
    assert gs.lint_graph(app) == []
    final = app.invoke({"meta": {"graph_id": "agent_graph:spec-fixture", "version": 0, "instance": {},
                                 "scope_root": str(tmp_path)}}, {"configurable": {"thread_id": "t"}})
    assert order == ["one", "two"] and final["completed"] == {"one": {"ref": "one"}, "two": {"ref": "two"}}


def test_ravel_graph_cli_is_registered_and_lists_graphs(capsys):
    from ravel import cli
    assert cli.FOCUSED_COMMANDS["graph"][0] == "workflow.graph_substrate"
    assert cli.main(["graph", "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert "substrate.selftest" in {g["id"] for g in listed["graphs"]}


def test_cli_run_status_respond_and_events(tmp_path, capsys):
    instance = json.dumps({"label": "c", "steps": 1, "delay_ms": 0, "ask": True})
    base = ["--scope-root", str(tmp_path), "--graph", "substrate.selftest", "--instance", instance]
    assert gs.main(["run", *base]) == 0
    observation = json.loads(capsys.readouterr().out)
    (pending,) = observation["interrupts"]
    assert gs.main(["respond", *base, "--responses", json.dumps({pending["id"]: {"answer": 7}})]) == 2
    assert "refused before resume" in capsys.readouterr().err
    assert gs.main(["respond", *base, "--responses", json.dumps({pending["id"]: {"answer": "synthetic"}})]) == 0
    # The answer is data: the routed gate still refuses the contract-less scope.
    assert json.loads(capsys.readouterr().out)["terminal"]["reason"] == "selftest_gate_refused"
    assert gs.main(["status", *base]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "hold"
    assert gs.main(["events", "--scope-root", str(tmp_path), "--type", "updates"]) == 0
    assert all(json.loads(line)["type"] == "updates" for line in capsys.readouterr().out.splitlines())
    assert gs.main(["status", "--scope-root", str(tmp_path)]) == 0
    assert len(json.loads(capsys.readouterr().out)["threads"]) == 1


# ---- environment at import, bound reconciliation, gates channel, stop --now ------------

SRC = Path(gs.__file__).resolve().parents[2]


@pytest.mark.parametrize("entry", ["ravel.workflow.langgraph_runtime", "ravel.workflow.graph_substrate",
                                   "ravel.workflow.effect_ledger", "ravel.workflow.graph_nodes",
                                   "ravel.workflow.graph_registry"])
def test_importing_a_kernel_entry_point_sets_strict_msgpack_before_langgraph_in_a_plain_process(tmp_path, entry):
    """No conftest, no variable: the entry point itself sets the environment."""
    code = (f"import importlib, json, os, sys\nimportlib.import_module({entry!r})\n"
            "import langgraph.graph\n"
            "from langgraph.checkpoint.serde import _msgpack\nfrom langgraph._internal import _serde\n"
            "from ravel.workflow import graph_substrate\ngraph_substrate.environment()\n"
            "print(json.dumps([_msgpack.STRICT_MSGPACK_ENABLED, _serde.STRICT_MSGPACK_ENABLED,\n"
            "                  os.environ['LANGSMITH_TRACING'], os.environ['LANGCHAIN_TRACING_V2']]))")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LANGGRAPH_", "LANGSMITH_", "LANGCHAIN_"))}
    env.update(PYTHONPATH=str(SRC), LANGSMITH_TRACING="true")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, env=env,
                          cwd=tmp_path)
    assert done.returncode == 0, done.stderr[-3000:]
    assert json.loads(done.stdout.strip().splitlines()[-1]) == [True, True, "false", "false"]


def test_the_ravel_graph_cli_runs_in_a_plain_process_without_the_variable(tmp_path):
    code = ("import sys\nfrom ravel import cli\n"
            "sys.exit(cli.main(['graph', 'run', '--scope-root', sys.argv[1], '--graph', 'substrate.selftest',\n"
            "                   '--instance', '{\"label\": \"p\", \"steps\": 1, \"delay_ms\": 0, \"ask\": false}']))")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LANGGRAPH_", "LANGSMITH_", "LANGCHAIN_"))}
    env.update(PYTHONPATH=str(SRC))
    done = subprocess.run([sys.executable, "-c", code, str(tmp_path / "scope")], capture_output=True, text=True,
                          timeout=120, env=env, cwd=tmp_path)
    assert done.returncode == 0, done.stderr[-3000:]
    assert json.loads(done.stdout)["terminal"]["reason"] == "selftest_complete"


class _Crash(BaseException):
    pass


def _open_effect(scope, label):
    """A started effect at another path of the same scope (its process died)."""
    where = effect_ledger.path("t.other", {"case": "x"}, None, {"step": label})
    with pytest.raises(_Crash):
        effect_ledger.call(scope, graph={"id": "t.other", "version": 1}, path=where, kind="model",
                           identity={"step": label}, provisioning={}, function=lambda: (_ for _ in ()).throw(_Crash()))
    return effect_ledger.latest(scope, where)["call_id"]


def _pending_reconcile(tmp_path):
    run_crashing(tmp_path, "t.effects", {"case": "plain"}, "inside:second")
    observation = gs.run(tmp_path, "t.effects", {"case": "plain"})
    (pending,) = observation["interrupts"]
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"observed": "synthetic"}')
    pin = {"path": "evidence.json", "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}
    return pending, pin


def test_a_reconcile_response_may_close_only_the_effect_its_interrupt_names(tmp_path):
    with fixtures():
        pending, pin = _pending_reconcile(tmp_path)
        other = _open_effect(tmp_path, "unrelated")
        with pytest.raises(ValueError, match="names a different effect"):
            gs.respond(tmp_path, "t.effects", {"case": "plain"}, {pending["id"]: {
                "call_id": other, "outcome": "completed", "evidence": [pin], "reason": "synthetic",
                "result": {"forged": True}}})
    assert effect_ledger.read(tmp_path, other)["status"] == "started"
    assert effect_ledger.read(tmp_path, pending["payload"]["payload"]["call_id"])["status"] == "started"


def test_a_reconcile_response_is_applied_only_inside_the_scope_lock(tmp_path):
    with fixtures():
        pending, pin = _pending_reconcile(tmp_path)
        identifier = pending["payload"]["payload"]["call_id"]
        code = ("import sys, time; sys.path.insert(0, sys.argv[2])\n"
                "from ravel.workflow.state_io import file_lock\n"
                "with file_lock(sys.argv[1], blocking=False):\n"
                "    print('held', flush=True); time.sleep(60)")
        holder = subprocess.Popen([sys.executable, "-c", code, str(tmp_path / gs.SCOPE_LOCK), str(SRC)],
                                  stdout=subprocess.PIPE, text=True)
        try:
            assert holder.stdout.readline().strip() == "held"
            with pytest.raises(gs.ScopeLocked):
                gs.respond(tmp_path, "t.effects", {"case": "plain"}, {pending["id"]: {
                    "call_id": identifier, "outcome": "completed", "evidence": [pin], "reason": "synthetic",
                    "result": {"done": "second"}}})
            assert effect_ledger.read(tmp_path, identifier)["status"] == "started"
        finally:
            holder.terminate()
            holder.wait(30)


def test_respond_refuses_while_the_scope_is_stopped_unless_the_stop_is_cleared(tmp_path):
    with fixtures():
        pending, pin = _pending_reconcile(tmp_path)
        identifier = pending["payload"]["payload"]["call_id"]
        answer = {pending["id"]: {"call_id": identifier, "outcome": "completed", "evidence": [pin],
                                  "reason": "synthetic", "result": {"done": "second"}}}
        gs.stop(tmp_path, reason="synthetic drain")
        with pytest.raises(ValueError, match="stopped"):
            gs.respond(tmp_path, "t.effects", {"case": "plain"}, answer)
        assert effect_ledger.read(tmp_path, identifier)["status"] == "started"
        done = gs.respond(tmp_path, "t.effects", {"case": "plain"}, answer, clear_stop=True)
    assert done["next"] == [] and done["interrupts"] == []


def test_only_gate_nodes_write_the_gates_channel(tmp_path):
    with fixtures():
        observation = gs.run(tmp_path, "t.misc", {"case": "forge"})
        values = _values(tmp_path, "t.misc", {"case": "forge"}, observation["thread_id"])
        assert observation["terminal"]["reason"] == "control_flow_refused"
        assert "gates" in list(values["failures"].values())[0]["message"]
        assert not (values.get("gates") or {})
        with pytest.raises(ValueError, match="framework channel"):
            gs.run(tmp_path / "input", "t.misc", {"case": "plain"},
                   input={"gates": {"launch": {"errors": [], "sequence": 1}}})


def test_map_and_subgraph_packets_cannot_carry_framework_channels(tmp_path):
    with fixtures():
        child = gs.BuildContext(scope_root=tmp_path, graph_id="t.branch", version=1, instance={"case": "x"})
        target = gs.build("t.branch", child)
        edge, _ = graph_nodes.map_node(lambda s: [1], str, target,
                                       lambda s, i: {"n": 1, "gates": {"approve_plan": {"errors": []}}}, name="b")
        state = {"meta": {"graph_id": "t.ask", "version": 1, "instance": {"case": "x"},
                          "scope_root": str(tmp_path), "path": None}}
        with pytest.raises(ValueError, match="framework channel"):
            edge.router(state)


def test_every_gate_exits_through_its_own_gate_route():
    builder = _bare()
    graph_nodes.add(builder, "check", graph_nodes.gate("launch", lambda s: {"digest": "0" * 64}), graph_id="t.x")
    builder.add_edge("work", "check")
    builder.add_edge("check", "hold")
    with pytest.raises(ValueError, match="gate node 'check' must exit through"):
        gs.finish(builder, "t.x")
    builder = _bare()
    graph_nodes.add(builder, "check", graph_nodes.gate("launch", lambda s: {"digest": "0" * 64}), graph_id="t.x")
    builder.add_edge("work", "check")
    graph_nodes.connect(builder, "check", graph_nodes.gate_route("other", passed="hold", refused="hold"))
    with pytest.raises(ValueError, match="gate node 'check' must exit through"):
        gs.finish(builder, "t.x")
    builder = _bare()
    graph_nodes.add(builder, "check", graph_nodes.gate("launch", lambda s: {"digest": "0" * 64}), graph_id="t.x")
    builder.add_edge("work", "check")
    graph_nodes.connect(builder, "check", graph_nodes.gate_route("launch", passed="hold", refused="decision_turn"))
    gs.finish(builder, "t.x")


def test_a_gated_effect_binds_its_gate_to_the_bytes_it_acts_on(tmp_path):
    seen = []

    def record(scope_root, gate, action):
        seen.append(action["digest"])
        return [{"code": "approval_missing", "gate": gate, "provider": "fixture", "message": "no approval",
                 "fix": "approve", "pins": []}]
    with fixtures():
        gs.run(tmp_path, "t.misc", {"case": "gated"}, gate_check=record)
        unbound = gs.run(tmp_path, "t.misc", {"case": "gated_unbound"}, gate_check=record)
        values = _values(tmp_path, "t.misc", {"case": "gated_unbound"}, unbound["thread_id"])
    assert seen == [hashlib.sha256(b"synthetic launch argv").hexdigest()]
    assert "action_bytes_sha256" in list(values["failures"].values())[0]["message"]
    assert effect_ledger.receipts(tmp_path) == []


def test_stop_now_also_terminates_and_verifies_a_registered_child_group(tmp_path):
    loop = ["-c", "import time\nwhile True: time.sleep(1)"]
    supervisor = subprocess.Popen([sys.executable, *loop], start_new_session=True)
    child = subprocess.Popen([sys.executable, *loop], start_new_session=True)
    try:
        gs._register_process(tmp_path, {"id": "worker-supervisor", "pid": supervisor.pid, "pgid": supervisor.pid,
                                        "child_pid": child.pid, "child_pgid": child.pid, "role": "worker-supervisor",
                                        "state": "running"})
        result = gs.stop(tmp_path, reason="synthetic stop now", now=True)
        (terminated,) = result["terminated"]
        assert terminated["child_pgid"] == child.pid and terminated["gone"] and result["all_gone"]
        assert child.wait(10) is not None and supervisor.wait(10) is not None
    finally:
        for process in (supervisor, child):
            if process.poll() is None:
                process.kill()
                process.wait()


def test_shared_role_dispatch_preserves_arguments_result_and_failure(monkeypatch, tmp_path):
    from ravel.workflow import graph_substrate as gs, research_cycle
    calls = []
    result = {"complete": False, "nodes": {"synthetic": {"status": "pending"}}}
    host = object()
    spec = {"graph_id": "synthetic", "nodes": []}

    def execute(*args, **kwargs):
        calls.append((args, kwargs))
        return result

    monkeypatch.setattr(research_cycle, "execute_graph", execute)
    assert gs.execute_role_graph(tmp_path, tmp_path / "graph", spec, host,
                                 prepared=True, workers=2) is result
    assert calls == [((tmp_path, tmp_path / "graph", spec, host), {"prepared": True, "workers": 2})]
    failure = RuntimeError("synthetic dispatch failure")

    def refuse(*args, **kwargs):
        raise failure

    monkeypatch.setattr(research_cycle, "execute_graph", refuse)
    with pytest.raises(RuntimeError) as caught:
        gs.execute_role_graph(tmp_path, tmp_path / "graph", spec, host, prepared=False, workers=1)
    assert caught.value is failure


def test_shared_legacy_pause_preserves_payload_and_discards_resume_value(monkeypatch):
    from langgraph import types
    from ravel.workflow import graph_substrate as gs
    calls = []
    payload = {"kind": "synthetic_delivery", "execution_authorized": False}
    monkeypatch.setattr(types, "interrupt", lambda value: calls.append(value) or {"resume": "data"})
    assert gs.legacy_pause(payload) is None
    assert calls == [payload] and calls[0] is payload
