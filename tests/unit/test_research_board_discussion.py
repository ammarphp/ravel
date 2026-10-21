"""Real board/cycle/Graph/Host receipt controls with an INERT model transport.

No provider, role-review, scientific worker, external process or physics runs.
The final ordinary preparation is an explicitly recorded source-only sentinel.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import pytest

from ravel import cli
from ravel.workflow import agent_host, execution, hypothesis_board as board, research_cycle as cycle
from ravel.workflow import research_board_discussion as meeting, science, state_io


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, str): path.write_text(value)
    else: state_io.atomic_json(path, value)
    return cycle._pin(path)


def contract(base):
    source = write(base/'api.py', 'def paired_square(x):\n    return sum(x)**2\n')
    request = {'schema_version': 1, 'task_id': 'original-whole-question',
        'task': 'Retain the paired signed population and all alternative explanations.',
        'source_capsules': [], 'api_documents': [{'id': 'api',
            'pin': {k: source[k] for k in ('path','sha256')}, 'language': 'python', 'role': 'api',
            'version': 'Authored inert arithmetic fixture', 'dependencies': []}],
        'queries': [{'id': 'math', 'symbol': 'paired_square', 'mode': 'definition',
            'documents': ['api'], 'required': True}],
        'requested_quantities': [{'id': 'paired', 'artifact': 'measurement',
            'pointer': '/quantities/covariance', 'check': {'kind': 'exact', 'value': [[1.0]]},
            'meaning': 'Two signed records; software fixture, no physics law.'}],
        'compatibility_groups': [{'id': 'whole', 'artifacts': ['measurement'], 'carryover': False,
            'basis': 'Every prospective design retains the complete supplied population.'}],
        'max_source_bytes': 16000, 'max_context_bytes': 16000, 'max_steps': 4}
    return {'schema_version': 1, 'id': 'whole-original-cycle',
        'question': 'Which supplied group interpretation distinguishes the paired signed variance?',
        'scope': 'Explicit software transport control; no model efficacy or physics.',
        'context_request': write(base/'context.json', request),
        'premises': [{'id': 'population', 'statement': 'Every original record stays retained.', 'basis': []}],
        'budget': {'calls': 20, 'output_tokens': 8192, 'wall_seconds': 600, 'native_attempts': 4},
        'max_experiments': 6, 'exploration_every': 2, 'required_experiments': ['paired']}


def candidate(base, ids):
    d=base/'candidate'; d.mkdir()
    write(d/'contract.json', {'schema_version':1, 'axes':[{'name':'x','unit':'1'}],
        'bins':[{'id':'one','low':[0.0],'high':[1.0]}], 'weight_names':['nominal'],
        'input_weight_unit':'1','representation':'integrated',
        'normalization':{'kind':'absolute','scale':1.0,'unit':'1'}})
    write(d/'records.jsonl', '\n'.join(json.dumps({'event_id':e,'group_id':'one','shard_id':'toy',
        'weights':{'nominal':w},'fills':[[.5]]}) for e,w in [('a',2),('b',-1)])+'\n')
    policy={'schema_version':1,'actors':{'proposer':'fixture-proposer','executor':'fixture-executor',
        'physics_critic':'fixture-critic','skeptical_verifier':'fixture-verifier','physics_decider':'fixture-decider'},
        'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
        'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'math','kind':'scientific'}],
        'claim_scopes':{'supplied_math':{'checks':['integrity','math'],'actions':['delivery','reuse']}}}
    spec={'schema_version':2,'mode':'quantities','source':'Authored signed-record fixture.',
        'assumptions':['Software source control only.'], 'max_seconds':30,'max_attempts':1,
        'approval_mode':'scripted_yes','task':{'contract':'contract.json','records':'records.jsonl'},
        'review_policy':{'schema_version':1,'policy':policy,'correction_contract':{'task_fields':[],'input_slots':[]}}}
    return {'id':'paired','question':'Measure the complete paired signed records.',
        'premise_ids':['population'],'parent':None,'change':'Use a declared common group.',
        'study':write(d/'study.json',spec),'cost':{'calls':0,'output_tokens':0,'wall_seconds':30,'native_attempts':1},
        'predictions':{x: 'shared' if i==0 else 'independent' if i==1 else None for i,x in enumerate(ids)},
        'observable':{'pointer':'/quantities/covariance/0/0','outcomes':{'shared':1.0,'independent':5.0}},
        'context_outputs':{'measurement':'outputs/attempt-1/result.json'},'acceptance_scope':'supplied_math','exploratory':True}


@pytest.fixture(autouse=True)
def inert_boundary(monkeypatch):
    monkeypatch.setattr(execution,'runtime_context',lambda:{'inert_software_control':True,
        'environment_sha256':execution.digest(execution.runtime_environment())})
    def denied(*a,**k): raise AssertionError('No external process/scientific worker allowed')
    monkeypatch.setattr(subprocess,'Popen',denied)


def setup(base, *, reveal=True, hypotheses_per_actor=1, evidence=True, custody='frozen_bytes', budget=None, imported=True):
    root=base/'cycle'; c=contract(base)
    if budget: c['budget'].update(budget)
    cycle.create(root,c,base_dir=base, evaluation_harness=True)
    policy={'schema_version':1,'board_id':'sealed-original',
        'participants':[{'actor_id':a,'session_id':'session-'+a,'model_id':'fixture-only',
            'fresh_generation':True} for a in ['alpha','beta']],
        'prediction_keys':['shape'],'limits':dict(board.DEFAULT_LIMITS),'artifact_pins':[]}
    observations=[]
    if evidence:
        pin=write(base/'located.txt','An original observation, retaining the missing mechanism.\n')
        policy['artifact_pins']=[{'id':'located','kind':'narrative','sha256':pin['sha256'],
            'size':pin['size'],'custody':custody}]
        observations=[{'id':'located','pin':pin,'missing_reason':None}]
    br=base/'board';board.create(br,policy,artifacts={'located':base/'located.txt'} if evidence and custody=='frozen_bytes' else {})
    submissions=[]
    for a in ['alpha','beta']:
        hypotheses=[{'id':'H'+str(i),'statement': a+' original minority '+str(i),
            'predictions':{'shape':'up' if a=='alpha' else None},'artifact_refs':[],
            'contradicts':[]} for i in range(hypotheses_per_actor)]
        submissions.append({'schema_version':1,'actor_id':a,'session_id':'session-'+a,
            'nonce':'independent-original-nonce-'+a,'hypotheses':hypotheses})
    for v in submissions:board.commit(br,v['actor_id'],board.submission_digest(policy,v))
    if reveal:
        for v in submissions:board.reveal(br,v)
        if imported: cycle.import_board(root,br,streams={'alpha':'citation_led','beta':'speculative'})
    options={'arm':'discussion','participant_order':['alpha','beta'],
        'designer':{'actor_id':'designer','session_id':'session-designer','model_id':'fixture-only'},
        'final_reviewers':[{'actor_id':a,'session_id':'session-'+a,'model_id':'future-only'} for a in ['critic','verifier']],
        'observations':observations,'candidates':[], 'max_output_tokens':128,'max_wall_seconds':10,
        'reasoning_effort':'low','adapter':'responses'}
    return root,br,options


def prepared(base, *, design=False, **options):
    root,br,opts=setup(base,**options)
    if design:
        opts['candidates']=[candidate(base,[h['id'] for h in cycle._load(root)[1]['hypotheses']])]
    pin=meeting.prepare(root,br,base/'arm',**opts)
    return root,opts,pin


def fake_host(base,root,monkeypatch,*,change=None,fail_at=None):
    host=agent_host.AgentHost(endpoint='http://127.0.0.1:9/v1/responses')
    contexts=[]; ledger_sizes=[]
    def response(data,params,request,control):
        index=len(contexts)
        # This is an explicit deterministic stand-in. Inspect real Host-published
        # contents and retained contexts, not a provider response or role vote.
        context=state_io.read_json(base/'arm'/('context-'+str(index)+'.json'))
        presented=json.dumps(json.loads(data)['input'])
        assert context['question'] in presented
        contexts.append(context);ledger_sizes.append(len(cycle._load(root)[1]['resource_ledger']))
        if index==fail_at: raise RuntimeError('explicit inert transport failure')
        ids=[h['id'] for h in context['retained_hypotheses']]
        basis=[r['pin'] for r in context['observations'] if r['pin'] is not None]
        value={'retained_hypothesis_ids':ids,'edges':[{'kind':'missing_premise',
            'hypothesis_ids':ids,'statement':'The mechanism needs a supplied source intervention.',
            'source_basis':basis}],
            'proposals':[{'kind':'acquisition','question':'Acquire the missing pairing law.',
                'hypothesis_ids':ids,'missing_inputs':['pairing intervention'],
                'expected_outcomes':[{'label':'new-law','prediction':None}], 'source_basis':basis}],
            'selected_experiment':'paired' if context['designer'] and context['candidates'] else None,
            'reason':'Keep minority explanations and ask for a discriminating source test.'}
        if change: change(index,value,context)
        return host._result(value,params,request,response_id='inert-only-'+str(index),
            observed_model='fixture-only',usage={'input_tokens':10,'output_tokens':10})
    monkeypatch.setattr(host,'_responses',response)
    return host,contexts,ledger_sizes


def test_discussion_complete_real_graph_adoption_and_ordinary_prepare(tmp_path,monkeypatch):
    root,opts,pin=prepared(tmp_path,design=True)
    before=cycle._load(root)[1];host,contexts,sizes=fake_host(tmp_path,root,monkeypatch)
    report_pin=meeting.run(root,pin,host=host);report=state_io.read_json(report_pin['path'])
    assert report['complete'] and sizes==[3,3,3]
    assert [len(x['prior_turns']) for x in contexts]==[0,1,2]
    assert all(len(x['retained_hypotheses'])==2 for x in contexts)
    assert report['all_original_hypotheses']==before['hypotheses']
    assert len(report['raw_turns'])==3 and len(report['actual_graph_observations'])==3
    assert all(x['usage']['calls']==1 for x in report['actual_graph_observations'])
    after=meeting.adopt(root,report_pin)
    assert after['experiments'][0]['discrimination']['observed_discrimination'] is False
    assert after['experiments'][0]['constructive_origin']['independent_scientific_review'] is False
    assert after['contract']==before['contract'] and after['context']==before['context']
    assert cycle.select(root)['selected']=='paired'
    calls=[]
    actual_plan = science.plan
    def source_only(rd, source, **kwargs):
        calls.append((rd, source))
        return actual_plan(rd, source, **kwargs)
    monkeypatch.setattr(science,'plan',source_only)
    cycle.prepare_experiment(root,'paired',tmp_path/'ordinary-prepared')
    assert len(calls)==1 and not list((tmp_path/'ordinary-prepared'/'outputs').rglob('result.json'))
    assert not (tmp_path/'ordinary-prepared'/'execution_attempt.json').exists()
    assert cycle._usage(cycle._load(root)[1])['native_attempts']==1
    assert cycle.status(root)['connected_task_complete'] is False


def test_isolated_matches_ceiling_without_prior_peer_context(tmp_path,monkeypatch):
    root,br,opts=setup(tmp_path);opts['arm']='isolated'
    pin=meeting.prepare(root,br,tmp_path/'arm',**opts)
    host,contexts,sizes=fake_host(tmp_path,root,monkeypatch)
    report=state_io.read_json(meeting.run(root,pin,host=host)['path'])
    assert [len(c['retained_hypotheses']) for c in contexts]==[1,1,2]
    assert [len(c['prior_turns']) for c in contexts]==[0,0,2]
    assert [h['actor_id'] for h in contexts[0]['original_board_hypotheses']]==['alpha']
    assert [h['actor_id'] for h in contexts[1]['original_board_hypotheses']]==['beta']
    assert report['reserved_ceiling']=={'calls':3,'output_tokens':384,'wall_seconds':30,'native_attempts':0}
    assert report['matched_declared_not_measured_equal_cost'] and not report['outside_api_blinding_proven']
    assert not report['final_review_contexts_created']
    result=meeting.adopt(root,cycle._pin(tmp_path/'arm'/'report.json'))
    assert result['kind']=='research_board_acquisition_proposal' and not result['design_adopted']
    assert cycle._load(root)[1]['experiments']==[]


def test_reveal_barrier_before_any_preparation(tmp_path):
    root,br,opts=setup(tmp_path,reveal=False)
    with pytest.raises(ValueError,match='reveals'):meeting.prepare(root,br,tmp_path/'arm',**opts)
    assert not (tmp_path/'arm').exists()


@pytest.mark.parametrize('kind',['omit_participant','duplicate_participant','review_actor','review_session'])
def test_complete_population_and_independent_final_identities(tmp_path,kind):
    root,br,opts=setup(tmp_path)
    if kind=='omit_participant':opts['participant_order']=['alpha']
    if kind=='duplicate_participant':opts['participant_order']=['alpha','alpha']
    if kind=='review_actor':opts['final_reviewers'][0]['actor_id']='alpha'
    if kind=='review_session':opts['designer']['session_id']='session-verifier'
    with pytest.raises(ValueError):meeting.prepare(root,br,tmp_path/'arm',**opts)
    assert not (tmp_path/'arm').exists()


@pytest.mark.parametrize('key',['calls','output_tokens','wall_seconds'])
def test_complete_budget_refusal_makes_zero_calls_or_partial_reservations(tmp_path,monkeypatch,key):
    bounds={'calls':2,'output_tokens':383,'wall_seconds':29}
    root,opts,pin=prepared(tmp_path,budget={key:bounds[key]})
    before=cycle._load(root)[1];host,contexts,_=fake_host(tmp_path,root,monkeypatch)
    with pytest.raises((ValueError,cycle.OperationalBoundaryError)):meeting.run(root,pin,host=host)
    assert contexts==[] and cycle._load(root)[1]==before
    assert not list((tmp_path/'arm').glob('graph-*'))


def test_failed_turn_retains_unused_reservations_raw_history_no_retry(tmp_path,monkeypatch):
    root,opts,pin=prepared(tmp_path)
    host,contexts,sizes=fake_host(tmp_path,root,monkeypatch,fail_at=1)
    report_pin=meeting.run(root,pin,host=host);report=state_io.read_json(report_pin['path'])
    assert not report['complete'] and len(report['turns'])==1 and len(contexts)==2
    assert len(report['reserved_turns'])==3 and len(report['actual_graph_observations'])==2
    assert report['actual_graph_observations'][-1]['complete'] is False
    assert (tmp_path/'arm'/'graph-1'/'calls').is_dir()
    with pytest.raises(ValueError,match='retry'):meeting.run(root,pin,host=host)
    with pytest.raises(ValueError,match='incomplete'):meeting.adopt(root,report_pin)
    assert len(contexts)==2


@pytest.mark.parametrize('kind',['minority','unknown_hypothesis','unpresented_source','early_selection'])
def test_invalid_turn_stops_and_preserves_raw_before_semantic_refusal(tmp_path,monkeypatch,kind):
    root,opts,pin=prepared(tmp_path)
    def change(i,v,c):
        if i!=0:return
        if kind=='minority':v['retained_hypothesis_ids'].pop()
        if kind=='unknown_hypothesis':v['edges'][0]['hypothesis_ids']=['fabricated']
        if kind=='unpresented_source':v['edges'][0]['source_basis']=[{'path':'/absent','sha256':'0'*64,'size':1}]
        if kind=='early_selection':v['selected_experiment']='paired'
    host,contexts,_=fake_host(tmp_path,root,monkeypatch,change=change)
    report=state_io.read_json(meeting.run(root,pin,host=host)['path'])
    assert not report['complete'] and report['turns']==[] and len(report['raw_turns'])==1
    assert len(contexts)==1 and len(report['reserved_turns'])==3


@pytest.mark.parametrize('key',['observations','physics_validated','reserved_ceiling','original_experiment_history'])
def test_resealed_report_cannot_drop_inputs_usage_or_invent_authority(tmp_path,monkeypatch,key):
    root,opts,pin=prepared(tmp_path);host,_,_=fake_host(tmp_path,root,monkeypatch)
    report=state_io.read_json(meeting.run(root,pin,host=host)['path'])
    if key=='physics_validated':report[key]=True
    elif key=='reserved_ceiling':report[key]['calls']=1
    elif key=='original_experiment_history':report[key]=[{'invented':'accepted'}]
    else:report[key]=[]
    forged=write(tmp_path/'forged.json',report)
    with pytest.raises(ValueError,match='whole retained report'):meeting.adopt(root,forged)
    assert cycle._load(root)[1]['experiments']==[]


def test_observation_change_after_preparation_refuses_before_dispatch(tmp_path,monkeypatch):
    root,opts,pin=prepared(tmp_path);(tmp_path/'located.txt').write_text('changed')
    host,contexts,_=fake_host(tmp_path,root,monkeypatch)
    with pytest.raises(ValueError):meeting.run(root,pin,host=host)
    assert contexts==[]


def test_changed_source_during_first_turn_retains_failure_and_all_rivals(tmp_path,monkeypatch):
    root,opts,pin=prepared(tmp_path)
    def change(i,v,c):
        if i==0:(tmp_path/'located.txt').write_text('changed within transport')
    host,contexts,_=fake_host(tmp_path,root,monkeypatch,change=change)
    report=state_io.read_json(meeting.run(root,pin,host=host)['path'])
    assert not report['complete'] and len(report['all_original_hypotheses'])==2
    assert len(contexts)==1 and len(report['raw_turns'])==1


def test_candidate_must_cover_unknown_minority_prediction(tmp_path):
    root,br,opts=setup(tmp_path)
    opts['candidates']=[candidate(tmp_path,[cycle._load(root)[1]['hypotheses'][0]['id']])]
    with pytest.raises(ValueError,match='every retained'):meeting.prepare(root,br,tmp_path/'arm',**opts)


def test_declared_missing_evidence_routes_to_explicit_acquisition(tmp_path,monkeypatch):
    root,br,opts=setup(tmp_path,custody='declared_digest')
    opts['observations'][0].update(pin=None,missing_reason='Original bytes not yet acquired')
    pin=meeting.prepare(root,br,tmp_path/'arm',**opts)
    host,contexts,_=fake_host(tmp_path,root,monkeypatch)
    result=meeting.adopt(root,meeting.run(root,pin,host=host))
    assert contexts[0]['observations'][0]['content_base64'] is None
    assert result['proposals'][0]['missing_inputs']==['pairing intervention']
    assert not result['execution_authorized']


def test_frozen_evidence_cannot_be_silently_declared_missing(tmp_path):
    root,br,opts=setup(tmp_path);opts['observations'][0].update(pin=None,missing_reason='skip')
    with pytest.raises(ValueError,match='frozen'):meeting.prepare(root,br,tmp_path/'arm',**opts)


def test_board_population_above16_imports_whole_census_atomically(tmp_path):
    root,br,opts=setup(tmp_path,hypotheses_per_actor=10,evidence=False)
    state=cycle._load(root)[1]
    assert len(state['hypotheses'])==20
    assert state['events'][-1]['kind']=='competing_hypotheses_proposed'
    assert len(state['events'][-1]['ids'])==20
    assert len(board.snapshot(br)['hypotheses'])==20
    meeting.prepare(root,br,tmp_path/'arm',**opts)


def test_cli_prepare_is_public_metadata_only_and_strict(tmp_path,capsys):
    root,br,opts=setup(tmp_path)
    request=write(tmp_path/'request.json',{'board_root':str(br),'output_dir':str(tmp_path/'arm'),**opts})
    assert cli.main(['research-cycle','discussion-prepare','--cycle',str(root),'--request',request['path']])==0
    pin=json.loads(capsys.readouterr().out)
    assert pin==cycle._pin(tmp_path/'arm'/'preparation.json')
    assert cycle._load(root)[1]['resource_ledger']==[]
    assert not list((tmp_path/'arm').glob('graph-*'))


def test_resealed_preparation_cannot_shrink_population_or_add_review_actor(tmp_path,monkeypatch):
    root,opts,pin=prepared(tmp_path);v=state_io.read_json(pin['path'])
    v['participant_order']=['alpha'];v['matched_declared_ceiling']['calls']=2
    forged=write(tmp_path/'forged-preparation.json',v)
    host,contexts,_=fake_host(tmp_path,root,monkeypatch)
    with pytest.raises(ValueError):meeting.run(root,forged,host=host)
    assert contexts==[]


@pytest.mark.parametrize('kind', ['late_invalid', 'collision', 'over_capacity'])
def test_whole_import_refuses_before_any_state_or_output_publication(tmp_path, monkeypatch, kind):
    root,br,opts=setup(tmp_path, imported=False, hypotheses_per_actor=17, evidence=False)
    before=cycle._load(root)[1]
    streams={'alpha':'citation_led','beta':'speculative'}
    if kind=='late_invalid': streams['beta']='invalid-stream'
    if kind=='collision': monkeypatch.setattr(cycle,'_board_hypothesis_id',lambda *args:'forced-collision')
    if kind=='over_capacity':
        rows=[{'id':'preexisting-'+str(i),'statement':'Retain rival '+str(i),'stream':'speculative',
            'premise_ids':[],'source_basis':[],'parents':[]} for i in range(32)]
        for i in [0,16]:
            chunk=rows[i:i+16]
            cycle.propose(root,chunk,origin={'kind':'supplied_source',
                'pin':write(tmp_path/('prior-'+str(i)+'.json'),chunk),'description':'Explicit fixture source.'})
        before=cycle._load(root)[1]
    with pytest.raises(ValueError):cycle.import_board(root,br,streams=streams)
    assert cycle._load(root)[1]==before
    assert not (root/'board-proposals').exists()


def test_public_import_then_discussion_has_complete_inverse_mapping(tmp_path,monkeypatch,capsys):
    root,br,opts=setup(tmp_path,imported=False)
    request=write(tmp_path/'import-request.json',{'board_root':str(br),
        'streams':{'alpha':'citation_led','beta':'speculative'}})
    assert cli.main(['research-cycle','import-board','--cycle',str(root),'--request',request['path']])==0
    imported=json.loads(capsys.readouterr().out)
    assert len(imported['hypotheses'])==2
    view=board.snapshot(br)
    ids=[cycle._board_hypothesis_id(view['charter_sha256'], h['actor_id'], h['hypothesis_id'], h['hypothesis_sha256'])
        for h in view['hypotheses']]
    assert all(':' not in h and len(h)<=128 for h in ids)
    assert [h['id'] for h in imported['hypotheses']]==ids
    pin=meeting.prepare(root,br,tmp_path/'arm',**opts)
    host,contexts,_=fake_host(tmp_path,root,monkeypatch)
    report=state_io.read_json(meeting.run(root,pin,host=host)['path'])
    assert len(report['hypothesis_mapping'])==2
    assert [h['hypothesis_id'] for h in report['hypothesis_mapping']]==['H0','H0']
    assert {h['actor_id'] for h in report['hypothesis_mapping']}=={'alpha','beta'}
    assert {h['cycle_hypothesis_id'] for h in report['hypothesis_mapping']}==set(ids)
    before=cycle._load(root)[1]
    with pytest.raises(ValueError,match='already'):cycle.import_board(root,br,streams={'alpha':'citation_led','beta':'speculative'})
    assert cycle._load(root)[1]==before


def test_board_id_and_claim_bytes_change_cycle_identity():
    base=cycle._board_hypothesis_id('a'*64,'actor','H1','b'*64)
    assert len({base,cycle._board_hypothesis_id('c'*64,'actor','H1','b'*64),
        cycle._board_hypothesis_id('a'*64,'other','H1','b'*64),
        cycle._board_hypothesis_id('a'*64,'actor','H2','b'*64),
        cycle._board_hypothesis_id('a'*64,'actor','H1','d'*64)})==5


def test_relative_pin_resolves_to_original_destination(tmp_path,monkeypatch):
    root,opts,pin=prepared(tmp_path)
    pin['path']='arm/preparation.json'
    host,contexts,_=fake_host(tmp_path,root,monkeypatch)
    assert state_io.read_json(meeting.run(root,pin,host=host)['path'])['complete']
    assert len(contexts)==3


def test_copied_preparation_cannot_redirect_writes_inside_original_cycle(tmp_path,monkeypatch):
    root,opts,pin=prepared(tmp_path)
    copied=write(root/'injected'/'preparation.json',state_io.read_json(pin['path']))
    host,contexts,_=fake_host(tmp_path,root,monkeypatch)
    with pytest.raises(ValueError,match='location'):meeting.run(root,copied,host=host)
    assert contexts==[] and not (root/'injected'/'graph-0').exists()


@pytest.mark.parametrize('which',['raw','checked'])
def test_resealed_report_cannot_bless_modified_turn_file(tmp_path,monkeypatch,which):
    root,opts,pin=prepared(tmp_path);host,_,_=fake_host(tmp_path,root,monkeypatch)
    report=state_io.read_json(meeting.run(root,pin,host=host)['path'])
    key='raw_turns' if which=='raw' else 'checked_turns'
    row=report[key][0]; value=state_io.read_json(row['path']);value['invented']='different raw bytes'
    report[key][0]=write(Path(row['path']),value)
    forged=write(tmp_path/'forged-report.json',report)
    with pytest.raises(ValueError,match='commitments'):meeting.adopt(root,forged)
    assert not cycle._load(root)[1]['experiments']



def test_public_run_and_adopt_keep_ordinary_prospective_gate(tmp_path,monkeypatch,capsys):
    root,opts,pin=prepared(tmp_path,design=True)
    host,contexts,_=fake_host(tmp_path,root,monkeypatch)
    monkeypatch.setattr(agent_host,'AgentHost',lambda:host)
    req=write(tmp_path/'run-request.json',{'preparation_pin':pin})
    assert cli.main(['research-cycle','discussion-run','--cycle',str(root),'--request',req['path']])==0
    report_pin=json.loads(capsys.readouterr().out)
    req=write(tmp_path/'adopt-request.json',{'report_pin':report_pin})
    assert cli.main(['research-cycle','discussion-adopt','--cycle',str(root),'--request',req['path']])==0
    result=json.loads(capsys.readouterr().out)
    assert len(contexts)==3 and len(result['experiments'])==1
    assert result['experiments'][0]['rundir'] is None
    assert not result['experiments'][0]['constructive_origin']['independent_scientific_review']
    assert not cycle.status(root)['connected_task_complete']


def test_ending_observation_change_refuses_adoption_before_commit(tmp_path,monkeypatch):
    root,opts,pin=prepared(tmp_path,design=True);host,_,_=fake_host(tmp_path,root,monkeypatch)
    report_pin=meeting.run(root,pin,host=host)
    original=cycle._graph_result;count=[]
    def changed(*a,**k):
        result=original(*a,**k);count.append(1)
        if len(count)==3:(tmp_path/'located.txt').write_text('late source mutation before design commit')
        return result
    monkeypatch.setattr(cycle,'_graph_result',changed)
    with pytest.raises(ValueError):meeting.adopt(root,report_pin)
    assert not cycle._load(root)[1]['experiments']


def test_second_arm_charges_same_cumulative_budget_without_reset(tmp_path,monkeypatch):
    root,br,opts=setup(tmp_path);pin=meeting.prepare(root,br,tmp_path/'arm',**opts)
    host,_,_=fake_host(tmp_path,root,monkeypatch);meeting.run(root,pin,host=host)
    opts['arm']='isolated';second=meeting.prepare(root,br,tmp_path/'second-arm',**opts)
    # A source-only refusal before dispatch documents that a second prepared
    # arm does not reset resource usage; the normal ledger has all first calls.
    after=cycle._load(root)[1]
    assert cycle._usage(after)['calls']==3
    meeting._reserve(root,state_io.read_json(second['path']),tmp_path/'second-arm')
    assert cycle._usage(cycle._load(root)[1])['calls']==6
    assert len(cycle._load(root)[1]['graphs'])==3


def test_candidate_input_exposure_preserves_whole_worker_without_model_bytes(tmp_path,monkeypatch):
    root,br,opts=setup(tmp_path)
    e=candidate(tmp_path,[h['id'] for h in cycle._load(root)[1]['hypotheses']])
    deps=[cycle._pin(p) for p in science.task_inputs(state_io.read_json(e['study']['path']),Path(e['study']['path']).parent)]
    hidden=next(p for p in deps if Path(p['path']).name=='records.jsonl')
    e=cycle.bind_input_exposure(e,{p['path']:'withheld_evaluation' if p==hidden else 'model_context' for p in deps},
        tmp_path/'exposure',base_dir=tmp_path,reason='Explicit fixture heldout-content control, no OS privacy.')
    opts['candidates']=[e];pin=meeting.prepare(root,br,tmp_path/'arm',**opts)
    prepared_value=state_io.read_json(pin['path'])
    assert hidden in prepared_value['candidates'][0]['input_pins']
    assert hidden not in prepared_value['candidates'][0]['model_input_pins']
    host,contexts,_=fake_host(tmp_path,root,monkeypatch)
    report=meeting.run(root,pin,host=host)
    graph_spec=state_io.read_json(tmp_path/'arm'/'graph-2'/'graph_spec.json')
    actual_inputs=graph_spec['nodes'][0]['inputs']
    assert not any(p['sha256']==hidden['sha256'] for p in actual_inputs)
    assert any(p['sha256']==e['input_exposure']['sha256'] for p in actual_inputs)
    result=meeting.adopt(root,report)
    assert result['experiments'][0]['input_pins']==deps
