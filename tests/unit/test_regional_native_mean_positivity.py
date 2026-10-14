"""Domain admission controls with the exact generated collector on inert objects."""
import contextlib
import io
import json
import pytest
from ravel.physics import native_likelihood as N
from test_regional_workspace_closure import fixture

def supplied_probe(source,actual):
    f=fixture()
    f.objects['ravel_mean_0'].value=source
    f.objects['n_exp_binR0_proc_ravel_full'].value=source
    f.objects['n_exp_binR0'].value=actual
    with contextlib.redirect_stdout(io.StringIO()):
        f.probe['construction_linkage']=f.collector(f.w,f.mc,f.response)
    return f

def test_positive_tiny_mean_is_admitted(tmp_path):
    f=supplied_probe(1.e-12,1.e-12)
    (tmp_path/'positive-tiny-probe.json').write_text(json.dumps(f.probe,indent=2)+'\n')
    assert N._check_workspace(f.probe,f.config,f.response)==[]

def test_positive_mean_retains_existing_equivalence_band():
    f=supplied_probe(1.e-12,9.e-11)
    assert N._check_workspace(f.probe,f.config,f.response)==[]

def test_positive_mean_outside_existing_band_refuses():
    f=supplied_probe(1.e-12,2.e-10)
    with pytest.raises(ValueError,match='regional total expected count differs'):
        N._check_workspace(f.probe,f.config,f.response)

@pytest.mark.parametrize('source',[0.,-1.e-12])
def test_nonpositive_reference_still_refuses(source):
    f=supplied_probe(source,1.e-12)
    with pytest.raises(ValueError,match='regional total expected count differs'):
        N._check_workspace(f.probe,f.config,f.response)

@pytest.mark.parametrize('actual',[0.,-1.e-12])
def test_nonpositive_return_refuses_before_tolerance_evaluation(actual,monkeypatch):
    f=supplied_probe(1.e-12,actual)
    def unavailable(*args):
        raise AssertionError('tolerance was evaluated before positivity')
    monkeypatch.setattr(N,'abs',unavailable,raising=False)
    with pytest.raises(ValueError,match='regional total expected count differs'):
        N._check_workspace(f.probe,f.config,f.response)
