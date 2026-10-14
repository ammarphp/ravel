"""Pure software controls; optional packages and native execution are never invoked."""
import copy
import hashlib
import json
from pathlib import Path
import pickle
import sys
from types import SimpleNamespace as NS
import pytest
from ravel.physics import eft_toolchain as adapter, eft_toolchain_core as core
from ravel.workflow import science

SETTINGS={'smeft_accuracy':'integrate','qed_order':1,'qcd_order':1,'smeft_matching_order':0,
          'smeft_matchingscale':91.1876,'mb_matchingscale':4.2,'mc_matchingscale':1.3,'parameters':{}}
META={'r':{'real':True},'z':{'tex':'complex operator'},'mixed':{'tex':'generated flavour mixing'}}
class WC:
    def __init__(self,eft,basis,scale,values):self.eft,self.basis,self.scale,self.values=eft,basis,scale,values
    @property
    def dict(self):return {k:core.complex_value(v) for k,v in self.values.items()}
class Wilson:
    initialized=[];transforms=[]
    def __init__(self,values,scale,eft,basis):
        self.wc=WC(eft,basis,scale,{k:{'Re':v.real,'Im':v.imag} for k,v in values.items()})
        self.options={**SETTINGS,'smeft_accuracy':'leadinglog'};self.initialized.append(self)
    def set_option(self,k,v):self.options[k]=v
    def get_option(self,k):return self.options[k]
    @property
    def parameters(self):return {'alpha_s':.118,**self.options['parameters']}
    def match_run(self,scale,eft,basis,sectors):
        self.transforms.append((scale,eft,basis,sectors,copy.deepcopy(self.options)))
        return WC(eft,basis,scale,{'r':self.wc.dict.get('r',0).real,'z':{'Re':2.,'Im':-3.},'mixed':.125})
BASIS=NS(sectors={'all':META},all_wcs=list(META),metadata={'normalization':'control-only'})
API=NS(Wilson=Wilson,wcxf=NS(WC=WC,Basis={(e,'test'):BASIS for e in core.EFTS}),parameters=NS(p={'alpha_s':.118}))
class Obs:
    arguments=['q2'];description='synthetic fixed observable'
    def prediction_par(self,par,w,**args):return par['a']+args['q2']+sum(v.real for v in w.wc.dict.values())
class Cov:
    def compute(self,*a,**kw):return 'sampling would occur'
FLAVIO=NS(default_parameters=NS(get_central_all=lambda:{'a':2.}),Observable={'control':Obs()},
          statistics=NS(likelihood=NS(SMCovariance=type('SMCov',(Cov,),{}),MeasurementCovariance=type('ExCov',(Cov,),{}))))
class Array:
    def __init__(self,v):self.v=v
    def tolist(self):return self.v
class Eigen:
    def min(self):return 0.
NP=NS(asarray=lambda x,dtype=None:Array(x),linalg=NS(eigvalsh=lambda a:Eigen()))
class Likelihood:
    def __init__(self,**kw):
        self.par_dict_default={'a':2.};self._sm_cov_loaded=True
        self.likelihoods={};self.fast_likelihoods={};self.par_dict_sm={'a':2.}
        for group in kw['include_likelihoods']:
            ml=NS(get_measurements=['exact_measurement'],observables=['control'])
            lh=NS(observables=['control'],measurement_likelihood=ml)
            if group.startswith('fast_'):
                suffix='_fix_ckm' if kw['fix_ckm'] else '_'+kw['ckm_scheme']
                with (Path(kw['sm_cov_folder'])/(group+suffix+'.p')).open('rb') as f:sm=pickle.load(f)
                with (Path(kw['exp_cov_folder'])/(group+'.p')).open('rb') as f:ex=pickle.load(f)
                lh.full_measurement_likelihood=ml;lh.sm_covariance=NS(get=lambda force=False,sm=sm:sm['covariance'])
                lh.exp_covariance=NS(get=lambda force=False,ex=ex:(ex['central'],ex['covariance']))
                self.fast_likelihoods[group]=lh
            else:self.likelihoods[group]=lh
        self.log_likelihood_sm={g:-1. for g in kw['include_likelihoods']}
    def _check_sm_cov_loaded(self):
        if not self._sm_cov_loaded:raise ValueError('no cache')
    def parameter_point(self,w):
        w.set_option('parameters',{'Vus':.225})
        scores={g:-.5 for g in self.log_likelihood_sm};scores['global']=sum(scores.values())
        return NS(w=w,par_dict_np={'a':2.,'Vus':.225},log_likelihood_dict=lambda:scores)
SMELLI=NS(GlobalLikelihood=Likelihood)

def cfg():
    return {'schema_version':1,'source':'synthetic control only','runtime':{'python':{'path':'fake','sha256':'0'*64},'site_roots':['site'],'assets':[{'path':'fake','sha256':'0'*64}],'versions':{'wilson':'fake','numpy':'fake','flavio':'fake','smelli':'fake'}},
        'wcxf':{'path':'fake','sha256':'0'*64},'conventions':{'input_kind':'new_physics','scale_unit':'GeV','coefficient_normalization':'native_wcxf_basis','flavour_assumptions':'all declared test coordinates','truncation':'upstream_native_no_additional_linearization','domain':'synthetic','evidence':[{'path':'fake','sha256':'0'*64}]},
        'wilson_options':copy.deepcopy(SETTINGS),'targets':[{'id':'low','eft':'WET','basis':'test','scale':4.8}],
        'observables':[{'id':'obs','name':'control','arguments':{'q2':1.},'unit':'declared_dimensionless','coefficient_source':'low'}],
        'parameter_overrides':{},'smelli':None,'max_seconds':20,'max_ram_mib':512,'max_export_bytes':16*1024*1024}
POINT={'eft':'SMEFT','basis':'test','scale':1000.,'values':{'r':.25,'z':{'Re':1.,'Im':2.}}}
def execute(tmp,c=None,point=None,smelli=SMELLI,cache=None):
    c=c or cfg();point=point or POINT;j=core.Journal(tmp/'progress.json',c['max_export_bytes'])
    data=core.evaluate(c,point,cache,API,FLAVIO,smelli,NP,j,tmp)
    j.retain('completed_quantities',data);j.value['status']='completed';j.save()
    return j.value

def pin(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def save(p,v):p.write_text(json.dumps(v));return pin(p)
def installed(site,name,version,files,requires=()):
    info=site/(name+'-'+version+'.dist-info');info.mkdir(parents=True)
    (info/'METADATA').write_text('Metadata-Version: 2.1\nName: '+name+'\nVersion: '+version+'\n'+''.join('Requires-Dist: '+r+'\n' for r in requires))
    for rel,text in files.items():
        p=site/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    (info/'RECORD').write_text(''.join(rel+',,\n' for rel in [*files,info.name+'/METADATA',info.name+'/RECORD']))

def fixture(tmp,monkeypatch):
    c=cfg();site=tmp/'site'
    installed(site,'wilson','0.0.1',{'wilson/__init__.py':'# fake source: never imported'},['numpy'])
    installed(site,'numpy','0.0.2',{'numpy/__init__.py':'# fake source: never imported'})
    src=site/'wilson/__init__.py'
    api=tmp/'api.json';save(api,{'schema_version':2,'releases':{'wilson':'0.0.1'},'required_package_files':{'wilson':{'__init__.py':pin(src)['sha256']}}})
    monkeypatch.setattr(adapter,'API',api)
    c['runtime']=adapter.runtime_block(Path(sys.executable).resolve(),[site],['wilson'])
    assert c['runtime']['versions']=={'wilson':'0.0.1','numpy':'0.0.2'}
    c['observables']=[]
    c['wcxf']=save(tmp/'point.json',POINT);proof=tmp/'proof';proof.write_text('synthetic');c['conventions']['evidence']=[pin(proof)]
    path=tmp/'config.json';save(path,c)
    return {'config':str(path)},c

def test_complex_full_basis_all_sectors_and_explicit_import_default(tmp_path):
    result=execute(tmp_path);core.delivery_check(result,cfg(),POINT)
    packed=result['result']['completed_quantities']['targets']['low']
    assert packed['complete_values']['z']=={'Re':2.,'Im':-3.}
    assert packed['complete_values']['mixed']['Re']==.125
    assert Wilson.transforms[-1][3]=='all' and Wilson.transforms[-1][4]['smeft_accuracy']=='integrate'
    assert result['result']['input_coefficients']['complete_values']['mixed']=={'Re':0.,'Im':0.}
    assert result['result']['completed_quantities']['predictions'][0]['difference']==2.375

@pytest.mark.parametrize('mutation',['unknown','imaginary_real','nonfinite','bad_scale','unknown_parameter'])
def test_coefficient_and_running_adversaries(tmp_path,mutation):
    point=copy.deepcopy(POINT);c=cfg()
    if mutation=='unknown':point['values']['unknown_flavour']=1.
    if mutation=='imaginary_real':point['values']['r']={'Im':.1}
    if mutation=='nonfinite':point['values']['z']={'Re':float('inf')}
    if mutation=='bad_scale':point['scale']=0
    if mutation=='unknown_parameter':c['wilson_options']['parameters']={'typo':1.}
    with pytest.raises(ValueError):execute(tmp_path,c,point)

@pytest.mark.parametrize('mutation',['unknown_source','duplicate_target','sectors_subset','linearized','wrong_units','missing_option','threshold_order','conflicting_parameter','empty'])
def test_closed_scientific_request(mutation):
    c=cfg()
    if mutation=='unknown_source':c['observables'][0]['coefficient_source']='missing'
    if mutation=='duplicate_target':c['targets']*=2
    if mutation=='sectors_subset':c['targets'][0]['sectors']=['sb']
    if mutation=='linearized':c['conventions']['truncation']='linear_only'
    if mutation=='wrong_units':c['conventions']['scale_unit']='TeV'
    if mutation=='missing_option':c['wilson_options'].pop('qed_order')
    if mutation=='threshold_order':c['wilson_options']['mc_matchingscale']=10.
    if mutation=='conflicting_parameter':c['wilson_options']['parameters']={'a':1.};c['parameter_overrides']={'a':2.}
    if mutation=='empty':c['targets']=[];c['observables']=[]
    with pytest.raises(ValueError):core.config(c)

@pytest.mark.parametrize('mutation',['missing_target','input_changed','generated_mixing_lost','call_missing','missing_observable','invented_uncertainty','authority'])
def test_complete_native_delivery_adversaries(tmp_path,mutation):
    d=execute(tmp_path);r=d['result'];q=r['completed_quantities']
    if mutation=='missing_target':q['targets']={}
    if mutation=='input_changed':r['input_coefficients']['wcxf']['values']['r']={'Re':3.,'Im':0.}
    if mutation=='generated_mixing_lost':q['targets']['low']['complete_values'].pop('mixed')
    if mutation=='call_missing':d['calls'].pop()
    if mutation=='missing_observable':q['predictions']=[]
    if mutation=='invented_uncertainty':q['predictions'][0]['uncertainty']=0.
    if mutation=='authority':d['physics_validated']=True
    with pytest.raises(ValueError):core.delivery_check(d,cfg(),POINT)

def test_sm_return_retained_if_np_fails(tmp_path,monkeypatch):
    original=Obs.prediction_par
    def fault(self,par,w,**kw):
        if w.wc.dict:raise ValueError('supplied fake NP failure')
        return original(self,par,w,**kw)
    monkeypatch.setattr(Obs,'prediction_par',fault)
    with pytest.raises(ValueError,match='fake NP'):execute(tmp_path)
    rows=core.read_json(tmp_path/'progress.json')['calls']
    assert rows[-2]['status']=='returned' and rows[-2]['return']==3.
    assert rows[-1]['status']=='failed' and rows[-1]['identity'].endswith(':NP')

def test_nonfinite_native_return_is_preserved_before_refusal(tmp_path,monkeypatch):
    monkeypatch.setattr(Obs,'prediction_par',lambda *a,**kw:float('inf'))
    with pytest.raises(ValueError):execute(tmp_path)
    rows=core.read_json(tmp_path/'progress.json')['calls']
    assert rows[-1]['return']=={'nonfinite_binary64':'inf'}

def smelli_config():
    c=cfg();c['observables']=[]
    c['smelli']={'coefficient_source':'low','include_likelihoods':['fast_likelihood_test.yaml','likelihood_test.yaml'],
        'fix_ckm':False,'ckm_scheme':'CKMSchemeRmuBtaunuBxlnuDeltaM','covariance_cache':{'path':'cache','sha256':'0'*64}}
    cache={'schema_version':1,'source':'synthetic exact covariance','parameters':{'a':2.},'fix_ckm':False,
        'ckm_scheme':c['smelli']['ckm_scheme'],'groups':{'fast_likelihood_test.yaml':{'observables':['control'],'experimental_central':[1.],
        'experimental_covariance':[[.25]],'sm_covariance':[[.1]]}}}
    return c,cache

def test_smelli_cache_population_delta_and_np_ckm_retained(tmp_path):
    c,cache=smelli_config();d=execute(tmp_path,c,cache=cache);core.delivery_check(d,c,POINT)
    assert d['result']['likelihood']['delta_log_likelihood']['global']==-1.
    assert d['result']['likelihood']['sm_native_reference']['likelihood_test.yaml']==-1.
    assert d['result']['smelli_parameters']['wilson_options_after_ckm']['parameters']['Vus']==.225
    assert d['result']['smelli_initialized_covariances']['fast_likelihood_test.yaml']['sm_covariance']==[[.1]]
    assert len(list((tmp_path/'sm-covariances').glob('*.p')))==1

@pytest.mark.parametrize('mutation',['missing_cache','extra_cache','parameter_mismatch','negative_variance','wrong_observable','dropped_likelihood','sampling'])
def test_smelli_adversaries(tmp_path,mutation):
    c,cache=smelli_config();native=SMELLI
    if mutation=='missing_cache':cache['groups']={}
    if mutation=='extra_cache':cache['groups']['fast_extra.yaml']=copy.deepcopy(next(iter(cache['groups'].values())))
    if mutation=='parameter_mismatch':cache['parameters']['a']=3.
    if mutation=='negative_variance':cache['groups']['fast_likelihood_test.yaml']['sm_covariance']=[[-1.]]
    if mutation=='wrong_observable':cache['groups']['fast_likelihood_test.yaml']['observables']=['different']
    if mutation=='dropped_likelihood':
        class Dropped(Likelihood):
            def __init__(self,**kw):super().__init__(**kw);self.likelihoods={}
        native=NS(GlobalLikelihood=Dropped)
    if mutation=='sampling':
        def sample(**kw):FLAVIO.statistics.likelihood.SMCovariance().compute()
        native=NS(GlobalLikelihood=sample)
    with pytest.raises(ValueError):execute(tmp_path,c,cache=cache,smelli=native)
    assert FLAVIO.statistics.likelihood.SMCovariance().compute()=='sampling would occur'

def test_duplicate_and_aliased_json(tmp_path):
    p=tmp_path/'input';p.write_text('{"a":1,"a":2}')
    with pytest.raises(ValueError,match='duplicate'):core.read_json(p)
    link=tmp_path/'alias';link.symlink_to(p)
    with pytest.raises(ValueError,match='aliased'):core.read_json(link)
    p.write_bytes(b'x'*20)
    with pytest.raises(ValueError):core.read_json(p,10)

def test_ordinary_route_and_no_optional_imports():
    assert science.adapter({'mode':'eft-toolchain','task':{'config':'x'}}) is adapter
    assert science._new_capability({'mode':'eft-toolchain','task':{'config':'x'}})
    assert not {'wilson','flavio','smelli','torch'} & set(sys.modules)
    with pytest.raises(ValueError):adapter.validate_scope({'schema_version':1})

def test_inputs_real_census_extra_member_and_source_mutation(tmp_path,monkeypatch):
    task,c=fixture(tmp_path,monkeypatch);assert Path(c['wcxf']['path']) in adapter.inputs(task,tmp_path)
    (tmp_path/'site/unrelated.py').write_text('outside every admitted distribution');adapter.inputs(task,tmp_path)
    extra=tmp_path/'site/wilson/extra';extra.write_text('unexpected')
    with pytest.raises(ValueError,match='census'):adapter.inputs(task,tmp_path)
    extra.unlink();(tmp_path/'site/wilson/__init__.py').write_text('changed')
    with pytest.raises(ValueError):adapter.inputs(task,tmp_path)

def fake_native(command,out,c):
    assert command[1:3]==['-I','-B'];req=core.read_json(out/'request.json')
    execute(out,c,req['point']);(out/'native-stdout.log').write_text('fake native only')
    return {'returncode':0,'control_only':True}

def test_actual_adapter_mocked_native_success_and_no_reuse(tmp_path,monkeypatch):
    task,c=fixture(tmp_path,monkeypatch);out=tmp_path/'output'
    monkeypatch.setattr(adapter,'approved',lambda *a:{'max_seconds':30})
    from ravel.physics import reinterpret_db
    monkeypatch.setattr(reinterpret_db,'execute_native',fake_native)
    result=adapter.run(task,tmp_path,out)
    assert result['status']=='passed' and result['numerical_qualification']=='unknown'
    with pytest.raises(FileExistsError):adapter.run(task,tmp_path,out)

@pytest.mark.parametrize('mutation',['partial_failure','missing_population','runtime_added','input_ABA'])
def test_adapter_failure_preserves_returns(tmp_path,monkeypatch,mutation):
    task,c=fixture(tmp_path,monkeypatch);out=tmp_path/'output'
    monkeypatch.setattr(adapter,'approved',lambda *a:{'max_seconds':30})
    from ravel.physics import reinterpret_db
    def fault(command,native,c):
        receipt=fake_native(command,native,c)
        if mutation=='partial_failure':raise ValueError('fake execution failure')
        if mutation=='missing_population':
            d=core.read_json(native/'progress.json');d['result']['completed_quantities']['targets']={};core.write_json(native/'progress.json',d)
        if mutation=='runtime_added':(tmp_path/'site/numpy/unplanned').write_text('extra')
        if mutation=='input_ABA':
            p=Path(c['wcxf']['path']);raw=p.read_bytes();p.unlink();p.write_bytes(raw)
        return receipt
    monkeypatch.setattr(reinterpret_db,'execute_native',fault)
    r=adapter.run(task,tmp_path,out)
    assert r['status']=='failed' and (out/'eft-native/progress.json').exists() and (out/'eft-raw-census.json').exists()

def test_absent_approval_refuses_before_output(tmp_path,monkeypatch):
    task,c=fixture(tmp_path,monkeypatch);out=tmp_path/'output'
    with pytest.raises(ValueError,match='approved'):adapter.run(task,tmp_path,out)
    assert not out.exists()

def test_host_source_context_exact_inputs_no_runtime_calls(tmp_path,monkeypatch):
    from ravel.workflow.agent_host import AgentHost,HostFailure
    task,c=fixture(tmp_path,monkeypatch);rp=save(tmp_path/'task.json',task)
    pins=[{'id':'task',**rp},*[{'id':'p'+str(i),**pin(p)} for i,p in enumerate(adapter.context_inputs(task,tmp_path))]]
    node={'id':'context','kind':'tool','role':'designer','depends_on':[],'inputs':pins,'packet':None,'action':'eft-toolchain-context','parameters':{'request_input':'task'},'max_attempts':1}
    host=AgentHost(api_key='not-used',bound_roots=[str(tmp_path)])
    control=NS(cancelled=lambda:False,call=lambda action,kind,request,operation:operation())
    value=host.execute(node,{'request_id':'pure','packet':None,'input_artifacts':pins},control)
    assert value['value']['mode']=='eft-toolchain' and value['value']['runtime_declaration']['actual_runtime_preflight']=='not_performed_by_context'
    node['inputs']=pins[:-1]
    with pytest.raises(HostFailure):host.execute(node,{'request_id':'pure','packet':None,'input_artifacts':pins[:-1]},control)


def test_worker_optimized_refusal_precedes_optional_imports(monkeypatch):
    from ravel.physics import eft_toolchain_worker as worker
    monkeypatch.setattr(worker.sys,'flags',NS(optimize=1))
    with pytest.raises(ValueError,match='optimized'):worker.main(['never-read'])
    assert not {'wilson','flavio','smelli'} & set(sys.modules)

def test_worker_import_custody_and_partial_unknown_refusal(tmp_path,monkeypatch):
    from ravel.physics import eft_toolchain_worker as worker
    path=tmp_path/'observed.py';path.write_text('# synthetic observed import')
    module=NS(__file__=str(path))
    monkeypatch.setattr(worker.sys,'modules',{'synthetic':module})
    request={'sites':[str(tmp_path)],'runtime_assets':{str(path):pin(path)['sha256']},'selected_files':{}}
    assert worker.imports(request)['synthetic']['path']==str(path)
    request['runtime_assets']={}
    with pytest.raises(ValueError,match='unadmitted'):worker.imports(request)

@pytest.mark.parametrize('field',['targets','predictions','likelihood'])
def test_duplicate_retained_records_are_bound(tmp_path,field):
    c,cache=smelli_config() if field=='likelihood' else (cfg(),None)
    d=execute(tmp_path,c,cache=cache)
    # JSON roundtrip removes Python object aliasing just as the real delivery does.
    d=json.loads(json.dumps(d));d['result'][field]={} if field!='predictions' else []
    with pytest.raises(ValueError,match='retained'):core.delivery_check(d,c,POINT)

@pytest.mark.parametrize('which',['target_return','sm_return','np_return','baseline_return','delta_return','missing_order','duplicate_order','wrong_semantics'])
def test_literal_return_and_reduction_adversaries(tmp_path,which):
    c,cache=smelli_config() if which not in ('target_return','sm_return','np_return') else (cfg(),None)
    d=json.loads(json.dumps(execute(tmp_path,c,cache=cache)))
    by={r['identity']:r for r in d['calls']}
    if which=='target_return':by['match_run:low']['return']['values']['z']={'Re':900.,'Im':-3.}
    if which=='sm_return':by['observable:obs:SM']['return']+=1.
    if which=='np_return':by['observable:obs:NP']['return']+=1.
    if which=='baseline_return':by['smelli:SM_reference']['return']['likelihood_test.yaml']=-11.
    if which=='delta_return':by['smelli:NP_minus_SM']['return']['likelihood_test.yaml']=-11.
    if which=='missing_order':by['smelli:NP_minus_SM'].pop('return_key_order')
    if which=='duplicate_order':by['smelli:NP_minus_SM']['return_key_order']=['likelihood_test.yaml','likelihood_test.yaml','global']
    if which=='wrong_semantics':by['smelli:NP_minus_SM']['sum_semantics']['python_major_minor']=[3,11]
    with pytest.raises(ValueError):core.delivery_check(d,c,POINT)


def test_native_dictionary_order_survives_json_sorting(tmp_path):
    c,cache=smelli_config();c['smelli']['include_likelihoods'].reverse()
    d=execute(tmp_path,c,cache=cache)
    row=d['calls'][-1]
    assert row['return_key_order']==['likelihood_test.yaml','fast_likelihood_test.yaml','global']
    loaded=core.read_json(tmp_path/'progress.json')
    assert list(loaded['calls'][-1]['return'])==sorted(row['return'])
    assert loaded['calls'][-1]['return_key_order']==row['return_key_order']
    core.delivery_check(loaded,c,POINT)


def test_global_inconsistency_refuses_even_when_every_duplicate_is_mutated(tmp_path):
    c,cache=smelli_config();d=json.loads(json.dumps(execute(tmp_path,c,cache=cache)))
    d['calls'][-1]['return']['global']=12.
    d['result']['likelihood']['delta_log_likelihood']['global']=12.
    d['result']['completed_quantities']['likelihood']['delta_log_likelihood']['global']=12.
    with pytest.raises(ValueError,match='ordered component sum'):core.delivery_check(d,c,POINT)


def test_literal_explicit_zero_kept_and_all_omitted_coordinates_zero_filled(tmp_path,monkeypatch):
    monkeypatch.setattr(Wilson,'match_run',lambda self,scale,eft,basis,sectors:WC(eft,basis,scale,{'r':0.}))
    d=execute(tmp_path);core.delivery_check(d,cfg(),POINT)
    packed=d['result']['completed_quantities']['targets']['low']
    assert set(packed['wcxf']['values'])=={'r'} and packed['complete_values']['z']=={'Re':0.,'Im':0.}
