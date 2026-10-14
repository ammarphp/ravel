"""Ordinary source-constructor/config/Graph controls with fabricated reviews.

No approved run/native program or real statistical result is generated here.
"""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from ravel.physics import native_statistical_construction as g,native_likelihood as n
from ravel.physics import discovery_heldout as d,asimov_sensitivity as s,regional_expected as e,combine_derivatives as state
from ravel.workflow import science
from test_source_graph_coverage import recipe,rebind


def prepared_recipe(tmp_path,monkeypatch):
    value=recipe(tmp_path,monkeypatch,expected=True)
    value['population']={k:[v[0]] for k,v in value['population'].items()};value['cells']=value['cells'][:1]
    cell=value['cells'][0];poi=next(p for p in cell['law']['parameters'] if p['role']=='poi')
    poi['bounds']=['0','2'];cell['expected_data']['point'][poi['name']]='1';cell['fit']['domain']=['0','2']
    cell['fit'].pop('saved_fit',None);cell['fit'].update(points=None,fixed_witness_points=[],minimizer=None,reference_quantiles=None)
    point=deepcopy(cell['expected_data']['point']);null=deepcopy(point);null[poi['name']]='0'
    cell['discovery_diagnostic']={'kind':d.KIND,'convention':'physical_nonnegative_domain',
        'starts':{'free':[point],'null':[null]},'profile_policy':deepcopy(e.PROFILE_POLICY),
        'max_fit_calls':2,'max_readbacks':5,'absolute_nll_band':'1/100000000','relative_nll_band':'0',
        'source':cell['law']['sources'][0]['id'],'statement':'Explicit inert source/profile protocol control, no physical closure'}
    rebind(value,tmp_path);return value


def test_full_constructor_emits_existing_native_source_and_ordinary_sensitivity(tmp_path,monkeypatch):
    value=prepared_recipe(tmp_path,monkeypatch);path=tmp_path/'recipe.json';path.write_bytes(g.encoded(value))
    result=g.run({'input':str(path)},tmp_path,tmp_path/'bundle')
    row=result['cells'][0];assert row['mode']=='asimov-sensitivity' and result['native_calls']==result['fit_calls']==0
    cp=Path(row['task']['input']);cfg=json.loads(cp.read_text());parsed=n._configuration(row['task'],cp.parent)
    assert cfg['discovery_diagnostic']==value['cells'][0]['discovery_diagnostic']
    assert parsed[8]['source_observations']=={b['id']:None for b in value['cells'][0]['law']['bins']}
    assert n.commands(cfg,parsed[3],cp.parent,has_response=True)[1] is None
    public=science.task_inputs({'mode':'asimov-sensitivity','task':row['task'],'max_seconds':30},cp.parent)
    assert all(Path(module.__file__) in public for module in (s,d,e,state,n))
    context=s.context(row['task'],cp.parent)
    assert context['cell']==value['cells'][0] and context['execution_authorized'] is False
    task_path=cp.parent/'ordinary-task.json';task_path.write_text(json.dumps(row['task']))
    graph=s.graph(row['task'],cp.parent,{'path':str(task_path),'sha256':n._hash(task_path)})
    assert graph['nodes'][0]['action']=='asimov-sensitivity-context'
    cfg['discovery_diagnostic']['starts']['null'][0][cfg['fit']['poi']]='1';cp.write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match='authenticated original source cell'):n._configuration(row['task'],cp.parent)


@pytest.mark.parametrize('change',[
    lambda cell:cell['discovery_diagnostic']['starts']['null'][0].pop(next(iter(cell['discovery_diagnostic']['starts']['null'][0]))),
    lambda cell:cell['fit'].__setitem__('fixed_witness_points',['0']),
    lambda cell:cell['discovery_diagnostic'].__setitem__('max_readbacks',4)])
def test_declared_original_source_population_and_no_hidden_calls(tmp_path,monkeypatch,change):
    value=prepared_recipe(tmp_path,monkeypatch);change(value['cells'][0])
    # Constructor validates source requests; native config additionally applies
    # the no-extra-work checks when materialized. Neither executes fit effects.
    path=tmp_path/'recipe.json';rebind(value,tmp_path);path.write_bytes(g.encoded(value))
    with pytest.raises(ValueError):g.run({'input':str(path)},tmp_path,tmp_path/'bundle')
