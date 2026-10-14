"""Prospective connected software controls; no authentic live search is claimed.

Root alone runs these. Scripted HTTPS responses pass through the REAL current
Host/Graph/campaign acquisition and receipt consumer, not invented bindings.
"""
import synthetic_identifiers as syn
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from ravel.workflow import agent_host, literature_context as lc
from ravel.workflow import literature_discovery as discovery, research_tools as tools
from ravel.workflow import research_cycle as cycle, research_coordinator_decisions as decisions
from ravel.workflow import report_integrity
from test_research_cycle import contract, write
from test_literature_context import scripted_transport, task


def record(recid='123', title='A μ source method'):
    return {'id': recid, 'created': '2021-01-01T00:00:00', 'updated': '2024-01-02T00:00:00',
        'links': {'self': discovery.API + '/' + recid}, 'metadata': {
        'control_number': int(recid), 'titles': [{'title': title}],
        'authors': [{'full_name': 'Original, Author'}], 'publication_info': [{'year': 2021}],
        'dois': [{'value': '10.1234/Original'}], 'arxiv_eprints': [{'value': (syn.arxiv(545))}],
        'urls': [{'value': 'https://papers.example.org/original'}]}}


def page(*records, total=None):
    return {'hits': {'total': len(records) if total is None else total, 'hits': list(records)},
            'links': {'next': 'https://untrusted.example.org/do-not-follow'}}


def setup(tmp_path):
    base = tmp_path.resolve(); root = base / 'campaign'
    cycle.create(root, contract(base), base_dir=base, evaluation_harness=True)
    host = agent_host.AgentHost(timeout_seconds=30, literature_origins=[discovery.ORIGIN])
    return base, root, host


def request(base, root, *, operation='query', prior=None, recid=None, selection=None, **updates):
    _, state = cycle._load(root)
    value = {'schema_version': 1, 'kind': 'literature-discovery-request', 'id': 'source-method',
        'cycle_binding': {'root': str(root), 'contract_sha256': cycle.ce.digest(state['contract'])},
        'provider': 'inspire', 'operation': operation, 'query': 'title "μ method"' if operation == 'query' else None,
        'page': 1 if operation == 'query' else None, 'max_results': 5 if operation == 'query' else None,
        'discovery': prior, 'recid': recid,
        'bibliography_selection': {'title_index': None, 'year_pointer': None} if operation == 'record' else None,
        'max_bytes': 200000, 'max_seconds': 20, 'tasks': [task()]}
    if selection is not None: value['bibliography_selection'] = selection
    value.update(updates)
    return write(base / (operation + '-' + str(len(list(base.glob(operation + '-*.json')))) + '.json'), value)


def acquire(monkeypatch, root, req, host, out, payload, **options):
    raw = json.dumps(payload, ensure_ascii=False).encode() if type(payload) is not bytes else payload
    calls = scripted_transport(monkeypatch, raw, **options)
    returned = tools.discover_literature(root, req, root / out, host, max_wall_seconds=30)
    return returned, calls, raw


def query(monkeypatch, tmp_path, payload=None):
    base, root, host = setup(tmp_path)
    result, calls, raw = acquire(monkeypatch, root, request(base, root), host, 'query', page(record()) if payload is None else payload)
    return base, root, host, result, calls, raw


def test_actual_query_record_located_context_and_writer_citation(monkeypatch, tmp_path):
    base, root, host, found, calls, raw = query(monkeypatch, tmp_path, page(record(), record('456'), total=100))
    assert calls[0]['target'] == '/api/literature?q=title+%22%CE%BC+method%22&size=5&page=1&format=json'
    assert len(calls) == 1 and [h['recid'] for h in found['result']['hits']] == ['123', '456']
    assert found['result']['remote_total'] == 100 and not any(found['claims'].values())
    assert Path(found['result']['raw_response']['path']).read_bytes() == raw
    resolved, calls, _ = acquire(monkeypatch, root, request(base, root, operation='record', prior=found['product'], recid='123'), host, 'record', record())
    assert resolved['result']['status'] == 'resolved' and calls[0]['target'] == '/api/literature/123?format=json'
    handoff = tools.prepare_discovered_sources(root, resolved['product'], root / 'sources', reason='Retain authentic scripted metadata; paper read remains open.')
    assert handoff['citation']['bibliography'] == {'title': 'A μ source method', 'authors': ['Original, Author'], 'year': '2021',
        'identifiers': ['INSPIRE:123', 'doi:10.1234/Original', ('arXiv:' + syn.arxiv(545))]}
    assert handoff['citation']['identity_evidence'][0]['source_role'] == 'secondary'
    assert handoff['primary_paper_required'] and not any(handoff['claims'].values())
    context = handoff['located_context']['context']
    assert context['acquisition_tasks'] == [task()] and len(context['documents']) == 1
    assert context['documents'][0]['pin'] == resolved['result']['raw_response']
    located = handoff['citation']['identity_evidence'][0]['located']
    assert report_integrity._located(located, base, {})['value'] == record()['metadata']
    assert lc.consume(handoff['located_context']['product'], base_dir=base) == handoff['located_context']
    # Two real service charges; bibliography preparation introduces no model/API call.
    _, state = cycle._load(root)
    assert len(state['graphs']) == 2 and sum(g['usage']['calls'] for g in state['graphs']) == 2


@pytest.mark.parametrize('mutation', ['wrong-id', 'changed-title', 'changed-version'])
def test_actual_record_refuses_wrong_or_changed_provider_epoch(monkeypatch, tmp_path, mutation):
    base, root, host, found, _, _ = query(monkeypatch, tmp_path)
    row = record()
    if mutation == 'wrong-id': row = record('999')
    elif mutation == 'changed-title': row['metadata']['titles'][0]['title'] = 'Changed source title'
    else: row['updated'] = '2025-01-01T00:00:00'
    actual, _, raw = acquire(monkeypatch, root, request(base, root, operation='record', prior=found['product'], recid='123'), host, 'lookup', row)
    assert actual['result']['status'] == 'unresolved' and actual['result']['reason']
    assert Path(actual['result']['raw_response']['path']).read_bytes() == raw
    with pytest.raises(ValueError, match='unresolved'):
        tools.prepare_discovered_sources(root, actual['product'], root / 'forbidden', reason='Unresolved')


@pytest.mark.parametrize('mutation', ['duplicate-id', 'id-control-mismatch', 'page-overflow', 'malformed-json'])
def test_authentic_ambiguous_or_malformed_page_stays_unresolved(monkeypatch, tmp_path, mutation):
    payload = page(record())
    if mutation == 'duplicate-id': payload = page(record(), record(title='Different title'))
    elif mutation == 'id-control-mismatch': payload['hits']['hits'][0]['metadata']['control_number'] = 999
    elif mutation == 'page-overflow': payload = page(*[record(str(100+i)) for i in range(6)])
    else: payload = b'{not JSON}'
    base, root, host, found, _, raw = query(monkeypatch, tmp_path, payload)
    assert found['result']['status'] == 'unresolved' and found['result']['reason']
    assert Path(found['result']['raw_response']['path']).read_bytes() == raw
    with pytest.raises(ValueError, match='authentic unambiguous'):
        tools.discover_literature(root, request(base, root, operation='record', prior=found['product'], recid='123'), root / 'lookup', host, max_wall_seconds=30)


def test_missing_bibliography_and_explicit_title_choice(monkeypatch, tmp_path):
    row = record(); row['metadata']['titles'].append({'title': 'Published alternate title'})
    base, root, host, found, _, _ = query(monkeypatch, tmp_path, page(row))
    unknown, _, _ = acquire(monkeypatch, root, request(base, root, operation='record', prior=found['product'], recid='123'), host, 'unresolved', row)
    assert unknown['result']['status'] == 'unresolved' and unknown['result']['resolution']['bibliography'] is None
    req = request(base, root, operation='record', prior=found['product'], recid='123', selection={'title_index': 1, 'year_pointer': '/metadata/publication_info/0/year'})
    # Each prospective request is a new immutable source epoch.
    prior_req = json.loads(Path(req['path']).read_text()); distinct = write(base/'explicit-record.json', prior_req)
    chosen, _, _ = acquire(monkeypatch, root, distinct, host, 'selected', row)
    assert chosen['result']['resolution']['bibliography']['title'] == 'Published alternate title'
    assert chosen['result']['resolution']['selected_title_index'] == 1


@pytest.mark.parametrize('field', ['titles', 'authors', 'publication_info'])
def test_missing_fields_never_invent_complete_writer_citation(monkeypatch, tmp_path, field):
    row = record(); row['metadata'].pop(field)
    base, root, host, found, _, _ = query(monkeypatch, tmp_path, page(row))
    result, _, _ = acquire(monkeypatch, root, request(base, root, operation='record', prior=found['product'], recid='123'), host, 'lookup', row)
    assert result['result']['status'] == 'unresolved' and result['result']['resolution']['bibliography'] is None


@pytest.mark.parametrize('options', [{'status': 302, 'headers': {'Location': 'https://untrusted.example.org'}},
                                   {'headers': {'Content-Length': '1000000'}},
                                   {'status': 404}, {'status': 429}])
def test_existing_redirect_framing_and_failure_laws(monkeypatch, tmp_path, options):
    base, root, host = setup(tmp_path)
    result, calls, _ = acquire(monkeypatch, root, request(base, root), host, 'query', b'Partial.', **options)
    assert len(calls) == 1 and result['result']['status'] == 'failed' and result['result']['raw_response'] is None
    assert not any(result['claims'].values())


@pytest.mark.parametrize('mutation', ['raw-response', 'product', 'extra-member'])
def test_current_consumer_detects_changed_response_and_generated_population(monkeypatch, tmp_path, mutation):
    base, root, _, found, _, _ = query(monkeypatch, tmp_path)
    if mutation == 'raw-response': Path(found['result']['raw_response']['path']).write_bytes(b'Changed')
    elif mutation == 'product':
        path = Path(found['product']['path']); value = json.loads(path.read_text()); value['result']['hits'][0]['metadata']['titles'] = [{'title': 'Fabricated'}]
        path.write_text(json.dumps(value))
    else: (Path(found['product']['path']).parent/'late.json').write_text('{}')
    with pytest.raises((ValueError, OSError)):
        discovery.consume(found['product'], base_dir=base)


@pytest.mark.parametrize('updates', [{'provider': 'invented'}, {'max_results': 26}, {'page': 101},
                                    {'query': ''}, {'max_bytes': 2*1024*1024}, {'recid': '123'}])
def test_closed_request_refusals_before_acquisition(tmp_path, monkeypatch, updates):
    base, root, host = setup(tmp_path)
    def never(*a, **k): raise AssertionError('invalid query may not acquire')
    monkeypatch.setattr(tools, 'acquire_literature', never)
    with pytest.raises(ValueError): tools.discover_literature(root, request(base, root, **updates), root/'invalid', host, max_wall_seconds=30)


def test_unseen_selected_identifier_cannot_be_fabricated(monkeypatch, tmp_path):
    base, root, host, found, _, _ = query(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match='authentic unambiguous'):
        tools.discover_literature(root, request(base, root, operation='record', prior=found['product'], recid='999'), root/'invalid', host, max_wall_seconds=30)


def test_real_coordinator_dispatch_preserves_declared_transport(tmp_path, monkeypatch):
    base, root, host = setup(tmp_path); req = request(base, root)
    scripted_transport(monkeypatch, json.dumps(page(record())).encode())
    result = decisions.invoke_extension('literature-discover', root, {'request_pin': req}, root/'query', host, {'max_wall_seconds': 30})
    assert result['result']['status'] == 'discovered' and decisions.EXTENSIONS['literature-discovered-sources'][1] == 'prepare_discovered_sources'
    with pytest.raises(ValueError): decisions.invoke_extension('literature-discover', root, {'request_pin': req, 'fabricated': 1}, root/'invalid', host, {'max_wall_seconds': 30})


def test_repinning_fabricated_hit_does_not_authenticate_it(monkeypatch, tmp_path):
    base, root, _, found, _, _ = query(monkeypatch, tmp_path)
    path = Path(found['product']['path']); doc = json.loads(path.read_text())
    doc['result']['hits'][0]['recid'] = '999'
    changed = write(path, doc)
    with pytest.raises(ValueError, match='metadata differs'):
        discovery.consume(changed, base_dir=base)


def test_failed_prefix_remains_diagnostic_not_source(monkeypatch, tmp_path):
    base, root, host = setup(tmp_path)
    result, _, raw = acquire(monkeypatch, root, request(base, root), host, 'query', b'Partial.', headers={'Content-Length': '100'})
    assert result['result']['raw_response'] is None
    assert Path(result['result']['captured_response']['path']).read_bytes() == raw
    assert result['result']['status'] == 'failed' and not any(result['claims'].values())


def test_actual_handoff_enters_existing_writer_preparation(monkeypatch, tmp_path):
    base, root, host, found, _, _ = query(monkeypatch, tmp_path)
    resolved, _, _ = acquire(monkeypatch, root, request(base, root, operation='record', prior=found['product'], recid='123'), host, 'record', record())
    handoff = tools.prepare_discovered_sources(root, resolved['product'], root/'sources', reason='Actual secondary metadata only')
    from test_manuscript_production import setup as writer_setup
    from ravel.workflow import manuscript_production as mp
    writer_root = base/'writer-fixture'; writer_root.mkdir()
    original, _, _ = writer_setup(writer_root, monkeypatch)
    original['citations'] = [deepcopy(handoff['citation'])]
    original['methods'][0]['citation_ids'] = [handoff['citation']['id']]
    prepared = mp.prepare_writer(original, writer_root/'prepared', base_dir=writer_root, campaign=writer_root/'campaign')
    # The writer reads the complete source context as an authenticated input artifact.
    node = prepared['spec']['nodes'][0]
    context = next(row for row in node['inputs'] if row['id'] == 'context')
    raw = Path(context['path']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == context['sha256']
    presented = raw.decode()
    assert json.dumps('A μ source method')[1:-1] in presented and 'INSPIRE:123' in presented
    assert 'secondary' in presented and 'independently unverified' in presented
    assert not prepared['execution_authorized'] and not (writer_root/'prepared/manuscript.md').exists()
