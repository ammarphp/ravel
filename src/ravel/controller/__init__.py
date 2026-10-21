"""The RAVEL controller: one process that owns a run from intake to delivery.

``ravel drive --request-file`` (and ``ravel ask``) start the ``controller.run`` graph in this
process. The controller reads the request bytes from the user's, operator's or harness's
channel, pins them in a protected store outside the run directory, selects a route from data
(``routes``), compiles a typed plan, takes authority from outside any worker, runs every step
through the governed step graph and delivers through one sink. Model sessions are workers that
step nodes start; they never orchestrate.

Modules: ``store`` (the protected run store and run ownership), ``state`` (the run state),
``graph`` (the ``controller.run`` graph and its wave executor), ``entry`` (the command-line
entries), ``command_policy`` (commands refused for controller-owned runs), ``routes`` (route
selection and the route-spec compiler) and ``testing`` (the in-process test seams).

Importing this package loads no graph framework: the command policy runs on every CLI call.
The helpers below read the controller's JSON schemas from package data.
"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "controller"
SCHEMAS = DATA / "schemas"
NOT_GOVERNED = "NOT GOVERNED"
_SCHEMA_CACHE: dict = {}


def schema(name):
    """The schema ``name`` (for example ``plan.v1``) with every ``{"$ref": "<name>"}`` inlined."""
    if name in _SCHEMA_CACHE:
        return json.loads(_SCHEMA_CACHE[name])
    resolved = _inline(_load(name), (name,))
    _SCHEMA_CACHE[name] = json.dumps(resolved, sort_keys=True)
    return resolved


def _load(name):
    if type(name) is not str or not name or "/" in name or name.startswith("."):
        raise ValueError(f"invalid controller schema name {name!r}")
    path = SCHEMAS / (name + ".json")
    if not path.is_file():
        raise ValueError(f"controller schema {name!r} is not installed")
    from ..workflow.state_io import read_json
    return read_json(path)


def _inline(value, seen):
    if type(value) is dict:
        if set(value) == {"$ref"}:
            target = value["$ref"]
            if target in seen:
                raise ValueError(f"controller schema reference cycle at {target!r}")
            return _inline(_load(target), (*seen, target))
        return {key: _inline(item, seen) for key, item in value.items()}
    if type(value) is list:
        return [_inline(item, seen) for item in value]
    return value


def schema_errors(value, name):
    """Errors of ``value`` against the controller schema ``name`` (the repository's strict subset)."""
    from ..validation.validate_task_contract import _schema_errors
    return _schema_errors(value, schema(name), "$")
