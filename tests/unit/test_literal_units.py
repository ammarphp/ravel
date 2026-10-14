"""Exact unit-bearing literal arithmetic (HEP area, luminosity, energy, length, time)."""
from fractions import Fraction

import pytest

from ravel.physics import literal_calculation as lit


def value(expression):
    q = lit.exact_value(expression)
    return Fraction(int(q['numerator']), int(q['denominator'])), q['unit']


@pytest.mark.parametrize('expression,expected,unit', [
    ('2+2', 4, '1'),
    ('2.5 fb * 300 fb^-1', 750, '1'),
    ('0.04 pb * 3000 fb-1 in events', 120000, 'events'),
    ('(7 fb^-1) * (2.0 pb)', 14000, '1'),
    ('1 TeV in GeV', 1000, 'GeV'),
    ('3 TeV + 250 GeV', Fraction(13, 4), 'TeV'),
    ('1.5 nb to pb', 1500, 'pb'),
    ('2e34 cm^-2 s^-1 * 1e7 s in fb^-1', 200, 'fb^-1'),
    ('1.2×10^-3 pb × 139 fb⁻¹', Fraction(834, 5), '1'),
    ('45 fb times 140 fb-1', 6300, '1'),
    ('300 GeV / 2 TeV', Fraction(3, 20), '1'),
    ('3 fb/GeV * 20 GeV in fb', 60, 'fb'),
    ('(2 m)^2 in cm^2', 40000, 'cm^2'),
    ('1 ns * 3 in ps', 3000, 'ps'),
    ('500 MeV - 0.25 GeV in keV', 250000, 'keV'),
])
def test_exact_dimension_tracking(expression, expected, unit):
    assert value(expression) == (Fraction(expected), unit)


def test_dimensionless_record_shape_is_unchanged():
    assert lit.exact_value('6/4') == {'numerator': '3', 'denominator': '2', 'unit': '1',
                                      'representation': 'exact_rational', 'rounding': 'none'}


@pytest.mark.parametrize('expression', [
    '2 GeV + 1 m', '1 GeV in m', '1 pb in events', '3 fb in GeV', '2 parsecs', '2 GeV^1.5',
    '1 pb in', 'in GeV', '2 GeV +', '__import__("os")', '1e5000 GeV',
])
def test_inconsistent_or_unknown_units_refuse(expression):
    with pytest.raises(ValueError):
        lit.exact_value(expression)


@pytest.mark.parametrize('prompt,expression', [
    ('Compute 1.2 pb * 139 fb^-1 in events.', '1.2 pb * 139 fb^-1 in events'),
    ('What is 13 TeV in GeV?', '13 TeV in GeV'),
    ('Calculate 45 fb times 140 fb-1, and give the result in events', '45 fb times 140 fb-1, and give the result in events'),
    ('Convert 3.2 nb to fb', '3.2 nb to fb'),
    ('Evaluate 2 + 3 * 4', '2 + 3 * 4'),
])
def test_prompt_expression_includes_units_and_result_clause(prompt, expression):
    assert lit.expression_from_prompt(prompt) == expression
    lit.exact_value(expression)


def test_result_clause_selects_reported_unit():
    assert value('45 fb times 140 fb-1, and give the result in events') == (6300, 'events')
    assert value('0.5 TeV + 20 GeV, expressed in GeV') == (520, 'GeV')


@pytest.mark.parametrize('prompt', [
    'Compute the partial width of the supplied model in GeV.',
    'Compute 2+2 and derive the physical lifetime in seconds.',
    'What is the expected number of events at the LHC?',
])
def test_prose_requests_are_not_literal(prompt):
    with pytest.raises(ValueError):
        lit.expression_from_prompt(prompt)


def test_task_unit_must_equal_the_computed_unit(tmp_path):
    pin = {'path': str(tmp_path / 'contract.json'), 'sha256': '0' * 64, 'size': 1}
    lit.validate({'parent_contract': pin, 'expression': '1 TeV in GeV', 'unit': 'GeV'})
    with pytest.raises(ValueError):
        lit.validate({'parent_contract': pin, 'expression': '1 TeV in GeV', 'unit': '1'})
    with pytest.raises(ValueError):
        lit.validate({'parent_contract': pin, 'expression': '2+2', 'unit': 'GeV'})


@pytest.mark.parametrize('prompt,unit', [('Compute 2.5 fb * 300 fb^-1 in events', 'events'), ('What is 0.75 TeV in GeV?', 'GeV')])
def test_unit_bearing_request_takes_the_literal_completion_route(tmp_path, prompt, unit):
    from ravel import cli
    from ravel.workflow import calculation_completion
    from ravel.workflow.state_io import read_json
    from intake_scientific_completion_fixture import pin
    root = tmp_path / 'parent'
    assert cli.main(['initiate', '--prompt', prompt, '--out', str(root)]) == 0
    assert read_json(root / 'inputs/task_contract.json')['task_mode'] == 'calculation'
    cp = pin(root / 'inputs/task_contract.json')
    route = calculation_completion.completion_route(cp, base_dir=root)
    assert route['literal'] is True
    expression = lit.expression_from_prompt(prompt)
    parent = lit.validate_parent({'parent_contract': cp, 'expression': expression, 'unit': unit}, root)
    assert parent['quantity']['unit'] == unit and parent['unit'] == unit
