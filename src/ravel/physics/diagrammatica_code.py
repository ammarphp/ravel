"""Source-pinned HEPTAPOD EDA script construction; no CAS execution.

Only the three named pure modules from HEPTAPOD v2.1.0 are executed, from
captured bytes, inside the approved worker. Toolbase/MCP/package initializers
and every native runner are outside this operation. GPL backend sources stay
external and retain their license; this module contains original wrapper code.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import threading
import time
from types import ModuleType

from ravel.workflow.operation_resources import document_pin
from ravel.workflow.state_io import _unique

RELEASE = "cb771f8cf054ec7c5f503109b21e55337cb28b41"
BACKEND = {
    "tools/nda/topology.py": "3eee5884b4da27e76bdabe494586001d48817d5a6df8f3b1a7ae5df88b2c56a2",
    "tools/nda/simple_diagram.py": "8107e888c1034c7713417a26a22e57f7c67d44ba1439241b7a7a6f038d68659e",
    "tools/eda/feyncalc_codegen.py": "68bff2630ac2cf2075e8fb9084be4b9460de60f0c16bf251648edef068d529ee",
}
LOCK = threading.RLock()
MAX_CAPTURE_BYTES = 16 * 1024**2
RESERVED = {"I", "Pi", "E", "D", "p", "p1", "p2", "amp", "ampSq", "ampCC",
            "ampSqKin", "width", "pMag", "nInit", "colorFactor", "symmetryFactor"}


def _keys(obj, keys, label):
    if type(obj) is not dict or set(obj) != set(keys):
        raise ValueError(label + " requires exactly " + ", ".join(keys))


def _json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _symbol(value):
    if (type(value) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,31}", value)
            or value in RESERVED):
        raise ValueError("ordinary nonreserved symbolic identifier required")
    return value


def validate(task):
    _keys(task, ("input",), "diagrammatica code task")
    if type(task["input"]) is not str or not task["input"].strip():
        raise ValueError("input must be a file path")
    return deepcopy(task)


def _diagram(doc):
    _keys(doc, ("schema_version", "operation", "units", "release", "backend_files",
                "diagram", "grounding", "vertex_coefficient_definition", "coupling_dimensions_GeV", "max_seconds"), "diagrammatica request")
    if (type(doc["schema_version"]) is not int or doc["schema_version"] != 1
            or doc["operation"] != "symbolic_decay_code" or doc["units"] != "GeV"
            or doc["release"] != RELEASE or type(doc["max_seconds"]) is not int
            or not 1 <= doc["max_seconds"] <= 60):
        raise ValueError("fixed release, operation, units and bounded code-construction budget required")
    if (type(doc["vertex_coefficient_definition"]) is not str
            or not doc["vertex_coefficient_definition"].strip()
            or len(doc["vertex_coefficient_definition"]) > 4096):
        raise ValueError("explicit model coefficient to vertex convention declaration required")
    d = doc["diagram"]
    _keys(d, ("initial", "final", "vertices", "color_factor"), "single-vertex decay")
    if (type(d["initial"]) is not list or len(d["initial"]) != 1
            or type(d["final"]) is not list or len(d["final"]) != 2
            or type(d["vertices"]) is not list or len(d["vertices"]) != 1
            or type(d["color_factor"]) is not int or d["color_factor"] not in (1, 3)):
        raise ValueError("one singlet parent, two daughters, one vertex and explicit Nc1/3 required")
    particles = d["initial"] + d["final"]
    for p in particles:
        _keys(p, ("label", "spin", "mass", "antiparticle", "self_conjugate"), "particle")
        _symbol(p["label"])
        if (type(p["spin"]) not in (int, float) or p["spin"] not in (0, .5, 1)
                or type(p["mass"]) not in (int, float) or not math.isfinite(p["mass"])
                or not 0 <= p["mass"] <= 1e9 or type(p["antiparticle"]) is not bool
                or type(p["self_conjugate"]) is not bool
                or p["self_conjugate"] != (p["spin"] != .5)):
            raise ValueError("explicit spin, finite mass and particle/anti declaration required")
        if (p["label"].lower() == "positron"
                or p["antiparticle"] != p["label"].lower().endswith("bar")
                or p["antiparticle"] and (not p["label"].endswith("bar") or len(p["label"]) <= 3)):
            raise ValueError("canonical label suffix bar must agree with explicit antiparticle declaration")
        if p["spin"] != .5 and p["antiparticle"]:
            raise ValueError("this operation admits neutral scalar/vector parents and scalar daughters only")
    parent, a, b = particles
    if (parent["antiparticle"] or parent["mass"] <= a["mass"] + b["mass"]
            or parent["label"] in (a["label"], b["label"])):
        raise ValueError("distinct neutral parent and strictly open supplied kinematic witness required")
    if a["label"] == b["label"] and a != b:
        raise ValueError("identical daughter labels require identical complete declarations")
    bases = [p["label"][:-3] if p["antiparticle"] else p["label"] for p in (a, b)]
    if bases[0] == bases[1] and a["mass"] != b["mass"]:
        raise ValueError("same-species particle and antiparticle require equal supplied mass")
    vertex = d["vertices"][0]
    _keys(vertex, ("type", "coupling"), "vertex")
    if parent["spin"] == 0 and a["spin"] == b["spin"] == 0:
        family = "SSS"; allowed = {"scalar"}; coupling_keys = None
        if d["color_factor"] != 1:
            raise ValueError("only color-singlet scalar daughters are served")
    elif parent["spin"] in (0, 1) and a["spin"] == b["spin"] == .5:
        if a["antiparticle"] == b["antiparticle"]:
            raise ValueError("one particle and one antiparticle required; Majorana/same-flow cases unserved")
        family = "SFF" if parent["spin"] == 0 else "VFF"
        allowed = {"scalar", "pseudoscalar", "chiral"} if family == "SFF" else {"vector", "axial-vector", "vector-axial", "chiral"}
        coupling_keys = {"gL", "gR"} if vertex["type"] == "chiral" else {"gV", "gA"} if vertex["type"] == "vector-axial" else None
    else:
        raise ValueError("only SSS, SFF and massive-parent VFF single-vertex decays are served")
    if vertex["type"] not in allowed:
        raise ValueError("vertex basis is unsupported for the declared spin family")
    coupling = vertex["coupling"]
    if coupling_keys:
        _keys(coupling, coupling_keys, "coupling basis")
        symbols = [_symbol(x) for x in coupling.values()]
        if len(set(symbols)) != len(symbols):
            raise ValueError("independent coupling coordinates need distinct symbols")
    else:
        symbols = [_symbol(coupling)]
    mass_symbols = {"m" + p["label"] for p in particles}
    if set(symbols) - {"g", "gL", "gR", "gV", "gA", "gS", "gP", "y", "yL", "yR"}:
        raise ValueError("use explicit ordinary coupling coordinates; Wolfram builtins/free expressions are unserved")
    if set(symbols) & mass_symbols:
        raise ValueError("mass and coupling symbolic coordinates must not collide")
    _keys(doc["coupling_dimensions_GeV"], symbols, "coupling dimensions")
    dimension = 1 if family == "SSS" else 0
    if any(type(value) is not int or value != dimension for value in doc["coupling_dimensions_GeV"].values()):
        raise ValueError("renormalizable SSS coefficient has mass dimension1; served fermion coefficients have dimension0")
    translated = deepcopy(d)
    for p in translated["initial"] + translated["final"]:
        del p["antiparticle"]
        del p["self_conjugate"]
    translated["topology"] = "tree_2body"
    return translated, family


def _capture(task, base):
    from ravel.workflow.science import regular
    captured = {}
    def read(value, parent, expected=None):
        path = regular(value, parent)
        observation = document_pin(path)
        raw = observation["text"].encode("utf-8")
        if expected is not None and observation["sha256"] != expected:
            raise ValueError("source input pin differs")
        if str(path) in captured and captured[str(path)] != raw:
            raise ValueError("input changed during code-construction capture")
        captured[str(path)] = raw
        if sum(map(len, captured.values())) > MAX_CAPTURE_BYTES:
            raise ValueError("code construction capture exceeds16MiB")
        return path, raw
    def bound(pin, parent):
        _keys(pin, ("path", "sha256"), "source pin")
        if type(pin["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]):
            raise ValueError("SHA256 source identity required")
        return read(pin["path"], parent, pin["sha256"])
    path, raw = read(validate(task)["input"], base)
    def nonfinite(value):
        raise ValueError("nonfinite request JSON")
    doc = json.loads(raw, object_pairs_hook=_unique, parse_constant=nonfinite)
    diagram, family = _diagram(doc)
    _keys(doc["backend_files"], BACKEND, "exact released pure backend closure")
    sources = {}
    for rel, expected in BACKEND.items():
        ref = doc["backend_files"][rel]
        if type(ref) is not dict or ref.get("sha256") != expected:
            raise ValueError("only exact inspected released backend bytes are executable")
        _, sources[rel] = bound(ref, path.parent)
    if type(doc["grounding"]) is not list or not doc["grounding"]:
        raise ValueError("at least one bound model/vertex/convention source required")
    for pin in doc["grounding"]:
        bound(pin, path.parent)
    return doc, diagram, family, sources, captured


def _ufo_request(task, base):
    # Read-only operation selection; the delegated compiler captures/validates
    # the complete request and scientific source again before consumption.
    from ravel.workflow.science import regular
    from ravel.workflow.state_io import read_json
    doc = read_json(regular(validate(task)["input"], base))
    return type(doc) is dict and doc.get("schema_version") == 2 and doc.get("operation") == "ufo_decay_code"


def inputs(task, base):
    """Intake reads and checks bytes only; no backend code executes here."""
    if _ufo_request(task, base):
        from ravel.physics import ufo_decay
        return ufo_decay.inputs(task, base)
    return [Path(p) for p in _capture(task, base)[4]]


def execution_seconds(task, base):
    if _ufo_request(task, base):
        from ravel.physics import ufo_decay
        return ufo_decay.execution_seconds(task, base)
    return _capture(task, base)[0]["max_seconds"]


@contextmanager
def _backend(sources):
    """Temporarily isolate the fixed pure dependency closure, never initializers.

    No source selection or import outside the hard-coded released module set.
    Captured bytes, not paths re-opened by an import loader, are compiled.
    Package namespace restoration also applies on generator/import failure.
    """
    names = ("tools", "tools.nda", "tools.eda", "tools.nda.topology",
             "tools.nda.simple_diagram", "tools.eda.feyncalc_codegen")
    with LOCK:
        old = {name: sys.modules.get(name) for name in names}
        try:
            for name in names[:3]:
                module = ModuleType(name); module.__path__ = []
                sys.modules[name] = module
            for rel in BACKEND:
                name = rel[:-3].replace("/", ".")
                raw = sources[rel]
                if hashlib.sha256(raw).hexdigest() != BACKEND[rel]:
                    raise ValueError("backend captured bytes changed")
                module = ModuleType(name); module.__package__ = name.rpartition(".")[0]
                module.__file__ = "heptapod-v2.1.0/" + rel
                sys.modules[name] = module
                exec(compile(raw, module.__file__, "exec"), module.__dict__)
            yield sys.modules[names[-2]], sys.modules[names[-1]]
        finally:
            for name, module in old.items():
                if module is None: sys.modules.pop(name, None)
                else: sys.modules[name] = module


def run(task, base, output):
    if _ufo_request(task, base):
        from ravel.physics import ufo_decay
        return ufo_decay.run(task, base, output)
    from ravel.physics.finite_mc_model import _admit_output
    doc, diagram, family, sources, captured = _capture(task, base)
    out = _admit_output(output)
    started = time.monotonic(); code = None; raw_code = None; failure = None; warnings = []; metadata = {}; aliases = {}
    try:
        with _backend(sources) as (parser, generator):
            result = generator.SymbolicFeynCalcCodeGenerator(assume_real_couplings=False).generate(parser.parse_diagram(diagram))
            warnings = result.warnings
            raw_code = result.code
            a, b = doc["diagram"]["final"]
            if a["spin"] == b["spin"] == .5:
                particle, anti = (b, a) if a["antiparticle"] else (a, b)
                if anti["label"][:-3] == particle["label"]:
                    aliases["m" + anti["label"]] = "m" + particle["label"]
            code = ("(* Generated using HEPTAPOD v2.1.0, tonymenzo/heptapod; GPL-3.0-or-later backend. *)\n"
                    "(* Explicit same-species mass-coordinate identification; raw upstream script retained separately. *)\n"
                    + "".join(f"{left} = {right};\n" for left, right in aliases.items()) + raw_code) if raw_code else None
            metadata = {"process_type": result.process_type.name, "momentum_map": result.momentum_map}
            if result.process_type.name != "DECAY_1TO2" or warnings or not code:
                raise ValueError("released generator returned unsupported/incomplete code")
        if time.monotonic()-started > doc["max_seconds"]:
            raise TimeoutError("declared construction time exhausted")
    except (ValueError, TypeError, KeyError, ImportError, RuntimeError, TimeoutError) as exc:
        failure = {"type": type(exc).__name__, "message": str(exc)}
    if code:
        with (out / "decay-symbolic.wl").open("xb") as stream: stream.write(code.encode())
        with (out / "upstream-symbolic.wl").open("xb") as stream: stream.write(raw_code.encode())
    drift = []
    for path, raw in captured.items():
        try:
            ending = document_pin(path)
            if ending["sha256"] != hashlib.sha256(raw).hexdigest(): drift.append(path)
        except (ValueError, OSError): drift.append(path)
    report = {"schema_version": 1, "status": "passed" if failure is None and not drift else "failed",
              "kind": "diagrammatica_symbolic_code", "scope": "unexecuted one-vertex1to2 EDA code construction",
              "physics_validated": False, "execution_authorized": False, "evaluated_width": None,
              "native_calls": 0, "model_calls": 0, "family": family, "metadata": metadata,
              "error": failure, "generator_warnings": warnings, "ending_input_errors": drift,
              "raw_script": "decay-symbolic.wl" if code else None,
              "script_sha256": hashlib.sha256(code.encode()).hexdigest() if code else None,
              "raw_upstream_script": "upstream-symbolic.wl" if raw_code else None,
              "raw_upstream_sha256": hashlib.sha256(raw_code.encode()).hexdigest() if raw_code else None,
              "same_species_mass_coordinate_identifications": aliases,
              "vertex_coefficient_definition": doc["vertex_coefficient_definition"],
              "coupling_dimensions_GeV": doc["coupling_dimensions_GeV"],
              "amplitude_squared_scope": "unaveraged spin/polarization-summed ampSqKin before Nc/symmetry/initial-spin width factors",
              "release": RELEASE, "diagram_declaration": doc["diagram"],
              "backend_attribution": {"repository": "https://github.com/tonymenzo/heptapod",
                                      "release": "v2.1.0", "license": "GPL-3.0-or-later",
                                      "upstream_sources_embedded_in_ravel": False,
                                      "redistribution_license_review_required": True},
              "numeric_masses_are_open_domain_witness_only": True,
              "symbolic_mass_names": ["m" + p["label"] for p in diagram["initial"] + diagram["final"]],
              "couplings_assumed_real": False, "elapsed_seconds": time.monotonic()-started,
              "source_inputs": [{"path": p, "sha256": hashlib.sha256(raw).hexdigest()} for p, raw in captured.items()],
              "limitations": ["No Wolfram/FeynCalc evaluation or numerical width is delivered.",
                              "Complete model, charge/quantum conservation and gauge identities are not established.",
                              "Nc is declared color multiplicity for a singlet parent; color tensors are not derived.",
                              "Majorana, loops, scattering, vector daughters and dim5 operators are unserved.",
                              "Native ABI/runtime, dimensional convention and complex-basis qualification remain independent tasks."]}
    with (out / "diagram-code-report.json").open("xb") as stream: stream.write(_json(report))
    return report
