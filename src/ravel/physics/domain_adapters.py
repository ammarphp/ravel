"""Bounded supplied-artifact physics operations. No generation or certification.

``validate``, ``inputs`` and ``run`` are consumed by the supervised workflow.
UFO files are parsed, never imported. Optional ONNX models execute on one CPU
thread only after their complete, self-contained graph has been checked.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
from pathlib import Path


DOMAINS = {"ufo", "eft", "classifier", "llp", "applicability", "efficiency-map"}


def _keys(value, required, optional=(), label="object"):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    missing, extra = set(required) - value.keys(), value.keys() - set(required) - set(optional)
    if missing or extra:
        raise ValueError(f"{label}: missing {sorted(missing)}, unknown {sorted(extra)}")


def _num(value, label, minimum=None, positive=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite numeric")
    if positive and value <= 0 or minimum is not None and value < minimum:
        raise ValueError(f"{label} is outside its allowed range")
    return float(value)


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _names(values, label):
    if not isinstance(values, list) or not values:
        raise ValueError(f"{label} must be a nonempty list")
    for value in values:
        _text(value, label)
    if len(set(values)) != len(values):
        raise ValueError(f"{label} contains duplicate names")
    return values


def _length(value):
    _keys(value, ("value", "unit"), label="length")
    _text(value["unit"], "length unit")
    if value["unit"] not in {"mm", "cm", "m"}:
        raise ValueError("length unit must be mm, cm or m; a lifetime in seconds is not a length")
    return _num(_num(value["value"], "length", positive=True) * {"mm": 1, "cm": 10, "m": 1000}[value["unit"]], "converted length", positive=True)


def validate(spec):
    """Validate the domain task configuration; raise ValueError on any defect."""
    _keys(spec, ("domain", "config"), label="domain task")
    _text(spec["domain"], "domain")
    if spec["domain"] not in DOMAINS:
        raise ValueError(f"domain must be one of {sorted(DOMAINS)}")
    c, domain = spec["config"], spec["domain"]
    required = {
        "ufo": ("model_dir", "parameters", "orders", "benchmarks_file"),
        "eft": ("basis_file", "coefficients", "coefficient_units", "validity", "queries", "atol", "rtol"),
        "classifier": ("model_file", "events_file", "controls_file", "features", "dtype", "input_name", "output_name", "score_index", "threshold", "comparison", "score_range", "atol", "rtol"),
        "llp": ("operation", "events_file", "target_ctau"),
        "applicability": ("family", "data_file"),
        "efficiency-map": ("map_file", "events_file"),
    }[domain]
    optional = {"llp": ("source_ctau", "geometry", "combination")}.get(domain, ())
    _keys(c, required, optional, "config")
    for key, value in c.items():
        if key.endswith("_file") or key == "model_dir":
            _text(value, key)
    if domain in {"eft", "classifier"}:
        _num(c["atol"], "atol", minimum=0)
        _num(c["rtol"], "rtol", minimum=0)
    if domain == "ufo":
        for key in ("parameters", "orders"):
            if not isinstance(c[key], dict) or not c[key]:
                raise ValueError(f"{key} must be a nonempty mapping")
            for name, value in c[key].items():
                _text(name, key)
                _num(value, key)
                if key == "orders" and (not isinstance(value, int) or value < 0):
                    raise ValueError("coupling order powers must be nonnegative integers")
    if domain == "eft":
        names = _names(c["coefficients"], "coefficients")
        if len(names) > 20:
            raise ValueError("at most 20 coefficients per bounded quadratic reconstruction")
        _keys(c["coefficient_units"], names, label="coefficient_units")
        _keys(c["validity"], names, label="validity")
        for name in names:
            _text(c["coefficient_units"][name], "coefficient unit")
            bounds = c["validity"][name]
            if not isinstance(bounds, list) or len(bounds) != 2:
                raise ValueError("each declared validity interval needs two boundaries")
            if _num(bounds[0], "validity low") >= _num(bounds[1], "validity high"):
                raise ValueError("validity bounds must increase")
        if not isinstance(c["queries"], list) or not c["queries"]:
            raise ValueError("queries must be a nonempty list")
        for point in c["queries"]:
            _coefficient_point(point, c)
    if domain == "classifier":
        if not isinstance(c["features"], list) or not c["features"]:
            raise ValueError("features must be nonempty")
        for feature in c["features"]:
            _keys(feature, ("name", "unit", "mean", "scale"), label="feature")
            _text(feature["unit"], "feature unit")
            _num(feature["mean"], "feature mean")
            _num(feature["scale"], "feature scale", positive=True)
        _names([f["name"] for f in c["features"]], "features")
        _text(c["dtype"], "dtype")
        _text(c["comparison"], "comparison")
        if c["dtype"] not in {"float32", "float64"} or c["comparison"] not in {">", ">="}:
            raise ValueError("unsupported classifier dtype or threshold comparison")
        if c["score_index"] is not None and (type(c["score_index"]) is not int or c["score_index"] < 0):
            raise ValueError("score_index must be null or a nonnegative integer")
        for key in ("input_name", "output_name"):
            _text(c[key], key)
        bounds = c["score_range"]
        if not isinstance(bounds, list) or len(bounds) != 2 or _num(bounds[0], "score low") >= _num(bounds[1], "score high"):
            raise ValueError("score_range must be an increasing interval")
        if not bounds[0] <= _num(c["threshold"], "threshold") <= bounds[1]:
            raise ValueError("threshold is outside declared score range")
    if domain == "llp":
        _length(c["target_ctau"])
        _text(c["operation"], "operation")
        if c["operation"] == "reweight":
            if set(c) != set(required) | {"source_ctau"}:
                raise ValueError("reweight requires source_ctau and no geometry/combination")
            _length(c["source_ctau"])
        elif c["operation"] == "decay-probability":
            if set(c) != set(required) | {"geometry", "combination"}:
                raise ValueError("decay-probability requires geometry and combination only")
            _text(c["combination"], "combination")
            if c["combination"] not in {"at-least-one", "all"}:
                raise ValueError("declare an LLP event combination: at-least-one or all")
            _keys(c["geometry"], ("r_min_mm", "r_max_mm", "z_half_mm"), label="geometry")
            g = c["geometry"]
            if _num(g["r_min_mm"], "r_min_mm", minimum=0) >= _num(g["r_max_mm"], "r_max_mm", positive=True):
                raise ValueError("cylinder radii must increase")
            _num(g["z_half_mm"], "z_half_mm", positive=True)
        else:
            raise ValueError("unsupported LLP operation")
    if domain == "applicability":
        _text(c["family"], "family")
        if c["family"] not in {"heavy-ion", "forward", "neutrino"}:
            raise ValueError("unsupported applicability family")


def _path(base_dir, name, directory=False):
    path = Path(name)
    path = path if path.is_absolute() else Path(base_dir) / path
    # Reject links in every component, not just the leaf, before resolving it.
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError(f"symlink input is forbidden: {component}")
    if directory and not path.is_dir() or not directory and not path.is_file():
        raise ValueError(f"input not found or wrong type: {path}")
    return path.resolve()


def inputs(spec, base_dir):
    """Enumerate every consumed artifact, including all files in a UFO directory."""
    validate(spec)
    c = spec["config"]
    files = [_path(base_dir, value) for key, value in c.items() if key.endswith("_file")]
    if "model_dir" in c:
        directory = _path(base_dir, c["model_dir"], directory=True)
        for item in sorted(directory.rglob("*")):
            if item.is_symlink():
                raise ValueError(f"symlink in UFO directory: {item}")
            if item.is_file():
                files.append(item)
        if not files:
            raise ValueError("empty UFO directory")
    return sorted(set(files))


def _json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key}")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError(f"nonfinite JSON constant {value}")
    return json.loads(Path(path).read_text(), object_pairs_hook=unique, parse_constant=invalid)


def _fingerprint(path):
    return {"path": str(path), "size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _numpy():
    try:
        import numpy
    except ImportError as exc:
        raise ValueError("this operation requires numpy; install ravel-hep[replay]") from exc
    return numpy


def _close(actual, expected, atol, rtol):
    return abs(actual - expected) <= atol + rtol * abs(expected)


def _ufo(c, base):
    directory = _path(base, c["model_dir"], directory=True)
    required = {"particles.py", "parameters.py", "couplings.py", "coupling_orders.py", "vertices.py", "lorentz.py", "object_library.py", "__init__.py"}
    missing = required - {p.name for p in directory.iterdir() if p.is_file()}
    if missing:
        raise ValueError(f"missing UFO files: {sorted(missing)}")
    constructors = {"Parameter": [], "Particle": [], "Coupling": [], "CouplingOrder": [], "Vertex": []}
    for filename in sorted(directory.rglob("*.py")):
        try:
            tree = ast.parse(filename.read_text(), filename=str(filename))
        except SyntaxError as exc:
            raise ValueError(f"invalid Python syntax in {filename.name}") from exc
        for stmt in tree.body:
            value = stmt.value if isinstance(stmt, (ast.Assign, ast.AnnAssign)) else None
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in constructors:
                data = {}
                for keyword in value.keywords:
                    if keyword.arg is None:
                        raise ValueError("dynamic UFO constructor arguments cannot be statically checked")
                    try:
                        data[keyword.arg] = ast.literal_eval(keyword.value)
                    except (ValueError, TypeError):
                        data[keyword.arg] = {"expression": ast.unparse(keyword.value)}
                constructors[value.func.id].append(data)
    index = {}
    for kind, rows in constructors.items():
        if not rows:
            raise ValueError(f"no statically identifiable {kind} objects")
        names = [r.get("name") for r in rows]
        _names(names, kind)
        index[kind] = dict(zip(names, rows))
    external, addresses = {}, set()
    for name, parameter in index["Parameter"].items():
        if parameter.get("nature") not in {"internal", "external"}:
            raise ValueError(f"parameter {name} has unrecognized nature")
        if parameter.get("nature") == "external":
            _num(parameter.get("value"), f"external parameter {name}")
            block, code = parameter.get("lhablock"), parameter.get("lhacode")
            _text(block, f"LHA block for {name}")
            if not isinstance(code, list) or not code or any(type(i) is not int for i in code):
                raise ValueError(f"invalid LHA code for {name}")
            address = (block.upper(), tuple(code))
            if address in addresses:
                raise ValueError(f"duplicate external LHA address {address}")
            addresses.add(address)
            external[name] = parameter["value"]
    for name, requested in c["parameters"].items():
        if name not in external:
            raise ValueError(f"declared parameter {name} is not a static external parameter")
    orders = index["CouplingOrder"]
    for name, order in orders.items():
        for key in ("expansion_order", "hierarchy"):
            if type(order.get(key)) is not int or order[key] < 0:
                raise ValueError(f"invalid {key} for coupling order {name}")
    for name, power in c["orders"].items():
        if name not in orders or power > orders[name]["expansion_order"]:
            raise ValueError(f"unsupported declared coupling order {name}={power}")
    for name, coupling in index["Coupling"].items():
        powers = coupling.get("order")
        if not isinstance(powers, dict) or any(k not in orders or type(v) is not int or v < 0 for k, v in powers.items()):
            raise ValueError(f"undeclared or nonstatic coupling order in {name}")
    pdgs = []
    for name, particle in index["Particle"].items():
        pdg = particle.get("pdg_code")
        if type(pdg) is not int or not pdg or pdg in pdgs:
            raise ValueError(f"invalid or duplicate explicit particle PDG code {pdg}")
        pdgs.append(pdg)
        for key in ("mass", "width"):
            ref = particle.get(key)
            if not isinstance(ref, dict) or set(ref) != {"expression"} or ref["expression"].split(".")[-1] not in index["Parameter"]:
                raise ValueError(f"unresolved {key} parameter for {name}")
    benchmarks = _json(_path(base, c["benchmarks_file"]))
    _keys(benchmarks, ("model_parameters", "coupling_orders", "checks"), label="UFO benchmarks")
    _keys(benchmarks["model_parameters"], c["parameters"], label="benchmark parameters")
    _keys(benchmarks["coupling_orders"], c["orders"], label="benchmark orders")
    for name, value in benchmarks["model_parameters"].items():
        _num(value, f"benchmark parameter {name}")
    for value in benchmarks["coupling_orders"].values():
        if type(value) is not int or value < 0:
            raise ValueError("benchmark coupling orders must be nonnegative integers")
    if benchmarks["model_parameters"] != c["parameters"] or benchmarks["coupling_orders"] != c["orders"]:
        raise ValueError("benchmark recipe differs from the declared parameter/order point")
    if not isinstance(benchmarks["checks"], list) or not benchmarks["checks"]:
        raise ValueError("supply independent numeric model benchmark checks")
    checks = []
    for check in benchmarks["checks"]:
        _keys(check, ("name", "actual", "reference", "unit", "atol", "rtol", "source"), label="model benchmark")
        for key in ("name", "unit", "source"):
            _text(check[key], key)
        for key in ("actual", "reference", "atol", "rtol"):
            _num(check[key], key, minimum=0 if key in {"atol", "rtol"} else None)
        checks.append({**check, "passed": _close(check["actual"], check["reference"], check["atol"], check["rtol"])})
    return {"counts": {k: len(v) for k, v in constructors.items()}, "external_defaults": external,
            "declared_parameters": c["parameters"], "declared_orders": c["orders"], "benchmarks": checks,
            "checks_passed": all(x["passed"] for x in checks)}, [
        "Static UFO structure and supplied benchmark arithmetic only; no model code imported or FeynRules executed.",
        "Dynamic anti-particles, expression values, vertices, gauge identities and actual generator parameter application are not validated.",
        "Benchmark values and source identifiers are supplied evidence, not independent recomputation or proof of reference provenance."]


def _coefficient_point(point, c):
    _keys(point, c["coefficients"], label="coefficient point")
    values = []
    for name in c["coefficients"]:
        value = _num(point[name], name)
        low, high = c["validity"][name]
        if not low <= value <= high:
            raise ValueError(f"{name} is outside declared EFT validity")
        values.append(value)
    return values


def _design(values):
    return [1.0, *values, *(values[i] * values[j] for i in range(len(values)) for j in range(i, len(values)))]


def _eft(c, base):
    np = _numpy()
    data = _json(_path(base, c["basis_file"]))
    _keys(data, ("coefficient_units", "prediction_unit", "bins", "samples", "controls", "source"), label="EFT basis")
    if data["coefficient_units"] != c["coefficient_units"]:
        raise ValueError("EFT coefficient units do not match")
    _text(data["prediction_unit"], "prediction unit")
    _text(data["source"], "EFT source")
    bins = _names(data["bins"], "bins")
    def rows(kind):
        if not isinstance(data[kind], list) or not data[kind]:
            raise ValueError(f"EFT {kind} must be nonempty")
        points, yields = [], []
        for row in data[kind]:
            _keys(row, ("point", "values"), label=f"EFT {kind} row")
            points.append(_coefficient_point(row["point"], c))
            if not isinstance(row["values"], list) or len(row["values"]) != len(bins):
                raise ValueError("EFT prediction bin count mismatch")
            yields.append([_num(x, "EFT prediction") for x in row["values"]])
        if len(set(map(tuple, points))) != len(points):
            raise ValueError(f"duplicate EFT points in {kind}")
        return points, np.asarray(yields, dtype=float)
    points, y = rows("samples")
    control_points, control_y = rows("controls")
    if set(map(tuple, points)) & set(map(tuple, control_points)):
        raise ValueError("EFT controls must be independent coefficient points")
    x = np.asarray([_design(point) for point in points])
    matrix, _, rank, singular = np.linalg.lstsq(x, y, rcond=None)
    if rank != x.shape[1]:
        raise ValueError("EFT sample design does not identify every interference/quadratic coefficient")
    condition = float(singular[0] / singular[-1])
    if not math.isfinite(condition) or condition > 1e10:
        raise ValueError("EFT basis is ill-conditioned; rescale coefficient coordinates")
    reconstructed, control_pred = x @ matrix, np.asarray([_design(p) for p in control_points]) @ matrix
    fit_passed = bool(np.all(np.abs(reconstructed-y) <= c["atol"] + c["rtol"] * np.abs(y)))
    control_passed = bool(np.all(np.abs(control_pred-control_y) <= c["atol"] + c["rtol"] * np.abs(control_y)))
    n = len(c["coefficients"])
    predictions = []
    for query in c["queries"]:
        basis = np.asarray(_design(_coefficient_point(query, c)))
        terms = matrix * basis[:, None]
        total = terms.sum(axis=0)
        predictions.append({"point": query, "sm": terms[0].tolist(), "linear_interference": terms[1:n+1].sum(axis=0).tolist(),
                            "quadratic_and_mixed": terms[n+1:].sum(axis=0).tolist(), "total": total.tolist(),
                            "nonnegative_for_poisson": bool(np.all(total >= 0))})
    if not np.isfinite(matrix).all() or any(not math.isfinite(v) for p in predictions for v in p["total"]):
        raise ValueError("nonfinite EFT reconstruction")
    names = ["SM", *c["coefficients"], *(f"{c['coefficients'][i]}*{c['coefficients'][j]}" for i in range(n) for j in range(i,n))]
    return {"basis_terms": names, "bin_names": bins, "prediction_unit": data["prediction_unit"], "coefficients_by_term": matrix.tolist(),
            "condition_number": condition, "fit_residual_max": float(np.max(np.abs(reconstructed-y))),
            "control_predictions": control_pred.tolist(), "control_references": control_y.tolist(),
            "fit_passed": fit_passed, "control_passed": control_passed, "checks_passed": fit_passed and control_passed,
            "predictions": predictions, "clipping_applied": False}, [
        "Exact quadratic dependence is assumed; truncation, scale validity and missing higher operators require physics review.",
        "Signed interference and negative totals are retained; negative totals cannot become Poisson means.",
        "No Monte Carlo covariance or coefficient uncertainty is inferred from central-value samples."]


def _classifier(c, base):
    np = _numpy()
    try:
        import onnx
        import onnxruntime as ort
    except ImportError as exc:
        raise ValueError("classifier execution requires optional onnx and onnxruntime packages") from exc
    model = _path(base, c["model_file"])
    model_bytes = model.read_bytes()
    proto = onnx.load_model_from_string(model_bytes)
    # Inspect all protobuf messages, including nested graphs and sparse tensors.
    def check_message(message):
        if message.DESCRIPTOR.full_name == "onnx.TensorProto" and (message.data_location == onnx.TensorProto.EXTERNAL or message.external_data):
            raise ValueError("ONNX external tensor data is not admitted; supply a self-contained model")
        if message.DESCRIPTOR.full_name == "onnx.NodeProto" and message.domain not in {"", "ai.onnx", "ai.onnx.ml"}:
            raise ValueError("custom ONNX operator domains are not admitted")
        for field, value in message.ListFields():
            if field.message_type is not None:
                if field.is_repeated:
                    for item in value:
                        check_message(item)
                else:
                    check_message(value)
    check_message(proto)
    onnx.checker.check_model(proto)
    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    session = ort.InferenceSession(model_bytes, sess_options=options, providers=["CPUExecutionProvider"])
    metadata = session.get_inputs()
    expected_type = {"float32": "tensor(float)", "float64": "tensor(double)"}[c["dtype"]]
    if len(metadata) != 1 or metadata[0].name != c["input_name"] or metadata[0].type != expected_type:
        raise ValueError("ONNX input name/count/dtype differs from the feature contract")
    shape = metadata[0].shape
    if len(shape) != 2 or isinstance(shape[1], int) and shape[1] != len(c["features"]):
        raise ValueError("ONNX input must be [batch, declared feature count]")
    if c["output_name"] not in [o.name for o in session.get_outputs()]:
        raise ValueError("ONNX output name does not exist")
    names = [f["name"] for f in c["features"]]
    def infer(file, controls=False):
        data = _json(_path(base, file))
        _keys(data, ("units", "events", "expected_scores") if controls else ("units", "events"), label="classifier data")
        if data["units"] != {f["name"]: f["unit"] for f in c["features"]}:
            raise ValueError("classifier feature units differ")
        if not isinstance(data["events"], list) or not data["events"]:
            raise ValueError("classifier events must be nonempty")
        vectors, ids, weights = [], [], []
        for row in data["events"]:
            _keys(row, ("event_id", "values", "weight"), label="classifier event")
            _text(row["event_id"], "event_id")
            _keys(row["values"], names, label="feature values")
            ids.append(row["event_id"])
            weights.append(_num(row["weight"], "event weight"))
            vectors.append([(_num(row["values"][f["name"]], f["name"])-f["mean"])/f["scale"] for f in c["features"]])
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate classifier event identities")
        matrix = np.asarray(vectors, dtype=c["dtype"])
        if not np.isfinite(matrix).all():
            raise ValueError("feature normalization/cast overflow")
        if isinstance(shape[0], int) and shape[0] != len(matrix):
            raise ValueError("ONNX static batch size differs from supplied data")
        output = np.asarray(session.run([c["output_name"]], {c["input_name"]: matrix})[0])
        if c["score_index"] is None:
            if output.shape != (len(matrix),):
                raise ValueError("null score_index requires a vector output")
            scores = output
        else:
            if output.ndim != 2 or output.shape[0] != len(matrix) or output.shape[1] <= c["score_index"]:
                raise ValueError("classifier score_index/output shape mismatch")
            scores = output[:, c["score_index"]]
        if not np.isfinite(scores).all() or np.any(scores < c["score_range"][0]) or np.any(scores > c["score_range"][1]):
            raise ValueError("classifier scores are nonfinite or outside declared range")
        passed = scores > c["threshold"] if c["comparison"] == ">" else scores >= c["threshold"]
        result = [{"event_id": ident, "score": float(score), "selected": bool(p), "weight": weight} for ident, score, p, weight in zip(ids,scores,passed,weights)]
        if controls:
            expected = data["expected_scores"]
            if not isinstance(expected, list) or len(expected) != len(scores):
                raise ValueError("control score count differs")
            return result, all(_close(float(s), _num(e,"expected score"), c["atol"], c["rtol"]) for s,e in zip(scores,expected))
        return result
    control_rows, passed = infer(c["controls_file"], True)
    rows = infer(c["events_file"])
    selected_weights = [r["weight"] for r in rows if r["selected"]]
    return {"events": rows, "controls": control_rows, "checks_passed": passed, "selected_sumw": math.fsum(selected_weights),
            "selected_sumw2": math.fsum(w*w for w in selected_weights), "runtime": ort.__version__, "provider": "CPUExecutionProvider"}, [
        "Classifier inference and supplied reference scores only; no training, calibration, domain-shift or analysis-efficiency certification.",
        "Feature ordering, units and affine preprocessing are explicit; nonlinear preprocessing must be in the supplied graph."]


def _events(data, label):
    if not isinstance(data, list) or not data:
        raise ValueError(f"{label} events must be a nonempty list")
    ids = []
    for event in data:
        if not isinstance(event, dict):
            raise ValueError("event must be an object")
        ids.append(_text(event.get("event_id"), "event_id"))
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate event identities")
    return data


def _llp(c, base):
    events = _events(_json(_path(base, c["events_file"])), "LLP")
    target = _length(c["target_ctau"])
    rows = []
    for event in events:
        _keys(event, ("event_id", "weight", "particles"), label="LLP event")
        weight = _num(event["weight"], "weight")
        if not isinstance(event["particles"], list) or not event["particles"]:
            raise ValueError("LLP particles must be nonempty")
        values, log_ratio = [], 0.0
        for particle in event["particles"]:
            if c["operation"] == "reweight":
                _keys(particle, ("proper_length_mm", "right_censored"), label="LLP reweight particle")
                length = _num(particle["proper_length_mm"], "proper_length_mm", minimum=0)
                if type(particle["right_censored"]) is not bool:
                    raise ValueError("right_censored must be a boolean")
                source = _length(c["source_ctau"])
                log_ratio += length * (1/source - 1/target)
                if not particle["right_censored"]:
                    log_ratio += math.log(source/target)
            else:
                _keys(particle, ("px_GeV", "py_GeV", "pz_GeV", "mass_GeV"), label="LLP momentum")
                px, py, pz = (_num(particle[k], k) for k in ("px_GeV", "py_GeV", "pz_GeV"))
                mass = _num(particle["mass_GeV"], "mass_GeV", positive=True)
                pt, momentum = math.hypot(px,py), math.hypot(px,py,pz)
                g = c["geometry"]
                if momentum == 0:
                    probability = 1.0 if g["r_min_mm"] == 0 else 0.0
                elif pt == 0 and g["r_min_mm"] > 0:
                    probability = 0.0
                else:
                    # Convert path geometry to proper lengths directly: L/(beta gamma).
                    lo = g["r_min_mm"] * mass / pt if pt else 0.0
                    hi = min(g["r_max_mm"] * mass / pt if pt else math.inf,
                             g["z_half_mm"] * mass / abs(pz) if pz else math.inf)
                    probability = 0.0 if hi <= lo else math.exp(-lo/target) * (-math.expm1(-(hi-lo)/target))
                values.append(probability)
        if c["operation"] == "reweight":
            if not math.isfinite(log_ratio) or log_ratio > 700 or log_ratio < -700:
                raise ValueError("lifetime reweighting is numerically unstable; no clipping or silent underflow allowed")
            factor = math.exp(log_ratio)
        elif c["combination"] == "all":
            factor = math.prod(values)
        else:
            factor = 1.0 if any(v == 1 for v in values) else -math.expm1(math.fsum(math.log1p(-v) for v in values))
        rows.append({"event_id": event["event_id"], "factor": factor, "weighted_contribution": weight*factor,
                     "per_particle_probabilities": values, "log_reweight": log_ratio if c["operation"] == "reweight" else None})
    contributions = [r["weighted_contribution"] for r in rows]
    return {"events": rows, "sumw": math.fsum(contributions), "sumw2": math.fsum(w*w for w in contributions),
            "checks_passed": True}, [
        "Prompt production at the cylinder origin, straight-line vacuum propagation and independent exponential decays are assumed for geometry.",
        "Reweighting assumes identical production and independent, untruncated exponential proper lengths; right-censoring uses survival ratios.",
        "No detector efficiency, branching fraction, absolute exposure normalization or validity of a new lifetime point is inferred."]


def _applicability(c, base):
    d = _json(_path(base, c["data_file"]))
    family = c["family"]
    if family == "neutrino":
        _keys(d, ("flavor_pdg", "target", "target_basis", "n_targets", "flux_unit", "cross_section_unit", "flux_exposure", "cross_section_averaging", "bins", "source"), label="neutrino inputs")
        if type(d["flavor_pdg"]) is not int or d["flavor_pdg"] not in {-16,-14,-12,12,14,16}:
            raise ValueError("declare one neutrino/antineutrino flavor per fold")
        _text(d["target_basis"], "target basis")
        if d["target_basis"] not in {"nucleon", "nucleus", "electron"}:
            raise ValueError("declare cross section and target count on the same target basis")
        if d["flux_unit"] != "cm^-2/bin" or d["cross_section_unit"] != f"cm^2/{d['target_basis']}" or d["flux_exposure"] != "integrated" or d["cross_section_averaging"] != "flux-weighted-per-bin":
            raise ValueError("neutrino fold requires integrated bin flux and matching flux-weighted cross sections")
        _text(d["target"], "target material")
        _text(d["source"], "flux and cross section source")
        targets = _num(d["n_targets"], "n_targets", positive=True)
        if not isinstance(d["bins"], list) or not d["bins"]:
            raise ValueError("neutrino bins must be nonempty")
        rows, previous = [], -math.inf
        for row in d["bins"]:
            _keys(row, ("energy_low_GeV", "energy_high_GeV", "flux", "cross_section", "efficiency"), label="neutrino bin")
            lo, hi = _num(row["energy_low_GeV"], "energy low", minimum=0), _num(row["energy_high_GeV"], "energy high", positive=True)
            if lo < previous or hi <= lo:
                raise ValueError("neutrino bins must be ordered and nonoverlapping")
            previous = hi
            flux, xs = _num(row["flux"], "flux", minimum=0), _num(row["cross_section"], "cross section", minimum=0)
            efficiency = _num(row["efficiency"], "efficiency", minimum=0)
            if efficiency > 1:
                raise ValueError("efficiency must be a fraction, not percent")
            rows.append({**row, "expected_events": flux * xs * targets * efficiency})
        result = {"bins": rows, "expected_events": math.fsum(r["expected_events"] for r in rows)}
        limitations = ["Supplied thin-target integrated flux and flux-weighted cross-section fold only; no flux generation, oscillation, nuclear model, energy migration or uncertainty propagation."]
    elif family == "heavy-ion":
        _keys(d, ("beam_mass_numbers", "sqrt_sNN_GeV", "centrality_percent", "centrality_definition", "event_exposure", "observable_unit", "bins", "source"), label="nuclear inputs")
        beams = d["beam_mass_numbers"]
        if not isinstance(beams, list) or len(beams) != 2 or any(type(a) is not int or a < 1 for a in beams) or max(beams) == 1:
            raise ValueError("nuclear normalization requires explicit nuclear beam mass numbers")
        _num(d["sqrt_sNN_GeV"], "sqrt_sNN_GeV", positive=True)
        centrality = d["centrality_percent"]
        if not isinstance(centrality, list) or len(centrality) != 2 or not 0 <= _num(centrality[0],"centrality") < _num(centrality[1],"centrality") <= 100:
            raise ValueError("invalid centrality percentile interval")
        for key in ("centrality_definition", "observable_unit", "source"):
            _text(d[key], key)
        exposure = _num(d["event_exposure"], "event_exposure", positive=True)
        if not isinstance(d["bins"], list) or not d["bins"]:
            raise ValueError("nuclear bins must be nonempty")
        rows, previous = [], -math.inf
        for row in d["bins"]:
            _keys(row, ("low", "high", "sumw", "sumw2"), label="nuclear bin")
            lo, hi = _num(row["low"],"low"), _num(row["high"],"high")
            if lo < previous or hi <= lo:
                raise ValueError("nuclear bins must be ordered and nonoverlapping")
            previous = hi
            sumw, sumw2 = _num(row["sumw"],"sumw"), _num(row["sumw2"],"sumw2",minimum=0)
            if sumw2 == 0 and sumw != 0:
                raise ValueError("nonzero bin sumw with zero sumw2 is inconsistent")
            scale = exposure * (hi-lo)
            rows.append({**row, "per_event_density": sumw/scale, "conditional_variance": sumw2/scale**2})
        result = {"bins": rows, "density_unit": f"1/{d['observable_unit']}"}
        limitations = ["Supplied selected-event exposure and fixed-denominator weighted-bin errors only; no centrality calibration, nuclear generator, event-exposure uncertainty, nuclear PDF or R_AA reference is inferred."]
    else:
        _keys(d, ("plane_z_mm", "radius_mm", "transport", "events", "source"), label="forward inputs")
        plane, radius = _num(d["plane_z_mm"],"plane_z_mm"), _num(d["radius_mm"],"radius_mm",positive=True)
        if d["transport"] != "neutral-straight-line-vacuum":
            raise ValueError("only neutral straight-line vacuum transport is implemented")
        _text(d["source"], "forward source")
        rows = []
        for event in _events(d["events"], "forward"):
            _keys(event, ("event_id", "weight", "x_mm", "y_mm", "z_mm", "px_GeV", "py_GeV", "pz_GeV", "charge"), label="forward event")
            for key in event.keys() - {"event_id"}:
                _num(event[key],key)
            if event["charge"] != 0:
                raise ValueError("charged-particle forward transport requires magnetic/optics machinery")
            dz = plane-event["z_mm"]
            reaches = event["pz_GeV"] != 0 and dz/event["pz_GeV"] > 0
            x = event["x_mm"] + event["px_GeV"]*dz/event["pz_GeV"] if reaches else None
            y = event["y_mm"] + event["py_GeV"]*dz/event["pz_GeV"] if reaches else None
            selected = reaches and math.hypot(x,y) <= radius
            rows.append({"event_id":event["event_id"], "x_at_plane_mm":x, "y_at_plane_mm":y, "selected":selected, "contribution":event["weight"] if selected else 0.0})
        weights = [r["contribution"] for r in rows]
        result = {"events":rows, "selected_sumw":math.fsum(weights), "selected_sumw2":math.fsum(w*w for w in weights)}
        limitations = ["Geometric neutral single-particle acceptance only; no beam optics, material, interactions, magnetic field or detector efficiency is inferred."]
    return {"family":family, **result, "checks_passed":True}, limitations


def _efficiency_map(c, base):
    """Fold exact-node event probabilities; keep MC and map uncertainty separate."""
    np = _numpy()
    grid = _json(_path(base, c["map_file"]))
    data = _json(_path(base, c["events_file"]))
    _keys(grid, ("map_id", "topology", "coordinate_units", "response_kind", "nodes", "uncertainty", "source"), label="efficiency map")
    _keys(data, ("map_id", "topology", "coordinate_units", "node_semantics", "weight_unit", "source", "events"), label="map events")
    for document in (grid, data):
        for key in ("map_id", "topology", "source"):
            _text(document[key], key)
    if grid["map_id"] != data["map_id"] or grid["topology"] != data["topology"]:
        raise ValueError("event/map topology or map identity differs")
    units = grid["coordinate_units"]
    if not isinstance(units, dict) or not units:
        raise ValueError("map coordinate units must be an explicit nonempty mapping")
    for name, unit in units.items():
        _text(name, "coordinate name")
        _text(unit, "coordinate unit")
    if data["coordinate_units"] != units:
        raise ValueError("event/map coordinate units differ; implicit conversion is forbidden")
    if grid["response_kind"] != "event-selection-probability":
        raise ValueError("map must declare an event-selection probability, not an object efficiency or cross section")
    _text(data["weight_unit"], "weight unit")
    _text(data["node_semantics"], "node semantics")
    if data["node_semantics"] not in {"alternative-model-points", "event-kinematics"}:
        raise ValueError("declare alternative-model-points or exclusive event-kinematics node semantics")
    nodes = grid["nodes"]
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 256:
        raise ValueError("supply between 1 and 256 exact map nodes per bounded fold")
    names, coordinates, probabilities = [], [], []
    for node in nodes:
        _keys(node, ("node_id", "coordinates", "efficiency"), label="map node")
        names.append(_text(node["node_id"], "node_id"))
        _keys(node["coordinates"], units, label="map coordinates")
        coordinates.append(tuple(_num(node["coordinates"][k], k) for k in units))
        probability = _num(node["efficiency"], "efficiency", minimum=0)
        if probability > 1:
            raise ValueError("efficiency is a probability fraction, not percent; clipping is forbidden")
        probabilities.append(probability)
    _names(names, "map node IDs")
    if len(set(coordinates)) != len(coordinates):
        raise ValueError("duplicate map coordinates cannot identify distinct response nodes")
    uncertainty = grid["uncertainty"]
    _keys(uncertainty, ("kind", "node_ids", "covariance", "source"), label="map uncertainty")
    _text(uncertainty["source"], "map uncertainty source")
    if uncertainty["kind"] != "absolute-probability-covariance" or uncertainty["node_ids"] != names:
        raise ValueError("map response covariance needs its absolute probability convention and exact node order")
    raw = uncertainty["covariance"]
    if not isinstance(raw, list) or len(raw) != len(nodes) or any(not isinstance(row, list) or len(row) != len(nodes) for row in raw):
        raise ValueError("response covariance dimensions differ from map node count")
    covariance = np.asarray([[_num(v, "response covariance") for v in row] for row in raw])
    if not np.array_equal(covariance, covariance.T):
        raise ValueError("response covariance must be exactly symmetric; no silent symmetrization")
    if np.any(np.diag(covariance) < 0):
        raise ValueError("negative response variance")
    scale = float(np.max(np.diag(covariance)))
    if float(np.linalg.eigvalsh(covariance)[0]) < -1e-12 * scale:
        raise ValueError("response covariance is not positive semidefinite")
    grouped, traces = {}, []
    population = [0 for _ in nodes]
    node_index = {name: index for index, name in enumerate(names)}
    for event in _events(data["events"], "efficiency map"):
        _keys(event, ("event_id", "group_id", "node_id", "coordinates", "weight"), label="map event")
        group = _text(event["group_id"], "independent group identity")
        node_name = _text(event["node_id"], "event node_id")
        if node_name not in node_index:
            raise ValueError(f"uncovered map node {node_name}; no extrapolation or implicit zero efficiency")
        index = node_index[node_name]
        population[index] += 1
        _keys(event["coordinates"], units, label="event coordinates")
        point = tuple(_num(event["coordinates"][k], k) for k in units)
        if point != coordinates[index]:
            raise ValueError("event coordinates are not the exact declared map node; no interpolation")
        weight = _num(event["weight"], "event weight")
        # Keep subevent terms until fsum so cancellation is not order-sensitive.
        terms = grouped.setdefault(group, [[] for _ in nodes])
        terms[index].append(weight)
        traces.append({"event_id":event["event_id"], "group_id":group, "node_id":node_name,
                       "weight":weight, "efficiency":probabilities[index], "contribution":weight*probabilities[index]})
    group_weights = [[math.fsum(terms) for terms in group] for group in grouped.values()]
    sums = [math.fsum(group[j] for group in group_weights) for j in range(len(nodes))]
    moments = np.asarray([[math.fsum(group[i]*group[j] for group in group_weights) for j in range(len(nodes))] for i in range(len(nodes))])
    probabilities = np.asarray(probabilities)
    values = probabilities * sums
    mc = moments * np.outer(probabilities, probabilities)
    response = covariance * np.outer(sums, sums)
    combine = data["node_semantics"] == "event-kinematics"
    mc_total = math.fsum(float(x) for x in mc.flat) if combine else None
    response_total = math.fsum(float(x) for x in response.flat) if combine else None
    if combine and (mc_total < 0 or response_total < 0):
        raise ValueError("negative propagated variance; no clipping of a numerically inconsistent covariance")
    return {"map_id":grid["map_id"], "topology":grid["topology"], "node_ids":names,
            "coordinate_units":units, "weight_unit":data["weight_unit"], "node_semantics":data["node_semantics"], "events":traces,
            "independent_groups":len(grouped), "input_sumw_by_node":sums,
            "input_subevents_by_node":population, "nodes_without_input_events":[names[i] for i,n in enumerate(population) if n == 0],
            "input_group_second_moments":moments.tolist(), "yield_by_node":values.tolist(),
            "total_yield":math.fsum(float(x) for x in values) if combine else None, "conditional_mc_covariance":mc.tolist(),
            "supplied_response_covariance":response.tolist(), "conditional_mc_total_variance":mc_total,
            "supplied_response_total_variance":response_total,
            "nonnegative_for_poisson":bool(np.all(values >= 0)), "interpolation_applied":False,
            "clipping_applied":False, "checks_passed":True}, [
        "Exact supplied topology and node identity only; the physical validity envelope, lifetime, detector response and topology completeness are not established.",
        "The map is an event-selection probability, not a per-object efficiency; no independence, branching ratio, luminosity or cross-section factor is inferred. Alternative model points are never summed into one physical total.",
        "Independent-group Poisson MC moments are conditional on the central map. Response covariance is propagated with fixed supplied event weights. They are reported separately; no missing cross-covariance, mixed term or joint uncertainty model is invented.",
        "Map provenance and uncertainty are supplied declarations, not detector validation. No interpolation, extrapolation, probability clipping or stochastic detector sampling occurs."]


def run(spec, base_dir, output_dir):
    """Execute one admitted supplied-artifact task and retain an honest result."""
    validate(spec)
    files = inputs(spec, base_dir)
    before = [_fingerprint(path) for path in files]
    operation = {"ufo":_ufo, "eft":_eft, "classifier":_classifier, "llp":_llp,
                 "applicability":_applicability, "efficiency-map":_efficiency_map}[spec["domain"]]
    details, limitations = operation(spec["config"], base_dir)
    after = [_fingerprint(path) for path in inputs(spec, base_dir)]
    if before != after:
        raise ValueError("domain input artifacts changed during execution")
    result = {"schema_version":1, "domain":spec["domain"], "status":"passed" if details["checks_passed"] else "failed",
              "physics_validated":False, "details":details, "limitations":limitations, "inputs":before}
    # allow_nan=False also rejects derived overflow before any result is published.
    serialized = json.dumps(result, indent=2, allow_nan=False) + "\n"
    output = Path(output_dir)
    if any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError("symlink output directory is forbidden")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "domain-result.json"
    with destination.open("x") as handle:
        handle.write(serialized)
    return result
