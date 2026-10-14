"""Transferred exact reviewed descriptor/FIFO controls; no native jobs or signals."""
from pathlib import Path
import io,json,os,stat
import pytest
from ravel.workflow import stage_supervisor as s

def test_regular_exact_bytes_and_short_descriptor_reads(tmp_path,monkeypatch):
    p=tmp_path/'record.json';raw=b'{"unknown":null,"status":"running"}\n';p.write_bytes(raw)
    opened=[];real_open=os.open;real_read=os.read;reads=[]
    def admission(path,flags,*a,**k):
        assert flags & os.O_NOFOLLOW and flags & os.O_NONBLOCK
        fd=real_open(path,flags,*a,**k);opened.append(fd);return fd
    def short(fd,n):reads.append(n);return real_read(fd,min(n,2))
    monkeypatch.setattr(os,'open',admission);monkeypatch.setattr(os,'read',short)
    assert s._interrupted_record_bytes(p)==raw and len(reads)>2
    with pytest.raises(OSError):os.fstat(opened[0])


@pytest.mark.parametrize('change',['symlink','directory'])
def test_replacement_at_descriptor_open_refuses(tmp_path,monkeypatch,change):
    p=tmp_path/'record.json';p.write_bytes(b'original\n');other=tmp_path/'other.json';other.write_bytes(b'original\n')
    real=os.open;seen=[]
    def replacement(path,flags,*a,**k):
        if Path(path)==p:
            seen.append(flags);p.unlink()
            if change=='symlink':p.symlink_to(other)
            else:p.mkdir()
        return real(path,flags,*a,**k)
    monkeypatch.setattr(os,'open',replacement)
    with pytest.raises((ValueError,OSError)):s._interrupted_record_bytes(p)
    assert seen and seen[0]&os.O_NOFOLLOW and seen[0]&os.O_NONBLOCK


@pytest.mark.parametrize('change',['append','same_bytes_new_leaf'])
def test_mutation_during_descriptor_read_refuses_and_closes(tmp_path,monkeypatch,change):
    p=tmp_path/'record.json';p.write_bytes(b'original\n');real=os.read;fds=[]
    def mutate(fd,n):
        raw=real(fd,n)
        if not fds:
            fds.append(fd)
            if change=='append':
                with p.open('ab') as stream:stream.write(b' ')
            else:p.unlink();p.write_bytes(raw)
        return raw
    monkeypatch.setattr(os,'read',mutate)
    with pytest.raises(ValueError,match='changed'):s._interrupted_record_bytes(p)
    with pytest.raises(OSError):os.fstat(fds[0])


def test_bounds_refuse_before_open(tmp_path,monkeypatch):
    p=tmp_path/'record.json';p.write_bytes(b'123')
    monkeypatch.setattr(s,'INTERRUPTED_RECORD_MAX_BYTES',2)
    monkeypatch.setattr(os,'open',lambda *a,**k:pytest.fail('oversized metadata reached descriptor open'))
    with pytest.raises(ValueError,match='bounded regular'):s._interrupted_record_bytes(p)


def test_swapped_fifo_cannot_reach_a_blocking_metadata_open(tmp_path,monkeypatch):
    """Abort exactly before a blocking FIFO open; never block the test itself."""
    p=tmp_path/'record.json';p.write_bytes(b'{"status":"running"}\n')
    real_io_open=io.open;real_os_open=os.open;attempts=[];activated=[]
    def selected(file):return isinstance(file,(str,Path)) and Path(file)==p
    def swap():
        if not activated:
            activated.append(True);p.unlink();os.mkfifo(p)
    def descriptor(file,flags,*a,**k):
        if selected(file):swap()
        if selected(file) and not flags & os.O_NONBLOCK:
            attempts.append({'operation':'os.open','flags':flags,'file_type':'FIFO'})
            raise BlockingIOError('guard aborted a blocking descriptor open')
        return real_os_open(file,flags,*a,**k)
    def no_blocking_fifo(file,*a,**k):
        if selected(file):swap()
        if selected(file) and stat.S_ISFIFO(p.lstat().st_mode):
            attempts.append({'mode':a[0] if a else k.get('mode'),'file_type':'FIFO'})
            raise BlockingIOError('guard aborted the otherwise blocking FIFO open')
        return real_io_open(file,*a,**k)
    monkeypatch.setattr(os,'open',descriptor);monkeypatch.setattr(io,'open',no_blocking_fifo)
    with pytest.raises((ValueError,OSError)):s._interrupted_record_bytes(p)
    # A correct bounded descriptor reader may refuse without attempting a
    # blocking stream open. The original implementation reaches that unsafe seam.
    assert activated, 'replacement interleaving did not execute'
    assert not attempts, 'regular metadata replacement reached blocking FIFO open: '+json.dumps(attempts)


