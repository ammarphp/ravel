"""Synthetic end-to-end controls for the statistics catalogue and non-model situations."""
from copy import deepcopy
from functools import lru_cache
from itertools import product
import json
import math
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from ravel.physics.inference import efficiency, lee, propagation, simplified, situations
from ravel.workflow import stat_mode_decision
from ravel.workflow.science import MODES


ROOT = Path(__file__).resolve().parents[2]
DERIVED = "derived-quantity-propagation"
EFFICIENCY = "efficiency-acceptance"
LEE = "look-elsewhere"
COMBINATION = "combination"
LIKELIHOOD = "likelihood-availability"


@pytest.fixture(autouse=True)
def preserve_numerical_backend():
    # Resolving a provider may import a module that installs its optimizer.
    import pyhf
    previous = pyhf.get_backend()
    try:
        yield
    finally:
        pyhf.set_backend(*previous)


def assessment(record, situation_id):
    return next(r for r in record["assessment"]["situations"] if r["situation"] == situation_id)


def choice(record, situation_id):
    return next(r for r in record["decision"]["choices"] if r["situation"] == situation_id)


def method_row(record, situation_id, method_id):
    return next(r for r in assessment(record, situation_id)["methods"] if r["method"] == method_id)


def check_status(rows, check_id):
    return next(r["status"] for r in rows if r["check"] == check_id)


def valid_check(record, check_id):
    return check_status(record["validity"]["checks"], check_id)


def assert_outcome(record, outcome):
    assert record["validity"]["outcome"] == outcome
    assert situations.audit(record) == []
    if outcome != "valid":
        assert situations.labels(record)


def mild_quantity():
    return {"name": "curved", "expression": "x * y", "inputs": [
        {"name": "x", "value": 4., "error": .08},
        {"name": "y", "value": 8., "error": .16}], "correlation": [[1., .3], [.3, 1.]]}


def propagated_record(definition, *, choices=None, availability=None):
    facts = situations.make_facts(deliverables=["derived-quantity"],
                                  derived=[propagation.facts_entry(definition)])
    results, calls = [], []
    methods = {"linear-propagation": "linear", "sampled-propagation": "sampled",
               "propagation-correlation-bracketing": "bracket"}

    def run(situation_id, method_id, evidence):
        assert situation_id == DERIVED
        result = propagation.propagate(definition, method=methods[method_id], samples=20000, seed=7)
        calls.append(method_id)
        results.append(result)
        return propagation.evidence([result])

    return situations.drive(facts, run, choices=choices, availability=availability), results, calls


def test_catalogue_integrity_and_installed_providers():
    assert situations._consistency_errors() == []
    used_methods, used_checks = set(), set()
    for item in situations.SITUATIONS:
        used_methods.update(item.methods)
        assert item.fallback["outcome"] in ("qualified", "held")
        assert item.fallback["qualification"].strip()
    assert used_methods == set(situations.METHODS)
    for method_id, method in situations.METHODS.items():
        status = situations.provider_status(method_id, resolve_entrypoints=True)
        assert status["available"], (method_id, status)
        assert set(method.provider.modes) <= set(MODES), method_id
        used_checks.update(method.checks)
    assert used_checks == set(situations.CHECKS)


@lru_cache(maxsize=None)
def cli_help(script, subcommand=None):
    args = [sys.executable, str(ROOT / "src/ravel/physics" / script)]
    if subcommand:
        args.append(subcommand)
    result = subprocess.run([*args, "--help"], cwd=ROOT, text=True,
                            capture_output=True, timeout=20)
    assert result.returncode == 0, (args, result.stdout, result.stderr)
    return result.stdout


def test_every_provider_command_names_a_real_cli():
    commands = {c for m in situations.METHODS.values() for c in m.provider.commands}
    assert commands
    for command in sorted(commands):
        parts = shlex.split(command)
        if parts[0] == "pyhf_exclude":
            assert len(parts) >= 2
            assert "usage:" in cli_help("pyhf_exclude.py", parts[1])
        else:
            assert parts[0] == "sa2json_native", command
            assert parts[1] == "--mc-stat" and len(parts) == 3
            help_text = cli_help("sa2json_native.py")
            assert "--mc-stat" in help_text
            # Check the choice on the option's own usage line, not incidental prose.
            option = next(line for line in help_text.splitlines() if "--mc-stat {" in line)
            assert parts[2] in option.split("{", 1)[1].split("}", 1)[0].split(",")


def test_catalogue_export_is_current():
    assert situations.main(["catalogue", "--check"]) == 0
    path = ROOT / "src/ravel/data/inference/statistics_situations.json"
    assert json.loads(path.read_text()) == situations.export()
    assert situations.catalogue_sha256() == situations.digest(situations.export())


def likelihood_inputs(full, covariance, yields, exclusive=False):
    review = None if full in ("absent", "unassessed") else {
        "path": "inputs/appropriateness.json", "verdict": full,
        "blocking_codes": ["selection-changed"] if full == "inappropriate" else []}
    has_full, has_cov = full != "absent", covariance != "absent"
    has_yields, registry = yields != "nothing", yields == "registry"
    source = "synthetic covariance declaration" if covariance == "sourced" else None
    evidence = {
        "published_likelihood": {"available": has_full, "path": "inputs/workspace.json" if has_full else None,
                                 "appropriateness": review},
        "covariance": {"available": has_cov, "path": "inputs/covariance.json" if has_cov else None,
                       "source": source},
        "systematics_registry": {"available": registry, "path": "inputs/systematics.json" if registry else None},
        "yields": {"available": has_yields, "path": "inputs/yields.json" if has_yields else None},
        "mutually_exclusive_regions": exclusive}
    facts = situations.make_facts(deliverables=["exclusion"], likelihood={
        "full": has_full, "appropriateness": review["verdict"] if review else None,
        "covariance": has_cov, "covariance_source": source, "yields": has_yields,
        "systematics_registry": registry, "mutually_exclusive_regions": exclusive})
    return evidence, facts


@pytest.mark.parametrize("full,covariance,yields,exclusive", list(product(
    ("appropriate", "inappropriate", "absent", "unassessed"),
    ("sourced", "unsourced", "absent"), ("registry", "yields", "nothing"), (False, True))))
def test_likelihood_ladder_matches_mode_decision(full, covariance, yields, exclusive):
    evidence, facts = likelihood_inputs(full, covariance, yields, exclusive)
    ladder = stat_mode_decision.decide(evidence)
    assessed = situations.assess(facts)
    selected = assessed["situations"][0]["default"]
    assert tuple(situations.STAT_MODE_OF_METHOD[m] for m in situations.situation(LIKELIHOOD).methods) == (
        stat_mode_decision.LADDER)
    mapped = situations.STAT_MODE_OF_METHOD.get(selected)
    if mapped == "best-sr-counting" and exclusive:
        mapped = "combined-counting"
    assert mapped == ladder["selected"]
    if selected is None:
        validity = situations.verify(facts, situations.decide(assessed), {})
        assert ladder["status"] == "unresolved"
        assert validity["outcome"] == "held"
        assert validity["holds"] == [{"situation": LIKELIHOOD,
                                      "label": situations.situation(LIKELIHOOD).fallback["qualification"]}]


@pytest.fixture(scope="module")
def valid_record():
    record, _, _ = propagated_record(mild_quantity())
    assert_outcome(record, "valid")
    return record


@pytest.mark.parametrize("tampering,error", [
    ("facts", "the recorded assessment does not follow from the recorded facts"),
    ("removed-choice", "the decision must choose exactly once for every detected situation"),
    ("changed-method", "recorded choice 'sampled-propagation' (default) does not follow"),
    ("unknown-edge", "neither the default, a justified seat choice nor a recorded escalation"),
    ("non-escalating-check", "neither the default, a justified seat choice nor a recorded escalation"),
    ("passing-check", "cites linearity, which does not fail on the recorded evidence (pass)"),
    ("evidence", "the recorded validity does not follow from the recorded evidence"),
    ("validity", "the recorded validity does not follow from the recorded evidence"),
    ("catalogue", "another catalogue version"),
])
def test_audit_refuses_tampering(valid_record, tampering, error):
    record = deepcopy(valid_record)
    row = choice(record, DERIVED)
    if tampering == "facts":
        record["facts"]["derived"][0]["inputs"][0]["value"] += 1
    elif tampering == "removed-choice":
        record["decision"]["choices"] = []
    elif tampering == "changed-method":
        row["method"] = "sampled-propagation"
    elif tampering in ("unknown-edge", "non-escalating-check", "passing-check"):
        target = "propagation-correlation-bracketing" if tampering == "unknown-edge" else "sampled-propagation"
        check = "mc-sample-precision" if tampering == "non-escalating-check" else "linearity"
        row.update(method=target, origin="escalation", escalations=[{
            "from": "linear-propagation", "to": target, "check": check}])
        # Recompute the verdict so refusal must come from provenance replay.
        record["validity"] = situations.verify(record["facts"], record["decision"], record["evidence"])
    elif tampering == "evidence":
        record["evidence"]["linearity"][0]["relative_difference"] = .5
        recomputed = situations.verify(record["facts"], record["decision"], record["evidence"])
        assert check_status(recomputed["checks"], "linearity") == "fail"
    elif tampering == "validity":
        record["validity"]["outcome"] = "held"
    elif tampering == "catalogue":
        record["catalogue_sha256"] = "0" * 64
    assert any(error in message for message in situations.audit(record)), situations.audit(record)


@pytest.mark.parametrize("reason,refused_method,admitted", [
    ("provider absent", None, False),
    ("budget exhausted", None, False),
    ("provider absent", "linear-propagation", False),
    ("budget exhausted", "sampled-propagation", False),
    ("budget exhausted", "linear-propagation", True),
])
def test_audit_requires_matching_budget_refusal(valid_record, reason, refused_method, admitted):
    evidence = deepcopy(valid_record["evidence"])
    if refused_method:
        evidence["budget_refusals"] = [{"method": refused_method, "reason": "synthetic budget exhausted"}]
    record = situations.record(valid_record["facts"], evidence, availability={
        "linear-propagation": {"available": False, "reason": reason}})
    assert choice(record, DERIVED)["method"] == "sampled-propagation"
    errors = situations.audit(record)
    if admitted:
        assert errors == []
    else:
        assert any("linear-propagation is recorded unavailable but is installed" in e for e in errors)


def test_derived_quantity_propagation():
    mild = mild_quantity()
    record, results, calls = propagated_record(mild)
    assert assessment(record, DERIVED)["evidence"] == {
        "quantities": ["curved"], "asymmetric_inputs": {}, "unknown_correlation": [], "nonlinear_declared": []}
    assert assessment(record, DERIVED)["default"] == "linear-propagation"
    assert calls == ["linear-propagation"]
    assert valid_check(record, "linearity") == "pass"
    # Independent first-order covariance calculation for x*y.
    sigma = math.sqrt((8 * .08) ** 2 + (4 * .16) ** 2 + 2 * .3 * 8 * 4 * .08 * .16)
    assert results[0]["linear"]["sigma"] == pytest.approx(sigma, rel=1e-7)
    assert results[0]["value"] == 32.
    assert_outcome(record, "valid")

    ratio = {"name": "ratio", "expression": "x / y", "inputs": [
        {"name": "x", "value": 10., "error": .1}, {"name": "y", "value": 5., "error": 2.}]}
    record, results, calls = propagated_record(ratio)
    assert assessment(record, DERIVED)["default"] == "linear-propagation"
    assert assessment(record, DERIVED)["evidence"]["quantities"] == ["ratio"]
    assert results[0]["linearity"]["relative_difference"] > situations.LINEARITY_TOLERANCE
    assert calls == ["linear-propagation", "sampled-propagation"]
    assert choice(record, DERIVED)["escalations"] == [
        {"from": "linear-propagation", "to": "sampled-propagation", "check": "linearity"}]
    assert valid_check(record, "mc-sample-precision") == "pass"
    assert_outcome(record, "valid")

    asymmetric = mild_quantity()
    asymmetric["inputs"][0] = {"name": "x", "value": 4., "error_up": .12, "error_down": .04}
    record, results, calls = propagated_record(asymmetric)
    assert assessment(record, DERIVED)["evidence"]["asymmetric_inputs"] == {"curved": ["x"]}
    linear = method_row(record, DERIVED, "linear-propagation")
    assert check_status(linear["prechecks"], "symmetric-errors") == "fail"
    assert "symmetric-errors" in linear["passed_over"]
    assert assessment(record, DERIVED)["default"] == "sampled-propagation"
    assert calls == ["sampled-propagation"]
    assert valid_check(record, "correlation-known") == valid_check(record, "mc-sample-precision") == "pass"
    assert results[0]["interval"][0] < results[0]["value"] < results[0]["interval"][1]
    assert_outcome(record, "valid")

    unknown = {"name": "sum", "expression": "x + y", "inputs": [
        {"name": "x", "value": 4., "error": .2}, {"name": "y", "value": 8., "error": .3}],
        "unknown_correlations": [["x", "y"]]}
    record, results, calls = propagated_record(unknown)
    assert assessment(record, DERIVED)["evidence"]["unknown_correlation"] == ["sum"]
    assert assessment(record, DERIVED)["default"] == "propagation-correlation-bracketing"
    assert choice(record, DERIVED)["origin"] == "escalation"
    for method in ("linear-propagation", "sampled-propagation"):
        skipped = method_row(record, DERIVED, method)
        assert check_status(skipped["prechecks"], "correlation-known") == "fail"
        assert "correlation-known" in skipped["passed_over"]
    assert calls == ["propagation-correlation-bracketing"]
    bracket = results[0]["correlation_bracket"]
    assert bracket["range"] == [-1., 1.]
    assert len(bracket["variants"]) == 3
    assert all(v["status"] == "evaluated" for v in bracket["details"].values())
    for rho in (-1., 0., 1.):
        sigma = math.sqrt(.2 ** 2 + .3 ** 2 + 2 * rho * .2 * .3)
        assert bracket["details"][f"x~y={rho:g}"]["std"] == pytest.approx(sigma, rel=.03)
    widest = max(bracket["variants"], key=bracket["variants"].get)
    assert bracket["reported"] == max(bracket["variants"].values())
    assert results[0]["interval"] == bracket["details"][widest]["interval"]
    assert valid_check(record, "bracket-envelope") == valid_check(record, "mc-sample-precision") == "pass"
    assert_outcome(record, "valid")

    seat = {DERIVED: {"method": "linear-propagation", "justification": "retain a first-order comparison"}}
    record, _, calls = propagated_record(ratio, choices=seat)
    assert calls == ["linear-propagation"]
    assert choice(record, DERIVED)["origin"] == "seat"
    assert not choice(record, DERIVED).get("escalations")
    assert record["validity"]["escalations"] == []
    assert valid_check(record, "linearity") == "fail"
    assert situations.CHECKS["linearity"].qualification in situations.labels(record)
    assert_outcome(record, "qualified")
    with pytest.raises(situations.StatisticsRecordError, match="nonblank justification"):
        propagated_record(ratio, choices={DERIVED: {"method": "linear-propagation"}})


def test_indefinite_propagation_correlation_is_refused():
    definition = {"name": "sum", "expression": "x + y + z", "inputs": [
        {"name": name, "value": 4., "error": .2} for name in ("x", "y", "z")],
        "correlation": [[1., 1., 0.], [1., 1., 1.], [0., 1., 1.]]}
    with pytest.raises(ValueError, match="correlation matrix"):
        propagation.propagate(definition, method="sampled", samples=20000)


def test_efficiency_acceptance():
    results = []

    def drive(row):
        facts = situations.make_facts(deliverables=["efficiency"], efficiencies=[row])

        def run(situation_id, method_id, evidence):
            assert situation_id == EFFICIENCY
            if row["weighted"]:
                assert method_id == "weighted-efficiency"
            if method_id == "weighted-efficiency":
                result = efficiency.weighted(**row["sums"])
            else:
                method = {"normal-binomial": "normal", "wilson-binomial": "wilson",
                          "clopper-pearson": "clopper-pearson"}[method_id]
                result = efficiency.interval(row["passed"], row["total"], method=method)
            results.append(result)
            return {"efficiency_results": [result]}

        return situations.drive(facts, run)

    record = drive(efficiency.facts_entry("central", passed=500, total=1000))
    assert assessment(record, EFFICIENCY)["evidence"]["efficiencies"] == ["central"]
    assert assessment(record, EFFICIENCY)["default"] == "normal-binomial"
    assert valid_check(record, "normal-approximation") == "pass"
    assert results[-1]["efficiency"] == .5
    assert results[-1]["interval"] == pytest.approx([.5 - math.sqrt(.25 / 1000), .5 + math.sqrt(.25 / 1000)])
    assert_outcome(record, "valid")

    record = drive(efficiency.facts_entry("edge", passed=1, total=100))
    assert assessment(record, EFFICIENCY)["evidence"]["efficiencies"] == ["edge"]
    normal = method_row(record, EFFICIENCY, "normal-binomial")
    assert check_status(normal["prechecks"], "normal-approximation") == "fail"
    assert "normal-approximation" in normal["passed_over"]
    assert assessment(record, EFFICIENCY)["default"] == "wilson-binomial"
    assert valid_check(record, "unweighted-counts") == "pass"
    assert results[-1]["method"] == "wilson"
    assert 0 < results[-1]["interval"][0] < .01 < results[-1]["interval"][1] < 1
    assert_outcome(record, "valid")

    sums = {"sumw_pass": -1., "sumw2_pass": 5., "sumw_fail": 11., "sumw2_fail": 13.}
    record = drive(efficiency.facts_entry("signed", weighted_sums=sums, negative_weights=True))
    assert assessment(record, EFFICIENCY)["evidence"]["negative_weights"] == ["signed"]
    assert assessment(record, EFFICIENCY)["evidence"]["weighted"] == ["signed"]
    assert assessment(record, EFFICIENCY)["default"] == "weighted-efficiency"
    assert valid_check(record, "nonnegative-weights") == "fail"
    assert results[-1]["negative_weight_sum"] is True
    assert results[-1]["efficiency"] == -.1
    assert results[-1]["sigma"] ** 2 == pytest.approx((5 * 1.1 ** 2 + 13 * .1 ** 2) / 100)
    assert situations.CHECKS["nonnegative-weights"].qualification in situations.labels(record)
    assert_outcome(record, "qualified")

    confidence = .683
    exact = efficiency.interval(0, 10, confidence=confidence, method="clopper-pearson")
    assert exact["interval"] == pytest.approx([0., 1 - ((1 - confidence) / 2) ** (1 / 10)])


def test_look_elsewhere():
    values = [0., 1., .1, 2., .2, 4., .1, 9.] + [.1] * 22
    assert len(values) == 30
    results = []

    def drive(claim, scan, *, independent=False, choices=None, dimensions=1):
        facts = situations.make_facts(deliverables=["discovery"], scan={
            "hypotheses": len(scan), "claim": claim, "independent_tests": independent, "dimensions": dimensions})

        def run(situation_id, method_id, evidence):
            assert situation_id == LEE
            if method_id == "sidak-correction":
                local = .5 * math.erfc(math.sqrt(max(scan) / 2))
                result = lee.sidak(local, len(scan))
            else:
                result = lee.global_significance(scan, reference_level=.5)
                if method_id == "local-significance":
                    result = {k: result[k] for k in ("local_p_value", "local_significance", "max_local_q0")}
            results.append(result)
            return {"look_elsewhere": result}

        return situations.drive(facts, run, choices=choices)

    record = drive("local", values)
    assert assessment(record, LEE)["evidence"] == {"hypotheses": 30, "claim": "local"}
    assert assessment(record, LEE)["default"] == "local-significance"
    assert valid_check(record, "local-claim") == "pass"
    assert results[-1]["local_p_value"] == pytest.approx(.5 * math.erfc(3 / math.sqrt(2)))
    assert_outcome(record, "valid")

    record = drive("global", values)
    assert assessment(record, LEE)["evidence"] == {"hypotheses": 30, "claim": "global"}
    local = method_row(record, LEE, "local-significance")
    assert check_status(local["prechecks"], "local-claim") == "fail"
    assert "local-claim" in local["passed_over"]
    assert assessment(record, LEE)["default"] == "trials-factor"
    assert valid_check(record, "upcrossings-observed") == "pass"
    assert results[-1]["upcrossings"] == 4
    expected = .5 * math.erfc(math.sqrt(9 / 2)) + 4 * math.exp(-(9 - .5) / 2)
    assert results[-1]["global_p_value"] == pytest.approx(expected, rel=1e-12)
    assert_outcome(record, "valid")

    record = drive("global", [9.] * 30)
    assert results[-1]["upcrossings"] == 0
    assert valid_check(record, "upcrossings-observed") == "fail"
    assert situations.CHECKS["upcrossings-observed"].qualification in situations.labels(record)
    assert_outcome(record, "qualified")

    record = drive("global", values, independent=True, choices={LEE: {
        "method": "sidak-correction", "justification": "the synthetic tests are independent"}})
    assert choice(record, LEE)["method"] == "sidak-correction"
    assert choice(record, LEE)["origin"] == "seat"
    assert valid_check(record, "independent-tests-declared") == "pass"
    assert results[-1]["global_p_value"] == pytest.approx(1 - (1 - results[-1]["local_p_value"]) ** 30)
    assert_outcome(record, "valid")

    # Upcrossings along a flattened two-dimensional grid are not a trials factor.
    record = drive("global", values, dimensions=2)
    trials = method_row(record, LEE, "trials-factor")
    assert check_status(trials["prechecks"], "one-dimensional-scan") == "fail"
    assert "one-dimensional-scan" in trials["passed_over"]
    assert "independent-tests-declared" in method_row(record, LEE, "sidak-correction")["passed_over"]
    assert choice(record, LEE)["origin"] == "fallback"
    assert situations.situation(LEE).fallback["qualification"] in situations.labels(record)
    assert_outcome(record, "qualified")


def workspace_component(name, kind="normsys"):
    modifier = {"name": "scale", "type": kind,
                "data": {"hi": 1.1, "lo": .9} if kind == "normsys" else {"hi_data": [22.], "lo_data": [18.]}}
    workspace = {"version": "1.0.0", "channels": [{"name": name, "samples": [
        {"name": "background", "data": [20.], "modifiers": [modifier]},
        {"name": "signal", "data": [5.], "modifiers": [{"name": "mu", "type": "normfactor", "data": None}]}]}],
        "observations": [{"name": name, "data": [20.]}],
        "measurements": [{"name": "source", "config": {"poi": "mu", "parameters": []}}]}
    return {"id": name, "workspace": workspace, "measurement": "source",
            "parameter_map": {"scale": "scale", "mu": "mu"}}


def test_combination():
    from ravel.physics import workspace_combination
    statement = "synthetic disjoint event populations with independent Poisson observations"
    outputs, calls = [], []

    def drive(inputs, independence, components=None):
        facts = situations.make_facts(combination={"inputs": inputs, "independence": independence})

        def run(situation_id, method_id, evidence):
            assert situation_id == COMBINATION
            calls.append(method_id)
            if method_id == "independent-combination":
                combined = simplified.combine([
                    simplified.SimplifiedLikelihood([20], [20], [5], [r["id"]], covariance=[[4]]) for r in inputs])
                # Instantiate and evaluate the real independent backend, without a limit scan.
                assert combined.backend() is not None
                assert 0 < combined.cls(1., "observed")[0] < 1
                outputs.append(combined)
            else:
                policy = {"measurement": "combined", "poi": "mu", "independence": independence,
                          "shared_parameters": {"scale": ["a", "b"], "mu": ["a", "b"]}}
                outputs.append(workspace_combination.combine(components, policy))
            return {"combined": {"status": "combined", "inputs": [r["id"] for r in inputs]}}

        return situations.drive(facts, run)

    independent = [{"id": "a", "parameters": {}}, {"id": "b", "parameters": {}}]
    record = drive(independent, statement)
    assert assessment(record, COMBINATION)["evidence"] == {
        "inputs": ["a", "b"], "shared_parameters": {}, "independence": statement}
    assert assessment(record, COMBINATION)["default"] == "independent-combination"
    assert valid_check(record, "independence-declared") == valid_check(record, "no-shared-parameters") == "pass"
    assert valid_check(record, "inputs-combined") == "pass"
    assert outputs[-1].labels == ["a", "b"]
    assert_outcome(record, "valid")

    shared = [{"id": name, "parameters": {"scale": "normsys", "mu": "normfactor"}} for name in ("a", "b")]
    record = drive(shared, statement, [workspace_component("a"), workspace_component("b")])
    assert assessment(record, COMBINATION)["evidence"]["shared_parameters"] == {
        "scale": {"a": "normsys", "b": "normsys"}, "mu": {"a": "normfactor", "b": "normfactor"}}
    skipped = method_row(record, COMBINATION, "independent-combination")
    assert check_status(skipped["prechecks"], "no-shared-parameters") == "fail"
    assert "no-shared-parameters" in skipped["passed_over"]
    assert assessment(record, COMBINATION)["default"] == "joint-likelihood"
    assert valid_check(record, "shared-parameter-consistency") == valid_check(record, "inputs-combined") == "pass"
    assert outputs[-1]["report"]["auxiliary_terms"] == 1
    assert outputs[-1]["report"]["shared_parameters"]["scale"] == ["a", "b"]
    assert_outcome(record, "valid")

    conflict = deepcopy(shared)
    conflict[1]["parameters"]["scale"] = "histosys"
    before = list(calls)
    record = drive(conflict, statement)
    assert "scale" in assessment(record, COMBINATION)["evidence"]["shared_parameters"]
    assert all(not row["eligible"] and row["passed_over"] for row in assessment(record, COMBINATION)["methods"])
    assert check_status(method_row(record, COMBINATION, "joint-likelihood")["prechecks"],
                        "shared-parameter-consistency") == "fail"
    assert choice(record, COMBINATION)["origin"] == "fallback"
    assert choice(record, COMBINATION)["method"] is None
    assert record["validity"]["checks"] == []
    assert calls == before
    assert_outcome(record, "qualified")

    record = drive(independent, None)
    assert assessment(record, COMBINATION)["evidence"]["independence"] is None
    for method in assessment(record, COMBINATION)["methods"]:
        assert check_status(method["prechecks"], "independence-declared") == "fail"
        assert "independence-declared" in method["passed_over"]
    assert choice(record, COMBINATION)["origin"] == "fallback"
    assert calls == before
    assert_outcome(record, "qualified")


def test_likelihood_availability(tmp_path):
    import pyhf
    from ravel.limits import read_limits
    from ravel.physics import pyhf_exclude
    pyhf.set_backend("numpy", pyhf_exclude.robust_optimizer(maxiter=200000), precision="64b")
    yields = [{"name": "a", "n": 20, "b": 20, "db": 2, "s": 5}]
    covariance = {"schema_version": 1, "kind": "background-covariance", "regions": ["a"],
                  "covariance": [[4]], "source": "synthetic covariance declaration"}
    workspace_path, patch_path = tmp_path / "workspace.json", tmp_path / "signal.json"
    workspace_path.write_text(json.dumps(workspace_component("a")["workspace"]))
    patch_path.write_text("[]")
    outputs, calls = {}, []
    declared_absent = {"schema_version": 1, "kind": "reference-limits", "available": False,
                       "reason": "synthetic: no published benchmark limits", "evidence": "synthetic fixture"}

    def drive(full, cov, supplied_yields, *, statement=True, reference=declared_absent):
        _, facts = likelihood_inputs(full, cov, supplied_yields)

        def run(situation_id, method_id, evidence):
            assert situation_id == LIKELIHOOD
            calls.append(method_id)
            if method_id == "published-likelihood":
                model, data = pyhf_exclude.model_from_likelihood(workspace_path, patch_path)
            elif method_id == "simplified-likelihood":
                engine = simplified.from_document(covariance, yields)
            elif method_id == "counting":
                model, data = pyhf_exclude.model_from_counting(yields[0])
            else:
                pytest.fail(f"unexpected provider {method_id}")
            if method_id not in outputs:
                outputs[method_id] = (engine.limits() if method_id == "simplified-likelihood"
                                      else pyhf_exclude.compute(model, data, n_curve=3))
            limits = read_limits(outputs[method_id])
            evidence = {"limits": {"observed": limits.observed.status, "median": limits.expected[2].status}}
            if statement:
                evidence["correlations_statement"] = "synthetic counting constraints are independent"
            if reference is not None and method_id in ("simplified-likelihood", "constructed-likelihood"):
                evidence["reference_closure"] = reference
            return evidence

        return situations.drive(facts, run)

    record = drive("appropriate", "sourced", "yields")
    assert assessment(record, LIKELIHOOD)["evidence"]["appropriateness"] == "appropriate"
    assert assessment(record, LIKELIHOOD)["default"] == "published-likelihood"
    assert valid_check(record, "published-appropriate") == valid_check(record, "limits-resolved") == "pass"
    assert_outcome(record, "valid")

    record = drive("unassessed", "sourced", "yields")
    assert assessment(record, LIKELIHOOD)["evidence"]["covariance_source"] == covariance["source"]
    skipped = method_row(record, LIKELIHOOD, "published-likelihood")
    assert check_status(skipped["prechecks"], "published-appropriate") == "fail"
    assert "appropriateness is not assessed" in skipped["passed_over"]
    assert assessment(record, LIKELIHOOD)["default"] == "simplified-likelihood"
    assert choice(record, LIKELIHOOD)["origin"] == "escalation"
    assert valid_check(record, "covariance-sourced") == valid_check(record, "limits-resolved") == "pass"
    assert valid_check(record, "reference-limits-declared") == valid_check(record, "reference-limit-closure") == "pass"
    assert_outcome(record, "valid")

    # A rung that stands in for the published likelihood without its closure evaluated is qualified.
    record = drive("unassessed", "sourced", "yields", reference=None)
    assert valid_check(record, "reference-limits-declared") == "fail"
    assert situations.CHECKS["reference-limits-declared"].qualification in situations.labels(record)
    assert_outcome(record, "qualified")

    for statement, expected in ((True, "valid"), (False, "qualified")):
        record = drive("absent", "absent", "yields", statement=statement)
        assert assessment(record, LIKELIHOOD)["evidence"]["available"]["yields"] is True
        assert assessment(record, LIKELIHOOD)["default"] == "counting"
        assert all(r["passed_over"] for r in assessment(record, LIKELIHOOD)["methods"][:-1])
        assert valid_check(record, "correlations-stated") == ("pass" if statement else "fail")
        assert valid_check(record, "limits-resolved") == "pass"
        assert_outcome(record, expected)

    before = list(calls)
    record = drive("absent", "absent", "nothing")
    assert not any(assessment(record, LIKELIHOOD)["evidence"]["available"].values())
    assert choice(record, LIKELIHOOD)["method"] is None
    assert choice(record, LIKELIHOOD)["origin"] == "fallback"
    assert record["validity"]["checks"] == []
    assert calls == before
    assert_outcome(record, "held")


def test_a_method_that_does_not_apply_is_passed_over_and_never_escalated_to():
    facts = situations.make_facts(deliverables=["exclusion"], model_origin="simplified",
                                  bins=[{"channel": "SR", "bin": 0, "observed": 2., "background": 1.5}])
    record = situations.record(facts, {"limits": {"observed": "resolved", "median": "resolved"}})
    toys = method_row(record, "low-counts", "toy-cls")
    assert toys["available"] is True and toys["eligible"] is False
    assert toys["inapplicable"] and toys["passed_over"] == toys["inapplicable"]
    assert choice(record, "low-counts")["method"] == "asymptotic-cls"
    assert choice(record, "low-counts")["origin"] == "fallback"
    assert situations.CHECKS["asymptotic-regime"].qualification in situations.labels(record)
    assert_outcome(record, "qualified")
    assert "HistFactory" in situations.export()["methods"]["toy-cls"]["applies"]
    assert situations.export()["methods"]["asymptotic-cls"]["applies"] is None
    # A recorded escalation to it does not recompute, even along a real catalogue edge.
    forged = deepcopy(record)
    row = choice(forged, "low-counts")
    row.update(method="toy-cls", origin="escalation",
               escalations=[{"from": "asymptotic-cls", "to": "toy-cls", "check": "asymptotic-regime"}])
    assert any("does not apply" in e for e in situations.audit(forged))
    # drive never escalates to it: the fallback runs once and is qualified.
    calls = []
    driven = situations.drive(facts, lambda s, m, e: calls.append(m) or {
        "limits": {"observed": "resolved", "median": "resolved"}})
    assert calls == ["asymptotic-cls"] and situations.audit(driven) == []


def test_no_detected_situation_is_valid():
    facts = situations.make_facts()
    assessed = situations.assess(facts)
    assert assessed["situations"] == []
    validity = situations.verify(facts, situations.decide(assessed), {})
    assert validity["outcome"] == "valid"
    assert validity["checks"] == validity["qualifications"] == validity["holds"] == []


@pytest.mark.parametrize("fields,error", [
    ({"extra": True}, "unknown keys"),
    ({"deliverables": ["unsupported"]}, "deliverables must be a list drawn from"),
    ({"deliverables": "exclusion"}, "deliverables must be a list drawn from"),
    ({"systematics": [{"name": "scale", "correlation": "invented"}]}, "has correlation 'invented'"),
    ({"scan": {"hypotheses": 3, "dimensions": 0}}, "scan dimensions must be a positive integer"),
])
def test_facts_schema_refuses_invalid_inputs(fields, error):
    facts = {"schema_version": 1, "kind": "statistics-facts", **fields}
    assert any(error in e for e in situations.facts_errors(facts))
    with pytest.raises(situations.StatisticsRecordError, match=error):
        situations.make_facts(**fields)


@pytest.mark.parametrize("damage", [
    lambda r: r.update(assessment="x"),
    lambda r: r["assessment"].update(situations=[1]),
    lambda r: r["decision"].update(choices=[1, "x"]),
    lambda r: r.update(evidence=[]),
    lambda r: r["validity"].update(checks=None),
])
def test_audit_refuses_a_malformed_record_without_raising(damage):
    facts = situations.make_facts(deliverables=["exclusion"], model_origin="counting", bins=[
        {"channel": "SR", "bin": 0, "observed": 2., "background": 1.5, "background_uncertainty": .5}])
    record = situations.record(facts, {"limits": {"observed": "resolved", "median": "resolved"}})
    assert situations.audit(record) == []
    damage(record)
    assert situations.audit(record)
