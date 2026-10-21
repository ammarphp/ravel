"""Runtime tripwire: the lowest layers assert a substrate context.

Every substrate node body runs with ``graph_nodes.TRIPWIRE`` set to its node record
``{ravel_kind, graph_id, role, node}``. A lowest layer (provider transport, CLI
launcher, worker launch, broker call, effect ledger, ``authorized_popen``) calls
``check(layer)`` first. ``1`` or ``block`` raises ``TripwireViolation`` when there is no
substrate context or the node kind may not reach that layer; ``report`` records the same
verdict without raising. In a controller process (``declare_controller_process``, or inside
``controller_scope``) the tripwire always blocks: ``RAVEL_AGENT_TRIPWIRE`` cannot lower it
there, and a lower request is kept in the verdict as ``requested_mode``. Elsewhere it is off
unless the variable sets it. Verdicts are kept in-process and, when
``RAVEL_AGENT_TRIPWIRE_RECORD`` names a file, appended to it as JSON lines.

This module never imports LangGraph: when ``graph_nodes`` has not been imported, no
substrate node can be running, so the context is absent. The layer table lives in
``data/agents/sanctioned.json`` (``tripwire_layers``). A static census can miss a
dynamic path; this check is the runtime backstop, not a proof of coverage.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
import json
import os
import sys
import threading

from ravel.paths import package_data_path

ENV = "RAVEL_AGENT_TRIPWIRE"
RECORD_ENV = "RAVEL_AGENT_TRIPWIRE_RECORD"
OFF = ("", "0")
_LOCK = threading.Lock()
OBSERVED: list[dict] = []
# Runs the controller drives in this process. A declaration lasts for the process: there is
# no call that lowers the tripwire again.
_CONTROLLER_RUNS: list[str] = []
_DECLARED: list[str] = []


def declare_controller_process(run_id):
    """Mark this process as the controller of ``run_id``; the tripwire blocks from now on."""
    with _LOCK:
        if str(run_id) not in _DECLARED:
            _DECLARED.append(str(run_id))


@contextmanager
def controller_scope(run_id):
    """While the controller drives ``run_id`` here, the tripwire blocks whatever the environment says."""
    with _LOCK:
        _CONTROLLER_RUNS.append(str(run_id))
    try:
        yield
    finally:
        with _LOCK:
            _CONTROLLER_RUNS.remove(str(run_id))


def controller_process():
    """Whether this process runs a controller-owned run's graph (declared or scoped)."""
    with _LOCK:
        return bool(_DECLARED or _CONTROLLER_RUNS)


def effective_mode():
    """``(mode, requested)``: ``block`` in a controller process, else the variable's request."""
    requested = os.environ.get(ENV, "").strip().lower()
    if controller_process() and requested not in ("1", "block"):
        return "block", requested
    return requested, requested


class TripwireViolation(RuntimeError):
    """A lowest layer was reached outside a substrate node that may act on it."""


@lru_cache(maxsize=1)
def _layers():
    document = json.loads(package_data_path("agents", "sanctioned.json").read_text())
    return {row["layer"]: tuple(row["acting_kinds"]) for row in document["tripwire_layers"]}


def context():
    """The running substrate node record, or None outside every node body."""
    nodes = sys.modules.get("ravel.workflow.graph_nodes")
    return None if nodes is None else nodes.TRIPWIRE.get()


def check(layer: str):
    """Assert a substrate context at ``layer``; returns the verdict, or None when the tripwire is off."""
    mode, requested = effective_mode()
    if mode in OFF:
        return None
    layers = _layers()
    if layer not in layers:
        raise ValueError(f"unknown tripwire layer {layer!r}; declare it in data/agents/sanctioned.json")
    current = context()
    if current is None:
        ok, reason = False, "no_substrate_context"
    elif current.get("ravel_kind") not in layers[layer]:
        ok, reason = False, f"kind {current.get('ravel_kind')} may not reach {layer}"
    else:
        ok, reason = True, None
    verdict = {"layer": layer, "ok": ok, "reason": reason, "mode": mode,
               "context": dict(current) if current else None}
    if requested != mode:
        verdict["requested_mode"] = requested  # a controller process ignored a lower request
    with _LOCK:
        OBSERVED.append(verdict)
        target = os.environ.get(RECORD_ENV)
        if target:
            with open(target, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(verdict, sort_keys=True, default=str) + "\n")
    if not ok and mode != "report":
        raise TripwireViolation(f"G8 tripwire at {layer}: {reason}")
    return verdict
