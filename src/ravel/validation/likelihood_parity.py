"""Bounded fixed-vector likelihood parity, with no fitting or root search.

The independent density uses Python math for every Poisson and Normal term,
including constants. It deliberately shares the published compiled main means;
it is not an independent implementation of HistFactory interpolation. Auxiliary
means/widths are assembled independently from the bound parameter-set contract.
NumPy and JAX compile in successive phases because pyhf's backend is global.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

MAX_BYTES = 16 * 1024 * 1024
TOLERANCES = {"twice_nll_atol": 1e-7, "expected_atol": 1e-9,
              "expected_rtol": 1e-10, "gradient_atol": 1e-5,
              "gradient_rtol": 1e-4, "step_scale": 1e-4}
SCOPE = "Fixed-vector published-model density and gradient parity; no optimizer, exclusion or physics validation"


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(label + " must be finite and nonboolean")
    return float(value)


def _keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(label + " has missing or unknown fields")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def compiled_json_identity(compiled):
    """Compare compiled metadata in the same JSON representation as its receipt.

    pyhf returns tuple bounds for some default parameter sets. Persisting the
    metadata writes those tuples as JSON arrays, which load as lists. This
    round-trip changes only that representation, never the live model or its
    numerical bounds, fixed mask, parameter order, or data.
    """
    return json.loads(json.dumps(compiled, allow_nan=False))


def compiled_reference_identity(reference):
    """Validate the saved data digest before reconciling numeric JSON spelling.

    Older compiled receipts hashed integer main observations with float
    auxiliaries; the current compiler hashes float inference data. Keep both
    identities and require an exact, lossless value/order correspondence.
    """
    source = reference["observed_and_auxiliary_data"]
    digest = lambda values: hashlib.sha256(json.dumps(
        values, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    if digest(source) != reference["data_compact_sha256"]:
        raise ValueError("compiled reference data digest does not match its literal saved data")
    floats = [_number(value, "reference observed/auxiliary data") for value in source]
    if any(actual != original for actual, original in zip(floats, source)):
        raise ValueError("compiled reference data cannot be represented losslessly as float")
    normalized = compiled_json_identity(reference)
    normalized["observed_and_auxiliary_data"] = floats
    normalized["data_compact_sha256"] = digest(floats)
    return normalized, {
        "source_literal_data_sha256": reference["data_compact_sha256"],
        "float_inference_data_sha256": normalized["data_compact_sha256"],
        "source_integer_values": sum(type(value) is int for value in source),
        "source_float_values": sum(type(value) is float for value in source),
        "exact_values_and_order_preserved": True,
        "source_bytes_and_evaluator_data_changed": False,
    }


def _pin(pin, base):
    from ravel.workflow.science import regular
    from ravel.physics.published_model import _json
    _keys(pin, ("path", "sha256"), "binding")
    path = regular(pin["path"], base)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("parity input exceeds byte bound")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != pin["sha256"]:
        raise ValueError("parity input differs from binding")
    return path, _json(raw)


def validate(task):
    _keys(task, ("input",), "likelihood-parity task")
    if not isinstance(task["input"], str) or not task["input"].strip():
        raise ValueError("likelihood-parity input path required")
    return deepcopy(task)


def validate_document(document):
    _keys(document, ("schema_version", "published_input", "retained_inputs", "compiled_reference", "runtime_inventory",
                     "grounding", "gradient_vectors", "limits", "tolerances"), "likelihood-parity input")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("unsupported likelihood-parity schema")
    _keys(document["limits"], ("seconds", "scalar_calls", "vectors"), "parity limits")
    for key, maximum in (("seconds", 300), ("scalar_calls", 4096), ("vectors", 32)):
        if type(document["limits"][key]) is not int or not 1 <= document["limits"][key] <= maximum:
            raise ValueError("parity " + key + " outside bound")
    # Tolerances are a prospective numerical contract, never adjusted to results.
    if document["tolerances"] != TOLERANCES:
        raise ValueError("parity requires the declared fixed tolerances")
    if not isinstance(document["grounding"], list):
        raise ValueError("grounding must be byte-bound evidence")
    if not isinstance(document["gradient_vectors"], list) or len(document["gradient_vectors"]) != 2:
        raise ValueError("exactly two predeclared gradient vectors required")
    for row in document["gradient_vectors"]:
        _keys(row, ("label", "parameters", "bounds", "fixed_coordinates", "data"), "gradient vector")
        if not isinstance(row["label"], str) or not row["label"].strip():
            raise ValueError("gradient vector label required")
    if len({row["label"] for row in document["gradient_vectors"]}) != 2:
        raise ValueError("gradient labels must be unique")
    return deepcopy(document)


def _load(task, base):
    from ravel.workflow.science import regular
    from ravel.physics.published_model import _json
    path = regular(validate(task)["input"], base)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("parity document exceeds byte bound")
    return path, validate_document(_json(path.read_bytes()))


def inputs(task, base, *, _session=None):
    """Admission reads bindings only: no model compilation or density evaluation."""
    from ravel.physics import published_model
    path, document = _load(task, base)
    pins = [document[key] for key in ("published_input", "retained_inputs", "compiled_reference", "runtime_inventory")]
    bound = [_pin(pin, path.parent)[0] for pin in [*pins, *document["grounding"]]]
    _, inventory = _pin(document["runtime_inventory"], path.parent)
    runtime = runtime_files(inventory, _session=_session)
    return list(dict.fromkeys([path, *bound, *runtime, *published_model.inputs({"input": str(bound[0])}, path.parent)]))


def _validation_inputs(task, base, session):
    """Private admission hook; numerical run boundaries keep fresh byte reads."""
    return inputs(task, base, _session=session)


def runtime_files(inventory, *, _session=None):
    """The inventory's byte-bound regular files also become supervisor inputs."""
    from ravel.workflow.science import regular
    if inventory.get("schema_version") != 1 or not isinstance(inventory.get("files"), list) or not 1 <= len(inventory["files"]) <= 50000:
        raise ValueError("invalid runtime file inventory")
    files = []
    for pin in inventory["files"]:
        _keys(pin, ("path", "sha256"), "runtime file binding")
        if not Path(pin["path"]).is_absolute():
            raise ValueError("runtime file bindings must be absolute")
        path = regular(pin["path"], ".", _session=_session)
        if _session is not None:
            observed_digest = _session.hash_file(path)
        else:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            observed_digest = digest.hexdigest()
        if observed_digest != pin["sha256"]:
            raise ValueError("runtime bytes differ: " + str(path))
        files.append(path)
    if len(set(files)) != len(files):
        raise ValueError("runtime inventory repeats a file")
    return files


def constraint_layout(model):
    """Snapshot exact auxiliary order and parameter correspondence, not the PDF."""
    rows = []
    for name in model.config.auxdata_order:
        pset = model.config.param_set(name)
        section = model.config.par_map[name]["slice"]
        if not pset.constrained or section.stop - section.start != pset.n_parameters:
            raise ValueError("invalid constrained parameter slice")
        if pset.pdf_type == "normal":
            widths = getattr(pset, "sigmas", [1.0] * pset.n_parameters)
            factors = [1.0] * pset.n_parameters
        elif pset.pdf_type == "poisson":
            widths, factors = [None] * pset.n_parameters, pset.factors
        else:
            raise ValueError("independent density does not support " + pset.pdf_type)
        if len(widths) != pset.n_parameters or len(factors) != pset.n_parameters:
            raise ValueError("invalid auxiliary dimensions")
        for offset, (width, factor) in enumerate(zip(widths, factors)):
            # Compiled pyhf parameter sets may contain NumPy scalar floats.
            # Normalize these runtime values; JSON-supplied values stay strict.
            width = None if width is None else float(width)
            factor = float(factor)
            if width is not None and _number(width, "constraint sigma") <= 0:
                raise ValueError("constraint sigma must be positive")
            if _number(factor, "constraint factor") <= 0:
                raise ValueError("constraint factor must be positive")
            rows.append({"name": name, "parameter_index": section.start + offset,
                         "pdf": pset.pdf_type, "sigma": width, "factor": factor})
    if len(rows) != model.config.nauxdata:
        raise ValueError("auxiliary layout must cover every auxiliary datum")
    return rows


def poisson_twice_nll(observed, mean):
    """Real nonnegative Asimov counts use the same gamma extension as pyhf."""
    observed = _number(observed, "Poisson observation")
    if observed < 0:
        raise ValueError("Poisson observation must be nonnegative")
    if not math.isfinite(mean) or mean < 0:
        return math.nan
    if mean == 0:
        return 0.0 if observed == 0 else math.inf
    return 2.0 * (mean - observed * math.log(mean) + math.lgamma(observed + 1.0))


def scalar_density(main_means, parameters, data, layout):
    """Independent normalized density and independently constructed auxiliaries."""
    if len(data) != len(main_means) + len(layout):
        raise ValueError("density data dimension mismatch")
    main = [poisson_twice_nll(_number(n, "main observation"), float(mean))
            for n, mean in zip(data[:len(main_means)], main_means)]
    auxiliary, expected = [], []
    for row, observed in zip(layout, data[len(main_means):]):
        theta = _number(parameters[row["parameter_index"]], "parameter")
        observed = _number(observed, "auxiliary observation")
        mean = theta * row["factor"]
        expected.append(mean)
        if row["pdf"] == "normal":
            sigma = _number(row["sigma"], "constraint sigma")
            if sigma <= 0:
                raise ValueError("constraint sigma must be positive")
            auxiliary.append(((observed - mean) / sigma) ** 2 + math.log(2 * math.pi) + 2 * math.log(sigma))
        elif row["pdf"] == "poisson":
            auxiliary.append(poisson_twice_nll(observed, mean))
        else:
            raise ValueError("unknown auxiliary distribution")
    return {"twice_nll": math.fsum([*main, *auxiliary]), "main_terms": main,
            "auxiliary_terms": auxiliary, "auxiliary_expected": expected}


def finite_difference(objective, point, bounds, fixed_coordinates, *, step_scale=1e-4):
    """Account for every coordinate; fixed coordinates are the only mask.

    Interior differences are central. Active bounds use second-order one-sided
    differences, at h and h/2. Steps may shrink only for declared bound distance,
    never because a comparison failed. The caller owns the objective-call budget.
    """
    point = [_number(value, "gradient coordinate") for value in point]
    if len(bounds) != len(point):
        raise ValueError("gradient bounds dimension mismatch")
    fixed = {}
    for item in fixed_coordinates:
        if not isinstance(item, (list, tuple)) or len(item) != 2 or type(item[0]) is not int:
            raise ValueError("invalid fixed coordinate")
        index, value = item
        if not 0 <= index < len(point) or index in fixed or point[index] != _number(value, "fixed coordinate"):
            raise ValueError("fixed coordinate differs, repeats or lies outside vector")
        fixed[index] = value
    rows = []
    for i, value in enumerate(point):
        if not isinstance(bounds[i], (list, tuple)) or len(bounds[i]) != 2:
            raise ValueError("invalid gradient bound")
        lower, upper = [_number(x, "gradient bound") for x in bounds[i]]
        if lower >= upper or not lower <= value <= upper:
            raise ValueError("gradient coordinate outside ordered finite bounds")
        if i in fixed:
            rows.append({"index": i, "rule": "fixed", "h": None, "h_gradient": None, "half_gradient": None})
            continue
        step = step_scale * max(1.0, abs(value))
        if value == lower or value == upper:
            direction = 1 if value == lower else -1
            step = min(step, (upper - lower) / 4)
            rule = "forward_second_order" if direction == 1 else "backward_second_order"
        else:
            direction, rule = 0, "central"
            step = min(step, (value - lower) / 2, (upper - value) / 2)
        if step <= 0 or value + step == value or value - step == value:
            raise ValueError("finite-difference step is unrepresentable")
        def at(delta):
            shifted = list(point)
            shifted[i] += delta
            result = float(objective(shifted))
            if not math.isfinite(result):
                raise ValueError("nonfinite independent finite-difference objective")
            return result
        derivatives = []
        for h in (step, step / 2):
            derivatives.append((at(h) - at(-h)) / (2 * h) if direction == 0 else
                               direction * (-3 * at(0) + 4 * at(direction * h) - at(direction * 2 * h)) / (2 * h))
        rows.append({"index": i, "rule": rule, "h": step,
                     "h_gradient": derivatives[0], "half_gradient": derivatives[1]})
    return rows


def compare_gradients(rows, analytic, *, atol=1e-5, rtol=1e-4):
    if len(rows) != len(analytic) or [row["index"] for row in rows] != list(range(len(rows))):
        raise ValueError("gradient comparison must account for every coordinate")
    results = []
    for row, derivative in zip(rows, analytic):
        derivative = _number(derivative, "analytic derivative")
        if row["rule"] == "fixed":
            results.append(dict(row, analytic=derivative, masked=True, passed=True))
            continue
        first, second = row["h_gradient"], row["half_gradient"]
        difference = abs(second - derivative)
        convergence = abs(first - second)
        tolerance = atol + rtol * max(abs(second), abs(derivative))
        results.append(dict(row, analytic=derivative, masked=False, absolute_residual=difference,
                            step_convergence_residual=convergence, tolerance=tolerance,
                            passed=math.isfinite(difference + convergence) and difference <= tolerance and convergence <= tolerance))
    return {"passed": all(row["passed"] for row in results), "coordinates": results}


class Budget:
    def __init__(self, seconds, calls):
        self.started, self.seconds, self.limit, self.calls = time.monotonic(), seconds, calls, 0
        self.categories = {}

    def check(self, category=None):
        if time.monotonic() - self.started > self.seconds:
            raise RuntimeError("parity wall budget exhausted")
        if category is not None:
            if self.calls >= self.limit:
                raise RuntimeError("parity scalar objective budget exhausted")
            self.calls += 1
            self.categories[category] = self.categories.get(category, 0) + 1


def _same_number(left, right, atol, rtol=0):
    if math.isfinite(left) and math.isfinite(right):
        return abs(left - right) <= atol + rtol * max(abs(left), abs(right))
    # An invalid PDF must remain invalid. Its particular NaN/Inf representation
    # is retained; it does not contribute to any maximum finite residual.
    return not math.isfinite(left) and not math.isfinite(right)


def _finite_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        return {"nonfinite": "nan" if math.isnan(value) else ("+inf" if value > 0 else "-inf")}
    if isinstance(value, dict):
        return {key: _finite_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_json(item) for item in value]
    return value


def _thread_snapshot():
    command = ["ps", "-M", "-p", str(os.getpid()), "-o", "pid,utime,stime,pcpu,comm"] if sys.platform == "darwin" else ["ps", "-L", "-p", str(os.getpid()), "-o", "pid,tid,time,pcpu,comm"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
    return {"command": command, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def _vectors(retained, compiled, gradients, limit):
    if retained["parameter_names"] != compiled["parameter_names"] or retained["parameter_order"] != compiled["parameter_order"]:
        raise ValueError("retained parameter order differs from compiled model")
    if retained["model_sha256"] != compiled["model_compact_sha256"] or retained["data_sha256"] != compiled["data_compact_sha256"]:
        raise ValueError("retained model or observed-data digest differs")
    if retained["nominal_parameters"] != compiled["inits"] or retained["source_suggested_fixed"] != compiled["fixed"]:
        raise ValueError("retained nominal or fixed coordinates differ")
    required_fixed = [[index, compiled["inits"][index]] for index, fixed in enumerate(compiled["fixed"]) if fixed]
    for row in gradients:
        if row["fixed_coordinates"] != required_fixed:
            raise ValueError("gradient mask must contain exactly the source-fixed coordinates")
        if row["bounds"] != retained["conditional_probe"]["bounds"] or row["data"] != compiled["observed_and_auxiliary_data"]:
            raise ValueError("gradient bounds/data differ from predeclared retained problem")
        if len(row["parameters"]) != compiled["npars"]:
            raise ValueError("gradient vector dimension differs")
        for index, value in enumerate(row["parameters"]):
            if compiled["fixed"][index]:
                if value != compiled["inits"][index]:
                    raise ValueError("gradient vector changes a source-fixed coordinate")
            elif not row["bounds"][index][0] < _number(value, "gradient coordinate") < row["bounds"][index][1]:
                raise ValueError("predeclared gradient vectors must be interior in every free coordinate")
    records = [{"label": "nominal", "parameters": compiled["inits"], "data": compiled["observed_and_auxiliary_data"], "bounds": compiled["bounds"]}]
    for row in retained["saved_fixed_vector_references"]:
        if row["data_role"] not in ("observed", "saved_asimov"):
            raise ValueError("unknown retained data role")
        expected = compiled["observed_and_auxiliary_data"] if row["data_role"] == "observed" else row["generating_asimov_data"]
        if row["data"] != expected:
            raise ValueError("retained vector data differs from declared observed/Asimov role")
        records.append({"label": f"evaluation-{row['evaluation_index']}-{row['fit_role']}", "parameters": row["parameters"],
                        "data": row["data"], "bounds": row["fit_bounds"]})
    records.extend(deepcopy(gradients))
    if not 1 <= len(records) <= limit or len({row["label"] for row in records}) != len(records):
        raise ValueError("duplicate vectors or vector budget exceeded")
    for row in records:
        if len(row["parameters"]) != compiled["npars"] or len(row["bounds"]) != compiled["npars"] or len(row["data"]) != compiled["nmaindata"] + compiled["nauxdata"]:
            raise ValueError("vector/data/bounds dimensions differ")
        for value, bounds in zip(row["parameters"], row["bounds"]):
            if len(bounds) != 2 or not _number(bounds[0], "lower bound") <= _number(value, "parameter") <= _number(bounds[1], "upper bound"):
                raise ValueError("saved vector outside its declared fit bounds")
        for value in row["data"]:
            _number(value, "vector data")
    return records


def run(task, base, out):
    """Supervised adapter. The caller owns the hard process timeout and approval."""
    from ravel.physics import published_model
    from ravel.workflow.state_io import atomic_json
    path, document = _load(task, base)
    bound = {key: _pin(document[key], path.parent) for key in ("published_input", "retained_inputs", "compiled_reference", "runtime_inventory")}
    for pin in document["grounding"]:
        _pin(pin, path.parent)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError("parity output must be empty; earlier evidence is never overwritten")
    budget = Budget(document["limits"]["seconds"], document["limits"]["scalar_calls"])
    report = {"schema_version": 1, "status": "running", "scope": SCOPE, "physics_validated": False,
              "generated_events": 0, "optimizer_calls": 0, "root_searches": 0,
              "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "tolerances": document["tolerances"],
              "objective_comparisons": [], "gradient_comparisons": [], "timing": {},
              "runtime": {"executable": sys.executable, "python": sys.version, "platform": platform.platform(),
                          "environment": {name: os.environ.get(name) for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "XLA_FLAGS", "JAX_PLATFORMS", "JAX_ENABLE_X64")},
                          "threads_before": _thread_snapshot()},
              "limitations": ["The scalar density shares compiled main means and is not an independent HistFactory interpolation implementation.",
                              "Finite-vector parity does not prove a global minimum, optimizer equivalence or physics validity.",
                              "Thread census includes idle runtime threads; environment settings alone do not establish one active mathematical thread."]}
    def save():
        report["budget"] = {"calls": budget.calls, "categories": budget.categories, "elapsed_seconds": time.monotonic() - budget.started}
        atomic_json(out / "likelihood_parity.json", _finite_json(report))
    save()
    try:
        runtime_files(bound["runtime_inventory"][1])
        report["runtime"]["inventory_before_passed"] = True
        import numpy as np
        import pyhf
        # Import engine before selecting either backend: its module initializer
        # selects NumPy, and no initializer may reset the requested JAX phase.
        from ravel.physics import pyhf_exclude as engine
        for name in ("numpy", "scipy", "pyhf", "jax", "jaxlib", "iminuit"):
            report["runtime"][name] = importlib.metadata.version(name)
        published_path, published = bound["published_input"]
        contract = published_model.load_published_model(published, published_path.parent)
        reference, representation = compiled_reference_identity(bound["compiled_reference"][1])
        report["compiled_reference_data_representation"] = representation
        save()
        retained = bound["retained_inputs"][1]
        numpy_results, differences = {}, {}
        compiled_numpy = layout_numpy = None
        for backend in ("numpy", "jax"):
            budget.check()
            started = time.monotonic()
            pyhf.set_backend(backend, precision="64b")
            model, data, compiled = published_model.compile_published_model(contract)
            compiled = compiled_json_identity(compiled)
            for key in ("modifier_settings", "measurement", "parameter_order", "channel_order", "channel_slices", "sample_order", "nmaindata", "parameter_names", "bounds", "inits", "fixed", "npars", "nauxdata", "auxdata", "constraints", "observed_and_auxiliary_data", "model_compact_sha256", "data_compact_sha256"):
                if compiled[key] != reference[key]:
                    raise ValueError("compiled reference differs: " + key)
            layout = constraint_layout(model)
            report["timing"][backend + "_model_compile_seconds"] = time.monotonic() - started
            records = _vectors(retained, compiled, document["gradient_vectors"], document["limits"]["vectors"])
            if backend == "numpy":
                compiled_numpy, layout_numpy = compiled, layout
                report["compiled_identity"] = {"model_sha256": compiled["model_compact_sha256"], "data_sha256": compiled["data_compact_sha256"],
                                                "parameter_names": compiled["parameter_names"], "auxiliary_layout": layout, "vectors": records}
            elif compiled != compiled_numpy or layout != layout_numpy:
                raise ValueError("NumPy/JAX compiled identities or auxiliary layouts differ")
            if backend == "jax":
                import jax
                import jax.numpy as jnp
                if not jax.config.x64_enabled or any(device.platform != "cpu" for device in jax.devices()):
                    raise ValueError("parity requires float64 CPU JAX")
                report["runtime"]["jax_devices"] = [str(device) for device in jax.devices()]
                def raw_nll(parameters, observations):
                    return pyhf.infer.mle.twice_nll(parameters, observations, model)[0]
                gradient_function = jax.jit(jax.value_and_grad(raw_nll))
            for index, row in enumerate(records):
                budget.check()
                started = time.monotonic()
                tensor = pyhf.tensorlib.astensor(row["parameters"])
                expected = np.asarray(model.expected_data(tensor), dtype=float).tolist()
                budget.check(backend + "_pyhf_density")
                nll = float(np.asarray(pyhf.infer.mle.twice_nll(tensor, row["data"], model)).reshape(-1)[0])
                budget.check(backend + "_independent_density")
                independent = scalar_density(expected[:model.config.nmaindata], row["parameters"], row["data"], layout)
                aux = independent["auxiliary_expected"]
                passed = _same_number(nll, independent["twice_nll"], TOLERANCES["twice_nll_atol"]) and all(
                    _same_number(a, b, TOLERANCES["expected_atol"], TOLERANCES["expected_rtol"]) for a, b in zip(expected[model.config.nmaindata:], aux))
                result = {"label": row["label"], "backend": backend, "expected": expected, "twice_nll": nll,
                          "independent": independent, "passed": passed, "seconds": time.monotonic() - started}
                if backend == "numpy":
                    numpy_results[row["label"]] = result
                else:
                    previous = numpy_results[row["label"]]
                    result["backend_nll_absolute_residual"] = abs(nll - previous["twice_nll"])
                    result["backend_expected_absolute_residuals"] = [abs(a - b) for a, b in zip(expected, previous["expected"])]
                    result["passed"] &= _same_number(nll, previous["twice_nll"], TOLERANCES["twice_nll_atol"]) and all(
                        _same_number(a, b, TOLERANCES["expected_atol"], TOLERANCES["expected_rtol"]) for a, b in zip(expected, previous["expected"]))
                report["objective_comparisons"].append(result)
                save()
                if not result["passed"]:
                    raise ValueError("objective or expected-value parity failed at " + row["label"])
            for row in document["gradient_vectors"]:
                started = time.monotonic()
                if backend == "numpy":
                    def independent_objective(point):
                        budget.check("finite_difference_independent_density")
                        means = np.asarray(model.expected_actualdata(point), dtype=float).tolist()
                        return scalar_density(means, point, row["data"], layout)["twice_nll"]
                    differences[row["label"]] = finite_difference(independent_objective, row["parameters"], row["bounds"], row["fixed_coordinates"])
                    report["timing"][row["label"] + "_finite_difference_seconds"] = time.monotonic() - started
                    report.setdefault("finite_differences", {})[row["label"]] = differences[row["label"]]
                    save()
                else:
                    budget.check("jax_value_and_gradient")
                    value, gradient = gradient_function(jnp.asarray(row["parameters"], dtype=jnp.float64), jnp.asarray(row["data"], dtype=jnp.float64))
                    value.block_until_ready()
                    gradient.block_until_ready()
                    elapsed = time.monotonic() - started
                    comparison = compare_gradients(differences[row["label"]], np.asarray(gradient).tolist())
                    comparison.update(label=row["label"], twice_nll=float(value), seconds=elapsed,
                                      includes_first_jit_compile=len(report["gradient_comparisons"]) == 0,
                                      projected_gradient_max=engine.robust_optimizer.projected_gradient(row["parameters"], np.asarray(gradient), row["bounds"], row["fixed_coordinates"]))
                    comparison["passed"] &= _same_number(float(value), numpy_results[row["label"]]["independent"]["twice_nll"], TOLERANCES["twice_nll_atol"])
                    report["gradient_comparisons"].append(comparison)
                    save()
                    if not comparison["passed"]:
                        raise ValueError("gradient parity or h/h2 convergence failed at " + row["label"])
            report["runtime"]["threads_after_" + backend] = _thread_snapshot()
        budget.check()
        runtime_files(bound["runtime_inventory"][1])
        report["runtime"]["inventory_after_passed"] = True
        budget.check()
        report["status"] = "passed"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        report["runtime"]["threads_final"] = _thread_snapshot()
        save()
    return {"status": report["status"], "physics_validated": False, "scope": SCOPE,
            "generated_events": 0, "optimizer_calls": 0, "root_searches": 0,
            "report": "likelihood_parity.json", "error": report.get("error")}
