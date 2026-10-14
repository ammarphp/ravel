"""Returned native/controller buffers are engineering fixture bytes only."""
from pathlib import Path
import io
import pytest
from cosmic_evolution_fixture import fixture,LIMITS,write
from ravel.physics import cosmic_evolution as op,cosmic_evolution_worker as worker,cosmic_evolution_core as core

class InertQuery:
    def __init__(self,argv,cwd,env,max_bytes):
        self.stdout=io.BytesIO();write(Path(cwd)/'stdout.log',b'{"jobs":[]}\n');write(Path(cwd)/'stderr.log',b'')
    def poll(self):return 0
    def close(self,stop=False):self.stdout.close();return {'returncode':0,'inert':True}

@pytest.mark.parametrize('attack',['none','bytes','ABA'])
def test_real_controller_consumption_remains_bound_at_ending(tmp_path,monkeypatch,attack):
    path,d,_,_=fixture(tmp_path/'input',operation='site-local-execution')
    cap=op._capture({'input':str(path)},path.parent)[2]
    monkeypatch.setattr(worker,'LocalClient',InertQuery)
    c=worker.Controller(d['runtime'],tmp_path/'controller',cap,LIMITS,float('inf'))
    assert c.invoke(['synthetic-source-command'])==b'{"jobs":[]}\n'
    p=c.root/'0/stdout.log';raw=p.read_bytes()
    if attack!='none':
        p.write_bytes(raw+b' ')
        if attack=='ABA':p.write_bytes(raw)
        with pytest.raises(ValueError):c.returned.finish()
    else:
        assert c.calls[0]['output_pins'][0]['sha256']==c.returned.files[str(p)]['sha256']
        c.returned.finish();c.publications.finish()

@pytest.mark.parametrize('attack',['bytes','ABA'])
def test_source_rank_return_not_rebaselined_before_phase_end(tmp_path,attack):
    p=tmp_path/'rank.json';write(p,{'rank':0,'nonce':'exact'})
    observed=core.Capture(tmp_path,{'max_input_files':2,'max_input_bytes':1024})
    assert worker._document(p,capture=observed)=={'rank':0,'nonce':'exact'}
    raw=p.read_bytes();p.write_bytes(raw+b' ')
    if attack=='ABA':p.write_bytes(raw)
    with pytest.raises(ValueError):observed.finish()
