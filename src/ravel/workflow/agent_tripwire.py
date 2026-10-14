"""Runtime tripwire: the lowest layers assert a substrate context.

Every substrate node body runs with ``graph_nodes.TRIPWIRE`` set to its node record
``{ravel_kind, graph_id, role, node}``. A lowest layer (provider transport, CLI
launcher, worker launch, broker call, effect ledger, ``authorized_popen``) calls
``check(layer)`` first. With ``RAVEL_AGENT_TRIPWIRE`` unset or ``0`` it does nothing;
``1`` or ``block`` raises ``TripwireViolation`` when there is no substrate context
or the node kind may not reach that layer; ``report`` records the same verdict
without raising. Verdicts are kept in-process and, when ``RAVEL_AGENT_TRIPWIRE_RECORD``
names a file, appended to it as JSON lines.

This module never imports LangGraph: when ``graph_nodes`` has not been imported, no
substrate node can be running, so the context is absent. The layer table lives in
``data/agents/sanctioned.json`` (``tripwire_layers``). A static census can miss a
dynamic path; this check is the runtime backstop, not a proof of coverage.
"""
from __future__ import annotations

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
    mode = os.environ.get(ENV, "").strip().lower()
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
    with _LOCK:
        OBSERVED.append(verdict)
        target = os.environ.get(RECORD_ENV)
        if target:
            with open(target, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(verdict, sort_keys=True, default=str) + "\n")
    if not ok and mode != "report":
        raise TripwireViolation(f"G8 tripwire at {layer}: {reason}")
    return verdict
