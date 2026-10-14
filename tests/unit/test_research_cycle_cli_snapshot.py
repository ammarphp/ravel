import json, os
from pathlib import Path
import pytest
from ravel.workflow import research_cycle as cycle, research_followup as followup
def test_growth_before_hash_refuses_before_any_oversized_read(tmp_path,monkeypatch):
    path=tmp_path/'request.json';path.write_bytes(b'{}')
    original_open=os.fdopen;reads=[];consumed=[0]
    class GrowingSnapshot:
        def __init__(self,stream):self.stream=stream;self.remaining=followup.MAX_BYTES+2
        def __enter__(self):self.stream.__enter__();return self
        def __exit__(self,*args):return self.stream.__exit__(*args)
        def fileno(self):return self.stream.fileno()
        def read(self,n):
            take=min(n,self.remaining);reads.append({'requested':n,'virtual_return':take})
            if consumed[0]+take>followup.MAX_BYTES+1:
                raise AssertionError('CLI unbounded hash consumed beyond2MiB+1 after a tiny initial stat')
            consumed[0]+=take;self.remaining-=take;return b' '*take
    def open_file(descriptor,*args,**kwargs):
        return GrowingSnapshot(original_open(descriptor,*args,**kwargs))
    monkeypatch.setattr(os,'fdopen',open_file)
    try:
        with pytest.raises(ValueError):cycle._cli_document(path)
    finally:
        (tmp_path/'growth-witness.json').write_text(json.dumps({'physical_fixture_bytes':2,'virtual_descriptor_bytes_after_precheck':followup.MAX_BYTES+2,'consumed_before_refusal':consumed[0],'read_attempts':reads,'large_file_allocated':False,'native_provider_calls':0},indent=2)+'\n')
    assert consumed[0] == followup.MAX_BYTES + 1
    assert reads == [{'requested':followup.MAX_BYTES+1,'virtual_return':followup.MAX_BYTES+1}]


def test_snapshot_parses_consumed_bytes_without_prehash_or_path_text(tmp_path,monkeypatch):
    p=tmp_path/'request.json';p.write_bytes(b'{"value":3}')
    def forbidden(*a,**k):raise AssertionError('unbounded prehash or second text read')
    monkeypatch.setattr(cycle,'_pin',forbidden);monkeypatch.setattr(Path,'read_text',forbidden)
    assert cycle._cli_document(p)=={'value':3}

def test_ending_parent_same_inode_alias_refuses(tmp_path,monkeypatch):
    original=tmp_path/'parent';original.mkdir();p=original/'request.json';p.write_bytes(b'{}')
    moved=tmp_path/'moved';open0=os.fdopen
    class Changed:
        def __init__(self,s):self.s=s
        def __enter__(self):self.s.__enter__();return self
        def __exit__(self,*args):return self.s.__exit__(*args)
        def fileno(self):return self.s.fileno()
        def read(self,n):
            raw=self.s.read(n);original.rename(moved);original.symlink_to(moved,target_is_directory=True);return raw
    def opening(descriptor,*args,**kwargs):
        return Changed(open0(descriptor,*args,**kwargs))
    monkeypatch.setattr(os,'fdopen',opening)
    with pytest.raises(ValueError,match='ordinary research paths'):cycle._cli_document(p)


def test_ending_ordinary_ancestor_replacement_with_same_hardlinked_leaf_refuses(tmp_path,monkeypatch):
    parent=tmp_path/'parent';parent.mkdir();other=tmp_path/'replacement';other.mkdir()
    path=parent/'request.json';path.write_bytes(b'{}');os.link(path,other/'request.json')
    moved=tmp_path/'original-parent';original_open=os.fdopen
    identity=lambda p:tuple(getattr(p.stat(),k) for k in ('st_dev','st_ino','st_mode','st_size','st_mtime_ns','st_ctime_ns'))
    initial_leaf=identity(path);initial_parent=(parent.stat().st_dev,parent.stat().st_ino)
    observed={}
    class Swap:
        def __init__(self,stream):self.stream=stream
        def __enter__(self):self.stream.__enter__();return self
        def __exit__(self,*args):return self.stream.__exit__(*args)
        def fileno(self):return self.stream.fileno()
        def read(self,n):
            raw=self.stream.read(n);parent.rename(moved);other.rename(parent);return raw
    def opening(descriptor,*args,**kwargs):
        return Swap(original_open(descriptor,*args,**kwargs))
    monkeypatch.setattr(os,'fdopen',opening)
    try:
        with pytest.raises(ValueError):observed['returned']=cycle._cli_document(path)
    finally:
        observed.update({'initial_leaf':initial_leaf,'ending_leaf':identity(path),'initial_parent':initial_parent,'ending_parent':(parent.stat().st_dev,parent.stat().st_ino),'ending_parents_ordinary':not parent.is_symlink(),'native_provider_calls':0})
        (tmp_path/'ancestor-witness.json').write_text(json.dumps(observed,indent=2)+'\n')
