"""The route-spec compiler: a route spec and the request's reading give a typed plan (``plan.v1``).

A route spec's ``steps`` are a template DAG (``step.v1`` fields, plus ``foreach``). The compiler
binds the spec's ``parameters`` from the reading, the contract and the supplied inputs, expands
``foreach`` templates into one step per item, substitutes ``{name}`` placeholders, checks every
step against ``step.v1`` and the DAG (unique ids, known dependencies, acyclic, inputs that name a
step's declared output), and maps every reading deliverable to a step output.

Population equality (R02, R04, R09): every reading deliverable is either mapped to a declared
output of a plan step or kept as an explicit open obligation (``deliverables[].status == open``
and ``open_obligations``); a required parameter the reading does not state is an open
obligation too. Nothing is dropped. The controller sends a plan with open obligations to the
judgment route, which keeps the covered part as a ``route`` step (R05).

Placeholders: ``{<parameter>}`` in any string of a step, and ``{item}``/``{index}`` inside a
``foreach`` template (``{item}`` is the item's ``id`` when it has one; an expanded step's id is
``<template id>.<item>``). A step reference in an input is ``<step id>:<path>``. A placeholder that stays
unresolved in a step id, operation, output path or input is a compile error.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

from .. import schema_errors
from . import select as selection

PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
TEMPLATE_KEYS = ("foreach",)
DEFAULT_STEP = {"inputs": [], "outputs": [], "depends_on": [], "waypoint": False, "rung": None, "budget": {},
                "protocols": [], "review": [], "instruction_sources": [], "obligations": []}
# A step's budget dimension -> the authority budget it counts against (P06 ``BUDGET_KEYS``): one name per resource.
# Broker calls are model calls; ``attempts`` is the step's retry limit, not a resource the authority grants. A
# dimension in neither is a compile error, never dropped.
AUTHORITY_BUDGET = {"wall_seconds": "wall_seconds", "events": "events", "broker_calls": "model_calls",
                    "tokens": "tokens", "cost_usd": "cost_usd", "core_hours": "core_hours", "children": "children",
                    "review_rounds": "review_rounds", "input_bytes": "input_bytes", "input_files": "input_files",
                    "batch_cpu_hours": "batch_cpu_hours", "batch_jobs": "batch_jobs"}
STEP_LIMITS = ("attempts",)


class CompileError(ValueError):
    """The route spec cannot be compiled into a valid plan."""


def authority_budget(budget, *, step=None):
    """A step's ``budget`` in the authority's dimensions (``AUTHORITY_BUDGET``), summed per dimension.

    The step's own limits (``STEP_LIMITS``) stay out; any other dimension raises ``CompileError``.
    """
    mapped = {}
    for dimension, value in (budget or {}).items():
        if dimension in STEP_LIMITS:
            continue
        if dimension not in AUTHORITY_BUDGET:
            raise CompileError(f"step {step or '?'} declares budget dimension {dimension!r}, which no authority "
                               "budget names")
        if type(value) not in (int, float) or value != value or value < 0:
            raise CompileError(f"step {step or '?'} budget dimension {dimension!r} is not a nonnegative number")
        key = AUTHORITY_BUDGET[dimension]
        mapped[key] = mapped.get(key, 0) + value
    return mapped


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def plan_sha256(plan):
    return _digest({k: v for k, v in plan.items() if k != "sha256"})


# ---- parameters ---------------------------------------------------------------------------

def _extract(source, key, reading, contract, supplied):
    if source == "fact":
        return [deepcopy(f.get("value")) for f in reading.get("facts") or () if type(f) is dict and f.get("type") == key]
    if source == "constraint":
        return [deepcopy(c.get("value")) for c in reading.get("constraints") or ()
                if type(c) is dict and c.get("type") == key]
    if source == "contract":
        return deepcopy(contract.get(key)) if key else None
    if source == "reading":
        return deepcopy(reading.get(key)) if key else None
    if source == "deliverables":
        return [deepcopy(d) for d in reading.get("deliverables") or () if type(d) is dict]
    if source == "supplied":
        return [deepcopy(s) for s in supplied or () if type(s) is dict and (not key or s.get("kind") == key)]
    raise CompileError(f"unknown parameter source {source!r}")


def bind(spec, reading, contract, supplied=()):
    """``(parameters, open)``: values bound from the intake records, and unbound required ones."""
    params, missing = {}, []
    for row in spec.get("parameters") or ():
        source, _, key = row["from"].partition(":")
        value = _extract(source, key, reading, contract, supplied)
        if value in (None, "", [], {}):
            value = deepcopy(row.get("default"))
        if value in (None, "", [], {}) and row.get("required"):
            missing.append({"kind": "parameter", "id": f"parameter:{row['name']}", "name": row["name"],
                            "reason": f"the request does not state {row['name']} ({row['from']})"})
        params[row["name"]] = value
    return params, missing


# ---- templates ----------------------------------------------------------------------------

def _scalar_text(value):
    return value if type(value) is str else json.dumps(value, sort_keys=True)


def _substitute(value, names):
    if type(value) is str:
        def replace(match):
            name = match.group(1)
            if name in names and names[name] is not None and type(names[name]) not in (dict, list):
                return _scalar_text(names[name])
            return match.group(0)
        return PLACEHOLDER.sub(replace, value)
    if type(value) is list:
        return [_substitute(v, names) for v in value]
    if type(value) is dict:
        return {k: _substitute(v, names) for k, v in value.items()}
    return deepcopy(value)


def _unresolved(step):
    found = []
    for field in ("id", "operation", "role", "route"):
        if type(step.get(field)) is str and PLACEHOLDER.search(step[field]):
            found.append(field)
    for output in step.get("outputs") or ():
        if type(output) is dict and PLACEHOLDER.search(str(output.get("path"))):
            found.append("outputs")
    for item in step.get("inputs") or ():
        if type(item) is dict and PLACEHOLDER.search(str(item.get("artifact"))):
            found.append("inputs")
    return sorted(set(found))


def _item_key(item, index):
    """A step-id-safe key for a ``foreach`` item: its ``id``, its value, or its index."""
    if type(item) is dict and type(item.get("id")) in (str, int):
        key = str(item["id"])
    elif type(item) in (str, int):
        key = str(item)
    else:
        key = str(index)
    key = re.sub(r"[^A-Za-z0-9_-]", "-", key)[:48].strip("-")
    return key or str(index)


def expand(templates, params):
    """``(steps, expansions)``: templates expanded by ``foreach``; ``expansions`` maps a template id to its step ids.

    Each expanded step keeps the id of the template it came from (``template_id``, unless the template names its
    own), so a policy declared for the template binds every expansion."""
    steps, expansions = [], {}
    for template in templates:
        if type(template) is not dict or type(template.get("id")) is not str:
            raise CompileError("every step template has a string id")
        base = {**deepcopy(DEFAULT_STEP), **{k: deepcopy(v) for k, v in template.items() if k not in TEMPLATE_KEYS}}
        loop = template.get("foreach")
        if loop is None:
            steps.append(_substitute(base, params))
            expansions[template["id"]] = [steps[-1]["id"]]
            continue
        items = params.get(loop)
        if type(items) is not list:
            raise CompileError(f"step {template['id']} iterates over {loop!r}, which is not a bound list")
        ids = []
        for index, item in enumerate(items):
            key = _item_key(item, index)
            names = {**params, "item": key, "index": index}
            step = _substitute(base, names)
            step["id"] = f"{_substitute(template['id'], params)}.{key}"
            # A validator of an expanded producer reads that producer's own output,
            # never another coordinate's output with the same template path.
            checks = (step.get("parameters") or {}).get("check_inputs") or {}
            for fields in checks.values() if type(checks) is dict else ():
                if type(fields) is dict:
                    for ref in fields.values():
                        if type(ref) is dict and ref.get("source") == "output" and ref.get("step") == template['id']:
                            ref["step"] = step["id"]
            step.setdefault("template_id", _substitute(template["id"], params))
            step.setdefault("parameters", {})
            step["parameters"] = {**step["parameters"], "item": deepcopy(item), "index": index}
            steps.append(step)
            ids.append(step["id"])
        expansions[template["id"]] = ids
    return steps, expansions


def _rewire(steps, expansions):
    """Dependencies and inputs that name a template expand to every step of that template."""
    for step in steps:
        depends = []
        for parent in step.get("depends_on") or ():
            depends.extend(expansions.get(parent, [parent]))
        step["depends_on"] = list(dict.fromkeys(depends))
        inputs = []
        for item in step.get("inputs") or ():
            artifact = item.get("artifact", "") if type(item) is dict else ""
            source, sep, rest = artifact.partition(":")
            if sep and source in expansions and expansions[source] != [source]:
                inputs.extend({**deepcopy(item), "artifact": f"{child}:{rest}"} for child in expansions[source])
            else:
                inputs.append(deepcopy(item))
        step["inputs"] = inputs
    return steps


PREPARE_RUNGS = (None, "none", "dry")


def _prepare(step):
    return (step.get("parameters") or {}).get("phase") == "prepare"


def check_dag(steps):
    """Problems with step ids, dependencies, inputs, cycles and the prepare phase (empty when sound).

    A prepare step (``parameters.phase == "prepare"``) runs before CHECK-IN 1: its rung is none or
    dry and it depends only on prepare steps.
    """
    problems, ids = [], [s.get("id") for s in steps]
    if len(ids) != len(set(ids)):
        problems.append("step ids are not unique")
    known = {s["id"]: s for s in steps if type(s.get("id")) is str}
    for step in steps:
        if _prepare(step):
            if step.get("rung") not in PREPARE_RUNGS:
                problems.append(f"prepare step {step['id']} has rung {step.get('rung')}; before CHECK-IN 1 only "
                                "rungs none and dry run")
            for parent in step.get("depends_on") or ():
                if parent in known and not _prepare(known[parent]):
                    problems.append(f"prepare step {step['id']} depends on {parent}, which runs after CHECK-IN 1")
    for step in steps:
        for parent in step.get("depends_on") or ():
            if parent not in known:
                problems.append(f"step {step['id']} depends on unknown step {parent}")
            if parent == step["id"]:
                problems.append(f"step {step['id']} depends on itself")
        for item in step.get("inputs") or ():
            source, sep, rest = str(item.get("artifact")).partition(":")
            if sep and source in known:
                declared = {o.get("path") for o in known[source].get("outputs") or ()}
                if rest not in declared:
                    problems.append(f"step {step['id']} reads {rest} from {source}, which does not declare it")
                if source not in step.get("depends_on", ()):
                    problems.append(f"step {step['id']} reads from {source} without depending on it")
    state, order = {}, []

    def visit(node, trail):
        if state.get(node) == "done":
            return
        if state.get(node) == "open":
            problems.append("dependency cycle through " + " -> ".join([*trail, node]))
            return
        state[node] = "open"
        for parent in known[node].get("depends_on") or ():
            if parent in known:
                visit(parent, [*trail, node])
        state[node] = "done"
        order.append(node)
    for node in known:
        visit(node, [])
    return problems


# ---- deliverables and population equality --------------------------------------------------

def _matches(rule, deliverable):
    if rule.get("any"):
        return True
    artifact = (deliverable.get("artifact") or {}).get("kind") if type(deliverable.get("artifact")) is dict else None
    claim = deliverable.get("claim_kind")
    if "artifact" in rule and artifact not in rule["artifact"]:
        return False
    if "claim" in rule and claim not in rule["claim"]:
        return False
    return "artifact" in rule or "claim" in rule


def population_holes(expected, actual):
    """The obligation ledger's population equality (P02); the same set difference when it is absent."""
    from importlib import import_module
    try:
        ledger = import_module(__package__.rsplit(".", 1)[0] + ".ledger")
    except ModuleNotFoundError as exc:
        if exc.name != __package__.rsplit(".", 1)[0] + ".ledger":
            raise
        present = set(actual)
        return [item for item in expected if item not in present]
    return list(ledger.population_equality(list(expected), list(actual)))


def map_deliverables(spec, reading, steps, expansions):
    rows, by_id = [], {s["id"]: s for s in steps}
    for deliverable in reading.get("deliverables") or ():
        if type(deliverable) is not dict or type(deliverable.get("id")) is not str:
            continue
        artifact = (deliverable.get("artifact") or {}).get("kind") if type(deliverable.get("artifact")) is dict else None
        row = {"id": deliverable["id"], "status": "open", "step": None, "output": None,
               "reason": f"no step of route {spec['id']} produces this deliverable",
               "claim_kind": deliverable.get("claim_kind"), "artifact_kind": artifact}
        for rule in spec.get("deliverables") or ():
            if not _matches(rule["match"], deliverable):
                continue
            targets = expansions.get(rule["step"])
            if targets is None:
                raise CompileError(f"deliverable rule names unknown step {rule['step']}")
            if len(targets) != 1 or targets[0] != rule["step"]:
                raise CompileError(f"deliverable rule names the foreach step {rule['step']}; name the step that "
                                   "assembles its items")
            declared = {o["path"] for o in by_id[rule["step"]]["outputs"]}
            if rule["output"] not in declared:
                raise CompileError(f"deliverable rule names {rule['output']}, which step {rule['step']} does not declare")
            row.update(status="mapped", step=rule["step"], output=rule["output"], reason=None)
            by_id[rule["step"]].setdefault("deliverables", [])
            if deliverable["id"] not in by_id[rule["step"]]["deliverables"]:
                by_id[rule["step"]]["deliverables"].append(deliverable["id"])
            break
        rows.append(row)
    expected = [r["id"] for r in rows]
    holes = population_holes(expected, [r["id"] for r in rows if r["status"] == "mapped"])
    for row in rows:
        if row["id"] in holes and row["status"] == "mapped":
            row.update(status="open", reason="population equality keeps this deliverable open")
    return rows, holes


# ---- compile -------------------------------------------------------------------------------

def _policy_checkins(checkins, reading, contract, *, waypoints=None):
    """Preserve route seats and add applicable waypoint and final review roles."""
    checkins = deepcopy(checkins or [])
    if contract.get("agent_layer_epoch") != 2:
        return checkins
    from ...workflow import request_plan, review_points, spawn_rows
    from ..graph import CI2_SEATS, CI3_SEATS, canonical_role

    try:
        request = request_plan.draft(reading, contract)
    except ValueError:
        # No request plan can be drafted from this reading (the minimal intake layout): there are no policy facts to
        # seat a specialist from, so the route's own seats stand and nothing is credited in their place.
        return checkins
    facts = deepcopy(request)
    facts.update(agent_layer_epoch=2, delegated=review_points.delegated_contract(contract),
                 contract=contract, plan=request)
    points = [p for p in review_points.population(facts)
              if p["blocking"] and p["mode"] in review_points.CONTROLLER_SEAT_MODES]
    for name, defaults, gates in (("checkin1", (), ("approve_plan",)),
                                  ("checkin2", CI2_SEATS, ("checkin2_accept",)),
                                  ("checkin3", CI3_SEATS, review_points.CONTROLLER_FINAL_GATES)):
        selected = [p for p in points if (any(review_points._weighs(p, gate, {}) for gate in gates)
                    if name == "checkin3" else p["gate"] in gates)]
        if name == "checkin2" and not (waypoints is None or waypoints
                or any(row["id"] == name for row in checkins)):
            continue
        row = next((row for row in checkins if row["id"] == name), None)
        if row is None:
            if not selected and name != "checkin3":
                continue
            row = {"id": name, "sections": [], "seats": list(defaults)}
            position = next((i for i, old in enumerate(checkins) if old["id"] > name), len(checkins))
            checkins.insert(position, row)
        seats = row.setdefault("seats", [])
        present = {canonical_role(role) for role in seats}
        counts = {}
        for point in selected:
            for required in point["roles"]:
                role = canonical_role(required["role"])
                if role not in present:
                    seats.append(role)
                    present.add(role)
                counts[role] = max(counts.get(role, 1), required["count"])
        if selected:
            row["review_points"] = deepcopy(selected)
        counted = {role: count for role, count in counts.items() if count > 1}
        if counted:
            row["seat_counts"] = counted
    return checkins


def compile(route_spec: dict, reading: dict, contract: dict, *, supplied=(), revision=0, run_id=None,
            parameters=None) -> dict:
    """A ``plan.v1`` for ``route_spec`` over this reading; raises ``CompileError`` on a malformed spec.

    ``parameters`` (a route adapter's re-binding) are merged last: after the bound parameters and the
    adapter's ``parameters()``.
    """
    errors = selection.spec_errors(route_spec)
    if errors:
        raise CompileError(f"route spec {route_spec.get('id')!r} is invalid: " + "; ".join(errors[:5]))
    reading = reading if type(reading) is dict else {}
    contract = contract if type(contract) is dict else {}
    params, missing = bind(route_spec, reading, contract, supplied)
    module = selection.adapter_module(route_spec)
    if module is not None and hasattr(module, "parameters"):
        computed = module.parameters(route_spec, reading, contract, supplied)
        if type(computed) is not dict:
            raise CompileError(f"route {route_spec['id']} adapter parameters() must return an object")
        params.update(deepcopy(computed))
    if parameters is not None:
        if type(parameters) is not dict:
            raise CompileError("explicit compile parameters must be an object")
        params.update(deepcopy(parameters))
    missing = [m for m in missing if params.get(m["name"]) in (None, "", [], {})]
    steps, expansions = expand(route_spec["steps"], params)
    steps = _rewire(steps, expansions)
    from ..engagement.planning import prepare_outputs
    steps = prepare_outputs(steps)
    for step in steps:
        unresolved = _unresolved(step)
        if unresolved:
            raise CompileError(f"step {step.get('id')} keeps unresolved placeholders in {unresolved}")
        authority_budget(step.get("budget"), step=step.get("id"))
        problems = schema_errors(step, "step.v1")
        if problems:
            raise CompileError(f"step {step.get('id')} is not a valid step.v1: " + "; ".join(problems[:5]))
    from .validator_inputs import BindingError, compile_inputs
    try:
        compile_inputs(steps, contract)
    except BindingError as exc:
        raise CompileError(str(exc)) from None
    problems = check_dag(steps)
    if problems:
        raise CompileError("the step DAG is unsound: " + "; ".join(problems[:5]))
    deliverables, holes = map_deliverables(route_spec, reading, steps, expansions)
    open_obligations = list(missing) + [
        {"kind": "deliverable", "id": row["id"], "reason": row["reason"]} for row in deliverables
        if row["status"] == "open"]
    plan = {
        "schema_version": 1, "kind": "controller-plan", "revision": int(revision),
        "route": {"id": route_spec["id"], "version": route_spec["version"],
                  "spec_sha256": selection.spec_sha256(route_spec)},
        "parameters": params, "steps": steps, "deliverables": deliverables,
        "waypoints": [s["id"] for s in steps if s.get("waypoint")],
        "checkins": _policy_checkins(route_spec.get("checkins"), reading, contract,
                                     waypoints=[s["id"] for s in steps if s.get("waypoint")]),
        "obligations": deepcopy(route_spec.get("obligations") or []),
        "open_obligations": open_obligations,
        "instruction_sources": deepcopy(route_spec.get("instruction_sources") or []),
        "reading_sha256": _digest(reading) if reading else None,
        "contract_sha256": _digest(contract) if contract else None,
    }
    if run_id is not None:
        plan["run_id"] = run_id
    plan["sha256"] = plan_sha256(plan)
    problems = schema_errors(plan, "plan.v1")
    if problems:
        raise CompileError("the compiled plan is not a valid plan.v1: " + "; ".join(problems[:5]))
    return plan


def conformance_errors(plan, spec):
    """Problems of a plan that claims the route ``spec``: it keeps every route check-in (with its sections
    and seats), every stage the spec declares (a ``foreach`` stage's expansions follow its parameters) and
    every route obligation, and it was compiled from this spec. Re-binding may add, never remove."""
    problems = []
    route = plan.get("route") or {}
    if route.get("id") != spec.get("id"):
        problems.append(f"the plan names route {route.get('id')!r}, not {spec.get('id')!r}")
    if route.get("spec_sha256") not in (None, selection.spec_sha256(spec)):
        problems.append(f"the plan was compiled from another version of route {spec.get('id')}")
    have = {c.get("id"): c for c in plan.get("checkins") or () if type(c) is dict}
    for checkin in spec.get("checkins") or ():
        got = have.get(checkin["id"])
        if got is None:
            problems.append(f"route check-in {checkin['id']} is missing from the plan")
            continue
        for field in ("sections", "seats"):
            lost = sorted(set(checkin.get(field) or ()) - set(got.get(field) or ()))
            if lost:
                problems.append(f"route check-in {checkin['id']} lost its {field} {lost}")
    ids = {s.get("id") for s in plan.get("steps") or () if type(s) is dict}
    for template in spec.get("steps") or ():
        if template.get("foreach") or PLACEHOLDER.search(str(template.get("id"))):
            continue
        if template["id"] not in ids:
            problems.append(f"route stage {template['id']} is missing from the plan")
    lost = sorted(set(spec.get("obligations") or ()) - set(plan.get("obligations") or ()))
    if lost:
        problems.append(f"route obligations {lost} are missing from the plan")
    return problems


def plan_errors(plan, spec=None):
    """Problems with a plan from any planner (route compiler, route binding or judgment graph): schema,
    DAG, prepare phase and digest; with ``spec``, conformance to the fixed route it claims."""
    problems = schema_errors(plan, "plan.v1")
    if problems:
        return problems
    if spec is not None:
        problems = conformance_errors(plan, spec)
    problems = list(problems) + check_dag(plan["steps"])
    for step in plan["steps"]:
        try:
            authority_budget(step.get("budget"), step=step["id"])
        except CompileError as exc:
            problems.append(str(exc))
    if plan["sha256"] != plan_sha256(plan):
        problems.append("the plan's sha256 does not match its content")
    known = {s["id"] for s in plan["steps"]}
    for row in plan["deliverables"]:
        if row["status"] == "mapped" and row.get("step") not in known:
            problems.append(f"deliverable {row['id']} maps to unknown step {row.get('step')}")
    for waypoint in plan["waypoints"]:
        if waypoint not in known:
            problems.append(f"waypoint {waypoint} is not a plan step")
    return problems
