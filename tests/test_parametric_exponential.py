"""Source/inert ordinary controls. No ROOT, optimizer, native or provider calls."""
import ast
from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction as F
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace

import pytest
from ravel.physics import background_construction as background, statistical_construction as regional
from ravel.physics import parametric_shapes as shapes, native_likelihood as native, background_discrete_profile as discrete
from ravel.workflow import science
from test_background_construction import specification
from test_statistical_construction import native_config, fixture


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    monkeypatch.setattr(native,'_process',lambda *a,**k: (_ for _ in ()).throw(AssertionError('native forbidden')))


def exp_spec(tmp_path, correlated=True):
    s=specification(tmp_path,correlated)
    p=deepcopy(s['candidates'][0]['parameters'][0]); p['name']='exp_yield'
    q=deepcopy(p); q.update(name='exp_slope',role='coefficient',initial='0',bounds=['-4','4'],meaning='physical inverse-x exponential slope')
    k=len(s['baseline']['auxiliary']['names'])
    s['candidates'][1]={'id':'exp','family':{'kind':'exponential','slopes':['exp_slope'],'slope_log_response':[['1/5','-1/10'] if k else []]},'parameters':[p,q],'source':'s'}
    return s


def oracle(shape,slope):
    # Independent high precision physical-x antiderivative, not implementation
    # sinhc/expm1 or finite differences.
    with localcontext() as ctx:
        ctx.prec=100
        D=lambda x:Decimal(F(x).numerator)/Decimal(F(x).denominator)
        a,b=map(D,shape['domain']); c=D(slope)
        if c==0:
            return [Decimal(0) if w is None else (D(w[1])-D(w[0]))/(b-a) for w in shape['bin_windows']]
        total=(c*b).exp()-(c*a).exp()
        return [Decimal(0) if w is None else ((c*D(w[1])).exp()-(c*D(w[0])).exp())/total for w in shape['bin_windows']]


def cpp_eval(expression,value):
    # Test-only balanced ternary translator for generated closed TFormula text.
    def translate(s):
        out=''; i=0
        while i<len(s):
            if s[i]=='(':
                start=i+1; depth=1; i+=1
                while depth:
                    depth+=(s[i]=='(')-(s[i]==')'); i+=1
                inner=s[start:i-1]; level=0; question=colon=None
                for j,c in enumerate(inner):
                    level+=(c=='(')-(c==')')
                    if level==0 and c=='?':question=j
                    if level==0 and c==':':colon=j
                if question is not None:
                    out+='('+translate(inner[question+1:colon])+' if '+translate(inner[:question])+' else '+translate(inner[colon+1:])+')'
                else:out+='('+translate(inner)+')'
            else:out+=s[i];i+=1
        return out
    return eval(translate(expression.replace('@0','value')),{'__builtins__':{},'abs':abs,'pow':pow,'exp':math.exp,'sinh':math.sinh,'value':value})


@pytest.mark.parametrize('slope',['0','1e-30','-1e-30','1e-9','-1e-9','1/2000','-1/2000','25','-25'])
def test_reference_native_formula_decimal_partition_and_derivative(slope):
    shape={'domain':['100','102'],'bin_windows':[['100','100.1'],['100.1','100.9'],['100.9','102'],None]}
    vals,deriv=shapes.fractions(shape,F(slope)); ref=oracle(shape,F(slope))
    assert vals==pytest.approx(list(map(float,ref)),rel=3e-13,abs=2e-15)
    assert math.fsum(vals)==pytest.approx(1,abs=3e-15)
    assert math.fsum(deriv)==pytest.approx(0,abs=5e-15)
    width,windows=shapes.geometry(shape['domain'],shape['bin_windows'])
    emitted=[0 if w is None else cpp_eval(shapes.native_fraction_expression(w),float(F(slope)*width)) for w in windows]
    assert emitted==pytest.approx(vals,rel=3e-13,abs=2e-15)
    # Independent derivative from Decimal differentiated antiderivative (center
    # the domain to avoid subtracting large physical first moments).
    with localcontext() as ctx:
        ctx.prec=90
        c=Decimal(F(slope).numerator)/Decimal(F(slope).denominator)
        if c==0: expected=[float(F(v)*(F(w[0])+F(w[1])-202)/2) if w else 0. for v,w in zip(vals,shape['bin_windows'])]
        else:
            def mean(lo,hi):
                x,y=Decimal(lo)-100,Decimal(hi)-100
                return (y*(c*y).exp()-x*(c*x).exp())/((c*y).exp()-(c*x).exp())-1/c
            whole=mean('100','102')
            expected=[float(v*(mean(*w)-whole)) if w else 0. for v,w in zip(ref,shape['bin_windows'])]
    assert deriv==pytest.approx(expected,rel=2e-11,abs=1e-14)


def test_affine_units_and_zero_limit_are_full_domain_not_surviving_bins():
    a={'domain':['0','2'],'bin_windows':[['0','1'],None]}
    b={'domain':['10','14'],'bin_windows':[['10','12'],None]}
    va,da=shapes.fractions(a,F(3)); vb,db=shapes.fractions(b,F(3,2))
    assert vb==pytest.approx(va) and db==pytest.approx([2*d for d in da])
    assert shapes.fractions(a,0)==([.5,0.],[-.25,0.])
    assert sum(va)<1 # no surviving-bin renormalization


def test_complete_regional_signed_controls_shared_covariance_and_gradients(tmp_path):
    spec=exp_spec(tmp_path);spec['transfer']['log_response'][0]=['2','-1']
    spec['transfer']['powers']={'kappa':1}
    row=background.construct(spec)[1];d=row['document'];p=regional.initial_point(d)
    p.update(c='1',ravel_aux_0='1/3',ravel_aux_1='-1/4',exp_slope='1/7')
    got=regional.mean_jet(d,p)
    assert row['integrated_fractions'] is None and row['penalty_nll']=='1'
    assert d['terms'][:-1]==spec['baseline']['terms']
    assert all(d[key]==spec['baseline'][key] for key in ('auxiliary','bins','partition','prediction','template_statistics','assumptions'))
    assert got['clipping_applied'] is False and any(v<0 for v in got['term_values'][0])
    # Every coordinate: common transfer and Gaussian slope/yield terms, plus
    # signed signal/control terms. Central numerical derivative only checks pure
    # deterministic mean algebra, no objective evaluation or optimization.
    for j,name in enumerate(got['coordinates']):
        if name=='kappa':continue
        h=F(1,1000000);lo={**p,name:str(F(p[name])-h)};hi={**p,name:str(F(p[name])+h)}
        diff=[(y-x)/(2*float(h)) for x,y in zip(regional.mean_jet(d,lo)['means'],regional.mean_jet(d,hi)['means'])]
        assert [v[j] for v in got['jacobian']]==pytest.approx(diff,rel=1e-6,abs=1e-7)


def test_mixture_fixed_yield_and_shape_penalty_and_native_factory_source(tmp_path):
    spec=exp_spec(tmp_path,False);c=spec['candidates'][1]
    p,q=c['parameters'];p['fixed']=True;q['fixed']=True
    c['family']['slopes'].append('second_slope');c['family']['slope_log_response'].append([])
    y=deepcopy(p);y.update(name='second_yield',fixed=False)
    z=deepcopy(q);z.update(name='second_slope',fixed=False)
    c['parameters']=[p,y,q,z]
    row=background.construct(spec)[1];compiled=regional.response(row['document']);code=regional.native_bridge_source(compiled)
    assert row['floating_background_coefficients']==2 and row['penalty_nll']=='1'
    assert sum('Exponential::' in f for f in compiled['shape_factories'])==2
    assert all('expm1' not in f for f in compiled['shape_factories']) # declared ROOT6.24 TFormula functions
    assert 'setConstant(True)' in code and 'setConstant(False)' in code
    ast.parse(code)
    # Execute the ACTUAL generated PhysicsModel methods against an inert API
    # recorder; no ROOT import, no substitute fit engine or native claim.
    mod=ModuleType('HiggsAnalysis.CombinedLimit.PhysicsModel');mod.PhysicsModel=type('PhysicsModel',(),{})
    saved=sys.modules.get(mod.__name__);sys.modules[mod.__name__]=mod
    try:
        ns={};exec(compile(code,'<generated regional plugin>','exec'),ns)
        calls=[]
        class Var:
            def setConstant(self,x):calls.append(('constant',x))
        builder=SimpleNamespace(doVar=lambda s:calls.append(('var',s)),out=SimpleNamespace(var=lambda n:Var()),extraNuisances=[],
                                doSet=lambda *a:calls.append(('set',a)),factory_=lambda s:calls.append(('factory',s)))
        model=ns['model'];model.modelBuilder=builder;model.doParametersOfInterest()
        assert [v for kind,v in calls if kind=='factory']==compiled['shape_factories']+compiled['factories']
        assert model.getYieldScale('A','ravel_full')=='ravel_mean_0'
        assert model.getYieldScale('A','ravel_dummy')==0
    finally:
        if saved is None:sys.modules.pop(mod.__name__,None)
        else:sys.modules[mod.__name__]=saved


def with_mc(tmp_path):
    d=background.construct(exp_spec(tmp_path))[1]['document']
    return regional.poisson_template_auxiliary(d,[{'bin':'mcBeta','rate':'beta','exposure':'3','source':'s','observed':15,'observation_id':'independent_mc/beta'}],
        source='s',statement='Artificial independently Poissonized unweighted MC normalization count, conditional analytic shape.',independence='Supplied independent MC experiment, no reuse of the SR/CR counts.')


def test_explicit_mc_generative_shared_rate_one_factor_and_preserved_main(tmp_path):
    d=with_mc(tmp_path);p=regional.initial_point(d);j=regional.mean_jet(d,p)
    assert j['means'][-1]==15
    assert j['jacobian'][-1][j['coordinates'].index('beta')]==3
    assert all(v==0 for i,v in enumerate(j['jacobian'][-1]) if i!=j['coordinates'].index('beta'))
    # Rate ties A/B/C/D, not independent bin constraints or duplicated Gaussian.
    assert j['jacobian'][0][j['coordinates'].index('beta')]==6
    assert j['jacobian'][1][j['coordinates'].index('beta')]==2
    assert len(d['template_statistics']['experiments'])==1
    p['beta']='1';assert regional.mean_jet(d,p)['means'][-1]==3
    d['bins'][-1]['observed']=0;regional.validate(d) # unweighted zero counts valid
    with pytest.raises(ValueError,match='duplicate'):regional.poisson_template_auxiliary(d,[],source='s',statement='x',independence='x')


@pytest.mark.parametrize('change',[
    lambda d:d['template_statistics']['experiments'][0].update(exposure='4'),
    lambda d:d['terms'][-1]['log_response'][-1].__setitem__(0,'1'),
    lambda d:d['terms'][0]['coefficients'].__setitem__(-1,'1'),
    lambda d:d['bins'][-1].update(observation_id=d['bins'][0]['observation_id']),
    lambda d:d['bins'][-1].update(observed=.5),
    lambda d:d['template_statistics'].update(kind='weighted_sumw2'),
    lambda d:d['template_statistics'].update(experiments=[]),
])
def test_mc_full_sampling_refusals(tmp_path,change):
    d=with_mc(tmp_path);change(d)
    with pytest.raises(ValueError):regional.validate(d)


@pytest.mark.parametrize('change',[
    lambda s:s['candidates'][1]['parameters'][1].update(bounds=['-100','100']),
    lambda s:s['candidates'][1]['family'].update(slope_log_response=[['10','10']]),
    lambda s:s['candidates'][1]['parameters'][1].update(role='rate'),
    lambda s:s['candidates'][1]['family'].update(slopes=['missing']),
    lambda s:s['bin_windows'].__setitem__(0,['0','2']),
    lambda s:s['bin_windows'].__setitem__(0,['1','1.000000000000000000001']),
    lambda s:s['candidates'][1]['family'].update(expression='arbitrary()'),
])
def test_closed_source_and_whole_slope_domain_refusals(tmp_path,change):
    s=exp_spec(tmp_path);change(s)
    with pytest.raises(ValueError):background.construct(s)


def test_full_ordinary_native_admission_sources_roles_and_witness(tmp_path):
    d=with_mc(tmp_path);cp,cfg=native_config(tmp_path,d)
    pub={'schema_version':2,'mode':'native-likelihood','task':{'input':str(cp)},'max_seconds':30}
    paths=science.task_inputs(pub,tmp_path)
    assert Path(shapes.__file__).resolve() in paths
    original=native._configuration(pub['task'],tmp_path);parsed,r=original[0],original[8]
    assert parsed['model']['regions'][-1]=={'channel':'mcBeta','role':'mc_auxiliary'}
    assert 'mcBeta' in regional.datacard(d).decode()
    assert r['law']['finite_mc']['experiments']==d['template_statistics']['experiments']
    from test_statistical_construction import state
    assert regional.native_witness(r,state(d))['ravel_mean_4']==15
    forged=deepcopy(r);forged['shape_factories'][0]+=' '
    with pytest.raises(ValueError,match='lowering changed'):regional.native_bridge_source(forged)
    # An ordinary external card cannot masquerade an MC auxiliary as this
    # construction-only law by dropping the typed source construction.
    bad=deepcopy(cfg);bad['model'].pop('construction');cp.write_text(json.dumps(bad))
    with pytest.raises(ValueError,match='SR/CR'):native._configuration(pub['task'],tmp_path)
    cp.write_text(json.dumps(cfg))
    original=Path(d['sources'][0]['path']);original.write_text('source changed')
    with pytest.raises(ValueError,match='changed'):science.task_inputs(pub,tmp_path)


def test_existing_population_route_exponential_and_full_mc_baseline(tmp_path):
    s=exp_spec(tmp_path);base=s['baseline']
    s['baseline']=regional.poisson_template_auxiliary(base,[{'bin':'mcBeta','rate':'beta','exposure':'3','source':'s','observed':15,'observation_id':'MC/beta'}],source='s',statement='Supplied artificial Poisson rate',independence='Supplied independent auxiliary')
    s['bin_windows'].append(None);s['transfer']['coefficients'].append('0');s['transfer']['log_response'].append(['0','0'])
    _,cfg=native_config(tmp_path,s['baseline']);fit=cfg['fit'];fit.pop('saved_fit');fit.update(points=3,absolute_nll=True)
    h=background.write_native_population(s,tmp_path/'population',runtime=cfg['runtime'],fit=fit,candidate_seconds=[30,40],overhead_seconds=10)
    pub={'schema_version':2,'mode':h['mode'],'task':h['task'],'max_seconds':80}
    assert science.adapter(pub) is discrete
    assert Path(shapes.__file__).resolve() in science.task_inputs(pub,tmp_path)
    entries=discrete._configuration(h['task'],tmp_path)[2]
    assert len(entries)==2 and native._configuration(entries[1]['task'],entries[1]['base'])[8]['shape_factories']
    assert all(e['config']['model']['regions'][-1]['role']=='mc_auxiliary' for e in entries)
    assert h['native_calls_executed']==0 and h['ordinary_admission_pending'] is True


def test_wrong_complete_total_stays_outside_domain_no_clipping(tmp_path):
    d=background.construct(exp_spec(tmp_path,False))[1]['document'];p=regional.initial_point(d)
    p.update(beta='0',exp_yield='0',c='1')
    got=regional.mean_jet(d,p)
    assert got['means'][0]<0 and got['strictly_positive_total'] is False and got['clipping_applied'] is False


def test_emitted_entire_native_mean_graph_matches_python_source_law(tmp_path):
    d=with_mc(tmp_path);p=regional.initial_point(d)
    p.update(c='1/3',beta='7',exp_slope='-1/7',ravel_aux_0='1/2',ravel_aux_1='-1/4')
    compiled=regional.response(d);values={n:float(F(v)) for n,v in p.items()}
    for factory in compiled['shape_factories']+compiled['factories']:
        if factory.startswith('Exponential::'):continue # source density object, not a bin mean
        match=re.fullmatch(r'expr::([A-Za-z0-9_]+)\("(.*)",(.*)\)',factory)
        if match:
            name,expr,args=match.groups();arguments=args.split(',')
            # Resolve actual generated RooFormulaVar argument order, including
            # correlated slope and downstream dynamic fraction functions.
            expr=re.sub(r'@(\d+)',lambda m:repr(values[arguments[int(m[1])]]),expr)
            values[name]=cpp_eval(expr,0)
        else:
            name,args=re.fullmatch(r'sum::(\w+)\((.*)\)',factory).groups()
            values[name]=math.fsum(values[n] for n in args.split(','))
    assert [values[n] for n in compiled['functions']]==pytest.approx(regional.mean_jet(d,p)['means'],rel=2e-13,abs=1e-13)


def test_irregular_partition_reflection_and_extreme_slopes():
    s={'domain':['-7','9'],'bin_windows':[['-7','-6.999'],['-6.999','0'],['0','9']]}
    r={'domain':['-7','9'],'bin_windows':[['8.999','9'],['2','8.999'],['-7','2']]}
    for lam in ('-50','-10','-.1','-.099999','-1e-20','0','1e-20','.099999','.1','10','50'):
        c=F(lam)/16;v,dp=shapes.fractions(s,c);w,dn=shapes.fractions(r,-c)
        assert v==pytest.approx(w,abs=2e-15,rel=5e-13)
        assert dp==pytest.approx([-x for x in dn],abs=5e-14,rel=2e-11)
        assert math.fsum(v)==pytest.approx(1,abs=2e-15)
        assert math.fsum(dp)==pytest.approx(0,abs=8e-14)
        assert v==pytest.approx(list(map(float,oracle(s,c))),abs=2e-15,rel=5e-13)


def test_shape_fixed_coordinate_and_namespace_refuse_before_bundle(tmp_path):
    s=exp_spec(tmp_path,False);s['candidates'][1]['parameters'][1]['fixed']=True
    d=background.construct(s)[1]['document'];p=regional.initial_point(d)
    with pytest.raises(ValueError,match='fixed'):regional.mean_jet(d,{**p,'exp_slope':'1'})
    for name in ('ravel_shape_7_slope','ravel_fraction_0_7','n_obs_binA'):
        bad=deepcopy(s);bad['candidates'][1]['parameters'][1]['name']=name;bad['candidates'][1]['family']['slopes']=[name]
        with pytest.raises(ValueError):background.construct(bad)


def test_subnormal_slope_limit_and_unrepresentable_positive_window_refusal(tmp_path):
    s={'domain':['0','1'],'bin_windows':[['0','1/2'],['1/2','1']]}
    vals,dp=shapes.fractions(s,F(5,10**324))
    assert vals==[.5,.5] and dp==[-.125,.125]
    bad=exp_spec(tmp_path,False);bad['domain']=['0','1'];bad['bin_windows']=[['0',str(F(5,10**324))],None,None,None]
    with pytest.raises(ValueError,match='not representable'):background.construct(bad)
    with pytest.raises(ValueError,match='arithmetic'):shapes.fractions({'domain':['0','1'],'bin_windows':[['0',str(F(5,10**324))]]},F(50))
