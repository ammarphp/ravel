"""Installed literature cards through charged graphs and actual governed worker seats.

Only the process/sandbox and sibling-service seams of the shared inert worker are
substituted. No provider is called; role cards, selection, projection, broker,
supervision, output custody, usage and persistent graph checkpoints are real.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ravel.workflow import agent_graph, agent_host, agent_worker, research_controller as bridge
from ravel.workflow import literature_evidence_scoring as scoring, literature_query as query
from ravel.workflow import research_cycle as cycle, research_tools as tools, role_registry
from ravel.workflow import research_coordinator_decisions as decisions
from ravel.workflow.research_orchestrator import campaign_contract
from test_langgraph_research_orchestration import open_fixture
from test_literature_query import QUERY, vocabulary
from test_literature_query_ops import serving_search
from test_literature_discovery_agent import scope, R
from test_research_cycle import write
from test_p04_support import (context, graphs, inert_worker, install_plan, records, run_env,
                              services_installed, qualify)


PUBLIC_REPLY = '''
if (spec.get('parameters') or {}).get('research_node'):
    fields = spec['parameters']['research_node']['parameters']['output_schema']['properties']
    kind = fields['kind']['const']
    if 'entries' in fields:
        public = {'kind': kind, 'request_sha256': fields['request_sha256']['const'],
                  'entries': ['zorp-boson'], 'terms': []}
    elif 'assessments' in fields:
        identities = fields['assessments']['items']['properties']['candidate']['enum']
        public = {'kind': kind, 'batch_sha256': fields['batch_sha256']['const'],
                  'assessments': [{'candidate': i, 'relevance_score': 9,
                                   'summary': 'Fictional reading aid.'} for i in identities]}
    else:
        item = fields['decisions']['items']['properties']
        criterion = item['judgments']['items']['properties']['criterion']['enum'][0]
        public = {'kind': kind, 'request_sha256': fields['request_sha256']['const'],
                  'decisions': [{'candidate': item['candidate']['enum'][0],
                                 'judgments': [{'criterion': criterion, 'judgment': 'uncertain',
                                                'field': None, 'excerpt': None}]}]}
    writes = [{'path': 'outputs/public-record.json', 'content': json.dumps(public)}]
'''


@pytest.fixture
def governed(run_env, inert_worker, graphs, monkeypatch):
    # Extend only the inert executable's byte producer, then re-probe and re-qualify
    # its changed bytes through the same protected qualification path.
    executable = inert_worker.executable
    source = executable.read_text()
    assert "writes = scenario.get('writes')" in source
    executable.write_text(source.replace("writes = scenario.get('writes')",
                                         "writes = scenario.get('writes')\n" + PUBLIC_REPLY))
    from ravel.workflow import transport_registry as tr
    qualify(run_env.store, tr.probe('claude-cli-worker', executable=str(executable)))
    inert_worker.scenario(turns=1)
    run = run_env.run_dir
    request, _, _, _ = open_fixture(run)
    value = decisions.request(request)
    (run / 'inputs/task_contract.json').write_bytes(Path(value['parent_contract']['path']).read_bytes())
    root = run / 'campaign'
    cycle.create(root, campaign_contract(value), base_dir=run, evaluation_harness=True)
    parent = bridge._step('campaign', 'subgraph')
    parent.update(graph={'id': 'research.loop', 'instance': {}},
                  parameters={'campaign': str(root), 'research_request': request})
    plan_sha = install_plan(run_env.store, [parent])
    ctx = context(run_env.store, run, plan_sha, research_campaign=str(root))
    run_env.store.append('research-subgraph-entry', {'parent_step': parent,
        'parent_step_sha256': cycle.ce.digest(parent), 'parent_plan_sha256': plan_sha,
        'request': request, 'campaign': str(root)})
    # Any accidental direct provider fallback fails the fixture.
    monkeypatch.setattr(agent_host.AgentHost, '_responses',
                        lambda *a, **k: pytest.fail('governed literature used a direct provider'))
    return root, ctx


def test_installed_expander_and_scorer_execute_through_governed_seats(governed, run_env):
    root, ctx = governed
    path = vocabulary(run_env.run_dir)
    world, serving_id = serving_search(run_env.root / 'served')
    _, envelope = tools.served_envelope(world.run, serving_id, node_id='worker', attempt=1)
    with bridge.bound(run_env.store, ctx):
        expanded = tools.expand_literature_query(root, QUERY, root / 'expand', agent_host.AgentHost(),
                                                 preferences={}, vocabulary=path)
        assert expanded['status'] == 'admitted', json.dumps({
            'reason': expanded['reason'], 'error': expanded['error'],
            'model': expanded['expansion']['model'],
            'nodes': agent_graph.status(expanded['graph'])['nodes'],
            'outcomes': records(run_env.store, 'step-outcome')}, default=str)
        assessed = tools.score_literature_evidence(root, world.run, serving_id, 'Which method is located?',
            root / 'score', agent_host.AgentHost(), preferences={}, node_id='worker', attempt=1)
        assert assessed['status'] == 'scored', assessed
    assert expanded['expansion']['model']['entries'] == ['zorp-boson']
    result = json.loads(Path(assessed['scoring']['path']).read_text())
    assert [row['original'] for row in result['evidence']] == envelope['results']
    assert result['evidence'][0]['assessment']['relevance_score'] == 9
    # An inherited goal is accepted only with its authenticated exact campaign reservation.
    assert query.admit(expanded['request'], expanded['graph'], vocabulary=path)['reason'] == 'graph_spec_mismatch'
    assert scoring.assemble(assessed['request'], assessed['graph'])['graph']['reason'] == 'graph_spec_mismatch'
    calls = records(run_env.store, 'research-call')
    assert len(calls) == 2
    dispatches = records(run_env.store, 'step-dispatch')
    assert [row['card_sha256'] for row in dispatches] == [role_registry.card_sha256(query.ROLE),
                                                        role_registry.card_sha256(scoring.ROLE)]
    for row in calls:
        role = row['node']['registry_role']
        assert row['observation']['usage']['reported'] is True
        assert row['observation']['usage']['input_tokens'] == 100
        assert row['observation']['isolation']['fresh_request'] is True
        assert row['observation']['isolation']['parent_transcript_supplied'] is False
        dispatch = next(d for d in dispatches if d['step_id'] == row['step_id'])
        record = agent_worker._record(run_env.run_dir, dispatch['node_id'], 1)
        receipt = agent_worker.load_receipt(run_env.run_dir, dispatch['node_id'], 1)
        assert receipt['role']['card_sha256'] == role_registry.card_sha256(role)
        assert receipt['attestation'] == 'transport_attested'
        manifest = json.loads((Path(record['packet']['path']) / 'manifest.json').read_text())
        assert manifest['role'] == role
        assert manifest['forbidden_inputs'] == sorted(role_registry.load(role)['sees']['forbidden_inputs'])
        ws = agent_worker.workspace(run_env.run_dir, dispatch['node_id'], 1)
        names = json.loads((ws / 'scratch/tools.json').read_text())
        assert set(names) <= {'ws_read', 'ws_write', 'submit_final'} and 'ws_write' in names
    accepted = [row for row in records(run_env.store, 'custody') if row['status'] == 'accepted']
    assert len(accepted) == 2 and {r['step_id'] for r in accepted} == {r['step_id'] for r in calls}
    _, state = cycle._load(root)
    assert len(state['graphs']) == 2 and all(g['usage']['calls'] == 1 for g in state['graphs'])
    for graph in state['graphs']:
        assert list(Path(graph['root']).rglob('*.sqlite*')), 'persistent graph checkpoints required'


@pytest.mark.parametrize('damage', ['card', 'qualification', 'tier', 'isolation'])
def test_governed_literature_refuses_before_worker_effects(governed, run_env, monkeypatch, damage):
    root, ctx = governed
    options = {}
    if damage == 'card':
        card = deepcopy(role_registry.load(query.ROLE))
        card['requires']['blind'] = False
        options['roles'] = {'roles': {query.ROLE: {'card': card}}}
    elif damage == 'qualification':
        # The matching same-user file cannot replace the protected qualification.
        run_env.store.entries[:] = [e for e in run_env.store.entries if e['kind'] != 'transport-qualification']
    elif damage == 'tier':
        ctx['agent_preferences']['tier_models'].pop('cheap')
    else:
        from ravel.workflow import sandbox
        monkeypatch.setattr(sandbox, 'available', lambda: None)
    with bridge.bound(run_env.store, ctx):
        result = tools.expand_literature_query(root, QUERY, root / 'refuse', agent_host.AgentHost(),
                                               preferences={}, **options)
    assert result['status'] == 'refused', result
    assert result['expansion'] == result['deterministic']
    assert records(run_env.store, 'step-dispatch') == []
    assert cycle._load(root)[1]['resource_ledger'] == []


def test_installed_selector_executes_through_the_same_governed_graph(governed, run_env):
    from ravel.workflow import literature_discovery_agent as selector
    root, ctx = governed
    document = selector.selection_request(selector.validate_scope(scope()),
                                          [{'recid': '9101', 'metadata': R['9101']['metadata']}])
    pin = write(root / 'selector-request.json', document)
    with bridge.bound(run_env.store, ctx):
        selected, refusal = tools._literature_dispatch(selector.ROLE, None, {}, None)
        assert refusal is None
        settings = {'model': selected['model'], 'reasoning_effort': selected['effort'],
                    'adapter': selected['adapter'], 'max_output_tokens': 2048, 'max_wall_seconds': 60}
        spec = selector.graph_spec(pin, document, settings, graph_id='selector-control')
        graph = root / 'selector-graph'
        assert tools._literature_graph(root, graph, spec, agent_host.AgentHost()) is None
    result = selector.admit(root, pin, graph, settings)
    assert result['status'] == 'admitted', result
    assert result['decisions']['9101']['topic']['judgment'] == 'uncertain'
    assert records(run_env.store, 'step-dispatch')[0]['card_sha256'] == role_registry.card_sha256(selector.ROLE)
    assert records(run_env.store, 'research-call')[0]['observation']['usage']['reported'] is True
