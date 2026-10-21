"""Local hybrid retrieval over immutable, located literature derivatives.

Only a trusted broker installs this provider. Source views are projected before
ranking, counts, model input or expansion. Results are untrusted contract
candidates; the broker still authenticates receipts and checks current
source bytes.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import hmac
import math
from pathlib import Path
import re
import time
from typing import Protocol, Sequence

from . import literature_provider as contract
from .knowledge import rank_literature


class EmbeddingModel(Protocol):
    identity: dict

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...

    def embed_query(self, text: str) -> Sequence[float]: ...


class Reranker(Protocol):
    identity: dict

    def score(self, query: str, texts: Sequence[str]) -> Sequence[float]: ...


def digest(value):
    return hashlib.sha256(contract.canonical(value)).hexdigest()


def normalize_settings(settings=None):
    defaults = dict(candidate_k=50, rrf_k=60.0, neighbour_radius=1,
                    expand_sections=True, expansion_slots=2)
    if settings is not None:
        if not isinstance(settings, dict) or set(settings) - set(defaults):
            raise ValueError('unknown literature index settings')
        defaults.update(settings)
    for key, low, high in (('candidate_k', 1, 512), ('neighbour_radius', 0, 8),
                           ('expansion_slots', 0, 32)):
        if type(defaults[key]) is not int or not low <= defaults[key] <= high:
            raise ValueError('invalid literature index settings')
    if (type(defaults['expand_sections']) is not bool
            or type(defaults['rrf_k']) not in (int, float)
            or not math.isfinite(defaults['rrf_k']) or not 0 < defaults['rrf_k'] <= 1e6):
        raise ValueError('invalid literature index settings')
    defaults['rrf_k'] = float(defaults['rrf_k'])
    return defaults


def _identity(row):
    return row['document_id'], row['version'] or '', row.get('unit_id', '')


def _scores():
    return dict(dense_raw=None, dense_diffused=None, bm25=None, fusion=None,
                reranker=None, rank=1, graph_paths=[])


def indexed_text(title, section_path, text):
    """Navigation text never replaces or changes the cited source span."""
    return title + '\n' + ' / '.join(section_path) + '\n' + text


def validate_corpus(corpus):
    """Validate a finite derivative, without granting source/receipt authority."""
    if (not isinstance(corpus, dict) or set(corpus) != {'schema_version', 'units', 'papers', 'inputs'}
            or type(corpus['schema_version']) is not int or corpus['schema_version'] != 1):
        raise ValueError('invalid literature corpus')
    result = deepcopy(corpus)
    if any(not isinstance(result[k], list) or len(result[k]) > 100000 for k in ('units', 'papers', 'inputs')):
        raise ValueError('bounded literature corpus required')
    papers, ids, units = {}, set(), {}
    for paper in result['papers']:
        contract._validate(paper, 'metadata')
        contract._source_fields(paper)
        key = (paper['document_id'], paper['version'])
        if key in papers or paper['id'] in ids:
            raise ValueError('duplicate literature paper')
        if paper['acquisition_status'] == 'available' and (paper['original'] is None or paper['version'] is None):
            raise ValueError('available paper requires its exact original')
        if paper['original'] is None and (not paper['lineage'] or paper['extraction'] is not None):
            raise ValueError('missing paper requires discovery lineage')
        papers[key] = paper
        ids.add(paper['id'])
    for unit in result['units']:
        if not isinstance(unit, dict) or set(unit) != {'evidence', 'indexed_text', 'parent_id', 'section_ids'}:
            raise ValueError('invalid literature unit')
        row = contract.validate_evidence(unit['evidence'])
        key = _identity(row)
        if key in units or row['id'] in ids or row['group_id'] is not None:
            raise ValueError('duplicate or grouped stored literature unit')
        paper = papers.get(key[:2])
        if paper is None or any(row[k] != paper[k] for k in
                               ('original', 'extraction', 'identifiers', 'quantities', 'classes', 'lineage')):
            raise ValueError('literature unit differs from its paper lineage')
        if unit['indexed_text'] != indexed_text(paper['title'], row['location']['section_path'], row['text']):
            raise ValueError('indexed text differs from title, section and exact excerpt')
        if (unit['parent_id'] is not None and not isinstance(unit['parent_id'], str)
                or not isinstance(unit['section_ids'], list)
                or any(not isinstance(s, str) for s in unit['section_ids'])
                or len(set(unit['section_ids'])) != len(unit['section_ids'])):
            raise ValueError('invalid literature structure')
        units[key] = unit
        ids.add(row['id'])
    for key, unit in units.items():
        for section in unit['section_ids']:
            if key[:2] + (section,) not in units:
                raise ValueError('section expansion refers to absent evidence')
    for item in result['inputs']:
        contract._validate(item, 'descriptor')
        if item['kind'] != 'source' and item['pin']['receipt_id'] is None:
            raise ValueError('derived corpus inputs require receipts')
    result['units'].sort(key=lambda u: _identity(u['evidence']))
    result['papers'].sort(key=_identity)
    result['inputs'] = sorted({contract.canonical(p): p for p in result['inputs']}.values(), key=contract.canonical)
    return result


MAX_COUNTED_BYTES = 60 * 1024  # Below the model adapter's per-text bound.


def normalize_excluded_roots(value):
    """Validated absolute roots no corpus member, product or index may lie under."""
    if value is None:
        return ()
    if type(value) not in (list, tuple) or len(value) > 256:
        raise ValueError('explicit bounded excluded_roots list required')
    roots = []
    for item in value:
        if not isinstance(item, (str, Path)) or not str(item) or not Path(item).is_absolute():
            raise ValueError('excluded roots must be absolute paths')
        roots.append(Path(item).resolve())
    return tuple(dict.fromkeys(roots))


def excluded(path, roots, base=None):
    """Whether ``path`` (relative paths against ``base``) resolves under an excluded root; reads nothing."""
    path = Path(path)
    if not path.is_absolute():
        if base is None:
            return True
        path = Path(base) / path
    path = path.resolve()
    return any(path == root or root in path.parents for root in roots)


ORIGIN_KINDS = ('document', 'pin', 'run', 'path')
MAX_ORIGINS = 4096
_SHA = re.compile(r'[0-9a-f]{64}')


def normalize_excluded_origins(value):
    """Validated excluded-origin entries ``{kind: document|pin|run|path, value}``, sorted and unique.

    The set comes from trusted installation settings (an evaluator-supplied list). ``document``
    names a document or record identity, ``pin`` a content sha256, ``run`` a run identity and
    ``path`` a corpus-relative pin path or directory.
    """
    if value is None:
        return ()
    if type(value) not in (list, tuple) or len(value) > MAX_ORIGINS:
        raise ValueError('explicit bounded excluded_origins list required')
    if isinstance(value, tuple):
        value = [dict(kind=item[0], value=item[1]) if isinstance(item, tuple) and len(item) == 2 else item
                 for item in value]
    found = set()
    for item in value:
        if (not isinstance(item, dict) or set(item) != {'kind', 'value'} or item['kind'] not in ORIGIN_KINDS
                or not isinstance(item['value'], str) or not item['value'].strip() or len(item['value']) > 4096):
            raise ValueError('excluded origins must be {kind: document|pin|run|path, value} entries')
        if item['kind'] == 'pin' and not _SHA.fullmatch(item['value']):
            raise ValueError('an excluded pin origin is a sha256 hex digest')
        if item['kind'] == 'path':
            path = item['value']
            if (path.startswith('/') or '\\' in path or '\x00' in path
                    or any(part in ('', '.', '..') for part in path.split('/'))):
                raise ValueError('an excluded path must be a canonical corpus-relative path')
        found.add((item['kind'], item['value']))
    return tuple(sorted(found))


def excluded_origins_sha256(origins):
    """The digest a manifest records for a configured excluded-origin set (None when there is none)."""
    origins = normalize_excluded_origins(origins)
    return digest([list(o) for o in origins]) if origins else None


def ancestry(row):
    """Origin identities a paper, evidence row or lineage descriptor carries: documents, pins, runs, paths.

    Transformed rows (extractions, generated derivatives) carry their sources' identities through
    their pins and lineage; the exclusion of a source therefore reaches everything derived from it.
    """
    found = {'document': set(), 'pin': set(), 'run': set(), 'path': set()}
    rows = [row, *(d for d in row.get('lineage', ()) if isinstance(d, dict))]
    for item in rows:
        if isinstance(item.get('document_id'), str):
            found['document'].add(item['document_id'])
        for key, values in (item.get('identifiers') or {}).items():
            for value in values if isinstance(values, list) else ():
                if isinstance(value, str):
                    (found['run'] if key == 'run' else found['document']).add(value)
        for pin in (item.get('original'), item.get('extraction'), item.get('pin')):
            if isinstance(pin, dict):
                if isinstance(pin.get('sha256'), str):
                    found['pin'].add(pin['sha256'])
                if isinstance(pin.get('path'), str):
                    found['path'].add(pin['path'])
                if isinstance(pin.get('receipt_id'), str):
                    found['run'].add(pin['receipt_id'])
    return found


def transformed_without_ancestry(row):
    """A derived row (an extraction or a generated derivative) that names no source it came from."""
    lineage = [d for d in row.get('lineage', ()) if isinstance(d, dict)]
    transformed = row.get('extraction') is not None or any(d.get('kind') != 'source' for d in lineage)
    sourced = row.get('original') is not None or any(d.get('kind') == 'source' for d in lineage)
    return transformed and not sourced


def excluded_origin(row, origins):
    """The kind of the first excluded origin ``row`` descends from, or None (reads nothing)."""
    if not origins:
        return None
    found = ancestry(row)
    for kind, value in origins:
        if kind == 'path':
            if any(path == value or path.startswith(value + '/') for path in found['path']):
                return kind
        elif value in found[kind]:
            return kind
    return None


def origin_problems(corpus, origins):
    """Counts of corpus rows that descend from an excluded origin or are derived without ancestry."""
    evidence = [*corpus.get('papers', ()), *(u.get('evidence', {}) for u in corpus.get('units', ()))]
    rows = [*evidence, *corpus.get('inputs', ())]
    named = sum(1 for r in rows if excluded_origin(r, origins))
    anchored = set()
    for row in evidence:
        if not transformed_without_ancestry(row):
            anchored.update(ancestry(row)['pin'])
    orphans = sum(1 for r in evidence if transformed_without_ancestry(r))
    orphans += sum(1 for r in corpus.get('inputs', ())
                   if r.get('kind') in ('generated', 'extracted')
                   and r.get('pin', {}).get('sha256') not in anchored)
    return named, orphans


def corpus_paths(corpus):
    """Every pinned path a corpus names: papers, units and all lineage and input descriptors."""
    found = []
    for row in [*corpus.get('papers', ()), *(u.get('evidence', {}) for u in corpus.get('units', ()))]:
        for pin in (row.get('original'), row.get('extraction')):
            if isinstance(pin, dict):
                found.append(pin.get('path'))
        found.extend(d.get('pin', {}).get('path') for d in row.get('lineage', ()) if isinstance(d, dict))
    found.extend(d.get('pin', {}).get('path') for d in corpus.get('inputs', ()) if isinstance(d, dict))
    return found


def _boundary_count(text):
    """Line boundaries (LF, as the retrieval contract counts them) before the end of ``text``."""
    return text.count('\n')


def split_units(corpus, *, count, limit):
    """Split units whose indexed text exceeds ``limit`` tokens into exact contiguous sub-intervals.

    ``count`` returns the embedding token count of each indexed text (title,
    section headings and excerpt together). Pieces break after whitespace, or
    inside an unbroken run only when that run alone cannot fit; their texts
    concatenate to the original excerpt, so no byte is dropped or truncated. The
    first piece keeps the unit identity; later pieces append ``#<n>``. A unit
    whose title and headings leave no room, or that carries a located
    measurement, is refused rather than truncated.
    """
    if type(limit) is not int or limit < 1 or not callable(count):
        raise ValueError('explicit token counter and positive limit required')
    corpus = validate_corpus(corpus)
    titles = {(p['document_id'], p['version']): p['title'] for p in corpus['papers']}

    def fits(prefix, piece):
        text = prefix + piece
        if len(text.encode('utf-8')) > MAX_COUNTED_BYTES:
            return False
        counted = count([text])
        if type(counted) not in (list, tuple) or len(counted) != 1 or type(counted[0]) is not int:
            raise ValueError('token counter must return one integer per text')
        return counted[0] <= limit

    def longest(prefix, parts, start):
        # The largest end index whose joined parts fit; parts grow monotonically.
        low, high = start, len(parts)
        while low < high:
            middle = (low + high + 1) // 2
            if fits(prefix, ''.join(parts[start:middle])):
                low = middle
            else:
                high = middle - 1
        return low

    units = []
    for unit in corpus['units']:
        row = unit['evidence']
        title = titles[(row['document_id'], row['version'])]
        prefix = indexed_text(title, row['location']['section_path'], '')
        if fits(prefix, row['text']):
            units.append(unit)
            continue
        if row['measurement'] is not None:
            raise ValueError('located measurement unit ' + row['id'] + ' exceeds the passage token window')
        parts, pieces, at = re.findall(r'\s+|\S+\s*', row['text']), [], 0
        if parts and not parts[0].strip() and len(parts) > 1:
            parts = [parts[0] + parts[1], *parts[2:]]
        while at < len(parts):
            end = longest(prefix, parts, at)
            if end > at:
                pieces.append(''.join(parts[at:end]))
                at = end
                continue
            word, low, high = parts[at], 0, len(parts[at])
            while low < high:
                middle = (low + high + 1) // 2
                if fits(prefix, word[:middle]):
                    low = middle
                else:
                    high = middle - 1
            if low == 0:
                raise ValueError('title and section headings of unit ' + row['id'] + ' leave no room in the '
                                 + str(limit) + '-token passage window')
            pieces.append(word[:low])
            parts[at] = word[low:]
        if ''.join(pieces) != row['text']:
            raise ValueError('split pieces differ from the exact located excerpt')
        offset, line_start, location = 0, row['location']['line_start'], row['location']
        for number, piece in enumerate(pieces):
            evidence = deepcopy(row)
            before, encoded = row['text'][:offset], piece.encode('utf-8')
            start = location['byte_start'] + len(before.encode('utf-8'))
            evidence.update(id=row['id'] if number == 0 else row['id'] + '#' + str(number),
                            unit_id=row['unit_id'] if number == 0 else row['unit_id'] + '#' + str(number),
                            text=piece, excerpt_sha256=hashlib.sha256(encoded).hexdigest())
            evidence['location'].update(byte_start=start, byte_end=start + len(encoded))
            if line_start is not None:
                evidence['location'].update(line_start=line_start + _boundary_count(before),
                                            line_end=line_start + _boundary_count(before + piece[:-1]))
            units.append(dict(evidence=evidence, indexed_text=indexed_text(title, location['section_path'], piece),
                              parent_id=unit['parent_id'], section_ids=list(unit['section_ids'])))
            offset += len(piece)
    return validate_corpus(dict(corpus, units=units))


def _pin(pin, base, receipts):
    """Convert checked local custody paths to portable serving names."""
    path = Path(pin['path'])
    path = (base / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        name = path.relative_to(base).as_posix()
    except ValueError:
        raise ValueError('literature source outside supplied corpus root') from None
    if not 0 < pin['size'] <= contract.MAX_SOURCE_BYTES or path.stat().st_size != pin['size']:
        raise ValueError('literature source size changed')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pin['sha256']:
        raise ValueError('literature source bytes changed')
    produced = dict(path=name, sha256=pin['sha256'], size=pin['size'],
                    receipt_id=receipts.get(pin['sha256'], pin.get('receipt_id')))
    contract._validate(produced, 'pin')
    return produced, raw


def _descriptor(pin, identifiers, quantities=(), classes=(), kind='source'):
    return dict(pin=pin, identifiers=deepcopy(identifiers), quantities=list(quantities),
                classes=list(classes), kind=kind)


def corpus_from_products(product_pins, *, base_dir, receipt_ids, bibliography=(), excluded_roots=None):
    """Consume existing located products before compiling their search overlay.

    Receipt IDs come from the trusted build caller, keyed by content hash. No
    acquisition, extraction, summarization or model service is invoked here.
    A product under an excluded root is refused before it is read.
    """
    from .literature_context import consume
    roots = normalize_excluded_roots(excluded_roots)
    for pin in product_pins:
        if roots and excluded(pin['path'], roots, base_dir):
            raise ValueError('a corpus product lies under an excluded root')
    contexts = [consume(pin, base_dir=base_dir) for pin in product_pins]
    return corpus_from_contexts(contexts, base_dir=base_dir, receipt_ids=receipt_ids, bibliography=bibliography,
                                excluded_roots=excluded_roots)


def corpus_from_contexts(contexts, *, base_dir, receipt_ids, bibliography=(), excluded_roots=None):
    """Compile already consumed forests; the caller authenticates their custody.

    Each item is the existing ``consume`` result with ``product`` and ``context``.
    Exact product/source bytes are checked again. A product depends on its whole
    input document population, so its complete lineage is retained even when
    only one of its units is selected. Source-pinned bibliography rows may supply
    a paper title; otherwise the existing citation label is retained explicitly.
    """
    import json
    base = Path(base_dir).resolve()
    roots = normalize_excluded_roots(excluded_roots)
    if roots:
        named = [c['product']['path'] for c in contexts]
        for consumed in contexts:
            for doc in consumed['context']['documents']:
                named += [p['path'] for p in (doc.get('pin'), doc.get('acquisition'), doc.get('extraction'))
                          if isinstance(p, dict)]
        named += [d['pin'].get('path') for item in bibliography if isinstance(item, dict)
                  for d in item.get('lineage') or () if isinstance(d, dict) and isinstance(d.get('pin'), dict)]
        named = [path for path in named if isinstance(path, str)]
        if any(excluded(path, roots, base) for path in named):
            raise ValueError('a corpus member lies under an excluded root')
    corpus = dict(schema_version=1, units=[], papers=[], inputs=[])
    titles = {}
    for item in bibliography:
        if (not isinstance(item, dict) or set(item) != {'document_id', 'version', 'title', 'lineage'}
                or not isinstance(item['title'], str) or not 0 < len(item['title']) <= 2048
                or not isinstance(item['lineage'], list) or not item['lineage']):
            raise ValueError('paper titles require pinned bibliography lineage')
        key = (item['document_id'], item['version'])
        if key in titles:
            raise ValueError('duplicate bibliography identity')
        titles[key] = deepcopy(item)
        for descriptor in item['lineage']:
            contract._validate(descriptor, 'descriptor')
            if descriptor['kind'] != 'source' and descriptor['pin']['receipt_id'] is None:
                raise ValueError('derived bibliography requires a receipt')
            _pin(descriptor['pin'], base, receipt_ids)
    for consumed in contexts:
        context = consumed['context']
        product_pin, product_raw = _pin(consumed['product'], base, receipt_ids)
        if (product_pin['receipt_id'] is None or json.loads(product_raw).get('context') != context
                or context.get('kind') != 'located-literature-context' or context.get('schema_version') != 1):
            raise ValueError('located forest differs from receipted product')
        docs = context['documents']
        all_ids = {'document': sorted(d['id'] for d in docs)}
        acquired_urls = sorted({d['acquisition_outcome']['url'] for d in docs if d.get('acquisition_outcome')})
        if acquired_urls:
            all_ids['url'] = acquired_urls
        lineage = [_descriptor(product_pin, all_ids, kind='generated')]
        originals, extractions = {}, {}
        for doc in docs:
            if doc.get('acquisition') is not None:
                acquisition_pin, acquisition_raw = _pin(doc['acquisition'], base, receipt_ids)
                binding = json.loads(acquisition_raw)
                if binding.get('kind') != 'ordinary-literature-acquisition-binding':
                    raise ValueError('source-produced acquisition binding required')
                outcome_pin, outcome_raw = _pin(binding['product'], base, receipt_ids)
                outcome = json.loads(outcome_raw)
                if (outcome != doc.get('acquisition_outcome')
                        or outcome.get('kind') != 'literature-acquisition-result'
                        or acquisition_pin['receipt_id'] is None or outcome_pin['receipt_id'] is None):
                    raise ValueError('acquisition lineage differs from receipted outcome')
                identifiers = {'document': [doc['id']], 'url': [outcome['url']]}
                lineage.extend([_descriptor(acquisition_pin, identifiers, kind='generated'),
                                _descriptor(outcome_pin, identifiers, kind='generated')])
            if doc['pin'] is not None:
                original, raw = _pin(doc['pin'], base, receipt_ids)
                originals[doc['id']] = original, raw
                lineage.append(_descriptor(original, {'document': [doc['id']]}, doc.get('domain', []), doc.get('tags', [])))
            if doc.get('extraction') is not None:
                binding_pin, binding_raw = _pin(doc['extraction'], base, receipt_ids)
                binding = json.loads(binding_raw)
                if binding.get('kind') != 'ordinary-literature-pdf-binding':
                    raise ValueError('source-produced PDF extraction binding required')
                extraction_pin, extraction_raw = _pin(binding['product'], base, receipt_ids)
                if extraction_pin['receipt_id'] is None or binding_pin['receipt_id'] is None:
                    raise ValueError('PDF extraction and binding require receipts')
                extractions[doc['id']] = extraction_pin, extraction_raw
                lineage.extend([_descriptor(binding_pin, {'document': [doc['id']]}, kind='generated'),
                                _descriptor(extraction_pin, {'document': [doc['id']]}, kind='extracted')])
        corpus['inputs'].extend(lineage)
        for doc in docs:
            original, raw = originals.get(doc['id'], (None, None))
            extraction, extraction_raw = extractions.get(doc['id'], (None, None))
            issues = [f.get('reason', 'Unresolved source parsing') for f in context.get('missing_and_unresolved', [])
                      if f.get('document') == doc['id']]
            title_row = titles.get((doc['id'], doc['version']))
            title = title_row['title'] if title_row else doc['citation']
            doc_lineage = deepcopy(lineage) + (title_row['lineage'] if title_row else [])
            if title_row:
                corpus['inputs'].extend(title_row['lineage'])
            common = dict(document_id=doc['id'], version=doc['version'], original=original, extraction=extraction,
                          extraction_reason=None if extraction else 'No extracted-text artifact; original source coordinates only.',
                          identifiers={'document': [doc['id']], 'tag': doc.get('tags', []), 'domain': doc.get('domain', [])},
                          quantities=doc.get('domain', []), classes=doc.get('tags', []), lineage=doc_lineage,
                          acquisition_status='available' if doc['status'] == 'supplied' else doc['status'],
                          extraction_issues=list(dict.fromkeys(issues)), physics_verified=False, execution_authorized=False)
            paper_id = 'paper:' + digest([doc['id'], doc['version']])
            reason = doc.get('reason') or 'Pinned document; source and extraction limitations retained.'
            if title_row is None:
                reason += ' Title uses the existing citation label; no separate bibliography title supplied.'
            corpus['papers'].append(dict(common, id=paper_id, title=title, reason=reason))
            forest = [u for u in context['units'] if u['document'] == doc['id']]
            by_id = {u['id']: u for u in forest}
            if len(by_id) != len(forest):
                raise ValueError('duplicate located forest units')
            for unit in forest:
                if not unit['text'] or original is None or (doc['format'] == 'pdf' and extraction is None):
                    continue
                ancestry, seen, parent = [], set(), unit
                while parent is not None:
                    if parent['id'] in seen:
                        raise ValueError('cyclic located forest')
                    seen.add(parent['id'])
                    if parent['kind'] == 'section':
                        ancestry.append(parent)
                    if parent['parent'] is not None and parent['parent'] not in by_id:
                        raise ValueError('unknown located forest parent')
                    parent = by_id.get(parent['parent'])
                ancestry.reverse()
                section_path = []
                for section in ancestry:
                    heading = next((u['text'] for u in forest if u['parent'] == section['id'] and u['kind'] == 'heading'), None)
                    # Keep the exact source heading, including markup. This is a
                    # source location label, not an inferred semantic heading.
                    heading = (heading or section['text'].split('\n', 1)[0]).strip()
                    if not heading or len(heading) > 2048:
                        raise ValueError('unrepresentable located section heading')
                    section_path.append(heading)
                page = unit.get('page_index')
                location = dict(section_path=section_path,
                                section_status=('inferred' if page is not None else 'source') if section_path else 'unavailable',
                                page_index=page, page_number=None if page is None else page + 1,
                                printed_page_label=None, line_start=unit['line_start'], line_end=unit['line_end'],
                                byte_start=unit['byte_start'], byte_end=unit['byte_end'],
                                space='pdf-page-text' if page is not None else 'original-text', null_reasons={})
                if unit['kind'] in {'table-row', 'table-cell', 'figure-caption', 'figure-file', 'axis-label'}:
                    location['located_unit'] = dict(kind=unit['kind'], **{
                        key: deepcopy(unit[key])
                        for key in ('row', 'column', 'column_span', 'header', 'units') if key in unit})
                for key in ('page_index', 'page_number', 'printed_page_label', 'line_start', 'line_end'):
                    if location[key] is None:
                        location['null_reasons'][key] = 'Not supplied in this source coordinate space.'
                if not section_path:
                    location['null_reasons']['section_path'] = 'No source section heading is located.'
                row = dict(common, id='unit:' + digest([doc['id'], doc['version'], unit['id']]),
                           unit_id=unit['id'], text=unit['text'], excerpt_sha256=unit['excerpt_sha256'],
                           location=location, scores=_scores(), group_id=None, measurement=None)
                contract.verify_excerpt(row, original=raw, extraction=extraction_raw)
                corpus['units'].append(dict(evidence=row, indexed_text=indexed_text(title, section_path, unit['text']),
                                            parent_id=unit['parent'], section_ids=[a['id'] for a in ancestry]))
    if set(titles) - {(p['document_id'], p['version']) for p in corpus['papers']}:
        raise ValueError('bibliography references an absent document version')
    if roots and any(excluded(path, roots, base) for path in corpus_paths(corpus)):
        raise ValueError('a corpus member lies under an excluded root')
    return validate_corpus(corpus)


def _vector(value, dimensions=None):
    try:
        vector = list(value)
        if (not vector or (dimensions is not None and len(vector) != dimensions)
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector)):
            raise ValueError
        norm = math.hypot(*vector)
        if not math.isfinite(norm) or not norm:
            raise ValueError
        return [v / norm for v in vector]
    except (TypeError, ValueError, OverflowError):
        raise ValueError('invalid literature model vector') from None


class HybridLiteratureProvider:
    """Policy-projected cosine/BM25 RRF with bounded local cross-encoding.

    ``flat`` omits structural expansion; ``hybrid`` reserves expansion slots.
    ``tree`` is explicitly unsupported. Model inference must be bounded by the
    installed adapter; checks before and after every call reject late results.
    A broker-owned cursor key (at least 32 bytes) permits restart-safe paging.
    """
    provider_id = 'local-hybrid'

    def __init__(self, snapshot, *, embedder, reranker, cursor_key, clock=time.monotonic):
        from .literature_build import validate_snapshot
        self._snapshot = validate_snapshot(snapshot)
        if not isinstance(cursor_key, bytes) or len(cursor_key) < 32:
            raise ValueError('trusted literature cursor key required')
        self._key, self._clock = cursor_key, clock
        self._embedder, self._reranker = embedder, reranker
        self._manifest = self._snapshot['manifest']
        self._settings = self._manifest['settings']
        self._check_models()

    def _check_models(self):
        if (contract.canonical(self._embedder.identity) != contract.canonical(self._manifest['embedding'])
                or contract.canonical(self._reranker.identity) != contract.canonical(self._manifest['reranker'])):
            raise ValueError('literature model identity differs from index')

    def index_identity(self, view):
        return dict(id=self._manifest['id'], manifest_sha256=self._manifest['manifest_sha256'],
                    policy_view_sha256=view.policy_sha256)

    def _permitted(self, row, view):
        descriptors = list(row['lineage'])
        if row['original'] is not None:
            descriptors.append(_descriptor(row['original'], row['identifiers'], row['quantities'], row['classes']))
        if row['extraction'] is not None:
            descriptors.append(_descriptor(row['extraction'], row['identifiers'], row['quantities'], row['classes'], 'extracted'))
        return all(view.permits(deepcopy(d)) for d in descriptors)

    @staticmethod
    def _matches(row, filters):
        for key, required in filters.items():
            if key in ('document_id', 'version', 'acquisition_status'):
                actual = [row[key]]
            elif key in ('classes', 'quantities'):
                actual = row[key]
            else:
                actual = row['identifiers'].get(key, [])
            if not set(required).intersection(actual):
                return False
        return True

    def _cursor(self, offset, request, index, view):
        binding = dict(index, selector_sha256=contract.selector_digest(request))
        payload = dict(binding, offset=offset, run=view.run_id, node=view.node_id, role=view.role)
        encoded = base64.urlsafe_b64encode(contract.canonical(payload)).decode().rstrip('=')
        signature = hmac.new(self._key, encoded.encode(), hashlib.sha256).hexdigest()
        return dict(binding, token=encoded + '.' + signature)

    def _offset(self, request, index, view):
        import json
        cursor = request['args'].get('cursor')
        if cursor is None:
            return 0
        try:
            encoded, signature = cursor['token'].split('.')
            expected = hmac.new(self._key, encoded.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            payload = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
            offset = payload['offset']
            if type(offset) is not int or offset < 1 or self._cursor(offset, request, index, view) != cursor:
                raise ValueError
            return offset
        except (ValueError, KeyError, TypeError, UnicodeError):
            raise ValueError('invalid literature cursor binding') from None

    @staticmethod
    def _issue(code, reason):
        return dict(code=code, id='retrieval', reason=reason)

    def _rank(self, records, query, top_k, state):
        if not records:
            return []
        state['check']()
        remaining = state['cap'] - state['expansions']
        if len(records) > remaining:
            records = records[:remaining]
            state['limited'] = True
        if not records:
            return []
        state['expansions'] += len(records)
        self._check_models()
        try:
            query_vector = _vector(self._embedder.embed_query(query), self._manifest['dimensions'])
        except Exception:
            raise ValueError('literature query embedding failed') from None
        state['check']()
        self._check_models()
        rows = [dict(id=record['evidence']['id'], indexed_text=record['indexed_text']) for record, _ in records]
        bm25 = {row['id']: score for score, row, _ in rank_literature(rows, query)}
        dense = {u['evidence']['id']: sum(a*b for a, b in zip(query_vector, _vector(v))) for u, v in records}
        by_id = {u['evidence']['id']: u for u, _ in records}
        tie = lambda identity: _identity(by_id[identity]['evidence'])
        lexical_order = sorted(bm25, key=lambda i: (-bm25[i], tie(i)))
        dense_order = sorted(dense, key=lambda i: (-dense[i], tie(i)))
        fusion = {}
        for ranking in (lexical_order, dense_order):
            for rank, identity in enumerate(ranking, 1):
                fusion[identity] = fusion.get(identity, 0.0) + 1.0 / (self._settings['rrf_k'] + rank)
        selected = sorted(fusion, key=lambda i: (-fusion[i], tie(i)))[:max(top_k, self._settings['candidate_k'])]
        state['check']()
        try:
            reranked = list(self._reranker.score(query, [by_id[i]['indexed_text'] for i in selected]))
            if len(reranked) != len(selected) or any(type(s) not in (int, float) or not math.isfinite(s) or abs(s) > 1e100 for s in reranked):
                raise ValueError
        except Exception:
            raise ValueError('literature reranking failed') from None
        state['check']()
        self._check_models()
        scores = dict(zip(selected, reranked))
        ordered = sorted(selected, key=lambda i: (-scores[i], -fusion[i], tie(i)))
        output = []
        for identity in ordered[:top_k]:
            row = deepcopy(by_id[identity]['evidence'])
            row['scores'] = dict(_scores(), dense_raw=dense[identity], bm25=bm25.get(identity),
                                 fusion=fusion[identity], reranker=scores[identity])
            output.append(row)
        return output

    def _expand(self, primary, records, top_k, state):
        if not primary:
            return primary
        lookup = {_identity(u['evidence']): u for u, _ in records}
        selected = {r['id'] for r in primary}
        result = list(primary)
        for row in primary:
            unit = lookup[_identity(row)]
            keys = []
            if self._settings['expand_sections']:
                keys.extend(_identity(row)[:2] + (s,) for s in reversed(unit['section_ids']) if s != row['unit_id'])
            siblings = sorted([u for u, _ in records if _identity(u['evidence'])[:2] == _identity(row)[:2]
                               and u['parent_id'] == unit['parent_id']],
                              key=lambda u: (u['evidence']['location']['page_index'] or 0,
                                             u['evidence']['location']['byte_start'], u['evidence']['unit_id']))
            pos = next(i for i, u in enumerate(siblings) if u['evidence']['id'] == row['id'])
            for distance in range(1, self._settings['neighbour_radius'] + 1):
                for index in (pos - distance, pos + distance):
                    if 0 <= index < len(siblings):
                        keys.append(_identity(siblings[index]['evidence']))
            for key in keys:
                state['check']()
                candidate = lookup.get(key)
                if candidate is None or candidate['evidence']['id'] in selected:
                    continue
                if len(result) >= top_k:
                    return result
                if state['expansions'] >= state['cap']:
                    state['limited'] = True
                    return result
                state['expansions'] += 1
                extra = deepcopy(candidate['evidence'])
                extra['scores'] = _scores()
                result.append(extra)
                selected.add(extra['id'])
        return result

    def _run(self, request, view, operation):
        request = contract.validate_request(request)
        if request['operation'] != operation:
            raise ValueError('literature operation differs from method')
        start = self._clock()
        budget, args = request['budgets'], request['args']
        def check():
            if self._clock() - start > budget['max_seconds']:
                raise TimeoutError('literature retrieval deadline exhausted')
        state = dict(check=check, expansions=0, cap=budget['max_expansions'], limited=False)
        index = self.index_identity(view)
        contract._validate(index, 'index')
        envelope = dict(schema_version=1, operation=operation, request_id=request['request_id'],
                        provider_id=self.provider_id, index=index, results=[], metadata=[], groups=[],
                        next_cursor=None, omitted=[], failures=[],
                        usage=dict(elapsed_seconds=0.0, expansions=0, token_accounting='utf8-byte-upper-bound'),
                        receipt_id='candidate:' + digest([request, index, view.run_id, view.node_id, view.role, view.attempt]))
        # No restricted record influences IDF, ranking, counts, model inputs,
        # neighbours, group existence or pagination positions.
        papers, records = [], []
        for paper in self._snapshot['corpus']['papers']:
            check()
            if self._permitted(paper, view) and self._matches(paper, args.get('filters', {})):
                papers.append(paper)
        permitted_papers = {(p['document_id'], p['version']) for p in papers}
        for unit, vector in zip(self._snapshot['corpus']['units'], self._snapshot['vectors']):
            check()
            row = unit['evidence']
            if _identity(row)[:2] not in permitted_papers or not self._permitted(row, view):
                continue
            scope = args.get('document_scope', [])
            if scope and dict(document_id=row['document_id'], version=row['version']) not in scope:
                continue
            records.append((unit, vector))
        offset = self._offset(request, index, view)
        paginated = None
        if operation == 'search':
            if args['mode'] == 'tree':
                envelope['omitted'].append(self._issue('unsupported', 'Tree diffusion is not provided by this index.'))
            else:
                slots = min(self._settings['expansion_slots'], args['top_k'] - 1) if args['mode'] == 'hybrid' else 0
                primary = self._rank(records, args['query'], args['top_k'], state)
                expanded = self._expand(primary[:args['top_k'] - slots], records, args['top_k'], state) if slots else primary
                ids = {r['id'] for r in expanded}
                envelope['results'] = (expanded + [r for r in primary if r['id'] not in ids])[:args['top_k']]
        elif operation == 'list_papers':
            paginated = ('metadata', papers)
        elif operation == 'get_paper':
            matching = [p for p in papers if p['document_id'] == args['document_id']
                        and (args['version'] is None or p['version'] == args['version'])]
            if args['version'] is None and len(matching) > 1:
                envelope['omitted'].append(self._issue('unsupported', 'Multiple pinned versions exist; select an exact version.'))
            elif matching:
                paper = matching[0]
                located = [deepcopy(u['evidence']) for u, _ in records if _identity(u['evidence'])[:2] == _identity(paper)[:2]
                           and (args['page_index'] is None or u['evidence']['location']['page_index'] == args['page_index'])
                           and (args['section'] is None or args['section'] in u['evidence']['location']['section_path'])]
                for row in located:
                    row['scores'] = _scores()
                located.sort(key=lambda r: (r['location']['page_index'] or 0, r['location']['byte_start'], r['location']['byte_end'], r['unit_id']))
                if located:
                    paginated = ('results', located)
                elif args['page_index'] is None and args['section'] is None:
                    paginated = ('metadata', [paper])
        else:
            for group in args['groups']:
                check()
                group_records = [(u, v) for u, v in records if u['evidence']['measurement'] is not None and
                                 group in [*u['evidence']['classes'], *u['evidence']['quantities'],
                                           *[x for values in u['evidence']['identifiers'].values() for x in values]]]
                rows = self._rank(group_records, args['topic'], args['top_k_per_group'], state)
                for row in rows:
                    row['group_id'] = group
                    row['id'] = 'group:' + digest([group, row['id']])
                envelope['results'].extend(rows)
                envelope['groups'].append(dict(id=group, status='available' if rows else 'empty',
                                                result_ids=[r['id'] for r in rows],
                                                reason=None if rows else 'No permitted located measurement matches this group.'))
        if paginated is not None:
            field, population = paginated
            if offset > len(population):
                raise ValueError('literature cursor outside current selection')
            count = min(args['limit'], budget['max_expansions'])
            envelope[field] = deepcopy(population[offset:offset + count])
            state['expansions'] = len(envelope[field])
            if offset + len(envelope[field]) < len(population):
                envelope['next_cursor'] = self._cursor(offset + len(envelope[field]), request, index, view)
        if state['limited']:
            envelope['omitted'].append(self._issue('budget', 'Expansion budget limited the permitted candidate population.'))
        if not envelope['results'] and not envelope['metadata'] and operation != 'compare_measurements' and not envelope['omitted']:
            envelope['omitted'].append(self._issue('no_match', 'No permitted located material matches these selectors.'))
        # Bound the COMPLETE envelope using the contract's conservative byte-token law.
        # Whole excerpts are omitted, never truncated into different evidence.
        cap = min(budget['max_bytes'], budget['max_tokens'])
        while True:
            check()
            for rank, row in enumerate(envelope['results'], 1):
                row['scores']['rank'] = rank
            for group in envelope['groups']:
                group['result_ids'] = [r['id'] for r in envelope['results'] if r['group_id'] == group['id']]
                group['status'] = 'available' if group['result_ids'] else 'empty'
                group['reason'] = None if group['result_ids'] else 'No located measurement was returned within these selectors and budgets.'
            envelope['usage'].update(elapsed_seconds=max(0.0, self._clock() - start), expansions=state['expansions'])
            if len(contract.canonical(envelope)) <= cap:
                break
            field = 'results' if envelope['results'] else 'metadata'
            if not envelope[field]:
                raise ValueError('literature envelope cannot fit requested budgets')
            envelope[field].pop()
            if not any(i['code'] == 'budget' for i in envelope['omitted']):
                envelope['omitted'].append(self._issue('budget', 'Whole evidence omitted to fit the complete envelope.'))
            if paginated is not None:
                count = len(envelope[paginated[0]])
                # A zero-result page cannot advance past unserved material.
                envelope['next_cursor'] = self._cursor(offset + count, request, index, view) if count else None
        # A fresh projection immediately before return catches changed views.
        if any(not self._permitted(row, view) for row in envelope['results'] + envelope['metadata']):
            raise ValueError('literature source view changed during retrieval')
        check()
        result = contract.validate_candidates(envelope, request, provider_id=self.provider_id, index=index)
        check()
        return result

    def search(self, request, *, view):
        return self._run(request, view, 'search')

    def get_paper(self, request, *, view):
        return self._run(request, view, 'get_paper')

    def list_papers(self, request, *, view):
        return self._run(request, view, 'list_papers')

    def compare_measurements(self, request, *, view):
        return self._run(request, view, 'compare_measurements')
