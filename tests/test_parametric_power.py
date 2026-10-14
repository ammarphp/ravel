"""Independent analytic and inert ordinary controls; no ROOT/model/fit calls."""
from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction as F
import ast
import json
import math
from pathlib import Path
import re

import pytest
from ravel.physics import background_construction as background, parametric_shapes as shapes
from ravel.physics import statistical_construction as regional, native_likelihood as native
from ravel.workflow import science
from test_background_construction import specification
from test_parametric_exponential import cpp_eval
from test_statistical_construction import native_config


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    monkeypatch.setattr(native,'_process',lambda *a,**k: (_ for _ in ()).throw(AssertionError('native forbidden')))


def power_spec(tmp_path, correlated=True):
    s=specification(tmp_path,correlated)
    y=deepcopy(s['candidates'][0]['parameters'][0]);y['name']='power_yield'
    p=deepcopy(y);p.update(name='power_exponent',role='coefficient',initial='-1',bounds=['-4','4'],meaning='dimensionless exponent of (x/a)**p; no unit conversion')
    s['candidates'][1]={'id':'power','family':{'kind':'floating_power','exponents':['power_exponent'],
      'exponent_response':[['1/5','-1/10'] if correlated else []]},'parameters':[y,p],'source':'s'}
    return s


def oracle(shape,p):
    # Independent Decimal physical-x antiderivatives and analytic derivatives.
    # Does not use the production log-coordinate/sinhc/expm1 implementation.
    with localcontext() as ctx:
        ctx.prec=150
        D=lambda v: Decimal(F(v).numerator)/Decimal(F(v).denominator)
        a,b=map(D,shape['domain']);n=D(p)+1;la=a.ln();lb=b.ln()
        result=[];derivative=[]
        for w in shape['bin_windows']:
            if w is None: result.append(Decimal(0));derivative.append(Decimal(0));continue
            u,v=map(D,w);lu=u.ln();lv=v.ln()
            if n==0:
                f=(lv-lu)/(lb-la);df=f*(lu+lv-la-lb)/2
            else:
                A=(n*lv).exp()-(n*lu).exp();T=(n*lb).exp()-(n*la).exp()
                f=A/T;df=f*((lv*(n*lv).exp()-lu*(n*lu).exp())/A-(lb*(n*lb).exp()-la*(n*la).exp())/T)
            result.append(f);derivative.append(df)
        return list(map(float,result)),list(map(float,derivative))


@pytest.mark.parametrize('p',['-4','-2','-1.000000001','-1.000000000000000000000000000001','-1','-0.999999999999999999999999999999','-0.999999999','-1e-30','0','1e-30','1/3','4'])
def test_analytic_full_integrals_derivatives_and_native_formula(p):
    s={'kind':'normalized_power','domain':['1','9'],'bin_windows':[['1','1.01'],['1.01','3'],['3','9'],None]}
    values,derivatives=shapes.fractions(s,F(p));expected,ds=oracle(s,p)
    assert values==pytest.approx(expected,rel=8e-13,abs=3e-15)
    assert derivatives==pytest.approx(ds,rel=2e-10,abs=2e-13)
    assert math.fsum(values)==pytest.approx(1,abs=3e-15)
    assert math.fsum(derivatives)==pytest.approx(0,abs=3e-14)
    L,windows=shapes.power_geometry(s['domain'],s['bin_windows'])
    emitted=[0. if w is None else cpp_eval(shapes.native_power_fraction_expression(s,i,L,w),float((F(p)+1)*L)) for i,w in enumerate(windows)]
    assert emitted==pytest.approx(expected,rel=8e-13,abs=3e-15)
    if F(p)==0:
        assert values==[float(F(1,800)),float(F(199,800)),.75,0.]
        assert emitted==values and derivatives[0] != 0


@pytest.mark.parametrize('scale',['1e-300','1e-150','1','1e150','1e300'])
@pytest.mark.parametrize('p',['-1','0','2/3'])
def test_units_scale_close_edges_and_unobserved_mass(scale,p):
    a=F(scale);s={'kind':'normalized_power','domain':[str(a),str(3*a)],
      'bin_windows':[[str(a),str(a*(1+F(1,10**10)))],[str(2*a),str(3*a)],None]}
    values,ds=shapes.fractions(s,F(p));v,d=oracle(s,p)
    assert values==pytest.approx(v,abs=3e-15,rel=2e-12)
    assert ds==pytest.approx(d,abs=3e-14,rel=2e-10)
    assert math.fsum(values)<1 # Full normalization mass outside selected windows.
    unit={'kind':'normalized_power','domain':['1','3'],'bin_windows':[['1','1.0000000001'],['2','3'],None]}
    assert shapes.fractions(unit,F(p))[0]==pytest.approx(values,rel=3e-13,abs=2e-15)


def test_close_complete_domain_and_log_limit():
    s={'kind':'normalized_power','domain':['1','1.000000000000001'],
       'bin_windows':[['1','1.0000000000000004'],['1.0000000000000004','1.000000000000001']]}
    for p in (-1,0,1):
        v,d=shapes.fractions(s,p);expected,ds=oracle(s,p)
        assert v==pytest.approx(expected,abs=2e-15) and d==pytest.approx(ds,abs=1e-28)
    assert shapes.fractions(s,0)[0]==[.4,.6]


@pytest.mark.parametrize('q',['-50','-10','-.1','-.001','0','.001','.1','10','50'])
def test_complete_dimensionless_envelope_and_refusal(q):
    s={'kind':'normalized_power','domain':['1','3'],'bin_windows':[['1','1.001'],['1.001','2'],['2','3']]}
    length,windows=shapes.power_geometry(s['domain'],s['bin_windows']);p=F(q)/length-1
    v,d=shapes.fractions(s,p);expected,ds=oracle(s,p)
    assert v==pytest.approx(expected,rel=1e-12,abs=3e-15)
    assert d==pytest.approx(ds,rel=3e-10,abs=5e-14)
    assert math.fsum(v)==pytest.approx(1,abs=3e-15)
    if abs(F(q))==50:
        beyond=p+F(1,1000000)*(1 if F(q)>0 else -1)
        with pytest.raises(ValueError,match='envelope'):shapes.fractions(s,beyond)


def test_mixture_fixed_coordinates_and_shape_population(tmp_path):
    s=power_spec(tmp_path,False);candidate=s['candidates'][1];y,p=candidate['parameters']
    y['fixed']=True;p['fixed']=True
    y2=deepcopy(y);y2.update(name='second_yield',fixed=False)
    p2=deepcopy(p);p2.update(name='second_exponent',initial='0',fixed=False)
    candidate['parameters']=[y,y2,p,p2]
    candidate['family'].update(exponents=['power_exponent','second_exponent'],exponent_response=[[],[]])
    row=background.construct(s)[1];d=row['document'];point=regional.initial_point(d)
    assert row['floating_background_coefficients']==2 and row['penalty_nll']=='1'
    compiled=regional.response(d)
    assert sum('Exponential::' in v for v in compiled['shape_factories'])==2
    assert all(t['shape']['kind']=='normalized_power' for t in d['terms'][-2:])
    with pytest.raises(ValueError,match='fixed'):regional.mean_jet(d,{**point,'power_exponent':'0'})


def test_full_law_correlated_response_mixed_derivatives_and_signed_controls(tmp_path):
    s=power_spec(tmp_path);s['transfer']['powers']={'kappa':1};s['transfer']['log_response'][0]=['2','-1']
    row=background.construct(s)[1];d=row['document'];point=regional.initial_point(d)
    point.update(c='1',power_exponent='-1',ravel_aux_0='1/3',ravel_aux_1='-1/4')
    got=regional.mean_jet(d,point)
    assert row['integrated_fractions'] is None and row['penalty_nll']=='1'
    assert d['terms'][:-1]==s['baseline']['terms']
    for key in ('auxiliary','bins','partition','prediction','template_statistics','assumptions'):assert d[key]==s['baseline'][key]
    assert any(v<0 for v in got['term_values'][0]) and not got['clipping_applied']
    # Independent chain rule from physical-x oracle: theta0=eta0,
    # theta1=.6eta0+.8eta1, hence dp/deta0=.14, dp/deta1=-.08.
    theta0=F(1,3);theta1=F(3,5)*theta0+F(4,5)*F(-1,4)
    p=F(-1)+F(1,5)*theta0-F(1,10)*theta1
    shape=d['terms'][-1]['shape'];vals,ds=oracle(shape,p)
    w=math.exp(float(2*theta0-theta1));y=4
    baseline=regional.mean_jet(s['baseline'],{k:v for k,v in point.items() if k not in ('power_yield','power_exponent')})
    assert got['means'][0]==pytest.approx(baseline['means'][0]+y*w*vals[0])
    for name,dp,dlog in [('ravel_aux_0',.14,1.4),('ravel_aux_1',-.08,-.8)]:
        j=got['coordinates'].index(name)
        assert got['jacobian'][0][j]==pytest.approx(baseline['jacobian'][0][baseline['coordinates'].index(name)]+y*w*(ds[0]*dp+vals[0]*dlog),rel=3e-12)
    for j,name in enumerate(got['coordinates']):
        if name=='kappa':continue
        h=F(1,10**6);low={**point,name:str(F(point[name])-h)};high={**point,name:str(F(point[name])+h)}
        deriv=[(b-a)/(2*float(h)) for a,b in zip(regional.mean_jet(d,low)['means'],regional.mean_jet(d,high)['means'])]
        assert [r[j] for r in got['jacobian']]==pytest.approx(deriv,abs=2e-7,rel=2e-6)


@pytest.mark.parametrize('change',[
    lambda s:s.update(domain=['0','3']),lambda s:s.update(domain=['-1','3']),
    lambda s:s.update(domain=['1e-200','1e200']),
    lambda s:s['candidates'][1]['parameters'][1].update(bounds=['-100','100']),
    lambda s:s['candidates'][1]['family'].update(exponent_response=[['100','100']]),
    lambda s:s['candidates'][1]['family'].update(exponents=['missing']),
    lambda s:s['candidates'][1]['parameters'][1].update(role='rate'),
    lambda s:s['candidates'][1]['family'].update(expression='user_expression'),
    lambda s:s['bin_windows'].__setitem__(0,['1','1.000000000000000000001']),
    lambda s:s['candidates'][1].update(source='unbound'),
])
def test_complete_domain_and_source_refusals(tmp_path,change):
    s=power_spec(tmp_path);change(s)
    with pytest.raises(ValueError):background.construct(s)


def test_complete_native_mean_graph_and_source_factory(tmp_path):
    d=background.construct(power_spec(tmp_path))[1]['document'];p=regional.initial_point(d)
    p.update(c='1/3',beta='7',power_exponent='-1',ravel_aux_0='1/2',ravel_aux_1='-1/4')
    compiled=regional.response(d);code=regional.native_bridge_source(compiled);ast.parse(code)
    values={n:float(F(v)) for n,v in p.items()}
    for factory in compiled['shape_factories']+compiled['factories']:
        if factory.startswith('Exponential::'):continue
        m=re.fullmatch(r'expr::([A-Za-z0-9_]+)\("(.*)",(.*)\)',factory)
        if m:
            name,expr,args=m.groups();arguments=args.split(',')
            expr=re.sub(r'@(\d+)',lambda m:repr(values[arguments[int(m[1])]]),expr);values[name]=cpp_eval(expr,0)
        else:
            name,args=re.fullmatch(r'sum::(\w+)\((.*)\)',factory).groups();values[name]=math.fsum(values[n] for n in args.split(','))
    assert [values[n] for n in compiled['functions']]==pytest.approx(regional.mean_jet(d,p)['means'],rel=3e-13,abs=1e-13)
    forged=deepcopy(compiled);forged['shape_factories'][0]+=' '
    with pytest.raises(ValueError,match='lowering changed'):regional.native_bridge_source(forged)


def test_real_ordinary_population_unapproved_plan_and_source_refusal(tmp_path):
    s=power_spec(tmp_path);_,cfg=native_config(tmp_path,s['baseline']);fit=cfg['fit']
    fit.pop('saved_fit');fit.update(points=3,absolute_nll=True)
    h=background.write_native_population(s,tmp_path/'population',runtime=cfg['runtime'],fit=fit,candidate_seconds=[30,40],overhead_seconds=10)
    actors={r:'PENDING-'+r for r in ('proposer','executor','physics_critic','skeptical_verifier','physics_decider')}
    policy={'schema_version':1,'actors':actors,'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
      'required_checks':[{'id':'complete_source','kind':'integrity'}],'claim_scopes':{'source_construction':{'checks':['complete_source'],'actions':['delivery']}}}
    spec={'schema_version':2,'mode':h['mode'],'task':h['task'],'source':'Artificial floating-power engineering preparation, no physics claim.',
      'assumptions':['Source construction only; native integration/fits/calibration unqualified.'],'max_seconds':80,'max_attempts':1,'approval_mode':'scripted_yes',
      'review_policy':{'schema_version':1,'policy':policy,'correction_contract':{'task_fields':[],'input_slots':[]}}}
    path=tmp_path/'spec.json';path.write_text(json.dumps(spec));rd=tmp_path/'unapproved'
    proposal=science.plan(rd,path)
    assert proposal['schema_version']==2 and not (rd/science.APPROVAL).exists() and not (rd/'outputs').exists()
    science.verify_plan(rd,approved=False)
    assert Path(shapes.__file__).resolve() in science.task_inputs(spec,tmp_path)
    Path(s['baseline']['sources'][0]['path']).write_text('Changed source')
    with pytest.raises(ValueError):science.verify_plan(rd,approved=False)


def test_mc_normalization_and_nonpositive_full_domain_preserved(tmp_path):
    d=background.construct(power_spec(tmp_path))[1]['document']
    d=regional.poisson_template_auxiliary(d,[{'bin':'MC','rate':'beta','exposure':'3','source':'s','observed':15,'observation_id':'independent/MC'}],source='s',statement='Artificial source MC law',independence='Independent artificial unweighted Poisson experiment')
    assert d['terms'][-2]['shape']['bin_windows'][-1] is None
    point=regional.initial_point(d);got=regional.mean_jet(d,point)
    assert got['means'][-1]==15 and got['jacobian'][-1][got['coordinates'].index('beta')]==3
    point.update(beta='0',power_yield='0',c='1');got=regional.mean_jet(d,point)
    assert got['means'][0]<0 and not got['strictly_positive_total'] and not got['clipping_applied']
