"""``controller.run``: the top-level graph every controller run executes (CONTROLLER-SPEC 3.1-3.2).

```
START → intake → route_select ─┬─ fixed route ─► plan_compile ─┬─────────────────────┐
                               └─ judgment ────► judgment_plan ◄┘ (open obligations)  │
                                                      │                               ▼
   materialise → prepare_guard → prepare_wave ─┬─ dispatch ─► dispatch_prepare ═Send═► prepare_step → prepare_join ┐
        ▲                                      ├─ review ───► bind → plan_review → checkin1 → checkin1_gate ─► approved
        └──────────── prepare_guard ◄──────────┼───────────────────────────────────────────────────────────────────┘
                                               └─ blocked ──► bounded_end
   approved → wave_guard → plan_wave ─┬─ dispatch ─► dispatch_wave ═Send═► step (controller.step) → join → wave_guard
                                      ├─ waypoint ─► checkin2 → checkin2_gate → went ───────────────────► wave_guard
                                      ├─ deviation ► deviation → deviation_gate → approved_deviation ───► wave_guard
                                      ├─ escalate ─► escalate → escalate_gate ──────────────────────────► wave_guard
                                      ├─ replan ───► replan (judgment.plan) → rematerialise ────────────► wave_guard
                                      ├─ done ─────► final_review → checkin3 → checkin3_gate → deliver → END
                                      └─ blocked ──► bounded_end → END
   stop, drain, exhausted bounds, refused gates, holds and failures ───────────────────► bounded_end → END
```

The graph runs in the controller process with its substrate scope inside the run's store
(``RunStore.graph_scope``): checkpoints, events, effects and the stop flag never live in the run
directory. Node bodies read the request bytes, reading, contract and plan from the store by
digest; graph state carries ids and digests.

Steps before CHECK-IN 1. A plan step whose ``parameters.phase`` is ``prepare`` (rung none or dry,
depending only on prepare steps) runs in the prepare phase: environment, inputs, resource and
trap sweeps, figure targets and cost, the evidence CHECK-IN 1 presents. Its executor
(``prepare_step``) is a separate map node from the execution executor (``step``), so every path
to execution provably passes the CHECK-IN 1 gate.

Check-ins. Every check-in is an authority point: the node asks the authority service with a
typed check-in view rendered from run state (``request(store, kind, {"view": ...}, bounds)``) and
pauses only while the answer is pending (a resume value is a poll, never authority). The gate
that follows verifies the authority record in the store (``authority.verify``), calls
``decision_gate.check`` on the run directory and ``ledger.gate`` for the transition, and is
read-only. The node that acts on a passed gate takes its re-check through ``ledger.decide``,
which discharges the decision's obligation. ``bounded_end`` is reachable from every node,
directly or through the builder's own ``decision_turn`` and ``hold``.

Ledger rows. The intake and route nodes record the rows their transitions require from the
records the enforcing actions wrote (``RECORDERS``): P01's request, intake, binding and
command-policy records, P06's authenticated mode record, P05's admission record, P12's layout
check, P14's host observation and the route record. A row whose provider shows no evidence stays
pending and the transition holds. Every wave and the delivery first ask P12 whether the run's
directory still has the controller's own layout (a downgrade written from outside holds the run).

Execution. The wave executor sends the ready steps of each wave to the ``controller.step``
graph through ``graph_nodes.map_node``: packet ``{"step": <step.v1>, "context": {...}}``, outcome in
the child's ``results["step"]``. Review seats (plan review, P8 attacks, final review) run
through the same graph with step ids ``plan_review``, ``kill_the_result`` and ``final_review``.
Once every waypoint step completed, the wave planner runs CHECK-IN 2's seats (the plan's declared
``checkins[].seats``) before the GO is asked for: each reviews the waypoint's exact outputs as its own
step ``waypoint_review.<role>``, and only every seat's credited ``accept`` leads to the authority
point; its gate checks that review round again. A seat's role is the canonical card id (an alias is
resolved through the role registry) and a check-in seat names its check-in (``checkin``), so the
instruction package delivers that check-in's units to it.

Review verdicts. A credited ``revise`` or ``unresolved`` review is a performed review, never acceptance:
within the run's correction rounds (``correction_rounds``) its producer runs again as a new attempt with
the review's findings pinned (``correction`` in the step context), and the new subject is reviewed again.
The producer is the reviewed step, the waypoint steps (CHECK-IN 2), the steps producing the plan's
results (final review, corrected inside that node) or the planner (plan review). Budgets and counters
carry on; past the bound, or without findings, the branch holds and the run ends qualified.

Judgment semantics (this graph is the one scheduler). The replan bound is the judgment policy's for the
run's frozen mode (``replan_bound``) and the replan count is the store's, so no new plan resets it. A
judgment-route delivery needs the three P8 attacks on the exact plan and drafted result (JR09): the
attack seat's ``judgment-attacks.v1`` document, checked by ``judgment.check_attacks`` before the CHECK-IN 3
triad and again at its gate. A ``decide`` step closes, and only then do its dependents run, with its
judgment record; at R2 or R3 also an RDJ case credited on that exact record, and at R3 current authority
for the recorded choice. An ``ask`` step's question goes to the escalation point with its options, each
with the effect bounds answering it allows, and its P7 default; the selected option is kept and its branch
continues, while an unanswered or refused question holds only that branch. A ``route`` step runs its
child (the fixed route it names, compiled and bound before CHECK-IN 1) once, under the parent's authority,
budget and invocation lineage. The frame findings a judgment plan carries are CHECK-IN 1 risks.

Route adapters. A route spec may name an ``adapter`` module under ``ravel.controller.routes``;
its optional functions are called with a context ``{store, run_dir, plan, state, reading,
contract}``: ``admit(step, context)`` admits each ready step before it is sent (a refusal holds that
step), ``bind(plan, context)`` re-binds the plan after the prepare phase, ``checkin(kind,
context)`` adds route sections to a check-in view, ``gate(transition, context)`` adds
route-specific gate errors, ``step(step, outcome, context)`` checks a completed step and
``ending(reason, context)`` records unfinished work before a bounded ending (it never blocks it). After CHECK-IN 1,
``packet_context(step, context)`` adds JSON context to a step's packet (never replacing the controller's own fields)
and ``dispatch(step, context, invoke)`` receives the step's own substrate invocation as ``invoke``: it runs it at most
once, and a refusal before it holds the step with no effect.

Plan identity. The scientific plan and its digest never change; an engagement decision's applied view is pinned
beside it (``install_applied_plan``: its own ``applied_sha256``), and every consumer of the plan checks that view
against the current decision (``current_plan``).

Engagement. As a plan-approving check-in (CHECK-IN 1, a deviation) renders, the engagement package decides the
run's tier by code from the facts pinned in the store; the check-in shows the decision and its authority binds the
decision's digest, and the decision's applied view is pinned (``engage``). Each wave join sends its outcomes' trigger
events (E1-E8) to the engagement monitor and checks the envelope's floors, with the independent broker count a
trusted composer installs (``register_broker_counter``); a floor breach on a completed session raises engagement and
holds every later wave (``engagement_hold``), and a raised engagement's view is pinned before the next dispatch.
Unknown usage is never zero: without a broker count the broker floor stays unestablished and nothing is accepted.

Collaborating services are resolved by name (``service``): the obligation ledger, authority,
sink, instructions, judgment and confinement packages. A service that is not installed is
replaced by a fail-closed stand-in: its gates refuse, its authority stays pending and its sink
delivers nothing.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import dataclasses
import hashlib
from ravel.workflow import private_files
from importlib import import_module
import inspect
import json
import os
from pathlib import Path
import time

from ..workflow import graph_nodes as nodes
from ..workflow import graph_registry
from ..workflow.agent_graph import GraphError
from .state import RunState
from .store import RunStore

GRAPH_ID = "controller.run"
STEP_GRAPH = "controller.step"
JUDGMENT_GRAPH = "judgment.plan"
AUTHORITY_SCHEMA = "controller_authority"
MAX_PLAN_REVISIONS = 3
MAX_WAVES = 256
MAX_POLLS = 64
CI3_SEATS = ("physics-critic", "skeptical-verifier", "physics-decider")
CI1_SEATS = ("plan-critic",)
# The CHECK-IN 2 seat of a plan that has a waypoint and declares no seats of its own (``checkins[].seats``).
CI2_SEATS = ("physics-critic",)
RUNGS = ("none", "dry", "smoke", "pilot", "full", "scan")
PREPARE_RUNGS = (None, "none", "dry")
# Gate nodes: (decision gate or None, ledger transition, authority kind, decisions that pass).
GATES = {
    "checkin1_gate": ("approve_plan", "checkin1->execute", "approve_plan", ("approve",)),
    "checkin2_gate": ("checkin2_accept", "checkin2->execute[{waypoint}]", "go", ("go",)),
    "deviation_gate": ("deviation", "deviation->execute[{event}]", "deviation", ("approve",)),
    "escalate_gate": (None, "escalate->execute", "r3_action", ("approve", "default")),
    "checkin3_gate": ("final_task", "checkin3->deliver", "final", ("accept",)),
}
# The gate names registered on the graph row (``escalation`` has no decision gate).
GATE_NAMES = {"checkin1_gate": "approve_plan", "checkin2_gate": "checkin2_accept", "deviation_gate": "deviation",
              "escalate_gate": "escalation", "checkin3_gate": "final_task"}
POINTS = {"checkin1_gate": "checkin1", "checkin2_gate": "checkin2", "deviation_gate": "deviation",
          "escalate_gate": "escalate", "checkin3_gate": "checkin3"}
GATE_OF = {point: gate for gate, point in POINTS.items()}
# The decisions of each authority kind that let its gate pass (a question's answer passes the escalation gate).
ACCEPTED = {**{kind: accepted for _, _, kind, accepted in GATES.values()}, "escalation": ("answer", "default")}
# The authority's label for an answer typed at the controller's terminal: evidence of an answer, never of a person
# (``physicist_terminal_response`` is unreachable on this platform).
TERMINAL_UNATTESTED = "terminal_operator_unattested"
AUTHORITY_KINDS = {"checkin1": "approve_plan", "checkin2": "go", "deviation": "deviation", "escalate": "r3_action",
                   "checkin3": "final"}
STEP_DONE = "completed"
TERMINAL_STEP = ("completed", "failed", "held", "escalated", "budget_exhausted", "stopped", "skipped")
LAUNCH_KINDS = ("operate", "acquire")
# Escalations that are one question each, with options of their own: an ``ask`` step's question (authority kind
# ``escalation``) and an R3 decision's authority for its recorded choice (``r3_action``). The other escalations of a
# wave (a worker's stop or decision block) are asked together as one R3 action.
QUESTION_KINDS = {"ask": "escalation", "decide": "r3_action"}
CLASS_RANK = {"R0": 0, "R1": 1, "R2": 2, "R3": 3}
# The frozen mode record's fields the run state keeps (the intake's projection; nothing later changes them).
MODE_KEYS = ("record_id", "mode", "bounds", "id", "installed", "source", "delegation", "budgets", "budget_source",
             "harness", "engagement", "restricted_sources", "remote_job_ceiling", "procedure_byte_ceiling",
             "agent_preferences", "site_resource_ceilings", "compute_policy")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


# ---- collaborating services ------------------------------------------------------------------

SERVICE_NAMES = ("ledger", "authority", "sink", "instructions", "judgment", "confine")
_OVERRIDES: dict = {}


class _AbsentLedger:
    installed = False

    def materialise(self, store, stage, context):
        return []

    def record(self, store, entry_id, status, evidence):
        return None

    def gate(self, store, transition):
        return [{"entry": "ledger-not-installed", "id": "ledger-not-installed", "reason": "ledger_not_installed",
                 "consequence": "diagnostic", "transition": transition,
                 "message": "the obligation ledger is not installed; no transition can be verified"}]

    def decide(self, store, rundir, gate_name, action):
        return [{"code": "ledger_not_installed", "gate": gate_name, "provider": "controller.ledger",
                 "message": "the obligation ledger is not installed; no decision can be discharged", "fix": "",
                 "pins": []}]

    @staticmethod
    def population_equality(expected, actual):
        present = set(actual)
        return [item for item in expected if item not in present]

    def summary(self, store):
        return {"installed": False}


class _AbsentAuthority:
    installed = False

    def operator_config(self):
        return {}

    def freeze_mode(self, store, contract, **_):
        return {"installed": False, "mode": "physicist-in-the-loop", "bounds": {}, "record_id": None}

    def request(self, store, kind, subject, bounds):
        return {"pending": {"kind": kind, "reason": "the authority service is not installed", "poll": False}}

    def stop_state(self, store):
        return "running"


class _AbsentSink:
    installed = False

    def deliver(self, store, plan):
        raise nodes.RecoveryHold("sink_not_installed", "install the sole sink; nothing is delivered without it")

    def bounded_end(self, store, reason):
        record = {"kind": "qualified-ending", "reason": reason, "delivered": False,
                  "labels": ["QUALIFIED ENDING", "NOT DELIVERED: the sink is not installed"]}
        record["id"] = store.append("receipt", record)
        return record

    def receipt(self, store):
        rows = store.scan("receipt")
        return rows[-1]["record"] if rows else {}


class _AbsentInstructions:
    installed = False

    def manifest(self, step, card):
        return {"units": [], "sha256": _digest([]), "installed": False}


class _AbsentJudgment:
    installed = False

    def classify(self, action):
        return "R3"

    def record_judgment(self, store, record):
        return store.append("judgment", dict(record))


class _AbsentConfine:
    installed = False

    def backends(self):
        return {}


_ABSENT = dict(zip(SERVICE_NAMES, (_AbsentLedger(), _AbsentAuthority(), _AbsentSink(), _AbsentInstructions(),
                                   _AbsentJudgment(), _AbsentConfine())))


def service(name):
    """The installed package for ``name``, a test override, or its fail-closed stand-in."""
    if name in _OVERRIDES:
        return _OVERRIDES[name]
    if name not in SERVICE_NAMES:
        raise GraphError(f"unknown controller service {name!r}")
    module = __package__ + "." + name
    try:
        return import_module(module)
    except ModuleNotFoundError as exc:
        if exc.name != module:
            raise
        return _ABSENT[name]


def service_function(name, module, function):
    """``function`` of service ``name``: its own attribute, or the function of that name in its submodule
    ``module`` (``confine.policy.admission``); None when the service offers neither (a stand-in)."""
    found = service(name)
    for holder in (found, getattr(found, module, None)):
        value = getattr(holder, function, None) if holder is not None else None
        if callable(value) and not inspect.ismodule(value):
            return value
    if not inspect.ismodule(found):
        return None
    try:
        value = getattr(import_module(f"{found.__name__}.{module}"), function, None)
    except ModuleNotFoundError as exc:
        if exc.name != f"{found.__name__}.{module}":
            raise
        return None
    return value if callable(value) else None


@contextmanager
def services(**overrides):
    """Substitute collaborating services for a block (test harness only, SW30)."""
    from .testing import refuse
    refuse("controller service substitution")
    unknown = set(overrides) - set(SERVICE_NAMES)
    if unknown:
        raise GraphError(f"unknown controller services {sorted(unknown)}")
    before = dict(_OVERRIDES)
    _OVERRIDES.update(overrides)
    try:
        yield
    finally:
        _OVERRIDES.clear()
        _OVERRIDES.update(before)


# ---- state helpers ---------------------------------------------------------------------------

def _store(state):
    run = state.get("run") or {}
    if not run.get("run_id") or not run.get("store_root"):
        raise nodes.RecoveryHold("run_identity_missing", "start the run through ravel drive or ravel ask")
    return RunStore(run["run_id"], root=run["store_root"])


def _run_dir(state):
    return Path(state["run"]["run_dir"])


def _json_blob(store, digest):
    return json.loads(store.get_blob(digest).decode("utf-8"))


def _put_json(store, value):
    return store.put_blob((json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                      allow_nan=False)).encode("utf-8"))


def _intake_records(state, store):
    pins = state.get("request") or {}
    record = store.read("intake", pins["intake_record_id"])["record"]
    return _json_blob(store, record["contract_blob"]), _json_blob(store, record["reading_blob"]), record


def _supplied(store):
    row = store.latest("supplied")
    return deepcopy(row["record"].get("inputs") or []) if row else []


def current_plan(state, store=None):
    """The plan document the state names, read from the store and checked against its digests.

    Two identities. The scientific plan (``blob``, ``sha256``) is immutable: its bytes hash to its digest. With an
    engagement decision applied (``applied_blob``, ``applied_sha256``) the plan is that applied view, accepted only as
    the current decision's application of exactly these scientific bytes (``applied_errors``). Every consumer reads
    the plan here: the check-in requests, the context each step is dispatched under and the sink."""
    pins = state.get("plan") or {}
    if not pins.get("blob"):
        return None
    store = store or _store(state)
    plan = _json_blob(store, pins["blob"])
    from .routes import plan_sha256
    if plan.get("sha256") != pins.get("sha256") or plan_sha256(plan) != plan["sha256"]:
        raise nodes.RecoveryHold("plan_digest_mismatch", "the stored plan does not match its pinned digest")
    if not (pins.get("applied_blob") or pins.get("applied_sha256")):
        return plan
    applied = _json_blob(store, pins["applied_blob"]) if pins.get("applied_blob") else None
    problems = applied_errors(store, plan, applied, pins.get("applied_sha256"))
    if problems:
        raise nodes.RecoveryHold("applied_plan_mismatch", "; ".join(problems)[:1500])
    return applied


def scientific_plan(state, store=None):
    """The scientific plan the state pins (its own bytes, checked by its digest), whatever view is applied to it."""
    pins = {k: v for k, v in (state.get("plan") or {}).items() if k not in ("applied_blob", "applied_sha256")}
    return current_plan({**state, "plan": pins}, store)


# The engagement package's binding interface the controller runs (P18).
ENGAGEMENT_API = ("decide", "apply", "effective_decision", "check_applied", "observe", "check_envelope")


def _engagement_package():
    """The installed engagement package offering its binding interface, or None."""
    module = __package__ + ".engagement"
    try:
        found = import_module(module)
    except ModuleNotFoundError as exc:
        if exc.name != module:
            raise
        return None
    return found if all(callable(getattr(found, name, None)) for name in ENGAGEMENT_API) else None


def _engagement():
    """The engagement package when the run composes it, else None: it is installed with its binding interface and the
    run's ledger gates its rows (``register_gate_hook``, where ``compose_services`` registers them). Nothing engages a
    run whose ledger cannot gate engagement rows (a stand-in ledger enforces none); with the installed ledger, a
    transition that needs the engagement evidence then holds. Checking an applied view needs only the package."""
    found = _engagement_package()
    return found if found is not None and callable(getattr(service("ledger"), "register_gate_hook", None)) else None


def applied_errors(store, plan, applied, applied_sha256):
    """Why ``applied`` is not the authenticated applied view of the scientific ``plan``: the view keeps the scientific
    digest, its own digest (``engagement.applied_sha256``) is the pinned one, the run's current engagement decision
    (``effective_decision``) covers exactly these scientific bytes, and the view equals that decision's deterministic
    application (``engagement.check_applied``). Changed seats, dropped duties, altered correction bounds, changed
    scientific bytes and a stale decision each refuse; a digest alone blesses nothing."""
    engagement = _engagement_package()
    if engagement is None:
        return ["the engagement package is not installed: an applied view cannot be checked"]
    if type(applied) is not dict:
        return ["the applied view is not in the store"]
    try:
        decision = engagement.effective_decision(store)
        problems = [str(p) for p in engagement.check_applied(applied, decision) or ()]
    except (ValueError, KeyError, TypeError) as exc:  # the engagement package's refusal
        return [f"the engagement decision cannot be applied: {exc}"[:500]]
    if decision.get("scientific_plan") != plan or decision.get("scientific_plan_sha256") != plan["sha256"]:
        problems.append("the engagement decision covers other scientific bytes")
    if applied.get("sha256") != plan["sha256"]:
        problems.append("the applied view names another scientific plan")
    if type(applied_sha256) is not str or (applied.get("engagement") or {}).get("applied_sha256") != applied_sha256:
        problems.append("the applied view's digest is not the pinned one")
    return problems


def install_applied_plan(store, pins, applied):
    """Pin ``applied`` as the view of the scientific plan ``pins`` name, keeping both identities: the scientific blob
    and digest stay as they are, a new ``plan`` record repeats the scientific record with the view's blob and digest
    (``applied_blob``, ``applied_sha256``, where the governed step binds a step to the view), and the returned pins
    carry both. A view that is not the current decision's application of exactly these scientific bytes is refused
    (``applied_errors``)."""
    scientific = {k: v for k, v in pins.items() if k not in ("applied_blob", "applied_sha256")}
    plan = current_plan({"plan": scientific}, store)
    digest = (applied.get("engagement") or {}).get("applied_sha256") if type(applied) is dict else None
    problems = applied_errors(store, plan, applied, digest)
    if problems:
        raise nodes.RecoveryHold("applied_plan_mismatch", "; ".join(problems)[:1500])
    record = deepcopy(store.read("plan", pins["record_id"])["record"])
    if record.get("plan_sha256") != plan["sha256"] or record.get("blob") != scientific["blob"]:
        raise nodes.RecoveryHold("plan_digest_mismatch", "the plan record differs from the pinned scientific plan")
    applied_blob = _put_json(store, applied)
    record.update(applied_blob=applied_blob, applied_sha256=digest)
    return {**pins, "record_id": store.append("plan", record), "applied_blob": applied_blob, "applied_sha256": digest}


# ---- engagement: the decision at an approving check-in, its applied view, events and envelope floors ----------

# The check-ins that approve a plan: its engagement is decided as they render, and their authority binds the decision.
ENGAGED_POINTS = ("checkin1", "deviation")
# The typed reason the next wave holds for once a session breached an envelope floor.
ENGAGEMENT_HOLD = "orchestration_evidence_missing"
# Worker failure codes of a schema or acknowledgement check: one that passes on its retry is a mechanical retry (E7).
MECHANICAL_CODES = ("final_record_schema", "card_output_schema", "instruction_ack", "reviewer_item_verdicts")
_BROKER_COUNTER: list = []


def register_broker_counter(fn):
    """Compose the run's independent model-request counter: ``fn(store) -> {"requests": int, "tokens": number} or
    None`` (None: no count for this run). Product composition installs the controller's transport-result counter,
    which reads provider usage captured outside worker write roots. Missing provider records remain unknown; no
    delivery is accepted on usage only the worker reported. Registration is explicit and stable."""
    if not callable(fn):
        raise TypeError("an independent broker counter must be callable")
    if _BROKER_COUNTER and _BROKER_COUNTER[0] is not fn:
        raise GraphError("an independent broker counter is already composed")
    _BROKER_COUNTER[:] = [fn]


def broker_counts(store):
    """The composed counter's reading for the run, or None without one. A failing or malformed reading is an invalid
    count, so the broker floor fails closed; it is never a missing count and never zero."""
    if not _BROKER_COUNTER:
        return None
    try:
        found = _BROKER_COUNTER[0](store)
    except Exception as exc:  # the counter's own failure: recorded, and the floor refuses
        store.append("broker-count", {"error": f"{type(exc).__name__}: {exc}"[:500]})
        return {"requests": None}
    if found is None:
        return None
    if type(found) is not dict:
        return {"requests": None}
    return {key: deepcopy(found[key]) for key in ("requests", "tokens") if key in found} or {"requests": None}


def _engaged(store):
    """The engagement package and whether the run recorded a decision (``(package or None, decided)``)."""
    engagement = _engagement()
    return engagement, bool(engagement is not None and store.scan(engagement.DECISION))


def engagement_decision(store, plan_sha256):
    """The latest recorded engagement decision on scientific plan ``plan_sha256``, verified, or None."""
    engagement = _engagement()
    if engagement is None or type(plan_sha256) is not str:
        return None
    for row in reversed(store.scan(engagement.DECISION)):
        record = {**deepcopy(row["record"]), "record_id": row["id"]}
        if record.get("scientific_plan_sha256") == plan_sha256:
            try:
                engagement.verify(record)
            except (ValueError, KeyError, TypeError) as exc:
                raise nodes.RecoveryHold("engagement_refused", f"the engagement decision is not intact: {exc}"[:500])
            return record
    return None


def _pin_view(store, pins, view):
    """Pin ``view`` beside the scientific plan ``pins`` name, once: a node re-entered after an interruption finds the
    record it pinned (the latest plan record) and pins nothing twice."""
    digest = (view.get("engagement") or {}).get("applied_sha256")
    if pins.get("applied_sha256") == digest and pins.get("applied_blob"):
        return pins
    latest = store.latest("plan")
    record = (latest or {}).get("record") or {}
    if (record.get("plan_sha256") == pins.get("sha256") and record.get("blob") == pins.get("blob")
            and record.get("applied_sha256") == digest and record.get("applied_blob")):
        return {**pins, "record_id": latest["id"], "applied_blob": record["applied_blob"], "applied_sha256": digest}
    return install_applied_plan(store, pins, view)


def engage(state, store):
    """Decide the run's engagement for its current scientific plan and pin that decision's applied view.

    Called as a plan-approving check-in renders (``ENGAGED_POINTS``), and when a plan is bound after an earlier
    decision (its own plan review then runs under its own view). ``decide`` computes the tier by code from the facts
    pinned in the store, once per scientific plan (a plan revised after a decision is decided as it is bound, before
    its own review credits any fact: conservatively); ``apply`` projects the effective decision onto the unchanged
    scientific plan, which keeps its digest; the view is pinned beside it with its own
    (``install_applied_plan``). Returns the plan pins with both identities. Without the engagement package nothing is
    decided: the ledger then holds every transition its rows gate. A refusal holds the run, typed."""
    engagement = _engagement()
    pins = state.get("plan") or {}
    if engagement is None or not pins.get("blob"):
        return pins
    scientific = scientific_plan(state, store)
    try:
        # One decision per scientific plan: a re-rendered check-in (a resumed or polled authority point) applies the
        # decision it showed; the pinned view's own plan record never makes a second one.
        if engagement_decision(store, scientific["sha256"]) is None:
            engagement.decide(store, {**state, "plan": scientific})
        view = engagement.apply(scientific, engagement.effective_decision(store))
    except (ValueError, KeyError, TypeError) as exc:  # the engagement package's refusal or a refused seat packet
        raise nodes.RecoveryHold("engagement_refused", f"the engagement decision cannot be applied: {exc}"[:1500])
    pinned = _pin_view(store, {k: v for k, v in pins.items() if k not in ("applied_blob", "applied_sha256")}, view)
    _record_engagement_rows(store, engagement_decision(store, scientific["sha256"]), pinned)
    return pinned


def repin_engagement(state, store):
    """After an escalation, pin the applied view of the effective decision (a raised tier, or a subject's re-review
    seats) so that every step not yet dispatched runs under it. Unchanged pins when the view is already pinned."""
    engagement = _engagement()
    pins = state.get("plan") or {}
    if engagement is None or not pins.get("applied_sha256"):
        return pins
    try:
        view = engagement.apply(scientific_plan(state, store), engagement.effective_decision(store))
    except (ValueError, KeyError, TypeError) as exc:
        raise nodes.RecoveryHold("engagement_refused", f"the raised engagement cannot be applied: {exc}"[:1500])
    return _pin_view(store, pins, view)


# The rows the decision and its applied view discharge (from the records those actions wrote; nothing by fiat).
ENGAGEMENT_ROWS = {"engagement.decide": ("EG01", "EG06"), "engagement.facts": ("EG02",), "engagement.apply": ("EG03",)}


def _record_engagement_rows(store, decision, pins):
    """EG01, EG02 and EG06 from the recorded decision (the tier computed by code from facts pinned in the store, each
    with its source and checker; only the operator's minimum and an authenticated raise act on it, upwards); EG03 from
    the pinned applied view, which ``install_applied_plan`` checked is the decision's exact application."""
    ledger = _row_ledger()
    if ledger is None or decision is None:
        return None
    changes = []
    for node, rows in ENGAGEMENT_ROWS.items():
        for key in ledger.pending(store, node=node):
            row = key.split("@", 1)[0]
            if row not in rows:
                continue
            evidence = ({"record": pins["record_id"], "sha256": pins["applied_sha256"],
                         "mechanism": "engagement.check_applied"} if row == "EG03" else
                        {"record": decision["record_id"], "sha256": decision["sha256"], "mechanism": node})
            changes.append((row, "P18", (key, "satisfied", {**evidence, "provider": "P18", "point": node})))
    return _apply_rows(store, "controller.engagement", changes, {}) if changes else None


def _record_raise_row(store, kind, record_id, pins, accepted):
    """EG12 at CHECK-IN 1, once the authority authenticates the approval: the decision it binds took the operator's
    minimum and any authenticated raise only upwards (``raise_only``); nobody lowered the computed tier."""
    ledger = _row_ledger()
    decision = engagement_decision(store, pins.get("plan_sha256"))
    if ledger is None or decision is None or pins.get("engagement_decision_sha256") != decision["sha256"]:
        return None
    try:
        record, _ = authenticated(store, kind, record_id, pins)
    except Exception:  # the authority service's refusal: nothing is recorded
        return None
    if record.get("decision") not in accepted:
        return None
    keys = [k for k in ledger.pending(store, node="authority.ci1") if k.split("@", 1)[0] == "EG12"]
    return _apply_rows(store, "authority.ci1", [("EG12", "P18", (key, "satisfied", {
        "authority": record_id, "record": decision["record_id"], "sha256": decision["sha256"],
        "mechanism": "engagement.policy.raise_only", "provider": "P18", "point": "authority.ci1"})) for key in keys],
        {}) if keys else None


def engagement_section(decision, pinning=()):
    """The check-in section that shows the engagement decision the approval binds: the tier and how it was computed,
    each fact with its source and checker, how the facts were pinned and credited before it (``pinning``, from
    ``engagement_fact_lines``), the seat plan and the projected usage (or why it is unknown)."""
    lines = [f"Tier {decision['tier']}: computed {decision['computed_tier']} by code from the facts below; operator "
             f"minimum {decision.get('operator_minimum') or 'none'}; authenticated raises "
             f"{len(decision.get('physicist_raise_ids') or [])}. The tier is never lowered; seats added by an "
             "escalation are R1 events, not a deviation."]
    for reason in decision.get("reasons") or ():
        value = json.dumps(reason.get("value"), sort_keys=True)
        lines.append(f"Fact {reason.get('fact')}: {value[:160]} (source {reason.get('source')}, checked by "
                     f"{reason.get('checker')}; minimum tier {reason.get('minimum_tier')}, rule {reason.get('rule')}).")
    lines += list(pinning)
    seats = decision.get("seat_plan") or {}
    lines.append(f"Seat plan {str(decision.get('seat_plan_sha256'))[:16]}: {len(seats.get('seats') or [])} review "
                 f"seat(s), {decision.get('correction_bound')} correction round(s), context units inline up to "
                 f"{(decision.get('packet_scope') or {}).get('inline_context_tokens')} tokens.")
    projected = decision.get("projected_envelope") or {}
    if projected.get("status") == "ready":
        low, high = projected["low"], projected["high"]
        lines.append(f"Projected usage at {decision['tier']} (design model): sessions {low['sessions']}-{high['sessions']}, "
                     f"model calls {low['calls']}-{high['calls']}, input tokens {low['input_tokens']}-"
                     f"{high['input_tokens']}, output tokens {low['output_tokens']}-{high['output_tokens']}, cost USD "
                     f"{low['cost_usd']}-{high['cost_usd']}.")
    else:
        lines.append("Projected usage: unavailable (no current projection for this route and tier).")
    envelopes = decision.get("envelopes") or {}
    chosen, full = envelopes.get(decision["tier"]) or {}, envelopes.get("full") or {}
    if chosen.get("projection_tier"):
        lines.append(f"Projected central cost: projection_tier={chosen['projection_tier']} at {decision['tier']}; "
                     f"{chosen.get('scope_reason') or 'reduced packet scope unavailable'}; saving unavailable.")
    elif (chosen.get("status") == full.get("status") == "ready"
          and all(all(k in (entry.get("central") or {}) for k in ("sessions", "calls", "cost_usd"))
                  for entry in (chosen, full))):
        a, b = chosen["central"], full["central"]
        saving = b["cost_usd"] - a["cost_usd"]
        percent = 100 * saving / b["cost_usd"] if b["cost_usd"] else 0
        lines.append(f"Projected central cost at {decision['tier']}: {a['sessions']} sessions, {a['calls']} calls, "
                     f"USD {a['cost_usd']:g}; at full: {b['sessions']} sessions, {b['calls']} calls, "
                     f"USD {b['cost_usd']:g}; saving USD {saving:g} ({percent:.1f}%).")
    else:
        lines.append(f"Projected central cost: unavailable (missing current {decision['tier']} or full entry).")
    budget = decision.get("budget_authority")
    compute_mode = (decision.get("compute_policy") or {}).get("mode", "bounded")
    lines.append(f"Compute policy: {compute_mode}; the frozen operator budgets and model preferences govern spending.")
    lines.append("Budget: the projection is within the operator's ceilings." if not budget else
                 f"Budget: {budget.get('class')} {budget.get('action')} ("
                 f"{', '.join(budget.get('dimensions') or ()) or budget.get('reason')}).")
    return {"id": "engagement", "title": "Engagement", "lines": lines}


# ---- engagement facts: pinned before the plan review, credited by it, read by the decision at CHECK-IN 1 ------------

# The controller's record of one pinning of the engagement facts on a scientific plan: what it pinned, what it refused
# to pin and why (typed), and, after the plan review, which pinned facts the credited plan critic covered.
ENGAGEMENT_FACTS = "engagement-facts"
# The adopted method decision a run supplies (``method_selection.DECISION_PATH``): staged at intake as
# ``inputs/<name>`` from the bytes the entry recorded, so its custody is the controller's, never a worker's.
METHOD_INPUT = "method-decision.json"


def adopted_method(state, store, *, plan=None):
    """Read the request-bound method from intake or controller-adopted method and cost preparation outputs.

    Installed ladder validation and the plan critic's exact fact credit govern engagement selection.
    """
    _, _, intake_record = _intake_records(state, store)
    rows = [r for r in intake_record.get("supplied") or () if type(r) is dict and r.get("name") == METHOD_INPUT]
    if not rows:
        if plan is not None and any(o.get('kind') == 'method-decision'
                                    for s in plan['steps'] for o in s.get('outputs', [])):
            from .engagement import planning
            try:
                return planning.adopted_method(state, store, plan, intake_record['request_sha256']), None
            except (ValueError, KeyError, TypeError, OSError) as exc:
                return None, 'planned_method_refused:' + str(exc)[:300]
        return None, "method_decision_not_supplied"
    if len(rows) != 1:
        return None, "method_decision_ambiguous"
    path = _run_dir(state) / "inputs" / METHOD_INPUT
    if path.is_symlink() or not path.is_file():
        return None, "method_decision_missing"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != rows[0].get("sha256"):
        return None, "method_decision_changed"
    try:
        method = json.loads(raw)
    except ValueError:
        return None, "method_decision_unreadable"
    if type(method) is not dict:
        return None, "method_decision_unreadable"
    from ..workflow.method_selection import validate_method_decision
    try:
        problems = validate_method_decision(method)
    except (ValueError, KeyError, TypeError) as exc:
        problems = [str(exc)]
    if problems:
        return None, "method_decision_invalid"
    if method.get("request_digest") != intake_record.get("request_sha256"):
        return None, "method_decision_other_request"
    return method, None


def plan_novelty(plan):
    """``(novelty, None)`` or ``(None, typed reason)``, derived by code from the plan's route: a fixed route whose
    compiled plan names the installed route spec it conforms to is a reviewed recipe (N0); a plan the judgment graph
    authored for this request is an authored implementation (N1). Anything else stays unknown (full). The plan critic
    still has to review the value before it counts."""
    route = plan.get("route") or {}
    if route.get("id") == "judgment":
        return "N1", None
    from . import routes
    from .routes.select import spec_sha256
    try:
        spec = routes.find(route.get("id"))
    except Exception:  # an uninstalled route spec: the novelty stays unknown
        return None, "route_spec_not_installed"
    if type(route.get("spec_sha256")) is not str or route["spec_sha256"] != spec_sha256(spec):
        return None, "route_spec_unpinned"
    return "N0", None


def run_lineage(store):
    """``none`` for a run whose frozen operating mode has no parent run; ``unknown`` otherwise (a child run's parent
    kind is not recorded in its mode, so its special-condition inventory stays incomplete: full)."""
    frozen = getattr(service("authority"), "frozen", None)
    if not callable(frozen):
        return "unknown"
    try:
        mode = frozen(store, required=False)
    except Exception:  # the authority's refusal or another interface: lineage unknown
        return "unknown"
    if type(mode) is dict and mode.get("run_id") == store.run_id and "parent" in mode and mode["parent"] is None:
        return "none"
    return "unknown"


def pin_engagement_facts(state, store, plan):
    """Pin the engagement facts of scientific ``plan`` before its plan review (``facts.pin_inputs``): the
    deliverable population against the pinned reading, the special-condition inventory from the contract and the
    run's lineage, the adopted method (``adopted_method``) and the plan's novelty (``plan_novelty``). Returns the
    review items the CHECK-IN 1 seats receive (one per pinned fact needing review), or ``[]`` when the run composes no
    engagement. Each refusal is recorded with its typed reason; nothing pinned here lowers anything until the plan
    critic's credited review covers it (``credit_engagement_facts``)."""
    if _engagement() is None:
        return []
    from .engagement import facts
    contract, reading, _ = _intake_records(state, store)
    method, method_refused = adopted_method(state, store, plan=plan)
    method_source = None
    if method is not None:
        from .engagement.records import latest
        adopted = latest(store, 'engagement-method-adoption')
        if (adopted and adopted.get('plan_sha256') == plan['sha256']
                and adopted.get('method_sha256') == _digest(method)):
            method_source = {'record_id': adopted['record_id'], 'sources': adopted['sources']}
    novelty, novelty_refused = plan_novelty(plan)
    parent = run_lineage(store)
    try:
        items = facts.pin_inputs(store, plan, reading, contract, method=method, novelty=novelty, parent=parent,
                                 method_source=method_source)
    except (ValueError, KeyError, TypeError) as exc:
        store.append(ENGAGEMENT_FACTS, {"plan_sha256": plan["sha256"], "event": "pinned", "items": [],
                                        "refused": [{"fact": "all", "reason": "pin_refused:" + str(exc)[:300]}]})
        return []
    refused = [{"fact": name, "reason": reason} for name, reason in
               (("compute", method_refused), ("novelty", novelty_refused),
                ("special", None if parent != "unknown" else "lineage_unknown")) if reason]
    store.append(ENGAGEMENT_FACTS, {"plan_sha256": plan["sha256"], "event": "pinned", "refused": refused,
                                    "items": [{k: i[k] for k in ("id", "record_id", "subject_sha256")} for i in items]})
    return items


def engagement_review_items(store, items):
    """The plan review items of the pinned facts ``items``: each names its record, the exact digest the credit binds,
    the fact's recorded content and what the critic checks."""
    found = []
    for item in items:
        record = deepcopy(store.read(item["id"], item["record_id"])["record"])
        identity = item['id'] + (':' + item['record_id'] if item['id'] == 'engagement-child-input' else '')
        found.append({"id": f"engagement:{identity}", "kind": "engagement_fact", "record_id": item["record_id"],
                      "subject_sha256": item["subject_sha256"], "fact": record, "must_check": item["must_check"]})
    return found


def credit_engagement_facts(store, plan, review_record_id, items):
    """After the plan review: credit exactly the pinned facts that the round's credited, accepting plan critic covered
    (``facts.credit_reviewed_facts``) and record which. A refused, revising or uncredited review credits nothing."""
    if _engagement() is None or not items:
        return []
    from .engagement import facts
    try:
        credited = facts.credit_reviewed_facts(store, plan, review_record_id)
    except (ValueError, KeyError, TypeError) as exc:
        credited, reason = [], "credit_refused:" + str(exc)[:300]
    else:
        reason = None if credited else "plan_critic_did_not_credit_and_accept"
    store.append(ENGAGEMENT_FACTS, {"plan_sha256": plan["sha256"], "event": "credited", "review": review_record_id,
                                    "credited": list(credited),
                                    "refused": [{"fact": "reviewed", "reason": reason}] if reason else []})
    return credited


def engagement_fact_lines(store, plan_sha256):
    """The CHECK-IN 1 lines that say how the decision's facts were pinned and credited (typed refusals included)."""
    rows = [r["record"] for r in store.scan(ENGAGEMENT_FACTS) if r["record"].get("plan_sha256") == plan_sha256]
    pinned = [r for r in rows if r.get("event") == "pinned"]
    credited = [r for r in rows if r.get("event") == "credited"]
    if not pinned:
        return ["Fact pinning: no facts were pinned before the plan review; every unreviewed fact takes its most "
                "complex value."]
    last = pinned[-1]
    lines = [f"Fact pinning before the plan review: {len(last.get('items') or [])} reviewable fact(s) pinned ("
             + (", ".join(i["id"] for i in last.get("items") or ()) or "none") + "); not pinned: "
             + (", ".join(f"{r['fact']} ({r['reason']})" for r in last.get("refused") or ()) or "none") + "."]
    if credited:
        done = credited[-1]
        lines.append(f"Plan critic credit (review {done.get('review')}): {len(done.get('credited') or [])} fact(s) "
                     "credited" + ("; " + ", ".join(f"{r['reason']}" for r in done.get("refused") or ())
                                   if done.get("refused") else "") + ".")
    else:
        lines.append("Plan critic credit: none recorded; pinned facts stay unreviewed (most complex value).")
    return lines


def observe_engagement(store, events):
    """Each controller-observed trigger event to ``engagement.observe`` (E1-E8); the escalations it recorded.

    Without a recorded decision there is no tier to raise and nothing is observed. A refusal (the installed policy
    changed after the decision) holds the run, typed."""
    engagement, decided = _engaged(store)
    if not decided or not events:
        return []
    found = []
    try:
        for event in events:
            raised = engagement.observe(store, event)
            if raised is not None:
                found.append(raised)
    except (ValueError, KeyError, TypeError) as exc:
        raise nodes.RecoveryHold("engagement_refused", f"an engagement event cannot be observed: {exc}"[:1500])
    return found


def _judgment_classes(store, ids):
    """The consequence classes of the judgment records ``ids`` (the judgment service's own stored records)."""
    stored = service_function("judgment", "records", "stored")
    if stored is None or not ids:
        return []
    wanted = set(ids)
    return [row.get("class") for row in stored(store) or () if row.get("judgment_id") in wanted]


def outcome_events(state, store, items, rows, outcomes, record_id):
    """The trigger events of one wave's outcomes, one event per attempt (one outcome raises engagement once), from the
    governed step's records as the join folded them: E1 a producer failure that persisted past its retries, E2 a
    review that asked for revision, stayed unresolved or was not credited, E4 a worker escalation, a replan request or
    a typed hold, E5 and E6 a decision whose recorded class exceeds the plan's (R2, R3), E7 a schema or
    acknowledgement failure that passed on its retry."""
    events, before = [], state.get("steps") or {}
    for item in items:
        step, attempt = item["step"], item["attempt"]
        row, outcome = rows[step["id"]], outcomes.get(step["id"]) or {}
        found = {}
        if row["status"] == "failed":  # a failure within the attempt limit is folded to a retry, not here
            found.update(validation_failed=True, retry_exhausted=True)
        review = outcome.get("review") or {}
        if review.get("verdict") in REVIEW_VERDICTS or review.get("credited") is False:
            found["review"] = {"verdict": review.get("verdict"), "credited": review.get("credited")}
        escalation = outcome.get("escalation")
        if escalation in ("checkin_flag", "decision_block", "new_experiment_required", "stop"):
            found["escalation"] = escalation
        if outcome.get("replan") or escalation == "new_experiment_required":
            found["replan"] = True
        if row["status"] == "held":
            found["status"] = "held"
        planned = CLASS_RANK.get(step.get("consequence_class"), -1)
        classes = [c for c in _judgment_classes(store, outcome.get("judgments") or ()) if c in ("R2", "R3")
                   and CLASS_RANK[c] > planned]
        if classes:
            found["new_consequence"] = max(classes, key=CLASS_RANK.get)
        codes = {c for c in str((before.get(step["id"]) or {}).get("reason") or "").split(",") if c}
        if row["status"] == STEP_DONE and attempt > 1 and codes and codes <= set(MECHANICAL_CODES):
            found["mechanical_retry_passed"] = True
        if found:
            events.append({**found, "step_id": step["id"], "attempt": attempt, "reason": row.get("reason"),
                           "subject_sha256": outcome.get("subject_sha256"),
                           "evidence": [{"kind": "wave-result", "record": record_id, "step": step["id"],
                                         "attempt": attempt}]})
    return events


def cost_events(store, items):
    """E8: a session of this wave whose observed cost exceeds twice the high bound the design model projects for its
    own packet (``envelope.project`` with the installed calibration, without retries). Recorded and notified only."""
    engagement, decided = _engaged(store)
    steps = {(item["step"]["id"], item["attempt"]) for item in items}
    if not decided or not steps:
        return []
    from .engagement import envelope
    calibration = {**engagement.data("calibration.json"), "high_retries": 0}
    observed = {(r["record"].get("node_id"), r["record"].get("seat"), r["record"].get("attempt")): r
                for r in store.scan("step-observation")}
    duties = {r["id"]: r["record"].get("duty_units") for r in store.scan("instruction-delivery")
              if r["record"].get("kind") == "instruction-delivery"}
    sessions = {(r["record"].get("node_id"), r["record"].get("seat"), r["record"].get("attempt")): r["record"]
                for r in store.scan("instruction-delivery") if r["record"].get("kind") == "instruction-delivery-session"}
    events = []
    for row in store.scan("step-dispatch"):
        dispatched = row["record"]
        parent_step = dispatched.get("parent_step") or dispatched.get("step_id")
        if (parent_step, dispatched.get("attempt")) not in steps:
            continue
        identity = (dispatched.get("node_id"), dispatched.get("seat"), dispatched.get("attempt"))
        found = observed.get(identity)
        cost = ((found or {}).get("record", {}).get("usage") or {}).get("cost_usd")
        tokens, units = dispatched.get("packet_tokens"), duties.get((sessions.get(identity) or {}).get("delivery"))
        if found is None or type(cost) not in (int, float) or type(tokens) is not int or type(units) is not int:
            continue
        purpose, step_id = dispatched.get("purpose"), str(parent_step)
        checkin = any(step_id == REVIEW_SEATS[p][0] or step_id.startswith(REVIEW_SEATS[p][0] + ".") for p in SEAT_CHECKINS)
        category = ("producer" if purpose == "producer" else "consult" if purpose == "consult" else
                    "checkin" if checkin else "review")
        expected = envelope.project([{"packet_tokens": tokens, "duty_units": units, "category": category,
                                      "conditional": False}], calibration)["high"]["cost_usd"]
        if cost > 2 * expected:
            events.append({"step_id": parent_step, "subject_sha256": None, "cost_usd": cost,
                           "expected_cost_usd": expected, "attempt": dispatched.get("attempt"),
                           "evidence": [{"kind": "step-observation", "record": found["id"]}]})
    return events


def envelope_wave(state, store):
    """The engagement envelope at a wave join (``check_envelope('wave')`` with the independent broker count). A floor
    breach on a completed session raises engagement (E4); the next wave then holds (``engagement_hold``)."""
    engagement, decided = _engaged(store)
    if not decided:
        return None, []
    try:
        check = engagement.check_envelope(store, "wave", broker=broker_counts(store))
    except (ValueError, KeyError, TypeError) as exc:
        raise nodes.RecoveryHold("engagement_refused", f"the engagement envelope cannot be checked: {exc}"[:1500])
    raised = []
    if check.get("hold") and check.get("status") in ("below_floor", "unknown"):
        raised = observe_engagement(store, [{"completed": True, "envelope_status": check["status"], "step_id": None,
                                             "subject_sha256": None,
                                             "evidence": [{"kind": "envelope-check", "record": check["record_id"]}]}])
    return check, raised


def engagement_hold(store):
    """Why the next wave holds, or None: a wave-join envelope check recorded a floor breach on a completed session.
    The breach is an orchestration failure that later evidence cannot undo, so every later wave holds too."""
    engagement = _engagement()
    if engagement is None:
        return None
    held = [row["record"] for row in store.scan(engagement.CHECK)
            if row["record"].get("stage") == "wave" and row["record"].get("hold")]
    if not held:
        return None
    rows = [f"{f.get('floor')} {f.get('seat')}: {f.get('reason')}" for f in
            list(held[-1].get("failures") or ()) + list(held[-1].get("unknown") or ()) if f.get("holds")]
    return f"{ENGAGEMENT_HOLD}: " + ("; ".join(rows) or "an engagement floor failed")[:500]


def envelope_delivery(store):
    """At delivery: the envelope check with the independent broker count, when one is composed. Without one the
    sink makes its own delivery check; the broker floor then stays unestablished and nothing is accepted."""
    engagement, decided = _engaged(store)
    broker = broker_counts(store)
    if not decided or broker is None:
        return None
    return engagement.check_envelope(store, "deliver", broker=broker)


def is_prepare(step):
    """A prepare-phase step: it runs before CHECK-IN 1 (``parameters.phase == "prepare"``)."""
    return (step.get("parameters") or {}).get("phase") == "prepare"


def _selected_route(store):
    """The route the run's selection pinned (its first route record), or None before the selection."""
    rows = store.scan("route")
    return rows[0]["record"].get("route") if rows else None


def _install_plan(store, plan, *, source, revision):
    """Validate and pin a plan; a plan that claims a fixed route must conform to that route's spec.

    A run whose selection pinned a read-only route (``inspect``, ``legacy``) keeps every plan revision free of
    effects, whichever planner wrote it (``routes.inspect.plan_errors``).
    """
    from .routes import RouteSpecError, find, plan_errors
    spec = None
    route = (plan.get("route") or {}).get("id") if type(plan) is dict else None
    if route and route != "judgment":
        try:
            spec = find(route)
        except RouteSpecError as exc:
            raise nodes.RecoveryHold("plan_invalid", f"the plan claims route {route}, which is not installed: {exc}")
    read_only = import_module(__package__ + ".routes.inspect")
    problems = plan_errors(plan, spec) + read_only.plan_errors(plan, route=_selected_route(store))
    if problems:
        raise nodes.RecoveryHold("plan_invalid", "; ".join(problems[:5]))
    blob = _put_json(store, plan)
    record_id = store.append("plan", {"plan_sha256": plan["sha256"], "blob": blob, "source": source,
                                      "revision": revision, "route": plan["route"]["id"],
                                      "open_obligations": len(plan.get("open_obligations") or [])})
    return {"sha256": plan["sha256"], "blob": blob, "record_id": record_id, "route": plan["route"]["id"],
            "revision": revision, "source": source, "steps": [s["id"] for s in plan["steps"]],
            "depends": {s["id"]: list(s.get("depends_on") or []) for s in plan["steps"]},
            "prepare": [s["id"] for s in plan["steps"] if is_prepare(s)],
            "decides": [s["id"] for s in plan["steps"] if s["kind"] == "decide"],
            "waypoints": list(plan.get("waypoints") or []),
            "open_obligations": len(plan.get("open_obligations") or [])}


def ledger_errors(store, transition, gate_name):
    """The ledger's unmet rows for ``transition`` as gate errors (``message`` text, ``entry`` pin)."""
    errors = []
    for row in service("ledger").gate(store, transition) or []:
        row = row if type(row) is dict else {"message": str(row)}
        errors.append({"code": "obligation_unmet", "gate": gate_name, "provider": "controller.ledger",
                       "message": str(row.get("message") or row.get("reason") or row)[:1000],
                       "fix": "satisfy or waive the obligation", "consequence": row.get("consequence"),
                       "pins": [str(row.get("entry") or row.get("id") or row.get("entry_id") or "")]})
    return errors


def require_transition(store, transition):
    """Hold the run (a qualified ending follows) when the ledger leaves ``transition`` unmet."""
    errors = ledger_errors(store, transition, transition)
    store.append("transition", {"transition": transition, "passed": not errors, "errors": deepcopy(errors)[:50]})
    if errors:
        raise nodes.RecoveryHold("obligations_unmet", f"{transition}: " + "; ".join(e["message"] for e in errors)[:1500])


def _status(phase, reason=None, terminal=None, would=None):
    return {"status": {"phase": phase, "terminal": terminal, "reason": reason, "would_make_possible": would}}


# ---- the rows the controller records (recorder map) --------------------------------------------
#
# Each recording point maps a catalogue row to ``(provider, evidence)``. ``evidence(store, context)``
# reads the record that the provider's enforcing action wrote and returns ledger evidence pointing at
# it (``record`` and every ``*_record`` value is a store id that ``store.read`` resolves), or None. A
# row without evidence stays pending, so the transition that requires it holds: nothing is
# satisfied by fiat, and no row moves to another node (the catalogue is not edited here).

# The channels a request may come from: the user's terminal or argument, the operator's file, the harness.
REQUEST_CHANNELS = ("terminal", "operator-file", "harness")
# Records only a routed run writes; none may precede the route (R01).
ROUTED_KINDS = ("route", "plan", "manifest", "wave", "review", "admission", "judgment")
# Commands the command policy must refuse for the run (SW13): a hidden focused command and an unlisted one.
POLICY_PROBES = (("work", "dispatch"), ("unlisted-command",))
POINTER_KEYS = ("record", "authority")


def _pointers(evidence):
    return [v for k, v in evidence.items() if k in POINTER_KEYS or k.endswith("_record")]


def _resolves(store, record_id):
    """Whether ``record_id`` names a record of this run's store (its kind is the id's prefix)."""
    if type(record_id) is not str or record_id.count("-") < 2:
        return False
    try:
        return store.read(record_id.rsplit("-", 2)[0], record_id)["id"] == record_id
    except (ValueError, KeyError):
        return False


def _request_evidence(store, context):
    """CT01: the intake read the one request the entry pinned from the user's, operator's or harness's channel."""
    intake = context["intake"]
    pins = intake["record"]
    requests = store.scan("request")
    if len(requests) != 1 or requests[0]["id"] != pins["request_record_id"]:
        return None
    request = requests[0]["record"]
    if request.get("channel") not in REQUEST_CHANNELS or request.get("sha256") != pins["request_sha256"]:
        return None
    store.get_blob(pins["request_sha256"])  # refuses missing or altered bytes
    return {"record": intake["id"], "request_record": requests[0]["id"], "sha256": pins["request_sha256"],
            "mechanism": "controller.intake"}


def _route_first_evidence(store, context):
    """R01: the intake is pinned and nothing was planned, reviewed, prepared or run before the route."""
    if any(store.scan(kind) for kind in ROUTED_KINDS):
        return None
    return {"record": context["intake"]["id"], "mechanism": "controller.intake"}


def _binding_evidence(store, context):
    """C25, C41, R11: the run directory is bound to this store by real path, device and inode, and the journal
    verifies; an alias, a copy or a moved directory is refused, and a resume continues this run only."""
    if store.check_binding() or store.verify():
        return None
    run = store.scan("run")[0]
    return {"record": run["id"], "sha256": run["digest"], "mechanism": "controller.store"}


def _placement_evidence(store, context):
    """CT03, SW20: the store lies under the operator-configured root (the one the confined launcher withholds),
    apart from the run directory and from every directory the legacy custody variables name."""
    from .store import IGNORED_ENVIRONMENT, _within, store_root
    run = store.scan("run")[0]
    root = Path(os.path.realpath(store.store_root))
    run_dir = Path(os.path.realpath(run["record"]["run_dir"]))
    if root != Path(os.path.realpath(store_root())) or _within(run_dir, root) or _within(root, run_dir):
        return None
    for name in IGNORED_ENVIRONMENT:
        value = os.environ.get(name)
        if value and os.path.isabs(value) and _within(root, Path(os.path.realpath(value))):
            return None
    return {"record": run["id"], "mechanism": "controller.store"}


def _probe_command_policy(store, run_dir):
    """Ask the command policy (checked before any CLI dispatch) about this run's directory; record the answers."""
    from . import command_policy
    probes = []
    for words in POLICY_PROBES:
        found = command_policy.refusal([*words, str(run_dir)]) or {}
        probes.append({"argv": [*words, "<run directory>"], "refused": bool(found), "switch": found.get("switch"),
                       "run_id": found.get("run_id")})
    return store.append("command-policy", {"policy_sha256": hashlib.sha256(command_policy.POLICY.read_bytes())
                                           .hexdigest(), "probes": probes})


def _command_policy_evidence(store, context):
    """SW13: the command policy refuses, for this run's directory, a hidden focused command and an unlisted one."""
    row = store.latest("command-policy")
    probes = (row or {}).get("record", {}).get("probes") or []
    if not probes or any(not p["refused"] or p["switch"] != "SW13" or p["run_id"] != store.run_id for p in probes):
        return None
    return {"record": row["id"], "sha256": row["record"]["policy_sha256"], "mechanism": "controller.command_policy"}


def _frozen_mode(store, context):
    """The run's one operating mode record, authenticated by the authority service, bound to the pinned contract."""
    frozen = getattr(service("authority"), "frozen", None)
    if not callable(frozen):
        return None
    mode = frozen(store)
    contract = context["contract"]
    prompt = contract.get("prompt") if type(contract.get("prompt")) is str else ""
    if (type(mode) is not dict or mode.get("run_id") != store.run_id or mode.get("contract_sha256") != _digest(contract)
            or mode.get("prompt_sha256") != hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            or not _resolves(store, mode.get("id"))):
        return None
    return mode


def _authority_evidence(row, holds):
    """A P06 row: the authority service's own evidence for it, else its authenticated mode record when ``holds``."""
    def evidence(store, context):
        provider = getattr(service("authority"), "ledger_evidence", None)
        provided = (provider(store) or {}).get(row) if callable(provider) else None
        if provided:
            return provided
        mode = _frozen_mode(store, context)
        return {"record": mode["id"], "mechanism": "authority.freeze_mode"} if mode and holds(mode) else None
    evidence.__name__ = f"_authority_evidence_{row}"
    return evidence


def _confine_evidence(row):
    """A P05 row: the confinement admission's evidence for it (``confine.ledger_evidence``)."""
    def evidence(store, context):
        provider = service_function("confine", "ledger_evidence", "ledger_evidence")
        return (provider(store) or {}).get(row) if provider else None
    evidence.__name__ = f"_confine_evidence_{row}"
    return evidence


def _check_layout(store, run_dir):
    """P12's layout question about this run's directory (``routes.legacy.check``); its answer is kept in the store."""
    from .routes import legacy
    return store.append("legacy-layout", {"view": legacy.check(run_dir)})


def _layout_evidence(row):
    """L01, SW26: P12's check finds this run's own intact layout (the epoch-two inputs contract the intake pinned,
    no run-root contract); L01 also needs the entry's admission of a new directory (``legacy.admit_new_run``)."""
    def evidence(store, context):
        latest = store.latest("legacy-layout")
        view = (latest or {}).get("record", {}).get("view") or {}
        facts = view.get("evidence") or {}
        if (view.get("layout") != "controller" or view.get("controller_run") != store.run_id
                or view.get("new_science") is not True or facts.get("contract") != "inputs/task_contract.json"
                or facts.get("agent_layer_epoch") != 2
                or facts.get("contract_sha256") != context["intake"]["record"]["contract_blob"]):
            return None
        found = {"record": latest["id"], "mechanism": "routes.legacy.check"}
        if row == "L01":
            admitted = store.latest("legacy-admission")
            if admitted is None or admitted["record"].get("layout") != "absent" or admitted["record"].get("refusal"):
                return None
            found["admission_record"] = admitted["id"]
        return found
    evidence.__name__ = f"_layout_evidence_{row}"
    return evidence


def _tripwire_evidence(store, context):
    """SW15: the controller process declared itself for this run, so the agent tripwire blocks in it whatever
    ``RAVEL_AGENT_TRIPWIRE`` says: the entry's host observation, and this process still blocking. A blocking
    mode is any but off and ``report`` (a controller process reports ``block``, or the ``1`` it was given)."""
    from ..workflow import agent_tripwire
    latest = store.latest("host-observation")
    tripwire = (latest or {}).get("record", {}).get("tripwire") or {}
    lenient = (*agent_tripwire.OFF, "report")
    if (tripwire.get("mode") in lenient or tripwire.get("declared") != store.run_id
            or tripwire.get("controller_process") is not True or not agent_tripwire.controller_process()
            or agent_tripwire.effective_mode()[0] in lenient):
        return None
    return {"record": latest["id"], "mechanism": "agent_tripwire.declare_controller_process"}


def _route_evidence(store, context):
    """R02: the route record of the data-driven selection and the table rows it evaluated in order (a
    supplied-study route is selected only when its row's predicate holds for the supplied inputs)."""
    row = store.read("route", context["route_record"])
    decision = _json_blob(store, row["record"]["evidence_blob"])
    if decision.get("route") != row["record"]["route"] or not decision.get("evidence"):
        return None
    return {"record": row["id"], "sha256": row["record"]["evidence_blob"], "mechanism": "routes.select"}


INTAKE_RECORDERS = {
    "CT01": ("P01", _request_evidence),
    "R01": ("P01", _route_first_evidence),
    "C25": ("P01", _binding_evidence),
    "C41": ("P01", _binding_evidence),
    "R11": ("P01", _binding_evidence),
    "CT03": ("P01", _placement_evidence),
    "SW20": ("P01", _placement_evidence),
    "SW13": ("P01", _command_policy_evidence),
    "A04": ("P06", _authority_evidence("A04", lambda mode: mode.get("mode") in ("physicist-in-the-loop",
                                                                               "autonomous"))),
    "CT04": ("P06", _authority_evidence("CT04", lambda mode: type(mode.get("operator_source")) is str
                                        and mode.get("parent") is None)),
    "SW25": ("P06", _authority_evidence("SW25", lambda mode: type((mode.get("provider_policy") or {})
                                                                  .get("policy_sha256")) is str)),
    "SW23": ("P05", _confine_evidence("SW23")),
    "SW29": ("P05", _confine_evidence("SW29")),
    "SW16": ("P05", _confine_evidence("SW16")),
    "L01": ("P12", _layout_evidence("L01")),
    "SW26": ("P12", _layout_evidence("SW26")),
    "SW15": ("P14", _tripwire_evidence),
}
ROUTE_RECORDERS = {"R02": ("P10", _route_evidence)}
RECORDERS = {"controller.intake": INTAKE_RECORDERS, "controller.route_select": ROUTE_RECORDERS}


def _record_rows(store, point, **context):
    """Record each pending row of recording point ``point`` whose provider shows evidence (``RECORDERS``).

    Returns ``{row: reason}`` for the rows left pending; the reasons and the recorded rows are kept in a
    ``ledger-evidence`` record, so the hold that follows says what is missing.
    """
    ledger = service("ledger")
    if not all(callable(getattr(ledger, name, None)) for name in ("pending", "record_many", "instance_key")):
        return {}  # a ledger stand-in without the row interface records nothing
    open_keys = set(ledger.pending(store, stage="intake"))
    changes, recorded, missing = [], [], {}
    for row, (provider, evidence) in RECORDERS[point].items():
        key = ledger.instance_key(row, store.run_id, {})
        if key not in open_keys:
            continue
        try:
            found = evidence(store, context)
            reason = "its provider shows no evidence"
        except (ValueError, KeyError, OSError) as exc:  # the provider refused (a missing or failed record)
            found, reason = None, f"{type(exc).__name__}: {exc}"
        if found and not all(_resolves(store, p) for p in _pointers(found) or [None]):
            found, reason = None, "its evidence names no record of this run"
        if found:
            changes.append((row, provider, (key, "satisfied", {**found, "provider": provider, "point": point})))
        else:
            missing[row] = f"{provider}: {reason}"[:500]
    return _apply_rows(store, point, changes, missing)


def _apply_rows(store, point, changes, missing):
    """Record ``changes`` (``(row, provider, (key, status, evidence))``) as one ledger event and keep a
    ``ledger-evidence`` record of what was recorded and what stays pending (``missing``: ``{row: reason}``)."""
    ledger = service("ledger")
    recorded = []
    refused = getattr(ledger, "LedgerError", ())
    try:
        if changes:
            ledger.record_many(store, [change for _, _, change in changes])
        recorded = [row for row, _, _ in changes]
    except refused:
        # One refused evidence object refuses the whole event: record the rows one by one, and leave each
        # refused row pending with the ledger's reason.
        for row, provider, change in changes:
            try:
                ledger.record_many(store, [change])
                recorded.append(row)
            except refused as exc:
                missing[row] = f"{provider}: the ledger refused its evidence: {exc}"[:500]
    store.append("ledger-evidence", {"point": point, "recorded": recorded, "pending": missing})
    return missing


def _row_ledger():
    """The ledger when it offers the row interface (``pending``, ``record_many``); None for a stand-in."""
    ledger = service("ledger")
    return ledger if all(callable(getattr(ledger, n, None)) for n in ("pending", "record_many")) else None


# The authority's (P06) rows each check-in discharges, by catalogue node. The controller records them only from the
# record the authority service authenticates for the current pins, at the authority point, before the gate checks
# the transition; the GATE row stays with ``ledger.decide`` in the acting node.
CHECKIN_ROWS = {"checkin1": {"authority.ci1": ("CHECKIN-1", "A01", "C05", "C07", "C15")},
                "checkin2": {"authority.ci2": ("A08", "C16", "C17", "CHECKIN-2")},
                "checkin3": {"authority.ci3": ("CHECKIN-3",), "authority.final": ("C42", "CHECKIN-final")},
                # A deviation (a replan or a recovery) is a typed check-in decided by the authority service.
                "deviation": {"authority.deviation": ("C31",), "controller.deviation": ("CHECKIN-deviation",)},
                # A question answered, or its conservative default (plan-declared, or a reasoned machine assumption)
                # taken after the operator's wait bound: the ask row of a judgment-planned run (JR08).
                "escalate": {"judgment.ask": ("JR08",)}}


class _Unverifiable(ValueError):
    """The authority service offers no authenticated reader for this decision."""


class _GrantsTooMuch(ValueError):
    """An authenticated final disposition that claims effects or review credit."""


def authenticated(store, kind, record_id, pins):
    """``(record, mechanism)``: authority record ``record_id`` as the authority service authenticates it for a
    current ``kind`` decision on ``pins``. ``verify`` for a decision that authorizes effects; ``disposition`` for
    the final disposition, which must grant no effect and no review credit. Raises the service's refusal (a
    ``ValueError``); no raw record body is ever read as authority."""
    authority = service("authority")
    mechanism = "disposition" if kind == "final" else "verify"
    reader = getattr(authority, mechanism, None)
    if not callable(reader):
        raise _Unverifiable(f"the authority service offers no authenticated {kind} reader ({mechanism})")
    record = reader(store, record_id, kind=kind, subject=pins)
    if type(record) is not dict:
        raise ValueError(f"the authority service returned no {kind} record")
    if kind == "final" and (record.get("authorizes_effects") is not False or record.get("review_credit") is not False):
        raise _GrantsTooMuch("a final disposition grants no effects and no review credit")
    return record, "authority." + mechanism


def _record_checkin_rows(store, name, kind, record_id, pins, accepted):
    """Record the authority's rows of check-in ``name`` (``CHECKIN_ROWS``) once the authority service
    authenticates ``record_id`` for the current ``pins`` and its decision lets the transition proceed. A refused,
    revoked, stale or negative decision records nothing: the rows stay pending and the gate holds."""
    ledger = _row_ledger()
    if ledger is None or name not in CHECKIN_ROWS:
        return None
    try:
        record, mechanism = authenticated(store, kind, record_id, pins)
        reason = None if record.get("decision") in accepted else f"the {kind} decision is {record.get('decision')!r}"
    except Exception as exc:  # the authority service's refusal
        mechanism, reason = None, f"{type(exc).__name__}: {exc}"
    for node, rows in CHECKIN_ROWS[name].items():
        keys = [k for k in ledger.pending(store, node=node) if k.split("@", 1)[0] in rows]
        changes, missing = [], {}
        for key in keys:
            row = key.split("@", 1)[0]
            if reason is None and _resolves(store, record_id):
                changes.append((row, "P06", (key, "satisfied", {"authority": record_id, "mechanism": mechanism,
                                                                 "provider": "P06", "point": node})))
            else:
                missing[row] = f"P06: {reason or 'the authority record names no record of this run'}"[:500]
        _apply_rows(store, node, changes, missing)
    return reason


def _record_operation_commit(store, kind, record_id, pins, plan, accepted):
    """Commit operation sources at authenticated approval, or record their typed absence.

    Existing inputs and executable/script bytes are pinned now. Prospective outputs
    bind their approved producer; custody pins their actual bytes at each effect.
    """
    ledger = _row_ledger()
    if ledger is None:
        return
    try:
        record, _ = authenticated(store, kind, record_id, pins)
    except Exception:  # the authority service's refusal: nothing is recorded
        return
    if record.get("decision") not in accepted:
        return
    keys = [k for k in ledger.pending(store, node="authority.ci1") if k.split("@", 1)[0] == "C18"]
    if any(s.get("operation") or s.get("kind") in LAUNCH_KINDS for s in plan.get("steps") or ()):
        from .confine import commitments
        try:
            commitment = commitments.create(store, plan, store.run_dir)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise nodes.RecoveryHold("operation_input_commitment_refused", str(exc)[:1500]) from None
        _apply_rows(store, "authority.ci1", [("C18", "P05", (key, "satisfied", {
            "authority": record_id, "record": commitment, "sha256": plan.get("sha256"),
            "mechanism": "confine.commitments.create"})) for key in keys], {})
        return
    _apply_rows(store, "authority.ci1", [("C18", "P01", (key, "not_applicable", {
        "reason": "not_applicable:plan_declares_no_operation_step", "authority": record_id,
        "sha256": plan.get("sha256")})) for key in keys], {})


def _record_mechanism_rows(store, point):
    """Record the authority's mechanism rows its own evidence shows (``authority.ledger_evidence``: the frozen
    mode, controls, steering, R3, deviation and terminal records it authenticated), at authority points and stop,
    deviation and escalation handling. A row without evidence stays pending; nothing is satisfied by fiat."""
    ledger = _row_ledger()
    provider = getattr(service("authority"), "ledger_evidence", None)
    if ledger is None or not callable(provider):
        return None
    try:
        evidence = provider(store) or {}
    except Exception as exc:  # the authority could not authenticate its own history: nothing is recorded
        store.append("ledger-evidence", {"point": point, "recorded": [],
                                         "pending": {"*": f"P06: {type(exc).__name__}: {exc}"[:500]}})
        return None
    changes, missing = [], {}
    for key in ledger.pending(store):
        row = key.split("@", 1)[0]
        found = evidence.get(row)
        if found is None:
            continue
        if type(found) is not dict or not _pointers(found) or not all(_resolves(store, p) for p in _pointers(found)):
            missing[row] = "P06: its evidence names no record of this run"
            continue
        changes.append((row, "P06", (key, "satisfied", {**found, "provider": "P06", "point": point})))
    if changes or missing:
        _apply_rows(store, point, changes, missing)
    return None


# ---- route adapters --------------------------------------------------------------------------

def adapter(state, store=None):
    """The route adapter module of the current plan's route, or None. A judgment-route plan's adapter is the
    judgment package's check-in part (``judgment.checkins``: its CHECK-IN 1 sections, flags and content rows).

    A route whose adapter is not installed holds (``route_adapter_missing``): its hooks are never skipped. An
    installed adapter's own import error propagates."""
    route = (state.get("plan") or {}).get("route") or (state.get("route") or {}).get("id")
    if not route:
        return None
    if route == "judgment":
        return import_module(__package__ + ".judgment.checkins")
    from .routes import adapter_module, find, RouteSpecError
    from .routes.select import RouteAdapterMissing
    try:
        return adapter_module(find(route))
    except RouteSpecError:
        return None
    except RouteAdapterMissing as exc:
        raise nodes.RecoveryHold(exc.reason, f"install the route adapter: {exc}"[:1500]) from None


def adapter_context(state, store):
    contract, reading, _ = _intake_records(state, store)
    return {"store": store, "run_dir": _run_dir(state), "plan": current_plan(state, store), "state": deepcopy(dict(state)),
            "reading": reading, "contract": contract}


def _adapter_errors(values, gate_name):
    errors = []
    for value in values or []:
        if type(value) is dict:
            errors.append({"code": str(value.get("code") or "route_refused"), "gate": gate_name,
                           "provider": "controller.route", "message": str(value.get("message") or value)[:1000],
                           "fix": str(value.get("fix") or ""), "pins": [str(p) for p in value.get("pins") or []]})
        else:
            errors.append({"code": "route_refused", "gate": gate_name, "provider": "controller.route",
                           "message": str(value)[:1000], "fix": "", "pins": []})
    return errors


# ---- intake ---------------------------------------------------------------------------------

def _write_run_intake(run_dir, prompt, output_workspace=None):
    """Draft the route records and write the run directory's reading copies (the legacy intake path).

    Declared output paths bind to ``output_workspace``, the directory the entry recorded when the
    request was received; a run directory that would itself violate them holds before any write.
    """
    from .. import cli
    from ..validation.validate_task_contract import validate as validate_task_contract
    from ..workflow import output_contract
    from ..workflow.capability_routing import plan as recovery_plan
    contract, reading, label = cli._draft_route(prompt, None, None, output_workspace=output_workspace)
    conflicts = output_contract.placement_conflicts(output_contract.rows(contract), run_dir)
    if conflicts:
        raise nodes.RecoveryHold("output_contract_placement", "; ".join(conflicts)[:2000])
    contract_errors = validate_task_contract(contract)
    recovery = recovery_plan(prompt, contract=contract, reading=reading)
    request_plan, plan_error = None, None
    try:
        request_plan, _ = cli._draft_plan(reading, contract)
    except ValueError as exc:
        plan_error = str(exc)[:2000]
    inputs = run_dir / "inputs"
    private_files.mkdir(inputs)
    private_files.write(run_dir / "request.txt", prompt.encode("utf-8"))
    intake_error, layout = None, "minimal"
    if not contract_errors and request_plan is not None:
        try:
            from ..workflow import gate_wiring
            gate_wiring.initialize_steering(run_dir, route="run-initialization")
            cli._write_intake(run_dir, prompt, contract, recovery, reading=reading, plan=request_plan, session_id="")
            gate_wiring.record_run_init(run_dir)
            layout = "epoch-two"
        except (OSError, ValueError) as exc:
            intake_error = str(exc)[:2000]
    if layout == "minimal":
        # The request, reading and draft contract stay readable; the controller routes it as judgment. The
        # contract is the controller's own (agent-layer epoch two): an inputs contract without it is the
        # epoch-one layout, which the decision gate treats as predating the agent layer (SW26).
        contract = {**contract, "agent_layer_epoch": 2}
        private_files.write(inputs / "reading.json", (json.dumps(reading, indent=2, allow_nan=False) + "\n").encode())
        private_files.write(inputs / "task_contract.json", (json.dumps(contract, indent=2, allow_nan=False) + "\n").encode())
        private_files.write(inputs / "capability_recovery.json", (json.dumps(recovery, indent=2, allow_nan=False) + "\n").encode())
    contract_bytes = (inputs / "task_contract.json").read_bytes()
    reading_bytes = (inputs / "reading.json").read_bytes()
    return {"contract": json.loads(contract_bytes), "reading": json.loads(reading_bytes),
            "contract_bytes": contract_bytes, "reading_bytes": reading_bytes,
            "label": json.loads(json.dumps(label, default=str)) if label is not None else None,
            "contract_errors": list(contract_errors), "plan_error": plan_error, "intake_error": intake_error,
            "layout": layout}


def _freeze_mode(store, contract, run_dir):
    freeze = service("authority").freeze_mode
    try:
        accepts = "run_dir" in inspect.signature(freeze).parameters
    except (TypeError, ValueError):
        accepts = False
    return freeze(store, contract, run_dir=run_dir) if accepts else freeze(store, contract)


def _output_contract_pins(contract):
    """The output-contract rows intake bound (their workspace and baselines), as the run state retains them.

    They live in the pinned contract blob, so a resumed or re-entered intake re-reads the same
    binding and never adopts entries created after the request was received.
    """
    from ..workflow import output_contract
    rows = output_contract.rows(contract)
    if not rows:
        return None
    workspaces = sorted({str((r["criteria"][output_contract.CRITERIA_KEY] or {}).get("workspace")) for r in rows})
    return {"rows": [r["id"] for r in rows], "rows_sha256": _digest(rows), "workspaces": workspaces}


def observe_environment(store, run_dir):
    """The run's environment profile (``environment-profile``), observed once by the confinement package from the
    existing doctor-census, batch, sandbox and resource probes; None without a confinement package (every tool's
    availability is then unobserved, never assumed)."""
    observe = service_function("confine", "profile", "observe")
    if observe is None:
        return None
    return observe(store, run_dir=str(run_dir))


# Controller-written files under ``inputs/`` that a supplied input may not displace.
CONTROLLER_INPUT_NAMES = ("reading.json", "task_contract.json", "capability_recovery.json")


def stage_supplied_inputs(run_dir, rows):
    """Copy each supplied input file to ``inputs/<name>`` of the run, pinned by the digest the entry recorded.

    A plan step reads a supplied file as the run input ``inputs/<name>`` (custody pins it by digest at dispatch;
    an operation commitment pins it at approval), so the bytes the operator supplied are staged once, at intake,
    from the entry's own record of them. A supplied directory (a legacy or controller run) is classified, not
    staged. Refused, typed: two supplied files of one name, a name the controller writes itself, a staged copy
    whose bytes differ from the record (a changed approved input), or a link anywhere on the copy's path.
    Returns the staged rows ``[{name, artifact, sha256, source}]``.
    """
    import shutil
    inputs = Path(run_dir) / "inputs"
    private_files.mkdir(inputs)
    staged, names = [], set()
    for row in rows or ():
        if type(row) is not dict or type(row.get("path")) is not str or type(row.get("sha256")) is not str:
            continue  # a directory or an unreadable entry: classified by the entry, never staged
        source = Path(row["path"])
        name = source.name
        if name in names or name in CONTROLLER_INPUT_NAMES or name != os.path.basename(name) or name.startswith("."):
            raise nodes.RecoveryHold("supplied_input_collision",
                                     f"supplied input {name!r} collides with another input of this run")
        names.add(name)
        target = inputs / name
        if target.is_symlink() or any(p.is_symlink() for p in target.parents if p.is_relative_to(Path(run_dir))):
            raise nodes.RecoveryHold("supplied_input_linked", f"inputs/{name} must not be reached through a link")
        if not target.exists():
            if source.is_symlink() or not source.is_file():
                raise nodes.RecoveryHold("supplied_input_missing", f"supplied input {source} is not a regular file")
            with source.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != row["sha256"]:
                    raise nodes.RecoveryHold("supplied_input_changed",
                                             f"supplied input {source} differs from the bytes the entry recorded")
            partial = inputs / (name + ".staging")
            private_files.copy(source, partial)
            os.replace(partial, target)
        with target.open("rb") as stream:
            found = hashlib.file_digest(stream, "sha256").hexdigest()
        if found != row["sha256"]:
            raise nodes.RecoveryHold("supplied_input_changed",
                                     f"inputs/{name} differs from the supplied bytes the entry recorded")
        staged.append({"name": name, "artifact": f"inputs/{name}", "sha256": found, "source": str(source),
                       **{k: row[k] for k in ("restricted", "data_classification") if k in row}})
    return staged


def intake(state):
    """Read the request bytes from the store (never from a worker), write the intake and pin it."""
    store = _store(state)
    register = getattr(service("authority"), "register_recorders", None)
    if callable(register):
        register(store)  # composition evidence must precede the first intake record
    if state.get("request"):
        raise nodes.RecoveryHold("request_injected", "the request comes from the channel the controller pinned; "
                                 "a request field in the run input is refused")
    done = store.latest("intake")
    if done is None:
        request = store.latest("request")
        if request is None:
            raise nodes.RecoveryHold("request_missing", "start the run through ravel drive or ravel ask")
        raw = store.get_blob(request["record"]["sha256"])
        try:
            prompt = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise nodes.RecoveryHold("request_not_utf8", "supply the request as UTF-8 text") from exc
        if not prompt.strip():
            raise nodes.RecoveryHold("request_blank", "the request is blank")
        workspace = request["record"].get("workspace")
        written = _write_run_intake(_run_dir(state), prompt,
                                    output_workspace=workspace if type(workspace) is str else None)
        staged = stage_supplied_inputs(_run_dir(state), _supplied(store))
        record = {"request_record_id": request["id"], "request_sha256": request["record"]["sha256"],
                  "supplied": staged,
                  "channel": request["record"]["channel"],
                  "contract_blob": store.put_blob(written["contract_bytes"]),
                  "reading_blob": store.put_blob(written["reading_bytes"]),
                  "label": written["label"], "contract_errors": written["contract_errors"],
                  "plan_error": written["plan_error"], "intake_error": written["intake_error"],
                  "layout": written["layout"], "task_mode": written["contract"].get("task_mode")}
        done = store.read("intake", store.append("intake", record))
    pins = done["record"]
    # A resumed run finds its staged supplied inputs unchanged, or holds.
    stage_supplied_inputs(_run_dir(state), _supplied(store))
    observe_environment(store, _run_dir(state))
    contract = _json_blob(store, pins["contract_blob"])
    reading = _json_blob(store, pins["reading_blob"])
    mode = _freeze_mode(store, contract, _run_dir(state))
    pin = _autonomy("pin_instructions")
    if callable(pin):
        pin(store, _run_dir(state), mode)  # the declared instruction document, pinned at run start (N3)
    ledger = service("ledger")
    rows = ledger.materialise(store, "intake", {
        "run_id": store.run_id, "task_mode": pins.get("task_mode"), "request_sha256": pins["request_sha256"],
        "deliverables": [d["id"] for d in reading.get("deliverables") or () if type(d) is dict and d.get("id")]})
    _probe_command_policy(store, _run_dir(state))
    _check_layout(store, _run_dir(state))
    _record_rows(store, "controller.intake", intake=done, contract=contract, run_dir=_run_dir(state), mode=mode)
    require_transition(store, "intake->route_select")
    request = {"sha256": pins["request_sha256"], "channel": pins["channel"],
               "record_id": pins["request_record_id"], "intake_record_id": done["id"],
               "reading_sha256": pins["reading_blob"], "contract_sha256": pins["contract_blob"]}
    retained = _output_contract_pins(contract)
    if retained:
        request["output_contract"] = retained
    return {"request": request,
            "mode": {k: deepcopy(v) for k, v in (mode or {}).items() if k in MODE_KEYS},
            "ledger": {"intake_rows": len(rows or []), **(ledger.summary(store) or {})},
            **_status("intake", "request, reading, contract and mode pinned")}


# ---- route and plan -------------------------------------------------------------------------

def route_select(state):
    from . import routes
    store = _store(state)
    contract, reading, _ = _intake_records(state, store)
    decision = routes.select(contract, reading, _supplied(store))
    evidence_blob = _put_json(store, decision)
    record_id = store.append("route", {"route": decision["route"], "row": decision.get("row"),
                                       "spec_sha256": decision.get("spec_sha256"),
                                       "version": decision.get("version"), "evidence_blob": evidence_blob})
    _record_rows(store, "controller.route_select", route_record=record_id)
    require_transition(store, "route_select->plan")
    return {"route": {"id": decision["route"], "row": decision.get("row"), "spec_sha256": decision.get("spec_sha256"),
                      "version": decision.get("version"), "record_id": record_id, "evidence_blob": evidence_blob},
            **_status("route", f"route {decision['route']}")}


def _route_branch(state):
    return "judgment" if (state.get("route") or {}).get("id") == "judgment" else "fixed"


def need_obligations(state, store, plan):
    """A fixed route's plan with every capability need it leaves unserved as an open obligation, so the judgment
    graph composes the rest with the need's best available tool (R05); a need-check problem that names no need is
    a route spec defect (``CompileError``)."""
    from ..workflow import tool_selection
    from .routes import CompileError, plan_sha256
    record, problems = tool_selection.check(plan, **tool_selection_inputs(state, store))
    tied = [p for row in record["needs"] for p in row["problems"]]
    untied = [p for p in problems if p not in tied]
    if untied:
        raise CompileError("the route plan names capability needs the census does not declare: " + "; ".join(untied)[:1500])
    rows = [row for row in record["needs"] if row["problems"]]
    if not rows:
        return plan
    plan = deepcopy(plan)
    plan["open_obligations"] = list(plan.get("open_obligations") or []) + [
        {"kind": "capability_need", "id": "need:" + row["need"], "reason": "; ".join(row["problems"])[:1000],
         "best": row["best"], "source": "tool-selection"} for row in rows]
    plan["sha256"] = plan_sha256(plan)
    return plan


def offline_sources(store, plan):
    """With an environment profile that records no network egress, a route's publication acquisitions read local
    sources only: the resource census consults its local rungs and the site mirror, the data acquisition reads the
    mirror's copy of the record. Each such step records the switch (``parameters.source_mode``) with the profile
    record it follows; the controller's acquisition admits these forms only under that profile (E16)."""
    from .routes import plan_sha256
    row = store.latest("environment-profile")
    profile = row["record"] if row else {}
    network = profile.get("network") or {}
    if network.get("egress") != "none":
        return plan
    mirror = (profile.get("sources") or {}).get("mirror")
    plan, changed = deepcopy(plan), False
    for step in plan["steps"]:
        launch = (step.get("parameters") or {}).get("launch") or {}
        argv = list(launch.get("argv") or [])
        if step.get("kind") != "acquire" or step.get("operation") != "acquire-published" or "--offline" in argv:
            continue
        if "--fetch-published-data" in argv:
            tail = ["--offline"] + (["--offline-mirror", mirror] if mirror else [])
        elif "--reading" in argv:
            tail = ["--offline"] + (["--mirror", mirror] if mirror else [])
        else:
            continue
        step["parameters"]["launch"]["argv"] = argv + tail
        step["parameters"]["source_mode"] = {
            "mode": "local", "mirror": mirror, "profile_record": row["id"],
            "reason": f"the environment profile records no network egress ({network.get('source') or 'probe'})"}
        changed = True
    if changed:
        plan["sha256"] = plan_sha256(plan)
    return plan


def plan_compile(state):
    from . import routes
    from .routes.select import RouteAdapterMissing, spec_sha256
    store = _store(state)
    route = state["route"]
    contract, reading, _ = _intake_records(state, store)
    revision = (state.get("plan") or {}).get("revision", -1) + 1
    try:
        spec = routes.find(route["id"])
        if route.get("spec_sha256") and route["spec_sha256"] != spec_sha256(spec):
            raise routes.RouteSpecError("the installed route spec changed after route selection")
        plan = routes.compile(spec, reading, contract, supplied=_supplied(store), revision=revision,
                              run_id=store.run_id)
        plan = need_obligations(state, store, plan)
        plan = offline_sources(store, plan)
    except RouteAdapterMissing as exc:  # the route cannot run without its adapter's hooks; judgment never replaces it
        raise nodes.RecoveryHold(exc.reason, f"install the route adapter: {exc}"[:1500]) from None
    except (routes.CompileError, routes.RouteSpecError) as exc:
        # The judgment route is pinned by the record that names it, so its steps are admitted (route_not_pinned).
        record_id = store.append("route", {"route": "judgment", "reason": "compile-failed", "error": str(exc)[:2000],
                                           "from": route["id"]})
        return {"route": {**route, "id": "judgment", "from": route["id"], "reason": "compile-failed",
                          "record_id": record_id},
                "loop": {"candidate": None}, **_status("plan", "route spec did not compile; judgment plans it")}
    if plan.get("open_obligations"):
        # A mixed request: the route covers part of it. The judgment graph keeps the covered part (R05).
        candidate = _put_json(store, plan)
        record_id = store.append("route", {"route": "judgment", "reason": "open-obligations", "from": route["id"],
                                           "candidate_blob": candidate, "open": len(plan["open_obligations"])})
        return {"route": {**route, "id": "judgment", "from": route["id"], "reason": "open-obligations",
                          "record_id": record_id},
                "loop": {"candidate": candidate}, **_status("plan", "open obligations; judgment composes the rest")}
    # Preparation must fit the same wall-time envelope as the subsequent work.
    # Execution facts and event requirements are resolved before CHECK-IN 1.
    from .routes.budgeting import BudgetInfeasible, narrow_plan
    envelope = _plan_budget_envelope(state)
    try:
        plan = narrow_plan(plan, {k: v for k, v in envelope.items() if k == 'wall_seconds'})
    except BudgetInfeasible as exc:
        store.append('plan-budget-refusal', {'reason': exc.code, 'evidence': exc.evidence, 'remedy': exc.remedy})
        raise nodes.RecoveryHold(exc.code, str(exc)) from None
    return {"plan": _install_plan(store, plan, source="route", revision=revision),
            **_status("plan", f"plan compiled from route {route['id']}")}


def _after_compile(state):
    return "planned" if (state.get("route") or {}).get("id") != "judgment" and (state.get("plan") or {}).get("blob") \
        else "judgment"


_CHILDREN: dict = {}


def _child(state, graph_id):
    from ..workflow import graph_substrate
    meta = state["meta"]
    key = (meta["scope_root"], graph_id, graph_registry.get(graph_id)["version"])
    if key not in _CHILDREN:
        row = graph_registry.get(graph_id)
        ctx = graph_substrate.BuildContext(scope_root=Path(meta["scope_root"]), graph_id=graph_id,
                                           version=row["version"], instance=deepcopy(meta.get("instance") or {}),
                                           row=row)
        _CHILDREN[key] = graph_substrate.build(graph_id, ctx, checkpointer=None)
    return _CHILDREN[key]


def _invoke(state, graph_id, view, segment):
    meta = nodes._meta(state)
    row = graph_registry.get(graph_id)
    child_meta = {"graph_id": graph_id, "version": row["version"], "instance": deepcopy(meta.get("instance")),
                  "scope_root": meta["scope_root"], "path": nodes.invocation(meta, segment)}
    found = nodes._invoke_child(_child(state, graph_id), {**view, "meta": child_meta}, "child")
    return found["results"]["child"]


def frozen_preferences(mode):
    """The agent preferences the run's mode record froze at intake when they are an agent-preferences document,
    else None. Nothing else supplies them (a run-tree copy is never read) and no default replaces them: a worker
    seat without them holds (``agent_preferences_missing``)."""
    found = (mode or {}).get("agent_preferences")
    if (type(found) is not dict or found.get("kind") != "agent-preferences" or found.get("schema_version") != 1
            or type(found.get("transport_preference")) is not list):
        return None
    return deepcopy(found)


def _context(state, store, step=None, **extra):
    """The context a child graph runs a step or a plan under: the run, its frozen mode and the frozen agent
    preferences every worker seat is filled from (``agent_preferences``). With a pinned plan it carries the GO pins
    the plan's full and scan effects execute under (``go_pins``, the waypoint digests CHECK-IN 2 binds) and whether
    they need a GO at all (``requires_go``: the plan has a waypoint or declares CHECK-IN 2); with ``step``, the
    stage its effect is admitted under (``stage``)."""
    run = state["run"]
    context = {"run_id": run["run_id"], "run_dir": run["run_dir"], "store_root": run["store_root"],
               "plan_sha256": (state.get("plan") or {}).get("sha256"), "mode": deepcopy(state.get("mode") or {}),
               "agent_preferences": frozen_preferences(state.get("mode")), "unattended": bool(run.get("unattended"))}
    if (state.get("plan") or {}).get("applied_sha256"):
        # The applied engagement view the step is dispatched under, beside the scientific digest its authority covers.
        context["applied_sha256"] = state["plan"]["applied_sha256"]
    if (state.get("plan") or {}).get("blob"):
        plan = current_plan(state, store)
        waypoints = list(plan.get("waypoints") or [])
        context["go_pins"] = waypoint_pins(waypoints, state.get("steps") or {})
        context["requires_go"] = bool(waypoints) or any(type(c) is dict and c.get("id") == "checkin2"
                                                        for c in plan.get("checkins") or ())
    if step is not None:
        context["stage"] = step_stage(step)
    return {**context, **extra}


def judgment_plan(state):
    """The judgment graph frames and decomposes the request into a typed plan (or replans it)."""
    store = _store(state)
    previous = state.get("plan") or {}
    revision = previous.get("revision", -1) + 1
    candidate = (state.get("loop") or {}).get("candidate")
    correction = (state.get("loop") or {}).get("correction")  # a plan review's correction round: its pinned findings
    view = {"request": deepcopy(state.get("request") or {}),
            "plan": _json_blob(store, candidate) if candidate else (current_plan(state, store) if previous else None),
            "context": _context(state, store, purpose="plan", revision=revision,
                                route=deepcopy(state.get("route") or {}),
                                **({"correction": deepcopy(correction)} if correction else {}))}
    found = _invoke(state, JUDGMENT_GRAPH, view, {"judgment": f"plan-{revision}"})
    plan = (found.get("results") or {}).get("plan")
    if found.get("outcome") != "ok" or type(plan) is not dict:
        raise nodes.RecoveryHold("judgment_plan_failed", f"the judgment graph returned {found.get('outcome')}: "
                                 + str((found.get("status") or {}).get("reason")))
    return {"plan": _install_plan(store, plan, source="judgment", revision=revision), "loop": {"candidate": None},
            **_status("plan", "plan from the judgment graph")}


TOOL_ROW = "CT09"  # every capability need of the plan is served by its best available tool, or a typed reason
TOOL_NODE = "controller.plan"


def request_text(state, store):
    """The verbatim request text the run pinned at intake (None when unreadable)."""
    digest = (state.get("request") or {}).get("sha256")
    try:
        return store.get_blob(digest).decode("utf-8") if type(digest) is str else None
    except (ValueError, OSError, UnicodeDecodeError):
        return None


def tool_selection_inputs(state, store):
    """What the capability-need check reads: the pinned profile (record id, document), supplied inputs, the
    request's derived label, reading and request text. Nothing here comes from a worker."""
    profile = store.latest("environment-profile")
    _, reading, intake = _intake_records(state, store)
    return {"profile": profile["record"] if profile else None, "profile_record": profile["id"] if profile else None,
            "supplied": _supplied(store), "label": intake.get("label"), "reading": reading,
            "request_text": request_text(state, store)}


def record_tool_selection(state, store, plan):
    """Check the plan's capability needs against the run's profile, keep the ``tool-selection`` record and record
    CT09 from it: satisfied when every need is served by its best available candidate or a typed reason, violated
    (fail closed) when an installed plan fails the check. Returns the record id."""
    from ..workflow import tool_selection
    inputs = tool_selection_inputs(state, store)
    record, problems = tool_selection.check(plan, **inputs)
    record_id = store.append(tool_selection.RECORD, record)
    ledger = _row_ledger()
    current = getattr(ledger, "current", None) if ledger is not None else None
    if not callable(current):
        return record_id
    entries = [row for row in current(store, node=TOOL_NODE) if row.get("id") == TOOL_ROW]
    changes, missing = [], {}
    for row in entries:
        if problems:
            if row.get("status") in ("pending", "satisfied"):
                changes.append((TOOL_ROW, "P01", (row["entry"], "violated", {
                    "reason": "the installed plan fails the capability-need check: " + "; ".join(problems)[:800],
                    "record": record_id, "sha256": plan.get("sha256"), "mechanism": "tool_selection.check"})))
            else:
                missing[TOOL_ROW] = f"P01: the row is {row.get('status')} and the plan fails the check"
        elif row.get("status") in ("pending", "satisfied"):
            changes.append((TOOL_ROW, "P01", (row["entry"], "satisfied", {
                "record": record_id, "sha256": plan.get("sha256"), "mechanism": "tool_selection.check",
                "needs": len(record["needs"]), "profile_record": inputs["profile_record"]})))
        else:
            missing[TOOL_ROW] = f"P01: the row is {row.get('status')}; a later plan cannot re-satisfy it"
    if changes or missing:
        _apply_rows(store, TOOL_NODE, changes, missing)
    return record_id


def _materialise_plan(state, store, plan_pins):
    """Instruction manifests for every step, the plan's obligations (plan stage of the ledger) and its
    plan-bind rows, recorded from their checks."""
    plan = current_plan({**state, "plan": plan_pins}, store)
    manifests = {}
    instructions = service("instructions")
    for step in plan["steps"]:
        manifest = instructions.manifest(step, _card(step.get("role")))
        if type(manifest) is not dict or type(manifest.get("sha256")) is not str:
            raise nodes.RecoveryHold("manifest_missing", f"step {step['id']} has no instruction manifest")
        manifests[step["id"]] = manifest["sha256"]
        store.append("manifest", {"step_id": step["id"], "plan_sha256": plan["sha256"], "manifest": manifest})
    children = bind_route_children(state, store, plan)
    rows = service("ledger").materialise(store, "plan", {"plan": deepcopy(plan), "run_id": store.run_id})
    selection = record_tool_selection(state, store, scientific_plan({**state, "plan": plan_pins}, store))
    # The plan-bind rows (each step's ownership and seat derivation) are recorded as the plan is bound, from their
    # checks; the governed step only verifies them before it dispatches the step.
    from .step import binding
    # The rows bind the scientific step bytes the governed step verifies (an applied engagement view pinned beside
    # the plan only adds its authenticated fields), also when a plan is materialised again after a replan.
    scientific = scientific_plan({**state, "plan": plan_pins}, store) if plan_pins.get("applied_blob") else plan
    binding.record_plan_rows(store, scientific, contract_sha256=(state.get("request") or {}).get("contract_sha256"),
                             ledger=service("ledger"))
    return {**plan_pins, "manifests": manifests, "materialised_rows": len(rows or []), "route_children": children,
            "tool_selection": selection}


def materialise(state):
    """Materialise the plan's obligations and build each step's instruction manifest."""
    store = _store(state)
    pins = _materialise_plan(state, store, state["plan"])
    require_transition(store, "plan->plan_review")
    if _engaged(store)[1]:
        # A plan revised after an earlier engagement decision: its review seats run under its own applied view.
        pins = engage({**state, "plan": pins}, store)
    return {"plan": pins, **_status("materialise", f"{len(pins['manifests'])} manifests; "
                                                   f"{pins['materialised_rows']} plan obligations")}


# ---- route children: a ``route`` step's fixed route, run as a child of this run --------------------------------------

ROUTE_PLAN = "route-plan"  # a route step's child plan (never a ``plan`` record: the ledger's plan stays the parent's)
ROUTE_CHILD = "route-child"  # one child step's outcome, kept as it settles (a re-entered child never runs it again)
ROUTE = "route"  # a route step whose parent request arrived: its child runs next


def route_child_excess(step, child):
    """Why ``child`` needs more than its route step holds: a higher rung, or a budget beyond the step's own in any
    dimension (the child spends only what the parent approved for that step). Empty when it fits."""
    from .routes.compiler import CompileError, authority_budget
    bounds = plan_bounds(child)
    problems = []
    if _rung_rank(bounds["rung"]) > _rung_rank(step.get("rung") or "none"):
        problems.append(f"rung {bounds['rung']} above the route step's {step.get('rung') or 'none'}")
    try:
        limit = authority_budget(step.get("budget"), step=step["id"])
    except CompileError as exc:
        return [str(exc)]
    problems += [f"budget {dimension}={value} above the route step's {limit.get(dimension, 0)}"
                 for dimension, value in sorted(bounds["budget"].items()) if value > limit.get(dimension, 0)]
    return problems


def bind_route_children(state, store, plan):
    """The child plan of each ``route`` step, bound by digest before CHECK-IN 1 so that the approval covers exactly
    it: the fixed route the step names, compiled inside this run from the pinned reading, contract and supplied
    inputs, carrying its lineage (``parameters.route_child``). The child inherits narrowing-only authority: a route
    that is not installed or does not compile, a child that covers only part of its request (open obligations), asks
    a CHECK-IN 2 of its own or needs more than its route step's rung or budget holds the plan. A child bound earlier
    for this plan is reused. ``{step id: {sha256, record_id}}``."""
    from . import routes
    from .routes.select import RouteAdapterMissing, spec_sha256
    route_steps = [s for s in plan["steps"] if s["kind"] == "route"]
    if not route_steps:
        return {}
    earlier = {(row["record"].get("parent_plan_sha256"), row["record"].get("parent_step")): row
               for row in store.scan(ROUTE_PLAN)}
    contract, reading, _ = _intake_records(state, store)
    bound = {}
    for step in route_steps:
        found = earlier.get((plan["sha256"], step["id"]))
        if found is not None:
            bound[step["id"]] = {"sha256": found["record"]["plan_sha256"], "record_id": found["id"]}
            continue

        def hold(code, text):
            raise nodes.RecoveryHold(code, f"route step {step['id']} ({step.get('route')}): {text}"[:1500])
        try:
            spec = routes.find(step.get("route"))
            child = routes.compile(spec, reading, contract, supplied=_supplied(store), revision=0, run_id=store.run_id,
                                   parameters={"route_child": {"parent_step": step["id"],
                                                               "parent_plan_sha256": plan["sha256"]}})
        except RouteAdapterMissing as exc:
            hold(exc.reason, f"install the route adapter: {exc}")
        except (routes.CompileError, routes.RouteSpecError) as exc:
            hold("route_child_invalid", str(exc))
        problems = routes.plan_errors(child, spec)
        if problems:
            hold("route_child_invalid", "; ".join(problems[:5]))
        if child.get("open_obligations"):
            hold("route_child_partial", f"the child leaves {len(child['open_obligations'])} obligation(s) open")
        if child.get("waypoints") or any(type(c) is dict and c.get("id") == "checkin2" for c in child.get("checkins") or ()):
            hold("route_child_checkin", "the child asks a CHECK-IN 2 of its own; a child inherits its parent's authority")
        excess = route_child_excess(step, child)
        if excess:
            hold("route_child_exceeds_step", "; ".join(excess))
        # A route's own re-binding, check-ins and gates are part of what it guarantees; a child runs under its parent's
        # check-ins, so a child whose route needs its own is held rather than run without them.
        module = routes.adapter_module(spec)
        hooks = [h for h in ("bind", "checkin", "gate", "packet_context", "dispatch")
                 if module is not None and hasattr(module, h)]
        if hooks:
            hold("route_child_adapter_hooks", f"the child route's own {', '.join(hooks)} hook(s) need check-ins, gates "
                 "or a dispatch of its own; a child runs inline under its parent's")
        record_id = store.append(ROUTE_PLAN, {"plan_sha256": child["sha256"], "blob": _put_json(store, child),
                                              "route": spec["id"], "spec_sha256": spec_sha256(spec),
                                              "parent_step": step["id"], "parent_plan_sha256": plan["sha256"],
                                              "steps": [s["id"] for s in child["steps"]]})
        bound[step["id"]] = {"sha256": child["sha256"], "record_id": record_id}
    return bound


def route_children(state, store):
    """The child plans the state's plan bound (``route_children``), read from the store and checked by digest."""
    from .routes import plan_sha256
    found = {}
    for step_id, pins in ((state.get("plan") or {}).get("route_children") or {}).items():
        row = store.read(ROUTE_PLAN, pins["record_id"])["record"]
        child = _json_blob(store, row["blob"])
        if child.get("sha256") != pins["sha256"] or row.get("plan_sha256") != pins["sha256"] \
                or plan_sha256(child) != child["sha256"]:
            raise nodes.RecoveryHold("route_child_digest_mismatch", f"the child plan of {step_id} differs from its pin")
        found[step_id] = child
    return found


def route_child(state, store, plan, step, child, budget):
    """Run route step ``step``'s bound child plan once, in this node: each child step through the step graph in
    dependency order, under the parent's authority (the context names the parent plan its approval covers, the child
    plan in ``route_child``, and carries the parent's frozen mode and GO pins), charged to the parent's ``budget`` and
    invoked under the route step (``route.<step>.<child step>.<attempt>``). The child route's ``admit`` and ``step``
    hooks see the child plan. A child step that completed (its ``route-child`` record) never runs again. A stop, an
    exhausted budget, a refused admission, a route spec that changed since it was bound or a child step that does not
    complete (a refusal, an escalation, a new-experiment request) holds the route step: a child's requests are not
    answered under its parent's authority. A child step's check-in flag is the parent's (``notes``).
    ``(row, hold, notes)``."""
    from . import routes
    from .routes.select import RouteAdapterMissing, spec_sha256
    sid = step["id"]
    row = {k: v for k, v in deepcopy((state.get("steps") or {}).get(sid) or {}).items() if k != "child"}
    rows, notes = {}, []

    def summary():
        return {"plan_sha256": (child or {}).get("sha256"), "record": pins.get("record_id"),
                "steps": {k: {"status": v.get("status"), "attempts": v.get("attempts"),
                              "outputs": deepcopy(v.get("outputs") or [])} for k, v in rows.items()}}

    def held(code, text):
        return ({**row, "status": "held", "reason": f"{code}: {text}"[:1000], "child": summary()},
                {"reason": code, "would_make_possible": text[:500]}, notes)
    pins = ((state.get("plan") or {}).get("route_children") or {}).get(sid) or {}
    if child is None or not pins:
        return held("route_child_missing", "no child plan was bound for the route step before CHECK-IN 1")
    try:
        spec = routes.find(child["route"]["id"])
        module = routes.adapter_module(spec)
    except (routes.RouteSpecError, RouteAdapterMissing) as exc:
        return held("route_child_invalid", f"the child route is not installed as bound: {exc}")
    if spec_sha256(spec) != store.read(ROUTE_PLAN, pins["record_id"])["record"].get("spec_sha256"):
        return held("route_child_spec_changed", "the installed child route changed after CHECK-IN 1 approved its plan")
    for entry in store.scan(ROUTE_CHILD):
        found = entry["record"]
        if found.get("parent_step") == sid and found.get("plan_sha256") == child["sha256"]:
            rows[found["step_id"]] = deepcopy(found["row"])
    lineage = {"step": sid, "plan_sha256": child["sha256"], "record": pins["record_id"],
               "parent_plan_sha256": plan["sha256"], "approve_plan": _latest_authority(state, "approve_plan")}
    child_engagement = None
    scientific_child = deepcopy(child)
    research_budget = (plan.get("parameters") or {}).get("research_loop_budget")
    if research_budget is not None:
        from .routes.research import child_engagement as child_policy
        descriptor = (step.get("parameters") or {}).get("item")
        if not isinstance(descriptor, dict):
            return held("research_child_tier_unpriced", "the research child has no bound facts descriptor")
        try:
            child_store, decision, child = child_policy.prepare(store, descriptor, child, research_budget, sid,
                                                               frozen_mode=state.get("mode") or {})
        except (nodes.RecoveryHold, ValueError, KeyError, TypeError) as exc:
            return held("research_child_tier_unpriced", str(exc))
        child_engagement = {"key": sid, "tier": decision["tier"], "decision_sha256": decision["sha256"],
                            "run_id": child_store.run_id}
    contract, reading, _ = _intake_records(state, store)
    by_id = {s["id"]: s for s in child["steps"]}
    loop = state.get("loop") or {}

    def child_context():
        return {"store": store, "run_dir": _run_dir(state), "plan": deepcopy(child),
                "state": {**deepcopy(dict(state)), "steps": deepcopy(rows)}, "reading": reading, "contract": contract}
    for cid in _in_order(child, set(by_id)):
        cstep = by_id[cid]
        while (rows.get(cid) or {}).get("status") != STEP_DONE:
            if service("authority").stop_state(store) != "running" or budget.get("exhausted"):
                return held("route_child_stopped", "the run stopped or exhausted its budget while the child ran")
            if child_engagement is not None:
                try:
                    child_store, decision, child = child_policy.prepare(
                        store, descriptor, scientific_child, research_budget, sid, frozen_mode=state.get("mode") or {})
                except (nodes.RecoveryHold, ValueError, KeyError, TypeError) as exc:
                    return held("research_child_tier_unpriced", str(exc))
                child_engagement.update(tier=decision["tier"], decision_sha256=decision["sha256"])
                cstep = next(s for s in child["steps"] if s["id"] == cid)
            if module is not None and hasattr(module, "admit"):
                refused = module.admit(deepcopy(cstep), child_context()) or []
                if refused:
                    return held("route_child_admission_refused", f"child step {cid}: " + "; ".join(
                        str(e.get("message") if type(e) is dict else e) for e in refused))
            previous = rows.get(cid) or {}
            attempt = int(previous.get("attempts") or 0) + 1
            correction = previous.get("correction") if previous.get("status") == CORRECT else None
            context = _context(state, store, cstep, attempt=attempt, wave=loop.get("number"), phase="execute",
                               seat_kind="launch" if cstep["kind"] in LAUNCH_KINDS else "worker",
                               route_child=deepcopy(lineage),
                               **({"research_child_engagement": deepcopy(child_engagement)} if child_engagement else {}),
                               **({"correction": deepcopy(correction)} if correction else {}))
            found = _invoke(state, STEP_GRAPH, {"step": deepcopy(cstep), "context": context},
                            {"route": f"{sid}.{cid}.{attempt}"})
            crow, outcome, _ = fold_outcome({**state, "steps": rows}, store, None, cstep, attempt, found, budget)
            if crow["status"] == STEP_DONE and module is not None and hasattr(module, "step"):
                problems = module.step(cstep, deepcopy(outcome), child_context()) or []
                if problems:
                    crow = {**crow, "status": "retry" if attempt < _attempt_limit(cstep) else "failed",
                            "reason": "route check: " + "; ".join(map(str, problems))[:1000]}
            record_id = store.append(ROUTE_CHILD, {"parent_step": sid, "plan_sha256": child["sha256"], "step_id": cid,
                                                  "attempt": attempt, "row": deepcopy(crow)})
            if child_engagement is not None:
                from . import engagement
                for event in outcome_events({**state, "steps": rows}, store,
                        [{"step": cstep, "attempt": attempt}], {cid: crow}, {cid: outcome}, record_id):
                    for evidence in event["evidence"]:
                        evidence["kind"] = ROUTE_CHILD
                    engagement.observe(child_store, event)
            rows[cid] = crow
            if outcome.get("escalation") == "checkin_flag":
                notes.append({"step": sid, "note": f"child step {cid}: {outcome.get('reason') or 'flagged'}"})
            elif outcome.get("escalation") or outcome.get("replan"):
                return held("route_child_escalated", f"child step {cid} asked {outcome.get('escalation') or 'a replan'}")
            if crow["status"] not in (STEP_DONE, "retry", CORRECT):
                return held("route_child_incomplete", f"child step {cid}: {crow['status']} ({crow.get('reason')})")
    if child_engagement is not None:
        try:
            child_policy.prepare(store, descriptor, scientific_child, research_budget, sid,
                                 frozen_mode=state.get("mode") or {})
        except (nodes.RecoveryHold, ValueError, KeyError, TypeError) as exc:
            return held("research_child_tier_unpriced", str(exc))
    order = _in_order(child, set(by_id))
    return ({**row, "status": STEP_DONE, "reason": f"its child route {child['route']['id']} completed",
             "outputs": [deepcopy(o) for cid in order for o in rows[cid].get("outputs") or ()],
             "receipts": [r for cid in order for r in rows[cid].get("receipts") or ()], "child": summary()}, None,
            notes)


def run_route_children(state, store, plan, steps, budget):
    """Each route step whose parent request arrived (``ROUTE``) runs its bound child (``route_child``): ``(rows, holds,
    notes)``, the notes being its child steps' check-in flags."""
    waiting = [s for s in plan["steps"] if (steps.get(s["id"]) or {}).get("status") == ROUTE]
    if not waiting:
        return {}, {}, []
    children = route_children(state, store)
    rows, holds, notes = {}, {}, []
    current = {**state, "steps": steps, "budget": budget}
    for step in waiting:
        rows[step["id"]], hold, flagged = route_child(current, store, plan, step, children.get(step["id"]), budget)
        notes.extend(flagged)
        if hold is not None:
            holds[step["id"]] = hold
    return rows, holds, notes


def _card(role):
    if not role:
        return None
    try:
        from ..workflow import role_registry
        return role_registry.load(role)
    except Exception:  # an unknown role is held by the step graph's preflight, not here
        return None


# ---- review seats ------------------------------------------------------------------------------

REVIEW_SEATS = {"plan": ("plan_review", "critic"), "waypoint": ("waypoint_review", "waypoint"),
                "attacks": ("kill_the_result", "crosscheck"), "final": ("final_review", "final"),
                "rdj": ("rdj_review", "rdj")}
# The check-in each review seat serves (the step's ``checkin``, from which the instruction package delivers that
# check-in's units). The P8 attacks are the final review's protocol seat, not a check-in seat; a deviation's decision
# has no review seat in this graph.
SEAT_CHECKINS = {"plan": "checkin1", "waypoint": "checkin2", "final": "checkin3"}
# Seats whose step id names the seat (one step, so one reservation, per seat). The plan and final seats keep the one
# step id the ledger's review transitions name (``plan_review``, ``final_review``).
PER_SEAT_STEPS = ("waypoint",)
# The rules each review seat checks: delivered as the seat's instruction units, which become its must_check items.
# The waypoint seats receive the CHECK-IN 2 rules through their check-in.
REVIEW_SOURCES = {"plan": ("docs/workflow/checklists/check-ins.md",), "waypoint": (),
                  "attacks": ("docs/workflow/checklists/judgment-protocols.md", "docs/workflow/steps/09-verify.md",
                              "docs/workflow/checklists/verification-panel.md"),
                  "final": ("docs/workflow/steps/09-verify.md", "docs/workflow/checklists/verification-panel.md"),
                  "rdj": ("docs/workflow/checklists/judgment-protocols.md",)}
# The P8 attack seat's document (JR09, the path the judgment policy names): one attack on each of basis, acceptance and
# statistics, with its test and outcome, naming the exact plan and drafted result (``judgment-attacks.v1``).
ATTACKS_OUTPUT = {"path": "outputs/judgment-attacks.json", "kind": "judgment-attacks", "required": True}
RDJ_ROLE = "rdj-critic"  # the independent reviewer of a decision record (an RDJ case)


from .review_seats import (canonical_role, checkin_seats, review_seat_key, review_step_id,
                           review_point_bindings)  # shared pure roster contract


def review_seat_counts(plan, name):
    from .review_seats import review_seat_counts as counts
    try:
        return counts(plan, name)
    except ValueError as exc:
        raise nodes.RecoveryHold("review_seat_counts_invalid", str(exc)) from None


# The seat-plan category of each derived review seat (the governed step's ``FOLD_CATEGORIES``).
SEAT_CATEGORIES = {"plan": "checkin1", "waypoint": "checkin2", "final": "checkin3", "attacks": "attack"}


def declared_seat(plan, role, purpose, n=1):
    """The applied engagement view's descriptor for the derived seat of ``role`` serving ``purpose`` when that seat
    carries folded roles, else None. Exactly one unconditional descriptor of that role and category must carry them;
    an ambiguous population delivers none, and the governed step then records the folded duties as undelivered."""
    category = SEAT_CATEGORIES.get(purpose)
    seats = ((plan.get("engagement") or {}).get("seat_plan") or {}).get("seats") or ()
    found = [s for s in seats if type(s) is dict and s.get("role") == role and s.get("category") == category
             and s.get("n", 1) == n and not s.get("conditional")]
    if len(found) != 1 or (not found[0].get("folded_roles") and found[0].get("required_count", 1) <= 1):
        return None
    return found[0]


def _seat_step(seat, *, purpose, plan, protocols=(), review_items=None, subject=None, step_id=None, n=1):
    """The step of one review seat: the seat's canonical role, the check-in it serves (``SEAT_CHECKINS``) and, with
    ``subject`` (``waypoint_subject``, ``result_subject``), the exact artifacts it reviews as its inputs, pinned by
    digest, after the steps that produced them. The P8 attack seat writes its ``judgment-attacks.v1`` document
    (``ATTACKS_OUTPUT``); ``step_id`` names a seat that reviews one step's subject (an RDJ case)."""
    role = canonical_role(seat)
    default_id, review_kind = REVIEW_SEATS[purpose]
    step_id = review_step_id(purpose, role, n, step_id)
    parameters = {"subject_plan_sha256": plan["sha256"], "purpose": purpose, "seat_kind": "review",
                  "review_kind": review_kind}
    bindings = review_point_bindings(plan, purpose, role, n)
    if bindings:
        parameters["review_points"] = bindings
    if review_items:
        parameters["review_items"] = deepcopy(review_items)
    inputs, depends = [{"artifact": "inputs/controller-plan.json", "sha256": None}], []
    if subject is not None:
        parameters["subject_sha256"] = subject["sha256"]
        inputs += deepcopy(subject["artifacts"])
        depends = list(subject["steps"])
        if subject.get("withheld"):
            # What the seat's card may not review (``_visible_subject``) is no input; the digest still binds it.
            parameters["subject_withheld"] = deepcopy(subject["withheld"])
    step = {"id": step_id, "kind": "review", "role": role, "inputs": inputs,
            "outputs": [{"path": f"outputs/review-{purpose}-{review_seat_key(role, n)}.json", "kind": "review-findings", "required": True}],
            "depends_on": depends, "waypoint": False, "rung": None, "budget": {}, "protocols": list(protocols),
            "review": [], "instruction_sources": list(REVIEW_SOURCES[purpose]), "obligations": [f"REVIEW-{purpose}"],
            "parameters": parameters}
    if purpose in SEAT_CHECKINS:
        step["checkin"] = SEAT_CHECKINS[purpose]
    descriptor = declared_seat(plan, role, purpose, n)
    if descriptor is not None:
        # The applied view folds other roles into this seat: it receives their duties exactly as the view declares
        # them (the packet step the policy sized: every folded item, card and manifest, the packet scope and the
        # constraint union) and one reviewer item per duty, each needing its own verdict. The descriptor itself is
        # named by key and digest (inline it would repeat every duty and overflow the packet); P04 resolves it from
        # the pinned applied view, binds the seat to it and discharges EG04 from the verdicts.
        parameters["engagement_seat_ref"] = {"key": descriptor["key"], "sha256": _digest(descriptor)}
        parameters["reviewer_items"] = deepcopy(descriptor.get("items") or [])
        step["engagement"] = deepcopy((descriptor.get("step") or {}).get("engagement") or {})
    if role == "assumption-auditor" and subject is not None and subject.get("assumption_audit"):
        path = assumption_audit_path(subject["sha256"])
        step["outputs"] = [{"path": path, "kind": "assumption-audit", "required": True}]
        parameters["check_inputs"] = {"check:validation.assumption_audit.check": {
            "document": {"output": path}}}
    if purpose == "attacks":
        step["outputs"] = [dict(ATTACKS_OUTPUT)]
        if subject is not None:
            # Kill-the-result (P8): the attacker writes its three attacks on this exact plan and drafted result.
            parameters["judgment"] = {"subject": {"kind": "draft", "plan_sha256": plan["sha256"],
                                                  "draft_sha256": subject["sha256"]}}
    return step


def _visible_subject(state, store, role, subject):
    """``subject`` as the seat of ``role`` may receive it: an artifact its card may not review
    (``review_projection.subject_class``: a blind card never reviews the producer's headline) is withheld from the
    seat's inputs and named in ``withheld`` with its class; the subject's digest still binds every artifact."""
    if subject is None:
        return None
    from ..workflow import review_projection
    places = {}
    for row in store.scan("custody"):
        record = row["record"]
        if record.get("status") == "accepted":
            places[(record.get("artifact"), record.get("sha256"))] = record.get("destination")
    kept, withheld = [], []
    for artifact in subject["artifacts"]:
        rel = places.get((artifact.get("artifact"), artifact.get("sha256")))
        try:
            found = review_projection.subject_class(_run_dir(state), role, rel) if type(rel) is str else None
        except review_projection.ProjectionRefused:
            found = None  # the governed step's own projection refuses an unusable card
        (withheld.append({**artifact, "class": found}) if found else kept.append(artifact))
    return {**subject, "artifacts": kept, "withheld": withheld}


def _record_review(store, record):
    """Append one review round (a ``review`` record): the record id the check-in binds."""
    return store.append("review", record)


def _run_seats(state, store, seats, *, purpose, protocols=(), review_items=None, subject=None, step_id=None,
               attempt=None, extra=None):
    """Run each seat of one review round through the step graph and record the round: ``(verdicts, attempt, record
    id)``. The governed step reports a completed review seat's credit and verdict (``review``); an outcome that
    carries neither (the interface fake's) counts as credited and accepting only when it completed. A seat that did
    not complete is neither credited nor accepting. Each verdict keeps the outputs the seat's step adopted.
    ``step_id``, ``attempt`` and ``extra`` (fields of the round's record) serve a seat on one step's subject."""
    plan = current_plan(state, store)
    revision = (state.get("plan") or {}).get("revision", 0)
    if attempt is None:
        attempt = revision + 1 if purpose == "plan" else \
            len((state.get("reviews") or {}).get(f"{purpose}_rounds") or []) + 1
    copy = _run_dir(state) / "inputs" / "controller-plan.json"
    private_files.write(copy, (json.dumps(plan, indent=2, sort_keys=True) + "\n").encode())
    verdicts = {}
    counts = review_seat_counts(plan, SEAT_CHECKINS.get(purpose))
    instances = [(role, n) for role in dict.fromkeys(canonical_role(seat) for seat in seats)
                 for n in range(1, counts.get(role, 1) + 1)]
    for seat, n in instances:
        step = _seat_step(seat, purpose=purpose, plan=plan, protocols=protocols, review_items=review_items,
                          subject=_visible_subject(state, store, seat, subject), step_id=step_id, n=n)
        found = _invoke(state, STEP_GRAPH, {"step": step, "context": _context(state, store, step, attempt=attempt,
                                                                               purpose=purpose)},
                        {"seat": f"{purpose}.{review_seat_key(seat, n)}.{attempt}"})
        outcome = (found.get("results") or {}).get("step") or {}
        review = outcome.get("review") or {}
        verdicts[review_seat_key(seat, n)] = {"status": outcome.get("status") or found.get("outcome"),
                          "credited": bool(review.get("credited", outcome.get("status") == STEP_DONE)),
                          "verdict": review.get("verdict", "accept" if outcome.get("status") == STEP_DONE else None),
                          "receipts": list(outcome.get("receipts") or []), "step": step["id"],
                          "findings": list(review.get("findings") or []),
                          "outputs": deepcopy(outcome.get("outputs") or [])}
    record = {"purpose": purpose, "plan_sha256": plan["sha256"], "attempt": attempt, "seats": verdicts}
    if purpose in SEAT_CHECKINS:
        record["checkin"] = SEAT_CHECKINS[purpose]
    if subject is not None:
        record.update(subject_sha256=subject["sha256"], subject=deepcopy(subject["pins"]))
    record.update(deepcopy(extra or {}))
    return verdicts, attempt, _record_review(store, record)


def _artifacts(step_ids, steps):
    """The executed outputs of steps ``step_ids`` as artifacts pinned by digest (``<step>:<path>``)."""
    return [{"artifact": o.get("artifact") or f"{sid}:{o['path']}", "sha256": o.get("sha256")}
            for sid in step_ids for o in (steps.get(sid) or {}).get("outputs") or ()
            if type(o) is dict and type(o.get("path")) is str]


def waypoint_subject(waypoints, steps):
    """What the CHECK-IN 2 seats review: each waypoint step's executed outputs as artifacts pinned by digest
    (``<step>:<path>``), and the ``waypoint:<id>`` pins of the GO (``sha256`` is their digest)."""
    pins = waypoint_pins(waypoints, steps)
    return {"steps": list(waypoints), "artifacts": _artifacts(waypoints, steps), "pins": pins, "sha256": _digest(pins)}


def result_subject(plan, steps):
    """What the P8 attacks are about: the result producers' executed outputs pinned by digest, and the drafted
    result (``sha256``: the digest of the step states, which CHECK-IN 3 binds as ``steps_sha256``)."""
    producers = result_producers(plan)
    drafted = _digest(steps)
    return {"steps": producers, "artifacts": _artifacts(producers, steps), "pins": {"steps_sha256": drafted},
            "sha256": drafted}


def _accepted(verdicts):
    """Every seat of a review round credited the subject and accepted it (a performed review is not acceptance)."""
    return bool(verdicts) and all(v.get("credited") and v.get("verdict") == "accept" for v in verdicts.values())


# ---- correction rounds: a credited revise or unresolved review is a performed review, never acceptance -------------

FINDINGS = "step-review-findings"  # the governed step's protected record of one review's findings
REVIEW_VERDICTS = ("revise", "unresolved")
CORRECT = "correct"  # a step whose producer runs again as a correction round, with the review's findings pinned


def correction_rounds(state):
    """How many correction rounds a credited ``revise`` or ``unresolved`` review may start on one subject: the
    judgment policy's ``review_rounds`` for the run's frozen mode (``judgment.bounds``; the first review is a round),
    else the frozen operator budgets, ``max_redos`` and ``review_rounds`` (the first review included), the stricter
    where both are set. Neither set: none, and such a review holds what it reviewed."""
    mode = state.get("mode") or {}
    bounds = getattr(service("judgment"), "bounds", None)
    rounds = (bounds(mode) or {}).get("review_rounds") if callable(bounds) else None
    if type(rounds) is int and rounds >= 0:
        return max(rounds - 1, 0)
    budgets = mode.get("budgets") or {}
    limits = [budgets["max_redos"]] if type(budgets.get("max_redos")) is int and budgets["max_redos"] >= 0 else []
    if type(budgets.get("review_rounds")) is int and budgets["review_rounds"] >= 0:
        limits.append(max(budgets["review_rounds"] - 1, 0))
    return min(limits) if limits else 0


def replan_bound(state):
    """How many replans the run may make: the judgment policy's ``replans`` for the run's frozen mode
    (``judgment.bounds``), and the operator's ``replans`` budget where the mode froze one: the stricter. Neither:
    none, so a new-experiment request ends the run qualified."""
    mode = state.get("mode") or {}
    bounds = getattr(service("judgment"), "bounds", None)
    found = (bounds(mode) or {}).get("replans") if callable(bounds) else None
    limits = [found] if type(found) is int and found >= 0 else []
    budget = (mode.get("budgets") or {}).get("replans")
    if type(budget) is int and budget >= 0:
        limits.append(budget)
    return min(limits) if limits else 0


def replans_done(state, store):
    """The replans this run made: its distinct replanned plans in the store (no new plan pin resets the count, and a
    plan record repeated for an applied view counts once)."""
    made = {row["record"].get("plan_sha256") for row in store.scan("plan") if row["record"].get("source") == "replan"}
    recovered = {row["record"].get("plan_sha256") for row in store.scan("recovery")
                 if row["record"].get("phase") == "adopted"}
    return max(len(made - recovered), int((state.get("plan") or {}).get("replans") or 0))


def pinned_findings(store, reviewed, review):
    """The findings ``review`` names (``findings``: the governed step's protected records of that review of step
    ``reviewed``), each pinned by its store id and digest; None when it names none or one that is not a findings
    record of ``reviewed`` in this run."""
    pins = []
    for record_id in review.get("findings") or ():
        try:
            row = store.read(FINDINGS, record_id)
        except (ValueError, KeyError, TypeError):
            return None
        record = row["record"]
        if record.get("parent_step", record.get("step_id")) != reviewed:
            return None
        pins.append({"record": row["id"], "kind": FINDINGS, "digest": row["digest"], "verdict": record.get("verdict"),
                     "subject_sha256": record.get("subject_sha256")})
    return pins or None


def review_correction(store, *, purpose, verdicts, subject_sha256, attempt, done, bound):
    """``(correction, problem)`` for a review round that did not accept its subject. ``verdicts`` maps each seat to its
    ``credited``, ``verdict``, ``findings`` and the reviewing ``step``. A refused or missing credit
    (``review_uncredited``), used-up rounds (``review_rounds_exhausted``) or a seat without its findings
    (``review_findings_missing``) start no correction: ``problem`` is ``(code, text)``. Otherwise ``correction`` is the
    round the producer runs: the findings pinned, the round number within the bound, the reviewed subject."""
    uncredited = sorted(seat for seat, v in verdicts.items() if not v.get("credited"))
    if not verdicts or uncredited:
        return None, ("review_uncredited", "no credited review by " + (", ".join(uncredited) or "any seat"))
    open_seats = {seat: v for seat, v in verdicts.items() if v.get("verdict") != "accept"}
    if any(v.get("verdict") not in REVIEW_VERDICTS for v in open_seats.values()):
        return None, ("review_verdict_unknown", "a seat returned no accept, revise or unresolved verdict")
    verdict = "revise" if any(v["verdict"] == "revise" for v in open_seats.values()) else "unresolved"
    if done >= bound:
        return None, ("review_rounds_exhausted", f"{verdict} after {done} of {bound} correction round(s)")
    findings = []
    for seat, v in sorted(open_seats.items()):
        pins = pinned_findings(store, v.get("step"), v)
        if pins is None:
            return None, ("review_findings_missing", f"the {verdict} review by {seat} names no findings of its own")
        findings.extend(pins)
    return {"purpose": purpose, "round": done + 1, "rounds": bound, "verdict": verdict, "findings": findings,
            "subject_sha256": subject_sha256, "reviewed_attempt": attempt}, None


def correction_steps(plan, steps, producers, correction):
    """The step rows a correction round sets: each producer of the reviewed subject runs again with the round's pinned
    findings (``correct``); every step that already completed on their outputs runs again after them (``retry``)."""
    children = {}
    for step in plan["steps"]:
        for parent in step.get("depends_on") or ():
            children.setdefault(parent, []).append(step["id"])
    rows = {sid: {**(steps.get(sid) or {}), "status": CORRECT, "correction": deepcopy(correction),
                  "reason": f"review {correction['verdict']}: correction round {correction['round']}"}
            for sid in producers}
    pending = [child for sid in producers for child in children.get(sid, ())]
    while pending:
        sid = pending.pop()
        if sid in rows or (steps.get(sid) or {}).get("status") != STEP_DONE:
            continue
        rows[sid] = {**{k: v for k, v in steps[sid].items() if k != "correction"}, "status": "retry",
                     "reason": "its inputs are corrected"}
        pending.extend(children.get(sid, ()))
    return rows


def _review_round(store, purpose, plan_sha256, subject_sha256, attempt):
    """The recorded review round of ``purpose`` on this plan, subject and attempt (a round re-entered after an
    interruption reuses it instead of dispatching its seats again), or None."""
    for row in reversed(store.scan("review")):
        record = row["record"]
        if (record.get("purpose"), record.get("plan_sha256"), record.get("subject_sha256"), record.get("attempt")) \
                == (purpose, plan_sha256, subject_sha256, attempt):
            return row
    return None


def checkin2_review(state, store, plan, steps):
    """CHECK-IN 2's review seats on the executed waypoint, before its authority is asked: ``(decision, reason,
    reviews, rows)``. Each seat the plan declares for CHECK-IN 2 (``checkins[].seats``, else ``CI2_SEATS``) reviews
    the waypoint steps' exact outputs as its own step. Only every seat's credited ``accept`` leads to the GO. A
    credited ``revise`` or ``unresolved`` starts a correction round within the bound (``rows``: the waypoint steps run
    again with the findings pinned, then the seats review their new outputs); a refused or missing credit, used-up
    rounds or a waypoint without executed outputs holds the GO."""
    waypoints = list(plan.get("waypoints") or [])
    subject = waypoint_subject(waypoints, steps)
    if not subject["artifacts"]:
        return "blocked", "the waypoint has no executed outputs for its CHECK-IN 2 review", {}, {}
    rounds = list((state.get("reviews") or {}).get("waypoint_rounds") or [])
    attempt = len(rounds) + 1
    found = _review_round(store, "waypoint", plan["sha256"], subject["sha256"], attempt)
    if found is not None:
        verdicts, record_id = deepcopy(found["record"]["seats"]), found["id"]
    else:
        review_items = None
        module = adapter(state, store)
        if module is not None and hasattr(module, "checkin"):
            # The route's CHECK-IN 2 rules reach the waypoint seats as review items (its errors hold CHECK-IN 2 later).
            review_items = (module.checkin("go", adapter_context(state, store)) or {}).get("review_items")
        verdicts, attempt, record_id = _run_seats(state, store, checkin_seats(plan, "checkin2", CI2_SEATS),
                                                  purpose="waypoint", review_items=review_items, subject=subject)
    reviews = {"checkin2": verdicts, "checkin2_record": record_id, "checkin2_subject": subject["sha256"],
               "waypoint_rounds": rounds + [attempt]}
    if _accepted(verdicts):
        return "waypoint", "the verification waypoint is reached and its review seats accepted it", reviews, {}
    corrections = dict((state.get("reviews") or {}).get("corrections") or {})
    done = int(corrections.get("waypoint") or 0)
    correction, problem = review_correction(store, purpose="waypoint", verdicts=verdicts, attempt=attempt,
                                            subject_sha256=subject["sha256"], done=done, bound=correction_rounds(state))
    if problem is not None:
        seen = "; ".join(f"{seat}: {v.get('verdict') if v.get('credited') else 'not credited'} ({v.get('status')})"
                         for seat, v in sorted(verdicts.items()))
        reason = f"the CHECK-IN 2 review did not accept the waypoint ({problem[0]}: {problem[1]}): {seen}"
        return "blocked", reason[:600], reviews, {}
    reviews["corrections"] = {**corrections, "waypoint": done + 1}
    return ("correct", f"the CHECK-IN 2 review asked for a correction (round {correction['round']} of "
            f"{correction['rounds']})", reviews, correction_steps(plan, steps, waypoints, correction))


def plan_review(state):
    store = _store(state)
    plan = current_plan(state, store)
    seats = checkin_seats(plan, "checkin1", CI1_SEATS)
    review_items = None
    module = adapter(state, store)
    if module is not None and hasattr(module, "checkin"):
        # The route's CHECK-IN 1 rules reach the plan critic as review items (its errors hold CHECK-IN 1 later).
        review_items = (module.checkin("approve_plan", adapter_context(state, store)) or {}).get("review_items")
    # The engagement facts are pinned before the review and reach its seats as review items; the round's record names
    # the exact fact digests it delivered, and only a credited, accepting plan critic credits them (EG02).
    scientific = scientific_plan(state, store)
    fact_items = engagement_review_items(store, pin_engagement_facts(state, store, scientific))
    if fact_items:
        review_items = list(review_items or []) + fact_items
    verdicts, attempt, review_id = _run_seats(
        state, store, seats, purpose="plan", review_items=review_items,
        extra={"engagement_fact_sha256s": [i["subject_sha256"] for i in fact_items]} if fact_items else None)
    credit_engagement_facts(store, scientific, review_id, fact_items)
    unmet = ledger_errors(store, "plan_review->checkin1", "plan_review")
    store.append("transition", {"transition": "plan_review->checkin1", "passed": not unmet, "errors": unmet[:50]})
    reviews = {"checkin1": verdicts, "checkin1_unmet": [e["message"] for e in unmet], "checkin1_correction": None}
    if unmet:
        decision, reason = "end", "plan review obligations unmet"
    elif _accepted(verdicts):
        decision, reason = "ok", "plan review seats accepted the plan"
    else:
        # A credited revise or unresolved review: the planner corrects the plan with the findings pinned, within the
        # correction rounds and the plan's revision bound; the new plan is reviewed again.
        corrections = dict((state.get("reviews") or {}).get("corrections") or {})
        done = int(corrections.get("plan") or 0)
        correction, problem = review_correction(store, purpose="plan", verdicts=verdicts, attempt=attempt,
                                                subject_sha256=plan["sha256"], done=done,
                                                bound=correction_rounds(state))
        if problem is None and (state.get("plan") or {}).get("revision", 0) >= MAX_PLAN_REVISIONS:
            problem = ("plan_revisions_exhausted", f"the plan reached {MAX_PLAN_REVISIONS} revisions")
        if problem is None:
            decision, reason = "revise", f"plan review asked for a correction (round {correction['round']})"
            reviews.update(checkin1_correction=correction, corrections={**corrections, "plan": done + 1})
        else:
            decision, reason = "end", f"plan review did not accept the plan ({problem[0]}: {problem[1]})"
    reviews["checkin1_next"] = decision
    return {"reviews": reviews, **_status("plan_review", reason)}


def _review_branch(state):
    """The plan review's decision (``plan_review``): the plan goes to CHECK-IN 1 only when every seat credited and
    accepted it, to a correction round within its bounds, else to a qualified ending."""
    reviews = state.get("reviews") or {}
    if reviews.get("checkin1_unmet"):
        return "end"
    decision = reviews.get("checkin1_next")
    if decision == "ok" and _accepted(reviews.get("checkin1") or {}):
        return "ok"
    return "revise" if decision == "revise" else "end"


def revise(state):
    """A plan revision: the CHECK-IN 1 answer asked for one, or the plan review a correction round. The planner
    receives that round's pinned findings (``loop.correction``)."""
    store = _store(state)
    reviews = state.get("reviews") or {}
    correction = reviews.get("checkin1_correction") if reviews.get("checkin1_next") == "revise" else None
    store.append("revision", {"from_plan_sha256": (state.get("plan") or {}).get("sha256"),
                              "revision": (state.get("plan") or {}).get("revision", 0) + 1,
                              "correction": deepcopy(correction)})
    return {"loop": {"candidate": None, "correction": deepcopy(correction)},
            **_status("revise", "plan revision requested")}


def _revise_branch(state):
    if (state.get("plan") or {}).get("revision", 0) >= MAX_PLAN_REVISIONS:
        return "end"
    return _route_branch(state)


# ---- check-in views and authority points ----------------------------------------------------------

def _latest_authority(state, kind):
    ids = (state.get("authority") or {}).get(kind) or []
    return ids[-1] if ids and ids[-1] else None


def escalation_rows(state):
    """The escalations one authority request is about: those the escalation point asked and that are not settled yet
    (when its gate checks the answer), else the next pending ones: one question alone (``QUESTION_KINDS``, with its
    own options) or every other pending escalation together."""
    rows = state.get("escalations") or {}
    chosen = {k: v for k, v in rows.items() if v.get("status") in ("asked", "unanswered")}
    if not chosen:
        pending = {k: v for k, v in sorted(rows.items()) if v.get("status") == "pending"}
        first = next(iter(pending), None)
        if first is not None and pending[first].get("escalation") in QUESTION_KINDS:
            chosen = {first: pending[first]}
        else:
            chosen = {k: v for k, v in pending.items() if v.get("escalation") not in QUESTION_KINDS}
    return {k: deepcopy(chosen[k]) for k in sorted(chosen)}


def escalation_subject(state):
    """The escalations an R3 decision or a question is about (``escalation_rows``). Status is left out, so the views
    of the request and of its gate agree."""
    return {k: {"escalation": v.get("escalation"), "attempt": v.get("attempt"), "reason": v.get("reason")}
            for k, v in escalation_rows(state).items()}


def point_kind(name, state):
    """The authority kind authority point ``name`` asks: its own, or, for the escalation point, the kind of the one
    question it asks (``QUESTION_KINDS``)."""
    rows = escalation_rows(state) if name == "escalate" else {}
    if len(rows) == 1:
        return QUESTION_KINDS.get(next(iter(rows.values())).get("escalation"), AUTHORITY_KINDS[name])
    return AUTHORITY_KINDS[name]


def _descendants(plan, step_id):
    """The ids of the steps that depend on ``step_id``, directly or through others."""
    children = {}
    for step in plan["steps"]:
        for parent in step.get("depends_on") or ():
            children.setdefault(parent, []).append(step["id"])
    found, pending = set(), list(children.get(step_id, ()))
    while pending:
        sid = pending.pop()
        if sid not in found:
            found.add(sid)
            pending.extend(children.get(sid, ()))
    return found


def answer_bounds(plan, step_id):
    """What an answer to step ``step_id``'s question lets happen, in the authority's typed form (rung, stages,
    budget): the steps after it, at their rung and stages and within their budgets."""
    after = _descendants(plan, step_id)
    return plan_bounds({"steps": [s for s in plan["steps"] if s["id"] in after]})


def escalation_question(state, store, plan):
    """The one question the escalation point asks, or None for a stop or a decision block: its kind and step, its
    text, the options with what each lets happen (``effect``; ``bounds`` in the authority's typed form), its
    conservative default and the pins that bind it. An ``ask`` offers its plan step's options, each letting its branch
    continue within the bounds of the steps after it. An R3 decision offers its judgment record's options, of which
    only the recorded choice has that effect: another one overturns the decision and its branch holds."""
    rows = escalation_rows(state)
    if len(rows) != 1:
        return None
    step_id, row = next(iter(rows.items()))
    if row.get("escalation") not in QUESTION_KINDS:
        return None
    bounds = answer_bounds(plan, step_id)
    if row["escalation"] == "ask":
        options = [{"id": o["id"], "text": o["text"], "effect": True, "bounds": deepcopy(bounds)}
                   for o in row.get("options") or ()]
        planned = next((s for s in plan["steps"] if s["id"] == step_id), None)
        pins = {f"ask:{step_id}": _digest(planned)}
    else:
        chosen = row.get("chosen")
        options = [{"id": o["id"], "text": o["text"], "effect": o["id"] == chosen,
                    **({"bounds": deepcopy(bounds)} if o["id"] == chosen else {})} for o in row.get("options") or ()]
        pins = {f"judgment:{step_id}": str(row.get("record_sha256") or "")}
    default = row.get("default") if row.get("default") in {o["id"] for o in options} else None
    assumption = row.get("assumption") if default is not None and (row.get("assumption") or {}).get("option") == default \
        else None
    return {"kind": QUESTION_KINDS[row["escalation"]], "step": step_id, "escalation": row["escalation"],
            "text": str(row.get("question") or row.get("reason") or "")[:1000], "options": options, "default": default,
            "bounds": bounds, "pins": pins, "assumption": deepcopy(assumption)}


def _rung_rank(rung):
    return RUNGS.index(rung) if rung in RUNGS else 0


def step_stage(step):
    """The stage the authority admits ``step``'s effect under: its launch's declared stage, else its operation,
    else its kind (the derivation the step graph uses when it asks ``authority.authorize_effect``)."""
    launch = (step.get("parameters") or {}).get("launch")
    return (launch.get("stage") if type(launch) is dict else None) or step.get("operation") or step["kind"]


def _plan_budget_envelope(state):
    from .routes.compiler import AUTHORITY_BUDGET
    mode = state.get('mode') or {}
    found = {**(mode.get('budgets') or {}), **((mode.get('bounds') or {}).get('budget') or {})}
    return {key: value for key, value in found.items() if key in set(AUTHORITY_BUDGET.values())}


def plan_bounds(plan):
    """What an approval of ``plan`` covers: its highest rung, its stages (every step's operation or kind and every
    launch's declared stage) and its summed step budgets in the authority's dimensions (``AUTHORITY_BUDGET``)."""
    from .routes.compiler import CompileError, authority_budget
    budget = {}
    try:
        for step in plan["steps"]:
            for dimension, value in authority_budget(step.get("budget"), step=step.get("id")).items():
                budget[dimension] = budget.get(dimension, 0) + value
    except CompileError as exc:
        raise nodes.RecoveryHold("budget_dimension_unknown", str(exc)[:1500]) from None
    rungs = [s.get("rung") for s in plan["steps"] if s.get("rung")]
    return {"rung": max(rungs, key=_rung_rank) if rungs else "none",
            "stages": sorted({s.get("operation") or s["kind"] for s in plan["steps"]}
                             | {step_stage(s) for s in plan["steps"]}),
            "budget": budget}


def waypoint_pins(waypoints, steps):
    """The ``waypoint:<id>`` pins a GO binds: the digest of each waypoint step's executed outputs."""
    return {f"waypoint:{w}": _digest((steps.get(w) or {}).get("outputs") or []) for w in waypoints}


def _strings(values):
    return [str(v) for v in values if str(v).strip()]


def _change_row(state):
    """The exact change a deviation check-in decides: one parameter/from/to/why/touches/direction row."""
    plan_pins = state.get("plan") or {}
    replans = [v for v in (state.get("replans") or {}).values() if v.get("status") in ("pending", "replanned")]
    return {"parameter": "plan", "from": str(plan_pins.get("approved_sha256") or "none"),
            "to": str(plan_pins.get("sha256")),
            "why": "; ".join(str(v.get("reason") or (v.get("request") or {}).get("why") or "")
                             for v in replans if v) or "the plan changed after its approval",
            "touches": sorted(plan_pins.get("changed_steps") or []) or ["plan"],
            "direction": "scope" if plan_pins.get("scope_changed") else (plan_pins.get("recovery_direction") or "plan")}


def _finding_text(finding):
    """One frame finding as a line of text (a finding is a string or a record with its text)."""
    if type(finding) is dict:
        finding = finding.get("text") or finding.get("finding") or finding.get("statement") or json.dumps(
            finding, sort_keys=True, ensure_ascii=False)
    return " ".join(str(finding).split())[:500]


def frame_findings(plan):
    """The frame critic's findings a judgment plan carries past its last frame round (``parameters.judgment``)."""
    found = ((plan.get("parameters") or {}).get("judgment") or {}).get("frame_findings") if type(plan) is dict else None
    return [text for text in map(_finding_text, found if type(found) is list else ()) if text]


def _checkin_flags(name, state, escalated, plan=None):
    """The numbered flags of check-in ``name`` from run state: step flags, review verdicts, escalated questions, and
    at CHECK-IN 1 the frame findings the plan carries (risks)."""
    flags = [{"kind": "risk", "text": f"{f.get('step')}: {f.get('note') or 'flagged by its step'}"}
             for f in (state.get("flags") or {}).get(name) or []]
    if name == "checkin1":
        flags += [{"kind": "risk", "text": f"frame finding: {text}"} for text in frame_findings(plan)]
        flags += [{"kind": "decision", "text": f"plan review by {seat}: {v.get('verdict')}"}
                  for seat, v in sorted(((state.get("reviews") or {}).get("checkin1") or {}).items())]
    if name == "checkin2":
        flags += [{"kind": "decision", "text": f"waypoint review by {seat}: {v.get('verdict')}"}
                  for seat, v in sorted(((state.get("reviews") or {}).get("checkin2") or {}).items())]
    if name == "checkin3":
        flags += [{"kind": "decision", "text": f"final review by {seat}: {v.get('verdict')}"}
                  for seat, v in sorted(((state.get("reviews") or {}).get("final") or {}).items())]
    flags += [{"kind": "question", "text": f"{step}: {row['escalation']}: {row['reason'] or 'no reason stated'}"}
              for step, row in escalated.items()]
    return flags


def _outputs(row):
    paths = [str(o.get("path")) for o in (row or {}).get("outputs") or () if type(o) is dict and o.get("path")]
    return ", ".join(paths[:8]) + (f" (+{len(paths) - 8} more)" if len(paths) > 8 else "") if paths else "no outputs"


def _checkin_sections(name, state, plan, contract, escalated, question=None):
    """The sections the controller writes from run state for check-in ``name``: the plain-language preamble
    (the request as pinned, what this decision lets happen) and the kind's own section (the executed waypoint
    evidence, the exact change, the results, the question or the action asked for). A route may supply its own
    instead."""
    steps, pins = state.get("steps") or {}, state.get("plan") or {}
    prompt = " ".join(str(contract.get("prompt") or "").split())
    request = f"Request: {prompt[:400]}" + ("..." if len(prompt) > 400 else "") if prompt else "Request: (empty)"
    revision = pins.get("revision", 0)
    sections = []
    if name == "checkin1":
        lines = [f"Plan revision {revision} on route {plan['route']['id']}: {len(plan['steps'])} steps producing "
                 f"{len(plan['deliverables'])} deliverables. Approving it lets execution start within the bounds "
                 "below; nothing beyond the prepare phase has run."]
    elif name == "checkin2":
        waypoints = list(plan.get("waypoints") or [])
        lines = [f"The verification waypoint {', '.join(waypoints)} ran. A GO lets the full and scan steps start "
                 "on this evidence."]
        sections.append({"id": "waypoint", "title": "Waypoint evidence",
                         "lines": [f"{w}: {(steps.get(w) or {}).get('status')}; {_outputs(steps.get(w))}"
                                   for w in waypoints]})
    elif name == "deviation":
        change = _change_row(state)
        lines = [f"The plan changed after its approval (now revision {revision}). Approving the change renews the "
                 "authority for the new plan; it does not change what was approved before."]
        sections.append({"id": "change", "title": "Exact change",
                         "lines": [f"{change['parameter']}: {change['from'][:16]} -> {change['to'][:16]} "
                                   f"({change['direction']}); touches {', '.join(change['touches'])}; "
                                   f"why: {change['why']}"]})
    elif name == "checkin3":
        lines = ["Every plan step finished and the final review ran. Accepting delivers the results through the sole "
                 "sink, which re-checks them."]
        sections.append({"id": "results", "title": "Results",
                         "lines": [f"{s['id']}: {(steps.get(s['id']) or {}).get('status')}; "
                                   f"{_outputs(steps.get(s['id']))}" for s in plan["steps"]]})
    elif question is not None and question["escalation"] == "ask":
        lines = [f"Step {question['step']} asks a question only the physicist or the operator may answer. An answer "
                 "lets its branch continue within the bounds of its option; without one that branch holds while the "
                 "others continue."]
        sections.append({"id": "question", "title": "Question", "lines": [f"{question['step']}: {question['text']}"]})
    elif question is not None:
        lines = [f"Step {question['step']} took an R3 decision: the steps after it run only with authority for its "
                 "recorded choice. Another option overturns the decision and holds that branch."]
        sections.append({"id": "action", "title": "Action asked for",
                         "lines": [f"{question['step']}: {question['text']}"]})
    else:
        lines = [f"{len(escalated)} step(s) escalated a decision only the physicist or the operator may take. "
                 "Continuing lets them run again; holding keeps their branch held while the others continue."]
        sections.append({"id": "action", "title": "Action asked for",
                         "lines": [f"{step}: {row['escalation']}: {row['reason'] or 'no reason stated'}"
                                   for step, row in escalated.items()] or ["no escalated step"]})
    return [{"id": "preamble", "title": "Plain-language preamble", "lines": [request, *lines]}] + sections


def retained_reading(state, store, *, flags, items):
    """The reading the authority retains for a check-in (``retained.capture``): the comparisons with the
    request (the authority adds every request pin the mode froze, with the plan's value), the
    physics-critical facts the reading inferred rather than read from the request, the check-in's flags and
    the reading items it shows. Every list is explicit; an empty one means there is nothing to disclose."""
    _, reading, _ = _intake_records(state, store)
    request = state.get("request") or {}
    inferred = [{"id": f.get("id"), "type": f.get("type"), "value": deepcopy(f.get("value"))}
                for f in reading.get("facts") or () if type(f) is dict and f.get("authority") == "inferred"
                and f.get("physics_critical")]
    return {"request_sha256": request.get("sha256"), "reading_sha256": request.get("reading_sha256"),
            "request_pins": {}, "inferred_critical_facts": inferred, "flags": deepcopy(flags),
            "items": {k: list(v) for k, v in items.items() if v}}


def _merge_checkin_pins(current, extra):
    """Keep the controller's scope immutable when adding route evidence pins."""
    merged = deepcopy(current)
    for key, value in (extra or {}).items():
        if not value:
            continue
        key, value = str(key), str(value)
        if key in merged and str(merged[key]) != value:
            raise nodes.RecoveryHold("checkin_pin_conflict", "route evidence conflicts with controller pin " + key)
        merged[key] = value
    return merged


def checkin_material(name, state, store):
    """``(view, reading, plan)`` of authority point ``name``: the typed check-in view (``checkin.v1`` fields)
    rendered from run state, the retained reading it is decided on and the stored plan document.

    With the authority's canonical items (``retained.view_items``) the view's items are built from the
    plan and the retained reading exactly as the authority's snapshot builds them (N2); without them the
    items are rendered as text.
    """
    kind = point_kind(name, state)
    request = state.get("request") or {}
    pins_state = state.get("plan") or {}
    plan = current_plan(state, store)
    contract, reading, _ = _intake_records(state, store)
    pins = {"plan_sha256": pins_state.get("sha256"), "request_sha256": request.get("sha256"),
            "reading_sha256": request.get("reading_sha256"), "contract_sha256": request.get("contract_sha256"),
            "route": plan["route"]["id"], "applied_sha256": pins_state.get("applied_sha256")}
    # A plan-approving check-in binds the engagement decision it shows (its record digest: an escalation later adds
    # seats as R1 events and never changes the decision this authority covered).
    engaged = engagement_decision(store, pins_state.get("sha256")) if name in ENGAGED_POINTS else None
    if engaged is not None:
        pins["engagement_decision_sha256"] = engaged["sha256"]
        # A judgment plan's own envelope (built with the route builder as the decision was taken) is pinned only here.
        binding = getattr(_engagement(), "envelope_binding", None)
        bound = binding(engaged) if callable(binding) else None
        if bound is not None:
            pins["engagement_envelope_sha256"] = bound
    approved_id = _latest_authority(state, "approve_plan")
    if name in ("checkin2", "deviation", "checkin3", "escalate") and approved_id:
        pins["approve_plan"] = approved_id
    steps = state.get("steps") or {}
    if name == "checkin2":
        pins.update(waypoint_pins(plan.get("waypoints") or [], steps))
        # The GO binds the review round its seats recorded on this waypoint evidence (``checkin2_review``).
        pins["checkin2_review"] = (state.get("reviews") or {}).get("checkin2_record")
    if name == "deviation":
        pins["approved_plan_sha256"] = pins_state.get("approved_sha256") or ""
    if name == "checkin3":
        pins["steps_sha256"] = _digest(steps)
    # Every check-in binds the exact child plans the route steps run under its approval.
    pins.update({f"route:{k}": v["sha256"] for k, v in sorted((pins_state.get("route_children") or {}).items())})
    escalated = escalation_subject(state) if name == "escalate" else {}
    question = escalation_question(state, store, plan) if name == "escalate" else None
    if name == "escalate":
        # Each R3 decision or answer binds the escalations it answers (a later escalation is a new question) and a
        # question the exact asking step or judgment record.
        pins["escalations"] = _digest(escalated)
        pins.update(question["pins"] if question is not None else {})
    shown = {
        "boundaries": _strings(f"{b.get('class')}: {b.get('would_make_possible') or ''}".strip()
                               for b in reading.get("boundaries") or () if type(b) is dict),
        "ambiguities": _strings(a.get("issue") for a in reading.get("ambiguities") or ()
                                if type(a) is dict and a.get("status") == "open" and a.get("issue")),
        "assumptions": _strings(plan.get("assumptions") or []),
    }
    flags = _checkin_flags(name, state, escalated, plan)
    sections, required = [], []
    module = adapter(state, store)
    if module is not None and hasattr(module, "checkin"):
        extra = module.checkin(kind, adapter_context(state, store)) or {}
        if extra.get("errors"):
            raise nodes.RecoveryHold("checkin_incomplete", "; ".join(map(str, extra["errors"]))[:1500])
        sections = deepcopy(extra.get("sections") or [])
        required = list(dict.fromkeys(extra.get("required_sections") or []))
        flags += deepcopy(extra.get("flags") or [])
        for key, rows in (extra.get("items") or {}).items():
            shown[key] = list(shown.get(key) or []) + _strings(rows)
        pins = _merge_checkin_pins(pins, extra.get("pins"))
    supplied = {s.get("id") for s in sections if type(s) is dict}
    sections = [s for s in _checkin_sections(name, state, plan, contract, escalated, question)
                if s["id"] not in supplied] + sections
    if engaged is not None and "engagement" not in supplied:
        sections.append(engagement_section(engaged, engagement_fact_lines(store, engaged["scientific_plan_sha256"])))
    retained = retained_reading(state, store, flags=flags, items=shown)
    view_items = service_function("authority", "retained", "view_items")
    if view_items is not None:
        items = view_items(plan, retained)
    else:
        items = {"steps": _strings(f"{s['id']}: {s['kind']}" + (f" {s['operation']}" if s.get("operation") else "")
                                   + (f" by {s['role']}" if s.get("role") else "")
                                   + (f" [{s['rung']}]" if s.get("rung") else "") for s in plan["steps"]),
                 "deliverables": _strings(f"{d['id']}: " + (f"{d['step']} {d['output']}" if d["status"] == "mapped"
                                                            else f"open ({d.get('reason')})")
                                          for d in plan["deliverables"]),
                 **retained["items"]}
        items = {k: v for k, v in items.items() if v}
    options = []
    if name == "escalate" and question is not None:
        options = deepcopy(question["options"])
    elif name == "escalate":
        options = [{"id": "continue", "text": "let the escalated steps run again", "effect": True},
                   {"id": "hold", "text": "hold the escalated branch; other branches continue", "effect": False}]
    view = {"run_id": store.run_id, "pins": {k: str(v) for k, v in pins.items() if v}, "sections": sections,
            "flags": deepcopy(retained["flags"]), "items": items, "options": options, "required_sections": required,
            "summary": f"route {plan['route']['id']}, plan revision {pins_state.get('revision', 0)}: "
                       f"{len(plan['steps'])} steps, {len(plan['deliverables'])} deliverables"}
    return view, retained, plan


def checkin_view(name, state, store):
    """The typed check-in view (``checkin.v1`` fields) rendered from run state for authority point ``name``."""
    return checkin_material(name, state, store)[0]


def authority_material(name, state, store):
    """``(subject, reading, plan)``: the request subject of authority point ``name`` (its view and the kind's
    own fields) with the retained reading and plan it is decided on."""
    view, reading, plan = checkin_material(name, state, store)
    subject = {"view": view}
    if name == "deviation":
        subject["change"] = _change_row(state)
    if name == "escalate":
        # A stop or decision block holds by default; a question's default is its P7 conservative default, if any
        # (never a default the controller supplies).
        question = escalation_question(state, store, plan)
        default = "hold" if question is None else question["default"]
        if default is not None:
            subject["conservative_default"] = default
        if question is not None and question.get("assumption"):
            # The default is a machine-reasoned assumption (``assumption_requests``), never a plan-declared P7
            # default: the authority takes it only under the operator's ``assumption`` delegation, and says so.
            subject["machine_assumption"] = {k: question["assumption"][k]
                                             for k in ("record", "option", "conditional", "alternatives")}
    return subject, reading, plan


def authority_subject(name, state, store):
    """The request subject for authority point ``name``: its view and the kind's own fields."""
    return authority_material(name, state, store)[0]


def retain(store, kind, *, plan, reading, view):
    """The authority's retained snapshot of the plan and reading a check-in is decided on
    (``retained.capture``), taken by the controller from its own records before it asks, never from a view
    anyone supplied. A snapshot the authority refuses (a plan without steps or deliverables, a request pin
    the plan omits) holds the check-in. Returns the snapshot, or None without a retaining authority."""
    capture = service_function("authority", "retained", "capture")
    if capture is None:
        return None
    try:
        return capture(store, kind, plan=plan, reading=reading, view=view)
    except ValueError as exc:  # the authority's refusal (AuthorityRefused)
        raise nodes.RecoveryHold("checkin_incomplete", f"the authority cannot retain this check-in: {exc}"[:1500])


def authority_bounds(name, state, store):
    """What a decision of authority point ``name`` covers: the plan's bounds, the stages of the route children it
    approves with it (their rung and budget are their route steps', which the plan's bounds count), and for a question
    what answering it lets happen (``answer_bounds``)."""
    if name in ("checkin1", "checkin2", "deviation"):
        bounds = plan_bounds(current_plan(state, store))
        stages = {stage for child in route_children(state, store).values() for stage in plan_bounds(child)["stages"]}
        if stages:
            bounds["stages"] = sorted(set(bounds["stages"]) | stages)
        return bounds
    if name == "escalate":
        question = escalation_question(state, store, current_plan(state, store))
        return deepcopy(question["bounds"]) if question is not None else {}
    return {}


def wait_over(pending):
    """Whether a pending authority answer has waited the operator's wait bound (its own clock)."""
    waited, bound = pending.get("waited_seconds"), pending.get("wait_bound_seconds")
    return type(waited) in (int, float) and type(bound) in (int, float) and waited >= bound


def _unanswered(name, kind, state, store, pending):
    """Unattended, past the wait bound, with no default the authority could take: nothing is authorized.

    The gate that follows refuses, so an escalation holds only its own branch and a check-in ends the
    run in a qualified delivery (an interactive run keeps waiting for the physicist instead).
    """
    store.append("authority-wait", {"kind": kind, "node": name, "request": pending.get("request"),
                                    "waited_seconds": pending.get("waited_seconds"),
                                    "wait_bound_seconds": pending.get("wait_bound_seconds"), "outcome": "held"})
    update = {"loop": {**(state.get("loop") or {}), f"{name}_decision": "unanswered", f"{name}_option": None},
              **_status(name, f"no {kind} authority within the operator's wait bound")}
    if name == "escalate":  # the gate refuses, and the unanswered escalations hold their branches
        update["escalations"] = {k: {**v, "status": "unanswered", "kind": kind}
                                 for k, v in escalation_rows(state).items()}
    return update


def pending_answer(kind, answer):
    """The pending part of the authority's ``answer`` for a ``kind`` decision, or None for a record its gate checks.

    A pending answer is ``{"pending": {...}}`` (with ``unattested_record`` when the physicist typed an answer at the
    controller's terminal). Defensively, a record labelled ``terminal_operator_unattested`` whose decision would
    let the transition proceed is pending as well: an unattested terminal answer proves no identity and never
    authorizes by itself, so the point keeps waiting for the operator's authenticated answer. A typed refusal
    only restricts and is taken as it is.
    """
    if type(answer) is not dict:
        return None
    if "pending" in answer:
        found = answer["pending"]
        pending = deepcopy(found) if type(found) is dict else {"reason": str(found)}
        if answer.get("unattested_record"):
            pending["unattested_record"] = answer["unattested_record"]
        return pending
    if answer.get("label") == TERMINAL_UNATTESTED and answer.get("decision") in ACCEPTED[kind]:
        return {"request": answer.get("request"), "kind": kind,
                "reason": "terminal identity is unattested; no approval granted",
                "needed": "an authenticated operator answer",
                "unattested_record": answer.get("id") or answer.get("record_id")}
    return None


def operator_answer_hint(store, kind, subject, pending):
    """How the operator answers a pending request (shown in the pause): ``ravel operator answer`` quoting the
    request and the challenge code printed with its WAITING line and sent through the operator notification. The
    answer is recorded as an operator command; nothing typed at the terminal attests a person's identity."""
    request = pending.get("request")
    decision = (" or ".join(o["id"] for o in subject["view"].get("options") or () if o.get("effect", True))
                if kind in ("r3_action", "escalation") else ACCEPTED[kind][0])
    command = (f"ravel operator answer --run {store.run_id} --request {request} --code <code> --decision <decision>"
               if request else f"ravel operator status --run {store.run_id}")
    return {"command": command, "request": request, "decision": decision or "reject",
            "code": "the challenge code printed with the request's WAITING line and sent to the operator",
            "needed": pending.get("needed"), "unattested_record": pending.get("unattested_record"),
            "terminal_identity_attested": False}


def authority_point(name):
    """Ask the authority service; pause only while its answer is pending. A resume value is a poll.

    An unattended run stops waiting once the operator's wait bound has passed: the authority service
    takes its recorded conservative default on that poll when one exists, otherwise nothing is authorized.
    An interactive run keeps waiting, also after an approval typed at the controller's terminal (unattested,
    ``pending_answer``): the pause names the operator-answer step, and the gate later checks only an
    authenticated record. The escalation point asks the kind of its subject (``point_kind``) and records the answer
    on the escalations it asked; they are settled only after the gate verified it (``settle_answers``).
    """
    def body(state):
        from langgraph.types import interrupt as pause
        kind = point_kind(name, state)
        store = _store(state)
        engaged = None
        if name in ENGAGED_POINTS:
            # The engagement decision is taken as the plan-approving check-in renders; its applied view is pinned
            # beside the scientific plan, and the view shows (and the authority binds) the decision.
            engaged = engage(state, store)
            state = {**state, "plan": engaged}
        subject, reading, plan = authority_material(name, state, store)
        # The snapshot the authority decides on, taken before every request (identical on a poll).
        retain(store, kind, plan=plan, reading=reading, view=subject["view"])
        bounds = authority_bounds(name, state, store)
        authority = service("authority")
        if kind == "approve_plan":
            from .authority import rdj
            if rdj.classification(store, subject["view"]["pins"])[0] == "R3":
                rdj.dispatch(store, state, _gate_action("checkin1_gate", state, subject["view"]["pins"]),
                             _context(state, store, purpose="plan"))
        if kind == "go":
            from .authority import rdj
            rdj.dispatch(store, state, _gate_action("checkin2_gate", state, subject["view"]["pins"]),
                         _context(state, store, purpose="waypoint"))
        if kind == "deviation":
            # The composed authority's own seam (as for the final task): a stand-in authority dispatches nothing.
            review_deviation = getattr(authority, "review_deviation", None)
            if callable(review_deviation):
                review_deviation(store, state, _gate_action("deviation_gate", state, subject["view"]["pins"]),
                                 _context(state, store, purpose="plan"))
        if kind == "final":
            review_final = getattr(authority, "review_final_task", None)
            if callable(review_final):
                review_final(store, state, _context(state, store, purpose="final"))
        unattended = bool((state.get("run") or {}).get("unattended"))
        answer = authority.request(store, kind, subject, bounds)
        polls = 0
        while pending_answer(kind, answer) is not None:
            pending = pending_answer(kind, answer)
            if unattended and wait_over(pending):
                return {**_unanswered(name, kind, state, store, pending),
                        **({"plan": engaged} if engaged is not None else {})}
            polls += 1
            if polls > MAX_POLLS:
                raise nodes.RecoveryHold("authority_unanswered", f"no {kind} authority after {MAX_POLLS} polls")
            pause({"kind": AUTHORITY_SCHEMA, "schema_id": AUTHORITY_SCHEMA, "graph_id": GRAPH_ID, "node": name,
                   "authority_kind": kind, "subject_sha256": _digest(subject["view"]["pins"]),
                   "pending": pending, "operator_answer": operator_answer_hint(store, kind, subject, pending),
                   "approval_from_resume": False},
                  response_schema=graph_registry.response_schema(AUTHORITY_SCHEMA))
            answer = authority.request(store, kind, subject, bounds)
        if type(answer) is not dict:
            raise nodes.RecoveryHold("authority_invalid", "the authority service returned no record")
        record_id = answer.get("id") or answer.get("record_id")
        decision, option = answer.get("decision"), answer.get("option")
        if record_id:
            # The check-in's own rows, from the record the authority authenticates, before its gate checks them.
            _record_checkin_rows(store, name, kind, record_id, subject["view"]["pins"],
                                 ACCEPTED.get(kind, GATES[GATE_OF[name]][3]))
            if name == "checkin1":
                _record_operation_commit(store, kind, record_id, subject["view"]["pins"], plan,
                                         GATES[GATE_OF[name]][3])
                _record_raise_row(store, kind, record_id, subject["view"]["pins"], GATES[GATE_OF[name]][3])
        _record_mechanism_rows(store, f"controller.{name}")
        update = {"authority": {kind: [record_id] if record_id else []},
                  "loop": {**(state.get("loop") or {}), f"{name}_decision": decision, f"{name}_option": option},
                  **_status(name, f"{kind} authority {decision}")}
        if engaged is not None:
            update["plan"] = engaged
        if name == "escalate":
            # Nothing runs on this answer yet: the gate verifies the record first, and only a verified answer is
            # settled (``settle_answers``); a refused or unverified one holds the branch (``escalation_held``).
            update["escalations"] = {k: {**v, "status": "asked", "kind": kind, "authority": record_id,
                                         "decision": decision, "option": option}
                                     for k, v in escalation_rows(state).items()}
        return update
    body.__name__ = "authority_" + name
    return nodes.Node("interrupt", body, interrupt_kind=AUTHORITY_SCHEMA)


def _authority_record(store, record_id):
    """The authority record ``record_id`` names, matched on the store's id or the authority's ``uid`` through the
    authority service's own authenticated reader (``records``); None when it offers no reader or no such record."""
    reader = getattr(service("authority"), "records", None)
    if not callable(reader) or type(record_id) is not str or not record_id:
        return None
    for row in reader(store) or ():
        if type(row) is dict and record_id in (row.get("id"), row.get("uid")):
            return row
    return None


def _authority_errors(store, state, gate_node, pins):
    kind = point_kind(POINTS[gate_node], state)
    accepted = ACCEPTED[kind]

    def error(code, message):
        return {"code": code, "gate": GATE_NAMES[gate_node], "provider": "controller.authority", "message": message,
                "fix": "obtain the decision from the operator or physicist through the authority service", "pins": []}
    record_id = _latest_authority(state, kind)
    if not record_id:
        return [error("authority_missing", f"no {kind} authority record")]
    try:
        record = _authority_record(store, record_id)
    except Exception as exc:  # the authority service could not authenticate the run's records
        return [error("authority_refused", str(exc)[:1000])]
    if record is None:
        return [error("authority_missing", f"the {kind} authority record {record_id} is not in the store")]
    if record.get("label") == "human_operator":
        return [error("authority_label", "a human label inferred from the terminal is not authority")]
    try:
        record, _ = authenticated(store, kind, record_id, pins)
    except _Unverifiable as exc:
        return [error("authority_unverified", str(exc)[:1000])]
    except _GrantsTooMuch as exc:
        return [error("authority_invalid", str(exc)[:1000])]
    except Exception as exc:  # the authority service's refusal is the gate's error
        return [error("authority_refused", str(exc)[:1000])]
    if record.get("decision") not in accepted:
        return [error("authority_not_granted", f"the {kind} decision is {record.get('decision')!r}")]
    return []


def checkin2_review_errors(state, store, gate_name):
    """The CHECK-IN 2 gate's own check of its seats' review: the round the run state names is in the store, reviewed
    the current waypoint outputs of this plan and every seat credited and accepted it. Anything else refuses the GO."""
    def error(code, message):
        return [{"code": code, "gate": gate_name, "provider": "controller.review", "message": message,
                 "fix": "run the CHECK-IN 2 seats on the current waypoint evidence", "pins": [str(record_id or "")]}]
    record_id = (state.get("reviews") or {}).get("checkin2_record")
    try:
        row = store.read("review", record_id) if record_id else None
    except (ValueError, KeyError):
        row = None
    if row is None:
        return error("checkin2_review_missing", f"no CHECK-IN 2 review round {record_id or ''} is in the store")
    plan = current_plan(state, store)
    record = row["record"]
    subject = waypoint_subject(list(plan.get("waypoints") or []), state.get("steps") or {})
    if (record.get("purpose"), record.get("plan_sha256"), record.get("subject_sha256")) != (
            "waypoint", plan["sha256"], subject["sha256"]):
        return error("checkin2_review_stale", "the CHECK-IN 2 review round is not of the current waypoint evidence")
    if not _accepted(record.get("seats") or {}):
        return error("checkin2_review_not_accepted", "a CHECK-IN 2 seat did not credit and accept the waypoint")
    return []


def deviation_event(plan_pins):
    """The ledger's occurrence id of the deviation that the current plan digest opened."""
    return f"deviation-{(plan_pins.get('sha256') or '')[:16]}"


def _gate_action(gate_node, state, pins):
    """The decision gate's action for a check-in: its digest is the canonical digest of the view's pins, which the
    action carries (``view_pins``) so a provider can verify which plan the decision is about."""
    gate_name = GATE_NAMES[gate_node]
    if gate_name == "approve_plan":
        from .authority.rdj import approval_action
        return approval_action(pins)
    action = {"kind": f"controller.{gate_name}", "digest": _digest(pins), "summary": f"controller {gate_name}",
              "pins": [], "node_id": None, "rung": None, "scope": None, "view_pins": deepcopy(pins)}
    plan = state.get("plan") or {}
    if gate_node == "checkin2_gate":
        action["waypoint"] = ",".join(plan.get("waypoints") or [])
    if gate_node == "deviation_gate":
        action["event"] = deviation_event(plan)
    if gate_node == "checkin3_gate":
        # The final task names what it delivers: each accepted output with the original requirements it answers.
        from ..workflow import review_points
        action.update(review_points.delivery_action(_run_dir(state)))
    return action


def transitions(gate_node, state):
    """The ledger transitions a gate checks: one per waypoint for CHECK-IN 2, the occurrence for a deviation."""
    template = GATES[gate_node][1]
    plan = state.get("plan") or {}
    if "{waypoint}" in template:
        return [template.format(waypoint=w) for w in plan.get("waypoints") or []] or [template.split("[")[0]]
    if "{event}" in template:
        return [template.format(event=deviation_event(plan))]
    return [template]


def controller_gate(gate_node):
    """Gate node (read-only): decision gate on the run directory, ledger transition, route and authority record."""
    decision_gate_name, transition, kind, _ = GATES[gate_node]
    gate_name = GATE_NAMES[gate_node]
    point = POINTS[gate_node]

    def body(state):
        store = _store(state)
        meta = nodes._meta(state)
        pins = checkin_view(point, state, store)["pins"]
        action = _gate_action(gate_node, state, pins)
        errors = []
        if decision_gate_name is not None:
            errors.extend(nodes.check_gate(str(_run_dir(state)), decision_gate_name, action, graph_id=meta["graph_id"]))
        checked = transitions(gate_node, state)
        for each in checked:
            errors.extend(ledger_errors(store, each, gate_name))
        module = adapter(state, store)
        if module is not None and hasattr(module, "gate"):
            for each in checked:
                errors.extend(_adapter_errors(module.gate(each, adapter_context(state, store)), gate_name))
        if gate_node == "checkin2_gate":
            errors.extend(checkin2_review_errors(state, store, gate_name))
        if gate_node == "checkin3_gate":
            errors.extend(attack_errors(state, store, gate_name))
        errors.extend(_authority_errors(store, state, gate_node, pins))
        store.append("gate", {"gate": gate_name, "transition": ",".join(checked), "subject_sha256": action["digest"],
                              "passed": not errors, "errors": deepcopy(errors)[:50]})
        providers = sorted({e.get("provider", "") for e in errors})
        update = {"gates": {gate_name: {"action_digest": action["digest"], "errors": errors, "providers": providers,
                                        "checked_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                        "sequence": time.time_ns()}}}
        if errors:
            # A refused gate ends the run: its ending states the refusal, not the authority's answer before it.
            update.update(_status(gate_node, f"the {gate_name} gate refused ({', '.join(providers)}): "
                                  + "; ".join(str(e.get("message")) for e in errors[:3])))
        return update
    body.__name__ = "controller_gate_" + gate_name
    return nodes.Node("gate", body, gate=gate_name)


def _decide(state, store, gate_node):
    """The acting node's re-check of a passed gate: the ledger discharges the decision only on a pass."""
    point = POINTS[gate_node]
    pins = checkin_view(point, state, store)["pins"]
    action = _gate_action(gate_node, state, pins)
    ledger = service("ledger")
    waypoints = action["waypoint"].split(",") if gate_node == "checkin2_gate" and action.get("waypoint") else [None]
    errors = []
    for waypoint in waypoints:
        each = {**action, "waypoint": waypoint} if waypoint else action
        errors.extend(ledger.decide(store, str(_run_dir(state)), GATES[gate_node][0], each) or [])
    if errors:
        messages = "; ".join(str(e.get("message") if type(e) is dict else getattr(e, "message", e)) for e in errors)
        raise nodes.RecoveryHold("decision_refused", f"{GATES[gate_node][0]}: {messages}"[:1500])


def approved(state):
    """After CHECK-IN 1 passes: the decision is discharged and the approved plan digest is the current one."""
    store = _store(state)
    _decide(state, store, "checkin1_gate")
    record_conditional_approval(state, store)
    plan = state.get("plan") or {}
    return {"plan": {**plan, "approved_sha256": plan.get("sha256"), "scope_changed": False, "changed_steps": [],
                     "recovery_direction": None},
            **_status("approved", "plan approved")}


def approved_deviation(state):
    store = _store(state)
    _decide(state, store, "deviation_gate")
    _record_mechanism_rows(store, "controller.approved_deviation")
    plan = state.get("plan") or {}
    return {"plan": {**plan, "approved_sha256": plan.get("sha256"), "scope_changed": False, "changed_steps": [],
                     "recovery_direction": None},
            "replans": {k: {**v, "status": "approved"} for k, v in (state.get("replans") or {}).items()
                        if v.get("status") == "replanned"},
            **_status("approved", "deviation approved")}


def checkin1_refused(state):
    decision = (state.get("loop") or {}).get("checkin1_decision")
    gate = (state.get("gates") or {}).get(GATE_NAMES["checkin1_gate"]) or {}
    # An approval the gate refused keeps the gate's own reason (which providers refused), not "not approved".
    reason = (state.get("status") or {}).get("reason") if decision in ACCEPTED["approve_plan"] and gate.get("errors") \
        else f"CHECK-IN 1 not approved ({decision})"
    return {"loop": {**(state.get("loop") or {}), "checkin1_refused": decision}, **_status("checkin1", reason)}


def _checkin1_refused_branch(state):
    decision = (state.get("loop") or {}).get("checkin1_decision")
    if decision in ("adjust", "revise") and (state.get("plan") or {}).get("revision", 0) < MAX_PLAN_REVISIONS:
        return "revise"
    return "end"


def went(state):
    store = _store(state)
    _decide(state, store, "checkin2_gate")
    plan = state.get("plan") or {}
    return {"plan": {**plan, "go_waypoints": list(plan.get("waypoints") or []), "go_sha256": plan.get("sha256")},
            **_status("checkin2", "GO recorded for the waypoint")}


# Why an escalation's branch holds when its gate refused, by kind: never answered, or refused (a conservative default
# that lets nothing happen is ``conservative_default_hold`` for every kind).
HELD_REASONS = {"ask": ("ask_unanswered", "ask_refused"), "decide": ("decision_authority_unanswered",
                                                                     "decision_authority_refused")}


def held_reason(row):
    """The typed hold of one escalation its gate refused (``HELD_REASONS``)."""
    unanswered, refused = HELD_REASONS.get(row.get("escalation"), ("escalation_refused", "escalation_refused"))
    if row.get("status") == "unanswered" or row.get("decision") is None:
        return {"reason": unanswered, "would_make_possible": "an authenticated answer from the operator or physicist"}
    if row.get("decision") == "default":
        return {"reason": "conservative_default_hold",
                "would_make_possible": "an authority record letting the step continue"}
    return {"reason": refused, "would_make_possible": "an authority record for the action"}


def escalation_held(state):
    """The escalation gate refused: the escalations its request asked hold their steps; other branches, and pending
    escalations it did not ask about, continue."""
    rows = state.get("escalations") or {}
    held = {k: v for k, v in rows.items() if v.get("status") in ("asked", "unanswered", "held")}
    known = state.get("holds") or {}
    _record_mechanism_rows(_store(state), "controller.escalation_held")
    return {"escalations": {k: {**v, "status": "held"} for k, v in held.items()},
            "steps": {k: {**(state.get("steps") or {}).get(k, {}), "status": "held"} for k in held},
            "holds": {k: held_reason(v) for k, v in held.items() if k not in known},
            **_status("escalation", "escalated steps held")}


# ---- decisions and answers: the judgment package's requirements on the schedule -----------------------------------

DECISIONS = "judgment-record"  # the judgment package's store record of one judgment call (judgment-record.v1)


def _record_sha256(body):
    """A judgment record's own digest (judgment-record.v1): canonical JSON of every field but ``record_sha256``."""
    return hashlib.sha256(json.dumps({k: v for k, v in body.items() if k != "record_sha256"}, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def judgment_record(state, store, step_id):
    """The judgment record the latest attempt of decide step ``step_id`` wrote (its outcome's ``judgments``): read
    from the store, naming this step, of a known class, its digest its own; else None."""
    for record_id in reversed(list((state.get("judgments") or {}).get(step_id) or ())):
        try:
            entry = store.read(DECISIONS, record_id)
        except (ValueError, KeyError, TypeError):
            continue
        body = entry["record"]
        if (type(body) is dict and body.get("step") == step_id and body.get("class") in CLASS_RANK
                and body.get("record_sha256") == _record_sha256(body)):
            return {**deepcopy(body), "judgment_id": entry["id"]}
    return None


def decision_class(step, record):
    """A decision's consequence class: its record's, raised (never lowered) by the class its plan step declared."""
    planned = step.get("consequence_class")
    return max((record["class"], planned if planned in CLASS_RANK else "R0"), key=CLASS_RANK.get)


def _choices(options):
    """A record's or a plan step's options as offered choices ``{id, text}`` (``reject`` is every request's own)."""
    return [{"id": o["id"], "text": " ".join(str(o.get("description") or o.get("text") or o["id"]).split())[:500]}
            for o in options or () if type(o) is dict and type(o.get("id")) is str and o["id"].lower() != "reject"]


def _reviewer_items(record):
    """The judgment package's must-check items for the reviewer of a decision record, when it offers them."""
    items = service_function("judgment", "records", "reviewer_items")
    try:
        return deepcopy(items(record)) if items is not None else None
    except (KeyError, TypeError, ValueError):
        return None


def rdj_case(state, store, plan, step, record, steps):
    """The RDJ case an R2 or R3 decision needs before its dependents run: an independent review (``RDJ_ROLE``) of its
    exact judgment record, credited and accepting, kept as a ``review`` round of purpose ``rdj``. A round recorded on
    this record is reused (a re-entered wave never asks it again); otherwise the seat runs now. ``(case, correction,
    problem)``: a credited ``revise`` within the correction rounds corrects the decision (it runs again with the
    findings pinned); a refused or missing credit or used-up rounds is a ``problem`` that holds it."""
    sid, subject_sha = step["id"], record["record_sha256"]
    rounds = [r for r in store.scan("review") if r["record"].get("purpose") == "rdj" and r["record"].get("step") == sid]
    found = next((r for r in reversed(rounds) if r["record"].get("subject_sha256") == subject_sha
                  and r["record"].get("plan_sha256") == plan["sha256"]), None)
    if found is not None:
        verdicts, attempt, case = deepcopy(found["record"]["seats"]), found["record"]["attempt"], found["id"]
    else:
        subject = {"steps": [sid], "artifacts": _artifacts([sid], steps), "pins": {f"judgment:{sid}": subject_sha},
                   "sha256": subject_sha}
        verdicts, attempt, case = _run_seats(state, store, [RDJ_ROLE], purpose="rdj", subject=subject,
                                             review_items=_reviewer_items(record), step_id=f"rdj_review.{sid}",
                                             attempt=len(rounds) + 1,
                                             extra={"step": sid, "judgment": record["judgment_id"]})
    if _accepted(verdicts):
        return case, None, None
    correction, problem = review_correction(store, purpose="rdj", verdicts=verdicts, subject_sha256=subject_sha,
                                            attempt=attempt, done=int((steps.get(sid) or {}).get("corrections") or 0),
                                            bound=correction_rounds(state))
    return None, correction, problem


def close_decides(state, store, plan, steps):
    """Close each completed ``decide`` step whose judgment's requirements hold (JR05 and the effect readiness of its
    class): its judgment record; at R1 a report at the next check-in; at R2 and R3 its RDJ case (``rdj_case``); at R3
    current authority for its recorded choice, asked at the escalation point (``settle_answers`` closes it). A
    decision without its record, or whose RDJ case was refused, holds its branch; one waiting for its R3 answer stays
    completed and not closed. ``(rows, holds, escalations, flags)``."""
    rows, holds, escalations, flags = {}, {}, {}, {}
    known = state.get("escalations") or {}
    pins = state.get("plan") or {}
    report = "checkin2" if pins.get("waypoints") and not pins.get("go_sha256") else "checkin3"
    module = None
    for step in plan["steps"]:
        sid, row = step["id"], steps.get(step["id"]) or {}
        if step["kind"] != "decide" or row.get("status") != STEP_DONE or row.get("closed") is True:
            continue
        record = judgment_record(state, store, sid)
        if record is None:
            rows[sid] = {**row, "status": "held", "reason": "judgment_record_missing: a decision closes only with its "
                                                              "judgment record"}
            holds[sid] = {"reason": "judgment_record_missing",
                          "would_make_possible": "the decision's judgment record, recorded by the judgment package"}
            continue
        module = module or adapter(state, store)
        if module is not None and hasattr(module, "decided"):
            # The route checks the stored record against the step as planned only now, after the decide close found it.
            problems = module.decided(deepcopy(step), deepcopy(record), adapter_context(state, store)) or []
            if problems:
                rows[sid] = {**row, "status": "held",
                             "reason": ("judgment_record_refused: " + "; ".join(map(str, problems)))[:600]}
                holds[sid] = {"reason": "judgment_record_refused",
                              "would_make_possible": "a judgment record that satisfies the decide step as planned"}
                continue
        cls = decision_class(step, record)
        judgment = {"record": record["judgment_id"], "class": cls, "record_sha256": record["record_sha256"]}
        if CLASS_RANK[cls] < 2:
            rows[sid] = {**row, "closed": True, "judgment": judgment}
            if cls == "R1":
                flags.setdefault(report, []).append({"step": sid, "note": f"R1 decision {record['judgment_id']} chose "
                                                                          f"{record.get('chosen')}"})
            continue
        case, correction, problem = rdj_case(state, store, plan, step, record, steps)
        if problem is not None:
            rows[sid] = {**row, "status": "held", "judgment": judgment,
                         "reason": f"{problem[0]}: the RDJ case of {sid}: {problem[1]}"[:600]}
            holds[sid] = {"reason": problem[0], "would_make_possible": "an RDJ case credited on the exact judgment record"}
            continue
        if correction is not None:
            rows.update(correction_steps(plan, steps, [sid], correction))
            rows[sid] = {**rows[sid], "corrections": int(row.get("corrections") or 0) + 1}
            continue
        judgment["rdj"] = case
        rows[sid] = {**row, "judgment": judgment, **({"closed": True} if cls == "R2" else {})}
        asked = known.get(sid) or {}
        if cls == "R2" or (asked.get("escalation") == "decide" and asked.get("record_sha256") == record["record_sha256"]):
            continue
        escalations[sid] = {"status": "pending", "escalation": "decide", "attempt": row.get("attempts"),
                            "reason": f"R3 decision: {record.get('question')}", "question": record.get("question"),
                            "record": record["judgment_id"], "record_sha256": record["record_sha256"],
                            "chosen": record.get("chosen"), "options": _choices(record.get("options")),
                            "default": record.get("default_option") if record.get("default") else None}
    return rows, holds, escalations, flags


def settle_answers(state, store, plan, steps):
    """The escalations whose answer the escalation gate passed (``asked``), settled: the record is checked again on the
    current pins (``_authority_errors``), then the steps of a stop or decision block run again on an approval or a
    default that lets them continue; an ``ask`` keeps the option the answer selected (the step completes, and its
    dependents receive the answer); an R3 decision closes when its recorded choice was authorized. Any other answer
    holds its branch. ``(rows, holds, escalations)``."""
    asked = {k: v for k, v in (state.get("escalations") or {}).items() if v.get("status") == "asked"}
    if not asked:
        return {}, {}, {}
    question = escalation_question(state, store, plan)
    errors = _authority_errors(store, state, "escalate_gate", checkin_view("escalate", state, store)["pins"])
    effects = {o["id"] for o in (question or {}).get("options") or () if o.get("effect")}
    rows, holds, settled = {}, {}, {}
    for sid, row in sorted(asked.items()):
        decision, option, current = row.get("decision"), row.get("option"), steps.get(sid) or {}
        if row.get("escalation") == "ask":
            taken = decision in ("answer", "default") and option in effects and (
                decision == "answer" or option == question["default"])
        elif row.get("escalation") == "decide":
            taken = decision in ("approve", "default") and option == row.get("chosen") and option in effects
        else:
            taken = decision == "approve" or (decision == "default" and option == "continue")
        if errors or not taken:
            rows[sid], settled[sid] = {**current, "status": "held"}, {**row, "status": "held"}
            holds[sid] = held_reason(row) if not errors else {"reason": "escalation_unverified",
                                                              "would_make_possible": errors[0]["message"][:500]}
            continue
        settled[sid] = {**row, "status": "resolved", "selected": option}
        if decision == "default" and not (row.get("assumption") or {}).get("option") == option:
            # A plan-declared conservative default the operator's machine authority took: listed with every other
            # assumption the delivery reports (``delivery_assumption_subject``) and audited at K8.
            store.append(ASSUMPTION_KIND, {
                "schema_version": 1, "phase": "default_taken", "step": sid, "attempt": row.get("attempt"),
                "option": option, "authority": row.get("authority"),
                "assumptions": [{"statement": f"MACHINE DEFAULT: the {row.get('escalation')} of step {sid} took its "
                                              f"plan-declared conservative default {option}; nobody answered within "
                                              "the operator's wait bound.", "kind": "machine_default", "step": sid,
                                 "option": option, "conditional": False}]})
        if row.get("escalation") == "ask":
            assumed = row.get("assumption") if decision == "default" and (row.get("assumption") or {}).get(
                "option") == option else None
            rows[sid] = {**current, "status": STEP_DONE, "reason": f"answered: {option}" + (
                         " (machine assumption" + (", conditional" if (assumed or {}).get("conditional") else "")
                         + ")" if assumed else ""),
                         "answer": {"option": option, "decision": decision, "authority": row.get("authority"),
                                    "bounds": deepcopy(question["bounds"]),
                                    **({"machine_assumption": deepcopy(assumed)} if assumed else {})}}
            # The ask step completes on its verified answer: its outcome is the controller's record (no worker ran),
            # which the governed step's parent check of every dependent reads.
            from .step import custody as step_custody
            step_custody.record_outcome(store, {"id": sid}, row.get("attempt"), STEP_DONE,
                                        reason=rows[sid]["reason"], answer=deepcopy(rows[sid]["answer"]),
                                        recorded_by="controller.settle_answers", outputs=[], receipts=[])
            _close_answered_seat(store, sid, row.get("authority"))
            if assumed:
                store.append(ASSUMPTION_KIND, {"schema_version": 1, "phase": "taken", "step": sid,
                                               "attempt": row.get("attempt"), "record": assumed.get("record"),
                                               "option": option, "conditional": bool(assumed.get("conditional")),
                                               "authority": row.get("authority")})
        elif row.get("escalation") == "decide":
            rows[sid] = {**current, "closed": True,
                         "judgment": {**(current.get("judgment") or {}), "authority": row.get("authority")}}
        else:  # the operator or physicist let the escalated steps continue: each runs again
            rows[sid] = {**current, "status": "retry"}
    return rows, holds, settled


def _close_answered_seat(store, step_id, authority):
    """The seat rows of an answered ``ask`` still pending (review-class rows need a credit for their reason): no worker
    ran, so they do not apply, and the authenticated answer that completed the step is the decision that says so."""
    ledger = _row_ledger()
    if ledger is None or not authority:
        return []
    closed = []
    for row in ledger.current(store, step=step_id):
        if row["status"] != "pending" or "/seat=" not in row["entry"]:
            continue
        try:
            ledger.record(store, row["entry"], "not_applicable", {
                "reason": "not_applicable:parent_request_answered", "credit": authority, "authority": authority,
                "mechanism": "controller.settle_answers", "detail": "an answered question runs no worker"})
            closed.append(row["entry"])
        except Exception as exc:  # a row the ledger refuses stays pending and holds its gate
            store.append("step-ledger-refused", {"step_id": step_id, "entry": row["entry"],
                                                 "reason": f"{type(exc).__name__}: {exc}"[:500]})
    return closed


# ---- the wave executor -----------------------------------------------------------------------

def closed(step_id, steps, decides=()):
    """Whether step ``step_id`` closed: it completed and, a ``decide`` step, its judgment's requirements hold (its
    row is ``closed``: the record, and at R2 or R3 its RDJ case and R3 authority, ``close_decides``)."""
    row = steps.get(step_id) or {}
    return row.get("status") == STEP_DONE and (step_id not in decides or row.get("closed") is True)


def ready_steps(plan_pins, steps, *, go=True, phase=None):
    """Ids of steps whose dependencies closed and that are neither running nor finished, in plan order.

    ``phase="prepare"`` selects prepare steps only. Steps at the ``full`` or ``scan`` rung wait for the
    CHECK-IN 2 GO when the plan has waypoints. A step in a correction round (``correct``) runs again. The
    dependents of a ``decide`` step wait until it closed (``closed``), not only completed.
    """
    prepare = set(plan_pins.get("prepare") or [])
    decides = set(plan_pins.get("decides") or [])
    ready = []
    for step_id in plan_pins.get("steps") or ():
        if phase == "prepare" and step_id not in prepare:
            continue
        row = steps.get(step_id) or {}
        if row.get("status") not in (None, "retry", CORRECT):
            continue
        parents = plan_pins.get("depends", {}).get(step_id) or []
        if not all(closed(p, steps, decides) for p in parents):
            continue
        if not go and row.get("rung") in ("full", "scan"):
            continue
        ready.append(step_id)
    return ready


def _native_authority_ready(store, plan, ready):
    """Keep the run's single current R3 view exact until its native action finishes.

    Consequential launches dispatch alone: another capture of the same decision kind would
    supersede the first while its governed critic or operator answer is pending. Deferred
    steps retain their readiness. The exact prelaunch gate recomputes consequence and authority.
    """
    from .step import launch_gate, spec
    from ravel.workflow import rdj_loop
    by_id = {step["id"]: step for step in plan["steps"]}
    for step_id in ready:
        step = by_id[step_id]
        if spec.branch(step) != "launch":
            continue
        try:
            cls, _ = rdj_loop.compute_class(store.run_dir, "launch", launch_gate.consequence_action(step))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            raise nodes.RecoveryHold("native_consequence_unavailable", str(exc)[:1500]) from None
        if rdj_loop.RANK[cls] > rdj_loop.RANK["R2"]:
            return [step_id]
    return list(ready)


def _admitted(state, store, plan, ready, steps):
    """The route's admission of each ready step (``admit(step, context)``): a refused step is held, not sent."""
    if not ready:
        return [], {}, {}
    route = state.get("route") or {}
    try:
        pin = route.get("record_id")
        record = store.read("route", pin)["record"] if isinstance(pin, str) and pin else None
        pinned = isinstance(route.get("id"), str) and bool(route["id"]) and isinstance(record, dict) \
            and record.get("route") == route["id"]
    except (OSError, ValueError, KeyError, TypeError):
        pinned = False
    if not pinned:
        text = "route_not_pinned: select the route and pin its controller-store record before dispatch"
        held = {s: {**(steps.get(s) or {}), "status": "held", "reason": text} for s in ready}
        holds = {s: {"reason": "route_not_pinned", "would_make_possible": text} for s in ready}
        store.append("admission", {"held": list(ready), "code": "route_not_pinned",
                                   "reasons": {s: text for s in ready}})
        return [], held, holds
    module = adapter(state, store)
    if module is None or not hasattr(module, "admit"):
        return list(ready), {}, {}
    context = adapter_context(state, store)
    by_id = {s["id"]: s for s in plan["steps"]}
    admitted, held, holds = [], {}, {}
    for step_id in ready:
        errors = module.admit(deepcopy(by_id[step_id]), context) or []
        if not errors:
            admitted.append(step_id)
            continue
        text = "; ".join(str(e.get("message") if type(e) is dict else e) for e in errors)[:1000]
        held[step_id] = {**(steps.get(step_id) or {}), "status": "held", "reason": "admission refused: " + text}
        holds[step_id] = {"reason": "admission_refused", "would_make_possible": text}
    if held:
        store.append("admission", {"held": sorted(held), "reasons": {k: v["would_make_possible"]
                                                                       for k, v in holds.items()}})
    return admitted, held, holds


def _governed(state, store):
    """Hold before further scientific work when the run's directory shows a layout written outside the
    controller (a run-root or non-epoch-two contract, SW26): ``routes.legacy.governed_errors``."""
    from .routes import legacy
    errors = legacy.governed_errors(_run_dir(state), store.run_id)
    if errors:
        raise nodes.RecoveryHold("legacy_layout", "; ".join(errors)[:1500])


def _items(plan, steps, ready):
    """The wave's items: each ready step with its next attempt and, in a correction round, the round (its findings)."""
    by_id = {s["id"]: s for s in plan["steps"]}
    items = []
    for step_id in ready:
        row = steps.get(step_id) or {}
        item = {"step": deepcopy(by_id[step_id]), "attempt": row.get("attempts", 0) + 1}
        if row.get("status") == CORRECT and row.get("correction"):
            item["correction"] = deepcopy(row["correction"])
        items.append(item)
    return items


def _with_rungs(state, plan):
    steps = deepcopy(state.get("steps") or {})
    for step in plan["steps"]:
        steps.setdefault(step["id"], {})
        steps[step["id"]].setdefault("rung", step.get("rung"))
    return steps


def prepare_wave(state):
    """Before CHECK-IN 1: run the plan's prepare steps (the evidence the check-in presents), then review."""
    store = _store(state)
    _governed(state, store)
    plan_pins = state.get("plan") or {}
    plan = current_plan(state, store)
    steps = _with_rungs(state, plan)
    wave = deepcopy(state.get("loop") or {})
    prepare = list(plan_pins.get("prepare") or [])
    reached = _boundary_reached(store)
    ready, held, holds = ([], {}, {}) if reached else _admitted(
        state, store, plan, ready_steps(plan_pins, steps, phase="prepare"), steps)
    ready = _native_authority_ready(store, plan, ready)
    steps.update(held)
    if reached:
        decision, reason, ready = "blocked", reached, []
    elif ready:
        decision, reason = "dispatch", f"{len(ready)} prepare step(s) ready"
    elif all((steps.get(s) or {}).get("status") == STEP_DONE for s in prepare):
        decision, reason, ready = "review", "the prepare phase is complete", []
    else:
        waiting = {s: (steps.get(s) or {}).get("status") for s in prepare
                   if (steps.get(s) or {}).get("status") != STEP_DONE}
        decision, reason = "blocked", "prepare steps cannot complete: " + json.dumps(waiting, sort_keys=True)[:500]
    number = wave.get("number", 0) + 1
    store.append("wave", {"number": number, "phase": "prepare", "decision": decision, "reason": reason,
                          "ready": ready, "plan_sha256": plan_pins.get("sha256")})
    update = {"loop": {**wave, "number": number, "phase": "prepare", "decision": decision, "reason": reason,
                       "items": _items(plan, steps, ready), "candidate": None},
              **_status("prepare", reason)}
    if held:
        update.update(steps=held, holds=holds)
    return update


def _prepare_branch(state):
    return (state.get("loop") or {}).get("decision") if (state.get("loop") or {}).get("decision") in (
        "dispatch", "review") else "blocked"


def bind(state):
    """After the prepare phase: the route may re-bind the plan from what the prepare steps found."""
    store = _store(state)
    module = adapter(state, store)
    if module is None or not hasattr(module, "bind"):
        return _status("bind", "no route binding")
    old = current_plan(state, store)
    try:
        plan = module.bind(old, adapter_context(state, store)) or old
    except nodes.RecoveryHold:
        raise
    except (ValueError, KeyError, TypeError, OSError) as exc:
        # The route refused to bind what its prepare steps produced: a typed hold naming the refusal.
        store.append("route-bind-refusal", {"route": (old.get("route") or {}).get("id"),
                                            "error": type(exc).__name__, "reason": str(exc)[:1500]})
        raise nodes.RecoveryHold("route_bind_refused", str(exc)[:1500]) from None
    from .routes.budgeting import BudgetInfeasible, narrow_plan
    try:
        plan = narrow_plan(plan, _plan_budget_envelope(state),
                           frozen_ids=[s['id'] for s in old['steps'] if is_prepare(s)])
    except BudgetInfeasible as exc:
        store.append('plan-budget-refusal', {'reason': exc.code, 'evidence': exc.evidence, 'remedy': exc.remedy})
        raise nodes.RecoveryHold(exc.code, str(exc)) from None
    if plan == old:
        return _status("bind", "the route kept the plan")
    pins = state.get("plan") or {}
    kept = {s["id"]: s for s in old["steps"] if is_prepare(s)}
    if any(s["id"] not in {p["id"] for p in plan["steps"]} for s in kept.values()):
        raise nodes.RecoveryHold("bind_dropped_prepare_steps", "a re-bound plan keeps the prepare steps that ran")
    installed = _install_plan(store, plan, source="bind", revision=pins.get("revision", 0) + 1)
    return {"plan": _materialise_plan(state, store, installed), **_status("bind", "the route re-bound the plan")}


def plan_wave(state):
    """Decide the next move of the execution loop from the plan, step states, authority and requests.

    Before the next wave, the answers the escalation gate verified are settled (``settle_answers``), the route steps
    whose request arrived run their bound children (``run_route_children``) and completed decisions close, or wait for
    their RDJ case or R3 answer (``close_decides``). A question or an R3 decision goes to the escalation point, one at
    a time; the other escalations of a wave go together.
    """
    store = _store(state)
    _governed(state, store)
    plan_pins = state.get("plan") or {}
    plan = current_plan(state, store)
    steps = _with_rungs(state, plan)
    wave = deepcopy(state.get("loop") or {})
    number = wave.get("number", 0)
    decides = set(plan_pins.get("decides") or [])
    decision, reason, ready, changed, holds, reviews = None, None, [], {}, {}, {}
    escalations, flags, budget, stopping, replanning = {}, {}, None, None, {}

    def adopt(rows, typed=None):
        steps.update(rows)
        changed.update(rows)
        holds.update(typed or {})
    held = engagement_hold(store) or _boundary_reached(store)
    if held:
        # An envelope floor failed on a completed session: orchestration is not running as designed, so no further
        # wave is sent; the run ends qualified with the breach in its receipt.
        decision, reason = "blocked", held
    elif plan_pins.get("approved_sha256") != plan_pins.get("sha256"):
        decision, reason = "deviation", "the plan changed after its approval"
    elif [k for k, v in (state.get("replans") or {}).items() if v.get("status") == "pending"]:
        pending = [v for v in (state.get("replans") or {}).values() if v.get("status") == "pending"]
        done, bound = replans_done(state, store), replan_bound(state)
        if all(v.get("kind") == "recovery" for v in pending):
            # A recovery request was admitted within the run's own recovery budget when it was made.
            decision, reason = "replan", "a step needs a governed recovery plan"
        else:
            decision, reason = ("replan", "a step requested a new experiment") if done < bound else \
                ("blocked", f"replan bound reached ({done} of {bound} replan(s) made)")
    else:
        rows, typed, escalations = settle_answers(state, store, plan, steps)
        adopt(rows, typed)
        current = {**state, "steps": steps, "escalations": {**(state.get("escalations") or {}), **escalations}}
        if not [k for k, v in current["escalations"].items() if v.get("status") == "pending"]:
            budget = deepcopy(state.get("budget") or {})
            budget.setdefault("used", {})
            rows, typed, notes = run_route_children(current, store, plan, steps, budget)
            adopt(rows, typed)
            if not rows:
                budget = None
            elif budget.get("exhausted") or service("authority").stop_state(store) != "running":
                # Nothing more is sent in this pass: the next guard ends the run.
                stopping = "the run stopped or exhausted its budget while a route child ran"
            current = {**current, "steps": steps, **({"budget": budget} if budget is not None else {})}
            rows, typed, asking, flags = close_decides(current, store, plan, steps)
            adopt(rows, typed)
            if notes:  # a child step's check-in flag reaches the parent's next check-in
                key = "checkin3" if plan_pins.get("go_sha256") or not plan_pins.get("waypoints") else "checkin2"
                flags.setdefault(key, []).extend(notes)
            escalations.update(asking)
            current = {**current, "steps": steps, "escalations": {**current["escalations"], **asking}}
        waypoints = list(plan_pins.get("waypoints") or [])
        go = not waypoints or plan_pins.get("go_sha256") == plan_pins.get("sha256")
        corrected = {}
        if stopping:
            decision, reason = "blocked", stopping
        elif [k for k, v in current["escalations"].items() if v.get("status") == "pending"]:
            assuming = assumption_requests(current, store, plan)
            if assuming:
                # Autonomous mode with the operator's ``assumption`` delegation: a question with no plan-declared
                # default first gets a governed judgment proposal (``replan`` purpose, ``assumption`` request), which
                # becomes its reasoned default; the escalation then asks for an answer as before.
                decision, reason = "replan", "a question without a declared default needs a reasoned assumption"
                replanning.update(assuming)
            else:
                decision, reason = "escalate", "a step escalated to the operator or physicist"
        elif waypoints and not go and all((steps.get(w) or {}).get("status") == STEP_DONE for w in waypoints):
            # CHECK-IN 2's seats review the executed waypoint before its authority is asked for a GO.
            decision, reason, reviews, corrected = checkin2_review(current, store, plan, steps)
        if corrected:
            # A correction round: the waypoint steps run again (new attempts, the findings pinned) before the seats
            # review their new outputs; the GO stays unasked.
            adopt(corrected)
            ready, admitted_held, admitted_holds = _admitted(current, store, plan,
                                                             ready_steps(plan_pins, steps, go=go), steps)
            adopt(admitted_held, admitted_holds)
            decision, reason = ("dispatch", reason) if ready else ("blocked", f"{reason}; no corrected step can run")
        elif decision is None:
            ready, admitted_held, admitted_holds = _admitted(current, store, plan,
                                                             ready_steps(plan_pins, steps, go=go), steps)
            adopt(admitted_held, admitted_holds)
            if ready:
                decision, reason = "dispatch", f"{len(ready)} ready step(s)"
            elif all(closed(s, steps, decides) for s in plan_pins.get("steps") or ()):
                unmet = ledger_errors(store, "execute->final_review", "execute")
                decision, reason = ("done", "every plan step completed") if not unmet else \
                    ("blocked", "obligations remain open before the final review: "
                     + "; ".join(e["message"] for e in unmet)[:400])
            else:
                waiting = {s: (steps.get(s) or {}).get("status") if (steps.get(s) or {}).get("status") != STEP_DONE
                           else "completed, not closed" for s in plan_pins.get("steps") or ()
                           if not closed(s, steps, decides)}
                decision, reason = "blocked", "no step can proceed: " + json.dumps(waiting, sort_keys=True)[:500]
    selected = _native_authority_ready(store, plan, ready)
    if selected != ready:
        reason = "one consequential native launch uses the current authority channel"
    ready = selected
    store.append("wave", {"number": number + 1, "phase": "execute", "decision": decision, "reason": reason,
                          "ready": ready, "plan_sha256": plan_pins.get("sha256")})
    update = {"loop": {**wave, "number": number + 1, "phase": "execute", "decision": decision, "reason": reason,
                       "items": _items(plan, steps, ready), "candidate": None},
              **_status("wave", reason)}
    if changed:
        update["steps"] = changed
    if holds:
        update["holds"] = holds
    if reviews:
        update["reviews"] = reviews
    if escalations:
        update["escalations"] = escalations
    if flags:
        update["flags"] = {k: list((state.get("flags") or {}).get(k) or []) + v for k, v in flags.items()}
    if budget is not None:
        update["budget"] = budget
    if replanning:
        update["replans"] = replanning
    return update


def _wave_branch(state):
    return (state.get("loop") or {}).get("decision") or "blocked"


def dispatch_wave(state):
    """Mark the wave's steps running; the map edge sends each to the step graph (which materialises its seat)."""
    items = (state.get("loop") or {}).get("items") or []
    running = {item["step"]["id"]: {**(state.get("steps") or {}).get(item["step"]["id"], {}), "status": "running",
                                    "attempts": item["attempt"]} for item in items}
    return {"steps": running, **_status("dispatch", f"{len(items)} step(s) dispatched")}


def _wave_items(state):
    return list((state.get("loop") or {}).get("items") or [])


def _item_key(item):
    return f"{item['step']['id']}@{item['attempt']}"


def route_packet_context(state, store, context):
    """What a route's ``packet_context(step, context)`` hook projects from: the adapter context, the step's own
    packet context and what the controller approved for it (``authority_subject``: the CHECK-IN 1 subject;
    ``approved_bounds``; ``site_budget``: the approved wall-time ceiling a site launch charges against)."""
    found = {**adapter_context(state, store), **deepcopy(context)}
    bounds = authority_bounds("checkin1", state, store)
    found.update(authority_subject=authority_subject("checkin1", state, store), approved_bounds=bounds)
    if "wall_seconds" in (bounds.get("budget") or {}):
        found["site_budget"] = bounds["budget"]["wall_seconds"]
    return found


def _json_only(value):
    """``value`` as JSON data (a path becomes its text); anything else non-JSON is refused."""
    def encode(item):
        if isinstance(item, Path):
            return str(item)
        raise TypeError(f"route context holds a {type(item).__name__}, not JSON data")
    try:
        return json.loads(json.dumps(value, default=encode, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise nodes.RecoveryHold("route_context_invalid", f"a route's packet context must be JSON data: {exc}"[:1500])


def _packet(state, item):
    """The step graph's packet for one item: the approved step and its context (a correction round's pinned findings
    in ``correction``: the producer's input for its new attempt; the options its ``ask`` parents' answers selected in
    ``answers``). After CHECK-IN 1 a route adapter's optional hooks join in: ``packet_context(step, context)`` adds
    JSON context (never replacing or removing the controller's own fields), and with ``dispatch(step, context,
    invoke)`` the packet names it (``route_dispatch``), so the step's invocation is offered to it
    (``route_dispatch``)."""
    store = _store(state)
    step = item["step"]
    points = list(step.get("points") or [])
    loop = state.get("loop") or {}
    steps = state.get("steps") or {}
    answers = {p: {"option": steps[p]["answer"]["option"], "authority": steps[p]["answer"]["authority"]}
               for p in step.get("depends_on") or () if type((steps.get(p) or {}).get("answer")) is dict}
    context = _context(state, store, step, attempt=item["attempt"], wave=loop.get("number"), phase=loop.get("phase"),
                       seat_kind="launch" if step["kind"] in LAUNCH_KINDS else "worker",
                       **({"point": points[0]} if len(points) == 1 else {}),
                       **({"correction": deepcopy(item["correction"])} if item.get("correction") else {}),
                       **({"answers": answers} if answers else {}))
    module = adapter(state, store) if loop.get("phase") != "prepare" else None
    if module is not None and hasattr(module, "packet_context"):
        extra = _json_only(module.packet_context(deepcopy(step), route_packet_context(state, store, context)) or {})
        context.update({k: v for k, v in extra.items() if k not in context})
    if module is not None and hasattr(module, "dispatch"):
        context["route_dispatch"] = module.__name__
    return {"step": deepcopy(step), "context": context}


def route_dispatch(packet, invoked):
    """One step invocation offered to its route adapter's ``dispatch(step, context, invoke)`` hook when the packet
    names it (``route_dispatch``). ``invoked()`` is the substrate's own child invocation of this item
    (``_invoke_child`` with the item's child metadata: its receipts and the call-site census see the step) and
    returns its envelope ``{outcome, results, status}``; the hook's ``invoke`` is a zero-argument closure over it that
    returns the step outcome, at most once. The hook gets the packet context with the run's store. A refusal before
    ``invoke`` holds the step with no shared-step effect (``route_dispatch_refused``); a failure after it holds the
    step's outcome (``route_dispatch_failed``). The envelope the join reads is the invocation's own when the hook
    returns its outcome."""
    context = packet.get("context") or {}
    name = context.get("route_dispatch")
    if not name:
        return invoked()
    from langgraph.errors import GraphBubbleUp
    if type(name) is not str or not name.startswith(__package__ + ".routes."):
        raise nodes.RecoveryHold("route_dispatch_invalid", f"{name!r} is not a route adapter")
    hook = getattr(import_module(name), "dispatch")
    calls = []

    def invoke():
        if calls:
            raise GraphError("a route's dispatch hook invokes its step once")
        calls.append(invoked())
        found = calls[0].get("results") or {}
        return deepcopy(found.get("step") or {"status": "failed" if calls[0].get("outcome") == "failed" else "held",
                                              "reason": (calls[0].get("status") or {}).get("reason")})
    store = RunStore(context["run_id"], root=context["store_root"])
    try:
        outcome = hook(deepcopy(packet["step"]), {**deepcopy(context), "store": store}, invoke)
    except GraphBubbleUp:
        raise
    except Exception as exc:  # the route's refusal or failure is a typed hold, never a skipped check
        code = "route_dispatch_failed" if calls else "route_dispatch_refused"
        from .batch_jobs import BatchJobsHold
        if isinstance(exc, BatchJobsHold):
            code = exc.code  # the scheduler observer's typed decision (recovery classifies it)
        text = f"{type(exc).__name__}: {exc}"[:1000]
        held = {"step_id": packet["step"]["id"], "attempt": context.get("attempt"), "status": "held", "outputs": [],
                "receipts": [], "escalation": None, "replan": None, "budget": {}, "judgments": [], "review": {}}
        if calls:  # the step ran: its outcome is kept, and held
            held = deepcopy((calls[0].get("results") or {}).get("step") or held)
        held.update(status="held", reason=f"{code}: {text}", hold={"reason": code, "would_make_possible": text})
        return {"outcome": "held", "results": {"step": held}, "status": {"reason": held["reason"]}}
    if calls and outcome == (calls[0].get("results") or {}).get("step"):
        return calls[0]
    outcome = outcome if type(outcome) is dict else {"status": "failed", "reason": "the route's dispatch returned no outcome"}
    status = outcome.get("status")
    return {"outcome": "ok" if status == STEP_DONE else ("failed" if status == "failed" else "held"),
            "results": {"step": deepcopy(outcome)}, "status": {"reason": outcome.get("reason")}}


def route_dispatching(body):
    """The execution map's per-item invocation, offered to the route's dispatch hook (``route_dispatch``)."""
    def invoke_item(state):
        item = state["map_item"]
        found = route_dispatch(state["map_packet"], lambda: body(state)["results"][item])
        return {"results": {item: found}}
    invoke_item.__name__ = body.__name__
    return invoke_item


def _attempt_limit(step):
    return int(step.get("attempt_limit") or 1)


def fold_outcome(state, store, module, step, attempt, found, budget):
    """``(row, outcome, hold)``: one attempt's outcome folded into its step row, its usage charged to ``budget``.

    A review is read by its verdict, not its credit alone: a credited ``revise`` or ``unresolved`` review of the
    attempt is a performed review, never acceptance. Within the run's correction rounds (``correction_rounds``) the
    step is corrected (``correct``: the producer runs again as a new attempt with the review's findings pinned, then
    is reviewed again); past the bound, or without findings, it is held (``hold``). A ``revise`` status without a
    credited review accepts nothing either."""
    outcome = (found.get("results") or {}).get("step")
    if type(outcome) is not dict:
        outcome = {"status": "failed" if found.get("outcome") == "failed" else "held",
                   "reason": (found.get("status") or {}).get("reason") or "the step graph returned no outcome"}
    status, reason, hold, correction = outcome.get("status"), outcome.get("reason"), None, None
    corrections = int(((state.get("steps") or {}).get(step["id"]) or {}).get("corrections") or 0)
    review = outcome.get("review") or {}
    if review.get("credited") is True and review.get("verdict") in REVIEW_VERDICTS and status in (
            STEP_DONE, "revise", "held"):
        subject = outcome.get("subject_sha256") or _digest(outcome.get("outputs") or [])
        correction, problem = review_correction(
            store, purpose="step", attempt=attempt, subject_sha256=subject, done=corrections,
            bound=correction_rounds(state),
            verdicts={"review": {**review, "step": outcome.get("step_id") or step["id"]}})
        if correction is not None:
            status, reason, corrections = CORRECT, f"review {correction['verdict']}: correction round " \
                f"{correction['round']} of {correction['rounds']}", corrections + 1
        else:
            status, reason = "held", f"{problem[0]}: {problem[1]}"
            hold = {"reason": problem[0], "would_make_possible": (
                "a corrected attempt the review accepts" if problem[0] == "review_rounds_exhausted"
                else "the review's findings, pinned for a correction round")}
    elif status == "revise":
        status, reason = "held", "review_uncredited: a revise outcome without a credited review"
        hold = {"reason": "review_uncredited", "would_make_possible": "a credited review of the attempt"}
    elif status == "held" and type(outcome.get("hold")) is dict:  # the controller's own typed hold (route dispatch)
        hold = {"reason": str(outcome["hold"].get("reason")),
                "would_make_possible": str(outcome["hold"].get("would_make_possible") or "")[:500]}
    if status not in ("completed", "failed", "held", "escalated", "budget_exhausted", "stopped", CORRECT):
        status = "failed"
    if status == STEP_DONE and module is not None and hasattr(module, "step"):
        problems = module.step(step, deepcopy(outcome), adapter_context(state, store)) or []
        if problems:
            status, reason = "failed", "route check: " + "; ".join(map(str, problems))[:1000]
    if status == "failed" and attempt < _attempt_limit(step):
        status = "retry"
    used = budget.setdefault("used", {})
    for dimension, value in (outcome.get("budget") or {}).items():
        if type(value) in (int, float):
            used[dimension] = used.get(dimension, 0) + value
    if status == "budget_exhausted":
        budget["exhausted"] = True
    row = {"status": status, "attempts": attempt, "rung": step.get("rung"),
           "outputs": deepcopy(outcome.get("outputs") or []), "receipts": list(outcome.get("receipts") or []),
           "reason": reason, "corrections": corrections}
    if correction is not None:
        row["correction"] = correction
    return row, outcome, hold


PARENT_KINDS = ("ask", "route")  # step kinds the governed step passes up: no worker runs them


def parent_request(state, step, attempt, row, escalation):
    """``(row, escalation, hold)`` for a parent request (``ask``, ``route``) of ``step``: the governed step ran no
    worker and passed it up. An ``ask`` becomes a pending question with the approved plan step's own options and P7
    default (never the worker's); a ``route`` waits for its bound child (``ROUTE``). A request of another kind than its
    step, a question without options or a route without its bound child holds, typed."""
    def held(code, text):
        return {**row, "status": "held", "reason": f"{code}: {text}"}, None, {"reason": code, "would_make_possible": text}
    if step["kind"] != escalation:
        return held("parent_request_mismatch", f"a {step['kind']} step passed up {escalation}")
    if escalation == "route":
        if step["id"] not in ((state.get("plan") or {}).get("route_children") or {}):
            return held("route_child_missing", "no child plan was bound for the route step before CHECK-IN 1")
        return {**row, "status": ROUTE, "reason": "route: its bound child runs next"}, None, None
    judgment = (step.get("parameters") or {}).get("judgment") or {}
    options = _choices(judgment.get("options"))
    if not options or type(step.get("question")) is not str:
        return held("ask_options_missing", "a question the plan states with the options an answer may take")
    default = judgment.get("default_option") if judgment.get("default") else None  # only a P7 default is one
    question = {"status": "pending", "escalation": "ask", "attempt": attempt, "reason": step["question"],
                "question": step["question"], "options": options,
                "default": default if default in {o["id"] for o in options} else None}
    return {**row, "status": "escalated", "reason": "ask: waiting for its answer"}, question, None


def join(state):
    """Fold each step outcome of the wave into the step states, budgets, escalations and requests.

    After CHECK-IN 1 the join is where engagement acts: each outcome's trigger events go to the engagement monitor,
    the envelope's floors are checked with the independent broker count (a breach on a completed session raises
    engagement and holds the next wave: ``engagement_hold``), and the applied view of a raised engagement is pinned
    before any later step is dispatched."""
    store = _store(state)
    results = state.get("results") or {}
    steps, escalations, replans, flags, judgments, holds, outcomes = {}, {}, {}, {}, {}, {}, {}
    budget = deepcopy(state.get("budget") or {})
    budget.setdefault("used", {})
    module = adapter(state, store)
    items = list((state.get("loop") or {}).get("items") or [])
    for item in items:
        step, attempt = item["step"], item["attempt"]
        steps[step["id"]], outcome, hold = fold_outcome(state, store, module, step, attempt,
                                                        results.get(_item_key(item)) or {}, budget)
        outcomes[step["id"]] = outcome
        if hold is not None:
            holds[step["id"]] = hold
        escalation = outcome.get("escalation")
        if escalation == "checkin_flag":
            flags.setdefault("checkin3" if (state.get("plan") or {}).get("go_sha256") else "checkin2", []).append(
                {"step": step["id"], "note": outcome.get("reason")})
        elif escalation in ("stop", "decision_block"):
            escalations[step["id"]] = {"status": "pending", "escalation": escalation, "attempt": attempt,
                                       "reason": outcome.get("reason")}
        elif escalation in PARENT_KINDS:
            steps[step["id"]], question, hold = parent_request(state, step, attempt, steps[step["id"]], escalation)
            if question is not None:
                escalations[step["id"]] = question
            if hold is not None:
                holds[step["id"]] = hold
        elif escalation != "new_experiment_required" and (steps[step["id"]]["status"] == "escalated" or (
                escalation is not None and steps[step["id"]]["status"] == "held")):
            # An escalation nothing here acts on is a typed hold, never success and never a stranded step.
            steps[step["id"]] = {**steps[step["id"]], "status": "held", "reason": f"escalation_unhandled: {escalation}"}
            holds[step["id"]] = {"reason": "escalation_unhandled", "would_make_possible": f"a handler for {escalation}"}
        if escalation == "new_experiment_required" or outcome.get("replan"):
            replans[step["id"]] = {"status": "pending", "request": deepcopy(outcome.get("replan")),
                                   "reason": outcome.get("reason")}
        if outcome.get("judgments") or step["kind"] == "decide":
            # A decide step's latest attempt names its judgment record (none: it never closes on an earlier one).
            judgments[step["id"]] = list(outcome.get("judgments") or [])
    for step_id, request in _recovery_requests(state, store, items, steps, outcomes).items():
        replans.setdefault(step_id, request)
    record_id = store.append("wave-result", {"number": (state.get("loop") or {}).get("number"),
                                             "phase": (state.get("loop") or {}).get("phase"), "steps": deepcopy(steps),
                                             "escalations": sorted(escalations), "replans": sorted(replans)})
    update = {"steps": steps, "budget": budget, **_status("join", f"{len(steps)} step outcome(s) adopted")}
    for key, value in (("escalations", escalations), ("replans", replans), ("flags", flags), ("judgments", judgments),
                       ("holds", holds)):
        if value:
            update[key] = value if key != "flags" else {k: list((state.get("flags") or {}).get(k) or []) + v
                                                        for k, v in value.items()}
    raised = observe_engagement(store, outcome_events(state, store, items, steps, outcomes, record_id)
                                + cost_events(store, items))
    _, floor = envelope_wave(state, store)
    if raised or floor:
        pins = repin_engagement(state, store)
        if pins != (state.get("plan") or {}):
            update["plan"] = pins
    return update


def _autonomy(function):
    """The authority service's autonomy boundary ``function`` (None for a stand-in authority)."""
    return service_function("authority", "autonomy", function)


def _boundary_reached(store):
    """An end boundary reached since the guard ran (a wait resumed past its bound): its reason, else None."""
    guard = _autonomy("guard")
    if not callable(guard):
        return None
    verdict, finding = guard(store)
    return f"{finding['reason']} [{finding['code']}]" if verdict == "exhausted" else None


def _recovery_inputs(store):
    """What a recovery plan may draw on: the run inputs staged at intake and the admitted operations."""
    intake = store.latest("intake")
    staged = [{k: row.get(k) for k in ("name", "artifact", "sha256")}
              for row in ((intake or {}).get("record") or {}).get("supplied") or () if type(row) is dict]
    try:
        from .step import operations
        tools = sorted(operations.signatures())
    except Exception:  # the catalogue is context, never a gate
        tools = []
    return staged, tools


def _recovery_requests(state, store, items, steps, outcomes):
    """``{step id: pending recovery request}`` for each step of the wave that ended failed or held for a recoverable
    reason, within the run's recovery budget (``recovery.request``)."""
    from . import recovery
    found, inputs = {}, None
    for item in items:
        step = item["step"]
        row = steps.get(step["id"]) or {}
        if row.get("status") not in ("failed", "held") or not recovery.classify(row)["recoverable"]:
            continue
        if inputs is None:
            inputs = _recovery_inputs(store)
        request = recovery.request(store, state.get("mode") or {}, step, row, outcomes.get(step["id"]),
                                   run_inputs=inputs[0], tools=inputs[1])
        if request is not None:
            found[step["id"]] = request
    return found


def _guard_policy(state):
    """A stop drains to the bounded ending. The autonomy boundaries come next (N1, N2, N6, N7): an end boundary
    (grant expired or revoked, deadline margin, a wait past its bound) ends the run qualified with the boundary
    named; a wait for a human (a pause, a changed instruction document, an unauthenticated grant, exhausted disk,
    repeated launch failures, a reported credential or batch-job condition) is recorded and notified once, and the
    run drains at this superstep boundary with its next node kept, so the driver resumes it once the wait clears."""
    store = _store(state)
    stop = service("authority").stop_state(store)
    if stop in ("stop_requested", "draining", "stopped"):
        return "drain"
    guard = _autonomy("guard")
    if callable(guard):
        verdict, finding = guard(store)
        if verdict == "exhausted":
            return "exhausted"
        if verdict == "wait":
            control = nodes.RUN_CONTROL.get()
            if control is None:
                return "drain"
            control.request_drain("waiting_for_human:" + finding["code"])
            return "go"
    if stop == "pause_requested":
        return "drain"
    if (state.get("loop") or {}).get("number", 0) >= MAX_WAVES or (state.get("budget") or {}).get("exhausted"):
        return "exhausted"
    return "go"


def replan(state):
    """A step asked for a new experiment: the judgment graph replans; the deviation gate renews authority."""
    store = _store(state)
    pins = state.get("plan") or {}
    old = scientific_plan(state, store)  # a replan changes the scientific plan; a new decision applies to its result
    requests = {k: v for k, v in (state.get("replans") or {}).items() if v.get("status") == "pending"}
    assuming = {k: v for k, v in requests.items() if v.get("kind") == ASSUMPTION_KIND}
    if assuming:
        return _assume(state, store, pins, old, assuming)
    view = {"request": deepcopy(state.get("request") or {}), "plan": old,
            "context": _context(state, store, purpose="replan", revision=pins.get("revision", 0) + 1,
                                replan_requests=deepcopy(requests), steps=deepcopy(state.get("steps") or {}))}
    recovering = {k: v for k, v in requests.items() if v.get("kind") == "recovery"}
    label = f"recovery-{pins.get('recoveries', 0) + 1}" if recovering and len(recovering) == len(requests) else \
        f"replan-{pins.get('replans', 0) + 1}"
    found = _invoke(state, JUDGMENT_GRAPH, view, {"judgment": label})
    plan = (found.get("results") or {}).get("plan")
    if found.get("outcome") != "ok" or type(plan) is not dict:
        if recovering:
            return _recovery_unplanned(store, recovering, ["the judgment graph did not return a recovery plan"])
        raise nodes.RecoveryHold("replan_failed", "the judgment graph did not return a plan")
    direction = None
    if recovering:
        direction, problems = _recovery_choice(store, recovering)
        if problems is not None and len(recovering) == len(requests):
            return _recovery_unplanned(store, recovering, problems)
    installed = _install_plan(store, plan, source="replan", revision=pins.get("revision", 0) + 1)
    service("ledger").materialise(store, "event", {"kind": "deviation", "id": deviation_event(installed)})
    before = {s["id"]: _digest(s) for s in old["steps"]}
    after = {s["id"]: _digest(s) for s in plan["steps"]}
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    scope_changed = {d["id"] for d in old["deliverables"]} != {d["id"] for d in plan["deliverables"]}
    mapped = {d["id"] for d in plan["deliverables"] if d.get("status") == "mapped"}
    # A deliverable mapped before and no longer mapped is a scope change too (a descope), whoever proposed it.
    scope_changed = scope_changed or any(d.get("status") == "mapped" and d["id"] not in mapped
                                         for d in old["deliverables"])
    counts = {"replans": pins.get("replans", 0) + (0 if len(recovering) == len(requests) else 1),
              "recoveries": pins.get("recoveries", 0) + (1 if recovering else 0)}
    if recovering:
        scope_changed = scope_changed or direction == "scope"
        for name in recovering:
            store.append("recovery", {"schema_version": 1, "phase": "adopted", "step": name,
                                      "plan_sha256": installed["sha256"], "direction": direction})
    return {"plan": {**installed, "approved_sha256": pins.get("approved_sha256"), "go_sha256": pins.get("go_sha256"),
                     **counts, "scope_changed": scope_changed, "changed_steps": changed,
                     "recovery_direction": direction},
            "replans": {k: {**v, "status": "replanned"} for k, v in requests.items()},
            **_status("replan", "the plan was revised; the deviation gate renews authority")}


# ---- reasoned assumptions: unanswered questions and physics-critical ambiguity --------------------------------------

# The store kind of every machine assumption event (``proposed``, ``refused``, ``taken``, ``alternative``,
# ``alternative_skipped``). Its ``assumptions`` lists reach the delivery's assumption list and the K8 auditor
# (``delivery_assumption_subject``).
ASSUMPTION_KIND = "assumption"


def _authority_mode(store):
    """The run's frozen operating-mode record from the authority service, or ``{}``."""
    frozen = getattr(service("authority"), "frozen", None)
    if not callable(frozen):
        return {}
    try:
        return frozen(store, required=False) or {}
    except Exception:  # an authority that cannot read the mode delegates nothing
        return {}


def assumption_delegated(store):
    """Whether the operator configured machine assumptions: autonomous mode with ``assumption`` among the machine
    check-ins (``ravel operator init|set --machine-checkins ...,assumption``)."""
    mode = _authority_mode(store)
    return mode.get("mode") == "autonomous" and "assumption" in (mode.get("machine_checkins") or ())


def step_physics_critical(step):
    """Whether the controller computes ``step`` as physics-critical: it resolves a physics-critical frame unknown
    (``judgment.planning`` gives such a step the effect ``physics_critical``) or its consequence class is R3. A
    worker's proposal can raise this, never lower it."""
    if type(step) is not dict:
        return False
    from .engagement.facts import action_of
    action = action_of(step)
    return "physics_critical" in (action.get("effects") or ()) or step.get("consequence_class") == "R3" or \
        ((step.get("parameters") or {}).get("judgment") or {}).get("declared_class") == "R3"


def assumption_requests(state, store, plan):
    """``{step id: pending assumption request}`` for each pending question of an ``ask`` step that has no
    plan-declared default and no proposal yet for its attempt, when the operator delegated machine assumptions.
    Interactive runs and undelegated autonomous runs get none: their questions wait for a human as before."""
    pending = {k: v for k, v in (state.get("escalations") or {}).items()
               if v.get("status") == "pending" and v.get("escalation") == "ask"
               and v.get("default") is None and not v.get("assumption")}
    if not pending or not assumption_delegated(store):
        return {}
    tried = {(r["record"].get("step"), r["record"].get("attempt")) for r in store.scan(ASSUMPTION_KIND)}
    staged, tools = _recovery_inputs(store)
    found = {}
    for sid, row in sorted(pending.items()):
        if (sid, row.get("attempt")) in tried:
            continue
        step = next((s for s in plan["steps"] if s["id"] == sid), None)
        found[sid] = {"status": "pending", "kind": ASSUMPTION_KIND,
                      "reason": f"question of step {sid} has no plan-declared default and needs a reasoned assumption",
                      "request": {"why": f"step {sid} asks a question no plan default answers",
                                  "assumption": {"question_step": sid, "question": row.get("question"),
                                                 "options": deepcopy(row.get("options") or []),
                                                 "attempt": row.get("attempt"),
                                                 "physics_critical": step_physics_critical(step),
                                                 "run_inputs": staged, "tools": tools,
                                                 "steps": deepcopy(state.get("steps") or {})}}}
    return found


def _judgment_block(store, name):
    """Block ``name`` of the planner's latest replan document (the judgment route's own plan record)."""
    from .judgment import control as judgment_control
    rows = [row["record"] for row in store.scan(judgment_control.PLAN_KIND)
            if row["record"].get("source") == "replan"]
    return (rows[-1].get("plan") or {}).get(name) if rows else None


def assumption_errors(block, step_id, row):
    """Why a planner's ``assumption`` block cannot be taken for the question of ``step_id`` (empty when it can):
    it names the question, a chosen option among those offered, every alternative it considered with evidence, and
    a rejection reason for each one not chosen."""
    if type(block) is not dict:
        return ["the judgment step returned no assumption block"]
    errors = []
    offered = {o.get("id") for o in row.get("options") or () if type(o) is dict}
    if block.get("question_step") != step_id:
        errors.append("the assumption block answers another question")
    if block.get("chosen") not in offered:
        errors.append("the chosen option is not one of the question's options")
    rows = block.get("alternatives")
    if type(rows) is not list or not rows:
        return errors + ["the assumption block lists no alternatives considered"]
    seen = set()
    for item in rows:
        if type(item) is not dict or item.get("option") not in offered or item.get("option") in seen:
            errors.append("each alternative names a distinct offered option")
            continue
        seen.add(item["option"])
        if type(item.get("evidence")) is not list or not item["evidence"] or \
                any(type(e) is not str or not e.strip() for e in item["evidence"]):
            errors.append(f"alternative {item['option']} cites no evidence")
        if type(item.get("reasons")) is not str or not item["reasons"].strip():
            errors.append(f"alternative {item['option']} states no reasons")
        if item["option"] != block.get("chosen") and not (type(item.get("rejection")) is str and item["rejection"].strip()):
            errors.append(f"alternative {item['option']} was not chosen and states no rejection reason")
    if block.get("chosen") not in seen:
        errors.append("the chosen option is not among the alternatives considered")
    if type(block.get("physics_critical")) is not bool:
        errors.append("the assumption block states whether the ambiguity is physics-critical")
    return errors


def _assumption_statement(row, option, critical, block):
    text = next((o.get("text") for o in row.get("options") or () if type(o) is dict and o.get("id") == option), "")
    others = ", ".join(f"{a['option']} ({a.get('rejection')})" for a in block["alternatives"] if a["option"] != option)
    return (("CONDITIONAL RESULT: " if critical else "") + f"MACHINE ASSUMPTION for the question "
            f"\"{str(row.get('question') or '')[:300]}\": option {option} ({str(text)[:200]}), chosen by the governed "
            f"judgment step because {str(next(a['reasons'] for a in block['alternatives'] if a['option'] == option))[:400]}; "
            f"alternatives considered: {others or 'none'}." + (" The result is conditional on this assumption; it is "
            "not a fact the run established." if critical else ""))


def _assume(state, store, pins, old, assuming):
    """The governed judgment step proposes the most defensible answer to each unanswered question (the replan
    purpose with an ``assumption`` request), with the alternatives it considered and its reasons. A valid proposal
    becomes the question's reasoned default (``escalation_question``) and is recorded as a machine assumption; the
    escalation then asks for an answer as before, and the authority takes the assumption only under the operator's
    delegation, once nobody answered within the wait bound. A physics-critical ambiguity is never taken as fact:
    the result is conditional on it, and, while the replan budget allows, the planner's sibling branch for the main
    alternative interpretation is installed as a plan deviation so the delivery reports both."""
    view = {"request": deepcopy(state.get("request") or {}), "plan": old,
            "context": _context(state, store, purpose="replan", revision=pins.get("revision", 0) + 1,
                                replan_requests=deepcopy(assuming), steps=deepcopy(state.get("steps") or {}))}
    number = len({(r["record"].get("step"), r["record"].get("attempt")) for r in store.scan(ASSUMPTION_KIND)}) + 1
    found = _invoke(state, JUDGMENT_GRAPH, view, {"judgment": f"assumption-{number}"})
    plan = (found.get("results") or {}).get("plan")
    block = _judgment_block(store, ASSUMPTION_KIND) if found.get("outcome") == "ok" and type(plan) is dict else None
    escalations, replans, branch = {}, {}, None
    for sid, request in sorted(assuming.items()):
        row = (state.get("escalations") or {}).get(sid) or {}
        attempt = row.get("attempt")
        problems = assumption_errors(block, sid, row)
        if problems:
            # Nothing is assumed: the question waits for a human exactly as without the delegation.
            store.append(ASSUMPTION_KIND, {"schema_version": 1, "phase": "refused", "step": sid, "attempt": attempt,
                                           "problems": problems[:10]})
            replans[sid] = {**request, "status": "unassumed", "problems": problems[:10]}
            continue
        option = block["chosen"]
        critical = bool(block["physics_critical"]) or bool(request["request"]["assumption"]["physics_critical"])
        statement = _assumption_statement(row, option, critical, block)
        record_id = store.append(ASSUMPTION_KIND, {
            "schema_version": 1, "phase": "proposed", "step": sid, "attempt": attempt, "option": option,
            "conditional": critical, "physics_critical": {"proposed": bool(block["physics_critical"]),
                                                          "computed": bool(request["request"]["assumption"]["physics_critical"])},
            "question": row.get("question"), "alternatives": deepcopy(block["alternatives"]),
            "rationale": block.get("rationale"),
            "assumptions": [{"statement": statement, "kind": "machine_assumption", "step": sid, "option": option,
                             "conditional": critical, "physics_critical": critical}]})
        escalations[sid] = {**row, "default": option,
                            "assumption": {"record": record_id, "option": option, "conditional": critical,
                                           "alternatives": len(block["alternatives"])}}
        replans[sid] = {**request, "status": "assumed"}
        if critical:
            branch = _alternative_branch(state, store, pins, old, plan, block, sid, record_id) or branch
    update = {"escalations": escalations, "replans": replans,
              **_status("replan", f"{len(escalations)} reasoned assumption(s) proposed")}
    if branch is not None:
        update["plan"] = branch
    return update


def _alternative_branch(state, store, pins, old, plan, block, sid, record_id):
    """Install the planner's plan with the sibling branch of the main alternative interpretation, when it adds one
    and the replan budget allows; the plan change is a deviation the deviation gate renews. The budget rule and the
    choice are recorded either way."""
    alternative = block.get("alternative_branch")
    before = {s["id"] for s in old["steps"]}
    added = sorted(s["id"] for s in plan["steps"] if s["id"] not in before)
    done, bound = replans_done(state, store), replan_bound(state)
    base = {"schema_version": 1, "step": sid, "record": record_id, "alternative_option": alternative,
            "added_steps": added, "replans_done": done, "replan_bound": bound,
            "budget_rule": "a sibling branch runs only while the run's replan bound has room (one replan per branch)"}
    unchanged = all(next((x for x in plan["steps"] if x["id"] == s["id"]), None) == s for s in old["steps"])
    if not alternative or not added or not unchanged or \
            {d["id"] for d in old["deliverables"]} != {d["id"] for d in plan["deliverables"]}:
        store.append(ASSUMPTION_KIND, {**base, "phase": "alternative_skipped",
                                       "reason": "the judgment step proposed no sibling branch that only adds steps"})
        return None
    if done >= bound:
        store.append(ASSUMPTION_KIND, {**base, "phase": "alternative_skipped",
                                       "reason": f"replan bound reached ({done} of {bound})"})
        return None
    installed = _install_plan(store, plan, source="replan", revision=pins.get("revision", 0) + 1)
    service("ledger").materialise(store, "event", {"kind": "deviation", "id": deviation_event(installed)})
    statement = (f"ALTERNATIVE BRANCH: the run also derives its results under option {alternative} of the question of "
                 f"step {sid} (steps {', '.join(added)}), because the chosen assumption is physics-critical.")
    store.append(ASSUMPTION_KIND, {**base, "phase": "alternative", "plan_sha256": installed["sha256"],
                                   "assumptions": [{"statement": statement, "kind": "alternative_branch",
                                                    "step": sid, "option": alternative, "conditional": True,
                                                    "steps": added}]})
    return {**installed, "approved_sha256": pins.get("approved_sha256"), "go_sha256": pins.get("go_sha256"),
            "replans": pins.get("replans", 0) + 1, "recoveries": pins.get("recoveries", 0), "scope_changed": False,
            "changed_steps": added, "recovery_direction": "plan"}


def record_conditional_approval(state, store):
    """A CHECK-IN 1 approval the operator's machine authority gave CONDITIONAL on facts the intake inferred as
    physics-critical (``authority`` evidence ``conditional_on``): each fact is recorded as a conditional assumption,
    so the delivery lists it, the K8 auditor reviews it and every result is labelled conditional on it."""
    ids = list((state.get("authority") or {}).get("approve_plan") or ())
    if not ids:
        return None
    try:
        record = _authority_record(store, ids[-1])
    except Exception as exc:  # the gate passed on this record: unread, its conditions would silently drop
        raise nodes.RecoveryHold("authority_refused", f"the CHECK-IN 1 approval {ids[-1]} cannot be read, so the "
                                 f"facts it is conditional on cannot be recorded: {type(exc).__name__}: {exc}"[:1500]
                                 ) from None
    facts = ((record or {}).get("evidence") or {}).get("conditional_on") or []
    if not facts or any(r["record"].get("phase") == "conditional_approval" and r["record"].get("record") == ids[-1]
                        for r in store.scan(ASSUMPTION_KIND)):
        return None
    statements = [{"statement": f"CONDITIONAL RESULT: the request does not state the {f.get('type') or 'fact'} "
                                f"{f.get('id')}; the run proceeds with the value the intake inferred "
                                f"({json.dumps(f.get('value'), sort_keys=True)[:200]}), which is not established fact.",
                   "kind": "inferred_critical_fact", "fact": deepcopy(f), "conditional": True} for f in facts]
    return store.append(ASSUMPTION_KIND, {"schema_version": 1, "phase": "conditional_approval", "step": None,
                                          "record": ids[-1], "conditional": True, "facts": deepcopy(facts),
                                          "assumptions": statements})


def _recovery_proposal(store):
    """The recovery block of the planner's latest replan document (the judgment route's own plan record)."""
    from .judgment import control as judgment_control
    rows = [row["record"] for row in store.scan(judgment_control.PLAN_KIND)
            if row["record"].get("source") == "replan"]
    return (rows[-1].get("plan") or {}).get("recovery") if rows else None


def _latest_request_ns(store, name):
    rows = [r["time_ns"] for r in store.scan("recovery") if r["record"].get("step") == name
            and r["record"].get("phase") == "requested"]
    return max(rows) if rows else 0


def _recovery_choice(store, recovering):
    """``(deviation direction, None)`` for a valid proposal with a chosen alternative, else ``(None, problems)``.
    Every alternative the planner considered, with its evidence and rejection reason, is kept in the store."""
    from . import recovery
    proposal = _recovery_proposal(store)
    direction, failures = None, []
    for name in recovering:
        problems = recovery.proposal_errors(proposal, name)
        recovery.record_proposal(store, name, proposal, problems)
        picked = None if problems else recovery.chosen(proposal)
        if problems:
            failures += problems
        elif picked is None:
            failures.append(f"no alternative recovers step {name}")
        else:
            found = recovery.direction(picked)
            direction = "scope" if "scope" in (direction, found) else (found if direction in (None, found) else "plan")
    return (direction, None) if not failures else (None, failures)


def _recovery_unplanned(store, recovering, problems):
    """No recovery plan is taken: the failed steps stay as they are and the rest of the run continues."""
    for name in recovering:
        if not [r for r in store.scan("recovery") if r["record"].get("step") == name
                and r["record"].get("phase") in ("proposed", "none", "refused")
                and r["time_ns"] >= _latest_request_ns(store, name)]:
            store.append("recovery", {"schema_version": 1, "phase": "refused", "step": name, "alternatives": [],
                                      "chosen": None, "problems": list(problems)[:10]})
    return {"replans": {k: {**v, "status": "unrecovered", "problems": list(problems)[:10]}
                        for k, v in recovering.items()},
            **_status("replan", "no recovery plan was taken; the rest of the run continues")}


def rematerialise(state):
    store = _store(state)
    pins = _materialise_plan(state, store, state["plan"])
    return {"plan": pins, **_status("materialise", "replanned steps materialised")}


# ---- final review, delivery and the bounded ending -------------------------------------------------

def result_producers(plan):
    """The steps whose outputs are the plan's results: those its mapped deliverables name, else its last steps."""
    known = [s["id"] for s in plan["steps"]]
    mapped = {d.get("step") for d in plan.get("deliverables") or () if type(d) is dict and d.get("status") == "mapped"}
    parents = {p for s in plan["steps"] for p in s.get("depends_on") or ()}
    return [sid for sid in known if sid in mapped] or [sid for sid in known if sid not in parents]


def _in_order(plan, chosen):
    """The step ids of ``chosen`` in plan order, each after its parents among them."""
    by_id = {s["id"]: s for s in plan["steps"]}
    remaining, order = [sid for sid in by_id if sid in chosen], []
    while remaining:
        ready = [sid for sid in remaining
                 if all(p not in chosen or p in order for p in by_id[sid].get("depends_on") or ())]
        if not ready:
            raise nodes.RecoveryHold("plan_cycle", "the corrected steps do not form a dependency order")
        order.extend(ready)
        remaining = [sid for sid in remaining if sid not in ready]
    return order


def correct_results(state, store, plan, correction, budget):
    """A correction round of the final review, run in this node (the final review has no edge back to the waves): the
    steps producing the plan's results run again through the step graph as new attempts with the round's findings
    pinned, then every step that completed on their outputs, in dependency order; each is admitted by the route
    first and its usage is charged to ``budget``. ``(rows, holds, why)``: the new step rows and holds, and why the round
    could not finish (None when every step completed and the plan's steps are closed again). A stop, an exhausted
    budget, a refused admission, an escalation or a new-experiment request ends the round; it never asks a check-in."""
    steps = deepcopy(state.get("steps") or {})
    marked = correction_steps(plan, steps, result_producers(plan), correction)
    by_id = {s["id"]: s for s in plan["steps"]}
    module = adapter(state, store)
    rows, holds = {}, {}
    for sid in _in_order(plan, marked):
        if service("authority").stop_state(store) != "running" or budget.get("exhausted"):
            return rows, holds, "the run stopped or exhausted its budget during the correction round"
        steps[sid] = marked[sid]
        current = {**state, "steps": steps, "budget": budget}
        _, held, refused = _admitted(current, store, plan, [sid], steps)
        if held:
            rows.update(held)
            holds.update(refused)
            return rows, holds, f"the route refused the corrected step {sid}"
        item = {"step": deepcopy(by_id[sid]), "attempt": int(marked[sid].get("attempts") or 0) + 1}
        if marked[sid]["status"] == CORRECT:
            item["correction"] = deepcopy(correction)
        packet = _packet(current, item)
        found = route_dispatch(packet, lambda: _invoke(current, STEP_GRAPH, packet, {
            "correction": f"final.{correction['round']}.{sid}.{item['attempt']}"}))
        row, outcome, hold = fold_outcome(current, store, module, by_id[sid], item["attempt"], found, budget)
        steps[sid] = rows[sid] = row
        if hold is not None:
            holds[sid] = hold
        if row["status"] != STEP_DONE or outcome.get("escalation") or outcome.get("replan"):
            return rows, holds, f"the corrected step {sid} did not complete ({row['status']}: {row['reason']})"
    unmet = ledger_errors(store, "execute->final_review", "execute")
    if unmet:
        return rows, holds, "obligations remain open after the correction: " + "; ".join(e["message"] for e in unmet)
    return rows, holds, None


# ---- the P8 attacks (JR09): three tested attacks on the exact plan and drafted result precede the final triad --------

ATTACKS = "judgment-attacks"  # a valid attack round on one plan and drafted result: its document and the seat's step
ATTACK_NODE = "judgment.kill_the_result"  # the catalogue node of JR09


def adopted_document(store, run_dir, verdict, path):
    """The JSON document a review seat's governed step adopted as its output ``path``: the destination its custody
    record names, else ``steps/<step>/<path>`` of the run directory, verified by the digest the step reported and
    never through a symbolic link. ``(document, None)`` or ``(None, problem)``."""
    rows = [o for o in verdict.get("outputs") or () if type(o) is dict and (
        o.get("path") == path or str(o.get("artifact") or "").endswith(":" + path))]
    if not rows or type(rows[-1].get("sha256")) is not str:
        return None, f"the seat adopted no output {path} with its digest"
    wanted, step_id, run = rows[-1]["sha256"], verdict.get("step"), Path(run_dir)
    places = [row["record"].get("destination") for row in store.scan("custody")
              if row["record"].get("artifact") == f"{step_id}:{path}" and row["record"].get("sha256") == wanted
              and row["record"].get("status") == "accepted"]
    for relative in [p for p in places if type(p) is str] + [f"steps/{step_id}/{path}"]:
        parts = Path(relative).parts
        if Path(relative).is_absolute() or ".." in parts:
            continue
        target = run.joinpath(*parts)
        if any(run.joinpath(*parts[:i]).is_symlink() for i in range(1, len(parts) + 1)) or not target.is_file():
            continue
        raw = target.read_bytes()
        if hashlib.sha256(raw).hexdigest() != wanted:
            return None, f"the adopted output {path} differs from its adopted digest"
        try:
            return json.loads(raw.decode("utf-8")), None
        except ValueError:
            return None, f"the adopted output {path} is not JSON"
    return None, f"the adopted output {path} is not in the run directory"


def attack_round(state, store, plan):
    """The P8 attacks on this plan and its drafted result (``result_subject``): the attack seat runs and its adopted
    ``judgment-attacks.v1`` document is checked by the judgment package (``check_attacks``) against the exact plan and
    draft digests; a valid round is kept as a ``judgment-attacks`` record. Nothing else stands in for that check.
    ``(verdicts, attempt, record id or None, problems)``."""
    subject = result_subject(plan, state.get("steps") or {})
    verdicts, attempt, review = _run_seats(state, store, ["physics-critic"], purpose="attacks", protocols=("P8",),
                                           subject=subject)
    seat = next(iter(verdicts.values()), {})
    if seat.get("status") != STEP_DONE or not seat.get("credited"):
        return verdicts, attempt, None, [f"the attack seat ended {seat.get('status')} without a credited review"]
    document, problem = adopted_document(store, _run_dir(state), seat, ATTACKS_OUTPUT["path"])
    if problem is not None:
        return verdicts, attempt, None, [problem]
    check = getattr(service("judgment"), "check_attacks", None)
    if not callable(check):
        return verdicts, attempt, None, ["attacks_unverifiable: the judgment package offers no check_attacks"]
    problems = [str(p) for p in check(document, plan_sha256=plan["sha256"], draft_sha256=subject["sha256"]) or ()]
    if problems:
        return verdicts, attempt, None, problems
    record = store.append(ATTACKS, {"schema_version": 1, "kind": ATTACKS, "plan_sha256": plan["sha256"],
                                    "draft_sha256": subject["sha256"], "document": document,
                                    "attacks_sha256": _digest(document), "review": review, "step": seat.get("step"),
                                    "attempt": attempt, "receipts": list(seat.get("receipts") or [])})
    return verdicts, attempt, record, []


def attack_items(store, record_id):
    """The attacks as the final triad's must-check items (JR09: each attack, its test and its recorded outcome)."""
    attacks = store.read(ATTACKS, record_id)["record"]["document"]["attacks"]
    return [{"id": f"JR09:{a['axis']}", "row": "JR09",
             "text": f"Attack on {a['axis']}: {a['attack']} Test: {a['test']} Recorded outcome: {a['outcome']}."}
            for a in attacks]


def attack_errors(state, store, gate_name):
    """Where a judgment-route delivery is decided, its attacks again (JR09): the attack record the final review kept
    is in the store, names this plan and the drafted result the run has now, and its document still passes the
    judgment package's check. Any other plan needs none; anything else refuses delivery."""
    plan = current_plan(state, store)
    if plan["route"]["id"] != "judgment":
        return []
    record_id = (state.get("reviews") or {}).get("attacks_record")

    def error(code, message):
        return [{"code": code, "gate": gate_name, "provider": "controller.judgment", "message": message,
                 "fix": "run the three P8 attacks on the current plan and drafted result", "pins": [str(record_id or "")]}]
    try:
        row = store.read(ATTACKS, record_id) if record_id else None
    except (ValueError, KeyError):
        row = None
    if row is None:
        return error("attacks_missing", "no record of the three P8 attacks on this result is in the store")
    record = row["record"]
    if (record.get("plan_sha256"), record.get("draft_sha256")) != (plan["sha256"], _digest(state.get("steps") or {})):
        return error("attacks_stale", "the P8 attacks name another plan or drafted result")
    check = getattr(service("judgment"), "check_attacks", None)
    if not callable(check):
        return error("attacks_unverifiable", "the judgment package offers no check_attacks")
    problems = check(record.get("document"), plan_sha256=plan["sha256"], draft_sha256=record["draft_sha256"])
    return error("attacks_invalid", "; ".join(map(str, problems))[:1000]) if problems else []


def record_attack_rows(store, *, record_id=None, credit=None, problems=None):
    """JR09 (node ``judgment.kill_the_result``, a review-gated row): satisfied by the attack record and the final
    triad's credit once the triad credited and accepted the attacked result; violated, with the reason, when the
    attacks are missing or invalid. Recorded before the final review's transition is checked; without both pointers
    nothing is recorded and the row stays pending."""
    ledger = _row_ledger()
    if ledger is None or not (problems or (record_id and credit)):
        return None
    evidence = {"mechanism": "judgment.check_attacks", "provider": "P08", "point": ATTACK_NODE}
    if problems:
        status, evidence = "violated", {**evidence, "reason": "; ".join(problems)[:1000]}
    else:
        status, evidence = "satisfied", {"record": record_id, "credit": credit, **evidence}
    keys = [k for k in ledger.pending(store, node=ATTACK_NODE) if k.split("@", 1)[0] == "JR09"]
    _apply_rows(store, ATTACK_NODE, [("JR09", "P08", (key, status, evidence)) for key in keys], {})
    return None


def final_review(state):
    """The P8 attacks (judgment route) and the CHECK-IN 3 seats on the plan's results; only every seat's credited
    ``accept`` passes to CHECK-IN 3. A credited ``revise`` or ``unresolved`` starts a correction round within the bound
    (``correct_results``), then the attacks and the seats review the new results as a new round. On the judgment
    route the triad runs only after three valid attacks on the exact plan and drafted result (``attack_round``), and
    receives them as its must-check items; missing or invalid attacks end the run qualified."""
    store = _store(state)
    plan = current_plan(state, store)
    seats = checkin_seats(plan, "checkin3", CI3_SEATS)
    reviews = deepcopy(state.get("reviews") or {})
    budget = deepcopy(state.get("budget") or {})
    rows, holds = {}, {}
    while True:
        work = {**state, "steps": {**(state.get("steps") or {}), **rows}, "budget": budget, "reviews": reviews}
        attacks, items = {}, None
        if plan["route"]["id"] == "judgment":
            attacks, number, record_id, problems = attack_round(work, store, plan)
            reviews.update(attacks_rounds=list(reviews.get("attacks_rounds") or []) + [number],
                           attacks_record=record_id)
            if problems:
                # No triad without the three attacks (JR09): the run ends qualified, and JR09 says why.
                record_attack_rows(store, problems=problems)
                reviews.update(final={f"attacks:{k}": v for k, v in attacks.items()}, final_unmet=[], final_next="end")
                reason = ("the P8 attacks on the drafted result are missing or invalid (attacks_invalid: "
                          + "; ".join(problems) + ")")[:1200]
                break
            items = attack_items(store, record_id)
        assumption_verdicts = review_delivery_assumptions(work, store, plan)
        verdicts, attempt, _ = _run_seats(work, store, [s for s in seats if s not in assumption_verdicts],
                                         purpose="final", review_items=items)
        verdicts.update(assumption_verdicts)
        combined = {**{f"attacks:{k}": v for k, v in attacks.items()}, **verdicts}
        if attacks and _accepted(combined):
            # The attacks preceded a triad that credited and accepted the attacked result: JR09's evidence.
            first = next(iter(verdicts.values()), {})
            record_attack_rows(store, record_id=reviews["attacks_record"], credit=(first.get("receipts") or [None])[0])
        record_final_rows(store, plan, verdicts)
        unmet = ledger_errors(store, "final_review->checkin3", "final_review")
        store.append("transition", {"transition": "final_review->checkin3", "passed": not unmet, "errors": unmet[:50]})
        reviews.update(final=combined, final_unmet=[e["message"] for e in unmet], final_next="end",
                       final_rounds=list(reviews.get("final_rounds") or []) + [attempt])
        if unmet:
            reason = "final review obligations unmet"
            break
        if _accepted(combined):
            reviews["final_next"], reason = "ok", "the final review seats accepted the results"
            break
        corrections = dict(reviews.get("corrections") or {})
        done = int(corrections.get("final") or 0)
        correction, problem = review_correction(store, purpose="final", verdicts=combined, attempt=attempt,
                                                subject_sha256=_digest(work["steps"]), done=done,
                                                bound=correction_rounds(state))
        if problem is not None:
            reason = f"the final review did not accept the results ({problem[0]}: {problem[1]})"
            break
        reviews["corrections"] = {**corrections, "final": done + 1}
        corrected, refused, why = correct_results(work, store, plan, correction, budget)
        store.append("wave-result", {"number": (state.get("loop") or {}).get("number"), "phase": "final-correction",
                                     "round": correction["round"], "steps": deepcopy(corrected),
                                     "escalations": [], "replans": [], "incomplete": why})
        rows.update(corrected)
        holds.update(refused)
        if why is not None:
            reason = f"final review correction round {correction['round']}: {why}"
            break
    if reviews.get("final_next") == "ok":
        # R05: each original obligation whose mapped plan steps are all closed is covered by them (the ledger's join).
        join = getattr(service("ledger"), "parent_join", None)
        if callable(join):
            join(store)
    update = {"reviews": reviews, **_status("final_review", reason)}
    if rows:
        update.update(steps=rows, budget=budget)
    if holds:
        update["holds"] = holds
    return update


FINAL_NODE = "review.final"  # the catalogue node of D04


def _seat_credits(store):
    """``{(step id, role): latest step-credit record}`` of the controller's own review seats."""
    found = {}
    for row in store.scan("step-credit"):
        record = row["record"]
        role = ((record.get("own") or {}).get("query") or {}).get("role")
        if role:
            found[(record.get("step_id"), role)] = {**record, "_record_id": row["id"]}
    return found


def _approving(credit):
    own = (credit or {}).get("own") or {}
    return bool(credit) and credit.get("credited") is True and own.get("credited") is True \
        and own.get("verdict") in ("accept", "pass")


def record_final_rows(store, plan, verdicts):
    """D04 (each CI3 seat), recorded from the actions that enforce it once the CI3 triad has run: the presentation
    passed the sink's Tier A tracing before acceptance, and that seat's own fresh review (Tier B) is credited and
    approves. Nothing else records it; a seat that does not meet both, or a sink that cannot trace the presentation,
    keeps its row pending with the reason."""
    ledger = _row_ledger()
    if ledger is None:
        return
    pending = {seat: [k for k in ledger.pending(store, node=FINAL_NODE, step=REVIEW_SEATS["final"][0])
                      if k.split("@", 1)[0] == "D04" and f"/seat=seat:{seat}:" in k] for seat in sorted(verdicts)}
    if not any(pending.values()):
        return
    tracer = getattr(service("sink"), "trace_presentation", None)
    trace = tracer(store, plan) if callable(tracer) else None
    credits = _seat_credits(store)
    changes, missing = [], {}
    for seat, keys in pending.items():
        if not keys:
            continue
        credit = credits.get((REVIEW_SEATS["final"][0], seat))
        if trace is not None and trace["passed"] and _approving(credit):
            changes += [("D04", "P01", (key, "satisfied", {
                "record": trace["record"], "credit": credit["_record_id"], "artifacts": trace["artifacts"],
                "mechanism": "controller.final_review"})) for key in keys]
        else:
            missing["D04"] = ("P01: " + ("the sink offers no Tier A tracing of the presentation" if trace is None
                                         else "the presentation failed Tier A tracing" if not trace["passed"]
                                         else f"the {seat} review is not credited or does not approve"))[:500]
    if changes or missing:
        _apply_rows(store, FINAL_NODE, changes, missing)


def _final_branch(state):
    """CHECK-IN 3 only after a final review whose every seat credited and accepted the results (verdicts, not credit
    alone); otherwise a qualified ending."""
    reviews = state.get("reviews") or {}
    if reviews.get("final_unmet") or reviews.get("final_next") != "ok":
        return "end"
    return "ok" if _accepted(reviews.get("final") or {}) else "end"


def delivery_assumption_subject(store, plan):
    """Located assumptions and accepted result bytes that the delivery auditor must review."""
    from .assumptions import recorded
    assumptions = recorded(store, plan)
    from .step.custody import custody_index, _verify
    index = custody_index(store)
    artifacts, reported = [], set()
    producers = set(result_producers(plan))
    for artifact, row in sorted(index.items()):
        if row.get("step_id") not in producers or row.get("status") != "accepted":
            continue
        if _verify(index, artifact, store.run_dir, set(), 0, store):
            raise ValueError("the delivery assumption subject failed custody: " + artifact)
        artifacts.append({"artifact": artifact, "sha256": row["sha256"]})
        path = Path(store.run_dir) / row["destination"]
        try:
            document = json.loads(path.read_bytes())
        except (ValueError, UnicodeError):
            continue
        names = document.get("assumptions_reported", []) if type(document) is dict else []
        if type(names) is not list or any(type(name) is not str for name in names):
            raise ValueError("the result's assumptions_reported is not a list of ids")
        reported.update(names)
    pins = {"plan_sha256": plan["sha256"], "assumptions": assumptions, "artifacts": artifacts}
    return {**pins, "steps": sorted(producers), "reported": sorted(reported), "sha256": _digest(pins)}


def delivery_assumption_evidence(rundir):
    """Read-only K8 credit from the current observed seat, exact assumptions and result bytes."""
    from ..workflow import rdj_approval
    try:
        store, plan = rdj_approval.controller_plan(rundir)
        subject = delivery_assumption_subject(store, plan)
        if not subject["assumptions"]:
            return {"status": "violated", "reason": "assumption_record_missing", "evidence": {
                "plan_sha256": plan["sha256"], "subject_sha256": subject["sha256"]}}
        if not subject["artifacts"]:
            raise ValueError("the delivery assumption audit has no accepted result subject")
        step_id = REVIEW_SEATS["final"][0]
        credit, reason = rdj_approval.seat_review(store, step_id, "assumption-auditor", plan["sha256"],
                                                 label="delivery assumption audit", blind=False)
        if reason:
            return {"status": "violated", "reason": reason, "evidence": {"subject_sha256": subject["sha256"]}}
        from .step.custody import custody_index, _verify
        artifact = step_id + ":" + assumption_audit_path(subject["sha256"])
        output = custody_index(store).get(artifact)
        if not output or output["status"] != "accepted" or _verify(custody_index(store), artifact, store.run_dir, set(), 0, store):
            raise ValueError("the observed assumption audit has no current accepted output")
        query = store.read("step-credit", credit["credit"])["record"]["own"]["query"]
        producer = output.get("producer") or {}
        session = store.read("review-session", credit["session_record"])["record"]
        from ..workflow import review_dispatch, agent_worker
        observed_session = review_dispatch._session({"session_id": producer.get("session_id"),
                                                    "transport": {"id": session.get("transport_id")}})
        if (producer.get("kind") != "worker" or observed_session != credit["session"]
                or canonical_role(producer.get("role")) != "assumption-auditor"):
            raise ValueError("the audit output was not produced by the credited observed assumption seat")
        receipt = agent_worker.load_receipt(rundir, producer["node_id"], producer["attempt"])
        pin = agent_worker._record(rundir, producer["node_id"], producer["attempt"])["receipt"]
        # Adoption hashes the parsed receipt; the observation binds its published bytes.
        # Verify both identities through the dispatcher's current custody, never compare them as equal.
        if producer.get("receipt_sha256") != _digest(receipt) or query["receipt_sha256"] != pin["sha256"]:
            raise ValueError("the audit receipt does not match the credited observed assumption seat")
        document = json.loads((Path(rundir) / output["destination"]).read_bytes())
        audit = document["audit"]
        expected = {a["id"]: a for a in subject["assumptions"]}
        items = audit["items"]
        if len(items) != len(expected) or {a["id"] for a in items} != set(expected):
            raise ValueError("the audit does not enumerate every recorded assumption exactly once")
        for item in items:
            original = expected[item["id"]]
            if item.get("statement") != original["statement"] or original["locator"] not in item.get("locators", []):
                raise ValueError("the audit changed an assumption or omitted its located source")
        from ..validation import assumption_audit
        errors = assumption_audit.check(audit, {"assumptions_reported": subject["reported"]})
        if errors:
            raise ValueError("; ".join(errors))
        return {"status": "satisfied", "reason": None, "evidence": {**credit,
                "subject_sha256": subject["sha256"], "audit_sha256": output["sha256"],
                "assumptions": sorted(expected), "mechanism": "controller.delivery_assumptions"}}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"status": "violated", "reason": str(exc)[:500], "evidence": {"mechanism": "controller.delivery_assumptions"}}


def assumption_audit_path(subject_sha256):
    return "outputs/assumption-audit-" + subject_sha256 + ".json"


def review_delivery_assumptions(state, store, plan):
    """Dispatch the applicable delivery auditor before CHECK-IN 3; missing records remain violated."""
    from ..workflow import spawn_rows, review_points
    try:
        points = spawn_rows.derive(review_points._facts(store.run_dir))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Without the pinned request plan the policy cannot say whether the audit applies: nothing is credited.
        store.append("delivery-assumption-review", {"status": "violated", "reason": "review_policy_facts_unavailable",
                                                     "detail": str(exc)[:500], "plan_sha256": plan["sha256"]})
        return {}
    if not any(p["row"] == "K8" and p["gate"] == "delivery" for p in points):
        return {}
    if "assumption-auditor" not in checkin_seats(plan, "checkin3", CI3_SEATS):
        store.append("delivery-assumption-review", {"status": "violated", "reason": "delivery_seat_not_declared",
                                                     "plan_sha256": plan["sha256"]})
        return {}  # The staffing provider still refuses the missing observed seat at delivery.
    subject = delivery_assumption_subject(store, plan)
    if not subject["assumptions"]:
        store.append("delivery-assumption-review", {"status": "violated", "reason": "assumption_record_missing",
                                                     "subject_sha256": subject["sha256"]})
        return {"assumption-auditor": {"status": "held", "credited": False, "verdict": None,
                                       "reason": "assumption_record_missing"}}
    path = "inputs/delivery-assumptions-" + subject["sha256"] + ".json"
    raw = (json.dumps({**subject, "kind": "delivery-assumption-subject"}, indent=2, sort_keys=True) + "\n").encode()
    target = Path(store.run_dir) / path
    private_files.write(target, raw)
    located = {**subject, "assumption_audit": True, "pins": {"assumptions_sha256": subject["sha256"]},
               "artifacts": [{"artifact": path, "sha256": hashlib.sha256(raw).hexdigest()}, *subject["artifacts"]]}
    verdicts, _, _ = _run_seats(state, store, ["assumption-auditor"], purpose="final", subject=located,
        review_items=[{"id": "delivery-assumptions", "row": "K8", "text":
            "Enumerate each assumption in the pinned delivery-assumption-subject, preserving its id, statement "
            "and locator. Grade severity and control from located evidence. Write the declared JSON document "
            "with audit (schema_version 1, kind assumption-audit, items) and result (the actual accepted results' "
            "assumptions_reported). The controller independently checks coverage against the result bytes."}])
    store.append("delivery-assumption-review", delivery_assumption_evidence(store.run_dir))
    return verdicts


def deliver(state):
    """The sole sink delivers the plan's accepted results (it re-checks delivery and the final task itself)."""
    store = _store(state)
    _governed(state, store)
    plan = current_plan(state, store)
    envelope_delivery(store)  # the delivery-stage envelope check with the independent broker count, when composed
    receipt = service("sink").deliver(store, plan)
    # A delivery the sink explicitly rejected (its own refusals, or nothing delivered) closes through the bounded
    # task ending. A delivery withheld from acceptance only by unmet obligations stays the run's delivered receipt,
    # labelled qualified or diagnostic, with its delivery gate decisions.
    refusals = (receipt.get("work") or {}).get("current_refusals") or []
    if receipt.get("accepted") is False and (refusals or receipt.get("delivered") is False):
        raise nodes.RecoveryHold("sink_delivery_refused: " + json.dumps(refusals or receipt.get("labels") or [],
                                                                        default=str)[:1500])
    return {"delivery": {"receipt": receipt.get("id") or receipt.get("receipt_id"),
                         "qualified": bool(receipt.get("qualified", False)),
                         "labels": list(receipt.get("labels") or []),
                         "architecture_complete": receipt.get("architecture_complete")},
            **_status("delivered", "delivered through the sink", terminal=None)}


def bounded_end(state):
    store = _store(state)
    status = state.get("status") or {}
    wave = state.get("loop") or {}
    reason = status.get("reason") or wave.get("reason") or "bounded ending"
    try:
        reason = _recovery_reason(state, store, reason)
    except Exception as exc:  # naming never blocks the ending
        store.append("ending-hook", {"error": f"recovery: {type(exc).__name__}: {exc}"[:1000]})
    named = _autonomy("ending_reason")
    if callable(named):
        try:
            reason = named(store, reason)  # the boundary the run reached, named first (N6)
        except Exception as exc:  # naming never blocks the ending
            store.append("ending-hook", {"error": f"boundary: {type(exc).__name__}: {exc}"[:1000]})
    try:
        module = adapter(state, store)
        if module is not None and hasattr(module, "ending"):
            module.ending(str(reason)[:2000], adapter_context(state, store))
    except Exception as exc:  # the route's record of unfinished work never blocks the ending
        store.append("ending-hook", {"error": f"{type(exc).__name__}: {exc}"[:1000]})
    try:
        # A stop, a refused gate or an exhausted bound: the authority's mechanism rows its records now show.
        _record_mechanism_rows(store, "controller.bounded_end")
    except Exception as exc:  # recording never blocks the ending; the rows stay pending
        store.append("ending-hook", {"error": f"ledger evidence: {type(exc).__name__}: {exc}"[:1000]})
    try:
        envelope_delivery(store)
    except Exception as exc:  # the sink's own check then decides; an unknown envelope is never accepted
        store.append("ending-hook", {"error": f"engagement envelope: {type(exc).__name__}: {exc}"[:1000]})
    receipt = service("sink").bounded_end(store, str(reason)[:2000])
    store.append("ending", {"reason": reason, "receipt": receipt.get("id") or receipt.get("receipt_id")})
    return {"delivery": {"receipt": receipt.get("id") or receipt.get("receipt_id"), "qualified": True,
                         "labels": list(receipt.get("labels") or []), "reason": reason,
                         "architecture_complete": False},
            **_status("bounded_end", str(reason)[:500], terminal="qualified")}


def _recovery_reason(state, store, reason):
    """The ending's reason with every unrecovered gap named and the alternatives tried (``recovery.summary``)."""
    from . import recovery
    pins = state.get("plan") or {}
    rows = [row["record"] for row in store.scan(recovery.KIND)]
    if rows and rows[-1].get("phase") == "adopted" and pins.get("approved_sha256") != pins.get("sha256"):
        # The recovery's deviation was not approved before the run ended.
        store.append(recovery.KIND, {"schema_version": 1, "phase": "declined", "step": rows[-1].get("step"),
                                     "plan_sha256": rows[-1].get("plan_sha256")})
    text = recovery.summary(store)
    return f"{reason}; {text}" if text else reason


def _hold_body(state):
    status = state.get("status") or {}
    if status.get("phase") == "handler":
        return {"status": {**status, "phase": "hold"}}
    return {"status": {"phase": "hold", "terminal": "hold", "reason": "controller_hold", "would_make_possible": None}}


def _hold_branch(state):
    failures = state.get("failures") or {}
    latest = failures[next(reversed(failures))] if failures else None
    return "end" if latest and latest.get("node") in ("bounded_end",) else "bounded_end"


def _decision_router(state, failure):
    return "end" if failure.get("node") in ("bounded_end",) else "bounded_end"


# ---- the builder -----------------------------------------------------------------------------

def compose_services():
    """Install the collaborating packages' explicit composition callbacks in this process.

    The ledger reads the authority record a waiver cites only through the authority service's
    authenticated reader, never a record a caller wrote (PACKAGES 0.2). Every controller process
    builds this graph, at start and at each resume, so each composes here. A stand-in service
    composes nothing, and the ledger then refuses every waiver.
    """
    register = getattr(service("ledger"), "register_authority_reader", None)
    reader = getattr(service("authority"), "read_authority", None)
    if callable(register) and callable(reader):
        register(reader)
    # The installed engagement provider's gates are composed explicitly too; importing the ledger never imports it.
    # Without a provider the ledger holds every gated transition once its catalogue names engagement rows.
    module = __package__ + ".engagement"
    try:
        engagement = import_module(module)
    except ModuleNotFoundError as exc:
        if exc.name != module:
            raise
    else:
        register_gates = getattr(engagement, "register_gates", None)
        if callable(register_gates) and callable(getattr(service("ledger"), "register_gate_hook", None)):
            register_gates(service("ledger"))


def build(ctx):
    compose_services()
    from langgraph.graph import END, START, StateGraph
    from ..workflow import graph_substrate
    builder = StateGraph(RunState)
    add = lambda name, node: nodes.add(builder, name, node, graph_id=GRAPH_ID)  # noqa: E731
    route, connect = nodes.route, nodes.connect
    guard_routes = {"drain": "bounded_end", "exhausted": "bounded_end", "escalate": "bounded_end"}

    add("decision_turn", nodes.decision_turn(GRAPH_ID, router=_decision_router, path_map={"bounded_end": "bounded_end"}))
    add("reconcile", nodes.reconcile_node())
    add("hold", nodes.Node("hold", _hold_body, then=route(_hold_branch, {"bounded_end": "bounded_end", "end": END})))

    add("intake", nodes.Node("effect", intake))
    add("route_select", nodes.Node("effect", route_select))
    connect(builder, "route_select", route(_route_branch, {"fixed": "plan_compile", "judgment": "judgment_plan"}))
    add("plan_compile", nodes.Node("effect", plan_compile))
    connect(builder, "plan_compile", route(_after_compile, {"planned": "materialise", "judgment": "judgment_plan"}))
    add("judgment_plan", nodes.Node("subgraph", judgment_plan))
    add("materialise", nodes.Node("effect", materialise))

    # The prepare phase: its own guard, planner, dispatcher, map node and join, before CHECK-IN 1.
    step_row = graph_registry.get(STEP_GRAPH)
    step_ctx = graph_substrate.BuildContext(scope_root=ctx.scope_root, graph_id=STEP_GRAPH, version=step_row["version"],
                                            instance=deepcopy(ctx.instance), row=step_row)
    target = graph_substrate.build(STEP_GRAPH, step_ctx, checkpointer=None)
    add("prepare_guard", nodes.guard(_guard_policy, {"go": "prepare_wave", **guard_routes}))
    add("prepare_wave", nodes.Node("effect", prepare_wave))
    connect(builder, "prepare_wave", route(_prepare_branch, {"dispatch": "dispatch_prepare", "review": "bind",
                                                             "blocked": "bounded_end"}))
    add("dispatch_prepare", nodes.Node("effect", dispatch_wave))
    prepare_edge, prepare_map = nodes.map_node(_wave_items, _item_key, target, _packet, name="prepare_step")
    add("prepare_step", prepare_map)
    connect(builder, "dispatch_prepare", prepare_edge)
    add("prepare_join", nodes.Node("effect", join))
    add("bind", nodes.Node("effect", bind))

    add("plan_review", nodes.Node("subgraph", plan_review))
    connect(builder, "plan_review", route(_review_branch, {"ok": "checkin1", "revise": "revise", "end": "bounded_end"}))
    add("revise", nodes.Node("effect", revise))
    connect(builder, "revise", route(_revise_branch, {"fixed": "plan_compile", "judgment": "judgment_plan",
                                                      "end": "bounded_end"}))

    for point, gate_node, passed, refused in (("checkin1", "checkin1_gate", "approved", "checkin1_refused"),
                                              ("checkin2", "checkin2_gate", "went", "bounded_end"),
                                              ("deviation", "deviation_gate", "approved_deviation", "bounded_end"),
                                              ("escalate", "escalate_gate", "wave_guard", "escalation_held"),
                                              ("checkin3", "checkin3_gate", "deliver", "bounded_end")):
        add(point, authority_point(point))
        add(gate_node, controller_gate(gate_node))
        builder.add_edge(point, gate_node)
        connect(builder, gate_node, nodes.gate_route(GATE_NAMES[gate_node], passed=passed, refused=refused))
    add("approved", nodes.Node("effect", approved))
    add("approved_deviation", nodes.Node("effect", approved_deviation))
    add("went", nodes.Node("effect", went))
    add("escalation_held", nodes.Node("effect", escalation_held))
    add("checkin1_refused", nodes.Node("effect", checkin1_refused))
    connect(builder, "checkin1_refused", route(_checkin1_refused_branch, {"revise": "revise", "end": "bounded_end"}))

    # Execution after CHECK-IN 1.
    add("wave_guard", nodes.guard(_guard_policy, {"go": "plan_wave", **guard_routes}))
    add("plan_wave", nodes.Node("effect", plan_wave))
    connect(builder, "plan_wave", route(_wave_branch, {
        "dispatch": "dispatch_wave", "waypoint": "checkin2", "deviation": "deviation", "escalate": "escalate",
        "replan": "replan", "done": "final_review", "blocked": "bounded_end"}))
    add("dispatch_wave", nodes.Node("effect", dispatch_wave))
    edge, mapped = nodes.map_node(_wave_items, _item_key, target, _packet, name="step")
    # Each item's own substrate invocation, offered to its route's dispatch hook (never a second path beside it).
    add("step", dataclasses.replace(mapped, function=route_dispatching(mapped.function)))
    connect(builder, "dispatch_wave", edge)
    add("join", nodes.Node("effect", join))
    add("replan", nodes.Node("subgraph", replan))
    add("rematerialise", nodes.Node("effect", rematerialise))

    add("final_review", nodes.Node("subgraph", final_review))
    connect(builder, "final_review", route(_final_branch, {"ok": "checkin3", "end": "bounded_end"}))
    add("deliver", nodes.Node("effect", deliver))
    add("bounded_end", nodes.Node("effect", bounded_end))

    builder.add_edge(START, "intake")
    builder.add_edge("intake", "route_select")
    builder.add_edge("judgment_plan", "materialise")
    builder.add_edge("materialise", "prepare_guard")
    builder.add_edge("prepare_step", "prepare_join")
    builder.add_edge("prepare_join", "prepare_guard")
    builder.add_edge("bind", "plan_review")
    builder.add_edge("approved", "wave_guard")
    builder.add_edge("approved_deviation", "wave_guard")
    builder.add_edge("went", "wave_guard")
    builder.add_edge("escalation_held", "wave_guard")
    builder.add_edge("step", "join")
    builder.add_edge("join", "wave_guard")
    builder.add_edge("replan", "rematerialise")
    builder.add_edge("rematerialise", "wave_guard")
    builder.add_edge("deliver", END)
    builder.add_edge("bounded_end", END)
    return builder


def instance(run_id):
    return {"run_id": run_id}
