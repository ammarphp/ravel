"""Fictional provider conformance, exact evidence, and legacy no-index controls."""
from copy import deepcopy
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import socket

import pytest
from jsonschema import Draft202012Validator

from ravel.workflow import literature_provider as lp

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures/literature_provider'


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def case(operation='search'):
    return next(c for c in fixture('conformance.json') if c['request']['operation'] == operation)


def check(c):
    return lp.validate_candidates(c['candidate'], c['request'], provider_id='fixture',
                                  index=case()['candidate']['index'])


def change(value, path, replacement):
    for key in path[:-1]:
        value = value[key]
    value[path[-1]] = replacement


def pin(raw, path='sources/synthetic.txt', receipt=None):
    return dict(path=path, sha256=hashlib.sha256(raw).hexdigest(), size=len(raw), receipt_id=receipt)


class InertProvider:
    """Reusable example adapter: fixed candidates, no runtime/model/source access.

    Production adapters additionally implement pre-ranking policy closure and
    selector-bound cursor checks. A structural protocol cannot certify effects.
    """
    provider_id = 'fixture'

    def _read(self, request, view, operation):
        request = lp.validate_request(request)
        assert request['operation'] == operation
        assert view.policy_sha256 == case()['candidate']['index']['policy_view_sha256']
        result = case(operation)['candidate']
        for row in result['results'] + result['metadata']:
            descriptors = [dict(pin=row['original'], identifiers=row['identifiers'],
                                quantities=row['quantities'], classes=row['classes'], kind='source')]
            assert all(view.permits(d) for d in descriptors + row['lineage'])
        return result

    def search(self, request, *, view):
        return self._read(request, view, 'search')

    def get_paper(self, request, *, view):
        return self._read(request, view, 'get_paper')

    def list_papers(self, request, *, view):
        return self._read(request, view, 'list_papers')

    def compare_measurements(self, request, *, view):
        return self._read(request, view, 'compare_measurements')


def test_schema_is_valid_and_operations_are_closed():
    schema = json.loads(files('ravel.data').joinpath('knowledge/schema/retrieval.json').read_text())
    Draft202012Validator.check_schema(schema)
    assert set(lp.OPERATIONS) == {'search', 'get_paper', 'list_papers', 'compare_measurements'}
    assert isinstance(InertProvider(), lp.RetrievalProvider)
    assert lp.SCHEMA_VERSION == 1


@pytest.mark.parametrize('operation', lp.OPERATIONS)
def test_four_operations_are_deterministic_evidence_only(operation, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Provider contract must not contact a network or model service')
    monkeypatch.setattr(socket, 'socket', forbidden)
    provider = InertProvider()
    view = lp.SourceView('2' * 64, 'run:synthetic', 'node:retrieval', 'reader', 1, lambda _: True)
    c = case(operation)
    first = getattr(provider, operation)(c['request'], view=view)
    second = getattr(provider, operation)(c['request'], view=view)
    assert lp.canonical(first) == lp.canonical(second)
    assert check(dict(c, candidate=first)) == first
    for row in first['results']:
        assert lp.verify_excerpt(row, original=(FIXTURES / 'source.txt').read_bytes()) == {
            'excerpt_sha256': row['excerpt_sha256'], 'physics_verified': False, 'execution_authorized': False}


@pytest.mark.parametrize('path,value', [
    (['schema_version'], 2), (['schema_version'], True), (['operation'], 'answer'),
    (['budgets', 'max_seconds'], float('nan')), (['budgets', 'max_seconds'], float('inf')),
    (['budgets', 'max_seconds'], 0), (['budgets', 'max_tokens'], True),
    (['budgets', 'max_tokens'], 1.0), (['budgets', 'max_bytes'], lp.MAX_BYTES + 1),
    (['budgets', 'max_expansions'], 0), (['args', 'top_k'], 0),
    (['args', 'mode'], 'deep'), (['args', 'query'], ''),
    (['args', 'query'], '\ud800'), (['args', 'filters'], {'topic': []}),
    (['args', 'endpoint'], 'https://example.invalid'),
    (['args', 'document_scope'], [{'document_id': 'paper:amber', 'version': 'v2'}] * 2),
])
def test_request_refuses_invalid_caps_selectors_and_hidden_effects(path, value):
    request = case()['request']; change(request, path, value)
    with pytest.raises(ValueError):
        lp.validate_request(request)


@pytest.mark.parametrize('operation', lp.OPERATIONS)
def test_request_requires_every_budget_and_no_provider_override(operation):
    for key in case(operation)['request']['budgets']:
        request = case(operation)['request']; del request['budgets'][key]
        with pytest.raises(ValueError): lp.validate_request(request)
    request = case(operation)['request']; request['provider_id'] = 'worker-choice'
    with pytest.raises(ValueError): lp.validate_request(request)


@pytest.mark.parametrize('path,value', [
    (['provider_id'], 'different'), (['request_id'], 'different'), (['operation'], 'get_paper'),
    (['index', 'id'], 'different'), (['index', 'manifest_sha256'], '3'*64),
    (['index', 'policy_view_sha256'], '3'*64), (['index', 'manifest_sha256'], 'x'*64),
    (['usage', 'elapsed_seconds'], 3), (['usage', 'expansions'], 51),
    (['usage', 'elapsed_seconds'], float('inf')), (['usage', 'token_accounting'], 'estimate'),
    (['results', 0, 'physics_verified'], True), (['results', 0, 'execution_authorized'], True),
    (['results', 0, 'acquisition_status'], 'missing'), (['results', 0, 'version'], None),
    (['results', 0, 'scores', 'rank'], 2), (['results', 0, 'scores', 'bm25'], float('nan')),
    (['results', 0, 'scores', 'reranker'], True), (['results', 0, 'group_id'], 'unknown'),
    (['results', 0, 'text'], 'Invented paraphrase'), (['results', 0, 'excerpt_sha256'], '0'*64),
    (['results', 0, 'extraction_reason'], None),
    (['results', 0, 'location', 'byte_start'], 99),
    (['results', 0, 'location', 'byte_end'], 999),
    (['results', 0, 'location', 'line_end'], 1),
    (['results', 0, 'location', 'line_start'], None),
    (['results', 0, 'location', 'page_number'], 1),
    (['results', 0, 'location', 'section_status'], 'unavailable'),
    (['results', 0, 'location', 'null_reasons'], {}),
    (['results', 0, 'location', 'space'], 'pdf-page-text'),
    (['results', 0, 'original', 'size'], True),
    (['results', 0, 'original', 'size'], lp.MAX_SOURCE_BYTES+1),
])
def test_candidate_refuses_forged_identity_authority_location_or_usage(path, value):
    c = case(); change(c['candidate'], path, value)
    with pytest.raises(ValueError): check(c)


@pytest.mark.parametrize('path', ['/tmp/source', '../source', 'a/../source', 'a/./source',
                                  'a//source', 'a\\source', 'C:/source', 'a\x00source',
                                  'a\nsource', 'a/'])
def test_pin_paths_are_portable_relative_names(path):
    c = case(); c['candidate']['results'][0]['original']['path'] = path
    with pytest.raises(ValueError): check(c)


def test_validators_return_detached_values_and_do_not_rewrite_evidence():
    c = case(); before = lp.canonical(c)
    result = check(c); result['results'][0]['text'] = 'changed copy'
    req = lp.validate_request(c['request']); req['args']['query'] = 'changed copy'
    assert lp.canonical(c) == before


@pytest.mark.parametrize('cap', ['max_bytes', 'max_tokens'])
def test_complete_envelope_budget_exact_boundary(cap):
    c = case(); size = len(lp.canonical(c['candidate']))
    c['request']['budgets'][cap] = size
    assert check(c)
    c['request']['budgets'][cap] -= 1
    with pytest.raises(ValueError): check(c)


def test_population_scope_and_duplicate_ids():
    c = case(); c['request']['args']['top_k'] = 1
    c['candidate']['results'].append(deepcopy(c['candidate']['results'][0]))
    with pytest.raises(ValueError): check(c)
    c['candidate']['results'][1]['id'] = 'second'
    c['candidate']['results'][1]['scores']['rank'] = 2
    with pytest.raises(ValueError): check(c)
    c = case(); c['request']['args']['document_scope'] = [{'document_id': 'paper:amber', 'version': 'v1'}]
    with pytest.raises(ValueError): check(c)
    c['request']['args']['document_scope'][0]['version'] = 'v2'
    assert check(c)


@pytest.mark.parametrize('operation', ['get_paper', 'list_papers'])
def test_cursors_pin_snapshot_policy_and_require_progress(operation):
    c = case(operation); cursor = dict(c['candidate']['index'], token='opaque-page:2', selector_sha256=lp.selector_digest(c['request']))
    c['candidate']['next_cursor'] = cursor
    assert check(c)
    for key in ('id', 'manifest_sha256', 'policy_view_sha256', 'selector_sha256'):
        bad = deepcopy(c); bad['candidate']['next_cursor'][key] = '3'*64
        with pytest.raises(ValueError): check(bad)
        bad = deepcopy(c); bad['request']['args']['cursor'] = dict(cursor, **{key: '3'*64})
        with pytest.raises(ValueError): check(bad)
    c['request']['args']['cursor'] = deepcopy(cursor)
    with pytest.raises(ValueError): check(c)
    c['candidate']['next_cursor'] = None
    assert check(c)


def test_unpaginated_search_and_compare_refuse_cursor():
    for op in ('search', 'compare_measurements'):
        c = case(op); c['candidate']['next_cursor'] = dict(c['candidate']['index'], token='page:2', selector_sha256=lp.selector_digest(c['request']))
        with pytest.raises(ValueError): check(c)


@pytest.mark.parametrize('key,value', [('version','v1'), ('document_id','paper:violet'),
                                      ('page_index',0), ('section','Introduction')])
def test_get_paper_is_exact_and_discloses_unversioned_resolution(key, value):
    c = case('get_paper'); assert check(c)['results'][0]['version'] == 'v2'
    c['request']['args'][key] = value
    with pytest.raises(ValueError): check(c)


def test_get_paper_cannot_mix_versions():
    c = case('get_paper'); c['candidate']['metadata'][0]['version'] = 'v3'
    with pytest.raises(ValueError): check(c)


def test_list_is_metadata_only_and_missing_sources_do_not_invent_pins():
    c = case('list_papers'); row = c['candidate']['metadata'][0]
    row.update(original=None, version=None, acquisition_status='missing',
               reason='Only a pinned discovery record is available.',
               lineage=[dict(pin=pin(b'discovery', 'metadata/record.json'),
                             identifiers={'document':['paper:amber']}, quantities=[], classes=['metadata'], kind='source')])
    assert check(c)['metadata'][0]['original'] is None
    bad = deepcopy(c); bad['candidate']['metadata'][0]['lineage'] = []
    with pytest.raises(ValueError): check(bad)
    bad = deepcopy(c); bad['candidate']['metadata'][0]['acquisition_status'] = 'available'
    with pytest.raises(ValueError): check(bad)
    c['candidate']['results'] = case()['candidate']['results']
    with pytest.raises(ValueError): check(c)


def test_metadata_identity_and_ids_are_unique():
    c = case('list_papers'); second = deepcopy(c['candidate']['metadata'][0]); second['id'] = 'different-id'
    c['candidate']['metadata'].append(second)
    with pytest.raises(ValueError): check(c)
    c = case('get_paper'); c['candidate']['metadata'][0]['id'] = c['candidate']['results'][0]['id']
    with pytest.raises(ValueError): check(c)


@pytest.mark.parametrize('mutation', ['omit', 'reorder', 'invent', 'references', 'missing_reason', 'empty_available', 'unknown_row', 'metadata'])
def test_comparison_retains_complete_ordered_missing_group_census(mutation):
    c = case('compare_measurements'); r = c['candidate']
    if mutation == 'omit': r['groups'].pop()
    elif mutation == 'reorder': r['groups'].reverse()
    elif mutation == 'invent': r['groups'][1]['result_ids'] = ['invented']
    elif mutation == 'references': r['groups'][0]['result_ids'] = []
    elif mutation == 'missing_reason': r['groups'][2]['reason'] = None
    elif mutation == 'empty_available': r['groups'][1]['status'] = 'available'
    elif mutation == 'unknown_row': r['results'][0]['group_id'] = 'unknown'
    elif mutation == 'metadata': r['metadata'] = case('list_papers')['candidate']['metadata']
    with pytest.raises(ValueError): check(c)


def test_comparison_budget_is_per_group_and_never_combines_values():
    c = case('compare_measurements'); c['request']['args']['top_k_per_group'] = 1
    r = c['candidate']; row = deepcopy(r['results'][0]); row['id'] = 'second'; row['scores']['rank'] = 2
    r['results'].append(row); r['groups'][0]['result_ids'].append('second')
    with pytest.raises(ValueError): check(c)
    c = case('compare_measurements'); item = c['candidate']['results'][0]
    item['measurement']['unit'] = None; item['measurement']['conditions'] = None
    assert check(c)['results'][0]['measurement']['value']['value'] == '12.5'
    item['measurement']['value']['value'] = '12.500'
    with pytest.raises(ValueError): check(c)


def test_source_pins_and_literal_spans_check_current_bytes():
    item = case()['candidate']['results'][0]; raw = (FIXTURES / 'source.txt').read_bytes()
    for wrong in (raw + b'!', raw.replace(b'12.5', b'13.5'), bytearray(raw), None):
        with pytest.raises(ValueError): lp.verify_excerpt(item, original=wrong)
    item['location']['line_start'] = item['location']['line_end'] = 3
    with pytest.raises(ValueError): lp.verify_excerpt(item, original=raw)


def test_unicode_subline_span_preserves_exact_bytes_and_line_numbers():
    item = case()['candidate']['results'][0]; raw = 'heading\nα = 7\n'.encode()
    start, end = len('heading\n'.encode()), len(raw)-1
    item.update(original=pin(raw), text=raw[start:end].decode(), excerpt_sha256=hashlib.sha256(raw[start:end]).hexdigest())
    item['location'].update(byte_start=start, byte_end=end)
    assert lp.verify_excerpt(item, original=raw)['physics_verified'] is False
    # The entire pinned text must be UTF-8, even outside the quoted span.
    raw += b'\xff'; item['original'] = pin(raw)
    with pytest.raises(ValueError, match='UTF-8'): lp.verify_excerpt(item, original=raw)


def test_extracted_text_requires_receipt_and_never_uses_pdf_byte_coordinates():
    item = case()['candidate']['results'][0]; original = b'non-text-source'; extracted = (FIXTURES/'source.txt').read_bytes()
    item.update(original=pin(original), extraction=pin(extracted, 'extractions/source.txt', 'producer:1'), extraction_reason=None)
    item['location']['space'] = 'extracted-text'
    assert lp.verify_excerpt(item, original=original, extraction=extracted)
    item['extraction']['receipt_id'] = None
    with pytest.raises(ValueError): lp.verify_excerpt(item, original=original, extraction=extracted)
    item = case()['candidate']['results'][0]; raw = b'%PDF-' + extracted
    item['original'] = pin(raw)
    with pytest.raises(ValueError): lp.verify_excerpt(item, original=raw)


def test_derived_lineage_needs_a_producing_receipt():
    c = case(); descriptor = dict(pin=pin(b'summary'), identifiers={}, quantities=[], classes=[], kind='generated')
    c['candidate']['results'][0]['lineage'] = [descriptor]
    with pytest.raises(ValueError): check(c)
    descriptor['pin']['receipt_id'] = 'summary:fixture'
    assert check(c)


def test_pdf_physical_pages_and_exact_extraction_bytes():
    item = fixture('pdf-evidence.json'); original = (FIXTURES/'original.bin').read_bytes(); extraction = (FIXTURES/'extraction.json').read_bytes()
    assert lp.verify_excerpt(item, original=original, extraction=extraction)['physics_verified'] is False
    for field, value in [('page_number', 0), ('page_number', 2), ('page_index', 1), ('section_status', 'source')]:
        bad = deepcopy(item); bad['location'][field] = value
        with pytest.raises(ValueError): lp.verify_excerpt(bad, original=original, extraction=extraction)
    with pytest.raises(ValueError): lp.verify_excerpt(item, original=original, extraction=extraction+b' ')


@pytest.mark.parametrize('mutation', ['source', 'roster', 'count', 'missing_page', 'status', 'text_hash', 'failure', 'version', 'list', 'duplicate', 'nan'])
def test_pdf_extraction_malformed_or_changed_records_fail_closed(mutation):
    item = fixture('pdf-evidence.json'); original = (FIXTURES/'original.bin').read_bytes(); record = fixture('extraction.json')
    if mutation == 'source': record['source']['sha256'] = '0'*64
    elif mutation == 'roster': record['pages'][0]['page_index'] = 1
    elif mutation == 'count': record['page_count'] = True
    elif mutation == 'missing_page': record['pages'] = []
    elif mutation == 'status': record['pages'][0]['status'] = 'failed'
    elif mutation == 'text_hash': record['pages'][0]['text_sha256'] = '0'*64
    elif mutation == 'failure': record['failure'] = 'Incomplete extraction'
    elif mutation == 'version': record['schema_version'] = 2
    elif mutation == 'list': record = []
    extraction = lp.canonical(record)
    if mutation == 'duplicate': extraction = extraction[:-1] + b',"page_count":1}'
    if mutation == 'nan': extraction = extraction[:-1] + b',"elapsed_seconds":NaN}'
    item['extraction'] = pin(extraction, 'extractions/amber.json', 'extraction:fixture')
    with pytest.raises(ValueError): lp.verify_excerpt(item, original=original, extraction=extraction)


def test_pdf_extraction_binds_original_content_not_producer_custody_path():
    # The existing extractor records its absolute custody location and extra
    # outcome fields; served pins carry admitted relative names. Content binds them.
    item = fixture('pdf-evidence.json'); original = (FIXTURES/'original.bin').read_bytes(); record = fixture('extraction.json')
    record['source']['path'] = '/srv/custody/sources/amber.pdf'
    record.update(request={'path': '/srv/custody/request.json', 'sha256': '4'*64, 'size': 1},
                  status='all_page_text_extracted', elapsed_seconds=0.5,
                  claims={'physics_verified': False, 'execution_authorized': False})
    record['pages'][0].update(reason=None, visual_status='unobserved', ocr_status='not_performed',
                              structured_math_tables='unverified')
    extraction = lp.canonical(record)
    item['extraction'] = pin(extraction, 'extractions/amber.json', 'extraction:fixture')
    assert lp.verify_excerpt(item, original=original, extraction=extraction)['physics_verified'] is False
    for key, value in [('size', 33), ('sha256', '0'*64), ('path', ''), ('path', None), ('url', 'x')]:
        bad = deepcopy(record); bad['source'][key] = value; raw = lp.canonical(bad)
        bad_item = deepcopy(item); bad_item['extraction'] = pin(raw, 'extractions/amber.json', 'extraction:fixture')
        with pytest.raises(ValueError, match='bind'):
            lp.verify_excerpt(bad_item, original=original, extraction=raw)


@pytest.mark.parametrize('name', ['show', 'find', 'limit', 'miss'])
def test_no_index_legacy_golden_bytes(name, monkeypatch):
    from ravel.workflow import knowledge
    from ravel.workflow.knowledge_atlas import encode
    expected_path = FIXTURES / ('legacy-' + name + '.json')
    expected = json.loads(expected_path.read_text())
    def forbidden(*args, **kwargs):
        raise AssertionError('No index must preserve the existing knowledge path')
    monkeypatch.setattr(InertProvider, '_read', forbidden)
    monkeypatch.setattr(socket, 'socket', forbidden)
    actual = knowledge.query(expected['op'], atlas_path=FIXTURES/'legacy-atlas.json', **expected['args'])
    assert encode(actual) == expected_path.read_bytes()


def test_cursor_selectors_cannot_be_swapped_but_page_size_may_change():
    c = case('list_papers'); req = c['request']
    req['args']['cursor'] = dict(c['candidate']['index'], token='page:2', selector_sha256=lp.selector_digest(req))
    before = lp.selector_digest(req)
    req['request_id'] = 'second-request'; c['candidate']['request_id'] = req['request_id']
    req['args']['limit'] = 2; req['budgets']['max_seconds'] = 1
    assert lp.selector_digest(req) == before
    assert check(c)
    req['args']['filters'] = {'category': ['changed']}
    with pytest.raises(ValueError, match='selectors'): check(c)


@pytest.mark.parametrize('op', ['search', 'get_paper', 'list_papers'])
def test_empty_responses_preserve_explicit_missing_outcomes(op):
    c = case(op); c['candidate']['results'] = []; c['candidate']['metadata'] = []
    with pytest.raises(ValueError, match='reason'): check(c)
    c['candidate']['omitted'] = [{'id': 'lookup:fixture', 'code': 'no_match', 'reason': 'No match in allowed snapshot.'}]
    assert check(c)


def test_unavailable_locations_are_explicit_and_budget_accounts_unicode():
    c = case(); row = c['candidate']['results'][0]
    row['location'].update(section_path=[], section_status='unavailable', line_start=None, line_end=None)
    row['location']['null_reasons'].update(section_path='No section label.', line_start='Byte location only.', line_end='Byte location only.')
    assert check(c)
    assert lp.verify_excerpt(row, original=(FIXTURES/'source.txt').read_bytes())
    row['location']['null_reasons']['line_end'] = 'Unknown — byte location only.'
    c['request']['budgets']['max_bytes'] = len(lp.canonical(c['candidate']).decode())
    with pytest.raises(ValueError, match='bytes'): check(c)
