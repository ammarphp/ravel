"""The research controller's peer integration, exercised against the integrated step and dispatch modules.

The step graph's research subgraph, its custody adoption, protected observation, worker packet selection,
the dispatcher's launch-channel and packet read-boundary evidence and the review resolver's protected
controller evidence run as installed. Interface fakes perform no provider or native calls.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import types

import pytest

from ravel.controller.step import custody as step_custody, graph as step_graph
from ravel.controller.step.services import StepHold, bound as live_store
from ravel.workflow import candidate_experiments as ce, research_controller as bridge
from ravel.workflow import agent_worker, broker, review_dispatch as rd
from p11_fakes import FakeRunStore, FakeStep, installed_step

Hold = StepHold


@contextmanager
def _live(store):
    with live_store(store):
        yield


@pytest.fixture
def peer(monkeypatch):
    """The integrated step graph and custody, with inert observation side records."""
    monkeypatch.setattr(step_graph, '_capture_session', lambda *args, **kw: (None, None, []))
    monkeypatch.setattr(step_graph, '_instruction_observation', lambda *args, **kw: {})
    monkeypatch.setattr(step_graph, '_usage_row', lambda *args, **kw: {})
    monkeypatch.setattr(step_graph, 'seat_closure', types.SimpleNamespace(observation_rows=lambda *args, **kw: {}))
    monkeypatch.setattr(step_graph, 'native_checks', types.SimpleNamespace(worker_inventory_rows=lambda *args, **kw: {}))
    return step_graph, step_custody


def state(tmp_path):
    store = FakeRunStore('peer-control', root=tmp_path / 'protected')
    acting = {'id': 'campaign', 'kind': 'subgraph', 'depends_on': [],
              'outputs': [{'path': 'outputs/progress.json', 'kind': 'document', 'required': True}]}
    return {'step': acting, 'acting': acting, 'branch': 'subgraph',
            'context': {'run_id': store.run_id, 'store_root': str(store.store_root), 'run_dir': str(tmp_path)},
            'store': store, 'preflight': {'graph': {'id': 'research.loop', 'instance': {}}}}


def _store_of(current):
    return current['store']


def test_research_subgraph_calls_adapter_and_stages_exact_progress(peer, tmp_path, monkeypatch):
    graph, custody = peer
    current = state(tmp_path)
    output = tmp_path / 'steps/campaign/outputs/progress.json'
    output.parent.mkdir(parents=True); output.write_text('{"scientific_acceptance":false}')
    pin = {'path': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'size': output.stat().st_size}
    calls = []
    def invoke(store, acting, context):
        calls.append((store, acting, context))
        return {'kind': 'research_progress_synthesis', 'parent_task_accepted': False,
                'controller_outcome': {'status': 'completed', 'reason': None, 'outputs': [pin]}}
    monkeypatch.setattr(bridge, 'invoke', invoke)
    with _live(_store_of(current)):
        child = graph.subgraph(current)['child']
    assert calls[0][1] is current['acting']
    assert calls[0][0] is _store_of(current)
    assert child['outcome'] == 'ok'
    rows = custody.subgraph_adoption(_store_of(current), run_dir=tmp_path,
        step=current['acting'], attempt=1, card=None, child=child, inputs_custody=[])
    assert len(rows) == 1 and rows[0]['status'] == 'staged'
    assert rows[0]['artifact'] == 'campaign:outputs/progress.json'
    assert rows[0]['sha256'] == pin['sha256']
    # The ordinary verdict remains separate from staging.
    assert all(row['record']['status'] == 'staged' for row in _store_of(current).scan('custody'))
    output.write_text('{}')
    with pytest.raises(Hold, match='adoption_bytes_changed'):
        custody.subgraph_adoption(_store_of(current), run_dir=tmp_path,
            step=current['acting'], attempt=1, card=None, child=child, inputs_custody=[])


@pytest.mark.parametrize('status,reason', [('held','research_effect_required'),
    ('budget_exhausted','budget_exhausted'), ('unknown','research_outcome_unbound')])
def test_noncompleted_research_adapter_cannot_become_ok(peer, tmp_path, monkeypatch, status, reason):
    graph, _ = peer
    monkeypatch.setattr(bridge, 'invoke', lambda *args: {'controller_outcome': {'status': status, 'reason': 'needs evidence'}})
    current = state(tmp_path)
    with _live(_store_of(current)), pytest.raises(Hold, match=reason):
        graph.subgraph(current)


def test_research_adapter_refusal_is_a_typed_hold(peer, tmp_path, monkeypatch):
    graph, _ = peer
    def refuse(*args):
        raise ValueError('research subgraph needs its adopted source-bound request pin')
    monkeypatch.setattr(bridge, 'invoke', refuse)
    current = state(tmp_path)
    with _live(_store_of(current)), pytest.raises(Hold, match='research_request_unbound'):
        graph.subgraph(current)
    assert _store_of(current).scan('step-subgraph') == []


def _observe_state(tmp_path):
    current = state(tmp_path)
    current.update(branch='worker', reservation={'key': 'one'},
                   packet={'delivery': 'delivered', 'manifest': {}, 'sha256': 'packet'})
    current['preflight'] = {'spec': {'node_id': 'worker'}}
    return current


def _observe(graph, current, receipt, monkeypatch):
    monkeypatch.setattr(agent_worker, 'load_receipt', lambda *args: deepcopy(receipt))
    monkeypatch.setattr(graph, 'evidence', types.SimpleNamespace(mirror=lambda *args, **kw: [], comparison_rows=lambda *a, **k: {}, call_counts=lambda rows: {}))
    monkeypatch.setattr(graph, 'budget', types.SimpleNamespace(settle=lambda *args, **kw: None))
    with _live(_store_of(current)):
        graph.observe(current)
    return _store_of(current).scan('step-observation')[0]['record']


def test_protected_observation_copies_actual_transport_and_no_invented_freshness(peer, tmp_path, monkeypatch):
    graph, _ = peer
    current = _observe_state(tmp_path)
    receipt = {'status':'ok', 'session_id':'actual-session', 'actor_id':'actual-actor',
        'attestation':'transport_attested', 'model': {'requested':'requested-model','observed':'actual-model'},
        'usage': {'reported':False}, 'transport': {'id':'actual-cli','transport_kind':'cli-worker',
            'observation': {'stdout_sha256':'actual-stdout'}},
        'isolation': {'profile':'ravel-sandbox','user_configuration_loaded':False,
                      'evidence': {'confirmed':True}}}
    observed = _observe(graph, current, receipt, monkeypatch)
    assert observed['model']['observed'] == 'actual-model'
    assert observed['isolation'] == receipt['isolation']
    assert 'fresh_request' not in observed['isolation']
    assert 'parent_transcript_supplied' not in observed['isolation']
    assert observed['transport_evidence']['execution_mode'] == 'transport_attested_cli'
    assert observed['transport_evidence']['observation']['stdout_sha256'] == 'actual-stdout'
    receipt['transport']['observation']['stdout_sha256'] = 'mutated'
    assert observed['transport_evidence']['observation']['stdout_sha256'] == 'actual-stdout'


def test_worker_claimed_freshness_without_dispatcher_launch_evidence_is_dropped(peer, tmp_path, monkeypatch):
    graph, _ = peer
    receipt = {'status':'ok', 'session_id':'actual-session', 'actor_id':'actual-actor',
        'transport': {'id':'actual-cli','transport_kind':'cli-worker'}, 'usage': {},
        'isolation': {'user_configuration_loaded':False, 'evidence': {'confirmed':True},
                      'fresh_request':True, 'parent_transcript_supplied':False}}
    observed = _observe(graph, _observe_state(tmp_path), receipt, monkeypatch)
    assert 'fresh_request' not in observed['isolation']
    assert 'parent_transcript_supplied' not in observed['isolation']


def test_governed_host_refuses_missing_dispatcher_freshness_proof(tmp_path):
    from test_p11_bridge import setup
    from ravel.workflow import research_cycle as cycle
    root, spec, store, context = setup(tmp_path)
    peer = FakeStep()
    actual = peer.run
    def without_proof(store, step, context):
        result = actual(store, step, context)
        for row in store.rows:
            if row['kind'] == 'step-observation':
                row['record']['isolation'].pop('fresh_request', None)
                row['record']['isolation'].pop('parent_transcript_supplied', None)
        return result
    peer.run = without_proof
    with installed_step(peer), bridge.bound(store, context):
        result = cycle.execute_graph(root, root / 'no-fresh-proof', spec, object())
    assert not result['complete']
    assert not store.scan('research-call')


def _finish_state(tmp_path, monkeypatch, graph):
    current = state(tmp_path)
    monkeypatch.setattr(graph.operations, 'route_context', lambda store, context: {'store': store})
    monkeypatch.setattr(graph.operations, 'observe_route', lambda step, outcome, context: outcome)
    return current


def test_outcome_names_adopted_destination_and_preserves_custody_identity(peer, tmp_path, monkeypatch):
    graph, _ = peer
    current = _finish_state(tmp_path, monkeypatch, graph)
    row = {'artifact':'campaign:outputs/progress.json', 'path':'outputs/progress.json',
           'destination':'steps/campaign/outputs/progress.json', 'sha256':'1'*64,
           'artifact_id':'2'*64, 'attempt':1, 'record_id':'custody-one'}
    current.update(validation={'passed':True}, checks={'passed':True, 'accepted':[row]})
    with _live(_store_of(current)):
        outcome = graph.finish(current)['outcome']
    assert outcome['status'] == 'completed'
    # The plan path stays the output's path (P04 consumers key on it); the adopted destination is named beside it.
    assert outcome['outputs'] == [{'artifact':row['artifact'], 'path':row['path'], 'destination':row['destination'],
                                   'sha256':row['sha256'], 'artifact_id':row['artifact_id'], 'attempt':row['attempt'],
                                   'record_id':row['record_id']}]


# ---- dispatcher launch evidence ---------------------------------------------------------------

@pytest.fixture
def leader():
    """A real child that leads its own session, as the supervisor spawns a worker."""
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        yield child.pid
    finally:
        child.kill(); child.wait(timeout=10)


def launch_fixture(tmp_path, argv=None):
    prompt = b'Explicit projected packet and worker surface.\n'
    stdin = tmp_path / 'prompt.txt'; stdin.write_bytes(prompt)
    argv = argv or ['codex', 'exec', '--json', '-']
    audit = {'argv':argv, 'argv_sha256':ce.digest(argv),
             'prompt': {'sha256':hashlib.sha256(prompt).hexdigest()}, 'context_channels':['stdin_packet']}
    audit_path = tmp_path / 'audit.json'; audit_path.write_text(json.dumps(audit))
    descriptor = {'argv':argv, 'transport': {'agent':'codex', 'transport_kind':'cli-worker',
        'stdin': {'path':str(stdin), 'sha256':hashlib.sha256(prompt).hexdigest()},
        'prompt_audit': {'path':str(audit_path), 'sha256':hashlib.sha256(audit_path.read_bytes()).hexdigest()}}}
    return descriptor, stdin.open('rb')


helper = agent_worker._launch_context_evidence


def test_actual_launch_proof_binds_controlled_argv_stdin_and_new_process_session(tmp_path, leader):
    descriptor, source = launch_fixture(tmp_path)
    proof = helper(descriptor, source, spawn_pid=leader)
    assert proof['fresh_session'] and proof['no_parent_transcript_channel']
    assert proof['scope'] == 'launch_channels_only'
    assert source.tell() == 0
    Path(descriptor['transport']['stdin']['path']).write_bytes(b'X')
    with pytest.raises(ValueError, match='argv or stdin changed'):
        helper(descriptor, source, spawn_pid=leader)


@pytest.mark.parametrize('extra', [['resume'], ['--resume=old'], ['--session-id','old'], ['--input-format','stream-json'],
                                  ['--from-pr','123'], ['--conversation-id=old'], ['--resume-at','old']])
def test_resume_and_conversation_payload_channels_never_get_fresh_proof(tmp_path, leader, extra):
    descriptor, source = launch_fixture(tmp_path, ['codex','exec',*extra,'-'])
    proof = helper(descriptor, source, spawn_pid=leader)
    assert not proof['fresh_session']
    assert not proof['no_parent_transcript_channel']


def test_no_spawn_and_changed_prompt_audit_cannot_mint_proof(tmp_path, leader):
    descriptor, source = launch_fixture(tmp_path)
    assert not helper(descriptor, source, spawn_pid=0)['fresh_session']
    if os.getsid(os.getpid()) != os.getpid():
        # A process that does not lead its own session is not a freshly spawned worker.
        assert not helper(descriptor, source, spawn_pid=os.getpid())['fresh_session']
    Path(descriptor['transport']['prompt_audit']['path']).write_text('{}')
    with pytest.raises(ValueError, match='audit changed'):
        helper(descriptor, source, spawn_pid=leader)


# ---- protected controller evidence ------------------------------------------------------------

def protected_call(tmp_path):
    run = tmp_path / 'run'; run.mkdir()
    store = FakeRunStore('protected-evidence', root=tmp_path / 'protected')
    output = run / 'steps/seat/outputs/public-record.json'; output.parent.mkdir(parents=True)
    output.write_text('{"verdict":"accept"}')
    pin = {'path':str(output), 'sha256':hashlib.sha256(output.read_bytes()).hexdigest(), 'size':output.stat().st_size}
    node = {'id':'seat', 'packet': {'manifest_sha256':'1'*64}}
    request = {'request_id':'request-one'}
    observed = {'step_id':'seat', 'attempt':1, 'receipt_sha256':'2'*64, 'status':'ok',
        'actor_id':'dispatcher-actor', 'session_id':'actual-session',
        'model': {'observed':'actual-model'}, 'tool_inventory': [],
        'transport_evidence': {'execution_mode':'transport_attested_cli'},
        # The shape controller.step.graph.observe records: freshness only from the dispatcher's launch context.
        'isolation': {'fresh_request':True, 'parent_transcript_supplied':False,
                      'launch_context': {'fresh_session':True, 'no_parent_transcript_channel':True,
                                         'scope':'launch_channels_only'}}}
    call = {'step_id':'seat', 'node':node, 'request':request, 'run_dir':str(run), 'output':pin,
        'outcome': {'step_id':'seat', 'status':'completed', 'attempt':1, 'receipts':['2'*64],
                    'outputs':[{'path':'steps/seat/outputs/public-record.json', 'sha256':pin['sha256']}]},
        'observation':observed, 'result_sha256':'3'*64}
    store.append('research-call',call); store.append('step-observation',observed)
    binding = {'run_id':store.run_id, 'graph_root':str(run/'graph'), 'request_id':'request-one',
        'node_sha256':ce.digest(node), 'request_sha256':ce.digest(request), 'result_sha256':'3'*64,
        'actor_id':'dispatcher-actor', 'session_id':'actual-session', 'packet_sha256':'1'*64,
        'observed_model':'actual-model', 'execution_mode':'transport_attested_cli',
        'public_value_sha256':ce.digest({'verdict':'accept'})}
    return store, binding, output


@pytest.mark.parametrize('evidence,expected', [
    ('launch', 'transport_attested'),
    ('stored_claim_only', 'self_attested'),       # an attestation field is a claim, never evidence
    ('no_parent_channel_unproven', 'self_attested'),
    ('stale_isolation', 'self_attested'),          # fresh flags without the launch observation
    ('http_fresh', 'transport_attested'),
    ('http_unfresh', 'self_attested'),
    ('unknown_mode', 'self_attested')])
def test_controller_attestation_comes_only_from_dispatcher_launch_and_transport_evidence(evidence, expected):
    launch = {'fresh_session': True, 'no_parent_transcript_channel': True, 'scope': 'launch_channels_only'}
    fresh = {'fresh_request': True, 'parent_transcript_supplied': False}
    observed = {'transport_evidence': {'execution_mode': 'transport_attested_cli'},
                'isolation': {**fresh, 'launch_context': dict(launch)}}
    if evidence == 'stored_claim_only':
        observed = {'attestation': 'transport_attested', 'transport_evidence': {'execution_mode': 'transport_attested_cli'},
                    'isolation': {}}
    elif evidence == 'no_parent_channel_unproven':
        observed['isolation']['launch_context']['no_parent_transcript_channel'] = False
    elif evidence == 'stale_isolation':
        del observed['isolation']['launch_context']
    elif evidence == 'http_fresh':
        observed = {'transport_evidence': {'execution_mode': 'responses_http'}, 'isolation': dict(fresh)}
    elif evidence == 'http_unfresh':
        observed = {'transport_evidence': {'execution_mode': 'responses_http'}, 'isolation': {}}
    elif evidence == 'unknown_mode':
        observed = {'transport_evidence': {'execution_mode': 'host_mediated_external'}, 'isolation': dict(fresh)}
    assert rd.controller_attestation(observed) == expected
    assert rd.controller_attestation(None) == 'self_attested'


@pytest.mark.parametrize('damage', [None,'actor','session','packet','model','output','duplicate_observation'])
def test_protected_controller_evidence_requires_exact_actor_session_packet_model_and_bytes(tmp_path, damage):
    store, binding, output = protected_call(tmp_path)
    if damage in {'actor','session','packet','model'}:
        field = {'actor':'actor_id','session':'session_id','packet':'packet_sha256','model':'observed_model'}[damage]
        binding[field] = 'different'
    elif damage == 'output':output.write_text('{}')
    elif damage == 'duplicate_observation':store.append('step-observation',store.scan('step-observation')[0]['record'])
    with bridge.bound(store, {'run_dir':str(tmp_path/'run')}):
        proof = rd._controller_evidence(binding)
    assert (proof is not None) == (damage is None)


@pytest.mark.parametrize('fresh,loaded,parent,expected', [(True,False,True,True),
    (False,False,True,False), (True,True,True,False), (True,False,False,True)])
def test_actual_observation_maps_only_explicit_dispatcher_launch_facts(peer, tmp_path, monkeypatch,
                                                                    fresh,loaded,parent,expected):
    graph, _ = peer
    current = _observe_state(tmp_path)
    receipt={'status':'ok','actor_id':'assigned-actor','session_id':'observed-session',
        'transport':{'id':'cli','transport_kind':'cli-worker'}, 'usage':{},
        'isolation':{'user_configuration_loaded':loaded,'evidence':{'confirmed':True},
            'launch_context':{'fresh_session':fresh,'no_parent_transcript_channel':parent}}}
    isolation=_observe(graph, current, receipt, monkeypatch)['isolation']
    assert isolation['fresh_request'] is expected
    assert isolation['parent_transcript_supplied'] is (False if parent else None)


@pytest.fixture
def inert_census(monkeypatch):
    monkeypatch.setattr(rd, 'census', lambda run, exclude=None: (['explicit-fake-author-context'], []))
    monkeypatch.setattr(rd, 'author_models', lambda run, exclude=None: {})


@pytest.mark.parametrize('changed', [False,True])
@pytest.mark.parametrize('read_boundary',['tools_disabled','packet_only'])
def test_p13_graph_resolution_rechecks_protected_evidence_and_keeps_existing_projection_gates(tmp_path,inert_census,changed,read_boundary):
    store,binding,output=protected_call(tmp_path)
    if read_boundary=='packet_only':
        boundary={'kind':'controller-packet-read-boundary.v1','verified':True,
                  'packet_sha256':binding['packet_sha256'],'role':'critic','broker_actions':['read','write']}
        for row in store.rows:
            if row['kind']=='research-call':row['record']['observation']['isolation']['packet_read_boundary']=deepcopy(boundary)
            elif row['kind']=='step-observation':row['record']['isolation']['packet_read_boundary']=deepcopy(boundary)
    query={'run':str(tmp_path/'run'),'role':'critic','subject_sha256':'4'*64,
           'receipt_sha256':'5'*64,'output_sha256':binding['public_value_sha256'],
           'packet_sha256':binding['packet_sha256']}
    record={'controller_binding':binding,'packet':{'manifest_sha256':query['packet_sha256']},
        'receipt_sha256':query['receipt_sha256'],'role':'critic','public_value_sha256':query['output_sha256'],
        'observation':'transport_attested_cli','attestation':'transport_attested','fresh_request':True,
        'parent_transcript_supplied':False,'read_boundary':read_boundary,'read_boundary_verified':True,
        'packet_builder':rd.PROTOCOL,'packet_subjects':[query['subject_sha256']],
        'exposure':{'author_identity':'withheld','author_rationale':'withheld',
                    'reference_values':'withheld','peer_verdicts':'withheld'},'request_id':'request-one'}
    if changed:output.write_text('{}')
    with bridge.bound(store,{'run_dir':str(tmp_path/'run')}):
        proof=rd._graph(query,record)
        assert (proof is not None) == (not changed)
        if proof is not None:
            assert proof['read_boundary'] == read_boundary
        # Even exact protected actor/session/output cannot replace packet projection.
        record['packet_builder']='unrecognized-author-summary'
        assert rd._graph(query,record) is None


def packet_workspace(tmp_path):
    packet=tmp_path/'original-packet';(packet/'artifacts').mkdir(parents=True)
    raw=b'{"scientific":"projected evidence"}\n';(packet/'artifacts/one.json').write_bytes(raw)
    manifest={'role':'critic','artifacts':[{'id':'one','path':'artifacts/one.json',
              'sha256':hashlib.sha256(raw).hexdigest()}]}
    manifest['sha256']=ce.digest(manifest)
    (packet/'manifest.json').write_text(json.dumps(manifest))
    ws=tmp_path/'worker'
    for folder in ('inputs/packet/artifacts','outputs','scratch'):(ws/folder).mkdir(parents=True)
    for name in ('manifest.json','artifacts/one.json'):
        (ws/'inputs/packet'/name).write_bytes((packet/name).read_bytes())
    (ws/'inputs/packet.md').write_text('Controller instructions for this exact role.')
    (ws/'inputs/toolbelt.json').write_text('{"trusted":"workspace read/write"}')
    (ws/'inputs/final-schema.json').write_text('{"type":"object"}')
    copies=[{'path':path.relative_to(ws).as_posix(),'sha256':broker.sha(path)}
            for path in (ws/'inputs').rglob('*') if path.is_file() and path.name not in {'toolbelt.json','final-schema.json'}]
    binding={'path':str(packet),'manifest_sha256':manifest['sha256']}
    record={'packet':binding,'spec':{'work_order':None},'input_copies':copies}
    audit=tmp_path/'prompt-audit.json';audit.write_text(json.dumps({'final_schema_sha256':broker.sha(ws/'inputs/final-schema.json')}))
    descriptor={'transport':{'controller':{'research_packet':binding,'research_role':'critic',
                'packet_sha256':broker.sha(ws/'inputs/packet.md')},
                'prompt_audit':{'path':str(audit),'sha256':broker.sha(audit)}}}
    tools=[{'name':'ws_read','executes_through':{'action':'read'}},
           {'name':'ws_write','executes_through':{'action':'write'}}]
    isolation={'user_configuration_loaded':False,'evidence':{'confirmed':True}}
    return ws,record,descriptor,tools,isolation


@pytest.mark.parametrize('damage',[None,'extra_input','changed_copy','preexisting_output','rich_tool',
                                   'config_loaded','denial_unconfirmed','wrong_packet'])
def test_real_packet_reader_and_broker_capability_census_produce_only_exact_packet_boundary(tmp_path,damage):
    ws,record,descriptor,tools,isolation=packet_workspace(tmp_path)
    if damage=='extra_input':(ws/'inputs/author-notes.json').write_text('private author rationale')
    elif damage=='changed_copy':(ws/'inputs/packet/artifacts/one.json').write_text('{}')
    elif damage=='preexisting_output':(ws/'outputs/author-result.json').write_text('{}')
    elif damage=='rich_tool':tools.append({'name':'lookup','executes_through':{'action':'knowledge query'}})
    elif damage=='config_loaded':isolation['user_configuration_loaded']=True
    elif damage=='denial_unconfirmed':isolation['evidence']['confirmed']=False
    elif damage=='wrong_packet':descriptor['transport']['controller']['research_packet']={'different':True}
    before=deepcopy(tools)
    proof=agent_worker._packet_read_boundary(ws,record,descriptor,tools,isolation)
    assert (proof is not None)==(damage is None)
    assert tools==before  # Broader tool capability is preserved; no false proof is issued.
    if proof:
        assert proof['broker_actions']==['read','write']
        assert proof['packet_sha256']==record['packet']['manifest_sha256']


def test_spawn_proof_failure_keeps_actual_child_registered_for_existing_cleanup(tmp_path):
    import ast
    function=ast.parse(inspect.getsource(agent_worker.supervise)).body[0]
    outer=next(node for node in function.body if isinstance(node,ast.Try) and node.finalbody)
    spawn=next(node for node in ast.walk(outer) if isinstance(node,ast.With)
        and any(isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute)
                and call.func.attr=='steering_dispatch' for call in ast.walk(node.items[0].context_expr)))
    # Execute the exact installed spawn/registration branch and the existing first
    # cleanup branch, with inert process and dispatch interfaces.
    cleanup=outer.finalbody[0]
    snippet=ast.Module(body=[ast.Try(body=[spawn],handlers=[],orelse=[],finalbody=[cleanup])],type_ignores=[])
    calls=[]
    class Child:
        pid=123;stdout=None;stderr=None
        def poll(self):return None
    from contextlib import nullcontext
    def fail(*args,**kwargs):raise ValueError('prompt proof changed after spawn')
    namespace={'gate_wiring':types.SimpleNamespace(steering_dispatch=lambda *args:nullcontext()),
        'subprocess':types.SimpleNamespace(Popen=lambda *args,**kwargs:Child(),PIPE='inert-pipe'),'run':tmp_path,'node_id':'seat',
        'argv':['inert'],'ws':tmp_path,'env':{},'source':None,
        # The inert child leads its own process group, as start_new_session makes it.
        'os':types.SimpleNamespace(getpgid=lambda pid:pid),
        'registration':{'child_pid':None,'child_pgid':None},
        'descriptor':{'transport':{'transport_kind':'cli-worker','prompt_audit':{'path':'inert-audit','sha256':'0'*64}}},
        'execution':{'isolation':{}},'_process_record':lambda run,row:calls.append(('registered',deepcopy(row))),
        '_launch_context_evidence':fail,'_group_alive':lambda pgid:True,
        '_terminate_child':lambda child,pgid:calls.append(('terminated',pgid)) or {'gone':True}}
    with pytest.raises(ValueError,match='proof changed'):
        exec(compile(ast.fix_missing_locations(snippet),'actual-supervisor-branches','exec'),namespace)
    assert calls[0][0]=='registered' and calls[0][1]['child_pgid']==123
    assert calls[-1]==('terminated',123)
    # Without the builder's prompt audit the dispatcher claims no launch evidence at all.
    calls.clear()
    namespace.update(registration={'child_pid':None,'child_pgid':None},execution={'isolation':{}},
                     descriptor={'transport':{'transport_kind':'cli-worker'}})
    exec(compile(ast.fix_missing_locations(ast.Module(body=[spawn],type_ignores=[])),'actual-supervisor-spawn','exec'),
         namespace)
    assert calls==[('registered',{'child_pid':123,'child_pgid':123})]
    assert 'launch_context' not in namespace['execution']['isolation']


@pytest.mark.parametrize('case',['packet_only','actual_node_input','edge','edge_wrong_sha','edge_extra_input','unrelated_row','different_packet'])
def test_worker_copy_omits_only_redundant_protected_snapshot_with_exhaustive_projection(case):
    select=step_graph._research_copy_rows
    original={'id':'seat','parameters':{'research_node':{'role':'critic','packet':{'path':'original','manifest_sha256':'1'*64},'inputs':[]}}}
    snapshot={'artifact':'inputs/research/seat.json','sha256':'2'*64,'kind':'run-input'}
    additional={'artifact':'inputs/actual-measurement.json','sha256':'3'*64,'kind':'run-input'}
    if case=='different_packet':original['parameters']['research_packet']={'path':'different','manifest_sha256':'0'*64}
    if case=='actual_node_input':original['parameters']['research_node']['inputs']=[{'id':'actual-measurement','sha256':'3'*64}]
    if case.startswith('edge'):
        original['parameters'].update(research_packet={'path':'public-edge','manifest_sha256':'4'*64},research_packet_subject_sha256='5'*64)
        original['parameters']['research_node']={'role':'rdj_edge_reviewer','packet':None,'inputs':[{'id':'rdj-payload','sha256':'5'*64}]}
        if case=='edge_wrong_sha':original['parameters']['research_packet_subject_sha256']='wrong'
        if case=='edge_extra_input':original['parameters']['research_node']['inputs'].append({'id':'private-author-note','sha256':'6'*64})
    rows=[snapshot,additional] if case=='unrelated_row' else [snapshot]
    before=deepcopy(original)
    selected=select(original,rows)
    expected_drop=case in {'packet_only','edge','unrelated_row'}
    assert (snapshot not in selected)==expected_drop
    if case=='unrelated_row':assert additional in selected
    assert original==before  # Original protected step inputs/contract remain intact.


def test_worker_receives_the_research_packet_and_controller_facts_name_it():
    packet={'path':'original','manifest_sha256':'1'*64}
    acting={'id':'seat','parameters':{'research_node':{'role':'critic','packet':packet,'inputs':[]},
                                      'research_packet':packet,'research_packet_subject_sha256':None}}
    projection={'path':'projection','manifest_sha256':'7'*64}
    current={'acting':acting,'preflight':{'review_packet':projection}}
    assert step_graph._worker_packet(current)==packet
    current['acting']={'id':'other','parameters':{}}
    assert step_graph._worker_packet(current)==projection  # The review projection stays for every other step.


def edge_workspace(tmp_path):
    ws,record,descriptor,tools,isolation=packet_workspace(tmp_path)
    packet=Path(record['packet']['path'])
    raw=(packet/'artifacts/one.json').read_bytes();subject=hashlib.sha256(raw).hexdigest()
    (packet/'artifacts/one.json').unlink();(ws/'inputs/packet/artifacts/one.json').unlink()
    (packet/'artifacts/rdj-payload.json').write_bytes(raw)
    manifest={'kind':'rdj_role_packet_v1','role':'rdj_edge_reviewer','artifacts':[{
        'id':'rdj-payload','path':'artifacts/rdj-payload.json','sha256':subject}]}
    manifest['sha256']=ce.digest(manifest);(packet/'manifest.json').write_text(json.dumps(manifest))
    for name in ('manifest.json','artifacts/rdj-payload.json'):(ws/'inputs/packet'/name).write_bytes((packet/name).read_bytes())
    record['packet']={'path':str(packet),'manifest_sha256':manifest['sha256']}
    record['input_copies']=[{'path':path.relative_to(ws).as_posix(),'sha256':broker.sha(path)}
        for path in (ws/'inputs').rglob('*') if path.is_file() and path.name not in {'toolbelt.json','final-schema.json'}]
    descriptor['transport']['controller'].update(research_packet=record['packet'],research_role='rdj_edge_reviewer',
        research_inputs=[{'id':'rdj-payload','sha256':subject}],research_packet_subject_sha256=subject)
    return ws,record,descriptor,tools,isolation


@pytest.mark.parametrize('damage',[None,'wrong_subject','extra_original_input','wrong_original_id'])
def test_edge_packet_publisher_authenticates_exact_sole_original_public_payload(tmp_path,damage):
    ws,record,descriptor,tools,isolation=edge_workspace(tmp_path)
    facts=descriptor['transport']['controller']
    if damage=='wrong_subject':facts['research_packet_subject_sha256']='0'*64
    elif damage=='extra_original_input':facts['research_inputs'].append({'id':'private-note','sha256':'0'*64})
    elif damage=='wrong_original_id':facts['research_inputs'][0]['id']='private-note'
    proof=agent_worker._packet_read_boundary(ws,record,descriptor,tools,isolation)
    assert (proof is not None)==(damage is None)
    if proof:assert proof['subject_sha256']==facts['research_inputs'][0]['sha256']


@pytest.mark.parametrize('damage',[None,'protected_subject','protected_packet','query_subject'])
def test_p13_edge_original_query_packet_none_requires_protected_exact_public_projection(tmp_path,inert_census,damage):
    ws,record,descriptor,tools,isolation=edge_workspace(tmp_path/'edge')
    boundary=agent_worker._packet_read_boundary(ws,record,descriptor,tools,isolation)
    store,binding,output=protected_call(tmp_path)
    subject=boundary['subject_sha256'];binding['packet_sha256']=None
    for row in store.rows:
        if row['kind']=='research-call':
            call=row['record'];call['node']={'id':'seat','role':rd.RDJ_EDGE_ROLE,'packet':None,
                'inputs':[{'id':rd.RDJ_PAYLOAD,'sha256':subject}]}
            call['worker_packet']=deepcopy(record['packet']);call['worker_packet_subject_sha256']=subject
            binding['node_sha256']=ce.digest(call['node'])
            call['observation']['isolation']['packet_read_boundary']=deepcopy(boundary)
            if damage=='protected_subject':call['worker_packet_subject_sha256']='0'*64
            elif damage=='protected_packet':call['worker_packet']['manifest_sha256']='0'*64
        elif row['kind']=='step-observation':row['record']['isolation']['packet_read_boundary']=deepcopy(boundary)
    query={'run':str(tmp_path/'run'),'role':rd.RDJ_EDGE_ROLE,'subject_sha256':subject,
           'receipt_sha256':'5'*64,'output_sha256':binding['public_value_sha256'],'packet_sha256':None}
    kept={'controller_binding':binding,'controller_edge_subject_sha256':subject,'packet':None,
        'graph_root':str(tmp_path/'run/graph'),'receipt_sha256':query['receipt_sha256'],'role':rd.RDJ_EDGE_ROLE,
        'public_value_sha256':query['output_sha256'],'observation':'transport_attested_cli','attestation':'transport_attested',
        'fresh_request':True,'parent_transcript_supplied':False,'read_boundary':'packet_only','read_boundary_verified':True,
        'packet_builder':rd.RDJ,'packet_subjects':[subject],'exposure':{'author_identity':'withheld',
         'author_rationale':'permitted','reference_values':'permitted','peer_verdicts':'withheld'},'request_id':'request-one'}
    if damage=='query_subject':query['subject_sha256']='0'*64
    with bridge.bound(store,{'run_dir':str(tmp_path/'run')}):proof=rd._graph(query,kept)
    assert (proof is not None)==(damage is None)
    assert query['packet_sha256'] is None
