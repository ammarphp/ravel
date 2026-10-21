"""Whole application source controls, supplied actors, zero external launches.

Actual ordinary graphs/cycle/planning are exercised. Actor outputs, review
fixtures and native returns are fabricated controls, never scientific evidence.
"""
from copy import deepcopy
import ast
import hashlib
import json
import platform
from pathlib import Path
import subprocess
import pytest
from ravel.workflow import sfitter_application as a, agent_graph as g, agent_host as ah
from ravel.workflow import task_completion as tc, route_prompt, research_cycle as cycle
from ravel.workflow.state_io import read_json
from test_sfitter_adapter import workflow_fixture, save, pin, UP
from test_sfitter_conductor import SuppliedHost, proposal, lead
from test_research_cycle import contract as cycle_contract, hypotheses, write
from test_source_tables import make as tables
PROCESS_ATTEMPTS=[]


@pytest.fixture(autouse=True)
def no_process(monkeypatch):
    def denied(*args,**kwargs):
        PROCESS_ATTEMPTS.append(repr(args));raise AssertionError('external launch forbidden in source controls')
    for name in ('Popen','run','check_output','check_call','call'):
        monkeypatch.setattr(subprocess,name,denied)
    monkeypatch.setattr(platform,'platform',lambda:'explicit-no-process-source-control')


def fixture(base):
    src=base/'inputs';src.mkdir()
    wf,docs,_=workflow_fixture(src);wf['model']={'name':'explicit-mock','reasoning_effort':'high','max_output_tokens':4096}
    wp=save(src/'workflow.json',wf)
    prompt='Construct a complete SMEFT study of all requested bins, keeping production and domain evidence explicit.'
    parent=route_prompt.route(prompt);req=tc.initial_requirements(prompt)
    req['assignments']=[{'id':'sfitter-app','purpose':'Whole application source control, not scientific closure.',
       'coverage':[{'obligation_id':r['id'],'criteria':deepcopy(r['criteria'])} for r in req['obligations']]}]
    parent['task_requirements']=req;pp=save(src/'parent.json',parent)
    pp['size']=Path(pp['path']).stat().st_size
    goal={'contract':pp,'assignment_id':'sfitter-app'}
    cp=save(src/'create.json',{'schema_version':1,'label':'application-control','workflow':wp,
                            'goal_binding':goal,'parent_session':None})
    session=a.create(cp,src,base/'session')
    return wf,docs,wp,goal,session


def fork_request(base,wp,goal,session):
    return save(base/'inputs/fork.json',{'schema_version':1,'label':'fork','workflow':wp,
                          'goal_binding':goal,'parent_session':session})


def test_complete_original_release_and_ordinary_launcher_session_shape(tmp_path):
    wf,_,_,goal,session=fixture(tmp_path)
    catalogue=a.registry(wf,tmp_path/'inputs')
    assert len(catalogue['actors'])==62 and len(catalogue['skills'])==18
    root=Path(session['path']).parent;forest=a._census(root)
    for tree in ('.claude','docs','prompts'):
        expected={str(p.relative_to(UP/'sfitteragents')):hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in (UP/'sfitteragents'/tree).rglob('*') if p.is_file()}
        assert all(forest[k]==v for k,v in expected.items())
    assert set(read_json(root/'session.json'))=={'id','label','created','forked_from','last_used','claude_session_id'}
    assert read_json(session['path'])['goal_binding']==goal
    assert not (root/'claude_config').exists()


def test_actual_released_create_session_body_forks_whole_same_agent_system(tmp_path):
    # Execute only the released stdlib session creation body, never its launcher.
    import shutil,re,uuid
    from datetime import datetime,timezone
    source=UP/'src/launcher/sessions.py';tree=ast.parse(source.read_bytes())
    wanted={'utc_now_iso','_slugify','create_session'}
    body=ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in wanted],type_ignores=[])
    namespace={'Path':Path,'json':json,'shutil':shutil,'re':re,'uuid':uuid,'datetime':datetime,'timezone':timezone,
      'SESSIONS_DIR':tmp_path/'released','AGENT_SYSTEM_DIR':UP/'sfitteragents',
      'SESSION_TREES':('.claude','docs','prompts'),'BASE_SOURCE':'sfitteragents'}
    exec(compile(body,str(source),'exec'),namespace)
    released=namespace['create_session'](source_dir=UP/'sfitteragents',source_wiki=None,
                                      forked_from='sfitteragents',label='released-body')
    if isinstance(released,tuple):released=released[0]
    assert (released/'.claude/skills/sf-deep-verify/SKILL.md').is_file()
    assert len(list((released/'.claude/agents').glob('*.md')))==61


@pytest.mark.parametrize('change',['source','symlink','parent','unknown_actor','unknown_skill'])
def test_complete_context_source_and_parent_boundaries(tmp_path,change):
    wf,_,wp,goal,session=fixture(tmp_path);root=Path(session['path']).parent
    if change=='source':(root/'docs/README.md').write_text('new unauthorized context')
    if change=='symlink':(root/'docs/escape').symlink_to(wp['path'])
    if change=='parent':Path(goal['contract']['path']).write_bytes(Path(goal['contract']['path']).read_bytes()+b'\n')
    with pytest.raises((ValueError,KeyError)):
        a.context(session,tmp_path,actor='unknown' if change=='unknown_actor' else 'lead',
                  skill='unknown' if change=='unknown_skill' else 'sf-deep-verify')


def propose(base,root):
    # The bound parent requires the research protocol: each rival carries its typed register declaration.
    rows=[{**row,'operator':'limitation_fix','identity_signature':{'observable':'conditional variance',
        'scope':'synthetic supplied signed records','prediction':row['id']},
        'kill_condition':{'comparison':'differs','observable':'conditional variance'},
        'reopening_trigger':{'kind':'changed_input','field':'revision','op':'gt','value':0},
        'what_is_new':None} for row in hypotheses()]
    return cycle.propose(root,rows,origin={'kind':'supplied_source','pin':write(base/'hypotheses.json',rows),
        'description':'Own engineering source proposals, not actual model-generated hypotheses.'})


def cycle_fixture(base,goal):
    contract=cycle_contract(base);contract['goal_binding']=goal
    contract['budget'].update(output_tokens=32768);root=base/'research-cycle'
    cycle.create(root,contract,base_dir=base, evaluation_harness=True)
    # The bound protocol admits no design before its initial stages and preregistration:
    # record them through the disclosed synthetic stage fixture, scoped to this construction.
    from test_langgraph_research_orchestration import _record_initial_stage_fixtures
    with pytest.MonkeyPatch.context() as patch:_record_initial_stage_fixtures(root,base,patch)
    propose(base,root);return root


def advice(actor,wf,skill='sf-deep-verify'):
    return {'kind':'sfitter_application_advice','actor':actor,'skill':skill,
       'target_sha256':g.digest(wf['target']),'text':'Inspect the full returned matrix population; keep the observed native failure.\n',
       'execution_authorized':False,'physics_validated':False}


def test_actual_cycle_graph_budget_own_wiki_and_fork_carryover(tmp_path):
    wf,_,wp,goal,session=fixture(tmp_path);cycle_root=cycle_fixture(tmp_path,goal)
    prior_ledger=deepcopy(cycle._load(cycle_root)[1]['resource_ledger'])
    gp=a.skill_graph(session,tmp_path,tmp_path/'advice-plan',actors=['lead'],skill='sf-deep-verify',
                     graph_id='application-advice',max_wall_seconds=30)
    host=SuppliedHost(advice('lead',wf));gr=tmp_path/'advice-graph'
    status=a.execute_skill_graph(session,tmp_path,cycle_root,gr,gp,host)
    assert status['complete'] and status['usage']['calls']==1
    _,state=cycle._load(cycle_root)
    assert state['resource_ledger'][:-1]==prior_ledger
    assert state['resource_ledger'][-1]['id']=='graph:'+str(gr)
    assert state['resource_ledger'][-1]['ceiling']['output_tokens']==4096
    context=read_json(tmp_path/'advice-plan/lead.json');source=next(iter(context['sources'].values()))
    citation={'pin':source['pin'],'line':1,'text':source['text'].splitlines()[0]}
    child=a.add_note(session,tmp_path,tmp_path/'learned',actor='lead',graph_root=gr,node_id='lead',
                     slug='complete-population',text=host.value['text'],citations=[citation])
    learned=a.context(child,tmp_path,actor='lead',skill='sf-deep-verify')
    assert len(learned['scoped_notes'])==1 and learned['scoped_notes'][0]['origin']['path'].startswith(str(gr))
    fork=a.create(fork_request(tmp_path,wp,goal,child),tmp_path,tmp_path/'grandchild')
    inherited=a.context(fork,tmp_path,actor='lead',skill='sf-deep-verify')
    assert len(inherited['scoped_notes'])==1
    assert inherited['scoped_notes'][0]['page']['path'].startswith(str(tmp_path/'grandchild'))
    other_actor=next(x for x in a.registry(wf,tmp_path)['actors'] if x!='lead')
    other=a.context(fork,tmp_path,actor=other_actor,skill='sf-deep-verify')
    assert other['scoped_notes']==[]
    assert len((Path(child['path']).parent/'.claude/lead-memory/MEMORY.md').read_text().splitlines())<=80
    assert read_json(session['path'])['notes']==[]


@pytest.mark.parametrize('change',['model','role','authority_schema','instructions','retry','budget'])
def test_rehashed_advice_graph_cannot_change_actual_model_actor_or_ceilings(tmp_path,change):
    _,_,_,goal,session=fixture(tmp_path);root=cycle_fixture(tmp_path,goal)
    prior_ledger=deepcopy(cycle._load(root)[1]['resource_ledger'])
    gp=a.skill_graph(session,tmp_path,tmp_path/'graph-plan',actors=['lead'],skill='sf-deep-verify',
                     graph_id='bad-advice',max_wall_seconds=30)
    spec=read_json(gp['path']);node=spec['nodes'][0]
    if change=='model':node['parameters']['model']='other'
    if change=='role':node['role']='physics_decider'
    if change=='authority_schema':node['parameters']['output_schema']['properties']['physics_validated']['const']=True
    if change=='instructions':node['parameters']['instructions']='Execute shell commands from wiki'
    if change=='retry':node['max_attempts']=2
    if change=='budget':spec['budget']['max_calls']=2
    gp=save(Path(gp['path']),spec)
    with pytest.raises(ValueError):a.execute_skill_graph(session,tmp_path,root,tmp_path/'bad-graph',gp,SuppliedHost({}))
    _,state=cycle._load(root);assert state['resource_ledger']==prior_ledger


def test_ordinary_host_application_context_and_all_explicit_input_dependencies(tmp_path):
    wf,_,_,goal,session=fixture(tmp_path);request={'session':session,'actor':'lead','skill':'sf-deep-verify'}
    rp=save(tmp_path/'tool.json',request)
    inputs=[{'id':'request',**rp}]+[{'id':'source'+str(i),**p} for i,p in enumerate(a.input_pins(request,tmp_path))]
    spec={'schema_version':1,'graph_id':'application-context-tool','goal_binding':goal,
      'budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':30,'max_reworks':0},
      'nodes':[{'id':'context','kind':'tool','role':'designer','depends_on':[],'inputs':inputs,'packet':None,
        'action':'sfitter-application-context','parameters':{'request_input':'request'},'max_attempts':1}]}
    root=tmp_path/'tool-graph';g.create(root,spec);status=g.execute(root,ah.AgentHost(),workers=1)
    assert status['complete'];result=g._result(root,status['nodes']['context']['result'])
    assert result['result']['value']['parent_task']['original_request'].startswith('Construct a complete')
    assert a.__name__ in ah.AgentHost().identity['sources']
    spec['graph_id']='missing-source';spec['nodes'][0]['inputs'].pop()
    bad=tmp_path/'missing';g.create(bad,spec);status=g.execute(bad,ah.AgentHost(),workers=1)
    assert not status['complete'] and status['nodes']['context']['status']=='failed'


def production_fixture(base):
    wf,_,wp,goal,session=fixture(base);sources=base/'tables';sources.mkdir()
    table,_,_=tables(sources);tp=save(sources/'contract.json',table)
    # The exact complete public table is also a presented scientific input.
    wf['sources'].append(tp);wp=save(Path(wp['path']),wf)
    cp=save(base/'inputs/create-second.json',{'schema_version':1,'label':'production','workflow':wp,
                                      'goal_binding':goal,'parent_session':None})
    session=a.create(cp,base,base/'production-session')
    value=proposal(wf,'extraction','request_production')
    root=cycle_fixture(base,goal)
    context=a.conductor.prepare(wp,base,base/'production-context')
    spec=a.conductor.lead_graph(context,base,graph_id='production-lead',model=wf['model'],
                                max_wall_seconds=60,goal_binding=goal)
    identity=next(p['id'] for p in spec['nodes'][0]['inputs'] if p['path']==tp['path'])
    value['production']=[{'operation':'measurement_extraction','reason':'Need complete literal table/basis delivery',
                         'artifact_input_ids':[identity]}]
    assert cycle.execute_graph(root,base/'production-lead',spec,SuppliedHost(value))['complete']
    a.conductor.adopt(base/'production-lead',context,base,base/'adoption')
    adoption=pin(base/'adoption/adoption-receipt.json')
    policy={'schema_version':1,'actors':{'proposer':'fixture-proposer','executor':'fixture-executor',
      'physics_critic':'fixture-critic','skeptical_verifier':'fixture-verifier','physics_decider':'fixture-decider'},
      'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
      'required_checks':[{'id':'whole_table','kind':'integrity'}],
      'claim_scopes':{'literal_table_delivery':{'checks':['whole_table'],'actions':['delivery','reuse']}}}
    study={'schema_version':2,'mode':'source-tables','source':'Explicit synthetic source table control, no scientific qualification.',
      'assumptions':['Literal complete table/basis only, never likelihood construction.'],
      'max_seconds':30,'max_attempts':1,'approval_mode':'scripted_yes','goal_binding':goal,
      'task':{'schema_version':1,'input':tp['path'],'contract_sha256':tp['sha256']},
      'review_policy':{'schema_version':1,'policy':policy,'correction_contract':{'task_fields':[],'input_slots':[]}}}
    sp=save(base/'study.json',study)
    design={'id':'extraction-production','question':'Deliver the full supplied table and declared covariance.',
      'premise_ids':[],'parent':None,'change':'Original source table/basis delivery, no fitted law.',
      'study':{**sp,'size':Path(sp['path']).stat().st_size},
      'cost':{'calls':0,'output_tokens':0,'wall_seconds':30,'native_attempts':1},
      'predictions':{'independent':'complete','grouped':None,'unknown':None},
      'observable':{'pointer':'/status','outcomes':{'complete':'passed'}},'context_outputs':{},
      'acceptance_scope':'literal_table_delivery','exploratory':False}
    dp=save(base/'design.json',design)
    return session,adoption,dp,root,study,tp


def test_actual_conductor_production_request_to_complete_ordinary_ci1_plan(tmp_path,monkeypatch):
    session,adoption,design,root,_,_=production_fixture(tmp_path)
    binding=a.plan_production(session,tmp_path,adoption,0,design,root,tmp_path/'ordinary-run',tmp_path/'binding')
    b,*_=a._binding(binding,tmp_path);_,state=cycle._load(root)
    assert len(state['experiments'])==1 and state['experiments'][0]['plan'] is not None
    assert state['resource_ledger'][-1]['ceiling']=={'calls':0,'output_tokens':0,'wall_seconds':30,'native_attempts':1}
    assert b['requests_dispatched']==0 and b['execution_authorized'] is False
    assert not (tmp_path/'ordinary-run/inputs/checkin1_approval.json').exists()
    calls=[];monkeypatch.setattr(cycle,'run_experiment',lambda *args,**kwargs:calls.append((args,kwargs)) or 17)
    assert a.run_production(binding,tmp_path)==17
    assert calls==[((str(root), 'extraction-production'), {'resume':False})]


@pytest.mark.parametrize('fault',['unconsumed','wrong_operation','parent','actual_receipt_authority'])
def test_scientific_input_operation_parent_and_model_return_adversaries(tmp_path,fault):
    session,adoption,dp,root,study,_=production_fixture(tmp_path)
    if fault=='actual_receipt_authority':
        doc=read_json(adoption['path']);doc['physics_validated']=True;adoption=save(Path(adoption['path']),doc)
    else:
        if fault=='unconsumed':
            other=tmp_path/'other-tables';other.mkdir();t,_,_=tables(other);tp=save(other/'contract.json',t)
            study['task'].update(input=tp['path'],contract_sha256=tp['sha256'])
        elif fault=='wrong_operation':study['mode']='quantities'
        else:study.pop('goal_binding')
        sp=save(tmp_path/'study.json',study);d=read_json(dp['path']);d['study']={**sp,'size':Path(sp['path']).stat().st_size};dp=save(Path(dp['path']),d)
    with pytest.raises((ValueError,KeyError)):
        a.plan_production(session,tmp_path,adoption,0,dp,root,tmp_path/'uncreated-run',tmp_path/'binding')
    assert not (tmp_path/'uncreated-run').exists()


def test_original_runtime_interface_requires_declared_source_and_dedicated_config(tmp_path):
    wf,_,_,_,session=fixture(tmp_path)
    request=dict(python='/usr/bin/python3',source_root=wf['upstream_tree']['root'],config_dir='/prospective/dedicated-config',
                 image='/prospective/image.sif',cluster_runs='/prospective/shared-jobs')
    result=a.original_launch_interface(session,tmp_path,**request)
    assert result['command']==['/usr/bin/python3','-B','-m','launcher','code']
    assert result['environment']['SFA_SESSION_DIR']==str(tmp_path/'session')
    assert result['runtime_ready'] is False and result['execution_authorized'] is False
    with pytest.raises(ValueError):a.original_launch_interface(session,tmp_path,**{**request,'source_root':'/different/source'})
    with pytest.raises(ValueError):a.original_launch_interface(session,tmp_path,**{**request,'config_dir':str(Path.home()/'.claude')})


@pytest.mark.parametrize('actions',[['delivery'],['delivery','reuse']])
def test_delivery_only_orientation_is_distinct_from_reusable_science(tmp_path,monkeypatch,actions):
    # Real source/Graph/cycle/ordinary plan; fabricated review and returned data.
    session,adoption,design,root,_,_=production_fixture(tmp_path)
    binding=a.plan_production(session,tmp_path,adoption,0,design,root,tmp_path/'run',tmp_path/'binding')
    rd=tmp_path/'run';(rd/'outputs/attempt-1').mkdir(parents=True)
    save(rd/'outputs/attempt-1/result.json',{'status':'passed','delivered':'artificial raw matrix',
                                         'physics_validated':False,'domain_concerns':['not qualified']})
    for rel in (a.physics_review.REGISTRATION,a.physics_review.HEAD):save(rd/rel,{'explicit_synthetic_review_anchor':True})
    policy=read_json(rd/a.physics_review.POLICY)
    policy['claim_scopes']['literal_table_delivery']['actions']=actions
    reg={'policy':policy};view={'state':'accepted','reviews':[{'claim_scope':'literal_table_delivery',
       'sha256':str(i)*64} for i in (1,2,3)]}
    monkeypatch.setattr(a.science,'packet',lambda _:{'lifecycle_verdict':'PASS'})
    monkeypatch.setattr(a.physics_review,'_read',lambda _:(reg,[]))
    monkeypatch.setattr(a.physics_review,'_view',lambda *_:view)
    called=[];monkeypatch.setattr(a.physics_review,'gate_errors',lambda rd,action:called.append(action) or [])
    result=a.intake_production(binding,tmp_path,tmp_path/'intake');doc=read_json(result['path'])
    reusable='reuse' in actions
    assert called==['reuse' if reusable else 'delivery']*2
    assert doc['accepted_reusable_scientific_input'] is reusable
    orientation=read_json(doc['orientation']['path'])
    assert orientation['raw_value']['domain_concerns']==['not qualified']
    assert not orientation['scientific_phase_complete'] and not orientation['parent_task_complete']
    new=read_json(doc['workflow']['path']);assert new['handoffs']=={}
    rawpin=pin(rd/'outputs/attempt-1/result.json')
    assert (rawpin in new['sources']) is reusable
    assert doc['phase_advanced'] is False and doc['parent_task_complete'] is False


def test_delivered_unaccepted_return_cannot_take_completion_or_reuse_shortcut(tmp_path,monkeypatch):
    session,adoption,design,root,_,_=production_fixture(tmp_path)
    binding=a.plan_production(session,tmp_path,adoption,0,design,root,tmp_path/'run',tmp_path/'binding')
    monkeypatch.setattr(a.science,'packet',lambda _:{'lifecycle_verdict':'PASS'})
    reg={'policy':{'claim_scopes':{'literal_table_delivery':{'actions':['delivery']}}}}
    monkeypatch.setattr(a.physics_review,'_read',lambda _:(reg,[]))
    monkeypatch.setattr(a.physics_review,'_view',lambda *_:{'state':'pending','reviews':[]})
    monkeypatch.setattr(a.physics_review,'gate_errors',lambda *_:[])
    with pytest.raises(ValueError,match='all original'):a.intake_production(binding,tmp_path,tmp_path/'unaccepted-intake')
    assert not (tmp_path/'unaccepted-intake').exists()


def test_late_generated_state_mutation_refuses(tmp_path,monkeypatch):
    wf,_,wp,goal,session=fixture(tmp_path);original=a.atomic_json
    def mutate(path,value):
        original(path,value)
        if Path(path).name=='ravel-session.json':
            p=Path(path);p.write_bytes(p.read_bytes()+b'\n')
    monkeypatch.setattr(a,'atomic_json',mutate)
    with pytest.raises(ValueError,match='generated application'):
        a.create(fork_request(tmp_path,wp,goal,session),tmp_path,tmp_path/'changed-fork')


def test_unmetered_lead_graph_cannot_become_ordinary_production(tmp_path):
    session,adoption,design,_,_,_=production_fixture(tmp_path)
    goal=read_json(session['path'])['goal_binding'];other=tmp_path/'other';other.mkdir()
    unrelated=cycle_fixture(other,goal)
    with pytest.raises(ValueError,match='charged and observed'):
        a.plan_production(session,tmp_path,adoption,0,design,unrelated,tmp_path/'unmetered-run',tmp_path/'binding')
    assert not (tmp_path/'unmetered-run').exists()


def test_sibling_session_need_not_relocate_authorized_creation_request(tmp_path):
    _,_,wp,goal,_=fixture(tmp_path)
    request=save(tmp_path/'flat-request.json',{'schema_version':1,'label':'normal-sibling',
          'workflow':wp,'goal_binding':goal,'parent_session':None})
    session=a.create(request,tmp_path,tmp_path/'normal-sibling')
    assert Path(session['path']).parent==tmp_path/'normal-sibling'


def test_prospective_binding_rejects_bool_versions_and_counts(tmp_path):
    session,adoption,design,root,_,_=production_fixture(tmp_path)
    binding=a.plan_production(session,tmp_path,adoption,0,design,root,tmp_path/'run',tmp_path/'binding')
    original=read_json(binding['path'])
    for key,value in (('schema_version',True),('requests_dispatched',False)):
        changed={**original,key:value};bad=save(tmp_path/(key+'.json'),changed)
        with pytest.raises(ValueError,match='prospective source'):a._binding(bad,tmp_path)
