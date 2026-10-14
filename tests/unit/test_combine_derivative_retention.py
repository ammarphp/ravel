"""Source-only attached-observation and durable partial-return controls."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from ravel.physics import combine_derivatives as c, native_likelihood_derivatives as d
from test_combine_derivatives import fixture,Real,Category,MC,Data


def execute(args,recorder=None):return c.execute(*args,d,recorder=recorder)


def attach(args,value=2.):
    data=args[2];data.aux=Real('nom',value,True);data.getGlobalObservables=lambda:[data.aux]
    return data.aux


def test_attached_null_empty_real_category_and_typed_flags_are_distinct():
    args=fixture();data=args[2]
    null=c.data_census(data);data.getGlobalObservables=lambda:[];empty=c.data_census(data)
    assert null!=empty and empty['global_observables']['snapshot']=='set'
    aux=attach(args);real=c.data_census(data);aux.constant=False
    assert c.data_census(data)!=real
    cat=Category('aux_cat');data.getGlobalObservables=lambda:[cat]
    typed=c.data_census(data)['global_observables']['coordinates'][0]
    assert typed['index']==7 and typed['states'][0]['index']==-4 and typed['kind']=='category'
    for bad in [SimpleNamespace(GetName=lambda:'bad',InheritsFrom=lambda k:False),Real('nom',float('inf'),True)]:
        data.getGlobalObservables=lambda:[bad]
        with pytest.raises(ValueError):c.data_census(data)


def test_default_data_snapshot_wins_with_model_fallback_without_changing_objective():
    args=fixture();attach(args,7.)
    result=execute(args)
    semantics=result['definition']['global_observable_semantics']
    assert semantics['explicit_source_option'] is None
    assert semantics['selected_globals'][0]['source']=='data_snapshot'
    assert semantics['selected_globals'][0]['recorded_coordinate']['value']==7.
    assert result['definition']['initial_state']['parameters'][2]['value']==2.
    assert c.validate_delivery(result,args[4],args[5],args[6],d)==result['estimates']
    args=fixture();result=execute(args)
    assert result['definition']['global_observable_semantics']['selected_globals'][0]['source']=='model'


def test_no_explicit_model_globals_records_default_automatic_data_set():
    args=fixture();attach(args,7.);args[1].GetGlobalObservables=lambda:[]
    result=execute(args)
    assert result['definition']['global_observable_semantics']['selected_globals'][0]['name']=='nom'
    assert result['definition']['initial_state']['model_config']['nll_options']==['Constrain(nuisances)']


@pytest.mark.parametrize('version',['6.22/00','6.24/00'])
def test_old_source_qualified_absent_getter_policy_is_explicit(version):
    args=fixture();args[5]['definition']['native_root_version']=version
    args[2].getGlobalObservables=None;args[1].GetExternalConstraints=None
    result=execute(args)
    assert result['definition']['observed_data']['global_observables']=={'accessor':'unavailable','snapshot':'unavailable','coordinates':None}
    assert result['definition']['global_observable_semantics']['default_source']=='model'
    assert result['definition']['initial_state']['model_config']['external_constraints_accessor']=='unavailable'
    c.validate_delivery(result,args[4],args[5],args[6],d)


@pytest.mark.parametrize('version,available',[('6.30/00',False),('6.22/00',True),('unknown',True)])
def test_unknown_or_contradictory_global_api_refuses_before_call(version,available):
    args=fixture();args[5]['definition']['native_root_version']=version
    if not available:args[2].getGlobalObservables=None
    with pytest.raises(ValueError,match='ROOT|API'):execute(args)
    assert not args[3].calls


@pytest.mark.parametrize('change',['value','flag','bounds','replace','category'])
def test_attached_auxiliary_drift_refuses_after_retaining_literal_return(change):
    args=fixture();aux=attach(args);events=[];nll=args[3]
    if change=='value':action=lambda:aux.setVal(7.)
    elif change=='flag':action=lambda:aux.setConstant(False)
    elif change=='bounds':action=lambda:setattr(aux,'bounds',(-100.,100.))
    elif change=='replace':action=lambda:setattr(args[2],'getGlobalObservables',lambda:None)
    else:
        auxcat=Category('cat_aux');args[2].getGlobalObservables=lambda:[auxcat];action=lambda:auxcat.setIndex(-4)
    nll.action=action
    with pytest.raises(ValueError,match='dataset global'):execute(args,events.append)
    assert len(nll.calls)==1
    assert [e['status'] for e in events]==['started','planned','running','returned','failed','reset']
    assert events[3]['payload']['literal_return']['finite']
    assert events[4]['payload']['attempted_calls']==events[4]['payload']['returned_calls']==1


def test_progressive_real_file_retains_first_point_and_later_call_exception(tmp_path):
    args=fixture();nll=args[3];old=nll.getVal;calls=0
    def get():
        nonlocal calls
        calls+=1
        if calls==2:raise RuntimeError('late inert evaluator failure')
        return old()
    nll.getVal=get;path=tmp_path/'points.jsonl';recorder=c.JsonlRecorder(path)
    try:
        with pytest.raises(RuntimeError,match='late'):execute(args,recorder)
    finally:recorder.close()
    rows=c.read_journal(path)
    assert [r['status'] for r in rows]==['started','planned','running','returned','checked','running','failed','reset']
    x,y=[q['value'] for q in nll.calls[0]['parameters'][:2]]
    assert rows[3]['payload']['literal_return']['value']==10+2*x+3*y+5*x*x+7*x*y+11*y*y
    assert rows[-2]['payload']['attempted_calls']==2 and rows[-2]['payload']['returned_calls']==1
    assert rows[-1]['payload']['state']==rows[0]['payload']['initial_state']
    with pytest.raises(FileExistsError):c.JsonlRecorder(path)


@pytest.mark.parametrize('value',[float('inf'),float('-inf'),float('nan')])
def test_nonfinite_returns_stay_tokens_and_cannot_be_successful_numeric_rows(value):
    args=fixture();args[3].getVal=lambda:value;events=[]
    with pytest.raises(ValueError,match='finite'):execute(args,events.append)
    raw=next(r for r in events if r['status']=='returned')['payload']['literal_return']
    assert raw=={'kind':'binary64','hex':value.hex(),'finite':False,'value':None}
    json.dumps(events,allow_nan=False)
    assert not any(r['status']=='checked' for r in events)


def test_nonobservable_drift_is_retained_before_dependent_state_refusal():
    args=fixture();args[3].action=lambda:args[0].var('theta').setVal(3.);events=[]
    with pytest.raises(ValueError,match='non-observable'):execute(args,events.append)
    assert 'returned' in [e['status'] for e in events] and 'checked' not in [e['status'] for e in events]


def test_reduction_failure_keeps_all_raw_checked_points():
    args=fixture();events=[]
    kernel=SimpleNamespace(compile_stencil=d.compile_stencil,reduce_observations=lambda *a:(_ for _ in ()).throw(ValueError('reduction failure')))
    with pytest.raises(ValueError,match='reduction'):c.execute(*args,kernel,recorder=events.append)
    assert len([e for e in events if e['status']=='checked'])==len(args[3].calls)>1
    assert events[-2]['status']=='failed' and events[-1]['status']=='reset'


@pytest.mark.parametrize('status',['started','planned','running','returned','checked','reduced'])
def test_recorder_failure_permits_no_further_nll_call(status):
    args=fixture();events=[]
    def recorder(event):
        if event['status']==status:raise OSError('inert journal failure')
        events.append(event)
    with pytest.raises(OSError,match='journal'):execute(args,recorder)
    count=len(args[3].calls)
    assert count==(0 if status in ('started','planned','running') else len(d.compile_stencil({'schema_version':1,'kind':'native-likelihood-stencil','identity':{'model_sha256':'1'*64,'runtime_binding_sha256':'2'*64,'evaluation_definition_sha256':'3'*64},'parameters':c._anchor(c.capture(args[0],args[1]),args[4],args[6])['parameters'],'axes':args[4]['axes'],'max_points':256})['points']) if status=='reduced' else 1)


def test_success_journal_complete_hash_chain_and_host_replay(tmp_path):
    args=fixture();path=tmp_path/'points.jsonl';writer=c.JsonlRecorder(path)
    try:result=execute(args,writer)
    finally:writer.close()
    assert c.read_journal(path)==result['point_journal']
    c.validate_delivery(result,args[4],args[5],args[6],d)
    for mutate in [lambda q:q['point_journal'].pop(),lambda q:q['point_journal'][3]['payload']['literal_return'].update(value=0.),lambda q:q['point_journal'][2].update(binding_sha256='0'*64),lambda q:q['native_states'][0]['dataset_globals_after'].update(snapshot='set',coordinates=[])]:
        bad=deepcopy(result);mutate(bad)
        with pytest.raises(ValueError):c.validate_delivery(bad,args[4],args[5],args[6],d)


def test_writer_byte_budget_and_short_write_refusal_are_real_file_controls(tmp_path,monkeypatch):
    path=tmp_path/'budget.jsonl';writer=c.JsonlRecorder(path)
    try:
        monkeypatch.setattr(c,'MAX_JOURNAL_BYTES',1)
        with pytest.raises(ValueError,match='budget'):writer({'not':'written'})
        assert path.stat().st_size==0
        monkeypatch.setattr(c,'MAX_JOURNAL_BYTES',1000)
        with patch.object(c.os,'write',return_value=0),pytest.raises(OSError,match='progress'):writer({'not':'written'})
    finally:writer.close()


def test_optional_pure_memory_recorder_exposes_partial_facts_on_exception():
    args=fixture();original=args[3].getVal;calls=0
    def get():
        nonlocal calls
        calls+=1
        if calls==2:raise RuntimeError('late pure memory failure')
        return original()
    args[3].getVal=get
    with pytest.raises(RuntimeError) as found:execute(args)
    assert [e['status'] for e in found.value.native_point_journal]==['started','planned','running','returned','checked','running','failed','reset']
    assert found.value.native_call_accounting=={'attempted':2,'returned':1,'durable_recorder_supplied':False,'successful_delivery':False}


def test_modern_external_constraint_accessor_cannot_inherit_legacy_absence():
    args=fixture();args[1].GetExternalConstraints=None
    with pytest.raises(ValueError,match='external constraint API'):execute(args)
    assert args[3].calls==[]


@pytest.mark.parametrize('version',['6.22/00','6.24/00','6.30/00'])
def test_pdf_default_tag_supplied_globals_refuse_before_value_call(version):
    args=fixture();args[5]['definition']['native_root_version']=version
    args[1].GetGlobalObservables=lambda:[];args[1].pdf.getStringAttribute=lambda key:'auxiliaryTag'
    if version!='6.30/00':args[2].getGlobalObservables=None;args[1].GetExternalConstraints=None
    else:attach(args,7.)
    events=[]
    with pytest.raises(ValueError,match='DefaultGlobalObservablesTag'):execute(args,events.append)
    assert args[3].calls==[] and not any(e['status']=='running' for e in events)


@pytest.mark.parametrize('version',['6.22/00','6.24/00','6.30/00'])
def test_explicit_model_globals_override_pdf_default_tag_without_changing_options(version):
    args=fixture();args[5]['definition']['native_root_version']=version
    args[1].pdf.getStringAttribute=lambda key:'unusedBecauseExplicitGlobals'
    if version!='6.30/00':args[2].getGlobalObservables=None;args[1].GetExternalConstraints=None
    result=execute(args)
    assert result['definition']['initial_state']['model_config']['default_global_observables_tag']=='unusedBecauseExplicitGlobals'
    assert result['definition']['global_observable_semantics']['selected_globals'][0]['name']=='nom'
    assert result['definition']['global_observable_semantics']['explicit_source_option'] is None
    c.validate_delivery(result,args[4],args[5],args[6],d)


def test_pdf_default_tag_changes_during_evaluation_refuse_and_retain_return():
    args=fixture();args[3].action=lambda:setattr(args[1].pdf,'getStringAttribute',lambda key:'changedTag');events=[]
    with pytest.raises(ValueError):execute(args,events.append)
    assert len(args[3].calls)==1 and any(e['status']=='returned' for e in events)


def test_truthy_empty_global_option_is_distinct_from_absent_option():
    class TruthyEmpty(list):
        def __bool__(self):return True
    args=fixture();args[1].GetGlobalObservables=lambda:TruthyEmpty()
    args[1].pdf.getStringAttribute=lambda key:'ignoredByExplicitEmptyOption';attach(args,7.)
    result=execute(args);meta=result['definition']['initial_state']['model_config']
    assert meta['global_observables']==[] and meta['supplied_nll_options']['global_observables'] is True
    assert meta['nll_options']==['Constrain(nuisances)','GlobalObservables(globals)']
    assert result['definition']['global_observable_semantics']['selected_globals']==[]
    c.validate_delivery(result,args[4],args[5],args[6],d)
