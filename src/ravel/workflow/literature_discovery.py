"""INSPIRE discovery metadata through the existing charged public GET service.

Independently implemented from the official REST API and HEP schema docs.
A query page is not a literature read or an identity/relevance certificate.
No HTTP client, search scheduler, credential discovery or synthetic bibliography.
"""
from copy import deepcopy
from pathlib import Path
import re
from urllib.parse import urlencode

from . import literature_context as lc, research_cycle as cycle

PROVIDER = 'inspire'
ORIGIN = 'https://inspirehep.net'
API = ORIGIN + '/api/literature'
VERSION = 'inspire-located-discovery/v1'
MAX_RESPONSE_BYTES = 512 * 1024  # Leaves space for lossless derived metadata within the existing 2MiB JSON contract.
FIELDS = ('titles', 'authors', 'publication_info', 'preprint_date', 'dois',
          'arxiv_eprints', 'documents', 'urls')
CLAIMS = {**lc.FLAGS, 'bibliography_verified': False, 'relevance_verified': False}


def _recid(value):
    if type(value) is not str or not re.fullmatch(r'[1-9][0-9]{0,15}', value):
        raise ValueError('literal positive INSPIRE record ID required')
    return value


def _request(pin, reader):
    pin, value = reader.document(pin)
    lc._keys(value, ('schema_version', 'kind', 'id', 'cycle_binding', 'provider',
                     'operation', 'query', 'page', 'max_results', 'discovery', 'recid',
                     'bibliography_selection', 'max_bytes', 'max_seconds', 'tasks'))
    if type(value['schema_version']) is not int or value['schema_version'] != 1 or value['kind'] != 'literature-discovery-request':
        raise ValueError('literature-discovery-request/v1 required')
    lc.knowledge._id(value['id'])
    if len(value['id']) > 48 or value['provider'] != PROVIDER:
        raise ValueError('finite supported provider and bounded document identity required')
    if value['cycle_binding'] is None:
        raise ValueError('discovery must retain the original campaign assignment')
    lc._scope(value['cycle_binding'], reader)
    lc._integer(value['max_bytes'], MAX_RESPONSE_BYTES)
    lc._integer(value['max_seconds'], 3600)
    if value['operation'] == 'query':
        lc.knowledge._text(value['query'], 2048)
        lc._integer(value['page'], 100); lc._integer(value['max_results'], 25)
        if any(value[k] is not None for k in ('discovery', 'recid', 'bibliography_selection')):
            raise ValueError('query cannot fabricate a selected record')
        url = API + '?' + urlencode({'q': value['query'], 'size': value['max_results'], 'page': value['page'], 'format': 'json'})
    elif value['operation'] == 'record':
        _recid(value['recid'])
        if any(value[k] is not None for k in ('query', 'page', 'max_results')) or value['discovery'] is None:
            raise ValueError('explicit selected query hit and exact record lookup required')
        lc._keys(value['bibliography_selection'], ('title_index', 'year_pointer'))
        title = value['bibliography_selection']['title_index']
        if title is not None: lc._integer(title, 1024, 0)
        year = value['bibliography_selection']['year_pointer']
        if year is not None and (type(year) is not str or not re.fullmatch(r'/metadata/(?:publication_info/[0-9]+/year|preprint_date)', year)):
            raise ValueError('explicit original year location required')
        url = API + '/' + value['recid'] + '?format=json'
    else:
        raise ValueError('query or explicit record operation required')
    lc._url(url)
    acquisition = {'schema_version': 1, 'kind': 'literature-acquisition', 'url': url,
        'format': 'text', 'expected_sha256': None, 'max_bytes': value['max_bytes'],
        'max_seconds': value['max_seconds'], 'tasks': deepcopy(value['tasks'])}
    # The existing service remains the sole task/network/framing validator.
    lc._request({'schema_version': 1, 'kind': 'literature-context-request', 'id': value['id'],
        'cycle_binding': value['cycle_binding'], 'documents': [], 'query': {'text': 'Discovery metadata only',
        'tags': [], 'roots': [], 'domain': [], 'max_nodes': 1}, 'annotations': [], 'hypotheses': [],
        'edges': [], 'acquisition_tasks': value['tasks']})
    return pin, value, acquisition


def _record(row):
    if type(row) is not dict or type(row.get('metadata')) is not dict:
        raise ValueError('literal complete provider record required')
    identity = row.get('id')
    if type(identity) is int: identity = str(identity)
    _recid(identity)
    control = row['metadata'].get('control_number')
    if type(control) is not int or str(control) != identity:
        raise ValueError('record ID and original control_number disagree')
    return {'recid': identity, 'metadata': deepcopy(row['metadata']),
        'updated': row.get('updated'), 'created': row.get('created'),
        'version_known': type(row.get('updated')) is str and bool(row['updated']),
        'lookup_url': API + '/' + identity + '?format=json'}


def _bibliography(record, selection):
    """Literal original fields only; ambiguity yields no writer citation."""
    m = record['metadata']; unknown = []
    titles = m.get('titles', [])
    if type(titles) is not list: titles = []; unknown.append('Malformed original titles')
    index = selection['title_index']
    if index is None and len(titles) == 1: index = 0
    title = None
    if index is not None and index < len(titles) and type(titles[index]) is dict:
        title = titles[index].get('title')
    if type(title) is not str or not title.strip(): unknown.append('Title is missing or requires an explicit original-version choice'); title = None
    authors = []
    supplied = m.get('authors')
    if type(supplied) is not list or not supplied:
        unknown.append('Complete original author roster missing')
    else:
        for author in supplied:
            if type(author) is not dict:
                unknown.append('Malformed original contributor'); continue
            roles = author.get('inspire_roles', ['author'])
            if type(roles) is not list or not roles or not set(roles) <= {'author', 'editor', 'supervisor'}:
                unknown.append('Unknown original contributor role'); continue
            if 'author' in roles:
                name = author.get('full_name')
                if type(name) is not str or not name.strip(): unknown.append('Original author name missing')
                else: authors.append(name)
        if not authors: unknown.append('Original author roster has no declared authors')
    pointer = selection['year_pointer']; year = None
    candidates = [(i, r['year']) for i, r in enumerate(m.get('publication_info', []))
                  if type(r) is dict and type(r.get('year')) is int and 1000 <= r['year'] <= 9999] if type(m.get('publication_info', [])) is list else []
    if pointer is None and len({y for _, y in candidates}) == 1:
        pointer = '/metadata/publication_info/' + str(candidates[0][0]) + '/year'
    if pointer is not None:
        from . import decision_case
        try: original = decision_case.pointer({'metadata': m}, pointer)
        except (KeyError, ValueError, IndexError, TypeError): original = None
        if pointer.endswith('/preprint_date') and type(original) is str and re.fullmatch(r'[0-9]{4}(?:-[0-9]{2}(?:-[0-9]{2})?)?', original):
            year = original[:4]
        elif type(original) is int and 1000 <= original <= 9999: year = str(original)
    if year is None: unknown.append('Publication/preprint year unresolved; creation/update dates are not publication dates')
    identifiers = ['INSPIRE:' + record['recid']]
    for field, prefix, pattern in [('dois', 'doi:', r'10\.[0-9]{4,9}/[^\s]+'),
                                  ('arxiv_eprints', 'arXiv:', r'(?:[0-9]{4}\.[0-9]{4,5}|[A-Za-z][A-Za-z0-9.-]*(?:-[A-Za-z0-9.-]+)?/[0-9]{7})(?:v[1-9][0-9]*)?')]:
        rows = m.get(field, [])
        if type(rows) is not list: unknown.append('Malformed original ' + field); continue
        for row in rows:
            val = row.get('value') if type(row) is dict else None
            if type(val) is not str or not re.fullmatch(pattern, val): unknown.append('Malformed original ' + field + ' identifier')
            elif prefix + val not in identifiers: identifiers.append(prefix + val)
    return {'bibliography': None if unknown else {'title': title, 'authors': authors, 'year': year, 'identifiers': identifiers},
        'unresolved': unknown, 'selected_title_index': index, 'selected_year_pointer': pointer,
        'uncertainties': ['INSPIRE is secondary metadata; bibliography/relevance and primary full text remain independently unverified.',
                          'No arXiv version, source license, scientific read or author identity beyond supplied provider fields is inferred.']}


def _derive(value, acquisition, reader, previous):
    result = {'provider': PROVIDER, 'operation': value['operation'], 'request_url': acquisition['url'],
        'status': 'failed' if acquisition['status'] == 'failed' else 'unresolved', 'reason': acquisition['failure'],
        'raw_response': acquisition['source_artifact'], 'captured_response': acquisition['captured_body'], 'hits': [], 'remote_total': None,
        'remote_total_relation': 'unknown', 'coverage': 'Only the declared page/record is acquired; no automatic pagination or exhaustive search claim.',
        'selected_record': None, 'resolution': None, 'claims': deepcopy(CLAIMS)}
    if acquisition['status'] != 'acquired': return result
    _, raw = reader.read(acquisition['source_artifact'], value['max_bytes'])
    try:
        document = lc.knowledge._json(raw)
        if value['operation'] == 'query':
            container = document['hits']; rows = container['hits']
            if type(rows) is not list or len(rows) > value['max_results']:
                raise ValueError('provider returned beyond declared complete page size')
            hits = [_record(row) for row in rows]
            result['hits'] = hits
            total = container.get('total')
            if type(total) is int and total >= len(rows):
                result.update(remote_total=total, remote_total_relation='eq')
            elif type(total) is dict and type(total.get('value')) is int and total['value'] >= len(rows) and total.get('relation') in {'eq', 'gte'}:
                result.update(remote_total=total['value'], remote_total_relation=total['relation'])
            if len({h['recid'] for h in hits}) != len(hits):
                raise ValueError('ambiguous repeated provider record ID; no hit may be selected')
            result.update(status='discovered', reason=None)
        else:
            record = _record(document)
            if record['recid'] != value['recid']: raise ValueError('exact lookup returned another record ID')
            selected = next(h for h in previous['hits'] if h['recid'] == value['recid'])
            if any(record['metadata'].get(k) != selected['metadata'].get(k) for k in FIELDS) or record['updated'] != selected['updated']:
                raise ValueError('selected provider record changed since query; retain both epochs and issue a fresh explicit query')
            result['selected_record'] = record
            result['resolution'] = _bibliography(record, value['bibliography_selection'])
            result.update(status='resolved' if result['resolution']['bibliography'] is not None else 'unresolved', reason=None)
    except (ValueError, KeyError, TypeError, IndexError, StopIteration) as exc:
        result.update(status='unresolved', reason=str(exc) or type(exc).__name__)
    return result


def _load_request(pin, reader):
    request, value, derived = _request(pin, reader)
    previous = None
    if value['operation'] == 'record':
        previous = consume(value['discovery'], base_dir=reader.base, _reader=reader)['result']
        if (previous['operation'] != 'query' or previous['status'] != 'discovered'
                or len([h for h in previous['hits'] if h['recid'] == value['recid']]) != 1):
            raise ValueError('selected ID must be one authentic unambiguous query hit')
        _, prior = reader.document(value['discovery'])
        _, prior_request, _ = _request(prior['request'], reader)
        if prior_request['cycle_binding'] != value['cycle_binding'] or prior_request['tasks'] != value['tasks']:
            raise ValueError('record resolution cannot change original campaign or scout obligations')
    return request, value, derived, previous


def execute(root, request_pin, out, host, *, max_wall_seconds):
    """One requested page/record; original Graph owns all GET admission/charges."""
    from . import research_tools as tools
    _, state = cycle._load(root); reader = lc._Reader(state['base_dir'])
    request, value, derived, previous = _load_request(request_pin, reader)
    expected = {'root': str(cycle._ordinary(root)), 'contract_sha256': cycle.ce.digest(state['contract'])}
    if value['cycle_binding'] != expected: raise ValueError('query belongs to another original assignment')
    out = tools._destination(root, out); out.mkdir()
    metadata = out / 'metadata'; metadata.mkdir()
    derived_pin = lc._emit(metadata / 'acquisition-request.json', lc._raw(derived), reader)
    actual = tools.acquire_literature(root, derived_pin, out / 'charged-acquisition', host, max_wall_seconds=max_wall_seconds)
    acquired = lc.consume_acquisition(actual['binding'], base_dir=reader.base, _reader=reader)
    result = _derive(value, acquired, reader, previous)
    producer, _ = reader.read(cycle._pin(__file__), lc.MAX_JSON_BYTES)
    document = {'schema_version': 1, 'kind': 'literature-discovery-result', 'request': request,
        'acquisition_request': derived_pin, 'binding': actual['binding'], 'producer': producer,
        'source_version': VERSION, 'result': result}
    product = lc._emit(metadata / 'product.json', lc._raw(document), reader)
    reader.finish(populations=((metadata, [derived_pin, product]),))
    returned = consume(product, base_dir=reader.base)
    return {'product': product, **deepcopy(returned)}


def consume(product_pin, *, base_dir, _reader=None):
    """Reconstruct every field from current authenticated original response."""
    reader = _reader or lc._Reader(base_dir)
    product, document = reader.document(product_pin)
    lc._keys(document, ('schema_version', 'kind', 'request', 'acquisition_request', 'binding', 'producer', 'source_version', 'result'))
    if document['schema_version'] != 1 or document['kind'] != 'literature-discovery-result' or document['source_version'] != VERSION:
        raise ValueError('actual current discovery product required')
    producer, _ = reader.read(document['producer'], lc.MAX_JSON_BYTES)
    if producer != cycle._pin(__file__): raise ValueError('foreign discovery adapter cannot certify provider metadata')
    _, value, expected, previous = _load_request(document['request'], reader)
    _, derived = lc._acquisition_request(document['acquisition_request'], reader)
    acquisition = lc.consume_acquisition(document['binding'], base_dir=base_dir, _reader=reader)
    if derived != expected or acquisition['request_value'] != expected or acquisition['request'] != document['acquisition_request']:
        raise ValueError('provider URL/query/limits differ from original typed discovery request')
    result = _derive(value, acquisition, reader, previous)
    if document['result'] != result: raise ValueError('discovery metadata differs from authentic raw response')
    reader.finish(populations=((Path(product['path']).parent, [product, document['acquisition_request']]),))
    return {'result': deepcopy(result), 'claims': deepcopy(CLAIMS)}


def prepare_sources(root, product_pin, out, *, reason):
    """Current metadata to located source and ordinary writer citation fields.

    Primary paper acquisition/extraction and methodological reading remain the
    existing next services. This secondary record cannot close those obligations.
    """
    from . import research_tools as tools
    _, state = cycle._load(root); reader = lc._Reader(state['base_dir'])
    consumed = consume(product_pin, base_dir=reader.base, _reader=reader)
    _, document = reader.document(product_pin); _, value, _, _ = _load_request(document['request'], reader)
    result = consumed['result']
    if result['operation'] != 'record' or result['status'] != 'resolved':
        raise ValueError('unresolved metadata cannot supply a complete writer bibliography')
    binding = {'root': str(cycle._ordinary(root)), 'contract_sha256': cycle.ce.digest(state['contract'])}
    if value['cycle_binding'] != binding: raise ValueError('bibliography belongs to another original campaign')
    out = tools._destination(root, out); out.mkdir()
    metadata = out / 'metadata'; metadata.mkdir()
    record = result['selected_record']; identity = value['id'] + '-metadata'
    doc = {'id': identity, 'pin': result['raw_response'], 'citation': result['request_url'],
        'version': 'Actual acquired provider record; updated=' + str(record['updated']) + '; content SHA256=' + result['raw_response']['sha256'],
        'license': 'Not inferred; consult original provider terms and underlying source rights',
        'access': 'Actual configured public GET; secondary metadata, not primary full text',
        'format': 'text', 'status': 'supplied', 'reason': None, 'parents': [], 'extraction': None,
        'acquisition': document['binding'], 'tags': ['bibliographic-metadata'], 'domain': [],
        'conventions': ['Secondary provider metadata; no scientific read claim'],
        'task_ids': [t['obligation_id'] for t in value['tasks']]}
    located_request = {'schema_version': 1, 'kind': 'literature-context-request', 'id': value['id'],
        'cycle_binding': binding, 'documents': [doc], 'query': {'text': 'Locate complete acquired bibliographic record',
        'tags': [], 'roots': [], 'domain': [], 'max_nodes': 512}, 'annotations': [], 'hypotheses': [],
        'edges': [], 'acquisition_tasks': deepcopy(value['tasks'])}
    pin = lc._emit(metadata / 'located-request.json', lc._raw(located_request), reader)
    context = tools.prepare_literature_context(root, pin, out / 'located', reason=reason)
    citation = {'id': value['id'], 'bibliography': deepcopy(result['resolution']['bibliography']),
        'identity_evidence': [{'source_role': 'secondary', 'source_url': result['request_url'],
            'located': {'artifact': result['raw_response'], 'format': 'json', 'location': '/metadata', 'value': deepcopy(record['metadata'])}}],
        'uncertainties': deepcopy(result['resolution']['uncertainties'])}
    # Same public source locator the author/integrity consumer will re-read.
    from . import report_integrity
    report_integrity._located(citation['identity_evidence'][0]['located'], reader.base, {})
    handoff = {'discovery': deepcopy(product_pin), 'located_context': context, 'citation': citation,
        'primary_paper_required': True, 'claims': deepcopy(CLAIMS)}
    handoff_pin = lc._emit(metadata / 'handoff.json', lc._raw(handoff), reader)
    reader.finish(populations=((metadata, [pin, handoff_pin]),))
    lc.consume(context['product'], base_dir=reader.base)
    consume(product_pin, base_dir=reader.base)
    reader.finish(populations=((metadata, [pin, handoff_pin]),))
    return {**handoff, 'handoff': handoff_pin}
