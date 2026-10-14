"""Supplied-oracle transport controls only; no graph, density, fit or LP."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
from ravel.physics import joint_score as a


@pytest.fixture(autouse=True)
def forbid_numerics(monkeypatch):
    def no(*args, **kwargs):
        pytest.fail("Forbidden graph/density/optimizer/LP call")
    monkeypatch.setattr(a, "_compile", no)
    monkeypatch.setattr(a, "run", no)
    monkeypatch.setattr(a.q, "_compile", no)
    monkeypatch.setattr(a.q, "run", no)
    monkeypatch.setattr(a.q.IndependentSourceOracle, "__init__", no)
    import pyhf
    import scipy.optimize
    monkeypatch.setattr(pyhf, "Workspace", no)
    monkeypatch.setattr(pyhf, "Model", no)
    monkeypatch.setattr(scipy.optimize, "minimize", no)
    monkeypatch.setattr(scipy.optimize, "linprog", no)


def fixture():
    points = [{"mu": 1.+i, "source": {"alpha": 0.}, "latent": {"c0": .1, "u": .9}} for i in range(3)]
    attempts = [{"original_seed_id": i, "parameters": point, "nll": 3.+i, "main_means": [2.+i]}
                for i, point in enumerate(points)]
    fit = {"verified": True, "parameters": deepcopy(points[0]), "nll": 3., "attempts": attempts}
    replies = [{"nll": 3.+i, "main_means": [2.+i], "distribution_means": [2.+i, 0., 30., 270.],
                "raw_source": {"auxiliary_logpdf": -1.5, "background": [1.], "signal": [1.+i]}}
               for i in range(3)]
    return fit, replies, {"nll_atol": 1e-8, "mean_atol": 1e-8, "mean_rtol": 1e-9}


def snapshot(out, i):
    path = out / ("case--free_mu--oracle-return-"+str(i)+".json")
    return path, json.loads(path.read_bytes())


def test_return1_survives_return2_hard_stop_surrogate(tmp_path):
    fit, replies, limits = fixture()
    retention = a.Retention(tmp_path)
    raw = retention.snapshot("raw-solver.json", fit)
    calls = []
    def supplied(point):
        calls.append(deepcopy(point))
        if len(calls) == 2:
            raise KeyboardInterrupt("supplied later hard-stop surrogate")
        return deepcopy(replies[0])
    with pytest.raises(KeyboardInterrupt):
        a._endpoint_checks(fit, SimpleNamespace(evaluate=supplied), retention, "case/free_mu", limits)
    path, kept = snapshot(tmp_path, 0)
    assert kept["parameters"] == fit["attempts"][0]["parameters"]
    assert kept["independent"] == replies[0]
    assert json.loads((tmp_path / raw["path"]).read_bytes()) == fit
    assert len(calls) == 2
    assert not (tmp_path / "case--free_mu--oracle-return-1.json").exists()
    rows = [json.loads(row) for row in (tmp_path / "score-progress.jsonl").read_bytes().splitlines()]
    completed = next(r for r in rows if r["state"] == "completed")
    assert completed["independent_return_snapshot"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("stop", ["comparison", "journal"])
def test_return_survives_before_comparison_or_completed_journal_stop(tmp_path, monkeypatch, stop):
    fit, replies, limits = fixture()
    def halted(*args, **kwargs):
        raise KeyboardInterrupt("supplied " + stop + " stop")
    retention = a.Retention(tmp_path)
    if stop == "comparison":
        monkeypatch.setattr(a.q, "_close", halted)
    else:
        original = retention.write
        def write(kind, identity, state, **fields):
            if state == "completed":
                halted()
            return original(kind, identity, state, **fields)
        retention.write = write
    with pytest.raises(KeyboardInterrupt):
        a._endpoint_checks(fit, SimpleNamespace(evaluate=lambda p: deepcopy(replies[0])),
                           retention, "case/free_mu", limits)
    assert snapshot(tmp_path, 0)[1]["independent"] == replies[0]


def test_ordinary_oracle_exception_keeps_prior_return_and_all_attempt_denominator(tmp_path):
    fit, replies, limits = fixture()
    calls = []
    def supplied(point):
        i = len(calls); calls.append(point)
        if i == 1:
            raise ValueError("supplied failed oracle")
        return deepcopy(replies[i])
    result = a._endpoint_checks(fit, SimpleNamespace(evaluate=supplied), a.Retention(tmp_path), "case/free_mu", limits)
    assert len(calls) == 3
    assert result["verified"] is False
    assert len(result["independent_endpoint_checks"]) == 3
    assert snapshot(tmp_path, 0)[1]["independent"] == replies[0]
    assert snapshot(tmp_path, 2)[1]["independent"] == replies[2]


def test_comparison_exception_retains_return_binding_in_error_record(tmp_path, monkeypatch):
    fit, replies, limits = fixture()
    fit["attempts"] = fit["attempts"][:1]
    def supplied_error(*args, **kwargs):
        raise ValueError("supplied comparison failure")
    monkeypatch.setattr(a.q, "_close", supplied_error)
    result = a._endpoint_checks(fit, SimpleNamespace(evaluate=lambda p: deepcopy(replies[0])),
                               a.Retention(tmp_path), "case/free_mu", limits)
    record = result["independent_endpoint_checks"][0]
    assert record["passed"] is False
    assert record["independent_return_snapshot"]["path"] == snapshot(tmp_path, 0)[0].name
    assert snapshot(tmp_path, 0)[1]["independent"] == replies[0]


@pytest.mark.parametrize("field", ["nll", "parameters"])
def test_selected_endpoint_binding_gate_unchanged(tmp_path, field):
    fit, replies, limits = fixture()
    if field == "nll":
        fit["nll"] += .001
    else:
        fit["parameters"]["mu"] += .001
    iterator = iter(replies)
    result = a._endpoint_checks(fit, SimpleNamespace(evaluate=lambda p: deepcopy(next(iterator))),
                               a.Retention(tmp_path), "case/free_mu", limits)
    assert result["selected_endpoint_binding"]["passed"] is False
    assert result["verified"] is False
    assert all(r["passed"] for r in result["independent_endpoint_checks"])
    assert len(list(tmp_path.glob("*--oracle-return-*.json"))) == 3


@pytest.mark.parametrize("cap", ["individual", "aggregate"])
def test_byte_limit_refuses_before_comparison_and_preserves_raw(tmp_path, monkeypatch, cap):
    fit, replies, limits = fixture()
    retention = a.Retention(tmp_path)
    raw = retention.snapshot("raw-solver.json", fit)
    if cap == "individual":
        monkeypatch.setattr(a, "MAX_ORACLE_RETURN_BYTES", 1)
    else:
        # Allow running identity but leave less than one return snapshot.
        monkeypatch.setattr(a, "MAX_OUTPUT_BYTES", retention.bytes+150)
    monkeypatch.setattr(a.q, "_close", lambda *args, **kwargs: pytest.fail("Compared unretained return"))
    fit["attempts"] = fit["attempts"][:1]
    try:
        result = a._endpoint_checks(fit, SimpleNamespace(evaluate=lambda p: deepcopy(replies[0])),
                                   retention, "case/free_mu", limits)
    except ValueError as error:
        assert cap == "aggregate" and "aggregate" in str(error)
    else:
        assert result["verified"] is False
        assert "byte ceiling" in result["independent_endpoint_checks"][0]["error"]
    assert (tmp_path / raw["path"]).exists()
    assert not list(tmp_path.glob("*--oracle-return-*.json"))


def test_resource_rows_add_twelve_returns_without_numerical_budget_changes():
    # Supplied resource rows exercise augmentation without archived design I/O.
    design = {"resource_bounds": {
        "campaign_retained_output_bytes_maximum": 144*1024**2,
        "original_source_endpoint_wrappers": 12,
        "fit_density_gradient_passes": 2000,
        "execution_seconds": 1350,
        "outer_work_seconds": 1290,
    }}
    design.update(cases=[{'id':c,'expected_free_coordinates':{'free':2,'fixed':1},'original_named_seeds':[{'id':str(i)} for i in range(3)]} for c in ('CASE-0001','CASE-0002')],objectives=[{'id':'free','fixed_mu':None},{'id':'fixed','fixed_mu':1.}])
    result = a._bounds(design)
    assert result["maximum_oracle_return_snapshot_files"] == 12
    assert result["maximum_oracle_return_snapshot_bytes_each"] == 1024**2
    assert result["campaign_retained_output_bytes_maximum"] == 144*1024**2
    assert result["original_source_endpoint_wrappers"] == 12
    assert result["fit_density_gradient_passes"] == 2000
    assert result["execution_seconds"] == 1350 and result["outer_work_seconds"] == 1290
    assert all(result[key] == value for key, value in design["resource_bounds"].items())
