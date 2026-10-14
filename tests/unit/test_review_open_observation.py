"""One locked capture, independent ending guards and fresh later authority."""
import hashlib
import json
import os
from pathlib import Path
import pytest
from ravel.workflow import physics_review as review, execution
from test_physics_review import run, make_attempt, check_packet, opened


def payload_attempt(run):
    root,_=run;p=root/'inputs/payload.bin';p.write_bytes(b'original nonempty payload')
    record=make_attempt(root,extra_inputs=[str(p)]);check_packet(root,record)
    return root,record,p


def capture(root,record):
    return review.open_cycle(root,effective_settings=['inputs/settings.cfg'],stage_receipts=[record['attempt_record']],check_results='inputs/checks.json')


def test_one_capture_reads_payload_once_plus_copy(run,monkeypatch):
    root,record,p=payload_attempt(run);old=Path.open;reads=[]
    def counted(path,*a,**kw):
        mode=a[0] if a else kw.get('mode','r')
        if path==p and 'r' in mode:reads.append(mode)
        return old(path,*a,**kw)
    monkeypatch.setattr(Path,'open',counted)
    event=capture(root,record)
    assert reads==['rb','rb']
    pin=next(v for v in event['snapshots'] if v['path']=='inputs/payload.bin')
    assert pin['sha256']==hashlib.sha256(p.read_bytes()).hexdigest()
    assert (root/pin['snapshot']).read_bytes()==p.read_bytes()


@pytest.mark.parametrize('kind',['content','restored_mtime','leaf_symlink','ancestor_symlink','snapshot_blob','ledger','journal_membership','absent_dangling_journal'])
def test_capture_ending_mutations_refuse_before_cycle_append(run,monkeypatch,kind):
    root,record,p=payload_attempt(run);old=review._capture_cycle
    def mutate(*a,**kw):
        result=old(*a,**kw);reg,events,payload=result
        if kind in ('content','restored_mtime'):
            stat=p.stat();p.write_bytes(b'changed payload same length')
            if kind=='restored_mtime':os.utime(p,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        elif kind=='leaf_symlink':
            q=p.with_name('outside.bin');p.rename(q);p.symlink_to(q)
        elif kind=='ancestor_symlink':
            actual=root/'inputs';moved=root/'renamed-inputs';actual.rename(moved);actual.symlink_to(moved,target_is_directory=True)
        elif kind=='snapshot_blob':
            pin=next(v for v in payload['snapshots'] if v['path']=='inputs/payload.bin');(root/pin['snapshot']).write_bytes(b'changed blob')
        elif kind=='ledger':
            q=root/'execution_state.json';data=json.loads(q.read_text());data['changed_control']=True;q.write_text(json.dumps(data))
        elif kind=='journal_membership':
            q=root/review.DIRECTORY/'events';q.mkdir(exist_ok=True);(q/'unexpected.json').write_text('{}')
        else:
            q=root/review.DIRECTORY/'events';assert not q.exists();q.symlink_to(root/'missing-journal',target_is_directory=True)
        return result
    monkeypatch.setattr(review,'_capture_cycle',mutate)
    with pytest.raises(ValueError):capture(root,record)
    assert json.loads((root/review.HEAD).read_text())['sequence']==0


def test_later_public_review_has_fresh_source_custody(run):
    root,record,p=payload_attempt(run);capture(root,record);p.write_bytes(b'changed after first authority')
    with pytest.raises(ValueError):
        review.submit_review(root,role='skeptical_verifier',actor_id='skeptic',verdict='accept',summary='synthetic boundary',claim_scope='reproduction')


def test_snapshot_copy_source_mutation_refuses(run,monkeypatch):
    root,record,p=payload_attempt(run);old=review.shutil.copyfileobj
    def copied(src,dst,*a,**kw):
        result=old(src,dst,*a,**kw)
        if Path(src.name)==p:p.write_bytes(b'changed immediately after copy')
        return result
    monkeypatch.setattr(review.shutil,'copyfileobj',copied)
    with pytest.raises(ValueError):capture(root,record)
    assert json.loads((root/review.HEAD).read_text())['sequence']==0
