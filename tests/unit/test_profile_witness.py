"""Retained numerical evidence using mocked fit results, never a physics fit."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.optimize import OptimizeResult

from ravel.physics import pyhf_exclude as engine


def test_unusable_byte_budget_rejected_before_record_mutation():
    record = {"sentinel": "preserved"}
    with pytest.raises(ValueError, match="at least 512"):
        engine._ProfileWitnessRecorder(record, max_bytes=1)
    assert record == {"sentinel": "preserved"}


@pytest.fixture
def model_data():
    return engine.model_from_counting({"n": 10, "b": 10, "db": 2, "s": 4})


@pytest.fixture
def fake_profiles(monkeypatch):
    def hypotest(mu, data, model, **kwargs):
        nominal = model.config.suggested_init()
        asimov = list(nominal)
        asimov[model.config.poi_index] = 0.
        fixed = list(nominal)
        fixed[model.config.poi_index] = float(mu)
        fits = SimpleNamespace(asimov_pars=asimov, free_fit_to_data=nominal,
            fixed_poi_fit_to_data=fixed, free_fit_to_asimov=asimov,
            fixed_poi_fit_to_asimov=fixed)
        value = float(np.exp(-4 * mu))
        return value, [value] * 5, SimpleNamespace(fitted_pars=fits)
    monkeypatch.setattr(engine, "hypotest", hypotest)
    monkeypatch.setattr(engine.pyhf.infer.mle, "twice_nll", lambda *args: np.array([0.]))
    return hypotest


def test_retention_preserves_default_results_and_records_complete_root_context(model_data, fake_profiles):
    default = engine.compute(*model_data, n_curve=2)
    witness = {}
    retained = engine.compute(*model_data, n_curve=2, profile_witness_record=witness,
                              profile_witness_context={"contract_sha256": "a" * 64})
    assert retained == default
    assert "profile_witnesses" not in default
    assert witness["complete"] is True and witness["status"] == "succeeded"
    assert witness["source_context"]["contract_sha256"] == "a" * 64
    assert witness["parameter_names"] == model_data[0].config.par_names
    assert witness["data"] == model_data[1]
    assert witness["pyhf_version"] == engine.pyhf.__version__
    assert witness["engine_source"]["sha256"] == hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest()
    assert witness["protocol_sha256"] == hashlib.sha256(engine._canonical(witness["protocol"])).hexdigest()
    evaluation = witness["evaluations"][0]
    assert set(evaluation["fitted_parameters"]) == {"asimov_pars", "free_fit_to_data",
        "fixed_poi_fit_to_data", "free_fit_to_asimov", "fixed_poi_fit_to_asimov"}
    np.testing.assert_equal(evaluation["asimov_data"], model_data[0].expected_data(
        evaluation["fitted_parameters"]["asimov_pars"]))
    fresh = [item for item in witness["evaluations"] if item["stage"]["phase"] == "fresh_check"]
    assert {item["stage"]["order"] for item in fresh} == {"descending", "ascending"}
    assert {i for item in fresh for i in item["stage"]["quantile_indices"]} == set(range(6))
    frozen = witness["frozen_pools"][0]
    assert frozen["sha256"] == hashlib.sha256(engine._canonical(frozen["parameters"])).hexdigest()
    assert len(witness["root_passes"][0]["bracket_cls"]) == 6
    assert all(len(edge) == 6 for bracket in witness["root_passes"][0]["bracket_cls"] for edge in bracket)


def test_adaptive_trace_records_current_objective_fixed_coordinates_and_frozen_pool(monkeypatch):
    record = {}
    collector = engine._ProfileWitnessRecorder(record)
    optimizer = engine.robust_optimizer()
    optimizer.begin_model()
    optimizer._witness = collector
    optimizer._profile_pool = [np.array([1., 100.]), np.array([-1., -100.]), np.array([.5, 0.])]
    objective = lambda x: (x[0] + 1.) ** 2 + (x[1] - 7.) ** 2
    calls = []
    def fake_once(minimizer, func, seed, *args):
        calls.append(seed.copy())
        return OptimizeResult(x=seed, fun=func(seed), success=True, status=0, message="mock")
    monkeypatch.setattr(optimizer, "_minimize_once", fake_once)
    optimizer._profile_frozen = True
    optimizer._minimize(None, objective, [1., 2.], bounds=[(-2, 2), (0, 10)], fixed_vals=[(1, 7.)])
    call = record["profile_calls"][0]
    assert call["current_objective_pool_scores"] == [
        {"pool_index": 0, "objective": 4.}, {"pool_index": 1, "objective": 0.},
        {"pool_index": 2, "objective": 2.25}]
    assert call["selected_seeds"] == [[1., 7.], [-1., 7.], [.5, 7.]]
    assert call["fixed_coordinates"] == [[1, 7.]]
    assert call["bounds"] == [[-2, 2], [0, 10]]
    assert call["chosen_result"]["parameters"] == [-1., 7.]
    assert call["pool_added"] == [] and call["pool_frozen"] is True
    assert [item["seed"] for item in record["minimizations"]] == call["selected_seeds"]
    assert all(item["status"] == "succeeded" for item in record["minimizations"])


@pytest.mark.parametrize("limits", [{"evaluations": 1}, {"bytes": 1000}])
def test_exhaustion_fails_explicitly_and_keeps_partial_evidence(model_data, fake_profiles, limits):
    witness = {}
    with pytest.raises(engine.ProfileWitnessBudgetError):
        engine.compute(*model_data, n_curve=2, profile_witness_record=witness, profile_witness_limits=limits)
    assert witness["status"] == "failed" and witness["complete"] is False
    assert witness["budget_error"]
    assert len(witness["evaluations"]) <= limits.get("evaluations", 5000)


def test_candidate_count_budget_cannot_be_swallowed_as_optimizer_fallback(monkeypatch):
    record = {}
    optimizer = engine.robust_optimizer()
    optimizer.begin_model()
    optimizer._witness = engine._ProfileWitnessRecorder(record, max_minimizations=1)
    optimizer._profile_pool = [np.array([-1.])]
    monkeypatch.setattr(optimizer, "_minimize_once", lambda minimizer, func, seed, *args:
                        OptimizeResult(x=seed, fun=func(seed), success=True))
    with pytest.raises(engine.ProfileWitnessBudgetError, match="minimizations"):
        optimizer._minimize(None, lambda x: x[0]**2, [1.], bounds=[(-2, 2)])
    assert len(record["minimizations"]) == 1
    assert record["profile_calls"][0]["status"] == "running"


def test_rejected_scipy_and_guarded_fallback_results_are_both_retained(monkeypatch):
    monkeypatch.setattr(engine.robust_optimizer, "escalated", False)
    record = {}
    optimizer = engine.robust_optimizer()
    optimizer.begin_model()
    optimizer._witness = engine._ProfileWitnessRecorder(record)
    def rejected(function, seed, **kwargs):
        return OptimizeResult(x=np.array([1.]), fun=1., success=False, status=9, message="mock rejection")
    monkeypatch.setattr(optimizer, "_migrad", lambda *args, **kwargs:
                        OptimizeResult(x=np.array([2.]), fun=0., success=True, nfev=1))
    result = optimizer._minimize(rejected, lambda x: float((x[0]-2)**2), [1.], bounds=[(0, 3)])
    assert result.fun == 0.
    trial = record["minimizations"][0]
    assert trial["scipy_result"]["parameters"] == [1.]
    assert trial["scipy_result"]["success"] is False
    assert trial["scipy_result"]["status"] == 9
    assert trial["fallback_status"] == "succeeded"
    assert trial["fallback_result"]["parameters"] == [2.]
    assert trial["rejected_scipy_reason"]


def test_failed_fit_and_evaluation_are_retained_on_interruption(monkeypatch, model_data, tmp_path):
    journal = tmp_path / "progress.jsonl"
    def interrupted(mu, data, model, **kwargs):
        _, optimizer = engine.pyhf.get_backend()
        def stop(*args):
            events = [json.loads(line) for line in journal.read_text().splitlines()]
            assert any(event["collection"] == "minimizations" and event["value"]["status"] == "running"
                       for event in events)
            raise KeyboardInterrupt("mock watchdog interruption")
        monkeypatch.setattr(optimizer, "_minimize_once", stop)
        optimizer._minimize(None, lambda x: float(x[0]**2), model.config.suggested_init(),
                            bounds=model.config.suggested_bounds())
    monkeypatch.setattr(engine, "hypotest", interrupted)
    witness = {}
    with pytest.raises(KeyboardInterrupt):
        engine.compute(*model_data, n_curve=2, profile_witness_record=witness, profile_witness_journal=journal)
    assert witness["minimizations"][0]["status"] == "failed"
    assert witness["evaluations"][0]["status"] == "failed"
    assert witness["error"]["type"] == "KeyboardInterrupt"
    head = None
    for sequence, line in enumerate(journal.read_text().splitlines()):
        event = json.loads(line)
        digest = event.pop("sha256")
        assert event["sequence"] == sequence and event["previous_sha256"] == head
        assert hashlib.sha256(engine._canonical(event)).hexdigest() == digest
        head = digest
    assert witness["journal_head_sha256"] == head


def test_journal_survives_process_exit_without_finally(tmp_path):
    journal = tmp_path / "killed.jsonl"
    script = """import os,sys
from ravel.physics.pyhf_exclude import _ProfileWitnessRecorder
recorder = _ProfileWitnessRecorder({}, journal_path=sys.argv[1])
recorder.update('metadata', None, source_context={'model_sha256':'a'*64})
recorder.start('evaluations', status='running', mu=1.)
recorder.start('minimizations', status='running', seed=[1.])
os._exit(99)
"""
    result = subprocess.run([sys.executable, "-c", script, str(journal)], check=False,
                            env={**os.environ, "PYTHONPATH": str(Path(engine.__file__).resolve().parents[2])})
    assert result.returncode == 99
    events = [json.loads(line) for line in journal.read_text().splitlines()]
    assert events[-1]["value"]["status"] == "running"
    assert events[-1]["collection"] == "minimizations"
    assert events[0]["value"]["source_context"]["model_sha256"] == "a" * 64


def test_terminal_error_and_exhaustion_journal_are_bounded(tmp_path):
    record = {}
    recorder = engine._ProfileWitnessRecorder(record, max_bytes=2000, journal_path=tmp_path / "bounded.jsonl")
    recorder.update("metadata", None, source_context={"model": "mock"})
    recorder.finish("failed", RuntimeError("x" * 5000))
    assert len(engine._canonical(record)) <= 2000
    assert record["error"]["message_truncated"] is True
    assert record["error"]["message_bytes"] == 5000
    assert record["error"]["message_sha256"] == hashlib.sha256(b"x" * 5000).hexdigest()
    assert json.loads((tmp_path / "bounded.jsonl").read_text().splitlines()[-1])["collection"] == "terminal"
    record = {}
    journal = tmp_path / "exhausted.jsonl"
    recorder = engine._ProfileWitnessRecorder(record, max_bytes=3000, journal_path=journal)
    item = recorder.start("evaluations", status="running")
    with pytest.raises(engine.ProfileWitnessBudgetError) as error:
        for index in range(30):
            recorder.update("evaluations", 0, progress=index, message="a"*100)
    recorder.finish("failed", error.value)
    terminal = json.loads(journal.read_text().splitlines()[-1])
    assert terminal["collection"] == "terminal"
    assert "journal byte budget" in terminal["value"]["budget_error"]
    assert len(journal.read_bytes()) <= 3000


def test_journal_io_failure_never_appends_a_reused_sequence(monkeypatch, tmp_path):
    record = {}
    journal = tmp_path / "io-failure.jsonl"
    recorder = engine._ProfileWitnessRecorder(record, journal_path=journal)
    monkeypatch.setattr(engine.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("mock fsync failure")))
    with pytest.raises(OSError) as error:
        recorder.update("metadata", None, source_context={"model": "mock"})
    recorder.finish("failed", error.value)
    assert recorder.journal_poisoned
    assert len(journal.read_text().splitlines()) == 1
    assert record["complete"] is False and record["journal_error"]["type"] == "OSError"


def test_enabled_missing_fit_vectors_fails_but_default_mock_remains_compatible(monkeypatch, model_data):
    monkeypatch.setattr(engine, "hypotest", lambda mu, *args, **kwargs:
                        (float(np.exp(-4*mu)), [float(np.exp(-4*mu))]*5))
    assert engine.compute(*model_data, n_curve=2)["obs_limit"] > 0
    witness = {}
    with pytest.raises(RuntimeError, match="fitted_pars"):
        engine.compute(*model_data, n_curve=2, profile_witness_record=witness)
    assert witness["complete"] is False


@pytest.mark.parametrize("failure", [False, True])
def test_cli_retains_unique_digest_bound_success_and_failure(monkeypatch, model_data, tmp_path, failure):
    bkg, patch = tmp_path / "bkg.json", tmp_path / "patch.json"
    bkg.write_text("{}")
    patch.write_text("[]")
    out = tmp_path / "out"
    monkeypatch.setattr(engine, "model_from_likelihood", lambda *args: model_data)
    monkeypatch.setattr(engine, "plot", lambda *args, **kwargs: None)
    def fake_compute(model, data, *, diagnostic_record, profile_witness_record, **kwargs):
        profile_witness_record.update(status="failed" if failure else "succeeded", complete=not failure)
        diagnostic_record.update(status="failed" if failure else "succeeded")
        if failure:
            raise RuntimeError("mock failed fit")
        return {"obs_limit": 1., "exp_limits": [.5, .8, 1., 1.2, 1.5],
                "limit_status": {"observed": "resolved", "expected": ["resolved"]*5}}
    monkeypatch.setattr(engine, "compute", fake_compute)
    monkeypatch.setattr(sys, "argv", ["pyhf", "likelihood", "--bkg", str(bkg), "--patch", str(patch),
                                     "--out", str(out), "--retain-profile-witnesses"])
    for _ in range(2):
        if failure:
            with pytest.raises(RuntimeError, match="mock failed fit"):
                engine.main()
        else:
            engine.main()
    artifacts = list(out.glob("profile_witnesses*.json"))
    assert len(artifacts) == 2
    if failure:
        references = [json.loads(path.read_text())["profile_witnesses"] for path in out.glob("inference_failure*.json")]
    else:
        result = json.loads((out / "exclusion.json").read_text())
        references = [result["profile_witnesses"]]
    for reference in references:
        assert hashlib.sha256(Path(reference["path"]).read_bytes()).hexdigest() == reference["sha256"]
        assert reference["complete"] is not failure
