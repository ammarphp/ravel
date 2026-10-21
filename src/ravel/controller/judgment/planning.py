"""Frame and plan checks, call classification and the compiled plan of the judgment route.

``check_frame`` refuses a question frame that drops a reading deliverable, constraint,
boundary or critical ambiguity, or whose assumptions are not numbered (JR02, R10).
``check_plan`` refuses a decomposition outside the closed step vocabulary, with a cycle,
an unknown dependency or an output-less step, with an inline-execution field, or one that
drops a frame deliverable, a held scope or an unknown (JR03, ROUTE-unsupported).
``classify_steps`` computes the consequence class of every decide and effectful step from
the code tables; the planner's class only raises it (JR06, A05). ``compile_plan`` attaches
each step's class and requirement (record, report, RDJ review, authority) and returns the
plan that CHECK-IN 1 approves; ``controller_plan`` is its controller ``plan.v1``.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
from importlib.resources import files
import json
import math

from . import classes, protocols, schemas
from .records import digest

EFFECTFUL = ("acquire", "operate", "author", "derive", "compare", "synthesize", "subgraph", "route")
DEFAULT_ROLES = {"acquire": "generator", "operate": "generator", "author": "analysis-author",
                 "derive": "calculation", "compare": "discrepancy-attributor", "synthesize": "coordinator",
                 "decide": "coordinator", "review": "physics-critic"}
BOUNDARY_RESOLVERS = ("ask", "acquire")
INLINE_FIELDS = ("argv", "command", "cmd", "code", "script", "shell", "exec", "python", "run", "inline")
SCOPE_CONSTRAINTS = {"prescribed_statistic": "statistic", "source_restriction": "source_restriction",
                     "blinding": "blinding", "budget": "budget", "requested_stage": "stage",
                     "negated_stage": "stage", "requested_tool": "tool", "tool_allowlist": "tool",
                     "template": "template", "keep_fixed": "fixed"}


@lru_cache(maxsize=1)
def _executor_tables() -> tuple:
    from ravel.workflow import production_executor
    signatures = json.loads(files("ravel").joinpath("data", "operation_signatures.json").read_text(encoding="utf-8"))
    return production_executor.executors(), signatures["operations"]


def executor_for(operation: str) -> tuple[str | None, bool]:
    """The operation's registered production executor (or None) and whether it is compute.

    An operation without a signature counts as compute, as the approve_plan role check does.
    """
    from ravel.workflow import production_executor
    table, signatures = _executor_tables()
    signature = signatures.get(operation)
    compute = signature is None or production_executor.requires_production(signature, table)
    return table["operations"].get(operation), compute


@lru_cache(maxsize=1)
def policy() -> dict:
    document = json.loads(files("ravel").joinpath("data", "judgment", "policy.json").read_text(encoding="utf-8"))
    if document.get("schema_version") != 1 or document.get("kind") != "judgment-policy":
        raise ValueError("judgment policy has an unexpected schema")
    return document


# ---- the frame (JR02, R10) -------------------------------------------------------------------

def check_frame(frame, reading: dict, request_sha256: str) -> list[str]:
    """Every reason ``frame`` cannot be the run's question frame."""
    problems = schemas.errors("question-frame.v1", frame)
    if problems:
        return problems
    if frame["request_sha256"] != request_sha256:
        problems.append("the frame is not of the pinned request")
    ids = [d["id"] for d in frame["deliverables"]]
    if len(set(ids)) != len(ids):
        problems.append("frame deliverable ids must be unique")
    reading_deliverables = [d["id"] for d in reading.get("deliverables") or []]
    referenced = {d["reading_ref"] for d in frame["deliverables"] if d["reading_ref"] is not None}
    for missing in sorted(set(reading_deliverables) - referenced):
        problems.append(f"reading deliverable {missing} is missing from the frame")
    for unknown in sorted(referenced - set(reading_deliverables)):
        problems.append(f"frame deliverable names reading deliverable {unknown}, which the reading does not have")
    refs = [d["reading_ref"] for d in frame["deliverables"] if d["reading_ref"] is not None]
    for twice in sorted({r for r in refs if refs.count(r) > 1}):
        problems.append(f"reading deliverable {twice} is framed more than once; one frame deliverable carries each")
    for d in frame["deliverables"]:
        if d["reading_ref"] is None and "scope_change" not in d:
            problems.append(f"frame deliverable {d['id']} traces to no reading deliverable and declares no scope change")
    constraints = {c["reading_ref"]: c for c in frame["constraints"] if c["reading_ref"] is not None}
    for row in reading.get("constraints") or []:
        if row.get("type") not in SCOPE_CONSTRAINTS:
            continue
        found = constraints.get(row.get("id"))
        if found is None:
            problems.append(f"reading constraint {row.get('id')} ({row.get('type')}) is missing from the frame")
            continue
        if row.get("type") == "prescribed_statistic":
            expected = (row.get("value") or {}).get("statistic")
            if found.get("value") != expected:
                problems.append(f"frame constraint {row.get('id')} must carry the prescribed statistic verbatim")
    boundaries = {b["reading_ref"] for b in frame["boundaries"] if b["reading_ref"] is not None}
    for index, row in enumerate(reading.get("boundaries") or []):
        name = row.get("id") or f"boundary-{index + 1}"
        if name not in boundaries:
            problems.append(f"reading boundary {name} ({row.get('class')}) is not held in the frame")
    unknowns = {u["reading_ref"] for u in frame["unknowns"] if u["reading_ref"] is not None}
    for row in reading.get("ambiguities") or []:
        if row.get("critical") and row.get("status", "open") == "open" and row.get("id") not in unknowns:
            problems.append(f"critical reading ambiguity {row.get('id')} is not listed as an unknown")
    numbers = [a["number"] for a in frame["assumptions"]]
    if numbers != list(range(1, len(numbers) + 1)):
        problems.append("assumptions must be numbered 1..n in order")
    for name, rows in (("unknown", frame["unknowns"]), ("boundary", frame["boundaries"])):
        keys = [r["id"] for r in rows]
        if len(set(keys)) != len(keys):
            problems.append(f"{name} ids must be unique")
    return problems


def frame_must_check(frame: dict, reading: dict) -> list[dict]:
    """must_check items for the frame reviewer; the mechanical results are attached by the caller."""
    deliverables = ", ".join(d["id"] for d in reading.get("deliverables") or []) or "none"
    return [{"id": "JR02:deliverables", "row": "JR02",
             "text": f"Every reading deliverable ({deliverables}) is in the frame with an acceptance criterion, "
                     "the requested statistic and units."},
            {"id": "JR02:assumptions", "row": "JR02", "text": "Assumptions are numbered and each states its basis."},
            {"id": "JR02:unknowns", "row": "JR02",
             "text": "Unknowns are listed, including every critical ambiguity of the reading."},
            {"id": "R10:held-scope", "row": "R10",
             "text": "Every boundary of the reading is held in the frame with what would make it possible; no held "
                     "scope is substituted."}]


# ---- the plan (JR03, ROUTE-unsupported) ------------------------------------------------------

def _closure(steps):
    by_id = {s["id"]: s for s in steps}
    ancestors = {}

    def visit(name, trail=()):
        if name in ancestors:
            return ancestors[name]
        if name in trail:
            raise ValueError(f"dependency cycle through {name}")
        found = set()
        for parent in by_id[name]["depends_on"]:
            if parent in by_id:
                found |= {parent} | visit(parent, trail + (name,))
        ancestors[name] = found
        return found
    for name in by_id:
        visit(name)
    return ancestors


def check_plan(plan, frame: dict, *, operations=None, routes=None, roles=None, failures=(), tools=None) -> list[str]:
    """Every reason ``plan`` cannot be adopted for ``frame``.

    ``operations`` and ``routes`` are the admitted operation and route-spec ids (None
    refuses every operate or route step: nothing is admitted without its contract);
    ``roles`` the registered card ids (None skips that check); ``failures`` the failed
    step ids a recovery plan must cover with a stage-recovery decision; ``tools`` the run's capability-need
    inputs (``tool_selection.check`` keywords: profile, supplied, derived label, reading, request text), under
    which every need that arises is served by its best available tool or a typed reason (None skips it).
    """
    if type(plan) is dict:
        for step in plan.get("steps") or []:
            if type(step) is dict:
                inline = sorted(set(step) & set(INLINE_FIELDS))
                if inline:
                    return [f"step {step.get('id')} carries inline execution fields {inline}; every step runs only "
                            "through the governed step graph"]
    problems = schemas.errors("judgment-plan.v1", plan)
    if problems:
        return problems
    if plan["frame_sha256"] != digest(frame):
        problems.append("the plan is not of the adopted frame")
    steps = plan["steps"]
    ids = [s["id"] for s in steps]
    if len(set(ids)) != len(ids):
        problems.append("step ids must be unique")
    known = set(ids)
    for step in steps:
        for parent in step["depends_on"]:
            if parent not in known:
                problems.append(f"step {step['id']} depends on unknown step {parent}")
            if parent == step["id"]:
                problems.append(f"step {step['id']} depends on itself")
    if problems:
        return problems
    try:
        ancestors = _closure(steps)
    except ValueError as exc:
        return [str(exc)]
    outputs = {(s["id"], o["path"]) for s in steps for o in s["outputs"]}
    for step in steps:
        problems.extend(_step_problems(step, ancestors[step["id"]], outputs, operations, routes, roles))
    fraction = sum(s["budget_share"]["fraction"] for s in steps)
    if fraction > 1.0 + 1e-9:
        problems.append(f"budget shares sum to {fraction:.3f}, above the envelope")
    problems.extend(_deliverable_problems(plan, frame, outputs))
    resolved = {name for s in steps for name in s.get("resolves") or []}
    by_resolver = {}
    for s in steps:
        for name in s.get("resolves") or []:
            by_resolver.setdefault(name, []).append(s)
    for unknown in frame["unknowns"]:
        if unknown["id"] not in resolved:
            problems.append(f"frame unknown {unknown['id']} is resolved by no step")
        elif unknown["physics_critical"] and not any(s["kind"] in ("ask", "decide") for s in by_resolver[unknown["id"]]):
            problems.append(f"physics-critical unknown {unknown['id']} must be resolved by an ask or a decide step")
    held = {d["id"] for d in plan["deliverables"] if d["status"] == "held"}
    for boundary in frame["boundaries"]:
        affected = set(boundary["holds"])
        if affected <= held:
            continue
        resolvers = by_resolver.get(boundary["id"], [])
        if not any(s["kind"] in BOUNDARY_RESOLVERS for s in resolvers):
            problems.append(f"boundary {boundary['id']} plans {sorted(affected - held)} without holding them or "
                            "asking for, or acquiring, what would make them possible; held scope is never substituted")
    for failed in failures:
        if failed not in known:
            continue  # the replan drops the failed step; its deliverables are held or served otherwise
        covering = by_resolver.get("failure:" + failed, [])
        recovery = [s for s in covering if s["kind"] == "decide" and "stage_recovery" in s.get("triggers", [])]
        if not recovery:
            problems.append(f"failed step {failed} needs a stage-recovery decision before any retry")
        elif not any(r["id"] in ancestors[failed] for r in recovery):
            problems.append(f"the retry of failed step {failed} must depend on its stage-recovery decision")
    if tools is not None:
        from ravel.workflow import tool_selection
        problems.extend(tool_selection.check(plan, **tools)[1])
    return problems


def _step_problems(step, ancestors, outputs, operations, routes, roles):
    problems = []
    name, kind = step["id"], step["kind"]
    if kind == "operate":
        if "operation" not in step:
            problems.append(f"operate step {name} names no operation")
        elif operations is None or step["operation"] not in operations:
            problems.append(f"operate step {name} names operation {step['operation']!r}, which is not admitted")
        else:
            executor, compute = executor_for(step["operation"])
            if executor is None and compute:
                problems.append(f"operate step {name}: compute operation {step['operation']!r} has no registered "
                                "production executor (executor_role_missing)")
            elif executor is not None and "role" in step and step["role"] != executor:
                problems.append(f"operate step {name} names role {step['role']!r}, not the registered production "
                                f"executor {executor!r} of {step['operation']!r} (executor_role_mismatch)")
    elif "operation" in step:
        problems.append(f"step {name} of kind {kind} cannot name an operation")
    if 'operation_task' in step:
        from ravel.controller.operation_tasks import declaration
        try:
            declaration({'kind': kind, 'operation': step.get('operation'),
                         'role': step.get('role') or executor_for(step.get('operation'))[0],
                         'inputs': step['inputs'], 'outputs': step['outputs'],
                         'parameters': {'operation_task': step['operation_task']}})
        except (ValueError, TypeError, KeyError) as exc:
            problems.append(f'step {name}: {exc}')
    if kind == "subgraph" and "graph" not in step:
        problems.append(f"subgraph step {name} names no registered graph")
    if kind != "subgraph" and "graph" in step:
        problems.append(f"step {name} of kind {kind} cannot name a graph")
    if kind == "route":
        if "route" not in step:
            problems.append(f"route step {name} names no route spec")
        elif routes is None or step["route"] not in routes:
            problems.append(f"route step {name} names route {step['route']!r}, which has no installed route spec")
    elif "route" in step:
        problems.append(f"step {name} of kind {kind} cannot name a route")
    if kind in ("ask", "decide") and "question" not in step:
        problems.append(f"{kind} step {name} states no question")
    if kind == "ask" and not step.get("options"):
        problems.append(f"ask step {name} offers no options")
    if step.get("default_option") is not None:
        if kind != "ask" or step["default_option"] not in {o["id"] for o in step.get("options") or []}:
            problems.append(f"step {name} names a default option that is not one of its offered options")
        elif not step.get("default"):
            problems.append(f"step {name} names a default option without its P7 conservative-default record")
        else:
            problems.extend(f"step {name} default: {p}" for p in protocols.check("P7", step["default"]))
    if kind == "decide" and "action" not in step:
        problems.append(f"decide step {name} states no action to classify")
    if kind not in ("ask", "decide") and ("question" in step or "options" in step):
        problems.append(f"step {name} of kind {kind} cannot carry a question")
    for item in step["inputs"]:
        artifact = item["artifact"]
        if ":outputs/" in artifact and not artifact.startswith("supplied:"):
            parent, path = artifact.split(":", 1)
            if parent not in ancestors:
                problems.append(f"step {name} reads {artifact} from a step it does not depend on")
            elif (parent, path) not in outputs:
                problems.append(f"step {name} reads {artifact}, which step {parent} does not declare")
    try:
        triggered = sorted(set(step.get("triggers") or []) | set(protocols.implied_triggers(kind, step.get("action"))))
        missing = sorted(set(protocols.protocol_ids_for(triggered)) - set(step["protocols"]))
    except ValueError as exc:
        return problems + [f"step {name}: {exc}"]
    if missing:
        problems.append(f"step {name} must name protocols {missing} that its triggers require")
    kinds = {o["kind"] for o in step["outputs"]}
    if kind == "compare" and "comparison" not in kinds:
        problems.append(f"compare step {name} must declare a comparison output carrying its P2 evidence")
    elif kind not in ("compare", "decide", "ask") and triggered and "protocol-evidence" not in kinds:
        problems.append(f"step {name} must declare a protocol-evidence output for its triggers {triggered}")
    if kind == "decide" and "judgment-record" not in kinds:
        problems.append(f"decide step {name} must declare its judgment-record output")
    if roles is not None:
        for role in step["review"] + ([step["role"]] if "role" in step else []):
            if role not in roles:
                problems.append(f"step {name} names unregistered role {role!r}")
    return problems + _verification_problems(step)


def _verification_problems(step):
    """A step a blind reviewer verifies (its card reviews blind, forbids producer headlines, and the step's result is
    one) needs the comparison its approval covers: ``verification`` with its output, pointer, unit and tolerance. The
    controller never assumes a default tolerance, so a step without one is refused here."""
    from ravel.workflow import review_projection, role_registry
    name, paths = step["id"], [o["path"] for o in step["outputs"]]
    declared = step.get("verification")
    if declared and declared.get("output") not in paths:
        return [f"step {name} declares a verification of {declared.get('output')!r}, which is not one of its outputs"]
    executor = executor_for(step["operation"])[0] if step["kind"] == "operate" and "operation" in step else None
    role = step.get("role") or executor or DEFAULT_ROLES.get(step["kind"], "coordinator")
    try:
        card = role_registry.load(role)
        reviewers = [role_registry.load(r) for r in dict.fromkeys([*(card.get("reviewed_by") or ()), *step["review"]])]
    except ValueError:
        return []  # an unregistered role is refused by its own check
    blind = [r["id"] for r in reviewers if review_projection.blind_card(r)
             and "producer_headline" in (r["sees"].get("forbidden_inputs") or ())]
    if blind and not declared and any(review_projection.headline(path) for path in paths):
        return [f"step {name} is verified blind by {', '.join(blind)} (its result is a producer headline the "
                "reviewer may not see): declare its verification (output, pointer, unit and tolerance); no default "
                "tolerance is assumed"]
    return []


def _deliverable_problems(plan, frame, outputs):
    problems = []
    planned = [d["id"] for d in plan["deliverables"]]
    expected = [d["id"] for d in frame["deliverables"]]
    if len(set(planned)) != len(planned):
        problems.append("plan deliverable ids must be unique")
    for missing in sorted(set(expected) - set(planned)):
        problems.append(f"frame deliverable {missing} is dropped by the plan; it stays an open obligation")
    for extra in sorted(set(planned) - set(expected)):
        problems.append(f"plan deliverable {extra} is not in the frame")
    for row in plan["deliverables"]:
        if row["status"] == "planned":
            if not row["outputs"]:
                problems.append(f"planned deliverable {row['id']} maps to no step output")
            for out in row["outputs"]:
                if (out["step"], out["path"]) not in outputs:
                    problems.append(f"deliverable {row['id']} maps to {out['step']}:{out['path']}, which is not declared")
        elif not row.get("held_reason"):
            problems.append(f"held deliverable {row['id']} states no held reason")
    return problems


def plan_must_check(plan: dict, frame: dict) -> list[dict]:
    items = [{"id": "JR03:dag", "row": "JR03",
              "text": "The decomposition is a DAG of typed steps that serves every frame deliverable or holds it with "
                      "a stated reason."},
             {"id": "C01:ladder", "row": "C01",
              "text": "Before any method escalation, every cheaper rung is accounted for or the request demands the "
                      "selected method."},
             {"id": "E03:ladder", "row": "E03",
              "text": "No resource is declared unavailable without the source ladder's rungs 1 to 5."},
             {"id": "R10:held-scope", "row": "R10",
              "text": "Held scope stays held or is asked about; nothing is silently substituted."}]
    triggered = sorted({t for s in plan["steps"] for t in s.get("triggers") or []})
    return items + protocols.must_check(triggered)


# ---- classification and compilation (JR06, A05) ----------------------------------------------

def step_action(step: dict, frame: dict) -> dict:
    """The classification inputs of a step: its declared action plus step kind, rung and resolved scope."""
    action = deepcopy(step.get("action") or {"summary": step["purpose"]})
    action.setdefault("step_kind", step["kind"])
    if step.get("rung") and step["kind"] != "decide":
        action.setdefault("rung", step["rung"])
    effects = list(action.get("effects") or [])
    critical = {u["id"] for u in frame["unknowns"] if u["physics_critical"]}
    if critical & set(step.get("resolves") or []) and "physics_critical" not in effects:
        effects.append("physics_critical")
    if any(name.startswith("B") for name in step.get("resolves") or []) and "boundary_change" not in effects \
            and step["kind"] not in BOUNDARY_RESOLVERS:
        effects.append("boundary_change")
    if effects:
        action["effects"] = effects
    if step.get("declared_class") and not action.get("declared_class"):
        action["declared_class"] = step["declared_class"]
    return action


def classify_steps(plan: dict, frame: dict) -> dict:
    """``{step id: explanation}`` for every decide and effectful step, computed by code."""
    result = {}
    for step in plan["steps"]:
        if step["kind"] in EFFECTFUL or step["kind"] in ("decide", "ask"):
            found = classes.explain(step_action(step, frame))
            result[step["id"]] = found
    for row in frame["deliverables"]:
        if "scope_change" in row:
            result["frame:" + row["id"]] = classes.explain({"summary": row["scope_change"]["reason"],
                                                            "effects": ["deliverable_added"]})
    return result


def requirement(step: dict) -> str:
    """What must hold before a step's effect (effectful) or before it closes (decide)."""
    return classes.requirement(step.get("class", "R3"))


def compile_plan(plan: dict, frame: dict, calls: dict, *, revision: int, parent_sha256=None) -> dict:
    """The controller plan that CHECK-IN 1 approves: the planner's steps with computed classes.

    Requirements are gates on the steps, not extra steps: an effectful step of class R2
    or R3 runs only after an RDJ case credited on its exact spec, and one of class R3
    only after an authority answer as well; a decide step closes only after the same
    requirements are met on its record. The controller schedules those reviews and asks.
    """
    steps = []
    for step in plan["steps"]:
        row = deepcopy(step)
        found = calls.get(step["id"])
        row["class"] = found["class"] if found else "R0"
        executor = executor_for(step["operation"])[0] if step["kind"] == "operate" and "operation" in step else None
        row.setdefault("role", executor or DEFAULT_ROLES.get(step["kind"], "coordinator"))
        row.setdefault("waypoint", False)
        row.setdefault("rung", None)
        row.setdefault("instruction_sources", list(policy()["instruction_sources"].get(
            "decide" if step["kind"] == "decide" else "review", [])))
        row["triggers"] = sorted(set(row.get("triggers") or []) | set(protocols.implied_triggers(
            step["kind"], step.get("action"))))
        row["requirement"] = classes.requirement(row["class"])
        steps.append(row)
    for row in steps:
        row["spec_sha256"] = digest({k: v for k, v in row.items() if k != "spec_sha256"})
    compiled = {"schema_version": 1, "kind": "judgment-compiled-plan", "revision": revision,
                "parent_plan_sha256": parent_sha256, "frame_sha256": plan["frame_sha256"],
                "planner_plan_sha256": digest(plan), "steps": steps,
                "deliverables": deepcopy(plan["deliverables"]),
                **({"tool_reasons": deepcopy(plan["tool_reasons"])} if plan.get("tool_reasons") else {}),
                "calls": {k: {"class": v["class"], "computed": v["computed"], "declared": v["declared"],
                              "declared_lower": v["declared_lower"], "unknown": v["unknown"]}
                          for k, v in sorted(calls.items())}}
    compiled["sha256"] = digest({k: v for k, v in compiled.items() if k != "sha256"})
    return compiled


BUDGET_DIMENSIONS = ("wall_seconds", "events", "broker_calls", "tokens", "cost_usd", "core_hours", "children",
                     "review_rounds", "attempts")
ROUTE_ROWS = ("JR01", "JR02", "JR03", "JR04", "JR05", "JR06", "JR07", "JR08", "JR09", "R10", "ROUTE-unsupported",
              "A05")
TRIGGER_ROWS = {"method_escalation": "C01", "adopt_default": "C08", "resource_unavailable": "E03",
                "stage_recovery": "E12"}


def plan_sha256(plan: dict) -> str:
    """The controller plan digest: canonical JSON of every field but ``sha256`` (UTF-8, no escapes)."""
    body = {k: v for k, v in plan.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


# Resource dimensions a step's share of the envelope is cut from; the authority counts every one but cost and
# core-hours in whole units, so a share is floored (a share never exceeds its fraction of the envelope).
SHARED_DIMENSIONS = ("wall_seconds", "events", "broker_calls", "tokens", "cost_usd", "core_hours", "children")
FRACTIONAL_DIMENSIONS = ("cost_usd", "core_hours")


def _budget(row, envelope):
    share = row.get("budget_share") or {"fraction": 0.0}
    budget = {k: v for k, v in share.items() if k in BUDGET_DIMENSIONS}
    for key, value in (envelope or {}).items():
        if key in SHARED_DIMENSIONS and key not in budget and type(value) in (int, float) and value >= 0:
            amount = value * share.get("fraction", 0.0)
            budget[key] = amount if key in FRACTIONAL_DIMENSIONS else int(math.floor(amount))
    return budget


def controller_step(row: dict, *, inputs: dict, deliverables: list, envelope=None) -> dict:
    """One compiled step as a controller ``step.v1``; judgment fields travel under ``parameters``."""
    step = {"id": row["id"], "kind": row["kind"], "description": row["purpose"], "role": row.get("role"),
            "inputs": [{"artifact": inputs.get(i["artifact"], {}).get("artifact", i["artifact"]),
                        "sha256": inputs.get(i["artifact"], {}).get("sha256", i.get("sha256"))}
                       for i in row["inputs"]],
            "outputs": deepcopy(row["outputs"]), "depends_on": list(row["depends_on"]),
            "waypoint": bool(row.get("waypoint")), "rung": row.get("rung"), "budget": _budget(row, envelope),
            "protocols": list(row["protocols"]), "review": list(row["review"]),
            "instruction_sources": list(row.get("instruction_sources") or []), "obligations": list(row["obligations"]),
            "consequence_class": row["class"], "deliverables": list(deliverables),
            "attempt_limit": policy()["bounds"]["step_attempts"],
            "parameters": {"judgment": {k: deepcopy(row[k]) for k in (
                "purpose", "requirement", "triggers", "resolves", "action", "declared_class", "options", "default",
                "default_option", "spec_sha256") if k in row}}}
    step["parameters"]["judgment"]["budget_fraction"] = (row.get("budget_share") or {}).get("fraction", 0.0)
    if row.get("check_inputs"):
        # The validator parameters CHECK-IN 1 approves with the step (the governed step's checks read them here).
        step["parameters"]["check_inputs"] = deepcopy(row["check_inputs"])
    if row.get("verification"):
        # How the controller compares a blind verifier's independent value with the step's result (approved here).
        step["parameters"]["verification"] = deepcopy(row["verification"])
    if row.get('operation_task'):
        step['parameters']['operation_task'] = deepcopy(row['operation_task'])
        # Request/reading aliases become their exact retained input artifact names.
        source = step['parameters']['operation_task']['task_input']
        step['parameters']['operation_task']['task_input'] = inputs.get(source, {}).get('artifact', source)
    for key in ("needs", "tool_reasons"):
        if row.get(key):
            # The capability needs the step declares and its typed reasons (CHECK-IN 1 approves them with the step).
            step["parameters"][key] = deepcopy(row[key])
    if "operation" in row:
        step["operation"] = row["operation"]
    if row["kind"] == "subgraph":
        step["graph"] = {"id": row["graph"]}
    if row["kind"] == "route":
        step["route"] = row["route"]
    if row.get("question"):
        step["question"] = row["question"]
    return step


def controller_plan(compiled: dict, *, frame: dict, reading: dict, run_id: str, revision: int, inputs: dict,
                    request: dict, envelope=None, rdj=None, frame_findings=None, final_seats=()) -> dict:
    """The controller ``plan.v1`` (``kind: controller-plan``) of a compiled judgment plan.

    Deliverables are keyed by the reading's deliverable ids, ``mapped`` to the step output
    that carries them or ``open`` with the held reason; held scope is listed again under
    ``open_obligations``. ``inputs`` maps the plan's request, reading and contract names to
    the run inputs the controller wrote. ``frame_findings`` are the frame critic's findings
    that a frame carried past its last revision round; CHECK-IN 1 shows them as risks. ``final_seats`` are the roles the
    run's review policy owes the final task or delivery besides the CHECK-IN 3 triad (the normalization auditor of a
    prediction claim): CHECK-IN 3 seats them, so the plan review, CHECK-IN 1 and the engagement view name them.
    """
    framed = {d["id"]: d for d in frame["deliverables"]}
    read = {d["id"]: d for d in reading.get("deliverables") or [] if type(d) is dict and "id" in d}
    served, rows, held = {}, [], []
    for row in compiled["deliverables"]:
        framing = framed[row["id"]]
        name = framing["reading_ref"] or row["id"]
        source = read.get(name, {})
        artifact = source.get("artifact") if type(source.get("artifact")) is dict else {}
        base = {"id": name, "claim_kind": source.get("claim_kind", framing.get("claim_kind")),
                "artifact_kind": artifact.get("kind")}
        if row["status"] == "planned":
            target = row["outputs"][0]
            rows.append({**base, "status": "mapped", "step": target["step"], "output": target["path"], "reason": None})
            served.setdefault(target["step"], []).append(name)
        else:
            rows.append({**base, "status": "open", "step": None, "output": None, "reason": row.get("held_reason")})
            held.append({"id": name, "kind": "deliverable", "reason": row.get("held_reason"), "source": "judgment"})
    triggered = {t for s in compiled["steps"] for t in s.get("triggers") or []}
    rows_named = set(ROUTE_ROWS) | {row for trigger, row in TRIGGER_ROWS.items() if trigger in triggered}
    if triggered:
        rows_named.add("E28")
    steps = [controller_step(row, inputs=inputs, deliverables=served.get(row["id"], []), envelope=envelope)
             for row in compiled["steps"]]
    from .steps import final_review_roles
    plan = {"schema_version": 1, "kind": "controller-plan", "run_id": run_id, "revision": revision,
            "route": {"id": "judgment", "version": 1, "spec_sha256": None},
            "parameters": {"judgment": {"frame_sha256": compiled["frame_sha256"],
                                        "compiled_sha256": compiled["sha256"],
                                        "planner_plan_sha256": compiled["planner_plan_sha256"],
                                        "calls": deepcopy(compiled["calls"]),
                                        "scope_changes": deepcopy(compiled.get("scope_changes") or []),
                                        "frame_findings": deepcopy(list(frame_findings or [])),
                                        "rdj": deepcopy(rdj or {})},
                           **({"tool_reasons": deepcopy(compiled["tool_reasons"])}
                              if compiled.get("tool_reasons") else {})},
            "steps": steps, "deliverables": rows, "waypoints": [s["id"] for s in steps if s["waypoint"]],
            "checkins": [{"id": "checkin1", "seats": [policy()["roles"]["critic"]]},
                         {"id": "checkin3", "seats": list(dict.fromkeys([*final_review_roles(), *final_seats]))}],
            "obligations": sorted(rows_named), "open_obligations": held,
            "instruction_sources": list(policy()["instruction_sources"]["decompose"]),
            "reading_sha256": request.get("reading_sha256"), "contract_sha256": request.get("contract_sha256")}
    plan["sha256"] = plan_sha256(plan)
    return plan


def controller_plan_problems(plan: dict) -> list[str]:
    """The controller's own plan check when the controller core is installed; empty otherwise."""
    try:
        from ravel.controller.routes import plan_errors
    except ImportError:
        return []
    return list(plan_errors(plan))


def scope_delta(old_plan: dict | None, new_plan: dict, frame: dict) -> list[dict]:
    """Scope changes a replan makes: deliverables dropped, newly held or added.

    A held deliverable that a replan plans again is not listed: ``check_plan`` admits that only
    when an ask or acquire step resolves the boundary that held it.
    """
    changes = []
    old = {d["id"]: d for d in (old_plan or {}).get("deliverables") or []}
    new = {d["id"]: d for d in new_plan["deliverables"]}
    for name in sorted(set(old) - set(new)):
        changes.append({"kind": "deliverable_dropped", "deliverable": name})
    for name in sorted(set(new) - set(old)):
        if old_plan is not None:
            changes.append({"kind": "deliverable_added", "deliverable": name})
    for name in sorted(set(old) & set(new)):
        if old[name]["status"] == "planned" and new[name]["status"] == "held":
            changes.append({"kind": "deliverable_dropped", "deliverable": name, "detail": "newly held"})
    return changes
