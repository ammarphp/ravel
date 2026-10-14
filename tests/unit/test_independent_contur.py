"""Focused independent Contur full-mode result correspondence; no inference."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
import test_contur_full_modes as f
from ravel.physics import contur_import as c

def witness(tmp_path,name,value):
    (tmp_path/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')

@pytest.mark.parametrize('field',['mode','physics'])
def test_returned_cached_result_matches_intended_original_serialization(tmp_path,monkeypatch,field):
    task,_=f.source_input(tmp_path,'single_results.db');out=tmp_path/'result'
    original=c.atomic_json
    def write_then_change(path,value):
        original(path,value)
        if Path(path)==out/'cached-contur-results.json':
            if field=='mode':value['points'][0]['runs'][0]['raw']['stat_type']='UNKNOWN'
            else:value['physics_validated']=True
    monkeypatch.setattr(c,'atomic_json',write_then_change)
    try:
        result=c.run(task,tmp_path,out)
    except ValueError:
        return
    persisted=json.loads((out/'cached-contur-results.json').read_text())
    witness(tmp_path,'returned-vs-intended.json',{'field':field,
        'returned_status':result['status'],'returned_mode':result['points'][0]['runs'][0]['raw']['stat_type'],
        'durable_mode':persisted['points'][0]['runs'][0]['raw']['stat_type'],
        'returned_physics_validated':result['physics_validated'],
        'durable_physics_validated':persisted['physics_validated'],
        'returned_equals_durable':result==persisted,'native_calls':0})
    assert result==persisted, 'Live returned result changed after intended serialization without refusal'

@pytest.mark.parametrize('target',['cached-contur-results.json','native-columns.csv'])
def test_generated_outputs_still_bound_after_ending_input_read(tmp_path,monkeypatch,target):
    task,_=f.source_input(tmp_path,'single_results.db');out=tmp_path/'result'
    original=c.inputs;changed=[]
    def ending_read(spec,base):
        files=original(spec,base)
        q=out/target
        if q.exists() and not changed:
            before=f.p(q);q.write_bytes(q.read_bytes()+b'\n');changed.append((before,f.p(q)))
        return files
    monkeypatch.setattr(c,'inputs',ending_read)
    try:
        result=c.run(task,tmp_path,out)
    except ValueError:
        return
    witness(tmp_path,'ending-output-correspondence.json',{'target':target,
        'returned_status':result['status'],'before':changed[0][0],'ending':changed[0][1],
        'native_calls':0,'source_inputs_unchanged':True})
    assert not changed or result['status']!='passed', 'Generated output changed in actual final input read but full-mode run passed'

def test_full_delivery_positive_preserves_literal_record_and_complete_csv(tmp_path):
    db=tmp_path/'db.sqlite';f.db(db,tmp_path/'source.yoda')
    points=c.decode_database(db,modes=c.FULL_MODES)
    out=tmp_path/'result';out.mkdir()
    result={'points':points,'mode_population':list(c.FULL_MODES),'status':'passed','physics_validated':False,'fresh_inference':False}
    original=deepcopy(result)
    pins=c.full_mode_delivery(out,'cached-contur-results.json',result,points)
    assert result==original==json.loads((out/'cached-contur-results.json').read_text())
    assert all(f.p(out/name)['sha256']==sha for name,sha in pins.items())
    assert all('CL'+mode in (out/'native-columns.csv').read_text().splitlines()[0] for mode in c.FULL_MODES)
