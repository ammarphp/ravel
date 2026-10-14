from pathlib import Path
from copy import deepcopy
from test_scientific_judgment import observed_role_boundary
from test_scientific_judgment import cycle,prepare,complete,FakeHost
from test_physics_review import run
from ravel.workflow import task_completion as tc,route_prompt,research_cycle as rc,agent_graph as graph,scientific_judgment as j,physics_review as review
from ravel.workflow.state_io import atomic_json

def test_real_create_bound_parent_then_prepared_role_retains_original_and_cost(cycle,tmp_path,monkeypatch, observed_role_boundary):
 prompt='Prepare a bounded interpretation study while retaining the whole original question.'
 task=route_prompt.route(prompt);requirements=tc.initial_requirements(prompt)
 requirements['assignments']=[{'id':'judgment-child','purpose':'Review only the observed study; leave the original parent question open.','coverage':[{'obligation_id':row['id'],'criteria':deepcopy(row['criteria'])} for row in requirements['obligations']]}]
 task['task_requirements']=requirements
 path=tmp_path/'parent/inputs/task_contract.json';path.parent.mkdir(parents=True);atomic_json(path,task)
 goal={'contract':rc._pin(path),'assignment_id':'judgment-child'}
 request=tmp_path/'context-request.json';atomic_json(request,{'fixture':'pure ordinary context compiler stand-in'})
 monkeypatch.setattr(rc.scientific_context,'compile_context',lambda request,base:{'request_sha256':rc.ce.digest(request),'steps':[]})
 campaign=tmp_path/'initially-bound-campaign'
 state=rc.create(campaign,{'schema_version':1,'id':'initial-parent-review','question':prompt,'scope':'Synthetic source join only','context_request':rc._pin(request),'premises':[],'budget':{'calls':3,'output_tokens':3072,'wall_seconds':60,'native_attempts':0},'max_experiments':1,'exploration_every':1,'required_experiments':[],'goal_binding':goal},base_dir=tmp_path, evaluation_harness=True)
 assert state['parent_task']==tc.binding_projection(goal,base_dir=tmp_path)
 state['experiments'].append({'id':'observed','rundir':str(cycle),'observation':{'kind':'synthetic terminal record'}})
 rc._commit(campaign,state,'fixture_observed_run')
 binding=prepare(cycle,tmp_path/'role','critic',campaign=campaign,experiment='observed')
 assert graph._load(Path(binding['graph_root']))[0]['goal_binding']==goal
 complete(cycle,binding,FakeHost())
 _,current=rc._load(campaign)
 assert rc._usage(current)=={'calls':1,'output_tokens':1024,'wall_seconds':20,'native_attempts':0}
 assert current['parent_task']==state['parent_task'] and review.status(cycle)['state']=='awaiting_review'
 assert j.next_step(cycle)['role']=='verifier'
