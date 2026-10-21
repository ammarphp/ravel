"""Corpus plan, exclusion screen, governed acquisition and build admission.

Fictional records only: four-digit provider records and synthetic literature
numbers. Scripted HTTPS answers pass through the REAL campaign, Host, Graph,
acquisition, extraction and location tools; no live network is used.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
import synthetic_identifiers as syn

from ravel.validation import check_agent_paths
from ravel.workflow import agent_host, literature_context as lc, literature_corpus as corpus
from ravel.workflow import literature_index, research_cycle as cycle, research_tools as tools
from test_research_cycle import contract, write
from test_literature_context import two_page_pdf

ORIGIN = 'https://papers.example.org'
BY = {'statement': 'CC BY 4.0', 'url': 'https://creativecommons.org/licenses/by/4.0/'}
DEFAULT = {'statement': 'Default distribution licence', 'url': 'http://arxiv.org/licenses/nonexclusive-distrib/1.0/'}


@pytest.fixture(autouse=True)
def refuse_real_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('a software control cannot make an external acquisition')
    monkeypatch.setattr(lc.http.client, 'HTTPSConnection', refuse)
    monkeypatch.setattr(lc.socket, 'getaddrinfo', refuse)


def document(i, **updates):
    number = syn.arxiv(600 + i)
    value = {'id': 'doc-' + str(i), 'title': 'Fictional search number ' + str(i), 'identifiers': {
                 'inspire': [str(9100 + i)], 'arxiv': [number], 'doi': ['10.9999/fictional.' + str(i)]},
             'version': number + 'v2',
             'source': {'url': ORIGIN + '/pdf/' + number + 'v2', 'format': 'pdf', 'sha256': None},
             'source_reason': None, 'terms': corpus.terms(BY, 'Provider metadata field /metadata/license/0'),
             'metadata': {'response': 'page-one', 'pointer': '/hits/hits/' + str(i)},
             'references': {'status': 'provider-list', 'inspire': ['9001']}, 'labels': ['family-fictional']}
    value.update(updates)
    return value


def plan(base, documents, **updates):
    response = write(base / 'responses' / 'page-one.json', {'hits': {'hits': [], 'total': 0}})
    value = {'schema_version': 1, 'kind': 'literature-corpus-plan', 'id': 'fictional-plan',
             'statement': 'Fictional corpus for software controls.',
             'selection': {'provider': 'inspire', 'retrieved_utc': '2026-01-01T00:00:00Z',
                           'criteria': [{'id': 'fictional', 'statement': 'Every fictional record.'}],
                           'responses': [{'id': 'page-one', 'url': ORIGIN + '/api?q=fictional', 'purpose': 'Selection page.',
                                          'response': {**response, 'path': 'responses/page-one.json'}}],
                           'order': 'Provider order.', 'target_size': 10},
             'origins': [{'origin': ORIGIN, 'min_interval_seconds': 3, 'terms_url': ORIGIN + '/terms'}],
             'service_terms': [{'source': 'fictional-provider', 'url': ORIGIN + '/terms', 'statement': 'Fictional terms.'}],
             'limits': {'max_source_bytes': 200000, 'max_seconds': 20, 'max_pages': 8, 'max_text_bytes': 200000,
                        'documents_per_campaign': 8},
             'screen': None, 'documents': documents}
    value.update(updates)
    return value


def rule(identity, identifiers, **updates):
    value = {'id': identity, 'kind': 'forbidden-source', 'identifiers': identifiers, 'origin': 'harness',
             'statement': 'Fictional restricted source ' + identity + '.', 'evidence': []}
    value.update(updates)
    return value


def exclusion(*rules, cited=True, text=True, unknown='refuse'):
    rules = list(rules) or [rule('restricted', {'inspire': ['9050'], 'arxiv': [syn.arxiv(650)],
                                                 'analysis': [syn.analysis(5)]})]
    named = lambda wanted, key: ([r['id'] for r in rules if corpus._identities(r.get('identifiers', {}))[key]
                                  or (key == 'arxiv' and r.get('identifiers'))] if wanted is True else list(wanted or []))
    return {'schema_version': 1, 'kind': 'literature-corpus-exclusion', 'id': 'fictional-exclusion',
            'statement': 'Restricted fictional records, their data records and any document citing or naming them.',
            'rules': rules, 'closure': {'cited': named(cited, 'inspire'), 'text': named(text, 'arxiv'),
                                        'unknown_references': unknown}, 'evidence': []}


def test_terms_follow_the_recorded_licence_only():
    assert corpus.terms(BY, 'p')['redistribution'] == 'permitted'
    assert corpus.terms({'statement': 'x', 'url': 'http://www.creativecommons.org/licenses/by/4.0/legalcode'}, 'p') == {
        **corpus.terms(BY, 'p'), 'licence': {'statement': 'x', 'url': 'http://www.creativecommons.org/licenses/by/4.0/legalcode'}}
    for licence in (DEFAULT, None, {'statement': 'Custom', 'url': None}, {'statement': 'x', 'url': 'https://example.org/l'}):
        value = corpus.terms(licence, 'p')
        assert value['redistribution'] == value['derivatives'] == 'local-only' and value['attribution']
    nd = corpus.terms({'statement': 'x', 'url': 'https://creativecommons.org/licenses/by-nd/4.0/'}, 'p')
    assert (nd['redistribution'], nd['derivatives']) == ('permitted', 'local-only')
    assert corpus.terms({'statement': 'x', 'url': 'https://creativecommons.org/publicdomain/zero/1.0/'}, 'p')['attribution'] is False


def _mutations():
    def doc(**u): return lambda p: p['documents'][0].update(u)
    return {
        'duplicate-id': lambda p: p['documents'].append(document(0, identifiers={'inspire': ['9199']})),
        'duplicate-identity': lambda p: p['documents'].append(document(1, identifiers={'arxiv': ['arXiv:' + syn.arxiv(600) + 'v1']}, version=None)),
        'data-record-identity': lambda p: p['documents'].append(document(1, identifiers={'hepdata': ['ins9100']}, version=None)),
        'foreign-version': doc(version=syn.arxiv(601) + 'v1'),
        'version-without-source': doc(source=None, source_reason='No original.'),
        'source-and-reason': doc(source_reason='Both.'),
        'neither-source-nor-reason': doc(source=None, version=None),
        'unconfigured-origin': doc(source={'url': 'https://other.example.org/x.pdf', 'format': 'pdf', 'sha256': None}),
        'credential-url': doc(source={'url': ORIGIN + '/x.pdf?token=secret', 'format': 'pdf', 'sha256': None}),
        'plain-http': doc(source={'url': 'http://papers.example.org/x.pdf', 'format': 'pdf', 'sha256': None}),
        'overstated-terms': doc(terms={**corpus.terms(DEFAULT, 'p'), 'redistribution': 'permitted'}),
        'unknown-response': doc(metadata={'response': 'page-two', 'pointer': '/hits/hits/0'}),
        'reserved-label': doc(labels=[corpus.QUERY_TAG]),
        'malformed-recid': doc(identifiers={'inspire': ['0123']}),
        'malformed-arxiv': doc(identifiers={'arxiv': ['not-a-number']}, version=None),
        'empty-identifiers': doc(identifiers={}),
        'unknown-field': doc(abstract='Not stored.'),
        'oversized-source-limit': lambda p: p['limits'].update(max_source_bytes=16 * 1024 * 1024 + 1),
        'campaign-revision-bound': lambda p: p['limits'].update(documents_per_campaign=31),
        'screen-census': lambda p: p.update(screen={'exclusion_sha256': 'a' * 64, 'screened': 1, 'admitted': 1,
                                                     'refused_documents': 0, 'refused': {'r:identity': 1}}),
        'screen-count': lambda p: p.update(screen={'exclusion_sha256': 'a' * 64, 'screened': 3, 'admitted': 1,
                                                    'refused_documents': 1, 'refused': {}}),
        'uncanonical-origin': lambda p: p['origins'][0].update(origin='https://Papers.Example.org'),
    }


@pytest.mark.parametrize('name', sorted(_mutations()))
def test_plan_refusals(tmp_path, name):
    value = plan(tmp_path, [document(0)])
    corpus.validate_plan(deepcopy(value))
    _mutations()[name](value)
    with pytest.raises(ValueError):
        corpus.validate_plan(value)


@pytest.mark.parametrize('identifiers', [
    {'arxiv': ['arXiv:' + syn.arxiv(605) + 'v3']},
    {'arxiv': [syn.arxiv(605).upper()]},
    {'inspire': ['INSPIRE:9105']},
    {'inspire': ['ins9105']},
    {'hepdata': ['ins9105']},
    {'hepdata': ['9105']},
])
def test_identity_screen_meets_every_spelling_and_keeps_only_counts(tmp_path, identifiers):
    value = plan(tmp_path, [document(5), document(6)])
    result = corpus.screen(value, exclusion(rule('restricted', identifiers)))
    assert [d['id'] for d in result['plan']['documents']] == ['doc-6']
    assert result['plan']['screen']['refused'] == {'restricted:identity': 1}
    assert result['refusals'][0]['document']['id'] == 'doc-5'
    admitted = json.dumps(result['plan'])
    assert 'doc-5' not in admitted and syn.arxiv(605) not in admitted and '9105' not in admitted


def test_report_number_spellings_and_title_scan(tmp_path):
    code = syn.analysis(5)
    tokens = code.split('-')
    titles = [code.lower(), ' '.join(tokens), tokens[0] + '-PAS-' + '-'.join(tokens[1:]), 'see ' + code + ' and more']
    documents = [document(i, title='Fictional ' + t) for i, t in enumerate(titles)]
    documents.append(document(9, identifiers={'inspire': ['9109'], 'analysis': [code.lower().replace('-', '_')]}, version=None))
    near = [document(20, title='Fictional ' + code + '1'), document(21, title='Fictional ' + syn.arxiv(650) + '1'),
            document(22, title='Fictional ' + syn.analysis(5, 2))]
    result = corpus.screen(plan(tmp_path, documents + near), exclusion())
    assert sorted(d['id'] for d in result['plan']['documents']) == ['doc-20', 'doc-21', 'doc-22']
    assert result['plan']['screen']['refused'] == {'restricted:identity': 1, 'restricted:text': 4}
    assert result['plan']['screen']['refused_documents'] == 5


def test_text_scan_meets_link_and_registered_identifier_forms(tmp_path):
    number = syn.arxiv(650)
    named = ['see https://arxiv.org/abs/' + number, 'see arxiv.org/pdf/' + number + 'v2',
             'see 10.48550/arXiv.' + number]
    near = ['see https://arxiv.org/abs/' + number + '1', 'see 10.48550/arXiv.' + number + '1']
    documents = [document(i, title='Fictional ' + t) for i, t in enumerate(named + near)]
    result = corpus.screen(plan(tmp_path, documents), exclusion())
    assert sorted(d['id'] for d in result['plan']['documents']) == ['doc-3', 'doc-4']
    assert result['plan']['screen']['refused'] == {'restricted:text': 3}


def test_citation_closure_and_unknown_references(tmp_path):
    cites = document(1, references={'status': 'provider-list', 'inspire': ['9001', '9050']})
    unknown = document(2, references={'status': 'unknown', 'inspire': []})
    data_only = rule('data', {'hepdata': ['ins9050']})
    value = plan(tmp_path, [cites, unknown, document(3)])
    assert corpus.screen(value, exclusion(data_only))['plan']['screen']['refused'] == {
        'closure:unknown-references': 1, 'data:cited': 1}
    assert [d['id'] for d in corpus.screen(value, exclusion(data_only, unknown='admit'))['plan']['documents']] == ['doc-2', 'doc-3']
    assert len(corpus.screen(value, exclusion(data_only, cited=False))['plan']['documents']) == 3
    # An enumerated citing set is an identity rule; its own citers stay admitted unless it is named.
    citing = rule('citing', {'inspire': ['9001']})
    source = rule('source', {'inspire': ['9050']})
    second = plan(tmp_path, [document(3), document(4, references={'status': 'provider-list', 'inspire': ['9050']})])
    result = corpus.screen(second, exclusion(source, citing, cited=['source'], text=False))
    assert [d['id'] for d in result['plan']['documents']] == ['doc-3']
    assert result['plan']['screen']['refused'] == {'source:cited': 1}
    assert corpus.screen(second, exclusion(source, citing, cited=['source', 'citing'], text=False))['plan']['documents'] == []
    for closure in ({'cited': ['absent']}, {'text': ['absent']}, {'cited': ['labelled']}):
        bad = exclusion(source, rule('labelled', {}, classes=['x']), cited=False, text=False)
        bad['closure'].update(closure)
        with pytest.raises(ValueError, match='closure'):
            corpus.validate_exclusion(bad)


def test_scoped_and_class_rules_exclude_whole_documents(tmp_path):
    scoped = rule('scoped', {'inspire': ['9101']}, kind='no-value-extraction', scope={'quantities': ['limit']})
    labelled = rule('labelled', {}, classes=['family-restricted'])
    value = plan(tmp_path, [document(1), document(2, labels=['family-restricted']), document(3)])
    result = corpus.screen(value, exclusion(scoped, labelled))
    assert [d['id'] for d in result['plan']['documents']] == ['doc-3']
    assert result['plan']['screen']['refused'] == {'labelled:identity': 1, 'scoped:identity': 1}


def test_screen_is_idempotent_and_bound_to_its_exclusion_list(tmp_path):
    value = plan(tmp_path, [document(1), document(5, identifiers={'arxiv': [syn.arxiv(650)]}, version=None)])
    first = corpus.screen(value, exclusion())['plan']
    assert first['screen']['screened'] == 2 and first['screen']['admitted'] == 1 and first['screen']['refused_documents'] == 1
    assert corpus.screen(first, exclusion())['plan'] == first
    other = exclusion(rule('other', {'inspire': ['9077']}))
    with pytest.raises(ValueError, match='another exclusion'):
        corpus.screen(first, other)
    with pytest.raises(ValueError):
        corpus.validate_exclusion({**exclusion(), 'rules': [rule('UPPER', {'inspire': ['9050']})]})
    with pytest.raises(ValueError):
        corpus.validate_exclusion(exclusion(rule('bad', {'arxiv': ['not-a-number']})))


def routed(monkeypatch, routes):
    """HTTPS answered by request path; an unknown path is a 404."""
    calls = []

    class Sock:
        def getpeername(self): return ('93.184.216.34', 443)
        def settimeout(self, seconds): assert seconds > 0

    class Response:
        def __init__(self, target):
            self.status, self.body = (200, routes[target]) if target in routes else (404, b'Not found.')
            self.offset = 0
        def getheader(self, key): return {'Content-Length': str(len(self.body))}.get(key)
        def read(self, n):
            part = self.body[self.offset:self.offset + n]; self.offset += len(part); return part

    class Connection:
        def __init__(self, host, port, timeout, context): self.sock = Sock(); self.host = host
        def connect(self): pass
        def request(self, method, target, headers): calls.append(target); self.target = target
        def getresponse(self): self.sock = None; return Response(self.target)
        def close(self): pass

    monkeypatch.setattr(lc.http.client, 'HTTPSConnection', Connection)
    monkeypatch.setattr(lc.socket, 'getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('93.184.216.34', 443))])
    return calls


class Clock:
    def __init__(self): self.now, self.sleeps = 100.0, []
    def __call__(self): return self.now
    def sleep(self, seconds): self.sleeps.append(seconds); self.now += seconds


def campaign(base, budget_calls=20):
    root = base / 'campaign'
    value = contract(base)
    value['budget'] = {**value['budget'], 'calls': budget_calls}
    cycle.create(root, value, base_dir=base, evaluation_harness=True)
    return root, agent_host.AgentHost(timeout_seconds=30, literature_origins=[ORIGIN])


TEXT = 'A fictional located method.\n\nIts results cite arXiv:{} in the references.\n'


def connected(tmp_path, monkeypatch, **limits):
    base = tmp_path.resolve()
    root, host = campaign(base)
    text_doc = document(4, source={'url': ORIGIN + '/text/' + syn.arxiv(604) + 'v2', 'format': 'text', 'sha256': None},
                        terms=corpus.terms(DEFAULT, 'Provider metadata field /metadata/license/0'))
    documents = [document(1), document(2), document(3, source=None, version=None, source_reason='No public original.'), text_doc]
    value = plan(base, documents)
    value['limits'].update(limits)
    admitted = corpus.screen(value, exclusion())['plan']
    plan_pin = write(base / 'plan.json', admitted)
    exclusion_pin = write(base / 'exclusion.json', exclusion())
    calls = routed(monkeypatch, {'/pdf/' + syn.arxiv(601) + 'v2': two_page_pdf(),
                                 '/text/' + syn.arxiv(604) + 'v2': TEXT.format(syn.arxiv(700)).encode()})
    return base, root, host, plan_pin, exclusion_pin, calls


def test_governed_acquisition_keeps_every_outcome_and_paces_requests(tmp_path, monkeypatch):
    base, root, host, plan_pin, exclusion_pin, calls = connected(tmp_path, monkeypatch)
    clock = Clock()
    value = corpus.acquire(plan_pin, exclusion_pin, campaign_root=root, host=host, out=root / 'corpus',
                           sleep=clock.sleep, clock=clock)
    assert calls == ['/pdf/' + syn.arxiv(601) + 'v2', '/pdf/' + syn.arxiv(602) + 'v2', '/text/' + syn.arxiv(604) + 'v2']
    assert clock.sleeps == [3.0, 3.0, 3.0]  # the fake clock stands still, so every request waits one interval
    census = value['census']
    assert census['status'] == {'failed': 1, 'located': 1, 'located-partial': 1, 'unsupported': 1}
    assert census['stage'] == {'acquisition': 2} and census['not_attempted'] == 0
    assert census['redistribution'] == {'local-only': 1, 'permitted': 3}
    assert census['origins'] == {ORIGIN: 3}
    failures = {row['document']: row for row in census['failures']}
    assert failures['doc-2']['reason'].startswith('source HTTP status 404')
    assert failures['doc-3']['reason'] == 'No public original.'
    assert failures['doc-1']['status'] == 'located-partial'
    outcomes = {o['document']['id']: corpus.consume_outcome(pin, base_dir=base) for pin, o in
                zip(value['outcomes'], [json.loads(Path(p['path']).read_text()) for p in value['outcomes']])}
    assert outcomes['doc-2']['product'] is not None and outcomes['doc-3']['acquisition'] is None
    context = lc.consume(outcomes['doc-2']['product'], base_dir=base)['context']
    assert context['documents'][0]['status'] == 'failed' and context['documents'][0]['pin'] is None
    assert any(r['kind'] == 'acquisition' for r in context['missing_and_unresolved'])
    located = lc.consume(outcomes['doc-1']['product'], base_dir=base)['context']
    assert {u['page_index'] for u in located['units'] if u['kind'] == 'page'} == {0, 1}
    assert not any(value['claims'].values())
    # A second run in the same output attempts nothing again.
    again = corpus.acquire(plan_pin, exclusion_pin, campaign_root=root, host=host, out=root / 'corpus',
                           sleep=clock.sleep, clock=clock)
    assert again == value and len(calls) == 3


def test_build_admission_scans_located_text_and_feeds_the_index_compiler(tmp_path, monkeypatch):
    base, root, host, plan_pin, exclusion_pin, _ = connected(tmp_path, monkeypatch)
    clock = Clock()
    value = corpus.acquire(plan_pin, exclusion_pin, campaign_root=root, host=host, out=root / 'corpus',
                           sleep=clock.sleep, clock=clock)
    record_pin = cycle._pin(root / 'corpus' / 'record.json')
    built = corpus.admit_build([record_pin], exclusion_pin, base_dir=base)
    assert {k: v for k, v in built['census'].items() if k != 'acquisition'} == {
        'exclusion_sha256': corpus.digest(exclusion()), 'admitted': 4, 'without_product': 0, 'refused': {},
        'relocated': []}
    assert built['census']['acquisition'] == {**value['census'], 'recorded': 4}
    # A newer build-time list naming a number cited only in the located text refuses that document.
    newer = exclusion(rule('restricted', {'arxiv': [syn.arxiv(700)]}))
    newer_pin = write(base / 'newer-exclusion.json', newer)
    refused = corpus.admit_build([record_pin], newer_pin, base_dir=base)
    assert refused['census']['refused'] == {'restricted:text': 1} and refused['census']['admitted'] == 3
    assert [r['document']['id'] for r in refused['refusals']] == ['doc-4']
    assert 'doc-4' not in json.dumps([refused['products'], refused['bibliography']])
    receipts = {hashlib.sha256(p.read_bytes()).hexdigest(): 'receipt-' + p.name
                for p in base.rglob('*') if p.is_file()}
    compiled = literature_index.corpus_from_products(refused['products'], base_dir=base, receipt_ids=receipts,
                                                     bibliography=refused['bibliography'])
    papers = {p['document_id']: p for p in compiled['papers']}
    assert set(papers) == {'doc-1', 'doc-2', 'doc-3'}
    assert papers['doc-1']['title'] == 'Fictional search number 1'
    assert {papers['doc-2']['acquisition_status'], papers['doc-3']['acquisition_status']} == {'failed', 'unsupported'}
    lineage = [d for d in papers['doc-1']['lineage'] if d['kind'] == 'source' and 'inspire' in d['identifiers']]
    assert lineage and 'ins9101' in lineage[0]['identifiers']['hepdata'] and 'INSPIRE:9101' in lineage[0]['identifiers']['inspire']
    assert any(u['evidence']['document_id'] == 'doc-1' for u in compiled['units'])
    assert value['census']['planned'] == 4


def test_tampered_outcome_record_and_foreign_directory_are_refused(tmp_path, monkeypatch):
    base, root, host, plan_pin, exclusion_pin, _ = connected(tmp_path, monkeypatch)
    clock = Clock()
    corpus.acquire(plan_pin, exclusion_pin, campaign_root=root, host=host, out=root / 'corpus',
                   sleep=clock.sleep, clock=clock)
    record_pin = cycle._pin(root / 'corpus' / 'record.json')
    path = root / 'corpus' / 'doc-2' / 'outcome.json'
    original = path.read_bytes()
    forged = json.loads(original); forged.update(status='located', stage='complete', reason=None)
    path.chmod(0o644); path.write_bytes(lc._raw(forged))
    with pytest.raises(ValueError):
        corpus.consume_outcome(cycle._pin(path), base_dir=base)
    path.write_bytes(original)
    summary = json.loads((root / 'corpus' / 'record.json').read_text())
    summary['census']['status'] = {'located': 4}
    (root / 'corpus' / 'record.json').write_text(json.dumps(summary))
    with pytest.raises(ValueError, match='differs from its recorded outcomes'):
        corpus.admit_build([cycle._pin(root / 'corpus' / 'record.json')], exclusion_pin, base_dir=base)
    (root / 'corpus' / 'doc-99').mkdir()
    with pytest.raises(ValueError, match='outside its plan'):
        corpus.record(plan_pin, exclusion_pin, out=root / 'corpus', base_dir=base)
    assert record_pin


def test_campaign_refusal_defers_and_stops_and_interruptions_are_retained(tmp_path, monkeypatch):
    base, root, host, plan_pin, exclusion_pin, calls = connected(tmp_path, monkeypatch)
    (root / 'corpus' / 'doc-1').mkdir(parents=True)

    def exhausted(*args, **kwargs):
        raise cycle.OperationalBoundaryError('original campaign cannot fit the declared graph branch')
    monkeypatch.setattr(tools, 'acquire_literature', exhausted)
    clock = Clock()
    value = corpus.acquire(plan_pin, exclusion_pin, campaign_root=root, host=host, out=root / 'corpus',
                           sleep=clock.sleep, clock=clock)
    assert value['census']['status'] == {'deferred': 2} and value['census']['not_attempted'] == 2 and not calls
    reasons = [row['reason'] for row in value['census']['failures']]
    assert reasons[0].startswith('Interrupted earlier attempt') and 'OperationalBoundaryError' in reasons[1]


def test_an_unlocatable_original_is_retained_and_the_run_continues(tmp_path, monkeypatch):
    base, root, host, plan_pin, exclusion_pin, calls = connected(tmp_path, monkeypatch)
    original = tools.prepare_literature_context

    def prepare(root_, pin, out, *, reason):
        if 'doc-1' in str(out):
            raise IndexError('fictional segmentation fault in an existing preparation')
        return original(root_, pin, out, reason=reason)
    monkeypatch.setattr(tools, 'prepare_literature_context', prepare)
    clock = Clock()
    value = corpus.acquire(plan_pin, exclusion_pin, campaign_root=root, host=host, out=root / 'corpus',
                           sleep=clock.sleep, clock=clock)
    failures = {row['document']: row for row in value['census']['failures']}
    assert (failures['doc-1']['status'], failures['doc-1']['stage']) == ('failed', 'location')
    assert failures['doc-1']['reason'] == corpus.PARTIAL + ' Location: IndexError: fictional segmentation fault in an existing preparation'
    assert value['census']['recorded'] == 4 and len(calls) == 3
    outcome = json.loads((root / 'corpus' / 'doc-1' / 'outcome.json').read_text())
    assert outcome['extraction'] is not None and outcome['product'] is None
    first_pin = cycle._pin(root / 'corpus' / 'record.json')
    built = corpus.admit_build([first_pin], exclusion_pin, base_dir=base)
    assert built['census']['without_product'] == 1 and built['census']['admitted'] == 3
    # Without relocation a recorded failure is final; with it, only location runs again, over the same receipts.
    monkeypatch.setattr(tools, 'prepare_literature_context', original)
    kept = corpus.acquire(plan_pin, exclusion_pin, campaign_root=root, host=host, out=root / 'kept',
                          previous=[first_pin], sleep=clock.sleep, clock=clock)
    assert kept['outcomes'] == []
    again = corpus.acquire(plan_pin, exclusion_pin, campaign_root=root, host=host, out=root / 'relocated',
                           previous=[first_pin], relocate=True, sleep=clock.sleep, clock=clock)
    assert len(calls) == 3 and again['census']['status'] == {'located-partial': 1}
    relocated = json.loads((root / 'relocated' / 'doc-1' / 'outcome.json').read_text())
    assert [relocated['acquisition'], relocated['extraction']] == [outcome['acquisition'], outcome['extraction']]
    second_pin = cycle._pin(root / 'relocated' / 'record.json')
    merged = corpus.admit_build([first_pin, second_pin], exclusion_pin, base_dir=base)
    assert merged['census']['admitted'] == 4 and merged['census']['relocated'] == ['doc-1']
    assert merged['census']['acquisition']['status'] == {'failed': 1, 'located': 1, 'located-partial': 1, 'unsupported': 1}
    with pytest.raises(ValueError, match='more than one final outcome'):
        corpus.admit_build([second_pin, second_pin], exclusion_pin, base_dir=base)


def test_documents_per_campaign_bounds_each_output(tmp_path, monkeypatch):
    base, root, host, plan_pin, exclusion_pin, calls = connected(tmp_path, monkeypatch, documents_per_campaign=2)
    clock = Clock()
    first = corpus.acquire(plan_pin, exclusion_pin, campaign_root=root, host=host, out=root / 'corpus',
                           sleep=clock.sleep, clock=clock)
    assert first['census']['recorded'] == 2 and first['census']['not_attempted'] == 2
    assert corpus.acquire(plan_pin, exclusion_pin, campaign_root=root, host=host, out=root / 'corpus',
                          sleep=clock.sleep, clock=clock) == first
    first_pin = cycle._pin(root / 'corpus' / 'record.json')
    second = corpus.acquire(plan_pin, exclusion_pin, campaign_root=root, host=host, out=root / 'corpus-2',
                            previous=[first_pin], sleep=clock.sleep, clock=clock)
    assert [o['path'].split('/')[-2] for o in second['outcomes']] == ['doc-3', 'doc-4'] and len(calls) == 3
    second_pin = cycle._pin(root / 'corpus-2' / 'record.json')
    merged = corpus.admit_build([first_pin, second_pin], exclusion_pin, base_dir=base)
    assert merged['census']['admitted'] == 4 and merged['census']['acquisition']['not_attempted'] == 0
    with pytest.raises(ValueError, match='more than one final outcome'):
        corpus.admit_build([first_pin, first_pin], exclusion_pin, base_dir=base)


def test_acquisition_refuses_unscreened_or_differently_screened_plans(tmp_path, monkeypatch):
    base, root, host, plan_pin, exclusion_pin, calls = connected(tmp_path, monkeypatch)
    admitted = json.loads(Path(plan_pin['path']).read_text())
    for name, value in (('unscreened', {**admitted, 'screen': None}),
                        ('smuggled', {**admitted, 'documents': admitted['documents'] + [document(
                            7, identifiers={'arxiv': [syn.arxiv(650)]}, version=None)],
                            'screen': {**admitted['screen'], 'screened': 5, 'admitted': 5}})):
        pin = write(base / (name + '.json'), value)
        with pytest.raises(ValueError, match='admitted|refuses'):
            corpus.acquire(pin, exclusion_pin, campaign_root=root, host=host, out=root / name)
    other = write(base / 'other.json', exclusion(rule('other', {'inspire': ['9077']})))
    with pytest.raises(ValueError, match='admitted'):
        corpus.acquire(plan_pin, other, campaign_root=root, host=host, out=root / 'other')
    with pytest.raises(ValueError, match='inside its campaign'):
        corpus.acquire(plan_pin, exclusion_pin, campaign_root=root, host=host, out=root)
    assert not calls


def test_module_has_no_direct_network_model_or_dispatch_reach():
    source = Path(corpus.__file__).read_text()
    assert check_agent_paths.scan_source(source, module='ravel.workflow.literature_corpus',
                                         path='ravel/workflow/literature_corpus.py', is_package=False) == []
    assert 'urllib' not in source and 'http.client' not in source and 'execute_graph' not in source
