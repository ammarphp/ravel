"""Software-only ordinary journal + accounted fake-role controls; no processes/network."""
from copy import deepcopy
from pathlib import Path
import pytest
from ravel.workflow import scientific_judgment as j, agent_graph as graph, physics_review as review, review_context as context
from ravel.workflow import execution, agent_host
from ravel.workflow.state_io import read_json, atomic_json
from test_physics_review import run, opened, finding, make_attempt, check_packet

class FakeHost:
    identity = {"fixture": "accounted fake transport; zero native/model/network calls"}
    def __init__(self, *, verdict='accept', proposal=None, proposal_verdict='adequate_for_bounded_test', mutate=None, closes=()):
        self.verdict, self.proposal, self.pverdict, self.mutate = verdict, proposal, proposal_verdict, mutate
        self.closes=list(closes)
    def execute(self,node,request,control):
        packet=Path(node['packet']['path']); manifest=read_json(packet/'manifest.json')
        subject=next(a['sha256'] for a in manifest['artifacts'] if a['id']=='judgment_request')
        contract=read_json(next(packet/a['path'] for a in manifest['artifacts'] if a['id']=='judgment_request'))
        case=read_json(contract['case_pin']['path'])
        audit={'case_sha256':execution.digest(case),'nodes':[{'id':n['id'],'decision':'supported','reason':'Synthetic evidence review only',
            'assumptions':[{'disposition':'accepted','reason':'Synthetic domain check'} for a in n['assumptions']]} for n in case['nodes']],
            'edges':[{'parent':e['parent'],'child':e['child'],'decision':'supported','reason':'Synthetic located link'} for e in case['edges']]}
        value={'schema_version':1,'kind':'scientific_review','subject_sha256':subject,'verdict':self.verdict,'summary':'Synthetic finite source control only',
            'findings':[finding()] if self.verdict=='send_back' else [],'closes':self.closes,'claim_scope':contract['claim_scope'] if self.verdict=='accept' else None,
            'audit':audit,'proposal':None,'proposal_verdict':None}
        if contract['phase']=='improvement':
            value.update(kind='scientific_repair_proposal',verdict=None,claim_scope=None,findings=[],proposal=deepcopy(self.proposal))
        if contract['phase']=='repair_design':
            value.update(kind='scientific_repair_design_review',verdict=None,claim_scope=None,findings=[],proposal_verdict=self.pverdict)
        if self.mutate:self.mutate(value,contract)
        agent_host.validate_public_result(value,node['parameters']['output_schema'])
        result={'kind':'model_result','value':value,'transport':{'request_id':request['request_id'],'execution_mode':'responses_http_loopback_control'},
                'isolation':{'fresh_request':True,'parent_transcript_supplied':False},'physics_validated':False,'execution_authorized':False}
        return control.call('synthetic_response','model',{'request_id':request['request_id']},lambda:result,output_tokens=16)

def prepare(root,tmp_path,role,*,scope='reproduction',**kw):
    actors={'critic':'critic','verifier':'skeptic','synthesizer':'physicist','improver':'improver'}
    return j.prepare_role(root,tmp_path/role,role=role,actor_id=actors[role],model='control',reasoning_effort='high',max_output_tokens=1024,max_wall_seconds=20,
        claim_scope=scope,allow_control=True,**kw)

def complete(root,binding,host=None):
    j.execute_role(binding,host or FakeHost())
    return j.consume(root,binding,allow_control=True)

@pytest.fixture
def cycle(run):opened(run);return run[0]

def test_accounted_control_roles_never_enter_existing_journal(cycle,tmp_path):
    for role in ('critic','verifier'):
        b=prepare(cycle,tmp_path,role)
        with pytest.raises(ValueError, match='self-attested'):
            complete(cycle,b)
    assert review.status(cycle)['state']=='awaiting_review'
    assert review.gate_errors(cycle,'delivery')
    assert len(review._read(cycle)[1])==1

def test_control_transport_refused_in_public_consumer(cycle,tmp_path):
    b=prepare(cycle,tmp_path,'critic');j.execute_role(b,FakeHost())
    with pytest.raises(ValueError,match='self-attested|control transport'):j.consume(cycle,b)
    assert review.status(cycle)['state']=='awaiting_review'

def test_synth_cannot_precede_actual_independent_reviews(cycle,tmp_path):
    with pytest.raises(ValueError,match='both actual'):prepare(cycle,tmp_path,'synthesizer')

def test_existing_strict_model_receipt_cannot_supply_synth(cycle,tmp_path, observed_role_boundary):
    for role in ('critic','verifier'):complete(cycle,prepare(cycle,tmp_path,role))
    b=prepare(cycle,tmp_path,'synthesizer');j.execute_role(b,FakeHost())
    with pytest.raises(ValueError,match='allowed model role'):
        graph.model_receipt(b['graph_root'],b['node_id'],expected_subject_sha256=b['subject_sha256'])

def test_fresh_rdj_coverage_and_stale_copied_case_refused(cycle,tmp_path, observed_role_boundary):
    b=prepare(cycle,tmp_path,'critic');j.execute_role(b,FakeHost(mutate=lambda v,c:v['audit'].update(case_sha256='a'*64)))
    with pytest.raises(ValueError,match='changed claim'):j.consume(cycle,b,allow_control=True)

def test_unresolved_material_action_cannot_accept(cycle,tmp_path, observed_role_boundary):
    b=prepare(cycle,tmp_path,'critic')
    def unresolved(v,c):v['audit']['nodes'][0].update(decision='unresolved',reason='Need discriminating evidence')
    j.execute_role(b,FakeHost(mutate=unresolved))
    with pytest.raises(ValueError,match='unresolved material action'):j.consume(cycle,b,allow_control=True)

def test_unresolved_audit_sendback_preserves_objection(cycle,tmp_path, observed_role_boundary):
    b=prepare(cycle,tmp_path,'critic')
    def unresolved(v,c):v['audit']['nodes'][0].update(decision='unresolved',reason='Need experiment')
    r=complete(cycle,b,FakeHost(verdict='send_back',mutate=unresolved))
    assert r['verdict']=='send_back' and j.next_step(cycle)['role']=='improver'

def test_changed_role_output_blocks_existing_ordinary_delivery(cycle,tmp_path, observed_role_boundary):
    bindings=[]
    for role in ('critic','verifier','synthesizer'):
        b=prepare(cycle,tmp_path,role);complete(cycle,b);bindings.append(b)
    path=next((Path(bindings[0]['graph_root'])/'attempts').glob('*.json'));path.write_text(path.read_text()+' ')
    assert any('review evidence changed' in x for x in review.gate_errors(cycle,'delivery'))
    assert review.gate_errors(cycle,'reuse')

def test_no_role_override_sendback(cycle,tmp_path, observed_role_boundary):
    complete(cycle,prepare(cycle,tmp_path,'critic'),FakeHost(verdict='send_back'))
    b=prepare(cycle,tmp_path,'verifier');j.execute_role(b,FakeHost())
    with pytest.raises(ValueError,match='rejected cycle'):j.consume(cycle,b,allow_control=True)

def repair():
    return {'changed_paths':['inputs/settings.cfg'],'stages':['detector'],'recheck_checks':['agreement'],
        'replacements':[{'path':'inputs/settings.cfg','text':'efficiency=0.85\n'}],
        'tests':[{'finding_id':'F1','method':'discriminating_experiment','reference':None,'observable':'produced value residual','intervention':'efficiency .8 to .85','held_conditions':'same recipe/source/start population',
            'alternatives':[{'hypothesis':'setting causes residual','prediction':'paired residual decreases'}, {'hypothesis':'different source is responsible','prediction':'residual persists'}]}],
        'max_seconds':None}

@pytest.mark.parametrize('attached', [False, True])
def test_ordinary_repair_proposal_skeptic_decider_and_return_to_work(cycle,tmp_path,monkeypatch,attached, observed_role_boundary):
    campaign=campaign_for(cycle,tmp_path,monkeypatch) if attached else None
    budget_options={'campaign':campaign,'experiment':'observed'} if attached else {}
    complete(cycle,prepare(cycle,tmp_path/'result','critic',**budget_options),FakeHost(verdict='send_back'))
    improver=prepare(cycle,tmp_path/'proposal','improver',scope=None,**budget_options)
    result=complete(cycle,improver,FakeHost(proposal=repair()))
    assert review.status(cycle)['redos_used']==0 and result['execution_authorized'] is False
    j.apply_proposal(cycle,improver,allow_control=True)
    skeptic=prepare(cycle,tmp_path/'skeptic','verifier',scope=None,proposal_binding=improver,**budget_options)
    complete(cycle,skeptic)
    decider=prepare(cycle,tmp_path/'decider','synthesizer',scope=None,proposal_binding=skeptic,**budget_options)
    complete(cycle,decider)
    admission=j.admit_repair(cycle,decider,allow_control=True)
    assert admission['redo_number']==1 and review.gate_errors(cycle,'correction','detector')==[]
    assert j.next_step(cycle)['phase']=='return_to_work' and review.gate_errors(cycle,'delivery')
    # Fresh engineering attempt and actual inherited rechecks, never a native job.
    rec=make_attempt(cycle);check_packet(cycle,rec)
    review.open_cycle(cycle,effective_settings=['inputs/settings.cfg'],stage_receipts=[rec['attempt_record']],check_results='inputs/checks.json',correction_id=admission['correction_id'])
    assert review.status(cycle)['state']=='awaiting_review'
    with pytest.raises(ValueError,match='superseded'):j.verify_binding(improver,allow_control=True)
    for role in ('critic','verifier','synthesizer'):
        b=prepare(cycle,tmp_path/'fresh',role,**budget_options);complete(cycle,b,FakeHost(closes=['F1']))
    assert review.status(cycle)['state']=='accepted' and review.gate_errors(cycle,'delivery')==[]
    if attached:
        from ravel.workflow import research_cycle as rc
        _,state=rc._load(campaign)
        assert rc._usage(state)=={'calls':7,'output_tokens':7168,'wall_seconds':140,'native_attempts':0}
        assert len(state['graphs'])==7 and all(g['complete'] for g in state['graphs'])

def test_identical_predictions_cannot_claim_discrimination(cycle,tmp_path, observed_role_boundary):
    complete(cycle,prepare(cycle,tmp_path/'result','critic'),FakeHost(verdict='send_back'))
    p=repair();p['tests'][0]['alternatives'][1]['prediction']=p['tests'][0]['alternatives'][0]['prediction']
    b=prepare(cycle,tmp_path/'proposal','improver',scope=None);j.execute_role(b,FakeHost(proposal=p))
    with pytest.raises(ValueError,match='do not discriminate'):j.consume(cycle,b,allow_control=True)

def test_prepared_repair_skeptic_cannot_close_or_admit(cycle,tmp_path, observed_role_boundary):
    complete(cycle,prepare(cycle,tmp_path/'result','critic'),FakeHost(verdict='send_back'))
    b=prepare(cycle,tmp_path/'proposal','improver',scope=None);complete(cycle,b,FakeHost(proposal=repair()));j.apply_proposal(cycle,b,allow_control=True)
    v=prepare(cycle,tmp_path/'skeptic','verifier',scope=None,proposal_binding=b);complete(cycle,v)
    with pytest.raises(ValueError,match='decider'):j.admit_repair(cycle,v,allow_control=True)
    assert review.status(cycle)['state']=='send_back' and review.gate_errors(cycle,'delivery')

def test_exact_prepared_bytes_revalidated_before_dispatch(cycle,tmp_path, observed_role_boundary):
    complete(cycle,prepare(cycle,tmp_path/'result','critic'),FakeHost(verdict='send_back'))
    b=prepare(cycle,tmp_path/'proposal','improver',scope=None);complete(cycle,b,FakeHost(proposal=repair()));j.apply_proposal(cycle,b,allow_control=True)
    v=prepare(cycle,tmp_path/'skeptic','verifier',scope=None,proposal_binding=b)
    (cycle/'inputs/settings.cfg').write_text('efficiency=0.86\n')
    with pytest.raises(ValueError,match='changed source or settings'):j.execute_role(v,FakeHost())
    assert graph.status(v['graph_root'])['usage']['calls']==0

def test_closed_schema_usable_in_actual_host(cycle,tmp_path):
    agent_host._schema(j.output_schema())
    b=prepare(cycle,tmp_path,'critic')
    host=agent_host.AgentHost.from_config({'type':'responses','endpoint':'http://127.0.0.1:9/v1/responses'})
    spec=read_json(Path(b['graph_root'])/graph.SPEC);state=read_json(Path(b['graph_root'])/graph.STATE)
    node=spec['nodes'][0];state['nodes']['critic']['attempt_id']='control'
    host.prepare_model_context(node,graph._request(spec,state,node,execution.digest(host.identity)))
    assert 'scientific_judgment' in repr(host.identity)

def test_tool_and_public_cli_are_reachable(cycle,tmp_path):
    from ravel import cli
    assert cli.FOCUSED_COMMANDS['judgment'][0]=='workflow.scientific_judgment'
    request=tmp_path/'tool.json';atomic_json(request,{'operation':'status','rundir':str(cycle),'arguments':{}})
    out=j.host_tool({'request_input':'action'},{'action':(request,execution.file_hash(request))})
    assert out['role']=='critic' and out['execution_authorized'] is False

def test_blind_recipe_preserves_declared_scientific_assumptions():
    projected=context._project_science_artifact({'specification':{'schema_version':2,'mode':'test','task':{},'assumptions':['LO convention; paired events']}},'recipe.json')
    assert projected[0]['specification']['assumptions']==['LO convention; paired events']

from test_failed_stage_review import case as failed_case

@pytest.mark.parametrize('attached', [False, True])
def test_actual_failed_ci2_handoff_never_opens_successful_review(failed_case,tmp_path,monkeypatch,attached):
    from ravel.workflow import failed_stage_review as failed
    root,record,request=failed_case
    # A run without a contract is refused by the gate; this pre-release run keeps its old decision.
    (root/'inputs').mkdir(exist_ok=True);atomic_json(root/'inputs/task_contract.json',{'prompt':'pre-release failed stage'})
    doc=failed.intake(request,base_dir=root);intake=j._new(tmp_path/'intake.json',doc)
    campaign=campaign_for(root,tmp_path,monkeypatch) if attached else None
    before={str(p):execution.file_hash(p) for p in root.rglob('*') if p.is_file()}
    bindings=[]
    class DiagnosticHost:
        identity={'fixture':'failed diagnostic fake transport zero calls'}
        def execute(self,node,request,control):
            value={'kind':'failed_scientific_stage_critique','summary':'Synthetic diagnosis; bounded line search unresolved',
                'observations':[{'artifact_id':'e0001','location':'$.failure','observation':'bounded line search'}],
                'mechanisms':[],'unknowns':[{'question':'stationary solution unknown','specific_evidence_or_experiment':'new admitted principal-face study'}]}
            result={'kind':'model_result','value':value,'transport':{'request_id':request['request_id'],'execution_mode':'responses_http_loopback_control'},
                'isolation':{'fresh_request':True,'parent_transcript_supplied':False}}
            return control.call('fixture','model',{'id':request['request_id']},lambda:result,output_tokens=16)
    for role in ('critic','verifier'):
        b=j.prepare_failed_role(root,intake,tmp_path/role,role=role,model='control',reasoning_effort='high',max_output_tokens=512,max_wall_seconds=20)
        if attached:
            from ravel.workflow import research_cycle as rc
            spec,_=graph._load(Path(b['graph_root']))
            rc.execute_graph(campaign,b['graph_root'],spec,DiagnosticHost(),prepared=True)
            j._campaign_graph(root,campaign,'observed',b['graph_root'])
        else:graph.execute(b['graph_root'],DiagnosticHost(),workers=1)
        bindings.append(b)
    if attached:
        _,state=rc._load(campaign)
        assert rc._usage(state)=={'calls':2,'output_tokens':1024,'wall_seconds':40,'native_attempts':0}
    feedback=j.failed_feedback(root,intake,*bindings,allow_control=True)
    assert feedback['stage_status']=='failed' and feedback['scientific_acceptance'] is False and feedback['automatic_redo'] is False
    assert not review.registered(root)
    if attached:
        with pytest.raises(ValueError,match='separate from immutable failed run history'):
            j.failed_feedback(root,intake,*bindings,allow_control=True,campaign=campaign,experiment='observed',out=root/'feedback.json')
    assert {str(p):execution.file_hash(p) for p in root.rglob('*') if p.is_file()}==before
    with pytest.raises(ValueError):j.failed_feedback(root,intake,*bindings)

def test_stale_anchor_refused_before_paid_dispatch(cycle,tmp_path):
    b=prepare(cycle,tmp_path,'critic');contract=read_json(b['request']['path'])
    path=Path(contract['case_anchor_pins'][0]['path']);path.write_text(path.read_text()+' ')
    with pytest.raises(ValueError):j.execute_role(b,FakeHost())
    assert graph.status(b['graph_root'])['usage']['calls']==0

def test_graph_rework_after_vote_blocks_ordinary_current_gate(cycle,tmp_path, observed_role_boundary):
    b=prepare(cycle,tmp_path,'critic');complete(cycle,b)
    state=read_json(Path(b['graph_root'])/graph.STATE);state['nodes']['critic']['generation']+=1
    atomic_json(Path(b['graph_root'])/graph.STATE,state)
    with pytest.raises(ValueError,match='review evidence changed'):j.next_step(cycle)

def test_missing_provider_preserves_pending_review(cycle,tmp_path, observed_role_boundary):
    b=prepare(cycle,tmp_path,'critic')
    class Unavailable:
        identity={'fixture':'no dispatch'}
        def execute(self,*args):raise ValueError('configured provider unavailable')
    graph.execute(b['graph_root'],Unavailable(),workers=1)
    assert review.status(cycle)['state']=='awaiting_review'
    with pytest.raises(ValueError,match='not complete'):j.consume(cycle,b)
    assert execution.load_execution(cycle)['stages']['detector']['status']=='succeeded'

@pytest.mark.parametrize('predictions,status',[
    ({'a':None,'b':None},'predictions_unknown'), ({'a':'same','b':'same'},'same_declared_prediction'),
    ({'a':'one','b':None},'same_declared_prediction'), ({'a':'one','b':'two'},'distinct_declared_predictions')])
def test_exploratory_replication_and_contrast_are_not_observed_resolution(predictions,status):
    from ravel.workflow import research_cycle
    result=research_cycle._discrimination(predictions)
    assert result['status']==status and result['observed_discrimination'] is False

def test_all_actual_critique_content_reaches_improver(cycle,tmp_path, observed_role_boundary):
    b=prepare(cycle,tmp_path/'first','critic');complete(cycle,b,FakeHost(verdict='send_back'))
    p=prepare(cycle,tmp_path/'next','improver',scope=None)
    packet=Path(p['graph_root']).parent/'context';manifest=read_json(packet/'manifest.json')
    item=next(a for a in manifest['artifacts'] if a['id']=='actual_role_judgments')
    doc=read_json(packet/item['path'])
    assert doc[0]['actual_public_role_outputs'][0]['audit']['nodes']
    assert doc[0]['recorded_review']['findings'][0]['id']=='F1'

def test_legacy_and_extended_review_events_remain_blinded(cycle,tmp_path):
    from bound_review import bound_review
    # A recorded vote is a bound role response; its journal event carries the dispatch binding.
    e=bound_review(cycle,role='physics_critic',verdict='accept',summary='Manual synthetic review',claim_scope='reproduction')
    assert 'independence_evidence' in e and context._review_event_identity(e) is not None
    legacy={k:v for k,v in e.items() if k not in {'supporting_artifacts','independence_evidence','sha256'}}
    legacy['sha256']=execution.digest(legacy)
    assert context._review_event_identity(legacy) is not None
    extended=deepcopy(legacy);extended['supporting_artifacts']=[];extended['sha256']=execution.digest({k:v for k,v in extended.items() if k!='sha256'})
    assert context._review_event_identity(extended) is not None

def test_host_tool_refuses_reviewers_self_orchestration(cycle,tmp_path):
    host=agent_host.AgentHost.from_config({'type':'responses','endpoint':'http://127.0.0.1:9/v1/responses'})
    with pytest.raises(agent_host.HostFailure,match='separate caller'):
        host._tool({'action':'scientific-judgment','role':'verifier','parameters':{}},{},None,{})

def test_wrong_declared_actor_and_scope_refused_before_graph(cycle,tmp_path):
    with pytest.raises(ValueError,match='wrong registered'):
        j.prepare_role(cycle,tmp_path/'wrong',role='critic',actor_id='physicist',model='control',reasoning_effort='high',max_output_tokens=1024,max_wall_seconds=10)
    with pytest.raises(ValueError,match='prospectively allowed'):
        prepare(cycle,tmp_path,'critic',scope='whole_physics_truth')

def test_ordinary_advance_drives_result_roles_without_native_work(cycle,tmp_path, observed_role_boundary):
    result=j.advance(cycle,tmp_path/'automatic',host=FakeHost(),model='control',reasoning_effort='high',max_output_tokens=1024,max_wall_seconds=20,
        claim_scope='reproduction',allow_control=True)
    assert result['phase']=='scoped_delivery' and result['execution_authorized'] is False
    assert execution.load_execution(cycle)['stages']['detector']['status']=='succeeded'

def test_ordinary_advance_drives_sendback_to_actual_nonvoting_improvement(cycle,tmp_path, observed_role_boundary):
    class LoopHost(FakeHost):
        def execute(self,node,request,control):
            self.verdict='send_back' if node['role']=='critic' else None
            self.proposal=repair()
            return super().execute(node,request,control)
    result=j.advance(cycle,tmp_path/'adaptive',host=LoopHost(),model='control',reasoning_effort='high',max_output_tokens=1024,max_wall_seconds=20,
        claim_scope='reproduction',improver_actor='improver',allow_control=True)
    assert result['phase']=='prepare_repair' and result['actual_feedback']['proposal']['tests'][0]['finding_id']=='F1'
    assert (cycle/'inputs/settings.cfg').read_text()=='efficiency=0.8\n'
    assert review.status(cycle)['redos_used']==0 and review.gate_errors(cycle,'delivery')

@pytest.mark.parametrize('defect',['none','wrong_value','self_reference'])
def test_direct_grounded_recheck_needs_no_invented_rivals(cycle,tmp_path,defect, observed_role_boundary):
    complete(cycle,prepare(cycle,tmp_path/'result','critic'),FakeHost(verdict='send_back'))
    b=prepare(cycle,tmp_path/'proposal','improver',scope=None)
    packet=Path(b['graph_root']).parent/'context';manifest=read_json(packet/'manifest.json')
    entry=next(a for a in manifest['artifacts'] if a['source_path']=='inputs/reference.json')
    if defect=='self_reference':entry=next(a for a in manifest['artifacts'] if a['source_path']=='outputs/produced.json')
    p=repair();test=p['tests'][0];test.update(method='direct_verification',alternatives=[],reference={
        'artifact_id':entry['id'],'location':'/value' if defect=='self_reference' else '/reference',
        'expected_json':'2' if defect=='wrong_value' else '1','grounding_reason':'Separate declared reference, not target-tuning'})
    j.execute_role(b,FakeHost(proposal=p))
    if defect=='none':
        result=j.consume(cycle,b,allow_control=True)
        assert result['proposal']['tests'][0]['alternatives']==[] and review.status(cycle)['redos_used']==0
    else:
        with pytest.raises(ValueError,match='reference|expected result'):j.consume(cycle,b,allow_control=True)

def test_input_parse_uses_only_authenticated_consumed_buffer(tmp_path,monkeypatch):
    p=tmp_path/'request.json';pin=j._new(p,{'operation':'status'})
    monkeypatch.setattr(j,'read_json',lambda *a: {'operation':'open','fabricated':'unbound read'})
    assert j._read_pin(pin)=={'operation':'status'}

def test_exact_consumed_duplicate_field_buffer_refused(tmp_path):
    p=tmp_path/'request.json';p.write_text('{"operation":"status","operation":"open"}')
    with pytest.raises(ValueError,match='duplicate'):j._read_pin(j._pin(p))


@pytest.mark.parametrize("mutable_in", ["effective_settings", "allowed_changed_paths"])
def test_direct_reference_absolute_alias_of_mutable_input_refused(tmp_path, monkeypatch, mutable_in):
    # Adapted from a retained reference-alias counterexample.
    root=tmp_path/'run';(root/'inputs').mkdir(parents=True)
    source=root/'inputs/settings.json';source.write_text('{"expected":100}\n')
    packet=tmp_path/'context';packet.mkdir()
    entry={'id':'anchor0','source_path':str(source),'source_sha256':execution.file_hash(source)}
    manifest={'artifacts':[entry]};manifest['sha256']=execution.digest(manifest)
    atomic_json(packet/'manifest.json',manifest)
    policy={'allowed_changed_paths':['inputs/settings.json'],'allowed_stages':['science'],'required_checks':[{'id':'agreement'}]}
    view={'findings':[{'id':'F1','required_stages':['science'],'check_ids':['agreement'],'required_paths':['inputs/settings.json']}],
          'cycle':{'receipts':[{'outputs':[str(root/'outputs')]}],
                   'effective_settings':[{'path':'inputs/settings.json','sha256':execution.file_hash(source)}] if mutable_in=='effective_settings' else []}}
    proposal={'changed_paths':['inputs/settings.json'],'stages':['science'],'recheck_checks':['agreement'],
              'replacements':[{'path':'inputs/settings.json','text':'{"expected":101}\n'}],
              'tests':[{'finding_id':'F1','observable':'value','intervention':'restore value','held_conditions':'same original sample',
                        'method':'direct_verification','alternatives':[],
                        'reference':{'artifact_id':'anchor0','location':'/expected','expected_json':'100','grounding_reason':'Declared original input'}}],
              'max_seconds':None}
    monkeypatch.setattr(j.review_context,'read_artifact',lambda *a,**k:source.read_bytes())
    with pytest.raises(ValueError,match='independent'):
        j._proposal(root,{'policy':policy},view,proposal,{'path':str(packet),'manifest_sha256':manifest['sha256']})


@pytest.mark.parametrize("inside", ["root", "new_child"])
def test_refused_failed_role_output_preserves_all_history_members(failed_case, tmp_path, inside):
    from ravel.workflow import failed_stage_review as failed
    root,record,request=failed_case
    intake=j._new(tmp_path/'intake.json',failed.intake(request,base_dir=root))
    before={str(p.relative_to(root)):execution.file_hash(p) if p.is_file() else None for p in root.rglob('*')}
    out=root if inside=='root' else root/'new-diagnostic'/'role'
    with pytest.raises(ValueError,match='separate from immutable failed run history'):
        j.prepare_failed_role(root,intake,out,role='critic',model='control',reasoning_effort='high',max_output_tokens=512,max_wall_seconds=20)
    assert {str(p.relative_to(root)):execution.file_hash(p) if p.is_file() else None for p in root.rglob('*')}==before



def campaign_for(root, tmp_path, monkeypatch, *, calls=8, goal_binding=None):
    # Ordinary immutable cycle history; only its context compiler is a pure stub.
    from ravel.workflow import research_cycle as rc
    monkeypatch.setattr(rc.scientific_context,'compile_context',lambda request,base:{'request_sha256':execution.digest(request),'steps':[]})
    request=tmp_path/'context-request.json';atomic_json(request,{'fixture':'software-only bounded context'})
    campaign=tmp_path/'campaign'
    state=rc.create(campaign,{'schema_version':1,'id':'review-budget','question':'Bound actual judgment calls','scope':'software control',
        'context_request':rc._pin(request),'premises':[],
        'budget':{'calls':calls,'output_tokens':8192,'wall_seconds':300,'native_attempts':0},
        'max_experiments':1,'exploration_every':1,'required_experiments':[],
        **({'goal_binding':goal_binding} if goal_binding is not None else {})},base_dir=tmp_path, evaluation_harness=True)
    state['experiments'].append({'id':'observed','rundir':str(root),'observation':{'kind':'synthetic terminal record'}})
    rc._commit(campaign,state,'fixture_observed_run')
    return campaign


def test_campaign_three_role_advance_charges_each_existing_ledger_reservation(cycle,tmp_path,monkeypatch, observed_role_boundary):
    from ravel.workflow import research_cycle as rc
    campaign=campaign_for(cycle,tmp_path,monkeypatch)
    result=j.advance(cycle,tmp_path/'roles',host=FakeHost(),model='control',reasoning_effort='high',max_output_tokens=1024,
        max_wall_seconds=20,claim_scope='reproduction',allow_control=True,campaign=campaign,experiment='observed')
    _,state=rc._load(campaign)
    assert result['phase']=='scoped_delivery'
    assert rc._usage(state)=={'calls':3,'output_tokens':3072,'wall_seconds':60,'native_attempts':0}
    assert len(state['graphs'])==3 and all(g['complete'] and g['usage']['calls']==1 for g in state['graphs'])


def test_campaign_run_mismatch_refused_before_role_preparation(cycle,tmp_path,monkeypatch):
    campaign=campaign_for(tmp_path/'other-run',tmp_path,monkeypatch)
    out=tmp_path/'roles'
    with pytest.raises(ValueError,match='exact observed experiment'):
        prepare(cycle,out,'critic',campaign=campaign,experiment='observed')
    assert not out.exists()


def test_campaign_exhausted_reservation_refuses_next_role_before_call(cycle,tmp_path,monkeypatch, observed_role_boundary):
    from ravel.workflow import research_cycle as rc
    campaign=campaign_for(cycle,tmp_path,monkeypatch,calls=1)
    critic=prepare(cycle,tmp_path/'roles','critic',campaign=campaign,experiment='observed');complete(cycle,critic)
    verifier=prepare(cycle,tmp_path/'roles','verifier',campaign=campaign,experiment='observed')
    with pytest.raises(ValueError,match='cumulative research resource ceiling'):j.execute_role(verifier,FakeHost())
    assert graph.status(verifier['graph_root'])['usage']['calls']==0
    _,state=rc._load(campaign);assert rc._usage(state)['calls']==1


def test_campaign_dispatch_exception_preserves_ceiling_and_available_actual_usage(cycle,tmp_path,monkeypatch):
    from ravel.workflow import research_cycle as rc
    campaign=campaign_for(cycle,tmp_path,monkeypatch)
    binding=prepare(cycle,tmp_path/'roles','critic',campaign=campaign,experiment='observed')
    def fail(*a,**k):raise RuntimeError('synthetic dispatch boundary')
    monkeypatch.setattr(graph,'execute',fail)
    with pytest.raises(RuntimeError,match='synthetic dispatch'):j.execute_role(binding,FakeHost())
    _,state=rc._load(campaign)
    assert rc._usage(state)=={'calls':1,'output_tokens':1024,'wall_seconds':20,'native_attempts':0}
    assert state['graphs'][0]['dispatch_error']=='RuntimeError' and state['graphs'][0]['usage']['calls']==0
    assert state['graphs'][0]['complete'] is False


def test_campaign_cannot_retroactively_admit_already_spent_prepared_graph(cycle,tmp_path,monkeypatch):
    from ravel.workflow import research_cycle as rc
    binding=prepare(cycle,tmp_path/'roles','critic');j.execute_role(binding,FakeHost())
    campaign=campaign_for(cycle,tmp_path,monkeypatch)
    spec,_=graph._load(Path(binding['graph_root']))
    with pytest.raises(ValueError,match='pristine prepared Graph'):
        rc.execute_graph(campaign,binding['graph_root'],spec,FakeHost(),prepared=True)
    _,state=rc._load(campaign);assert rc._usage(state)['calls']==0


def test_campaign_resume_retains_single_ceiling_and_changed_spec_refuses(cycle,tmp_path,monkeypatch):
    from ravel.workflow import research_cycle as rc
    campaign=campaign_for(cycle,tmp_path,monkeypatch)
    binding=prepare(cycle,tmp_path/'roles','critic',campaign=campaign,experiment='observed')
    j.execute_role(binding,FakeHost());j.execute_role(binding,FakeHost())
    _,state=rc._load(campaign);assert len(state['resource_ledger'])==1 and rc._usage(state)['calls']==1
    spec,_=graph._load(Path(binding['graph_root']));spec['budget']['max_calls']=2
    with pytest.raises(ValueError,match='original resource reservation'):
        rc.execute_graph(campaign,binding['graph_root'],spec,FakeHost(),prepared=True)
    assert graph.status(binding['graph_root'])['usage']['calls']==1


def test_campaign_consumer_refuses_review_dispatched_outside_its_ledger(cycle,tmp_path,monkeypatch, observed_role_boundary):
    campaign=campaign_for(cycle,tmp_path,monkeypatch)
    binding=prepare(cycle,tmp_path/'roles','critic',campaign=campaign,experiment='observed')
    graph.execute(binding['graph_root'],FakeHost(),workers=1)
    with pytest.raises(ValueError,match='retained exact resource reservation'):j.consume(cycle,binding,allow_control=True)
    assert review.status(cycle)['state']=='awaiting_review'



def test_campaign_failed_accounted_role_retains_actual_call_and_full_ceiling(cycle,tmp_path,monkeypatch, observed_role_boundary):
    from ravel.workflow import research_cycle as rc
    campaign=campaign_for(cycle,tmp_path,monkeypatch)
    binding=prepare(cycle,tmp_path/'roles','critic',campaign=campaign,experiment='observed')
    class FailedHost:
        identity={'fixture':'accounted transport failure; zero model/provider calls'}
        def execute(self,node,request,control):
            def fail():raise ValueError('synthetic provider failure')
            return control.call('fixture','model',{'request_id':request['request_id']},fail,output_tokens=16)
    result=j.execute_role(binding,FailedHost())
    _,state=rc._load(campaign)
    assert result['complete'] is False and state['graphs'][0]['usage']['calls']==1
    assert rc._usage(state)=={'calls':1,'output_tokens':1024,'wall_seconds':20,'native_attempts':0}
    with pytest.raises(ValueError):j.consume(cycle,binding,allow_control=True)
    assert review.status(cycle)['state']=='awaiting_review'



def test_host_prepare_tool_binds_campaign_without_nested_dispatch(cycle,tmp_path,monkeypatch):
    campaign=campaign_for(cycle,tmp_path,monkeypatch)
    request=tmp_path/'tool-request.json'
    pin=j._new(request,{'operation':'prepare-role','rundir':str(cycle),'arguments':{
        'out':str(tmp_path/'host-role'),'role':'critic','actor_id':'critic','model':'control','reasoning_effort':'high',
        'max_output_tokens':1024,'max_wall_seconds':20,'claim_scope':'reproduction','case_pin':None,'proposal_binding':None,
        'campaign':str(campaign),'experiment':'observed'}})
    binding=j.host_tool({'request_input':'action'},{'action':(request,pin['sha256'])})
    contract=j._read_pin(binding['request'])
    assert contract['campaign']=={'root':str(campaign),'experiment':'observed'}
    assert graph.status(binding['graph_root'])['usage']['calls']==0



def campaign_parent(tmp_path):
    from ravel.workflow import task_completion as tc, route_prompt, research_cycle as rc, rdj_custody
    prompt='Prepare a bounded interpretation study while retaining the whole original question.'
    contract=route_prompt.route(prompt);req=tc.initial_requirements(prompt)
    req['assignments']=[{'id':'judgment-child','purpose':'Review the bounded observed study without completing the whole parent.',
        'coverage':[{'obligation_id':r['id'],'criteria':deepcopy(r['criteria'])} for r in req['obligations']]}]
    contract['task_requirements']=req
    path=tmp_path/'parent'/'inputs'/'task_contract.json';path.parent.mkdir(parents=True);atomic_json(path,contract)
    binding={'contract':rc._pin(path),'assignment_id':'judgment-child'}
    rdj_custody.record_input_snapshot(path.parent.parent,'run_init')
    tc.binding_projection(binding,base_dir=tmp_path)  # actual ordinary contract validation, no parent acceptance
    return binding


def test_campaign_role_prepared_graph_inherits_real_parent_assignment(cycle,tmp_path,monkeypatch, observed_role_boundary):
    goal=campaign_parent(tmp_path);campaign=campaign_for(cycle,tmp_path,monkeypatch,goal_binding=goal)
    binding=prepare(cycle,tmp_path/'role','critic',campaign=campaign,experiment='observed')
    spec,_=graph._load(Path(binding['graph_root']))
    assert spec['goal_binding']==goal
    result=complete(cycle,binding)
    assert result['verdict']=='accept' and review.status(cycle)['state']=='awaiting_review'
    assert not j._read_pin(binding['request'])['actor_identity_authenticated']


def test_failed_diagnostic_prepared_graph_inherits_parent_without_mutating_failure(failed_case,tmp_path,monkeypatch):
    from ravel.workflow import failed_stage_review as failed
    root,record,request=failed_case
    goal=campaign_parent(tmp_path);campaign=campaign_for(root,tmp_path,monkeypatch,goal_binding=goal)
    intake=j._new(tmp_path/'intake.json',failed.intake(request,base_dir=root))
    before={str(p.relative_to(root)):execution.file_hash(p) if p.is_file() else None for p in root.rglob('*')}
    binding=j.prepare_failed_role(root,intake,tmp_path/'role',role='critic',model='control',reasoning_effort='high',
        max_output_tokens=512,max_wall_seconds=20,campaign=campaign,experiment='observed')
    spec,_=graph._load(Path(binding['graph_root']))
    assert spec['goal_binding']==goal and set(binding)=={'graph_root','node_id','context_manifest_sha256','actor_id'}
    assert not review.registered(root)
    assert {str(p.relative_to(root)):execution.file_hash(p) if p.is_file() else None for p in root.rglob('*')}==before


def test_parent_contract_drift_refused_before_any_campaign_model_call(cycle,tmp_path,monkeypatch):
    from ravel.workflow import research_cycle as rc
    goal=campaign_parent(tmp_path);campaign=campaign_for(cycle,tmp_path,monkeypatch,goal_binding=goal)
    binding=prepare(cycle,tmp_path/'role','critic',campaign=campaign,experiment='observed')
    path=Path(goal['contract']['path']);path.write_text(path.read_text()+' ')
    with pytest.raises(ValueError):j.execute_role(binding,FakeHost())
    assert read_json(Path(binding['graph_root'])/graph.STATE)['usage']['calls']==0



def test_direct_reference_manifest_classification_uses_authenticated_original_buffer(tmp_path,monkeypatch):
    root=tmp_path/'run';(root/'inputs').mkdir(parents=True)
    source=root/'inputs/settings.json';source.write_text('{"expected":100}\n')
    packet=tmp_path/'context';packet.mkdir()
    manifest={'artifacts':[{'id':'anchor0','source_path':str(source),'source_sha256':execution.file_hash(source)}]}
    manifest['sha256']=execution.digest(manifest);atomic_json(packet/'manifest.json',manifest)
    forged=deepcopy(manifest);forged['artifacts'][0]['source_path']=str(tmp_path/'independent-reference.json')
    # Old pathname parser could return substituted classification while later raw reader sees original.
    monkeypatch.setattr(j,'read_json',lambda *a:forged)
    monkeypatch.setattr(j.review_context,'read_artifact',lambda *a,**k:source.read_bytes())
    policy={'allowed_changed_paths':['inputs/settings.json'],'allowed_stages':['science'],'required_checks':[{'id':'agreement'}]}
    view={'findings':[{'id':'F1','required_stages':['science'],'check_ids':['agreement'],'required_paths':['inputs/settings.json']}],
          'cycle':{'receipts':[{'outputs':['outputs']}],'effective_settings':[{'path':'inputs/settings.json'}]}}
    proposal={'changed_paths':['inputs/settings.json'],'stages':['science'],'recheck_checks':['agreement'],
        'replacements':[{'path':'inputs/settings.json','text':'{"expected":101}\n'}],
        'tests':[{'finding_id':'F1','observable':'value','intervention':'restore','held_conditions':'same original input',
        'method':'direct_verification','alternatives':[],
        'reference':{'artifact_id':'anchor0','location':'/expected','expected_json':'100','grounding_reason':'Independent declared reference'}}],'max_seconds':None}
    with pytest.raises(ValueError,match='independent'):
        j._proposal(root,{'policy':policy},view,proposal,{'path':str(packet),'manifest_sha256':manifest['sha256']})



def test_failed_feedback_cli_exposes_existing_campaign_join_arguments(tmp_path,monkeypatch,capsys):
    intake=tmp_path/'intake.json';critic=tmp_path/'critic.json';verifier=tmp_path/'verifier.json'
    for path in (intake,critic,verifier):atomic_json(path,{'software':'argument transport only'})
    captured={}
    def feedback(root,*args,**kw):captured.update(kw);return {'execution_authorized':False}
    monkeypatch.setattr(j,'failed_feedback',feedback)
    out=tmp_path/'new-feedback.json';campaign=tmp_path/'campaign'
    assert j.main(['failed-feedback','--rundir',str(tmp_path),'--intake',str(intake),'--critic-binding',str(critic),
        '--verifier-binding',str(verifier),'--campaign',str(campaign),'--experiment','observed','--out',str(out)])==0
    assert captured=={'campaign':campaign,'experiment':'observed','out':out}
    assert not out.exists()


def test_partial_failed_feedback_campaign_arguments_refuse_before_intake(tmp_path):
    with pytest.raises(ValueError,match='supplied together'):
        j.failed_feedback(tmp_path,{'invalid':'not read'}, {}, {}, experiment='observed')


@pytest.fixture
def observed_role_boundary(monkeypatch):
    """The inert transport reports a fresh observed request without tools, as an HTTP adapter records it.

    Unchanged, the loopback inert transport is a control transport and its votes are refused.
    Tests requesting this fixture cover downstream journal/schema semantics through the ordinary
    evidence path: the graph accounts the inert response, its runner records the dispatch and the
    default resolver reads that record. Nonvoting context and evidence requests keep the control
    report. The unmodified FakeHost path is covered by the control-refusal tests.
    """
    original = graph.Control.call
    def call(self, label, kind, request, function, output_tokens=0, downstream=None):
        def observed():
            result = function()
            transport = result.get('transport') if type(result) is dict else None
            value = result.get('value') if type(result) is dict else None
            if (kind != 'model' or type(transport) is not dict
                    or transport.get('execution_mode') != 'responses_http_loopback_control'
                    or type(value) is dict and value.get('kind') in {'scientific_context_request', 'scientific_evidence_request'}):
                return result
            return {**result, 'transport': {**transport, 'execution_mode': 'responses_http'},
                    'isolation': {**result.get('isolation', {}), 'model_tools_supplied': False}}
        return original(self, label, kind, request, observed, output_tokens=output_tokens, downstream=downstream)
    monkeypatch.setattr(graph.Control, 'call', call)
