"""Construct source-bound Poisson models for new SR/CR and ABCD analyses.

This is a closed family, not arbitrary code execution: means are sums of
nonnegative templates times products of rate factors and exponential responses
to supplied correlated Gaussian auxiliaries. Compilation, local identification,
numerical profiling and statistical calibration remain separate claims.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from ravel.physics.quantities import _keys, _number, _text, _unique

AUX_PREFIX = "__ravel_aux_"
MAX_BINS, MAX_COMPONENTS, MAX_PARAMETERS = 64, 64, 24


def _load_bytes(raw):
    from ravel.workflow.state_io import _unique as unique_json
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("statistical model input exceeds 8 MiB")
    def reject(value):
        raise ValueError("nonfinite statistical JSON: " + value)
    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            reject(value)
        return result
    return json.loads(raw, object_pairs_hook=unique_json, parse_constant=reject, parse_float=finite_float)


def _load(path):
    return _load_bytes(path.read_bytes())


def _regular(value, base):
    path = Path(value)
    path = path if path.is_absolute() else Path(base) / path
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError("statistical input must be a regular file without symlink components")
    return path.resolve()


def _vector(values, size, label, *, nonnegative=False):
    if not isinstance(values, list) or len(values) != size:
        raise ValueError(f"{label} must have exactly {size} entries")
    out = [_number(v, label) for v in values]
    if nonnegative and any(v < 0 for v in out):
        raise ValueError(f"{label} must be nonnegative")
    return out


def _matrix(values, rows, columns, label):
    if not isinstance(values, list) or len(values) != rows:
        raise ValueError(f"{label} has wrong row count")
    return [_vector(row, columns, label) for row in values]


def _name(name, label):
    _text(name, label)
    if name.startswith(AUX_PREFIX):
        raise ValueError("names cannot use the reserved auxiliary prefix")
    return name


def validate(task):
    """Validate a bounded task without running a solver or reading its files."""
    _keys(task, ("input", "profile_points", "comparison_points"), label="statistical task")
    _text(task["input"], "input")
    if not isinstance(task["profile_points"], list) or len(task["profile_points"]) > 32:
        raise ValueError("profile_points must be a list with at most 32 entries")
    for point in task["profile_points"]:
        if _number(point, "profile point") < 0:
            raise ValueError("profile points must be nonnegative")
    if len(set(task["profile_points"])) != len(task["profile_points"]):
        raise ValueError("duplicate profile point")
    if not isinstance(task["comparison_points"], list) or not 2 <= len(task["comparison_points"]) <= 32:
        raise ValueError("two to 32 frozen comparison points are required")
    for point in task["comparison_points"]:
        if not isinstance(point, dict) or not point:
            raise ValueError("comparison point must be a complete parameter map")
        for name, value in point.items():
            _name(name, "point parameter")
            _number(value, "point parameter")
    return deepcopy(task)


def prepare(document):
    """Check generative semantics; source-byte verification belongs to inputs()."""
    import numpy as np
    _keys(document, ("schema_version", "model_id", "question", "sources", "parameters", "bins",
                     "components", "auxiliary", "partition", "template_statistics", "assumptions"),
          label="statistical model")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("unsupported statistical model version")
    for field in ("model_id", "question"):
        _text(document[field], field)
    sources = document["sources"]
    if not isinstance(sources, list) or not sources:
        raise ValueError("source-bound model requires sources")
    for source in sources:
        _keys(source, ("id", "path", "sha256"), label="source")
        _text(source["id"], "source id")
        _text(source["path"], "source path")
        digest = source["sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("source sha256 must be a lowercase SHA256")
    source_names = [s["id"] for s in sources]
    _unique(source_names, "source identities")
    def source(value):
        if value not in source_names:
            raise ValueError("unknown scientific source reference")

    parameters = document["parameters"]
    if not isinstance(parameters, list) or not 1 <= len(parameters) <= MAX_PARAMETERS:
        raise ValueError("one to 24 rate parameters required")
    for parameter in parameters:
        _keys(parameter, ("name", "role", "initial", "bounds", "meaning"), label="parameter")
        _name(parameter["name"], "parameter name")
        _text(parameter["meaning"], "parameter meaning")
        if parameter["role"] not in ("poi", "rate"):
            raise ValueError("parameter role must be poi or rate")
        low, high = _vector(parameter["bounds"], 2, "parameter bounds", nonnegative=True)
        initial = _number(parameter["initial"], "initial parameter")
        if not low < initial < high:
            raise ValueError("initial rate must be strictly inside nonnegative fit bounds")
    names = [p["name"] for p in parameters]
    _unique(names, "rate names")
    pois = [p["name"] for p in parameters if p["role"] == "poi"]
    if len(pois) != 1:
        raise ValueError("exactly one parameter of interest is required")
    poi = pois[0]
    auxiliary = document["auxiliary"]
    _keys(auxiliary, ("names", "observed", "covariance", "source"), label="auxiliary")
    aux_names = auxiliary["names"]
    if not isinstance(aux_names, list) or len(aux_names) > MAX_PARAMETERS:
        raise ValueError("at most 24 auxiliary coordinates are supported")
    for name in aux_names:
        _name(name, "auxiliary name")
    if len(set(aux_names)) != len(aux_names) or set(names) & set(aux_names):
        raise ValueError("rate and physical auxiliary identities must be unique")
    k = len(aux_names)
    observed_aux = _vector(auxiliary["observed"], k, "auxiliary observations")
    covariance = _matrix(auxiliary["covariance"], k, k, "auxiliary covariance")
    if k:
        source(auxiliary["source"])
        cov = np.asarray(covariance)
        scale = max(float(np.max(np.abs(cov))), 1e-300)
        if not np.allclose(cov, cov.T, rtol=0, atol=1e-12*scale):
            raise ValueError("auxiliary covariance must be symmetric")
        eigen = np.linalg.eigvalsh(cov)
        if eigen.min() <= max(eigen.max()*1e-12, 0):
            raise ValueError("auxiliary covariance must be positive definite without regularization")
        cholesky = np.linalg.cholesky(cov)
    else:
        if auxiliary["source"] is not None:
            raise ValueError("empty auxiliary source must be null")
        cholesky = np.empty((0, 0))

    bins = document["bins"]
    if not isinstance(bins, list) or not 1 <= len(bins) <= MAX_BINS:
        raise ValueError("one to 64 disjoint count bins required")
    for row in bins:
        _keys(row, ("id", "role", "observed", "observation_id", "source"), label="count bin")
        _text(row["id"], "bin id")
        _text(row["observation_id"], "observation identity")
        source(row["source"])
        if row["role"] not in ("signal", "control"):
            raise ValueError("only fitted signal/control bins are supported; validation data must remain held out")
        if type(row["observed"]) is not int or row["observed"] < 0:
            raise ValueError("observed count must be a nonnegative integer; Asimov data are separate")
    ids = [row["id"] for row in bins]
    _unique(ids, "bin identities")
    _unique([row["observation_id"] for row in bins], "observation identities")
    n = len(bins)
    partition = document["partition"]
    _keys(partition, ("kind", "source", "overlap_counts"), label="partition")
    if partition["kind"] != "disjoint":
        raise ValueError("only explicitly disjoint Poisson observations are supported")
    source(partition["source"])
    overlaps = _matrix(partition["overlap_counts"], n, n, "overlap_counts")
    for i in range(n):
        for j in range(n):
            value = partition["overlap_counts"][i][j]
            if type(value) is not int or value < 0 or (i == j and value != bins[i]["observed"]):
                raise ValueError("overlap counts must be integers with observed-count diagonal")
            if i != j and value:
                raise ValueError("overlapping observations cannot become independent Poisson bins")

    components = document["components"]
    if not isinstance(components, list) or not 1 <= len(components) <= MAX_COMPONENTS:
        raise ValueError("one to 64 template components required")
    used = set()
    nominal_total = np.zeros(n)
    signal_present = False
    for component in components:
        _keys(component, ("id", "nominal", "factors", "log_response", "source"), label="component")
        _text(component["id"], "component id")
        source(component["source"])
        nominal = _vector(component["nominal"], n, "nominal component", nonnegative=True)
        nominal_total += nominal
        _matrix(component["log_response"], n, k, "component log response")
        if not isinstance(component["factors"], list) or len(component["factors"]) != n:
            raise ValueError("every bin, including control signal, needs explicit rate factors")
        for i, factors in enumerate(component["factors"]):
            if not isinstance(factors, list) or len(set(factors)) != len(factors) or any(f not in names for f in factors):
                raise ValueError("each component/bin requires unique known rate factors")
            used.update(factors)
            if poi in factors and nominal[i] > 0:
                signal_present = True
            # Bound the exported positive factor, not the user's scientific response.
            whitened = np.asarray(component["log_response"][i]) @ cholesky
            if any(abs(value) > 50 for value in whitened):
                raise ValueError("log-rate response exceeds the bounded numerical domain")
    _unique([c["id"] for c in components], "component identities")
    if used != set(names) or not signal_present:
        raise ValueError("every rate must be used and the POI must affect a positive template")
    if np.any(nominal_total <= 0):
        raise ValueError("a count bin with no positive nominal prediction requires an explicit different model")
    statistics = document["template_statistics"]
    _keys(statistics, ("kind", "reason", "source"), label="template statistics")
    if statistics["kind"] not in ("conditional_fixed", "supplied_log_gaussian_approximation"):
        raise ValueError("template statistics must declare fixed conditional predictions or supplied log-Gaussian approximation")
    _text(statistics["reason"], "template statistics reason")
    source(statistics["source"])
    if statistics["kind"] == "supplied_log_gaussian_approximation" and not k:
        raise ValueError("an approximate template model requires supplied auxiliary coordinates")
    assumptions = document["assumptions"]
    if not isinstance(assumptions, list) or not assumptions:
        raise ValueError("explicit generative and data-use assumptions required")
    for assumption in assumptions:
        _keys(assumption, ("id", "statement", "source", "status"), label="assumption")
        _text(assumption["id"], "assumption identity")
        _text(assumption["statement"], "assumption statement")
        source(assumption["source"])
        if assumption["status"] not in ("assumed", "externally_checked"):
            raise ValueError("assumption status must be assumed or externally_checked")
    _unique([a["id"] for a in assumptions], "assumption identities")
    return {"poi": poi, "parameter_names": list(names), "auxiliary_names": aux_names[:],
            "bin_ids": list(ids), "cholesky": cholesky.tolist(), "source_ids": list(source_names),
            "observed_auxiliary": observed_aux}


def inputs(task, base_dir):
    task = validate(task)
    path = _regular(task["input"], base_dir)
    document = _load(path)
    prepare(document)
    paths = [path]
    for reference in document["sources"]:
        source = _regular(reference["path"], path.parent)
        if hashlib.sha256(source.read_bytes()).hexdigest() != reference["sha256"]:
            raise ValueError(f"statistical source hash mismatch: {reference['id']}")
        if source not in paths:
            paths.append(source)
    for point in task["comparison_points"]:
        _point(document, point)
    poi = next(p for p in document["parameters"] if p["role"] == "poi")
    if any(not poi["bounds"][0] <= p <= poi["bounds"][1] for p in task["profile_points"]):
        raise ValueError("profile point exceeds the declared POI fit range")
    return paths


def _point(document, point):
    expected = {p["name"] for p in document["parameters"]} | set(document["auxiliary"]["names"])
    if not isinstance(point, dict) or set(point) != expected:
        raise ValueError("point must identify every rate and physical auxiliary parameter exactly")
    for value in point.values():
        _number(value, "point value")
    for parameter in document["parameters"]:
        if not parameter["bounds"][0] <= point[parameter["name"]] <= parameter["bounds"][1]:
            raise ValueError("point rate lies outside declared bounds")
    return point


def evaluate(document, point):
    """Producer likelihood in physical coordinates, with analytic mean Jacobian."""
    import numpy as np
    _point(document, point)
    rate_names = [p["name"] for p in document["parameters"]]
    aux_names = document["auxiliary"]["names"]
    names = rate_names + aux_names
    theta = np.asarray([point[name] for name in aux_names])
    means = np.zeros(len(document["bins"]))
    jacobian = np.zeros((len(means), len(names)))
    for component in document["components"]:
        for i, nominal in enumerate(component["nominal"]):
            factors = component["factors"][i]
            response = np.asarray(component["log_response"][i])
            base = nominal * math.exp(float(response @ theta))
            contribution = base * math.prod(point[name] for name in factors)
            means[i] += contribution
            for name in factors:
                jacobian[i, names.index(name)] += base * math.prod(point[other] for other in factors if other != name)
            jacobian[i, len(rate_names):] += contribution * response
    counts = np.asarray([row["observed"] for row in document["bins"]])
    if not np.all(np.isfinite(means)) or np.any(means < 0) or any(mean == 0 and count > 0 for mean, count in zip(means, counts)):
        raise ValueError("model point has no finite Poisson likelihood")
    poisson = math.fsum(float(mean) - (int(count)*math.log(float(mean)) if count else 0.) for mean, count in zip(means, counts))
    auxiliary = 0.
    if aux_names:
        delta = theta - document["auxiliary"]["observed"]
        auxiliary = .5 * float(delta @ np.linalg.solve(document["auxiliary"]["covariance"], delta))
    return {"means": means.tolist(), "poisson_nll": poisson, "auxiliary_nll": auxiliary,
            "nll_without_constant": poisson+auxiliary, "jacobian": jacobian.tolist(), "parameter_order": names}


def identifiability(document, point=None):
    """Local expected-information rank; bounds never supply missing information."""
    import numpy as np
    metadata = prepare(document)
    if point is None:
        point = {p["name"]: p["initial"] for p in document["parameters"]}
        point.update(dict.fromkeys(metadata["auxiliary_names"], 0.))
    values = evaluate(document, point)
    means = np.asarray(values["means"])
    if np.any(means <= 0):
        raise ValueError("local information needs positive means at its stated reference point")
    jacobian = np.asarray(values["jacobian"])
    rows = jacobian / np.sqrt(means)[:, None]
    k = len(metadata["auxiliary_names"])
    if k:
        aux_rows = np.zeros((k, rows.shape[1]))
        aux_rows[:, -k:] = np.linalg.inv(np.asarray(metadata["cholesky"]))
        rows = np.vstack([rows, aux_rows])
    scales = np.asarray([p["initial"] for p in document["parameters"]] +
                        [math.sqrt(document["auxiliary"]["covariance"][i][i]) for i in range(k)])
    rows = rows * scales[None, :]
    _, singular, vt = np.linalg.svd(rows, full_matrices=True)
    tolerance = 1e-10 * max(float(singular[0]), 1.)
    rank = int(np.count_nonzero(singular > tolerance))
    nulls = vt[rank:]
    poi_index = values["parameter_order"].index(metadata["poi"])
    poi_identified = not any(abs(vector[poi_index]) > 1e-7 for vector in nulls)
    return {"identified": rank == len(values["parameter_order"]), "poi_identifiable": poi_identified,
            "rank": rank, "parameter_count": len(values["parameter_order"]),
            "parameter_order": values["parameter_order"], "reference_point": point,
            "singular_values": singular.tolist(), "rank_tolerance": tolerance,
            "null_directions": (nulls * scales[None, :]).tolist(), "column_scales": scales.tolist(), "scope": "local expected-information rank only; global identifiability is not proved"}


def compile_model(document):
    """Export positive log-linear means exactly using explicit code1 modifiers."""
    import numpy as np
    metadata = prepare(document)
    k = len(metadata["auxiliary_names"])
    chol = np.asarray(metadata["cholesky"]).reshape((k, k))
    whitened_observed = np.linalg.solve(chol, metadata["observed_auxiliary"]).tolist() if k else []
    aux_names = [f"{AUX_PREFIX}{i}" for i in range(k)]
    channels = []
    for i, row in enumerate(document["bins"]):
        samples = []
        for component in document["components"]:
            modifiers = [{"name": name, "type": "normfactor", "data": None} for name in component["factors"][i]]
            response = np.asarray(component["log_response"][i]) @ chol
            modifiers.extend({"name": name, "type": "normsys", "data": {"hi": math.exp(float(effect)), "lo": math.exp(-float(effect))}}
                             for name, effect in zip(aux_names, response))
            samples.append({"name": component["id"], "data": [component["nominal"][i]], "modifiers": modifiers})
        channels.append({"name": row["id"], "samples": samples})
    parameters = [{"name": p["name"], "inits": [p["initial"]], "bounds": [p["bounds"]]}
                  for p in document["parameters"]]
    parameters.extend({"name": name, "inits": [0.], "bounds": [[-8., 8.]], "auxdata": [observed]}
                      for name, observed in zip(aux_names, whitened_observed))
    workspace = {"version": "1.0.0", "channels": channels,
                 "observations": [{"name": row["id"], "data": [row["observed"]]} for row in document["bins"]],
                 "measurements": [{"name": document["model_id"], "config": {"poi": metadata["poi"], "parameters": parameters}}]}
    return {"workspace": workspace, "model_settings": {"modifier_settings": {"normsys": {"interpcode": "code1"}}},
            "auxiliary_transform": {"physical_names": metadata["auxiliary_names"], "whitened_names": aux_names,
                                    "cholesky": metadata["cholesky"], "observed_whitened": whitened_observed,
                                    "meaning": "theta = L eta; eta numerical fit bounds [-8,8], active bounds unresolved"},
            "source_basis": {"bins": metadata["bin_ids"], "rates": metadata["parameter_names"],
                             "sources": document["sources"], "template_statistics": document["template_statistics"]}}


def _backend(bundle):
    import pyhf
    if pyhf.__version__ != "0.7.6":
        raise RuntimeError("statistical compiler cross-check requires pinned pyhf 0.7.6")
    pyhf.set_backend("numpy")
    workspace = pyhf.Workspace(bundle["workspace"])
    model = workspace.model(**bundle["model_settings"])
    return model, workspace.data(model)


def _compiled_point(document, bundle, model, point):
    import numpy as np
    _point(document, point)
    values = {p["name"]: point[p["name"]] for p in document["parameters"]}
    transform = bundle["auxiliary_transform"]
    if transform["physical_names"]:
        white = np.linalg.solve(transform["cholesky"], [point[name] for name in transform["physical_names"]])
        values.update(zip(transform["whitened_names"], white))
    return np.asarray([values[name] for name in model.config.par_names])


def _physical_point(document, bundle, model, vector):
    import numpy as np
    values = dict(zip(model.config.par_names, vector))
    point = {p["name"]: float(values[p["name"]]) for p in document["parameters"]}
    transform = bundle["auxiliary_transform"]
    if transform["physical_names"]:
        physical = np.asarray(transform["cholesky"]) @ [values[name] for name in transform["whitened_names"]]
        point.update((name, float(value)) for name, value in zip(transform["physical_names"], physical))
    return point


def compare_likelihoods(document, points, bundle=None):
    """Compare producer, independent original-coordinate checker and pyhf."""
    import numpy as np
    from ravel.validation.statistical_model_witness import evaluate as independent
    bundle = compile_model(document) if bundle is None else bundle
    model, data = _backend(bundle)
    order = [model.config.channels.index(row["id"]) for row in document["bins"]]
    rows = []
    for point in points:
        producer = evaluate(document, point)
        witness = independent(document, point)
        pars = _compiled_point(document, bundle, model, point)
        means = np.asarray(model.expected_actualdata(pars))[order]
        backend_nll = -float(np.asarray(model.logpdf(pars, data)).reshape(-1)[0])
        # logpdf is ln L, so -ln L; its factorial/Gaussian constants cancel below.
        rows.append({"point": point, "producer": producer["nll_without_constant"],
                     "independent": witness["nll_without_constant"], "backend": backend_nll,
                     "mean_residual": max(abs(float(a)-float(b)) for a,b in zip(means, witness["means"])),
                     "producer_mean_residual": max(abs(float(a)-float(b)) for a,b in zip(producer["means"], witness["means"]))})
    origin = rows[0]
    for row in rows:
        row["likelihood_difference_residual"] = (row["backend"]-origin["backend"])-(row["independent"]-origin["independent"])
        row["producer_nll_residual"] = row["producer"]-row["independent"]
    maximum = max(abs(row[key]) for row in rows for key in ("mean_residual", "producer_mean_residual", "likelihood_difference_residual", "producer_nll_residual"))
    return {"passed": maximum <= 1e-8, "max_absolute_residual": maximum, "atol": 1e-8,
            "comparisons": rows, "scope": "same supplied model, independent likelihood arithmetic and pyhf compilation; no coverage claim"}


def fit(document, *, fixed=None, bundle=None):
    """Bounded multistart direct and compiled fits with retained failures."""
    import numpy as np
    import pyhf
    from scipy.optimize import minimize
    bundle = compile_model(document) if bundle is None else bundle
    model, data = _backend(bundle)
    initial = np.asarray(model.config.suggested_init(), dtype=float)
    bounds = model.config.suggested_bounds()
    poi_index = model.config.poi_index
    if fixed is not None:
        _number(fixed, "fixed POI")
        if not bounds[poi_index][0] <= fixed <= bounds[poi_index][1]:
            raise ValueError("fixed POI outside fit range")
        initial[poi_index] = fixed
    free = [i for i in range(len(initial)) if fixed is None or i != poi_index]
    def expand(vector):
        point = initial.copy()
        point[free] = vector
        return point
    def objective(vector):
        try:
            return evaluate(document, _physical_point(document, bundle, model, expand(vector)))["nll_without_constant"]
        except (ValueError, OverflowError, FloatingPointError):
            return math.inf
    attempts = []
    candidates = []
    current = initial[free]
    if not free:
        candidates.append((objective([]), initial.copy(), "direct_fixed"))
    for method in ("Powell", "L-BFGS-B") if free else ():
        options = {"maxiter": 2000, "ftol": 1e-12}
        if method == "Powell":
            options["xtol"] = 1e-9
        else:
            options["gtol"] = 1e-8
        result = minimize(objective, current, method=method, bounds=[bounds[i] for i in free], options=options)
        value = float(objective(result.x))
        attempts.append({"backend": "scipy_direct", "method": method, "success": bool(result.success),
                         "message": str(result.message), "nll": value if math.isfinite(value) else None,
                         "evaluations": int(result.nfev)})
        if result.success and math.isfinite(value):
            candidates.append((value, expand(result.x), method))
            current = result.x
    if not candidates:
        return {"verified": False, "attempts": attempts, "failure": "all direct optimization attempts failed"}
    direct_best = min(candidates, key=lambda x:x[0])
    compiled_candidates = []
    starts = [initial, direct_best[1]]
    for start in starts:
        try:
            kwargs = {"init_pars": start.tolist(), "par_bounds": bounds, "return_fitted_val": True,
                      "maxiter": 2000, "tolerance": 1e-9}
            if fixed is None:
                vector, _ = pyhf.infer.mle.fit(data, model, **kwargs)
            else:
                vector, _ = pyhf.infer.mle.fixed_poi_fit(fixed, data, model, **kwargs)
            vector = np.asarray(vector)
            if fixed is not None and abs(float(vector[poi_index])-fixed) > 1e-10:
                raise ValueError("compiled fit changed the fixed parameter of interest")
            value = evaluate(document, _physical_point(document, bundle, model, vector))["nll_without_constant"]
            compiled_candidates.append((value, vector, "pyhf_slsqp"))
            attempts.append({"backend": "pyhf_slsqp", "success": True, "nll": value})
        except (ValueError, RuntimeError, FloatingPointError, pyhf.exceptions.FailedMinimization) as error:
            attempts.append({"backend": "pyhf_slsqp", "success": False, "error": str(error)})
    if not compiled_candidates:
        return {"verified": False, "attempts": attempts, "failure": "compiled optimization failed"}
    compiled_best = min(compiled_candidates, key=lambda x:x[0])
    best = min([direct_best, compiled_best], key=lambda x:x[0])
    discrepancy = abs(direct_best[0]-compiled_best[0])
    active = []
    for i, (value, bound) in enumerate(zip(best[1], bounds)):
        if fixed is not None and i == poi_index:
            continue
        if abs(value-bound[1]) <= 1e-6*max(1., abs(bound[1])):
            active.append({"parameter": model.config.par_names[i], "boundary": "upper_fit_cap"})
        if abs(value-bound[0]) <= 1e-6*max(1., abs(bound[0])):
            if model.config.par_names[i].startswith(AUX_PREFIX):
                active.append({"parameter": model.config.par_names[i], "boundary": "lower_auxiliary_fit_cap"})
            elif bound[0] > 0:
                active.append({"parameter": model.config.par_names[i], "boundary": "positive_lower_fit_cap"})
    point = _physical_point(document, bundle, model, best[1])
    details = evaluate(document, point)
    means = np.asarray(details["means"])
    counts = np.asarray([row["observed"] for row in document["bins"]])
    ratio = np.divide(counts, means, out=np.zeros_like(means), where=means != 0)
    physical_gradient = np.asarray(details["jacobian"]).T @ (1.-ratio)
    nrates = len(document["parameters"])
    k = len(document["auxiliary"]["names"])
    if k:
        physical_gradient[nrates:] += np.linalg.solve(document["auxiliary"]["covariance"],
            [point[name]-observed for name, observed in zip(document["auxiliary"]["names"], document["auxiliary"]["observed"])])
    gradients = {p["name"]: physical_gradient[i] for i,p in enumerate(document["parameters"])}
    if k:
        gradients.update(zip(bundle["auxiliary_transform"]["whitened_names"],
            np.asarray(bundle["auxiliary_transform"]["cholesky"]).T @ physical_gradient[nrates:]))
    coordinate_scale = {p["name"]: p["initial"] for p in document["parameters"]}
    projected = []
    for i, name in enumerate(model.config.par_names):
        if fixed is not None and i == poi_index:
            projected.append(0.)
            continue
        value, (lower, upper) = best[1][i], bounds[i]
        gradient = float(gradients[name])
        if abs(value-lower) <= 1e-7*max(1., abs(lower)):
            gradient = min(gradient, 0.)
        if abs(value-upper) <= 1e-7*max(1., abs(upper)):
            gradient = max(gradient, 0.)
        projected.append(gradient*coordinate_scale.get(name, 1.))
    projected_norm = max(abs(x) for x in projected)
    gradient_tolerance = 1e-4 * max(1., math.sqrt(float(sum(counts))))
    stationarity = {"passed": projected_norm <= gradient_tolerance,
                    "scaled_projected_gradient_norm": projected_norm, "tolerance": gradient_tolerance,
                    "physical_parameter_order": details["parameter_order"], "physical_gradient": physical_gradient.tolist(),
                    "scope": "first-order constrained stationarity; no global optimality proof"}
    return {"verified": discrepancy <= 1e-5 and not active and stationarity["passed"], "parameters": point,
            "stationarity": stationarity,
            "means": evaluate(document, point)["means"], "nll_without_constant": best[0],
            "solver_nll_difference": discrepancy, "active_numerical_bounds": active, "attempts": attempts,
            "scope": "bounded numerical cross-solver optimum; no proof of global optimum or interval calibration"}


def moment_log_response(quantity_result, *, coordinates, evidence, interpretation, base_dir="."):
    """Preserve a supplied full absolute-yield covariance as a local approximation.

    This does not convert normalized covariance, moment covariance or systematic
    variation weights into auxiliary evidence without an explicit interpretation.
    The caller must bind the actual quantity artifact and scientific justification.
    """
    import numpy as np
    _keys(evidence, ("path", "sha256"), label="quantity evidence")
    _text(evidence["path"], "quantity evidence path")
    if not isinstance(evidence["sha256"], str) or len(evidence["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in evidence["sha256"]):
        raise ValueError("quantity evidence requires a SHA256")
    _text(interpretation, "explicit uncertainty interpretation")
    source_path = _regular(evidence["path"], base_dir)
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != evidence["sha256"] or _load(source_path) != quantity_result:
        raise ValueError("quantity evidence bytes differ from the supplied moment result")
    quantity = quantity_result.get("quantity", quantity_result.get("contract"))
    if not isinstance(quantity, dict) or quantity.get("normalization", {}).get("kind") != "absolute":
        raise ValueError("only absolute quantity predictions may become local log-rate responses")
    if quantity.get("representation") != "integrated":
        raise ValueError("template inputs must be integrated absolute yields")
    order = quantity_result.get("covariance_order")
    if not isinstance(order, list) or not isinstance(coordinates, list) or not coordinates:
        raise ValueError("full covariance order and selected coordinates required")
    if len({json.dumps(v, sort_keys=True) for v in order}) != len(order):
        raise ValueError("duplicate quantity covariance coordinates")
    if len({json.dumps(v, sort_keys=True) for v in coordinates}) != len(coordinates):
        raise ValueError("duplicate selected covariance coordinates")
    try:
        indices = [order.index(value) for value in coordinates]
        ids = quantity_result["bin_ids"]
        values = [quantity_result["values"][coord["weight"]][ids.index(coord["bin_id"])] for coord in coordinates]
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError("quantity coordinates do not resolve to actual central values") from error
    if any(_number(value, "central prediction") <= 0 for value in values):
        raise ValueError("zero or negative templates cannot use a log-rate approximation")
    full = np.asarray(_matrix(quantity_result["covariance"], len(order), len(order), "quantity covariance"))
    covariance = full[np.ix_(indices, indices)]
    scale = max(float(np.max(np.abs(covariance))), 1e-300)
    if not np.allclose(covariance, covariance.T, rtol=0, atol=1e-12*scale):
        raise ValueError("quantity covariance is asymmetric")
    eigen, vectors = np.linalg.eigh(covariance)
    if eigen.min() < -1e-12*scale:
        raise ValueError("quantity covariance is not positive semidefinite")
    active = eigen > 1e-12*scale
    loading = vectors[:, active] * np.sqrt(eigen[active])
    response = loading / np.asarray(values)[:, None]
    reconstructed = (np.asarray(values)[:, None]*response) @ (np.asarray(values)[:, None]*response).T
    return {"kind": "local_log_gaussian_template_approximation", "coordinates": coordinates,
            "central": values, "covariance": covariance.tolist(), "log_response": response.tolist(),
            "basis_rank": int(active.sum()), "discarded_eigenvalues": eigen[~active].tolist(),
            "reconstruction_residual": float(np.max(np.abs(reconstructed-covariance))),
            "evidence": evidence, "interpretation": interpretation,
            "sampling_model": quantity_result.get("uncertainty_scope"),
            "limitations": ["Matches the supplied covariance only to first order at zero nuisance.",
                            "Exponential deformation changes finite-shift means and higher moments; it is not an exact finite-MC sampling law.",
                            "Unselected coordinates remain outside this model; no unknown cross-source independence is inferred."]}



def attach_quantity_uncertainty(document, quantity_result, *, mappings, evidence,
                                source_id, interpretation, base_dir="."):
    """Join actual event-yield moments to named template bins without diagonalizing.

    The initial bridge accepts one already joint MC moment source and no existing
    auxiliary experiment. Combining separately supplied sources would require
    cross-covariance or a reviewed independence construction, neither inferred here.
    """
    prepare(document)
    if document["auxiliary"]["names"]:
        raise ValueError("existing auxiliary sources need a supplied joint correlation model")
    if not isinstance(mappings, list) or not mappings:
        raise ValueError("explicit quantity-to-component/bin mappings required")
    for mapping in mappings:
        _keys(mapping, ("coordinate", "component", "bin_id"), label="quantity mapping")
        _keys(mapping["coordinate"], ("weight", "bin_id"), label="quantity coordinate")
    projected = moment_log_response(quantity_result, coordinates=[row["coordinate"] for row in mappings],
                                    evidence=evidence, interpretation=interpretation, base_dir=base_dir)
    if quantity_result.get("unit") != "events":
        raise ValueError("Poisson template bridge requires an explicit absolute events unit and supplied conversion")
    _name(source_id, "MC source identity")
    result = deepcopy(document)
    ids = [row["id"] for row in result["bins"]]
    components = {row["id"]: row for row in result["components"]}
    targets = []
    for row, value in zip(mappings, projected["central"]):
        if row["component"] not in components or row["bin_id"] not in ids:
            raise ValueError("quantity mapping targets an unknown template component/bin")
        index = ids.index(row["bin_id"])
        if components[row["component"]]["nominal"][index] != value:
            raise ValueError("quantity central value does not match target template exactly")
        targets.append((row["component"], index))
    if len(set(targets)) != len(targets):
        raise ValueError("multiple quantity coordinates cannot overwrite the same template")
    rank = projected["basis_rank"]
    if rank == 0:
        raise ValueError("zero-variance quantity has no Gaussian auxiliary source to attach")
    names = [f"{source_id}_mode_{i}" for i in range(rank)]
    if set(names) & {p["name"] for p in result["parameters"]}:
        raise ValueError("MC auxiliary identity collides with a physical rate parameter")
    reference = {"id": source_id, **evidence}
    matching = [ref for ref in result["sources"] if ref["id"] == source_id]
    if matching and matching != [reference]:
        raise ValueError("MC source identity conflicts with a different artifact")
    if not matching:
        result["sources"].append(reference)
    result["auxiliary"] = {"names": names, "observed": [0.]*rank,
                           "covariance": [[float(i == j) for j in range(rank)] for i in range(rank)],
                           "source": source_id}
    for component in result["components"]:
        component["log_response"] = [[0.]*rank for _ in ids]
    for (component, index), response in zip(targets, projected["log_response"]):
        components[component]["log_response"][index] = response
    result["template_statistics"] = {"kind": "supplied_log_gaussian_approximation", "source": source_id,
                                     "reason": interpretation}
    assumption_id = f"{source_id}_local_gaussian_model"
    if assumption_id in {a["id"] for a in result["assumptions"]}:
        raise ValueError("MC approximation assumption identity already used")
    result["assumptions"].append({"id": assumption_id, "statement": interpretation + " First-order log-Gaussian approximation only; finite-MC coverage remains unvalidated.",
                                  "source": source_id, "status": "assumed"})
    prepare(result)
    return {"document": result, "propagation": projected}


def run(task, base_dir, output_dir):
    """Construct, cross-check and profile a supplied novel count model."""
    import numpy as np
    import pyhf
    import scipy
    task = validate(task)
    model_path = _regular(task["input"], base_dir)
    model_bytes = model_path.read_bytes()
    document = _load_bytes(model_bytes)
    paths = inputs(task, base_dir)
    source_snapshot = [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths]
    captured_hashes = {row["path"]: row["sha256"] for row in source_snapshot}
    if captured_hashes[str(model_path)] != hashlib.sha256(model_bytes).hexdigest():
        raise ValueError("statistical model changed between capture and validation")
    for reference in document["sources"]:
        source_path = _regular(reference["path"], model_path.parent)
        if captured_hashes.get(str(source_path)) != reference["sha256"]:
            raise ValueError("statistical source changed between validation and capture")
    bundle = compile_model(document)
    identification = identifiability(document)
    comparisons = compare_likelihoods(document, task["comparison_points"], bundle)
    fitted = None
    profiles = []
    status = "passed" if comparisons["passed"] else "failed"
    if comparisons["passed"] and identification["identified"]:
        fitted = fit(document, bundle=bundle)
        if not fitted["verified"]:
            status = "failed"
        else:
            poi = next(p["name"] for p in document["parameters"] if p["role"] == "poi")
            for strength in task["profile_points"]:
                profile = fit(document, fixed=strength, bundle=bundle)
                row = {"signal_strength": strength, "fit": profile, "twice_delta_nll": None, "q_mu": None}
                if profile["verified"]:
                    delta = 2*(profile["nll_without_constant"]-fitted["nll_without_constant"])
                    if delta < -1e-5:
                        profile["verified"] = False
                        profile["failure"] = "conditional fit improves on claimed global fit"
                        status = "failed"
                    else:
                        row["twice_delta_nll"] = max(delta, 0.)
                        row["q_mu"] = max(delta, 0.) if fitted["parameters"][poi] <= strength else 0.
                else:
                    status = "failed"
                profiles.append(row)
    result = {"schema_version": 1, "kind": "constructed_poisson_model", "model_id": document["model_id"],
              "question": document["question"], "status": status, "physics_validated": False,
              "model_assessment": "identified_locally" if identification["identified"] else "unidentified",
              "local_identifiability": identification, "independent_likelihood": comparisons,
              "fit": fitted, "profiles": profiles, "inference": None,
              "sources": source_snapshot,
              "assumptions": document["assumptions"], "template_statistics": document["template_statistics"],
              "versions": {"numpy": np.__version__, "scipy": scipy.__version__, "pyhf": pyhf.__version__},
              "limitations": ["Successful construction and profiling do not establish physical background transfers, source independence or coverage.",
                              "Observed count partition and auxiliary independence are source-bound supplied assumptions, not authenticated by naming files.",
                              "The exported workspace requires its explicit code1 settings and auxiliary basis.",
                              "Profile statistics are numerical diagnostics; no general-model exclusion or discovery result is produced."]}
    if any(hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest() != row["sha256"] for row in source_snapshot):
        raise ValueError("statistical input changed during construction or fitting")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {"workspace.json": bundle["workspace"], "model-settings.json": bundle["model_settings"],
                 "model-basis.json": {k:v for k,v in bundle.items() if k not in ("workspace", "model_settings")},
                 "statistical-model.json": result}
    for name, value in artifacts.items():
        with (output/name).open("x") as stream:
            stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+"\n")
    return result
