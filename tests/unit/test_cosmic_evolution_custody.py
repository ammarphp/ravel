from copy import deepcopy
from pathlib import Path
import hashlib,json,os,struct
import pytest
from cosmic_evolution_fixture import fixture,pin,write,save,policy,LIMITS,FIELDS,ZS
from ravel.physics import cosmic_evolution as op, cosmic_evolution_core as core
from ravel.workflow import science,state_io


@pytest.mark.parametrize('attack',['missing','extra','duplicate','no-newline','bad-ABI','bad-count','bad-size','hardlink','wrong-cwd'])
def test_complete_actual_ic_population_refuses(tmp_path,attack):
    path,d,w,_=fixture(tmp_path/'input');c=d['cases'][0]['ic'];base=path.parent
    if attack=='missing':c['chunks']=[]
    elif attack=='extra':c['chunks'].append(c['chunks'][0])
    elif attack=='duplicate':c['file_list']=write(base/'retained-ic/FileList','chunk.bin\nchunk.bin\n');c['chunks']*=2
    elif attack=='no-newline':c['file_list']=write(base/'retained-ic/FileList','chunk.bin')
    elif attack=='bad-ABI':w['real_bytes']=4
    elif attack=='bad-count':c['shape']=[3,3,3]
    elif attack=='bad-size':c['chunks'][0]=write(base/'retained-ic/chunk.bin',struct.pack('<qii',8,3,4)+bytes(8*7*8)+b'x')
    elif attack=='hardlink':
        os.link(c['chunks'][0]['path'],base/'retained-ic/alias.bin');c['chunks'].append(pin(base/'retained-ic/alias.bin'));c['file_list']=write(base/'retained-ic/FileList','chunk.bin\nalias.bin\n')
    elif attack=='wrong-cwd':c['reader_base']=str(base)
    with pytest.raises((ValueError,FileNotFoundError)):core.binary_ic(core.Capture(base,LIMITS),c,w)

def test_signed_transfer_and_native_card_empty_order(tmp_path):
    path,d,w,_=fixture(tmp_path/'input');_,_,cap,obs,_,_=op._capture({'input':str(path)},path.parent)
    assert obs[0]['transfer']['rows'][0]==[.01,-1.,0.]
    assert {'key':'amr.probin_file','value':''} in obs[0]['original_nyx_card_rows']
    rows=core.card(b'np=2\nnp=2\n');assert len(rows)==2 and op._effective(rows)=={'np':'2'}
    with pytest.raises(ValueError):op._effective(core.card(b'np=2\nnp=3\n'))
    cap.finish()

@pytest.mark.parametrize('key',['np','z_in','amr.n_cell','nyx.plot_z_values','amr.derive_plot_vars','nyx.analysis_z_values','amr.checkpoint_files_output'])
def test_full_card_denominator_refuses_changed_physics(tmp_path,key):
    path,d,_,_=fixture(tmp_path/'input');c=d['cases'][0];which='ic_card' if key in ('np','z_in') else 'nyx_card';p=Path(c[which]['path']);text=p.read_text()
    lines=[line for line in text.splitlines() if not line.startswith(key+'=')];lines.append(key+'=0');c[which]=write(p,'\n'.join(lines)+'\n');save(path,d)
    with pytest.raises(ValueError):op.inputs({'input':str(path)},path.parent)

@pytest.mark.parametrize('attack',['bytes','ABA','tree-tail','resource','config-nonfinite','input-symlink'])
def test_authenticated_consumption_and_ending_refuse(tmp_path,attack):
    path,d,_,_=fixture(tmp_path/'input');base=path.parent
    if attack=='config-nonfinite':path.write_text(path.read_text().replace('"max_seconds": 60','"max_seconds": NaN'));expected=lambda:op._capture({'input':str(path)},base)
    elif attack=='resource':d['resources']['max_input_files']=1;save(path,d);expected=lambda:op._capture({'input':str(path)},base)
    elif attack=='input-symlink':p=Path(d['cases'][0]['ic_card']['path']);q=p.with_suffix('.alias');q.symlink_to(p);d['cases'][0]['ic_card']={**d['cases'][0]['ic_card'],'path':str(q)};save(path,d);expected=lambda:op._capture({'input':str(path)},base)
    else:
        cap=op._capture({'input':str(path)},base)[2]
        p=Path(d['cases'][0]['transfer']['file']['path']);raw=p.read_bytes()
        if attack=='bytes':p.write_bytes(raw+b'x')
        elif attack=='ABA':p.write_bytes(raw+b'x');p.write_bytes(raw)
        else:write(base/'source/new-tail.cpp','new unbound source')
        expected=cap.finish
    with pytest.raises(ValueError):expected()

@pytest.mark.parametrize('kind',['request','result','plan','ack','ic-products','closure'])
def test_publication_never_rebaselines_changed_new_json(tmp_path,monkeypatch,kind):
    original=state_io.atomic_json
    def changed(p,v):original(p,v);original(p,{'substituted':True,'physics_verified':True})
    monkeypatch.setattr(state_io,'atomic_json',changed)
    with pytest.raises(ValueError):core.Publications(LIMITS).json(tmp_path/(kind+'.json'),{'limits':1,'physics_verified':False})

@pytest.mark.parametrize('attack',['bytes','ABA'])
def test_publication_ending_intended_commitment(tmp_path,attack):
    pub=core.Publications(LIMITS);p=tmp_path/'result.json';pub.json(p,{'science':False});raw=p.read_bytes();p.write_bytes(raw+b' ')
    if attack=='ABA':p.write_bytes(raw)
    with pytest.raises(ValueError):pub.finish()

def test_strict_science_and_source_json_remain_strict():
    for raw in (b'{"x":1,"x":2}',b'{"x":Infinity}',b'{"x":1e999}'):
        with pytest.raises(ValueError):core.loads(raw)

def test_no_actual_private_writer_or_matching_ic_can_be_admitted(tmp_path):
    path,d,_,_=fixture(tmp_path/'input',operation='site-local-execution',writer=False);save(path,d)
    with pytest.raises(ValueError,match='prerequisites unresolved'):op.inputs({'input':str(path)},path.parent)

def test_publication_keeps_consumed_identity_not_a_later_rebaseline(tmp_path,monkeypatch):
    original=core.Capture.finish;target=tmp_path/'result.json';fired=[]
    def late(c):
        original(c)
        if str(target) in c.files and not fired:
            fired.append(True);raw=target.read_bytes();target.write_bytes(raw+b' ');target.write_bytes(raw)
    monkeypatch.setattr(core.Capture,'finish',late)
    pub=core.Publications(LIMITS);pub.json(target,{'physics_verified':False})
    with pytest.raises(ValueError):pub.finish()
