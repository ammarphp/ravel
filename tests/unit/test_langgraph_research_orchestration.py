"""Prospective real-framework software controls; authored, not author-executed.

All model responses are explicit inert local fixtures through actual Host context,
public-schema and Control.call paths. The quantities worker uses only supplied
synthetic records. No provider, native generator or physics qualification.
"""

from method_decision_fixture import admit_method
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import TypedDict

import pytest
from langgraph.graph import START, END
from langgraph.types import interrupt
from ravel.workflow import agent_graph as graph, agent_host, langgraph_runtime as runtime
from ravel.workflow import research_orchestrator as orchestration, research_coordinator_decisions as decisions
from ravel.workflow import research_cycle as cycle, scientific_context, science, task_completion, route_prompt
from ravel.workflow.state_io import atomic_json, read_json


# The Host presents inline at most a quarter of its declared request bound. A method
# assessment needs the complete packet presented, and that packet holds the whole
# source of every operation it names (about 1 MiB): declare a bound that holds it.
METHOD_REQUEST_BYTES=8*1024*1024
# The ordinary bound cannot present that packet, so the assessment refuses the receipt.
# The scripted Host and the open fixture keep it as their default: the loop-graph parity
# fixture of the refused first assessment imports both.
ORDINARY_REQUEST_BYTES=2*1024*1024


def write(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if type(value) is str:path.write_text(value)
    else:atomic_json(path,value)
    return cycle._pin(path)


def node(name, parents=(), inputs=()):
    return {'id':name,'kind':'tool','role':'executor','depends_on':list(parents),
        'inputs':list(inputs),'packet':None,'action':'fixture','parameters':{},'max_attempts':1}


def graph_spec(nodes, calls=20):
    return {'schema_version':1,'graph_id':'framework-control','budget':{'max_nodes':16,
        'max_calls':calls,'max_output_tokens':0,'max_wall_seconds':120,'max_reworks':3},'nodes':nodes}


class ToolHost:
    identity={'fixture':'actual-graph-call-custody-only'}
    def __init__(self):self.calls=[]
    def execute(self, item, request, control):
        def effect():
            self.calls.append(item['id'])
            return {'fixture':item['id']}
        return control.call('fixture','tool',request,effect)


@pytest.mark.parametrize('order',[['join','right','left','root'],['root','left','right','join']])
def test_real_released_framework_accepts_valid_dag_list_order_and_and_join(tmp_path,order):
    rows={'root':node('root'),'left':node('left',['root']),
        'right':node('right',['root']),'join':node('join',['left','right'])}
    root=tmp_path/'graph';graph.create(root,graph_spec([rows[i] for i in order]))
    host=ToolHost();result=graph.execute(root,host,workers=2)
    assert result['complete'] and host.calls[0]=='root' and host.calls[-1]=='join'
    assert sorted(host.calls)==sorted(rows)
    assert read_json(root/graph.SPEC)['nodes']==[rows[i] for i in order]
    graph.execute(root,host,workers=2)
    assert len(host.calls)==4 and graph.status(root)['usage']['calls']==4


def test_rework_one_sibling_reuses_unchanged_pinned_generation(tmp_path):
    root=tmp_path/'graph';graph.create(root,graph_spec([node('A'),node('B')]))
    host=ToolHost();graph.execute(root,host)
    prior=deepcopy(graph.status(root)['nodes']['A']['result'])
    graph.rework(root,['B'],reason='Explicit engineering sibling rework.')
    result=graph.execute(root,host)
    assert result['complete'] and host.calls.count('A')==1 and host.calls.count('B')==2
    assert result['nodes']['A']['result']==prior and result['usage']['calls']==3


def test_revision_reuses_unrelated_but_refuses_changed_host_and_actual_input(tmp_path):
    data=tmp_path/'data';data.write_text('original')
    pin=lambda:{'id':'data','path':str(data),'sha256':hashlib.sha256(data.read_bytes()).hexdigest()}
    root=tmp_path/'graph';spec=graph_spec([node('A'),node('B',inputs=[pin()])])
    graph.create(root,spec);host=ToolHost();graph.execute(root,host)
    data.write_text('changed')
    with pytest.raises(ValueError):graph.execute(root,host)
    newer=deepcopy(spec);newer['nodes'][1]['inputs']=[pin()]
    graph.revise(root,newer,reason='Actual source changed for B only.')
    graph.execute(root,host)
    assert host.calls.count('A')==1 and host.calls.count('B')==2
    host.identity={'fixture':'different actual Host'}
    with pytest.raises(ValueError):graph.execute(root,host)


class State(TypedDict, total=False):
    value:int


def machine(directory,nodes,initial=None):
    return runtime.run_state_machine(directory,thread_id='same-original-question',state_type=State,
        nodes=nodes,edges=[(START,'work'),('work',END)],initial={'value':0} if initial is None else initial,
        max_steps=4,identity_binding={'original_scope':'no authority from a checkpoint'})


def test_actual_sqlite_interrupt_restarts_node_and_retains_effect_receipt(tmp_path):
    effect=tmp_path/'effect.json';approval=tmp_path/'explicit-control-approval'
    entries=[]
    def work(state):
        entries.append('entry')
        if not approval.exists():interrupt({'kind':'explicit_control_needed','approval_from_resume':False})
        if not effect.exists():write(effect,{'completed':1,'physics_validated':False})
        assert read_json(effect)=={'completed':1,'physics_validated':False}
        return {'value':1}
    directory=tmp_path/'framework';_,first=machine(directory,{'work':work})
    assert first['interrupted'] and not effect.exists()
    _,still=machine(directory,{'work':work})
    assert still['interrupted'] and not effect.exists()  # None cannot authorize.
    approval.write_text('Explicit engineering-only authorization.')
    final,observed=machine(directory,{'work':work})
    assert final['value']==1 and not observed['interrupted'] and len(entries)>=3
    before=effect.read_bytes();calls=len(entries)
    machine(directory,{'work':work})
    assert effect.read_bytes()==before and len(entries)==calls  # terminal callbacks can be skipped.


def test_effect_before_checkpoint_crash_reconciles_without_second_effect(tmp_path):
    effect=tmp_path/'effect.json';entries=[]
    def work(state):
        entries.append('entry')
        if not effect.exists():
            write(effect,{'exact_effect':1,'physics_validated':False})
            raise RuntimeError('Injected crash after an actual effect, before framework checkpoint.')
        assert read_json(effect)=={'exact_effect':1,'physics_validated':False}
        return {'value':1}
    with pytest.raises(RuntimeError):machine(tmp_path/'framework',{'work':work})
    before=effect.read_bytes();state,_=machine(tmp_path/'framework',{'work':work})
    assert state['value']==1 and effect.read_bytes()==before and len(entries)==2


def test_unknown_started_effect_is_held_on_every_reentry(tmp_path):
    started=tmp_path/'started';count=[]
    def work(state):
        if started.exists():raise orchestration.RecoveryHold('Actual effect outcome is unknown.')
        started.write_text('owned invocation has no reconciled completion')
        count.append('effect-start')
        raise orchestration.RecoveryHold('Unknown completion must not be repeated.')
    for _ in range(2):
        with pytest.raises(orchestration.RecoveryHold):machine(tmp_path/'framework',{'work':work})
    assert count==['effect-start']


def test_shared_directory_owns_entire_cross_process_invocation(tmp_path):
    directory=tmp_path/'framework';started=tmp_path/'started';release=tmp_path/'release'
    program=r'''
import sys,time
from pathlib import Path
from typing import TypedDict
from langgraph.graph import START,END
from ravel.workflow.langgraph_runtime import run_state_machine
class S(TypedDict): value:int
root,started,release=map(Path,sys.argv[1:])
def work(state):
    started.write_text('owned active invocation')
    end=time.monotonic()+8
    while not release.exists() and time.monotonic()<end:time.sleep(.02)
    if not release.exists():raise RuntimeError('test release not delivered')
    return {'value':1}
run_state_machine(root,thread_id='same-original-question',state_type=S,nodes={'work':work},
 edges=[(START,'work'),('work',END)],initial={'value':0},max_steps=4,
 identity_binding={'original_scope':'no authority from a checkpoint'})
'''
    process=subprocess.Popen([sys.executable,'-B','-c',program,str(directory),str(started),str(release)])
    try:
        end=time.monotonic()+6
        while not started.exists() and process.poll() is None and time.monotonic()<end:time.sleep(.02)
        assert started.exists() and process.poll() is None
        dispatched=[]
        with pytest.raises(ValueError,match='another process owns'):
            machine(directory,{'work':lambda s:(dispatched.append('duplicate'),{'value':2})[1]})
        assert dispatched==[]
    finally:
        release.write_text('explicit release');process.wait(timeout=10)
    assert process.returncode==0


PROMPT='Implement a search analysis comparing the complete supplied signed-event variance. Deliver a comparison figure and an internal note; retain failed and inconclusive evidence.'


def parent(base):
    contract=route_prompt.route(PROMPT)
    contract.setdefault('task_requirements',task_completion.initial_requirements(PROMPT))
    req=contract['task_requirements']
    for identity,meaning in [('figure','Complete comparison figure.'),('note','Internal note with negative evidence.')]:
        req['obligations'].append({'id':identity,'kind':'deliverable','statement':meaning,'criteria':{'deliverable':meaning},
            'evidence':[{'start':0,'end':len(PROMPT),'text':PROMPT}]})
    req['assignments']=[{'id':'original-task','purpose':'Preserve the complete original supplied research request.',
        'coverage':[{'obligation_id':r['id'],'criteria':deepcopy(r['criteria'])} for r in req['obligations']]}]
    return contract,write(base/'parent/inputs/task_contract.json',contract)


def context(base):
    source=write(base/'method.py','def grouped_variance(weights):\n    return sum(weights)**2\n')
    return source,{'schema_version':1,'task_id':'supplied-signed-control','task':PROMPT,
        'source_capsules':[],'api_documents':[{'id':'method','pin':{k:source[k] for k in ('path','sha256')},
            'language':'python','role':'api','version':'Explicit supplied software-control method.','dependencies':[]}],
        'queries':[{'id':'method-law','symbol':'grouped_variance','mode':'definition','documents':['method'],'required':True}],
        'requested_quantities':[{'id':'conditional-variance','artifact':'measurement','pointer':'/quantities/covariance',
            'check':{'kind':'exact','value':[[1.0]]},'meaning':'Complete signed pair; supplied arithmetic, no physics calibration.'}],
        'compatibility_groups':[{'id':'current-control','artifacts':['measurement'],'carryover':False,
            'basis':'Every experiment preserves both complete signed records.'}],
        'max_source_bytes':128000,'max_context_bytes':16000,'max_steps':6}


def supplied_study(base,goal):
    contract=write(base/'supplied/contract.json',{'schema_version':1,'axes':[{'name':'x','unit':'1'}],
        'bins':[{'id':'one','low':[0.0],'high':[1.0]}],'weight_names':['nominal'],'input_weight_unit':'1',
        'representation':'integrated','normalization':{'kind':'absolute','scale':1.0,'unit':'1'}})
    records=write(base/'supplied/records.jsonl','\n'.join(json.dumps({'event_id':str(i),'group_id':'shared','shard_id':'control',
        'weights':{'nominal':w},'fills':[[.5]]}) for i,w in enumerate([2,-1]))+'\n')
    policy={'schema_version':1,'actors':{'proposer':'fixture-worker','executor':'fixture-worker',
        'physics_critic':'fixture-critic','skeptical_verifier':'fixture-verifier','physics_decider':'fixture-decider'},
        'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
        'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'math','kind':'scientific'}],
        'claim_scopes':{'supplied_math_diagnostic':{'checks':['integrity','math'],'actions':['delivery','reuse']}}}
    spec={'schema_version':2,'mode':'quantities','source':'Explicit complete supplied-record engineering control.',
        'assumptions':['No generated events, independent model calls or physical efficacy.'],'max_seconds':30,
        'max_attempts':1,'approval_mode':'scripted_yes','goal_binding':goal,
        'task':{'contract':contract['path'],'records':records['path']},'review_policy':{'schema_version':1,
            'policy':policy,'correction_contract':{'task_fields':[],'input_slots':[]}}}
    return spec,[contract,records]


class ScriptedResearchHost(agent_host.AgentHost):
    """Real Host preparation/result validators; no actual HTTP/model dispatch."""
    def __init__(self,callback,*,omit_presentation=False,max_request_bytes=ORDINARY_REQUEST_BYTES):
        super().__init__(endpoint='http://127.0.0.1:1/v1/responses',
            max_request_bytes=max_request_bytes,max_response_bytes=1024*1024)
        self.callback=callback;self.actual_contexts=[];self.omit_presentation=omit_presentation
    @property
    def identity(self):return {'fixture':'scripted-research-host-v1','source':cycle._pin(Path(__file__))}
    def execute(self,item,request,control):
        if item['kind']=='tool':return super().execute(item,request,control)
        prepared=self.prepare_model_context(item,request);context=prepared['context']
        self.actual_contexts.append(deepcopy(context))
        def response():
            public=self.callback(item,context)
            result=self._result(public,item['parameters'],request,observed_model='scripted-control')
            result=self._presented_result(result,context)
            if self.omit_presentation and item['role'] in {'critic','verifier'}:
                result['isolation'].pop('evidence_presentation',None)
            return result
        return control.call('scripted-model','model',request,response,output_tokens=item['parameters']['max_output_tokens'])


def open_fixture(base, *, mutation=None, extra_evidence=(), initial_premises=(), max_request_bytes=ORDINARY_REQUEST_BYTES):
    contract,cp=parent(base);source,declared=context(base)
    goal={'contract':cp,'assignment_id':'original-task'}
    study,inputs=supplied_study(base,goal)
    # The bound protocol dispatches no study without its prospective evaluation and exposure:
    # the evaluated population is the study's own supplied record input.
    population=inputs[1]
    campaign={'id':'complete-original-research','budget':{'calls':40,'output_tokens':200000,'wall_seconds':3600,'native_attempts':6},
        'max_experiments':6,'exploration_every':2,'required_experiments':['paired'],'premises':list(initial_premises)}
    setting={'model':'scripted-control','reasoning_effort':'high','adapter':'model','max_output_tokens':4096,'max_wall_seconds':30}
    mapping=[{'obligation_id':r['id'],'original':deepcopy(r),'quantities':['conditional-variance'] if r['id']=='original-request' else [],
        'method':'Complete supplied signed-pair arithmetic; figure/note require later actual production.',
        'sources':[source],'unresolved':'' if r['id']=='original-request' else r['statement']} for r in contract['task_requirements']['obligations']]
    rp=orchestration.prepare_open(cp,base/'request',base_dir=base,campaign=campaign,runtime=setting,
        evidence=[{'pin':p,'purpose':'model_context'} for p in [source,*inputs]]+list(extra_evidence),candidate_modes=['quantities'],
        review={'arguments':{},'allow_control':True},max_decisions=8)
    def callback(item,ctx):
        if item['role'] in {'critic','verifier'}:
            return {'kind':'context-method-assessment','subject_sha256':item['parameters']['output_schema']['properties']['subject_sha256']['const'],
                'verdict':'adequate_for_prospective_tests','findings':['No physics or parent acceptance from this supplied control.'],
                'summary':'The complete original figure/note obligations remain explicitly unresolved.'}
        core=json.loads(next(p['content'] for p in ctx['input_artifacts'] if p['id']=='scientific-core'))
        if core['phase']=='declare-context':
            changed=deepcopy(mapping)
            if mutation=='drop-obligation':changed.pop()
            return {'kind':'research-context-declaration','context_json':json.dumps(declared),
                'obligation_mapping_json':json.dumps(changed),'modes':[],'reason':'Source-grounded prospective control.'}
        if core['phase']=='hypotheses':
            stream=core['stream'];identity='paired-law' if stream=='speculative' else 'separate-law'
            assert core['hypotheses']==[] and core['peer_ideas_presented'] is False
            # The bound protocol registers each rival with its typed declaration.
            return {'hypotheses':[{'id':identity,'statement':'Explicit rival supplied-record law.','stream':stream,
                'premise_ids':[],'source_basis':[source],'parents':[],
                'operator':'limitation_fix','identity_signature':{'observable':'relation',
                    'scope':'supplied signed records','prediction':identity},
                'kill_condition':{'comparison':'differs','observable':'relation'},
                'reopening_trigger':{'kind':'changed_input','field':'revision','op':'gt','value':0},
                'what_is_new':None}]}
        turn=len(core['prior_operation_effects'])
        if turn==0:
            action='preparation-tool';arguments={'action':'scientific-context','parameters':{'request_input':'missing'},'inputs':[],'records':[]}
        elif turn==1:
            assert core['prior_operation_effects'][0]['actual_effect']['status']=='preparation_failed'
            action='preparation-tool';arguments={'action':'scientific-context','parameters':{'request_input':'request'},
                'inputs':[{'id':'request','pin':{'generated_record':'context-request','field':'pin3'}},
                    {'id':'method','pin':source}],
                'records':[{'id':'context-request','purpose':'prospective_configuration',
                    'value':deepcopy(declared),'source_basis':[source]}]}
        elif turn==2:
            prepared=core['prior_operation_effects'][1]['actual_effect']
            assert prepared['status']=='prepared' and prepared['scientific_acceptance'] is False
            assert prepared['actual_preparation']['value']['action']=='scientific-context'
            # This is a source-grounded configuration, not observed covariance.
            assert prepared['authored_configuration_provenance']['path']
            action='experiment';arguments={'study':deepcopy(study),'records':[], 'source_mapping':deepcopy(mapping),
                'experiment':{'id':'paired','question':'Measure every supplied signed record.','premise_ids':[],'parent':None,
                    'change':'Use the complete supplied pair after actual missing-input preparation failure.',
                    'cost':{'calls':0,'output_tokens':0,'wall_seconds':30,'native_attempts':1},
                    'predictions':{'paired-law':'shared','separate-law':'independent'},
                    'observable':{'pointer':'/quantities/covariance/0/0','outcomes':{'shared':1.0,'independent':5.0}},
                    'context_outputs':{'measurement':'outputs/attempt-1/result.json'},
                    'acceptance_scope':'supplied_math_diagnostic','exploratory':True,
                    'evaluation':{'candidate':'paired','family':'supplied-math','round':1,'purpose':'full',
                        'cells':['supplied-pair'],'seeds':[101],'generation':'supplied-records',
                        'population_pins':[population],'value_pointer':'/quantities/covariance/0/0'}}}
        elif turn==3:action='run-selected';arguments={}
        else:action='progress';arguments={'reason':'The original figure/note and independent scientific review remain open.'}
        return {'kind':'research-action','action':action,'reason':'Actual source-bound software-control choice.',
            'arguments_json':json.dumps(arguments)}
    return rp,ScriptedResearchHost(callback,omit_presentation=mutation=='missing-presentation',
        max_request_bytes=max_request_bytes),source,contract


def pass_initial_stages(root,rp,out,host,base,monkeypatch):
    """Actual open flow up to its hold for the bound protocol's initial stages, then those stages.

    The method assessment passes on the complete presented packet. The flow then holds
    for the limitation census before any idea stream; that hold is neither an approval
    nor a hypothesis. The two initial stages run as actual stage Graphs with synthetic
    external role deliveries and a synthetic preregistration is bound. The caller's next
    invocation continues the same flow. The external decision provider is an inert seam here.
    """
    held=orchestration.open_research(root,rp,out,host=host)
    assert held['phase']=='ordinary_effect_required' and held['execution_authorized'] is False
    waiting=[row['value'] for row in held['checkpoint']['interrupts']]
    assert [row['kind'] for row in waiting]==['research_stage_required']
    assert waiting[0]['stage']['id']=='limitation_census' and waiting[0]['execution_authorized'] is False
    _,state=cycle._load(root)
    assert state['hypotheses']==[] and state['experiments']==[] and state['methodology']['preregistration'] is None
    assert state['scientific_context_declaration']['origin']['role']=='designer'
    assert not any(e['kind']=='coordinator_effect_committed' for e in state['events'])
    complete_initial_stages(root,base,monkeypatch)


def complete_initial_stages(root,base,monkeypatch):
    """Limitation census and ideas through actual stage Graphs, then a synthetic preregistration.

    Every role answer is a synthetic external delivery (accept, no attributed claim): a
    transport control, never a scientific review.
    """
    from ravel.workflow import research_protocol as protocol
    from test_agent_graph import external_response
    from test_research_default_protocol import register,synthetic_artifacts
    monkeypatch.setattr(protocol,'decision_errors',lambda *a,**k:[])
    artifacts=synthetic_artifacts(base/'methodology-fixture')
    settings={'model':'host-agent','reasoning_effort':'high','adapter':'external','max_output_tokens':1024,'max_wall_seconds':900}
    stage_host=agent_host.AgentHost()
    for stage in ('limitation_census','ideas'):
        artifact=write(base/('stage-'+stage+'.json'),artifacts[stage]);out=base/('stage-'+stage)
        assert not orchestration.run_protocol_stage(root,artifact,out,host=stage_host,settings=settings)['complete']
        for role,row in graph.status(out/'graph')['nodes'].items():
            assert row['status']!='completed'
            pending=graph.prepare_external(out/'graph',role)
            fields=read_json(pending['request_file'])['parameters']['output_schema']['properties']
            public={key:fields[key]['const'] for key in ('stage','role_id','subject_sha256')}
            public.update(verdict='accept',findings=['Synthetic transport control only.'],attributed_claim_ids=[])
            graph.deliver_external(out/'graph',role,external_response(pending,out/(role+'-response.json'),
                value=public,actor_id='synthetic-'+role,observed_model='host-agent'))
        assert orchestration.run_protocol_stage(root,artifact,out,host=stage_host,settings=settings)['complete']
    register(root)
    record=protocol.methodology_status(root)['record']
    assert [row['status'] for row in record['stages'][:2]]==['done','done'] and record['preregistration'] is not None


def test_complete_open_question_actual_design_failed_preparation_science_resume_and_whole_parent(tmp_path,monkeypatch):
    rp,host,source,parent_contract=open_fixture(tmp_path,max_request_bytes=METHOD_REQUEST_BYTES)
    root=tmp_path/'campaign';out=root/'coordinator'
    pass_initial_stages(root,rp,out,host,tmp_path,monkeypatch)
    held=orchestration.open_research(root,rp,out,host=host)
    assert [row['value']['kind'] for row in held['checkpoint']['interrupts']]==['ordinary_checkin1_and_machine_lease_required']
    assert held['phase']=='ordinary_effect_required'
    _,state=cycle._load(root);e=state['experiments'][0]
    assert e['rundir'] and e['observation'] is None
    assert state['scientific_context_declaration']['origin']['role']=='designer'
    assert {r['obligation_id'] for r in state['scientific_context_declaration']['mapping']}=={r['id'] for r in parent_contract['task_requirements']['obligations']}
    initial_calls=len(host.actual_contexts);ceiling=cycle._usage(state)
    # A retry supplies no interrupt response and cannot turn the checkpoint
    # into CHECK-IN 1 or a native lease. Actual approval remains absent.
    repeated=orchestration.open_research(root,rp,out,host=host)
    assert repeated['phase']=='ordinary_effect_required'
    _,unapproved=cycle._load(root)
    assert unapproved['experiments'][0]['observation'] is None
    assert not (Path(e['rundir'])/science.APPROVAL).exists()
    assert len(host.actual_contexts)==initial_calls and cycle._usage(unapproved)==ceiling
    admit_method(e['rundir'])
    science.approve(e['rundir'],'Root-authorized inert software control; no physicist/native/model authority.',scripted=True)
    result=orchestration.open_research(root,rp,out,host=host)
    _,now=cycle._load(root);e=now['experiments'][0]
    assert read_json(Path(e['rundir'])/'outputs/attempt-1/result.json')['quantities']['covariance']==[[1.0]]
    assert e['observation'] is not None and e['adjudication'] is None
    assert result['parent_task_accepted'] is False
    assert now['contract']['budget']==state['contract']['budget'] and cycle._usage(now)['calls']>=ceiling['calls']
    assert len(host.actual_contexts)==initial_calls+1  # only the later progress choice, not prior designer roles.
    before=len(host.actual_contexts);again=orchestration.open_research(root,rp,out,host=host)
    assert again==result and len(host.actual_contexts)==before
    assert not any(context.get('parent_transcript') for context in host.actual_contexts)
    assert len([x for x in now['events'] if x['kind']=='coordinator_effect_committed'])==4


def test_actual_designer_cannot_drop_original_nonnumeric_obligation(tmp_path):
    rp,host,_,_=open_fixture(tmp_path,mutation='drop-obligation')
    with pytest.raises(ValueError,match='complete original obligation'):
        orchestration.open_research(tmp_path/'campaign',rp,tmp_path/'campaign/coordinator',host=host)
    _,state=cycle._load(tmp_path/'campaign')
    assert not state['experiments'] and not state['hypotheses'] and not state.get('scientific_context_declaration')


def test_bound_method_source_drift_refuses_resume_without_new_model_call(tmp_path,monkeypatch):
    rp,host,source,_=open_fixture(tmp_path,max_request_bytes=METHOD_REQUEST_BYTES);root=tmp_path/'campaign';out=root/'coordinator'
    pass_initial_stages(root,rp,out,host,tmp_path,monkeypatch)
    held=orchestration.open_research(root,rp,out,host=host);assert held['phase']=='ordinary_effect_required'
    assert cycle._load(root)[1]['experiments'][0]['observation'] is None
    calls=len(host.actual_contexts);Path(source['path']).write_text('def grouped_variance(weights):\n    return 999\n')
    with pytest.raises(ValueError):orchestration.open_research(root,rp,out,host=host)
    assert len(host.actual_contexts)==calls


def test_preparation_output_handoff_checks_known_native_producer_pin(tmp_path):
    output=tmp_path/'effect';sp=write(output/'prepared/science.json',{'schema_version':2,'source':'Explicit prospective control only.'})
    actual={'value':{'kind':'ravel_tool_result','action':'model-event-plan','value':{'specification':sp}}}
    delivered=decisions._prepared_inputs(actual,output)
    assert sp in delivered and read_json(delivered[0]['path'])==actual['value']
    Path(sp['path']).write_text('{}')
    with pytest.raises(ValueError,match='committed preparation output changed'):decisions._prepared_inputs(actual,output)


def test_authored_json_cannot_claim_retrieved_or_measured_physics(tmp_path):
    # The actual-origin requirement fires before any prospective emission.
    with pytest.raises((ValueError,OSError)):
        decisions.authored_records({'root':str(tmp_path/'absent'),'node_id':'model','inputs':[]},
            [{'id':'invented','purpose':'measured_covariance','value':[[1.0]],'source_basis':[]}],tmp_path/'outputs')
    assert not (tmp_path/'outputs').exists()


def test_method_assessment_requires_actual_host_presentation(tmp_path):
    # The Host could present the complete packet: only the omitted observation refuses.
    rp,host,_,_=open_fixture(tmp_path,mutation='missing-presentation',max_request_bytes=METHOD_REQUEST_BYTES)
    with pytest.raises(ValueError,match='actual complete method core/source presentation'):
        orchestration.open_research(tmp_path/'campaign',rp,tmp_path/'campaign/coordinator',host=host)
    _,state=cycle._load(tmp_path/'campaign')
    assert not state['experiments'] and not state['hypotheses']


def test_actual_model_origin_cannot_relabel_configuration_as_measurement(tmp_path,monkeypatch):
    rp,host,source,_=open_fixture(tmp_path,max_request_bytes=METHOD_REQUEST_BYTES);root=tmp_path/'campaign'
    pass_initial_stages(root,rp,root/'coordinator',host,tmp_path,monkeypatch)
    held=orchestration.open_research(root,rp,root/'coordinator',host=host)
    assert held['phase']=='ordinary_effect_required'
    origin=cycle._graph_result(root/'coordinator/turns/0/graph','decision')
    out=tmp_path/'forged-observation'
    with pytest.raises(ValueError,match='authored physics observations are forbidden'):
        decisions.authored_records(origin,[{'id':'covariance','purpose':'measured_covariance',
            'value':[[1.0]],'source_basis':[source]}],out)
    assert not out.exists()


def test_completed_campaign_effect_cannot_be_rebound_by_checkpoint(tmp_path,monkeypatch):
    rp,host,_,_=open_fixture(tmp_path,max_request_bytes=METHOD_REQUEST_BYTES);root=tmp_path/'campaign';out=root/'coordinator'
    pass_initial_stages(root,rp,out,host,tmp_path,monkeypatch)
    held=orchestration.open_research(root,rp,out,host=host)
    assert held['phase']=='ordinary_effect_required'
    _,state=cycle._load(root)
    event=next(e for e in state['events'] if e['kind']=='coordinator_effect_committed')
    pin=event['effect'];original=Path(pin['path']).read_bytes();count=len(host.actual_contexts)
    value=json.loads(original);value['actual_effect']['status']='prepared'
    Path(pin['path']).write_text(json.dumps(value))
    with pytest.raises(ValueError):orchestration.open_research(root,rp,out,host=host)
    assert len(host.actual_contexts)==count


def test_real_public_host_open_preparation_binds_complete_original_inputs(tmp_path):
    rp,_,source,_=open_fixture(tmp_path/'base')
    request=read_json(rp['path'])
    settings={k:request[k] for k in ('campaign','runtime','evidence','candidate_modes','review','max_decisions')}
    preparation=write(tmp_path/'ordinary-preparation.json',{'parent_contract':request['parent_contract'],'settings':settings})
    pins=[preparation,request['parent_contract'],*[r['pin'] for r in request['evidence']]]
    tool=node('prepare',inputs=[{'id':'request' if i==0 else 'input'+str(i),'path':p['path'],'sha256':p['sha256']}
        for i,p in enumerate(pins)])
    tool['action']='research-open-prepare';tool['parameters']={'request_input':'request','output_dir':str(tmp_path/'host-prepared')}
    spec=graph_spec([tool],calls=1);root=tmp_path/'host-graph';graph.create(root,spec)
    observed=graph.execute(root,agent_host.AgentHost())
    assert observed['complete'] and observed['usage']['calls']==1
    actual=cycle._graph_result(root,'prepare')['value']
    assert actual['kind']=='ravel_tool_result' and actual['action']=='research-open-prepare'
    prepared=read_json(actual['value']['path'])
    assert prepared['handoff']==request['handoff'] and prepared['campaign']==request['campaign']
    assert prepared['handoff']['compute_authorized'] is False
    Path(source['path']).write_text('def grouped_variance(weights):\n    return 999\n')
    with pytest.raises(ValueError):graph.execute(root,agent_host.AgentHost())


@pytest.mark.parametrize('action',[
    'model-proposals','routine-workflow','routine-step','manuscript-author',
    'manuscript-collect','manuscript-build','manuscript-review','manuscript-consume','manuscript-finalize'])
def test_finite_extensions_use_exact_source_defined_argument_and_return_transport(tmp_path,monkeypatch,action):
    from types import SimpleNamespace
    from ravel.workflow import scientific_judgment
    root=tmp_path/'campaign';out=root/'effect';host=object();calls=[]
    pin={'path':str(tmp_path/'input'),'sha256':'a'*64,'size':13}
    role={'request':pin,'graph_root':str(root/'role'),'node_id':'critic'}
    envelope={'manuscript':{'case':pin},'role_binding':role,'execution_authorized':False}
    writer={'kind':'manuscript-author-binding','request':pin,'graph':str(root/'author')}
    def prepare_writer(request,out,*,base_dir,campaign):
        assert campaign==root;return writer
    def execute_writer(binding,host):
        assert binding is writer;calls.append('writer');return {'complete':True}
    def prepare_integrity_role(package,out,*,base_dir,campaign,experiment,rundir,**kw):
        assert campaign==root and experiment=='actual' and rundir==str(root/'actual');return envelope
    def execute_role(binding,host):
        assert binding is role and binding is not envelope;calls.append('role');return {'complete':True}
    def consume_integrity_role(package,binding,*,base_dir):
        assert binding is role;calls.append('consume');return {'phase':'actual-journal'}
    def finalize(package,bindings,build_binding,final_manifest,completion_request,*,base_dir,rundir):
        assert bindings==[role] and set(build_binding)=={'rundir','receipt','result'}
        return {'kind':'whole-parent-manuscript-delivery'}
    module=SimpleNamespace(
        prepare_model_proposals=lambda root,request_pin,*,premise_map,reason:{'premises':['full']},
        routine_workflow=lambda root,choice_pin,out,host,*,max_wall_seconds:{'specification':pin,'goal_binding':{}},
        routine_step=lambda root,selection_pin,*,base_dir,host,output_dir:pin,
        prepare_writer=prepare_writer,execute_writer=execute_writer,
        collect=lambda binding,out:{'package':{},'package_pin':pin,'integrity_preparation':{}},
        prepare_build=lambda package,out,*,base_dir,runtime,review_policy,goal_binding:{
            'specification':pin,'ordinary_plan':{},'execution_authorized':False,'scientific_acceptance':False},
        prepare_integrity_role=prepare_integrity_role,consume_integrity_role=consume_integrity_role,finalize=finalize)
    monkeypatch.setattr(decisions.importlib,'import_module',lambda name:module)
    monkeypatch.setattr(scientific_judgment,'execute_role',execute_role)
    args={
        'model-proposals':{'request_pin':pin,'premise_map':{},'reason':'actual located source'},
        'routine-workflow':{'choice_pin':pin},'routine-step':{'selection_pin':pin},
        'manuscript-author':{'request':{}},'manuscript-collect':{'binding':writer},
        'manuscript-build':{'package':pin,'arguments':{'runtime':{},'review_policy':{},'goal_binding':{}}},
        'manuscript-review':{'package':pin,'arguments':{'experiment':'actual','rundir':str(root/'actual')}},
        'manuscript-consume':{'package':pin,'binding':role},
        'manuscript-finalize':{'package':pin,'bindings':[role],'build_binding':{'rundir':str(root/'actual'),'receipt':pin,'result':pin},
            'final_manifest':pin,'completion_request':pin,'rundir':str(root/'actual')}}
    result=decisions.invoke_extension(action,root,args[action],out,host,{'max_wall_seconds':20})
    assert set(decisions.EXTENSION_TRANSPORT)==set(decisions.EXTENSIONS)
    assert set(args[action])==set(decisions.EXTENSION_TRANSPORT[action]['arguments'])
    if action=='manuscript-review':assert result is envelope and calls==['role']
    elif action=='manuscript-author':assert result is writer and calls==['writer']
    elif action=='manuscript-consume':assert calls==['consume']
    elif action=='routine-step':assert result is pin
    else:assert result


@pytest.mark.parametrize('defect',['missing-role','extra-field','authority'])
def test_manuscript_preparation_is_not_replaced_by_generic_role_or_authority(tmp_path,monkeypatch,defect):
    from types import SimpleNamespace
    from ravel.workflow import scientific_judgment
    prepared={'manuscript':{},'role_binding':{'request':{}},'execution_authorized':False}
    if defect=='missing-role':prepared.pop('role_binding')
    elif defect=='extra-field':prepared['review_accepted']=True
    else:prepared['execution_authorized']=True
    monkeypatch.setattr(decisions.importlib,'import_module',lambda name:SimpleNamespace(
        prepare_integrity_role=lambda *a,**kw:prepared))
    calls=[];monkeypatch.setattr(scientific_judgment,'execute_role',lambda *a:calls.append(a))
    with pytest.raises((ValueError,KeyError)):
        decisions.invoke_extension('manuscript-review',tmp_path,{'package':{},'arguments':{}},tmp_path/'out',object(),{})
    assert not calls


def test_actual_agenthost_executes_inline_method_review_before_ordinary_study(tmp_path,monkeypatch):
    # Only the socket transport is replaced. Actual AgentHost.execute builds the
    # request, validates parameters, prepares packet, calls Control and emits the
    # real presentation receipt. This is explicitly inert software telemetry.
    rp,scripted,_,_=open_fixture(tmp_path)
    host=agent_host.AgentHost(endpoint='http://127.0.0.1:1/v1/responses',
        max_request_bytes=METHOD_REQUEST_BYTES,max_response_bytes=1024*1024)
    wires=[]
    def responses(data,parameters,request,control,*,path=None):
        wire=json.loads(data);ctx=json.loads(wire['input'][0]['content']);wires.append((str(control.root),request,ctx))
        item={'id':request['node_id'],'role':ctx['role'],'parameters':parameters}
        public=scripted.callback(item,ctx)
        return host._result(public,parameters,request,observed_model='inert-socket-control')
    monkeypatch.setattr(host,'_responses',responses)
    pass_initial_stages(tmp_path/'campaign',rp,tmp_path/'campaign/coordinator',host,tmp_path,monkeypatch)
    result=orchestration.open_research(tmp_path/'campaign',rp,tmp_path/'campaign/coordinator',host=host)
    assert result['phase']=='ordinary_effect_required'
    _,state=cycle._load(tmp_path/'campaign')
    assert state['experiments'][0]['observation'] is None
    reviews=[(r,q,c) for r,q,c in wires if c['role'] in {'critic','verifier'}]
    assert len(reviews)==2 and all('presentation' not in c['review_packet'] for _,_,c in reviews)
    for graph_root,request,ctx in reviews:
        actual=graph.role_receipt(graph_root,request['node_id'],
            expected_subject_sha256=state['scientific_context_declaration']['request']['sha256'],
            require_exact_subject=False,allowed_roles={ctx['role']})
        presented=actual['isolation']['evidence_presentation']
        assert presented['presentation']['kind']=='complete_inline_role_evidence'
        assert presented['presentation']['all_content_read_by_model'] is False
        assert set(presented['presented_subject_sha256s'])=={
            hashlib.sha256(e['content'].encode()).hexdigest() for e in ctx['review_packet']['artifacts']}


def test_actual_exposure_producer_requires_fresh_charged_design_without_private_bodies(tmp_path,monkeypatch):
    binary=tmp_path/'private-input.bin';binary.write_bytes(b'PRIVATE-WORKER-ONLY\xff\x00')
    private=cycle._pin(binary)
    rp,host,_,_=open_fixture(tmp_path,extra_evidence=[{'pin':private,'purpose':'execution_dependency'}],
        max_request_bytes=METHOD_REQUEST_BYTES)
    original_inputs=science.task_inputs
    # Explicit synthetic operation dependency at the input-provider boundary;
    # canonical plan design, exposure producer, actual model calls and admission
    # are unmocked. No native/binary science evaluation is claimed.
    def inputs(spec,base):
        result=list(original_inputs(spec,base))
        if spec['mode']=='quantities':result.append(binary)
        return result
    monkeypatch.setattr(science,'task_inputs',inputs)
    callback=host.callback
    def decisions_with_private(item,ctx):
        if item['role'] in {'critic','verifier'}:return callback(item,ctx)
        core=json.loads(next(p['content'] for p in ctx['input_artifacts'] if p['id']=='scientific-core'))
        turn=len(core.get('prior_operation_effects',[]))
        if core['phase']=='action' and turn==3:
            previous=core['prior_operation_effects'][-1]['actual_effect']
            assert previous['status']=='prepared_not_admitted'
            exposure=read_json(read_json(previous['prepared_experiment']['path'])['experiment']['input_exposure']['path'])
            assert {r['path']:r['purpose'] for r in exposure['inputs']}[str(binary)]=='execution_dependency'
            return {'kind':'research-action','action':'experiment','reason':'Fresh design sees exact exposure inventory.',
                'arguments_json':json.dumps({'prepared_experiment':previous['prepared_experiment']})}
        return callback(item,ctx)
    host.callback=decisions_with_private
    pass_initial_stages(tmp_path/'campaign',rp,tmp_path/'campaign/coordinator',host,tmp_path,monkeypatch)
    result=orchestration.open_research(tmp_path/'campaign',rp,tmp_path/'campaign/coordinator',host=host)
    assert result['parent_task_accepted'] is False
    _,state=cycle._load(tmp_path/'campaign');assert len(state['experiments'])==1
    e=state['experiments'][0]
    assert private in e['input_pins'] and e['observation'] is None and e['rundir'] is None
    exposure=read_json(e['input_exposure']['path'])
    assert exposure['study']==e['study'] and exposure['whole_worker_custody_retained'] is True
    origins=[row['coordinator_origin'] for row in state['experiments']]
    assert all(private not in origin['inputs'] for origin in origins)
    assert all(not any(a.get('sha256')==private['sha256'] for a in ctx.get('input_artifacts',[]))
        for ctx in host.actual_contexts)
    assert read_json(e['authored_configuration_provenance']['path'])['physics_validated'] is False
    assert state['parent_task']['contract']==decisions.request(rp)['parent_contract']
    prepared=read_json(next(event for event in state['events']
        if event['kind']=='coordinator_effect_committed'
        and read_json(event['effect']['path'])['actual_effect'].get('status')=='prepared_not_admitted')['effect']['path'])
    package=read_json(prepared['actual_effect']['prepared_experiment']['path'])
    with pytest.raises(ValueError,match='whole exposure inventory'):
        cycle._model_input_admission(package['experiment'],e['input_pins'],
            package['original_origin']['inputs'],tmp_path)
    with pytest.raises(ValueError,match='cannot enter this model packet'):
        cycle._model_input_admission(e,e['input_pins'],[*e['coordinator_origin']['inputs'],private],tmp_path)
    binary.write_bytes(b'changed private worker bytes')
    with pytest.raises(ValueError,match='all execution dependencies'):
        cycle._exposure_manifest(e,[cycle._pin(p['path']) for p in e['input_pins']],tmp_path)


def test_actual_committed_premise_revision_recovers_before_effect_checkpoint(tmp_path,monkeypatch):
    source=write(tmp_path/'premise.txt','Explicit original prospective premise; no measurement.')
    premise={'id':'method-assumption','statement':'Old prospective assumption.','basis':[source]}
    rp,host,_,_=open_fixture(tmp_path,extra_evidence=[{'pin':source,'purpose':'model_context'}],
        initial_premises=[premise],max_request_bytes=METHOD_REQUEST_BYTES)
    callback=host.callback
    def revise_once(item,ctx):
        if item['role'] in {'critic','verifier'}:return callback(item,ctx)
        core=json.loads(next(p['content'] for p in ctx['input_artifacts'] if p['id']=='scientific-core'))
        if core['phase']=='action' and len(core.get('prior_operation_effects',[]))==0:
            return {'kind':'research-action','action':'revise-premise','reason':'Actual source-backed revision.',
                'arguments_json':json.dumps({'identity':'method-assumption','statement':'New prospective assumption.',
                    'basis':[source],'reason':'Keep failed/open quantities and reconsider method.'})}
        if core['phase']=='action':
            return {'kind':'research-action','action':'progress','reason':'No scientific result implied.',
                'arguments_json':json.dumps({'reason':'Retain whole question after one source-bound premise change.'})}
        return callback(item,ctx)
    host.callback=revise_once
    original_put=decisions._put;fired=[]
    def crash(path,value):
        if Path(path).name=='coordinator-effect.json' and value['action']=='revise-premise' and not fired:
            fired.append(True);raise RuntimeError('inert failure after canonical premise commit')
        return original_put(path,value)
    monkeypatch.setattr(decisions,'_put',crash)
    root=tmp_path/'campaign';out=root/'coordinator'
    pass_initial_stages(root,rp,out,host,tmp_path,monkeypatch)
    with pytest.raises(RuntimeError,match='after canonical premise commit'):
        orchestration.open_research(root,rp,out,host=host)
    before=cycle._load(root)[1];calls=before['resource_ledger']
    revisions=[event for event in before['events'] if event['kind']=='premise_revised']
    assert len(revisions)==1 and revisions[0]['before_state_sha256']
    result=orchestration.open_research(root,rp,out,host=host)
    after=cycle._load(root)[1]
    assert len([event for event in after['events'] if event['kind']=='premise_revised'])==1
    assert after['premises'][0]['statement']=='New prospective assumption.'
    origin=revisions[0]['coordinator_origin']
    assert cycle._coordinator_effect(after,origin)['document']['actual_effect']['sha256']==read_json(
        root/'history'/f"{revisions[0]['revision']:04d}.json")['sha256']
    assert all(row in after['resource_ledger'] for row in calls)
    assert result['parent_task_accepted'] is False
    with pytest.raises(ValueError,match='actual original decision'):
        cycle.revise_premise(root,'method-assumption','Unrequested replacement.',basis=[source],
            reason='Keep failed/open quantities and reconsider method.',coordinator_origin=origin)


def _record_initial_stage_fixtures(root, base, monkeypatch):
    """Supply explicit synthetic stage artifacts for the isolated transport test.

    The external decision provider and role responses are inert seams here;
    the enforcement controls separately test missing-provider refusal. A reason
    string no longer exempts these mandatory research stages.
    """
    from ravel.workflow import research_protocol as protocol
    from test_research_default_protocol import synthetic_artifacts
    artifacts = synthetic_artifacts(base/'methodology-fixture')
    monkeypatch.setattr(protocol, 'decision_errors', lambda *a, **k: [])
    for stage in ('limitation_census', 'ideas'):
        artifact = write(base/('skip-'+stage+'.json'), artifacts[stage])
        prepared = protocol.prepare_stage(root, stage, artifact, base/('skip-review-'+stage), model='stub')
        def result(graph_root, node_id, stage=stage, prepared=prepared):
            return {'value':{'value':{'stage':stage, 'role_id':node_id,
                'subject_sha256':prepared['subject']['sha256'], 'verdict':'accept',
                'findings':[], 'attributed_claim_ids':[]}}}
        def receipt(graph_root, node_id, stage=stage, **kwargs):
            manifest = read_json(base/('skip-review-'+stage)/node_id/'packet/manifest.json')
            return {'context_transport_separated':True, 'execution_observation':'host_attested_external',
                'presented_subject_sha256s':[r['sha256'] for r in manifest['artifacts']], 'synthetic_stub':True}
        with monkeypatch.context() as patch:
            patch.setattr(cycle, 'validate_graph_reservation', lambda *a: None)
            patch.setattr(cycle, '_graph_result', result)
            patch.setattr(graph, 'role_receipt', receipt)
            status = protocol.complete_stage(root, prepared, base/('skip-graph-'+stage))
        assert next(r for r in status['record']['stages'] if r['id']==stage)['status']=='done'
    preregistration = write(base/'preregistration.json', {'schema_version':1,
        'kind':'research-preregistration', 'approximations':[],
        'selection_rule': {'direction': 'maximize', 'metric': 'response', 'k': 1, 'alpha': .05},
        'stop_rule': {'successes': 1, 'max_rounds': 2, 'budget': 60, 'coverage_floor': 1, 'families': ['synthetic']},
        'expected_effect':{'statement':'Synthetic custody control; no physical inference.'},
        'evaluator_not_applicable':{k:'Supplied arithmetic only; no evaluator applies.'
            for k in ('limit_setter', 'likelihood_builder', 'cutflow_comparator')}})
    protocol.preregister(root, preregistration, {}, evaluation_harness=True)


def _actual_tool_exposure_case(base, monkeypatch, *, private):
    """Real producer/Host/Graph/campaign route; only socket response is inert.

    Private bytes are a synthetic task-input-provider dependency, never native
    data or model content. The real tool-context producer carries an additional
    supplied API plus its complete blueprint/bundle/API/source closure.
    """
    from ravel.workflow import research_tools as tools, research_blueprint as blueprint
    original_task, parent_pin = parent(base)
    method, declared = context(base)
    declared['max_source_bytes'] = 1024 * 1024
    declared['max_context_bytes'] = 128000
    context_pin = write(base/'declared-context.json', declared)
    extra_api = write(base/'additional-tool-api.py',
        'def retained_tool_method(records):\n    return records\n')
    goal = {'contract': parent_pin, 'assignment_id': 'original-task'}
    study, supplied = supplied_study(base, goal)
    binary = base/'private-input.bin'
    binary_pin = None
    if private:
        binary.write_bytes(b'PRIVATE-WORKER-ONLY\xff\x00')
        binary_pin = cycle._pin(binary)
        original_inputs = science.task_inputs
        def inputs(spec, source_base):
            result = list(original_inputs(spec, source_base))
            if spec['mode'] == 'quantities':result.append(binary)
            return result
        monkeypatch.setattr(science, 'task_inputs', inputs)
    mapping = [{'obligation_id':r['id'], 'original':deepcopy(r),
        'quantities':['conditional-variance'] if r['id']=='original-request' else [],
        'method':'Complete supplied signed-pair law; figure and note remain unresolved.',
        'sources':[method], 'unresolved':'' if r['id']=='original-request' else r['statement']}
        for r in original_task['task_requirements']['obligations']]
    campaign = {'id':'complete-tool-exposure', 'budget':{'calls':12, 'output_tokens':50000,
        'wall_seconds':600, 'native_attempts':2}, 'max_experiments':2,
        'exploration_every':2, 'required_experiments':['paired'], 'premises':[]}
    settings = {'model':'inert-source-control', 'reasoning_effort':'high', 'adapter':'model',
        'max_output_tokens':4096, 'max_wall_seconds':30}
    evidence = [{'pin':p, 'purpose':'model_context'} for p in [method, extra_api, *supplied]]
    if private:evidence.append({'pin':binary_pin, 'purpose':'execution_dependency'})
    request = orchestration.prepare_open(parent_pin, base/'request', base_dir=base,
        campaign=campaign, runtime=settings, evidence=evidence, candidate_modes=['quantities'],
        review={'arguments':{}, 'allow_control':True}, max_decisions=4,
        context_request=context_pin, obligation_mapping=mapping)
    value = decisions.request(request)
    root = base/'campaign'
    contract = {'schema_version':1, **deepcopy(value['campaign']),
        'question':value['handoff']['original_request'],
        'scope':'Complete original research assignment; planning/preparation remain intermediate.',
        'context_request':context_pin, 'goal_binding':goal}
    cycle.create(root, contract, base_dir=base, evaluation_harness=True)
    _record_initial_stage_fixtures(root, base, monkeypatch)
    hypotheses = [{'id':identity, 'statement':'Explicit supplied-record rival law.',
        'stream':stream, 'premise_ids':[], 'source_basis':[method], 'parents':[],
        'operator':'limitation_fix', 'identity_signature':{'observable':'relation',
            'scope':'supplied signed records', 'prediction':identity},
        'kill_condition':{'comparison':'differs', 'observable':'relation'},
        'reopening_trigger':{'kind':'changed_input', 'field':'revision', 'op':'gt', 'value':0},
        'what_is_new':None}
        for identity,stream in [('paired-law','speculative'),('separate-law','citation_led')]]
    hp = write(base/'hypotheses.json', hypotheses)
    cycle.propose(root, hypotheses, origin={'kind':'supplied_source', 'pin':hp,
        'description':'Complete explicit synthetic rivals; no model or scientific vote.'})
    experiment = {'id':'paired', 'question':'Measure all supplied signed records.', 'premise_ids':[],
        'parent':None, 'change':'Preserve original signed pair and complete actual tool context.',
        'cost':{'calls':0, 'output_tokens':0, 'wall_seconds':30, 'native_attempts':1},
        'predictions':{'paired-law':'shared', 'separate-law':'independent'},
        'observable':{'pointer':'/quantities/covariance/0/0', 'outcomes':{'shared':1.0, 'independent':5.0}},
        'context_outputs':{'measurement':'outputs/attempt-1/result.json'},
        'acceptance_scope':'supplied_math_diagnostic', 'exploratory':True}
    blueprint_context = blueprint.prepare_context(root, root/'blueprint-context')
    template = write(root/'template/study.json', study)
    files = [{'id':identity, 'path':'inputs/'+filename, 'format':form, 'source':pin}
        for identity,filename,form,pin in [('contract','contract.json','json',supplied[0]),
            ('records','records.jsonl','jsonl',supplied[1])]]
    if private:files.append({'id':'worker-only', 'path':'inputs/private.bin', 'format':'literal', 'source':binary_pin})
    blueprint_request = write(root/'blueprint.json', {'schema_version':1, 'context':blueprint_context,
        'study_template':template, 'files':files,
        'bindings':[{'document':'study', 'pointer':'/task/'+identity, 'file':identity}
            for identity in ('contract','records')],
        'variables':[{'id':'grouping', 'file':'records', 'pointer':'/0/group_id',
            'schema':{'type':'string','enum':['shared','independent']},
            'meaning':'Synthetic signed-record grouping, never a physical calibration.', 'premise_ids':[]}],
        'experiment_template':{k:deepcopy(experiment[k]) for k in blueprint.EXPERIMENT_FIELDS}})
    bundle = tools.prepare(root, blueprint_request, root/'tool-context',
        api_documents=[{'id':'extra-tool-api', 'pin':{k:extra_api[k] for k in ('path','sha256')},
            'language':'python', 'role':'api', 'version':'Supplied engineering source, never imported', 'dependencies':[]}],
        queries=[{'id':'retained-tool-method', 'symbol':'retained_tool_method', 'mode':'definition',
            'documents':['extra-tool-api'], 'required':True}])
    experiment['tool_context'] = bundle
    tool_pins = tools.input_pins(bundle, base)
    assert extra_api in tool_pins
    worker = [cycle._pin(p) for p in science.task_inputs(study, Path(template['path']).parent)]
    complete = cycle._tool_input_closure(experiment, worker, base, state=cycle._load(root)[1])
    assert {p['path'] for p in worker} < {p['path'] for p in complete}
    assert set(p['path'] for p in tool_pins) <= set(p['path'] for p in complete)
    host = agent_host.AgentHost(endpoint='http://127.0.0.1:1/v1/responses',
        max_request_bytes=METHOD_REQUEST_BYTES, max_response_bytes=1024*1024)
    wires = []
    pending = {}
    def responses(data, parameters, request_value, control, *, path=None):
        actual_context = json.loads(json.loads(data)['input'][0]['content'])
        wires.append(deepcopy(actual_context))
        public = {'kind':'research-action','action':'experiment',
            'reason':'Complete source-bound prospective input exposure, not scientific acceptance.',
            'arguments_json':json.dumps(pending['arguments'])}
        return host._result(public, parameters, request_value, observed_model='inert-source-control')
    monkeypatch.setattr(host, '_responses', responses)
    def turn(number, arguments, *, effects=(), omit=(), extra_inputs=()):
        pending['arguments'] = deepcopy(arguments)
        prepared = decisions.prepare_decision(root, value, root/('turn-'+str(number))/'source',
            phase='action', effects=effects)
        names = {p['path'] for p in prepared['inputs']}
        for p in tool_pins:
            if p != binary_pin and p['path'] not in names:
                prepared['inputs'].append(deepcopy(p));names.add(p['path'])
        for p in extra_inputs:
            if p['path'] not in {r['path'] for r in prepared['inputs']}:prepared['inputs'].append(deepcopy(p))
        prepared['inputs'] = [p for p in prepared['inputs'] if p['path'] not in set(omit)]
        spec = decisions.decision_spec(root, prepared, settings, graph_id='tool-design-'+str(number))
        origin = decisions.actual(root, root/('turn-'+str(number))/'graph', prepared, spec,
            host=host, settings=settings)
        assert all(set(p)=={'id','path','sha256'} for p in origin['inputs'])
        return origin
    first_args = {'study':study, 'experiment':experiment, 'source_mapping':mapping, 'records':[]}
    first_origin = turn(1, first_args)
    first = decisions.admit_experiment(root, value, first_origin, root/'turn-1/effect', first_args)
    first_effect = None
    if private:
        assert first['status']=='prepared_not_admitted'
        assert cycle._load(root)[1]['experiments']==[]
        first_effect = write(root/'turn-1/effect/coordinator-effect.json', {'action':'experiment',
            'arguments':first_args, 'origin':first_origin, 'actual_effect':first,
            'parent_task_accepted':False, 'scientific_authority_from_checkpoint':False})
        cycle._record_coordinator_effect(root, first_origin, first_effect)
    return {'root':root, 'base':base, 'value':value, 'settings':settings, 'first':first,
        'first_origin':first_origin, 'first_effect':first_effect, 'turn':turn,
        'tool_pins':tool_pins, 'complete':complete, 'binary':binary_pin, 'wires':wires,
        'request':request, 'extra_api':extra_api}


@pytest.mark.parametrize('private',[False,True])
def test_actual_host_tool_context_uses_complete_public_or_two_turn_worker_custody(tmp_path,monkeypatch,private):
    case = _actual_tool_exposure_case(tmp_path, monkeypatch, private=private)
    root = case['root']
    if private:
        prepared = case['first']['prepared_experiment']
        arguments = {'prepared_experiment':prepared}
        second = case['turn'](2, arguments,
            effects=[{'origin':case['first_origin'],'effect':case['first_effect']}])
        assert prepared not in second['inputs']  # pin3 and Graph records differ honestly.
        assert (prepared['path'],prepared['sha256']) in {(p['path'],p['sha256']) for p in second['inputs']}
        result = decisions.admit_experiment(root, case['value'], second, root/'turn-2/effect', arguments)
        assert result['preparation_origin']==case['first_origin']
        assert result['prepared_experiment']==prepared
    _, state = cycle._load(root)
    assert len(state['experiments'])==1
    experiment = state['experiments'][0]
    assert experiment['input_pins']==case['complete']
    assert experiment['rundir'] is None and experiment['observation'] is None and experiment['adjudication'] is None
    assert state['parent_task']['contract']==case['value']['parent_contract']
    assert state['contract']['budget']==case['value']['campaign']['budget']
    assert cycle._usage(state)['calls']==(2 if private else 1)
    if private:
        manifest = read_json(experiment['input_exposure']['path'])
        assert manifest['study']==experiment['study']
        assert {p['path'] for p in manifest['inputs']}=={p['path'] for p in case['complete']}
        assert {p['path']:p['purpose'] for p in manifest['inputs']}[case['binary']['path']]=='execution_dependency'
        assert (case['binary']['path'],case['binary']['sha256']) not in {
            (p['path'],p['sha256']) for p in experiment['coordinator_origin']['inputs']}
        assert all(not any(a.get('sha256')==case['binary']['sha256'] for a in c['input_artifacts']) for c in case['wires'])
        assert all('PRIVATE-WORKER-ONLY' not in json.dumps(c) for c in case['wires'])
        with pytest.raises(ValueError,match='cannot enter this model packet'):
            cycle._model_input_admission(experiment,experiment['input_pins'],
                [*experiment['coordinator_origin']['inputs'],case['binary']],tmp_path)
    missing = [p for p in experiment['coordinator_origin']['inputs'] if p['path']!=case['extra_api']['path']]
    with pytest.raises(ValueError,match='all explicitly disclosed study sources'):
        cycle._model_input_admission(experiment,experiment['input_pins'],missing,tmp_path)
    Path(case['extra_api']['path']).write_text('def changed_tool_method():\n    return None\n')
    with pytest.raises(ValueError):
        cycle._tool_input_closure(experiment,experiment['input_pins'],tmp_path,state=state)


@pytest.mark.parametrize('defect',['missing-input','size','hash','uncommitted-copy'])
def test_actual_fresh_designer_cannot_admit_absent_changed_or_uncommitted_preparation(tmp_path,monkeypatch,defect):
    case = _actual_tool_exposure_case(tmp_path,monkeypatch,private=True)
    prepared = deepcopy(case['first']['prepared_experiment'])
    omit = ();extra_inputs = ()
    if defect=='missing-input':omit=(prepared['path'],)
    elif defect=='size':prepared['size']+=1
    elif defect=='hash':prepared['sha256']='f'*64
    else:
        copied = tmp_path/'foreign-preparation.json'
        copied.write_bytes(Path(prepared['path']).read_bytes())
        prepared=cycle._pin(copied);extra_inputs=(prepared,)
    arguments={'prepared_experiment':prepared}
    origin=case['turn'](2,arguments,
        effects=[{'origin':case['first_origin'],'effect':case['first_effect']}],omit=omit,extra_inputs=extra_inputs)
    with pytest.raises(ValueError):
        decisions.admit_experiment(case['root'],case['value'],origin,case['root']/'turn-2/effect',arguments)
    _,state=cycle._load(case['root'])
    assert state['experiments']==[] and state['parent_task']['contract']==case['value']['parent_contract']
    assert cycle._usage(state)['calls']==2


@pytest.mark.parametrize('role',['critic','verifier'])
def test_actual_method_reviewer_uses_only_complete_source_bound_packet_without_private_body(tmp_path,monkeypatch,role):
    from ravel.workflow import review_context
    case=_actual_tool_exposure_case(tmp_path,monkeypatch,private=True)
    root=case['root'];value=case['value'];received=[]
    prepared=decisions.prepare_assessment(root,value,root/('method-'+role),role=role)
    spec=decisions.decision_spec(root,prepared,case['settings'],graph_id='actual-method-'+role)
    item=spec['nodes'][0]
    assert item['role']==role and item['inputs']==[] and item['packet']==prepared['packet']
    manifest=review_context.verify_packet(prepared['packet']['path'],
        expected_manifest_sha256=prepared['packet']['manifest_sha256'])
    assert manifest['role']==role and manifest['source_event_sha256']==value['context_request']['sha256']
    assert value['context_request']['path'] in {entry['source_path'] for entry in manifest['artifacts']}
    core=read_json(prepared['core']['path'])
    assert core['original_task']['obligations']==value['handoff']['obligations']
    assert core['question']==value['handoff']['original_request']
    assert {row['pin']['path']:row['purpose'] for row in core['complete_input_inventory']}[case['binary']['path']]=='execution_dependency'
    assert case['binary']['path'] not in {entry['source_path'] for entry in manifest['artifacts']}
    host=agent_host.AgentHost(endpoint='http://127.0.0.1:1/v1/responses',
        max_request_bytes=METHOD_REQUEST_BYTES,max_response_bytes=1024*1024)
    def responses(data,parameters,request,control,*,path=None):
        context=json.loads(json.loads(data)['input'][0]['content']);received.append(context)
        assert context['role']==role and 'input_artifacts' not in context
        assert context['review_packet']['manifest_sha256']==prepared['packet']['manifest_sha256']
        assert 'PRIVATE-WORKER-ONLY' not in json.dumps(context)
        public={'kind':'context-method-assessment','subject_sha256':prepared['subject_sha256'],
            'verdict':'adequate_for_prospective_tests','findings':['All original unresolved deliverables remain.'],
            'summary':'Software-only explicit source-bound prospective judgment, no scientific acceptance.'}
        return host._result(public,parameters,request,observed_model='inert-method-control')
    monkeypatch.setattr(host,'_responses',responses)
    origin=decisions.actual(root,root/('method-'+role+'-graph'),prepared,spec,
        host=host,settings=case['settings'])
    receipt=decisions.assessment_receipt(origin,prepared,allow_control=True)
    assert len(received)==1 and receipt['role']==role
    assert receipt['scientific_independence_proven'] is False and receipt['physics_validated'] is False
    assert {entry['sha256'] for entry in manifest['artifacts']} <= set(receipt['isolation']['evidence_presentation']['presented_subject_sha256s'])
    raw=deepcopy(spec)
    raw['nodes'][0]['inputs']=[{'id':'scientific-subject','path':prepared['subject']['path'],
        'sha256':prepared['subject']['sha256']}]
    with pytest.raises(graph.GraphError,match='blind model roles require a role packet and no extra raw inputs'):
        graph.validate(raw)
    source=Path(prepared['subject']['path']);original=source.read_bytes()
    source.write_bytes(original+b' ')
    with pytest.raises((ValueError,graph.GraphError)):
        decisions.prepare_assessment(root,value,root/('changed-'+role),role=role)
    source.write_bytes(original)
    assert not any(e['observation'] is not None or e['adjudication'] is not None
        for e in cycle._load(root)[1]['experiments'])


def _complete_progress_control(base):
    parent_contract, cp = parent(base)
    _, declared = context(base)
    contract = {'schema_version':1, 'id':'complete-progress-history', 'question':PROMPT,
        'scope':'Actual software-only call receipts; no scientific or model efficacy.',
        'context_request':write(base/'progress-context.json', declared), 'premises':[],
        'budget':{'calls':40, 'output_tokens':0, 'wall_seconds':3600, 'native_attempts':0},
        'max_experiments':6, 'exploration_every':2, 'required_experiments':['paired'],
        'goal_binding':{'contract':cp, 'assignment_id':'original-task'}}
    root=base/'progress-cycle';cycle.create(root,contract,base_dir=base, evaluation_harness=True)
    return root,parent_contract


def test_complete_progress_machine_census_and_human_science_survive_real_long_receipt_history(tmp_path,monkeypatch):
    from ravel.workflow import research_progress, scientific_report
    root, parent_contract = _complete_progress_control(tmp_path)
    host=ToolHost()
    # These are actual ordinary tool Graph receipts/reservations, not fabricated
    # metrics rows. Repeated long paths are genuine custody identities.
    for index in range(15):
        child=root/('complete-source-custody-'+str(index)+'-'+'x'*80)
        observed=cycle.execute_graph(root,child,graph_spec([node('work')],calls=1),host)
        assert observed['complete']
    before=cycle._load(root)[1]
    machine=cycle.progress_synthesis(root,render_text=False)
    human=cycle.progress_synthesis(root)
    assert 'report_text' not in machine
    assert {k:v for k,v in human.items() if k!='report_text'}==machine
    assert len(json.dumps(machine,indent=2).encode())>scientific_report.MAX_TEXT_BYTES
    assert len(human['report_text'].encode())<=scientific_report.MAX_TEXT_BYTES
    assert len(machine['actual_graph_usage'])==len(machine['resource_ledger'])==15
    resource=machine['outcome_metrics']['resource_use']
    assert len(resource['call_receipts'])==15 and resource['calls']['debited_count']==15
    assert len(resource['graphs'])==15 and resource['calls']['provider_invocation_count'] is None
    assert machine['required_experiments']==['paired'] and machine['all_experiments'][0]['status']=='not_designed'
    assert [r['original'] for r in machine['parent_completion_view']['obligation_census']]==parent_contract['task_requirements']['obligations']
    text=human['report_text']
    encoded=text.split('Complete scientific obligations and evidence census:\n',1)[1].split('\n\n## Research outcome instrumentation',1)[0]
    scientific=json.loads(encoded)
    for key,row in scientific.items():assert row==machine[key]
    assert scientific['parent_task']['original_request']==PROMPT
    assert '/outcome_metrics/input_pins' in text and '/resource_ledger' in text
    assert len(machine['outcome_metrics']['input_pins'])>30
    assert not any(machine[k] for k in ['final_delivery','parent_task_accepted','execution_authorized','physics_validated'])
    assert cycle._load(root)[1]==before
    # Rendering remains a separately enforced original text boundary. Structured
    # mode changes neither evidence validation nor scientific/final acceptance.
    monkeypatch.setattr(scientific_report,'MAX_TEXT_BYTES',1)
    with pytest.raises(ValueError,match='existing text budget'):cycle.progress_synthesis(root)
    assert cycle.progress_synthesis(root,render_text=False)==machine
    source=tmp_path/'method.py';source.write_text('def foreign_method():\n    return 0\n')
    with pytest.raises(ValueError):cycle.progress_synthesis(root,render_text=False)


@pytest.mark.parametrize('render_text',[None,0,1,'false'])
def test_progress_render_choice_is_explicit_bool_before_any_source_access(tmp_path,render_text):
    with pytest.raises(ValueError,match='render_text boolean'):
        cycle.progress_synthesis(tmp_path/'absent-campaign',render_text=render_text)


def test_human_progress_keeps_complete_failed_and_open_scientific_rows_without_mutating_census():
    from ravel.workflow import research_progress
    result={'question':PROMPT,'scope':'Supplied rendering software control.', 'research_state_sha256':'a'*64,
        'context_sha256':'b'*64,'accepted_scoped_facts':None,
        'requested_quantity_census':[{'request':{'id':'variance','unit':'1'},'measurement':{'value':5,'passed':False},'status':'failed_quantity_check'}],
        'required_experiments':['failed','open'],
        'all_experiments':[{'id':'failed','question':'Original full negative experiment.', 'outcome':None,
            'observation':{'execution_status':'failed','outcome':None,'result':{'path':'original-result','sha256':'c'*64}},
            'diagnostic_feedback':{'statement':'Exact retained objection; no approved result.'}},
            {'id':'open','status':'not_designed','observation':None,'scientific_acceptance':False}],
        'hypotheses':[{'id':'rival','statement':'Original skeptical alternative.','origin':{'kind':'supplied_source'}}],
        'premises':[{'id':'conditional','statement':'Original unresolved prerequisite.'}],
        'staged_protocol':{'required_stage_ids':['full','ablation'],'complete_scientific_evidence':False},
        'parent_task':{'original_request':PROMPT,'original_obligations':[{'id':'note','statement':'Complete original internal note.'}]},
        'parent_completion_view':{'obligation_census':[{'id':'note','state':'open','contributions':[]}]},
        'resource_ledger':[{'id':'old-failed-reservation','cost':{'calls':2}}], 'actual_graph_usage':[], 'timing':{},
        'operational_boundaries':[{'statement':'Original finite missingness boundary.'}],
        'outcome_metrics':{'original_task':{'state':'unresolved','original_obligation_denominator':1},
            'complete_experiment_census':[{'id':'failed','state':'failed'},{'id':'open','state':'not_designed'}],
            'resource_use':{'calls':{'complete_count':None,'debited_count':2,'observed_count':0,'started_count':1,'ambiguous_count':1}},'utility':None}}
    before=deepcopy(result);text=research_progress._render_text(result)
    assert result==before
    encoded=text.split('Complete scientific obligations and evidence census:\n',1)[1].split('\n\n## Research outcome instrumentation',1)[0]
    projected=json.loads(encoded)
    assert projected['all_experiments']==before['all_experiments'] and projected['requested_quantity_census']==before['requested_quantity_census']
    assert projected['parent_task']==before['parent_task'] and projected['hypotheses']==before['hypotheses']
    assert projected['premises']==before['premises'] and projected['staged_protocol']==before['staged_protocol']
    assert 'Exact retained objection' in text and 'Started records: 1; ambiguous records: 1.' in text
    assert '/outcome_metrics/interventions' in text and '/operational_boundaries' in text


@pytest.mark.parametrize('state',['fresh','valid','stale-approval','malformed-approval',
    'broken-approval-link','changed-input','missing-input','resume-is-not-approval'])
def test_ordinary_approval_gate_distinguishes_fresh_absence_from_invalid_current_custody(tmp_path,monkeypatch,state):
    # Actual ordinary preparation and verifier; no worker/native/model execution.
    _,parent_pin=parent(tmp_path)
    goal={'contract':parent_pin,'assignment_id':'original-task'}
    spec,inputs=supplied_study(tmp_path,goal)
    specification=write(tmp_path/'science.json',spec)
    rundir=tmp_path/'study'
    science.plan(rundir,specification['path']); admit_method(rundir)
    approval=rundir/science.APPROVAL
    holds=[];delegations=[]
    class ExplicitCI1Hold(RuntimeError):pass
    def hold(value):
        holds.append(deepcopy(value))
        if state!='resume-is-not-approval':raise ExplicitCI1Hold('ordinary CHECK-IN 1 is still required')
        return None  # A generic resume payload cannot create an approval receipt.
    def no_delegation(*args,**kwargs):
        delegations.append((args,kwargs))
        raise AssertionError('undelegated supplied study cannot acquire machine authority')
    import langgraph.types
    monkeypatch.setattr(langgraph.types,'interrupt',hold)
    monkeypatch.setattr(science,'approve_delegated',no_delegation)
    if state in {'valid','stale-approval','malformed-approval'}:
        science.approve(rundir,'Explicit root software-control assent; no physicist or scientific review.',scripted=True)
        receipt=read_json(approval)
        assert receipt['expert_review'] is False and receipt['approval_mode']=='scripted_yes'
        if state=='stale-approval':
            receipt['plan_sha256']='0'*64;atomic_json(approval,receipt)
        elif state=='malformed-approval':approval.write_text('{invalid original receipt\n')
    elif state=='broken-approval-link':approval.symlink_to(rundir/'nonexistent-original-receipt')
    elif state=='changed-input':Path(inputs[1]['path']).write_text('foreign incomplete record population\n')
    elif state=='missing-input':Path(inputs[1]['path']).unlink()
    before=(os.readlink(approval) if approval.is_symlink() else approval.read_bytes() if approval.exists() else None)
    if state=='valid':
        assert orchestration._ordinary_approval_gate(rundir,selected='paired',goal_binding=goal) is None
        science.verify_plan(rundir,approved=True)
        assert not holds
    elif state=='fresh':
        with pytest.raises(ExplicitCI1Hold):
            orchestration._ordinary_approval_gate(rundir,selected='paired',goal_binding=goal)
        assert holds==[{'kind':'ordinary_checkin1_and_machine_lease_required','rundir':str(rundir),
            'selected':'paired','original_goal_binding':goal,'approval_from_resume':False}]
        science.verify_plan(rundir,approved=False)
    else:
        with pytest.raises((ValueError,FileNotFoundError)):
            orchestration._ordinary_approval_gate(rundir,selected='paired',goal_binding=goal)
        assert len(holds)==(1 if state=='resume-is-not-approval' else 0)
    assert not delegations
    after=(os.readlink(approval) if approval.is_symlink() else approval.read_bytes() if approval.exists() else None)
    assert after==before  # Existing receipt/link bytes survive; fresh absence stays absent.
    assert not (rundir/'execution_attempt.json').exists()
    assert not (rundir/'outputs/attempt-1/result.json').exists()
