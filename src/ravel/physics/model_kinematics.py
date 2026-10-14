"""Conditional decay thresholds from pinned text and explicit interpretations.

This is a necessary rest-mass condition, not a decay calculation. In particular,
an inclusive off-shell channel cannot be rejected using nominal pole masses.
Supplemental masses and final-state interpretations are reviewable assertions;
their text custody does not prove their scientific applicability.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re

from ravel.physics import model_inputs as slha

MAX_CONTEXT_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 1024 * 1024
MAX_SOURCE_TOTAL = 8 * 1024 * 1024
MAX_SOURCES = 32
SIGNED_NEUTRALINOS = {1000022, 1000023, 1000025, 1000035}
SEMANTICS = {"on_shell_final_states", "off_shell_inclusive", "unknown"}


def _keys(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(label + " has unexpected or missing fields")


def _text(value, label, maximum=4096):
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValueError(label + " needs bounded nonempty text")
    return value


def _line(value):
    if type(value) is not int or not 1 <= value <= slha.MAX_BYTES:
        raise ValueError("source line must be a bounded positive integer")
    return value


def _pdg(value):
    if type(value) is not int:
        raise ValueError("PDG must be an integer")
    return slha._integer(str(value), "kinematic PDG")


def _regular(name, base):
    _text(name, "kinematic source path")
    path = Path(name).expanduser()
    path = path if path.is_absolute() else Path(base) / path
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError("kinematic evidence requires a regular file without symlinks")
    return path.resolve()


def _raw(path, maximum):
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("kinematic source exceeds bounded size")
    return raw


def _unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate kinematic JSON key")
        out[key] = value
    return out


def _nonfinite(value):
    raise ValueError("nonfinite kinematic JSON: " + value)


def read_context(name, source_digest, base):
    """Return checked manifest and all consumed pins, without importing code."""
    path = _regular(name, base)
    raw = _raw(path, MAX_CONTEXT_BYTES)
    try:
        context = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_nonfinite)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("kinematic context requires strict UTF-8 JSON") from exc
    _keys(context, {"schema_version", "source_sha256", "mass_convention", "sources",
                    "supplemental_masses", "channel_semantics"}, "kinematic context")
    if type(context["schema_version"]) is not int or context["schema_version"] != 1:
        raise ValueError("unsupported kinematic context schema")
    if slha._pinned_hash(context["source_sha256"], "kinematic source SHA256") != source_digest:
        raise ValueError("kinematic context is bound to different SLHA bytes")
    if type(context["mass_convention"]) is not str or context["mass_convention"] not in {"nonnegative_only", "slha1_signed_neutralino"}:
        raise ValueError("unsupported explicit mass convention")
    sources = context["sources"]
    if type(sources) is not dict or len(sources) > MAX_SOURCES:
        raise ValueError("kinematic sources must be a bounded object")
    pins = [{"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}]
    source_lines = {}
    consumed = {path}
    total_bytes = 0
    for identity, record in sources.items():
        _text(identity, "kinematic source identity", 128)
        _keys(record, {"path", "sha256"}, "kinematic source record")
        p = _regular(record["path"], base)
        if p in consumed:
            raise ValueError("kinematic evidence source paths must be distinct")
        consumed.add(p)
        data = _raw(p, MAX_SOURCE_BYTES)
        digest = hashlib.sha256(data).hexdigest()
        if slha._pinned_hash(record["sha256"], "kinematic evidence SHA256") != digest:
            raise ValueError("kinematic evidence hash differs from manifest")
        total_bytes += len(data)
        if total_bytes > MAX_SOURCE_TOTAL:
            raise ValueError("kinematic aggregate evidence exceeds bound")
        try:
            source_lines[identity] = data.decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise ValueError("kinematic mass evidence must be UTF-8 text") from exc
        pins.append({"path": str(p), "sha256": digest, "size": len(data)})
    masses = context["supplemental_masses"]
    if type(masses) is not list or len(masses) > slha.MAX_PARTICLES:
        raise ValueError("supplemental mass assertions must be a bounded list")
    seen_pdgs, used_sources = set(), set()
    for record in masses:
        _keys(record, {"pdg", "pdg_token", "mass_token", "unit", "source_id", "source_line", "source_text"}, "supplemental mass")
        pdg = abs(_pdg(record["pdg"]))
        pdg_token = _text(record["pdg_token"], "PDG evidence token", 16)
        if slha._integer(pdg_token, "supplemental PDG evidence") != record["pdg"]:
            raise ValueError("supplemental PDG token differs from declared signed particle identity")
        if pdg in seen_pdgs:
            raise ValueError("duplicate supplemental mass PDG")
        seen_pdgs.add(pdg)
        token = _text(record["mass_token"], "mass token", 128)
        if slha._fraction(token, "supplemental rest mass") < 0:
            raise ValueError("supplemental rest masses must be nonnegative")
        if type(record["unit"]) is not str or record["unit"] not in {"GeV", "MeV"}:
            raise ValueError("supplemental mass needs explicit GeV or MeV unit")
        identity = record["source_id"]
        if type(identity) is not str or identity not in source_lines:
            raise ValueError("supplemental mass evidence source is absent")
        used_sources.add(identity)
        line = _line(record["source_line"])
        text = _text(record["source_text"], "source mass line", 16384)
        lines = source_lines[identity]
        if line > len(lines) or lines[line - 1] != text:
            raise ValueError("supplemental mass source line differs from pinned text")
        if not re.search(r"(?<![\w.+-])" + re.escape(pdg_token) + r"(?![\w.])", text):
            raise ValueError("declared PDG token must occur on the exact pinned source line")
        if not re.search(r"(?<![\w.])" + re.escape(token) + r"(?![\w.])", text) or not re.search(r"\b" + record["unit"] + r"\b", text):
            raise ValueError("mass token and declared unit must occur on the pinned source line")
    if used_sources != set(sources):
        raise ValueError("kinematic sources must all support declared mass assertions")
    channels = context["channel_semantics"]
    if type(channels) is not list or len(channels) > slha.MAX_CHANNELS:
        raise ValueError("channel interpretations must be a bounded list")
    seen_lines = set()
    for record in channels:
        _keys(record, {"source_line", "parent_pdg", "daughter_pdgs", "interpretation",
                       "source_ref", "evidence_text", "evidence_sha256"}, "channel interpretation")
        line = _line(record["source_line"])
        if line in seen_lines:
            raise ValueError("duplicate channel interpretation source line")
        seen_lines.add(line)
        _pdg(record["parent_pdg"])
        daughters = record["daughter_pdgs"]
        if type(daughters) is not list or not 1 <= len(daughters) <= slha.MAX_DAUGHTERS:
            raise ValueError("channel interpretation needs bounded daughter PDGs")
        for pdg in daughters:
            _pdg(pdg)
        if type(record["interpretation"]) is not str or record["interpretation"] not in SEMANTICS:
            raise ValueError("unsupported channel interpretation")
        _text(record["source_ref"], "channel interpretation source reference")
        text = _text(record["evidence_text"], "channel interpretation evidence", 16384)
        if slha._pinned_hash(record["evidence_sha256"], "channel interpretation SHA256") != hashlib.sha256(text.encode()).hexdigest():
            raise ValueError("channel interpretation evidence hash mismatch")
    return context, pins


def verify_pins(pins):
    for record in pins:
        path = _regular(record["path"], Path.cwd())
        data = _raw(path, max(MAX_CONTEXT_BYTES, MAX_SOURCE_BYTES))
        if len(data) != record["size"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError("kinematic evidence changed during diagnosis")


def audit(inventory, context):
    """Assess only explicitly interpreted, known-mass channels; never approve."""
    if inventory is None:
        return {"status": "not_assessed_source_refused", "channels": [], "physics_validated": False,
                "execution_authorized": False, "reason": "Strict source inventory is unavailable."}
    masses = {}
    for row in inventory["masses"]:
        mass = Fraction(row["mass_GeV_exact"])
        interpretation = "nonnegative_supplied_mass"
        if mass < 0:
            if context["mass_convention"] == "slha1_signed_neutralino" and row["pdg"] in SIGNED_NEUTRALINOS:
                mass = abs(mass)
                interpretation = "magnitude_of_declared_SLHA1_signed_neutralino_eigenvalue"
            else:
                mass = None
                interpretation = "unresolved_negative_mass_convention"
        masses[row["pdg"]] = {"mass": mass, "origin": "SLHA_MASS", "source_line": row["source_line"],
                               "interpretation": interpretation}
    for row in context["supplemental_masses"]:
        pdg = abs(row["pdg"])
        if pdg in masses:
            raise ValueError("supplemental mass cannot override supplied SLHA MASS")
        mass = slha._fraction(row["mass_token"], "supplemental mass")
        if row["unit"] == "MeV":
            mass /= 1000
        masses[pdg] = {"mass": mass, "origin": "pinned_supplemental_mass_assertion",
                       "source_line": row["source_line"], "source_id": row["source_id"],
                       "interpretation": "nonnegative_rest_mass_as_explicitly_asserted"}
    meanings = {row["source_line"]: row for row in context["channel_semantics"]}
    used_lines, channels = set(), []
    for decay in inventory["decays"]:
        for channel in decay["channels"]:
            line = channel["source_line"]
            meaning = meanings.get(line)
            scope = "unknown" if meaning is None else meaning["interpretation"]
            if meaning is not None:
                used_lines.add(line)
                if meaning["parent_pdg"] != decay["declared_pdg"] or meaning["daughter_pdgs"] != channel["daughter_pdgs"]:
                    raise ValueError("channel interpretation differs from source parent/daughter IDs")
            ids = [decay["declared_pdg"], *channel["daughter_pdgs"]]
            unavailable = sorted({pdg for pdg in ids if abs(pdg) not in masses or masses[abs(pdg)]["mass"] is None})
            record = {"parent_pdg": decay["declared_pdg"], "daughter_pdgs": channel["daughter_pdgs"],
                      "source_line": line, "branching_fraction_exact": channel["branching_fraction_exact"],
                      "interpretation": scope, "interpretation_assertion": meaning,
                      "unresolved_mass_pdgs": unavailable,
                      "mass_charge_conjugation": "MASS lookup uses absolute PDG identity; signed daughter IDs are preserved.",
                      "positive_channel_by_card": Fraction(decay["total_width_GeV_exact"]) > 0 and Fraction(channel["branching_fraction_exact"]) > 0}
            if unavailable:
                record["status"] = "unresolved_missing_or_signed_mass"
            else:
                parent = masses[abs(ids[0])]["mass"]
                threshold = sum((masses[abs(pdg)]["mass"] for pdg in ids[1:]), Fraction(0))
                slack = parent - threshold
                record.update(parent_mass_GeV_exact=slha._rational(parent), daughter_mass_sum_GeV_exact=slha._rational(threshold),
                              mass_slack_GeV_exact=slha._rational(slack), mass_slack_GeV_decimal=slha._decimal(slack),
                              mass_origins=[{key: value for key, value in masses[abs(pdg)].items() if key != "mass"} for pdg in ids])
                if scope != "on_shell_final_states":
                    record["status"] = "unresolved_channel_semantics" if scope == "unknown" else "not_applicable_off_shell_inclusive"
                elif parent == 0:
                    record["status"] = "unresolved_massless_parent_rest_frame"
                elif not record["positive_channel_by_card"]:
                    record["status"] = "inactive_by_supplied_width_or_BR"
                elif slack < 0:
                    record["status"] = "on_shell_necessary_condition_violated"
                elif slack == 0:
                    record["status"] = "exact_threshold_boundary"
                else:
                    record["status"] = "on_shell_necessary_condition_met"
            channels.append(record)
    if used_lines != set(meanings):
        raise ValueError("channel interpretation refers to an absent source channel")
    counts = {}
    for row in channels:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {"schema_version": 1, "status": "conditional_threshold_diagnosis", "channels": channels,
            "status_counts": counts, "physics_validated": False, "execution_authorized": False,
            "condition": "For a massive on-shell parent and on-shell final states: M_parent >= sum(m_daughters).",
            "mass_convention": context["mass_convention"], "scope": "Exact arithmetic conditional on supplied masses and declared final-state interpretations.",
            "limitations": ["A met necessary condition is not sufficient for a physical decay or a nonzero width.",
                "Equality is a threshold boundary, not a claim of open phase space.",
                "Inclusive off-shell resonances, mother mass distributions and finite-width effects need separate differential evidence.",
                "Supplemental PDG/mass/unit token presence on a pinned source line does not prove their semantic association or particle-model applicability.",
                "Missing masses are never replaced with SM defaults; negative arbitrary masses remain unresolved."]}
