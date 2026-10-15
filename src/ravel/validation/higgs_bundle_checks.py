"""Named refusal checks for supplied rates, conventions, closure and domains."""
from __future__ import annotations

import math
import numpy as np

from ravel.physics.measurement import _matrix
from ravel.physics.higgs_parameterization import Parameterization, _schema, validate_bundle
from ravel.physics.coupling_polynomial import held_out


def check_measurement_bundle(bundle):
    _schema(bundle, "measurement-bundle.json")
    rows = bundle["rows"]
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("measurement row ids must be unique")
    if any(r["mass_gev"] != bundle["mass_gev"] for r in rows):
        raise ValueError("measurement rows mix scalar mass values")
    for row in rows:
        if (row["quantity"] == "mu") != (row["unit"] == "1"):
            raise ValueError("measurement quantity and unit differ")
    if not isinstance(bundle["correlation"], list):
        raise ValueError("resolve correlation file before named measurement check")
    order = bundle.get("correlation_order", ids)
    correlation = _matrix({"bin_ids": order, "matrix": bundle["correlation"], "unit": "(1)^2"},
                          ids, "1", "correlation", np)
    if not np.allclose(np.diag(correlation), 1, atol=1e-12, rtol=0):
        raise ValueError("correlation diagonal must be one")
    if np.max(np.abs(correlation)) > 1 + 1e-12:
        raise ValueError("correlation is not positive semidefinite")
    if bundle["overlap"]["policy"] == "independent" and not np.allclose(correlation, np.eye(len(ids)), atol=1e-12, rtol=0):
        raise ValueError("independence conflicts with cross-row correlation")
    return {"check": "check:higgs.measurement_bundle", "passed": True,
            "row_ids": ids, "correlation": correlation.tolist(), "mass_gev": bundle["mass_gev"]}


def check_prediction_convention(measurements, parameterization):
    check_measurement_bundle(measurements)
    doc = validate_bundle(parameterization)
    if measurements["mass_gev"] != doc["mass_gev"]:
        raise ValueError("prediction mass differs from measurement mass")
    rates = {r["id"]: r for r in doc["rates"]}
    ids = [r["id"] for r in measurements["rows"]]
    if set(ids) != set(rates):
        raise ValueError("prediction must cover exactly the measured row identities")
    for row in measurements["rows"]:
        prediction = rates[row["id"]]
        if any(row[k] != prediction[k] for k in ("production", "decay", "unit")):
            raise ValueError("measurement and prediction channel or unit differs")
    modes = {k: v["mode"] for k, v in doc.get("loops", {}).items()}
    if any(modes.get(k) != v for k, v in measurements.get("loop_modes", {}).items()):
        raise ValueError("measurement and prediction loop convention differs")
    return {"check": "check:higgs.prediction_convention", "passed": True,
            "mass_gev": doc["mass_gev"], "convention": doc["convention"], "loop_modes": modes}


def check_parameterization_closure(bundle):
    doc = validate_bundle(bundle)
    closure = doc.get("closure")
    if not closure:
        raise ValueError("parameterization requires supplied held-out closure points")
    evaluator = Parameterization(doc, _validated=True)
    comparisons = []
    for point in closure["points"]:
        predicted = [r["value"] for r in evaluator.evaluate(point["parameters"])["rates"]]
        comparison = held_out(predicted=predicted, prediction_variance=None,
                              observed=point["values"], uncertainty=point["uncertainty"],
                              tolerance_sigma=closure["tolerance_sigma"])
        if not all(math.isfinite(x) for x in comparison["pulls"]) or not comparison["passed"]:
            raise ValueError("parameterization held-out closure failed")
        comparisons.append({"parameters": point["parameters"], **comparison})
    return {"check": "check:higgs.parameterization_closure", "passed": True, "points": comparisons}


def check_boundary_parameters(bundle):
    doc = validate_bundle(bundle)
    parameters = doc["parameters"]
    free_bsm = [n for n in doc.get("bsm_parameters", {}).values() if not parameters[n]["fixed"]]
    vectors = doc.get("vector_parameters", [])
    if free_bsm and "width_constraint" not in doc:
        if not vectors:
            raise ValueError("free BSM width requires declared vector parameters or a width constraint")
        free_vectors = [n for n in vectors if not parameters[n]["fixed"]]
        if free_vectors and doc.get("vector_upper_bound") != 1:
            raise ValueError("free BSM branching fraction with free vector coupling needs vector upper bound or width constraint")
    limits = {}
    for name, p in parameters.items():
        lo, hi = p["bounds"]
        if name in doc.get("bsm_parameters", {}).values():
            lo, hi = max(0, lo) if lo is not None else 0, min(1, hi) if hi is not None else 1
        if name in vectors and "vector_upper_bound" in doc:
            # The rate depends on the squared coupling, so the bound applies to both signs.
            lo, hi = max(-1, lo) if lo is not None else -1, min(1, hi) if hi is not None else 1
        if lo is not None and hi is not None and lo >= hi:
            raise ValueError("boundary parameters have an empty domain")
        limits[name] = [lo, hi]
    return {"check": "check:higgs.boundary_parameters", "passed": True,
            "limits": limits, "free_bsm": free_bsm, "width_constraint": doc.get("width_constraint")}


CHECKS = ("higgs.measurement_bundle", "higgs.prediction_convention",
          "higgs.parameterization_closure", "higgs.boundary_parameters")

CHECK_FUNCTIONS = {
    "check:higgs.measurement_bundle": check_measurement_bundle,
    "check:higgs.prediction_convention": check_prediction_convention,
    "check:higgs.parameterization_closure": check_parameterization_closure,
    "check:higgs.boundary_parameters": check_boundary_parameters,
}
