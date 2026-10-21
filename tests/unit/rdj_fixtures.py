"""Synthetic runs, real execution receipts and receipted role calls for the decision-justification tests.

Every role call goes through the dispatcher protocol of ``rdj_loop.run_roles``: the fixture writes a worker
receipt in the decision-receipt shape and registers it in the RAVEL custody store, as the worker dispatcher
does. The loop never sees the responder's text as identity; it reads the registered receipt.
"""
import hashlib
import json
import sys
from pathlib import Path

from ravel.workflow import execution, rdj_custody
from ravel.workflow import rdj_loop as rdj

PROMPT = "Set a limit on the synthetic signal model and keep the approved binning."
TOOL = [sys.executable, "-m", "ravel.physics.pyhf_exclude"]  # a RAVEL tool module; the fixture never runs it
VALIDATOR = [sys.executable, "-m", "ravel.validation.certify_acceptance"]
COST = {"mode": "scan", "points": 3, "walltime_h": [0.1, 0.2]}


def sha(raw):
    return hashlib.sha256(raw if isinstance(raw, bytes) else raw.encode()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class Run:
    """A synthetic run: task contract, cost record, custody records at run init, and an action file."""

    def __init__(self, root, *, cost=COST, snapshot=True, prompt=True, extra_inputs=(), run_id=None):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        contract = {"prompt": PROMPT, "task_requirements": {"prompt_sha256": sha(PROMPT)}, "agent_layer_epoch": 2}
        contract["request_plan"] = self.put("inputs/request_plan.json", {"nodes": [], "claims": [], "edges": []})
        self.put("inputs/task_contract.json", {**contract, **({"run_id": run_id} if run_id else {})})
        if run_id:
            rdj_custody.bind_run(root, run_id)  # RAVEL binds the run identity at initialization
        self.put("inputs/cards/settings.json", {"bins": 4, "threshold": 2.5})
        for rel, data in extra_inputs:
            self.put(rel, data)
        if cost is not None:
            self.put("inputs/cost_preflight.json", {"schema_version": 2, "generated_by": "cost_preflight.py", **cost})
        if prompt:
            rdj_custody.record_user_text(root, "prompt", "inputs/task_contract.json")
        if snapshot:
            rdj_custody.record_input_snapshot(root, "run_init")
        self.action_pin = self.put("outputs/plan.json", {"points": 3})

    def put(self, rel, data):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = data if isinstance(data, bytes) else data.encode() if isinstance(data, str) else json.dumps(data).encode()
        path.write_bytes(raw)
        return {"path": rel, "sha256": sha(raw)}

    def pin(self, rel):
        return {"path": rel, "sha256": sha((self.root / rel).read_bytes())}

    def stage(self, name, rel, data, command=None, *, kind="tool_output", locator="", inputs=(), register=True,
              cwd=None, **binding):
        """A real succeeded execution receipt for one output file; the command is never run. ``register``
        records the receipt in custody as the stage supervisor does after a supervised finish."""
        command = list(command or (VALIDATOR if kind == "measurement" else TOOL))
        inputs = list(inputs)
        spec = {"command": command, "cwd": str(cwd or self.root), "inputs": inputs, "outputs": [rel], "parents": {},
                "input_snapshot": execution.snapshot(self.root, inputs), "runtime": execution.runtime_context()}
        spec["fingerprint"] = execution.digest(spec)
        record = execution.begin_attempt(self.root, name, spec, f"logs/{name}.log")
        pin = self.put(rel, data)
        (self.root / f"logs/{name}.log").write_text("fixture\n")
        assert execution.finish_attempt(self.root, record, 0) == 0
        registrar = getattr(rdj_custody, "register_stage_receipt", None)
        if register and registrar is not None:
            registrar(self.root, name, record["attempt_id"])
        anchor = {"kind": kind, "binding": {"receipt_id": f"stage:{name}:{record['attempt_id']}", "output_path": rel,
                                            "sha256": pin["sha256"], **binding}, "locator": locator}
        if kind == "measurement":
            anchor["binding"].setdefault("validator_id", "certify_acceptance")
            anchor["binding"].setdefault("validator_sha256", sha(Path(execution.__file__).parents[1].joinpath(
                "validation/certify_acceptance.py").read_bytes()))
        return anchor

    def action(self, kind="bulk_launch", summary="Launch the synthetic scan", **extra):
        return {"kind": kind, "digest": self.action_pin["sha256"], "summary": summary, "pins": [self.action_pin],
                **extra}

    def prompt_span(self, text):
        start = PROMPT.index(text)
        return {"kind": "user_requirement", "binding": {"source": "prompt", "sha256": sha(PROMPT), "start": start,
                                                        "end": start + len(text), "text": text}}

    def steering(self, text):
        """User steering recorded through RAVEL's user-message path."""
        return rdj_custody.record_user_steering(self.root, text)

    def approve(self, case_id, text=None, *, confirmed=True):
        """A human approval recorded through the CHECK-IN response path, naming the case.

        ``confirmed`` records the operator's confirmation at the controller terminal (the
        inert ``operator_capture`` stand-in), which is what lets the approval be recorded;
        without it ``record_human_approval`` refuses and records nothing."""
        from ravel.workflow import approval_capture
        from operator_capture import confirm
        text = text or f"I approve {case_id}."
        pin = self.steering(text)
        start = text.index(case_id)
        digest = rdj_custody._commit_line(self.root, case_id)["record"]["data"]["digest"]
        attestation = (confirm("case_approval", approval_capture.case_binding(self.root, case_id, digest, pin["sha256"]))
                       if confirmed else None)
        return rdj_custody.record_human_approval(self.root, case_id=case_id, source="user_steering",
                                                 path=pin["path"], start=start, end=start + len(case_id),
                                                 text=case_id, attestation=attestation)

    def reopen(self, digest, text=None):
        """A user decision, recorded through the steering path, that reopens one action."""
        text = text or f"Reopen action {digest[:12]} for one more attempt."
        pin = self.steering(text)
        start = text.index(digest[:12])
        return rdj_custody.record_reopen(self.root, action_digest=digest, source="user_steering", path=pin["path"],
                                         start=start, end=start + 12, text=digest[:12])

    def case(self, case_id):
        return json.loads((self.root / f"rdj/cases/{case_id}.json").read_text())

    def check_result(self, check_id, *, status="failed", producer="ravel.validation.numerical_witness", pins=None,
                     rel=None, register=True):
        """A check result written by a recognized check and registered in custody, as the check runner does.
        ``pins`` default to the run's settings card; the result names them so a later edit makes it stale."""
        pins = [self.pin("inputs/cards/settings.json")] if pins is None else pins
        rel = rel or f"checks/{check_id}.json"
        self.put(rel, {"schema_version": 1, "kind": rdj_custody.CHECK_RESULT_KIND, "check_id": check_id,
                       "producer": producer, "status": status, "pins": pins})
        if register:
            rdj_custody.register_check_result(self.root, rel)
        return "check:" + check_id


def record_decision(run, kind, *, case_id=None, digest=None, finding_id=None, text=None):
    """A user decision recorded through the steering path: ``approve`` a case, ``reopen`` an action or
    ``withdraw`` one finding of a case."""
    if kind == "approve":
        return run.approve(case_id, text)
    if kind == "reopen":
        return run.reopen(digest, text)
    if kind == "withdraw":
        text = text or f"Withdraw finding {finding_id} of {case_id}."
        pin = run.steering(text)
        start = text.index(finding_id)
        return rdj_custody.record_withdrawal(run.root, case_id=case_id, finding_id=finding_id, source="user_steering",
                                             path=pin["path"], start=start, end=start + len(finding_id),
                                             text=finding_id)
    raise ValueError(f"unknown decision {kind}")


# The proposer's session, as a role call named "proposer" would present it: one session never both proposes and reviews.
PROPOSER = {"actor_id": "proposer", "session_receipt": "fixture-transport:proposer-session",
            "attestation": "self_attested"}


def node(identity, assertion, anchors=(), **extra):
    return {"id": identity, "assertion": assertion, "rationale": "public rationale for " + identity,
            "anchors": list(anchors), **extra}


EXECUTION_MODE = {"transport_attested": "transport_attested_cli", "host_attested": "host_attested_external",
                  "self_attested": "relay_schema_2"}


def said(output, actor, *, session=None, attestation="transport_attested", family="family-a", **extra):
    return {"output": output, "actor": actor, "session": session or f"{actor}-session", "attestation": attestation,
            "family": family, **extra}


def assigned(name, node_id, family="family-a"):
    """The actor the worker dispatcher assigns to the role call ``name`` makes at ``node_id``:
    sha256 over transport, model, worker session and attempt. A responder never states one."""
    return rdj_custody.actor_record("fixture-transport", "m", "worker-session-" + name, node_id + "/1", family=family)


def reviewer(overrides=None, name="edge-reviewer", log=None, **extra):
    overrides = overrides or {}

    def respond(payload):
        if log is not None:
            log.append(sorted(e["edge_id"] for e in payload["edges"]))
        rows = []
        for edge in payload["edges"]:
            row = {"edge_id": edge["edge_id"], "entailment": "holds", "relevance": "relevant",
                   "grounding": "anchored", "code": "no_issue", "reason": "the hop holds", "request": None}
            row.update(overrides.get(edge["edge_id"], {}))
            rows.append(row)
        return said({"reviews": rows}, name, **extra)
    return respond


def critic(findings=(), name="critic", **extra):
    return lambda payload: said({"findings": list(findings)}, name, **extra)


def critic_once(findings=(), name="critic", **extra):
    """A critic that raises its findings on the first run and finds nothing new on re-runs."""
    calls = []

    def respond(payload):
        calls.append(payload)
        return said({"findings": list(findings) if len(calls) == 1 else []}, name, **extra)
    return respond


def verifier(outcome="authorize", name="verifier", resolved="yes", **extra):
    def respond(payload):
        return said({"per_finding": [{"finding_id": f["id"], "resolved": resolved, "reason": "checked"}
                                     for f in payload["findings"]], "outcome": outcome}, name, **extra)
    return respond


class Roles:
    """Receipted role calls through the worker-receipt contract."""

    def __init__(self, register=True, verified=True, **responders):
        responders.setdefault("edge_reviewer", reviewer())
        responders.setdefault("critic", critic())
        responders.setdefault("verifier", verifier())
        self.responders = responders
        self.register = register
        self.verified = verified
        self.calls = []

    def dispatch(self, rundir, request):
        role = request["role"]
        self.calls.append((role, request["payload"]))
        said_ = self.responders[role](request["payload"])
        node_id = f"rdj-{request['case_id']}-{request['slot']}"
        workspace = Path(rundir) / "agent-work" / node_id / "1"
        workspace.mkdir(parents=True, exist_ok=True)
        final = canonical(said_["output"])
        (workspace / "final.json").write_bytes(final)
        # The dispatcher's part: it assigns the actor of this worker session and registers it below.
        actor = assigned(said_["actor"], node_id, said_["family"])
        receipt = {"schema_version": 1, "kind": "agent-worker-receipt", "node_id": node_id, "attempt": 1,
                   "role": {"id": request["agent_role"], "version": "1.0.0", "card_sha256": "0" * 64},
                   "review_point_id": None,
                   "transport": {"id": "fixture-transport", "transport_kind": "http-adapter",
                                 "declaration_sha256": "0" * 64, "probe_sha256": "0" * 64},
                   "model": {"requested": "m", "observed": "m", "family": said_["family"], "effort": "low"},
                   "session_id": said_["session"], "actor_id": actor["actor_id"], "attestation": said_["attestation"],
                   "execution_mode": said_.get("mode") or EXECUTION_MODE[said_["attestation"]],
                   "request_sha256": request["payload_sha256"],
                   "rdj": {"case_id": request["case_id"], "slot": request["slot"],
                           "payload_sha256": request["payload_sha256"]},
                   "final_record": {"path": "final.json", "sha256": sha(final), "schema": "rdj-role-output",
                                    "valid": True},
                   "status": "ok", "failure": None,
                   "usage": {"input_tokens": 10, "output_tokens": 10, "cost_usd": None, "reported": True}}
        path = workspace / "receipt.json"
        path.write_text(json.dumps(receipt, sort_keys=True))
        rel = path.relative_to(rundir).as_posix()
        if self.register:  # The dispatcher records the label its transport re-verification established.
            label = said_.get("verified_label", said_["attestation"]) if self.verified else None
            rdj_custody.register_worker_receipt(rundir, rel, verified_label=label, actor=actor)
        return {"kind": "worker_receipt", "path": rel}


def challenge(run, case_id, kind, target):
    rows = [c for c in rdj.next_challenges(run.root, case_id) if c["kind"] == kind and c["target"] == target]
    assert rows, (kind, target, rdj.next_challenges(run.root, case_id))
    return rows[0]["id"]


def add(run, case_id, parent, *specs, kind="why_believe", **op):
    """Answer one challenge on ``parent`` with one or more children."""
    cid = challenge(run, case_id, "why_action" if parent == "action" and kind == "why_believe" else kind, parent)
    return rdj.answer(run.root, case_id, [{"op": "add_child", "challenge_id": cid, "parent": parent, "node": spec, **op}
                                          for spec in specs])


def two_level_r2(run, *, leaf_anchor=None, gate="launch", kind="bulk_launch", tuning=None, roles=None, **opts):
    """action -> A -> B (B anchored), plus one alternative; returns the case id."""
    case_id = rdj.open_case(run.root, gate, run.action(kind), PROPOSER, tuning=tuning, **opts)
    add(run, case_id, "action", node("A", "The smoke receipts show the chain is functional"))
    rdj.run_roles(run.root, case_id, roles or Roles())
    anchor = leaf_anchor or run.stage("smoke", "outputs/smoke.json", {"events": 100})
    add(run, case_id, "A", node("B", "The smoke stage completed with output", anchors=[anchor]))
    add(run, case_id, "action", node("alt", "Launch a single point first", kind="alternative"),
        kind="why_over_alternative")
    return case_id


def escalate(run, gate="launch", kind="bulk_launch"):
    """An escalate receipt for ``run.action(kind)`` at ``gate``: a case left with a blocking edge verdict is
    escalated when the next case of the same action opens. Returns (escalated case id, action digest)."""
    failing = reviewer({"action->A": {"entailment": "fails", "code": "decision_does_not_follow",
                                      "reason": "the stated readiness does not entail the action"}})
    case_id = rdj.open_case(run.root, gate, run.action(kind), PROPOSER)
    add(run, case_id, "action", node("A", "The chain is ready"))
    rdj.run_roles(run.root, case_id, Roles(edge_reviewer=failing))
    try:
        rdj.open_case(run.root, gate, run.action(kind), PROPOSER)
    except ValueError as exc:
        assert "escalat" in str(exc), exc
    else:
        raise AssertionError("the abandoned case was not escalated")
    outcomes = [r["record"]["outcome"] for r in rdj_custody.rows(run.root, "receipts") if r["record"]["case_id"] == case_id]
    assert outcomes == ["escalate"], outcomes
    return case_id, run.action_pin["sha256"]


def prepare_case(run, gate, kind="bulk_launch", cls=None, *, tuning=None, action=None, roles=None):
    """Open and review a case through ``rdj_loop`` until only code's decision remains: a chain down to the
    class's minimum depth whose leaf is a registered tool output and a span of the user's request (the
    authoritative practice an analysis choice needs), plus one alternative. ``cls`` is declared
    (it only raises the computed class). Returns the case id; ``rdj.authorize`` decides it."""
    roles = roles or Roles()
    action = action or run.action(kind)
    record = None
    if tuning is not None:
        record = {"class": tuning, "parameter": "synthetic.parameter", "from": 1.0, "to": 1.1,
                  "reason": "The approved plan separates the calibration sample from the measured sample"}
    case_id = rdj.open_case(run.root, gate, action, PROPOSER, tuning=record,
                            declared={"class": cls} if cls else None)
    depth = max(2, anchor_check_depth(run.case(case_id)["risk"]["class"]))
    parent = "action"
    for level in range(1, depth + 1):
        name = f"L{level}"
        anchors = [run.stage(f"evidence-{case_id[-8:]}", f"outputs/evidence-{case_id[-8:]}.json",
                             {"converged": True}),
                   run.prompt_span("keep the approved binning")] if level == depth else []
        add(run, case_id, parent, node(name, f"Step {level} of the synthetic justification holds", anchors=anchors))
        rdj.run_roles(run.root, case_id, roles)
        parent = name
    add(run, case_id, "action", node("alt", "Do nothing for now", kind="alternative"), kind="why_over_alternative")
    rdj.run_roles(run.root, case_id, roles)
    return case_id


def anchor_check_depth(cls):
    from ravel.workflow import rdj_anchor
    return rdj_anchor.policy()["classes"][cls]["min_depth"]


def authorize_tuning_case(run, cls="R2", tuning="calibration", *, gate="deviation", action=None, approve=False):
    """Open, review and authorize a real ``tuning_change`` case of class ``cls`` through ``rdj_loop`` with the
    fixture roles. Returns the authorize receipt."""
    case_id = prepare_case(run, gate, "tuning_change", cls, tuning=tuning, action=action)
    if approve:
        run.approve(case_id)
    receipt = rdj.authorize(run.root, case_id)
    assert receipt["outcome"] == "authorize", receipt
    return receipt
