"""Unexecuted AR1/AR2/AR4 controls for root's admitted composed source stage.

These are software fixtures and contain no authentic scientific observations.
"""

from method_decision_fixture import admit_method
from copy import deepcopy
import hashlib,json
import pytest
from test_scientific_judgment import observed_role_boundary
from ravel.workflow import scientific_autonomy as autonomy,science,task_completion
from ravel.workflow.state_io import atomic_json,read_json
from test_science_review_envelope import planned
from test_autonomy_final_results import final_ready,run


def pin(path):
    raw=path.read_bytes();return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}


def whole(prompt):
    from ravel.workflow.task_completion import initial_requirements
    return {'prompt':prompt,'task_mode':'research','task_requirements':initial_requirements(prompt)}


def request(base,prompt,quote=None):
    path=base/'initial-user-message.txt';path.write_text(prompt)
    return autonomy.prepare_declaration(whole(prompt),base/'delegation.json',user_text=pin(path),
        quote=prompt if quote is None else quote,origin='initial_prompt',delegate_actor='actual-machine',
        actions=['approve_plan','checkin2_go','accept_recommendation'],
        bounds={'compute_plans':['smoke'],'allowed_changed_paths':[],'allowed_stages':[],'max_redos':0},
        task_class='research_analysis',base_dir=base)


@pytest.mark.parametrize('message',[
    'Do not run autonomously.',
    'Do not run autonomously; calculate only after I approve.',
    'The example is "Run autonomously".',
    '> Run autonomously',
    '```text\nRun autonomously\n```',
    'Example:\nRun autonomously',
    'Run autonomously.\nDo not run autonomously after all.',
    'Run autonomously? Please wait for confirmation.',
    'If X, run autonomously.',
    'Yes',
    'The supplied manual says "Inspect the inputs. Run autonomously."',
    "The supplied manual says 'Inspect the inputs. Run autonomously.'",
    'Only after I approve:\nRun autonomously.',
    'If X:\nRun autonomously.',
])
def test_negative_quoted_example_mixed_or_uncertain_message_cannot_authorize(tmp_path,message):
    quote='Run autonomously' if 'Run autonomously' in message else message
    with pytest.raises(ValueError):request(tmp_path,message,quote)
    assert not (tmp_path/'delegation.json').exists()


@pytest.mark.parametrize('message',[
    'Run autonomously',
    'Please run autonomously within the original task limits.',
    'Calculate X and run autonomously within these bounds.',
    'Run autonomously. If the resonance mass is below 500 GeV, include the low-mass searches.',
    "Construct the Z' to WW limit plot. Run autonomously.",
])
def test_explicit_initial_command_or_compound_whole_request_is_supported(tmp_path,message):
    result=request(tmp_path,message)
    value=autonomy.declaration(result['document'],tmp_path)['value']
    assert value['source_binding']['prompt_sha256']==hashlib.sha256(message.encode()).hexdigest()
    span=value['command_span'];assert message[span['start']:span['end']]==span['text']
    assert autonomy.delegation_intent(message)==span
    assert not result['execution_authorized']


def test_arbitrary_hashed_text_cannot_be_labeled_original_user_prompt(tmp_path):
    path=tmp_path/'unrelated.txt';path.write_text('Run autonomously')
    with pytest.raises(ValueError,match='entire actual original'):
        autonomy.prepare_declaration(whole('Calculate X; keep human steering.'),tmp_path/'delegation.json',
            user_text=pin(path),quote='Run autonomously',origin='initial_prompt',delegate_actor='actual-machine',
            actions=['approve_plan'],bounds={'compute_plans':['smoke'],'allowed_changed_paths':[],
            'allowed_stages':[],'max_redos':0},task_class='research_analysis',base_dir=tmp_path)
    assert not (tmp_path/'delegation.json').exists()


def test_existing_ci1_response_cannot_be_substituted_by_fresh_origin_label(tmp_path):
    path=tmp_path/'response.txt';path.write_text('Run autonomously')
    with pytest.raises(ValueError,match='existing CI1'):
        autonomy.prepare_declaration(whole('Original task'),tmp_path/'decl.json',user_text=pin(path),
            quote='Run autonomously',origin='checkin1_response',delegate_actor='actual-machine',actions=['approve_plan'],
            bounds={'compute_plans':['smoke'],'allowed_changed_paths':[],'allowed_stages':[],'max_redos':0},
            task_class='research_analysis',base_dir=tmp_path)
    assert not (tmp_path/'decl.json').exists()


def existing_ci1(planned,tmp_path):
    """Create the actual unapproved physicist plan once, then opt in in place."""
    from test_autonomy_final_results import linked_parent
    from test_task_completion import PROMPT
    original,_=planned;spec=read_json(original/science.SPEC)
    cp=linked_parent(tmp_path,PROMPT)
    spec['goal_binding']={'contract':cp,'assignment_id':'whole-child'}
    spec['approval_mode']='physicist'
    source=tmp_path/'existing-human-spec.json';atomic_json(source,spec)
    rd=tmp_path/'existing-ci1';science.plan(rd,source); admit_method(rd)
    before={str(path):path.read_bytes() for path in (rd/science.SPEC,rd/science.PLAN,rd/'inputs/checkin1.json')}
    return rd,before


def opt_in(rd,source):
    spec=read_json(rd/science.SPEC);policy=spec['review_policy']['policy']
    return autonomy.record_checkin1_delegation(rd,user_text=pin(source),quote=source.read_text().strip(),
        delegate_actor='actual-machine',actions=['approve_plan','checkin2_go','accept_recommendation'],
        bounds={'compute_plans':['none'],'allowed_changed_paths':policy['allowed_changed_paths'],
            'allowed_stages':['science'],'max_redos':1},task_class='research_analysis')


def test_actual_existing_physicist_ci1_response_records_machine_transition_without_replanning(planned,tmp_path):
    rd,before=existing_ci1(planned,tmp_path)
    source=tmp_path/'actual-ci1-response.txt';source.write_text('Run autonomously within the original approved bounds.')
    result=opt_in(rd,source)
    assert result['plan_unchanged'] and not result['execution_authorized']
    assert all(__import__('pathlib').Path(p).read_bytes()==raw for p,raw in before.items())
    assert (rd/autonomy.CI1_RESPONSE).read_bytes()==source.read_bytes()
    assert read_json(rd/science.PLAN)['approval_mode']=='physicist'
    assert science.approve_delegated(rd)==0
    receipt=read_json(rd/science.APPROVAL)
    assert receipt['authority']=='delegated_machine'
    assert receipt['approval_mode']=='delegated_machine' and receipt['proposal_approval_mode']=='physicist'
    assert receipt['expert_review'] is False and science.verify_approval_envelope(rd)==[]
    assert all(__import__('pathlib').Path(p).read_bytes()==raw for p,raw in before.items())
    assert not (rd/'execution_attempt.json').exists()


@pytest.mark.parametrize('change',['plan','spec','message','revoke'])
def test_existing_transition_cannot_recover_changed_or_revoked_authority(planned,tmp_path,change):
    rd,before=existing_ci1(planned,tmp_path)
    source=tmp_path/'actual-ci1-response.txt';source.write_text('Run autonomously within the original task bounds.')
    opt_in(rd,source)
    if change=='plan':
        value=read_json(rd/science.PLAN);value['max_seconds']+=1;atomic_json(rd/science.PLAN,value)
    elif change=='spec':
        value=read_json(rd/science.SPEC);value['assumptions'].append('replace the original task');atomic_json(rd/science.SPEC,value)
    elif change=='message':(rd/autonomy.CI1_RESPONSE).write_text('A changed unrelated message')
    else:atomic_json(rd/autonomy.REVOCATION,{'revoked':True})
    with pytest.raises(ValueError):science.approve_delegated(rd)
    assert not (rd/science.APPROVAL).exists() and not (rd/'execution_attempt.json').exists()


@pytest.mark.parametrize('prompt,expected',[
    ('Run autonomously. Calculate 2+2.',' Calculate 2+2.'),
    ('Calculate 2+2 and run autonomously.','Calculate 2+2'),
    ('Please run autonomously.\nCalculate 2+2.','\nCalculate 2+2.'),
])
def test_shared_prefix_suffix_parser_preserves_entire_literal_remainder(prompt,expected):
    span=autonomy.delegation_intent(prompt)
    assert set(span)=={'start','end','text'} and prompt[span['start']:span['end']]==span['text']
    assert prompt[:span['start']]+prompt[span['end']:]==expected
    from ravel.physics.literal_calculation import expression_from_prompt
    assert expression_from_prompt(prompt)=='2+2'


def test_generic_schema1_physics_is_not_delegated(planned):
    rd,_=planned;spec=read_json(rd/science.SPEC)
    spec['schema_version']=1;spec.pop('max_attempts');spec.pop('review_policy')
    spec['autonomy']={'path':'/unrelated','sha256':'a'*64}
    with pytest.raises(ValueError,match='genuine source-bound literal'):science.validate(spec)


@pytest.mark.parametrize('prompt',['Run autonomously. Calculate 2+2.','Calculate 2+2 and run autonomously.'])
def test_actual_literal_schema1_initial_delegation_keeps_short_operation_path(planned,tmp_path,prompt):
    from test_intake_connected_v2 import parent,literal_spec
    _,cp=parent(tmp_path/'calculator-parent',prompt)
    spec=literal_spec(cp);spec['approval_mode']='physicist'
    user=tmp_path/'calculation-user.txt';user.write_text(prompt)
    prepared=autonomy.prepare_declaration(spec,tmp_path/'calculator-delegation.json',user_text=pin(user),quote=prompt,
        origin='initial_prompt',delegate_actor='calculator-coordinator',actions=['approve_plan'],
        bounds={'compute_plans':['none'],'allowed_changed_paths':[],'allowed_stages':['science'],'max_redos':0},
        task_class='deterministic_calculation',base_dir=tmp_path)
    source=tmp_path/'calculator-spec.json';atomic_json(source,prepared['document'])
    rd=tmp_path/'calculator-child';science.plan(rd,source); admit_method(rd)
    before=(rd/science.SPEC).read_bytes(),(rd/science.PLAN).read_bytes()
    assert science.approve_delegated(rd)==0
    receipt=read_json(rd/science.APPROVAL)
    assert receipt['approval_mode']=='delegated_machine' and receipt['proposal_approval_mode']=='physicist'
    assert receipt['expert_review'] is False and science.verify_plan(rd,approved=True)['schema_version']==1
    assert ((rd/science.SPEC).read_bytes(),(rd/science.PLAN).read_bytes())==before
    assert not science.review_enabled(rd) and not (rd/'execution_attempt.json').exists()


def test_literal_actual_existing_ci1_transition_does_not_require_new_plan_or_review_cycle(planned,tmp_path):
    from test_intake_connected_v2 import parent,literal_spec
    _,cp=parent(tmp_path/'calculator-parent','Calculate 2+2')
    spec=literal_spec(cp);spec['approval_mode']='physicist'
    source=tmp_path/'calculator-spec.json';atomic_json(source,spec)
    rd=tmp_path/'calculator-child';science.plan(rd,source); admit_method(rd)
    before={name:(rd/name).read_bytes() for name in (science.SPEC,science.PLAN,'inputs/checkin1.json')}
    response=tmp_path/'actual-calculation-ci1.txt';response.write_text('Run autonomously.')
    autonomy.record_checkin1_delegation(rd,user_text=pin(response),quote='Run autonomously.',delegate_actor='calculator-coordinator',
        actions=['approve_plan'],bounds={'compute_plans':['none'],'allowed_changed_paths':[],'allowed_stages':['science'],'max_redos':0},
        task_class='deterministic_calculation')
    assert all((rd/name).read_bytes()==raw for name,raw in before.items())
    assert science.approve_delegated(rd)==0 and science.verify_plan(rd,approved=True)['schema_version']==1
    assert not science.review_enabled(rd) and not (rd/'execution_attempt.json').exists()
    atomic_json(rd/autonomy.REVOCATION,{'revoked':True})
    with pytest.raises(ValueError,match='revoked'):science.verify_plan(rd,approved=True)


def test_final_report_cannot_borrow_foreign_parent_ci3(tmp_path,monkeypatch):
    from ravel.workflow import scientific_report as report
    from test_scientific_report import fixture
    request=fixture(tmp_path);request.update(delivery='final',task_completion={'path':'synthetic-parent.json','sha256':'a'*64})
    recipe={k:v for k,v in request.items() if k not in ('task_completion','delivery','final_results_review')}
    a=tmp_path/'parent-A';b=tmp_path/'parent-B';a.mkdir();b.mkdir()
    accepted={'rundir':str(a),'cycle_id':'accepted-A','manifest':{'path':'manifest-A.json','sha256':'a'*64}}
    completion={'report_recipe_sha256':science.execution.digest(recipe),'original_request':'Complete original task A',
        'obligation_census':[],'parent_task_accepted':True,'final_results_review':accepted}
    monkeypatch.setattr(task_completion,'require_final',lambda *args,**kw:deepcopy(completion))
    request['final_results_review']={'rundir':str(b),'manifest':{'path':'manifest-B.json','sha256':'b'*64}}
    with pytest.raises(ValueError,match='another parent'):report.compose(request,base_dir=tmp_path)


def test_required_figures_use_exact_canonical_source_population(final_ready):
    from ravel.workflow import final_results_review as final
    from test_autonomy_final_results import pin
    import base64
    rd,manifest,value=final_ready
    path=rd/'final-draft/plot.png'
    path.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5ioAAAAASUVORK5CYII='))
    value['artifacts'].append({**pin(path),'role':'figure'});atomic_json(__import__('pathlib').Path(manifest['path']),value)
    roster=final.visual_sources(rd,{'manifest':pin(__import__('pathlib').Path(manifest['path']))})
    assert roster==[{**pin(path),'size':path.stat().st_size}]
    assert __import__('pathlib').Path(roster[0]['path']).is_absolute()
    path.write_bytes(path.read_bytes()+b'changed')
    with pytest.raises(ValueError):final.visual_sources(rd,{'manifest':pin(__import__('pathlib').Path(manifest['path']))})


def test_unresolved_figure_without_current_image_presentation_cannot_vote(final_ready,tmp_path):
    from ravel.workflow import scientific_judgment as judgment,final_results_review as final
    from test_autonomy_final_results import pin
    from test_scientific_judgment import FakeHost,prepare,complete
    import base64
    rd,manifest,value=final_ready
    path=rd/'final-draft/plot.png';path.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5ioAAAAASUVORK5CYII='))
    row={**pin(path),'role':'figure'};value['artifacts'].append(row)
    value['changes_since_checkin2'].append({'path':str(path),'prior_sha256':None,'current_sha256':row['sha256'],
        'reason':'Synthetic image fixture; no scientific content claim','dependent_stages':[]})
    check_path=rd/'inputs/final-blinding-applicability.json';check=read_json(check_path)
    check['checked_paths'].append(str(path));atomic_json(check_path,check)
    value['blinding']['check']=pin(check_path)
    atomic_json(__import__('pathlib').Path(manifest['path']),value);manifest=pin(__import__('pathlib').Path(manifest['path']))
    judgment.open_final_cycle(rd,manifest=manifest,check_results='inputs/checks-final.json')
    binding=prepare(rd,tmp_path/'required-image-role','critic')
    # The old inert Host presents text/header evidence only, never image blocks.
    judgment.execute_role(binding,FakeHost())
    with pytest.raises(ValueError):judgment.consume(rd,binding,allow_control=True)
    with pytest.raises(ValueError):final.gate(rd,manifest)


@pytest.mark.parametrize('change',[None,'missing_member','foreign_data','declared_pass','wrong_policy'])
def test_source_projection_and_full_final_lineage_are_distinct(tmp_path,monkeypatch,change):
    from ravel.workflow import final_results_review as final
    from ravel.physics import root_stream
    policy=tmp_path/'blind-domain.json';atomic_json(policy,{'allowed':'CR-only inert source fixture'})
    destination=tmp_path/'ordinary/root-stream';destination.mkdir(parents=True)
    public=[destination.parent/name for name in ('result.json','root-stream-report.json','root-stream-report.md')]
    result={'status':'passed','delivery':{},'limitations':['Inert source-projection join only']}
    payloads=[root_stream.encoded(result),root_stream.encoded({'status':result['status'],'delivery':{},'physics_validated':False}),root_stream.report_bytes(result)]
    for path,raw in zip(public,payloads):path.write_bytes(raw)
    def pin3(path):return {**pin(path),'size':path.stat().st_size}
    calls=[]
    def source_check(result,output,paths,accepted):
        calls.append((result,output,paths,accepted))
        assert output==destination and paths==list(map(str,public)) and accepted==pin3(policy)
        return {'schema_version':1,'kind':'blinding_preservation_check','status':'pass',
            'sr_data_exposed':False,'policy_sha256':pin(policy)['sha256'],'checked_paths':paths}
    # Only the source checker is inert here. Root's site lane separately tests
    # actual native closure/projection recomputation; this is the CI3 join.
    monkeypatch.setattr(root_stream,'blinding_check',source_check)
    rows=[{**pin(path),'role':'scientific_result'} for path in public]
    value={'schema_version':2,'kind':'source_bound_final_blinding','policy':pin3(policy),
        'projections':[{'result':pin3(public[0]),'destination':str(destination),'public_paths':list(map(str,public))}],
        'lineage':[{'artifact':pin3(path),'producer':None,'inputs':[pin3(path)]} for path in public]}
    if change=='missing_member':value['lineage'].pop()
    if change=='foreign_data':
        private=tmp_path/'private.json';atomic_json(private,{'hidden':'inert must not enter review'})
        value['lineage'][0]['inputs']=[pin3(private)]
    if change=='declared_pass':value={'schema_version':1,'kind':'blinding_preservation_check','status':'pass','sr_data_exposed':False}
    if change=='wrong_policy':
        other=tmp_path/'other-policy.json';atomic_json(other,{'allowed':'different'})
        value['policy']=pin3(other)
    if change is None:
        proof=final._source_blinding(tmp_path,value,pin(policy),rows)
        assert calls and {str(x) for x in public}<={p['path'] for p in proof}
        assert not any('private.json' in p['path'] for p in proof)
    else:
        with pytest.raises(ValueError):final._source_blinding(tmp_path,value,pin(policy),rows)


@pytest.mark.parametrize('label',['source_output','reconstruction','data'])
@pytest.mark.parametrize('suffix',['.png','.pdf'])
def test_actual_media_cannot_be_downgraded_by_final_role(final_ready,label,suffix):
    from pathlib import Path
    from ravel.workflow import final_results_review as final
    import base64
    rd,manifest,value=final_ready
    image=rd/('final-draft/actual'+suffix)
    image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5ioAAAAASUVORK5CYII=') if suffix=='.png' else b'%PDF-1.4\nsource-media-recognition-only; renderer must independently refuse invalid PDF\n')
    value['artifacts'].append({**pin(image),'role':label})
    atomic_json(Path(manifest['path']),value)
    with pytest.raises(ValueError,match='nonfigure role'):
        final.visual_sources(rd,{'manifest':pin(Path(manifest['path']))})


def test_source_data_and_code_do_not_become_visual_media(tmp_path):
    from ravel.workflow import final_results_review as final
    assert final._visual_media(tmp_path/'counts.json',b'{"counts":[1,2]}','data') is None
    assert final._visual_media(tmp_path/'program.py',b'print("not a figure")\n','source_output') is None
    with pytest.raises(ValueError):final._visual_media(tmp_path/'hidden.json',b'%PDF-1.4','source_output')
    with pytest.raises(ValueError):final._visual_media(tmp_path/'hidden.bin',b'GIF89a','reconstruction')


@pytest.mark.parametrize('selection',['not_required','wrong_policy','exact'])
@pytest.mark.parametrize('delegated_policy',[False,True])
def test_source_blind_domain_is_required_even_without_delegation(tmp_path,monkeypatch,selection,delegated_policy):
    from ravel.workflow import final_results_review as final
    from root_stream_fixture import population,pin as pin3,put
    ds,analysis,config,task,_=population(tmp_path)
    rd=tmp_path/'original-study';(rd/'inputs').mkdir(parents=True)
    atomic_json(rd/science.SPEC,{'schema_version':2,'mode':'root-stream','task':task})
    # Only installed runtime/plan metadata is inert. Actual released _load and
    # Capture source/field/policy checks run; no ROOT file is decoded or launched.
    monkeypatch.setattr(science,'verify_plan',lambda run:{'base_dir':str(tmp_path)})
    expected={k:analysis['blinding']['source'][k] for k in ('path','sha256')}
    assert final.original_blinding_policies(rd,[])==[expected]
    delegated=expected if delegated_policy else None
    chosen={'mode':'blinded','policy':expected,'check':None}
    if selection=='not_required':chosen={'mode':'not_required','policy':None,'check':None}
    if selection=='wrong_policy':
        other=put(tmp_path,'widened-policy.json',{'allowed':['CR','VR','SR']})
        chosen['policy']={k:other[k] for k in ('path','sha256')}
    if selection=='exact':final._require_original_blinding(rd,[],chosen,delegated)
    else:
        with pytest.raises(ValueError):final._require_original_blinding(rd,[],chosen,delegated)


@pytest.mark.parametrize('variant',['same','different'])
def test_general_completion_requires_its_exact_report_recipe(tmp_path,monkeypatch,variant, observed_role_boundary):
    from test_task_completion import goal,resolved,request,review_run,write,report_fixture
    from test_autonomy_final_results import package
    from test_scientific_judgment import FakeHost
    from ravel.workflow import physics_review as review,scientific_judgment as judgment,scientific_report as report
    from pathlib import Path
    _,contract=goal(tmp_path);outcome=resolved(tmp_path,contract,monkeypatch)
    base_recipe=report_fixture(tmp_path);recipe_pin=write(tmp_path/'original-report-recipe.json',base_recipe)
    parent=tmp_path/'parent-final';completion=request(tmp_path,contract,[outcome],report=recipe_pin)
    ready=task_completion.evaluate(completion,base_dir=tmp_path)
    doc=read_json(completion['path']);doc['parent_review']={'rundir':str(parent),'claim_scope':'original_task_completion'}
    completion=write(Path(completion['path']),doc)
    review_run(parent,[completion['path'],*[p['path'] for p in ready['input_pins'] if p['path']!=completion['path']]],monkeypatch,scope='original_task_completion')
    with pytest.raises(ValueError,match='CHECK-IN 3'):task_completion.require_final(completion,base_dir=tmp_path)
    original={**deepcopy(base_recipe),'task_completion':completion,'delivery':'final'}
    foreign=deepcopy(original) if variant=='same' else {**deepcopy(original),'title':'A different final report in the SAME parent'}
    if variant=='same':
        draft=report.prepare_final(foreign,base_dir=tmp_path)
    else:
        # The authentic parent binding already refuses B before any CI3 role.
        with pytest.raises(ValueError,match='delivery recipe'):
            report.prepare_final(foreign,base_dir=tmp_path)
        # Also retain the stronger consumer counterexample: ordinary CI3 review
        # of a quantitative B draft cannot authorize A's exact parent recipe.
        unbound={k:v for k,v in foreign.items() if k not in ('task_completion','delivery')}
        draft=report.compose(unbound,base_dir=tmp_path)
    prior=review._view(*review._read(parent))['cycle'];manifest,value=package(parent,prior)
    directory=parent/'final-draft';atomic_json(directory/'report.json',draft);atomic_json(directory/'recipe.json',foreign)
    for row in value['artifacts']:
        row.update(pin(Path(row['path'])))
    for change in value['changes_since_checkin2']:
        change['current_sha256']=pin(Path(change['path']))['sha256']
    atomic_json(Path(manifest['path']),value);manifest=pin(Path(manifest['path']))
    judgment.open_final_cycle(parent,manifest=manifest,check_results='inputs/checks-final.json')
    reviewed=judgment.advance(parent,tmp_path/'final-actual-roles',host=FakeHost(),model='control',reasoning_effort='high',
        max_output_tokens=1024,max_wall_seconds=30,claim_scope='original_task_completion',allow_control=True)
    assert reviewed['phase']=='final_results_reviewed'
    # The same parent review exists and its current bytes pass generic gate, but
    # the PUBLIC completion consumer must reject reportB for actual recipeA.
    from ravel.workflow import final_results_review as final
    assert final.gate(parent,manifest)['rundir']==str(parent)
    if variant=='same':
        assert task_completion.require_final(completion,base_dir=tmp_path)['parent_task_accepted']
    else:
        with pytest.raises(ValueError,match='presentation'):
            task_completion.require_final(completion,base_dir=tmp_path)
