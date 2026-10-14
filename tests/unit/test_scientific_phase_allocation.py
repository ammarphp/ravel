import copy
import pytest
from ravel.workflow import scientific_phase_allocation as module
allocate=module.allocate

def vector(calls=0,tokens=0,wall=0,native=0):
    return dict(calls=calls,output_tokens=tokens,wall_seconds=wall,native_attempts=native)
def request():
    return dict(schema_version=1,budget=vector(6,24576,300,2),usage=vector(),checks=[{'id':'density','cost':vector(1,0,60)},{'id':'stationarity','cost':vector(1,0,30)},{'id':'reference','cost':vector(1,0,30)}],designs=[{'id':'candidate','construction_cost':vector(1,4096,30,1),'check_ids':['density','stationarity','reference'],'polish_cost':vector(1,4096,30,1)}],completed_check_ids=[],retained_design_ids=[],mandatory_check_ids=['density','stationarity','reference'])

def test_reserves_checks_before_construction():
    r=allocate(request());assert r['check_reservation']==vector(3,0,120)
    assert r['affordable_design_ids']==['candidate'];assert r['polishable_design_ids']==[]
    assert r['designs'][0]['construction']['required_total_with_reservation']==vector(4,4096,150,1)

def test_independent_checks_cannot_be_replaced_by_optimizer_success():
    q=request();q['retained_design_ids']=['candidate'];q['usage']=vector(1,4096,30,1)
    r=allocate(q);assert r['designs'][0]['polish']['reason']=='checks_pending';assert r['pending_reserved_check_ids']==['density','stationarity','reference']

def test_optional_polish_only_after_complete_checks():
    q=request();q['retained_design_ids']=['candidate'];q['completed_check_ids']=['density','stationarity','reference'];q['usage']=vector(4,4096,150,1)
    r=allocate(q);assert r['polishable_design_ids']==['candidate'];assert r['check_reservation']==vector()

@pytest.mark.parametrize('key,value',[('calls',0),('output_tokens',0),('wall_seconds',100),('native_attempts',0)])
def test_each_independent_cap_blocks_new_design(key,value):
    q=request();q['budget'][key]=value;r=allocate(q)
    assert r['blocked_design_ids']==['candidate'];assert r['designs'][0]['construction']['deficits'][key]>0

def test_shared_checks_reserve_once_and_keep_explicit_order():
    q=request();q['designs'].append({**q['designs'][0],'id':'second'});q['retained_design_ids']=['candidate','second']
    r=allocate(q);assert r['check_reservation']==vector(3,0,120);assert r['pending_reserved_check_ids']==['density','stationarity','reference']

def test_new_design_additional_checks_are_not_lost():
    q=request();q['mandatory_check_ids']=[];q['designs'][0]['check_ids']=['density'];q['checks'].append({'id':'fresh','cost':vector(2,0,70)})
    q['designs'].append({**q['designs'][0],'id':'second','check_ids':['fresh']});q['retained_design_ids']=['candidate']
    r=allocate(q);row=r['designs'][1]['construction'];assert row['additional_check_ids']==['fresh'];assert row['required_total_with_reservation']==vector(4,4096,160,1)

def test_declared_overrun_is_retained_and_blocks_zero_cost_work():
    q=request();q['usage']['calls']=7;q['completed_check_ids']=['density','stationarity','reference'];q['designs'][0]['construction_cost']=vector();q['designs'][0]['polish_cost']=vector()
    r=allocate(q);assert r['actual_usage_overrun']['calls']==1;assert r['blocked_design_ids']==['candidate']
    q['retained_design_ids']=['candidate'];assert allocate(q)['polishable_design_ids']==[]

def test_result_is_not_execution_or_scientific_authority():
    r=allocate(request());assert r['individual_feasibility_only'];assert not r['execution_authorized'];assert not r['scientific_completion_inferred']

def test_retained_result_is_preserved_even_when_checks_unaffordable():
    q=request();q['retained_design_ids']=['candidate'];q['usage']=vector(5,8192,290,2)
    r=allocate(q);assert r['designs'][0]['construction']['status']=='retained';assert r['check_reservation_deficits']['calls']==2;assert r['check_reservation_deficits']['wall_seconds']==110

def test_no_input_alias_or_mutation():
    q=request();before=copy.deepcopy(q);r=allocate(q);assert q==before;r['budget']['calls']=0;assert q==before

@pytest.mark.parametrize('field,value',[('schema_version',True),('budget',{}),('checks',{}),('designs',{}),('completed_check_ids',['unknown']),('retained_design_ids',['unknown']),('mandatory_check_ids',['density','density'])])
def test_malformed_request_refuses(field,value):
    q=request();q[field]=value
    with pytest.raises(ValueError):allocate(q)

@pytest.mark.parametrize('field',['budget','usage'])
@pytest.mark.parametrize('key,value',[('calls',True),('calls',1.0),('output_tokens',-1),('native_attempts','1'),('wall_seconds',float('inf')),('wall_seconds',float('nan')),('wall_seconds',True)])
def test_invalid_costs_refuse(field,key,value):
    q=request();q[field][key]=value
    with pytest.raises(ValueError):allocate(q)

def test_unknown_or_duplicate_structure_refuses():
    for edit in [lambda q:q.update(extra=1),lambda q:q['checks'].append(q['checks'][0]),lambda q:q['designs'].append(q['designs'][0]),lambda q:q['designs'][0].update(check_ids=['absent']),lambda q:q['checks'][0].update(extra=1)]:
        q=request();edit(q)
        with pytest.raises(ValueError):allocate(q)

def test_equal_budget_constructed_portfolio_reserves_three_checks_before_polish():
    # Policy correctness control, not real optimization/efficacy evidence.
    q=dict(schema_version=1,budget=vector(6),usage=vector(),checks=[{'id':'check-'+str(i),'cost':vector(1)} for i in range(3)],designs=[{'id':'start-'+str(i),'construction_cost':vector(1),'check_ids':['check-'+str(i)],'polish_cost':vector(1)} for i in range(3)],completed_check_ids=[],retained_design_ids=[],mandatory_check_ids=['check-'+str(i) for i in range(3)])
    history=[]
    for i in range(3):
        result=allocate(q);identity='start-'+str(i);assert identity in result['affordable_design_ids'];assert result['polishable_design_ids']==[]
        q['retained_design_ids'].append(identity);q['usage']['calls']+=1;history.append(result)
    result=allocate(q);assert result['check_reservation']['calls']==3;assert result['available_after_reservation']['calls']==0
    for i in range(3):q['completed_check_ids'].append('check-'+str(i));q['usage']['calls']+=1
    assert allocate(q)['polishable_design_ids']==[]
    # Same constructed action costs:3construction+1polish leaves only2checks.
    assert 6-3-1==2;assert len(q['completed_check_ids'])==3;assert q['usage']['calls']==6
