"""Portable bounded-adapter controls with a complete synthetic MC census."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import pyhf
import pytest
from scipy.stats import poisson

from ravel.physics import joint_fit as study
from joint_model_fixtures import write_mc

pytestmark = pytest.mark.filterwarnings("ignore:jsonschema.RefResolver is deprecated:DeprecationWarning")


def fixture(tmp_path):
    pyhf.set_backend("numpy", precision="64b")
    source = {"version": "1.0.0", "channels": [],
              "observations": [{"name": "SR", "data": [22]}, {"name": "CR", "data": [28]}],
              "measurements": [{"name": "M", "config": {"poi": "mu", "parameters": []}}]}
    for name, count in [("SR", 10.), ("CR", 20.)]:
        alpha = {"name": "alpha", "type": "normsys", "data": {"hi": 1.1, "lo": .9}}
        source["channels"].append({"name": name, "samples": [
            {"name": "signal", "data": [6.], "modifiers": [{"name": "mu", "type": "normfactor", "data": None}, deepcopy(alpha)]},
            {"name": "background", "data": [count], "modifiers": [{"name": "beta", "type": "normfactor", "data": None}, deepcopy(alpha)]}]})
    background = deepcopy(source)
    for channel in background["channels"]:
        channel["samples"] = channel["samples"][1:]
    def pinned(name, value):
        path = tmp_path / name
        path.write_bytes(study.compact(value))
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    mc_path = write_mc(tmp_path / "MC")
    doc = {"schema_version": 1, "model_id": "synthetic-source-conditioned-adapter", "measurement": "M",
           "background_source": pinned("background.json", background),
           "assumptions": ["Explicit complete synthetic IID MC law.", "Condition alpha at published initial value0; no experimental interpretation."],
           "limits": {"execution_seconds": 60, "fit_budget": {"objective_calls": 12000, "gradient_calls": 600,
                "feasibility_lp_calls": 16, "stationarity_lp_calls": 3, "maxiter": 150, "lp_maxiter": 1000, "wall_seconds": 15}},
           "mu_domain": {"initial": 1., "upper": 10.},
           "cases": [{"point_id": "synthetic", "workspace": pinned("workspace.json", source),
                "signal_samples": {"SR": ["signal"], "CR": ["signal"]}, "free_source": ["beta"],
                "fixed_source": {"alpha": 0.}, "profile_points": [0.],
                "mc_models": [{"id": "N10", "input": {"path": str(mc_path), "sha256": hashlib.sha256(mc_path.read_bytes()).hexdigest()}}]}]}
    input_path = tmp_path / "study.json"
    input_path.write_bytes(study.compact(doc))
    return input_path, doc


def compile_case(path):
    _, doc, _, background, cases = study._capture({"input": str(path)}, path.parent)
    case, workspace_path, workspace, models = cases[0]
    return study.construct(doc, case, workspace_path, workspace, background, models[0][1])


def test_actual_tiny_adapter_preserves_all_factors_and_matches_saturated_oracle(tmp_path):
    path, _ = fixture(tmp_path)
    report = study.run({"input": str(path)}, tmp_path, tmp_path / "out")
    assert report["status"] == "passed", report
    assert report["fit_calls"] == 4 and len(report["models"]) == 2
    assert report["resources"]["maximum_fit_calls"] == 4
    assert report["generated_events"] == report["calibration_trials"] == 0
    oracle = 2 * sum(n * math.log(n / mean) + mean - n for n, mean in zip([28, 22], [100 / 3, 50 / 3]))
    for row in report["models"]:
        best = row["fits"][0]["result"]
        assert best["parameters"]["mu"] == pytest.approx(8 / 3, abs=3e-4)
        assert best["parameters"]["source"] == pytest.approx({"alpha": 0., "beta": .6}, abs=3e-4)
        assert row["fits"][1]["twice_delta_nll"] == pytest.approx(oracle, abs=3e-7)
        assert len(best["recipe"]["conditional_masks"]["source"]) == 1
        assert best["recipe"]["true_fixed_source_coordinates"] == []
    assert json.loads((tmp_path / "out/joint_fit.json").read_text()) == report
    with pytest.raises(ValueError, match="fresh"):
        study.run({"input": str(path)}, tmp_path, tmp_path / "out")


@pytest.mark.parametrize("change", ["missing_mask", "noninitial", "signal_free", "wrong_nominal"])
def test_source_conditioning_cannot_hide_unmodeled_response(tmp_path, change):
    path, doc = fixture(tmp_path)
    case = doc["cases"][0]
    if change == "missing_mask":
        case["fixed_source"] = {}
    elif change == "noninitial":
        case["fixed_source"]["alpha"] = .1
    elif change == "signal_free":
        case["free_source"] = ["alpha"]
        case["fixed_source"] = {"beta": 1.}
    else:
        source_path = Path(case["workspace"]["path"])
        source = json.loads(source_path.read_text())
        source["channels"][0]["samples"][0]["data"] = [7.]
        source_path.write_bytes(study.compact(source))
        case["workspace"]["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    path.write_bytes(study.compact(doc))
    with pytest.raises(ValueError):
        compile_case(path)


def test_conditioned_callback_refuses_response_coordinate_movement(tmp_path):
    path, _ = fixture(tmp_path)
    joint, background, mc, _, latent = compile_case(path)
    point = background.initial_point()
    point["alpha"] = .01
    with pytest.raises(ValueError, match="conditioned"):
        joint.evaluate(point, latent, mu=1.)


def test_changed_source_initial_cannot_masquerade_as_nominal_signal(tmp_path):
    path, doc = fixture(tmp_path)
    case = doc["cases"][0]
    case["fixed_source"]["alpha"] = .2
    for pin in (case["workspace"], doc["background_source"]):
        source_path = Path(pin["path"])
        source = json.loads(source_path.read_text())
        source["measurements"][0]["config"]["parameters"] = [{"name": "alpha", "inits": [.2]}]
        source_path.write_bytes(study.compact(source))
        pin["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    path.write_bytes(study.compact(doc))
    with pytest.raises(ValueError, match="literal nominal"):
        compile_case(path)


@pytest.mark.parametrize("change", ["duplicate_grid", "over_cap", "duplicate_point", "source_drift", "budget"])
def test_admission_refuses_before_fitting(tmp_path, monkeypatch, change):
    path, doc = fixture(tmp_path)
    case = doc["cases"][0]
    if change == "duplicate_grid":
        case["profile_points"] = [0., 0.]
    elif change == "over_cap":
        case["profile_points"] = [11.]
    elif change == "duplicate_point":
        doc["cases"].append(deepcopy(case))
    elif change == "source_drift":
        Path(case["workspace"]["path"]).write_text("{}")
    elif change == "budget":
        doc["limits"]["fit_budget"]["wall_seconds"] = 31
    path.write_bytes(study.compact(doc))
    monkeypatch.setattr(study.JointProfiler, "fit", lambda *a, **k: pytest.fail("invalid admission invoked a fit"))
    with pytest.raises(ValueError):
        study.inputs({"input": str(path)}, tmp_path)


def test_all_failed_fit_denominators_and_attempts_are_retained(tmp_path, monkeypatch):
    path, _ = fixture(tmp_path)
    calls = []
    def failed(*args, **kwargs):
        calls.append(kwargs)
        return {"verified": False, "status": "budget_exhausted", "attempts": [{"index": 0, "error": "synthetic budget"}]}
    monkeypatch.setattr(study.JointProfiler, "fit", failed)
    report = study.run({"input": str(path)}, tmp_path, tmp_path / "out")
    assert report["status"] == "failed" and report["diagnostic_delivery_complete"]
    assert report["fit_calls"] == len(calls) == 4
    assert all(row["twice_delta_nll"] is None for model in report["models"] for row in model["fits"])
    assert all(row["result"]["attempts"][0]["error"] == "synthetic budget" for model in report["models"] for row in model["fits"])


def test_unexpected_fit_exception_retains_started_fit_identity(tmp_path, monkeypatch):
    path, _ = fixture(tmp_path)
    def crash(*args, **kwargs):
        saved = json.loads((tmp_path / "out/joint_fit.json").read_text())
        assert saved["fit_calls"] == 1
        assert saved["models"][0]["fits"][0]["status"] == "running"
        raise RuntimeError("synthetic unexpected solver exception")
    monkeypatch.setattr(study.JointProfiler, "fit", crash)
    report = study.run({"input": str(path)}, tmp_path, tmp_path / "out")
    fit = report["models"][0]["fits"][0]
    assert report["status"] == "failed" and report["fit_calls"] == 1
    assert fit["status"] == "failed" and fit["result"] is None
    assert "synthetic unexpected" in fit["error"]["message"]
