"""Fictional source contracts over the ordinary charged acquisition path."""
from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import urlencode

import pytest

from ravel.workflow import literature_discovery as discovery, literature_discovery_agent as a
from test_literature_discovery_agent import (R, ROLES, SELECTOR, begin, campaign, page,  # noqa: F401
                                           reply_for, routed, run_selection, scope, write, j)


def sources():
    from ravel.workflow import literature_discovery_sources
    return literature_discovery_sources


class FakeSource:
    id = 'fake'
    capabilities = {'citations': False, 'natural_language': True}

    def query_url(self, row):
        return 'https://example.invalid/find?' + urlencode({'q': row['query'], 'page': row['page']})

    def citations_url(self, recid, page):
        raise AssertionError('citation access is unsupported')

    def identifiers(self, record):
        return record['identifiers']

    def parse_page(self, payload):
        return {'records': deepcopy(payload['items']), 'total': len(payload['items']), 'next': None}


def fake_record():
    return {'recid': 'orb-a', 'identifiers': {'analysis': ['ORBIT-A']},
            'title': 'Fictional glimmer resonance', 'abstract': 'A quuxon study.',
            'years': [2020], 'document_type': ['article'], 'references': [], 'linked_hepdata': [],
            'updated': 'epoch-a', 'lookup_url': 'https://example.invalid/orb-a'}


def source_scope(name, **updates):
    return scope(universe={'provider': name, 'years': {'from': 2010, 'to': None},
                           'document_types': None}, **updates)


def test_the_inspire_source_reproduces_the_agent_url_and_identifier_laws():
    source = sources().InspireSource()
    row = {'query': 'glimmer resonance', 'size': 4, 'page': 2, 'purpose': {'kind': 'variant'}}
    expected_url = discovery.API + '?q=glimmer+resonance&size=4&page=2&format=json'
    assert source.query_url(row) == a._request_url(row) == expected_url
    parsed = source.parse_page(page(R['9102'], total={'value': 7, 'relation': 'gte'}))
    record = parsed['records'][0]
    assert {k: record[k] for k in discovery._record(R['9102'])} == discovery._record(R['9102'])
    expected_identifiers = {'inspire': ['9102', 'ins9102', 'INSPIRE:9102'],
                            'arxiv': [R['9102']['metadata']['arxiv_eprints'][0]['value'],
                                      'arXiv:' + R['9102']['metadata']['arxiv_eprints'][0]['value']],
                            'hepdata': ['ins9102', 'ins9102'], 'analysis': []}
    assert source.identifiers(record) == a._record_identifiers('9102', R['9102']['metadata']) == expected_identifiers
    assert record['title'] == R['9102']['metadata']['titles'][0]['title']
    assert record['references'] == ['9101', '9104', '9105']
    assert record['linked_hepdata'][0]['ref'] == 'ins9102'
    assert parsed['total'] == 7 and parsed['next'] is not None
    citation = {**row, 'purpose': {'kind': 'expansion', 'direction': 'references', 'node': '9102'}}
    assert source.query_url(citation) == source.citations_url('9102', citation)
    assert source.query_url(citation) == discovery.API + '?q=citedby%3Arecid%3A9102&size=4&page=2&format=json'


def test_a_second_inert_source_runs_the_loop_without_touching_it(monkeypatch, campaign):
    module = sources()
    monkeypatch.setitem(module.SOURCES, 'fake', FakeSource)
    base, root, host = campaign()
    host.literature_origins = ['https://example.invalid']
    calls = routed(monkeypatch, {('glimmer resonance', '1'): {'items': [fake_record()]}})
    out, initial = begin(base, root, source_scope('fake', seeds=[], follow=[]),
                         source='fake', selector=SELECTOR)
    assert initial['source'] == 'fake'
    step = a.advance(root, out, host, roles=ROLES)
    assert step['status'] == 'select' and step['source'] == 'fake'
    run_selection(monkeypatch, root, host, step, reply_for(step['request'], judge={'orb-a': [
        j('topic', 'met', 'title', 'glimmer resonance'), j('channel', 'met', 'abstract', 'quuxon study'),
        j('review', 'unmet')]}))
    done = a.advance(root, out, host, selection=step['graph_root'], roles=ROLES)
    report = a.consume(root, out, roles=ROLES)
    assert done['source'] == report['source'] == 'fake' and len(calls) == 1
    assert report['population']['demonstrated'][0]['recid'] == 'orb-a'
    assert report['population']['demonstrated'][0]['located'][0]['pointer'] == '/title'
    assert report['follow_up'][0]['source'] == 'fake'
    assert report['capabilities'] == FakeSource.capabilities
    for ledger in (out / 'ledger').glob('*.json'):
        value = json.loads(ledger.read_text())
        assert value['source'] == value['event']['source'] == 'fake'
    for rows in report['population'].values():
        assert all(row['source'] == 'fake' for row in rows)
    assert all(row['source'] == 'fake' for row in report['search_universe']['queries'])
    with pytest.raises(ValueError, match='source'):
        a.report(root, out, source='inspire', roles=ROLES)
    # Even the same identity cannot replay under a different URL law.
    class ChangedSource(FakeSource):
        def query_url(self, row): return super().query_url(row) + '&changed=1'
    monkeypatch.setitem(module.SOURCES, 'fake', ChangedSource)
    with pytest.raises(ValueError, match='planned|source|URL'):
        a.consume(root, out, roles=ROLES)


def test_scope_cannot_select_a_source_and_unknown_sources_are_refused(campaign):
    with pytest.raises(ValueError, match='fields'):
        a.validate_scope(scope(source='fake'))
    with pytest.raises(ValueError, match='discovery_source_unknown'):
        sources().source_for('absent')
    base, root, _ = campaign()
    with pytest.raises(ValueError, match='discovery_source_unknown'):
        begin(base, root, source='absent')
    assert not (root / 'discovery').exists()


def test_a_source_without_citation_capability_qualifies_citation_steps_honestly(monkeypatch, campaign):
    module = sources()
    class QueryOnly(module.InspireSource):
        id = 'query-only'
        capabilities = {'citations': False, 'natural_language': False}
        def citations_url(self, recid, page):
            raise AssertionError('must refuse before constructing a citation URL')
    monkeypatch.setitem(module.SOURCES, 'query-only', QueryOnly)
    base, root, host = campaign()
    calls = routed(monkeypatch, {('recid:9101', '1'): page(R['9101'])})
    out, _ = begin(base, root, source_scope('query-only', queries=[], source_restrictions=[]),
                   source='query-only')
    assert a.advance(root, out, host, roles=ROLES)['status'] == 'complete'
    report = a.consume(root, out, roles=ROLES)
    assert len(calls) == 1
    refusals = [g for g in report['gaps'] if g.get('reason') == 'source_lacks_citations']
    assert len(refusals) == 2 and all(g['status'] == 'refused' for g in refusals)
    assert report['usage']['expansions'] == 0


def test_cursor_pages_with_unknown_totals_remain_bounded(monkeypatch, campaign):
    module = sources()
    class CursorSource(FakeSource):
        def query_url(self, row):
            return super().query_url(row) + '&cursor=' + str(row.get('cursor', 'first'))
        def parse_page(self, payload):
            return {'records': payload['items'], 'total': None, 'next': payload['cursor']}
    monkeypatch.setitem(module.SOURCES, 'fake', CursorSource)
    base, root, host = campaign()
    host.literature_origins = ['https://example.invalid']
    second = {**fake_record(), 'recid': 'orb-b', 'identifiers': {'analysis': ['ORBIT-B']}}
    calls = routed(monkeypatch, {
        ('glimmer resonance', '1'): {'items': [fake_record()], 'cursor': 'next-page'},
        ('glimmer resonance', '2'): {'items': [second], 'cursor': 'unvisited-page'},
    })
    out, _ = begin(base, root, source_scope('fake', seeds=[], follow=[],
                                          limits={'page_size': 1, 'max_pages': 2}), source='fake')
    a.advance(root, out, host, roles=ROLES)
    report = a.consume(root, out, roles=ROLES)
    assert len(calls) == 2 and 'cursor=next-page' in calls[1]['target']
    assert report['usage']['requests'] == 2 and report['counts']['unresolved'] == 2
    assert any(g['kind'] == 'unfetched_pages' for g in report['gaps'])


@pytest.mark.parametrize('change', [{'provider': 'fake'}, {'request_url': 'https://example.invalid/foreign'},
                                  {'operation': 'record'}])
def test_an_inspire_receipt_cannot_change_source_or_url_law(monkeypatch, tmp_path, change):
    module = sources()
    source = module.InspireSource()
    row = {'query': 'fictional glimmer', 'size': 1, 'page': 1}
    result = {'provider': 'inspire', 'operation': 'query', 'request_url': source.query_url(row), **change}
    monkeypatch.setattr(discovery, 'consume', lambda *args, **kwargs: {'result': result})
    with pytest.raises(ValueError, match='source|planned'):
        module.consume_page(source, {}, base_dir=tmp_path, row=row, expected_request={})
