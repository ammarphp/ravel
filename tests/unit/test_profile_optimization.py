"""Profile-likelihood numerical controls, independent of old scan baselines."""
from types import SimpleNamespace
import json
import sys

import numpy as np
import pytest
from scipy.optimize import brentq, minimize, OptimizeResult

from ravel.physics import pyhf_exclude as engine


@pytest.fixture(autouse=True)
def reset_optimizer_state():
    engine.robust_optimizer.escalated = False
    yield
    engine.robust_optimizer.escalated = False


@pytest.mark.parametrize("gradient", [False, True])
def test_successful_local_minimum_is_improved_from_other_basin(gradient):
    # Tilted double well: two valid stationary local minima, one globally lower.
    # An optimizer success flag and tiny gradient do not choose the correct basin.
    value = lambda x: (x[0] ** 2 - 1) ** 2 + .2 * x[0]
    jac = lambda x: np.array([4 * x[0] * (x[0] ** 2 - 1) + .2])
    function = (lambda x: (value(x), jac(x))) if gradient else value
    lower = brentq(lambda x: 4 * x * (x*x - 1) + .2, -1.2, -.8)
    optimizer = engine.robust_optimizer(tolerance=1e-10)
    first = optimizer._minimize(minimize, function, [1.], do_grad=gradient, bounds=[(-2, 2)])
    assert first.success and first.x[0] > 0 and abs(jac(first.x)[0]) < 1e-4
    optimizer.begin_model()
    optimizer._profile_pool = [np.array([-1.])]
    repaired = optimizer._minimize(minimize, function, [1.], do_grad=gradient, bounds=[(-2, 2)])
    assert repaired.fun < first.fun - .39
    np.testing.assert_allclose(repaired.x, [lower], atol=1e-5)
    assert optimizer.profile_improvements == 1


def test_prior_start_is_rescored_on_current_objective_and_fixed_coordinates():
    optimizer = engine.robust_optimizer(tolerance=1e-10)
    optimizer.begin_model()
    optimizer._profile_pool = [np.array([-1., -100.]), np.array([1., 100.])]
    value = lambda x: (x[0] + 1.) ** 2 + (x[1] - 7.) ** 2
    result = optimizer._minimize(minimize, value, [1., 2.], bounds=[(-2, 2), (0, 10)],
                                 fixed_vals=[(1, 7.)])
    np.testing.assert_allclose(result.x, [-1., 7.], atol=1e-5)


def test_gradient_path_detects_nonfinite_objective_visits(monkeypatch):
    optimizer = engine.robust_optimizer(tolerance=1e-9)
    visited = []
    def function(x):
        return (float('nan'), np.array([float('nan')])) if x[0] < 0 else ((x[0]-2)**2, np.array([2*(x[0]-2)]))
    def false_success(fun, x0, **kwargs):
        fun(np.array([-1.]))
        return OptimizeResult(x=np.array([1.]), fun=1., success=True)
    def fallback(func, x0, bounds, fixed_vals, gradient=None):
        visited.append(float(func(np.array([2.]))))
        np.testing.assert_allclose(gradient(np.array([2.])), [0.])
        return OptimizeResult(x=np.array([2.]),fun=0.,success=True)
    monkeypatch.setattr(optimizer,'_migrad',fallback)
    result=optimizer._minimize(false_success,function,[1.],do_grad=True,bounds=[(0,3)])
    assert visited == [0.] and engine.robust_optimizer.escalated
    assert result.fun == 0.


def test_inference_start_resets_retained_model_parameters():
    optimizer=engine.robust_optimizer()
    optimizer.begin_model();optimizer._profile_pool=[np.array([1.])]
    optimizer.profile_improvements=2
    optimizer.begin_model()
    assert optimizer._profile_pool == [] and optimizer.profile_improvements == 0


def _fits(**changes):
    values=dict(asimov_pars=[0.],free_fit_to_data=[0.],fixed_poi_fit_to_data=[1.],
                free_fit_to_asimov=[0.],fixed_poi_fit_to_asimov=[1.])
    values.update(changes)
    return SimpleNamespace(**values)


def test_profile_nesting_rejects_false_success_with_positive_controls(monkeypatch):
    # Asimov generator is a known optimum, while fixed POI=1 costs one unit.
    model=SimpleNamespace(expected_data=lambda _: [0.])
    monkeypatch.setattr(engine.pyhf.infer.mle,'twice_nll',lambda p,data,model:np.array([p[0]**2]))
    assert engine.profile_fit_consistency(model,[0.],_fits())['passed']
    invalid=_fits(free_fit_to_data=[.1])
    assert not engine.profile_fit_consistency(model,[0.],invalid)['passed']
    invalid=_fits(free_fit_to_asimov=[.1])
    assert not engine.profile_fit_consistency(model,[0.],invalid)['passed']


@pytest.mark.parametrize('bad',['0','-1','nan','inf','1','2'])
def test_cli_rejects_invalid_fit_tolerance_before_reading_inputs(monkeypatch,bad):
    monkeypatch.setattr(sys,'argv',['pyhf','likelihood','--bkg','absent','--patch','absent',
                       '--out','unused','--fit-tolerance',bad])
    with pytest.raises(SystemExit) as error:engine.main()
    assert error.value.code == 2


def test_requested_backend_failure_is_not_silently_replaced(monkeypatch,tmp_path):
    monkeypatch.setattr(sys,'argv',['pyhf','likelihood','--bkg','absent','--patch','absent',
        '--out',str(tmp_path/'out'),'--backend','jax'])
    monkeypatch.setattr(engine.pyhf,'set_backend',lambda *a,**kw:(_ for _ in ()).throw(ImportError('missing requested JAX')))
    with pytest.raises(SystemExit) as error:engine.main()
    assert error.value.code == 2 and not (tmp_path/'out').exists()


def test_transient_invalid_gradient_trial_requires_profile_context(monkeypatch):
    def function(x):
        return (float('nan'), np.array([float('nan')])) if x[0] < 0 else ((x[0]-2)**2, np.array([2*(x[0]-2)]))
    def recovered(fun, x0, **kwargs):
        fun(np.array([-1.]))
        return OptimizeResult(x=np.array([2.]), fun=0., success=True)
    calls = []
    def fallback(*args, **kwargs):
        calls.append(True)
        return OptimizeResult(x=np.array([2.]), fun=0., success=True)
    optimizer = engine.robust_optimizer(tolerance=1e-9)
    monkeypatch.setattr(optimizer, '_migrad', fallback)
    optimizer._minimize(recovered, function, [1.], do_grad=True, bounds=[(0,3)])
    assert calls == [True] and engine.robust_optimizer.escalated
    engine.robust_optimizer.escalated = False
    optimizer.begin_model()
    calls.clear()
    result = optimizer._minimize(recovered, function, [1.], do_grad=True, bounds=[(0,3)])
    assert result.fun == 0. and calls == []
    assert not engine.robust_optimizer.escalated
    assert optimizer.profile_recovered_transients == 1
    assert optimizer.profile_invalid_trials == 1


@pytest.mark.parametrize('invalid_visit', [False, True])
def test_successful_unchanged_nonstationary_analytic_init_is_rejected(monkeypatch, invalid_visit):
    optimizer = engine.robust_optimizer(tolerance=1e-9)
    optimizer.begin_model()
    def function(x):
        return ((x[0]-2)**2, np.array([2*(x[0]-2)])) if x[0]>=0 else (np.nan,np.array([np.nan]))
    def false_success(fun, x0, **kwargs):
        if invalid_visit: fun(np.array([-1.]))
        return OptimizeResult(x=np.array([1.]),fun=1.,success=True)
    calls=[]
    def fallback(*args, **kwargs):
        calls.append(True)
        return OptimizeResult(x=np.array([2.]),fun=0.,success=True)
    monkeypatch.setattr(optimizer, '_migrad', fallback)
    result=optimizer._minimize(false_success,function,[1.],do_grad=True,bounds=[(0,3)])
    assert result.fun == 0. and calls == [True]
    assert not engine.robust_optimizer.escalated
    assert optimizer.profile_rejected_candidates[0]['projected_gradient_max'] == 2.


def test_projected_gradient_checks_feasible_descent_and_fixed_coordinates():
    project = engine.robust_optimizer.projected_gradient
    # x^2 on [1,2] minimizes at 1; derivative +2 cannot descend inside the interval.
    assert project([1.], [2.], [(1,2)], []) == 0.
    assert project([1.], [-2.], [(1,2)], []) == 2.
    assert project([2.], [-2.], [(1,2)], []) == 0.
    assert project([2.], [2.], [(1,2)], []) == 2.
    assert project([1.], [20.], [(0,2)], [(0,1.)]) == 0.
    assert project([1.], [np.nan], [(0,2)], []) == float('inf')


def test_monotonic_discontinuous_curve_cannot_be_reported_as_root(monkeypatch):
    model,data = engine.model_from_counting({'n':10,'b':10,'db':2,'s':4})
    def discontinuous(mu, *args, **kwargs):
        value=.1 if mu<.731 else .01
        return value, [value]*5
    monkeypatch.setattr(engine,'hypotest',discontinuous)
    with pytest.raises(RuntimeError,match='unstable'):
        engine.compute(model,data,n_curve=2)


def test_repeated_root_evaluation_drift_cannot_be_hidden_by_cache(monkeypatch):
    model,data = engine.model_from_counting({'n':10,'b':10,'db':2,'s':4})
    counts={}
    def unstable(mu,*args,**kwargs):
        counts[mu]=counts.get(mu,0)+1
        scale=1 if counts[mu]%2 else 1.02
        value=float(np.exp(-4*mu*scale))
        return value,[value]*5
    monkeypatch.setattr(engine,'hypotest',unstable)
    with pytest.raises(RuntimeError,match='unstable|monotonically'):
        engine.compute(model,data,n_curve=2)


def test_smooth_stable_curve_passes_fresh_root_checks(monkeypatch):
    model,data = engine.model_from_counting({'n':10,'b':10,'db':2,'s':4})
    def stable(mu,*args,**kwargs):
        value=float(np.exp(-4*mu))
        return value,[value]*5
    monkeypatch.setattr(engine,'hypotest',stable)
    result=engine.compute(model,data,n_curve=2)
    assert result['obs_limit'] == pytest.approx(-np.log(.05)/4,rel=1e-4)
    assert result['inference']['fresh_check_evaluations'] >= 3
    assert result['inference']['root_cls_max_error'] < 5e-4


def test_analytic_migrad_valid_flag_requires_stationarity(monkeypatch):
    class FakeMinuit:
        def __init__(self, objective, *x, grad=None):
            self.values=list(x); self.fval=float(objective(*x))
            self.limits=[None]*len(x);self.fixed=[False]*len(x)
            self.valid=True;self.fmin=SimpleNamespace(edm=0.);self.nfcn=1
        def migrad(self,**kwargs):pass
    monkeypatch.setitem(sys.modules,'iminuit',SimpleNamespace(Minuit=FakeMinuit))
    with pytest.raises(RuntimeError,match='stationary'):
        engine.robust_optimizer._migrad(lambda x:x[0]**2,[1.],[(-2,2)],[],gradient=lambda x:2*x)
    result=engine.robust_optimizer._migrad(lambda x:x[0]**2,[0.],[(-2,2)],[],gradient=lambda x:2*x)
    assert result.fun == 0.


def test_narrow_bounds_do_not_mask_interior_gradient_or_out_of_range_fit():
    optimizer=engine.robust_optimizer
    assert optimizer.projected_gradient([5e-9],[1e9],[(0,1e-8)],[]) == 1e9
    assert not optimizer._valid_result([5e-8],50.,lambda x:1e9*x[0],[(0,1e-8)],[])
    assert optimizer._valid_result([5e-9],5.,lambda x:1e9*x[0],[(0,1e-8)],[])
    assert optimizer.projected_gradient([0.],[1e9],[(0,1e-8)],[]) == 0.


def test_unguarded_optimizer_is_not_labeled_as_validated_profile():
    old=engine.pyhf.get_backend()
    model,data=engine.model_from_counting({'n':10,'b':10,'db':2,'s':4})
    try:
        engine.pyhf.set_backend('numpy',engine.scipy_optimizer())
        with pytest.raises(ValueError,match='requires robust_optimizer'):
            engine.compute(model,data)
    finally:
        engine.pyhf.set_backend(*old)


def test_cli_success_records_explicit_backend_and_input_hashes(tmp_path,monkeypatch):
    source=tmp_path/'srs.json';source.write_text(json.dumps([{'name':'SR','n':10,'b':10,'db':2,'s':4}]))
    out=tmp_path/'out'
    monkeypatch.setattr(sys,'argv',['pyhf','counting','--srs',str(source),'--out',str(out),
        '--backend','numpy','--fit-tolerance','1e-8'])
    monkeypatch.setattr(engine,'plot',lambda *args,**kwargs:None)
    engine.main()
    result=json.loads((out/'exclusion.json').read_text())
    provenance=result['execution_provenance']
    assert provenance['backend'] == 'numpy' and provenance['precision'] == '64b'
    assert provenance['fit_tolerance'] == 1e-8
    import hashlib
    assert provenance['inputs'][0]['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert provenance['dependencies']['pyhf'] == engine.pyhf.__version__
    assert not (out/'inference_failure.json').exists()


def test_cli_failure_preserves_pinned_attempt_without_emitting_limit(tmp_path,monkeypatch):
    source=tmp_path/'srs.json';source.write_text(json.dumps([{'name':'SR','n':10,'b':10,'db':2,'s':4}]))
    out=tmp_path/'out'
    monkeypatch.setattr(sys,'argv',['pyhf','counting','--srs',str(source),'--out',str(out)])
    def failed(*args,**kwargs):raise RuntimeError('ordinary numerical failure')
    monkeypatch.setattr(engine,'hypotest',failed)
    for _ in range(2):
        with pytest.raises(RuntimeError,match='ordinary numerical failure'):engine.main()
    records=list(out.glob('inference_failure*.json'))
    assert len(records) == 2 and not (out/'exclusion.json').exists()
    for path in records:
        report=json.loads(path.read_text())
        assert report['status'] == report['diagnostics']['status'] == 'failed'
        assert report['execution_provenance']['inputs'][0]['path'] == str(source)
        assert report['diagnostics']['evaluations'][0]['status'] == 'failed'
        assert len(report['diagnostics']['model_sha256']) == 64


def test_final_root_checks_use_immutable_portfolio_and_both_orders(monkeypatch):
    optimizer=engine.robust_optimizer()
    old=engine.pyhf.get_backend();engine.pyhf.set_backend('numpy',optimizer)
    try:
        model,data=engine.model_from_counting({'n':10,'b':10,'db':2,'s':4})
        visits={}; discovery=[False]
        def late_branch(mu,*args,**kwargs):
            visits[mu]=visits.get(mu,0)+1
            if mu == .001 and visits[mu] == 2:discovery[0]=True
            if mu <= .001:return 1.,[1.]*5
            value=float(np.exp(-4*mu)) * (.02 if discovery[0] else 1.)
            return value,[value]*5
        monkeypatch.setattr(engine,'hypotest',late_branch)
        # The late branch has a jump near the low endpoint. It cannot be served
        # as either the old smooth root or a new discontinuity-as-root.
        with pytest.raises(RuntimeError,match='unstable|monotonically'):
            engine.compute(model,data,n_curve=2)
        assert not optimizer._profile_enabled and not optimizer._profile_frozen
    finally:engine.pyhf.set_backend(*old)
