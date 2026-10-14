"""Portable intended-byte preparation controls, with inert external boundaries."""
import hashlib,json
from pathlib import Path
import pytest
from test_research_protocol import make,no_process
from ravel.workflow import research_cycle as cycle,research_protocol as proto,research_presentation as material,state_io

@pytest.mark.parametrize('target',['host_request','host_inventory','host_commitment','meta_spec','meta_manifest','legacy_subject','legacy_manifest','legacy_basis','cli_context'])
def test_all_adjacent_preparation_emissions_refuse_first_rebase(tmp_path,monkeypatch,target):
    root,_=make(tmp_path,monkeypatch);out=tmp_path/'prepared';changed=[];old=cycle._pin
    names={'host_request':'request.json','host_inventory':'inventory.json','host_commitment':'inventory-commitment.json',
        'meta_spec':'graph-spec.json','meta_manifest':'context/manifest.json',
        'legacy_subject':'context/artifacts/subject.json','legacy_manifest':'context/manifest.json','legacy_basis':'context/artifacts/basis0.txt','cli_context':'context.json'}
    expected=out/names[target]
    def alter(path):
        if Path(path)==expected and not changed:
            expected.write_bytes(expected.read_bytes()+b'\nFOREIGN GENERATED CONTENT\n');changed.append(True)
        return old(path)
    monkeypatch.setattr(cycle,'_pin',alter)
    with pytest.raises(ValueError):
        if target.startswith('host_'):
            proto.prepare_host_request(root,'context',{},tmp_path/'graph',out,presentation='indexed')
        elif target=='cli_context':
            out.mkdir();proto.main(['context','--cycle',str(root),'--out',str(expected)])
        else:
            proto.prepare_meta_review(root,out,role='critic',model='inert',reasoning_effort='high',max_output_tokens=128,max_wall_seconds=10,
                presentation='inline' if target.startswith('legacy_') else 'indexed')
    assert changed,'actual generated commitment seam was not reached'

def test_default_json_serialization_and_exclusive_existing_file(tmp_path):
    value={'z':'Unicode \u00e9','a':1};raw=(json.dumps(value,indent=2,allow_nan=False)+'\n').encode()
    p=tmp_path/'default.json';pin=material.write_json_new(p,value)
    assert p.read_bytes()==raw and pin['sha256']==hashlib.sha256(raw).hexdigest()
    with pytest.raises(FileExistsError):material.write_json_new(p,{'foreign':True})
    assert p.read_bytes()==raw
