"""Supplied-gradient algebra and mocked solver transport; no real fit/density."""
from types import SimpleNamespace
import math
import pytest

from ravel.physics import continuous_fit as cf


def box(x,g,bounds=((0.,1.),),names=('mu',)):
    return cf._box_stationarity(x,g,bounds,names)


def test_published_adverse_supplied_quadratic_is_not_stationary():
    x=5e-8;g=5e8
    old=0. if x<1e-7 and g>0 else g
    assert old==0.
    result=box([x],[g]);assert result['projected_gradient_max']==g
    assert result['active_bounds']==[] and result['bound_slacks'][0]['lower']==x
    # Pure scalar witness, not a likelihood evaluation or optimization.
    assert .5*1e16*x*x==pytest.approx(12.5)
    assert g*(-x)==-25.


@pytest.mark.parametrize('x',[math.nextafter(0.,1.),1e-17,5e-8])
def test_all_positive_physical_slacks_retain_full_gradient(x):
    r=box([x],[1e9]);assert r['projected_coordinate_gradient']==[1e9]
    assert not r['active_bounds'] and not r['near_artificial_bounds']


@pytest.mark.parametrize('g,expected',[(1e9,0.),(-1e9,-1e9),(0.,0.)])
def test_exact_physical_bound_has_correct_one_sided_direction(g,expected):
    r=box([0.],[g]);assert r['projected_coordinate_gradient']==[expected]
    assert r['active_bounds']==[{'parameter':'mu','side':'lower','physical':True}]


@pytest.mark.parametrize('x,g,names',[(1.-5e-8,-1e9,('mu',)),(5e-8,1e9,('transfer_theta',))])
def test_near_artificial_cap_keeps_gradient_and_separate_refusal(x,g,names):
    r=box([x],[g],names=names)
    assert r['projected_coordinate_gradient']==[g] and r['active_bounds']==[]
    assert len(r['near_artificial_bounds'])==1
    assert r['near_artificial_policy']=='conservative_refusal_only_no_gradient_projection'


@pytest.mark.parametrize('x,g,expected',[(1.,-1e9,0.),(1.,1e9,1e9)])
def test_exact_artificial_upper_bound_projects_but_never_is_physical(x,g,expected):
    r=box([x],[g]);assert r['projected_coordinate_gradient']==[expected]
    assert r['active_bounds'][0]['physical'] is False and r['near_artificial_bounds']


@pytest.mark.parametrize('x',[math.nextafter(0.,-1.),math.nextafter(1.,2.),float('nan'),float('inf')])
def test_infeasible_or_nonfinite_coordinate_refuses(x):
    with pytest.raises(ValueError,match='finite and exactly feasible'):box([x],[1.])


@pytest.mark.parametrize('g',[float('nan'),float('inf'),float('-inf')])
def test_nonfinite_gradient_refuses(g):
    with pytest.raises(ValueError):box([.5],[g])


def test_coordinate_gradient_population_cannot_truncate():
    with pytest.raises(ValueError,match='population'):box([.5],[])
    with pytest.raises(ValueError,match='unique'):box([.5,.5],[1.,1.],((0.,1.),(0.,1.)),('mu','mu'))


@pytest.mark.parametrize('mu,g,verified',[(5e-8,5e8,False),(0.,5e8,True),(5e-8,5e-5,True)])
def test_fit_uses_exact_activity_and_retains_full_endpoint(monkeypatch,mu,g,verified):
    np=pytest.importorskip('numpy');opt=pytest.importorskip('scipy.optimize')
    document={'full_range':[0.,5.],'parameters':{
      'mu':{'bounds':[0.,1.],'initial':.3},
      'background_yield':{'bounds':[1.,10.],'initial':2.},
      'slope':{'bounds':[-1.,1.],'initial':0.},
      'transfer_theta':{'bounds':[-8.,8.],'initial':0.}}}
    monkeypatch.setattr(cf,'prepare',lambda d:d)
    mocks=[]
    def supplied(*args,**kw):
        mocks.append(kw['method'])
        return SimpleNamespace(x=np.array([mu,math.log(2.),0.,0.]),success=True,message='Supplied synthetic endpoint; no optimizer',nit=0)
    monkeypatch.setattr(opt,'minimize',supplied)
    monkeypatch.setattr(cf,'evaluate',lambda *a:{'nll':0.,'gradient':[g,0.,0.,0.]})
    monkeypatch.setattr(cf,'independent_quadrature',lambda *a:{'nll':0.})
    monkeypatch.setattr(cf,'identifiability',lambda *a:{'identified':True})
    result=cf.fit(document);assert result['verified'] is verified
    assert mocks==['L-BFGS-B','L-BFGS-B','SLSQP','SLSQP']
    assert len(result['attempts'])==4
    for row in result['attempts']:
        assert row['verified'] is verified
        assert row['stationarity']['coordinates'][0]==mu
        assert row['stationarity']['coordinate_gradient'][0]==g
        assert row['projected_gradient_max']==(0. if mu==0. else abs(g))


def test_conservative_artificial_cap_guard_is_still_used_by_fit(monkeypatch):
    np=pytest.importorskip('numpy');opt=pytest.importorskip('scipy.optimize')
    d={'full_range':[0.,5.],'parameters':{
      'mu':{'bounds':[0.,1.],'initial':.3},'background_yield':{'bounds':[1.,10.],'initial':2.},
      'slope':{'bounds':[-1.,1.],'initial':0.},'transfer_theta':{'bounds':[-8.,8.],'initial':0.}}}
    monkeypatch.setattr(cf,'prepare',lambda x:x)
    monkeypatch.setattr(opt,'minimize',lambda *a,**kw:SimpleNamespace(x=np.array([.3,5e-8,0.,0.]),success=True,message='Synthetic',nit=0))
    monkeypatch.setattr(cf,'evaluate',lambda *a:{'nll':0.,'gradient':[0.,0.,0.,0.]})
    monkeypatch.setattr(cf,'independent_quadrature',lambda *a:{'nll':0.})
    monkeypatch.setattr(cf,'identifiability',lambda *a:{'identified':True})
    r=cf.fit(d);assert not r['verified']
    assert all(a['projected_gradient_max']==0 and a['stationarity']['near_artificial_bounds'] for a in r['attempts'])
