"""Inert software controls for a source-specific SAME-run checkpoint.

These fixtures supply explicit synthetic native classes/process/command/origin
boundaries. They never import MG, compile, generate, qualify a grid or establish
an original successful physical event sample. Root owns later native controls.
"""
import ast
from collections import defaultdict
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
from types import SimpleNamespace

import pytest
from ravel.physics import native_integration_checkpoint as n, generator_reuse as s
from ravel.physics import model_event_phases as phases, model_events as m, model_event_seed as seeds


class AllResults(dict):
    def def_current(self, run, tag):
        self.lastrun = run
        self.current = self[run][self[run].tags.index(tag)]


class RunResults(list): pass
class OneTagResults(dict): pass
class RunStatistics(dict): pass
class Banner(dict): pass
class RunCardLO(dict): pass

CLASSES = {module+'.'+name: globals()[name] for module,names in n.NATIVE_CLASSES.items() for name in names}


CHANNEL_STATE = n.channel_state


def policy():
    return {'candidate':None,'max_files':1000,'max_bytes':8*1024**2,'max_member_bytes':1024**2}


def state(process):
    tag=OneTagResults(run_name='ravel',tag='tag_1',cross=2.,error=.1,prev_cross=1.,
                      run_statistics={('P1','1'):RunStatistics(stable_points=13,unstable_points=0,max_precision=1.e99)})
    run=RunResults([OneTagResults(run_name='ravel',tag='old',cross=1.),tag]);run.tags=['old','tag_1']
    results=AllResults(ravel=run);results.current=tag;results.lastrun='ravel';results.path=str(process);results.order=['ravel']
    card=RunCardLO(iseed=0,gridpack=False,nevents=3,python_seed=-2);card.parameter_types={'iseed':int};card.user_set={'iseed'};card.includepath=defaultdict(list,{'run_card.inc':['iseed']})
    return {'results':results,'run_name':'ravel','run_tag':'tag_1','run_card':card,'banner':Banner(mgruncard='source bytes'),
        'random':22,'random_orig':19,'nb_refine':0,'opts':{'accuracy':.1,'points':1000},'history':['launch','survey'],
        'Gdirs':None,'_options':{},'to_store':[],'total_jobs':1}


def build_case(tmp_path,monkeypatch,output=None,*,ceiling=100,checkpoint_policy=None):
    tmp_path.mkdir(parents=True,exist_ok=True)
    process=tmp_path/'process';mg=tmp_path/'mg';model=tmp_path/'model'
    mg.mkdir();model.mkdir();process.mkdir()
    (model/'vertices.py').write_bytes(b'inert source-only model')
    manifest=tmp_path/'model-manifest.json';manifest.write_bytes(s.encoded(m.bridge.source_tree(model)))
    for relative,raw in {'RunWeb':str(os.getpid()).encode(),'HTML/results.pkl':b'not live: deliberately stale',
        'Cards/run_card.dat':b'0 = iseed\n','Cards/me5_configuration.txt':('mg5_path = '+str(mg)+'\n').encode(),
        'SubProcesses/subproc.mg':b'P1\n','SubProcesses/randinit':b'r=22\n','SubProcesses/P1/symfact.dat':b'1 1\n',
        'SubProcesses/P1/G1/results.dat':b'2 .1 .1 13 3 4 3 1 0 2 1 0 0\n',
        'SubProcesses/P1/G1/ftn25':b'synthetic complete proposal','SubProcesses/P1/G1/events.lhe':b'',
        'SubProcesses/P1/G1/log.txt':b'raw diagnostics retained'}.items():
        p=process/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    (process/'SubProcesses/P1/G1/local-grid').symlink_to('ftn25')
    destination=tmp_path/'capsule' if output is None else output/'integration-checkpoint'
    stdout=tmp_path/'generate.log' if output is None else output/'generate-decay-shower-reweight-stdout.log'
    stdout.parent.mkdir(parents=True,exist_ok=True);stdout.write_bytes(b'actual-fixture native prefix\nUsing random number seed offset = 19\n')
    config={'source':'synthetic','max_seconds':ceiling,'generation':{'seed':19,'events':3},'runtime':{'options':{}},'model_tree':{'root':str(model),'manifest':{'path':str(manifest),'sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}},'cards':{'run':{'path':str(process/'Cards/run_card.dat'),'sha256':'a'*64}}}
    config_path=tmp_path/'source-config.json';config_path.write_bytes(s.encoded(config))
    request={'policy':policy() if checkpoint_policy is None else deepcopy(checkpoint_policy),'config':config,'original':{'rundir':str(tmp_path/'old'),'attempt':1,'source_base':str(tmp_path),
             'config_sha256':hashlib.sha256(config_path.read_bytes()).hexdigest(),'goal_binding':{'synthetic':True}},'process':str(process),'madgraph':str(mg),
             'roots':{'process':str(process),'madgraph':str(mg),'model':str(model)},'destination':str(destination),'stdout':str(stdout)}
    cmd=SimpleNamespace(**state(process),me_dir=str(process),param_card_iterator=[],force_run=False,cluster_mode=0,
                        options={'run_mode':0},proc_characteristics={'loop_induced':False})
    # Synthetic class/frame owner boundary; real ordinary launcher guard has
    # separate source-bound-frame controls below. No MG execution is claimed.
    monkeypatch.setattr(n,'native_owner',lambda command,root,support:support.regular_bytes(Path(command.me_dir)/'RunWeb',128))
    monkeypatch.setattr(n,'registry',lambda root,*args:CLASSES)
    monkeypatch.setattr(n,'source_inputs',lambda root,*args:[])
    # Authentic source hashes are modeled explicitly; this is not native source acceptance.
    for name in n.SOURCE_NAMES:
        p=mg/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(name.encode())
    monkeypatch.setattr(n,'process_table',lambda:[{'pid':os.getpid(),'parent':1,'group':os.getpgrp(),'state':'R'}])
    monkeypatch.setattr(n,'channel_state',lambda *args:[{'process':'P1','channels':['G1'],'zero_phase_space':False}])
    record=n.capture(cmd,request,s)
    return cmd,request,record


def test_live_codec_preserves_shared_current_statistics_prior_cross_and_types(tmp_path):
    original=state(tmp_path);graph=n.encode_graph(original,CLASSES);copy=n.decode_graph(graph,CLASSES)
    assert copy['results'].current is copy['results']['ravel'][1]
    assert copy['results'].current['prev_cross']==1. and copy['results'].current['run_statistics'][('P1','1')]['stable_points']==13
    assert copy['run_card'].parameter_types['iseed'] is int and copy['run_card'].user_set=={'iseed'}
    assert n.encode_graph(copy,CLASSES)==graph
    assert n.encode_graph([1],{})!=n.encode_graph((1,),{})
    assert n.encode_graph(1,{})!=n.encode_graph(True,{})


@pytest.mark.parametrize('bad',[object(),float('nan'),lambda:None])
def test_unknown_or_nonfinite_native_state_is_not_guessed(bad):
    with pytest.raises(ValueError):n.encode_graph(bad,CLASSES)


def test_capture_live_final_state_ignores_stale_database_and_preserves_empty_pool(tmp_path,monkeypatch):
    cmd,request,record=build_case(tmp_path,monkeypatch)
    live=n.decode_graph(record['state'],CLASSES)
    assert live['results'].current['run_statistics'][('P1','1')]['stable_points']==13
    database=next(x for x in record['tree']['rows'] if x['relative']=='HTML/results.pkl')
    assert s._blob_bytes(database,1024)==b'not live: deliberately stale'
    empty=next(x for x in record['tree']['rows'] if x['relative'].endswith('events.lhe'))
    assert s._blob_bytes(empty,1024)==b'' and record['physics_validated'] is False
    assert n.verify(record)==record


@pytest.mark.parametrize('defect',['bytes','member','directory','alias','missing','mode'])
def test_snapshot_changed_storage_is_never_a_new_baseline(tmp_path,monkeypatch,defect):
    _,_,record=build_case(tmp_path,monkeypatch);root=Path(record['tree']['root']);p=root/'tree/SubProcesses/P1/G1/ftn25'
    if defect=='bytes':p.write_bytes(b'changed')
    elif defect=='member':(root/'extra').write_bytes(b'new')
    elif defect=='directory':(root/'unlisted').mkdir()
    elif defect=='alias':p.unlink();p.symlink_to(root/'checkpoint.json')
    elif defect=='missing':p.unlink()
    else:
        # Storage modes are its authenticated structural observation during each read.
        real=s.regular_bytes;armed=[True]
        def read(path,maximum):
            raw=real(path,maximum)
            if Path(path)==p and armed[0]:armed[0]=False;p.chmod(0o600 if p.stat().st_mode&0o777!=0o600 else 0o644)
            return raw
        monkeypatch.setattr(s,'regular_bytes',read)
    with pytest.raises((ValueError,OSError)):n.materialize(record,tmp_path/'fresh',record['tree']['roots'])
    assert not (tmp_path/'fresh').exists()


def test_fresh_materialization_omits_only_owner_and_untrusted_pickle_relocates_link(tmp_path,monkeypatch):
    _,_,record=build_case(tmp_path,monkeypatch);fresh=tmp_path/'fresh';roots=dict(record['tree']['roots'],process=str(fresh))
    n.materialize(record,fresh,roots)
    assert not (fresh/'RunWeb').exists() and not (fresh/'HTML/results.pkl').exists()
    assert (fresh/'SubProcesses/P1/G1/local-grid').is_symlink()
    assert (fresh/'SubProcesses/P1/G1/local-grid').read_bytes()==b'synthetic complete proposal'
    assert (fresh/'SubProcesses/P1/G1/events.lhe').read_bytes()==b''
    assert (fresh/'SubProcesses/randinit').read_bytes()==b'r=22\n'
    assert s._blob_bytes(next(x for x in record['tree']['rows'] if x['relative']=='RunWeb'),128)==str(os.getpid()).encode()


@pytest.mark.parametrize('present',[False,True])
def test_fresh_setup_then_exact_tag_and_rng_restore_without_copied_timestamp(tmp_path,monkeypatch,present):
    old=random.getstate();had=hasattr(random,'mg_seedset');marker=getattr(random,'mg_seedset',None)
    try:
        if present:random.mg_seedset=-2
        elif hasattr(random,'mg_seedset'):del random.mg_seedset
        _,request,record=build_case(tmp_path,monkeypatch)
        fresh=tmp_path/'fresh';roots=dict(request['roots'],process=str(fresh));n.materialize(record,fresh,roots)
        (fresh/'RunWeb').write_text(str(os.getpid()));calls=[]
        cmd=SimpleNamespace(me_dir=str(fresh),force_run=False,configured=0)
        cmd.split_arg=lambda line:line.split();cmd.check_survey=lambda args:calls.append(('check',args))
        def setup():
            calls.append(('setup',None));cmd.configured=987;cmd.run_card=n.decode_graph(record['state'],CLASSES)['run_card']
            random.seed(42);random.mg_seedset=42
        cmd.configure_directory=setup
        contract=dict(request,record=record,process=str(fresh),roots=roots)
        assert n.restore_survey(cmd,'ravel',contract,s) is None
        assert calls==[('check',['ravel']),('setup',None)] and cmd.configured==987
        assert cmd.results.current is cmd.results['ravel'][1] and cmd.results['ravel'].tags==['old','tag_1']
        assert cmd.random==22 and cmd.random_orig==19 and cmd.nb_refine==0
        assert random.getstate()==n.decode_graph(record['python_random_state'],{})
        assert hasattr(random,'mg_seedset') is present
        if present:assert random.mg_seedset==-2
        with pytest.raises(ValueError,match='once'):n.restore_survey(cmd,'ravel',contract,s)
    finally:
        random.setstate(old)
        if had:random.mg_seedset=marker
        elif hasattr(random,'mg_seedset'):del random.mg_seedset


def test_setup_that_changes_committed_grid_refuses_before_native_tail(tmp_path,monkeypatch):
    _,request,record=build_case(tmp_path,monkeypatch);fresh=tmp_path/'fresh';roots=dict(request['roots'],process=str(fresh));n.materialize(record,fresh,roots)
    (fresh/'RunWeb').write_text(str(os.getpid()))
    cmd=SimpleNamespace(me_dir=str(fresh),force_run=False,configured=0,split_arg=lambda x:x.split(),check_survey=lambda x:None)
    def setup():
        cmd.configured=1;cmd.run_card=n.decode_graph(record['state'],CLASSES)['run_card'];(fresh/'SubProcesses/P1/G1/ftn25').write_bytes(b'changed by setup')
    cmd.configure_directory=setup
    with pytest.raises(ValueError,match='bytes changed'):n.restore_survey(cmd,'ravel',dict(request,record=record,process=str(fresh),roots=roots),s)
    assert not hasattr(cmd,'results')


@pytest.mark.parametrize('defect',['child','zombie','other_group_child'])
def test_capture_integration_children_must_be_quiescent(tmp_path,monkeypatch,defect):
    table=[{'pid':100,'parent':90,'group':90,'state':'R'},{'pid':90,'parent':1,'group':90,'state':'S'}]
    child={'pid':101,'parent':100,'group':91 if defect=='other_group_child' else 90,'state':'Z' if defect=='zombie' else 'S'}
    table.append(child)
    with pytest.raises(ValueError,match='descendants'):n.quiescent_children(table,100,90)


def test_source_phase_wrapper_forwards_return_once_then_commits_and_full_driver_remains(tmp_path):
    calls=[]
    def original(cmd,line):calls.append(('survey',line));return 7
    helper=SimpleNamespace(capture=lambda cmd,request,support:(calls.append(('capture',None)) or {'tree':{'root':str(tmp_path)}}))
    class Emit:
        next_id=0
        def __call__(self,row):calls.append(('row',row['state']))
    emit=Emit();row={'phase':'survey'};contract={'policy':policy()};stack=[]
    assert phases.wrap(original,row,emit,stack,(helper,s,contract))(object(),'ravel')==7
    assert [x[0] for x in calls].count('survey')==1
    assert calls[-1]==('row','completed') and stack==[]
    source=Path(phases.__file__).read_text()
    assert "runpy.run_path(sys.argv[0], run_name='__main__')" in source
    assert 'do_refine(' not in source and 'do_combine_events(' not in source


def test_failed_recorder_prevents_dependent_tail_and_preserves_native_exception():
    class Emit:
        next_id=0
        def __call__(self,row):pass
    def fail(*args):raise ValueError('recorder failed')
    helper=SimpleNamespace(capture=fail);calls=[]
    def original(*args):calls.append('original');return 1
    with pytest.raises(ValueError,match='recorder failed'):
        phases.wrap(original,{'phase':'survey'},Emit(),[],(helper,s,{'policy':policy()}))(object(),'ravel')
    assert calls==['original']
    error=RuntimeError('native original');calls.clear()
    def native(*args):calls.append('original');raise error
    with pytest.raises(RuntimeError) as caught:phases.wrap(native,{'phase':'survey'},Emit(),[])(object(),'ravel')
    assert caught.value is error and calls==['original']


@pytest.mark.parametrize('field',['max_files','max_bytes','max_member_bytes'])
def test_declared_operational_bound_refuses_partial_capture(tmp_path,monkeypatch,field):
    _,_,record=build_case(tmp_path,monkeypatch)
    changed=deepcopy(record);changed['tree']['options'][field]=1
    # A changed manifest is not an admitted re-budgeting of its original state.
    with pytest.raises((ValueError,OSError)):n.verify(changed)


def test_intended_checkpoint_manifest_change_refuses_before_capture_returns(tmp_path,monkeypatch):
    real=s.write_bytes
    def write(path,raw):
        result=real(path,raw)
        if Path(path).name=='checkpoint.json':
            changed=raw[:-1]+b' '
            assert changed!=raw and len(changed)==len(raw)
            Path(path).write_bytes(changed)
        return result
    monkeypatch.setattr(s,'write_bytes',write)
    with pytest.raises(ValueError,match='manifest changed'):build_case(tmp_path,monkeypatch)


def test_grown_checkpoint_manifest_refuses_at_exact_pre_read_size_bound(tmp_path,monkeypatch):
    real=s.write_bytes
    def write(path,raw):
        result=real(path,raw)
        if Path(path).name=='checkpoint.json':
            grown=raw+b' '
            assert grown!=raw and len(grown)==len(raw)+1
            Path(path).write_bytes(grown)
        return result
    monkeypatch.setattr(s,'write_bytes',write)
    with pytest.raises(ValueError,match='^bounded regular reuse member required$'):build_case(tmp_path,monkeypatch)


@pytest.mark.parametrize('defect',['seed','events','process','compiler','library','cards','model','order'])
def test_complete_same_run_compatibility_does_not_become_fresh_independent_sample(defect,tmp_path):
    original={'source':'first','max_seconds':60,'generation':{'seed':19,'events':3,'order':'LO'},'runtime':{'options':{'fortran_compiler':'fc'},'library':'lib1'},
              'cards':{'process':{'path':'proc.dat','sha256':'a'*64}},'model_tree':{'root':'model','manifest':{'path':'model.json','sha256':'b'*64}},'process':'pp>tt'}
    changed=deepcopy(original)
    if defect in ('seed','events','order'):changed['generation'][defect]='NLO' if defect=='order' else 4
    elif defect=='compiler':changed['runtime']['options']['fortran_compiler']='otherfc'
    elif defect=='library':changed['runtime']['library']='lib2'
    elif defect=='process':changed['process']='gg>4l'
    elif defect=='cards':changed['cards']['process']['sha256']='c'*64
    else:changed['model_tree']['manifest']['sha256']='c'*64
    assert n.compatibility(original,tmp_path)!=n.compatibility(changed,tmp_path)
    same=deepcopy(original);same['max_seconds']=20;same['source']='new continuation statement';same['integration_checkpoint']=policy()
    assert n.compatibility(original,tmp_path)==n.compatibility(same,tmp_path)


def load_fixture(name):
    path=Path(__file__).with_name(name);spec=importlib.util.spec_from_file_location('checkpoint_fixture_'+path.stem,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_real_public_plan_records_checkpoint_full_goal_and_exposure_without_effect(tmp_path,monkeypatch):
    f=load_fixture('test_model_events.py');request,c=f.setup_request(tmp_path)
    c['operative_seed_observation']={'schema_version':1,'mode':seeds.MODE};c['integration_checkpoint']=policy()
    request['config']=f.write(tmp_path/'checkpoint-config.json',c)
    # Explicit source-only inert engine boundary; no generator acceptance claimed.
    monkeypatch.setattr(n,'source_inputs',lambda root:[Path(root)/'VERSION'])
    monkeypatch.setattr(seeds,'source_inputs',lambda root:[Path(root)/'VERSION'])
    from ravel.workflow import model_event_plan,science,task_completion,route_prompt
    prompt='Generate the complete original three-event sample, preserving all weights.'
    req=task_completion.initial_requirements(prompt)
    req['assignments']=[{'id':'generation','purpose':prompt,'coverage':[{'obligation_id':'original-request','criteria':{'request':prompt}}]}]
    contract=route_prompt.route(prompt);contract['task_requirements']=req;pin=f.write(tmp_path/'original/task_contract.json',contract);pin['size']=Path(pin['path']).stat().st_size
    request['goal_binding']={'contract':pin,'assignment_id':'generation'}
    model_event_plan.prepare(request,base_dir=tmp_path,output_dir=tmp_path/'prepared')
    science.plan(tmp_path/'run',tmp_path/'prepared/science.json')
    plan=science.verify_plan(tmp_path/'run',approved=False)
    spec=json.loads((tmp_path/'prepared/science.json').read_text())
    assert plan['mode']=='model-events' and spec['goal_binding']==request['goal_binding']
    assert any(x.endswith('native_integration_checkpoint.py') for x in plan['stages'][0]['inputs'])
    assert json.loads(Path(spec['task']['config']).read_text())['generation']['events']==3
    assert not (tmp_path/'run/inputs/science-approval.json').exists() and not (tmp_path/'run/execution_attempt.json').exists()


def test_actual_worker_both_calls_and_existing_authority_tail_are_bound_by_source():
    tree=ast.parse(Path(m.__file__).read_text());worker=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='native_worker')
    calls=[x for x in ast.walk(worker) if isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute) and isinstance(x.func.value,ast.Name) and x.func.value.id=='model_event_seed' and x.func.attr=='observe']
    assert len(calls)==2 and all(any(k.arg is None and 'continuation_seed' in ast.unparse(k.value) for k in x.keywords) for x in calls)
    source=Path(n.__file__).read_text()
    assert "science.verify_plan(rd,approved=True,_session=session)" in source
    assert "state['stages']['science']['status'] == 'failed'" in source
    assert "c['max_seconds'] <= remaining" in source
    assert 'original_success_inferred' in source and 'False' in source


@pytest.mark.parametrize('defect',[None,'missing_result','missing_grid','nonfinite','alias','zero_result','zero_process'])
def test_complete_native_channel_reader_retains_zero_law_and_refuses_uncommitted_products(tmp_path,monkeypatch,defect):
    cmd,request,_=build_case(tmp_path,monkeypatch)
    directory=Path(cmd.me_dir)/'SubProcesses/P1';grid=directory/'G1/ftn25';result=directory/'G1/results.dat'
    if defect=='missing_result':result.unlink()
    elif defect=='missing_grid':grid.unlink()
    elif defect=='alias':(directory/'G1').rename(directory/'other');(directory/'G1').symlink_to('other')
    elif defect=='zero_process':
        cmd.Gdirs=({str(directory):[]},{})
        (directory/'ajob.no_ps.log').write_bytes(b'source zero-phase-space diagnostic')
    class Reader:
        def __init__(self,channel):
            self.axsec=self.xsec=0. if defect=='zero_result' else 2.
            self.xerru=self.xerrc=.1;self.nevents=13;self.nw=3;self.maxit=4;self.nunwgt=3;self.luminosity=1.;self.wgt=0.;self.maxwgt=float('nan') if defect=='nonfinite' else 1.
            self.run_statistics=RunStatistics(stable_points=13)
        def read_results(self,path):Path(path).read_bytes()
    module=SimpleNamespace(__file__=str(Path(request['madgraph'])/'madgraph/madevent/sum_html.py'),OneResult=Reader,RunStatistics=RunStatistics)
    monkeypatch.setattr(n.importlib,'import_module',lambda name:module)
    if defect in ('missing_result','missing_grid','nonfinite','alias'):
        with pytest.raises((ValueError,OSError)):CHANNEL_STATE(cmd,s,1024**2,request['madgraph'])
    else:
        rows=CHANNEL_STATE(cmd,s,1024**2,request['madgraph'])
        assert len(rows)==1 and rows[0]['process']=='P1'
        assert rows[0]['zero_phase_space'] is (defect=='zero_process')
        if defect!='zero_process':assert rows[0]['channels'][0]['result_size']==len(result.read_bytes())


def origin_case(tmp_path,monkeypatch,*,ceiling=100,checkpoint_policy=None):
    from contextlib import contextmanager
    from ravel.workflow import science,execution,state_io,validation_io
    output=tmp_path/'old/output';output.mkdir(parents=True)
    _,request,record=build_case(tmp_path,monkeypatch,output,ceiling=ceiling,checkpoint_policy=checkpoint_policy)
    # Explicit inert original approved-native boundary. The real core Session,
    # source pin/readback, failed-state, charge and cleanup code below is used.
    monkeypatch.setattr(n,'PRIMARY',record['source_contract'])
    helper={'path':str(Path(n.__file__)),'sha256':hashlib.sha256(Path(n.__file__).read_bytes()).hexdigest(),'size':Path(n.__file__).stat().st_size}
    phase={'integration_checkpoint':{'helper':helper,'storage_helper':helper,'request':{'original':record['original']}}}
    monkeypatch.setattr(execution,'STATE_NAME','execution.json')  # explicit inert fixture ledger pathname
    def write(path,value):
        if path.name=='execution.json':value=dict(schema_version=execution.VERSION,revision=0,**value)
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(s.encoded(value))
    write(output/'native-phase-observer-request.json',phase)
    digest=hashlib.sha256(s.encoded(phase)).hexdigest()
    (output/'command-observations.jsonl').write_bytes(s.encoded({'phase':'generate-decay-shower-reweight','state':'running','command':['inert-phase',digest]}))
    checkpoint=output/'integration-checkpoint/checkpoint.json'
    (output/'model-events-phase-observations.jsonl').write_bytes(s.encoded({'phase':'survey','state':'captured','checkpoint':{'path':str(checkpoint),'sha256':s.digest(record),'size':checkpoint.stat().st_size}}))
    rd=tmp_path/'old';write(rd/'execution_attempt.json',{'attempt':1})
    group=record['capture_owner']['group']
    write(output/'native-process.json',{'command':['inert-native-boundary'],'pid':group,'process_group':group})
    monkeypatch.setattr(n,'process_table',lambda:[])  # exact inert old-group absence after capture
    write(output/'native-execution.json',{'command':['inert-native-boundary'],'wall_seconds':40,'max_seconds':ceiling})
    write(rd/'logs/science.failure.json',{'stage':'science','elapsed_s':40,'cleanup':{'group_state':'empty','remaining_group_members':[],'requires_recovery':False}})
    write(output/'native-input.json',{'config_sha256':record['original']['config_sha256'],'source_base':str(tmp_path),'config':request['config'],'model':request['roots']['model']})
    ledger={'stages':{'science':{'status':'failed'}}};write(rd/'execution.json',ledger)
    monkeypatch.setattr(science,'verify_plan',lambda *a,**k:{'fixture':'original admitted plan','base_dir':str(tmp_path)})
    monkeypatch.setattr(science,'execution_spec',lambda *a,**k:{'mode':'model-events','goal_binding':record['original']['goal_binding'],'task':{'config':'source-config.json'}})
    monkeypatch.setattr(science,'_selected',lambda *a,**k:({'outputs':['output']},{},100))
    @contextmanager
    def scope(path):
        session=validation_io.ValidationSession(path,resolve_path=execution.resolve_path,read_json=state_io.read_json,
            runtime_context=lambda:{'inert_software':True},digest=execution.digest,state_name='execution.json')
        try:
            yield session
            errors=session.finish()
            if errors:raise ValueError('; '.join(errors))
        finally:session.close()
    monkeypatch.setattr(science,'_validation_scope',scope)
    changed=deepcopy(request['config']);changed['max_seconds']=30
    changed['integration_checkpoint']=dict(policy(),candidate={'rundir':str(rd),'attempt':1,'checkpoint_sha256':s.digest(record)})
    return changed,rd,output,write


@pytest.mark.parametrize('defect',[None,'success','old_owner','budget','native_budget','receipt_budget','source_config','attempt','helper','phase','original_stdout'])
def test_failed_origin_current_custody_charge_cleanup_and_remaining_budget_are_real_consumers(tmp_path,monkeypatch,defect):
    c,rd,output,write=origin_case(tmp_path,monkeypatch)
    if defect=='success':write(rd/'execution.json',{'stages':{'science':{'status':'succeeded'}}})
    elif defect=='old_owner':monkeypatch.setattr(n,'process_table',lambda:[{'pid':os.getpgrp(),'parent':1,'group':os.getpgrp(),'state':'S'}])
    elif defect=='budget':c['max_seconds']=61
    elif defect=='native_budget':
        doc=json.loads((output/'native-input.json').read_text());doc['config']['max_seconds']=50;write(output/'native-input.json',doc)
    elif defect=='receipt_budget':write(output/'native-execution.json',{'command':['inert-native-boundary'],'wall_seconds':40,'max_seconds':50})
    elif defect=='source_config':
        path=rd.parent/'source-config.json';doc=json.loads(path.read_text());doc['max_seconds']=1000;write(path,doc)
    elif defect=='attempt':c['integration_checkpoint']['candidate']['attempt']=2
    elif defect=='helper':
        doc=json.loads((output/'native-phase-observer-request.json').read_text());doc['integration_checkpoint']['helper']['sha256']='0'*64
        write(output/'native-phase-observer-request.json',doc)
        digest=hashlib.sha256(s.encoded(doc)).hexdigest()
        (output/'command-observations.jsonl').write_bytes(s.encoded({'phase':'generate-decay-shower-reweight','state':'running','command':['inert-phase',digest]}))
    elif defect=='phase':(output/'model-events-phase-observations.jsonl').write_bytes(b'')
    elif defect=='original_stdout':(output/'generate-decay-shower-reweight-stdout.log').write_bytes(b'foreign log')
    if defect is not None:
        with pytest.raises((ValueError,OSError)):n.admit(c,tmp_path)
        assert not (tmp_path/'continuation').exists()
        return
    admitted=n.admit(c,tmp_path)
    assert admitted['state']=='continue' and admitted['remaining_original_seconds']==60
    assert str(output/'integration-checkpoint/checkpoint.json') in admitted['inputs']
    assert json.loads((rd/'execution.json').read_text())['stages']['science']['status']=='failed'
    assert not (tmp_path/'continuation').exists()


@pytest.mark.parametrize('requested',[10,11])
def test_original_native_ceiling_binds_even_when_stage_has_more_time(tmp_path,monkeypatch,requested):
    c,rd,output,write=origin_case(tmp_path,monkeypatch,ceiling=50)
    c['max_seconds']=requested
    if requested==11:
        with pytest.raises(ValueError,match='original remaining charged wall budget'):n.admit(c,tmp_path)
        assert not (tmp_path/'continuation').exists()
    else:
        admitted=n.admit(c,tmp_path)
        assert admitted['remaining_original_seconds']==10
        assert json.loads((output/'native-execution.json').read_text())['max_seconds']==50
        assert json.loads((rd/'execution.json').read_text())['stages']['science']['status']=='failed'


@pytest.mark.parametrize('defect',[None,'outside','foreign_source','old_marker'])
def test_forced_child_requires_real_source_bound_enclosing_owner_frame(tmp_path,monkeypatch,defect):
    process=tmp_path/'process';process.mkdir();(process/'RunWeb').write_text(str(os.getpid()))
    root=tmp_path/'mg';path=root/'madgraph/interface/launch_ext_program.py';path.parent.mkdir(parents=True)
    raw="class MELauncher:\n def launch_program(self,cmd,consume):\n  usecmd=cmd\n  return consume(cmd)\n"
    path.write_text(raw)
    namespace={};exec(compile(raw,str(path),'exec'),namespace)
    owner=namespace['MELauncher']();owner.running_dir=str(process)
    module=SimpleNamespace(__file__=str(path),MELauncher=namespace['MELauncher'])
    cmd=SimpleNamespace(me_dir=str(process),force_run=True)
    monkeypatch.setattr(n.importlib,'import_module',lambda name:module)
    if defect=='foreign_source':module.__file__=str(tmp_path/'unrelated.py')
    elif defect=='old_marker':(process/'RunWeb').write_text('987650')
    consume=lambda command:n.native_owner(command,root,s)
    if defect is None:
        assert owner.launch_program(cmd,consume)==str(os.getpid()).encode()
    else:
        with pytest.raises(ValueError):
            if defect=='outside':consume(cmd)
            else:owner.launch_program(cmd,consume)


def test_released_defaultdict_list_factory_items_and_shared_values_are_exact(tmp_path):
    original=state(tmp_path);shared=['iseed'];original['run_card'].includepath=defaultdict(list,first=shared,second=shared)
    restored=n.decode_graph(n.encode_graph(original,CLASSES),CLASSES)
    d=restored['run_card'].includepath
    assert type(d) is defaultdict and d.default_factory is list and list(d)==['first','second']
    assert d['first'] is d['second'] and d['new']==[]
    assert type(d['new']) is list


@pytest.mark.parametrize('factory',[None,int,dict])
def test_nonreleased_defaultdict_factory_is_not_coerced(factory):
    with pytest.raises(ValueError,match='defaultdict'):n.encode_graph(defaultdict(factory),CLASSES)


@pytest.mark.parametrize('dimension',['member','total','files'])
def test_smaller_current_policy_refuses_before_any_checkpoint_payload_read(tmp_path,monkeypatch,dimension):
    _,_,record=build_case(tmp_path,monkeypatch)
    current=policy()
    if dimension=='member':current['max_member_bytes']=len(s.encoded(record))-1
    elif dimension=='total':
        current['max_bytes']=record['tree']['total_bytes']+len(s.encoded(record))+record['survey_stdout']['size']+record['continuation_control']['genesis']['size']-1
        current['max_member_bytes']=min(current['max_member_bytes'],current['max_bytes'])
    else:current['max_files']=len(record['tree']['rows'])+record['tree']['referenced_files']
    real=s.regular_bytes;reads=[]
    def read(path,maximum):reads.append(str(path));return real(path,maximum)
    monkeypatch.setattr(s,'regular_bytes',read)
    with pytest.raises(ValueError,match='current'):n.materialize(record,tmp_path/'fresh',record['tree']['roots'],limits=current)
    assert reads==[] and not (tmp_path/'fresh').exists()
    # The unchanged original policy still admits exactly the complete record.
    assert n.verify(record)==record


def claim_case(tmp_path,monkeypatch):
    c,rd,out,write=origin_case(tmp_path,monkeypatch)
    admission=n.admit(c,tmp_path);owners={};active=[None];terminal={}
    # Explicit inert current approved/registered native boundary. claim/admit,
    # locks, immutable emissions and full reservation arithmetic remain real.
    def owner(task,base,output,**kwargs):
        selected=owners[str(output)]
        if active[0] is not None and active[0]!=str(output):raise ValueError('inert current registration differs')
        return deepcopy(selected)
    monkeypatch.setattr(n,'_owner',owner)
    monkeypatch.setattr(n,'_terminal',lambda claim:terminal.get(claim['owner']['rundir']))
    def add(name,seconds):
        output=tmp_path/name/'output';output.mkdir(parents=True)
        owner={'rundir':str(output.parent),'attempt':1,'output':str(output),'fingerprint':name,
            'child_pid':123,'child_identity':'inert declared current owner',
            'config':{'path':str(tmp_path/'source-config.json'),'sha256':admission['origin_request']['config_sha256']},'goal_binding':admission['goal_binding']}
        owners[str(output)]=(owner,seconds)
        return output
    return c,admission,add,terminal,active


@pytest.mark.parametrize('scenario',['duplicate','concurrent','unknown','failed_exhausted','succeeded','unused_remainder'])
def test_all_successors_share_one_original_reservation_and_rng_lineage(tmp_path,monkeypatch,scenario):
    c,admission,add,terminal,active=claim_case(tmp_path,monkeypatch)
    first=add('first',30 if scenario=='unused_remainder' else 60)
    claim=n.claim(c,tmp_path,{'config':'source-config.json'},first)
    root,journal=n.read_control(admission['record'])
    assert sum(e['claim']['seconds'] for e in journal['entries'])==claim['seconds']
    assert claim['same_sample_lineage'] and not claim['independent_sample']
    if scenario=='duplicate':
        with pytest.raises(ValueError,match='duplicate'):n.claim(c,tmp_path,{'config':'source-config.json'},first)
    elif scenario=='concurrent':
        from ravel.workflow.state_io import file_lock
        with file_lock(root/'control.lock'):
            with pytest.raises(ValueError,match='another process owns control.lock'):n.claim(c,tmp_path,{'config':'source-config.json'},add('second',30))
    else:
        if scenario in ('failed_exhausted','unused_remainder','succeeded'):
            terminal[str(first.parent)]={'status':'succeeded' if scenario=='succeeded' else 'failed','fixture':'explicit inert terminal/cleanup authority'}
        second=add('second',30)
        if scenario=='unused_remainder':
            second_claim=n.claim(c,tmp_path,{'config':'source-config.json'},second)
            final=n.read_control(admission['record'])[1]
            assert sum(e['claim']['seconds'] for e in final['entries'])==60 and final['entries'][0]['status']=='failed'
            assert second_claim['checkpoint_sha256']==claim['checkpoint_sha256']
        else:
            with pytest.raises(ValueError,match='active or unknown|cumulative|cannot replay'):n.claim(c,tmp_path,{'config':'source-config.json'},second)
    assert sum(e['claim']['seconds'] for e in n.read_control(admission['record'])[1]['entries'])>=claim['seconds']


@pytest.mark.parametrize('defect',['journal_missing','genesis_missing','extra','claim_bytes','mode','unregistered'])
def test_control_missing_mutated_or_unadmitted_never_replenishes_grant(tmp_path,monkeypatch,defect):
    c,admission,add,terminal,active=claim_case(tmp_path,monkeypatch);first=add('first',30)
    claim=n.claim(c,tmp_path,{'config':'source-config.json'},first);root,_=n.read_control(admission['record'])
    if defect=='journal_missing':(root/'journal.json').unlink()
    elif defect=='genesis_missing':(root/'genesis.json').unlink()
    elif defect=='extra':(root/'unlisted').write_bytes(b'new')
    elif defect=='claim_bytes':Path(claim['claim']['path']).write_bytes(b'{}')
    elif defect=='mode':(root/'journal.json').chmod(0o644)
    else:active[0]=str(first)
    with pytest.raises((ValueError,OSError)):n.claim(c,tmp_path,{'config':'source-config.json'},add('second',30))
    assert not (tmp_path/'second/output/native-input.json').exists()


def test_actual_worker_claim_precedes_native_effect_and_both_ending_guards():
    tree=ast.parse(Path(m.__file__).read_text());run=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='run')
    claim=next(x for x in ast.walk(run) if isinstance(x,ast.Call) and ast.unparse(x.func)=='native_integration_checkpoint.claim')
    native=next(x for x in ast.walk(run) if isinstance(x,ast.Call) and ast.unparse(x.func)=='execute_native')
    assert claim.lineno<native.lineno
    assert sum(isinstance(x,ast.Call) and ast.unparse(x.func)=='native_integration_checkpoint.verify_claim' for x in ast.walk(run))>=3
    worker=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='native_worker')
    assert sum(isinstance(x,ast.Call) and ast.unparse(x.func)=='native_integration_checkpoint.verify_claim' for x in ast.walk(worker))>=3


@pytest.mark.parametrize('defect',[None,'status','fingerprint','identity','goal','native_parent'])
def test_actual_current_owner_reads_registered_plan_attempt_state_and_native_identity(tmp_path,monkeypatch,defect):
    from ravel.workflow import science,execution
    c,rd,out,write=origin_case(tmp_path,monkeypatch)
    monkeypatch.setattr(m,'_approved',lambda task,output:(rd,{'max_seconds':30}))
    monkeypatch.setattr(science,'_selected',lambda *a,**k:({'outputs':['output']},{'fingerprint':'bound-current'},30))
    monkeypatch.setattr(execution,'process_identity',lambda pid:'declared inert process identity')
    state={'status':'running','fingerprint':'bound-current','child_pid':os.getpid(),'child_identity':'declared inert process identity'}
    if defect=='status':state['status']='failed'
    elif defect=='fingerprint':state['fingerprint']='foreign'
    elif defect=='identity':state['child_identity']='foreign'
    elif defect=='goal':monkeypatch.setattr(science,'execution_spec',lambda *a,**k:{'mode':'model-events','goal_binding':None,'task':{'config':'source-config.json'}})
    write(rd/'execution.json',{'stages':{'science':state}})
    task={'config':'source-config.json'}
    if defect=='native_parent':
        write(out/'native-process.json',{'pid':os.getpid(),'process_group':os.getpgrp(),'owner_pid':os.getppid()+1})
        with pytest.raises(ValueError,match='native continuation owner'):n._owner(task,tmp_path,out,native=True)
        return
    if defect is not None:
        with pytest.raises(ValueError,match='current'):n._owner(task,tmp_path,out)
        return
    owner,seconds=n._owner(task,tmp_path,out)
    assert owner['rundir']==str(rd) and owner['attempt']==1 and owner['fingerprint']=='bound-current' and seconds==30
    assert owner['config']['sha256']==hashlib.sha256((tmp_path/'source-config.json').read_bytes()).hexdigest()


@pytest.mark.parametrize('status',['failed','succeeded','unknown_cleanup','changed_config'])
def test_failed_terminal_releases_only_ownership_with_zero_refund_and_fresh_custody(tmp_path,monkeypatch,status):
    from ravel.workflow import science,execution
    c,rd,out,write=origin_case(tmp_path,monkeypatch)
    monkeypatch.setattr(science,'_selected',lambda *a,**k:({'outputs':['output']},{'fingerprint':'bound-current'},30))
    owner={'rundir':str(rd),'attempt':1,'output':str(out),'fingerprint':'bound-current','child_pid':123,
        'child_identity':'inert identity','config':{'path':str(tmp_path/'source-config.json'),'sha256':hashlib.sha256((tmp_path/'source-config.json').read_bytes()).hexdigest()},'goal_binding':{'synthetic':True}}
    write(rd/'execution.json',{'stages':{'science':{'status':'succeeded' if status=='succeeded' else 'failed','fingerprint':'bound-current','child_pid':123,'child_identity':'inert identity'}}})
    write(out/'native-process.json',{'pid':987,'process_group':987,'owner_pid':123,'command':['inert']})
    write(out/'native-execution.json',{'command':['inert'],'returncode':0,'resource_violation':None})
    if status=='unknown_cleanup':monkeypatch.setattr(n,'process_table',lambda:[{'pid':987,'group':987,'parent':123,'state':'S'}])
    elif status=='changed_config':(tmp_path/'source-config.json').write_bytes(b'{}')
    claim={'owner':owner,'seconds':30};terminal=n._terminal(claim)
    if status in ('unknown_cleanup','changed_config'):assert terminal is None
    else:
        assert terminal['status']==status and terminal['refund_seconds']==0 and terminal['charged_seconds']==30
        assert any(x['path'].endswith('native-execution.json') for x in terminal['receipt_inputs'])


@pytest.mark.parametrize('defect',['intended_bytes','writer_exception'])
def test_claim_write_failure_prevents_effect_and_never_reuses_unknown_charge(tmp_path,monkeypatch,defect):
    from ravel.workflow import state_io
    c,admission,add,terminal,active=claim_case(tmp_path,monkeypatch);first=add('first',30)
    real=state_io.atomic_json
    def write(path,value):
        if defect=='writer_exception':raise OSError('inert interrupted journal emission')
        real(path,value)
        doc=json.loads(Path(path).read_text());doc['entries'][0]['claim']['seconds']=1
        real(path,doc)
    monkeypatch.setattr(state_io,'atomic_json',write)
    with pytest.raises((ValueError,OSError)):n.claim(c,tmp_path,{'config':'source-config.json'},first)
    assert not (first/'native-input.json').exists()
    monkeypatch.setattr(state_io,'atomic_json',real)
    with pytest.raises((ValueError,OSError)):n.claim(c,tmp_path,{'config':'source-config.json'},add('second',30))


def test_public_nested_continuation_config_retains_current_base_and_no_planning_effect(tmp_path,monkeypatch):
    c,rd,output,write=origin_case(tmp_path,monkeypatch);nested=tmp_path/'successor';nested.mkdir()
    transported=deepcopy(c)
    for name,pin in transported['cards'].items():pin['path']=os.path.relpath(pin['path'],nested)
    transported['model_tree']['root']=os.path.relpath(transported['model_tree']['root'],nested)
    transported['model_tree']['manifest']['path']=os.path.relpath(transported['model_tree']['manifest']['path'],nested)
    write(nested/'config.json',transported)
    admitted=n.admit(transported,nested)
    assert admitted['current_source_base']==str(nested) and admitted['record']['compatibility']==n.compatibility(transported,nested)
    root,journal=n.read_control(admitted['record'])
    assert journal['entries']==[] and not (nested/'native-input.json').exists()
    with pytest.raises(ValueError,match='same-run complete'):n.admit(transported,tmp_path)


@pytest.mark.parametrize('old_mib,current_mib,log_kib',[
    (1,2,1536), (2,1,1536), (1,2,768), (2,1,768),
])
def test_closed_original_log_uses_one_intersection_at_admission_seed_and_ending(tmp_path,monkeypatch,old_mib,current_mib,log_kib):
    original_policy=dict(policy(),max_member_bytes=old_mib*1024**2)
    c,rd,output,write=origin_case(tmp_path,monkeypatch,checkpoint_policy=original_policy)
    c['integration_checkpoint']['max_member_bytes']=current_mib*1024**2
    capsule=output/'integration-checkpoint';record=json.loads((capsule/'checkpoint.json').read_text())
    # All mandatory original metadata fits its actual capture policy. Only the
    # subsequently closed log grows; neither checkpoint nor genesis is rewritten.
    prefix=(capsule/'survey-stdout-prefix.bin').read_bytes()
    assert all(size<=original_policy['max_member_bytes'] for size in (
        (capsule/'checkpoint.json').stat().st_size,len(prefix),record['continuation_control']['genesis']['size']))
    origin=output/'generate-decay-shower-reweight-stdout.log'
    origin.write_bytes(prefix+b'x'*(log_kib*1024-len(prefix)))
    root,journal=n.read_control(record);before={p.name:p.read_bytes() for p in root.iterdir()}
    seen=[];effect_calls=[];real=s.regular_bytes
    def read(path,maximum):
        if Path(path)==origin:seen.append(maximum)
        return real(path,maximum)
    def owner(*args,**kwargs):
        effect_calls.append(args)
        raise AssertionError('read-only admission must not claim a native owner')
    monkeypatch.setattr(s,'regular_bytes',read);monkeypatch.setattr(n,'_owner',owner)
    ceiling=min(old_mib,current_mib)*1024**2
    if origin.stat().st_size>ceiling:
        with pytest.raises(ValueError,match='bounded regular reuse member required'):n.admit(c,tmp_path)
        assert seen==[ceiling]
    else:
        admitted=n.admit(c,tmp_path)
        assert admitted['effective_policy']['max_member_bytes']==ceiling
        assert admitted['record']['tree']['options']==original_policy
        tail=tmp_path/'continued-tail.log';tail.write_bytes(b'actual-fixture resumed tail without a survey\n')
        evidence=n.seed_evidence(admitted,tail);n.ending(admitted)
        assert evidence['effective_policy']==admitted['effective_policy']
        assert evidence['original_stdout']==admitted['original_stdout'] and evidence['same_sample_lineage'] and not evidence['independent_sample']
        assert len(seen)>=3 and all(limit==ceiling for limit in seen)
    assert not effect_calls and not (tmp_path/'continuation').exists()
    assert c['integration_checkpoint']['max_member_bytes']==current_mib*1024**2
    assert journal['entries']==[] and n.read_control(record)[1]['entries']==[]
    assert {p.name:p.read_bytes() for p in root.iterdir()}==before
