from copy import deepcopy
from fractions import Fraction as F
from types import SimpleNamespace as NS
from pathlib import Path
import hashlib,json,math,ast
import pytest
from ravel.physics import regional_expected as e,statistical_construction as r,native_likelihood as n


def fixture(tmp_path,conditional=False):
 p=tmp_path/'source.txt';p.write_text('Explicit synthetic expected background/source law; no measured population.\n')
 def par(name,role,initial,bounds):return dict(name=name,role=role,initial=initial,bounds=bounds,fixed=False,meaning='synthetic',source='s')
 d={'schema_version':1,'model_id':'expected_test','question':'Background Asimov source test','sources':[{'id':'s','path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}],
 'parameters':[par('mu','poi','1',['0','20']),par('beta','rate','1',['1/100','10'])],
 'bins':[{'id':x,'role':role,'observed':v if conditional else None,'observation_id':x,'source':'s'} for x,role,v in [('SR','signal_region',12),('CR','control_region',22)]],
 'terms':[{'id':'bkg','basis':'background','coefficients':['41/4','41/2'],'powers':{'beta':1},'log_response':[['1/10'],['-1/10']],'source':'s'}, {'id':'sig','basis':'bsm','coefficients':['2','3'],'powers':{'mu':1},'log_response':[['0'],['0']],'source':'s'}],
 'auxiliary':{'kind':'supplied_gaussian_factor','names':['theta'],'observed':['1/4'],'factor':[['2']],'eta_bounds':[['-3','3']],'source':'s'},
 'partition':{'kind':'declared_disjoint_poisson_counts','source':'s','statement':'synthetic disjoint Poisson SRCR'},'prediction':{'units':'expected_events','energy':'13TeV','luminosity':'1fb-1','basis':'b+mu*s','scale':'source','domain_statement':'positive','source':'s'},
 'template_statistics':{'kind':'conditional_on_supplied_coefficients','source':'s','statement':'fixed synthetic coefficients'},'assumptions':[{'id':'synthetic','statement':'artificial law only','source':'s','status':'assumed'}],
 'expected_data':{'kind':e.KIND,'conditioning':'fit_observed_background' if conditional else 'supplied_nominal','point':{'mu':'0','beta':'1','ravel_aux_0':'1/2'},'source':'s','statement':'complete synthetic generating state or conditioning start, not postfit data','fit':{'strategy':1,'tolerance':'1/10','max_calls':300,'max_iterations':100,'max_edm':'1/1000'} if conditional else None}}
 return d


def fit():return dict(method='AsymptoticLimits',data='asimov_background',poi='mu',domain=['0','20'],mass=125,seed=789,points=None,minimizer={'strategy':1,'tolerance':.1},fixed_witness_points=['0','1'],reference_quantiles=None)

class Var:
 def __init__(self,name,value,lo=-100,hi=100,fixed=False,unbounded=False):self.name=name;self.value=value;self.lo=lo;self.hi=hi;self.fixed=fixed;self.unbounded=unbounded
 def getVal(self):return self.value
 def setVal(self,v):self.value=float(v)
 def getMin(self):return self.lo
 def getMax(self):return self.hi
 def isConstant(self):return self.fixed
 def setConstant(self,v):self.fixed=v
 def hasMin(self):return not self.unbounded
 def hasMax(self):return not self.unbounded
 def GetName(self):return self.name
 def getError(self):return max(0.,getattr(self,'error',.1))
 def setError(self,x):self.error=x
 def hasError(self):return getattr(self,'error',.1)>=0
 def removeError(self):self.error=-1.
 def hasAsymError(self):return getattr(self,'asym',None) is not None
 def getAsymErrorLo(self):return self.asym[0] if self.hasAsymError() else 0.
 def getAsymErrorHi(self):return self.asym[1] if self.hasAsymError() else 0.
 def setAsymError(self,a,b):self.asym=(a,b)
 def removeAsymError(self):self.asym=None
class Collection(list):
 def find(self,name):return next((v for v in self if v.name==name),None)
 def getSize(self):return len(self)
class Data:
 def __init__(self,w,bins):self.w=w;self.bins=bins;self.rows=[[w.var('n_obs_bin'+b['id']).getVal() for b in bins]]
 def numEntries(self):return len(self.rows)
 def weight(self):return 1.
 def get(self,i):return Collection([Var('n_obs_bin'+b['id'],v) for b,v in zip(self.bins,self.rows[i])])
 def reset(self):self.rows=[]
 def add(self,obs):self.rows.append([v.getVal() for v in obs])
class Workspace:
 def __init__(self,d):
  self.d=d;self.v={p['name']:Var(p['name'],float(F(p['initial'])),*map(lambda x:float(F(x)),p['bounds']),fixed=p['fixed']) for p in d['parameters']}
  self.v['ravel_aux_0']=Var('ravel_aux_0',0.,-3,3)
  self.v['ravel_aux_0_In']=Var('ravel_aux_0_In',0.,fixed=True,unbounded=True)
  for b in d['bins']:self.v['n_obs_bin'+b['id']]=Var('n_obs_bin'+b['id'],0. if b['observed'] is None else b['observed'],0.,math.inf)
 def var(self,name):return self.v.get(name)
 def function(self,name):
  i=int(name.rsplit('_',1)[1]);return NS(getVal=lambda:r.mean_jet(self.d,{k:str(F(self.v[k].value)) for k in r.coordinates(self.d)})['means'][i])

def fake(tmp_path,d):
 w=Workspace(d);data=Data(w,d['bins']);obs=Collection([w.var('n_obs_bin'+b['id']) for b in d['bins']]);mc=NS(GetObservables=lambda:obs)
 calls=[]
 class Mini:
  def __init__(self,nll):calls.append('fit')
  def setErrorLevel(self,x):assert x==.5
  def setStrategy(self,x):pass
  def setEps(self,x):pass
  def setMaxFunctionCalls(self,x):pass
  def setMaxIterations(self,x):pass
  def minimize(self,*args):w.var('beta').setVal(1.1);w.var('ravel_aux_0').setVal(.25);return 0
  def hesse(self):return 0
  def save(self):
   floats=Collection([w.var('beta'),w.var('ravel_aux_0')]);const=Collection([w.var('mu')])
   return NS(status=lambda:0,covQual=lambda:3,edm=lambda:.00001,minNll=lambda:3.,numInvalidNLL=lambda:0,numStatusHistory=lambda:2,statusLabelHistory=lambda i:['Migrad','Hesse'][i],statusCodeHistory=lambda i:0,floatParsFinal=lambda:floats,constPars=lambda:const,covarianceMatrix=lambda:[[.01,0.],[0.,.01]])
 class File:
  def __init__(self,path):self.path=Path(path)
  def WriteTObject(self,obj,name):
   (tmp_path/'raw-fit-written').write_text(name);self.path.write_bytes(b'FAKE RooFitResult no ROOT')
  def Close(self):pass
 root=NS(RooMinimizer=Mini,TFile=NS(Open=lambda path,*args:File(path)))
 return root,w,mc,data,calls


def test_nominal_fractional_counts_auxiliary_and_original_exposure(tmp_path):
 d=fixture(tmp_path);r.validate(d);response=r.response(d);root,w,mc,data,calls=fake(tmp_path,d)
 out=e.prepare(root,w,mc,data,object(),response,tmp_path/'journal.json');e.validate_delivery(out,response)
 assert calls==[] and out['observed_endpoint'] is None
 assert out['generated_counts']['SR']==pytest.approx(10.25*math.exp(.125),rel=2e-15)
 assert out['generated_counts']['CR']==pytest.approx(20.5*math.exp(-.125),rel=2e-15)
 assert out['generated_globals']['ravel_aux_0_In']['value']==.5
 assert out['original_counts']=={'SR':0.,'CR':0.}
 assert out['original_globals']['ravel_aux_0_In']['value']==0.
 assert data.numEntries()==1 and out['final_state']['mu']['constant'] is False
 assert json.loads((tmp_path/'journal.json').read_text())==out


def test_conditional_uses_integer_data_preserves_original_and_fit_result(tmp_path):
 d=fixture(tmp_path,True);root,w,mc,data,calls=fake(tmp_path,d);response=r.response(d)
 out=e.prepare(root,w,mc,data,object(),response,tmp_path/'journal.json');e.validate_delivery(out,response)
 assert calls==['fit'] and (tmp_path/'raw-fit-written').read_text()=='conditioning_fit'
 assert out['original_counts']=={'SR':12.,'CR':22.}
 assert out['generating_state']['beta']['value']==1.1 and out['generated_globals']['ravel_aux_0_In']['value']==.25
 assert out['conditioning_fit']['floating_parameters'][0]['name']=='beta'

@pytest.mark.parametrize('mutation',[
 lambda d:d['expected_data']['point'].pop('beta'),
 lambda d:d['expected_data']['point'].update(mu='1'),
 lambda d:d['expected_data']['point'].update(ravel_aux_0='4'),
 lambda d:d['expected_data'].update(source='missing'),
 lambda d:d['parameters'][0].update(bounds=['-1','20']),
 lambda d:d['terms'][1]['powers'].update(mu=2),
 lambda d:d['terms'][1]['coefficients'].__setitem__(0,'-1'),
 lambda d:d['terms'][1].update(basis='interference'),
 lambda d:d['terms'][1]['powers'].update(theta=1),
 lambda d:d['bins'][0].update(observed=12.3),
 lambda d:d['bins'][0].update(observed=12),
 lambda d:d['expected_data'].update(conditioning='rounded_published_data'),
 lambda d:d['expected_data'].update(fit={'strategy':1}),
 ])
def test_false_expected_premises_refused(tmp_path,mutation):
 d=fixture(tmp_path);mutation(d)
 with pytest.raises(ValueError):r.validate(d)

@pytest.mark.parametrize('bad',[12.5,None,-1,True])
def test_conditional_needs_real_integer_observations(tmp_path,bad):
 d=fixture(tmp_path,True);d['bins'][0]['observed']=bad
 with pytest.raises(ValueError):r.validate(d)

@pytest.mark.parametrize('field,value',[('status',1),('cov_qual',2),('edm',1.),('invalid_nll',1),('migrad_status',4),('hesse_status',4)])
def test_bad_conditioning_diagnostics_refused(tmp_path,field,value):
 d=fixture(tmp_path,True);root,w,mc,data,calls=fake(tmp_path,d);response=r.response(d)
 out=e.prepare(root,w,mc,data,object(),response,tmp_path/'journal.json');out['conditioning_fit'][field]=value
 with pytest.raises(ValueError):e.validate_delivery(out,response)

@pytest.mark.parametrize('mutate',[
 lambda x:x['generated_counts'].update(SR=1.),lambda x:x['dataset_counts'].update(CR=0.),
 lambda x:x['generated_globals']['ravel_aux_0_In'].update(value=0.),
 lambda x:x['generated_globals']['ravel_aux_0_In'].update(has_min=True),
 lambda x:x['generating_state']['beta'].update(value=2.),
 lambda x:x.update(observed_endpoint=3.),lambda x:x.update(coverage_qualified=True),
 lambda x:x['original_counts'].update(SR=2.),
])
def test_raw_source_dataset_state_mismatch_refused(tmp_path,mutate):
 d=fixture(tmp_path);root,w,mc,data,calls=fake(tmp_path,d);response=r.response(d)
 out=e.prepare(root,w,mc,data,object(),response,tmp_path/'journal.json');mutate(out)
 with pytest.raises(ValueError):e.validate_delivery(out,response)


def test_failed_preparation_preserves_native_counts(tmp_path):
 d=fixture(tmp_path);root,w,mc,data,calls=fake(tmp_path,d);data.add=lambda obs:None
 with pytest.raises(ValueError):e.prepare(root,w,mc,data,object(),r.response(d),tmp_path/'journal.json')
 raw=json.loads((tmp_path/'journal.json').read_text());assert raw['status']=='failed' and len(raw['generated_counts'])==2


def test_only_expected_quantiles_and_finite_domain(tmp_path):
 rows=[{'limit':i+1.,'quantileExpected':q} for i,q in enumerate([.025,.16,.5,.84,.975])]
 f=fit();out=n.extract_rows(rows,f)
 with pytest.raises(ValueError,match='crossing evidence'):e.check_limits(out,f)
 with pytest.raises(ValueError):n.extract_rows(rows+[{'limit':2.,'quantileExpected':-1.}],f)
 rows[-1]['limit']=20.
 with pytest.raises(ValueError):e.check_limits(n.extract_rows(rows,f),f)


def test_exact_expected_command_has_no_observed_fit_or_toy_branch(tmp_path):
 d=fixture(tmp_path);cfg={'schema_version':1,'model':{'card':'model.txt'},'fit':fit(),'expected_data':d['expected_data']}
 build,cmd=n.commands(cfg,{x:Path(x) for x in ('combine','text2workspace','python')},tmp_path,has_response=True)
 assert cmd[1]==str(tmp_path/'ravel_expected_workspace.root')
 assert cmd[cmd.index('--run')+1]=='blind' and '--picky' in cmd and '--strictBounds' in cmd and '-t' not in cmd
 assert cmd[cmd.index('--rule')+1]=='CLs' and cmd[cmd.index('--qtilde')+1]=='1'
 cfg.pop('expected_data');_,legacy=n.commands(cfg,{x:Path(x) for x in ('combine','text2workspace','python')},tmp_path,has_response=True)
 assert legacy[legacy.index('-t')+1]=='-1' and '--run' not in legacy


def test_positive_but_signed_source_remains_observed_profile_only(tmp_path):
 d=fixture(tmp_path);d.pop('expected_data')
 for b in d['bins']:b['observed']=3
 d['terms'][1]['coefficients'][0]='-1';r.validate(d)
 with pytest.raises(ValueError):r.write_native_bundle(d,tmp_path/'bad',runtime={},fit=fit(),max_seconds=30)
 assert not (tmp_path/'bad').exists()


def test_explicit_noninteger_expectations_do_not_relax_observed_route(tmp_path):
 d=fixture(tmp_path);d.pop('expected_data');d['bins'][0]['observed']=10.25;d['bins'][1]['observed']=20
 with pytest.raises(ValueError):r.validate(d)


def test_native_probe_still_constructs_same_linked_nll_and_preparation_is_explicit():
 tree=ast.parse(n.NATIVE_PROBE);text=ast.unparse(tree)
 assert 'createNLL(data, cmdlist)' in text and "'--qualify-expected'" in text
 # Preparation selects the regional or source-graph implementation on the explicit source kind.
 prepares=[node for node in ast.walk(tree) if isinstance(node,ast.Call)
           and isinstance(node.func,ast.IfExp)
           and ast.unparse(node.func.orelse)=='module.prepare']
 assert len(prepares)==1
 prepare=prepares[0]
 assert ast.unparse(prepare.func.body)=='module.prepare_source_graph'
 assert ast.unparse(prepare.func.test)=="response.get('kind') == 'native-source-graph/v1'"
 assert [ast.unparse(arg) for arg in prepare.args[:6]]==['ROOT','w','mc','data','nll','response']


def runtime(tmp_path):
 tmp_path.mkdir(parents=True,exist_ok=True)
 def pin(p):return dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
 binary=tmp_path/'tool';binary.write_text('#!/bin/sh\nexit 99\n');binary.chmod(0o755)
 lib=tmp_path/'libHiggsAnalysisCombinedLimit.so';lib.write_bytes(b'synthetic not executable ABI')
 mod=tmp_path/'PhysicsModel.py';mod.write_text('# inert test artifact')
 version=tmp_path/'combine.cpp';version.write_text('std::string combineTagString = "v9.2.1";\nif(datacard == "") {\ncerr << "Missing datacard file" << endl;\ncout << "Usage: combine [options]\\n";\nreturn 1002;\n}\nif (seed == -1) { }\ncombiner.applyOptions(vm);\n')
 return {'tools':{k:pin(binary) for k in ('combine','text2workspace','python')},'transport':{'kind':'local'},'artifacts':[pin(lib),pin(mod)],'environment':{'PATH':'/usr/bin:/bin'},'version_proof':{'kind':'missing_datacard_diagnostic','source':pin(version),'expected_returncode':234},'expected':{'combine_version':'9.2.1','root_version':'6.22/00','cmssw_version':None,'architecture':'x86_64','custom_classes':['RooParametricHist']}}


def test_real_bundle_configuration_ordinary_resource_and_child_parity(tmp_path,monkeypatch):
 import subprocess
 monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:(_ for _ in ()).throw(AssertionError('No child/native process allowed')))
 from ravel.workflow import science,resonance_study
 d=fixture(tmp_path);doc=tmp_path/'law.json';doc.write_text(json.dumps(d));pin={'path':str(doc),'sha256':hashlib.sha256(doc.read_bytes()).hexdigest()}
 result=resonance_study.construct_regional(pin,runtime(tmp_path/'runtime'),fit(),tmp_path/'prepared',base_dir=tmp_path,max_seconds=40)
 assert result['mode']=='native-likelihood' and result['build_or_fit_executed'] is False
 cfg=n._configuration(result['task'],tmp_path)[0]
 assert cfg['expected_data']==d['expected_data'] and cfg['schema_version']==1
 deps=n.inputs(result['task'],tmp_path)
 assert Path(e.__file__) in deps and Path(r.__file__) in deps and doc not in deps # complete supplied construction/source is pinned
 assert n.execution_seconds(result['task'],tmp_path)==40
 assert science.adapter({'mode':'native-likelihood','task':result['task']}) is n
 spec={'mode':'native-likelihood','task':result['task'],'max_seconds':60}
 assert set(science.task_inputs(spec,tmp_path))>=set(deps)
 # Existing observed branch cannot quietly consume nominal-data construction.
 p=Path(result['task']['input']);cfg.pop('expected_data');p.write_text(json.dumps(cfg))
 with pytest.raises(ValueError,match='masquerade'):n._configuration(result['task'],tmp_path)


def test_width_full_four_region_expected_build_and_signed_refusal(tmp_path):
 import expected_only_width_fixture as wf
 from ravel.physics import mass_width_grid as w
 law=wf.law_fixture(tmp_path/'law',n=43,k=2);coord={'mass_GeV':40,'width_over_mass':.3};response=wf.response_fixture(tmp_path/'response',law,coord)
 pars=[law['poi'],*law['transfer']['coefficients'],*law['latent_rates']['central'],*law['latent_rates']['forward']]
 request={'kind':e.KIND,'conditioning':'supplied_nominal','point':{**{p['name']:p['initial'] for p in pars},'ravel_aux_0':'0','ravel_aux_1':'0'},'source':'lawsrc','statement':'Explicit artificial full prefit background law','fit':None};request['point']['strength']='0'
 law['expected_data']=request
 for row in law['regions']:row['observed']=[None]*43
 w.validate_law(law);d=w.construct(law,response,coord);assert len(d['bins'])==172 and len(d['parameters'])==93 and len(r.coordinates(d))==95 and d['expected_data']==request
 means=r.mean_jet(d,request['point'])['means'];assert all(v>0 for v in means)
 assert means[86]==105. and means[0]==pytest.approx(100*13/87+5)
 # No hidden integer substitute is written into construction; only the explicit
 # pre-preparation card scaffold uses zeros and cannot be accepted as a result.
 assert all(b['observed'] is None for b in d['bins'])
 response=wf.response_fixture(tmp_path/'signed',law,coord,signed=True)
 with pytest.raises(ValueError,match='nonlinear'):w.construct(law,response,coord)


def test_width_observed_floats_still_refuse_and_nominal_needs_complete_point(tmp_path):
 import expected_only_width_fixture as wf
 from ravel.physics import mass_width_grid as w
 law=wf.law_fixture(tmp_path/'law')
 law['regions'][0]['observed'][0]=10.4
 with pytest.raises(ValueError):w.validate_law(law)


def test_conditioning_mutable_data_and_fit_population_fail(tmp_path):
 d=fixture(tmp_path,True);root,w,mc,data,calls=fake(tmp_path,d);response=r.response(d)
 out=e.prepare(root,w,mc,data,object(),response,tmp_path/'journal.json')
 for mutation in [lambda x:x['conditioning_counts'].update(SR=999.),lambda x:x['conditioning_fit']['floating_parameters'].pop(),lambda x:x['conditioning_fit']['covariance'][0].pop(),lambda x:x['conditioned_state']['mu'].update(constant=False)]:
  changed=deepcopy(out);mutation(changed)
  with pytest.raises(ValueError):e.validate_delivery(changed,response)


@pytest.mark.parametrize('mutation',[None,'ravel_expected_workspace.root','ravel_expected_preparation.json','ravel_regional_expected.py','ravel_workspace.root'])
def test_full_native_orchestration_retains_preparation_and_expected_only_rows(tmp_path,monkeypatch,mutation):
 """Actual _run orchestration with explicitly fake native process/results only."""
 from expected_crossing_fixture import known_document,roots,setup
 d=known_document(tmp_path);hand=r.write_native_bundle(d,tmp_path/'input',runtime=runtime(tmp_path/'rt'),fit=fit(),max_seconds=40)
 config=n._configuration(hand['task'],tmp_path)[0];response=r.response(d)
 calls=[];workspace_checks=[]
 def process(cmd,cwd,env,log,deadline,**kwargs):
  calls.append((list(cmd),Path(log).name));work=Path(cwd)
  # Tiny inert native output placeholders. No ROOT/compiler/process is loaded.
  if Path(log).name=='workspace-build.log':(work/'ravel_workspace.root').write_bytes(b'fake-source-workspace')
  if Path(log).name=='native-fit.log':(work/'higgsCombine.ravel.AsymptoticLimits.mH125.root').write_bytes(b'fake-quantile-tree')
  if Path(log).name=='combine-version.log':raw=' <<< Combine >>>\n <<< v9.2.1 >>>\nMissing datacard file\nUsage: combine [options]\n'
  elif Path(log).name=='expected-preparation.log':
   root,w,mc,data,_=fake(tmp_path,d);out=e.prepare(root,w,mc,data,object(),response,work/'ravel_expected_preparation.json')
   (work/'ravel_expected_workspace.root').write_bytes(b'fake-generated-workspace')
   raw='RAVEL_NATIVE_PROBE='+json.dumps({'expected_preparation':out})
  elif Path(log).name=='native-result.log':
   if mutation:
    path=work/mutation;path.write_bytes(path.read_bytes()+b'ADVERSE MUTATION')
   raw='RAVEL_NATIVE_RESULT='+json.dumps({'rows':roots(20.25,3.5),'fit_results':[]})
  elif Path(log).name=='expected-crossings.log':
   area=tmp_path/'crossing-fake';area.mkdir();args=setup(area,d,roots(20.25,3.5))
   request=json.loads((work/'ravel_expected_crossing_request.json').read_text());args=(*args[:-1],request)
   crossing=e.qualify_crossings(*args,work/'ravel_expected_crossings.json')
   raw='RAVEL_NATIVE_PROBE='+json.dumps({'expected_crossings':crossing})
  else:raw='RAVEL_NATIVE_PROBE='+json.dumps({'fake':True})
  Path(log).write_text(raw);return raw
 monkeypatch.setattr(n,'_process',process)
 monkeypatch.setattr(n,'_check_probe',lambda *x,**k:None) # separately qualified source checker, no fake runtime qualification claimed
 def check(probe,cfg,resp,prepared=None):
  workspace_checks.append(prepared is not None)
  if prepared:e.validate_delivery(prepared,resp)
  return []
 monkeypatch.setattr(n,'_check_workspace',check)
 result=n.run(hand['task'],tmp_path,tmp_path/'out')
 if mutation:
  assert result['status']=='failed' and 'evidence changed' in result['error']['message']
  assert (tmp_path/'out/native-work'/mutation).read_bytes().endswith(b'ADVERSE MUTATION')
  return
 assert result['status']=='passed',result.get('error')
 assert workspace_checks==[False,True]
 assert [x[1] for x in calls]==['combine-help.log','combine-version.log','native-identity.log','workspace-build.log','workspace-probe.log','expected-preparation.log','expected-workspace-probe.log','native-fit.log','native-result.log','expected-crossings.log']
 assert result['inference']['observed_endpoint'] is None and len(result['inference']['quantiles'])==5
 assert result['expected_data']['original_counts']=={'SR':0.}
 assert 'expected_preparation' in result['commands']
 assert (tmp_path/'out/native-work/ravel_workspace.root').read_bytes()==b'fake-source-workspace'
 assert (tmp_path/'out/native-expected-data.json').is_file()


def test_generated_script_mutation_is_not_rebaselined(tmp_path,monkeypatch):
 # The adapter's ending contract must remain an immutable digest comparison.
 tree=ast.parse(Path(n.__file__).read_text());fn=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='_run')
 text=ast.unparse(fn)
 assert "expected_protected = {str(p): _hash(p) for p in (workspace, native_config, probe_script, response_path, work / 'ravel_regional_expected.py', work / 'ravel_source_response.py')}" in text
 assert 'any((_hash(Path(p)) != h for p, h in expected_protected.items()))' in text


def test_nonfinite_fit_partial_is_raw_and_failed(tmp_path):
 d=fixture(tmp_path,True);root,w,mc,data,calls=fake(tmp_path,d)
 cls=root.RooMinimizer
 class Bad(cls):
  def save(self):
   f=super().save();f.edm=lambda:math.nan;return f
 root.RooMinimizer=Bad
 with pytest.raises(ValueError,match='nonfinite'):e.prepare(root,w,mc,data,object(),r.response(d),tmp_path/'bad.json')
 saved=json.loads((tmp_path/'bad.json').read_text())
 assert saved['status']=='failed' and saved['conditioning_fit']['edm']=={'nonfinite_native_float':'nan'}
 assert (tmp_path/'bad.fit.root').is_file()
 assert saved['conditioning_fit']['raw_result']['sha256']==hashlib.sha256((tmp_path/'bad.fit.root').read_bytes()).hexdigest()
