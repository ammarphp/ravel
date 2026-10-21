"""Fakes for the judgment package's collaborators, with the shapes those packages publish.

``Store`` keeps P01's record envelopes and blobs; ``Steps`` answers ``step.run`` the way P04's
governed step does (``status`` completed/held/failed/..., outputs adopted under
``steps/<step id>/<path>`` of the run directory, ``review`` credit); ``Authority`` answers like
P06 (``authority-record.v1`` with ``decision``/``option``, or ``{"pending": ...}``, taking a
subject's conservative default after the wait bound); ``Ledger`` keeps P02's instance keys
(``<row>@<run>[/step=...]``), pending entries by discharging node and its evidence rules.
Everything is fictional and in memory or under the test's temporary directory; nothing calls a
model, a provider, the network or a native tool. The tests at the end check these fakes against
the binding signatures.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from ravel.controller.judgment import records, services

RUN_ID = "run-judgment-fixture"
REQUEST = "Estimate how lowering a fictional detector threshold changes the expected sensitivity of a fictional search."


def digest(value):
    return records.digest(value)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ---- P01: the run store ------------------------------------------------------------------------

class Store:
    """In-memory run store with P01's envelopes ``{id, kind, seq, record, ...}`` and blobs."""

    def __init__(self, run_id, *, root, run_dir):
        self.run_id = run_id
        self.store_root = Path(root)
        self.root = self.store_root / run_id
        self._run_dir = Path(run_dir)
        self.entries = []
        self.blobs = {}

    @property
    def run_dir(self):
        return self._run_dir

    def append(self, kind, record):
        json.dumps(record, allow_nan=False)
        prev = self.entries[-1]["digest"] if self.entries else "0" * 64
        body = {"schema_version": 1, "seq": len(self.entries) + 1, "kind": kind, "time_ns": len(self.entries) + 1,
                "prev": prev, "record": deepcopy(record)}
        entry = {**body, "id": f"{kind}-{body['seq']:06d}-{digest(body)[:12]}"}
        entry["digest"] = digest(entry)
        self.entries.append(entry)
        return entry["id"]

    def read(self, kind, record_id):
        for entry in self.entries:
            if entry["id"] == record_id and entry["kind"] == kind:
                return deepcopy(entry)
        raise ValueError(f"no {kind} record {record_id}")

    def scan(self, kind):
        return [deepcopy(e) for e in self.entries if e["kind"] == kind]

    def latest(self, kind):
        rows = self.scan(kind)
        return rows[-1] if rows else None

    def put_blob(self, data):
        key = sha(data)
        self.blobs[key] = bytes(data)
        return key

    def get_blob(self, key):
        data = self.blobs[key]
        assert sha(data) == key
        return data

    def path(self, *parts):
        return self.root.joinpath(*parts)

    def records(self, kind):
        return [e["record"] for e in self.entries if e["kind"] == kind]


# ---- P04: the governed step ---------------------------------------------------------------------

def outcome(step, attempt=1, status="completed", outputs=(), review=None, reason=None, escalation=None, **extra):
    return {"step_id": step["id"], "attempt": attempt, "status": status, "outputs": list(outputs),
            "receipts": [f"receipt-{step['id']}-{attempt}"], "escalation": escalation, "replan": None,
            "budget": {"wall_seconds": 0}, "judgments": [], "review": review or {}, "reason": reason, **extra}


class Steps:
    """``step.run``: scripted worker documents written and adopted like the governed step adopts them.

    ``documents`` maps a step id (or a prefix ending in ``*``) to a callable
    ``(step, context, fixture) -> {declared path: JSON document}`` or to an outcome override.
    Reviews are credited and accept unless ``reviews`` scripts another verdict.
    """

    def __init__(self, fixture):
        self.fixture = fixture
        self.calls = []
        self.documents = {}
        self.statuses = {}
        self.reviews = {}

    def _match(self, table, step_id):
        if step_id in table:
            return table[step_id]
        for key, value in table.items():
            if key.endswith("*") and step_id.startswith(key[:-1]):
                return value
        return None

    def __call__(self, store, step, context):
        assert context["plan_sha256"], "the governed step needs a plan binding"
        bound = [store.get_blob(r["blob"]) for r in store.records("plan") if r["plan_sha256"] == context["plan_sha256"]]
        assert bound, "the step's plan record is in the store"
        plan = json.loads(bound[-1])
        assert any(row == step for row in plan["steps"]), f"step {step['id']} is bound to its plan with equal bytes"
        self.calls.append({"step": deepcopy(step), "context": deepcopy(context)})
        status = self._match(self.statuses, step["id"])
        if callable(status):
            status = status(step, context, self.fixture)
        if isinstance(status, dict):
            return status
        if status is not None and status != "completed":
            return outcome(step, context["attempt"], status=status, reason=f"scripted {status}")
        writer = self._match(self.documents, step["id"])
        produced = writer(step, context, self.fixture) if writer else {}
        outputs = []
        for path, document in produced.items():
            raw = (json.dumps(document, sort_keys=True) + "\n").encode()
            target = Path(context["run_dir"]) / "steps" / step["id"] / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            outputs.append({"artifact": f"{step['id']}:{path}", "path": path, "sha256": sha(raw)})
        review = None
        if step["kind"] in ("review", "subgraph"):
            verdict = self._match(self.reviews, step["id"]) or {"credited": True, "verdict": "accept"}
            review = dict(verdict)
        return outcome(step, context["attempt"], outputs=outputs, review=review)

    def ids(self):
        return [c["step"]["id"] for c in self.calls]


# ---- P06: authority -----------------------------------------------------------------------------

class Authority:
    """Authority records from a script; ``pending`` answers wait and take a conservative default."""

    def __init__(self, fixture, answers=None, *, wait_bound=0, r3_policy="escalate_and_wait"):
        self.fixture = fixture
        self.answers = {k: (list(v) if type(v) is list else [v]) for k, v in (answers or {}).items()}
        self.calls = []
        self.pending_since = {}
        self.wait_bound = wait_bound
        self.r3_policy = r3_policy
        self.stop = "running"
        self.contexts = {}

    def capture(self, store, kind, *, plan, reading, view):
        """P06's ``retained.capture``: the independent plan and reading the check-in view must equal."""
        if not isinstance(plan, dict) or not isinstance(reading, dict):
            raise ValueError("A retained decision needs independent plan and reading records.")
        if not {"request_pins", "inferred_critical_facts", "flags"} <= reading.keys():
            raise ValueError("Reading disclosures are incomplete.")
        if kind == "approve_plan" and (not plan.get("steps") or not plan.get("deliverables")):
            raise ValueError("The plan has no steps or deliverables.")
        if "plan_sha256" in view["pins"] and view["pins"]["plan_sha256"] != plan.get("sha256"):
            raise ValueError("The view does not bind its source plan.")
        expected = deepcopy(view)
        expected["items"] = {**deepcopy(reading.get("items", {})),
                             **{key: deepcopy(plan.get(key, [])) for key in ("steps", "deliverables", "boundaries")}}
        expected["flags"] = deepcopy(reading["flags"])
        snapshot = {"plan": deepcopy(plan), "reading": deepcopy(reading), "view": expected}
        snapshot["id"] = "context-" + digest(snapshot)
        self.contexts[kind] = snapshot
        return deepcopy(snapshot)

    def disposition(self, store, record_id, *, kind, subject=None):
        """P06's ``disposition``: the stored record when it is the current, attested decision of ``kind``
        on its retained snapshot with the current pins; non-authorizing decisions included."""
        identifier, body = services.unwrap(store.read("authority", record_id))
        record = {**body, "id": identifier or record_id}
        rows = [services.unwrap(row) for row in store.scan("authority")]
        current = next((identifier for identifier, row in reversed(rows) if row.get("kind") == kind), None)
        context = self.contexts.get(kind)
        if (record.get("kind") != kind or record_id != current or context is None
                or record.get("context_record") != context["id"] or self.stop != "running"
                or record.get("label") != "operator_configured_machine"):
            raise ValueError("No current authenticated decision.")
        pins = record.get("subject", {}).get("pins", {})
        if subject is not None and any(pins.get(key) != value for key, value in subject.items()):
            raise ValueError("Authority pins changed.")
        return record

    def verify(self, store, record_id, *, kind, subject=None):
        """P06's ``verify``: a current disposition that also authorizes effects (never a final)."""
        record = self.disposition(store, record_id, kind=kind, subject=subject)
        if record.get("authorizes_effects") is not True:
            raise ValueError("No current effect authorization.")
        return record

    def script(self, **answers):
        """Script the answers of each authority kind (a decision, a ``(decision, option)`` or a list)."""
        self.answers.update({k: (list(v) if type(v) is list else [v]) for k, v in answers.items()})

    def config(self):
        return {"mode": "autonomous", "budgets": {}, "r3_policy": self.r3_policy,
                "wait_bound_seconds": self.wait_bound, "notify_command": None, "store_root": None}

    def request(self, store, kind, subject, bounds):
        assert type(subject) is dict and type(subject.get("view")) is dict, "an authority request carries its view"
        assert subject["view"]["run_id"] == store.run_id and subject["view"]["pins"], "the view pins its run state"
        assert set(bounds) <= {"compute_plan", "stages", "budget", "policy"}
        context = self.contexts.get(kind)
        if context is None or context["view"] != subject.get("view"):
            return {"pending": {"reason": "No matching retained compiler and reading snapshot."}}
        self.calls.append((kind, deepcopy(subject)))
        queue = self.answers.get(kind)
        decision = queue.pop(0) if queue and len(queue) > 1 else (queue[0] if queue else "approve")
        key = digest({"kind": kind, "subject": subject})
        if decision == "pending":
            since = self.pending_since.setdefault(key, self.fixture.clock["now"])
            default = subject.get("conservative_default")
            waited = self.fixture.clock["now"] - since
            if default is not None and (self.r3_policy == "conservative_default" or waited >= self.wait_bound):
                return self._record(store, kind, subject, "default", option=default)
            return {"pending": {"request": "authority-request-" + key[:8], "kind": kind,
                                "reason": "a question only a human can answer", "needed": "an operator answer",
                                "since_ns": int(since * 1e9), "waited_seconds": waited,
                                "wait_bound_seconds": self.wait_bound,
                                "status_line": "WAITING FOR A HUMAN: fictional"}}
        option = None
        if type(decision) is tuple:
            decision, option = decision
        return self._record(store, kind, subject, decision, option=option)

    def _record(self, store, kind, subject, decision, option=None):
        record = {"schema": "authority-record.v1", "kind": kind, "decision": decision, "option": option,
                  "subject_sha256": digest(subject), "run_id": store.run_id,
                  "label": "operator_configured_machine", "source": "fake-operator"}
        positive = {"approve_plan": "approve", "go": "go", "deviation": "approve",
                    "r3_action": "approve", "escalation": "answer", "steering": "approve"}
        selected = next((row for row in subject["view"].get("options", []) if row["id"] == option), None)
        authorizing_decision = (decision == positive.get(kind)
                                or (decision == "default" and kind in ("r3_action", "escalation")))
        record["authorizes_effects"] = bool(kind != "final" and authorizing_decision
                                           and (option is None or selected is not None and selected.get("effect", True)))
        record["subject"] = {"pins": deepcopy(subject["view"]["pins"])}
        record["context_record"] = self.contexts[kind]["id"]
        record["id"] = store.append("authority", record)
        return record


# ---- P02: the obligation ledger ----------------------------------------------------------------

LEDGER_ROWS = {"JR01": "judgment.frame", "JR02": "judgment.frame", "R10": "judgment.frame",
               "ROUTE-unsupported": "judgment.frame", "JR03": "judgment.decompose", "JR06": "judgment.classify",
               "A05": "judgment.classify", "JR07": "judgment.replan", "JR08": "judgment.ask",
               "JR09": "judgment.kill_the_result", "E12": "judgment.recovery", "C08": "judgment.default",
               "GATE-failed_stage_feedback": "ledger.gate[failed_stage_feedback]"}
STEP_ROWS = {"JR04": "judgment.fanout", "JR05": "judgment.record", "E28": "judgment.protocol"}
R_ROWS = ("C01", "E03", "E12", "E28", "JR02", "JR09")


class Ledger:
    """P02-shaped ledger: instance keys, pending by node, evidence rules, scripted transition holds."""

    def __init__(self, unmet=None):
        self.unmet = dict(unmet or {})
        self.status = {}
        self.calls = []

    def key(self, row, step=None):
        return f"{row}@{RUN_ID}" + (f"/step={step}" if step else "")

    def materialise(self, store, stage, context):
        self.calls.append(("materialise", stage))
        return []

    def pending(self, store, node=None, step=None, **_):
        """Pending entries of ``node``; with ``step``, only that step's scoped entries (as the ledger filters)."""
        found = []
        rows = STEP_ROWS if step is not None else LEDGER_ROWS
        for row, row_node in rows.items():
            if node is not None and node != row_node:
                continue
            key = self.key(row, step)
            self.status.setdefault(key, "pending")
            if self.status[key] == "pending":
                found.append(key)
        return found

    def record(self, store, entry_id, status, evidence):
        row = entry_id.split("@", 1)[0]
        if status == "satisfied":
            assert any(evidence.get(k) for k in ("receipt", "artifact", "sha256", "validator", "credit", "authority",
                                                 "instruction_receipt", "ack", "mechanism", "covered_by", "gate",
                                                 "probe", "record")), "satisfied needs evidence"
            if row in R_ROWS and not evidence.get("credit"):
                raise ValueError(f"{entry_id}: a review-gated row is satisfied only by a credit id")
        if status == "violated":
            assert evidence.get("reason"), "violated needs a reason"
        if self.status.get(entry_id) == "violated":
            raise ValueError("violated is final")
        self.status[entry_id] = status
        self.calls.append(("record", entry_id, status))

    def gate(self, store, transition):
        self.calls.append(("gate", transition))
        return deepcopy(self.unmet.get(transition, []))

    def statuses(self, row):
        return {k: v for k, v in self.status.items() if k.split("@", 1)[0] == row}


class Sink:
    def __init__(self):
        self.calls = []

    def deliver(self, store, plan):
        self.calls.append(("deliver", plan["sha256"]))
        receipt = {"kind": "delivery", "qualified": False, "plan_sha256": plan["sha256"], "labels": []}
        receipt["id"] = store.append("receipt", receipt)
        return receipt

    def bounded_end(self, store, reason):
        self.calls.append(("bounded_end", reason))
        receipt = {"kind": "delivery", "qualified": True, "reason": reason, "labels": ["QUALIFIED ENDING"]}
        receipt["id"] = store.append("receipt", receipt)
        return receipt


# ---- fictional request records -------------------------------------------------------------------

def reading(deliverables=("D1",), boundaries=(), constraints=(), ambiguities=()):
    return {"schema_version": 1, "kind": "request-reading", "deliverables": [
        {"id": d, "obligation_ids": [f"deliverable-{d}"], "artifact": {"kind": "figure", "require": {}},
         "claim_kind": "prediction"} for d in deliverables],
        "facts": [], "constraints": list(constraints), "ambiguities": list(ambiguities),
        "boundaries": list(boundaries), "witness": [], "dismissed": []}


def contract(epoch=2, mode="unsupported"):
    return {"schema_version": 1, "prompt": REQUEST, "task_mode": mode, "agent_layer_epoch": epoch}


def frame(request_sha, *, deliverables=None, boundaries=(), unknowns=(), assumptions=None, constraints=()):
    return {"schema_version": 1, "kind": "question-frame", "request_sha256": request_sha,
            "objective": "Estimate the change in expected sensitivity as the threshold is lowered.",
            "deliverables": deliverables if deliverables is not None else [
                {"id": "D1", "reading_ref": "D1", "description": "Sensitivity versus threshold figure.",
                 "acceptance": "A curve over the requested threshold range with stated uncertainty.",
                 "statistic": "expected sensitivity", "units": "events"}],
            "constraints": list(constraints), "unknowns": list(unknowns),
            "assumptions": assumptions if assumptions is not None else [
                {"number": 1, "statement": "The fictional detector response is linear in the threshold.",
                 "basis": "a stated simplification for this fixture", "physics_critical": False}],
            "boundaries": list(boundaries)}


def step(step_id, kind="derive", *, outputs=None, depends_on=(), triggers=(), protocols=(), **extra):
    row = {"id": step_id, "kind": kind, "purpose": f"Fictional {kind} step {step_id}.",
           "inputs": [{"artifact": "reading"}], "outputs": outputs or [{"path": f"outputs/{step_id}.json",
                                                                       "kind": "result", "required": True}],
           "depends_on": list(depends_on), "budget_share": {"fraction": 0.1}, "protocols": list(protocols),
           "review": [], "obligations": ["D1"]}
    if triggers:
        row["triggers"] = list(triggers)
    row.update(extra)
    return row


def plan(frame_doc, steps_, deliverables=None):
    return {"schema_version": 1, "kind": "judgment-plan", "frame_sha256": digest(frame_doc), "steps": steps_,
            "deliverables": deliverables if deliverables is not None else [
                {"id": "D1", "status": "planned", "outputs": [{"step": steps_[-1]["id"],
                                                               "path": steps_[-1]["outputs"][0]["path"]}]}]}


def p7(physics_critical=False):
    return {"assumption": "The fictional background stays flat below the threshold.",
            "default": "Keep the flat background.", "alternatives": ["a falling background"],
            "claim_type": "other", "direction_established": False, "expected_sign": "unknown",
            "expected_size": "a few percent", "reversible_knob": "background_shape", "physics_critical": physics_critical,
            "flag": {"checkin_flag": 1, "deviation": "flat background default"},
            "justification": {"kind": "request_span", "reference": "lowering a fictional detector threshold"}
            if physics_critical else None}


def record(step_id, *, kind="plot_style", options=2, triggers=(), evidence=None, declared=None, default=None,
           default_option=None, reversibility="reversible"):
    rows = [{"id": "a", "description": "linear axes", "predicted_consequences": "readable"},
            {"id": "b", "description": "logarithmic axes", "predicted_consequences": "shows the tail"}][:options]
    body = {"schema_version": 1, "kind": "judgment-record", "id": f"jr-{step_id}", "step": step_id,
            "question": "Which presentation serves the deliverable?", "options": rows, "chosen": "a",
            "rationale": "The values stay within one decade.", "action": {"summary": "a fictional choice", "kind": kind},
            "triggers": list(triggers), "protocol_evidence": evidence or {},
            "reversibility": {"kind": reversibility, "note": "a reversible knob"}, "budget_impact": {"note": "none"}}
    if options == 1:
        body["single_option_reason"] = "only one presentation fits the requested figure"
    if declared:
        body["declared_class"] = declared
    if default is not None:
        body["default"] = default
        body["default_option"] = default_option
    return body


# ---- the fixture -----------------------------------------------------------------------------

class Fixture:
    """One fictional run: store, request records in blobs, collaborators, clock and the graph view."""

    def __init__(self, tmp_path, *, reading_doc=None, contract_doc=None, purpose="plan"):
        self.tmp = Path(tmp_path)
        self.run_dir = self.tmp / "run"
        self.run_dir.mkdir()
        self.store = Store(RUN_ID, root=self.tmp / "store", run_dir=self.run_dir)
        self.request_text = REQUEST
        self.reading = reading_doc if reading_doc is not None else reading()
        self.contract = contract_doc if contract_doc is not None else contract()
        self.pins = {"sha256": self.store.put_blob(REQUEST.encode()), "channel": "terminal",
                     "reading_sha256": self.store.put_blob(json.dumps(self.reading).encode()),
                     "contract_sha256": self.store.put_blob(json.dumps(self.contract).encode())}
        self.clock = {"now": 1000.0}
        self.steps = Steps(self)
        self.authority = Authority(self)
        self.ledger = Ledger()
        self.sink = Sink()
        self.catalogue = {"operations": [{"mode": "literal-calculation", "status": "source_present_not_admitted",
                                          "descriptor": None}], "planning_tools": [], "declared_chains": [],
                          "scope": "fictional"}
        self.routes = set()
        self.purpose = purpose
        self.mode = {"mode": "autonomous", "bounds": {}}

    def frame_doc(self, **kw):
        return frame(self.pins["sha256"], **kw)

    def view(self, *, purpose=None, revision=0, plan=None, **context):
        return {"request": dict(self.pins), "plan": plan,
                "context": {"run_id": RUN_ID, "run_dir": str(self.run_dir), "store_root": str(self.store.store_root),
                            "mode": deepcopy(self.mode), "unattended": True, "purpose": purpose or self.purpose,
                            "revision": revision, "route": {"id": "judgment"}, **context}}

    def sleep(self, seconds):
        self.clock["now"] += seconds

    @contextmanager
    def installed(self):
        services.enable_local_seams()
        with services.overridden(
                open_store=lambda run: self.store, step_run=self.steps,
                ledger_materialise=self.ledger.materialise, ledger_record=self.ledger.record,
                ledger_gate=self.ledger.gate, ledger_pending=self.ledger.pending,
                plan_bind=lambda store, plan, **options: {"recorded": 0},
                authority_request=self.authority.request, authority_capture=self.authority.capture,
                authority_verify=self.authority.verify, authority_disposition=self.authority.disposition,
                stop_state=lambda store: self.authority.stop,
                operator_config=self.authority.config, sink_deliver=self.sink.deliver,
                sink_bounded_end=self.sink.bounded_end, catalogue=lambda: self.catalogue,
                route_specs=lambda: set(self.routes),
                roles=lambda: {"coordinator", "plan-critic", "physics-critic", "skeptical-verifier", "physics-decider",
                               "rdj-critic", "generator", "analysis-author", "calculation", "discrepancy-attributor"},
                recovery_hints=lambda prompt, contract, reading: {"status": "fictional", "suggested_steps": []},
                now=lambda: self.clock["now"], sleep=self.sleep):
            yield self

    def events(self, name=None):
        rows = self.store.records("judgment-event")
        return [r for r in rows if name is None or r["event"] == name]


def registered_row():
    path = Path(__file__).resolve().parents[3] / "src/ravel/data/graphs/registration/judgment.plan.json"
    return json.loads(path.read_text())["graphs"][0]


@contextmanager
def judgment_graph():
    """The ``judgment.plan`` row from its registration fragment (unless the loader already has it)."""
    from ravel.workflow import graph_registry
    try:
        graph_registry.get("judgment.plan")
        yield
        return
    except graph_registry.RegistryError:
        pass
    with graph_registry.registered(registered_row()):
        yield


@contextmanager
def passing_decision_gate(monkeypatch, *, errors=()):
    """The decision gate's providers all active and its check returning ``errors`` (default none)."""
    from ravel.workflow import decision_gate
    rows = [{"id": name, "module": "fictional", "function": "gate_errors", "gates": ["*"], "active": True,
             "reason": None, "missing_function": False}
            for name in ("review_points", "rdj", "ceilings", "raw_launch", "input_closure")]
    monkeypatch.setattr(decision_gate, "check", lambda rundir, gate, action: list(errors))
    monkeypatch.setattr(decision_gate, "providers", lambda gate: deepcopy(rows))
    yield


def invoke(fixture, view, *, scope=None):
    """Invoke ``judgment.plan`` the way the controller graph does: a child invocation, no checkpointer."""
    from ravel.workflow import gate_wiring, graph_nodes, graph_registry, graph_substrate
    scope = Path(scope or fixture.tmp / "scope")
    scope.mkdir(parents=True, exist_ok=True)
    gate_wiring.initialize_steering(scope, route="graph-scope")
    row = graph_registry.get("judgment.plan")
    ctx = graph_substrate.BuildContext(scope_root=scope, graph_id="judgment.plan", version=row["version"],
                                       instance={"run_id": RUN_ID}, row=row)
    compiled = graph_substrate.build("judgment.plan", ctx, checkpointer=None)
    meta = {"graph_id": "judgment.plan", "version": row["version"], "instance": {"run_id": RUN_ID},
            "scope_root": str(scope), "path": None}
    found = graph_nodes._invoke_child(compiled, {**view, "meta": meta}, "child")
    return found["results"]["child"]


@pytest.fixture
def judged(tmp_path, monkeypatch):
    fixture = Fixture(tmp_path)
    with ExitStack() as stack:
        stack.enter_context(judgment_graph())
        stack.enter_context(passing_decision_gate(monkeypatch))
        stack.enter_context(fixture.installed())
        yield fixture


# ---- the fakes keep the binding signatures --------------------------------------------------------

BINDING = {"append": ["kind", "record"], "read": ["kind", "record_id"], "scan": ["kind"]}


def test_fake_store_keeps_the_binding_signatures():
    for name, parameters in BINDING.items():
        assert list(inspect.signature(getattr(Store, name)).parameters)[1:] == parameters
    assert list(inspect.signature(Steps.__call__).parameters)[1:] == ["store", "step", "context"]
    assert list(inspect.signature(Authority.request).parameters)[1:] == ["store", "kind", "subject", "bounds"]
    assert list(inspect.signature(Ledger.record).parameters)[1:] == ["store", "entry_id", "status", "evidence"]
    assert list(inspect.signature(Ledger.gate).parameters)[1:] == ["store", "transition"]
    assert list(inspect.signature(Sink.bounded_end).parameters)[1:] == ["store", "reason"]


def test_store_envelopes_unwrap_to_their_records(tmp_path):
    store = Store(RUN_ID, root=tmp_path / "s", run_dir=tmp_path / "r")
    identifier = store.append("kind-a", {"value": 1})
    assert services.records(store, "kind-a") == [(identifier, {"value": 1})]
    assert services.record(store, "kind-a", identifier) == {"value": 1}
    assert services.unwrap({"value": 2}) == (None, {"value": 2})
