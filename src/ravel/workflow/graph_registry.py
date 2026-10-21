"""Registered substrate graphs: identity, version, scope, roles, gates and interrupts.

A row's integer ``version`` (with every reachable subgraph's) is part of the thread
id and is recorded, never keyed, in effect receipts. It is bumped on any change to
routing, to the node bodies of model work, or to requests; ``structure_sha256``
makes a routing change without a bump fail at build. An edit that keeps behaviour
keeps the version and stays resumable. Response schemas for
typed interrupts live beside the registry under ``responses/<schema_id>.json``.

A package that owns a graph may register it as a fragment, ``registration/<graph id>.json``
(``{"schema_version": 1, "kind": "graph-registration", "graphs": [<row>, ...]}``), instead of
editing ``registry.json``. Fragment rows are validated against the same schema; an id that
appears twice anywhere is refused.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from importlib import import_module
from pathlib import Path
import re

from . import graph_environment  # noqa: F401  (strict msgpack before any LangGraph import)
from .state_io import read_json

DATA = Path(__file__).resolve().parents[1] / "data" / "graphs"
REGISTRY = DATA / "registry.json"
SCHEMA = DATA / "registry.schema.json"
RESPONSES = DATA / "responses"
REGISTRATION = DATA / "registration"
SCHEMA_ID = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
PIN = "pin-on-first-build"  # fixture rows only (``registered``): the first build records the digest
_EXTRA: list[dict] = []
_REPLACED: set = set()
_BUILDERS: dict = {}


class RegistryError(ValueError):
    """A graph or response schema is unregistered or malformed."""


def _schema_errors(value, schema):
    from ..validation.validate_task_contract import _schema_errors as errors
    return errors(value, schema, "$")


def fragments(directory=None):
    """Rows of the registration fragments (``registration/*.json``), validated, in file order."""
    rows = []
    directory = Path(directory) if directory is not None else REGISTRATION
    if not directory.is_dir():
        return rows
    schema = read_json(SCHEMA)
    for path in sorted(directory.glob("*.json")):
        document = read_json(path)
        if (type(document) is not dict or document.get("schema_version") != 1
                or document.get("kind") != "graph-registration" or type(document.get("graphs")) is not list
                or set(document) != {"schema_version", "kind", "graphs"}):
            raise RegistryError(f"graph registration {path.name} must be "
                                '{"schema_version": 1, "kind": "graph-registration", "graphs": [...]}')
        problems = _schema_errors({"schema_version": 1, "kind": "graph-registry", "graphs": document["graphs"]},
                                  schema)
        if problems:
            raise RegistryError(f"graph registration {path.name} invalid: " + "; ".join(problems))
        rows.extend(document["graphs"])
    return rows


def load(path=None):
    document = read_json(path or REGISTRY)
    problems = _schema_errors(document, read_json(SCHEMA))
    if problems:
        raise RegistryError("graph registry invalid: " + "; ".join(problems))
    installed = document["graphs"] + (fragments() if path is None else [])
    rows = [row for row in installed if row["id"] not in _REPLACED] + deepcopy(_EXTRA)
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise RegistryError("graph registry has a duplicate id")
    for row in _EXTRA:
        checked = {**row, "structure_sha256": "0" * 64} if row.get("structure_sha256") == PIN else row
        problems = _schema_errors({**document, "graphs": [checked]}, read_json(SCHEMA))
        if problems:
            raise RegistryError("graph registry row invalid: " + "; ".join(problems))
    return rows


def get(graph_id):
    for row in load():
        if row["id"] == graph_id:
            return row
    raise RegistryError(f"graph {graph_id!r} is not registered")


def pin_structure(graph_id, digest):
    """Record a fixture row's structure digest at its first build; later builds must match it."""
    for row in _EXTRA:
        if row["id"] == graph_id and row.get("structure_sha256") == PIN:
            row["structure_sha256"] = digest
            return digest
    raise RegistryError(f"graph {graph_id!r} has no pinnable fixture row")


def builder(row):
    if row["id"] in _BUILDERS:
        return _BUILDERS[row["id"]]
    function = getattr(import_module(row["module"]), row["builder"], None)
    if not callable(function):
        raise RegistryError(f"graph {row['id']} builder {row['module']}.{row['builder']} is not callable")
    return function


def check_instance(row, instance):
    if type(instance) is not dict or set(instance) != set(row["instance_keys"]):
        raise RegistryError(f"graph {row['id']} instance requires exactly {sorted(row['instance_keys'])}")
    return instance


@contextmanager
def registered(*rows, builders=None, replace=False):
    """Add rows (and optional in-process builders) for a block; tests and fixtures only.

    ``replace`` lets the rows stand in for installed rows with the same ids. A controller process
    refuses this seam unless the test harness enabled it (SW30).
    """
    from ..controller.testing import SeamRefused, refuse_for_controller
    try:
        refuse_for_controller("graph registration")
    except SeamRefused as exc:
        raise RegistryError(str(exc)) from None
    before, before_builders, before_replaced = list(_EXTRA), dict(_BUILDERS), set(_REPLACED)
    _EXTRA.extend(deepcopy(list(rows)))
    _BUILDERS.update(builders or {})
    if replace:
        _REPLACED.update(row["id"] for row in rows)
    try:
        load()
        yield
    finally:
        _EXTRA[:] = before
        _BUILDERS.clear()
        _BUILDERS.update(before_builders)
        _REPLACED.clear()
        _REPLACED.update(before_replaced)


def response_schema(schema_id):
    if type(schema_id) is not str or not SCHEMA_ID.fullmatch(schema_id):
        raise RegistryError("invalid response schema id")
    path = RESPONSES / (schema_id + ".json")
    if not path.is_file():
        raise RegistryError(f"response schema {schema_id!r} is not registered")
    return read_json(path)


def response_errors(schema_id, value):
    return _schema_errors(value, response_schema(schema_id))


def schema_ids():
    return sorted(p.stem for p in RESPONSES.glob("*.json"))
