import importlib.util
import json
import math
from pathlib import Path
import pytest

from ravel.physics import workspace_combination_witness as witness
import test_workspace_combination as fixture
POINTS=['nominal','poi_zero','poi_two','plus','minus']

def run(tmp_path,components=None,policy=None,compiler=None,**kwargs):
    if components is None:components,policy=fixture.inputs()
    snapshots=[]
    def record(value):
        (tmp_path/'progress.json').write_text(json.dumps(value,allow_nan=False))
        snapshots.append(value)
    result=witness.qualify(components,policy,POINTS,compiler=compiler or fixture.join.combine,record=record,**kwargs)
    return result,snapshots


def test_complete_mixed_shared_normal_witness_and_actual_compilation_count(tmp_path,monkeypatch):
    import pyhf
    calls=[];old=pyhf.Workspace.model
    def counted(self,*args,**kwargs):calls.append(1);return old(self,*args,**kwargs)
    monkeypatch.setattr(pyhf.Workspace,'model',counted)
    result,snapshots=run(tmp_path)
    assert len(calls)==8 and result['calls']==20 and result['passed']
    assert len(result['points'])==5 and result['fits']==0
    assert all(p['auxiliary_terms']==1 and p['density_residual']<1e-12 for p in result['points'])
    assert json.loads((tmp_path/'progress.json').read_text())['status']=='completed'
    assert any(x['journal'][-1]['status']=='running' for x in snapshots)


def test_unique_poisson_auxiliary_union_is_counted_once(tmp_path):
    components,policy=fixture.inputs();del policy['shared_parameters']['common']
    for row in components:
        row['workspace']['channels'][0]['samples'][0]['modifiers'][0].update(type='shapesys',data=[2.])
        row['parameter_map']['theta']=row['id']+'_stat'
    result,_=run(tmp_path,components,policy)
    assert result['passed'] and all(p['auxiliary_terms']==2 for p in result['points'])


def test_completed_density_retained_before_expired_clock(tmp_path,monkeypatch):
    import pyhf
    clock=[0.];old=pyhf.Model.logpdf
    monkeypatch.setattr(witness.time,'monotonic',lambda:clock[0])
    def late(self,*args,**kwargs):
        value=old(self,*args,**kwargs);clock[0]=2.;return value
    monkeypatch.setattr(pyhf.Model,'logpdf',late)
    with pytest.raises(TimeoutError):run(tmp_path,max_seconds=1.)
    saved=json.loads((tmp_path/'progress.json').read_text())
    assert saved['status']=='failed' and saved['calls']==4
    assert saved['journal'][-1]['status']=='returned'
    assert math.isfinite(saved['journal'][-1]['value'])
    assert len(saved['points'][0]['component_means'])==2
    assert math.isfinite(saved['points'][0]['independent_logpdf'])


def test_late_density_failure_preserves_all_prior_points(tmp_path,monkeypatch):
    import pyhf
    old=pyhf.Model.logpdf;count=[0]
    def fails(self,*args,**kwargs):
        count[0]+=1
        if count[0]==5:raise RuntimeError('deliberate final failure')
        return old(self,*args,**kwargs)
    monkeypatch.setattr(pyhf.Model,'logpdf',fails)
    with pytest.raises(RuntimeError,match='final failure'):run(tmp_path)
    saved=json.loads((tmp_path/'progress.json').read_text())
    assert saved['calls']==20 and len(saved['points'])==5
    assert all(p['passed'] for p in saved['points'][:4])
    assert saved['points'][-1]['status']=='running' and saved['journal'][-1]['status']=='failed'
    assert len(saved['points'][-1]['component_means'])==2


def test_changed_observation_refuses_before_numerical_calls(tmp_path):
    def corrupt(*args):
        value=fixture.join.combine(*args);value['workspace']['observations'][0]['data'][0]+=1;return value
    with pytest.raises(ValueError,match='observations differ'):run(tmp_path,compiler=corrupt)
    assert json.loads((tmp_path/'progress.json').read_text())['calls']==0


def test_nonfinite_joined_mean_refuses_with_return_retained(tmp_path,monkeypatch):
    import pyhf
    old=pyhf.Model.expected_actualdata
    def corrupt(self,*args,**kwargs):
        value=old(self,*args,**kwargs)
        if len(self.config.channels)==2:value[1]=float('nan')
        return value
    monkeypatch.setattr(pyhf.Model,'expected_actualdata',corrupt)
    with pytest.raises(ValueError,match='nonfinite joined mean'):run(tmp_path)
    saved=json.loads((tmp_path/'progress.json').read_text())
    assert saved['status']=='failed' and saved['calls']==3
    assert saved['journal'][-1]['status']=='returned'
    assert saved['journal'][-1]['value'][1]=={'nonfinite_float':'nan'}
    assert len(saved['points'][0]['component_means'])==2


@pytest.mark.parametrize('keyword,value',[('max_calls',19),('mean_atol',float('inf')),('density_atol',True)])
def test_bad_protocol_refuses_before_any_model(tmp_path,keyword,value):
    with pytest.raises(ValueError):run(tmp_path,**{keyword:value})
    assert not (tmp_path/'progress.json').exists()
