"""Actual Host/Graph source controls; no model/native calls."""
from copy import deepcopy
import hashlib,json
from pathlib import Path
import pytest
from ravel.workflow import agent_graph,agent_host as host,scientific_phase_allocation as phase
from ravel.workflow.execution import digest
from test_scientific_phase_allocation import request as phase_request

def pin(path):return {'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
class Control:
    def __init__(self):self.calls=[]
    def cancelled(self):return False
    def check_cancelled(self):pass
    def call(self,label,kind,request,function,output_tokens=0):self.calls.append(label);return function()
def setup(base,role='proposer'):
    path=base/'request.json';path.write_text(json.dumps(phase_request())+'\n')
    inputs=[{'id':'request',**pin(path)}]
    node={'id':'phase','kind':'tool','role':role,'depends_on':[],'inputs':inputs,'packet':None,'action':'scientific-phase','parameters':{'request_input':'request'},'max_attempts':1}
    request={'schema_version':1,'graph_id':'phase-control','graph_revision':'a'*64,'node_id':'phase','generation':1,'node_sha256':digest(node),'request_id':'b'*64,'input_artifacts':deepcopy(inputs),'packet':None,'dependencies':[]}
    return node,request
def test_real_host_enters_control_call_and_reserves_mandatory_checks(tmp_path):
    node,request=setup(tmp_path);control=Control();result=host.AgentHost().execute(node,request,control)
    assert control.calls==['scientific-phase'];assert result['value']['check_reservation']['calls']==3
    assert not result['execution_authorized'];assert not result['physics_validated']
@pytest.mark.parametrize('role',['critic','verifier'])
def test_blind_roles_do_not_receive_planning_data(tmp_path,role):
    node,request=setup(tmp_path,role);control=Control()
    with pytest.raises(host.HostFailure,match='blinded'):host.AgentHost().execute(node,request,control)
    assert not control.calls
def test_missing_policy_request_is_refused_before_tool_call(tmp_path):
    node,request=setup(tmp_path);node['inputs']=[];request['input_artifacts']=[];request['node_sha256']=digest(node);control=Control()
    with pytest.raises(host.HostFailure,match='explicit'):host.AgentHost().execute(node,request,control)
    assert not control.calls
def test_actual_graph_accounts_one_tool_reuses_then_refuses_policy_source_drift(tmp_path,monkeypatch):
    node,_=setup(tmp_path);specification={'schema_version':1,'graph_id':'phase-control','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':30,'max_reworks':0},'nodes':[node]}
    root=tmp_path/'graph';agent_graph.create(root,specification);adapter=host.AgentHost()
    assert agent_graph.execute(root,adapter,workers=1)['usage']['calls']==1
    assert agent_graph.execute(root,adapter,workers=1)['usage']['calls']==1
    altered=tmp_path/'altered-policy.py';altered.write_bytes(Path(phase.__file__).read_bytes()+b'\n# Source-drift engineering control\n');monkeypatch.setattr(phase,'__file__',str(altered))
    retained=agent_graph.status(root)
    with pytest.raises(agent_graph.GraphError,match='^completed generation source/request/host differs; explicit rework required$'):agent_graph.execute(root,adapter,workers=1)
    # The refusal precedes any reservation: no call is charged and the completed generation is untouched.
    assert agent_graph.status(root)==retained and retained['usage']['calls']==1
def test_actual_graph_refuses_changed_policy_usage_input_on_reuse(tmp_path):
    node,_=setup(tmp_path);specification={'schema_version':1,'graph_id':'phase-control','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':30,'max_reworks':0},'nodes':[node]}
    root=tmp_path/'graph';agent_graph.create(root,specification);adapter=host.AgentHost();assert agent_graph.execute(root,adapter,workers=1)['complete']
    path=tmp_path/'request.json';value=json.loads(path.read_text());value['usage']['calls']=5;path.write_text(json.dumps(value)+'\n')
    with pytest.raises(agent_graph.GraphError):agent_graph.execute(root,adapter,workers=1)
