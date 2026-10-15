"""Synthetic rate mappings and source-convention refusals."""
import copy
import json
from pathlib import Path

import pytest


FIXTURES = Path(__file__).parents[1] / "fixtures" / "higgs"


def bundle():
    return json.loads((FIXTURES / "parameterization.json").read_text())


@pytest.mark.parametrize("mutation, match", [
    (lambda b: b["branching_fractions"].update(bb=0.4), "sum"),
    (lambda b: b["parameters"]["BR_inv"].update(initial=1), "branching"),
    (lambda b: b["loops"]["g"].update(mode="unspecified"), "loop"),
    (lambda b: b["production"]["P-0001"]["polynomial"]["terms"][0]["powers"].update(unknown=2), "parameter"),
])
def test_invalid_parameterization_is_refused(mutation, match):
    from ravel.physics.higgs_parameterization import validate_bundle
    doc = bundle()
    mutation(doc)
    with pytest.raises(ValueError, match=match):
        validate_bundle(doc)


def test_failed_held_out_closure_is_refused():
    from ravel.validation.higgs_bundle_checks import check_parameterization_closure
    doc = bundle()
    doc["closure"] = {"points": [{"parameters": {}, "values": [50.0, 50.0],
                                  "uncertainty": [0.01, 0.01]}], "tolerance_sigma": 2.0}
    with pytest.raises(ValueError, match="closure"):
        check_parameterization_closure(doc)


def test_prediction_mass_and_loop_conventions_are_refused():
    from ravel.validation.higgs_bundle_checks import check_prediction_convention
    measurement = json.loads((FIXTURES / "measurements.json").read_text())
    doc = bundle()
    doc["mass_gev"] += 0.5
    with pytest.raises(ValueError, match="mass"):
        check_prediction_convention(measurement, doc)
    doc = bundle()
    measurement["loop_modes"] = {"g": "effective"}
    with pytest.raises(ValueError, match="loop"):
        check_prediction_convention(measurement, doc)


def test_resolved_and_effective_loops_match_declared_coefficients():
    from ravel.physics.higgs_parameterization import evaluate
    doc = bundle()
    point = {"kappa_V": 1.2, "kappa_F": 0.9, "kappa_g": 1.1}
    resolved = evaluate(doc, point)
    expected = 1.2 * 0.9**2 + 0.1 * 1.2**2 - 0.3 * 0.9 * 1.2
    assert resolved["loop_scales"]["g"] == pytest.approx(expected, abs=1e-12)
    assert resolved["loop_modes"] == {"g": "resolved"}
    doc["loops"]["g"] = {"mode": "effective", "parameter": "kappa_g"}
    effective = evaluate(doc, point)
    assert effective["loop_scales"]["g"] == pytest.approx(1.1**2, abs=1e-12)
    assert effective["loop_modes"] == {"g": "effective"}
    assert effective["rates"][1]["value"] != resolved["rates"][1]["value"]


def test_all_three_effective_loop_modifiers_and_bsm_width():
    from ravel.physics.higgs_parameterization import evaluate
    doc = bundle()
    for loop, parameter in (("g", "kappa_g"), ("gamma", "kappa_gamma"), ("Zgamma", "kappa_Zgamma")):
        doc["parameters"][parameter] = {"initial": 1, "sm": 1, "fixed": True, "bounds": [0.1, 3]}
        doc["loops"][loop] = {"mode": "effective", "parameter": parameter}
    doc["decays"] = {n: {"loop": n} for n in doc["loops"]}
    doc["branching_fractions"] = {"g": 0.5, "gamma": 0.3, "Zgamma": 0.2}
    doc["rates"][0]["decay"] = "gamma"
    doc["rates"][1]["decay"] = "g"
    result = evaluate(doc, {"BR_inv": 0.1, "BR_undet": 0.2, "kappa_gamma": 1.2})
    visible = 0.5 + 0.3 * 1.2**2 + 0.2
    assert result["width_scaling"] == pytest.approx(visible / 0.7, abs=1e-12)
    assert result["rates"][0]["mu"] == pytest.approx(1.2**2 / (visible / 0.7), abs=1e-12)


def test_heft_dictionary_preserves_supplied_contact_normalization():
    from ravel.physics.higgs_parameterization import HEFT_KEYS, evaluate
    doc = bundle()
    doc["framework"] = "heft-lo"
    for name in HEFT_KEYS:
        if name not in doc["parameters"]:
            value = 1 if name == "kappa_2V" else 0
            doc["parameters"][name] = {"initial": value, "sm": value, "fixed": True, "bounds": [None, None]}
    doc["heft_dictionary"] = {n: n for n in HEFT_KEYS}
    doc["heft_normalization"] = "Supplied dimensionless contact terms in the declared amplitude basis"
    doc["loops"]["g"]["polynomial"] = {"terms": [
        {"coefficient": 1, "powers": {"kappa_F": 2}},
        {"coefficient": 2, "powers": {"kappa_F": 1, "c_gg": 1}},
        {"coefficient": 1, "powers": {"c_gg": 2}}]}
    result = evaluate(doc, {"c_gg": 0.2, "c_2": -0.3})
    assert result["loop_scales"]["g"] == pytest.approx(1.2**2)
    assert result["heft_dictionary"]["c_2"] == -0.3
    assert result["heft_normalization"] == doc["heft_normalization"]


def test_reference_branching_rows_are_selected_by_supplied_ids():
    from ravel.physics.higgs_parameterization import reference_branching_fractions
    table = {"schema_version": 1, "kind": "higgs-reference-tables", "synthetic": True,
             "citations": {"SRC-0001": {"title": "Synthetic reference", "locator": "synthetic://source", "source_file": "source.txt"}},
             "rows": [], "ratios": []}
    for identity, value in (("REF-0001", 0.4), ("REF-0002", 0.6)):
        table["rows"].append({"id": identity, "quantity": "branching_ratio", "process": identity,
                              "mass_gev": 124, "value": value, "reference_value": value, "unit": "1",
                              "citation_key": "SRC-0001", "uncertainty": {"minus": 0.01, "plus": 0.02,
                              "definition": "Synthetic interval"}})
    assert reference_branching_fractions(table, {"D-0001": "REF-0001", "D-0002": "REF-0002"}, mass_gev=124) == {"D-0001": 0.4, "D-0002": 0.6}


def test_parameterization_operation_pins_input_and_uses_supplied_output(tmp_path):
    from ravel.physics.higgs_parameterization import run
    path = tmp_path / "input.json"
    path.write_text(json.dumps(bundle()))
    result = run({"schema_version": 1, "input": path.name,
                  "output": {"filename": "declared.json", "format": "json-compact"}}, tmp_path, tmp_path / "out")
    assert result["closure"]["passed"]
    assert len(result["inputs"]) == 1
    assert json.loads((tmp_path / "out" / "declared.json").read_text()) == result
    assert result["physics_validated"] is False


def test_closure_consumes_the_shared_held_out_comparator():
    from ravel.validation.higgs_bundle_checks import check_parameterization_closure
    doc = bundle()
    doc["closure"] = {"points": [{"parameters": {}, "values": [1.0, 1.0],
                                  "uncertainty": [1e-8, 1e-8]}], "tolerance_sigma": 1}
    result = check_parameterization_closure(doc)
    assert result["passed"]
    assert result["points"][0]["combined_uncertainty"] == [1e-8, 1e-8]


@pytest.mark.xfail(reason="awaits H-01", strict=True)
def test_reference_table_v2_coefficient_interface():
    # The source table successor must supply mass-bound loop coefficient rows.
    root = Path(__file__).parents[2] / "src" / "ravel" / "data" / "knowledge" / "higgs"
    table = json.loads((root / "higgs-reference-tables.json").read_text())
    assert table["schema_version"] == 2
    assert any(r["quantity"] == "kappa_coefficient" for r in table["rows"])
