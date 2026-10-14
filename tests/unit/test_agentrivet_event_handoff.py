"""Prospective ordinary build/event handoff controls, not native qualification.

Source roles use real ordinary Graph APIs with inert transport. Retained native
predecessor authority and compilation are explicit synthetic fixture seams; the
new constructor, typed input readers, public science plan and worker dispatch
are real. No fake authority is carried into delivered scientific acceptance.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest
from ravel.physics import agentrivet_source, existing_events, routine_build, science_worker
from ravel.workflow import agentrivet_construction as operation, science, execution, research_tools
from ravel.workflow.state_io import atomic_json, read_json
from agentrivet_construction_fixture import allow_own_source_census, host, triplet, MODEL, CODE, pin
from test_agentrivet_construction import prepared, generated
from test_agentrivet_source import pure_plan, complete_capsule, runtime_template
from test_rivet_built_adapter import evidence, task as built_task
from test_rivet_preload import fixture as preload_fixture


def workload(base, rp, operation_name='events', seconds=120):
    path=base/(operation_name+'-workload.json')
    atomic_json(path,{'schema_version':1,'kind':'agentrivet-ordinary-workload',
        'operation':operation_name,'construction_request':rp,'max_seconds':seconds})
    return pin(path)


def event_fixture(base, monkeypatch):
    raw,rp=prepared(base)
    code=CODE.decode()+'\nvoid fixture() { declareCentrality(Observable(), "Calibration", "V0M", "CENT"); }\n'
    queue=[deepcopy(MODEL),*triplet(code=code)];seen=[]
    actor=host(monkeypatch,queue,seen)
    gp=operation.generate(rp,base_dir=base,host=actor)
    root,plugin,_,cc,_,_=evidence(base,monkeypatch)
    cc.write_bytes(operation._bytes(read_json(gp['path'])['raw_request']['translation_unit'],Path(gp['path']).parent)[1])
    plan=read_json(root/'build-plan.json');plan['routine']='TEST';atomic_json(root/'build-plan.json',plan)
    selected={'source_files':[{'path':str(cc),'sha256':pin(cc)['sha256']}]}
    monkeypatch.setattr(routine_build,'bound_routine',lambda *a:selected)
    def retained_native_boundary(rd, backend):
        assert Path(rd)==root and backend=='routine-build'
        return {},root,{'status':'passed','physics_validated':False},pin(root/'build-receipt.json')
    monkeypatch.setattr(operation,'_ordinary_result',retained_native_boundary)
    event=built_task();event.update(routine='TEST')
    event.pop('build_plan');event.pop('build_receipt')
    event['observables'][0]['path']='/TEST/count'
    reference=base/'reference.json';atomic_json(reference,{'source':'whole supplied synthetic reference'})
    event['grounding']=[{'path':reference.name,'sha256':pin(reference)['sha256']}]
    return raw,rp,gp,root,event,[{'index':0,'path':'/TEST/count'}],workload(base,rp),cc


def prepare_event(base, monkeypatch, *, event_change=None, seconds=120, suffix='events-prepared'):
    raw,rp,gp,root,event,mapping,wp,cc=event_fixture(base,monkeypatch)
    if seconds!=120:wp=workload(base,rp,seconds=seconds)
    if event_change:event_change(event,rp,gp,base)
    before=deepcopy(event)
    result=operation.prepare_events(rp,gp,root,event,mapping,wp,base_dir=base,output_dir=base/suffix)
    assert event==before
    return raw,rp,gp,event,wp,result


def test_complete_relative_event_inputs_exact_ceiling_survive_real_ordinary_plan(tmp_path,monkeypatch,pure_plan):
    raw,rp,gp,event,wp,result=prepare_event(tmp_path,monkeypatch)
    binding=read_json(result['path']);spec=read_json(binding['specification']['path'])
    assert spec['max_seconds']==120 and existing_events.execution_seconds(spec['task'],tmp_path)==1
    assert binding['workload']==wp and spec['goal_binding']==read_json(rp['path'])['goal_binding']
    assert spec['task']['events']==str(tmp_path/'events.hepmc')
    assert spec['task']['metadata']==str(tmp_path/'metadata.json')
    assert spec['task']['observables']==event['observables'] and spec['task']['seed']==event['seed']
    assert {row['path'] for row in binding['source_inputs']}=={str(p) for p in science.task_inputs(spec,Path(binding['specification']['path']).parent)}
    rd=tmp_path/'ordinary-event-run';science.plan(rd,binding['specification']['path'])
    plan=science.verify_plan(rd,approved=False)
    assert plan['max_seconds']==120 and plan['execution_task']==spec['task']
    assert not (rd/'execution_attempt.json').exists() and not binding['execution_authorized']
    assert not binding['physics_validated']


def test_exact_identical_operation_grounding_is_retained_once(tmp_path,monkeypatch,pure_plan):
    def same(event,rp,gp,base):
        event['grounding'] += [rp,gp,read_json(gp['path'])['raw_request']['paper']]
    _,rp,gp,_,wp,result=prepare_event(tmp_path,monkeypatch,event_change=same)
    task=read_json(read_json(result['path'])['specification']['path'])['task']
    # The construction evidence (checks, bookings, checklist) is grounded for reviewers.
    evidence=read_json(gp['path'])['construction_evidence']
    assert len(task['grounding'])==6
    for wanted in (rp,gp,wp,evidence):assert task['grounding'].count(wanted)==1
    assert len(existing_events._grounding_inputs(task,tmp_path))==6


@pytest.mark.parametrize('defect',['missing','bytes','alias','conflicting_pin','canonical_duplicate'])
def test_original_grounding_refuses_without_dropping_population(tmp_path,monkeypatch,pure_plan,defect):
    def changed(event,rp,gp,base):
        reference=base/'reference.json'
        if defect=='missing':reference.unlink()
        elif defect=='bytes':reference.write_text('changed source')
        elif defect=='alias':
            link=base/'alias.json';link.symlink_to(reference);event['grounding'][0]['path']=str(link)
        elif defect=='conflicting_pin':event['grounding'] += [{'path':rp['path'],'sha256':'0'*64}]
        else:event['grounding'] += [{'path':'./reference.json','sha256':pin(reference)['sha256']}]
    with pytest.raises((ValueError,OSError)):prepare_event(tmp_path,monkeypatch,event_change=changed)
    assert not (tmp_path/'events-prepared').exists()


def test_preload_source_origin_and_native_object_paths_retain_actual_base(tmp_path,monkeypatch,pure_plan):
    raw,rp,gp,root,event,mapping,wp,cc=event_fixture(tmp_path,monkeypatch)
    value,_,calibration=preload_fixture(tmp_path,original=cc)
    # Restore the exact authenticated generation bytes after preload_fixture writes its own source.
    cc.write_bytes(operation._bytes(read_json(gp['path'])['raw_request']['translation_unit'],Path(gp['path']).parent)[1])
    law=value['centrality_preload'];line=next(i for i,text in enumerate(cc.read_text().splitlines(),1) if 'declareCentrality' in text)
    law['routine_source'].update(sha256=pin(cc)['sha256'],first_line=line,last_line=line,text=cc.read_text().splitlines()[line-1])
    event.update(options=value['options'],centrality_preload=law)
    result=operation.prepare_events(rp,gp,root,event,mapping,wp,base_dir=tmp_path,output_dir=tmp_path/'preloaded-study')
    spec=read_json(read_json(result['path'])['specification']['path']);new=spec['task']
    assert new['centrality_preload']['path']==str(calibration)
    assert new['centrality_preload']['origin']['path']==str(calibration)
    assert new['observables']==event['observables'] and new['options']==event['options']
    assert set(existing_events.inputs(new,tmp_path/'preloaded-study'))>=set(existing_events.inputs({**event,'build_plan':str(root/'build-plan.json'),'build_receipt':str(root/'build-receipt.json')},tmp_path))


@pytest.mark.parametrize('operation_name',['build','events'])
@pytest.mark.parametrize('defect',['absent','changed','wrong_operation','other_request','boolean','too_large','spent_budget','expired'])
def test_explicit_workload_cannot_renew_or_borrow_original_budget(tmp_path,monkeypatch,operation_name,defect):
    _,rp=prepared(tmp_path);request=read_json(rp['path']);wp=workload(tmp_path,rp,operation_name)
    if defect=='absent':wp=None
    elif defect=='changed':Path(wp['path']).write_text('{}')
    elif defect=='expired':
        _,state=operation.research_cycle._load(request['campaign'])
        state['timing'].update(started_epoch=1.,deadline_epoch=2.)
        monkeypatch.setattr(operation.research_cycle,'_load',lambda *a:(None,state))
    elif defect=='spent_budget':
        _,state=operation.research_cycle._load(request['campaign'])
        state['resource_ledger'].append({'id':'already-reserved','ceiling':{'calls':0,'output_tokens':0,'wall_seconds':state['contract']['budget']['wall_seconds'],'native_attempts':0},'basis':{}})
        monkeypatch.setattr(operation.research_cycle,'_load',lambda *a:(None,state))
    else:
        value=read_json(wp['path'])
        if defect=='wrong_operation':value['operation']='events' if operation_name=='build' else 'build'
        elif defect=='other_request':value['construction_request']=pin(tmp_path/'paper.txt')
        elif defect=='boolean':value['max_seconds']=True
        else:value['max_seconds']=86400
        atomic_json(wp['path'],value);wp=pin(Path(wp['path']))
    with pytest.raises((ValueError,TypeError)):
        operation._workload(rp,request,wp,operation_name,tmp_path)


def test_workload_equality_preserves_remaining_original_ceiling_without_charge(tmp_path):
    _,rp=prepared(tmp_path);request=read_json(rp['path'])
    _,state=operation.research_cycle._load(request['campaign'])
    seconds=state['contract']['budget']['wall_seconds']
    wp=workload(tmp_path,rp,seconds=seconds)
    assert operation._workload(rp,request,wp,'events',tmp_path)[2]==seconds
    assert operation.research_cycle._load(request['campaign'])[1]['resource_ledger']==[]


def test_late_original_input_change_refuses_before_delivering_preparation(tmp_path,monkeypatch,pure_plan):
    raw,rp,gp,root,event,mapping,wp,cc=event_fixture(tmp_path,monkeypatch)
    real=operation._emit;fired=[]
    def changed(path,value):
        result=real(path,value)
        if Path(path).name=='science-spec.json':
            (tmp_path/'reference.json').write_text('late original byte change');fired.append(True)
        return result
    monkeypatch.setattr(operation,'_emit',changed)
    with pytest.raises(ValueError):operation.prepare_events(rp,gp,root,event,mapping,wp,base_dir=tmp_path,output_dir=tmp_path/'late-input-study')
    assert fired and (tmp_path/'late-input-study/science-spec.json').exists()
    assert not (tmp_path/'late-input-study/event-preparation.json').exists()


def build_fixture(base,monkeypatch):
    raw,rp,gp,_,_=generated(base,monkeypatch)
    generation=read_json(gp['path']);spec=read_json(generation['source_study']['specification']['path'])
    source_out=base/'source-delivery';source_out.mkdir()
    result=agentrivet_source.run(spec['task'],Path(generation['source_study']['specification']['path']).parent,source_out)
    atomic_json(source_out/'result.json',result)
    def retained_source_boundary(rd,backend):
        assert Path(rd)==source_out and backend=='agentrivet-source'
        return spec,source_out,result,pin(source_out/'result.json')
    monkeypatch.setattr(operation,'_ordinary_result',retained_source_boundary)
    capsule,closure=complete_capsule(base,result);runtime,probe=runtime_template(base,capsule)
    return rp,gp,source_out,capsule,closure,runtime,probe,workload(base,rp,'build')


def test_build_whole_ceiling_survives_real_source_preparation_and_plan(tmp_path,monkeypatch,pure_plan):
    rp,gp,rd,capsule,closure,runtime,probe,wp=build_fixture(tmp_path,monkeypatch)
    result=operation.prepare_build(rp,gp,rd,pin(capsule),pin(closure),pin(runtime),wp,probe=probe,base_dir=tmp_path,output_dir=tmp_path/'built-study')
    binding=read_json(result['path']);spec=read_json(binding['specification']['path'])
    assert spec['max_seconds']==120 and routine_build.execution_seconds(spec['task'],tmp_path/'built-study')==1
    assert binding['workload']==wp and not binding['execution_authorized']
    run=tmp_path/'ordinary-build-run';science.plan(run,binding['specification']['path'])
    plan=science.verify_plan(run,approved=False)
    assert plan['max_seconds']==120 and plan['execution_task']==spec['task']
    assert not (run/'execution_attempt.json').exists()


@pytest.mark.parametrize('selected',['build','events'])
def test_real_ordinary_plan_to_worker_dispatch_preserves_full_task_and_base(tmp_path,monkeypatch,pure_plan,selected):
    if selected=='build':
        rp,gp,old,capsule,closure,runtime,probe,wp=build_fixture(tmp_path,monkeypatch)
        result=operation.prepare_build(rp,gp,old,pin(capsule),pin(closure),pin(runtime),wp,probe=probe,base_dir=tmp_path,output_dir=tmp_path/'worker-prepared')
        implementation=routine_build
    else:
        _,_,_,_,_,result=prepare_event(tmp_path,monkeypatch,suffix='worker-prepared');implementation=existing_events
    binding=read_json(result['path']);spec=read_json(binding['specification']['path'])
    rd=tmp_path/'worker-run';science.plan(rd,binding['specification']['path'])
    plan=science.verify_plan(rd,approved=False)
    # Explicit worker-registration/approval seam: no OS process or scientific
    # execution authority is fabricated. Actual execution_spec and dispatch run.
    monkeypatch.setattr(science_worker,'verify_worker',lambda _rd:{**plan,'output_directory':'outputs/attempt-1','attempt':1})
    observed=[]
    class NativeBoundaryReached(Exception):pass
    def stop(task,base,out,**kwargs):
        observed.append((deepcopy(task),Path(base),Path(out)));raise NativeBoundaryReached()
    monkeypatch.setattr(implementation,'run',stop)
    if hasattr(implementation,'run_in_worker'):monkeypatch.setattr(implementation,'run_in_worker',stop)
    with pytest.raises(NativeBoundaryReached):science_worker.main([str(rd)])
    assert observed==[(spec['task'],Path(plan['base_dir']),rd/'outputs/attempt-1/analysis' if selected=='events' else rd/'outputs/attempt-1')]
    assert plan['max_seconds']==120


@pytest.mark.parametrize('family',['derived','density','categorical','cumulant'])
def test_existing_typed_native_source_populations_survive_relocation(tmp_path,monkeypatch,pure_plan,family):
    from ravel.physics import native_cumulant
    import os
    raw,rp,gp,root,event,mapping,wp,cc=event_fixture(tmp_path,monkeypatch)
    if family=='derived':
        from test_native_estimate import sample
        # Reuse only the fixture constructor, not its test or transport result.
        operand_dir=tmp_path/'derived-data';operand_dir.mkdir()
        _,quantity=sample.__wrapped__(operand_dir)
        event['observables'].append(quantity)
    elif family=='density':
        from test_native_density import sample
        _,quantity=sample.__wrapped__(tmp_path);event['observables'].append(quantity)
    elif family=='categorical':
        source=tmp_path/'categorical.cc';source.write_text('Source categorical finalization fixture.\n')
        excerpt={**pin(source),'first_line':1,'last_line':1,'text':source.read_text().strip()}
        dependency=tmp_path/'CategoricalAPI.hh';dependency.write_text('Literal native categorical grammar fixture.\n')
        dep={**pin(dependency),'first_line':1,'last_line':1,'text':dependency.read_text().strip()}
        event['observables'].append({'path':'/TEST/category','axes':[{'name':'flavour','unit':'1','native_type':'S'}],
            'representation':'native','normalization':'absolute','unit':'1','quantity_kind':'native_categorical',
            'native_categorical':{'source':{**excerpt,'path':source.name},'source_dependencies':[dep],
                'final_native_type':'BINNEDESTIMATE<S>','raw_objects':[],
                'source_finalization':'Literal synthetic finalize source, no physics interpretation.',
                'native_error_semantics':'Native marginal errors retained.',
                'flow_policy':'retain_all','group_covariance':'not_supplied',
                'native_weight':{'native':'','suffix':''}}})
        # The existing contract requires at least one literal RAW object.
        event['observables'][-1]['native_categorical']['raw_objects']=[{'id':'raw','path':'/RAW/TEST/category','role':'raw_operand','native_type':'BINNEDHISTO<S>','unit':'1'}]
    else:
        from cumulant_fixture import mapping
        supplied=mapping(tmp_path/'mapping')
        event['routine']=supplied['routine']
        supplied['sources']=[{**source,'path':os.path.relpath(source['path'],tmp_path)} for source in supplied['sources']]
        event['observables']=native_cumulant.requests_for(supplied)
    event.update(build_plan=str(root/'build-plan.json'),build_receipt=str(root/'build-receipt.json'))
    session=execution._validation_session(tmp_path)
    try:
        original,relocated,before=operation._relocate_event_task(event,tmp_path,session)
        newbase=tmp_path/'new-source-base';newbase.mkdir()
        after=operation._input_census(existing_events.inputs(relocated,newbase),newbase,session)
        assert before==after and original==event
        assert [q['path'] for q in relocated['observables']]==[q['path'] for q in event['observables']]
        if family=='derived':assert relocated['observables'][-1]['native_derived']['operands']==event['observables'][-1]['native_derived']['operands']
        if family=='density':assert relocated['observables'][-1]['native_density']['raw_histogram_path']==event['observables'][-1]['native_density']['raw_histogram_path']
        if family=='categorical':assert relocated['observables'][-1]['native_categorical']['raw_objects']==event['observables'][-1]['native_categorical']['raw_objects']
        if family=='cumulant':assert len(relocated['observables'])==len(supplied['outputs'])
        assert not session.finish()
    finally:session.close()


@pytest.mark.parametrize('different_file',[False,True])
def test_lineage_identity_uses_exact_original_base_and_path_not_digest_alone(tmp_path,different_file):
    from ravel.physics import native_incumbent
    original=tmp_path/'lineage.json';original.write_text('{"source":"same bytes"}\n')
    nested=tmp_path/'nested';nested.mkdir()
    actual=original
    if different_file:actual=nested/'lineage.json';actual.write_bytes(original.read_bytes())
    left={'path':'lineage.json','sha256':pin(original)['sha256']}
    right={'path':str(actual),'sha256':pin(actual)['sha256']}
    assert native_incumbent.same_bound_pin(left,tmp_path,right,nested) is (not different_file)


def test_relative_lineage_evaluation_keeps_original_build_and_nested_operand_bases(tmp_path,monkeypatch,pure_plan):
    from ravel.physics import native_incumbent
    from ravel import analysis_sources
    raw,rp,gp,root,event,mapping,wp,cc=event_fixture(tmp_path,monkeypatch)
    lineage=tmp_path/'lineage.json';atomic_json(lineage,{'source':'explicit synthetic native authority seam'})
    original_pin=pin(lineage)
    plan=read_json(root/'build-plan.json');plan['improvement_lineage']=original_pin;atomic_json(root/'build-plan.json',plan)
    config=tmp_path/'routine-build.json';atomic_json(config,{'source_capsule':str(tmp_path/'capsule.json'),'improvement_lineage':original_pin})
    evaluation_dir=tmp_path/'evaluation';evaluation_dir.mkdir()
    evaluation=evaluation_dir/'evaluation.json'
    def relative(p):return {'path':'../'+p.name,'sha256':pin(p)['sha256']}
    atomic_json(evaluation,{'schema_version':1,'kind':'native-improvement-evaluation',
        'improvement_lineage':relative(lineage),'partition':'full_case',
        'events':relative(tmp_path/'events.hepmc'),'metadata':relative(tmp_path/'metadata.json'),
        'checker_inputs':[relative(tmp_path/'reference.json')]})
    event.update(improvement_lineage={'path':lineage.name,'sha256':original_pin['sha256']},
                 improvement_evaluation={'path':'evaluation/evaluation.json','sha256':pin(evaluation)['sha256']})
    # Only accepted-incumbent provenance/native authority is synthetic. The
    # real event_inputs body still reads the actual plan/config/evaluation,
    # exact bound identities, checker files and complete HepMC event census.
    record={'source_routine':'OLD'}
    monkeypatch.setattr(native_incumbent,'validate_lineage',lambda *a:record)
    monkeypatch.setattr(analysis_sources,'load_capsule',lambda *a:{'routine':'TEST'})
    observed=[]
    def retained_source(pin_value,capsule,base):
        assert pin_value==original_pin and Path(base)==tmp_path
        observed.append(deepcopy(pin_value));return record,[lineage]
    monkeypatch.setattr(native_incumbent,'source_binding',retained_source)
    monkeypatch.setattr(existing_events,'execution_seconds',lambda *a:200)
    wp=workload(tmp_path,rp,seconds=240)
    result=operation.prepare_events(rp,gp,root,event,mapping,wp,base_dir=tmp_path,output_dir=tmp_path/'lineage-study')
    new=read_json(read_json(result['path'])['specification']['path'])['task']
    assert new['improvement_lineage']==original_pin and new['improvement_evaluation']==pin(evaluation)
    assert read_json(evaluation)['improvement_lineage']==relative(lineage)
    assert read_json(root/'build-plan.json')['improvement_lineage']==original_pin
    assert {lineage,evaluation,tmp_path/'events.hepmc',tmp_path/'metadata.json',tmp_path/'reference.json'}<=set(native_incumbent.event_inputs(new,tmp_path/'lineage-study'))
    assert observed and all(p==original_pin for p in observed)
    substitute=tmp_path/'equal-but-distinct.json';substitute.write_bytes(lineage.read_bytes())
    wrong=deepcopy(new);wrong['improvement_lineage']=pin(substitute)
    with pytest.raises(ValueError,match='omit or transplant'):native_incumbent.event_inputs(wrong,tmp_path/'lineage-study')


@pytest.mark.parametrize('selected',['build','events'])
def test_public_coordinator_requires_and_forwards_same_workload_pin(tmp_path,monkeypatch,selected):
    raw,rp=prepared(tmp_path);wp=workload(tmp_path,rp,selected)
    captured=[]
    if selected=='build':
        arguments={'request':rp,'generation':rp,'source_rundir':'source-run','reviewed_capsule':rp,
            'closure':rp,'runtime':rp,'probe':{},'workload':wp}
        def call(*args,**kwargs):captured.append((args,kwargs));return {'prepared':True}
        monkeypatch.setattr(operation,'prepare_build',call)
    else:
        arguments={'request':rp,'generation':rp,'build_rundir':'build-run','event_task':{},'histogram_mapping':[],'workload':wp}
        def call(*args,**kwargs):captured.append((args,kwargs));return {'prepared':True}
        monkeypatch.setattr(operation,'prepare_events',call)
    selection=tmp_path/'selected-step.json';atomic_json(selection,{'action':'prepare-build' if selected=='build' else 'prepare-events','arguments':arguments})
    assert research_tools.routine_step(raw['campaign'],{**pin(selection),'size':selection.stat().st_size},base_dir=tmp_path,output_dir=tmp_path/'step')=={'prepared':True}
    assert captured[0][0][-1]==wp
    arguments.pop('workload');atomic_json(selection,{'action':'prepare-build' if selected=='build' else 'prepare-events','arguments':arguments})
    with pytest.raises(ValueError):research_tools.routine_step(raw['campaign'],{**pin(selection),'size':selection.stat().st_size},base_dir=tmp_path,output_dir=tmp_path/'missing')
    assert len(captured)==1
