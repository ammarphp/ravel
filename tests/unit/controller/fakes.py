"""Fakes for every binding interface of the 1.3.0 controller build (PACKAGES.md section 0.2).

Each fake has the binding signature and returns the documented shape, so a package can build and
test against the interfaces before the package that owns one lands. They are deterministic,
need no model, provider, network or native tool, and keep their records in memory or under the
test's temporary directory. Use them through ``installed`` (the controller's service seam), which
the test harness enables (``ravel.controller.testing``).

Contents:

- ``FakeRunStore``: an in-memory ``RunStore`` (P01) with the same record envelopes.
- ``fake_controller_owned``, ``fake_select``, ``fake_compile``, ``fake_check``: P01 functions.
- ``FakeLedger`` (P02), ``FakeInstructions`` (P03), ``FakeAuthority`` (P06), ``FakeSink`` (P07),
  ``FakeJudgment`` (P08), ``FakeConfine`` (P05), ``fake_decide``/``fake_family_relation`` (P13).
- ``step_run`` (P04): the ``step.run`` entry; ``fake_step_graph``/``fake_judgment_graph``: registered
  stand-ins for the ``controller.step`` and ``judgment.plan`` graphs (rows from ``graph_rows``).
- ``route_specs``: one fictional route spec per row of the start.md table.

The ``controller.step`` packet (the map target's input view) is ``{"step": <step.v1>, "context":
{...}}`` and its final ``results["step"]`` is the step outcome (``STEP_OUTCOME_KEYS``). The
``judgment.plan`` input view is ``{"request": ..., "plan": <plan.v1 or None>, "context": {...}}``
and its final ``results["plan"]`` is a ``plan.v1``.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import itertools
import json
import time
from pathlib import Path
from typing import Annotated, TypedDict

STEP_OUTCOME_KEYS = ("step_id", "attempt", "status", "outputs", "receipts", "escalation", "replan",
                     "budget", "judgments", "review", "reason")
STEP_STATUSES = ("completed", "failed", "held", "escalated", "budget_exhausted", "stopped")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


# ---- P01: store, ownership, routes, command policy -----------------------------------------------

class FakeRunStore:
    """In-memory ``RunStore``: append-only envelopes with a hash chain and a monotonically stamped clock."""
    _seq = itertools.count(1)

    def __init__(self, run_id: str, *, root: Path | None = None):
        self.run_id = run_id
        self.store_root = Path(root) if root is not None else Path("/nonexistent-fake-store")
        self.root = self.store_root / run_id
        self.entries: list[dict] = []
        self.blobs: dict[str, bytes] = {}

    def append(self, kind: str, record: dict) -> str:
        json.dumps(record, allow_nan=False)
        prev = self.entries[-1]["digest"] if self.entries else "0" * 64
        body = {"schema_version": 1, "seq": len(self.entries) + 1, "kind": kind, "time_ns": time.time_ns(),
                "prev": prev, "record": deepcopy(record)}
        entry = {**body, "id": f"{kind}-{body['seq']:06d}-{digest(body)[:12]}"}
        entry["digest"] = digest(entry)
        self.entries.append(entry)
        return entry["id"]

    def read(self, kind: str, record_id: str) -> dict:
        for entry in self.entries:
            if entry["id"] == record_id and entry["kind"] == kind:
                return deepcopy(entry)
        raise ValueError(f"no {kind} record {record_id}")

    def scan(self, kind: str) -> list[dict]:
        return [deepcopy(e) for e in self.entries if e["kind"] == kind]

    def latest(self, kind):
        rows = self.scan(kind)
        return rows[-1] if rows else None

    def head(self):
        return {"seq": len(self.entries), "digest": self.entries[-1]["digest"] if self.entries else "0" * 64}

    def checkpointer(self):
        from langgraph.checkpoint.memory import InMemorySaver
        return InMemorySaver()

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def put_blob(self, data: bytes) -> str:
        key = hashlib.sha256(data).hexdigest()
        self.blobs[key] = bytes(data)
        return key

    def get_blob(self, key: str) -> bytes:
        return self.blobs[key]

    def verify(self):
        return []


def fake_controller_owned(run_dir: Path, owned=()) -> str | None:
    """``controller_owned`` over an explicit set of ``(path, run_id)`` pairs."""
    target = Path(run_dir).resolve()
    for path, run_id in owned:
        path = Path(path).resolve()
        if target == path or path in target.parents:
            return run_id
    return None


def fake_select(contract: dict, reading: dict, supplied: list[dict]) -> dict:
    mode = (contract or {}).get("task_mode")
    route = {"reproduce": "analysis", "scan": "analysis", "generate": "scoped", "likelihood": "scoped",
             "calculation": "calculation", "research": "research"}.get(mode, "judgment")
    return {"route": route, "evidence": [{"row": None, "route": route, "matched": True, "reason": "fake"}]}


def fake_compile(route_spec: dict, reading: dict, contract: dict, **_) -> dict:
    from ravel.controller.routes import compile as real
    return real(route_spec, reading, contract)


def fake_check(argv: list[str], owned=()) -> str | None:
    for argument in argv:
        if fake_controller_owned(argument, owned):
            return "refused for a controller-owned run (fake policy)"
    return None


# ---- P02: obligation ledger ---------------------------------------------------------------------

class FakeLedger:
    """``materialise``/``record``/``gate``/``population_equality``/``summary`` over a store's records.

    ``unmet`` maps a transition to the rows ``gate`` returns (default: none), so a test can hold
    any edge. Every call is logged in ``calls``.
    """
    STATUSES = ("pending", "satisfied", "violated", "waived", "not_applicable")

    def __init__(self, unmet=None, refuse=None):
        self.unmet = dict(unmet or {})
        self.refuse = dict(refuse or {})
        self.calls: list[tuple] = []
        self.contexts: list[tuple] = []

    def materialise(self, store, stage: str, context: dict) -> list[str]:
        self.calls.append(("materialise", stage))
        self.contexts.append((stage, deepcopy(context)))
        ids = [f"{stage.upper()}-{i}" for i, _ in enumerate(context.get("rows") or [stage])]
        for entry_id in ids:
            store.append("ledger", {"entry_id": entry_id, "status": "pending", "stage": stage})
        return ids

    def record(self, store, entry_id: str, status: str, evidence: dict) -> None:
        if status not in self.STATUSES:
            raise ValueError(status)
        self.calls.append(("record", entry_id, status))
        store.append("ledger", {"entry_id": entry_id, "status": status, "evidence": deepcopy(evidence)})

    def gate(self, store, transition: str) -> list[dict]:
        self.calls.append(("gate", transition))
        return deepcopy(self.unmet.get(transition, []))

    def decide(self, store, rundir, gate_name: str, action: dict) -> list:
        """The decision gate's re-check by the acting node; ``refuse`` maps a gate to its errors."""
        self.calls.append(("decide", gate_name))
        self.contexts.append(("decide", deepcopy({"gate": gate_name, **action})))
        return deepcopy(self.refuse.get(gate_name, []))

    @staticmethod
    def population_equality(expected: list[str], actual: list[str]) -> list[str]:
        present = set(actual)
        return [item for item in expected if item not in present]

    def summary(self, store) -> dict:
        rows = store.scan("ledger")
        counts = {}
        for row in rows:
            status = row["record"].get("status")
            counts[status] = counts.get(status, 0) + 1
        return {"counts": counts, "head": store.head()["digest"] if hasattr(store, "head") else None}


# ---- P03: instructions ------------------------------------------------------------------------

class FakeInstructions:
    def manifest(self, step: dict, card: dict | None) -> dict:
        units = [{"id": f"{source}#fake/1", "sha256": digest(source), "kind": "duty"}
                 for source in step.get("instruction_sources") or ()]
        return {"units": units, "sha256": digest(units)}

    def packet(self, manifest: dict, card: dict | None, step: dict, inputs: list[dict]) -> dict:
        text = json.dumps({"manifest": manifest, "step": step.get("id"), "inputs": inputs}, sort_keys=True)
        return {"text": text, "sha256": hashlib.sha256(text.encode()).hexdigest(), "schema": "producer.v2"}

    def check_ack(self, manifest: dict, final_record: dict, outputs: list[str]) -> list[str]:
        ack = (final_record or {}).get("instruction_ack") or {}
        return [] if ack.get("manifest_sha256") == manifest.get("sha256") else ["instruction acknowledgement missing"]

    def reviewer_items(self, manifest: dict, card: dict | None) -> list[dict]:
        return [{"item": u["id"], "source": "manifest"} for u in manifest.get("units") or ()]


# ---- P05: confinement ------------------------------------------------------------------------

class FakeConfine:
    def popen(self, spec: dict, **popen_kwargs):
        raise RuntimeError("the fake confined launcher starts no process")

    def probe(self, kind: str, target: dict) -> dict:
        return {"kind": kind, "tools": [], "mounts": [], "env_names": [], "network": "none"}

    def backends(self) -> dict:
        return {"bwrap": "fake: unavailable", "sandbox-exec": "fake: unavailable", "oci-local": "fake: unavailable"}

    def mint_capability(self, store, launch_id: str, scope: dict) -> str:
        return "fake-capability-" + digest({"launch": launch_id, "scope": scope})[:16]

    def verify_capability(self, token: str, jobscript: Path) -> dict:
        return {"valid": token.startswith("fake-capability-"), "launch_id": None}


# ---- P06: authority ---------------------------------------------------------------------------

class FakeAuthority:
    """The authority service (P06) from a script, with its request, record and verification contract.

    ``answers`` maps a kind to a decision or a list of them, consumed per new subject: a decision of
    the kind's vocabulary (``DECISIONS``), ``"pending"``, or ``("default", option)``. An unscripted
    kind gets its positive decision (machine authority in autonomous mode). ``stop`` is the stop
    state, or a list of states consumed per call. Subjects are checked as the real service checks
    them: a typed view of this run with string pins, the pins each kind binds, a change row for a
    deviation, options for an R3 action, and bounds of rung, stages, budget and policy only.
    """
    DECISIONS = {"approve_plan": ("approve", "adjust", "reject"), "go": ("go", "adjust", "stop"),
                 "deviation": ("approve", "reject"), "final": ("accept", "rework", "reject"),
                 "r3_action": ("approve", "reject", "default"), "escalation": ("answer", "reject", "default")}
    POSITIVE = {"approve_plan": "approve", "go": "go", "deviation": "approve", "final": "accept",
                "r3_action": "approve", "escalation": "answer"}
    AUTHORIZING = {"approve_plan": ("approve",), "go": ("go",), "deviation": ("approve",), "final": (),
                   "r3_action": ("approve", "default"), "escalation": ("answer", "default")}
    CHANGE_KEYS = ("parameter", "from", "to", "why", "touches", "direction")
    DIRECTIONS = ("tighten", "loosen", "input", "plan", "scope")
    _uids = itertools.count(1)

    def __init__(self, answers=None, *, mode="autonomous", stop="running", config=None, clock=time.time_ns):
        self.answers = {k: (list(v) if type(v) is list else [v]) for k, v in (answers or {}).items()}
        self.mode, self.stop, self.config = mode, stop, dict(config or {})
        self.clock = clock
        self.calls: list[tuple] = []
        self.decided: dict = {}
        self.since: dict = {}

    def operator_config(self) -> dict:
        return {"mode": self.mode, "budgets": {}, "r3_policy": "escalate_and_wait", "wait_bound_seconds": 0,
                "notify_command": None, "store_root": None, **self.config}

    def _append(self, store, body):
        body = {"schema": "authority-record.v1", "uid": f"auth-{next(self._uids):06d}", "run_id": store.run_id,
                "time_ns": time.time_ns(), "review_credit": False, "human_identity_authenticated": False, **body}
        store_id = store.append("authority", body)
        return {**body, "id": body["uid"], "store_id": store_id}

    def freeze_mode(self, store, contract: dict, *, run_dir=None) -> dict:
        self.calls.append(("freeze_mode", run_dir is not None))
        record = self._append(store, {"kind": "mode", "mode": self.mode, "bounds": {}, "label": "operator_configured_machine"})
        return {**record, "record_id": record["id"]}

    @classmethod
    def check_subject(cls, store, kind, subject, bounds):
        if type(subject) is not dict or type(subject.get("view")) is not dict:
            raise ValueError(f"a {kind} request carries the run-state view it is decided on")
        extra = set(subject) - {"view", "checkin", "gate", "change", "policy", "conservative_default",
                                "request_pins", "inferred_critical_facts", "obligations"}
        if extra:
            raise ValueError(f"unknown request subject fields {sorted(extra)}")
        view = subject["view"]
        if view.get("run_id") != store.run_id:
            raise ValueError("the check-in view names a different run")
        if set(view) - {"run_id", "pins", "sections", "flags", "items", "options", "required_sections", "summary"}:
            raise ValueError("unknown check-in view fields")
        pins = view.get("pins")
        if type(pins) is not dict or not pins or any(type(k) is not str or type(v) is not str or not v
                                                     for k, v in pins.items()):
            raise ValueError("a check-in view carries string pins")
        for key, rows in (view.get("items") or {}).items():
            if key not in ("steps", "deliverables", "boundaries", "ambiguities", "questions", "assumptions") or \
                    any(type(r) is not str or not r.strip() for r in rows):
                raise ValueError(f"check-in items {key} are nonempty strings")
        for flag in view.get("flags") or []:
            if set(flag) != {"kind", "text"} or flag["kind"] not in ("assumption", "decision", "question",
                                                                      "ambiguity", "risk"):
                raise ValueError("a check-in flag is {kind, text}")
        if kind == "approve_plan" and "plan_sha256" not in pins:
            raise ValueError("CHECK-IN 1 binds the plan digest")
        if kind == "go" and ("approve_plan" not in pins or not any(k.startswith("waypoint") for k in pins)):
            raise ValueError("CHECK-IN 2 binds the CHECK-IN 1 record and the waypoint evidence")
        if kind in ("deviation", "final") and "approve_plan" not in pins:
            raise ValueError(f"a {kind} check-in binds the CHECK-IN 1 record")
        change = subject.get("change")
        if kind == "deviation" and (type(change) is not dict or set(change) != set(cls.CHANGE_KEYS)
                                    or change["direction"] not in cls.DIRECTIONS or not change["touches"]):
            raise ValueError("a deviation states one exact change row")
        if kind != "deviation" and change is not None:
            raise ValueError("only a deviation carries a change row")
        if kind in ("r3_action", "escalation") and not view.get("options"):
            raise ValueError(f"a {kind} check-in offers its options")
        default = subject.get("conservative_default")
        if default is not None and default not in [o["id"] for o in view.get("options") or []]:
            raise ValueError("a conservative default names an offered option")
        if type(bounds) is not dict or set(bounds) - {"rung", "stages", "budget", "policy"}:
            raise ValueError("request bounds hold rung, stages, budget and policy only")

    def request(self, store, kind: str, subject: dict, bounds: dict) -> dict:
        self.check_subject(store, kind, subject, bounds)
        self.calls.append(("request", kind, deepcopy(subject)))
        key = (kind, digest(subject["view"]["pins"]))
        if key in self.decided:
            return deepcopy(self.decided[key])
        queue = self.answers.get(kind)
        answer = queue.pop(0) if queue and len(queue) > 1 else (queue[0] if queue else self.POSITIVE[kind])
        if answer == "pending":
            # The real service's pending answer: one request per subject, waiting since its first ask.
            since = self.since.setdefault(key, self.clock())
            return {"pending": {"request": f"request-{len(self.since):04d}", "kind": kind,
                                "reason": "waiting for a human (fake)", "needed": "an operator answer",
                                "since_ns": since, "waited_seconds": (self.clock() - since) / 1e9,
                                "wait_bound_seconds": self.operator_config()["wait_bound_seconds"]}}
        decision, option = answer if type(answer) is tuple else (answer, None)
        if decision not in self.DECISIONS[kind]:
            raise ValueError(f"{decision!r} is not a {kind} decision")
        label = "operator_configured_machine" if self.mode == "autonomous" else "physicist_terminal_response"
        # An option without effect (the hold of an R3 action) authorizes nothing, whatever the decision.
        effects = {o["id"]: o.get("effect", True) for o in subject["view"].get("options") or []}
        record = self._append(store, {
            "kind": kind, "decision": decision, "option": option, "label": label,
            "subject": {"pins": deepcopy(subject["view"]["pins"]), "change": deepcopy(subject.get("change"))},
            "bounds": deepcopy(bounds),
            "authorizes_effects": decision in self.AUTHORIZING[kind] and kind != "final" and effects.get(option, True)})
        self.decided[key] = record
        return deepcopy(record)

    def disposition(self, store, record_id, *, kind, subject=None):
        """A current decision of ``kind`` for the current pins, authenticated without granting anything (the final
        disposition included): the record of an authenticated label, never an unattested terminal answer."""
        for entry in store.scan("authority"):
            body = entry["record"]
            if record_id in (body.get("uid"), entry["id"]):
                break
        else:
            raise ValueError(f"{kind} authority {record_id!r} is not in the controller store")
        if body.get("kind") != kind:
            raise ValueError(f"record {record_id} is {body.get('kind')} authority, not {kind}")
        if body.get("label") not in ("operator_configured_machine", "delegated_machine", "operator_command"):
            raise ValueError(f"the {body.get('label')} label authorizes nothing")
        for name, value in (subject or {}).items():
            if body["subject"]["pins"].get(name) != value:
                raise ValueError(f"{kind} authority {record_id} is stale: pin {name} changed")
        return {**body, "id": body["uid"]}

    def verify(self, store, record_id, *, kind, subject=None):
        for entry in store.scan("authority"):
            body = entry["record"]
            if body.get("uid") == record_id:
                break
        else:
            raise ValueError(f"{kind} authority {record_id!r} is not in the controller store")
        if body.get("kind") != kind:
            raise ValueError(f"record {record_id} is {body.get('kind')} authority, not {kind}")
        if body.get("decision") not in self.AUTHORIZING[kind] or not body.get("authorizes_effects"):
            raise ValueError(f"{kind} record {record_id} decided {body.get('decision')!r}, which authorizes nothing")
        for name, value in (subject or {}).items():
            if body["subject"]["pins"].get(name) != value:
                raise ValueError(f"{kind} authority {record_id} is stale: pin {name} changed")
        return body

    def records(self, store):
        return [{k: e["record"].get(k) for k in ("uid", "kind", "decision", "option", "label")}
                for e in store.scan("authority")]

    def stop_state(self, store) -> str:
        if type(self.stop) is list:
            return self.stop.pop(0) if len(self.stop) > 1 else self.stop[0]
        return self.stop


# ---- P07: sink --------------------------------------------------------------------------------

class FakeSink:
    def __init__(self):
        self.calls: list[tuple] = []

    def deliver(self, store, plan: dict) -> dict:
        self.calls.append(("deliver", plan.get("sha256")))
        receipt = {"kind": "delivery", "qualified": False, "plan_sha256": plan.get("sha256"), "labels": [],
                   "architecture_complete": False}
        receipt["id"] = store.append("receipt", receipt)
        return receipt

    def bounded_end(self, store, reason: str) -> dict:
        self.calls.append(("bounded_end", reason))
        receipt = {"kind": "delivery", "qualified": True, "reason": reason, "labels": ["QUALIFIED ENDING"],
                   "architecture_complete": False}
        receipt["id"] = store.append("receipt", receipt)
        return receipt

    def receipt(self, store) -> dict:
        rows = store.scan("receipt")
        return rows[-1]["record"] if rows else {}


# ---- P08: judgment ----------------------------------------------------------------------------

class FakeJudgment:
    CLASSES = ("R0", "R1", "R2", "R3")

    def classify(self, action: dict) -> str:
        declared = (action or {}).get("class")
        return declared if declared in self.CLASSES else "R3"

    def record_judgment(self, store, record: dict) -> str:
        return store.append("judgment", {"schema": "judgment-record.v1", **deepcopy(record)})

    @staticmethod
    def bounds(mode: dict) -> dict:
        """The installed judgment policy's bounds for the run's frozen mode (replans, review rounds)."""
        from ravel.controller import judgment
        return judgment.bounds(mode)

    @staticmethod
    def check_attacks(document, *, plan_sha256: str, draft_sha256: str) -> list[str]:
        """The installed judgment package's check of the three P8 attacks (JR09)."""
        from ravel.controller import judgment
        return judgment.check_attacks(document, plan_sha256=plan_sha256, draft_sha256=draft_sha256)


# ---- P13: review independence ------------------------------------------------------------------

def fake_decide(query: dict) -> dict:
    return {"credited": True, "label": "separate session, same model family", "reasons": []}


def fake_family_relation(models: dict) -> str:
    families = {v for v in (models or {}).values() if v}
    return "same" if len(families) == 1 else ("different" if families else "unknown")


# ---- P04: the step entry and the registered stand-in graphs ------------------------------------

def step_outcome(step, attempt=1, status="completed", **extra):
    outcome = {"step_id": step["id"], "attempt": attempt, "status": status,
               "outputs": [{"path": o["path"], "sha256": digest({"step": step["id"], "path": o["path"]})}
                           for o in step.get("outputs") or ()],
               "receipts": [f"fake-receipt-{step['id']}-{attempt}"], "escalation": None, "replan": None,
               "budget": {"wall_seconds": 0}, "judgments": [], "review": {}, "reason": None}
    outcome.update(extra)
    return outcome


SCRIPT: dict = {}  # step id -> list of outcome overrides, consumed per attempt (tests set it)
DISPATCHED: list = []  # (step id, attempt) in dispatch order
PACKETS: list = []  # (step, context) as the step graph received them


def attack_document(step: dict) -> dict:
    """A ``judgment-attacks.v1`` document on the plan and drafted result an attack seat's step names (P8)."""
    parameters = step.get("parameters") or {}
    return {"schema_version": 1, "kind": "judgment-attacks",
            "subject": {"plan_sha256": parameters.get("subject_plan_sha256"),
                        "draft_sha256": parameters.get("subject_sha256")},
            "attacks": [{"axis": axis, "attack": f"the fictional {axis} could be wrong",
                         "test": f"a fictional {axis} test", "outcome": "survives",
                         "evidence": ["a located fictional observation"]}
                        for axis in ("basis", "acceptance", "statistics")]}


def step_run(store, step: dict, context: dict) -> dict:
    """``step.run``: the scripted outcome of one attempt of ``step`` (default: completed). A completed P8 attack seat
    writes its declared ``judgment-attacks`` document where the governed step adopts it (``steps/<step>/<path>`` of
    the run directory) and reports its digest, unless the script sets the outputs."""
    attempt = int((context or {}).get("attempt", 1))
    DISPATCHED.append((step["id"], attempt))
    PACKETS.append((deepcopy(step), deepcopy(context)))
    queue = SCRIPT.get(step["id"])
    override = queue.pop(0) if queue else {}
    outcome = step_outcome(step, attempt, **override)
    declared = [o for o in step.get("outputs") or () if o.get("kind") == "judgment-attacks"]
    if declared and outcome["status"] == "completed" and "outputs" not in override and (context or {}).get("run_dir"):
        path = declared[0]["path"]
        raw = json.dumps(attack_document(step), sort_keys=True).encode()
        target = Path(context["run_dir"]) / "steps" / step["id"] / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        outcome["outputs"] = [o for o in outcome["outputs"] if o["path"] != path] + [
            {"artifact": f"{step['id']}:{path}", "path": path, "sha256": hashlib.sha256(raw).hexdigest()}]
    return outcome


def fake_step_graph(ctx):
    """The ``controller.step`` stand-in: one effect node calling ``step_run``, with the required nodes."""
    from langgraph.graph import END, START, StateGraph
    from ravel.workflow import graph_nodes as nodes

    class View(TypedDict, total=False):
        meta: dict
        step: dict
        context: dict

    class State(nodes.BaseState, total=False):
        step: dict
        context: dict

    builder = StateGraph(State, input_schema=View)
    add = lambda name, node: nodes.add(builder, name, node, graph_id="controller.step")  # noqa: E731

    def run(state):
        from ravel.controller.store import RunStore
        context = state.get("context") or {}
        store = RunStore(context["run_id"], root=context["store_root"]) if context.get("store_root") else None
        return {"results": {"step": step_run(store, state["step"], context)}}
    add("run", nodes.Node("effect", run))
    add("decision_turn", nodes.decision_turn("controller.step"))
    add("reconcile", nodes.reconcile_node())
    add("hold", nodes.hold("controller_step_hold"))
    builder.add_edge(START, "run")
    builder.add_edge("run", END)
    return builder


PLANS: list = []  # plans the fake judgment graph returns, in order (tests set them)


def fake_judgment_graph(ctx):
    """The ``judgment.plan`` stand-in: returns the next plan of ``PLANS`` (or a one-step plan)."""
    from langgraph.graph import END, START, StateGraph
    from ravel.workflow import graph_nodes as nodes

    class View(TypedDict, total=False):
        meta: dict
        request: dict
        plan: dict
        context: dict

    class State(nodes.BaseState, total=False):
        request: dict
        plan: dict
        context: dict

    builder = StateGraph(State, input_schema=View)
    add = lambda name, node: nodes.add(builder, name, node, graph_id="judgment.plan")  # noqa: E731

    def plan(state):
        found = deepcopy(PLANS.pop(0)) if PLANS else judgment_plan()
        return {"results": {"plan": found}}
    add("plan", nodes.Node("effect", plan))
    add("decision_turn", nodes.decision_turn("judgment.plan"))
    add("reconcile", nodes.reconcile_node())
    add("hold", nodes.hold("judgment_plan_hold"))
    builder.add_edge(START, "plan")
    builder.add_edge("plan", END)
    return builder


def judgment_plan(steps=None, deliverables=None, waypoints=(), revision=0):
    from ravel.controller.routes import plan_sha256
    steps = steps if steps is not None else [make_step("j1", kind="derive", outputs=["outputs/answer.json"])]
    plan = {"schema_version": 1, "kind": "controller-plan", "revision": revision,
            "route": {"id": "judgment", "version": 1, "spec_sha256": None}, "parameters": {},
            "steps": steps, "deliverables": deliverables if deliverables is not None else [],
            "waypoints": list(waypoints), "checkins": [], "obligations": [], "open_obligations": [],
            "instruction_sources": [], "reading_sha256": None, "contract_sha256": None}
    plan["sha256"] = plan_sha256(plan)
    return plan


def make_step(step_id, *, kind="operate", depends_on=(), outputs=(), waypoint=False, rung=None, **extra):
    step = {"id": step_id, "kind": kind, "inputs": [], "depends_on": list(depends_on),
            "outputs": [{"path": p, "kind": "artifact", "required": True} for p in outputs],
            "waypoint": waypoint, "rung": rung, "budget": {}, "protocols": [], "review": [],
            "instruction_sources": [], "obligations": []}
    step.update(extra)
    return step


def graph_rows():
    """Registry rows for the stand-in graphs (pinned on first build)."""
    from ravel.workflow import graph_registry
    base = {"kernel_version": 1, "scope": "run", "instance_keys": ["run_id"], "roles": [], "gates": {},
            "subgraphs": [], "interrupts": [], "structure_sha256": graph_registry.PIN, "owner": "controller-fakes"}
    # Match the installed dependency version while retaining this stand-in's separate structure pin.
    step_version = graph_registry.get("controller.step")["version"]
    # The builders are in-process (``registered(builders=...)``); the module names are never imported.
    return [{**base, "id": "controller.step", "version": step_version, "module": "ravel.controller.fakes_step",
             "builder": "fake_step_graph"},
            {**base, "id": "judgment.plan", "version": 1, "module": "ravel.controller.fakes_judgment",
             "builder": "fake_judgment_graph"}]


def reset():
    SCRIPT.clear()
    DISPATCHED.clear()
    PACKETS.clear()
    PLANS.clear()


@contextmanager
def stand_in_graphs():
    """Register the stand-in ``controller.step`` and ``judgment.plan`` graphs (replacing real ones)."""
    from ravel.workflow import graph_registry
    reset()
    with graph_registry.registered(*graph_rows(), builders={"controller.step": fake_step_graph,
                                                             "judgment.plan": fake_judgment_graph}, replace=True):
        yield
    reset()


def no_checkpoint_seat(monkeypatch):
    """The stand-ins run no exact-action RDJ seat for the CHECK-IN 2 GO (``authority.rdj.dispatch`` of a
    ``controller.checkin2_accept`` action); every other dispatch is the installed one.

    That seat binds a planning plan through the run's real obligation ledger and reads the authority's retained GO
    snapshot, while this harness installs a stand-in ledger and authority and substitutes the decision gates
    (``passing_gates``), which take no RDJ credit. The seat and the gate that requires it are exercised by
    test_checkin2_action (dispatch, ordering and the provider's refusals)."""
    from ravel.controller.authority import rdj
    installed = rdj.dispatch

    def dispatch(store, state, action, context, *args, **kwargs):
        if (action or {}).get("kind") == "controller.checkin2_accept":
            return None
        return installed(store, state, action, context, *args, **kwargs)
    monkeypatch.setattr(rdj, "dispatch", dispatch)


# ---- driving a controller run in a test ------------------------------------------------------

PROVIDERS = ("review_points", "rdj", "ceilings", "spawn_rows", "input_closure", "raw_launch")


def active_providers(gate):
    """``gate_providers`` seam: every provider the controller's gates require is active."""
    return {name: True for name in PROVIDERS}


def passing_gates(scope_root, gate_name, action):
    """``gate_check`` seam: the decision gate passes (the ledger and authority still decide)."""
    return []


def isolate(tmp_path, monkeypatch):
    """Legacy custody and the default controller store root under the test's temporary directory."""
    from ravel.controller import store
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "legacy-state"))
    root = tmp_path / "controller-store"
    monkeypatch.setattr(store, "default_store_root", lambda: root)
    return root


REQUEST = (b"Estimate the yield of a fictional widget process in a toy model and report the value "
           b"with its uncertainty.")


def drive_request(tmp_path, request=REQUEST, *, gate_check=passing_gates, unattended=False, rundir=None,
                  channel="terminal", supplied=(), **options):
    """Start a controller run for ``request`` and drive it with the stand-ins; ``(store, observation)``."""
    from ravel.controller import entry
    store = entry.start(request, channel=channel, rundir=rundir or tmp_path / "runs" / "r1",
                        root=tmp_path / "controller-store", unattended=unattended, supplied=supplied)
    observation = entry.drive(store, unattended=unattended, gate_check=gate_check,
                              gate_providers=active_providers, **options)
    return store, observation


def final_state(store):
    """The ``controller.run`` thread's last checkpoint values."""
    from ravel.workflow import graph_substrate
    _, _, snapshot = graph_substrate._pending(store.graph_scope(), "controller.run", {"run_id": store.run_id})
    return snapshot.values


@contextmanager
def installed(**services):
    """Install fakes as the controller's services (``ledger``, ``authority``, ``sink``, ``instructions``,
    ``judgment``, ``confine``) for a block; unnamed services get fresh fakes."""
    from ravel.controller import graph
    chosen = {"ledger": FakeLedger(), "authority": FakeAuthority(), "sink": FakeSink(),
              "instructions": FakeInstructions(), "judgment": FakeJudgment(), "confine": FakeConfine()}
    chosen.update(services)
    with graph.services(**chosen):
        yield chosen


# ---- route specs: one fictional spec per row of the start.md table ------------------------------

def _spec(route_id, row, when, steps, deliverables, *, admits=True, checkins=None):
    return {"schema_version": 1, "kind": "route-spec", "id": route_id, "version": 1,
            "title": f"fixture route for start.md row {row}", "match": {"row": row, "when": when},
            "admits_scientific_deliverables": admits, "parameters": [], "steps": steps,
            "checkins": checkins or [{"id": "checkin1", "sections": ["plan"], "seats": ["plan-critic"]}],
            "obligations": [f"ROUTE-{route_id}"], "deliverables": deliverables}


def _one_step(kind="operate", output="outputs/result.json"):
    return [make_step("s1", kind=kind, outputs=[output])]


ROW_FIXTURES = (
    # (row, route id, predicate)
    (1, "fixture-study", {"all": [{"field": "supplied_kinds", "nonempty": True},
                                  {"field": "requested_stages", "disjoint": ["generation", "shower", "detector"]}]}),
    (2, "fixture-manuscript", {"field": "operation_kind", "eq": "manuscript"}),
    (3, "fixture-chain", {"field": "operation_kind", "eq": "diagram"}),
    (5, "fixture-research", {"field": "task_mode", "in": ["research", "method_study", "anomaly_search"]}),
    (6, "fixture-analysis", {"field": "task_mode", "in": ["reproduce", "reinterpret", "scan", "projection", "survey",
                                                          "summary_plot", "no_routine"]}),
    (7, "fixture-calculation", {"field": "task_mode", "eq": "calculation"}),
    (8, "fixture-scoped", {"field": "task_mode", "in": ["generate", "likelihood"]}),
)


def route_specs():
    """Fictional specs for the start.md rows a route package owns (rows 4 and 9 are the controller's)."""
    specs = []
    for row, route_id, when in ROW_FIXTURES:
        specs.append(_spec(route_id, row, when, _one_step(), [{"match": {"any": True}, "step": "s1",
                                                              "output": "outputs/result.json"}]))
    return specs
