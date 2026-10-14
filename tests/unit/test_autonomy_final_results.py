"""Unexecuted C36 source controls, for root's later software admission.

All returned numbers and model responses are inert fixtures. Existing ordinary
approval/journal/Graph code is exercised; no scientific/native provider is used.
"""

from method_decision_fixture import admit_method
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import pytest
from ravel.workflow import scientific_autonomy as autonomy,final_results_review as final
from ravel.workflow import execution,physics_review as review,scientific_judgment as judgment
from ravel.workflow import scientific_report as report,science,workflow_state
from ravel.workflow.state_io import atomic_json,read_json
from test_physics_review import run,opened,accept,make_attempt,check_packet,finding
from test_scientific_judgment import observed_role_boundary
from test_scientific_judgment import FakeHost,prepare,complete,repair
from test_science_review_envelope import planned
from test_scientific_report import fixture as report_fixture


def pin(path):
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def linked_parent(base,prompt):
    from ravel.workflow import route_prompt,task_completion
    from test_task_completion import PROMPT
    # An actual synthetic whole-question contract and complete one-child
    # assignment, not an arbitrary origin label or input authority surrogate.
    parent=route_prompt.route(PROMPT)
    parent['prompt']=prompt;req=task_completion.initial_requirements(prompt)
    req['assignments']=[{'id':'whole-child','purpose':'Complete original synthetic question',
        'coverage':[{'obligation_id':o['id'],'criteria':deepcopy(o['criteria'])} for o in req['obligations']]}]
    parent['task_requirements']=req
    path=base/'original-parent.json';atomic_json(path,parent)
    return {**pin(path),'size':path.stat().st_size}


def delegated(base,document,*,origin='initial_prompt',policy=None,bounds=None):
    from ravel.workflow.task_completion import initial_requirements
    from test_task_completion import PROMPT
    document=deepcopy(document)
    command='Run autonomously within this exact bounded task; keep scientific review.'
    if 'schema_version' in document and 'mode' in document:
        if 'goal_binding' not in document:
            parent=linked_parent(base,PROMPT+'\n'+command)
            document['goal_binding']={'contract':parent,'assignment_id':'whole-child'}
        message=read_json(document['goal_binding']['contract']['path'])['prompt']
    else:
        message=document.get('prompt',str(document.get('objective','Keep the complete synthetic original research task.'))+'\n'+command)
        document['prompt']=message;document['task_requirements']=initial_requirements(message)
    text=base/'user-message.txt';text.write_text(message)
    return autonomy.prepare_declaration(document,base/'delegation.json',
        user_text=pin(text),quote=command,origin=origin,delegate_actor='machine-coordinator',
        actions=['approve_plan','checkin2_go','accept_recommendation'],bounds=bounds or {
            'compute_plans':['smoke'],'allowed_changed_paths':['inputs/settings.cfg'],
            'allowed_stages':['detector'],'max_redos':1},task_class='research_analysis',
        blinding_policy=policy,base_dir=base)


def test_original_user_text_can_select_delegation_before_approval(tmp_path):
    origin='initial_prompt'
    document={'task_mode':'research','compute_plan':'smoke','objective':'Keep the entire original question'}
    result=delegated(tmp_path,document,origin=origin)
    assert 'autonomy' not in document and result['approval_required'] and not result['execution_authorized']
    d=autonomy.declaration(result['document'],tmp_path)
    assert d['value']['origin']==origin and d['authority_label']=='machine_under_user_delegation'
    assert d['human_identity_authenticated'] is False
    assert set(autonomy.input_paths(result['document'],tmp_path))=={str(tmp_path/'delegation.json'),str(tmp_path/'user-message.txt')}


@pytest.mark.parametrize('field,value',[('objective','narrow the question'),('compute_plan','full')])
def test_delegation_never_changes_original_question_or_compute_plan(tmp_path,field,value):
    document=delegated(tmp_path,{'task_mode':'research','compute_plan':'smoke','objective':'whole question'})['document']
    document[field]=value
    with pytest.raises(ValueError,match='objective or resource'):autonomy.declaration(document,tmp_path)


@pytest.mark.parametrize('change',['quote','unknown','mode','bool_redos'])
def test_malformed_or_overclaimed_delegation_refuses(tmp_path,change):
    document=delegated(tmp_path,{'task_mode':'research'})['document'];path=tmp_path/'delegation.json'
    value=read_json(path)
    if change=='quote':value['quote']='permission invented by the agent'
    if change=='unknown':value['actions'].append('unblind_sr_data')
    if change=='mode':value['task_class']='deterministic_calculation'
    if change=='bool_redos':value['bounds']['max_redos']=True
    atomic_json(path,value);document['autonomy']=pin(path)
    with pytest.raises(ValueError):autonomy.declaration(document,tmp_path)


@pytest.mark.parametrize('change',['source','alias','relative'])
def test_exact_user_source_and_declaration_identity(tmp_path,change):
    document=delegated(tmp_path,{'task_mode':'research'})['document']
    if change=='source':(tmp_path/'user-message.txt').write_text('Run autonomously under DIFFERENT conditions.\n')
    if change=='alias':
        alias=tmp_path/'alias.json';alias.symlink_to(tmp_path/'delegation.json');document['autonomy']['path']=str(alias)
    if change=='relative':document['autonomy']['path']='delegation.json'
    with pytest.raises(ValueError):autonomy.declaration(document,tmp_path)


def test_invalid_intake_quote_leaves_no_authority_file(tmp_path):
    source=tmp_path/'user.txt';source.write_text('Please calculate this quantity.\n');out=tmp_path/'delegation.json'
    with pytest.raises(ValueError):
        autonomy.prepare_declaration({'task_mode':'calculation'},out,user_text=pin(source),quote=source.read_text(),
            origin='initial_prompt',delegate_actor='agent',actions=['accept_recommendation'],
            bounds={'compute_plans':[],'allowed_changed_paths':[],'allowed_stages':[],'max_redos':0},
            task_class='deterministic_calculation',base_dir=tmp_path)
    assert not out.exists()


def attach(run):
    rd,_=run
    result=delegated(rd,{'task_mode':'research','compute_plan':'smoke'})
    atomic_json(rd/'inputs/task_contract.json',result['document'])
    return rd


def test_revocation_and_exhausted_authority_escalate_before_any_new_role(run,tmp_path):
    rd=attach(run);opened(run)
    assert autonomy.authorize(rd,'accept_recommendation')['authority_label']=='machine_under_user_delegation'
    text=rd/'revoke.txt';text.write_text('Stop autonomous work; I will steer the next stage.\n')
    record=autonomy.revoke(rd,user_text=pin(text),quote=text.read_text().strip())
    assert record['execution_authorized'] is False
    with pytest.raises(ValueError,match='revoked'):autonomy.authorize(rd,'accept_recommendation')
    with pytest.raises(ValueError,match='revoked'):
        judgment.advance(rd,tmp_path/'must-not-create',host=FakeHost(),model='control',reasoning_effort='high',
            max_output_tokens=1024,max_wall_seconds=20,claim_scope='reproduction',allow_control=True)
    assert not (tmp_path/'must-not-create').exists()


def test_authority_never_waives_approval_or_scientific_hold(run,monkeypatch):
    rd=attach(run);opened(run)
    monkeypatch.setattr(workflow_state,'verify_approval',lambda *a,**kw:['missing real access/approval'])
    with pytest.raises(ValueError,match='escalation'):autonomy.authorize(rd,'accept_recommendation')


def delegated_science(planned):
    rd,source=planned
    document=read_json(source)
    policy=document['review_policy']['policy']
    result=delegated(source.parent,document,bounds={'compute_plans':['none'],
        'allowed_changed_paths':policy['allowed_changed_paths'],'allowed_stages':['science'],'max_redos':1})
    out=source.with_name('delegated-spec.json');atomic_json(out,result['document'])
    fresh=rd.with_name('autonomous-run');science.plan(fresh,out); admit_method(fresh)
    return fresh,result['document']


def test_initial_prompt_records_distinct_machine_ci1_without_another_human_reply(planned):
    from ravel import cli
    rd,document=delegated_science(planned)
    args=cli.parser().parse_args(['approve','--rundir',str(rd),'--delegated'])
    assert cli._approve(args)==0
    receipt=read_json(rd/science.APPROVAL)
    assert receipt['schema_version']==3 and receipt['generated_by']=='ravel.workflow.science.approve_delegated'
    assert receipt['authority']=='delegated_machine' and receipt['expert_review'] is False
    assert receipt['delegation']==document['autonomy']
    assert science.verify_approval_envelope(rd)==[]
    assert not (rd/'execution_attempt.json').exists() and not (rd/'execution_state.json').exists()


@pytest.mark.parametrize('change',['question','budget','source','revoke'])
def test_changed_plan_source_limits_and_revocation_block_initial_machine_action(planned,change):
    rd,document=delegated_science(planned)
    if change=='question':
        value=read_json(rd/science.SPEC);value['assumptions'].append('silently replace the question');atomic_json(rd/science.SPEC,value)
    if change=='budget':
        value=read_json(rd/science.SPEC);value['max_seconds']+=1;atomic_json(rd/science.SPEC,value)
    if change=='source':Path(document['autonomy']['path']).write_text('{}\n')
    if change=='revoke':
        path=rd/'revoke.txt';path.write_text('Stop autonomous operation.\n');autonomy.revoke(rd,user_text=pin(path),quote=path.read_text().strip())
    with pytest.raises(ValueError):science.approve_delegated(rd)
    assert not (rd/science.APPROVAL).exists()


def test_revocation_blocks_next_native_entry_without_erasing_retained_machine_approval(planned):
    rd,_=delegated_science(planned);science.approve_delegated(rd)
    path=rd/'stop.txt';path.write_text('Stop delegated execution before the next stage.\n')
    autonomy.revoke(rd,user_text=pin(path),quote=path.read_text().strip())
    assert science.verify_approval_envelope(rd)==[]
    with pytest.raises(ValueError,match='revoked'):science.run(rd)
    assert not (rd/'execution_attempt.json').exists()


def test_correction_is_limited_by_user_paths_and_stages(run):
    rd=attach(run);opened(run)
    p=repair();assert autonomy.correction_authority(rd,p)['value']['bounds']['max_redos']==1
    for field,value in [('changed_paths',['inputs/unapproved.cfg']),('stages',['statistics'])]:
        bad={**p,field:value}
        with pytest.raises(ValueError,match='delegated'):autonomy.correction_authority(rd,bad)


def test_actual_improver_skeptic_decider_accept_only_prepared_bounded_repair(run,tmp_path, observed_role_boundary):
    rd=attach(run);opened(run)
    # This run predates its protocol binding; resuming binds it with a recorded receipt.
    from ravel.workflow import research_launch
    assert research_launch.migrate(rd)['applied_by']=='machine'
    complete(rd,prepare(rd,tmp_path/'initial','critic'),FakeHost(verdict='send_back'))
    result=judgment.advance(rd,tmp_path/'improve',host=FakeHost(proposal=repair()),improver_actor='improver',
        model='control',reasoning_effort='high',max_output_tokens=1024,max_wall_seconds=20,allow_control=True)
    assert result['phase']=='review_prepared_repair' and review.status(rd)['redos_used']==0
    assert (rd/'inputs/settings.cfg').read_text()=='efficiency=0.85\n'
    admitted=judgment.advance(rd,tmp_path/'design',host=FakeHost(),proposal_binding=result['improver_binding'],
        model='control',reasoning_effort='high',max_output_tokens=1024,max_wall_seconds=20,allow_control=True)
    assert admitted['phase']=='ordinary_correction_admitted' and admitted['human_review_claimed'] is False
    assert review.status(rd)['state']=='correction_admitted' and review.gate_errors(rd,'delivery')
    assert review.gate_errors(rd,'correction','detector')==[]
    # Approval and a distinct native launch lease are not fabricated here.
    assert admitted['execution_authorized'] is False


def package(rd,predecessor):
    out=rd/'final-draft';out.mkdir()
    atomic_json(out/'report.json',{'kind':'scientific_quantitative_report_draft','report_text':'Exact full result; synthetic control.'})
    atomic_json(out/'recipe.json',{'recipe':'synthetic complete final recipe'})
    rows=[{**pin(out/name),'role':role} for name,role in [('report.json','report'),('recipe.json','report_recipe')]]
    observation=rd/'inputs/final-blinding-applicability.json'
    atomic_json(observation,{'schema_version':1,'kind':'blinding_applicability_check','status':'pass',
        'sr_data_present':False,'checked_paths':[r['path'] for r in rows]})
    checks=read_json(rd/'inputs/checks.json')
    checks['checks'][1]['evidence'].append({'path':str(observation),'location':'$.sr_data_present'})
    atomic_json(rd/'inputs/checks-final.json',checks)
    value={'schema_version':1,'kind':'checkin3_final_results','source_cycle_id':predecessor['cycle_id'],
        'source_cycle_sha256':predecessor['sha256'],'artifact_roots':[str(out)],'artifacts':rows,
        'claims':[{'id':'claim1','text':'Every synthetic result is shown; no physical acceptance claim.',
            'evidence':[r['path'] for r in rows]}],
        'changes_since_checkin2':[{'path':r['path'],'prior_sha256':None,'current_sha256':r['sha256'],
            'reason':'New immutable final draft from accepted original outputs','dependent_stages':[]} for r in rows],
        'blinding':{'mode':'not_required','policy':None,'check':pin(observation)}}
    target=rd/'inputs/final-package.json';atomic_json(target,value)
    return pin(target),value


@pytest.fixture
def final_ready(run):
    rd,_=run;opened(run);accept(rd);_,events=review._read(rd)
    manifest,value=package(rd,events[0]);return rd,manifest,value


def test_final_checkpoint_uses_actual_fresh_three_role_graphs(final_ready,tmp_path, observed_role_boundary):
    rd,manifest,value=final_ready
    cycle=judgment.open_final_cycle(rd,manifest=manifest,check_results='inputs/checks-final.json')
    assert cycle['final_results']['source_cycle_id']==value['source_cycle_id']
    assert review.status(rd)['state']=='awaiting_review' and review.gate_errors(rd,'delivery')
    result=judgment.advance(rd,tmp_path/'final-roles',host=FakeHost(),model='control',reasoning_effort='high',
        max_output_tokens=1024,max_wall_seconds=20,claim_scope='reproduction',allow_control=True)
    assert result['phase']=='final_results_reviewed' and review.status(rd)['state']=='accepted'
    assert final.gate(rd,manifest,report='Exact full result; synthetic control.',recipe={'recipe':'synthetic complete final recipe'})['unblinding_authorized'] is False
    assert review.validate_snapshot(review.snapshot(rd,action='delivery'))==[]


@pytest.mark.parametrize('change',['omit_artifact','omit_change','extra_claim','overlap','symlink','wrong_predecessor'])
def test_complete_final_population_and_changes_are_not_inferred(final_ready,change):
    rd,manifest,value=final_ready
    if change=='omit_artifact':value['artifacts'].pop()
    if change=='omit_change':value['changes_since_checkin2'].pop()
    if change=='extra_claim':value['claims'][0]['evidence'].append(str(rd/'inputs/settings.cfg'))
    if change=='overlap':value['artifact_roots'].append(value['artifact_roots'][0])
    if change=='symlink':(rd/'final-draft/alias.svg').symlink_to(rd/'final-draft/figure.svg')
    if change=='wrong_predecessor':value['source_cycle_sha256']='a'*64
    atomic_json(Path(manifest['path']),value);manifest=pin(Path(manifest['path']))
    with pytest.raises(ValueError):judgment.open_final_cycle(rd,manifest=manifest,check_results='inputs/checks-final.json')
    assert review.status(rd)['state']=='accepted' and len(review._read(rd)[1])==4


@pytest.mark.parametrize('change',['report','recipe','new_member'])
def test_reviewed_final_bytes_cannot_be_reworded_or_expanded(final_ready,change):
    rd,manifest,_=final_ready;judgment.open_final_cycle(rd,manifest=manifest,check_results='inputs/checks-final.json');accept(rd)
    if change=='report':(rd/'final-draft/report.json').write_text('{"report_text":"Changed final claim"}')
    if change=='recipe':(rd/'final-draft/recipe.json').write_text('{"recipe":"Different scope"}')
    if change=='new_member':(rd/'final-draft/new-output.json').write_text('{}')
    with pytest.raises(ValueError):final.gate(rd,manifest)


def test_final_rejection_routes_material_error_to_actual_stage_and_new_revision(final_ready,tmp_path, observed_role_boundary):
    rd,manifest,_=final_ready;judgment.open_final_cycle(rd,manifest=manifest,check_results='inputs/checks-final.json')
    complete(rd,prepare(rd,tmp_path/'final-reject','critic'),FakeHost(verdict='send_back'))
    assert judgment.next_step(rd)['phase']=='repair_proposal'
    b=prepare(rd,tmp_path/'improvement','improver',scope=None)
    complete(rd,b,FakeHost(proposal=repair()));judgment.apply_proposal(rd,b,allow_control=True)
    s=prepare(rd,tmp_path/'skeptic','verifier',scope=None,proposal_binding=b);complete(rd,s)
    d=prepare(rd,tmp_path/'decider','synthesizer',scope=None,proposal_binding=s);complete(rd,d)
    correction=judgment.admit_repair(rd,d,allow_control=True)
    assert correction['stages']==['detector'] and review.gate_errors(rd,'delivery')
    rec=make_attempt(rd);check_packet(rd,rec)
    review.open_cycle(rd,effective_settings=['inputs/settings.cfg'],stage_receipts=[rec['attempt_record']],
        check_results='inputs/checks.json',correction_id=correction['correction_id'])
    assert 'final_results' not in review._view(*review._read(rd))['cycle']
    with pytest.raises(ValueError):final.gate(rd,manifest)


def test_calculation_does_not_acquire_a_universal_ci3_burden(final_ready):
    rd,_,_=final_ready
    # A caller label cannot turn a registered scientific workflow into the
    # genuine schema1 literal calculator short path.
    assert final.required(rd,contract={'task_mode':'calculation'}) is True
    assert final.required(rd,contract={'task_mode':'research'}) is True
    assert final.required(rd,contract={'task_mode':'reinterpret'}) is True


def test_blinding_requires_original_policy_and_current_scientific_check(final_ready):
    rd,manifest,value=final_ready
    value['blinding']={'mode':'blinded','policy':None,'check':None}
    atomic_json(Path(manifest['path']),value)
    with pytest.raises(ValueError,match='current evidence'):judgment.open_final_cycle(rd,manifest=pin(Path(manifest['path'])),check_results='inputs/checks-final.json')


def test_unexposed_declaration_is_not_a_blinding_observation(final_ready):
    rd,manifest,value=final_ready
    policy=rd/'inputs/blinding.json';atomic_json(policy,{'policy':'SR data remain hidden'})
    observed=rd/'inputs/blinding-observation.json';atomic_json(observed,{'schema_version':1,'kind':'blinding_preservation_check',
        'policy_sha256':pin(policy)['sha256'],'status':'pass','sr_data_exposed':True,'checked_paths':[r['path'] for r in value['artifacts']]})
    value['blinding']={'mode':'blinded','policy':pin(policy),'check':pin(observed)}
    atomic_json(Path(manifest['path']),value)
    with pytest.raises(ValueError):judgment.open_final_cycle(rd,manifest=pin(Path(manifest['path'])),check_results='inputs/checks-final.json')


def test_simple_report_legacy_output_shape_and_public_parser_are_preserved(tmp_path):
    result=report.compose(report_fixture(tmp_path),base_dir=tmp_path)
    assert result['kind']=='scientific_quantitative_report' and 'final_results_review' not in result
    assert workflow_state.build_parser().parse_args(['delegated-go','--rundir','r']).cmd=='delegated-go'
    assert workflow_state.build_parser().parse_args(['revoke-delegation','--rundir','r','--user-text','u','--user-text-sha256','a'*64,'--quote','stop']).cmd=='revoke-delegation'
