"""Independent, bounded witnesses for a massless QED tree control.

This module evaluates the analytic oracle and measured numerical postconditions.
It neither imports a UFO nor executes a generator. Passing these checks covers
the named process and phase-space points, not a general physical model.
"""
import math
import re


CHECK_NAMES = ("effective_parameters", "amplitude_reference", "lorentz",
               "ward_massless", "gauge_pair", "partial_width", "resonance",
               "spin_correlations", "permutation")
MANDATORY_CHECKS = ("effective_parameters", "amplitude_reference", "lorentz")
LEG_PDGS = (-11, 11, -13, 13)


def number(value, name, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    return float(value)


def dot(left, right):
    return left[0] * right[0] - math.fsum(a * b for a, b in zip(left[1:], right[1:]))


def subtract(left, right):
    return [a - b for a, b in zip(left, right)]


def invariants(momenta):
    total = [a + b for a, b in zip(momenta[0], momenta[1])]
    return (dot(total, total), dot(subtract(momenta[0], momenta[2]),
                                   subtract(momenta[0], momenta[2])),
            dot(subtract(momenta[0], momenta[3]), subtract(momenta[0], momenta[3])))


def normalized(momenta):
    """A common positive energy scale cancels from dimensionless observables."""
    scale = max(p[0] for p in momenta)
    return [[component / scale for component in momentum] for momentum in momenta]


def validate_points(payload):
    keys = {"schema_version", "energy_unit", "component_order", "leg_pdgs", "points"}
    if not isinstance(payload, dict) or set(payload) != keys:
        raise ValueError("phase-space file requires exact schema, units, order, legs and points")
    if (type(payload["schema_version"]) is not int or payload["schema_version"] != 1
            or payload["energy_unit"] != "GeV"
            or payload["component_order"] != ["E", "px", "py", "pz"]
            or payload["leg_pdgs"] != list(LEG_PDGS)):
        raise ValueError("massless QED control requires GeV E,px,py,pz and explicit e+,e-,mu+,mu- legs")
    points = payload["points"]
    if not isinstance(points, list) or not 2 <= len(points) <= 32:
        raise ValueError("supply 2..32 frozen phase-space points")
    ids, shapes = set(), set()
    for point in points:
        if not isinstance(point, dict) or set(point) != {"id", "momenta"}:
            raise ValueError("each point requires exactly id and momenta")
        identity = point["id"]
        if (not isinstance(identity, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", identity)
                or identity in ids or "__" in identity):
            raise ValueError("phase-space ids must be unique simple names without double underscores")
        ids.add(identity)
        momenta = point["momenta"]
        if not isinstance(momenta, list) or len(momenta) != 4:
            raise ValueError("the exclusive control has exactly four external legs")
        for momentum in momenta:
            if not isinstance(momentum, list) or len(momentum) != 4:
                raise ValueError("each momentum requires E,px,py,pz")
            for component in momentum:
                number(component, "momentum component")
            energy = number(momentum[0], "external energy", positive=True)
            unit = [component / energy for component in momentum]
            if (any(not math.isfinite(component) or abs(component) > 1 + 1e-11 for component in unit)
                    or abs(dot(unit, unit)) > 1e-11):
                raise ValueError("the analytic control requires every external leg to be massless")
        scaled = normalized(momenta)
        incoming = [a + b for a, b in zip(*scaled[:2])]
        outgoing = [a + b for a, b in zip(*scaled[2:])]
        if any(abs(a - b) > 1e-11 * incoming[0] for a, b in zip(incoming, outgoing)):
            raise ValueError("phase-space point violates four-momentum conservation")
        s, t, u = invariants(scaled)
        if s <= 0 or abs(s + t + u) > 1e-10 * s:
            raise ValueError("invalid massless scattering invariants")
        shapes.add(round(t / s, 12))
    if len(shapes) < 2:
        raise ValueError("independent reference coverage needs at least two scattering angles")
    return points


def qed_m2(momenta, alpha_inverse):
    """Spin-averaged, color-singlet |M|^2, without flux or phase space.

    For distinct massless charged fermions and photon exchange only,
    |M|^2 = 2 e^4 (t^2 + u^2)/s^2 with e^2 = 4 pi / alpha_inverse.
    """
    alpha_inverse = number(alpha_inverse, "aEWM1", positive=True)
    s, t, u = invariants(normalized(momenta))
    coupling = 4.0 * math.pi / alpha_inverse
    return number(2.0 * coupling * coupling * ((t / s) ** 2 + (u / s) ** 2),
                  "representable analytic |M|^2", positive=True)


def boost_z(momenta, beta=0.3):
    gamma = 1.0 / math.sqrt(1.0 - beta ** 2)
    return [[gamma * (p[0] - beta * p[3]), p[1], p[2], gamma * (p[3] - beta * p[0])]
            for p in momenta]


def evaluations(points):
    return [item for point in points for item in
            ({"id": point["id"], "momenta": point["momenta"]},
             {"id": point["id"] + "__boost_z", "momenta": boost_z(point["momenta"])} )]


def validate_oracle(payload, points, expected_parameters):
    keys = {"schema_version", "kind", "source", "formula", "alpha_inverse", "atol", "rtol", "expected_m2"}
    if not isinstance(payload, dict) or set(payload) != keys:
        raise ValueError("oracle requires exact identity, formula, tolerances and frozen reference values")
    if (type(payload["schema_version"]) is not int or payload["schema_version"] != 1
            or payload["kind"] != "qed-massless-tree-spin-average"
            or payload["formula"] != "2*e^4*(t^2+u^2)/s^2; e^2=4*pi/alpha_inverse"):
        raise ValueError("unsupported independent oracle convention")
    if not isinstance(payload["source"], str) or not payload["source"].strip():
        raise ValueError("oracle source and derivation provenance are required")
    if number(payload["alpha_inverse"], "oracle inverse alpha", positive=True) != expected_parameters["aEWM1"]:
        raise ValueError("oracle coupling point differs from requested effective parameters")
    for key, ceiling in (("atol", 1e-10), ("rtol", 1e-6)):
        value = number(payload[key], key)
        if not 0 <= value <= ceiling:
            raise ValueError(f"{key} exceeds the bounded control tolerance ({ceiling})")
    refs = payload["expected_m2"]
    if not isinstance(refs, dict) or set(refs) != {p["id"] for p in points}:
        raise ValueError("oracle reference coverage differs from frozen phase-space ids")
    for point in points:
        supplied = number(refs[point["id"]], "reference |M|^2", positive=True)
        independent = qed_m2(point["momenta"], payload["alpha_inverse"])
        if not math.isclose(supplied, independent, abs_tol=0.0, rel_tol=1e-11):
            raise ValueError("frozen reference disagrees with the independent analytic convention")
    if payload["atol"] > payload["rtol"] * min(refs.values()):
        raise ValueError("absolute tolerance must not exceed relative tolerance times the smallest positive reference")
    return payload


def relative_delta(actual, reference):
    value = abs(actual - reference) / reference
    # Grossly inconsistent finite inputs can overflow this derived ratio.
    # Preserve a JSON-safe failed row instead of emitting an infinite metric.
    return value if math.isfinite(value) else None


def compare(points, oracle, expected_parameters, measured, required_checks):
    """Return all check applicability and complete numerical coverage."""
    expected_ids = {p["id"] for p in evaluations(points)}
    if set(measured) != {"parameters", "masses_gev", "m2"}:
        raise ValueError("measured witness requires parameters, external masses and matrix elements")
    if set(measured["m2"]) != expected_ids:
        raise ValueError("measured amplitude coverage differs from the exact planned evaluations")
    parameters = measured["parameters"]
    if set(parameters) != {"aEWM1", "ee"} or len(measured["masses_gev"]) != 4:
        raise ValueError("compiled effective parameter coverage is incomplete")
    for name, value in parameters.items():
        number(value, f"effective {name}", positive=True)
    for value in measured["masses_gev"]:
        number(value, "compiled external mass")
    for value in measured["m2"].values():
        number(value, "measured amplitude", positive=True)
    effective_ok = (math.isclose(parameters["aEWM1"], expected_parameters["aEWM1"], rel_tol=1e-12)
                    and all(value == 0.0 for value in measured["masses_gev"])
                    and math.isclose(parameters["ee"], math.sqrt(4 * math.pi / expected_parameters["aEWM1"]),
                                     abs_tol=0.0, rel_tol=1e-11))
    reference_rows, lorentz_rows = [], []
    for point in points:
        identity = point["id"]
        actual, reference = measured["m2"][identity], oracle["expected_m2"][identity]
        delta = relative_delta(actual, reference)
        reference_rows.append({"id": identity, "actual_m2": actual, "reference_m2": reference,
                               "absolute_delta": abs(actual - reference),
                               "relative_delta": delta,
                               "passed": delta is not None and delta <= oracle["rtol"]})
        boosted = measured["m2"][identity + "__boost_z"]
        delta = relative_delta(boosted, actual)
        lorentz_rows.append({"id": identity, "original_m2": actual, "boosted_m2": boosted,
                             "absolute_delta": abs(actual - boosted),
                             "relative_delta": delta,
                             "passed": delta is not None and delta <= oracle["rtol"]})
    checks = [
        {"name": "effective_parameters", "status": "passed" if effective_ok else "failed",
         "measured": parameters, "external_masses_gev": measured["masses_gev"]},
        {"name": "amplitude_reference", "status": "passed" if all(r["passed"] for r in reference_rows) else "failed",
         "independence": "analytic spin trace and explicit Mandelstam invariants, independent of UFO/ALOHA",
         "comparison": "relative residual to each positive reference; absolute tolerance cannot loosen it",
         "atol": oracle["atol"], "rtol": oracle["rtol"], "points": reference_rows},
        {"name": "lorentz", "status": "passed" if all(r["passed"] for r in lorentz_rows) else "failed",
         "independence": "same generated amplitude; metamorphic consistency only",
         "transformation": "common z boost, beta=0.3", "points": lorentz_rows},
        {"name": "ward_massless", "status": "not_applicable", "reason": "no external massless gauge vector in this process"},
        {"name": "gauge_pair", "status": "unsupported", "reason": "no Feynman/unitary amplitude comparison implemented"},
        {"name": "partial_width", "status": "not_applicable", "reason": "four stable external fermions; no decay process"},
        {"name": "resonance", "status": "not_applicable", "reason": "photon exchange only; no massive resonant approximation"},
        {"name": "spin_correlations", "status": "not_applicable", "reason": "spin average with stable legs; no shower or decay distribution"},
        {"name": "permutation", "status": "unsupported", "reason": "no independently regenerated leg permutation implemented"},
    ]
    by_name = {c["name"]: c for c in checks}
    complete = all(by_name[name]["status"] == "passed" for name in required_checks)
    return {"checks_passed": complete, "required_checks": list(required_checks), "checks": checks,
            "required_unresolved": [name for name in required_checks if by_name[name]["status"] != "passed"],
            "evaluated_points": len(points), "evaluated_matrix_elements": len(expected_ids),
            "physical_scope": "massless SM photon-only e+ e- > mu+ mu- at the named points and parameter card"}
