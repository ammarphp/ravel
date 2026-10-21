"""Statistics situations exercised with inert synthetic likelihoods and real fits.

Low counts in an exclusion escalate to toy CLs; in an estimate the small-count
regime qualifies the asymptotic interval (the interval-regime check).
"""
from copy import deepcopy
import json
import subprocess
import sys

import numpy as np
import pytest

from ravel.limits import attach_limits
from ravel.physics import pyhf_exclude as exclude
from ravel.physics.inference import exclusion_statistics, model_checks, profile, situations, uncertainty
from ravel.validation import statistical_calibration


@pytest.fixture(autouse=True)
def numerical_state():
    previous = exclude.pyhf.get_backend()
    escalated = exclude.robust_optimizer.escalated
    random_state = np.random.get_state()
    try:
        exclude.robust_optimizer.escalated = False
        exclude.pyhf.set_backend("numpy", exclude.robust_optimizer(maxiter=200000), precision="64b")
        yield
    finally:
        exclude.pyhf.set_backend(*previous)
        exclude.robust_optimizer.escalated = escalated
        np.random.set_state(random_state)


def write_json(path, value):
    path.write_text(json.dumps(value))
    return str(path)


def assessment(record, name):
    return next(r for r in record["assessment"]["situations"] if r["situation"] == name)


def choice(record, name):
    return next(r for r in record["decision"]["choices"] if r["situation"] == name)


def check(record, name):
    return next(r for r in record["validity"]["checks"] if r["check"] == name)


def assert_document(document):
    assert situations.audit(document["statistics"]) == []
    statements = document["uncertainty"]
    for statement in statements if isinstance(statements, list) else [statements]:
        assert uncertainty.statement_errors(statement) == []


def workspace(n=100, b=100, s=20, *, modifiers=(), bounds=(0, 10), free_background=False):
    background_modifiers = list(deepcopy(modifiers))
    if free_background:
        background_modifiers.append({"name": "background_scale", "type": "normfactor", "data": None})
    return {"version": "1.0.0", "channels": [{"name": "region", "samples": [
        {"name": "signal", "data": [s], "modifiers": [{"name": "mu", "type": "normfactor", "data": None}]},
        {"name": "background", "data": [b], "modifiers": background_modifiers}]}],
        "observations": [{"name": "region", "data": [n]}],
        "measurements": [{"name": "measurement", "config": {"poi": "mu", "parameters": [
            {"name": "mu", "bounds": [list(bounds)], "inits": [1.0]}]}}]}


def normsys(name="source", relative=.1):
    return {"name": name, "type": "normsys", "data": {"hi": 1 + relative, "lo": 1 - relative}}


def run_exclusion(tmp_path, monkeypatch, mode, *, srs=None, spec=None, registry=None, extra=()):
    tmp_path.mkdir(parents=True, exist_ok=True)
    args = ["pyhf_exclude", mode, "--out", str(tmp_path / "out")]
    if spec is not None:
        # The signal is added by a JSON patch, exercising the same loader as production.
        background = deepcopy(spec)
        signal = background["channels"][0]["samples"].pop(0)
        patch = [{"op": "add", "path": "/channels/0/samples/0", "value": signal}]
        args += ["--bkg", write_json(tmp_path / "workspace.json", background),
                 "--patch", write_json(tmp_path / "patch.json", patch)]
    else:
        args += ["--srs", write_json(tmp_path / "yields.json", srs)]
    if registry is not None:
        args += ["--systematics", write_json(tmp_path / "sources.json", registry), "--regions-exclusive"]
    monkeypatch.setattr(sys, "argv", args + list(extra))
    try:
        exclude.main()
    except SystemExit as exc:
        assert exc.code == 3
        exit_code = 3
    else:
        exit_code = 0
    document = json.loads((tmp_path / "out" / "exclusion.json").read_text())
    assert_document(document)
    assert (exit_code == 3) == (document["statistics"]["validity"]["outcome"] == "held")
    return document


def run_estimation(tmp_path, spec, *, patch=None, parameters=("mu",), points=11, process=False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    args = ["--workspace", write_json(tmp_path / "workspace.json", spec),
            "--out", str(tmp_path / "estimation.json"), "--points", str(points), "--level", "0.6827"]
    if patch is not None:
        args += ["--patch", write_json(tmp_path / "patch.json", patch)]
    for parameter in parameters:
        args += ["--parameter", parameter]
    if process:
        completed = subprocess.run([sys.executable, "-m", "ravel.physics.inference.profile", *args],
                                   capture_output=True, text=True, timeout=60)
        code = completed.returncode
        assert code in (0, 3), completed.stdout + completed.stderr
    else:
        code = profile.main(args)
    document = json.loads((tmp_path / "estimation.json").read_text())
    assert document["schema_version"] == 1 and document["kind"] == "estimation"
    assert_document(document)
    assert (code == 3) == (document["statistics"]["validity"]["outcome"] == "held")
    return document, code


def source_registry(correlation="correlated"):
    return {"schema_version": 1, "absent": [], "sources": [
        {"name": "normalization", "kind": "normsys", "relative": .1,
         "applies_to": {"samples": ["background"], "regions": "all"},
         "correlation": correlation, "origin": "requester-assumption",
         "statement": "synthetic normalization uncertainty"}]}


def test_low_counts(tmp_path, monkeypatch):
    large = run_exclusion(tmp_path / "large", monkeypatch, "counting",
                          srs=[dict(name="region", n=100, b=100, db=10, s=20)])
    assert "low-counts" not in {r["situation"] for r in large["statistics"]["assessment"]["situations"]}
    assert large["statistics"]["validity"]["outcome"] == "valid"

    small = [dict(name="region", n=2, b=1.5, db=.2, s=2)]
    toys = run_exclusion(tmp_path / "toys", monkeypatch, "counting", srs=small,
                         extra=["--toys", "100", "--toy-seed", "11"])
    record = toys["statistics"]
    detected = assessment(record, "low-counts")
    assert detected["evidence"]["bins"][0]["observed"] == 2
    assert detected["evidence"]["bins"][0]["channel"] == "region"  # the reported region, not the model's channel
    assert situations.result_facts_errors(record, {"region": toys["per_sr"]["region"]["n"]}) == []
    assert detected["evidence"]["bins"][0]["background"] == pytest.approx(1.5)
    assert "asymptotic-regime" in detected["methods"][0]["passed_over"]
    assert choice(record, "low-counts")["method"] == "toy-cls"
    assert choice(record, "low-counts")["origin"] == "escalation"
    assert record["evidence"]["toys"]["status"] == "run"
    precision = check(record, "toy-mc-precision")
    assert precision["status"] in {"pass", "fail"}
    assert record["validity"]["outcome"] == ("valid" if all(
        c["status"] == "pass" for c in record["validity"]["checks"]) else "qualified")

    refused = run_exclusion(tmp_path / "budget", monkeypatch, "counting", srs=small,
                            extra=["--toys", "50", "--toy-max-seconds", "0.001"])["statistics"]
    toy_method = next(m for m in assessment(refused, "low-counts")["methods"] if m["method"] == "toy-cls")
    assert toy_method["available"] is False and "budget" in toy_method["unavailable_reason"]
    assert refused["evidence"]["budget_refusals"][0]["bound"] == "seconds"
    assert choice(refused, "low-counts")["method"] == "asymptotic-cls"
    assert choice(refused, "low-counts")["origin"] == "fallback"
    assert check(refused, "asymptotic-regime")["status"] == "fail"
    assert refused["validity"]["outcome"] == "qualified"
    assert situations.CHECKS["asymptotic-regime"].qualification in situations.labels(refused)

    explicit = run_exclusion(tmp_path / "seat", monkeypatch, "counting", srs=small,
                             extra=["--cls-calculator", "asymptotic"])["statistics"]
    seat = choice(explicit, "low-counts")
    assert seat["method"] == "asymptotic-cls" and seat["origin"] == "seat" and seat["seat"]
    assert seat["justification"] == exclusion_statistics.CALCULATOR_JUSTIFICATION
    assert check(explicit, "asymptotic-regime")["status"] == "fail"
    assert explicit["validity"]["outcome"] == "qualified"


def test_systematic_nuisances(tmp_path, monkeypatch):
    modifiers = [normsys("first", .1), normsys("second", .05)]
    nominal = run_exclusion(tmp_path / "nominal", monkeypatch, "likelihood",
                            spec=workspace(modifiers=modifiers))["statistics"]
    assert assessment(nominal, "systematic-nuisances")["evidence"]["sources"] == ["first", "second"]
    assert choice(nominal, "systematic-nuisances")["method"] == "profiled-nuisances"
    assert choice(nominal, "systematic-nuisances")["origin"] == "default"
    assert set(nominal["evidence"]["pulls"]) == {"first", "second"}
    assert nominal["evidence"]["pull_fit_valid"] is True
    assert check(nominal, "pulls-within-limit")["status"] == "pass"
    assert nominal["validity"]["outcome"] == "valid"
    tension = run_exclusion(tmp_path / "tension", monkeypatch, "likelihood",
                            spec=workspace(n=220, modifiers=modifiers))["statistics"]
    assert max(map(abs, tension["evidence"]["pulls"].values())) > 3
    assert check(tension, "pulls-within-limit")["status"] == "fail"
    assert tension["validity"]["outcome"] == "qualified"
    assert situations.CHECKS["pulls-within-limit"].qualification in situations.labels(tension)

    bracketed = run_exclusion(tmp_path / "bracket", monkeypatch, "constructed",
                              srs=[dict(name="left", n=100, b=100, db=10, s=20),
                                   dict(name="right", n=80, b=80, db=8, s=10)],
                              registry=source_registry("unknown"))
    record = bracketed["statistics"]
    assert assessment(record, "systematic-nuisances")["evidence"]["unknown_correlation"] == ["normalization"]
    assert "correlation-declared" in assessment(record, "systematic-nuisances")["methods"][0]["passed_over"]
    assert choice(record, "systematic-nuisances")["method"] == "correlation-bracketing"
    assert choice(record, "systematic-nuisances")["origin"] == "escalation"
    bracket = bracketed["correlation_bracket"]
    assert len(bracket["variants"]) == 2
    assert bracket["reported"] == max(bracket["variants"].values()) == bracketed["exp_limits"][2]
    assert bracket["variants"][bracket["reported_variant"]] == bracket["reported"]
    assert check(record, "bracket-envelope")["status"] == "pass"
    assert record["validity"]["outcome"] == "qualified"
    assert any("endpoint sensitivity" in label for label in situations.labels(record))


def test_model_validation(tmp_path, monkeypatch):
    constructed = run_exclusion(tmp_path / "constructed", monkeypatch, "constructed",
                                srs=[dict(name="region", n=100, b=100, db=10, s=20)],
                                registry=source_registry())
    record = constructed["statistics"]
    assert assessment(record, "model-validation")["evidence"]["model_origin"] == "constructed"
    assert choice(record, "model-validation")["method"] == "signal-injection"
    assert choice(record, "model-validation")["origin"] == "default"
    assert record["evidence"]["injection"] and all(r["valid"] for r in record["evidence"]["injection"])
    assert check(record, "signal-injection")["status"] == "pass"
    assert record["validity"]["outcome"] == "valid"

    degenerate = workspace(free_background=True)
    ws = exclude.pyhf.Workspace(degenerate)
    model = ws.model()
    # Only injection validity is under test here; these are inert limit placeholders.
    result = attach_limits({"obs_limit": 2., "exp_limits": [1., 1.5, 2., 2.5, 3.],
                            "limit_status": {"observed": "resolved", "expected": ["resolved"] * 5}})
    exclusion_statistics.attach(result, model=model, data=ws.data(model), mode="constructed")
    assert_document(result)
    held = result["statistics"]
    assert choice(held, "model-validation")["method"] == "signal-injection"
    assert any(not r["valid"] for r in held["evidence"]["injection"])
    assert check(held, "signal-injection")["status"] == "fail"
    assert held["validity"]["outcome"] == "held"
    estimate, code = run_estimation(tmp_path / "degenerate", degenerate, process=True)
    assert code == 3 and check(estimate["statistics"], "signal-injection")["status"] == "fail"

    # Removing data-only constants must preserve likelihood ratios for both auxiliary laws.
    for spec in (workspace(n=1, b=1e-20, s=1e-20), workspace(modifiers=[normsys()]),
                 workspace(modifiers=[{"name": "simulation", "type": "shapesys", "data": [10.]}])):
        ws = exclude.pyhf.Workspace(spec)
        model = ws.model()
        stable = model_checks._DevianceModel(model)
        nominal = np.asarray(model.config.suggested_init(), float)
        shifted = nominal + .1
        data = ws.data(model)
        np.testing.assert_allclose(stable.logpdf(shifted, data) - stable.logpdf(nominal, data),
                                   model.logpdf(shifted, data) - model.logpdf(nominal, data), atol=1e-10)

    signal, background = 20., 20.
    model, _ = exclude.model_from_counting(dict(name="region", n=40, s=signal, b=background,
                                                db=1e-6 * background))
    previous_backend = exclude.pyhf.get_backend()
    coverage = model_checks.exclusion_coverage(model, mu_true=1., ntoys=300, seed=7)
    assert exclude.pyhf.get_backend() == previous_backend
    exact = statistical_calibration.known_background_poisson_coverage(1., signal, background)
    assert exact["status"] == "resolved"
    assert coverage["failed_toys"] == 0 and coverage["toys"] == 300
    assert coverage["false_exclusion_lower"] <= exact["retained_rejected_probability"] <= coverage["false_exclusion_upper"]
    facts = situations.facts_from_model(model, [40.] + model.config.auxdata, origin="supplied")
    coverage_record = situations.record(facts, {"coverage": coverage}, choices={"model-validation": {
        "method": "coverage-toys", "justification": "compare seeded toys with the known-background counting law"}})
    assert choice(coverage_record, "model-validation")["origin"] == "seat"
    assert check(coverage_record, "coverage-at-truth")["status"] == "pass"
    assert coverage_record["validity"]["outcome"] == "valid"
    assert situations.audit(coverage_record) == []
    known, _ = exclude.model_from_counting(dict(name="region", n=40, s=signal, b=background, db=0))
    assert model_checks.exclusion_coverage(known, ntoys=20, seed=7)["failed_toys"] == 0


def test_parameter_estimation(tmp_path):
    gaussian = workspace(n=1000, b=1000, s=100, bounds=(-5, 10), modifiers=[normsys(relative=.01)])
    ws = exclude.pyhf.Workspace(gaussian)
    model = ws.model()
    start = np.asarray(model.config.suggested_init(), float)
    before = start.copy()
    model_checks._fit(model, ws.data(model), init=start, fixed={model.config.poi_index: .25})
    np.testing.assert_array_equal(start, before)
    # Exercise optional patch loading and repeated --parameter arguments on scalar parameters.
    document, code = run_estimation(tmp_path / "gaussian", gaussian, patch=[], parameters=("mu", "source"))
    record = document["statistics"]
    assert assessment(record, "parameter-estimation")["evidence"]["parameters"] == ["mu", "source"]
    assert record["facts"]["model_origin"] == "supplied"
    assert choice(record, "parameter-estimation")["method"] == "quadratic-errors"
    assert choice(record, "parameter-estimation")["origin"] == "default"
    assert check(record, "parabolic-profile")["status"] == "pass"
    assert code == 0 and record["validity"]["outcome"] == "valid"
    assert document["parameters"][0]["best_fit"] == pytest.approx(0, abs=1e-3)
    for row, statement in zip(document["parameters"], document["uncertainty"]):
        assert {"stat_low", "stat_high", "syst_low", "syst_high"} <= row.keys()
        assert {"statistical", "systematic", "method"} == {c["kind"] for c in statement["components"]}

    small, code = run_estimation(tmp_path / "small", workspace(n=3, b=1, s=2))
    record = small["statistics"]
    selected = choice(record, "parameter-estimation")
    assert assessment(record, "parameter-estimation")["default"] == "quadratic-errors"
    assert selected["method"] == "profile-likelihood" and selected["origin"] == "escalation"
    assert selected["escalations"] == [{"from": "quadratic-errors", "to": "profile-likelihood",
                                       "check": "parabolic-profile"}]
    assert situations.CHECKS["parabolic-profile"].evaluate(record["facts"], record["evidence"])["status"] == "fail"
    assert check(record, "interval-resolved")["status"] == "pass"
    assert check(record, "away-from-boundary")["status"] == "pass"
    # An estimate owes no CLs calibration; its small-count interval is qualified, not held.
    assert "low-counts" not in {r["situation"] for r in record["assessment"]["situations"]}
    assert check(record, "asymptotic-interval-regime")["status"] == "fail"
    assert situations.CHECKS["asymptotic-interval-regime"].qualification in situations.labels(record)
    assert code == 0 and record["validity"]["outcome"] == "qualified"

    boundary, code = run_estimation(tmp_path / "boundary", workspace(n=0, b=1, s=2))
    record = boundary["statistics"]
    assert boundary["parameters"][0]["best_fit"] == pytest.approx(0, abs=1e-4)
    assert choice(record, "parameter-estimation")["method"] == "profile-likelihood"
    assert check(record, "away-from-boundary")["status"] == "fail"
    assert situations.CHECKS["away-from-boundary"].qualification in situations.labels(record)
    assert situations.CHECKS["asymptotic-interval-regime"].qualification in situations.labels(record)
    assert code == 0 and record["validity"]["outcome"] == "qualified"


def test_limited_mc_statistics():
    for modelled in (True, False):
        modifiers = [{"name": "simulation", "type": "staterror", "data": [30.]}] if modelled else []
        ws = exclude.pyhf.Workspace(workspace(modifiers=modifiers))
        model = ws.model()
        if modelled:
            result = exclude.compute(model, ws.data(model), n_curve=3)
            exclusion_statistics.attach(result, model=model, data=ws.data(model), mode="likelihood")
            assert_document(result)
            record = result["statistics"]
        else:
            facts = situations.facts_from_model(model, ws.data(model), origin="published")
            assert facts["mc_statistics"] == "none"
            bins = deepcopy(facts["bins"])
            bins[0]["mc"] = {"sumw": 100., "sumw2": 30. ** 2}
            facts = situations.make_facts(**{k: v for k, v in {**facts, "bins": bins}.items()
                                            if k not in ("kind", "schema_version")})
            record = situations.record(facts, {"mc_statistics": "none"})
        detected = assessment(record, "limited-mc-statistics")
        assert detected["evidence"]["flagged"][0]["flags"] == ["relative-mc-uncertainty"]
        assert choice(record, "limited-mc-statistics")["method"] == "mc-staterror"
        assert choice(record, "limited-mc-statistics")["origin"] == "default"
        assert check(record, "mc-moments-available")["status"] == "pass"
        assert check(record, "mc-statistics-modelled")["status"] == ("pass" if modelled else "fail")
        assert record["validity"]["outcome"] == ("valid" if modelled else "qualified")
        assert situations.audit(record) == []
        if not modelled:
            assert situations.CHECKS["mc-statistics-modelled"].qualification in situations.labels(record)


def test_uncertainty_statements(tmp_path, monkeypatch):
    document = run_exclusion(tmp_path, monkeypatch, "counting",
                             srs=[dict(name="region", n=100, b=100, db=20, s=20)])
    components = {c["name"]: c for c in document["uncertainty"]["components"]}
    impact = components["systematic-impact"]
    assert impact["status"] == "evaluated" and impact["fixed_parameters"]
    assert 0 < impact["stat_only_expected_median"] < document["exp_limits"][2]
    assert impact["relative_impact"] > 0
    assert {"statistical", "systematic", "method"} == {
        c["kind"] for c in document["uncertainty"]["components"]}
