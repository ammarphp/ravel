"""Step adapters of the analysis route: the evidence each step leaves (P6, P3, P1, E04, E05, E14, C28-C30)."""
from __future__ import annotations

import pytest

from statistics_records import with_statistics

from ravel.controller.routes.analysis import evidence
from p09_support import (Store, adopt, adopt_prepare, compile_plan, context, contract, outcome, reading,
                              route_analysis)


@pytest.fixture
def run(tmp_path):
    store = Store()
    read, con = reading(), contract("reproduce")
    plan = compile_plan("analysis", read, con)
    states = adopt_prepare(store, tmp_path, plan)
    return store, plan, context(store, tmp_path, plan, read, con, states)


def _step(plan, step_id):
    return next(s for s in plan["steps"] if s["id"] == step_id)


def _codes(errors):
    return {e["code"] for e in errors}


def test_synthesis_refuses_missing_recipe_rows_and_accepts_the_complete_ledger(run, tmp_path, monkeypatch):
    from ravel.controller.routes.analysis import checkins
    store, plan, ctx = run
    current = {"unknown": [{"id": "R1", "status": "unknown"}],
               "deviated": [{"id": "R2", "status": "deviated"}]}
    monkeypatch.setattr(checkins, "recipe_rows", lambda _: current)
    deck = _step(plan, "synthesize")
    adopt(store, tmp_path, deck["id"], "outputs/results.json", {"headline": "value retained", "numbers": []})
    errors = evidence.check(deck, None, ctx)
    assert [e["code"] for e in errors] == ["recipe_rows_dropped", "recipe_rows_dropped"]
    assert all(e["row"] == "C36" and e["step"] == deck["id"] for e in errors)
    assert "1 unknown recipe ledger row(s)" in errors[0]["message"]
    assert "1 deviated recipe ledger row(s)" in errors[1]["message"]
    adopt(store, tmp_path, deck["id"], "outputs/results.json",
          {"headline": "value retained", "numbers": [], "recipe_ledger": current})
    assert evidence.check(deck, None, ctx) == []


def test_step_02_complete_prepare_evidence_holds(run):
    store, plan, ctx = run
    for step_id in ("env", "inputs.census", "inputs.route", "inputs.traps", "inputs.figures", "inputs.cost"):
        assert evidence.check(_step(plan, step_id), None, ctx) == [], step_id


def test_step_02_unadopted_output_is_missing_evidence(tmp_path):
    store = Store()
    read, con = reading(), contract("reproduce")
    plan = compile_plan("analysis", read, con)
    errors = evidence.check(_step(plan, "inputs.route"), None, context(store, tmp_path, plan, read, con, {}))
    assert _codes(errors) == {"evidence_missing"}


def test_step_02_changed_bytes_after_custody_are_refused(run, tmp_path):
    store, plan, ctx = run
    target = tmp_path / "steps" / "inputs.route" / "outputs" / "route_analysis.json"
    target.write_text(target.read_text().replace("best-sr-counting", "combined-counting"))
    errors = evidence.check(_step(plan, "inputs.route"), None, ctx)
    assert any("differs from the bytes" in e["message"] for e in errors)


def test_step_01_environment_must_account_for_every_planned_operation(run, tmp_path):
    store, plan, ctx = run
    adopt(store, tmp_path, "env", "outputs/environment.json",
          {"tools": [{"name": "event generator", "status": "missing", "required": True}], "operations": []})
    codes = _codes(evidence.check(_step(plan, "env"), None, ctx))
    assert {"environment_operations_uncovered", "environment_tool_absent"} <= codes


def test_e04_census_rung_without_status_and_error_read_as_absence(run, tmp_path):
    """P6: every rung keeps its status; an unreachable source is never recorded as absent."""
    store, plan, ctx = run
    adopt(store, tmp_path, "inputs.census", "outputs/inputs/resource_census.json",
          {"rungs": {"hepdata": {"status": "OK"}, "routines": {}, "code-search": {"status": "ERROR outage-or-block",
                                                                                   "absent": True}}})
    codes = _codes(evidence.check(_step(plan, "inputs.census"), None, ctx))
    assert {"census_rung_unstated", "census_error_as_absence"} <= codes


def test_e04_route_analysis_mismatch_must_be_a_bounded_approximation(run, tmp_path):
    """E04: a routine selecting another final state is admitted only as a stated bounded approximation."""
    store, plan, ctx = run
    adopt(store, tmp_path, "inputs.route", "outputs/route_analysis.json",
          route_analysis(mismatches=[{"what": "the routine selects one lepton, the request two"}]))
    assert "route_analysis_unbounded_mismatch" in _codes(evidence.check(_step(plan, "inputs.route"), None, ctx))
    adopt(store, tmp_path, "inputs.route", "outputs/route_analysis.json",
          route_analysis(mismatches=[{"what": "one lepton, not two", "approximation": "X1"}],
                         approximations=[{"id": "X1", "reason": "no two-lepton routine exists",
                                          "bound": "acceptance differs by at most a stated factor"}]))
    assert evidence.check(_step(plan, "inputs.route"), None, ctx) == []


def test_e04_route_analysis_left_undecided_without_escalation_is_refused(run, tmp_path):
    store, plan, ctx = run
    adopt(store, tmp_path, "inputs.route", "outputs/route_analysis.json", route_analysis(stat_mode="TBD-judgment"))
    assert "route_analysis_undecided" in _codes(evidence.check(_step(plan, "inputs.route"), None, ctx))


@pytest.mark.parametrize("field,requested,selected", [("final_state", "two jets", "three leptons"),
                                                       ("energy", "13 TeV", "8 TeV")])
def test_structured_fixed_input_is_compared_even_without_declared_mismatches(run, tmp_path, field, requested, selected):
    store, plan, ctx = run
    text = f"Keep {field} fixed at {requested}."
    ctx["contract"]["prompt"] = text
    ctx["reading"]["constraints"] = [{"id": "K1", "type": "keep_fixed", "value": {field: requested},
                                       "evidence": [{"start": 0, "end": len(text), "text": text}]}]
    def codes(**extra):
        adopt(store, tmp_path, "inputs.route", "outputs/route_analysis.json", route_analysis(**{field: selected}, **extra))
        return _codes(evidence.check(_step(plan, "inputs.route"), None, ctx))
    assert "route_analysis_constraint_mismatch" in codes()
    approximation = {"id": "X1", "reason": "retained comparison establishes a limited substitute",
                     "bound": "restricted to the stated domain and uncertainty"}
    assert "route_analysis_constraint_mismatch" in codes(approximations=[approximation])
    mismatch = {"constraint": "K1", "field": field, "requested": requested, "selected": selected, "approximation": "X1"}
    assert codes(approximations=[approximation], mismatches=[mismatch]) == set()
    for key, wrong in (("constraint", "K2"), ("field", "model"), ("selected", "different"), ("requested", "different")):
        assert "route_analysis_constraint_mismatch" in codes(approximations=[approximation], mismatches=[{**mismatch, key: wrong}])
    assert "route_analysis_constraint_mismatch" in codes(approximations=[{**approximation, "bound": "TBD"}], mismatches=[mismatch])
    selected = requested
    assert codes() == set()
    ctx["reading"]["constraints"][0]["evidence"][0]["text"] = "different request"
    assert "route_analysis_constraint_unbound" in codes()


def test_e05_figure_target_needs_published_axes_and_source(run, tmp_path):
    """E05: axis scales come from the actual reference; a target from memory without axes is refused."""
    store, plan, ctx = run
    adopt(store, tmp_path, "inputs.figures", "outputs/figure_target.json",
          {"targets": [{"figure_id": "Figure 3", "role": "summary"}]})
    codes = _codes(evidence.check(_step(plan, "inputs.figures"), None, ctx))
    assert {"figure_axes_unrecorded", "figure_source_missing"} <= codes


def test_e05_figure_panels_requested_must_all_be_targets(tmp_path):
    store = Store()
    read = reading()
    read["deliverables"].append({"id": "D3", "artifact": {"kind": "figure", "require": {}}, "claim_kind": "exclusion"})
    con = contract("reproduce")
    plan = compile_plan("analysis", read, con)
    states = adopt_prepare(store, tmp_path, plan)
    errors = evidence.check(_step(plan, "inputs.figures"), None, context(store, tmp_path, plan, read, con, states))
    assert "figure_panels_dropped" in _codes(errors)


def test_e05_waypoint_proposal_must_be_substantive(run, tmp_path):
    store, plan, ctx = run
    adopt(store, tmp_path, "inputs.figures", "outputs/waypoint.json", {"element": "TBD"})
    assert "waypoint_incomplete" in _codes(evidence.check(_step(plan, "inputs.figures"), None, ctx))


def test_a06_cost_record_must_cover_the_highest_rung(run, tmp_path):
    store, plan, ctx = run
    adopt(store, tmp_path, "inputs.cost", "outputs/cost_preflight.json",
          {"mode": "smoke", "status": "uncalibrated", "basis": "pilot pending"})
    assert "cost_rung_mismatch" in _codes(evidence.check(_step(plan, "inputs.cost"), None, ctx))


def test_e14_recast_needs_a_bound_current_qualification(run, tmp_path):
    """E14: an installed routine is not qualified by its presence."""
    store, plan, ctx = run
    step = _step(plan, "recast.smoke")
    adopt(store, tmp_path, step["id"], "outputs/smoke/recast.json",
          {"samples": ["smoke"], "events": 1000, "lhe_check": {"status": "PASS"},
           "detector_mode": "simpleanalysis-delphes-native"})
    assert "qualification_unbound" in _codes(evidence.check(step, outcome(step), ctx))
    adopt(store, tmp_path, step["id"], "outputs/smoke/recast.json",
          {"samples": ["smoke"], "events": 1000, "lhe_check": {"status": "PASS"},
           "qualification": {"routine": "FICTIONAL_ROUTINE_1", "status": "qualified"},
           "detector_mode": "simpleanalysis-delphes-native"})
    assert evidence.check(step, outcome(step), ctx) == []


LIMITS = {"schema_version": 1, "quantity": "signal_strength",
          "observed": {"value": 0.8, "status": "resolved", "bracket": [0.5, 1.0]},
          "expected": [{"value": v, "status": "resolved", "bracket": [v / 2, v * 2]} for v in (0.5, 0.7, 0.9, 1.2, 1.6)],
          "origin": "fixture", "notes": []}


def test_step_07_exclusion_without_prescribed_statistic_delivers_95_cls(run, tmp_path):
    store, plan, ctx = run
    step = _step(plan, "run.full")
    adopt(store, tmp_path, step["id"], "outputs/limits.json", with_statistics(
          {"statistic": "CLs", "confidence_level": 0.95, "limits": LIMITS,
           "detector_mode": "simpleanalysis-delphes-native"}))
    assert evidence.check(step, outcome(step), ctx) == []
    adopt(store, tmp_path, step["id"], "outputs/limits.json",
          {"statistic": "significance", "limits": LIMITS, "detector_mode": "simpleanalysis-delphes-native"})
    assert "statistic_default" in _codes(evidence.check(step, outcome(step), ctx))


def test_step_07_prescribed_statistic_is_the_primary_result(tmp_path):
    store = Store()
    read, con = reading(prescribed="S/sqrt(B+dB^2)"), contract("reproduce")
    plan = compile_plan("analysis", read, con)
    states = adopt_prepare(store, tmp_path, plan)
    ctx = context(store, tmp_path, plan, read, con, states)
    step = _step(plan, "run.full")
    adopt(store, tmp_path, step["id"], "outputs/limits.json",
          {"statistic": "CLs", "limits": LIMITS, "detector_mode": "simpleanalysis-delphes-native"})
    assert "statistic_substituted" in _codes(evidence.check(step, outcome(step), ctx))


def test_c28_comparison_needs_one_pinned_comparator_and_matching_basis(run, tmp_path):
    """C28: one pinned comparator; quantity, basis and unit match; an approved lattice and tolerance."""
    store, plan, ctx = run
    step = _step(plan, "compare.reference")
    good = {"comparator": {"source": "published table 3"}, "lattice": "the published grid", "tolerance": 0.2,
            "basis_manifests": [{"quantity": "cross-section limit", "basis": "per-point", "unit": "fb"},
                                {"quantity": "cross-section limit", "basis": "per-point", "unit": "fb"}],
            "attributions": []}
    adopt(store, tmp_path, step["id"], "outputs/comparison.json", good)
    assert evidence.check(step, outcome(step), ctx) == []
    bad = dict(good, basis_manifests=[good["basis_manifests"][0], dict(good["basis_manifests"][1], unit="pb")],
               comparators=[{"source": "a"}, {"source": "b"}])
    adopt(store, tmp_path, step["id"], "outputs/comparison.json", bad)
    assert {"basis_mismatch", "comparator_unpinned"} <= _codes(evidence.check(step, outcome(step), ctx))


def test_c29_c30_attribution_needs_noise_model_and_registered_replicas(run, tmp_path):
    """C29, C30: residual causes come from registered output, distinct replicas and an approved noise model."""
    store, plan, ctx = run
    step = _step(plan, "compare.reference")
    adopt(store, tmp_path, step["id"], "outputs/comparison.json",
          {"comparator": {"source": "published table 3"}, "lattice": "grid", "tolerance": 0.2,
           "basis_manifests": [{"quantity": "q", "basis": "b", "unit": "u"}] * 2,
           "attributions": [{"cause": "shower model", "model_output": "a hand-typed number", "replicas": ["s1", "s1"],
                             "noise_model": "", "above_noise": False}]})
    codes = _codes(evidence.check(step, outcome(step), ctx))
    assert {"residual_model_unregistered", "replicas_not_distinct", "attribution_below_noise"} <= codes


def test_step_09_verification_records_three_tested_attacks(run, tmp_path):
    """P8: basis, acceptance and statistics attacks, each with how it was tested."""
    store, plan, ctx = run
    step = _step(plan, "verify.adversary")
    adopt(store, tmp_path, step["id"], "outputs/tier_b.json",
          {"attacks": [{"kind": "basis", "attack": "a", "tested_by": "recomputed"},
                       {"kind": "statistics", "attack": "b", "tested_by": ""}]})
    errors = evidence.check(step, outcome(step), ctx)
    assert _codes(errors) == {"attacks_missing"} and "acceptance" in errors[0]["message"]


def test_step_09_tier_a_numbers_trace_to_artifacts(run, tmp_path):
    store, plan, ctx = run
    step = _step(plan, "verify.mechanical")
    adopt(store, tmp_path, step["id"], "outputs/tier_a.json",
          {"verdict": "PASS", "numbers": [{"value": 0.8, "artifact": "run.full:outputs/limits.json"}, {"value": 2}]})
    assert _codes(evidence.check(step, outcome(step), ctx)) == {"tier_a_untraced"}


def test_unknown_adapter_is_refused(run):
    store, plan, ctx = run
    step = dict(_step(plan, "env"), parameters={"adapter": "nonexistent"})
    assert _codes(evidence.check(step, None, ctx)) == {"adapter_unknown"}


def test_step_09_tier_a_fail_cannot_pass_as_completed_verification(run, tmp_path):
    store, plan, ctx = run
    step = _step(plan, "verify.mechanical")
    adopt(store, tmp_path, step["id"], "outputs/tier_a.json", {"verdict": "FAIL", "numbers": []})
    assert _codes(evidence.check(step, outcome(step), ctx)) == {"tier_a_failed"}


def test_step_09_fabricated_and_changed_numerical_sources_are_refused(run, tmp_path):
    store, plan, ctx = run
    step = _step(plan, "verify.mechanical")
    doc = {"verdict": "PASS", "numbers": [{"value": 0.8, "artifact": "run.full:outputs/limits.json"}]}
    adopt(store, tmp_path, step["id"], "outputs/tier_a.json", doc)
    assert _codes(evidence.check(step, outcome(step), ctx)) == {"tier_a_untraced"}
    adopt(store, tmp_path, "run.full", "outputs/limits.json", {"value": 0.8})
    assert evidence.check(step, outcome(step), ctx) == []
    (tmp_path / "steps/run.full/outputs/limits.json").write_text('{"value": 2}')
    assert _codes(evidence.check(step, outcome(step), ctx)) == {"tier_a_untraced"}


def test_step_02_custody_reads_refuse_symlink_ancestors_and_revoked_custody(run, tmp_path):
    from ravel.controller.routes.analysis import common
    store, plan, ctx = run
    artifact = "inputs.route:outputs/route_analysis.json"
    record = common.accepted(store, artifact)
    target = tmp_path / record["destination"]
    raw = target.read_bytes()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / target.name).write_bytes(raw)
    target.unlink()
    target.parent.rmdir()
    target.parent.symlink_to(outside, target_is_directory=True)
    assert "symbolic link" in common.read_output(ctx, "inputs.route", "outputs/route_analysis.json")[2]
    target.parent.unlink()
    target.parent.mkdir()
    target.write_bytes(raw)
    store.append("custody", {**record, "status": "rejected"})
    offered = {"outputs": [{"path": "outputs/route_analysis.json", "sha256": record["sha256"]}]}
    assert "no current accepted" in common.read_output(ctx, "inputs.route", "outputs/route_analysis.json",
                                                      outcome=offered)[2]


def test_c28_empty_equal_basis_manifests_are_refused(run, tmp_path):
    store, plan, ctx = run
    step = _step(plan, "compare.reference")
    adopt(store, tmp_path, step["id"], "outputs/comparison.json", {
        "comparator": {"source": "published table"}, "lattice": "grid", "tolerance": 0.2,
        "basis_manifests": [{}, {}], "attributions": []})
    assert "basis_mismatch" in _codes(evidence.check(step, outcome(step), ctx))


def test_c29_replica_seed_labels_and_artifact_prefix_alone_carry_no_credit(run, tmp_path):
    store, plan, ctx = run
    step = _step(plan, "compare.reference")
    doc = {"comparator": {"source": "published table"}, "lattice": "grid", "tolerance": 0.2,
           "basis_manifests": [{"quantity": "q", "basis": "b", "unit": "u"}] * 2,
           "attributions": [{"cause": "sampling", "model_output": "artifact:producer:model.json",
                             "replicas": ["seed-1", "seed-2"], "noise_model": "approved model", "above_noise": True}]}
    adopt(store, tmp_path, step["id"], "outputs/comparison.json", doc)
    assert {"residual_model_unregistered", "replicas_unregistered"} <= _codes(evidence.check(step, outcome(step), ctx))
    adopt(store, tmp_path, "producer", "model.json", {"model": "sampling"})
    for name in ("replica1.json", "replica2.json"):
        adopt(store, tmp_path, "producer", name, {"replica": name})
    doc["attributions"][0]["replicas"] = ["producer:replica1.json", "producer:replica2.json"]
    adopt(store, tmp_path, step["id"], "outputs/comparison.json", doc)
    assert evidence.check(step, outcome(step), ctx) == []
    doc["attributions"][0]["replicas"] = ["producer:replica1.json", "artifact:producer:replica1.json"]
    adopt(store, tmp_path, step["id"], "outputs/comparison.json", doc)
    assert "replicas_not_distinct" in _codes(evidence.check(step, outcome(step), ctx))
