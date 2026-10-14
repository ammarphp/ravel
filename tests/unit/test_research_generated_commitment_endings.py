"""Complete finite generated-output ending population; all transports inert."""
import json
from pathlib import Path
import pytest
from test_research_protocol import make,no_process
from test_research_presentation import population,selections
from ravel.workflow import research_cycle as cycle,research_protocol as proto,research_presentation as material


@pytest.mark.parametrize('presentation,target',[('indexed','public_case'),('indexed','inventory'),('indexed','page0000'),('indexed','manifest'),('indexed','graph_spec'),
    ('inline','subject'),('inline','basis0'),('inline','manifest'),('inline','graph_spec')])
def test_meta_all_emitted_members_refuse_after_last_emission(tmp_path,monkeypatch,presentation,target):
    root,_=make(tmp_path,monkeypatch);out=tmp_path/'meta';changed=[]
    pages=None
    if presentation=='indexed':
        source=population(tmp_path,root,2);pages=selections(root,source[0])
    relative={'public_case':'context/artifacts/public_case.json','inventory':'context/artifacts/inventory.json','page0000':'context/artifacts/page0000.json',
        'manifest':'context/manifest.json','graph_spec':'graph-spec.json','subject':'context/artifacts/subject.json','basis0':'context/artifacts/basis0.txt'}
    path=out/relative[target];old=material.write_json_new
    def late(p,value):
        pin=old(p,value)
        if Path(p)==out/'graph-spec.json' and not changed:
            path.write_bytes(path.read_bytes()+b'\nFOREIGN LATE GENERATED MATERIAL\n');changed.append(True)
        return pin
    monkeypatch.setattr(material,'write_json_new',late)
    with pytest.raises(ValueError):
        proto.prepare_meta_review(root,out,role='critic',model='inert',reasoning_effort='high',max_output_tokens=128,max_wall_seconds=10,
            presentation=presentation,evidence_pages=pages)
    assert changed,'actual last-emission seam was not reached'


def test_compact_host_commitment_ending_also_retained(tmp_path,monkeypatch):
    root,_=make(tmp_path,monkeypatch);out=tmp_path/'host';changed=[];old=material.write_json_new
    def late(p,value):
        pin=old(p,value)
        if Path(p)==out/'request.json' and not changed:
            path=out/'inventory-commitment.json';path.write_bytes(path.read_bytes()+b'\nFOREIGN LATE COMMITMENT\n');changed.append(True)
        return pin
    monkeypatch.setattr(material,'write_json_new',late)
    with pytest.raises(ValueError):proto.prepare_host_request(root,'context',{},tmp_path/'graph',out,presentation='indexed')
    assert changed
