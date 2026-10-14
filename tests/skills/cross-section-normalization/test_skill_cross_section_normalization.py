"""Synthetic cross-section interpolation and delivered-yield audits."""
import copy

import pytest

from ravel.physics import normalization_ledger as nl

SKILL = 'cross-section-normalization'


def ledger():
    return {'schema_version': 1, 'sample': 'synthetic weighted sample',
            'luminosity': {'value': 2., 'unit': 'fb^-1', 'source': 'synthetic assumption'},
            'sigma': {'value': 1., 'unit': 'pb', 'order': 'LO', 'tool': 'synthetic calculator',
                      'pdf': 'synthetic PDF', 'scales': 'synthetic fixed scale',
                      'process_basis': 'synthetic production', 'source': 'synthetic table'},
            'generated': {'sumw': 4., 'sumw2': 14., 'n_events': 3, 'requested_N': 10},
            'selected': {'region': {'sumw': [2., -1.], 'sumw2': [4., 1.], 'bin_edges': [0., 2., 6.]}},
            'bin_convention': 'per-bin', 'denominator': 'sumw'}


def test_record_lists_tested_blocks(handbook):
    assert handbook.listed(SKILL) == ['audit-normalization', 'interpolate-supplied-table']


def test_signed_sums_and_units_are_audited(handbook):
    audit = handbook.load(SKILL, 'audit-normalization')['audit_normalization']
    report = audit(ledger(), {'region': [1000., -500.]})
    assert report['passed'] and report['expected']['region']['errors'] == [1000., 500.]
    equivalent = ledger(); equivalent['sigma'].update(value=1000., unit='fb')
    assert audit(equivalent, {'region': [1000., -500.]})['passed']
    wrong = audit(ledger(), {'region': [1., -.5]})
    assert not wrong['passed']
    assert 'unit_swap' in {r['code'] for r in wrong['failures']}


def test_bin_width_and_requested_count_are_distinct(handbook):
    audit = handbook.load(SKILL, 'audit-normalization')['audit_normalization']
    per_width = ledger(); per_width['bin_convention'] = 'per-unit-width'
    assert audit(per_width, {'region': [500., -125.]})['passed']
    bad = ledger(); bad['denominator'] = 'requested_N'
    assert 'requested_N_denominator' in {r['code'] for r in audit(bad, {})['failures']}


def test_zero_signed_denominator_and_double_correction_fail(handbook):
    audit = handbook.load(SKILL, 'audit-normalization')['audit_normalization']
    zero = ledger(); zero['generated']['sumw'] = 0.
    assert not audit(zero, {})['passed']
    bad = ledger()
    basis = {'final_states': ['synthetic pair'], 'multiplicities': 1, 'generation_cuts': [], 'pdf': 'synthetic PDF'}
    bad['k'] = {'value': 2., 'applied_once': False,
                'numerator_basis': {**basis, 'order': 'NLO'}, 'denominator_basis': {**basis, 'order': 'LO'}}
    assert 'k_applied_twice' in {r['code'] for r in audit(bad, {})['failures']}
    bad['k']['applied_once'] = True
    bad['k']['numerator_basis']['multiplicities'] = 2
    assert 'k_basis_mismatch' in {r['code'] for r in audit(bad, {})['failures']}


def test_published_grid_interpolation_never_extrapolates(handbook):
    interpolate = handbook.load(SKILL, 'interpolate-supplied-table')['interpolate_supplied_table']
    entry = {'basis': 'synthetic', 'parameters': [{'name': 'mass', 'key_level': 0}]}
    data = {'100': {'xsec_pb': 1., 'unc_pb': .1}, '400': {'xsec_pb': .25, 'unc_pb': .025}}
    sigma, uncertainty, _ = interpolate(entry, data, {'mass': 200.})
    assert sigma == pytest.approx(.5)
    assert uncertainty['relative_up'] == pytest.approx(.1)
    with pytest.raises(ValueError, match='no extrapolation'):
        interpolate(entry, data, {'mass': 500.})
    hole = copy.deepcopy(data); hole['400']['xsec_pb'] = 0.
    with pytest.raises(ValueError, match='empty or nonpositive'):
        interpolate(entry, hole, {'mass': 200.})


def test_source_omission_is_refused():
    bad = ledger(); del bad['sigma']['source']
    with pytest.raises(ValueError, match='source'):
        nl.validate(bad)


def test_skill_audit_retains_primary_yields_and_reports_alternate(handbook):
    audit = handbook.load(SKILL, 'audit-normalization')['audit_normalization']
    doc = ledger()
    doc['sigma_alternates'] = [{'order': 'NLO', 'pdf': 'synthetic alternate PDF',
                                'value_pb': 2., 'source': 'synthetic alternate calculator'}]
    report = audit(doc, {'region': [1000., -500.]})
    assert report['passed'] and report['expected']['region']['values'] == [1000., -500.]
    assert report['sigma_alternates'][0]['delivered_total'] == 1000.
    assert report['sigma_alternates'][0]['ratio'] == 2.
