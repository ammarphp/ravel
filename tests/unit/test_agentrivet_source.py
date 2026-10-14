"""Real source/build/review APIs; synthetic stage receipts, no executed jobs."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest
from ravel import analysis_sources
from ravel.physics import agentrivet_source as source, routine_build
from ravel.physics.science_worker import diagnostic_presentation
from ravel.plotting import science_figures
from ravel.workflow import science, execution, launch_authorization, physics_review
from ravel.workflow.state_io import atomic_json, read_json
import test_agentrivet_candidate as supplied


def review_wrapper():
    return {'schema_version':1,'policy':{'schema_version':1,
        'actors':{'proposer':'supplier','executor':'source-worker','physics_critic':'source-critic',
                  'skeptical_verifier':'source-verifier','physics_decider':'source-decider'},
        'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
        'required_checks':[{'id':'integrity','kind':'integrity'}, {'id':'domain-census','kind':'scientific'}],
        'claim_scopes':{'source_delivery':{'checks':['integrity','domain-census'],'actions':['delivery','reuse']}}},
        'correction_contract':{'task_fields':[],'input_slots':[]}}


def small_stage(rd, stage, command, inputs, outputs, parents, cwd, **kwargs):
    """Original unit-test pattern; never a process-authenticity substitute."""
    inputs = list(inputs)
    executable = str(Path(sys.executable).resolve())
    if executable not in inputs:
        inputs.append(executable)
    binding={'command':list(command),'cwd':str(Path(cwd).resolve()),'inputs':list(inputs),
        'outputs':list(outputs),'parents':{},'runtime':execution.runtime_context(),
        'input_snapshot':execution.snapshot(rd,inputs)}
    binding['fingerprint']=execution.digest(binding)
    return binding


@pytest.fixture
def pure_plan(monkeypatch):
    monkeypatch.setattr(execution,'plan_stage',small_stage)
    monkeypatch.setattr(execution,'runtime_context',lambda:{'platform':'inert source-only fixture',
        'python':sys.version,'environment_sha256':execution.digest(execution.runtime_environment()),
        'packages_sha256':execution.digest({'fixture':'no scientific dependencies imported'})})
    monkeypatch.setattr(launch_authorization,'audit_launches',lambda *a,**k:[])
    monkeypatch.setattr(routine_build.subprocess,'run',lambda *a,**k:pytest.fail('native/compiler or job dispatch'))


def materialized(tmp_path):
    request=supplied.fixture(tmp_path/'inputs')
    prepared=source.prepare_source_study(request,base_dir=tmp_path,
        output_dir=tmp_path/'prepared',review_policy=review_wrapper(),approval_mode='scripted_yes')
    out=tmp_path/'source-output';out.mkdir()
    result=source.run(prepared['task'],tmp_path/'prepared',out)
    atomic_json(out/'result.json',result)
    return request,prepared,result,supplied.pin(out/'result.json')


def complete_capsule(tmp_path,result):
    original=read_json(result['capsule']['path']);reviewed=deepcopy(original)
    reviewed['dependency_review']={'complete':True,'description':'Synthetic ordinary closure guard; not native header qualification'}
    reviewed['dependencies'][0].update(status='resolved',reason='Synthetic fixture declaration, no actual native build claim')
    p=tmp_path/'reviewed-capsule.json';atomic_json(p,reviewed)
    closure={'schema_version':1,'kind':'agentrivet-source-closure-declaration',
        'proposal':result['proposal'],'reviewed_capsule':supplied.pin(p),'reviewer':'supplied-source-reviewer',
        'declarations':[{'id':row['id'],'status':'requires_event_test','evidence':'Declared source mapping; synthetic fixture only'} for row in result['domain_obligations']],
        'limitations':['All paper/native/reference/complete-event qualification remains unserved.']}
    cp=tmp_path/'closure.json';atomic_json(cp,closure)
    return p,cp


def runtime_template(tmp_path,capsule):
    tools=tmp_path/'synthetic-tools';tools.mkdir()
    for name in ('fixturecxx','probe','python'):
        p=tools/name;p.write_text('Synthetic executable bytes; MUST NEVER RUN\n');p.chmod(0o755)
    builder=tools/'rivet-build';builder.write_text('''rivetcxx=$(which $(echo "fixturecxx" | awk '{print $1}') 2> /dev/null)
if [[ -x "$rivetcxx" ]]; then
mycxx="fixturecxx"
elif [[ -x "$abscxx" ]]; then
mycxx="$CXX"
fi
''');builder.chmod(0o755)
    probe={'executable':'probe','arguments':['--show-analysis','TEST'],'expected_exit_code':0,'stdout_contains':['TEST']}
    config={'schema_version':1,'source_capsule':str(capsule),
        'recipe':{'name':'rivet-plugin','compile_units':['TEST.cc'],'output':'RivetTEST.so','flags':[]},
        'runtime':{'tools':{name:supplied.pin(tools/file) for name,file in [('compiler','fixturecxx'),('build','rivet-build'),('probe','probe'),('python','python')]},
                   'artifacts':[],'environment':{'PATH':str(tools)}},'probe':probe}
    raw=tmp_path/'runtime-draft.json';atomic_json(raw,config)
    sealed=routine_build.seal_configuration({'backend':'routine-build','input':str(raw)},tmp_path)
    p=tmp_path/'runtime-sealed.json';atomic_json(p,sealed)
    return p,probe


def test_source_task_normal_plan_review_context_and_fresh_build_plan(pure_plan,tmp_path):
    request=supplied.fixture(tmp_path/'inputs')
    prepared=source.prepare_source_study(request,base_dir=tmp_path,
        output_dir=tmp_path/'prepared',review_policy=review_wrapper(),approval_mode='scripted_yes')
    rd=tmp_path/'source-run';science.plan(rd,prepared['specification']['path'])
    plan=science.verify_plan(rd,approved=False)
    assert plan['execution_task']==prepared['task'] and plan['max_attempts']==1
    assert not (rd/'execution_attempt.json').exists()
    from method_decision_fixture import admit_method
    admit_method(rd)
    science.approve(rd,'Synthetic source-only lifecycle control; no actual job',scripted=True)
    token={'attempt':1,'plan_sha256':execution.file_hash(rd/science.PLAN),'budget_seconds':60,
           'started_utc':execution.utc_now(),'correction_id':None,'correction_plan_sha256':None}
    atomic_json(rd/'execution_attempt.json',token);atomic_json(rd/'logs/science-attempts/00000001.json',token)
    stage=plan['stages'][0]
    record=execution.begin_attempt(rd,'science',plan['stage_binding'],stage['log'])
    out=rd/'outputs/attempt-1';out.mkdir(parents=True)
    result=source.run(plan['execution_task'],plan['base_dir'],out)
    atomic_json(out/'result.json',result)
    atomic_json(out/'recipe.json',{'task':prepared['task']})
    atomic_json(out/'verification.json',{'passed':True,'scope':'supplier_source_materialization_delivery',
        'physics_validated':False,'expert_review':False,'result_sha256':analysis_sources.digest(out/'result.json')})
    atomic_json(out/'checkin2.json',{'schema_version':1,'kind':'checkin2','sections':{
        'waypoint':'Synthetic retained lifecycle fixture','expectation':'Source delivery only','ask':{'options':['GO','ADJUST']}}})
    (rd/stage['log']).write_text('Synthetic stage receipt; no OS worker or native job executed.\n')
    presentation,text=diagnostic_presentation('analyze',result)
    assert presentation['status_scope']=='supplier_source_materialization_delivery'
    assert 'review remains required' in text and not presentation['physics_validated']
    rendered=science_figures.render(read_json(rd/science.SPEC),result,plan['base_dir'],out)
    assert rendered['figures']==[]
    report=(out/'domain-declarations.md').read_text()
    assert all(row['id'] in report and row['selector'] in report for row in result['domain_obligations'])
    assert execution.finish_attempt(rd,record,0)==0
    atomic_json(rd/'inputs/source-checks.json',{'schema_version':1,'checks':[
        {'id':cid,'status':'pass','attempt_ids':[record['attempt_id']],
         'evidence':[{'path':'outputs/attempt-1/result.json','location':'$.domain_obligations'}]}
        for cid in ('integrity','domain-census')]})
    cycle=physics_review.open_cycle(rd,effective_settings=science.review_effective_settings(rd),
        stage_receipts=[record['attempt_record']],check_results='inputs/source-checks.json')
    assert cycle['cycle_id']
    assert physics_review.gate_errors(rd,'delivery')
    assert physics_review.status(rd)['state']!='accepted'
    capsule,closure=complete_capsule(tmp_path,result)
    runtime,probe=runtime_template(tmp_path,capsule)
    build=source.prepare_build(supplied.pin(out/'result.json'),supplied.pin(capsule),supplied.pin(closure),supplied.pin(runtime),
        probe=probe,base_dir=tmp_path,output_dir=tmp_path/'build-preparation')
    native_plan=routine_build.build_plan(build['task'],tmp_path,tmp_path/'unexecuted-build-output')
    assert native_plan['recipe']['compile_units']==['TEST.cc']
    assert native_plan['compute_authorized'] is False and not native_plan['physics_validated']
    assert not (tmp_path/'unexecuted-build-output').exists()
    assert build['prior_reviews_carried']==[] and not build['execution_authorized']
    assert 'execution_identity' not in read_json(build['draft']['path'])
    assert read_json(build['sealed']['path'])['schema_version']==2


def test_v1_and_inner_budget_refuse_normal_source_admission(pure_plan,tmp_path):
    _,prepared,_,_=materialized(tmp_path)
    spec=read_json(prepared['specification']['path']);spec['schema_version']=1
    spec.pop('review_policy');spec.pop('max_attempts')
    p=tmp_path/'legacy.json';atomic_json(p,spec)
    with pytest.raises(ValueError,match='version 2'):science.plan(tmp_path/'legacy-run',p)
    spec=read_json(prepared['specification']['path']);spec['max_seconds']=59
    with pytest.raises(ValueError,match='adapter execution budget'):science.task_inputs(spec,tmp_path/'prepared')


def test_same_call_source_drift_refuses_after_materialization(tmp_path,monkeypatch):
    _,prepared,_,_=materialized(tmp_path)
    original=source.candidate.import_candidate
    def mutate(request,**kwargs):
        result=original(request,**kwargs)
        Path(request['paper']['path']).write_text('changed during source materialization')
        return result
    monkeypatch.setattr(source.candidate,'import_candidate',mutate)
    out=tmp_path/'changed-output';out.mkdir()
    with pytest.raises(ValueError,match='actual consumed bytes differ'):source.run(prepared['task'],tmp_path/'prepared',out)


@pytest.mark.parametrize('mutation',['incomplete_capsule','changed_code','missing_url','wrong_probe','changed_tool','changed_proposal','prior_reviews'])
def test_fresh_build_seal_never_bypasses_closure_source_or_denominator(pure_plan,tmp_path,mutation):
    _,_,result,result_pin=materialized(tmp_path)
    capsule,closure=complete_capsule(tmp_path,result);runtime,probe=runtime_template(tmp_path,capsule)
    if mutation=='incomplete_capsule':
        c=read_json(capsule);c['dependency_review']['complete']=False;atomic_json(capsule,c)
    elif mutation=='changed_code':
        c=read_json(capsule);p=Path(c['root'])/'TEST.cc';p.write_bytes(b'Changed new candidate must be reimported')
        c['files'][0]['sha256']=analysis_sources.digest(p);atomic_json(capsule,c)
    elif mutation=='missing_url':
        c=read_json(closure);c['declarations']=[r for r in c['declarations'] if r['id']!='hepdata_url'];atomic_json(closure,c)
    elif mutation=='wrong_probe':probe['stdout_contains']=['OtherRoutine']
    elif mutation=='changed_tool':Path(read_json(runtime)['runtime']['tools']['compiler']['path']).write_text('changed executable')
    elif mutation=='changed_proposal':
        r=read_json(result_pin['path']);r['domain_obligations']=r['domain_obligations'][:-1];atomic_json(result_pin['path'],r);result_pin=supplied.pin(Path(result_pin['path']))
    else:
        r=read_json(result_pin['path']);r['prior_reviews_carried']=['upstream approval'];atomic_json(result_pin['path'],r);result_pin=supplied.pin(Path(result_pin['path']))
    with pytest.raises(ValueError):source.prepare_build(result_pin,supplied.pin(capsule),supplied.pin(closure),supplied.pin(runtime),
        probe=probe,base_dir=tmp_path,output_dir=tmp_path/'new-build')
