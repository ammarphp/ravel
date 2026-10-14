"""Joined original-parent / task-derived blueprint / ordinary-plan control.

Supplied fixtures and inert runtime metadata only; no model/native/science worker.
The original human scope remains open after a concrete component proposal.
"""
from copy import deepcopy
from pathlib import Path
import pytest
from ravel.workflow import research_cycle as cycle,research_blueprint as blueprint,research_followup as follow,agent_host,execution,science,task_completion
from ravel.workflow.state_io import read_json
from test_task_completion import goal,PROMPT,request as completion_request
import test_research_blueprint as bp


def test_task_derived_blueprint_real_unapproved_plan_keeps_original_parent_open(tmp_path,monkeypatch):
    _,parent_pin=goal(tmp_path)
    binding={'contract':parent_pin,'assignment_id':'summary-child'}
    original_contract=bp.contract;original_experiment=bp.experiment
    def bound_contract(base):
        c=original_contract(base);c['goal_binding']=deepcopy(binding);return c
    def bound_experiment(base,*args,**kwargs):
        e=original_experiment(base,*args,**kwargs);path=Path(e['study']['path']);spec=read_json(path)
        spec['goal_binding']=deepcopy(binding);e['study']=bp.write(path,spec);return e
    monkeypatch.setattr(bp,'contract',bound_contract);monkeypatch.setattr(bp,'experiment',bound_experiment)
    monkeypatch.setattr(execution,'runtime_context',lambda:{'explicit_inert_source_control':True,'environment_sha256':execution.digest(execution.runtime_environment())})
    root,request_pin,choice_pin,document,_=bp.case(tmp_path,monkeypatch,concrete_baseline=True)
    graph=tmp_path/'original-task-blueprint-graph'
    assert cycle.execute_graph(root,graph,bp.graph_spec(root,request_pin,choice_pin,document),agent_host.AgentHost())['complete']
    result=cycle._graph_result(graph,'compile')['value']['value']
    portfolio=read_json(result['portfolio']['path'])
    for e in portfolio['experiments']:assert read_json(e['study']['path'])['goal_binding']==binding
    admission=tmp_path/'original-task-blueprint-admission'
    graph_spec=blueprint.admission_spec(root,graph,node_id='compile',graph_id='bound-component-admission',max_wall_seconds=30)
    assert cycle.execute_graph(root,admission,graph_spec,agent_host.AgentHost())['complete']
    blueprint.adopt_portfolio(root,admission,node_id='admit',context_pin=result['context'])
    rd=tmp_path/'unapproved-component-plan';cycle.prepare_experiment(root,'paired',rd)
    science.verify_plan(rd,approved=False)
    assert read_json(rd/science.SPEC)['goal_binding']==binding
    assert not (rd/science.APPROVAL).exists() and not (rd/'execution_attempt.json').exists()
    state=cycle.status(root)
    assert state['parent_task']['original_request']==PROMPT and state['parent_task']['contract']==parent_pin
    assert not state['parent_task_accepted'] and not state['execution_authorized']
    original_obligations=[r['id'] for r in state['parent_task']['effective_obligations']]
    assert original_obligations==['original-request','atlas','cms','domain']
    progress=task_completion.evaluate(completion_request(tmp_path,parent_pin,[]),base_dir=tmp_path)
    assert progress['unmet_obligation_ids']==original_obligations and not progress['parent_task_accepted']
    assert not list((rd/'outputs').rglob('result.json'))
