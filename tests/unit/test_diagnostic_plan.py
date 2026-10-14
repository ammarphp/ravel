"""Independent contrasts and adverse scientific evidence controls."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from ravel.workflow import diagnostic_plan as dp


@pytest.mark.parametrize("pointer", ["/-1", "/01", "/~", "/~2", "/٠"])
def test_evidence_pointer_cannot_silently_select_a_python_alias(pointer):
    with pytest.raises(ValueError):
        dp.pointer(["first", "last"], pointer)

BASE = Path(__file__).resolve().parents[2] / "tests/fixtures/physics-review"


def plan():
    return dp.read_json(BASE / "clean-plan.json")


def pin(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def write(path, value):
    path.write_text(json.dumps(value, allow_nan=False))
    return pin(path)


def relationship(p, tmp_path, *, cross=None, status="uncorrelated"):
    """Explicit new synthetic assumption evidence; never migrate historical inputs."""
    source = {"schema_version": 1, "kind": "uncertainty_relationship", "status": status,
              "rationale": "Frozen synthetic engineering control: prescribed marginal and cross moments, not a physics independence claim.",
              "basis": p["comparison"]["basis"],
              "baseline": p["comparison"]["baseline"], "candidate": p["comparison"]["candidate"],
              "cross_covariance": cross}
    p["schema_version"] = 2
    p["comparison"]["uncertainty_relationship"] = {
        "status": status, "artifact": write(tmp_path / "relationship.json", source)}
    return p


def independent(tmp_path, *, missing=False):
    p = plan()
    p["comparison"]["kind"] = "independent"
    p["hypotheses"][0]["relative_tolerance"] = .3
    p["fixed_artifacts"] = [pin(BASE / "recipe.json")]
    for role, population, values in (("baseline", "reference", [100., 100.]), ("candidate", "replica", [101., 99.])):
        record = {"schema_version": 1, "kind": "estimates", "basis": p["comparison"]["basis"],
                  "population_id": population, "expected_exposure": 10000, "actual_exposure": 10000,
                  "values": values, "covariance": None if missing and role == "baseline" else [[1., .5], [.5, 1.]],
                  "covariance_status": "unavailable" if missing and role == "baseline" else "supplied",
                  "uncertainty_scope": "Explicit supplied synthetic covariance"}
        p["comparison"][role] = write(tmp_path / (role + ".json"), record)
    p["data_use"] = [{"population_id": population, "role": "validation", "artifact": p["comparison"][role]}
                     for role,population in (("baseline", "reference"), ("candidate", "replica"))]
    return relationship(p, tmp_path)


def test_all_frozen_clean_fault_twins_preserve_originals():
    original = {p: p.read_bytes() for p in BASE.rglob("*") if p.is_file()}
    spec = importlib.util.spec_from_file_location("review_controls", BASE / "run_controls.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.run()
    assert report["passed"]
    assert len(report["cases"]) == 11
    assert report["physics_validated"] is False
    assert report["review_required"] is True
    assert {p: p.read_bytes() for p in original} == original


def test_producer_prose_twins_do_not_change_deterministic_evidence_result():
    for stem,status in (("clean", "supported"), ("hidden-compensating-shape", "contradicted")):
        results = [dp.evaluate(dp.read_json(BASE / (stem + "-" + variant + "-plan.json")), BASE)
                   for variant in ("optimistic", "skeptical")]
        assert [r["status"] for r in results] == [status, status]
        assert results[0]["criterion_outcomes"] == results[1]["criterion_outcomes"]


def test_paired_covariance_uses_identical_events_not_independent_error():
    result = dp.evaluate(plan(), BASE)
    assert result["status"] == "supported"
    assert result["comparison_covariance"] == [[0., 0.], [0., 0.]]
    assert result["criterion_outcomes"][0]["channels"][0]["envelope"] == [0., 0.]
    assert "disposition" not in result


def test_independent_covariance_is_added_including_off_diagonal(tmp_path):
    result = dp.evaluate(independent(tmp_path), BASE)
    assert result["status"] == "supported"
    assert result["comparison_covariance"] == [[2., 1.], [1., 2.]]
    assert result["cross_covariance"] == [[0., 0.], [0., 0.]]
    assert "assumption" in result["uncertainty_relationship"]["scope"]


@pytest.mark.parametrize("legacy", [False, True])
def test_population_and_file_identities_do_not_supply_zero_cross_covariance(tmp_path, legacy):
    p = independent(tmp_path)
    if legacy:
        p["schema_version"] = 1
        del p["comparison"]["uncertainty_relationship"]
    else:
        p["comparison"]["uncertainty_relationship"] = {
            "status": "unavailable", "reason": "Shared reference/theory contributions have no supplied relationship."}
    result = dp.evaluate(p, BASE)
    assert result["status"] == "unresolved"
    assert result["comparison_covariance"] is None
    assert result["cross_covariance"] is None
    assert result["uncertainty_relationship"]["status"] == "unavailable"
    assert "not replaced by zero" in result["criterion_outcomes"][0]["channels"][0]["reason"]


def test_new_independent_schema_requires_explicit_relationship_and_legacy_does_not_grow_fields(tmp_path):
    p = independent(tmp_path)
    del p["comparison"]["uncertainty_relationship"]
    with pytest.raises(ValueError, match="uncertainty_relationship"):
        dp.validate(p)
    p = independent(tmp_path)
    p["schema_version"] = 1
    with pytest.raises(ValueError, match="comparison requires exactly"):
        dp.validate(p)


def test_shared_opposite_nuisance_response_prevents_false_support(tmp_path):
    p = independent(tmp_path)
    for role, value in (("baseline", 100.), ("candidate", 103.5)):
        path = Path(p["comparison"][role]["path"])
        source = dp.read_json(path)
        source["values"] = [value, value]
        source["covariance"] = [[1., 0.], [0., 1.]]
        p["comparison"][role] = write(path, source)
    for i, role in enumerate(("baseline", "candidate")):
        p["data_use"][i]["artifact"] = p["comparison"][role]
    p["hypotheses"][0].update(direction="increase", relative_tolerance=0)
    uncorrelated = dp.evaluate(relationship(p, tmp_path), BASE)
    assert uncorrelated["status"] == "supported"
    assert uncorrelated["comparison_covariance"] == [[2., 0.], [0., 2.]]
    supplied = dp.evaluate(relationship(p, tmp_path, cross=[[-.9, 0.], [0., -.9]], status="supplied"), BASE)
    assert supplied["status"] == "unresolved"
    assert supplied["comparison_covariance"] == [[3.8, 0.], [0., 3.8]]
    lo, hi = supplied["criterion_outcomes"][0]["channels"][0]["envelope"]
    assert lo < 0 < hi


def test_cross_covariance_need_not_be_symmetric_or_positive_semidefinite(tmp_path):
    p = independent(tmp_path)
    for role in ("baseline", "candidate"):
        path = Path(p["comparison"][role]["path"])
        source = dp.read_json(path)
        source["covariance"] = [[1., 0.], [0., 1.]]
        p["comparison"][role] = write(path, source)
    for i, role in enumerate(("baseline", "candidate")):
        p["data_use"][i]["artifact"] = p["comparison"][role]
    result = dp.evaluate(relationship(p, tmp_path, cross=[[0., .2], [-.1, 0.]], status="supplied"), BASE)
    assert result["status"] == "supported"
    assert result["comparison_covariance"] == [[2., -.1], [-.1, 2.]]


def test_positive_marginals_cannot_hide_invalid_joint_covariance(tmp_path):
    p = independent(tmp_path)
    result = dp.evaluate(relationship(p, tmp_path, cross=[[2., 0.], [0., 2.]], status="supplied"), BASE)
    assert result["status"] == "contradicted"
    assert "positive semidefinite" in result["integrity_checks"][-1]["reason"]


@pytest.mark.parametrize("mutation", ["stale", "wrong_basis", "wrong_comparison", "blank_rationale", "hidden_cross"])
def test_uncorrelated_assumption_requires_current_located_comparison_evidence(tmp_path, mutation):
    p = independent(tmp_path)
    path = Path(p["comparison"]["uncertainty_relationship"]["artifact"]["path"])
    source = dp.read_json(path)
    if mutation == "stale":
        path.write_text(path.read_text() + "\n")
    else:
        if mutation == "wrong_basis": source["basis"]["unit"] = "pb"
        elif mutation == "wrong_comparison": source["candidate"] = source["baseline"]
        elif mutation == "blank_rationale": source["rationale"] = ""
        else: source["cross_covariance"] = [[0., 0.], [0., 0.]]
        p["comparison"]["uncertainty_relationship"]["artifact"] = write(path, source)
    result = dp.evaluate(p, BASE)
    assert result["status"] == "contradicted"
    assert result["integrity_checks"][-1]["criterion"] == "evidence_integrity"


def test_absent_reference_covariance_stays_unresolved(tmp_path):
    result = dp.evaluate(independent(tmp_path, missing=True), BASE)
    assert result["status"] == "unresolved"
    assert result["comparison_covariance"] is None
    assert "not replaced by zero" in result["criterion_outcomes"][0]["channels"][0]["reason"]


def test_exploratory_calibration_does_not_become_confirmation():
    p = plan()
    for use in p["data_use"]:
        use["role"] = "calibration"
    result = dp.evaluate(p, BASE)
    assert result["status"] == "unresolved"
    assert result["data_role_status"] == "exploratory_calibration"


def test_retrospective_rs1_capacity_is_a_conditional_stop_not_calibration():
    result = dp.evaluate(dp.read_json(BASE / "rs1-track-capacity-plan.json"), BASE)
    assert result["status"] == "contradicted"
    assert result["data_role_status"] == "exploratory_calibration"
    assert result["criterion_outcomes"][0]["status"] == "unresolved"
    assert result["capacity"]["target"] < result["capacity"]["lower"]
    assert result["physics_validated"] is False


@pytest.mark.parametrize("mutation", ["population", "bytes"])
def test_calibration_validation_reuse_is_rejected(mutation):
    p = plan()
    extra = deepcopy(p["data_use"][0])
    extra["role"] = "calibration"
    if mutation == "population":
        extra["artifact"] = deepcopy(p["fixed_artifacts"][0])
    else:
        extra["population_id"] = "different-label-does-not-make-new-data"
    p["data_use"].append(extra)
    with pytest.raises(ValueError, match="calibration and validation"):
        dp.validate(p)


def test_independent_self_comparison_is_not_an_independent_replica(tmp_path):
    p = independent(tmp_path)
    p["comparison"]["candidate"] = p["comparison"]["baseline"]
    p["data_use"][1] = deepcopy(p["data_use"][0])
    result = dp.evaluate(p, BASE)
    assert result["status"] == "contradicted"
    assert "independent estimates reuse" in result["integrity_checks"][-1]["reason"]


def test_paired_original_weight_changes_are_rejected(tmp_path):
    p = plan()
    candidate = dp.read_json(BASE / p["comparison"]["candidate"]["path"])
    candidate["records"][0]["weight"] = 2
    p["comparison"]["candidate"] = write(tmp_path / "candidate.json", candidate)
    p["data_use"][1]["artifact"] = p["comparison"]["candidate"]
    result = dp.evaluate(p, BASE)
    assert "original weights" in result["integrity_checks"][-1]["reason"]


def test_correlated_signed_subevents_are_combined_before_squaring(tmp_path):
    p = plan()
    p["fixed_artifacts"] = [pin(BASE / "recipe.json")]
    data = dp.read_json(BASE / p["comparison"]["baseline"]["path"])
    for record in data["records"]:
        record["group_id"] = "shared"
    p["comparison"]["baseline"] = write(tmp_path / "base.json", data)
    data["records"][0]["bins"][0] += 1
    data["records"][2]["bins"][0] -= 1
    p["comparison"]["candidate"] = write(tmp_path / "changed.json", data)
    for i,role in enumerate(("baseline", "candidate")):
        p["data_use"][i]["artifact"] = p["comparison"][role]
    result = dp.evaluate(p, BASE)
    assert result["comparison_covariance"] == [[0., 0.], [0., 0.]]
    assert result["status"] == "unresolved"  # one correlated group cannot satisfy precision


def test_hidden_shape_change_survives_equal_integrated_rate():
    p = dp.read_json(BASE / "hidden-compensating-shape-plan.json")
    result = dp.evaluate(p, BASE)
    assert result["status"] == "contradicted"
    rows = result["criterion_outcomes"][0]["channels"]
    assert sum(r["difference"] for r in rows) == pytest.approx(0)
    assert all(r["status"] == "contradicted" for r in rows)


def test_capacity_bound_can_stop_an_unreachable_target(tmp_path):
    p = independent(tmp_path)
    p["capacity"] = {"artifact": write(tmp_path / "capacity.json", {"lower": .395, "upper": .558, "target": .294}),
                     "lower_pointer": "/lower", "upper_pointer": "/upper", "target_pointer": "/target",
                     "reason": "Declared fixed-sample capacity cannot reach target without changing a held-fixed assumption"}
    result = dp.evaluate(p, BASE)
    assert result["capacity"]["status"] == "contradicted"
    assert result["status"] == "contradicted"


def test_invalid_covariance_and_stale_source_do_not_pass(tmp_path):
    p = independent(tmp_path)
    path = Path(p["comparison"]["candidate"]["path"])
    record = dp.read_json(path)
    record["covariance"] = [[1., 2.], [2., 1.]]
    p["comparison"]["candidate"] = write(path, record)
    p["data_use"][1]["artifact"] = p["comparison"]["candidate"]
    assert "positive semidefinite" in dp.evaluate(p, BASE)["integrity_checks"][-1]["reason"]
    path.write_text(path.read_text() + "\n")
    assert "bytes changed" in dp.evaluate(p, BASE)["integrity_checks"][-1]["reason"]


def test_finite_source_values_cannot_generate_nonfinite_report_arithmetic(tmp_path):
    p = independent(tmp_path)
    for role,sign in (("baseline", -1), ("candidate", 1)):
        path = Path(p["comparison"][role]["path"])
        record = dp.read_json(path); record["values"] = [sign * 1e308, 100.]
        p["comparison"][role] = write(path, record)
    for i,role in enumerate(("baseline", "candidate")):
        p["data_use"][i]["artifact"] = p["comparison"][role]
    relationship(p, tmp_path)
    result = dp.evaluate(p, BASE)
    assert result["status"] == "contradicted"
    assert "contrast difference must be finite" in result["integrity_checks"][-1]["reason"]
    json.dumps(result, allow_nan=False)


def test_unknown_fields_uncovered_channels_and_boolean_precision_rejected():
    p = plan(); p["extra"] = True
    with pytest.raises(ValueError): dp.validate(p)
    p = plan(); p["hypotheses"][0]["channels"] = ["low"]
    with pytest.raises(ValueError, match="every declared channel"): dp.validate(p)
    p = plan(); p["precision"]["max_relative_mc_error"] = True
    with pytest.raises(ValueError, match="finite and numeric"): dp.validate(p)


def test_real_frozen_rs1_projection_keeps_closure_unresolved():
    result = dp.evaluate(dp.read_json(BASE / "rs1-frozen-plan.json"), BASE)
    assert result["status"] == "unresolved"
    assert result["comparison_covariance"] is None
    assert result["physics_validated"] is False


def test_cli_preserves_existing_output(tmp_path):
    out = tmp_path / "result.json"
    assert dp.main(["--plan", str(BASE / "clean-plan.json"), "--out", str(out)]) == 0
    before = out.read_bytes()
    with pytest.raises(SystemExit):
        dp.main(["--plan", str(BASE / "clean-plan.json"), "--out", str(out)])
    assert out.read_bytes() == before
