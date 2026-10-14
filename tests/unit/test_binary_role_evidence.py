"""Pure indexed-evidence controls: no model/native/provider/OS child calls."""
from copy import deepcopy
from pathlib import Path
import base64
import hashlib
import json
import os
import pytest
from ravel.workflow import agent_host as host, agent_graph as graph, review_context as rc
from ravel.workflow.state_io import atomic_json, read_json


def packet(root, docs, *, omissions=()):
    root.mkdir(); (root/'artifacts').mkdir()
    entries=[]
    for identity,raw in docs.items():
        suffix='.json' if identity in {'judgment_request','public_case'} else '.dat'
        path=f'artifacts/{identity}{suffix}'; (root/path).write_bytes(raw)
        sha=hashlib.sha256(raw).hexdigest()
        entries.append({'id':identity,'path':path,'sha256':sha,'source_sha256':sha,
                        'source_path':'/original/outputs/'+identity,'projection':'literal source copy'})
    manifest={'schema_version':1,'role':'critic','cycle_id':'fixture-cycle','source_event_sha256':'a'*64,
              'artifacts':entries,'omissions':list(omissions),'findings':[],'reviews':[],
              'allowed_claim_scopes':['diagnostic'],'required_checks':[]}
    manifest['sha256']=graph.digest(manifest);atomic_json(root/'manifest.json',manifest)
    return {'path':str(root),'manifest_sha256':manifest['sha256']}


def node(pin,action='external',kind='model',parameters=None):
    return {'id':'critic','kind':kind,'role':'critic' if kind=='model' else 'executor','depends_on':[],
            'inputs':[],'packet':pin,'action':action,'parameters':parameters or {
            'instructions':'Inspect exact supplied synthetic evidence. No actual physics claim.',
            'model':'inert-synthetic','reasoning_effort':'low','max_output_tokens':256,
            'output_schema':{'type':'object','properties':{'status':{'type':'string'}},
                             'required':['status'],'additionalProperties':False}},'max_attempts':1}


def request(n):
    return {'schema_version':1,'graph_id':'fixture','graph_revision':'a'*64,'node_id':n['id'],
            'generation':0,'node_sha256':graph.digest(n),'request_id':'b'*64,
            'input_artifacts':deepcopy(n['inputs']),'packet':deepcopy(n['packet']),'dependencies':[]}


class Control:
    calls=[]
    def check_cancelled(self): pass
    def cancelled(self): return False
    def call(self,label,kind,request,function,output_tokens=0):
        self.calls.append((label,kind)); return function()


def test_binary_witness_and_exact_text_survive(tmp_path):
    raw=b'\xcf\xfa\xed\xfe\x00\xffretained-binary'
    p=packet(tmp_path/'packet',{'binary':raw,'judgment_request':b'{"scope":"diagnostic"}'})
    prepared=host.AgentHost().prepare_model_context(node(p),request(node(p)))
    view=prepared['context']['review_packet']
    assert view['manifest_sha256']==p['manifest_sha256']
    assert view['presentation']['binary_count']==1
    assert view['presentation']['all_content_read_by_model'] is False
    assert view['artifacts'][0]['id']=='judgment_request'
    assert view['binary_witnesses'][0]['witness']['hex']==raw[:32].hex()
    assert view['binary_witnesses'][0]['witness']['whole_content_presented'] is False
    page=rc.read_artifact_page(p['path'],'binary',expected_manifest_sha256=p['manifest_sha256'],max_bytes=8)
    assert page['content_encoding']=='base64'
    assert base64.b64decode(page['content'])==raw[:8]
    assert page['artifact_sha256']==hashlib.sha256(raw).hexdigest()
    assert (Path(p['path'])/'artifacts/binary.dat').read_bytes()==raw


def test_large_complete_index_and_paged_omissions(tmp_path):
    docs={f'a{i:04}':(f'source-{i}:'+'x'*400).encode() for i in range(180)}
    docs['judgment_request']=b'{"exact":"request"}'
    omitted=[{'id':f'old{i}','source_sha256':'d'*64,'reason':'large original retained; witness required'} for i in range(43)]
    p=packet(tmp_path/'packet',docs,omissions=omitted)
    h=host.AgentHost(max_request_bytes=12000)
    view=h.prepare_model_context(node(p),request(node(p)))['context']['review_packet']
    assert len(json.dumps(view).encode())<12000
    assert view['presentation']['artifact_count']==181
    assert view['presentation']['omission_count']==43
    assert view['context']['omissions']['sha256']==graph.digest(omitted)
    assert view['context']['omissions']['complete_content_presented'] is False
    seen=[];offset=0
    while True:
        page=rc.read_index_page(p['path'],expected_manifest_sha256=p['manifest_sha256'],offset=offset,max_bytes=4096)
        seen += [e['id'] for e in page['entries']]
        assert page['artifact_content_presented'] is False
        assert page['complete_index_sha256']==view['presentation']['complete_index_sha256']
        if page['complete']:break
        assert page['next_offset']>offset;offset=page['next_offset']
    assert seen==list(docs)
    selected=rc.read_index_page(p['path'],expected_manifest_sha256=p['manifest_sha256'],query='a0179')
    assert [e['id'] for e in selected['entries']]==['a0179']
    omission=rc.read_index_page(p['path'],expected_manifest_sha256=p['manifest_sha256'],section='omissions',query='old42')
    assert omission['entries']==[omitted[-1]]
    assert omission['complete_index_sha256']==graph.digest(omitted)


def test_complete_external_transport_has_honest_exact_presentation(tmp_path):
    raw=b'\xff\x00binary'; subject=b'{"exact":"role request"}'
    p=packet(tmp_path/'packet',{'binary':raw,'judgment_request':subject,'public_case':b'{"case":"inert"}'})
    root=tmp_path/'graph';n=node(p)
    graph.create(root,{'schema_version':1,'graph_id':'inert-synthetic-transport',
        'budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':256,'max_wall_seconds':30,'max_reworks':0},'nodes':[n]})
    prepared=graph.prepare_external(root,'critic')
    assert prepared['model_executed'] is False
    document=read_json(prepared['request_file'])
    assert set(document['prepared_host']['sources'])=={'agent_graph','agent_host','review_context','langgraph_runtime'}
    assert graph._validate_prepared_external_host(document['prepared_host'])==graph._external_identity()
    response=tmp_path/'response.json'
    atomic_json(response,{'schema_version':1,'request_id':prepared['request_id'],
        'request_sha256':prepared['request_sha256'],'invocation_id':'synthetic-only-no-model',
        'actor_id':'synthetic-critic','observed_model':'inert-fixture','fresh_context':True,
        'parent_transcript_supplied':False,'value':{'status':'evidence_requested'}})
    status=graph.deliver_external(root,'critic',response)
    assert status['complete'] and status['usage']['calls']==1
    sha=hashlib.sha256(subject).hexdigest()
    r=graph.role_receipt(root,'critic',expected_subject_sha256=sha,require_exact_subject=True)
    assert r['exact_subject_presented'] and not r['physics_validated']
    with pytest.raises(graph.GraphError,match='exact scientific subject'):
        graph.role_receipt(root,'critic',expected_subject_sha256=hashlib.sha256(raw).hexdigest(),require_exact_subject=True)
    binary=graph.role_receipt(root,'critic',expected_subject_sha256=hashlib.sha256(raw).hexdigest())
    assert not binary['exact_subject_presented']


def test_small_legacy_context_is_inline_and_two_source_pin_still_valid(tmp_path):
    p=packet(tmp_path/'packet',{'evidence':b'{"value":3}'})
    v=host.AgentHost().prepare_model_context(node(p),request(node(p)))['context']['review_packet']
    assert 'presentation' not in v
    assert v['artifacts'][0]['content']=='{"value":3}'
    prepared=graph._capture_external_host(tmp_path)
    assert set(prepared['sources'])=={'agent_graph','agent_host','review_context','langgraph_runtime'}
    assert graph._validate_prepared_external_host(prepared)==prepared['identity']
    # An identity names every source it binds. A current four-source identity cannot shed one pin.
    partial=deepcopy(prepared);partial['sources'].pop('review_context')
    with pytest.raises(graph.GraphError,match='prepared host sources requires exactly'):
        graph._validate_prepared_external_host(partial)
    # Legacy three-source and two-source records stay valid under their own closed identities.
    prepared['identity'].pop('langgraph_runtime_sha256');prepared['sources'].pop('langgraph_runtime')
    assert graph._validate_prepared_external_host(prepared)==prepared['identity']
    prepared['identity'].pop('review_context_sha256');prepared['sources'].pop('review_context')
    assert set(prepared['sources'])=={'agent_graph','agent_host'}
    assert graph._validate_prepared_external_host(prepared)==prepared['identity']


@pytest.mark.parametrize('change',['bytes','binary','extra','remove','symlink','manifest'])
def test_complete_custody_refuses_drift(tmp_path,change):
    p=packet(tmp_path/'packet',{'a0001':b'old','binary':b'\xff\x00'})
    d=Path(p['path']); target=d/'artifacts/a0001.dat'
    if change=='bytes':target.write_bytes(b'new')
    elif change=='binary':(d/'artifacts/binary.dat').write_bytes(b'\xfe\x00')
    elif change=='extra':(d/'artifacts/foreign.dat').write_bytes(b'extra')
    elif change=='remove':target.unlink()
    elif change=='symlink':target.unlink();target.symlink_to(d/'artifacts/binary.dat')
    else:
        m=read_json(d/'manifest.json');m['role']='verifier';atomic_json(d/'manifest.json',m)
    with pytest.raises((ValueError,host.HostFailure)):
        host.AgentHost().prepare_model_context(node(p),request(node(p)))


@pytest.mark.parametrize('mode',['bytes','aba','member','ancestor'])
def test_ending_census_refuses_late_change(tmp_path,monkeypatch,mode):
    p=packet(tmp_path/'packet',{'first':b'old','second':b'next'})
    target=Path(p['path'])/'artifacts/first.dat';old=target.read_bytes()
    original=rc._PacketIndex.read
    def change(self,entry):
        raw=original(self,entry)
        if entry['id']=='second':
            if mode in ('bytes','aba'):
                target.write_bytes(b'new')
                if mode=='aba':target.write_bytes(old)
            elif mode=='member':(target.parent/'foreign.dat').write_bytes(b'new')
            else:
                parent=target.parent;parent.rename(parent.with_name('old-artifacts'))
                parent.mkdir()
                for child in parent.with_name('old-artifacts').iterdir():os.link(child,parent/child.name)
        return raw
    monkeypatch.setattr(rc._PacketIndex,'read',change)
    with pytest.raises((ValueError,host.HostFailure)):
        host.AgentHost().prepare_model_context(node(p),request(node(p)))


def test_prepare_checks_manifest_once_per_observation(tmp_path,monkeypatch):
    p=packet(tmp_path/'packet',{f'a{i}':b'{}' for i in range(40)})
    original=rc._strict_json_bytes;calls=[]
    def read(raw):calls.append(len(raw));return original(raw)
    monkeypatch.setattr(rc,'_strict_json_bytes',read)
    rc.verify_packet(p['path'],expected_manifest_sha256=p['manifest_sha256'])
    assert len(calls)==1
    rc.verify_packet(p['path'],expected_manifest_sha256=p['manifest_sha256'])
    assert len(calls)==2


def test_tool_index_and_unpreviewed_page_are_existing_accounted_actions(tmp_path):
    docs={f'a{i:02}':b'x'*600 for i in range(40)};docs['binary']=b'\xff\x00\xfe'
    p=packet(tmp_path/'packet',docs)
    h=host.AgentHost(max_request_bytes=18000)
    idx=node(p,'review-index','tool',{'section':'artifacts','offset':0,'max_bytes':4096,'query':'a39'})
    control=Control();r=h.execute(idx,request(idx),control)
    assert r['value']['entries'][0]['id']=='a39' and r['physics_validated'] is False
    page=node(p,'review-read','tool',{'artifact_id':'a39','offset':500,'max_bytes':64})
    r=h.execute(page,request(page),control)
    assert r['value']['content']=='x'*64
    assert ('review-index','tool') in control.calls and ('review-read','tool') in control.calls
    page['parameters']['artifact_id']='absent'
    with pytest.raises(host.HostFailure):h.execute(page,request(page),control)


@pytest.mark.parametrize('kwargs',[{'offset':-1},{'offset':999},{'max_bytes':0},{'max_bytes':65537},{'section':'raw'},{'query':'x'*257}])
def test_index_page_bounds(tmp_path,kwargs):
    p=packet(tmp_path/'packet',{'evidence':b'{}'})
    with pytest.raises(ValueError):rc.read_index_page(p['path'],expected_manifest_sha256=p['manifest_sha256'],**kwargs)


def test_exact_required_request_over_bound_refuses_not_truncates(tmp_path):
    p=packet(tmp_path/'packet',{'binary':b'\xff','judgment_request':b'x'*10000})
    with pytest.raises(host.HostFailure,match='bounded declared witness'):
        host.AgentHost(max_request_bytes=10000).prepare_model_context(node(p),request(node(p)))


def test_last_context_serialization_cannot_admit_changed_copy(tmp_path,monkeypatch):
    p=packet(tmp_path/'packet',{'binary':b'\xff','judgment_request':b'{"exact":true}'})
    target=Path(p['path'])/'artifacts/binary.dat'
    original=host._json_bytes
    def late(value):
        raw=original(value)
        if type(value) is dict and set(value)=={'context','parameters'}:
            target.write_bytes(b'\xfe')
        return raw
    monkeypatch.setattr(host,'_json_bytes',late)
    with pytest.raises(ValueError,match='ending identity'):
        host.AgentHost().prepare_model_context(node(p),request(node(p)))


def test_source_helper_is_bound_before_external_dispatch(tmp_path):
    prepared=graph._capture_external_host(tmp_path)
    helper=Path(prepared['sources']['review_context']['path'])
    assert prepared['identity']['review_context_sha256']==hashlib.sha256(helper.read_bytes()).hexdigest()
    helper.write_bytes(helper.read_bytes()+b'\n# changed')
    with pytest.raises(graph.GraphError,match='prepared external host source changed'):
        graph._validate_prepared_external_host(prepared)


def test_no_allocating_read_of_over_limit_member(tmp_path,monkeypatch):
    p=packet(tmp_path/'packet',{'binary':b'\xff'})
    target=Path(p['path'])/'artifacts/binary.dat'
    original=Path.lstat
    def inflated(path):
        stat=original(path)
        if path==target:
            values=list(stat);values[6]=64*1024**2+1
            return os.stat_result(values)
        return stat
    monkeypatch.setattr(Path,'lstat',inflated)
    with pytest.raises((ValueError,host.HostFailure),match='custody|bounded'):
        host.AgentHost().prepare_model_context(node(p),request(node(p)))


def test_nul_containing_bytes_are_explicit_opaque_witness(tmp_path):
    p=packet(tmp_path/'packet',{'nul':b'\x00binary','judgment_request':b'{"scope":"diagnostic"}'})
    view=host.AgentHost().prepare_model_context(node(p),request(node(p)))['context']['review_packet']
    assert view['presentation']['binary_count']==1
    assert view['binary_witnesses'][0]['witness']['hex']==b'\x00binary'.hex()
    assert all(a['id']!='nul' for a in view['artifacts'])
