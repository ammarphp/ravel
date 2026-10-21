"""Read-only routes (``inspect``, ``legacy``): questions answered with no scientific effect.

The inspection route answers development and inspection questions about RAVEL or about a run
(CONTROLLER-SPEC 5.3); the legacy route inspects epoch-one and 1.x runs. Their specs admit no
scientific deliverables, so route selection never sends a scientific request to them (R01).
Their plans may contain only read-only steps: a worker reads and writes a document, a reviewer
reads it, or the operator is asked. ``plan_effects`` lists every effect a plan would have and
must be empty for a read-only route; ``guard`` is the per-step check the governed step applies,
so a step added by a replan, or a changed step, cannot introduce an effect either.
"""
from __future__ import annotations

ROUTE_ID = "inspect"
READ_ONLY_ROUTES = ("inspect", "legacy")
READ_ONLY_KINDS = ("synthesize", "review", "ask")
READ_ONLY_OUTPUT_KINDS = ("document",)
READ_ONLY_RUNGS = (None, "none")
# Budget dimensions that measure a scientific effect; a read-only step reserves none of them.
EFFECT_DIMENSIONS = ("events", "core_hours", "cost_usd", "children")
# Step fields that start a launch, a subgraph or a child plan.
EFFECT_FIELDS = ("operation", "graph", "route")


def _effect(step_id, code, detail):
    return {"step": step_id, "code": code, "detail": detail}


def review_artifact(step, output):
    """Recognize a review seat's findings through its effective read-only role contract."""
    if (step.get('kind') != 'review' or output.get('kind') != 'review-findings'
            or (step.get('parameters') or {}).get('seat_kind') != 'review'):
        return False
    from ravel.workflow import role_registry
    try:
        card = role_registry.load(step.get('role'))
    except (ValueError, KeyError, TypeError):
        return False
    return (card['output']['schema'] == 'findings.v2'
            and card['requires']['tools'] == 'broker-readonly')


def step_effects(step: dict) -> list[dict]:
    """Every effect ``step`` would have (empty for a read-only step)."""
    if type(step) is not dict:
        return [_effect(None, "step_malformed", "a step is an object")]
    sid = step.get("id")
    found = []
    if step.get("kind") not in READ_ONLY_KINDS:
        found.append(_effect(sid, "effectful_kind", f"kind {step.get('kind')!r} is not one of {READ_ONLY_KINDS}"))
    for field in EFFECT_FIELDS:
        if step.get(field) not in (None, "", {}):
            found.append(_effect(sid, f"step_{field}", f"a read-only step names no {field}"))
    if step.get("rung") not in READ_ONLY_RUNGS:
        found.append(_effect(sid, "effect_rung", f"rung {step.get('rung')!r} is an execution rung"))
    if step.get("waypoint"):
        found.append(_effect(sid, "waypoint", "a waypoint marks executed evidence"))
    budget = step.get("budget") if type(step.get("budget")) is dict else {}
    for dimension in EFFECT_DIMENSIONS:
        if budget.get(dimension):
            found.append(_effect(sid, "effect_budget", f"budget {dimension}={budget[dimension]} reserves an effect"))
    for output in step.get("outputs") or ():
        kind = output.get("kind") if type(output) is dict else None
        if kind not in READ_ONLY_OUTPUT_KINDS and not (type(output) is dict and review_artifact(step, output)):
            found.append(_effect(sid, "effect_output",
                f"output kind {kind!r} requires a document or its declared read-only review contract"))
    parameters = step.get("parameters") if type(step.get("parameters")) is dict else {}
    for key in ("launch", "task", "effects"):
        if parameters.get(key):
            found.append(_effect(sid, f"parameter_{key}", f"parameters.{key} requests an effect"))
    if step.get("consequence_class") in ("R2", "R3"):
        found.append(_effect(sid, "consequential_action", f"consequence class {step['consequence_class']}"))
    return found


def plan_effects(plan: dict) -> list[dict]:
    """Every effect of a plan's steps and deliverables; empty means the plan has no scientific effect."""
    if type(plan) is not dict:
        return [_effect(None, "plan_malformed", "a plan is an object")]
    found = []
    for step in plan.get("steps") or ():
        found.extend(step_effects(step))
    for row in plan.get("deliverables") or ():
        if type(row) is dict and row.get("status") == "mapped" and row.get("artifact_kind") not in (None, "document"):
            found.append(_effect(row.get("step"), "scientific_deliverable",
                                 f"deliverable {row.get('id')} is a {row.get('artifact_kind')} artifact"))
        if type(row) is dict and row.get("status") == "mapped" and row.get("claim_kind") not in (None, "document"):
            found.append(_effect(row.get("step"), "scientific_claim",
                                 f"deliverable {row.get('id')} makes a {row.get('claim_kind')} claim"))
    if plan.get("waypoints"):
        found.append(_effect(None, "waypoint", "a read-only plan has no execution waypoints"))
    return found


def read_only(plan: dict) -> bool:
    """True when the plan was compiled from a read-only route spec."""
    route = plan.get("route") if type(plan) is dict else None
    return type(route) is dict and route.get("id") in READ_ONLY_ROUTES


def guard(step: dict, plan: dict, *, route: str | None = None) -> list[dict]:
    """The governed step's check: in a read-only run, a step with any effect is refused.

    ``route`` is the route the run state pins (``state.route``); a later plan revision from
    another planner keeps the run read-only, so either pin makes the check apply.
    """
    if route not in READ_ONLY_ROUTES and not read_only(plan):
        return []
    return step_effects(step)


def plan_errors(plan: dict, *, route: str | None = None) -> list[str]:
    """A read-only run's plan with effects is invalid (the compiler's and the replan's check)."""
    if route not in READ_ONLY_ROUTES and not read_only(plan):
        return []
    return [f"{row['step'] or 'plan'}: {row['code']}: {row['detail']}" for row in plan_effects(plan)]
