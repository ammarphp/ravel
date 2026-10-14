"""AUTHORED UNRUN: real materialization verifier, disclosed inherited inert roles.

No model/native/render/actual scientific votes. Campaign and prior writer response
seams are inherited stand-ins; verify_author is never replaced. A genuine source
materialization remains necessary even with those inert authority observations.
"""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from ravel.workflow import manuscript_production as mp, scientific_judgment as sj
from test_manuscript_production import setup, completed, pin, put


def prior(root, monkeypatch):
    request, state, value = setup(root/'source', monkeypatch)
    binding = mp.prepare_writer(request, root/'writer', base_dir=root/'source', campaign=root/'campaign')
    completed(binding, state, value, monkeypatch)
    collected = mp.collect(binding, root/'note')
    return request, state, value, binding, collected


def feedback(root, package, monkeypatch):
    # Disclosed role boundary; actual prior authored bytes are still verified.
    case = {'root':'whole', 'nodes':[{'id':'whole','anchors':[{'format':'json','location':'',
        'value':json.loads(Path(package['integrity_request']['path']).read_text())}]}]}
    case_pin={k:v for k,v in put(root,'case.json',case).items() if k in ('path','sha256')}
    observed={'receipt':{'role':'critic'},'value':{'verdict':'send_back','findings':['Synthetic material objection.']},
        'contract':{'case_pin':case_pin,'rundir':str(root)},'supporting_artifacts':[]}
    records=getattr(monkeypatch,'_manuscript_feedback_records',None)
    if records is None:
        records={}
        monkeypatch._manuscript_feedback_records=records
    binding={'synthetic_sendback_boundary_only':True,'case_pin':case_pin}
    records[mp.ce.digest(binding)]=deepcopy(observed)
    def retained(binding,*args,**kwargs):
        if mp.ce.digest(binding) not in records:raise ValueError('unknown retained feedback binding')
        return deepcopy(records[mp.ce.digest(binding)])
    monkeypatch.setattr(sj,'verify_binding',retained)
    return binding


def revise(root, request, package, monkeypatch):
    request=deepcopy(request)
    request['revision']={'previous_package':put(root,'previous-copy.json',package),
        'feedback_binding':feedback(root,package,monkeypatch)}
    return request


@pytest.mark.parametrize('field',['manuscript','latex','model_provenance'])
@pytest.mark.parametrize('route',['prepare','execute','collect'])
def test_honest_new_previous_pin_cannot_replace_prior_products(tmp_path,monkeypatch,field,route):
    request,state,value,binding,collected=prior(tmp_path,monkeypatch)
    changed=deepcopy(collected['package']);changed[field]=put(tmp_path,'foreign-'+field+'.txt','Foreign content, honestly pinned.')
    request=revise(tmp_path/'revision-input',request,changed,monkeypatch)
    if route=='prepare':
        with pytest.raises(ValueError):mp.prepare_writer(request,tmp_path/'revision',base_dir=tmp_path/'source',campaign=tmp_path/'campaign')
        assert not (tmp_path/'revision').exists()
    else:
        current=deepcopy(binding);current['request']=put(tmp_path/'current','production-request.json',request)
        with pytest.raises(ValueError):
            if route=='execute':mp.execute_writer(current,object())
            else:mp.collect(current,tmp_path/'new-note')
        assert not (tmp_path/'new-note').exists()


def test_genuine_direct_revision_retains_complete_prior_products_and_original_campaign(tmp_path,monkeypatch):
    request,state,value,binding,collected=prior(tmp_path,monkeypatch)
    request=revise(tmp_path/'revision-input',request,collected['package'],monkeypatch)
    revision=mp.prepare_writer(request,tmp_path/'revision',base_dir=tmp_path/'source',campaign=tmp_path/'campaign')
    paths={p['path'] for p in revision['input_pins']}
    package=collected['package']
    assert {package[k]['path'] for k in ('manuscript','latex','model_provenance','author_binding','production_request','integrity_request')}<=paths
    assert str(Path(binding['graph'])/mp.agent_graph.SPEC) in paths
    assert str(Path(binding['graph'])/mp.agent_graph.STATE) in paths
    assert revision['spec']['nodes'][0]['role']=='improver'
    assert revision['campaign']==binding['campaign'] and not revision['execution_authorized']
    assert mp._REVISION_VERIFICATION.get() is None


@pytest.mark.parametrize('fault',['missing-product','changed-product','binding','graph'])
def test_actual_prior_origin_custody_drift_refuses_before_presentation(tmp_path,monkeypatch,fault):
    request,state,value,binding,collected=prior(tmp_path,monkeypatch)
    request=revise(tmp_path/'revision-input',request,collected['package'],monkeypatch)
    if fault=='missing-product':Path(collected['package']['manuscript']['path']).unlink()
    elif fault=='changed-product':Path(collected['package']['latex']['path']).write_text('Changed after honest pin.')
    elif fault=='binding':Path(collected['package']['author_binding']['path']).write_text('{}')
    else:Path(binding['graph'],mp.agent_graph.SPEC).write_text('{}')
    with pytest.raises(ValueError):mp.prepare_writer(request,tmp_path/'revision',base_dir=tmp_path/'source',campaign=tmp_path/'campaign')
    assert not (tmp_path/'revision').exists() and mp._REVISION_VERIFICATION.get() is None


def test_foreign_equal_context_campaign_cannot_renew_direct_revision_budget(tmp_path,monkeypatch):
    request,state,value,binding,collected=prior(tmp_path,monkeypatch)
    request=revise(tmp_path/'revision-input',request,collected['package'],monkeypatch)
    with pytest.raises(ValueError,match='original authenticated author campaign'):
        mp.prepare_writer(request,tmp_path/'revision',base_dir=tmp_path/'source',campaign=tmp_path/'new-campaign')
    assert not (tmp_path/'revision').exists()


def test_operation_cache_rereads_products_and_clears_on_exception(tmp_path,monkeypatch):
    request,state,value,binding,collected=prior(tmp_path,monkeypatch)
    session={'active':[],'verified':{}}
    token=mp._REVISION_VERIFICATION.set(session)
    try:
        mp._revision_origin(collected['package'],tmp_path,{})
        assert session['verified'] and session['active']==[]
        Path(collected['package']['manuscript']['path']).write_text('Changed within same verification operation.')
        with pytest.raises(ValueError):mp._revision_origin(collected['package'],tmp_path,{})
    finally:mp._REVISION_VERIFICATION.reset(token)
    assert mp._REVISION_VERIFICATION.get() is None


def test_active_origin_cycle_refused_without_recursive_author_dispatch(tmp_path,monkeypatch):
    request,state,value,binding,collected=prior(tmp_path,monkeypatch)
    origin=str(Path(collected['package']['author_binding']['path']).resolve())
    token=mp._REVISION_VERIFICATION.set({'active':[origin],'verified':{}})
    try:
        with pytest.raises(ValueError,match='cyclic previous'):mp._revision_origin(collected['package'],tmp_path,{})
    finally:mp._REVISION_VERIFICATION.reset(token)


def test_bounded_genuine_second_revision_reconsumes_first_revision_ancestry(tmp_path,monkeypatch):
    request,state,value,original,collected=prior(tmp_path,monkeypatch)
    first=revise(tmp_path/'first-input',request,collected['package'],monkeypatch)
    binding=mp.prepare_writer(first,tmp_path/'first',base_dir=tmp_path/'source',campaign=tmp_path/'campaign')
    completed(binding,state,value,monkeypatch)
    state['sha256']='2'*64;state['graphs']=[{'root':original['graph'],'complete':True},{'root':binding['graph'],'complete':True}]
    first_package=mp.collect(binding,tmp_path/'first-note')
    second=revise(tmp_path/'second-input',request,first_package['package'],monkeypatch)
    second_binding=mp.prepare_writer(second,tmp_path/'second',base_dir=tmp_path/'source',campaign=tmp_path/'campaign')
    assert second_binding['spec']['nodes'][0]['role']=='improver'
    assert collected['package']['model_provenance'] in second_binding['input_pins']
    assert mp._REVISION_VERIFICATION.get() is None


@pytest.mark.parametrize('field',['source_base','input_pins','integrity_request_sha256','author_id','original_task'])
def test_rehashed_prior_origin_metadata_is_not_self_attestation(tmp_path,monkeypatch,field):
    request,state,value,binding,collected=prior(tmp_path,monkeypatch)
    package=deepcopy(collected['package'])
    package[field]={'source_base':str(tmp_path/'foreign-base'),'input_pins':[],
        'integrity_request_sha256':'f'*64,'author_id':'foreign-author',
        'original_task':put(tmp_path,'foreign-task.txt','A different original scientific task.')}[field]
    request=revise(tmp_path/'revision-input',request,package,monkeypatch)
    with pytest.raises(ValueError):mp.prepare_writer(request,tmp_path/'revision',base_dir=tmp_path/'source',campaign=tmp_path/'campaign')
    assert not (tmp_path/'revision').exists()


def test_ancestry_uses_existing_finite_integrity_envelope(tmp_path,monkeypatch):
    request,state,value,binding,collected=prior(tmp_path,monkeypatch)
    assert mp.MAX_REVISION_ANCESTORS==mp.integrity.MAX_ITEMS
    token=mp._REVISION_VERIFICATION.set({'active':['other-'+str(i) for i in range(mp.integrity.MAX_ITEMS)],'verified':{}})
    try:
        with pytest.raises(ValueError,match='finite verification bound'):mp._revision_origin(collected['package'],tmp_path,{})
    finally:mp._REVISION_VERIFICATION.reset(token)
