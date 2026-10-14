"""UNRUN local-reader/domain regressions using fabricated complete replica records.

Path(unquote(urlsplit(uri).path)).absolute() is the pinned local reader's path
construction. No event file, ROOT reader, scientific production or authority is
provided. Only root may execute these ordinary source/API controls.
"""
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from ravel.physics import mc_closure as h
from test_mc_closure_replica_admission import replicas


@pytest.mark.parametrize('malformed,replacement', [
    ('file:///fabricated/%FF.root', 'file:///fabricated/%EF%BF%BD.root'),
    ('file:///fabricated/%E2%82.root', 'file:///fabricated/%EF%BF%BD.root')])
@pytest.mark.parametrize('malformed_role', ['prediction', 'heldout'])
def test_malformed_utf8_pair_matching_actual_local_reader_refuses(
        replicas, monkeypatch, malformed, replacement, malformed_role):
    # This is the original N1 reader/key pair, plus a truncated multibyte pair.
    # Distinct GUIDs and complete exposures cannot make the reused file independent.
    actual = lambda uri: Path(unquote(urlsplit(uri).path)).absolute()
    assert actual(malformed) == actual(replacement)
    assert malformed != replacement
    for role in ('prediction', 'heldout'):
        replicas.sample(role)['members'][0]['uri'] = malformed if role == malformed_role else replacement
    assert replicas.sample('prediction')['members'][0]['guid'] != replicas.sample('heldout')['members'][0]['guid']
    replicas.sync()
    monkeypatch.setattr(h, 'contrast', lambda *args: pytest.fail('reader alias reached independence contrast'))
    with pytest.raises(ValueError, match='strict UTF-8 local URI'):
        h._load(replicas.task, replicas.base)


@pytest.mark.parametrize('literal,encoded', [
    ('file:///fabricated/é.root', 'file:///fabricated/%C3%A9.root'),
    ('file:///fabricated/�.root', 'file:///fabricated/%EF%BF%BD.root'),
    ('file://localhost/fabricated/μ.root', 'file:///fabricated/%CE%BC.root')])
def test_valid_unicode_reader_alias_refuses_without_rewriting(replicas, literal, encoded):
    assert Path(unquote(urlsplit(literal).path)).absolute() == Path(unquote(urlsplit(encoded).path)).absolute()
    replicas.sample('prediction')['members'][0]['uri'] = literal
    replicas.sample('heldout')['members'][0]['uri'] = encoded
    replicas.sync()
    with pytest.raises(ValueError, match='URI alias'):
        h._load(replicas.task, replicas.base)


@pytest.mark.parametrize('prediction,heldout', [
    ('file:///fabricated/é.root', 'file:///fabricated/%CE%BC.root'),
    ('file:///fabricated/%EF%BF%BD.root', 'file:///fabricated/v.root')])
def test_distinct_valid_unicode_paths_preserve_complete_original_sources(
        replicas, prediction, heldout):
    assert Path(unquote(urlsplit(prediction).path)).absolute() != Path(unquote(urlsplit(heldout).path)).absolute()
    replicas.sample('prediction')['members'][0]['uri'] = prediction
    replicas.sample('heldout')['members'][0]['uri'] = heldout
    replicas.sync()
    value = h._load(replicas.task, replicas.base)
    for role, uri in [('prediction', prediction), ('heldout', heldout)]:
        assert value[4][role]['dataset']['samples'][0]['members'][0]['uri'] == uri
    assert value[-1][0]['original_source_entries'] == {'prediction': 2, 'heldout': 2}
    assert value[-1][0]['result']['basis'] == ['SR', 'CR', 'VR']
    assert h.context(replicas.task, replicas.base)['execution_authorized'] is False
    assert h.inputs(replicas.task, replicas.base)
    assert h.execution_seconds(replicas.task, replicas.base) == 60
