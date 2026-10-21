"""Offline controls for graph-scoped search and its rescue; all inputs are fictional.

A real local index is built with fake embedding/reranking adapters and a real
exact-identifier graph. No network, model service or scientific job runs, and
no scientific validity is claimed.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import synthetic_identifiers as syn
from ravel.workflow import literature_build as store
from ravel.workflow import literature_graph_retrieval as retrieval
from ravel.workflow import literature_index as index
from ravel.workflow import literature_provider as contract
from ravel.workflow.literature_relations import (
    GraphQuery, RetrievalDocumentBinding, RetrievalSourceBinding, SourceDocument, build_graph, digest,
)


FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures/literature_provider'
TEXTS = {
    'a': ['amber flux in the first selection.', 'amber notes on the first selection.'],
    'b': ['amber flux in the second selection.'],
    'c': ['amber flux amber flux beyond the navigation metadata.'],
    'd': ['unrelated grey background text.'],
}
QUERY = GraphQuery('related_papers', 'inspire:9901')


def fixture_case(operation):
    cases = json.loads((FIXTURES / 'conformance.json').read_text())
    return next(c for c in cases if c['request']['operation'] == operation)


def descriptor(name, *, kind='source', receipt=None):
    return {'pin': {'path': 'sources/' + name + '.json', 'sha256': 'd' * 64, 'size': 23, 'receipt_id': receipt},
            'identifiers': {'source': [name]}, 'quantities': [], 'classes': ['metadata'], 'kind': kind}


def make_corpus(texts, lineage=None):
    """Source-native rows with exact byte intervals; ``lineage`` maps names to parents."""
    data, raws = dict(schema_version=1, units=[], papers=[], inputs=[]), {}
    for name, paragraphs in sorted(texts.items()):
        document = 'paper:fictional:' + name
        raw = ('Results\n' + ''.join(p + '\n' for p in paragraphs)).encode()
        raws[document] = raw
        paper = fixture_case('get_paper')['candidate']['metadata'][0]
        paper.update(id='metadata:' + name, document_id=document, version='v1', title='Fictional study ' + name,
                     original=dict(path='sources/' + name + '.txt', sha256=hashlib.sha256(raw).hexdigest(),
                                   size=len(raw), receipt_id=None),
                     identifiers={'document': [document]}, quantities=['rate'], classes=['text'],
                     lineage=deepcopy((lineage or {}).get(name, [])))
        data['inputs'].extend(paper['lineage'])
        offset = len(b'Results\n')
        for i, text in enumerate(paragraphs, 1):
            row = fixture_case('search')['candidate']['results'][0]
            for key in ('document_id', 'version', 'original', 'extraction', 'extraction_reason', 'identifiers',
                        'quantities', 'classes', 'lineage', 'acquisition_status', 'extraction_issues',
                        'physics_verified', 'execution_authorized'):
                row[key] = deepcopy(paper[key])
            row.update(id=f'evidence:{name}:{i}', unit_id=f'paragraph:{i}', text=text,
                       excerpt_sha256=hashlib.sha256(text.encode()).hexdigest(), scores=index._scores())
            row['location'].update(byte_start=offset, byte_end=offset + len(text.encode()),
                                   line_start=i + 1, line_end=i + 1)
            offset += len(text.encode()) + 1
            data['units'].append(dict(evidence=row, parent_id=None, section_ids=[], indexed_text=index.indexed_text(
                paper['title'], row['location']['section_path'], text)))
        data['papers'].append(paper)
    return data, raws


class Embedder:
    identity = {'name': 'fictional-embedding', 'revision': '1'}

    def embed_documents(self, texts):
        return [[1.0 + text.count('amber'), 1.0] for text in texts]

    def embed_query(self, query):
        return [1.0, 0.0]


class Reranker:
    """Counts query words, so fictional texts order predictably."""
    identity = {'name': 'fictional-reranker', 'revision': '1'}

    def score(self, query, texts):
        return [sum(text.split().count(word) for word in query.split()) for text in texts]


class Recording:
    """The real provider behind a recorder; ``faults`` apply to successive calls."""

    def __init__(self, inner, faults=()):
        self.provider_id, self.inner, self.calls, self.faults = inner.provider_id, inner, [], list(faults)

    def search(self, request, *, view):
        self.calls.append(deepcopy(request))
        fault = self.faults.pop(0) if self.faults else None
        if isinstance(fault, BaseException):
            raise fault
        result = self.inner.search(request, view=view)
        return fault(result) if callable(fault) else result


def source(name, kind, doc):
    return SourceDocument(name, kind, 'https://example.invalid/' + name, 'snapshot-1', digest(doc), doc, ())


def graph_sources():
    return [
        source('bib-one', 'inspire', {'metadata': {'control_number': 9901,
               'arxiv_eprints': [{'value': syn.arxiv(1) + 'v1'}],
               'references': [{'record': {'$ref': 'https://inspirehep.net/api/literature/9902'}}]}}),
        source('bib-two', 'inspire', {'metadata': {'control_number': 9902}}),
        source('model-list', 'models', {'models': [{'id': 'model-a', 'analysis_ids': ['SEARCH-B']}]}),
    ]


def document_bindings(extra=()):
    return [RetrievalDocumentBinding('inspire:9901', 'paper:fictional:a', 'v1', (descriptor('binding-a'), *extra)),
            RetrievalDocumentBinding('inspire:9902', 'paper:fictional:b', 'v1', (descriptor('binding-b'),)),
            RetrievalDocumentBinding('model:model-a', 'paper:fictional:d', 'v1', (descriptor('binding-d'),))]


def source_view(**kwargs):
    default = dict(policy_sha256='2' * 64, run_id='run:fictional', node_id='node:reader',
                   role='reader', attempt=1, permits=lambda _: True)
    return contract.SourceView(**dict(default, **kwargs))


def setup(tmp_path, texts=TEXTS, *, settings=None, faults=(), lineage=None, bindings=None, clock=lambda: 0.0):
    data, raws = make_corpus(texts, lineage)
    snapshot = store.build_index(tmp_path, data, embedder=Embedder(), reranker_identity=Reranker.identity)
    inner = index.HybridLiteratureProvider(snapshot, embedder=Embedder(), reranker=Reranker(),
                                           cursor_key=b'k' * 32, clock=lambda: 0.0)
    provider, graph = Recording(inner, faults), build_graph(graph_sources())
    sources = [RetrievalSourceBinding(s['id'], s['sha256'], (descriptor(s['id']),)) for s in graph.to_dict()['sources']]
    search = retrieval.GraphGuidedSearch(provider, graph, graph_sha256=graph.sha256, source_bindings=sources,
                                         document_bindings=document_bindings() if bindings is None else bindings,
                                         settings=settings, clock=clock)
    return SimpleNamespace(search=search, provider=provider, inner=inner, raws=raws, graph=graph)


def request(**args):
    req = {'schema_version': 1, 'operation': 'search', 'request_id': 'request:graph',
           'budgets': {'max_tokens': 262144, 'max_bytes': 262144, 'max_seconds': 10.0, 'max_expansions': 200},
           'args': {'query': 'amber flux', 'top_k': 3, 'mode': 'flat', 'document_scope': [], 'filters': {}}}
    for key in [k for k in args if k in req['budgets']]:
        req['budgets'][key] = args.pop(key)
    req['args'].update(args)
    return req


def run(env, req=None, *, view=None, queries=(QUERY,), **kwargs):
    view, req = view or source_view(), req or request()
    identity = env.inner.index_identity(view)
    out = env.search.search(req, view=view, index=identity, queries=list(queries), **kwargs)
    envelope, trace = out['envelope'], out['trace']
    assert contract.validate_candidates(envelope, req, provider_id=env.search.provider_id, index=identity) == envelope
    for row in envelope['results']:
        assert contract.verify_excerpt(row, original=env.raws[row['document_id']])['physics_verified'] is False
    assert [r['id'] for r in envelope['results']] == [r['id'] for r in trace['served']]
    for row, served in zip(envelope['results'], trace['served']):
        assert bool(row['scores']['graph_paths']) == (served['origin'] == 'scope')
    assert trace['physics_verified'] is False and trace['execution_authorized'] is False
    assert contract.canonical(trace) and trace['usage'] == envelope['usage']
    phases = trace['graph']['expansions'] + trace['scope_search']['expansions'] + trace['rescue']['expansions']
    assert phases == envelope['usage']['expansions']
    assert envelope['usage']['expansions'] <= req['budgets']['max_expansions']
    return out


def ids(rows):
    return [row['id'] for row in rows]


def doc(name):
    return {'document_id': 'paper:fictional:' + name, 'version': 'v1'}


@pytest.mark.parametrize('mode', ['flat', 'hybrid'])
def test_scope_ranks_inside_graph_and_reserved_rescue_recovers_a_missing_branch(tmp_path, mode):
    # The best match (c) has no graph binding: incomplete metadata must not erase it.
    env = setup(tmp_path)
    out = run(env, request(mode=mode))
    envelope, trace = out['envelope'], out['trace']
    scoped, rescued = env.provider.calls
    assert scoped['args']['document_scope'] == [doc('a'), doc('b')]
    assert rescued['args']['document_scope'] == [] and rescued['args']['top_k'] == 1 + 3
    oracle = env.inner.search(scoped, view=source_view())['results']
    assert ids(envelope['results']) == ids(oracle)[:2] + ['evidence:c:1']
    assert [s['origin'] for s in trace['served']] == ['scope', 'scope', 'rescue']
    assert trace['rescue']['triggers'] == ['reserved'] and trace['rescue']['coverage'] == 'global'
    assert trace['rescue']['served_outside_scope'] == 1 and trace['rescue']['duplicates'] >= 2
    assert trace['graph']['status'] == 'matched' and trace['graph']['document_scope'] == [doc('a'), doc('b')]
    edges = {e['id'] for e in env.graph.to_dict()['edges']}
    for row in envelope['results'][:2]:
        for path in row['scores']['graph_paths']:
            assert path[0] == 'inspire:9901' and set(path[1:]) <= edges
        # Scoped evidence carries the graph lineage that selected its document.
        assert descriptor('bib-one') in row['lineage']
    assert envelope['results'][2]['lineage'] == [] and envelope['provider_id'] == 'graph-guided/local-hybrid'
    assert envelope['index'] == env.inner.index_identity(source_view())


def test_without_graph_scope_search_equals_the_plain_provider_and_says_so(tmp_path):
    for queries in ((), (GraphQuery('related_papers', 'inspire:9999'),)):
        env = setup(tmp_path / str(len(queries)))
        out = run(env, queries=queries)
        plain = env.inner.search(request(), view=source_view())
        assert out['envelope']['results'] == plain['results']
        assert any(i['code'] == 'missing' and i['id'] == 'graph-scope' for i in out['envelope']['omitted'])
        assert len(env.provider.calls) == 1 and env.provider.calls[0]['args']['document_scope'] == []
        assert out['trace']['graph']['status'] == ('unmatched' if queries else 'not_requested')
        assert out['trace']['rescue']['triggers'] == ['reserved', 'graph_unavailable']
        assert out['trace']['scope_search']['status'] == 'not_run'


def test_insufficient_policy_runs_rescue_only_on_an_observable_trigger(tmp_path):
    env = setup(tmp_path, settings={'rescue_trigger': 'insufficient'})
    full = run(env, request(top_k=2))
    assert len(env.provider.calls) == 1 and full['trace']['rescue']['status'] == 'not_triggered'
    assert full['trace']['rescue']['triggers'] == [] and len(full['envelope']['results']) == 2
    under = run(env, request(top_k=5))
    assert under['trace']['rescue']['triggers'] == ['scoped_underfilled']
    assert ids(under['envelope']['results'])[3:] == ['evidence:c:1', 'evidence:d:1']
    assert under['trace']['rescue']['served_outside_scope'] == 2


def test_caller_scope_is_never_widened_and_rescue_takes_its_exact_complement(tmp_path):
    env = setup(tmp_path)
    out = run(env, request(document_scope=[doc('a'), doc('c')]))
    assert [c['args']['document_scope'] for c in env.provider.calls] == [[doc('a')], [doc('c')]]
    assert {r['document_id'] for r in out['envelope']['results']} == {'paper:fictional:a', 'paper:fictional:c'}
    assert out['trace']['rescue']['coverage'] == 'complement'
    inside = run(env, request(document_scope=[doc('a')]))
    assert inside['trace']['rescue']['status'] == 'no_outside_population'
    assert len(env.provider.calls) == 3


def test_source_view_applies_before_ranking_in_both_searches(tmp_path):
    hidden = 'paper:fictional:c'
    env = setup(tmp_path / 'view')
    view = source_view(permits=lambda d: hidden not in d['identifiers'].get('document', []))
    out = run(env, view=view)
    removed = setup(tmp_path / 'removed', {k: v for k, v in TEXTS.items() if k != 'c'})
    assert out['envelope']['results'] == run(removed)['envelope']['results']
    assert hidden not in json.dumps(out)


def test_withheld_graph_source_or_binding_cannot_shape_the_scope(tmp_path):
    env = setup(tmp_path)
    for name in ('bib-two', 'binding-b'):
        view = source_view(permits=lambda d, name=name: name not in d['identifiers'].get('source', []))
        out = run(env, view=view)
        assert out['trace']['graph']['document_scope'] == [doc('a')]
        assert name not in json.dumps(out)
        b_rows = [s for s in out['trace']['served'] if s['id'].startswith('evidence:b')]
        assert all(s['origin'] == 'rescue' and not s['in_graph_scope'] for s in b_rows)


def test_multiple_typed_queries_union_their_scopes(tmp_path):
    env = setup(tmp_path)
    out = run(env, queries=(QUERY, GraphQuery('models', 'analysis:SEARCH-B')))
    assert env.provider.calls[0]['args']['document_scope'] == [doc('a'), doc('b'), doc('d')]
    assert [q['status'] for q in out['trace']['graph']['queries']] == ['matched', 'matched']
    with pytest.raises(ValueError, match='bounded typed graph query'):
        run(env, queries=(QUERY,) * (retrieval.MAX_QUERIES + 1))
    with pytest.raises(ValueError, match='typed graph queries'):
        run(env, queries=('MATCH (n) RETURN n',))


def test_expansion_and_time_reserves_belong_to_the_rescue(tmp_path):
    env = setup(tmp_path)
    out = run(env, request(max_expansions=40, max_seconds=8.0))
    graph = sum(q['expansions'] for q in out['trace']['graph']['queries'])
    scoped, rescued = env.provider.calls
    assert scoped['budgets']['max_expansions'] == 40 - 10 - graph and scoped['budgets']['max_seconds'] == 6.0
    assert out['trace']['scope_search']['expansion_cap'] == 40 - 10 - graph
    assert rescued['budgets']['max_seconds'] == 8.0
    assert rescued['budgets']['max_expansions'] >= 10
    assert out['envelope']['usage']['expansions'] <= 40


def test_wall_time_is_charged_per_phase_and_the_request_deadline_is_final(tmp_path):
    now = [0.0]

    def advance(to):
        def fault(result):
            now[0] = to
            return result
        return fault
    env = setup(tmp_path / 'charged', faults=[advance(5.0), advance(7.0)], clock=lambda: now[0])
    out = run(env)
    assert [c['budgets']['max_seconds'] for c in env.provider.calls] == [7.5, 5.0]
    assert out['trace']['scope_search']['elapsed_seconds'] == 5.0 and out['trace']['rescue']['elapsed_seconds'] == 2.0
    assert out['envelope']['usage']['elapsed_seconds'] == 7.0
    now[0] = 0.0
    late = setup(tmp_path / 'late', faults=[None, advance(10.5)], clock=lambda: now[0])
    with pytest.raises(TimeoutError):
        run(late)


def test_graph_budget_exhaustion_still_leaves_a_rescue(tmp_path):
    env = setup(tmp_path)
    out = run(env, request(max_expansions=2))
    assert {'graph_budget', 'graph_unavailable'} <= set(out['trace']['rescue']['triggers'])
    assert out['trace']['rescue']['status'] == 'completed' and len(out['envelope']['results']) == 1
    assert out['envelope']['usage']['expansions'] == 2


def test_scoped_timeout_is_recorded_and_the_rescue_uses_its_reserve(tmp_path):
    env = setup(tmp_path, faults=[TimeoutError('slow')])
    out = run(env)
    trace, envelope = out['trace'], out['envelope']
    assert trace['scope_search']['status'] == 'timeout' and 'scoped_timeout' in trace['rescue']['triggers']
    assert {'code': 'timeout', 'id': 'scope', 'reason': envelope['failures'][0]['reason']} in envelope['failures']
    assert trace['rescue']['coverage'] == 'global' and len(envelope['results']) == 3
    assert {s['origin'] for s in trace['served']} == {'rescue'}
    assert any(s['in_graph_scope'] for s in trace['served'])


def test_provider_errors_and_identity_changes_are_never_converted_to_a_rescue(tmp_path):
    def other_index(result):
        return dict(result, index=dict(result['index'], id='index:other'))

    def changed(result):
        result = deepcopy(result)
        result['results'][-1]['extraction_issues'] = ['changed between searches']
        return result

    for faults, message in (([ValueError('policy refusal')], 'policy refusal'),
                            ([other_index], 'identity changed'), ([None, changed], 'identity changed')):
        env = setup(tmp_path / message.replace(' ', '-') / str(len(faults)), faults=faults)
        with pytest.raises(ValueError, match=message):
            run(env)
        assert len(env.provider.calls) == len(faults)


def test_view_change_between_searches_is_refused(tmp_path):
    env = setup(tmp_path)

    def permits(descriptor):
        if descriptor['identifiers'].get('document') == ['paper:fictional:a']:
            return len(env.provider.calls) < 2
        return True
    with pytest.raises(ValueError, match='view changed'):
        run(env, view=source_view(permits=permits))


def test_byte_allocation_keeps_the_rescue_share_while_omitting_whole_rows(tmp_path):
    env = setup(tmp_path)
    full = run(env)['envelope']
    issue = retrieval._issue('budget', 'graph-guided', 'Whole evidence omitted to fit the complete envelope '
                             'within the scope and rescue shares.')
    cap = (len(contract.canonical(full)) - len(contract.canonical(full['results'][1])) - 1
           + len(contract.canonical(issue)) + 1 + 16)
    out = run(env, request(max_bytes=cap, max_tokens=cap))
    assert ids(out['envelope']['results']) == [full['results'][0]['id'], 'evidence:c:1']
    assert issue in out['envelope']['omitted'] and out['trace']['budget_omissions'] == 1
    assert len(contract.canonical(out['envelope'])) <= cap


def test_overlong_combined_lineage_is_left_to_the_rescue_not_truncated(tmp_path):
    parents = [descriptor(f'parent-{i}') for i in range(10)]
    extra = tuple(descriptor(f'roster-{i}') for i in range(58))
    env = setup(tmp_path, lineage={'a': parents}, bindings=document_bindings(extra))
    view = source_view(permits=lambda d: 'paper:fictional:c' not in d['identifiers'].get('document', []))
    out = run(env, request(top_k=4), view=view)
    assert out['trace']['scope_search']['lineage_overflow'] == 2
    # Rescue capacity goes first to evidence outside the graph scope.
    assert ids(out['envelope']['results']) == ['evidence:b:1', 'evidence:d:1', 'evidence:a:1', 'evidence:a:2']
    assert 'lineage_overflow' in out['trace']['rescue']['triggers']
    assert any(i['code'] == 'unsupported' and i['id'] == 'graph-scope' for i in out['envelope']['omitted'])
    for row in out['envelope']['results']:
        assert len(row['lineage']) <= 64
        if row['document_id'] == 'paper:fictional:a':
            assert row['lineage'] == parents and row['scores']['graph_paths'] == []


def test_unsupported_mode_is_disclosed_by_both_searches(tmp_path):
    env = setup(tmp_path)
    out = run(env, request(mode='tree'))
    assert out['envelope']['results'] == []
    assert {i['id'] for i in out['envelope']['omitted'] if i['code'] == 'unsupported'} == {
        'scope:retrieval', 'rescue:retrieval'}


def test_repeat_is_deterministic_and_batch_measures_the_rescue(tmp_path):
    env = setup(tmp_path)
    first, second = run(env), run(env)
    assert first == second
    unscoped = run(env, queries=())
    total = retrieval.summarize([first['trace'], second['trace'], unscoped['trace']])
    assert total['searches'] == 3 and total['graph_matched'] == 2 and total['scoped_completed'] == 2
    assert total['triggers']['reserved'] == 3 and total['triggers']['graph_unavailable'] == 1
    assert total['served_scope'] == 4 and total['served_rescue'] == 5
    assert total['served_rescue_outside_scope'] == 2 + 3 - sum(
        s['in_graph_scope'] for s in unscoped['trace']['served'])
    assert total['rescue_status'] == {'completed': 3}
    with pytest.raises(ValueError):
        retrieval.summarize([{'kind': 'other'}])


def test_receipt_binds_the_denials_and_bindings_that_shape_the_scope(tmp_path):
    # Replay must never confuse two different results under one receipt.
    env = setup(tmp_path)
    plain = run(env)
    denied = run(env, denied_sources=frozenset({'bib-two'}))
    hidden = run(env, denied_identifiers=frozenset({'inspire:9902'}))
    rebound = retrieval.GraphGuidedSearch(env.provider, env.graph, graph_sha256=env.graph.sha256,
                                          source_bindings=env.search._sources, document_bindings=document_bindings()[:1])
    view = source_view()
    other = rebound.search(request(), view=view, index=env.inner.index_identity(view), queries=[QUERY])
    for out in (denied, hidden, other):
        assert out['trace']['graph']['document_scope'] == [doc('a')]
    receipts = [out['envelope']['receipt_id'] for out in (plain, denied, hidden, other)]
    assert len(set(receipts)) == 4 and [out['trace']['receipt_id'] for out in (plain, denied)] == receipts[:2]
    assert other['trace']['bindings_sha256'] != plain['trace']['bindings_sha256']
    assert 'bib-two' not in json.dumps(denied) and 'inspire:9902' not in json.dumps(hidden)


@pytest.mark.parametrize('top_k,fraction,slots', [(1, 0.5, 0), (2, 0.25, 1), (3, 0.25, 1),
                                                  (10, 0.25, 2), (4, 0.5, 2), (512, 0.5, 256)])
def test_rescue_slot_law(top_k, fraction, slots):
    assert retrieval.rescue_slots(top_k, fraction) == slots


@pytest.mark.parametrize('settings', [{'unknown': 1}, {'rescue_fraction': 0}, {'rescue_fraction': 0.75},
                                      {'rescue_fraction': float('nan')}, {'rescue_trigger': 'never'},
                                      {'max_paths_per_result': 0}, {'max_paths_per_result': True}, []])
def test_settings_cannot_remove_or_oversize_the_reserve(settings):
    with pytest.raises(ValueError):
        retrieval.normalize_settings(settings)


def test_untrusted_configuration_and_requests_are_refused(tmp_path):
    env = setup(tmp_path)
    graph, view = env.graph, source_view()
    with pytest.raises(ValueError, match='pinned generation'):
        retrieval.GraphGuidedSearch(env.provider, graph, graph_sha256='0' * 64, source_bindings=[], document_bindings=[])
    with pytest.raises(ValueError, match='trusted retrieval provider'):
        retrieval.GraphGuidedSearch(object(), graph, graph_sha256=graph.sha256, source_bindings=[], document_bindings=[])
    with pytest.raises(ValueError, match='explicit retrieval bindings'):
        retrieval.GraphGuidedSearch(env.provider, graph, graph_sha256=graph.sha256, source_bindings=[object()],
                                    document_bindings=[])
    listing = fixture_case('list_papers')['request']
    with pytest.raises(ValueError, match='only for search'):
        env.search.search(listing, view=view, index=env.inner.index_identity(view))
    with pytest.raises(ValueError, match='policy view changed'):
        env.search.search(request(), view=view, index=dict(env.inner.index_identity(view), policy_view_sha256='3' * 64))

    def with_metadata(result):
        result = deepcopy(result)
        result['metadata'] = [fixture_case('get_paper')['candidate']['metadata'][0]]
        result['metadata'][0].update(document_id='paper:fictional:a', version='v1')
        result['results'] = result['results'][:1]
        return result
    refusing = setup(tmp_path / 'metadata', faults=[with_metadata])
    with pytest.raises(ValueError, match='evidence-only'):
        run(refusing)


# ---- the qualified trusted serving profile

class Served:
    """The real provider with its index identity; records each search scope and can fault."""

    def __init__(self, inner):
        self.inner, self.provider_id, self.calls, self.faults = inner, inner.provider_id, [], []

    def index_identity(self, view):
        return self.inner.index_identity(view)

    def search(self, request, *, view):
        self.calls.append(deepcopy(request['args']['document_scope']))
        if self.faults:
            raise self.faults.pop(0)
        return self.inner.search(request, view=view)

    def get_paper(self, request, *, view):
        self.calls.append('get_paper')
        return self.inner.get_paper(request, view=view)

    def list_papers(self, request, *, view):
        return self.inner.list_papers(request, view=view)

    def compare_measurements(self, request, *, view):
        return self.inner.compare_measurements(request, view=view)


class Unindexed(Served):
    index_identity = None


def serving_world(base, name, *, restrictions=(), graph_extra=(), provider=Served, view=None, qualify_as=None):
    from ravel.workflow import broker as core, knowledge_broker, literature_serving as serving
    root = base / name
    data, raws = make_corpus(TEXTS)
    for document, raw in raws.items():
        target = root / 'corpus/sources' / (document.rsplit(':', 1)[1] + '.txt')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    snapshot = store.build_index(root / 'index', data, embedder=Embedder(), reranker_identity=Reranker.identity)
    inner = provider(index.HybridLiteratureProvider(snapshot, embedder=Embedder(), reranker=Reranker(),
                                                    cursor_key=b'k' * 32, clock=lambda: 0.0))
    graph = build_graph(graph_sources() + list(graph_extra))
    sources = [RetrievalSourceBinding(s['id'], s['sha256'], (descriptor(s['id']),)) for s in graph.to_dict()['sources']]
    bindings = document_bindings()
    run = root / 'run'
    (run / 'inputs').mkdir(parents=True)
    (run / 'inputs/task_contract.json').write_text(json.dumps({'forbidden_sources': list(restrictions)}))
    workspace = core.work_root(run) / 'reader' / '1'
    for part in ('inputs', 'outputs', 'scratch', 'calls'):
        (workspace / part).mkdir(parents=True)
    broker = knowledge_broker.create(run, workspace, role='literature-scout', node_id='reader', attempt=1,
                                     allowed_actions=[serving.ACTION], max_calls=40)
    manifest = snapshot['manifest']
    pins = retrieval.GraphGuidedSearch(inner, graph, graph_sha256=graph.sha256, source_bindings=sources,
                                       document_bindings=bindings)
    profile = serving.graph_profile(
        inner, graph, index={'id': manifest['id'], 'manifest_sha256': manifest['manifest_sha256']},
        graph_sha256=graph.sha256, bindings_sha256=pins._bindings_sha256, source_bindings=sources,
        document_bindings=bindings, view=view or serving.source_view(broker, snapshot), clock=lambda: 0.0)
    record = serving.qualify(qualify_as or profile, snapshot)
    configuration = serving.Serving(profile, snapshot=snapshot, qualification=record, source_root=root / 'corpus',
                                    index_root=root / 'index')
    serving.register(broker, configuration)
    return SimpleNamespace(broker=broker, run=run, inner=inner, profile=profile, snapshot=snapshot, root=root,
                           data=data, sources=sources, bindings=bindings, graph=graph, configuration=configuration)


def typed(identifier='inspire:9901', **changes):
    return dict({'operation': 'related_papers', 'identifier': identifier, 'max_expansions': 50,
                 'max_bytes': 16384}, **changes)


def search_args(**changes):
    return dict({'query': 'amber flux', 'top_k': 3, 'mode': 'flat', 'document_scope': [], 'filters': {},
                 'graph_queries': [typed()]}, **changes)


def test_graph_search_served_through_the_qualified_profile(tmp_path, monkeypatch):
    from ravel.workflow import broker as core, literature_serving as serving
    base = Path(os.path.realpath(tmp_path))
    monkeypatch.setenv('RAVEL_STATE_DIR', str(base / 'state'))
    w = serving_world(base, 'served')

    # The composed search is not a provider: the serving call shape lacks its trusted inputs.
    guided = retrieval.GraphGuidedSearch(w.inner, w.graph, graph_sha256=w.graph.sha256, source_bindings=w.sources,
                                         document_bindings=w.bindings)
    with pytest.raises(TypeError):
        guided.search(request(), view=source_view())
    assert not w.inner.calls

    reply = serving.call(w.broker, 'search', search_args())
    assert reply['status'] == 'ok', reply
    envelope = json.loads(serving.load(w.run, reply))
    assert envelope['provider_id'] == 'graph-guided/' + w.inner.provider_id
    scoped = [row for row in envelope['results'] if row['scores']['graph_paths']]
    assert {row['document_id'] for row in scoped} <= {'paper:fictional:a', 'paper:fictional:b'} and scoped
    assert all(path[0] == 'inspire:9901' for row in scoped for path in row['scores']['graph_paths'])
    units = {u['evidence']['id']: u['evidence'] for u in w.data['units']}
    # Rows keep their admitted lineage; the graph lineage that selected them stays in custody.
    assert all(row['lineage'] == units[row['id']]['lineage'] for row in envelope['results'])
    assert w.inner.calls[0] == [doc('a'), doc('b')] and w.inner.calls[1] == []
    rows = [row['record'] for row in core.ledger(w.run, serving.LEDGER)]
    admitted, served = rows[-2], rows[-1]
    assert admitted['graph']['graph_sha256'] == w.graph.sha256 == served['graph']['trace']['graph_sha256']
    assert admitted['graph']['bindings_sha256'] == served['graph']['trace']['bindings_sha256']
    assert admitted['graph']['queries'] == [dict(typed(), kind=None, relation_types=[], max_hops=6, max_results=50)]
    assert descriptor('binding-a') in served['graph']['trace']['graph']['lineage']
    assert 'trace' not in json.loads(reply['stdout_tail'])
    # Other operations stay on the inner provider unchanged.
    paper = serving.call(w.broker, 'get_paper', {'document_id': 'paper:fictional:a', 'version': 'v1', 'section': None,
                                                 'page_index': None, 'cursor': None, 'limit': 4})
    assert paper['status'] == 'ok', paper
    assert json.loads(serving.load(w.run, paper))['provider_id'] == w.inner.provider_id
    calls = len(w.inner.calls)
    again = serving.replay(w.broker, json.loads(reply['stdout_tail'])['serving_id'])
    assert again['status'] == 'ok' and again['outputs'] == reply['outputs'], again

    def refused(world, reply, code, calls):
        assert reply['status'] == 'refused' and reply['error']['code'] == code, reply
        assert len(world.inner.calls) == calls, world.inner.calls
        last = core.ledger(world.run, serving.LEDGER)[-1]['record']
        assert last['event'] == 'denied' and last['code'] == code

    calls = len(w.inner.calls)
    # Budget breach: typed queries cannot spend more than the request's own expansions.
    refused(w, serving.call(w.broker, 'search', search_args(graph_queries=[typed(max_expansions=300)])),
            'budget_exceeded', calls)
    refused(w, serving.call(w.broker, 'search', search_args(budgets={
        'max_tokens': 32768, 'max_bytes': 32768, 'max_seconds': 10.0, 'max_expansions': 5000})), 'budget_exceeded', calls)
    refused(w, serving.call(w.broker, 'search', search_args(graph_queries=[typed()] * 9)), 'schema_violation', calls)
    refused(w, serving.call(w.broker, 'search', search_args(graph_queries=[dict(typed(), language='free')])),
            'schema_violation', calls)

    # A scoped-search integrity error is refused; no rescue or other search runs instead.
    w.inner.faults.append(ValueError('fictional index fault'))
    refused(w, serving.call(w.broker, 'search', search_args()), 'provider_failed', calls + 1)
    assert w.inner.calls[-1] == [doc('a'), doc('b')]

    # Missing index: the inner provider cannot name the configured index.
    m = serving_world(base, 'unindexed', provider=Unindexed)
    refused(m, serving.call(m.broker, 'search', search_args()), 'stale_index', 0)

    # Changed graph digest: the qualification pins another generation, and replay pins its own.
    extra = (source('bib-three', 'inspire', {'metadata': {'control_number': 9903}}),)
    g = serving_world(base, 'regraphed', graph_extra=extra)
    other = serving_world(base, 'pinned', graph_extra=())
    stale = serving.Serving(g.profile, snapshot=g.snapshot, qualification=serving.qualify(other.profile, g.snapshot),
                            source_root=g.root / 'corpus', index_root=g.root / 'index')
    g.broker._literature_serving.serving = stale
    refused(g, serving.call(g.broker, 'search', search_args()), 'stale_index', 0)
    regraphed = serving_world(base, 'replayed', graph_extra=extra).profile
    w.broker._literature_serving.serving = serving.Serving(
        regraphed, snapshot=w.snapshot, qualification=serving.qualify(regraphed, w.snapshot),
        source_root=w.root / 'corpus', index_root=w.root / 'index')
    before = len(w.inner.calls)
    # The recorded graph pins are part of the recorded qualification; a new generation is refused before any search.
    assert admitted['graph']['graph_sha256'] != regraphed.pins['graph_sha256']
    replayed = serving.replay(w.broker, json.loads(reply['stdout_tail'])['serving_id'])
    assert replayed['status'] == 'refused' and replayed['error']['code'] == 'provider_unqualified', replayed
    assert len(w.inner.calls) == before

    # Policy change: a profile configured for another source view refuses before any search.
    p = serving_world(base, 'policy', view=source_view(policy_sha256='3' * 64))
    refused(p, serving.call(p.broker, 'search', search_args()), 'policy_changed', 0)

    # A denied source named by a typed query is refused before any search.
    rows = [{'kind': 'forbidden-source', 'statement': 'Withhold the declared fictional source.', 'evidence': [],
             'origin': 'harness', 'paths': ['sources/b.txt']}]
    d = serving_world(base, 'denied', restrictions=rows)
    refused(d, serving.call(d.broker, 'search', search_args(graph_queries=[typed('inspire:9902')])),
            'forbidden_source', 0)

    # Without a qualified graph profile typed queries are not an accepted field.
    plain = serving.Serving(w.inner, snapshot=w.snapshot, qualification=serving.qualify(w.inner, w.snapshot),
                            source_root=w.root / 'corpus', index_root=w.root / 'index')
    w.broker._literature_serving.serving = plain
    calls = len(w.inner.calls)
    refused(w, serving.call(w.broker, 'search', search_args()), 'schema_violation', calls)
    assert serving.call(w.broker, 'search', {k: v for k, v in search_args().items() if k != 'graph_queries'})['status'] == 'ok'
