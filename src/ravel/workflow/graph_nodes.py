"""Node kinds every substrate graph is built from.

Each factory returns a ``Node`` whose metadata ``{ravel_kind, role, gate, graph_id}``
the G8 introspection reads, and wraps its body so that the body returns a state
update only: a body that returns ``Command`` or ``Send`` is refused. Branching is
``route`` with a declared ``path_map``; only ``map_node`` emits ``Send``. Gates call
``decision_gate.check`` and never write; effects go through ``effect_ledger.call``
under a domain path; interrupts carry a typed response schema, are ledgered as data
and are followed by a gate, because a resume value is never authority. Errors
become typed failure records routed by each builder's own handler to its own
``decision_turn``, ``reconcile`` or ``hold``. Handoffs are final-record data routed
by the parent's ``path_map``; ``Command.PARENT`` is not used. The ``agent`` kind is
added for broker actions.
"""
from __future__ import annotations

# Strict msgpack is read when LangGraph is imported (R4): set it before any import below.
from . import graph_environment  # noqa: F401

from contextlib import contextmanager  # noqa: E402
from contextvars import ContextVar  # noqa: E402
from copy import deepcopy  # noqa: E402
from dataclasses import asdict, dataclass, field, is_dataclass  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
from importlib import import_module  # noqa: E402
from pathlib import Path  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from typing import Annotated, Any, Callable, TypedDict  # noqa: E402

from langgraph.managed import RemainingSteps  # noqa: E402

from . import effect_ledger, graph_registry  # noqa: E402
from .agent_graph import AmbiguousCall, GraphError  # noqa: E402
from .state_io import atomic_json  # noqa: E402

KINDS = ("gate", "effect", "agent", "map", "interrupt", "rdj", "guard", "decision_turn", "hold", "board", "subgraph")
GUARD_VERDICTS = ("go", "escalate", "drain", "exhausted")
REQUIRED_NODES = ("decision_turn", "reconcile", "hold")
# Interrupts not followed by a gate: reconcile evidence re-enters a ledgered effect, and
# RDJ proposer answers are content bound to case_sha256 that ``answer`` checks (§1.7 item 3).
UNGATED_INTERRUPTS = ("reconcile_evidence", "proposer_answers")
MAX_INVALID_RESPONSES = 3
END = "__end__"
RESPONSES = "framework/responses"
EDGE_MARK = "__ravel_edge__"
GATE_MARK = "__ravel_gate__"
# Framework channels: a run input, map packet or subgraph view never carries them, and
# only the named node kind writes them (gates: gate; responses: interrupt).
FRAMEWORK_CHANNELS = ("meta", "effects", "gates", "responses", "failures")
CHANNEL_WRITERS = {"gates": "gate", "responses": "interrupt"}
SUBSTRATE_MARK = "__ravel_substrate__"

# Tripwire: set for the duration of every substrate node body. A model or tool
# call observed while it is None, or inside a kind that may not act, is a G8 bypass.
TRIPWIRE: ContextVar[dict | None] = ContextVar("ravel_graph_node", default=None)
# Gate provider overrides for a run (tests, fixtures). None uses decision_gate.
GATE_CHECK: ContextVar[Callable | None] = ContextVar("ravel_gate_check", default=None)
GATE_PROVIDERS: ContextVar[Callable | None] = ContextVar("ravel_gate_providers", default=None)
# The runner's RunControl: a guard that sees the stop file drains the run at the next
# superstep boundary instead of ending the thread, so the graph stays resumable.
RUN_CONTROL: ContextVar[Any] = ContextVar("ravel_run_control", default=None)
# Provisioning drift observed on reused receipts during this invocation.
RUN_DRIFT: ContextVar[list | None] = ContextVar("ravel_run_drift", default=None)


class GateRefused(GraphError):
    """A consequential effect's gate re-check returned errors immediately before acting."""
    not_dispatched = True

    def __init__(self, message, errors=()):
        super().__init__(message)
        self.errors = list(errors)


class ResponseInvalid(GraphError):
    """A resume value failed its response schema repeatedly."""


class RecoveryHold(GraphError):
    """A node cannot proceed; the run ends in a typed hold, not an abort."""
    not_dispatched = True

    def __init__(self, reason, would_make_possible=None):
        super().__init__(reason)
        self.reason, self.would_make_possible = reason, would_make_possible


class ControlFlowRefused(GraphError):
    """A node body tried to branch (``Command``/``Send``) instead of returning a state update."""


# ---- base channels (§1.9) -------------------------------------------------------

def write_once(left, right):
    """Dict channel shared across graph boundaries: equal re-merge accepted, change refused."""
    result = dict(left or {})
    for key, value in (right or {}).items():
        if key in result and result[key] != value:
            raise GraphError(f"write-once channel key {key!r} cannot change")
        result[key] = deepcopy(value)
    return result


def write_once_value(left, right):
    if left and right and left != right:
        raise GraphError("graph meta is written once")
    return deepcopy(right or left)


def latest_by_sequence(left, right):
    result = dict(left or {})
    for key, value in (right or {}).items():
        if key not in result or value.get("sequence", 0) >= result[key].get("sequence", 0):
            result[key] = deepcopy(value)
    return result


def last_value(left, right):
    return deepcopy(right) if right is not None else left


class BaseState(TypedDict, total=False):
    meta: Annotated[dict, write_once_value]
    effects: Annotated[dict, write_once]
    gates: Annotated[dict, latest_by_sequence]
    responses: Annotated[dict, write_once]
    failures: Annotated[dict, write_once]
    results: Annotated[dict, write_once]
    status: Annotated[dict, last_value]
    remaining_steps: RemainingSteps


def lint_state(value, path="$"):
    """JSON-safe values and LangChain messages only (§1.9, Q5). Returns problems."""
    if value is None or type(value) in (str, bool, int):
        return []
    if type(value) is float:
        return [] if value == value and value not in (float("inf"), float("-inf")) else [f"{path} is not finite"]
    if type(value) is list:
        return [p for i, item in enumerate(value) for p in lint_state(item, f"{path}[{i}]")]
    if type(value) is dict:
        problems = []
        for key, item in value.items():
            if type(key) is not str:
                problems.append(f"{path} has a non-string key")
            problems.extend(lint_state(item, f"{path}.{key}"))
        return problems
    try:
        from langchain_core.messages import BaseMessage
        if isinstance(value, BaseMessage):
            return []
    except ImportError:
        pass
    return [f"{path} holds {type(value).__module__}.{type(value).__name__}, which is not JSON-safe"]


# ---- nodes and edges ----------------------------------------------------------------

@dataclass
class Edge:
    """A conditional edge: ``router(state)`` returns a key of ``path_map``.

    ``path_map`` may be the string ``"nodes"``: ``finish`` then declares every node
    of the builder (used by ``reconcile`` to re-enter the node whose effect it closed).
    """
    router: Callable
    path_map: dict | str
    kind: str = "route"
    target: str | None = None


@dataclass
class Node:
    kind: str
    function: Callable
    role: str | None = None
    gate: str | None = None
    options: dict = field(default_factory=dict)
    then: Edge | str | None = None
    interrupt_kind: str | None = None

    def metadata(self, graph_id):
        return {"ravel_kind": self.kind, "role": self.role, "gate": self.gate, "graph_id": graph_id}


def route(router: Callable, path_map: dict) -> Edge:
    """The only way to branch. A key outside ``path_map`` or a ``Send`` is refused (§1.10, R10)."""
    if type(path_map) is not dict or not path_map:
        raise GraphError("route needs a non-empty path_map")
    return Edge(router, dict(path_map))


def _edge_function(edge: Edge, path_map):
    from langgraph.types import Send

    def decide(state):
        key = edge.router(state)
        if edge.kind == "map":
            if type(key) is not list or any(type(s) is not Send or s.node != edge.target for s in key):
                raise ControlFlowRefused("map router may send only to its declared target")
            return key
        if isinstance(key, Send) or type(key) is list:
            raise ControlFlowRefused("only map_node may emit Send")
        if key not in path_map:
            raise ControlFlowRefused(f"route key {key!r} is not in the declared path_map")
        return key
    setattr(decide, EDGE_MARK, edge.kind)
    setattr(decide, GATE_MARK, getattr(edge.router, GATE_MARK, None))
    decide.__name__ = "route_" + getattr(edge.router, "__name__", "edge").strip("<>")
    return decide


def connect(builder, source, edge: Edge | str, *, nodes=None):
    """Add ``edge`` from ``source``: a static edge for a name, a declared conditional edge otherwise."""
    if type(edge) is str:
        builder.add_edge(source, edge)
        return builder
    path_map = edge.path_map
    if path_map == "nodes":
        path_map = {name: name for name in sorted(nodes or builder.nodes) if not name.startswith("__")}
        path_map["end"] = END
    if edge.kind == "map":
        builder.add_conditional_edges(source, _edge_function(edge, path_map), [edge.target])
    else:
        builder.add_conditional_edges(source, _edge_function(edge, path_map), path_map)
    return builder


def add(builder, name, node: Node, *, graph_id):
    """Register ``node`` on a StateGraph builder with its G8 metadata and its declared exit."""
    if node.kind not in KINDS:
        raise GraphError(f"unknown node kind {node.kind!r}")
    if "error_handler" in node.options:
        raise GraphError("node error handlers are the builder's own (§1.8); do not set one per node")
    builder.add_node(name, _instrumented(node.kind, graph_id, node.role, node.function),
                     metadata=node.metadata(graph_id), **node.options)
    if node.kind == "interrupt":
        builder.__dict__.setdefault("_ravel_interrupts", {})[name] = node.interrupt_kind
    if node.then is not None:
        if type(node.then) is Edge and node.then.path_map == "nodes":
            pending = builder.__dict__.setdefault("_ravel_deferred", [])
            pending.append((name, node.then))
        else:
            connect(builder, name, node.then)
    return builder


def _instrumented(kind, graph_id, role, function):
    import inspect
    from langgraph.types import Command, Send
    parameters = list(inspect.signature(function).parameters)
    if len(parameters) != 1:
        raise GraphError("substrate node bodies take exactly the state argument")

    def body(state):
        token = TRIPWIRE.set({"ravel_kind": kind, "graph_id": graph_id, "role": role,
                              "node": effect_ledger._node_name()})
        try:
            from contextlib import ExitStack
            from . import gate_wiring
            meta = state.get('meta') or {}
            with ExitStack() as running:
                if meta.get('scope_root'):
                    # The final steering check and the record of this running node are one steering
                    # transaction; the body then runs outside the lock and drains under a later pause.
                    try:
                        running.enter_context(gate_wiring.steering_admitted(meta['scope_root'], effect_ledger._node_name()))
                    except gate_wiring.SteeringRefused as exc:
                        raise GraphError(str(exc)) from None
                update = function(state)
        finally:
            TRIPWIRE.reset(token)
        if isinstance(update, (Command, Send)) or (type(update) in (list, tuple) and update
                                                  and isinstance(update[0], (Command, Send))):
            raise ControlFlowRefused(f"{kind} node body returned {type(update).__name__}; "
                                     "return a state update and branch with route()")
        if type(update) is dict:
            for channel, writer in CHANNEL_WRITERS.items():
                if channel in update and kind != writer:
                    raise ControlFlowRefused(f"{kind} node wrote the framework channel {channel}; "
                                             f"only {writer} nodes write it")
        return update
    body.__name__ = getattr(function, "__name__", "node")
    return body


@contextmanager
def gate_checker(function, control=None, providers=None, drift=None):
    tokens = (GATE_CHECK.set(function), RUN_CONTROL.set(control), GATE_PROVIDERS.set(providers),
              RUN_DRIFT.set(drift))
    try:
        yield
    finally:
        RUN_DRIFT.reset(tokens[3])
        GATE_PROVIDERS.reset(tokens[2])
        RUN_CONTROL.reset(tokens[1])
        GATE_CHECK.reset(tokens[0])


def _meta(state):
    meta = state.get("meta") or {}
    if not meta.get("graph_id") or not meta.get("scope_root"):
        raise GraphError("graph meta (graph_id, version, instance, scope_root) missing from state")
    return meta


def invocation(meta, segment):
    """The domain path prefix of a node of this graph invocation (graph, instance, enclosing path)."""
    return effect_ledger.path(meta["graph_id"], meta.get("instance") or {}, meta.get("path"), segment)


def _utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _plain(error):
    if is_dataclass(error):
        return json.loads(json.dumps(asdict(error)))  # tuples become lists in graph state
    if type(error) is dict:
        return deepcopy(error)
    return {"code": type(error).__name__, "message": str(error)}


def _required_providers(graph_id, gate_name):
    try:
        row = graph_registry.get(graph_id)
    except graph_registry.RegistryError:
        return None
    declared = row.get("gates") or {}
    return None if gate_name not in declared else list(declared[gate_name]["required_providers"])


def check_gate(scope_root, gate_name, action, *, graph_id=None):
    """``decision_gate.check`` plus ``provider_inactive`` for each inactive required provider.

    Fails closed while the decision-gate module is absent: an absent provider never yields an
    empty error list.
    """
    checker, providers = GATE_CHECK.get(), GATE_PROVIDERS.get()
    errors = []
    if checker is not None or providers is not None:
        # SW30: a controller run never takes its gate decisions from an in-process override.
        from ..controller import store as controller_store
        from ..controller.testing import SeamRefused, refuse_for_controller
        try:
            owned = controller_store.controller_owned(scope_root) is not None
        except getattr(controller_store, "StoreError", ValueError):
            owned = True  # a damaged controller marker: ownership unknown, so the override is refused
        try:
            refuse_for_controller("the GATE_CHECK/GATE_PROVIDERS gate override", owned=owned)
        except SeamRefused as exc:
            checker = providers = None
            errors.append({"code": "seam_refused", "gate": gate_name, "provider": "controller",
                           "message": str(exc), "fix": "decide the gate through the installed decision gate",
                           "pins": []})
    if checker is None or providers is None:
        try:
            from . import decision_gate
            checker = checker or decision_gate.check
            providers = providers or getattr(decision_gate, "providers", None)
        except ImportError:
            if checker is None:
                errors.append({"code": "gate_provider_unavailable", "gate": gate_name, "provider": "decision_gate",
                               "message": "decision_gate is not installed; the gate cannot pass",
                               "fix": "install the decision gate", "pins": []})
    if checker is not None:
        errors.extend(_plain(e) for e in checker(scope_root, gate_name, deepcopy(action)))
    required = _required_providers(graph_id, gate_name) if graph_id else []
    if required is None:
        errors.append({"code": "gate_not_declared", "gate": gate_name, "provider": "graph_registry",
                       "message": f"gate {gate_name} is not declared in the graph's registry row",
                       "fix": "declare the gate with its required_providers", "pins": []})
        required = []
    active = providers(gate_name) if providers is not None else {}
    reasons = {}
    if type(active) is list:  # decision_gate.providers returns its registry rows
        reasons = {r.get("id"): r.get("reason") for r in active if type(r) is dict and r.get("reason")}
        active = {r.get("id"): r.get("active") is True for r in active if type(r) is dict}
    for provider in required:
        if not (active or {}).get(provider):
            cause = reasons.get(provider) or "inactive or absent"
            errors.append({"code": "provider_inactive", "gate": gate_name, "provider": provider,
                           "message": f"required provider {provider} is unavailable: {cause}",
                           "fix": f"install or enable {provider}", "pins": []})
    return errors


# ---- factories --------------------------------------------------------------------

def gate(gate_name: str, action: Callable[[dict], dict]) -> Node:
    """Check a decision gate on the exact action digest; record the verdict, never act."""
    def body(state):
        meta = _meta(state)
        act = action(state)
        if type(act) is not dict or type(act.get("digest")) is not str:
            raise GraphError("gate action requires the digest of the exact bytes acted on")
        errors = check_gate(meta["scope_root"], gate_name, act, graph_id=meta["graph_id"])
        return {"gates": {gate_name: {"action_digest": act["digest"], "errors": errors,
                                      "providers": sorted({e.get("provider", "") for e in errors}),
                                      "checked_utc": _utc(), "sequence": time.time_ns()}}}
    return Node("gate", body, gate=gate_name)


def gate_passed(gate_name):
    """Router: the most recent verdict for ``gate_name`` had no errors."""
    def decide(state):
        verdict = (state.get("gates") or {}).get(gate_name)
        return "pass" if verdict is not None and verdict["errors"] == [] else "refuse"
    decide.__name__ = "gate_" + gate_name
    setattr(decide, GATE_MARK, gate_name)
    return decide


def gate_route(gate_name, *, passed, refused) -> Edge:
    return route(gate_passed(gate_name), {"pass": passed, "refuse": refused})


def _implementation_sha256(modules):
    found = {}
    for name in modules:
        module = import_module(name)
        found[name] = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    return effect_ledger.digest(found)


def effect(name: str, *, kind: str, run: Callable, segment: Callable, identity: Callable, to_state: Callable,
           provisioning: Callable | None = None, gate: str | None = None, implementation=(),
           downstream: Callable | None = None, charges: Callable | None = None, max_attempts: int = 1,
           revalidate: Callable | None = None) -> Node:
    """One deterministic RAVEL action, at most once per domain path and attempt.

    ``run(state, identity)`` performs the action. ``segment(state)`` is the node's own
    path segment; ``identity(state)`` defines equality and ``provisioning(state)`` is
    recorded only. ``check`` and ``compute`` effects name the ``implementation`` modules
    whose digest enters their identity. A consequential effect names its ``gate`` and
    re-checks it inside the same body, immediately before acting; its ``identity(state)``
    carries ``action_bytes_sha256``, the sha256 of the exact bytes acted on (launch argv,
    sealed request), and that digest is the action the gate checks.
    """
    if kind not in effect_ledger.KINDS:
        raise GraphError(f"effect kind must be one of {effect_ledger.KINDS}")
    if kind in effect_ledger.DETERMINISTIC and not implementation:
        raise GraphError("check and compute effects name their implementation modules")

    def body(state):
        meta = _meta(state)
        root = meta["scope_root"]
        where = invocation(meta, segment(state))
        ident = dict(identity(state))
        if implementation:
            ident["implementation_sha256"] = _implementation_sha256(implementation)
        if gate is not None and (type(ident.get("action_bytes_sha256")) is not str
                                 or not effect_ledger.SHA.fullmatch(ident["action_bytes_sha256"])):
            raise GraphError(f"gated effect {name} must carry action_bytes_sha256, the digest of the exact bytes "
                             "it acts on, in its identity")
        prov = dict(provisioning(state)) if provisioning else {}
        saved = effect_ledger.latest(root, where)
        replay = saved is not None and (saved["status"] in effect_ledger.OPEN or (
            saved["status"] == "completed" and saved["identity_sha256"] == effect_ledger.digest({**ident, "kind": kind})))
        if gate is not None and not replay:
            # Immediately before reserving: a refusal must not consume the path.
            errors = check_gate(root, gate, {"kind": name, "digest": ident["action_bytes_sha256"], "summary": name,
                                             "pins": []}, graph_id=meta["graph_id"])
            if errors:
                raise GateRefused(f"gate {gate} refused effect {name}", errors)
        result = effect_ledger.call(
            root, graph={"id": meta["graph_id"], "version": meta["version"]}, path=where, kind=kind,
            identity=ident, provisioning=prov, function=lambda: run(state, ident),
            charges=charges(state) if charges else (), downstream=downstream(state) if downstream else None,
            revalidate=revalidate, max_attempts=max_attempts, drift=RUN_DRIFT.get())
        receipt = effect_ledger.latest(root, where)
        update = dict(to_state(state, result) or {})
        update["effects"] = write_once(update.get("effects"), {effect_ledger.digest(where): {
            "call_id": receipt["call_id"], "name": name, "result_sha256": effect_ledger.digest(result)}})
        return update
    return Node("effect", body, gate=gate)


def agent(name: str, **options) -> Node:
    """A governed worker as a ``worker`` effect node; see ``agent_worker.graph_node``."""
    from .agent_worker import graph_node
    return graph_node(name, **options)


def _response_path(scope_root, where, payload_sha):
    return Path(scope_root) / RESPONSES / hashlib.sha256(where.encode()).hexdigest() / (payload_sha + ".json")


def recorded_response(scope_root, where, payload_sha):
    target = _response_path(scope_root, where, payload_sha)
    from .state_io import read_json
    return read_json(target) if target.exists() else None


def interrupt(kind: str, payload, response_schema=None, *, schema_id: str | None = None,
              segment: Callable | None = None) -> Node:
    """Pause for a typed response. Nothing effectful precedes the call; the node re-runs on resume.

    A validated response is ledgered as data under the node's path and the payload
    digest. When a version bump starts a new thread, the same path and payload return
    the recorded response without asking again (N5). An invalid value re-asks
    (bounded). Always follow this node with a gate: the response proves nothing.
    """
    sid = schema_id or kind
    graph_registry.response_schema(sid)

    def body(state):
        from langgraph.types import interrupt as pause
        meta = _meta(state)
        node = effect_ledger._node_name()
        value_of = payload(state) if callable(payload) else deepcopy(payload)
        where = invocation(meta, segment(state) if segment else {"interrupt": node or kind})
        payload_sha = effect_ledger.digest(value_of)
        key = effect_ledger.digest({"path": where, "payload_sha256": payload_sha})
        saved = recorded_response(meta["scope_root"], where, payload_sha)
        if saved is not None and not graph_registry.response_errors(sid, saved["value"]):
            return {"responses": {key: {"schema_id": sid, "value": saved["value"],
                                        "value_sha256": saved["value_sha256"], "replayed": True}}}
        request = {"kind": kind, "schema_id": sid, "graph_id": meta["graph_id"], "path": where, "node": node,
                   "payload": value_of, "payload_sha256": payload_sha, "approval_from_resume": False}
        schema = response_schema if response_schema is not None else graph_registry.response_schema(sid)
        for _ in range(MAX_INVALID_RESPONSES):
            value = pause(request, response_schema=schema)
            if hasattr(value, "model_dump"):
                value = value.model_dump(mode="json")
            errors = graph_registry.response_errors(sid, value)
            if not errors:
                record = {"schema_version": 1, "kind": "graph-response", "schema_id": sid, "path": where,
                          "payload_sha256": payload_sha, "value": value,
                          "value_sha256": effect_ledger.digest(value), "received_utc": _utc(),
                          "approval_from_resume": False}
                target = _response_path(meta["scope_root"], where, payload_sha)
                if not target.exists():
                    atomic_json(target, record)
                return {"responses": {key: {"schema_id": sid, "value": value,
                                            "value_sha256": record["value_sha256"], "replayed": False}}}
            request = {**request, "previous_errors": errors}
        raise ResponseInvalid(f"{sid} response failed its schema {MAX_INVALID_RESPONSES} times")
    return Node("interrupt", body, interrupt_kind=kind)


def guard(policy: Callable, routes: dict | None = None) -> Node:
    """Ceilings, card stops, protocol bounds, remaining steps and the stop file.

    ``policy(state)`` returns one of go, escalate, drain, exhausted. ``routes`` maps a
    verdict to a node; an unmapped non-go verdict ends the run with a typed status.
    """
    routes = dict(routes or {})
    if "go" not in routes:
        raise GraphError("guard needs a route for go")
    terminals = {"drain": "stopped", "exhausted": "budget_exhausted", "escalate": "escalate"}

    def body(state):
        meta = _meta(state)
        control = RUN_CONTROL.get()
        if effect_ledger.stop_requested(meta["scope_root"]) and control is None:
            verdict = "drain"
        elif state.get("remaining_steps") is not None and state["remaining_steps"] <= 2:
            verdict = "exhausted"
        else:
            if effect_ledger.stop_requested(meta["scope_root"]):
                control.request_drain("stop_requested")
            verdict = policy(state)
        if verdict not in GUARD_VERDICTS:
            raise GraphError(f"guard verdict must be one of {GUARD_VERDICTS}")
        terminal = None if verdict in routes else terminals[verdict]
        return {"status": {"phase": "guard", "verdict": verdict, "terminal": terminal, "reason": verdict,
                           "would_make_possible": None}}

    def decide(state):
        return (state.get("status") or {}).get("verdict")
    decide.__name__ = "guard"
    return Node("guard", body, then=route(decide, {v: routes.get(v, END) for v in GUARD_VERDICTS}))


def hold(reason: str, would_make_possible: str | None = None) -> Node:
    """Terminal node with a typed status; replaces dead-end interrupts.

    Reached from the builder's error handler, it keeps the handler's typed status.
    """
    def body(state):
        status = state.get("status") or {}
        if status.get("phase") == "handler":
            return {"status": {**status, "phase": "hold"}}
        return {"status": {"phase": "hold", "terminal": "hold", "reason": reason,
                           "would_make_possible": would_make_possible}}
    return Node("hold", body, then=END)


def decision_turn(subsystem: str, router: Callable | None = None, path_map: dict | None = None) -> Node:
    """Route the latest typed failure to the subsystem's decision; default target of the error handler.

    Without a ``router`` the run ends with ``decision_required`` (``escalate`` for a
    ceiling). A ``router(state, failure)`` returns a key of the declared ``path_map``.
    """
    if (router is None) != (path_map is None):
        raise GraphError("decision_turn needs both router and path_map, or neither")

    def latest(state):
        failures = state.get("failures") or {}
        return failures[next(reversed(failures))] if failures else None

    def body(state):
        failure = latest(state)
        if failure is not None and router is not None and router(state, failure) != "end":
            return {"status": {"phase": "decision", "terminal": None, "subsystem": subsystem,
                               "reason": failure["failure_kind"], "would_make_possible": None}}
        terminal = "escalate" if failure and failure["failure_kind"] == "ceiling_exceeded" else "decision_required"
        return {"status": {
            "phase": "decision", "terminal": terminal, "subsystem": subsystem,
            "reason": failure["failure_kind"] if failure else "no_failure_recorded",
            "would_make_possible": failure.get("would_make_possible") if failure else None}}

    def decide(state):
        failure = latest(state)
        return router(state, failure) if router is not None and failure is not None else "end"
    decide.__name__ = "decision_" + subsystem.replace(".", "_")
    declared = {**(path_map or {}), "end": END}
    return Node("decision_turn", body, then=route(decide, declared))


def board_sync(season_key: Callable, *, sync: Callable) -> Node:
    """Reveal/sync against the board journal as a keyed journal effect (the research board supplies ``sync``)."""
    def body(state):
        meta = _meta(state)
        key = season_key(state)
        where = invocation(meta, {"board": key})
        result = effect_ledger.call(meta["scope_root"], graph={"id": meta["graph_id"], "version": meta["version"]},
                                    path=where, kind="journal", identity={"board": key}, provisioning={},
                                    function=lambda: sync(state), drift=RUN_DRIFT.get())
        receipt = effect_ledger.latest(meta["scope_root"], where)
        return {"effects": {effect_ledger.digest(where): {"call_id": receipt["call_id"], "name": "board",
                                                          "result_sha256": effect_ledger.digest(result)}}}
    return Node("board", body)


def _outcome(final):
    status = (final or {}).get("status") or {}
    if status.get("terminal") is None:
        return "ok"
    return "held" if status["terminal"] in {"hold", "stopped"} else "failed"


def _invoke_child(compiled, child_input, key):
    final = compiled.invoke(child_input)
    status = (final or {}).get("status") or {}
    return {"results": {key: {"outcome": _outcome(final), "results": deepcopy((final or {}).get("results") or {}),
                              "status": deepcopy(status)}}}


def _substrate_graph(compiled):
    graph_id = getattr(compiled, SUBSTRATE_MARK, None)
    if not graph_id:
        raise GraphError("target is not a compiled substrate graph")
    return graph_id


def _view_keys(compiled):
    builder = compiled.builder
    view = builder.input_schema
    if view is None or view is builder.state_schema:
        raise GraphError("map target needs a graph-level input_schema (its role view, R7)")
    keys = set(getattr(view, "__annotations__", {}))
    if "meta" not in keys:
        raise GraphError("map target's input_schema must include meta")
    return keys


def subgraph(graph_id: str, ctx, *, project: Callable | None = None, key: str | None = None) -> Node:
    """A registered graph as a node; it checkpoints under the parent's thread (P3).

    The child's base channels stay private: it receives its own ``meta`` and the
    ``project(state)`` view, and returns one keyed write-once ``results`` entry.
    """
    from . import graph_substrate
    compiled = graph_substrate.build(graph_id, ctx, checkpointer=None)
    row = graph_registry.get(graph_id)

    def body(state):
        meta = _meta(state)
        node = effect_ledger._node_name() or graph_id
        child_meta = {"graph_id": graph_id, "version": row["version"], "instance": deepcopy(ctx.instance),
                      "scope_root": meta["scope_root"], "path": invocation(meta, {"node": node})}
        view = dict(project(state)) if project else {}
        _no_framework_channels(view, "subgraph view")
        return _invoke_child(compiled, {**view, "meta": child_meta}, key or node)
    body.__name__ = "subgraph_" + graph_id.replace(".", "_")
    return Node("subgraph", body)


def map_node(items: Callable, item_key: Callable, target, project: Callable, *, name: str,
             join: str = "all") -> tuple[Edge, Node]:
    """The only emitter of ``Send``: one validated packet per item into a substrate subgraph.

    ``project(state, item)`` builds the packet; a key outside the target's input view is
    refused before the ``Send`` (R7). The target's own handler contains an item's
    failure (R5c, N1); each item's outcome is ``ok``, ``failed`` or ``held`` in
    ``results[<item key>]``. Read the join through ``joined`` (sorted by item key).
    """
    from langgraph.types import Send
    if join != "all":
        raise GraphError("map join must be 'all'")
    graph_id = _substrate_graph(target)
    view = _view_keys(target)
    row = graph_registry.get(graph_id)

    def router(state):
        meta = _meta(state)
        packets = []
        for item in items(state):
            identifier = str(item_key(item))
            packet = dict(project(state, item))
            _no_framework_channels(packet, "map packet")
            extra = set(packet) - (view - {"meta"})
            if extra:
                raise GraphError(f"map packet keys {sorted(extra)} are outside the target's view")
            child_meta = {"graph_id": graph_id, "version": row["version"], "instance": deepcopy(meta.get("instance")),
                          "scope_root": meta["scope_root"],
                          "path": invocation(meta, {"map": name, "item": identifier})}
            packets.append(Send(name, {"map_item": identifier, "map_packet": {**packet, "meta": child_meta}}))
        return packets
    router.__name__ = "map_" + name
    edge = Edge(router, {name: name}, kind="map", target=name)

    def body(state):
        return _invoke_child(target, state["map_packet"], state["map_item"])
    body.__name__ = "map_" + name

    class Packet(TypedDict):
        map_item: str
        map_packet: dict
    return edge, Node("map", body, options={"input_schema": Packet})


def _no_framework_channels(value, what):
    found = sorted(set(value) & set(FRAMEWORK_CHANNELS))
    if found:
        raise GraphError(f"{what} cannot carry framework channel(s) {found}")


def joined(state):
    """``results`` sorted by item key: the order-invariant join (P2)."""
    results = state.get("results") or {}
    return [{"key": key, **results[key]} for key in sorted(results)]


def map_items(items, item_key: Callable, run: Callable, *, workers: int = 1) -> list[dict]:
    """``map`` semantics for a host loop outside a compiled graph (``cli_agent_host.answer_graph``).

    Each item runs independently: an exception is that item's ``failed`` outcome and the
    others still run. Results are sorted by item key, whatever the completion order, and
    the caller re-runs only items whose work is not yet done.
    """
    from concurrent.futures import ThreadPoolExecutor
    items = list(items)
    keys = [str(item_key(item)) for item in items]
    if len(keys) != len(set(keys)):
        raise GraphError("map item keys must be unique")
    if type(workers) is not int or not 1 <= workers <= 16:
        raise GraphError("map workers must be an integer from 1 to 16")

    def one(pair):
        key, item = pair
        try:
            return {"key": key, "outcome": "ok", "result": run(item)}
        except Exception as error:  # contained: one item's failure is data, not an abort
            return {"key": key, "outcome": "failed", "error": _plain(error)}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, zip(keys, items)))
    return sorted(results, key=lambda r: r["key"])


def join_sha256(results) -> str:
    """Order-invariant digest of a map join: item keys, outcomes and results (P2)."""
    return effect_ledger.digest([{"key": r["key"], "outcome": r["outcome"], "result": r.get("result")}
                                 for r in sorted(results, key=lambda r: r["key"])])


def handoff(source_key: str, roles, *, none: str, refuse: str = "decision_turn") -> Edge:
    """Route on the ``handoff`` field of a final record in ``results[source_key]`` (§4.8).

    A handoff is data: the handing-off role's ``finish`` has already run. A role outside
    ``roles`` (the registry row's roles) routes to ``refuse``.
    """
    roles = list(roles)

    def decide(state):
        record = ((state.get("results") or {}).get(source_key) or {})
        target = (record.get("handoff") or {}).get("role") if type(record.get("handoff")) is dict else None
        if target is None:
            return "none"
        return target if target in roles else "refuse"
    decide.__name__ = "handoff_" + source_key
    return route(decide, {**{r: r for r in roles}, "none": none, "refuse": refuse})


def rdj(gate_name: str, action: Callable, ctx=None) -> Node:
    """``rdj.case`` as a subgraph (registered by the decision journal); refuses until it is registered."""
    try:
        graph_registry.get("rdj.case")
    except graph_registry.RegistryError as exc:
        raise GraphError("rdj node needs the rdj.case graph") from exc
    node = subgraph("rdj.case", ctx)
    node.kind, node.gate = "rdj", gate_name
    return node


# ---- errors as decision turns (§1.8) -------------------------------------------------

def _failure_kind(error):
    names = {cls.__name__ for cls in type(error).__mro__}
    if isinstance(error, effect_ledger.NondeterministicRequest):
        return "nondeterministic_request"
    if isinstance(error, (effect_ledger.Ambiguous, AmbiguousCall)):
        return "ambiguous"
    if isinstance(error, effect_ledger.StopRequested):
        return "stop_requested"
    if isinstance(error, RecoveryHold) or "RecoveryHold" in names:
        return "recovery_hold"
    if isinstance(error, GateRefused):
        return "gate_refused"
    if isinstance(error, ControlFlowRefused):
        return "control_flow_refused"
    if "TransportRefusal" in names:
        return "transport_refusal"
    if "CeilingExceeded" in names:
        return "ceiling_exceeded"
    if isinstance(error, ResponseInvalid):
        return "response_invalid"
    return "exception"


def failure_record(state, node, error):
    kind = _failure_kind(error)
    base = {"failure_kind": kind, "node": node, "error_type": type(error).__name__,
            "message": str(error)[:2000], "call_id": getattr(error, "call_id", None),
            "missing": list(getattr(error, "missing", None) or []),
            "gate_errors": [_plain(e) for e in getattr(error, "errors", None) or []] if kind == "gate_refused" else [],
            "would_make_possible": getattr(error, "would_make_possible", None)}
    existing = state.get("failures") or {}
    stem = effect_ledger.digest(base)
    occurrence = sum(1 for v in existing.values() if v.get("stem") == stem)
    record = {**base, "schema_version": 1, "kind": "graph-failure", "stem": stem, "occurrence": occurrence}
    if kind == "exception":
        # A crash keeps its traceback (bounded) beside its class, so a FAIL names where it happened.
        import traceback
        record["traceback"] = "".join(traceback.format_exception(type(error), error, error.__traceback__))[-6000:]
    return effect_ledger.digest({"stem": stem, "occurrence": occurrence}), record


def _terminal(status, reason, would=None):
    return {"phase": "handler", "terminal": status, "reason": reason, "would_make_possible": would}


# Exceptions the default handler routed. On the pinned LangGraph, stream(subgraphs=True)
# re-raises a handled node error after the run completes (conformance probe S2); the
# runner swallows exactly these objects and nothing else.
_HANDLED: dict[int, BaseException] = {}
_HANDLED_LOCK = threading.Lock()


def was_handled(error, *, forget=True):
    with _HANDLED_LOCK:
        known = _HANDLED.get(id(error)) is error
        if known and forget:
            del _HANDLED[id(error)]
        return known


def forget_handled():
    with _HANDLED_LOCK:
        _HANDLED.clear()


def error_handler(node_names):
    """The builder's own handler; its ``goto`` is confined to the builder's
    ``decision_turn``, ``reconcile`` and ``hold`` (N4), at build and at run time."""
    from langgraph.errors import NodeError
    missing = [n for n in REQUIRED_NODES if n not in node_names]
    if missing:
        raise GraphError(f"builder needs its own {', '.join(missing)} node(s) (§1.8)")
    allowed = set(REQUIRED_NODES)

    def go(target, update):
        from langgraph.types import Command
        if target not in allowed or target not in node_names:
            raise GraphError(f"error handler goto {target!r} is outside its builder")
        return Command(goto=target, update=update)

    def handle(state, error: NodeError):
        with _HANDLED_LOCK:
            _HANDLED[id(error.error)] = error.error
        fid, record = failure_record(state, error.node, error.error)
        kind = record["failure_kind"]
        update = {"failures": {fid: record}}
        if kind == "ambiguous":
            return go("reconcile", update)
        if kind == "nondeterministic_request":
            return go("hold", {**update, "status": _terminal(
                "hold", "version_bump_required", "bump the graph or card version for the changed request")})
        if kind == "stop_requested":
            return go("hold", {**update, "status": _terminal("stopped", "stop_requested")})
        if kind == "recovery_hold":
            return go("hold", {**update, "status": _terminal(
                "hold", getattr(error.error, "reason", str(error.error)), record["would_make_possible"])})
        return go("decision_turn", update)

    handle.__annotations__["error"] = NodeError
    handle.__ravel_handler__ = True
    return handle


def reconcile_node() -> Node:
    """After an ambiguous effect: close it through the typed validator, else pause for evidence.

    The resume value is not used; ``ravel graph respond`` applies ``effect_ledger.reconcile``
    from its pinned evidence before resuming, and this node re-derives from the receipt.
    A closed effect re-enters the node that raised (declared through ``path_map``).
    """
    def target(state):
        open_failures = [f for f in (state.get("failures") or {}).values()
                         if f["failure_kind"] == "ambiguous" and f.get("call_id")]
        return open_failures[-1] if open_failures else None

    def body(state):
        from langgraph.types import interrupt as pause
        meta = _meta(state)
        latest = target(state)
        if latest is None:
            return {"status": _terminal("hold", "no_ambiguous_effect")}
        receipt = effect_ledger.read(meta["scope_root"], latest["call_id"]) or {}
        if receipt.get("status") in effect_ledger.OPEN:
            receipt = effect_ledger.auto_reconcile(meta["scope_root"], latest["call_id"]) or receipt
        if receipt.get("status") in effect_ledger.OPEN:
            pause({"kind": "reconcile_evidence", "schema_id": "reconcile_evidence", "graph_id": meta["graph_id"],
                   "path": receipt.get("path"), "node": effect_ledger._node_name(),
                   "payload": {"call_id": latest["call_id"], "failed_node": latest["node"]},
                   "payload_sha256": effect_ledger.digest({"call_id": latest["call_id"]}),
                   "approval_from_resume": False},
                  response_schema=graph_registry.response_schema("reconcile_evidence"))
            receipt = effect_ledger.read(meta["scope_root"], latest["call_id"]) or {}
        if receipt.get("status") in effect_ledger.OPEN:
            return {"status": _terminal("hold", "reconcile_required",
                                        f"reconcile {latest['call_id']} with pinned evidence")}
        if receipt.get("status") in {"completed", "reconciled"} or (
                receipt.get("status") == "failed" and receipt.get("reconciliation")):
            return {"status": {"phase": "reconciled", "terminal": None, "reason": receipt["status"],
                               "would_make_possible": None, "reenter": latest["node"]}}
        return {"status": _terminal("decision_required", "reconciled_effect_failed")}

    def decide(state):
        status = state.get("status") or {}
        return status.get("reenter") if status.get("phase") == "reconciled" else "end"
    decide.__name__ = "reconcile"
    return Node("interrupt", body, then=Edge(decide, "nodes"), interrupt_kind="reconcile_evidence")


reconcile = reconcile_node
