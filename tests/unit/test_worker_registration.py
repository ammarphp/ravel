"""Portable mechanical custody controls; no solver/method/native/model calls."""
import ast
from pathlib import Path
import pytest
from ravel.workflow import execution, science


def harness(tmp_path,monkeypatch,records):
    (tmp_path/execution.STATE_NAME).write_text('{}')
    state={'now':0.0,'loads':0,'sleeps':0,'parent':11}
    monkeypatch.setattr(execution.os,'getppid',lambda:state['parent'])
    monkeypatch.setattr(execution.os,'getpid',lambda:22)
    monkeypatch.setattr(execution,'process_identity',lambda pid:'birth-'+str(pid))
    def read(_):
        i=state['loads'];state['loads']+=1
        return {'stages':{'stationarity_trial':records[min(i,len(records)-1)]}}
    monkeypatch.setattr(execution,'load_execution',read)
    import time
    monkeypatch.setattr(time,'monotonic',lambda:state['now'])
    def sleep(n):state['now']+=n;state['sleeps']+=1
    monkeypatch.setattr(time,'sleep',sleep)
    return state


def row(**changes):
    return {'status':'running','supervisor_pid':11,'child_pid':22,'child_identity':'birth-22',**changes}


def test_delayed_publication_generic_stage(tmp_path,monkeypatch):
    s=harness(tmp_path,monkeypatch,[row(child_pid=None,child_identity=None),row()])
    execution.await_worker_registration(tmp_path,'stationarity_trial')
    assert s['loads']==2 and s['sleeps']==1


@pytest.mark.parametrize('changes',[{'status':'failed'},{'supervisor_pid':12},{'child_pid':23},
    {'child_identity':'reused-birth'},{'child_pid':None,'child_identity':'orphan-birth'},
    {'child_pid':22,'child_identity':None}])
def test_foreign_or_cancelled_registration_refuses(tmp_path,monkeypatch,changes):
    s=harness(tmp_path,monkeypatch,[row(**changes)])
    with pytest.raises(ValueError):execution.await_worker_registration(tmp_path,'stationarity_trial')
    assert s['loads']==1 and s['sleeps']==0


def test_parent_reuse_refuses(tmp_path,monkeypatch):
    s=harness(tmp_path,monkeypatch,[row()]);count=[0]
    def identity(pid):
        if pid==11:
            count[0]+=1
            return 'birth-11' if count[0]==1 else 'new-birth-11'
        return 'birth-22'
    monkeypatch.setattr(execution,'process_identity',identity)
    with pytest.raises(ValueError,match='parent changed'):execution.await_worker_registration(tmp_path,'stationarity_trial')
    assert s['loads']==0


def test_never_published_is_bounded(tmp_path,monkeypatch):
    s=harness(tmp_path,monkeypatch,[row(child_pid=None,child_identity=None)])
    with pytest.raises(ValueError,match='timed out'):execution.await_worker_registration(tmp_path,'stationarity_trial',timeout=.05)
    assert s['now']==.05 and s['sleeps']==2


@pytest.mark.parametrize('timeout',[0,-1,True,6,float('inf'),float('nan')])
def test_invalid_wait_budget(tmp_path,timeout):
    with pytest.raises(ValueError,match='timeout'):execution.await_worker_registration(tmp_path,'stationarity_trial',timeout=timeout)


def test_symlink_ledger_refuses(tmp_path,monkeypatch):
    s=harness(tmp_path,monkeypatch,[row()]);p=tmp_path/execution.STATE_NAME
    p.unlink();(tmp_path/'real').write_text('{}');p.symlink_to('real')
    with pytest.raises(ValueError,match='without symlinks'):execution.await_worker_registration(tmp_path,'stationarity_trial')
    assert s['loads']==0


def test_missing_identity_refuses(tmp_path,monkeypatch):
    s=harness(tmp_path,monkeypatch,[row()]);monkeypatch.setattr(execution,'process_identity',lambda pid:None)
    with pytest.raises(ValueError,match='identity unavailable'):execution.await_worker_registration(tmp_path,'stationarity_trial')
    assert s['loads']==0


def test_stage_name_cannot_change_registration_selection(tmp_path,monkeypatch):
    s=harness(tmp_path,monkeypatch,[row()])
    with pytest.raises(ValueError,match='valid stage'):execution.await_worker_registration(tmp_path,'../science')
    assert s['loads']==0


def test_existing_science_wait_delegates(monkeypatch):
    calls=[];monkeypatch.setattr(execution,'await_worker_registration',lambda *a,**k:calls.append((a,k)))
    science._await_worker_registration(Path('/unused'),timeout=1)
    assert calls==[((Path('/unused'),'science'),{'timeout':1})]


