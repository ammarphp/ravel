"""Receipt-census regressions; inert software facade, no ROOT/fit qualification."""
from copy import deepcopy
from fractions import Fraction as F
import json
import pytest
from ravel.physics import regional_calibration as c, statistical_construction as r, continuous_dijet_shapes as k
from test_dijet_calibration import fixture,delivery,facade
from test_regional_expected import e

@pytest.mark.parametrize('change',['admission_mean_checks','toy_mean_checks','admission_truth_means','erase_resolved_audit','certified_reference_flag','forged_kernel_counters'])
def test_original_peer_receipt_omissions_refuse(tmp_path,change):
    d,q,result,_=delivery(tmp_path);row=result['rows'][0]
    if change=='admission_mean_checks':result['reference_admission']['reference_audit']['mean_checks']=[]
    elif change=='toy_mean_checks':row['reference_audit']['mean_checks']=[]
    elif change=='admission_truth_means':result['reference_admission']['truth_means']=[]
    elif change=='erase_resolved_audit':row['reference_audit'].update(calls=[],mean_checks=[],reserved_evaluations=0,known_successful_evaluations=0)
    elif change=='certified_reference_flag':result['reference_admission']['estimated_reference_uncertainty_is_certified']=True
    else:
        call=row['reference_audit']['calls'][0];call['actual_evaluations']=call['result']['evaluations']=1;call['result']['subdivisions']=999999
        row['reference_audit']['known_successful_evaluations']=sum(call['actual_evaluations'] or 0 for call in row['reference_audit']['calls'])
    with pytest.raises(ValueError):c.validate_delivery(result,r.response(d),q,e)

@pytest.mark.parametrize('change',['extra_mean','extra_call','reordered_state','missing_bin','truth_mean','counter_bool','counter_negative','counter_depth','counter_attempts','counter_reuse'])
def test_complete_report_census_and_feasible_source_counts(tmp_path,change):
    d,q,result,_=delivery(tmp_path);audit=result['rows'][0]['reference_audit'];call=audit['calls'][0]
    if change=='extra_mean':audit['mean_checks'].append(deepcopy(audit['mean_checks'][-1]))
    elif change=='extra_call':audit['calls'].append(deepcopy(call));audit['reserved_evaluations']+=call['reserved_evaluations'];audit['known_successful_evaluations']+=call['actual_evaluations']
    elif change=='reordered_state':audit['mean_checks'][0]['point']['mu']='3/2'
    elif change=='missing_bin':result['reference_admission']['truth_means'][0]['means'].pop('MC')
    elif change=='truth_mean':result['reference_admission']['truth_means'][0]['means']['SR']+=1
    elif change=='counter_bool':call['result']['subdivisions']=True
    elif change=='counter_negative':call['result']['subdivisions']=-1
    elif change=='counter_depth':call['result']['subdivisions']=3*(2**20)
    elif change=='counter_attempts':call['result']['subdivisions']=0
    else:call['result']['subdivisions']=100000
    with pytest.raises(ValueError):c.validate_delivery(result,r.response(d),q,e)


def test_structurally_feasible_counts_are_not_host_traversal_identity(tmp_path):
    d,q,result,_=delivery(tmp_path);old=deepcopy(result)
    for audit in [result['reference_admission']['reference_audit'],result['rows'][0]['reference_audit']]:
        for call in audit['calls']:
            assert call['result']['evaluations']>100
            call['actual_evaluations']=call['result']['evaluations']=101
            call['result']['subdivisions']=25
        audit['known_successful_evaluations']=sum(call['actual_evaluations'] for call in audit['calls'])
    raw=deepcopy(result);c.validate_delivery(result,r.response(d),q,e)
    assert result==raw and result!=old


def test_complete_multiple_truths_and_same_physical_ordinal_population(tmp_path):
    d,q=fixture(tmp_path);q['truths'][0]['point']['ravel_aux_0']='0'
    q['truths'].append({'id':'second','point':{**q['truths'][0]['point'],'alpha':'1/10'}});q['trials_per_truth']=2
    rt,w,mc,data,_=facade(tmp_path,d,q)
    result=c.execute(rt,w,mc,data,r.response(d),q,e,tmp_path/'multiple.json',30.)
    assert all(row['status']=='included' for row in result['rows'])
    raw=deepcopy(result);c.validate_delivery(result,r.response(d),q,e)
    assert result==raw and len(result['reference_admission']['truth_means'])==2 and len(result['rows'])==4
    result['reference_admission']['truth_means'].reverse()
    with pytest.raises(ValueError):c.validate_delivery(result,r.response(d),q,e)


@pytest.mark.parametrize('failure',['kernel_partial','total_mean','profile'])
def test_genuine_incomplete_prefix_and_unknown_cost_remain_unresolved(tmp_path,monkeypatch,failure):
    d,q=fixture(tmp_path);q['truths'][0]['point']['ravel_aux_0']='0'
    if failure=='kernel_partial':
        extra=deepcopy(d['terms'][0]);extra.update(id='extra',coefficients=['1','1','0']);d['terms'].append(extra)
    rt,w,mc,data,_=facade(tmp_path,d,q)
    original=k.reference;seen=[]
    def reference(shape,coefficients):
        seen.append(1)
        if failure=='kernel_partial' and len(seen)==4:raise ValueError('explicit inert partial source-reference failure')
        value=original(shape,coefficients)
        return value
    monkeypatch.setattr(k,'reference',reference)
    finite=c.finite;mean_calls=[]
    def checked(value,name):
        if name=='total mean':
            mean_calls.append(1)
            if failure=='total_mean' and len(mean_calls)==4:raise ValueError('explicit inert TOTAL mean failure after returned reference')
        return finite(value,name)
    monkeypatch.setattr(c,'finite',checked)
    if failure=='profile':monkeypatch.setattr(e,'_profile_fit',lambda *_:(_ for _ in ()).throw(ValueError('explicit inert profile failure')))
    result=c.execute(rt,w,mc,data,r.response(d),q,e,tmp_path/'prefix.json',30.)
    monkeypatch.setattr(k,'reference',original);monkeypatch.setattr(c,'finite',finite)
    row=result['rows'][0];assert row['status']=='unresolved' and row['error']['type']=='ValueError'
    raw=deepcopy(result);c.validate_delivery(result,r.response(d),q,e);assert result==raw
    audit=row['reference_audit']
    if failure=='kernel_partial':
        assert [v['status'] for v in audit['calls']]==['returned','failed'] and audit['calls'][-1]['actual_evaluations'] is None and not audit['mean_checks']
    elif failure=='total_mean':assert len(audit['calls'])==1 and audit['calls'][0]['status']=='returned' and not audit['mean_checks']
    else:assert len(audit['calls'])==len(audit['mean_checks'])==1 and row['observation'] and result['top_level_profile_requests']==1
    assert result['summary']['cohorts'][0]['scheduled']==1 and result['summary']['cohorts'][0]['identification_interval']==[0,1]


def test_unissued_reservations_are_not_fabricated_consumption(tmp_path):
    d,q=fixture(tmp_path);q['reference_budget']['toy_reserved_evaluations']=100000
    rt,w,mc,data,_=facade(tmp_path,d,q);result=c.execute(rt,w,mc,data,r.response(d),q,e,tmp_path/'unissued.json',30.)
    raw=deepcopy(result);c.validate_delivery(result,r.response(d),q,e);assert result==raw
    assert result['rows'][0]['status']=='unissued' and result['top_level_profile_requests']==0 and len(result['rows'])==1
    result['rows'][0]['reference_audit']=c.ReferenceAudit(q,d,'toy').evidence
    with pytest.raises(ValueError):c.validate_delivery(result,r.response(d),q,e)
