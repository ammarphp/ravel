"""Trusted discovery sources and their URL, metadata and identifier laws.

Sources never perform HTTP themselves. The closed registry is caller configuration;
all pages use the existing charged acquisition service and are rederived on replay.
A canonical record has recid, identifiers, title, abstract, years, document_type,
references and linked_hepdata, plus optional provenance/epoch and lookup fields.
``citations_url`` receives a planned page row (direction, size and page included).
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Protocol
from urllib.parse import urlencode, parse_qs, urlsplit

from . import literature_context as lc, literature_discovery as discovery, research_cycle as cycle

_RECID = re.compile(r'[1-9][0-9]{0,15}\Z')
_ARXIV = re.compile(r'(?:arxiv:)?((?:[0-9]{4}\.[0-9]{4,5}|[a-z][a-z0-9.-]*/[0-9]{7}))(v[1-9][0-9]*)?\Z', re.I)
_LINK = re.compile(r'/api/literature/([1-9][0-9]{0,15})\Z')
DIRECTIONS = {'cited_by': 'refersto:recid:{}', 'references': 'citedby:recid:{}'}
SEED_QUERY = 'recid:{}'


class DiscoverySource(Protocol):
    id: str
    capabilities: dict[str, bool]

    def query_url(self, planned_row: dict) -> str: ...
    def citations_url(self, recid: str, page: dict | int) -> str: ...
    def parse_page(self, payload: dict) -> dict: ...
    def identifiers(self, record: dict) -> dict[str, list[str]]: ...


def _list(metadata, name):
    """A provider list field, or empty when absent or malformed; secondary metadata never crashes a replay."""
    value = metadata.get(name)
    return value if type(value) is list else []


def _record_identifiers(recid, metadata):
    arxiv = []
    for row in _list(metadata, 'arxiv_eprints'):
        value = row.get('value') if type(row) is dict else None
        if type(value) is str and value:
            arxiv += [value, 'arXiv:' + value]
    hepdata = ['ins' + recid] + [str(r.get('value')) for r in _hepdata_rows(metadata)]
    reports = [r.get('value') for r in _list(metadata, 'report_numbers')
               if type(r) is dict and type(r.get('value')) is str and r['value']]
    return {'inspire': [recid, 'ins' + recid, 'INSPIRE:' + recid], 'arxiv': arxiv, 'hepdata': hepdata,
            'analysis': reports}


def _query_identifiers(text):
    """Identifiers a query names literally; a query naming a restricted source is refused before access."""
    tokens = [t for t in re.split(r'[\s"()]+', text) if t]
    found = {'inspire': [], 'arxiv': [], 'hepdata': [], 'analysis': []}
    for token in tokens:
        for part in [token, *token.split(':')]:
            if _RECID.match(part):
                found['inspire'].append(part); found['hepdata'].append('ins' + part)
            elif _ARXIV.fullmatch(part):
                found['arxiv'].append(part)
            elif part:
                found['analysis'].append(part)
    return {k: list(dict.fromkeys(v)) for k, v in found.items()}


def _strings(value):
    return type(value) is list and all(type(v) is str for v in value)


def _field(metadata, name, key):
    rows = metadata.get(name)
    if type(rows) is list and rows and type(rows[0]) is dict and type(rows[0].get(key)) is str and rows[0][key].strip():
        return rows[0][key]
    return None


def _years(metadata):
    years = set()
    for value in (metadata.get('preprint_date'), metadata.get('earliest_date')):
        if type(value) is str and re.match(r'[0-9]{4}', value):
            years.add(int(value[:4]))
    for row in _list(metadata, 'publication_info'):
        if type(row) is dict and type(row.get('year')) is int and 1000 <= row['year'] <= 9999:
            years.add(row['year'])
    return sorted(years)


def _hepdata_rows(metadata):
    return [r for r in _list(metadata, 'external_system_identifiers') if type(r) is dict
            and str(r.get('schema', '')).upper() == 'HEPDATA' and type(r.get('value')) in (str, int)]


def _linked_references(metadata):
    found = set()
    for row in _list(metadata, 'references'):
        ref = row.get('record', {}).get('$ref') if type(row) is dict and type(row.get('record')) is dict else None
        match = _LINK.search(ref) if type(ref) is str else None
        if match: found.add(match.group(1))
    return found


def inspire_record(hit):
    """Project original metadata without replacing its retained provenance fields."""
    recid, metadata = hit['recid'], hit['metadata']
    linked = []
    for i, row in enumerate(_list(metadata, 'external_system_identifiers')):
        if row in _hepdata_rows(metadata):
            linked.append({'ref': str(row['value']),
                           'identifiers': {'hepdata': [str(row['value'])], 'inspire': [recid]},
                           'pointer': f'/metadata/external_system_identifiers/{i}'})
    return {**deepcopy(hit), 'identifiers': _record_identifiers(recid, metadata),
            'title': _field(metadata, 'titles', 'title'), 'abstract': _field(metadata, 'abstracts', 'value'),
            'years': _years(metadata),
            'document_type': list(metadata['document_type']) if _strings(metadata.get('document_type')) else None,
            'references': sorted(_linked_references(metadata)), 'linked_hepdata': linked,
            'citation_count': metadata.get('citation_count'),
            'graph_identifiers': {'inspire': [recid],
                                  'arxiv': [r.get('value') for r in _list(metadata, 'arxiv_eprints')
                                            if type(r) is dict]},
            'field_pointers': {'title': '/metadata/titles/0/title', 'abstract': '/metadata/abstracts/0/value'}}


class InspireSource:
    id = 'inspire'
    capabilities = {'citations': True, 'natural_language': False}

    def query_url(self, planned_row):
        row = planned_row
        purpose = row.get('purpose', {})
        if purpose.get('kind') == 'expansion':
            return self.citations_url(purpose['node'], row)
        query = (' or '.join(SEED_QUERY.format(s) for s in purpose['seeds'])
                 if purpose.get('kind') == 'seed' else row['query'])
        return discovery.API + '?' + urlencode({'q': query, 'size': row['size'], 'page': row['page'],
                                                'format': 'json'})

    def citations_url(self, recid, page):
        if type(page) is int:
            page = {'page': page, 'size': 10, 'purpose': {'direction': 'cited_by'}}
        query = DIRECTIONS[page['purpose']['direction']].format(recid)
        return discovery.API + '?' + urlencode({'q': query, 'size': page['size'], 'page': page['page'],
                                                'format': 'json'})

    def parse_page(self, payload):
        container = payload['hits']
        rows = container['hits']
        if type(rows) is not list:
            raise ValueError('literal complete provider page required')
        records = [inspire_record(discovery._record(row)) for row in rows]
        total, relation = container.get('total'), 'unknown'
        if type(total) is int and total >= len(rows):
            relation = 'eq'
        elif (type(total) is dict and type(total.get('value')) is int and total['value'] >= len(rows)
              and total.get('relation') in {'eq', 'gte'}):
            total, relation = total['value'], total['relation']
        else:
            total = None
        return {'records': records, 'total': total, 'total_relation': relation,
                'next': True if total is not None and total > len(rows) else None}

    def identifiers(self, record):
        return _record_identifiers(record['recid'], record['metadata'])


SOURCES = {'inspire': InspireSource}


def source_for(name=None) -> DiscoverySource:
    """Resolve only trusted registered names; scope documents never select a source."""
    name = 'inspire' if name is None else name
    if type(name) is not str or name not in SOURCES:
        raise ValueError('discovery_source_unknown')
    source = SOURCES[name]()
    if (source.id != name or type(source.capabilities) is not dict
            or set(source.capabilities) != {'citations', 'natural_language'}
            or any(type(v) is not bool for v in source.capabilities.values())
            or any(not callable(getattr(source, method, None))
                   for method in ('query_url', 'citations_url', 'parse_page', 'identifiers'))):
        raise ValueError('discovery_source_unknown: invalid registered source contract')
    return source


def planned_query(source, row):
    """Legacy query spelling for receipts; source URL construction remains authoritative."""
    if isinstance(source, InspireSource) and (row['purpose']['kind'] != 'expansion'
                                            or source.capabilities['citations']):
        return parse_qs(urlsplit(source.query_url(row)).query)['q'][0]
    return row['query']


def valid_seed(source, seed):
    if isinstance(source, InspireSource):
        return type(seed) is str and bool(_RECID.fullmatch(seed))
    return type(seed) is str and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,63}', seed))


def seed_identifiers(source, recid):
    if isinstance(source, InspireSource):
        return {'inspire': [recid, 'ins' + recid], 'hepdata': ['ins' + recid]}
    return source.identifiers({'recid': recid, 'identifiers': {source.id: [recid]}})


def record_url(source, recid, record=None):
    if isinstance(source, InspireSource):
        return discovery.API + '/' + recid
    return record.get('lookup_url') if record else None


def source_metadata(source):
    return {'api': discovery.API, 'client_version': discovery.VERSION} if isinstance(source, InspireSource) else {
        'api': None, 'client_version': None}


def request_document(source, binding, scope, row, index):
    url = source.query_url(row)
    limits = scope['limits']
    if type(source) is InspireSource:
        return {'schema_version': 1, 'kind': 'literature-discovery-request',
                'id': f'{scope["id"]}-r{index:04d}', 'cycle_binding': deepcopy(binding),
                'provider': source.id, 'operation': 'query', 'query': parse_qs(urlsplit(url).query)['q'][0],
                'page': row['page'], 'max_results': row['size'], 'discovery': None, 'recid': None,
                'bibliography_selection': None, 'max_bytes': limits['max_response_bytes'],
                'max_seconds': limits['request_seconds'], 'tasks': deepcopy(scope['tasks'])}
    return {'schema_version': 1, 'kind': 'literature-acquisition', 'url': url, 'format': 'text',
            'expected_sha256': None, 'max_bytes': limits['max_response_bytes'],
            'max_seconds': limits['request_seconds'], 'tasks': deepcopy(scope['tasks'])}


def _page_result(source, acquired, reader, row):
    result = {'source': source.id, 'operation': 'query', 'request_url': acquired['url'],
              'status': 'failed' if acquired['status'] == 'failed' else 'unresolved',
              'reason': acquired['failure'], 'records': [], 'remote_total': None,
              'remote_total_relation': 'unknown', 'next': None}
    if acquired['status'] != 'acquired':
        return result
    _, raw = reader.read(acquired['source_artifact'])
    try:
        parsed = source.parse_page(lc.knowledge._json(raw))
        records = parsed['records']
        if (type(records) is not list or len(records) > row['size']
                or len({r['recid'] for r in records}) != len(records)):
            raise ValueError('ambiguous or oversized provider page')
        total = parsed['total']
        if total is not None and (type(total) is not int or total < len(records)):
            raise ValueError('invalid provider total')
        result.update(records=records, remote_total=total,
                      remote_total_relation=parsed.get('total_relation', 'eq' if total is not None else 'unknown'),
                      next=parsed['next'], status='discovered', reason=None)
    except (ValueError, KeyError, TypeError) as exc:
        result.update(status='unresolved', reason='Provider metadata unresolved: ' + str(exc))
    return result


def execute_page(source, root, request, out, host, row, *, max_wall_seconds):
    """One ordinary charged GET, with a pinned wrapper for nonlegacy sources."""
    from . import research_tools as tools
    if type(source) is InspireSource:
        return tools.discover_literature(root, request, out, host, max_wall_seconds=max_wall_seconds)
    _, campaign = cycle._load(root)
    reader = lc._Reader(campaign['base_dir'])
    out = tools._destination(root, out)
    out.mkdir(); (out / 'metadata').mkdir()
    actual = tools.acquire_literature(root, request, out / 'charged-acquisition', host,
                                      max_wall_seconds=max_wall_seconds)
    acquired = lc.consume_acquisition(actual['binding'], base_dir=reader.base, _reader=reader)
    document = {'source': source.id, 'request': deepcopy(request), 'row': deepcopy(row),
                'binding': actual['binding'], 'producer': cycle._pin(__file__),
                'result': _page_result(source, acquired, reader, row)}
    product = lc._emit(out / 'metadata' / 'product.json', lc._raw(document), reader)
    return {'product': product}


def consume_page(source, product, *, base_dir, row, expected_request):
    """Recompute from authenticated bytes, enforcing source identity and the current URL law."""
    reader = lc._Reader(base_dir)
    if type(source) is InspireSource:
        original = discovery.consume(product, base_dir=base_dir)['result']
        if original['provider'] != source.id or original['operation'] != 'query':
            raise ValueError('discovery source differs from its product')
        if original['request_url'] != source.query_url(row):
            raise ValueError('discovery product differs from its planned query page')
        # Keep the legacy client's exact failure status and total semantics.
        records = [inspire_record(hit) for hit in original['hits']]
        if original['status'] == 'discovered':
            _, raw = reader.read(original['raw_response'])
            records = source.parse_page(lc.knowledge._json(raw))['records']
        return {**original, 'source': source.id, 'records': records,
                'next': True if original['remote_total'] is not None
                and original['remote_total'] > row['page'] * row['size'] else None}
    _, document = reader.document(product)
    lc._keys(document, ('source', 'request', 'row', 'binding', 'producer', 'result'))
    if document['source'] != source.id or document['row'] != row or document['producer'] != cycle._pin(__file__):
        raise ValueError('discovery source or planned page differs from its product')
    _, request = lc._acquisition_request(document['request'], reader)
    acquired = lc.consume_acquisition(document['binding'], base_dir=base_dir, _reader=reader)
    if (request != expected_request or acquired['request'] != document['request']
            or acquired['request_value'] != request or acquired['url'] != source.query_url(row)):
        raise ValueError('discovery source URL/limits differ from its planned query page')
    result = _page_result(source, acquired, reader, row)
    if document['result'] != result:
        raise ValueError('discovery source metadata differs from authentic raw response')
    return result
