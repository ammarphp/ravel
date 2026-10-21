"""Engagement tiers by task complexity: facts pinned before the plan review, credited by it, decided at CHECK-IN 1.

Three requests of increasing complexity, each run through the controller graph to its end:

- a simple task (one deliverable of a fixed calculation route, no consequential choice, an adopted method that
  reuses a standard value) is computed **lean**;
- a medium task (the same, with a method whose single point is forecast at 500 core-hours) is computed **standard**;
- an ambiguous task (an open request the judgment graph plans) stays **full**, with the route fact as the only
  reason, on the real composition.

For each: the tier decision and every fact with its source and checker are rendered in the CHECK-IN 1 artifact the
authority decided on; the facts that needed review were pinned before the plan review and credited by its credited,
accepting plan critic; every seat that carries folded roles received their duties (the applied view's descriptor
and one reviewer item per folded duty), so EG04 is discharged from its verdicts; the floors hold; the run ends
honestly.

Where the runs execute:

- The lean and standard runs use the P01 interface harness (``fakes.py`` and ``test_p01_graph``'s fixtures). Faked:
  the ledger (``fakes.FakeLedger``), the sink (``fakes.FakeSink``), the instruction service handle
  (``fakes.FakeInstructions``), the judgment service (``test_p01_graph._FakeJudgment``), confinement
  (``fakes.FakeConfine``), the governed step graph and the judgment planning graph (``fakes.stand_in_graphs``), the
  decision gates (``fakes.passing_gates``) and the fixed route's spec (``fakes._spec``, registered under the installed
  route id ``calculation`` with one derive step, because the installed calculation route's prepare phase needs the
  study runtime's custody, which the stand-in step graph does not provide). Real: the controller graph, the authority
  service (``test_p01_graph.real_authority``), route selection and compilation over the registered spec, the
  engagement package with its installed policy, the role cards, the instruction catalogue and P03 manifests and
  packets, P04's binding of each derived seat to the applied view (``operations.plan_step``), and the CHECK-IN
  renderer and its retained snapshot. The fake ledger registers no gate hooks, so the engagement package is composed
  explicitly (``graph._engagement``); the stand-in step graph opens no worker sessions, so the wave envelope check has
  no usage to read and is not run in the positive runs (``test_a_floor_breach_holds_the_run`` keeps it and shows the
  hold).
- The ambiguous run is the wave-A gate's inert autonomous run (``test_composition_wave_a``): every service is the
  installed package and every seat a sandboxed inert worker session.

A fully composed lean or standard run needs an inert harness for a fixed route of tier rule lean (the calculation,
scoped or study route: their study runtime, prepare custody and review-point subgraphs) whose plan holds no R2/R3
step; the analysis route classifies its acquisition steps R3 and is therefore full by design.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

import fakes
from ravel.controller import graph, routes
from ravel.controller.store import RunStore
from test_p01_graph import _accept_final, _p04_review_seat_admission, controller, real_authority  # noqa: F401
from test_p18_execution import _fold, _outcome, _step, lean  # noqa: F401

FIXTURES = Path(__file__).parents[2] / "fixtures"
SIMPLE = b"Calculate the yield of a fictional widget process in a toy model and report the value with its uncertainty."
FACT_NAMES = ("route", "deliverables", "consequence", "compute", "novelty", "special")


# ---- the operator-supplied method decision and the fixed route ------------------------------------------------------

def method_decision(request, *, cpu_hours=0.5):
    """The adopted method decision for ``request``: the fictional standard-value method, its forecast core-hours."""
    method = json.loads((FIXTURES / "method_decisions" / "standard_table.json").read_text())
    method["request_digest"] = hashlib.sha256(request).hexdigest()
    method["cost_forecast"]["cpu_hours"] = cpu_hours
    return method


def supplied_method(directory, method):
    """The supplied-input rows of ``method`` written as ``method-decision.json`` (intake stages it by digest)."""
    from ravel.controller import entry
    path = Path(directory) / "operator-inputs" / graph.METHOD_INPUT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(method, indent=1))
    return entry._supplied([str(path)], directory)


def calculation_spec():
    """A fictional one-step spec under the installed route id ``calculation`` (start-table row 7)."""
    return fakes._spec("calculation", 7, {"field": "task_mode", "eq": "calculation"},
                       [fakes.make_step("s1", kind="derive", outputs=["outputs/result.json"])],
                       [{"match": {"any": True}, "step": "s1", "output": "outputs/result.json"}])


def _drive_tier(controller, authority, capfd, monkeypatch, *, method=None, envelope=False, credit=True):
    """One controller run of the simple calculation request; returns ``(store, observation, admitted, svc)``."""
    monkeypatch.setattr(graph, "_engagement", graph._engagement_package)
    if not envelope:
        monkeypatch.setattr(graph, "envelope_wave", lambda state, store: (None, []))
    if not credit:
        monkeypatch.setattr(graph, "credit_engagement_facts", lambda *args: [])
    real_step, admitted = fakes.step_run, []

    def admitted_step(store, step, context):
        outcome = real_step(store, step, context)
        return _p04_review_seat_admission(store, step, context, admitted) or outcome
    monkeypatch.setattr(fakes, "step_run", admitted_step)
    supplied = supplied_method(controller, method) if method is not None else ()
    with routes.registered(calculation_spec(), only=True), fakes.installed(authority=authority) as svc:
        store, observation = fakes.drive_request(controller, SIMPLE, unattended=False, supplied=supplied)
        if observation.get("interrupts"):
            observation = _accept_final(store, observation, capfd)
    return store, observation, admitted, svc


def _decision(store):
    rows = store.scan("engagement-decision")
    assert rows, "no engagement decision was recorded"
    return rows[-1]["record"]


def _engagement_lines(store):
    """The engagement section of the CHECK-IN 1 view the authority captured and decided on."""
    from ravel.controller.authority import retained
    view = retained.current(store, "approve_plan")["view"]
    [section] = [s for s in view["sections"] if s["id"] == "engagement"]
    return section["lines"]


def _assert_rendered(store, tier):
    """The tier decision and its facts, each with its source and checker, are in the CHECK-IN 1 artifact."""
    decision = _decision(store)
    lines = _engagement_lines(store)
    assert lines[0].startswith(f"Tier {tier}: computed {decision['computed_tier']} by code"), lines[0]
    for reason in decision["reasons"]:
        shown = f"Fact {reason['fact']}: {json.dumps(reason['value'], sort_keys=True)[:160]} (source {reason['source']}"
        assert any(line.startswith(shown) for line in lines), (shown, lines)
    return lines


def _assert_credited(store):
    """The method and novelty facts were pinned before the plan review and credited by its accepting plan critic."""
    pinned, credited = [r["record"] for r in store.scan(graph.ENGAGEMENT_FACTS)][-2:]
    assert pinned["event"] == "pinned" and credited["event"] == "credited", (pinned, credited)
    review = store.read("review", credited["review"])["record"]
    assert review["purpose"] == "plan" and review["seats"]["plan-critic"]["credited"] is True
    assert review["seats"]["plan-critic"]["verdict"] == "accept"
    assert sorted(review["engagement_fact_sha256s"]) == sorted(i["subject_sha256"] for i in pinned["items"])
    assert {i["id"] for i in pinned["items"]} == {"engagement-method", "engagement-novelty"}
    credits = [r for r in store.scan("engagement-fact-credit") if r["id"] in credited["credited"]]
    assert len(credits) == 2 and all(r["record"]["review_record_id"] == credited["review"] for r in credits)
    # The pins precede the review the plan critic credited them in; the review's seat received each fact.
    seq = {r["id"]: r["seq"] for r in store.scan("engagement-method") + store.scan("engagement-novelty")}
    review_seq = next(r["seq"] for r in store.scan("review") if r["id"] == credited["review"])
    assert all(seq[i["record_id"]] < review_seq for i in pinned["items"])
    plan_seat = next((s for s, _ in fakes.PACKETS if s["id"] == "plan_review"), None)
    if plan_seat is not None:
        delivered = {i.get("subject_sha256") for i in plan_seat["parameters"].get("review_items") or ()}
        assert {i["subject_sha256"] for i in pinned["items"]} <= delivered


def _folded_seats(store):
    """The derived check-in seats the stand-in step graph received carrying folded roles (by descriptor reference)."""
    return [s for s, _ in fakes.PACKETS if (s.get("parameters") or {}).get("engagement_seat_ref")]


def _descriptor(store, step):
    """The applied view's descriptor a derived seat names, as P04 resolves it."""
    from ravel.controller.step import operations
    return operations.referenced_seat(graph.current_plan(fakes.final_state(store), store), step)


def _assert_folded_duties_delivered(store, admitted, expected_roles):
    """Each seat that carries folded roles received its applied-view descriptor and one reviewer item per duty; P04
    bound it to the view; its real P03 packet carries every item; EG04 is discharged by a verdict on each delivered
    item, and the same seat without the descriptor would have been the old violation."""
    from ravel.controller import instructions
    from ravel.controller.step import graph as step_graph
    plan = graph.current_plan(fakes.final_state(store), store)
    seats = _folded_seats(store)
    assert seats, "no derived check-in seat carried folded duties"
    roles = set()
    for step in seats:
        descriptor = _descriptor(store, step)
        assert descriptor in plan["engagement"]["seat_plan"]["seats"]  # exactly the applied view's descriptor
        assert step["parameters"]["engagement_seat_ref"] == {"key": descriptor["key"],
                                                             "sha256": graph._digest(descriptor)}
        assert step["parameters"]["reviewer_items"] == descriptor["items"]
        assert step["engagement"] == descriptor["step"]["engagement"]
        roles |= set(descriptor["folded_roles"])
        assert any(s["id"] == step["id"] and s["role"] == step["role"] for s, _ in admitted), step["id"]
        card = graph._card(step["role"])
        manifest = instructions.manifest(step, card)
        packet = instructions.packet(manifest, card, step, [])
        assert instructions.check_packet(packet, manifest, card, step, []) == []
        assert all(item["id"] in packet["text"] for item in descriptor["items"])
        response = {"item_verdicts": [{"item": i["id"], "verdict": "pass", "evidence": ["final_record#/kind"]}
                                      for i in step["parameters"]["reviewer_items"]]}
        problems = instructions.check_item_verdicts(descriptor["items"], response)
        row = step_graph._fold_row(descriptor, credit_id="step-credit-fixture", credited=True, problems=problems)
        assert row["status"] == "satisfied" and row["evidence"]["folded_roles"] == descriptor["folded_roles"], row
        undelivered = step_graph._fold_row(None, credit_id="step-credit-fixture", credited=True, problems=[],
                                           declared=descriptor["folded_roles"])
        assert undelivered["evidence"]["reason"].startswith("folded_duties_not_delivered:")
    assert roles >= set(expected_roles), roles
    return seats


def _assert_floors(store, svc, decision, seats):
    """The fixed floors on the run: plan review (F2), claim review by a fresh distinct verifier (F1), three written
    and tested attacks before the verdict, carried or declared (F3), consequence classes from code (F4), authority
    labels (F11), the fold's constraint union (F12) and the sole sink (F6)."""
    from ravel.controller import authority
    plan = graph.current_plan(fakes.final_state(store), store)
    seat_plan = plan["engagement"]["seat_plan"]
    plan_review = next(r["record"] for r in store.scan("review") if r["record"]["purpose"] == "plan")
    assert plan_review["seats"]["plan-critic"] == {**plan_review["seats"]["plan-critic"], "credited": True,
                                                   "verdict": "accept"}
    assert "checkin:checkin1:plan-critic" in {s["key"] for s in seat_plan["seats"]}
    verifier = next(s for s in seat_plan["seats"] if s["key"] == seat_plan["claim_coverage"]["D1"])
    assert {"id": "claim:D1", "kind": "claim", "claim_id": "D1"} in verifier["items"]
    assert verifier["constraints"]["fresh_session"] is True
    attack = next(s for s in seat_plan["seats"] if s.get("attacks_required"))
    assert attack["attacks_required"] == 3 and attack["attacks_before_verdict"] is True
    assert [i["id"] for i in attack["items"] if i.get("kind") == "attack"] == ["attack:1", "attack:2", "attack:3"]
    assert decision["facts"]["consequence"]["checker"] == "code:classify"
    approvals = [r for r in authority.records(store) if r["kind"] == "approve_plan"]
    assert approvals and approvals[-1]["label"] == "operator_configured_machine"
    assert all("human" not in str(r.get("label")) for r in authority.records(store))
    for step in seats:
        descriptor = _descriptor(store, step)
        for folded in descriptor["folded_cards"]:
            for name in ("forbidden_inputs", "required_inputs"):
                assert set((folded.get("sees") or {}).get(name) or ()) <= set(descriptor["constraints"][name])
    assert svc["sink"].calls[-1][0] == "deliver"


def _assert_honest_end(store, observation):
    """The run delivered through the sink; the engagement receipt accepts nothing without usage evidence."""
    from ravel.controller import engagement
    assert observation["terminal"] is None, observation
    section = engagement.receipt_section(store)
    assert section["accepted_allowed"] is False and "USAGE UNKNOWN" in section["labels"], section
    assert section["tier"] == _decision(store)["tier"]


# ---- the three requests ---------------------------------------------------------------------------------------------

def test_a_simple_task_is_computed_lean(controller, real_authority, capfd, monkeypatch):
    store, observation, admitted, svc = _drive_tier(controller, real_authority, capfd, monkeypatch,
                                                    method=method_decision(SIMPLE))
    decision = _decision(store)
    assert decision["computed_tier"] == decision["tier"] == "lean", decision["reasons"]
    assert {r["fact"]: r["minimum_tier"] for r in decision["reasons"]} == {name: "lean" for name in FACT_NAMES}
    assert all(decision["facts"][name]["checker"].startswith("code") for name in FACT_NAMES)
    assert decision["facts"]["compute"]["value"] == "C0" and decision["facts"]["novelty"]["value"] == "N0"
    _assert_credited(store)
    lines = _assert_rendered(store, "lean")
    assert any(line.startswith("Plan critic credit (review ") and "2 fact(s) credited" in line for line in lines)
    # At lean the final verifier carries the other CHECK-IN 3 critic, the P8 attack seat and the integrity seat.
    seats = _assert_folded_duties_delivered(store, admitted, {"physics-critic", "integrity-auditor"})
    assert {s["role"] for s in seats} == {"skeptical-verifier"}
    verifier = _descriptor(store, seats[0])
    assert verifier["attacks_required"] == 3 and verifier["constraints"]["fresh_session"] is True
    _assert_floors(store, svc, decision, seats)
    _assert_honest_end(store, observation)
    _assert_reference_refusals(store, seats[0], monkeypatch)


def _assert_reference_refusals(store, step, monkeypatch):
    """P04 resolves a referenced descriptor only from the pinned applied view and only with its exact duties: a
    dropped item, a changed packet engagement, another digest or both forms at once hold the seat."""
    from ravel.controller.step import graph as step_graph, operations
    from ravel.controller.step.services import StepHold
    plan = graph.current_plan(fakes.final_state(store), store)
    descriptor = operations.referenced_seat(plan, step)
    monkeypatch.setattr(operations, "current_plan", lambda store_, context: deepcopy(plan))
    monkeypatch.setattr(step_graph, "_store", lambda state: store)
    assert step_graph._declared_descriptor({"acting": step, "context": {}}) == descriptor
    assert step_graph._declared_descriptor({"acting": {**step, "parameters": {}}, "context": {}}) is None
    tampered = []
    for change in ("items", "engagement", "digest", "both"):
        bad = deepcopy(step)
        if change == "items":
            bad["parameters"]["reviewer_items"] = bad["parameters"]["reviewer_items"][1:]
        elif change == "engagement":
            bad["engagement"]["items"] = bad["engagement"]["items"][1:]
        elif change == "digest":
            bad["parameters"]["engagement_seat_ref"]["sha256"] = "0" * 64
        else:
            bad["parameters"]["engagement_seat"] = descriptor
        with pytest.raises(StepHold) as held:
            operations.plan_step(store, bad, {"plan_sha256": plan["sha256"], "plan": plan})
        tampered.append(held.value.reason)
    assert tampered == ["engagement_view_invalid"] * 4, tampered


def test_a_medium_task_is_computed_standard(controller, real_authority, capfd, monkeypatch):
    store, observation, admitted, svc = _drive_tier(controller, real_authority, capfd, monkeypatch,
                                                    method=method_decision(SIMPLE, cpu_hours=500))
    decision = _decision(store)
    assert decision["computed_tier"] == decision["tier"] == "standard", decision["reasons"]
    minima = {r["fact"]: r["minimum_tier"] for r in decision["reasons"]}
    assert minima == {**{name: "lean" for name in FACT_NAMES}, "compute": "standard"}, minima
    assert decision["facts"]["compute"]["value"] == "C2"
    _assert_credited(store)
    _assert_rendered(store, "standard")
    # At standard the final verifier carries the CHECK-IN 3 critic's duties; the decider is conditional on a
    # disagreement and the attack floor stays a separate seat.
    seats = _assert_folded_duties_delivered(store, admitted, {"physics-critic"})
    seat_plan = graph.current_plan(fakes.final_state(store), store)["engagement"]["seat_plan"]
    assert any(s.get("conditional") == "attacker_verifier_disagree" for s in seat_plan["seats"])
    _assert_floors(store, svc, decision, seats)
    _assert_honest_end(store, observation)


@pytest.fixture
def ambiguous(tmp_path, monkeypatch):
    """The wave-A gate's inert autonomous run of its open request, with an adopted method decision supplied."""
    import test_composition_wave_a as wave_a
    from ravel.controller import entry
    method = method_decision(wave_a.REQUEST)
    path = tmp_path / "operator-inputs" / graph.METHOD_INPUT
    path.parent.mkdir()
    path.write_text(json.dumps(method, indent=1))
    real_start = entry.start

    # Unclassified supplied bytes are restricted, and restricted or internal bytes reach a CLI worker only through an
    # endpoint-confined gateway. The operator classifies the fictional method decision public and admits only the
    # inert worker transport for it, as the wave-A gate's own run (no supplied bytes) dispatches that worker.
    classified = {"level": "public", "allowed_providers": [{"transport_id": wave_a.TRANSPORT,
                                                            "account_class": "login:subscription"}]}

    def start(request, **options):
        options.setdefault("supplied", entry._supplied([str(path)], tmp_path, data_classification=classified))
        return real_start(request, **options)
    monkeypatch.setattr(entry, "start", start)
    yield from wave_a._drive(tmp_path, monkeypatch, wave_a.REQUEST)


def test_an_ambiguous_task_stays_full_on_the_real_composition(ambiguous):
    import test_composition_wave_a as wave_a
    store, summary = ambiguous
    wave_a._assert_milestones(store, summary)
    decision = _decision(store)
    assert decision["computed_tier"] == decision["tier"] == "full", decision["reasons"]
    minima = {r["fact"]: r["minimum_tier"] for r in decision["reasons"]}
    # The route fact is the only reason for full: every other fact is known and reviewed.
    assert [name for name, tier in minima.items() if tier == "full"] == ["route"], minima
    assert decision["facts"]["route"]["value"] == "judgment.open"
    assert decision["facts"]["compute"] == {**decision["facts"]["compute"], "value": "C0",
                                            "checker": "code+plan-critic"}
    assert decision["facts"]["novelty"]["value"] == "N1" and minima["novelty"] == "standard"
    assert all(decision["facts"][name]["checker"].startswith("code") for name in FACT_NAMES)
    pinned, credited = [r["record"] for r in store.scan(graph.ENGAGEMENT_FACTS)][-2:]
    assert len(credited["credited"]) == 2 and pinned["refused"] == [], (pinned, credited)
    review = store.read("review", credited["review"])["record"]
    assert review["seats"]["plan-critic"]["credited"] is True and review["seats"]["plan-critic"]["verdict"] == "accept"
    lines = _assert_rendered(store, "full")
    assert any("2 fact(s) credited" in line for line in lines), lines
    # At full every declared seat is separate: nothing is folded and no EG04 row is violated.
    eg04 = wave_a._instances(store, "EG04")
    assert eg04 and all(i.status != "violated" for i in eg04), [(i.status, i.evidence) for i in eg04]
    wave_a._assert_derived_and_verified(store)
    wave_a._assert_final_review(store, summary)


# ---- negatives ------------------------------------------------------------------------------------------------------

def test_unpinned_facts_keep_full(controller, real_authority, capfd, monkeypatch):
    """No adopted method: the compute fact is never pinned, stays unknown and keeps the run full; the CHECK-IN 1
    artifact says which fact was not pinned and why."""
    store, observation, _, _ = _drive_tier(controller, real_authority, capfd, monkeypatch)
    decision = _decision(store)
    assert decision["tier"] == "full" and decision["facts"]["compute"]["source"] == "missing"
    assert {r["fact"]: r["rule"] for r in decision["reasons"]}["compute"] == "unknown-means-complex"
    lines = _assert_rendered(store, "full")
    assert any("not pinned: compute (method_decision_not_supplied)" in line for line in lines), lines
    assert not _folded_seats(store)
    assert observation["terminal"] is None


def test_pinned_but_uncredited_facts_keep_full(controller, real_authority, capfd, monkeypatch):
    """Facts pinned before the plan review but never credited by it count for nothing."""
    store, _, _, _ = _drive_tier(controller, real_authority, capfd, monkeypatch, method=method_decision(SIMPLE),
                                 credit=False)
    assert store.scan("engagement-method") and store.scan("engagement-novelty")
    assert store.scan("engagement-fact-credit") == []
    decision = _decision(store)
    assert decision["tier"] == "full"
    assert {r["fact"]: r["minimum_tier"] for r in decision["reasons"]}["compute"] == "full"
    assert any(line.startswith("Plan critic credit: none recorded") for line in _engagement_lines(store))


def test_a_review_that_covers_no_fact_credits_none(controller, real_authority, capfd, monkeypatch):
    """The credit binds the review record's own list of delivered fact digests: a review of the same plan that
    names none, or whose plan critic did not accept, credits nothing."""
    from ravel.controller.engagement import facts
    store, _, _, _ = _drive_tier(controller, real_authority, capfd, monkeypatch, method=method_decision(SIMPLE))
    plan = _decision(store)["scientific_plan"]
    credited = store.read("review", [r["record"] for r in store.scan(graph.ENGAGEMENT_FACTS)][-1]["review"])
    record = deepcopy(credited["record"])
    silent = store.append("review", {k: v for k, v in record.items() if k != "engagement_fact_sha256s"})
    assert facts.credit_reviewed_facts(store, plan, silent) == []
    revising = deepcopy(record)
    revising["seats"]["plan-critic"]["verdict"] = "revise"
    assert facts.credit_reviewed_facts(store, plan, store.append("review", revising)) == []


def _facts_state(tmp_path, request=SIMPLE):
    """A run store with one intake record and its run directory, for the adopted-method reader."""
    store = RunStore("run-tiers-facts", root=tmp_path / "store")
    run_dir = tmp_path / "run"
    (run_dir / "inputs").mkdir(parents=True)
    state = {"run": {"run_id": store.run_id, "store_root": str(tmp_path / "store"), "run_dir": str(run_dir)}}

    def intake(supplied):
        record = {"contract_blob": store.put_blob(b"{}"), "reading_blob": store.put_blob(b"{}"),
                  "request_sha256": hashlib.sha256(request).hexdigest(), "supplied": supplied}
        state["request"] = {"intake_record_id": store.append("intake", record)}
        return state
    return store, run_dir, intake


def test_a_worker_written_or_foreign_method_never_lowers(tmp_path):
    """Only the method decision intake staged from the operator's supplied bytes is adopted: a run-tree file nobody
    supplied (a worker can write one), changed staged bytes, a decision for another request and an invalid decision
    are each refused with a typed reason, so the compute fact stays unknown (full)."""
    store, run_dir, intake = _facts_state(tmp_path)
    good = json.dumps(method_decision(SIMPLE)).encode()
    (run_dir / "inputs" / graph.METHOD_INPUT).write_bytes(good)
    assert graph.adopted_method(intake([]), store) == (None, "method_decision_not_supplied")
    row = {"name": graph.METHOD_INPUT, "artifact": "inputs/" + graph.METHOD_INPUT,
           "sha256": hashlib.sha256(good).hexdigest(), "source": "operator"}
    method, reason = graph.adopted_method(intake([row]), store)
    assert reason is None and method == json.loads(good)
    (run_dir / "inputs" / graph.METHOD_INPUT).write_bytes(good.replace(b"0.5", b"0.25"))
    assert graph.adopted_method(intake([row]), store) == (None, "method_decision_changed")
    for changed, expected in ((method_decision(b"another fictional request"), "method_decision_other_request"),
                              ({**method_decision(SIMPLE), "family": "no-such-family"}, "method_decision_invalid")):
        raw = json.dumps(changed).encode()
        (run_dir / "inputs" / graph.METHOD_INPUT).write_bytes(raw)
        staged = {**row, "sha256": hashlib.sha256(raw).hexdigest()}
        assert graph.adopted_method(intake([staged]), store) == (None, expected)


def test_novelty_is_derived_from_the_route_never_asserted():
    plan = {"route": {"id": "judgment"}}
    assert graph.plan_novelty(plan) == ("N1", None)
    spec = routes.find("calculation")
    from ravel.controller.routes.select import spec_sha256
    assert graph.plan_novelty({"route": {"id": "calculation", "spec_sha256": spec_sha256(spec)}}) == ("N0", None)
    assert graph.plan_novelty({"route": {"id": "calculation", "spec_sha256": "0" * 64}}) == (None, "route_spec_unpinned")
    assert graph.plan_novelty({"route": {"id": "calculation", "novelty": "N0"}}) == (None, "route_spec_unpinned")
    assert graph.plan_novelty({"route": {"id": "fictional-uninstalled"}})[1] == "route_spec_not_installed"


def test_full_tier_delivers_no_fold_descriptor():
    """A derived seat carries a descriptor only when the applied view folds roles into it (never at full)."""
    seat = {"key": "checkin:checkin3:skeptical-verifier", "role": "skeptical-verifier", "category": "checkin3",
            "conditional": None, "folded_roles": [], "items": [], "step": {"engagement": {}}}
    plan = {"sha256": "a" * 64, "engagement": {"seat_plan": {"seats": [seat]}}}
    assert graph.declared_seat(plan, "skeptical-verifier", "final") is None
    folded = {**seat, "folded_roles": ["physics-critic"]}
    assert graph.declared_seat({**plan, "engagement": {"seat_plan": {"seats": [folded]}}},
                               "skeptical-verifier", "final") == folded
    # Two unconditional descriptors of one role and category are ambiguous: none is delivered (EG04 then violated).
    twice = {"seat_plan": {"seats": [folded, {**folded, "key": "floor:claims:1"}]}}
    assert graph.declared_seat({**plan, "engagement": twice}, "skeptical-verifier", "final") is None


def test_a_floor_breach_holds_the_run(controller, real_authority, capfd, monkeypatch):
    """With the envelope check kept, the stand-in step graph's dispatches have no session evidence: the structural
    floor H1 fails at the first wave join, engagement escalates and the run holds with the typed reason."""
    store, observation, _, _ = _drive_tier(controller, real_authority, capfd, monkeypatch,
                                           method=method_decision(SIMPLE), envelope=True)
    assert _decision(store)["tier"] == "lean"
    assert observation["terminal"]["status"] == "qualified"
    assert observation["terminal"]["reason"].startswith(graph.ENGAGEMENT_HOLD), observation["terminal"]
    raised = [r["record"] for r in store.scan("engagement-escalation")]
    assert raised and "E4" in raised[-1]["triggers"] and raised[-1]["new_tier"] == "standard"


def test_an_undischarged_rereview_withholds_acceptance(lean):
    """EG05 at accepted delivery: an escalation that requires a re-review withholds acceptance, typed, until a later
    credited review of its subject (with every seat it added) discharges it; a run-level one needs a later accepted
    final review."""
    from ravel.controller import engagement
    review = {"credited": True, "verdict": "revise", "seats": [{"seat": "seat:physics-critic:1", "credited": True,
                                                                "verdict": "revise"}], "findings": []}
    _, _, raised = _fold(lean, _step("s1"), _outcome("s1", review=review))
    assert raised and raised[0]["rereview"] is True
    rows = [r for r in engagement.gate_errors(lean.store, "deliver[accepted]") if r["row"] == "EG05"]
    assert [r["reason"] for r in rows] == [f"rereview_undischarged:{raised[0]['record_id']}:s1"]
    # A credited review of another step, or an uncredited one of this step, discharges nothing.
    lean.store.append("step-credit", {"step_id": "s2", "credited": True, "seats": [], "own": None})
    lean.store.append("step-credit", {"step_id": "s1", "credited": False, "seats": [], "own": None})
    assert [r["row"] for r in engagement.rereview_errors(lean.store)] == ["EG05"]
    needed = sorted({s["role"] for s in raised[0]["seats_added"] if s["step_id"] == "s1"})
    lean.store.append("step-credit", {"step_id": "s1", "credited": True, "own": None,
                                      "seats": [{"role": role, "credited": True} for role in needed]})
    assert engagement.rereview_errors(lean.store) == []
    # A run-level re-review (no step) is discharged only by a later final review whose every seat accepted.
    lean.store.append("engagement-escalation", {**{k: v for k, v in raised[0].items() if k != "record_id"},
                                                "step_id": None, "event_sha256": "c" * 64})
    assert [r["reason"].rsplit(":", 1)[-1] for r in engagement.rereview_errors(lean.store)] == ["run"]
    lean.store.append("review", {"purpose": "final", "seats": {"skeptical-verifier": {"credited": True,
                                                                                    "verdict": "revise"}}})
    assert engagement.rereview_errors(lean.store)
    lean.store.append("review", {"purpose": "final", "seats": {"skeptical-verifier": {"credited": True,
                                                                                    "verdict": "accept"}}})
    assert engagement.rereview_errors(lean.store) == []
