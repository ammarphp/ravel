"""Selectable advisory investigator teams; mandatory scientific gates stay separate."""
from copy import deepcopy

import pytest

from ravel.workflow import agent_graph as graph
from test_agent_graph import node, spec, Host, role_packet


def compact(tmp_path):
    packet, _ = role_packet(tmp_path / 'review-context', 'verifier', {'value': 2})
    investigator = node('investigate', kind='model', role='proposer')
    consult = node('consult', ['investigate'], kind='model', role='improver')
    reviewer = node('review', ['consult'], kind='model', role='verifier'); reviewer['packet'] = packet
    plan = spec([investigator, consult, reviewer])
    plan['team_shape'] = {'policy': 'investigator_consult_reviewer', 'investigator': 'investigate',
        'consultations': [{'node': 'consult', 'specialty': 'Supplied normalization arithmetic'}],
        'boundaries': [{'subject': 'consult', 'reviewer': 'review'}]}
    return plan


def test_selected_team_uses_ordinary_calls_and_retains_no_execution_authority(tmp_path):
    plan = compact(tmp_path); root = tmp_path / 'graph'
    graph.create(root, plan)
    state = graph.execute(root, Host())
    assert state['usage']['calls'] == 3 and state['complete']
    assert state['team_shape'] == plan['team_shape']
    assert state['execution_authorized'] is False and state['advisory'] is True
    graph.execute(root, Host())
    assert graph.status(root)['usage']['calls'] == 3


def test_default_plan_bytes_and_dispatch_population_are_unchanged(tmp_path):
    plan = spec([node('investigate', kind='model', role='proposer'),
                 node('consult', ['investigate'], kind='model', role='improver'),
                 node('reconsider', ['consult'], kind='model', role='designer'),
                 node('derive', ['reconsider'], kind='model', role='improver'),
                 node('summarize', ['derive'], kind='model', role='synthesizer')])
    assert graph.validate(plan) == plan and 'team_shape' not in graph.validate(plan)
    root = tmp_path / 'graph'; graph.create(root, plan)
    state = graph.execute(root, Host())
    assert state['usage']['calls'] == 5
    assert state['team_shape'] == {'policy': 'current'}
    assert state['execution_authorized'] is False


@pytest.mark.parametrize('defect', ['hidden_agent', 'map', 'duplicate_actor_node', 'missing_boundary',
    'voting_consultation', 'tool_reviewer', 'missing_subject_dependency', 'unblinded_reviewer', 'unknown_policy'])
def test_compact_policy_rejects_omitted_agents_or_unreviewed_boundaries(tmp_path, defect):
    plan = compact(tmp_path)
    if defect == 'hidden_agent': plan['nodes'].append(node('hidden', kind='model', role='designer'))
    elif defect == 'map':
        # A map would hide a wider worker population behind a single role name.
        plan['team_shape']['consultations'][0]['node'] = 'unlisted-map'
    elif defect == 'duplicate_actor_node': plan['team_shape']['consultations'][0]['node'] = 'investigate'
    elif defect == 'missing_boundary': plan['team_shape']['boundaries'] = []
    elif defect == 'voting_consultation': plan['nodes'][1]['role'] = 'synthesizer'
    elif defect == 'tool_reviewer': plan['nodes'][2]['kind'] = 'tool'
    elif defect == 'missing_subject_dependency': plan['nodes'][2]['depends_on'] = []
    elif defect == 'unblinded_reviewer': plan['nodes'][2]['packet'] = None
    elif defect == 'unknown_policy': plan['team_shape']['policy'] = 'invented'
    with pytest.raises(graph.GraphError): graph.validate(plan)


def test_revision_cannot_switch_ablation_arm_or_remove_required_review(tmp_path):
    plan = compact(tmp_path); root = tmp_path / 'graph'; graph.create(root, plan)
    changed = deepcopy(plan); changed.pop('team_shape'); changed['nodes'][0]['parameters']['new'] = True
    with pytest.raises(graph.GraphError, match='cannot change its selected team-shape'):
        graph.revise(root, changed, reason='Switching would erase the selected arm')
    assert graph.status(root)['reworks'] == 0
