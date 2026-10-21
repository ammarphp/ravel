"""``RunState``: the typed state of the ``controller.run`` graph (CONTROLLER-SPEC 3.3).

State carries ids, digests and small JSON records only; the bytes they name live in the store
or the run directory and are verified by digest when read. The substrate refuses state that is
not JSON-safe. A resume value is data, never authority.

| Field | Content | Written by |
|---|---|---|
| ``run`` | run id, run directory, store root, composition digest, controller mode, host kind | entry (input) |
| ``request`` | sha256 of the request bytes, channel, reading and contract pins | ``intake`` |
| ``mode`` | frozen operating-mode record id and its bounds | ``intake`` (authority service) |
| ``route`` | route id or ``judgment``, match evidence, route-spec digest | ``route_select`` |
| ``plan`` | plan digest and record id, step ids, dependencies, waypoints, revision count; two identities: the immutable scientific blob and ``sha256``, and with an engagement decision applied its view's ``applied_blob`` and ``applied_sha256`` | plan nodes |
| ``ledger`` | ledger head digest and counts by status and class | obligation ledger |
| ``authority`` | authority record ids per check-in and per R3 action | authority nodes |
| ``steps`` | per step: status, attempts, receipt ids, adopted artifact digests, review credit ids | wave join |
| ``budget`` | reservation ids; used, reserved, unknown per dimension | wave join (from step outcomes) |
| ``judgments`` | judgment record ids with consequence class | judgment and step outcomes |
| ``holds`` | typed holds with reason codes and what would release them | all |
| ``delivery`` | sink receipt id, label set, ``architecture_complete`` as the sink derived it | ``deliver``, ``bounded_end`` |
"""
from __future__ import annotations

from copy import deepcopy
from typing import Annotated

from ..workflow import graph_nodes
from ..workflow.agent_graph import GraphError


def merge(left, right):
    """Dict channel: keys from ``right`` replace those of ``left``; other keys are kept."""
    result = deepcopy(left or {})
    result.update(deepcopy(right or {}))
    return result


def append_ids(left, right):
    """``{key: [ids]}``: lists only grow, in order, without duplicates."""
    result = deepcopy(left or {})
    for key, values in (right or {}).items():
        current = result.setdefault(key, [])
        for value in values or []:
            if value not in current:
                current.append(value)
    return result


def once(left, right):
    """Written once; an equal re-write is accepted, a change is refused."""
    if left and right and left != right:
        raise GraphError("a write-once controller field cannot change")
    return deepcopy(right or left)


class RunState(graph_nodes.BaseState, total=False):
    run: Annotated[dict, once]
    request: Annotated[dict, once]
    mode: Annotated[dict, once]
    route: Annotated[dict, graph_nodes.last_value]
    plan: Annotated[dict, graph_nodes.last_value]
    ledger: Annotated[dict, graph_nodes.last_value]
    authority: Annotated[dict, append_ids]
    steps: Annotated[dict, merge]
    budget: Annotated[dict, graph_nodes.last_value]
    judgments: Annotated[dict, merge]
    holds: Annotated[dict, merge]
    delivery: Annotated[dict, graph_nodes.last_value]
    # Controller bookkeeping: the execution loop's current wave decision, pending escalations and check-in flags.
    loop: Annotated[dict, graph_nodes.last_value]
    escalations: Annotated[dict, merge]
    replans: Annotated[dict, merge]
    flags: Annotated[dict, merge]
    reviews: Annotated[dict, merge]


FIELDS = ("run", "request", "mode", "route", "plan", "ledger", "authority", "steps", "budget", "judgments",
          "holds", "delivery")
