"""Proposed source/API WMS and background/validation/sensitivity controls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from ravel.workflow import site_workflow as w,science,research_cycle
from ravel.physics import root_stream as stream,root_stream_core as core,root_stream_statistics as stats,statistical_construction as regional
from root_stream_fixture import population,accumulate,event_population,pin,put


def workflow_fixture(root,monkeypatch,owner=None):
    rd=root/'study';(rd/'inputs').mkdir(parents=True);plan=put(rd,'inputs/science-plan.json',{'schema_version':2,'stages':[{'outputs':['outputs']}]})
    proof=put(root,'audit.json',{'synthetic':'software only'});python=put(root,'analysis-python',b'never executed');(root/'analysis-python').chmod(0o755)
    source=root/'source';source.mkdir();put(source,'module.py',b'# synthetic complete source\n')
    policy=put(root,'blind-policy.json',{'schema_version':1,'policy':'exclude_signal_region_data_from_model_and_analysis','review_source':proof,'original_domain':None})
    monkeypatch.setattr(w,'_source_assets',lambda:(source,stream.census(source)))
    monkeypatch.setattr(science,'verify_plan',lambda rd,approved=False,**kwargs:{'schema_version':2,'stages':[{'outputs':['outputs']}]})
    monkeypatch.setattr(science,'execution_spec',lambda rd,**kwargs:{'mode':'quantities'})
    request={'schema_version':1,'site_id':'synthetic','python':python,'tasks':[{'id':'analyze','rundir':str(rd),'plan':plan,'owner':owner or {'kind':'ordinary'},'depends_on':[]}],
             'audit':{'prompts':[proof],'model_build':'exact-synthetic-build','timestamps':['2026-10-09T00:00:00Z'],'token_accounting':proof,'environment':proof,'tracked_skill_sources':[proof],'blinding_policy':policy},
             'wms':{'engine':'snakemake','version':'9.27.0','cores':1,'retries':0}}
    return request,rd,source


def test_export_has_no_execution_and_original_digest_quoted_complete_closure(tmp_path,monkeypatch):
    request,rd,source=workflow_fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(science,'run',lambda *a,**k:pytest.fail('export must not execute'))
    result=w.export(request,tmp_path,tmp_path/'export');doc=w.verify(result['manifest']['path'],result['manifest']['sha256'])
    assert doc['execution_authorized'] is False
    raw=(tmp_path/'export/Snakefile').read_text()
    assert 'run-step' in raw and result['manifest']['sha256'] in raw and 'retries: 0' in raw
    assert 'approve' not in raw and '--resume' not in raw
    put(source,'new-empty.py',b'')
    with pytest.raises(ValueError):w.verify(result['manifest']['path'],result['manifest']['sha256'])


@pytest.mark.parametrize('name',['all','ravel_verify_export','rule','include'])
def test_reserved_snakemake_names_are_refused_as_task_ids(tmp_path,monkeypatch,name):
    request,_,_=workflow_fixture(tmp_path,monkeypatch);request['tasks'][0]['id']=name
    with pytest.raises(ValueError,match='reserved'):w.validate(request)


def test_actual_existing_ordinary_gate_then_authenticated_completion(tmp_path,monkeypatch):
    request,rd,_=workflow_fixture(tmp_path,monkeypatch);result=w.export(request,tmp_path,tmp_path/'export');events=[]
    def approval(rd,approved=False,**kwargs):
        events.append(('verify',approved))
        if approved:raise ValueError('unapproved actual plan')
        return {'schema_version':2,'stages':[{'outputs':['outputs']}]}
    monkeypatch.setattr(science,'verify_plan',approval)
    monkeypatch.setattr(science,'run',lambda *a,**k:pytest.fail('must preserve approval'))
    with pytest.raises(ValueError):w.run_step(result['manifest']['path'],'analyze',result['manifest']['sha256'])
    assert ('verify',True) in events
    monkeypatch.setattr(science,'verify_plan',lambda *a,**k:{'schema_version':2,'stages':[{'outputs':['outputs']}]})
    def run(rundir,resume):
        assert resume is False;out=rd/'outputs';out.mkdir()
        stream.write_new(out/'result.json',{'status':'passed','physics_validated':False})
        stream.write_new(out/'verification.json',{'passed':True,'physics_validated':False});return 0
    monkeypatch.setattr(science,'run',run)
    # Disclosed inert ordinary authority fixture: this adapter-route test does
    # not execute a native job or claim source/runtime qualification.
    monkeypatch.setattr(stream,'ordinary_delivery',lambda rd,**kwargs:{'outputs':[pin(Path(rd)/'outputs/result.json'),pin(Path(rd)/'outputs/verification.json')]})
    assert w.run_step(result['manifest']['path'],'analyze',result['manifest']['sha256'])['scientific_acceptance_inferred'] is False
    (rd/'outputs/result.json').write_bytes(b'{}\n')
    with pytest.raises(ValueError):w.verify(result['manifest']['path'],result['manifest']['sha256'])


def test_actual_campaign_route_not_standalone_bypass(tmp_path,monkeypatch):
    cycle=tmp_path/'cycle';cycle.mkdir();owner={'kind':'research_cycle','cycle':str(cycle),'experiment':'original'}
    request,rd,_=workflow_fixture(tmp_path,monkeypatch,owner)
    state={'context':{'request_sha256':'a'*64},'contract':{'same':'original'},'experiments':[{'id':'original','rundir':str(rd),'plan':pin(rd/'inputs/science-plan.json'),'parent':None}]}
    monkeypatch.setattr(research_cycle,'_load',lambda root:(root,state))
    result=w.export(request,tmp_path,tmp_path/'export')
    monkeypatch.setattr(science,'run',lambda *a,**k:pytest.fail('campaign must keep its authority route'))
    def blocked(root,identity,resume):
        assert root==str(cycle) and identity=='original' and resume is False
        raise ValueError('actual parent/cost/protocol boundary')
    monkeypatch.setattr(research_cycle,'run_experiment',blocked)
    with pytest.raises(ValueError):w.run_step(result['manifest']['path'],'analyze',result['manifest']['sha256'])
    assert not (tmp_path/'export/completed/analyze.json').exists()


@pytest.mark.parametrize('fault',['retry','shell','unknown_owner','missing_model','unordered_dependency'])
def test_closed_reproducibility_contract_refusals(tmp_path,monkeypatch,fault):
    request,_,_=workflow_fixture(tmp_path,monkeypatch)
    if fault=='retry':request['wms']['retries']=1
    if fault=='shell':request['tasks'][0]['command']='arbitrary'
    if fault=='unknown_owner':request['tasks'][0]['owner']={'kind':'guessed'}
    if fault=='missing_model':request['audit']['model_build']=''
    if fault=='unordered_dependency':request['tasks'][0]['depends_on']=['unprepared']
    with pytest.raises(ValueError):w.validate(request)


def law(proof,expected=False):
    bins=[{'id':'Signal','role':'signal_region','observed':None,'observation_id':'signal','source':'law'},
          {'id':'Control','role':'control_region','observed':None if expected else 0,'observation_id':'control','source':'law'}] if expected else [{'id':'Control','role':'control_region','observed':0,'observation_id':'control','source':'law'}]
    n=len(bins)
    d={'schema_version':1,'model_id':'Expected' if expected else 'Background','question':'Synthetic complete source-defined background and sensitivity design',
       'sources':[{'id':'law','path':proof['path'],'sha256':proof['sha256']}],
       'parameters':[{'name':'mu','role':'poi','initial':'1','bounds':['0','10'],'fixed':False,'meaning':'supplied strength','source':'law'},
                     {'name':'beta','role':'rate','initial':'1','bounds':['0','10'],'fixed':False,'meaning':'supplied background normalization','source':'law'}],
       'bins':bins,'terms':[{'id':'B','basis':'background','coefficients':['0']*n,'powers':{'beta':1},'log_response':[[] for _ in bins],'source':'law'},
                           {'id':'S','basis':'bsm','coefficients':['0']*n,'powers':{'mu':1},'log_response':[[] for _ in bins],'source':'law'}],
       'auxiliary':{'kind':'supplied_gaussian_factor','names':[],'observed':[],'factor':[],'eta_bounds':[],'source':'law'},
       'partition':{'kind':'declared_disjoint_poisson_counts','source':'law','statement':'Synthetic caller-independent physical event assumption'},
       'prediction':{'units':'expected_events','energy':'13 TeV supplied fixture','luminosity':'1 fb^-1 supplied fixture','basis':'supplied nonnegative background and signal','scale':'supplied','domain_statement':'caller conditional domain','source':'law'},
       'template_statistics':{'kind':'conditional_on_supplied_coefficients','statement':'Full signed MC covariance retained; no nuisance law inferred','source':'law'},
       'assumptions':[{'id':'Conditional','statement':'Synthetic conditional source law, no physics qualification','source':'law','status':'assumed'}]}
    if expected:d['expected_data']={'kind':'regional-background-asimov/v1','conditioning':'supplied_nominal','point':{'mu':'0','beta':'1'},'source':'law','statement':'supplied expected sensitivity state, no observed SR','fit':None}
    return d


def test_connected_blinded_cr_vr_to_actual_background_and_sensitivity_consumers(tmp_path):
    ds,a,cfg,task,proof=population(tmp_path);events=deepcopy(event_population())
    # Positive original synthetic signal-control population for the explicit
    # monotone expected law, accumulated before any projection.
    events['signal'][1]=(1,.5,1,[[.5]])
    delivery=accumulate(ds,a,cfg['limits'],2,events)
    roles={'schema_version':1,'quantity':'regions','bins':[{'id':x,'role':role} for x,role in [('CR','control_region'),('VR','validation_region'),('SR','signal_region')]],'statement':'complete original roles'}
    design={'schema_version':1,'background':law(proof),'expected_sensitivity':law(proof,True),
        'term_bindings':[{'model':model,'term':term,'sample':sample,'quantity':'regions','bin_ids':ids} for model,ids in [('background',['CR']),('expected_sensitivity',['SR','CR'])] for term,sample in [('B','background'),('S','signal')]],
        'control_counts':{'sample':'data','quantity':'regions','bin_ids':['CR']},'validation':{'sample':'data','quantity':'regions','bin_ids':['VR']},
        'region_roles':proof,'statement':'supplied original whole design','native_bundle':None}
    docs,held=stats.project(delivery,design,roles)
    for doc in docs.values():doc['sources'].append({'id':'stream_delivery','path':proof['path'],'sha256':proof['sha256']})
    assert regional.validate(docs['background'])['bins'][0]['observed']==1
    assert regional.mean_jet(docs['background'],{'mu':'0','beta':'1'})['means']==[400.0]
    assert regional.response(docs['expected_sensitivity'])['document']['expected_data']['conditioning']=='supplied_nominal'
    assert all(x['observed'] is None for x in docs['expected_sensitivity']['bins'])
    assert held=={'bin_ids':['VR'],'counts':[1],'fit_executed':False,'held_out':True}
    assert docs['expected_sensitivity']['terms'][0]['coefficients']==['800','400']
    assert docs['expected_sensitivity']['terms'][1]['coefficients']==['750','125']
    assert delivery['samples'][0]['normalization']==ds['samples'][0]['normalization']
    # Exact covariance preserves source same-event overlap; do not map it away.
    data=delivery['samples'][2]['quantities']['regions'];data['covariance'][0][1]=data['covariance'][1][0]=1
    with pytest.raises(ValueError):stats.project(delivery,design,roles)


@pytest.mark.parametrize('fault',['multifill','weighted','sr_observed','vr_fitted','omit_control_signal'])
def test_blinded_statistical_join_refuses_ambiguous_or_missing_population(tmp_path,fault):
    ds,a,cfg,_,proof=population(tmp_path);delivery=accumulate(ds,a,cfg['limits'],2)
    roles={'schema_version':1,'quantity':'regions','bins':[{'id':x,'role':role} for x,role in [('CR','control_region'),('VR','validation_region'),('SR','signal_region')]],'statement':'complete'}
    design={'schema_version':1,'background':law(proof),'expected_sensitivity':law(proof,True),'term_bindings':[{'model':m,'term':t,'sample':s,'quantity':'regions','bin_ids':ids} for m,ids in [('background',['CR']),('expected_sensitivity',['SR','CR'])] for t,s in [('B','background'),('S','signal')]],'control_counts':{'sample':'data','quantity':'regions','bin_ids':['CR']},'validation':{'sample':'data','quantity':'regions','bin_ids':['VR']},'region_roles':proof,'statement':'complete','native_bundle':None}
    if fault=='multifill':delivery['samples'][2]['quantities']['regions']['covariance'][0][0]=2
    if fault=='weighted':delivery['samples'][2]['quantities']['regions']['values']['nominal'][0]=.5
    if fault=='sr_observed':design['expected_sensitivity']['bins'][0]['observed']=0
    if fault=='vr_fitted':design['control_counts']['bin_ids']=['VR']
    if fault=='omit_control_signal':design['term_bindings'].pop()
    with pytest.raises(ValueError):stats.project(delivery,design,roles)


def test_actual_source_handoff_materialization_retains_blinding_and_consumable_laws(tmp_path,monkeypatch):
    ds,a,cfg,task,proof=population(tmp_path);events=deepcopy(event_population());events['signal'][1]=(1,.5,1,[[.5]])
    d=accumulate(ds,a,cfg['limits'],2,events)
    identities=[]
    for s in ds['samples']:
        m=s['members'][0];identity={'guid':m['guid'],'size_bytes':m['size_bytes'],'checksum':{k:m['checksum'][k] for k in ('algorithm','value')},'entries':m['entries']}
        identities.append({'member':m['id'],'before':identity,'after':deepcopy(identity),'evidence_scope':'inert actual source fixture'})
    native={'schema_version':1,'status':'passed','delivery':d,'identities':identities,'physics_validated':False}
    stream.validate_delivery(native,ds,a,cfg['limits'])
    out=tmp_path/'ordinary'/'root-stream';(out/'native').mkdir(parents=True)
    request_pin=stream.write_new(out/'native/request.json',{'config':cfg,'dataset':ds,'analysis':a});native_pin=stream.write_new(out/'native/native-result.json',native)
    value={'schema_version':1,'kind':'root-stream-result','status':'passed','physics_validated':False,'status_scope':stream.SCOPE,
           'delivery':stream.public_delivery(native,ds,a),'errors':[],'native_receipt':None,'limitations':['synthetic pure control only']}
    result_pin=stream.write_new(out/'root-stream-result.json',value)
    cap=core.Capture();stream._load(task,tmp_path,cap);cap.finish()
    g=stream.Guard(value,out,inputs={str(p):r['sha256'] for p,r in cap.rows.items()},native_pin=native_pin,request_pin=request_pin,native_outputs=stream.census(out/'native'))
    closure=stream.write_new(out/'closure.json',g.closure())
    roles=put(tmp_path,'region-roles.json',{'schema_version':1,'quantity':'regions','bins':[{'id':x,'role':r} for x,r in [('CR','control_region'),('VR','validation_region'),('SR','signal_region')]],'statement':'original synthetic roles'})
    design={'schema_version':1,'background':law(proof),'expected_sensitivity':law(proof,True),
        'term_bindings':[{'model':m,'term':t,'sample':s,'quantity':'regions','bin_ids':ids} for m,ids in [('background',['CR']),('expected_sensitivity',['SR','CR'])] for t,s in [('B','background'),('S','signal')]],
        'control_counts':{'sample':'data','quantity':'regions','bin_ids':['CR']},'validation':{'sample':'data','quantity':'regions','bin_ids':['VR']},'region_roles':roles,'statement':'complete synthetic source laws','native_bundle':None}
    # This scientific table oracle uses a disclosed inert successful-origin
    # fixture; the actual ordinary verifier has separate positive/refusal cases.
    monkeypatch.setattr(stream,'ordinary_stream_delivery',lambda result,destination,task:{'result':deepcopy(result),'scientific_acceptance_inferred':False})
    handoff=stats.materialize({'schema_version':1,'stream_task':put(tmp_path,'task.json',task),'stream_result':result_pin,'stream_closure':closure,'design':put(tmp_path,'design.json',design)},tmp_path,tmp_path/'statistics')
    assert handoff['background']['state']=='blocked_missing_original_native_runtime_and_fit'
    assert handoff['sensitivity_computed'] is False and handoff['held_out_validation']['held_out'] is True
    observed=json.loads((tmp_path/'statistics/background.json').read_text())
    expected=json.loads((tmp_path/'statistics/expected_sensitivity.json').read_text())
    assert regional.source_inputs(observed,tmp_path)
    assert regional.mean_jet(observed,{'mu':'0','beta':'1'})['means']==[400.0]
    assert regional.mean_jet(expected,{'mu':'0','beta':'1'})['means']==[800.0,400.0]
    assert all(b['observed'] is None for b in expected['bins'])
    assert handoff['moment_and_variation_evidence']==value['delivery']['samples']
    assert handoff['moment_and_variation_evidence'][2]['visibility']=='original_allowed_CR_VR_aggregates_only'
    public={**value,'commitment':closure}
    stream.write_new(out.parent/'result.json',public);stream.write_report(public,out.parent)
    paths=[str(out.parent/name) for name in ('result.json','root-stream-report.json','root-stream-report.md')]
    checked=stream.blinding_check(public,out,paths,a['blinding']['source'])
    assert checked=={'schema_version':1,'kind':'blinding_preservation_check','policy_sha256':a['blinding']['source']['sha256'],
                     'status':'pass','sr_data_exposed':False,'checked_paths':paths}
    from contextlib import contextmanager
    @contextmanager
    def model_source_session(rd):yield object()
    put(tmp_path,science.PLAN,{'synthetic':'inert lifecycle boundary only'})
    monkeypatch.setattr(science,'_validation_scope',model_source_session)
    monkeypatch.setattr(science,'verify_plan',lambda *args,**kwargs:{'schema_version':2,'stages':[{'outputs':['ordinary']}]})
    monkeypatch.setattr(science,'execution_spec',lambda *args,**kwargs:{'mode':'root-stream','task':task})
    monkeypatch.setattr(stream,'ordinary_delivery',lambda *args,**kwargs:{'result':deepcopy(public),'scientific_acceptance_inferred':False})
    for source in map(Path,paths):
        assert stream.model_input_text(source.read_text(),source_path=source,source_sha256=pin(source)['sha256'])==source.read_text()
    with pytest.raises(ValueError):stream.blinding_check(public,out,[str(out/'native/native-result.json'),*paths[1:]],a['blinding']['source'])
    (out.parent/'root-stream-report.json').write_bytes(stream.encoded({'delivery':native}))
    with pytest.raises(ValueError):stream.blinding_check(public,out,paths,a['blinding']['source'])


def test_frozen_export_rejects_later_root_blind_domain_revision(tmp_path,monkeypatch):
    fixture=tmp_path/'stream';fixture.mkdir();ds,a,cfg,task,proof=population(fixture)
    request,rd,_=workflow_fixture(tmp_path,monkeypatch)
    request['audit']['blinding_policy']=put(tmp_path,'original-export-policy.json',{'schema_version':1,'policy':'exclude_signal_region_data_from_model_and_analysis','review_source':proof,'original_domain':a['blinding']['source']})
    monkeypatch.setattr(science,'execution_spec',lambda rd,**kwargs:{'mode':'root-stream','task':task})
    exported=w.export(request,tmp_path,tmp_path/'export')
    changed=deepcopy(a);changed['blinding']['model_fields']['regions'].append('SR')
    changed['blinding']['allowed_regions'].append('SR')
    modified=put(fixture,'modified-analysis.json',changed);newcfg=deepcopy(cfg);newcfg['analysis']=modified
    newtask={'config':put(fixture,'modified-config.json',newcfg)}
    monkeypatch.setattr(science,'execution_spec',lambda rd,**kwargs:{'mode':'root-stream','task':newtask})
    with pytest.raises(ValueError):w.verify(exported['manifest']['path'],exported['manifest']['sha256'])
