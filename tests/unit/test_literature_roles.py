"""Fictional source controls for opt-in tools and bounded role context."""
from copy import deepcopy
import hashlib
import json

import pytest

from ravel.workflow import broker as core, broker_mcp, literature_roles as roles, literature_serving as serving, toolbelt
from test_literature_serving import args, base, bind, install, make_run, ROLE, TOOL_ROW


def card(operations=('search', 'get_paper', 'list_papers', 'compare_measurements')):
    return {'id': ROLE, 'knowledge': {'literature_operations': list(operations)},
            'tools': {'ravel_actions': [serving.ACTION]}, 'requires': {'tools': 'broker-readonly'}}


def setup(base, configuration=True):
    installed = install(base)
    run = make_run(base)
    broker = bind(run, installed.serving if configuration else None)
    return installed, broker


def request(op='search'):
    return {'op': op, 'args': args(op)}


def test_undeclared_roles_gain_no_tools():
    assert roles.operations({'knowledge': {}}) == ()
    assert roles.tools({'knowledge': {}}, TOOL_ROW, executable=[serving.ACTION]) == []


@pytest.mark.parametrize('declared', [['unknown'], ['search', 'search'], 'search', [None]])
def test_invalid_declarations_are_rejected(declared):
    value = card()
    value['knowledge']['literature_operations'] = declared
    with pytest.raises(ValueError):
        roles.operations(value)


@pytest.mark.parametrize('field', ['action', 'tool-less'])
def test_declarations_require_the_broker(field):
    value = card()
    if field == 'action':
        value['tools']['ravel_actions'] = []
    else:
        value['requires']['tools'] = 'none'
    with pytest.raises(ValueError):
        roles.operations(value)


def test_mcp_uses_only_role_declared_operations_and_the_existing_action(base):
    installed, broker = setup(base)
    tools = roles.tools(card(('search',)), TOOL_ROW, executable=[serving.ACTION])
    server = broker_mcp.Server(tools, broker.call)
    assert [row['name'] for row in server.listing()] == ['literature_search']
    broker.allowed_actions.add(serving.ACTION)
    response = server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                              'params': {'name': 'literature_search', 'arguments': args('search')}})
    reply = response['result']['structuredContent']
    assert reply['status'] == 'ok'
    assert json.loads(serving.load(broker.rundir, reply))['operation'] == 'search'
    assert installed.provider.calls == ['search']
    assert roles.tools(card(), TOOL_ROW, executable=[]) == []
    assert all(t['executes_through']['action'] == serving.ACTION for t in tools)
    assert 'literature_replay' not in {t['name'] for t in tools}


@pytest.mark.parametrize('op', ['search', 'get_paper', 'list_papers', 'compare_measurements'])
def test_packet_payload_is_exact_served_bytes_and_custody_is_retained(base, op):
    installed, broker = setup(base)
    section, payloads = roles.packet(broker, card(), broker.node_id, [request(op)], budget_tokens=100000)
    assert len(section['requests']) == 1
    row = section['requests'][0]
    raw = payloads[row['path']]
    reply = broker.verify_ledger()[-1]['reply']
    assert raw == serving.load(broker.rundir, reply)
    assert hashlib.sha256(raw).hexdigest() == row['sha256']
    assert row['receipt_id'] == reply['receipt_id']
    assert section['used_tokens'] == len(raw)
    assert set(section['served_ids']) == set(row['ids'])
    assert section['physics_verified'] is section['execution_authorized'] is False
    assert installed.provider.calls == [op]


def test_whole_population_is_validated_before_any_call(base):
    installed, broker = setup(base)
    with pytest.raises(ValueError):
        roles.packet(broker, card(('search',)), broker.node_id,
                     [request(), request('list_papers')], budget_tokens=100000)
    assert installed.provider.calls == []
    assert broker.verify_ledger() == []


@pytest.mark.parametrize('budget', [-1, True, 1.5])
def test_invalid_packet_budget_refuses_before_calls(base, budget):
    installed, broker = setup(base)
    with pytest.raises(ValueError):
        roles.packet(broker, card(), broker.node_id, [request()], budget_tokens=budget)
    assert installed.provider.calls == []


def test_empty_remaining_budget_never_retrieves(base):
    installed, broker = setup(base)
    section, payloads = roles.packet(broker, card(), broker.node_id, [request()], budget_tokens=0)
    assert payloads == {} and section['served_ids'] == []
    assert section['omitted'] == [{'request': 0, 'reason': 'budget'}]
    assert installed.provider.calls == []


def test_envelope_that_does_not_fit_remains_omitted_with_receipt(base):
    _, broker = setup(base)
    section, payloads = roles.packet(broker, card(), broker.node_id, [request()], budget_tokens=1)
    assert not payloads and not section['served_ids'] and section['used_tokens'] == 0
    assert section['omitted'][0]['reason'] == 'budget'
    assert section['omitted'][0]['receipt_id'] == broker.verify_ledger()[-1]['receipt_id']


def test_unconfigured_serving_is_a_receipted_packet_omission(base):
    _, broker = setup(base, False)
    section, payloads = roles.packet(broker, card(), broker.node_id, [request()], budget_tokens=100000)
    assert not payloads and not section['served_ids']
    assert section['omitted'][0]['reason'] == 'retrieval_unavailable'
    assert broker.verify_ledger()[-1]['status'] == 'refused'


def test_required_knowledge_budget_is_reserved_and_legacy_index_is_unchanged(base):
    _, broker = setup(base)
    index = {'node_id': broker.node_id, 'card_id': ROLE, 'budget_tokens': 10, 'used_tokens': 10}
    original = deepcopy(index)
    assert roles.supplement(index, card(), {}, {}) == (index, {})
    binding = {'workspace': broker.workspace, 'literature_broker': broker, 'literature_requests': [request()]}
    result, payloads = roles.supplement(index, card(), {}, binding)
    assert index == original and result['used_tokens'] == 10 and not payloads
    assert result['literature']['omitted'][0]['reason'] == 'budget'


@pytest.mark.parametrize('mismatch', ['role', 'node', 'workspace', 'missing'])
def test_packet_cannot_be_injected_into_another_binding(base, mismatch):
    installed, broker = setup(base)
    value = card()
    index = {'node_id': broker.node_id, 'card_id': ROLE, 'budget_tokens': 100000, 'used_tokens': 0}
    binding = {'workspace': broker.workspace, 'literature_broker': broker, 'literature_requests': [request()]}
    if mismatch == 'role':
        value['id'] = 'other-role'
    elif mismatch == 'node':
        index['node_id'] = 'other-node'
    elif mismatch == 'workspace':
        binding['workspace'] = base / 'elsewhere'
    else:
        del binding['literature_broker']
    with pytest.raises(ValueError):
        roles.supplement(index, value, {}, binding)
    assert installed.provider.calls == []


def test_citations_require_same_attempt_custody(base):
    installed, broker = setup(base)
    section, _ = roles.packet(broker, card(), broker.node_id, [request()], budget_tokens=100000)
    index = {'node_id': broker.node_id, 'card_id': ROLE, 'literature': section}
    identity = section['served_ids'][0]
    assert roles.validate_citations({'literature_used': [identity, identity]}, index, broker) == [identity]
    with pytest.raises(ValueError, match='never served'):
        roles.validate_citations({'literature_used': ['invented']}, index, broker)
    other = bind(broker.rundir, installed.serving, attempt=2)
    with pytest.raises(ValueError, match='another attempt'):
        roles.validate_citations({'literature_used': [identity]}, index, other)
    with pytest.raises(ValueError, match='ID list'):
        roles.validate_citations({'literature_used': 'invented'}, index, broker)


def test_tools_refuse_provider_selection_and_replay_arguments():
    tools = roles.tools(card(('search',)), TOOL_ROW, executable=[serving.ACTION])
    for key in ('provider', 'index', 'endpoint', 'serving_id'):
        request_args = {**args('search'), key: 'untrusted'}
        request_row = toolbelt.to_request(tools, 'literature_search', request_args, 'fictional-call')
        assert toolbelt.match(tools, serving.ACTION, request_row['args']) is None


@pytest.mark.parametrize('value', [None, False, {}, ''])
def test_malformed_disabled_request_blocks_are_not_silently_ignored(value):
    with pytest.raises(ValueError, match='bounded list'):
        roles.supplement({}, card(), {}, {'literature_requests': value})


def test_duplicate_envelopes_are_exact_and_charged_once(base):
    _, broker = setup(base)
    section, payloads = roles.packet(broker, card(), broker.node_id, [request(), request()],
                                     budget_tokens=100000)
    assert len(section['requests']) == 2 and len(payloads) == 1
    assert section['requests'][0]['path'] == section['requests'][1]['path']
    assert section['requests'][0]['receipt_id'] != section['requests'][1]['receipt_id']
    assert section['used_tokens'] == sum(len(raw) for raw in payloads.values())


def test_followup_mcp_evidence_is_citable_without_being_in_the_initial_packet(base):
    _, broker = setup(base)
    section, _ = roles.packet(broker, card(), broker.node_id, [request('list_papers')], budget_tokens=100000)
    tools = roles.tools(card(('search',)), TOOL_ROW, executable=[serving.ACTION])
    server = broker_mcp.Server(tools, broker.call)
    response = server.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                              'params': {'name': 'literature_search', 'arguments': args('search')}})
    reply = response['result']['structuredContent']
    identity = json.loads(serving.load(broker.rundir, reply))['results'][0]['id']
    assert identity not in section['served_ids']
    index = {'node_id': broker.node_id, 'card_id': ROLE, 'literature': section}
    assert roles.validate_citations({'literature_used': [identity]}, index, broker) == [identity]
    # A legacy cold bundle also permits explicit use of later governed tool results.
    del index['literature']
    assert roles.validate_citations({'literature_used': [identity]}, index, broker) == [identity]


# ---- the worker lifecycle: pre-launch literature context and final-record citations

from test_knowledge_bundles import sources  # noqa: E402,F401  (fixture)

# The `sources` fixture packet captured at the integration base 73a3578: a card without
# literature_operations must materialize byte-identical files (sha256 of the sorted file digests).
BASE_PACKET_SHA256 = 'eb705c6bbd292cc2b3ba9e08f85a59f7e92db01d90622c0ab87d9b1820f4b915'


def _spec(node='scout', attempt=1):
    return {'schema_version': 1, 'kind': 'agent-worker-spec', 'node_id': node, 'attempt': attempt,
            'role': {'id': ROLE, 'version': '1', 'card_sha256': '1' * 64}, 'transport_preference': ['stub'],
            'inputs': [], 'declared_outputs': [{'path': 'outputs/result.txt', 'kind': 'text', 'required': True}],
            'budgets': {'max_turns': 5, 'max_wall_seconds': 20, 'max_broker_calls': 20, 'max_cost_usd': None},
            'final_record_schema': 'producer.v1', 'work_order': None, 'rdj_challenges': None,
            'parent': {'review_point_id': None, 'map_id': None, 'rca_ticket': None}}


def _knowledge(sources, requests=(), *, budget=100000, literature=True):
    card, facts, binding = deepcopy(sources)
    card['id'] = ROLE
    card['knowledge']['budget_tokens'] = budget
    if literature:
        card.update(tools={'ravel_actions': [serving.ACTION]}, requires={'tools': 'broker-readonly'})
        card['knowledge']['literature_operations'] = ['search', 'get_paper']
    binding.pop('workspace')
    facts.pop('node_id')
    value = {'card': card, 'node_facts': facts, 'binding': binding}
    if requests:
        value['literature_requests'] = list(requests)
    return value


def _scoped(op, document):
    if op == 'search':
        return {'op': 'search', 'args': args('search', document_scope=[{'document_id': document, 'version': 'v1'}])}
    return {'op': 'get_paper', 'args': args('get_paper', document_id=document)}


@pytest.fixture
def lifecycle(base, monkeypatch):
    from ravel.workflow import agent_worker
    from test_literature_serving import installation
    from ravel.workflow import literature_settings
    settings = installation(base, monkeypatch)
    monkeypatch.setenv(literature_settings.SETTINGS_ENV, str(settings.path))
    return agent_worker, make_run(base)


def _put(run, ws):
    tool = core.Broker(run, ws, node_id=ws.parent.name, attempt=int(ws.name), allowed_actions=['write'], max_calls=50)
    assert tool.call({'call_id': 'put-result', 'action': 'write',
                      'args': {'path': 'outputs/result.txt', 'content': 'done'}})['status'] == 'ok'


def _follow_up(run, ws, spec, op, document):
    """The attempt's later tool retrieval, through the production broker the supervisor builds."""
    from ravel.workflow import literature_settings, tool_gate
    tools = serving.tools(TOOL_ROW)
    made = tool_gate.production_broker(run, ws, tools=tools, role=ROLE, node_id=spec['node_id'], attempt=spec['attempt'],
                                       max_calls=spec['budgets']['max_broker_calls'],
                                       retrieval=literature_settings.for_tools(tools))
    request = _scoped(op, document)
    reply = made.call(toolbelt.to_request(tools, 'literature_' + op, request['args'], 'follow-' + op))
    assert reply['status'] == 'ok', reply
    return [row['id'] for row in json.loads(serving.load(run, reply))['results']]


def test_worker_lifecycle_cites_packet_and_follow_up_literature(lifecycle, sources):
    worker, run = lifecycle
    spec = _spec()
    ws = worker.materialize(run, spec, knowledge=_knowledge(sources, [_scoped('search', 'paper:alder')]))
    index = json.loads((ws / 'inputs/knowledge/index.json').read_bytes())
    section = index['literature']
    assert section['binding']['node_id'] == 'scout' and section['served_ids'] and not section['omitted']
    assert index['used_tokens'] <= index['budget_tokens'] and index['items']
    record = worker._record(run, 'scout', 1)
    pinned = {p['path'] for p in record['input_copies']}
    assert 'inputs/knowledge/index.json' in pinned and section['requests'][0]['path'] in pinned
    later = _follow_up(run, ws, spec, 'get_paper', 'paper:birch')
    assert not set(later) & set(section['served_ids'])
    _put(run, ws)
    final = {'completed': True, 'knowledge_used': index['served_ids'][:1],
             'literature_used': [section['served_ids'][0], later[0]]}
    receipt = worker.finish(run, spec, final=final, execution={'exit_status': 0})
    assert receipt['status'] == 'ok' and receipt['outcome']['computed_checks']['knowledge_citations'] is True
    assert receipt['knowledge']['literature_used'] == [section['served_ids'][0], later[0]]
    assert receipt['knowledge']['used_ids'] == index['served_ids'][:1]
    assert receipt['knowledge']['bundle_sha256'] == index['bundle_sha256']


@pytest.mark.parametrize('case', ['wrong attempt', 'unserved', 'excess budget', 'injected payload'])
def test_lifecycle_refuses_unproven_literature_use(lifecycle, sources, case):
    worker, run = lifecycle
    first = _spec()
    requests = [_scoped('search', 'paper:alder')]
    if case == 'excess budget':
        over = {**serving.DEFAULT_BUDGETS, 'max_bytes': serving.DEFAULT_CEILINGS['max_bytes'] + 1}
        requests.append({'op': 'get_paper', 'args': {**args('get_paper', document_id='paper:birch'), 'budgets': over}})
    ws = worker.materialize(run, first, knowledge=_knowledge(sources, requests))
    section = json.loads((ws / 'inputs/knowledge/index.json').read_bytes())['literature']
    cited = section['served_ids'][:1]
    spec = first
    if case == 'wrong attempt':
        spec = _spec(attempt=2)
        ws = worker.materialize(run, spec, knowledge=_knowledge(sources))
    elif case == 'unserved':
        cited = cited + ['unit:invented:1']
    elif case == 'excess budget':
        assert [row['reason'] for row in section['omitted']] == ['budget_exceeded']
        cited = cited + ['unit:birch:1']
    else:
        payload = ws / section['requests'][0]['path']
        payload.chmod(0o600)
        payload.write_bytes(payload.read_bytes().replace(b'Alder', b'Aldex'))
        with pytest.raises(ValueError, match='materialized input changed'):
            worker.materialize(run, first, knowledge=_knowledge(sources, requests))
    _put(run, ws)
    receipt = worker.finish(run, spec, final={'completed': True, 'knowledge_used': [], 'literature_used': cited},
                            execution={'exit_status': 0})
    assert receipt['status'] == 'failed' and receipt['credited_outputs'] == []
    checks = receipt['outcome']['computed_checks']
    if case == 'injected payload':
        assert checks['inputs_unchanged'] is False
    else:
        assert checks['knowledge_citations'] is False


def test_role_budget_keeps_required_knowledge_and_omits_what_does_not_fit(lifecycle, sources):
    worker, run = lifecycle
    probe = worker.materialize(run, _spec('probe'), knowledge=_knowledge(sources))
    required = json.loads((probe / 'inputs/knowledge/index.json').read_bytes())['used_tokens']
    ws = worker.materialize(run, _spec(), knowledge=_knowledge(sources, [_scoped('search', 'paper:alder')],
                                                               budget=required + 16))
    index = json.loads((ws / 'inputs/knowledge/index.json').read_bytes())
    assert index['used_tokens'] <= index['budget_tokens'] == required + 16
    assert [row['reason'] for row in index['literature']['omitted']] == ['budget']
    assert index['literature']['requests'] == [] and index['items']


@pytest.mark.parametrize('case', ['workspace', 'broker', 'requests in binding', 'another role', 'extra key'])
def test_dispatcher_binds_workspace_broker_and_role(lifecycle, sources, case):
    worker, run = lifecycle
    value = _knowledge(sources)
    if case == 'workspace':
        value['binding']['workspace'] = '/elsewhere'
    elif case == 'broker':
        value['binding']['literature_broker'] = object()
    elif case == 'requests in binding':
        value['binding']['literature_requests'] = [_scoped('search', 'paper:alder')]
    elif case == 'another role':
        value['card']['id'] = 'another-role'
    else:
        value['serving'] = 'remote'
    with pytest.raises(ValueError):
        worker.materialize(run, _spec(), knowledge=value)
    assert not worker.dispatched(run, 'scout', 1)


def test_card_without_literature_operations_writes_the_base_packet(lifecycle, sources):
    from ravel.workflow import knowledge_bundles
    card, facts, binding = deepcopy(sources)
    knowledge_bundles.materialize(card, facts, binding)
    files = {p.relative_to(binding['workspace']).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(binding['workspace'].rglob('*')) if p.is_file()}
    assert hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest() == BASE_PACKET_SHA256
    # The worker lifecycle without literature requests materializes the same bundle content.
    worker, run = lifecycle
    ws = worker.materialize(run, _spec(), knowledge=_knowledge(sources, literature=False))
    index = json.loads((ws / 'inputs/knowledge/index.json').read_bytes())
    assert 'literature' not in index and not (ws / 'outputs' / 'literature').exists()
    receipt = worker.finish(run, _spec(), final={'completed': True}, execution={'exit_status': 0})
    assert receipt['knowledge']['bundle_sha256'] == index['bundle_sha256']
    assert 'literature_used' not in receipt['knowledge']
