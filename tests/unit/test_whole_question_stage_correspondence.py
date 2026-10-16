"""Real ordinary source APIs with inert fixtures; no generated physics samples."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import pytest

from ravel.physics import model_event_commitment as custody
from ravel.physics.ma5_pad import InputCapture
from ravel.workflow import stage_correspondence as correspondence, resonance_study as rs, science, execution
from test_model_events import config, write
from test_resonance_study import fixture, pin


@pytest.fixture(autouse=True)
def no_execution(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k: (_ for _ in ()).throw(AssertionError('pure source control')))
    monkeypatch.setattr(execution,'runtime_context',lambda:{'source_control_inert_runtime':True,
        'environment_sha256':execution.digest(execution.runtime_environment())})


def producer(base):
    process=base/'process';events=process/'Events/run';events.mkdir(parents=True)
    (events/'sample.hepmc').write_text('Inert committed member, not a scientific event stream\n')
    (events/'unselected.txt').write_text('Complete unselected member\n')
    (events/'empty').mkdir()
    commitment=custody.snapshot(process)
    request={'process':str(process),'config':{'complete_original_config':True}}
    rows=[{k:r[k] for k in ('path','sha256','size')} for r in commitment['files']]
    result={'status':'passed','intended':request['config'],'generated_member_commitment':commitment,
        'generated_artifacts':rows}
    return process,commitment,request,result,{'files':rows}


def test_exact_complete_producer_member_positive(tmp_path):
    process,commitment,request,result,census=producer(tmp_path)
    before=deepcopy((commitment,request,result,census));capture=InputCapture()
    observed=custody.member(commitment,request,result,census,'Events/run/sample.hepmc',capture)
    assert observed==pin(process/'Events/run/sample.hepmc')
    assert len(capture.streams)==2 and before==(commitment,request,result,census)


@pytest.mark.parametrize('fault',['selected_bytes','added_unselected','removed_unselected','removed_directory',
    'same_bytes_replacement','root_replacement','symlink','fifo','foreign','duplicate','old_record','wrong_source'])
def test_original_whole_member_custody_refusals(tmp_path,fault):
    process,commitment,request,result,census=producer(tmp_path)
    selected=process/'Events/run/sample.hepmc';relative='Events/run/sample.hepmc'
    if fault=='selected_bytes': selected.write_text('Changed scientific member')
    elif fault=='added_unselected': (selected.parent/'late.dat').write_text('Late')
    elif fault=='removed_unselected': (selected.parent/'unselected.txt').unlink()
    elif fault=='removed_directory': (selected.parent/'empty').rmdir()
    elif fault=='same_bytes_replacement':
        original=selected.read_bytes();selected.rename(selected.with_suffix('.old'));selected.write_bytes(original)
    elif fault=='root_replacement':
        root=process/'Events';root.rename(process/'old-Events');root.mkdir()
    elif fault in ('symlink','fifo'):
        selected.unlink()
        if fault=='symlink': selected.symlink_to(selected.parent/'unselected.txt')
        else: os.mkfifo(selected)
    elif fault=='foreign': relative='../other'
    elif fault=='duplicate': census['files'].append(deepcopy(census['files'][0]))
    elif fault=='old_record': commitment={}
    elif fault=='wrong_source': result['intended']={'asserted_label_only':True}
    with pytest.raises((ValueError,OSError)):
        custody.member(commitment,request,result,census,relative,InputCapture())


def test_late_unselected_membership_refuses_after_selected_capture(tmp_path):
    process,commitment,request,result,census=producer(tmp_path)
    class Late(InputCapture):
        def finish(self):
            super().finish()
            (process/'Events/late-unselected').write_text('late')
    with pytest.raises(ValueError,match='membership'):
        custody.member(commitment,request,result,census,'Events/run/sample.hepmc',Late())


def generation_recipe(base, *, scheme='unmerged_lo', variations=False):
    path,recipe=fixture(base/'recipe')
    for h in recipe['hypotheses']:
        h.update(mass_gev=172.5,width_gev=1.4,interference='none',basis='bsm')
        source=config(base/h['id'],scheme=scheme,variations=variations);cp=write(base/h['id']/'generation.json',source)
        h['model']=source['model_tree']['manifest'];h['sources']=[h['model']]
        template=deepcopy(recipe['stages'][0]);spec=json.loads(Path(template['study']['path']).read_text())
        spec.update(mode='model-events',task={'config':cp['path']},max_seconds=60)
        study=write(base/h['id']/'study.json',spec)
        stage={'id':'generate_'+h['id'],'hypothesis':h['id'],'search':None,'role':'prediction',
            'study':study,'documents':[{'id':'generation_config','task_key':'config','source':cp}],
            'links':[],'exports':{'result':'result.json'},'claim_scope':'diagnostic','missing':[]}
        recipe['stages'].insert(0,stage)
    for search in recipe['searches']:
        search['applicability'].update(mass_gev=[100.,750.],width_over_mass=[.001,.25],bases=['bsm'])
    for h in recipe['hypotheses']:
        stage=next(s for s in recipe['stages'] if s['id']=='generate_'+h['id'])
        spec=json.loads(Path(stage['study']['path']).read_text())
        projected=correspondence.project(spec,Path(stage['study']['path']).parent,InputCapture())
        mapping={'schema_version':2,'original_study':stage['study'],'hypothesis_sha256':rs._digest(h),
            'search_sha256':None,'projected_target':projected,
            'bindings':[{'field':f,'address':a} for f,a in [('energy_tev',None),('model_sha256',None),
                ('mass_gev','MASS/6'),('width_gev','DECAY/6')]],'sources':[h['model']],'limitations':[]}
        stage['target_mapping']=write(base/h['id']/'mapping.json',mapping)
    for pair in recipe['pairs']:
        h=next(h for h in recipe['hypotheses'] if h['id']==pair['hypothesis'])
        search=next(s for s in recipe['searches'] if s['id']==pair['search'])
        mapping=json.loads(Path(pair['mapping']['path']).read_text())
        mapping.update(hypothesis_sha256=rs._digest(h),search_sha256=rs._digest(search),basis=h['basis'])
        pair['mapping']=write(Path(pair['mapping']['path']),mapping)
        pair['stages'].insert(0,'generate_'+h['id'])
    write(path,recipe)
    return path,recipe


def test_actual_generation_projection_and_ordinary_preparation(tmp_path):
    path,recipe=generation_recipe(tmp_path/'source')
    assessed=rs.assess(path)
    assert len(assessed['pairs'])==2 and not any(row['blockers'] for row in assessed['pairs'])
    stage=next(s for s in recipe['stages'] if s['id']=='generate_H0')
    target=assessed['pairs'][0]['stage_targets'][0]
    assert target['projection']['facts']['parameter_values']['MASS/6']=='172.5'
    assert target['comparison']['checked_fields']==['energy_tev','mass_gev','model_sha256','width_gev']
    assert 'cp' in target['comparison']['source_premises']
    prepared=rs.prepare_stage(path,stage['id'],{},tmp_path/'prepared')
    spec=json.loads(Path(prepared['specification']['path']).read_text())
    assert spec['mode']=='model-events' and spec['goal_binding']['contract']==recipe['parent_contract']
    assert Path(path) in science.task_inputs(spec,tmp_path/'prepared')
    science.plan(tmp_path/'ordinary',prepared['specification']['path'])
    science.verify_plan(tmp_path/'ordinary',approved=False)
    assert not (tmp_path/'ordinary'/science.APPROVAL).exists()


@pytest.mark.parametrize('field,value',[('mass_gev',400.),('width_gev',20.),('energy_tev',14.)])
def test_resealed_labels_never_override_actual_card_or_beam(tmp_path,field,value):
    path,recipe=generation_recipe(tmp_path/'source')
    h=recipe['hypotheses'][0];h[field]=value
    stage=next(s for s in recipe['stages'] if s['id']=='generate_'+h['id'])
    mapped=json.loads(Path(stage['target_mapping']['path']).read_text());mapped['hypothesis_sha256']=rs._digest(h)
    stage['target_mapping']=write(Path(stage['target_mapping']['path']),mapped);write(path,recipe)
    with pytest.raises(ValueError,match='operative|beam'): rs.assess(path)


def test_unsupported_semantic_binding_and_wrong_model_refuse(tmp_path):
    path,recipe=generation_recipe(tmp_path/'source');h=recipe['hypotheses'][0]
    stage=next(s for s in recipe['stages'] if s['id']=='generate_'+h['id'])
    mapped=json.loads(Path(stage['target_mapping']['path']).read_text())
    mapped['bindings'].append({'field':'cp','address':'asserted-even'})
    stage['target_mapping']=write(Path(stage['target_mapping']['path']),mapped);write(path,recipe)
    with pytest.raises(ValueError,match='semantic labels'):rs.assess(path)


def test_adapter_task_path_registry_does_not_open_arbitrary_links():
    spec={'mode':'analyze','task':{'backend':'rivet','events':'existing.hepmc'}}
    assert correspondence.task_slot(spec,'events')=='events_path'
    for key in ('source_root','runtime','metadata','options'):
        with pytest.raises(ValueError):correspondence.task_slot(spec,key)
    with pytest.raises(ValueError):correspondence.task_slot({'mode':'model-events','task':{'config':'x'}},'config')


def test_actual_native_card_full_regions_and_absent_physics_stay_explicit(tmp_path):
    from test_native_likelihood import fixture as native_fixture
    cp,config,_,_,_=native_fixture(tmp_path)
    projection=correspondence.project({'mode':'native-likelihood','task':{'input':str(cp)},'max_seconds':config['max_seconds']+60},tmp_path,InputCapture())
    assert projection['facts']['regions']==config['model']['regions']
    assert projection['facts']['fit']==config['fit']
    assert {'energy_tev','model_sha256','mass_gev','basis'}<=set(projection['unavailable_typed_fields'])


def test_real_analysis_projection_preserves_whole_metadata_and_observables(tmp_path,monkeypatch):
    from test_rivet_built_adapter import task, evidence
    evidence(tmp_path,monkeypatch)
    spec={'mode':'analyze','task':task(),'max_seconds':60}
    projection=correspondence.project(spec,tmp_path,InputCapture())
    assert projection['facts']['energy_tev']=='13'
    assert projection['facts']['observables']==spec['task']['observables']
    assert projection['facts']['metadata']['events']==1
    assert projection['facts']['metadata']['weight_names']==['nominal']
    altered=deepcopy(projection);altered['facts']['metadata']['cross_section_pb']=2
    with pytest.raises(ValueError):correspondence.same_target(projection,altered)


@pytest.mark.parametrize('fault',[None,'old_commitment','late_unselected','original_source'])
def test_accepted_recorded_member_uses_actual_original_materialized_config(tmp_path,monkeypatch,fault):
    path,recipe,stage,rd,process,output=accepted_case(tmp_path,monkeypatch)
    stages=rs._load(path)[5]
    if fault=='old_commitment':(output/'generated-member-commitment.json').unlink()
    elif fault=='original_source':
        changed=json.loads((output/'native-input.json').read_text());changed['config']['generation']['energy_gev']=[7000,7000]
        write(output/'native-input.json',changed)
    capture=InputCapture()
    if fault in ('old_commitment','original_source'):
        with pytest.raises((ValueError,OSError)):rs._accepted(stages[stage['id']],rd,capture,pin(path))
        return
    observed=rs._accepted(stages[stage['id']],rd,capture,pin(path))
    assert observed[2]['events']==pin(process/'Events/run/sample.hepmc')
    if fault=='late_unselected':
        (process/'Events/new-unselected').write_text('late')
        with pytest.raises(ValueError):rs._finish_accepted([observed],capture)
    else:rs._finish_accepted([observed],capture)


def test_complete_portfolio_correspondence_and_disclosed_source_refusals(tmp_path):
    path,recipe=generation_recipe(tmp_path/'source')
    rows=[s for s in recipe['stages'] if s['role']=='prediction']
    proposal={'experiments':[{'id':s['id'],'study':s['study']} for s in rows]}
    manifest={'schema_version':1,'recipe':pin(path),
        'stages':[{'experiment':s['id'],'stage':s['id']} for s in rows]}
    proposal['stage_correspondence']=write(tmp_path/'correspondence.json',manifest)
    presented=[proposal['stage_correspondence'],*rs.input_pins(path)]
    assert rs.portfolio_correspondence(proposal,tmp_path,presented)==manifest
    with pytest.raises(ValueError,match='Host inputs'):
        rs.portfolio_correspondence(proposal,tmp_path,[proposal['stage_correspondence']])
    incomplete=deepcopy(manifest);incomplete['stages'].pop()
    proposal['stage_correspondence']=write(tmp_path/'incomplete.json',incomplete)
    with pytest.raises(ValueError,match='missing portfolio'):
        rs.portfolio_correspondence(proposal,tmp_path,[proposal['stage_correspondence'],*presented])


def test_native_model_file_slot_preserves_staged_identity_and_closed_pin():
    original={'path':'model.txt','sha256':'a'*64,'staged_path':'model.txt'}
    doc={'model':{'files':[original]}}
    spec={'mode':'native-likelihood','task':{'input':'native.json'}}
    assert correspondence.document_slot(spec,doc,'/model/files/0',original)=={'staged_path':'model.txt'}
    for pointer in ('/model/files/00','/runtime/tools/native','/model/files/0/path'):
        with pytest.raises(ValueError):correspondence.document_slot(spec,doc,pointer,original)


def analysis_link_case(base, monkeypatch):
    """Real linked intake with an explicit inert predecessor review boundary."""
    from test_rivet_built_adapter import task, evidence
    from test_model_events import hepmc
    path,recipe=generation_recipe(base/'source',scheme='mlm',variations=True)
    generation=next(s for s in recipe['stages'] if s['id']=='generate_H0')
    original=Path(generation['documents'][0]['source']['path']);cfg=json.loads(original.read_text())
    cfg['outputs']['hepmc_relative']='Events/run/sample.hepmc'
    generation['documents'][0]['source']=write(original,cfg)
    mapped=json.loads(Path(generation['target_mapping']['path']).read_text())
    mapped['projected_target']=correspondence.project(json.loads(Path(generation['study']['path']).read_text()),original.parent,InputCapture())
    generation['target_mapping']=write(Path(generation['target_mapping']['path']),mapped)
    generation['exports']['events']={'kind':'generated_member','path':'Events/run/sample.hepmc','format':'HepMC2'}
    analysis_base=base/'analysis-source';evidence(analysis_base,monkeypatch)
    raw=hepmc().replace(' 0 3 1 2 3',' 0 3 2 2 3',1)
    (analysis_base/'events.hepmc').write_text(raw)
    metadata=json.loads((analysis_base/'metadata.json').read_text())
    metadata.update(events=3,weight_names=['nominal','scale_1001','scale_1002'])
    metadata_pin=write(analysis_base/'metadata.json',metadata)
    source=json.loads(Path(generation['study']['path']).read_text())
    source.update(mode='analyze',task=task());source['task']['runtime']['version']='4.1.3'
    study=write(analysis_base/'science.json',source)
    h=next(h for h in recipe['hypotheses'] if h['id']=='H0')
    analysis={'id':'analyze_H0','hypothesis':'H0','search':None,'role':'response','study':study,
        'documents':[{'id':'analysis_metadata','task_key':'metadata','source':metadata_pin}],
        'links':[{'task_key':'events','from_stage':'generate_H0','export':'events'}],
        'exports':{'result':'result.json'},'claim_scope':'diagnostic','missing':[]}
    projection=correspondence.project(source,analysis_base,InputCapture())
    analysis['target_mapping']=write(analysis_base/'mapping.json',{'schema_version':2,'original_study':study,
        'hypothesis_sha256':rs._digest(h),'search_sha256':None,'projected_target':projection,
        'bindings':[{'field':'energy_tev','address':None}],'sources':[h['model']],'limitations':[]})
    recipe['stages'].insert(recipe['stages'].index(generation)+1,analysis)
    next(p for p in recipe['pairs'] if p['hypothesis']=='H0')['stages'].insert(1,'analyze_H0')
    write(path,recipe)
    prepared=rs.prepare_stage(path,'generate_H0',{},base/'generation-prepared')
    producer_spec=json.loads(Path(prepared['specification']['path']).read_text())
    rd=base/'inert-accepted-producer';output=rd/'outputs/attempt-1';output.mkdir(parents=True)
    process,_,request,result,_=producer(rd/'work')
    events=process/'Events/run/sample.hepmc';events.write_text(raw)
    commitment=custody.snapshot(process);rows=[{k:r[k] for k in ('path','sha256','size')} for r in commitment['files']]
    config_document=json.loads(Path(producer_spec['task']['config']).read_text())
    request['config']=config_document
    result.update(intended=config_document,generated_member_commitment=commitment,generated_artifacts=rows,
        shower_population={'returned_events':3,'weight_names':metadata['weight_names'],'format':'HepMC2','complete_framing':True,'raw_sha256':pin(events)['sha256']})
    for name,value in [('native-input.json',request),('model-events-native.json',result),('generated-member-commitment.json',commitment)]:write(output/name,value)
    def accepted(entry,run,capture,request_pin):
        assert entry[0]['id']=='generate_H0' and Path(run)==rd
        event_pin=custody.member(commitment,request,result,{'files':rows},'Events/run/sample.hepmc',capture)
        return rd,producer_spec,{'events':event_pin}, {'explicit_inert_review_boundary':True},output,set(output.iterdir()),False
    original_verify=science.verify_plan
    monkeypatch.setattr(rs,'_accepted',accepted)
    monkeypatch.setattr(science,'verify_plan',lambda root,*a,**k: None if Path(root)==rd else original_verify(root,*a,**k))
    original_spec=science.execution_spec
    monkeypatch.setattr(science,'execution_spec',lambda root,**kwargs: producer_spec if Path(root)==rd else original_spec(root,**kwargs))
    monkeypatch.setattr(rs.physics_review,'snapshot',lambda *a,**k:{'explicit_inert_review_boundary':True})
    return path,recipe,rd,events,analysis_base


def test_generated_event_path_reaches_real_analysis_intake_and_ordinary_plan(tmp_path,monkeypatch):
    path,recipe,rd,events,_=analysis_link_case(tmp_path,monkeypatch)
    prepared=rs.prepare_stage(path,'analyze_H0',{'generate_H0':str(rd)},tmp_path/'analysis-prepared')
    spec=json.loads(Path(prepared['specification']['path']).read_text())
    assert spec['task']['events']==str(events) and spec['task']['backend']=='rivet-built'
    assert spec['goal_binding']['contract']==recipe['parent_contract']
    pins=rs.handoff_inputs(spec,tmp_path/'analysis-prepared')
    assert pin(events) in pins and not prepared['execution_authorized']
    science.plan(tmp_path/'ordinary-analysis',prepared['specification']['path'])
    science.verify_plan(tmp_path/'ordinary-analysis',approved=False)
    assert not (tmp_path/'ordinary-analysis'/science.APPROVAL).exists()


def test_consumer_metadata_cannot_relabel_original_generated_population(tmp_path,monkeypatch):
    path,recipe,rd,events,base=analysis_link_case(tmp_path,monkeypatch)
    metadata=json.loads((base/'metadata.json').read_text());metadata['events']=2
    # A fully resealed metadata declaration still cannot replace the observed
    # original producer exposure. All ordinary source hashes are refreshed in
    # this synthetic fixture, but its actual event commitment is unchanged.
    write(base/'metadata.json',metadata)
    stage=next(s for s in recipe['stages'] if s['id']=='analyze_H0')
    stage['documents'][0]['source']=pin(base/'metadata.json')
    mapping=json.loads(Path(stage['target_mapping']['path']).read_text())
    source=json.loads(Path(stage['study']['path']).read_text())
    mapping['projected_target']=correspondence.project(source,base,InputCapture())
    stage['target_mapping']=write(Path(stage['target_mapping']['path']),mapping);write(path,recipe)
    # The real route first refuses a predecessor from the previous recipe
    # epoch. Do not weaken that gate merely to reach a later witness.
    with pytest.raises(ValueError,match='recipe epoch'):
        rs.prepare_stage(path,'analyze_H0',{'generate_H0':str(rd)},tmp_path/'refused')
    # Independently exercise the actual population boundary with the same
    # explicitly inert accepted-review fixture and original committed stream.
    source['task']['events']=str(events)
    observed=rs._accepted(rs._load(path)[5]['generate_H0'],rd,InputCapture(),pin(path))
    with pytest.raises(ValueError,match='population'):
        rs._producer_analysis_population(source,base,observed,InputCapture())


def test_pin_transport_preserves_full_template_law_without_asserting_basis():
    facts={'bridge':{'template':{'path':'old.json','sha256':'a'*64}},'template':{'channels':[{'name':'SR','data':[3,4]}]}}
    original={'mode':'signal-template','facts':facts,'goal_binding':None,'unavailable_typed_fields':['basis']}
    moved=deepcopy(original);moved['facts']['bridge']['template']['path']='accepted.json'
    correspondence.same_target(original,moved)
    moved['facts']['template']['channels'][0]['data'][1]=5
    with pytest.raises(ValueError):correspondence.same_target(original,moved)
    with pytest.raises(ValueError,match='basis unavailable'):
        correspondence.compare(original,{'basis':'bsm','interference':'none'},None,[{'field':'basis','address':None}])


def test_native_file_document_handoff_preserves_complete_card_and_staged_name(tmp_path,monkeypatch):
    from test_native_likelihood import fixture as native_fixture
    path,recipe=generation_recipe(tmp_path/'source')
    (tmp_path/'native').mkdir()
    cp,doc,_,_,_=native_fixture(tmp_path/'native')
    original_stage=next(s for s in recipe['stages'] if s['role']=='constraint' and s['hypothesis']=='H0')
    spec=json.loads(Path(original_stage['study']['path']).read_text());spec.update(mode='native-likelihood',task={'input':str(cp)},max_seconds=doc['max_seconds']+60)
    stage=deepcopy(original_stage);stage['study']=write(tmp_path/'native/study.json',spec)
    stage['documents']=[{'id':'native_config','task_key':'input','source':pin(cp)}]
    generation=next(s for s in recipe['stages'] if s['id']=='generate_H0')
    generation['exports']['card']='model.txt'
    stage['links']=[{'document':'native_config','pointer':'/model/files/0','from_stage':generation['id'],'export':'card'}]
    h=next(h for h in recipe['hypotheses'] if h['id']=='H0');search=recipe['searches'][0]
    stage['target_mapping']=write(tmp_path/'native/mapping.json',{'schema_version':2,'original_study':stage['study'],'hypothesis_sha256':rs._digest(h),'search_sha256':rs._digest(search),
        'projected_target':correspondence.project(spec,cp.parent,InputCapture()),'bindings':[],'sources':[h['model']],'limitations':[]})
    recipe['stages'][recipe['stages'].index(original_stage)]=stage;write(path,recipe)
    # A separately accepted earlier source may expose only a recorded ordinary
    # card. Its complete content must equal the declared native law; no YODA-to-
    # likelihood transformation or missing detector response is invented.
    out=tmp_path/'inert-predecessor/outputs';out.mkdir(parents=True)
    source_card=Path(doc['model']['files'][0]['path']);source_card=source_card if source_card.is_absolute() else cp.parent/source_card
    card=out/'model.txt';card.write_bytes(source_card.read_bytes())
    header=write(tmp_path/'inert-predecessor/handoff.json',{'request':pin(path)})
    predecessor={'resonance_handoff':header['path']}
    monkeypatch.setattr(rs,'_accepted',lambda *a:(out.parent,predecessor,{'card':pin(card)}, {'inert_review':True},out,{card},False))
    monkeypatch.setattr(rs,'_finish_accepted',lambda rows,c:c.finish())
    prepared=rs.prepare_stage(path,stage['id'],{'generate_H0':str(out.parent)},tmp_path/'native-prepared')
    effective=json.loads(Path(prepared['specification']['path']).read_text());config=json.loads(Path(effective['task']['input']).read_text())
    assert config['model']['files'][0]=={**pin(card),'staged_path':doc['model']['files'][0]['staged_path']}
    assert config['model']['regions']==doc['model']['regions'] and config['fit']==doc['fit']
    science.task_inputs(effective,tmp_path/'native-prepared')
    card.write_bytes(card.read_bytes()+b'\n# source changed\n')
    with pytest.raises(ValueError):rs.handoff_inputs(effective,tmp_path/'native-prepared')


@pytest.mark.parametrize('fault',[None,'added_unselected','removed_unselected','changed_result'])
def test_actual_common_worker_final_publication_binds_complete_generation(tmp_path,monkeypatch,fault):
    from ravel.physics import science_worker
    from types import SimpleNamespace
    rd=tmp_path/'run';rd.mkdir();process,commitment,request,result,census=producer(rd/'work')
    result.update(physics_validated=False,status_scope='source_bound_generated_event_delivery',generated_events=1,scope='inert complete producer record')
    spec={'schema_version':2,'mode':'model-events','task':{'config':'inert'},'assumptions':['Explicit fake native boundary; no events generated']}
    monkeypatch.setattr(science_worker,'verify_worker',lambda root:{'base_dir':str(rd),'stage_binding':{'input_snapshot':{}},'output_directory':'outputs'})
    monkeypatch.setattr(science_worker,'execution_spec',lambda root:spec)
    def run(task,base,out):
        for name,value in [('native-input.json',request),('model-events-native.json',result),('generated-member-commitment.json',commitment),('generated-artifact-census.json',census),('model-events.json',result)]:write(out/name,value)
        return deepcopy(result)
    monkeypatch.setattr(science_worker,'adapter',lambda spec:SimpleNamespace(run=run))
    from ravel.plotting import science_figures
    monkeypatch.setattr(science_figures,'render',lambda *a:{'figures':[],'tables':[]})
    old=science_worker.atomic_json
    def ending(path,value):
        old(path,value)
        if Path(path).name=='checkin2.json':
            if fault=='added_unselected':(process/'Events/late-unselected').write_text('late')
            elif fault=='removed_unselected':(process/'Events/run/unselected.txt').unlink()
            elif fault=='changed_result':write(rd/'outputs/result.json',{**result,'status':'failed'})
    monkeypatch.setattr(science_worker,'atomic_json',ending)
    if fault is None:assert science_worker.main([str(rd)])==0
    else:
        with pytest.raises(ValueError):science_worker.main([str(rd)])
    assert (rd/'outputs/RESULT.md').is_file()


def test_complete_events_rechecked_after_review_refresh(tmp_path,monkeypatch):
    process,commitment,request,result,census=producer(tmp_path/'producer')
    output=tmp_path/'run/outputs';output.mkdir(parents=True)
    write(output/'native-input.json',request);write(output/'generated-member-commitment.json',commitment)
    spec={'mode':'model-events'};snapshot={'explicit_inert_review_boundary':True}
    monkeypatch.setattr(science,'verify_plan',lambda *a,**k:None)
    monkeypatch.setattr(science,'execution_spec',lambda *a,**k:spec)
    def refresh(*a,**k):
        (process/'Events/late-during-review').write_text('late')
        return snapshot
    monkeypatch.setattr(rs.physics_review,'snapshot',refresh)
    row=(output.parent,spec,{},snapshot,output,set(output.iterdir()),False)
    with pytest.raises(ValueError,match='membership'):rs._finish_accepted([row],InputCapture())


def test_full_width_domain_and_all_missing_cells_remain_source_facts(tmp_path):
    from test_mass_width_grid import request_fixture,put
    path,doc,_=request_fixture(tmp_path/'width',missing=True)
    masses=[17,29,311];widths=[.017,.12,.47]
    doc['axes']=[{'name':'mass_GeV','values':masses},{'name':'width_over_mass','values':widths}]
    doc['cells']=[{'coordinate':{'mass_GeV':m,'width_over_mass':w},'generation_request':None,'response':None,'missing':['Actual source response and integer law absent']} for m in masses for w in widths];put(path,doc)
    projection=correspondence.project({'mode':'mass-width-grid','task':{'input':str(path)},'goal_binding':doc['goal_binding'],'max_seconds':60},path.parent,InputCapture())
    assert len(projection['facts']['cells'])==9 and projection['facts']['document']['regional_input'] is None
    assert all(row['missing'] for row in projection['facts']['cells']) and 'physical_prediction_or_inference' in projection['unavailable_typed_fields']
    assert projection['facts']['document']['goal_binding']==doc['goal_binding']
    doc['cells'].pop();put(path,doc)
    with pytest.raises(ValueError,match='denominator'):correspondence.project({'mode':'mass-width-grid','task':{'input':str(path)},'goal_binding':doc['goal_binding'],'max_seconds':60},path.parent,InputCapture())


def test_full_svj_scenarios_and_unavailable_assets_remain_source_facts(tmp_path):
    from test_svj_recipe import fixture as svj_fixture,task
    doc=svj_fixture(tmp_path,missing=True);source=task(tmp_path,doc)
    projection=correspondence.project({'mode':'svj-recipe','task':source,'goal_binding':doc['goal_binding'],'max_seconds':60},tmp_path,InputCapture())
    assert projection['facts']['document']['templates']==doc['templates'] and len(doc['templates'])==4
    assert projection['facts']['points'][0]['generation'] is None and projection['facts']['energy_tev']=='13'
    assert len(projection['facts']['document']['response_scenarios'])==len(projection['facts']['document']['background_scenarios'])==2


def test_supplied_mssm_and_llp_cells_remain_source_facts(tmp_path):
    from test_mssm_observable_map import large_plane,llp_template,emit
    from ravel.physics import mssm_llp_handoff
    source,doc=large_plane(tmp_path/'source')
    projection=correspondence.project({'mode':'mssm-observable-map','task':source},tmp_path/'source',InputCapture())
    assert len(projection['facts']['points'])==len(doc['points']) and projection['facts']['axes']==doc['axes']
    template,q=llp_template(tmp_path/'source',doc);q['construction_limits']={'max_points':128,'max_cells':512};emit(Path(template['path']),q)
    prepared=mssm_llp_handoff.prepare(source,tmp_path/'source',template['path'],tmp_path/'llp-prepared')
    llp=correspondence.project({'mode':'llp-plane-recipe','task':prepared['ordinary_task'],'goal_binding':q['goal_binding'],'max_seconds':60},tmp_path/'llp-prepared',InputCapture())
    assert len(llp['facts']['points'])==len(llp['facts']['cells'])==len(doc['points'])
    assert llp['facts']['document']['construction_limits']==q['construction_limits']
    assert all(component['cohort'] is None for point in llp['facts']['points'] for component in point['components'])
    assert 'physical_prediction_or_inference' in llp['unavailable_typed_fields']


def test_actual_blueprint_portfolio_checks_whole_recipe_before_existing_admission(tmp_path,monkeypatch):
    from test_research_blueprint import case
    from test_research_cycle import experiment
    from ravel.workflow import research_blueprint as blueprint
    root,_,_,request,_=case(tmp_path/'cycle-source',monkeypatch,concrete_baseline=True)
    context_pin=request['context'];context=json.loads(Path(context_pin['path']).read_text())
    path,recipe=generation_recipe(tmp_path/'resonance-source')
    stage=next(s for s in recipe['stages'] if s['id']=='generate_H0')
    row=experiment(tmp_path/'cycle-source','source-generation',grouped=False,parent=None,premise_ids=['pairing'])
    row.update(study={**stage['study'],'size':Path(stage['study']['path']).stat().st_size},acceptance_scope='diagnostic',cost={**row['cost'],'wall_seconds':60},
        predictions={'independent':'passed'},observable={'pointer':'/status','outcomes':{'passed':'passed','failed':'failed'}})
    manifest=write(tmp_path/'correspondence.json',{'schema_version':1,'recipe':pin(path),'stages':[{'experiment':row['id'],'stage':stage['id']}]})
    proposal={'kind':'research_portfolio','parent_experiment':None,'context_sha256':context_pin['sha256'],
        'reason':'Compile the exact whole source-bound generation study; all other recipe cells remain in the source denominator.',
        'experiments':[row],'stage_correspondence':manifest}
    presented=[context_pin,manifest,*rs.input_pins(path),*blueprint.inputs(request,base_dir=tmp_path/'cycle-source')]
    checked=rs.research_portfolio(proposal,context,proposal_base=tmp_path,context_pin=context_pin,presented_pins=presented)
    assert checked==proposal and len(checked['experiments'])==1
    assert not (root/'experiments/source-generation').exists()
    bad=deepcopy(proposal);bad['experiments'][0]['study']=recipe['stages'][0]['study']
    if bad['experiments'][0]['study']==row['study']:bad['experiments'][0]['study']=recipe['stages'][1]['study']
    with pytest.raises(ValueError,match='exact operative'):rs.research_portfolio(bad,context,proposal_base=tmp_path,context_pin=context_pin,presented_pins=presented)


def accepted_case(tmp_path,monkeypatch):
    path,recipe=generation_recipe(tmp_path/'source',scheme='mlm')
    stage=next(s for s in recipe['stages'] if s['id']=='generate_H0')
    # This closed export is selected from the actual producer config, never a
    # guessed arbitrary work path. The test supplies accepted-format evidence;
    # review APIs are explicitly inert boundaries, not fabricated real votes.
    original_path=Path(stage['documents'][0]['source']['path'])
    cfg=json.loads(original_path.read_text());cfg['outputs']['hepmc_relative']='Events/run/sample.hepmc'
    stage['documents'][0]['source']=write(original_path,cfg)
    mapped=json.loads(Path(stage['target_mapping']['path']).read_text())
    mapped['projected_target']=correspondence.project(json.loads(Path(stage['study']['path']).read_text()),
        Path(stage['study']['path']).parent,InputCapture())
    stage['target_mapping']=write(Path(stage['target_mapping']['path']),mapped)
    stage['exports']['events']={'kind':'generated_member','path':'Events/run/sample.hepmc','format':'HepMC2'}
    write(path,recipe)
    prepared=rs.prepare_stage(path,stage['id'],{},tmp_path/'prepared')
    spec=json.loads(Path(prepared['specification']['path']).read_text())
    rd=tmp_path/'retained-run';science.plan(rd,prepared['specification']['path'])
    output=rd/'outputs/attempt-1';output.mkdir(parents=True)
    process,commitment,request,result,census=producer(rd/'work')
    materialized=Path(spec['task']['config']);actual=json.loads(materialized.read_text())
    request.update(config=actual,config_sha256=pin(materialized)['sha256'])
    result.update(intended=actual,shower_population={'returned_events':1,'weight_names':['nominal'],'format':'HepMC2','complete_framing':True,
        'raw_sha256':pin(process/'Events/run/sample.hepmc')['sha256']})
    result['generated_member_commitment']=commitment
    delivered={**result,'native_execution':{'explicit_inert_returned_format':True}}
    for name,value in [('native-input.json',request),('model-events-native.json',result),
        ('generated-member-commitment.json',commitment),('generated-artifact-census.json',census),
        ('model-events.json',delivered),('result.json',delivered)]:write(output/name,value)
    monkeypatch.setattr(science,'verify_plan',lambda *a,**k:None)
    monkeypatch.setattr(science,'execution_spec',lambda root:json.loads((Path(root)/science.SPEC).read_text()))
    monkeypatch.setattr(science,'packet',lambda *a,**k:{'errors':[],'execution':{'status':'succeeded'}})
    monkeypatch.setattr(science,'_selected',lambda *a,**k:({'outputs':['outputs/attempt-1']},None,None))
    monkeypatch.setattr(rs.physics_review,'status',lambda *a,**k:{'state':'accepted','claim_scope':'diagnostic','live_errors':[]})
    monkeypatch.setattr(rs.physics_review,'snapshot',lambda *a,**k:{'explicit_inert_review_boundary':True})
    monkeypatch.setattr(rs.physics_review,'validate_snapshot',lambda *a,**k:[])
    return path,recipe,stage,rd,process,output


@pytest.mark.parametrize('fault',[None,'modified_original_study','new_missing_recipe','old_missing_commitment'])
def test_retained_original_study_requires_exact_source_and_prospective_member_commitment(tmp_path,monkeypatch,fault):
    from ravel.workflow import retained_science_review
    path,recipe,stage,rd,process,output=accepted_case(tmp_path,monkeypatch)
    recorded=deepcopy(science.execution_spec(rd));recorded.pop('resonance_handoff')
    study=write(tmp_path/'original-retained-science.json',recorded)
    stage.update(study=study,retained_producer=True)
    stage['documents'][0]['source']=pin(Path(recorded['task']['config']))
    mapping=json.loads(Path(stage['target_mapping']['path']).read_text())
    mapping.update(original_study=study,projected_target=correspondence.project(recorded,tmp_path,InputCapture()))
    stage['target_mapping']=write(Path(stage['target_mapping']['path']),mapping);write(path,recipe)
    # The existing retained API is the explicit original-policy review boundary
    # in this synthetic control. We do not submit votes or refresh an old plan.
    monkeypatch.setattr(retained_science_review,'observe',lambda *a,**k:{'mode':'model-events','explicit_inert_original_policy':True})
    monkeypatch.setattr(science,'execution_spec',lambda *a,**k:recorded)
    entry=rs._load(path)[5][stage['id']]
    if fault=='modified_original_study':
        changed=deepcopy(recorded);changed['assumptions'].append('A different, superficially matching original study')
        new_pin=write(tmp_path/'modified-original.json',changed)
        entry=({**entry[0],'study':new_pin},Path(new_pin['path']),changed,entry[3])
    elif fault=='new_missing_recipe':entry=({**entry[0],'retained_producer':False},*entry[1:])
    elif fault=='old_missing_commitment':(output/'generated-member-commitment.json').unlink()
    capture=InputCapture()
    if fault is None:
        observed=rs._accepted(entry,rd,capture,pin(path));assert observed[6] is True
        assert observed[2]['events']==pin(process/'Events/run/sample.hepmc')
        rs._finish_accepted([observed],capture)
    else:
        with pytest.raises((ValueError,OSError)):rs._accepted(entry,rd,capture,pin(path))


def test_normalized_source_population_is_projected_without_renaming(tmp_path):
    from test_mssm_observable_map import fixture as spectrum_fixture, emit, save
    from ravel.physics import population_inputs, mssm_observable_map
    task, document=spectrum_fixture(tmp_path)
    source={'rows':[{'name':p['id'],'values':{'x':p['coordinate'][0],'y':p['coordinate'][1]}} for p in document['points']]}
    normalized=population_inputs.normalize(source,{'records':['rows'],'identity':['name'],
        'coordinates':[['values','x'],['values','y']],'relations':[]})
    document['population']={'kind':'source-listed','source':emit(tmp_path/'normalized.json',normalized),'layout':'point-list-v1'}
    save(task,document);result=mssm_observable_map.compile_map(task,tmp_path)
    projection=correspondence.project({'mode':'mssm-observable-map','task':task},tmp_path,InputCapture())
    assert len(projection['facts']['points'])==len(source['rows'])
    assert projection['facts']['document']['population']['layout']=='point-list-v1'
    assert [row['id'] for row in projection['facts']['points']]==[row['id'] for row in result['points']]


def test_added_unselected_member_during_initial_complete_capture_refuses(tmp_path,monkeypatch):
    process,_,_,_,_=producer(tmp_path);original=custody._file;done=[]
    def during(path):
        row=original(path)
        if not done:
            done.append(True);(process/'Events/added-after-census').write_text('late')
        return row
    monkeypatch.setattr(custody,'_file',during)
    with pytest.raises(ValueError,match='membership'):custody.snapshot(process)


@pytest.mark.parametrize('value',[1.,2.])
def test_literal_coupling_binding_compares_source_component_without_invented_convention(tmp_path,value):
    path,recipe=generation_recipe(tmp_path/'source')
    h=recipe['hypotheses'][0];stage=next(s for s in recipe['stages'] if s['id']=='generate_'+h['id'])
    study=json.loads(Path(stage['study']['path']).read_text());cp=Path(study['task']['config'])
    source=json.loads(cp.read_text());parameter=Path(source['cards']['parameter']['path'])
    parameter.write_text(parameter.read_text()+'BLOCK YUKAWA\n 6 '+str(value)+'\n')
    source['cards']['parameter']=pin(parameter);write(cp,source)
    stage['documents'][0]['source']=pin(cp)
    projection=correspondence.project(study,Path(stage['study']['path']).parent,InputCapture())
    bindings=[{'field':f,'address':a} for f,a in [('energy_tev',None),('model_sha256',None),
        ('mass_gev','MASS/6'),('width_gev','DECAY/6'),('coupling/yt/real','YUKAWA/6')]]
    if value==1.:
        checked=correspondence.compare(projection,h,None,bindings)
        assert 'coupling/yt/real' in checked['checked_fields']
        assert 'coupling_conventions' in checked['source_premises'] and not checked['physics_validated']
    else:
        with pytest.raises(ValueError,match='coupling'):correspondence.compare(projection,h,None,bindings)


def test_recorded_process_must_be_canonical_absolute(tmp_path):
    process,commitment,request,result,census=producer(tmp_path)
    with pytest.raises(ValueError,match='canonical'):custody.snapshot('process')
    with pytest.raises(ValueError,match='canonical'):custody.snapshot(process/'..'/'process')


@pytest.mark.parametrize('fault',[None,'added_unselected','removed_unselected'])
def test_actual_native_worker_prospective_commitment_and_late_publication_refusal(tmp_path,monkeypatch,fault):
    from ravel.physics import model_events as m,model_event_process
    from test_model_events import lhe,hepmc
    c=config(tmp_path/'inputs','mlm',variations=True,decay=True)
    out=tmp_path/'out';out.mkdir();process=tmp_path/'PROC'
    request={'config':c,'madgraph':c['runtime']['madgraph_tree']['root'],'model':c['model_tree']['root'],
        'process':str(process),'python':c['runtime']['python']['path'],
        'card_paths':{n:p['path'] for n,p in c['cards'].items() if p},'config_sha256':'a'*64,
        'process_observer_sha256':pin(Path(model_event_process.__file__))['sha256'],
        # Production requests resolve card pins against the configuration's directory.
        'source_base':str(tmp_path/'inputs')}
    # The production request names the digests of the two delivery helpers the worker copies.
    from ravel.validation import science_shower_guard, lhe_check
    request['delivery_helper_sha256'] = {str(Path(module.__file__).resolve()): pin(Path(module.__file__))['sha256']
                                        for module in (science_shower_guard, lhe_check)}
    rp=tmp_path/'request.json';write(rp,request)
    # Explicit inert native process-identity boundary. The actual generation
    # worker, card checks, full LHE/shower parsers and custody body below run.
    monkeypatch.setattr(model_event_process,'verify',lambda *a,**k:{'explicit_inert_process_identity':True})
    monkeypatch.setattr(m,'observe_exported_process',lambda *a,**k:{'matched':True,'commands':[]})
    def inert(argv,cwd,out,journal,label):
        if label=='build':
            (process/'Cards').mkdir(parents=True)
            (process/'Cards/proc_card_mg5.dat').write_text((out/'build.mg5').read_text())
            (out/'generation-process-definitions.jsonl').write_text('{}\n')
        else:
            source=process/c['outputs']['lhe_relative'];source.parent.mkdir(parents=True);source.write_text(lhe())
            (process/c['outputs']['hepmc_relative']).write_text(hepmc())
            (process/'Events/unselected.txt').write_text('Complete unselected native member')
        (out/(label+'-stdout.log')).write_text('Inert protocol; no native command')
        (out/(label+'-stderr.log')).write_text('')
        return {'phase':label,'command':argv,'returncode':0}
    monkeypatch.setattr(m,'_command',inert)
    original=m.bridge._write
    def ending(path,value):
        original(path,value)
        if Path(path).name=='model-events-native.json':
            if fault=='added_unselected':(process/'Events/late-unselected').write_text('late')
            elif fault=='removed_unselected':(process/'Events/unselected.txt').unlink()
    monkeypatch.setattr(m.bridge,'_write',ending)
    if fault is None:
        result=m.native_worker(rp,out)
        assert result['population']['generated_events']==3 and result['shower_population']['returned_events']==3
        commitment=json.loads((out/'generated-member-commitment.json').read_text())
        assert commitment==result['generated_member_commitment']
        assert str(process/'Events/unselected.txt') in {row['path'] for row in commitment['files']}
        custody.verify(commitment,process)
    else:
        with pytest.raises(ValueError):m.native_worker(rp,out)
        assert (out/'model-events-native.json').is_file() # retained failed candidate, never success authority
