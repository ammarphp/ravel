"""Exact P04 derived binding with real adopted request/campaign validation.

The integrated ``operations.plan_step`` and ``graph._authorize`` run against protected-store fakes and inert
preparation only. No provider, native worker, generation, or approval labels supply evidence.
"""
from copy import deepcopy
import json
from pathlib import Path
import types

import pytest

from ravel.controller.step import graph as step_graph, operations
from ravel.controller.step.services import StepHold as Hold
from ravel.workflow import candidate_experiments as ce, research_cycle as cycle
from ravel.workflow import research_orchestrator as orchestration
from p11_fakes import FakeRunStore, InertReviewHost
from test_langgraph_research_orchestration import open_fixture


@pytest.fixture
def peer():
    return operations


@pytest.fixture
def bound_parent(tmp_path):
    base=tmp_path/'scientific-run';base.mkdir()
    request,_,_,_=open_fixture(base)
    campaign=base/'campaign'
    orchestration._open_plan(campaign,request,campaign/'coordinator',host=InertReviewHost())
    parent={'id':'campaign','kind':'subgraph','graph':{'id':'research.loop','instance':{}},
            'parameters':{'research_request':request,'campaign':str(campaign)}}
    plan={'steps':[parent]};plan['sha256']=ce.digest(plan)
    store=FakeRunStore('derived-control',root=tmp_path/'protected')
    entry={'parent_step':deepcopy(parent),'parent_step_sha256':ce.digest(parent),
           'parent_plan_sha256':plan['sha256'],'request':deepcopy(request),'campaign':str(campaign)}
    identity=store.append('research-subgraph-entry',entry)
    step={'id':'research-role-one','kind':'author','role':'physics-critic','operation':None,
          'parameters':{'research_node':{'id':'critic'}},'budget':{'wall_seconds':30},
          'inputs':[],'outputs':[],'depends_on':[]}
    derived={'step':deepcopy(step),'step_sha256':ce.digest(step),'parent_entry_id':identity,
             'parent_plan_sha256':plan['sha256']}
    store.append('research-derived-step',derived)
    context={'run_dir':str(base),'plan_sha256':plan['sha256']}
    return store,plan,step,context,campaign


@pytest.fixture
def use_parent(monkeypatch):
    def use(peer,bound_parent):
        store,plan,step,context,campaign=bound_parent
        # The only plan service fake: exact current approved parent document.
        monkeypatch.setattr(peer,'current_plan',lambda actual_store,actual_context:deepcopy(plan))
        return store,plan,step,context,campaign
    return use


def test_exact_protected_child_binds_to_original_approved_parent(peer,bound_parent,use_parent):
    store,plan,step,context,_=use_parent(peer,bound_parent)
    actual,sha,kind=peer.plan_step(store,step,context)
    assert actual==step and actual is not step
    assert sha==plan['sha256'] and kind=='derived_research_step'
    assert peer.plan_step(store,plan['steps'][0],context)[2]=='plan_step'


@pytest.mark.parametrize('damage',['step','step_digest','plan','entry_id','missing_entry','parent_bytes',
    'parent_digest','parent_plan','parent_kind','parent_graph','request_pin','request_bytes','campaign_binding',
    'request_contract','kind','context_only','malformed_derived','malformed_entry'])
def test_missing_or_forged_lineage_request_and_campaign_hold(peer,bound_parent,use_parent,damage):
    store,plan,step,context,campaign=use_parent(peer,bound_parent)
    entry=store.rows[0]['record'];derived=store.rows[1]['record']
    if damage=='step':step['parameters']['different']='forged'
    elif damage=='step_digest':derived['step_sha256']='0'*64
    elif damage=='plan':plan['sha256']='0'*64
    elif damage=='entry_id':derived['parent_entry_id']='not-a-record'
    elif damage=='missing_entry':store.rows.pop(0)
    elif damage=='parent_bytes':entry['parent_step']['parameters']['different']='forged'
    elif damage=='parent_digest':entry['parent_step_sha256']='0'*64
    elif damage=='parent_plan':entry['parent_plan_sha256']='0'*64
    elif damage=='parent_kind':entry['parent_step']['kind']='author'
    elif damage=='parent_graph':entry['parent_step']['graph']['id']='other.loop'
    elif damage=='request_pin':entry['request']['sha256']='0'*64
    elif damage=='request_bytes':Path(entry['request']['path']).write_text('{}')
    elif damage=='campaign_binding':entry['campaign']=str(campaign/'coordinator')
    elif damage=='request_contract':
        _,state=cycle._load(campaign);state['contract']['question']='different original assignment'
        cycle._commit(campaign,state,'fixture_contract_tamper')
    elif damage=='kind':
        step['kind']='subgraph';derived.update(step=deepcopy(step),step_sha256=ce.digest(step))
    elif damage=='malformed_derived':store.rows[1]['record']=['malformed protected record']
    elif damage=='malformed_entry':store.rows[0]['record']=['malformed protected entry']
    elif damage=='context_only':
        context.update(research_derived_step=deepcopy(derived),research_subgraph_entry=deepcopy(entry));store.rows=[]
    with pytest.raises(Hold):peer.plan_step(store,step,context)


@pytest.mark.parametrize('damage',[None,'own_checkin1','inherit_budget','inherit_authority','route'])
def test_derived_child_route_keeps_its_own_approval_and_parent_bounds(peer,bound_parent,use_parent,damage):
    store,plan,step,context,_=use_parent(peer,bound_parent)
    step.update(kind='route',route='study',parameters={'own_checkin1':True,'inherit_budget':True,'inherit_authority':True})
    if damage=='route':step['route']='other'
    elif damage:step['parameters'][damage]=False
    store.rows[1]['record'].update(step=deepcopy(step),step_sha256=ce.digest(step))
    if damage:
        with pytest.raises(Hold):peer.plan_step(store,step,context)
    else:assert peer.plan_step(store,step,context)[2]=='derived_research_step'


def test_operator_authority_and_executor_checks_follow_derived_binding(peer,bound_parent,use_parent,monkeypatch):
    store,plan,step,context,_=use_parent(peer,bound_parent)
    peer.plan_step(store,step,context)
    class Authority:
        calls=[]
        def authorize_effect(self,actual_store,effect):
            self.calls.append(effect)
            raise ValueError('operator has not approved this budget effect')
    authority=Authority()
    monkeypatch.setattr(step_graph,'module',lambda name:authority)
    with pytest.raises(Hold,match='authority_effect_invalid'):
        step_graph._authorize(store,context,step,{'wall_seconds':30})
    assert authority.calls[0]['pins']['plan_sha256']==plan['sha256']
    assert authority.calls[0]['requires_go'] is True
    assert authority.calls[0]['budget']=={'wall_seconds':30}
    assert peer.executor_errors({'operation':'supplied-operation','role':'wrong-role'},
        table={'operations':{'supplied-operation':'original-executor'}})[0]['code']=='executor_role_mismatch'
