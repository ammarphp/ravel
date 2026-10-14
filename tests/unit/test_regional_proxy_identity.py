"""Semantic public-API fixtures; no ROOT/backend/model execution."""
import contextlib
import copy
import io
import itertools
import sys
import pytest

from ravel.physics import native_likelihood as N
from test_regional_workspace_closure import fixture


def collect(f):
    with contextlib.redirect_stdout(io.StringIO()):
        q=f.collector(f.w,f.mc,f.response)
    f.probe['construction_linkage']=q
    return q


@pytest.mark.parametrize('order',list(itertools.permutations(range(3))))
def test_gaussian_server_order_does_not_change_named_proxy_roles(order):
    f=fixture();aux=f.objects['ravel_aux_0_Pdf'];original=list(aux.children)
    aux.children=[original[i] for i in order]
    q=collect(f);N._check_workspace(f.probe,f.config,f.response)
    n=next(x for x in q['leaves'] if x['name']==aux.name)
    assert n['servers']==[x.name for x in aux.children]
    assert n['proxy_identity']['roles']=={'x':'ravel_aux_0','mean':'ravel_aux_0_In','sigma':'1'}
    assert q['auxiliary_widths'][aux.name]=={'name':'1','constant':True,'value':1.}
    assert q['semantic_proxy_queries']==9


def test_poisson_reordered_servers_require_correct_x_and_mean_roles():
    f=fixture();pdf=f.objects['pdf_binR0'];pdf.children.reverse()
    q=collect(f);N._check_workspace(f.probe,f.config,f.response)
    assert q['rows'][0]['pdf']['servers']==['n_exp_binR0','n_obs_binR0']
    assert q['rows'][0]['pdf']['proxy_identity']['roles']=={'mean':'n_exp_binR0','x':'n_obs_binR0'}


@pytest.mark.parametrize('roles',[('x','mean'),('mean','sigma'),('x','sigma')])
def test_same_gaussian_servers_with_changed_role_are_refused(roles):
    f=fixture();aux=f.objects['ravel_aux_0_Pdf'];a,b=roles
    aux.proxy_roles[a],aux.proxy_roles[b]=aux.proxy_roles[b],aux.proxy_roles[a]
    assert {x.name for x in aux.children}=={'ravel_aux_0','ravel_aux_0_In','1'}
    collect(f)
    with pytest.raises(ValueError):N._check_workspace(f.probe,f.config,f.response)


def test_same_poisson_servers_with_changed_x_and_mean_are_refused():
    f=fixture();pdf=f.objects['pdf_binR0']
    pdf.proxy_roles['x'],pdf.proxy_roles['mean']=pdf.proxy_roles['mean'],pdf.proxy_roles['x']
    collect(f)
    with pytest.raises(ValueError,match='semantic proxy identities'):N._check_workspace(f.probe,f.config,f.response)


@pytest.mark.parametrize('malformed',[
    lambda p:p['construction_linkage']['leaves'][-1].pop('proxy_identity'),
    lambda p:p['construction_linkage']['leaves'][-1]['proxy_identity']['roles'].update(sigma='ravel_aux_0_In'),
    lambda p:p['construction_linkage']['leaves'][-1]['proxy_identity']['queries'][0].update(code=True),
    lambda p:p['construction_linkage']['leaves'][-1]['proxy_identity']['queries'][0].update(selected=[]),
    lambda p:p['construction_linkage'].update(semantic_proxy_queries=8),
    lambda p:p['construction_linkage'].update(semantic_proxy_queries=True),
    lambda p:p['construction_linkage']['auxiliary_widths']['ravel_aux_0_Pdf'].update(value=0.),
    lambda p:p['construction_global_ranges']['ravel_aux_0_In'].update(has_max=True),
])
def test_complete_semantics_and_wrong_gaussian_law_remain_required(malformed):
    f=fixture();malformed(f.probe)
    with pytest.raises((ValueError,KeyError)):N._check_workspace(f.probe,f.config,f.response)


@pytest.mark.parametrize('broken',['unknown_code','bool_code','no_selected','sigma_selected','duplicate_role','extra_server'])
def test_dependency_query_must_reproduce_complete_primary_api_contract(broken):
    f=fixture();aux=f.objects['ravel_aux_0_Pdf'];original=aux.getAnalyticalIntegral
    def altered(requested,selected):
        code=original(requested,selected)
        if broken=='unknown_code':return 3
        if broken=='bool_code':return bool(code)
        if broken=='no_selected':selected.clear()
        if broken=='sigma_selected' and code==0:selected.extend(requested)
        if broken=='duplicate_role':
            selected[:]=requested;return 1
        return code
    if broken=='extra_server':aux.children.append(f.objects['beta'])
    else:aux.getAnalyticalIntegral=altered
    with pytest.raises(RuntimeError,match='semantic proxy'):
        collect(f)


def test_dependency_query_adds_no_mean_width_or_dummy_evaluations():
    f=fixture();before={n:x.reads for n,x in f.objects.items()}
    collect(f)
    expected={'1':1}
    for i in range(3):
        expected.update({f'n_exp_binR{i}_proc_ravel_dummy':1,f'n_exp_binR{i}':1,f'ravel_mean_{i}':1})
    assert {n:x.reads-before[n] for n,x in f.objects.items() if x.reads!=before[n]}==expected
    assert 'ROOT' not in sys.modules


def test_role_query_handles_many_bins_without_expanding_numerical_calls():
    f=fixture(172);q=collect(f);N._check_workspace(f.probe,f.config,f.response)
    assert q['semantic_proxy_queries']==347
    assert q['extra_initial_mean_evaluations']==344
    assert len(q['rows'])==172
