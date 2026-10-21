"""P01 ``controller.run``: its registered structure and its behaviour with the interface fakes.

Structure: the registered digest, every interrupt followed by its gate, no path from intake to
execution that avoids the CHECK-IN 1 gate (A01; only the prepare phase runs before it), and
``bounded_end`` reachable from every node.
Behaviour (stand-in step and judgment graphs, fake ledger, authority and sink with the real
services' contracts): the positive path, refusals that dispatch nothing (R01, A01), revision,
the prepare phase, waypoint, escalation, replan, stop, budget, holds, the ledger's transitions and
decisions, route adapters, each ending in a delivery or a qualified ending.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from importlib.util import module_from_spec, spec_from_file_location
import inspect
import json
from pathlib import Path
import re
import sys
import time
import types

import pytest

import fakes
from ravel.controller import graph, judgment as _judgment, routes
from ravel.workflow import graph_registry, graph_nodes, graph_substrate as gs


class _FakeAuthority(fakes.FakeAuthority):
    """The authority interface fake with the authenticated disposition reader its binding interface gained:
    ``disposition`` returns a current decision of the kind for the current pins without granting anything (the
    final gate reads the final record only through it). Its records say they carry no review credit and no human
    identity. The shared fake gains the same (fragment ``B-A-C2/fakes-disposition.patch``)."""
    LABELS = ("operator_configured_machine", "delegated_machine", "operator_command")

    def _append(self, store, body):
        return super()._append(store, {**body, "review_credit": False, "human_identity_authenticated": False})

    def disposition(self, store, record_id, *, kind, subject=None):
        for entry in store.scan("authority"):
            body = entry["record"]
            if record_id in (body.get("uid"), entry["id"]):
                break
        else:
            raise ValueError(f"{kind} authority {record_id!r} is not in the controller store")
        if body.get("kind") != kind:
            raise ValueError(f"record {record_id} is {body.get('kind')} authority, not {kind}")
        if body.get("label") not in self.LABELS:
            raise ValueError(f"the {body.get('label')} label authorizes nothing")
        for name, value in (subject or {}).items():
            if body["subject"]["pins"].get(name) != value:
                raise ValueError(f"{kind} authority {record_id} is stale: pin {name} changed")
        return {**body, "id": body["uid"]}


class _FakeJudgment(fakes.FakeJudgment):
    """The judgment interface fake with the installed judgment package's own policy helpers: ``bounds`` (the frozen
    mode's replan and review bounds) and ``check_attacks`` (the three P8 attacks, JR09). The shared fake gains the
    same (fragment ``B-B-C2/fakes-attacks.patch``)."""

    @staticmethod
    def bounds(mode):
        return _judgment.bounds(mode)

    @staticmethod
    def check_attacks(document, *, plan_sha256, draft_sha256):
        return _judgment.check_attacks(document, plan_sha256=plan_sha256, draft_sha256=draft_sha256)


AXES = ("basis", "acceptance", "statistics")
ATTACK_WRITERS: dict = {}  # attempt -> function(step) -> the document the attack seat writes, or None (tests set them)


def _attack_document(step, *, axes=AXES, subject=None):
    """A ``judgment-attacks.v1`` document on the plan and drafted result the attack seat's step names."""
    parameters = step.get("parameters") or {}
    return {"schema_version": 1, "kind": "judgment-attacks",
            "subject": subject or {"plan_sha256": parameters.get("subject_plan_sha256"),
                                   "draft_sha256": parameters.get("subject_sha256")},
            "attacks": [{"axis": axis, "attack": f"the fictional {axis} could be wrong",
                         "test": f"a fictional {axis} test", "outcome": "survives",
                         "evidence": ["a located fictional observation"]} for axis in axes]}


def _writing_attacks(real):
    """The stand-in step graph's P8 attack seat writes its declared ``judgment-attacks`` output where the governed
    step adopts it (``steps/<step>/<path>`` of the run directory) and reports its digest; a test may make it write
    another document, or none (``ATTACK_WRITERS``)."""
    def step_run(store, step, context):
        outcome = real(store, step, context)
        declared = [o for o in step.get("outputs") or () if o.get("kind") == "judgment-attacks"]
        if not declared or outcome.get("status") != "completed":
            return outcome
        path = declared[0]["path"]
        document = ATTACK_WRITERS.get(outcome["attempt"], _attack_document)(step)
        outcome["outputs"] = [o for o in outcome["outputs"] if o["path"] != path]
        if document is not None:
            raw = json.dumps(document, sort_keys=True).encode()
            target = Path(context["run_dir"]) / "steps" / step["id"] / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            outcome["outputs"].append({"artifact": f"{step['id']}:{path}", "path": path,
                                       "sha256": hashlib.sha256(raw).hexdigest()})
        return outcome
    return step_run


@pytest.fixture
def controller(tmp_path, monkeypatch):
    fakes.isolate(tmp_path, monkeypatch)
    from ravel.workflow import agent_tripwire
    monkeypatch.setattr(agent_tripwire, "_DECLARED", [])  # a controller declaration lasts for its process
    monkeypatch.setattr(fakes, "FakeAuthority", _FakeAuthority)  # ``fakes.installed()`` builds this one
    monkeypatch.setattr(fakes, "FakeJudgment", _FakeJudgment)  # and this one
    monkeypatch.setattr(fakes, "step_run", _writing_attacks(fakes.step_run))
    ATTACK_WRITERS.clear()
    # This unit harness substitutes the governed step graph and decision gates;
    # it issues no RDJ credit. The real final seat is covered by test_composition_wave_a.
    from ravel.controller import authority
    monkeypatch.setattr(authority, "review_final_task", lambda *args: None)
    monkeypatch.setattr(authority, "review_deviation", lambda *args: None)  # the same RDJ seat seam
    fakes.no_checkpoint_seat(monkeypatch)  # nor the CHECK-IN 2 GO's
    # This interface harness has no observed assumption-audit worker; real delivery
    # staffing and its refusals are exercised by the composition and delivery tests.
    monkeypatch.setattr(graph, "review_delivery_assumptions", lambda *args: {})
    with fakes.stand_in_graphs():
        yield tmp_path


def _structure(tmp_path):
    ctx = gs._context(tmp_path, graph.GRAPH_ID, {"run_id": "run-structure"})
    builder = gs._deferred_view(graph_registry.builder(ctx.row)(ctx))
    return builder, gs.structure(builder)


def _successors(structure, *, handler=True):
    edges = {}
    for start, end in structure["edges"]:
        for source in (start if type(start) is list else [start]):
            edges.setdefault(source, set()).add(end)
    for source, branches in structure["branches"].items():
        for name, ends in branches.items():
            if source == "reconcile":
                continue  # re-enters only the node whose ambiguous effect it closed
            edges.setdefault(source, set()).update((ends or {}).values())
    if handler:  # the builder's error handler can route any node to these
        for node in structure["nodes"]:
            edges.setdefault(node, set()).update({"decision_turn", "hold"})
    return edges


def _reachable(edges, start, *, avoid=()):
    seen, pending = set(), [start]
    while pending:
        node = pending.pop()
        if node in seen or node in avoid:
            continue
        seen.add(node)
        pending.extend(edges.get(node, ()))
    return seen


def _dispatched():
    return [step for step, _ in fakes.DISPATCHED]


def test_registered_structure_digest_and_registry_row(controller):
    row = graph_registry.get(graph.GRAPH_ID)
    assert row["module"] == "ravel.controller.graph" and row["instance_keys"] == ["run_id"]
    assert {s["id"] for s in row["subgraphs"]} == {graph.STEP_GRAPH, graph.JUDGMENT_GRAPH}
    ctx = gs._context(controller, graph.GRAPH_ID, {"run_id": "run-structure"})
    compiled = gs.build(graph.GRAPH_ID, ctx)
    assert compiled.structure_sha256 == row["structure_sha256"]
    assert gs.lint_graph(compiled) == []
    assert gs.closure(graph.GRAPH_ID) == [[graph.GRAPH_ID, 1], [graph.STEP_GRAPH, 2], [graph.JUDGMENT_GRAPH, 1]]
    assert set(row["gates"]) == set(graph.GATE_NAMES.values())
    assert set(row["interrupts"]) == {"controller_authority", "reconcile_evidence"}


def test_every_interrupt_is_followed_by_its_gate(controller):
    builder, structure = _structure(controller)
    interrupts = [n for n, meta in structure["nodes"].items() if meta["ravel_kind"] == "interrupt" and n != "reconcile"]
    assert sorted(interrupts) == ["checkin1", "checkin2", "checkin3", "deviation", "escalate"]
    for name in interrupts:
        successors = [end for start, end in structure["edges"] if start == name]
        assert successors == [name + "_gate"], name
        assert structure["nodes"][name + "_gate"]["ravel_kind"] == "gate"
    for name, meta in structure["nodes"].items():
        if meta["ravel_kind"] == "gate":
            assert name in structure["branches"] and len(structure["branches"][name]) == 1
            assert not [end for start, end in structure["edges"] if start == name]  # gates are read-only exits


def test_A01_no_path_reaches_execution_without_the_checkin1_gate(controller):
    _, structure = _structure(controller)
    edges = _successors(structure)
    assert "dispatch_wave" in _reachable(edges, "intake")
    for executor in ("dispatch_wave", "step", "join", "checkin2", "deviation", "escalate", "final_review", "deliver"):
        assert executor not in _reachable(edges, "intake", avoid={"checkin1_gate"}), executor
    # Only the prepare phase (rung none or dry) runs before CHECK-IN 1, through its own executor.
    assert "prepare_step" in _reachable(edges, "intake", avoid={"checkin1_gate"})
    # The route is pinned before any planning, preparation or review worker can run (R01).
    for worker in ("plan_review", "judgment_plan", "prepare_step"):
        assert worker not in _reachable(edges, "intake", avoid={"route_select"}), worker


def test_R01_no_worker_or_launch_exists_before_the_route_is_pinned(controller):
    _, structure = _structure(controller)
    edges = _successors(structure)
    for worker in ("plan_review", "judgment_plan", "prepare_step", "step", "final_review"):
        assert worker not in _reachable(edges, "intake", avoid={"route_select"}), worker
    with fakes.installed():
        fakes.PLANS.append(_prepare_plan())
        store, _ = fakes.drive_request(controller)
    route = store.scan("route")[0]["seq"]
    effects = [r["seq"] for kind in ("wave", "review", "manifest", "plan") for r in store.scan(kind)]
    assert effects and min(effects) > route
    assert store.scan("intake")[0]["seq"] < route


def test_bounded_end_is_reachable_from_every_node(controller):
    _, structure = _structure(controller)
    edges = _successors(structure)
    for node in structure["nodes"]:
        if node in ("bounded_end", "reconcile"):
            continue
        assert "bounded_end" in _reachable(edges, node), node
    plain = _successors(structure, handler=False)
    for node in structure["nodes"]:
        if node in ("bounded_end", "deliver", "reconcile", "decision_turn", "hold"):
            continue
        assert "bounded_end" in _reachable(plain, node), node


def test_positive_path_delivers_through_the_sink(controller):
    with fakes.installed() as svc:
        store, observation = fakes.drive_request(controller)
    values = fakes.final_state(store)
    dispatched = _dispatched()
    assert observation["terminal"] is None and observation["next"] == []
    assert svc["sink"].calls and svc["sink"].calls[-1][0] == "deliver"
    assert dispatched[0] == "plan_review" and "j1" in dispatched
    assert dispatched.index("j1") < dispatched.index("final_review")
    assert "kill_the_result" in dispatched  # the judgment route's P8 attacks
    assert values["steps"]["j1"]["status"] == "completed" and values["delivery"]["qualified"] is False
    assert [r["record"]["gate"] for r in store.scan("gate") if r["record"]["passed"]] == ["approve_plan", "final_task"]
    assert [c[1] for c in svc["authority"].calls if c[0] == "request"] == ["approve_plan", "final"]
    assert svc["authority"].calls[0] == ("freeze_mode", True)
    seqs = {r["kind"]: r["seq"] for r in reversed(store.scan("route") + store.scan("review"))}
    assert seqs["route"] < seqs["review"]


def test_checkin_views_follow_the_authority_contract(controller):
    with fakes.installed() as svc:
        store, _ = fakes.drive_request(controller)
    requests = {c[1]: c[2] for c in svc["authority"].calls if c[0] == "request"}
    ci1, final = requests["approve_plan"]["view"], requests["final"]["view"]
    assert ci1["run_id"] == store.run_id and ci1["pins"]["plan_sha256"] == fakes.final_state(store)["plan"]["sha256"]
    assert ci1["items"]["steps"] == ["j1: derive"] and ci1["flags"][0]["kind"] == "decision"
    assert final["pins"]["approve_plan"].startswith("auth-") and "steps_sha256" in final["pins"]
    assert all(type(v) is str for v in ci1["pins"].values())


@pytest.mark.parametrize("answer", ["reject", "adjust"])
def test_A01_a_refused_checkin1_dispatches_no_plan_step(controller, answer):
    with fakes.installed(authority=fakes.FakeAuthority({"approve_plan": answer})) as svc:
        store, observation = fakes.drive_request(controller)
    values, dispatched = fakes.final_state(store), _dispatched()
    assert "j1" not in dispatched
    assert observation["terminal"]["status"] == "qualified"
    assert svc["sink"].calls[-1][0] == "bounded_end"
    if answer == "adjust":  # bounded revisions, each re-planned and re-reviewed
        assert values["plan"]["revision"] == graph.MAX_PLAN_REVISIONS
        assert dispatched.count("plan_review") == graph.MAX_PLAN_REVISIONS + 1


def test_A01_an_unmet_ledger_transition_refuses_execution(controller):
    ledger = fakes.FakeLedger(unmet={"checkin1->execute": [{"entry": "ROUTE-x", "message": "route row unmet"}]})
    with fakes.installed(ledger=ledger):
        store, observation = fakes.drive_request(controller)
    assert "j1" not in _dispatched() and observation["terminal"]["status"] == "qualified"
    refused = [r["record"] for r in store.scan("gate") if not r["record"]["passed"]]
    assert refused and refused[0]["errors"][0]["code"] == "obligation_unmet"
    assert refused[0]["errors"][0]["pins"] == ["ROUTE-x"]


def test_a_decision_gate_refusal_and_an_absent_ledger_fail_closed(controller):
    def refusing(scope_root, gate_name, action):
        return [{"code": "synthetic", "gate": gate_name, "provider": "fixture", "message": "no", "fix": "",
                 "pins": []}] if gate_name == "approve_plan" else []
    with fakes.installed():
        store, observation = fakes.drive_request(controller, gate_check=refusing)
    assert "j1" not in _dispatched() and observation["terminal"]["status"] == "qualified"
    with fakes.installed(ledger=graph._ABSENT["ledger"]) as svc:
        store, observation = fakes.drive_request(controller, rundir=controller / "runs" / "r2")
    assert "j1" not in _dispatched() and observation["terminal"]["status"] == "qualified"
    assert svc["sink"].calls[-1][0] == "bounded_end"


def test_the_acting_node_rechecks_through_the_ledger_and_a_refusal_holds(controller):
    with fakes.installed() as svc:
        fakes.drive_request(controller)
    assert ("decide", "approve_plan") in svc["ledger"].calls
    fakes.reset()
    ledger = fakes.FakeLedger(refuse={"approve_plan": [{"message": "provider refused on re-check"}]})
    with fakes.installed(ledger=ledger) as svc:
        store, observation = fakes.drive_request(controller, rundir=controller / "runs" / "r2")
    assert "j1" not in _dispatched() and observation["terminal"]["status"] == "qualified"
    failures = fakes.final_state(store)["failures"].values()
    assert any(f["node"] == "approved" and f["message"] == "decision_refused"
               and "provider refused on re-check" in f["would_make_possible"] for f in failures)


def _prepare_plan():
    prepare = {"phase": "prepare"}
    return fakes.judgment_plan(steps=[
        fakes.make_step("p1", kind="acquire", rung="none", outputs=["outputs/census.json"], parameters=prepare),
        fakes.make_step("p2", kind="derive", rung="dry", depends_on=["p1"], outputs=["outputs/cost.json"],
                        parameters=prepare),
        fakes.make_step("s1", rung="smoke", depends_on=["p2"], outputs=["outputs/events.json"])])


@pytest.mark.parametrize("answer", ["approve", "reject"])
def test_prepare_steps_run_before_checkin1_and_nothing_else_does(controller, answer):
    with fakes.installed(authority=fakes.FakeAuthority({"approve_plan": answer})) as svc:
        fakes.PLANS.append(_prepare_plan())
        store, observation = fakes.drive_request(controller)
    dispatched = _dispatched()
    assert dispatched[:2] == ["p1", "p2"] and dispatched[2] == "plan_review"
    contexts = {step["id"]: context for step, context in fakes.PACKETS}
    assert contexts["p1"]["phase"] == "prepare" and contexts["p1"]["seat_kind"] == "launch"
    if answer == "approve":
        assert "s1" in dispatched and contexts["s1"]["phase"] == "execute"
        assert observation["terminal"] is None
    else:
        assert "s1" not in dispatched and observation["terminal"]["status"] == "qualified"
    phases = [r["record"].get("phase") for r in store.scan("wave")]
    assert phases[0] == "prepare" and (answer == "reject" or "execute" in phases)


@pytest.mark.parametrize("mutate,fragment", [
    (lambda plan: plan["steps"][1].update(rung="smoke"), "only rungs none and dry"),
    (lambda plan: plan["steps"][0].update(depends_on=["s1"]) or plan["steps"][2].update(depends_on=[]),
     "runs after CHECK-IN 1"),
])
def test_a_prepare_step_above_dry_or_after_execution_is_refused(controller, mutate, fragment):
    plan = _prepare_plan()
    mutate(plan)
    plan["sha256"] = routes.plan_sha256(plan)
    assert any(fragment in p for p in routes.plan_errors(plan))
    with fakes.installed() as svc:
        fakes.PLANS.append(plan)
        store, observation = fakes.drive_request(controller)
    assert fakes.DISPATCHED == [] and svc["sink"].calls[-1][0] == "bounded_end"


def test_waypoint_holds_the_full_rung_until_the_checkin2_go(controller):
    plan = fakes.judgment_plan(steps=[fakes.make_step("w", rung="smoke", waypoint=True, outputs=["outputs/w.json"]),
                                      fakes.make_step("f", rung="full", outputs=["outputs/f.json"])],
                               waypoints=["w"])
    with fakes.installed() as svc:
        fakes.PLANS.append(plan)
        store, observation = fakes.drive_request(controller)
    dispatched = _dispatched()
    assert [c[1] for c in svc["authority"].calls if c[0] == "request"] == ["approve_plan", "go", "final"]
    assert dispatched.index("w") < dispatched.index("f")
    go = [c for c in svc["authority"].calls if c[0] == "request" and c[1] == "go"][0][2]
    assert "waypoint:w" in go["view"]["pins"] and go["view"]["pins"]["approve_plan"].startswith("auth-")
    decided = [c for stage, c in svc["ledger"].contexts if stage == "decide" and c["gate"] == "checkin2_accept"]
    assert [d["waypoint"] for d in decided] == ["w"]
    assert ("gate", "checkin2->execute[w]") in svc["ledger"].calls  # the qualifier names the waypoint step
    assert observation["terminal"] is None


def test_waypoint_without_go_never_runs_the_full_rung(controller):
    plan = fakes.judgment_plan(steps=[fakes.make_step("w", rung="smoke", waypoint=True, outputs=["outputs/w.json"]),
                                      fakes.make_step("f", rung="full", outputs=["outputs/f.json"])],
                               waypoints=["w"])
    with fakes.installed(authority=fakes.FakeAuthority({"go": "stop"})):
        fakes.PLANS.append(plan)
        store, observation = fakes.drive_request(controller)
    dispatched = _dispatched()
    assert "w" in dispatched and "f" not in dispatched and observation["terminal"]["status"] == "qualified"


@pytest.mark.parametrize("decision,completes", [("approve", True), ("reject", False), (("reject", "hold"), False),
                                                (("default", "hold"), False), (("default", "continue"), True)])
def test_escalations_go_to_the_authority_and_a_refusal_holds_only_that_branch(controller, decision, completes):
    plan = fakes.judgment_plan(steps=[fakes.make_step("a", outputs=["outputs/a.json"]),
                                      fakes.make_step("b", outputs=["outputs/b.json"]),
                                      fakes.make_step("c", depends_on=["b"], outputs=["outputs/c.json"])])
    with fakes.installed(authority=fakes.FakeAuthority({"r3_action": decision})) as svc:
        fakes.PLANS.append(plan)
        fakes.SCRIPT["a"] = [{"status": "escalated", "escalation": "decision_block", "reason": "physics-critical"}]
        store, observation = fakes.drive_request(controller)
    values, dispatched = fakes.final_state(store), _dispatched()
    request = [c[2] for c in svc["authority"].calls if c[0] == "request" and c[1] == "r3_action"][0]
    assert request["conservative_default"] == "hold" and [o["id"] for o in request["view"]["options"]] == [
        "continue", "hold"]
    assert "c" in dispatched  # the other branch continued
    if completes:
        assert dispatched.count("a") == 2 and values["steps"]["a"]["status"] == "completed"
        assert observation["terminal"] is None
    else:
        assert dispatched.count("a") == 1 and values["steps"]["a"]["status"] == "held"
        assert values["holds"]["a"]["reason"] == (
            "conservative_default_hold" if decision == ("default", "hold") else "escalation_refused")
        assert observation["terminal"]["status"] == "qualified"


def test_a_new_experiment_request_replans_and_renews_authority(controller):
    first = fakes.judgment_plan(steps=[fakes.make_step("a", outputs=["outputs/a.json"])])
    second = fakes.judgment_plan(steps=[fakes.make_step("a", outputs=["outputs/a.json"]),
                                        fakes.make_step("b", depends_on=["a"], outputs=["outputs/b.json"])],
                                 revision=1)
    with fakes.installed() as svc:
        fakes.PLANS.extend([first, second])
        fakes.SCRIPT["a"] = [{"escalation": "new_experiment_required", "replan": {"why": "control sample"}}]
        store, observation = fakes.drive_request(controller)
    values, dispatched = fakes.final_state(store), _dispatched()
    assert [c[1] for c in svc["authority"].calls if c[0] == "request"] == ["approve_plan", "deviation", "final"]
    deviation = [c[2] for c in svc["authority"].calls if c[0] == "request" and c[1] == "deviation"][0]
    assert deviation["change"]["touches"] == ["b"] and deviation["change"]["direction"] == "plan"
    assert deviation["change"]["why"] == "control sample"
    assert values["plan"]["sha256"] == second["sha256"] and values["plan"]["replans"] == 1
    assert values["plan"]["approved_sha256"] == second["sha256"]
    assert ("decide", "deviation") in svc["ledger"].calls
    event = f"deviation-{second['sha256'][:16]}"
    assert ("event", {"kind": "deviation", "id": event}) in svc["ledger"].contexts  # opened before its gate
    assert ("gate", f"deviation->execute[{event}]") in svc["ledger"].calls
    assert [c["event"] for stage, c in svc["ledger"].contexts if stage == "decide" and c["gate"] == "deviation"] == [event]
    assert "b" in dispatched and observation["terminal"] is None


def test_stop_and_budget_exhaustion_end_qualified_without_further_dispatch(controller):
    plan = fakes.judgment_plan(steps=[fakes.make_step("a", outputs=["outputs/a.json"]),
                                      fakes.make_step("b", depends_on=["a"], outputs=["outputs/b.json"])])
    with fakes.installed(authority=fakes.FakeAuthority(stop=["running", "running", "stop_requested"])) as svc:
        fakes.PLANS.append(plan)
        store, observation = fakes.drive_request(controller)
    dispatched = _dispatched()
    assert "a" in dispatched and "b" not in dispatched
    assert svc["sink"].calls[-1][0] == "bounded_end" and observation["terminal"]["status"] == "qualified"
    with fakes.installed() as svc:
        fakes.PLANS.append(deepcopy(plan))
        fakes.SCRIPT["a"] = [{"status": "budget_exhausted"}]
        store, observation = fakes.drive_request(controller, rundir=controller / "runs" / "r2")
    assert "b" not in _dispatched() and svc["sink"].calls[-1][0] == "bounded_end"


def test_failed_attempts_retry_within_the_step_limit_then_hold_the_branch(controller):
    plan = fakes.judgment_plan(steps=[fakes.make_step("a", outputs=["outputs/a.json"], attempt_limit=2),
                                      fakes.make_step("b", outputs=["outputs/b.json"])])
    with fakes.installed() as svc:
        fakes.PLANS.append(plan)
        fakes.SCRIPT["a"] = [{"status": "failed"}, {"status": "failed"}]
        store, observation = fakes.drive_request(controller)
    values, dispatched = fakes.final_state(store), _dispatched()
    assert dispatched.count("a") == 2 and values["steps"]["a"]["status"] == "failed"
    assert values["steps"]["b"]["status"] == "completed"
    assert svc["sink"].calls[-1][0] == "bounded_end"
    assert '"a": "failed"' in store.latest("wave")["record"]["reason"]


ANALYSIS_REQUEST = (b"Reproduce the published exclusion contour of a fictional search for a heavy scalar decaying to "
                    b"two photons at 13 TeV.")


def test_a_matching_route_spec_compiles_the_plan_and_a_partial_one_goes_to_judgment(controller):
    analysis = next(s for s in fakes.route_specs() if s["id"] == "fixture-analysis")
    with routes.registered(analysis, only=True), fakes.installed():
        store, observation = fakes.drive_request(controller, ANALYSIS_REQUEST)
    values = fakes.final_state(store)
    assert values["route"]["id"] == "fixture-analysis" and values["plan"]["source"] == "route"
    assert "s1" in _dispatched() and observation["terminal"] is None
    partial = deepcopy(analysis)
    partial["deliverables"] = [{"match": {"artifact": ["figure"]}, "step": "s1", "output": "outputs/result.json"}]
    with routes.registered(partial, only=True), fakes.installed():
        store, observation = fakes.drive_request(controller, ANALYSIS_REQUEST, rundir=controller / "runs" / "r2")
    values = fakes.final_state(store)
    assert values["route"]["id"] == "judgment" and values["route"]["reason"] == "open-obligations"
    assert values["plan"]["source"] == "judgment"
    candidates = [r["record"] for r in store.scan("route") if r["record"].get("reason") == "open-obligations"]
    assert candidates and candidates[0]["from"] == "fixture-analysis"
    # The run that falls back to judgment pins the judgment route record it wrote, so its steps are admitted.
    pinned = store.read("route", values["route"]["record_id"])["record"]
    assert pinned["route"] == "judgment" and pinned["reason"] == "open-obligations"
    plan = graph.current_plan(values, store)
    ready = [plan["steps"][0]["id"]]
    assert graph._admitted(values, store, plan, ready, values["steps"]) == (ready, {}, {})


class _Adapter:
    """A fictional route adapter: computed points, a re-bound plan, a CHECK-IN section, a gate and a step check."""
    def __init__(self, *, checkin_errors=(), gate_errors=None, step_errors=None):
        self.calls = []
        self.checkin_errors, self.gate_errors, self.step_errors = list(checkin_errors), gate_errors or {}, \
            list(step_errors or [])

    def parameters(self, spec, reading, contract, supplied):
        self.calls.append("parameters")
        return {"points": [{"id": "p-a"}, {"id": "p-b"}]}

    def bind(self, plan, context):
        self.calls.append("bind")
        assert set(context) == {"store", "run_dir", "plan", "state", "reading", "contract"}
        rebound = deepcopy(plan)
        rebound["revision"] = plan["revision"] + 1
        rebound["sha256"] = routes.plan_sha256(rebound)
        return rebound

    def checkin(self, kind, context):
        self.calls.append(("checkin", kind))
        return {"sections": [{"id": "route-figures", "title": "Figures", "lines": ["fictional figure target"]}],
                "required_sections": ["route-figures"], "flags": [{"kind": "assumption", "text": "fictional A1"}],
                "items": {"assumptions": ["fictional assumption"]}, "pins": {"route_census": "f" * 64},
                "errors": list(self.checkin_errors)}

    def gate(self, transition, context):
        self.calls.append(("gate", transition))
        return list(self.gate_errors.get(transition, []))

    def step(self, step, outcome, context):
        self.calls.append(("step", step["id"]))
        return [self.step_errors.pop(0)] if self.step_errors and step["id"].startswith("point") else []


def _adapter_spec():
    spec = deepcopy(next(s for s in fakes.route_specs() if s["id"] == "fixture-analysis"))
    spec["adapter"] = "fixture_adapter"
    spec["steps"] = [fakes.make_step("prepare", kind="acquire", rung="none", outputs=["outputs/census.json"],
                                     parameters={"phase": "prepare"}),
                     fakes.make_step("point", depends_on=["prepare"], outputs=["outputs/point-{item}.json"],
                                     points=["{item}"], foreach="points", attempt_limit=2),
                     fakes.make_step("s1", depends_on=["point"], outputs=["outputs/result.json"])]
    return spec


def test_route_adapter_hooks_shape_the_plan_check_ins_gates_and_steps(controller, monkeypatch):
    hooks = _Adapter(step_errors=["fictional point check failed once"])
    module = types.ModuleType("ravel.controller.routes.fixture_adapter")
    for name in ("parameters", "bind", "checkin", "gate", "step"):
        setattr(module, name, getattr(hooks, name))
    monkeypatch.setitem(sys.modules, "ravel.controller.routes.fixture_adapter", module)
    with routes.registered(_adapter_spec(), only=True), fakes.installed() as svc:
        store, observation = fakes.drive_request(controller, ANALYSIS_REQUEST)
    values, dispatched = fakes.final_state(store), _dispatched()
    assert observation["terminal"] is None
    assert hooks.calls[0] == "parameters" and "bind" in hooks.calls
    assert dispatched[:2] == ["prepare", "plan_review"]
    assert dispatched.count("point.p-a") + dispatched.count("point.p-b") == 3  # one point retried after its check
    assert {step["id"]: context.get("point") for step, context in fakes.PACKETS
            if step["id"].startswith("point")} == {"point.p-a": "p-a", "point.p-b": "p-b"}
    assert values["plan"]["source"] == "bind" and values["plan"]["revision"] == 1
    ci1 = [c[2] for c in svc["authority"].calls if c[0] == "request" and c[1] == "approve_plan"][0]["view"]
    assert ci1["required_sections"] == ["route-figures"] and ci1["pins"]["route_census"] == "f" * 64
    assert ci1["items"]["assumptions"] == ["fictional assumption"]
    assert ("gate", "checkin1->execute") in hooks.calls and ("checkin", "final") in hooks.calls


@pytest.mark.parametrize("hooks,transition", [
    (_Adapter(checkin_errors=["CHECK-IN 1 lacks its figure section"]), None),
    (_Adapter(gate_errors={"checkin1->execute": [{"code": "fidelity_pin", "message": "fidelity differs"}]}),
     "checkin1->execute"),
])
def test_route_adapter_refusals_hold_the_run_before_execution(controller, monkeypatch, hooks, transition):
    module = types.ModuleType("ravel.controller.routes.fixture_adapter")
    for name in ("parameters", "bind", "checkin", "gate", "step"):
        setattr(module, name, getattr(hooks, name))
    monkeypatch.setitem(sys.modules, "ravel.controller.routes.fixture_adapter", module)
    with routes.registered(_adapter_spec(), only=True), fakes.installed() as svc:
        store, observation = fakes.drive_request(controller, ANALYSIS_REQUEST)
    assert not [s for s in _dispatched() if s.startswith("point") or s == "s1"]
    assert observation["terminal"]["status"] == "qualified" and svc["sink"].calls[-1][0] == "bounded_end"
    if transition:
        refused = [r["record"] for r in store.scan("gate") if not r["record"]["passed"]]
        assert refused[0]["errors"][-1]["code"] == "fidelity_pin" or any(
            e["code"] == "fidelity_pin" for e in refused[0]["errors"])


def test_an_invalid_judgment_plan_holds_and_ends_qualified(controller):
    bad = fakes.judgment_plan()
    bad["steps"][0]["depends_on"] = ["ghost"]
    bad["sha256"] = routes.plan_sha256(bad)
    with fakes.installed() as svc:
        fakes.PLANS.append(bad)
        store, observation = fakes.drive_request(controller)
    assert fakes.DISPATCHED == [] and svc["sink"].calls[-1][0] == "bounded_end"
    values = fakes.final_state(store)
    assert any(f["node"] == "judgment_plan" for f in values["failures"].values())


def test_pending_authority_pauses_and_a_poll_resumes_without_authority_from_the_resume(controller):
    authority = fakes.FakeAuthority({"approve_plan": ["pending", "approve"]})
    with fakes.installed(authority=authority) as svc:
        store, observation = fakes.drive_request(controller)
        assert [i["schema_id"] for i in observation["interrupts"]] == ["controller_authority"]
        payload = observation["interrupts"][0]["payload"]
        assert payload["approval_from_resume"] is False and payload["authority_kind"] == "approve_plan"
        assert "j1" not in _dispatched()
        with pytest.raises(ValueError, match="refused before resume"):
            gs.respond(store.graph_scope(), graph.GRAPH_ID, {"run_id": store.run_id},
                       {observation["interrupts"][0]["id"]: {"kind": "approve"}},
                       gate_check=fakes.passing_gates, gate_providers=fakes.active_providers)
        from ravel.controller import entry
        observation = entry.drive(store, resume=True, gate_check=fakes.passing_gates,
                                  gate_providers=fakes.active_providers)
    assert observation["terminal"] is None and "j1" in _dispatched()
    assert [c[1] for c in svc["authority"].calls if c[0] == "request"].count("approve_plan") >= 2


class _Clock:
    """The time the fake authority reads; the entry's sleep advances it (no real waiting)."""

    def __init__(self):
        self.now, self.sleeps = time.time_ns(), []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += int(seconds * 1e9)


def test_unattended_runs_poll_a_pending_check_in_until_the_operator_answers(controller):
    clock = _Clock()
    authority = fakes.FakeAuthority({"approve_plan": ["pending", "pending", "approve"]},
                                    config={"wait_bound_seconds": 600}, clock=clock)
    with fakes.installed(authority=authority):
        store, observation = fakes.drive_request(controller, unattended=True, sleep=clock.sleep)
    assert observation["terminal"] is None and "j1" in _dispatched()
    assert clock.sleeps and all(0 < s <= 600 for s in clock.sleeps)
    assert not store.scan("authority-wait")


def test_an_unattended_check_in_unanswered_within_the_wait_bound_ends_qualified_without_dispatch(controller):
    clock = _Clock()
    authority = fakes.FakeAuthority({"approve_plan": "pending"}, config={"wait_bound_seconds": 300}, clock=clock)
    with fakes.installed(authority=authority) as svc:
        store, observation = fakes.drive_request(controller, unattended=True, sleep=clock.sleep)
    assert observation["terminal"]["status"] == "qualified" and "j1" not in _dispatched()
    assert svc["sink"].calls[-1][0] == "bounded_end"
    waits = [r["record"] for r in store.scan("authority-wait")]
    assert waits and waits[-1]["kind"] == "approve_plan" and waits[-1]["outcome"] == "held"
    # The wait lasted the operator's bound, in polls the graph's own poll limit allows.
    assert sum(clock.sleeps) >= 300 and len(clock.sleeps) < graph.MAX_POLLS
    # Positive control: interactive runs never time out; they wait for the physicist's resume.
    fakes.reset()
    interactive = fakes.FakeAuthority({"approve_plan": "pending"}, config={"wait_bound_seconds": 0}, clock=clock)
    with fakes.installed(authority=interactive):
        store, observation = fakes.drive_request(controller, rundir=controller / "runs" / "r2")
    assert [i["payload"]["authority_kind"] for i in observation["interrupts"]] == ["approve_plan"]
    assert not store.scan("authority-wait")


def test_an_unattended_escalation_unanswered_within_the_wait_bound_holds_only_its_branch(controller):
    clock = _Clock()
    plan = fakes.judgment_plan(steps=[fakes.make_step("a", outputs=["outputs/a.json"]),
                                      fakes.make_step("b", outputs=["outputs/b.json"]),
                                      fakes.make_step("c", depends_on=["b"], outputs=["outputs/c.json"])])
    authority = fakes.FakeAuthority({"r3_action": "pending"}, config={"wait_bound_seconds": 120}, clock=clock)
    with fakes.installed(authority=authority):
        fakes.PLANS.append(plan)
        fakes.SCRIPT["a"] = [{"status": "escalated", "escalation": "decision_block", "reason": "physics-critical"}]
        store, observation = fakes.drive_request(controller, unattended=True, sleep=clock.sleep)
    values, dispatched = fakes.final_state(store), _dispatched()
    assert "c" in dispatched and dispatched.count("a") == 1  # the other branch continued
    assert values["steps"]["a"]["status"] == "held" and values["holds"]["a"]["reason"] == "escalation_refused"
    assert [r["record"]["kind"] for r in store.scan("authority-wait")] == ["r3_action"]
    assert observation["terminal"]["status"] == "qualified"


def test_each_escalation_is_its_own_r3_decision_and_never_reuses_an_earlier_answer(controller):
    plan = fakes.judgment_plan(steps=[fakes.make_step("a", outputs=["outputs/a.json"]),
                                      fakes.make_step("b", depends_on=["a"], outputs=["outputs/b.json"])])
    with fakes.installed(authority=fakes.FakeAuthority({"r3_action": ["approve", "reject"]})) as svc:
        fakes.PLANS.append(plan)
        fakes.SCRIPT["a"] = [{"status": "escalated", "escalation": "decision_block", "reason": "first question"}]
        fakes.SCRIPT["b"] = [{"status": "escalated", "escalation": "decision_block", "reason": "second question"}]
        store, observation = fakes.drive_request(controller)
    values = fakes.final_state(store)
    views = [c[2]["view"] for c in svc["authority"].calls if c[0] == "request" and c[1] == "r3_action"]
    first, second = views[0], views[-1]
    # Each R3 question names the escalated step and its reason, and binds them in its pins.
    assert first["pins"]["escalations"] != second["pins"]["escalations"]
    assert [f["text"] for f in first["flags"] if f["kind"] == "question"] == ["a: decision_block: first question"]
    assert [f["text"] for f in second["flags"] if f["kind"] == "question"] == ["b: decision_block: second question"]
    # The first answer (continue) let a run again; the second (reject) holds b instead of reusing it.
    assert values["steps"]["a"]["status"] == "completed" and _dispatched().count("b") == 1
    assert values["steps"]["b"]["status"] == "held" and values["holds"]["b"]["reason"] == "escalation_refused"
    assert observation["terminal"]["status"] == "qualified"


def test_R05_the_final_review_joins_each_original_obligation_only_once_the_results_are_accepted(controller):
    class JoiningLedger(fakes.FakeLedger):
        def parent_join(self, store):
            self.calls.append(("parent_join",))
            return []
    ledger = JoiningLedger()
    with fakes.installed(ledger=ledger):
        fakes.drive_request(controller)
    calls = [c[:2] for c in ledger.calls]
    # The ledger's conservation join runs after the final review accepted the results, before CHECK-IN 3's gate.
    assert calls.count(("parent_join",)) == 1, calls
    assert calls.index(("gate", "final_review->checkin3")) < calls.index(("parent_join",)) \
        < calls.index(("gate", "checkin3->deliver")), calls
    fakes.reset()
    refusing = JoiningLedger(unmet={"final_review->checkin3": [{"id": "D04", "entry": "D04@x", "reason": "pending"}]})
    with fakes.installed(ledger=refusing):
        fakes.drive_request(controller, rundir=controller / "runs" / "r2")
    assert ("parent_join",) not in refusing.calls   # no accepted final review, no join


def test_the_ledger_receives_the_whole_plan_and_gates_each_transition(controller):
    with fakes.installed() as svc:
        store, observation = fakes.drive_request(controller)
    ledger = svc["ledger"]
    assert [stage for stage, _ in ledger.contexts if stage != "decide"][:2] == ["intake", "plan"]
    plan_context = next(context for stage, context in ledger.contexts if stage == "plan")
    assert plan_context["plan"]["sha256"] == fakes.final_state(store)["plan"]["sha256"]
    seats = [(step["id"], step["role"], step["parameters"]["review_kind"], context["attempt"])
             for step, context in fakes.PACKETS if step["kind"] == "review"]
    assert seats[0] == ("plan_review", "plan-critic", "critic", 1)
    assert ("kill_the_result", "physics-critic", "crosscheck", 1) in seats
    assert {s for s in seats if s[0] == "final_review"} == {("final_review", r, "final", 1) for r in graph.CI3_SEATS}
    producer = [context for step, context in fakes.PACKETS if step["id"] == "j1"][0]
    assert producer["seat_kind"] == "worker" and producer["attempt"] == 1
    assert [c[1] for c in ledger.calls if c[0] == "gate"] == [
        "intake->route_select", "route_select->plan", "plan->plan_review", "plan_review->checkin1",
        "checkin1->execute", "execute->final_review", "final_review->checkin3", "checkin3->deliver"]


@pytest.mark.parametrize("transition", ["intake->route_select", "route_select->plan", "plan->plan_review",
                                        "plan_review->checkin1", "final_review->checkin3", "checkin3->deliver"])
def test_an_unmet_transition_ends_the_run_qualified(controller, transition):
    ledger = fakes.FakeLedger(unmet={transition: [{"entry": "ROW-1", "message": "fictional row unmet",
                                                   "reason": "unmet", "consequence": "qualified"}]})
    with fakes.installed(ledger=ledger) as svc:
        store, observation = fakes.drive_request(controller)
    dispatched = _dispatched()
    assert observation["terminal"]["status"] == "qualified" and svc["sink"].calls[-1][0] == "bounded_end"
    if transition not in ("final_review->checkin3", "checkin3->deliver"):
        assert "j1" not in dispatched
    recorded = [r["record"] for r in store.scan("transition") + store.scan("gate")
                if r["record"].get("transition") == transition]
    assert recorded and recorded[-1]["passed"] is False
    assert recorded[-1]["errors"][0]["pins"] == ["ROW-1"] and recorded[-1]["errors"][0]["message"] == "fictional row unmet"


def test_ready_steps_respects_dependencies_attempts_the_go_and_the_phase():
    pins = {"steps": ["a", "b", "c", "d"], "depends": {"a": [], "b": ["a"], "c": [], "d": ["c"]}, "prepare": ["c"]}
    steps = {"a": {"status": "completed"}, "c": {"status": "running"}, "d": {"rung": "full"}}
    assert graph.ready_steps(pins, steps) == ["b"]
    steps["c"] = {"status": "completed"}
    assert graph.ready_steps(pins, steps, go=False) == ["b"]
    assert graph.ready_steps(pins, steps, go=True) == ["b", "d"]
    steps["b"] = {"status": "retry", "attempts": 1}
    assert graph.ready_steps(pins, steps)[0] == "b"
    assert graph.ready_steps(pins, {"a": {"status": "completed"}}, phase="prepare") == ["c"]


def test_absent_services_fail_closed():
    absent = graph._ABSENT
    assert absent["ledger"].gate(None, "checkin1->execute")[0]["id"] == "ledger-not-installed"
    assert absent["ledger"].decide(None, "x", "approve_plan", {})
    assert "pending" in absent["authority"].request(None, "approve_plan", {}, {})
    with pytest.raises(graph_nodes.RecoveryHold):
        absent["sink"].deliver(None, {})
    assert absent["judgment"].classify({"class": "R0"}) == "R3"


@pytest.mark.parametrize("fails", [False, True])
def test_the_route_ending_hook_records_unfinished_work_and_never_blocks_the_ending(controller, monkeypatch, fails):
    calls = []

    def ending(reason, context):
        calls.append((reason, sorted(context)))
        if fails:
            raise RuntimeError("fictional ending failure")
    module = types.ModuleType("ravel.controller.routes.fixture_adapter")
    module.ending = ending
    monkeypatch.setitem(sys.modules, "ravel.controller.routes.fixture_adapter", module)
    spec = deepcopy(next(s for s in fakes.route_specs() if s["id"] == "fixture-analysis"))
    spec["adapter"] = "fixture_adapter"
    with routes.registered(spec, only=True), fakes.installed(authority=fakes.FakeAuthority({"approve_plan": "reject"})) as svc:
        store, observation = fakes.drive_request(controller, ANALYSIS_REQUEST)
    assert observation["terminal"]["status"] == "qualified" and svc["sink"].calls[-1][0] == "bounded_end"
    assert len(calls) == 1 and "CHECK-IN 1" in calls[0][0]
    assert calls[0][1] == ["contract", "plan", "reading", "run_dir", "state", "store"]
    assert bool(store.scan("ending-hook")) is fails


def test_the_route_admits_each_step_before_it_is_sent_and_a_refusal_holds_only_that_step(controller, monkeypatch):
    seen = []

    def admit(step, context):
        seen.append(step["id"])
        assert set(context) == {"store", "run_dir", "plan", "state", "reading", "contract"}
        return [{"code": "mode_contract", "message": "fictional delivery contract missing"}] \
            if step["id"] == "point.p-a" else []
    module = types.ModuleType("ravel.controller.routes.fixture_adapter")
    module.admit = admit
    module.parameters = lambda spec, reading, contract, supplied: {"points": [{"id": "p-a"}, {"id": "p-b"}]}
    monkeypatch.setitem(sys.modules, "ravel.controller.routes.fixture_adapter", module)
    with routes.registered(_adapter_spec(), only=True), fakes.installed() as svc:
        store, observation = fakes.drive_request(controller, ANALYSIS_REQUEST)
    values, dispatched = fakes.final_state(store), _dispatched()
    assert seen[0] == "prepare" and "point.p-a" in seen  # both phases ask the route
    assert "point.p-a" not in dispatched and "point.p-b" in dispatched and "s1" not in dispatched
    assert values["steps"]["point.p-a"]["status"] == "held"
    assert values["holds"]["point.p-a"] == {"reason": "admission_refused",
                                            "would_make_possible": "fictional delivery contract missing"}
    assert store.latest("admission")["record"]["held"] == ["point.p-a"]
    assert observation["terminal"]["status"] == "qualified" and svc["sink"].calls[-1][0] == "bounded_end"


def test_a_route_binding_that_drops_route_seats_or_stages_is_refused_before_checkin1(controller, monkeypatch):
    def bind(plan, context):
        rebound = deepcopy(plan)
        rebound["checkins"] = [{**c, "seats": []} for c in rebound["checkins"]]
        rebound["revision"] = plan["revision"] + 1
        rebound["sha256"] = routes.plan_sha256(rebound)
        return rebound
    module = types.ModuleType("ravel.controller.routes.fixture_adapter")
    module.bind = bind
    module.parameters = lambda spec, reading, contract, supplied: {"points": [{"id": "p-a"}]}
    monkeypatch.setitem(sys.modules, "ravel.controller.routes.fixture_adapter", module)
    with routes.registered(_adapter_spec(), only=True), fakes.installed() as svc:
        store, observation = fakes.drive_request(controller, ANALYSIS_REQUEST)
    dispatched = _dispatched()
    assert dispatched == ["prepare"] and observation["terminal"]["status"] == "qualified"
    failures = fakes.final_state(store)["failures"].values()
    assert any(f["node"] == "bind" and "lost its seats" in (f["would_make_possible"] or "") for f in failures)


def test_review_seats_receive_their_rules_and_the_routes_checkin1_review_items(controller, monkeypatch):
    items = [{"id": "census", "check": "every source the request names is in the resource census"},
             {"id": "substance", "check": "no CHECK-IN 1 section is empty or a placeholder"}]
    module = types.ModuleType("ravel.controller.routes.fixture_adapter")
    module.checkin = lambda kind, context: {"sections": [], "review_items": items}
    module.parameters = lambda spec, reading, contract, supplied: {"points": [{"id": "p-a"}]}
    monkeypatch.setitem(sys.modules, "ravel.controller.routes.fixture_adapter", module)
    with routes.registered(_adapter_spec(), only=True), fakes.installed():
        fakes.drive_request(controller, ANALYSIS_REQUEST)
    seats = {(step["id"], step["role"]): step for step, _ in fakes.PACKETS if step["kind"] == "review"}
    plan_seat = seats[("plan_review", "plan-critic")]
    assert plan_seat["instruction_sources"] == ["docs/workflow/checklists/check-ins.md"]
    assert plan_seat["parameters"]["review_items"] == items
    final = seats[("final_review", "skeptical-verifier")]
    assert final["instruction_sources"] == ["docs/workflow/steps/09-verify.md",
                                            "docs/workflow/checklists/verification-panel.md"]
    assert "review_items" not in final["parameters"]


# ---- with the real authority service (P06) -------------------------------------------------------

class _CanonicalItems:
    """The real authority service. While it lacks its canonical check-in items (``retained.view_items``, which
    its owner is adding), this lane stands in for that one helper: the items are rendered once from the
    retained plan and reading, and captured with exactly those items. The authenticated disposition reader and
    the mechanism-row evidence its owner adds with them (``disposition``, ``ledger_evidence``) are stood in for
    the same way, mirroring the owner's implementation over the service's own records; once the service has a
    helper, its own is used. Every other call is the service's own."""

    def __init__(self, authority):
        self._authority = authority
        for name in ("disposition", "ledger_evidence"):
            if hasattr(authority, name):
                setattr(self, name, getattr(authority, name))

    def __getattr__(self, name):
        return getattr(self._authority, name)

    @staticmethod
    def disposition(store, record_id, *, kind, subject):
        """A current decision and its pins, authenticated without granting an effect (a final disposition too)."""
        from ravel.controller.authority import common, service, stop
        kind = common.kind_of(kind)
        if type(record_id) is not str or not record_id:
            raise common.AuthorityRefused(f"no {kind} authority record named")
        try:
            record = common.read(store, common.AUTHORITY, record_id, common.SCHEMA)
        except KeyError:
            raise common.AuthorityRefused(f"{kind} authority {record_id!r} is not in the controller store") from None
        if record.get("run_id") != common.run_id(store):
            raise common.AuthorityRefused("the authority record belongs to a different run")
        if record.get("kind") != kind:
            raise common.AuthorityRefused(f"record {record_id} is {record.get('kind')} authority, not {kind}")
        if kind in common.CONTROLS:
            if stop.control(store)["record"] != record["id"]:
                raise common.AuthorityRefused("control authority was superseded by a later control")
        else:
            service._current_record(store, record)
        if record.get("label") == common.TERMINAL:
            raise common.AuthorityRefused("human terminal attestation is unavailable on this platform")
        if record.get("label") not in common.LABELS:
            raise common.AuthorityRefused("the unattested authority label authorizes nothing")
        if subject is not None:
            bound = record.get("subject") or {}
            if kind not in common.CONTROLS:
                bound = bound.get("pins") or {}
            for name, value in subject.items():
                if bound.get(name) != value:
                    raise common.AuthorityRefused(f"{kind} authority {record_id} is stale: pin {name} changed")
        if record["label"] in (common.MACHINE, common.DELEGATED) and stop.control(store)["revoked"]:
            raise common.AuthorityRefused("machine authority for this run was revoked by the operator")
        return record

    @staticmethod
    def ledger_evidence(store):
        """Mechanism-row evidence from the authenticated authority records (none for an action that never ran)."""
        from ravel.controller.authority import common, mode, service, stop
        frozen = mode.frozen(store)
        history = service._authority_records(store)
        observations = common.scan(store, common.OBSERVATIONS, common.OBSERVATION_SCHEMA)
        mode.effective_bounds(store)
        stop.control(store)
        evidence = {row: {"authority": frozen["id"]} for row in ("A02", "A03", "C09", "SW01", "SW02")}

        def cite(rows, record):
            for row in rows:
                evidence[row] = {"authority": record["id"]}
        for record in history:
            kind = record["kind"]
            if (record.get("label") == common.LEGACY_TERMINAL and record.get("source") == "controller_terminal"
                    and not record.get("authorizes_effects")):
                cite(("CT07",), record)
            if kind in common.CONTROLS:
                cite(("A10", "G06", "B05", "C40", "SW05"), record)
            if record.get("mode_record") != frozen["id"] or record.get("label") not in common.LABELS:
                continue
            if kind == "steering" and record.get("decision") == "approve" and record.get("authorizes_effects"):
                cite(("C37", "C38", "C39", "SW03"), record)
            if kind == "r3_action" and record.get("subject", {}).get("gate") in service.GATES_R3:
                cite(("A11", "G11"), record)
            change = record.get("subject", {}).get("change")
            if (kind == "deviation" and record.get("decision") == "approve" and record.get("authorizes_effects")
                    and type(change) is dict and set(change) == set(service.CHANGE_KEYS)):
                cite(("A09", "C20", "C21", "C32"), record)
        for record in service._requests(store):
            if (record.get("mode_record") == frozen["id"] and record["kind"] == "r3_action"
                    and record.get("subject", {}).get("gate") in service.GATES_R3):
                cite(("A11", "G11"), record)
        for record in observations:
            if record.get("control") in {r["id"] for r in history if r["kind"] in common.CONTROLS}:
                cite(("B05", "C40", "SW05"), record)
        return evidence

    @staticmethod
    def view_items(plan, reading):
        from ravel.controller.authority import common
        items = deepcopy(dict(reading.get("items") or {}))
        for key in ("steps", "deliverables"):
            items[key] = [common.canonical(row) for row in plan.get(key) or []]
        items["boundaries"] = list(items.get("boundaries") or [])
        return items

    def capture(self, store, kind, *, plan, reading, view):
        from ravel.controller.authority import common, mode, retained
        kind = common.kind_of(kind)
        if not {"request_pins", "inferred_critical_facts", "flags"} <= set(reading):
            raise common.AuthorityRefused("reading must explicitly disclose request comparisons and inferred facts")
        if kind == "approve_plan" and (not plan.get("steps") or not plan.get("deliverables")):
            raise common.AuthorityRefused("a retained plan requires steps and deliverables")
        requested, planned = mode.frozen(store).get("request_pins", {}), plan.get("request_pins", {})
        if not set(requested) <= set(planned):
            raise common.AuthorityRefused("the retained plan omits frozen request pins")
        reading = deepcopy(reading)
        reading["request_pins"].update({k: {"requested": v, "planned": planned[k]} for k, v in requested.items()})
        expected = {**deepcopy(view), "items": self.view_items(plan, reading), "flags": deepcopy(reading["flags"])}
        value = {"kind": kind, "view": expected, "plan": deepcopy(plan), "reading": reading}
        previous = next((r for r in reversed(common.scan(store, retained.KIND, retained.SCHEMA))
                         if r["kind"] == kind), None)
        if previous is not None and all(previous[k] == v for k, v in value.items()):
            return previous
        return common.append(store, retained.KIND, {"schema": retained.SCHEMA, "uid": common.uid(),
                                                    "run_id": common.run_id(store), **value})


class _Mutating:
    """A worker changed a deliverable in the check-in view on its way to the authority service."""

    def __init__(self, authority):
        self._authority = authority

    def __getattr__(self, name):
        return getattr(self._authority, name)

    def request(self, store, kind, subject, bounds):
        subject = deepcopy(subject)
        if kind == "approve_plan":
            first = subject["view"]["items"]["deliverables"][0]
            subject["view"]["items"]["deliverables"][0] = (first.replace("answer", "altered")
                                                           if type(first) is str else {**first, "id": "D-altered"})
        return self._authority.request(store, kind, subject, bounds)


@pytest.fixture
def real_authority(controller, monkeypatch):
    """The real authority service in autonomous mode, its operator configuration in the test's lock domain."""
    from ravel.workflow.approval_authority import AGENT_MARKERS
    for name in AGENT_MARKERS:
        monkeypatch.delenv(name, raising=False)
    from ravel.controller import authority
    from ravel.controller.authority import issuer, operator, retained
    monkeypatch.setattr(issuer, "home", lambda: operator.controller_home() / "issuer")
    operator.init(mode="autonomous")
    return authority if hasattr(retained, "view_items") else _CanonicalItems(authority)


def _mapped_plan():
    return fakes.judgment_plan(deliverables=[{"id": "D1", "status": "mapped", "step": "j1",
                                              "output": "outputs/answer.json"}])


def _accept_final(store, observation, capfd):
    from ravel.controller import authority, entry
    [pending] = entry._pending(observation)
    assert pending["payload"]["authority_kind"] == "final"
    code = re.findall(r"--code (\S+)", capfd.readouterr().err)[-1]
    result = authority.answer(store, pending["payload"]["pending"]["request"], code, "accept")
    assert result["label"] == "operator_command"
    return entry.drive(store, resume=True, gate_check=fakes.passing_gates, gate_providers=fakes.active_providers)


def test_checkin1_resolves_with_the_real_authority_service(controller, real_authority, capfd):
    from ravel.controller import authority
    from ravel.controller.authority import retained
    plan = _mapped_plan()
    fakes.PLANS.append(plan)
    with fakes.installed(authority=real_authority) as svc:
        store, observation = fakes.drive_request(controller, unattended=False)
        observation = _accept_final(store, observation, capfd)
    records = {r["kind"]: r for r in authority.records(store)}
    assert records["approve_plan"]["label"] == "operator_configured_machine", observation.get("interrupts")
    assert records["approve_plan"]["decision"] == "approve" and records["approve_plan"]["authorizes_effects"]
    assert "j1" in _dispatched() and _dispatched().index("plan_review") < _dispatched().index("j1")
    assert [r["record"]["gate"] for r in store.scan("gate") if r["record"]["passed"]][0] == "approve_plan"
    # The controller captured the snapshot before it asked: the request was decided on that snapshot.
    snapshot = retained.current(store, "approve_plan")
    approval = authority.verify(store, records["approve_plan"]["id"], kind="approve_plan")
    assert approval["subject"]["context_record"] == snapshot["id"]
    assert snapshot["plan"]["sha256"] == plan["sha256"] and snapshot["reading"]["inferred_critical_facts"] == []
    assert snapshot["view"]["pins"]["plan_sha256"] == plan["sha256"]
    # The final check-in is captured and decided the same way, and the run delivers through the sink.
    assert records["final"]["label"] == "operator_command"
    assert retained.current(store, "final")["view"]["pins"]["approve_plan"] == records["approve_plan"]["id"]
    assert observation["terminal"] is None and svc["sink"].calls[-1][0] == "deliver"

    # A worker-mutated view (a changed deliverable) is refused against the captured snapshot: nothing runs.
    fakes.reset()
    fakes.PLANS.append(_mapped_plan())
    with fakes.installed(authority=_Mutating(real_authority)):
        mutated, observation = fakes.drive_request(controller, unattended=True, rundir=controller / "runs" / "r2")
    pending = observation["interrupts"][0]["payload"]["pending"]
    assert pending["reason"] == "check-in incomplete"
    assert any("differs from authenticated retained plan and reading" in e for e in pending["errors"])
    assert not [r for r in authority.records(mutated) if r["kind"] == "approve_plan"]
    assert "j1" not in _dispatched()


def test_checkin2_and_a_deviation_are_decided_on_captured_snapshots(controller, real_authority, capfd):
    from ravel.controller import authority
    from ravel.controller.authority import retained
    plan = fakes.judgment_plan(steps=[fakes.make_step("w", rung="smoke", waypoint=True, outputs=["outputs/w.json"]),
                                      fakes.make_step("f", rung="full", outputs=["outputs/f.json"])],
                               deliverables=[{"id": "D1", "status": "mapped", "step": "f", "output": "outputs/f.json"}],
                               waypoints=["w"])
    fakes.PLANS.append(plan)
    with fakes.installed(authority=real_authority):
        store, observation = fakes.drive_request(controller, unattended=False)
        observation = _accept_final(store, observation, capfd)
    records = {r["kind"]: r for r in authority.records(store)}
    assert records["go"]["label"] == "operator_configured_machine", observation.get("interrupts")
    snapshot = retained.current(store, "go")
    assert snapshot["view"]["pins"]["approve_plan"] == records["approve_plan"]["id"]
    assert snapshot["view"]["pins"]["waypoint:w"] and authority.verify(store, records["go"]["id"], kind="go")
    assert [s["id"] for s in snapshot["view"]["sections"]][:2] == ["preamble", "waypoint"]
    assert _dispatched().index("w") < _dispatched().index("f") and observation["terminal"] is None

    # A step asks for a new experiment: the replanned plan's deviation is captured and decided on its own snapshot.
    fakes.reset()
    deliverables = [{"id": "D1", "status": "mapped", "step": "a", "output": "outputs/a.json"}]
    first = fakes.judgment_plan(steps=[fakes.make_step("a", outputs=["outputs/a.json"])], deliverables=deliverables)
    second = fakes.judgment_plan(steps=[fakes.make_step("a", outputs=["outputs/a.json"]),
                                        fakes.make_step("b", depends_on=["a"], outputs=["outputs/b.json"])],
                                 deliverables=deliverables, revision=1)
    fakes.PLANS.extend([first, second])
    fakes.SCRIPT["a"] = [{"escalation": "new_experiment_required", "replan": {"why": "control sample"}}]
    with fakes.installed(authority=real_authority):
        replanned, observation = fakes.drive_request(controller, unattended=False, rundir=controller / "runs" / "r2")
        observation = _accept_final(replanned, observation, capfd)
    records = {r["kind"]: r for r in authority.records(replanned)}
    assert records["deviation"]["label"] == "operator_configured_machine", observation.get("interrupts")
    deviation = retained.current(replanned, "deviation")
    assert deviation["plan"]["sha256"] == second["sha256"] and deviation["view"]["pins"]["plan_sha256"] == second["sha256"]
    assert retained.current(replanned, "approve_plan")["plan"]["sha256"] == first["sha256"]
    assert "b" in _dispatched() and observation["terminal"] is None


# ---- one budget and stage vocabulary between the plan, the authority and the step -------------------------------

# Operator ceilings above every installed route's summed step budget, so that the only budget escalation a CHECK-IN
# could still meet is a dimension the authority does not know.
GENEROUS = {"wall_seconds": 10 ** 9, "model_calls": 10 ** 9, "tokens": 10 ** 12, "core_hours": 10 ** 6,
            "events": 10 ** 12, "children": 10 ** 6, "review_rounds": 10 ** 6}


@pytest.fixture
def generous_authority(controller, monkeypatch):
    """The real authority service in autonomous mode with explicit operator ceilings above every installed route."""
    from ravel.workflow.approval_authority import AGENT_MARKERS
    for name in AGENT_MARKERS:
        monkeypatch.delenv(name, raising=False)
    from ravel.controller import authority
    from ravel.controller.authority import issuer, operator, retained
    monkeypatch.setattr(issuer, "home", lambda: operator.controller_home() / "issuer")
    operator.init(mode="autonomous", budgets=GENEROUS, wait_bound_seconds=0)
    return authority if hasattr(retained, "view_items") else _CanonicalItems(authority)


def _installed_plans():
    """Every installed route spec compiled over one reading (``routes.compile``, adapters included)."""
    from ravel.cli import _draft_route
    from ravel.controller.routes.select import installed_specs
    contract, reading, _ = _draft_route(ANALYSIS_REQUEST.decode(), None, None)
    return {spec["id"]: routes.compile(spec, reading, contract) for spec in installed_specs()}


def _carrying(compiled):
    """A judgment-route plan carrying a compiled route plan's steps (budgets, rungs, launches) and waypoints."""
    steps = deepcopy(compiled["steps"])
    producer = next(s for s in reversed(steps) if s.get("outputs"))
    return fakes.judgment_plan(steps=steps, waypoints=list(compiled.get("waypoints") or []),
                               deliverables=[{"id": "D1", "status": "mapped", "step": producer["id"],
                                              "output": producer["outputs"][0]["path"]}])


def test_checkin1_budget_is_within_the_operator_envelope_for_every_installed_spec(controller, generous_authority):
    from ravel.controller import authority
    from ravel.controller.authority import operator
    compiled = _installed_plans()
    assert {"inspect", "legacy", "manuscript", "ml.inference", "ml.training"} <= set(compiled)
    for route_id, plan in sorted(compiled.items()):
        fakes.reset()
        fakes.PLANS.append(_carrying(plan))
        with fakes.installed(authority=generous_authority):
            store, observation = fakes.drive_request(controller, unattended=True,
                                                     rundir=controller / "runs" / route_id)
        records = [r for r in authority.records(store) if r["kind"] == "approve_plan"]
        waits = [r["record"].get("reason") or "" for r in store.scan("authority-request")
                 if r["record"].get("kind") == "approve_plan"]
        assert not [w for w in waits if "broker_calls" in w or "ceiling 0" in w], (route_id, waits)
        assert records and records[-1]["decision"] == "approve", (route_id, waits, observation.get("terminal"))
        assert records[-1]["label"] == "operator_configured_machine"
        bounds = graph.plan_bounds(plan)
        # One vocabulary: every bound dimension is an authority budget key; step retry limits stay out.
        assert set(bounds["budget"]) <= set(operator.BUDGET_KEYS), (route_id, bounds["budget"])
        declared = [s.get("budget") or {} for s in plan["steps"]]
        if any("broker_calls" in b for b in declared):
            assert bounds["budget"]["model_calls"] == sum(b.get("broker_calls", 0) for b in declared)
        launches = {((s.get("parameters") or {}).get("launch") or {}).get("stage") for s in plan["steps"]} - {None}
        assert launches <= set(bounds["stages"]), route_id  # every launch stage is inside the approval
    assert graph.plan_bounds(compiled["ml.training"])["stages"].count("ml-training") == 1


def test_the_step_context_carries_its_stage_and_the_go_pins_it_executes_under(controller, generous_authority):
    from ravel.controller import authority
    plan = fakes.judgment_plan(steps=[
        fakes.make_step("w", rung="smoke", waypoint=True, outputs=["outputs/w.json"]),
        fakes.make_step("f", kind="operate", rung="full", depends_on=["w"], outputs=["outputs/f.json"],
                        operation="fictional-operation",
                        parameters={"launch": {"stage": "fictional-training", "argv": ["fictional"]}}),
        fakes.make_step("g", kind="derive", rung="full", depends_on=["w"], outputs=["outputs/g.json"])],
        deliverables=[{"id": "D1", "status": "mapped", "step": "g", "output": "outputs/g.json"}], waypoints=["w"])
    assert graph.plan_bounds(plan)["stages"] == ["derive", "fictional-operation", "fictional-training", "operate"]
    fakes.PLANS.append(plan)
    with fakes.installed(authority=generous_authority):
        store, observation = fakes.drive_request(controller, unattended=True)
    contexts = {step["id"]: context for step, context in fakes.PACKETS}
    # The stage P04 asks the authority to admit: the launch's declared stage, else the operation, else the kind.
    assert contexts["f"]["stage"] == "fictional-training" and contexts["g"]["stage"] == "derive"
    assert contexts["w"]["stage"] == "operate" and contexts["plan_review"]["stage"] == "review"
    # The GO pins are the waypoint digests the GO bound; the authority finds that GO from them.
    go = [r for r in authority.records(store) if r["kind"] == "go"][-1]
    approval = [r for r in authority.records(store) if r["kind"] == "approve_plan"][-1]
    pins = authority.verify(store, go["id"], kind="go")["subject"]["pins"]
    for step_id in ("f", "g"):
        assert contexts[step_id]["go_pins"] == {k: v for k, v in pins.items() if k.startswith("waypoint:")}
        assert contexts[step_id]["requires_go"] is True
        assert authority.current(store, "go", {**contexts[step_id]["go_pins"],
                                               "approve_plan": approval["id"]})["id"] == go["id"]
    # A plan without a waypoint has no CHECK-IN 2: its full steps need no GO.
    fakes.reset()
    fakes.PLANS.append(fakes.judgment_plan(steps=[fakes.make_step("h", kind="derive", rung="full",
                                                                  outputs=["outputs/h.json"])],
                                           deliverables=[{"id": "D1", "status": "mapped", "step": "h",
                                                          "output": "outputs/h.json"}]))
    with fakes.installed(authority=generous_authority):
        fakes.drive_request(controller, unattended=True, rundir=controller / "runs" / "r2")
    context = {step["id"]: context for step, context in fakes.PACKETS}["h"]
    assert context["requires_go"] is False and context["go_pins"] == {} and context["stage"] == "derive"


# ---- frozen agent preferences reach every worker step -------------------------------------------------------------

PREFERENCES = {"schema_version": 1, "kind": "agent-preferences",
               "transport_preference": ["ravel-loop-local", "claude-cli-worker"]}
# The operator settings the authority freezes into the mode record with the preferences (WA-A2's record fields).
FROZEN = {"budgets": {"model_calls": 100}, "budget_source": {"kind": "default_budgets"}, "harness": None,
          "engagement": {"minimum_tier": None}, "restricted_sources": None, "remote_job_ceiling": 0,
          "procedure_byte_ceiling": 1048576, "site_resource_ceilings": None}


class _FreezingPreferences(_FakeAuthority):
    """The authority's mode record as the operator configuration freezes it: with the agent preferences (or
    without them, ``preferences=None``) and the other consumer settings."""

    def __init__(self, *args, preferences=PREFERENCES, **kwargs):
        super().__init__(*args, **kwargs)
        self.preferences = deepcopy(preferences)

    def freeze_mode(self, store, contract, *, run_dir=None):
        self.calls.append(("freeze_mode", run_dir is not None))
        record = self._append(store, {"kind": "mode", "mode": self.mode, "bounds": {},
                                      "label": "operator_configured_machine", **deepcopy(FROZEN),
                                      "agent_preferences": deepcopy(self.preferences)})
        return {**record, "record_id": record["id"]}


def _p04_seat_admission(store, step, context):
    """The governed step's admission of a worker seat (``seats.preferences``), ahead of the stand-in's outcome: a
    seat without admitted frozen preferences holds as P04 holds it."""
    from ravel.controller.step import seats, spec
    if spec.branch(step) == "worker":
        try:
            seats.preferences(context, {"family": "fictional-family"})
        except Exception as exc:  # P04's StepHold
            return fakes.step_outcome(step, int(context.get("attempt", 1)), status="held",
                                      reason=getattr(exc, "reason", str(exc)))
    return None


def test_worker_packet_carries_the_frozen_preferences(controller, monkeypatch):
    from ravel.controller import entry
    from ravel.controller.step import seats
    real_step = fakes.step_run

    def admitted_step(store, step, context):
        outcome = real_step(store, step, context)  # records the packet the step graph received
        return _p04_seat_admission(store, step, context) or outcome
    monkeypatch.setattr(fakes, "step_run", admitted_step)
    views = []
    invoke = graph._invoke
    monkeypatch.setattr(graph, "_invoke", lambda state, graph_id, view, segment:
                        views.append((graph_id, deepcopy(view))) or invoke(state, graph_id, view, segment))
    authority = _FreezingPreferences({"approve_plan": ["pending", "approve"]})
    with fakes.installed(authority=authority):
        store = entry.start(fakes.REQUEST, channel="terminal", rundir=controller / "runs" / "r1",
                            root=controller / "controller-store")
        # A run-tree copy of the preferences (the old stand-in) is never read: it names no admitted transport.
        (store.run_dir / "inputs").mkdir(exist_ok=True)
        (store.run_dir / "inputs" / "agent_preferences.json").write_text(json.dumps(
            {**PREFERENCES, "transport_preference": ["codex-cli-worker"]}))
        observation = entry.drive(store, gate_check=fakes.passing_gates, gate_providers=fakes.active_providers)
        first_step, first_context = fakes.PACKETS[0]
        assert first_step["id"] == "plan_review" and first_context.get("agent_preferences") == PREFERENCES
        assert [i["payload"]["authority_kind"] for i in observation["interrupts"]] == ["approve_plan"]
        paused = fakes.final_state(store)
        # The resume path continues from the store with the same frozen mode projection.
        resumed = entry.open_for_resume(store.run_id, root=controller / "controller-store")
        observation = entry.drive(resumed, resume=True, gate_check=fakes.passing_gates,
                                  gate_providers=fakes.active_providers)
    assert observation["terminal"] is None and "j1" in _dispatched()
    for values in (paused, fakes.final_state(store)):
        assert values["mode"]["agent_preferences"] == PREFERENCES
        assert {k: values["mode"][k] for k in FROZEN} == FROZEN  # every frozen consumer setting is kept
    contexts = {step["id"]: context for step, context in fakes.PACKETS}
    for step_id in ("j1", "plan_review", "final_review", "kill_the_result"):
        assert contexts[step_id]["agent_preferences"] == PREFERENCES, step_id
        assert contexts[step_id]["agent_preferences"]["transport_preference"] == ["ravel-loop-local",
                                                                                  "claude-cli-worker"]
    prefs, kept, _ = seats.preferences(contexts["j1"], {"family": "fictional-family"})
    assert kept == ["ravel-loop-local", "claude-cli-worker"]
    judgment = [view["context"] for graph_id, view in views if graph_id == graph.JUDGMENT_GRAPH]
    assert judgment and all(c["agent_preferences"] == PREFERENCES for c in judgment)

    # A run frozen without preferences holds at its first worker step: no permissive default replaces them.
    fakes.reset()
    with fakes.installed(authority=_FreezingPreferences(preferences=None)) as svc:
        held, observation = fakes.drive_request(controller, rundir=controller / "runs" / "r2")
    assert _dispatched() == ["plan_review"] and observation["terminal"]["status"] == "qualified"
    assert fakes.PACKETS[0][1]["agent_preferences"] is None
    review = held.latest("review")["record"]["seats"]["plan-critic"]
    assert review["status"] == "held" and review["credited"] is False
    assert svc["sink"].calls[-1][0] == "bounded_end"
    # A malformed (unadmitted) frozen value is no preference document either.
    fakes.reset()
    with fakes.installed(authority=_FreezingPreferences(preferences={"transport_preference": ["claude-cli-worker"]})):
        fakes.drive_request(controller, rundir=controller / "runs" / "r3")
    assert _dispatched() == ["plan_review"] and fakes.PACKETS[0][1]["agent_preferences"] is None


# ---- seat and adapter conformance ---------------------------------------------------------------------------------

# The step schema names a seat's check-in by the controller's name; the installed instruction catalogue keys its
# check-in templates CI1, CI2, CI3 and deviation. Until the instruction package selects the template from the schema's
# name, a manifest is built with the template the name stands for; once it does, the installed manifest is used as it
# is. Any other refusal is the instruction package's own.
CHECKIN_TEMPLATES = {"checkin1": "CI1", "checkin2": "CI2", "checkin3": "CI3", "deviation": "deviation"}
# The study-family routes (their CHECK-IN 3 seats name the synthesizer alias).
STUDY_ROUTES = ("study", "study.site", "scoped", "calculation", "chain")


def _p03_manifest(step, card):
    """The real instruction manifest (P03) of ``step`` for the effective ``card``."""
    from ravel.controller import instructions
    try:
        return instructions.manifest(step, card)
    except instructions.PacketRefused as exc:
        if exc.reasons != [f"unknown instruction selector: checkin:{step.get('checkin')}"]:
            raise
    return instructions.manifest({**step, "checkin": CHECKIN_TEMPLATES[step["checkin"]]}, card)


def _route_plan(route_id):
    """The installed route's plan compiled over one reading (its adapter's parameters included)."""
    from ravel.cli import _draft_route
    contract, reading, _ = _draft_route(ANALYSIS_REQUEST.decode(), None, None)
    return routes.compile(routes.find(route_id), reading, contract)


def test_checkin3_seat_for_a_study_route_names_the_card_id(controller, monkeypatch):
    from ravel.controller.step import cards
    from ravel.workflow import role_registry
    # Every study-family route compiles (the calculation route's DAG included) and seats an alias at CHECK-IN 3.
    declared = {route: next(c["seats"] for c in _route_plan(route)["checkins"] if c["id"] == "checkin3")
                for route in STUDY_ROUTES}
    assert all("synthesizer" in seats for seats in declared.values()), declared
    plan = _mapped_plan()
    plan["checkins"] = deepcopy(_route_plan("study")["checkins"])
    plan["sha256"] = routes.plan_sha256(plan)
    with fakes.installed() as svc:
        fakes.PLANS.append(plan)
        store, observation = fakes.drive_request(controller)
    final = [step for step, _ in fakes.PACKETS if step["id"] == "final_review"]
    pinned = role_registry.registry_sha256()
    for step in final:
        # The governed step builds the seat's packet from the card of the role the step names (P03 refuses another).
        manifest = _p03_manifest(step, graph._card(step["role"]))
        card, _, _ = cards.resolve(step["role"], {"registry_sha256": pinned})  # P04: a canonical role id, no alias
        assert manifest["role"] == card["id"] == step["role"]
    assert [step["role"] for step in final] == ["physics-critic", "skeptical-verifier", "physics-decider"]
    assert set(store.latest("review")["record"]["seats"]) == {"physics-critic", "skeptical-verifier",
                                                               "physics-decider"}
    assert observation["terminal"] is None and svc["sink"].calls[-1][0] == "deliver"

    # A route whose adapter is not installed holds with a typed reason before anything is planned or dispatched.
    fakes.reset()
    spec = deepcopy(next(s for s in fakes.route_specs() if s["id"] == "fixture-analysis"))
    spec["adapter"] = "fixture_absent_adapter"
    with routes.registered(spec, only=True), fakes.installed() as svc:
        store, observation = fakes.drive_request(controller, ANALYSIS_REQUEST, rundir=controller / "runs" / "r2")
        with pytest.raises(graph_nodes.RecoveryHold) as held:  # and at run time, for a plan already installed
            graph.adapter({"plan": {"route": spec["id"]}})
    failures = list(fakes.final_state(store)["failures"].values())
    assert [(f["node"], f["failure_kind"], f["message"]) for f in failures] == [
        ("plan_compile", "recovery_hold", "route_adapter_missing")]
    assert held.value.reason == "route_adapter_missing"
    assert fakes.DISPATCHED == [] and observation["terminal"]["status"] == "qualified"
    assert svc["sink"].calls[-1][0] == "bounded_end"

    # An installed adapter whose own import fails raises its own error: it is never read as a missing adapter.
    package = sys.modules["ravel.controller.routes"]
    adapters = controller / "adapters"
    adapters.mkdir()
    (adapters / "fixture_broken_adapter.py").write_text("import fictional_missing_dependency  # noqa: F401\n")
    monkeypatch.setattr(package, "__path__", [*package.__path__, str(adapters)])
    broken = {**spec, "adapter": "fixture_broken_adapter"}
    with routes.registered(broken, only=True):
        with pytest.raises(ModuleNotFoundError) as failed:
            graph.adapter({"plan": {"route": broken["id"]}})
    assert failed.value.name == "fictional_missing_dependency"


# ---- CHECK-IN 2 review seats and the check-in units every check-in seat receives -----------------------------------

def _p04_review_seat_admission(store, step, context, manifests):
    """The governed step's admission of a controller review seat ahead of the stand-in's outcome: the published step
    schema (``spec.check``), the seat bound to the pinned plan (``operations.plan_step``) and its canonical card
    (``cards.resolve``), then the seat's real instruction manifest (P03). A refusal holds the seat as P04 holds it; an
    admitted seat's manifest is kept in ``manifests``."""
    from ravel.controller import instructions
    from ravel.controller.step import cards, operations, spec
    from ravel.controller.step.services import StepHold
    from ravel.workflow import role_registry
    if step.get("kind") != "review":
        return None
    try:
        checked = spec.check(step)
        operations.plan_step(store, checked, context)
        card, _, _ = cards.resolve(checked["role"], {"registry_sha256": role_registry.registry_sha256()})
        manifests.append((checked, _p03_manifest(checked, card)))
    except (StepHold, instructions.PacketRefused) as exc:
        return fakes.step_outcome(step, int(context.get("attempt", 1)), status="held",
                                  reason=getattr(exc, "reason", str(exc)))
    return None


def _waypoint_plan(seats=("figure-critic", "physics-critic")):
    plan = fakes.judgment_plan(steps=[fakes.make_step("w", rung="smoke", waypoint=True, outputs=["outputs/w.json"]),
                                      fakes.make_step("f", rung="full", depends_on=["w"], outputs=["outputs/f.json"])],
                               deliverables=[{"id": "D1", "status": "mapped", "step": "f", "output": "outputs/f.json"}],
                               waypoints=["w"])
    plan["checkins"] = [{"id": "checkin2", "seats": list(seats)}]
    plan["sha256"] = routes.plan_sha256(plan)
    return plan


def test_checkin2_dispatches_the_declared_waypoint_seat_before_go(controller, monkeypatch):
    from ravel.controller.instructions import catalogue
    real_step, manifests = fakes.step_run, []

    def admitted_step(store, step, context):
        outcome = real_step(store, step, context)  # records the packet the step graph received
        return _p04_review_seat_admission(store, step, context, manifests) or outcome
    monkeypatch.setattr(fakes, "step_run", admitted_step)
    seats = ["waypoint_review.figure-critic", "waypoint_review.physics-critic"]
    with fakes.installed() as svc:
        fakes.PLANS.append(_waypoint_plan())
        store, observation = fakes.drive_request(controller)
    values, dispatched = fakes.final_state(store), _dispatched()
    # Each declared seat is its own step (its own reservation) and reviews the executed waypoint before the GO.
    assert dispatched.index("w") < min(dispatched.index(s) for s in seats) and max(
        dispatched.index(s) for s in seats) < dispatched.index("f")
    review = next(r for r in reversed(store.scan("review")) if r["record"]["purpose"] == "waypoint")
    go = next(r for r in store.scan("authority") if r["record"]["kind"] == "go")
    assert review["seq"] < go["seq"] and go["record"]["subject"]["pins"]["checkin2_review"] == review["id"]
    assert set(review["record"]["seats"]) == {"figure-critic", "physics-critic"}
    assert all(v["credited"] and v["verdict"] == "accept" for v in review["record"]["seats"].values())
    outputs = values["steps"]["w"]["outputs"]
    for seat_id in seats:
        step, context = next((s, c) for s, c in fakes.PACKETS if s["id"] == seat_id)
        assert step["role"] == seat_id.split(".", 1)[1] and step["checkin"] == "checkin2"
        assert step["parameters"]["purpose"] == "waypoint" and step["depends_on"] == ["w"]
        assert [i for i in step["inputs"] if i["artifact"] != "inputs/controller-plan.json"] == [
            {"artifact": f"w:{o['path']}", "sha256": o["sha256"]} for o in outputs]  # the exact waypoint artifacts
    # Every check-in seat names its check-in, and its real manifest carries that check-in's units.
    templates = {name: set(catalogue.installed().resolve(f"checkin:{template}"))
                 for name, template in CHECKIN_TEMPLATES.items()}
    admitted = {(step["id"], step["role"]): (step, manifest) for step, manifest in manifests}
    for key, checkin in ((("waypoint_review.figure-critic", "figure-critic"), "checkin2"),
                         (("waypoint_review.physics-critic", "physics-critic"), "checkin2"),
                         (("plan_review", "plan-critic"), "checkin1"),
                         (("final_review", "physics-decider"), "checkin3")):
        step, manifest = admitted[key]
        assert step["checkin"] == checkin and templates[checkin]
        assert templates[checkin] <= {u["id"] for u in manifest["units"] if u["via"] in ("checkin", "source")}, key
    assert "f" in dispatched and observation["terminal"] is None and svc["sink"].calls[-1][0] == "deliver"

    # A seat that keeps returning revise, or whose review is not credited, holds checkin2->execute: no GO, no full rung.
    for name, script in (("revise", [{"review": {"credited": True, "verdict": "revise"}}] * 8),
                         ("uncredited", [{"status": "held", "reason": "review_uncredited",
                                          "review": {"credited": False, "verdict": None}}])):
        fakes.reset()
        with fakes.installed() as svc:
            fakes.PLANS.append(_waypoint_plan())
            fakes.SCRIPT["waypoint_review.physics-critic"] = deepcopy(script)
            store, observation = fakes.drive_request(controller, rundir=controller / "runs" / name)
        assert "waypoint_review.physics-critic" in _dispatched() and "f" not in _dispatched()
        assert "go" not in [c[1] for c in svc["authority"].calls if c[0] == "request"]
        assert observation["terminal"]["status"] == "qualified" and svc["sink"].calls[-1][0] == "bounded_end"

    # The seats ran but their review record is not in the store when the gate checks it: the gate refuses the GO.
    fakes.reset()
    recorded = graph._record_review
    monkeypatch.setattr(graph, "_record_review", lambda store, record: "review-000000-unrecorded"
                        if record["purpose"] == "waypoint" else recorded(store, record))
    with fakes.installed() as svc:
        fakes.PLANS.append(_waypoint_plan())
        store, observation = fakes.drive_request(controller, rundir=controller / "runs" / "unrecorded")
    refused = [r["record"] for r in store.scan("gate") if r["record"]["gate"] == "checkin2_accept"]
    assert refused and not refused[-1]["passed"]
    assert any(e["code"] == "checkin2_review_missing" for e in refused[-1]["errors"])
    assert "f" not in _dispatched() and observation["terminal"]["status"] == "qualified"


# ---- a credited revise is a performed review, never acceptance: bounded correction rounds -------------------------

FINDINGS = "step-review-findings"


class _ReviewBounds(_FakeJudgment):
    """The judgment service with its policy bounds for the run's frozen mode (``judgment.bounds``)."""

    def __init__(self, review_rounds):
        self.review_rounds = review_rounds

    def bounds(self, mode):
        return {"review_rounds": self.review_rounds}


def _reviewing(monkeypatch):
    """The stand-in step graph records, for each scripted review that does not accept, the protected findings record
    the governed step writes (``step-review-findings``) and names it in the outcome (``review.findings``)."""
    real_step = fakes.step_run

    def step_run(store, step, context):
        outcome = real_step(store, step, context)
        review = outcome.get("review") or {}
        if review.get("verdict") in ("revise", "unresolved") and review.get("findings") is None:
            record = store.append(FINDINGS, {"schema_version": 1, "step_id": step["id"], "parent_step": step["id"],
                                             "attempt": outcome["attempt"], "verdict": review["verdict"],
                                             "subject_sha256": fakes.digest(outcome["outputs"]),
                                             "record": {"item_verdicts": [{"id": "fictional-defect",
                                                                           "verdict": "fail"}]}})
            outcome["review"] = {**review, "findings": [record]}
        return outcome
    monkeypatch.setattr(fakes, "step_run", step_run)


REVISE = {"review": {"credited": True, "verdict": "revise"}, "budget": {"wall_seconds": 7}}


def _accept(step_id):
    """A credited accepting review of a corrected attempt that changed the artifact."""
    return {"review": {"credited": True, "verdict": "accept"}, "budget": {"wall_seconds": 7},
            "outputs": [{"path": f"outputs/{step_id}.json", "sha256": fakes.digest({"corrected": step_id})}]}


def test_credited_revise_triggers_a_bounded_correction(controller, monkeypatch):
    _reviewing(monkeypatch)
    plan = fakes.judgment_plan(steps=[fakes.make_step("a", kind="derive", outputs=["outputs/a.json"])],
                               deliverables=[{"id": "D1", "status": "mapped", "step": "a", "output": "outputs/a.json"}])
    with fakes.installed(judgment=_ReviewBounds(3)) as svc:
        fakes.PLANS.append(plan)
        fakes.SCRIPT["a"] = [deepcopy(REVISE), _accept("a")]
        store, observation = fakes.drive_request(controller)
    values = fakes.final_state(store)
    contexts = [context for step, context in fakes.PACKETS if step["id"] == "a"]
    # The producer runs again as a new attempt, with the findings of the review pinned as its input.
    assert [c["attempt"] for c in contexts] == [1, 2] and "correction" not in contexts[0]
    finding = store.scan(FINDINGS)[0]
    correction = contexts[1]["correction"]
    assert correction["findings"] == [{"record": finding["id"], "kind": FINDINGS, "digest": finding["digest"],
                                       "verdict": "revise", "subject_sha256": finding["record"]["subject_sha256"]}]
    assert (correction["round"], correction["rounds"], correction["verdict"], correction["purpose"]) == (
        1, 2, "revise", "step")
    # The re-reviewed, changed artifact is accepted: the run completes and delivers; nothing was reset.
    assert values["steps"]["a"]["status"] == "completed" and values["steps"]["a"]["attempts"] == 2
    assert values["steps"]["a"]["outputs"] == _accept("a")["outputs"]
    assert values["budget"]["used"]["wall_seconds"] == 14
    assert observation["terminal"] is None and svc["sink"].calls[-1][0] == "deliver"

    # A sibling that keeps returning revise stops at the bound, without a budget reset, and the run ends qualified.
    fakes.reset()
    plan = fakes.judgment_plan(steps=[fakes.make_step("a", kind="derive", outputs=["outputs/a.json"]),
                                      fakes.make_step("b", kind="derive", outputs=["outputs/b.json"])],
                               deliverables=[{"id": "D1", "status": "mapped", "step": "a", "output": "outputs/a.json"}])
    with fakes.installed(judgment=_ReviewBounds(3)) as svc:
        fakes.PLANS.append(plan)
        fakes.SCRIPT["a"] = [deepcopy(REVISE), _accept("a")]
        fakes.SCRIPT["b"] = [deepcopy(REVISE) for _ in range(6)]
        store, observation = fakes.drive_request(controller, rundir=controller / "runs" / "r2")
    values = fakes.final_state(store)
    assert [c["attempt"] for s, c in fakes.PACKETS if s["id"] == "b"] == [1, 2, 3]  # two corrections: the bound
    assert [c["correction"]["round"] for s, c in fakes.PACKETS if s["id"] == "b" and "correction" in c] == [1, 2]
    assert values["steps"]["a"]["status"] == "completed"
    assert values["steps"]["b"]["status"] == "held" and values["holds"]["b"]["reason"] == "review_rounds_exhausted"
    assert values["budget"]["used"]["wall_seconds"] == 7 * 5  # every attempt is charged; nothing was reset
    assert "final_review" not in _dispatched()
    assert observation["terminal"]["status"] == "qualified" and svc["sink"].calls[-1][0] == "bounded_end"


def test_correction_rounds_come_from_the_judgment_policy_else_the_frozen_operator_budgets():
    from ravel.controller import judgment
    mode = {"budgets": {"max_redos": 1, "review_rounds": 3}}
    with graph.services(judgment=_ReviewBounds(4)):
        assert graph.correction_rounds({"mode": mode}) == 3  # four review rounds: the first review and three more
    with graph.services(judgment=fakes.FakeJudgment()):
        assert graph.correction_rounds({"mode": mode}) == 1  # the stricter of max_redos and review_rounds - 1
        assert graph.correction_rounds({"mode": {"budgets": {"review_rounds": 3}}}) == 2
        assert graph.correction_rounds({"mode": {"budgets": {"max_redos": 0, "review_rounds": 3}}}) == 0
        assert graph.correction_rounds({"mode": {}}) == 0  # nothing configured: no correction
    with graph.services(judgment=judgment):  # the installed policy names no review_rounds: the operator's budgets
        assert graph.correction_rounds({"mode": mode}) == 1


def _correction_of(context):
    return (context["correction"]["purpose"], context["correction"]["round"], context["correction"]["verdict"])


def test_credited_revise_at_each_check_in_seat_corrects_its_producer_within_the_bound(controller, monkeypatch):
    _reviewing(monkeypatch)
    corrected_w = {"outputs": [{"path": "outputs/w.json", "sha256": fakes.digest({"corrected": "w"})}]}
    # CHECK-IN 2: the waypoint step runs again with the seat's findings; the seat reviews its new outputs; then the GO.
    with fakes.installed(judgment=_ReviewBounds(3)) as svc:
        fakes.PLANS.append(_waypoint_plan(seats=("physics-critic",)))
        fakes.SCRIPT["waypoint_review.physics-critic"] = [deepcopy(REVISE)]
        fakes.SCRIPT["w"] = [{}, deepcopy(corrected_w)]
        store, observation = fakes.drive_request(controller, rundir=controller / "runs" / "waypoint")
    contexts = {sid: [c for s, c in fakes.PACKETS if s["id"] == sid] for sid in ("w", "waypoint_review.physics-critic")}
    assert [c["attempt"] for c in contexts["w"]] == [1, 2]
    assert _correction_of(contexts["w"][1]) == ("waypoint", 1, "revise")
    assert [f["record"] for f in contexts["w"][1]["correction"]["findings"]] == [store.scan(FINDINGS)[0]["id"]]
    assert [c["attempt"] for c in contexts["waypoint_review.physics-critic"]] == [1, 2]
    rounds = [r for r in store.scan("review") if r["record"]["purpose"] == "waypoint"]
    go = next(r for r in store.scan("authority") if r["record"]["kind"] == "go")["record"]["subject"]["pins"]
    assert len(rounds) == 2 and rounds[0]["record"]["subject_sha256"] != rounds[1]["record"]["subject_sha256"]
    assert go["checkin2_review"] == rounds[1]["id"] and go["waypoint:w"] == graph._digest(corrected_w["outputs"])
    assert _dispatched().index("f") > _dispatched().index("w", 2) and svc["sink"].calls[-1][0] == "deliver"

    # CHECK-IN 3: the deliverable's producer runs again in the final review; the triad reviews the new results.
    fakes.reset()
    with fakes.installed(judgment=_ReviewBounds(3)) as svc:
        fakes.PLANS.append(_mapped_plan())
        fakes.SCRIPT["final_review"] = [deepcopy(REVISE)]
        fakes.SCRIPT["j1"] = [{}, _accept("answer")]
        store, observation = fakes.drive_request(controller, rundir=controller / "runs" / "final")
    values = fakes.final_state(store)
    contexts = [c for s, c in fakes.PACKETS if s["id"] == "j1"]
    assert [c["attempt"] for c in contexts] == [1, 2] and _correction_of(contexts[1]) == ("final", 1, "revise")
    assert sorted({c["attempt"] for s, c in fakes.PACKETS if s["id"] == "final_review"}) == [1, 2]
    assert values["steps"]["j1"]["outputs"] == _accept("answer")["outputs"]
    assert values["reviews"]["corrections"] == {"final": 1} and values["reviews"]["final_rounds"] == [1, 2]
    assert observation["terminal"] is None and svc["sink"].calls[-1][0] == "deliver"

    # CHECK-IN 1: the planner revises the plan with the plan critic's findings; the new plan is reviewed again.
    fakes.reset()
    views = []
    invoke = graph._invoke
    monkeypatch.setattr(graph, "_invoke", lambda state, graph_id, view, segment:
                        views.append((graph_id, deepcopy(view))) or invoke(state, graph_id, view, segment))
    with fakes.installed(judgment=_ReviewBounds(3)) as svc:
        fakes.PLANS.extend([_mapped_plan(), _mapped_plan()])
        fakes.SCRIPT["plan_review"] = [deepcopy(REVISE)]
        store, observation = fakes.drive_request(controller, rundir=controller / "runs" / "plan")
    planning = [view["context"] for graph_id, view in views if graph_id == graph.JUDGMENT_GRAPH]
    assert len(planning) == 2 and "correction" not in planning[0]
    assert _correction_of(planning[1]) == ("plan", 1, "revise")
    assert [f["record"] for f in planning[1]["correction"]["findings"]] == [store.scan(FINDINGS)[0]["id"]]
    assert [c["attempt"] for s, c in fakes.PACKETS if s["id"] == "plan_review"] == [1, 2]
    assert fakes.final_state(store)["plan"]["revision"] == 1 and svc["sink"].calls[-1][0] == "deliver"


@pytest.mark.parametrize("seat", ["plan_review", "waypoint_review.physics-critic", "final_review"])
def test_a_check_in_seat_that_keeps_returning_revise_ends_qualified_at_the_bound(controller, monkeypatch, seat):
    _reviewing(monkeypatch)
    with fakes.installed(judgment=_ReviewBounds(2)) as svc:  # one correction round
        fakes.PLANS.extend([_waypoint_plan(seats=("physics-critic",)), _waypoint_plan(seats=("physics-critic",))])
        fakes.SCRIPT[seat] = [deepcopy(REVISE) for _ in range(9)]
        store, observation = fakes.drive_request(controller)
    values, dispatched = fakes.final_state(store), _dispatched()
    assert sorted({c["attempt"] for s, c in fakes.PACKETS if s["id"] == seat}) == [1, 2]  # bound reached, no third
    assert observation["terminal"]["status"] == "qualified" and svc["sink"].calls[-1][0] == "bounded_end"
    assert "exhausted" in values["status"]["reason"] or "exhausted" in json.dumps(values.get("failures") or {})
    requests = [c[1] for c in svc["authority"].calls if c[0] == "request"]
    if seat == "plan_review":
        assert requests == [] and "w" not in dispatched
    elif seat.startswith("waypoint_review"):
        assert "go" not in requests and "f" not in dispatched
    else:
        assert "final" not in requests and [c["attempt"] for s, c in fakes.PACKETS if s["id"] == "f"] == [1, 2]


def test_a_credited_revise_without_findings_or_rounds_holds_and_never_reaches_checkin3(controller, monkeypatch):
    _reviewing(monkeypatch)
    # A producer's credited revise that names no findings cannot be corrected: the step holds.
    with fakes.installed(judgment=_ReviewBounds(3)) as svc:
        fakes.PLANS.append(_mapped_plan())
        fakes.SCRIPT["j1"] = [{"review": {"credited": True, "verdict": "revise", "findings": []}}]
        store, observation = fakes.drive_request(controller)
    values = fakes.final_state(store)
    assert values["steps"]["j1"]["status"] == "held" and values["holds"]["j1"]["reason"] == "review_findings_missing"
    assert _dispatched().count("j1") == 1 and svc["sink"].calls[-1][0] == "bounded_end"
    # No correction rounds configured: a credited revise at the final review is never read as acceptance.
    fakes.reset()
    with fakes.installed() as svc:
        fakes.PLANS.append(_mapped_plan())
        fakes.SCRIPT["final_review"] = [{"review": {"credited": True, "verdict": "unresolved"}}]
        store, observation = fakes.drive_request(controller, rundir=controller / "runs" / "r2")
    assert "final" not in [c[1] for c in svc["authority"].calls if c[0] == "request"]
    assert observation["terminal"]["status"] == "qualified" and svc["sink"].calls[-1][0] == "bounded_end"
    assert "review_rounds_exhausted" in fakes.final_state(store)["status"]["reason"]


class _HookLedger(fakes.FakeLedger):
    """The ledger interface fake with its gate-provider registry (``register_gate_hook``)."""

    def __init__(self):
        super().__init__()
        self.hooks = {}

    def register_gate_hook(self, provider_id, fn):
        self.hooks[provider_id] = fn


def test_every_graph_build_composes_the_installed_engagement_gates_explicitly(controller, monkeypatch):
    composed = []
    provider = types.ModuleType("ravel.controller.engagement")
    from p07_support import package_path
    package_path(provider)  # the real engagement submodules still import
    provider.register_gates = lambda ledger: composed.append(ledger) or ledger.register_gate_hook("engagement", len)
    monkeypatch.setitem(sys.modules, "ravel.controller.engagement", provider)
    ledger = _HookLedger()
    with fakes.installed(ledger=ledger):
        store, observation = fakes.drive_request(controller)
    assert composed and all(found is ledger for found in composed) and ledger.hooks == {"engagement": len}
    assert observation["terminal"] is None
    # A provider without its registration, or a ledger without a provider registry, composes nothing; the run builds.
    fakes.reset()
    from p07_support import package_path
    monkeypatch.setitem(sys.modules, "ravel.controller.engagement",
                        package_path(types.ModuleType("ravel.controller.engagement")))
    with fakes.installed(ledger=_HookLedger()) as svc:
        store, observation = fakes.drive_request(controller, rundir=controller / "runs" / "r2")
    assert svc["ledger"].hooks == {} and observation["terminal"] is None


# ---- the judgment package's semantics govern the schedule: replans, attacks, decide readiness, ask and route --------

class _BoundedAuthority(_FakeAuthority):
    """The authority interface fake whose frozen mode carries the operator's bounds and budgets."""

    def __init__(self, *args, bounds=None, budgets=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.frozen_bounds, self.frozen_budgets = dict(bounds or {}), budgets

    def freeze_mode(self, store, contract, *, run_dir=None):
        self.calls.append(("freeze_mode", run_dir is not None))
        body = {"kind": "mode", "mode": self.mode, "bounds": dict(self.frozen_bounds),
                "label": "operator_configured_machine"}
        if self.frozen_budgets is not None:
            body["budgets"] = dict(self.frozen_budgets)
        record = self._append(store, body)
        return {**record, "record_id": record["id"]}


def _replanning(requests):
    """Plans whose newest step asks for a new experiment each time: revision n adds step ``b<n>`` after the last."""
    plans, steps = [], [fakes.make_step("a", outputs=["outputs/a.json"])]
    for revision in range(requests + 1):
        if revision:
            steps = steps + [fakes.make_step(f"b{revision}", depends_on=[steps[-1]["id"]],
                                             outputs=[f"outputs/b{revision}.json"])]
        plans.append(fakes.judgment_plan(steps=deepcopy(steps), revision=revision))
    return plans


@pytest.mark.parametrize("bounds,budgets,allowed", [({"replans": 1}, None, 1), ({}, {"replans": 0}, 0), ({}, None, 3)])
def test_the_replan_bound_comes_from_the_frozen_mode_and_never_resets(controller, bounds, budgets, allowed):
    with fakes.installed(authority=_BoundedAuthority(bounds=bounds, budgets=budgets)) as svc:
        fakes.PLANS.extend(_replanning(4))
        for step in ("a", "b1", "b2", "b3", "b4"):
            fakes.SCRIPT[step] = [{"escalation": "new_experiment_required", "replan": {"why": f"control for {step}"}}]
        store, observation = fakes.drive_request(controller)
    values = fakes.final_state(store)
    assert [c[1] for c in svc["authority"].calls if c[0] == "request"].count("deviation") == allowed
    assert values["plan"].get("replans", 0) == allowed and values["plan"]["revision"] == allowed
    assert len([r for r in store.scan("plan") if r["record"]["source"] == "replan"]) == allowed
    assert observation["terminal"]["status"] == "qualified" and "replan bound" in values["status"]["reason"]


def test_checkin1_shows_the_frame_findings_the_plan_carries(controller):
    plan = fakes.judgment_plan()
    plan["parameters"] = {"judgment": {"frame_findings": ["the fictional frame leaves the sign of the bias open",
                                                         {"text": "a fictional unknown stays unresolved"}]}}
    plan["sha256"] = routes.plan_sha256(plan)
    with fakes.installed() as svc:
        fakes.PLANS.append(plan)
        fakes.drive_request(controller)
    ci1 = [c[2] for c in svc["authority"].calls if c[0] == "request" and c[1] == "approve_plan"][0]["view"]
    risks = [f["text"] for f in ci1["flags"] if f["kind"] == "risk"]
    assert "frame finding: the fictional frame leaves the sign of the bias open" in risks
    assert "frame finding: a fictional unknown stays unresolved" in risks


class _AttackRows(fakes.FakeLedger):
    """The ledger interface fake with the row interface for JR09 (node ``judgment.kill_the_result``)."""
    LedgerError = ValueError

    def __init__(self):
        super().__init__()
        self.recorded = []

    def pending(self, store, *, stage=None, node=None, step=None):
        return [f"JR09@{store.run_id}"] if node == "judgment.kill_the_result" and not self.recorded else []

    def record_many(self, store, changes):
        self.recorded.extend(deepcopy(list(changes)))

    def instance_key(self, row, run_id, scope):
        return f"{row}@{run_id}"


def test_delivery_follows_three_recorded_attacks_on_the_exact_plan_and_draft(controller):
    ledger = _AttackRows()
    with fakes.installed(ledger=ledger) as svc:
        store, observation = fakes.drive_request(controller)
    values, dispatched = fakes.final_state(store), _dispatched()
    [record] = store.scan("judgment-attacks")
    attacks = record["record"]
    assert attacks["plan_sha256"] == values["plan"]["sha256"] and attacks["draft_sha256"] == graph._digest(values["steps"])
    assert sorted(a["axis"] for a in attacks["document"]["attacks"]) == sorted(AXES)
    seat = [s for s, _ in fakes.PACKETS if s["id"] == "kill_the_result"][0]
    assert seat["outputs"] == [{"path": "outputs/judgment-attacks.json", "kind": "judgment-attacks", "required": True}]
    assert seat["parameters"]["subject_sha256"] == attacks["draft_sha256"] and seat["depends_on"] == ["j1"]
    # The attacks precede the fresh CHECK-IN 3 triad and become its must-check items.
    assert dispatched.index("kill_the_result") < dispatched.index("final_review")
    finals = [s for s, _ in fakes.PACKETS if s["id"] == "final_review"]
    assert {i["id"] for i in finals[0]["parameters"]["review_items"]} == {f"JR09:{a}" for a in AXES}
    # JR09 is recorded from the attack record and the triad's credit, before the gate checks the transition.
    assert ledger.recorded == [(f"JR09@{store.run_id}", "satisfied", {
        "record": record["id"], "credit": "fake-receipt-final_review-1", "mechanism": "judgment.check_attacks",
        "provider": "P08", "point": "judgment.kill_the_result"})]
    assert observation["terminal"] is None and svc["sink"].calls[-1][0] == "deliver"
    # The CHECK-IN 3 gate checks the attack record again: a changed result or plan refuses delivery.
    with graph.services(judgment=_FakeJudgment()):
        assert graph.attack_errors(values, store, "final_task") == []
        changed = {**values, "steps": {**values["steps"], "j1": {**values["steps"]["j1"], "outputs": []}}}
        assert [e["code"] for e in graph.attack_errors(changed, store, "final_task")] == ["attacks_stale"]
        assert [e["code"] for e in graph.attack_errors({**values, "reviews": {}}, store, "final_task")] == [
            "attacks_missing"]


@pytest.mark.parametrize("writer,problem", [
    (lambda step: _attack_document(step, axes=("basis", "statistics", "basis")), "P8 needs one attack on each"),
    (lambda step: _attack_document(step, subject={"plan_sha256": "0" * 64, "draft_sha256": "0" * 64}),
     "different plan or draft"),
    (lambda step: None, "outputs/judgment-attacks.json"),
    ("unchecked", "check_attacks"),
])
def test_delivery_is_refused_without_three_recorded_attacks(controller, writer, problem):
    ledger = _AttackRows()
    services = {"ledger": ledger}
    if writer == "unchecked":
        services["judgment"] = graph._ABSENT["judgment"]  # nothing can check the attacks: refused, never assumed valid
    else:
        ATTACK_WRITERS[1] = writer
    with fakes.installed(**services) as svc:
        store, observation = fakes.drive_request(controller)
    values, dispatched = fakes.final_state(store), _dispatched()
    assert "kill_the_result" in dispatched and "final_review" not in dispatched  # no triad without the attacks
    assert "final" not in [c[1] for c in svc["authority"].calls if c[0] == "request"]
    assert observation["terminal"]["status"] == "qualified" and svc["sink"].calls[-1][0] == "bounded_end"
    assert problem in values["status"]["reason"] and not store.scan("judgment-attacks")
    [(key, status, evidence)] = ledger.recorded
    assert key == f"JR09@{store.run_id}" and status == "violated" and problem in evidence["reason"]


P7 = {"assumption": "The fictional sample stays representative.", "default": "Keep the first option.",
      "alternatives": ["the second option"], "claim_type": "other", "direction_established": False,
      "expected_sign": "unknown", "expected_size": "small", "reversible_knob": "option", "physics_critical": False,
      "flag": {"checkin_flag": 1, "deviation": "first option kept"}, "justification": None}
OPTIONS = [{"id": "opt-a", "description": "take the first fictional option"},
           {"id": "opt-b", "description": "take the second fictional option"}]
BOUNDS = {"rung": "smoke", "stages": ["derive"], "budget": {"wall_seconds": 60}}


def _ask_plan(default=None):
    judgment = {"options": deepcopy(OPTIONS), "default_option": default, "default": deepcopy(P7) if default else None}
    return fakes.judgment_plan(steps=[
        fakes.make_step("q", kind="ask", question="Which fictional option should the run take?", outputs=[],
                        parameters={"judgment": judgment}),
        fakes.make_step("a", kind="derive", depends_on=["q"], rung="smoke", budget={"wall_seconds": 60},
                        outputs=["outputs/a.json"]),
        fakes.make_step("b", kind="derive", outputs=["outputs/b.json"])],
        deliverables=[{"id": "D1", "status": "mapped", "step": "a", "output": "outputs/a.json"}])


def _parent(kind, status="escalated", route=None):
    """The governed step's outcome for a parent kind (``ask``, ``route``): no worker ran; the request goes up."""
    return {"status": status, "escalation": kind, "outputs": [], "receipts": [], "budget": {}, "reason": kind,
            "request": {"kind": kind, "question": None, "route": route}}


@pytest.mark.parametrize("status", ["escalated", "held"])
@pytest.mark.parametrize("answer,reason", [("pending", "ask_unanswered"), ("reject", "ask_refused")])
def test_an_unanswered_or_refused_ask_holds_only_its_branch(controller, status, answer, reason):
    clock = _Clock()
    authority = fakes.FakeAuthority({"escalation": answer}, config={"wait_bound_seconds": 60}, clock=clock)
    with fakes.installed(authority=authority) as svc:
        fakes.PLANS.append(_ask_plan())  # a default option without its P7 record is no conservative default
        fakes.PLANS[0]["steps"][0]["parameters"]["judgment"]["default_option"] = "opt-a"
        fakes.PLANS[0]["sha256"] = routes.plan_sha256(fakes.PLANS[0])
        fakes.SCRIPT["q"] = [_parent("ask", status)]
        store, observation = fakes.drive_request(controller, unattended=True, sleep=clock.sleep)
    values, dispatched = fakes.final_state(store), _dispatched()
    assert dispatched.count("q") == 1 and "b" in dispatched and "a" not in dispatched
    assert values["steps"]["q"]["status"] == "held" and values["holds"]["q"]["reason"] == reason
    assert values["steps"]["b"]["status"] == "completed" and "answer" not in values["steps"]["q"]
    request = [c[2] for c in svc["authority"].calls if c[0] == "request" and c[1] == "escalation"][0]
    view = request["view"]
    assert "conservative_default" not in request
    assert [(o["id"], o["effect"], o["bounds"]) for o in view["options"]] == [("opt-a", True, BOUNDS),
                                                                              ("opt-b", True, BOUNDS)]
    assert [s["id"] for s in view["sections"]][:2] == ["preamble", "question"]
    assert "Which fictional option should the run take?" in json.dumps(view["sections"])
    assert observation["terminal"]["status"] == "qualified" and svc["sink"].calls[-1][0] == "bounded_end"


@pytest.mark.parametrize("answer,default", [(("answer", "opt-b"), None), (("default", "opt-a"), "opt-a")])
def test_an_answered_ask_retains_the_selected_option_and_its_branch_continues(controller, answer, default):
    with fakes.installed(authority=fakes.FakeAuthority({"escalation": answer})) as svc:
        fakes.PLANS.append(_ask_plan(default=default))
        fakes.SCRIPT["q"] = [_parent("ask")]
        store, observation = fakes.drive_request(controller)
    values = fakes.final_state(store)
    [record] = [r["record"] for r in store.scan("authority") if r["record"]["kind"] == "escalation"]
    request = [c[2] for c in svc["authority"].calls if c[0] == "request" and c[1] == "escalation"][0]
    assert request.get("conservative_default") == default
    assert values["steps"]["q"]["status"] == "completed" and values["steps"]["q"]["answer"] == {
        "option": answer[1], "decision": answer[0], "authority": record["uid"], "bounds": BOUNDS}
    context = [c for s, c in fakes.PACKETS if s["id"] == "a"][0]
    assert context["answers"] == {"q": {"option": answer[1], "authority": record["uid"]}}
    assert _dispatched().count("q") == 1 and observation["terminal"] is None and svc["sink"].calls[-1][0] == "deliver"


def _child_spec(**step):
    spec = deepcopy(next(s for s in fakes.route_specs() if s["id"] == "fixture-analysis"))
    spec["steps"][0].update(step)
    return spec


def _routing_plan():
    return fakes.judgment_plan(steps=[
        fakes.make_step("r", kind="route", route="fixture-analysis", rung="smoke", budget={"wall_seconds": 120}),
        fakes.make_step("c", kind="derive", depends_on=["r"], outputs=["outputs/c.json"])],
        deliverables=[{"id": "D1", "status": "mapped", "step": "c", "output": "outputs/c.json"}])


def test_a_route_step_runs_one_child_with_inherited_limits(controller):
    with routes.registered(_child_spec(rung="smoke", budget={"wall_seconds": 100}), only=True), \
            fakes.installed() as svc:
        fakes.PLANS.append(_routing_plan())
        fakes.SCRIPT["r"] = [_parent("route", route="fixture-analysis")]
        fakes.SCRIPT["s1"] = [{"budget": {"wall_seconds": 30}}]
        store, observation = fakes.drive_request(controller)
    values, dispatched = fakes.final_state(store), _dispatched()
    parent = values["plan"]["sha256"]
    [bound] = store.scan("route-plan")
    child = graph._json_blob(store, bound["record"]["blob"])
    assert (bound["record"]["parent_step"], bound["record"]["parent_plan_sha256"]) == ("r", parent)
    assert child["route"]["id"] == "fixture-analysis" and child["sha256"] == bound["record"]["plan_sha256"]
    assert child["parameters"]["route_child"] == {"parent_step": "r", "parent_plan_sha256": parent}
    # One child, run once through the governed step, after its parent asked for it and before the dependent.
    assert dispatched.count("r") == 1 and dispatched.count("s1") == 1
    assert dispatched.index("r") < dispatched.index("s1") < dispatched.index("c")
    context = [c for s, c in fakes.PACKETS if s["id"] == "s1"][0]
    approval = values["authority"]["approve_plan"][-1]
    assert context["plan_sha256"] == parent and context["mode"] == values["mode"]  # the parent's authority
    assert context["route_child"] == {"step": "r", "plan_sha256": child["sha256"], "record": bound["id"],
                                      "parent_plan_sha256": parent, "approve_plan": approval}
    # The child's usage is the parent's; CHECK-IN 1 approved the exact child plan and its stages.
    assert values["budget"]["used"]["wall_seconds"] >= 30
    assert values["steps"]["r"]["status"] == "completed"
    assert values["steps"]["r"]["child"]["plan_sha256"] == child["sha256"]
    assert values["steps"]["r"]["child"]["steps"]["s1"]["status"] == "completed"
    ci1 = [r["record"] for r in store.scan("authority") if r["record"]["kind"] == "approve_plan"][0]
    assert ci1["subject"]["pins"]["route:r"] == child["sha256"] and "operate" in ci1["bounds"]["stages"]
    assert observation["terminal"] is None and svc["sink"].calls[-1][0] == "deliver"


@pytest.mark.parametrize("child", [{"rung": "full"}, {"budget": {"wall_seconds": 500}}])
def test_a_route_child_beyond_its_step_holds_before_anything_runs(controller, child):
    with routes.registered(_child_spec(**child), only=True), fakes.installed() as svc:
        fakes.PLANS.append(_routing_plan())
        store, observation = fakes.drive_request(controller)
    assert fakes.DISPATCHED == [] and not [c for c in svc["authority"].calls if c[0] == "request"]
    assert observation["terminal"]["status"] == "qualified" and svc["sink"].calls[-1][0] == "bounded_end"
    failures = fakes.final_state(store)["failures"].values()
    assert any(f["message"] == "route_child_exceeds_step" for f in failures)


def _decide_plan(cls):
    return fakes.judgment_plan(steps=[
        fakes.make_step("d", kind="decide", role="coordinator", outputs=["outputs/judgment-record.json"],
                        consequence_class=cls),
        fakes.make_step("e", kind="derive", depends_on=["d"], rung="smoke", budget={"wall_seconds": 60},
                        outputs=["outputs/e.json"]),
        fakes.make_step("f", kind="derive", outputs=["outputs/f.json"])],
        deliverables=[{"id": "D1", "status": "mapped", "step": "e", "output": "outputs/e.json"}])


def _deciding(monkeypatch, cls, *, chosen="opt-a"):
    """The stand-in step graph's decide step records its judgment (the governed step's validation stores the
    worker's record through the judgment package and names it in ``judgments``)."""
    real = fakes.step_run

    def step_run(store, step, context):
        outcome = real(store, step, context)
        if step["kind"] == "decide" and outcome["status"] == "completed":
            # A valid worker record, stored the way the validate node stores it (the judgment package's
            # record_judgment): checked against the step, classified at least at the step's planned class.
            worker = {"schema_version": 1, "kind": "judgment-record", "id": f"judgment-{step['id']}", "step": step["id"],
                      "question": "Which fictional option should the decision take?",
                      "options": [{**o, "predicted_consequences": "fictional"} for o in OPTIONS], "chosen": chosen,
                      "rationale": "the fictional evidence favours it",
                      "action": {"summary": "Take the chosen fictional option.", "kind": "reversible_choice"},
                      "triggers": [],
                      "protocol_evidence": {}, "reversibility": {"kind": "reversible", "note": "before any effect"},
                      "budget_impact": {"note": "nothing is spent"}}
            outcome["judgments"] = [_judgment.records.record_judgment(store, worker, step=step, plan_class=cls)]
        return outcome
    monkeypatch.setattr(fakes, "step_run", step_run)


def test_ready_steps_waits_for_a_closed_decide():
    pins = {"steps": ["d", "e"], "depends": {"d": [], "e": ["d"]}, "decides": ["d"]}
    assert graph.ready_steps(pins, {"d": {"status": "completed"}}) == []
    assert graph.ready_steps(pins, {"d": {"status": "completed", "closed": True}}) == ["e"]


def test_a_decide_without_its_judgment_record_never_closes(controller):
    with fakes.installed() as svc:
        fakes.PLANS.append(_decide_plan("R1"))
        store, observation = fakes.drive_request(controller)
    values, dispatched = fakes.final_state(store), _dispatched()
    assert "d" in dispatched and "f" in dispatched and "e" not in dispatched
    assert values["steps"]["d"]["status"] == "held" and values["holds"]["d"]["reason"] == "judgment_record_missing"
    assert observation["terminal"]["status"] == "qualified" and svc["sink"].calls[-1][0] == "bounded_end"


def test_an_r2_decide_without_its_rdj_case_blocks_its_dependents(controller, monkeypatch):
    _deciding(monkeypatch, "R2")
    with fakes.installed() as svc:
        fakes.PLANS.append(_decide_plan("R2"))
        fakes.SCRIPT["rdj_review.d"] = [{"status": "held", "review": {"credited": False}}]
        store, observation = fakes.drive_request(controller)
    values, dispatched = fakes.final_state(store), _dispatched()
    assert "rdj_review.d" in dispatched and "f" in dispatched and "e" not in dispatched
    assert values["steps"]["d"]["status"] == "held" and values["holds"]["d"]["reason"] == "review_uncredited"
    assert observation["terminal"]["status"] == "qualified" and svc["sink"].calls[-1][0] == "bounded_end"
    # Positive control: the RDJ seat credits the exact record, and only then does the dependent run.
    fakes.reset()
    with fakes.installed() as svc:
        fakes.PLANS.append(_decide_plan("R2"))
        store, observation = fakes.drive_request(controller, rundir=controller / "runs" / "r2")
    values, dispatched = fakes.final_state(store), _dispatched()
    [record] = store.scan("judgment-record")
    seat = [s for s, _ in fakes.PACKETS if s["id"] == "rdj_review.d"][0]
    assert seat["role"] == "rdj-critic" and seat["depends_on"] == ["d"]
    assert seat["parameters"]["subject_sha256"] == record["record"]["record_sha256"]
    assert dispatched.index("d") < dispatched.index("rdj_review.d") < dispatched.index("e")
    assert values["steps"]["d"]["closed"] is True and values["steps"]["d"]["judgment"]["record"] == record["id"]
    assert observation["terminal"] is None and svc["sink"].calls[-1][0] == "deliver"


@pytest.mark.parametrize("answer,closes", [(("approve", "opt-a"), True), (("approve", "opt-b"), False),
                                           ("reject", False)])
def test_an_r3_decide_needs_current_authority_for_its_exact_action(controller, monkeypatch, answer, closes):
    _deciding(monkeypatch, "R3")
    with fakes.installed(authority=fakes.FakeAuthority({"r3_action": answer})) as svc:
        fakes.PLANS.append(_decide_plan("R3"))
        store, observation = fakes.drive_request(controller)
    values, dispatched = fakes.final_state(store), _dispatched()
    [record] = store.scan("judgment-record")
    request = [c[2] for c in svc["authority"].calls if c[0] == "request" and c[1] == "r3_action"][0]
    assert request["view"]["pins"]["judgment:d"] == record["record"]["record_sha256"]
    options = {o["id"]: o for o in request["view"]["options"]}
    assert options["opt-a"]["effect"] is True and options["opt-a"]["bounds"] == BOUNDS  # the recorded choice
    assert options["opt-b"]["effect"] is False  # another option overturns the recorded choice
    rdj = [r for r in store.scan("review") if r["record"]["purpose"] == "rdj"]
    asked = [r for r in store.scan("authority") if r["record"]["kind"] == "r3_action"]
    assert rdj and asked and rdj[0]["seq"] < asked[0]["seq"]  # the RDJ case precedes the R3 question
    assert ("e" in dispatched) is closes and values["steps"]["d"].get("closed") is (True if closes else None)
    if closes:
        assert observation["terminal"] is None and svc["sink"].calls[-1][0] == "deliver"
    else:
        assert values["steps"]["d"]["status"] == "held" and observation["terminal"]["status"] == "qualified"


# ---- two plan identities: the immutable scientific plan and its authenticated applied engagement view --------------

_P18_SPEC = spec_from_file_location("p18_engagement_fakes", Path(__file__).parents[2] / "fixtures/engagement/fakes.py")
p18 = module_from_spec(_P18_SPEC)
_P18_SPEC.loader.exec_module(p18)


def _engagement_facts(store, plan):
    """The controller-derived engagement facts a decision reads, credited on this plan (as the P18 record tests
    write them)."""
    from ravel.controller.engagement.records import digest
    store.append("engagement-population", {"plan_sha256": plan["sha256"],
                                           "deliverable_ids": [d["id"] for d in plan["deliverables"]]})
    method = json.loads((Path(__file__).parents[2] / "fixtures/method_decisions/standard_table.json").read_text())
    for kind, body in (("engagement-method", {"method": method, "scan_points": 1}),
                       ("engagement-novelty", {"value": "N0"})):
        store.append(kind, body)
        store.append("engagement-fact-credit", {"credited": True, "role": "plan-critic", "subject_sha256": digest(body),
                                                "plan_sha256": plan["sha256"]})
    store.append("engagement-special", {"plan_sha256": plan["sha256"], "complete": True, "flags": []})


def _engaging(monkeypatch, plan, *, minimum=None):
    """The engagement package with its fixture policy and cards for ``plan`` (its decisions and applications are its
    own; only the role cards, instruction manifests and operator configuration are the fixture's)."""
    from ravel.controller.engagement import policy
    p18.install_fakes(monkeypatch, operator={"engagement": {"minimum_tier": minimum}} if minimum else None)
    installed = p18.policy_for(plan)
    monkeypatch.setattr(policy, "load_policy", lambda: deepcopy(installed))


def _scientific_pins(store, plan):
    """The scientific plan pinned as the controller pins it: its own bytes, record and digest."""
    blob = graph._put_json(store, plan)
    record = store.append("plan", {"plan_sha256": plan["sha256"], "blob": blob, "source": "route", "revision": 0,
                                   "route": plan["route"]["id"], "open_obligations": 0})
    return {"sha256": plan["sha256"], "blob": blob, "record_id": record, "revision": 0, "source": "route",
            "route": plan["route"]["id"], "steps": [s["id"] for s in plan["steps"]]}


def _plan_step(store, step, context):
    """P04's T03 binding of a step to its approved plan (``operations.plan_step``). While the installed step package
    does not read the applied view yet (its consumer change folds separately), this mirrors that change's binding
    interface over the same records: the plan record's scientific blob and its protected ``applied_blob`` /
    ``applied_sha256`` pair, the context's ``applied_sha256``, and ``engagement.check_applied`` against the current
    effective decision. Once the step package reads it, its own binding is used."""
    from ravel.controller.step import operations
    from ravel.controller.step.services import StepHold
    if "applied_blob" in inspect.getsource(operations.current_plan):
        return operations.plan_step(store, step, context)
    from ravel.controller import engagement
    wanted = context["plan_sha256"]
    record = [r["record"] for r in store.scan("plan") if r["record"].get("plan_sha256") == wanted][-1]
    plan = json.loads(store.get_blob(record["blob"]).decode())
    if plan.get("sha256") != wanted or routes.plan_sha256(plan) != wanted:
        raise StepHold("plan_digest_mismatch", "the complete scientific plan bytes differ from the approved digest")
    if record.get("applied_blob"):
        applied = json.loads(store.get_blob(record["applied_blob"]).decode())
        decision = engagement.effective_decision(store)
        if (decision["scientific_plan"] != plan or engagement.check_applied(applied, decision)
                or record.get("applied_sha256") != applied["engagement"]["applied_sha256"]
                or context.get("applied_sha256") not in (None, record["applied_sha256"])):
            raise StepHold("engagement_view_invalid", "the complete applied view differs from the current decision")
        plan = applied
    found = [row for row in plan["steps"] if row["id"] == step["id"]]
    if len(found) != 1 or graph._digest(found[0]) != graph._digest(step):
        raise StepHold("plan_step_changed", f"step {step['id']} differs from the approved plan")
    return deepcopy(found[0]), plan["sha256"], "plan_step"


def _tampered(applied):
    """Applied views that change scientific scope or the engagement: each must be refused."""
    def operation(view):
        view["steps"][0]["operation"] = "fictional-other-operation"

    def inputs(view):
        view["steps"][1]["inputs"] = [{"artifact": "s1:outputs/other.json", "sha256": None}]

    def scope(view):
        view["deliverables"] = view["deliverables"][:1]

    def undeclared_seat(view):
        view["steps"][1]["seats"].append({"seat": "step:s2:trap-auditor", "role": "trap-auditor", "kind": "review"})

    def dropped_duties(view):
        view["engagement"]["seat_plan"]["seats"][0]["items"] = []

    def correction_bound(view):
        view["steps"][1]["correction_rounds"] += 1
    for change in (operation, inputs, scope, undeclared_seat, dropped_duties, correction_bound):
        view = deepcopy(applied)
        change(view)
        yield change.__name__, view


def test_applied_engagement_plan_keeps_both_identities(controller, monkeypatch, tmp_path):
    from ravel.controller import engagement
    from ravel.controller.step.services import StepHold
    from ravel.controller.store import RunStore
    plan = p18.fictional_plan()
    _engaging(monkeypatch, plan)
    store = RunStore("run-engaged", root=tmp_path / "engaged-store")
    pins = _scientific_pins(store, plan)
    store.append("route", {"route": plan["route"]["id"]})
    _engagement_facts(store, plan)
    decision = engagement.decide(store, {"plan": plan})
    applied = engagement.apply(plan, decision)
    # The applied view keeps the scientific digest and carries its own authenticated digest.
    installed = graph.install_applied_plan(store, pins, applied)
    assert installed["sha256"] == plan["sha256"] == applied["sha256"]
    assert installed["applied_sha256"] == applied["engagement"]["applied_sha256"] != plan["sha256"]
    assert graph.current_plan({"plan": installed}, store) == applied
    scientific = {k: v for k, v in installed.items() if k not in ("applied_blob", "applied_sha256")}
    assert graph.current_plan({"plan": scientific}, store) == plan  # the scientific bytes are untouched
    record = store.scan("plan")[-1]["record"]
    assert record["blob"] == pins["blob"] and json.loads(store.get_blob(record["blob"])) == plan
    assert (record["applied_blob"], record["applied_sha256"]) == (installed["applied_blob"], installed["applied_sha256"])
    # P04's binding accepts the applied steps under both identities.
    context = {"plan_sha256": plan["sha256"], "applied_sha256": installed["applied_sha256"]}
    for step in applied["steps"]:
        assert _plan_step(store, step, context)[:2] == (step, plan["sha256"])
    # Changed operations, inputs, scope, an undeclared seat, dropped duties or an altered correction bound refuse,
    # at installation, at every consumer (current_plan) and at P04's binding.
    for name, view in _tampered(applied):
        with pytest.raises(graph_nodes.RecoveryHold, match="applied_plan_mismatch"):
            graph.install_applied_plan(store, pins, view)
        forged = {**installed, "applied_blob": graph._put_json(store, view),
                  "applied_sha256": view["engagement"]["applied_sha256"]}
        with pytest.raises(graph_nodes.RecoveryHold, match="applied_plan_mismatch"):
            graph.current_plan({"plan": forged}, store)
    with pytest.raises(StepHold):
        _plan_step(store, {**applied["steps"][1], "correction_rounds": 9}, context)
    # Changed scientific bytes refuse whatever the applied view says.
    changed = deepcopy(plan)
    changed["steps"][0]["operation"] = "fictional-other-operation"
    changed["sha256"] = routes.plan_sha256(changed)
    with pytest.raises(graph_nodes.RecoveryHold, match="applied_plan_mismatch"):
        graph.current_plan({"plan": {**installed, "blob": graph._put_json(store, changed),
                                     "sha256": changed["sha256"]}}, store)
    # A later decision (the operator raised the tier) makes the earlier application stale; re-applying the current
    # decision succeeds and the scientific digest is unchanged.
    _engaging(monkeypatch, plan, minimum="full")
    current = engagement.decide(store, {"plan": plan})
    assert decision["tier"] != "full" and current["tier"] == "full" and current["sha256"] != decision["sha256"]
    with pytest.raises(graph_nodes.RecoveryHold, match="applied_plan_mismatch"):
        graph.current_plan({"plan": installed}, store)
    with pytest.raises(StepHold):
        _plan_step(store, applied["steps"][0], context)
    renewed = graph.install_applied_plan(store, scientific, engagement.apply(plan, engagement.effective_decision(store)))
    assert renewed["sha256"] == plan["sha256"] and graph.current_plan({"plan": renewed}, store)["sha256"] == plan["sha256"]


class _ViewSink(fakes.FakeSink):
    """The sink interface fake that keeps the plan document it was asked to deliver."""

    def __init__(self):
        super().__init__()
        self.plans = []

    def deliver(self, store, plan):
        self.plans.append(deepcopy(plan))
        return super().deliver(store, plan)


def test_an_applied_view_is_kept_through_resume_dispatch_and_delivery(controller, monkeypatch):
    """With the engagement decision applied when CHECK-IN 1 is approved (a stand-in for the engagement wiring), the
    run keeps both identities across a pause and a resume, dispatches the applied steps under them, binds them in its
    check-ins and delivers the applied view."""
    from ravel.controller import engagement, entry
    plan = fakes.judgment_plan(steps=[fakes.make_step("w", rung="smoke", waypoint=True, outputs=["outputs/w.json"]),
                                      fakes.make_step("f", rung="full", depends_on=["w"], outputs=["outputs/f.json"])],
                               deliverables=[{"id": "D1", "status": "mapped", "step": "f", "output": "outputs/f.json"}],
                               waypoints=["w"])
    _engaging(monkeypatch, plan)
    applied_at = []
    approved = graph.approved

    def approving(state):
        update = approved(state)
        store = graph._store(state)
        scientific = graph.current_plan(state, store)
        _engagement_facts(store, scientific)
        view = engagement.apply(scientific, engagement.decide(store, {"plan": scientific}))
        update["plan"] = graph.install_applied_plan(store, update["plan"], view)
        applied_at.append(view)
        return update
    monkeypatch.setattr(graph, "approved", approving)
    sink = _ViewSink()
    with fakes.installed(authority=fakes.FakeAuthority({"go": ["pending", "go"]}), sink=sink) as svc:
        fakes.PLANS.append(plan)
        store, observation = fakes.drive_request(controller)
        assert [i["payload"]["authority_kind"] for i in observation["interrupts"]] == ["go"]
        before = fakes.final_state(store)["plan"]
        resumed = entry.open_for_resume(store.run_id, root=controller / "controller-store")
        observation = entry.drive(resumed, resume=True, gate_check=fakes.passing_gates,
                                  gate_providers=fakes.active_providers)
    values = fakes.final_state(resumed)
    [view] = applied_at
    assert before["sha256"] == values["plan"]["sha256"] == plan["sha256"]
    assert before["applied_sha256"] == values["plan"]["applied_sha256"] == view["engagement"]["applied_sha256"]
    # The applied steps go out under both identities; the check-ins after CHECK-IN 1 bind the applied view too.
    for step_id in ("w", "f"):
        sent, context = [(s, c) for s, c in fakes.PACKETS if s["id"] == step_id][0]
        assert sent == next(s for s in view["steps"] if s["id"] == step_id)
        assert context["plan_sha256"] == plan["sha256"] and context["applied_sha256"] == view["engagement"]["applied_sha256"]
    go = [c[2] for c in svc["authority"].calls if c[0] == "request" and c[1] == "go"][0]["view"]["pins"]
    assert go["plan_sha256"] == plan["sha256"] and go["applied_sha256"] == view["engagement"]["applied_sha256"]
    assert observation["terminal"] is None and sink.plans == [view]


# ---- route dispatch hooks: a site step runs inside the substrate's own invocation, never beside it ------------------

SITE_RECORD = "fixture-site"
SITE_ACTIVE: list = []  # the site steps whose dispatch is under way (the invocation records what it ran within)


def _site_dispatch(store, step, context, invoke):
    """A fictional site dispatcher (the binding interface's ``site.dispatch(store, step, context, invoke)``): it needs
    the step's exact approved jobscript pin and scope and the approved site budget, refuses before anything runs
    without them, reserves the cost durably, calls ``invoke`` once and keeps the outcome; a replay returns it."""
    pin = ((step.get("parameters") or {}).get("launch") or {}).get("jobscript")
    if type(pin) is not dict or set(pin) != {"path", "sha256"} or not (step.get("parameters") or {}).get("wms_scope"):
        raise ValueError("a site step needs its exact approved jobscript pin and scope")
    if type(context.get("site_budget")) not in (int, float) or step["budget"]["wall_seconds"] > context["site_budget"]:
        raise ValueError("a site step needs the approved site budget")
    done = [r["record"] for r in store.scan(SITE_RECORD) if r["record"]["step"] == step["id"]
            and r["record"]["event"] == "outcome"]
    if done:
        return deepcopy(done[-1]["outcome"])
    store.append(SITE_RECORD, {"event": "reserved", "step": step["id"], "cost": step["budget"]["wall_seconds"],
                               "ceiling": context["site_budget"], "plan_sha256": context["plan_sha256"]})
    SITE_ACTIVE.append(step["id"])
    try:
        outcome = invoke()
    finally:
        SITE_ACTIVE.remove(step["id"])
    store.append(SITE_RECORD, {"event": "outcome", "step": step["id"], "outcome": deepcopy(outcome)})
    return outcome


class _SiteAdapter:
    """A fictional route adapter with the two optional dispatch hooks."""

    def __init__(self):
        self.calls = []

    def packet_context(self, step, context):
        self.calls.append(("packet_context", step["id"], "store" in context))
        # JSON only; its run id must never replace the controller's own.
        return {"plan_route": context["plan"]["route"]["id"], "authority_subject": context["authority_subject"],
                "site_budget": context.get("site_budget"), "run_id": "a-route-supplied-run-id"}

    def dispatch(self, step, context, invoke):
        self.calls.append(("dispatch", step["id"]))
        if step["id"] != "operate":
            return invoke()
        return _site_dispatch(context["store"], step, context, invoke)


def _site_spec(jobscript=True):
    spec = deepcopy(next(s for s in fakes.route_specs() if s["id"] == "fixture-analysis"))
    spec["adapter"] = "fixture_adapter"
    launch = {"jobscript": {"path": "inputs/site/job.sh", "sha256": "a" * 64}} if jobscript else {}
    spec["steps"] = [fakes.make_step("operate", rung="smoke", budget={"wall_seconds": 100}, outputs=["outputs/site.json"],
                                     parameters={"launch": launch, "wms_scope": {"workflow_dir": "inputs/site"}}),
                     fakes.make_step("s1", kind="derive", depends_on=["operate"], outputs=["outputs/result.json"])]
    return spec


def _site_installed(monkeypatch, hooks):
    """Install the fictional adapter and record every substrate child invocation (``graph_nodes._invoke_child``):
    the step it ran, its child invocation path and the site dispatches under way when it ran."""
    module = types.ModuleType("ravel.controller.routes.fixture_adapter")
    module.packet_context, module.dispatch = hooks.packet_context, hooks.dispatch
    monkeypatch.setitem(sys.modules, "ravel.controller.routes.fixture_adapter", module)
    invocations = []
    real = graph_nodes._invoke_child

    def invoke_child(compiled, child_input, key):
        invocations.append({"step": (child_input.get("step") or {}).get("id"), "key": key, "site": list(SITE_ACTIVE),
                            "path": json.dumps((child_input.get("meta") or {}).get("path"), default=str)})
        return real(compiled, child_input, key)
    monkeypatch.setattr(graph_nodes, "_invoke_child", invoke_child)
    SITE_ACTIVE.clear()
    return invocations


def test_site_dispatch_intercepts_once_through_the_substrate(controller, monkeypatch):
    hooks = _SiteAdapter()
    invocations = _site_installed(monkeypatch, hooks)
    with routes.registered(_site_spec(), only=True), fakes.installed() as svc:
        store, observation = fakes.drive_request(controller, ANALYSIS_REQUEST)
    values = fakes.final_state(store)
    assert values["route"]["id"] == "fixture-analysis" and observation["terminal"] is None
    # The site step ran exactly once, inside the parent's own substrate invocation of its map item (its child path),
    # with the site dispatcher in the path; the other step went through the same hook and the same invocation.
    [site] = [i for i in invocations if i["step"] == "operate"]
    assert site["site"] == ["operate"] and site["key"] == "operate@1" and "operate@1" in site["path"]
    assert _dispatched().count("operate") == 1
    assert [i["site"] for i in invocations if i["step"] == "s1"] == [[]] and ("dispatch", "s1") in hooks.calls
    assert ("dispatch", "operate") in hooks.calls
    assert [r["record"]["event"] for r in store.scan(SITE_RECORD)] == ["reserved", "outcome"]
    # It appears in the graph's own records: the wave that ran it, with the step graph's receipt.
    ran = [r["record"]["steps"]["operate"] for r in store.scan("wave-result") if "operate" in r["record"]["steps"]]
    assert len(ran) == 1 and ran[0]["status"] == "completed" and ran[0]["receipts"] == ["fake-receipt-operate-1"]
    # The packet carries the route's JSON context beside the controller's own fields, which it never replaces.
    context = [c for s, c in fakes.PACKETS if s["id"] == "operate"][0]
    assert context["run_id"] == store.run_id and context["plan_route"] == "fixture-analysis"
    assert context["site_budget"] == 100 and context["authority_subject"]["view"]["pins"]["plan_sha256"]
    assert "store" not in context and ("packet_context", "operate", True) in hooks.calls


def test_a_site_step_without_its_jobscript_pin_holds_with_no_shared_step_effect(controller, monkeypatch):
    hooks = _SiteAdapter()
    invocations = _site_installed(monkeypatch, hooks)
    with routes.registered(_site_spec(jobscript=False), only=True), fakes.installed() as svc:
        store, observation = fakes.drive_request(controller, ANALYSIS_REQUEST)
    values = fakes.final_state(store)
    assert ("dispatch", "operate") in hooks.calls
    assert "operate" not in [i["step"] for i in invocations] and "operate" not in _dispatched()  # nothing ran
    assert store.scan(SITE_RECORD) == [] and "s1" not in _dispatched()
    assert values["steps"]["operate"]["status"] == "held"
    assert values["holds"]["operate"]["reason"] == "route_dispatch_refused"
    assert "jobscript" in values["holds"]["operate"]["would_make_possible"]
    assert observation["terminal"]["status"] == "qualified" and svc["sink"].calls[-1][0] == "bounded_end"



def test_no_step_is_admitted_while_the_route_is_not_pinned(controller):
    with fakes.installed():
        store, observation = fakes.drive_request(controller)
    values = fakes.final_state(store)
    plan = graph.current_plan(values, store)
    # The route record the selection pinned admits the ready steps; a state that names none of this run's route
    # records admits nothing, and says why.
    assert graph._admitted(values, store, plan, ["j1"], values["steps"]) == (["j1"], {}, {})
    unpinned = {**values, "route": {**values["route"], "record_id": "route-000099-0123456789ab"}}
    admitted, held, holds = graph._admitted(unpinned, store, plan, ["j1"], values["steps"])
    assert admitted == [] and held["j1"]["status"] == "held" and holds["j1"]["reason"] == "route_not_pinned"
    assert store.latest("admission")["record"] == {"held": ["j1"], "code": "route_not_pinned",
                                                   "reasons": {"j1": held["j1"]["reason"]}}
    assert held["j1"]["reason"].startswith("route_not_pinned:")


def test_a_checkin_gate_action_carries_the_view_pins_its_digest_commits_to():
    import hashlib
    from ravel.workflow import rdj_approval
    pins = {"plan_sha256": "a" * 64, "request_sha256": "b" * 64, "route": "analysis"}
    action = graph._gate_action("checkin1_gate", {"plan": {}}, pins)
    assert action["view_pins"] == pins and action["view_pins"] is not pins
    assert action["digest"] == hashlib.sha256(json.dumps(pins, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert rdj_approval.approved_plan(action) == "a" * 64


@pytest.mark.parametrize('label', ['qualified', 'diagnostic'])
def test_a_sink_refusal_reaches_the_bounded_task_ending(controller, label):
    class RefusingSink(fakes.FakeSink):
        def deliver(self, store, plan):
            receipt = super().deliver(store, plan)
            return {**receipt, 'accepted': False, 'qualified': True, 'label': label,
                    'work': {'current_refusals': [{'code': 'artifact_custody',
                                                   'message': 'the declared artifact has changed'}]}}

    with fakes.installed(sink=RefusingSink()) as services:
        store, observation = fakes.drive_request(controller)
    assert observation['terminal']['status'] == 'qualified'
    assert [call[0] for call in services['sink'].calls] == ['deliver', 'bounded_end']
    ending = services['sink'].calls[-1][1]
    assert 'sink_delivery_refused' in ending and 'artifact_custody' in ending
    assert fakes.final_state(store)['delivery']['qualified'] is True


@pytest.mark.parametrize('label', ['qualified', 'diagnostic'])
def test_a_delivery_withheld_only_by_unmet_obligations_stays_the_delivered_receipt(controller, label):
    """The sink refused nothing: unmet obligations alone withhold acceptance, so the run ends at its delivery."""
    class WithholdingSink(fakes.FakeSink):
        def deliver(self, store, plan):
            receipt = super().deliver(store, plan)
            return {**receipt, 'accepted': False, 'qualified': True, 'label': label,
                    'labels': [f'{label.upper()} DELIVERY'], 'work': {'current_refusals': []}}

    with fakes.installed(sink=WithholdingSink()) as services:
        store, observation = fakes.drive_request(controller)
    assert [call[0] for call in services['sink'].calls] == ['deliver']
    assert observation['terminal'] is None and observation['next'] == []
    delivery = fakes.final_state(store)['delivery']
    assert delivery['qualified'] is True and delivery['labels'] == [f'{label.upper()} DELIVERY']
