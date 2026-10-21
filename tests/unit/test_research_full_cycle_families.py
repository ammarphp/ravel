"""Direct stage and CLI session policy uses current charged worker observations.

Only delivered model transport responses are inert. The declared-card override
retains a former family preference to demonstrate that it is descriptive.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ravel.workflow import agent_graph, agent_host, role_registry, transport_registry
from ravel.workflow import research_cycle as cycle, research_protocol as protocol
from ravel.workflow import research_coordinator_decisions as decisions
from test_agent_graph import external_response
from test_research_full_cycle_authority import campaign, authorize
from test_research_default_protocol import synthetic_artifacts
from test_research_cycle import write


@pytest.fixture
def declared_pair(monkeypatch):
    original = role_registry.load

    def load(role, **kwargs):
        card = deepcopy(original(role, **kwargs))
        if role == 'sufficiency-verifier':
            card['model']['distinct_family_from'] = ['limitation-census']
        return card

    monkeypatch.setattr(role_registry, 'load', load)


def prepare(tmp_path, *, same=False):
    root = campaign(tmp_path)
    artifact = write(root / 'census.json', synthetic_artifacts(root)['limitation_census'])
    authorize(root, protocol.stage_action('limitation_census', artifact))
    prepared = protocol.prepare_stage(root, 'limitation_census', artifact, root / 'first-stage',
        model='gpt-5', adapter='external', role_models={
            'limitation-census': {'model': 'gpt-5'},
            'sufficiency-verifier': {'model': 'gpt-5' if same else 'claude-x'}},
        max_output_tokens=1024, max_wall_seconds=900)
    return root, prepared


def delivered(tmp_path, models):
    root, prepared = prepare(tmp_path)
    graph = root / 'first-stage/graph'
    spec = protocol._method_json(prepared['specification'], root)
    cycle.execute_graph(root, graph, spec, agent_host.AgentHost())
    for role in prepared['roles']:
        request = agent_graph.prepare_external(graph, role)
        fields = json.loads(Path(request['request_file']).read_text())['parameters']['output_schema']['properties']
        value = {key: fields[key]['const'] for key in ('stage', 'role_id', 'subject_sha256')}
        value.update(verdict='accept', findings=['Fictional independently attributed transport.'], attributed_claim_ids=[])
        response = external_response(request, root / (role + '-response.json'), value=value,
            actor_id='fictional-' + role, invocation_id='fictional-' + role,
            observed_model=models[role])
        agent_graph.deliver_external(graph, role, response)
    return root, prepared, graph


def test_XF04_direct_preparation_keeps_same_family_separate_seats(tmp_path, declared_pair):
    root, prepared = prepare(tmp_path, same=True)
    assert len(prepared['roles']) == 2
    assert (root / 'first-stage').exists()


def test_XF04_screen_same_family_is_labelled_pending_session_credit():
    checks = decisions.stage_family_check(None, 'screen',
        {'screen-producer': 'claude-x', 'plan-critic': 'claude-y'})
    assert checks['plan-critic']['family_check'] == 'same'
    assert checks['plan-critic']['session_check'] == 'pending'


@pytest.mark.parametrize('entry', ['api', 'cli'])
def test_XF04_same_family_observed_delivery_completes_via_direct_api_or_cli(
        tmp_path, declared_pair, entry):
    root, prepared, graph = delivered(tmp_path,
        {'limitation-census': 'claude-x', 'sufficiency-verifier': 'claude-y'})
    if entry == 'api':
        protocol.complete_stage(root, prepared, graph)
    else:
        request = write(root / 'complete-request.json', {'prepared': prepared, 'graph_root': str(graph)})
        protocol.main(['stage-complete', '--cycle', str(root), '--request', request['path']])
    checks = decisions.receipt_family_check('limitation_census', graph, {}, root=root)
    assert checks['sufficiency-verifier']['family_check'] == 'same'
    assert checks['sufficiency-verifier']['session_check'] == 'distinct'
    assert protocol.methodology_status(root)['next_stage'] == 'ideas'


def prior_stage(tmp_path):
    root, prepared, graph = delivered(tmp_path,
        {'limitation-census': 'claude-x', 'sufficiency-verifier': 'gpt-5'})
    protocol.complete_stage(root, prepared, graph)
    custom = deepcopy(protocol.default_protocol())
    acceptance = next(s for s in custom['stages'] if s['id'] == 'acceptance')
    acceptance['roles'] = ['sufficiency-verifier']
    acceptance['required_inputs'] = ['limitation_census']
    return root, prepared, graph, custom


def test_later_reviewer_compares_actual_prior_producer_instead_of_requested_model(tmp_path, declared_pair):
    root, _, _, custom = prior_stage(tmp_path)
    receipt = decisions.bound_stage_receipt(root, 'limitation-census', stage_id='limitation_census')
    assert receipt['transport']['observed_model'] == 'claude-x'
    same = decisions.stage_family_check(root, 'acceptance', {'sufficiency-verifier': 'claude-y'}, custom)
    assert same['sufficiency-verifier']['family_check'] == 'same'
    result = decisions.stage_family_check(root, 'acceptance', {'sufficiency-verifier': 'gpt-5'}, custom)
    assert result['sufficiency-verifier']['family_check'] == 'different'


@pytest.mark.parametrize('damage', ['missing', 'stale'])
def test_later_family_check_refuses_missing_or_stale_prior_observation(tmp_path, declared_pair, damage):
    root, _, _, custom = prior_stage(tmp_path)
    row = protocol.methodology_status(root)['record']['stages'][0]
    pin = row['worker_receipts']['limitation-census']
    path = Path(pin['path'])
    if not path.is_absolute(): path = root / path
    raw = path.read_bytes()
    if damage == 'missing':
        path.unlink()
    else:
        path.write_bytes(raw + b'\n')
    with pytest.raises((ValueError, OSError)):
        decisions.stage_family_check(root, 'acceptance', {'sufficiency-verifier': 'gpt-5'}, custom)


def test_declared_not_applicable_prior_stage_keeps_its_actual_observations(tmp_path, declared_pair, monkeypatch):
    """Roles that reviewed a declared not_applicable artifact did run; their receipts still bind later checks.

    Only the route classification is fixed here, so this stage may be declared
    not_applicable; decision authority, dispatch and completion stay real.
    """
    monkeypatch.setattr(protocol, 'stage_inapplicable', lambda stage_id, root: stage_id == 'limitation_census')
    root = campaign(tmp_path)
    artifact = write(root / 'census-not-applicable.json',
                     {'status': 'not_applicable', 'reason': 'Fictional route-computed inapplicability.'})
    authorize(root, protocol.stage_action('limitation_census', artifact))
    prepared = protocol.prepare_stage(root, 'limitation_census', artifact, root / 'first-stage',
        model='gpt-5', adapter='external', role_models={
            'limitation-census': {'model': 'gpt-5'}, 'sufficiency-verifier': {'model': 'claude-x'}},
        max_output_tokens=1024, max_wall_seconds=900)
    graph = root / 'first-stage/graph'
    cycle.execute_graph(root, graph, protocol._method_json(prepared['specification'], root), agent_host.AgentHost())
    for role, model in (('limitation-census', 'claude-x'), ('sufficiency-verifier', 'gpt-5')):
        request = agent_graph.prepare_external(graph, role)
        fields = json.loads(Path(request['request_file']).read_text())['parameters']['output_schema']['properties']
        value = {key: fields[key]['const'] for key in ('stage', 'role_id', 'subject_sha256')}
        value.update(verdict='accept', findings=['Fictional review of the declared inapplicability.'],
                     attributed_claim_ids=[])
        agent_graph.deliver_external(graph, role, external_response(request, root / (role + '-response.json'),
            value=value, actor_id='fictional-' + role, invocation_id='fictional-' + role, observed_model=model))
    protocol.complete_stage(root, prepared, graph)
    row = protocol.methodology_status(root)['record']['stages'][0]
    assert row['status'] == 'not_applicable' and set(row['worker_receipts']) == set(row['roles'])
    receipt = decisions.bound_stage_receipt(root, 'limitation-census', stage_id='limitation_census')
    assert receipt['transport']['observed_model'] == 'claude-x'
    custom = deepcopy(protocol.default_protocol())
    acceptance = next(s for s in custom['stages'] if s['id'] == 'acceptance')
    acceptance['roles'] = ['sufficiency-verifier']
    acceptance['required_inputs'] = ['limitation_census']
    same = decisions.stage_family_check(root, 'acceptance', {'sufficiency-verifier': 'claude-y'}, custom)
    assert same['sufficiency-verifier']['family_check'] == 'same'
    assert decisions.stage_family_check(root, 'acceptance', {'sufficiency-verifier': 'gpt-5'},
                                        custom)['sufficiency-verifier']['family_check'] == 'different'
