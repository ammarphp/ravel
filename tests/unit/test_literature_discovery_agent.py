"""Controls for bounded INSPIRE discovery with a governed criterion selector.

Records, titles and identifiers are fictional. Scripted HTTPS pages pass through the real
campaign, Host, Graph and acquisition receipt path of the existing discovery client; the
selector's model node runs on an inert Host whose reply is fixed by the test. Subprocesses
are refused, so no process, provider or model is reached.
"""
import synthetic_identifiers as syn
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from urllib.parse import parse_qs, urlsplit

import pytest

from ravel.validation import check_agent_paths
from ravel.workflow import agent_graph, agent_host, literature_context as lc
from ravel.workflow import literature_discovery as discovery, literature_discovery_agent as a
from ravel.workflow import research_cycle as cycle
from ravel.workflow.literature_relations import SourceDocument, build_graph, digest
from test_literature_context import task
from test_research_cycle import contract, write

PROTOCOL = ['Judge fictional criteria from the presented fields only.', 'Quote exact excerpts for met judgments.']
ROLES = {'aliases': {}, 'roles': {a.ROLE: {'card': {'id': a.ROLE, 'protocol': PROTOCOL}}}}
SELECTOR = {'model': 'explicit-inert-fixture', 'reasoning_effort': 'low', 'adapter': 'responses',
            'max_output_tokens': 2048, 'max_wall_seconds': 60}
CRITERIA = [{'id': 'topic', 'kind': 'required', 'statement': 'Studies the fictional glimmer resonance.'},
            {'id': 'channel', 'kind': 'required', 'statement': 'Uses a quuxon final state.'},
            {'id': 'review', 'kind': 'exclusion', 'statement': 'Is a review article.'},
            {'id': 'data', 'kind': 'preferred', 'statement': 'Releases tabulated results.'}]
WITHHELD_TITLE = 'Withheld glimmer source'
FORBIDDEN = {'kind': 'forbidden-source', 'statement': 'A fictional withheld source.', 'evidence': [],
             'identifiers': {'arxiv': ['arXiv:' + syn.arxiv(6) + 'v2']}}


def record(recid, title, *, abstract=None, year=2020, eprint=None, refs=(), cited=None, hepdata=None,
           types=('article',), reports=()):
    m = {'control_number': int(recid), 'titles': [{'title': title}], 'authors': [{'full_name': 'Fictional, Author'}],
         'publication_info': [{'year': year}], 'document_type': list(types)}
    if abstract: m['abstracts'] = [{'value': abstract}]
    if eprint: m['arxiv_eprints'] = [{'value': eprint}]
    if refs: m['references'] = [{'record': {'$ref': discovery.API + '/' + r}} for r in refs]
    if cited is not None: m['citation_count'] = cited
    if hepdata: m['external_system_identifiers'] = [{'schema': 'HEPDATA', 'value': hepdata}]
    if reports: m['report_numbers'] = [{'value': r} for r in reports]
    return {'id': recid, 'created': '2020-01-01T00:00:00', 'updated': '2024-01-02T00:00:00', 'metadata': m}


def page(*records, total=None):
    return {'hits': {'total': len(records) if total is None else total, 'hits': list(records)}}


R = {
    '9101': record('9101', 'Glimmer resonance search in quuxon final states', cited=5, refs=('9102', '9109'),
                    abstract='We search for a glimmer resonance decaying to quuxon pairs.'),
    '9102': record('9102', 'Glimmer resonance with quuxons', eprint=syn.arxiv(2), hepdata='ins9102',
                    refs=('9101', '9104', '9105'),
                    abstract='A glimmer resonance is studied with quuxon jets; tabulated results are released.'),
    '9103': record('9103', 'Glimmer resonance overview'),
    '9104': record('9104', 'Quuxon calibration', abstract='A calibration of quuxon response.'),
    '9105': record('9105', 'Early glimmer notes', year=1999),
    '9106': record('9106', WITHHELD_TITLE, eprint=syn.arxiv(6)),
    '9107': record('9107', 'Glimmer resonance in another channel'),
    '9108': record('9108', 'Glimmer resonance revisited', abstract='Quuxon final states constrain the resonance.'),
    '9109': record('9109', 'A review of glimmer resonances', abstract='This review covers quuxon searches.'),
}
ROUTES = {
    ('recid:9101', '1'): page(R['9101']),
    ('glimmer resonance', '1'): page(R['9102'], R['9103'], R['9104'], R['9105'], total=7),
    ('glimmer resonance', '2'): page(R['9106'], R['9107'], total=7),
    ('refersto:recid:9101', '1'): page(R['9108']),
    ('citedby:recid:9101', '1'): page(R['9102'], R['9109']),
}


def j(criterion, judgment, field=None, excerpt=None):
    return {'criterion': criterion, 'judgment': judgment, 'field': field, 'excerpt': excerpt}


JUDGE = {
    '9101': [j('topic', 'met', 'title', 'Glimmer resonance search'), j('channel', 'met', 'abstract', 'quuxon pairs'),
              j('review', 'unmet')],
    '9102': [j('topic', 'met', 'title', 'Glimmer resonance'), j('channel', 'met', 'abstract', 'quuxon jets'),
              j('review', 'unmet'), j('data', 'met', 'abstract', 'tabulated results are released')],
    '9103': [j('topic', 'met', 'title', 'Glimmer resonance overview'),
              j('channel', 'met', 'abstract', 'quuxon final state'), j('review', 'uncertain')],
    '9104': [j('topic', 'unmet'), j('channel', 'met', 'title', 'Quuxon calibration'), j('review', 'unmet')],
    '9108': [j('topic', 'met', 'title', 'Glimmer resonance revisited'),
              j('channel', 'met', 'abstract', 'Quuxon final states'), j('review', 'unmet')],
    '9109': [j('topic', 'met', 'title', 'review of glimmer resonances'), j('channel', 'met', 'abstract', 'quuxon searches'),
              j('review', 'met', 'abstract', 'This review')],
}


def routed(monkeypatch, routes, *, missing=None):
    """HTTPS answered by (q, page); an unknown route is an empty page, or ``missing`` status."""
    calls = []

    class Sock:
        def getpeername(self): return ('93.184.216.34', 443)
        def settimeout(self, seconds): assert seconds > 0

    class Response:
        def __init__(self, status, body): self.offset, self.status, self.body = 0, status, body
        def getheader(self, key): return None
        def read(self, n):
            part = self.body[self.offset:self.offset + n]; self.offset += len(part); return part

    class Connection:
        def __init__(self, host, port, timeout, context):
            calls.append({'host': host}); self.sock = Sock()
        def connect(self): pass
        def request(self, method, target, headers):
            query = parse_qs(urlsplit(target).query)
            calls[-1].update(target=target, q=query.get('q', [None])[0], page=query.get('page', [None])[0])
        def getresponse(self):
            self.sock = None
            key = (calls[-1]['q'], calls[-1]['page'])
            if key in routes:
                return Response(200, json.dumps(routes[key]).encode())
            if missing is not None:
                return Response(missing, b'{"status": "unavailable"}')
            return Response(200, json.dumps(page(total=0)).encode())
        def close(self): pass

    monkeypatch.setattr(lc.http.client, 'HTTPSConnection', Connection)
    monkeypatch.setattr(lc.socket, 'getaddrinfo', lambda *args, **kwargs: [(2, 1, 6, '', ('93.184.216.34', 443))])
    return calls


@pytest.fixture
def campaign(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('no process, provider or model dispatch in discovery controls')
    monkeypatch.setattr(subprocess, 'Popen', refuse)

    def make(calls=200):
        base = tmp_path.resolve(); root = base / 'campaign'
        value = contract(base)
        value['budget'] = {'calls': calls, 'output_tokens': 100000, 'wall_seconds': 100000, 'native_attempts': 6}
        cycle.create(root, value, base_dir=base, evaluation_harness=True)
        host = agent_host.AgentHost(timeout_seconds=30, literature_origins=[discovery.ORIGIN])
        return base, root, host
    return make


def scope(**updates):
    value = {'schema_version': 1, 'kind': a.SCOPE_KIND, 'id': 'glimmer-sources',
             'question': 'Which searches constrain the fictional glimmer resonance in quuxon final states?',
             'criteria': deepcopy(CRITERIA), 'concepts': [],
             'queries': [{'id': 'broad', 'text': 'glimmer resonance'}], 'seeds': ['9101'],
             'universe': {'provider': 'inspire', 'years': {'from': 2010, 'to': None}, 'document_types': None},
             'follow': ['cited_by', 'references'], 'limits': {'page_size': 4, 'max_pages': 2},
             'source_restrictions': [deepcopy(FORBIDDEN)], 'tasks': [task()]}
    value.update(updates)
    return value


def reply_for(pin, judge=JUDGE, omit=()):
    document = json.loads(Path(pin['path']).read_text())
    return {'kind': a.CHOICE_KIND, 'request_sha256': pin['sha256'],
            'decisions': [{'candidate': c['key'], 'judgments': deepcopy(judge[c['key']])}
                          for c in document['candidates'] if c['key'] in judge and c['key'] not in omit]}


def run_selection(monkeypatch, root, host, step, reply):
    """The caller's part: execute the returned Graph through the ordinary charged campaign API."""
    monkeypatch.setattr(host, '_responses', lambda data, parameters, request, control: host._result(
        deepcopy(reply), parameters, request, observed_model='explicit-inert-fixture',
        usage={'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}))
    return cycle.execute_graph(root, Path(step['graph_root']), step['graph_spec'], host)


def fictional_graph():
    def source(name, kind, doc):
        return SourceDocument(name, kind, 'https://example.invalid/' + name, 'snapshot-1', digest(doc), doc, ())
    return build_graph([
        source('bibliography', 'inspire', {'metadata': {'control_number': 9102,
               'titles': [{'title': 'Glimmer resonance with quuxons'}], 'arxiv_eprints': [{'value': syn.arxiv(2)}]}}),
        source('implementations', 'catalogue', {
            'sources': {'engine-a': {'revision': 'a' * 40, 'repository': 'https://example.invalid/repository'}},
            'entries': [{'id': 'engine-a:selection_a', 'framework': 'engine-a', 'source_id': 'engine-a',
                         'inspire_id': 'ins9102', 'analysis_ids': ['SEARCH-A'], 'upstream_status': 'released',
                         'source_files': ['analyses/selection_a.cc'], 'workspaces': []}]})])


def begin(base, root, value=None, **options):
    pin = write(base / 'scope.json', scope() if value is None else value)
    return root / 'discovery', a.start(root, pin, root / 'discovery', roles=ROLES, **options)


def by_recid(report):
    return {e['recid']: e for entries in report['population'].values() for e in entries}


# Typed scope and the governed call -----------------------------------------------------------

@pytest.mark.parametrize('change, message', [
    ({'criteria': [{'id': 'topic', 'kind': 'preferred', 'statement': 'Anything.'}]}, 'required criterion'),
    ({'criteria': [{'id': 'topic', 'kind': 'vague', 'statement': 'Anything.'}]}, 'criterion kind'),
    ({'seeds': ['0912']}, 'record IDs'),
    ({'seeds': ['9101', '9101']}, 'duplicate seed'),
    ({'concepts': [{'id': 'c', 'field': 'title', 'forms': ['say "this"']}]}, 'quotation'),
    ({'concepts': [{'id': 'c', 'field': 'abstract', 'forms': ['glimmer']}]}, 'title or any'),
    ({'queries': [{'id': 'concepts-0', 'text': 'glimmer'}]}, 'reserved'),
    ({'queries': [], 'concepts': [], 'seeds': []}, 'needs a query'),
    ({'limits': {'page_size': 26}}, 'page_size'),
    ({'limits': {'max_depth': 4}}, 'max_depth'),
    ({'limits': {'unknown': 1}}, 'limits accept'),
    ({'follow': ['sideways']}, 'citation directions'),
    ({'universe': {'provider': 'elsewhere', 'years': {'from': None, 'to': None}, 'document_types': None}}, 'provider'),
    ({'universe': {'provider': 'inspire', 'years': {'from': 2020, 'to': 2010}, 'document_types': None}}, 'empty year'),
    ({'tasks': []}, 'scout obligations'),
    ({'id': '9-start'}, 'scope ID'),
    ({'source_restrictions': [{'kind': 'forbidden-source', 'statement': 'x'}]}, 'evidence'),
])
def test_scope_is_typed_closed_and_bounded(change, message):
    with pytest.raises(ValueError, match=message):
        a.validate_scope(scope(**change))
    extra = scope(); extra['unexpected'] = True
    with pytest.raises(ValueError, match='exactly'):
        a.validate_scope(extra)


def test_query_variants_are_explicit_then_one_concept_form_at_a_time():
    value = a.validate_scope(scope(concepts=[
        {'id': 'resonance', 'field': 'title', 'forms': ['glimmer resonance', 'glimmer state']},
        {'id': 'channel', 'field': 'any', 'forms': ['quuxon pair', 'quuxon jets', 'two quuxons']}]))
    assert [v['query'] for v in a.variants(value)] == [
        'glimmer resonance',
        't "glimmer resonance" and "quuxon pair"', 't "glimmer state" and "quuxon pair"',
        't "glimmer resonance" and "quuxon jets"', 't "glimmer resonance" and "two quuxons"']
    assert value['limits'] == {**a.LIMITS, 'page_size': 4, 'max_pages': 2}


def test_module_authors_no_instruction_text_or_direct_model_reach():
    source = Path(a.__file__).read_text()
    assert check_agent_paths.scan_source(source, module='ravel.workflow.literature_discovery_agent',
                                         path='ravel/workflow/literature_discovery_agent.py', is_package=False) == []


def test_selector_graph_is_one_bounded_call_with_the_card_protocol_and_a_closed_schema(tmp_path):
    value = a.validate_scope(scope())
    candidates = [{'recid': r, 'metadata': R[r]['metadata']} for r in ('9101', '9103')]
    request = a.selection_request(value, candidates, roles=ROLES)
    assert request['candidates'][1]['abstract'] is None and request['candidates'][0]['years'] == [2020]
    pin = write(tmp_path / 'request.json', request)
    spec = a.graph_spec(pin, request, SELECTOR, graph_id='select-control', roles=ROLES)
    assert spec['budget'] == {'max_nodes': 1, 'max_calls': 1, 'max_output_tokens': 2048, 'max_wall_seconds': 60,
                              'max_reworks': 0}
    (node,) = spec['nodes']
    assert node['kind'] == 'model' and node['max_attempts'] == 1 and node['parameters']['instructions'] == ' '.join(PROTOCOL)
    schema = node['parameters']['output_schema']['properties']
    assert schema['request_sha256']['const'] == pin['sha256']
    assert schema['decisions']['items']['properties']['candidate']['enum'] == ['9101', '9103']
    judgment = schema['decisions']['items']['properties']['judgments']['items']['properties']
    assert judgment['criterion']['enum'] == [c['id'] for c in CRITERIA] and judgment['excerpt']['maxLength'] == 300
    for bad in ({'adapter': 'arbitrary'}, {'model': ' '}, {'max_output_tokens': 10}, {'max_wall_seconds': 5}):
        with pytest.raises(ValueError):
            a._selector({**SELECTOR, **bad})
    with pytest.raises(ValueError, match='role_card_unavailable'):
        a.selection_request(value, candidates, roles={'aliases': {}, 'roles': {}})


@pytest.mark.parametrize('judgments, status, reasons', [
    ({'topic': 'L', 'channel': 'L', 'review': 'unmet'}, 'demonstrated', []),
    ({'topic': 'L', 'channel': 'L'}, 'plausible', ['not_judged:review']),
    ({'topic': 'L', 'channel': 'uncertain', 'review': 'unmet'}, 'plausible', ['required_uncertain:channel']),
    ({'topic': 'L', 'channel': 'U', 'review': 'unmet'}, 'plausible', ['required_unlocated:channel:excerpt_not_in_field']),
    ({'topic': 'unmet', 'channel': 'uncertain', 'review': 'unmet'}, 'rejected', ['required_unmet:topic', 'required_uncertain:channel']),
    ({'topic': 'L', 'channel': 'L', 'review': 'L'}, 'rejected', ['exclusion_applies:review']),
    ({'topic': 'L', 'channel': 'L', 'review': 'U'}, 'plausible', ['exclusion_unlocated:review:excerpt_not_in_field']),
    ({'topic': 'L', 'channel': 'L', 'review': 'uncertain'}, 'plausible', ['exclusion_uncertain:review']),
])
def test_classification_needs_located_support_for_demonstrated_and_located_exclusions(judgments, status, reasons):
    located = {'field': 'title', 'pointer': '/metadata/titles/0/title', 'start': 0, 'end': 4, 'excerpt': 'Text'}
    rows = {k: {'judgment': 'met', 'located': located, 'location_failure': None} if v == 'L' else
            {'judgment': 'met', 'located': None, 'location_failure': 'excerpt_not_in_field'} if v == 'U' else
            {'judgment': v, 'located': None, 'location_failure': None} for k, v in judgments.items()}
    verdict = a.classify(rows, CRITERIA)
    assert verdict['status'] == status and verdict['reasons'] == reasons


def test_excerpts_must_be_exact_bounded_and_inside_the_presented_field():
    shown = {'title': 'Glimmer resonance search', 'abstract': 'We search for quuxon pairs.'}
    assert a._locate(shown, 'abstract', 'quuxon pairs', 300) == (
        {'field': 'abstract', 'pointer': '/metadata/abstracts/0/value', 'start': 14, 'end': 26,
         'excerpt': 'quuxon pairs'}, None)
    assert a._locate(shown, 'abstract', 'Quuxon pairs', 300)[1] == 'excerpt_not_in_field'
    assert a._locate(shown, 'title', 'Gli', 300)[1] == 'excerpt_out_of_bounds'
    assert a._locate(shown, 'title', 'Glimmer resonance search', 10)[1] == 'excerpt_out_of_bounds'
    assert a._locate({'title': 'x', 'abstract': None}, 'abstract', 'quuxon', 300)[1] == 'field_absent'
    assert a._locate(shown, None, None, 300)[1] == 'no_excerpt'
    value = a.validate_scope(scope(limits={'max_abstract_chars': 10}))
    shown = a._presented({'recid': '9102', 'metadata': R['9102']['metadata']}, value['limits'])
    assert shown['abstract'] == 'A glimmer ' and shown['abstract_truncated']
    assert a._locate(shown, 'abstract', 'quuxon jets', 300)[1] == 'excerpt_not_in_field'


def test_source_policy_aliases_withhold_every_spelling_and_queries_are_screened_by_located_rows():
    rows = a.validate_scope(scope())['source_restrictions']
    identities = a._record_identifiers('9106', R['9106']['metadata'])
    assert not a._screen(rows, identities)['allowed']
    assert a._screen(rows, a._record_identifiers('9102', R['9102']['metadata']))['allowed']
    assert a._screen_query(rows, 'eprint ' + syn.arxiv(6)) is not None
    assert a._screen_query(rows, 'glimmer resonance') is None
    blinded = [{'kind': 'blinded', 'statement': 'Observed data are blinded.', 'evidence': []}]
    assert a._screen_query(blinded, 'glimmer resonance') is None
    assert not a._screen(blinded, identities)['allowed']
    scoped = [{'kind': 'no-value-extraction', 'statement': 'No limit values from this source.', 'evidence': [],
               'identifiers': {'analysis': [syn.analysis(4).lower()]}, 'scope': {'quantities': ['upper-limit']}}]
    tagged = a._record_identifiers('9104', record('9104', 'x', reports=(syn.analysis(4),))['metadata'])
    assert not a._screen(scoped, tagged)['allowed']
    assert a._screen_query(scoped, 'glimmer ' + syn.analysis(4)) is None
    # A versioned restriction also denies the unversioned publication node of the relation graph.
    assert {'arxiv:' + syn.arxiv(6), 'arxiv:' + syn.arxiv(6) + 'v2'} <= a._graph_denials(rows)


def test_malformed_provider_metadata_is_unknown_never_a_crash():
    metadata = {'control_number': 9110, 'titles': 'not a list', 'arxiv_eprints': {'value': syn.arxiv(10)},
                'external_system_identifiers': 5, 'references': 'none', 'publication_info': {'year': 2020},
                'report_numbers': [{'value': 7}], 'document_type': 'article'}
    assert a._record_identifiers('9110', metadata)['arxiv'] == [] and a._years(metadata) == []
    assert a._hepdata_rows(metadata) == [] and a._linked_references(metadata) == set()
    universe = {'provider': 'inspire', 'years': {'from': 2010, 'to': None}, 'document_types': ['article']}
    assert a._outside(metadata, universe) == (None, ['year_unknown', 'document_type_unknown'])
    shown = a._presented({'recid': '9110', 'metadata': metadata}, a.LIMITS)
    assert shown['title'] is None and shown['abstract'] is None and shown['document_type'] is None


# The connected crawl ----------------------------------------------------------------------------

def test_crawl_selects_expands_and_reports_a_complete_population(monkeypatch, campaign):
    base, root, host = campaign()
    calls = routed(monkeypatch, ROUTES)
    out, started = begin(base, root, selector=SELECTOR, graph=fictional_graph())
    assert started['status'] == 'ready' and not calls
    first = a.advance(root, out, host, roles=ROLES)
    assert first['status'] == 'select' and first['batch'] == ['9101', '9102', '9103', '9104', '9107']
    assert [(c['q'], c['page']) for c in calls] == [('recid:9101', '1'), ('glimmer resonance', '1'),
                                                    ('glimmer resonance', '2')]
    request = Path(first['request']['path']).read_text()
    assert WITHHELD_TITLE not in request and '"9106"' not in request and syn.arxiv(6) not in request
    run_selection(monkeypatch, root, host, first, reply_for(first['request'], omit=('9107',)))
    second = a.advance(root, out, host, selection=first['graph_root'], roles=ROLES)
    assert second['status'] == 'select' and second['batch'] == ['9108', '9109']
    expansions = [(c['q'], c['page']) for c in calls[3:]]
    assert expansions == [('refersto:recid:9101', '1'), ('citedby:recid:9101', '1'),
                          ('refersto:recid:9102', '1'), ('citedby:recid:9102', '1'),
                          ('refersto:recid:9103', '1'), ('citedby:recid:9103', '1')]
    run_selection(monkeypatch, root, host, second, reply_for(second['request']))
    done = a.advance(root, out, host, selection=second['graph_root'], roles=ROLES)
    assert done['status'] == 'complete' and len(calls) == 9

    report = json.loads(Path(done['report']['path']).read_text())
    assert a.consume(root, out, roles=ROLES) == report
    raw = Path(done['report']['path']).read_text()
    assert WITHHELD_TITLE not in raw and '"9106"' not in raw and syn.arxiv(6) not in raw
    groups = {k: [e['recid'] for e in v] for k, v in report['population'].items()}
    assert groups == {'demonstrated': ['9101', '9102', '9108'], 'plausible_needs_validation': ['9103'],
                      'unresolved': ['9107'], 'rejected': ['9104', '9109'], 'outside_universe': ['9105']}
    assert report['withheld']['count'] == 1 and list(report['withheld']['by_rule'].values()) == [1]
    assert report['counts']['encountered'] == 9
    entries = by_recid(report)
    assert entries['9103']['reasons'] == ['required_unlocated:channel:field_absent', 'exclusion_uncertain:review']
    assert entries['9107']['reasons'] == ['selector_gave_no_decision']
    assert entries['9109']['reasons'] == ['exclusion_applies:review']
    assert entries['9101']['seed'] and entries['9108']['depth'] == 1
    assert entries['9102']['origins'] == [{'key': 'variant:broad:p1', 'rank': 0}, {'key': 'expand:references:9101:p1', 'rank': 0}]
    assert entries['9102']['preferred_met'] == 1
    abstract = R['9102']['metadata']['abstracts'][0]['value']
    for row in entries['9102']['located']:
        text = R['9102']['metadata']['titles'][0]['title'] if row['field'] == 'title' else abstract
        assert text[row['start']:row['end']] == row['excerpt']
    gaps = {(g['kind'], g.get('key') or g.get('recid')) for g in report['gaps']}
    assert ('unfetched_pages', 'variant:broad:p2') in gaps
    # An unjudged candidate's citations are unexplored too; rejected and outside records are not a gap.
    frontier = {g['recid']: g['reason'] for g in report['gaps'] if g['kind'] == 'frontier_not_expanded'}
    assert frontier == {'9107': 'not_judged', '9108': 'depth_limit'}
    assert 'per-rule counts' in report['definitions']['withheld']
    universe = report['search_universe']
    assert universe['lower_bound'] and universe['first_request_at'] and len(universe['queries']) == 9
    assert {(d['kind'], d['recid']) for d in universe['disagreements']} == {
        ('citation_count', '9101'), ('reference_count', '9102'), }
    follow = {f['recid']: f['candidates'] for f in report['follow_up']}
    assert set(follow) == {'9101', '9102', '9103', '9108'}
    assert {'kind': 'hepdata-record', 'status': 'candidate', 'ref': 'ins9102', 'basis': 'provider-listed',
            'pointer': '/metadata/external_system_identifiers/0',
            'lookup_url': 'https://www.hepdata.net/record/ins9102?format=json'} in follow['9102']
    assert any(c['kind'] == 'implementation' and c['status'] == 'candidate' for c in follow['9102'])
    assert any(c['status'] == 'no_graph_match' for c in follow['9101'])
    assert report['usage'] == {'requests': 9, 'expansions': 6, 'selection_calls': 2}
    assert not any(report['claims'].values()) and report['primary_source_required']
    _, state = cycle._load(root)
    assert len(state['graphs']) == 11 and sum(g['usage']['calls'] for g in state['graphs']) == 11
    assert a.advance(root, out, host, roles=ROLES) == done
    assert a.status(root, out, roles=ROLES)['status'] == 'complete'


def test_without_a_selector_the_crawl_is_deterministic_and_expands_seeds_only(monkeypatch, campaign):
    base, root, host = campaign()
    calls = routed(monkeypatch, ROUTES)
    out, _ = begin(base, root)
    done = a.advance(root, out, host, roles=ROLES)
    assert done['status'] == 'complete'
    assert [c['q'] for c in calls[3:]] == ['refersto:recid:9101', 'citedby:recid:9101']
    report = a.consume(root, out, roles=ROLES)
    assert not report['population']['demonstrated'] and not report['population']['plausible_needs_validation']
    assert {tuple(e['reasons']) for e in report['population']['unresolved']} == {('selector_disabled',)}
    assert report['selection']['calls'] == [] and report['follow_up'] == []
    frontier = {g['recid']: g['reason'] for g in report['gaps'] if g['kind'] == 'frontier_not_expanded'}
    assert frontier == {'9102': 'not_judged', '9103': 'not_judged', '9104': 'not_judged', '9107': 'not_judged',
                        '9108': 'depth_limit', '9109': 'depth_limit'}
    _, state = cycle._load(root)
    assert sum(g['usage']['calls'] for g in state['graphs']) == len(calls) == 5


# Refusals, halts and budgets ---------------------------------------------------------------------

def test_unexecuted_or_uncharged_selection_is_refused_and_stops_selection(monkeypatch, campaign):
    base, root, host = campaign()
    routed(monkeypatch, ROUTES)
    out, _ = begin(base, root, selector=SELECTOR)
    step = a.advance(root, out, host, roles=ROLES)
    with pytest.raises(ValueError, match='declared root'):
        a.advance(root, out, host, selection=str(out / 'elsewhere'), roles=ROLES)
    with pytest.raises(ValueError, match='never created'):
        a.advance(root, out, host, selection=step['graph_root'], roles=ROLES)
    with pytest.raises(ValueError, match='no selector call'):
        a.advance(root, a.start(root, write(base / 'other.json', scope()), root / 'idle', roles=ROLES) and root / 'idle',
                  host, decline='Nothing is pending.', roles=ROLES)
    # Executed outside the campaign: a model reply that was never charged is not admitted.
    monkeypatch.setattr(host, '_responses', lambda data, parameters, request, control: host._result(
        reply_for(step['request']), parameters, request, observed_model='explicit-inert-fixture',
        usage={'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}))
    agent_graph.create(Path(step['graph_root']), step['graph_spec'])
    agent_graph.execute(Path(step['graph_root']), host)
    assert a.admit(root, step['request'], step['graph_root'], SELECTOR, roles=ROLES)['reason'] == 'not_charged'
    done = a.advance(root, out, host, selection=step['graph_root'], roles=ROLES)
    report = a.consume(root, out, roles=ROLES)
    assert done['status'] == 'complete' and not report['population']['demonstrated']
    reasons = {e['recid']: e['reasons'] for e in report['population']['unresolved']}
    assert reasons['9102'] == ['selection_refused:not_charged']
    assert report['selection']['stopped'] == 'stopped_after_selection_refused:not_charged'
    # Seeds stay expandable; refused candidates are not followed.
    assert {q['key'] for q in report['search_universe']['queries'] if q['purpose']['kind'] == 'expansion'} == {
        'expand:cited_by:9101:p1', 'expand:references:9101:p1'}


def test_altered_card_or_reply_is_refused_and_a_decline_is_recorded(monkeypatch, campaign):
    base, root, host = campaign()
    routed(monkeypatch, ROUTES)
    out, _ = begin(base, root, selector=SELECTOR)
    step = a.advance(root, out, host, roles=ROLES)
    reply = reply_for(step['request'])
    reply['decisions'].append(deepcopy(reply['decisions'][0]))
    run_selection(monkeypatch, root, host, step, reply)
    assert a.admit(root, step['request'], step['graph_root'], SELECTOR, roles=ROLES)['reason'] == 'invalid_choice'
    drifted = {'aliases': {}, 'roles': {a.ROLE: {'card': {'id': a.ROLE, 'protocol': ['A changed protocol.']}}}}
    assert a.admit(root, step['request'], step['graph_root'], SELECTOR, roles=drifted)['reason'] == 'graph_spec_mismatch'
    assert a.admit(root, step['request'], step['graph_root'], {**SELECTOR, 'model': 'other'},
                   roles=ROLES)['reason'] == 'graph_spec_mismatch'
    done = a.advance(root, out, host, decline='No selector transport is qualified for this campaign.', roles=ROLES)
    report = a.consume(root, out, roles=ROLES)
    assert done['status'] == 'complete'
    assert report['selection']['calls'][0]['status'] == 'declined'
    assert by_recid(report)['9103']['reasons'][0].startswith('selection_declined:')


def test_exhausted_campaign_budget_halts_with_a_qualified_report_and_no_retry(monkeypatch, campaign):
    base, root, host = campaign(calls=2)
    calls = routed(monkeypatch, ROUTES)
    out, _ = begin(base, root, selector=SELECTOR)
    done = a.advance(root, out, host, roles=ROLES)
    assert done['status'] == 'halted' and len(calls) == 2
    report = a.consume(root, out, roles=ROLES)
    assert 'ceiling exhausted' in report['halt_reason']
    assert ('request_failed', 'variant:broad:p2') in {(g['kind'], g.get('key')) for g in report['gaps']}
    assert {tuple(e['reasons']) for e in report['population']['unresolved']} == {('halted_before_selection',)}
    assert a.advance(root, out, host, roles=ROLES) == done and len(calls) == 2


def test_a_failed_provider_page_is_a_gap_and_the_crawl_continues(monkeypatch, campaign):
    base, root, host = campaign()
    calls = routed(monkeypatch, {k: v for k, v in ROUTES.items() if k[0] != 'glimmer resonance'}, missing=503)
    out, _ = begin(base, root)
    assert a.advance(root, out, host, roles=ROLES)['status'] == 'complete'
    report = a.consume(root, out, roles=ROLES)
    assert ('request_failed', 'variant:broad:p1') in {(g['kind'], g.get('key')) for g in report['gaps']}
    assert len(calls) == 4 and report['status'] == 'complete'


def test_budgets_caps_and_withheld_queries_become_explicit_gaps(monkeypatch, campaign):
    base, root, host = campaign()
    calls = routed(monkeypatch, ROUTES)
    value = scope(queries=[{'id': 'broad', 'text': 'glimmer resonance'}, {'id': 'named', 'text': 'eprint ' + syn.arxiv(6)},
                           {'id': 'spare', 'text': 'quuxon pairs'}],
                  seeds=['9101', '9106'], limits={'page_size': 4, 'max_pages': 2, 'max_variants': 2,
                                                   'max_candidates': 3, 'max_expansions': 1})
    value['source_restrictions'][0]['identifiers']['inspire'] = ['ins9106']
    out, _ = begin(base, root, value)
    assert a.advance(root, out, host, roles=ROLES)['status'] == 'complete'
    assert not any('9106' in str(c['q']) or syn.arxiv(6) in str(c['q']) for c in calls)
    report = a.consume(root, out, roles=ROLES)
    kinds = {(g['kind'], g.get('key') or g.get('variant')) for g in report['gaps']}
    assert {('query_withheld', 'variant:named:p1'), ('variant_budget', 'spare'),
            ('budget_exhausted', 'expand:references:9101:p1')} <= kinds
    assert ('seeds_withheld', None) in kinds and report['counts']['withheld_seeds'] == 1
    assert '"9106"' not in json.dumps(report['gaps']) and '"ins9106"' not in json.dumps(report['gaps'])
    capped = [e['recid'] for e in report['population']['unresolved'] if e['reasons'] == ['candidate_cap']]
    assert capped == ['9104', '9105', '9107', '9108'] and len(report['population']['unresolved']) - len(capped) == 3


def test_interrupted_request_is_adopted_on_resume_and_never_repeated(monkeypatch, campaign):
    base, root, host = campaign()
    calls = routed(monkeypatch, ROUTES)
    out, _ = begin(base, root)
    real = a._append

    def crash(out_dir, steps, head, event):
        if event['type'] == 'request':
            raise KeyboardInterrupt('simulated interruption after the charged request')
        return real(out_dir, steps, head, event)
    monkeypatch.setattr(a, '_append', crash)
    with pytest.raises(KeyboardInterrupt):
        a.advance(root, out, host, roles=ROLES)
    monkeypatch.setattr(a, '_append', real)
    assert len(calls) == 1
    assert a.advance(root, out, host, roles=ROLES)['status'] == 'complete'
    steps, _ = a._steps(out)
    first = steps[1]['event']
    assert first['type'] == 'request' and first['recovered'] and first['product'] is not None
    assert [c['q'] for c in calls].count('recid:9101') == 1


def test_tampered_ledger_or_report_is_refused(monkeypatch, campaign):
    base, root, host = campaign()
    routed(monkeypatch, ROUTES)
    out, _ = begin(base, root)
    done = a.advance(root, out, host, roles=ROLES)
    report = Path(done['report']['path'])
    original = report.read_bytes()
    report.write_bytes(original.replace(b'"complete"', b'"completed"', 1))
    with pytest.raises(ValueError, match='differs'):
        a.consume(root, out, roles=ROLES)
    report.write_bytes(original)
    step = out / 'ledger' / '0001.json'
    value = json.loads(step.read_text()); value['event']['query'] = 'something else'
    step.write_bytes(lc._raw(value))
    with pytest.raises(ValueError, match='chain|plan'):
        a.consume(root, out, roles=ROLES)
    with pytest.raises(ValueError):
        a.start(root, write(base / 'again.json', scope()), out, roles=ROLES)
