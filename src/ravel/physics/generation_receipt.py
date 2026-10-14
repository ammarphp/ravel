"""The generation receipt handed from parton-level generation to the shower and detector stages.

``generation-receipt.json`` records what produced each LHE file: generator name,
version and selection, the executed cards with sha256, the process and model
(UFO) identity, beams and PDF, events generated and accepted, the cross section
with its source and convention, the event-weight convention and any LHE
transform applied before the shower. A batch of parameter points carries one
entry per point.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

SCHEMA_VERSION = 1
POINT_KEYS = ("id", "overrides", "seed", "events", "cards", "cross_section", "lhe")


def file_record(path, root):
    path = Path(path)
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"path": str(path.relative_to(root)), "sha256": h, "size": path.stat().st_size}


def cross_section(value_pb, error_pb, *, events, source):
    return {"value_pb": value_pb, "error_pb": error_pb, "unit": "pb", "order": "LO",
            "source": source, "events_in_estimate": events,
            "convention": "Leading-order matrix-element cross section after the run card's generator-level cuts; "
                          "the error is the integration uncertainty only (no scale, PDF or higher-order uncertainty)."}


def point(identity, overrides, seed, audit, cards, lhe):
    return {"id": identity, "overrides": overrides, "seed": seed,
            "events": {"generated": audit["events"], "accepted": audit["events"]},
            "cards": cards,
            "cross_section": cross_section(audit["cross_section_pb"], audit["integration_error_pb"],
                                           events=audit["events"], source="LHE <init> XSECUP/XERRUP summed over processes"),
            "lhe": lhe}


def build(*, generator, process, model, beams, pdf, points, weight_convention, cross_section_only,
          transform=None, shower=None):
    doc = {"schema_version": SCHEMA_VERSION, "kind": "generation-receipt",
           "generator": generator, "process": process, "model": model, "beams": beams, "pdf": pdf,
           "weights": {"idwtup": weight_convention,
                       "nominal": "uniform positive event weights (unweighted events)",
                       "normalization": "sum of event weights equals the cross section in pb (IDWTUP +-3/+-4)",
                       "named_weights": []},
           "cross_section_only": cross_section_only, "points": points,
           "transform": transform, "shower": shower, "physics_validated": False}
    errors = validate(doc)
    if errors:
        raise ValueError("invalid generation receipt: " + "; ".join(errors))
    return doc


def validate(doc):
    """Structural checks a consumer runs before reading the LHE files."""
    errors = []
    if type(doc) is not dict or doc.get("schema_version") != SCHEMA_VERSION or doc.get("kind") != "generation-receipt":
        return ["generation-receipt schema 1 required"]
    for key in ("generator", "process", "model", "beams", "pdf", "weights", "points"):
        if key not in doc:
            errors.append(f"missing {key}")
    if errors:
        return errors
    if not doc["generator"].get("version"):
        errors.append("generator version required")
    if type(doc["points"]) is not list or not doc["points"]:
        return errors + ["at least one point required"]
    ids = [p.get("id") for p in doc["points"]]
    if len(set(ids)) != len(ids):
        errors.append("point ids must be unique")
    for p in doc["points"]:
        if set(p) != set(POINT_KEYS):
            errors.append(f"point {p.get('id')}: fields {sorted(POINT_KEYS)} required")
            continue
        xs = p["cross_section"]
        if not (type(xs.get("value_pb")) in (int, float) and xs["value_pb"] > 0
                and type(xs.get("error_pb")) in (int, float) and xs["error_pb"] >= 0 and xs.get("source")):
            errors.append(f"point {p['id']}: positive cross section with error and source required")
        if p["events"]["accepted"] > p["events"]["generated"] or p["events"]["generated"] < 1:
            errors.append(f"point {p['id']}: inconsistent event counts")
        if not doc.get("cross_section_only") and not p["lhe"]:
            errors.append(f"point {p['id']}: LHE file record required")
        for card in p["cards"]:
            if set(card) != {"name", "path", "sha256", "size"}:
                errors.append(f"point {p['id']}: cards need name, path, sha256 and size")
    if doc.get("transform") is not None and doc["transform"].get("required_downstream_settings") is None:
        errors.append("transform record needs its required downstream settings")
    return errors


def check_files(doc, root):
    """Re-hash every card and LHE file the receipt names, relative to ``root``."""
    root = Path(root)
    bad = []
    for p in doc["points"]:
        for record in [*p["cards"], *([p["lhe"]] if p["lhe"] else [])]:
            path = root / record["path"]
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
                bad.append(record["path"])
    return bad
