"""Exact P01 response-schema fragment, executable against its published base contract.

The schema owner must apply these same properties to the shared JSON. Until composition,
this function supplies the extended contract to P06 tests without editing the peer file.
"""
from copy import deepcopy


def authority_record(base, *, response=True):
    value = deepcopy(base)
    value['properties']['id'] = {'type': 'string', 'minLength': 1}
    value['properties']['issuer'] = {
        'type': 'object', 'additionalProperties': False,
        'required': ['algorithm', 'key_id', 'mac'],
        'properties': {'algorithm': {'const': 'hmac-sha256'},
                       'key_id': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                       'mac': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}}}
    value['required'] = list(dict.fromkeys([k for k in value['required'] if k != 'id']
                                          + ['issuer'] + (['id'] if response else [])))
    for labels in (value['properties']['label']['enum'],
                   value['allOf'][0]['then']['properties']['label']['enum']):
        if 'terminal_operator_unattested' not in labels:
            labels.append('terminal_operator_unattested')
    rule = {'if': {'properties': {'label': {'const': 'terminal_operator_unattested'}}},
            'then': {'properties': {'authorizes_effects': {'const': False}}}}
    if rule not in value['allOf']:
        value['allOf'].append(rule)
    return value
