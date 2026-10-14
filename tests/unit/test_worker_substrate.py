"""Graph-substrate joins; the legacy agent-graph fixture changes only to type a definite outage."""
from copy import deepcopy
import pytest
from ravel.workflow import agent_graph as graph


def put(rundir, ws, rel, text):
    """Write a worker output through its broker: only a broker output pin credits an output."""
    from ravel.workflow import broker
    tool=broker.Broker(rundir,ws,node_id=ws.parent.name,attempt=int(ws.name),allowed_actions=['write'],max_calls=100000)
    assert tool.call({'call_id':'put-'+broker.digest([rel,text])[:24],'action':'write',
                      'args':{'path':rel,'content':text}})['status']=='ok'


def worker_spec():
    from test_agent_worker import spec
    return spec()


def plan(tmp_path, kind='agent'):
    spec=worker_spec() if kind=='agent' else {'schema_version':1,'kind':'agent-map','id':'group',
        'spec':worker_spec(),'items':[{'key':k,'inputs':[]} for k in ('a','b','c')],'join':'all'}
    return {'schema_version':1,'graph_id':'worker-control','budget':{'max_nodes':3,'max_calls':6,
        'max_output_tokens':0,'max_wall_seconds':60,'max_reworks':2},'nodes':[
        {'id':'dispatch','kind':kind,'role':'executor','depends_on':[],'inputs':[],'packet':None,
         'action':'dispatch','parameters':{'rundir':str(tmp_path/'run'),'spec':spec},'max_attempts':2}]}


def test_agent_worker_spec_is_admitted_and_launch_descriptor_cannot_be_data(tmp_path):
    spec=plan(tmp_path)
    assert graph.validate(spec)['nodes'][0]['kind']=='agent'
    spec['nodes'][0]['parameters']['launch_spec']={'argv':['/bin/sleep','1']}
    with pytest.raises(graph.GraphError):graph.validate(spec)


def test_worker_executes_on_substrate_and_reuses_receipt(tmp_path,monkeypatch):
    from ravel.workflow import agent_worker as worker, effect_ledger
    from test_agent_graph import Host
    monkeypatch.setenv('RAVEL_STATE_DIR',str(tmp_path/'state'))
    (tmp_path/'run').mkdir()
    calls=[]
    def dispatch(rundir,spec,**options):
        calls.append(spec['node_id'])
        ws=worker.materialize(rundir,spec,graph=options['graph'],framework_step=options['framework_step'])
        put(rundir,ws,'outputs/result.txt','output')
        return worker.finish(rundir,spec,final={'completed':True},execution={'exit_status':0})
    monkeypatch.setattr(worker,'dispatch',dispatch)
    root=tmp_path/'graph';graph.create(root,plan(tmp_path));host=Host()
    assert graph.execute(root,host)['complete']
    assert graph.execute(root,host)['complete'] and calls==['worker']
    receipt=worker.load_receipt(tmp_path/'run','worker',1)
    assert receipt['graph']['id']=='worker-control'
    assert receipt['framework_step']['thread_id']
    assert len(effect_ledger.receipts(root/'effects'))==1


def test_control_preserves_legacy_identity_and_charges_one_effect(tmp_path):
    from ravel.workflow import effect_ledger
    from test_agent_graph import Host, node, spec
    root=tmp_path/'graph';graph.create(root,spec([node('effect')]))
    host=Host();graph.execute(root,host);graph.execute(root,host)
    state=graph.status(root);raw=graph.read_json(root/graph.STATE)
    attempt=raw['nodes']['effect']['attempt_id']
    assert list(raw['calls'])==[effect_ledger.legacy_call_id(attempt,'fixture')]
    assert state['usage']['calls']==1 and len(effect_ledger.receipts(root/'effects'))==1


def test_worker_receipt_closes_runner_crash_before_graph_effect_receipt(tmp_path,monkeypatch):
    import json,subprocess,sys
    monkeypatch.setenv('RAVEL_STATE_DIR',str(tmp_path/'state'))
    run=tmp_path/'run';run.mkdir();root=tmp_path/'graph';graph.create(root,plan(tmp_path))
    program=r'''
import os,sys
from pathlib import Path
from ravel.workflow import agent_graph as graph,agent_worker as worker,broker as _broker
def put(rundir,ws,rel,text):
 assert _broker.Broker(rundir,ws,node_id=ws.parent.name,attempt=int(ws.name),allowed_actions=['write'],max_calls=100000).call({'call_id':'put-'+_broker.digest([rel,text])[:24],'action':'write','args':{'path':rel,'content':text}})['status']=='ok'
class Host:
 identity={'fixture':'stable-worker-recovery'}
original=worker.dispatch
def dispatch(rundir,spec,**options):
 ws=worker.materialize(rundir,spec,**options)
 try:return worker.load_receipt(rundir,spec['node_id'],spec['attempt'])
 except ValueError:pass
 put(rundir,ws,'outputs/result.txt','result')
 (ws/'scratch/launches').write_text('one')
 receipt=worker.finish(rundir,spec,final={'completed':True},execution={'exit_status':0})
 if sys.argv[2]=='crash':os._exit(31)
 return receipt
worker.dispatch=dispatch
graph.execute(Path(sys.argv[1]),Host())
'''
    first=subprocess.run([sys.executable,'-B','-c',program,str(root),'crash'],timeout=10)
    assert first.returncode==31
    resumed=subprocess.run([sys.executable,'-B','-c',program,str(root),'resume'],timeout=10)
    assert resumed.returncode==0 and graph.status(root)['complete']
    assert graph.status(root)['usage']['calls']==1
    assert (run/'agent-work/worker/1/scratch/launches').read_text()=='one'


def test_delegation_uses_only_the_contract_api():
    import inspect
    source=inspect.getsource(graph)
    for superseded in ('effect_ledger.call(','effect_ledger.call_id(','_verified_result','domain_key=','carry_over='):
        assert superseded not in source


def test_external_delivery_closes_ledger_before_receipt_and_state(tmp_path,monkeypatch):
    from ravel.workflow import effect_ledger
    from test_agent_graph import role_packet, external_node, external_response, spec
    packet,_=role_packet(tmp_path/'verifier','verifier',{'covariance':[[1,0],[0,1]]})
    root=tmp_path/'graph';graph.create(root,spec([external_node(packet)],calls=1,tokens=256))
    prepared=graph.prepare_external(root,'verify')
    raw=graph.read_json(root/graph.STATE);call_id=next(iter(raw['calls']))
    assert graph._delegated(root,raw['graph_id'],call_id)['status']=='ambiguous'
    def refuse(*args,**kwargs):raise effect_ledger.agent_graph.GraphError('ledger refused')
    monkeypatch.setattr(effect_ledger,'deliver_external',refuse)
    response=external_response(prepared,tmp_path/'response.json')
    with pytest.raises(graph.GraphError,match='ledger refused'):graph.deliver_external(root,'verify',response)
    receipt=graph.read_json(root/'calls'/(call_id+'.json'));raw=graph.read_json(root/graph.STATE)
    assert receipt['status']!='completed' and raw['calls'][call_id]['status']=='ambiguous'
    monkeypatch.undo()
    assert graph.deliver_external(root,'verify',response)['complete']
    receipt=graph.read_json(root/'calls'/(call_id+'.json'));raw=graph.read_json(root/graph.STATE)
    effect=graph._delegated(root,raw['graph_id'],call_id)
    assert receipt['status']==raw['calls'][call_id]['status']==effect['status']=='completed'
    assert effect['result_sha256']==graph.digest(receipt['result'])


def test_typed_not_dispatched_failure_closes_its_effect_and_retries_on_new_attempt(tmp_path):
    from ravel.workflow import effect_ledger
    from test_agent_graph import Host, node, spec
    class Refused(effect_ledger.NotDispatched):
        retryable=True
    failures=[]
    def operation(item,request,control):
        if not failures:
            failures.append(1);raise Refused('transport closed before send')
        return {'public':item['id']}
    root=tmp_path/'graph';graph.create(root,spec([node('effect',attempts=2)]));host=Host(operation)
    state=graph.execute(root,host)
    assert state['complete'] and host.dispatched==['effect','effect']
    raw=graph.read_json(root/graph.STATE)
    statuses=sorted(graph._delegated(root,raw['graph_id'],c)['status'] for c in raw['calls'])
    assert statuses==['completed','failed']


def _effects(root):
    return graph.read_json(root/'counter.json')['n'] if (root/'counter.json').exists() else 0


@pytest.mark.parametrize('boundary',['host-after-commit','host-after-commit-retryable','ledger-outcome-write',
                                     'call-receipt-write','graph-state-save'])
def test_exception_after_a_possible_commit_is_ambiguous_and_never_redispatched(tmp_path,monkeypatch,boundary):
    """An injected exception at every boundary after dispatch began: one effect, no fresh retry."""
    from ravel.workflow import effect_ledger
    from test_agent_graph import Host, node, spec
    root=tmp_path/'graph';graph.create(root,spec([node('effect',attempts=3)]))
    class Lost(RuntimeError):
        retryable=boundary.endswith('retryable')
    armed=[True]
    def operation(item,request,control):
        graph.atomic_json(root/'counter.json',{'n':_effects(root)+1})
        if boundary.startswith('host') and armed[0]:
            armed[0]=False;raise Lost('response lost after commit')
        return {'public':item['id']}
    def once(target,name):
        original=getattr(target,name)
        def broken(*args,**kwargs):
            if armed[0] and (name!='atomic_json' or '/calls/' in str(args[0]) and args[1].get('status')=='completed') and (
                    name!='_save' or _effects(root)):
                if name!='_write_outcome' or args[1]['status']=='completed':
                    armed[0]=False;raise OSError('injected write failure')
            return original(*args,**kwargs)
        monkeypatch.setattr(target,name,broken)
    if boundary=='ledger-outcome-write':once(effect_ledger,'_write_outcome')
    if boundary=='call-receipt-write':once(graph,'atomic_json')
    if boundary=='graph-state-save':once(graph,'_save')
    host=Host(operation)
    state=graph.execute(root,host)
    assert not armed[0]  # the injected exception fired
    monkeypatch.undo()
    state=graph.execute(root,host);state=graph.execute(root,host)
    assert _effects(root)==1 and host.dispatched==['effect']
    assert not state['complete'] and state['nodes']['effect']['status']=='ambiguous'
    with pytest.raises(graph.GraphError,match='ambiguous'):graph.rework(root,['effect'],reason='hide the unknown effect')
    raw=graph.read_json(root/graph.STATE);(call_id,)=raw['calls']
    assert graph._delegated(root,raw['graph_id'],call_id)['status'] in {'ambiguous','started','completed'}


def test_failed_reconciliation_cannot_close_a_ledger_completed_effect(tmp_path,monkeypatch):
    from test_agent_graph import Host, node, spec
    root=tmp_path/'graph';graph.create(root,spec([node('effect',attempts=3)]))
    original=graph.atomic_json
    def broken(path,value):
        if '/calls/' in str(path) and value.get('status')=='completed':raise OSError('injected')
        return original(path,value)
    monkeypatch.setattr(graph,'atomic_json',broken)
    graph.execute(root,Host());monkeypatch.undo()
    raw=graph.read_json(root/graph.STATE);(call_id,)=raw['calls']
    assert graph._delegated(root,raw['graph_id'],call_id)['status']=='completed'
    evidence=tmp_path/'operator-note.json';evidence.write_text('{"claim":"never sent"}')
    from test_agent_graph import pin
    with pytest.raises(graph.GraphError,match='completed'):
        graph.reconcile(root,call_id,outcome='failed',evidence=[pin(evidence)],reason='claimed failure')
    assert graph.status(root)['nodes']['effect']['status']=='ambiguous'


def test_runner_crash_before_materialize_dispatches_exactly_once(tmp_path,monkeypatch):
    import subprocess,sys
    from ravel.workflow import agent_worker as worker
    monkeypatch.setenv('RAVEL_STATE_DIR',str(tmp_path/'state'))
    run=tmp_path/'run';run.mkdir();root=tmp_path/'graph';graph.create(root,plan(tmp_path))
    program=r'''
import os,sys
from pathlib import Path
from ravel.workflow import agent_graph as graph,agent_worker as worker,broker as _broker
def put(rundir,ws,rel,text):
 assert _broker.Broker(rundir,ws,node_id=ws.parent.name,attempt=int(ws.name),allowed_actions=['write'],max_calls=100000).call({'call_id':'put-'+_broker.digest([rel,text])[:24],'action':'write','args':{'path':rel,'content':text}})['status']=='ok'
class Host:
 identity={'fixture':'stable-worker-recovery'}
def dispatch(rundir,spec,**options):
 if sys.argv[2]=='crash':os._exit(32)
 ws=worker.materialize(rundir,spec,**options)
 put(rundir,ws,'outputs/result.txt','result')
 log=Path(sys.argv[1]).parent/'launches';log.write_text(log.read_text()+'x' if log.exists() else 'x')
 return worker.finish(rundir,spec,final={'completed':True},execution={'exit_status':0})
worker.dispatch=dispatch
graph.execute(Path(sys.argv[1]),Host());graph.execute(Path(sys.argv[1]),Host())
'''
    assert subprocess.run([sys.executable,'-B','-c',program,str(root),'crash'],timeout=20).returncode==32
    assert subprocess.run([sys.executable,'-B','-c',program,str(root),'resume'],timeout=20).returncode==0
    state=graph.status(root)
    assert state['complete'] and (tmp_path/'launches').read_text()=='x'
    assert not worker.dispatched(run,'worker',1) and worker.load_receipt(run,'worker',2)['status']=='ok'
    raw=graph.read_json(root/graph.STATE)
    statuses=sorted(graph._delegated(root,raw['graph_id'],c)['status'] for c in raw['calls'])
    assert statuses==['completed','reconciled']


def test_never_dispatched_reservation_recovers_on_a_single_attempt_node(tmp_path,monkeypatch):
    import subprocess,sys
    from ravel.workflow import agent_worker as worker
    monkeypatch.setenv('RAVEL_STATE_DIR',str(tmp_path/'state'))
    run=tmp_path/'run';run.mkdir();root=tmp_path/'graph'
    single=plan(tmp_path);single['nodes'][0]['max_attempts']=1;graph.create(root,single)
    program=r'''
import os,sys
from pathlib import Path
from ravel.workflow import agent_graph as graph,agent_worker as worker,broker as _broker
def put(rundir,ws,rel,text):
 assert _broker.Broker(rundir,ws,node_id=ws.parent.name,attempt=int(ws.name),allowed_actions=['write'],max_calls=100000).call({'call_id':'put-'+_broker.digest([rel,text])[:24],'action':'write','args':{'path':rel,'content':text}})['status']=='ok'
class Host:
 identity={'fixture':'stable-worker-recovery'}
def dispatch(rundir,spec,**options):
 if sys.argv[2]=='crash':os._exit(32)
 ws=worker.materialize(rundir,spec,**options)
 put(rundir,ws,'outputs/result.txt','result')
 return worker.finish(rundir,spec,final={'completed':True},execution={'exit_status':0})
worker.dispatch=dispatch
graph.execute(Path(sys.argv[1]),Host())
'''
    assert subprocess.run([sys.executable,'-B','-c',program,str(root),'crash'],timeout=20).returncode==32
    assert subprocess.run([sys.executable,'-B','-c',program,str(root),'resume'],timeout=20).returncode==0
    state=graph.status(root)
    assert state['complete'] and state['usage']['calls']==1
    assert state['nodes']['dispatch']['generation_attempts']==1


def test_released_external_reservation_closes_its_ledger_effect(tmp_path):
    from test_agent_graph import role_packet, external_node, spec
    packet,_=role_packet(tmp_path/'verifier','verifier',{'covariance':[[1,0],[0,1]]})
    root=tmp_path/'graph';graph.create(root,spec([external_node(packet)],calls=2,tokens=512))
    graph.prepare_external(root,'verify')
    raw=graph.read_json(root/graph.STATE);call_id=next(iter(raw['calls']))
    graph.release_external(root,'verify',reason='host lost the response')
    assert graph._delegated(root,raw['graph_id'],call_id)['status']=='failed'


def blind_plan(tmp_path,packet,kind='agent'):
    from test_agent_worker import blind_spec
    p=plan(tmp_path,kind)
    n=p['nodes'][0];n['role']='verifier';n['packet']=packet
    if kind=='agent':n['parameters']['spec']=blind_spec()
    else:n['parameters']['spec']['spec']=blind_spec()
    return p


def test_blind_worker_nodes_require_a_packet_matching_role_card_and_no_raw_inputs(tmp_path):
    from test_agent_worker import blind_packet
    packet=blind_packet(tmp_path)
    assert graph.validate(blind_plan(tmp_path,packet))['nodes'][0]['role']=='verifier'
    assert graph.validate(blind_plan(tmp_path,packet,'map'))
    raw={'pin':{'path':'x','sha256':'0'*64},'as':'inputs/x'}
    variants=[]
    p=blind_plan(tmp_path,None);variants.append(p)
    p=blind_plan(tmp_path,packet);p['nodes'][0]['parameters']['spec']['role']['id']='executor';variants.append(p)
    p=blind_plan(tmp_path,packet);p['nodes'][0]['parameters']['spec']['inputs']=[raw];variants.append(p)
    p=blind_plan(tmp_path,packet);p['nodes'][0]['parameters']['spec']['work_order']=raw['pin'];variants.append(p)
    p=blind_plan(tmp_path,packet,'map');p['nodes'][0]['parameters']['spec']['items'][0]['inputs']=[raw];variants.append(p)
    for variant in variants:
        with pytest.raises(graph.GraphError,match='blind worker'):graph.validate(variant)


def test_blind_worker_dispatch_materializes_only_the_packet_and_protects_the_graph_root(tmp_path,monkeypatch):
    from ravel.workflow import agent_worker as worker
    from test_agent_graph import Host
    from test_agent_worker import blind_packet
    monkeypatch.setenv('RAVEL_STATE_DIR',str(tmp_path/'state'));(tmp_path/'run').mkdir()
    seen={}
    def dispatch(rundir,spec,**options):
        seen.update(options)
        ws=worker.materialize(rundir,spec,graph=options['graph'],framework_step=options['framework_step'],
                              packet=options['packet'],protected=options['protected'])
        put(rundir,ws,'outputs/result.txt','disposition')
        return worker.finish(rundir,spec,final={'completed':True},execution={'exit_status':0})
    monkeypatch.setattr(worker,'dispatch',dispatch)
    root=tmp_path/'graph';graph.create(root,blind_plan(tmp_path,blind_packet(tmp_path)))
    assert graph.execute(root,Host())['complete']
    assert seen['protected']==[str(root.resolve())] or seen['protected']==[str(root)]
    ws=worker.workspace(tmp_path/'run','review',1)
    assert sorted(p.relative_to(ws).as_posix() for p in (ws/'inputs').rglob('*') if p.is_file())==[
        'inputs/packet/artifacts/evidence.json','inputs/packet/manifest.json']
    targets=worker._denied_probe_targets(tmp_path/'run',worker._record_path(tmp_path/'run','review',1),
                                         worker._record(tmp_path/'run','review',1))
    assert any(t.name==graph.STATE for t in targets) and any('framework' in t.parts for t in targets)


def test_quorum_map_node_completes_when_its_quorum_is_met(tmp_path,monkeypatch):
    from ravel.workflow import agent_worker as worker
    from test_agent_graph import Host
    monkeypatch.setenv('RAVEL_STATE_DIR',str(tmp_path/'state'));(tmp_path/'run').mkdir()
    def dispatch(rundir,spec,**options):
        ws=worker.materialize(rundir,spec,graph=options['graph'],framework_step=options['framework_step'])
        if not spec['node_id'].endswith('.b'):put(rundir,ws,'outputs/result.txt','r')
        return worker.finish(rundir,spec,final={'completed':True},execution={'exit_status':0})
    monkeypatch.setattr(worker,'dispatch',dispatch)
    p=plan(tmp_path,'map');p['nodes'][0]['parameters']['spec']['join']='quorum:2'
    root=tmp_path/'graph';graph.create(root,p)
    assert graph.execute(root,Host())['complete']
    p=plan(tmp_path/'all','map');(tmp_path/'all').mkdir();(tmp_path/'all'/'run').mkdir()
    root=tmp_path/'graph-all';graph.create(root,p)
    state=graph.execute(root,Host())
    assert not state['complete'] and state['nodes']['dispatch']['status']=='failed'


def test_worker_receipt_carries_effect_identity_and_closes_a_crashed_effect_through_its_validator(tmp_path,monkeypatch):
    from ravel.workflow import agent_worker as worker, effect_ledger, graph_nodes
    monkeypatch.setenv('RAVEL_STATE_DIR',str(tmp_path/'state'));run=tmp_path/'run';run.mkdir()
    scope=tmp_path/'scope';effect_ledger._scope(scope)
    launches=[]
    def dispatch(rundir,spec,**options):
        launches.append(spec['attempt'])
        ws=worker.materialize(rundir,spec,graph=options['graph'],framework_step=options['framework_step'],
                              protected=options['protected'],effect=options['effect'])
        put(rundir,ws,'outputs/result.txt','result')
        receipt=worker.finish(rundir,spec,final={'completed':True},execution={'exit_status':0})
        if len(launches)==1:raise RuntimeError('runner lost after the worker receipt')
        return receipt
    monkeypatch.setattr(worker,'dispatch',dispatch)
    node=graph_nodes.agent('review',rundir=run,spec=lambda state:worker_spec(),segment=lambda state:{'agent':'review'},
                           to_state=lambda state,result:{'receipt':result['status']})
    assert node.kind=='effect'
    state={'meta':{'graph_id':'worker-node','version':0,'instance':{},'scope_root':str(scope)}}
    with pytest.raises(effect_ledger.Ambiguous):node.function(state)
    receipt=worker.load_receipt(run,'worker',1)
    (saved,)=effect_ledger.receipts(scope)
    assert receipt['identity_sha256']==saved['identity_sha256'] and saved['status']=='ambiguous'
    assert receipt['epoch']=={'cancellation':saved['epoch']['cancellation']}
    assert node.function(state)['receipt']=='ok' and launches==[1]
    (closed,)=effect_ledger.receipts(scope)
    assert closed['status']=='completed' and closed['reconciliation']['auto'] is True
    assert closed['result_sha256']==effect_ledger.digest(receipt)


def test_legacy_execution_holds_the_scope_runner_and_honours_stop(tmp_path):
    from ravel.workflow import effect_ledger, graph_substrate
    from test_agent_graph import Host, node, spec
    root=tmp_path/'graph';graph.create(root,spec([node('one'),node('two',['one'])]));host=Host()
    graph_substrate.stop(root/'effects',reason='drain before dispatch')
    state=graph.execute(root,host)
    assert host.dispatched==[] and not state['complete'] and state['usage']['calls']==0
    with graph_substrate.scope_runner(effect_ledger._scope(root/'effects'),'other','thread'):
        with pytest.raises(graph_substrate.ScopeLocked):graph.execute(root,host,clear_stop=True)
    assert host.dispatched==[]
    state=graph.execute(root,host,clear_stop=True)
    assert state['complete'] and host.dispatched==['one','two']
    raw=graph.read_json(root/graph.STATE)
    assert all(graph._delegated(root,raw['graph_id'],c)['epoch']['runner']>=1 for c in raw['calls'])


def test_stop_during_a_node_drains_its_successors_and_resume_reuses_the_receipt(tmp_path):
    from ravel.workflow import graph_substrate
    from test_agent_graph import Host, node, spec
    root=tmp_path/'graph';graph.create(root,spec([node('one'),node('two',['one'])]))
    def operation(item,request,control):
        if item['id']=='one':graph_substrate.stop(root/'effects',reason='drain mid-run')
        return {'public':item['id']}
    host=Host(operation)
    state=graph.execute(root,host)
    assert host.dispatched==['one'] and state['nodes']['two']['status']=='pending'
    state=graph.execute(root,host,clear_stop=True)
    assert state['complete'] and host.dispatched==['one','two'] and state['usage']['calls']==2
