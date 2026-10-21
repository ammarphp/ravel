"""``judgment.plan``: a question with no fixed path, driven end to end.

The graph's input view is the controller graph's: ``{"request": <run-state request pins>,
"plan": <controller plan or None>, "context": {run_id, run_dir, store_root, mode, purpose,
revision, ...}}``. ``context.purpose`` selects what it does:

- ``plan`` (the default) and ``replan``: frame, frame review, decompose (or replan), classify
  every call by code, RDJ cases for every R2 or R3 effectful call, then return the plan as a
  controller ``plan.v1`` in ``results["plan"]``; ``controller.run`` runs CHECK-IN 1, the waves,
  the final review and delivery. A bound ends in a typed planning hold, which the controller
  turns into a qualified ending.
- ``route``: the whole judgment route of CONTROLLER-SPEC 6.2 in this graph, for a controller
  that delegates it:

```
START → start → guard → advance ─┬─ frame / frame_review / decompose / classify_calls / plan_review
                                 ├─ checkin1 ──► approve_plan_gate ─┐
                                 ├─ execute (one wave through controller.step) → wave_review
                                 ├─ ask (questions and R3 calls: answer, default or held branch)
                                 ├─ replan / deviation ──► deviation_gate / adopt
                                 ├─ recovery_gate (failed_stage_feedback) ───┤
                                 ├─ kill_the_result (three attacks, P8) → final_review (fresh triad)
                                 ├─ checkin3 ──► final_task_gate ──► delivery_gate ─► gate_passed | gate_refused
                                 ├─ deliver (sole sink) → END
                                 ├─ return_plan → END            (purpose plan or replan)
                                 ├─ planning_held → END          (purpose plan or replan)
                                 └─ bounded_end (qualified delivery) → END     (reachable from every node)
every phase node → guard → advance
```

The hub ``advance`` derives the next phase from the run store (``control``); a crash, a
resumed run or a new invocation continues from the stored events. Every typed step runs
through ``step.run``, the governed step graph's entry; the planner never runs anything. Gates
call the decision gate on the run directory and the obligation ledger. There is no refusal of
the request: the outcomes are a plan, a delivery, a qualified delivery or a typed hold.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from ravel.workflow import graph_nodes as nodes
from ravel.workflow.state_io import atomic_json

from . import control, planning, protocols, records, recovery, services, steps, waves
from .records import digest

GRAPH_ID = "judgment.plan"
MAX_PASSES = 240
GATES = {"approve_plan": "approve_plan_gate", "deviation": "deviation_gate",
         "failed_stage_feedback": "recovery_gate", "final_task": "final_task_gate", "delivery": "delivery_gate"}
# Ledger transitions the gates check (the obligation ledger's transition table).
TRANSITIONS = {"approve_plan": "checkin1→execute", "deviation": "deviation→execute",
               "failed_stage_feedback": "checkin1→execute", "final_task": "checkin3→deliver",
               "delivery": "deliver[accepted]"}
PHASE_NODES = ("frame", "frame_review", "decompose", "classify_calls", "plan_review", "checkin1", "adopt", "execute",
               "wave_review", "ask", "replan", "deviation", "kill_the_result", "final_review", "checkin3")
CONTEXT_DIR = "inputs/judgment"
STOPPING = ("stop_requested", "draining", "stopped")
R_ROWS = ("C01", "E03", "E12", "E28", "JR02", "JR09")
CONTROLLER_PLAN_KIND = "plan"
PLANNING_SOURCE = "judgment-planning"  # plans bound only to run the route's own planning seats


class State(nodes.BaseState, total=False):
    request: dict
    plan: dict
    context: dict
    decision: dict
    passes: int


# ---- shared helpers -----------------------------------------------------------------------------

def _run(state) -> dict:
    context = state.get("context") or {}
    return {"run_id": context.get("run_id"), "store_root": context.get("store_root"),
            "run_dir": context.get("run_dir")}


def _store(state):
    run = _run(state)
    if not run["run_id"]:
        raise nodes.RecoveryHold("run_identity_missing", "the controller passes the run id in the context")
    return services.call("open_store", run)


def purpose(state) -> str:
    value = (state.get("context") or {}).get("purpose") or "plan"
    return value if value in control.PURPOSES else "plan"


def _revision(state) -> int:
    value = (state.get("context") or {}).get("revision", 0)
    return value if type(value) is int and value >= 0 else 0


def _envelope(state) -> dict:
    """The budget envelope a judgment plan's step shares are cut from: the operator's frozen budgets, narrowed by
    the approval's own budget bounds where they set a dimension (a subgraph or launch step reserves from these;
    an unknown amount never passes a finite ceiling)."""
    mode = _mode(state)
    found = {**(mode.get("budgets") or {}), **((mode.get("bounds") or {}).get("budget") or {})}
    # The operator's model-call ceiling is a step's ``broker_calls`` budget (the authority's naming).
    if "model_calls" in found and "broker_calls" not in found:
        found["broker_calls"] = found.pop("model_calls")
    return found


def _mode(state) -> dict:
    return deepcopy((state.get("context") or {}).get("mode") or {})


def _bound(state):
    return control.bounds(_mode(state))


def _view(store, state):
    return control.fold(control.events(store), _bound(state))


def _guarded(function):
    """Typed holds for absent components; the substrate's handler routes everything else."""
    def body(state):
        try:
            return function(state)
        except services.ComponentAbsent as exc:
            raise nodes.RecoveryHold(str(exc), exc.would_make_possible) from None
    body.__name__ = function.__name__
    return body


def _request(state, store) -> dict:
    """The verbatim request, reading and contract, read by digest from the store (or file pins)."""
    pins = state.get("request") or {}
    found = {}
    sources = (("text", "sha256", ("text", "request")), ("reading", "reading_sha256", ("reading",)),
               ("contract", "contract_sha256", ("contract",)))
    for key, blob_key, pin_keys in sources:
        raw = None
        if type(pins.get(blob_key)) is str and hasattr(store, "get_blob"):
            try:
                raw = store.get_blob(pins[blob_key])
            except Exception as exc:  # a missing or altered blob is a typed hold, not a guess
                raise nodes.RecoveryHold(f"the {key} blob cannot be read: {exc}", "restore the intake records")
            digest_value = pins[blob_key]
        else:
            pin = next((pins[k] for k in pin_keys if type(pins.get(k)) is dict), None)
            raw, problem = services.read_pin(_run(state), pin) if pin else (None, "no pin")
            if raw is None:
                raise nodes.RecoveryHold(f"the run state pins no readable {key}: {problem}",
                                         "the controller pins the request, reading and contract at intake")
            digest_value = pin["sha256"]
        found[key] = raw.decode("utf-8") if key == "text" else json.loads(raw)
        found[key + "_sha256"] = digest_value
    found["sha256"] = found["text_sha256"]
    return found


def _context_file(state, name, document) -> dict:
    """A content-addressed controller document under the run's ``inputs/``; never overwritten."""
    run = _run(state)
    if not run["run_dir"]:
        raise nodes.RecoveryHold("the context names no run directory", "the controller passes run_dir")
    raw = (json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    sha = hashlib.sha256(raw).hexdigest()
    relative = f"{CONTEXT_DIR}/{name}-{sha[:16]}.json"
    target = Path(run["run_dir"]) / relative
    if not target.exists():
        atomic_json(target, json.loads(raw))
    if hashlib.sha256(target.read_bytes()).hexdigest() != sha:
        raise nodes.RecoveryHold(f"context file {relative} differs from its content address", "remove the altered file")
    return {"artifact": relative, "sha256": sha}


def _inputs(state, store, request) -> dict:
    """Run-input copies of the request, reading and contract that the governed step can verify."""
    return {"request": _context_file(state, "request", {"request": request["text"], "sha256": request["sha256"]}),
            "reading": _context_file(state, "reading", request["reading"]),
            "contract": _context_file(state, "contract", request["contract"])}


def _base_inputs(inputs):
    return [deepcopy(inputs[name]) for name in ("request", "reading", "contract")]


def _bind(store, state, plan_doc, *, source, revision=None, applied=None) -> str:
    """Pin a controller plan, materialise its obligations (the ledger's plan stage) and record its plan-bind
    rows; return its digest.

    Each plan step's plan-bind rows (ownership, seat derivation) are recorded here from their checks
    and only verified by the governed step, so no plan is bound without them. The store's latest
    ``plan`` record and the ledger's current plan name the same plan: binding the plan that is
    already the latest appends no record, and materialising the current plan again appends nothing.
    """
    rows = [row for _, row in services.records(store, CONTROLLER_PLAN_KIND)]
    if not (rows and rows[-1].get("plan_sha256") == plan_doc["sha256"] and rows[-1].get("blob")):
        blob = store.put_blob(json.dumps(plan_doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                         allow_nan=False).encode("utf-8"))
        store.append(CONTROLLER_PLAN_KIND, {"plan_sha256": plan_doc["sha256"], "blob": blob, "source": source,
                                            "revision": revision,
                                            "route": (plan_doc.get("route") or {}).get("id") or "judgment",
                                            "open_obligations": len(plan_doc.get("open_obligations") or []),
                                            **deepcopy(applied or {})})
    try:
        services.call("ledger_materialise", store, "plan", {"plan": deepcopy(plan_doc), "run_id": _run(state)["run_id"]})
        # The plan-bind rows (ownership, seat derivation) are recorded as the plan is bound, from their checks.
        services.call("plan_bind", store, deepcopy(plan_doc), contract_sha256=plan_doc.get("contract_sha256"))
    except services.ComponentAbsent:
        raise
    except Exception as exc:  # a plan the ledger cannot state is never run under
        raise nodes.RecoveryHold("plan_unmaterialised", f"the ledger refused plan {plan_doc['sha256'][:12]}: "
                                 f"{type(exc).__name__}: {exc}"[:1000]) from None
    return plan_doc["sha256"]


def _step_context(state, plan_sha, phase, attempt=1, **extra):
    run, context = _run(state), state.get("context") or {}
    # The run's frozen agent preferences reach every judgment seat as P01 passed them (None holds the seat in P04).
    return {"run_id": run["run_id"], "run_dir": run["run_dir"], "store_root": run["store_root"],
            "plan_sha256": plan_sha, "attempt": attempt, "mode": _mode(state),
            "agent_preferences": deepcopy(context.get("agent_preferences")),
            "unattended": bool(context.get("unattended")), "purpose": "judgment-" + phase, "route": "judgment",
            "fresh_session": True, **extra}


def _held_plan(store):
    """The latest plan the run holds that is not a planning plan (an executing or proposed controller plan), or None."""
    for _, row in reversed(services.records(store, CONTROLLER_PLAN_KIND)):
        if row.get("source") != PLANNING_SOURCE and row.get("blob"):
            plan_doc = services.blob_json(store, row["blob"])
            if type(plan_doc) is not dict or plan_doc.get("sha256") != row.get("plan_sha256"):
                raise nodes.RecoveryHold("plan_digest_mismatch", "a held plan differs from its pinned digest")
            # The engagement decision's applied view pinned beside the plan travels with it when it is bound again.
            applied = {k: row[k] for k in ("applied_blob", "applied_sha256") if row.get(k) is not None}
            return {"plan": plan_doc, "source": row.get("source"), "revision": row.get("revision"), "applied": applied}
    return None


def _run_planning_steps(store, state, request, phase, step_list) -> dict:
    """Bind one phase's planning steps to a planning plan and run each through the governed step.

    While they run, the planning plan is the ledger's current plan (their plan-stage rows exist only
    there). Afterwards a plan the run already holds is current again, so a planning phase never
    displaces the population that the run's gates judge.
    """
    held = _held_plan(store)
    plan_doc = steps.planning_plan(step_list, run_id=_run(state)["run_id"], reading=request["reading"],
                                   request={"reading_sha256": request["reading_sha256"],
                                            "contract_sha256": request["contract_sha256"]}, phase=phase)
    sha = _bind(store, state, plan_doc, source=PLANNING_SOURCE)
    found = {}
    try:
        for step in step_list:
            outcome = services.call("step_run", store, step, _step_context(state, sha, phase))
            found[step["id"]] = services.normalize_outcome(outcome)
    finally:
        if held is not None:
            _bind(store, state, held["plan"], source=held["source"], revision=held["revision"],
                  applied=held.get("applied"))
    return found


def _findings(state, outcome, step_id):
    """Findings of a review worker's final record, when it was adopted (advisory feedback only)."""
    document, _ = services.read_output(_run(state), outcome, path="final-record.json", step_id=step_id)
    rows = (document or {}).get("findings") if type(document) is dict else None
    return deepcopy(rows)[:50] if type(rows) is list else []


def _credit(outcome):
    """A credit pointer for the ledger: the governed step's first receipt, when one exists."""
    return (outcome.get("receipts") or [None])[0]


def _catalogue_summary():
    catalogue = services.call("catalogue")
    operations = []
    for row in catalogue.get("operations") or []:
        descriptor = row.get("descriptor") or {}
        operations.append({"mode": row["mode"], "status": row.get("status"), "summary": descriptor.get("summary"),
                           "operations": descriptor.get("operations")})
    tools = [{"mode": row["mode"], "summary": row.get("summary")} for row in catalogue.get("planning_tools") or []]
    summary = {"operations": operations, "planning_tools": tools,
               "chains": [c["id"] for c in catalogue.get("declared_chains") or []], "scope": catalogue.get("scope")}
    statistics = (catalogue.get("statistics_situations") or {}).get("catalogue") or {}
    methods = statistics.get("methods") or {}
    rows = [{"situation": s["id"], "revealed_by": s.get("revealed_by"),
             "methods": [{"method": m, "cost": (methods.get(m) or {}).get("cost"),
                          "checks": (methods.get(m) or {}).get("checks")} for m in s.get("methods") or ()],
             "fallback": s.get("fallback")}
            for s in statistics.get("situations") or () if isinstance(s, dict) and s.get("id")]
    if rows:
        # The statistics problems a plan may meet, the installed methods (cheapest first) and their checks.
        summary["statistics"] = {"situations": rows, "purpose": statistics.get("purpose")}
    return summary


def _operations():
    catalogue = services.call("catalogue")
    return {row["mode"] for row in catalogue.get("operations") or []} | {
        row["mode"] for row in catalogue.get("planning_tools") or []}


def _routes(state):
    found = set(services.call("route_specs"))
    candidate = state.get("plan") if purpose(state) == "plan" else None
    if type(candidate) is dict and type((candidate.get("route") or {}).get("id")) is str:
        found.add(candidate["route"]["id"])
    found.discard("judgment")
    return found


def ledger_note(store, node, status, evidence, *, rows=None, step=None):
    """Record the judgment rows a node discharges; recording never gates.

    The ledger's own pending entries of the discharging node are recorded (filtered to
    ``rows`` and ``step``). A row the ledger refuses stays pending, and the transition gates
    that need it refuse the edge, so a missed record fails closed; the refusal is kept as a
    ``ledger_unrecorded`` event.
    """
    def wanted(keys):
        return [key for key in keys if rows is None or str(key).split("@", 1)[0] in rows]
    try:
        targets = wanted(services.call("ledger_pending", store, node=node, step=step) or []) if step else []
        if not targets:
            # A row the ledger instantiates once per run carries no step scope.
            targets = [k for k in wanted(services.call("ledger_pending", store, node=node) or [])
                       if "/step=" not in str(k)]
    except services.ComponentAbsent as exc:
        control.append(store, {"event": "ledger_unrecorded", "node": node, "status": status, "reason": str(exc)[:500]})
        return
    for key in targets:
        row = str(key).split("@", 1)[0]
        body = dict(evidence)
        if status == "violated":
            body.setdefault("reason", "the judgment route observed the violation")
        if status == "satisfied" and row in R_ROWS and not body.get("credit"):
            control.append(store, {"event": "ledger_unrecorded", "node": node, "entry": key, "status": status,
                                   "reason": "a review-gated row is satisfied only with a credit"})
            continue
        try:
            services.call("ledger_record", store, key, status, body)
        except Exception as exc:  # the ledger refused this entry; the edge stays fail-closed
            control.append(store, {"event": "ledger_unrecorded", "node": node, "entry": key, "status": status,
                                   "reason": f"{type(exc).__name__}: {exc}"[:500]})


def _operator():
    try:
        return services.call("operator_config") or {}
    except services.ComponentAbsent:
        return {}


def _wait_bound():
    value = _operator().get("wait_bound_seconds", _operator().get("wait_bound"))
    return value if type(value) in (int, float) and value >= 0 else None


def _authority(store, kind, subject, *, plan=None, reading=None, since=None, wait=False):
    """Ask the authority service; while pending and ``wait``, poll within the wait bound.

    A stop or pause request ends the wait at once (the answer stays pending), so the hub
    drains the run instead of sleeping out the operator's wait bound.
    """
    now = services.call("now")
    subject = deepcopy(subject)
    if plan is not None or reading is not None:
        # Compiler/reading sources are independent of the proposed check-in view. Preserve
        # supplied items so a conflicting view is refused against the captured snapshot.
        source = deepcopy(reading)
        if type(plan) is not dict or type(source) is not dict:
            return services.normalize_authority({"pending": {"reason": "retained plan and reading are missing"}})
        if not {"request_pins", "inferred_critical_facts", "flags"} <= source.keys():
            return services.normalize_authority({"pending": {"reason": "retained reading disclosures are missing"}})
        view = subject["view"]
        items = view.setdefault("items", {})
        for key, value in (source.get("items") or {}).items():
            items.setdefault(key, deepcopy(value))
        for key in ("steps", "deliverables", "boundaries"):
            items.setdefault(key, deepcopy(plan.get(key, [])))
        flags = deepcopy(source.get("flags") or [])
        for flag in view.get("flags") or []:
            if flag not in flags:
                flags.append(deepcopy(flag))
        view["flags"] = source["flags"] = flags
        source["items"] = {**{k: deepcopy(v) for k, v in items.items()
                             if k not in ("steps", "deliverables", "boundaries")},
                           **deepcopy(source.get("items") or {})}
        try:
            services.call("authority_capture", store, kind, plan=plan, reading=source, view=view)
        except ValueError as exc:
            return services.normalize_authority({"pending": {"reason": str(exc)}})

    def request():
        return services.normalize_authority(services.call("authority_request", store, kind, subject, {}),
                                            store=store, kind=kind, subject=subject["view"].get("pins"))

    result = request()
    if result["state"] != "pending":
        return result
    bound = result["wait_bound"] if type(result["wait_bound"]) in (int, float) else _wait_bound()
    result = {**result, "since": since if since is not None else (result["since"] or now), "wait_bound": bound}
    if not wait or bound is None:
        return result
    poll = planning.policy()["ask"]["poll_seconds"]
    deadline = result["since"] + bound
    while services.call("now") < deadline:
        services.call("sleep", max(0.0, min(poll, deadline - services.call("now"))))
        if services.call("stop_state", store) in STOPPING + ("pause_requested",):
            return result
        again = request()
        if again["state"] != "pending":
            return again
    return result


def _view_subject(store, *, pins, summary, items=None, flags=None, options=None, section=None):
    """An authority-service check-in view: run, pins, items, flags and options."""
    view = {"run_id": store.run_id, "pins": dict(pins), "summary": summary,
            "sections": [{"id": "preamble", "title": "Preamble", "lines": [summary]}]}
    if section:
        name, lines = section
        view["sections"].append({"id": name, "title": name.title(), "lines": list(lines)})
    if items:
        view["items"] = deepcopy(items)
    if flags:
        view["flags"] = [{"kind": f["kind"], "text": str(f["text"])[:1000]} for f in flags]
    if options:
        view["options"] = options
    return view


def _authority_reading(state, store):
    """Explicit disclosures derived from the pinned intake reading, never the check-in view."""
    reading = deepcopy(_request(state, store)["reading"])
    reading.setdefault("request_pins", {})
    reading.setdefault("inferred_critical_facts", [])
    for fact in reading.get("facts") or []:
        if fact.get("physics_critical") and fact.get("authority") == "inferred" \
                and fact not in reading["inferred_critical_facts"]:
            reading["inferred_critical_facts"].append(deepcopy(fact))
    reading.setdefault("flags", [])
    return reading


# ---- nodes: start and hub -------------------------------------------------------------------

def start(state):
    store = _store(state)
    rows = control.events(store)
    if not any(row["event"] == "started" for row in rows):
        request = _request(state, store)
        # The route's own rows (JR01 onwards) are plan-stage rows: the first planning plan, with no step
        # yet and every deliverable open, materialises them before the first is recorded.
        _run_planning_steps(store, state, request, "start", [])
        route = deepcopy((state.get("context") or {}).get("route") or {})
        identifier = control.append(store, {"event": "started", "request_sha256": request["sha256"],
                                            "route": route, "purpose": purpose(state)})
        ledger_note(store, "judgment.frame", "satisfied", {"mechanism": "route_select→judgment.plan",
                                                           "record": identifier}, rows=("JR01",))
    return {"passes": state.get("passes", 0)}


def advance(state):
    store = _store(state)
    stop = services.call("stop_state", store)
    mode = purpose(state)
    if stop in STOPPING or stop == "pause_requested":
        reason = f"stop: {stop}"
        decision = ({"phase": "planning_held", "reason": reason, "detail": {"stop_state": stop}} if mode != "route"
                    else {"phase": "hold", "reason": "pause_requested", "detail": {}} if stop == "pause_requested"
                    else {"phase": "bounded_end", "reason": reason, "detail": {"stop_state": stop}})
    elif mode == "route":
        view = _view(store, state)
        decision = control.next_phase(view, _bound(state), now=services.call("now"), wait_bound=_wait_bound())
        if decision["phase"] == "kill_the_result":
            unmet = services.call("ledger_gate", store, "execute→final_review") or []
            if unmet:
                decision = {"phase": "bounded_end", "reason": "the ledger refuses the edge to the final review",
                            "detail": {"unmet": deepcopy(unmet)[:20]}}
    else:
        view = _view(store, state)
        decision = control.next_planning(view, _bound(state), purpose=mode, revision=_revision(state))
    return {"decision": decision, "passes": state.get("passes", 0) + 1}


def _route(state):
    decision = state.get("decision") or {}
    phase = decision.get("phase")
    if phase == "gate":
        return GATES[decision["detail"]["gate"]]
    if phase == "hold":
        return "paused" if decision.get("reason") == "pause_requested" else "done"
    return phase


# ---- nodes: framing and decomposition (both purposes) ----------------------------------------------

def frame(state):
    store = _store(state)
    request = _request(state, store)
    inputs = _inputs(state, store, request)
    view = _view(store, state)
    number = state["decision"]["detail"]["round"]
    previous = view["frame"]
    feedback = list((previous or {}).get("problems") or []) + list(((previous or {}).get("review") or {}).get(
        "findings") or [])
    candidate = state.get("plan") if purpose(state) == "plan" else None
    context = _context_file(state, f"frame-{number}", {
        "schema": "question-frame.v1", "request_sha256": request["sha256"], "catalogue": _catalogue_summary(),
        "route_specs": sorted(_routes(state)), "subgraphs": planning.policy()["subgraphs"],
        "step_kinds": planning.policy()["step_kinds"], "feedback": feedback, "covered_by_route": candidate,
        "recovery": services.call("recovery_hints", request["text"], request["contract"], request["reading"])})
    step = steps.planner_step(
        "frame", number, inputs=_base_inputs(inputs) + [context], output="frame",
        obligations=["JR01", "JR02", "R10", "ROUTE-unsupported"],
        purpose="Frame the request as question-frame.v1: the objective; every reading deliverable with its acceptance "
                "criterion, requested statistic and units; constraints; unknowns; numbered assumptions; and the "
                "boundaries that would hold work. Execute nothing.")
    outcome = _run_planning_steps(store, state, request, "frame", [step])[step["id"]]
    event = {"event": "frame", "round": number, "step": step["id"], "frame_sha256": None, "frame_record": None,
             "problems": [], "status": outcome["status"]}
    if outcome["status"] == "adopted":
        document, where = services.read_output(_run(state), outcome, path=step["outputs"][0]["path"],
                                               step_id=step["id"])
        if document is None:
            event.update(status="no_output", problems=[where])
        else:
            problems = planning.check_frame(document, request["reading"], request["sha256"])
            if problems:
                event.update(status="refused", problems=problems)
            else:
                sha = digest(document)
                record = store.append(control.FRAME_KIND, {"schema_version": 1, "kind": control.FRAME_KIND,
                                                           "round": number, "frame": document, "sha256": sha})
                event.update(status="written", frame_sha256=sha, frame_record=record)
    else:
        event["problems"] = [outcome.get("reason") or f"the frame step ended {outcome['status']}"]
    control.append(store, event)
    return {}


def _frame_document(store, view):
    accepted = view["frame_accepted"] or {}
    record_id = accepted.get("record") or (view["frame"] or {}).get("frame_record")
    return services.record(store, control.FRAME_KIND, record_id)["frame"]


def frame_review(state):
    store = _store(state)
    request = _request(state, store)
    inputs = _inputs(state, store, request)
    view = _view(store, state)
    current = view["frame"]
    document = services.record(store, control.FRAME_KIND, current["frame_record"])["frame"]
    attempt = view["frame_review_attempts"].get(current["frame_sha256"], 0) + 1
    pin = _context_file(state, f"frame-{current['round']}-adopted", document)
    step = steps.review_step(
        f"judgment-frame-review-{current['round']}-{attempt}", seats=[planning.policy()["roles"]["critic"]],
        subject={"kind": "question-frame", "sha256": current["frame_sha256"]},
        must_check=planning.frame_must_check(document, request["reading"]), inputs=_base_inputs(inputs) + [pin],
        obligations=["JR02", "R10"],
        purpose="Review the question frame against the reading: every deliverable, numbered assumptions, listed "
                "unknowns and held boundaries.")
    outcome = _run_planning_steps(store, state, request, "frame-review", [step])[step["id"]]
    credited = outcome["status"] == "adopted" and outcome["credited"]
    verdict = services.normalize_verdict(outcome["verdict"]) if credited else "fail"
    identifier = control.append(store, {"event": "frame_review", "round": current["round"],
                                        "frame_sha256": current["frame_sha256"], "credited": credited,
                                        "verdict": verdict, "findings": _findings(state, outcome, step["id"]),
                                        "attempt": attempt, "credit": _credit(outcome)})
    if credited and verdict == "pass":
        ledger_note(store, "judgment.frame", "satisfied", {"record": identifier, "credit": _credit(outcome),
                                                           "sha256": current["frame_sha256"]},
                    rows=("JR02", "R10", "ROUTE-unsupported"))
    return {}


def _tool_inputs(store, request):
    """What the capability-need check reads: the run's pinned environment profile and supplied inputs (from the
    controller store) with the request's derived label (pinned at intake), reading and text. None when the store
    keeps no profile."""
    latest = getattr(store, "latest", None)
    if not callable(latest):
        return None
    profile = latest("environment-profile")
    if profile is None:
        return None
    supplied, intake = latest("supplied"), latest("intake")
    return {"profile": profile["record"], "profile_record": profile["id"],
            "supplied": deepcopy(((supplied or {}).get("record") or {}).get("inputs") or []),
            "label": deepcopy(((intake or {}).get("record") or {}).get("label")), "reading": request.get("reading"),
            "request_text": request.get("text")}


def _tool_view(store, request):
    """Every capability need, whether it arises for this request and its ranked candidates on this host."""
    inputs = _tool_inputs(store, request)
    if inputs is None:
        return None
    from ravel.workflow import tool_selection
    return tool_selection.planning_view(**{k: v for k, v in inputs.items() if k != "profile_record"})


def _planner_context(state, store, view, frame_doc, name, extra):
    tools = _tool_view(store, _request(state, store))
    return _context_file(state, name, {
        "schema": "judgment-plan.v1", "frame_sha256": view["frame_accepted"]["frame_sha256"], "frame": frame_doc,
        "frame_findings": view["frame_accepted"]["findings"], "catalogue": _catalogue_summary(),
        "route_specs": sorted(_routes(state)), "subgraphs": planning.policy()["subgraphs"],
        "step_kinds": planning.policy()["step_kinds"], "seed_plan": recovery.seed_plan(frame_doc),
        **({"tools": tools} if tools is not None else {}), **extra})


def decompose(state):
    store = _store(state)
    request = _request(state, store)
    inputs = _inputs(state, store, request)
    view = _view(store, state)
    detail = state["decision"]["detail"]
    frame_doc = _frame_document(store, view)
    revision = detail.get("revision")
    tag = f"r{revision}-{detail['round']}" if revision is not None else str(detail["round"])
    candidate = state.get("plan") if purpose(state) == "plan" else None
    context = _planner_context(state, store, view, frame_doc, f"decompose-{tag}", {
        "feedback": detail.get("problems"), "covered_by_route": candidate,
        "previous_plan": state.get("plan") if purpose(state) == "plan" and revision else None})
    step = steps.planner_step(
        "decompose", 0, inputs=_base_inputs(inputs) + [context], output="plan", obligations=["JR03"],
        purpose="Decompose the frame into judgment-plan.v1: a DAG of typed steps from the closed vocabulary, each with "
                "inputs, outputs, obligations, budget share, protocols and seats; judgment calls as decide steps; every "
                "frame deliverable mapped to one step output or held with its reason. Execute nothing.")
    step["id"] = f"judgment-decompose-{tag}"
    _plan_step(store, state, request, view, step, frame_doc, source="decompose", round_=detail["round"],
               revision=revision)
    return {}


def _plan_step(store, state, request, view, step, frame_doc, *, source, round_, revision, failures=()):
    outcome = _run_planning_steps(store, state, request, source, [step])[step["id"]]
    event = {"event": "plan", "source": source, "step": step["id"], "status": outcome["status"], "plan_sha256": None,
             "plan_record": None, "frame_sha256": view["frame_accepted"]["frame_sha256"], "problems": [],
             "round": round_ if source == "decompose" and revision is None else 0, "revision": revision}
    if outcome["status"] == "adopted":
        document, where = services.read_output(_run(state), outcome, path=step["outputs"][0]["path"],
                                               step_id=step["id"])
        if document is None:
            event.update(status="no_output", problems=[where])
        else:
            problems = planning.check_plan(document, frame_doc, operations=_operations(), routes=_routes(state),
                                           roles=services.call("roles"), failures=tuple(failures),
                                           tools=_tool_inputs(store, request))
            if problems:
                event.update(status="refused", problems=problems)
            else:
                sha = digest(document)
                record = store.append(control.PLAN_KIND, {"schema_version": 1, "kind": control.PLAN_KIND,
                                                          "source": source, "plan": document, "sha256": sha})
                event.update(status="written", plan_sha256=sha, plan_record=record)
    else:
        event["problems"] = [outcome.get("reason") or f"the planner step ended {outcome['status']}"]
    identifier = control.append(store, event)
    if event["status"] == "written":
        ledger_note(store, "judgment.decompose", "satisfied", {"record": identifier, "sha256": event["plan_sha256"]},
                    rows=("JR03",))
    return event


def _plan_for(view, decision):
    detail = decision["detail"]
    if detail.get("revision") is not None:
        rows = [r for r in view["plans_for"].get(detail["revision"], []) if r["status"] == "written"]
        return rows[-1] if rows else view["plan"]
    return view["plan"]


def classify_calls(state):
    store = _store(state)
    view = _view(store, state)
    detail = state["decision"]["detail"]
    frame_doc = _frame_document(store, view)
    row = _plan_for(view, state["decision"])
    plan_doc = services.record(store, control.PLAN_KIND, row["plan_record"])["plan"]
    calls = planning.classify_steps(plan_doc, frame_doc)
    adopted = control.adopted_plan(view)
    if purpose(state) == "route":
        revision = 0 if adopted is None else view["replans"]
        changes = planning.scope_delta(adopted, plan_doc, frame_doc) if adopted else []
    else:
        revision = detail.get("revision", _revision(state))
        changes = _controller_scope_delta(state.get("plan") if purpose(state) == "replan" else None, plan_doc,
                                          frame_doc)
    compiled = planning.compile_plan(plan_doc, frame_doc, calls, revision=revision,
                                     parent_sha256=adopted["compiled_sha256"] if adopted else None)
    record = store.append(control.COMPILED_KIND, compiled)
    identifier = control.append(store, {"event": "classified", "compiled_sha256": compiled["sha256"],
                                        "planner_plan_sha256": compiled["planner_plan_sha256"], "revision": revision,
                                        "scope_changes": changes, "steps": compiled["steps"],
                                        "deliverables": compiled["deliverables"], "calls": compiled["calls"],
                                        "frame_sha256": compiled["frame_sha256"], "sha256": compiled["sha256"],
                                        "record": record})
    lowered = sorted(name for name, found in calls.items() if found["declared_lower"])
    ledger_note(store, "judgment.classify", "satisfied", {"record": identifier, "mechanism": "classes.explain",
                                                          "sha256": compiled["sha256"]}, rows=("JR06", "A05"))
    if lowered:
        control.append(store, {"event": "flag", "text": "the planner declared a class below the computed one for "
                                                        + ", ".join(lowered) + "; the computed class applies"})
    return {}


def _controller_scope_delta(old_plan, plan_doc, frame_doc):
    """Scope changes of a replan against the controller plan it replaces (reading-keyed deliverables)."""
    if type(old_plan) is not dict:
        return []
    framed = {d["id"]: d for d in frame_doc["deliverables"]}
    new = {}
    for row in plan_doc["deliverables"]:
        name = (framed.get(row["id"]) or {}).get("reading_ref") or row["id"]
        new[name] = "mapped" if row["status"] == "planned" else "open"
    old = {row["id"]: row["status"] for row in old_plan.get("deliverables") or [] if type(row) is dict}
    changes = [{"kind": "deliverable_dropped", "deliverable": name} for name in sorted(set(old) - set(new))]
    changes += [{"kind": "deliverable_added", "deliverable": name} for name in sorted(set(new) - set(old))]
    changes += [{"kind": "deliverable_dropped", "deliverable": name, "detail": "newly held"}
                for name in sorted(set(old) & set(new)) if old[name] == "mapped" and new[name] == "open"]
    return changes


def plan_review(state):
    store = _store(state)
    request = _request(state, store)
    inputs = _inputs(state, store, request)
    view = _view(store, state)
    sha = state["decision"]["detail"]["compiled_sha256"]
    compiled = view["compiled_history"][sha]
    frame_doc = _frame_document(store, view)
    attempt = (view["plan_review"].get(sha) or {}).get("attempts", 0) + 1
    pin = _context_file(state, f"plan-{compiled['revision']}-{attempt}", {
        "compiled": {k: compiled.get(k) for k in ("compiled_sha256", "revision", "steps", "deliverables", "calls",
                                                  "scope_changes")}, "frame": frame_doc})
    batch, critic = [], None
    if state["decision"]["detail"].get("critic", True):
        plan_doc = services.record(store, control.PLAN_KIND, _plan_for(view, state["decision"])["plan_record"])["plan"]
        critic = steps.review_step(
            f"judgment-plan-review-{compiled['revision']}-{attempt}", seats=[planning.policy()["roles"]["critic"]],
            subject={"kind": "judgment-plan", "sha256": sha}, must_check=planning.plan_must_check(plan_doc, frame_doc),
            inputs=_base_inputs(inputs) + [pin], obligations=["JR03", "C01", "E03", "R10"],
            purpose="Review the decomposition before CHECK-IN 1: obligations, routes, method ladders, source ladders, "
                    "held scope and resource contracts.")
        batch.append(critic)
    cases = {}
    for row in control.rdj_calls(compiled):
        case = steps.rdj_step(f"judgment-rdj-{row['id']}-{compiled['revision']}-{attempt}",
                              subject={"kind": "step-spec", "step": row["id"], "sha256": row["spec_sha256"],
                                       "class": row["class"]},
                              must_check=protocols.must_check(row["triggers"]) + [{
                                  "id": "JR06:class", "row": "JR06",
                                  "text": f"The planned {row['class']} step {row['id']} is justified before its effect."}],
                              inputs=[pin], purpose=f"Independent RDJ review of the planned {row['class']} step {row['id']}.",
                              protocols=protocols.protocol_ids_for(row["triggers"]))
        cases[row["id"]] = case
        batch.append(case)
    outcomes = _run_planning_steps(store, state, request, "plan-review", batch) if batch else {}
    if critic is not None:
        found = outcomes[critic["id"]]
        credited = found["status"] == "adopted" and found["credited"]
        verdict = services.normalize_verdict(found["verdict"]) if credited else "fail"
        findings, credit = _findings(state, found, critic["id"]), _credit(found)
    else:
        credited, verdict, findings, credit = True, "pass", [], None
    rdj = {}
    for name, case in cases.items():
        found = outcomes[case["id"]]
        case_verdict = services.normalize_verdict(found["verdict"])
        # An RDJ case counts only when its observed seat session is credited and it approves the step.
        rdj[name] = {"event": "review", "step": name, "subject_sha256": case["parameters"]["judgment"]["subject"]["sha256"],
                     "credited": found["status"] == "adopted" and found["credited"] and case_verdict == "pass",
                     "verdict": case_verdict, "attempt": attempt, "credit_id": _credit(found), "kind": "rdj"}
    control.append(store, {"event": "plan_review", "compiled_sha256": sha, "credited": credited, "verdict": verdict,
                           "findings": findings, "rdj": rdj, "credit": credit, "critic": critic is not None})
    return {}


def replan(state):
    store = _store(state)
    request = _request(state, store)
    inputs = _inputs(state, store, request)
    view = _view(store, state)
    detail = state["decision"]["detail"]
    frame_doc = _frame_document(store, view)
    if purpose(state) == "route":
        adopted = control.adopted_plan(view)
        revision, number, failures = None, detail["number"], tuple(view["failures"])
        payload = {"request": view["replan_request"], "failures": list(failures),
                   "adopted": {k: adopted[k] for k in ("compiled_sha256", "steps", "deliverables")} if adopted else None,
                   "steps": {name: {k: row.get(k) for k in ("status", "attempts", "reason")}
                             for name, row in view["steps"].items()}}
    else:
        context = state.get("context") or {}
        revision, number = detail["revision"], detail.get("round", 1)
        failures = tuple(sorted(name for name, row in (context.get("steps") or {}).items()
                                if type(row) is dict and row.get("status") == "failed"))
        payload = {"request": deepcopy(context.get("replan_requests") or {}), "failures": list(failures),
                   "previous_plan": deepcopy(state.get("plan")), "steps": deepcopy(context.get("steps") or {})}
    tag = f"r{revision}-{number}" if revision is not None else str(number)
    pin = _planner_context(state, store, view, frame_doc, f"replan-{tag}", payload)
    step = steps.planner_step(
        "replan", 0, inputs=_base_inputs(inputs) + [pin], output="plan", obligations=["JR07", "JR03"],
        purpose="Propose a revised judgment-plan.v1 for the replan request: keep closed steps unchanged, cover every "
                "failed step with a stage-recovery decision, keep every frame deliverable mapped or held. Execute "
                "nothing.")
    step["id"] = f"judgment-replan-{tag}"
    event = _plan_step(store, state, request, view, step, frame_doc, source="replan", round_=0, revision=revision,
                       failures=failures)
    identifier = control.append(store, {"event": "replan", "number": number if revision is None else
                                        len(view["replanned"]) + 1, "revision": revision,
                                        "status": "proposed" if event["status"] == "written" else "refused",
                                        "plan_sha256": event["plan_sha256"], "problems": event["problems"][:20]})
    if event["status"] == "written":
        ledger_note(store, "judgment.replan", "satisfied", {"record": identifier, "mechanism": "bounded replan"},
                    rows=("JR07",))
    return {}


def return_plan(state):
    store = _store(state)
    request = _request(state, store)
    inputs = _inputs(state, store, request)
    view = _view(store, state)
    detail = state["decision"]["detail"]
    if detail["revision"] in view["returned"]:
        returned = view["returned"][detail["revision"]]
        return {"results": {"plan": services.blob_json(store, returned["blob"])}}
    compiled = view["compiled_history"][detail["compiled_sha256"]]
    frame_doc = _frame_document(store, view)
    review = view["plan_review"].get(compiled["compiled_sha256"]) or {}
    plan = planning.controller_plan(compiled, frame=frame_doc, reading=request["reading"],
                                    run_id=_run(state)["run_id"], revision=detail["revision"], inputs=inputs,
                                    request={"reading_sha256": request["reading_sha256"],
                                             "contract_sha256": request["contract_sha256"]},
                                    envelope=_envelope(state),
                                    rdj={k: v.get("credit_id") for k, v in (review.get("rdj") or {}).items()},
                                    frame_findings=view["frame_accepted"]["findings"],
                                    final_seats=_final_seats(state))
    problems = planning.controller_plan_problems(plan)
    if problems:
        raise nodes.RecoveryHold("judgment_plan_invalid", "; ".join(problems[:5]))
    blob = store.put_blob(json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode("utf-8"))
    control.append(store, {"event": "returned", "revision": detail["revision"], "purpose": purpose(state),
                           "plan_sha256": plan["sha256"], "compiled_sha256": compiled["compiled_sha256"],
                           "blob": blob})
    return {"results": {"plan": plan}}


def planning_held(state):
    decision = state.get("decision") or {}
    status = state.get("status") or {}
    reason = decision.get("reason") or status.get("reason") or "judgment planning held"
    return {"status": {"phase": "hold", "terminal": "hold", "reason": "judgment_planning_held: " + reason,
                       "would_make_possible": "a revised request, a credited review or a higher bound; the "
                                              "controller ends the run with a qualified delivery"}}


# ---- nodes: the route (purpose route) ------------------------------------------------------------

def _final_seats(state):
    """The roles the run's review policy owes the final task or delivery (``review_points.controller_seats``); none
    when the policy cannot be read, and the final task's review-point check then refuses for each seat it lacks."""
    from ravel.workflow import review_points
    try:
        return review_points.controller_seats(_run(state)["run_dir"])
    except Exception:
        return []


def _controller_plan(state, store, view, compiled):
    """The controller plan of a compiled plan, written into the store for the governed step."""
    request = _request(state, store)
    inputs = _inputs(state, store, request)
    review = view["plan_review"].get(compiled["compiled_sha256"]) or {}
    plan = planning.controller_plan(compiled, frame=_frame_document(store, view), reading=request["reading"],
                                    run_id=_run(state)["run_id"], revision=compiled.get("revision") or 0,
                                    inputs=inputs, request={"reading_sha256": request["reading_sha256"],
                                                            "contract_sha256": request["contract_sha256"]},
                                    envelope=_envelope(state),
                                    rdj={k: v.get("credit_id") for k, v in (review.get("rdj") or {}).items()},
                                    frame_findings=view["frame_accepted"]["findings"],
                                    final_seats=_final_seats(state))
    _bind(store, state, plan, source="judgment-route", revision=compiled.get("revision") or 0)
    return plan


def _approval_id(view):
    """The CHECK-IN 1 authority record of the plan the route adopted first."""
    for compiled_sha, row in view["checkin1"].items():
        if row["authority"]["state"] in control.GRANTED:
            return row["authority"].get("record_id")
    return None


def checkin1(state):
    store = _store(state)
    view = _view(store, state)
    sha = state["decision"]["detail"]["compiled_sha256"]
    compiled = view["compiled_history"][sha]
    frame_doc = _frame_document(store, view)
    plan = _controller_plan(state, store, view, compiled)
    review = view["plan_review"].get(sha) or {}
    flags = [{"kind": "assumption", "text": f"{a['number']}. {a['statement']} ({a['basis']})"}
             for a in frame_doc["assumptions"]]
    flags += [{"kind": "risk", "text": f"Boundary {b['id']}: {b['statement']}"}
              for b in frame_doc["boundaries"]]
    flags += [{"kind": "risk", "text": f"class {c['class']}: {name}"} for name, c in sorted(compiled["calls"].items())
              if c["class"] in ("R2", "R3")]
    flags += [{"kind": "risk", "text": str(f)[:500]} for f in view["frame_accepted"]["findings"]
              + list(review.get("findings") or [])]
    subject = {"view": _view_subject(
        store, pins={"plan_sha256": plan["sha256"]}, summary=f"Judgment-route plan {plan['sha256'][:12]}",
        items={"steps": plan["steps"], "deliverables": plan["deliverables"],
               "boundaries": plan.get("boundaries", []),
               "questions": [f"{u['id']}: {u['question']}" for u in frame_doc["unknowns"]]},
        flags=flags)}
    previous = (view["checkin1"].get(sha) or {}).get("authority") or {}
    result = _authority(store, "approve_plan", subject, since=previous.get("since"),
                        plan=plan, reading=_authority_reading(state, store),
                        wait=bool(state["decision"]["detail"].get("wait")))
    control.append(store, {"event": "checkin1", "compiled_sha256": sha, "plan_sha256": plan["sha256"],
                           "authority": {**result, "subject_sha256": sha}})
    return {}


def _gate_action(state, gate):
    detail = state["decision"]["detail"]
    action = {"kind": "judgment." + gate, "digest": detail["subject_sha256"], "summary": f"judgment route {gate}",
              "pins": [], "node_id": None, "rung": None, "scope": None}
    if gate == "delivery":
        store = _store(state)
        result = control.draft(_view(store, state))
        action["outputs"] = [{"id": row["id"], "artifact": out, "requirement_ids": [row["id"]]}
                             for row in result["deliverables"] for out in row["outputs"]]
    return action


def _error(gate, code, message, fix, pins=()):
    return {"code": code, "gate": gate, "provider": "judgment", "message": message, "fix": fix, "pins": list(pins)}


def _gate_checks(state, store, gate):
    """The judgment route's own checks beside the decision gate and the ledger."""
    detail = state["decision"]["detail"]
    subject = detail["subject_sha256"]
    errors = []
    if (nodes.GATE_CHECK.get() is not None or nodes.GATE_PROVIDERS.get() is not None) and not services.seams_enabled():
        errors.append(_error(gate, "gate_seam_refused", "an in-process gate override is active in a controller run",
                             "run without gate overrides; only the controller test harness may enable them"))
    for row in services.call("ledger_gate", store, TRANSITIONS[gate]) or []:
        name = (row.get("id") or row.get("entry") or row.get("entry_id")) if type(row) is dict else str(row)
        errors.append({"code": "ledger_unmet", "gate": gate, "provider": "ledger",
                       "message": f"obligation {name} is not met for {TRANSITIONS[gate]}",
                       "fix": "discharge the obligation or carry it as a labelled limitation", "pins": [str(name)]})
    view = _view(store, state)
    if gate == "approve_plan":
        authority = (view["checkin1"].get(subject) or {}).get("authority") or {}
        if authority.get("state") not in control.GRANTED or authority.get("subject_sha256") != subject:
            errors.append(_error(gate, "authority_missing", "no CHECK-IN 1 authority record for this exact plan",
                                 "answer CHECK-IN 1 through the authority service", [subject]))
    elif gate == "deviation":
        authority = (view["deviation"].get(subject) or {}).get("authority") or {}
        if authority.get("state") not in control.GRANTED:
            errors.append(_error(gate, "authority_missing", "no renewed authority for this scope-changing replan",
                                 "answer the deviation through the authority service", [subject]))
    elif gate == "failed_stage_feedback":
        errors.extend(recovery_errors(store, _request(state, store)["contract"], subject))
    elif gate in ("final_task", "delivery"):
        authority = (view["checkin3"].get(subject) or {}).get("authority") or {}
        if authority.get("state") not in control.ACCEPTED:
            errors.append(_error(gate, "authority_missing", "no CHECK-IN 3 authority record for this result",
                                 "answer CHECK-IN 3 through the authority service", [subject]))
        if gate == "delivery":
            attacks = view["attacks"].get(subject)
            if attacks is None or attacks["status"] != "valid":
                errors.append(_error(gate, "attacks_missing", "delivery without the three recorded P8 attacks",
                                     "run kill_the_result before the final review", [subject]))
            review = view["final_review"].get(subject)
            if review is None or not review["credited"] or review["verdict"] != "pass":
                errors.append(_error(gate, "final_review_missing", "no credited passing final review of this result",
                                     "run the fresh final review", [subject]))
            if control.draft(view)["missing"]:
                errors.append(_error(gate, "deliverable_output_missing", "planned deliverables lack adopted outputs",
                                     "produce or hold every deliverable", [subject]))
    return errors


def recovery_errors(store, contract, subject):
    """GATE-failed_stage_feedback and E12: an epoch-two contract and complete recovery evidence."""
    errors = []
    if type(contract) is not dict or contract.get("agent_layer_epoch") != 2:
        errors.append(_error("failed_stage_feedback", "epoch_one_layout_refused",
                             "an epoch-one contract cannot pass a controller decision gate",
                             "the controller run's contract is epoch two"))
    stored = records.by_digest(store, subject)
    if stored is None:
        return errors + [_error("failed_stage_feedback", "recovery_record_missing",
                                "no judgment record for this feedback", "record the stage-recovery decision",
                                [subject])]
    evidence = (stored.get("protocol_evidence") or {}).get("recovery")
    problems = protocols.check("recovery", evidence) if evidence is not None else [
        "missing local diagnosis and recipe search evidence"]
    return errors + [_error("failed_stage_feedback", "recovery_evidence_incomplete", p,
                            "run local diagnosis and the external recipe search as co-primary steps", [subject])
                     for p in problems]


def _gate_node(gate):
    """Gate node: decision gate on the run directory, the ledger transition and the judgment checks."""
    def body(state):
        import time
        store = _store(state)
        meta = nodes._meta(state)
        action = _gate_action(state, gate)
        run_dir = _run(state)["run_dir"] or meta["scope_root"]
        errors = list(nodes.check_gate(str(run_dir), gate, action, graph_id=meta["graph_id"]))
        errors += _gate_checks(state, store, gate)
        return {"gates": {gate: {"action_digest": action["digest"], "errors": errors,
                                 "providers": sorted({e.get("provider", "") for e in errors}),
                                 "checked_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                 "sequence": time.time_ns()}}}
    body.__name__ = "judgment_gate_" + gate
    return nodes.Node("gate", _guarded(body), gate=gate)


# A passing gate discharges its row; a refusal leaves the row pending (the refusal stays in the gate
# event), so a later passing decision can still discharge it, as the ledger's own decisions do.
GATE_NOTES = {"failed_stage_feedback": ("ledger.gate[failed_stage_feedback]", ("GATE-failed_stage_feedback",)),
              "deviation": ("judgment.replan", ("JR07",))}


def _record_gate(state, passed):
    store = _store(state)
    detail = state["decision"]["detail"]
    verdict = (state.get("gates") or {}).get(detail["gate"]) or {}
    identifier = control.append(store, {"event": "gate", "gate": detail["gate"],
                                        "subject_sha256": detail["subject_sha256"],
                                        "transition": TRANSITIONS[detail["gate"]], "passed": passed,
                                        "errors": deepcopy(verdict.get("errors") or [])[:50]})
    if passed and detail["gate"] in GATE_NOTES:
        node, rows = GATE_NOTES[detail["gate"]]
        ledger_note(store, node, "satisfied", {"gate": detail["gate"], "record": identifier,
                                               "mechanism": "decision_gate.check + ledger.gate"}, rows=rows)
    return {}


def gate_passed(state):
    return _record_gate(state, True)


def gate_refused(state):
    return _record_gate(state, False)


def adopt(state):
    store = _store(state)
    sha = state["decision"]["detail"]["compiled_sha256"]
    identifier = control.append(store, {"event": "adopted", "compiled_sha256": sha})
    ledger_note(store, "judgment.replan", "satisfied", {"record": identifier, "mechanism": "scope-preserving replan"},
                rows=("JR07",))
    return {}


def _adopted_controller_plan(state, store, view):
    compiled = control.adopted_plan(view)
    return compiled, _controller_plan(state, store, view, compiled)


def execute(state):
    store = _store(state)
    request = _request(state, store)
    view = _view(store, state)
    compiled, plan = _adopted_controller_plan(state, store, view)
    detail = state["decision"]["detail"]
    by_id = {s["id"]: s for s in compiled["steps"]}
    planned = {s["id"]: s for s in plan["steps"]}
    number = view["waves"] + 1
    reviews = []
    for item in detail.get("reviews") or []:
        row = by_id[item["step"]]
        stored = records.by_digest(store, item["subject_sha256"]) if item["subject"] == "record" else None
        pin = _context_file(state, f"review-{row['id']}-{item['attempt']}", {
            "step": {k: row[k] for k in ("id", "kind", "purpose", "class", "spec_sha256")}, "record": stored,
            "outcome": (view["steps"].get(row["id"]) or {}).get("outcome")})
        must = records.reviewer_items(stored) if stored else protocols.must_check(row["triggers"])
        reviews.append((item, steps.rdj_step(f"judgment-rdj-{row['id']}-{item['subject']}-{item['attempt']}",
                                             subject={"kind": item["subject"], "step": row["id"],
                                                      "sha256": item["subject_sha256"],
                                                      "class": (stored or row)["class"]},
                                             must_check=must, inputs=[pin],
                                             purpose=f"Independent RDJ review of {row['id']}.",
                                             protocols=protocols.protocol_ids_for(row["triggers"]))))
    if reviews:
        found = _run_planning_steps(store, state, request, "wave-review", [case for _, case in reviews])
        for item, case in reviews:
            outcome = found[case["id"]]
            verdict = services.normalize_verdict(outcome["verdict"])
            control.append(store, {"event": "review", "step": item["step"], "subject_sha256": item["subject_sha256"],
                                   "credited": outcome["status"] == "adopted" and outcome["credited"]
                                   and verdict == "pass", "verdict": verdict,
                                   "attempt": item["attempt"], "credit_id": _credit(outcome), "kind": "rdj"})
    ran = []
    for name in detail.get("ready") or []:
        attempt = control.next_attempt(view, name)
        outcome = services.normalize_outcome(services.call(
            "step_run", store, planned[name], _step_context(state, plan["sha256"], "execute", attempt, wave=number)))
        control.append(store, {"event": "step", "step": name, "attempt": attempt,
                               "spec_sha256": by_id[name]["spec_sha256"], "outcome": outcome})
        ran.append(name)
    identifier = control.append(store, {"event": "wave_ran", "number": number, "steps": ran,
                                        "reviews": [i["step"] for i, _ in reviews]})
    for name in ran:
        ledger_note(store, "judgment.fanout", "satisfied", {"record": identifier, "mechanism": "controller.step"},
                    rows=("JR04",), step=name)
    return {}


def _engagement_event(store, plan, event, identifier):
    """The wave review's engagement hook: a trigger this review found goes to the engagement monitor (E1 a decision
    record refused with no attempt left, E3 a comparison outside its tolerance or an anchor outside its regime, E4 a
    typed hold or a replan, E5 or E6 a decision recorded above its planned class). The monitor records and ratchets;
    a run without an engagement decision has no tier to raise, and nothing is sent."""
    try:
        from ravel.controller import engagement
    except ImportError:
        return None
    if not store.scan(engagement.DECISION):
        return None
    kind, name, found = event.get("event"), event.get("step"), {}
    if kind == "record":
        rank = {"R0": 0, "R1": 1, "R2": 2, "R3": 3}
        planned = next((s.get("class") for s in plan["steps"] if s["id"] == name), None)
        if event.get("class") in ("R2", "R3") and rank[event["class"]] > rank.get(planned, -1):
            found["new_consequence"] = event["class"]
    elif kind == "flag" and (event.get("replan_request") or {}).get("reason") == "discrepancy":
        found["outside_tolerance" if "tolerance" in str(event.get("text")) else "anchor_mismatch"] = True
    elif kind == "step_state" and event.get("status") == "held":
        found["status"] = "held"
    elif kind == "step_state" and event.get("status") == "violated":
        found.update(validation_failed=True, retry_exhausted=True)
    elif kind == "wave_review" and event.get("replan_request"):
        found["replan"] = True
    if not found:
        return None
    return engagement.observe(store, {**found, "step_id": name, "subject_sha256": None,
                                      "evidence": [{"kind": "judgment-control", "record": identifier, "event": kind}]})


def wave_review(state):
    store = _store(state)
    view = _view(store, state)
    plan = control.adopted_plan(view)
    number = state["decision"]["detail"]["number"]
    wave = next(e for e in reversed(control.events(store)) if e["event"] == "wave_ran" and e["number"] == number)
    rows_for = {"method_escalation": ("judgment.method_ladder", "C01"), "resource_unavailable":
                ("judgment.source_ladder", "E03"), "stage_recovery": ("judgment.recovery", "E12"),
                "adopt_default": ("judgment.default", "C08")}
    found = waves.review(store, _run(state), view, plan, _bound(state), number, wave)
    for event in found:
        identifier = control.append(store, event)
        _engagement_event(store, plan, event, identifier)
        if event["event"] == "record":
            evidence = {"record": event["judgment_id"], "sha256": event["record_sha256"],
                        "mechanism": "records.record_judgment"}
            ledger_note(store, "judgment.record", "satisfied", evidence, rows=("JR05",), step=event["step"])
            for trigger, (node, row) in rows_for.items():
                if trigger in event["triggers"] and row == "C08":
                    ledger_note(store, node, "satisfied", evidence, rows=(row,), step=event["step"])
        elif event["event"] == "step_state" and event["status"] == "violated" and any(
                e["event"] == "record_refused" and e["step"] == event["step"] for e in found):
            # The decision is refused with no attempt left: its record obligation is violated for good.
            evidence = {"reason": (event.get("reason") or "")[:1000], "record": identifier}
            ledger_note(store, "judgment.record", "violated", evidence, rows=("JR05",), step=event["step"])
            ledger_note(store, "judgment.protocol", "violated", evidence, rows=("E28",), step=event["step"])
    return {}


def _ask_subject(store, view, compiled, item):
    """The authority-service request for one question or R3 call, with its conservative default."""
    row = next(s for s in compiled["steps"] if s["id"] == item["step"])
    record = (view["steps"].get(row["id"]) or {}).get("record")
    plan_sha = (view["checkin1"].get(view["adopted"]) or {}).get("plan_sha256") or view["adopted"]
    pins = {"plan_sha256": plan_sha, "subject_sha256": item["subject_sha256"]}
    if row["kind"] == "ask":
        options = [{"id": o["id"], "text": o["description"]} for o in row.get("options") or []]
        view_ = _view_subject(store, pins=pins, summary=row["purpose"], items={"questions": [row["question"]]},
                              options=options, section=("question", [row["question"]]))
        default = row.get("default_option") if row.get("default") else None
        return row, "escalation", {"view": view_, **({"conservative_default": default} if default else {})}, record
    if record is not None:
        stored = records.by_digest(store, item["subject_sha256"]) or {}
        options = [{"id": o["id"], "text": o["description"]} for o in stored.get("options") or []]
        view_ = _view_subject(store, pins=pins, summary=f"R3 judgment of step {row['id']}: {stored.get('question')}",
                              options=options, flags=[{"kind": "decision", "text": f"recorded choice "
                                                       f"{stored.get('chosen')}: {stored.get('rationale')}"}],
                              section=("action", [stored.get("question") or row["purpose"]]))
        default = stored.get("default_option") if stored.get("default") else None
        return row, "r3_action", {"view": view_, **({"conservative_default": default} if default else {})}, record
    options = [{"id": control.AUTHORIZE, "text": "Run the step as planned."},
               {"id": "decline", "text": "Do not run it; its branch is held.", "effect": False}]
    view_ = _view_subject(store, pins=pins, summary=f"R3 step {row['id']}: {row['purpose']}", options=options,
                          section=("action", [row["purpose"]]))
    return row, "r3_action", {"view": view_, "conservative_default": "decline"}, record


def ask(state):
    store = _store(state)
    view = _view(store, state)
    compiled = control.adopted_plan(view)
    _, plan = _adopted_controller_plan(state, store, view)
    reading = _authority_reading(state, store)
    detail = state["decision"]["detail"]
    for item in detail.get("asks") or []:
        row, kind, subject, record = _ask_subject(store, view, compiled, item)
        _record_answer(store, row, item, record, _authority(store, kind, subject, plan=plan, reading=reading))
    for item in detail.get("wait") or []:
        row, kind, subject, record = _ask_subject(store, view, compiled, item)
        result = _authority(store, kind, subject, plan=plan, reading=reading, since=item.get("since"), wait=True)
        if result["state"] != "pending":
            _record_answer(store, row, item, record, result)
            break
    for item in detail.get("expired") or []:
        row, kind, subject, record = _ask_subject(store, view, compiled, item)
        result = _authority(store, kind, subject, plan=plan, reading=reading, since=item.get("since"))
        if result["state"] == "pending":
            result = {**result, "state": "held", "detail": "the wait bound passed with no answer and no recorded "
                                                           "conservative default within the delegation"}
        _record_answer(store, row, item, record, result)
    return {}


def _record_answer(store, row, item, record, result):
    identifier = control.append(store, {"event": "authority", "step": row["id"],
                                        "subject_sha256": item["subject_sha256"],
                                        **{k: result.get(k) for k in ("state", "record_id", "label", "answer", "since",
                                                                       "wait_bound", "detail")}})
    if result["state"] == "pending":
        return
    if result["state"] in ("defaulted", "held") or row["kind"] == "ask":
        ledger_note(store, "judgment.ask", "satisfied", {"record": identifier, "authority": result.get("record_id"),
                                                         "mechanism": "authority." + result["state"]},
                    rows=("JR08",), step=row["id"])
    if result["state"] == "defaulted" and record is not None:
        kept = result.get("answer") == record.get("chosen")
        records.record_outcome(store, record["judgment_id"], "confirmed" if kept else "overturned",
                               {"default": result.get("answer"), "label": result.get("label"),
                                "authority": result.get("record_id")})
        if not kept:
            control.append(store, {"event": "flag", "step": row["id"],
                                   "text": f"the conservative default {result.get('answer')} overturned the recorded "
                                           f"choice {record.get('chosen')} of step {row['id']}; its branch is held"})
    if row["kind"] == "ask" and result["state"] in control.GRANTED and any(
            name.startswith("B") for name in row.get("resolves") or []) and result.get("answer") not in (
            "keep_held", "keep_open", None) and result["state"] != "defaulted":
        control.append(store, {"event": "replan_requested",
                               "request": {"reason": "boundary_answered", "step": row["id"],
                                           "answer": result.get("answer")}})


def deviation(state):
    store = _store(state)
    view = _view(store, state)
    detail = state["decision"]["detail"]
    sha = detail["compiled_sha256"]
    compiled = view["compiled_history"][sha]
    plan = _controller_plan(state, store, view, compiled)
    old_plan = (view["checkin1"].get(view["adopted"]) or {}).get("plan_sha256") or view["adopted"]
    changes = detail.get("changes") or []
    subject = {"view": _view_subject(store, pins={"approve_plan": _approval_id(view) or "missing",
                                                  "plan_sha256": plan["sha256"]},
                                     summary="A scope-changing replan of the judgment route"),
               "change": {"parameter": "plan", "from": old_plan, "to": plan["sha256"],
                          "why": (view["replan_request"] or {}).get("reason") or "replan",
                          "touches": sorted({c["deliverable"] for c in changes}) or ["plan"],
                          "direction": "scope"}}
    subject["view"]["sections"].append({"id": "change", "title": "Change",
                                        "lines": [json.dumps(subject["change"], sort_keys=True)]})
    previous = (view["deviation"].get(sha) or {}).get("authority") or {}
    result = _authority(store, "deviation", subject, plan=plan, reading=_authority_reading(state, store),
                        since=previous.get("since"), wait=bool(detail.get("wait")))
    control.append(store, {"event": "deviation", "compiled_sha256": sha, "plan_sha256": plan["sha256"],
                           "authority": {**result, "subject_sha256": sha}})
    return {}


def kill_the_result(state):
    store = _store(state)
    request = _request(state, store)
    inputs = _inputs(state, store, request)
    view = _view(store, state)
    result = control.draft(view)
    sha = result["sha256"]
    number = view["kill_rounds"].get(sha, 0) + 1
    producers = sorted({(row.get("role") or "") for row in control.adopted_plan(view)["steps"]} - {""})
    pin = _context_file(state, f"draft-{number}", {"draft": result, "plan_sha256": view["adopted"]})
    step = steps.attack_step(number, inputs=_base_inputs(inputs) + [pin],
                             subject={"kind": "draft", "sha256": sha, "plan_sha256": view["adopted"]},
                             exclude_roles=[planning.policy()["roles"]["planner"]] + producers)
    step["id"] = f"judgment-attack-{sha[:12]}-{number}"
    outcome = _run_planning_steps(store, state, request, "kill-the-result", [step])[step["id"]]
    event = {"event": "attacks", "draft_sha256": sha, "status": outcome["status"], "attacks_sha256": None,
             "problems": [], "record": None}
    if outcome["status"] == "adopted":
        document, where = services.read_output(_run(state), outcome, path=step["outputs"][0]["path"],
                                               step_id=step["id"])
        if document is None:
            event.update(status="no_output", problems=[where])
        else:
            problems = protocols.check_attacks(document, plan_sha256=view["adopted"], draft_sha256=sha)
            if problems:
                event.update(status="invalid", problems=problems)
            else:
                record = store.append(control.ATTACKS_KIND, {"schema_version": 1, "kind": control.ATTACKS_KIND,
                                                             "draft_sha256": sha, "attacks": document["attacks"]})
                event.update(status="valid", attacks_sha256=digest(document), record=record)
    else:
        event["problems"] = [outcome.get("reason") or f"the attack step ended {outcome['status']}"]
    identifier = control.append(store, event)
    if event["status"] != "valid":
        ledger_note(store, "judgment.kill_the_result", "violated",
                    {"record": identifier, "reason": "; ".join(event["problems"])[:1000]}, rows=("JR09",))
    return {}


def final_review(state):
    store = _store(state)
    request = _request(state, store)
    inputs = _inputs(state, store, request)
    view = _view(store, state)
    result = control.draft(view)
    sha = result["sha256"]
    attacks = services.record(store, control.ATTACKS_KIND, view["attacks"][sha]["record"])["attacks"]
    number = view["final_rounds"].get(sha, 0) + 1
    must = [{"id": f"JR09:{a['axis']}", "row": "JR09",
             "text": f"Attack on {a['axis']}: {a['attack']} Test: {a['test']} Recorded outcome: {a['outcome']}."}
            for a in attacks]
    pin = _context_file(state, f"final-{number}", {"draft": result, "attacks": attacks,
                                                    "flags": [f.get("text") for f in view["flags"]]})
    seats = [steps.review_step(f"judgment-final-{seat}-{sha[:12]}-{number}", seats=[seat],
                               subject={"kind": "draft", "sha256": sha, "plan_sha256": view["adopted"]},
                               must_check=must, inputs=_base_inputs(inputs) + [pin], obligations=["JR09", "D04"],
                               purpose="Fresh final review of the drafted result with the three attacks as must_check "
                                       "items.") for seat in steps.final_review_roles()]
    found = _run_planning_steps(store, state, request, "final-review", seats)
    credited = all(found[s["id"]]["status"] == "adopted" and found[s["id"]]["credited"] for s in seats)
    verdicts = [services.normalize_verdict(found[s["id"]]["verdict"]) for s in seats]
    verdict = "pass" if verdicts and all(v == "pass" for v in verdicts) else (
        "revise" if "revise" in verdicts else "fail")
    findings = [f for s in seats for f in _findings(state, found[s["id"]], s["id"])]
    identifier = control.append(store, {"event": "final_review", "draft_sha256": sha,
                                        "credited": credited, "verdict": verdict if credited else "fail",
                                        "findings": findings[:50],
                                        "credit": [_credit(found[s["id"]]) for s in seats]})
    if credited:
        ledger_note(store, "judgment.kill_the_result", "satisfied",
                    {"record": identifier, "credit": _credit(found[seats[0]["id"]]) or identifier}, rows=("JR09",))
    return {}


def checkin3(state):
    store = _store(state)
    view = _view(store, state)
    _, plan = _adopted_controller_plan(state, store, view)
    detail = state["decision"]["detail"]
    sha = detail["draft_sha256"]
    result = control.draft(view)
    review = view["final_review"].get(sha) or {}
    flags = [{"kind": "risk", "text": str(f.get("text"))} for f in view["flags"] if f.get("text")]
    flags += [{"kind": "decision", "text": f"R1 decision of {name} is reported here"}
              for name, row in sorted(view["steps"].items()) if (row.get("record") or {}).get("class") == "R1"]
    subject = {"view": _view_subject(
        store, pins={"approve_plan": _approval_id(view) or "missing", "draft_sha256": sha},
        summary=f"Judgment-route result {sha[:12]} (final review {review.get('verdict')})",
        items={"deliverables": plan["deliverables"]}, flags=flags,
        section=("results", [f"{d['id']}: {d['status']}" for d in result["deliverables"]]))}
    previous = (view["checkin3"].get(sha) or {}).get("authority") or {}
    found = _authority(store, "final", subject, plan=plan, reading=_authority_reading(state, store),
                       since=previous.get("since"), wait=bool(detail.get("wait")))
    control.append(store, {"event": "checkin3", "draft_sha256": sha, "authority": {**found, "subject_sha256": sha}})
    return {}


def deliver(state):
    store = _store(state)
    view = _view(store, state)
    _, plan = _adopted_controller_plan(state, store, view)
    receipt = services.call("sink_deliver", store, plan)
    control.append(store, {"event": "delivered", "plan_sha256": plan["sha256"], "receipt": deepcopy(receipt)})
    return {"results": {"judgment": {"outcome": "delivered", "plan_sha256": plan["sha256"]}}}


def _ending_reason(state):
    """Why the run ends: a bound of the graph, a node failure, or the phase the hub decided."""
    decision, status = state.get("decision") or {}, state.get("status") or {}
    if status.get("phase") == "guard" and status.get("verdict") not in (None, "go"):
        return f"the judgment graph's {status['verdict']} bound was reached", {}
    if status.get("phase") == "decision":
        return f"a judgment-route node failed ({status.get('reason')})", {"subsystem": status.get("subsystem")}
    return decision.get("reason") or "bounded ending", decision.get("detail") or {}


def bounded_end(state):
    reason, detail = _ending_reason(state)
    if purpose(state) != "route":
        # The controller graph owns the ending of a planning call: it ends the run qualified.
        return {"status": {"phase": "hold", "terminal": "hold", "reason": "judgment_planning_held: " + reason,
                           "would_make_possible": "the controller ends the run with a qualified delivery"}}
    store = _store(state)
    unmet = services.call("ledger_gate", store, "deliver[qualified]") or []
    receipt = services.call("sink_bounded_end", store, "judgment route: " + reason)
    identifier = control.append(store, {"event": "bounded_end", "reason": reason, "detail": deepcopy(detail),
                                        "unmet": deepcopy(unmet)[:50], "receipt": deepcopy(receipt)})
    if "replan" in reason:
        ledger_note(store, "judgment.replan", "satisfied", {"record": identifier, "mechanism": "replan bound"},
                    rows=("JR07",))
    return {"results": {"judgment": {"outcome": "qualified", "reason": reason}}}


def _failure_router(state, failure):
    if purpose(state) != "route" or failure.get("node") in ("bounded_end", "deliver", "start"):
        return "end"
    return "bounded_end"


def build(ctx):
    from langgraph.graph import END, START, StateGraph
    builder = StateGraph(State)

    def add(name, node):
        nodes.add(builder, name, node, graph_id=GRAPH_ID)

    add("decision_turn", nodes.decision_turn(GRAPH_ID, _failure_router, {"bounded_end": "bounded_end"}))
    add("reconcile", nodes.reconcile_node())
    add("hold", nodes.hold("judgment_hold"))
    add("done", nodes.hold("judgment_route_ended", "a new request starts a new run"))
    add("paused", nodes.hold("judgment_paused", "the operator resumes the run; a new invocation continues from the store"))
    add("planning_held", nodes.Node("hold", planning_held, then=nodes.END))
    add("start", nodes.Node("effect", _guarded(start)))
    add("guard", nodes.guard(lambda s: "exhausted" if s.get("passes", 0) >= MAX_PASSES else "go",
                             {"go": "advance", "exhausted": "bounded_end", "drain": "bounded_end",
                              "escalate": "bounded_end"}))
    add("advance", nodes.Node("guard", _guarded(advance)))
    bodies = {"frame": ("subgraph", frame), "frame_review": ("subgraph", frame_review),
              "decompose": ("subgraph", decompose), "classify_calls": ("effect", classify_calls),
              "plan_review": ("subgraph", plan_review), "checkin1": ("effect", checkin1), "adopt": ("effect", adopt),
              "execute": ("subgraph", execute), "wave_review": ("effect", wave_review), "ask": ("effect", ask),
              "replan": ("subgraph", replan), "deviation": ("effect", deviation),
              "kill_the_result": ("subgraph", kill_the_result), "final_review": ("subgraph", final_review),
              "checkin3": ("effect", checkin3)}
    for name in PHASE_NODES:
        kind, function = bodies[name]
        add(name, nodes.Node(kind, _guarded(function)))
        builder.add_edge(name, "guard")
    for gate, name in GATES.items():
        add(name, _gate_node(gate))
        nodes.connect(builder, name, nodes.gate_route(gate, passed="gate_passed", refused="gate_refused"))
    add("gate_passed", nodes.Node("effect", _guarded(gate_passed)))
    add("gate_refused", nodes.Node("effect", _guarded(gate_refused)))
    builder.add_edge("gate_passed", "guard")
    builder.add_edge("gate_refused", "guard")
    add("return_plan", nodes.Node("effect", _guarded(return_plan)))
    add("deliver", nodes.Node("effect", _guarded(deliver)))
    add("bounded_end", nodes.Node("effect", _guarded(bounded_end)))
    for name in ("return_plan", "deliver", "bounded_end"):
        builder.add_edge(name, END)
    paths = {name: name for name in PHASE_NODES}
    paths.update({name: name for name in GATES.values()})
    paths.update({name: name for name in ("return_plan", "planning_held", "deliver", "bounded_end", "done", "paused")})
    nodes.connect(builder, "advance", nodes.route(_route, paths))
    builder.add_edge(START, "start")
    builder.add_edge("start", "guard")
    return builder


def instance(run_id: str) -> dict:
    if type(run_id) is not str or not run_id:
        raise ValueError("judgment.plan instance requires a run id")
    return {"run_id": run_id}
