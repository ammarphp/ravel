"""Governed literature query expansion and evidence scoring as explicit controller operations.

Fictional vocabulary, corpus and replies only. Subprocesses are refused and no
model is reached. The registered role cards are dispatched through the real role
dispatcher (transport registry) against synthetic probe and qualification
records stored in a per-test state directory, written the way the merged-roles
acceptance does; they are never shipped and claim no live run. Outside a bound
controller scope a selected sandbox worker has no governed seat dispatcher, so
the one-shot Host refuses as ``transport_unsupported`` naming the selected route.
The installed-card governed success is in controller/test_literature_seats.py.
Separate synthetic no-tool
cards exercise the stateless HTTP adapter through real graph/campaign custody;
they do not establish HTTP support for the released broker-tool cards.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from ravel.controller.step import host_operations, operations
from ravel.validation import signature_conformance
from ravel.workflow import agent_host, literature_evidence_scoring as s, literature_query as q
from ravel.workflow import production_executor, research_cycle as cycle, research_tools as tools, role_registry
from ravel.workflow import transport_registry as transport
from test_literature_query import QUERY, reply, vocabulary
from test_research_cycle import contract
import test_literature_serving as served_world

EXECUTABLE_SHA256 = hashlib.sha256(b'literature operations synthetic selection executable').hexdigest()
SELECTED = 'claude-cli-worker'


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n')


def qualified_routes():
    """Synthetic confirmed probes and live qualification records for every CLI route, in the state dir."""
    for document in transport.all_declarations():
        if document['transport_kind'] not in transport.CLI_KINDS:
            continue
        probe = {'schema_version': 1, 'kind': 'transport-probe', 'transport_id': document['id'],
                 'declaration_sha256': transport.declaration_sha256(document),
                 'cli_version': 'synthetic-selection-control', 'help_sha256': '0' * 64,
                 'flags': {flag: 'confirmed' for flag in transport.template_flags(document)},
                 'capabilities_confirmed': {key: bool(document['capabilities'][key])
                                            for key in transport.BOOLEAN_CAPABILITIES},
                 'unusable': [], 'probed_utc': '2026-10-11T00:00:00Z',
                 'executable_path': '/synthetic/literature-selection-control',
                 'executable_sha256': EXECUTABLE_SHA256, 'exit_status': 0}
        _write(transport.probe_path(document['id']), probe)
        path = transport.qualification_path(document['id'])
        _write(path, {'schema_version': 1, 'kind': 'transport-qualification', 'transport_id': document['id'],
                      'status': 'live_qualified', 'record_path': str(path),
                      'executable_path': probe['executable_path'], 'executable_sha256': EXECUTABLE_SHA256,
                      'declaration_sha256': transport.declaration_sha256(document),
                      'probe_sha256': transport.digest(probe), 'receipt': {'synthetic': 'literature selection control'},
                      'observed': {}, 'steps': [], 'rundir': '/synthetic/literature-selection-control',
                      'qualified_utc': '2026-10-11T00:00:00Z'})
    return {d['id']: EXECUTABLE_SHA256 for d in transport.all_declarations()
            if d['transport_kind'] in transport.CLI_KINDS}


def preferences(drop_tiers=()):
    declarations = transport.all_declarations()
    order = [SELECTED] + sorted(d['id'] for d in declarations if d['id'] != SELECTED)
    tiers, families = {}, {}
    for document in declarations:
        for model in document['models']:
            identity = model['id'] if '{' not in model['id'] else document['id'] + '-fixture-model'
            families[identity] = model['family'] if model['family'] != 'any' else 'anthropic'
            for tier in model['tiers']:
                if tier not in drop_tiers:
                    tiers.setdefault(tier, {}).setdefault(document['id'], identity)
    return {'schema_version': 1, 'kind': 'agent-preferences',
            'families': {card['family']: order for card in role_registry.all_cards()},
            'tier_models': tiers, 'model_families': families}


def campaign(base, calls=20, output_tokens=100000):
    root = base / 'campaign'
    value = contract(base)
    value['budget'] = {**value['budget'], 'calls': calls, 'output_tokens': output_tokens, 'wall_seconds': 3600}
    cycle.create(root, value, base_dir=base, evaluation_harness=True)
    return root


@pytest.fixture
def inert(monkeypatch, tmp_path):
    def refuse(*args, **kwargs):
        raise AssertionError('no process, provider or model dispatch in literature operation controls')
    monkeypatch.setattr(subprocess, 'Popen', refuse)
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path.resolve() / 'state'))
    calls = []
    monkeypatch.setattr(agent_host.AgentHost, '_responses', lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(
        AssertionError('no model call is admissible for the released literature cards')))
    return calls


@pytest.fixture
def dispatch(inert):
    return {'preferences': preferences(), 'executables': qualified_routes()}


@pytest.fixture
def http_dispatch(inert):
    """Synthetic no-tool cards qualify for the real stateless HTTP declaration.

    Released cards still require broker-readonly tools and keep their CLI refusal
    tests. Only this explicit fixture changes that requirement; no production
    capability, dispatcher, graph or campaign custody is replaced.
    """
    roles = {'aliases': {}, 'roles': {}}
    for role in (q.ROLE, s.ROLE, 'literature-discovery-selector'):
        card = deepcopy(role_registry.load(role))
        card['requires']['tools'] = 'none'
        roles['roles'][role] = {'card': card}
    prefs = {'schema_version': 1, 'kind': 'agent-preferences',
             'families': {'research': ['http-responses']},
             'tier_models': {'cheap': {'http-responses': 'explicit-inert-fixture'}},
             'model_families': {'explicit-inert-fixture': 'openai'}}
    options = {'roles': roles, 'preferences': prefs, 'probes': {}, 'executables': {}}
    for role in roles['roles']:
        selected, refusal = tools._literature_dispatch(role, roles, prefs, {}, {})
        assert refusal is None and selected['transport_id'] == 'http-responses'
        assert selected['adapter'] == 'responses' and selected['tier'] == 'cheap'
    return options


def inert_response(monkeypatch, host, responder):
    """Replace only provider I/O; retain Host validation, receipts and usage."""
    calls = []

    def respond(data, parameters, request, control):
        calls.append({'data': data, 'parameters': deepcopy(parameters)})
        return host._result(responder(data, parameters), parameters, request,
                            observed_model='explicit-inert-fixture',
                            usage={'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2})
    monkeypatch.setattr(host, '_responses', respond)
    return calls


def test_http_expansion_is_admitted_through_the_charged_role_graph(tmp_path, monkeypatch, http_dispatch):
    base = tmp_path.resolve()
    root, path, host = campaign(base), vocabulary(base), agent_host.AgentHost()

    def choose(data, parameters):
        pin = {'sha256': parameters['output_schema']['properties']['request_sha256']['const']}
        return reply(pin, ['zorp-boson'])
    calls = inert_response(monkeypatch, host, choose)
    result = tools.expand_literature_query(root, QUERY, root / 'expand', host, vocabulary=path, **http_dispatch)
    assert result['status'] == 'admitted' and result['reason'] is None
    assert result['dispatch']['transport_id'] == 'http-responses'
    assert result['expansion']['model']['status'] == 'admitted'
    assert result['expansion']['model']['entries'] == ['zorp-boson']
    assert result['deterministic'] == q.expand(QUERY, vocabulary=path)
    assert len(calls) == len(charged(root)) == 1
    receipt = result['expansion']['model']['receipt']
    assert hashlib.sha256(Path(receipt['path']).read_bytes()).hexdigest() == receipt['sha256']
    _, state = cycle._load(root)
    assert len(state['graphs']) == 1 and state['graphs'][0]['usage']['calls'] == 1
    assert json.loads((root / 'expand/operation.json').read_text()) == result


def test_http_expansion_allowance_refusal_preserves_deterministic_terms(tmp_path, monkeypatch, http_dispatch):
    base = tmp_path.resolve()
    root, path, host = campaign(base, output_tokens=1), vocabulary(base), agent_host.AgentHost()
    calls = inert_response(monkeypatch, host, lambda *_: pytest.fail('allowance must refuse before provider I/O'))
    result = tools.expand_literature_query(root, QUERY, root / 'expand', host, vocabulary=path, **http_dispatch)
    assert result['status'] == 'refused' and result['reason'] == 'allowance_exhausted'
    assert result['dispatch']['transport_id'] == 'http-responses'
    assert result['expansion'] == result['deterministic'] == q.expand(QUERY, vocabulary=path)
    assert calls == [] and charged(root) == []


@pytest.mark.parametrize('failed_batch', [False, True])
def test_http_scoring_preserves_served_originals_and_charges_batches(tmp_path, monkeypatch, http_dispatch,
                                                                   failed_batch):
    base = tmp_path.resolve()
    root, host = campaign(base), agent_host.AgentHost()
    world, serving_id = serving_search(base / 'serving')
    _, envelope = tools.served_envelope(world.run, serving_id, node_id='worker', attempt=1)
    batch_ids = []

    def assess(data, parameters):
        schema = parameters['output_schema']['properties']
        ids = schema['assessments']['items']['properties']['candidate']['enum']
        batch_ids.append(ids)
        return {'kind': s.REPLY_KIND, 'batch_sha256': schema['batch_sha256']['const'],
                'assessments': [{'candidate': identity, 'relevance_score': 11 if failed_batch and
                                len(batch_ids) == 2 else 9, 'summary': 'Fictional reading aid.'}
                               for identity in ids]}
    calls = inert_response(monkeypatch, host, assess)
    result = tools.score_literature_evidence(root, world.run, serving_id, 'Which rate is reported?', root / 'score',
                                             host, node_id='worker', attempt=1,
                                             limits={'batch_size': 1, 'top_k': 3}, **http_dispatch)
    record = json.loads(Path(result['scoring']['path']).read_text())
    assert [item['original'] for item in record['evidence']] == envelope['results']
    assert len(calls) == 3 and len(charged(root)) == 1
    _, state = cycle._load(root)
    assert len(state['graphs']) == 1 and state['graphs'][0]['usage']['calls'] == 3
    assert result['dispatch']['transport_id'] == 'http-responses'
    assessments = {item['id']: item['assessment'] for item in record['evidence']}
    if failed_batch:
        assert result['reason'] == 'batch_failed' and result['status'] != 'scored'
        failed_id = batch_ids[1][0]
        assert assessments[failed_id]['status'] == 'error'
        assert assessments[failed_id]['relevance_score'] is None
        assert failed_id not in record['ranking']
    else:
        assert result['status'] == 'scored' and result['reason'] is None
        assert record['graph']['status'] == 'admitted' and len(record['ranking']) == 3
    assert assessments[batch_ids[0][0]]['status'] == 'scored'
    assert not record['summaries_are_evidence'] and not record['physics_verified']
    assert json.loads((root / 'score/operation.json').read_text()) == result


def charged(root):
    _, state = cycle._load(root)
    return [row['id'] for row in state['resource_ledger']]


def test_the_dispatcher_selects_a_qualified_worker_the_one_shot_call_cannot_run_on(dispatch):
    for role in (q.ROLE, s.ROLE, 'literature-discovery-selector'):
        selected = transport.select(role_registry.load(role), dispatch['preferences'], executables=dispatch['executables'])
        assert selected['transport_id'] == SELECTED and transport.load(SELECTED)['transport_kind'] == 'cli-worker'
        selection, refusal = tools._literature_dispatch(role, None, dispatch['preferences'], None, dispatch['executables'])
        assert selection is None and refusal == {'reason': 'transport_unsupported', 'missing': [SELECTED]}
    # Without a qualification record every literature card is refused before any route is chosen.
    unqualified = tools._literature_dispatch(q.ROLE, None, dispatch['preferences'], {}, None)[1]
    assert unqualified['reason'] == 'transport_unavailable'


def test_expansion_refuses_on_the_selected_route_and_keeps_the_deterministic_expansion(tmp_path, inert, dispatch):
    base = tmp_path.resolve()
    root, path = campaign(base), vocabulary(base)
    result = tools.expand_literature_query(root, QUERY, root / 'expand', agent_host.AgentHost(), vocabulary=path,
                                           **dispatch)
    deterministic = q.expand(QUERY, vocabulary=path)
    assert result['status'] == 'refused' and result['reason'] == 'transport_unsupported'
    assert result['missing'] == [SELECTED] and result['dispatch'] is None
    assert result['deterministic'] == result['expansion'] == deterministic
    assert deterministic['model'] == {'status': 'not_requested'} and inert == [] and charged(root) == []
    assert not (root / 'expand' / 'graph').exists()
    assert json.loads((root / 'expand' / 'operation.json').read_text()) == result


@pytest.mark.parametrize('case', ['missing-card', 'weak-tier'])
def test_expansion_refusals_stay_specific(tmp_path, inert, dispatch, case):
    base = tmp_path.resolve()
    root, path = campaign(base), vocabulary(base)
    options = dict(dispatch, vocabulary=path)
    if case == 'missing-card':
        options['roles'] = {'aliases': {}, 'roles': {}}
    else:
        options['preferences'] = preferences(drop_tiers=('cheap',))
    result = tools.expand_literature_query(root, QUERY, root / 'expand', agent_host.AgentHost(), **options)
    expected = {'missing-card': 'role_card_unavailable', 'weak-tier': 'model_tier_unavailable'}[case]
    assert result['status'] == 'refused' and result['reason'] == expected
    assert result['expansion'] == q.expand(QUERY, vocabulary=path) and inert == [] and charged(root) == []
    if case == 'weak-tier':
        assert 'model:cheap' in result['missing']


def serving_search(base):
    world = served_world.world(base)
    reply = served_world.serving.call(world.broker, 'search', served_world.args('search'))
    assert reply['status'] == 'ok', reply
    return world, json.loads(reply['stdout_tail'])['serving_id']


@pytest.mark.parametrize('case', ['qualified-route', 'stale-bytes', 'wrong-attempt', 'unserved-id', 'missing-card',
                                  'weak-tier'])
def test_scoring_refusals_stay_specific_and_never_become_accepted_scores(tmp_path, inert, dispatch, case):
    base = tmp_path.resolve()
    root = campaign(base)
    world, serving_id = serving_search(base / 'serving')
    options = dict(dispatch, node_id='worker', attempt=1, limits={'batch_size': 1, 'top_k': 3})
    if case == 'stale-bytes':
        folder = world.broker.workspace / 'outputs' / 'literature'
        target = next(folder.iterdir())
        target.write_bytes(target.read_bytes().replace(b'Alder', b'Alter'))
    elif case == 'wrong-attempt':
        options['attempt'] = 2
    elif case == 'unserved-id':
        serving_id = 'serving:999'
    elif case == 'missing-card':
        options['roles'] = {'aliases': {}, 'roles': {}}
    elif case == 'weak-tier':
        options['preferences'] = preferences(drop_tiers=('cheap',))
    result = tools.score_literature_evidence(root, world.run, serving_id, 'Which rate is reported?', root / 'score',
                                             agent_host.AgentHost(), **options)
    assert result['status'] == 'refused' and inert == [] and charged(root) == []
    if case in ('stale-bytes', 'wrong-attempt', 'unserved-id'):
        assert result['reason'] == 'stale_envelope' and result['scoring'] is None
        return
    if case == 'missing-card':
        assert result['reason'] == 'role_card_unavailable'
        return
    expected = {'qualified-route': 'transport_unsupported', 'weak-tier': 'model_tier_unavailable'}[case]
    assert result['reason'] == expected
    record = json.loads(Path(result['scoring']['path']).read_text())
    located = json.loads(served_world.serving.load(world.run, next(
        r for r in world.broker.verify_ledger() if r['status'] == 'ok')['reply']))
    assert [e['original'] for e in record['evidence']] == located['results']
    assert all(e['assessment']['relevance_score'] is None for e in record['evidence'])
    assert {e['assessment']['status'] for e in record['evidence'][:3]} == {'error'} and record['ranking'] == []


def step(operation, argv, **task):
    return {'id': 'S-1', 'kind': 'operate', 'operation': operation, 'role': None,
            'outputs': [{'path': 'outputs/record.json', 'kind': 'document'}],
            'parameters': {'task': {'max_wall_seconds': 300, **task}, 'launch': {'argv': argv}}}


def test_controller_operations_are_registered_host_operations_with_closed_launches():
    registered = operations.signatures()
    table = production_executor.executors()
    for name, policy in operations.LITERATURE_OPERATIONS.items():
        signature = registered[name]
        assert signature_conformance.entry_errors(name, signature) == []
        assert signature['implementation'] == policy['implementation'] and signature['effects'] == []
        assert name in table['host_operations'] and name not in table['operations']
        assert role_registry.load(policy['dispatches'])['family'] == 'research'
        argv = [*policy['argv'], '--request', 'inputs/request.json']
        admitted = step(name, argv, query='fictional query', question='q', serving_id='serving:1',
                        scope_pin={'path': 'inputs/scope.json'})
        assert operations.admission_errors(admitted) == []
        assert operations.literature_launch_errors(admitted) == []
        assert host_operations.admission_errors(admitted, table, branch='launch') == []
        for bad in ([*policy['argv'][:-1], 'prepare', '--request', 'x'], [*policy['argv'], '--request'],
                    ['python', '-m', 'ravel.workflow.literature_query', '--query', 'x']):
            assert operations.literature_launch_errors(step(name, bad))
    fragment = json.loads((Path(operations.SIGNATURES).parent / 'literature/registration/literature-operations.json')
                          .read_text())
    assert {k: registered[k] for k in fragment['operation_signatures']} == fragment['operation_signatures']
    from ravel.workflow import literature_index, literature_provider
    for module in (literature_index, literature_provider):
        source = Path(module.__file__).read_text()
        assert 'research_tools' not in source and 'literature_evidence_scoring' not in source


def test_the_controller_command_runs_the_operation_through_the_cli(tmp_path, inert, dispatch, capsys):
    base = tmp_path.resolve()
    root, path = campaign(base), vocabulary(base)
    request = base / 'request.json'
    request.write_text(json.dumps({'root': str(root), 'query': QUERY, 'output_dir': str(root / 'cli'),
                                   'vocabulary': path, **dispatch}))
    assert tools.main(['literature-expand', '--request', str(request)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed['kind'] == tools.EXPANSION_KIND and printed['reason'] == 'transport_unsupported' and inert == []
    assert printed['expansion'] == q.expand(QUERY, vocabulary=path)
    assert tools.literature_operations()['deterministic_expansion']['model_calls'] == 0
