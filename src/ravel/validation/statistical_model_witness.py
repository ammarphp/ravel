"""Independent physical-coordinate likelihood witnesses for constructed models.

No producer or compiler helper is imported. The checker verifies supplied
arithmetic, not the scientific validity, identity or independence of inputs.
Poisson and Gaussian normalizing constants are omitted consistently.
"""
from __future__ import annotations

import math


def _number(value, label):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{label} must be a finite number, not boolean")
    return float(value)


def _name(value, label):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be a nonempty trimmed name")
    return value


def _list(value, label, length=None):
    if not isinstance(value, list) or (length is not None and len(value) != length):
        raise ValueError(f"{label} has invalid array dimensions")
    return value


def _unique(values, label):
    for value in values:
        _name(value, label)
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {label}")


def _poisson_nll(counts, means):
    terms = []
    for count, mean in zip(counts, means):
        if mean < 0 or not math.isfinite(mean):
            raise ValueError("Poisson mean must be finite and nonnegative")
        if mean == 0:
            if count:
                return math.inf
            terms.append(0.0)
        else:
            terms.append(mean - count * math.log(mean))
    return math.fsum(terms)


def evaluate(document, point):
    """Evaluate means and NLL directly in the supplied physical nuisance basis.

    The point must identify every rate and auxiliary coordinate exactly once.
    An impossible positive observation at zero mean has infinite NLL; zero
    observed events at zero mean contribute zero, without a log(0) evaluation.
    """
    if not isinstance(document, dict) or type(document.get("schema_version")) is not int or document["schema_version"] != 1:
        raise ValueError("witness requires model schema_version 1")
    for key in ("parameters", "bins", "components", "auxiliary"):
        if key not in document:
            raise ValueError(f"model is missing {key}")
    parameters = _list(document["parameters"], "parameters")
    bins = _list(document["bins"], "bins")
    components = _list(document["components"], "components")
    if not parameters or not bins or not components:
        raise ValueError("model requires nonempty parameters, bins and components")
    rates, bounds = [], {}
    for parameter in parameters:
        if not isinstance(parameter, dict) or not {"name", "role", "bounds"} <= parameter.keys():
            raise ValueError("parameter requires name, role and bounds")
        name = _name(parameter["name"], "rate name")
        if parameter["role"] not in ("poi", "rate"):
            raise ValueError("parameter has unknown role")
        lower, upper = (_number(x, "parameter bound") for x in _list(parameter["bounds"], "bounds", 2))
        if lower < 0 or upper <= lower:
            raise ValueError("rate bounds must be nonnegative and ordered")
        rates.append(name)
        bounds[name] = (lower, upper)
    _unique(rates, "rate name")
    if sum(p["role"] == "poi" for p in parameters) != 1:
        raise ValueError("exactly one parameter must be the POI")
    counts, bin_ids = [], []
    for bin_ in bins:
        if not isinstance(bin_, dict) or not {"id", "observed"} <= bin_.keys():
            raise ValueError("bin requires id and observed")
        bin_ids.append(_name(bin_["id"], "bin id"))
        count = bin_["observed"]
        if type(count) is not int or count < 0:
            raise ValueError("observed Poisson count must be a nonnegative integer")
        _number(count, "observed count")
        counts.append(count)
    _unique(bin_ids, "bin id")
    auxiliary = document["auxiliary"]
    if not isinstance(auxiliary, dict) or not {"names", "observed", "covariance"} <= auxiliary.keys():
        raise ValueError("auxiliary requires names, observed and covariance")
    names = _list(auxiliary["names"], "auxiliary names")
    _unique(names, "auxiliary name")
    if set(names) & set(rates):
        raise ValueError("rate and auxiliary names collide")
    observed = [_number(x, "auxiliary observation") for x in _list(auxiliary["observed"], "auxiliary observed", len(names))]
    covariance = _list(auxiliary["covariance"], "auxiliary covariance", len(names))
    covariance = [[_number(x, "auxiliary covariance") for x in _list(row, "covariance row", len(names))] for row in covariance]
    if not isinstance(point, dict) or set(point) != set(rates) | set(names):
        raise ValueError("point must cover exactly every rate and auxiliary name")
    values = {name: _number(value, "point coordinate") for name, value in point.items()}
    for name in rates:
        if not bounds[name][0] <= values[name] <= bounds[name][1]:
            raise ValueError(f"point rate {name} lies outside declared bounds")
    auxiliary_nll = 0.0
    if names:
        import numpy as np

        matrix = np.asarray(covariance, dtype=float)
        scale = float(np.max(np.abs(matrix)))
        if scale == 0 or not np.allclose(matrix, matrix.T, rtol=0, atol=1e-12 * scale):
            raise ValueError("auxiliary covariance must be symmetric positive definite")
        # Validate without changing, symmetrizing or whitening the supplied basis.
        try:
            if float(np.linalg.eigvalsh(matrix).min()) <= 0:
                raise ValueError("auxiliary covariance must be positive definite")
            residual = np.asarray([y - values[name] for y, name in zip(observed, names)])
            auxiliary_nll = float(residual @ np.linalg.solve(matrix, residual) / 2)
        except np.linalg.LinAlgError as error:
            raise ValueError("invalid auxiliary covariance") from error
        if not math.isfinite(auxiliary_nll) or auxiliary_nll < 0:
            raise ValueError("invalid auxiliary quadratic form")
    contributions = [[] for _ in bins]
    component_ids = []
    for component in components:
        if not isinstance(component, dict) or not {"id", "nominal", "factors", "log_response"} <= component.keys():
            raise ValueError("component requires id, nominal, factors and log_response")
        component_ids.append(_name(component["id"], "component id"))
        nominal = _list(component["nominal"], "component nominal", len(bins))
        factors = _list(component["factors"], "component factors", len(bins))
        response = _list(component["log_response"], "component log_response", len(bins))
        for index in range(len(bins)):
            central = _number(nominal[index], "component nominal")
            if central < 0:
                raise ValueError("component nominal must be nonnegative")
            selected = _list(factors[index], "bin factors")
            _unique(selected, "bin factor")
            if set(selected) - set(rates):
                raise ValueError("component factor names an unknown rate")
            coefficients = [_number(x, "log response") for x in _list(response[index], "bin log_response", len(names))]
            try:
                exponent = math.fsum(a * values[name] for a, name in zip(coefficients, names))
                value = central * math.prod(values[name] for name in selected)
                # A structural zero is zero for every finite coordinate.
                if value != 0:
                    value *= math.exp(exponent)
            except (OverflowError, ValueError) as error:
                raise ValueError("nonfinite component prediction") from error
            if not math.isfinite(value):
                raise ValueError("nonfinite component prediction")
            contributions[index].append(value)
    _unique(component_ids, "component id")
    try:
        means = [math.fsum(items) for items in contributions]
        poisson_nll = _poisson_nll(counts, means)
    except (OverflowError, ValueError) as error:
        raise ValueError("invalid accumulated prediction") from error
    return {"means": means, "poisson_nll": poisson_nll,
            "auxiliary_nll": auxiliary_nll,
            "nll_without_constant": poisson_nll + auxiliary_nll}


def verify(document, points, claims, atol=1e-8):
    """Compare finite producer claims at frozen physical-coordinate points."""
    atol = _number(atol, "atol")
    if atol < 0:
        raise ValueError("atol must be nonnegative")
    points = _list(points, "points")
    claims = _list(claims, "claims", len(points))
    if not points:
        raise ValueError("verification requires at least one point")
    comparisons = []
    maximum = 0.0
    for index, (point, claim) in enumerate(zip(points, claims)):
        if not isinstance(claim, dict) or not {"means", "nll_without_constant"} <= claim.keys():
            raise ValueError("claim requires means and nll_without_constant")
        actual = evaluate(document, point)
        mean_claims = [_number(x, "claimed mean") for x in _list(claim["means"], "claimed means", len(actual["means"]))]
        residuals = {"means": [abs(a - c) for a, c in zip(actual["means"], mean_claims)]}
        for key in ("nll_without_constant", "poisson_nll", "auxiliary_nll"):
            if key in claim:
                claimed = _number(claim[key], f"claimed {key}")
                residuals[key] = abs(actual[key] - claimed)
        largest = max([*residuals["means"], *(v for k, v in residuals.items() if k != "means")])
        maximum = max(maximum, largest)
        comparisons.append({"point_index": index, "actual": actual,
                            "absolute_residuals": residuals, "passed": largest <= atol})
    return {"passed": maximum <= atol, "comparisons": comparisons,
            "max_absolute_residual": maximum, "atol": atol}


def on_off_reference(n, m, s, control_signal, transfer, mu):
    """Analytic profile of Pois(n|mu*s+beta) Pois(m|mu*c+tau*beta).

    Rates have nonnegative physical bounds with no numerical upper caps.
    This reference calculates a likelihood ratio, not CLs or coverage.
    """
    if any(type(x) is not int or x < 0 for x in (n, m)):
        raise ValueError("on/off observations must be nonnegative integers")
    _number(n, "n")
    _number(m, "m")
    s, c, tau, mu = [_number(x, label) for x, label in
                     ((s, "signal"), (control_signal, "control signal"), (transfer, "transfer"), (mu, "mu"))]
    if s <= 0 or c < 0 or tau <= 0 or mu < 0:
        raise ValueError("invalid on/off signal, transfer or POI")
    a = (1 + tau) * tau
    b = (1 + tau) * mu * (c + tau * s) - tau * (n + m)
    constant = (1 + tau) * mu * mu * s * c - mu * (n * c + tau * m * s)
    discriminant = b * b - 4 * a * constant
    if not math.isfinite(discriminant) or discriminant < 0:
        raise ValueError("invalid analytic profile polynomial")
    root = math.sqrt(discriminant)
    # Stable positive root when cancellation would occur in -b + sqrt(D).
    beta = max(0.0, (-2 * constant / (b + root)) if b > 0 and b + root else (-b + root) / (2 * a))
    means = [mu * s + beta, mu * c + tau * beta]
    profile = _poisson_nll((n, m), means)
    candidates = [(0.0, (n + m) / (1 + tau)), ((n + m) / (s + c), 0.0)]
    direction = tau * s - c
    if direction != 0:
        saturated = ((tau * n - m) / direction, (m * s - n * c) / direction)
        if min(saturated) >= 0:
            candidates.append(saturated)
    scored = [(_poisson_nll((n, m), (u * s + v, u * c + tau * v)), u, v) for u, v in candidates]
    global_nll, muhat, betahat = min(scored)
    if not math.isfinite(profile) or not math.isfinite(global_nll):
        raise ValueError("on/off reference has impossible observations")
    q = 0.0 if muhat > mu else max(0.0, 2 * (profile - global_nll))
    return {"profile_beta": beta, "means": means, "poisson_nll": profile,
            "muhat": muhat, "betahat": betahat, "global_poisson_nll": global_nll,
            "qtilde_mu": q, "identifiable": direction != 0}
