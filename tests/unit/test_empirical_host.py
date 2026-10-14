"""Real private AgentHost.execute entrypoints; no model, native or child calls."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import threading
import pytest
from test_empirical_search import e, write, contract, population, advance, request as contrast_request
from ravel.workflow import execution, agent_graph as graph

MODULE=Path(__file__).resolve().parents[2]/'src/ravel/workflow/agent_host.py'
spec=importlib.util.spec_from_file_location('ravel.workflow.empirical_host_candidate',MODULE)
h=importlib.util.module_from_spec(spec);sys.modules[spec.name]=h;spec.loader.exec_module(h)


class Control:
    def __init__(self):self.cancel=threading.Event();self.calls=[]
    def check_cancelled(self):
        if self.cancel.is_set():raise RuntimeError('cancelled')
    def cancelled(self):return self.cancel.is_set()
    def call(self,label,kind,request,function,output_tokens=0):
        self.calls.append({'label':label,'kind':kind,'request':deepcopy(request)})
        return function()


def pin(path,identity):
    return {'id':identity,'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def node(pins,*,action='empirical-next',role='improver',parameters=None):
    n={'id':'choose','kind':'tool','role':role,'depends_on':[],'inputs':pins,'packet':None,
        'action':action,'parameters':parameters or {'request_input':'request'},'max_attempts':1}
    req={'schema_version':1,'graph_id':'calibration','graph_revision':'a'*64,'node_id':'choose',
        'generation':1,'node_sha256':execution.digest(n),'request_id':'b'*64,
        'input_artifacts':deepcopy(pins),'packet':None,'dependencies':[]}
    return n,req


def prepared(tmp_path):
    plan,ledger=population(tmp_path,[('seed',None,'seed',2,['grouping']),('drop','seed','ablation',6,[])],
        values={('seed','blind'):987654321,('seed','whole'):123456789})
    req={'schema_version':1,'contract':contract(component_experiments=True),
        'plan':write(tmp_path/'plan.json',plan),'ledger':ledger,'previous':None}
    write(tmp_path/'request.json',req)
    deps=e.input_pins(req,base_dir=tmp_path)
    pins=[pin(tmp_path/'request.json','request')]+[pin(tmp_path/r['path'],'dep'+str(i)) for i,r in enumerate(deps)]
    return req,pins


def test_actual_host_route_generates_next_operation_without_heldout_numerical_answers(tmp_path):
    req,pins=prepared(tmp_path);n,r=node(pins);c=Control()
    result=h.AgentHost().execute(n,r,c)
    assert len(c.calls)==1 and c.calls[0]['kind']=='tool'
    assert result['action']=='empirical-next'
    value=result['value'];assert value['decision']['kind']=='improve_component'
    assert value['decision']['parent_candidate_id']=='seed'
    assert '987654321' not in json.dumps(value) and '123456789' not in json.dumps(value)
    assert 'intake' not in value and 'ledger' not in value
    assert value['independent_context_or_os_blinding_checked'] is False
    assert result['execution_authorized'] is result['physics_validated'] is False


@pytest.mark.parametrize('reverse_repeats',[False,True])
def test_actual_host_component_target_is_stable_with_repeated_contrasts(tmp_path,reverse_repeats):
    contrasts=[('g_high','seed','ablation',10,['weighting']),
        ('g_low','seed','ablation',2,['weighting'])]
    if reverse_repeats:contrasts.reverse()
    plan,ledger=population(tmp_path,[('seed',None,'seed',1,['grouping','weighting']),
        *contrasts,('weight','seed','ablation',5,['grouping'])],values={('seed','blind'):987654321})
    specification={'schema_version':1,'contract':contract(component_experiments=True),
        'plan':write(tmp_path/'plan.json',plan),'ledger':ledger,'previous':None}
    write(tmp_path/'request.json',specification)
    dependencies=e.input_pins(specification,base_dir=tmp_path)
    pins=[pin(tmp_path/'request.json','request')]+[pin(tmp_path/p['path'],'dep'+str(i))
        for i,p in enumerate(dependencies)]
    n,r=node(pins);control=Control();result=h.AgentHost().execute(n,r,control)
    assert len(control.calls)==1
    assert result['value']['decision']['component_id']=='grouping'
    assert len(result['value']['decision']['development_history'])==4
    assert result['value']['usage']['experiment_attempts']==12
    assert '987654321' not in json.dumps(result['value'])


@pytest.mark.parametrize('which',['check','result','request','old-round'])
def test_missing_nested_pin_refuses_before_host_operation(tmp_path,which):
    req,pins=prepared(tmp_path)
    if which=='old-round':
        old=e.advance_request(req,base_dir=tmp_path);prior=write(tmp_path/'old.json',old)
        req['previous']=prior;write(tmp_path/'request.json',req)
        pins[0]=pin(tmp_path/'request.json','request')
        # Its extra immutable round must be bound even when all underlying facts already are.
    else:
        target='request.json' if which=='request' else req['plan']
        if which!='request':
            plan=json.loads((tmp_path/target['path']).read_text());target=plan['trials'][0][which]['path']
        pins=[p for p in pins if Path(p['path']).name!=target]
    n,r=node(pins);c=Control()
    with pytest.raises(h.HostFailure):h.AgentHost().execute(n,r,c)
    assert c.calls==[]


def test_old_round_and_current_plan_dependencies_are_all_normal_inputs(tmp_path):
    req,pins=prepared(tmp_path)
    old=e.advance_request(req,base_dir=tmp_path);req['previous']=write(tmp_path/'old.json',old)
    write(tmp_path/'request.json',req)
    deps=e.input_pins(req,base_dir=tmp_path)
    pins=[pin(tmp_path/'request.json','request')]+[pin(tmp_path/d['path'],'dep'+str(i)) for i,d in enumerate(deps)]
    n,r=node(pins);result=h.AgentHost().execute(n,r,Control())
    assert result['value']['round']==2 and result['value']['usage']['experiment_attempts']==6


@pytest.mark.parametrize('role',['critic','verifier','physics_critic','skeptical_verifier'])
def test_generation_tool_cannot_consume_a_blind_review_role(tmp_path,role):
    req,pins=prepared(tmp_path);n,r=node(pins,role=role);c=Control()
    with pytest.raises(h.HostFailure):h.AgentHost().execute(n,r,c)
    assert c.calls==[]


def test_source_followup_uses_actual_host_entry_and_complete_pinned_source(tmp_path):
    req,pins=prepared(tmp_path);record=e.advance_request(req,base_dir=tmp_path)
    write(tmp_path/'round.json',record)
    plan=json.loads((tmp_path/req['plan']['path']).read_text());cr=contrast_request(tmp_path,plan)
    write(tmp_path/'contrast.json',cr)
    pins=[p for p in pins if p['id']!='request']+[pin(tmp_path/'contrast.json','contrast'),pin(tmp_path/'round.json','round')]
    for i,row in enumerate(e.cc.input_pins(cr)):pins.append(pin(tmp_path/row['path'],'source'+str(i)))
    n,r=node(pins,action='empirical-component-prepare',parameters={'request_input':'contrast','round_input':'round'})
    result=h.AgentHost().execute(n,r,Control())
    assert result['value']['selected_action']['component_id']=='grouping'
    assert 'return x + 1' in result['value']['preparation']['controlled_source']
    out=tmp_path/'materialized'
    materialized=e.cc.materialize(result['value']['preparation'],out,tmp_path)
    assert Path(materialized['source_path']).is_file() and materialized['executed'] is False
    assert (tmp_path/'seed.py').read_text()=='def estimator(x):\n    return x\n'


def test_source_followup_requires_bound_license_and_denominator_history(tmp_path):
    req,pins=prepared(tmp_path);record=e.advance_request(req,base_dir=tmp_path)
    write(tmp_path/'round.json',record);plan=json.loads((tmp_path/req['plan']['path']).read_text())
    cr=contrast_request(tmp_path,plan);write(tmp_path/'contrast.json',cr)
    pins=[p for p in pins if p['id']!='request']+[pin(tmp_path/'contrast.json','contrast'),pin(tmp_path/'round.json','round')]
    for i,row in enumerate(e.cc.input_pins(cr)[:2]):pins.append(pin(tmp_path/row['path'],'source'+str(i)))
    n,r=node(pins,action='empirical-component-prepare',parameters={'request_input':'contrast','round_input':'round'})
    c=Control()
    with pytest.raises(h.HostFailure):h.AgentHost().execute(n,r,c)
    assert c.calls==[]


def test_host_identity_binds_controller_and_existing_comparison_code(tmp_path):
    identity=h.AgentHost().identity
    assert identity['sources']['ravel.workflow.empirical_search']==hashlib.sha256(Path(e.__file__).read_bytes()).hexdigest()
    assert 'ravel.workflow.candidate_experiments' in identity['sources']


def test_actual_graph_route_retains_a_tool_receipt_and_resume_does_not_repeat(tmp_path):
    req,pins=prepared(tmp_path);n,_=node(pins)
    spec={'schema_version':1,'graph_id':'measured-controller','budget':{'max_nodes':1,'max_calls':1,
        'max_output_tokens':0,'max_wall_seconds':30,'max_reworks':0},'nodes':[n]}
    root=tmp_path/'graph';graph.create(root,spec)
    adapter=h.AgentHost();first=graph.execute(root,adapter)
    assert first['complete'] is True and first['usage']=={'calls':1,'reserved_output_tokens':0}
    reference=first['nodes']['choose']['result'];raw=(root/reference['path']).read_bytes()
    second=graph.execute(root,adapter)
    assert second['usage']==first['usage'] and second['nodes']['choose']['result']==reference
    assert (root/reference['path']).read_bytes()==raw
    assert second['execution_authorized'] is False


def test_next_proposer_context_has_only_explicit_generation_projection(tmp_path):
    req,pins=prepared(tmp_path);n,r=node(pins)
    view=h.AgentHost().execute(n,r,Control())['value'];write(tmp_path/'public.json',view)
    public=pin(tmp_path/'public.json','measured-public-context')
    model={'id':'proposal','kind':'model','role':'improver','depends_on':[],'inputs':[public],
        'packet':None,'action':'responses','parameters':{'instructions':'Return a structured source proposal using the declared measured component target.',
            'model':'nonexecuted-context-control','reasoning_effort':'high','max_output_tokens':128,'output_schema':None},'max_attempts':1}
    request={'request_id':'c'*64,'packet':None,'input_artifacts':[public]}
    prepared_context=h.AgentHost().prepare_model_context(model,request)
    text=json.dumps(prepared_context)
    assert '987654321' not in text and '123456789' not in text
    assert 'grouping' in text and 'complete-census' in text
    assert len(prepared_context['context']['input_artifacts'])==1
