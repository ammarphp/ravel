"""Synthetic sequencing, node metadata, and fail-closed dependency seams."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ravel.workflow import agent_worker, broker, graph_nodes as nodes, graph_substrate as gs
from ravel.workflow.graphs import literature as lg, manuscript as mg
from test_agent_worker import put, spec as worker_spec, result as worker_result
from test_evidence_card import card
from test_knowledge_broker import setup as broker_setup


@pytest.mark.parametrize('name', [lg.SOURCE, lg.SCOUT, mg.SECTION, mg.GRAPH])
def test_registered_graph_compiles_and_has_only_substrate_nodes(tmp_path, name):
    ctx = gs.BuildContext(scope_root=tmp_path, graph_id=name, version=1, instance={'request_id': 'synthetic'})
    compiled = gs.build(name, ctx)
    assert gs.lint_graph(compiled) == []
    metadata = {key: row.metadata for key, row in compiled.get_graph().nodes.items() if not key.startswith('__')}
    assert metadata['hold']['ravel_kind'] == 'hold'
    if name == lg.SCOUT:
        assert metadata['scout']['role'] == metadata['cards']['role'] == 'literature-scout'
        assert metadata['post']['ravel_kind'] == 'board'
        assert metadata['source_reads']['ravel_kind'] == 'map'
    if name == mg.GRAPH:
        assert metadata['integrity_auditor']['role'] == 'integrity-auditor'
        assert metadata['meta_reviewer']['role'] == 'research-meta-reviewer'
        assert metadata['checkin3']['ravel_kind'] == 'interrupt'
        assert metadata['final_task']['ravel_kind'] == 'gate'


def test_manuscript_integrity_provider_fails_closed_until_m22(tmp_path):
    # The manuscript graph's integrity gate names registered, active providers, and a scope root
    # without its pinned contract and plan is refused: the gate never passes on an empty root.
    assert nodes._required_providers(mg.GRAPH, 'report_integrity') == ['review_points', 'rdj']
    errors = nodes.check_gate(tmp_path, 'report_integrity', {'kind': 'report', 'digest': '1' * 64,
                              'summary': 'Synthetic report', 'pins': []}, graph_id=mg.GRAPH)
    assert [(row['code'], row['gate'], row['provider']) for row in errors] == [
        ('gate_inputs_invalid', 'report_integrity', 'review_points')]
    assert errors[0]['pins'] == ['inputs:contract-plan'] and 'task_contract.json' in errors[0]['message']


def _dispatch(monkeypatch, outputs):
    """Inert worker producer: actual materialization, completion and receipt checks."""
    calls = []
    def dispatch(root, spec, **options):
        calls.append(spec['node_id'])
        ws = agent_worker.materialize(root, spec)
        put(root, ws, 'outputs/result.txt', json.dumps(outputs(spec['node_id'])))
        return agent_worker.finish(root, spec, final=worker_result(), execution={'exit_status': 0})
    monkeypatch.setattr(agent_worker, 'dispatch', dispatch)
    return calls


def _spec(role, state):
    name = nodes.TRIPWIRE.get()['node'] if 'node' in nodes.TRIPWIRE.get() else None
    # Current worker purpose is determined by the actual node, not model content.
    if name is None:
        from ravel.workflow import effect_ledger
        name = effect_ledger._node_name()
    spec = worker_spec(name=name)
    from ravel.workflow import role_registry
    spec['role'] = {'id': role, 'version': role_registry.load(role)['version'],
                    'card_sha256': role_registry.card_sha256(role)}
    return spec


def _consume(root, receipt):
    ws = agent_worker.workspace(root, receipt['node_id'], receipt['attempt'])
    raw = (ws / 'outputs/result.txt').read_bytes()
    assert receipt['credited_outputs'][0]['sha256'] == hashlib.sha256(raw).hexdigest()
    return json.loads(raw)


def test_literature_graph_empty_source_map_still_checks_and_posts(tmp_path, monkeypatch):
    _, source_broker, _ = broker_setup(tmp_path, monkeypatch)
    root = source_broker.rundir
    raw, value = card(); (source_broker.workspace / 'inputs/paper.txt').write_bytes(raw)
    calls = _dispatch(monkeypatch, lambda name: {'cards': [value]} if 'cards' in name else {'sources': []})
    posts = []
    services = lg.Services(epoch='1' * 64, worker_spec=_spec,
        consume_worker=lambda role, receipt, state: _consume(root, receipt), source_items=lambda state: [],
        acquire=lambda state: pytest.fail('empty map acquired a source'),
        extract=lambda state: pytest.fail('empty map extracted a source'),
        reextract=lambda state: pytest.fail('valid cards retried'),
        card_population=lambda state: state['work']['cards']['cards'],
        post=lambda state, report: posts.append(report) or {'journal': 'synthetic-post'}, broker=source_broker)
    with lg.services(services):
        observation = gs.run(root, lg.SCOUT, {'request_id': 'synthetic'}, input={'request': {}}, max_steps=40)
    assert observation['terminal'] is None
    assert calls == ['scout', 'cards']
    assert len(posts) == 1 and posts[0]['anchor_ids'] == ['card-a']


def test_source_graph_wraps_acquisition_then_extraction_without_model_call(tmp_path):
    calls = []
    services = lg.Services(epoch='1' * 64, worker_spec=None, consume_worker=None, source_items=None,
        acquire=lambda state: calls.append('acquire') or {'binding': 'synthetic-acquisition'},
        extract=lambda state: calls.append('extract') or {'binding': 'synthetic-extraction'},
        reextract=None, card_population=None, post=None, broker=None)
    with lg.services(services):
        observation = gs.run(tmp_path, lg.SOURCE, {'request_id': 'synthetic'}, input={'source': {'id': 'source-a'}, 'request': {}})
    assert observation['terminal'] is None and calls == ['acquire', 'extract']


def test_manuscript_sections_require_complete_population():
    services = mg.Services(epoch='1' * 64, worker_spec=None, consume_worker=None,
        sections=lambda state: [], integrity_action=None, final_action=None, record_pin=None)
    with mg.services(services), pytest.raises(ValueError, match='complete'):
        mg._sections({})


def test_missing_lg6_services_refuse():
    with pytest.raises(ValueError, match='research-loop seam'):
        lg.active()
    with pytest.raises(ValueError, match='research-loop seam'):
        mg.active()


def test_literature_retry_is_bounded_and_original_failure_receipt_survives(tmp_path, monkeypatch):
    _, source_broker, _ = broker_setup(tmp_path, monkeypatch)
    root = source_broker.rundir
    raw, good = card(); bad = deepcopy(good); bad['value'] = '99.3'
    (source_broker.workspace / 'inputs/paper.txt').write_bytes(raw)
    calls = _dispatch(monkeypatch, lambda name: {'cards': [bad]} if name == 'cards' else
                       {'cards': [good]} if name == 'revised_cards' else {'sources': []})
    retries, posts = [], []
    services = lg.Services(epoch='1' * 64, worker_spec=_spec,
        consume_worker=lambda role, receipt, state: _consume(root, receipt), source_items=lambda state: [],
        acquire=None, extract=None,
        reextract=lambda state: retries.append(state['failed_card_ids']) or {'retry': 'source-a'},
        card_population=lambda state: state['work'].get('revised_cards', state['work'].get('cards'))['cards'],
        post=lambda state, report: posts.append(report) or {'journal': 'synthetic-post'}, broker=source_broker)
    with lg.services(services):
        observation = gs.run(root, lg.SCOUT, {'request_id': 'retry'}, input={'request': {}}, max_steps=40)
    assert observation['terminal'] is None and calls == ['scout', 'cards', 'revised_cards']
    assert retries == [['card-a']] and posts[0]['census'][0]['status'] == 'checked'
    assert any(row['status'] == 'refused' and row['action'] == 'literature.check' for row in source_broker.verify_ledger())


def test_manuscript_auditor_receives_and_reads_record_then_ci3_remains_gated(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    root = tmp_path / 'run'; (root / 'inputs').mkdir(parents=True)
    raw = b'Complete synthetic record with failure and unresolved scope.'
    path = root / 'inputs/record.txt'; path.write_bytes(raw)
    pin = {'path': 'inputs/record.txt', 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    calls, reads = [], []
    def spec(role, state):
        value = _spec(role, state)
        if role == 'integrity-auditor':
            assert state['record'] == pin
            value['inputs'] = [{'pin': pin, 'as': 'inputs/record.txt'}]
        return value
    def dispatch(run, value, **options):
        calls.append(value['node_id'])
        ws = agent_worker.materialize(run, value)
        if value['role']['id'] == 'integrity-auditor':
            tool = broker.Broker(run, ws, node_id=value['node_id'], attempt=1, allowed_actions=['read'], max_calls=10)
            reply = tool.call({'call_id': 'record', 'action': 'read', 'args': {'path': 'inputs/record.txt'}})
            assert reply['status'] == 'ok'; reads.append(reply['receipt_id'])
        put(run, ws, 'outputs/result.txt', json.dumps({'phase': value['node_id']}))
        return agent_worker.finish(run, value, final=worker_result(), execution={'exit_status': 0})
    monkeypatch.setattr(agent_worker, 'dispatch', dispatch)
    exported = []
    monkeypatch.setattr(mg.procedure_export, 'export_for_delivery', lambda run: exported.append(str(run)) or
                        {'directory': 'synthetic-procedure', 'execution_authorized': False})
    action = lambda state: {'kind': 'report', 'digest': '1' * 64, 'summary': 'Synthetic record', 'pins': [pin]}
    service = mg.Services(epoch='1' * 64, worker_spec=spec,
        consume_worker=lambda role, receipt, state: _consume(root, receipt),
        sections=lambda state: [{'id': 'section-a'}, {'id': 'section-b'}],
        integrity_action=action, final_action=action, record_pin=lambda state: pin)
    # Distinct section workers are part of the original prepared spec, never one shared write set.
    original_spec = service.worker_spec
    def section_spec(role, state):
        value = original_spec(role, state)
        if state.get('section'):
            value['node_id'] = state['section']['id']
        return value
    service = mg.Services(**{**service.__dict__, 'worker_spec': section_spec})
    providers = lambda gate: {name: True for name in ('report_integrity', 'review_points', 'rdj', 'raw_launch')}
    def gate(root, name, action):
        return [{'code': 'missing_final_record', 'message': 'Resume is not approval'}] if name == 'final_task' else []
    with mg.services(service), nodes.gate_checker(gate, providers=providers):
        paused = gs.run(root, mg.GRAPH, {'request_id': 'synthetic'}, input={'request': {}}, max_steps=40,
                        gate_check=gate, gate_providers=providers)
        assert paused['interrupts']
        held = gs.run(root, mg.GRAPH, {'request_id': 'synthetic'}, respond={paused['interrupts'][0]['id']: {'decision': 'approve'}}, max_steps=40,
                      gate_check=gate, gate_providers=providers)
    assert reads and exported == [str(root)]
    assert calls[0] == 'story' and set(calls[1:3]) == {'section-a', 'section-b'}
    assert calls[-3:] == ['writer', 'integrity_auditor', 'meta_reviewer']
    assert held['terminal']['status'] == 'hold'
