"""Declared single-scalar rate mappings with supplied loop coefficients.

Each production/decay modifier is a squared coupling, a dimensionless
polynomial or a declared loop. Interference signs reside in supplied terms.
The visible width is sum(BR_SM * modifier); the total width divides this by
1 - BR_inv - BR_undet. No omitted decay fractions or loop coefficients are
filled in. A declared vector bound limits the magnitude of each vector
parameter to one. HEFT contact normalizations and all six dictionary entries
are declared by the caller, including the two entries relevant to scalar pairs.
"""
from __future__ import annotations

from functools import lru_cache
import json
import math
from pathlib import Path

from ravel.physics.measurement import _load
from ravel.physics.quantities import _keys, _number, _text
from ravel.physics.supplied_contracts import output_contract, publish


HEFT_KEYS = ("kappa_V", "kappa_F", "c_gg", "c_gammagamma", "kappa_2V", "c_2")


@lru_cache(maxsize=2)
def _validator(name):
    from jsonschema import Draft202012Validator
    path = Path(__file__).parents[1] / "data" / "higgs" / "schemas" / name
    return Draft202012Validator(json.loads(path.read_text()))


def _schema(document, name):
    try:
        json.dumps(document, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError("bundle must contain finite JSON values") from exc
    error = next(_validator(name).iter_errors(document), None)
    if error:
        path = ".".join(map(str, error.absolute_path))
        if error.validator == "exclusiveMinimum" and error.validator_value == 0:
            raise ValueError(f"{name} {path} must be positive")
        raise ValueError(f"{name} {path}: {error.message}")


def _polynomial(record, names):
    for term in record["terms"]:
        _number(term["coefficient"], "polynomial coefficient")
        for name, power in term["powers"].items():
            if name not in names:
                raise ValueError(f"polynomial references unknown parameter {name}")
            if type(power) is not int or power < 0:
                raise ValueError("polynomial powers must be nonnegative integers")


def _poly_value(record, point):
    return math.fsum(term["coefficient"] * math.prod(point[name] ** power
                      for name, power in term["powers"].items()) for term in record["terms"])


def validate_bundle(document):
    """Validate declarations and domain; return a detached JSON document."""
    _schema(document, "parameterization-bundle.json")
    doc = json.loads(json.dumps(document, allow_nan=False))
    names = doc["parameters"]
    if doc["mass_gev"] <= 0:
        raise ValueError("prediction mass must be positive")
    bsm = doc.get("bsm_parameters", {})
    if "combined" in bsm and len(bsm) != 1:
        raise ValueError("combined and split BSM branching fractions cannot coexist")
    if len(set(bsm.values())) != len(bsm):
        raise ValueError("BSM branching fraction parameters must be distinct")
    for name in bsm.values():
        if name not in names:
            raise ValueError("unknown BSM branching fraction parameter")
        if not 0 <= names[name]["initial"] < 1 or not 0 <= names[name]["sm"] < 1:
            raise ValueError("BSM branching fraction must lie in [0,1)")
    if math.fsum(names[n]["initial"] for n in bsm.values()) >= 1:
        raise ValueError("sum of BSM branching fractions must be below one")
    for name, record in names.items():
        lo, hi = record["bounds"]
        if lo is not None and hi is not None and lo >= hi:
            raise ValueError(f"parameter {name} bounds must be ordered")
        for key in ("initial", "sm"):
            value = _number(record[key], f"parameter {name}")
            if (lo is not None and value < lo) or (hi is not None and value > hi):
                raise ValueError(f"parameter {name} {key} is outside bounds")
    vectors = doc.get("vector_parameters", [])
    if len(set(vectors)) != len(vectors) or any(n not in names for n in vectors):
        raise ValueError("vector parameters must be distinct declared parameters")
    if "vector_upper_bound" in doc and not vectors:
        raise ValueError("vector upper bound requires declared vector parameters")
    if "vector_upper_bound" in doc and any(abs(names[n][key]) > 1 for n in vectors for key in ("initial", "sm")):
        raise ValueError("vector parameter magnitude exceeds declared upper bound")
    for key, loop in doc.get("loops", {}).items():
        if loop["mode"] == "effective":
            if loop["parameter"] not in names:
                raise ValueError(f"loop {key} references unknown parameter")
        else:
            _polynomial(loop["polynomial"], names)
    for group in ("production", "decays"):
        for modifier in doc[group].values():
            if "parameter" in modifier and modifier["parameter"] not in names:
                raise ValueError("modifier references unknown parameter")
            if "loop" in modifier and modifier["loop"] not in doc.get("loops", {}):
                raise ValueError("modifier references undeclared loop")
            if "polynomial" in modifier:
                _polynomial(modifier["polynomial"], names)
    fractions = doc["branching_fractions"]
    if set(fractions) != set(doc["decays"]):
        raise ValueError("branching fractions must cover exactly all declared decays")
    if not math.isclose(math.fsum(fractions.values()), 1.0, abs_tol=1e-10, rel_tol=0):
        raise ValueError("SM branching fractions must sum to one; supply every decay")
    ids = [r["id"] for r in doc["rates"]]
    if len(set(ids)) != len(ids):
        raise ValueError("rate ids must be unique")
    for row in doc["rates"]:
        if row["production"] not in doc["production"] or row["decay"] not in doc["decays"]:
            raise ValueError("rate references undeclared production or decay")
        if row["unit"] == "1" and row["sm_value"] != 1:
            raise ValueError("dimensionless signal-strength SM value must be one")
        if "mass_gev" in row and row["mass_gev"] != doc["mass_gev"]:
            raise ValueError("rate mass differs from prediction mass")
        if "convention" in row and row["convention"] != doc["convention"]:
            raise ValueError("mixed prediction order, PDF or branching program")
    if doc["framework"] == "heft-lo":
        if set(doc.get("heft_dictionary", {})) != set(HEFT_KEYS):
            raise ValueError("HEFT requires all six dictionary entries")
        if any(name not in names for name in doc["heft_dictionary"].values()):
            raise ValueError("HEFT dictionary references unknown parameter")
        _text(doc.get("heft_normalization"), "HEFT contact normalization")
    elif "heft_dictionary" in doc or "heft_normalization" in doc:
        raise ValueError("HEFT dictionary requires framework heft-lo")
    evaluator = Parameterization(doc, _validated=True)
    evaluator.evaluate()
    sm = evaluator.evaluate({name: p["sm"] for name, p in names.items()})
    if sm["br_bsm"] != 0 or any(not math.isclose(v, 1, abs_tol=1e-10, rel_tol=0)
                              for v in (*sm["production_scales"].values(), *sm["decay_scales"].values())):
        raise ValueError("declared SM point must normalize each rate modifier to one with zero BSM width")
    return doc


class Parameterization:
    """Compile validation once; subsequent evaluations enforce the point domain."""

    def __init__(self, document, *, _validated=False):
        self.document = document if _validated else validate_bundle(document)

    def point(self, values=None):
        doc = self.document
        point = {name: p["initial"] for name, p in doc["parameters"].items()}
        values = {} if values is None else values
        if not isinstance(values, dict) or set(values) - set(point):
            raise ValueError("point references an unknown parameter")
        point.update(values)
        for name, value in point.items():
            value = _number(value, f"parameter {name}")
            lo, hi = doc["parameters"][name]["bounds"]
            if (lo is not None and value < lo) or (hi is not None and value > hi):
                raise ValueError(f"parameter {name} outside declared bounds")
            point[name] = value
        if "vector_upper_bound" in doc and any(abs(point[n]) > 1 for n in doc["vector_parameters"]):
            raise ValueError("vector parameter magnitude exceeds declared upper bound")
        fractions = [point[n] for n in doc.get("bsm_parameters", {}).values()]
        if any(not 0 <= v < 1 for v in fractions) or math.fsum(fractions) >= 1:
            raise ValueError("BSM branching fractions outside physical domain")
        return point

    def evaluate(self, values=None):
        doc, point = self.document, self.point(values)
        loops = {key: (point[loop["parameter"]] ** 2 if loop["mode"] == "effective"
                       else _poly_value(loop["polynomial"], point)) for key, loop in doc.get("loops", {}).items()}

        def scale(modifier):
            if "parameter" in modifier:
                return point[modifier["parameter"]] ** 2
            if "loop" in modifier:
                return loops[modifier["loop"]]
            if "constant" in modifier:
                return modifier["constant"]
            return _poly_value(modifier["polynomial"], point)

        production = {n: scale(m) for n, m in doc["production"].items()}
        decays = {n: scale(m) for n, m in doc["decays"].items()}
        if any(not math.isfinite(v) or v < 0 for v in (*loops.values(), *production.values(), *decays.values())):
            raise ValueError("rate modifier must be finite and nonnegative")
        visible = math.fsum(doc["branching_fractions"][n] * v for n, v in decays.items())
        br_bsm = math.fsum(point[n] for n in doc.get("bsm_parameters", {}).values())
        width = visible / (1 - br_bsm)
        if not math.isfinite(width) or width <= 0:
            raise ValueError("total width scaling must be finite and positive")
        rates = [{**row, "mu": production[row["production"]] * decays[row["decay"]] / width}
                 for row in doc["rates"]]
        for row in rates:
            row["value"] = row["sm_value"] * row["mu"]
            if not math.isfinite(row["value"]):
                raise ValueError("prediction is nonfinite")
        result = {"framework": doc["framework"], "mass_gev": doc["mass_gev"], "convention": doc["convention"],
                  "parameters": point, "loop_modes": {k: v["mode"] for k, v in doc.get("loops", {}).items()},
                  "loop_scales": loops, "width_scaling": width, "visible_width_scaling": visible,
                  "br_bsm": br_bsm, "production_scales": production, "decay_scales": decays, "rates": rates}
        if doc["framework"] == "heft-lo":
            result["heft_dictionary"] = {key: point[name] for key, name in doc["heft_dictionary"].items()}
            result["heft_normalization"] = doc["heft_normalization"]
        return result


def evaluate(bundle, point=None):
    return Parameterization(bundle).evaluate(point)


def reference_branching_fractions(table, decay_rows, *, mass_gev):
    """Select exact mass-bound v1 reference rows using supplied decay identities.

    The reference source loader owns source-byte qualification. This seam only
    validates table structure and the selected complete branching-fraction set;
    it performs no interpolation, channel guessing or silent renormalization.
    """
    from ravel.validation.constants_manifest import check_higgs_tables
    if check_higgs_tables(table):
        raise ValueError("invalid supplied Higgs reference table")
    rows = {r["id"]: r for r in table["rows"]}
    if not isinstance(decay_rows, dict) or not decay_rows or len(set(decay_rows.values())) != len(decay_rows):
        raise ValueError("supply distinct reference row ids for every decay")
    fractions = {}
    for decay, identity in decay_rows.items():
        _text(decay, "decay identity")
        row = rows.get(identity)
        if row is None or row["quantity"] != "branching_ratio" or row["unit"] != "1" or row["mass_gev"] != mass_gev:
            raise ValueError("reference branching row identity, mass or unit differs")
        fractions[decay] = row["value"]
    if not math.isclose(math.fsum(fractions.values()), 1, abs_tol=1e-10, rel_tol=0):
        raise ValueError("reference branching fractions must sum to one")
    return fractions


def validate(spec):
    _keys(spec, ("schema_version", "input", "output"), ("point",), "higgs parameterization task")
    if type(spec["schema_version"]) is not int or spec["schema_version"] != 1:
        raise ValueError("unsupported parameterization task version")
    _text(spec["input"], "parameterization input")
    output_contract(spec["output"])
    return json.loads(json.dumps(spec, allow_nan=False))


def inputs(spec, base_dir):
    spec = validate(spec)
    from ravel.physics.inference.documents import Context
    return [Context(spec["input"], base_dir).document_path]


def run(spec, base_dir, output_dir):
    """Pure calculation adapter; supervising workflow owns scientific admission."""
    from ravel.validation.higgs_bundle_checks import check_parameterization_closure
    spec = validate(spec)
    path = inputs(spec, base_dir)[0]
    document, digest = _load(path)
    closure = check_parameterization_closure(document)
    result = {"schema_version": 1, "kind": "higgs-parameterization",
              **evaluate(document, spec.get("point")), "closure": closure,
              "status_scope": "supplied_rate_parameterization", "physics_validated": False,
              "inputs": [{"path": str(path), "sha256": digest}]}
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    publish(output, result, spec["output"])
    return result


def check_parameterization_closure(doc):
    """Owner interface of ``check:higgs.parameterization_closure`` for the scalar review checks.

    ``doc`` is the parameterization bundle with its supplied held-out ``closure`` points. The
    comparison is ``higgs_bundle_checks.check_parameterization_closure``; this returns its typed
    status record. A failed comparison is a material finding; a bundle without closure points or
    with an invalid declaration leaves the check inconclusive. No tolerance or point is inferred.
    """
    from ravel.validation import higgs_bundle_checks
    identity = "check:higgs.parameterization_closure"
    try:
        validate_bundle(doc)
    except (ValueError, TypeError, KeyError) as exc:
        return {"status": "inconclusive", "findings": [], "outcome": "inputs_invalid", "detail": str(exc)}
    if not doc.get("closure"):
        return {"status": "inconclusive", "findings": [], "outcome": "inputs_missing",
                "detail": "parameterization requires supplied held-out closure points"}
    try:
        report = higgs_bundle_checks.check_parameterization_closure(doc)
    except ValueError as exc:
        return {"status": "failed", "outcome": "flagged_conflict",
                "findings": [{"id": identity + ":closure", "code": "closure", "materiality": "A",
                              "summary": str(exc)}]}
    return {"status": "passed", "findings": [], "outcome": "passed", "points": report["points"]}
