"""Pure engineering controls: no Contur/SDK imports or scientific worker calls."""
import argparse
import ast
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest
from ravel.physics import contur_yoda as m, contur_import
from ravel.workflow import science

@pytest.fixture(autouse=True)
def deny_external_launches(monkeypatch):
    import subprocess
    def deny(*args, **kwargs):
        raise AssertionError('no external launches admitted by source-only controls')
    for name in ('Popen', 'run', 'call', 'check_call', 'check_output'):
        monkeypatch.setattr(subprocess, name, deny)
    monkeypatch.setattr(os, 'system', deny)





def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2)+'\n')
    return path


def pin(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def requested():
    s = deepcopy(m.FIXED)
    s.update({k: False for k in m.BOOL_FLAGS})
    s.update({k: True for k in m.INVERSE_FLAGS})
    s.update(use_spey=False, min_num_sys=5, min_num_sys_sm=5,
             add_sqrt_evtcount_signal_error=True, flat_uncertainty=None,
             only_analyses=['SYN_9051_I1325'], veto_analyses=[], weight='', sorting_metric='LLR')
    return s


def fixture(tmp):
    y = tmp/'supplied.yoda'; y.write_text('SOURCE-ONLY YODA PLACEHOLDER, NEVER EXECUTED\n')
    p = tmp/'original-params.dat'; p.write_text('mZp = 1000\ncotH = 1.5\n')
    c = tmp/'supplied-config.dat'; c.write_text('SOURCE-ONLY CONFIG PLACEHOLDER\n')
    py = tmp/'bound-python'; py.write_text('not an interpreter\n'); py.chmod(0o755)
    dependency = tmp/'dependency.py'; dependency.write_text('# bound stand-in\n')
    assets = {}
    for kind in ('source','data','user'):
        root = tmp/kind; root.mkdir()
        names = {'source': ['src/contur/__init__.py','bin/contur','pyproject.toml','COPYING'],
                 'data': ['data/reference.yoda'], 'user': ['analyses.db','models.db']}[kind]
        files = {}
        for name in names:
            f = root/name; f.parent.mkdir(parents=True,exist_ok=True); f.write_text('# source control '+name+'\n')
            files[name] = pin(f)['sha256']
        md = {'schema_version':1,'kind':'contur-'+kind,'root':str(root),'files':files,'scope':'synthetic custody control, not released code/runtime'}
        if kind == 'source': md.update(version=m.VERSION,commit=m.COMMIT)
        assets[kind] = pin(write(tmp/(kind+'-manifest.json'),md))
    rt = {'schema_version':1,'kind':'contur-declared-runtime','python_sha256':pin(py)['sha256'],
          'installed_distribution_version':'3.1.4; declared stand-in, not runtime qualification',
          'files':[pin(dependency)],'environment':{k:os.environ.get(k) for k in m.ENV_KEYS},
          'scope':'complete declared fixture only; no execution consumption'}
    d = {'schema_version':1,'source':'synthetic input/assets; no native result', 'yoda':pin(y),'parameters':pin(p),
         'expected_events':17,'config':pin(c),'runtime':{'python':pin(py),'manifest':pin(write(tmp/'runtime.json',rt))},
         'assets':assets,'settings':requested(),'max_seconds':30,'max_ram_mib':512}
    inp = write(tmp/'input.json',d)
    return {'input':str(inp)},d


@pytest.mark.parametrize('key,value',[('max_seconds',True),('max_seconds',0),('max_seconds',901),('max_ram_mib',511),('expected_events',0),('expected_events',False)])
def test_integer_contract_refuses(tmp_path,key,value):
    task,d=fixture(tmp_path);d[key]=value;write(Path(task['input']),d)
    with pytest.raises(ValueError):m.inputs(task,tmp_path)


@pytest.mark.parametrize('key,value',[('stat_types',['SMBG']),('multi_p',True),('no_pools',True),('offline',False),('npyscripts',0),('only_analyses',[]),('min_num_sys',True),('min_num_sys',0),('flat_uncertainty',-1),('flat_uncertainty',float('nan')),('weight',None),('diag',0),('sorting_metric','discovery')])
def test_requested_scientific_semantics_are_explicit(key,value):
    s=requested();s[key]=value
    with pytest.raises((ValueError,TypeError)):m.settings(s)


@pytest.mark.parametrize('text',['m = 1\nm = 2\n','m=1\n','m = nan\n','slha_file = spectrum.slha\n',' = 1\n','m = 1 = 2\n',''])
def test_parameter_format_and_population_refusal(tmp_path,text):
    p=tmp_path/'params.dat';p.write_text(text)
    with pytest.raises(ValueError):m.parameter_values(p)




def test_source_materialization_retains_original_bytes_and_version_mismatch(tmp_path):
    task,d=fixture(tmp_path);before={str(p):m._sha(p) for p in m.inputs(task,tmp_path)}
    out=tmp_path/'prepared';native=m.materialize(task,tmp_path,out)
    assert (out/'input/supplied.yoda').read_bytes()==Path(d['yoda']['path']).read_bytes()
    assert (out/'input/params.dat').read_bytes()==Path(d['parameters']['path']).read_bytes()
    assert (out/'user/analyses.db').read_bytes()==(tmp_path/'user/analyses.db').read_bytes()
    assert m.parameter_values(out/'input/params.dat')=={'mZp':1000,'cotH':1.5}
    assert json.loads((out/'preparation.json').read_text())['installed_distribution_version'].startswith('3.1.4')
    assert json.loads(native.read_text())['assets']==d['assets']
    assert before=={str(p):m._sha(p) for p in m.inputs(task,tmp_path)}
    with pytest.raises(FileExistsError):m.materialize(task,tmp_path,out)


@pytest.mark.parametrize('kind,name',[('source','src/contur/new.py'),('data','data/new.yoda'),('user','unbound-extra.dat')])
def test_missing_manifest_leaf_refuses(tmp_path,kind,name):
    task,d=fixture(tmp_path);p=tmp_path/kind/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('new unbound asset')
    with pytest.raises(ValueError,match='inventory'):m.inputs(task,tmp_path)


@pytest.mark.parametrize('key',['yoda','parameters','config'])
def test_altered_scientific_bytes_refuse(tmp_path,key):
    task,d=fixture(tmp_path);Path(d[key]['path']).write_text('altered')
    with pytest.raises(ValueError,match='changed'):m.inputs(task,tmp_path)


def test_symlink_and_traversal_are_not_manifest_assets(tmp_path):
    task,d=fixture(tmp_path);p=tmp_path/'source-manifest.json';md=json.loads(p.read_text())
    md['files']['../supplied.yoda']=d['yoda']['sha256'];write(p,md);d['assets']['source']=pin(p);write(Path(task['input']),d)
    with pytest.raises(ValueError,match='canonical'):m.inputs(task,tmp_path)








@pytest.mark.parametrize('key,value',[('diag',True),('flat_uncertainty',.2),('min_num_sys_sm',9),('weight','variation'),('only_analyses',['OTHER']),('use_spey',True)])
def test_configuration_override_refuses_before_inference(key,value):
    effective=requested();effective[key]=value
    with pytest.raises(ValueError,match='before inference'):m.check_effective(requested(),effective)


def test_arguments_preserve_overlap_protection_modes_and_named_weight():
    d={'settings':requested(),'yoda':{'path':'relative/native.yoda.gz'}}
    d['settings']['weight']='PDF[1]';d['settings']['exclude_hww']=False;d['settings']['use_spey']=True
    args=m.arguments(d,Path('/fresh/work'))
    assert args[0]=='/fresh/work/input/native.yoda.gz'
    assert args[args.index('--weight-name')+1]=='PDF[1]'
    assert '--spey' in args and '--withhiggsww' in args and '--nomultip' in args
    assert not set(args)&{'--no-pools','--no-exp','--databg','--grid','--add-db','--all'}
    assert args[args.index('--resultsfile')+1]=='results.db'


def raw_point():
    return SimpleNamespace(full_likelihood_results={k:{'CLs':.95} for k in contur_import.MODES},
                           sorted_blocks_results={k:{'FIRST':{'CLs':.97},'SECOND':{'CLs':.97},'OTHER':{'CLs':.7}} for k in contur_import.MODES})


@pytest.mark.parametrize('value',[None,False,-.1,1.1,float('nan'),float('inf')])
def test_none_to_zero_or_invalid_native_confidence_is_never_results(value):
    p=raw_point();p.full_likelihood_results['SMBG']['CLs']=value
    with pytest.raises(ValueError):m.confidence_witness(p)


def test_genuine_zero_confidence_is_allowed():
    p=raw_point();p.full_likelihood_results['SMBG']['CLs']=0
    assert m.confidence_witness(p)['SMBG']['combined']==0


def test_complete_database_reconciliation_keeps_ties_and_complement(tmp_path):
    db=tmp_path/'fresh.db';yoda=tmp_path/'supplied.yoda'
    with sqlite3.connect(db) as c:
        for table,columns in contur_import.REQUIRED_COLUMNS.items():
            c.execute('CREATE TABLE '+table+' ('+','.join(x+' '+('TEXT' if x in {'run_point','yoda_files','name','stat_type','addition_argument','pool_name','histos'} else 'INTEGER' if x in {'id','model_id','model_point_id','run_id','map_id','events_num'} else 'DOUBLE') for x in columns)+')')
        c.execute('INSERT INTO model_point VALUES (1,1,?,?)',('',repr([str(yoda)])))
        c.execute('INSERT INTO parameter_value VALUES (1,?,?)',('mZp',1000))
        for i,mode in enumerate(contur_import.MODES,1):
            c.execute('INSERT INTO run VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(i,1,1,17,mode,.95,3.25,2.34567,None,None,None,'NATIVE'))
            for j,(name,val) in enumerate([('FIRST',.97),('SECOND',.97),('OTHER',.7)],1):
                c.execute('INSERT INTO exclusions VALUES (?,?,?,?,?,?,?,?,?,?,?)',(10*i+j,i,name,mode,val,'/'+name,1.,2.,None,None,None))
    points=contur_import.decode_database(db);doc={'parameter_values':{'mZp':1000},'expected_events':17}
    out=m.reconcile(points,doc,yoda,m.confidence_witness(raw_point()))
    assert len(out[0]['runs'])==3
    for run in out[0]['runs']:
        assert len(run['pools'])==3 and len(run['dominant_candidates'])==2
        assert run['native_exclusion_confidence']==.95
        assert run['conventional_cls_complement']==pytest.approx(.05)
    for key,value in [('expected_events',16),('parameter_values',{'mZp':1001})]:
        changed=deepcopy(doc);changed[key]=value
        with pytest.raises(ValueError):m.reconcile(points,changed,yoda,m.confidence_witness(raw_point()))
    with pytest.raises(ValueError):m.reconcile(points,doc,tmp_path/'wrong.yoda',m.confidence_witness(raw_point()))
    wrong=m.confidence_witness(raw_point());wrong['SMBG']['pools'].pop('OTHER')
    with pytest.raises(ValueError):m.reconcile(points,doc,yoda,wrong)


def test_ordinary_mode_hooks_and_direct_run_refusal(tmp_path):
    assert 'contur-yoda' in science.MODES
    spec={'mode':'contur-yoda','task':{'input':'fake.json'}}
    assert science.adapter(spec) is m and science._new_capability(spec)
    with pytest.raises(ValueError,match='approved'):m.run(spec['task'],tmp_path,tmp_path/'out')


def test_private_native_entry_requires_live_parent_before_contur_import(tmp_path,monkeypatch):
    task,d=fixture(tmp_path);native=m.materialize(task,tmp_path,tmp_path/'prepared')
    def refuse(*args):raise ValueError('no current ordinary worker')
    monkeypatch.setattr(m,'_delegated_parent',refuse)
    with pytest.raises(ValueError,match='ordinary worker'):m.native_worker(native,tmp_path/'prepared',tmp_path)
    assert not any(n=='contur' or n.startswith('contur.') for n in __import__('sys').modules)


def test_cli_native_arg_contract_and_no_sdk_without_delegation(tmp_path):
    with pytest.raises(ValueError,match='delegation'):m.main(['--native-worker','--input','x','--out',str(tmp_path)])


def test_parent_delegation_rejects_prepared_files_without_running_worker(tmp_path):
    from ravel.workflow import state_io
    rd=tmp_path/'run';rd.mkdir()
    write(rd/science.PLAN,{'stages':[{'outputs':['outputs/attempt-1']}],'stage_binding':{'fingerprint':'dummy'}})
    # A malformed/no-approval plan is deliberately not promoted by source preparation.
    with pytest.raises((ValueError,FileNotFoundError,KeyError)):
        m._delegated_parent(rd,{},rd/'outputs/attempt-1/contur-work')


def test_source_public_cli_dispatch_exists_without_actual_execution():
    from ravel import cli
    # The same ordinary preparer is selected by the public dispatcher, no alternate runner.
    assert any('contur_yoda' in str(x) for x in vars(cli).values())


def test_full_adapter_readback_source_path_and_process_command(tmp_path,monkeypatch):
    task,d=fixture(tmp_path);out=tmp_path/'out';out.mkdir()
    monkeypatch.setattr(m,'_approved',lambda *args:(tmp_path,{'max_seconds':60}))
    from ravel.physics import reinterpret_db
    calls=[]
    def retained_capture(command,output,document):
        calls.append(command)
        parsed={}
        # Exercise the ACTUAL private entry argparse rather than matching prose.
        monkeypatch.setattr(m,'native_worker',lambda inp,work,rd:parsed.update(input=inp,work=work,rundir=rd))
        script_index=command.index(str(Path(m.__file__).resolve()))
        assert command[1:script_index]==['-B','-X','pycache_prefix='+str(out/'contur-work/bytecode-cache')]
        # Python consumes only the prefix; every post-script argument reaches argparse.
        assert m.main(command[script_index+1:])==0
        assert parsed['input']==str(out/'contur-work/native-input.json')
        assert parsed['rundir']==str(tmp_path)
        work=out/'contur-work';native=work/'native-output';native.mkdir()
        db=native/'results.db';yoda=work/'input/supplied.yoda'
        with sqlite3.connect(db) as c:
            for table,cols in contur_import.REQUIRED_COLUMNS.items():
                c.execute('CREATE TABLE '+table+' ('+','.join(x+' '+('TEXT' if x in {'run_point','yoda_files','name','stat_type','addition_argument','pool_name','histos'} else 'INTEGER' if x in {'id','model_id','model_point_id','run_id','map_id','events_num'} else 'DOUBLE') for x in cols)+')')
            c.execute('INSERT INTO model_point VALUES (1,1,?,?)',('',repr([str(yoda)])))
            c.executemany('INSERT INTO parameter_value VALUES (1,?,?)',[('mZp',1000.),('cotH',1.5)])
            for i,mode in enumerate(contur_import.MODES,1):
                c.execute('INSERT INTO run VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(i,1,1,17,mode,.95,3.25,2.,None,None,None,'STAND-IN'))
                for j,(name,val) in enumerate([('FIRST',.97),('SECOND',.97),('OTHER',.7)],1):
                    c.execute('INSERT INTO exclusions VALUES (?,?,?,?,?,?,?,?,?,?,?)',(10*i+j,i,name,mode,val,'/'+name,1.,2.,None,None,None))
        write(work/'native-observation.json',{'effective_settings':{'effective':document['settings']},'confidence_witness':m.confidence_witness(raw_point())})
        return {'returncode':0,'scope':'fake captured output; no child process/scientific computation'}
    monkeypatch.setattr(reinterpret_db,'execute_native',retained_capture)
    result=m.run(task,tmp_path,out)
    assert len(calls)==1 and calls[0][1]=='-B'
    assert result['fresh_inference'] is True # Adapter postcondition under fake transport, not an actual result claim.
    assert result['event_weights_validated'] is False and result['physics_validated'] is False
    assert (out/'native-columns.csv').is_file()
    from ravel.plotting.science_figures import render
    shown=render({'mode':'contur-yoda','task':task},result,tmp_path,out)
    assert shown['tables'][0]['files']==['native-columns.csv','contur-results.json']
    assert shown['figures']==[]


def test_all_external_module_files_are_observed_or_refused(tmp_path):
    source=tmp_path/'source';source.mkdir();a=source/'__init__.py';a.write_text('actual source')
    dep=tmp_path/'arbitrary_dependency.py';dep.write_text('dependency source')
    modules={'contur':SimpleNamespace(__file__=str(a)),'unanticipated_dependency':SimpleNamespace(__file__=str(dep))}
    declared={str(a):m._sha(a)}
    with pytest.raises(ValueError,match='absent'):m.module_witness(source,declared,{},modules=modules)
    observed=m.module_witness(source,declared,{str(dep):m._sha(dep)},modules=modules)
    assert set(observed)==set(modules)
    dep.write_text('changed dependency')
    with pytest.raises(ValueError,match='changed'):m.module_witness(source,declared,{str(dep):observed['unanticipated_dependency']['sha256']},modules=modules)


def test_sourceless_bytecode_and_wrong_contur_location_refuse(tmp_path):
    p=tmp_path/'cache.pyc';p.write_bytes(b'untrusted compiled code')
    with pytest.raises(ValueError,match='bytecode'):m.module_witness(tmp_path,{}, {},modules={'contur':SimpleNamespace(__file__=str(p))})
    p=tmp_path/'outside.py';p.write_text('outside Contur module')
    with pytest.raises(ValueError,match='outside'):m.module_witness(tmp_path/'admitted',{str(p):m._sha(p)}, {},modules={'contur':SimpleNamespace(__file__=str(p))})


@pytest.mark.parametrize('relative', ['input/supplied.yoda','input/params.dat','input/config.dat','user/analyses.db','user/models.db'])
def test_all_actual_staged_inputs_refuse_before_sdk(tmp_path, monkeypatch, relative):
    import builtins
    task,_=fixture(tmp_path);work=tmp_path/'prepared';native=m.materialize(task,tmp_path,work)
    original={str(p):m._sha(p) for p in m.inputs(task,tmp_path)}
    (work/relative).write_bytes((work/relative).read_bytes()+b'CHANGED STAGED BYTES\n')
    assert original=={str(p):m._sha(p) for p in m.inputs(task,tmp_path)}
    monkeypatch.setattr(m,'_delegated_parent',lambda *args:None)
    real_import=builtins.__import__;sdk=[]
    def no_sdk(name,*args,**kwargs):
        if name=='contur' or name.startswith('contur.'):
            sdk.append(name);raise AssertionError('actual SDK is not admitted')
        return real_import(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',no_sdk)
    with pytest.raises(ValueError,match='staged'):m.native_worker(native,work,tmp_path/'run')
    assert sdk==[]


@pytest.mark.parametrize('relative', ['input/unbound.dat','user/unbound.dat'])
def test_initial_staged_inventory_rejects_extra_files(tmp_path,relative):
    task,_=fixture(tmp_path);work=tmp_path/'prepared';native=m.materialize(task,tmp_path,work)
    _,doc,_,bundles,_=m._admission({'input':str(native)},work)
    (work/relative).write_text('unbound staged input')
    with pytest.raises(ValueError,match='staged'):m.staged_inputs(doc,bundles,work,initial_user=True)


@pytest.mark.parametrize('relative', ['input/params.dat','user/models.db'])
def test_staged_symlink_is_not_matching_byte_custody(tmp_path,relative):
    task,_=fixture(tmp_path);work=tmp_path/'prepared';native=m.materialize(task,tmp_path,work)
    _,doc,_,bundles,_=m._admission({'input':str(native)},work)
    target=work/relative;copy=tmp_path/'equal-bytes';copy.write_bytes(target.read_bytes())
    target.unlink();target.symlink_to(copy)
    with pytest.raises(ValueError,match='symlink'):m.staged_inputs(doc,bundles,work,initial_user=True)


@pytest.mark.parametrize('relative', ['input/supplied.yoda','input/params.dat','input/config.dat'])
def test_ending_scientific_copy_drift_refuses(tmp_path,relative):
    task,_=fixture(tmp_path);work=tmp_path/'prepared';native=m.materialize(task,tmp_path,work)
    _,doc,_,bundles,_=m._admission({'input':str(native)},work)
    p=work/relative;p.write_bytes(p.read_bytes()+b'ENDING DRIFT\n')
    with pytest.raises(ValueError,match='scientific'):m.staged_inputs(doc,bundles,work)


def test_ending_writable_user_inventory_is_retained_without_false_immutability(tmp_path):
    task,_=fixture(tmp_path);work=tmp_path/'prepared';native=m.materialize(task,tmp_path,work)
    _,doc,_,bundles,_=m._admission({'input':str(native)},work)
    initial=m.staged_inputs(doc,bundles,work,initial_user=True)
    (work/'user/models.db').write_text('owned changed DB stand-in')
    (work/'user/new-owned-log').write_text('owned new log stand-in')
    (work/'user/analyses.db').unlink()
    ending=m.staged_inputs(doc,bundles,work)
    assert ending['scientific_files']==initial['scientific_files']
    assert {k:v['change'] for k,v in ending['user_changes'].items()}=={'analyses.db':'removed','models.db':'changed','new-owned-log':'added'}
    assert ending['initial_user_required'] is False
    with pytest.raises(ValueError,match='initial user'):m.staged_inputs(doc,bundles,work,initial_user=True)


def sdk_stand_in(monkeypatch,work,settings,*,at_arguments=None,inside_process=None,wrong_yoda=False):
    """Pure full observer body with named SDK stand-ins; no Contur is imported."""
    import sys
    from types import ModuleType
    monkeypatch.setattr(sys,'path',list(sys.path))
    for key in ('CONTUR_USER_DIR','CONTUR_DATA_PATH'):
        monkeypatch.setenv(key,os.environ.get(key,'source-control-placeholder'))
    cfg=ModuleType('contur.config.config');cfg.__dict__.update(settings)
    contur=ModuleType('contur');contur.__version__=m.VERSION;contur.__path__=[]
    run=ModuleType('contur.run');run.__path__=[]
    config=ModuleType('contur.config');config.__path__=[];config.config=cfg
    arg=ModuleType('contur.run.arg_utils');analysis=ModuleType('contur.run.run_analysis')
    consumed=[]
    def get_args(args,kind):
        if at_arguments:at_arguments()
        return args
    def process(args,yoda,csvfile=None):
        consumed.append(yoda)
        if inside_process:inside_process()
        return raw_point()
    def write_point(point,*args):return None
    def main(args):
        p=work/'input'/('wrong.yoda' if wrong_yoda else 'supplied.yoda')
        point=analysis.process_single(args,str(p))
        analysis.write_point(point)
    arg.get_args=get_args;analysis.process_single=process;analysis.write_point=write_point;analysis.main=main
    run.arg_utils=arg;run.run_analysis=analysis
    for name,module in [('contur',contur),('contur.run',run),('contur.run.arg_utils',arg),('contur.run.run_analysis',analysis),('contur.config',config),('contur.config.config',cfg)]:
        monkeypatch.setitem(sys.modules,name,module)
    monkeypatch.setattr(m,'module_witness',lambda *args,**kwargs:{'scope':'explicit SDK stand-in; not loaded-source qualification'})
    monkeypatch.setattr(m,'_delegated_parent',lambda *args:None)
    return consumed


@pytest.mark.parametrize('relative', ['input/params.dat','user/analyses.db'])
def test_staged_drift_after_sdk_setup_refuses_before_process(tmp_path,monkeypatch,relative):
    task,d=fixture(tmp_path);work=tmp_path/'prepared';native=m.materialize(task,tmp_path,work)
    def drift():p=work/relative;p.write_bytes(p.read_bytes()+b'AFTER SDK SETUP\n')
    consumed=sdk_stand_in(monkeypatch,work,d['settings'],at_arguments=drift)
    with pytest.raises(ValueError,match='staged'):m.native_worker(native,work,tmp_path/'run')
    assert consumed==[]


def test_actual_before_process_wrapper_rejects_wrong_yoda(tmp_path,monkeypatch):
    task,d=fixture(tmp_path);work=tmp_path/'prepared';native=m.materialize(task,tmp_path,work)
    consumed=sdk_stand_in(monkeypatch,work,d['settings'],wrong_yoda=True)
    with pytest.raises(ValueError,match='process_single YODA'):m.native_worker(native,work,tmp_path/'run')
    assert consumed==[]


def test_full_observer_ending_checkpoint_retains_owned_user_db_write(tmp_path,monkeypatch):
    task,d=fixture(tmp_path);work=tmp_path/'prepared';native=m.materialize(task,tmp_path,work)
    original={str(p):m._sha(p) for p in m.inputs(task,tmp_path)}
    consumed=sdk_stand_in(monkeypatch,work,d['settings'],inside_process=lambda:(work/'user/models.db').write_text('owned DB change'))
    observed=m.native_worker(native,work,tmp_path/'run')
    assert consumed==[str(work/'input/supplied.yoda')]
    assert observed['staged_before_sdk']['user_changes']==observed['staged_before_inference']['user_changes']=={}
    assert observed['staged_after_inference']['user_changes']['models.db']['change']=='changed'
    assert observed['confidence_witness']==m.confidence_witness(raw_point())
    assert original=={str(p):m._sha(p) for p in m.inputs(task,tmp_path)}


def test_full_observer_ending_checkpoint_refuses_scientific_mutation(tmp_path,monkeypatch):
    task,d=fixture(tmp_path);work=tmp_path/'prepared';native=m.materialize(task,tmp_path,work)
    sdk_stand_in(monkeypatch,work,d['settings'],inside_process=lambda:(work/'input/params.dat').write_text('mZp = 2\n'))
    with pytest.raises(ValueError,match='staged scientific'):m.native_worker(native,work,tmp_path/'run')


def test_outer_readback_checks_staged_payload_even_if_originals_unchanged(tmp_path,monkeypatch):
    from ravel.physics import reinterpret_db
    task,d=fixture(tmp_path);out=tmp_path/'out';out.mkdir()
    monkeypatch.setattr(m,'_approved',lambda *args:(tmp_path,{'max_seconds':60}))
    def capture(command,output,document):
        work=out/'contur-work'
        (work/'input/supplied.yoda').write_text('mutated staged YODA; same claimed exposure')
        write(work/'native-observation.json',{'effective_settings':{'effective':document['settings']},'confidence_witness':m.confidence_witness(raw_point())})
        return {'scope':'fake capture, no process'}
    monkeypatch.setattr(reinterpret_db,'execute_native',capture)
    monkeypatch.setattr(contur_import,'decode_database',lambda _:[]) # Reconciliation also remains independently required.
    monkeypatch.setattr(m,'reconcile',lambda *args:[])
    with pytest.raises(ValueError,match='staged scientific'):m.run(task,tmp_path,out)
