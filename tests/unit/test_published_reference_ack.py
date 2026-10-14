"""Explicit selected errata through the complete synthetic archive importer."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from test_published_model import fixture,oracle
from source_record_fixtures import reviewed,write


def selected(tmp_path):
    d,_,_=fixture(tmp_path,change=lambda b,p:p['metadata']['references'].update(hepdata='unattributed'))
    epin=write(tmp_path/'external.json',{'identity':'ANA-0001','resource':'synthetic archive'})
    entry={'id':'source-attribution','source':d['source'],'archive_sha256':d['archive']['sha256'],'members':d['members'],
        'field':'/metadata/references/hepdata','observed':'unattributed','external_record_source':'external',
        'external_assertions':[{'pointer':'/identity','expected':'ANA-0001'},{'pointer':'/resource','expected':'synthetic archive'}]}
    value=reviewed(tmp_path,'errata-registry',{'external':epin},errata=[entry])
    rpin=write(tmp_path/'registry.json',value)
    d['source_reference_acknowledgment']={'kind':entry['id'],'field':entry['field'],'observed':entry['observed'],
        'external_record':epin,'reviewed_registry':rpin}
    return d,value,rpin


def test_explicit_erratum_keeps_workspace_numbers_and_original_archive(tmp_path):
    d,_,_=selected(tmp_path);before=Path(d['archive']['path']).read_bytes()
    admitted=oracle.load_published_model(d)
    assert admitted.workspace()['observations']==[{'name':'SR','data':[12]},{'name':'CR','data':[20]}]
    receipt=admitted.manifest()['source_reference_acknowledgment']
    assert receipt['literal_source_value']=='unattributed' and receipt['source_bytes_modified'] is False
    assert Path(d['archive']['path']).read_bytes()==before


def test_erratum_registry_and_evidence_are_ordinary_approval_inputs(tmp_path):
    d,value,rpin=selected(tmp_path)
    path=tmp_path/'input.json';path.write_text(json.dumps(d))
    inputs=oracle.inputs({'input':str(path)},tmp_path)
    assert Path(rpin['path']) in inputs
    assert all(Path(p['path']) in inputs for p in value['review']['evidence'])
    assert Path(d['source_reference_acknowledgment']['external_record']['path']) in inputs


@pytest.mark.parametrize('field',['archive','member','source','literal','registry','evidence'])
def test_any_changed_attribution_binding_refuses(tmp_path,field):
    d,value,rpin=selected(tmp_path)
    if field=='archive':d['archive']['sha256']='0'*64
    elif field=='member':d['members']['background']['sha256']='0'*64
    elif field=='source':d['source']['record_id']='ANA-0002'
    elif field=='literal':d['source_reference_acknowledgment']['observed']='other'
    elif field=='registry':Path(rpin['path']).write_text('{}')
    else:Path(value['review']['evidence'][0]['path']).write_text('changed')
    with pytest.raises(ValueError):oracle.load_published_model(d)


def test_missing_registry_cannot_use_ambient_authority(tmp_path,monkeypatch):
    d,_,rpin=selected(tmp_path)
    del d['source_reference_acknowledgment']['reviewed_registry']
    monkeypatch.setenv(oracle.REFERENCE_ACKS_ENV,rpin['path'])
    with pytest.raises(ValueError) as error:oracle.load_published_model(d)
    assert error.value.reason=='missing_reviewed_erratum'


def test_mismatch_without_erratum_has_typed_missing_input(tmp_path):
    d,_,_=fixture(tmp_path,change=lambda b,p:p['metadata']['references'].update(hepdata='unattributed'))
    with pytest.raises(ValueError) as error:oracle.load_published_model(d)
    assert error.value.reason=='missing_reviewed_erratum'
