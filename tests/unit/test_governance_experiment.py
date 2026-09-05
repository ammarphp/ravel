"""Accounting regressions. Synthetic fixtures are software tests, not agent results."""
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "benchmarks" / "governance" / "experiment.py"
spec = importlib.util.spec_from_file_location("governance_experiment", SCRIPT)
experiment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(experiment)


def study():
    return {
        "experiment_id": "synthetic-test-only", "protocol_sha256": "a" * 64,
        "code_commit": "b" * 40, "environment_sha256": "c" * 64,
        "model": "fixture-model", "runtime": "fixture-runtime", "schedule_seed": 42,
        "seeds": [11, 29], "budget": {"usd_per_run": 1, "seconds_per_run": 60},
        "tasks": [
            {"id": "supported", "expected": "complete", "prompt_sha256": "d" * 64,
             "oracle_sha256": "e" * 64, "fidelity_tolerance": 0.1},
            {"id": "unsupported", "expected": "refuse", "prompt_sha256": "f" * 64,
             "oracle_sha256": "a" * 64, "fidelity_tolerance": None},
        ],
    }


def cohort():
    registry = experiment.freeze(study())
    rows = []
    for run in registry["runs"]:
        supported = run["task_id"] == "supported"
        rows.append({"run_id": run["run_id"], "status": "completed" if supported else "refused",
                     "unsupported_claim": False, "refusal_valid": None if supported else True,
                     "fidelity_error": 0.05 if supported else None,
                     "cost_usd": 0.1, "wall_seconds": 2, "interventions": 0,
                     "executor_id": "fixture-executor", "scorer_id": "fixture-independent-reviewer",
                     "evidence_sha256": "b" * 64, "notes": "Synthetic fixture only"})
    return registry, {"schema_version": 1, "registry_sha256": registry["registry_sha256"], "outcomes": rows}


def test_roster_is_complete_crossed_and_deterministic():
    registry = experiment.freeze(study())
    assert registry == experiment.freeze(study())
    assert len(registry["runs"]) == 2 * 2 * 4
    assert len({r["run_id"] for r in registry["runs"]}) == 16
    for task in ("supported", "unsupported"):
        for seed in (11, 29):
            assert {r["arm"] for r in registry["runs"] if r["task_id"] == task and r["seed"] == seed} == set(experiment.ARMS)


@pytest.mark.parametrize("change", ["remove", "duplicate", "unplanned"])
def test_cannot_improve_denominator_by_dropping_or_repeating_runs(change):
    registry, outcomes = cohort()
    if change == "remove":
        outcomes["outcomes"].pop()
    elif change == "duplicate":
        outcomes["outcomes"].append(copy.deepcopy(outcomes["outcomes"][0]))
    else:
        outcomes["outcomes"][0]["run_id"] = "0" * 64
    with pytest.raises(ValueError, match="accounting|duplicate"):
        experiment.score(registry, outcomes)


def test_outcomes_from_previous_campaign_cannot_be_reused_by_relabeling_document():
    registry, outcomes = cohort()
    updated = copy.deepcopy(registry["spec"])
    updated["code_commit"] = "c" * 40
    next_registry = experiment.freeze(updated)
    outcomes["registry_sha256"] = next_registry["registry_sha256"]
    with pytest.raises(ValueError, match="accounting"):
        experiment.score(next_registry, outcomes)


def test_all_verified_results_have_separate_completion_and_refusal_controls():
    registry, outcomes = cohort()
    for arm in experiment.score(registry, outcomes)["arms"].values():
        assert arm["planned"] == 4
        assert arm["unsupported_claim_rate"] == 0
        assert arm["verified_completion_rate"] == 1
        assert arm["verified_valid_refusal_rate"] == 1


def test_blanket_refusal_cannot_score_as_useful_completion():
    registry, outcomes = cohort()
    for row in outcomes["outcomes"]:
        row.update(status="refused", refusal_valid=True, fidelity_error=None)
    for arm in experiment.score(registry, outcomes)["arms"].values():
        assert arm["unsupported_claim_rate"] == 0
        assert arm["verified_completion_rate"] == 0
        assert arm["refusals_on_completion_controls"] == 2


def test_explicit_unrun_assignment_is_not_a_zero_invalidity_success():
    registry, outcomes = cohort()
    row = outcomes["outcomes"][0]
    arm_name = registry["runs"][0]["arm"]
    row.update(status="not_started", unsupported_claim=None, refusal_valid=None, fidelity_error=None,
               cost_usd=0, wall_seconds=0, interventions=0, executor_id=None, scorer_id=None,
               evidence_sha256=None, notes="Scheduler stopped before launch")
    arm = experiment.score(registry, outcomes)["arms"][arm_name]
    assert arm["planned"] == 4
    assert arm["unsupported_claim_rate"] is None
    assert arm["unsupported_claim_rate_bounds"] == [0, 0.25]
    assert arm["status_counts"]["not_started"] == 1


def test_missing_cost_and_unscored_fidelity_remain_visible():
    registry, outcomes = cohort()
    row = next(r for r in outcomes["outcomes"] if r["status"] == "completed")
    row.update(cost_usd=None, fidelity_error=None, notes="Usage unavailable; oracle did not finish")
    arm_name = next(r["arm"] for r in registry["runs"] if r["run_id"] == row["run_id"])
    arm = experiment.score(registry, outcomes)["arms"][arm_name]
    assert arm["cost_usd"]["missing_runs"] == 1
    assert arm["cost_usd"]["known_sum"] == pytest.approx(0.3)
    assert arm["verified_completion_rate"] == 0.5
    assert arm["fidelity_scored"] == 1


@pytest.mark.parametrize("status", ["timeout", "crash"])
def test_failed_attempt_can_still_contain_an_unsupported_claim(status):
    registry, outcomes = cohort()
    row = outcomes["outcomes"][0]
    row.update(status=status, unsupported_claim=True, refusal_valid=None, fidelity_error=None)
    arm = experiment.score(registry, outcomes)["arms"][registry["runs"][0]["arm"]]
    assert arm["unsupported_claim_rate"] == 0.25
    assert arm["unsupported_claim_rate_bounds"] == [0.25, 0.25]


@pytest.mark.parametrize("field,value", [("cost_usd", float("nan")), ("wall_seconds", float("inf")),
                                        ("fidelity_error", -1), ("interventions", True),
                                        ("interventions", 0.5), ("unsupported_claim", 1)])
def test_invalid_metrics_are_rejected(field, value):
    registry, outcomes = cohort()
    outcomes["outcomes"][0][field] = value
    with pytest.raises(ValueError):
        experiment.score(registry, outcomes)


def test_self_scoring_and_evidence_omission_are_rejected():
    registry, outcomes = cohort()
    row = outcomes["outcomes"][0]
    row["scorer_id"] = row["executor_id"]
    with pytest.raises(ValueError, match="independent"):
        experiment.score(registry, outcomes)
    row["scorer_id"] = "independent"
    row["evidence_sha256"] = None
    with pytest.raises(ValueError, match="evidence"):
        experiment.score(registry, outcomes)


@pytest.mark.parametrize("change", ["arms", "roster", "tolerance", "schema"])
def test_registry_changes_invalidate_frozen_roster(change):
    registry, outcomes = cohort()
    registry = copy.deepcopy(registry)
    if change == "arms":
        registry["arms"]["full"]["enforcement"] = False
    elif change == "roster":
        registry["runs"].pop()
    elif change == "schema":
        registry["schema_version"] = True
    else:
        registry["spec"]["tasks"][0]["fidelity_tolerance"] = 100
    with pytest.raises(ValueError, match="registry"):
        experiment.score(registry, outcomes)


def test_design_requires_negative_controls_and_distinct_repeats():
    spec = study()
    spec["tasks"].pop()
    with pytest.raises(ValueError, match="controls"):
        experiment.freeze(spec)
    spec = study()
    spec["seeds"] = [1, 1]
    with pytest.raises(ValueError, match="duplicates"):
        experiment.freeze(spec)


def test_fidelity_is_kept_per_task_instead_of_pooling_different_units():
    registry, outcomes = cohort()
    for arm in experiment.score(registry, outcomes)["arms"].values():
        assert "fidelity_median_known" not in arm
        assert arm["fidelity_by_task"] == {"supported": {
            "planned": 2, "scored": 2, "median_known": 0.05, "tolerance": 0.1}}


@pytest.mark.parametrize("text", ['{"unsupported_claim": true, "unsupported_claim": false}',
                                  '{"metric": NaN}', '{"metric": Infinity}'])
def test_json_cannot_silently_replace_judgments_or_accept_nonstandard_constants(tmp_path, text):
    path = tmp_path / "ambiguous.json"
    path.write_text(text)
    with pytest.raises(ValueError):
        experiment.load_json(path)


def test_cli_rejects_incomplete_accounting_without_emitting_score(tmp_path):
    registry, outcomes = cohort()
    outcomes["outcomes"].pop()
    reg = tmp_path / "registry.json"
    out = tmp_path / "outcomes.json"
    reg.write_text(json.dumps(registry))
    out.write_text(json.dumps(outcomes))
    result = subprocess.run([sys.executable, str(SCRIPT), "score", str(reg), str(out)],
                            text=True, capture_output=True)
    assert result.returncode == 2
    assert not result.stdout
    assert "complete accounting required" in result.stderr
