"""Correlated supplied-rate coupling fits using iminuit profiles.

These are declared likelihood-ratio approximations to reduced measurements.
For deviation d = prediction - measurement, the variable width is
2*s_minus*s_plus/(s_minus+s_plus) + d*(s_plus-s_minus)/(s_minus+s_plus).
Thus the supplied one-sigma endpoints have delta chi-square one. Log-normal
treatment uses fixed lower/upper widths in log(prediction/measurement),
derived from the logarithms of the supplied endpoints. This is a two-sided
log-normal approximation; equal log widths give an ordinary log-normal profile.
Neither treatment adds a parameter-dependent Gaussian determinant to a supplied
profile approximation.
"""
from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import numpy as np
from iminuit import Minuit
from scipy.stats import chi2 as chi2_distribution
from scipy.optimize import brentq

from ravel.physics.higgs_parameterization import Parameterization
from ravel.physics.quantities import _keys, _text
from ravel.physics.supplied_contracts import output_contract, publish
from ravel.validation.higgs_bundle_checks import (
    check_boundary_parameters, check_measurement_bundle,
    check_parameterization_closure, check_prediction_convention,
)


TREATMENTS = ("symmetric-gaussian", "variable-width-gaussian", "log-normal")
CONFIDENCES = {"68": float(chi2_distribution.cdf(1, 1)), "95": 0.95}


class RateLikelihood:
    """Prevalidated arrays, without diagonal fallback or ridge regularization."""

    def __init__(self, measurements, treatment):
        if treatment not in TREATMENTS:
            raise ValueError("unknown uncertainty treatment")
        check = check_measurement_bundle(measurements)
        self.treatment = treatment
        self.values = np.array([r["value"] for r in measurements["rows"]])
        self.minus = np.array([r["uncertainty"]["minus"] for r in measurements["rows"]])
        self.plus = np.array([r["uncertainty"]["plus"] for r in measurements["rows"]])
        correlation = np.array(check["correlation"])
        eigen = np.linalg.eigvalsh(correlation)
        if eigen.min() <= eigen.max() * 1e-12:
            raise ValueError("singular correlation has an undeclared null direction")
        self.inverse = np.linalg.inv(correlation)
        if treatment == "log-normal":
            if np.any(self.values <= 0) or np.any(self.minus >= self.values):
                raise ValueError("log-normal requires positive measurement and lower endpoint")
            self.minus = -np.log1p(-self.minus / self.values)
            self.plus = np.log1p(self.plus / self.values)

    def __call__(self, prediction):
        prediction = np.asarray(prediction, dtype=float)
        if prediction.shape != self.values.shape or not np.all(np.isfinite(prediction)):
            raise ValueError("prediction must supply a finite value per measurement row")
        deviation = prediction - self.values
        if self.treatment == "log-normal":
            if np.any(prediction <= 0):
                return math.inf
            deviation = np.log(prediction / self.values)
        if self.treatment == "log-normal":
            width = np.where(deviation >= 0, self.plus, self.minus)
        elif self.treatment == "symmetric-gaussian":
            width = (self.minus + self.plus) / 2
        else:
            width = (2 * self.minus * self.plus + (self.plus - self.minus) * deviation) / (self.minus + self.plus)
        if np.any(width <= 0) or not np.all(np.isfinite(width)):
            return math.inf
        residual = deviation / width
        value = float(residual @ self.inverse @ residual)
        return max(value, 0.0) if math.isfinite(value) else math.inf


def chi_square(measurements, prediction, *, treatment="symmetric-gaussian"):
    """Evaluate a supplied prediction in measurement row order."""
    return RateLikelihood(measurements, treatment)(prediction)


def _minimize(objective, names, start, limits, *, fixed=(), covariance=False):
    m = Minuit(objective, *start, name=names)
    m.errordef = Minuit.LEAST_SQUARES
    m.tol = 1e-9
    m.precision = 1e-15
    for name in names:
        m.limits[name] = limits[name]
        m.fixed[name] = name in fixed
    if len(fixed) < len(names):
        m.migrad()
        if not m.valid:
            m.strategy = 2
            m.migrad()
        if covariance:
            m.hesse()
        if not m.valid or (covariance and (m.covariance is None or not m.fmin.has_posdef_covar or m.fmin.has_made_posdef_covar)):
            raise ValueError("coupling fit/profile did not converge with a valid covariance")
    return m


def _affine_design(evaluator, free, point, row_ids):
    """Exact affine coefficients when the declared width is parameter independent."""
    doc = evaluator.document
    if any(n in free for n in doc.get("bsm_parameters", {}).values()):
        return None

    def coefficients(modifier):
        if "loop" in modifier:
            loop = doc["loops"][modifier["loop"]]
            modifier = {"parameter": loop["parameter"]} if loop["mode"] == "effective" else {"polynomial": loop["polynomial"]}
        if "constant" in modifier:
            return np.zeros(len(free))
        if "parameter" in modifier:
            return None if modifier["parameter"] in free else np.zeros(len(free))
        values = np.zeros(len(free))
        for term in modifier["polynomial"]["terms"]:
            powers = term["powers"]
            total = sum(powers.get(n, 0) for n in free)
            if total > 1:
                return None
            if total == 1:
                name = next(n for n in free if powers.get(n, 0) == 1)
                coefficient = term["coefficient"] * math.prod(point[n] ** power for n, power in powers.items() if n not in free)
                values[free.index(name)] += coefficient
        return values

    for modifier in doc["decays"].values():
        value = coefficients(modifier)
        if value is None or np.any(value):
            return None
    evaluated = evaluator.evaluate(point)
    rates = {r["id"]: r for r in doc["rates"]}
    design = []
    for identity in row_ids:
        row = rates[identity]
        coefficient = coefficients(doc["production"][row["production"]])
        if coefficient is None:
            return None
        design.append(coefficient * row["sm_value"] * evaluated["decay_scales"][row["decay"]] / evaluated["width_scaling"])
    return np.asarray(design)


def fit(measurements, parameterization, *, treatment="symmetric-gaussian", scans=(), predictor=None):
    """Fit a bundle, profiling all nonfixed parameters.

    ``predictor(point)`` is the in-process seam for other rate frameworks. It
    returns a finite vector in measurement row order. The supplied bundle still
    declares parameter domains, mass, units, conventions and width scaling.
    A caller supplying this seam owns its independent closure qualification.
    Scans are supplied records {parameters: [name, ...], axes: [[value, ...], ...]}
    with one or two free coordinates; no scientific grid is synthesized.
    """
    evaluator = Parameterization(parameterization)
    doc = evaluator.document
    convention_check = check_prediction_convention(measurements, doc)
    boundary_check = check_boundary_parameters(doc)
    closure_check = check_parameterization_closure(doc) if "closure" in doc and predictor is None else None
    likelihood = RateLikelihood(measurements, treatment)
    names = list(doc["parameters"])
    fixed = [n for n in names if doc["parameters"][n]["fixed"]]
    free = [n for n in names if n not in fixed]
    if not free:
        raise ValueError("coupling fit requires at least one free parameter")
    limits = boundary_check["limits"]
    row_ids = [r["id"] for r in measurements["rows"]]

    def prediction(point, evaluated):
        if predictor is not None:
            return np.asarray(predictor(point), dtype=float)
        rates = {r["id"]: r["value"] for r in evaluated["rates"]}
        return np.array([rates[key] for key in row_ids])

    def objective(*values):
        point = dict(zip(names, map(float, values)))
        try:
            evaluated = evaluator.evaluate(point)
        except (ValueError, OverflowError):
            return math.inf
        value = likelihood(prediction(point, evaluated))
        if "width_constraint" in doc:
            constraint = doc["width_constraint"]
            value += ((evaluated["width_scaling"] - constraint["value"]) / constraint["sigma"]) ** 2
        return value

    start = [doc["parameters"][n]["initial"] for n in names]
    m = _minimize(objective, names, start, limits, fixed=fixed, covariance=True)
    affine_covariance = None
    if treatment == "symmetric-gaussian" and predictor is None and "width_constraint" not in doc:
        point = dict(zip(names, map(float, start)))
        design = _affine_design(evaluator, free, point, row_ids)
        if design is not None:
            sigma = (likelihood.minus + likelihood.plus) / 2
            precision = likelihood.inverse / np.outer(sigma, sigma)
            fisher = design.T @ precision @ design
            try:
                affine_covariance = np.linalg.inv(fisher)
            except np.linalg.LinAlgError as exc:
                raise ValueError("affine prediction has an unidentified parameter direction") from exc
            offset = prediction(point, evaluator.evaluate(point)) - design @ np.array([point[n] for n in free])
            exact = affine_covariance @ design.T @ precision @ (likelihood.values - offset)
            refined = {**point, **dict(zip(free, map(float, exact)))}
            # A constrained optimum remains the original iminuit result.
            if all((limits[n][0] is None or refined[n] >= limits[n][0]) and
                   (limits[n][1] is None or refined[n] <= limits[n][1]) for n in free):
                m = _minimize(objective, names, [refined[n] for n in names], limits, fixed=fixed, covariance=True)
            else:
                affine_covariance = None
    best = {n: float(m.values[n]) for n in names}
    minimum = float(m.fval)
    covariance = np.array([[m.covariance[a, b] for b in free] for a in free])
    if affine_covariance is not None:
        covariance = affine_covariance
    errors = np.sqrt(np.diag(covariance))
    if not np.all(np.isfinite(covariance)) or np.any(errors <= 0):
        raise ValueError("invalid fitted parameter covariance")
    intervals = {}
    for label, confidence in CONFIDENCES.items():
        m.minos(*free, cl=confidence)
        intervals[label] = {}
        for name in free:
            error = m.merrors[name]
            if not error.is_valid:
                raise ValueError(f"profile interval failed for parameter {name}")
            lower, upper = best[name] + float(error.lower), best[name] + float(error.upper)
            threshold = float(chi2_distribution.ppf(confidence, 1))
            if len(free) == 1:
                def crossing(value):
                    point = {**best, name: value}
                    return objective(*[point[n] for n in names]) - minimum - threshold

                for direction, endpoint, at_limit in ((-1, lower, error.at_lower_limit), (1, upper, error.at_upper_limit)):
                    if at_limit:
                        continue
                    limit = limits[name][0 if direction == -1 else 1]
                    while crossing(endpoint) < 0:
                        endpoint = best[name] + 1.01 * (endpoint - best[name])
                        if limit is not None and direction * (endpoint - limit) > 0:
                            endpoint = limit
                            break
                    root = brentq(crossing, *sorted((best[name], endpoint)), xtol=1e-12, rtol=1e-14)
                    if direction == -1:
                        lower = root
                    else:
                        upper = root
            intervals[label][name] = {
                "lower": lower, "upper": upper,
                "lower_at_limit": bool(error.at_lower_limit), "upper_at_limit": bool(error.at_upper_limit),
                "delta_chi2": threshold,
                "confidence": confidence, "degrees_of_freedom": 1,
            }
    scan_results = []
    for scan in scans:
        _keys(scan, ("parameters", "axes"), label="coupling scan")
        selected, axes = scan["parameters"], scan["axes"]
        if not isinstance(selected, list) or len(selected) not in (1, 2) or len(set(selected)) != len(selected) or any(n not in free for n in selected):
            raise ValueError("scan must select one or two distinct free parameters")
        if not isinstance(axes, list) or len(axes) != len(selected) or any(not isinstance(a, list) or not a for a in axes):
            raise ValueError("scan axes must supply values for each selected parameter")
        if any(type(v) not in (int, float) or not math.isfinite(v) for a in axes for v in a):
            raise ValueError("scan axes must contain finite numbers")
        points = []
        for coordinates in itertools.product(*axes):
            scan_point = {**best, **dict(zip(selected, coordinates))}
            try:
                evaluator.point(scan_point)
            except ValueError:
                points.append({"coordinates": list(coordinates), "delta_chi2": None, "status": "outside_domain"})
                continue
            scan_fixed = [*fixed, *selected]
            if len(scan_fixed) == len(names):
                value = objective(*[scan_point[n] for n in names])
            else:
                profiled = _minimize(objective, names, [scan_point[n] for n in names], limits, fixed=scan_fixed)
                value = float(profiled.fval)
            if not math.isfinite(value):
                points.append({"coordinates": list(coordinates), "delta_chi2": None, "status": "outside_likelihood_domain"})
                continue
            if value < minimum - 1e-7:
                raise ValueError("profile scan found a lower minimum; supply a better fit initialization")
            points.append({"coordinates": list(coordinates), "delta_chi2": max(value - minimum, 0.0), "status": "converged"})
        dof = len(selected)
        scan_results.append({"parameters": selected, "axes": axes, "points": points, "degrees_of_freedom": dof,
                             "thresholds": {k: float(chi2_distribution.ppf(c, dof)) for k, c in CONFIDENCES.items()}})
    sm = {n: doc["parameters"][n]["sm"] for n in names}
    sm_value = objective(*[sm[n] for n in names])
    if not math.isfinite(sm_value):
        raise ValueError("declared SM point lies outside the likelihood domain")
    if any(sm[n] != best[n] for n in fixed):
        raise ValueError("fixed parameters differ from the SM null; comparison is not nested")
    delta = sm_value - minimum
    if delta < -1e-7:
        raise ValueError("SM point has a lower objective than the fitted minimum")
    nobs = len(row_ids) + int("width_constraint" in doc)
    at_boundary = any(interval["lower_at_limit"] or interval["upper_at_limit"] for interval in intervals["68"].values())
    result = {"schema_version": 1, "kind": "higgs-coupling-fit", "status": "converged",
              "engine": "iminuit", "engine_version": __import__("iminuit").__version__,
              "central_value_method": "exact affine Gaussian stationary point verified by iminuit" if affine_covariance is not None else "iminuit MIGRAD",
              "treatment": treatment, "framework": doc["framework"], "mass_gev": doc["mass_gev"],
              "treatment_detail": {"symmetric-gaussian": "fixed arithmetic-mean error",
                                   "variable-width-gaussian": "width linear in prediction minus measurement",
                                   "log-normal": "two-sided fixed log-space endpoint widths"}[treatment],
              "convention": doc["convention"], "loop_modes": convention_check["loop_modes"],
              "best_fit": best, "chi2_min": minimum, "intervals": intervals, "scans": scan_results,
              "parameter_order": free, "covariance": covariance.tolist(),
              "correlation": (covariance / np.outer(errors, errors)).tolist(),
              "hesse_errors": dict(zip(free, map(float, errors))),
              "predictions": prediction(best, evaluator.evaluate(best)).tolist(), "row_ids": row_ids,
              "sm_comparison": {"parameters": sm, "chi2": sm_value, "delta_chi2": max(delta, 0.0),
                                "degrees_of_freedom": len(free),
                                "p_value": float(chi2_distribution.sf(max(delta, 0), len(free))),
                                "method": "asymptotic likelihood ratio", "boundary_sensitive": at_boundary},
              "sm_goodness_of_fit": {"degrees_of_freedom": nobs, "chi2": sm_value,
                                     "p_value": float(chi2_distribution.sf(sm_value, nobs))},
              "fit_degrees_of_freedom": nobs - len(free),
              "status_scope": "supplied_rate_coupling_fit", "physics_validated": False,
              "coverage_qualified": False, "optimizer_globality_qualified": False,
              "checks": [convention_check, boundary_check, *([closure_check] if closure_check else [])],
              "limitations": ["Reduced-rate likelihood approximation conditional on supplied errors and correlation.",
                              "Wilks thresholds and p-values need calibration for boundaries, nonlinearity and asymmetric treatments.",
                              "The symmetric treatment uses the arithmetic mean of the two error magnitudes.",
                              "HESSE covariance and local MINOS intervals do not enumerate disconnected minima."]}
    json.dumps(result, allow_nan=False)
    return result


def validate(spec):
    if isinstance(spec, dict) and spec.get("mode") == "mass-combination":
        raise ValueError("mass-combination mode is reserved for a separate adapter")
    _keys(spec, ("schema_version", "input", "output"), ("mode", "treatment", "scans"), "higgs coupling fit task")
    if type(spec["schema_version"]) is not int or spec["schema_version"] != 1:
        raise ValueError("unsupported coupling-fit task version")
    _text(spec["input"], "fit input")
    output_contract(spec["output"])
    if spec.get("mode", "couplings") != "couplings":
        raise ValueError("unsupported coupling-fit mode")
    if spec.get("treatment", "symmetric-gaussian") not in TREATMENTS:
        raise ValueError("unknown uncertainty treatment")
    return json.loads(json.dumps(spec, allow_nan=False))


def _context(spec, base_dir):
    from ravel.physics.inference.documents import Context
    context = Context(spec["input"], base_dir)
    _keys(context.document, ("measurements", "parameterization"), label="coupling-fit input")
    bundles = {}
    measurement_context = context
    for key in ("measurements", "parameterization"):
        raw = context.document[key]
        if isinstance(raw, dict) and set(raw) == {"path"}:
            nested = Context(context.path(raw["path"]), context.root)
            bundles[key] = nested.document
            context.pins.update(nested.pins)
            if key == "measurements":
                measurement_context = nested
        else:
            bundles[key] = json.loads(json.dumps(raw, allow_nan=False))
    measurement = bundles["measurements"]
    from ravel.physics.higgs_parameterization import _schema
    _schema(measurement, "measurement-bundle.json")
    if isinstance(measurement.get("correlation"), dict):
        reference = measurement["correlation"]
        order = reference.get("bin_ids")
        if not order:
            raise ValueError("correlation reference requires explicit bin_ids in table order")
        if reference["format"] == "hepdata":
            table = measurement_context._table(measurement_context.path(reference["path"]))
            axes = table.get("independent_variables", [])
            labels = list(dict.fromkeys(str(v.get("value")) for v in axes[0]["values"])) if len(axes) == 2 else []
            if labels != order:
                raise ValueError("correlation table labels differ from declared bin_ids order")
        measurement["correlation"] = measurement_context.matrix(reference, "correlation").tolist()
        measurement["correlation_order"] = order
        context.pins.update(measurement_context.pins)
    return context, bundles


def inputs(spec, base_dir):
    context, _ = _context(validate(spec), base_dir)
    return [Path(pin["path"]) for pin in context.inputs()]


def run(spec, base_dir, output_dir):
    """Pure Python adapter; called after the existing scientific admission."""
    spec = validate(spec)
    context, bundles = _context(spec, base_dir)
    check_parameterization_closure(bundles["parameterization"])
    result = fit(**bundles, treatment=spec.get("treatment", "symmetric-gaussian"), scans=spec.get("scans", ()))
    result["inputs"] = context.inputs()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    publish(output, result, spec["output"])
    return result
