"""Ordinary Host/graph route, no model or native transport."""
from copy import deepcopy
import hashlib,json,threading
from pathlib import Path
import pytest
from test_scientific_artifact import fixture,write,s
from ravel.workflow import execution,agent_graph as graph,agent_host as h

class Control:
    def __init__(self):self.cancel=threading.Event();self.calls=[]
    def check_cancelled(self):
        if self.cancel.is_set():raise RuntimeError('cancelled')
    def cancelled(self):return self.cancel.is_set()
    def call(self,label,kind,request,function,output_tokens=0):
        self.calls.append({'label':label,'kind':kind,'request':deepcopy(request)});return function()

def pin(p,identity):return {'id':identity,'path':str(p.resolve()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def prepared(tmp_path):
    specification,_=fixture(tmp_path);write(tmp_path/'request.json',specification)
    pins=[pin(tmp_path/'request.json','request')]+[pin(tmp_path/row['path'],'dep'+str(i)) for i,row in enumerate(s.input_pins(specification,base_dir=tmp_path))]
    return specification,pins
def node(pins,role='improver'):
    n={'id':'deliver','kind':'tool','role':role,'depends_on':[],'inputs':pins,'packet':None,
        'action':'scientific-artifact','parameters':{'request_input':'request'},'max_attempts':1}
    r={'schema_version':1,'graph_id':'deliver','graph_revision':'a'*64,'node_id':'deliver','generation':1,
        'node_sha256':execution.digest(n),'request_id':'b'*64,'input_artifacts':deepcopy(pins),'packet':None,'dependencies':[]}
    return n,r

def test_real_host_delivers_exact_numeric_artifact_once(tmp_path):
    _,pins=prepared(tmp_path);n,r=node(pins);c=Control();out=h.AgentHost().execute(n,r,c)
    assert out['value']['artifact']['efficiency']!=.09 and out['execution_authorized'] is False
    assert len(c.calls)==1 and c.calls[0]['request']['request_id']==r['request_id'] and c.calls[0]['request']['input_artifacts']==r['input_artifacts']

@pytest.mark.parametrize('missing',['prompt.txt','tool.json'])
def test_unbound_nested_task_or_tool_refuses_before_call(tmp_path,missing):
    _,pins=prepared(tmp_path);pins=[p for p in pins if Path(p['path']).name!=missing];n,r=node(pins);c=Control()
    with pytest.raises(h.HostFailure):h.AgentHost().execute(n,r,c)
    assert c.calls==[]

@pytest.mark.parametrize('role',['critic','verifier','physics_critic','skeptical_verifier'])
def test_construction_action_keeps_blind_review_roles_separate(tmp_path,role):
    _,pins=prepared(tmp_path);n,r=node(pins,role);c=Control()
    with pytest.raises(h.HostFailure):h.AgentHost().execute(n,r,c)
    assert c.calls==[]

def test_real_graph_resume_preserves_one_artifact_call(tmp_path):
    _,pins=prepared(tmp_path);n,_=node(pins)
    specification={'schema_version':1,'graph_id':'typed-artifact','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':30,'max_reworks':0},'nodes':[n]}
    root=tmp_path/'graph';graph.create(root,specification);host=h.AgentHost()
    first=graph.execute(root,host);reference=first['nodes']['deliver']['result'];raw=(root/reference['path']).read_bytes()
    second=graph.execute(root,host)
    assert first['complete'] is True and second['usage']==first['usage']=={'calls':1,'reserved_output_tokens':0}
    assert second['nodes']['deliver']['result']==reference and (root/reference['path']).read_bytes()==raw
    assert second['execution_authorized'] is False

def test_host_identity_binds_serializer_and_existing_pin_reader():
    sources=h.AgentHost().identity['sources']
    assert sources['ravel.workflow.scientific_artifact']==hashlib.sha256(Path(s.__file__).read_bytes()).hexdigest()
    assert 'ravel.workflow.candidate_experiments' in sources
