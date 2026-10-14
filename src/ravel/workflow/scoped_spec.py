"""Strict, explicit inputs for bounded generation and supplied-likelihood workflows.

Defaults in an upstream run card are recorded after execution, never inferred from
the prompt. A shower stage runs only when declared; no detector, PDF download,
spectrum calculation or theory correction is silently added by these adapters.

Generation may name an installed MadGraph version (or ``auto``: chosen by the
process's parton content), a reviewed derived UFO (``model_origin``), a batch of
parameter points with per-point card overrides, a cross-section-only run, a
declared LHE transform before the shower and a structured physics intent that is
reconciled with the executed cards.
"""
from pathlib import Path
import re

from ravel.validation.validate_task_contract import (
    _object, _array, _enum, _TEXT, _POSITIVE, _NONNEG, _COUNT, _schema_errors,
)

MODES = ("generate", "likelihood")
NUMBER = {"type": "number"}
SCALAR = {"anyOf": [NUMBER, {"type": "boolean"},
                      {"type": "string", "pattern": r"^[A-Za-z0-9_.+\-]+$"}]}
RUNTIME = _object({"madgraph": _TEXT, "python": _TEXT, "compiler": _TEXT, "lhapdf_config": _TEXT,
                   "environment": _object({"SDKROOT": _TEXT, "LIBRARY_PATH": _TEXT})},
                  ("madgraph", "python", "compiler"))
GENERATION = _object({
    "runtime": RUNTIME,
    "model": {"type": "string", "pattern": r"^[A-Za-z][A-Za-z0-9_\-]*$"},
    "definitions": _object({}, additional={"type": "string", "pattern": r"^[A-Za-z0-9_+~\- ]+$"}),
    "process": {"type": "string", "pattern": r"^[A-Za-z0-9_+~>,/@=(). \-]+$"},
    "parameter_card": _TEXT,
    "events": {"type": "integer", "minimum": 1, "maximum": 1000000},
    "seed": {"type": "integer", "minimum": 1, "maximum": 30081},
    "beam_pdg": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
    "run_settings": _object({}, additional=SCALAR),
    "observable": _object({
        "kind": {"type": "string", "const": "final_state_mass"},
        "final_state_pdg": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
        "bin_edges_gev": {"type": "array", "items": _NONNEG, "minItems": 3, "maxItems": 201},
        "min_pt_gev": _NONNEG, "max_abs_eta": _POSITIVE, "min_mass_gev": _NONNEG,
    }, ("kind", "final_state_pdg", "bin_edges_gev")),
    "observables": {"type": "array", "items": {"type": "object"}, "minItems": 1, "maxItems": 16},
    "final_state_pdg": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
    "shower": {"type": "object"},
    "generator": _object({"name": {"const": "madgraph"},
                          "version": {"type": "string", "pattern": r"^(auto|[0-9]+\.[0-9]+\.[0-9]+)$"}},
                         ("name", "version")),
    "model_origin": _TEXT,
    "parameter_points": {"type": "array", "minItems": 1, "maxItems": 64, "items": _object({
        "id": {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"},
        "overrides": {"type": "array", "minItems": 1, "maxItems": 64, "items": _object({
            "block": {"type": "string", "pattern": r"^[A-Za-z][A-Za-z0-9_]*$"},
            "code": {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 4},
            "value": {"anyOf": [NUMBER, {"type": "string", "const": "Auto"}]}}, ("block", "code", "value"))},
    }, ("id", "overrides"))},
    "cross_section_only": {"type": "boolean"},
    "lhe_transform": _TEXT,
    "physics_intent": {"type": "object"},
}, ("model", "definitions", "process", "events", "seed", "beam_pdg", "run_settings"))
# MadGraph built-in PDF labels and the LHAPDF identifiers they write into the LHE.
BUILTIN_PDFS = {"cteq6l1": 10042, "cteq6_l": 10041, "cteq6_m": 10000,
                "nn23lo": 246800, "nn23lo1": 247000, "nn23nlo": 244800}
COUNTING = _object({"observed": {"type": "integer", "minimum": 0}, "background": _POSITIVE,
                    "background_uncertainty": _NONNEG, "signal": _POSITIVE},
                   ("observed", "background", "background_uncertainty", "signal"))
LIKELIHOOD = _object({
    "workspace": _TEXT, "measurement": _TEXT, "counting": COUNTING,
    "poi_cap": _POSITIVE,
    "normalization": _object({"kind": _enum(("signal_strength", "signal_events")),
                               "luminosity_fb": _POSITIVE}, ("kind",)),
}, ("poi_cap", "normalization"))
SCHEMA = _object({
    "schema_version": {"type": "integer", "const": 1}, "mode": _enum(MODES),
    "source": _TEXT, "assumptions": {"type": "array", "items": _TEXT, "minItems": 1},
    "max_seconds": {"type": "integer", "minimum": 1, "maximum": 86400},
    "approval_mode": _enum(("physicist", "scripted_yes")),
    "generation": GENERATION, "likelihood": LIKELIHOOD,
    # Optional placement of the one supervised stage (ravel.workflow.placement).
    "execution": {"type": "object"},
    "goal_binding": _object({"contract": {"type": "object"}, "assignment_id": _TEXT}, ("contract", "assignment_id")),
}, ("schema_version", "mode", "source", "assumptions", "max_seconds", "approval_mode"))


def validate(spec):
    errors = _schema_errors(spec, SCHEMA, "spec")
    if errors:
        return errors
    if "execution" in spec:
        from ravel.workflow import placement
        try:
            placement.validate(spec["execution"])
        except ValueError as exc:
            return [f"spec.execution: {exc}"]
    mode = spec["mode"]
    section = "generation" if mode == "generate" else "likelihood"
    if section not in spec or ({"generation", "likelihood"} - {section}) & spec.keys():
        return [f"{mode} requires only the {section} specification"]
    if mode == "likelihood":
        s = spec[section]
        if ("workspace" in s) == ("counting" in s):
            errors.append("supply exactly one workspace or counting model")
        if "measurement" in s and "workspace" not in s:
            errors.append("measurement selection requires a supplied workspace")
        norm = s["normalization"]
        if norm["kind"] == "signal_events" and not (
                "counting" in s and s["counting"]["signal"] == 1):
            errors.append("signal_events requires an explicit unit-signal counting model")
        if "luminosity_fb" in norm and norm["kind"] != "signal_events":
            errors.append("luminosity conversion requires signal_events, not arbitrary signal strength")
        if s["poi_cap"] > 1e6:
            errors.append("poi_cap exceeds the bounded adapter range (1e6)")
        return errors
    g = spec[section]
    settings = g["run_settings"]
    required = {"ebeam1", "ebeam2", "lpp1", "lpp2", "pdlabel", "lhaid",
                "fixed_ren_scale", "fixed_fac_scale", "dynamical_scale_choice", "scalefact"}
    errors += [f"explicit run setting required: {k}" for k in sorted(required - settings.keys())]
    reserved = {"nevents", "iseed", "run_tag", "use_syst", "systematics_program", "ickkw"}
    if reserved & settings.keys():
        errors.append("events/seed belong in typed fields; matching and reweighting are outside this adapter")
    for key, value in settings.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            errors.append(f"invalid run-card key: {key!r}")
        if key in ("ebeam1", "ebeam2", "scalefact", "scale", "dsqrt_q2fact1", "dsqrt_q2fact2") and (
                type(value) not in (float, int) or value <= 0):
            errors.append(f"{key} must be positive numeric")
        if key in ("lpp1", "lpp2", "lhaid", "dynamical_scale_choice") and type(value) is not int:
            errors.append(f"{key} must be an integer")
        if key.startswith("fixed_") and type(value) is not bool:
            errors.append(f"{key} must be a boolean")
    if settings.get("fixed_ren_scale") and "scale" not in settings:
        errors.append("fixed renormalization scale requires scale in GeV")
    if settings.get("fixed_fac_scale") and not {"dsqrt_q2fact1", "dsqrt_q2fact2"} <= settings.keys():
        errors.append("fixed factorization scale requires dsqrt_q2fact1/2 in GeV")
    # Beam particles must agree with lpp; hadron beams take a MadGraph built-in PDF
    # or an installed, pinned LHAPDF set. No PDF set is downloaded.
    from ravel.physics import beam_content
    _, beam_errors = beam_content.content(g)
    errors += beam_errors
    if "runtime" not in g and "generator" not in g:
        errors.append("supply runtime paths or a generator version")
    label = settings.get("pdlabel")
    if label == "lhapdf":
        if "runtime" in g and "lhapdf_config" not in g["runtime"]:
            errors.append("an LHAPDF set requires runtime.lhapdf_config (the installed lhapdf-config)")
        if type(settings.get("lhaid")) is not int or settings["lhaid"] <= 0:
            errors.append("an LHAPDF set requires its positive integer lhaid")
    elif label in BUILTIN_PDFS:
        if settings.get("lhaid") != BUILTIN_PDFS[label]:
            errors.append(f"built-in PDF {label} has lhaid {BUILTIN_PDFS[label]}")
    else:
        errors.append("pdlabel must be a MadGraph built-in PDF (" + ", ".join(sorted(BUILTIN_PDFS)) + ") or lhapdf")
    if ">" not in g["process"] or "@" in g["process"]:
        errors.append("supply one LO process, with an explicit final state and no process-number directive")
    errors += _batch_errors(g)
    if "physics_intent" in g:
        from ravel.workflow.spec_reconciliation import validate_intent
        errors += validate_intent(g["physics_intent"])
    for name in g["definitions"]:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
            errors.append("invalid particle alias")
    if "parameter_points" in g and "shower" in g:
        errors.append("a parameter batch ends at parton level; shower each point through event production")
    if g.get("cross_section_only"):
        if {"observable", "observables", "shower", "final_state_pdg"} & g.keys():
            errors.append("a cross-section-only run has no observables, final-state census or shower")
        return errors
    if ("observable" in g) == ("observables" in g):
        return errors + ["declare exactly one of observable (final-state mass) or observables (typed list)"]
    if "observable" in g:
        edges = g["observable"]["bin_edges_gev"]
        if any(a >= b for a, b in zip(edges, edges[1:])):
            errors.append("observable bin edges must be strictly increasing")
        if any(pdg == 0 for pdg in g["observable"]["final_state_pdg"]):
            errors.append("final state requires nonzero PDG identifiers")
        if "final_state_pdg" in g:
            errors.append("final_state_pdg belongs to the final-state mass observable")
    else:
        from ravel.physics.final_state_observables import check
        errors += check(g["observables"])
        if any(pdg == 0 for pdg in g.get("final_state_pdg", [])):
            errors.append("final state requires nonzero PDG identifiers")
    if "shower" in g:
        from ravel.physics.scoped_shower import check as check_shower
        errors += check_shower(g["shower"])
        if "observable" in g:
            errors.append("a shower stage requires typed observables")
    return errors


def _batch_errors(g):
    points = g.get("parameter_points")
    if points is None:
        return []
    errors = []
    ids = [p["id"] for p in points]
    if len(set(ids)) != len(ids):
        errors.append("parameter point ids must be unique")
    if g["seed"] + len(points) - 1 > 30081:
        errors.append("seed + number of points - 1 must not exceed 30081 (one seed per point)")
    for point in points:
        addresses = [(o["block"].upper(), tuple(o["code"])) for o in point["overrides"]]
        if len(set(addresses)) != len(addresses):
            errors.append(f"point {point['id']}: one override per block/code")
        for o in point["overrides"]:
            if o["value"] == "Auto" and o["block"].upper() != "DECAY":
                errors.append(f"point {point['id']}: Auto is a DECAY width value only")
            if o["block"].upper() == "DECAY" and len(o["code"]) != 1:
                errors.append(f"point {point['id']}: a DECAY override names one particle")
            if type(o["value"]) is float and o["value"] != o["value"]:
                errors.append(f"point {point['id']}: nonfinite override")
    return errors


def require_valid(spec):
    errors = validate(spec)
    if errors:
        raise ValueError("invalid scoped specification: " + "; ".join(errors))


def input_file(value, base):
    path = Path(value).expanduser()
    path = path if path.is_absolute() else Path(base) / path
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"input must be an existing regular file, not a symlink: {path}")
    return path.resolve()
