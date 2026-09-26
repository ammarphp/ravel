"""YODA 2 integration checks; enabled with the native Rivet interpreter."""
import math
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
