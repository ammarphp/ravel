"""Independent density arithmetic and bounded parity failure controls."""
from copy import deepcopy
import json
import hashlib
import math
from types import SimpleNamespace

import pytest

from ravel.validation import likelihood_parity as parity


@pytest.fixture(autouse=True)
def preserve_global_backend():
    pyhf = pytest.importorskip("pyhf")
    backend, optimizer = pyhf.get_backend()
    yield
    pyhf.set_backend(backend, optimizer)


def test_scalar_density_retains_constants_and_heterogeneous_auxiliary_order():
    layout = [{"pdf": "poisson", "parameter_index": 2, "factor": 8, "sigma": None},
              {"pdf": "normal", "parameter_index": 0, "factor": 1, "sigma": .2}]
    result = parity.scalar_density([3.5, 0], [.9, 17, 1.2], [2.25, 0, 7.5, 1.0], layout)
    poisson = lambda n, mean: 2 * (mean - n * math.log(mean) + math.lgamma(n + 1))
    expected = poisson(2.25, 3.5) + poisson(7.5, 9.6) + .5 ** 2 + math.log(2 * math.pi * .2 ** 2)
    assert result["twice_nll"] == pytest.approx(expected, abs=1e-12)
    assert result["auxiliary_expected"] == pytest.approx([9.6, .9])
    wrong_order = parity.scalar_density([3.5, 0], [.9, 17, 1.2], [2.25, 0, 1, 7.5], layout)
    assert abs(wrong_order["twice_nll"] - expected) > 1


def test_zero_poisson_density_and_invalid_mean_are_retained():
    assert parity.poisson_twice_nll(0, 0) == 0
    assert math.isinf(parity.poisson_twice_nll(1, 0))
    assert math.isnan(parity.poisson_twice_nll(0, -1))
    assert math.isnan(parity.poisson_twice_nll(0, math.nan))
    with pytest.raises(ValueError, match="nonnegative"):
        parity.poisson_twice_nll(-1, 1)
    with pytest.raises(ValueError, match="dimension"):
        parity.scalar_density([1], [], [], [])


def test_independent_density_detects_changed_sigma_or_poisson_factor():
    layout = [{"pdf": "normal", "parameter_index": 0, "factor": 1, "sigma": .2},
              {"pdf": "poisson", "parameter_index": 1, "factor": 7, "sigma": None}]
    baseline = parity.scalar_density([3], [.9, 1.2], [2, 1, 7], layout)["twice_nll"]
    changed = deepcopy(layout)
    changed[0]["sigma"] = 1
    assert abs(parity.scalar_density([3], [.9, 1.2], [2, 1, 7], changed)["twice_nll"] - baseline) > 1
    changed = deepcopy(layout)
    changed[1]["factor"] = 10
    assert abs(parity.scalar_density([3], [.9, 1.2], [2, 1, 7], changed)["twice_nll"] - baseline) > 1


def test_layout_accounts_for_vector_constraints_and_actual_auxiliary_order():
    sets = {"normal": SimpleNamespace(constrained=True, n_parameters=2, pdf_type="normal"),
            "gamma": SimpleNamespace(constrained=True, n_parameters=1, pdf_type="poisson", factors=[12])}
    config = SimpleNamespace(auxdata_order=["gamma", "normal"], param_set=sets.__getitem__, nauxdata=3,
                             par_map={"normal": {"slice": slice(0, 2)}, "gamma": {"slice": slice(3, 4)}})
    rows = parity.constraint_layout(SimpleNamespace(config=config))
    assert [row["parameter_index"] for row in rows] == [3, 0, 1]
    assert [row["sigma"] for row in rows] == [None, 1, 1]
    config.nauxdata = 4
    with pytest.raises(ValueError, match="every auxiliary"):
        parity.constraint_layout(SimpleNamespace(config=config))


def test_finite_difference_covers_fixed_interior_and_both_bounds():
    point = [1, 0, 2, .5]
    bounds = [[-2, 2], [0, 2], [0, 2], [0, 1]]
    objective = lambda x: sum((i + 1) * v * v for i, v in enumerate(x))
    rows = parity.finite_difference(objective, point, bounds, [[3, .5]])
    assert [row["rule"] for row in rows] == ["central", "forward_second_order", "backward_second_order", "fixed"]
    checked = parity.compare_gradients(rows, [2, 0, 12, 4])
    assert checked["passed"]
    assert checked["coordinates"][3]["masked"]
    assert not parity.compare_gradients(rows, [2.01, 0, 12, 4])["passed"]
    with pytest.raises(ValueError, match="every coordinate"):
        parity.compare_gradients(rows[:-1], [2, 0, 12, 4])


def test_h_half_h_must_converge_even_if_one_matches_analytic():
    rows = [{"index": 0, "rule": "central", "h": 1e-4, "h_gradient": 1.1, "half_gradient": 1.0}]
    assert not parity.compare_gradients(rows, [1.0])["passed"]


@pytest.mark.parametrize("fixed", [[[0, 2]], [[0, 1], [0, 1]], [[7, 1]]])
def test_finite_difference_rejects_untrue_fixed_coordinate(fixed):
    with pytest.raises(ValueError, match="fixed coordinate"):
        parity.finite_difference(lambda x: x[0] ** 2, [1], [[0, 3]], fixed)


def test_budget_fails_before_extra_evaluation(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(parity.time, "monotonic", lambda: clock[0])
    budget = parity.Budget(5, 1)
    budget.check("a")
    with pytest.raises(RuntimeError, match="scalar"):
        budget.check("a")
    assert budget.calls == 1
    clock[0] = 16
    with pytest.raises(RuntimeError, match="wall"):
        budget.check()


def test_independent_density_matches_synthetic_pyhf_normal_and_poisson():
    pyhf = pytest.importorskip("pyhf")
    np = pytest.importorskip("numpy")
    pyhf.set_backend("numpy", precision="64b")
    model = pyhf.Model({"channels": [{"name": "single", "samples": [
        {"name": "signal", "data": [3, 2], "modifiers": [{"name": "mu", "type": "normfactor", "data": None},
            {"name": "shape", "type": "shapesys", "data": [1, .5]}]},
        {"name": "background", "data": [8, 5], "modifiers": [{"name": "normal", "type": "normsys", "data": {"lo": .8, "hi": 1.3}},
            {"name": "stat", "type": "staterror", "data": [1, .6]}]}]}]})
    point = model.config.suggested_init()
    point[model.config.poi_index] = .6
    point[model.config.par_map["normal"]["slice"].start] = -.25
    data = [10, 7, *model.config.auxdata]
    layout = parity.constraint_layout(model)
    means = np.asarray(model.expected_data(point)).tolist()
    result = parity.scalar_density(means[:2], point, data, layout)
    assert result["twice_nll"] == pytest.approx(float(np.asarray(pyhf.infer.mle.twice_nll(point, data, model))[0]), abs=1e-10)
    assert result["auxiliary_expected"] == pytest.approx(means[2:], abs=1e-12)


def test_nonfinite_output_is_json_safe_but_not_silently_finite():
    assert parity._finite_json([math.nan, math.inf, -math.inf]) == [{"nonfinite": "nan"}, {"nonfinite": "+inf"}, {"nonfinite": "-inf"}]
    assert not parity._same_number(1, math.nan, 1e-7)


def test_declared_tolerances_cannot_be_relaxed():
    doc = {"schema_version": 1, "published_input": {}, "retained_inputs": {}, "compiled_reference": {}, "runtime_inventory": {},
           "grounding": [], "gradient_vectors": [{"label": label, "parameters": [], "bounds": [], "fixed_coordinates": [], "data": []} for label in ("a", "b")],
           "limits": {"seconds": 300, "scalar_calls": 4096, "vectors": 32}, "tolerances": dict(parity.TOLERANCES)}
    parity.validate_document(doc)
    doc["tolerances"]["twice_nll_atol"] = 1e-4
    with pytest.raises(ValueError, match="fixed tolerances"):
        parity.validate_document(doc)


def test_runtime_inventory_checks_actual_bytes_and_rejects_duplicates(tmp_path):
    import hashlib
    file = tmp_path / "runtime.py"
    file.write_text("x = 1\n")
    pin = {"path": str(file), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
    assert parity.runtime_files({"schema_version": 1, "files": [pin]}) == [file]
    with pytest.raises(ValueError, match="repeats"):
        parity.runtime_files({"schema_version": 1, "files": [pin, pin]})
    file.write_text("x = 2\n")
    with pytest.raises(ValueError, match="runtime bytes differ"):
        parity.runtime_files({"schema_version": 1, "files": [pin]})


def test_gradient_mask_cannot_hide_free_coordinates():
    compiled = {"parameter_names": ["fixed", "free"], "parameter_order": ["fixed", "free"],
                "model_compact_sha256": "m", "data_compact_sha256": "d", "inits": [1, 1],
                "fixed": [True, False], "npars": 2, "nmaindata": 1, "nauxdata": 0,
                "bounds": [[0, 2], [0, 2]], "observed_and_auxiliary_data": [3]}
    retained = {"parameter_names": compiled["parameter_names"], "parameter_order": compiled["parameter_order"],
                "model_sha256": "m", "data_sha256": "d", "nominal_parameters": [1, 1],
                "source_suggested_fixed": [True, False], "conditional_probe": {"bounds": compiled["bounds"]},
                "saved_fixed_vector_references": []}
    gradients = [{"label": "test", "parameters": [1, 1.02], "bounds": compiled["bounds"],
                  "data": [3], "fixed_coordinates": [[0, 1]]}]
    assert len(parity._vectors(retained, compiled, gradients, 32)) == 2
    gradients[0]["fixed_coordinates"].append([1, 1.02])
    with pytest.raises(ValueError, match="exactly the source-fixed"):
        parity._vectors(retained, compiled, gradients, 32)


def test_saved_asimov_data_cannot_be_replaced_by_observed():
    compiled = {"parameter_names": ["p"], "parameter_order": ["p"], "model_compact_sha256": "m",
                "data_compact_sha256": "d", "inits": [1], "fixed": [False], "npars": 1,
                "nmaindata": 1, "nauxdata": 0, "bounds": [[0, 2]], "observed_and_auxiliary_data": [3]}
    retained = {"parameter_names": ["p"], "parameter_order": ["p"], "model_sha256": "m", "data_sha256": "d",
                "nominal_parameters": [1], "source_suggested_fixed": [False],
                "saved_fixed_vector_references": [{"data_role": "saved_asimov", "data": [3], "generating_asimov_data": [2.5]}]}
    with pytest.raises(ValueError, match="observed/Asimov role"):
        parity._vectors(retained, compiled, [], 32)


def test_real_pyhf_bounds_match_persisted_json_without_changing_model():
    pyhf = pytest.importorskip("pyhf")
    model = pyhf.simplemodels.uncorrelated_background([3], [10], [2])
    compiled = {"bounds": model.config.suggested_bounds(),
                "parameter_names": model.config.par_names,
                "fixed": model.config.suggested_fixed(),
                "data": [12, *model.config.auxdata]}
    raw_bounds = deepcopy(compiled["bounds"])
    persisted = json.loads(json.dumps(compiled))
    # This is the real tuple/list mismatch that spent the zero-evaluation run.
    assert compiled["bounds"] != persisted["bounds"]
    normalized = parity.compiled_json_identity(compiled)
    assert normalized == persisted
    assert compiled["bounds"] == raw_bounds
    assert model.config.suggested_bounds() == raw_bounds
    changed = deepcopy(persisted)
    changed["bounds"][0][1] += .001
    assert normalized != changed
    changed = deepcopy(persisted)
    changed["parameter_names"].reverse()
    assert normalized != changed
    changed = deepcopy(persisted)
    changed["fixed"][0] = not changed["fixed"][0]
    assert normalized != changed


def test_compiled_json_identity_refuses_nonfinite_metadata():
    with pytest.raises(ValueError, match="JSON"):
        parity.compiled_json_identity({"bounds": [(0, math.inf)]})


def test_legacy_data_digest_is_verified_before_lossless_spelling_reconciliation():
    digest = lambda values: hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()
    reference = {"observed_and_auxiliary_data": [12, 20, 1.0],
                 "data_compact_sha256": digest([12, 20, 1.0]), "bounds": [[0, 10]]}
    before = deepcopy(reference)
    normalized, witness = parity.compiled_reference_identity(reference)
    assert reference == before
    assert normalized["data_compact_sha256"] == digest([12.0, 20.0, 1.0])
    assert normalized["data_compact_sha256"] != reference["data_compact_sha256"]
    assert normalized["observed_and_auxiliary_data"] == reference["observed_and_auxiliary_data"]
    assert witness["exact_values_and_order_preserved"]
    assert witness["source_integer_values"] == 2
    for field, value in (("data_compact_sha256", "wrong"),
                         ("observed_and_auxiliary_data", [13, 20, 1.0])):
        bad = {**reference, field: value}
        with pytest.raises(ValueError, match="literal saved data"):
            parity.compiled_reference_identity(bad)
    lossy = [2 ** 53 + 1]
    with pytest.raises(ValueError, match="losslessly"):
        parity.compiled_reference_identity({"observed_and_auxiliary_data": lossy,
                                           "data_compact_sha256": digest(lossy)})
