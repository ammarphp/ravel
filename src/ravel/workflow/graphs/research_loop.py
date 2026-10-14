"""``research.loop``: the open-research coordinator on the graph substrate.

The node table is ``research_orchestrator._open_plan``'s, shared with the legacy state
machine, so both engines dispatch the same roles and leave equal receipts (dual-run
parity). On the substrate:

- every node is a ledgered effect at ``node:<name>/state:<sha>``: a re-entered node with an
  unchanged state returns its receipt, and nothing is dispatched twice;
- a ``protocol-stage`` action runs the ``research.stage`` subgraph, whose result is committed
  as that turn's coordinator effect exactly as the legacy ``run_protocol_stage`` effect;
- a wait for an ordinary outside effect (host delivery, approval, a stage run) is a typed
  ``external_delivery`` turn followed by the ``research_choice`` gate, then the waiting node
  re-enters; the legacy engine's dead-end interrupts are gone;
- a failed action, stage or refused dispatch becomes an observation committed for the
  next decision turn (OD M14); any other failure ends in a typed status, never an abort;
- ``ravel graph stop`` drains at a superstep boundary and ``ravel research-orchestrate run``
  continues (R-56 parts 1-2).
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import threading
from typing import Annotated, TypedDict

from .. import effect_ledger, graph_nodes
from ..agent_graph import GraphError
from . import DeliveryRequired, ServiceRefused, host, pause, service, stage

GRAPH_ID = "research.loop"
KINDS = {"declare_call": "model", "assessment_call": "model", "decision_call": "model",
         "idea_call": "worker", "action_effect": "worker"}
MAX_ATTEMPTS = 64
# Failures at these nodes are the outcome of a chosen action: the next decision turn sees them.
ACTION_NODES = ("action_effect", "stage", "stage_commit")
RECORDED_KINDS = ("exception", "transport_refusal", "gate_refused", "ceiling_exceeded")
PRIVATE = set(graph_nodes.FRAMEWORK_CHANNELS) | {"results", "status", "remaining_steps", "loop", "stage_run"}

_PLANS: dict = {}
_PLANS_LOCK = threading.Lock()


class StageFailed(GraphError):
    """The stage subgraph ended in a failed outcome; its status is the observation."""


def _view(state):
    return {k: v for k, v in state.items() if k not in PRIVATE}


def plan(state):
    """The shared node table for this run (cached per request, output and host)."""
    from .. import research_orchestrator as orchestrator
    loop = state["loop"]
    key = (state["meta"]["scope_root"], loop["request"]["sha256"], loop["out"], loop["host"])
    with _PLANS_LOCK:
        found = _PLANS.get(key)
    if found is None:
        found = service(lambda: orchestrator._open_plan(state["meta"]["scope_root"], loop["request"], loop["out"],
                                                        host=host(loop["host"]), pause=pause,
                                                        stage_runner=_stage_runner_refused))
        if found["operation"] != loop["operation"]:
            raise ServiceRefused(ValueError("research operation differs from the run's binding"))
        with _PLANS_LOCK:
            _PLANS[key] = found
    _current(found["operation"])
    return found


def forget_plans():
    with _PLANS_LOCK:
        _PLANS.clear()


def _stage_runner_refused(*args, **kwargs):
    raise ValueError("protocol stages run through the research.stage subgraph on this engine")


def _current(operation):
    """As the legacy engine: the request and every bound service source are unchanged."""
    from .. import research_orchestrator as orchestrator
    if orchestrator._pin(operation["path"]) != operation:
        raise ServiceRefused(ValueError("research checkpoint/request changed before domain effect"))
    for pin in orchestrator._read(operation)["source_pins"]:
        if orchestrator._pin(pin["path"]) != pin:
            raise ServiceRefused(ValueError("research service source changed before domain effect"))


def _segment(name):
    return lambda s: {"node": name, "state": effect_ledger.digest(_view(s))}


def _identity(name):
    return lambda s: {"node": name, "operation_sha256": s["loop"]["operation"]["sha256"],
                      "state_sha256": effect_ledger.digest(_view(s))}


def _open_node(name):
    def run(state, identity):
        found = plan(state)
        view = _view(state)
        update = service(lambda: found["nodes"][name](view))
        _current(found["operation"])
        return json.loads(json.dumps(update or {}, allow_nan=False))
    return graph_nodes.effect("research.open." + name, kind=KINDS.get(name, "journal"), run=run,
                              segment=_segment(name), identity=_identity(name), max_attempts=MAX_ATTEMPTS,
                              to_state=lambda s, r: r)


# ---- protocol stages ----------------------------------------------------------------------------

def _turn_dest(found, state):
    return Path(found["out"]) / "turns" / str(state["turn"]) / "effect"


def _origin_checked(found, state):
    """The action effect's own checks: the routing checkpoint equals the actual model action."""
    from .. import research_cycle as cycle
    from ..agent_host import _loads
    found["validate"](_view(state))
    origin = cycle._graph_result(state["origin"]["root"], state["origin"]["node_id"])
    public = origin["value"].get("value", {})
    if (origin != state["origin"] or public.get("kind") != "research-action"
            or public.get("action") != state["action"] or _loads(public["arguments_json"]) != state["arguments"]):
        raise ValueError("routing checkpoint differs from actual source-bound model action")
    return origin


def _stage_body(ctx):
    from .. import graph_substrate
    compiled = graph_substrate.build(stage.GRAPH_ID, graph_substrate.BuildContext(
        scope_root=ctx.scope_root, graph_id=stage.GRAPH_ID, version=_row(stage.GRAPH_ID)["version"],
        instance=deepcopy(ctx.instance)), checkpointer=None)

    def body(state):
        from .. import research_cycle as cycle
        found = plan(state)
        meta = state["meta"]

        def checked():
            origin = _origin_checked(found, state)
            cycle.ce.keys(state["arguments"], {"artifact"})
            _, campaign = cycle._load(meta["scope_root"])
            return cycle._coordinator_effect(campaign, origin)
        committed = service(checked)
        if committed is not None:
            return {"stage_run": {"turn": state["turn"], "committed": True}}
        dest = _turn_dest(found, state)
        request = stage.request(artifact=state["arguments"]["artifact"], out=dest / "protocol",
                                settings=found["value"]["runtime"], host_key=state["loop"]["host"],
                                operation_sha256=state["loop"]["operation"]["sha256"])
        child_meta = {"graph_id": stage.GRAPH_ID, "version": _row(stage.GRAPH_ID)["version"],
                      "instance": deepcopy(meta.get("instance")), "scope_root": meta["scope_root"],
                      "path": graph_nodes.invocation(meta, {"stage": "turn-" + str(state["turn"])})}
        final = compiled.invoke({"stage_request": request, "meta": child_meta})
        status = (final or {}).get("status") or {}
        if status.get("terminal") in {"hold", "stopped"}:
            raise graph_nodes.RecoveryHold("stage_" + str(status.get("reason")), status.get("would_make_possible"))
        if status.get("terminal") is not None or "stage" not in ((final or {}).get("results") or {}):
            raise StageFailed(json.dumps({"stage_status": status, "failures": list(
                ((final or {}).get("failures") or {}).values())[-1:]}, sort_keys=True, default=str)[:1900])
        return {"stage_run": {"turn": state["turn"], "committed": False, "effect": final["results"]["stage"]}}
    body.__name__ = "stage"
    return graph_nodes.Node("subgraph", body)


def _commit(found, state, origin, effect):
    from .. import research_coordinator_decisions as decisions, research_cycle as cycle
    dest = _turn_dest(found, state)
    effect_pin = decisions._put(dest / "coordinator-effect.json", {
        "action": state["action"], "arguments": state["arguments"], "origin": state["origin"],
        "actual_effect": effect, "parent_task_accepted": False, "scientific_authority_from_checkpoint": False})
    cycle._record_coordinator_effect(state["meta"]["scope_root"], state["origin"], effect_pin)
    history = [*state.get("action_results", []), {"origin": state["origin"], "effect": effect_pin}]
    return {"action_results": history, "turn": state["turn"] + 1, "result": effect}


def _stage_commit(state, identity):
    from .. import research_cycle as cycle

    def run():
        found = plan(state)
        origin = _origin_checked(found, state)
        _, campaign = cycle._load(state["meta"]["scope_root"])
        committed = cycle._coordinator_effect(campaign, origin)
        if committed is not None:
            if committed["pin"]["path"] != str(_turn_dest(found, state) / "coordinator-effect.json"):
                raise ValueError("committed effect belongs to another original coordinator turn")
            return {"action_results": [*state.get("action_results", []), {"origin": origin, "effect": committed["pin"]}],
                    "turn": state["turn"] + 1, "result": committed["document"]["actual_effect"]}
        return _commit(found, state, origin, state["stage_run"]["effect"])
    return json.loads(json.dumps(service(run), allow_nan=False))


def _latest_failure(state):
    failures = state.get("failures") or {}
    if not failures:
        return None, None
    key = next(reversed(failures))
    return key, failures[key]


def _record_failure(state, identity):
    """Commit the failed action as this turn's observation; the next decision turn reads it."""
    def run():
        found = plan(state)
        origin = _origin_checked(found, state)
        key, failure = _latest_failure(state)
        effect = {"status": "action_failed", "action": state["action"], "failure_id": key,
                  "failure": {k: failure.get(k) for k in ("failure_kind", "node", "error_type", "message", "missing",
                                                           "gate_errors", "would_make_possible")},
                  "observation_not_falsification": True, "scientific_acceptance": False,
                  "execution_authorized": False}
        return _commit(found, state, origin, effect)
    return json.loads(json.dumps(service(run), allow_nan=False))


def _route_failure(state, failure):
    if failure["error_type"] == DeliveryRequired.__name__:
        return "await"
    if failure["node"] in ACTION_NODES and failure["failure_kind"] in RECORDED_KINDS:
        return "record"
    return "end"


def _delivery_payload(state):
    key, failure = _latest_failure(state)
    return {"kind": "research-ordinary-effect-required", "failure_id": key, "waiting_node": failure["node"],
            "request": failure["message"], "would_make_possible": failure.get("would_make_possible"),
            "approval_from_resume": False, "execution_authorized": False}


def _reenter(state):
    _, failure = _latest_failure(state)
    return failure["node"] if failure else "end"


def _row(graph_id):
    from .. import graph_registry
    return graph_registry.get(graph_id)


class LoopState(graph_nodes.BaseState, total=False):
    loop: dict
    stage_run: Annotated[dict, graph_nodes.last_value]


def build(ctx):
    from langgraph.graph import START, END, StateGraph
    from .. import research_orchestrator as orchestrator

    fields = {**LoopState.__annotations__,
              **{k: Annotated[v, graph_nodes.last_value] for k, v in orchestrator.ResearchState.__annotations__.items()
                 if k not in LoopState.__annotations__}}
    state = TypedDict("ResearchLoopState", fields, total=False)
    builder = StateGraph(state)
    add = lambda name, node: graph_nodes.add(builder, name, node, graph_id=ctx.graph_id)
    names = sorted({a for a, _ in orchestrator.OPEN_EDGES if a != "START"}
                   | {b for _, b in orchestrator.OPEN_EDGES if b != "END"}
                   | {name for name, _, _ in orchestrator.OPEN_CONDITIONAL}
                   | {t for _, _, targets in orchestrator.OPEN_CONDITIONAL for t in targets.values() if t != "END"})
    for name in names:
        add(name, _open_node(name))
    add("stage", _stage_body(ctx))
    add("stage_commit", graph_nodes.effect(
        "research.stage_commit", kind="journal", run=_stage_commit, segment=_segment("stage_commit"),
        identity=_identity("stage_commit"), max_attempts=MAX_ATTEMPTS, to_state=lambda s, r: r))
    add("record_failure", graph_nodes.effect(
        "research.record_failure", kind="journal", run=_record_failure, segment=_segment("record_failure"),
        identity=_identity("record_failure"), max_attempts=MAX_ATTEMPTS, to_state=lambda s, r: r))
    add("await_delivery", graph_nodes.interrupt(
        "external_delivery", _delivery_payload, segment=lambda s: {"await": _latest_failure(s)[0]}))
    add("delivered", graph_nodes.gate("research_choice", lambda s: {
        "kind": "research_ordinary_delivery", "summary": "ordinary outside effect delivered", "pins": [],
        "digest": effect_ledger.digest({"failure": _latest_failure(s)[0], "responses": s.get("responses") or {}})}))
    add("reenter", graph_nodes.Node("guard", lambda s: {"status": {
        "phase": "reenter", "verdict": "go", "terminal": None, "reason": _reenter(s), "would_make_possible": None}},
        then=graph_nodes.Edge(_reenter, "nodes")))
    add("refused", graph_nodes.hold("research_delivery_gate_refused",
                                    "the research_choice gate passes on the delivered effect"))
    add("decision_turn", graph_nodes.decision_turn(GRAPH_ID, _route_failure,
                                                   {"await": "await_delivery", "record": "record_failure"}))
    add("reconcile", graph_nodes.reconcile_node())
    add("hold", graph_nodes.hold("research_loop_hold"))
    for a, b in orchestrator.OPEN_EDGES:
        if (a, b) == ("selected_operation", "action_effect"):
            continue
        builder.add_edge(START if a == "START" else a, END if b == "END" else b)
    for name, router, targets in orchestrator.OPEN_CONDITIONAL:
        graph_nodes.connect(builder, name, graph_nodes.route(router, {k: END if v == "END" else v
                                                                      for k, v in targets.items()}))
    graph_nodes.connect(builder, "selected_operation", graph_nodes.route(
        lambda s: "stage" if s.get("action") == "protocol-stage" else "act",
        {"stage": "stage", "act": "action_effect"}))
    builder.add_edge("stage", "stage_commit")
    builder.add_edge("stage_commit", "decision_prepare")
    builder.add_edge("record_failure", "decision_prepare")
    builder.add_edge("await_delivery", "delivered")
    graph_nodes.connect(builder, "delivered", graph_nodes.gate_route("research_choice", passed="reenter",
                                                                     refused="refused"))
    return builder


def roles():
    from .. import research_protocol
    return sorted({r for row in research_protocol.default_protocol()["stages"] for r in row["roles"]})
