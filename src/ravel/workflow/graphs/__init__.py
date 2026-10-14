"""Registered subsystem graphs built on the graph substrate.

Shared here: the in-process host registry (a host is a live object, never graph state),
and the adapter that turns a research service's exception into a typed failure the
builder's own handler routes (§1.8).
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import threading

from .. import graph_nodes
from ..agent_graph import AmbiguousCall, GraphError

_HOSTS: dict = {}
_HOSTS_LOCK = threading.Lock()


def host_key(host):
    from ..agent_graph import _host_identity
    return _host_identity(host)


@contextmanager
def hosts(host):
    """Make ``host`` available to graph nodes for the block; yields its key (the host identity digest)."""
    key = host_key(host)
    with _HOSTS_LOCK:
        previous = _HOSTS.get(key)
        _HOSTS[key] = host
    try:
        yield key
    finally:
        with _HOSTS_LOCK:
            if previous is None:
                _HOSTS.pop(key, None)
            else:
                _HOSTS[key] = previous


def host(key):
    with _HOSTS_LOCK:
        found = _HOSTS.get(key)
    if found is None:
        raise graph_nodes.RecoveryHold("host_unavailable",
                                       "continue through: ravel research-orchestrate run --engine graph "
                                       "with the run's host configuration")
    return found


class DeliveryRequired(GraphError):
    """A node waits for an ordinary outside effect (a host delivery, an approval, a stage run).

    Nothing was dispatched by this attempt that the service's own custody does not
    reconcile on re-entry, so the effect path may run again after the delivery.
    """
    not_dispatched = True

    def __init__(self, payload):
        self.payload = payload
        text = json.dumps(payload, sort_keys=True, default=str)
        super().__init__(text[:1900])
        self.would_make_possible = "deliver the ordinary effect " + str((payload or {}).get("kind"))


class ServiceRefused(GraphError):
    """A research service refused or failed before committing an effect it cannot reconcile.

    The research services are re-entrant through their own receipts (agent Graph calls,
    campaign commits, pinned emissions); an unknown started call surfaces as
    ``AmbiguousCall`` and is never wrapped.
    """
    not_dispatched = True

    def __init__(self, error):
        self.error_type = type(error).__name__
        super().__init__(f"{self.error_type}: {error}"[:1900])


def pause(payload):
    """The substrate form of a legacy interrupt: a typed delivery turn, never a dead end."""
    raise DeliveryRequired(payload)


def service(function):
    """Call a research service; classify its failure for the builder's handler."""
    from ..research_orchestrator import RecoveryHold
    try:
        return function()
    except (AmbiguousCall, DeliveryRequired, ServiceRefused, graph_nodes.RecoveryHold):
        raise
    except RecoveryHold as exc:
        raise graph_nodes.RecoveryHold("research_service_hold", str(exc)[:1000]) from exc
    except Exception as exc:
        if getattr(exc, "not_dispatched", False):
            raise
        raise ServiceRefused(exc) from exc
