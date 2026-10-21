"""P06: the published authority-record schema is the response contract the service actually returns.

The committed JSON equals the executable helper's response variant, the stored body has its own
explicit variant, and an unattested terminal label can never authorize effects.
"""
from __future__ import annotations

from copy import deepcopy
import json
from importlib.resources import files

import pytest
from jsonschema import Draft202012Validator

from test_p06_support import autonomous, frozen_store, operator_home, view  # noqa: F401
from ravel.controller.authority import common, request
from ravel.controller.authority.schema import authority_record

PATH = files('ravel').joinpath('data/controller/schemas/authority-record.v1.json')


def committed():
    return json.loads(PATH.read_text())


def without_defs(schema):
    return {k: v for k, v in schema.items() if k != '$defs'}


def test_committed_schema_equals_the_response_helper():
    schema = committed()
    assert without_defs(schema) == authority_record(without_defs(schema), response=True)
    assert 'id' in schema['required'] and 'issuer' in schema['required']
    assert schema['additionalProperties'] is False
    assert set(schema['properties']) >= {'id', 'issuer'}
    assert 'terminal_operator_unattested' in schema['properties']['label']['enum']
    assert 'terminal_operator_unattested' in schema['allOf'][0]['then']['properties']['label']['enum']


def test_stored_body_variant_is_explicit_and_lacks_the_id():
    schema = committed()
    stored = schema['$defs']['stored_body']
    assert 'id' not in stored['required'] and 'issuer' in stored['required']
    assert stored['additionalProperties'] is False
    assert authority_record(stored, response=False) == stored
    assert stored['properties'] == schema['properties']


def test_a_real_request_return_and_its_stored_body_validate(operator_home, tmp_path):
    schema = committed()
    response, stored = Draft202012Validator(without_defs(schema)), Draft202012Validator(schema['$defs']['stored_body'])
    autonomous()
    store = frozen_store(tmp_path)
    record = request(store, 'approve_plan', {'view': view(store, 'approve_plan', plan_sha256='a' * 64)}, {'rung': 'full'})
    assert 'id' in record and list(response.iter_errors(record)) == []
    body = store.read('authority', record['id'])
    assert 'id' not in body and list(stored.iter_errors(body)) == []
    # the response form requires the id the stored body does not carry
    assert list(response.iter_errors(body))


def test_unattested_label_cannot_authorize_effects(operator_home, tmp_path):
    schema = committed()
    response = Draft202012Validator(without_defs(schema))
    autonomous()
    store = frozen_store(tmp_path)
    record = request(store, 'approve_plan', {'view': view(store, 'approve_plan', plan_sha256='a' * 64)}, {'rung': 'full'})
    unattested = {**deepcopy(record), 'label': 'terminal_operator_unattested', 'authorizes_effects': False}
    assert list(response.iter_errors(unattested)) == []  # positive control
    forged = {**unattested, 'authorizes_effects': True}
    assert list(response.iter_errors(forged))
    stored = Draft202012Validator(schema['$defs']['stored_body'])
    body = {k: v for k, v in forged.items() if k != 'id'}
    assert list(stored.iter_errors(body))
