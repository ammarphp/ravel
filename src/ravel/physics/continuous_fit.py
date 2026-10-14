"""Source-bound extended exponential fits in disjoint signal/control ranges.

This deliberately closed family uses exact continuum bin integrals, one FULL
yield before a positive SR transfer, and fixed supplied signals in *every*
region. The transfer auxiliary is a measurement, z ~ Normal(theta, 1), not a
random prior on theta. Toys repeat that measurement at fixed nuisance truths.
No published workspace is transformed and no finite-MC likelihood is inferred.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from ravel.physics.quantities import _keys, _number, _text, _unique
from ravel.physics.statistical_model import _load_bytes, _regular

PARAMETERS = ("mu", "background_yield", "slope", "transfer_theta")
MAX_BINS, MAX_TRIALS, MAX_TRUTHS = 32, 256, 4


def validate(task):
    """Validate a task without reading files or starting a numerical fit."""
    _keys(task, ("input",), label="continuous fit task")
    _text(task["input"], "input")
    return deepcopy(task)


def _vector(value, size, label):
    if not isinstance(value, list) or len(value) != size:
        raise ValueError(f"{label} requires exactly {size} entries")
    return [_number(v, label) for v in value]


def _point(document, point):
    _keys(point, PARAMETERS, label="continuous parameter point")
    for name in PARAMETERS:
        x = _number(point[name], name)
        low, high = document["parameters"][name]["bounds"]
        if not low <= x <= high:
            raise ValueError(f"{name} exceeds declared parameter bounds")
    return point


def prepare(document):
    """Validate explicit model semantics; byte custody is checked by inputs()."""
    _keys(document, ("schema_version", "model_id", "question", "sources", "full_range",
                     "background", "transfer", "parameters", "regions", "partition",
                     "signal_statistics", "comparison_points", "profile_points",
                     "calibration", "assumptions"), label="continuous model")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("unsupported continuous model version")
    _text(document["model_id"], "model_id")
    _text(document["question"], "question")
    sources = document["sources"]
    if not isinstance(sources, list) or not sources:
        raise ValueError("continuous model requires source byte pins")
    for source in sources:
        _keys(source, ("id", "path", "sha256", "reference"), label="continuous source")
        for key in ("id", "path", "reference"):
            _text(source[key], key)
        digest = source["sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("source hash must be a lowercase SHA256")
    ids = [s["id"] for s in sources]
    _unique(ids, "source identities")
    def source(value):
        if value not in ids:
            raise ValueError("unknown source identity")

    low, high = _vector(document["full_range"], 2, "FULL range")
    if not low < high or not math.isfinite(high-low):
        raise ValueError("FULL range must have finite positive width")
    background = document["background"]
    _keys(background, ("family", "yield_definition", "source"), label="background")
    if background["family"] != "exponential" or background["yield_definition"] != "full_range_before_sr_transfer":
        raise ValueError("only exponential FULL yield before SR transfer is supported")
    source(background["source"])
    transfer = document["transfer"]
    _keys(transfer, ("nominal", "log_sigma", "observed_auxiliary", "sampling_law", "source", "meaning"), label="transfer")
    if _number(transfer["nominal"], "transfer nominal") <= 0 or not 0 < _number(transfer["log_sigma"], "transfer log sigma") <= 2:
        raise ValueError("transfer must be positive with explicit nonzero log sigma <= 2")
    _number(transfer["observed_auxiliary"], "transfer auxiliary")
    if transfer["sampling_law"] != "z_normal_theta_unit_variance":
        raise ValueError("transfer requires z ~ Normal(theta,1) auxiliary sampling")
    _text(transfer["meaning"], "transfer meaning")
    source(transfer["source"])
    parameters = document["parameters"]
    _keys(parameters, PARAMETERS, label="parameter definitions")
    for name, p in parameters.items():
        _keys(p, ("initial", "bounds", "meaning"), label="parameter")
        a, b = _vector(p["bounds"], 2, "parameter bounds")
        x = _number(p["initial"], "initial parameter")
        _text(p["meaning"], "parameter meaning")
        if not a < x < b:
            raise ValueError("initial parameters must lie strictly inside finite bounds")
    if parameters["mu"]["bounds"][0] != 0 or parameters["mu"]["bounds"][1] > 1e4:
        raise ValueError("mu requires physical lower bound zero and bounded search <= 10000")
    if not 0 < parameters["background_yield"]["bounds"][0] < parameters["background_yield"]["bounds"][1] <= 1e7:
        raise ValueError("background FULL yield must be strictly positive and bounded <= 1e7")
    if max(abs(x)*(high-low) for x in parameters["slope"]["bounds"]) > 100:
        raise ValueError("slope range exceeds stable exponential range")
    if max(abs(x) for x in parameters["transfer_theta"]["bounds"]) > 12:
        raise ValueError("transfer theta numerical bounds exceed 12")

    regions = document["regions"]
    if not isinstance(regions, list) or not 2 <= len(regions) <= 8:
        raise ValueError("two to eight explicit SR/CR regions required")
    bin_ranges, observations, names = [], [], []
    controls = 0
    for region in regions:
        _keys(region, ("name", "role", "edges", "observed", "signal", "observation_ids", "source"), label="region")
        names.append(_text(region["name"], "region name"))
        source(region["source"])
        if region["role"] not in ("signal", "control"):
            raise ValueError("regions must be fitted signal/control ranges")
        edges = region["edges"]
        if not isinstance(edges, list) or not 2 <= len(edges) <= MAX_BINS+1:
            raise ValueError("region requires explicit bin edges")
        edges = [_number(x, "edge") for x in edges]
        if edges[0] < low or edges[-1] > high or any(b <= a for a,b in zip(edges,edges[1:])):
            raise ValueError("bin edges must increase strictly inside FULL range")
        n = len(edges)-1
        if not isinstance(region["observed"], list) or len(region["observed"]) != n or any(type(x) is not int or not 0 <= x <= 1e7 for x in region["observed"]):
            raise ValueError("observations must be nonnegative integer counts, not Asimov data")
        signal = _vector(region["signal"], n, "supplied signal")
        if any(x < 0 for x in signal) or not any(x > 0 for x in signal):
            raise ValueError("each SR/CR needs complete nonnegative and nonzero supplied signal")
        if not isinstance(region["observation_ids"], list) or len(region["observation_ids"]) != n:
            raise ValueError("each count requires its observation identity")
        observations.extend(region["observation_ids"])
        bin_ranges.extend(zip(edges,edges[1:]))
        controls += n if region["role"] == "control" else 0
    _unique(names, "region names")
    _unique(observations, "observation identities")
    if not 4 <= len(bin_ranges) <= MAX_BINS or controls < 2 or not any(r["role"] == "signal" for r in regions):
        raise ValueError("at least four bins, two CR bins and one SR required")
    for i, (a,b) in enumerate(bin_ranges):
        if any(max(a,c) < min(b,d) for c,d in bin_ranges[i+1:]):
            raise ValueError("overlapping SR/CR bins cannot form independent Poisson factors")
    partition = document["partition"]
    _keys(partition, ("boundary_convention", "source", "assertion"), label="partition")
    if partition["boundary_convention"] != "half_open_final_closed":
        raise ValueError("partition requires explicit half-open bins, final FULL endpoint closed")
    source(partition["source"])
    _text(partition["assertion"], "partition assertion")
    stats = document["signal_statistics"]
    _keys(stats, ("mode", "finite_mc", "source", "meaning"), label="signal statistics")
    if stats["mode"] != "conditional_fixed" or stats["finite_mc"] != "not_modeled":
        raise ValueError("only conditional fixed signals supported; finite MC cannot be invented")
    source(stats["source"])
    _text(stats["meaning"], "fixed signal interpretation")
    points = document["comparison_points"]
    if not isinstance(points, list) or not 2 <= len(points) <= 16:
        raise ValueError("two to sixteen frozen independent density comparison points required")
    for point in points:
        _point(document, point)
    profile_points = document["profile_points"]
    if not isinstance(profile_points, list) or not 1 <= len(profile_points) <= 16:
        raise ValueError("one to sixteen profile points required")
    if any(not 0 <= _number(x, "profile mu") <= parameters["mu"]["bounds"][1] for x in profile_points) or len(set(profile_points)) != len(profile_points):
        raise ValueError("profile strengths must be unique and within mu bounds")
    calibration = document["calibration"]
    _keys(calibration, ("enabled", "seed", "trials_per_truth", "truths", "nuisance_sampling", "auxiliary_sampling", "statistic", "confidence_level", "threshold", "interval_method", "maxiter"), label="calibration")
    if type(calibration["enabled"]) is not bool or type(calibration["seed"]) is not int or not 0 <= calibration["seed"] < 2**32:
        raise ValueError("calibration requires explicit enable flag and uint32 seed")
    if type(calibration["trials_per_truth"]) is not int or not 1 <= calibration["trials_per_truth"] <= MAX_TRIALS:
        raise ValueError("calibration exceeds bounded 256 trials per truth")
    if not isinstance(calibration["truths"], list) or not 1 <= len(calibration["truths"]) <= MAX_TRUTHS:
        raise ValueError("one to four frozen truth settings required")
    for point in calibration["truths"]:
        _point(document, point)
    if calibration["nuisance_sampling"] != "fixed_truth" or calibration["auxiliary_sampling"] != "gaussian_repeated":
        raise ValueError("toys require fixed nuisance truths and repeated fluctuating Gaussian auxiliary")
    if calibration["statistic"] != "two_sided_profile_lr" or calibration["interval_method"] != "fixed_threshold_confidence_set_inclusion":
        raise ValueError("only two-sided fixed-threshold LR confidence-set diagnostic supported")
    if not 0 < _number(calibration["confidence_level"], "confidence level") < 1 or not 0 < _number(calibration["threshold"], "LR threshold") <= 100:
        raise ValueError("explicit finite confidence level and LR threshold required")
    if type(calibration["maxiter"]) is not int or not 20 <= calibration["maxiter"] <= 2000:
        raise ValueError("fit iteration ceiling must be 20 to 2000")
    assumptions = document["assumptions"]
    if not isinstance(assumptions, list) or len(assumptions) < 3:
        raise ValueError("explicit transfer, background-family and fixed-template assumptions required")
    for assumption in assumptions:
        _text(assumption, "assumption")
    return deepcopy(document)


def _capture(task, base_dir):
    """Couple the source inventory to the exact validated model bytes."""
    path = _regular(validate(task)["input"], base_dir)
    raw = path.read_bytes()
    document = prepare(_load_bytes(raw))
    captured = {str(path): raw}
    for pin in document["sources"]:
        source = _regular(pin["path"], path.parent)
        source_bytes = source.read_bytes()
        if hashlib.sha256(source_bytes).hexdigest() != pin["sha256"]:
            raise ValueError(f"continuous source hash mismatch: {pin['id']}")
        if str(source) in captured and captured[str(source)] != source_bytes:
            raise ValueError("continuous source changed during capture")
        captured[str(source)] = source_bytes
    for p,raw in captured.items():
        if Path(p).read_bytes() != raw:
            raise ValueError("continuous model/source changed during capture")
    return document, captured


def inputs(task, base_dir):
    """Return model and every verified original source path for execution custody."""
    _, captured = _capture(task,base_dir)
    return [Path(p) for p in captured]


def exponential_integral(low, high, slope, origin=0.):
    """Exact integral of exp(slope*(x-origin)); slope zero is the flat limit."""
    for x in (low, high, slope, origin):
        _number(x, "exponential argument")
    if not low < high:
        raise ValueError("integral requires increasing endpoints")
    width = high-low
    q = slope*width
    if slope == 0:
        return width
    return math.exp(slope*(low-origin))*math.expm1(q)/slope


def _mean_x(low, high, slope, origin):
    width, q = high-low, slope*(high-low)
    if abs(q) < 1e-3:
        offset = .5+q/12-q**3/720+q**5/30240
    else:
        offset = 1+1/math.expm1(q)-1/q
    return low-origin+width*offset


def _rows(document):
    return [(r["name"], r["role"], a,b,n,s) for r in document["regions"]
            for a,b,n,s in zip(r["edges"],r["edges"][1:],r["observed"],r["signal"])]


def _data(document, data):
    rows = _rows(document)
    if data is None:
        return [row[4] for row in rows], document["transfer"]["observed_auxiliary"]
    _keys(data, ("counts", "auxiliary"), label="repeated data")
    counts = _vector(data["counts"], len(rows), "repeated counts")
    if any(x < 0 or x != int(x) for x in counts):
        raise ValueError("repeated counts must be nonnegative integers")
    return counts, _number(data["auxiliary"], "repeated auxiliary")


def evaluate(document, point, data=None):
    """Analytic means/full density and physical-coordinate mean Jacobian."""
    import numpy as np
    from scipy.special import gammaln, xlogy
    _point(document, point)
    counts, z = _data(document, data)
    lo, hi = document["full_range"]
    slope = point["slope"]
    total = exponential_integral(lo,hi,slope,lo)
    full_mean = _mean_x(lo,hi,slope,lo)
    transfer = document["transfer"]["nominal"]*math.exp(document["transfer"]["log_sigma"]*point["transfer_theta"])
    means, backgrounds, fractions, jac = [], [], [], []
    for _,role,a,b,_,signal in _rows(document):
        frac = exponential_integral(a,b,slope,lo)/total
        background = point["background_yield"]*frac*(transfer if role == "signal" else 1)
        mean = background+point["mu"]*signal
        fractions.append(frac)
        backgrounds.append(background)
        means.append(mean)
        jac.append([signal, background/point["background_yield"],
                    background*(_mean_x(a,b,slope,lo)-full_mean),
                    background*document["transfer"]["log_sigma"] if role == "signal" else 0])
    means, jac, counts = np.asarray(means), np.asarray(jac), np.asarray(counts)
    if not np.all(np.isfinite(means)) or np.any(means <= 0):
        raise ValueError("continuous Poisson means must stay finite and strictly positive")
    delta = point["transfer_theta"]-z
    nll = float(np.sum(means-xlogy(counts,means)+gammaln(counts+1))+.5*delta**2+.5*math.log(2*math.pi))
    grad = jac.T@(1-counts/means)
    grad[3] += delta
    return {"means": means.tolist(), "background": backgrounds, "full_range_fractions": fractions,
            "transfer": transfer, "nll": nll, "jacobian": jac.tolist(), "gradient": grad.tolist(),
            "parameter_order": list(PARAMETERS)}


def independent_quadrature(document, point, data=None):
    """Original continuous-density witness: no analytic integral/evaluate calls.

    Recomputes each region's integral with adaptive quadrature and the complete
    Poisson/Gaussian probability including constants. Shared input is not an
    independent experiment, nor a native ROOT execution.
    """
    from scipy.integrate import quad
    _point(document, point)
    counts, z = _data(document, data)
    a,b = document["full_range"]
    def density(x):
        return math.exp(point["slope"]*(x-a))
    denominator, denominator_error = quad(density,a,b,epsabs=1e-11,epsrel=1e-11)
    means, errors = [], []
    for region in document["regions"]:
        for left,right,signal in zip(region["edges"],region["edges"][1:],region["signal"]):
            integral,error = quad(density,left,right,epsabs=1e-11,epsrel=1e-11)
            coefficient = point["background_yield"]
            if region["role"] == "signal":
                coefficient *= document["transfer"]["nominal"]*math.exp(document["transfer"]["log_sigma"]*point["transfer_theta"])
            means.append(point["mu"]*signal+coefficient*integral/denominator)
            errors.append(abs(coefficient)*(error/denominator+abs(integral)*denominator_error/denominator**2))
    nll = sum(mean-count*math.log(mean)+math.lgamma(count+1) for mean,count in zip(means,counts))
    nll += (z-point["transfer_theta"])**2/2+math.log(2*math.pi)/2
    return {"means": means, "nll": nll, "quadrature_mean_error_estimates": errors,
            "method": "adaptive_quadrature_of_original_exponential_density"}


def compare(document, points, data=None):
    """Retain full absolute density checks, including normalization constants."""
    rows = []
    for point in points:
        analytic = evaluate(document,point,data)
        independent = independent_quadrature(document,point,data)
        mean_error = max(abs(a-b) for a,b in zip(analytic["means"],independent["means"]))
        density_error = abs(analytic["nll"]-independent["nll"])
        passed = mean_error <= 1e-9*(1+max(analytic["means"])) and density_error <= 1e-8
        rows.append({"parameters": deepcopy(point), "analytic": analytic, "independent": independent,
                     "max_mean_difference": mean_error, "absolute_nll_difference": density_error, "passed": passed})
    return {"passed": all(row["passed"] for row in rows), "points": rows,
            "limits": "Quadrature and direct density are independent arithmetic, not native ROOT inference."}


def identifiability(document, point=None):
    """Local data-plus-auxiliary information rank; bounds cannot add information."""
    import numpy as np
    point = point or {name:p["initial"] for name,p in document["parameters"].items()}
    evaluation = evaluate(document,point)
    jac = np.asarray(evaluation["jacobian"])/np.sqrt(evaluation["means"])[:,None]
    matrix = np.vstack([jac,[0,0,0,1]])
    scales = np.linalg.norm(matrix,axis=0)
    normalized = matrix/np.where(scales>0,scales,1)
    _, singular, vh = np.linalg.svd(normalized,full_matrices=False)
    rank = int(np.sum(singular > max(singular[0]*1e-8,1e-12)))
    return {"identified": rank == 4, "rank": rank, "parameter_count": 4,
            "column_scaled_singular_values": singular.tolist(),
            "null_directions_in_physical_coordinates": [(v/np.where(scales>0,scales,1)).tolist() for v in vh[rank:]],
            "parameters": deepcopy(point), "scope": "local Jacobian including genuine transfer auxiliary"}


def _box_stationarity(coordinates, gradient, bounds, names):
    """Project only at an exact feasible bound; positive slack stays interior.

    The existing proximity guard remains solely a conservative refusal near
    artificial caps. It is never used to remove a feasible descent direction.
    This checks supplied first derivatives, not a global-optimum certificate.
    """
    if not names or len(set(names)) != len(names) or any(name not in PARAMETERS for name in names):
        raise ValueError("stationarity requires unique declared parameter coordinates")
    if not len(coordinates) == len(gradient) == len(bounds) == len(names):
        raise ValueError("stationarity coordinate/gradient/bound population differs")
    projected, active, near_artificial, slacks, points, derivatives, geometry = [], [], [], [], [], [], []
    for name, coordinate, derivative, limits in zip(names, coordinates, gradient, bounds):
        if len(limits) != 2:
            raise ValueError("stationarity requires two bounds per coordinate")
        x, g, a, b = float(coordinate), float(derivative), float(limits[0]), float(limits[1])
        if not all(math.isfinite(value) for value in (x, g, a, b)) or not a < b or not a <= x <= b:
            raise ValueError("stationarity coordinate must be finite and exactly feasible")
        at_low, at_high = x == a, x == b
        projected.append(0.0 if at_low and g > 0 or at_high and g < 0 else g)
        if at_low or at_high:
            active.append({"parameter": name, "side": "lower" if at_low else "upper",
                           "physical": bool(name == "mu" and at_low and a == 0.0)})
        lower, upper = x-a, b-x
        for side, slack, limit in (("lower", lower, a), ("upper", upper, b)):
            guard = 1e-7*(1+abs(limit))
            if slack < guard and not (name == "mu" and side == "lower" and a == 0.0):
                near_artificial.append({"parameter": name, "side": side, "slack": slack, "guard": guard})
        slacks.append({"parameter": name, "lower": lower, "upper": upper})
        points.append(x); derivatives.append(g); geometry.append([a,b])
    return {"coordinate_order": list(names), "coordinates": points, "coordinate_bounds": geometry,
            "coordinate_gradient": derivatives, "projected_coordinate_gradient": projected,
            "projected_gradient_max": max(abs(value) for value in projected), "active_bounds": active,
            "near_artificial_bounds": near_artificial, "bound_slacks": slacks,
            "activity_rule": "exact_feasible_coordinate_equality",
            "near_artificial_policy": "conservative_refusal_only_no_gradient_projection",
            "gradient_tolerance": 1e-4}


def _end_point_on_bounds(coordinates, objective, bounds, names):
    """Take the last step a solver cannot: onto a bound it stopped within rounding of.

    A solver can end a few units of rounding inside a bound that the objective still
    descends toward (one library returns 0.0 there, another 7e-18). The step left is
    smaller than its tolerance, and the exact-equality activity rule would then read an
    active bound as an interior point with a nonzero gradient. Such a coordinate is set
    to its bound only when its slack is within 1e-12*(1+|bound|), the gradient there
    points out of the box, and the objective evaluated at the bound has not risen beyond
    its own rounding. Stationarity is judged afterwards, at the point actually returned.
    A coordinate with more slack is never moved, and no gradient is projected here.
    """
    import numpy as np
    point = np.array([float(value) for value in coordinates])
    value, gradient = objective(point)
    moves = []
    for index, (name, limits) in enumerate(zip(names, bounds)):
        for side, limit in (("lower", float(limits[0])), ("upper", float(limits[1]))):
            slack = point[index]-limit if side == "lower" else limit-point[index]
            outward = gradient[index] > 0 if side == "lower" else gradient[index] < 0
            if not (0 < slack <= 1e-12*(1+abs(limit)) and outward and math.isfinite(value)):
                continue
            trial = point.copy()
            trial[index] = limit
            trial_value, trial_gradient = objective(trial)
            if math.isfinite(trial_value) and trial_value <= value+4*math.ulp(value):
                moves.append({"parameter": name, "side": side, "slack": float(slack),
                              "nll_before": float(value), "nll_after": float(trial_value)})
                point, value, gradient = trial, trial_value, trial_gradient
    return point, moves


def fit(document, fixed_mu=None, data=None, maxiter=500):
    """Profile actual continuum yield/slope/transfer, retaining solver attempts.

    Log yield and range-scaled slope are numerical coordinates only. Acceptance
    requires two solver families agreeing, a projected analytic gradient, local
    identification, inactive artificial caps and original-density agreement.
    """
    import numpy as np
    from scipy.optimize import minimize
    document = prepare(document)
    if type(maxiter) is not int or not 20 <= maxiter <= 2000:
        raise ValueError("maxiter must respect the 20 to 2000 ceiling")
    if fixed_mu is not None:
        _number(fixed_mu, "fixed mu")
        if not 0 <= fixed_mu <= document["parameters"]["mu"]["bounds"][1]:
            raise ValueError("fixed mu exceeds bounds")
    width = document["full_range"][1]-document["full_range"][0]
    free = [name for name in PARAMETERS if name != "mu" or fixed_mu is None]
    def to_coordinate(name,value):
        return math.log(value) if name == "background_yield" else value*width if name == "slope" else value
    def physical(x):
        point = {"mu": fixed_mu} if fixed_mu is not None else {}
        for name,value in zip(free,x):
            point[name] = float(math.exp(value) if name == "background_yield" else value/width if name == "slope" else value)
            # exp(log(bound)) can cross its exact physical bound by one ulp.
            # Only correct coordinate round-trip error, never an out-of-range fit.
            a,b = document["parameters"][name]["bounds"]
            epsilon = 1e-12*(1+max(abs(a),abs(b)))
            if a-epsilon <= point[name] < a:
                point[name] = a
            if b < point[name] <= b+epsilon:
                point[name] = b
        return point
    bounds = [tuple(to_coordinate(name,x) for x in document["parameters"][name]["bounds"]) for name in free]
    initial = np.asarray([to_coordinate(name,document["parameters"][name]["initial"]) for name in free])
    def objective(x):
        result = evaluate(document,physical(x),data)
        grad = []
        for name in free:
            value = result["gradient"][PARAMETERS.index(name)]
            if name == "background_yield":
                value *= physical(x)[name]
            elif name == "slope":
                value /= width
            grad.append(value)
        return result["nll"], np.asarray(grad)
    alternate = initial.copy()
    for i,name in enumerate(free):
        if name == "mu":
            alternate[i] = min(max(.3,bounds[i][0]+1e-5),bounds[i][1]-1e-5)
        elif name == "slope":
            alternate[i] = .25*bounds[i][0]+.75*bounds[i][1]
        elif name == "transfer_theta":
            alternate[i] = .75*initial[i]
    attempts = []
    candidates = []
    for method in ("L-BFGS-B", "SLSQP"):
        for start_id,start in enumerate((initial,alternate)):
            try:
                options = {"maxiter": maxiter, "ftol": 1e-12}
                if method == "L-BFGS-B":
                    options.update(gtol=1e-8,maxls=40)
                result = minimize(objective,start.copy(),jac=True,method=method,bounds=bounds,options=options)
                end_point,moves = _end_point_on_bounds(result.x, objective, bounds, free)
                point = physical(end_point)
                value,gradient = objective(end_point)
                stationarity = _box_stationarity(end_point, gradient, bounds, free)
                active = stationarity["active_bounds"]
                norm = stationarity["projected_gradient_max"]
                independent = independent_quadrature(document,point,data)
                identified = identifiability(document,point)["identified"]
                verified = bool(result.success and math.isfinite(value) and norm <= 1e-4 and identified and
                                all(row["physical"] for row in active) and not stationarity["near_artificial_bounds"] and
                                abs(value-independent["nll"]) <= 1e-8)
                row = {"method": method, "start": start_id, "success": bool(result.success), "verified": verified,
                       "message": str(result.message), "iterations": int(result.nit), "parameters": point,
                       "nll": value, "projected_gradient_max": norm, "active_bounds": active, "stationarity": stationarity,
                       "identified": identified, "quadrature_nll_difference": abs(value-independent["nll"])}
                if moves:
                    row["end_point_moves"] = moves
                attempts.append(row)
                if verified:
                    candidates.append(row)
            except (ValueError, OverflowError, FloatingPointError) as error:
                attempts.append({"method": method, "start": start_id, "success": False, "verified": False, "error": str(error)})
    if not candidates:
        return {"verified": False, "fixed_mu": fixed_mu, "attempts": attempts, "failure": "no stationary identified fit with inactive artificial bounds"}
    best = min(candidates,key=lambda row:row["nll"])
    method_best = [min((r["nll"] for r in candidates if r["method"] == method),default=math.inf) for method in ("L-BFGS-B","SLSQP")]
    gap = abs(method_best[0]-method_best[1])
    verified = math.isfinite(gap) and gap <= 1e-5
    return {"verified": verified, "fixed_mu": fixed_mu, "parameters": best["parameters"], "nll": best["nll"],
            "attempts": attempts, "cross_solver_nll_difference": gap if math.isfinite(gap) else None,
            "failure": None if verified else "independent solver families did not resolve the same minimum",
            "limits": "Multi-start numerical agreement and stationarity do not prove a global optimum."}


def profile(document, strengths=None, data=None, maxiter=500):
    """Return the two-sided bounded profile LR; no asymptotic CLs conversion."""
    global_fit = fit(document,data=data,maxiter=maxiter)
    profiles = []
    for mu in document["profile_points"] if strengths is None else strengths:
        conditional = fit(document,fixed_mu=mu,data=data,maxiter=maxiter)
        delta = None
        if global_fit["verified"] and conditional["verified"]:
            delta = 2*(conditional["nll"]-global_fit["nll"])
            if delta < -1e-5:
                conditional["verified"] = False
                conditional["failure"] = "conditional optimum improves claimed global minimum"
                delta = None
            else:
                delta = max(delta,0.)
        profiles.append({"mu": mu, "fit": conditional, "twice_delta_nll": delta})
    return {"verified": global_fit["verified"] and all(row["fit"]["verified"] and row["twice_delta_nll"] is not None for row in profiles),
            "global_fit": global_fit, "profiles": profiles, "statistic": "two_sided_profile_lr"}


def _binomial_interval(successes,trials,confidence):
    from scipy.stats import beta
    alpha = (1-confidence)/2
    return [float(beta.ppf(alpha,successes,trials-successes+1)) if successes else 0.,
            float(beta.ppf(1-alpha,successes+1,trials-successes)) if successes < trials else 1.]


def calibrate(document):
    """Bounded fixed-truth toys with repeated auxiliaries and all-failure counts.

    This diagnoses a *supplied* LR threshold's confidence-set inclusion. It does
    not silently choose an asymptotic threshold, calibrate CLs, estimate signal
    template statistics, or drop failed fits from the ensemble denominator.
    """
    import numpy as np
    document = prepare(document)
    protocol = document["calibration"]
    if not protocol["enabled"]:
        return {"executed": False, "protocol": deepcopy(protocol)}
    rng = np.random.default_rng(protocol["seed"])
    ensembles = []
    for truth in protocol["truths"]:
        means = evaluate(document,truth)["means"]
        records = []
        for trial in range(protocol["trials_per_truth"]):
            data = {"counts": rng.poisson(means).tolist(), "auxiliary": float(rng.normal(truth["transfer_theta"],1.))}
            result = profile(document,[truth["mu"]],data,protocol["maxiter"])
            statistic = result["profiles"][0]["twice_delta_nll"] if result["verified"] else None
            records.append({"trial": trial, "data": data, "verified": result["verified"], "fits": result,
                            "statistic": statistic, "includes_truth": statistic <= protocol["threshold"] if statistic is not None else None})
        total = len(records)
        resolved = [row for row in records if row["verified"]]
        included = sum(row["includes_truth"] for row in resolved)
        failures = total-len(resolved)
        estimates = [row["fits"]["global_fit"]["parameters"]["mu"] for row in resolved]
        bias = float(np.mean(estimates)-truth["mu"]) if estimates else None
        bias_mcse = float(np.std(estimates,ddof=1)/math.sqrt(len(estimates))) if len(estimates)>1 else None
        ensembles.append({"truth": deepcopy(truth), "generated_trials": total, "resolved_trials": len(resolved),
                          "failed_trials": failures, "included_resolved_trials": included,
                          "coverage_bounds_all_trials": [included/total,(included+failures)/total],
                          "exact_binomial_intervals_failure_exclude_include": [_binomial_interval(included,total,protocol["confidence_level"]),_binomial_interval(included+failures,total,protocol["confidence_level"])],
                          "signal_bias_resolved_only": bias, "signal_bias_mcse_resolved_only": bias_mcse,
                          "coverage_mcse_upper_bound": .5/math.sqrt(total), "trials": records})
    return {"executed": True, "protocol": deepcopy(protocol), "ensembles": ensembles,
            "all_fits_resolved": all(row["failed_trials"] == 0 for row in ensembles),
            "limits": ["Finite toy precision is retained; no coverage tolerance or physics certification is inferred.",
                       "Signal arrays are conditioned on as exact supplied predictions; finite signal MC is not modeled.",
                       "Fixed nuisance truths with fluctuating auxiliaries are frequentist repetitions, not prior sampling.",
                       "Threshold inclusion is two-sided LR confidence-set diagnostics, not CLs or interval endpoint inversion.",
                       "Background-family misspecification and detector applicability remain untested."]}


def run(task, base_dir, output_dir):
    """Source-custodied comparisons, fits and explicitly enabled bounded toys."""
    import scipy
    import numpy as np
    document, captured = _capture(task,base_dir)
    identification = identifiability(document)
    comparison = compare(document,document["comparison_points"])
    fitted = None
    calibration = {"executed": False, "failure": "pre-fit arithmetic or identification unresolved"}
    if identification["identified"] and comparison["passed"]:
        fitted = profile(document,maxiter=document["calibration"]["maxiter"])
        if fitted["verified"]:
            calibration = calibrate(document)
    passed = bool(fitted and fitted["verified"] and (not calibration["executed"] or calibration["all_fits_resolved"]))
    result = {"schema_version": 1, "kind": "continuous_exponential_sr_cr", "model_id": document["model_id"],
              "status": "passed" if passed else "failed", "physics_validated": False,
              "numerical_inference": fitted is not None, "identifiability": identification,
              "comparison": comparison, "profile": fitted, "calibration": calibration,
              "input_snapshot": [{"path":p,"sha256":hashlib.sha256(raw).hexdigest()} for p,raw in captured.items()],
              "versions": {"scipy":scipy.__version__,"numpy":np.__version__},
              "limits": ["Passed means bounded arithmetic/numerical checks only; physical background/transfer validity requires source review.",
                         "FULL yield is before SR transfer; final fitted-background total can differ from FULL yield.",
                         "Conditional fixed signal arrays have no inferred finite-MC uncertainty or official modifier transport."]}
    out = Path(output_dir)
    out.mkdir(parents=True,exist_ok=True)
    for name,value in (("continuous_fit_contract",document),("continuous_fit_result",result),
                       ("continuous_fit_comparison",comparison),("continuous_fit_profile",fitted),("continuous_fit_calibration",calibration)):
        (out/(name+".json")).write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+"\n")
    for p,raw in captured.items():
        if hashlib.sha256(Path(p).read_bytes()).hexdigest() != hashlib.sha256(raw).hexdigest():
            raise ValueError("continuous source changed during execution")
    return result
