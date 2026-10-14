"""Prospective software custody controls; author has not imported/run these.

Small tests use declared synthetic receipts with real runtime, snapshots and
validators, never mocked green stage proof. Connected tests retain the existing
explicit inert native/approval fixture and actual public qualification/build APIs.
No result here establishes real native, scientific or publisher qualification.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import pytest
from ravel.workflow import execution as e, publication_runtime as pr, report_integrity as ri
from ravel.physics import manuscript_build as mb
from test_publication_runtime_v2 import LIMITS, pin, put, qualification_fixture


def fixture(root):
    """Complete tiny declared population; never dispatch the inert command."""
    rd=root/'declared-qualification';rd.mkdir(parents=True)
    inputs=rd/'input';inputs.mkdir();put(inputs/'selected.dat',b'selected');put(inputs/'unselected.dat',b'unselected')
    (inputs/'empty').mkdir();outputs=rd/'output';outputs.mkdir()
    selected=put(outputs/'selected.json',{'synthetic_software_only':True});put(outputs/'unselected.dat',b'unselected result')
    log=rd/'logs/control.log';put(log,b'Synthetic declaration, no native process launched\n')
    runtime=e.runtime_context()
    record={'stage':'qualification','attempt_id':'declared-control-attempt','attempt_record':'logs/attempt/record.json',
        'command':['inert-software-declaration'],'cwd':str(rd),'inputs':[str(inputs)],'outputs':[str(outputs)],
        'parents':{},'runtime':runtime,'runtime_environment':e.runtime_environment(),'status':'succeeded',
        'input_snapshot':e.snapshot(rd,[str(inputs)]),'output_snapshot':e.snapshot(rd,[str(outputs)],outputs=True),
        'log':'logs/control.log','log_snapshot':e.snapshot(rd,[str(log)])}
    record['fingerprint']=e.digest({k:record[k] for k in ('command','cwd','inputs','outputs','input_snapshot','parents','runtime')})
    record['receipt_sha256']=e.receipt_digest(record)
    receipt=put(rd/record['attempt_record'],record)
    state={'schema_version':1,'revision':1,'stages':{'qualification':record}}
    put(rd/e.STATE_NAME,state)
    return rd,{'rundir':str(rd),'receipt':receipt},selected,record


def consume(binding,selected,root,scope,*,limits=LIMITS):
    consumed=ri.CustodyInputs();budget=ri.CustodyAccumulator(limits)
    value=ri._operational_json(selected,root,consumed,limits=limits,accumulator=budget)
    stage=ri._executed(binding,[],[{'artifact':selected,'value':value}],root,consumed,
        limits=limits,accumulator=budget,_qualification_scope=scope)
    assert stage['state']=='current_successful_stage'
    return consumed,budget,stage


def sessions(monkeypatch):
    result=[];factory=e._validation_session
    def create(*args,**kwargs):
        session=factory(*args,**kwargs);result.append(session);return session
    monkeypatch.setattr(e,'_validation_session',create)
    return result


@pytest.mark.parametrize('uses',[2,3])
def test_one_scope_shares_stage_but_retains_every_fresh_payload_read(tmp_path,monkeypatch,uses):
    rd,binding,selected,record=fixture(tmp_path);seen=sessions(monkeypatch)
    reads=[];metadata=[];reader=ri._dependency;json_reader=ri._operational_json
    def observe(pin,*args,**kwargs):
        reads.append(pin['path']);return reader(pin,*args,**kwargs)
    def observe_json(pin,*args,**kwargs):
        metadata.append(pin['path']);return json_reader(pin,*args,**kwargs)
    monkeypatch.setattr(ri,'_dependency',observe)
    monkeypatch.setattr(ri,'_operational_json',observe_json)
    with pr._qualification_validation() as scope:
        results=[consume(binding,selected,tmp_path,scope) for _ in range(uses)]
        assert len(seen)==1 and not seen[0].closed and 'qualification' in seen[0].stages
        assert all(row[2]==results[0][2] for row in results)
        for field in ('input_snapshot','output_snapshot'):
            for root,snapshot in record[field].items():
                for leaf in snapshot['files']:
                    path=str(Path(root)/leaf['name'])
                    assert reads.count(path)==uses
        assert metadata.count(selected['path'])==uses
        assert metadata.count(binding['receipt']['path'])==uses
        assert metadata.count(str(rd/e.STATE_NAME))==uses
        assert all(result[1].members==results[0][1].members for result in results)
    assert scope.closed and not scope.sessions and not scope.ledgers
    assert seen[0].closed and not seen[0].hashes and not seen[0].stages


@pytest.mark.parametrize('distinction',['run','stage-receipt','policy'])
def test_distinct_identity_or_policy_has_independent_session(tmp_path,monkeypatch,distinction):
    rd,binding,selected,record=fixture(tmp_path/'one');other=binding;limits=LIMITS
    if distinction=='run':_,other,_,_=fixture(tmp_path/'two')
    if distinction=='stage-receipt':
        state=e.load_execution(rd);second=deepcopy(record)
        second.update(stage='other-qualification',attempt_id='other-attempt',attempt_record='logs/other/record.json')
        receipt=put(rd/second['attempt_record'],second);state['stages'][second['stage']]=second;put(rd/e.STATE_NAME,state)
        other={'rundir':str(rd),'receipt':receipt}
    if distinction=='policy':limits={**LIMITS,'max_files':19999}
    seen=sessions(monkeypatch)
    with pr._qualification_validation() as scope:
        consume(binding,selected,tmp_path,scope)
        # A different run needs its own actual selected output, not first-run evidence.
        output=pin(Path(other['rundir'])/'output/selected.json')
        consume(other,output,tmp_path,scope,limits=limits)
        assert len(seen)==2 and seen[0] is not seen[1]
    assert all(session.closed for session in seen)


@pytest.mark.parametrize('change',['ledger-value','ledger-replace','receipt-replace','input-byte',
    'output-byte','log-byte','empty-directory','ancestor-symlink','mutable-state','runtime','runtime-error'])
def test_reuse_and_final_census_refuse_late_complete_population_change(tmp_path,monkeypatch,change):
    rd,binding,selected,record=fixture(tmp_path);seen=sessions(monkeypatch)
    # Runtime's genuine starting census is retained; only inject changed/failing
    # later observation. No stage validation is replaced by a green fixture.
    context=e.runtime_context;changed=[False]
    if change in {'runtime','runtime-error'}:
        def current():
            value=context()
            if changed[0]:
                if change=='runtime-error':raise OSError('injected runtime census failure')
                return {**value,'packages_sha256':'0'*64}
            return value
        monkeypatch.setattr(e,'runtime_context',current)
    with pytest.raises((ValueError,OSError),match=('^ordinary existing manuscript evidence required$' if change=='ancestor-symlink' else 'custody differs|changed|symlink|census')):
        with pr._qualification_validation() as scope:
            consume(binding,selected,tmp_path,scope)
            assert len(seen)==1 and not seen[0].closed
            if change=='ledger-value':
                value=e.load_execution(rd);value['revision']+=1;put(rd/e.STATE_NAME,value)
            elif change in {'ledger-replace','receipt-replace'}:
                path=rd/e.STATE_NAME if change=='ledger-replace' else Path(binding['receipt']['path'])
                replacement=rd/'replacement';replacement.write_bytes(path.read_bytes());replacement.replace(path)
            elif change=='input-byte':(rd/'input/unselected.dat').write_bytes(b'changed input')
            elif change=='output-byte':(rd/'output/unselected.dat').write_bytes(b'changed output')
            elif change=='log-byte':(rd/'logs/control.log').write_bytes(b'changed log')
            elif change=='empty-directory':(rd/'input/new-empty').mkdir()
            elif change=='ancestor-symlink':
                source=rd/'input';moved=rd/'moved-input';source.rename(moved);source.symlink_to(moved,target_is_directory=True)
            elif change=='mutable-state':seen[0].tracked[0][0]['revision']+=1
            else:changed[0]=True
            consume(binding,selected,tmp_path,scope)
    assert seen and all(session.closed and not session.hashes and not session.stages for session in seen)


def test_closed_and_cross_outward_calls_never_borrow_authority(tmp_path,monkeypatch):
    _,binding,selected,_=fixture(tmp_path);seen=sessions(monkeypatch)
    for _ in range(2):
        with pr._qualification_validation() as scope:consume(binding,selected,tmp_path,scope)
    assert len(seen)==2 and seen[0] is not seen[1] and all(s.closed for s in seen)
    with pytest.raises(ValueError,match='closed or inactive'):
        with pr._qualification_validation(scope):pass
    # Standalone _executed keeps its original owned validator and return schema.
    consumed=ri.CustodyInputs();value=ri._operational_json(selected,tmp_path,consumed,limits=LIMITS)
    result=ri._executed(binding,[],[{'artifact':selected,'value':value}],tmp_path,consumed,limits=LIMITS)
    assert result['state']=='current_successful_stage' and len(seen)==3 and seen[-1].closed


def test_exception_closes_without_leaking_a_scope_to_clean_next_call(tmp_path,monkeypatch):
    _,binding,selected,_=fixture(tmp_path);seen=sessions(monkeypatch)
    with pytest.raises(ValueError,match='later observation failed'):
        with pr._qualification_validation() as scope:
            consume(binding,selected,tmp_path,scope);raise ValueError('later observation failed')
    assert scope.closed and seen[0].closed
    with pr._qualification_validation() as clean:consume(binding,selected,tmp_path,clean)
    assert seen[1] is not seen[0] and seen[1].closed


def test_relative_receipt_join_retains_original_base_owner(tmp_path):
    _,binding,selected,_=fixture(tmp_path)
    binding={**binding,'receipt':{**binding['receipt'],'path':str(Path(binding['receipt']['path']).relative_to(tmp_path))}}
    with pr._qualification_validation() as scope:consume(binding,selected,tmp_path,scope)


def test_original_union_cap_and_conflict_still_refuse(tmp_path):
    _,binding,selected,_=fixture(tmp_path)
    with pytest.raises(ValueError,match='complete operational custody exceeds declared limits; no truncation'):
        with pr._qualification_validation() as scope:
            consume(binding,selected,tmp_path,scope,limits={**LIMITS,'max_files':1})
    # Exact original add path remains, no bulk or accepted union cache.
    budget=ri.CustodyAccumulator(LIMITS);budget.add(selected)
    with pytest.raises(ValueError,match='identity'):
        budget.add({**selected,'sha256':'0'*64})


def test_finish_failure_prevents_qualified_emission_and_next_call_is_fresh(tmp_path,monkeypatch):
    task,c,rt,result,observations,calls,rd=qualification_fixture(tmp_path,monkeypatch)
    real=pr._QualificationScope.finish;seen=[]
    def finish(scope):
        seen.append(scope)
        if len(seen)==1:
            # Actual final census, with a changed unselected original log.
            (rd/'logs/supervisor.log').write_bytes(b'changed after all observations')
        return real(scope)
    monkeypatch.setattr(pr._QualificationScope,'finish',finish)
    out=tmp_path/'refused-qualified.json'
    with pytest.raises(ValueError,match='custody differs'):
        pr.qualify(rt['closure_manifest'],observations,out)
    assert not out.exists() and seen[0].closed
    assert len(calls)==3 # All were explicit inert returns, no native dispatch.


def test_public_verified_result_shares_qualification_only_and_closes_before_return(tmp_path,monkeypatch):
    from test_publication_runtime_ci3 import complete_fixture
    f=complete_fixture(tmp_path,monkeypatch);seen=sessions(monkeypatch);qualifier=f['qualifier']
    result=mb.verified_result(f['binding'],base_dir=tmp_path)
    assert result==f['built']
    qualifying=[session for session in seen if Path(session.rundir)==qualifier]
    assert len(qualifying)==1
    assert all(session.closed and not session.hashes and not session.stages for session in seen)
    assert len(f['calls'])==6
    # A separate public call must redo the real stage traversal, not reopen the
    # prior closed session. CI3's later verification likewise remains separate.
    second=mb.verified_result(f['binding'],base_dir=tmp_path)
    assert second==result
    assert len([s for s in seen if Path(s.rundir)==qualifier])==2


def test_public_verified_result_finish_sees_late_unselected_qualification_log(tmp_path,monkeypatch):
    from test_publication_runtime_ci3 import complete_fixture
    f=complete_fixture(tmp_path,monkeypatch);original=mb._inputs;calls=[0];seen=sessions(monkeypatch)
    def last_inputs(*args,**kwargs):
        result=original(*args,**kwargs);calls[0]+=1
        if calls[0]==2:(f['qualifier']/'logs/supervisor.log').write_bytes(b'late unselected qualification log')
        return result
    monkeypatch.setattr(mb,'_inputs',last_inputs)
    with pytest.raises(ValueError,match='^method execution custody differs: validation final census unavailable: artifact identity changed during validation: .*/ordinary-custody/logs/supervisor[.]log$'):
        mb.verified_result(f['binding'],base_dir=tmp_path)
    assert calls[0]==2 and seen and all(session.closed for session in seen)


def test_missing_and_failed_stage_keep_original_provisional_failure_schema(tmp_path,monkeypatch):
    rd,binding,selected,record=fixture(tmp_path);seen=sessions(monkeypatch)
    record['status']='failed';put(Path(binding['receipt']['path']),record)
    state=e.load_execution(rd);state['stages']['qualification']=record;put(rd/e.STATE_NAME,state)
    binding={**binding,'receipt':pin(Path(binding['receipt']['path']))}
    with pr._qualification_validation() as scope:
        result=ri._executed(binding,[],[],tmp_path,ri.CustodyInputs(),limits=LIMITS,_qualification_scope=scope)
        assert result=={'state':'failed_or_incomplete_retained_stage','status':'failed','stage':'qualification',
            'attempt_id':'declared-control-attempt','runtime_consumption_verified':False}
        assert ri._executed(None,[],[],tmp_path,{},_qualification_scope=scope)=={
            'state':'execution_evidence_missing','runtime_consumption_verified':False}
    assert seen==[] and scope.closed
