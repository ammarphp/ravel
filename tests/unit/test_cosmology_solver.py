"""Independent supplied-API controls, no real cosmology engine or native launch."""
from copy import deepcopy
from types import SimpleNamespace as NS
from pathlib import Path
import hashlib,json,math,sys
import pytest
from ravel.physics import cosmology_solver as c
from ravel.workflow import science

def document(engine='class',points=1):
 p={'H0':50.,'omega_b':.022,'omega_cdm':.12,'A_s':2e-9,'n_s':.96,'tau':.05,'T_CMB':2.7255,'YHe':.24,'N_eff':3.046}
 return {'schema_version':1,'engine':engine,'source':'supplied engineering control, no physical computation','profile':'flat-massless-lcdm-linear','points':[{'id':'p'+str(i),'parameters':deepcopy(p)} for i in range(points)],'grid':{'k_h_mpc':[.1,.2],'redshifts':[0.,1.],'background_redshifts':[0.,1.]},'model':None,'components':None,'runtime':{'python':{},'manifest':{}},'trusted_runtime':True,'operation_resources':{'schema_version':1,'kind':'solver','generated_events':0,'solver_evaluations':points,'max_seconds':30},'max_ram_mib':512,'measurement':None}

def api_class(fail=False):
 class Class:
  def __init__(self):self.cleaned=[]
  def set(self,settings):self.settings=settings
  def compute(self,level):
   assert level==['fourier']
   if fail:raise RuntimeError('supplied solver failure')
  def pk_lin(self,k,z):return 8*k+z
  def Hubble(self,z):return (100+z)/c.C_KM_S
  def angular_distance(self,z):return 10*z
  def struct_cleanup(self):self.cleaned.append('struct')
  def empty(self):self.cleaned.append('empty')
 instance=Class()
 return NS(Class=lambda:instance),instance

def api_camb():
 seen={}
 class Params:
  def __init__(self):self.InitPower=NS(set_params=lambda **k:seen.update(initial_power=k))
  def set_cosmology(self,**k):seen['cosmology']=k
  def set_matter_power(self,**k):seen['matter_power']=k
 class Data:
  def get_matter_power_interpolator(self,**k):seen['interpolation']=k;return NS(kmin=.05,kmax=.25,zmin=0.,zmax=2.,P=lambda z,k,grid:2*k+z)
  def hubble_parameter(self,z):return 100+z
  def angular_diameter_distance(self,z):return 10*z
 def solve(p):seen['WantCls']=p.WantCls;seen['nonlinear']=p.NonLinear;return Data()
 return NS(CAMBparams=Params,model=NS(NonLinear_none=0),get_results=solve),seen

def execute(d,api):
 writes=[];v=c.execute_points(d,api,lambda r:writes.append(r));return v,writes

def test_class_unit_witness_and_complete_rectangular_population():
 d=document();api,instance=api_class();v,writes=execute(d,api)
 assert len(v['points'][0]['cells'])==8 and v['uncompleted_points']==[]
 # Independent dimensional conversion: kphysical=(.1 h/Mpc)*.5;
 # source returns 8*.05 Mpc^3, converted by h^3=1/8 => .05 (Mpc/h)^3.
 assert v['points'][0]['cells'][0]['value']==pytest.approx(.05)
 assert v['points'][0]['cells'][4]['value']==100
 assert instance.settings['N_ncdm']==0 and instance.settings['N_ur']==3.046
 assert instance.cleaned==['struct','empty'] and writes[-1]['status']=='passed'
 assert writes[3]['calls'][1]['raw_return']==pytest.approx(.4)

def test_camb_native_parameters_no_cls_massless_linear_units_and_range():
 api,seen=api_camb();v,_=execute(document('camb'),api)
 assert seen['cosmology']['ombh2']==.022 and seen['cosmology']['omch2']==.12
 assert seen['cosmology']['mnu']==0 and seen['cosmology']['num_massive_neutrinos']==0
 assert seen['cosmology']['nnu']==3.046 and seen['WantCls']is False and seen['nonlinear']==0
 assert seen['interpolation']=={'nonlinear':False,'var1':'delta_tot','var2':'delta_tot','hubble_units':True,'k_hunit':True,'extrap_kmax':None}
 assert seen['matter_power']['redshifts']==[1.,0.]
 assert seen['matter_power']['kmax']>.2*.5
 assert v['points'][0]['cells'][0]['unit']=='(Mpc/h)^3'

def test_first_failure_retains_spent_call_all_uncompleted_points_and_cleanup():
 d=document(points=2);api,instance=api_class(True);writes=[]
 with pytest.raises(RuntimeError):c.execute_points(d,api,lambda r:writes.append(r))
 assert writes[-1]['status']=='failed' and writes[-1]['solver_calls_started']==1 and writes[-1]['solver_calls_returned']==0
 assert writes[-1]['uncompleted_points']==['p0','p1'] and writes[-1]['calls'][0]['status']=='failed'
 assert instance.cleaned==['struct','empty']

def cobaya_document():
 d=document('cobaya');d.update(profile='logposterior',grid=None,model={},components={'priors':['0'],'likelihoods':['gaussian'],'derived':['y'],'derived_units':{'y':'1'}});d['points'][0]['parameters']={'x':.2};return d

def cobaya_api(answer):
 seen={}
 class Model:
  parameterization=NS(sampled_params=lambda:{'x':None})
  def logposterior(self,p,**kw):seen.update(parameters=p,arguments=kw);return deepcopy(answer)
  def close(self):seen['closed']=True
 return NS(get_model=lambda cfg,stop_at_error:Model()),seen

def test_cobaya_complete_named_outputs_and_no_cache_finite_clipping():
 api,seen=cobaya_api({'logpost':-4.,'logpriors':{'0':-1.},'loglikes':{'gaussian':-3.},'derived':{'y':2.}})
 d=cobaya_document();v=c.execute_points(d,api,lambda _:None,{'params':{'x':{}},'likelihood':{'gaussian':{}}})
 assert len(v['points'][0]['cells'])==4 and seen['closed']
 assert seen['arguments']==dict(as_dict=True,make_finite=False,return_derived=True,cached=False)
 assert v['points'][0]['cells'][0]['value']==-4.

def test_cobaya_outside_prior_preserves_infinity_and_every_uncomputed_component():
 api,_=cobaya_api({'logpost':-math.inf,'logpriors':{'0':-math.inf},'loglikes':{},'derived':{}})
 v=c.execute_points(cobaya_document(),api,lambda _:None,{})
 cells=v['points'][0]['cells'];assert len(cells)==4
 assert cells[0]['value']=={'nonfinite':'-inf'} and all(x['value']=={'not_computed':'outside_prior'} for x in cells[2:])
 assert v['calls'][0]['raw_return']['logpost']=={'nonfinite':'-inf'}

@pytest.mark.parametrize('answer',[{'logpost':True,'logpriors':{'0':-1.},'loglikes':{'gaussian':-3.},'derived':{'y':2.}}, {'logpost':float('nan'),'logpriors':{'0':-1.},'loglikes':{'gaussian':-3.},'derived':{'y':2.}}, {'logpost':-4.,'logpriors':{'0':-1.},'loglikes':{},'derived':{'y':2.}}])
def test_cobaya_invalid_or_incomplete_return_retained_then_refused(answer):
 api,seen=cobaya_api(answer);writes=[]
 with pytest.raises(ValueError):c.execute_points(cobaya_document(),api,lambda r:writes.append(r),{})
 assert writes[-1]['solver_calls_returned']==1 and writes[-1]['status']=='failed'
 assert writes[-1]['calls'][0]['raw_return']is not None and seen['closed']

@pytest.mark.parametrize('change',[lambda d:d['operation_resources'].update(generated_events=1),lambda d:d['operation_resources'].update(solver_evaluations=2),lambda d:d['grid']['k_h_mpc'].reverse(),lambda d:d['points'][0]['parameters'].update(H0=True),lambda d:d['points'][0]['parameters'].update(mnu=.06),lambda d:d.update(profile='nonlinear')])
def test_wrong_physics_or_resource_contract_refuses_before_api(change):
 d=document();change(d)
 with pytest.raises(ValueError):c.validate_document(d)

@pytest.mark.parametrize('value',[{'external':'module.func'},{'params':{'x':{'value':'lambda y:y'}}},{'sampler':{'mcmc':{}}}])
def test_dynamic_callback_install_sampling_not_the_public_facade(value):
 with pytest.raises(ValueError):c._no_code(value)

def pin(path):return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
def save(path,value):path.write_text(json.dumps(value)+'\n');return pin(path)
def fixture(tmp_path):
 d=document();site=tmp_path/'native-site';site.mkdir();module=site/'classy-stub-source.py';module.write_text('SOURCE ONLY NOT IMPORTED\n')
 manifest={'schema_version':1,'engine':'class','version':'3.4.1','files':[pin(module)],'site_roots':[str(site)],'environment':{}}
 d['runtime']={'python':pin(Path(sys.executable).resolve()),'manifest':save(tmp_path/'runtime.json',manifest)}
 path=tmp_path/'solver.json';save(path,d);return path,d,module

def policy():
 return {'schema_version':1,'policy':{'schema_version':1,'actors':{'proposer':'p','executor':'e','physics_critic':'c','skeptical_verifier':'v','physics_decider':'d'},'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'census','kind':'scientific'}],'claim_scopes':{'cosmology_solver_delivery':{'checks':['integrity','census'],'actions':['delivery','reuse']}}},'correction_contract':{'task_fields':[],'input_slots':[]}}

def test_public_registered_ordinary_plan_whole_inputs_v2_no_approval(tmp_path):
 path,d,module=fixture(tmp_path);pp=tmp_path/'policy.json';save(pp,policy());out=tmp_path/'spec.json'
 c.prepare(path,pp,out,approval_mode='scripted_yes');spec=json.loads(out.read_bytes())
 assert science.adapter(spec)is c and science._new_capability(spec)
 science.plan(tmp_path/'planned',out)
 plan=json.loads((tmp_path/'planned/inputs/science-plan.json').read_bytes())
 assert str(module)in plan['stage_binding']['input_snapshot']
 assert not (tmp_path/'planned/inputs/science-approval.json').exists()
 spec['schema_version']=1;spec.pop('review_policy');save(tmp_path/'old.json',spec)
 with pytest.raises(ValueError):science.plan(tmp_path/'old',tmp_path/'old.json')

def test_public_unapproved_run_refuses_before_transport_or_output(tmp_path,monkeypatch):
 path,d,module=fixture(tmp_path)
 from ravel.physics import reinterpret_db
 monkeypatch.setattr(reinterpret_db,'execute_native',lambda *a:(_ for _ in ()).throw(AssertionError('no native transport')))
 out=tmp_path/'run/outputs/attempt-1/cosmology-solver'
 with pytest.raises((ValueError,FileNotFoundError)):c.run({'input':str(path)},tmp_path,out)
 assert not out.exists()

def test_consumed_document_aba_and_runtime_mutation_refuse(tmp_path,monkeypatch):
 path,d,module=fixture(tmp_path);expected=pin(path)['sha256'];real=c.operation_resources.document_pin
 def changed(p):
  doc=real(p)
  if Path(p)==path:doc['text']=doc['text'].replace('50.0','75.0')
  return doc
 monkeypatch.setattr(c.operation_resources,'document_pin',changed)
 # The delegated pin reader must independently hash the exact consumed buffer.
 with pytest.raises(ValueError):c._read(path,expected)

def test_runtime_source_and_version_before_plan_refuse(tmp_path):
 path,d,module=fixture(tmp_path);module.write_text('CHANGED')
 with pytest.raises(ValueError):c.inputs({'input':str(path)},tmp_path)

def test_complete_result_truncation_counter_and_unit_refuse():
 d=document();api,_=api_class();v,_=execute(d,api);v.update(engine='class',version='3.4.1',operation_resources=d['operation_resources'],physics_validated=False)
 assert c.complete_result(d,v)is v
 for kind in ['truncate','counter','unit','point']:
  changed=deepcopy(v)
  if kind=='truncate':changed['points'][0]['cells'].pop()
  elif kind=='counter':changed['solver_calls_returned']=0
  elif kind=='unit':changed['points'][0]['cells'][0]['unit']='Mpc^3'
  else:changed['points'][0]['parameters']['H0']=70
  with pytest.raises(ValueError):c.complete_result(d,changed)

def posterior_result(d):
 api,_=cobaya_api({'logpost':-4.,'logpriors':{'0':-1.},'loglikes':{'gaussian':-3.},'derived':{'y':2.}})
 v=c.execute_points(d,api,lambda _:None,{})
 v.update(engine=d['engine'],version=c.VERSIONS[d['engine']],operation_resources=d['operation_resources'],physics_validated=False)
 return v

@pytest.mark.parametrize('fault',['truncate','duplicate','unit','uncomputed','nonfinite'])
def test_outer_posterior_full_population_refuses(fault):
 d=cobaya_document();v=posterior_result(d);assert c.complete_result(d,v)is v
 if fault=='truncate':v['points'][0]['cells'].pop()
 elif fault=='duplicate':v['points'][0]['cells'][2]=deepcopy(v['points'][0]['cells'][1])
 elif fault=='unit':v['points'][0]['cells'][-1]['unit']='GeV'
 elif fault=='uncomputed':v['points'][0]['cells'][-1]['value']={'not_computed':'outside_prior'}
 else:v['points'][0]['cells'][-1]['value']={'nonfinite':'-inf'}
 with pytest.raises(ValueError):c.complete_result(d,v)

def measurement_model():
 ids=['late','early'];unit='km/s/Mpc'
 def vector(v):return {'bin_ids':ids[:],'unit':unit,'values':v}
 return {'schema_version':1,'analysis_id':'artificial-correlated-H-control','quantity':{'axes':[{'name':'redshift','unit':'1'}],'bins':[{'id':'early','low':[0.],'high':[.5]},{'id':'late','low':[.5],'high':[1.5]}],'representation':'integrated','normalization':'absolute','unit':unit},'data':vector([99.,101.]),'sm':vector([1.,2.]),'signal':vector([0.,0.]),'experimental_covariance':{'bin_ids':ids[:],'matrix':[[4.,1.],[1.,9.]],'unit':'('+unit+')^2'},'theory_covariance':{'bin_ids':ids[:],'matrix':[[1.,.25],[.25,2.]],'unit':'('+unit+')^2'},'covariance_policy':'independent_theory_sum','overlap':{'policy':'single_measurement'},'constraints':[]}

def bridge_fixture(tmp_path):
 path,d,module=fixture(tmp_path)
 bridge={'model':measurement_model(),'point_id':'p0','quantity':'Hubble','cell_ids':[x['id'] for x in c.linear_cells(d,'p0') if x['quantity']=='Hubble'],'bin_ids':['late','early'],'role':'sm','task':{'schema_version':1,'input':'prospective-new-model.json','inference':'goodness_of_fit','signal_strength':0.}}
 d['measurement']=save(tmp_path/'bridge.json',bridge);save(path,d)
 api,_=api_class();v,_=execute(d,api);v.update(engine='class',version='3.4.1',operation_resources=d['operation_resources'],physics_validated=False)
 return path,d,v,bridge

def test_complete_covariance_bridge_exact_order_units_and_no_inference(tmp_path):
 path,d,v,bridge=bridge_fixture(tmp_path);assert path in c.inputs({'input':str(path)},tmp_path)
 h=c.measurement_handoff(d,v,tmp_path)
 assert h['model']['sm']['values']==[100.,101.]
 assert h['model']['experimental_covariance']==bridge['model']['experimental_covariance']
 assert h['model']['theory_covariance']==bridge['model']['theory_covariance']
 assert h['model']['data']==bridge['model']['data'] and h['model']['signal']==bridge['model']['signal']
 assert h['model']['quantity']==bridge['model']['quantity'] and h['task']==bridge['task']
 assert not h['covariance_changed'] and not h['inference_performed'] and not h['execution_authorized']
 # Deliberately noncanonical bin order is preserved and explicitly mapped;
 # it is never sorted into a mismatched covariance order.
 assert h['model']['sm']['bin_ids']==['late','early']

@pytest.mark.parametrize('fault',['unit','cells','bins','covariance','task','source'])
def test_bridge_scope_complete_population_and_source_refuse(tmp_path,fault):
 path,d,v,b=bridge_fixture(tmp_path)
 if fault=='unit':b['model']['sm']['unit']='Mpc'
 elif fault=='cells':b['cell_ids'].pop()
 elif fault=='bins':b['bin_ids'].reverse()
 elif fault=='covariance':b['model']['experimental_covariance']['matrix']=[[1.,2.],[2.,1.]]
 elif fault=='task':b['task']['inference']='exclusion'
 else:(tmp_path/'bridge.json').write_text('CHANGED');
 if fault!='source':d['measurement']=save(tmp_path/'bridge.json',b);save(path,d)
 with pytest.raises(ValueError):c.inputs({'input':str(path)},tmp_path)

def test_real_adapter_with_supplied_transport_retains_new_ordinary_measurement_task(tmp_path,monkeypatch):
 path,d,v,b=bridge_fixture(tmp_path);rd=tmp_path/'run';out=rd/'outputs/attempt-1/cosmology-solver'
 monkeypatch.setattr(science,'verify_worker',lambda root:{'base_dir':str(tmp_path),'output_directory':'outputs/attempt-1'})
 monkeypatch.setattr(science,'execution_spec',lambda root:{'mode':'cosmology-solver','task':{'input':str(path)}})
 from ravel.physics import reinterpret_db,measurement
 def supplied_transport(command,native,resources):
  assert resources=={'max_seconds':30,'max_ram_mib':512} and command[1:3]==['-I','-B']
  save(native/'native-result.json',v);return {'status':'supplied engineering stand-in; no subprocess'}
 monkeypatch.setattr(reinterpret_db,'execute_native',supplied_transport)
 result=c.run({'input':str(path)},tmp_path,out)
 emitted=json.loads((out/'measurement-task.json').read_bytes());measurement.validate(emitted)
 assert emitted['input']==str(out/'measurement-model.json')
 assert json.loads(Path(emitted['input']).read_bytes())==result['measurement_handoff']['model']
 assert result['generated_events']==0 and not result['physics_validated']

@pytest.mark.parametrize('status',['passed','failed'])
def test_actual_common_worker_serialization_fresh_adapter_dir_no_physics_calls(tmp_path,monkeypatch,status):
 from ravel.physics import science_worker as worker
 rd=tmp_path/'ordinary';rd.mkdir()
 spec={'schema_version':2,'mode':'cosmology-solver','task':{'input':'not-read-in-supplied-result-seam'},'assumptions':['Supplied serializer only; no real solver']}
 monkeypatch.setattr(worker,'verify_worker',lambda _: {'attempt':1,'base_dir':str(tmp_path),'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':{}}})
 monkeypatch.setattr(worker,'execution_spec',lambda _:spec)
 def supplied_result(task,base,out):
  assert out==rd/'outputs/attempt-1/cosmology-solver'
  out.mkdir();save(out/'cosmology-result.json',{'status':status,'physics_validated':False})
  return {'status':status,'physics_validated':False,'limitations':['supplied serializer control only']}
 monkeypatch.setattr(c,'run',supplied_result)
 assert worker.main([str(rd)])==(0 if status=='passed' else 3)
 assert json.loads((rd/'outputs/attempt-1/result.json').read_bytes())['status']==status
 assert json.loads((rd/'outputs/attempt-1/figures.json').read_bytes())['status']=='not_applicable'

def test_no_native_import_before_live_delegation(tmp_path):
 with pytest.raises((ValueError,FileNotFoundError)):c.native_worker(tmp_path/'input.json',tmp_path/'out',tmp_path/'missing-run')

def test_raw_return_persisted_before_conversion_failure():
 api,instance=api_class();api.Class=lambda:instance;instance.pk_lin=lambda k,z:float('nan');writes=[]
 with pytest.raises(ValueError):c.execute_points(document(),api,lambda v:writes.append(v))
 assert writes[-1]['calls'][1]['raw_return']=={'nonfinite':'nan'} and writes[-1]['solver_calls_returned']==1
 assert writes[-1]['status']=='failed' and writes[-1]['uncompleted_points']==['p0']

@pytest.mark.parametrize('engine',['class','camb','cobaya'])
@pytest.mark.parametrize('fault',['value','call_operation','extra_call','raw_return'])
def test_complete_native_raw_return_derivation_and_call_census(engine,fault):
 d=cobaya_document() if engine=='cobaya' else document(engine)
 if engine=='cobaya':v=posterior_result(d)
 else:
  api,_=api_class() if engine=='class' else api_camb();v,_=execute(d,api);v.update(engine=engine,version=c.VERSIONS[engine],operation_resources=d['operation_resources'],physics_validated=False)
 if fault=='value':v['points'][0]['cells'][0]['value']=12345.
 elif fault=='call_operation':v['calls'][0]['operation']='unrelated'
 elif fault=='extra_call':v['calls'].append(deepcopy(v['calls'][-1]))
 elif engine=='cobaya':v['calls'][0]['raw_return']['derived']['y']=99.
 else:v['calls'][1]['raw_return']=99.
 with pytest.raises(ValueError):c.complete_result(d,v)

def test_declared_startup_environment_refuses_deterministic_drift(tmp_path):
 path,d,module=fixture(tmp_path);manifest=json.loads((tmp_path/'runtime.json').read_bytes())
 manifest['environment']={'PATH':'never-the-current-path'};d['runtime']['manifest']=save(tmp_path/'runtime.json',manifest);save(path,d)
 with pytest.raises(ValueError,match='startup environment'):c.inputs({'input':str(path)},tmp_path)

def test_finite_output_populations_refuse_before_solver():
 d=document(points=64)
 with pytest.raises(ValueError,match='cell ceiling'):
  d['grid']['k_h_mpc']=[.01+i*.001 for i in range(256)];c.validate_document(d)
 d=cobaya_document();d['components']['derived']=['x']*257
 with pytest.raises(ValueError):c.validate_document(d)


def test_loaded_native_entry_is_bound_core_not_an_sdk_dependency(tmp_path,monkeypatch):
 path,d,module=fixture(tmp_path);_,_,m,_=c._admission({'input':str(path)},tmp_path)
 monkeypatch.setattr(c,'sys',NS(modules={'__main__':NS(__file__=str(Path(c.__file__).resolve())),'classy':NS(__file__=str(module))}))
 loaded=c.loaded_modules(d,m,tmp_path)
 assert set(loaded)=={'classy'} and loaded['classy']['sha256']==pin(module)['sha256']

@pytest.mark.parametrize('name',['ravel.foreign','__main__'])
def test_loaded_module_name_cannot_hide_foreign_unbound_file(tmp_path,monkeypatch,name):
 path,d,module=fixture(tmp_path);foreign=tmp_path/'not-bound.py';foreign.write_text('unbound source only\n');_,_,m,_=c._admission({'input':str(path)},tmp_path)
 monkeypatch.setattr(c,'sys',NS(modules={name:NS(__file__=str(foreign)),'classy':NS(__file__=str(module))}))
 with pytest.raises(ValueError,match='absent/changed'):c.loaded_modules(d,m,tmp_path)


@pytest.mark.parametrize('kind', ['float64','float32','int64','uint64','zero_dim'])
def test_native_real_numpy_scalar_boundary_only(kind):
 import numpy as np
 value={'float64':np.float64(2),'float32':np.float32(2),'int64':np.int64(2),'uint64':np.uint64(2),'zero_dim':np.asarray(2.,dtype=np.float64)}[kind]
 assert c._native_scalar(value,'getter')==2.
 with pytest.raises(ValueError):c._num(value,'closed JSON parameter')

@pytest.mark.parametrize('kind', ['bool','vector','object','complex','nan','inf'])
def test_native_scalar_invalid_return_retained_then_refused(kind):
 import numpy as np
 value={'bool':np.bool_(True),'vector':np.asarray([1.]),'object':np.asarray(2,dtype=object),'complex':np.complex128(1+2j),'nan':np.float64(float('nan')),'inf':np.float64(float('inf'))}[kind]
 api,instance=api_class();instance.pk_lin=lambda *a:value;writes=[]
 with pytest.raises(ValueError):c.execute_points(document(),api,lambda r:writes.append(r))
 row=writes[-1]['calls'][-1]
 assert row['status']=='returned' and row['raw_return']==c._raw(value)
 assert writes[-1]['status']=='failed' and writes[-1]['solver_calls_returned']==1
 assert writes[-1]['uncompleted_points']==['p0'] and instance.cleaned==['struct','empty']

@pytest.mark.parametrize('limits', [
 {'kmin':0.},{'kmin':.3},{'kmax':0.},{'zmin':-1.},{'zmax':-1.},
 {'kmax':float('nan')},{'zmax':float('inf')},{'kmin':True},{'kmin':None}])
def test_invalid_camb_support_fails_before_all_observable_getters(limits):
 api,_=api_camb();old=api.get_results;queries=[]
 def solve(pars):
  data=old(pars)
  def interpolation(**kw):
   support={'kmin':.1,'kmax':.2,'zmin':0.,'zmax':1.};support.update(limits)
   return NS(**support,P=lambda *a,**kw:queries.append(a))
  data.get_matter_power_interpolator=interpolation
  data.hubble_parameter=lambda *a:queries.append(a)
  data.angular_diameter_distance=lambda *a:queries.append(a)
  return data
 api.get_results=solve;writes=[]
 with pytest.raises(ValueError):c.execute_points(document('camb',points=2),api,lambda r:writes.append(r))
 assert queries==[] and writes[-1]['status']=='failed'
 assert writes[-1]['solver_calls_returned']==1 and writes[-1]['uncompleted_points']==['p0','p1']
 assert writes[-1]['interpolation_support']['p0']['status']=='observed'

@pytest.mark.parametrize('fault', ['missing_point','extra_point','limits','request','units','extrapolation','raw_outside'])
def test_complete_result_revalidates_whole_actual_support(fault):
 d=document('camb',points=2);api,_=api_camb();value,_=execute(d,api)
 value.update(engine='camb',version=c.VERSIONS['camb'],operation_resources=d['operation_resources'],physics_validated=False)
 assert c.complete_result(d,value)['status']=='passed'
 support=value['interpolation_support']
 if fault=='missing_point':del support['p1']
 elif fault=='extra_point':support['foreign']=deepcopy(support['p0'])
 elif fault=='limits':support['p1']['limits']['kmax']=1.
 elif fault=='request':support['p1']['requested']['redshifts']=[0.]
 elif fault=='units':support['p1']['k_unit']='1/Mpc'
 elif fault=='extrapolation':support['p1']['extrapolation']=True
 else:support['p1']['raw_support']['kmax']=.15
 with pytest.raises(ValueError):c.complete_result(d,value)


def test_camb_support_retains_native_zero_dim_bounds_and_single_z():
 import numpy as np
 d=document('camb');d['grid']['redshifts']=[0.]
 limits={k:np.asarray(v)for k,v in {'kmin':.1,'kmax':.2,'zmin':0.,'zmax':0.}.items()}
 row=c._camb_support(d,limits)
 assert row['limits']==row['raw_support']=={'kmin':.1,'kmax':.2,'zmin':0.,'zmax':0.}
 assert row['extrapolation']is False and row['requested']['redshifts']==[0.]
