"""Authority consumers require retained evidence and current effect authorization."""
from copy import deepcopy
import json

import pytest

from ravel.controller import authority
from ravel.controller.authority import retained
from ravel.controller.judgment import graph, services
from test_p06_support import autonomous, frozen_store, operator_home  # noqa: F401


def material(store):
    plan = {"sha256": "a" * 64, "steps": ["derive the fictional quantity"],
            "deliverables": ["the derived result"], "boundaries": []}
    reading = {"request_pins": {}, "inferred_critical_facts": [], "flags": []}
    view = graph._view_subject(store, pins={"plan_sha256": plan["sha256"]},
                               summary="Derive a fictional quantity.",
                               items={key: plan[key] for key in ("steps", "deliverables", "boundaries")}, flags=[])
    view["flags"] = []
    return plan, reading, {"view": view}


def test_unattested_terminal_record_grants_nothing():
    record = {"id": "unattested", "kind": "approve_plan", "decision": "approve",
              "label": "terminal_operator_unattested", "authorizes_effects": False}
    result = services.normalize_authority(record)
    assert result["state"] == "pending"
    assert result["label"] == record["label"]


def test_request_without_retained_snapshot_stays_pending(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    _, _, subject = material(store)
    result = graph._authority(store, "approve_plan", subject)
    assert result["state"] == "pending"
    assert store.scan("authority") == []
    assert store.scan("authority-context") == []


def test_current_verified_record_grants_authority(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    plan, reading, subject = material(store)
    retained.capture(store, "approve_plan", plan=plan, reading=reading, view=subject["view"])
    result = graph._authority(store, "approve_plan", subject)
    assert result["state"] == "granted"
    record = authority.verify(store, result["record_id"], kind="approve_plan",
                              subject=subject["view"]["pins"])
    assert record["authorizes_effects"] is True


def test_request_captures_independent_sources_before_asking(operator_home, tmp_path, monkeypatch):
    autonomous()
    store = frozen_store(tmp_path)
    plan, reading, subject = material(store)
    original = deepcopy((plan, reading, subject))
    request = authority.request

    def ask(store, kind, subject, bounds):
        snapshot = retained.current(store, kind)
        assert snapshot["plan"] == plan
        assert snapshot["reading"] == {**reading, "items": {}}
        assert snapshot["view"] == subject["view"]
        return request(store, kind, subject, bounds)

    monkeypatch.setattr(authority, "request", ask)
    result = graph._authority(store, "approve_plan", subject, plan=plan, reading=reading)
    assert result["state"] == "granted"
    assert authority.verify(store, result["record_id"], kind="approve_plan")["authorizes_effects"] is True
    assert (plan, reading, subject) == original


@pytest.mark.parametrize("change", ["steps", "deliverables", "questions"])
def test_changed_view_is_refused_against_independent_sources(operator_home, tmp_path, change):
    autonomous()
    store = frozen_store(tmp_path)
    plan, reading, subject = material(store)
    reading["items"] = {"questions": ["Keep the supplied boundary?"]}
    subject["view"]["items"][change] = ["A different item."]
    result = graph._authority(store, "approve_plan", subject, plan=plan, reading=reading)
    assert result["state"] == "pending"
    assert store.scan("authority") == []
    assert retained.current(store, "approve_plan")["plan"] == plan
    assert retained.current(store, "approve_plan")["reading"]["items"]["questions"] == reading["items"]["questions"]


@pytest.mark.parametrize("missing", ["request_pins", "inferred_critical_facts", "flags"])
def test_incomplete_sources_cannot_reuse_an_earlier_approval(operator_home, tmp_path, missing):
    autonomous()
    store = frozen_store(tmp_path)
    plan, reading, subject = material(store)
    first = graph._authority(store, "approve_plan", subject, plan=plan, reading=reading)
    assert first["state"] == "granted"
    del reading[missing]
    result = graph._authority(store, "approve_plan", subject, plan=plan, reading=reading)
    assert result["state"] == "pending"
    assert len(store.scan("authority")) == 1


def test_missing_frozen_request_pins_cannot_be_inferred(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path, contract={"request_pins": {"statistic": "declared"}})
    plan, reading, subject = material(store)
    result = graph._authority(store, "approve_plan", subject, plan=plan, reading=reading)
    assert result["state"] == "pending"
    assert store.scan("authority") == []
    assert store.scan("authority-context") == []


@pytest.mark.parametrize("change", ["scope", "snapshot", "revoke"])
def test_approval_requires_current_verification(operator_home, tmp_path, change):
    autonomous()
    store = frozen_store(tmp_path)
    plan, reading, subject = material(store)
    retained.capture(store, "approve_plan", plan=plan, reading=reading, view=subject["view"])
    record = authority.request(store, "approve_plan", subject, {})
    pins = dict(subject["view"]["pins"])
    assert services.normalize_authority(record, store=store, kind="approve_plan", subject=pins)["state"] == "granted"
    if change == "scope":
        pins["plan_sha256"] = "b" * 64
    elif change == "snapshot":
        reading["flags"] = [{"kind": "risk", "text": "A newly disclosed uncertainty."}]
        retained.capture(store, "approve_plan", plan=plan, reading=reading, view=subject["view"])
    else:
        from ravel.controller.authority import stop
        stop.record_control(store, "revoke", label=authority.OPERATOR_COMMAND,
                            source="operator_cli", reason="Delegation withdrawn.", evidence={})
    assert services.normalize_authority(record, store=store, kind="approve_plan", subject=pins)["state"] == "pending"


def test_normalizer_uses_the_verified_record_bytes(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    plan, reading, subject = material(store)
    retained.capture(store, "approve_plan", plan=plan, reading=reading, view=subject["view"])
    record = authority.request(store, "approve_plan", subject, {})
    altered = {**record, "option": "a-different-option", "label": "a-different-label"}
    result = services.normalize_authority(altered, store=store, kind="approve_plan", subject=subject["view"]["pins"])
    assert result["state"] == "granted"
    assert result["answer"] == "approve"
    assert result["label"] == authority.MACHINE


@pytest.mark.parametrize("decision", ["approve", "answer", "go", "accept", "default"])
@pytest.mark.parametrize("authorizes", [False, None, 1, "true"])
def test_granting_words_without_explicit_effect_authorization_stay_pending(decision, authorizes):
    assert services.normalize_authority({"decision": decision, "authorizes_effects": authorizes})["state"] == "pending"


def test_poll_verifies_the_later_record(operator_home, tmp_path, monkeypatch):
    autonomous()
    store = frozen_store(tmp_path)
    plan, reading, subject = material(store)
    retained.capture(store, "approve_plan", plan=plan, reading=reading, view=subject["view"])
    record = authority.request(store, "approve_plan", subject, {})
    answers = iter([{"pending": {"wait_bound_seconds": 10}}, record])
    clock = {"now": 1.0}
    verified = []
    original = authority.verify

    def verify(store, record_id, **scope):
        verified.append(record_id)
        return original(store, record_id, **scope)

    def sleep(seconds):
        clock["now"] += seconds

    services.enable_local_seams()
    monkeypatch.setattr(authority, "verify", verify)
    with services.overridden(authority_request=lambda *args: next(answers), now=lambda: clock["now"], sleep=sleep):
        result = graph._authority(store, "approve_plan", subject, wait=True)
    assert result["state"] == "granted"
    assert verified == [record["id"]]


def test_pinned_inferred_facts_remain_in_the_retained_disclosure(monkeypatch):
    fact = {"id": "F1", "physics_critical": True, "authority": "inferred", "value": {"response": "unknown"}}
    source = {"facts": [fact], "request_pins": {"statistic": {"requested": "a", "planned": "b"}},
              "inferred_critical_facts": ["An existing disclosure."],
              "flags": [{"kind": "risk", "text": "A retained risk."}]}
    original = deepcopy(source)
    monkeypatch.setattr(graph, "_request", lambda state, store: {"reading": source})
    reading = graph._authority_reading({}, object())
    assert reading["inferred_critical_facts"] == ["An existing disclosure.", fact]
    assert reading["request_pins"] == source["request_pins"]
    assert reading["flags"] == source["flags"]
    assert source == original


@pytest.mark.parametrize("phase", ["checkin1", "deviation", "ask", "r3_action", "checkin3"])
def test_direct_nodes_capture_retained_sources_before_request(operator_home, tmp_path, monkeypatch, phase):
    autonomous()
    store = frozen_store(tmp_path)
    plan, reading, _ = material(store)
    sha = "b" * 64
    step = {"id": "question", "kind": "operate" if phase == "r3_action" else "ask",
            "purpose": "Resolve the supplied question.",
            "question": "Keep the boundary?", "options": [{"id": "hold", "description": "Keep it held."}]}
    compiled = {"sha256": sha, "steps": [step], "calls": {}}
    frame = {"assumptions": [], "boundaries": [{"id": "B1", "statement": "One supplied quantity only."}],
             "unknowns": []}
    view = {"compiled_history": {sha: compiled}, "plan_review": {}, "frame_accepted": {"findings": []},
            "checkin1": {sha: {"plan_sha256": plan["sha256"],
                                "authority": {"state": "granted", "record_id": "earlier-approval"}}},
            "adopted": sha, "steps": {}, "deviation": {}, "replan_request": {}, "flags": [],
            "final_review": {}, "checkin3": {}}
    state = {"context": {"run_id": store.run_id},
             "decision": {"detail": {"compiled_sha256": sha, "draft_sha256": sha,
                                       "asks": [{"step": "question", "subject_sha256": sha}]}}}
    monkeypatch.setattr(graph, "_store", lambda state: store)
    monkeypatch.setattr(graph, "_view", lambda store, state: view)
    monkeypatch.setattr(graph, "_request", lambda state, store: {"reading": reading})
    monkeypatch.setattr(graph, "_controller_plan", lambda *args: plan)
    monkeypatch.setattr(graph, "_frame_document", lambda *args: frame)
    monkeypatch.setattr(graph.control, "adopted_plan", lambda view: compiled)
    monkeypatch.setattr(graph.control, "draft", lambda view: {"sha256": sha, "deliverables": []})
    monkeypatch.setattr(graph.control, "append", lambda store, event: "retained-event")
    called = []
    original_request = authority.request

    def request(store, kind, subject, bounds):
        snapshot = retained.current(store, kind)
        assert snapshot["plan"] == plan
        assert snapshot["reading"]["request_pins"] == reading["request_pins"]
        assert snapshot["reading"]["inferred_critical_facts"] == reading["inferred_critical_facts"]
        assert snapshot["view"] == subject["view"]
        if kind == "approve_plan":
            assert any("One supplied quantity only." in f["text"] for f in snapshot["view"]["flags"])
            answer = original_request(store, kind, subject, bounds)
            assert authority.verify(store, answer["id"], kind=kind)["authorizes_effects"] is True
            called.append(kind)
            return answer
        called.append(kind)
        return {"pending": {"reason": "An authenticated answer is required."}}

    monkeypatch.setattr(authority, "request", request)
    getattr(graph, "ask" if phase == "r3_action" else phase)(state)
    assert called == [{"checkin1": "approve_plan", "deviation": "deviation", "ask": "escalation",
                       "r3_action": "r3_action", "checkin3": "final"}[phase]]


def test_structured_plan_capture_with_the_declared_renderer_interface(operator_home, tmp_path, monkeypatch):
    """A local renderer fake supplies the separately integrated structured-item contract."""
    from ravel.controller.authority import checkin
    autonomous()
    store = frozen_store(tmp_path)
    plan, reading, subject = material(store)
    plan["steps"] = [{"id": "derive", "kind": "derive"}]
    plan["deliverables"] = [{"id": "result", "status": "mapped"}]
    subject["view"]["items"] = {key: deepcopy(plan[key]) for key in ("steps", "deliverables", "boundaries")}
    render = checkin.render

    def structured_render(kind, view):
        displayed = deepcopy(view)
        displayed["items"] = {key: [json.dumps(row, sort_keys=True) if isinstance(row, dict) else row for row in rows]
                              for key, rows in view.get("items", {}).items()}
        return render(kind, displayed)

    monkeypatch.setattr(checkin, "render", structured_render)
    result = graph._authority(store, "approve_plan", subject, plan=plan, reading=reading)
    assert result["state"] == "granted"
    assert retained.current(store, "approve_plan")["plan"] == plan
    assert authority.verify(store, result["record_id"], kind="approve_plan")["authorizes_effects"] is True
    subject["view"]["items"]["deliverables"][0]["status"] = "open"
    assert graph._authority(store, "approve_plan", subject, plan=plan, reading=reading)["state"] == "pending"


def final_disposition(store, draft="d" * 64):
    """CHECK-IN 1, then the final check-in on its retained snapshot, both through the real authority."""
    from test_p06_support import view as checkin_view
    approval = authority.request(store, "approve_plan",
                                 {"view": checkin_view(store, "approve_plan", plan_sha256="a" * 64)}, {"rung": "full"})
    pins = {"approve_plan": approval["id"], "draft_sha256": draft}
    final = authority.request(store, "final", {"view": checkin_view(store, "final", **pins)}, {})
    assert final["decision"] == "accept" and final["authorizes_effects"] is False
    return final, pins


def test_final_acceptance_is_an_authenticated_disposition_that_grants_no_effect(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    final, pins = final_disposition(store)
    result = services.normalize_authority(final, store=store, kind="final", subject=pins)
    assert result["state"] == "accepted" and result["record_id"] == final["id"]
    assert result["answer"] == "accept" and result["label"] == authority.MACHINE
    assert result["state"] not in graph.control.GRANTED          # an accepted result authorizes no execution
    altered = {**final, "label": "a-different-label", "comment": "caller text"}
    assert services.normalize_authority(altered, store=store, kind="final", subject=pins)["label"] == authority.MACHINE


@pytest.mark.parametrize("change", ["pins", "superseded", "forged", "storeless"])
def test_final_acceptance_without_its_current_disposition_stays_pending(operator_home, tmp_path, change):
    from test_p06_support import view as checkin_view
    autonomous()
    store = frozen_store(tmp_path)
    final, pins = final_disposition(store)
    record, scope, target = final, dict(pins), store
    if change == "pins":
        scope["draft_sha256"] = "e" * 64
    elif change == "superseded":
        later = {**pins, "draft_sha256": "e" * 64}
        authority.request(store, "final", {"view": checkin_view(store, "final", **later)}, {})
    elif change == "forged":
        record = {**final, "id": "f" * 32}
    else:
        target = None
    result = services.normalize_authority(record, store=target, kind="final", subject=scope)
    assert result["state"] == "pending" and result["answer"] is None


def test_a_declining_conservative_default_is_authenticated_and_grants_no_effect(operator_home, tmp_path):
    from test_p06_support import view as checkin_view
    autonomous(r3_policy="conservative_default")
    store = frozen_store(tmp_path)
    pins = {"action_sha256": "f" * 64}
    record = authority.request(store, "r3_action", {"view": checkin_view(store, "r3_action", **pins),
                                                    "gate": "spend_above_ceiling", "conservative_default": "hold"}, {})
    assert record["decision"] == "default" and record["option"] == "hold" and record["authorizes_effects"] is False
    result = services.normalize_authority(record, store=store, kind="r3_action", subject=pins)
    assert result["state"] == "defaulted" and result["answer"] == "hold" and result["record_id"] == record["id"]
    assert graph.control.answer({**result, "subject_sha256": "s"}, "s", graph.control.AUTHORIZE) == "held"
    for scope, target in (({"action_sha256": "e" * 64}, store), (pins, None)):
        assert services.normalize_authority(record, store=target, kind="r3_action", subject=scope)["state"] == "pending"
    claimed = {**record, "option": graph.control.AUTHORIZE}           # the stored bytes decide, not the caller's
    assert services.normalize_authority(claimed, store=store, kind="r3_action", subject=pins)["answer"] == "hold"
