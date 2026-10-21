"""At most one external effect per domain path under LangGraph's at-least-once execution.

LangGraph re-runs a task after a crash, a replay or a resume. Every effect a
substrate node performs is therefore reserved here under a domain path (graph,
instance, enclosing invocation, stage, round, role, item, turn, tool call), never
under the framework task id or the graph version. A request is split into an
``identity`` that defines equality and a ``provisioning`` record that is kept and
never compared.

A completed path returns its revalidated receipt. A started path without an
outcome is ambiguous under every version and is never dispatched again. Attempt
numbers come from the ledger, not from LangGraph's ``node_attempt``. Charges are
written ahead with the call id as their identity, so a crash at any boundary
neither loses nor doubles a charge. An exception from a dispatched effect is
ambiguous unless it is a typed ``NotDispatched`` (or the kind is deterministic).
Receipts carry no scientific authority, approval or truth authentication.

The worker-delegation API (``delegated_path``, ``delegate``, ``delegated``,
``deliver_external``, ``verified_result``, ``LEGACY_KINDS`` and the
``worker_receipt`` downstream contract) is stable; its functions below document it.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Sequence

from . import graph_environment  # noqa: F401  (strict msgpack before any LangGraph import)
from . import agent_graph, agent_tripwire
from .state_io import atomic_json, file_lock, read_json

SCHEMA_VERSION = 2
CALLS = "calls"
INDEX = "calls/index"
LOCK = "calls/.ledger.lock"
SCOPE = "framework/scope.json"
EPOCH = "framework/epoch.json"
STOP = "framework/STOP"
SCOPE_LOCK = "framework/locks/scope.lock"
EVIDENCE = "calls/evidence"
SHA = re.compile(r"[0-9a-f]{64}\Z")
KIND = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
SEGMENT = re.compile(r"[A-Za-z0-9_.:@+=-]{1,200}\Z")
KINDS = ("check", "compute", "model", "worker", "native", "journal", "external")
# agent_graph ``Control.call`` kinds and worker dispatch, mapped to effect kinds.
LEGACY_KINDS = {"model": "model", "tool": "external", "worker": "worker"}
DETERMINISTIC = {"check", "compute"}
STATUSES = ("reserving", "started", "completed", "failed", "refused", "ambiguous", "reconciled", "superseded",
            "voided")
OPEN = {"started", "ambiguous"}
RETRYABLE = {"failed", "refused", "voided", "reconciled"}
OUTCOMES = {"completed", "not_dispatched", "failed"}
CHARGE_LEDGERS = ("run_ceilings", "campaign")
LOCK_TIMEOUT_SECONDS = 30.0
MAX_REUSES = 32


class Ambiguous(agent_graph.AmbiguousCall):
    """A reserved effect has no trustworthy outcome; reconcile, never re-dispatch."""
    def __init__(self, message, call_id=None):
        super().__init__(message)
        self.call_id = call_id


class NondeterministicRequest(agent_graph.GraphError):
    """A completed path was re-entered with a different identity and no declared change."""
    def __init__(self, message, call_id=None):
        super().__init__(message)
        self.call_id = call_id


class CallFailed(agent_graph.CallFailure):
    """The path's attempts are exhausted; the subsystem's decision turn decides."""
    def __init__(self, message, call_id=None):
        super().__init__(message)
        self.call_id = call_id


class StopRequested(agent_graph.GraphError):
    """The scope is draining: no new effect may be reserved."""


class NotDispatched(agent_graph.GraphError):
    """Raised by an effect function that knows its action was not sent (a refusal before
    dispatch, a closed transport). Only this, or a deterministic kind, records ``failed``
    and lets a later attempt run; every other exception is ambiguous."""
    not_dispatched = True


def digest(value):
    """The shared digest of a JSON value."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def _utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- domain paths and call ids ------------------------------------------------------------

def _segment(segment):
    if type(segment) is not dict or not segment:
        raise agent_graph.GraphError("path segment must be a non-empty JSON object")
    parts = []
    for key, value in segment.items():
        if type(key) is not str or not KIND.fullmatch(key):
            raise agent_graph.GraphError(f"invalid path segment key {key!r}")
        if type(value) is int and type(value) is not bool:
            value = str(value)
        if type(value) is not str or not SEGMENT.fullmatch(value):
            raise agent_graph.GraphError(f"path segment {key} must be a short identifier or integer")
        parts.append(f"{key}:{value}")
    return "/".join(parts)


def path(graph_id, instance, parent, segment):
    """``[<parent>/]<graph id>[<sha256(instance)>]/<segment>``: version- and task-id-free."""
    if type(graph_id) is not str or not KIND.fullmatch(graph_id):
        raise agent_graph.GraphError("invalid graph id")
    if type(instance) is not dict:
        raise agent_graph.GraphError("graph instance must be a JSON object")
    if parent is not None and (type(parent) is not str or not parent.strip()):
        raise agent_graph.GraphError("parent path must be a non-empty string")
    own = f"{graph_id}[{digest(instance)}]/{_segment(segment)}"
    return own if parent is None else f"{parent}/{own}"


def extend(prefix, segment):
    """A further segment under an existing path (for example a turn inside an agent node)."""
    if type(prefix) is not str or not prefix.strip():
        raise agent_graph.GraphError("path prefix required")
    return f"{prefix}/{_segment(segment)}"


def call_id(scope_id, path_text, attempt):
    if type(scope_id) is not str or not SHA.fullmatch(scope_id):
        raise agent_graph.GraphError("invalid scope id")
    if type(path_text) is not str or not path_text.strip():
        raise agent_graph.GraphError("effect path required")
    if type(attempt) is not int or attempt < 1:
        raise agent_graph.GraphError("attempt must be a positive integer")
    return digest({"scope_id": scope_id, "path": path_text, "attempt": attempt})


def legacy_call_id(attempt_id, label):
    """The ``agent_graph.Control.call`` identity, byte for byte (the broker delegation keeps it)."""
    return agent_graph.digest({"attempt_id": attempt_id, "label": label})


def _scope(scope_root):
    root = Path(scope_root).expanduser().absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise agent_graph.GraphError("effect scope root cannot traverse a symlink")
    root.mkdir(parents=True, exist_ok=True)
    return root


def scope_id(scope_root):
    """The scope's stable identity, minted once at first use and kept if the tree moves."""
    root = _scope(scope_root)
    record = root / SCOPE
    if record.exists():
        return read_json(record)["scope_id"]
    record.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(root / "framework" / ".scope.lock"):
        if not record.exists():
            atomic_json(record, {"schema_version": 1, "kind": "graph-scope",
                                 "scope_id": digest({"scope_root": str(root), "created_utc": _utc(),
                                                     "nonce": os.urandom(16).hex()}),
                                 "created_utc": _utc()})
    return read_json(record)["scope_id"]


def epoch(scope_root):
    """``{runner, cancellation}``: the runner epoch rises at each scope-lock acquisition,
    the cancellation epoch at each ``stop --now``."""
    path_ = Path(scope_root) / EPOCH
    value = read_json(path_) if path_.exists() else {}
    return {"runner": int(value.get("runner", 0)), "cancellation": int(value.get("cancellation", 0))}


def bump_epoch(scope_root, which):
    if which not in {"runner", "cancellation"}:
        raise agent_graph.GraphError("epoch must be runner or cancellation")
    root = _scope(scope_root)
    (root / "framework").mkdir(exist_ok=True)
    with file_lock(root / "framework" / ".epoch.lock"):
        current = epoch(root)
        current[which] += 1
        atomic_json(root / EPOCH, {"schema_version": 1, "kind": "graph-epoch", **current, "updated_utc": _utc()})
    return current


def _receipt_path(root, identifier):
    if type(identifier) is not str or not SHA.fullmatch(identifier):
        raise agent_graph.GraphError("invalid call id")
    return Path(root) / CALLS / (identifier + ".json")


def _index_path(root, path_text):
    return Path(root) / INDEX / (hashlib.sha256(path_text.encode()).hexdigest() + ".json")


def read(scope_root, identifier):
    receipt = _receipt_path(scope_root, identifier)
    return read_json(receipt) if receipt.exists() else None


def attempts(scope_root, path_text):
    """The receipts of one path, oldest first."""
    index = _index_path(scope_root, path_text)
    if not index.exists():
        return []
    return [read(scope_root, entry["call_id"]) for entry in read_json(index)["attempts"]]


def latest(scope_root, path_text):
    found = attempts(scope_root, path_text)
    return found[-1] if found else None


def _write(root, record):
    atomic_json(_receipt_path(root, record["call_id"]), record)
    index = _index_path(root, record["path"])
    listing = read_json(index) if index.exists() else {"schema_version": 1, "kind": "effect-path-index",
                                                       "path": record["path"], "attempts": []}
    entries = {e["call_id"]: e for e in listing["attempts"]}
    entries[record["call_id"]] = {"attempt": record["attempt"], "call_id": record["call_id"],
                                  "status": record["status"]}
    listing["attempts"] = sorted(entries.values(), key=lambda e: e["attempt"])
    atomic_json(index, listing)


def framework_step():
    """The LangGraph step executing this effect; null fields outside a graph run.

    ``task_id`` and ``node_attempt`` are observation only and never part of a key (R3).
    """
    step = {"thread_id": None, "checkpoint_ns": None, "checkpoint_id": None, "task_id": None, "node_attempt": None,
            "kernel_module_sha256": kernel_module_sha256()}
    try:
        from langgraph.runtime import get_runtime
        info = get_runtime().execution_info
    except Exception:
        return step
    if info is None:
        return step
    return {**step, "thread_id": info.thread_id, "checkpoint_ns": info.checkpoint_ns,
            "checkpoint_id": info.checkpoint_id, "task_id": info.task_id, "node_attempt": info.node_attempt}


KERNEL_MODULES = ("graph_substrate.py", "effect_ledger.py", "graph_nodes.py", "graph_registry.py", "graph_environment.py",
                  "langgraph_runtime.py")
_KERNEL_SHA: dict = {}


def kernel_module_sha256():
    if not _KERNEL_SHA:
        here = Path(__file__).resolve().parent
        _KERNEL_SHA.update({name: hashlib.sha256((here / name).read_bytes()).hexdigest()
                            for name in KERNEL_MODULES if (here / name).is_file()})
    return dict(_KERNEL_SHA)


def _node_name():
    try:
        from langgraph.config import get_config
        return get_config().get("metadata", {}).get("langgraph_node")
    except Exception:
        return None


def stop_requested(scope_root):
    return (Path(scope_root) / STOP).exists()


# ---- the scope runner lock and in-flight effects ----------------------------------------------

# Real paths of the scope roots whose runner lock this process holds (graph_substrate.scope_runner).
_HELD_SCOPES: set[str] = set()
# Call ids whose function is executing in this process.
_INFLIGHT: set[str] = set()
_INFLIGHT_GUARD = threading.Lock()


@contextmanager
def holding_scope(scope_root):
    """Mark the scope's runner lock as held by this process for the block."""
    key = os.path.realpath(scope_root)
    _HELD_SCOPES.add(key)
    try:
        yield
    finally:
        _HELD_SCOPES.discard(key)


@contextmanager
def _scope_exclusive(root):
    """The scope runner lock for a reconciliation: already held here, or taken now without waiting."""
    if os.path.realpath(root) in _HELD_SCOPES:
        yield
        return
    lock = root / SCOPE_LOCK
    lock.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise agent_graph.GraphError("a runner holds the scope; reconcile through ravel graph respond or "
                                         "after the runner drains") from None
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


# ---- re-entrant scope lock -------------------------------------------------------------------

_REENTRANT: dict[str, list] = {}
_REENTRANT_GUARD = threading.Lock()


@contextmanager
def reentrant_lock(lock_path, *, admission=False, timeout=LOCK_TIMEOUT_SECONDS):
    """A process-wide re-entrant mutex keyed by the real path plus one ``flock`` per process.

    Nested calls and other threads of the holding process wait on the mutex (with
    ``timeout``) instead of being refused; another process is refused at once when
    ``admission`` is true and waits up to ``timeout`` otherwise. This is the primitive
    of the campaign lock.
    """
    target = Path(lock_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    key = os.path.realpath(target)
    with _REENTRANT_GUARD:
        slot = _REENTRANT.setdefault(key, [threading.RLock(), 0, None])
    mutex = slot[0]
    if not mutex.acquire(timeout=timeout):
        raise agent_graph.GraphError(f"timed out waiting for {target.name} inside this process")
    try:
        if slot[1] == 0:
            descriptor = os.open(target, os.O_RDWR | os.O_CREAT, 0o600)
            deadline = time.monotonic() + (0.0 if admission else timeout)
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        os.close(descriptor)
                        raise agent_graph.GraphError(f"another process owns {target.name}") from None
                    time.sleep(0.02)
            slot[2] = descriptor
        slot[1] += 1
        try:
            yield
        finally:
            slot[1] -= 1
            if slot[1] == 0:
                fcntl.flock(slot[2], fcntl.LOCK_UN)
                os.close(slot[2])
                slot[2] = None
    finally:
        mutex.release()


# ---- charges, validators -------------------------------------------------------------------

# name -> (present(scope_root, identity) -> bool, apply(scope_root, identity, amount) -> None)
_CHARGE_LEDGERS: dict[str, tuple[Callable, Callable]] = {}
# downstream kind -> validator(scope_root, receipt, document) -> result (raises to refuse)
_VALIDATORS: dict[str, Callable] = {}


def register_charge_ledger(name, *, present, apply):
    """Bind ``run_ceilings`` or ``campaign`` to its owner's idempotent charge functions."""
    if name not in CHARGE_LEDGERS:
        raise agent_graph.GraphError(f"charge ledger must be one of {CHARGE_LEDGERS}")
    _CHARGE_LEDGERS[name] = (present, apply)


def register_validator(kind, validator):
    """The typed validator through which ``auto_reconcile`` reads a ``downstream.kind`` receipt."""
    if type(kind) is not str or not KIND.fullmatch(kind) or not callable(validator):
        raise agent_graph.GraphError("validator needs a kind and a callable")
    _VALIDATORS[kind] = validator


@contextmanager
def registrations(*, charge_ledgers=None, validators=None):
    """Temporary bindings for a block (tests and fixtures)."""
    before = dict(_CHARGE_LEDGERS), dict(_VALIDATORS)
    for name, pair in (charge_ledgers or {}).items():
        register_charge_ledger(name, present=pair[0], apply=pair[1])
    for kind, function in (validators or {}).items():
        register_validator(kind, function)
    try:
        yield
    finally:
        _CHARGE_LEDGERS.clear(); _CHARGE_LEDGERS.update(before[0])
        _VALIDATORS.clear(); _VALIDATORS.update(before[1])


def _charges(charges):
    found = []
    for charge in charges or ():
        if type(charge) is not dict or set(charge) != {"ledger", "amount"} or charge["ledger"] not in CHARGE_LEDGERS:
            raise agent_graph.GraphError("charge must be {ledger: run_ceilings|campaign, amount}")
        if charge["ledger"] not in _CHARGE_LEDGERS:
            raise agent_graph.GraphError(f"charge ledger {charge['ledger']} is not bound")
        digest(charge["amount"])
        found.append({"ledger": charge["ledger"], "amount": deepcopy(charge["amount"]), "applied": False})
    return found


def _apply_charges(root, record):
    """Apply each intended charge once, keyed by the call id; record it as applied."""
    for charge in record["charges"]:
        if charge["applied"]:
            continue
        if charge["ledger"] not in _CHARGE_LEDGERS:
            raise agent_graph.GraphError(f"charge ledger {charge['ledger']} is not bound")
        present, apply = _CHARGE_LEDGERS[charge["ledger"]]
        if not present(root, record["call_id"]):
            apply(root, record["call_id"], deepcopy(charge["amount"]))
        charge["applied"] = True
        _write(root, record)


def _downstream(downstream):
    if downstream is None:
        return None
    if (type(downstream) is not dict or set(downstream) != {"kind", "path"}
            or type(downstream["kind"]) is not str or not KIND.fullmatch(downstream["kind"])
            or type(downstream["path"]) is not str or not downstream["path"].strip()
            or Path(downstream["path"]).is_absolute() or ".." in Path(downstream["path"]).parts):
        raise agent_graph.GraphError("downstream must be {kind, path} with a scope-relative path")
    return dict(downstream)


def _pin_evidence(root, path_text):
    target = root / path_text
    if any(p.is_symlink() for p in (target, *target.parents)) or not target.is_file():
        return None
    data = target.read_bytes()
    return {"path": path_text, "sha256": hashlib.sha256(data).hexdigest()}, data


def _group_alive(pgid):
    try:
        os.killpg(int(pgid), 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, OverflowError):
        return True


def _validated_downstream(root, saved, *, closing=False):
    """The downstream receipt's result through its typed validator, or None.

    Refused: no registered validator, a different identity digest, an older
    cancellation epoch than the reservation, or a ``pgid``/``child_pgid`` still
    alive. Closing an open effect also needs the current cancellation epoch: a
    receipt written before the latest ``stop --now`` is kept as historical.
    """
    downstream = saved.get("downstream")
    if not downstream or downstream["kind"] not in _VALIDATORS:
        return None
    pinned = _pin_evidence(root, downstream["path"])
    if pinned is None:
        return None
    pin, data = pinned
    try:
        document = json.loads(data)
    except ValueError:
        return None
    if type(document) is not dict:
        return None
    if document.get("identity_sha256") != saved["identity_sha256"]:
        return None
    try:
        written = int((document.get("epoch") or {}).get("cancellation", -1))
    except (TypeError, ValueError):
        return None
    if written < saved["epoch"]["cancellation"]:
        return None
    if any(document.get(key) is not None and _group_alive(document[key]) for key in ("pgid", "child_pgid")):
        return None
    if closing and written < epoch(root)["cancellation"]:
        return {"stale": {"pin": pin, "epoch": {"cancellation": written}, "observed_utc": _utc()}}
    try:
        outcome = _VALIDATORS[downstream["kind"]](root, deepcopy(saved), deepcopy(document))
    except Exception:
        return None
    if type(outcome) is not dict or outcome.get("status") not in {"completed", "failed"}:
        return None
    return {"pin": pin, "status": outcome["status"], "result": outcome.get("result")}


def _revalidate(root, saved, revalidate):
    if digest(saved["result"]) != saved.get("result_sha256"):
        raise agent_graph.GraphError("effect receipt result changed")
    for pin in (saved["result"].get("pins") or []) if type(saved["result"]) is dict else []:
        found = _pin_evidence(root, pin["path"]) if type(pin) is dict and "path" in pin else None
        if found is None or found[0]["sha256"] != pin.get("sha256"):
            raise agent_graph.GraphError(f"effect output pin changed: {pin}")
    if saved.get("downstream"):
        if saved["downstream"]["kind"] not in _VALIDATORS:
            raise agent_graph.GraphError(f"effect declares a {saved['downstream']['kind']} downstream receipt "
                                         "but no validator is registered for it")
        checked = _validated_downstream(root, saved)
        if checked is None or checked["status"] != "completed":
            raise agent_graph.GraphError("effect downstream receipt no longer validates")
    if revalidate is not None:
        revalidate(deepcopy(saved))
    return deepcopy(saved["result"])


def _declared_change(saved, graph, identity):
    if saved["graph"]["version"] != graph["version"]:
        return True
    old_card = (saved.get("identity") or {}).get("card") or {}
    new_card = identity.get("card") or {}
    return old_card.get("version") != new_card.get("version")


# ---- the call ------------------------------------------------------------------------------

def call(scope_root, *, graph, path, kind, identity, provisioning, function: Callable[[], object],
         charges: Sequence[dict] = (), downstream=None, revalidate=None, max_attempts=1, node_id=None,
         drift=None):
    """Run ``function`` at most once per domain path and attempt; return its receipted result.

    ``graph`` is ``{id, version}``; the version is recorded, not keyed. ``identity``
    defines equality; ``provisioning`` is recorded and never compared. A provisioning
    difference on reuse is appended to ``drift`` (a list) and to the receipt's reuses.
    """
    agent_tripwire.check('effect_ledger.call')
    root = _scope(scope_root)
    if (type(graph) is not dict or set(graph) != {"id", "version"} or type(graph["id"]) is not str
            or type(graph["version"]) is not int or graph["version"] < 0):
        raise agent_graph.GraphError("graph must be {id, version}")
    if kind not in KINDS:
        raise agent_graph.GraphError(f"effect kind must be one of {KINDS}")
    if type(identity) is not dict or type(provisioning) is not dict:
        raise agent_graph.GraphError("identity and provisioning must be JSON objects")
    if kind in DETERMINISTIC and not identity.get("implementation_sha256"):
        raise agent_graph.GraphError("check and compute effects name their implementation_sha256")
    if type(max_attempts) is not int or max_attempts < 1:
        raise agent_graph.GraphError("max_attempts must be a positive integer")
    identity_sha = digest({**identity, "kind": kind})
    provisioning_sha = digest(provisioning)
    downstream = _downstream(downstream)
    sid = scope_id(root)
    with file_lock(root / LOCK):
        history = _repair_supersession(root, attempts(root, path))
        saved = history[-1] if history else None
        supersedes = None
        if saved is not None:
            status = saved["status"]
            if status == "completed":
                if saved["identity_sha256"] == identity_sha:
                    result = _revalidate(root, saved, revalidate)
                    _record_reuse(root, saved, graph, provisioning, provisioning_sha, drift)
                    return result
                if _declared_change(saved, graph, identity) or kind in DETERMINISTIC:
                    supersedes = saved
                else:
                    raise NondeterministicRequest(
                        "completed effect re-entered with a different identity and no declared version change; "
                        "bump the graph or card version", saved["call_id"])
            elif status in OPEN:
                closed = _auto_reconcile_locked(root, saved)
                if closed is not None and closed["status"] == "completed" and closed["identity_sha256"] == identity_sha:
                    return deepcopy(closed["result"])
                raise Ambiguous("started effect has no receipted outcome; reconcile it, never re-dispatch",
                                saved["call_id"])
            elif status == "reserving":
                if saved["identity_sha256"] != identity_sha:
                    raise NondeterministicRequest("reserved effect re-entered with a different identity",
                                                  saved["call_id"])
                record = saved
            elif status in RETRYABLE:
                used = sum(1 for r in history if r["status"] in RETRYABLE)
                if used >= max_attempts:
                    raise CallFailed(f"effect path exhausted its {max_attempts} attempt(s); decision turn required",
                                     saved["call_id"])
            elif status != "superseded":
                raise agent_graph.GraphError(f"unknown effect status {status!r}")
        if saved is None or saved["status"] != "reserving":
            # Monotonic: one past the highest attempt ever recorded on the path.
            number = 1 + max((r["attempt"] for r in history), default=0)
            identifier = call_id(sid, path, number)
            record = {"schema_version": SCHEMA_VERSION, "call_id": identifier, "node_id": node_id or _node_name(),
                      "attempt_id": None, "request_sha256": identity_sha, "kind": kind,
                      "output_tokens_reserved": 0, "status": "reserving",
                      "graph": dict(graph), "path": path, "attempt": number,
                      "identity": deepcopy(identity), "identity_sha256": identity_sha,
                      "provisioning": deepcopy(provisioning), "provisioning_sha256": provisioning_sha,
                      "epoch": epoch(root), "framework_step": framework_step(),
                      "charges": _charges(charges), "downstream": downstream,
                      "supersedes": supersedes["call_id"] if supersedes else None, "superseded_by": None,
                      "reuses": [], "reserved_utc": _utc()}
            _write(root, record)
            if supersedes is not None:
                _write(root, {**supersedes, "status": "superseded", "superseded_by": identifier})
        _apply_charges(root, record)
        record = {**record, "status": "started", "started_utc": _utc()}
        _write(root, record)
    began = time.monotonic()
    identifier = record["call_id"]
    with _INFLIGHT_GUARD:
        _INFLIGHT.add(identifier)
    try:
        dispatched = False
        try:
            value = function()
            dispatched = True
            result_sha = digest(value)
        except Exception as exc:
            # After dispatch the action may have committed: retry only on a typed
            # NotDispatched before the function returned, or for a deterministic kind.
            ambiguous = bool(getattr(exc, "ambiguous", False)) or (kind not in DETERMINISTIC and (
                dispatched or not getattr(exc, "not_dispatched", False)))
            outcome = {**record, "status": "ambiguous" if ambiguous else "failed", "error_type": type(exc).__name__,
                       "retryable": bool(getattr(exc, "retryable", False)) and not ambiguous,
                       "elapsed_seconds": time.monotonic() - began}
            _write_outcome(root, outcome)
            if ambiguous and not isinstance(exc, Ambiguous):
                raise Ambiguous(str(exc), identifier) from exc
            raise
        outcome = {**record, "status": "completed", "result": value, "result_sha256": result_sha,
                   "elapsed_seconds": time.monotonic() - began, "completed_utc": _utc()}
        # Durable before LangGraph adopts the node's writes.
        _write_outcome(root, outcome)
    finally:
        with _INFLIGHT_GUARD:
            _INFLIGHT.discard(identifier)
    return deepcopy(value)


def _write_outcome(root, outcome):
    """Write the outcome only over this process's own ``started`` record.

    A record closed meanwhile (an explicit reconciliation) is kept; the outcome is
    appended to its ``late_outcomes`` and the effect is reported ambiguous.
    """
    with file_lock(root / LOCK):
        current = read(root, outcome["call_id"])
        if current is not None and current["status"] != "started":
            late = {"status": outcome["status"], "result_sha256": outcome.get("result_sha256"),
                    "error_type": outcome.get("error_type"), "observed_utc": _utc()}
            _write(root, {**current, "late_outcomes": (current.get("late_outcomes") or []) + [late]})
            raise Ambiguous(f"effect was closed as {current['status']} while it ran; its own outcome is kept "
                            "as a late outcome", outcome["call_id"])
        _write(root, outcome)


def _repair_supersession(root, history):
    """Finish a supersession interrupted between the successor and predecessor writes."""
    by_id = {r["call_id"]: r for r in history}
    for record in history:
        before = by_id.get(record.get("supersedes"))
        if before is not None and before["status"] != "superseded":
            repaired = {**before, "status": "superseded", "superseded_by": record["call_id"]}
            _write(root, repaired)
            by_id[before["call_id"]] = repaired
    return [by_id[r["call_id"]] for r in history]


def _record_reuse(root, saved, graph, provisioning, provisioning_sha, drift):
    changed = sorted(k for k in set(saved.get("provisioning") or {}) | set(provisioning)
                     if (saved.get("provisioning") or {}).get(k) != provisioning.get(k))
    entry = {"utc": _utc(), "graph_version": graph["version"], "framework_step": framework_step(),
             "provisioning_sha256": provisioning_sha, "provisioning_drift": changed}
    if changed and drift is not None:
        drift.append({"call_id": saved["call_id"], "path": saved["path"], "keys": changed})
    reuses = (saved.get("reuses") or [])[-(MAX_REUSES - 1):] + [entry]
    _write(root, {**saved, "reuses": reuses})


def recover(scope_root):
    """Runner start: apply the missing charges of every ``reserving`` record (its function never ran)."""
    root = _scope(scope_root)
    finished, open_ = [], []
    with file_lock(root / LOCK):
        for index in sorted((root / INDEX).glob("*.json")) if (root / INDEX).is_dir() else ():
            found = [read(root, e["call_id"]) for e in read_json(index)["attempts"]]
            _repair_supersession(root, [r for r in found if r is not None])
        for saved in receipts(root):
            if saved.get("status") == "reserving":
                _apply_charges(root, saved)
                finished.append(saved["call_id"])
            elif saved.get("status") in OPEN:
                open_.append(saved["call_id"])
    return {"reserving_recovered": finished, "ambiguous": open_}


def _auto_reconcile_locked(root, saved):
    if saved["status"] not in OPEN:
        return None
    checked = _validated_downstream(root, saved, closing=True)
    if checked is None:
        return None
    if "stale" in checked:
        historical = [h for h in saved.get("historical_downstream") or [] if h["pin"] != checked["stale"]["pin"]]
        _write(root, {**saved, "historical_downstream": historical + [checked["stale"]]})
        return None
    reconciliation = {"outcome": checked["status"], "evidence": [checked["pin"]], "auto": True,
                      "reason": f"closed from downstream {saved['downstream']['kind']} receipt through its validator",
                      "truth_authenticated": False}
    record = {**saved, "status": checked["status"], "reconciliation": reconciliation}
    if checked["status"] == "completed":
        result = checked["result"] if checked["result"] is not None else {"downstream": checked["pin"]}
        record.update(result=result, result_sha256=digest(result))
    _write(root, record)
    return record


def auto_reconcile(scope_root, identifier):
    """Close a started effect from its downstream receipt, only through the typed validator."""
    root = _scope(scope_root)
    with file_lock(root / LOCK):
        saved = read(root, identifier)
        if saved is None:
            raise agent_graph.GraphError("unknown effect call id")
        return _auto_reconcile_locked(root, saved)


def reconcile(scope_root, identifier, *, outcome, evidence, reason, result=None):
    """Record an explicit evidence-pinned resolution of a started or ambiguous effect.

    ``completed`` closes the attempt with its result; ``failed`` and ``not_dispatched``
    (status ``reconciled``) let a later attempt proceed within the retry bound.
    Evidence custody is checked (path inside the scope, digest equal), not its truth.
    Runs under the scope runner lock (held here or taken without waiting) and
    refuses an effect whose function is still executing in this process.
    """
    root = _scope(scope_root)
    if outcome not in OUTCOMES:
        raise agent_graph.GraphError("reconciliation outcome must be completed, not_dispatched or failed")
    if type(reason) is not str or not reason.strip() or len(reason) > 4000:
        raise agent_graph.GraphError("reconciliation reason required")
    if type(evidence) is not list or not evidence:
        raise agent_graph.GraphError("reconciliation requires evidence pins")
    pins = []
    for pin in evidence:
        if type(pin) is not dict or set(pin) != {"path", "sha256"}:
            raise agent_graph.GraphError("evidence pin must be {path, sha256}")
        _downstream({"kind": "evidence", "path": pin["path"]})
        pinned = _pin_evidence(root, pin["path"])
        if pinned is None or pinned[0]["sha256"] != pin["sha256"]:
            raise agent_graph.GraphError(f"evidence pin does not match {pin['path']}")
        pins.append(pinned[0])
    if (outcome == "completed") != (result is not None):
        raise agent_graph.GraphError("only a completed reconciliation carries its result")
    with _scope_exclusive(root), file_lock(root / LOCK):
        with _INFLIGHT_GUARD:
            if identifier in _INFLIGHT:
                raise agent_graph.GraphError("effect is in flight in this process; it cannot be reconciled")
        saved = read(root, identifier)
        if saved is None or saved["status"] not in OPEN:
            raise agent_graph.GraphError("only a started or ambiguous effect can be reconciled")
        status = {"completed": "completed", "failed": "failed", "not_dispatched": "reconciled"}[outcome]
        record = {**saved, "status": status,
                  "reconciliation": {"outcome": outcome, "evidence": pins, "reason": reason, "auto": False,
                                     "truth_authenticated": False}}
        if result is not None:
            record.update(result=result, result_sha256=digest(result))
        _write(root, record)
    return record


# ---- the worker-delegation API (stable) -----------------------------------------------------------

DELEGATION_GRAPH = "agent_graph"


def delegated_path(graph_id, attempt_id, label):
    """The domain path of an ``agent_graph`` call: one path per legacy call id."""
    if type(graph_id) is not str or not graph_id.strip():
        raise agent_graph.GraphError("delegated graph id required")
    return path(DELEGATION_GRAPH, {"graph_id": graph_id}, None, {"call": legacy_call_id(attempt_id, label)})


def delegated(scope_root, graph_id, attempt_id, label):
    """The latest receipt of a delegated call, or None."""
    return latest(scope_root, delegated_path(graph_id, attempt_id, label))


def delegate(scope_root, *, graph_id, attempt_id, label, kind, request, function: Callable[[], object],
             graph_version=0, charges: Sequence[dict] = (), downstream=None, revalidate=None, max_attempts=1,
             node_id=None, drift=None):
    """``call`` for an ``agent_graph`` host call or worker dispatch.

    ``kind`` is a key of ``LEGACY_KINDS`` or an effect kind. The identity is the legacy
    call id plus the request digest, so a changed request on the same label is
    ``NondeterministicRequest``; the legacy kind is kept as provisioning.
    """
    effect_kind = LEGACY_KINDS.get(kind, kind)
    if effect_kind not in KINDS or effect_kind in DETERMINISTIC:
        raise agent_graph.GraphError(f"delegated kind must be one of {sorted(LEGACY_KINDS)} or a "
                                     "non-deterministic effect kind")
    identity = {"legacy_call_id": legacy_call_id(attempt_id, label), "request_sha256": agent_graph.digest(request)}
    return call(scope_root, graph={"id": DELEGATION_GRAPH, "version": graph_version},
                path=delegated_path(graph_id, attempt_id, label), kind=effect_kind, identity=identity,
                provisioning={"legacy_kind": kind, "graph_id": graph_id}, function=function, charges=charges,
                downstream=downstream, revalidate=revalidate, max_attempts=max_attempts, node_id=node_id, drift=drift)


def verified_result(scope_root, identifier, *, revalidate=None):
    """The result of a completed effect after the reuse checks (result digest, output
    pins, downstream validator, ``revalidate``); refused otherwise."""
    root = _scope(scope_root)
    with file_lock(root / LOCK):
        saved = read(root, identifier)
        if saved is None or saved["status"] != "completed":
            raise agent_graph.GraphError(f"effect {identifier} is not completed")
        return _revalidate(root, saved, revalidate)


def deliver_external(scope_root, identifier, *, receipt, reason):
    """Close a paused or interrupted effect from its producer's receipt.

    ``receipt`` is ``{status: completed|failed, result?, call_id?, request_sha256?}``;
    its ``call_id`` and ``request_sha256``, when present, must correlate with the
    reservation's identity. The receipt is pinned under ``calls/evidence/`` and applied
    through ``reconcile`` (scope lock, never an in-flight effect).
    """
    root = _scope(scope_root)
    if type(receipt) is not dict or receipt.get("status") not in {"completed", "failed"}:
        raise agent_graph.GraphError("external receipt must have status completed or failed")
    saved = read(root, identifier)
    if saved is None:
        raise agent_graph.GraphError("unknown effect call id")
    identity = saved.get("identity") or {}
    for key in ("call_id", "request_sha256"):
        expected = identity.get("legacy_call_id" if key == "call_id" else key)
        if key in receipt and receipt[key] != expected:
            raise agent_graph.GraphError(f"external receipt {key} does not correlate with the reservation")
    if not any(key in receipt for key in ("call_id", "request_sha256")):
        raise agent_graph.GraphError("external receipt must correlate by call_id or request_sha256")
    evidence = root / EVIDENCE / (identifier + ".json")
    if any(p.is_symlink() for p in (evidence.parent, evidence.parent.parent)):
        raise agent_graph.GraphError("evidence directory cannot be a symlink")
    atomic_json(evidence, receipt)
    pin = {"path": str(evidence.relative_to(root)), "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}
    completed = receipt["status"] == "completed"
    return reconcile(root, identifier, outcome="completed" if completed else "failed", evidence=[pin],
                     reason=reason, result=deepcopy(receipt.get("result")) if completed else None)


def receipts(scope_root, *, graph_id=None, thread_id=None, prefix=None):
    root = Path(scope_root) / CALLS
    found = []
    for receipt in sorted(root.glob("*.json")) if root.is_dir() else ():
        saved = read_json(receipt)
        if graph_id is not None and (saved.get("graph") or {}).get("id") != graph_id:
            continue
        if thread_id is not None and (saved.get("framework_step") or {}).get("thread_id") != thread_id:
            continue
        if prefix is not None and not str(saved.get("path", "")).startswith(prefix):
            continue
        found.append(saved)
    return found


def usage(scope_root, prefix):
    """Counts derived from receipts under a path prefix (never from summed channels)."""
    tally = {status: 0 for status in STATUSES}
    charged = {}
    for saved in receipts(scope_root, prefix=prefix):
        tally[saved["status"]] = tally.get(saved["status"], 0) + 1
        for charge in saved.get("charges") or ():
            if charge["applied"] and type(charge["amount"]) in (int, float):
                charged[charge["ledger"]] = charged.get(charge["ledger"], 0) + charge["amount"]
    return {"prefix": prefix, "status": tally, "charged": charged}


def counts(scope_root, **filters):
    tally = {"completed": 0, "started": 0, "ambiguous": 0, "reserving": 0}
    for saved in receipts(scope_root, **filters):
        if saved["status"] == "superseded":
            continue
        tally[saved["status"]] = tally.get(saved["status"], 0) + 1
    return tally
