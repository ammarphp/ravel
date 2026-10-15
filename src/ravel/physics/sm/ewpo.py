"""Supplied electroweak Gaussian fits with explicit formula and scheme contracts.

All measurements, fit populations, reference points and covariance assumptions
are supplied. Polynomial shards carry sources and closed validity domains. The
shipped coefficient census has no qualified PDF domains: consumers must supply
them before evaluation. This module launches no programs and imports no upstream
physics package. Admitted EFT workers can call the injected upstream seams below.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.linalg import solve_triangular
from scipy.optimize import brentq, least_squares, minimize

PARAMETERS = ("m_Z", "m_t", "m_H", "alpha_s", "delta_alpha_had")
DATA = Path(__file__).resolve().parents[2] / "data/sm/ewpo/parametrizations.json"


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + " must be finite and numeric")
    return float(value)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def parametrizations():
    """Return independent copies of the cited coefficient census and source holds."""
    return json.loads(DATA.read_text())["parametrizations"]


def _sources(shard):
    sources = shard.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("formula source evidence is required")
    ids = []
    for row in sources:
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k].strip()
                                                for k in ("id", "citation", "locator")):
            raise ValueError("formula source id, citation and locator are required")
        ids.append(row["id"])
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate formula source")
    return ids


def _domain(shard):
    sources = _sources(shard)
    validity = shard.get("validity")
    if not isinstance(validity, dict) or validity.get("source") not in sources:
        raise ValueError("source-backed validity ranges are required; no extrapolation")
    ranges = validity.get("ranges")
    if not isinstance(ranges, dict) or not ranges:
        raise ValueError("closed validity ranges are required")
    answer = {}
    for name, limits in ranges.items():
        if not isinstance(limits, list) or len(limits) != 2:
            raise ValueError("validity range must have two finite endpoints")
        lo, hi = (_number(x, "validity endpoint") for x in limits)
        if lo >= hi:
            raise ValueError("validity endpoints must increase")
        answer[name] = (lo, hi)
    return answer


def _evaluate(shard, parameters):
    if shard.get("kind") != "polynomial":
        raise ValueError("cited polynomial unavailable; supply a qualified formula shard")
    ranges = _domain(shard)
    for name, (lo, hi) in ranges.items():
        value = _number(parameters.get(name), "validity parameter " + name)
        if not lo <= value <= hi:
            raise ValueError(name + " outside formula validity range")
    variables = {}
    definitions = shard.get("variables")
    terms = shard.get("terms")
    if not isinstance(definitions, dict) or not isinstance(terms, list) or not terms:
        raise ValueError("formula variables and coefficient terms required")
    for name, row in definitions.items():
        dependencies = row.get("parameters", [row.get("parameter")])
        if not isinstance(dependencies, list) or not dependencies or any(k not in ranges for k in dependencies):
            raise ValueError("every formula parameter needs a validity range")
        value = sum(_number(parameters[k], k) for k in dependencies)
        reference = _number(row.get("reference"), "formula reference")
        transform = row.get("transform")
        if transform == "difference":
            value -= reference
        else:
            if reference == 0:
                raise ValueError("nonzero formula reference required")
            ratio = value / reference
            if transform == "log_ratio":
                if ratio <= 0:
                    raise ValueError("positive logarithm argument required")
                value = math.log(ratio)
            elif transform == "ratio_minus_one":
                value = ratio - 1
            elif transform == "ratio_squared_minus_one":
                value = ratio * ratio - 1
            elif transform == "ratio_squared":
                value = ratio * ratio
            else:
                raise ValueError("unknown formula transform")
        variables[name] = value
    contributions = []
    for term in terms:
        value = _number(term.get("coefficient"), "formula coefficient")
        powers = term.get("powers")
        if not isinstance(powers, dict):
            raise ValueError("formula monomial powers required")
        for name, power in powers.items():
            if name not in variables or type(power) is not int or not 0 <= power <= 16:
                raise ValueError("unknown variable or invalid polynomial power")
            value *= variables[name] ** power
        contributions.append(value)
    return _number(math.fsum(contributions), "prediction")


def predict(parameters, observables, *, parametrizations=None):
    """Evaluate the supplied population; never infer a missing physics input."""
    rows = globals()["parametrizations"]() if parametrizations is None else parametrizations
    answer = {}
    for name in observables:
        if name not in rows:
            raise ValueError("missing cited parametrization for " + name)
        answer[name] = _evaluate(rows[name], parameters)
    return answer


def oblique_shifts(parameters, observables, stu, *, parametrizations=None):
    """First-order oblique shifts at the declared, fixed SM reference point.

    alpha_mZ and the on-shell mixing angle are explicit inputs. Width shifts
    use the neutral-current rho correction and effective-angle derivative;
    ratios are linearized, without retaining products of the shifts.
    """
    if len(stu) != 3:
        raise ValueError("three oblique coordinates required")
    S, T, U = [_number(x, "oblique coordinate") for x in stu]
    alpha = _number(parameters.get("alpha_mZ"), "alpha_mZ")
    sw = _number(parameters.get("s2w_on_shell"), "s2w_on_shell")
    if not 0 < alpha < 1 or not 0 < sw < .5:
        raise ValueError("physical oblique EW scheme inputs required")
    cw = 1 - sw
    angle_shift = alpha / (cw - sw) * (S / 4 - sw * cw * T)
    rows = globals()["parametrizations"]() if parametrizations is None else parametrizations
    names = list(observables)
    base = predict(parameters, names, parametrizations=rows)
    answer = {}
    fermions = {"Gamma_e": (-.5, -1.), "Gamma_mu": (-.5, -1.),
                "Gamma_tau": (-.5, -1.), "Gamma_u": (.5, 2/3),
                "Gamma_c": (.5, 2/3), "Gamma_d": (-.5, -1/3),
                "Gamma_s": (-.5, -1/3), "Gamma_b": (-.5, -1/3)}

    def width(name):
        value = predict(parameters, [name], parametrizations=rows)[name]
        if name == "Gamma_nu":
            return value * alpha * T
        angle = predict(parameters, ["sin2theta_eff"], parametrizations=rows)["sin2theta_eff"]
        t3, charge = fermions[name]
        gv = t3 - 2 * charge * angle
        return value * (alpha * T - 4 * charge * gv / (gv * gv + t3 * t3) * angle_shift)

    def hadronic():
        quarks = ["Gamma_" + q for q in ("u", "c", "d", "s", "b")]
        values = predict(parameters, quarks, parametrizations=rows)
        return sum(values.values()), sum(width(k) for k in quarks)

    for name in names:
        if name == "m_W":
            answer[name] = alpha * base[name] / (2 * (cw - sw)) * (
                -S / 2 + cw * T + (cw - sw) / (4 * sw) * U)
        elif name == "sin2theta_eff":
            answer[name] = angle_shift
        elif name == "Gamma_nu" or name in fermions:
            answer[name] = width(name)
        elif name in ("Gamma_Z", "R_l", "R_b", "R_c"):
            gh, dgh = hadronic()
            if name == "Gamma_Z":
                answer[name] = dgh + sum(width("Gamma_" + f) for f in ("e", "mu", "tau")) + 3 * width("Gamma_nu")
            elif name == "R_l":
                leptons = ["Gamma_" + f for f in ("e", "mu", "tau")]
                gl = sum(predict(parameters, leptons, parametrizations=rows).values()) / 3
                dgl = sum(width(k) for k in leptons) / 3
                answer[name] = base[name] * (dgh / gh - dgl / gl)
            else:
                f = "Gamma_" + name[-1]
                gf = predict(parameters, [f], parametrizations=rows)[f]
                answer[name] = base[name] * (width(f) / gf - dgh / gh)
        else:
            raise ValueError("no declared linear oblique shift for " + name)
    return answer


def _measurement(row, name, unit=None):
    if not isinstance(row, dict):
        raise ValueError("measurement object required for " + name)
    value = _number(row.get("value"), name)
    error = _number(row.get("uncertainty"), name + " uncertainty")
    if error <= 0:
        raise ValueError("positive measurement uncertainty required")
    if "unit" in row:
        expected = unit or ("1" if name in ("alpha_s", "delta_alpha_had", "sin2theta_eff", "R_l", "R_b", "R_c") else "GeV")
        if row["unit"] != expected:
            raise ValueError("measurement unit differs for " + name)
    return value, error


def _covariance(spec, names, errors):
    declaration = spec.get("covariance")
    if declaration is None:
        c = np.diag(np.square(errors))
        policy = "supplied marginal errors, declared independent by absence of covariance"
    else:
        if not isinstance(declaration, dict):
            raise ValueError("covariance object required")
        order = declaration.get("order")
        if not isinstance(order, list) or len(set(order)) != len(order) or set(order) != set(names):
            raise ValueError("covariance must cover the exact measurement population")
        try:
            c = np.asarray(declaration.get("matrix"), dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError("numeric covariance matrix required") from exc
        if c.shape != (len(order), len(order)):
            raise ValueError("covariance dimensions differ")
        indices = [order.index(n) for n in names]
        c = c[np.ix_(indices, indices)]
        # The matrix and the marginal errors state the same quantity twice.
        if not np.allclose(np.diag(c), np.square(errors), rtol=2e-6, atol=0):
            raise ValueError("covariance diagonal differs from the supplied uncertainties")
        policy = "supplied full measurement covariance"
    if "theory_covariance" in spec:
        t = spec["theory_covariance"]
        if not isinstance(t, dict):
            raise ValueError("theory covariance object required")
        order = t.get("order")
        if not isinstance(order, list) or len(set(order)) != len(order) or set(order) != set(names):
            raise ValueError("theory covariance population differs")
        try:
            matrix = np.asarray(t.get("matrix"), dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError("numeric theory covariance matrix required") from exc
        if matrix.shape != c.shape or not np.all(np.isfinite(matrix)) or not np.allclose(matrix, matrix.T, rtol=1e-12, atol=0):
            raise ValueError("finite symmetric theory covariance required")
        diagonal = np.diag(matrix)
        if np.any(diagonal < 0) or np.any(matrix[diagonal == 0] != 0):
            raise ValueError("PSD theory covariance required")
        positive = np.flatnonzero(diagonal > 0)
        if len(positive):
            correlation = matrix[np.ix_(positive, positive)] / np.sqrt(np.outer(diagonal[positive], diagonal[positive]))
            if min(np.linalg.eigvalsh(correlation)) < -1e-12:
                raise ValueError("PSD theory covariance required")
        indices = [order.index(n) for n in names]
        c += matrix[np.ix_(indices, indices)]
        policy += "; supplied independent additive theory covariance"
    if not np.all(np.isfinite(c)) or not np.allclose(c, c.T, rtol=1e-12, atol=0):
        raise ValueError("finite symmetric covariance required")
    try:
        np.linalg.cholesky(c)
    except np.linalg.LinAlgError as exc:
        raise ValueError("positive definite covariance required") from exc
    return c, policy


class _Problem:
    def __init__(self, original):
        self.spec = s = deepcopy(original)
        if not isinstance(s, dict) or s.get("schema_version") != 1:
            raise ValueError("version-one fit specification required")
        self.mode = s.get("mode")
        if self.mode not in ("sm", "indirect", "oblique", "smeft"):
            raise ValueError("unknown EW fit mode")
        if self.mode == "smeft" and "linear_response" not in s:
            raise ValueError("supplied source-bound SMEFT linear response required")
        self.point = {k: _number(v, k) for k, v in s.get("parameter_point", {}).items()}
        if any(k not in self.point for k in PARAMETERS):
            raise ValueError("complete SM parameter point required")
        conventions = s.get("conventions", {})
        if conventions.get("mass_definition") != "on_shell_running_width":
            raise ValueError("on-shell running-width mass definition required")
        if conventions.get("top_mass") != "pole" or conventions.get("weak_angle") != "effective_leptonic":
            raise ValueError("pole top mass and effective leptonic angle conventions required")
        self.rows = s.get("parametrizations", parametrizations())
        self.inputs = s.get("inputs", {})
        if not isinstance(self.inputs, dict):
            raise ValueError("inputs object required")
        self.max_nfev = s.get("max_nfev", 2000)
        if type(self.max_nfev) is not int or self.max_nfev <= 0:
            raise ValueError("max_nfev must be a positive integer")
        self.priors = self.inputs.get("parameters", {})
        self.observations = deepcopy(self.inputs.get("observables", {}))
        if not isinstance(self.priors, dict) or not set(self.priors) <= set(PARAMETERS):
            raise ValueError("unknown SM parameter measurement")
        if not isinstance(self.observations, dict) or set(self.observations) & set(PARAMETERS):
            raise ValueError("distinct observable measurement names required")
        if "m_W" in self.observations:
            raise ValueError("m_W must use one explicitly selected variant")
        mass = self.inputs.get("m_W")
        self.variant = None
        if mass is not None:
            if not isinstance(mass, dict) or not isinstance(mass.get("variant"), str) or not mass["variant"].strip():
                raise ValueError("exactly one selected mass variant required")
            self.variant = mass["variant"]
            self.observations["m_W"] = mass
        self.names = list(self.priors) + list(self.observations)
        rows = [self.priors.get(k, self.observations.get(k)) for k in self.names]
        if self.mode == "smeft":
            self.response = s["linear_response"]
            _sources(self.response)
            if self.response.get("reference_point") != self.point:
                raise ValueError("SMEFT response reference point mismatch")
            if self.response.get("eft") != "SMEFT" or self.response.get("basis") != "Warsaw" or self.response.get("unit") != "GeV^-2":
                raise ValueError("explicit SMEFT Warsaw and inverse-square-GeV response required")
            if _number(self.response.get("scale"), "SMEFT scale") <= 0:
                raise ValueError("positive SMEFT scale required")
            self.free = self.response.get("coefficients")
            if not isinstance(self.free, list) or not self.free or len(set(self.free)) != len(self.free):
                raise ValueError("distinct response coefficients required")
            self.coefficient_ranges = _domain(self.response)
            if set(self.coefficient_ranges) != set(self.free):
                raise ValueError("coefficient response validity population differs")
            extra = s.get("coefficient_priors", {})
            if not isinstance(extra, dict) or not set(extra) <= set(self.free) or set(extra) & set(self.names):
                raise ValueError("coefficient prior population differs")
            self.names += list(extra)
            rows += list(extra.values())
        self.units = {k: ("1" if k in ("alpha_s", "delta_alpha_had") else "GeV") for k in self.priors}
        for k in self.observations:
            standard = "1" if k in ("sin2theta_eff", "R_l", "R_b", "R_c") else ("pb" if k == "sigma0had_pb" else "GeV")
            self.units[k] = self.rows.get(k, {}).get("unit", standard)
            if k in ("m_W", "sin2theta_eff") and self.units[k] != standard:
                raise ValueError("prediction unit differs for " + k)
        if self.mode == "smeft":
            self.units.update({k: self.response["unit"] for k in self.free})
        values_errors = [_measurement(row, name, self.units[name]) for name, row in zip(self.names, rows)]
        if not values_errors:
            raise ValueError("nonempty supplied measurement population required")
        self.y = np.array([v for v, _ in values_errors])
        self.c, self.covariance_policy = _covariance(s, self.names, [e for _, e in values_errors])
        self.drop = s.get("drop") if self.mode == "indirect" else None
        if self.mode == "indirect" and self.drop not in self.names:
            raise ValueError("indirect mode must drop one measured input")
        self.kept = [i for i, n in enumerate(self.names) if n != self.drop]
        self.L = np.linalg.cholesky(self.c[np.ix_(self.kept, self.kept)])
        self.observable_names = list(self.observations)
        self.reference = None
        if self.mode == "oblique":
            self.reference = s.get("reference_point")
            if not isinstance(self.reference, dict) or not {"m_H", "m_t"} <= self.reference.keys():
                raise ValueError("explicit oblique reference point required")
            if self.inputs.get("reference_point") != self.reference or any(self.point.get(k) != v for k, v in self.reference.items()):
                raise ValueError("oblique reference point mismatch")
            if conventions.get("ew_scheme") != "alpha_mZ":
                raise ValueError("oblique alpha_mZ EW scheme required")
            if type(s.get("free_u", True)) is not bool:
                raise ValueError("free_u must be boolean")
            self.free = ["S", "T", "U"] if s.get("free_u", True) else ["S", "T"]
        elif self.mode != "smeft":
            self.free = s.get("free_parameters", list(PARAMETERS))
            if not isinstance(self.free, list) or len(set(self.free)) != len(self.free) or not set(self.free) <= set(PARAMETERS):
                raise ValueError("distinct known free SM parameters required")
        self.x0 = np.array([self.point[k] for k in self.free]) if self.mode in ("sm", "indirect") else np.zeros(len(self.free))
        self.bounds = self._bounds()
        self.prediction(self.x0)

    def _bounds(self):
        limits = {k: [-np.inf, np.inf] for k in self.free}
        if self.mode in ("sm", "indirect", "oblique"):
            for name in self.observable_names:
                if name not in self.rows:
                    raise ValueError("missing cited parametrization for " + name)
                for k, (lo, hi) in _domain(self.rows[name]).items():
                    if k in limits:
                        limits[k] = [max(limits[k][0], lo), min(limits[k][1], hi)]
        if self.mode == "smeft":
            limits = deepcopy(self.coefficient_ranges)
        for k, endpoints in self.spec.get("bounds", {}).items():
            if k not in limits or not isinstance(endpoints, list) or len(endpoints) != 2:
                raise ValueError("bounds must name free coordinates")
            lo, hi = [_number(v, "bound") for v in endpoints]
            limits[k] = [max(limits[k][0], lo), min(limits[k][1], hi)]
        for k, (lo, hi) in limits.items():
            if lo >= hi:
                raise ValueError("empty intersected validity domain for " + k)
        return np.array([limits[k][0] for k in self.free]), np.array([limits[k][1] for k in self.free])

    def prediction(self, x):
        point = dict(self.point)
        if self.mode in ("sm", "indirect"):
            point.update(zip(self.free, x))
        result = {k: point[k] for k in self.priors}
        if self.mode == "smeft":
            r = self.response
            for name in self.observable_names:
                if name not in r.get("baseline", {}) or name not in r.get("jacobian", {}) or set(r["jacobian"][name]) != set(self.free):
                    raise ValueError("complete response observable population required")
                result[name] = _number(r["baseline"][name], "response baseline") + sum(
                    _number(r["jacobian"][name][k], "response derivative") * v for k, v in zip(self.free, x))
            result.update(dict(zip(self.free, x)))
        else:
            result.update(predict(point, self.observable_names, parametrizations=self.rows))
        if self.mode == "oblique":
            shifts = oblique_shifts(point, self.observable_names, list(x) + ([0.] if len(x) == 2 else []), parametrizations=self.rows)
            for name in self.observable_names:
                result[name] += shifts[name]
        return np.array([_number(result[n], n + " prediction") for n in self.names])

    def residual(self, x):
        return solve_triangular(self.L, (self.y - self.prediction(x))[self.kept], lower=True)

    def solve(self, fixed=None):
        fixed = fixed or {}
        indices = [i for i, name in enumerate(self.free) if name not in fixed]
        x = self.x0.copy()
        for name, value in fixed.items():
            if name not in self.free:
                raise ValueError("profile coordinate must be free")
            i = self.free.index(name)
            x[i] = _number(value, "profile coordinate")
        if any(x < self.bounds[0]) or any(x > self.bounds[1]):
            raise ValueError("initial or profile coordinate outside validity bounds")
        if not indices:
            residual = self.residual(x)
            return x, float(residual @ residual), np.empty((len(residual), 0))
        if self.mode in ("oblique", "smeft") and not fixed:
            baseline = self.residual(np.zeros(len(x)))
            # Use exact response columns, avoiding subtraction of large SM values.
            columns = []
            for i in range(len(x)):
                if self.mode == "oblique":
                    unit = np.zeros(3); unit[i] = 1.
                    derivative = oblique_shifts(self.point, self.observable_names, unit, parametrizations=self.rows)
                else:
                    derivative = {n: _number(self.response["jacobian"][n][self.free[i]], "response derivative") for n in self.observable_names}
                    derivative[self.free[i]] = 1.
                values = np.array([derivative.get(n, 0.) for n in self.names])
                columns.append(solve_triangular(self.L, values[self.kept], lower=True))
            design = np.column_stack(columns)
            scales = np.linalg.norm(design, axis=0)
            if np.any(scales == 0):
                raise ValueError("fit directions are not identifiable")
            x, _, rank, _ = np.linalg.lstsq(design / scales, baseline, rcond=None)
            x /= scales
            if rank != len(x):
                raise ValueError("fit directions are not identifiable")
            if any(x < self.bounds[0]) or any(x > self.bounds[1]):
                raise ValueError("linear fit outside declared validity bounds")
            residual = self.residual(x)
            return x, float(residual @ residual), design

        def unpack(part):
            answer = x.copy(); answer[indices] = part
            return answer

        fitted = least_squares(lambda part: self.residual(unpack(part)), x[indices],
                               bounds=(self.bounds[0][indices], self.bounds[1][indices]),
                               x_scale="jac", xtol=1e-12, ftol=1e-12, gtol=1e-12,
                               max_nfev=self.max_nfev)
        if not fitted.success:
            raise ValueError("numerical fit did not converge: " + fitted.message)
        return unpack(fitted.x), float(fitted.fun @ fitted.fun), fitted.jac

    def profile(self, name, value):
        if name in self.free:
            return self.solve({name: value})[1]
        if name not in self.observations or self.mode not in ("sm", "indirect"):
            raise ValueError("profile target must be a free parameter or a predicted observable")
        center, _, jacobian = self.solve()
        scales = np.sqrt(np.diag(_parameter_covariance(jacobian)))
        if not len(scales):
            raise ValueError("observable profile requires free coordinates")
        index = self.names.index(name)
        unit = math.sqrt(self.c[index, index])
        target = _number(value, "profile target")
        def unpack(z):
            return center + scales * z
        def objective(z):
            residual = self.residual(unpack(z))
            return float(residual @ residual)
        constraint = lambda z: (self.prediction(unpack(z))[index] - target) / unit
        fitted = minimize(objective, np.zeros(len(center)), method="SLSQP",
                          bounds=list(zip((self.bounds[0]-center)/scales, (self.bounds[1]-center)/scales)),
                          constraints=[{"type": "eq", "fun": constraint}],
                          options={"ftol": 1e-11, "maxiter": 1000})
        if not fitted.success or abs(constraint(fitted.x)) > 1e-7:
            raise ValueError("observable profile failed within declared validity: " + fitted.message)
        return float(fitted.fun)


def _parameter_covariance(jacobian):
    n = jacobian.shape[1]
    if not n:
        return np.zeros((0, 0))
    scales = np.linalg.norm(jacobian, axis=0)
    if np.any(scales == 0):
        raise ValueError("fit directions are not identifiable")
    normalized = jacobian / scales
    _, singular, vt = np.linalg.svd(normalized, full_matrices=False)
    if len(singular) != n or singular[-1] <= np.finfo(float).eps * max(normalized.shape) * singular[0]:
        raise ValueError("fit directions are not identifiable")
    c = (vt.T / singular**2) @ vt / np.outer(scales, scales)
    return (c + c.T) / 2


def profile_chi2(spec, parameter, value):
    """Refit all other coordinates after removing the indirect measurement."""
    return _Problem(spec).profile(parameter, value)


def _interval(problem, x, chi2, covariance, parameter):
    delta = _number(problem.spec.get("delta_chi2", 1.), "interval delta chi-square")
    if delta <= 0:
        raise ValueError("positive interval delta chi-square required")
    if parameter in problem.free:
        i = problem.free.index(parameter)
        center = x[i]
        variance = covariance[i, i]
        bounds = (problem.bounds[0][i], problem.bounds[1][i])
    else:
        i = problem.names.index(parameter)
        center = problem.prediction(x)[i]
        gradient = []
        for j in range(len(x)):
            h = np.cbrt(np.finfo(float).eps) * max(1., abs(x[j]))
            plus, minus = x.copy(), x.copy()
            plus[j] = min(x[j] + h, problem.bounds[1][j])
            minus[j] = max(x[j] - h, problem.bounds[0][j])
            gradient.append((problem.prediction(plus)[i] - problem.prediction(minus)[i]) / (plus[j] - minus[j]))
        gradient = np.array(gradient)
        variance = float(gradient @ covariance @ gradient)
        bounds = (-np.inf, np.inf)
    sigma = math.sqrt(variance * delta)
    if sigma <= 0:
        raise ValueError("profile target has no identifiable uncertainty direction")
    endpoints, status = [], []
    for sign, bound in [(-1, bounds[0]), (1, bounds[1])]:
        distance = sigma
        target = lambda value: problem.profile(parameter, value) - chi2 - delta
        for _ in range(60):
            candidate = max(bound, center - distance) if sign < 0 else min(bound, center + distance)
            if candidate == center:
                endpoints.append(center); status.append("validity_boundary"); break
            if target(candidate) >= 0:
                lo, hi = sorted((center, candidate))
                endpoints.append(float(brentq(target, lo, hi, xtol=1e-11)))
                status.append("profile_root"); break
            if candidate == bound:
                endpoints.append(float(bound)); status.append("validity_boundary"); break
            distance *= 2
        else:
            raise ValueError("profile interval could not be bracketed")
    return {"interval": endpoints, "endpoint_status": status, "delta_chi2": delta,
            "method": "profile_delta_chi2"}


def fit(spec: dict) -> dict:
    """Fit one supplied population with exactly one selected mass variant.

    inputs.parameters holds Gaussian SM constraints. inputs.observables holds
    value/uncertainty rows; m_W lives only at inputs.m_W, with a variant label.
    covariance.order names the complete population, including a dropped input.
    indirect.drop removes its row and column before fitting and profiling.
    Coefficient responses are supplied data, never evidence of tool execution.
    """
    problem = _Problem(spec)
    x, chi2, jacobian = problem.solve()
    covariance = _parameter_covariance(jacobian)
    predictions = problem.prediction(x)
    params = dict(problem.point)
    if problem.mode in ("sm", "indirect"):
        params.update(zip(problem.free, map(float, x)))
    kept_names = [problem.names[i] for i in problem.kept]
    result = {"schema_version": 1, "mode": problem.mode, "variant": problem.variant,
              "chi2_min": chi2, "parameters": params,
              "predictions": dict(zip(problem.names, map(float, predictions))),
              "pulls": {problem.names[i]: float((problem.y[i] - predictions[i]) / math.sqrt(problem.c[i, i])) for i in problem.kept},
              "whitened_residuals": dict(zip(kept_names, map(float, problem.residual(x)))),
              "pull_definition": "measurement minus prediction divided by marginal total standard deviation",
              "free_parameters": problem.free, "parameter_covariance": covariance.tolist(),
              "measurement_count": len(problem.kept), "degrees_of_freedom": len(problem.kept) - len(x),
              "covariance_policy": problem.covariance_policy,
              "numerical_status": "converged", "physics_validated": False,
              "covariance_method": "local linear Gaussian information",
              "inputs_sha256": _digest({"spec": spec, "effective_parametrizations": problem.rows}), "spec_sha256": _digest(spec),
              "parametrizations_sha256": _digest(problem.rows),
              "conventions": deepcopy(spec["conventions"])}
    result["prediction_units"] = {k: problem.units[k] for k in problem.names}
    result["theory_uncertainty"] = "supplied covariance" if "theory_covariance" in spec else "not supplied"
    result["active_bounds"] = [name for i, name in enumerate(problem.free)
                               if any(math.isfinite(bound) and abs(x[i]-bound) <= 1e-8*max(1., abs(x[i]))
                                      for bound in (problem.bounds[0][i], problem.bounds[1][i]))]
    if problem.mode == "oblique":
        result["oblique"] = list(map(float, x)) + ([0.] if len(x) == 2 else [])
        full = np.zeros((3, 3)); full[:len(x), :len(x)] = covariance
        result["oblique_covariance"] = full.tolist()
        result["reference_point"] = deepcopy(problem.reference)
        result["fit_scope"] = "conditional on fixed SM nuisance parameters at the declared reference point"
    if problem.mode == "smeft":
        result["wilson_coefficients"] = dict(zip(problem.free, map(float, x)))
        result["response_sha256"] = _digest(problem.response)
        result["response_scope"] = "supplied linear truncation at zero coefficients; upstream execution qualification separate"
        result["eft"] = problem.response["eft"]
        result["basis"] = problem.response["basis"]
        result["scale"] = problem.response["scale"]
        result["coefficient_unit"] = problem.response["unit"]
    if problem.mode == "indirect":
        dropped = problem.drop
        row = {"name": dropped, "value": float(predictions[problem.names.index(dropped)]),
               "dropped_measurement": deepcopy(problem.priors.get(dropped, problem.observations.get(dropped)))}
        row.update(_interval(problem, x, chi2, covariance, dropped))
        result["indirect"] = row
    return result


def fit_variants(spec, variants):
    """Evaluate independent variants, retaining a complete record for each."""
    if not isinstance(variants, list) or not variants:
        raise ValueError("nonempty separate variant population required")
    if not isinstance(spec, dict) or not isinstance(spec.get("inputs"), dict):
        raise ValueError("fit specification with an inputs object required")
    labels = [row.get("variant") if isinstance(row, dict) else None for row in variants]
    if any(not isinstance(label, str) or not label.strip() for label in labels) or len(set(labels)) != len(labels):
        raise ValueError("distinct variant labels required")
    results = []
    for row in variants:
        separate = deepcopy(spec)
        separate["inputs"]["m_W"] = deepcopy(row)
        results.append(fit(separate))
    return results


def oblique_likelihood(spec) -> dict:
    """Consumer contract: three-coordinate mean, PSD covariance and reference."""
    if not isinstance(spec, dict) or spec.get("mode") != "oblique":
        raise ValueError("oblique likelihood requires an explicit oblique specification")
    result = fit(spec)
    return {"mean": result["oblique"], "covariance": result["oblique_covariance"],
            "reference_point": result["reference_point"], "inputs_sha256": result["inputs_sha256"],
            "spec_sha256": result["spec_sha256"], "chi2_min": result["chi2_min"],
            "variant": result["variant"], "physics_validated": False}


def flavio_predictions(parameters, observables, coefficient_document, wilson_options, *, wilson_api, flavio_api):
    """In-process seam for an already admitted EFT worker; APIs are injected.

    Use upstream observable names and full supplied upstream parameter maps.
    Never infer the absent effective-angle polynomial from a constant input.
    """
    from ravel.physics.eft_toolchain_core import new_wilson
    coefficients = new_wilson(wilson_api, coefficient_document, wilson_options)
    return {name: _number(flavio_api.Observable[name].prediction_par(parameters, coefficients), name)
            for name in observables}


def flavio_linear_response(reference_point, parameters, observables, coefficients, steps,
                           validity, sources, *, scale, wilson_options, wilson_api,
                           flavio_api, derivative_tolerance=1e-6):
    """Extract the derivative at zero through the existing injected native seam.

    observables maps caller fit names to upstream names. All probe steps and
    coefficient domains are supplied. Full and half-step central differences
    must agree; even-power terms are recorded, then intentionally discarded
    by the declared dimension-six linear truncation. This does not certify a
    physical domain, source custody or an upstream likelihood calculation.
    """
    if not isinstance(observables, dict) or not observables or len(set(observables.values())) != len(observables):
        raise ValueError("distinct upstream observable mapping required")
    mapping = {"m_H": "m_h", "m_t": "m_t", "m_Z": "m_Z", "alpha_s": "alpha_s",
               "delta_alpha_had": "Delta_alpha_e_had", "delta_alpha_lep": "Delta_alpha_e_lep"}
    for native, upstream in mapping.items():
        if native not in reference_point or upstream not in parameters or _number(reference_point[native], native) != _number(parameters[upstream], upstream):
            raise ValueError("upstream response parameter reference mismatch: " + native)
    if not isinstance(coefficients, list) or not coefficients or len(set(coefficients)) != len(coefficients) or set(steps) != set(coefficients):
        raise ValueError("distinct coefficients and complete probe steps required")
    tolerance = _number(derivative_tolerance, "derivative tolerance")
    if tolerance <= 0 or _number(scale, "response scale") <= 0:
        raise ValueError("positive scale and tolerance required")
    answer = {"eft": "SMEFT", "basis": "Warsaw", "scale": scale, "unit": "GeV^-2",
              "reference_point": deepcopy(reference_point), "coefficients": deepcopy(coefficients),
              "sources": deepcopy(sources), "validity": deepcopy(validity),
              "truncation": "linear_at_zero_coefficients", "parameters_sha256": _digest(parameters),
              "wilson_options_sha256": _digest(wilson_options), "observable_mapping": deepcopy(observables),
              "physics_validated": False, "upstream_execution_receipt": "caller must bind admitted EFT worker evidence"}
    ranges = _domain(answer)
    if set(ranges) != set(coefficients):
        raise ValueError("coefficient validity population differs")
    native_names = list(observables.values())
    def evaluate(values):
        return flavio_predictions(parameters, native_names, {"eft": "SMEFT", "basis": "Warsaw", "scale": scale, "values": values},
                                  wilson_options, wilson_api=wilson_api, flavio_api=flavio_api)
    base = evaluate({})
    answer["baseline"] = {k: base[v] for k, v in observables.items()}
    answer["jacobian"] = {k: {} for k in observables}
    probes = {}
    for coefficient in coefficients:
        h = _number(steps[coefficient], "probe step")
        if h <= 0 or not ranges[coefficient][0] <= -h < 0 < h <= ranges[coefficient][1]:
            raise ValueError("symmetric probe outside declared coefficient validity")
        plus, minus = evaluate({coefficient: h}), evaluate({coefficient: -h})
        half_plus, half_minus = evaluate({coefficient: h / 2}), evaluate({coefficient: -h / 2})
        for name, native in observables.items():
            full = (plus[native] - minus[native]) / (2*h)
            half = (half_plus[native] - half_minus[native]) / h
            if not math.isclose(full, half, rel_tol=tolerance, abs_tol=tolerance):
                raise ValueError("unstable linear response derivative")
            answer["jacobian"][name][coefficient] = _number(half, "linear derivative")
        probes[coefficient] = {"step": h, "plus": plus, "minus": minus,
                               "half_plus": half_plus, "half_minus": half_minus}
    answer["probes"] = probes
    return answer


def ewpt_cross_check(config, point, cache, *, wilson_api, flavio_api, smelli_api, journal, output):
    """Reuse the complete upstream likelihood and covariance-custody contract.

    This call performs no process launch. The ordinary EFT adapter remains the
    launch path; its method decision and admission must precede scientific work.
    """
    from ravel.physics import eft_toolchain_core
    selected = config.get("smelli")
    if not isinstance(selected, dict) or selected.get("include_likelihoods") != ["likelihood_ewpt.yaml"]:
        raise ValueError("exactly the declared EW likelihood required")
    return eft_toolchain_core.evaluate(config, point, cache, wilson_api, flavio_api, smelli_api, np, journal, output)


def ew_input_schema_status():
    return "awaits_producer_schema"


def external_fit_interface_status():
    return "awaits_admitted_adapter"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fit", "oblique-likelihood"))
    parser.add_argument("spec", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    from ravel.workflow.state_io import read_json
    spec = read_json(args.spec)
    result = fit(spec) if args.command == "fit" else oblique_likelihood(spec)
    from ravel.physics.supplied_contracts import publish
    publish(args.output.parent, result, {"filename": args.output.name, "format": "json"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
