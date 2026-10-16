"""Synthetic descriptor facts and explicit missing-evidence contracts."""
import math

import pytest

from ravel.validation import semantic_composition as semantics


@pytest.mark.parametrize('field,value', [
    ('scale', True), ('scale', math.nan), ('scale', 0),
    ('luminosity', {'value': -1}), ('luminosity', {'scale': math.inf}),
    ('luminosity', {'unit': 'events'}),
    ('event_population', {'events': True}), ('event_population', {'events': 1.0}),
    ('event_population', {'sumw': math.nan}), ('event_population', {'sumw2': -1}),
    ('event_population', {'negative_events': -1}), ('event_population', {'grouping': ''}),
    ('event_population', {'extra': 1}),
    ('applicability', {'parameters': {'x': {'minimum': 2, 'maximum': 1}}}),
    ('applicability', {'parameters': {'x': {'minimum': True}}}),
    ('applicability', {'assumptions': ['']}),
])
def test_invalid_stated_facts_are_errors(field, value):
    errors = semantics.descriptor_errors({field: value})
    assert errors
    assert all({'observed', 'expected', 'repair'} <= set(row) for row in errors)


def test_valid_facts_and_legacy_partial_descriptors():
    quantity = {'scale': 1000, 'event_population': {
        'id': 'sample', 'revision': 'v1', 'grouping': 'event', 'events': 3,
        'sumw': -1, 'sumw2': 3, 'negative_events': 2},
        'luminosity': {'value': 2, 'unit': 'fb^-1', 'scale': 1},
        'applicability': {'id': 'domain', 'parameters': {
            'x': {'minimum': -2, 'maximum': 2, 'unit': ''}}, 'assumptions': ['supplied']}}
    assert semantics.descriptor_errors(quantity) == []
    assert semantics.descriptor_errors({}) == []
    assert semantics.descriptor_errors({'event_population': {}}) == []
    assert semantics.descriptor_errors({'covariance': {'status': 'unknown', 'matrix': None}}) == []


@pytest.mark.parametrize('matrix', [
    [[1, 2], [2, 1]], [[1, 0.1], [0.2, 1]], [[True, 0], [0, 1]],
    [[1, math.nan], [math.nan, 1]], [[1]], [[1, 0]],
    [[-1e-30, 0], [0, -1e-30]],
])
def test_covariance_rejects_wrong_dimensions_nonfinite_and_non_psd(matrix):
    assert semantics.descriptor_errors({'covariance': {
        'status': 'known', 'basis': ['a', 'b'], 'matrix': matrix, 'source': 'supplied'}})


def test_covariance_status_basis_and_singular_psd():
    assert not semantics.descriptor_errors({'covariance': {
        'status': 'known', 'basis': ['a', 'b'], 'matrix': [[1, 1], [1, 1]], 'source': 'supplied'}})
    assert semantics.descriptor_errors({'covariance': {'status': 'known', 'matrix': None}})
    assert semantics.descriptor_errors({'covariance': {'status': 'unknown', 'matrix': [[1]]}})
    assert semantics.descriptor_errors({'covariance': {'basis': ['a', 'a']}})
    assert semantics.descriptor_errors({'covariance': {'source': ''}})


def test_partial_facts_become_nested_obligations_only_when_required():
    requirement = {'required': ['event_population.grouping', 'luminosity.value',
                              'applicability.parameters.x.minimum', 'covariance.matrix']}
    report = semantics.compare({'event_population': {}, 'luminosity': {'unit': 'fb^-1'},
                                'applicability': {'parameters': {'x': {}}}}, requirement, 'edge')
    assert report['errors'] == []
    assert {row['field'] for row in report['obligations']} == set(requirement['required'])
    assert semantics.requirement_errors({'required': ['event_population.extra']})
