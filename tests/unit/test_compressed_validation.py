"""Trace fidelity, weighted covariance and honest reference incompleteness."""
import copy
import gzip
import json
import math
from pathlib import Path

import pytest

from ravel.physics import compressed_validation as validation
from ravel.physics import native_simpleanalysis as native


def event(event_id, weight, accepted=True):
    row = validation.new_event(event_id, weight)
    for key in row['predicates']:
        if key not in validation.UNAVAILABLE:
            row['predicates'][key] = True
    for key in ('met_low', 'risr_low', 'subleading_pt_low'):
        row['predicates'][key] = False
    row['predicates']['b_veto'] = accepted
    row['accepted_regions'] = ['SR_S_high_eMT2a'] if accepted else []
    return row


def report(tmp_path, rows, metadata=None):
    path = tmp_path/'trace.jsonl.gz'
    validation.write_trace(path, rows, metadata or {})
    return validation.summarize_trace(path)


def test_nested_weighted_covariance_and_all_input_population(tmp_path):
    result = report(tmp_path, [event(10, 2), event(20, 1), event(30, 3, False)])
    row = next(row for row in result['cutflows']['high'] if row['predicate']=='b_veto')
    assert result['all_events']['count'] == 3
    assert row['count'] == 2 and row['sumw_pb'] == 3 and row['sumw2_pb2'] == 5
    assert row['conditional']['ratio'] == .5
    assert row['conditional']['mc_standard_error'] == pytest.approx(math.sqrt(3.5/36))
    assert result['first_comparable_reference_divergence'] is None
    assert result['truth_acceptance']['status'] == 'unavailable'


def test_early_rejection_and_unknown_are_distinct(tmp_path):
    early = validation.new_event(1, 2)
    early['predicates']['bad_jet_veto'] = False
    unresolved = validation.new_event(2, 1)
    result = report(tmp_path, [early, unresolved])
    assert result['all_events']['count'] == 2
    for row in result['cutflows']['high']:
        assert row['count'] == 0
        assert row['unknown_count'] == 1
        assert row['cumulative']['status'] == 'unresolved'


@pytest.mark.parametrize('mutation', ['duplicate', 'weight', 'predicate', 'promote_trigger', 'membership'])
def test_inconsistent_or_fabricated_trace_fails(tmp_path, mutation):
    rows = [event(1, 1)]
    if mutation == 'duplicate': rows.append(copy.deepcopy(rows[0]))
    elif mutation == 'weight': rows[0]['weight_pb'] = math.nan
    elif mutation == 'predicate': del rows[0]['predicates']['b_veto']
    elif mutation == 'promote_trigger': rows[0]['predicates']['trigger'] = True
    else: rows[0]['accepted_regions'] = []
    with pytest.raises(ValueError): report(tmp_path, rows)


def test_public_reference_requires_matching_declared_point(tmp_path):
    path = tmp_path/'trace.gz'
    validation.write_trace(path, [event(1,1)], {'masses_gev':[150,130]})
    with pytest.raises(ValueError, match='m150/140'):
        validation.summarize_trace(path, tmp_path)


def test_public_reference_preserves_missing_rows_and_luminosity(tmp_path):
    import yaml
    for name in ('table_22.yaml', 'table_23.yaml'):
        (tmp_path/name).write_text(yaml.safe_dump({'dependent_variables':[{'values':[{'value':28-i} for i in range(28)]}]}))
    path = tmp_path/'trace.gz'
    validation.write_trace(path, [event(1,.001)], {'masses_gev':[150,140]})
    result = validation.summarize_trace(path,tmp_path)
    rows = result['reference_cutflows']['high']['rows']
    assert next(x for x in rows if x['predicate']=='author16_veto')['native_cumulative_weighted_events_at_reference_lumi'] is None
    assert next(x for x in rows if x['predicate']=='b_veto')['native_cumulative_weighted_events_at_reference_lumi'] == 140
    assert all(x['status']=='diagnostic_only_unmatched_prior_predicates' for x in rows)


def objects():
    return {'el_pt':[[12.]], 'el_eta':[[.6]], 'el_phi':[[.2]], 'el_charge':[[-1]], 'el_id':[[0x7fffffff]],
            'mu_pt':[[7.]], 'mu_eta':[[-.6]], 'mu_phi':[[-.2]], 'mu_charge':[[1]], 'mu_id':[[0x7fffffff]],
            'jet_pt':[[150.]], 'jet_eta':[[1.8]], 'jet_phi':[[3.]], 'jet_m':[[10.]],
            'jet_id':[[native.LooseBadJet | native.JVT50Jet]], 'met_pt':[250.], 'met_phi':[0.]}


def test_hook_keeps_original_selection_and_records_early_no_jet():
    arrays = objects()
    arrays['jet_pt'] = [[]]; arrays['jet_eta'] = [[]]; arrays['jet_phi'] = [[]]
    arrays['jet_m'] = [[]]; arrays['jet_id'] = [[]]
    row = validation.new_event(19,.02)
    assert native.select_objects(arrays,0,trace=row) is None
    assert row['predicates']['bad_jet_veto'] is True
    assert row['predicates']['signal_jet'] is False
    assert row['predicates']['two_signal_leptons'] is True
    assert row['predicates']['trigger'] is None
    assert row['objects']['signal_jets'] == 0


def test_trace_hook_preserves_sr_and_cr_return_shape(tmp_path):
    arrays = objects()
    row = validation.new_event(19,.02)
    selected = native.select_objects(arrays,0,trace=row)
    assert selected is not None
    plain = native.select_regions(selected,.75,30,include_controls=True)
    traced = native.select_regions(selected,.75,30,include_controls=True,trace=row)
    assert plain == traced
    assert row['kinematics']['mt2_test_mass'] == 100
    assert set(row['accepted_regions']) == plain[0]
    assert row['predicates']['same_flavour'] is False
    result = report(tmp_path,[row])
    assert result['all_events']['sumw_pb'] == .02


def test_trace_preserves_signed_and_zero_weights(tmp_path):
    result = report(tmp_path,[event(1,2),event(2,-1),event(3,0)])
    assert result['all_events']['count'] == 3
    assert result['all_events']['sumw_pb'] == 1
    assert result['all_events']['sumw2_pb2'] == 5


def test_zero_selection_never_reports_certified_zero_uncertainty(tmp_path):
    result = report(tmp_path,[event(1,1,False)])
    row = next(x for x in result['cutflows']['high'] if x['predicate']=='b_veto')
    assert row['conditional']['ratio'] == 0
    assert row['conditional']['status'] == 'zero_selected_precision_unresolved'
    assert row['conditional']['mc_standard_error'] is None


def test_truncated_population_cannot_be_an_honest_smaller_denominator(tmp_path):
    with pytest.raises(ValueError,match='population'):
        report(tmp_path,[event(1,1)],{'input_events':2})
