"""Complete synthetic diagnosis controls with real graph receipts, no model calls."""
from copy import deepcopy
import json

import pytest

from ravel.validation import fault_injection as fi
from ravel.validation import fault_injection_study as study
from ravel.workflow import agent_graph


@pytest.mark.parametrize("fault", study.FAULTS, ids=lambda row: row["id"])
def test_single_fault_is_measured_repaired_and_only_descendants_rerun(tmp_path, fault):
    document = study.study()
    settings = study.inject(document, fault["id"])
    differences = [(stage, key) for stage in study.STAGES for key in settings[stage]
                   if settings[stage][key] != document["rules"][stage][key]]
    assert differences == [(fault["stage"], fault["key"])]
    result = fi.evaluate_case(tmp_path/"case", fault["id"])
    assert result["error"] is None
    assert all(result["scores"].values()), result
    expected = ["sample-" + s for s in study.STAGES[study.STAGES.index(fault["stage"]):]]
    assert result["rerun"] == expected
    assert result["calls"] == 10 + len(expected)
    assert result["before"]["value"] != pytest.approx(result["reference"]["value"])
    assert result["after"]["value"] == pytest.approx(result["reference"]["value"], rel=1e-10)
    assert result["intervention"]["before"] != result["intervention"]["after"]
    assert not result["physics_validated"] and not result["execution_authorized"]
    state = agent_graph.status(tmp_path/"case"/"study")
    for name, row in state["nodes"].items():
        assert row["generation"] == (1 if name in expected else 0)


def test_signed_weights_and_existing_ledger_name_the_planted_faults(tmp_path):
    expected = {"factor_missing": "k_omitted", "factor_doubled": "k_applied_twice", "unit_conversion": "unit_swap"}
    for fault, code in expected.items():
        report = fi.evaluate_case(tmp_path/fault, fault)
        failures = report["intervention"]["before"]["ledger_check"]["failures"]
        assert code in {row["code"] for row in failures}
        assert report["intervention"]["after"]["ledger_check"]["passed"]
        assert any(r["code"] == "negative_weights" for r in report["intervention"]["after"]["ledger_check"]["warnings"])


def test_clean_control_is_not_repaired_and_false_positives_lose_credit(tmp_path):
    def constant(packet):
        return {"detected": True, "first_stage": "inference", "test": study.TESTS["inference"],
                "changes": [{"key": "result_scale", "value": 1.}]}
    result = fi.evaluate_case(tmp_path/"case", "inference_scale", proposer=constant)
    assert result["scores"]["repaired"]
    assert not result["scores"]["control_untouched"]
    assert all(result["executed"].count("control-" + s) == 1 for s in study.STAGES)


@pytest.mark.parametrize("kind", ["wrong_stage", "no_test", "wrong_value", "compound_change", "nonfinite", "abstain"])
def test_asserted_success_without_discriminating_repair_receives_no_credit(tmp_path, kind):
    def propose(packet):
        value = fi.deterministic_proposal(packet)
        if not value["detected"]:
            return value
        if kind == "wrong_stage":
            value.update(first_stage="inference", test=study.TESTS["inference"], changes=[{"key": "result_scale", "value": 1.}])
        elif kind == "no_test":
            value["test"] = "assert_repaired"
        elif kind == "wrong_value":
            value["changes"][0]["value"] = 2
        elif kind == "compound_change":
            value["changes"].append({"key": "unit_multiplier", "value": 1.})
        elif kind == "nonfinite":
            value["changes"][0]["value"] = float("nan")
        elif kind == "abstain":
            value = {"detected": False, "first_stage": None, "test": None, "changes": []}
        return value
    result = fi.evaluate_case(tmp_path/"case", "factor_missing", proposer=propose)
    assert not result["scores"]["repaired"]
    assert not result["scores"]["corrected_conclusion"]
    assert result["rerun"] == []
    assert result["before"] == result["after"]



def test_alternating_answers_cannot_identify_arms_from_submission_order(tmp_path, monkeypatch):
    results = []
    for reverse in (0, 1):
        monkeypatch.setattr(fi.secrets, "randbelow", lambda n, value=reverse: value)
        calls = []
        def alternate(packet):
            calls.append(None)
            return {"detected": len(calls) == 1, "first_stage": None, "test": None, "changes": []}
        results.append(fi.evaluate_case(tmp_path/str(reverse), "factor_missing", proposer=alternate))
    assert results[0]["scores"]["detected"] and results[0]["scores"]["control_untouched"]
    assert not results[1]["scores"]["detected"] and not results[1]["scores"]["control_untouched"]
    assert not any(row["scores"]["repaired"] for row in results)


def test_suite_reports_each_class_and_preserves_original_population(tmp_path, record_property):
    report = fi.evaluate_suite(tmp_path/"suite")
    assert {k: v["total"] for k, v in report["classes"].items()} == {
        "cards": 1, "selections": 1, "normalization": 3, "templates": 2, "inference": 2}
    assert len(report["rows"]) == 9
    assert all(row["total"] == row[key] for row in report["classes"].values() for key in fi.SCORES)
    assert "corrected_conclusion" in fi.score_table(report)
    record_property("fault_evaluation", json.dumps({"classes": report["classes"], "rows": [
        {key: row[key] for key in ("fault", "scores", "before", "after", "reference", "rerun", "calls", "seconds")}
        for row in report["rows"]]}, sort_keys=True))
    with pytest.raises(ValueError, match="new output"):
        fi.evaluate_suite(tmp_path/"suite")
    with pytest.raises(ValueError, match="unique"):
        fi.evaluate_suite(tmp_path/"duplicate", fault_ids=["card_rate", "card_rate"])


def test_proposer_cannot_mutate_retained_study_or_correct_control(tmp_path):
    seen = []
    def mutate(packet):
        proposal = fi.deterministic_proposal(packet)
        seen.append(deepcopy(packet))
        packet["study"]["events"].clear()
        packet["artifacts"].clear()
        return proposal
    report = fi.evaluate_case(tmp_path/"case", "wrong_bin", proposer=mutate)
    assert all(report["scores"].values())
    assert all(len(packet["study"]["events"]) == 8 for packet in seen)


def test_cli_has_no_model_transport_mode(tmp_path):
    with pytest.raises(SystemExit):
        fi.main(["--out", str(tmp_path/"missing"), "--mode", "agent"])
    with pytest.raises(SystemExit):
        fi.main(["--out", str(tmp_path/"unexpected"), "--model", "synthetic-model"])
    assert not (tmp_path/"missing").exists() and not (tmp_path/"unexpected").exists()


@pytest.mark.parametrize("failed_arm", ["sample", "control"])
@pytest.mark.parametrize("reverse", [0, 1])
def test_failed_proposal_retains_both_arms_independent_of_order(tmp_path, monkeypatch, failed_arm, reverse):
    monkeypatch.setattr(fi.secrets, "randbelow", lambda n: reverse)
    attempted = []

    def fail_one(packet):
        result = fi.deterministic_proposal(packet)
        arm = "sample" if result["detected"] else "control"
        attempted.append(arm)
        if arm == failed_arm:
            raise OSError("synthetic unavailable transport")
        return result

    report = fi.evaluate_case(tmp_path/"case", "factor_missing", proposer=fail_one)
    assert sorted(attempted) == ["control", "sample"]
    assert report["proposal_errors"] == {failed_arm: {
        "type": "OSError", "message": "synthetic unavailable transport"}}
    assert report["error"] is not None
    assert report["scores"]["control_untouched"] == (failed_arm == "sample")
    for score in fi.SCORES[:-1]:
        assert report["scores"][score] == (failed_arm == "control")
    assert report["rerun"] == ([] if failed_arm == "sample" else [
        "sample-normalization", "sample-templates", "sample-inference"])


def test_suite_never_overwrites_a_disjoint_existing_population(tmp_path):
    root = tmp_path/"suite"
    fi.evaluate_suite(root, fault_ids=["factor_missing"])
    original = (root/"scores.json").read_bytes()
    with pytest.raises(ValueError, match="new output"):
        fi.evaluate_suite(root, fault_ids=["wrong_bin"])
    assert (root/"scores.json").read_bytes() == original
    assert not (root/"wrong_bin").exists()
    with pytest.raises(ValueError, match="mode"):
        fi.evaluate_suite(tmp_path/"invalid", mode="human")
    assert not (tmp_path/"invalid").exists()
