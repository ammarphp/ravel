"""Candidate literature protocol, independent of the knowledge-kernel version.

Providers are trusted installation adapters, not worker-selected modules. They
must apply the supplied source view before ranking, counting or expanding any
derivative. Only the knowledge broker may expose checked candidates to workers.
This module performs no acquisition, model call, index IO or scientific inference.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
from importlib.resources import files
import json
from functools import lru_cache
from typing import Callable, Literal, Protocol, TypedDict, runtime_checkable

Operation = Literal['search', 'get_paper', 'list_papers', 'compare_measurements']
MAX_BYTES = 512 * 1024
MAX_SOURCE_BYTES = 16 * 1024 * 1024
SCHEMA_VERSION = 1
OPERATIONS = ('search', 'get_paper', 'list_papers', 'compare_measurements')


class Budgets(TypedDict):
    max_tokens: int
    max_bytes: int
    max_seconds: float
    max_expansions: int


class Request(TypedDict):
    schema_version: int
    operation: Operation
    request_id: str
    budgets: Budgets
    args: dict


@dataclass(frozen=True)
class SourceView:
    """Run/role projection supplied by the broker before provider traversal.

    ``permits`` must be applied to complete source/derivative lineage, including
    metadata-only rows, before statistics, ranking, expansion or counts. Its
    argument is a descriptor from retrieval.json. A provider cannot substitute a
    view or clear lineage. The broker rechecks the view at the serving boundary.
    """
    policy_sha256: str
    run_id: str
    node_id: str
    role: str
    attempt: int
    permits: Callable[[dict], bool]


@runtime_checkable
class RetrievalProvider(Protocol):
    """Four bounded, read-only operations returning untrusted candidate envelopes.

    Requests and results use retrieval.json. Index selection and admission are
    trusted configuration. Filters and document scope only narrow the supplied
    view; they never select a provider, index, path, endpoint, credential or
    policy exemption. No method may fetch missing material or invoke a
    generative model/model service. Declared pinned local embedding/reranking
    inference is allowed within the request's budgets. Summaries and deep scoring
    are separate governed operations. Ties use document/version/unit identity.
    Pagination is bound to the exact index, policy, operation and selector args;
    the opaque token must be checked by the provider, never used as a path.
    Missing index configuration leaves existing knowledge APIs unchanged; it
    must not trigger discovery, provisioning or a fabricated index identity.
    """
    provider_id: str

    def search(self, request: Request, *, view: SourceView) -> dict: ...
    def get_paper(self, request: Request, *, view: SourceView) -> dict: ...
    def list_papers(self, request: Request, *, view: SourceView) -> dict: ...
    def compare_measurements(self, request: Request, *, view: SourceView) -> dict: ...


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


@lru_cache(maxsize=8)
def _validator(definition):
    # Schema validation belongs to the serving side. A worker presenting an
    # already-authenticated reply also imports this module's envelope bound.
    from jsonschema import Draft202012Validator, validators
    schema = json.loads(files('ravel.data').joinpath('knowledge/schema/retrieval.json').read_text())
    if definition:
        schema = {'$defs': schema['$defs'], '$ref': '#/$defs/' + definition}
    # Coordinates/counts are Python integers too, not integral floats which
    # JSON Schema would otherwise accept but which cannot index source bytes.
    checker = Draft202012Validator.TYPE_CHECKER.redefine(
        'integer', lambda checker, value: type(value) is int)
    return validators.extend(Draft202012Validator, type_checker=checker)(schema)


def _validate(value, definition=None):
    # Do not accept NaN, infinities, booleans masquerading as integers, or an
    # unbounded serialized population before traversing the schema.
    try:
        valid = len(canonical(value)) <= MAX_BYTES and _validator(definition).is_valid(value)
    except (ValueError, TypeError, RecursionError, OverflowError):
        valid = False
    if not valid:
        # Never echo source text or schema error values into worker refusals.
        raise ValueError('invalid retrieval ' + (definition or 'envelope'))
    return deepcopy(value)


def _source_fields(row):
    extraction = row['extraction']
    if (extraction is None) != (row['extraction_reason'] is not None):
        raise ValueError('absent extraction requires an explicit reason')
    for descriptor in row['lineage']:
        if descriptor['kind'] != 'source' and descriptor['pin']['receipt_id'] is None:
            raise ValueError('derived lineage requires its producing receipt')


def validate_evidence(item):
    """Check an evidence item's internal consistency, without reading sources.

    ``verify_excerpt`` additionally checks supplied current source bytes. Neither
    function authenticates receipts, policy admission or scientific correctness.
    Byte offsets are half-open UTF-8 intervals; lines are one-based inclusive.
    Null measurement fields mean unsourced, never dimensionless/unconditional.
    """
    item = _validate(item, 'evidence')
    _source_fields(item)
    loc = item['location']
    nullable = ('page_index', 'page_number', 'printed_page_label', 'line_start', 'line_end')
    missing = {key for key in nullable if loc[key] is None}
    if not loc['section_path']:
        missing.add('section_path')
    if set(loc['null_reasons']) != missing:
        raise ValueError('every unavailable location needs exactly one reason')
    if (loc['section_status'] == 'unavailable') != (not loc['section_path']):
        raise ValueError('section status differs from section location')
    if (loc['line_start'] is None) != (loc['line_end'] is None):
        raise ValueError('line interval must be present or absent together')
    if loc['line_start'] is not None and loc['line_end'] < loc['line_start']:
        raise ValueError('reversed retrieval line interval')
    if loc['space'] == 'pdf-page-text':
        if loc['page_index'] is None or loc['page_number'] != loc['page_index'] + 1:
            raise ValueError('PDF physical page coordinates disagree')
        if loc['section_status'] == 'source':
            raise ValueError('PDF sections must be labelled inferred or unavailable')
    elif any(loc[k] is not None for k in ('page_index', 'page_number', 'printed_page_label')):
        raise ValueError('text coordinates cannot claim physical PDF pages')
    if (loc['space'] == 'original-text') != (item['extraction'] is None):
        raise ValueError('coordinate space differs from extraction pin')
    raw = item['text'].encode('utf-8')
    start, end = loc['byte_start'], loc['byte_end']
    pin = item['original'] if item['extraction'] is None else item['extraction']
    if end <= start or (loc['space'] != 'pdf-page-text' and end > pin['size']):
        raise ValueError('retrieval byte interval outside pinned source')
    if len(raw) != end - start or hashlib.sha256(raw).hexdigest() != item['excerpt_sha256']:
        raise ValueError('retrieval excerpt length or hash differs')
    if item['measurement'] is not None:
        for field in item['measurement'].values():
            for literal in field if isinstance(field, list) else ([] if field is None else [field]):
                a, b = literal['byte_start'], literal['byte_end']
                if not start <= a < b <= end or raw[a-start:b-start] != literal['value'].encode('utf-8'):
                    raise ValueError('measurement fields require exact excerpt locations')
    return item


def validate_request(request: Request) -> Request:
    """Closed operation-specific arguments and finite explicit resource caps."""
    return _validate(request, 'request')


def selector_digest(request: Request) -> str:
    """Bind pagination to operation/selectors, excluding page size and budgets.

    Providers must also authenticate their opaque token and its position. This
    digest is a binding check, not a signature or an authorization credential.
    """
    request = validate_request(request)
    args = {key: value for key, value in request['args'].items() if key not in ('cursor', 'limit')}
    return hashlib.sha256(canonical({'operation': request['operation'], 'args': args})).hexdigest()


def validate_candidates(candidate, request, *, provider_id, index):
    """Validate identity, snapshot/cursor, result bounds and complete group census.

    This is structural conformance only; the broker must still check policy,
    current pins, producer custody and exact located bytes before serving.
    """
    request = validate_request(request)
    result = _validate(candidate)
    _validate(index, 'index')
    if (result['provider_id'] != provider_id or result['index'] != index
            or result['operation'] != request['operation']
            or result['request_id'] != request['request_id']):
        raise ValueError('retrieval provider, index or request identity changed')
    args, op = request['args'], request['operation']
    for cursor in (args.get('cursor'), result['next_cursor']):
        if cursor is not None and any(cursor[key] != index[key] for key in
                                      ('id', 'manifest_sha256', 'policy_view_sha256')):
            raise ValueError('retrieval cursor belongs to a different snapshot')
        if cursor is not None and cursor['selector_sha256'] != selector_digest(request):
            raise ValueError('retrieval cursor belongs to different selectors')
    rows = result['results']
    metadata = result['metadata']
    if not rows and not metadata and op != 'compare_measurements' and not (result['omitted'] or result['failures']):
        raise ValueError('empty retrieval requires a missing, failure or no-match reason')
    ids = [r['id'] for r in [*rows, *metadata]]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate retrieval evidence IDs')
    if op not in ('get_paper', 'list_papers') and result['next_cursor'] is not None:
        raise ValueError('only paper lookup and listing support pagination')
    if result['next_cursor'] is not None and result['next_cursor'] == args.get('cursor'):
        raise ValueError('retrieval cursor made no progress')
    for row in rows:
        validate_evidence(row)
    identities = [(r['document_id'], r['version']) for r in metadata]
    if len(set(identities)) != len(identities):
        raise ValueError('duplicate retrieval metadata identities')
    for row in metadata:
        _source_fields(row)
        if row['acquisition_status'] == 'available' and (row['original'] is None or row['version'] is None):
            raise ValueError('available metadata requires an exact source pin and version')
        if row['original'] is None and (not row['lineage'] or row['extraction'] is not None):
            raise ValueError('missing source metadata requires pinned discovery lineage')
    if op == 'list_papers' and rows:
        raise ValueError('list_papers returns metadata only')
    limit = args.get('top_k', args.get('limit', 512))
    if op != 'compare_measurements' and len(rows) + len(result['metadata']) > limit:
        raise ValueError('retrieval population exceeds requested limit')
    scope = args.get('document_scope', [])
    for row in [*rows, *result['metadata']]:
        if scope and {'document_id': row['document_id'], 'version': row['version']} not in scope:
            raise ValueError('retrieval result outside document scope')
        if op == 'get_paper' and (row['document_id'] != args['document_id'] or
                                 (args['version'] is not None and row['version'] != args['version'])):
            raise ValueError('retrieval document/version differs from request')
    if op == 'get_paper':
        versions = {r['version'] for r in [*rows, *result['metadata']]}
        if len(versions) > 1:
            raise ValueError('get_paper must resolve one pinned version')
        for row in rows:
            if args['page_index'] is not None and row['location']['page_index'] != args['page_index']:
                raise ValueError('retrieval page differs from request')
            if args['section'] is not None and args['section'] not in row['location']['section_path']:
                raise ValueError('retrieval section differs from request')
    groups = result['groups']
    if op == 'compare_measurements':
        if [g['id'] for g in groups] != args['groups']:
            raise ValueError('complete ordered comparison groups required')
        if result['metadata']:
            raise ValueError('comparison rows must be located evidence')
        for group in groups:
            selected = [r['id'] for r in rows if r['group_id'] == group['id']]
            if (group['result_ids'] != selected or len(selected) > args['top_k_per_group']
                    or (group['status'] == 'available') != bool(selected)):
                raise ValueError('comparison group census differs from evidence rows')
            if (group['status'] == 'available') != (group['reason'] is None):
                raise ValueError('empty or missing comparison group requires a reason')
        if any(row['group_id'] not in args['groups'] for row in rows):
            raise ValueError('unknown comparison group')
    elif groups or any(row['group_id'] is not None for row in rows):
        raise ValueError('comparison groups only belong to compare_measurements')
    if [r['scores']['rank'] for r in rows] != list(range(1, len(rows) + 1)):
        raise ValueError('complete ordered retrieval ranks required')
    budget = request['budgets']
    if len(canonical(result)) > budget['max_bytes']:
        raise ValueError('retrieval envelope exceeds requested bytes')
    # UTF-8 bytes are a conservative token upper bound without a generator
    # tokenizer. Count the complete serialized envelope, including citations.
    if len(canonical(result)) > budget['max_tokens']:
        raise ValueError('retrieval envelope exceeds conservative token bound')
    usage = result['usage']
    if (usage['elapsed_seconds'] > budget['max_seconds']
            or usage['expansions'] > budget['max_expansions']):
        raise ValueError('retrieval usage exceeds requested caps')
    return result


def verify_excerpt(item, *, original: bytes, extraction: bytes | None = None):
    """Compare exact UTF-8 source bytes in their declared coordinate space.

    PDF extraction coordinates address a page's UTF-8 text, never PDF bytes.
    Extraction records must bind the original hash and complete physical page
    roster. The broker separately authenticates their producing receipts.
    Subline spans remain byte-located literature evidence, not v1 line assertions.
    """
    from ..validation.evidence_card import _range

    item = validate_evidence(item)

    def pinned(raw, pin):
        if (type(raw) is not bytes or not 0 < len(raw) <= MAX_SOURCE_BYTES or len(raw) != pin['size']
                or hashlib.sha256(raw).hexdigest() != pin['sha256']):
            raise ValueError('retrieval source pin differs from current bytes')

    pinned(original, item['original'])
    loc = item['location']
    if loc['space'] == 'original-text':
        if extraction is not None or item['extraction'] is not None:
            raise ValueError('original text cannot claim extraction coordinates')
        if original.startswith(b'%PDF-'):
            raise ValueError('PDF bytes are not original text coordinates')
        raw = original
    else:
        if item['extraction'] is None:
            raise ValueError('extraction coordinates require a producer pin')
        pinned(extraction, item['extraction'])
        if loc['space'] == 'pdf-page-text':
            if not original.startswith(b'%PDF-'):
                raise ValueError('PDF page coordinates require an original PDF')
            try:
                record = json.loads(extraction, object_pairs_hook=_unique_object,
                                    parse_constant=_invalid_constant)
            except (ValueError, UnicodeError, RecursionError):
                raise ValueError('invalid PDF extraction record') from None
            # The producer records its own custody location (an absolute path);
            # served pins carry admitted relative names. Exact content binds the
            # two; the broker authenticates the producing receipt and custody.
            source = record.get('source') if isinstance(record, dict) else None
            if (not isinstance(record, dict) or type(record.get('schema_version')) is not int
                    or record['schema_version'] != 1
                    or record.get('kind') != 'literature-pdf-extraction-result'
                    or not isinstance(source, dict) or set(source) != {'path', 'sha256', 'size'}
                    or not isinstance(source['path'], str) or not source['path']
                    or type(source['size']) is not int
                    or [source['sha256'], source['size']] != [item['original'][k] for k in ('sha256', 'size')]
                    or 'failure' not in record or record['failure'] is not None):
                raise ValueError('PDF extraction does not bind this original')
            pages, count = record.get('pages'), record.get('page_count')
            if (type(count) is not int or not 0 < count <= 100000 or not isinstance(pages, list)
                    or len(pages) != count or any(not isinstance(p, dict) or type(p.get('page_index')) is not int
                                                or p['page_index'] != i for i, p in enumerate(pages))):
                raise ValueError('PDF extraction requires a complete physical page roster')
            if loc['page_index'] >= count:
                raise ValueError('PDF page outside extraction roster')
            page = pages[loc['page_index']]
            if page.get('status') != 'extracted' or not isinstance(page.get('text'), str):
                raise ValueError('PDF page has unresolved extraction')
            try:
                raw = page['text'].encode('utf-8')
            except UnicodeError:
                raise ValueError('PDF page text requires valid UTF-8') from None
            if hashlib.sha256(raw).hexdigest() != page.get('text_sha256'):
                raise ValueError('PDF page text hash changed')
        else:
            raw = extraction
    start, end = _range([loc['byte_start'], loc['byte_end']], len(raw))
    excerpt = raw[start:end]
    if (excerpt != item['text'].encode('utf-8')
            or hashlib.sha256(excerpt).hexdigest() != item['excerpt_sha256']):
        raise ValueError('retrieval excerpt differs from exact source bytes')
    # Decode all bytes as well: an offset cannot silently split a UTF-8 codepoint.
    try:
        raw.decode('utf-8'); raw[:start].decode('utf-8'); raw[:end].decode('utf-8')
    except UnicodeError:
        raise ValueError('retrieval coordinates require complete UTF-8 text') from None
    if loc['line_start'] is not None:
        if (loc['line_start'] != raw[:start].count(b'\n') + 1
                or loc['line_end'] != raw[:end - 1].count(b'\n') + 1):
            raise ValueError('retrieval line location differs from source bytes')
    return {'excerpt_sha256': item['excerpt_sha256'], 'physics_verified': False,
            'execution_authorized': False}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate extraction key')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('nonfinite extraction number')
