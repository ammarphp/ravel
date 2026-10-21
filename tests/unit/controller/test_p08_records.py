"""Judgment records and protocol evidence (JR05, JR06, A05, C01, C08, E03, E12, E28, JR09)."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ravel.controller.judgment import protocols, records
from test_p08_fakes import RUN_ID, Store, p7, record

METHODS = Path(__file__).resolve().parents[2] / "fixtures/method_decisions"


@pytest.fixture
def store(tmp_path):
    return Store(RUN_ID, root=tmp_path / "store", run_dir=tmp_path / "run")


def decide(step_id="choose", **extra):
    return {"id": step_id, "kind": "decide", "protocols": ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"],
            "triggers": [], **extra}


def test_JR05_a_valid_record_is_stored_with_the_controller_class(store):
    identifier = records.record_judgment(store, record("choose"), step=decide())
    stored = records.for_step(store, "choose")
    assert len(stored) == 1 and stored[0]["judgment_id"] == identifier
    assert stored[0]["class"] == "R1" and stored[0]["reviewer_requirement"] == "report_at_next_checkin"
    assert stored[0]["outcome"] == "pending" and records.by_digest(store, stored[0]["record_sha256"]) is not None


@pytest.mark.parametrize("mutate, expected", [
    (lambda r: r.pop("options"), "options"),
    (lambda r: r.update(options=r["options"][:1]), "at least two options"),
    (lambda r: r.update(chosen="z"), "chosen option"),
    (lambda r: r.update(rationale=""), "rationale"),
    (lambda r: r.pop("reversibility"), "reversibility"),
    (lambda r: r.update(step="another"), "names step"),
])
def test_JR05_decision_without_a_valid_record_is_refused(store, mutate, expected):
    body = record("choose")
    mutate(body)
    with pytest.raises(records.JudgmentRecordError) as raised:
        records.record_judgment(store, body, step=decide())
    assert any(expected in e for e in raised.value.errors)
    assert records.for_step(store, "choose") == []


def test_JR05_single_option_needs_its_reason(store):
    body = record("choose", options=1)
    assert records.check_record(body, step=decide()) == []
    body.pop("single_option_reason")
    assert any("two options" in e for e in records.check_record(body, step=decide()))


def test_JR06_worker_class_is_replaced_and_A05_recomputed_upward(store):
    body = record("choose", kind="physics_critical_ambiguity", declared="R1")
    body["class"] = "R1"
    records.record_judgment(store, body, step=decide())
    stored = records.for_step(store, "choose")[-1]
    assert stored["class"] == "R3" and stored["reviewer_requirement"] == "authority"
    assert stored["class_factors"]["supplied_class"] == "R1" and stored["class_factors"]["recomputed"] is True
    assert stored["class_factors"]["declared_lower"] is True


def test_JR06_plan_class_and_irreversibility_raise_the_record_class(store):
    records.record_judgment(store, record("a"), step=decide("a"), plan_class="R2")
    records.record_judgment(store, record("b", reversibility="irreversible"), step=decide("b"))
    assert records.for_step(store, "a")[-1]["class"] == "R2"
    assert records.for_step(store, "b")[-1]["class"] == "R3"


def test_E28_judgment_step_without_its_protocol_evidence_is_refused(store):
    body = record("choose", triggers=["compare"])
    problems = records.check_record(body, step=decide())
    assert any("missing P2 evidence" in p for p in problems)
    with pytest.raises(records.JudgmentRecordError):
        records.record_judgment(store, body, step=decide())


def test_E28_judgment_step_must_receive_the_protocol_units_its_triggers_name():
    body = record("choose", triggers=["compare"], evidence={"P2": p2()})
    assert records.check_record(body, step=decide()) == []
    assert any("instruction units" in p for p in records.check_record(body, step=decide(protocols=["P1"])))


def p2(**override):
    side = {"states_summed": "both charges", "order": "next-to-leading", "pdf": "a fictional set",
            "sample": "inclusive", "column": "expected", "channel": "combined", "normalization": "model rate"}
    value = {"manifests": [{"side": "produced", **side}, {"side": "published", **side}],
             "transformation": {"applied_to": None, "description": "none needed", "result": None},
             "identity_check": {"kind": "ratio on the reference curve", "expected": 1.0, "measured": 1.04,
                                "tolerance": 0.1}}
    value.update(override)
    return value


def test_E28_P2_refuses_a_comparison_until_the_manifests_match():
    assert protocols.check("P2", p2()) == []
    mismatched = p2()
    mismatched["manifests"][1]["sample"] = "tagged"
    assert any("still differ" in p for p in protocols.check("P2", mismatched))
    transformed = deepcopy(mismatched)
    transformed["transformation"] = {"applied_to": 1, "description": "rescale to the inclusive sample",
                                     "result": {**transformed["manifests"][1], "sample": "inclusive"}}
    assert protocols.check("P2", transformed) == []
    assert any("identity check fails" in p for p in protocols.check("P2", p2(identity_check={
        "kind": "ratio", "expected": 1.0, "measured": 1.5, "tolerance": 0.1})))


def ladder(statuses):
    names = {1: "publication", 2: "data_record", 3: "public_code", 4: "recast_database", 5: "citing_work"}
    return {"claim": "unavailable", "census": None,
            "rungs": [{"rung": n, "name": names[n], "status": statuses.get(n, "ABSENT"), "evidence": f"rung {n} record",
                       "reason": "not applicable here" if statuses.get(n) == "NOT_APPLICABLE" else None}
                      for n in sorted(names) if statuses.get(n) != "missing"]}


def test_E03_unavailable_needs_rungs_one_to_five_with_definitive_answers(store):
    assert protocols.check("P6", ladder({})) == []
    assert protocols.check("P6", ladder({4: "NOT_APPLICABLE"})) == []
    assert any("outage" in p for p in protocols.check("P6", ladder({2: "ERROR"})))
    assert any("outage" in p for p in protocols.check("P6", ladder({3: "SKIPPED"})))
    assert any("lacks rung 5" in p for p in protocols.check("P6", ladder({5: "missing"})))
    assert any("contradicts" in p for p in protocols.check("P6", ladder({1: "OK"})))
    body = record("acquire", kind="resource_unavailable")
    assert any("missing P6" in p for p in records.check_record(body, step=decide("acquire")))
    body["protocol_evidence"] = {"P6": ladder({2: "ERROR"})}
    with pytest.raises(records.JudgmentRecordError):
        records.record_judgment(store, body, step=decide("acquire"))
    body["protocol_evidence"] = {"P6": ladder({})}
    records.record_judgment(store, body, step=decide("acquire"))
    assert records.for_step(store, "acquire")[-1]["class"] == "R2"


def test_C08_physics_critical_default_needs_a_justified_record(store):
    body = record("choose", kind="adopt_default_left_to_physicist", evidence={"P7": p7(physics_critical=True)})
    assert records.check_record(body, step=decide()) == []
    unjustified = deepcopy(body)
    unjustified["protocol_evidence"]["P7"]["justification"] = None
    assert any("justification" in p for p in records.check_record(unjustified, step=decide()))
    missing = deepcopy(body)
    missing["protocol_evidence"] = {}
    assert any("missing P7" in p for p in records.check_record(missing, step=decide()))
    records.record_judgment(store, body, step=decide())
    assert records.for_step(store, "choose")[-1]["class"] == "R3"


def test_C08_default_option_carries_its_P7_record():
    body = record("choose", default=p7(), default_option="a")
    assert records.check_record(body, step=decide()) == []
    body["default_option"] = "z"
    assert any("default option" in p for p in records.check_record(body, step=decide()))
    body = record("choose")
    body["default_option"] = "a"
    assert any("P7" in p for p in records.check_record(body, step=decide()))


def test_C08_record_default_is_checked_like_its_P7_evidence(store):
    unjustified = p7(physics_critical=True)
    unjustified["justification"] = None
    body = record("choose", default=unjustified, default_option="a")
    assert any("justification" in p for p in records.check_record(body, step=decide()))
    with pytest.raises(records.JudgmentRecordError):
        records.record_judgment(store, body, step=decide())
    inferred = p7()
    inferred["expected_sign"] = "weaker_claim"
    assert any("bias sign" in p for p in records.check_record(record("choose", default=inferred, default_option="a"),
                                                               step=decide()))
    assert records.check_record(record("choose", default=p7(physics_critical=True), default_option="a"),
                                step=decide()) == []


def test_C01_method_escalation_needs_every_cheaper_rung_accounted():
    pytest.importorskip("jsonschema")
    valid = json.loads((METHODS / "parameter_scan.json").read_text())
    body = record("choose", kind="method_escalation", evidence={"method_ladder": valid})
    assert records.check_record(body, step=decide()) == []
    stripped = deepcopy(valid)
    stripped["explicit_request"] = {"requested": False, "quote": None}
    stripped["alternatives"].pop(0)
    body["protocol_evidence"] = {"method_ladder": stripped}
    assert any("method ladder" in p for p in records.check_record(body, step=decide()))
    body["protocol_evidence"] = {}
    assert any("missing method_ladder" in p for p in records.check_record(body, step=decide()))


def recovery():
    return {"failure": {"step": "generate", "summary": "the fictional generator wrote no events"},
            "local_diagnosis": {"summary": "an undecayed state empties the selection", "evidence": ["log excerpt"]},
            "recipe_search": {"path": "inputs/recipe_search.json", "sha256": "a" * 64, "hits": 2},
            "diagnosis_class": "generator_model"}


def test_E12_stage_recovery_keeps_local_diagnosis_and_recipe_search():
    body = record("recover", kind="stage_recovery", evidence={"recovery": recovery()})
    assert records.check_record(body, step=decide("recover")) == []
    no_search = deepcopy(body)
    no_search["protocol_evidence"]["recovery"].pop("recipe_search")
    assert any("recipe_search" in p for p in records.check_record(no_search, step=decide("recover")))
    no_diagnosis = deepcopy(body)
    no_diagnosis["protocol_evidence"]["recovery"]["local_diagnosis"]["evidence"] = []
    assert records.check_record(no_diagnosis, step=decide("recover"))


def attack_document(plan="a" * 64, draft="b" * 64, axes=("basis", "acceptance", "statistics")):
    return {"schema_version": 1, "kind": "judgment-attacks", "subject": {"plan_sha256": plan, "draft_sha256": draft},
            "attacks": [{"axis": axis, "attack": f"{axis} attack", "test": f"{axis} test", "outcome": "survives",
                         "evidence": ["a located observation"]} for axis in axes]}


def test_JR09_three_attacks_one_per_axis_for_the_exact_draft():
    assert protocols.check_attacks(attack_document(), plan_sha256="a" * 64, draft_sha256="b" * 64) == []
    assert protocols.check_attacks(attack_document(axes=("basis", "basis", "statistics")),
                                   plan_sha256="a" * 64, draft_sha256="b" * 64)
    assert protocols.check_attacks(attack_document(axes=("basis", "statistics")), plan_sha256="a" * 64,
                                   draft_sha256="b" * 64)
    assert protocols.check_attacks(attack_document(), plan_sha256="a" * 64, draft_sha256="c" * 64)


def test_P3_trap_sweep_is_the_record_the_trap_sweep_tool_builds():
    from ravel.workflow import trap_sweep
    built = trap_sweep.build({"verdicts": [{"id": f"T{i}", "hit": False, "evidence": "checked"}
                                           for i in range(1, 13)]})
    assert protocols.check("P3", built) == []
    altered = deepcopy(built)
    altered["none_hit"] = False
    assert protocols.check("P3", altered)


def test_P4_ratio_outside_its_regime_cannot_proceed_silently():
    row = {"quantity": "rate", "value": 2.0, "unit": "fb", "anchor": {"source": "a fictional table", "value": 1.0,
                                                                       "kind": "published"},
           "ratio": 2.0, "tolerance": 0.2, "regime_reason": None, "action": "proceed"}
    assert any("regime" in p for p in protocols.check("P4", {"rows": [row]}))
    assert protocols.check("P4", {"rows": [{**row, "action": "open_p5"}]}) == []
    assert any("value / anchor" in p for p in protocols.check("P4", {"rows": [{**row, "ratio": 3.0,
                                                                               "action": "open_p5"}]}))


def test_P5_tests_run_in_cost_order():
    cause = {"category": "basis", "test": "re-normalize", "contribution": None}
    good = {"discrepancy": {"quantity": "limit", "observed": 1.3, "expected": 1.0},
            "causes": [{**cause, "id": "c1", "cause": "basis", "cost_rank": 1, "status": "confirmed"},
                       {**cause, "id": "c2", "cause": "statistics", "cost_rank": 2, "status": "untested"}],
            "residual": {"value": 0.05, "irreducible": True, "statement": "a small remainder"}}
    assert protocols.check("P5", good) == []
    bad = deepcopy(good)
    bad["causes"][0]["status"], bad["causes"][1]["status"] = "untested", "killed"
    assert any("cost order" in p for p in protocols.check("P5", bad))


def test_P7_bias_sign_is_not_inferred_without_evidence():
    value = p7()
    value["expected_sign"] = "weaker_claim"
    assert any("bias sign" in p for p in protocols.check("P7", value))


def test_record_outcome_is_appended_and_read_back(store):
    identifier = records.record_judgment(store, record("choose"), step=decide())
    records.record_outcome(store, identifier, "confirmed", {"authority": "authority-1"})
    assert records.outcomes(store) == {identifier: "confirmed"}
    with pytest.raises(ValueError):
        records.record_outcome(store, identifier, "approved", {"x": 1})


def test_JR08_authority_subject_offers_the_conservative_default_only_with_its_P7_record(store):
    records.record_judgment(store, record("choose", default=p7(), default_option="b"), step=decide())
    stored = records.for_step(store, "choose")[-1]
    subject = records.authority_subject(RUN_ID, stored, pins={"plan_sha256": "c" * 64})
    assert subject["conservative_default"] == "b"
    assert [o["id"] for o in subject["view"]["options"]] == ["a", "b"]
    plain = records.for_step(store, "choose")[-1]
    plain.pop("default")
    assert "conservative_default" not in records.authority_subject(RUN_ID, plain, pins={"plan_sha256": "c" * 64})
