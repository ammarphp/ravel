"""The judgment schemas: read from the installed package, references inlined, checked exactly.

Schemas live in ``data/judgment/schemas``. A ``{"$ref": "<file>[#<property>]"}`` names
another schema file of that directory, or one property of it; references are inlined
before checking with the repository's structural validator
(``validate_task_contract._schema_errors``), which evaluates the keywords used here
with exact Python types.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
import json

SCHEMAS = ("question-frame.v1", "judgment-plan.v1", "judgment-record.v1", "judgment-attacks.v1", "action.v1")
PROTOCOL_SCHEMAS = ("P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "recovery")


def _directory():
    return files("ravel").joinpath("data", "judgment", "schemas")


@lru_cache(maxsize=None)
def _raw(name: str) -> str:
    if "/" in name.replace("protocols/", "", 1) or ".." in name or not name.endswith(".json"):
        raise ValueError(f"schema reference {name!r} is outside the judgment schema directory")
    return _directory().joinpath(*name.split("/")).read_text(encoding="utf-8")


ANNOTATIONS = ("title", "description")
MAPPINGS = ("properties",)


def _resolve(node, depth=0):
    """Inline references in one schema object; annotation keywords are dropped from schema
    objects only, never from the property names of a ``properties`` mapping."""
    if depth > 16:
        raise ValueError("judgment schema references nest too deeply")
    if type(node) is dict:
        if "$ref" in node:
            if set(node) != {"$ref"}:
                raise ValueError("a judgment schema reference stands alone")
            target, _, fragment = node["$ref"].partition("#")
            document = json.loads(_raw(target))
            if fragment:
                document = document["properties"][fragment]
            return _resolve(document, depth + 1)
        result = {}
        for key, value in node.items():
            if key in ANNOTATIONS:
                continue
            if key in MAPPINGS and type(value) is dict:
                result[key] = {name: _resolve(item, depth) for name, item in value.items()}
            else:
                result[key] = _resolve(value, depth)
        return result
    if type(node) is list:
        return [_resolve(item, depth) for item in node]
    return node


@lru_cache(maxsize=None)
def _schema(name: str) -> str:
    return json.dumps(_resolve(json.loads(_raw(name))), sort_keys=True)


def schema(name: str) -> dict:
    """The resolved schema ``name`` (``question-frame.v1`` or ``protocols/P2.v1`` and so on)."""
    return json.loads(_schema(name + ".json"))


def errors(name: str, value) -> list[str]:
    """Structural problems of ``value`` against the judgment schema ``name``."""
    from ravel.validation.validate_task_contract import _schema_errors
    return _schema_errors(deepcopy(value), schema(name), "$")


def protocol_errors(protocol: str, value) -> list[str]:
    if protocol not in PROTOCOL_SCHEMAS:
        return [f"$ names unknown protocol evidence {protocol!r}"]
    return errors(f"protocols/{protocol}.v1", value)
