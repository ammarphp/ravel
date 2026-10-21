"""Synthetic normalization applicability controls; no scientific execution."""
from copy import deepcopy

import pytest

from ravel.workflow.normalization_policy import normalization_disposition


def analytic_plan():
    return {
        'nodes': [{'id': 'N1', 'kind': 'operation', 'operation': 'formula-grid', 'fields': []}],
        'inputs': [{'id': 'I1', 'source': 'published', 'status': 'located',
                    'provides': {'kind': 'expression', 'require': {}}}],
        'claims': [{'id': 'C1', 'inherits': ['N1'],
                    'deliverable': {'artifact': 'binned_values'}}],
        'edges': [{'id': 'E1', 'from': {'ref': 'I1', 'slot': 'expression'},
                   'to': {'ref': 'N1', 'slot': 'formula'}, 'kind': 'expression',
                   'require': {}, 'resolution': 'compatible'}],
    }


def test_formula_grid_pure_analytic_has_explicit_absence_evidence():
    plan = analytic_plan()
    result = normalization_disposition(plan, 'C1')
    assert result['disposition'] == 'not_applicable'
    assert result['reason'] == 'proven_pure_analytic_binned_values'
    evidence = result['evidence']
    assert evidence['ancestor_node_ids'] == ['N1']
    assert evidence['ancestor_ids'] == ['I1', 'N1']
    assert evidence['unresolved_lineage'] == []
    assert evidence['normalization_facts'] == []
    assert evidence['missing_normalization'] == {
        'cross_section_facts': 'absent', 'luminosity_facts': 'absent',
        'weights_facts': 'absent', 'normalization_facts': 'absent',
        'normalization_ledger_signature_check': 'absent',
    }
    assert evidence['signature_checks'] == [
        {'node_id': 'N1', 'operation': 'formula-grid',
         'checks': ['io_contract', 'formula_check_value']}]
    assert normalization_disposition(deepcopy(plan), 'C1') == result


def test_review_policy_records_pure_analytic_disposition_and_retains_normalized_yields(tmp_path):
    import hashlib
    import json
    from ravel.workflow import review_points
    plan = analytic_plan()
    folder = tmp_path / 'inputs'
    folder.mkdir()
    def pin():
        raw = json.dumps(plan).encode()
        (folder / 'plan.json').write_bytes(raw)
        (folder / 'task_contract.json').write_text(json.dumps({
            'agent_layer_epoch': 2, 'request_plan': {
                'path': str(folder / 'plan.json'), 'sha256': hashlib.sha256(raw).hexdigest()}}))
    pin()
    check = 'check:physics.normalization_ledger.check'
    row = review_points.check_classification(tmp_path, [check])['checks'][check]
    assert row['applies'] is False and row['reason'] == 'no_normalized_binned_claim'
    disposition = row['evidence']['claim_dispositions'][0]
    assert disposition['evidence']['ancestor_node_ids'] == ['N1']
    assert disposition['evidence']['missing_normalization']['weights_facts'] == 'absent'
    plan['nodes'][0]['fields'] = [{'pointer': '/task/cross_section_pb', 'value': 2}]
    pin()
    row = review_points.check_classification(tmp_path, [check])['checks'][check]
    assert row['applies'] is True and row['points']


@pytest.mark.parametrize('field', [
    '/task/normalization/cross_section_pb', '/task/luminosity_fb',
    '/task/weights', '/task/quantity/weight_convention',
])
def test_analytic_operation_with_normalization_pointer_stays_applicable(field):
    plan = analytic_plan()
    plan['nodes'][0]['fields'] = [{'pointer': field, 'value': 1}]
    result = normalization_disposition(plan, 'C1')
    assert result['applicable']
    assert 'typed_normalization_facts' in result['evidence']['triggers']
    assert result['evidence']['normalization_facts'][0]['value'] == field


@pytest.mark.parametrize('where', ['node', 'input', 'claim', 'edge'])
def test_nested_typed_normalization_facts_on_all_lineage_records(where):
    plan = analytic_plan()
    target = {'node': plan['nodes'][0], 'input': plan['inputs'][0]['provides']['require'],
              'claim': plan['claims'][0], 'edge': plan['edges'][0]['require']}[where]
    target['quantity'] = {'normalization': {'per_luminosity': False},
                          'cross_section_pb': 0, 'weights': []}
    assert normalization_disposition(plan, 'C1')['applicable']


def test_normalized_columnar_yield_requires_audit():
    plan = analytic_plan()
    plan['nodes'][0]['operation'] = 'columnar-analysis'
    plan['nodes'][0]['fields'] = [{'pointer': '/selection_origin', 'value': 'reimplemented'}]
    result = normalization_disposition(plan, 'C1')
    assert result['applicable']
    assert 'simulation_basis' in result['evidence']['triggers']


@pytest.mark.parametrize('mutation', [
    'unknown_operation', 'unknown_ref', 'untyped_input', 'missing_input',
    'unresolved_edge', 'authored_node', 'no_analytic_basis',
])
def test_unknown_or_incomplete_binned_lineage_never_gains_exception(mutation):
    plan = analytic_plan()
    if mutation == 'unknown_operation':
        plan['nodes'][0]['operation'] = 'unregistered-operation'
    elif mutation == 'unknown_ref':
        plan['claims'][0]['inherits'].append('N404')
    elif mutation == 'untyped_input':
        plan['inputs'][0]['provides']['kind'] = ''
    elif mutation == 'missing_input':
        plan['edges'] = []
    elif mutation == 'unresolved_edge':
        plan['edges'][0]['resolution'] = 'unresolved'
    elif mutation == 'authored_node':
        plan['nodes'][0]['kind'] = 'authored'
    elif mutation == 'no_analytic_basis':
        plan['nodes'] = []
        plan['edges'] = []
        plan['claims'][0]['inherits'] = ['I1']
        plan['claims'][0]['basis_declared'] = ['analytic']
    result = normalization_disposition(plan, 'C1')
    assert result['applicable']
    assert result['reason'] == 'binned_lineage_not_proven_pure_analytic'
    assert result['evidence']['unresolved_lineage']
    assert 'missing_normalization' not in result['evidence']


def test_awaited_expression_keeps_its_known_normalization_semantics():
    plan = analytic_plan()
    plan['inputs'][0]['status'] = 'awaited'
    assert not normalization_disposition(plan, 'C1')['applicable']


def test_normalization_is_inherited_through_claims():
    plan = analytic_plan()
    plan['claims'].append({'id': 'C2', 'inherits': ['C1'],
                           'deliverable': {'artifact': 'binned_values'}})
    plan['claims'][0]['quantity'] = {'weight_convention': 'signed'}
    result = normalization_disposition(plan, 'C2')
    assert result['applicable']
    assert result['evidence']['ancestor_node_ids'] == ['N1']
    assert any(f['ref'] == 'C1' for f in result['evidence']['normalization_facts'])


def test_signature_normalization_requirement_applies_without_named_facts():
    from ravel.validation.validate_request_plan import signatures
    plan = analytic_plan()
    registry = deepcopy(signatures())
    registry['formula-grid']['review']['checks'].append('normalization_ledger')
    result = normalization_disposition(plan, 'C1', reg=registry)
    assert result['applicable']
    assert 'signature_normalization_ledger' in result['evidence']['triggers']


@pytest.mark.parametrize('trigger', ['absolute_yield', 'basis', 'none', 'typed_fact'])
def test_non_binned_claim_preserves_existing_triggers(trigger):
    plan = analytic_plan()
    claim = plan['claims'][0]
    claim['deliverable']['artifact'] = 'scalar'
    if trigger == 'absolute_yield':
        claim['absolute_yield'] = True
    elif trigger == 'basis':
        claim['basis_declared'] = ['generated_prediction']
    elif trigger == 'typed_fact':
        claim['quantity'] = {'luminosity_fb': 1}
    assert normalization_disposition(plan, claim)['applicable'] == (trigger in {'absolute_yield', 'basis'})
