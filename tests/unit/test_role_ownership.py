"""Synthetic quantity authority, staged production and fit boundary controls."""
from copy import deepcopy

import pytest

from ravel.workflow import agent_graph, role_registry as roles, sfitter_workflow as fit


def staged_document():
    document = roles.registry_document()
    for identity in ('routine-constructor', 'upstream-agentrivet-coder'):
        card = roles.load(identity)
        card['ownership']['inputs'] = ['analysis-routine']
        document['roles'][identity] = {'card': card, 'override': None}
    return document


def assignments():
    return {'draft': 'routine-constructor', 'revision': 'upstream-agentrivet-coder'}


def handoff(source='draft', target='revision'):
    return {'kind': 'analysis-routine', 'from': source, 'to': target}


def node(identity, role, depends=()):
    return {'id': identity, 'kind': 'model', 'role': 'designer', 'registry_role': role,
            'depends_on': list(depends), 'inputs': [], 'packet': None,
            'action': 'fixture', 'parameters': {}, 'max_attempts': 1}


def graph(nodes, **extra):
    return {'schema_version': 1, 'graph_id': 'synthetic-ownership',
            'budget': {'max_nodes': 8, 'max_calls': 8, 'max_output_tokens': 100,
                       'max_wall_seconds': 60, 'max_reworks': 0},
            'nodes': nodes, **extra}


def test_duplicate_producers_are_refused():
    with pytest.raises(ValueError, match='duplicate ownership'):
        roles.validate_ownership(assignments())


def test_explicit_output_to_input_handoff_is_admitted():
    result = roles.validate_ownership(assignments(), [handoff()], document=staged_document())
    assert result == {'analysis-routine': 'revision'}


def test_reviewer_cannot_own_even_with_a_producer_output_schema():
    card = roles.load('physics-critic')
    card['ownership']['owns'] = ['analysis-routine']
    card['output']['schema'] = 'producer.v1'
    assert any('only a producer' in e for e in roles.validate_card(card))


def test_reviewer_cannot_claim_producer_independence():
    card = roles.load('physics-critic')
    card['independence']['kind'] = 'producer'
    card['ownership']['owns'] = ['analysis-routine']
    assert any('only a producer' in e for e in roles.validate_card(card))


@pytest.mark.parametrize('field', ['owns', 'judges', 'inputs'])
def test_unknown_quantity_is_refused(field):
    card = roles.load('routine-constructor')
    card['ownership'][field].append('synthetic-unknown')
    assert any('unknown quantity' in e for e in roles.validate_card(card))


def test_producer_must_declare_ownership():
    card = roles.load('routine-constructor')
    card['ownership']['owns'] = []
    assert any('producer must declare' in e for e in roles.validate_card(card))


def test_handoff_requires_declared_input():
    with pytest.raises(ValueError, match='declared consumer input'):
        roles.validate_ownership(assignments(), [handoff()])


@pytest.mark.parametrize('links', [
    [handoff(), handoff()],
    [handoff(), handoff('revision', 'draft')],
    [handoff('draft', 'absent')],
    [handoff('draft', 'draft')],
])
def test_invalid_handoffs_refused(links):
    with pytest.raises(ValueError):
        roles.validate_ownership(assignments(), links, document=staged_document())


def test_branching_or_disconnected_production_refused():
    owners = {**assignments(), 'third': 'routine-constructor'}
    for links in ([handoff()], [handoff(), handoff('draft', 'third')]):
        with pytest.raises(ValueError):
            roles.validate_ownership(owners, links, document=staged_document())


def test_long_handoff_chain_has_one_final_owner():
    owners = {**assignments(), 'third': 'routine-constructor'}
    assert roles.validate_ownership(owners, [handoff(), handoff('revision', 'third')],
                                    document=staged_document()) == {'analysis-routine': 'third'}


def test_required_quantity_cannot_have_no_owner():
    with pytest.raises(ValueError, match='missing owner'):
        roles.validate_ownership({}, required_kinds=['coupling-modifier-extraction'])


def test_graph_refuses_duplicate_and_accepts_scheduled_handoff(monkeypatch):
    document = staged_document()
    monkeypatch.setattr(roles, 'registry_document', lambda **kwargs: deepcopy(document))
    spec = graph([node('draft', 'routine-constructor'),
                  node('revision', 'upstream-agentrivet-coder', ['draft'])])
    with pytest.raises(agent_graph.GraphError, match='duplicate ownership'):
        agent_graph.validate(spec)
    spec['quantity_handoffs'] = [handoff()]
    assert agent_graph.validate(spec) == spec
    spec['nodes'][1]['depends_on'] = []
    with pytest.raises(agent_graph.GraphError, match='scheduling dependency'):
        agent_graph.validate(spec)


def test_graph_refuses_unknown_role_and_missing_required_quantity():
    with pytest.raises(agent_graph.GraphError, match='unregistered role'):
        agent_graph.validate(graph([node('draft', 'synthetic-unknown')]))
    with pytest.raises(agent_graph.GraphError, match='missing owner'):
        agent_graph.validate(graph([node('draft', 'routine-constructor')],
                                   required_quantity_kinds=['coupling-modifier-extraction']))


def test_higgs_in_fit_has_one_owner_per_quantity_and_judges_only_review():
    owners = fit.validate_phase_ownership(higgs=True)
    assert owners['coupling-modifier-extraction'] == 'sf-kappa-extractor'
    assert owners['signal-scale-uncertainty'] == 'sf-scale-uncertainty-estimator'
    assert owners['signal-pdf-uncertainty'] == 'sf-pdf-uncertainty-estimator'
    assert owners['measurement-parameterization-bundle'] == 'higgs-coupling-analyst'
    assert owners['measurement-extraction'] == 'sf-measurement-extractor'
    for identity in ('higgs-combination-reviewer', 'higgs-theory-uncertainty-auditor'):
        assert not roles.load(identity)['ownership']['owns']
        assert roles.load(identity)['ownership']['judges']
    assert all(h['from'] == 'higgs-coupling-analyst' for h in fit.HIGGS_IN_FIT_HANDOFFS)


def test_fit_phase_table_refuses_missing_owner_and_cross_phase_duplicate():
    table = deepcopy(fit.ROLES)
    table['parameterization'] = tuple(r for r in table['parameterization'] if r != 'sf-kappa-extractor')
    with pytest.raises(ValueError, match='missing owner'):
        fit.validate_phase_ownership(roles=table)
    document = roles.registry_document()
    card = roles.load('sf-id-encoder')
    card['ownership']['owns'].append('coupling-modifier-extraction')
    document['roles']['sf-id-encoder'] = {'card': card, 'override': None}
    with pytest.raises(ValueError, match='duplicate ownership'):
        fit.validate_phase_ownership(document=document)
    assert any('duplicate ownership' in e for e in roles.validate_registry(document))


def test_shipped_registry_passes():
    assert roles.validate_registry() == []
    assert all(card['ownership']['owns'] for card in roles.all_cards()
               if card['independence']['kind'] == 'producer')


def worker_node(identity, role, tmp_path, kind='agent'):
    card = roles.load(role)
    worker = {'schema_version': 1, 'kind': 'agent-worker-spec', 'node_id': identity,
              'attempt': 1, 'role': {'id': role, 'version': card['version'],
                                    'card_sha256': roles.card_sha256(role)},
              'transport_preference': ['synthetic-transport'], 'inputs': [],
              'declared_outputs': [], 'budgets': {'max_turns': 1, 'max_wall_seconds': 60,
                                                 'max_broker_calls': 1, 'max_cost_usd': None},
              'final_record_schema': 'producer.v1', 'work_order': None, 'rdj_challenges': None,
              'parent': {'review_point_id': None, 'map_id': None, 'rca_ticket': None}}
    result = node(identity, role)
    result.pop('registry_role')
    if kind == 'map':
        worker = {'schema_version': 1, 'kind': 'agent-map', 'id': identity,
                  'spec': worker, 'items': [{'key': 'one'}], 'join': 'all'}
    result.update(kind=kind, action='dispatch', parameters={'rundir': str(tmp_path), 'spec': worker})
    return result


@pytest.mark.parametrize('kind', ['agent', 'map'])
def test_worker_roles_are_checked_without_optional_binding(tmp_path, kind):
    spec = graph([worker_node('draft', 'routine-constructor', tmp_path, kind),
                  worker_node('revision', 'upstream-agentrivet-coder', tmp_path, kind)])
    with pytest.raises(agent_graph.GraphError, match='duplicate ownership'):
        agent_graph.validate(spec)


@pytest.mark.parametrize('kind', ['agent', 'map'])
def test_worker_binding_cannot_hide_actual_role(tmp_path, kind):
    item = worker_node('draft', 'routine-constructor', tmp_path, kind)
    item['registry_role'] = 'sf-kappa-extractor'
    with pytest.raises(agent_graph.GraphError, match='differs from dispatched worker'):
        agent_graph.validate(graph([item]))


@pytest.mark.parametrize('kind', ['agent', 'map'])
@pytest.mark.parametrize('label', sorted(agent_graph.ROLES))
def test_scheduler_labels_do_not_claim_quantity_ownership(tmp_path, kind, label):
    spec = graph([worker_node('first', label, tmp_path, kind),
                  worker_node('second', label, tmp_path, kind)])
    assert agent_graph.validate(spec) == spec


@pytest.mark.parametrize('kind', ['agent', 'map'])
def test_scheduler_label_worker_can_bind_a_specialist(tmp_path, kind):
    bound = worker_node('draft', 'designer', tmp_path, kind)
    bound['registry_role'] = 'routine-constructor'
    other = worker_node('revision', 'designer', tmp_path, kind)
    other['registry_role'] = 'upstream-agentrivet-coder'
    other['depends_on'] = ['draft']
    with pytest.raises(agent_graph.GraphError, match='duplicate ownership'):
        agent_graph.validate(graph([bound, other]))


def test_independent_proposer_panel_is_admitted(tmp_path):
    spec = graph([worker_node('stream-a', 'idea-proposer-a', tmp_path),
                  worker_node('stream-b', 'idea-proposer-b', tmp_path)])
    assert agent_graph.validate(spec) == spec


def test_role_cannot_judge_its_own_quantity():
    card = roles.load('routine-constructor')
    card['ownership']['judges'] = card['ownership']['owns'][:]
    assert any('judge its own' in e for e in roles.validate_card(card))


def test_bound_specialists_execute_through_the_existing_host(tmp_path):
    from test_sfitter_conductor import fixture, SuppliedHost
    from ravel.workflow import sfitter_conductor
    request, _, request_pin = fixture(tmp_path)
    spec = sfitter_conductor.consultant_graph(request, tmp_path, request_pin)
    root = tmp_path / 'bound-specialists'
    agent_graph.create(root, spec)
    state = agent_graph.execute(root, SuppliedHost({'claims': ['Supplied synthetic draft.']}), workers=1)
    assert state['complete'], state['nodes']
