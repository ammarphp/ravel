"""Synthetic structural contracts for shared mechanical validation."""
import math

import pytest

from ravel.validation import core
from ravel.workflow import agent_host


def record_schema(item):
    return {"type": "object", "properties": {"value": item},
            "required": ["value"], "additionalProperties": False}


@pytest.mark.parametrize("value", [True, 1.0, "1", None])
def test_integer_is_runtime_strict(value):
    with pytest.raises(core.MechanicalValidationError, match="field=.*observed=.*expected=.*repair="):
        core.validate_value({"value": value}, record_schema({"type": "integer"}))


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, True, "1"])
def test_finite_number_refuses_nonfinite_and_coercion(value):
    with pytest.raises(core.MechanicalValidationError):
        core.finite_number(value, field="$.value")


def test_closed_object_and_pin():
    assert core.closed_object({"value": 1}, {"value"}) == {"value": 1}
    assert core.pin({"value": 1}, {"value": 1.0}) == {"value": 1}
    with pytest.raises(core.MechanicalValidationError):
        core.closed_object({"value": 1, "extra": 2}, {"value"})
    with pytest.raises(core.MechanicalValidationError):
        core.pin({"value": True}, {"value": 1})


@pytest.mark.parametrize('value', [{}, {'value': 1, 'unknown': 2}, [], None])
def test_optional_fields_do_not_open_the_object_or_erase_diagnostics(value):
    with pytest.raises(core.MechanicalValidationError) as caught:
        core.closed_object(value, ('value',), ('description',), field='contract')
    assert caught.value.field == 'contract'
    assert caught.value.observed
    assert 'description' in caught.value.expected
    assert caught.value.repair == 'repair the supplied record'
    for record in ({'value': 1}, {'value': 1, 'description': 'supplied'}):
        assert core.closed_object(record, ('value',), ('description',)) is record


def test_closed_object_custom_exception_retains_structured_cause():
    with pytest.raises(RuntimeError) as caught:
        core.closed_object({}, ('value',), field='contract', error=RuntimeError)
    assert caught.value.__cause__.field == 'contract'


@pytest.mark.parametrize("item", [
    {"type": "integer", "minimum": True},
    {"type": "number", "minimum": math.inf},
    {"type": "number", "minimum": 2, "maximum": 1},
    {"type": "string", "maxLength": 10_000_001},
    {"type": "string", "$ref": "#"},
    {"type": "array"},
    {"type": "string", "anyOf": []},
])
def test_schema_subset_refusals(item):
    with pytest.raises(core.MechanicalValidationError, match="repair="):
        core.validate_schema(record_schema(item))


def _closed(**properties):
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


def test_pure_object_union_admits_only_closed_alternatives():
    schema = {"type": "object", "anyOf": [_closed(a={"type": "integer"}), _closed(b={"type": "string"})]}
    core.validate_schema(schema)
    core.validate_value({"a": 1}, schema)
    core.validate_value({"b": "x"}, schema)
    for value in ({}, {"a": 1, "b": "x"}, {"a": "x"}, []):
        with pytest.raises(core.MechanicalValidationError, match="conditional output alternatives|output schema"):
            core.validate_value(value, schema)
    for choices in ([], [_closed(a={"type": "integer"})] * 17,
                    [{"type": "object", "properties": {"a": {"type": "integer"}}}],
                    [{"type": "string"}]):
        with pytest.raises(core.MechanicalValidationError):
            core.validate_schema({"type": "object", "anyOf": choices})


def test_depth_and_private_fields_remain_refused():
    item = {"type": "integer"}
    for _ in range(34):
        item = {"type": "array", "items": item}
    with pytest.raises(core.MechanicalValidationError, match="unsupported output schema"):
        core.validate_schema(item)
    schema = {"type": "object", "properties": {"private_reasoning": {"type": "string"}},
              "required": ["private_reasoning"], "additionalProperties": False}
    with pytest.raises(core.MechanicalValidationError):
        core.validate_schema(schema)


def test_host_delegates_and_retains_failure_contract():
    schema = record_schema({"type": "number", "enum": [1.0]})
    assert agent_host.validate_public_result({"value": 1}, schema) == {"value": 1}
    with pytest.raises(agent_host.HostFailure, match="output schema"):
        agent_host.validate_public_result({"value": True}, schema)
    with pytest.raises(agent_host.HostFailure, match="output enum"):
        agent_host.validate_public_result({"value": 2}, schema)
    with pytest.raises(agent_host.HostFailure, match="invalid public JSON"):
        agent_host.validate_public_result({"value": math.nan}, schema)


def test_alternatives_and_nested_diagnostics():
    schema = record_schema({"type": ["integer", "string"], "anyOf": [
        {"type": "integer", "minimum": 2}, {"type": "string", "minLength": 2}]})
    core.validate_schema(schema)
    core.validate_value({"value": 2}, schema)
    with pytest.raises(core.MechanicalValidationError, match="conditional output alternatives.*value"):
        core.validate_value({"value": 1}, schema)


@pytest.mark.parametrize('value', [
    {'path': '', 'sha256': 'a' * 64}, {'path': '  ', 'sha256': 'a' * 64},
    {'path': 'record', 'sha256': 'A' * 64}, {'path': 'record', 'sha256': '0' * 63},
    {'path': True, 'sha256': 'a' * 64}, {'path': 'record', 'sha256': 'a' * 64, 'extra': 1},
])
def test_exact_file_pin_shape(value):
    with pytest.raises(core.MechanicalValidationError):
        core.validate_pin(value)
    assert core.validate_pin({'path': 'record', 'sha256': 'a' * 64})['path'] == 'record'


def test_finite_json_tree_any_shape_and_explicit_bounds():
    for value in (None, True, 1, 1.5, 'text', [1, {'value': 2}]):
        assert core.finite_json_tree(value) == value
    for value in ([{'value': math.nan}], {1: 'value'}, (1, 2)):
        with pytest.raises(core.MechanicalValidationError):
            core.finite_json_tree(value)
    with pytest.raises(core.MechanicalValidationError, match='nesting'):
        core.finite_json_tree([[1]], max_depth=1)
    with pytest.raises(core.MechanicalValidationError, match='complete JSON'):
        core.finite_json_tree('long', maximum_bytes=2)


def test_private_diagnostics_redact_contents():
    secret = 'hidden-content-marker'
    with pytest.raises(core.MechanicalValidationError) as caught:
        core.finite_json_tree({'private_reasoning': secret}, reject_private=True)
    assert secret not in str(caught.value)
    assert '<redacted>' in str(caught.value)
    with pytest.raises(core.MechanicalValidationError) as caught:
        core.validate_value({'private_reasoning': secret}, {'type': 'integer'})
    assert secret not in str(caught.value)


@pytest.mark.parametrize('number', [math.inf, math.nan])
def test_schema_rejects_nonfinite_constants_in_unused_alternative(number):
    schema = {'type': 'number', 'anyOf': [
        {'type': 'number'}, {'type': 'number', 'const': number}]}
    with pytest.raises(core.MechanicalValidationError, match='invalid public JSON'):
        core.validate_schema(schema)


@pytest.mark.parametrize('keyword,expected', [('const', (1,)), ('enum', [(1,)])])
def test_python_tuple_schema_literals_do_not_coerce_to_json_arrays(keyword, expected):
    schema = {'type': 'array', 'items': {'type': 'integer'}, keyword: expected}
    core.validate_schema(schema)
    with pytest.raises(core.MechanicalValidationError):
        core.validate_value([1], schema)


def test_host_legacy_messages_and_structured_diagnostic_cause():
    schema = record_schema({'enum': ['ready'], 'type': 'string'})
    with pytest.raises(agent_host.HostFailure, match=r'^public JSON does not match output schema$') as caught:
        agent_host.validate_public_result({'value': True}, schema)
    assert caught.value.__cause__.field == "$['value']"
    assert 'repair=' in caught.value.diagnostics
    with pytest.raises(agent_host.HostFailure, match=r'^public JSON does not match output enum$'):
        agent_host.validate_public_result({'value': 'other'}, schema)


def test_conditional_refusal_precedes_nested_literal_refusal():
    schema = record_schema({'enum': ['ready'], 'type': 'string'})
    schema['anyOf'] = [record_schema({'type': 'string', 'enum': ['ready']})]
    with pytest.raises(agent_host.HostFailure, match=r'^public JSON does not match conditional output alternatives$'):
        agent_host.validate_public_result({'value': 'other'}, schema)


def test_supplied_field_order_retains_legacy_first_refusal():
    schema = {'type': 'object', 'required': ['first', 'second'], 'additionalProperties': False,
              'properties': {'first': {'type': 'integer'},
                             'second': {'type': 'string', 'enum': ['ready']}}}
    with pytest.raises(agent_host.HostFailure, match=r'^public JSON does not match output enum$'):
        agent_host.validate_public_result({'second': 'other', 'first': False}, schema)
