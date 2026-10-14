"""Real source extraction -> protocol checks -> ordinary Graph/Host, no jobs."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest
from ravel.physics import sfitter_scan_extraction as e
from ravel.workflow import sfitter_scan_review as r, agent_graph as g
from ravel.workflow.agent_host import AgentHost
from test_sfitter_scan_extraction import fixture
from test_sfitter_adapter import save, pin, BASIS
from test_physics_review import run, opened


def setup(tmp, *, split_groups=False, **kwargs):
    base, source, sp, wf, docs, card, rates, coef, C = fixture(tmp, **kwargs)
    if split_groups:
        target=wf['target']; first=deepcopy(target['observables'][0])
        first.update(bins=['left'],normalization='absolute')
        second=deepcopy(first);second.update(ID='second',name='second_group',bins=['right'])
        target['observables']=[first,second]
        ext=[]; original=docs['extraction']['payload']['rows'][0]
        for i,ob in enumerate(target['observables']):
            row=deepcopy(original);row.update(ID=ob['ID'],name=ob['name'],bin_widths=[original['bin_widths'][i]])
            for slot in ('Meas','Bkg'):
                row[slot]['data']=[original[slot]['data'][i]]
                for m in row[slot]['modifiers']:m['data']=[m['data'][i]]
            ext.append(row)
        docs['extraction']['payload']['rows']=ext
        sm=docs['sm_template']['payload']['rows'][0]
        docs['sm_template']['payload']['rows']=[{**deepcopy(sm),'ID':ob['ID'],'name':ob['name'],'data':[10.+10*i]} for i,ob in enumerate(target['observables'])]
        for phase in ('extraction','sm_template'):
            docs[phase]['target_sha256']=g.digest(target);wf['handoffs'][phase]=save(base/(phase+'.json'),docs[phase])
        source['workflow']=save(base/'workflow.json',wf)
        rates['target_sha256']=g.digest(target)
        rates['bins']=[{'observable_id':ob['ID'],'bin_id':ob['bins'][0],'unit':ob['unit'],'representation':ob['representation'],'bin_width':2.+i} for i,ob in enumerate(target['observables'])]
        rates['joint_covariance']['coordinates']=[{'point_id':p['id'],'observable_id':b['observable_id'],'bin_id':b['bin_id'],'quantity':'rate'} for p in rates['points'] for b in rates['bins']]
        definition=json.loads(Path(source['scan_definition']['path']).read_bytes());definition['target_sha256']=g.digest(target)
        source['scan_definition']=save(base/'scan-definition.json',definition)
        source['rates']=save(base/'rates.json',rates);sp=save(base/'request.json',source)
    receipt = e.materialize(sp, base, tmp/'extracted')
    receipt_pin = pin(tmp/'extracted/extraction-receipt.json')
    primary = save(base/'review-premises.json', {'acceptance': 'total',
        'criterion': 'Explicit synthetic finite-point source-control band; not calibrated physics acceptance.'})
    regime = save(base/'regime.json', {'schema_version': 1, 'observables': [
        {'ID': ob['ID'], 'acceptance': 'total', 'source': {'artifact': primary, 'location': '/acceptance'}}
        for ob in wf['target']['observables']], 'sources': [primary]})
    criterion = {'absolute': 1e-10, 'relative': 0., 'justification': {'artifact': primary, 'location': '/criterion'}}
    request = {'schema_version': 1, 'id': 'source_scan_review', 'extraction_request': sp,
        'extraction_receipt': receipt_pin, 'regime': regime,
        'criteria': {name: {ob['ID']: deepcopy(criterion) for ob in wf['target']['observables']}
                     for name in ('baseline', 'polynomial')},
        'check_ids': ['agreement'], 'claim_scope': 'reproduction'}
    return base, request, save(base/'review-request.json', request), source, wf, docs, rates, receipt, coef, C


def test_complete_return_to_actual_protocol_and_role_preparation_boundary(tmp_path):
    base, request, rp, source, wf, docs, rates, receipt, coef, C = setup(tmp_path)
    result = r.prepare(rp, base, tmp_path/'review')
    report = json.loads(Path(result['protocol_report']['path']).read_bytes())
    concern = next(c for c in report['concerns'] if c['id']=='coefficient_baseline')
    assert concern['status']=='pass'
    assert {c['method'] for c in concern['checks']}=={'polynomial', 'vector_agreement'}
    assert len(concern['checks'][0]['recomputation']['points'])==len(rates['points'])
    assert len(report['warnings'])==8 and report['old_votes_carried']==[]
    assert result['next'].startswith('existing sfitter_review_protocol.prepare_role')
    assert not result['execution_authorized'] and not result['native_fit_completed']
    # Domain checks use the real SM template, not the separately fitted intercept.
    data=json.loads(Path(result['projection']['path']).read_bytes())
    assert data['polynomial'][0]['offset']==docs['sm_template']['payload']['rows'][0]['data']
    assert {(p['path'],p['sha256']) for p in data['inputs']} <= {(p['path'],p['sha256']) for p in report['inputs']}
    original=json.loads(Path(request['regime']['path']).read_bytes())
    derived=json.loads((tmp_path/'review/review-regime.json').read_bytes())
    assert original['observables']==derived['observables']


def test_full_shape_covariance_has_returned_data_jacobian_and_crosspoint_terms(tmp_path):
    base, request, *_ = setup(tmp_path, quadratic=False)
    result = r.analyze(request, base)
    J=np.asarray(result['native_covariance_jacobian']); source=e.extract(
        json.loads(Path(request['extraction_request']['path']).read_bytes()), base)
    Y=np.asarray(source['normalized_rates']); expected=np.zeros_like(J)
    for i,row in enumerate(Y):
        integral=row @ np.array([2.,3.])
        expected[i*2:(i+1)*2,i*2:(i+1)*2]=np.eye(2)/integral-np.outer(row,[2.,3.])/integral**2
    np.testing.assert_allclose(J,expected,atol=1e-15)
    np.testing.assert_allclose(result['native_covariance'],J @ np.asarray(source['normalized_joint_covariance'])@J.T,atol=1e-14)
    assert result['native_covariance'][0][2]!=0 and 'first-order delta' in result['covariance_scope']


def test_isolated_component_is_preserved_and_never_normalized_as_total(tmp_path):
    base, request, rp, _, wf, _, rates, *_ = setup(tmp_path, components=True)
    result=r.analyze(request,base)
    isolated=[row for row in result['coverage'] if row['component']=='linear']
    assert len(isolated)==1 and isolated[0]['native_observed'] is None
    assert isolated[0]['disposition']=='isolated_component_extraction_evidence'
    assert len(result['coverage'])==len(rates['points'])
    assert len(result['polynomial'][0]['points'])==len(rates['points'])-1
    assert len(result['covariance_coordinate_order'])==len(rates['points'])*2
    receipt=r.prepare(rp,base,tmp_path/'review')
    report=json.loads(Path(receipt['protocol_report']['path']).read_bytes())
    assert next(c for c in report['concerns'] if c['id']=='coefficient_baseline')['status']=='pass'


def test_complete_two_observable_baseline_polynomial_and_covariance_census(tmp_path):
    base,request,rp,*_=setup(tmp_path,quadratic=False,split_groups=True)
    receipt=r.prepare(rp,base,tmp_path/'review')
    projection=json.loads(Path(receipt['projection']['path']).read_bytes())
    assert [p['observable'] for p in projection['polynomial']]==['control','second']
    assert [p['observable'] for p in projection['independent_sm']]==['control','second']
    assert all(len(p['observed'])==1 for group in projection['polynomial'] for p in group['points'])
    n=len(projection['covariance_coordinate_order'])
    np.testing.assert_array_equal(projection['native_covariance_jacobian'],np.eye(n))
    report=json.loads(Path(receipt['protocol_report']['path']).read_bytes())
    concern=next(c for c in report['concerns'] if c['id']=='coefficient_baseline')
    assert concern['status']=='pass' and len(concern['checks'])==4


def test_actual_graph_host_reads_the_whole_source_and_missing_input_refuses(tmp_path):
    base, request, rp, *_ = setup(tmp_path, quadratic=False)
    spec=r.graph(request,base,rp);rd=tmp_path/'graph';g.create(rd,spec)
    assert g.execute(rd,AgentHost(api_key='not-used'),workers=1)['complete']
    _,state=g._load(rd);answer=g._result(rd,state['nodes']['domain']['result'])
    assert answer['result']['value']['kind']=='sfitter_scan_domain_source_projection'
    assert g.status(rd)['usage']['calls']==1
    broken=deepcopy(spec);broken['graph_id']='omission';broken['nodes'][0]['inputs'].pop()
    rd=tmp_path/'omission';g.create(rd,broken)
    assert not g.execute(rd,AgentHost(api_key='not-used'),workers=1)['complete']


def test_prepared_complete_source_concern_enters_existing_role_api_without_calls(run,tmp_path):
    opened(run);actual_run=run[0]
    base,request,rp,*_=setup(tmp_path,quadratic=False)
    prepared=r.prepare(rp,base,tmp_path/'review')
    # Existing tiny review journal uses explicitly synthetic authority fixture;
    # this is preparation, not a scientific vote or a dispatched model role.
    binding=r.protocol.prepare_role(actual_run,prepared['protocol_request'],tmp_path/'role',
        role='critic',actor_id='critic',model='control-only',reasoning_effort='high',
        max_output_tokens=1024,max_wall_seconds=20,allow_control=True)
    assert binding['request']==prepared['protocol_request']
    assert not binding['execution_authorized'] and not binding['physics_validated']
    from ravel.workflow import physics_review
    assert physics_review.status(actual_run)['state']=='awaiting_review'


@pytest.mark.parametrize('target',['report','parameterization','workflow','authority'])
def test_rehashed_unrelated_or_changed_returned_handoffs_do_not_become_review_evidence(tmp_path,target):
    base, request, rp, _, wf, _, rates, receipt, *_ = setup(tmp_path, quadratic=False)
    if target=='authority':
        receipt['execution_authorized']=True
    else:
        path=Path(receipt[target]['path']);doc=json.loads(path.read_bytes())
        if target=='report':doc['raw_point_population'][0]['weight_population'][0]['sumw']='99'
        elif target=='parameterization':doc['payload']['rows'][0]['modifiers'][0]['data'][0]+=1.
        else:doc['target']['process']='unrelated source process'
        receipt[target]=save(path,doc)
    request['extraction_receipt']=save(Path(request['extraction_receipt']['path']),receipt)
    with pytest.raises(ValueError):r.analyze(request,base)


@pytest.mark.parametrize('target',['scan-domain-projection.json','review-regime.json','domain-request.json','domain-report.json','domain-preparation-receipt.json','extra.json'])
def test_ending_delivery_rechecks_every_member_after_last_callback(tmp_path,monkeypatch,target):
    base,request,rp,*_=setup(tmp_path,quadratic=False);original=e.atomic_json
    def mutate(path,value):
        original(path,value)
        if Path(path).name=='domain-preparation-receipt.json':
            (Path(path).parent/target).write_text('late divergent output')
    monkeypatch.setattr(e,'atomic_json',mutate)
    with pytest.raises(ValueError):r.prepare(rp,base,tmp_path/'review')


def test_ending_original_source_drift_is_refused(tmp_path,monkeypatch):
    base,request,rp,*_=setup(tmp_path,quadratic=False);original=r.protocol.context
    def mutate(*args,**kwargs):
        result=original(*args,**kwargs)
        Path(request['regime']['path']).write_text('{}')
        return result
    monkeypatch.setattr(r.protocol,'context',mutate)
    with pytest.raises(ValueError):r.prepare(rp,base,tmp_path/'review')


@pytest.mark.parametrize('kind',['partial_regime','bad_criterion','missing_criterion','zero_reference','output_alias'])
def test_real_domain_source_refusals(tmp_path,kind):
    base,request,rp,*_=setup(tmp_path,quadratic=False)
    if kind=='partial_regime':request['regime']=save(Path(request['regime']['path']),{'schema_version':1,'observables':[],'sources':[]})
    elif kind=='bad_criterion':request['criteria']['polynomial']['control']['relative']=float('inf')
    elif kind=='missing_criterion':request['criteria']['baseline'].clear()
    elif kind=='zero_reference':request['criteria']['baseline']['control']['justification']['location']='/absent'
    else:
        with pytest.raises(ValueError):r.prepare(rp,base,tmp_path/'unrelated/../inputs/derived')
        return
    if kind=='bad_criterion':
        with pytest.raises(ValueError):r.analyze(request,base)
    else:
        rp=save(Path(rp['path']),request)
        with pytest.raises((ValueError,KeyError)):r.prepare(rp,base,tmp_path/'review')


def test_nonpositive_total_integrals_remain_unresolved_not_dropped(tmp_path):
    base,source,sp,wf,docs,card,rates,coef,C=fixture(tmp_path,quadratic=False)
    coef[1]=[-50.,-50.]
    for point in rates['points']:
        D,_=e._design(wf,[point],[[e._coordinate(point['values'][axis]) for axis in BASIS]])
        point['rates']=((D@coef)[0]/.4).tolist()
    source['rates']=save(base/'rates.json',rates);sp=save(base/'request.json',source)
    receipt=e.materialize(sp,base,tmp_path/'extracted')
    assert receipt['handoff_eligible']
    primary=save(base/'premise.json',{'criterion':'Toy criterion','acceptance':'total'})
    criterion={'absolute':1e-10,'relative':0.,'justification':{'artifact':primary,'location':'/criterion'}}
    request={'schema_version':1,'id':'invalid_integral','extraction_request':sp,
      'extraction_receipt':pin(tmp_path/'extracted/extraction-receipt.json'),
      'regime':save(base/'regime.json',{'schema_version':1,'observables':[{'ID':'control','acceptance':'total','source':{'artifact':primary,'location':'/acceptance'}}],'sources':[primary]}),
      'criteria':{k:{'control':criterion} for k in ('baseline','polynomial')},'check_ids':['agreement'],'claim_scope':'reproduction'}
    rp=save(base/'review-request.json',request);result=r.prepare(rp,base,tmp_path/'review')
    projection=json.loads(Path(result['projection']['path']).read_bytes())
    assert projection['unresolved_native_normalizations'] and projection['native_covariance'] is None
    assert len(projection['coverage'])==len(rates['points'])
    report=json.loads(Path(result['protocol_report']['path']).read_bytes())
    assert next(c for c in report['concerns'] if c['id']=='coefficient_baseline')['status']=='inconclusive'
