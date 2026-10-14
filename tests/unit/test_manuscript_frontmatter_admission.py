"""Prospective independent ordinary-caller controls — AUTHORED, NOT RUN.

Inherited stock setup/completed functions expose explicitly inert transport and
campaign authority. No actual model response, scientific vote, TeX/PDF or data.
Source-owner review may read these; only root may admit their execution.
"""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from ravel.workflow import manuscript_production as mp
from test_manuscript_production import setup,completed,put


def test_actual_prepare_writer_refuses_combined_title_abstract_before_graph(tmp_path,monkeypatch):
    request,state,value=setup(tmp_path/'original',monkeypatch)
    base=tmp_path/'original'
    fmt=json.loads(Path(request['formatting']['path']).read_text())
    fmt['sections']=[{'id':i,'heading':heading,'semantics':roles,'placement':'main'}for i,heading,roles in [
        ('opening','Opening',['title','abstract']),('methods','Methods',['methods']),
        ('results','Results',['results']),('limitations','Limitations',['limitations'])]]
    for row in fmt['rules']:
        if row['kind'] in {'required_sections','section_order'}:
            row['value']=['opening','methods','results','limitations']
    request['formatting']=put(base,'format.json',fmt)
    # Desired admission: incompatible native frontmatter must fail before any
    # author Graph, not after one charged generation in _materialize.
    with pytest.raises(ValueError,match='frontmatter|native role'):
        mp.prepare_writer(request,tmp_path/'writer',base_dir=base,campaign=tmp_path/'campaign')
    assert not (tmp_path/'writer/graph').exists()


def test_actual_prepare_writer_keeps_nonfront_multi_semantic_custom_sections(tmp_path,monkeypatch):
    request,state,value=setup(tmp_path/'original',monkeypatch)
    base=tmp_path/'original';fmt=json.loads(Path(request['formatting']['path']).read_text())
    fmt['sections']=[{'id':i,'heading':heading,'semantics':roles,'placement':'main'}for i,heading,roles in [
        ('title','Title',['title']),('abstract','Abstract',['abstract']),
        ('intro','Custom introduction',['strategy','methods']),('results','Results',['results']),
        ('conclusion','Custom conclusion',['limitations'])]]
    for row in fmt['rules']:
        if row['kind'] in {'required_sections','section_order'}:
            row['value']=['title','abstract','intro','results','conclusion']
    request['formatting']=put(base,'format.json',fmt)
    value=deepcopy(value);value['paragraphs'][2]['section']='intro';value['paragraphs'][-1]['section']='conclusion'
    binding=mp.prepare_writer(request,tmp_path/'writer',base_dir=base,campaign=tmp_path/'campaign')
    # Existing disclosed inert transport. This is not an actual author call.
    completed(binding,state,value,monkeypatch)
    package=mp.collect(binding,tmp_path/'note')['package']
    tex=Path(package['latex']['path']).read_text()
    assert 'Custom introduction' in tex and 'Custom conclusion' in tex
    mp.verify_author(package,base_dir=tmp_path/'note')
