"""Route selection as data: the ``docs/workflow/start.md`` first-match table, evaluated in code.

Route packages write route specs (``src/ravel/data/controller/routes/<route>.json``, schema
``route-spec.v1``). Each spec's ``match`` names its table row (``row``, the precedence) and a
predicate (``when``) over a fixed view of the intake records: the contract, the reading and the
supplied inputs. ``select`` evaluates the specs in row order and returns the first match.

There is no refusal (JR01). A held request (D1, ``unsupported``), an open parent (the table's
fourth row) and a request no spec matches go to the ``judgment`` route, which plans them as
typed steps under the same governance. A spec that admits no scientific deliverables (an
inspection route) is never selected for a request that has them, so a request phrased as
development keeps its scientific obligations (R01).

Predicate grammar (validated by ``predicate_errors``)::

    {"all": [p, ...]} | {"any": [p, ...]} | {"not": p} | {"field": <name>, <operator>: <value>}

Operators: ``eq``, ``in`` (value is a list), ``contains_any``, ``contains_all`` and ``disjoint``
(the field is a list), ``nonempty`` and ``empty`` (true or false) and ``is`` (a boolean field).
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from .. import DATA, schema_errors

ROUTES = DATA / "routes"
JUDGMENT = "judgment"
OPERATORS = ("eq", "in", "contains_any", "contains_all", "disjoint", "nonempty", "empty", "is")
# The view a predicate reads. Lists are sorted and deduplicated; scalars are strings or booleans.
FIELDS = {
    "task_mode": "scalar", "intake_kind": "scalar", "operation": "scalar", "operation_kind": "scalar",
    "label_rule": "scalar", "label_open": "bool", "held": "bool", "handoff_route": "scalar",
    "supplied_kinds": "list", "supplied_fact_types": "list", "artifact_kinds": "list", "claim_kinds": "list",
    "requested_stages": "list", "negated_stages": "list", "requested_tools": "list",
    "prescribed_statistics": "list", "boundary_classes": "list", "fact_types": "list",
    "constraint_types": "list", "scientific_deliverables": "bool", "deliverable_count": "scalar",
}
# Rows of the table that the controller itself routes to the judgment graph.
BUILTIN = (
    {"id": JUDGMENT, "reason": "open-parent", "match": {"row": 4, "order": 0, "when": {"field": "label_open", "is": True}}},
)
_EXTRA: list = []
_ONLY = [False]


class RouteSpecError(ValueError):
    """A route spec or predicate is malformed."""


class RouteAdapterMissing(LookupError):
    """The adapter module a route spec names is not installed (the controller holds: ``route_adapter_missing``).

    Not a ``RouteSpecError``: a spec error lets a caller go on without the route's hooks, a missing adapter never
    does. An adapter that is installed but fails its own imports raises its own error instead."""

    reason = "route_adapter_missing"

    def __init__(self, route, module):
        super().__init__(f"route {route!r} names the adapter {module}, which is not installed")
        self.route, self.module = route, module


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def spec_sha256(spec):
    return _digest(spec)


# ---- the view -------------------------------------------------------------------------------

def _values(rows, key, inner=None):
    found = set()
    for row in rows or ():
        if type(row) is not dict:
            continue
        value = row.get(key)
        if inner is not None and type(value) is dict:
            value = value.get(inner)
        if type(value) is str and value:
            found.add(value)
    return sorted(found)


def _constraint_values(reading, kind, inner):
    return sorted({str(c["value"].get(inner)) for c in reading.get("constraints") or ()
                   if type(c) is dict and c.get("type") == kind and type(c.get("value")) is dict
                   and c["value"].get(inner) not in (None, "")})


def view(contract, reading, supplied):
    """The facts a match predicate reads, derived from the intake records only."""
    from ...workflow import intake
    contract = contract if type(contract) is dict else {}
    reading = reading if type(reading) is dict else {}
    intent = contract.get("intake") if type(contract.get("intake")) is dict else {}
    deliverables = [d for d in reading.get("deliverables") or () if type(d) is dict]
    artifacts = sorted({(d.get("artifact") or {}).get("kind") for d in deliverables
                        if type(d.get("artifact")) is dict and (d.get("artifact") or {}).get("kind")})
    claims = sorted({d.get("claim_kind") for d in deliverables if type(d.get("claim_kind")) is str})
    try:
        handoff = intake.handoff_route(contract, reading) if contract else None
    except Exception:  # a fact the view cannot derive is absent, never a refusal
        handoff = None
    try:
        open_parent = bool(contract) and intake.open_parent(contract, reading)
    except Exception:
        open_parent = False
    try:
        operation_kind = intake.operation_kind(contract["prompt"]) if type(contract.get("prompt")) is str else None
    except Exception:
        operation_kind = None
    try:
        from ...workflow.derived_label import derive
        label = derive(reading, None, intent=intent if intent.get("source") == "host-agent" else None) \
            if reading.get("kind") else {}
    except Exception:
        label = {}
    scientific = any(((d.get("artifact") or {}).get("kind") not in (None, "document")
                      or d.get("claim_kind") not in (None, "document")) for d in deliverables)
    task_mode = contract.get("task_mode")
    return {
        "task_mode": task_mode if type(task_mode) is str else None,
        "intake_kind": intent.get("kind") if type(intent.get("kind")) is str else None,
        "operation": intent.get("operation") if type(intent.get("operation")) is str else None,
        "operation_kind": operation_kind,
        "label_rule": label.get("rule") if type(label.get("rule")) is str else None,
        "label_open": open_parent,
        "held": task_mode == "unsupported",
        "handoff_route": handoff,
        "supplied_kinds": _values(supplied, "kind"),
        "supplied_fact_types": sorted({f.get("type") for f in reading.get("facts") or ()
                                       if type(f) is dict and f.get("authority") == "supplied"
                                       and type(f.get("type")) is str}),
        "artifact_kinds": artifacts,
        "claim_kinds": claims,
        "requested_stages": _constraint_values(reading, "requested_stage", "stage"),
        "negated_stages": _constraint_values(reading, "negated_stage", "stage"),
        "requested_tools": _constraint_values(reading, "requested_tool", "tool"),
        "prescribed_statistics": _constraint_values(reading, "prescribed_statistic", "statistic"),
        "boundary_classes": _values(reading.get("boundaries"), "class"),
        "fact_types": _values(reading.get("facts"), "type"),
        "constraint_types": _values(reading.get("constraints"), "type"),
        "scientific_deliverables": scientific,
        "deliverable_count": len(deliverables),
    }


# ---- predicates ----------------------------------------------------------------------------

def predicate_errors(predicate, path="when"):
    if type(predicate) is not dict or not predicate:
        return [f"{path} must be a non-empty object"]
    if set(predicate) in ({"all"}, {"any"}):
        key = next(iter(predicate))
        items = predicate[key]
        if type(items) is not list or not items:
            return [f"{path}.{key} must be a non-empty list"]
        return [e for i, item in enumerate(items) for e in predicate_errors(item, f"{path}.{key}[{i}]")]
    if set(predicate) == {"not"}:
        return predicate_errors(predicate["not"], f"{path}.not")
    operators = set(predicate) - {"field"}
    if "field" not in predicate or len(operators) != 1:
        return [f"{path} needs one field and exactly one operator of {OPERATORS}"]
    field, operator = predicate["field"], next(iter(operators))
    value = predicate[operator]
    if field not in FIELDS:
        return [f"{path}.field {field!r} is not a view field ({sorted(FIELDS)})"]
    if operator not in OPERATORS:
        return [f"{path} operator {operator!r} is not one of {OPERATORS}"]
    kind = FIELDS[field]
    if operator in ("nonempty", "empty", "is") and type(value) is not bool:
        return [f"{path}.{operator} takes true or false"]
    if operator == "is" and kind != "bool":
        return [f"{path}: is applies to a boolean field"]
    if operator in ("contains_any", "contains_all", "disjoint"):
        if kind != "list":
            return [f"{path}: {operator} applies to a list field"]
        if type(value) is not list or not value or any(type(v) is not str for v in value):
            return [f"{path}.{operator} takes a non-empty list of strings"]
    if operator == "in" and (type(value) is not list or not value):
        return [f"{path}.in takes a non-empty list"]
    if operator in ("eq", "in") and kind == "list":
        return [f"{path}: {operator} applies to a scalar field"]
    return []


def evaluate(predicate, facts):
    if "all" in predicate:
        return all(evaluate(p, facts) for p in predicate["all"])
    if "any" in predicate:
        return any(evaluate(p, facts) for p in predicate["any"])
    if "not" in predicate:
        return not evaluate(predicate["not"], facts)
    field = predicate["field"]
    operator = next(k for k in predicate if k != "field")
    value, actual = predicate[operator], facts.get(field)
    if operator == "eq":
        return actual == value
    if operator == "in":
        return actual in value
    if operator == "is":
        return actual is value
    if operator in ("nonempty", "empty"):
        present = bool(actual)
        return present is value if operator == "nonempty" else (not present) is value
    actual = set(actual or ())
    if operator == "contains_any":
        return bool(actual & set(value))
    if operator == "contains_all":
        return set(value) <= actual
    return not (actual & set(value))  # disjoint


# ---- specs ----------------------------------------------------------------------------------

def spec_errors(spec):
    errors = schema_errors(spec, "route-spec.v1")
    if errors:
        return errors
    if spec["id"] == JUDGMENT:
        return ["the judgment route is the controller's own; a route spec cannot claim its id"]
    return predicate_errors(spec["match"]["when"], "match.when")


def _read_specs(path):
    from ...workflow.state_io import read_json
    document = read_json(path)
    if type(document) is dict and document.get("kind") == "route-spec-family":
        specs = document.get("specs")
        if type(specs) is not list or not specs:
            raise RouteSpecError(f"{path.name}: a route-spec family lists its specs")
        return specs
    return [document]


def installed_specs():
    """Route specs from the installed package data, validated; a malformed spec is an error."""
    specs = []
    if ROUTES.is_dir():
        for path in sorted(ROUTES.glob("*.json")):
            for spec in _read_specs(path):
                errors = spec_errors(spec)
                if errors:
                    raise RouteSpecError(f"route spec {path.name} is invalid: " + "; ".join(errors[:5]))
                specs.append(spec)
    return specs


def load_specs():
    specs = ([] if _ONLY[0] else installed_specs()) + deepcopy(_EXTRA)
    ids = [s["id"] for s in specs]
    if len(ids) != len(set(ids)):
        raise RouteSpecError("route specs have a duplicate id")
    return specs


@contextmanager
def registered(*specs, only=False):
    """Add route specs for a block (``only``: ignore the installed specs). Test harness only."""
    from ..testing import refuse
    refuse("route-spec registration")
    for spec in specs:
        errors = spec_errors(spec)
        if errors:
            raise RouteSpecError(f"route spec {spec.get('id')!r} is invalid: " + "; ".join(errors[:5]))
    before, before_only = list(_EXTRA), _ONLY[0]
    _EXTRA.extend(deepcopy(list(specs)))
    _ONLY[0] = only or before_only
    try:
        load_specs()
        yield
    finally:
        _EXTRA[:] = before
        _ONLY[0] = before_only


def ordered(specs):
    rows = list(specs) + [dict(b) for b in BUILTIN]
    return sorted(rows, key=lambda s: (s["match"]["row"], s["match"].get("order", 0), s["id"] != JUDGMENT, s["id"]))


def adapter_module(spec):
    """The route's adapter module under ``ravel.controller.routes`` (installed code only), or None.

    An adapter's optional functions: ``parameters(spec, reading, contract, supplied)`` (compile time),
    ``bind(plan, context)``, ``checkin(kind, context)``, ``gate(transition, context)`` and
    ``step(step, outcome, context)`` (run time; ``context`` holds the store, run directory, plan,
    state, reading and contract).

    An adapter that is not installed raises ``RouteAdapterMissing``: the module, or the package that would hold
    it, is absent. Any other import error, a missing dependency of an installed adapter included, propagates.
    """
    name = (spec or {}).get("adapter")
    if not name:
        return None
    if type(name) is not str or not re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*", name):
        raise RouteSpecError(f"route {spec.get('id')!r} names an invalid adapter {name!r}")
    from importlib import import_module
    module = __package__ + "." + name
    try:
        return import_module(module)
    except ModuleNotFoundError as exc:
        # Python imports the parent packages first, so a name on the adapter's own path means it is not installed.
        parts = name.split(".")
        if exc.name not in {__package__ + "." + ".".join(parts[:i]) for i in range(1, len(parts) + 1)}:
            raise
        raise RouteAdapterMissing(spec.get("id"), module) from None


def find(route_id):
    for spec in load_specs():
        if spec["id"] == route_id:
            return spec
    raise RouteSpecError(f"no installed route spec {route_id!r}")


def select(contract: dict, reading: dict, supplied: list[dict]) -> dict:
    """``{"route": <id> | "judgment", "evidence": [...]}``: the first matching row; never a refusal."""
    facts = view(contract, reading, supplied)
    evidence = []
    if facts["held"]:
        evidence.append({"row": 9, "route": JUDGMENT, "matched": True,
                         "reason": "held request (task mode unsupported): capability recovery runs as judgment "
                                   "steps"})
        return {"route": JUDGMENT, "evidence": evidence, "view": facts, "spec_sha256": None, "version": None,
                "row": 9}
    for spec in ordered(load_specs()):
        matched = evaluate(spec["match"]["when"], facts)
        if matched and spec["id"] != JUDGMENT and facts["intake_kind"] == "inspect" \
                and spec.get("admits_scientific_deliverables", True):
            evidence.append({"row": spec["match"]["row"], "route": spec["id"], "matched": False,
                             "reason": "recorded intake classification is inspect; scientific routing needs "
                                       "a resolved intake"})
            continue
        if matched and spec["id"] != JUDGMENT and spec.get("admits_scientific_deliverables", True) is False \
                and facts["scientific_deliverables"]:
            evidence.append({"row": spec["match"]["row"], "route": spec["id"], "matched": False,
                             "reason": "admits no scientific deliverables; the request has them"})
            continue
        evidence.append({"row": spec["match"]["row"], "route": spec["id"], "matched": matched,
                         "reason": spec.get("reason") or ("predicate holds" if matched else "predicate fails")})
        if matched:
            builtin = spec["id"] == JUDGMENT
            return {"route": spec["id"], "evidence": evidence, "view": facts,
                    "spec_sha256": None if builtin else spec_sha256(spec),
                    "version": None if builtin else spec["version"], "row": spec["match"]["row"]}
    evidence.append({"row": None, "route": JUDGMENT, "matched": True,
                     "reason": "no route spec matches: the judgment graph plans the request"})
    return {"route": JUDGMENT, "evidence": evidence, "view": facts, "spec_sha256": None, "version": None, "row": None}


def selection_rows(store):
    """A research request admitted to another route has that route's obligations.

    The recorded first-match decision, recomputed from the pinned intake, is the
    reason. An absent research event is never a reason, and selecting a research
    route alone proves none of its later execution requirements.
    """
    from ..authority.standing import _snapshot
    try:
        reader, _, _ = _snapshot(store)
        if reader.check_binding():
            return {}
        intake = reader.latest('intake')
        route = reader.latest('route')
        if intake is None or route is None or route['seq'] <= intake['seq']:
            return {}
        pins = intake['record']
        contract = json.loads(reader.get_blob(pins['contract_blob']))
        reading = json.loads(reader.get_blob(pins['reading_blob']))
        supplied = reader.latest('supplied')
        inputs = (supplied['record'].get('inputs') or []) if supplied is not None else []
        actual = select(contract, reading, inputs)
        recorded = json.loads(reader.get_blob(route['record']['evidence_blob']))
        if actual != recorded or any(route['record'].get(k) != actual[k]
                                     for k in ('route', 'row', 'spec_sha256', 'version')):
            return {}
        if actual['route'] == 'research':
            return {}  # the selected route must record its own execution
        return {'ROUTE-research': {'status': 'not_applicable', 'evidence': {
            'reason': 'not_applicable:request_admitted_to_another_route',
            'record': route['id'], 'intake_record': intake['id'],
            'sha256': route['record']['evidence_blob'], 'selected_route': actual['route'],
            'task_mode': contract.get('task_mode'), 'mechanism': 'routes.select.first_match'}}}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}
