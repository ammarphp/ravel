"""Constructive next turns through the existing research cycle and AgentGraph.

No second journal, runner, goal state or acceptance policy lives here. Actual
critic/verifier content is presented before independent ideation; both idea
sets are then presented to a designer. Proposed studies still use ordinary
science admission, phase reservations, CHECK-IN 1 and scientific review.
"""
from copy import deepcopy
from . import provider_transport
import hashlib
import json
from pathlib import Path
import time

from . import agent_graph, research_cycle as cycle, state_io

STREAMS = ("citation_led", "speculative")
MAX_BYTES = 2 * 1024 * 1024


def _bytes(pin, base):
    """Authenticate the bytes consumed, not a path subsequently reread."""
    cycle.ce.keys(pin, ("path", "sha256", "size"))
    cycle.ce.sha(pin["sha256"])
    if type(pin["size"]) is not int or not 0 <= pin["size"] <= MAX_BYTES:
        raise ValueError("bounded next-turn content required")
    path = Path(pin["path"])
    path = cycle._ordinary(path if path.is_absolute() else Path(base) / path)
    with path.open("rb") as stream:
        import os
        before = os.fstat(stream.fileno())
        raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    current = cycle._ordinary(path).stat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    if (identity(before) != identity(after) or identity(after) != identity(current)
            or len(raw) != pin["size"] or hashlib.sha256(raw).hexdigest() != pin["sha256"]):
        raise ValueError("next-turn content changed during authenticated consumption")
    return path, raw


def _json(pin, base):
    from .agent_host import _loads
    return _loads(_bytes(pin, base)[1])


def _write_new(path, value):
    path = cycle._ordinary(path)
    if path.exists(): raise ValueError("fresh immutable next-turn artifact required")
    state_io.atomic_json(path, value)
    return cycle._pin(path)


def _feedback_content(root, identity):
    feedback_pin = cycle.feedback_packet(root, identity)
    _, state = cycle._load(root)
    parent = next(e for e in state["experiments"] if e["id"] == identity)
    value = _json(feedback_pin, state["base_dir"])
    content, pins = [], [feedback_pin]
    if parent.get("diagnostic_feedback") is not None:
        diagnostic_pin = parent["diagnostic_feedback"]
        diagnostic = _json(diagnostic_pin, state["base_dir"])
        pins.append(diagnostic_pin)
        for row in diagnostic["reviews"]:
            if diagnostic["kind"] == "failed_stage_historical_feedback":
                path = Path(row["report"]["path"])
                pin = cycle._pin(path)
                if pin["sha256"] != row["report"]["sha256"]:
                    raise ValueError("retained role report changed")
                raw = _bytes(pin, state["base_dir"])[1]
                content.append({"role": row["role"], "actor_id": row["actor_id"],
                    "source": pin, "content": raw.decode("utf-8"),
                    "transport": "retained_attributed_report", "fresh_model_call_observed": False})
                pins.append(pin)
            else:
                receipt = row["receipt"]
                content.append({"role": receipt["role"], "actor_id": row["actor_id"],
                    "content": deepcopy(receipt["public_value"]),
                    "transport": receipt["execution_observation"],
                    "fresh_model_call_observed": receipt["execution_observation"] in {
                        "remote_transport_observed", "local_transport_observed", "host_attested_external"}})
    else:
        # The actual detached ordinary review snapshot contains the role event
        # prose. Present those events, not only its filename or accept verdict.
        pin = parent["adjudication"]["snapshot"]
        snapshot = _json(pin, state["base_dir"])
        content.append({"role": "ordinary_review_history", "source": pin,
            "content": snapshot["events"], "transport": "ordinary_review_journal",
            "fresh_model_call_observed": False})
        pins.append(pin)
    if not content: raise ValueError("actual role content required for constructive ideation")
    if len(json.dumps(content, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError("complete role feedback exceeds next-turn content bound; no truncation")
    # Re-observe the canonical feedback after all content has been consumed.
    if cycle.feedback_packet(root, identity) != feedback_pin:
        raise ValueError("review feedback changed during next-turn preparation")
    return state, value, feedback_pin, content, pins


def prepare_ideation(root, parent, output_dir, *, citation_sources, speculative_sources):
    """Present complete actual feedback to two separately charged Graph turns.

    Speculation may have no prior source. It is not gated on a citation, a
    successful parent or agreement with the critic. The contexts contain no
    peer idea output; this is declared presentation isolation, not an OS proof.
    """
    if any(type(rows) is not list or len(rows) > 16 for rows in (citation_sources, speculative_sources)):
        raise ValueError("bounded explicit idea-source census required")
    out = cycle._ordinary(output_dir)
    if out.exists(): raise ValueError("fresh ideation directory required")
    state, feedback, feedback_pin, reports, common_pins = _feedback_content(root, parent)
    premise_bindings = {p["id"]: p["sha256"] for p in state["premises"]}
    result = {}
    for stream, sources in zip(STREAMS, (citation_sources, speculative_sources)):
        source_content = []
        seen = set()
        for pin in sources:
            path, raw = _bytes(pin, state["base_dir"])
            if str(path) in seen: raise ValueError("distinct idea sources required")
            seen.add(str(path))
            source_content.append({"pin": deepcopy(pin), "content": raw.decode("utf-8")})
        value = {"kind": "research_ideation_context", "stream": stream,
            "cycle_root": str(cycle._ordinary(root)), "parent_experiment": parent,
            "feedback_pin": feedback_pin, "feedback": feedback, "role_content": reports,
            "premise_bindings": premise_bindings,
            "whole_task": deepcopy(state["context"]["requested_quantities"]),
            "sources": source_content, "common_pins": common_pins,
            "instructions": ("Generate competing mechanistic hypotheses and useful tests from the located primary sources; "
                "citation presence is attribution, not proof." if stream == "citation_led" else
                "Generate ambitious rival explanations and constructive remedies. Prior publication and prior supporting "
                "evidence are not required. State what would discriminate each idea, including surprising negative outcomes."),
            "output_contract": "{hypotheses:[{id,statement,stream,premise_ids,source_basis,parents}]}; stream must equal this stream",
            "peer_ideas_presented": False, "scientific_independence_proven": False,
            "execution_authorized": False, "physics_validated": False}
        if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_BYTES:
            raise ValueError("complete ideation context exceeds byte bound; no truncation")
        result[stream] = _write_new(out / (stream + ".json"), value)
    return result


def _current_design_ideas(root, state, context):
    """Rebind the complete two-stream census to real current Graph outputs.

    Duplicated context rows are presentation, not authority. Neither deleting
    one stream nor replacing its hypotheses with an empty list can narrow the
    actual adopted rival population presented to an experiment designer.
    """
    rows = context.get("ideas")
    if (type(rows) is not list or len(rows) != len(STREAMS)
            or {row.get("stream") for row in rows if type(row) is dict} != set(STREAMS)):
        raise ValueError("both unique actual ideation streams required in the design context")
    charged = {g["root"] for g in state["graphs"]}
    for row in rows:
        cycle.ce.keys(row, ("stream", "binding", "origin", "hypotheses"))
        binding = row["binding"]
        cycle.ce.keys(binding, ("graph_root", "node_id", "context_pin"))
        # Refuse a design-context reference before recursive freshness checking;
        # each stream must point to an ORIGINAL ideation context.
        idea_context = _json(binding["context_pin"], state["base_dir"])
        if idea_context.get("kind") != "research_ideation_context":
            raise ValueError("original separate ideation context required")
        _, idea_context = _current_context(root, binding["context_pin"])
        if (idea_context["stream"] != row["stream"]
                or idea_context["parent_experiment"] != context["parent_experiment"]
                or str(cycle._ordinary(binding["graph_root"])) not in charged):
            raise ValueError("design context must retain its exact charged stream and parent")
        actual = cycle._graph_result(binding["graph_root"], binding["node_id"])
        exact_input = [{"id": "constructive-context", **{k: binding["context_pin"][k] for k in ("path", "sha256")}}]
        if (actual != row["origin"] or actual["role"] != "proposer" or actual["node_kind"] != "model"
                or actual["inputs"] != exact_input or actual["value"].get("kind") != "model_result"):
            raise ValueError("design context must bind each original actual model result")
        hypotheses = actual["value"]["value"]["hypotheses"]
        if type(hypotheses) is not list or not hypotheses or row["hypotheses"] != hypotheses:
            raise ValueError("design hypotheses differ from the complete actual model-result census")
        for hypothesis in hypotheses:
            retained = next((h for h in state["hypotheses"] if h["id"] == hypothesis["id"]), None)
            if (retained is None or retained["origin"] != actual or hypothesis["stream"] != row["stream"]
                    or {k: retained[k] for k in hypothesis} != hypothesis
                    or not cycle._fresh(state, retained["premise_bindings"])):
                raise ValueError("complete currently adopted rival content required before study design")


def _current_context(root, pin):
    _, state = cycle._load(root)
    context = _json(pin, state["base_dir"])
    if context.get("cycle_root") != str(cycle._ordinary(root)):
        raise ValueError("next-turn context belongs to another cycle")
    if context["premise_bindings"] != {p["id"]: p["sha256"] for p in state["premises"]}:
        raise ValueError("premise changed; reframe the next turn")
    fresh = cycle.feedback_packet(root, context["parent_experiment"])
    if fresh != context["feedback_pin"]:
        raise ValueError("actual feedback changed; prepare a new constructive turn")
    _, feedback, _, reports, _ = _feedback_content(root, context["parent_experiment"])
    if context["feedback"] != feedback or context["role_content"] != reports:
        raise ValueError("complete actual role feedback differs from presented context")
    if context["whole_task"] != state["context"]["requested_quantities"]:
        raise ValueError("whole requested quantity census changed")
    # Authenticate all content sources even though the context embeds bytes.
    for source in context.get("sources", []):
        if _bytes(source["pin"], state["base_dir"])[1].decode("utf-8") != source["content"]:
            raise ValueError("idea source differs from presented content")
    for report in context["role_content"]:
        if "source" in report:
            raw = _bytes(report["source"], state["base_dir"])[1]
            expected = _json(report["source"], state["base_dir"])["events"] if report["role"] == "ordinary_review_history" else raw.decode("utf-8")
            if expected != report["content"]: raise ValueError("role content differs from its original report")
    if context.get("kind") == "research_design_context":
        _current_design_ideas(root, state, context)
    elif context.get("kind") != "research_ideation_context":
        raise ValueError("ordinary ideation or design context required")
    return state, context


def ideation_spec(context_pin, *, graph_id, model, reasoning_effort, max_output_tokens, max_wall_seconds, adapter="responses"):
    """One normal model node; the caller uses cycle.execute_graph with its Host."""
    context = _json(context_pin, Path.cwd())
    if context["kind"] != "research_ideation_context" or context["stream"] not in STREAMS:
        raise ValueError("prepared separate ideation context required")
    cycle._text(model)
    cycle._text(reasoning_effort)
    if adapter not in provider_transport.MODEL_ACTIONS: raise ValueError("explicit ordinary Host adapter required")
    if type(max_output_tokens) is not int or not 16 <= max_output_tokens <= 32000:
        raise ValueError("finite idea output reservation required")
    schema = {"type": "object", "properties": {"hypotheses": {"type": "array", "minItems": 1, "maxItems": 16,
        "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "statement": {"type": "string"},
            "stream": {"type": "string", "enum": [context["stream"]]},
            "premise_ids": {"type": "array", "items": {"type": "string"}},
            "source_basis": {"type": "array", "items": {"type": "object", "properties": {
                "path": {"type": "string"}, "sha256": {"type": "string"}, "size": {"type": "integer"}},
                "required": ["path", "sha256", "size"], "additionalProperties": False}},
            "parents": {"type": "array", "items": {"type": "string"}}},
            "required": ["id", "statement", "stream", "premise_ids", "source_basis", "parents"],
            "additionalProperties": False}}}, "required": ["hypotheses"], "additionalProperties": False}
    spec = {"schema_version": 1, "graph_id": graph_id,
        "budget": {"max_nodes": 1, "max_calls": 1, "max_output_tokens": max_output_tokens,
            "max_wall_seconds": max_wall_seconds, "max_reworks": 0},
        "nodes": [{"id": "ideas", "kind": "model", "role": "proposer", "depends_on": [],
            "inputs": [{"id": "constructive-context", **{k: context_pin[k] for k in ("path", "sha256")}}],
            "packet": None, "action": adapter, "max_attempts": 1,
            "parameters": {"instructions": context["instructions"], "model": model,
                "reasoning_effort": reasoning_effort, "max_output_tokens": max_output_tokens, "output_schema": schema}}]}
    return agent_graph.validate(spec)


def adopt_ideas(root, graph_root, *, context_pin, node_id="ideas"):
    """Adopt an actual charged stream result, retaining unsupported rivals."""
    state, context = _current_context(root, context_pin)
    if context["kind"] != "research_ideation_context": raise ValueError("ideation context required")
    if str(cycle._ordinary(graph_root)) not in {g["root"] for g in state["graphs"]}:
        raise ValueError("ideation must use this cycle's charged ordinary Graph")
    origin = cycle._graph_result(graph_root, node_id)
    exact_input = [{"id": "constructive-context", **{k: context_pin[k] for k in ("path", "sha256")}}]
    if origin["inputs"] != exact_input or origin["role"] != "proposer" or origin["node_kind"] != "model":
        raise ValueError("separate stream must present only its exact checked context")
    spec, _ = agent_graph._load(cycle._ordinary(graph_root))
    node = next(n for n in spec["nodes"] if n["id"] == node_id)
    expected = ideation_spec(context_pin, graph_id=spec["graph_id"], model=node["parameters"]["model"],
        reasoning_effort=node["parameters"]["reasoning_effort"],
        max_output_tokens=node["parameters"]["max_output_tokens"],
        max_wall_seconds=spec["budget"]["max_wall_seconds"], adapter=node["action"])["nodes"][0]
    expected["id"] = node_id
    if node != expected:
        raise ValueError("ideation instructions/schema/dependencies must preserve its separate presented stream")
    value = origin["value"]
    if value.get("kind") != "model_result": raise ValueError("actual structured model result required; controls remain controls")
    cycle.ce.keys(value["value"], ("hypotheses",))
    rows = value["value"]["hypotheses"]
    if not rows or any(h["stream"] != context["stream"] for h in rows):
        raise ValueError("hypotheses must retain their independently presented stream")
    allowed = [s["pin"] for s in context["sources"]] + [context["feedback_pin"]]
    allowed += [r["source"] for r in context["role_content"] if "source" in r]
    visible = {(str(cycle._ordinary(Path(p["path"]) if Path(p["path"]).is_absolute()
               else Path(state["base_dir"]) / p["path"])), p["sha256"]) for p in allowed}
    for h in rows:
        for basis in h["source_basis"]:
            path = Path(basis["path"])
            key = (str(cycle._ordinary(path if path.is_absolute() else Path(state["base_dir"]) / path)), basis["sha256"])
            if key not in visible:
                raise ValueError("declared hypothesis basis was not presented to its ideation stream")
    # This is the existing journal operation, not a second idea store.
    return cycle.propose(root, rows, origin={"kind": "graph", "root": str(graph_root), "node_id": node_id})


def run_ideation(root, parent, output_dir, *, host, model, reasoning_effort,
                 max_output_tokens, max_wall_seconds, citation_sources,
                 speculative_sources, adapter="responses"):
    """Drive both fresh turns through the existing Graph/Host accounting.

    This is a convenience composition, not a new scheduler or execution
    authority. Preflight reserves room for BOTH stream ceilings. Each actual
    turn is separately charged by cycle.execute_graph; an incomplete turn
    stops the composition without retry or adoption of a partial portfolio.
    Source/queue/review time remains within the original cycle clock.
    """
    out = cycle._ordinary(output_dir)
    if out.exists(): raise ValueError("fresh independent ideation route required; no implicit retry")
    _, state = cycle._load(root)
    # The ordinary graph validator owns scalar bounds; validate before creating
    # contexts or invoking an expensive actor.
    if (type(max_output_tokens) is not int or not 16 <= max_output_tokens <= 32000
            or type(max_wall_seconds) is not int or not 1 <= max_wall_seconds <= 3600):
        raise ValueError("finite two-stream reservations required")
    needed = {"calls": 2, "output_tokens": 2 * max_output_tokens,
              "wall_seconds": 2 * max_wall_seconds, "native_attempts": 0}
    usage = cycle._usage(state)
    if any(usage[k] + needed[k] > state["contract"]["budget"][k] for k in cycle.VECTORS):
        raise ValueError("complete two-stream ideation cannot fit cumulative cycle budget")
    deadline = state["timing"]["deadline_epoch"]
    if deadline is not None and needed["wall_seconds"] > max(0, deadline - time.time()):
        raise cycle.OperationalBoundaryError("both ideation ceilings cannot fit the original campaign deadline")
    contexts = prepare_ideation(root, parent, out / "contexts",
        citation_sources=citation_sources, speculative_sources=speculative_sources)
    bindings, observations = {}, []
    for stream in STREAMS:
        _current_context(root, contexts[stream])
        spec = ideation_spec(contexts[stream], graph_id="followup-" + stream,
            model=model, reasoning_effort=reasoning_effort, max_output_tokens=max_output_tokens,
            max_wall_seconds=max_wall_seconds, adapter=adapter)
        graph = out / (stream + "-graph")
        result = cycle.execute_graph(root, graph, spec, host)
        observations.append({"stream": stream, "graph_root": str(graph), "result": result})
        bindings[stream] = {"graph_root": str(graph), "node_id": "ideas", "context_pin": contexts[stream]}
        if not result["complete"]:
            return {"kind": "connected_ideation_observation", "complete": False,
                "bindings": bindings, "observations": observations,
                "hypotheses_adopted": False, "retry_attempts": 0,
                "execution_authorized": False, "physics_validated": False}
    # Adopt through the original immutable cycle operations, only after BOTH
    # transport turns completed. A failure remains in the ordinary graph ledger.
    for stream in STREAMS:
        adopt_ideas(root, bindings[stream]["graph_root"], context_pin=contexts[stream])
    return {"kind": "connected_ideation_observation", "complete": True,
        "bindings": bindings, "observations": observations,
        "hypotheses_adopted": True, "retry_attempts": 0,
        "execution_authorized": False, "physics_validated": False}


def prepare_design_context(root, parent, idea_bindings, output_dir):
    """Explicitly present both actual idea results and original role critique."""
    if type(idea_bindings) is not dict or set(idea_bindings) != set(STREAMS):
        raise ValueError("both independent idea streams required before design")
    state, feedback, feedback_pin, reports, pins = _feedback_content(root, parent)
    ideas = []
    for stream in STREAMS:
        binding = idea_bindings[stream]
        cycle.ce.keys(binding, ("graph_root", "node_id", "context_pin"))
        _, context = _current_context(root, binding["context_pin"])
        if context["stream"] != stream or context["parent_experiment"] != parent:
            raise ValueError("idea stream or parent differs")
        origin = cycle._graph_result(binding["graph_root"], binding["node_id"])
        if str(cycle._ordinary(binding["graph_root"])) not in {g["root"] for g in state["graphs"]}:
            raise ValueError("uncharged idea result cannot supply the designer")
        rows = origin["value"]["value"]["hypotheses"]
        for row in rows:
            retained = next((h for h in state["hypotheses"] if h["id"] == row["id"]), None)
            if (retained is None or retained["origin"] != origin or row["stream"] != stream
                    or not cycle._fresh(state, retained["premise_bindings"])):
                raise ValueError("designer must consume the current actually adopted rival census")
        ideas.append({"stream": stream, "binding": deepcopy(binding), "origin": origin, "hypotheses": rows})
    value = {"kind": "research_design_context", "cycle_root": str(cycle._ordinary(root)),
        "parent_experiment": parent, "feedback_pin": feedback_pin, "feedback": feedback,
        "role_content": reports, "premise_bindings": {p["id"]: p["sha256"] for p in state["premises"]},
        "ideas": ideas, "whole_task": deepcopy(state["context"]["requested_quantities"]),
        "usage_ceiling": cycle._usage(state), "budget": state["contract"]["budget"],
        "instructions": "Construct competing executable ordinary studies, not only commentary. Declare rival outcomes "
            "and controls that distinguish delivery infrastructure from scientific mechanisms. Preserve all requested quantities, "
            "failed and negative evidence, alternative hypotheses, and preconstruction lifecycle/check reservations. "
            "A surprising idea can deserve a test without evidence for its expected result. Select among affordable designs "
            "only after the current phase policy is updated; no study or review is authorized here.",
        "execution_authorized": False, "physics_validated": False}
    if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError("complete competing design context exceeds bound; no truncation")
    return _write_new(cycle._ordinary(output_dir) / "design-context.json", value)


def bound_portfolio(proposal, context, *, proposal_base, context_pin, presented_pins):
    """Ordinary Host admission of a complete rival study portfolio."""
    if 'stage_correspondence' in proposal:
        from . import resonance_study
        resonance_study.portfolio_correspondence(proposal, proposal_base, presented_pins)
    cycle.ce.keys(proposal, {'kind','parent_experiment','context_sha256','reason','experiments'} |
                  ({'stage_correspondence'} if 'stage_correspondence' in proposal else set()))
    if (proposal["kind"] != "research_portfolio" or context["kind"] != "research_design_context"
            or proposal["context_sha256"] != context_pin["sha256"]
            or proposal["parent_experiment"] != context["parent_experiment"]):
        raise ValueError("portfolio requires the exact complete next-turn design context")
    _, current = _current_context(context["cycle_root"], context_pin)
    if current != context:
        raise ValueError("portfolio must consume its exact current full design context")
    cycle._text(proposal["reason"])
    rows = proposal["experiments"]
    if type(rows) is not list or not 1 <= len(rows) <= 8 or len({e["id"] for e in rows}) != len(rows):
        raise ValueError("bounded distinct competing ordinary studies required")
    presented = {p["sha256"] for p in presented_pins}
    if context_pin["sha256"] not in presented: raise ValueError("designer must receive the full context as a normal input")
    rivals = {h["id"] for stream in context["ideas"] for h in stream["hypotheses"]}
    if not rivals <= {h for e in rows for h in e["predictions"]}:
        raise ValueError("every generated rival needs a predicted outcome or explicit unknown in the portfolio")
    for e in rows:
        if e["parent"] != context["parent_experiment"]:
            raise ValueError("every competing study must retain the actual feedback parent")
        synthetic_revision = {"kind": "research_revision", "parent_experiment": e["parent"],
            "feedback_sha256": context["feedback_pin"]["sha256"], "reason": proposal["reason"],
            "hypotheses": [], "experiment": e}
        # The exact feedback is embedded AND a normal pin, preserving the
        # existing task-input exposure/heldout boundary for each actual study.
        cycle.bound_revision(synthetic_revision, context["feedback"], proposal_base=proposal_base,
            feedback_pin=context["feedback_pin"], presented_pins=presented_pins)
    return deepcopy(proposal)


def adopt_portfolio(root, graph_root, *, node_id, context_pin):
    """Atomically add rival studies to the existing journal, with no vote carry."""
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        state, context = _current_context(root, context_pin)
        if context["kind"] != "research_design_context": raise ValueError("current full design context required")
        if str(cycle._ordinary(graph_root)) not in {g["root"] for g in state["graphs"]}:
            raise ValueError("designer must use the cycle's cumulative ordinary Graph")
        origin = cycle._graph_result(graph_root, node_id)
        if origin["role"] != "designer" or origin["value"].get("kind") not in {"model_result", "ravel_tool_result"}:
            raise ValueError("actual structured designer result required")
        # Recheck the original ideas, not merely the cached context text.
        for stream in context["ideas"]:
            if cycle._graph_result(stream["binding"]["graph_root"], stream["binding"]["node_id"]) != stream["origin"]:
                raise ValueError("rival Graph result changed after designer preparation")
        proposal = bound_portfolio(origin["value"]["value"], context, proposal_base=state["base_dir"],
            context_pin=context_pin, presented_pins=origin["inputs"])
        trial = deepcopy(state)
        for e in proposal["experiments"]:
            cycle._append_design(trial, e)
            added = trial["experiments"][-1]
            cycle._model_input_admission(added, added["input_pins"], origin["inputs"], state["base_dir"])
            added["constructive_origin"] = {**origin, "complete_role_content_presented": True,
                "design_context": context_pin, "independent_scientific_review": False}
            trial["revisions"].append({"parent": e["parent"], "candidate": e["id"],
                "feedback": context["feedback_pin"], "origin": added["constructive_origin"],
                "reason": proposal["reason"], "incumbent_and_negative_results_retained": True,
                "old_votes_carried": []})
        return cycle._commit(Path(root), trial, "constructive_rival_portfolio_adopted",
            experiment_ids=[e["id"] for e in proposal["experiments"]])
