"""Pure/source and inert ordinary controls. Never import ROOT or run a fit."""
import ast
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
import math
import re
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest
from ravel.physics import continuous_dijet_shapes as shapes
from ravel.physics import background_construction as background, statistical_construction as regional, native_likelihood as native
from ravel.workflow import science
from test_background_construction import specification
from test_statistical_construction import native_config, state


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    monkeypatch.setattr(native,'_process',lambda *a,**k: (_ for _ in ()).throw(AssertionError('native forbidden')))


def policy():
    return {'native':{'engine':'RooIntegrator1D','absolute_tolerance':'1e-12','relative_tolerance':'1e-10','max_steps':16},
            'reference':{'absolute_tolerance':'1e-12','relative_tolerance':'1e-10','max_depth':20,'max_evaluations':200000,
                         'maximum_probability_error':'1e-8','maximum_gradient_error':'1e-7'}}


def shape(j=2):
    return {'kind':shapes.KIND,'sqrt_s':'10','domain':['1','8'],
            'bin_windows':[['1','2'],['2','5'],['5','8'],None],
            'parameters':['alpha']+['beta'+str(i) for i in range(1,j+1)],
            'parameter_response':[[] for _ in range(j+1)],'integration':policy()}


def dijet_spec(tmp_path,correlated=True,kind='dijet4'):
    s=specification(tmp_path,correlated); candidate=s['candidates'][1]
    j={'dijet3':1,'dijet4':2,'dijet_log_polynomial':4}[kind]
    p=deepcopy(candidate['parameters'][0]);p['name']='dijet_yield'
    names=['alpha']+['beta'+str(i) for i in range(1,j+1)]
    pars=[p]
    for name in names:
        q=deepcopy(p);q.update(name=name,role='coefficient',initial='0',bounds=['-1','1'],meaning='signed dimensionless dijet coefficient')
        pars.append(q)
    k=len(s['baseline']['auxiliary']['names'])
    response=[['1/20','-1/30'] if k else [] for _ in names]
    s['candidates'][1]={'id':'dijet','family':{'kind':kind,'sqrt_s':'10','parameters':names,'parameter_response':response,'integration':policy()},'parameters':pars,'source':'s'}
    return s


def polynomial_integral(a,b,alpha,beta):
    # Independent exact antiderivative for integer powers q**beta*(1-q)**alpha.
    return sum(((-1)**i*math.comb(alpha,i)*(b**(beta+i+1)-a**(beta+i+1))/F(beta+i+1) for i in range(alpha+1)),F())


@pytest.mark.parametrize('alpha,beta',[(0,0),(1,0),(3,2),(5,4),(0,7)])
def test_complete_bin_integrals_match_exact_polynomial_limit(alpha,beta):
    s=shape();result=shapes.reference(s,[alpha,beta,0])
    a,b=(F(v)/10 for v in s['domain']);den=polynomial_integral(a,b,alpha,beta)
    exact=[0 if w is None else float(polynomial_integral(F(w[0])/10,F(w[1])/10,alpha,beta)/den) for w in s['bin_windows']]
    assert result['fractions']==pytest.approx(exact,rel=2e-10,abs=2e-12)
    assert math.fsum(result['fractions'])==pytest.approx(1,abs=3e-12)
    for i in range(3):assert math.fsum(v[i] for v in result['gradient'])==pytest.approx(0,abs=3e-11)
    assert result['clipping_applied'] is False
    assert result['evaluations']<=s['integration']['reference']['max_evaluations']
    assert 'not certified' in result['error_semantics']


@pytest.mark.parametrize('beta1,beta2',[('0','-1'),('2','-2'),('-3','-4')])
def test_log_gaussian_erf_antiderivative_independent_limit(beta1,beta2):
    s=shape();got=shapes.fractions(s,[0,F(beta1),F(beta2)])[0]
    # q=e^t gives exp(beta2*t²+(beta1+1)*t). Constants cancel.
    c=float(F(beta2));offset=float(F(beta1)+1)/(2*c)
    primitive=lambda q:math.erf(math.sqrt(-c)*(math.log(float(q))+offset))
    a,b=(F(v)/10 for v in s['domain']);den=primitive(b)-primitive(a)
    expected=[0 if w is None else (primitive(F(w[1])/10)-primitive(F(w[0])/10))/den for w in s['bin_windows']]
    assert got==pytest.approx(expected,rel=3e-9,abs=3e-12)


def test_full_domain_yield_keeps_gaps_and_mass_units():
    s=shape();s['bin_windows']=[['1','2'],None,['1','8']]
    result=shapes.reference(s,[0,0,0]);assert result['fractions']==pytest.approx([1/7,0,1])
    assert result['gradient'][-1]==[0,0,0]
    scaled=deepcopy(s);scaled['sqrt_s']='10000';scaled['domain']=['1000','8000'];scaled['bin_windows']=[['1000','2000'],None,['1000','8000']]
    assert shapes.reference(scaled,[1,-2,F(1,10)])==shapes.reference(s,[1,-2,F(1,10)])


@pytest.mark.parametrize('index',[0,1,2,3,4])
def test_general_log_polynomial_moment_gradients(index):
    s=shape(4);point=[F(1,5),F(-1,3),F(1,10),F(-1,50),F(1,200)]
    values,grad=shapes.fractions(s,point);h=F(1,100000)
    lo=point.copy();hi=point.copy();lo[index]-=h;hi[index]+=h
    diff=[(b-a)/(2*float(h)) for a,b in zip(shapes.fractions(s,lo)[0],shapes.fractions(s,hi)[0])]
    assert [v[index] for v in grad]==pytest.approx(diff,rel=5e-7,abs=2e-8)


@pytest.mark.parametrize('kind',['dijet3','dijet4','dijet_log_polynomial'])
def test_complete_common_regional_law_and_full_auxiliary_gradient(tmp_path,kind):
    spec=dijet_spec(tmp_path,True,kind);spec['transfer']['log_response'][0]=['1/5','-1/7'];spec['transfer']['powers']={'kappa':1}
    row=background.construct(spec)[1];doc=row['document'];point=regional.initial_point(doc)
    point.update(c='1/2',ravel_aux_0='1/3',ravel_aux_1='-1/4',alpha='1/5',beta1='-1/3')
    got=regional.mean_jet(doc,point)
    assert doc['terms'][:-1]==spec['baseline']['terms']
    assert all(doc[key]==spec['baseline'][key] for key in ('auxiliary','bins','partition','prediction','template_statistics','assumptions'))
    assert got['clipping_applied'] is False and any(v<0 for v in got['term_values'][0])
    assert row['integrated_fractions'] is None
    assert row['floating_background_coefficients']==len(spec['candidates'][1]['parameters'])
    for j,name in enumerate(got['coordinates']):
        if name=='kappa':continue
        h=F(1,100000);lo={**point,name:str(F(point[name])-h)};hi={**point,name:str(F(point[name])+h)}
        diff=[(b-a)/(2*float(h)) for a,b in zip(regional.mean_jet(doc,lo)['means'],regional.mean_jet(doc,hi)['means'])]
        assert [v[j] for v in got['jacobian']]==pytest.approx(diff,rel=3e-6,abs=5e-8)


def test_poisson_template_auxiliary_keeps_main_density_and_full_rate(tmp_path):
    doc=background.construct(dijet_spec(tmp_path))[1]['document']
    full=regional.poisson_template_auxiliary(doc,[{'bin':'mcBeta','rate':'beta','exposure':'3','source':'s','observed':15,'observation_id':'independent_mc/beta'}],
        source='s',statement='Artificial independent MC normalization count.',independence='No reuse of SR/CR counts.')
    jet=regional.mean_jet(full,regional.initial_point(full))
    assert full['terms'][-2]['shape']['bin_windows'][-1] is None
    assert jet['means'][-1]==15
    assert jet['jacobian'][-1][jet['coordinates'].index('beta')]==3
    assert all(v==0 for i,v in enumerate(jet['jacobian'][-1]) if i!=jet['coordinates'].index('beta'))


@pytest.mark.parametrize('mutation',[
    lambda s:s.update(sqrt_s='0'),lambda s:s.update(domain=['0','8']),lambda s:s.update(domain=['1','10']),
    lambda s:s.update(bin_windows=[['1','9']]),lambda s:s.update(bin_windows=[['2','2']]),
    lambda s:s['integration']['native'].update(engine='unknown'),lambda s:s['integration']['native'].update(max_steps=21),
    lambda s:s['integration']['native'].update(relative_tolerance='0'),lambda s:s['integration']['reference'].update(max_depth=25),
    lambda s:s['integration']['reference'].update(max_evaluations=200001),lambda s:s['integration']['reference'].update(maximum_probability_error='1'),
    lambda s:s.update(expression='callback'),lambda s:s.update(parameters=['alpha','alpha','beta2'])])
def test_closed_schema_and_bounded_domain_refusals(tmp_path,mutation):
    doc=background.construct(dijet_spec(tmp_path,False))[1]['document'];s=doc['terms'][-1]['shape'];mutation(s)
    with pytest.raises((ValueError,KeyError,TypeError)):regional.validate(doc)


def test_reference_refuses_budget_and_effective_box_instead_of_clipping(tmp_path):
    s=shape();s['integration']['reference']['max_evaluations']=32
    with pytest.raises(ValueError,match='budget'):shapes.reference(s,[4,-3,2])
    with pytest.raises(ValueError,match='envelope'):shapes.reference(shape(4),[99]*5)
    doc=background.construct(dijet_spec(tmp_path))[1]['document']
    doc['terms'][-1]['shape']['parameter_response'][0]=['100','100']
    with pytest.raises(ValueError,match='box'):regional.validate(doc)


def test_reference_refuses_depth_and_estimated_error_limits():
    s=shape();s['integration']['reference'].update(max_depth=4,absolute_tolerance='1e-14',relative_tolerance='1e-14')
    with pytest.raises(ValueError,match='depth'):shapes.reference(s,[4,-3,2])
    s=shape();s['integration']['reference'].update(absolute_tolerance='1e-6',relative_tolerance='1e-6',maximum_probability_error='1e-12',maximum_gradient_error='1e-12')
    with pytest.raises(ValueError,match='estimated normalized error'):shapes.reference(s,[4,-3,2])


def test_native_formula_exact_density_convention_and_common_auxiliary_state(tmp_path):
    doc=background.construct(dijet_spec(tmp_path))[1]['document'];shape_=doc['terms'][-1]['shape']
    point=regional.initial_point(doc);point.update(alpha='1/4',beta1='-1/3',beta2='1/5',ravel_aux_0='1/3',ravel_aux_1='-1/4')
    # Independent evaluation of emitted CLOSED source text, using complete native
    # coordinates. Ratios remove its common centering factor; this checks signs,
    # order, q=m/sqrt_s and nuisance transport without executing ROOT.
    theta=[F(1,3),F(3,5)*F(1,3)+F(4,5)*F(-1,4)]
    expected=[float(F(point[name])+sum((F(r)*t for r,t in zip(row,theta)),F())) for name,row in zip(shape_['parameters'],shape_['parameter_response'])]
    payload=regional.response(doc);formulas={}
    for expression in payload['shape_factories']:
        match=re.fullmatch(r'(expr|EXPR)::(\w+)\("(.+)",(.+)\)',expression);assert match
        formulas[match[2]]=(match[3],match[4].split(','))
    def evaluate(name,q):
        if name.endswith('_x'):return q
        if name in point:return float(F(point[name]))
        expression,args=formulas[name]
        text=re.sub(r'@(\d+)',lambda m:repr(evaluate(args[int(m[1])],q)),expression)
        return eval(text,{'__builtins__':{},'exp':math.exp,'log':math.log,'pow':pow})
    pdf=payload['shape_integrals'][0]['pdf']
    independent=lambda q:(1-q)**expected[0]*q**(expected[1]+expected[2]*math.log(q))
    for q in (.1,.17,.23,.3):
        assert evaluate(pdf,q)/evaluate(pdf,.2)==pytest.approx(independent(q)/independent(.2),rel=3e-14)
    assert shapes.UPSTREAM_API['tag']=='v6-22-08'
    assert all(len(r['sha256'])==64 and 'root-project/root/v6-22-08/' in r['url'] for r in shapes.UPSTREAM_API['sources'].values())


@pytest.mark.parametrize('kind',['dijet3','dijet4'])
def test_family_census_and_coefficient_order_fail_before_preparation(tmp_path,kind):
    spec=dijet_spec(tmp_path,False,kind);candidate=spec['candidates'][1]
    candidate['family']['parameters'].append('missing')
    with pytest.raises(ValueError,match='coefficient population'):background.construct(spec)
    assert not (tmp_path/'population').exists()


def test_degenerate_binary64_geometry_and_coefficient_roles_refused(tmp_path):
    doc=background.construct(dijet_spec(tmp_path,False))[1]['document']
    doc['terms'][-1]['shape']['bin_windows'][0]=['1','1.000000000000000000001']
    with pytest.raises(ValueError,match='binary64'):regional.validate(doc)
    doc=background.construct(dijet_spec(tmp_path,False))[1]['document']
    next(p for p in doc['parameters'] if p['name']=='alpha').update(role='rate',bounds=['0','1'])
    with pytest.raises(ValueError,match='coefficient'):regional.validate(doc)


def test_ordinary_population_prepares_every_candidate_and_pins_kernel(tmp_path):
    spec=dijet_spec(tmp_path);_,cfg=native_config(tmp_path,spec['baseline'])
    fit=cfg['fit'];fit.pop('saved_fit');fit.update(points=3,absolute_nll=True)
    packet=background.write_native_population(spec,tmp_path/'population',runtime=cfg['runtime'],fit=fit,candidate_seconds=[30,40],overhead_seconds=10)
    task=packet['task'];inputs=science.task_inputs(packet,tmp_path)
    assert packet['native_calls_executed']==0
    assert Path(shapes.__file__).resolve() in inputs
    study=json.loads(Path(task['input']).read_text());assert [r['id'] for r in study['candidates']]==['constant','dijet']
    doc=json.loads((tmp_path/'population/dijet/construction.json').read_text());assert doc['terms'][:-1]==spec['baseline']['terms']
    observed=state(doc);witness=regional.native_witness(regional.response(doc),observed)
    assert set(witness)=={'ravel_mean_'+str(i) for i in range(4)}


def test_native_integrals_are_raw_same_density_ranges_config_and_no_extra_fit_coordinate(tmp_path,monkeypatch):
    doc=background.construct(dijet_spec(tmp_path))[1]['document'];compiled=regional.response(doc);code=regional.native_bridge_source(compiled);ast.parse(code)
    assert 'NormSet' not in code and '@0/@1' in code
    calls=[];variables={};pdfs={};integrals={}
    class Value:
        def __init__(self,name):self.name=name;self.constant=False;self.values=[]
        def setVal(self,value):self.values.append(value)
        def setLabel(self,value):self.values.append(value)
        def setConstant(self,value):self.constant=value
        def setRange(self,*args):calls.append(('range',self.name,args))
    class Config:
        def __init__(self):self.entries={n:Value(n) for n in ('sumRule','extrapolation','maxSteps','minSteps','fixSteps')};self.method=Value('method')
        def method1D(self):return self.method
        def setEpsAbs(self,value):calls.append(('epsAbs',value))
        def setEpsRel(self,value):calls.append(('epsRel',value))
        def getConfigSection(self,name):assert name=='RooIntegrator1D';return SimpleNamespace(find=lambda n:self.entries[n])
    class Integral:
        def SetName(self,name):self.name=name
    class Density:
        def __init__(self):self.cfg=Config()
        def specialIntegratorConfig(self,copy):assert copy is True;return self.cfg
        def createIntegral(self,args,*commands):
            assert len(commands)==2 and commands[0][0]=='NumIntConfig' and commands[1][0]=='Range'
            calls.append(('integral',self,args,commands));return Integral()
    def factory(expression):
        calls.append(('factory',expression))
        if expression.startswith('EXPR::'):pdfs[expression.split('::')[1].split('(')[0]]=Density()
    def do_var(literal):variables[literal.split('[')[0]]=Value(literal.split('[')[0])
    workspace=SimpleNamespace(var=lambda n:variables[n],pdf=lambda n:pdfs[n])
    setattr(workspace,'import',lambda integral,command:integrals.update({integral.name:integral}))
    physics=ModuleType('HiggsAnalysis.CombinedLimit.PhysicsModel');physics.PhysicsModel=object
    root=ModuleType('ROOT');root.RooArgSet=lambda variable:('ArgSet',variable)
    root.RooFit=SimpleNamespace(NumIntConfig=lambda c:('NumIntConfig',c),Range=lambda r:('Range',r),RecycleConflictNodes=lambda:('RecycleConflictNodes',))
    monkeypatch.setitem(sys.modules,physics.__name__,physics);monkeypatch.setitem(sys.modules,'ROOT',root)
    namespace={};exec(code,namespace);model=namespace['model']
    model.modelBuilder=SimpleNamespace(doVar=do_var,out=workspace,extraNuisances=[],doSet=lambda *a:None,factory_=factory)
    model.doParametersOfInterest()
    declaration=compiled['shape_integrals'][0];density=pdfs[declaration['pdf']]
    assert variables[declaration['variable']].constant is True
    assert variables[declaration['variable']] not in model.modelBuilder.extraNuisances
    assert len([r for r in calls if r[0]=='integral'])==4 # whole plus A/B/C, no D
    assert all(r[1] is density for r in calls if r[0]=='integral')
    assert density.cfg.entries['maxSteps'].values==[16] and density.cfg.entries['minSteps'].values==[17]
    assert density.cfg.entries['fixSteps'].values==[0]
    assert density.cfg.entries['sumRule'].values==['Trapezoid'] and density.cfg.entries['extrapolation'].values==['Wynn-Epsilon']
    assert set(integrals)=={declaration['denominator'],*[b['numerator'] for b in declaration['bins']]}
    assert model.getYieldScale('A','ravel_full')=='ravel_mean_0'
    assert model.getYieldScale('A','ravel_dummy')==0
    setattr(workspace,'import',lambda *args:True)
    with pytest.raises(ValueError,match='import failed'):model.doParametersOfInterest()
