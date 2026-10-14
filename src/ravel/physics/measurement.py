"""Inference for explicitly supplied Gaussian measurement models.

This route consumes measurements in their declared units, never converts a
YODA distribution into event counts, and never manufactures a covariance or SM
prediction. Normalized measurements require explicit linear constraints and
their exact covariance null space. Optional Spey inference uses its documented
``default.multivariate_normal`` backend; goodness of fit is not an exclusion.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

from ravel.physics.quantities import _keys, _number, _text, _unique, validate_binning


def validate(spec):
    """Validate task syntax without reading inputs or importing inference tools."""
    if isinstance(spec, dict) and spec.get("inference") == "linear_fit":
        _keys(spec, ("schema_version", "input", "inference"), (), "measurement linear-fit task")
        if type(spec["schema_version"]) is not int or spec["schema_version"] != 1:
            raise ValueError("unsupported measurement schema_version")
        _text(spec["input"], "measurement input path")
        return json.loads(json.dumps(spec, allow_nan=False))
    _keys(spec, ("schema_version", "input", "inference", "signal_strength"), ("poi_max",), "measurement task")
    if type(spec["schema_version"]) is not int or spec["schema_version"] != 1:
        raise ValueError("unsupported measurement schema_version")
    _text(spec["input"], "measurement input path")
    if spec["inference"] not in ("goodness_of_fit", "spey_cls"):
        raise ValueError("inference must be goodness_of_fit, spey_cls or linear_fit")
    if _number(spec["signal_strength"], "signal_strength") < 0:
        raise ValueError("signal_strength must be nonnegative")
    if spec["inference"] == "spey_cls":
        if "poi_max" not in spec or _number(spec["poi_max"], "poi_max") <= 0:
            raise ValueError("spey_cls requires a positive finite poi_max")
    elif "poi_max" in spec:
        raise ValueError("poi_max is only defined for spey_cls")
    return json.loads(json.dumps(spec, allow_nan=False))


def inputs(spec, base_dir):
    """Return files that the supervising lifecycle must bind before approval."""
    spec = validate(spec)
    path = Path(spec["input"])
    if not path.is_absolute():
        path = Path(base_dir) / path
    if path.is_symlink() or not path.is_file():
        raise ValueError("measurement input must be a regular, nonsymlink file")
    return [path.resolve()]


def _load(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate measurement JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"nonfinite JSON constant: {value}")

    raw = path.read_bytes()
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant), hashlib.sha256(raw).hexdigest()


def _vector(record, bin_ids, unit, label, np):
    _keys(record, ("bin_ids", "values", "unit"), label=label)
    _unique(record["bin_ids"], f"{label} bin_ids")
    if set(record["bin_ids"]) != set(bin_ids):
        raise ValueError(f"{label} bin identity does not match quantity")
    if record["unit"] != unit:
        raise ValueError(f"{label} unit does not match quantity")
    if not isinstance(record["values"], list) or len(record["values"]) != len(bin_ids):
        raise ValueError(f"{label} vector has wrong size")
    values = [_number(value, label) for value in record["values"]]
    return np.array([values[record["bin_ids"].index(bin_id)] for bin_id in bin_ids])


def _matrix(record, bin_ids, unit, label, np):
    _keys(record, ("bin_ids", "matrix", "unit"), label=label)
    _unique(record["bin_ids"], f"{label} bin_ids")
    if set(record["bin_ids"]) != set(bin_ids) or record["unit"] != f"({unit})^2":
        raise ValueError(f"{label} bin identity or squared unit does not match quantity")
    matrix = record["matrix"]
    n = len(bin_ids)
    if not isinstance(matrix, list) or len(matrix) != n or any(not isinstance(row, list) or len(row) != n for row in matrix):
        raise ValueError(f"{label} must be a square matrix covering every bin")
    for row in matrix:
        for value in row:
            _number(value, label)
    order = [record["bin_ids"].index(bin_id) for bin_id in bin_ids]
    matrix = np.array(matrix, dtype=float)[np.ix_(order, order)]
    scale = max(float(np.max(np.abs(matrix))), 1e-300)
    if not np.allclose(matrix, matrix.T, rtol=0, atol=1e-12 * scale):
        raise ValueError(f"{label} is asymmetric")
    matrix = (matrix + matrix.T) / 2
    if float(np.linalg.eigvalsh(matrix).min()) < -1e-12 * scale:
        raise ValueError(f"{label} is not positive semidefinite")
    return matrix


def prepare(document):
    """Validate the complete supplied model and return projected arrays.

    Theory covariance, if present, is fixed with respect to signal strength and
    is added only under the caller's explicit independent-theory declaration.
    No unrecorded ridge regularization, bin dropping or diagonal fallback occurs.
    """
    import numpy as np

    linear = isinstance(document, dict) and "linear_terms" in document
    required = ("schema_version", "analysis_id", "quantity", "data", "sm", "linear_terms" if linear else "signal",
                "experimental_covariance", "covariance_policy", "overlap", "constraints")
    _keys(document, required, ("theory_covariance",), "measurement input")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("unsupported measurement input schema_version")
    _text(document["analysis_id"], "analysis_id")
    quantity = document["quantity"]
    _keys(quantity, ("axes", "bins", "representation", "normalization", "unit"), label="measurement quantity")
    volumes = validate_binning(quantity["axes"], quantity["bins"])
    if quantity["representation"] not in ("integrated", "differential") or quantity["normalization"] not in ("absolute", "normalized"):
        raise ValueError("explicit measurement representation and normalization are required")
    unit = _text(quantity["unit"], "quantity unit")
    if quantity["normalization"] == "normalized":
        dimensions = [axis["unit"] for axis in quantity["axes"] if axis["unit"] != "1"]
        expected_unit = "1/(" + "*".join(dimensions) + ")" if dimensions and quantity["representation"] == "differential" else "1"
        if unit != expected_unit:
            raise ValueError(f"normalized quantity unit must be {expected_unit}")
    ids = [b["id"] for b in quantity["bins"]]
    n = len(ids)
    data, sm = (_vector(document[key], ids, unit, key, np) for key in ("data", "sm"))
    terms, parameters = (_terms(document["linear_terms"], ids, unit, np) if linear else (None, None))
    signal = _vector(document["signal"], ids, unit, "signal", np) if not linear else np.zeros(n)
    experimental = _matrix(document["experimental_covariance"], ids, unit, "experimental_covariance", np)
    policy = document["covariance_policy"]
    if policy == "experimental_only":
        if "theory_covariance" in document:
            raise ValueError("theory covariance supplied but excluded by covariance_policy")
        theory = np.zeros_like(experimental)
    elif policy == "independent_theory_sum":
        if "theory_covariance" not in document:
            raise ValueError("independent_theory_sum requires supplied theory covariance")
        theory = _matrix(document["theory_covariance"], ids, unit, "theory_covariance", np)
    else:
        raise ValueError("covariance_policy must be experimental_only or independent_theory_sum")
    covariance = experimental + theory
    if not np.all(np.isfinite(covariance)):
        raise ValueError("combined covariance is nonfinite")
    overlap = document["overlap"]
    if not isinstance(overlap, dict):
        raise ValueError("an explicit overlap policy is required")
    if overlap.get("policy") == "single_measurement":
        _keys(overlap, ("policy",), label="overlap policy")
    elif overlap.get("policy") == "joint_covariance":
        _keys(overlap, ("policy", "evidence"), label="overlap policy")
        _text(overlap["evidence"], "joint covariance evidence")
    elif overlap.get("policy") == "independent_measurements":
        _keys(overlap, ("policy", "bin_groups", "evidence"), label="overlap policy")
        _text(overlap["evidence"], "independence evidence")
        groups = overlap["bin_groups"]
        if not isinstance(groups, list) or len(groups) != n:
            raise ValueError("bin_groups must identify every quantity bin")
        for group in groups:
            _text(group, "measurement group")
        for i in range(n):
            for j in range(n):
                if groups[i] != groups[j] and (experimental[i, j] != 0 or theory[i, j] != 0):
                    raise ValueError("independence declaration conflicts with cross-measurement covariance")
    else:
        raise ValueError("unknown overlap policy; overlapping measurements require a supplied joint covariance")
    constraints = document["constraints"]
    if not isinstance(constraints, list):
        raise ValueError("constraints must be an explicit list")
    constraint_rows, constraint_values = [], []
    for constraint in constraints:
        _keys(constraint, ("coefficients", "value"), label="linear constraint")
        row = constraint["coefficients"]
        if not isinstance(row, list) or len(row) != n:
            raise ValueError("constraint dimensionality differs from quantity")
        row = np.array([_number(x, "constraint coefficient") for x in row])
        norm = float(np.linalg.norm(row))
        if not math.isfinite(norm) or norm == 0:
            raise ValueError("constraint coefficients must have finite nonzero norm")
        constraint_rows.append(row / norm)
        constraint_values.append(_number(constraint["value"], "constraint value") / norm)
    if quantity["normalization"] == "normalized":
        area = np.array(volumes if quantity["representation"] == "differential" else [1.0]*n)
        if not any(np.allclose(c["coefficients"], area, rtol=1e-12, atol=0) and math.isclose(c["value"], 1., rel_tol=1e-12) for c in constraints):
            raise ValueError("normalized quantity requires an explicit unit-area constraint using bin volumes")
    if constraint_rows:
        a, b = np.array(constraint_rows), np.array(constraint_values)
        _, singular, vt = np.linalg.svd(a, full_matrices=True)
        rank = int(np.count_nonzero(singular > 1e-12 * singular.max()))
        if rank != len(constraints):
            raise ValueError("linear constraints must be independent")
        deformations = [("signal deformation", signal)] if terms is None else [
            ("linear term " + parameters[k]["name"], terms[:, k]) for k in range(terms.shape[1])]
        for label, vector, expected in (("data", data, b), ("sm", sm, b), *((l, v, np.zeros_like(b)) for l, v in deformations)):
            if not np.allclose(a @ vector, expected, rtol=1e-10, atol=1e-10 * max(float(np.max(np.abs(vector))), 1e-300)):
                raise ValueError(f"{label} violates a declared deterministic constraint")
        cscale = max(float(np.max(np.abs(covariance))), 1e-300)
        if not np.allclose(covariance @ a.T, 0, rtol=0, atol=1e-10 * cscale):
            raise ValueError("covariance does not preserve the declared deterministic constraints")
        projection = vt[rank:]
    else:
        rank, projection = 0, np.eye(n)
    if rank == n:
        raise ValueError("constraints leave no stochastic measurement degrees of freedom")
    reduced = projection @ covariance @ projection.T
    eigen = np.linalg.eigvalsh(reduced)
    if eigen.min() <= max(eigen.max() * 1e-12, 0):
        raise ValueError("covariance has an undeclared null direction or is numerically ill-conditioned")
    return {"bin_ids": ids, "quantity": quantity, "data": data, "sm": sm, "signal": signal,
            "covariance": covariance, "projection": projection, "projected_covariance": reduced,
            "projected_data": projection @ data, "projected_sm": projection @ sm,
            "projected_signal": projection @ signal, "degrees_of_freedom": n-rank,
            "covariance_condition_number": float(eigen.max() / eigen.min()),
            "linear_terms": terms, "parameters": parameters,
            "projected_terms": None if terms is None else projection @ terms}


def _terms(record, bin_ids, unit, np):
    """Prediction derivatives d(prediction)/d(parameter) for a linear model."""
    _keys(record, ("parameters", "bin_ids", "unit", "matrix"), label="linear_terms")
    _unique(record["bin_ids"], "linear_terms bin_ids")
    if set(record["bin_ids"]) != set(bin_ids):
        raise ValueError("linear_terms bin identity does not match quantity")
    if record["unit"] != unit:
        raise ValueError("linear_terms unit (prediction change per unit parameter) must equal the quantity unit")
    parameters = record["parameters"]
    if not isinstance(parameters, list) or not parameters:
        raise ValueError("linear_terms requires at least one parameter")
    for row in parameters:
        _keys(row, ("name", "unit"), label="linear parameter")
        _text(row["name"], "parameter name")
        _text(row["unit"], "parameter unit")
    _unique([row["name"] for row in parameters], "parameter names")
    matrix = record["matrix"]
    p = len(parameters)
    if not isinstance(matrix, list) or len(matrix) != len(bin_ids) or any(
            not isinstance(row, list) or len(row) != p for row in matrix):
        raise ValueError("linear_terms matrix must have one row per bin and one column per parameter")
    values = [[_number(x, "linear term") for x in row] for row in matrix]
    order = [record["bin_ids"].index(bin_id) for bin_id in bin_ids]
    return np.array([values[i] for i in order], dtype=float), [dict(row) for row in parameters]


LEVELS = (("68.27", 0.6826894921370859), ("95", 0.95))


def linear_fit(model):
    """Closed-form generalized least squares for prediction = sm + terms @ theta.

    Exact for a linear model with fixed Gaussian covariance: profiled intervals
    are best fit +/- z sigma and joint regions are Fisher ellipsoids at the
    chi-square quantile for the number of parameters. Signs are not restricted.
    """
    import numpy as np
    from scipy.stats import chi2, norm

    a, c = model["projected_terms"], model["projected_covariance"]
    r = model["projected_data"] - model["projected_sm"]
    p = a.shape[1]
    dof = model["degrees_of_freedom"] - p
    if dof < 0:
        raise ValueError("more fitted parameters than stochastic measurement degrees of freedom")
    ci_a = np.linalg.solve(c, a)
    fisher = a.T @ ci_a
    fisher = (fisher + fisher.T) / 2
    eigen = np.linalg.eigvalsh(fisher)
    if eigen.min() <= max(eigen.max(), 0) * 1e-10:
        raise ValueError("the measurements do not constrain every parameter direction; the linear model is degenerate")
    covariance = np.linalg.inv(fisher)
    covariance = (covariance + covariance.T) / 2
    best = covariance @ (ci_a.T @ r)
    chi2_min = max(float((r - a @ best) @ np.linalg.solve(c, r - a @ best)), 0.)
    chi2_sm = max(float(r @ np.linalg.solve(c, r)), 0.)
    sigma = np.sqrt(np.diag(covariance))
    intervals = []
    for k, row in enumerate(model["parameters"]):
        one = float(ci_a[:, k] @ r / fisher[k, k])
        width = 1 / math.sqrt(fisher[k, k])
        profiled, fixed = {}, {"best_fit": one}
        for label, level in LEVELS:
            z = float(norm.ppf(0.5 + level / 2))
            profiled[label] = [float(best[k] - z * sigma[k]), float(best[k] + z * sigma[k])]
            fixed[label] = [one - z * width, one + z * width]
        intervals.append({"parameter": row["name"], "unit": row["unit"], "profiled": profiled, "others_fixed_at_zero": fixed})
    delta = max(chi2_sm - chi2_min, 0.)
    return {"parameters": model["parameters"], "best_fit": best.tolist(), "standard_errors": sigma.tolist(),
            "covariance": covariance.tolist(), "correlation": (covariance / np.outer(sigma, sigma)).tolist(),
            "fisher_information": fisher.tolist(), "chi2_min": chi2_min, "degrees_of_freedom": dof,
            "p_value": float(chi2.sf(chi2_min, dof)) if dof > 0 else None,
            "sm_point": {"chi2": chi2_sm, "delta_chi2": delta, "p_value": float(chi2.sf(delta, p))},
            "intervals": intervals,
            "joint_region": {"definition": "(theta - best_fit)^T fisher_information (theta - best_fit) <= delta_chi2",
                             "delta_chi2": {label: float(chi2.ppf(level, p)) for label, level in LEVELS}},
            "method": "closed-form generalized least squares; exact for a linear model with fixed Gaussian covariance",
            "sign_constraints": "none"}


def _spey_limits(model, spec, np):
    """Obtain all six bounded roots from Spey and audit them analytically.

    A fixed-covariance, one-parameter Gaussian has an exact one-dimensional
    sufficient statistic. Supplying it to the same Gaussian backend preserves
    every likelihood ratio and avoids backend assumptions about positive bin
    contents after a normalized measurement's orthogonal projection.
    """
    from scipy.optimize import brentq
    from scipy.stats import norm
    from ravel.limits import LimitCurve, LimitResult

    # Spey's optional import-time update request is inappropriate in a pinned run.
    os.environ["SPEY_CHECKUPDATE"] = "OFF"
    try:
        import spey
    except ImportError as error:
        raise RuntimeError("spey_cls requires the full Python installation, including spey==0.2.6") from error
    if spey.version() != "0.2.6":
        raise RuntimeError("this adapter is verified with spey==0.2.6; other versions require a compatibility review")
    covariance, signal = model["projected_covariance"], model["projected_signal"]
    inverse_signal = np.linalg.solve(covariance, signal)
    information = float(signal @ inverse_signal)
    if information <= 0 or not math.isfinite(information):
        raise ValueError("the supplied signal has no finite sensitivity in the stochastic measurement subspace")
    sigma = 1 / math.sqrt(information)
    muhat = float(inverse_signal @ (model["projected_data"] - model["projected_sm"]) / information)
    statistic = muhat / sigma
    backend = spey.get_backend("default.multivariate_normal")(
        signal_yields=[1 / sigma], background_yields=[0.0], data=[statistic], covariance_matrix=[[1.0]])
    cap = spec["poi_max"]
    fit_cap = max(cap * 2, abs(muhat) + 20*sigma, 1.0)
    cache = {}

    def cls(mu):
        if mu == 0:
            return [1.0]*6
        if mu not in cache:
            observed = backend.exclusion_confidence_level(poi_test=mu, expected=spey.ExpectationType.observed,
                par_bounds=[(0.0, fit_cap)], verbose=False)
            expected = backend.exclusion_confidence_level(poi_test=mu, expected=spey.ExpectationType.apriori,
                par_bounds=[(0.0, fit_cap)], verbose=False)
            if len(observed) != 1 or len(expected) != 5:
                raise ValueError("unexpected Spey CLs result shape")
            values = [1 - float(x) for x in [*observed, *expected]]
            if any(not math.isfinite(x) or x < -1e-10 or x > 1+1e-10 for x in values):
                raise ValueError("Spey returned an invalid CLs value")
            cache[mu] = values
        return cache[mu]

    curves, checks = [], []
    cap_values = cls(cap)
    for index, hat in enumerate([muhat, *[x*sigma for x in (-2, -1, 0, 1, 2)]]):
        if cap_values[index] > .05:
            curves.append(LimitCurve(cap, "above_scan", (cap, None)))
            checks.append({"status": "above_scan", "cls_at_cap": cap_values[index]})
            continue
        root = float(brentq(lambda mu: cls(mu)[index] - .05, 0, cap, xtol=1e-10, rtol=1e-10, maxiter=100))
        actual = cls(root)[index]
        # At an upper-limit crossing root >= muhat; this is the independent
        # closed-form Gaussian tail ratio for the same qtilde CLs model.
        analytic = float(math.exp(norm.logsf((root-hat)/sigma) - norm.logcdf(hat/sigma)))
        if abs(actual-.05) > 5e-5 or abs(actual-analytic) > 5e-5 or root < max(hat, 0):
            raise ValueError("Spey root failed the independent Gaussian CLs audit")
        curves.append(LimitCurve(root, "resolved", (0., cap)))
        checks.append({"status": "resolved", "cls": actual, "independent_gaussian_cls": analytic,
                       "residual": actual-.05, "bracket_cls": [1., cap_values[index]]})
    limits = LimitResult(curves[0], tuple(curves[1:]), origin="spey.default.multivariate_normal",
                        notes=("Supplied fixed-covariance Gaussian measurement; asymptotic qtilde; apriori expected bands.",))
    return {"backend": "spey.default.multivariate_normal", "backend_version": spey.version(),
            "confidence_level": .95, "unit": "dimensionless_signal_strength", "limits": limits.to_dict(),
            "numerical_evidence": checks, "poi_cap": cap, "fit_poi_cap": fit_cap,
            "sufficient_statistic": {"standardized_measurement": statistic, "signal_per_unit_strength": 1/sigma,
                                     "variance": 1.0, "exact_for": "linear signal with fixed supplied Gaussian covariance"},
            "excluded_at_test_strength": curves[0].exclusion(spec["signal_strength"]),
            "expected_prescription": "apriori", "test_statistic": "qtilde"}


def run(spec, base_dir, output_dir):
    """Execute a supplied model and retain a new, self-describing JSON result."""
    import numpy as np
    import scipy
    from scipy.stats import chi2

    spec = validate(spec)
    path = inputs(spec, base_dir)[0]
    document, digest = _load(path)
    model = prepare(document)
    if (spec["inference"] == "linear_fit") != (model["linear_terms"] is not None):
        raise ValueError("linear_fit requires linear_terms in the input; other inferences require a signal vector")
    if spec["inference"] == "linear_fit":
        return _write_linear(spec, document, digest, path, model, output_dir)
    residual = model["projected_data"] - model["projected_sm"]
    signal, covariance = model["projected_signal"], model["projected_covariance"]
    inverse_residual = np.linalg.solve(covariance, residual)
    inverse_signal = np.linalg.solve(covariance, signal)
    information = float(signal @ inverse_signal)
    dof = model["degrees_of_freedom"]

    def goodness(vector):
        value = max(float(vector @ np.linalg.solve(covariance, vector)), 0.)
        return {"chi2": value, "degrees_of_freedom": dof, "p_value": float(chi2.sf(value, dof))}

    fit = None
    if information > 0:
        muhat = float(signal @ inverse_residual / information)
        fit = {"unconstrained_signal_strength": muhat, "standard_error": 1 / math.sqrt(information),
               "chi2": max(float((residual-muhat*signal) @ np.linalg.solve(covariance, residual-muhat*signal)), 0.),
               "degrees_of_freedom": dof-1}
    result = {"schema_version": 1, "kind": "supplied_gaussian_measurement", "analysis_id": document["analysis_id"],
              "input": {"path": str(path), "sha256": digest}, "task": spec,
              "quantity": model["quantity"], "bin_ids": model["bin_ids"], "unit": model["quantity"]["unit"],
              "goodness_of_fit": {"sm": goodness(residual),
                                  "tested_model": goodness(residual-spec["signal_strength"]*signal)},
              "fit": fit, "covariance_policy": document["covariance_policy"], "overlap": document["overlap"],
              "covariance_condition_number": model["covariance_condition_number"],
              "constraint_projection": model["projection"].tolist(), "constraints": document["constraints"],
              "inference": None, "status": "passed", "status_scope": "numerical evaluation of the supplied model; not physics validation",
              "versions": {"numpy": np.__version__, "scipy": scipy.__version__},
              "physics_validated": False,
              "limitations": ["Inference is conditional on the supplied Gaussian measurement and fixed covariance, not an experimental-likelihood reconstruction.",
                              "Goodness-of-fit p-values are not CLs exclusion limits or discovery claims.",
                              "The supplied theory covariance is independent of experimental covariance and fixed with signal strength when that policy is declared.",
                              "Input provenance, Gaussian approximation, overlap evidence, unfolding/model dependence and theory coverage require separate scientific validation."]}
    if spec["inference"] == "spey_cls":
        result["inference"] = _spey_limits(model, spec, np)
        limits = result["inference"]["limits"]
        if any(curve["status"] != "resolved" for curve in [limits["observed"], *limits["expected"]]):
            result["status"] = "failed"
            result["failure_reason"] = "One or more CLs crossings remain beyond the declared signal-strength cap."
    encoded = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "measurement.json").open("x") as stream:
        stream.write(encoded)
    return result


def _write_linear(spec, document, digest, path, model, output_dir):
    import numpy as np
    import scipy
    fit = linear_fit(model)
    result = {"schema_version": 1, "kind": "supplied_gaussian_measurement", "analysis_id": document["analysis_id"],
              "input": {"path": str(path), "sha256": digest}, "task": spec,
              "quantity": model["quantity"], "bin_ids": model["bin_ids"], "unit": model["quantity"]["unit"],
              "inference": "linear_fit", "linear_fit": fit,
              "covariance_policy": document["covariance_policy"], "overlap": document["overlap"],
              "covariance_condition_number": model["covariance_condition_number"],
              "constraint_projection": model["projection"].tolist(), "constraints": document["constraints"],
              "status": "passed", "status_scope": "numerical evaluation of the supplied linear model; not physics validation",
              "versions": {"numpy": np.__version__, "scipy": scipy.__version__}, "physics_validated": False,
              "limitations": ["The fit is conditional on the supplied linear prediction derivatives, SM prediction and fixed Gaussian covariance.",
                              "Higher-order terms in the parameters are not included; linear-order validity is a separate check.",
                              "Overlap, unfolding and theory-covariance assumptions require separate scientific validation."]}
    encoded = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "measurement.json").open("x") as stream:
        stream.write(encoded)
    return result
