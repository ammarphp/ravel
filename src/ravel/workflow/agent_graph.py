"""Bounded host-executed advisory agent graphs with immutable call receipts.

Graph checkpoints record orchestration, never CHECK-IN approval, scientific
acceptance or process success. Hosts must use the existing Ravel authority for
physics effects. Started calls without an outcome are ambiguous, not retryable.
No OS sandbox or actor authentication is claimed by this module.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import time
import uuid

from .state_io import atomic_json, file_lock, read_json

ROLES = {"proposer", "critic", "improver", "verifier", "synthesizer", "designer", "executor",
         "rdj_edge_reviewer", "rdj_critic", "rdj_verifier"}  # rdj_*: decision-justification roles (rdj_loop)
BLIND_GRAPH_ROLES = {"critic", "verifier", "rdj_critic", "rdj_verifier"}
# Planning roles a host may deliver from its own working context. The receipt
# records the actual isolation; review roles keep the fresh-context requirement.
HOST_CONTEXT_ROLES = {"proposer", "improver", "designer"}
HOST_DESIGNED = "host-designed, not independent"
# A released external reservation returns its node to pending. The bound keeps
# a stuck node recoverable without permitting unbounded re-preparation.
MAX_EXTERNAL_RELEASES = 3
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
STATE = "graph_state.json"
SPEC = "graph_spec.json"
LIMITATION = ("ADVISORY scheduling only. No approval, physics validity, actor authentication, "
              "OS sandbox or exactly-once guarantee for unreceipted external effects.")


class GraphError(ValueError):
    """An invalid or stale graph cannot become current evidence."""


class AmbiguousCall(GraphError):
    """A dispatched call has no trustworthy outcome; reconcile it explicitly."""
    ambiguous = True
    retryable = False


class CallFailure(GraphError):
    retryable = False


class ReceiptedFailure(CallFailure):
    """A dispatched action failed with a durable typed receipt (``receipt``, status failed).

    Only this, or an exception with ``not_dispatched``, lets a host call that raised
    close as failed; every other raise after dispatch leaves the call ambiguous.
    """
    def __init__(self, message, receipt, *, retryable=False):
        super().__init__(message)
        if type(receipt) is not dict or receipt.get("status") != "failed":
            raise GraphError("a failure receipt must be a JSON object with status failed")
        self.receipt = receipt
        self.retryable = retryable


class Cancelled(GraphError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _keys(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise GraphError(f"{label} requires exactly {sorted(keys)}")


def _text(value, label, maximum=65536):
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise GraphError(f"invalid {label}")


def _id(value, label):
    if type(value) is not str or not ID.fullmatch(value):
        raise GraphError(f"invalid {label}")


def _integer(value, label, minimum=0, maximum=10000000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise GraphError(f"{label} must be an integer in [{minimum}, {maximum}]")


def _path(value):
    _text(value, "path", 4096)
    path = Path(value).expanduser().absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise GraphError("graph paths cannot traverse symlinks")
    return path.resolve()


def _pin(pin):
    _keys(pin, {"id", "path", "sha256", *({'restricted'} if 'restricted' in pin else set())}, "artifact pin")
    if 'restricted' in pin and type(pin['restricted']) is not bool:
        raise GraphError('input pin restricted must be boolean')
    _id(pin["id"], "artifact ID")
    if type(pin["sha256"]) is not str or not SHA.fullmatch(pin["sha256"]):
        raise GraphError("invalid artifact digest")
    return {**pin, "path": str(_path(pin["path"]))}


def _team_shape(spec):
    """Validate an opt-in investigation arm without changing any review gate.

    The graph remains an advisory scheduler. Required decision-gate reviewers
    still run independently of this investigator/consultation schedule.
    """
    shape = spec.get('team_shape', {'policy': 'current'})
    if type(shape) is not dict:
        raise GraphError('team shape must be an explicit policy object')
    if shape.get('policy') == 'current':
        _keys(shape, {'policy'}, 'current team shape')
        return shape
    _keys(shape, {'policy', 'investigator', 'consultations', 'boundaries'}, 'team shape')
    if shape['policy'] != 'investigator_consult_reviewer':
        raise GraphError('unknown team-shape policy')
    nodes = {n['id']: n for n in spec['nodes']}
    investigator = nodes.get(shape['investigator'])
    if investigator is None or investigator['kind'] not in {'model', 'agent'} or investigator['role'] not in HOST_CONTEXT_ROLES:
        raise GraphError('team shape needs one declared investigator node')
    if type(shape['consultations']) is not list or type(shape['boundaries']) is not list or not shape['boundaries']:
        raise GraphError('team shape needs explicit consultations and consequential boundaries')
    population = [shape['investigator']]
    for consultation in shape['consultations']:
        _keys(consultation, {'node', 'specialty'}, 'specialist consultation')
        _text(consultation['specialty'], 'consultation specialty', 4000)
        node = nodes.get(consultation['node'])
        if node is None or node['kind'] not in {'model', 'agent'} or node['role'] not in {'improver', 'designer'}:
            raise GraphError('specialist consultation must be a non-voting model or worker node')
        population.append(node['id'])
    subjects = set()
    for boundary in shape['boundaries']:
        _keys(boundary, {'subject', 'reviewer'}, 'consequential boundary')
        reviewer = nodes.get(boundary['reviewer']); subject = boundary['subject']
        if subject not in nodes or subject in subjects:
            raise GraphError('each named consequential subject needs exactly one investigator-arm reviewer')
        subjects.add(subject)
        if (reviewer is None or reviewer['kind'] != 'model' or reviewer['role'] not in {'critic', 'verifier'}
                or reviewer['packet'] is None or subject not in reviewer['depends_on']):
            raise GraphError('consequential boundary needs a separate blind reviewer depending on its subject')
        population.append(reviewer['id'])
    if len(population) != len(set(population)):
        raise GraphError('investigator, consultations and boundary reviewers must be distinct nodes')
    agents = {n['id'] for n in nodes.values() if n['kind'] != 'tool'}
    if set(population) != agents:
        raise GraphError('team shape must census every model/worker; hidden agents and maps are refused')
    return shape


def validate(spec):
    """Validate a finite DAG; dependencies schedule, never implicitly expose context."""
    _keys(spec, {"schema_version", "graph_id", "budget", "nodes", *({"goal_binding"} if "goal_binding" in spec else set()),
                 *({'quantity_handoffs'} if 'quantity_handoffs' in spec else set()),
                 *({'required_quantity_kinds'} if 'required_quantity_kinds' in spec else set()),
                 *({'data_classification'} if 'data_classification' in spec else set()),
                 *({'team_shape'} if 'team_shape' in spec else set())}, "agent graph")
    if 'data_classification' in spec:
        from .provider_policy import classification
        classification(spec['data_classification'])
    if "goal_binding" in spec:
        from .task_completion import binding_projection
        binding_projection(spec["goal_binding"], base_dir=Path.cwd())
    if type(spec["schema_version"]) is not int or spec["schema_version"] != 1:
        raise GraphError("agent graph schema_version must be integer 1")
    _id(spec["graph_id"], "graph ID")
    budget = spec["budget"]
    _keys(budget, {"max_nodes", "max_calls", "max_output_tokens", "max_wall_seconds", "max_reworks"}, "graph budget")
    _integer(budget["max_nodes"], "node budget", 1, 256)
    _integer(budget["max_calls"], "call budget", 0, 10000)
    _integer(budget["max_output_tokens"], "output token reservation budget")
    _integer(budget["max_wall_seconds"], "wall-time budget", 1, 86400)
    _integer(budget["max_reworks"], "rework budget", 0, 100)
    if type(spec["nodes"]) is not list or not 1 <= len(spec["nodes"]) <= budget["max_nodes"]:
        raise GraphError("graph node count exceeds budget")
    nodes = {}
    canonical = deepcopy(spec)
    for node in canonical["nodes"]:
        _keys(node, {"id", "kind", "role", "depends_on", "inputs", "packet", "action", "parameters", "max_attempts",
                     *({'registry_role'} if 'registry_role' in node else set())}, "graph node")
        _id(node["id"], "node ID")
        if node["id"] in nodes:
            raise GraphError("duplicate node ID")
        if node["kind"] not in ("model", "tool", "agent", "map") or node["role"] not in ROLES:
            raise GraphError("unknown node kind or role")
        if type(node["depends_on"]) is not list or len(node["depends_on"]) != len(set(node["depends_on"])):
            raise GraphError("invalid or duplicate scheduling dependency")
        for dep in node["depends_on"]:
            _id(dep, "dependency ID")
        if type(node["inputs"]) is not list or len(node["inputs"]) > 128:
            raise GraphError("node inputs must be a finite pin list")
        node["inputs"] = [_pin(pin) for pin in node["inputs"]]
        if len({p["id"] for p in node["inputs"]}) != len(node["inputs"]):
            raise GraphError("duplicate input ID")
        if node["packet"] is not None:
            _keys(node["packet"], {"path", "manifest_sha256"}, "role packet binding")
            if not SHA.fullmatch(str(node["packet"]["manifest_sha256"])):
                raise GraphError("invalid packet digest")
            node["packet"]["path"] = str(_path(node["packet"]["path"]))
        if node["kind"] == "model" and node["role"] in BLIND_GRAPH_ROLES:
            if node["packet"] is None or node["inputs"]:
                raise GraphError("blind model roles require a role packet and no extra raw inputs")
        if node["kind"] in {"agent", "map"} and node["role"] in BLIND_GRAPH_ROLES:
            # A blind worker receives only the code-computed role packet, under its own role card.
            worker = (node["parameters"].get("spec") or {}) if type(node["parameters"]) is dict else {}
            inner = worker.get("spec") if node["kind"] == "map" and type(worker) is dict else worker
            items = worker.get("items") if node["kind"] == "map" and type(worker) is dict else []
            if (node["packet"] is None or node["inputs"] or type(inner) is not dict
                    or (inner.get("role") or {}).get("id") != node["role"] or inner.get("inputs")
                    or inner.get("work_order") is not None
                    or type(items) is not list or any(type(i) is not dict or i.get("inputs") for i in items)):
                raise GraphError("blind worker roles require a role packet, a matching role card and no raw inputs or work order")
        _text(node["action"], "node action", 80)
        if type(node["parameters"]) is not dict:
            raise GraphError("node parameters must be an object")
        if len(json.dumps(node["parameters"], allow_nan=False).encode()) > 262144:
            raise GraphError("node parameters exceed finite payload limit")
        if node["kind"] in {"agent", "map"}:
            _keys(node["parameters"], {"rundir", "spec"}, "worker dispatch parameters")
            node["parameters"]["rundir"] = str(_path(node["parameters"]["rundir"]))
            if node["action"] != "dispatch":
                raise GraphError("worker nodes use the code-owned dispatch action")
            from . import agent_worker
            try:
                if node["kind"] == "agent":
                    agent_worker._validate(node["parameters"]["spec"])
                else:
                    agent_worker.validate_map(node["parameters"]["spec"])
            except (ValueError, KeyError, TypeError) as exc:
                raise GraphError(str(exc)) from exc
        _integer(node["max_attempts"], "node attempt budget", 1, 16)
        nodes[node["id"]] = node
    seen, active = set(), set()
    def walk(node_id):
        if node_id in active:
            raise GraphError("cyclic scheduling graph")
        if node_id in seen:
            return
        if node_id not in nodes:
            raise GraphError("absent dependency node")
        active.add(node_id)
        for dep in nodes[node_id]["depends_on"]:
            walk(dep)
        active.remove(node_id)
        seen.add(node_id)
    for node_id in nodes:
        walk(node_id)
    from . import role_registry
    assignments = {}
    for node in nodes.values():
        identity = node.get('registry_role')
        if node['kind'] in {'agent', 'map'}:
            worker = node['parameters']['spec']
            if node['kind'] == 'map':
                worker = worker['spec']
            worker_identity = worker['role']['id']
            # A scheduler label names a graph role, not a scientific specialist;
            # only an explicit registry binding then assigns quantity ownership.
            if worker_identity not in ROLES:
                if identity is not None:
                    if type(identity) is not str:
                        raise GraphError('registered scientific role must be text')
                    try:
                        resolved = role_registry.resolve_names([identity, worker_identity])
                    except ValueError as exc:
                        raise GraphError(str(exc)) from exc
                    if resolved[identity] != resolved[worker_identity]:
                        raise GraphError('registry role differs from dispatched worker role')
                identity = worker_identity
        if identity is not None:
            if type(identity) is not str:
                raise GraphError('registered scientific role must be text')
            assignments[node['id']] = identity
    required = canonical.get('required_quantity_kinds', [])
    if type(required) is not list or any(type(k) is not str for k in required) or len(set(required)) != len(required):
        raise GraphError('required quantity kinds must be a unique text list')
    try:
        role_registry.validate_ownership(assignments, canonical.get('quantity_handoffs', []), required_kinds=required)
        for handoff in canonical.get('quantity_handoffs', []):
            def precedes(source, target):
                return source in nodes[target]['depends_on'] or any(precedes(source, dep) for dep in nodes[target]['depends_on'])
            if not precedes(handoff['from'], handoff['to']):
                raise GraphError('quantity handoff requires a scheduling dependency')
    except (ValueError, KeyError, TypeError) as exc:
        raise GraphError(str(exc)) from exc
    _team_shape(canonical)
    return canonical


def _root(value):
    root = _path(str(value))
    if not root.is_dir():
        raise GraphError("graph directory is absent")
    return root


def _load(root):
    spec = validate(read_json(root / SPEC))
    state = read_json(root / STATE)
    if (type(state) is not dict or state.get("schema_version") != 1
            or state.get("spec_sha256") != digest(spec) or state.get("graph_id") != spec["graph_id"]
            or set(state.get("nodes", {})) != {node["id"] for node in spec["nodes"]}):
        raise GraphError("graph checkpoint differs from its exact specification")
    return spec, state


def _save(root, state):
    state["sequence"] += 1
    atomic_json(root / STATE, state)


def _event(state, event_name, **values):
    state["history"].append({"sequence": len(state["history"]) + 1, "event": event_name, **values})


def create(root, spec):
    spec = validate(spec)
    root = _path(str(root))
    from . import provider_policy
    declaration = spec.get('data_classification')
    inherited = provider_policy.inherited_declaration(root.parent, include_project=False)
    if declaration is not None and inherited is not None and declaration != inherited:
        raise provider_policy.PolicyRefused('child graph cannot override its run data classification')
    if declaration is None:
        declaration = inherited
    declaration = provider_policy.validate_run_start(
        root, declaration, [p for n in spec['nodes'] for p in n['inputs']])
    root.mkdir(parents=True, exist_ok=False)
    provider_policy.start(root, data_classification=declaration,
                          input_pins=[p for n in spec['nodes'] for p in n['inputs']])
    from . import gate_wiring
    gate_wiring.initialize_steering(root, route='graph-scope')
    for name in ("specs", "attempts", "calls"):
        (root / name).mkdir()
    spec_sha = digest(spec)
    atomic_json(root / "specs" / (spec_sha + ".json"), spec)
    atomic_json(root / SPEC, spec)
    state = {"schema_version": 1, "graph_id": spec["graph_id"], "instance_id": uuid.uuid4().hex,
             "spec_sha256": spec_sha, "graph_revision": 0, "sequence": 0,
             "started_epoch": None, "cancelled": False, "cancel_reason": None,
             "reworks": 0, "usage": {"calls": 0, "reserved_output_tokens": 0},
             "calls": {}, "history": [], "nodes": {node["id"]: {
                 "status": "pending", "generation": 0, "attempts": 0, "generation_attempts": 0,
                 "attempt_id": None, "result": None, "retryable": False, "error": None}
                 for node in spec["nodes"]}, "limitations": [LIMITATION]}
    _event(state, "created", spec_sha256=spec_sha)
    atomic_json(root / STATE, state)
    return status(root)


def _artifact_checks(node):
    for pin in node["inputs"]:
        path = _path(pin["path"])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != pin["sha256"]:
            raise GraphError(f"input artifact changed: {pin['id']}; supply an explicit graph revision")
    if node["packet"]:
        from . import review_context
        packet = _path(node["packet"]["path"])
        # Authenticate and bound the manifest before inspecting its role.
        manifest = review_context.verify_packet(packet, expected_manifest_sha256=node["packet"]["manifest_sha256"])
        if manifest.get("role") != node["role"]:
            raise GraphError("role packet belongs to a different role")


def _result(root, reference):
    _keys(reference, {"path", "sha256", "result_sha256", "binding_sha256", "host_sha256"}, "node result reference")
    path = _path(str(root / reference["path"]))
    if not path.is_relative_to(root / "attempts") or not path.is_file():
        raise GraphError("node result escaped receipt custody")
    document = read_json(path)
    if digest(document) != reference["sha256"] or digest(document["result"]) != reference["result_sha256"]:
        raise GraphError("node result receipt changed")
    if document["request"]["binding_sha256"] != reference["binding_sha256"]:
        raise GraphError("node result input binding changed")
    return document


def _request(spec, state, node, host_sha):
    dependencies = []
    for dep in node["depends_on"]:
        if state["nodes"][dep]["status"] != "completed":
            raise GraphError("node dependency is not complete")
        dependencies.append({"node_id": dep, "result_sha256": state["nodes"][dep]["result"]["result_sha256"]})
    current = state["nodes"][node["id"]]
    binding = {"node_sha256": digest(node), "generation": current["generation"],
               "input_artifacts": node["inputs"], "packet": node["packet"],
               "dependencies": dependencies, "host_sha256": host_sha}
    request = {"schema_version": 1, "graph_id": state["graph_id"], "graph_revision": state["graph_revision"],
               "node_id": node["id"], "generation": current["generation"],
               "node_sha256": digest(node), "input_artifacts": node["inputs"], "packet": node["packet"],
               "dependencies": dependencies, "binding_sha256": digest(binding)}
    if "goal_binding" in spec:
        from .task_completion import binding_projection
        binding = {**binding, "goal_binding": spec["goal_binding"]}
        request["binding_sha256"] = digest(binding)
        request["goal_binding"] = spec["goal_binding"]
        request["parent_task"] = binding_projection(spec["goal_binding"], base_dir=Path.cwd())
    request["request_id"] = digest({"instance": state["instance_id"], "generation": current["generation"],
                                     "attempt_id": current["attempt_id"], "binding": request["binding_sha256"]})
    return request


def _deadline(spec, state):
    if state["started_epoch"] is not None and time.time() - state["started_epoch"] >= spec["budget"]["max_wall_seconds"]:
        raise GraphError("graph cumulative wall-time budget exhausted")


class Control:
    """Every actual host/tool dispatch is reserved and receipted below node retry."""
    def __init__(self, root, node_id, attempt_id):
        self.root, self.node_id, self.attempt_id = root, node_id, attempt_id

    def cancelled(self):
        with file_lock(self.root / "state.lock"):
            return _load(self.root)[1]["cancelled"]

    def check_cancelled(self):
        if self.cancelled():
            raise Cancelled("graph cancelled; no further dispatch")

    def call(self, label, kind, request, function, output_tokens=0, downstream=None):
        _text(label, "call label", 128)
        if kind not in {"model", "tool"}:
            raise GraphError("unknown call kind")
        _integer(output_tokens, "output token reservation")
        if kind != "model" and output_tokens:
            raise GraphError("only model calls reserve generated tokens")
        call_id = digest({"attempt_id": self.attempt_id, "label": label})
        request_sha = digest(request)
        receipt_path = self.root / "calls" / (call_id + ".json")
        with file_lock(self.root / "state.lock"):
            spec, state = _load(self.root)
            if state["cancelled"]:
                raise Cancelled("graph cancelled; no further dispatch")
            current = state["nodes"].get(self.node_id)
            if current is None or current["attempt_id"] != self.attempt_id or current["status"] != "running":
                raise GraphError("host call is outside its current active node attempt")
            _deadline(spec, state)
            old = state["calls"].get(call_id)
            if old:
                if old["request_sha256"] != request_sha or old["kind"] != kind:
                    raise GraphError("call identity reused with changed content")
                if receipt_path.exists():
                    saved = read_json(receipt_path)
                    if saved.get("request_sha256") != request_sha or saved.get("call_id") != call_id:
                        raise GraphError("call receipt correlation changed")
                    if saved.get("status") == "completed":
                        if digest(saved["result"]) != saved.get("result_sha256"):
                            raise GraphError("call response changed")
                        if old.get("receipt_sha256") and old["receipt_sha256"] != digest(saved):
                            raise GraphError("call receipt changed")
                        old.update(status="completed", receipt_sha256=digest(saved))
                        _save(self.root, state)
                        return saved["result"]
                if old["status"] in {"started", "ambiguous"}:
                    value = _delegated_completion(self.root, state["graph_id"], call_id, request)
                    if value is not _ABSENT:
                        saved = {**{k:v for k,v in old.items() if k != "receipt_sha256"},
                            "status":"completed", "result":value, "result_sha256":digest(value),
                            "elapsed_seconds":0.0}
                        atomic_json(receipt_path,saved)
                        old.update(status="completed",receipt_sha256=digest(saved))
                        _save(self.root,state)
                        return value
                    raise AmbiguousCall("started call has no receipted outcome; explicit reconciliation required")
                raise CallFailure("prior labeled call failed; a new bounded attempt is required")
            if state["usage"]["calls"] >= spec["budget"]["max_calls"]:
                raise GraphError("graph cumulative call budget exhausted")
            if state["usage"]["reserved_output_tokens"] + output_tokens > spec["budget"]["max_output_tokens"]:
                raise GraphError("graph cumulative output token reservation budget exhausted")
            state["usage"]["calls"] += 1
            state["usage"]["reserved_output_tokens"] += output_tokens
            if state["started_epoch"] is None:
                state["started_epoch"] = time.time()
            record = {"schema_version": 1, "call_id": call_id, "node_id": self.node_id,
                      "attempt_id": self.attempt_id, "request_sha256": request_sha,
                      "kind": kind, "output_tokens_reserved": output_tokens, "status": "started"}
            state["calls"][call_id] = dict(record)
            _event(state, "call_reserved", call_id=call_id, node_id=self.node_id, kind=kind)
            _save(self.root, state)
            atomic_json(receipt_path, record)
        began = time.monotonic()
        from . import effect_ledger
        raised, entered = [], []
        def dispatch():
            entered.append(True)
            try:
                return function()
            except Exception as exc:
                raised.append(exc)
                raise
        try:
            try:
                value = effect_ledger.delegate(self.root / "effects", graph_id=state["graph_id"],
                    attempt_id=self.attempt_id, label=label, kind=kind, request=request,
                    function=dispatch, node_id=self.node_id, downstream=downstream)
                # Validate finite serializable public data before recording a response.
                result_sha = digest(value)
                outcome = {**record, "status": "completed", "result": value, "result_sha256": result_sha,
                           "elapsed_seconds": time.monotonic() - began}
                # This receipt is durable before the graph checkpoint adopts completion.
                atomic_json(receipt_path, outcome)
                with file_lock(self.root / "state.lock"):
                    _, state = _load(self.root)
                    state["calls"][call_id].update(status="completed", receipt_sha256=digest(outcome))
                    _save(self.root, state)
                return value
            except effect_ledger.Ambiguous as exc:
                cause = exc.__cause__
                if cause is not None and raised and cause is raised[0] and (
                        isinstance(cause, ReceiptedFailure) or getattr(cause, "ambiguous", False)):
                    # A typed host outcome: a durable failure receipt for the dispatched
                    # action fails the attempt; a typed pause stays ambiguous.
                    raise cause
                raise
            except Exception as exc:
                definite = (raised and exc is raised[0] and getattr(exc, "not_dispatched", False)) or not entered
                if definite or getattr(exc, "ambiguous", False):
                    raise
                # The action was entered and its outcome was not recorded: a raise
                # after dispatch, or a failed receipt or checkpoint write, is never
                # evidence that nothing committed.
                raise AmbiguousCall(f"call outcome unrecorded after dispatch: {type(exc).__name__}") from exc
        except Exception as exc:
            ambiguous = bool(getattr(exc, "ambiguous", False))
            outcome = {**record, "status": "ambiguous" if ambiguous else "failed",
                       "error_type": type(exc.__cause__ if isinstance(exc, AmbiguousCall) and exc.__cause__ else exc).__name__,
                       "retryable": bool(getattr(exc, "retryable", False)) and not ambiguous,
                       "elapsed_seconds": time.monotonic() - began}
            if isinstance(exc, ReceiptedFailure):
                outcome["failure_receipt"] = exc.receipt
            atomic_json(receipt_path, outcome)
            if isinstance(exc, ReceiptedFailure):
                _close_delegated(self.root, state["graph_id"], call_id, outcome,
                    "The host returned a typed failure receipt for the dispatched action")
            with file_lock(self.root / "state.lock"):
                _, state = _load(self.root)
                state["calls"][call_id].update(status=outcome["status"], receipt_sha256=digest(outcome))
                _save(self.root, state)
            raise


_ABSENT = object()


def _delegated(root, graph_id, call_id):
    """The latest ledger record of one legacy call (``effect_ledger.delegated_path``)."""
    from . import effect_ledger
    return effect_ledger.latest(root / "effects", effect_ledger.path(
        effect_ledger.DELEGATION_GRAPH, {"graph_id": graph_id}, None, {"call": call_id}))


def _delegated_completion(root, graph_id, call_id, request):
    """The verified result of a legacy call's completed ledger effect, or ``_ABSENT``."""
    from . import effect_ledger
    saved = _delegated(root, graph_id, call_id)
    if (saved is None or saved["status"] != "completed"
            or (saved.get("identity") or {}).get("request_sha256") != digest(request)):
        return _ABSENT
    return effect_ledger.verified_result(root / "effects", saved["call_id"])


def _close_delegated(root, graph_id, call_id, record, reason):
    """Close a legacy call's open ledger effect from its canonical receipt; idempotent.

    Callers close the ledger before they adopt the outcome in graph state, so a
    crash between the two leaves a completed effect that ``Control.call`` adopts.
    """
    from . import effect_ledger
    saved = _delegated(root, graph_id, call_id)
    if saved is None:
        return None
    completed = record["status"] == "completed"
    if saved["status"] in effect_ledger.OPEN:
        receipt = {"status": "completed" if completed else "failed", "call_id": record["call_id"],
                   "request_sha256": record["request_sha256"]}
        if completed:
            receipt["result"] = record["result"]
        return effect_ledger.deliver_external(root / "effects", saved["call_id"], receipt=receipt, reason=reason)
    if completed and (saved["status"] != "completed" or saved.get("result_sha256") != digest(record["result"])):
        raise GraphError("effect ledger outcome differs from the canonical call receipt")
    if not completed and saved["status"] == "completed":
        raise GraphError("the effect ledger records this call as completed; it cannot close as failed")
    return saved


def _not_dispatched(root, graph_id, call_id, prior):
    """Fail a reserved call whose dispatch provably never began, in the ledger and the graph."""
    from . import effect_ledger
    record = {**{k: v for k, v in prior.items() if k != "receipt_sha256"}, "status": "failed",
              "reconciliation": {"outcome": "not_dispatched", "reason": "no dispatch custody record exists",
                                 "truth_authenticated": False}}
    saved = _delegated(root, graph_id, call_id)
    if saved is not None and saved["status"] in effect_ledger.OPEN:
        evidence = root / "effects" / effect_ledger.EVIDENCE / (saved["call_id"] + ".json")
        atomic_json(evidence, record)
        effect_ledger.reconcile(root / "effects", saved["call_id"], outcome="not_dispatched",
            evidence=[{"path": evidence.relative_to(root / "effects").as_posix(),
                       "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
            reason="No dispatch custody record exists for the reserved call")
    atomic_json(root / "calls" / (call_id + ".json"), record)
    with file_lock(root / "state.lock"):
        _, latest = _load(root)
        if latest["calls"][call_id]["status"] != "failed":
            # Never dispatched: the reservation consumed neither a node attempt nor a call.
            current = latest["nodes"][prior["node_id"]]
            if current["attempt_id"] == prior["attempt_id"]:
                current["generation_attempts"] -= 1
            latest["usage"]["calls"] -= 1
        latest["calls"][call_id].update(status="failed", receipt_sha256=digest(record))
        _save(root, latest)


def _host_identity(host):
    identity = getattr(host, "identity", None)
    if not isinstance(identity, dict) or not identity:
        raise GraphError("executable host must expose its nonsecret source/config identity")
    return digest(identity)


def _external_identity():
    from . import agent_host, review_context, langgraph_runtime
    return {"adapter": "host_mediated_external", "schema_version": 1,
            "langgraph_runtime_sha256": hashlib.sha256(Path(langgraph_runtime.__file__).read_bytes()).hexdigest(),
            "review_context_sha256": hashlib.sha256(Path(review_context.__file__).read_bytes()).hexdigest(),
            "agent_graph_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "agent_host_sha256": hashlib.sha256(Path(agent_host.__file__).read_bytes()).hexdigest()}



def _validate_prepared_external_host(prepared):
    """Verify source custody, not host authentication or scientific authority."""
    _keys(prepared, {"identity", "sources"}, "prepared external host")
    identity = prepared["identity"]
    names = (("agent_graph", "agent_host", "review_context", "langgraph_runtime")
             if "langgraph_runtime_sha256" in identity else
             ("agent_graph", "agent_host", "review_context") if "review_context_sha256" in identity
             else ("agent_graph", "agent_host"))
    _keys(identity, {"adapter", "schema_version", *(name+"_sha256" for name in names)},
          "external host identity")
    if (identity["adapter"] != "host_mediated_external" or
            type(identity["schema_version"]) is not int or identity["schema_version"] != 1):
        raise GraphError("canonical external host identity required")
    _keys(prepared["sources"], set(names), "prepared host sources")
    for name in names:
        expected = identity[name + "_sha256"]
        if type(expected) is not str or not SHA.fullmatch(expected):
            raise GraphError("exact prepared host source digest required")
        pin = prepared["sources"][name]
        _keys(pin, {"path", "sha256"}, "prepared host source pin")
        path = _path(pin["path"])
        if (pin["sha256"] != expected or not path.is_file() or path.stat().st_size > 1000000
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
            raise GraphError("prepared external host source changed")
    return identity


def _capture_external_host(root):
    """Store immutable source bytes before reserving a future external call."""
    from . import agent_host, review_context, langgraph_runtime
    identity = _external_identity()
    folder = _path(str(root / "host_sources"))
    folder.mkdir(exist_ok=True)
    sources = {}
    for name, source in (("agent_graph", Path(__file__)), ("agent_host", Path(agent_host.__file__)),
                         ("review_context", Path(review_context.__file__)),
                         ("langgraph_runtime", Path(langgraph_runtime.__file__))):
        raw = source.read_bytes()
        expected = identity[name + "_sha256"]
        if len(raw) > 1000000 or hashlib.sha256(raw).hexdigest() != expected:
            raise GraphError("external host source changed during preparation")
        target = _path(str(folder / (expected + ".py")))
        if not target.exists():
            with target.open("xb") as stream:
                stream.write(raw)
        sources[name] = {"path": str(target), "sha256": expected}
    prepared = {"identity": identity, "sources": sources}
    _validate_prepared_external_host(prepared)
    if identity != _external_identity():
        raise GraphError("external host source changed during preparation")
    return prepared


def _node_host_sha(node, default):
    return digest(_external_identity()) if node["kind"] == "model" and node["action"] == "external" else default


def _run_node(root, node_id, host, host_sha):
    from contextlib import ExitStack
    from . import gate_wiring
    with ExitStack() as running:
        # The final steering check and the record of this running node are one steering
        # transaction; the node then runs outside the lock and drains under a later pause.
        try:
            running.enter_context(gate_wiring.steering_admitted(root, node_id))
        except gate_wiring.SteeringRefused as exc:
            raise GraphError(str(exc)) from None
        return _run_admitted_node(root, node_id, host, host_sha)


def _run_admitted_node(root, node_id, host, host_sha):
    with file_lock(root / "state.lock"):
        spec, state = _load(root)
        if state["cancelled"]:
            return node_id
        _deadline(spec, state)
        node = next(n for n in spec["nodes"] if n["id"] == node_id)
        host_sha = _node_host_sha(node, host_sha)
        current = state["nodes"][node_id]
        _artifact_checks(node)
        if current["status"] != "running":
            if current["generation_attempts"] >= node["max_attempts"]:
                raise GraphError("node attempt budget exhausted")
            current["attempt_id"] = uuid.uuid4().hex
            current["attempts"] += 1
            current["generation_attempts"] += 1
            current["status"] = "running"
            _event(state, "node_started", node_id=node_id, generation=current["generation"],
                   attempt_id=current["attempt_id"])
            _save(root, state)
        request = _request(spec, state, node, host_sha)
        attempt_id = current["attempt_id"]
        attempt_path = root / "attempts" / (attempt_id + ".json")
    control = Control(root, node_id, attempt_id)
    try:
        if attempt_path.exists():
            saved = read_json(attempt_path)
            if saved.get("request") != request or saved.get("host_sha256") != host_sha:
                raise GraphError("saved attempt differs from current exact inputs")
            result = saved["result"]
        else:
            service = None
            if node["kind"] in {"agent", "map"}:
                from . import agent_worker
                try:
                    from .effect_ledger import framework_step
                    step = framework_step()
                except ImportError:
                    step = None
                worker_spec = deepcopy(node["parameters"]["spec"])
                if node["kind"] == "agent":
                    # Monotonic over generations: a workspace is never reused after a
                    # refunded or reworked attempt.
                    worker_spec["attempt"] = current["attempts"]
                recovering=False
                def dispatch_worker():
                    dispatch = agent_worker.dispatch if node["kind"] == "agent" else agent_worker.dispatch_map
                    result = dispatch(Path(node["parameters"]["rundir"]), worker_spec,
                        **({'retry_failed':not recovering} if node["kind"]=="map" else {}),
                        graph={"id":state["graph_id"],"version":state["graph_revision"]}, framework_step=step,
                        packet=node["packet"], protected=[str(root)],
                        **({"effect":effect} if node["kind"]=="agent" else {}))
                    receipts = [result] if node["kind"] == "agent" else result
                    joined = (agent_worker.join_outcome(worker_spec, receipts) if node["kind"] == "map"
                              else {"ok": "ok", "ambiguous": "ambiguous"}.get(result["status"], "failed"))
                    if joined == "ambiguous":
                        raise AmbiguousCall("worker requires explicit reconciliation")
                    if joined != "ok":
                        raise ReceiptedFailure("worker completion checks did not pass",
                            {"status": "failed", "worker_receipts": [
                                {"node_id": r.get("node_id"), "attempt": r.get("attempt"),
                                 "status": r["status"], "sha256": digest(r)} for r in receipts]},
                            retryable=all(r["status"] in {"ok","failed"} for r in receipts))
                    return result
                # A worker has its own durable launch custody. If the graph
                # runner died, reattach to that exact attempt before closing its
                # original effect reservation; never allocate another CLI.
                call_id=digest({"attempt_id":attempt_id,"label":"worker-dispatch"})
                dispatch_request={**request,"worker_spec":worker_spec}
                downstream=None
                if node["kind"]=="agent":
                    # The worker receipt carries this effect's identity and epoch and its
                    # supervisor writes the downstream document the ledger validates.
                    from . import effect_ledger
                    downstream={"kind":agent_worker.DOWNSTREAM_KIND,"path":f"downstream/worker/{call_id}.json"}
                    effect={"identity_sha256":effect_ledger.digest({"legacy_call_id":call_id,
                                "request_sha256":digest(dispatch_request),"kind":effect_ledger.LEGACY_KINDS["tool"]}),
                            "epoch":{"cancellation":effect_ledger.epoch(root/"effects")["cancellation"]},
                            "downstream":str(root/"effects"/downstream["path"])}
                prior=state["calls"].get(call_id)
                if prior and prior["status"] in {"started","ambiguous"}:
                    recovering=True
                    run=Path(node["parameters"]["rundir"])
                    if node["kind"]=="agent" and not agent_worker.dispatched(run,worker_spec["node_id"],worker_spec["attempt"]):
                        # The runner died after the reservation and before any custody
                        # record: no worker ran. Close this attempt as not dispatched
                        # and refund its node attempt and call; the node retries.
                        _not_dispatched(root,state["graph_id"],call_id,prior)
                        error=CallFailure("worker reservation was never dispatched; retry under a new attempt")
                        error.retryable=True
                        raise error
                    failure=None
                    try:
                        recovered=dispatch_worker()
                        receipt={**{k:v for k,v in prior.items() if k!="receipt_sha256"},
                            "status":"completed","result":recovered,"result_sha256":digest(recovered),"elapsed_seconds":0.0}
                    except ReceiptedFailure as exc:
                        failure=exc
                        receipt={**{k:v for k,v in prior.items() if k!="receipt_sha256"},
                            "status":"failed","error_type":type(exc).__name__,"retryable":exc.retryable,
                            "failure_receipt":exc.receipt,"elapsed_seconds":0.0}
                    _close_delegated(root,state["graph_id"],call_id,receipt,
                        "Worker custody receipt closed the interrupted graph reservation")
                    atomic_json(root/"calls"/(call_id+".json"),receipt)
                    with file_lock(root/"state.lock"):
                        _, latest=_load(root)
                        latest["calls"][call_id].update(status=receipt["status"],receipt_sha256=digest(receipt))
                        _save(root,latest)
                    if failure is not None:
                        raise failure
                result = control.call("worker-dispatch", "tool", dispatch_request, dispatch_worker, downstream=downstream)
            else:
                from .langchain_service import ChargedService
                service = ChargedService(host, node, request, control)
                result = service.invoke({"node": node, "request": request})
            _artifact_checks(node)
            with file_lock(root / "state.lock"):
                _, state = _load(root)
                calls = [{"call_id": identity, "sha256": call.get("receipt_sha256")}
                         for identity, call in state["calls"].items()
                         if call["attempt_id"] == attempt_id and call["status"] == "completed"]
                if not any(state["calls"][call["call_id"]]["kind"] == ("tool" if node["kind"] in {"agent", "map"} else node["kind"]) for call in calls):
                    raise GraphError("node result has no accounted executable host dispatch")
            saved = {"schema_version": 1, "node_id": node_id, "attempt_id": attempt_id,
                     "request": request, "host_sha256": host_sha, "result": result,
                     "result_sha256": digest(result), "call_receipts": calls, "advisory": True,
                     "service_observation": service.observation if service is not None else {"adapter":"agent_worker"}}
            atomic_json(attempt_path, saved)
        reference = {"path": attempt_path.relative_to(root).as_posix(), "sha256": digest(saved),
                     "result_sha256": digest(result), "binding_sha256": request["binding_sha256"],
                     "host_sha256": host_sha}
        with file_lock(root / "state.lock"):
            _, state = _load(root)
            current = state["nodes"][node_id]
            if current["attempt_id"] != attempt_id or current["generation"] != request["generation"]:
                raise GraphError("late result belongs to a superseded node generation")
            current.update(status="cancelled" if state["cancelled"] else "completed", result=reference,
                           retryable=False, error=None)
            _event(state, "node_result_fenced" if state["cancelled"] else "node_completed",
                   node_id=node_id, result_sha256=reference["result_sha256"])
            _save(root, state)
        return node_id
    except Exception as exc:
        with file_lock(root / "state.lock"):
            _, state = _load(root)
            current = state["nodes"][node_id]
            if current["attempt_id"] == attempt_id:
                current.update(status="cancelled" if state["cancelled"] else
                               "ambiguous" if getattr(exc, "ambiguous", False) else "failed",
                               retryable=bool(getattr(exc, "retryable", False)),
                               error={"type": type(exc).__name__, "message": str(exc)[:1000]})
                _event(state, "node_failed", node_id=node_id, status=current["status"], error_type=type(exc).__name__)
                _save(root, state)
        return node_id


def execute(root, host, *, workers=1, clear_stop=False):
    """Default durable LangGraph scheduling over ordinary accounted effects.

    Calls, generations, external responses, source checks and scientific
    authority still use this module's existing canonical receipts/services.
    The run holds the substrate scope runner on ``<root>/effects``; a
    ``ravel graph stop`` there drains it until a run with ``clear_stop``.
    """
    from .langgraph_runtime import execute as framework_execute
    return framework_execute(root, host, workers=workers, clear_stop=clear_stop)


def _affected(spec, changed):
    selected = set(changed)
    ids = {n["id"] for n in spec["nodes"]}
    if not selected <= ids:
        raise GraphError("rework names an absent node")
    while True:
        successor = selected | {n["id"] for n in spec["nodes"] if selected.intersection(n["depends_on"])}
        if successor == selected:
            return sorted(selected)
        selected = successor


def _invalidate(state, affected, reason):
    for node_id in affected:
        current = state["nodes"][node_id]
        if current["status"] in {"running", "ambiguous"}:
            raise GraphError("reconcile active or ambiguous calls before rework")
    for node_id in affected:
        current = state["nodes"][node_id]
        current.update(status="pending", generation=current["generation"] + 1, generation_attempts=0,
                       attempt_id=None, result=None, retryable=False, error=None)
        current.pop("external_releases", None)
    state["reworks"] += 1
    state["graph_revision"] += 1
    _event(state, "rework", affected_nodes=affected, reason=reason)


def rework(root, nodes=(), *, reason, findings=None):
    root = _root(root); _text(reason, "rework reason", 4000)
    with file_lock(root / "run.lock", blocking=False), file_lock(root / "state.lock"):
        spec, state = _load(root)
        if findings is not None:
            from . import finding_routing as routing
            repairs, limitations = routing.partition(findings)
            artifacts = {p['sha256'] for node in spec['nodes'] for p in node['inputs']}
            for current in state['nodes'].values():
                if current['result']:
                    artifacts.update(current['result'][k] for k in ('sha256', 'result_sha256'))
            for finding in findings:
                classification = routing.validate(finding)
                if classification and classification['artifact_sha256'] not in artifacts:
                    raise GraphError('finding must bind a current graph artifact digest')
            targets = [routing.validate(f)['target'] for f in repairs if routing.kind(f) == 'defect']
            # Unclassified documents retain the old caller-supplied routing.
            if any(routing.kind(f) == 'unclassified' for f in repairs):
                targets += list(nodes)
            elif repairs and nodes and set(nodes) != set(targets):
                raise GraphError('rework nodes must exactly match named defect targets')
            _affected(spec, targets)
            seen = state.get('finding_reworks', {})
            fresh = [f for f in repairs if routing.kind(f) == 'unclassified' or routing.repair_key(f) not in seen]
            targets = list(dict.fromkeys(routing.validate(f)['target'] for f in fresh if routing.kind(f) == 'defect'))
            if any(routing.kind(f) == 'unclassified' for f in fresh):
                targets += list(nodes)
            affected = _affected(spec, targets)
            if affected and state['reworks'] >= spec['budget']['max_reworks']:
                raise GraphError('graph cumulative rework budget exhausted')
            if affected:
                _invalidate(state, affected, reason)
            ledger = state.setdefault('finding_reworks', {})
            for finding in fresh:
                if routing.kind(finding) == 'defect':
                    ledger[routing.repair_key(finding)] = deepcopy(finding)
            census = state.setdefault('limitation_census', [])
            for row in routing.limitation_census(limitations):
                if row not in census:
                    census.append(row)
            _event(state, 'findings_routed', findings=deepcopy(findings), affected_nodes=affected)
        else:
            if state['reworks'] >= spec['budget']['max_reworks']:
                raise GraphError('graph cumulative rework budget exhausted')
            affected = _affected(spec, nodes)
            if not affected:
                raise GraphError('rework needs a changed node')
            _invalidate(state, affected, reason)
        _save(root, state)
    return status(root)


def revise(root, spec, *, reason, expected_spec_sha256=None, expected_state_sha256=None):
    root = _root(root); new = validate(spec); _text(reason, "revision reason", 4000)
    with file_lock(root / "run.lock", blocking=False), file_lock(root / "state.lock"):
        old, state = _load(root)
        from . import provider_policy
        current_policy = provider_policy.inherited_declaration(root)
        if (old.get('data_classification') != new.get('data_classification')
                and new.get('data_classification') != current_policy):
            raise provider_policy.PolicyRefused('graph provider policy change requires an explicit approval record')
        provider_policy.validate_start(current_policy, [p for n in new['nodes'] for p in n['inputs']])
        for expected in (expected_spec_sha256, expected_state_sha256):
            if expected is not None and (type(expected) is not str or not SHA.fullmatch(expected)):
                raise GraphError('exact revision fence SHA required')
        if ((expected_spec_sha256 is not None and digest(old)!=expected_spec_sha256)
                or (expected_state_sha256 is not None and digest(state)!=expected_state_sha256)):
            raise GraphError('current Graph specification or state superseded the checked predecessor')
        if _team_shape(old) != _team_shape(new):
            raise GraphError('a revision cannot change its selected team-shape arm')
        if old["graph_id"] != new["graph_id"] or old["budget"] != new["budget"]:
            raise GraphError("a graph revision cannot change identity or widen/reset its frozen budget")
        before, after = {n["id"]: n for n in old["nodes"]}, {n["id"]: n for n in new["nodes"]}
        if set(before) != set(after):
            raise GraphError("bounded revisions retain the declared node set")
        changed = [node_id for node_id in before if before[node_id] != after[node_id]]
        if not changed:
            raise GraphError("revision has no changed node")
        if state["reworks"] >= old["budget"]["max_reworks"]:
            raise GraphError("graph cumulative rework budget exhausted")
        affected = sorted(set(_affected(old, changed)) | set(_affected(new, changed)))
        _invalidate(state, affected, reason)
        new_sha = digest(new)
        atomic_json(root / "specs" / (new_sha + ".json"), new)
        # Both files are atomic individually. An interrupted pair fails closed on load.
        atomic_json(root / SPEC, new)
        state["spec_sha256"] = new_sha
        _event(state, "spec_revised", before_sha256=digest(old), after_sha256=new_sha)
        _save(root, state)
    return status(root)


def cancel(root, *, reason):
    root = _root(root); _text(reason, "cancel reason", 4000)
    with file_lock(root / "state.lock"):
        _, state = _load(root)
        state.update(cancelled=True, cancel_reason=reason)
        _event(state, "cancelled", reason=reason)
        _save(root, state)
    return status(root)


def resume(root):
    root = _root(root)
    with file_lock(root / "run.lock", blocking=False), file_lock(root / "state.lock"):
        spec, state = _load(root)
        _deadline(spec, state)
        if not state["cancelled"]:
            raise GraphError("graph is not cancelled")
        state.update(cancelled=False, cancel_reason=None)
        for current in state["nodes"].values():
            if current["status"] == "cancelled":
                # Reenter the same attempt; persisted calls/results are reconciled.
                current["status"] = "completed" if current["result"] else "running"
        _event(state, "resumed")
        _save(root, state)
    return status(root)


def status(root):
    root = _root(root)
    with file_lock(root / "state.lock"):
        spec, state = _load(root)
        for current in state["nodes"].values():
            if current["result"]:
                _result(root, current["result"])
        result = deepcopy(state)
        result["complete"] = all(n["status"] == "completed" for n in state["nodes"].values()) and not state["cancelled"]
        if "goal_binding" in spec:
            from .task_completion import binding_projection
            result["parent_task"] = binding_projection(spec["goal_binding"], base_dir=Path.cwd())
        # Repeated refused requests remain visible to the decider without
        # invalidating nodes, spending calls or reclassifying scientific findings.
        from . import finding_routing as routing
        histories = {}
        for event in state['history']:
            if event['event'] != 'findings_routed':
                continue
            for finding in event['findings']:
                if routing.kind(finding) != 'defect':
                    continue
                key = routing.repair_key(finding)
                histories.setdefault(key, []).append({'sequence': event['sequence'],
                    'finding': deepcopy(finding), 'affected_nodes': event['affected_nodes']})
        result['limitation_candidates'] = [
            {'repair_key': key, 'finding': deepcopy(rows[-1]['finding']),
             'route': 'physics_decider', 'classification': 'limitation_candidate',
             'unchanged_requests': sum(not r['affected_nodes'] for r in rows),
             'history': rows, 'execution_authorized': False}
            for key, rows in histories.items() if sum(not r['affected_nodes'] for r in rows) >= 2]
        result['redo_counts_by_stage'] = {node['id']: sum(node['id'] in e['affected_nodes']
            for e in state['history'] if e['event'] == 'rework') for node in spec['nodes']}
        result['team_shape'] = deepcopy(_team_shape(spec))
        result["advisory"] = True
        result["execution_authorized"] = False
        result["budget"] = spec["budget"]
        return result




def reconcile(root, call_id, *, outcome, evidence, reason, result=None):
    """Record an explicit evidence-backed resolution of an ambiguous host effect.

    Evidence custody and the caller's disposition are checked, not their truth.
    Manually reconstructed model results cannot become observed live reviews.
    """
    root = _root(root); _text(reason, "reconciliation reason", 4000)
    if type(call_id) is not str or not SHA.fullmatch(call_id) or outcome not in {"completed", "not_dispatched", "failed"}:
        raise GraphError("invalid call reconciliation")
    if type(evidence) is not list or not evidence:
        raise GraphError("call reconciliation requires external evidence pins")
    pins = [_pin(pin) for pin in evidence]
    _artifact_checks({"inputs": pins, "packet": None})
    if (outcome == "completed") != (result is not None):
        raise GraphError("only a completed reconciliation requires its public result")
    if result is not None:
        from .agent_host import validate_public_result
        result = validate_public_result(result, None)
        if result.get("kind") == "model_result":
            result = deepcopy(result)
            result.setdefault("transport", {})["execution_mode"] = "reconciled_attestation"
    with file_lock(root / "run.lock", blocking=False), file_lock(root / "state.lock"):
        _, state = _load(root)
        call = state["calls"].get(call_id)
        if call is None or call["status"] not in {"started", "ambiguous"}:
            raise GraphError("only a started/ambiguous call can be reconciled")
        current = state["nodes"][call["node_id"]]
        if current["attempt_id"] != call["attempt_id"]:
            raise GraphError("reconciliation belongs to an obsolete node attempt")
        record = {**{k: v for k, v in call.items() if k != "receipt_sha256"},
                  "status": "completed" if outcome == "completed" else "failed",
                  "reconciliation": {"outcome": outcome, "evidence": pins, "reason": reason,
                                     "truth_authenticated": False}}
        if result is not None:
            record.update(result=result, result_sha256=digest(result))
        _close_delegated(root, state["graph_id"], call_id, record, reason)
        atomic_json(root / "calls" / (call_id + ".json"), record)
        call.update(status=record["status"], receipt_sha256=digest(record))
        current.update(status="running" if outcome == "completed" else "failed", retryable=False,
                       error=None if outcome == "completed" else {"type": "ReconciledEffect", "message": reason})
        _event(state, "call_reconciled", call_id=call_id, outcome=outcome, evidence=pins, reason=reason)
        _save(root, state)
    return status(root)


def prepare_external(root, node_id):
    """Reserve one host invocation before dispatch by an external trusted host.

    This exports a sealed public request; it does not execute a model. The host
    must disclose actual context and later deliver its response. Independent
    critic/verifier roles require fresh context without a parent transcript. Inference
    token use inside that host is unavailable, so the token ceiling is a declared
    reservation rather than an enforced limit on underlying inference.
    """
    from .agent_host import prepare_model_context, completion_limits
    root = _root(root)
    with file_lock(root / "run.lock", blocking=False):
        with file_lock(root / "state.lock"):
            spec, state = _load(root)
            if state["cancelled"]:
                raise Cancelled("cancelled graph cannot prepare an external request")
            _deadline(spec, state)
            node = next((n for n in spec["nodes"] if n["id"] == node_id), None)
            if node is None or node["kind"] != "model" or node["action"] != "external":
                raise GraphError("external preparation requires an external model node")
            current = state["nodes"][node_id]
            if current["status"] != "pending":
                raise GraphError("only a pending external node can be prepared")
            _artifact_checks(node)
            current.update(status="running", attempt_id=uuid.uuid4().hex,
                           attempts=current["attempts"] + 1,
                           generation_attempts=current["generation_attempts"] + 1)
            if current["generation_attempts"] > node["max_attempts"]:
                raise GraphError("external node attempt budget exhausted")
            prepared_host = _capture_external_host(root)
            request = _request(spec, state, node, digest(prepared_host["identity"]))
            attempt_id = current["attempt_id"]
            prepared = prepare_model_context(node, request)
            from . import provider_policy
            if provider_policy.inherited_declaration(root) is not None:
                prepared['context']['provider_policy_run'] = str(provider_policy.find_run(root))
            document = {"schema_version": 1, "kind": "external_agent_request", "request": request,
                        **prepared, "execution_mode": "host_mediated_external",
                        "completion_limits": completion_limits(prepared["parameters"]),
                        "prepared_host": prepared_host,
                        "limitations": ["No model has executed when this request is prepared.",
                            "Fresh context and model identity require the external host's attestation.",
                            "No OS sandbox; internal inference call/token use is unavailable."]}
            declaring_run, unresolved_run = _declaring_run(root)
            if declaring_run is not None:
                # The request names the run whose pinned project document its session receives; the
                # request digest binds it, so the name travels with the file wherever it is answered.
                document["project_run"] = declaring_run
            elif unresolved_run is not None:
                # The graph's run pins nothing under a tree that pins a document. The request says so,
                # and it is answered only by a caller that names this run.
                document["project_run_unresolved"] = unresolved_run
            document["sha256"] = digest(document)
            _event(state, "external_node_prepared", node_id=node_id, request_id=request["request_id"])
            _save(root, state)
        class AwaitingExternal(RuntimeError):
            ambiguous = True
        control = Control(root, node_id, attempt_id)
        try:
            control.call("external", "model", document,
                         lambda: (_ for _ in ()).throw(AwaitingExternal("awaiting actual externally hosted response")),
                         output_tokens=prepared["parameters"]["max_output_tokens"])
        except AwaitingExternal:
            pass
        except Exception:
            with file_lock(root / "state.lock"):
                _, state = _load(root)
                state["nodes"][node_id].update(status="failed", retryable=False,
                    error={"type": "ExternalPreparationFailed", "message": "No external dispatch was admitted"})
                _save(root, state)
            raise
        out = root / "requests" / (attempt_id + ".json")
        atomic_json(out, document)
        with file_lock(root / "state.lock"):
            _, state = _load(root)
            state["nodes"][node_id].update(status="awaiting_external", external_request={
                "path": out.relative_to(root).as_posix(), "sha256": digest(document)})
            _save(root, state)
    return {"request_file": str(out), "request_id": request["request_id"],
            "request_sha256": document["sha256"], "node_id": node_id, "model_executed": False,
            "usage": status(root)["usage"]}


def deliver_external(root, node_id, response_path, *, prepared_host=None):
    """Import a public response bound to an already reserved external invocation.

    The host's invocation/actor/freshness fields are attestations. This custody
    check does not authenticate an agent or independently certify its judgment.
    A legacy pending request can explicitly present its original, source-pinned
    host identity. Its request stays unchanged; the delivery implementation is
    separately recorded. This completion never reserves another model call.
    """
    from .agent_host import external_completion, HostFailure
    root = _root(root); response_path = _path(str(response_path))
    with file_lock(root / "run.lock", blocking=False), file_lock(root / "state.lock"):
        spec, state = _load(root)
        node = next((n for n in spec["nodes"] if n["id"] == node_id), None)
        current = state["nodes"].get(node_id)
        if node is None or current["status"] != "awaiting_external":
            raise GraphError("external node is not awaiting this response")
        _artifact_checks(node)
        reference = current["external_request"]
        try:
            document = read_json(root / reference["path"])
        except (OSError, ValueError) as exc:
            raise GraphError("prepared external request unavailable or invalid") from exc
        if digest(document) != reference["sha256"] or document["sha256"] != digest({k: v for k, v in document.items() if k != "sha256"}):
            raise GraphError("prepared external request changed")
        try:
            response, value, usage, usage_report, response_pin = external_completion(document, response_path)
        except (HostFailure, OSError, ValueError, TypeError) as exc:
            raise GraphError(str(exc)) from exc
        response_sha = response_pin["sha256"]
        attested_fresh = response["fresh_context"] is True and response["parent_transcript_supplied"] is False
        if node["role"] not in HOST_CONTEXT_ROLES and not attested_fresh:
            raise GraphError(f"external {node['role']} requires an attested fresh context without parent transcript; "
                             "deliver a fresh-context response for the same request, or run "
                             "`ravel agent-graph release-external` to return the node to pending")
        delivery_identity = _external_identity()
        stored_host = document.get("prepared_host")
        if stored_host is not None:
            if prepared_host is not None and prepared_host != stored_host:
                raise GraphError("explicit completion host differs from prepared host")
            prepared_identity = _validate_prepared_external_host(stored_host)
        elif prepared_host is not None:
            prepared_identity = _validate_prepared_external_host(prepared_host)
        else:
            # Legacy same-source delivery retains compatibility. Source drift
            # cannot reconstruct the old binding and needs an explicit pin.
            prepared_identity = delivery_identity
        retained_host = stored_host if stored_host is not None else prepared_host
        prepared_sha = digest(prepared_identity)
        request = _request(spec, state, node, prepared_sha)
        if document["request"] != request or response["request_id"] != request["request_id"] or response["request_sha256"] != document["sha256"]:
            raise GraphError("external response belongs to a different request/context/subject")
        from . import transport_receipt
        evidence = response.get("isolation") if response["schema_version"] == 3 else None
        declaration = None
        if evidence is not None:
            from . import transport_registry
            declaration = transport_registry.load(evidence["transport_id"])  # digest verified by external_completion
        attestation, attestation_reasons = transport_receipt.relay_attestation(response, declaration=declaration)
        session = evidence.get("cli_session_id") if evidence is not None else None
        for other_id, other in state["nodes"].items():
            if other_id != node_id and other.get("result"):
                previous = _result(root, other["result"])["result"]
                if node["role"] in {"critic", "verifier"} and previous.get("transport", {}).get("actor_id") == response["actor_id"]:
                    raise GraphError("independent reviewer cannot reuse a prior node's declared actor")
                if node["role"] in {"critic", "verifier"} and session is not None \
                        and previous.get("transport", {}).get("cli_session_id") == session:
                    raise GraphError("independent reviewer cannot reuse a prior node's CLI session")
        result = {"kind": "model_result", "value": value,
                  "usage": usage,
                  "transport": {"adapter": "external", "execution_mode": "host_mediated_external",
                      "request_id": request["request_id"], "requested_model": document["parameters"]["model"],
                      "reasoning_effort": document["parameters"]["reasoning_effort"],
                      "observed_model": response["observed_model"], "invocation_id": response["invocation_id"],
                      "actor_id": response["actor_id"], "response_sha256": response_sha,
                      "external_response_pin": response_pin, "usage_report": usage_report,
                      "usage_observation": "external_host_reported" if usage_report["state"] == "host_reported" else "unknown",
                      "inference_token_ceiling_enforced": False, "remote_cancellation_supported": False,
                      "prepared_host_identity": prepared_identity,
                      "delivery_host_identity": delivery_identity,
                      "pending_host_completion": prepared_identity != delivery_identity,
                      "response_schema_version": response["schema_version"], "attestation": attestation,
                      "attestation_reasons": attestation_reasons, "cli_session_id": session},
                  "isolation": {"fresh_request": response["fresh_context"],
                      "fresh_context": response["fresh_context"],
                      "parent_transcript_supplied": response["parent_transcript_supplied"],
                      "model_tools_supplied": False, "os_sandbox": False,
                      "freshness_is_host_attestation": True,
                      "independent": False,
                      "limitation": "Relay evidence does not authenticate response authorship or independent execution; no OS sandbox is established."},
                  "public_output_only": True, "execution_authorized": False, "physics_validated": False}
        if evidence is not None:
            result["isolation"]["transport_evidence"] = evidence
            result["isolation"]["user_configuration_loaded"] = response["user_configuration_loaded"]
        if node["role"] == "designer":
            result["isolation"]["independence"] = (
                "fresh context attested by host" if attested_fresh else HOST_DESIGNED)
        from .agent_host import AgentHost
        result = AgentHost._presented_result(result, document["context"])
        call_id = digest({"attempt_id": current["attempt_id"], "label": "external"})
        call = state["calls"].get(call_id)
        if (type(call) is not dict or call.get("request_sha256") != digest(document)
                or call.get("status") != "ambiguous" or call.get("kind") != "model"
                or call.get("node_id") != node_id or call.get("attempt_id") != current["attempt_id"]
                or call.get("output_tokens_reserved") != document["parameters"]["max_output_tokens"]):
            raise GraphError("external invocation does not match its reserved call")
        call_path = _path(str(root / "calls" / (call_id + ".json")))
        retained_call = read_json(call_path)
        if (digest(retained_call) != call.get("receipt_sha256") or
                any(retained_call.get(key) != value for key, value in call.items() if key != "receipt_sha256")):
            raise GraphError("external reserved call receipt changed")
        delivery_host = _capture_external_host(root)
        if delivery_host["identity"] != delivery_identity:
            raise GraphError("external delivery host changed during completion")
        result["transport"]["delivery_host_sources"] = delivery_host["sources"]
        result["transport"]["prepared_host_sources"] = (
            retained_host["sources"] if retained_host is not None else delivery_host["sources"])
        try:
            ending = external_completion(document, response_path, expected=response_pin)
        except (HostFailure, OSError, ValueError, TypeError) as exc:
            raise GraphError(str(exc)) from exc
        if ending != (response, value, usage, usage_report, response_pin):
            raise GraphError("complete external response/usage evidence changed at ending")
        outcome = {**{k: v for k, v in call.items() if k != "receipt_sha256"}, "status": "completed",
                   "result": result, "result_sha256": digest(result),
                   "external_response": {"path": str(response_path), "sha256": response_sha}}
        # The ledger closes first: if it refuses, neither the receipt nor the state
        # records completion; if the process dies after it, Control.call adopts it.
        _close_delegated(root, state["graph_id"], call_id, outcome,
                         "Canonical external response receipt closed the paused reservation")
        atomic_json(root / "calls" / (call_id + ".json"), outcome)
        call.update(status="completed", receipt_sha256=digest(outcome))
        saved = {"schema_version": 1, "node_id": node_id, "attempt_id": current["attempt_id"],
                 "request": request, "host_sha256": prepared_sha, "result": result,
                 "result_sha256": digest(result), "call_receipts": [{"call_id": call_id, "sha256": digest(outcome)}],
                 "advisory": True}
        path = root / "attempts" / (current["attempt_id"] + ".json")
        atomic_json(path, saved)
        current.update(status="cancelled" if state["cancelled"] else "completed", result={
            "path": path.relative_to(root).as_posix(), "sha256": digest(saved), "result_sha256": digest(result),
            "binding_sha256": request["binding_sha256"], "host_sha256": saved["host_sha256"]})
        _event(state, "external_response_fenced" if state["cancelled"] else "external_response_received",
               node_id=node_id, invocation_id=response["invocation_id"], response_sha256=response_sha,
               prepared_host_sha256=prepared_sha, delivery_host_sha256=digest(delivery_identity))
        _save(root, state)
    return status(root)


def release_external(root, node_id, *, reason):
    """Return a node stuck in awaiting_external to pending for a fresh preparation.

    The host states why its reserved response cannot be delivered. The released
    request can no longer be delivered: a new preparation has a new attempt and
    request identity. The node attempt and the declared call/token reservation
    are refunded because no response was accepted. Each node may be released at
    most MAX_EXTERNAL_RELEASES times per generation. The reason is the host's
    statement; it is recorded, not authenticated.
    """
    root = _root(root); _text(reason, "release reason", 4000)
    with file_lock(root / "run.lock", blocking=False), file_lock(root / "state.lock"):
        spec, state = _load(root)
        node = next((n for n in spec["nodes"] if n["id"] == node_id), None)
        current = state["nodes"].get(node_id)
        if node is None or current is None or current["status"] != "awaiting_external":
            raise GraphError("only a node in awaiting_external can be released")
        released = current.get("external_releases", 0)
        if released >= MAX_EXTERNAL_RELEASES:
            raise GraphError(f"external release budget exhausted for {node_id} "
                             f"({MAX_EXTERNAL_RELEASES} per generation); revise the graph instead")
        call_id = digest({"attempt_id": current["attempt_id"], "label": "external"})
        call = state["calls"].get(call_id)
        if type(call) is not dict or call.get("status") != "ambiguous" or call.get("node_id") != node_id:
            raise GraphError("external node has no outstanding reserved call to release")
        call_path = _path(str(root / "calls" / (call_id + ".json")))
        retained = read_json(call_path)
        if digest(retained) != call.get("receipt_sha256"):
            raise GraphError("external reserved call receipt changed")
        record = {**retained, "status": "released",
                  "release": {"reason": reason, "reservation_refunded": True, "truth_authenticated": False}}
        _close_delegated(root, state["graph_id"], call_id, record, "Host released the reserved external response: " + reason)
        atomic_json(call_path, record)
        call.update(status="released", receipt_sha256=digest(record))
        state["usage"]["calls"] = max(0, state["usage"]["calls"] - 1)
        state["usage"]["reserved_output_tokens"] = max(
            0, state["usage"]["reserved_output_tokens"] - call.get("output_tokens_reserved", 0))
        current.update(status="pending", attempt_id=None, result=None, retryable=False, error=None,
                       generation_attempts=max(0, current["generation_attempts"] - 1),
                       external_releases=released + 1)
        current.pop("external_request", None)
        _event(state, "external_released", node_id=node_id, call_id=call_id, reason=reason)
        _save(root, state)
    return status(root)


def _external_completion_evidence(root, node, current, saved):
    """Reconsume original envelope/evidence; receipt hashes do not imply current bytes."""
    from .agent_host import external_completion, HostFailure
    reference = current.get("external_request")
    if type(reference) is not dict:
        raise GraphError("external completion lacks its original prepared request")
    path = _path(str(root / reference["path"]))
    try:
        document = read_json(path)
    except (OSError, ValueError) as exc:
        raise GraphError("original external completion request unavailable or invalid") from exc
    if (digest(document) != reference["sha256"] or
            document["sha256"] != digest({k: v for k, v in document.items() if k != "sha256"})
            or document["request"] != saved["request"] or document["parameters"] != node["parameters"]):
        raise GraphError("original external completion request changed")
    refs = saved.get("call_receipts", [])
    if len(refs) != 1:
        raise GraphError("external completion requires its exact single reserved call")
    call = read_json(root / "calls" / (refs[0]["call_id"] + ".json"))
    expected_call = digest({"attempt_id": saved["attempt_id"], "label": "external"})
    if (refs[0]["call_id"] != expected_call or digest(call) != refs[0]["sha256"]
            or call.get("request_sha256") != digest(document) or call.get("status") != "completed"
            or call.get("kind") != "model" or call.get("node_id") != node["id"]
            or call.get("attempt_id") != saved["attempt_id"]
            or call.get("output_tokens_reserved") != document["parameters"]["max_output_tokens"]
            or call.get("result") != saved["result"]):
        raise GraphError("external completion differs from original consumed reservation")
    transport = saved["result"]["transport"]
    expected = transport.get("external_response_pin", call.get("external_response"))
    if type(expected) is not dict or expected.get("sha256") != transport.get("response_sha256"):
        raise GraphError("external completion lacks its retained response commitment")
    try:
        response, value, usage, report, pin = external_completion(document, expected["path"], expected=expected)
    except (HostFailure, OSError, ValueError, TypeError) as exc:
        raise GraphError(str(exc)) from exc
    if (value != saved["result"]["value"] or usage != saved["result"]["usage"]
            or any(response[k] != transport.get(k) for k in ("request_id", "invocation_id", "actor_id", "observed_model"))
            or "usage_report" in transport and transport["usage_report"] != report
            or "usage_observation" in transport and transport["usage_observation"] != (
                "external_host_reported" if report["state"] == "host_reported" else "unknown")
            or transport.get("inference_token_ceiling_enforced") is not False):
        raise GraphError("external completion usage/value/host attribution changed")
    return {"response": pin, "usage_report": report, "calls": 1,
            "reserved_output_tokens": call["output_tokens_reserved"],
            "actual_token_ceiling_enforced": False}


def model_receipt(root, node_id, *, expected_subject_sha256, expected_packet_sha256=None,
                  require_exact_subject=False):
    """Check a current model-call receipt, never authenticate its scientific vote.

    Loopback fixtures are controls. Remote calls and externally coordinated calls
    have different execution evidence; caller attestations are not signatures.
    """
    return role_receipt(root, node_id, expected_subject_sha256=expected_subject_sha256,
                        expected_packet_sha256=expected_packet_sha256,
                        require_exact_subject=require_exact_subject,
                        allowed_roles={"critic", "verifier"})


def role_receipt(root, node_id, *, expected_subject_sha256, expected_packet_sha256=None,
                 require_exact_subject=False, allowed_roles=None):
    """Current accounted model transport for an explicit role, without a vote.

    model_receipt retains its stricter independent-critic/verifier admission.
    This general receipt also supports non-voting improvers and synthesizers.
    """
    allowed_roles = set(ROLES) if allowed_roles is None else set(allowed_roles)
    if not allowed_roles or not allowed_roles <= set(ROLES):
        raise GraphError("known explicit model roles required")
    root = _root(root)
    if type(expected_subject_sha256) is not str or not SHA.fullmatch(expected_subject_sha256):
        raise GraphError("expected scientific subject digest is required")
    if type(require_exact_subject) is not bool:
        raise GraphError("require_exact_subject must be a boolean")
    with file_lock(root / "state.lock"):
        spec, state = _load(root)
        if state["cancelled"]:
            raise GraphError("cancelled graph cannot supply a current review")
        node = next((n for n in spec["nodes"] if n["id"] == node_id), None)
        if node is None or node["kind"] != "model" or node["role"] not in allowed_roles:
            raise GraphError("model receipt requires an explicitly allowed model role")
        current = state["nodes"][node_id]
        if current["status"] != "completed" or not current["result"]:
            raise GraphError("model review is not complete")
        _artifact_checks(node)
        saved = _result(root, current["result"])
        expected = _request(spec, state, node, saved["host_sha256"])
        if expected["binding_sha256"] != saved["request"]["binding_sha256"]:
            raise GraphError("model review belongs to superseded inputs or dependencies")
        packet_sha = node["packet"]["manifest_sha256"] if node["packet"] else None
        if expected_packet_sha256 is not None and packet_sha != expected_packet_sha256:
            raise GraphError("model review context differs from expected packet")
        presented_subjects = {pin["sha256"] for pin in node["inputs"]}
        subjects = set(presented_subjects)
        receipt_index = None
        if node["packet"]:
            from . import review_context
            # Observe every copied artifact until the ending receipt census.
            receipt_index = review_context._PacketIndex(node["packet"]["path"], packet_sha)
            manifest = receipt_index.manifest
            for artifact in manifest["artifacts"]:
                receipt_index.read(artifact)
                subjects.add(artifact["sha256"])
                if artifact.get("presentation", "inline") != "on_demand":
                    presented_subjects.add(artifact["sha256"])
                if artifact.get("source_sha256"):
                    subjects.add(artifact["source_sha256"])
        if expected_subject_sha256 not in subjects:
            raise GraphError("model review is not bound to the expected scientific subject")
        exact_subject_presented = expected_subject_sha256 in presented_subjects
        accounted = []
        for reference in saved.get("call_receipts", []):
            call = read_json(root / "calls" / (reference["call_id"] + ".json"))
            known = state["calls"].get(reference["call_id"], {})
            if digest(call) != reference["sha256"] or known.get("receipt_sha256") != reference["sha256"]:
                raise GraphError("model-call receipt changed")
            if call["kind"] == "model" and call["status"] == "completed":
                accounted.append(reference)
        result = saved["result"]
        if not accounted or type(result) is not dict or result.get("kind") != "model_result":
            raise GraphError("review has no accounted structured model response")
        transport, isolation = result.get("transport", {}), result.get("isolation", {})
        if "evidence_presentation" in isolation:
            presentation = isolation["evidence_presentation"]
            if (type(presentation) is not dict or presentation.get("manifest_sha256") != packet_sha
                    or type(presentation.get("presented_subject_sha256s")) is not list
                    or not set(presentation["presented_subject_sha256s"]) <= subjects):
                raise GraphError("model evidence presentation differs from bound packet")
            presented_subjects = set(presentation["presented_subject_sha256s"])
            exact_subject_presented = expected_subject_sha256 in presented_subjects
            if require_exact_subject and not exact_subject_presented:
                raise GraphError("model review did not present the exact scientific subject")
        if require_exact_subject and not exact_subject_presented:
            raise GraphError("model review did not present the exact scientific subject")
        if transport.get("request_id") != saved["request"]["request_id"]:
            raise GraphError("model response correlation differs from request")
        mode = transport.get("execution_mode", "unestablished")
        completion_evidence = (_external_completion_evidence(root, node, current, saved)
                               if mode == "host_mediated_external" else None)
        observation = ("host_attested_external" if mode == "host_mediated_external" else
                       "remote_transport_observed" if mode in {"responses_http", "provider_http"} else
                       "local_transport_observed" if mode == "provider_http_local" else
                       "control_only" if mode == "responses_http_loopback_control" else "unestablished")
        attestation, session = _receipt_attestation(root, transport, observation, isolation)
        _require_declared_instructions(root, isolation)
        if mode == "transport_attested_cli":
            observation = "transport_attested_cli" if attestation == "transport_attested" else "unestablished"
        receipt = {"schema_version": 1, "kind": "agent_model_receipt", "node_id": node_id,
                "role": node["role"], "subject_sha256": expected_subject_sha256,
                "exact_subject_presented": exact_subject_presented,
                "presented_subject_sha256s": sorted(presented_subjects),
                "context_manifest_sha256": packet_sha, "request_id": transport["request_id"],
                "receipt_sha256": current["result"]["sha256"], "host_sha256": saved["host_sha256"],
                "transport": transport, "isolation": isolation, "execution_observation": observation,
                "public_value": result["value"], "public_value_sha256": digest(result["value"]),
                "context_transport_separated": bool(isolation.get("fresh_request")
                    and isolation.get("parent_transcript_supplied") is False and packet_sha),
                "attestation": attestation, "session": session,
                "actor_identity_authenticated": False, "scientific_independence_proven": False,
                "physics_validated": False, "execution_authorized": False,
                "limitations": [LIMITATION, "Transport custody does not establish the truth of a review judgment."]}
        if completion_evidence is not None:
            receipt["external_completion_evidence"] = completion_evidence
        if "independence" in isolation:
            receipt["independence"] = isolation["independence"]
        if "visual_presentation" in isolation:
            visual_calls = []
            for reference in accounted:
                call = read_json(root / "calls" / (reference["call_id"] + ".json"))
                if (call.get("result_sha256") != digest(result)
                        or call.get("result") != result):
                    raise GraphError("visual presentation is not the current accounted model result")
                visual_calls.append({"call_id": reference["call_id"],
                    "request_sha256": call["request_sha256"], "receipt_sha256": reference["sha256"]})
            receipt["model_call_requests"] = visual_calls
        if receipt_index is not None: receipt_index.finish()
        if completion_evidence is not None and _external_completion_evidence(root, node, current, saved) != completion_evidence:
            raise GraphError("external completion changed during ending receipt consumption")
        return receipt


def _declaring_run(root):
    """``(declaring, unresolved)``: the run that owns this graph when that run pins a project instruction document.

    Both are None for a graph whose run declares nothing. A graph in a run that pins nothing under a
    declaring run's tree returns that inner run as ``unresolved``: answering its request asks for the
    run by name. A pin that custody knows and the run tree no longer shows is not a missing
    declaration; it refuses the preparation.
    """
    from . import project_instructions
    try:
        run = project_instructions.owning_run(root)
        return (str(run) if run is not None and project_instructions.for_run(run) is not None else None), None
    except project_instructions.ProjectInstructionsError as exc:
        if project_instructions.unsettled(exc):
            return None, str(project_instructions.nearest_run(root))
        raise GraphError(str(exc)) from None


def _require_declared_instructions(root, isolation):
    """Refuse a model review whose session was not shown the pinned project instruction document of the graph's run.

    The session's isolation evidence names the document it was given. A run that pins a document
    credits no review without that record, and none that names another document.
    """
    from . import project_instructions
    evidence = isolation.get("transport_evidence") if type(isolation) is dict else None
    try:
        try:
            pinned = project_instructions.for_path(root)
        except project_instructions.ProjectInstructionsError as exc:
            # The session was started for a named run. That name settles a run that pins nothing under a
            # tree that pins a document, exactly as it did at dispatch; it must be the graph's nearest run.
            named = evidence.get("project_run") if type(evidence) is dict else None
            if not project_instructions.unsettled(exc) or type(named) is not str:
                raise
            pinned = project_instructions.for_path(root, named)
    except project_instructions.ProjectInstructionsError as exc:
        raise GraphError(str(exc)) from None
    if pinned is None:
        return
    problem = project_instructions.supplied_problem(
        evidence.get("project_instructions") if type(evidence) is dict else None, pinned)
    if problem is not None:
        raise GraphError("model review session was not shown the run's pinned project instruction document "
                         f"({problem}); it is not credited")


def _receipt_attestation(root, transport, observation, isolation=None):
    """(attestation, session) for a model receipt, recomputed from host-held evidence.

    A launched CLI's session record is re-read from its create-only file, re-verified and its session id
    compared again with every other session in the graph. A relay label is recomputed from its stored schema and evidence;
    every relay is self_attested. HTTP transports observed by this host are
    transport_attested. Anything else is self_attested.
    """
    from . import transport_receipt
    mode = transport.get("execution_mode")
    if mode == "transport_attested_cli":
        record, pin = transport.get("session_receipt"), transport.get("session_receipt_pin")
        try:
            if type(pin) is not dict or transport_receipt.read(root, pin) != record:
                raise transport_receipt.ReceiptError("session record differs from its pinned file")
            receipt = transport_receipt.shape(record["launcher_receipt"])
            others = transport_receipt.session_ids(root, exclude=Path(pin["path"]).name)
            label, _ = transport_receipt.attestation(receipt, verification=record["verification"], other_session_ids=others,
                tools_required=receipt["configuration"].get("tools_required", "none"))
        except (transport_receipt.ReceiptError, OSError, ValueError, KeyError, TypeError):
            label, receipt, pin = "self_attested", None, None
        session = {"transport_id": receipt["transport"]["id"] if receipt else None,
                   "cli_session_id": receipt["cli_reported"]["session_id"] if receipt else None,
                   "session_receipt_pin": pin}
        return label, session
    if mode == "host_mediated_external":
        evidence = (isolation or {}).get("transport_evidence")
        label, _ = transport_receipt.relay_attestation({
            "schema_version": transport.get("response_schema_version"), "isolation": evidence})
        return label, {"transport_id": None, "cli_session_id": transport.get("cli_session_id"), "session_receipt_pin": None}
    if observation in {"remote_transport_observed", "local_transport_observed"}:
        return "transport_attested", {"transport_id": None, "cli_session_id": None, "session_receipt_pin": None}
    return "self_attested", {"transport_id": None, "cli_session_id": None, "session_receipt_pin": None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "run", "status", "cancel", "resume", "rework", "revise", "prepare-external",
                 "deliver-external", "release-external", "reconcile"):
        sub = commands.add_parser(name)
        sub.add_argument("--graph", type=Path, required=True)
        if name in {"create", "revise"}:
            sub.add_argument("--spec", type=Path, required=True)
        if name in {"prepare-external", "deliver-external", "release-external"}:
            sub.add_argument("--node", required=True)
        if name == "deliver-external":
            sub.add_argument("--response", type=Path, required=True)
        if name == "reconcile":
            sub.add_argument("--call", required=True)
            sub.add_argument("--outcome", choices=("completed", "not_dispatched", "failed"), required=True)
            sub.add_argument("--evidence", type=Path, required=True)
            sub.add_argument("--result", type=Path)
            sub.add_argument("--reason", required=True)
        if name == "run":
            sub.add_argument("--host-config", type=Path, required=True)
            sub.add_argument("--workers", type=int, default=1)
        if name in {"cancel", "rework", "revise", "release-external"}:
            sub.add_argument("--reason", required=True)
        if name == "rework":
            sub.add_argument("--nodes", nargs="+", default=[])
            sub.add_argument("--findings", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            result = create(args.graph, read_json(args.spec))
        elif args.command == "run":
            from .agent_host import AgentHost
            result = execute(args.graph, AgentHost.from_config(read_json(args.host_config)), workers=args.workers)
        elif args.command == "reconcile":
            result = reconcile(args.graph, args.call, outcome=args.outcome, evidence=read_json(args.evidence),
                reason=args.reason, result=read_json(args.result) if args.result else None)
        elif args.command == "prepare-external":
            result = prepare_external(args.graph, args.node)
        elif args.command == "deliver-external":
            result = deliver_external(args.graph, args.node, args.response)
        elif args.command == "release-external":
            result = release_external(args.graph, args.node, reason=args.reason)
        elif args.command == "cancel":
            result = cancel(args.graph, reason=args.reason)
        elif args.command == "resume":
            result = resume(args.graph)
        elif args.command == "rework":
            findings = None
            if args.findings:
                from .role_registry import validate_output
                document = read_json(args.findings)
                errors = validate_output('findings.v2', document)
                if errors:
                    raise GraphError('; '.join(errors))
                findings = document['items']
            result = rework(args.graph, args.nodes, reason=args.reason, findings=findings)
        elif args.command == "revise":
            result = revise(args.graph, read_json(args.spec), reason=args.reason)
        else:
            result = status(args.graph)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError) as exc:
        parser.exit(1, f"agent graph: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
