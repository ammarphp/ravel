"""Shadow governance derivation: steps of §2.7.1, the v1 diff and the monotone join, on synthetic plans."""
import copy
import json

import pytest

from ravel.workflow import intake_v2_shadow as shadow

SHA = '0' * 64


def _plan(level='expected', measured=False, rung='none', operation='search-statistics', stages_contract=None):
    nodes = [{'id': 'N1', 'kind': 'operation', 'operation': operation, 'implementation': 'science-mode',
              'status': 'available', 'covers': ['original-request'], 'fields': [], 'rung': rung}]
    inputs = [{'id': 'I1', 'source': 'requester', 'status': 'supplied',
               'provides': {'kind': 'binned_values', 'require': {}}}]
    edges = [{'id': 'E1', 'from': {'ref': 'I1', 'slot': 'out'}, 'to': {'ref': 'N1', 'slot': 'signal'},
              'kind': 'binned_values', 'require': {}, 'resolution': 'compatible'},
             {'id': 'E2', 'from': {'ref': 'N1', 'slot': 'limits'}, 'to': {'ref': 'C1', 'slot': 'deliverable'},
              'kind': 'inference', 'require': {}, 'resolution': 'compatible'}]
    if measured:
        inputs.append({'id': 'I2', 'source': 'published', 'status': 'located',
                       'provides': {'kind': 'table', 'require': {'observed': True}}})
        edges.append({'id': 'E3', 'from': {'ref': 'I2', 'slot': 'out'}, 'to': {'ref': 'N1', 'slot': 'measured'},
                      'kind': 'table', 'require': {'observed': True}, 'resolution': 'compatible'})
    claims = [{'id': 'C1', 'kind': 'exclusion', 'statement': 'synthetic', 'obligation_ids': ['original-request'],
               'deliverable': {'artifact': 'inference', 'template': None}, 'level': level,
               'statistic': {'source': 'policy_default', 'definition': '95% CLs', 'evidence': [], 'secondary': []},
               'comparison': {'target': 'none', 'locator': None, 'metric': None, 'tolerance': None},
               'conventions': {'basis_conversion': False}, 'basis_declared': [], 'inherits': []},
              {'id': 'C2', 'kind': 'document', 'statement': 'write-up', 'obligation_ids': ['original-request'],
               'deliverable': {'artifact': 'document', 'template': None}, 'level': 'not_applicable',
               'statistic': {'source': 'not_applicable', 'definition': None, 'evidence': [], 'secondary': []},
               'comparison': {'target': 'none', 'locator': None, 'metric': None, 'tolerance': None},
               'conventions': {'basis_conversion': False}, 'basis_declared': [], 'inherits': ['C1']}]
    return {'schema_version': 1, 'kind': 'request-plan', 'prompt_sha256': SHA, 'reading': {'path': 'r', 'sha256': SHA},
            'signatures': {'path': 'ravel/data/operation_signatures.json', 'entries': {}}, 'status': 'draft',
            'authors': [], 'inputs': inputs, 'nodes': nodes, 'edges': edges, 'claims': claims, 'waypoints': [],
            'boundaries': [], 'coverage': [{'obligation_id': 'original-request', 'by': ['N1']}],
            'aggregate_budget': {}, 'label': {'task_mode': 'research', 'rule': 'D5', 'floor_row': 'research'}}


READING = {'prompt_sha256': SHA, 'facts': [], 'constraints': [], 'ambiguities': [], 'boundaries': [], 'witness': [],
           'dismissed': []}


def test_derive_states_every_step_and_pins_its_inputs():
    governance = shadow.derive(READING, _plan())
    for key in ('lineage', 'bases', 'kind_floor', 'levels', 'effects', 'stages', 'checks', 'checkin1', 'waypoints',
                'review', 'launch', 'layout', 'completion', 'label', 'derivation_sha256', 'signature_entries'):
        assert key in governance, key
    assert list(governance['signature_entries']) == ['search-statistics']
    assert governance['lineage']['C1'] == ['I1', 'N1']
    assert governance['lineage']['C2'] == ['C1', 'I1', 'N1']  # inherits carries the parent's lineage
    assert governance['stages'] == {'statistic': {'level': 'R', 'via': ['N1']}}
    assert 'limit_status' in governance['checks']['claims']['C1']
    assert governance['kind_floor']['C1']['ok'] is True
    assert governance['layout'] == {'C1': 'inference', 'C2': 'document'}


def test_observed_level_is_admitted_only_with_measured_data_in_the_lineage():
    without = shadow.derive(READING, _plan(level='observed'))['levels']['C1']
    assert without == {'declared': 'observed', 'admissible': ['expected'], 'ok': False}
    measured = shadow.derive(READING, _plan(level='observed', measured=True))['levels']['C1']
    assert measured == {'declared': 'observed', 'admissible': ['observed', 'expected'], 'ok': True}
    assert shadow.derive(READING, _plan())['levels']['C2']['admissible'] == ['not_applicable']


def test_compute_effects_raise_the_minimum_rung_review_point_and_launch_requirements():
    governance = shadow.derive(READING, _plan(operation='native-likelihood', rung='smoke'))
    assert governance['effects']['N1'] == {'effects': ['executes_native'], 'minimum_rung': 'smoke', 'rung': 'smoke'}
    assert governance['review']['points'] == [{'node': 'N1', 'kind': 'smoke_review', 'effects': ['executes_native']}]
    assert governance['launch']['nodes']['N1'] == {'maximum_rung': 'smoke', 'go_required': True, 'lease_required': True}
    assert governance['launch']['checkin1_required'] is True


def test_derive_never_mutates_its_inputs():
    plan, reading = _plan(measured=True), copy.deepcopy(READING)
    before = shadow.canonical([reading, plan])
    shadow.derive(reading, plan)
    assert shadow.canonical([reading, plan]) == before


def test_diff_reports_a_stage_v2_requires_that_v1_does_not():
    governance = shadow.derive(READING, _plan())
    contract = {'task_mode': 'calculation'}
    v1 = shadow.applied(contract)
    assert v1['levels']['statistics'] != 'R'
    rows = shadow.diff(governance, contract)['rows']
    assert {'aspect': 'stage:statistics', 'v1': v1['levels']['statistics'], 'v2': 'R', 'direction': 'tightened',
            'via': ['statistic']} in rows


def test_join_keeps_dropped_requirements_and_reports_added_ones():
    heavy = shadow.derive(READING, _plan(operation='native-likelihood', rung='smoke'))
    light = shadow.derive(READING, _plan(operation='measurement'))
    assert heavy['launch']['checkin1_required'] and not light['launch']['checkin1_required']
    joined, report = shadow.join(heavy, light)
    assert joined['launch']['checkin1_required'] is True
    assert joined['launch']['nodes']['N1']['go_required'] is True
    assert set(heavy['checks']['nodes']['N1']) <= set(joined['checks']['nodes']['N1'])
    assert {'aspect': 'checkin1', 'direction': 'dropped', 'kept': True} in report
    assert {'aspect': 'check:N1:limit_status', 'direction': 'dropped', 'kept': True} in report
    _, tightened = shadow.join(light, heavy)
    assert {'aspect': 'check:N1:limit_status', 'direction': 'tightened'} in tightened
    assert not any(r['direction'] == 'dropped' for r in tightened)
    same, nothing = shadow.join(heavy, heavy)
    assert nothing == [] and shadow.canonical(same) == shadow.canonical(heavy)


def test_command_line_summarises_the_shadow_without_writing(tmp_path, capsys):
    prompts = tmp_path / 'prompts.json'
    prompts.write_text(json.dumps(['Compute the leading-order width of a 1 TeV scalar decaying to two photons.']))
    assert shadow.main(['--prompts', str(prompts), '--summary']) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['cases'] == 1 and 'results' not in out
    assert sorted(p.name for p in tmp_path.iterdir()) == ['prompts.json']
    with pytest.raises(SystemExit):
        shadow.main([])
