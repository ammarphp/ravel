"""Synthetic reference extraction and source custody controls."""
from hashlib import sha256
import copy
import pytest


def api():
    from ravel.validation import qualification_rows
    return qualification_rows


def row():
    text='Table 7\nresponse 7.25 +/- 0.50 unit\n'
    return dict(id='qual:synthetic:response',tool='synthetic',quantity='response',
                source={'arxiv':None,'doi':'10.0000/synthetic','hepdata':None,'url':None,
                        'licence':'LicenseRef-source-pending'},
                locator='Table 7',value=7.25,uncertainty={'minus':0.5,'plus':0.5,'definition':'standard uncertainty'},
                units='unit',conditions={'setting':'synthetic'},extraction_method='text',extracted_by='synthetic-extractor',
                status='filled',evidence={'text_sha256':sha256(text.encode()).hexdigest(),
                                         'quote':'response 7.25 +/- 0.50 unit','value_literal':'7.25'})


@pytest.mark.parametrize('field',['locator','units'])
def test_missing_locator_or_units_is_refused(field):
    r=row(); del r[field]
    with pytest.raises(ValueError): api().validate_row(r,text='Table 7\nresponse 7.25 +/- 0.50 unit\n')


def test_planted_wrong_value_is_refused():
    r=row(); r['value']=8.25
    with pytest.raises(ValueError,match='value'): api().validate_row(r,text='Table 7\nresponse 7.25 +/- 0.50 unit\n')


def test_correct_extraction_and_mutated_text():
    r=row(); api().validate_row(r,text='Table 7\nresponse 7.25 +/- 0.50 unit\n')
    with pytest.raises(ValueError,match='checksum'): api().validate_row(r,text='changed')


def test_absent_extracted_text_does_not_authorize_filled_value():
    with pytest.raises(ValueError,match='extracted text'): api().validate_row(row())


def test_number_in_wrong_section_is_refused():
    r=row(); r['locator']='Table 8'
    with pytest.raises(ValueError,match='locator'): api().validate_row(r,text='Table 7\nresponse 7.25 +/- 0.50 unit\n')


def test_pending_rows_are_structural_only_and_ids_resolve():
    doc=api().load_rows(); assert len(doc['comparators'])==17
    referenced={i for ids in doc['comparators'].values() for i in ids}
    assert referenced=={r['id'] for r in doc['rows']}
    for identity in referenced:
        r=api().resolve(identity,require_filled=False)
        assert r['status']=='pending' and r['value'] is None
        with pytest.raises(ValueError,match='pending'): api().resolve(identity)
    assert api().check_directory()==[]


def test_new_directory_is_registered_with_knowledge_check(tmp_path):
    from ravel.validation.check_knowledge import reference_row_errors
    d=tmp_path/'src/ravel/data/knowledge/qualification'; d.mkdir(parents=True)
    (d/'rows.json').write_text('{}')
    assert reference_row_errors(tmp_path)


def test_matching_value_elsewhere_does_not_validate_cited_section():
    text='Table 7\nresponse absent\nTable 8\nresponse 7.25 +/- 0.50 unit\n'
    r=row(); r['evidence']['text_sha256']=sha256(text.encode()).hexdigest()
    with pytest.raises(ValueError,match='locator'): api().validate_row(r,text=text)


def test_filled_cache_resolution_and_symlink_refusal(tmp_path):
    import json
    module=api(); r=row(); r['evidence']['text_file']='source.txt'
    (tmp_path/'rows.json').write_text(json.dumps(dict(schema_version=1,comparators={'synthetic':[r['id']]},rows=[r])))
    (tmp_path/'schema.json').write_bytes((module.DIRECTORY/'schema.json').read_bytes())
    cache=tmp_path/'cache'; cache.mkdir(); (cache/'source.txt').write_text('Table 7\nresponse 7.25 +/- 0.50 unit\n')
    assert module.resolve(r['id'],directory=tmp_path,source_cache=cache)['value']==7.25
    (cache/'source.txt').unlink(); (cache/'source.txt').symlink_to(tmp_path/'rows.json')
    with pytest.raises(ValueError,match='ordinary'): module.resolve(r['id'],directory=tmp_path,source_cache=cache)
