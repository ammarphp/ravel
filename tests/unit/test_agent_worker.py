"""Worker lifecycle controls using inert Python children only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest


def spec(name='worker',attempt=1):
    return {'schema_version':1,'kind':'agent-worker-spec','node_id':name,'attempt':attempt,
        'role':{'id':'executor','version':'1','card_sha256':'1'*64},
        'transport_preference':['stub'], 'inputs':[],
        'declared_outputs':[{'path':'outputs/result.txt','kind':'text','required':True}],
        'budgets':{'max_turns':5,'max_wall_seconds':20,'max_broker_calls':20,'max_cost_usd':None},
        'final_record_schema':'producer.v1','work_order':None,'rdj_challenges':None,
        'parent':{'review_point_id':None,'map_id':None,'rca_ticket':None}}


def setup(tmp_path,monkeypatch):
    from ravel.workflow import agent_worker as worker
    monkeypatch.setenv('RAVEL_STATE_DIR',str(tmp_path/'state'))
    run=tmp_path/'run';run.mkdir(exist_ok=True)
    return worker,run


def result():
    return {'completed':True,'findings':[{'status':'ok','strict':True,'label_source':'model'}]}


def put(run, ws, rel, text):
    """Write a worker output through its broker: only a broker output pin credits an output."""
    from ravel.workflow import broker
    tool=broker.Broker(run,ws,node_id=ws.parent.name,attempt=int(ws.name),allowed_actions=['write'],max_calls=100000)
    reply=tool.call({'call_id':'put-'+hashlib.sha256((rel+'\0'+text).encode()).hexdigest()[:24],'action':'write',
                     'args':{'path':rel,'content':text}})
    assert reply['status']=='ok',reply


def test_model_findings_cannot_populate_outcome_or_checks(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch)
    ws=worker.materialize(run,spec())
    r=worker.finish(run,spec(),final=result(),execution={'exit_status':0})
    assert r['outcome']['label_source']=='computed'
    assert r['outcome']['strict'] is False and r['status']=='failed'
    assert r['outcome']['computed_checks']['declared_outputs'] is False
    assert 'findings' not in r['outcome']
    assert r['completion_claimed_without_receipts'] is True
    assert worker.completion_cells(run)[0]['completion_claimed_without_receipts']==1


@pytest.mark.parametrize('transport',['claude','codex','gemini','opencode','ravel-loop'])
def test_all_stub_transports_have_same_receipt_schema(tmp_path,monkeypatch,transport):
    worker,run=setup(tmp_path,monkeypatch)
    s=spec();ws=worker.materialize(run,s);put(run,ws,'outputs/result.txt','output')
    r=worker.finish(run,s,final=result(),execution={'exit_status':0,'transport':{'id':transport,'transport_kind':'stub'}})
    assert r['status']=='ok' and r['outcome']['strict']
    assert set(r)==worker.RECEIPT_FIELDS
    assert r['graph'] is None and r['framework_step'] is None
    assert r['recovery'] is None


def test_missing_final_and_output_outside_outputs_not_credited(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch)
    bad=spec();bad['declared_outputs'][0]['path']='scratch/result.txt'
    with pytest.raises(ValueError):worker.materialize(run,bad)
    s=spec();ws=worker.materialize(run,s);(ws/'outputs/result.txt').symlink_to(run/'outside')
    r=worker.finish(run,s,final={},execution={'exit_status':0})
    assert r['credited_outputs']==[] and r['status']=='failed'


def test_workspace_lives_outside_run_tree_and_receipt_is_published(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch)
    s=spec();ws=worker.materialize(run,s)
    assert not ws.is_relative_to(run) and not run.is_relative_to(ws)
    put(run,ws,'outputs/result.txt','output')
    r=worker.finish(run,s,final=result(),execution={'exit_status':0})
    assert r['status']=='ok' and r['transcript']['path']=='agent-work/worker/1/transcript.jsonl'
    published=run/'agent-work/worker/1'
    assert (published/'receipt.json').read_bytes()==(ws/'receipt.json').read_bytes()
    assert (published/'outputs/result.txt').read_text()=='output'
    assert worker.load_receipt(run,'worker',1)==r and worker.status(run)['workers']==[r]
    monkeypatch.setenv('RAVEL_WORK_ROOT',str(run/'work'))
    with pytest.raises(ValueError,match='outside the run tree'):worker.materialize(run,spec(attempt=2))


def test_ledger_and_graph_root_writes_never_void_a_running_worker(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch)
    (run/'science.txt').write_text('protected input')
    s=spec();ws=worker.materialize(run,s);put(run,ws,'outputs/result.txt','output')
    for rel in ('calls/1.json','calls/index/a.json','framework/epoch.json','effects/calls/2.json',
                'graphs/review/graph_state.json','graphs/review/calls/3.json','graphs/review/attempts/a.json',
                'nested/scope/framework/scope.json','nested/scope/calls/4.json','nested/scope/agent-work/processes.json'):
        (run/rel).parent.mkdir(parents=True,exist_ok=True);(run/rel).write_text('{}')
    r=worker.finish(run,s,final=result(),execution={'exit_status':0})
    assert r['status']=='ok' and r['run_tree']['modified'] is False
    from ravel.workflow import broker
    s2=spec(attempt=2);s2['inputs']=[{'pin':{'path':'science.txt','sha256':broker.sha(run/'science.txt')},'as':'inputs/science.txt'}]
    ws=worker.materialize(run,s2);put(run,ws,'outputs/result.txt','output')
    (run/'unrelated-science.txt').write_text('another analysis wrote this')
    s3=spec(attempt=3);ws3=worker.materialize(run,s3);put(run,ws3,'outputs/result.txt','output')
    (run/'science.txt').write_text('changed input')
    assert worker.finish(run,s2,final=result(),execution={'exit_status':0})['status']=='voided'
    assert worker.finish(run,s3,final=result(),execution={'exit_status':0})['status']=='ok'


def test_run_tree_modified_is_voided_with_finding(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch)
    from ravel.workflow import broker
    (run/'control.json').write_text('declared')
    s=spec();s['inputs']=[{'pin':{'path':'control.json','sha256':broker.sha(run/'control.json')},'as':'inputs/control.json'}]
    ws=worker.materialize(run,s)
    (run/'control.json').write_text('changed')
    put(run,ws,'outputs/result.txt','result')
    r=worker.finish(run,s,final=result(),execution={'exit_status':0})
    assert r['status']=='voided' and r['failure']['code']=='run_modified'
    assert r['credited_outputs']==[]
    assert worker.findings(run)[0]['code']=='run_modified'


def test_failed_then_pass_same_node_has_verified_recovery_marker(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch)
    s=spec();worker.materialize(run,s);failed=worker.finish(run,s,final=result(),execution={'exit_status':1})
    s=spec(attempt=2);ws=worker.materialize(run,s);put(run,ws,'outputs/result.txt','output')
    passed=worker.finish(run,s,final=result(),execution={'exit_status':0})
    assert passed['recovery']['attempt']==1 and passed['recovery']['node_id']=='worker'
    assert passed['recovery']['receipt_sha256']==hashlib.sha256((run/'agent-work/worker/1/receipt.json').read_bytes()).hexdigest()


def test_killed_worker_requires_explicit_reconcile(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch);s=spec();worker.materialize(run,s)
    r=worker.finish(run,s,final=None,execution={'exit_status':-9})
    assert r['status']=='ambiguous'
    assert worker.dispatch(run,s)['status']=='ambiguous'
    with pytest.raises(ValueError):worker.reconcile(run,'worker',1)
    evidence=run/'evidence.txt';evidence.write_text('inert child was reaped')
    r=worker.reconcile(run,'worker',1,evidence={'path':'evidence.txt','sha256':hashlib.sha256(evidence.read_bytes()).hexdigest()},reason='Verified inert child ended.')
    assert r['status']=='failed' and r['outcome']['label_source']=='computed'


def test_rdj_binding_and_write_log_use_verified_outputs(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch);s=spec();s['rdj_challenges']={'case_id':'case','slot':'critic','payload_sha256':'a'*64}
    ws=worker.materialize(run,s);put(run,ws,'outputs/result.txt','result')
    r=worker.finish(run,s,final=result(),execution={'exit_status':0,'session_id':'session'})
    assert r['rdj']==s['rdj_challenges']
    writes=[json.loads(x) for x in (run/'agent-audit/writes.jsonl').read_text().splitlines()]
    assert set(writes[0])=={'path','sha256','session_id','utc'}
    assert writes[0]['sha256']==r['credited_outputs'][0]['sha256']
    row=json.loads((ws/'transcript.jsonl').read_text().splitlines()[0])
    assert row['stream']=='worker/1' and row['ravel']['receipt_sha256']


def test_unavailable_sandbox_refuses_before_launch(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch)
    from ravel.workflow import sandbox
    monkeypatch.setattr(sandbox,'available',lambda:None)
    r=worker.dispatch(run,spec(),launch_spec={'argv':['/bin/sleep','1']})
    assert r['status']=='refused' and r['failure']['code']=='sandbox_unavailable'
    assert worker.processes(run)==[]


def test_map_retry_only_failed_item_and_join_sorted(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch)
    calls=[]
    def dispatch(rundir,s,**kwargs):
        calls.append(s['node_id']);ws=worker.materialize(rundir,s)
        if s['node_id']!='group.b' or s['attempt']>1:put(run,ws,'outputs/result.txt',s['node_id'])
        return worker.finish(rundir,s,final=result(),execution={'exit_status':0})
    monkeypatch.setattr(worker,'dispatch',dispatch)
    m={'schema_version':1,'kind':'agent-map','id':'group','spec':spec(),
        'items':[{'key':k,'inputs':[]} for k in ('c','a','b')],'join':'all'}
    first=worker.dispatch_map(run,m);second=worker.dispatch_map(run,m)
    assert calls==['group.a','group.b','group.c','group.b']
    assert [r['node_id'] for r in second]==['group.a','group.b','group.c']
    assert worker.join_digest(second)==worker.join_digest(list(reversed(second)))
    assert first[1]['status']=='failed' and second[1]['status']=='ok'


def test_runner_kill_reattaches_to_one_inert_child(tmp_path,monkeypatch):
    """Process lifecycle proof, with explicit inert confinement/IPC seams.

    Actual OS confinement and socket IPC are a separate reviewer qualification.
    """
    worker,run=setup(tmp_path,monkeypatch)
    s=spec();s['budgets']['max_wall_seconds']=10
    # The inert IPC seam has no broker socket, so the output is optional: this test is the lifecycle.
    s['declared_outputs'][0]['required']=False
    ws=worker.materialize(run,s)
    child_code='''import pathlib,time,json
p=pathlib.Path('scratch/launches');p.write_text(p.read_text()+'x' if p.exists() else 'x')
end=time.monotonic()+8
while not pathlib.Path('scratch/release').exists() and time.monotonic()<end:time.sleep(.02)
pathlib.Path('outputs/result.txt').write_text('result')
print(json.dumps({'completed':True}))
'''
    supervisor_patch='''
import contextlib,socketserver
from ravel.workflow import agent_worker as w,sandbox,broker
class InertServer:
 def __init__(self,*a,**k):pass
 def serve_forever(self):pass
 def shutdown(self):pass
 def server_close(self):pass
socketserver.ThreadingUnixStreamServer=InertServer
w.os.chmod=lambda *a:None
sandbox.available=lambda:'inert-test-seam'
sandbox.probe=lambda *a,**k:{'backend':'inert-test-seam','confirmed':False,'scope':'lifecycle only'}
sandbox.command=lambda ws,argv,**k:argv
broker.serve=lambda b:contextlib.nullcontext()
'''
    parent_code='''import json,pathlib,subprocess,sys,time
from ravel.workflow import agent_worker as w,sandbox
sandbox.available=lambda:'inert-test-seam'
original=w.subprocess.Popen
patch=PATCH
# Only the supervisor command is replaced; its child uses real Popen.
def start(argv,**kwargs):
 if '-m' in argv and 'ravel.workflow.agent_worker' in argv:
  i=argv.index('--rundir');run=argv[i+1];node=argv[argv.index('--node')+1];attempt=int(argv[argv.index('--attempt')+1])
  body=patch+'\\nw.supervise(pathlib.Path('+repr(run)+'),'+repr(node)+','+str(attempt)+')'
  return original([sys.executable,'-B','-c','import pathlib\\n'+body],**kwargs)
 return original(argv,**kwargs)
w.subprocess.Popen=start
run=pathlib.Path(sys.argv[1]);spec=json.loads(sys.argv[2]);desc=json.loads(sys.argv[3])
w.dispatch(run,spec,launch_spec=desc,wait=False)
pathlib.Path(sys.argv[4]).write_text('attached')
if sys.argv[5]=='first':time.sleep(15)
'''.replace('PATCH',repr(supervisor_patch))
    descriptor={'argv':[sys.executable,'-B','-c',child_code],
                'transport':{'id':'inert-stub','transport_kind':'stub'}}
    marker=tmp_path/'started'
    first=subprocess.Popen([sys.executable,'-B','-c',parent_code,str(run),json.dumps(s),json.dumps(descriptor),str(marker),'first'],start_new_session=True)
    try:
        end=time.monotonic()+6
        # The child creates then writes the marker; wait for its content, not its existence.
        while not ((ws/'scratch/launches').exists() and (ws/'scratch/launches').read_text()) and time.monotonic()<end:
            if first.poll() is not None:break
            time.sleep(.02)
        assert marker.exists() and (ws/'scratch/launches').read_text()=='x'
        first.kill();first.wait(timeout=5)
        second=subprocess.run([sys.executable,'-B','-c',parent_code,str(run),json.dumps(s),json.dumps(descriptor),str(tmp_path/'reattached'),'second'],timeout=5)
        assert second.returncode==0 and (ws/'scratch/launches').read_text()=='x'
        (ws/'scratch/release').write_text('finish inert child')
        end=time.monotonic()+8
        # receipt.json lands before its custody pin; wait for the pin, not the file.
        while not worker._record(run,'worker',1)['receipt'] and time.monotonic()<end:time.sleep(.02)
        r=worker.load_receipt(run,'worker',1)
        assert r['status']=='ok' and r['isolation']['evidence']['confirmed'] is False
        assert (ws/'scratch/launches').read_text()=='x'
        end=time.monotonic()+3
        while any(p['status']!='finished' for p in worker.processes(run)) and time.monotonic()<end:time.sleep(.02)
        assert all(p['verified_gone'] for p in worker.processes(run))
    finally:
        (ws/'scratch/release').write_text('test cleanup')
        if first.poll() is None:first.terminate();first.wait(timeout=5)


def test_actual_sandbox_denial_probe_or_explicit_sandbox_block(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch);ws=worker.materialize(run,spec())
    from ravel.workflow import sandbox
    forbidden=run/'private';forbidden.write_text('protected')
    try:
        evidence=sandbox.probe(ws,forbidden=forbidden,read_paths=sandbox.runtime_paths([sys.executable]))
    except sandbox.SandboxUnavailable:
        pytest.skip('sandbox-blocked: actual OS denial probes unavailable here; reviewer must run')
    assert evidence['confirmed'] and all(evidence['computed_checks'].values())


def test_credited_output_change_cannot_reuse_successful_receipt(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch);s=spec();ws=worker.materialize(run,s)
    put(run,ws,'outputs/result.txt','original')
    worker.finish(run,s,final=result(),execution={'exit_status':0})
    put(run,ws,'outputs/result.txt','changed')
    with pytest.raises(ValueError,match='credited output'):worker.load_receipt(run,'worker',1)


def test_map_cannot_reuse_a_changed_specification(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch)
    def dispatch(rundir,s,**options):
        ws=worker.materialize(rundir,s);put(rundir,ws,'outputs/result.txt','result')
        return worker.finish(rundir,s,final=result(),execution={'exit_status':0})
    monkeypatch.setattr(worker,'dispatch',dispatch)
    m={'schema_version':1,'kind':'agent-map','id':'group','spec':spec(),
        'items':[{'key':'a','inputs':[]}],'join':'all'}
    worker.dispatch_map(run,m)
    m['spec']['role']['card_sha256']='b'*64
    with pytest.raises(ValueError,match='changed'):worker.dispatch_map(run,m)


def test_work_cli_status_refusal_is_explicit(tmp_path,monkeypatch,capsys):
    worker,run=setup(tmp_path,monkeypatch)
    assert worker.main(['status','--rundir',str(run)])==0
    assert json.loads(capsys.readouterr().out)['workers']==[]
    assert worker.main(['stop','--rundir',str(run)])==0
    assert json.loads(capsys.readouterr().out)['verified_gone'] is True


def test_supervisor_ipc_denial_is_receipted_before_any_child(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch);s=spec();worker.materialize(run,s)
    from ravel.workflow import broker
    from ravel.workflow.state_io import atomic_json,read_json
    descriptor=broker.custody(run)/(worker._key('worker',1)+'.launch.json')
    atomic_json(descriptor,{'argv':['/bin/sleep','1']})
    path=worker._record_path(run,'worker',1);record=read_json(path)
    record['launch']={'token':'nonce','descriptor_sha256':broker.sha(descriptor),'pid':None,'control_socket':None,'status':'reserved'}
    atomic_json(path,record)
    def denied(*args,**kwargs):raise PermissionError('inert IPC denial')
    monkeypatch.setattr(worker.socketserver,'ThreadingUnixStreamServer',denied)
    worker.supervise(run,'worker',1)
    receipt=worker.load_receipt(run,'worker',1)
    assert receipt['status']=='refused' and receipt['failure']['code']=='ipc_unavailable'
    assert all(p['verified_gone'] and p['child_pgid'] is None for p in worker.processes(run))


def _real_sandbox_or_skip(tmp_path):
    from ravel.workflow import sandbox
    ws=tmp_path/'qualify';[(ws/n).mkdir(parents=True) for n in ('inputs','outputs','scratch')]
    (tmp_path/'private').write_text('protected')
    try:sandbox.probe(ws,forbidden=tmp_path/'private',read_paths=sandbox.runtime_paths([sys.executable]))
    except sandbox.SandboxUnavailable:pytest.skip('sandbox-blocked: actual OS confinement unavailable here')


BROKER_CHILD='''import json,os,socket,pathlib,time
def call(req):
  s=socket.socket(socket.AF_UNIX);s.connect(os.environ["RAVEL_BROKER_SOCKET"]);s.sendall((json.dumps(req)+"\\n").encode())
  return json.loads(s.makefile("rb").readline())
r=call({"call_id":"r1","action":"read","args":{"path":"inputs/data.txt"}})
call({"call_id":"w1","action":"write","args":{"path":"outputs/result.txt","content":r["stdout_tail"].upper()}})
x=call({"call_id":"x1","action":"shell","args":{"cmd":"id"}})
probes={}
for name,p in [("run",RUNFILE),("calls","calls/1.json")]:
  try:open(p).read();probes[name]="read"
  except PermissionError:probes[name]="denied"
try:open("calls/forged.json","w").write("{}");probes["forge"]="wrote"
except PermissionError:probes["forge"]="denied"
pathlib.Path("outputs/probes.json").write_text(json.dumps(probes))
print(json.dumps({"completed":True,"unregistered":x["error"]["code"]}))
'''


def test_real_sandboxed_worker_uses_socket_broker_and_cannot_forge_receipts(tmp_path,monkeypatch):
    _real_sandbox_or_skip(tmp_path)
    worker,run=setup(tmp_path,monkeypatch)
    from ravel.workflow import broker
    (run/'data.txt').write_text('payload')
    s=spec();s['inputs']=[{'pin':{'path':'data.txt','sha256':broker.sha(run/'data.txt')},'as':'inputs/data.txt'}]
    child=BROKER_CHILD.replace('RUNFILE',repr(str(run/'data.txt')))
    r=worker.dispatch(run,s,launch_spec={'argv':[sys.executable,'-B','-c',child],
                                         'transport':{'id':'inert-stub','transport_kind':'stub'}})
    ws=worker.workspace(run,'worker',1)
    assert r['status']=='ok' and r['isolation']['evidence']['confirmed'] is True
    assert json.loads((ws/'outputs/probes.json').read_text())=={'run':'denied','calls':'denied','forge':'denied'}
    assert (ws/'outputs/result.txt').read_text()=='PAYLOAD' and not (ws/'calls/forged.json').exists()
    assert json.loads((ws/'final.json').read_text())['unregistered']=='not_allowlisted'
    receipts=broker.Broker(run,ws,node_id='worker',attempt=1,allowed_actions=[],max_calls=0).verify_ledger()
    assert [x['action'] for x in receipts]==['read','write','shell'] and receipts[2]['status']=='refused'
    assert r['broker']['calls']==3 and all(p['verified_gone'] for p in worker.processes(run))
    public=json.loads((run/'agent-work/processes.json').read_text())
    assert public['processes'] and not any('token' in p for p in public['processes'])


def test_real_stop_reaches_supervisor_and_verifies_child_gone(tmp_path,monkeypatch):
    _real_sandbox_or_skip(tmp_path)
    worker,run=setup(tmp_path,monkeypatch)
    s=spec();s['budgets']['max_wall_seconds']=30
    child="import time,pathlib\npathlib.Path('scratch/up').write_text('1')\ntime.sleep(25)\n"
    worker.dispatch(run,s,launch_spec={'argv':[sys.executable,'-B','-c',child],
                                       'transport':{'id':'inert-stub','transport_kind':'stub'}},wait=False)
    ws=worker.workspace(run,'worker',1);end=time.monotonic()+10
    while not (ws/'scratch/up').exists() and time.monotonic()<end:time.sleep(.05)
    assert (ws/'scratch/up').exists()
    result=worker.stop(run)
    assert result['verified_gone'] is True and len(result['stopped'])==1
    receipt=worker.load_receipt(run,'worker',1)
    assert receipt['status']=='ambiguous' and receipt['credited_outputs']==[]


def test_kernel_stop_now_terminates_sandboxed_child_and_leaves_receipt(tmp_path,monkeypatch):
    _real_sandbox_or_skip(tmp_path)
    import os
    from ravel.workflow import graph_substrate
    worker,run=setup(tmp_path,monkeypatch)
    s=spec();s['budgets']['max_wall_seconds']=30
    child="import time,pathlib\npathlib.Path('scratch/up').write_text('1')\ntime.sleep(25)\n"
    worker.dispatch(run,s,launch_spec={'argv':[sys.executable,'-B','-c',child],
                                       'transport':{'id':'inert-stub','transport_kind':'stub'}},wait=False)
    ws=worker.workspace(run,'worker',1);end=time.monotonic()+10
    while not (ws/'scratch/up').exists() and time.monotonic()<end:time.sleep(.05)
    entry=next(p for p in json.loads((run/'agent-work/processes.json').read_text())['processes']
               if p['id']=='worker-supervisor:worker/1')
    assert entry['child_pgid'] and entry['child_pid']==entry['child_pgid']
    result=graph_substrate.stop(run,reason='inert stop control',now=True)
    assert result['all_gone'] and result['terminated'][0]['child_pgid']==entry['child_pgid']
    with pytest.raises(ProcessLookupError):os.killpg(entry['child_pgid'],0)
    receipt=worker.load_receipt(run,'worker',1)
    assert receipt['status']=='ambiguous' and receipt['credited_outputs']==[]
    custody=next(p for p in worker.processes(run) if p['node_id']=='worker')
    assert custody['verified_gone'] is True and custody['child_pgid']==entry['child_pgid']
    termination=custody['termination']
    assert termination['gone'] is True and 'SIGTERM' in (*termination['signals'],termination.get('observed_exit_signal'))


def test_untyped_parent_is_refused_before_materialization(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch)
    for parent in (None,'review-1',{'review_point_id':None}):
        s=spec();s['parent']=parent
        with pytest.raises(ValueError):worker.materialize(run,s)
    assert not (run/'agent-work').exists()


@pytest.mark.parametrize('window',['before-publication','mid-publication'])
def test_interrupted_publication_is_repaired_before_a_receipt_is_returned(tmp_path,monkeypatch,window):
    worker,run=setup(tmp_path,monkeypatch)
    s=spec();ws=worker.materialize(run,s);put(run,ws,'outputs/result.txt','output')
    put(run,ws,'outputs/second.txt','second')
    original=worker._publish
    def crash(run_,ws_,node_id,attempt):
        if window=='mid-publication':  # one torn projection file, then the crash
            torn=run_/'agent-work'/node_id/str(attempt)/'receipt.json'
            torn.parent.mkdir(parents=True,exist_ok=True);torn.write_text('{')
        raise OSError('crash during publication')
    monkeypatch.setattr(worker,'_publish',crash)
    with pytest.raises(OSError):worker.finish(run,s,final=result(),execution={'exit_status':0})
    monkeypatch.setattr(worker,'_publish',original)
    published=run/'agent-work/worker/1'
    assert worker._record(run,'worker',1)['receipt'] and not (published/'outputs/second.txt').exists()
    for recover in (lambda:worker.dispatch(run,s),lambda:worker.finish(run,s)):
        r=recover()
        assert r['status']=='ok'
        for name in ('receipt.json','transcript.jsonl','final.json','outputs/result.txt','outputs/second.txt'):
            assert (published/name).read_bytes()==(ws/name).read_bytes()


def blind_packet(tmp_path,role='verifier'):
    from test_agent_graph import role_packet
    tmp_path.mkdir(parents=True,exist_ok=True)
    packet,_=role_packet(tmp_path/('packet-'+role),role,{'measurement':[1.0,2.0]})
    return packet


def blind_spec(role='verifier',attempt=1):
    s=spec('review',attempt);s['role']={'id':role,'version':'1','card_sha256':'2'*64};return s


def test_blind_worker_workspace_holds_only_its_role_packet(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch)
    from ravel.workflow import broker
    (run/'producer-headline.json').write_text('{"verdict":"supported"}')
    raw={'pin':{'path':'producer-headline.json','sha256':broker.sha(run/'producer-headline.json')},'as':'inputs/headline.json'}
    packet=blind_packet(tmp_path)
    with pytest.raises(ValueError,match='blind role'):worker.materialize(run,blind_spec())
    s=blind_spec();s['inputs']=[raw]
    with pytest.raises(ValueError,match='blind role'):worker.materialize(run,s,packet=packet)
    s=blind_spec();s['work_order']=raw['pin']
    with pytest.raises(ValueError,match='blind role'):worker.materialize(run,s,packet=packet)
    with pytest.raises(ValueError,match='different role'):
        worker.materialize(run,blind_spec(),packet=blind_packet(tmp_path,'critic'))
    ws=worker.materialize(run,blind_spec(attempt=2),packet=packet)
    files=sorted(p.relative_to(ws).as_posix() for p in (ws/'inputs').rglob('*') if p.is_file())
    assert files==['inputs/packet/artifacts/evidence.json','inputs/packet/manifest.json']
    record=worker._record(run,'review',2)
    assert record['blind'] is True and record['packet']['manifest_sha256']==packet['manifest_sha256']
    (Path(packet['path'])/'artifacts/evidence.json').write_text('{"measurement":[9]}')
    with pytest.raises(ValueError,match='changed'):worker.materialize(run,blind_spec(attempt=3),packet=packet)
    # A non-blind role may not overwrite the packet location with a raw input either.
    s=spec();s['inputs']=[{**raw,'as':'inputs/packet/manifest.json'}]
    with pytest.raises(ValueError,match='role packet'):worker.materialize(run,s,packet=None)


BLIND_CHILD='''import json,os,socket,pathlib
def call(req):
  s=socket.socket(socket.AF_UNIX);s.connect(os.environ["RAVEL_BROKER_SOCKET"]);s.sendall((json.dumps(req)+"\\n").encode())
  return json.loads(s.makefile("rb").readline())
probes={}
for name,p in TARGETS:
  try:open(p,"rb").read();probes[name]="read"
  except (PermissionError,FileNotFoundError):probes[name]="denied"
packet=call({"call_id":"p1","action":"read","args":{"path":"inputs/packet/artifacts/evidence.json"}})
probes["packet_via_broker"]=packet["status"]
for i,rel in enumerate(["../../producer/1/outputs/result.txt","inputs/../../producer/1/outputs/result.txt","calls/1.json"]):
  probes["broker_escape_%d"%i]=call({"call_id":"e%d"%i,"action":"read","args":{"path":rel}})["status"]
call({"call_id":"w1","action":"write","args":{"path":"outputs/result.txt","content":json.dumps(probes)}})
print(json.dumps({"completed":True}))
'''


def test_real_sandbox_blind_worker_cannot_read_producer_output_or_graph_custody(tmp_path,monkeypatch):
    """Workspace, broker, checkpoint, event log and store: every channel to withheld data is denied."""
    _real_sandbox_or_skip(tmp_path)
    worker,run=setup(tmp_path,monkeypatch)
    from ravel.workflow import broker
    producer=worker.materialize(run,spec('producer'));put(run,producer,'outputs/result.txt','headline: supported')
    worker.finish(run,spec('producer'),final=result(),execution={'exit_status':0})
    graph_root=tmp_path/'graph';(graph_root/'framework').mkdir(parents=True);(graph_root/'effects/calls').mkdir(parents=True)
    (graph_root/'graph_state.json').write_text('{"nodes":{"producer":{"result":"supported"}}}')
    (graph_root/'framework/checkpoint.sqlite').write_text('checkpoint with producer writes')
    (graph_root/'effects/calls/producer.json').write_text('{"result":"supported"}')
    (graph_root/'events.jsonl').write_text('{"event":"node_completed"}')
    custody=broker.custody(run)
    targets=[('published_output',run/'agent-work/producer/1/outputs/result.txt'),
             ('live_output',producer/'outputs/result.txt'),('producer_receipt',producer/'receipt.json'),
             ('graph_state',graph_root/'graph_state.json'),('checkpoint',graph_root/'framework/checkpoint.sqlite'),
             ('effect_store',graph_root/'effects/calls/producer.json'),('event_log',graph_root/'events.jsonl'),
             ('receipt_ledger',custody/'worker-receipts.jsonl'),('withheld_source',run/'producer-headline.json')]
    (run/'producer-headline.json').write_text('{"verdict":"supported"}')
    child=BLIND_CHILD.replace('TARGETS',repr([(n,str(p)) for n,p in targets]))
    descriptor={'argv':[sys.executable,'-B','-c',child],'transport':{'id':'inert-stub','transport_kind':'stub'}}
    r=worker.dispatch(run,blind_spec(),launch_spec=descriptor,packet=blind_packet(tmp_path),protected=[graph_root])
    assert r['status']=='ok' and r['isolation']['evidence']['confirmed'] is True
    assert r['isolation']['evidence']['denied_reads']>=10
    ws=worker.workspace(run,'review',1)
    probes=json.loads((ws/'outputs/result.txt').read_text())
    assert {k:v for k,v in probes.items() if k in dict(targets)}=={name:'denied' for name,_ in targets}
    assert probes['packet_via_broker']=='ok'
    assert [probes['broker_escape_%d'%i] for i in range(3)]==['refused']*3
    refused=worker.dispatch(run,blind_spec(attempt=2),packet=blind_packet(tmp_path/'b'),
        launch_spec={**descriptor,'allowed_actions':['read','write','board read']})
    assert refused['status']=='refused' and refused['failure']['code']=='blind_action_refused'
    roots=worker.dispatch(run,blind_spec(attempt=3),packet=blind_packet(tmp_path/'c'),
        launch_spec={**descriptor,'read_paths':[*__import__('ravel.workflow.sandbox',fromlist=['x']).runtime_paths(descriptor['argv']),str(tmp_path/'packet-verifier')]})
    assert roots['status']=='refused' and roots['failure']['code']=='read_root_refused'


def test_declared_environment_names_reach_the_child_and_configuration_exposure_is_computed(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch)
    from ravel.workflow import sandbox
    import pwd
    for names in (['PATH'],['HOME'],['RAVEL_STATE_DIR'],['bad-name'],['A','A']):
        with pytest.raises(ValueError,match='pass_env_names'):worker._pass_env_names({'pass_env_names':names})
    # USER and LOGNAME are reserved: only a Claude-family CLI worker names them, and their values
    # come from the password database, never the parent environment.
    for names in (['USER'],['LOGNAME']):
        with pytest.raises(ValueError,match='pass_env_names'):worker._pass_env_names({'pass_env_names':names})
        with pytest.raises(ValueError,match='pass_env_names'):
            worker._pass_env_names({'pass_env_names':names,'transport':{'transport_kind':'cli-worker','agent':'codex'}})
    claude={'pass_env_names':['LOGNAME','USER'],'transport':{'transport_kind':'cli-worker','agent':'claude'}}
    assert worker._pass_env_names(claude)==['LOGNAME','USER']
    monkeypatch.setenv('USER','parent-spoofed-user')
    account=pwd.getpwuid(__import__('os').getuid()).pw_name
    assert worker._account_env(claude)=={'LOGNAME':account,'USER':account}
    assert worker._account_env({'pass_env_names':[]})=={}
    home=pwd.getpwuid(__import__('os').getuid()).pw_dir
    assert sandbox.user_configuration_exposed([home]) and sandbox.user_configuration_exposed([home+'/.config'])
    assert sandbox.user_configuration_exposed(['/usr'],['XDG_CONFIG_HOME'])
    assert not sandbox.user_configuration_exposed(['/usr','/bin'],['WORKER_FIXTURE_FLAG'])
    _real_sandbox_or_skip(tmp_path)
    monkeypatch.setenv('WORKER_FIXTURE_FLAG','fixture-value');monkeypatch.setenv('WORKER_UNDECLARED','hidden')
    child=("import os,json,socket\ns=socket.socket(socket.AF_UNIX);s.connect(os.environ['RAVEL_BROKER_SOCKET'])\n"
           "value=json.dumps([os.environ.get('WORKER_FIXTURE_FLAG'),os.environ.get('WORKER_UNDECLARED')])\n"
           "s.sendall((json.dumps({'call_id':'w1','action':'write','args':{'path':'outputs/result.txt','content':value}})+'\\n').encode())\n"
           "s.makefile('rb').readline()\nprint('{\"completed\":true}')\n")
    r=worker.dispatch(run,spec(),launch_spec={'argv':[sys.executable,'-B','-c',child],'pass_env_names':['WORKER_FIXTURE_FLAG'],
                                               'transport':{'id':'inert-stub','transport_kind':'stub'}})
    ws=worker.workspace(run,'worker',1)
    assert r['status']=='ok' and r['pass_env_names']==['WORKER_FIXTURE_FLAG']
    assert json.loads((ws/'outputs/result.txt').read_text())==['fixture-value',None]
    assert r['isolation']['user_configuration_loaded'] is False
    assert 'fixture-value' not in (ws/'receipt.json').read_text()


def test_read_roots_outside_the_tool_runtime_are_refused_for_every_role(tmp_path,monkeypatch):
    _real_sandbox_or_skip(tmp_path)
    worker,run=setup(tmp_path,monkeypatch)
    from ravel.workflow import sandbox
    unrelated=tmp_path/'other-project';unrelated.mkdir();(unrelated/'notes.txt').write_text('unrelated')
    argv=[sys.executable,'-B','-c','print(1)']
    r=worker.dispatch(run,spec(),launch_spec={'argv':argv,'read_paths':[*sandbox.runtime_paths(argv),str(unrelated)],
                                               'transport':{'id':'inert-stub','transport_kind':'stub'}})
    assert r['status']=='refused' and r['failure']['code']=='read_root_refused' and r['credited_outputs']==[]


def test_final_record_schemas_are_code_owned_and_validated(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch)
    s=spec();s['final_record_schema']='free-form.v9'
    with pytest.raises(ValueError,match='final record schema'):worker.materialize(run,s)
    review={'completed':True,'disposition':'request_evidence','findings':[{'summary':'covariance source not supplied'}]}
    for attempt,final,status in ((1,review,'ok'),(2,{**review,'disposition':'approved'},'failed'),
                                 (3,{**review,'findings':[{'summary':' '}]},'failed'),(4,{'completed':True},'failed')):
        s=spec(attempt=attempt);s['final_record_schema']='reviewer.v1'
        ws=worker.materialize(run,s);put(run,ws,'outputs/result.txt','review')
        r=worker.finish(run,s,final=final,execution={'exit_status':0})
        assert r['status']==status and r['final_record']['valid'] is (status=='ok')


def test_quorum_join_item_attempt_bound_and_concurrency(tmp_path,monkeypatch):
    import threading
    worker,run=setup(tmp_path,monkeypatch)
    barrier=threading.Barrier(3,timeout=5);calls=[]
    def dispatch(rundir,s,**kwargs):
        calls.append((s['node_id'],s['attempt']));barrier.wait()
        ws=worker.materialize(rundir,s)
        if s['node_id']!='group.b':put(run,ws,'outputs/result.txt','r')
        return worker.finish(rundir,s,final=result(),execution={'exit_status':0})
    monkeypatch.setattr(worker,'dispatch',dispatch)
    m={'schema_version':1,'kind':'agent-map','id':'group','spec':spec(),'join':'quorum:2',
       'items':[{'key':k,'inputs':[]} for k in ('a','b','c')],'workers':3,'max_item_attempts':2}
    receipts=worker.dispatch_map(run,m)  # three items meet the barrier only when run concurrently
    assert worker.join_outcome(m,receipts)=='ok' and worker.join_outcome({**m,'join':'all'},receipts)=='failed'
    barrier=threading.Barrier(1,timeout=5)
    worker.dispatch_map(run,m);worker.dispatch_map(run,m)
    assert [c for c in calls if c[0]=='group.b']==[('group.b',1),('group.b',2)]
    ambiguous=[{**r,'status':'ambiguous'} if r['node_id']=='group.b' else r for r in receipts]
    assert worker.join_outcome(m,ambiguous)=='ambiguous'
    for bad in ({**m,'join':'quorum:4'},{**m,'workers':0},{**m,'max_item_attempts':17},{**m,'extra':1}):
        with pytest.raises(ValueError):worker.validate_map(bad)


def test_absent_transport_adapter_and_validator_allowlist_fail_closed(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch)
    from ravel.workflow import broker, sandbox
    import importlib
    monkeypatch.setattr(sandbox,'available',lambda:'macos')
    real=importlib.import_module
    def absent(name,*args,**kwargs):
        if name=='ravel.workflow.transports.cli_worker':raise ImportError(name)
        return real(name,*args,**kwargs)
    monkeypatch.setattr(worker.importlib,'import_module',absent)
    r=worker.dispatch(run,spec())
    assert r['status']=='refused' and r['failure']['code']=='transport_adapter_unavailable'
    assert r['attestation']=='self_attested' and worker.processes(run)==[]
    ws=worker.workspace(run,'worker',1)
    tool=broker.Broker(run,ws,node_id='worker',attempt=1,allowed_actions=['check'],max_calls=1)
    monkeypatch.setattr(broker,'read_json',lambda path:[])
    with pytest.raises(ValueError,match='allowlist'):
        tool.register('check',lambda args:{},derivation='registered_validator',validator_id='unlisted')


def test_concurrent_publication_repairs_do_not_collide(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    worker,run=setup(tmp_path,monkeypatch)
    s=spec();ws=worker.materialize(run,s)
    for i in range(40):(ws/f'outputs/part-{i}.txt').write_text(str(i))
    put(run,ws,'outputs/result.txt','r');worker.finish(run,s,final=result(),execution={'exit_status':0})
    import shutil;shutil.rmtree(run/'agent-work/worker/1')
    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts=list(pool.map(lambda _:worker.load_receipt(run,'worker',1),range(16)))
    assert all(r['status']=='ok' for r in receipts)
    assert (run/'agent-work/worker/1/outputs/part-39.txt').read_text()=='39'
    assert not list((run/'agent-work/worker/1').rglob('*.publish'))


def test_an_output_without_a_matching_broker_receipt_is_not_credited(tmp_path,monkeypatch):
    worker,run=setup(tmp_path,monkeypatch)
    s=spec();ws=worker.materialize(run,s)
    (ws/'outputs/result.txt').write_text('written natively')  # a native tool, no broker receipt
    r=worker.finish(run,s,final=result(),execution={'exit_status':0})
    assert r['credited_outputs']==[] and r['outcome']['computed_checks']['declared_outputs'] is False
    s2=spec(attempt=2);ws2=worker.materialize(run,s2);put(run,ws2,'outputs/result.txt','receipted')
    (ws2/'outputs/result.txt').write_text('changed after the receipt')
    r2=worker.finish(run,s2,final=result(),execution={'exit_status':0})
    assert r2['credited_outputs']==[] and r2['status']=='failed'


FORGING_CHILD='''import json,pathlib
pathlib.Path("scratch/stdout").write_text(json.dumps({"completed":True,"forged":True}))
pathlib.Path("scratch/stderr").write_text("forged")
print(json.dumps({"completed":False,"genuine":True}))
'''


def test_receipt_inputs_come_from_the_supervisor_pipe_not_the_workspace(tmp_path,monkeypatch):
    _real_sandbox_or_skip(tmp_path)
    worker,run=setup(tmp_path,monkeypatch)
    r=worker.dispatch(run,spec(),launch_spec={'argv':[sys.executable,'-B','-c',FORGING_CHILD],
                                              'transport':{'id':'inert-stub','transport_kind':'stub'}})
    ws=worker.workspace(run,'worker',1)
    assert json.loads((ws/'final.json').read_text())=={'completed':False,'genuine':True}
    captured=worker.capture_path(run,'worker',1,'stdout')
    assert json.loads(captured.read_text())=={'completed':False,'genuine':True}
    assert not captured.is_relative_to(ws.parent) and r['isolation']['evidence']['confirmed'] is True


@pytest.mark.parametrize('validator_id, passed', [('check-run', False),
    ('check:validation.validate_run_state.check_route', True)])
def test_finish_matches_the_exact_required_self_check(tmp_path, monkeypatch, validator_id, passed):
    from ravel.workflow import broker
    worker, run = setup(tmp_path, monkeypatch)
    check = 'check:validation.validate_run_state.check_route'
    path = run / 'order.json'
    path.write_text(json.dumps({'kind': 'work-order', 'node_id': 'worker', 'self_check': [check]}))
    value = spec()
    value['work_order'] = {'path': 'order.json', 'sha256': broker.sha(path)}
    ws = worker.materialize(run, value)
    put(run, ws, 'outputs/result.txt', 'synthetic')
    target = broker.Broker(run, ws, node_id='worker', attempt=1, allowed_actions=['check'], max_calls=100000)
    # A validator receipt is ok only when its handler reports that the validator ran and passed.
    target.register('check', lambda args: {'validator_executed': True, 'exit_status': 0},
                    derivation='registered_validator', validator_id=validator_id)
    assert target.call({'call_id': 'self-check', 'action': 'check', 'args': {}})['status'] == 'ok'
    receipt = worker.finish(run, value, final=result(), execution={'exit_status': 0})
    assert receipt['outcome']['computed_checks']['self_checks'] == passed
    assert receipt['status'] == ('ok' if passed else 'failed')
