"""Failure consult graph, charged inert worker and next-turn input custody."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from ravel.workflow import agent_worker, broker, graph_substrate as gs


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))


def stub_dependencies(monkeypatch):
    module = ModuleType('ravel.workflow.knowledge_bundle')
    def materialize(card, node_facts, binding):
        from ravel.workflow.knowledge import load_atlas
        rows = {row['id']: row for row in load_atlas()['entries']}
        context = Path(binding['workspace']) / 'inputs/knowledge'
        context.mkdir(parents=True, exist_ok=True)
        items = []
        ids = set(card['knowledge']['must_read'])
        ids.update(i for i, r in rows.items() if '#' in i and set(r.get('links', {}).get('handbooks', [])) & ids)
        source_root = Path(__file__).parents[2]
        for ordinal, identity in enumerate(sorted(ids)):
            source = source_root / rows[identity]['source']['path']
            dest = context / (str(ordinal) + '.md')
            dest.write_bytes(source.read_bytes())
            items.append({'id': identity, 'kind': rows[identity]['kind'],
                          'path': dest.relative_to(Path(binding['workspace'])).as_posix(),
                          'sha256': broker.sha(dest), 'reason': 'must_read', 'tokens': 10})
        result = {'schema_version': 1, 'kind': 'knowledge-bundle', 'card_id': card['id'],
                  'node_id': node_facts['node_id'], 'items': items, 'omitted': [],
                  'budget_tokens': card['knowledge']['budget_tokens'], 'used_tokens': len(items) * 10}
        result['bundle_sha256'] = broker.digest(result)
        return result
    module.materialize = materialize
    monkeypatch.setitem(sys.modules, module.__name__, module)


def worker_spec(node='producer', attempt=1):
    return {'schema_version': 1, 'kind': 'agent-worker-spec', 'node_id': node, 'attempt': attempt,
            'role': {'id': 'generator', 'version': '1', 'card_sha256': '1' * 64},
            'transport_preference': ['stub'], 'inputs': [], 'declared_outputs': [],
            'budgets': {'max_turns': 3, 'max_wall_seconds': 20, 'max_broker_calls': 3, 'max_cost_usd': None},
            'final_record_schema': 'producer.v1', 'work_order': None, 'rdj_challenges': None,
            'parent': {'review_point_id': None, 'map_id': None, 'rca_ticket': None}}


def request(run, observations=None):
    from ravel.workflow.consults import prepare_failure
    return prepare_failure(run, node_id='producer', observations=observations or
                           {'tool': 'madgraph', 'exit_status': 1, 'stderr': 'No process found'},
                           budgets=worker_spec()['budgets'], transport_preference=['stub'])


@pytest.mark.parametrize('observations', [r['observations'] for r in
    json.loads((Path(__file__).parents[1] / 'fixtures/failures/synthetic.json').read_text())['failures']
    if r['expected_class'].startswith(('infra.', 'provision.'))])
def test_infrastructure_and_provision_graph_spawn_no_agent(tmp_path, monkeypatch, observations):
    def refuse(*args, **kwargs):
        raise AssertionError('an infrastructure route must spawn no agent')
    monkeypatch.setattr(agent_worker, 'dispatch', refuse)
    run = tmp_path / 'run'; run.mkdir()
    pin = request(run, observations)
    result = gs.run(run, 'consult.case', {'request': pin})
    assert result['terminal']['status'] == 'hold'
    assert not agent_worker.status(run)['workers']


def execute_consult(run, monkeypatch, stub=True):
    if stub:
        stub_dependencies(monkeypatch)
    def inert_dispatch(rundir, spec, **options):
        from ravel.workflow import graph_nodes
        assert graph_nodes.TRIPWIRE.get()['ravel_kind'] == 'agent'
        assert graph_nodes.TRIPWIRE.get()['role'] == spec['role']['id']
        ws = agent_worker.materialize(rundir, spec, **{k: v for k, v in options.items()
                                                     if k in ('graph', 'framework_step', 'packet', 'protected', 'effect')})
        packet = json.loads((ws / 'inputs/consult-context.json').read_text())
        assert packet['failure']['class_id'] == 'tool.madgraph.process'
        assert packet['failure_modes'] and packet['bundle']['items']
        pair = packet['pitfall_checks'][0]
        advice = {'schema_version': 1, 'kind': 'consult-advice', 'answer': 'Inspect the declared input.',
                  'fixes': [{'pitfall_id': pair['pitfall_id'], 'check_id': pair['check_id'],
                             'fix': 'Repair the input copy and rerun the cited check.'}]}
        from ravel.workflow import broker
        tool = broker.Broker(rundir, ws, node_id=spec['node_id'], attempt=spec['attempt'], allowed_actions=['write'],
                             max_calls=100)
        assert tool.call({'call_id': 'advice', 'action': 'write',
                          'args': {'path': 'outputs/advice.json', 'content': json.dumps(advice)}})['status'] == 'ok'
        return agent_worker.finish(rundir, spec, final={'completed': True}, execution={'exit_status': 0})
    monkeypatch.setattr(agent_worker, 'dispatch', inert_dispatch)
    pin = request(run)
    return gs.run(run, 'consult.case', {'request': pin}), pin


def test_consult_record_reaches_real_producer_next_turn(tmp_path, monkeypatch):
    from ravel.workflow.consults import next_turn_spec
    run = tmp_path / 'run'; run.mkdir()
    result, pin = execute_consult(run, monkeypatch)
    assert not result['next'] and result['terminal'] is None, result
    spec = next_turn_spec(run, worker_spec(attempt=2), request=pin)
    workspace = agent_worker.materialize(run, spec)
    records = list((workspace / 'inputs/consults').glob('*.json'))
    assert len(records) == 1
    record = json.loads(records[0].read_text())
    assert record['advisory'] is True and record['acceptance_vote'] is False
    assert record['advice']['fixes'] and record['producer_node_id'] == 'producer'
    assert record['worker_receipt']['sha256']
    replay = gs.run(run, 'consult.case', {'request': pin})
    assert not replay['next'] and replay['terminal'] is None and len(agent_worker.status(run)['workers']) == 1


def test_advice_without_offered_pitfall_check_is_refused(tmp_path, monkeypatch):
    from ravel.workflow.consults import validate_advice
    advice = {'schema_version': 1, 'kind': 'consult-advice', 'answer': 'Synthetic answer',
              'fixes': [{'pitfall_id': 'hb:sibling#pitfall-1', 'check_id': 'check:other', 'fix': 'Inspect'}]}
    with pytest.raises(ValueError, match='pitfall'):
        validate_advice(advice, [{'pitfall_id': 'hb:sibling#pitfall-1', 'check_id': 'check:sibling'}])


def test_changed_consult_record_cannot_enter_next_turn(tmp_path, monkeypatch):
    from ravel.workflow.consults import next_turn_spec
    run = tmp_path / 'run'; run.mkdir()
    result, pin = execute_consult(run, monkeypatch)
    assert not result['next'] and result['terminal'] is None, result
    path = next((run / 'consults/records').glob('*.json'))
    doc = json.loads(path.read_text()); doc['advisory'] = False; path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='consult'):
        next_turn_spec(run, worker_spec(attempt=2), request=pin)


def test_graphs_registered_and_intake_designer_is_agent(tmp_path):
    from ravel.workflow.graphs import intake_plan
    from ravel.workflow import graph_nodes
    spec = {'schema_version': 1, 'graph_id': 'synthetic-intake',
            'budget': {'max_nodes': 2, 'max_calls': 2, 'max_output_tokens': 32, 'max_wall_seconds': 10, 'max_reworks': 0},
            'nodes': [{'id': 'choose', 'kind': 'model', 'role': 'designer', 'depends_on': [], 'inputs': [],
                       'packet': None, 'action': 'responses', 'parameters': {}, 'max_attempts': 1},
                      {'id': 'prepare', 'kind': 'tool', 'role': 'executor', 'depends_on': ['choose'], 'inputs': [],
                       'packet': None, 'action': 'intake-plan', 'parameters': {}, 'max_attempts': 1}]}
    turns = []
    def runner(node_id, host):
        turns.append((node_id, graph_nodes.TRIPWIRE.get()['ravel_kind']))
        return node_id
    ctx = gs.BuildContext(tmp_path, 'intake.plan', 1, {}, node_runner=runner)
    app = intake_plan.compile_spec(spec, None, ctx)
    assert gs.lint_graph(app) == []
    app.invoke({'meta': {'graph_id': 'intake.plan', 'version': 1, 'instance': {}, 'scope_root': str(tmp_path)}})
    assert turns == [('choose', 'agent'), ('prepare', 'effect')]


def test_intake_runtime_uses_named_graph_entry(monkeypatch):
    from ravel.workflow.graphs import intake_plan
    from ravel.workflow import langgraph_runtime
    assert 'intake_plan.compile_if_planner' in Path(langgraph_runtime.__file__).read_text()


def test_merged_bundle_provider_supplies_full_handbooks_and_offered_checks(tmp_path):
    from ravel.workflow.consults import worker_spec as consult_spec
    run = tmp_path.resolve() / 'run'; run.mkdir()
    spec = consult_spec(run, request(run))
    assert spec['role']['id'] == 'consult-madgraph'
    packet = json.loads((run / spec['inputs'][0]['pin']['path']).read_text())
    served = {item['id'] for item in packet['bundle']['items']}
    assert {'hb:madgraph-launch', 'hb:madgraph-model-import', 'hb:lhapdf-pdf-sets'} <= served
    assert packet['pitfall_checks']
    assert {p['pitfall_id'].split('#')[0] for p in packet['pitfall_checks']} <= served
    knowledge = [i for i in spec['inputs'] if i['as'].startswith('inputs/knowledge/')]
    assert len(knowledge) == len(packet['bundle']['items'])
    for item in knowledge:
        assert broker.sha(run / item['pin']['path']) == item['pin']['sha256']


def test_merged_bundle_record_reaches_producer_next_turn(tmp_path, monkeypatch):
    from ravel.workflow.consults import next_turn_spec
    run = tmp_path.resolve() / 'run'; run.mkdir()
    result, pin = execute_consult(run, monkeypatch, stub=False)
    assert not result['next'] and result['terminal'] is None, result
    workspace = agent_worker.materialize(run, next_turn_spec(run, worker_spec(attempt=2), request=pin))
    assert len(list((workspace / 'inputs/consults').glob('*.json'))) == 1


def test_missing_bundle_holds_without_worker_dispatch(tmp_path, monkeypatch):
    from ravel.workflow import consults
    original = consults.import_module
    def unavailable(name):
        if name == 'ravel.workflow.knowledge_bundle':
            raise ModuleNotFoundError('bundle absent', name=name)
        return original(name)
    monkeypatch.setattr(consults, 'import_module', unavailable)
    monkeypatch.setattr(agent_worker, 'dispatch', lambda *a, **k: pytest.fail('missing bundle must hold'))
    run = tmp_path / 'run'; run.mkdir()
    pin = request(run)
    result = gs.run(run, 'consult.case', {'request': pin})
    assert result['terminal']['status'] == 'hold'
    assert result['terminal']['reason'] == 'consult_bundle_unavailable'


def test_three_questions_are_durable_and_replays_do_not_use_a_slot(tmp_path):
    from ravel.workflow.consults import prepare_question
    run = tmp_path / 'run'; run.mkdir()
    options = {'node_id': 'producer', 'tool': 'madgraph', 'budgets': worker_spec()['budgets'],
               'transport_preference': ['stub']}
    first = prepare_question(run, question='Inspect input alpha?', **options)
    assert prepare_question(run, question='Inspect input alpha?', **options) == first
    prepare_question(run, question='Inspect input beta?', **options)
    prepare_question(run, question='Inspect input gamma?', **options)
    with pytest.raises(ValueError, match='three'):
        prepare_question(run, question='Inspect input delta?', **options)
    assert prepare_question(run, question='Inspect input alpha?', **options) == first


def test_diagnostic_handoff_preserves_advisory_record(tmp_path, monkeypatch):
    from ravel.workflow.consults import diagnostic_inputs
    run = tmp_path / 'run'; run.mkdir()
    result, pin = execute_consult(run, monkeypatch)
    assert result['terminal'] is None
    packet = diagnostic_inputs(run, request=pin)
    assert packet['consult_records'] and packet['acceptance_vote'] is False
    assert packet['failure']['class_id'] == 'tool.madgraph.process'


def test_question_answer_does_not_invent_a_pitfall():
    from ravel.workflow.consults import validate_advice
    answer = {'schema_version': 1, 'kind': 'consult-advice', 'answer': 'The supplied convention needs clarification.', 'fixes': []}
    assert validate_advice(answer, [], require_fix=False) == answer
    with pytest.raises(ValueError):
        validate_advice(answer, [], require_fix=True)
