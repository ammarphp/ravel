"""Governed literature serving through the knowledge broker. Fictional sources and fakes only.

Deterministic fakes stand in for the local embedding and cross-encoder adapters;
no model, network, acquisition or scientific job runs. Every denial must leave a
custody record and a broker refusal receipt, with no provider call (when refused
before dispatch) and no result file.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from ravel.workflow import broker as core, broker_mcp, effect_ledger, knowledge_broker, tool_gate, toolbelt
from ravel.workflow import literature_build as store, literature_index as engine, literature_provider as contract
from ravel.workflow import literature_serving as serving, literature_settings as settings_loader

ROLE = 'literature-scout'
PAPERS = {
    'alder': {'identifiers': {'arxiv': ['fictional-preprint-alder'], 'inspire': ['ins1001']},
              'lines': ['Alder rate is 3.5 units in calm air.', 'Alder method uses a counting rule.']},
    'birch': {'identifiers': {'arxiv': ['fictional-preprint-birch'], 'inspire': ['ins1002']},
              'lines': ['Birch rate is 7.25 units in calm air.', 'Birch method repeats the counting rule.']},
    'cedar': {'identifiers': {}, 'url': 'https://arxiv.org/abs/fictional-preprint-cedarv2',
              'lines': ['Cedar rate is 1.75 units under dry conditions.', 'Cedar method splits the counting rule.']},
    'dogwood': {'identifiers': {}, 'quantities': ['rate', 'edge_value'],
                'lines': ['Dogwood rate is 9.0 units under dry conditions.', 'Dogwood method inverts the counting rule.']},
}
TOOL_ROW = {'id': 'cmd:literature', 'title': 'Literature retrieval', 'summary': 'Located literature candidates'}


def pin(raw, path, receipt_id=None):
    return {'path': path, 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw), 'receipt_id': receipt_id}


def make_corpus(source_root, papers=PAPERS):
    """Source-native fictional papers: exact byte intervals, one located measurement each."""
    data = {'schema_version': 1, 'units': [], 'papers': [], 'inputs': []}
    for name, spec in papers.items():
        document = 'paper:' + name
        raw = ('Results\n' + '\n'.join(spec['lines']) + '\n').encode()
        (source_root / 'sources').mkdir(parents=True, exist_ok=True)
        (source_root / 'sources' / (name + '.txt')).write_bytes(raw)
        lineage = []
        if 'url' in spec:
            record = json.dumps({'url': spec['url']}).encode()
            lineage.append({'pin': pin(record, 'acquisitions/' + name + '.json', 'receipt:acquisition:' + name),
                            'identifiers': {'document': [document], 'url': [spec['url']]},
                            'quantities': [], 'classes': [], 'kind': 'generated'})
        common = {'document_id': document, 'version': 'v1', 'original': pin(raw, 'sources/' + name + '.txt'),
                  'extraction': None, 'extraction_reason': 'Source-native UTF-8 text.',
                  'identifiers': {'document': [document], **deepcopy(spec['identifiers'])},
                  'quantities': list(spec.get('quantities', ['rate'])), 'classes': ['text'], 'lineage': lineage,
                  'acquisition_status': 'available', 'extraction_issues': [], 'physics_verified': False,
                  'execution_authorized': False}
        title = 'Fictional ' + name + ' study'
        data['papers'].append({**deepcopy(common), 'id': 'record:' + name, 'title': title,
                               'reason': 'Pinned fictional document.'})
        offset = len(b'Results\n')
        for number, line in enumerate(spec['lines'], 1):
            encoded = line.encode()
            measurement = None
            if number == 1:
                value = line.split(' is ')[1].split(' ')[0]
                start, unit = offset + line.index(value), offset + line.index('units')
                measurement = {'value': {'value': value, 'byte_start': start, 'byte_end': start + len(value)},
                               'unit': {'value': 'units', 'byte_start': unit, 'byte_end': unit + 5},
                               'conditions': None}
            location = {'section_path': ['Results'], 'section_status': 'source', 'page_index': None,
                        'page_number': None, 'printed_page_label': None, 'line_start': number + 1,
                        'line_end': number + 1, 'byte_start': offset, 'byte_end': offset + len(encoded),
                        'space': 'original-text',
                        'null_reasons': {k: 'Source is text.' for k in ('page_index', 'page_number', 'printed_page_label')}}
            evidence = {**deepcopy(common), 'id': 'unit:' + name + ':' + str(number), 'unit_id': 'paragraph:' + str(number),
                        'text': line, 'excerpt_sha256': hashlib.sha256(encoded).hexdigest(), 'location': location,
                        'scores': engine._scores(), 'group_id': None, 'measurement': measurement}
            data['units'].append({'evidence': evidence, 'indexed_text': engine.indexed_text(title, ['Results'], line),
                                  'parent_id': None, 'section_ids': []})
            offset += len(encoded) + 1
    return data


class Embedder:
    identity = {'name': 'fictional-embedding', 'revision': '1'}

    @staticmethod
    def _vector(text):
        words = text.lower().split()
        return [1.0 + sum('rate' in w for w in words), 1.0 + sum('method' in w for w in words), 1.0 + len(words) % 3]

    def embed_documents(self, texts):
        return [self._vector(t) for t in texts]

    def embed_query(self, text):
        return self._vector(text)


class Reranker:
    identity = {'name': 'fictional-cross-encoder', 'revision': '1'}

    def __init__(self):
        self.calls, self.offset = [], 0.0

    def score(self, query, texts):
        self.calls.append(list(texts))
        words = query.lower().split()
        return [self.offset + float(sum(t.lower().count(w) for w in words)) for t in texts]


class Recording:
    """Delegates to the hybrid provider and records every invocation, the effect a denial must precede."""

    def __init__(self, inner, change=None):
        self.inner, self.change, self.calls = inner, change, []
        self.provider_id = inner.provider_id

    def index_identity(self, view):
        return self.inner.index_identity(view)

    def _run(self, op, request, view):
        self.calls.append(op)
        result = getattr(self.inner, op)(request, view=view)
        return self.change(result, request, view) if self.change else result

    def search(self, request, *, view):
        return self._run('search', request, view)

    def get_paper(self, request, *, view):
        return self._run('get_paper', request, view)

    def list_papers(self, request, *, view):
        return self._run('list_papers', request, view)

    def compare_measurements(self, request, *, view):
        return self._run('compare_measurements', request, view)


def restriction(**fields):
    row = {'kind': 'forbidden-source', 'statement': 'Withhold the declared fictional source.', 'evidence': [],
           'origin': 'harness'}
    row.update(fields)
    return row


def install(base, *, papers=PAPERS, change=None, clock=lambda: 0.0, **options):
    source_root, index_root = base / 'corpus', base / 'index'
    source_root.mkdir(parents=True, exist_ok=True)
    corpus = make_corpus(source_root, papers)
    embedder, reranker = Embedder(), Reranker()
    snapshot = store.build_index(index_root, corpus, embedder=embedder, reranker_identity=reranker.identity)
    inner = engine.HybridLiteratureProvider(snapshot, embedder=embedder, reranker=reranker, cursor_key=b'k' * 32,
                                            clock=clock)
    provider = Recording(inner, change)
    configuration = serving.Serving(provider, snapshot=snapshot, qualification=serving.qualify(provider, snapshot),
                                    source_root=source_root, index_root=index_root, **options)
    return SimpleNamespace(source_root=source_root, index_root=index_root, corpus=corpus, snapshot=snapshot,
                           provider=provider, embedder=embedder, reranker=reranker, serving=configuration)


def make_run(base, restrictions=()):
    run = base / 'run'
    (run / 'inputs').mkdir(parents=True, exist_ok=True)
    (run / 'inputs/task_contract.json').write_text(json.dumps({'forbidden_sources': list(restrictions)}))
    return run


def bind(run, configuration=None, *, node='worker', attempt=1, allowed=(serving.ACTION,), max_calls=80, **options):
    workspace = core.work_root(run) / node / str(attempt)
    for name in ('inputs', 'outputs', 'scratch', 'calls'):
        (workspace / name).mkdir(parents=True, exist_ok=True)
    made = knowledge_broker.create(run, workspace, role=ROLE, node_id=node, attempt=attempt,
                                   allowed_actions=list(allowed), max_calls=max_calls, **options)
    serving.register(made, configuration)
    return made


def world(base, restrictions=(), **options):
    installed = install(base, **options)
    run = make_run(base, restrictions)
    return SimpleNamespace(**vars(installed), run=run, broker=bind(run, installed.serving))


@pytest.fixture
def base(tmp_path, monkeypatch):
    root = Path(os.path.realpath(tmp_path))
    monkeypatch.setenv('RAVEL_STATE_DIR', str(root / 'state'))
    return root


def args(op, **changes):
    value = {'search': {'query': 'rate units', 'top_k': 3, 'mode': 'flat', 'document_scope': [], 'filters': {}},
             'get_paper': {'document_id': 'paper:alder', 'version': 'v1', 'section': None, 'page_index': None,
                           'cursor': None, 'limit': 8},
             'list_papers': {'filters': {}, 'limit': 8, 'cursor': None},
             'compare_measurements': {'topic': 'rate', 'groups': ['rate', 'absent-group'], 'top_k_per_group': 2,
                                      'filters': {}}}[op]
    value = deepcopy(value)
    value.update(changes)
    return value


def ledger(run):
    return [row['record'] for row in core.ledger(run, serving.LEDGER)]


def written(made):
    folder = made.workspace / 'outputs' / 'literature'
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def summary(reply):
    return json.loads(reply['stdout_tail'])


def located(run, reply):
    return json.loads(serving.load(run, reply))


def documents(run, reply):
    value = located(run, reply)
    return sorted({row['document_id'] for row in value['results'] + value['metadata']})


def requalify(record, **changes):
    record = {k: v for k, v in {**record, **changes}.items() if k != 'qualification_sha256'}
    return {**record, 'qualification_sha256': core.digest(record)}


def assert_denied(w, reply, code, *, stage='admission', calls=0, made=None):
    """A refusal receipted in custody and by the broker, with no result file and no unexpected provider call."""
    made = made or w.broker
    assert reply['status'] == 'refused' and reply['error']['code'] == code, reply
    identity = re.search(r'\[(serving:\d+)\]\Z', reply['error']['message'])[1]
    rows = core.ledger(w.run, serving.LEDGER)
    last = rows[-1]['record']
    assert last['event'] == 'denied' and last['code'] == code and last['stage'] == stage, last
    assert last.get('serving_id', 'serving:%d' % rows[-1]['n']) == identity
    receipts = made.verify_ledger()
    assert receipts[-1]['status'] == 'refused' and receipts[-1]['output_pins'] == [] and receipts[-1]['reply'] == reply
    # Every result file is the output pin of a delivered call; the denial wrote none.
    delivered = {p['path'].rsplit('/', 1)[1] for r in receipts if r['status'] == 'ok' for p in r['output_pins']}
    assert set(written(made)) == delivered and len(w.provider.calls) == calls
    return last


# ---- delivery and the order of custody records and effects

@pytest.mark.parametrize('op', contract.OPERATIONS)
def test_each_operation_is_served_as_located_bytes_after_its_custody_record(base, op):
    w = world(base)
    seen, write = [], w.broker._write
    w.broker._write = lambda value: (seen.append([r['event'] for r in ledger(w.run)]), write(value))[1]
    reply = serving.call(w.broker, op, args(op))
    assert reply['status'] == 'ok', reply
    assert seen == [['admitted', 'served']]
    raw, info = serving.load(w.run, reply), summary(reply)
    assert hashlib.sha256(raw).hexdigest() == info['located_sha256'] == reply['outputs'][0]['sha256']
    assert info['path'] == serving.OUTPUTS + '/' + info['located_sha256'] + '.json'
    envelope = json.loads(raw)
    assert raw == contract.canonical(envelope) and 'elapsed_seconds' not in envelope['usage']
    assert envelope['operation'] == op and envelope['index']['manifest_sha256'] == w.serving.index['manifest_sha256']
    assert envelope['results'] or envelope['metadata']
    assert not any(r['physics_verified'] or r['execution_authorized'] for r in envelope['results'] + envelope['metadata'])
    receipt = w.broker.verify_ledger()[-1]
    assert receipt['derivation'] == 'retrieval' and receipt['source'] == {
        'uri': 'ravel-literature://index/' + w.serving.index['manifest_sha256'], 'record_id': info['located_sha256']}
    served = ledger(w.run)[-1]
    assert served['serving_id'] == info['serving_id'] and served['located_sha256'] == info['located_sha256']
    assert [r['id'] for r in served['results']] == [r['id'] for r in envelope['results']]
    assert w.provider.calls == [op]


def test_custody_records_precede_the_provider_call_and_the_result_file(base, monkeypatch):
    sequence = []
    w = world(base, change=lambda result, request, view: (sequence.append('provider'), result)[1])
    real, write = core.append_ledger, w.broker._write
    monkeypatch.setattr(core, 'append_ledger', lambda run, name, record: (
        sequence.append(name + ':' + record.get('event', '') if name == serving.LEDGER else name),
        real(run, name, record))[1])
    w.broker._write = lambda value: (sequence.append('write'), write(value))[1]
    assert serving.call(w.broker, 'search', args('search'))['status'] == 'ok'
    assert sequence == ['broker-reservations', 'literature-serving:admitted', 'provider',
                        'literature-serving:served', 'write', 'broker', 'acquisition']
    sequence.clear()
    assert serving.call(w.broker, 'search', args('search', top_k=0))['status'] == 'refused'
    assert sequence == ['broker-reservations', 'literature-serving:denied', 'broker']
    sequence.clear()
    w.provider.change = lambda result, request, view: (sequence.append('provider'), {**result, 'request_id': 'x'})[1]
    assert serving.call(w.broker, 'search', args('search'))['status'] == 'refused'
    assert sequence == ['broker-reservations', 'literature-serving:admitted', 'provider',
                        'literature-serving:denied', 'broker']


def test_located_bytes_are_content_addressed_and_exclude_measured_time(base):
    ticks = iter(range(1, 10 ** 7))
    w = world(base, clock=lambda: next(ticks) ** 2 * 1e-7)
    first = serving.call(w.broker, 'search', args('search'))
    second = serving.call(w.broker, 'search', args('search'))
    assert first['status'] == second['status'] == 'ok' and first['outputs'] == second['outputs']
    served = [r for r in ledger(w.run) if r['event'] == 'served']
    assert served[0]['usage']['elapsed_seconds'] != served[1]['usage']['elapsed_seconds']
    assert served[0]['located_sha256'] == served[1]['located_sha256']
    assert written(w.broker) == [served[0]['located_sha256'] + '.json']


def test_without_configuration_every_call_is_a_receipted_unavailable_refusal(base):
    run = make_run(base)
    made = bind(run, None, allowed=(serving.ACTION, serving.REPLAY_ACTION, 'knowledge.show'))
    reply = serving.call(made, 'search', args('search'))
    assert reply['status'] == 'refused' and reply['error']['code'] == 'retrieval_unavailable'
    assert ledger(run)[-1]['code'] == 'retrieval_unavailable' and written(made) == []
    assert serving.replay(made, 'serving:1')['error']['code'] == 'retrieval_unavailable'
    # Registration adds only the two literature actions; existing handlers stay in place.
    plain_workspace = core.work_root(run) / 'plain' / '1'
    for name in ('inputs', 'outputs', 'scratch', 'calls'):
        (plain_workspace / name).mkdir(parents=True)
    plain = knowledge_broker.create(run, plain_workspace, role=ROLE, node_id='plain', attempt=1,
                                    allowed_actions=[], max_calls=4)
    literature = {serving.ACTION, serving.REPLAY_ACTION}
    assert set(made.actions) - literature == set(plain.actions) - literature
    assert literature <= set(made.actions)
    shown = made.call({'call_id': 'show', 'action': 'knowledge.show', 'args': {'id': 'cmd:work'}})
    assert shown['status'] == 'ok' and shown['outputs'][0]['path'].split('/')[-2] == 'knowledge'


# ---- denials before any provider call

SCHEMA_CASES = {
    'missing op': {'args': args('search')},
    'unknown op': {'op': 'summarize', 'args': args('search')},
    'arguments not an object': {'op': 'search', 'args': ['rate']},
    'extra outer key': {'op': 'search', 'args': args('search'), 'index_root': '/elsewhere'},
    'missing field': {'op': 'search', 'args': {k: v for k, v in args('search').items() if k != 'mode'}},
    'extra field': {'op': 'search', 'args': {**args('search'), 'provider': 'remote'}},
    'string count': {'op': 'search', 'args': args('search', top_k='3')},
    'integral float': {'op': 'search', 'args': args('search', top_k=3.0)},
    'boolean count': {'op': 'search', 'args': args('search', top_k=True)},
    'zero count': {'op': 'search', 'args': args('search', top_k=0)},
    'unknown mode': {'op': 'search', 'args': args('search', mode='semantic')},
    'zero byte budget': {'op': 'search', 'args': {**args('search'), 'budgets': {**serving.DEFAULT_BUDGETS, 'max_bytes': 0}}},
    'unknown budget': {'op': 'search', 'args': {**args('search'), 'budgets': {**serving.DEFAULT_BUDGETS, 'priority': 1}}},
    'malformed cursor': {'op': 'list_papers', 'args': args('list_papers', cursor={'token': 'x'})},
    'absent version': {'op': 'get_paper', 'args': {k: v for k, v in args('get_paper').items() if k != 'version'}},
    'empty groups': {'op': 'compare_measurements', 'args': args('compare_measurements', groups=[])},
}


@pytest.mark.parametrize('case', SCHEMA_CASES)
def test_schema_violations_are_receipted_before_any_provider_call(base, case):
    w = world(base)
    reply = w.broker.call({'call_id': 'bad', 'action': serving.ACTION, 'args': deepcopy(SCHEMA_CASES[case])})
    assert_denied(w, reply, 'schema_violation')
    assert 'remote' not in reply['error']['message'] and 'elsewhere' not in reply['error']['message']


UNQUALIFIED = ('missing', 'other provider', 'other implementation', 'operation not qualified', 'not policy scoped',
               'tampered', 'other index', 'not a provider')


@pytest.mark.parametrize('case', UNQUALIFIED)
def test_unqualified_providers_are_refused_before_dispatch(base, case):
    w = world(base)
    record = w.serving.qualification
    if case == 'missing':
        record = None
    elif case == 'other provider':
        record = requalify(record, provider_id='remote-fiction')
    elif case == 'other implementation':
        record = requalify(record, implementation='elsewhere.Provider')
    elif case == 'operation not qualified':
        record = requalify(record, operations=['get_paper'])
    elif case == 'not policy scoped':
        record = requalify(record, policy_scoped=False)
    elif case == 'tampered':
        record = {**record, 'operations': ['search']}
    elif case == 'other index':
        record = requalify(record, index={'id': 'literature:' + '3' * 64, 'manifest_sha256': '3' * 64})
    else:
        w.serving.provider = SimpleNamespace(provider_id=w.provider.provider_id, search=w.provider.search)
    w.serving.qualification = record
    assert_denied(w, serving.call(w.broker, 'search', args('search')), 'provider_unqualified')


def test_a_moved_installation_index_is_stale_before_dispatch(base):
    w = world(base)
    subset = {k: PAPERS[k] for k in ('alder', 'birch')}
    store.update_index(w.index_root, make_corpus(w.source_root, subset), embedder=w.embedder,
                       reranker_identity=w.reranker.identity)
    assert_denied(w, serving.call(w.broker, 'search', args('search')), 'stale_index')


def test_a_provider_serving_another_snapshot_is_stale_before_dispatch(base):
    w = world(base)
    other = store.build_index(base / 'other-index', make_corpus(base / 'other', {'alder': PAPERS['alder']}),
                              embedder=w.embedder, reranker_identity=w.reranker.identity)
    w.provider.inner = engine.HybridLiteratureProvider(other, embedder=w.embedder, reranker=w.reranker,
                                                       cursor_key=b'k' * 32, clock=lambda: 0.0)
    assert_denied(w, serving.call(w.broker, 'search', args('search')), 'stale_index')


def test_a_removed_pinned_manifest_is_stale_before_dispatch(base):
    w = world(base)
    (w.index_root / 'snapshots' / w.serving.index['manifest_sha256'] / 'manifest.json').unlink()
    assert_denied(w, serving.call(w.broker, 'list_papers', args('list_papers')), 'stale_index')


@pytest.mark.parametrize('field,code', [('manifest_sha256', 'stale_index'), ('policy_view_sha256', 'policy_changed'),
                                        ('selector_sha256', 'schema_violation')])
def test_a_cursor_from_another_snapshot_view_or_selection_is_refused(base, field, code):
    w = world(base)
    first = serving.call(w.broker, 'list_papers', args('list_papers', limit=1))
    cursor = located(w.run, first)['next_cursor']
    assert cursor is not None and w.provider.calls == ['list_papers']
    page = serving.call(w.broker, 'list_papers', args('list_papers', limit=1, cursor=cursor))
    assert page['status'] == 'ok' and documents(w.run, page) == ['paper:birch']
    cursor[field] = '4' * 64
    assert_denied(w, serving.call(w.broker, 'list_papers', args('list_papers', limit=1, cursor=cursor)), code, calls=2)


def test_policy_changed_after_binding_is_refused_before_the_handler(base):
    w = world(base)
    (w.run / 'inputs/task_contract.json').write_text(
        json.dumps({'forbidden_sources': [restriction(identifiers={'arxiv': ['fictional-preprint-absent']})]}))
    reply = serving.call(w.broker, 'search', args('search'))
    assert reply['status'] == 'refused' and reply['error']['code'] == 'forbidden_source'
    assert w.provider.calls == [] and ledger(w.run) == [] and written(w.broker) == []
    report = serving.audit(w.run)
    assert report['calls'] == [] and [r['code'] for r in report['broker_only']] == ['forbidden_source']


def test_policy_changed_during_retrieval_is_refused_before_serving(base):
    contract_path = base / 'run' / 'inputs' / 'task_contract.json'

    def change(result, request, view):
        rows = [restriction(identifiers={'arxiv': ['fictional-preprint-absent']})]
        contract_path.write_text(json.dumps({'forbidden_sources': rows}))
        return result
    w = world(base, change=change)
    assert_denied(w, serving.call(w.broker, 'search', args('search')), 'policy_changed', stage='serving', calls=1)


FORBIDDEN_ROWS = [restriction(identifiers={'arxiv': ['fictional-preprint-birch'], 'inspire': ['ins1002']}),
                  restriction(classes=['withheld-class'])]
SELECTORS = {
    'exact paper': ('get_paper', args('get_paper', document_id='paper:birch')),
    'unversioned paper': ('get_paper', args('get_paper', document_id='paper:birch', version=None)),
    'document scope': ('search', args('search', document_scope=[{'document_id': 'paper:alder', 'version': 'v1'},
                                                                {'document_id': 'paper:birch', 'version': 'v1'}])),
    'versioned identity filter': ('search', args('search', filters={'arxiv': ['fictional-preprint-birchv4']})),
    'padded identity filter': ('list_papers', args('list_papers', filters={'inspire': ['ins01002']})),
    'document filter': ('list_papers', args('list_papers', filters={'document_id': ['paper:birch']})),
    'class filter': ('list_papers', args('list_papers', filters={'classes': ['withheld-class']})),
    'comparison group': ('compare_measurements', args('compare_measurements', groups=['rate', 'fictional-preprint-birch'])),
}


@pytest.mark.parametrize('case', SELECTORS)
def test_selectors_naming_withheld_sources_are_refused_before_dispatch(base, case):
    w = world(base, FORBIDDEN_ROWS)
    op, request = SELECTORS[case]
    reply = serving.call(w.broker, op, request)
    assert_denied(w, reply, 'forbidden_source')
    message = reply['error']['message']
    assert w.broker.policy_sha256 in message
    secrets = ('fictional-preprint-birch', 'ins1002', 'Withhold', 'withheld-class', 'birch')
    assert not any(secret in message for secret in secrets)


@pytest.mark.parametrize('field,value', [('max_bytes', 65537), ('max_tokens', 65537), ('max_seconds', 61.0),
                                         ('max_expansions', 4097)])
def test_request_budgets_above_the_serving_ceilings_are_refused(base, field, value):
    w = world(base, ceilings={'max_bytes': 65536, 'max_tokens': 65536, 'max_seconds': 60.0, 'max_expansions': 4096})
    budgets = {**serving.DEFAULT_BUDGETS, field: value}
    assert_denied(w, serving.call(w.broker, 'search', {**args('search'), 'budgets': budgets}), 'budget_exceeded')


@pytest.mark.parametrize('op,payload', [('search', args('search', top_k=5)), ('list_papers', args('list_papers', limit=5)),
                                        ('compare_measurements', args('compare_measurements', groups=['rate', 'a', 'b'],
                                                                      top_k_per_group=2))])
def test_result_counts_above_the_serving_ceiling_are_refused(base, op, payload):
    w = world(base, ceilings={'max_results': 4})
    assert_denied(w, serving.call(w.broker, op, payload), 'budget_exceeded')


@pytest.mark.parametrize('allowance,admitted', [({'max_requests': 2}, 2), ({'max_bytes': 33000}, 1),
                                                ({'max_seconds': 15.0}, 1)])
def test_the_attempt_allowance_is_exhausted_before_dispatch(base, allowance, admitted):
    w = world(base, allowance=allowance)
    assert serving.call(w.broker, 'search', args('search', top_k=0))['status'] == 'refused'  # never admitted
    for n in range(admitted):
        assert serving.call(w.broker, 'search', args('search', query='rate units ' + str(n)))['status'] == 'ok'
    reply = serving.call(w.broker, 'search', args('search'))
    assert_denied(w, reply, 'budget_exhausted', calls=admitted)
    other = bind(w.run, w.serving, node='other')
    assert serving.call(other, 'search', args('search'))['status'] == 'ok'


# ---- the source view is applied before ranking, statistics and counts

def visible(w):
    reply = serving.call(w.broker, 'list_papers', args('list_papers'))
    assert reply['status'] == 'ok', reply
    return documents(w.run, reply)


VIEW_CASES = {
    'versioned arxiv spelling': ([restriction(identifiers={'arxiv': ['fictional-preprint-alderv3']})], ['paper:birch', 'paper:cedar']),
    'padded inspire spelling': ([restriction(identifiers={'inspire': ['ins001001']})], ['paper:birch']),
    'identity from acquisition url': ([restriction(identifiers={'arxiv': ['fictional-preprint-cedar']})], ['paper:alder', 'paper:birch']),
    'absent identity': ([restriction(identifiers={'inspire': ['ins999']})], ['paper:alder', 'paper:birch']),
    'corpus path': ([restriction(paths=['sources/birch.txt'])], ['paper:alder', 'paper:cedar', 'paper:dogwood']),
    'whole document under a scoped ban': ([restriction(kind='no-value-extraction', identifiers={'arxiv': ['fictional-preprint-alder']},
                                                       scope={'quantities': ['edge_value']})], ['paper:birch', 'paper:cedar']),
    'unselected scoped ban keeps its scope': ([restriction(kind='no-value-extraction', origin='request',
                                                           scope={'quantities': ['edge_value']})],
                                              ['paper:alder', 'paper:birch', 'paper:cedar']),
    'class': ([restriction(classes=['text'])], []),
}


@pytest.mark.parametrize('case', VIEW_CASES)
def test_the_source_view_withholds_restricted_and_unresolvable_documents(base, case):
    rows, expected = VIEW_CASES[case]
    w = world(base, rows)
    if expected:
        assert visible(w) == expected
    else:
        reply = serving.call(w.broker, 'list_papers', args('list_papers'))
        assert reply['status'] == 'ok' and located(w.run, reply)['metadata'] == []
        assert located(w.run, reply)['omitted'][0]['code'] == 'no_match'
    for paper in sorted(set(f'paper:{n}' for n in PAPERS) - set(expected)):
        assert_denied(w, serving.call(w.broker, 'get_paper', args('get_paper', document_id=paper)), 'forbidden_source',
                      calls=1)
    search = serving.call(w.broker, 'search', args('search', top_k=8))
    hidden = {f'paper:{n}' for n in PAPERS} - set(expected)
    raw = serving.load(w.run, search)
    assert not any(name.split(':')[1].capitalize().encode() in raw for name in hidden)


def test_an_unestablished_source_view_is_refused_before_dispatch(base):
    installed = install(base)
    run = make_run(base, [restriction(paths=['refs/**'])])
    secret = run / 'inputs' / 'refs' / 'unreadable.txt'
    secret.parent.mkdir()
    secret.write_text('fictional withheld bytes')
    secret.chmod(0)
    try:
        if os.access(secret, os.R_OK):
            pytest.skip('this account can read files without read permission')
        w = SimpleNamespace(**vars(installed), run=run, broker=bind(run, installed.serving))
        assert_denied(w, serving.call(w.broker, 'search', args('search')), 'policy_unavailable')
    finally:
        secret.chmod(0o600)


def test_load_refuses_changed_outputs_and_other_replies(base):
    w = world(base)
    reply = serving.call(w.broker, 'search', args('search'))
    path = core.locate(w.run, reply['outputs'][0]['path'])
    assert serving.load(w.run, reply) == path.read_bytes()
    with pytest.raises(ValueError, match='no matching broker receipt'):
        serving.load(w.run, {**reply, 'stdout_tail': '{}'})
    w.broker.allowed_actions.add('knowledge.show')
    shown = w.broker.call({'call_id': 'show', 'action': 'knowledge.show', 'args': {'id': 'cmd:work'}})
    with pytest.raises(ValueError, match='not a delivered literature result'):
        serving.load(w.run, shown)
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError, match='changed after custody'):
        serving.load(w.run, reply)


def test_a_copy_of_a_withheld_run_input_is_withheld_from_the_corpus(base):
    installed = install(base)
    run = make_run(base, [restriction(paths=['refs/**'])])
    (run / 'inputs' / 'refs').mkdir()
    (run / 'inputs' / 'refs' / 'copy.txt').write_bytes((installed.source_root / 'sources' / 'dogwood.txt').read_bytes())
    w = SimpleNamespace(**vars(installed), run=run, broker=bind(run, installed.serving))
    assert visible(w) == ['paper:alder', 'paper:birch', 'paper:cedar']


def test_withheld_documents_never_reach_statistics_model_inputs_or_counts(base):
    pair = {k: PAPERS[k] for k in ('alder', 'birch')}
    restricted = world(base / 'restricted', [FORBIDDEN_ROWS[0]], papers=pair)
    clean = world(base / 'clean', papers={'alder': PAPERS['alder']})
    unrestricted = world(base / 'unrestricted', papers=pair)
    outcomes = []
    for w in (restricted, clean, unrestricted):
        reply = serving.call(w.broker, 'search', args('search', top_k=4, mode='hybrid'))
        assert reply['status'] == 'ok'
        rows = located(w.run, reply)['results']
        outcomes.append([(r['id'], r['scores']) for r in rows if r['document_id'] == 'paper:alder'])
        listed = located(w.run, serving.call(w.broker, 'list_papers', args('list_papers')))
        if w is not unrestricted:
            assert [m['document_id'] for m in listed['metadata']] == ['paper:alder']
            assert not any('Birch' in text for call in w.reranker.calls for text in call)
    assert outcomes[0] == outcomes[1]
    # Control: the same paper, when admitted, does change the alder statistics.
    assert outcomes[2] != outcomes[0]


# ---- serving-boundary checks after the provider ran

@pytest.mark.parametrize('error,code', [(RuntimeError('adapter detail: Birch rate'), 'provider_failed'),
                                        (TimeoutError('deadline'), 'budget_exhausted')])
def test_provider_failures_are_receipted_after_admission_without_output(base, error, code):
    def change(result, request, view):
        raise error
    w = world(base, change=change)
    reply = serving.call(w.broker, 'search', args('search'))
    last = assert_denied(w, reply, code, stage='retrieval', calls=1)
    assert 'Birch' not in reply['error']['message'] and type(error).__name__ in last['detail']
    assert [r['event'] for r in ledger(w.run)] == ['admitted', 'denied']


def _first(result, key, value):
    result['results'][0][key] = value
    return result


def _excerpt(result):
    result['results'][0]['text'] += '!'
    return result


def _ranks(result):
    result['results'][0]['scores']['rank'], result['results'][1]['scores']['rank'] = 2, 1
    return result


def _population(result):
    extra = deepcopy(result['results'][0])
    extra['id'], extra['scores']['rank'] = 'unit:extra', len(result['results']) + 1
    result['results'].append(extra)
    return result


def _view(result):
    result['index']['policy_view_sha256'] = '5' * 64
    return result


def _manifest(result):
    result['index']['manifest_sha256'] = '6' * 64
    return result


CONTRACT_CASES = {
    'verified promotion': (lambda r: _first(r, 'physics_verified', True), 'provider_schema_violation'),
    'execution authority': (lambda r: _first(r, 'execution_authorized', True), 'provider_schema_violation'),
    'altered excerpt': (_excerpt, 'provider_schema_violation'),
    'rank order': (_ranks, 'provider_schema_violation'),
    'request identity': (lambda r: {**r, 'request_id': 'literature:other'}, 'provider_schema_violation'),
    'not an envelope': (lambda r: [r], 'provider_schema_violation'),
    'population above top_k': (_population, 'provider_schema_violation'),
    'another source view': (_view, 'provider_schema_violation'),
    'another manifest': (_manifest, 'stale_index'),
}


@pytest.mark.parametrize('case', CONTRACT_CASES)
def test_provider_contract_violations_are_refused_at_the_serving_boundary(base, case):
    mutate, code = CONTRACT_CASES[case]
    w = world(base, change=lambda result, request, view: mutate(deepcopy(result)))
    assert_denied(w, serving.call(w.broker, 'search', args('search')), code, stage='serving', calls=1)


def _inject(w, document):
    """A provider that leaks one stored unit of another document into otherwise valid results."""
    stored = deepcopy(w.serving.units[(document, 'v1', 'paragraph:1')])

    def change(result, request, view):
        result = deepcopy(result)
        stored['scores'] = {**engine._scores(), 'rank': len(result['results'])}
        result['results'][-1] = stored
        return result
    return change


def test_a_provider_leaking_a_withheld_unit_is_refused_at_the_serving_boundary(base):
    w = world(base, [restriction(paths=['sources/birch.txt'])])
    w.provider.change = _inject(w, 'paper:birch')
    reply = serving.call(w.broker, 'search', args('search', filters={'document_id': ['paper:alder']}))
    last = assert_denied(w, reply, 'forbidden_source', stage='serving', calls=1)
    assert 'unit:birch:1' in last['detail'] and 'birch' not in reply['error']['message']


def test_a_graph_path_naming_a_withheld_document_is_refused(base):
    w = world(base, [restriction(paths=['sources/birch.txt'])])

    def change(result, request, view):
        result = deepcopy(result)
        result['results'][0]['scores']['graph_paths'] = [['paper:alder', 'paper:birch']]
        return result
    w.provider.change = change
    assert_denied(w, serving.call(w.broker, 'search', args('search')), 'forbidden_source', stage='serving', calls=1)


@pytest.mark.parametrize('field', ['omitted', 'failures'])
def test_provider_prose_naming_a_withheld_source_is_refused(base, field):
    w = world(base, [restriction(identifiers={'arxiv': ['fictional-preprint-birch'], 'inspire': ['ins1002']})])

    def change(result, request, view):
        result = deepcopy(result)
        result[field].append({'code': 'missing', 'id': 'retrieval', 'reason': 'Skipped fictional-preprint-birch while ranking.'})
        return result
    w.provider.change = change
    assert_denied(w, serving.call(w.broker, 'search', args('search')), 'forbidden_source', stage='serving', calls=1)


def test_legacy_path_patterns_also_withhold_corpus_pins(base):
    installed = install(base)
    run = make_run(base)
    w = SimpleNamespace(**vars(installed), run=run,
                        broker=bind(run, installed.serving, forbidden_sources=['sources/cedar.*']))
    assert visible(w) == ['paper:alder', 'paper:birch', 'paper:dogwood']


def _section(result):
    result['results'][0]['location']['section_path'] = ['Methods']
    return result


def _title(result):
    result['metadata'][0]['title'] = 'A relabelled fictional study'
    return result


@pytest.mark.parametrize('op,mutate', [('search', _section), ('list_papers', _title)])
def test_rows_that_are_not_admitted_index_records_are_unauthenticated(base, op, mutate):
    w = world(base, change=lambda result, request, view: mutate(deepcopy(result)))
    assert_denied(w, serving.call(w.broker, op, args(op)), 'unauthenticated_evidence', stage='serving', calls=1)


@pytest.mark.parametrize('damage', ['rewritten', 'linked', 'removed'])
def test_changed_current_source_bytes_are_unauthenticated(base, damage):
    w = world(base)
    source = w.source_root / 'sources' / 'alder.txt'
    raw = source.read_bytes()
    source.unlink()
    if damage == 'rewritten':
        source.write_bytes(raw.replace(b'3.5', b'4.5'))
    elif damage == 'linked':
        (w.source_root / 'alder-copy.txt').write_bytes(raw)
        source.symlink_to(w.source_root / 'alder-copy.txt')
    assert_denied(w, serving.call(w.broker, 'get_paper', args('get_paper')), 'unauthenticated_evidence',
                  stage='serving', calls=1)


def test_an_unwritable_result_withdraws_its_served_record(base):
    w = world(base)
    (w.broker.workspace / 'outputs' / 'literature').write_text('not a directory')
    reply = serving.call(w.broker, 'search', args('search'))
    assert reply['status'] == 'refused' and reply['error']['code'] == 'output_failed'
    assert [(r['event'], r.get('stage')) for r in ledger(w.run)] == [('admitted', None), ('served', None),
                                                                      ('denied', 'output')]
    identity = ledger(w.run)[-1]['serving_id']
    assert {c['serving_id']: c['outcome'] for c in serving.audit(w.run)['calls']} == {identity: 'denied'}
    assert serving.served_ids(w.run, node_id='worker', attempt=1) == set()
    auditor = bind(w.run, w.serving, node='auditor', allowed=())
    assert serving.replay(auditor, identity)['error']['code'] == 'replay_unavailable'


# ---- one code path: the same bytes on every surface

def surface(base, run, configuration, tools, name, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(base / name / 'state'))
    return bind(run, configuration, allowed=toolbelt.allowed_actions(tools), max_calls=20,
                guards=[tool_gate.broker_guard(tools, rundir=run)])


def test_cli_dispatcher_socket_mcp_and_in_graph_calls_serve_identical_bytes(base, monkeypatch, capsys):
    installed = install(base)
    run = make_run(base)
    tools = serving.tools(TOOL_ROW)
    request = args('search', mode='hybrid')
    prefix = effect_ledger.path('synthetic.literature', {'case': 'synthetic'}, None, {'turn': 1})
    identity = tool_gate.call_id(prefix + '/tool:t1')
    replies, raws, records, receipts = [], [], [], []

    def collect(made, reply):
        replies.append(reply)
        raws.append(serving.load(run, reply))
        records.append([{k: v for k, v in r.items() if k != 'utc'} for r in ledger(run)])
        receipts.append([{k: v for k, v in r.items() if k not in ('started_utc', 'finished_utc', 'wall_seconds')}
                         for r in made.verify_ledger()])

    made = surface(base, run, installed.serving, tools, 'graph', monkeypatch)
    gate = tool_gate.ravel_gate(tools, scope_root=base / 'graph-scope', graph={'id': 'synthetic.literature', 'version': 1},
                                prefix=prefix, broker_call=made.call)
    collect(made, gate.call({'tool_call': {'name': 'literature_search', 'args': request, 'id': 't1'}}))

    made = surface(base, run, installed.serving, tools, 'socket', monkeypatch)
    with core.serve(made):
        collect(made, core.socket_call(made.socket_path, toolbelt.to_request(tools, 'literature_search', request,
                                                                             identity)))

    made = surface(base, run, installed.serving, tools, 'mcp', monkeypatch)
    with core.serve(made):
        server = broker_mcp.Server(tools, lambda r: core.socket_call(made.socket_path, r))
        result = server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                'params': {'name': 'literature_search', 'arguments': request,
                                           '_meta': {'call_id': identity}}})['result']
        assert result['isError'] is False
        collect(made, result['structuredContent'])

    made = surface(base, run, installed.serving, tools, 'dispatcher', monkeypatch)
    collect(made, serving.call(made, 'search', request, call_id=identity))

    assert replies[0]['status'] == 'ok' and all(reply == replies[0] for reply in replies)
    assert all(raw == raws[0] for raw in raws) and all(record == records[0] for record in records)
    assert all(receipt == receipts[0] for receipt in receipts) and len(receipts[0]) == 1

    monkeypatch.setenv('RAVEL_STATE_DIR', str(base / 'cli' / 'state'))
    request_path = base / 'request.json'
    request_path.write_text(json.dumps(request))
    capsys.readouterr()
    assert serving.main(['search', '--rundir', str(run), '--request', str(request_path), '--node', 'worker',
                         '--attempt', '1', '--role', ROLE], serving=installed.serving) == 0
    assert capsys.readouterr().out.encode() == raws[0] + b'\n'
    assert [{k: v for k, v in r.items() if k != 'utc'} for r in ledger(run)] == records[0]
    assert installed.provider.calls == ['search'] * 5


def test_the_cli_without_configuration_refuses_with_a_receipt(base, capsys):
    run = make_run(base)
    request_path = base / 'request.json'
    request_path.write_text(json.dumps(args('search')))
    assert serving.main(['search', '--rundir', str(run), '--request', str(request_path), '--node', 'cli']) == 2
    reply = json.loads(capsys.readouterr().out)
    assert reply['status'] == 'refused' and reply['error']['code'] == 'retrieval_unavailable'
    assert serving.main(['audit', '--rundir', str(run)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert [c['outcome'] for c in report['calls']] == ['denied']


# ---- deterministic replay

@pytest.mark.parametrize('op', contract.OPERATIONS)
def test_replay_reproduces_the_located_bytes_of_every_operation(base, op):
    w = world(base)
    reply = serving.call(w.broker, op, args(op))
    identity = summary(reply)['serving_id']
    auditor = bind(w.run, w.serving, node='auditor', allowed=())
    replayed = serving.replay(auditor, identity)
    assert replayed['status'] == 'ok', replayed
    info = summary(replayed)
    assert info['replay_of'] == identity and info['reproduced'] is True
    assert serving.load(w.run, replayed) == serving.load(w.run, reply)
    assert ledger(w.run)[-1]['event'] == 'replayed' and ledger(w.run)[-1]['recorded_binding'] == ledger(w.run)[0]['binding']
    assert serving.REPLAY_ACTION not in auditor.allowed_actions


def test_replay_reproduces_a_later_page_bound_to_its_recorded_worker(base):
    w = world(base)
    first = serving.call(w.broker, 'get_paper', args('get_paper', limit=1))
    cursor = located(w.run, first)['next_cursor']
    page = serving.call(w.broker, 'get_paper', args('get_paper', limit=1, cursor=cursor))
    assert page['status'] == 'ok' and [r['unit_id'] for r in located(w.run, page)['results']] == ['paragraph:2']
    auditor = bind(w.run, w.serving, node='auditor', allowed=())
    replayed = serving.replay(auditor, summary(page)['serving_id'])
    assert replayed['status'] == 'ok' and serving.load(w.run, replayed) == serving.load(w.run, page)


def test_replay_detects_results_that_changed_after_delivery(base):
    w = world(base)
    identity = summary(serving.call(w.broker, 'search', args('search')))['serving_id']
    w.reranker.offset = 0.5
    auditor = bind(w.run, w.serving, node='auditor', allowed=())
    reply = serving.replay(auditor, identity)
    last = assert_denied(w, reply, 'replay_mismatch', stage='replay', calls=2, made=auditor)
    assert last['replay_of'] == identity and last['reproduced_sha256'] != ledger(w.run)[1]['located_sha256']


def test_replay_refuses_changed_conditions_with_receipts(base):
    w = world(base)
    identity = summary(serving.call(w.broker, 'search', args('search')))['serving_id']
    denied_id = re.search(r'\[(serving:\d+)\]', serving.call(w.broker, 'search', args('search', top_k=0))
                          ['error']['message'])[1]
    auditor = bind(w.run, w.serving, node='auditor', allowed=())
    assert_denied(w, serving.replay(auditor, 'serving:999'), 'replay_unavailable', calls=1, made=auditor)
    assert_denied(w, serving.replay(auditor, denied_id), 'replay_unavailable', calls=1, made=auditor)
    assert_denied(w, serving._dispatch(auditor, serving.REPLAY_ACTION, {'serving_id': 5}, None), 'schema_violation',
                  calls=1, made=auditor)
    original = w.serving.qualification
    w.serving.qualification = requalify(original, evidence=['a later conformance run'])
    assert_denied(w, serving.replay(auditor, identity), 'provider_unqualified', calls=1, made=auditor)
    w.serving.qualification = original
    store.update_index(w.index_root, make_corpus(w.source_root, {'alder': PAPERS['alder']}), embedder=w.embedder,
                       reranker_identity=w.reranker.identity)
    assert_denied(w, serving.replay(auditor, identity), 'stale_index', calls=1, made=auditor)


def test_replay_under_a_changed_source_policy_is_refused(base):
    w = world(base)
    identity = summary(serving.call(w.broker, 'search', args('search')))['serving_id']
    (w.run / 'inputs/task_contract.json').write_text(json.dumps({'forbidden_sources': [restriction(paths=['x/**'])]}))
    auditor = bind(w.run, w.serving, node='auditor', allowed=())
    assert_denied(w, serving.replay(auditor, identity), 'policy_changed', calls=1, made=auditor)


# ---- audit, citations, registration and tool rows

def test_audit_accounts_for_every_literature_broker_call(base):
    w = world(base)
    ok = serving.call(w.broker, 'search', args('search'))
    bad = w.broker.call({'call_id': 'bad', 'action': serving.ACTION, 'args': {'op': 'search'}})
    w.broker.allowed_actions.discard(serving.ACTION)
    blocked = w.broker.call({'call_id': 'blocked', 'action': serving.ACTION, 'args': {'op': 'search', 'args': args('search')}})
    assert (ok['status'], bad['status'], blocked['error']['code']) == ('ok', 'refused', 'not_allowlisted')
    report = serving.audit(w.run)
    outcomes = {c['serving_id']: (c['outcome'], [r['receipt_id'] for r in c['receipts']]) for c in report['calls']}
    assert outcomes == {summary(ok)['serving_id']: ('delivered', [ok['receipt_id']]),
                        re.search(r'\[(serving:\d+)\]', bad['error']['message'])[1]: ('denied', [bad['receipt_id']])}
    assert report['broker_only'] == [{'receipt_id': blocked['receipt_id'], 'status': 'refused',
                                      'code': 'not_allowlisted', 'action': serving.ACTION}]
    assert report['ledger_rows'] == 3 and report['unverified_receipts'] == []


def test_citations_must_name_evidence_served_to_the_same_attempt(base):
    w = world(base)
    reply = serving.call(w.broker, 'search', args('search'))
    served = [r['id'] for r in located(w.run, reply)['results']]
    assert serving.check_citations(w.run, served[:2], node_id='worker', attempt=1) == sorted(served[:2])
    with pytest.raises(ValueError, match='never served'):
        serving.check_citations(w.run, [served[0], 'unit:invented'], node_id='worker', attempt=1)
    with pytest.raises(ValueError, match='never served'):
        serving.check_citations(w.run, served[:1], node_id='worker', attempt=2)


def test_registration_is_trusted_and_binds_one_configuration(base):
    w = world(base)
    assert serving.register(w.broker, w.serving).serving is w.serving
    with pytest.raises(ValueError, match='already bound'):
        serving.register(w.broker, install(base / 'second').serving)
    with pytest.raises(ValueError, match='trusted Serving'):
        serving.register(w.broker, {'provider': 'remote'})
    plain = core.Broker(w.run, w.broker.workspace, node_id='plain', attempt=1, allowed_actions=[], max_calls=1)
    with pytest.raises(ValueError, match='source-bound broker'):
        serving.register(plain, w.serving)
    late = bind(w.run, None, node='late')
    serving.register(late, w.serving)
    assert serving.call(late, 'search', args('search'))['status'] == 'ok'
    foreign_workspace = core.work_root(w.run) / 'foreign' / '1'
    for name in ('inputs', 'outputs', 'scratch', 'calls'):
        (foreign_workspace / name).mkdir(parents=True)
    foreign = knowledge_broker.create(w.run, foreign_workspace, role=ROLE, node_id='foreign', attempt=1,
                                      allowed_actions=[], max_calls=1)
    if getattr(foreign, '_literature_serving', None) is None:
        foreign.register(serving.ACTION, lambda a: {}, derivation='retrieval', read_only=True)
        with pytest.raises(ValueError, match='trusted adapter'):
            serving.register(foreign, w.serving)
    with pytest.raises(ValueError):
        serving.Serving(w.provider, snapshot=w.snapshot, qualification=w.serving.qualification,
                        source_root=w.source_root, ceilings={'max_bytes': 10 ** 9})


def test_production_brokers_serve_literature_tools_from_their_trusted_configuration(base):
    installed = install(base)
    run = make_run(base)
    tools = serving.tools(TOOL_ROW)
    made = {}
    for node, configuration in (('worker', installed.serving), ('unbound', None)):
        workspace = core.work_root(run) / node / '1'
        for name in ('inputs', 'outputs', 'scratch', 'calls'):
            (workspace / name).mkdir(parents=True)
        made[node] = tool_gate.production_broker(run, workspace, tools=tools, role=ROLE, node_id=node, attempt=1,
                                                 max_calls=10, retrieval=configuration)
    reply = made['worker'].call(toolbelt.to_request(tools, 'literature_search', args('search'), 'c1'))
    assert reply['status'] == 'ok' and located(run, reply)['results']
    refused = made['unbound'].call(toolbelt.to_request(tools, 'literature_search', args('search'), 'c1'))
    assert refused['status'] == 'refused' and refused['error']['code'] == 'retrieval_unavailable'
    widened = made['worker'].call({'call_id': 'c2', 'action': serving.ACTION,
                                   'args': {'op': 'search', 'args': {**args('search'), 'index_root': '/x'}}})
    assert widened['error']['code'] == 'not_allowlisted'
    replay = made['worker'].call({'call_id': 'c3', 'action': serving.REPLAY_ACTION, 'args': {'serving_id': 'serving:2'}})
    assert replay['error']['code'] == 'not_allowlisted'
    with pytest.raises(ValueError, match='already bound'):
        serving.register(made['worker'], install(base / 'second').serving)


def test_tool_rows_are_typed_broker_tools_on_every_surface(base):
    tools = serving.tools(TOOL_ROW)
    assert [t['name'] for t in tools] == ['literature_search', 'literature_get_paper', 'literature_list_papers',
                                          'literature_compare_measurements']
    assert toolbelt.allowed_actions(tools) == [serving.ACTION]
    for tool, op in zip(tools, contract.OPERATIONS):
        request = toolbelt.to_request(tools, tool['name'], args(op), 'c1')
        assert request == {'call_id': 'c1', 'action': serving.ACTION, 'args': {'op': op, 'args': args(op)}}
        assert toolbelt.match(tools, serving.ACTION, request['args']) is tool
        budgeted = {**args(op), 'budgets': dict(serving.DEFAULT_BUDGETS)}
        assert toolbelt.match(tools, serving.ACTION, {'op': op, 'args': budgeted}) is tool
        assert toolbelt.match(tools, serving.ACTION, {'op': op, 'args': {**args(op), 'index_root': '/x'}}) is None
    listing = broker_mcp.Server(tools, lambda r: {}).listing()
    assert [t['name'] for t in listing] == [t['name'] for t in tools]
    assert all(t['annotations']['readOnlyHint'] for t in listing)



# ---- trusted installation settings (the production loader)

QUERIES = []


def installation(base, monkeypatch, *, qualification=True, **changes):
    """A settings document over a tiny admitted fictional index, as an installation writes it.

    The pinned models are the fictional ONNX installation of the model tests; the index is built
    through the same qualified index adapters (``literature_models.index_models``) the loader uses.
    """
    from ravel.workflow import literature_models as lm
    from test_literature_models import fake_factory, make_installation
    root = base / 'installation'
    models = root / 'models'
    doc = make_installation(models)
    real_embedder, real_reranker = lm.Embedder, lm.Reranker
    monkeypatch.setattr(lm, 'Embedder', lambda model_id=None, *, root=None, **kw: real_embedder(
        model_id, root=root, doc=doc, tokenizer_factory=fake_factory, **kw))
    monkeypatch.setattr(lm, 'Reranker', lambda model_id=None, *, root=None, **kw: real_reranker(
        model_id, root=root, doc=doc, tokenizer_factory=fake_factory, **kw))
    queries = real_embedder.embed_queries
    monkeypatch.setattr(real_embedder, 'embed_queries', lambda self, texts: QUERIES.append(len(texts)) or
                        queries(self, texts))
    embedder, reranker = lm.Embedder(root=models), lm.Reranker(root=models)
    index_embedder, index_reranker = lm.index_models(embedder, reranker, embedding_qualification=lm.qualify(embedder),
                                                     reranker_qualification=lm.qualify(reranker))
    source_root, index_root = root / 'corpus', root / 'index'
    source_root.mkdir(parents=True)
    snapshot = store.build_index(index_root, make_corpus(source_root), embedder=index_embedder,
                                 reranker_identity=index_reranker.identity)
    (root / 'cursor.key').write_bytes(b'c' * 32)
    provider = settings_loader._local_provider(snapshot, cursor_key=b'c' * 32, models_root=str(models))
    if qualification:
        record = serving.qualify(provider, snapshot, evidence=['fictional conformance run'])
        (root / 'qualification.json').write_text(json.dumps(record))
    section = {'provider': 'local', 'graph': False, 'index_root': str(index_root),
               'index_manifest_sha256': snapshot['manifest']['manifest_sha256'], 'source_root': str(source_root),
               'qualification': str(root / 'qualification.json'), 'cursor_key': str(root / 'cursor.key'),
               'models_root': str(models), 'budgets': None, 'ceilings': None, 'allowance': None}
    section.update(changes)
    path = root / 'settings.json'
    path.write_text(json.dumps({'schema_version': 1, 'kind': settings_loader.SETTINGS_KIND, 'retrieval': section}))
    QUERIES.clear()
    return SimpleNamespace(path=path, snapshot=snapshot, source_root=source_root, index_root=index_root, root=root,
                           embedder=index_embedder, reranker=index_reranker)


def production(run, node, configuration, tools=None):
    workspace = core.work_root(run) / node / '1'
    for name in ('inputs', 'outputs', 'scratch', 'calls'):
        (workspace / name).mkdir(parents=True)
    return tool_gate.production_broker(run, workspace, tools=serving.tools(TOOL_ROW) if tools is None else tools,
                                       role=ROLE, node_id=node, attempt=1, max_calls=10, retrieval=configuration)


def test_production_startup_from_settings_serves_once_with_authenticated_bytes(base, monkeypatch):
    from ravel.workflow import literature_mcp
    settings = installation(base, monkeypatch)
    tools = serving.tools(TOOL_ROW)
    configuration = settings_loader.for_tools(tools, settings.path)
    assert isinstance(configuration, serving.Serving)
    assert configuration.index['manifest_sha256'] == settings.snapshot['manifest']['manifest_sha256']
    run = make_run(base)
    made = production(run, 'worker', configuration)
    mcp = broker_mcp.Server(tools, made.call, literature_output=literature_mcp.projector(made.workspace))
    result = mcp.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                         'params': {'name': 'literature_search', 'arguments': args('search')}})['result']
    reply = result['structuredContent']
    assert result['isError'] is False and reply['status'] == 'ok'
    raw = serving.load(run, reply)
    assert result['content'][-1]['text'].encode() == raw
    assert json.loads(raw)['index']['manifest_sha256'] == configuration.index['manifest_sha256']
    assert [r['event'] for r in ledger(run)] == ['admitted', 'served']
    assert QUERIES == [1] and len(made.verify_ledger()) == 1
    report = serving.audit(run)
    assert [c['outcome'] for c in report['calls']] == ['delivered']
    # A toolbelt without a literature tool never reads the settings, even a damaged document.
    settings.path.write_text('{')
    assert settings_loader.for_tools([t for t in tools if False], settings.path) is None


@pytest.mark.parametrize('arguments', [
    {'op': 'search', 'args': {**args('search'), 'index_root': '/elsewhere'}},
    {'op': 'search', 'args': {**args('search'), 'provider': 'local'}},
    {'op': 'search', 'args': {**args('search'), 'source_root': '/elsewhere'}},
    {'op': 'search', 'args': args('search'), 'provider': 'local'},
    {'op': 'search', 'args': args('search'), 'qualification': {'provider_id': 'remote'}},
])
def test_worker_specified_roots_or_providers_are_schema_violations(base, monkeypatch, arguments):
    settings = installation(base, monkeypatch)
    configuration = settings_loader.from_settings(settings.path)
    run = make_run(base)
    made = bind(run, configuration)
    reply = made.call({'call_id': 'w1', 'action': serving.ACTION, 'args': arguments})
    assert reply['status'] == 'refused' and reply['error']['code'] == 'schema_violation', reply
    assert [r['event'] for r in ledger(run)] == ['denied'] and written(made) == []
    assert QUERIES == []
    # The production broker's guard refuses the same widened call before the handler.
    guarded = production(run, 'guarded', configuration)
    assert guarded.call({'call_id': 'w2', 'action': serving.ACTION, 'args': arguments})['error']['code'] == 'not_allowlisted'


@pytest.mark.parametrize('case', ['absent record', 'other provider', 'invalid settings', 'unknown provider',
                                  'graph enabled', 'missing cursor key', 'models unavailable'])
def test_unqualified_settings_refuse_every_call_with_a_receipt(base, monkeypatch, case):
    settings = installation(base, monkeypatch, qualification=case != 'absent record')
    document = json.loads(settings.path.read_text())
    if case == 'other provider':
        record = json.loads((settings.root / 'qualification.json').read_text())
        (settings.root / 'qualification.json').write_text(json.dumps(requalify(record, provider_id='remote-fiction')))
    elif case == 'invalid settings':
        document['retrieval']['endpoint'] = 'https://elsewhere.invalid'
    elif case == 'unknown provider':
        document['retrieval']['provider'] = 'mcp'
    elif case == 'graph enabled':
        document['retrieval']['graph'] = True
    elif case == 'missing cursor key':
        (settings.root / 'cursor.key').unlink()
    elif case == 'models unavailable':
        from ravel.workflow import literature_models

        def unavailable(**_):
            raise literature_models.ModelError('fictional model is not installed')
        monkeypatch.setattr(literature_models, 'Embedder', unavailable)
    settings.path.write_text(json.dumps(document))
    configuration = settings_loader.from_settings(settings.path)
    assert configuration is not None
    run = make_run(base)
    made = production(run, 'worker', configuration)
    reply = made.call(toolbelt.to_request(serving.tools(TOOL_ROW), 'literature_search', args('search'), 'q1'))
    assert reply['status'] == 'refused' and reply['error']['code'] == 'provider_unqualified', reply
    last = ledger(run)[-1]
    assert last['event'] == 'denied' and last['code'] == 'provider_unqualified' and written(made) == []
    assert QUERIES == []
    assert made.call({'call_id': 'r1', 'action': serving.REPLAY_ACTION,
                      'args': {'serving_id': 'serving:1'}})['error']['code'] == 'not_allowlisted'


@pytest.mark.parametrize('case', ['moved', 'unknown pin', 'corrupt snapshot'])
def test_stale_or_missing_indexes_refuse_with_a_receipt(base, monkeypatch, case):
    settings = installation(base, monkeypatch)
    pinned = settings.snapshot['manifest']['manifest_sha256']
    if case == 'moved':
        store.update_index(settings.index_root, make_corpus(settings.source_root, {'alder': PAPERS['alder']}),
                           embedder=settings.embedder, reranker_identity=settings.reranker.identity)
    elif case == 'unknown pin':
        document = json.loads(settings.path.read_text())
        document['retrieval']['index_manifest_sha256'] = '5' * 64
        settings.path.write_text(json.dumps(document))
    else:
        (settings.index_root / 'snapshots' / pinned / 'corpus.json').write_text('{}')
    configuration = settings_loader.from_settings(settings.path)
    if case == 'moved':
        assert isinstance(configuration, serving.Serving) and configuration.index['manifest_sha256'] == pinned
    else:
        assert isinstance(configuration, serving.ConfigurationRefusal)
    run = make_run(base)
    made = production(run, 'worker', configuration)
    reply = made.call(toolbelt.to_request(serving.tools(TOOL_ROW), 'literature_search', args('search'), 'q1'))
    assert reply['status'] == 'refused' and reply['error']['code'] == 'stale_index', reply
    assert ledger(run)[-1]['code'] == 'stale_index' and written(made) == []
    assert QUERIES == []


# Captured at the integration base 73a3578 (`knowledge_broker.create` with
# `literature_serving.register(made, None)`): the unconfigured refusal must stay byte-identical.
BASE_UNCONFIGURED_REPLY = (b'{"call_id": "c1", "error": {"code": "retrieval_unavailable", "message": "no literature index '
                           b'is configured; existing knowledge queries are unchanged [serving:1]"}, "outputs": [], '
                           b'"receipt_id": "worker/1/1", "status": "refused", "stdout_tail": ""}')
BASE_UNCONFIGURED_RECORD = {'action': 'literature query',
                            'args_sha256': 'fd0ed15b6db144ee4c0f334212bbc73803ecbf26b7f44420468527b15c5f8999',
                            'code': 'retrieval_unavailable', 'detail': 'no trusted serving configuration is bound',
                            'event': 'denied', 'op': 'search', 'stage': 'admission'}


@pytest.mark.parametrize('case', ['absent document', 'provider off', 'auto without index', 'auto with empty root'])
def test_no_index_installations_refuse_with_the_base_bytes(base, monkeypatch, case):
    path = base / 'settings' / 'settings.json'
    path.parent.mkdir(parents=True)
    section = {'absent document': None, 'provider off': {'provider': 'off', 'index_root': str(base / 'nowhere')},
               'auto without index': {'provider': 'auto'},
               'auto with empty root': {'provider': 'auto', 'index_root': str(base / 'settings')}}[case]
    if section is not None:
        path.write_text(json.dumps({'schema_version': 1, 'kind': settings_loader.SETTINGS_KIND, 'retrieval': section}))
    monkeypatch.setenv(settings_loader.SETTINGS_ENV, str(path))
    tools = serving.tools(TOOL_ROW)
    assert settings_loader.settings_path() == path
    configuration = settings_loader.for_tools(tools)
    assert configuration is None
    run = make_run(base)
    made = production(run, 'worker', configuration)
    reply = made.call(toolbelt.to_request(tools, 'literature_search', args('search'), 'c1'))
    assert json.dumps(reply, sort_keys=True).encode() == BASE_UNCONFIGURED_REPLY
    record = {k: v for k, v in ledger(run)[0].items() if k != 'utc'}
    assert record.pop('binding') == {'attempt': 1, 'node_id': 'worker', 'role': ROLE,
                                     'run_id': knowledge_broker.run_id(run)}
    assert record == BASE_UNCONFIGURED_RECORD


def test_settings_document_is_closed_and_needs_absolute_paths():
    good = {'schema_version': 1, 'kind': settings_loader.SETTINGS_KIND, 'retrieval': {'provider': 'off'}}
    assert settings_loader.validate_settings(good)['graph'] is False
    for retrieval in ({'provider': 'remote'}, {'graph': True}, {'index_root': 'relative/index'},
                      {'index_manifest_sha256': 'x'}, {'budgets': []}, {'endpoint': 'x'},
                      {'provider': 'local', 'index_root': '/a'}):
        with pytest.raises(settings_loader.SettingsError):
            settings_loader.validate_settings({**good, 'retrieval': retrieval})
    with pytest.raises(settings_loader.SettingsError):
        settings_loader.validate_settings({**good, 'kind': 'other'})
    with pytest.raises(ValueError):
        serving.ConfigurationRefusal('retrieval_unavailable', 'not a configuration failure')


# ---- the trusted lineage driver: corpus records to a qualified, bindable serving configuration

def lineage_settings(base, **retrieval):
    (base / 'cursor.key').write_bytes(b'c' * 32)
    document = {'schema_version': 1, 'kind': 'ravel-retrieval-settings',
                'retrieval': {'provider': 'auto', 'index_root': str(base / 'index'), 'source_root': str(base),
                              'qualification': str(base / 'qualification.json'),
                              'cursor_key': str(base / 'cursor.key'), **retrieval}}
    path = base / 'settings.json'
    path.write_text(json.dumps(document))
    return path


def lineage_provider(snapshot, *, cursor_key):
    return engine.HybridLiteratureProvider(snapshot, embedder=Embedder(), reranker=Reranker(), cursor_key=cursor_key,
                                           clock=lambda: 0.0)


def test_lineage_driver_keeps_denominator_failures_and_refusals_visible_and_located_exactly(tmp_path, monkeypatch):
    import synthetic_identifiers as syn
    from test_literature_corpus import Clock, connected, exclusion, rule, write
    from ravel.workflow import literature_corpus as corpus, literature_settings, research_cycle as cycle
    monkeypatch.setenv('RAVEL_STATE_DIR', str(Path(os.path.realpath(tmp_path)) / 'state'))
    base, root, host, plan_pin, exclusion_pin, _ = connected(tmp_path, monkeypatch)
    clock = Clock()
    corpus.acquire(plan_pin, exclusion_pin, campaign_root=root, host=host, out=root / 'corpus',
                   sleep=clock.sleep, clock=clock)
    record_pin = cycle._pin(root / 'corpus' / 'record.json')
    # The current list restricts one document through an alias found only in its located text.
    current = write(base / 'current-exclusion.json', exclusion(rule('restricted', {'arxiv': [syn.arxiv(700)]})))
    receipts = {hashlib.sha256(p.read_bytes()).hexdigest(): 'receipt-' + p.name for p in base.rglob('*') if p.is_file()}
    settings = lineage_settings(base)
    built = corpus.build_from_records([record_pin], current, settings=settings, embedder=Embedder(),
                                      reranker_identity=Reranker.identity, receipt_ids=receipts,
                                      provider_factory=lineage_provider)
    record = json.loads(Path(built['record_path']).read_text())
    assert record == built['record'] and record['kind'] == 'literature-index-build-record'
    census = record['census']
    assert census['admitted'] == 3 and census['refused'] == {'restricted:text': 1}
    assert census['acquisition']['planned'] == 4 and census['acquisition']['not_attempted'] == 0
    assert {f['document'] for f in census['acquisition']['failures']} >= {'doc-2', 'doc-3'}
    assert record['papers']['status'] == {'available': 1, 'failed': 1, 'unsupported': 1}
    assert record['terms']['index'] == 'local-only'
    # Refused identities stay in supervisor custody only.
    assert [r['document']['id'] for r in built['refusals']] == ['doc-4']
    assert 'doc-4' not in json.dumps(record) and syn.arxiv(604) not in json.dumps(record)
    snapshot = built['snapshot']
    assert 'doc-4' not in json.dumps(snapshot['corpus']) and snapshot['corpus']['units']
    for unit in snapshot['corpus']['units']:
        row = unit['evidence']
        original = (base / row['original']['path']).read_bytes()
        extraction = None if row['extraction'] is None else (base / row['extraction']['path']).read_bytes()
        contract.verify_excerpt(row, original=original, extraction=extraction)
    assert json.loads((base / 'qualification.json').read_text()) == built['qualification']
    # The settings loader binds the same index and qualification.
    monkeypatch.setattr(literature_settings, '_local_provider',
                        lambda snapshot, *, cursor_key, models_root: lineage_provider(snapshot, cursor_key=cursor_key))
    configuration = literature_settings.from_settings(settings)
    assert isinstance(configuration, serving.Serving), configuration
    assert configuration.index == {'id': snapshot['manifest']['id'],
                                   'manifest_sha256': snapshot['manifest']['manifest_sha256']}
    run = make_run(base)
    made = bind(run, configuration)
    listed = serving.call(made, 'list_papers', args('list_papers', limit=16))
    assert listed['status'] == 'ok', listed
    envelope = located(run, listed)
    assert {p['document_id']: p['acquisition_status'] for p in envelope['metadata']} == {
        'doc-1': 'available', 'doc-2': 'failed', 'doc-3': 'unsupported'}
    assert 'doc-4' not in serving.load(run, listed).decode()
    found = serving.call(made, 'search', args('search', query='fictional located method'))
    assert found['status'] == 'ok' and 'doc-4' not in serving.load(run, found).decode()


def test_lineage_driver_refuses_excluded_roots_and_a_mismatched_pin_before_qualifying(tmp_path, monkeypatch):
    from test_literature_corpus import Clock, connected
    from ravel.workflow import literature_corpus as corpus, literature_settings, research_cycle as cycle
    base, root, host, plan_pin, exclusion_pin, _ = connected(tmp_path, monkeypatch)
    clock = Clock()
    corpus.acquire(plan_pin, exclusion_pin, campaign_root=root, host=host, out=root / 'corpus',
                   sleep=clock.sleep, clock=clock)
    record_pin = cycle._pin(root / 'corpus' / 'record.json')
    receipts = {hashlib.sha256(p.read_bytes()).hexdigest(): 'receipt-' + p.name for p in base.rglob('*') if p.is_file()}
    common = dict(embedder=Embedder(), reranker_identity=Reranker.identity, receipt_ids=receipts,
                  provider_factory=lineage_provider)
    for roots, match in (([str(root / 'corpus')], 'excluded root'), ([str(base / 'index')], 'excluded root')):
        settings = lineage_settings(base, excluded_roots=roots)
        with pytest.raises(ValueError, match=match):
            corpus.build_from_records([record_pin], exclusion_pin, settings=settings, **common)
        assert not (base / 'qualification.json').exists() and not (base / 'index' / 'current.json').exists()
    settings = lineage_settings(base, index_manifest_sha256='0' * 64)
    with pytest.raises(ValueError, match='pin another index manifest'):
        corpus.build_from_records([record_pin], exclusion_pin, settings=settings, **common)
    assert not (base / 'qualification.json').exists()
    with pytest.raises(ValueError, match='provider off'):
        corpus.build_from_records([record_pin], exclusion_pin, settings=lineage_settings(base, provider='off'), **common)


def test_excluded_roots_are_a_closed_list_of_absolute_paths():
    good = {'schema_version': 1, 'kind': settings_loader.SETTINGS_KIND, 'retrieval': {'provider': 'off'}}
    assert settings_loader.validate_settings(good)['excluded_roots'] == []
    roots = ['/fictional/withheld', '/fictional/other']
    accepted = settings_loader.validate_settings({**good, 'retrieval': {'provider': 'off', 'excluded_roots': roots}})
    assert accepted['excluded_roots'] == roots
    for value in ('/fictional/withheld', ['relative/root'], ['/a', '/a'], [''], [None], ['/x'] * 300):
        with pytest.raises(settings_loader.SettingsError):
            settings_loader.validate_settings({**good, 'retrieval': {'provider': 'off', 'excluded_roots': value}})
    for key in ('index_root', 'source_root'):
        with pytest.raises(settings_loader.SettingsError, match='under an excluded root'):
            settings_loader.validate_settings({**good, 'retrieval': {
                'provider': 'off', key: '/fictional/withheld/store', 'excluded_roots': roots}})


def test_the_loader_and_the_index_build_agree_on_one_model_identity(base, monkeypatch):
    settings = installation(base, monkeypatch)
    configuration = settings_loader.from_settings(settings.path)
    assert isinstance(configuration, serving.Serving)
    manifest = configuration.snapshot['manifest']
    assert manifest['embedding'] == settings.embedder.identity and manifest['reranker'] == settings.reranker.identity
    assert {'model_id', 'tokenizer_sha256', 'runtime', 'qualification_sha256'} <= set(manifest['embedding'])
    run = make_run(base)
    made = production(run, 'worker', configuration)
    reply = made.call(toolbelt.to_request(serving.tools(TOOL_ROW), 'literature_search', args('search'), 'q1'))
    assert reply['status'] == 'ok', reply
    # Models qualified under another runtime make the same index unusable: refused, never served.
    from ravel.workflow import literature_models as lm
    loaded = lm.Embedder

    monkeypatch.setattr(lm, 'Embedder', lambda model_id=None, *, root=None, **kw: loaded(model_id, root=root, threads=2))
    other = settings_loader.from_settings(settings.path)
    assert isinstance(other, serving.ConfigurationRefusal) and other.code == 'provider_unqualified'


# ---- excluded origins: the run source view and the serving boundary withhold evaluator-supplied origins

BIRCH = [{'kind': 'document', 'value': 'paper:birch'}]


def test_the_view_withholds_an_excluded_origin_before_ranking(base):
    w = world(base, excluded_origins=BIRCH)
    reply = serving.call(w.broker, 'search', args('search', top_k=8))
    assert reply['status'] == 'ok' and 'paper:birch' not in documents(w.run, reply)
    listed = serving.call(w.broker, 'list_papers', args('list_papers'))
    assert 'paper:birch' not in documents(w.run, listed)
    refused = serving.call(w.broker, 'get_paper', args('get_paper', document_id='paper:birch'))
    assert_denied(w, refused, 'forbidden_source', calls=2)


def test_a_served_row_descending_from_an_excluded_origin_is_forbidden(base):
    w = world(base, excluded_origins=BIRCH)
    w.provider.change = _inject(w, 'paper:birch')
    reply = serving.call(w.broker, 'search', args('search', filters={'document_id': ['paper:alder']}))
    last = assert_denied(w, reply, 'forbidden_source', stage='serving', calls=1)
    assert 'unit:birch:1' in last['detail'] and 'birch' not in reply['error']['message']


def test_the_view_digest_binds_the_excluded_origin_set(base):
    plain = world(base / 'plain')
    origin = world(base / 'origin', excluded_origins=BIRCH)
    views = [w.broker._literature_serving.view(node_id='worker', role=ROLE, attempt=1).policy_sha256
             for w in (plain, origin)]
    assert views[0] != views[1]


def test_the_loader_refuses_an_index_built_under_another_origin_set(base, monkeypatch):
    settings = installation(base, monkeypatch)
    document = json.loads(settings.path.read_text())
    document['retrieval']['excluded_origins'] = [{'kind': 'document', 'value': 'paper:elm'}]
    settings.path.write_text(json.dumps(document))
    refused = settings_loader.from_settings(settings.path)
    assert isinstance(refused, serving.ConfigurationRefusal) and refused.code == 'stale_index'
    # An evaluator-supplied document is read through its absolute path; a malformed one refuses.
    origins = base / 'evaluator' / 'origins.json'
    origins.parent.mkdir()
    origins.write_text(json.dumps({'schema_version': 1, 'kind': settings_loader.ORIGINS_KIND,
                                   'origins': [{'kind': 'run', 'value': 'run-fictional'}]}))
    document['retrieval']['excluded_origins'] = str(origins)
    settings.path.write_text(json.dumps(document))
    assert settings_loader.excluded_origins(settings_loader.validate_settings(document)) == (('run', 'run-fictional'),)
    assert settings_loader.from_settings(settings.path).code == 'stale_index'
    origins.write_text('{"origins": []}')
    assert settings_loader.from_settings(settings.path).code == 'provider_unqualified'
    for bad in ('relative/origins.json', [{'kind': 'paper', 'value': 'x'}], [{'kind': 'document'}]):
        document['retrieval']['excluded_origins'] = bad
        with pytest.raises(settings_loader.SettingsError):
            settings_loader.validate_settings(document)


def test_an_index_built_under_the_configured_origins_is_served(base, monkeypatch):
    from ravel.workflow import literature_models as lm
    settings = installation(base, monkeypatch)
    origins = [{'kind': 'document', 'value': 'paper:elm'}]
    snapshot = store.build_index(base / 'origin-index', make_corpus(settings.source_root), embedder=settings.embedder,
                                 reranker_identity=settings.reranker.identity, excluded_origins=origins)
    provider = settings_loader._local_provider(snapshot, cursor_key=b'c' * 32,
                                               models_root=str(settings.root / 'models'))
    (settings.root / 'qualification.json').write_text(json.dumps(serving.qualify(provider, snapshot)))
    document = json.loads(settings.path.read_text())
    document['retrieval'].update(index_root=str(base / 'origin-index'), excluded_origins=origins,
                                 index_manifest_sha256=snapshot['manifest']['manifest_sha256'])
    settings.path.write_text(json.dumps(document))
    configuration = settings_loader.from_settings(settings.path)
    assert isinstance(configuration, serving.Serving), getattr(configuration, 'detail', None)
    assert configuration.excluded_origins == (('document', 'paper:elm'),)
    assert lm is not None
