"""The analysis check-in views through the authority service's typed renderer (``checkin.v1``).

The controller merges the route's part of a view (sections, required sections, flags, items, pins)
into the view it hands the authority service, which renders the check-in and refuses one that drops a
section, flag or pin. These tests render every analysis check-in kind through the real renderer and
validator. They need the authority service; a worktree without it skips this file at collection.
"""
from __future__ import annotations

import pytest

pytest.importorskip("ravel.controller.authority")
from ravel.controller.authority import checkin as authority_checkin  # noqa: E402
from ravel.controller.routes import analysis  # noqa: E402
from p09_support import (Store, adopt, adopt_prepare, compile_plan, context, contract, grant,  # noqa: E402
                              reading, record_outcome)


def _view(store, route_part, options=()):
    """The view the controller hands the authority service: its own fields plus the route's part."""
    return {"run_id": store.run_id, "pins": dict(route_part.get("pins") or {}) or {"run": store.run_id},
            "sections": list(route_part.get("sections") or []), "flags": list(route_part.get("flags") or []),
            "items": dict(route_part.get("items") or {}), "options": list(options),
            "required_sections": list(route_part.get("required_sections") or []), "summary": "analysis route"}


def _rendered(kind, view):
    artifact = authority_checkin.render(kind, view)
    assert authority_checkin.validate(artifact, view) == []
    assert not [s for s in artifact["sections"] if s.get("missing")], kind
    return artifact


def _prepared(tmp_path, *, scan=False):
    store = Store()
    read, con = reading(scan=scan), contract("scan" if scan else "reproduce")
    plan = compile_plan("analysis.scan" if scan else "analysis", read, con)
    states = adopt_prepare(store, tmp_path, plan, cost_mode="scan" if scan else None)
    plan = analysis.bind(plan, context(store, tmp_path, plan, read, con, states)) or plan
    return store, plan, read, con, states


@pytest.mark.parametrize("scan", [False, True])
def test_a06_checkin1_renders_and_validates_through_the_authority_service(tmp_path, scan):
    store, plan, read, con, states = _prepared(tmp_path, scan=scan)
    part = analysis.checkin("approve_plan", context(store, tmp_path, plan, read, con, states))
    assert part["errors"] == []
    artifact = _rendered("approve_plan", _view(store, part))
    ids = [s["id"] for s in artifact["sections"]]
    assert ids[0] == "preamble" and ids[-1] == "respond" and "plan" in ids and "flags" in ids
    assert set(part["required_sections"]) <= set(ids)


def test_c10_checkin2_renders_with_its_waypoint_pins(tmp_path):
    store, plan, read, con, states = _prepared(tmp_path)
    grant(store, "approve_plan", plan=plan)
    waypoint = next(s for s in plan["steps"] if s["waypoint"])
    adopt(store, tmp_path, waypoint["id"], "outputs/waypoint.json",
          {"summary": "The smoke cutflow agrees.", "element": "first three cutflow rows",
           "expectation": "within ten percent", "evidence": "within six percent"})
    record_outcome(store, waypoint)
    part = analysis.checkin("go", context(store, tmp_path, plan, read, con, states))
    assert part["errors"] == []
    _rendered("go", _view(store, part))


def test_deviation_and_escalation_views_render(tmp_path):
    store, plan, read, con, states = _prepared(tmp_path)
    deviation = analysis.checkin("deviation", context(store, tmp_path, plan, read, con, states))
    view = _view(store, deviation)
    view["pins"]["approve_plan"] = "authority-fixture"
    _rendered("deviation", view)
    ctx = context(store, tmp_path, plan, read, con, states)
    ctx["state"]["escalations"] = {"recast.smoke": {"status": "pending", "escalation": "decision_block",
                                                    "reason": "the routine's lepton definition is ambiguous"}}
    escalation = analysis.checkin("r3_action", ctx)
    _rendered("r3_action", _view(store, escalation, options=[{"id": "continue", "text": "run again"},
                                                             {"id": "hold", "text": "hold", "effect": False}]))
