"""Narrow current full-profile returned/result ending controls, no native calls."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
import test_contur_full_modes as f
import test_contur_yoda as old
from ravel.physics import contur_import as c,contur_yoda as m, reinterpret_db


def full_native(tmp_path,monkeypatch):
    task,d=old.fixture(tmp_path);d['schema_version']=2;d['settings']=f.full_settings();old.write(Path(task['input']),d)
    out=tmp_path/'out';monkeypatch.setattr(m,'_approved',lambda *a:(tmp_path,{'max_seconds':100}))
    def supplied(command,output,document):
        work=out/'contur-work';native=work/'native-output';native.mkdir()
        f.db(native/'results.db',work/'input/supplied.yoda')
        old.write(work/'native-observation.json',{'effective_settings':{'effective':document['settings']},'confidence_witness':m.confidence_witness(f.full_point(),modes=c.FULL_MODES)})
        return {'returncode':0,'scope':'supplied inert result, no native process'}
    monkeypatch.setattr(reinterpret_db,'execute_native',supplied)
    return task,out

@pytest.mark.parametrize('target',['contur-results.json','native-columns.csv'])
def test_actual_full_native_ending_input_read_cannot_stale_delivery(tmp_path,monkeypatch,target):
    task,out=full_native(tmp_path,monkeypatch);original=m.inputs;changed=[]
    def ending(task,base):
        files=original(task,base);p=out/target
        if p.exists() and not changed:p.write_bytes(p.read_bytes()+b'\n');changed.append(True)
        return files
    monkeypatch.setattr(m,'inputs',ending)
    with pytest.raises(ValueError,match='delivery bytes'):m.run(task,tmp_path,out)
    assert changed==[True]

@pytest.mark.parametrize('field',['mode','physics'])
def test_actual_full_native_detached_writer_preserves_return(tmp_path,monkeypatch,field):
    task,out=full_native(tmp_path,monkeypatch);original=c.atomic_json;mutations=[]
    def writer(path,value):
        original(path,value)
        if Path(path)==out/'contur-results.json':
            if field=='mode':value['points'][0]['runs'][0]['raw']['stat_type']='UNKNOWN'
            else:value['physics_validated']=True
            mutations.append(True)
    monkeypatch.setattr(c,'atomic_json',writer)
    result=m.run(task,tmp_path,out)
    assert mutations==[True] and result==json.loads((out/'contur-results.json').read_text())
    assert result['physics_validated'] is False and result['points'][0]['runs'][0]['raw']['stat_type']=='DATABG'

def test_external_live_result_change_refuses_original_commitment(tmp_path,monkeypatch):
    path=tmp_path/'inert.sqlite';f.db(path,tmp_path/'y.yoda');points=c.decode_database(path,modes=c.FULL_MODES)
    out=tmp_path/'out';out.mkdir();result={'points':points,'physics_validated':False};original=c.atomic_json
    def writer(path,value):
        original(path,value);result['physics_validated']=True
    monkeypatch.setattr(c,'atomic_json',writer)
    with pytest.raises(ValueError,match='original commitment'):c.full_mode_delivery(out,'result.json',result,points)

def test_original_commitment_is_not_recomputed_after_change(tmp_path):
    path=tmp_path/'inert.sqlite';f.db(path,tmp_path/'y.yoda');points=c.decode_database(path,modes=c.FULL_MODES)
    out=tmp_path/'out';out.mkdir();result={'points':points,'physics_validated':False}
    initial=c.full_mode_delivery(out,'result.json',result,points)
    (out/'native-columns.csv').write_bytes(b'changed')
    with pytest.raises(ValueError,match='delivery bytes'):c.verify_full_mode_delivery(out,'result.json',result,initial)
    assert initial['native-columns.csv']!=f.p(out/'native-columns.csv')['sha256']
