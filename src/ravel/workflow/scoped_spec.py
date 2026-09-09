"""Strict, explicit inputs for bounded parton and supplied-likelihood workflows.

Defaults in an upstream run card are recorded after execution, never inferred from
the prompt. No detector, shower, PDF download, spectrum calculation or theory
correction is silently added by these adapters.
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
RUNTIME = _object({"madgraph": _TEXT, "python": _TEXT, "compiler": _TEXT,
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
}, ("runtime", "model", "definitions", "process", "events", "seed", "beam_pdg", "run_settings", "observable"))
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
}, ("schema_version", "mode", "source", "assumptions", "max_seconds", "approval_mode"))


def validate(spec):
    errors = _schema_errors(spec, SCHEMA, "spec")
    if errors:
        return errors
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
    # This first adapter uses installed builtin proton PDFs. LHAPDF downloads and
    # lepton beams need an independently tested runtime/normalization contract.
    if g["beam_pdg"] != [2212, 2212] or any(settings.get(k) != 1 for k in ("lpp1", "lpp2")):
        errors.append("this adapter currently supports proton-proton beams only")
    if settings.get("pdlabel") != "cteq6l1" or settings.get("lhaid") != 10042:
        errors.append("this adapter currently supports the installed cteq6l1 PDF (10042) only")
    if ">" not in g["process"] or "@" in g["process"]:
        errors.append("supply one LO process, with an explicit final state and no process-number directive")
    for name in g["definitions"]:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
            errors.append("invalid particle alias")
    edges = g["observable"]["bin_edges_gev"]
    if any(a >= b for a, b in zip(edges, edges[1:])):
        errors.append("observable bin edges must be strictly increasing")
    if any(pdg == 0 for pdg in g["observable"]["final_state_pdg"]):
        errors.append("final state requires nonzero PDG identifiers")
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
