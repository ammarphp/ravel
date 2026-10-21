"""``research.stage``: one bound protocol stage on the graph substrate.

```
prepare (journal: role models, session independence, research_protocol.prepare_stage)
 ─► dispatch (worker: the stage's role Graph through research_cycle.execute_graph)
 ─► complete (journal: session independence on observed models, research_protocol.complete_stage) ─► END
      └ pending roles ─► deliver (external_delivery) ─► gate(research_choice) ─► dispatch
```

The stage writes exactly the files ``research_orchestrator.run_protocol_stage`` writes
(``preparation.json``, ``review/``, ``graph/``), so both engines leave equal receipts.
Role models come from the role cards' tiers (``research_coordinator_decisions.role_assignments``);
every role requires a distinct actor, session and packet at completion. Observed model
families are retained as descriptive labels and never veto a separate session.
Errors route to this builder's own decision turn: the parent sees a failed or held outcome.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Annotated, TypedDict

from .. import effect_ledger, graph_nodes
from . import host, service

GRAPH_ID = "research.stage"
SAME_MODEL = ("model", "reasoning_effort", "adapter")


class StageView(TypedDict, total=False):
    meta: dict
    stage_request: dict


def _request(state):
    return state["stage_request"]


def _root(state):
    return Path(_request(state).get("campaign_root") or state["meta"]["scope_root"])


def _responses(state):
    return len(state.get("responses") or {})


def _stage_identity(state):
    request = _request(state)
    return {"artifact": request["artifact"], "out": request["out"], "settings_sha256": effect_ledger.digest(
        request["settings"]), "operation_sha256": request["operation_sha256"]}


def assignments_for(stage_id, settings, *, root=None):
    """The stage roles' models, checked against the proposers they judge (which may belong to an earlier stage)."""
    from .. import research_coordinator_decisions as decisions, research_protocol
    stage = next(r for r in research_protocol.default_protocol()["stages"] if r["id"] == stage_id)
    if root is not None:
        assigned = decisions.role_assignments(settings, stage['roles'])
        checks = decisions.stage_family_check(root, stage_id,
                                              {role: row['model'] for role, row in assigned.items()})
        return {role: {**assigned[role], **checks[role]} for role in stage['roles']}
    proposers = [p for p in decisions.stage_proposers(stage_id) if p not in stage["roles"]]
    assigned = decisions.role_assignments(settings, [*stage["roles"], *proposers])
    checks = decisions.dispatch_check(stage_id, assigned)
    return {role: {**assigned[role], **checks[role]} for role in stage["roles"]}


def model_options(stage_id, settings, *, root=None):
    """``prepare_stage`` keyword arguments for the stage's assigned role models, and the assignments.

    Without per-role settings every role takes the single runtime, exactly as before.
    """
    assigned = assignments_for(stage_id, settings, root=root)
    common = {tuple(row[k] for k in SAME_MODEL) for row in assigned.values()}
    options = {"max_output_tokens": settings["max_output_tokens"], "max_wall_seconds": settings["max_wall_seconds"]}
    if len(common) == 1:
        model, effort, adapter = common.pop()
        options.update(model=model, reasoning_effort=effort, adapter=adapter)
    else:
        first = next(iter(assigned.values()))
        options.update(model=first["model"], reasoning_effort=first["reasoning_effort"], adapter=first["adapter"],
                       role_models={r: {k: row[k] for k in SAME_MODEL} for r, row in assigned.items()})
    return options, assigned


def _prepare(state, identity):
    from .. import research_coordinator_decisions as decisions, research_orchestrator as orchestrator
    from .. import research_protocol as protocol
    request, root = _request(state), _root(state)
    out, settings = Path(request["out"]), request["settings"]
    binding = out / "preparation.json"

    def run():
        if binding.exists():
            prepared = orchestrator._read(orchestrator._pin(binding))
            if prepared["artifact"] != request["artifact"]:
                raise orchestrator.RecoveryHold("research stage proposal changed; retain the original review "
                                                "and prepare a new one")
            return {"prepared": prepared, "assignments": assignments_for(prepared["stage"], settings, root=root)}
        stage = protocol.methodology_status(root)["next_stage"]
        if stage is None:
            raise ValueError("all bound research stages already complete")
        options, assigned = model_options(stage, settings, root=root)
        prepared = protocol.prepare_stage(root, stage, request["artifact"], out / "review", **options)
        decisions._put(binding, prepared)
        return {"prepared": prepared, "assignments": assigned}
    return service(run)


def _dispatch(state, identity):
    from .. import graph_substrate as substrate, research_orchestrator as orchestrator
    request, root = _request(state), _root(state)
    prepared = state["prepared"]
    graph_root = Path(request["out"]) / "graph"

    def run():
        spec = orchestrator._read(prepared["specification"])
        result = substrate.execute_role_graph(root, graph_root, spec, host(request["host"]),
                                              prepared=graph_root.exists(), workers=prepared["workers"])
        return {"complete": bool(result["complete"]), "graph": result}
    return service(run)


def _complete(state, identity):
    from .. import research_coordinator_decisions as decisions, research_protocol as protocol
    root, prepared = _root(state), state["prepared"]

    def run():
        current = protocol.methodology_status(root)
        if next(r for r in current["record"]["stages"] if r["id"] == prepared["stage"])["status"] == "done":
            return {"complete": True, "methodology": current, "scientific_acceptance": False}
        graph_root = Path(_request(state)["out"]) / "graph"
        # Verify actual actor, session and packet separation before credit.
        decisions.receipt_family_check(prepared["stage"], graph_root, _request(state)["settings"], root=root)
        completed = protocol.complete_stage(root, prepared, graph_root)
        return {"complete": True, "methodology": completed, "scientific_acceptance": False}
    return service(run)


def _pending(state):
    graph = (state.get("dispatch") or {}).get("graph") or {}
    return {"kind": "research-stage-delivery-required", "stage": state["prepared"]["stage"], "complete": False,
            "graph_root": str(Path(_request(state)["out"]) / "graph"),
            "pending": sorted(n for n, row in (graph.get("nodes") or {}).items()
                              if type(row) is dict and row.get("status") != "completed"),
            "execution_authorized": False}


def _delivered_action(state):
    """The exact recorded role delivery, pinned for the ordinary resume decision."""
    from .. import research_orchestrator as orchestrator
    responses = state.get("responses") or {}
    if not responses:
        raise ValueError("stage delivery has no recorded response")
    payload = _pending(state)
    where = graph_nodes.invocation(state["meta"], {"deliver": len(responses) - 1})
    key = next(reversed(responses))
    row = responses[key]
    if (key != effect_ledger.digest({"path": where, "payload_sha256": effect_ledger.digest(payload)})
            or row["schema_id"] != "external_delivery" or row["value_sha256"] != effect_ledger.digest(row["value"])):
        raise ValueError("stage delivery differs from its recorded response")
    return orchestrator.stage_delivery_action(_root(state), payload, row["value"])


def build(ctx):
    from langgraph.graph import END, START, StateGraph

    state = TypedDict("StageState", {
        **graph_nodes.BaseState.__annotations__, "stage_request": dict,
        "prepared": Annotated[dict, graph_nodes.last_value], "assignments": Annotated[dict, graph_nodes.last_value],
        "dispatch": Annotated[dict, graph_nodes.last_value]}, total=False)
    builder = StateGraph(state, input_schema=StageView)
    add = lambda name, node: graph_nodes.add(builder, name, node, graph_id=ctx.graph_id)
    add("prepare", graph_nodes.effect(
        "research.stage.prepare", kind="journal", run=_prepare, segment=lambda s: {"prepare": "stage"},
        identity=_stage_identity, max_attempts=8,
        to_state=lambda s, r: {"prepared": r["prepared"], "assignments": r["assignments"]}))
    add("dispatch", graph_nodes.effect(
        "research.stage.dispatch", kind="worker", run=_dispatch, segment=lambda s: {"dispatch": _responses(s)},
        identity=lambda s: {**_stage_identity(s), "specification": s["prepared"]["specification"],
                            "deliveries": _responses(s)}, max_attempts=8,
        to_state=lambda s, r: {"dispatch": r}))
    add("deliver", graph_nodes.interrupt("external_delivery", _pending,
                                         segment=lambda s: {"deliver": _responses(s)}))
    add("delivered", graph_nodes.gate("research_choice", _delivered_action))
    add("complete", graph_nodes.effect(
        "research.stage.complete", kind="journal", run=_complete, segment=lambda s: {"complete": "stage"},
        identity=lambda s: {**_stage_identity(s), "specification": s["prepared"]["specification"]}, max_attempts=8,
        to_state=lambda s, r: {"results": {"stage": r}}))
    add("refused", graph_nodes.hold("stage_delivery_gate_refused",
                                    "the research_choice gate passes for this stage's delivery"))
    add("decision_turn", graph_nodes.decision_turn(GRAPH_ID))
    add("reconcile", graph_nodes.reconcile_node())
    add("hold", graph_nodes.hold("research_stage_hold"))
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "dispatch")
    graph_nodes.connect(builder, "dispatch", graph_nodes.route(
        lambda s: "complete" if (s.get("dispatch") or {}).get("complete") else "deliver",
        {"complete": "complete", "deliver": "deliver"}))
    builder.add_edge("deliver", "delivered")
    graph_nodes.connect(builder, "delivered", graph_nodes.gate_route("research_choice", passed="dispatch",
                                                                     refused="refused"))
    builder.add_edge("complete", END)
    return builder


def request(*, artifact, out, settings, host_key, operation_sha256, campaign_root=None):
    """The stage graph's input view for one stage run."""
    return {"artifact": deepcopy(artifact), "out": str(out), "settings": deepcopy(settings), "host": host_key,
            "operation_sha256": operation_sha256,
            **({"campaign_root": str(campaign_root)} if campaign_root is not None else {})}
