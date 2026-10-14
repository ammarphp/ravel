"""Narrow real lock/API serialization controls on synthetic closed receipts."""
from pathlib import Path
import threading
import pytest
from retained_status_fixture import closed
from ravel.workflow import execution,physics_review as review,retained_science_review as retained
from ravel.workflow.state_io import file_lock
from independent_retained_v1_companion import hold_status_as_new_evidence

@pytest.fixture(autouse=True)
def inert_platform(monkeypatch):
    monkeypatch.setattr(execution.platform,'platform',lambda:'synthetic-source-control-platform')

def test_real_hold_writer_cannot_enter_observe_to_write_boundary(closed,monkeypatch):
    original=retained.observe;busy=threading.Event();written=threading.Event();errors=[];seen=[];threads=[]
    def writer():
        try:
            with pytest.raises(ValueError,match='another process owns'):
                with file_lock(closed.root/review.DIRECTORY/'write.lock',blocking=False):pass
            busy.set()
            assert written.wait(10),'packet did not finish its bounded write'
            event,raw=hold_status_as_new_evidence(closed);seen.append((event,raw))
        except BaseException as exc:errors.append(exc);busy.set()
    def start_queued_writer(root,*a,**k):
        proof=original(root,*a,**k)
        thread=threading.Thread(target=writer,daemon=True);threads.append(thread);thread.start()
        assert busy.wait(5),'no lock observation'
        assert not errors,errors
        assert review._view(*review._read(closed.root))['state']=='accepted'
        return proof
    with monkeypatch.context() as patch:
        patch.setattr(retained,'observe',start_queued_writer)
        try:result=retained.packet(closed.root,write=True)
        finally:written.set()
    for thread in threads:thread.join(15);assert not thread.is_alive()
    assert not errors,errors
    assert result['review_state']=='accepted' and result['lifecycle_verdict']=='PASS'
    assert len(seen)==1 and review._view(*review._read(closed.root))['state']=='scientific_hold'
    assert (closed.root/'current_state.json').read_bytes()==seen[0][1]
    observed=retained.packet(closed.root)
    assert observed['review_state']=='scientific_hold' and observed['lifecycle_verdict']=='PENDING'
    with pytest.raises(ValueError,match='overwrite evidence'):
        retained.packet(closed.root,write=True)
    assert (closed.root/'current_state.json').read_bytes()==seen[0][1]

def test_prior_real_hold_commitment_refuses_before_write(closed):
    event,raw=hold_status_as_new_evidence(closed)
    with pytest.raises(ValueError,match='overwrite evidence'):retained.packet(closed.root,write=True)
    assert (closed.root/'current_state.json').read_bytes()==raw
    assert retained.packet(closed.root)['scientific_hold_sha256']==event['sha256']

def test_late_original_output_change_refuses_before_any_status_write(closed,monkeypatch):
    target=closed.root/'current_state.json';before=target.read_bytes();original=retained.observe
    def changed(*a,**k):
        proof=original(*a,**k)
        (closed.root/'outputs/attempt-1/result.json').write_text('changed original returned bytes')
        return proof
    monkeypatch.setattr(retained,'observe',changed)
    with pytest.raises(ValueError,match='changed before status write'):retained.packet(closed.root,write=True)
    assert target.read_bytes()==before

def test_lock_alias_refuses_before_status_write(closed,tmp_path):
    lock=closed.root/review.DIRECTORY/'write.lock';lock.unlink();foreign=tmp_path/'foreign-lock';foreign.write_text('preserve')
    lock.symlink_to(foreign);before=(closed.root/'current_state.json').read_bytes()
    with pytest.raises(ValueError,match='ordinary existing review lock'):retained.packet(closed.root,write=True)
    assert foreign.read_text()=='preserve' and (closed.root/'current_state.json').read_bytes()==before
