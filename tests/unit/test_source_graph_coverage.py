"""Source-only end-to-end engineering controls. Every engine/role is explicit inert fake."""
import ast,copy,hashlib,itertools,json,math
from pathlib import Path
from types import SimpleNamespace as NS
from fractions import Fraction as F
import pytest
from ravel.physics import native_statistical_construction as g,regional_expected as e,native_likelihood as n
from ravel.workflow import science
from source_graph_coverage_fixture import fixture,pin,structural_fixture
from source_graph_coverage_fixture import Var,Collection,Data


def recipe(tmp_path,monkeypatch,*,population=False,expected=True):
 d,_=fixture(tmp_path,monkeypatch,population=population);d['schema_version']=2
 for c in d['cells']:
  c['observables'].append({'name':'angleObs','bounds':['-1','2'],'unit':'dimensionless','member':'coordinate_source'})
  for node in c['nodes']:
   if node['kind']=='template':
    t=node['template'];vals=t['values'];t.pop('observable');t.pop('edges');t.pop('values')
    t.update(axes=[{'observable':'massObs','edges':['1','2','4']},{'observable':'angleObs','edges':['-1','0','2']}],values=[{'indices':[i,j],'integral':str(F(vals[i])*F(j+1,3))}for i,j in itertools.product(range(2),repeat=2)])
    node['depends_on']=['massObs','angleObs']
   elif node['name']=='interference':node['depends_on']=['massObs','angleObs','slope'];node['factory']='expr::interference("@0*@1*@2",massObs,angleObs,slope)'
  for t in c['components']:
   windows=t.pop('bin_windows');t.pop('observable');t['observables']=['massObs','angleObs'];t['bin_windows']=[{'massObs':w,'angleObs':['-1','2']}for w in windows]
  c['integration'].update(policy='ROOT6.22-joint-original-source-relative-policy',max_eval_2d=1000,max_eval_3d=10000,max_eval_nd=100000,max_warn=10,max_template_cells=64)
  if expected:
   c['expected_data']={'kind':'source-graph-asimov/v1','conditioning':'supplied_nominal','point':{p['name']:p['initial']for p in c['law']['parameters']+c['parameters']},'source':c['law']['sources'][0]['id'],'statement':'Explicit synthetic full generating point, not physics evidence','fit':None}
   c['expected_data']['point'].update({f'ravel_aux_{i}':'1/4'for i in range(len(c['law']['auxiliary']['names']))})
   c['fit']['data']='source_asimov'
   for b in c['law']['bins']:b['observed']=None
 rebind(d,tmp_path);return d


def rebind(d,tmp_path):
 facts={f['path']:f for f in d['source_capsule']['files']}
 for node in d['cells'][0]['nodes']:
  if node['kind']=='template':
   t=node['template'];p=Path(d['source_capsule']['root'])/t['source_path'];p.write_bytes(g.encoded({k:t[k]for k in ('axes','values','semantics')}));facts[t['source_path']]['sha256']=pin(p)['sha256']
 subject=Path(d['review']['subject']['path']);subject.write_bytes(g.subject(d));d['review']['subject']=pin(subject)


def test_complete_16_cell_joint_expected_constructor_and_ordinary_native_inputs(tmp_path,monkeypatch):
 d=recipe(tmp_path,monkeypatch,population=True);p=tmp_path/'recipe.json';p.write_bytes(g.encoded(d));result=g.run({'input':str(p)},tmp_path,tmp_path/'prepared')
 assert len(result['cells'])==16 and result['native_calls']==result['fit_calls']==0 and not result['physics_validated']
 for row in result['cells']:
  cfgpath=Path(row['task']['input']);cfg=json.loads(cfgpath.read_text());parsed=n._configuration(row['task'],cfgpath.parent);r=parsed[8]
  assert r['source_observations']=={b['id']:None for b in r['document']['bins']}
  assert all(b['observed']==0 for b in r['document']['bins']) and cfg['expected_data']==next(c['expected_data']for c in d['cells']if c['id']==row['id'])
  inputs=science.task_inputs({'mode':'native-likelihood','task':row['task'],'max_seconds':30},cfgpath.parent)
  assert Path(e.__file__)in inputs and Path(n.__file__)in inputs
  build,cmd=n.commands(cfg,parsed[3],cfgpath.parent,has_response=True)
  assert 'ravel_expected_workspace.root' in cmd[1] and '-t'not in cmd and '--rule'not in cmd and '--run'not in cmd
  assert '--saveFitResult'in cmd
  bridge=Path(row['bridge']['path']).read_text();ast.parse(bridge)
  assert 'NormSet'not in bridge and 'abs('not in bridge and 'RooAdaptiveIntegratorND'in bridge and 'data.set(variables,'in bridge
 assert result['population']==d['population']


@pytest.mark.parametrize('mutation',[
 lambda d:d['cells'].pop(),lambda d:d['cells'][0]['expected_data']['point'].pop('slope'),
 lambda d:d['cells'][0]['components'][0]['bin_windows'][0].pop('angleObs'),
 lambda d:d['cells'][0]['nodes'][0]['template']['values'].pop(),
 lambda d:d['cells'][0]['nodes'][0]['template']['values'][1].update(indices=[0,0]),
 lambda d:d['cells'][0]['integration'].update(max_template_cells=3),
 lambda d:d['cells'][0]['fit'].update(method='AsymptoticLimits'),
 lambda d:d['cells'][0]['expected_data'].update(conditioning='fit_observed_at_fixed_poi'),
 lambda d:d['cells'][0]['expected_data']['point'].update(kappa='0'),
 lambda d:d['cells'][0]['components'][0].update(observables=['massObs']),
])
def test_complete_expected_joint_schema_refuses_missing_domains_population_or_inference(tmp_path,monkeypatch,mutation):
 d=recipe(tmp_path,monkeypatch,population=True);mutation(d)
 with pytest.raises(ValueError):g.validate_document(d)


def test_joint_signed_overlap_is_actual_correlated_table_not_product_of_marginals():
 t={'axes':[{'observable':'x','edges':['0','1','3']},{'observable':'y','edges':['0','2','5']}],'values':[{'indices':[0,0],'integral':'-2'},{'indices':[0,1],'integral':'0'},{'indices':[1,0],'integral':'6'},{'indices':[1,1],'integral':'1'}]}
 assert g.joint_template_integral(t,{'x':['0','3'],'y':['0','5']})==5
 assert g.joint_template_integral(t,{'x':['0','1'],'y':['0','2']})==-2
 assert g.joint_template_integral(t,{'x':['1/2','2'],'y':['1','7/2']})==F(5,4)


@pytest.mark.parametrize('kind',['underflow','overflow','collapsed','native_center','volume'])
def test_joint_native_geometry_never_erases_original_integral(kind):
 if kind=='underflow':edges=['0','1e100'];values='1e-300'
 elif kind=='overflow':edges=['0','1e-300'];values='1e300'
 elif kind=='collapsed':edges=['1','1.'+'0'*99+'1'];values='1'
 elif kind=='native_center':edges=['1e308','1.5e308'];values='1'
 else:edges=['0','1e200'];values='1'
 t={'axes':[{'observable':'x','edges':edges},{'observable':'y','edges':edges if kind=='volume'else ['0','1']}],'values':[{'indices':[0,0],'integral':values}]}
 with pytest.raises(ValueError):g._joint_template_geometry(t)


class RangeVar(Var):
 def ClassName(self):return 'RooRealVar'
 def getMin(self,name=None):return self.lo if name is None else self.ranges[name][0]
 def getMax(self,name=None):return self.hi if name is None else self.ranges[name][1]


def fake_graph(tmp_path,compiled):
 d=compiled['document'];v={p['name']:Var(p['name'],float(F(p['initial'])),*map(lambda q:float(F(q)),p['bounds']),fixed=p['fixed'])for p in d['parameters']}
 for i,bounds in enumerate(d['auxiliary']['eta_bounds']):
  v[f'ravel_aux_{i}']=Var(f'ravel_aux_{i}',0.,*map(lambda q:float(F(q)),bounds));v[f'ravel_aux_{i}_In']=Var(f'ravel_aux_{i}_In',0.,fixed=True,unbounded=True)
 for b in d['bins']:v['n_obs_bin'+b['id']]=Var('n_obs_bin'+b['id'],b['observed'],0.,10000.)
 cell=next(c for c in compiled['recipe']['cells']if c['id']==compiled['cell'])
 for o in cell['observables']:
  v[o['name']]=RangeVar(o['name'],0.,*map(lambda q:float(F(q)),o['bounds']),fixed=True);v[o['name']].ranges={}
 functions={};means={b['id']:10.25+i*.5 for i,b in enumerate(d['bins'])}
 for i,b in enumerate(d['bins']):functions[f'ravel_mean_{i}']=NS(getVal=lambda b=b:means[b['id']])
 for j,t in enumerate(cell['components']):
  names=t['observables'];functions[t['node']]=NS(GetName=lambda t=t:t['node'])
  for name,range_ in ([('ravel_graph_den_'+str(j),None)]if t['normalization']=='full_domain'else [])+[(f'ravel_graph_int_{j}_{i}',f'ravel_graph_int_{j}_{i}')for i in range(len(d['bins']))]:
   if range_:
    rectangle=t['bin_windows'][int(name.rsplit('_',1)[1])]
    for key,ends in rectangle.items():v[key].ranges[range_]=list(map(lambda q:float(F(q)),ends))
   functions[name]=NS(isValid=lambda:True,numIntRealVars=lambda names=names:Collection([v[n]for n in names]),anaIntVars=lambda:Collection(),numIntCatVars=lambda:Collection(),intVars=lambda names=names:Collection([v[n]for n in names]),getVal=lambda range_=range_:5.0 if range_ is None else -1.25,intRange=lambda range_=range_:range_,integrand=lambda t=t:functions[t['node']])
 w=NS(var=lambda name:v.get(name),function=lambda name:functions.get(name),pdf=lambda name:None);data=Data(w,d['bins']);mc=NS(GetObservables=lambda:Collection([v['n_obs_bin'+b['id']]for b in d['bins']]))
 return NS(),w,mc,data,means,functions


def generated(tmp_path,monkeypatch):
 d=recipe(tmp_path,monkeypatch);r=g.response(d,'cell0');root,w,mc,data,means,fns=fake_graph(tmp_path,r);out=e.prepare_source_graph(root,w,mc,data,object(),r,tmp_path/'journal.json');return d,r,out,w,data,means,fns


def test_actual_shared_native_prepare_fake_full_counts_gaussians_extra_coordinate_fractional(tmp_path,monkeypatch):
 d,r,out,w,data,means,fns=generated(tmp_path,monkeypatch)
 obs=g.validate_expected_delivery(out,r);assert obs['counts']==means and data.rows==[list(means.values())] and any(v%1 for v in means.values())
 assert len(means)==len(d['cells'][0]['law']['bins']) and len(out['generated_globals'])==len(d['cells'][0]['law']['auxiliary']['names'])
 assert 'slope'in out['generating_state'] and out['original_counts']=={b['id']:None for b in d['cells'][0]['law']['bins']}
 assert json.loads((tmp_path/'journal.json').read_text())==out
 assert all(x['effective']['eps_abs']==0 and x['status']is None and x['numerical_equivalence_qualified']is False for x in out['integration_readback'])
 assert any(x['value']<0 for x in out['integration_readback'])


@pytest.mark.parametrize('mutation',[
 lambda x:x['initial_dataset_counts'].pop('D'),lambda x:x['original_counts'].update(D=0),
 lambda x:x['generated_counts'].pop('D'),lambda x:x['count_domains']['D'].update(maximum=1.),
 lambda x:x['original_state']['slope'].update(value=1),lambda x:x['generating_state']['kappa'].update(constant=False),
 lambda x:x['generated_globals'].pop('ravel_aux_1_In'),lambda x:x.update(expected_data_qualified=True),
 lambda x:x['integration_readback'].pop(),lambda x:x['integration_readback'][0].update(status=0),
 lambda x:x['integration_readback'][0]['ranges']['angleObs'].__setitem__(1,1.),
 lambda x:x['integration_readback'][0]['effective'].update(eps_abs=1e-8),
])
def test_expected_complete_readback_refuses_modified_census_or_qualification(tmp_path,monkeypatch,mutation):
 _,r,out,*_=generated(tmp_path,monkeypatch);mutation(out)
 with pytest.raises(ValueError):g.validate_expected_delivery(out,r)


def test_count_domain_refusal_retains_exact_fractional_native_return_without_expanding_range(tmp_path,monkeypatch):
 d=recipe(tmp_path,monkeypatch);r=g.response(d,'cell0');root,w,mc,data,means,fns=fake_graph(tmp_path,r)
 v=w.var('n_obs_binA');v.hi=1.;before=data.rows[:]
 with pytest.raises(ValueError,match='domain'):e.prepare_source_graph(root,w,mc,data,object(),r,tmp_path/'failed.json')
 failure=json.loads((tmp_path/'failed.json').read_text());assert failure['status']=='failed' and failure['native_mean_returns']['A']==10.25 and v.hi==1. and data.rows==before


def test_nonnumeric_factor_partition_retained_without_false_numerical_certificate(tmp_path,monkeypatch):
 _,r,out,*_=generated(tmp_path,monkeypatch);rows=out['integration_readback'];row=rows[0];row['factoredVars']=['angleObs'];row['numIntRealVars']=['massObs'];row['numerical_dimension']=1
 row['effective']={'eps_abs':1e-8,'eps_rel':1e-8,'max_warn':None,'method':'RooIntegrator1D'}
 assert g.integration_witness(rows,r)[0]['factoredVars']==['angleObs']
 row['anaIntVars']=['angleObs']
 with pytest.raises(ValueError):g.integration_witness(rows,r)


def test_complete_mc_count_and_gaussian_population_with_original_latent_exposure(tmp_path,monkeypatch):
 d=recipe(tmp_path,monkeypatch);cell=d['cells'][0];law=cell['law']
 # The original supplied unweighted normalization auxiliary is explicit; graph terms do not manufacture it.
 for b in law['bins']:b['observed']=3
 cell['law']=g.regional.poisson_template_auxiliary(law,[{'bin':'MC','rate':'beta','exposure':'7/2','source':'s','observed':17,'observation_id':'syntheticMC'}],statement='Synthetic independent normalization auxiliary',independence='Supplied explicit Poisson experiment',source='s')
 for b in cell['law']['bins']:b['observed']=None
 for t in cell['components']:
  t['coefficients'].append('0');t['log_response'].append(['0','0']);t['bin_windows'].append({'massObs':['1','4'],'angleObs':['-1','2']})
 rebind(d,tmp_path);g.validate_document(d);r=g.response(d,'cell0');root,w,mc,data,means,functions=fake_graph(tmp_path,r);means['MC']=17.5
 out=e.prepare_source_graph(root,w,mc,data,object(),r,tmp_path/'mc.json');g.validate_expected_delivery(out,r)
 assert len(out['dataset_counts'])==5 and out['dataset_counts']['MC']==17.5 and len(out['generated_globals'])==2
 cell['components'][0]['coefficients'][-1]='1'
 with pytest.raises(ValueError,match='MC count law'):g.validate_document(d)


def test_nonfinite_mean_is_retained_as_failed_native_return(tmp_path,monkeypatch):
 d=recipe(tmp_path,monkeypatch);r=g.response(d,'cell0');root,w,mc,data,means,functions=fake_graph(tmp_path,r);means['D']=math.inf
 with pytest.raises(ValueError):e.prepare_source_graph(root,w,mc,data,object(),r,tmp_path/'nonfinite.json')
 out=json.loads((tmp_path/'nonfinite.json').read_text());assert out['status']=='failed' and out['native_mean_returns']['D']=={'nonfinite_native_float':'inf'}


def test_actual_source_conditioning_operation_and_full_fit_readback(tmp_path,monkeypatch):
 d=recipe(tmp_path,monkeypatch);cell=d['cells'][0]
 for b in cell['law']['bins']:b['observed']=30
 req=cell['expected_data'];req.update(conditioning='fit_observed_at_fixed_poi',fit={'strategy':1,'tolerance':'1/10','max_calls':30,'max_iterations':20,'max_edm':'1/1000'});req['point']['c']='1'
 rebind(d,tmp_path);r=g.response(d,'cell0');root,w,mc,data,means,fns=fake_graph(tmp_path,r);calls=[]
 class Mini:
  def __init__(self,nll):calls.append('fit')
  def setErrorLevel(self,x):assert x==.5
  def setStrategy(self,x):pass
  def setEps(self,x):pass
  def setMaxFunctionCalls(self,x):assert x==30
  def setMaxIterations(self,x):assert x==20
  def minimize(self,*args):w.var('beta').setVal(5.5);w.var('slope').setVal(.5);return 0
  def hesse(self):return 0
  def save(self):
   floats=Collection([w.var(n)for n in r['coordinates']if not w.var(n).isConstant()]);const=Collection([w.var(n)for n in r['coordinates']if w.var(n).isConstant()]);size=len(floats)
   return NS(status=lambda:0,covQual=lambda:3,edm=lambda:1e-5,minNll=lambda:17.,numInvalidNLL=lambda:0,numStatusHistory=lambda:2,statusLabelHistory=lambda i:['Migrad','Hesse'][i],statusCodeHistory=lambda i:0,floatParsFinal=lambda:floats,constPars=lambda:const,covarianceMatrix=lambda:[[.1 if i==j else 0. for j in range(size)]for i in range(size)])
 class File:
  def __init__(self,p):self.p=Path(p)
  def WriteTObject(self,obj,name):self.p.write_bytes(b'Explicit inert fake fit result')
  def Close(self):pass
 root.RooMinimizer=Mini;root.TFile=NS(Open=lambda p,*a:File(p))
 out=e.prepare_source_graph(root,w,mc,data,object(),r,tmp_path/'conditioned.json');g.validate_expected_delivery(out,r)
 assert calls==['fit'] and out['original_counts']=={k:30 for k in 'ABCD'} and out['generating_state']['c']['value']==1. and out['generating_state']['slope']['value']==.5
 assert len(out['conditioning_fit']['floating_parameters'])==len(r['coordinates'])-2
 bad=copy.deepcopy(out);bad['conditioning_fit']['floating_parameters'].pop()
 with pytest.raises(ValueError,match='population'):g.validate_expected_delivery(bad,r)
 bad=copy.deepcopy(out);bad['conditioning_fit']['covariance'][0][1]=.5
 with pytest.raises(ValueError,match='covariance'):g.validate_expected_delivery(bad,r)


def test_actual_emitted_full_joint_bridge_disclosed_analytic_fake_api(tmp_path,monkeypatch):
 import re,sys
 from types import ModuleType
 d=recipe(tmp_path,monkeypatch);compiled=g.response(d,'cell0');objects={};tables=[];calls=[]
 class V:
  def __init__(self,name,values):self.name=name;self.value,self.lo,self.hi=values;self.ranges={}
  def GetName(self):return self.name
  def getVal(self):return self.value
  def setVal(self,v):self.value=v
  def setConstant(self,v):self.constant=v
  def setUnit(self,v):self.unit=v
  def setBinning(self,b):self.edges=b.edges
  def setRange(self,name,lo,hi):self.ranges[name]=[lo,hi]
 class Fn:
  def __init__(self,name,kind,args,formula=None):self.name=name;self.kind=kind;self.args=args;self.formula=formula
  def GetName(self):return self.name
  def getVal(self):
   values=[objects[n].getVal()for n in self.args]
   return sum(values)if self.kind=='sum'else eval(re.sub(r'@(\d+)',lambda m:repr(values[int(m[1])]),self.formula),{'__builtins__':{},'pow':pow,'exp':math.exp})
  def getObservables(self,vs):
   wanted={v.name for v in vs};pending=self.args[:];used=set()
   while pending:
    n=pending.pop()
    if n in wanted:used.add(n)
    elif hasattr(objects[n],'args'):pending+=objects[n].args
   return [objects[n]for n in sorted(used)]
  def setIntegratorConfig(self,c):self.config=c
  def integral(self,rectangle):
   if self.kind=='sum':return sum(objects[n].integral(rectangle)for n in self.args)
   assert self.name=='interference'
   x,y=rectangle['massObs'],rectangle['angleObs'];return objects['slope'].getVal()*(x[1]**2-x[0]**2)*(y[1]**2-y[0]**2)/4
  def createIntegral(self,vs,cfg,range_=None):
   assert len(vs)==2 and cfg is self.config
   rectangle={v.name:v.ranges[range_]if range_ else [v.lo,v.hi]for v in vs};calls.append((self.name,copy.deepcopy(rectangle),range_))
   return Integral(self,vs,rectangle)
 class Integral:
  def __init__(self,fn,vs,rect):self.fn=fn;self.vs=vs;self.rect=rect
  def SetName(self,n):self.name=n
  def numIntRealVars(self):return self.vs
  def getVal(self):return self.fn.integral(self.rect)
 class DH:
  def __init__(self,name,title,vs):self.vs=vs;self.rows={};tables.append(self)
  def set(self,vs,weight,error):
   assert error==0.;index=tuple(next(i for i,(a,b)in enumerate(zip(v.edges,v.edges[1:]))if a<v.value<b)for v in self.vs);assert index not in self.rows
   self.rows[index]={'height':weight,'error':error}
 class HistFn(Fn):
  def __init__(self,name,title,vs,data,order):assert order==0;self.name=name;self.args=[v.name for v in vs];self.data=data
  def integral(self,rectangle):
   total=0.
   for index,row in self.data.rows.items():
    volume=1.
    for v,i in zip(self.data.vs,index):
     lo,hi=rectangle[v.name];a,b=v.edges[i:i+2];volume*=max(0.,min(hi,b)-max(lo,a))
    total+=row['height']*volume
   return total
  def getVal(self):return self.integral({v.name:[v.lo,v.hi]for v in self.data.vs})
 class Config:
  def __init__(self,default):self.values={}
  def setEpsAbs(self,x):self.values['eps_abs']=x
  def setEpsRel(self,x):self.values['eps_rel']=x
  def method1D(self):return self
  def method2D(self):return self
  def methodND(self):return self
  def setLabel(self,x):self.values.setdefault('methods',[]).append(x)
  def getConfigSection(self,n):return self
  def setRealValue(self,n,v):self.values[n]=v
  def setCatLabel(self,n,v):self.values[n]=v
 class WS:
  def var(self,n):return objects[n]
  def function(self,n):return objects.get(n)
  def pdf(self,n):return objects.get(n)
 w=WS();setattr(w,'import',lambda fn,*a:objects.__setitem__(fn.name,fn))
 class Builder:
  out=w
  def __init__(self):self.extraNuisances=[]
  def doVar(self,literal):name,values=literal[:-1].split('[');objects[name]=V(name,list(map(float,values.split(','))))
  def doSet(self,*a):pass
  def factory_(self,literal):
   match=re.fullmatch(r'expr::(\w+)\("([^"]*)",(.*)\)',literal)
   if match:name,expr,args=match.groups();objects[name]=Fn(name,'expr',args.split(','),expr)
   else:
    match=re.fullmatch(r'sum::(\w+)\((.*)\)',literal);assert match,literal
    name,args=match.groups();objects[name]=Fn(name,'sum',args.split(','))
 root=ModuleType('ROOT');root.RooArgSet=lambda *v:list(v);root.RooDataHist=DH;root.RooHistFunc=HistFn;root.RooNumIntConfig=Config;root.RooBinning=lambda n,edges:NS(edges=list(edges));root.RooAbsReal=NS(defaultIntegratorConfig=lambda:object());root.RooFit=NS(RecycleConflictNodes=lambda:object());root.gSystem=NS(Load=lambda p:0)
 mod=ModuleType('HiggsAnalysis.CombinedLimit.PhysicsModel');mod.PhysicsModel=type('PhysicsModel',(),{})
 monkeypatch.setitem(sys.modules,'ROOT',root);monkeypatch.setitem(sys.modules,'HiggsAnalysis.CombinedLimit.PhysicsModel',mod)
 namespace={};exec(compile(g.native_bridge_source(compiled),'actual-emitted-joint-bridge-explicit-fake-API','exec'),namespace);model=namespace['model'];model.modelBuilder=Builder();model.doParametersOfInterest()
 assert any(isinstance(x,Config)for x in model._ravel_graph_objects)
 assert len(tables)==3 and all(len(t.rows)==4 and all(r['error']==0. for r in t.rows.values())for t in tables)
 assert len(calls)==9 and calls[0][1]=={'massObs':[1.,4.],'angleObs':[-1.,2.]}
 assert objects['ravel_graph_den_0'].getVal()==pytest.approx(17.5)
 assert 'ravel_graph_den_1'not in objects and all(objects[f'ravel_mean_{i}'].getVal()>0 for i in range(4))
 objects['c'].setVal(1.);objects['slope'].setVal(.1)
 assert objects['ravel_graph_int_1_0'].getVal()==pytest.approx(.225)
 assert objects['ravel_mean_0'].getVal()<objects['ravel_base_mean_0'].getVal()+6*objects['ravel_graph_int_0_0'].getVal()/objects['ravel_graph_den_0'].getVal()
 assert objects['massObs'].constant and objects['angleObs'].constant and all(v.name not in ('massObs','angleObs')for v in model.modelBuilder.extraNuisances)


def graph_probe(compiled,delivery=None):
 from source_graph_coverage_fixture import count_product_fixture,state
 cell=next(c for c in compiled['recipe']['cells']if c['id']==compiled['cell']);witnesses=[]
 _,w,mc,data,_,_=fake_graph(Path('.'),compiled)
 integrals=e.source_graph_integrals(w,compiled)
 for point in cell['fit']['fixed_witness_points']:
  values=copy.deepcopy(delivery['generating_state'])if delivery else state(compiled['base']['document']);values.update({p['name']:{'value':float(F(p['initial'])),'minimum':float(F(p['bounds'][0])),'maximum':float(F(p['bounds'][1])),'constant':p['fixed']}for p in cell['parameters']});values['c']['value']=float(F(point));witnesses.append({'point':point,'raw_nll_at_source_nuisance_values':123.,'construction_state':values,'scales':{k:20.+i for i,k in enumerate(compiled['functions'])},'source_graph_integrals':copy.deepcopy(integrals)})
 p=count_product_fixture(compiled['base']['document'],witnesses);p['workspace']['nuisances'].append('slope');p['construction_linkage']['coordinate_domains']['slope']={'minimum':-2.,'maximum':2.,'constant':False}
 p['source_graph_nodes']={node['name']:{'class':node['class'],'servers':sorted(node['depends_on'])}for node in cell['nodes']}
 p['source_graph_observables']={o['name']:{'bounds':list(map(lambda q:float(F(q)),o['bounds'])),'unit':o['unit'],'constant':True}for o in cell['observables']}
 p['source_graph_integrals']=integrals;p['construction_count_domains']={b['id']:{'has_min':True,'has_max':True,'minimum':0.,'maximum':10000.}for b in cell['law']['bins']}
 p['source_graph_templates']={}
 for node in cell['nodes']:
  if node['kind']=='template':
   t=node['template'];p['source_graph_templates'][node['name']]={'axes':[{'observable':a['observable'],'edges':list(map(lambda q:float(F(q)),a['edges']))}for a in t['axes']],'cells':[{'indices':x['indices'],'height':x['height'],'sumw2':0.}for x in g._joint_template_geometry(t)],'interpolation_order':0}
 if delivery:p['construction_observations']=g.validate_expected_delivery(delivery,compiled)
 return p


def test_real_structural_serialized_joint_readback_and_unknown_numerical_status(tmp_path,monkeypatch):
 _,r,out,*_=generated(tmp_path,monkeypatch);p=graph_probe(r,out);cell=r['recipe']['cells'][0];cfg={'fit':cell['fit'],'model':{'regions':[{'channel':b['id'],'role':b['role']}for b in cell['law']['bins']]}}
 rows=n._check_workspace(p,cfg,r,out);assert len(rows)==8 and not any(x['numerical_equivalence_qualified']for x in rows)
 bad=copy.deepcopy(p);bad['construction_count_domains']['A']['maximum']=9999.
 with pytest.raises(ValueError,match='domains'):n._check_workspace(bad,cfg,r,out)
 bad=copy.deepcopy(p);bad['source_graph_templates']['down']['cells'][3]['sumw2']=1.
 with pytest.raises(ValueError,match='heights/errors'):n._check_workspace(bad,cfg,r,out)
 bad=copy.deepcopy(p);bad['source_graph_integrals'][0]['observables'].reverse()
 with pytest.raises(ValueError,match='identity'):n._check_workspace(bad,cfg,r,out)


@pytest.mark.parametrize('mutation',[None,'ravel_regional_expected.py','ravel_expected_workspace.root'])
def test_actual_ordinary_worker_orchestration_fake_runtime_true_source_readback_and_ending_custody(tmp_path,monkeypatch,mutation):
 d=recipe(tmp_path,monkeypatch);path=tmp_path/'recipe.json';path.write_bytes(g.encoded(d));prepared=g.run({'input':str(path)},tmp_path,tmp_path/'bundle');task=prepared['cells'][0]['task'];r=g.response(d,'cell0');calls=[];deliveries=[]
 def process(cmd,cwd,env,log,deadline,**kwargs):
  name=Path(log).name;calls.append(name);work=Path(cmd[1]).parent if name.startswith('expected-')else Path(cwd)
  nativework=Path(log).parent.parent/'native-work'
  if name=='workspace-build.log':(nativework/'ravel_workspace.root').write_bytes(b'explicit fake original workspace')
  if name=='native-fit.log':(Path(cwd)/'higgsCombine.ravel.MultiDimFit.mH120.root').write_bytes(b'explicit fake fit tree')
  if name=='combine-version.log':raw=' <<< Combine >>>\n <<< v9.2.1 >>>\nMissing datacard file\nUsage: combine [options]\n'
  elif name=='workspace-probe.log':raw='RAVEL_NATIVE_PROBE='+json.dumps(graph_probe(r))
  elif name=='expected-preparation.log':
   root,w,mc,data,means,fns=fake_graph(tmp_path,r);value=e.prepare_source_graph(root,w,mc,data,object(),r,nativework/'ravel_expected_preparation.json');deliveries.append(value)
   (nativework/'ravel_expected_workspace.root').write_bytes(b'explicit fake generated workspace');raw='RAVEL_NATIVE_PROBE='+json.dumps({'expected_preparation':value})
  elif name=='expected-workspace-probe.log':raw='RAVEL_NATIVE_PROBE='+json.dumps(graph_probe(r,deliveries[0]))
  elif name=='native-result.log':
   if mutation:
    target=nativework/mutation;target.write_bytes(target.read_bytes()+b'changed after preparation')
   states=deliveries[0]['generating_state'];diagnostic={'name':'multidimfit.ravel.root:fit_mdf','status':0,'covariance_quality':3,'edm':1e-5,'minimum_nll':3.,'invalid_nll_evaluations':0,'status_history':[{'label':'Migrad','status':0}],'floating_parameters':[{'name':name,'value':v['value'],'error':.1}for name,v in states.items()if not v['constant']],'constant_parameters':[{'name':name,'value':v['value']}for name,v in states.items()if v['constant']]}
   raw='RAVEL_NATIVE_RESULT='+json.dumps({'rows':[{'c':0.,'deltaNLL':0.,'quantileExpected':-1.}],'fit_results':[diagnostic]})
  else:raw='RAVEL_NATIVE_PROBE='+json.dumps({'fake':True})
  Path(log).write_text(raw);return raw
 monkeypatch.setattr(n.platform,'platform',lambda:'explicit synthetic platform metadata, no ABI qualification');monkeypatch.setattr(n,'_process',process);monkeypatch.setattr(n,'_check_probe',lambda *a,**k:None)
 # Runtime identity/actual optimizer extraction are inert; structural/dataset/source ending checks above are production APIs.
 # Literal fake ROOT result rows pass real extraction and full parameter census, without engine execution.
 result=n.run(task,tmp_path,tmp_path/'result')
 if mutation:
  assert result['status']=='failed' and 'evidence changed'in result['error']['message'];return
 assert result['status']=='passed',result.get('error')
 assert result['inference']['observed_endpoint']is None and result['inference']['data_semantics']=='generated_source_graph_Asimov_not_observed'
 assert result['expected_data']['generated_counts']['A']==10.25 and result['integration_diagnostics']['convergence']=='unknown'
 assert calls==['combine-help.log','combine-version.log','native-identity.log','workspace-build.log','workspace-probe.log','expected-preparation.log','expected-workspace-probe.log','native-fit.log','native-result.log']
 assert all('crossing'not in k for k in result['commands']) and all(not x['numerical_equivalence_qualified']for x in result['native_function_comparisons'])


def test_public_unapproved_ordinary_plan_has_full_expected_joint_census_and_no_dispatch(tmp_path,monkeypatch):
 from source_graph_coverage_fixture import policy
 monkeypatch.setattr(n.platform,'platform',lambda:'explicit synthetic runtime metadata, no platform query')
 d=recipe(tmp_path,monkeypatch);path=tmp_path/'recipe.json';path.write_bytes(g.encoded(d));p=policy();p.update(max_redos=0,allowed_stages=['science'],allowed_changed_paths=[])
 spec={'schema_version':2,'mode':'native-statistical-construction','source':d['question'],'assumptions':d['assumptions'],'max_seconds':30,'approval_mode':'scripted_yes','task':{'input':str(path)},'max_attempts':1,'review_policy':{'schema_version':1,'policy':p,'correction_contract':{'task_fields':[],'input_slots':[]}}}
 sp=tmp_path/'spec.json';sp.write_bytes(g.encoded(spec));plan=science.plan(tmp_path/'unapproved',sp)
 assert plan['mode']=='native-statistical-construction' and plan['max_attempts']==1 and str(tmp_path/'original/nominal.json')in plan['stage_binding']['inputs']
 assert not (tmp_path/'unapproved'/science.APPROVAL).exists() and not (tmp_path/'unapproved/outputs').exists()


def test_declared_native_lvalue_transformation_retains_whole_original_tuple(tmp_path,monkeypatch):
 _,r,out,*_=generated(tmp_path,monkeypatch);cell=r['recipe']['cells'][0]
 cell['nodes'].append({'name':'transformedMass','kind':'factory','class':'RooLinearVar','depends_on':['massObs','slope'],'members':['class_source'],'factory':'RooLinearVar::transformedMass(massObs,slope)'})
 row=out['integration_readback'][0];row['intVars']=['angleObs','transformedMass'];row['numIntRealVars']=['angleObs'];row['anaIntVars']=['transformedMass'];row['numerical_dimension']=1;row['effective']={'eps_abs':1e-8,'eps_rel':1e-8,'max_warn':None,'method':'RooIntegrator1D'}
 row['engine_variables']=[{'name':'angleObs','class':'RooRealVar','original_observables':['angleObs']},{'name':'transformedMass','class':'RooLinearVar','original_observables':['massObs']}]
 assert g.integration_witness(out['integration_readback'],r)[0]['observables']==['massObs','angleObs']
 row['engine_variables'][1]['original_observables']=[]
 with pytest.raises(ValueError,match='closure'):g.integration_witness(out['integration_readback'],r)
