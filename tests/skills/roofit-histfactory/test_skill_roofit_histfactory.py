"""Exact source-bin integral witness; no RooFit or Combine process runs."""
from fractions import Fraction

import pytest

from ravel.physics import native_statistical_construction as native

SKILL = 'roofit-histfactory'


def test_record_lists_tested_blocks(handbook):
    assert handbook.listed(SKILL) == ['source-template-integral']


def test_source_values_are_integrals_not_heights(handbook):
    integrate = handbook.load(SKILL, 'source-template-integral')['source_template_integral']
    template = {'edges': ['0', '2', '6'], 'values': ['6', '8']}
    assert integrate(template, ['0', '6']) == Fraction(14)
    assert integrate(template, ['1', '4']) == Fraction(7)
    assert integrate(template, ['8', '9']) == 0


@pytest.mark.parametrize('template', [
    {'edges': ['0', '2', '2'], 'values': ['6', '8']},
    {'edges': ['0', '2', '1'], 'values': ['6', '8']},
    {'edges': ['0', '1e-400'], 'values': ['1']},
])
def test_invalid_or_native_erased_geometry_is_refused(handbook, template):
    integrate = handbook.load(SKILL, 'source-template-integral')['source_template_integral']
    with pytest.raises(ValueError):
        integrate(template, ['0', '1'])


def test_incomplete_graph_is_refused_before_native_execution():
    with pytest.raises(ValueError, match='native constructor'):
        native.validate_document({'schema_version': 2, 'kind': native.KIND})
