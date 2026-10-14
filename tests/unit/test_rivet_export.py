"""YODA 2 integration checks; enabled with the native Rivet interpreter."""
import math
import sys
from types import SimpleNamespace
import pytest
from ravel.physics.rivet_export import export


def setup(tmp_path,normalized=False):
    yoda=pytest.importorskip('yoda')
    if not str(yoda.__version__).startswith('2.'): pytest.skip('requires YODA2')
    h=yoda.Histo1D([0.,1.,3.],'/RAW/TEST/h')
    h.fill(.5,2); h.fill(2.,1)
    final=h.clone(); final.setPath('/TEST/h'); final.scaleW(1/3 if normalized else 1)
    e=final.mkEstimate(source='stats')
    e.setPath('/TEST/h')
    yoda.write([h,e],str(tmp_path/'file.yoda'))
    request={'path':'/TEST/h','axes':[{'name':'x','unit':'GeV'}],
             'representation':'differential','normalization':'normalized' if normalized else 'absolute','unit':'1/GeV' if normalized else 'pb/GeV'}
    return tmp_path/'file.yoda',request


def test_finalized_density_is_not_divided_by_width_twice(tmp_path):
    p,r=setup(tmp_path)
    x=export(p,[r])['observables']['/TEST/h']
    assert [b['value'] for b in x['bins']]==[2,.5]
    assert [b['error_low'] for b in x['bins']]==[2,.5]
    r['representation']='integrated'
    assert [b['value'] for b in export(p,[r])['observables']['/TEST/h']['bins']]==[2,1]


def test_unit_area_not_claimed_from_label(tmp_path):
    p,r=setup(tmp_path)
    r['normalization']='normalized'
    r['unit']='1/GeV'
    with pytest.raises(ValueError,match='unit integrated area'): export(p,[r])


def test_normalized_integral_and_missing_observable(tmp_path):
    p,r=setup(tmp_path,normalized=True)
    bins=export(p,[r])['observables']['/TEST/h']['bins']
    assert math.fsum(b['integrated_sumw'] for b in bins)==pytest.approx(1)
    r['path']='/TEST/missing'
    with pytest.raises(ValueError,match='missing'): export(p,[r])


@pytest.mark.parametrize('defect',['partial','dimension'])
def test_finalized_raw_geometry_must_be_complete(tmp_path,defect):
    p,r=setup(tmp_path)
    import yoda
    objects=yoda.read(str(p))
    if defect=='partial':
        h=yoda.Histo1D([0.,1.]);h.fill(.5,1)
        e=h.mkEstimate(source='stats');e.setPath('/TEST/h');objects['/TEST/h']=e
    else:
        raw=yoda.Histo2D([0.,1.,3.],[0.,1.]);raw.setPath('/RAW/TEST/h');objects['/RAW/TEST/h']=raw
    yoda.write(objects,str(p))
    with pytest.raises(ValueError,match='binning differ'): export(p,[r])


def test_normalized_units_cannot_claim_cross_section(tmp_path):
    p,r=setup(tmp_path,normalized=True);r['unit']='pb/GeV'
    with pytest.raises(ValueError,match='normalized quantity unit'): export(p,[r])


def scalar_request(path='/TEST/count'):
    return {'path': path, 'axes': [], 'representation': 'integrated',
            'normalization': 'absolute', 'unit': 'pb', 'quantity_kind': 'scalar_counter'}


@pytest.mark.parametrize('estimate', [False, True])
@pytest.mark.parametrize('weights', [(2., -1.), (), (-2.,)])
def test_actual_yoda_scalar_retains_scaled_final_and_raw_moments(tmp_path, estimate, weights):
    yoda = pytest.importorskip('yoda')
    if not str(yoda.__version__).startswith('2.'):
        pytest.skip('requires YODA2')
    raw = yoda.Counter('/RAW/TEST/count')
    for weight in weights:
        raw.fill(weight)
    final = raw.clone()
    final.scaleW(3.)
    if estimate:
        final = final.mkEstimate(source='stats')
    final.setPath('/TEST/count')
    path = tmp_path/'counter.yoda'
    yoda.write([raw, final], str(path))
    result = export(path, [scalar_request()])['observables']['/TEST/count']
    expected_raw = {'sumw': math.fsum(weights), 'sumw2': math.fsum(w*w for w in weights),
                    'entries': float(len(weights))}
    assert result['raw_counter'] == expected_raw
    assert result['quantity_kind'] == 'scalar_counter'
    assert len(result['bins']) == 1
    row = result['bins'][0]
    assert row['low'] == row['high'] == []
    assert row['value'] == pytest.approx(3*expected_raw['sumw'])
    assert row['entries'] == expected_raw['entries']
    assert row['variance'] == pytest.approx(9*expected_raw['sumw2'])
    assert row['error_low'] == row['error_high'] == pytest.approx(math.sqrt(9*expected_raw['sumw2']))
    assert result['flow_sumw'] is result['flow_sumw2'] is result['raw_flow_sumw'] is None
    if estimate:
        assert result['final_counter'] is None
    else:
        assert result['final_counter'] == {'sumw': 3*expected_raw['sumw'],
                                           'sumw2': 9*expected_raw['sumw2'],
                                           'entries': expected_raw['entries']}


@pytest.mark.parametrize('raw_kind', ['missing', 'histogram'])
def test_actual_yoda_finalized_scalar_requires_raw_counter(tmp_path, raw_kind):
    yoda = pytest.importorskip('yoda')
    if not str(yoda.__version__).startswith('2.'):
        pytest.skip('requires YODA2')
    counter = yoda.Counter('/TEST/count')
    counter.fill(1.)
    final = counter.mkEstimate(source='stats')
    final.setPath('/TEST/count')
    objects = [final]
    if raw_kind == 'histogram':
        objects.append(yoda.Histo1D([0., 1.], '/RAW/TEST/count'))
    path = tmp_path/'counter.yoda'
    yoda.write(objects, str(path))
    with pytest.raises(ValueError, match='matching RAW Counter'):
        export(path, [scalar_request()])


class Counter:
    """Boundary control with the actual Counter method names and no binDim."""
    def __init__(self, sumw=1., sumw2=5., entries=2.):
        self.moments = sumw, sumw2, entries

    def sumW(self):
        return self.moments[0]

    def sumW2(self):
        return self.moments[1]

    def numEntries(self):
        return self.moments[2]


class Estimate0D:
    def __init__(self, value=3., errors=(-2., 4.)):
        self.value, self.errors = value, errors

    def val(self):
        return self.value

    def quadSum(self):
        return self.errors


def fake_scalar(monkeypatch, final=None, raw=None):
    objects = {'/TEST/count': Counter(3., 45.) if final is None else final,
               '/RAW/TEST/count': Counter() if raw is None else raw}
    monkeypatch.setitem(sys.modules, 'yoda', SimpleNamespace(__version__='2.1.3', read=lambda _: objects))
    return objects


def test_scalar_boundary_keeps_asymmetric_final_errors_without_inventing_variance(monkeypatch):
    fake_scalar(monkeypatch, final=Estimate0D())
    result = export('unused.yoda', [scalar_request()])['observables']['/TEST/count']
    assert result['final_counter'] is None
    assert result['raw_counter'] == {'sumw': 1., 'sumw2': 5., 'entries': 2.}
    row = result['bins'][0]
    assert row['value'] == 3.
    assert (row['error_low'], row['error_high'], row['variance']) == (2., 4., None)


@pytest.mark.parametrize('change', [
    {'axes': [{'name': 'x', 'unit': 'GeV'}]},
    {'representation': 'differential'},
    {'normalization': 'normalized'},
])
def test_scalar_boundary_rejects_geometry_and_normalization(monkeypatch, change):
    fake_scalar(monkeypatch)
    request = scalar_request()
    request.update(change)
    with pytest.raises(ValueError, match='zero axes, integrated representation and absolute normalization'):
        export('unused.yoda', [request])


@pytest.mark.parametrize('moments', [(1., -1., 2.), (math.inf, 1., 2.),
                                     (1., math.nan, 2.), (1., 1., -1.), (1., 1., math.inf)])
def test_scalar_boundary_refuses_invalid_raw_moments(monkeypatch, moments):
    fake_scalar(monkeypatch, raw=Counter(*moments))
    with pytest.raises(ValueError, match='invalid scalar Counter weighted moments'):
        export('unused.yoda', [scalar_request()])


@pytest.mark.parametrize('final', [Counter(math.nan, 5.), Estimate0D(math.inf),
                                  Estimate0D(errors=(-math.inf, 1.)),
                                  Estimate0D(errors=(-1e308, 1e308))])
def test_scalar_boundary_refuses_invalid_final_values(monkeypatch, final):
    fake_scalar(monkeypatch, final=final)
    with pytest.raises(ValueError, match='invalid scalar Counter'):
        export('unused.yoda', [scalar_request()])


def test_scalar_boundary_refuses_mismatched_entries_and_implicit_counter(monkeypatch):
    fake_scalar(monkeypatch, final=Counter(3., 45., 3.))
    with pytest.raises(ValueError, match='RAW Counter entries differ'):
        export('unused.yoda', [scalar_request()])
    request = scalar_request()
    request.pop('quantity_kind')
    with pytest.raises(ValueError, match='unsupported YODA quantity type: Counter'):
        export('unused.yoda', [request])


def test_scalar_boundary_explicit_raw_path_and_complete_requested_denominator(monkeypatch):
    objects = fake_scalar(monkeypatch)
    request = scalar_request('/RAW/TEST/count')
    result = export('unused.yoda', [request])['observables']['/RAW/TEST/count']
    assert result['final_counter'] is None
    assert result['bins'][0]['value'] == 1.
    assert result['raw_counter'] == {'sumw': 1., 'sumw2': 5., 'entries': 2.}
    objects.pop('/TEST/count')
    with pytest.raises(ValueError, match='requested observable missing'):
        export('unused.yoda', [request, scalar_request()])


@pytest.mark.parametrize('defect', ['missing_raw', 'wrong_final', 'unknown_kind'])
def test_scalar_boundary_refuses_unsupported_storage_and_kind(monkeypatch, defect):
    objects = fake_scalar(monkeypatch)
    request = scalar_request()
    if defect == 'missing_raw':
        objects.pop('/RAW/TEST/count')
        reason = 'matching RAW Counter'
    elif defect == 'wrong_final':
        objects['/TEST/count'] = object()
        reason = 'Counter or finalized Estimate0D'
    else:
        request['quantity_kind'] = 'arbitrary_scalar'
        reason = 'unsupported explicit YODA quantity_kind'
    with pytest.raises(ValueError, match=reason):
        export('unused.yoda', [request])


def profile_request(path='/TEST/profile', dim=1):
    return {'path': path, 'axes': [{'name': a, 'unit': 'GeV'} for a in 'xy'[:dim]],
            'representation': 'mean', 'normalization': 'absolute', 'unit': 'GeV',
            'quantity_kind': 'profile_mean'}


def profile_fixture(tmp_path, *, dim=1, estimate=False, scale=1., weights=(2., 1.)):
    yoda = pytest.importorskip('yoda')
    if not str(yoda.__version__).startswith('2.'):
        pytest.skip('requires YODA2')
    raw = (yoda.Profile1D([0., 1., 3.], '/RAW/TEST/profile') if dim == 1 else
           yoda.Profile2D([0., 1., 3.], [0., 2.], '/RAW/TEST/profile'))
    for x, value, weight in ((.5, 2., weights[0]), (.5, 4., weights[1]),
                             (2., 8., 1.), (2., 10., 1.)):
        raw.fill(*(([x] if dim == 1 else [x, 1.]) + [value, weight]))
    final = raw.clone()
    final.scale(dim, scale)
    if estimate:
        final = final.mkEstimate(source='stats')
    final.setPath('/TEST/profile')
    path = tmp_path / 'profile.yoda'
    yoda.write([raw, final], str(path), precision=17)
    return path, profile_request(dim=dim), raw, final


@pytest.mark.parametrize('dim', [1, 2])
@pytest.mark.parametrize('estimate', [False, True])
def test_actual_yoda_profile_preserves_dependent_mean_moments_without_width_conversion(tmp_path, dim, estimate):
    path, request, _, _ = profile_fixture(tmp_path, dim=dim, estimate=estimate)
    result = export(path, [request])['observables']['/TEST/profile']
    assert [b['value'] for b in result['bins']] == pytest.approx([8/3, 9])
    # Independent weighted-mean arithmetic: var=(24*3-8^2)/(3^2-5)=2,
    # effective N=3^2/5, so mean variance=10/9. This is not sumW2=5.
    assert [b['variance'] for b in result['bins']] == pytest.approx([10/9, 1])
    assert [b['integrated_sumw'] for b in result['bins']] == [None, None]
    row = result['bins'][0]
    moments = row['raw_profile']
    assert moments['sumw'] == 3 and moments['sumw2'] == 5 and moments['entries'] == 2
    assert moments['coordinate_sumw'] == ([1.5, 8.] if dim == 1 else [1.5, 3., 8.])
    assert moments['coordinate_squared_sumw'] == ([.75, 24.] if dim == 1 else [.75, 3., 24.])
    assert moments['coordinate_cross_sumw'] == ([4.] if dim == 1 else [1.5, 4., 8.])
    assert row['final_profile'] == (None if estimate else moments)
    assert result['moment_semantics']['coordinate_squared_sumw'] == 'sum(weight*coordinate^2)'
    assert result['raw_flow_sumw'] == result['raw_flow_sumw2'] == 0
    assert 'signed weights' in result['uncertainty_scope']


def test_actual_yoda_native_profile_scaling_retains_both_final_and_raw_moments(tmp_path):
    path, request, _, _ = profile_fixture(tmp_path, scale=3.)
    result = export(path, [request])['observables']['/TEST/profile']
    assert [b['value'] for b in result['bins']] == pytest.approx([8., 27.])
    assert [b['variance'] for b in result['bins']] == pytest.approx([10., 9.])
    first = result['bins'][0]
    assert first['raw_profile']['coordinate_sumw'][-1] == 8.
    assert first['final_profile']['coordinate_sumw'][-1] == 24.
    assert first['final_profile']['coordinate_squared_sumw'][-1] == 216.


def test_actual_yoda_signed_profile_keeps_native_error_convention_without_covariance_claim(tmp_path):
    path, request, _, _ = profile_fixture(tmp_path, weights=(3., -1.))
    result = export(path, [request])['observables']['/TEST/profile']
    row = result['bins'][0]
    assert row['value'] == 1.
    assert row['variance'] == pytest.approx(5.)
    assert row['raw_profile']['sumw'] == 2.
    assert row['raw_profile']['sumw2'] == 10.
    assert row['raw_profile']['coordinate_squared_sumw'][-1] == -4.
    assert 'absolute weighted variance' in result['uncertainty_scope']
    assert 'do not supply cross-bin' in result['covariance_scope']


@pytest.mark.parametrize('defect', ['empty', 'cancellation', 'one_entry'])
def test_actual_yoda_profile_refuses_undefined_mean_or_error(tmp_path, defect):
    yoda = pytest.importorskip('yoda')
    if not str(yoda.__version__).startswith('2.'):
        pytest.skip('requires YODA2')
    raw = yoda.Profile1D([0., 1.], '/RAW/TEST/profile')
    if defect != 'empty':
        raw.fill(.5, 2., 1.)
    if defect == 'cancellation':
        raw.fill(.5, 4., -1.)
    final = raw.clone()
    final.setPath('/TEST/profile')
    path = tmp_path / 'profile.yoda'
    yoda.write([raw, final], str(path))
    with pytest.raises(ValueError, match='mean or upstream standard error is undefined'):
        export(path, [profile_request()])


@pytest.mark.parametrize('defect', ['missing_raw', 'histogram_raw', 'geometry', 'derived', 'mask', 'raw_mask', 'entries'])
def test_actual_yoda_profile_refuses_unsupported_association_and_derivation(tmp_path, defect):
    path, request, raw, final = profile_fixture(tmp_path, estimate=defect == 'derived')
    import yoda
    objects = {'/RAW/TEST/profile': raw, '/TEST/profile': final}
    if defect == 'missing_raw':
        objects.pop('/RAW/TEST/profile')
        reason = 'matching RAW Profile'
    elif defect == 'histogram_raw':
        objects['/RAW/TEST/profile'] = yoda.Histo1D([0., 1., 3.], '/RAW/TEST/profile')
        reason = 'matching RAW Profile'
    elif defect == 'geometry':
        objects['/RAW/TEST/profile'] = yoda.Profile1D([0., 2., 3.], '/RAW/TEST/profile')
        reason = 'binning differ'
    elif defect == 'derived':
        final.bins()[0].setVal(42.)
        reason = 'derived profile transformation'
    elif defect in ('mask', 'raw_mask'):
        (raw if defect == 'raw_mask' else final).maskBinAt(.5)
        reason = 'masked bins'
    else:
        final.fill(.5, 3.)
        reason = 'entries differ'
    yoda.write(objects, str(path), precision=17)
    with pytest.raises(ValueError, match=reason):
        export(path, [request])


@pytest.mark.parametrize('change', [{'representation': 'differential'}, {'normalization': 'normalized'}, {'axes': []}])
def test_actual_yoda_profile_requires_explicit_mean_semantics(tmp_path, change):
    path, request, _, _ = profile_fixture(tmp_path)
    request.update(change)
    with pytest.raises(ValueError, match='profile_mean requires'):
        export(path, [request])


def test_actual_yoda_profile_raw_path_is_explicit_and_profile_is_not_implicit_histogram(tmp_path):
    path, request, _, _ = profile_fixture(tmp_path)
    request['path'] = '/RAW/TEST/profile'
    result = export(path, [request])['observables'][request['path']]
    assert result['bins'][0]['value'] == pytest.approx(8/3)
    request.pop('quantity_kind')
    request['representation'] = 'integrated'
    with pytest.raises(ValueError, match='unsupported YODA quantity type'):
        export(path, [request])


def test_actual_yoda_profile_default_text_precision_keeps_serialized_final_errors(tmp_path):
    path, request, raw, final = profile_fixture(tmp_path, estimate=True)
    import yoda
    yoda.write([raw, final], str(path))
    reread = yoda.read(str(path))['/TEST/profile'].bins()[0]
    result = export(path, [request])['observables']['/TEST/profile']
    row = result['bins'][0]
    assert row['value'] == reread.val()
    assert row['error_low'] == abs(reread.quadSum()[0])
    assert row['variance'] == reread.quadSum()[0] ** 2
    assert 'source-format decimal precision intervals' in result['raw_mean_comparison']['scope']
    assert row['serialization_bounds']['raw']['moment_tokens']['sumW'] == '3.000000e+00'


@pytest.mark.parametrize('categories', [['toward', 'away'], [0, 1, 2]])
def test_actual_yoda_categorical_profiles_are_not_continuous_means(tmp_path, categories):
    yoda = pytest.importorskip('yoda')
    if not str(yoda.__version__).startswith('2.'):
        pytest.skip('requires YODA2')
    raw = yoda.Profile1D(categories, '/RAW/TEST/profile')
    final = raw.clone()
    final.setPath('/TEST/profile')
    path = tmp_path / 'categorical.yoda'
    yoda.write([raw, final], str(path))
    with pytest.raises(ValueError, match='categorical or unbounded profile bins'):
        export(path, [profile_request()])


def test_actual_yoda_histograms_do_not_acquire_profile_representation(tmp_path):
    path, request = setup(tmp_path)
    request['representation'] = 'mean'
    with pytest.raises(ValueError, match='histogram requires explicit'):
        export(path, [request])


@pytest.mark.parametrize('dependent', [(5., 6.), (10., 10.0001)])
@pytest.mark.parametrize('precision', [6, 17])
@pytest.mark.parametrize('weights', [(1., 2.), (2., -1.)])
def test_actual_profile_cancellation_uses_literal_precision_enclosure_not_global_error_tolerance(tmp_path, dependent, precision, weights):
    import math
    yoda = pytest.importorskip('yoda')

    area = 8*math.pi/3
    raw = yoda.Profile1D([0., 5.], '/RAW/TEST/profile')
    for value, weight in zip(dependent, weights):
        raw.fill(2.5, value/area, weight)
    final = raw.mkEstimate(source='stats');final.setPath('/TEST/profile')
    if precision == 17:
        # The Python writer's precision argument is not honored by this native
        # installation. This source-supported annotation actually retains DP.
        raw.setAnnotation('WriterDoublePrecision', '1')
        final.setAnnotation('WriterDoublePrecision', '1')
    true_mean, true_error = raw.bins()[0].mean(2), raw.bins()[0].stdErr(2)
    path = tmp_path/'cancellation.yoda';yoda.write([raw, final], str(path), precision=precision)
    result = export(path, [profile_request()])['observables']['/TEST/profile']['bins'][0]
    bounds = result['serialization_bounds']
    if precision == 17:
        assert len(bounds['raw']['moment_tokens']['sumW'].split('.')[1].split('e')[0]) == 17
    assert bounds['raw']['mean'][0] <= true_mean <= bounds['raw']['mean'][1]
    assert bounds['raw']['stderr'][0] <= true_error <= bounds['raw']['stderr'][1]
    assert bounds['estimate']['error_low'][0] <= true_error <= bounds['estimate']['error_low'][1]
    assert result['error_low'] == abs(yoda.read(str(path))['/TEST/profile'].bins()[0].quadSum()[0])
    if dependent == (5., 6.) and precision == 6 and weights == (1., 2.):
        parsed_error=yoda.read(str(path))['/RAW/TEST/profile'].bins()[0].stdErr(2)
        assert abs(parsed_error-true_error)/true_error > 2e-6
    # The same retained RAW interval must reject an error outside its bound.
    bad=2*bounds['raw']['stderr'][1]+.1
    final.bins()[0].setErr(bad,'stats')
    yoda.write([raw, final], str(path), precision=precision)
    with pytest.raises(ValueError,match='derived profile transformation'):
        export(path,[profile_request()])


def test_actual_token_precision_controls_interval_width_and_zero_denominator_refuses():
    from ravel.physics.rivet_export import _profile_rounding_bounds

    broad={'sumW':'3.000000e+00','sumW2':'5.000000e+00','sumW(A2)':'2.029226e+00','sumW2(A2)':'1.382084e+00'}
    narrow={k: format(float(v),'.17e') for k,v in broad.items()}
    a,b=(_profile_rounding_bounds(t,1) for t in [broad,narrow])
    assert b['stderr'][1]-b['stderr'][0] < (a['stderr'][1]-a['stderr'][0])/1e6
    ambiguous=dict(broad,sumW2='9.000000e+00')
    with pytest.raises(ValueError,match='nonzero denominator'):
        _profile_rounding_bounds(ambiguous,1)


@pytest.mark.parametrize('tokens', [
    {'sumW':'3.000000e+00','sumW2':'5.000000e+00','sumW(A2)':'2.029226e+00','sumW2(A2)':'1.382084e+00'},
    {'sumW':'1.000000e+00','sumW2':'5.000000e+00','sumW(A2)':'4.774648e-01','sumW2(A2)':'1.994761e-01'},
    {'sumW':'3.000000e+00','sumW2':'5.000000e+00','sumW(A2)':'3.000000e+00','sumW2(A2)':'3.000030e+00'},
])
def test_source_order_intervals_enclose_native_dbn_at_all_moment_endpoints(tokens):
    """API endpoint stress states, not physical event distributions."""
    from itertools import product
    from ravel.physics.rivet_export import _profile_rounding_bounds, _rounded_token
    yoda = pytest.importorskip('yoda')
    keys=('sumW','sumW2','sumW(A2)','sumW2(A2)')
    bounds=_profile_rounding_bounds(tokens,1)
    for w,q,a,b in product(*[_rounded_token(tokens[k]) for k in keys]):
        dbn=yoda.Dbn2D()
        dbn.set(2.,[w,0.,a],[q,0.,b],[0.])
        mean,error=dbn.mean(2),dbn.stdErr(2)
        assert bounds['mean'][0] <= mean <= bounds['mean'][1]
        assert bounds['stderr'][0] <= error <= bounds['stderr'][1]
