"""Public tool/graph source controls, with supplied synthetic evidence only."""
from copy import deepcopy
import hashlib,json
from pathlib import Path
import pytest
from ravel.workflow import agent_graph,agent_host as host, scientific_report as sr
from ravel.workflow.execution import digest
from test_scientific_report import fixture,draft,attach_context

def pin(path):return {'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
def write(path,data):path.write_text(json.dumps(data,allow_nan=False)+'\n');return pin(path)
class Control:
    def __init__(self):self.calls=[]
    def cancelled(self):return False
    def check_cancelled(self):pass
    def call(self,label,kind,request,function,output_tokens=0):self.calls.append(label);return function()

def setup(base,action='report-revise',role='proposer',context=False):
    r=fixture(base)
    if context:attach_context(base,r)
    p=base/'request.json';write(p,r)
    old=draft(base,r);old['slots']['table/point0/0']['value']=.225
    dp=base/'draft.json';write(dp,old)
    paths={'request':p,**({'draft':dp} if action=='report-revise' else {})}
    for i, row in enumerate(sr.input_pins(r,base_dir=base)):
        raw=Path(row['path']);paths['dependency'+str(i)]=raw if raw.is_absolute() else base/raw
    inputs=[{'id':key,**pin(path)} for key,path in paths.items()]
    parameters={'request_input':'request',**({'draft_input':'draft'} if action=='report-revise' else {})}
    node={'id':'report','kind':'tool','role':role,'depends_on':[],'inputs':inputs,'packet':None,'action':action,'parameters':parameters,'max_attempts':1}
    request={'schema_version':1,'graph_id':'report-control','graph_revision':'a'*64,'node_id':'report','generation':1,'node_sha256':digest(node),'request_id':'b'*64,'input_artifacts':deepcopy(inputs),'packet':None,'dependencies':[]}
    return r,node,request

@pytest.mark.parametrize('action',['scientific-report','report-revise'])
def test_actual_host_tool_materializes_report_and_retains_discrepancies(tmp_path,action):
    _,node,request=setup(tmp_path,action,context=True);control=Control()
    output=host.AgentHost().execute(node,request,control)['value']
    assert '| -0.225 |' in output['report_text'] and output['context_sha256']
    assert control.calls==[action]
    if action=='report-revise':assert output['inspection']['changes'][0]['before']==.225
    assert not output['scientific_acceptance']

@pytest.mark.parametrize('omit',['basis.txt','probe.json','api.py','context.json'])
def test_all_actual_tool_basis_context_and_history_dependencies_must_be_graph_inputs(tmp_path,omit):
    _,node,request=setup(tmp_path,context=True)
    node['inputs']=[x for x in node['inputs'] if Path(x['path']).name!=omit]
    request['input_artifacts']=deepcopy(node['inputs']);request['node_sha256']=digest(node)
    control=Control()
    with pytest.raises(host.HostFailure):host.AgentHost().execute(node,request,control)
    assert not control.calls

@pytest.mark.parametrize('role',['critic','verifier'])
def test_blinded_roles_do_not_receive_report_constructor_corpus(tmp_path,role):
    _,node,request=setup(tmp_path,role=role);control=Control()
    with pytest.raises(host.HostFailure,match='blinded'):host.AgentHost().execute(node,request,control)
    assert not control.calls

@pytest.mark.parametrize('module',[sr,sr.sa,sr.ce,sr.sc,sr.sc.analysis_sources,sr.sc.state_io])
def test_actual_graph_charges_one_tool_reuses_then_rejects_consumed_dependency_drift(tmp_path,monkeypatch,module):
    _,node,_=setup(tmp_path,context=True)
    specification={'schema_version':1,'graph_id':'report-control','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':30,'max_reworks':0},'nodes':[node]}
    root=tmp_path/'graph';agent_graph.create(root,specification);adapter=host.AgentHost()
    first=agent_graph.execute(root,adapter,workers=1)
    assert first['complete'] and first['usage']['calls']==1
    assert agent_graph.execute(root,adapter,workers=1)['usage']['calls']==1
    different=tmp_path/'different.py';different.write_bytes(Path(module.__file__).read_bytes()+b'\n# Actual dependency identity adverse control\n')
    monkeypatch.setattr(module,'__file__',str(different))
    retained=agent_graph.status(root)
    with pytest.raises(agent_graph.GraphError,match='^completed generation source/request/host differs; explicit rework required$'):agent_graph.execute(root,adapter,workers=1)
    # The refusal precedes any reservation: no call is charged and the completed generation is untouched.
    assert agent_graph.status(root)==retained and retained['usage']['calls']==1

def test_reuse_refuses_changed_supplied_scientific_output(tmp_path):
    _,node,_=setup(tmp_path)
    specification={'schema_version':1,'graph_id':'report-control','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':30,'max_reworks':0},'nodes':[node]}
    root=tmp_path/'graph';agent_graph.create(root,specification);adapter=host.AgentHost()
    assert agent_graph.execute(root,adapter,workers=1)['complete']
    (tmp_path/'probe.json').write_text('{}')
    with pytest.raises(agent_graph.GraphError):agent_graph.execute(root,adapter,workers=1)
