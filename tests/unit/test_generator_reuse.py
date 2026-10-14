"""Synthetic inert software controls; no MG/UFO/compiler/engine execution.

Native command and ordinary-success stand-ins are explicitly named; they do not
establish a successful physical run or qualify the reused static libraries.
"""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import pytest
from ravel.physics import generator_reuse as r, model_events as m, model_event_process as observer


def fixtures():
    path=Path(__file__).with_name('test_model_events.py')
    spec=importlib.util.spec_from_file_location('generator_reuse_inert_fixtures',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def options():return {'candidate':None,'max_files':2000,'max_bytes':8*1024**2,'max_member_bytes':1024**2}


def export(tmp_path):
    process=tmp_path/'process';process.mkdir()
    for name,raw in {'Cards/proc_card_mg5.dat':b'import model /old/model-full\ngenerate e+ e- > t t~\n',
        'Cards/run_card.dat':b'3 = nevents\n19 = iseed\n','Cards/param_card.dat':b'BLOCK MASS\n 6 172.5\n',
        'Source/model.f':b'synthetic source\n','Source/include.inc':b'1\n','SubProcesses/subproc.mg':b'P1\n',
        'Cards/me5_configuration.txt':b'mg5_path = /old/mg\n'}.items():
        p=process/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    (process/'Events').mkdir();(process/'HTML').mkdir();(process/'lib').mkdir();(process/'bin').mkdir()
    (process/'bin/madevent').write_bytes(b'inert non-executable script');(process/'bin/madevent').chmod(0o755)
    (process/'Source/local.inc').symlink_to('include.inc')
    (process/'Source/future.inc').symlink_to('new.inc')
    roots={'process':str(process),'madgraph':'/old/mg','model':'/old/model'}
    record=r.capture_export(process,tmp_path/'capsule',options(),roots)
    return process,record


def test_prelaunch_export_is_immutable_and_fresh_materialization_has_exact_modes_links(tmp_path):
    process,record=export(tmp_path);fresh=tmp_path/'fresh'
    roots={'process':str(fresh),'madgraph':'/new/mg','model':'/new/model'}
    result=r.materialize(record,fresh,roots)
    assert result['adaptive_state_reused'] is False
    assert (fresh/'bin/madevent').stat().st_mode&0o777==0o755
    assert (fresh/'Source/local.inc').is_symlink() and (fresh/'Source/local.inc').read_bytes()==b'1\n'
    assert (fresh/'Source/future.inc').is_symlink() and not (fresh/'Source/future.inc').exists()
    assert (fresh/'Cards/me5_configuration.txt').read_bytes()==b'mg5_path = /new/mg\n'
    assert not list((fresh/'Events').iterdir())
    (process/'Source/model.f').write_bytes(b'old mutable process changed after capture')
    assert r.verify_tree(record)==record


@pytest.mark.parametrize('defect',['bytes','extra','directory','link','missing'])
def test_capsule_mutation_is_not_reused(tmp_path,defect):
    _,record=export(tmp_path);root=Path(record['root'])
    p=root/'tree/Source/model.f'
    if defect=='bytes':p.write_bytes(b'changed')
    elif defect=='extra':(root/'extra').write_bytes(b'unknown')
    elif defect=='directory':(root/'unrecorded-empty').mkdir()
    elif defect=='link':p.unlink();p.symlink_to(root/'export.json')
    else:p.unlink()
    with pytest.raises((ValueError,OSError)):r.materialize(record,tmp_path/'fresh',{'process':str(tmp_path/'fresh'),'madgraph':'/new/mg','model':'/new/model'})
    assert not (tmp_path/'fresh').exists()


@pytest.mark.parametrize('name',['Events/ravel/events.lhe','Events/random-state.pkl'])
def test_arbitrary_completed_or_failed_event_tree_is_not_export_input(tmp_path,name):
    process,record=export(tmp_path);p=process/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'never reuse')
    with pytest.raises(ValueError,match='event state'):r.capture_export(process,tmp_path/'another',options(),record['roots'])


def test_static_source_overlay_never_contains_grids_rng_cards_or_events(tmp_path):
    process,record=export(tmp_path)
    for name in ('Source/model.o','lib/libmodel.a','SubProcesses/P1/madevent','SubProcesses/P1/G1/grid.dat','SubProcesses/randinit','Events/ravel/events.lhe','Cards/changed.dat'):
        p=process/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(name.encode())
    static=r.capture_static(process,tmp_path/'static',record,'b'*64,{'source_sha256':'a'*64})
    assert [x['relative'] for x in static['rows']]==['Source/model.o','lib/libmodel.a']
    fresh=tmp_path/'fresh';r.materialize(record,fresh,{'process':str(fresh),'madgraph':'/new/mg','model':'/new/model'})
    # A static overlay is NOT hidden in an export-only snapshot.
    assert not (fresh/'Source/model.o').exists()
    assert r.apply_static(static,fresh)==2
    assert (fresh/'Source/model.o').read_bytes()==b'Source/model.o'
    assert not (fresh/'SubProcesses/randinit').exists() and not (fresh/'SubProcesses/P1/G1').exists()
    assert (fresh/'Cards/run_card.dat').read_bytes()==b'3 = nevents\n19 = iseed\n'


@pytest.mark.parametrize('defect',['process','order','model','generator','compiler','library'])
def test_full_export_identity_refuses_structural_runtime_changes(tmp_path,defect):
    f=fixtures();c=f.config(tmp_path/'input');t=f.texts(c);original=r.compatibility(c,tmp_path,t)
    if defect=='process':t['process']=t['process'].replace('t t~','b b~')
    elif defect=='order':
        c['generation']['order']='NLO';t['process']=t['process'].replace('t t~','t t~ [QCD]')
    else:
        tree=c['model_tree'] if defect=='model' else c['runtime']['madgraph_tree'] if defect=='generator' else c['runtime']['dependencies'][0]['tree']
        name='vertices.py' if defect=='model' else 'VERSION' if defect=='generator' else 'fc' if defect=='compiler' else 'cxx'
        path=Path(tree['root'])/name;path.write_text(path.read_text()+'\nchanged\n')
        manifest=Path(tree['manifest']['path']);manifest.write_text(json.dumps(m.bridge.source_tree(Path(tree['root'])))+'\n');tree['manifest']['sha256']=m.bridge._hash(manifest)
        if defect=='compiler':
            support=Path(c['runtime']['python_manifest']['path']);doc=json.loads(support.read_text());doc['files'][0]['sha256']=m.bridge._hash(path)
            support.write_text(json.dumps(doc)+'\n');c['runtime']['python_manifest']['sha256']=m.bridge._hash(support)
    changed=r.compatibility(c,tmp_path,t)
    assert original['export_sha256']!=changed['export_sha256']


def test_fresh_seed_exposure_only_preserve_compatibility_but_physical_card_change_drops_static(tmp_path):
    f=fixtures();c=f.config(tmp_path/'input');t=f.texts(c);original=r.compatibility(c,tmp_path,t)
    c['generation'].update(seed=27,events=7);t['run']=t['run'].replace('19 = iseed','27 = iseed').replace('3 = nevents','7 = nevents')
    Path(c['cards']['run']['path']).write_text(t['run']);c['cards']['run']['sha256']=hashlib.sha256(t['run'].encode()).hexdigest()
    changed=r.compatibility(c,tmp_path,t)
    assert changed==original
    t['parameter']=t['parameter'].replace('172.5','180');Path(c['cards']['parameter']['path']).write_text(t['parameter'])
    c['cards']['parameter']['sha256']=hashlib.sha256(t['parameter'].encode()).hexdigest()
    physical=r.compatibility(c,tmp_path,t)
    assert physical['export_sha256']==original['export_sha256'] and physical['static_sha256']!=original['static_sha256']


@pytest.mark.parametrize('defect',['missing','failed','unapproved'])
def test_unavailable_original_authority_is_explicit_miss_and_ordinary_fresh_plan_remains_available(tmp_path,defect):
    f=fixtures();c=f.config(tmp_path/'input');c['generator_reuse']=options()
    c['generator_reuse']['candidate']={'rundir':str(tmp_path/'old'),'capsule_sha256':'f'*64}
    if defect!='missing':(tmp_path/'old').mkdir();(tmp_path/'old/execution.json').write_text(json.dumps({'stages':{'science':{'status':'failed' if defect=='failed' else 'succeeded'}}}))
    selection=r.probe(c,tmp_path,f.texts(c))
    assert selection['state']=='miss' and selection['inputs']==[]
    assert m.validate_config(c) is c
    cp=f.write(tmp_path/'config.json',c)
    from ravel.workflow import science
    request={'schema_version':2,'mode':'model-events','source':'synthetic complete source','task':{'config':cp['path']},
        'review_policy':f.write(tmp_path/'policy.json',f.policy()),'max_seconds':90,'redo_budget':0}
    # The existing public preparer supplies the real ordinary schema rather than this illustrative raw mapping.
    from ravel.workflow import model_event_plan
    req={'schema_version':1,'config':cp,'review_policy':request['review_policy'],'supervisor_seconds':90,'goal_binding':None}
    model_event_plan.prepare(req,base_dir=tmp_path,output_dir=tmp_path/'prepared')
    science.plan(tmp_path/'new-run',tmp_path/'prepared/science.json')
    assert (tmp_path/'new-run/inputs/science-plan.json').is_file()
    assert not (tmp_path/'new-run/inputs/science-approval.json').exists()


def test_intended_emission_change_refuses_before_first_baseline(tmp_path,monkeypatch):
    real=Path.write_bytes
    def mutate(path,raw):
        value=real(path,raw)
        if path.name=='record.json':real(path,b'forged')
        return value
    monkeypatch.setattr(Path,'write_bytes',mutate)
    with pytest.raises(ValueError,match='intended'):r.write_document(tmp_path/'record.json',{'physics_validated':False})
    assert (tmp_path/'record.json').read_bytes()==b'forged'


def test_last_read_namespace_birth_in_capsule_refuses(tmp_path,monkeypatch):
    _,record=export(tmp_path);real=r.regular_bytes;root=Path(record['root']);last=record['rows'][-1]
    files=[x for x in record['rows'] if x['type']=='file'];target=Path(files[-1]['blob']['path']);armed=[True]
    def read(path,maximum):
        raw=real(path,maximum)
        if Path(path)==target and armed[0]:armed[0]=False;(root/'late').write_bytes(b'new')
        return raw
    monkeypatch.setattr(r,'regular_bytes',read)
    with pytest.raises(ValueError,match='late'):r.verify_tree(record)


def test_public_prepare_captures_reuse_contract_and_original_full_event_budget(tmp_path):
    f=fixtures();req,c=f.setup_request(tmp_path);c['generator_reuse']=options();req['config']=f.write(tmp_path/'config.json',c)
    from ravel.workflow import model_event_plan,science
    model_event_plan.prepare(req,base_dir=tmp_path,output_dir=tmp_path/'prepared')
    science.plan(tmp_path/'run',tmp_path/'prepared/science.json')
    plan=json.loads((tmp_path/'run/inputs/science-plan.json').read_text())
    assert plan['mode']=='model-events' and json.loads((tmp_path/'prepared/science.json').read_text())['max_seconds']==90
    assert any(x.endswith('generator_reuse.py') for x in plan['stages'][0]['inputs'])
    assert json.loads(Path(json.loads((tmp_path/'prepared/science.json').read_text())['task']['config']).read_text())['generation']['events']==3


def test_native_static_api_is_source_signature_bound_and_never_bypasses_engine_compile(tmp_path):
    path=tmp_path/'madgraph/interface/madevent_interface.py';path.parent.mkdir(parents=True)
    path.write_text('class MadEventCmd:\n def configure_directory(self,html_opening=True):\n  return None\n')
    original=r.build_api(tmp_path);path.write_text(path.read_text().replace('return None','return 42'))
    assert r.build_api(tmp_path)!=original
    path.write_text('class MadEventCmd:\n def configure_directory(self,unknown):\n  return None\n')
    with pytest.raises(ValueError,match='signature'):r.build_api(tmp_path)
    source=Path(m.__file__).with_name('model_event_phases.py').read_text()
    fn=ast.parse(source)
    assert 'result = original(*arguments, **keywords)' in ast.unparse(fn)


@pytest.mark.parametrize('defect',['bytes','new-member','grid-injection'])
def test_static_capsule_changes_refuse_and_never_widen_overlay(tmp_path,defect):
    process,record=export(tmp_path);(process/'Source/model.o').write_bytes(b'compiled inert stand-in')
    static=r.capture_static(process,tmp_path/'static',record,'c'*64,{'source_sha256':'a'*64})
    if defect=='bytes':Path(static['rows'][0]['blob']['path']).write_bytes(b'changed')
    elif defect=='new-member':(Path(static['root'])/'new').write_bytes(b'unknown')
    else:
        static['rows'][0]['relative']='SubProcesses/P1/G1/grid.dat'
    with pytest.raises((ValueError,OSError)):r.verify_static(static)


def test_external_source_directory_link_is_complete_and_remaps_to_fresh_source(tmp_path):
    process,unused=export(tmp_path);old=tmp_path/'oldmg';new=tmp_path/'newmg'
    for root in (old,new):
        (root/'CutTools').mkdir(parents=True);(root/'CutTools/library.a').write_bytes(b'source-bound inert library')
    (process/'Source/CutTools').symlink_to(old/'CutTools',target_is_directory=True)
    (process/'Cards/me5_configuration.txt').write_text('mg5_path = '+str(old)+'\n')
    roots={'process':str(process),'madgraph':str(old),'model':'/old/model'}
    record=r.capture_export(process,tmp_path/'with-link',options(),roots)
    fresh=tmp_path/'fresh';r.materialize(record,fresh,{'process':str(fresh),'madgraph':str(new),'model':'/new/model'})
    assert (fresh/'Source/CutTools/library.a').read_bytes()==b'source-bound inert library'
    (new/'CutTools/extra.a').write_bytes(b'not authenticated original source directory')
    with pytest.raises(ValueError,match='directory differs'):r.materialize(record,tmp_path/'next',{'process':str(tmp_path/'next'),'madgraph':str(new),'model':'/new/model'})


@pytest.mark.parametrize('ceiling',['files','bytes'])
def test_linked_source_work_is_charged_to_complete_not_per_link_ceiling(tmp_path,ceiling):
    process,prior=export(tmp_path);mg=tmp_path/'mg'
    for name in ('A','B'):
        (mg/name).mkdir(parents=True);(mg/name/'library.a').write_bytes(b'x'*100)
        (process/'Source'/name).symlink_to(mg/name,target_is_directory=True)
    bounds=options();population=len(r._structure(process,2000)[1])
    if ceiling=='files':bounds['max_files']=population+1
    else:bounds['max_bytes']=prior['total_bytes']+199;bounds['max_member_bytes']=bounds['max_bytes']
    with pytest.raises(ValueError,match='(ceiling|declared bytes)'):
        r.capture_export(process,tmp_path/'bounded',bounds,{'process':str(process),'madgraph':str(mg),'model':'/old/model'})
    assert not (tmp_path/'bounded/export.json').exists()


def test_capture_helper_ending_is_bound_to_intended_generated_bytes(tmp_path):
    process,exported=export(tmp_path);helper=r.write_bytes(tmp_path/'native-generator-reuse.py',b'original authenticated helper')
    identity={'source':{'path':'synthetic-journal','sha256':'b'*64}}
    compatibility={'export':{'synthetic':True},'export_sha256':r.digest({'synthetic':True}),'static_sha256':'a'*64}
    info=r.publish(tmp_path,exported,compatibility,{'state':'fresh','process_identity':identity,'capture_helper':helper})
    result={'generator_reuse':info,'generation_process_identity':identity}
    assert r.ending(result,tmp_path)['physics_validated'] is False
    Path(helper['path']).write_bytes(b'changed capture helper')
    with pytest.raises(ValueError,match='capture helper changed'):r.ending(result,tmp_path)


def test_static_observer_forwards_exact_original_arguments_return_and_exception(tmp_path):
    # Extract only our pure wrapper; no native module import or configure invocation.
    from types import SimpleNamespace
    import functools
    source=ast.parse(Path(m.__file__).with_name('model_event_phases.py').read_text())
    fn=next(x for x in ast.walk(source) if isinstance(x,ast.FunctionDef) and x.name=='observe_static')
    fn=deepcopy(fn);fn.decorator_list=[];calls=[];result=object();failure=ValueError('released original failure')
    obj=SimpleNamespace(me_dir=str(tmp_path/'process'));destination=tmp_path/'static';destination.mkdir()
    def original(*args,**kwargs):
        calls.append((args,kwargs))
        if kwargs.get('raise_original'):raise failure
        return result
    namespace={'Path':Path,'original':original,'capture':{'process':obj.me_dir,'destination':str(destination)}}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<inert-static-capture-wrapper>','exec'),namespace)
    observe=namespace['observe_static']
    assert observe(obj,False,html_opening=False) is result
    assert calls==[((obj,False),{'html_opening':False})]
    with pytest.raises(ValueError) as raised:observe(obj,raise_original=True)
    assert raised.value is failure and len(calls)==2
