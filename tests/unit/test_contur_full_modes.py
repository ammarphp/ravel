"""Source law and file-only/inert transport controls, never Contur inference."""
import ast
from copy import deepcopy
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import pytest
from ravel.physics import contur_import as c,contur_yoda as m
from ravel.workflow import science
import test_contur_yoda as old

def local_input(variable):
    """A local input named by an environment variable; a test that needs it skips without it.
    RAVEL_CONTUR_SOURCE: the original Contur source tree; RAVEL_CONTUR_PREVIOUS_PACKAGE: a previous
    Ravel package tree; RAVEL_CONTUR_REVIEW_SPECIFICATION: a prepared science specification."""
    value=os.environ.get(variable)
    if not value or not Path(value).exists():
        pytest.skip(f'set {variable} to the local input this test reads')
    return Path(value)
def R():return local_input('RAVEL_CONTUR_SOURCE')
def L():return local_input('RAVEL_CONTUR_PREVIOUS_PACKAGE')

@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    import os,subprocess
    def refuse(*a,**k):raise AssertionError('no external/native/scientific calls')
    for n in ('Popen','run','call','check_call','check_output'):monkeypatch.setattr(subprocess,n,refuse)
    monkeypatch.setattr(os,'system',refuse)

def p(path):return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
def source_input(tmp_path,name,version=2):
    d={'schema_version':version,'database':p(R()/'tests/sources'/name),
       'source':{'version':c.VERSION,'commit':c.COMMIT},
       'modes':list(c.FULL_MODES if version==2 else c.MODES),
       'run_selection':{'policy':'latest_id_per_point_and_stat_type'},
       'scope':'Source/file-only original result transport, no inference'}
    d['source'].update({k:p(R()/v) for k,v in m.SOURCE_ROLES.items()})
    path=tmp_path/'input.json';path.write_text(json.dumps(d)+'\n')
    return {'schema_version':1,'input':str(path)},d
def full_settings():
    s=old.requested();s['stat_types']=list(c.FULL_MODES);return s
def full_point():
    return SimpleNamespace(full_likelihood_results={k:{'CLs':.95} for k in c.FULL_MODES},
        sorted_blocks_results={k:{'FIRST':{'CLs':.97},'SECOND':{'CLs':.97},'OTHER':{'CLs':.7}} for k in c.FULL_MODES})
def db(path,yoda,modes=c.FULL_MODES):
    with sqlite3.connect(path) as q:
        for t,cols in c.REQUIRED_COLUMNS.items():
            q.execute('CREATE TABLE '+t+' ('+','.join(k+' '+('TEXT' if k in {'run_point','yoda_files','name','stat_type','addition_argument','pool_name','histos'} else 'INTEGER' if k in {'id','model_id','model_point_id','run_id','map_id','events_num'} else 'DOUBLE') for k in cols)+')')
        q.execute('INSERT INTO model_point VALUES (1,1,?,?)',('0000',repr([str(yoda)])))
        q.executemany('INSERT INTO parameter_value VALUES (1,?,?)',[('mZp',1000.),('cotH',1.5)])
        for i,mode in enumerate(modes,1):
            q.execute('INSERT INTO run VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(i,1,1,17,mode,.95,None,2.,None,None,None,'SUPPLIED INERT RETURN'))
            for j,(name,v) in enumerate([('FIRST',.97),('SECOND',.97),('OTHER',.7)],1):
                q.execute('INSERT INTO exclusions VALUES (?,?,?,?,?,?,?,?,?,?,?)',(10*i+j,i,name,mode,v,'/'+name,None,2.,None,None,None))

def test_original_four_mode_entire_database_raw_rows_and_csv(tmp_path):
    task,d=source_input(tmp_path,'single_results.db')
    result=c.run(task,tmp_path,tmp_path/'result')
    point=result['points'][0];assert [r['raw']['stat_type'] for r in point['runs']]==list(c.FULL_MODES)
    with sqlite3.connect(R()/'tests/sources/single_results.db') as q:
        q.row_factory=sqlite3.Row
        raw={r['stat_type']:dict(r) for r in q.execute('SELECT * FROM run')}
        pools={r['id']:[dict(x) for x in q.execute('SELECT * FROM exclusions WHERE run_id=?',(r['id'],))] for r in q.execute('SELECT * FROM run')}
    for r in point['runs']:
        assert r['raw']==raw[r['raw']['stat_type']] and r['pools']==pools[r['raw']['id']]
        assert r['conventional_cls_complement']==1-r['raw']['combined_exclusion']
    assert result['mode_population']==list(c.FULL_MODES)
    assert result['fresh_inference'] is False and result['physics_validated'] is False
    csvrows=list(csv.DictReader(io.StringIO((tmp_path/'result/native-columns.csv').read_text())))
    assert len(csvrows)==1 and all('CL'+k in csvrows[0] for k in c.FULL_MODES)

@pytest.mark.parametrize('name',['contur_run.db','spey_results.db'])
def test_real_old_three_grid_behavior_matches_original_source(tmp_path,name):
    spec=importlib.util.spec_from_file_location('ravel.physics.legacy_contur_import',L()/'src/ravel/physics/contur_import.py')
    legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    path=R()/'tests/sources'/name
    a=c.decode_database(path);b=legacy.decode_database(path)
    assert a==b and c.export_csv(a)==legacy.export_csv(b)
    task,d=source_input(tmp_path,name,1);result=c.run(task,tmp_path,tmp_path/'result')
    assert 'mode_population' not in result and result['points']==a

@pytest.mark.parametrize('modes',[['SMBG','EXP','HLEXP'],['DATABG','EXP','SMBG','HLEXP'],['DATABG','SMBG','EXP','EXP'],['DATABG','SMBG','EXP','HLEXP','UNKNOWN']])
def test_explicit_new_profile_no_subset_order_duplicate_unknown(tmp_path,modes):
    _,d=source_input(tmp_path,'single_results.db');d['modes']=modes
    with pytest.raises(ValueError):c._contract(d)

@pytest.mark.parametrize('modes',[c.MODES,('DATABG','SMBG','EXP'),(*c.FULL_MODES,'UNKNOWN')])
def test_requested_mode_population_database_mismatch(tmp_path,modes):
    path=tmp_path/'db.sqlite';db(path,tmp_path/'input.yoda',modes)
    with pytest.raises(ValueError):c.decode_database(path,modes=c.FULL_MODES)
    with pytest.raises(ValueError):c.decode_database(R()/'tests/sources/single_results.db')

def test_native_cli_source_body_and_effective_configuration():
    s=full_settings();d={'schema_version':2,'settings':s,'yoda':{'path':'supplied.yoda'}}
    args=m.arguments(d,Path('/owned'));assert args.count('--databg')==1 and '--nomultip' in args
    cfg=SimpleNamespace(**deepcopy(s));state=m.effective_state(cfg,schema_version=2)
    assert m.check_effective(s,state,schema_version=2)['effective']['stat_types']==list(c.FULL_MODES)
    source=(R()/'src/contur/run/arg_utils.py').read_text();tree=ast.parse(source)
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='setup_stat_types')
    env={'cfg':SimpleNamespace(),'const':SimpleNamespace(SMBG='SMBG',EXPECTED='EXP',HLEXPECTED='HLEXP',DATABG='DATABG')}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<exact primary setup_stat_types>','exec'),env)
    env['setup_stat_types']({'DATABG':True});assert env['cfg'].stat_types==s['stat_types']
    env['setup_stat_types']({'DATABG':False});assert env['cfg'].stat_types==list(c.MODES)
    bad=deepcopy(state);bad['stat_types']=list(c.MODES)
    with pytest.raises(ValueError):m.check_effective(s,bad,schema_version=2)
    with pytest.raises(ValueError):m.settings(s)

@pytest.mark.parametrize('kind',['missing','unknown','None','zero'])
def test_native_full_confidence_keys_and_missing_values(kind):
    q=full_point()
    if kind=='missing':q.full_likelihood_results.pop('DATABG')
    elif kind=='unknown':q.sorted_blocks_results['UNKNOWN']={}
    elif kind=='None':q.full_likelihood_results['DATABG']['CLs']=None
    else:q.full_likelihood_results['DATABG']['CLs']=0
    if kind=='zero':assert m.confidence_witness(q,modes=c.FULL_MODES)['DATABG']['combined']==0
    else:
        with pytest.raises(ValueError):m.confidence_witness(q,modes=c.FULL_MODES)

def test_all_four_raw_native_reconcile_and_none_diagnostics(tmp_path):
    y=tmp_path/'supplied.yoda';path=tmp_path/'db.sqlite';db(path,y)
    points=c.decode_database(path,modes=c.FULL_MODES)
    doc={'schema_version':2,'settings':full_settings(),'parameter_values':{'mZp':1000.,'cotH':1.5},'expected_events':17}
    witness=m.confidence_witness(full_point(),modes=c.FULL_MODES)
    assert m.reconcile(points,doc,y,witness)==points
    assert all(r['raw']['nll'] is None and r['raw']['mu_hat'] is None for r in points[0]['runs'])
    for mode in c.FULL_MODES:
        bad=deepcopy(witness);bad.pop(mode)
        with pytest.raises(ValueError):m.reconcile(points,doc,y,bad)

@pytest.mark.parametrize('target',['cached-contur-results.json','native-columns.csv'])
def test_generated_delivery_mutation_after_write_refuses(tmp_path,monkeypatch,target):
    task,_=source_input(tmp_path,'single_results.db');out=tmp_path/'result'
    original=Path.write_bytes
    def altered(self,data):
        answer=original(self,data)
        if self==out/'native-columns.csv':
            q=out/target;original(q,q.read_bytes()+b'CORRUPTION')
        return answer
    monkeypatch.setattr(Path,'write_bytes',altered)
    with pytest.raises(ValueError,match='delivery bytes'):c.run(task,tmp_path,out)

def test_full_public_native_entry_observer_inert_sdk(tmp_path,monkeypatch):
    task,d=old.fixture(tmp_path);d['schema_version']=2;d['settings']=full_settings();old.write(Path(task['input']),d)
    work=tmp_path/'prepared';native=m.materialize(task,tmp_path,work)
    monkeypatch.setattr(old,'raw_point',full_point)
    consumed=old.sdk_stand_in(monkeypatch,work,d['settings'])
    result=m.native_worker(native,work,tmp_path/'run')
    assert consumed==[str(work/'input/supplied.yoda')]
    assert list(result['confidence_witness'])==list(c.FULL_MODES)
    assert result['effective_settings']['effective']['stat_types']==list(c.FULL_MODES)

def test_native_run_full_readback_and_existing_report_inert_transport(tmp_path,monkeypatch):
    from ravel.physics import reinterpret_db
    task,d=old.fixture(tmp_path);d['schema_version']=2;d['settings']=full_settings();old.write(Path(task['input']),d)
    out=tmp_path/'result';monkeypatch.setattr(m,'_approved',lambda *a:(tmp_path,{'max_seconds':100}))
    calls=[]
    def fake(command,output,document):
        calls.append(command);work=out/'contur-work';native=work/'native-output';native.mkdir()
        db(native/'results.db',work/'input/supplied.yoda')
        old.write(work/'native-observation.json',{'effective_settings':{'effective':document['settings']},
          'confidence_witness':m.confidence_witness(full_point(),modes=c.FULL_MODES)})
        return {'returncode':0,'scope':'supplied inert return only; no native process'}
    monkeypatch.setattr(reinterpret_db,'execute_native',fake)
    result=m.run(task,tmp_path,out)
    assert len(calls)==1 and result['mode_population']==list(c.FULL_MODES)
    assert [r['raw']['stat_type'] for r in result['points'][0]['runs']]==list(c.FULL_MODES)
    from ravel.plotting.science_figures import render
    report=render({'mode':'contur-yoda','task':task},result,tmp_path,out)
    assert report['tables'][0]['files']==['native-columns.csv','contur-results.json']

def test_full_native_load_actual_science_adapter_and_schema_refusals(tmp_path):
    task,d=old.fixture(tmp_path);d['schema_version']=2;d['settings']=full_settings();old.write(Path(task['input']),d)
    assert m._load(task,tmp_path)[1]['schema_version']==2
    assert science.adapter({'mode':'contur-yoda','task':task}) is m
    d['schema_version']=1;old.write(Path(task['input']),d)
    with pytest.raises(ValueError):m._load(task,tmp_path)


@pytest.mark.parametrize('kind',['input','semantic'])
def test_cached_final_bound_input_drift_refuses(tmp_path,monkeypatch,kind):
    task,d=source_input(tmp_path,'single_results.db')
    # Copy only a small semantic file. Original third-party input stays read-only.
    semantic=tmp_path/'semantic.py'
    semantic.write_bytes(Path(d['source']['confidence_semantics']['path']).read_bytes())
    d['source']['confidence_semantics']=p(semantic);old.write(Path(task['input']),d)
    original=c.full_mode_delivery
    def altered(*a,**k):
        answer=original(*a,**k)
        target=Path(task['input']) if kind=='input' else semantic
        target.write_bytes(target.read_bytes()+b'\n')
        return answer
    monkeypatch.setattr(c,'full_mode_delivery',altered)
    with pytest.raises(ValueError,match='changed'):c.run(task,tmp_path,tmp_path/'out')

@pytest.mark.parametrize('target',['contur-results.json','native-columns.csv'])
def test_native_profile_delivery_exact_bytes_refuse(tmp_path,monkeypatch,target):
    out=tmp_path/'out';out.mkdir();path=tmp_path/'db.sqlite';db(path,tmp_path/'y.yoda')
    points=c.decode_database(path,modes=c.FULL_MODES)
    original=Path.write_bytes
    def altered(self,data):
        answer=original(self,data)
        if self==out/'native-columns.csv':
            q=out/target;original(q,q.read_bytes()+b'foreign')
        return answer
    monkeypatch.setattr(Path,'write_bytes',altered)
    with pytest.raises(ValueError,match='delivery bytes'):
        c.full_mode_delivery(out,'contur-results.json',{'status':'supplied inert result'},points)


@pytest.mark.parametrize('kind',['digest','path'])
def test_persistent_between_admission_and_consumption_pin_drift_refuses(tmp_path,monkeypatch,kind):
    task,d=source_input(tmp_path,'single_results.db');original=c._load;calls=[]
    other=tmp_path/'other.py';other.write_text('foreign semantic source')
    def altered(path):
        calls.append(path)
        if len(calls)==2:
            changed=deepcopy(d)
            if kind=='digest':changed['source']['confidence_semantics']['sha256']='0'*64
            else:changed['source']['confidence_semantics']=p(other)
            old.write(Path(task['input']),changed)
        return original(path)
    monkeypatch.setattr(c,'_load',altered)
    with pytest.raises(ValueError,match='identities differ'):c.run(task,tmp_path,tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_actual_full_profile_prepare_ordinary_unapproved_specification(tmp_path):
    task,d=old.fixture(tmp_path);d['schema_version']=2;d['settings']=full_settings();old.write(Path(task['input']),d)
    reference=local_input('RAVEL_CONTUR_REVIEW_SPECIFICATION')
    policy=json.loads(reference.read_text())['review_policy'];old.write(tmp_path/'policy.json',policy)
    prepared=m.prepare(task['input'],tmp_path/'policy.json',tmp_path/'science.json')
    assert prepared['schema_version']==2 and prepared['mode']=='contur-yoda'
    assert prepared['task']==task and prepared['max_attempts']==1
    assert prepared['max_seconds']==60 and prepared['review_policy']['policy']['max_redos']==0
    assert science.adapter(prepared) is m
    assert json.loads((tmp_path/'science.json').read_text())==prepared
    assert not (tmp_path/'plan.json').exists()
