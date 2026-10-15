"""Validation and selection for generated electroweak reference inputs."""
from __future__ import annotations

import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator

_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = _ROOT / "data/sm/schema/ew-inputs.schema.json"
_PDGID = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")


def _schema(path=None):
    return json.loads(Path(path or SCHEMA).read_text(encoding="utf-8"))


def validate_ew_inputs(document, *, schema_path=None):
    """Return a schema-valid bundle whose variant names are database identifiers."""
    errors = sorted(Draft202012Validator(_schema(schema_path)).iter_errors(document), key=str)
    if errors:
        raise ValueError("EW input schema: " + errors[0].message)
    for identifier, row in document["m_w_variants"].items():
        if not _PDGID.fullmatch(identifier) or row["pdgid"] != identifier:
            raise ValueError("m_W variants must be keyed by their PDG identifiers")
    return document


def select_mw_variant(document, pdgid):
    """Select one m_W input by its PDG identifier, never by a human label."""
    validate_ew_inputs(document)
    try:
        return document["m_w_variants"][pdgid]
    except KeyError as exc:
        raise KeyError(f"unknown m_W PDG identifier: {pdgid}") from exc
