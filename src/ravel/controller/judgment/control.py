"""Event-sourced control of the judgment route.

Every node of ``judgment.plan`` appends typed events to the run store (kind
``judgment-event``); ``fold`` turns the events into a view and ``next_phase`` decides,
by code, what the route does next. Graph state carries only the phase and digests, so
a crash, a new attempt or a resumed run continues from the store, never from model
memory or graph state alone. Routing is code: a worker's output is data that a check
accepts or refuses.

Two purposes share the events. ``plan`` and ``replan`` answer the controller graph
(``controller.run``), which runs CHECK-IN 1, the waves, the final review and delivery
itself: ``next_planning`` frames, decomposes, classifies and reviews the R2+ calls, then
returns a plan. ``route`` drives the whole judgment route of CONTROLLER-SPEC 6.2 in this
graph (``next_phase``), for a controller that delegates the route.

Bounds (``data/judgment/policy.json``, operator-configurable where the frozen mode
names them): frame rounds, plan rounds, plan-review rounds, replans, kill rounds,
final-review rounds, step attempts and waves. Reaching a bound ends the run in a
qualified delivery; there is no refusal of the request for lack of a path.
"""
from __future__ import annotations

from copy import deepcopy

from . import classes, planning
from .records import digest
from .services import records as store_records

EVENT_KIND = "judgment-event"
FRAME_KIND = "judgment-frame"
PLAN_KIND = "judgment-plan"
COMPILED_KIND = "judgment-compiled-plan"
ATTACKS_KIND = "judgment-attacks"
REVIEW_ATTEMPTS = 2
PHASES = ("frame", "frame_review", "decompose", "classify_calls", "plan_review", "checkin1", "gate", "adopt",
          "execute", "wave_review", "ask", "replan", "deviation", "kill_the_result", "final_review", "checkin3",
          "deliver", "bounded_end", "hold", "return_plan", "planning_held")
PURPOSES = ("plan", "replan", "route")
# The only terminal outcomes of the judgment route: a delivery, a qualified delivery, or a typed
# infrastructure hold. No status means "refused for lack of a path" (JR01).
TERMINALS = ("delivered", "qualified", "hold")
# Check-ins and deviations offer no conservative default: only a granted answer is authority.
GRANTED = ("granted",)
# A final check-in authorizes no effect: only its authenticated current disposition accepts the result.
ACCEPTED = ("accepted",)
# The option an effectful R3 step's authority request offers to let the effect happen.
AUTHORIZE = "authorize"


# ---- store ----------------------------------------------------------------------------------

def events(store) -> list[dict]:
    rows = [{**body, "_id": identifier} for identifier, body in store_records(store, EVENT_KIND)]
    return sorted(rows, key=lambda row: row.get("sequence", 0))


def append(store, event: dict) -> str:
    if event.get("event") is None:
        raise ValueError("a judgment event needs its event name")
    record = {"schema_version": 1, "kind": EVENT_KIND, "sequence": len(store.scan(EVENT_KIND)) + 1,
              **deepcopy(event)}
    return store.append(EVENT_KIND, record)


def bounds(mode: dict | None) -> dict:
    """The policy bounds with the frozen mode's operator values where it sets them."""
    policy = planning.policy()
    result = dict(policy["bounds"])
    declared = (mode or {}).get("bounds") or {}
    for ours, theirs in policy["operator_bounds"].items():
        value = declared.get(theirs)
        if type(value) is int and value >= 0:
            result[ours] = value
    return result


# ---- the view -------------------------------------------------------------------------------

def _empty():
    return {"started": None, "ended": None, "frame_rounds": 0, "frame": None, "frame_accepted": None,
            "frame_review_attempts": {}, "plan_rounds": 0, "plan": None, "plan_problems": [], "compiled": None,
            "compiled_history": {}, "plan_review": {}, "checkin1": {}, "gates": {}, "adopted": None, "steps": {},
            "waves": 0, "waves_reviewed": 0, "replans": 0, "replan_request": None, "deviation": {},
            "attacks": {}, "kill_rounds": {}, "final_review": {}, "final_rounds": {}, "checkin3": {},
            "flags": [], "failures": [], "end_request": None, "plans_for": {}, "returned": {}, "replanned": []}


def _step(view, name):
    return view["steps"].setdefault(name, {"status": "pending", "attempts": 0, "outcome": None, "record": None,
                                           "review": None, "authority": None, "reason": None})


def fold(rows: list[dict], bound: dict) -> dict:
    """The judgment view after every event, in order."""
    view = _empty()
    for row in rows:
        _apply(view, row, bound)
    return view


def _apply(view, row, bound):
    name = row["event"]
    if name == "started":
        view["started"] = row
    elif name == "frame":
        view["frame_rounds"] = max(view["frame_rounds"], row["round"])
        view["frame"] = {**row, "review": None}
    elif name == "frame_review":
        frame = view["frame"]
        if frame is None or frame.get("frame_sha256") != row["frame_sha256"]:
            return
        attempts = view["frame_review_attempts"]
        attempts[row["frame_sha256"]] = attempts.get(row["frame_sha256"], 0) + 1
        frame["review"] = row
        # After the last round a frame the critic asked to revise goes on with its findings; a frame
        # the critic failed never does.
        if row["credited"] and (row["verdict"] == "pass" or (
                row["verdict"] == "revise" and view["frame_rounds"] >= bound["frame_rounds"])):
            view["frame_accepted"] = {"frame_sha256": row["frame_sha256"], "record": frame["frame_record"],
                                      "findings": [] if row["verdict"] == "pass" else list(row["findings"])}
    elif name == "plan":
        view["plan_rounds"] = max(view["plan_rounds"], row.get("round", 0))
        if row.get("revision") is not None:
            view["plans_for"].setdefault(row["revision"], []).append(row)
        if row["status"] == "written":
            view["plan"] = row
            view["plan_problems"] = []
            if row.get("source") == "replan" and row.get("revision") not in view["replanned"]:
                view["replanned"].append(row.get("revision"))
        else:
            view["plan_problems"] = list(row.get("problems") or [])
    elif name == "returned":
        view["returned"][row["revision"]] = row
    elif name == "classified":
        view["compiled"] = row
        view["compiled_history"][row["compiled_sha256"]] = row
    elif name == "plan_review":
        previous = view["plan_review"].get(row["compiled_sha256"])
        attempts = (previous or {}).get("attempts", 0) + 1
        view["plan_review"][row["compiled_sha256"]] = {**row, "attempts": attempts}
        for step_id, review in (row.get("rdj") or {}).items():
            _step(view, step_id)["review"] = review
    elif name == "checkin1":
        view["checkin1"][row["compiled_sha256"]] = row
    elif name == "gate":
        view["gates"][f"{row['gate']}:{row['subject_sha256']}"] = row
        if row["gate"] == "approve_plan" and row["passed"]:
            _adopt(view, row["subject_sha256"])
        if row["gate"] == "deviation" and row["passed"]:
            _adopt(view, row["subject_sha256"])
            view["replan_request"] = None
    elif name == "adopted":
        _adopt(view, row["compiled_sha256"])
        view["replan_request"] = None
    elif name == "step":
        state = _step(view, row["step"])
        state["attempts"] = max(state["attempts"], row["attempt"] - state.get("attempt_base", 0))
        state["last_attempt"] = max(state.get("last_attempt", 0), row["attempt"])
        state["outcome"] = row["outcome"]
        state["status"] = {"adopted": "adopted", "held": "held", "stopped": "stopped",
                           "exhausted": "exhausted"}.get(row["outcome"]["status"], "failed")
        state["reason"] = row["outcome"].get("reason")
        state["spec_sha256"] = row.get("spec_sha256")
    elif name == "step_state":
        state = _step(view, row["step"])
        state["status"] = row["status"]
        state["reason"] = row.get("reason")
        if row["status"] == "failed" and row["step"] not in view["failures"]:
            view["failures"].append(row["step"])
    elif name == "record":
        state = _step(view, row["step"])
        state["record"] = row
        state["status"] = "recorded"
    elif name == "record_refused":
        state = _step(view, row["step"])
        state["status"] = "violated"
        state["reason"] = "; ".join(row["problems"])[:2000]
        state["record"] = None
    elif name == "review":
        _step(view, row["step"])["review"] = row
    elif name == "authority":
        _step(view, row["step"])["authority"] = row
    elif name == "wave_ran":
        view["waves"] = max(view["waves"], row["number"])
    elif name == "wave_review":
        view["waves_reviewed"] = max(view["waves_reviewed"], row["number"])
        if row.get("replan_request") and view["replan_request"] is None:
            view["replan_request"] = row["replan_request"]
        if row.get("end") and view["end_request"] is None:
            view["end_request"] = row["end"]
    elif name == "replan":
        view["replans"] = max(view["replans"], row["number"])
        if row["status"] == "refused" and view["replans"] >= bound["replans"]:
            view["replan_request"] = {**(view["replan_request"] or {}), "exhausted": True}
    elif name == "deviation":
        view["deviation"][row["compiled_sha256"]] = row
    elif name == "attacks":
        view["attacks"][row["draft_sha256"]] = row
        view["kill_rounds"][row["draft_sha256"]] = view["kill_rounds"].get(row["draft_sha256"], 0) + 1
    elif name == "final_review":
        view["final_review"][row["draft_sha256"]] = row
        view["final_rounds"][row["draft_sha256"]] = view["final_rounds"].get(row["draft_sha256"], 0) + 1
        if row["credited"] and row["verdict"] != "pass" and view["replan_request"] is None:
            view["replan_request"] = {"reason": "final_review_findings", "findings": list(row.get("findings") or []),
                                      "draft_sha256": row["draft_sha256"]}
    elif name == "checkin3":
        view["checkin3"][row["draft_sha256"]] = row
    elif name == "flag":
        view["flags"].append(row)
    elif name == "replan_requested":
        if view["replan_request"] is None:
            view["replan_request"] = row["request"]
    elif name in ("delivered", "bounded_end"):
        view["ended"] = row


def _adopt(view, compiled_sha):
    """Adopt a compiled plan: unchanged steps keep their state; a changed or new step starts
    pending and keeps only a review or authority bound to its new spec digest."""
    previous = view["compiled_history"].get(view["adopted"]) if view["adopted"] else None
    current = view["compiled_history"].get(compiled_sha)
    view["adopted"] = compiled_sha
    if current is None:
        return
    old = {s["id"]: s["spec_sha256"] for s in previous["steps"]} if previous else {}
    kept = {}
    for step in current["steps"]:
        state = view["steps"].get(step["id"])
        if state is None:
            continue
        if previous is None or old.get(step["id"]) == step["spec_sha256"]:
            kept[step["id"]] = state
            continue
        # A changed step starts its tries again; its attempt numbers keep counting, so a governed
        # step attempt is never reused for different bytes.
        fresh = {"status": "pending", "attempts": 0, "outcome": None, "record": None, "review": None,
                 "authority": None, "reason": None, "attempt_base": state.get("last_attempt", 0),
                 "last_attempt": state.get("last_attempt", 0)}
        for key in ("review", "authority"):
            item = state.get(key)
            if item is not None and item.get("subject_sha256") == step["spec_sha256"]:
                fresh[key] = item
        kept[step["id"]] = fresh
    view["steps"] = kept
    view["failures"] = [name for name in view["failures"] if name in kept and kept[name]["status"] == "failed"]


# ---- step status over the adopted plan --------------------------------------------------------

def answer(authority, subject, chosen) -> str | None:
    """``granted``, ``held`` or None (no final answer yet) of an R3 authority answer on ``subject``.

    A conservative default taken after the wait bound lets the effect proceed only when it is
    the option ``chosen`` itself (the recorded choice, or ``authorize`` for an effectful step);
    a default that differs overturns that choice, and its branch is held.
    """
    if authority is None or authority.get("subject_sha256") != subject:
        return None
    state = authority["state"]
    if state == "granted":
        return "granted"
    if state == "defaulted":
        return "granted" if chosen is not None and authority.get("answer") == chosen else "held"
    if state in ("declined", "held"):
        return "held"
    return None


def status(step: dict, view: dict, bound: dict) -> str:
    """The derived status of one adopted step.

    pending or retry (may run), a wait (awaiting_review, awaiting_authority, awaiting_gate,
    awaiting_record), closed, or a branch stop (held, violated, failed, stopped, exhausted).
    """
    state = view["steps"].get(step["id"])
    if step["kind"] == "ask":
        authority = (state or {}).get("authority")
        if authority is None or authority.get("subject_sha256") != step["spec_sha256"]:
            return "pending"
        return {"granted": "closed", "defaulted": "closed", "declined": "held", "held": "held"}.get(
            authority["state"], "awaiting_authority")
    if state is None:
        return "pending"
    base = state["status"]
    if base in ("held", "violated", "failed", "stopped", "exhausted", "closed", "retry"):
        return base
    if step["kind"] != "decide":
        if step["class"] == "R3" and answer(state.get("authority"), step["spec_sha256"], AUTHORIZE) == "held":
            return "held"
        return "awaiting_review" if base == "adopted" else base
    record = state.get("record")
    if record is None:
        return "awaiting_record" if base == "adopted" else "pending"
    cls, subject = record["class"], record["record_sha256"]
    if classes.RANK[cls] >= 2:
        review = state.get("review")
        if review is None or review.get("subject_sha256") != subject or not review.get("credited"):
            if review is not None and review.get("subject_sha256") == subject and \
                    review.get("attempt", 1) >= bound["step_attempts"]:
                return "held"
            return "awaiting_review"
    if cls == "R3":
        found = answer(state.get("authority"), subject, record.get("chosen"))
        if found == "held":
            return "held"
        if found != "granted":
            return "awaiting_authority"
    if "stage_recovery" in (record.get("triggers") or []):
        gate = view["gates"].get(f"failed_stage_feedback:{subject}")
        if gate is None:
            return "awaiting_gate"
        if not gate["passed"]:
            return "held"
    return "closed"


def effect_ready(step: dict, view: dict) -> tuple[bool, str | None]:
    """Whether an effectful step's requirement holds before its effect, and what is missing."""
    cls = step["class"]
    state = view["steps"].get(step["id"]) or {}
    if classes.RANK[cls] >= 2:
        review = state.get("review")
        if review is None or review.get("subject_sha256") != step["spec_sha256"] or not review.get("credited"):
            return False, "rdj_review"
    if cls == "R3" and answer(state.get("authority"), step["spec_sha256"], AUTHORIZE) != "granted":
        return False, "authority"
    return True, None


def next_attempt(view, step_id) -> int:
    """The governed step attempt number of a step's next run (monotonic across plan revisions)."""
    state = view["steps"].get(step_id) or {}
    return max(state.get("last_attempt", 0), state.get("attempt_base", 0) + state.get("attempts", 0)) + 1


def adopted_plan(view) -> dict | None:
    return view["compiled_history"].get(view["adopted"]) if view["adopted"] else None


def schedule(view: dict, bound: dict) -> dict:
    """What can happen now in the adopted plan: ready steps, reviews, asks, gates, waits."""
    plan = adopted_plan(view)
    result = {"ready": [], "reviews": [], "asks": [], "gates": [], "waiting": [], "closed": [], "stopped": [],
              "blocked": []}
    if plan is None:
        return result
    statuses = {s["id"]: status(s, view, bound) for s in plan["steps"]}
    for step in plan["steps"]:
        name, current = step["id"], statuses[step["id"]]
        state = view["steps"].get(name) or {}
        if current == "closed":
            result["closed"].append(name)
            continue
        if current in ("held", "failed", "stopped", "exhausted") or (current == "violated"):
            result["stopped"].append({"step": name, "status": current, "reason": state.get("reason")})
            continue
        if current == "awaiting_review":
            if step["kind"] == "decide":
                review = state.get("review") or {}
                subject = state["record"]["record_sha256"]
                tried = review.get("attempt", 0) if review.get("subject_sha256") == subject else 0
                result["reviews"].append({"step": name, "subject": "record", "subject_sha256": subject,
                                          "attempt": tried + 1})
            else:
                result["blocked"].append({"step": name, "reason": "adopted output awaits the wave review"})
            continue
        if current == "awaiting_record":
            result["blocked"].append({"step": name, "reason": "awaiting the wave review of its record"})
            continue
        if current == "awaiting_gate":
            result["gates"].append({"gate": "failed_stage_feedback", "step": name,
                                    "subject_sha256": state["record"]["record_sha256"]})
            continue
        if current == "awaiting_authority":
            subject = state["record"]["record_sha256"] if step["kind"] == "decide" else step["spec_sha256"]
            _authority_item(result, step, state, subject)
            continue
        parents = [statuses.get(p) for p in step["depends_on"]]
        if not all(p == "closed" for p in parents):
            if any(p in ("held", "failed", "stopped", "exhausted", "violated") for p in parents):
                result["blocked"].append({"step": name, "reason": "a parent branch stopped"})
            else:
                result["blocked"].append({"step": name, "reason": "parents not closed"})
            continue
        if step["kind"] == "ask":
            _authority_item(result, step, state, step["spec_sha256"])
            continue
        if current == "retry" or current == "pending":
            if state.get("attempts", 0) >= bound["step_attempts"]:
                result["stopped"].append({"step": name, "status": "held", "reason": "step attempts exhausted"})
                continue
            if step["kind"] != "decide":
                ok, missing = effect_ready(step, view)
                if not ok and missing == "rdj_review":
                    review = state.get("review") or {}
                    tried = review.get("attempt", 0) if review.get("subject_sha256") == step["spec_sha256"] else 0
                    if tried >= bound["step_attempts"]:
                        result["stopped"].append({"step": name, "status": "held",
                                                  "reason": "the RDJ review of this step was not credited"})
                    else:
                        result["reviews"].append({"step": name, "subject": "spec",
                                                  "subject_sha256": step["spec_sha256"], "attempt": tried + 1})
                    continue
                if not ok and missing == "authority":
                    _authority_item(result, step, state, step["spec_sha256"])
                    continue
            result["ready"].append(name)
    return result


def _authority_item(result, step, state, subject):
    authority = state.get("authority")
    if authority is not None and authority.get("subject_sha256") == subject and authority["state"] == "pending":
        result["waiting"].append({"step": step["id"], "subject_sha256": subject, "since": authority.get("since"),
                                  "wait_bound": authority.get("wait_bound")})
    else:
        result["asks"].append({"step": step["id"], "subject_sha256": subject})


# ---- the draft --------------------------------------------------------------------------------

def draft(view: dict) -> dict:
    """The drafted result: every planned deliverable's adopted outputs, and every held one."""
    plan = adopted_plan(view)
    rows, missing = [], []
    for deliverable in (plan or {}).get("deliverables") or []:
        if deliverable["status"] == "held":
            rows.append({"id": deliverable["id"], "status": "held", "held_reason": deliverable.get("held_reason"),
                         "outputs": []})
            continue
        outputs = []
        for target in deliverable["outputs"]:
            outcome = (view["steps"].get(target["step"]) or {}).get("outcome") or {}
            found = [o for o in outcome.get("outputs") or [] if o["path"] == target["path"]
                     or o["path"].endswith("/" + target["path"])]
            if not found:
                missing.append(f"{deliverable['id']}: {target['step']}:{target['path']}")
                continue
            outputs.append({"step": target["step"], "path": found[-1]["path"], "sha256": found[-1].get("sha256")})
        rows.append({"id": deliverable["id"], "status": "planned", "outputs": outputs})
    body = {"plan_sha256": view["adopted"], "deliverables": rows}
    return {**body, "sha256": digest(body), "missing": missing}


# ---- the next phase ---------------------------------------------------------------------------

def _end(reason, **detail):
    return {"phase": "bounded_end", "reason": reason, "detail": detail}


def _go(phase, reason, **detail):
    return {"phase": phase, "reason": reason, "detail": detail}


def next_phase(view: dict, bound: dict, *, now: float, wait_bound=None) -> dict:
    """The next phase of the judgment route, decided by code from the view."""
    if view["ended"] is not None:
        return _go("hold", "judgment route already ended", ended=view["ended"]["event"])
    if view["end_request"] is not None:
        return _end(view["end_request"])
    found = _frame_phase(view, bound)
    if found is not None:
        return found
    found = _plan_phase(view, bound, now=now, wait_bound=wait_bound)
    if found is not None:
        return found
    return _execution_phase(view, bound, now=now, wait_bound=wait_bound)


def _frame_phase(view, bound):
    if view["frame_accepted"] is not None:
        return None
    frame = view["frame"]
    if frame is not None and frame["status"] == "written":
        review = frame["review"]
        attempts = view["frame_review_attempts"].get(frame["frame_sha256"], 0)
        if review is None:
            return _go("frame_review", "the frame awaits its independent review", round=frame["round"])
        if not review["credited"]:
            if attempts < REVIEW_ATTEMPTS:
                return _go("frame_review", "the frame review was not credited; one more attempt",
                           round=frame["round"])
            return _end("the frame review could not be credited", attempts=attempts)
    if view["frame_rounds"] < bound["frame_rounds"]:
        return _go("frame", "the request needs a question frame", round=view["frame_rounds"] + 1)
    return _end("frame rounds exhausted without an acceptable frame", rounds=view["frame_rounds"])


def _authority_wait(authority, now, wait_bound):
    bound = authority.get("wait_bound") if authority.get("wait_bound") is not None else wait_bound
    since = authority.get("since")
    if type(bound) not in (int, float) or type(since) not in (int, float):
        return False
    return now < since + bound


def _plan_phase(view, bound, *, now, wait_bound):
    plan = view["plan"]
    revision_open = view["adopted"] is None
    if view["adopted"] is not None and view["replan_request"] is None:
        compiled = view["compiled"]
        if compiled is None or compiled["compiled_sha256"] == view["adopted"]:
            return None
    if plan is None or plan.get("frame_sha256") != view["frame_accepted"]["frame_sha256"]:
        if revision_open:
            if view["plan_rounds"] < bound["plan_rounds"]:
                return _go("decompose", "the frame needs a decomposition", round=view["plan_rounds"] + 1,
                           problems=view["plan_problems"])
            return _end("plan rounds exhausted without an acceptable plan", rounds=view["plan_rounds"],
                        problems=view["plan_problems"])
        return None
    compiled = view["compiled"]
    if compiled is None or compiled["planner_plan_sha256"] != plan["plan_sha256"]:
        return _go("classify_calls", "the plan's calls need their consequence classes", plan_sha256=plan["plan_sha256"])
    sha = compiled["compiled_sha256"]
    if sha == view["adopted"]:
        return None
    review = view["plan_review"].get(sha)
    if review is None or (not review["credited"] and review["attempts"] < bound["plan_review_rounds"]):
        return _go("plan_review", "the plan awaits the plan critic and its RDJ cases", compiled_sha256=sha)
    if not review["credited"]:
        return _end("the plan review could not be credited", compiled_sha256=sha)
    if review["verdict"] != "pass" and revision_open and view["plan_rounds"] < bound["plan_rounds"]:
        return _go("decompose", "the plan critic asked for a revision", round=view["plan_rounds"] + 1,
                   problems=list(review.get("findings") or []))
    if review["verdict"] != "pass" and not revision_open:
        return _refused_replan(view, bound, "the plan critic did not pass the replan")
    if compiled["revision"] == 0:
        checkin = view["checkin1"].get(sha)
        if checkin is None:
            return _go("checkin1", "CHECK-IN 1 has no authority record for this plan", compiled_sha256=sha)
        authority = checkin["authority"]
        if authority["state"] == "pending":
            if _authority_wait(authority, now, wait_bound):
                return _go("checkin1", "CHECK-IN 1 is waiting for an answer", compiled_sha256=sha, wait=True)
            return _end("CHECK-IN 1 was not answered within the wait bound", compiled_sha256=sha)
        if authority["state"] not in GRANTED:
            if view["plan_rounds"] < bound["plan_rounds"]:
                return _go("decompose", "CHECK-IN 1 declined the plan", round=view["plan_rounds"] + 1,
                           problems=[authority.get("detail") or "CHECK-IN 1 declined the plan"])
            return _end("CHECK-IN 1 declined the plan and plan rounds are exhausted", compiled_sha256=sha)
        gate = view["gates"].get(f"approve_plan:{sha}")
        if gate is None:
            return _go("gate", "CHECK-IN 1 answered; the approve_plan gate decides the edge", gate="approve_plan",
                       subject_sha256=sha, transition="checkin1→execute")
        return _end("the approve_plan gate refused the edge to execution", errors=gate["errors"])
    # a replan: scope changes need renewed authority before adoption
    changes = compiled.get("scope_changes") or []
    if not changes:
        return _go("adopt", "a scope-preserving replan passed its review; adoption needs no renewed authority",
                   compiled_sha256=sha)
    deviation = view["deviation"].get(sha)
    if deviation is None:
        return _go("deviation", "a scope-changing replan needs renewed authority", compiled_sha256=sha,
                   changes=changes)
    authority = deviation["authority"]
    if authority["state"] == "pending":
        if _authority_wait(authority, now, wait_bound):
            return _go("deviation", "the deviation is waiting for an answer", compiled_sha256=sha, wait=True)
        return _refused_replan(view, bound, "the deviation was not answered within the wait bound")
    if authority["state"] not in GRANTED:
        return _refused_replan(view, bound, "the scope-changing replan was declined")
    gate = view["gates"].get(f"deviation:{sha}")
    if gate is None:
        return _go("gate", "the deviation is authorized; the deviation gate decides adoption", gate="deviation",
                   subject_sha256=sha, transition="deviation→execute")
    return _refused_replan(view, bound, "the deviation gate refused the replan")


def _refused_replan(view, bound, reason):
    if view["replans"] < bound["replans"]:
        return _go("replan", reason + "; the planner proposes another plan", number=view["replans"] + 1)
    return _end(reason + "; the replan bound is reached", replans=view["replans"])


def _execution_phase(view, bound, *, now, wait_bound):
    if view["waves"] > view["waves_reviewed"]:
        return _go("wave_review", "the last wave awaits its review", number=view["waves"])
    request = view["replan_request"]
    if request is not None:
        if request.get("exhausted") or view["replans"] >= bound["replans"]:
            return _end("a replan was needed and the replan bound is reached", replans=view["replans"],
                        request=request)
        return _go("replan", "the wave review asked for a replan", number=view["replans"] + 1, request=request)
    found = schedule(view, bound)
    if found["asks"]:
        return _go("ask", "questions and R3 calls need answers", asks=found["asks"])
    if found["gates"]:
        item = found["gates"][0]
        return _go("gate", "a stage-recovery decision feeds back only through its gate", gate=item["gate"],
                   subject_sha256=item["subject_sha256"], step=item["step"], transition="failed_stage_feedback")
    if found["ready"] or found["reviews"]:
        if view["waves"] >= bound["max_waves"]:
            return _end("the wave bound is reached", waves=view["waves"])
        return _go("execute", "steps and reviews are ready", ready=found["ready"], reviews=found["reviews"])
    if found["waiting"]:
        live = [w for w in found["waiting"] if _authority_wait(w, now, wait_bound)]
        if live:
            return _go("ask", "only answers can advance the run; waiting within the bound", asks=[], wait=live)
        return _go("ask", "the wait bound passed for open questions", asks=[], expired=found["waiting"])
    plan = adopted_plan(view)
    if plan is not None and len(found["closed"]) == len(plan["steps"]):
        return _final_phase(view, bound, now=now, wait_bound=wait_bound)
    return _end("no branch can proceed", stopped=found["stopped"], blocked=found["blocked"])


def _final_phase(view, bound, *, now, wait_bound):
    result = draft(view)
    sha = result["sha256"]
    if result["missing"]:
        return _end("planned deliverables lack their adopted outputs", missing=result["missing"])
    attacks = view["attacks"].get(sha)
    if attacks is None or attacks["status"] != "valid":
        if view["kill_rounds"].get(sha, 0) < bound["kill_rounds"]:
            return _go("kill_the_result", "the drafted result needs its three attacks before the final review",
                       draft_sha256=sha)
        return _end("the kill-the-result attacks are missing or incomplete; no final review without them",
                    draft_sha256=sha)
    review = view["final_review"].get(sha)
    if review is None or (not review["credited"] and view["final_rounds"].get(sha, 0) < bound["final_review_rounds"]):
        return _go("final_review", "the drafted result awaits the fresh final review", draft_sha256=sha)
    if not review["credited"]:
        return _end("the final review could not be credited", draft_sha256=sha)
    if review["verdict"] != "pass":
        return _end("the final review did not pass and no replan remains", draft_sha256=sha,
                    findings=list(review.get("findings") or []))
    checkin = view["checkin3"].get(sha)
    if checkin is None:
        return _go("checkin3", "CHECK-IN 3 has no authority record for this result", draft_sha256=sha)
    if checkin["authority"]["state"] == "pending":
        if _authority_wait(checkin["authority"], now, wait_bound):
            return _go("checkin3", "CHECK-IN 3 is waiting for an answer", draft_sha256=sha, wait=True)
        return _end("CHECK-IN 3 was not answered within the wait bound", draft_sha256=sha)
    if checkin["authority"]["state"] not in ACCEPTED:
        return _end("CHECK-IN 3 declined the result", draft_sha256=sha)
    for gate, transition in (("final_task", "checkin3→deliver"), ("delivery", "deliver[accepted]")):
        verdict = view["gates"].get(f"{gate}:{sha}")
        if verdict is None:
            return _go("gate", f"the {gate} gate decides delivery", gate=gate, subject_sha256=sha,
                       transition=transition)
        if not verdict["passed"]:
            return _end(f"the {gate} gate refused delivery", errors=verdict["errors"], draft_sha256=sha)
    return _go("deliver", "every gate passed; the sole sink delivers", draft_sha256=sha)


# ---- planning for the controller graph ----------------------------------------------------------

def _held(reason, **detail):
    return {"phase": "planning_held", "reason": reason, "detail": detail}


def rdj_calls(compiled: dict) -> list[dict]:
    """Decide and effectful steps of class R2 or R3: each needs an RDJ case credited on its exact spec."""
    return [s for s in compiled["steps"] if (s["kind"] in planning.EFFECTFUL or s["kind"] == "decide")
            and classes.RANK[s["class"]] >= 2]


def next_planning(view: dict, bound: dict, *, purpose: str, revision: int) -> dict:
    """The next phase when the controller graph asks for a plan (``plan``) or a replan (``replan``).

    The controller numbers its plan revisions; each revision it asks for gets its own
    decomposition (a revision request carries the previous plan's review or CHECK-IN 1
    answer). Bounds end in a typed planning hold, which the controller turns into a
    qualified ending.
    """
    if purpose not in ("plan", "replan"):
        raise ValueError(f"planning purpose must be plan or replan, not {purpose!r}")
    found = _frame_phase(view, bound)
    if found is not None:
        return found if found["phase"] != "bounded_end" else _held(found["reason"], **found["detail"])
    if revision in view["returned"]:
        return _go("return_plan", "this revision's plan was already returned", revision=revision,
                   compiled_sha256=view["returned"][revision]["compiled_sha256"])
    attempts = view["plans_for"].get(revision, [])
    written = [row for row in attempts if row["status"] == "written"
               and row.get("source") == ("replan" if purpose == "replan" else "decompose")
               and row.get("frame_sha256") == view["frame_accepted"]["frame_sha256"]]
    if not written:
        if purpose == "replan" and len(view["replanned"]) >= bound["replans"]:
            return _held("the replan bound is reached", replans=len(view["replanned"]), bound=bound["replans"])
        if len(attempts) >= bound["plan_rounds"]:
            return _held(f"no acceptable {purpose} within the bounded rounds", revision=revision,
                         problems=(attempts[-1].get("problems") or [])[:20] if attempts else [])
        problems = (attempts[-1].get("problems") or []) if attempts else []
        return _go("replan" if purpose == "replan" else "decompose", f"revision {revision} needs a {purpose}",
                   revision=revision, round=len(attempts) + 1, problems=problems, number=len(view["replanned"]) + 1)
    plan = written[-1]
    compiled = next((row for row in reversed(list(view["compiled_history"].values()))
                     if row["planner_plan_sha256"] == plan["plan_sha256"] and row.get("revision") == revision), None)
    if compiled is None:
        return _go("classify_calls", "the plan's calls need their consequence classes", revision=revision,
                   plan_sha256=plan["plan_sha256"])
    sha = compiled["compiled_sha256"]
    if rdj_calls(compiled):
        review = view["plan_review"].get(sha)
        credited = review is not None and all((review.get("rdj") or {}).get(s["id"], {}).get("credited")
                                              for s in rdj_calls(compiled))
        if not credited:
            if review is None or review["attempts"] < bound["plan_review_rounds"]:
                return _go("plan_review", "every R2 or R3 call needs its RDJ case before CHECK-IN 1",
                           compiled_sha256=sha, revision=revision, critic=False)
            return _held("an RDJ case of an R2 or R3 call could not be credited", compiled_sha256=sha)
    return _go("return_plan", "the plan is framed, decomposed, classified and its R2+ calls reviewed",
               revision=revision, compiled_sha256=sha)
