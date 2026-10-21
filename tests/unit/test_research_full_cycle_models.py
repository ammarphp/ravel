"""Per-role stage dispatch controls. All deliveries are inert and fictional."""
import json
from pathlib import Path

import pytest

from ravel.workflow import agent_graph, agent_host, research_cycle, research_protocol as protocol
from ravel.workflow import research_coordinator_decisions as decisions
from ravel.workflow import research_orchestrator as orch
from ravel.workflow.graphs import stage
from test_research_default_protocol import governed_cycle, register, synthetic_artifacts, write
from test_research_loop_graph import EXTERNAL, JUDGES, STAGE_SETTINGS
from test_research_full_cycle import deliver_stage as deliver
from test_agent_graph import external_response


def settings():
    return {**STAGE_SETTINGS, 'tiers': JUDGES, 'roles': {
        'screen-producer': {**EXTERNAL, 'model': 'claude-x'},
        'plan-critic': {**EXTERNAL, 'model': 'gpt-5'}}}


@pytest.fixture
def census(tmp_path, monkeypatch):
    monkeypatch.setattr(protocol, 'decision_errors', lambda *a, **k: [])
    root = governed_cycle(tmp_path, extra_wall_seconds=60)
    artifact = write(root, 'census.json', synthetic_artifacts(root)['limitation_census'])
    return root, artifact


def test_mixed_models_reach_the_stage_preparer():
    options, assigned = stage.model_options('screen', settings())
    assert options['role_models'] == {
        'screen-producer': {**EXTERNAL, 'model': 'claude-x'},
        'plan-critic': {**EXTERNAL, 'model': 'gpt-5'}}
    assert assigned['plan-critic']['family_check'] == 'different'


def test_prepare_stage_assigns_model_effort_and_transport_per_role(census):
    root, artifact = census
    prepared = protocol.prepare_stage(root, 'limitation_census', artifact, root/'review',
        model='claude-x', role_models={
            'sufficiency-verifier': {'model': 'gpt-5', 'reasoning_effort': 'max', 'adapter': 'responses'}})
    spec = json.loads(Path(prepared['specification']['path']).read_text())
    assert [(n['id'], n['action'], n['parameters']['model'], n['parameters']['reasoning_effort'])
            for n in spec['nodes']] == [
                ('limitation-census', 'external', 'claude-x', 'high'),
                ('sufficiency-verifier', 'responses', 'gpt-5', 'max')]
    assert len({n['packet']['path'] for n in spec['nodes']}) == len(prepared['roles'])
    assert spec['budget']['max_calls'] == len(prepared['roles'])


@pytest.mark.parametrize('overrides', [[], {'unknown-role': {}}, {'limitation-census': []},
    {'limitation-census': {'tier': 'judgment'}}, {'limitation-census': {'model': ''}},
    {'limitation-census': {'reasoning_effort': None}}, {'limitation-census': {'adapter': 'command'}},
    {'limitation-census': {'adapter': []}}])
def test_bad_role_settings_refuse_before_packets_or_round_charge(census, overrides):
    root, artifact = census
    before = research_cycle._load(root)[1]
    with pytest.raises(ValueError):
        protocol.prepare_stage(root, 'limitation_census', artifact, root/'review', model='stub', role_models=overrides)
    assert not (root/'review').exists()
    assert research_cycle._load(root)[1] == before


@pytest.mark.parametrize('observed', ['claude-y', None, 'unclassified-model'])
def test_receipt_check_requires_current_campaign_despite_configured_models(monkeypatch, observed):
    monkeypatch.setattr(decisions, 'observed_models', lambda path: {
        'screen-producer': 'claude-x', **({'plan-critic': observed} if observed is not None else {})})
    with pytest.raises(ValueError, match='current campaign required'):
        decisions.receipt_family_check('screen', 'unused', settings())


@pytest.mark.parametrize('changed_model', [False, True])
def test_r2_join_uses_real_separate_packets_and_checks_delivered_models(census, changed_model):
    root, _ = census
    register(root)
    artifacts = synthetic_artifacts(root)
    host = agent_host.AgentHost()
    for name in ('limitation_census', 'ideas', 'baseline'):
        if name == 'ideas':
            from test_research_full_cycle_ideas import actual_ideas
            artifacts[name] = actual_ideas(root, artifacts[name], root/'idea-dispatches')
        out = root/name
        artifact = write(root, name+'.json', artifacts[name])
        assert not orch.run_protocol_stage(root, artifact, out, host=host, settings=STAGE_SETTINGS)['complete']
        deliver(out/'graph')
        assert orch.run_protocol_stage(root, artifact, out, host=host, settings=STAGE_SETTINGS)['complete']
    artifact = write(root, 'screen.json', artifacts['screen'])
    out = root/'screen'
    initial = orch.run_protocol_stage(root, artifact, out, host=host, settings=settings())
    assert not initial['complete'] and set(initial['graph']['nodes']) == {'screen-producer', 'plan-critic'}
    for role in initial['graph']['nodes']:
        request = agent_graph.prepare_external(out/'graph', role)
        document = json.loads(Path(request['request_file']).read_text())
        assigned = document['parameters']['model']
        assert assigned == settings()['roles'][role]['model']
        fields = document['parameters']['output_schema']['properties']
        public = {key: fields[key]['const'] for key in ('stage', 'role_id', 'subject_sha256')}
        public.update(verdict='accept', findings=[], attributed_claim_ids=[])
        observed = 'claude-y' if changed_model and role == 'plan-critic' else assigned
        response = external_response(request, out/(role+'-response.json'), value=public,
            actor_id='inert-'+role, invocation_id='inert-'+role, observed_model=observed)
        agent_graph.deliver_external(out/'graph', role, response)
    assert orch.run_protocol_stage(root, artifact, out, host=host, settings=settings())['complete']
    row = next(r for r in protocol.methodology_status(root)['record']['stages'] if r['id'] == 'screen')
    assert set(row['worker_receipts']) == {'screen-producer', 'plan-critic'}
    for role, pin in row['worker_receipts'].items():
        receipt = protocol._method_json(pin, root)
        expected = 'claude-y' if changed_model and role == 'plan-critic' else settings()['roles'][role]['model']
        assert receipt['transport']['observed_model'] == expected
    checks = decisions.receipt_family_check('screen', out/'graph', settings(), root=root)
    relationship = 'same' if changed_model else 'different'
    assert checks['plan-critic']['family_check'] == relationship
    assert checks['plan-critic']['family_label'] == f'separate session, {relationship} model family'
    assert checks['plan-critic']['session_check'] == 'distinct'
    assert checks['screen-producer']['session_check'] == 'distinct'
    assert agent_graph.status(out/'graph')['usage']['calls'] == 2


def test_partial_stage_resume_cannot_adopt_a_missing_role_or_repeat_completed_calls(census):
    from test_research_full_cycle import deliver_stage
    root, artifact = census
    out, host = root/'stage', agent_host.AgentHost()
    assert not orch.run_protocol_stage(root, artifact, out, host=host, settings=STAGE_SETTINGS)['complete']
    deliver_stage(out/'graph', omit='sufficiency-verifier')
    partial = orch.run_protocol_stage(root, artifact, out, host=host, settings=STAGE_SETTINGS)
    assert not partial['complete']
    assert protocol.methodology_status(root)['next_stage'] == 'limitation_census'
    _, state = research_cycle._load(root)
    ledger = state['resource_ledger']
    first = agent_graph.status(out/'graph')['nodes']['limitation-census']['result']
    deliver_stage(out/'graph')
    assert orch.run_protocol_stage(root, artifact, out, host=host, settings=STAGE_SETTINGS)['complete']
    assert agent_graph.status(out/'graph')['nodes']['limitation-census']['result'] == first
    assert research_cycle._load(root)[1]['resource_ledger'] == ledger
    row = protocol.methodology_status(root)['record']['stages'][0]
    assert row['round'] == 1 and set(row['worker_receipts']) == set(row['roles'])


def test_ordinary_approval_uses_the_engine_pause_without_granting_authority(tmp_path, monkeypatch):
    from ravel.workflow import science, scientific_autonomy
    from ravel.workflow.graphs import DeliveryRequired, pause
    calls = []
    monkeypatch.setattr(science, 'verify_plan', lambda *a, **k: calls.append(k['approved']))
    monkeypatch.setattr(scientific_autonomy, 'observed_run_document', lambda root: (None, {}))
    with pytest.raises(DeliveryRequired) as pending:
        orch._ordinary_approval_gate(tmp_path, selected='fictional', goal_binding={}, pause=pause)
    assert pending.value.payload['kind'] == 'ordinary_checkin1_and_machine_lease_required'
    assert calls == [False] and not (tmp_path/science.APPROVAL).exists()


def test_injected_pause_cannot_replace_an_invalid_existing_approval(tmp_path, monkeypatch):
    from ravel.workflow import science
    path = tmp_path/science.APPROVAL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('invalid retained receipt')
    def invalid(*args, **kwargs):
        assert kwargs['approved'] is True
        raise ValueError('invalid current source binding')
    monkeypatch.setattr(science, 'verify_plan', invalid)
    def cannot_pause(payload):
        pytest.fail('an existing invalid approval cannot request replacement authority')
    with pytest.raises(orch.RecoveryHold, match='never replace'):
        orch._ordinary_approval_gate(tmp_path, selected='fictional', goal_binding={}, pause=cannot_pause)
    assert path.read_text() == 'invalid retained receipt'
