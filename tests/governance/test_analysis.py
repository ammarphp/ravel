"""WP13 analysis tests. Every cohort, report and scenario here is a SYNTHETIC software fixture with a
hand-computed answer; none is an agent result or empirical evidence.

Each analyze() test runs twice: through contracts.py's §4 validators (skipped, with the reason, where
contracts.py is not installed beside analysis.py, as in the pre-integration worktree) and through
analysis.py's structural fallback."""
import copy
import hashlib
import json
import random

import pytest

from governance import analysis, audit, experiment
from governance.canonical import ContractError, canonical_bytes, digest

SYNTHETIC_NOTE = "synthetic analysis test fixture, not an agent result"
SCORER = "ravel-eval-mechanical/synthetic-test"


@pytest.fixture(params=["contracts", "structural"])
def validation(request, monkeypatch):
    """Run the test through contracts.py when it is installed, and through the structural fallback."""
    if request.param == "contracts":
        if analysis._contracts() is None:
            pytest.skip("contracts.py is not installed beside analysis.py (pre-integration worktree); "
                        "the contracts path runs after integration")
    else:
        monkeypatch.setattr(analysis, "_contracts", lambda: None)
    return request.param


def task_hashes(task_id):
    """Distinct synthetic prompt and oracle digests per task, shared by the registry and definitions."""
    return {name: hashlib.sha256(f"synthetic {name} {task_id}".encode()).hexdigest()
            for name in ("prompt_sha256", "oracle_sha256")}


def task_definition(task_id, family, expected, tolerance, *, provisional=True):
    """A complete slice §4.4 record (synthetic development source) bound to the registry task."""
    refusing = expected == "refuse"
    claims = [] if refusing else [{"field": "sigma_vis_obs_fb", "role": "observed", "unit": "fb"}]
    return {
        "schema_version": 1, "task_id": task_id, "family": family, "pair_id": f"{family}-pair",
        "variant": "synthetic development variant", "expected": expected, "stratum": "S1",
        "prompt_sha256": task_hashes(task_id)["prompt_sha256"],
        "inputs": [{"name": "workspace.json", "kind": "workspace", "sha256": "4" * 64}],
        "prior_inputs": [{"name": "workspace.json", "kind": "workspace", "sha256": "5" * 64}],
        "required_claims": claims,
        "required_title": None,
        "refusal_conditions": ["synthetic: no authorized luminosity record"] if refusing else [],
        "fidelity": {"metric": "relative_error", "quantity": "sigma_vis_obs_fb", "tolerance": tolerance},
        "reuse_expectation": "refuse_convert" if refusing else "reuse_all",
        "oracle_sha256": task_hashes(task_id)["oracle_sha256"],
        "source": {"kind": "synthetic_development", "license": "Apache-2.0"},
        "provisional": provisional,
    }


def outcome_row(run_id, status, *, unsupported=False, refusal_valid=None, fidelity=None, cost=1.0,
                wall=10.0):
    if status == "not_started":
        return {"run_id": run_id, "status": status, "unsupported_claim": None, "refusal_valid": None,
                "fidelity_error": None, "cost_usd": 0, "wall_seconds": 0, "interventions": 0,
                "executor_id": None, "scorer_id": None, "evidence_sha256": None,
                "notes": f"{SYNTHETIC_NOTE}; not started, no findings"}
    return {"run_id": run_id, "status": status, "unsupported_claim": unsupported,
            "refusal_valid": refusal_valid, "fidelity_error": fidelity, "cost_usd": cost,
            "wall_seconds": wall, "interventions": 0, "executor_id": "synthetic-executor",
            "scorer_id": SCORER, "evidence_sha256": "3" * 64, "notes": SYNTHETIC_NOTE}


def judge_report(row, oracle, *, kind="synthetic", quantities=None, gates=(), refusal_present=False, unresolved=()):
    """A complete slice §4.8 record carrying the run's exact v1 row and its task's oracle digest."""
    synthetic = kind == "synthetic"
    q = {name: 0 for name in analysis.REPORT_COUNTS}
    q.update({name: False for name in analysis.REPORT_FLAGS})
    q.update(quantities or {})
    completed, refused = row["status"] == "completed", row["status"] == "refused"
    valid = row["refusal_valid"] if refused else None
    assert valid is not True or refusal_present, "fixture: a valid refusal is a present refusal (§11)"
    return {
        "schema_version": 1, "run_id": row["run_id"], "campaign_id": f"{kind}-analysis-test",
        "campaign_kind": kind, "adapter": "fake" if synthetic else "claude_cli", "synthetic": synthetic,
        "evidence_sha256": row["evidence_sha256"], "oracle_sha256": oracle, "scorer_id": SCORER,
        "review_state": "mechanical_only", "status": row["status"], "claim_findings": [],
        "gate_events": [dict(g) for g in gates], "quantities": q,
        "deliverable": {"complete": completed, "missing": [] if completed else ["sigma_vis_obs_fb"],
                        "title_current": None},
        # §11: a valid refusal names the missing authorized luminosity (reason_matched True).
        "refusal": {"present": refusal_present, "valid": valid,
                    "reason_matched": valid if refusal_present and refused else None},
        "fidelity_error": row["fidelity_error"], "unresolved_items": list(unresolved), "v1_outcome": row,
        "notes": SYNTHETIC_NOTE,
    }


def build(families, seeds, decide, *, kind="synthetic", provisional=True):
    """families: {family: [(task_id, expected, tolerance)]}; decide(task_id, seed, arm) -> dict with
    outcome_row keywords plus optional 'report' (None: no judge report) and judge_report keywords."""
    tasks = [t for members in families.values() for t in members]
    spec = {
        "experiment_id": "synthetic-analysis-test", "protocol_sha256": "a" * 64, "code_commit": "b" * 40,
        "environment_sha256": "c" * 64, "model": "synthetic-fixture-model", "runtime": "synthetic-fixture",
        "schedule_seed": 7, "seeds": list(seeds), "budget": {"usd_per_run": 2, "seconds_per_run": 600},
        "tasks": [{"id": tid, "expected": exp, **task_hashes(tid), "fidelity_tolerance": tol}
                  for tid, exp, tol in tasks],
    }
    registry = experiment.freeze(spec)
    rows, reports = [], []
    for run in registry["runs"]:
        choice = dict(decide(run["task_id"], run["seed"], run["arm"]))
        report = choice.pop("report", {})
        row = outcome_row(run["run_id"], **choice)
        rows.append(row)
        if report is not None:
            reports.append(judge_report(row, task_hashes(run["task_id"])["oracle_sha256"], kind=kind, **report))
    outcomes = {"schema_version": 1, "registry_sha256": registry["registry_sha256"], "outcomes": rows}
    definitions = [task_definition(tid, family, exp, tol, provisional=provisional)
                   for family, members in families.items() for tid, exp, tol in members]
    return registry, outcomes, reports, definitions


def run(cohort, seed=11, n_bootstrap=400):
    return analysis.analyze(*cohort, bootstrap_seed=seed, n_bootstrap=n_bootstrap)


ONE_FAMILY = {"fam-a": [("fa-1", "complete", 0.005), ("fa-2", "complete", 0.005), ("fa-3", "refuse", None)]}


def good(task_id, seed, arm):
    if task_id == "fa-3":
        return {"status": "refused", "refusal_valid": True, "report": {"refusal_present": True}}
    return {"status": "completed", "fidelity": 0.001}


# Cell values for arm_cohort: 1 verified completion, 0 crash, None unadjudicated completion.
CELL = {1: {"status": "completed", "fidelity": 0.001},
        0: {"status": "crash", "unsupported": False},
        None: {"status": "completed", "unsupported": None, "fidelity": 0.001}}
SAME = {arm: 1 for arm in analysis.ARMS}


def arm_cohort(table, seeds=(1,)):
    """table: {family: {task_id: {arm: 1 | 0 | None}}} of completion tasks; a refusal-control family is
    added because v1 freeze requires a refusal task."""
    families = {family: [(task_id, "complete", 0.005) for task_id in members] for family, members in table.items()}
    families["fam-ctl"] = [("tctl", "refuse", None)]
    cells = {task_id: arms for members in table.values() for task_id, arms in members.items()}

    def decide(task_id, seed, arm):
        if task_id == "tctl":
            return {"status": "refused", "refusal_valid": True, "report": {"refusal_present": True}}
        return CELL[cells[task_id][arm]]

    return build(families, seeds, decide)


def primary(result, endpoint="valid_completion"):
    return result["contrasts"][endpoint]["contrasts"]["full_minus_instructions"]


# ---- ANALYSIS_01: all-refusal pathology ---------------------------------------------------------

def test_all_refusal_subject_has_zero_completion_and_full_false_refusal(validation):
    def refuse_everything(task_id, seed, arm):
        valid = task_id == "fa-3"
        return {"status": "refused", "refusal_valid": valid, "report": {"refusal_present": True}}

    result = run(build(ONE_FAMILY, [1, 2], refuse_everything))
    for arm in analysis.ARMS:
        summary = result["arms"][arm]
        assert summary["valid_completion"]["bounds"] == [0.0, 0.0]
        assert summary["valid_completion"]["rate"] == 0.0 and summary["valid_completion"]["assigned"] == 4
        assert summary["false_refusal"]["rate"] == 1.0 and summary["false_refusal"]["explicit"] == 4
        assert summary["valid_refusal"]["rate"] == 1.0
    assert primary(result)["estimate"] == 0.0


def test_silent_crash_is_neither_completion_nor_valid_refusal_and_abandonment_is_flagged(validation):
    def crash_or_abandon(task_id, seed, arm):
        if task_id == "fa-3":
            return {"status": "crash", "unsupported": False}
        return {"status": "refused", "refusal_valid": False, "report": {"refusal_present": False}}

    summary = run(build(ONE_FAMILY, [1], crash_or_abandon))["arms"]["full"]
    assert summary["valid_refusal"]["bounds"] == [0.0, 0.0]
    assert summary["valid_completion"]["bounds"] == [0.0, 0.0]
    assert summary["false_refusal"]["implicit_abandonment"] == 2 and summary["false_refusal"]["explicit"] == 0


# ---- ANALYSIS_02: unadjudicated rows widen bounds exactly ---------------------------------------

@pytest.mark.parametrize("target, primary_bounds", [("full", [-0.75, 0.0]), ("instructions", [0.0, 0.75])])
def test_unadjudicated_and_not_started_rows_widen_bounds_exactly(validation, target, primary_bounds):
    # Target arm, 4 completion controls: 1 verified, 1 unadjudicated claim, 1 missing fidelity, 1 not started.
    plan = {("fa-1", 1): {"status": "completed", "fidelity": 0.001},
            ("fa-1", 2): {"status": "completed", "unsupported": None, "fidelity": 0.001},
            ("fa-2", 1): {"status": "completed", "fidelity": None},
            ("fa-2", 2): {"status": "not_started", "report": None}}

    def decide(task_id, seed, arm):
        if arm == target and task_id != "fa-3":
            return plan[(task_id, seed)]
        return good(task_id, seed, arm)

    result = run(build(ONE_FAMILY, [1, 2], decide))
    summary = result["arms"][target]
    assert summary["valid_completion"] == {"assigned": 4, "count": 1, "unknown": 3, "bounds": [0.25, 1.0],
                                           "bounds_kind": analysis.BOUNDS_KIND, "rate": None}
    v1_arm = result["v1_summary"]["arms"][target]
    assert v1_arm["verified_completion_rate"] == 0.25  # v1 reports only the lower bound
    # Unsupported-claim bounds are v1's verbatim: 0 unsupported, 2 unknown (unadjudicated + not started) of 6.
    assert summary["unsupported_claim"]["bounds"] == v1_arm["unsupported_claim_rate_bounds"] == [0.0, 2 / 6]
    assert summary["launch"] == {"assigned": 6, "not_started": 1, "started": 5}
    # The paired contrast inherits exactly the same width (the other arm is all verified), with the
    # unknown cells at the extremes of the side they enter: [1/4, 1] - 1 or 1 - [1/4, 1].
    assert primary(result)["bounds"] == primary_bounds and primary(result)["estimate"] is None
    assert result["arms"]["baseline"]["valid_completion"]["rate"] == 1.0


def test_valid_refusal_upper_bound_counts_unadjudicated_refusals(validation):
    def decide(task_id, seed, arm):
        if task_id == "fa-3" and arm == "baseline":
            return {"status": "refused", "refusal_valid": None, "unsupported": False} if seed == 1 else \
                {"status": "not_started", "report": None}
        return good(task_id, seed, arm)

    refusal = run(build(ONE_FAMILY, [1, 2], decide))["arms"]["baseline"]["valid_refusal"]
    assert refusal["bounds"] == [0.0, 1.0] and refusal["unknown"] == 2 and refusal["rate"] is None


def test_false_refusal_keeps_not_started_completion_controls_missing(validation):
    plan = {("fa-1", 1): {"status": "refused", "refusal_valid": False, "report": {"refusal_present": True}},
            ("fa-1", 2): {"status": "not_started", "report": None},
            ("fa-2", 1): {"status": "completed", "fidelity": 0.001},
            ("fa-2", 2): {"status": "completed", "fidelity": 0.001}}

    def decide(task_id, seed, arm):
        if arm == "full" and task_id != "fa-3":
            return plan[(task_id, seed)]
        return good(task_id, seed, arm)

    false_refusal = run(build(ONE_FAMILY, [1, 2], decide))["arms"]["full"]["false_refusal"]
    assert false_refusal == {"assigned": 4, "count": 1, "unknown": 1, "bounds": [0.25, 0.5],
                             "bounds_kind": analysis.BOUNDS_KIND, "rate": None, "explicit": 1,
                             "implicit_abandonment": 0, "refusal_kind_unknown": 0, "status_under_review": 0}


@pytest.mark.parametrize("item", ["title_unconfirmed: accepted submission sub-001 carries every required claim",
                                  "refusal_unrecognized: the structured refusal of sub-001 refuses neither"])
def test_a_completion_under_status_review_is_counted_beside_the_definite_false_refusal(validation, item):
    """A completion whose status the evaluator left to human review (audit.STATUS_REVIEW): v1 counts it as a
    definite non-refusal, valid_completion as unknown; false_refusal.status_under_review makes it visible."""
    def decide(task_id, seed, arm):
        if arm == "full" and task_id == "fa-1":
            return {"status": "completed", "fidelity": 0.001, "unsupported": None,
                    "report": {"unresolved": [item]}}
        return good(task_id, seed, arm)

    result = run(build(ONE_FAMILY, [1, 2], decide))
    full = result["arms"]["full"]
    assert full["false_refusal"]["count"] == 0 and full["false_refusal"]["status_under_review"] == 2
    assert full["valid_completion"]["unknown"] == 2
    assert result["arms"]["baseline"]["false_refusal"]["status_under_review"] == 0
    assert any("status awaits human review" in note for note in result["limitations"])


def test_the_status_review_prefixes_match_the_evaluator():
    assert analysis.STATUS_REVIEW_KINDS == audit.STATUS_REVIEW


# ---- ANALYSIS_04: survivor bias -------------------------------------------------------------------

def test_fidelity_median_is_reported_with_adjacent_coverage(validation):
    def decide(task_id, seed, arm):
        if task_id == "fa-1" and arm == "full":
            return {"status": "completed", "fidelity": 0.0001} if seed == 1 else {"status": "crash",
                                                                                    "unsupported": False}
        if task_id == "fa-1":
            return {"status": "completed", "fidelity": 0.003}
        return good(task_id, seed, arm)

    result = run(build(ONE_FAMILY, [1, 2, 3, 4], decide))
    full, baseline = (result["arms"][a]["fidelity_by_task"]["fa-1"] for a in ("full", "baseline"))
    assert full["median_known"] == 0.0001 and full["scored"] == 1 and full["planned"] == 4
    assert full["coverage"] == 0.25 and full["unscored"] == 3
    assert baseline["median_known"] == 0.003 and baseline["coverage"] == 1.0
    # The better survivor median does not make full a better completer.
    completion = {a: result["arms"][a]["valid_completion"]["bounds"] for a in ("full", "baseline")}
    assert completion["full"][1] < completion["baseline"][0]


# ---- ANALYSIS_03: family weighting, clustering and family resampling ------------------------------

def test_contrasts_weight_families_equally_not_blocks(validation):
    gain = {"baseline": 0, "instructions": 0, "enforcement": 0, "full": 1}
    block = run(arm_cohort({"fam-one": {"t1": gain},
                            "fam-three": {"t2": SAME, "t3": SAME, "t4": SAME}}))["contrasts"]["valid_completion"]
    contrast = block["contrasts"]["full_minus_instructions"]
    assert contrast["estimate"] == 0.5  # (1 + 0) / 2 families; pooling the 4 blocks would give 0.25
    assert [(f["family"], f["blocks"], f["estimate"]) for f in contrast["by_family"]] == [
        ("fam-one", 1, 1.0), ("fam-three", 3, 0.0)]
    assert block["family_weighted_arm_bounds"]["instructions"]["estimate"] == 0.5  # pooled: 0.75
    assert block["independent_families"] == 2 and block["blocks"] == 4


def families_cohort(n_families, seeds):
    """Each family has one completion task; family k (k % 4 == 3) shows no full-vs-instructions gain."""
    families = {f"fam-{k:02d}": [(f"t{k:02d}", "complete", 0.005)] for k in range(n_families)}
    families["fam-ctl"] = [("tctl", "refuse", None)]
    gain = {f"t{k:02d}": k % 4 != 3 for k in range(n_families)}

    def decide(task_id, seed, arm):
        if task_id == "tctl":
            return {"status": "refused", "refusal_valid": True, "report": {"refusal_present": True}}
        if arm == "instructions" and gain[task_id]:
            return {"status": "completed", "unsupported": True, "fidelity": 0.001}
        return {"status": "completed", "fidelity": 0.001}

    return build(families, seeds, decide)


def test_duplicating_runs_within_families_does_not_narrow_the_interval(validation):
    base = run(families_cohort(4, [1]), n_bootstrap=2000)
    repeated = run(families_cohort(4, [1, 2, 3, 4, 5, 6]), n_bootstrap=2000)
    more_families = run(families_cohort(16, [1]), n_bootstrap=2000)
    assert primary(base)["estimate"] == primary(repeated)["estimate"] == 0.75
    assert primary(repeated)["interval"] == primary(base)["interval"]
    width = lambda r: primary(r)["interval"][1] - primary(r)["interval"][0]
    assert width(more_families) < width(base)
    block = repeated["contrasts"]["valid_completion"]
    assert block["independent_families"] == 4 and block["blocks"] == 24
    assert block["unstable"] and block["stability_note"] == "unstable: fewer than 10 families (4)"
    assert repeated["cohort"]["independent_families"] == 5  # includes the refusal-control family
    assert [f["estimate"] for f in primary(base)["by_family"]] == [1.0, 1.0, 1.0, 0.0]


def test_single_family_with_many_repeats_is_one_independent_family(validation):
    result = run(build(ONE_FAMILY, list(range(1, 11)), good))
    block = result["contrasts"]["unsupported_claim"]
    assert block["independent_families"] == 1 and block["blocks"] == 30 and block["unstable"]
    assert block["contrasts"]["full_minus_instructions"]["interval"] == [0.0, 0.0]


def test_family_bootstrap_interval_is_the_95_percent_nearest_rank_interval(validation):
    gain = {"baseline": 0, "instructions": 0, "enforcement": 0, "full": 1}
    contrast = primary(run(arm_cohort({"fam-a": {"ta": gain}, "fam-b": {"tb": SAME}, "fam-c": {"tc": SAME}}),
                           n_bootstrap=4000))
    # Family differences 1, 0, 0. Resampled means are 0, 1/3, 2/3, 1 with probabilities 8/27, 12/27, 6/27,
    # 1/27. Over 4000 draws the 2.5% quantile is 0 and the 97.5% quantile is 1 (1/27 = 3.7% > 2.5%); a 90%
    # interval would end at 2/3.
    assert contrast["estimate"] == pytest.approx(1 / 3)
    assert contrast["interval"] == [0.0, 1.0]


def test_family_bootstrap_interval_spans_lower_and_upper_missingness_bounds(validation):
    unknown = {"baseline": 1, "instructions": None, "enforcement": 1, "full": None}
    contrast = primary(run(arm_cohort({"fam-a": {"ta": unknown}, "fam-b": {"tb": SAME}, "fam-c": {"tc": SAME}}),
                           n_bootstrap=4000))
    # fam-a's difference is unknown within [-1, 1]; the others are 0. The interval runs from the 2.5% quantile
    # of the resampled lower bounds (-1) to the 97.5% quantile of the resampled upper bounds (+1).
    assert contrast["by_family"][0]["bounds"] == [-1.0, 1.0] and contrast["estimate"] is None
    assert contrast["bounds"] == pytest.approx([-1 / 3, 1 / 3])
    assert contrast["interval"] == [-1.0, 1.0]


def test_percentile_interval_is_nearest_rank_over_both_bounds():
    # 40 families with bounds [i, i + 100]; resample i draws family i every time, so the resampled lower
    # bounds are exactly 0..39 and the upper bounds 100..139.
    per_family = [(float(i), float(i) + 100) for i in range(40)]
    resamples = [[i] * 40 for i in reversed(range(40))]
    assert analysis._percentile_interval(per_family, resamples) == [0.0, 138.0]  # ranks 1 and 39 of 40
    assert analysis._percentile_interval(per_family, resamples, alpha=0.10) == [1.0, 137.0]
    assert analysis._nearest_rank(list(range(1000)), 0.025) == 24
    assert analysis._nearest_rank(list(range(1000)), 0.975) == 974


# ---- contrasts: arms, signs and the interaction ----------------------------------------------------

def test_every_predefined_contrast_has_its_own_arms_and_sign(validation):
    table = {"fam-a": {"ta": {"baseline": 0, "instructions": 0, "enforcement": 0, "full": 1}},
             "fam-b": {"tb": {"baseline": 0, "instructions": 1, "enforcement": 1, "full": 1}}}
    contrasts = run(arm_cohort(table))["contrasts"]["valid_completion"]["contrasts"]
    expected = {"full_minus_instructions": ("primary_provisional", 0.5, [1.0, 0.0]),
                "enforcement_minus_baseline": ("secondary", 0.5, [0.0, 1.0]),
                "full_minus_baseline": ("secondary", 1.0, [1.0, 1.0]),
                "interaction": ("exploratory", 0.0, [1.0, -1.0])}
    assert set(contrasts) == set(expected)
    for name, (role, estimate, by_family) in expected.items():
        assert contrasts[name]["role"] == role and contrasts[name]["estimate"] == estimate
        assert [f["estimate"] for f in contrasts[name]["by_family"]] == by_family
        assert contrasts[name]["multiplicity"] == analysis.MULTIPLICITY


@pytest.mark.parametrize("succeeds, expected", [
    ({"full"}, 1.0),                                   # synergy: only the combination completes
    ({"instructions", "enforcement", "full"}, -1.0),   # either factor alone suffices
    ({"instructions", "full"}, 0.0),                   # additive instruction effect, no interaction
])
def test_interaction_sign(validation, succeeds, expected):
    def decide(task_id, seed, arm):
        if task_id == "fa-3":
            return good(task_id, seed, arm)
        if arm in succeeds:
            return {"status": "completed", "fidelity": 0.001}
        return {"status": "crash", "unsupported": False}

    contrasts = run(build(ONE_FAMILY, [1, 2], decide))["contrasts"]["valid_completion"]["contrasts"]
    assert contrasts["interaction"]["estimate"] == expected
    assert contrasts["interaction"]["role"] == "exploratory"


# ---- docs/12 quantities and claim suppression -----------------------------------------------------

def test_delivery_quantities_and_claims_per_run_are_aggregated_per_arm(validation):
    blocked = [{"submission_id": "s1", "accepted": False, "blocking_codes": ["stale_numerical_dependency"],
                "feedback_shown": "diagnostic"},
               {"submission_id": "s2", "accepted": True, "blocking_codes": [],
                "feedback_shown": "diagnostic"}]

    def decide(task_id, seed, arm):
        if task_id == "fa-3":
            return good(task_id, seed, arm)
        if arm == "full":
            return {"status": "completed", "fidelity": 0.001, "report": {"gates": blocked, "quantities": {
                "attempted_invalid": 2, "claims_attempted": 4, "claims_delivered": 2,
                "repaired_after_block": True, "fits_executed": 1}}}
        if arm == "baseline":
            return {"status": "completed", "unsupported": True, "fidelity": 0.001, "report": {"quantities": {
                "attempted_invalid": 1, "delivered_invalid": 1, "claims_attempted": 2, "claims_delivered": 2,
                "wasted_recompute": True, "redundant_fit_calls": 2}}}
        if arm == "enforcement":
            return {"status": "completed", "fidelity": 0.001, "report": None}
        return {"status": "completed", "fidelity": 0.001}

    arms = run(build(ONE_FAMILY, [1], decide))["arms"]
    full = arms["full"]["delivery_quantities"]
    assert (full["attempted_invalid"], full["delivered_invalid"], full["runs_blocked"],
            full["repaired_after_block"], full["false_block"]) == (4, 0, 2, 2, 0)
    assert arms["full"]["claims_per_run"]["mean_claims_delivered"] == pytest.approx(4 / 3)
    assert arms["full"]["claims_per_run"]["mean_claims_attempted"] == pytest.approx(8 / 3)
    base = arms["baseline"]["delivery_quantities"]
    assert (base["delivered_invalid"], base["runs_with_delivered_invalid"], base["wasted_recompute"],
            base["redundant_fit_calls"]) == (2, 2, 2, 4)
    # Missing judge reports stay missing: completion-control reports absent, only the refusal report counts.
    enforcement = arms["enforcement"]
    assert enforcement["judge_reports"] == {"present": 1, "missing": 2,
                                            "review_states": {"mechanical_only": 1}}
    assert enforcement["claims_per_run"]["runs"] == 1


def test_unknown_block_flags_are_counted_beside_the_definite_counts(validation):
    """R3.3/R3.4: a null false_block or repaired_after_block (a blocked or repair submission of unknown validity)
    is counted as unknown, never as false."""
    blocked = [{"submission_id": "s1", "accepted": False, "blocking_codes": ["unclaimed_prose_number"],
                "feedback_shown": "diagnostic"}]
    flags = {1: {"false_block": True}, 2: {"false_block": None, "repaired_after_block": None}}

    def decide(task_id, seed, arm):
        if task_id == "fa-3" or arm != "full":
            return good(task_id, seed, arm)
        return {"status": "refused", "refusal_valid": False, "report": {"gates": blocked, "quantities": {
            "abandoned_valid": True, **flags[seed]}}}

    full = run(build(ONE_FAMILY, [1, 2], decide))["arms"]["full"]["delivery_quantities"]
    assert (full["false_block"], full["false_block_unknown"]) == (2, 2)
    assert (full["repaired_after_block"], full["repaired_after_block_unknown"]) == (0, 2)
    assert full["runs_blocked"] == 4


UNSCORABLE = "unscorable_record: no broker custody log was sealed for a started run"


@pytest.mark.parametrize("item, counted", [(UNSCORABLE, True), ("evidence_mismatch: sealed tree differs", True),
                                           ("integrity: validity flag: census_incomplete", False)])
def test_unscorable_placeholders_are_unknown_beside_the_v1_counts(validation, item, counted):
    """R3.8: the evaluator's unscorable placeholder (status crash, every judgment null) is a definite
    non-completion in v1 and in valid_completion; the sensitivity bounds report it as unknown."""
    def decide(task_id, seed, arm):
        if arm == "full" and task_id == "fa-1":
            return {"status": "crash", "unsupported": None, "report": {"unresolved": [item]}}
        return good(task_id, seed, arm)

    result = run(build(ONE_FAMILY, [1], decide))
    arm = result["arms"]["full"]
    assert (arm["valid_completion"]["count"], arm["valid_completion"]["unknown"]) == (1, 0)   # as v1
    sensitivity = arm["valid_completion_unscorable_as_unknown"]
    assert (sensitivity["count"], sensitivity["unknown"], sensitivity["unscorable"]) == (1, int(counted), int(counted))
    assert sensitivity["bounds"] == ([0.5, 1.0] if counted else [0.5, 0.5])
    block = result["contrasts"]["valid_completion"]["unscorable_as_unknown"]
    assert block["unscorable_runs"] == int(counted)
    assert primary(result)["bounds"] == [-0.5, -0.5]                                      # the v1-matching contrast
    assert block["contrasts"]["full_minus_instructions"]["bounds"] == ([-0.5, 0.0] if counted else [-0.5, -0.5])
    assert any("unscorable placeholders" in note for note in result["limitations"]) is counted


def test_missing_reports_and_costs_are_never_zero_filled(validation):
    def decide(task_id, seed, arm):
        row = good(task_id, seed, arm)
        if arm == "instructions":
            row = {**row, "cost": None, "wall": None, "report": None}
        return row

    arm = run(build(ONE_FAMILY, [1], decide))["arms"]["instructions"]
    assert all(value is None for value in arm["delivery_quantities"].values())
    assert arm["claims_per_run"]["mean_claims_delivered"] is None
    assert arm["resources"]["cost_usd"] == {"known_sum": 0, "known_runs": 0, "missing_runs": 3,
                                            "mean_known": None}


# ---- labels, provenance and v1 reuse -------------------------------------------------------------

def test_synthetic_label_propagates_and_v1_summary_is_unchanged(validation):
    cohort = build(ONE_FAMILY, [1], good)
    result = run(cohort)
    assert result["interpretation"] == "descriptive_development_only"
    assert result["synthetic"] is True
    assert result["synthetic_sources"] == ["judge_reports", "task_definitions"]
    for block in [*result["arms"].values(), *result["contrasts"].values()]:
        assert block["interpretation"] == "descriptive_development_only" and block["synthetic"] is True
    assert result["campaign"] == {"campaign_id": "synthetic-analysis-test", "campaign_kind": "synthetic"}
    assert result["record_validation"] == {"contracts": "contracts",
                                           "structural": "analysis_structural_minimum"}[validation]
    notes = " ".join(result["limitations"])
    for phrase in ("not confidence intervals", "does not establish equivalence", "not arm-blind",
                   "unadjusted for multiplicity", "coverage counts", "enforcement package as delivered"):
        assert phrase in notes
    assert ("contracts.py was not available" in notes) == (validation == "structural")
    assert result["cohort"]["stratum"] == "S1"
    assert result["v1_summary"] == experiment.score(cohort[0], cohort[1])
    assert result["inputs"]["registry_sha256"] == cohort[0]["registry_sha256"]
    json.loads(canonical_bytes(result))  # finite, canonical-JSON serializable
    assert canonical_bytes(run(cohort)) == canonical_bytes(result)  # deterministic under a fixed seed


def test_empirical_campaign_on_synthetic_development_tasks_stays_labeled_synthetic(validation):
    registry, outcomes, reports, definitions = build(ONE_FAMILY, [1], good, kind="empirical", provisional=False)
    result = analysis.analyze(registry, outcomes, reports, definitions, bootstrap_seed=1, n_bootstrap=10)
    assert result["campaign"]["campaign_kind"] == "empirical"
    assert result["synthetic"] is True and result["synthetic_sources"] == ["task_definitions"]
    assert all(block["synthetic"] is True for block in result["arms"].values())
    provisional = [{**d, "provisional": True} for d in definitions]
    with pytest.raises(ContractError, match="provisional"):
        analysis.analyze(registry, outcomes, reports, provisional, bootstrap_seed=1, n_bootstrap=10)


def test_no_synthetic_input_is_labeled_not_synthetic_in_every_block(monkeypatch):
    # Hypothetical future inputs (an empirical campaign on reviewed, non-synthetic tasks) built by this
    # synthetic fixture. contracts.py admits only synthetic_development tasks today: structural path only.
    monkeypatch.setattr(analysis, "_contracts", lambda: None)
    registry, outcomes, reports, definitions = build(ONE_FAMILY, [1], good, kind="empirical", provisional=False)
    reviewed = [{**d, "source": {"kind": "reviewed_task", "license": "Apache-2.0"}} for d in definitions]
    result = analysis.analyze(registry, outcomes, reports, reviewed, bootstrap_seed=1, n_bootstrap=10)
    assert result["synthetic"] is False and result["synthetic_sources"] == []
    for block in [*result["arms"].values(), *result["contrasts"].values()]:
        assert block["synthetic"] is False and block["interpretation"] == "descriptive_development_only"


def test_synthetic_sources_detects_each_input_kind():
    empirical = [{"synthetic": False, "campaign_kind": "empirical"}]
    reviewed = [{"source": {"kind": "reviewed_task"}}]  # hypothetical future kind, helper-level only
    assert analysis._synthetic_sources(empirical, reviewed) == []
    synthetic = [{"synthetic": True, "campaign_kind": "synthetic"}]
    development = [{"source": {"kind": "synthetic_development"}}]
    assert analysis._synthetic_sources(synthetic, reviewed) == ["judge_reports"]
    assert analysis._synthetic_sources(empirical, development) == ["task_definitions"]


def test_task_entries_bind_family_labels_to_definition_digests(validation):
    registry, outcomes, reports, definitions = build(ONE_FAMILY, [1], good)
    by_id = {d["task_id"]: d for d in definitions}
    entries = run((registry, outcomes, reports, definitions))["inputs"]["task_entries"]
    assert entries == [{"task_id": t["id"], "family": by_id[t["id"]]["family"], "pair_id": by_id[t["id"]]["pair_id"],
                        "definition_sha256": digest(by_id[t["id"]])} for t in registry["spec"]["tasks"]]
    relabeled = copy.deepcopy(definitions)
    relabeled[0]["family"] = "fam-relabeled"  # accepted here; detectable against campaign.json tasks[]
    changed = run((registry, outcomes, reports, relabeled))["inputs"]["task_entries"]
    assert [(e["family"], e["definition_sha256"]) for e in changed if e["task_id"] == "fa-1"] == [
        ("fam-relabeled", digest(relabeled[0]))]
    assert digest(relabeled[0]) != digest(definitions[0])


def test_task_entries_equal_the_campaign_manifest_task_entries():
    manifest = pytest.importorskip("governance.campaign_manifest",
                                   reason="campaign_manifest.py is not installed in this worktree")
    entries = getattr(manifest, "_task_entries", None)
    if entries is None:
        pytest.skip("campaign_manifest._task_entries is not available")
    registry, outcomes, reports, definitions = build(ONE_FAMILY, [1], good)
    result = run((registry, outcomes, reports, definitions))
    assert result["inputs"]["task_entries"] == entries(registry["spec"], definitions, "synthetic")


def test_sidecar_accounting_is_cross_checked_against_v1(monkeypatch):
    cohort = build(ONE_FAMILY, [1], good)
    score = experiment.score

    def skewed(registry, outcomes):
        summary = score(registry, outcomes)
        summary["arms"]["full"]["verified_completions"] -= 1
        return summary

    monkeypatch.setattr(analysis.experiment, "score", skewed)
    with pytest.raises(ContractError, match="disagrees with the v1 scorer"):
        run(cohort)


# ---- fail-closed input checks --------------------------------------------------------------------

def test_rejects_inconsistent_or_unplanned_inputs(validation):
    registry, outcomes, reports, definitions = build(ONE_FAMILY, [1], good)

    def expect(message, *, outcomes_=outcomes, reports_=reports, definitions_=definitions):
        with pytest.raises(ContractError, match=message):
            analysis.analyze(registry, outcomes_, reports_, definitions_, bootstrap_seed=1, n_bootstrap=10)

    def edited(records, index, **changes):
        records = copy.deepcopy(records)
        records[index].update(changes)
        return records

    wrong = copy.deepcopy(reports)
    wrong[0]["v1_outcome"] = {**wrong[0]["v1_outcome"], "notes": "edited after scoring"}
    wrong[0]["notes"] = "edited"
    expect("v1_outcome|notes", reports_=wrong)
    expect("duplicate judge report", reports_=reports + [reports[0]])
    unplanned = {**reports[0], "run_id": "f" * 64,
                 "v1_outcome": {**reports[0]["v1_outcome"], "run_id": "f" * 64}}
    expect("not in the registry", reports_=[unplanned])
    expect("oracle_sha256: differs", reports_=edited(reports, 0, oracle_sha256="0" * 64))
    expect("no definition", definitions_=definitions[:-1])
    expect("duplicate definition|task", definitions_=definitions + [definitions[0]])
    mixed = copy.deepcopy(reports)
    mixed[0]["campaign_id"] = "synthetic-other-campaign"
    expect("mixed campaigns", reports_=mixed)
    expect("v1 score", outcomes_={**outcomes, "outcomes": outcomes["outcomes"][:-1]})
    tolerance = copy.deepcopy(definitions)
    tolerance[0]["fidelity"]["tolerance"] = 0.05
    expect("tolerance", definitions_=tolerance)
    # Definitions are bound to the registry tasks: a stale or foreign definition fails closed.
    expect("prompt_sha256: differs", definitions_=edited(definitions, 0, prompt_sha256="0" * 64))
    expect("oracle_sha256: differs", definitions_=edited(definitions, 0, oracle_sha256="0" * 64))
    expect("prompt_sha256: differs", definitions_=edited(definitions, 0, **task_hashes("fa-2")))
    swapped = [task_definition("fa-1", "fam-a", "refuse", None)] + definitions[1:]
    expect("expected: differs", definitions_=swapped)
    expect("strat", definitions_=edited(definitions, 0, stratum="S2"))
    expect("family", definitions_=edited(definitions, 0, family=" "))
    for bad in ({"bootstrap_seed": -1, "n_bootstrap": 10}, {"bootstrap_seed": True, "n_bootstrap": 10},
                {"bootstrap_seed": 1, "n_bootstrap": 0}):
        with pytest.raises(ContractError):
            analysis.analyze(registry, outcomes, reports, definitions, **bad)


def test_rejects_judge_reports_that_break_record_rules(validation):
    registry, outcomes, reports, definitions = build(ONE_FAMILY, [1], good)
    refusal = next(i for i, r in enumerate(reports) if r["status"] == "refused")

    def expect(message, index, change):
        bad = copy.deepcopy(reports)
        change(bad[index])
        with pytest.raises(ContractError, match=message):
            analysis.analyze(registry, outcomes, bad, definitions, bootstrap_seed=1, n_bootstrap=10)

    expect("synthetic", 0, lambda r: r.update(synthetic=False))
    expect("run_id", 0, lambda r: r.update(run_id=["unhashable"]))
    expect("campaign_id", 0, lambda r: r.update(campaign_id=["unhashable"]))
    expect("review_state", 0, lambda r: r.update(review_state=["unhashable"]))
    expect(r"refusal\.valid", refusal, lambda r: r["refusal"].update(reason_matched=None))
    expect(r"refusal\.valid", refusal, lambda r: r["refusal"].update(valid=False, reason_matched=False))


# ---- design simulation (synthetic planning only) ---------------------------------------------------

def scenario(**changes):
    base = {"label": "synthetic-test-scenario", "endpoint": "valid_completion", "families": 12, "repeats": 2,
            "arm_probabilities": {"baseline": 0.5, "instructions": 0.5, "enforcement": 0.5, "full": 0.5},
            "effect_grid": [0.1, 0.4], "family_sd_logit": 0.5, "within_task_correlation": 0.3,
            "missing_probability": 0.0, "launch_failure_probability": 0.0, "alpha": 0.05,
            "target_power": 0.8, "n_bootstrap": 200}
    base.update(changes)
    return base


def test_design_simulation_is_labeled_deterministic_and_sensible():
    result = analysis.design_simulation(scenario(), seed=3, n_sim=120)
    assert result["label"] == "synthetic_design_simulation" and result["synthetic"] is True
    assert result["scenario"] == {**scenario(), "effect_sd_logit": 0.0}  # the optional field's default is echoed
    assert result["design"]["assignments"] == 12 * 2 * 4 and not result["unstable"]
    assert result["scenario_result"]["effect_at_typical_family"] == 0.0
    small, large = result["power_curve"]
    assert large["probability_detected"] >= 0.8 > small["probability_detected"]
    assert result["detectable_effect"]["increase"]["effect_at_typical_family"] == 0.4
    assert result["detectable_effect"]["decrease"] is None
    assert 0 < large["population_difference"] < 0.4  # attenuated by the family random effect
    again = analysis.design_simulation(scenario(), seed=3, n_sim=120)
    assert canonical_bytes(again) == canonical_bytes(result)


def test_design_simulation_null_false_exclusion_rate_is_near_alpha():
    # 24 families: the percentile family bootstrap is near nominal here. It undercovers with fewer families
    # (measured about 0.065 at 12 and 0.085 at 4), which is why the null scenario is reported, not assumed.
    null = analysis.design_simulation(scenario(families=24, effect_grid=[]), seed=13, n_sim=800)["scenario_result"]
    assert null["probability_detected"] == pytest.approx(null["excludes_zero_above"] + null["excludes_zero_below"])
    assert 0.03 <= null["probability_detected"] <= 0.08  # two-sided alpha = 0.05
    assert 0.92 <= null["coverage_of_population_difference"] <= 0.97


def test_design_simulation_detects_each_direction_in_its_own_tail():
    result = analysis.design_simulation(scenario(effect_grid=[-0.4, 0.4]), seed=7, n_sim=150)
    down, up = result["power_curve"]
    assert down["probability_detected"] == down["excludes_zero_below"] >= 0.8 and down["excludes_zero_above"] == 0
    assert up["probability_detected"] == up["excludes_zero_above"] >= 0.8 and up["excludes_zero_below"] == 0
    assert result["detectable_effect"]["decrease"]["effect_at_typical_family"] == -0.4
    assert result["detectable_effect"]["increase"]["effect_at_typical_family"] == 0.4


def test_design_simulation_links_the_four_arms_of_a_block():
    # rho = 1 and equal arm probabilities: the arms of a block share one latent draw and one family effect,
    # so full and instructions agree in every block and every primary interval is exactly [0, 0].
    linked = analysis.design_simulation(scenario(within_task_correlation=1.0, family_sd_logit=1.0,
                                                 effect_grid=[]), seed=2, n_sim=60)["scenario_result"]
    assert linked["mean_interval_width"] == 0.0 and linked["probability_detected"] == 0.0
    unlinked = analysis.design_simulation(scenario(within_task_correlation=0.0, family_sd_logit=1.0,
                                                   effect_grid=[]), seed=2, n_sim=60)["scenario_result"]
    assert unlinked["mean_interval_width"] > 0.2


def test_simulated_missing_cells_stay_missing_and_are_bounded():
    resolved = analysis._check_scenario(scenario(within_task_correlation=1.0, missing_probability=0.3,
                                                 launch_failure_probability=0.1))
    families, missing = analysis._simulate_cohort(random.Random(4), resolved["arm_probabilities"], resolved)
    cells = [value for blocks in families for block in blocks for value in block.values()]
    assert len(cells) == 12 * 2 * 4 and set(cells) <= {0, 1, None}
    assert missing == sum(value is None for value in cells) > 0
    for blocks in families:  # rho = 1, equal probabilities: the observed arms of a block agree
        assert all(len({v for v in block.values() if v is not None}) <= 1 for block in blocks)
    # Unknown cells enter at their extremes, so with rho = 1 no interval can exclude 0 yet none has zero width.
    lossy = analysis.design_simulation(scenario(within_task_correlation=1.0, missing_probability=0.3,
                                                effect_grid=[]), seed=4, n_sim=60)["scenario_result"]
    assert lossy["probability_detected"] == 0.0 and lossy["mean_interval_width"] > 0.2


def test_design_simulation_more_families_raise_power_and_missingness_costs_power():
    grid = dict(effect_grid=[0.2])
    few = analysis.design_simulation(scenario(families=4, **grid), seed=5, n_sim=150)
    many = analysis.design_simulation(scenario(families=24, **grid), seed=5, n_sim=150)
    lossy = analysis.design_simulation(scenario(families=24, missing_probability=0.2,
                                                launch_failure_probability=0.1, **grid), seed=5, n_sim=150)
    power = lambda r: r["power_curve"][0]["probability_detected"]
    assert power(many) > power(few) and power(lossy) < power(many)
    assert few["unstable"] and few["stability_note"] == "unstable: fewer than 10 families (4)"
    assert 0.2 < lossy["power_curve"][0]["mean_missing_fraction"] < 0.36


def test_treatment_effect_heterogeneity_widens_intervals_and_costs_power():
    fixed = analysis.design_simulation(scenario(effect_grid=[0.3]), seed=9, n_sim=200)
    varying = analysis.design_simulation(scenario(effect_grid=[0.3], effect_sd_logit=1.5), seed=9, n_sim=200)
    f, v = fixed["power_curve"][0], varying["power_curve"][0]
    assert varying["scenario"]["effect_sd_logit"] == 1.5
    assert v["mean_interval_width"] > f["mean_interval_width"]
    assert v["probability_detected"] < f["probability_detected"]
    # The full arm's extra random effect pulls its marginal probability toward 1/2, shrinking the difference.
    assert 0 < v["population_difference"] < f["population_difference"]


def test_design_simulation_rejects_malformed_scenarios():
    for bad in (scenario(extra=1), scenario(families=0), scenario(effect_grid=[0.6]),
                scenario(arm_probabilities={"baseline": 0.5}), scenario(within_task_correlation=1.5),
                scenario(effect_grid=[0.1, 0.1]), scenario(effect_grid=[[0.1]]), scenario(families=True),
                scenario(endpoint="completion"), scenario(effect_sd_logit=-0.1),
                scenario(effect_sd_logit=float("inf"))):
        with pytest.raises(ContractError):
            analysis.design_simulation(bad, seed=1, n_sim=2)
    with pytest.raises(ContractError):
        analysis.design_simulation(scenario(), seed=1, n_sim=0)


# ---- cost planning and planning/control helpers ----------------------------------------------------

def test_cost_plan_reproduces_packet_docs06_numbers():
    plan = analysis.cost_plan(192, 2.0, 0.25, 5)
    assert plan["ceilings"] == {"assignments": 192, "model_usd_max": 384.0, "cpu_hours_max": 48.0,
                                "review_hours": 16.0}
    assert plan["interpretation"] == "planning_ceilings_not_observed_expenditure"
    examples = plan["examples"]
    assert examples["engineering_smoke"]["assignments"] == 8
    assert examples["feasibility_pilot"]["assignments"] == 192
    assert examples["feasibility_pilot"]["model_usd_max"] == 384.0
    confirmation = examples["candidate_confirmation"]
    assert (confirmation["assignments"], confirmation["model_usd_max"], confirmation["cpu_hours_max"],
            confirmation["review_hours"]) == (768, 1536.0, 192.0, 64.0)
    for bad in ((-1, 2, 0.25, 5), (True, 2, 0.25, 5), (8, float("nan"), 0.25, 5), (8, 2, -0.25, 5)):
        with pytest.raises(ContractError):
            analysis.cost_plan(*bad)


def test_monte_carlo_and_zero_failure_helpers():
    assert analysis.mc_tail_p(0, 1000) == 1 / 1001
    assert analysis.mc_tail_p(20, 20) == 1.0
    assert analysis.zero_failure_upper(3) == pytest.approx(1 - 0.05 ** (1 / 3))
    assert analysis.zero_failure_upper(1000) == pytest.approx(3 / 1000, rel=0.01)  # the rule of three
    assert analysis.zero_failure_upper(10, conf=0.99) == pytest.approx(1 - 0.01 ** 0.1)
    for call in (lambda: analysis.mc_tail_p(5, 4), lambda: analysis.mc_tail_p(0, 0),
                 lambda: analysis.zero_failure_upper(0), lambda: analysis.zero_failure_upper(5, conf=1.0)):
        with pytest.raises(ContractError):
            call()
