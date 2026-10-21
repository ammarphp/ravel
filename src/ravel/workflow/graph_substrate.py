"""The graph substrate: build, thread identity, locks, runner, events, stop and drain.

Every registered RAVEL graph runs here, in RAVEL's own process, against one local
checkpoint database per scope root (a run, campaign or case directory). LangGraph
schedules, checkpoints, pauses and drains; it never carries authority. Effects are
exactly-once through ``effect_ledger``; gates re-derive authority from files; resume
values are routing data. ``framework_values_are_scientific_authority`` is always false.

CLI: ``ravel graph run|status|stop|respond|events|list`` (and ``serve`` for the
detached runner).
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import stat
import subprocess
import sys
import threading
import time
from typing import Annotated, Any, Callable

from . import graph_environment  # noqa: F401  (strict msgpack before any LangGraph import)
from . import effect_ledger, graph_nodes, graph_registry
from .agent_graph import GraphError
from .state_io import atomic_json, file_lock, read_json

KERNEL_VERSION = 1      # bumped only by a deliberate change to checkpoint layout or kernel semantics
DB = "framework/graphs.sqlite"
STORE = "framework/store.sqlite"
EVENTS = "framework/events.jsonl"
PROCESSES = "agent-work/processes.json"
LOCKS = "framework/locks"
SCOPE_LOCK = effect_ledger.SCOPE_LOCK
HOLDER = "framework/locks/scope.json"
THREADS = "framework/threads"
STOP = effect_ledger.STOP
DEFAULT_MAX_STEPS = 500
STOP_POLL_SECONDS = 0.05
TERMINATE_GRACE_SECONDS = 5.0


class ScopeLocked(GraphError):
    """Another runner owns this scope root (one runner per scope, §1.5; P9)."""
    def __init__(self, message, holder=None):
        super().__init__(message)
        self.holder = holder


ThreadLocked = ScopeLocked


def _utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- environment and identity ----------------------------------------------------------

def environment():
    """Tracing off and strict msgpack on; refuse to run otherwise (CAP §2.6, §2.14; R4).

    Both strict-msgpack module flags are read when LangGraph is imported, so the
    entry points set the variable before any LangGraph import (``graph_nodes`` does
    it at its own import); setting it later leaves both flags false and is refused.
    """
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"
    from langgraph._internal import _serde
    from langgraph.checkpoint.serde import _msgpack
    if not (_msgpack.STRICT_MSGPACK_ENABLED and _serde.STRICT_MSGPACK_ENABLED):
        raise GraphError("strict msgpack is not active: LangGraph was imported before "
                         "LANGGRAPH_STRICT_MSGPACK=true was set")
    serde = strict_serializer()
    if serde._allowed_msgpack_modules is not None or serde.pickle_fallback:
        raise GraphError("strict msgpack deserialization is not active")
    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        if os.environ.get(name, "").lower() != "false":
            raise GraphError(f"{name} must be false")


def strict_serializer():
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    # Explicit allowlist (None = the built-in safe types only) and no pickle, whatever
    # the import order or environment (R4).
    return JsonPlusSerializer(allowed_msgpack_modules=None, pickle_fallback=False)


def execute_role_graph(root, graph_root, specification, host, *, prepared, workers):
    """Shared role dispatch for registered research nodes and their legacy adapter.

    The research service retains its preparation, worker custody and receipts.
    This boundary forwards the call without changing its result or exceptions.
    """
    from . import research_cycle
    return research_cycle.execute_graph(root, graph_root, specification, host,
                                        prepared=prepared, workers=workers)


def legacy_pause(payload):
    """Compatibility interrupt for an existing legacy research checkpoint.

    Registered graphs use typed interrupt nodes; legacy resume values remain data
    and are discarded by the original shared research node table.
    """
    from langgraph.types import interrupt
    interrupt(payload)


def identity():
    """``{kernel_version, versions}``: no module digests (those go into each receipt's framework_step)."""
    from . import langgraph_runtime
    return {"kernel_version": KERNEL_VERSION, "versions": langgraph_runtime.identity()["versions"]}


def closure(graph_id):
    """Sorted ``[(id, version)]`` of the graph and every registered subgraph it can reach."""
    seen, pending = {}, [graph_id]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        row = graph_registry.get(current)
        seen[current] = row["version"]
        for child in row["subgraphs"]:
            registered = graph_registry.get(child["id"])
            if registered["version"] != child["version"]:
                raise GraphError(f"{current} declares {child['id']} v{child['version']}; "
                                 f"the registry has v{registered['version']}")
            pending.append(child["id"])
    return sorted([gid, version] for gid, version in seen.items())


def thread_id(graph_id, instance):
    """sha256 of {graph_id, instance, closure, kernel}.

    A child version bump changes every parent thread containing it; a kernel fix that
    keeps ``KERNEL_VERSION`` changes none. Source digests are excluded on purpose (§1.5).
    """
    return effect_ledger.digest({"graph_id": graph_id, "instance": instance, "closure": closure(graph_id),
                                 "kernel": identity()})


# ---- persistence -------------------------------------------------------------------------

def _scope_root(value):
    root = Path(value).expanduser().absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise GraphError("scope root cannot traverse a symlink")
    root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise GraphError("scope root must be a directory")
    return root


def _regular(path):
    if path.is_symlink() or (path.exists() and not stat.S_ISREG(path.lstat().st_mode)):
        raise GraphError(f"{path.name} must be a regular file")
    if not path.exists():
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    return path


@contextmanager
def saver(scope_root):
    """The scope's one checkpoint database, hardened as langgraph_runtime.persistent."""
    from langgraph.checkpoint.sqlite import SqliteSaver
    root = _scope_root(scope_root)
    (root / "framework").mkdir(exist_ok=True)
    db = _regular(root / DB)
    connection = sqlite3.connect(str(db), check_same_thread=False)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        yield SqliteSaver(connection, serde=strict_serializer())
    finally:
        connection.close()


# ---- build -------------------------------------------------------------------------------

@dataclass
class BuildContext:
    scope_root: Path
    graph_id: str
    version: int
    instance: dict
    row: dict = field(default_factory=dict)
    node_runner: Callable | None = None
    extras: dict = field(default_factory=dict)


def _context(scope_root, graph_id, instance):
    row = graph_registry.get(graph_id)
    graph_registry.check_instance(row, instance)
    return BuildContext(scope_root=Path(scope_root), graph_id=graph_id, version=row["version"],
                        instance=deepcopy(instance), row=row)


def structure(builder):
    """Nodes, node metadata, static edges and declared path maps of a builder (§1.6)."""
    nodes = {name: spec.metadata for name, spec in builder.nodes.items() if not name.startswith("__")}
    edges = sorted([list(e) for e in builder.edges]
                   + [[sorted(starts), end] for starts, end in builder.waiting_edges], key=json.dumps)
    branches = {source: {name: (dict(spec.ends) if spec.ends is not None else None)
                         for name, spec in sorted(found.items())}
                for source, found in sorted(builder.branches.items())}
    return {"nodes": nodes, "edges": edges, "branches": branches}


def structure_sha256(builder):
    return effect_ledger.digest(structure(builder))


def finish(builder, graph_id, *, checkpointer=None, expected_structure=None):
    """Apply the substrate's checks and its own error handler to a builder, then compile.

    Refused: a node not built by a substrate factory; a
    conditional edge without a declared ``path_map`` or not made by ``route``/``map_node``;
    a per-node error handler; a builder without its own ``decision_turn``, ``reconcile``
    and ``hold``; an interrupt not followed by a gate; a gate that does not exit through
    its own ``gate_route``; a structure digest that differs from the registry row. Node
    bodies that return ``Command`` or write another kind's framework channel are refused
    at run time.
    """
    for source, edge in builder.__dict__.pop("_ravel_deferred", []):
        graph_nodes.connect(builder, source, edge, nodes=builder.nodes)
    names = {n for n in builder.nodes if not n.startswith("__")}
    for name in names:
        spec = builder.nodes[name]
        kind = (spec.metadata or {}).get("ravel_kind")
        if kind not in graph_nodes.KINDS:
            raise GraphError(f"node {name!r} was not built by a substrate node factory")
        if spec.error_handler_node is not None:
            raise GraphError(f"node {name!r} has its own error handler; the builder owns error handling (§1.8)")
    if any(builder.nodes[n].is_error_handler for n in builder.nodes):
        raise GraphError("error handlers are installed by the substrate only")
    for source, found in builder.branches.items():
        for name, spec in found.items():
            marker = getattr(getattr(spec.path, "func", None), graph_nodes.EDGE_MARK, None)
            if marker is None:
                raise GraphError(f"conditional edge {name!r} from {source!r} was not made by route or map_node")
            if spec.ends is None:
                raise GraphError(f"conditional edge {name!r} from {source!r} has no path_map")
    interrupts = builder.__dict__.get("_ravel_interrupts", {})
    for name in names:
        if builder.nodes[name].metadata.get("ravel_kind") != "interrupt" or \
                interrupts.get(name) in graph_nodes.UNGATED_INTERRUPTS:
            continue
        successors = [end for start, end in builder.edges if start == name]
        if (not successors or name in builder.branches
                or any(end not in names or builder.nodes[end].metadata.get("ravel_kind") != "gate"
                       for end in successors)):
            raise GraphError(f"interrupt node {name!r} must be followed by a gate node")
    for name in names:
        gate_name = builder.nodes[name].metadata.get("gate")
        if builder.nodes[name].metadata.get("ravel_kind") != "gate":
            continue
        exits = list(builder.branches.get(name, {}).values())
        if (any(start == name for start, _ in builder.edges) or len(exits) != 1
                or getattr(getattr(exits[0].path, "func", None), graph_nodes.GATE_MARK, None) != gate_name):
            raise GraphError(f"gate node {name!r} must exit through its own gate_route({gate_name!r}, ...)")
    for required, kind in (("decision_turn", "decision_turn"), ("reconcile", "interrupt"), ("hold", "hold")):
        if required not in names or builder.nodes[required].metadata.get("ravel_kind") != kind:
            raise GraphError(f"builder {graph_id} needs its own {required} node of kind {kind} (§1.8)")
    digest = structure_sha256(builder)
    if expected_structure is not None and digest != expected_structure:
        raise GraphError(f"graph {graph_id} structure {digest} differs from the registry row; "
                         "bump the version and record the new structure_sha256")
    builder.set_node_defaults(error_handler=graph_nodes.error_handler(names))
    compiled = builder.compile(checkpointer=checkpointer, name=graph_id)
    setattr(compiled, graph_nodes.SUBSTRATE_MARK, graph_id)
    compiled.structure_sha256 = digest
    return compiled


def build(graph_id, ctx, *, checkpointer=None):
    row = graph_registry.get(graph_id)
    builder = graph_registry.builder(row)(ctx)
    expected = row["structure_sha256"]
    if expected == graph_registry.PIN:
        expected = graph_registry.pin_structure(graph_id, structure_sha256(_deferred_view(builder)))
    return finish(builder, graph_id, checkpointer=checkpointer, expected_structure=expected)


def _deferred_view(builder):
    for source, edge in builder.__dict__.pop("_ravel_deferred", []):
        graph_nodes.connect(builder, source, edge, nodes=builder.nodes)
    return builder


def lint_graph(compiled):
    """Problems with the G8 node metadata of a compiled graph (empty when clean)."""
    problems = []
    for name, node in compiled.get_graph().nodes.items():
        if name.startswith("__"):
            continue
        metadata = node.metadata or {}
        if metadata.get("ravel_kind") not in graph_nodes.KINDS or not metadata.get("graph_id"):
            problems.append(f"{name}: missing ravel_kind/graph_id metadata")
    return problems


# ---- records -----------------------------------------------------------------------------

def _json_safe(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "id") and hasattr(value, "value"):
        return {"id": value.id, "value": _json_safe(value.value)}
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json"))
    return repr(value)


def _value_sha(value):
    return effect_ledger.digest(_json_safe(value))


def _receipt_ids(value):
    effects = value.get("effects") if type(value) is dict else None
    return sorted(e["call_id"] for e in (effects or {}).values() if type(e) is dict and e.get("call_id"))


def _redacted(graph_id, tid, part):
    """One line per stream event without any value: keys, digests and receipt ids (R12)."""
    kind, ns, data = part.get("type"), list(part.get("ns") or ()), part.get("data")
    base = {"type": kind, "ns": ns, "graph_id": graph_id, "thread_id": tid, "utc": _utc()}
    lines = []
    if kind == "updates" and type(data) is dict:
        for node, update in data.items():
            update = update if type(update) is dict else {"value": update}
            lines.append({**base, "task_id": None, "node": node, "keys_written": sorted(update),
                          "value_sha256": {k: _value_sha(v) for k, v in update.items()},
                          "receipt_ids": _receipt_ids(update)})
    elif kind == "tasks" and type(data) is dict:
        result = data.get("result")
        written = dict(result) if type(result) is dict else (
            {k: v for k, v in result} if type(result) in (list, tuple) and all(
                type(r) in (list, tuple) and len(r) == 2 for r in result) else {})
        digests = {k: _value_sha(v) for k, v in written.items()}
        if "input" in data:
            digests["__input__"] = _value_sha(data["input"])
        lines.append({**base, "task_id": data.get("id"), "node": data.get("name"), "keys_written": sorted(written),
                      "value_sha256": digests, "receipt_ids": _receipt_ids(written)})
    else:
        value = data if type(data) is dict else {"value": data}
        lines.append({**base, "task_id": None, "node": None, "keys_written": sorted(value),
                      "value_sha256": {k: _value_sha(v) for k, v in value.items()}, "receipt_ids": []})
    return lines


def _append_event(root, graph_id, tid, part):
    path = root / EVENTS
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for line in _redacted(graph_id, tid, part):
            stream.write(json.dumps(line, sort_keys=True, allow_nan=False) + "\n")


def _thread_path(root, tid):
    return root / THREADS / (tid + ".json")


def _write_thread(root, tid, **values):
    path = _thread_path(root, tid)
    with file_lock(root / THREADS / ".lock"):
        record = read_json(path) if path.exists() else {"schema_version": 1, "kind": "graph-thread",
                                                        "thread_id": tid}
        record.update(values, updated_utc=_utc())
        atomic_json(path, record)
    return record


def _register_process(root, entry):
    path = root / PROCESSES
    with file_lock(root / "agent-work" / "processes.lock"):
        registry = read_json(path) if path.exists() else {"schema_version": 1, "kind": "process-registry",
                                                          "processes": []}
        registry["processes"] = [p for p in registry["processes"] if p["id"] != entry["id"]] + [entry]
        atomic_json(path, registry)


def _update_process(root, identifier, **values):
    path = root / PROCESSES
    with file_lock(root / "agent-work" / "processes.lock"):
        if not path.exists():
            return
        registry = read_json(path)
        for entry in registry["processes"]:
            if entry["id"] == identifier:
                entry.update(values)
        atomic_json(path, registry)


def processes(scope_root):
    path = Path(scope_root) / PROCESSES
    return read_json(path)["processes"] if path.exists() else []


# ---- the scope runner lock ---------------------------------------------------------------

def holder(scope_root):
    path = Path(scope_root) / HOLDER
    return read_json(path) if path.exists() else None


@contextmanager
def scope_runner(root, graph_id, tid):
    """One runner per scope root for its whole life (§1.5).

    A second runner, a standalone child entry or another registered graph on the same
    scope is refused with the holder record, in this process (R11) or another. The
    runner epoch rises at each acquisition and is stamped into every reservation.
    """
    (root / LOCKS).mkdir(parents=True, exist_ok=True)
    try:
        with file_lock(root / SCOPE_LOCK, blocking=False), effect_ledger.holding_scope(root):
            current = effect_ledger.bump_epoch(root, "runner")
            record = {"schema_version": 1, "kind": "graph-scope-holder", "pid": os.getpid(),
                      "runner_epoch": current["runner"], "graph_id": graph_id, "thread_id": tid,
                      "acquired_utc": _utc(), "released_utc": None}
            atomic_json(root / HOLDER, record)
            try:
                yield record
            finally:
                atomic_json(root / HOLDER, {**record, "released_utc": _utc()})
    except ValueError as exc:
        if "another process owns" not in str(exc):
            raise
        found = holder(root)
        raise ScopeLocked(f"scope {root} is held by runner {json.dumps(found, sort_keys=True)}; "
                          f"drain it with: ravel graph stop --scope-root {root} --reason <why>", found) from None


# ---- controller-owned scopes ---------------------------------------------------------------

def controller_scope(scope_root):
    """The run id when a controller run owns this scope (its store's graph scope or its run directory)."""
    from ..controller.store import controller_owned
    return controller_owned(scope_root)


def refuse_controller_switches(scope_root, *, clear_stop=False, gate_check=None, gate_providers=None):
    """Refuse, for a controller-owned scope, the switches its run never takes from a caller.

    ``--clear-stop`` (SW05): a controller run's stop is cleared by the operator or the physicist through
    the authority service, never as a side effect of continuing. The gate seams (SW30): ``gate_check``,
    ``gate_providers``, the ``GATE_CHECK``/``GATE_PROVIDERS`` context variables and the machine lease's
    ``_LOCATION`` substitute decisions; they are refused unless the test harness enabled them.
    """
    owner = controller_scope(scope_root)
    if clear_stop and owner is not None:
        raise GraphError(f"--clear-stop is refused for the controller-owned run {owner}; the operator "
                         "releases a stop with `ravel operator resume`, the physicist at the controller's terminal")
    seams = [name for name, value in (("gate_check", gate_check), ("gate_providers", gate_providers),
                                      ("GATE_CHECK", graph_nodes.GATE_CHECK.get()),
                                      ("GATE_PROVIDERS", graph_nodes.GATE_PROVIDERS.get())) if value is not None]
    from . import machine_lease
    if getattr(machine_lease, "_LOCATION", None) is not None:
        seams.append("machine_lease._LOCATION")
    if seams:
        from ..controller.testing import SeamRefused, refuse_for_controller
        try:
            refuse_for_controller("the in-process seam(s) " + ", ".join(seams), owned=owner is not None)
        except SeamRefused as exc:
            raise GraphError(str(exc)) from None
    return owner


# ---- runner ------------------------------------------------------------------------------

_CONTROLS: list = []


def _watch_stop(root, control, done):
    while not done.wait(STOP_POLL_SECONDS):
        if (root / STOP).exists():
            control.request_drain("stop_requested")
            return


def _observation(root, row, instance, tid, snapshot, terminal, drift=()):
    status = (snapshot.values or {}).get("status") or {}
    if terminal is None and status.get("terminal"):
        terminal = {"status": status["terminal"], "reason": status.get("reason"),
                    "would_make_possible": status.get("would_make_possible")}
    interrupts = [{"id": p.id, "kind": (p.value or {}).get("kind") if isinstance(p.value, dict) else None,
                   "schema_id": (p.value or {}).get("schema_id") if isinstance(p.value, dict) else None,
                   "payload": _json_safe(p.value)} for p in snapshot.interrupts]
    mine = [r for r in effect_ledger.receipts(root) if r.get("status") != "superseded"
            and ((r.get("framework_step") or {}).get("thread_id") == tid
                 or any((u.get("framework_step") or {}).get("thread_id") == tid for u in r.get("reuses") or ()))]
    tally = {s: sum(1 for r in mine if r["status"] == s) for s in ("completed", "started", "ambiguous", "reserving")}
    return {"graph_id": row["id"], "version": row["version"], "instance": deepcopy(instance), "thread_id": tid,
            "checkpoint_id": (snapshot.config or {}).get("configurable", {}).get("checkpoint_id"),
            "next": list(snapshot.next), "interrupts": interrupts, "terminal": terminal,
            "effects": tally, "provisioning_drift": list(drift),
            "framework_values_are_scientific_authority": False}


def run(scope_root, graph_id, instance, *, input=None, respond=None, workers=None, detach=False,
        max_steps=None, gate_check=None, gate_providers=None, clear_stop=False, _reconciliations=()):
    """Start or continue the thread for (graph, instance, closure, kernel); return an observation."""
    environment()
    if input is not None:
        if type(input) is not dict:
            raise GraphError("run input must be a JSON object")
        forged = sorted(set(input) & set(graph_nodes.FRAMEWORK_CHANNELS))
        if forged:
            raise GraphError(f"run input cannot carry framework channel(s) {forged}")
    location = Path(scope_root).expanduser().absolute()
    refuse_controller_switches(location, clear_stop=clear_stop, gate_check=gate_check, gate_providers=gate_providers)
    created = not location.exists() or (location.is_dir() and not location.is_symlink() and not any(location.iterdir()))
    root = _scope_root(scope_root)
    from . import gate_wiring
    if created:
        # A scope this call creates gets its steering journal; an existing one keeps its custody.
        gate_wiring.initialize_steering(root, route='graph-scope')
    allowed, reason = gate_wiring.dispatch_permitted(root, (instance or {}).get("node_id"))
    if not allowed:
        raise GraphError(reason)
    ctx = _context(root, graph_id, instance)
    tid = thread_id(graph_id, instance)
    if workers is not None and (type(workers) is not int or not 1 <= workers <= 16):
        raise GraphError("workers must be an integer in [1, 16]")
    if clear_stop:
        (root / STOP).unlink(missing_ok=True)
    if detach:
        with gate_wiring.steering_dispatch(root, (instance or {}).get("node_id")):
            return _detach(root, graph_id, instance, input=input, workers=workers, max_steps=max_steps)
    with scope_runner(root, graph_id, tid):
        effect_ledger.recover(root)
        for value in _reconciliations:
            effect_ledger.reconcile(root, value["call_id"], outcome=value["outcome"], evidence=value["evidence"],
                                    reason=value["reason"], result=value.get("result"))
        return _invoke(root, ctx, tid, input=input, respond=respond, workers=workers,
                       max_steps=max_steps, gate_check=gate_check, gate_providers=gate_providers)


def _invoke(root, ctx, tid, *, input, respond, workers, max_steps, gate_check, gate_providers):
    from langgraph.errors import GraphDrained, GraphRecursionError
    from langgraph.runtime import RunControl
    from langgraph.types import Command
    row = ctx.row
    before = identity()["versions"]
    with saver(root) as checkpointer:
        app = build(ctx.graph_id, ctx, checkpointer=checkpointer)
        # One executor slot is taken by the stream consumer when subgraphs or custom
        # events stream; max_concurrency=1 deadlocks on the pinned version (probe S1).
        config = {"configurable": {"thread_id": tid}, "recursion_limit": max_steps or DEFAULT_MAX_STEPS,
                  "max_concurrency": (workers or 1) + 1}
        snapshot = app.get_state(config)
        if respond is not None:
            if not snapshot.created_at:
                raise GraphError("cannot respond to a thread with no checkpoint")
            value = Command(resume=respond)
        elif snapshot.created_at:
            value = None
        else:
            value = {**deepcopy(input or {}), "meta": {"graph_id": ctx.graph_id, "version": ctx.version,
                                                       "instance": deepcopy(ctx.instance), "scope_root": str(root),
                                                       "path": None}}
        if (root / STOP).exists():
            _write_thread(root, tid, graph_id=ctx.graph_id, version=ctx.version, instance=ctx.instance,
                          state="stopped", terminal={"status": "stopped", "reason": "stop_requested",
                                                     "would_make_possible": "ravel graph run --clear-stop"})
            return {**_observation(root, row, ctx.instance, tid, snapshot, None),
                    "terminal": {"status": "stopped", "reason": "stop_requested",
                                 "would_make_possible": "ravel graph run --clear-stop"}}
        _write_thread(root, tid, graph_id=ctx.graph_id, version=ctx.version, instance=ctx.instance,
                      state="running", pid=os.getpid(), terminal=None)
        control, done, drift = RunControl(), threading.Event(), []
        _CONTROLS.append(control)
        watcher = threading.Thread(target=_watch_stop, args=(root, control, done), daemon=True)
        watcher.start()
        terminal = None
        try:
            with graph_nodes.gate_checker(gate_check, control, gate_providers, drift):
                for part in app.stream(value, config, stream_mode=["updates", "custom", "tasks"],
                                       subgraphs=True, version="v2", durability="sync", control=control):
                    _append_event(root, ctx.graph_id, tid, part)
                    if part.get("type") == "updates":
                        for node, update in (part.get("data") or {}).items():
                            if node.startswith("__"):
                                continue
                            problems = graph_nodes.lint_state(update) if isinstance(update, dict) else []
                            if problems:
                                control.request_drain("state_not_json_safe")
                                terminal = {"status": "hold", "reason": "state_not_json_safe",
                                            "would_make_possible": "; ".join(problems)[:2000]}
        except GraphRecursionError:
            terminal = {"status": "budget_exhausted", "reason": "recursion_limit",
                        "would_make_possible": "raise the step budget or add a RemainingSteps guard"}
        except GraphDrained as exc:
            if terminal is None:
                terminal = {"status": "stopped", "reason": exc.reason,
                            "would_make_possible": "ravel graph run --clear-stop"}
        except Exception as exc:
            # Probe S2: the stream re-raises an error the default handler already routed.
            if not graph_nodes.was_handled(exc):
                raise
        finally:
            done.set()
            _CONTROLS.remove(control)
        snapshot = app.get_state(config)
        observation = _observation(root, row, ctx.instance, tid, snapshot, terminal, drift)
    state = ("interrupted" if observation["interrupts"] else
             observation["terminal"]["status"] if observation["terminal"] else
             "completed" if not observation["next"] else "paused")
    _write_thread(root, tid, state=state, terminal=observation["terminal"], pid=None,
                  checkpoint_id=observation["checkpoint_id"])
    if identity()["versions"] != before:
        raise GraphError("graph framework identity changed during execution")
    return observation


def _detach(root, graph_id, instance, *, input, workers, max_steps):
    argv = [sys.executable, "-m", "ravel.workflow.graph_substrate", "serve", "--scope-root", str(root),
            "--graph", graph_id, "--instance", json.dumps(instance, sort_keys=True)]
    if input is not None:
        argv += ["--input", json.dumps(input, sort_keys=True)]
    if workers is not None:
        argv += ["--workers", str(workers)]
    if max_steps is not None:
        argv += ["--max-steps", str(max_steps)]
    tid = thread_id(graph_id, instance)
    log = root / "framework" / f"runner-{tid[:16]}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "LANGGRAPH_STRICT_MSGPACK": "true", "LANGSMITH_TRACING": "false",
           "LANGCHAIN_TRACING_V2": "false"}
    with log.open("ab") as stream:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                                   start_new_session=True, env=env)
    entry = {"id": f"graph-runner-{process.pid}", "pid": process.pid, "pgid": process.pid, "argv": argv,
             "role": "graph-runner", "thread_id": tid, "graph_id": graph_id, "started_utc": _utc(),
             "state": "running", "log": str(log.relative_to(root))}
    _register_process(root, entry)
    return {"graph_id": graph_id, "thread_id": tid, "detached": {"pid": process.pid, "pgid": process.pid,
                                                                  "process_id": entry["id"]},
            "framework_values_are_scientific_authority": False}


def _serve(scope_root, graph_id, instance, *, input, workers, max_steps):
    def drain(signum, frame):
        for control in list(_CONTROLS):
            control.request_drain("terminated")
    signal.signal(signal.SIGTERM, drain)
    root = _scope_root(scope_root)
    identifier = f"graph-runner-{os.getpid()}"
    try:
        observation = run(root, graph_id, instance, input=input, workers=workers, max_steps=max_steps)
        print(json.dumps(observation, sort_keys=True))
        return 0
    finally:
        _update_process(root, identifier, state="exited", ended_utc=_utc())


# ---- respond, status, stop, events -------------------------------------------------------

def _pending(scope_root, graph_id, instance):
    root = _scope_root(scope_root)
    from . import gate_wiring
    allowed, reason = gate_wiring.dispatch_permitted(root, (instance or {}).get("node_id"))
    if not allowed:
        raise GraphError(reason)
    ctx = _context(root, graph_id, instance)
    tid = thread_id(graph_id, instance)
    with saver(root) as checkpointer:
        app = build(graph_id, ctx, checkpointer=checkpointer)
        snapshot = app.get_state({"configurable": {"thread_id": tid}})
    return root, tid, snapshot


def respond(scope_root, graph_id, instance, responses, *, workers=None, gate_check=None, gate_providers=None,
            clear_stop=False):
    """Validate every value against its schema before any resume, then resume by id map (Q4).

    A ``reconcile_evidence`` response may name only the effect its interrupt names; it is
    applied through ``effect_ledger.reconcile`` from its pinned evidence inside the scope
    runner lock, before the resume; the graph then re-derives the outcome from the
    receipt. Other responses are ledgered as data by their interrupt node and never pass
    a gate. A stopped scope refuses responses unless ``clear_stop``.
    """
    environment()
    if type(responses) is not dict or not responses:
        raise GraphError("responses must be a non-empty map of interrupt id to value")
    refuse_controller_switches(Path(scope_root).expanduser().absolute(), clear_stop=clear_stop,
                               gate_check=gate_check, gate_providers=gate_providers)
    if (Path(scope_root) / STOP).exists() and not clear_stop:
        raise GraphError("scope is stopped; answer with --clear-stop to resume, or clear the stop first")
    root, tid, snapshot = _pending(scope_root, graph_id, instance)
    pending = {p.id: p.value for p in snapshot.interrupts}
    if not pending:
        raise GraphError("thread has no pending interrupt")
    problems = []
    for identifier, value in responses.items():
        if identifier not in pending:
            problems.append(f"{identifier}: not a pending interrupt")
            continue
        schema_id = pending[identifier].get("schema_id") if isinstance(pending[identifier], dict) else None
        if schema_id is None:
            problems.append(f"{identifier}: interrupt has no response schema")
            continue
        errors = graph_registry.response_errors(schema_id, value)
        problems.extend(f"{identifier}: {e}" for e in errors)
        if schema_id == "reconcile_evidence" and not errors:
            named = ((pending[identifier].get("payload") or {}).get("call_id"))
            if value["call_id"] != named:
                problems.append(f"{identifier}: reconcile_evidence names a different effect than its interrupt")
    if problems:
        raise GraphError("responses refused before resume: " + "; ".join(problems))
    reconciliations = [deepcopy(value) for identifier, value in responses.items()
                       if pending[identifier].get("schema_id") == "reconcile_evidence"]
    return run(root, graph_id, instance, respond=dict(responses), workers=workers, gate_check=gate_check,
               gate_providers=gate_providers, clear_stop=clear_stop, _reconciliations=reconciliations)


def _scope_held(root):
    path = root / SCOPE_LOCK
    if not path.exists():
        return False
    try:
        with file_lock(path, blocking=False):
            return False
    except ValueError:
        return True


def status(scope_root, graph_id=None, instance=None):
    root = _scope_root(scope_root)
    stop = read_json(root / STOP) if (root / STOP).exists() else None
    held = _scope_held(root)
    current = holder(root) if held else None
    if graph_id is None:
        threads = [read_json(p) for p in sorted((root / THREADS).glob("*.json"))] if (root / THREADS).is_dir() else []
        for record in threads:
            record["running"] = bool(current and current["thread_id"] == record["thread_id"])
        return {"scope_root": str(root), "stop": stop, "holder": current, "threads": threads,
                "processes": processes(root), "framework_values_are_scientific_authority": False}
    _, tid, snapshot = _pending(root, graph_id, instance)
    record = read_json(_thread_path(root, tid)) if _thread_path(root, tid).exists() else {}
    observation = _observation(root, graph_registry.get(graph_id), instance, tid, snapshot,
                               record.get("terminal"))
    running = bool(current and current["thread_id"] == tid)
    state = ("running" if running else "stopped" if stop is not None and observation["next"] else
             record.get("state") or ("absent" if not snapshot.created_at else "paused"))
    return {**observation, "state": state, "stop": stop, "running": running, "holder": current}


def stop(scope_root, *, reason, now=False, pause=None):
    """Drain: no new superstep is dispatched; running tasks finish and receipt their effects.

    ``now`` also raises the cancellation epoch, terminates the registered process groups
    (only those) and verifies them gone. A steering pause names itself in the record.
    """
    root = _scope_root(scope_root)
    if type(reason) is not str or not reason.strip():
        raise GraphError("stop reason required")
    atomic_json(root / STOP, {"schema_version": 1, "kind": "graph-stop", "reason": reason, "now": bool(now),
                              "requested_utc": _utc(), **({"steering_pause": pause} if pause is not None else {})})
    terminated, cancellation = [], None
    if now:
        cancellation = effect_ledger.bump_epoch(root, "cancellation")["cancellation"]
        for entry in processes(root):
            if entry.get("state") != "running":
                # A worker publishes its child's terminal custody before its own
                # supervisor finishes shutting down. Verify the registered groups
                # even if that publication already labels the public entry exited.
                if (entry.get("role") != "worker-supervisor"
                        or not any(_group_alive(group) for group in (entry["pgid"], entry.get("child_pgid"))
                                   if group is not None)):
                    continue
                terminated.append(_verify_terminal_worker(entry))
                continue
            terminated.append(_terminate(root, entry))
    return {"scope_root": str(root), "stop": read_json(root / STOP), "terminated": terminated,
            "cancellation_epoch": cancellation, "all_gone": all(t["gone"] for t in terminated)}


def _group_alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _owned(pid, pgid):
    """The registered group still belongs to the registered process (no pgid reuse)."""
    if pid is None:
        return _group_alive(pgid)
    try:
        return os.getpgid(pid) == pgid
    except ProcessLookupError:
        return False


def _verify_terminal_worker(entry):
    """Wait for shutdown without signalling identities from a historical exited entry.

    Such a group may already have been reused. If it remains visible at the bound,
    report unverified disappearance; do not turn the old entry back into kill authority.
    """
    groups = [(entry["pid"], entry["pgid"])]
    if entry.get("child_pgid") is not None:
        groups.append((entry.get("child_pid"), entry["child_pgid"]))
    deadline = time.monotonic() + TERMINATE_GRACE_SECONDS
    while any(_group_alive(group) for _, group in groups) and time.monotonic() < deadline:
        for pid, _ in groups:
            if pid is not None:
                _reap(pid)
        time.sleep(0.05)
    return {"id": entry["id"], "pgid": entry["pgid"], "child_pgid": entry.get("child_pgid"),
            "signal": None, "gone": not any(_group_alive(group) for _, group in groups)}


def _terminate(root, entry):
    """Terminate the entry's ``pgid`` and, when registered, its ``child_pgid`` (a worker child
    in its own session); verify both gone."""
    pgid, child = entry["pgid"], entry.get("child_pgid")
    groups = [(entry["pid"], pgid)] + ([(entry.get("child_pid"), child)] if child is not None else [])
    pids = [pid for pid, _ in groups if pid is not None]
    live = [group for pid, group in groups if _owned(pid, group)]
    sent = None
    for name in ("SIGTERM", "SIGKILL"):
        live = [group for group in live if _group_alive(group)]
        if not live:
            break
        sent = name
        for group in live:
            try:
                os.killpg(group, getattr(signal, name))
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + TERMINATE_GRACE_SECONDS
        while any(_group_alive(group) for group in live) and time.monotonic() < deadline:
            for pid in pids:
                _reap(pid)
            time.sleep(0.05)
    gone = not any(_group_alive(group) for _, group in groups)
    state = "exited" if sent is None and gone else "terminated" if gone else "running"
    _update_process(root, entry["id"], state=state, ended_utc=_utc(), signal=sent)
    return {"id": entry["id"], "pgid": pgid, "child_pgid": child, "signal": sent, "gone": gone}


def _reap(pid):
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass


def events(scope_root, *, thread=None, types=None):
    path = Path(scope_root) / EVENTS
    if not path.exists():
        return []
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if thread is not None and not event["thread_id"].startswith(thread):
            continue
        if types and event["type"] not in types:
            continue
        found.append(event)
    return found


# ---- agent_graph JSON specs -------------------------------------------------------------

def compile_spec(spec, host, ctx):
    """An ``agent_graph`` JSON spec as a substrate StateGraph (the broker calls this from execute).

    Each spec node becomes a substrate node whose body is ``ctx.node_runner(node_id, host)``;
    dependencies become AND edges. The broker supplies the runner (and the ``agent`` kind through the tool gate).
    """
    from typing import TypedDict
    from langgraph.graph import END, START, StateGraph
    from . import agent_graph
    canonical = agent_graph.validate(spec)
    graph_id = "agent_graph:" + canonical["graph_id"]
    runner = getattr(ctx, "node_runner", None)

    class SpecState(graph_nodes.BaseState, total=False):
        completed: Annotated[dict, graph_nodes.write_once]

    builder = StateGraph(SpecState)
    labels = {n["id"]: "node_" + str(i) for i, n in enumerate(canonical["nodes"])}

    def make(node_id):
        def body(state):
            if runner is None:
                raise GraphError("compile_spec needs ctx.node_runner (supplied by the agent_graph owner)")
            reference = runner(node_id, host)
            return {"completed": {node_id: reference}} if reference is not None else {}
        return body

    for node in canonical["nodes"]:
        graph_nodes.add(builder, labels[node["id"]], graph_nodes.Node("effect", make(node["id"]), role=node["role"]),
                        graph_id=graph_id)
    graph_nodes.add(builder, "decision_turn", graph_nodes.decision_turn("agent_graph"), graph_id=graph_id)
    graph_nodes.add(builder, "reconcile", graph_nodes.reconcile_node(), graph_id=graph_id)
    graph_nodes.add(builder, "hold", graph_nodes.hold("agent_graph_hold"), graph_id=graph_id)
    successors = set()
    for node in canonical["nodes"]:
        if node["depends_on"]:
            builder.add_edge([labels[p] for p in node["depends_on"]], labels[node["id"]])
            successors.update(node["depends_on"])
        else:
            builder.add_edge(START, labels[node["id"]])
    for node in canonical["nodes"]:
        if node["id"] not in successors:
            builder.add_edge(labels[node["id"]], END)
    return finish(builder, graph_id, checkpointer=getattr(ctx, "checkpointer", None))


# ---- the registered kernel self-test graph ----------------------------------------------

def selftest(ctx):
    """``substrate.selftest``: a guard, ``steps`` journal effects and an optional typed interrupt
    followed by a routed gate (it refuses, fail-closed, while ``decision_gate`` is absent).

    The structure does not depend on the instance, so one ``structure_sha256`` covers it.
    """
    from langgraph.graph import START, StateGraph

    class State(graph_nodes.BaseState, total=False):
        step: int
        tally: Annotated[dict, graph_nodes.write_once]

    steps, delay, ask = int(ctx.instance["steps"]), int(ctx.instance["delay_ms"]), bool(ctx.instance["ask"])
    builder = StateGraph(State)

    def act(state, identity):
        time.sleep(delay / 1000.0)
        marker = Path(state["meta"]["scope_root"]) / "selftest" / f"step-{identity['step']}.json"
        atomic_json(marker, {"schema_version": 1, "kind": "selftest-effect", "step": identity["step"]})
        return {"step": identity["step"]}

    add = lambda name, node: graph_nodes.add(builder, name, node, graph_id=ctx.graph_id)
    add("guard", graph_nodes.guard(lambda s: "go" if s.get("step", 0) < steps else "exhausted",
                                   routes={"go": "act", "exhausted": "finale"}))
    add("act", graph_nodes.effect(
        "selftest.act", kind="journal", run=act, segment=lambda s: {"step": s.get("step", 0)},
        identity=lambda s: {"label": ctx.instance["label"], "step": s.get("step", 0)},
        to_state=lambda s, r: {"step": r["step"] + 1, "tally": {str(r["step"]): True}}))
    add("finale", graph_nodes.guard(lambda s: "go" if ask else "exhausted", routes={"go": "ask", "exhausted": "done"}))
    add("ask", graph_nodes.interrupt("requirement_clarification", {"question": "synthetic clarification"}))
    add("check", graph_nodes.gate("final_task", lambda s: {"kind": "selftest", "digest": effect_ledger.digest(
        s.get("responses") or {}), "summary": "selftest", "pins": []}))
    add("done", graph_nodes.hold("selftest_complete"))
    add("refused", graph_nodes.hold("selftest_gate_refused", "the final_task gate passes (decision_gate)"))
    add("decision_turn", graph_nodes.decision_turn("selftest"))
    add("reconcile", graph_nodes.reconcile_node())
    add("hold", graph_nodes.hold("selftest_hold"))
    builder.add_edge(START, "guard")
    builder.add_edge("act", "guard")
    builder.add_edge("ask", "check")
    graph_nodes.connect(builder, "check", graph_nodes.gate_route("final_task", passed="done", refused="refused"))
    return builder


# ---- CLI ---------------------------------------------------------------------------------

def _instance_arg(text):
    value = json.loads(text)
    if type(value) is not dict:
        raise argparse.ArgumentTypeError("instance must be a JSON object")
    return value


def _parser():
    ap = argparse.ArgumentParser(prog="ravel graph", description="run, observe, answer and stop registered graphs")
    sub = ap.add_subparsers(dest="action", required=True)
    for name, text in (("run", "start or continue a graph thread"), ("status", "observe threads or one thread"),
                       ("respond", "answer pending interrupts (validated before resume)"),
                       ("serve", "detached runner process (internal)")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--scope-root", type=Path, required=True)
        p.add_argument("--graph", required=name != "status")
        p.add_argument("--instance", type=_instance_arg, required=name != "status")
        if name in {"run", "serve"}:
            p.add_argument("--input", type=_instance_arg)
            p.add_argument("--workers", type=int)
            p.add_argument("--max-steps", type=int)
        if name == "run":
            p.add_argument("--detach", action="store_true")
        if name in {"run", "respond"}:
            p.add_argument("--clear-stop", action="store_true")
        if name == "respond":
            p.add_argument("--responses", type=_instance_arg, required=True,
                           help="JSON object: interrupt id to response value")
        if name == "status":
            p.add_argument("--follow", action="store_true", help="poll until the thread is no longer running")
            p.add_argument("--interval", type=float, default=2.0)
    p = sub.add_parser("stop", help="drain the scope; --now also terminates registered process groups")
    p.add_argument("--scope-root", type=Path, required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--now", action="store_true")
    p = sub.add_parser("events", help="print observation events")
    p.add_argument("--scope-root", type=Path, required=True)
    p.add_argument("--thread")
    p.add_argument("--type", action="append", choices=["updates", "custom", "tasks", "messages"])
    sub.add_parser("list", help="list registered graphs")
    return ap


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.action == "list":
            result = {"graphs": graph_registry.load(), "response_schemas": graph_registry.schema_ids()}
        elif args.action == "run":
            result = run(args.scope_root, args.graph, args.instance, input=args.input, workers=args.workers,
                         detach=args.detach, max_steps=args.max_steps, clear_stop=args.clear_stop)
        elif args.action == "serve":
            return _serve(args.scope_root, args.graph, args.instance, input=args.input, workers=args.workers,
                          max_steps=args.max_steps)
        elif args.action == "respond":
            result = respond(args.scope_root, args.graph, args.instance, args.responses, clear_stop=args.clear_stop)
        elif args.action == "status":
            if (args.graph is None) != (args.instance is None):
                raise GraphError("status needs both --graph and --instance, or neither")
            result = status(args.scope_root, args.graph, args.instance)
            while args.follow and args.graph and result["running"]:
                time.sleep(max(0.1, args.interval))
                result = status(args.scope_root, args.graph, args.instance)
        elif args.action == "stop":
            result = stop(args.scope_root, reason=args.reason, now=args.now)
        else:
            for event in events(args.scope_root, thread=args.thread, types=args.type):
                print(json.dumps(event, sort_keys=True))
            return 0
    except (OSError, ValueError) as exc:
        print(f"ravel graph: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
