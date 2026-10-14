"""Synthetic source pin refusal controls."""
import copy
import json
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def validator():
    return Draft202012Validator(json.loads((ROOT / 'native/setup/tools-pins.schema.json').read_text()))


def document(kind='git', filled=False):
    row = dict(tool='synthetic-tool', kind=kind, url='https://example.invalid/tool',
               version='1.2.3', licence_file='LICENSE', status='pending',
               commit=None, sha256=None, size=None, revision=None, digest=None,
               licence_text_sha256=None, fetched_utc=None,
               licence=dict(spdx='MIT', redistribute=True, import_into_ravel='allowed',
                            container_publish='allowed', evidence_status='pending'))
    if filled:
        row.update(status='filled', commit='a'*40, sha256='b'*64, size=17, revision=3,
                   digest='sha256:'+'c'*64, licence_text_sha256='d'*64,
                   fetched_utc='2026-01-02T03:04:05Z')
        row['licence']['evidence_status']='verified'
    return dict(schema_version=1, tools={'synthetic-tool': row}, tool_rows={'synthetic': ['synthetic-tool']})


@pytest.mark.parametrize('mutation', ['licence_file','commit','sha256','licence_text_sha256','fetched_utc'])
def test_missing_source_or_licence_evidence_is_refused(mutation):
    doc=document(filled=True); del doc['tools']['synthetic-tool'][mutation]
    assert list(validator().iter_errors(doc))


@pytest.mark.parametrize('kind,field', [('git','commit'),('archive','sha256'),('conda','sha256'),
                                       ('svn','revision'),('image','digest')])
def test_filled_source_requires_kind_pin(kind,field):
    doc=document(kind,True); doc['tools']['synthetic-tool'][field]=None
    assert list(validator().iter_errors(doc))


@pytest.mark.parametrize('kind', ['git','archive','conda','svn','image'])
def test_complete_and_pending_sources_validate(kind):
    validator().validate(document(kind)); validator().validate(document(kind,True))


def test_catalogue_rows_resolve_and_have_licences():
    doc=json.loads((ROOT / 'native/setup/tools-pins.json').read_text()); validator().validate(doc)
    assert len(doc['tool_rows']) >= 35
    assert set(doc['tools']) == {k for keys in doc['tool_rows'].values() for k in keys}
    for row in doc['tools'].values():
        assert row['licence_file'] and row['licence']['spdx']
        if not row['licence']['redistribute']:
            assert row['licence']['container_publish']=='never'


def test_pending_resolution_is_not_installable():
    from ravel.setup.licence_policy import load_pin
    with pytest.raises(ValueError,match='pending'):
        load_pin('synthetic-tool', document=document())
    assert load_pin('synthetic-tool', document=document(filled=True))['commit']=='a'*40


@pytest.mark.parametrize('mutation', ['short_hash','wildcard_version','unverified_licence'])
def test_runtime_pin_resolver_refuses_malformed_filled_entry(mutation):
    from ravel.setup.licence_policy import load_pin
    doc=document(filled=True); r=doc['tools']['synthetic-tool']
    if mutation=='short_hash': r['commit']='abc'
    elif mutation=='wildcard_version': r['version']='1.*'
    else: r['licence']['evidence_status']='pending'
    with pytest.raises(ValueError): load_pin('synthetic-tool',document=doc)


def test_fragment_licence_entries_retain_policy_and_evidence():
    from ravel.setup.licence_policy import licence_entries
    doc=document(); entries=licence_entries(['synthetic-tool'],document=doc)
    assert entries[0]['component']=='synthetic-tool'
    assert entries[0]['licence_text_sha256'] is None
    with pytest.raises(ValueError,match='pending'):
        licence_entries(['synthetic-tool'],document=doc,require_verified=True)
