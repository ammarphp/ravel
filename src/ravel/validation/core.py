"""Mechanical record checks; these checks confer no scientific authority.

The bounded schema dialect intentionally excludes references and extensions.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache

PRIVATE_FIELDS = {"chain_of_thought", "private_reasoning", "reasoning_trace", "scratchpad"}
SCHEMA_KEYS = {"type", "properties", "required", "additionalProperties", "items", "enum", "const",
               "minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum", "description", "title", "anyOf"}
JSON_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}


class MechanicalValidationError(ValueError):
    """A repairable structural failure with a bounded diagnostic."""


def _diagnostic(value, depth=0):
    """Render bounded public structure without revealing private field contents."""
    if depth > 6:
        return "<nested value>"
    if type(value) is dict:
        return {key: "<redacted>" if key in PRIVATE_FIELDS else _diagnostic(item, depth + 1)
                for key, item in list(value.items())[:16]}
    if type(value) in (list, tuple):
        return [_diagnostic(item, depth + 1) for item in value[:16]]
    if type(value) is str:
        return value[:240]
    if value is None or type(value) in (bool, int, float):
        return value
    return "<" + type(value).__name__ + ">"


def fail(field, observed, expected, *, repair="repair the supplied record", message="invalid record"):
    try:
        rendered = repr(_diagnostic(observed))
    except (ValueError, OverflowError, RecursionError):
        rendered = "<unrenderable value>"
    if len(rendered) > 240:
        rendered = rendered[:237] + "..."
    error = MechanicalValidationError(
        f"{message}; field={field}; observed={rendered}; expected={expected}; repair={repair}")
    error.legacy_message = message
    error.field = field
    error.observed = rendered
    error.expected = expected
    error.repair = repair
    raise error


def closed_object(value, required, optional=(), *, field="$", error=MechanicalValidationError,
                  message="invalid record"):
    """Require declared keys only, including exact dict runtime type."""
    required, optional = set(required), set(optional)
    if (type(value) is not dict or required - set(value)
            or set(value) - required - optional):
        expected = f"object with exactly fields {sorted(required)!r}"
        if optional:
            expected += f" and optional fields {sorted(optional)!r}"
        try:
            fail(field, value, expected, message=message)
        except MechanicalValidationError as exc:
            if error is MechanicalValidationError:
                raise
            raise error(str(exc)) from exc
    return value


def finite_number(value, *, field="$", minimum=None, maximum=None):
    """Reject booleans, nonnumbers, overflow and nonfinite numeric values."""
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid or (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        fail(field, value, f"finite number in [{minimum}, {maximum}]")
    return value


def pin(value, expected, *, field="$"):
    """Require JSON equality without bool/numeric coercion."""
    if not same_json(value, expected):
        fail(field, value, f"pinned value {_diagnostic(expected)!r}", repair="restore the declared pin or obtain a new contract")
    return value


def _text(value, label, maximum=100_000):
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise MechanicalValidationError(f"invalid {label}")


def _integer(value, label, minimum=1, maximum=10_000_000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise MechanicalValidationError(f"invalid {label}")


def _json_bytes(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise MechanicalValidationError("invalid public JSON") from exc

def same_json(left, right):
    # JSON Schema numeric equality treats 1 and 1.0 alike, while a boolean is
    # distinct from a number. Scientific anchor type checks remain separate.
    if type(left) in (int, float) and type(right) in (int, float):
        return left == right
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return set(left) == set(right) and all(same_json(left[key], right[key]) for key in left)
    if type(left) is list:
        return len(left) == len(right) and all(same_json(a, b) for a, b in zip(left, right))
    return left == right



def _check_schema_body(schema, depth=0, field="$schema"):
    """Validate an explicit finite JSON-schema subset before any transport call."""
    if depth > 32 or type(schema) is not dict or set(schema) - SCHEMA_KEYS:
        raise MechanicalValidationError("unsupported output schema")
    types = schema.get("type")
    if isinstance(types, str):
        types = [types]
    if not isinstance(types, list) or not types or any(type(t) is not str or t not in JSON_TYPES for t in types) or len(set(types)) != len(types):
        raise MechanicalValidationError("output schema requires supported explicit types")
    # A pure object union keeps every alternative closed and fully required.
    # It permits versioned records without admitting partially specified objects.
    if set(schema) == {'type', 'anyOf'} and schema['type'] == 'object':
        choices = schema['anyOf']
        if type(choices) is not list or not 1 <= len(choices) <= 16:
            raise MechanicalValidationError('bounded output alternatives required')
        for index, choice in enumerate(choices):
            _check_schema(choice, depth + 1, f"{field}.anyOf[{index}]")
            if choice['type'] != 'object':
                raise MechanicalValidationError('object alternatives require object type')
        return
    for key in ("description", "title"):
        if key in schema:
            _text(schema[key], "schema annotation", 4096)
    if "object" in types:
        properties, required = schema.get("properties"), schema.get("required")
        if (type(properties) is not dict or type(required) is not list
                or any(type(key) is not str or key in PRIVATE_FIELDS for key in properties)
                or any(type(key) is not str for key in required)
                or len(set(required)) != len(required) or set(required) != set(properties)
                or schema.get("additionalProperties") is not False):
            raise MechanicalValidationError("object output schemas require all properties and no additional fields")
        for key, nested in properties.items():
            _check_schema(nested, depth + 1, f"{field}.properties[{key!r}]")
    elif any(key in schema for key in ("properties", "required", "additionalProperties")):
        raise MechanicalValidationError("object schema fields require object type")
    if "array" in types:
        _check_schema(schema.get("items"), depth + 1, f"{field}.items")
    elif "items" in schema:
        raise MechanicalValidationError("array schema fields require array type")
    for key in ("minItems", "maxItems", "minLength", "maxLength"):
        if key in schema:
            _integer(schema[key], "schema bound", 0)
            needed = "array" if key.endswith("Items") else "string"
            if needed not in types:
                raise MechanicalValidationError("output schema bound does not apply to its type")
    for key in ("minimum", "maximum"):
        if key in schema:
            try:
                valid = type(schema[key]) in (int, float) and math.isfinite(schema[key])
            except OverflowError:
                valid = False
            if not valid:
                raise MechanicalValidationError("schema bounds must be finite numbers")
        if key in schema and not {"integer", "number"}.intersection(types):
            raise MechanicalValidationError("output schema bound does not apply to its type")
    for lower, upper in (("minimum", "maximum"), ("minItems", "maxItems"), ("minLength", "maxLength")):
        if lower in schema and upper in schema and schema[lower] > schema[upper]:
            raise MechanicalValidationError("inverted output schema bounds")
    if "enum" in schema and (type(schema["enum"]) is not list or not schema["enum"]):
        raise MechanicalValidationError("schema enum requires values")
    if "anyOf" in schema:
        if type(schema["anyOf"]) is not list or not 1 <= len(schema["anyOf"]) <= 16:
            raise MechanicalValidationError("bounded output alternatives required")
        for index, choice in enumerate(schema["anyOf"]):
            _check_schema(choice, depth + 1, f"{field}.anyOf[{index}]")



def _check_schema(schema, depth=0, field="$schema"):
    try:
        _check_schema_body(schema, depth, field)
    except MechanicalValidationError as exc:
        if "; field=" in str(exc):
            raise
        fail(field, schema, "bounded explicit closed output schema", message=str(exc),
             repair="repair the supplied schema before dispatch")


def validate_schema(schema, depth=0):
    """Admit only the historical bounded, closed output-schema dialect."""
    _check_schema(schema, depth)
    try:
        _json_bytes(schema)
    except MechanicalValidationError as exc:
        fail("$schema", schema, "finite serializable schema", message=str(exc),
             repair="repair the supplied schema before dispatch")


def _enum_keyword(validator, choices, instance, schema):
    from jsonschema import ValidationError
    if all(not same_json(instance, choice) for choice in choices):
        yield ValidationError("value does not equal a declared JSON enum value")


def _const_keyword(validator, expected, instance, schema):
    from jsonschema import ValidationError
    if not same_json(instance, expected):
        yield ValidationError("value does not equal the declared JSON constant")


def _properties_keyword(validator, properties, instance, schema):
    if not validator.is_type(instance, "object"):
        return
    # Legacy matching visits supplied fields in record order after shape checks.
    for key, value in instance.items():
        if key in properties:
            yield from validator.descend(value, properties[key], path=key, schema_path=key)


def _ordered_keywords(schema):
    # Legacy refusal precedence is semantic, independent of schema key order:
    # type, conditional alternatives, literals, object shape, then child values.
    priority = {"type": 0, "anyOf": 1, "enum": 2, "const": 3,
                "required": 4, "additionalProperties": 5, "properties": 6, "items": 7}
    return sorted(schema.items(), key=lambda pair: priority.get(pair[0], 8))


@lru_cache(maxsize=1)
def _strict_validator():
    # Bootstrap consumers use finite JSON and diagnostics before dependencies
    # are installed. Schema consumers still use the same strict library rules.
    from jsonschema import Draft202012Validator, validators
    checker = Draft202012Validator.TYPE_CHECKER.redefine_many({
        "integer": lambda checker, value: type(value) is int,
        "number": lambda checker, value: type(value) in (int, float),
        "object": lambda checker, value: type(value) is dict,
        "array": lambda checker, value: type(value) is list,
        "string": lambda checker, value: type(value) is str,
        "boolean": lambda checker, value: type(value) is bool,
    })
    return validators.create(
        meta_schema=Draft202012Validator.META_SCHEMA,
        validators={**Draft202012Validator.VALIDATORS, "enum": _enum_keyword,
                    "const": _const_keyword, "properties": _properties_keyword},
        type_checker=checker, applicable_validators=_ordered_keywords)


def __getattr__(name):
    if name == 'StrictValidator':
        return _strict_validator()
    raise AttributeError(name)


def validate_value(value, schema):
    """Validate admitted schemas using jsonschema, preserving strict JSON types."""
    try:
        _json_bytes(value)
    except MechanicalValidationError as exc:
        fail("$", value, "finite serializable JSON", message=str(exc))
    issue = next(_strict_validator()(schema).iter_errors(value), None)
    if issue is None:
        return value
    phrases = {
        "type": "public JSON does not match output schema",
        "anyOf": "public JSON does not match conditional output alternatives",
        "enum": "public JSON does not match output enum",
        "const": "public JSON does not match output constant",
        "required": "public JSON object fields do not match schema",
        "additionalProperties": "public JSON object fields do not match schema",
    }
    field = "$" + "".join(f"[{part!r}]" for part in issue.absolute_path)
    fail(field, issue.instance, f"{issue.validator} {_diagnostic(issue.validator_value)!r}",
         message=phrases.get(issue.validator, "public JSON exceeds output schema bound"))


_PIN_SCHEMA = {
    "type": "object", "required": ["path", "sha256"], "additionalProperties": False,
    "properties": {"path": {"type": "string", "minLength": 1, "pattern": r"\S"},
                   "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$", "minLength": 64, "maxLength": 64}},
}
@lru_cache(maxsize=1)
def _pin_validator():
    return _strict_validator()(_PIN_SCHEMA)


def validate_pin(value, *, field="$"):
    """Check an exact path/digest record; does not read or authenticate its file."""
    issue = next(_pin_validator().iter_errors(value), None)
    if issue is not None:
        located = field + "".join(f"[{part!r}]" for part in issue.absolute_path)
        fail(located, issue.instance, "exact {path: nonempty string, sha256: 64 lowercase hex characters}",
             repair="supply the exact file path and digest from the source bytes")
    return value


def finite_json_tree(value, *, field="$", max_depth=64, reject_private=False, maximum_bytes=None):
    """Require finite strict JSON of any shape with a bounded nesting depth.

    A byte limit and the public-field privacy fence are explicit caller policies.
    This checks structure only, without scientific interpretation or coercion.
    """
    pending = [(value, field, 0)]
    while pending:
        item, located, depth = pending.pop()
        if depth > max_depth:
            fail(located, "<nested value>", f"JSON nesting depth <= {max_depth}")
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                fail(located, item, "JSON object with string keys")
            if reject_private and PRIVATE_FIELDS.intersection(item):
                fail(located, item, "public fields without private reasoning")
            pending.extend((child, located + f"[{key!r}]", depth + 1) for key, child in item.items())
        elif type(item) is list:
            pending.extend((child, located + f"[{index}]", depth + 1) for index, child in enumerate(item))
        elif type(item) is float:
            finite_number(item, field=located)
        elif item is not None and type(item) not in (str, int, bool):
            fail(located, item, "strict JSON value")
    encoded = _json_bytes(value)
    if maximum_bytes is not None and len(encoded) > maximum_bytes:
        fail(field, f"{len(encoded)} bytes", f"complete JSON <= {maximum_bytes} bytes")
    return value
