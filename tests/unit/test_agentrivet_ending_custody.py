from pathlib import Path
import pytest
from ravel.physics import agentrivet_candidate as bridge
import test_agentrivet_candidate as supplied

def test_ending_ancestor_symlink_refused(tmp_path,monkeypatch):
 parent=tmp_path/'input';parent.mkdir();p=parent/'code.cc';p.write_bytes(supplied.CODE);pin=supplied.pin(p)
 original=Path.open;relocated=tmp_path/'original'
 class Stream:
  def __init__(self,stream):self.stream=stream
  def __enter__(self):self.stream.__enter__();return self
  def __exit__(self,*a):return self.stream.__exit__(*a)
  def fileno(self):return self.stream.fileno()
  def read(self,*a):
   raw=self.stream.read(*a);parent.rename(relocated);parent.symlink_to(relocated,target_is_directory=True);return raw
 def open_(path,*a,**kw):
  s=original(path,*a,**kw)
  return Stream(s) if path==p else s
 monkeypatch.setattr(Path,'open',open_)
 with pytest.raises(ValueError):bridge._snapshot(pin,tmp_path)
