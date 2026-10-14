"""Actual Host/graph entry controls for executable adaptation context."""
from copy import deepcopy
import hashlib,importlib.util,json,sys,threading
from pathlib import Path
import pytest
from test_adaptation_reuse import a,write,setup
from ravel.workflow import execution,agent_graph as graph
MODULE=Path(__file__).resolve().parents[2]/'src/ravel/workflow/agent_host.py'
spec=importlib.util.spec_from_file_location('ravel.workflow.adaptation_host_candidate',MODULE)
h=importlib.util.module_from_spec(spec);sys.modules[spec.name]=h;spec.loader.exec_module(h)

class Control:
    def __init__(self):self.cancel=threading.Event();self.calls=[]
    def check_cancelled(self):
        if self.cancel.is_set():raise RuntimeError('cancelled')
    def cancelled(self):return self.cancel.is_set()
    def call(self,label,kind,request,function,output_tokens=0):
        self.calls.append({'label':label,'kind':kind,'request':deepcopy(request)});return function()

def pin(p,identity):return {'id':identity,'path':str(p.resolve()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def prepared(tmp_path):
    request,_=setup(tmp_path);write(tmp_path/'request.json',request)
    pins=[pin(tmp_path/'request.json','request')]+[pin(Path(row['path']),'dep'+str(i)) for i,row in enumerate(a.input_pins(request,base_dir=tmp_path))]
    return request,pins

def node(pins,*,role='improver',action='adaptation-retrieve',parameters=None):
    node={'id':'reuse','kind':'tool','role':role,'depends_on':[],'inputs':pins,'packet':None,'action':action,
        'parameters':parameters or {'request_input':'request'},'max_attempts':1}
    request={'schema_version':1,'graph_id':'reuse','graph_revision':'a'*64,'node_id':'reuse','generation':1,
        'node_sha256':execution.digest(node),'request_id':'b'*64,'input_artifacts':deepcopy(pins),'packet':None,'dependencies':[]}
    return node,request

def test_real_host_retrieves_and_prepares_new_executable_source(tmp_path):
    request,pins=prepared(tmp_path);n,r=node(pins);c=Control()
    record=h.AgentHost().execute(n,r,c)['value'];assert len(c.calls)==1
    assert c.calls[0]['request']['request_id']==r['request_id'] and c.calls[0]['request']['input_artifacts']==r['input_artifacts']
    assert record['selected'][0]['id']=='group_cross_terms'
    write(tmp_path/'retrieval.json',record);write(tmp_path/'bindings.json',{'entry_id':'group_cross_terms','bindings':{'function':'challenger'}})
    pins=[p for p in pins if p['id']!='request']+[pin(tmp_path/'retrieval.json','retrieval'),pin(tmp_path/'bindings.json','bindings')]
    n,r=node(pins,action='adaptation-prepare',parameters={'retrieval_input':'retrieval','bindings_input':'bindings'})
    proposed=h.AgentHost().execute(n,r,c)['value'];assert len(c.calls)==2
    space={};exec(compile(proposed['controlled_source'],'source-proposal','exec'),space)
    assert space['challenger']([('a',2),('a',3),('b',-2)])==29
    assert proposed['source_obligations']==request['task']['source_obligations']
    assert proposed['old_votes_carried']==[] and proposed['scientific_acceptance'] is False

@pytest.mark.parametrize('missing',['catalog.json','group_program.py','measurement.json'])
def test_incomplete_source_or_observation_inventory_refuses_before_host_call(tmp_path,missing):
    _,pins=prepared(tmp_path);pins=[p for p in pins if Path(p['path']).name!=missing]
    n,r=node(pins);control=Control()
    with pytest.raises(h.HostFailure):h.AgentHost().execute(n,r,control)
    assert control.calls==[]

@pytest.mark.parametrize('role',['critic','verifier','physics_critic','skeptical_verifier'])
def test_retrieval_is_construction_context_and_keeps_blind_roles_separate(tmp_path,role):
    _,pins=prepared(tmp_path);n,r=node(pins,role=role);control=Control()
    with pytest.raises(h.HostFailure):h.AgentHost().execute(n,r,control)
    assert control.calls==[]

def test_actual_graph_resume_reuses_one_context_operation_without_new_call(tmp_path):
    _,pins=prepared(tmp_path);n,_=node(pins)
    specification={'schema_version':1,'graph_id':'adaptation-graph','budget':{'max_nodes':1,'max_calls':1,
        'max_output_tokens':0,'max_wall_seconds':30,'max_reworks':0},'nodes':[n]}
    root=tmp_path/'graph';graph.create(root,specification);host=h.AgentHost()
    first=graph.execute(root,host);reference=first['nodes']['reuse']['result'];raw=(root/reference['path']).read_bytes()
    second=graph.execute(root,host)
    assert first['complete'] is True and first['usage']==second['usage']=={'calls':1,'reserved_output_tokens':0}
    assert second['nodes']['reuse']['result']==reference and (root/reference['path']).read_bytes()==raw
    assert second['execution_authorized'] is False

def test_host_identity_binds_retrieval_and_both_existing_dependencies():
    sources=h.AgentHost().identity['sources']
    assert sources['ravel.workflow.adaptation_reuse']==hashlib.sha256(Path(a.__file__).read_bytes()).hexdigest()
    assert 'ravel.workflow.candidate_experiments' in sources and 'ravel.workflow.constructive_contrast' in sources
