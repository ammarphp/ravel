"""Synthetic complete evidence, real public readers/Host/Graph; zero scientific calls."""
from pathlib import Path
from copy import deepcopy
import hashlib
import json
import os
import pytest
from ravel.workflow import review_context as rc, physics_review as pr, agent_graph as graph, agent_host as host, scientific_judgment as judgment, execution
from ravel.workflow.state_io import atomic_json, read_json
from ravel import cli

LIMITS={'max_artifacts':20000,'max_total_bytes':512*1024**2}


def node(pin):
    return {'id':'critic','kind':'model','role':'critic','depends_on':[], 'inputs':[],
        'packet':pin,'action':'external','max_attempts':1,'parameters':{
        'instructions':'Engineering fixture only. Inspect indexed retained assertions; no physics or authority.',
        'model':'inert-control','reasoning_effort':'low','max_output_tokens':256,
        'output_schema':{'type':'object','properties':{'status':{'type':'string'}},'required':['status'],'additionalProperties':False}}}


@pytest.fixture(scope='module')
def large(tmp_path_factory):
    root=tmp_path_factory.mktemp('complete-12107'); (root/'inputs').mkdir(); (root/pr.DIRECTORY/'snapshots').mkdir(parents=True)
    # Hardlinks only make this own fixture compact on disk; each of the 12107
    # ordinary paths is independently read/authenticated by the actual APIs.
    prefix=b'bounded synthetic retained source assertion\n'
    raw=prefix+b'x'*(24576-len(prefix))
    assert len(raw)==24576
    source=root/pr.DIRECTORY/'snapshots/payload.blob';source.write_bytes(raw);sha=hashlib.sha256(raw).hexdigest()
    rows=[]
    for i in range(12107):
        path=root/f'inputs/source-{i:05d}.dat';os.link(source,path)
        rows.append({'path':str(path),'sha256':sha,'size':len(raw),'snapshot':str(source),'content_retained':True})
    for i in range(72):
        rows.append({'path':str(root/f'inputs/unretained-{i}.bin'),'sha256':'d'*64,'size':2000001,'snapshot':None,'content_retained':False})
    reg={'run_id':'synthetic-only','policy':{'claim_scopes':{'diagnostic':{}},'required_checks':[],'max_redos':0},'sha256':'f'*64}
    cycle={'event':'cycle','cycle_id':'synthetic-cycle','sha256':'e'*64,'snapshots':rows,'checks':[], 'inherited_findings':[]}
    return root,raw,reg,[cycle]


def bind(monkeypatch,fixture):
    root,raw,reg,events=fixture
    monkeypatch.setattr(pr,'_read',lambda *a,**kw:(deepcopy(reg),deepcopy(events)))
    monkeypatch.setattr(pr,'_base_live',lambda *a,**kw:None)
    monkeypatch.setattr(execution,'runtime_context',lambda:{'platform':'synthetic','python':'inert','environment_sha256':'inert','packages_sha256':'inert'})
    return root,raw


@pytest.fixture(scope='module')
def packet(large,tmp_path_factory):
    # This is a genuine public projection/create call over explicit inert journal
    # records. No real journal or original stage has been opened or modified.
    m=pytest.MonkeyPatch(); root,_=bind(m,large)
    out=tmp_path_factory.mktemp('packets')/'packet'
    try:manifest=rc.create(root,'critic',out,index_limits=LIMITS)
    finally:m.undo()
    return out,manifest


def test_public_complete_projection_host_external_and_pages(large,packet,tmp_path):
    out,m=packet;raw=large[1];assert len(m['artifacts'])==12107 and len(m['omissions'])==72
    assert m['index_limits']==LIMITS
    pin={'path':str(out),'manifest_sha256':m['sha256']};n=node(pin);r=tmp_path/'graph'
    graph.create(r,{'schema_version':1,'graph_id':'synthetic-large-ordinary','budget':{
        'max_nodes':1,'max_calls':1,'max_output_tokens':256,'max_wall_seconds':30,'max_reworks':0},'nodes':[n]})
    ready=graph.prepare_external(r,'critic')
    assert ready['model_executed'] is False and graph.status(r)['usage']['calls']==1
    document=read_json(ready['request_file'])
    prepared=host.AgentHost(max_request_bytes=12000).prepare_model_context(n,document['request'])['context']['review_packet']
    assert prepared['presentation']['artifact_count']==12107
    assert prepared['presentation']['all_content_read_by_model'] is False
    assert prepared['presentation']['omission_count']==72
    assert len(json.dumps(prepared).encode())<=12000
    page=rc.read_index_page(out,expected_manifest_sha256=m['sha256'],query='a12106')
    assert page['total_entries']==12107 and [e['id'] for e in page['entries']]==['a12106']
    assert page['artifact_content_presented'] is False
    missing=rc.read_index_page(out,expected_manifest_sha256=m['sha256'],section='omissions',query='unretained-71')
    assert missing['total_entries']==72 and len(missing['entries'])==1
    content=rc.read_artifact_page(out,'a12106',expected_manifest_sha256=m['sha256'],max_bytes=32)
    assert content['bytes']==32 and content['total_bytes']==len(raw) and not content['complete']
    assert content['artifact_sha256']==hashlib.sha256(raw).hexdigest()


def test_public_batch_full_basis_once_selected_content_bounded(large,packet,monkeypatch):
    root,raw=bind(monkeypatch,large);out,m=packet
    selected=['a12106','a0000']
    result=rc.read_artifacts(out,selected,expected_manifest_sha256=m['sha256'],rundir=root,expected_role='critic',
        max_source_bytes=512*1024**2,max_session_io_bytes=4*1024**3)
    assert result['receipt']['requested_ids']==selected and result['receipt']['requested_content_reads']==2
    assert result['receipt']['content_bytes']==2*len(raw)
    assert result['receipt']['manifest_parses']==1
    assert result['receipt']['limits']['max_total_bytes']==64*1024**2
    assert result['receipt']['total_operation_io_bytes'] is None
    assert all(not result['receipt'][x] for x in ('acceptance','delivery','reuse','role_vote'))
    assert all(e['content']==raw for e in result['artifacts'])
    with pytest.raises(ValueError,match='source projection exceeds'):
        rc.read_artifacts(out,selected,expected_manifest_sha256=m['sha256'],rundir=root,expected_role='critic')


def test_legacy_large_count_still_refuses(packet,tmp_path):
    out,m=packet;old=deepcopy(m);old.pop('index_limits');old['sha256']=graph.digest({k:v for k,v in old.items()if k!='sha256'})
    tiny=tmp_path/'legacy';tiny.mkdir();(tiny/'artifacts').mkdir();atomic_json(tiny/'manifest.json',old)
    with pytest.raises(ValueError,match='bounded complete'):
        rc.verify_packet(tiny,expected_manifest_sha256=old['sha256'])


@pytest.mark.parametrize('change',['count','limits','duplicate','path','omissions','json'])
def test_closed_finite_index_and_malformed_population(packet,tmp_path,change):
    _,m=packet;doc=deepcopy(m)
    if change=='count':doc['artifacts']=[doc['artifacts'][0]]*20001
    elif change=='limits':doc['index_limits']['max_total_bytes']=512*1024**2+1
    elif change=='duplicate':doc['artifacts'][1]=doc['artifacts'][0]
    elif change=='path':doc['artifacts'][0]['path']='artifacts/../foreign.dat'
    elif change=='omissions':doc['omissions']='not an inventory'
    p=tmp_path/change;p.mkdir();(p/'artifacts').mkdir()
    doc['sha256']=graph.digest({k:v for k,v in doc.items()if k!='sha256'})
    atomic_json(p/'manifest.json',doc)
    if change=='json':(p/'manifest.json').write_text('{"artifacts":[],"artifacts":[]}')
    with pytest.raises(ValueError):rc.verify_packet(p,expected_manifest_sha256=doc['sha256'])


def test_aggregate_authentication_bound_not_unlimited(packet):
    out,m=packet;index=rc._PacketIndex(out,m['sha256']);entry=index.entries['a0000']
    index.total=index.limits['max_total_bytes']-1
    with pytest.raises(ValueError,match='aggregate byte bound'):index.read(entry)


@pytest.mark.parametrize('kind',['bytes','aba','member'])
def test_final_copy_or_membership_drift_refuses(packet,monkeypatch,kind):
    out,m=packet;entry=m['artifacts'][0];p=out/entry['path'];old=p.read_bytes();index=rc._PacketIndex(out,m['sha256']);index.read(entry)
    if kind=='member':extra=out/'artifacts/foreign.dat';extra.write_bytes(b'new')
    else:p.write_bytes(b'changed');
    if kind=='aba':p.write_bytes(old)
    try:
        with pytest.raises(ValueError):index.finish()
    finally:
        if kind=='member':extra.unlink()
        else:p.write_bytes(old)


def test_no_cross_call_cache(packet):
    out,m=packet;a=rc._PacketIndex(out,m['sha256']);b=rc._PacketIndex(out,m['sha256'])
    assert a is not b and a.observed is not b.observed
    assert 'a12106' not in a.observed
    a.finish();b.finish()


@pytest.mark.parametrize('valid',[True,False])
def test_high_id_empty_requires_exact_same_cycle_source(tmp_path,monkeypatch,valid):
    p=tmp_path/'packet';p.mkdir();(p/'artifacts').mkdir();(p/'artifacts/a10000.dat').write_bytes(b'')
    sha=hashlib.sha256(b'').hexdigest();cycle={'cycle_id':'own','sha256':'e'*64,'event':'cycle',
        'snapshots':[{'path':'inputs/empty.dat','size':0,'sha256':sha}]}
    reg={};monkeypatch.setattr(pr,'_read',lambda *a,**kw:(reg,[cycle]));monkeypatch.setattr(pr,'_empty_input_paths',lambda *a:{'inputs/empty.dat'})
    monkeypatch.setattr(pr,'_empty_snapshot_allowed',lambda *a:True)
    doc={'artifacts':[{'id':'a10000','path':'artifacts/a10000.dat','sha256':sha,'source_phase':'current_cycle',
        'projection':'exact bytes','source_path':'inputs/empty.dat'if valid else'inputs/control.json','source_sha256':sha}],
        'cycle_id':'own','source_event_sha256':'e'*64,'omissions':[]}
    doc['sha256']=graph.digest(doc);atomic_json(p/'manifest.json',doc)
    pin={'kind':'role_context','path':str(p/'manifest.json'),'sha256':hashlib.sha256((p/'manifest.json').read_bytes()).hexdigest(),
        'manifest_sha256':doc['sha256'],'cycle_id':'own','cycle_sha256':'e'*64}
    monkeypatch.setattr(execution,'runtime_context',lambda:{})
    session=execution._validation_session(tmp_path)
    try:
        if valid:
            assert pr._context_support(tmp_path,pin,session)['kind']=='role_context'
            assert session.finish()==[]
        else:
            with pytest.raises(ValueError,match='empty role context'):pr._context_support(tmp_path,pin,session)
    finally:session.close()



def test_source_session_declaration_distinct_from_content_ceiling(tmp_path,monkeypatch):
    monkeypatch.setattr(execution,'runtime_context',lambda:{})
    s=rc._BatchReadSession(tmp_path,4*1024**3);s._reserve(1147464304);s._reserve(580*1024**2)
    assert s.io_bytes>1024**3
    with pytest.raises(ValueError,match='I/O'):s._reserve(4*1024**3)
    s.close()
    assert rc._BATCH_LIMITS['max_total_bytes']==256*1024**2 and rc._BATCH_LIMITS['max_artifact_bytes']==64*1024**2


def test_role_preparation_passes_declared_resources_to_public_context(monkeypatch,tmp_path):
    # Stop immediately at the actual create boundary; do not fabricate a vote,
    # dispatch or scientific run. Every guard before that boundary remains called.
    reg={'policy':{'actors':{'physics_critic':'critic'},'claim_scopes':{'diagnostic':{}}}}
    view={'state':'awaiting_review','reviews':[]};seen=[]
    monkeypatch.setattr(judgment,'_live',lambda *a,**kw:(tmp_path,reg,[],view))
    def capture(root,role,out,**kw):
        seen.append(kw);raise RuntimeError('inert stop at actual public create')
    monkeypatch.setattr(rc,'create',capture)
    with pytest.raises(RuntimeError,match='inert stop'):
        judgment.prepare_role(tmp_path,tmp_path/'fresh',role='critic',actor_id='critic',model='inert',reasoning_effort='low',
            max_output_tokens=256,max_wall_seconds=30,claim_scope='diagnostic',context_index_limits=LIMITS)
    assert seen==[{'index_limits':LIMITS}]


def test_public_cli_context_resource_declaration(monkeypatch,tmp_path,capsys):
    calls=[];monkeypatch.setattr(rc,'create',lambda *a,**kw:calls.append(kw)or{'inert':True})
    assert cli.main(['review-context','create','--rundir',str(tmp_path),'--role','critic','--out',str(tmp_path/'context'),
        '--max-index-artifacts','20000','--max-index-bytes','536870912'])==0
    assert calls==[{'index_limits':LIMITS}]
    calls.clear();monkeypatch.setattr(judgment,'prepare_role',lambda *a,**kw:calls.append(kw)or{'inert':True})
    assert cli.main(['judgment','prepare-role','--rundir',str(tmp_path),'--out',str(tmp_path/'role'),
        '--role','critic','--actor','critic','--model','inert','--reasoning-effort','low',
        '--max-output-tokens','256','--max-wall-seconds','30','--max-index-artifacts','20000','--max-index-bytes','536870912'])==0
    assert calls[0]['context_index_limits']==LIMITS


def test_host_judgment_request_allows_only_named_closed_resource_argument(monkeypatch,tmp_path):
    seen=[];monkeypatch.setattr(judgment,'prepare_role',lambda *a,**kw:seen.append(kw)or{'inert':True})
    kwargs={'out':str(tmp_path/'role'),'role':'critic','actor_id':'critic','model':'inert','reasoning_effort':'low',
        'max_output_tokens':256,'max_wall_seconds':30,'claim_scope':None,'case_pin':None,'proposal_binding':None,
        'context_index_limits':LIMITS}
    path=tmp_path/'request.json';atomic_json(path,{'operation':'prepare-role','rundir':str(tmp_path),'arguments':kwargs})
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    assert judgment.host_tool({'request_input':'request'},{'request':(path,sha)})=={'inert':True}
    assert seen[0]['context_index_limits']==LIMITS
    bad=deepcopy(kwargs);bad['undocumented_unlimited']=True
    atomic_json(path,{'operation':'prepare-role','rundir':str(tmp_path),'arguments':bad})
    with pytest.raises(ValueError,match='prepare arguments'):
        judgment.host_tool({'request_input':'request'},{'request':(path,hashlib.sha256(path.read_bytes()).hexdigest())})


def test_ordinary_advance_forwards_same_declared_envelope(monkeypatch,tmp_path):
    seen=[];reg={'policy':{'actors':{'physics_critic':'critic'}}}
    monkeypatch.setattr(judgment,'_live',lambda *a,**kw:(tmp_path,reg,[],{}))
    monkeypatch.setattr(judgment,'next_step',lambda *a:{'phase':'result_review','role':'critic'})
    def stop(*a,**kw):seen.append(kw);raise RuntimeError('inert stop before role work')
    monkeypatch.setattr(judgment,'prepare_role',stop)
    class InertHost:
        identity={'fixture':'declared inert host; the stop precedes every dispatch'}
        def execute(self,*a,**kw):raise AssertionError('no role may be dispatched')
    # The review session binds the host identity before any role is prepared.
    with pytest.raises(graph.GraphError,match='executable host must expose its nonsecret source/config identity'):
        judgment.advance(tmp_path,tmp_path/'unbound',host=None,model='inert',reasoning_effort='low',
            max_output_tokens=256,max_wall_seconds=30,context_index_limits=LIMITS)
    assert seen==[]
    with pytest.raises(RuntimeError,match='inert stop'):
        judgment.advance(tmp_path,tmp_path/'advance',host=InertHost(),model='inert',reasoning_effort='low',
            max_output_tokens=256,max_wall_seconds=30,context_index_limits=LIMITS)
    assert len(seen)==1 and seen[0]['context_index_limits']==LIMITS
