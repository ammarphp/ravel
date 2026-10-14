"""An erratum for one field cannot authorize an unrelated source discrepancy."""
import pytest
from test_published_model import fixture,oracle
from source_record_fixtures import reviewed,write


def test_metadata_erratum_cannot_clear_unrelated_attribution(tmp_path):
    d,_,_=fixture(tmp_path,change=lambda b,p:p['metadata']['references'].update(hepdata='wrong',other='placeholder'))
    external=write(tmp_path/'record.json',{'identity':'ANA-0001'})
    row={'id':'other-field','source':d['source'],'archive_sha256':d['archive']['sha256'],'members':d['members'],
        'field':'/metadata/references/other','observed':'placeholder','external_record_source':'record',
        'external_assertions':[{'pointer':'/identity','expected':'ANA-0001'}]}
    binding=write(tmp_path/'registry.json',reviewed(tmp_path,'errata-registry',{'record':external},errata=[row]))
    d['source_reference_acknowledgment']={'kind':row['id'],'field':row['field'],'observed':row['observed'],
        'external_record':external,'reviewed_registry':binding}
    with pytest.raises(ValueError) as error:oracle.load_published_model(d)
    assert error.value.reason=='missing_reviewed_erratum'
