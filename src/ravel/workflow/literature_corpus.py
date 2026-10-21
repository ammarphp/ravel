"""Corpus plans for located literature: admission, governed acquisition and census.

A plan names documents chosen by recorded metadata criteria, their exact
originals and per-source terms. It is installation data, not a corpus, a
relevance judgement or a licence grant. Admission screens every document with
the unchanged ``source_policy`` matching law over alias-closed identifiers,
plus an optional citation closure and an identifier scan of its title.

Acquisition runs only the existing governed tools (``acquire_literature``,
``extract_literature_pdf`` and ``prepare_literature_context`` in
``research_tools``) inside an existing campaign, one document at a time and
paced per origin. Every outcome is retained, including failures; nothing is
fetched here directly, retried silently or summarised by a model. Build
admission re-screens each located product's lineage and scans its located text
before the product may enter an index build.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import time

from jsonschema import Draft202012Validator, validators

from . import literature_context as lc, source_policy

KEYS = ('inspire', 'arxiv', 'doi', 'analysis', 'hepdata')
MAX_PLAN_BYTES = 16 * 1024 * 1024
# A located request's knowledge query selects by this tag only, so a corpus
# product carries its whole forest without a preselected knowledge packet.
QUERY_TAG = 'corpus-build-no-preselection'
PARTIAL = 'Some original pages have no extracted text.'
CLAIMS = {**lc.FLAGS, 'relevance_verified': False, 'licence_verified': False,
          'exclusion_complete': False}

# Licences whose redistribution terms are recorded here; any other statement,
# including an absent one, is local use only. Keys are canonical URLs.
LICENCES = {
    'creativecommons.org/licenses/by/4.0': ('CC BY 4.0', 'permitted', 'permitted'),
    'creativecommons.org/licenses/by/3.0': ('CC BY 3.0', 'permitted', 'permitted'),
    'creativecommons.org/licenses/by-sa/4.0': ('CC BY-SA 4.0 (share-alike)', 'permitted', 'permitted'),
    'creativecommons.org/licenses/by-nd/4.0': ('CC BY-ND 4.0 (no derivatives)', 'permitted', 'local-only'),
    'creativecommons.org/licenses/by-nc/4.0': ('CC BY-NC 4.0 (non-commercial)', 'local-only', 'local-only'),
    'creativecommons.org/licenses/by-nc-sa/4.0': ('CC BY-NC-SA 4.0 (non-commercial)', 'local-only', 'local-only'),
    'creativecommons.org/licenses/by-nc-nd/4.0': ('CC BY-NC-ND 4.0 (non-commercial, no derivatives)', 'local-only', 'local-only'),
    'creativecommons.org/publicdomain/zero/1.0': ('CC0 1.0', 'permitted', 'permitted'),
    'arxiv.org/licenses/nonexclusive-distrib/1.0': ('arXiv non-exclusive distribution licence 1.0', 'local-only', 'local-only'),
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


@lru_cache(maxsize=8)
def _validator(definition):
    schema = json.loads(files('ravel.data').joinpath('knowledge/schema/literature-corpus.json').read_text())
    schema = {'$defs': schema['$defs'], '$ref': '#/$defs/' + definition}
    checker = Draft202012Validator.TYPE_CHECKER.redefine('integer', lambda checker, value: type(value) is int)
    return validators.extend(Draft202012Validator, type_checker=checker)(schema)


def _schema(value, definition):
    try:
        valid = _validator(definition).is_valid(value)
    except (ValueError, TypeError, RecursionError, OverflowError):
        valid = False
    if not valid:
        raise ValueError('invalid literature corpus ' + definition)
    return deepcopy(value)


def _licence_key(url):
    key = re.sub(r'^https?://(?:www\.)?', '', url.strip().lower())
    key = re.sub(r'/(?:legalcode(?:\.[a-z-]+)?|deed\.[a-z-]+)?/?$', '', key)
    return key.rstrip('/')


def terms(licence, provenance):
    """Recorded terms for one original; unknown licences stay local use only."""
    known = LICENCES.get(_licence_key(licence['url'])) if licence and licence['url'] else None
    if known is None:
        label = 'No licence statement recorded' if licence is None else 'Unrecognised licence statement'
        return {'licence': deepcopy(licence), 'provenance': provenance, 'redistribution': 'local-only',
                'derivatives': 'local-only', 'attribution': True,
                'basis': label + ': local use only; no redistribution of full text, extractions or derivatives.'}
    name, redistribution, derivatives = known
    return {'licence': deepcopy(licence), 'provenance': provenance, 'redistribution': redistribution,
            'derivatives': derivatives, 'attribution': not name.startswith('CC0'),
            'basis': 'Recognised licence ' + name + ': redistribution ' + redistribution + ', derivatives '
                     + derivatives + '; only under that licence with its notices, never relicensed.'}


def canonical_identifier(key, value):
    """One comparison form per identity; spellings differ, the identity does not."""
    value = value.strip()
    if key == 'arxiv':
        value = re.sub(r'v[1-9][0-9]*$', '', re.sub(r'(?i)^arxiv:', '', value)).lower()
        if not re.fullmatch(r'[0-9]{4}\.[0-9]{4,5}|[a-z][a-z.-]*/[0-9]{7}', value):
            raise ValueError('literature corpus arXiv identifier required')
    elif key == 'inspire':
        value = re.sub(r'(?i)^(?:inspire:|ins)', '', value)
        if not re.fullmatch(r'[1-9][0-9]{0,15}', value):
            raise ValueError('literature corpus INSPIRE identifier required')
    elif key == 'hepdata':
        value = re.sub(r'(?i)^(?:hepdata:)?(?:ins)?', '', value)
        if not re.fullmatch(r'[1-9][0-9]{0,15}', value):
            raise ValueError('literature corpus data-record identifier required')
        value = 'ins' + value
    elif key == 'doi':
        value = re.sub(r'(?i)^doi:', '', value).lower()
        if not re.fullmatch(r'10\.[0-9]{4,9}/\S+', value):
            raise ValueError('literature corpus DOI required')
    elif key == 'analysis':
        value = re.sub(r'[\s_-]+', '-', value.upper()).strip('-')
        if not re.fullmatch(r'[A-Z0-9]+(?:-[A-Z0-9]+)*', value):
            raise ValueError('literature corpus report number required')
    else:
        raise ValueError('unknown literature corpus identifier kind')
    return value


def _spellings(key, value):
    if key == 'arxiv':
        return {value, 'arXiv:' + value}
    if key == 'inspire':
        return {value, 'INSPIRE:' + value}
    if key == 'hepdata':
        return {value, value[3:]}
    if key == 'doi':
        return {value, 'doi:' + value}
    return {value}


def _identities(identifiers):
    """Canonical identities; a paper and its data record share one identity."""
    found = {key: set() for key in KEYS}
    for key, values in identifiers.items():
        found[key].update(canonical_identifier(key, v) for v in values)
    found['hepdata'].update('ins' + v for v in list(found['inspire']))
    found['inspire'].update(v[3:] for v in list(found['hepdata']))
    return found


def descriptor(document, rules=()):
    """A ``source_policy`` descriptor that every spelling of the identity meets.

    Each rule's own spelling of an identity the document has is added, so the
    unchanged exact-match law applies. A corpus derivative may encode any
    quantity of its source, so scoped extraction bans located at the document
    restrict the whole document.
    """
    found = _identities(document['identifiers'])
    spellings = {key: set() for key in KEYS}
    for key, values in found.items():
        for value in values:
            spellings[key] |= _spellings(key, value)
    for key, values in document['identifiers'].items():
        spellings[key].update(values)
    if document['version'] is not None and found['arxiv']:
        spellings['arxiv'].update({document['version'], 'arXiv:' + document['version']})
    for row in rules:
        for key, values in row.get('identifiers', {}).items():
            for value in values:
                try:
                    if canonical_identifier(key, value) in found[key]:
                        spellings[key].add(value)
                except ValueError:
                    continue  # A spelling of another identity kind cannot locate this one.
    quantities = sorted({q for row in rules for q in row.get('scope', {}).get('quantities', [])})
    return {'identifiers': {k: sorted(v) for k, v in spellings.items() if v},
            'classes': sorted(document['labels']), 'quantities': quantities}


def _unique(rows, what):
    ids = [row['id'] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('unique literature corpus ' + what + ' identities required')
    return set(ids)


def validate_plan(plan):
    """Closed plan; terms, identities, origins and the screen census are recomputed."""
    plan = _schema(plan, 'plan')
    responses = _unique(plan['selection']['responses'], 'response')
    _unique(plan['selection']['criteria'], 'criterion')
    configured = lc.origins([o['origin'] for o in plan['origins']])
    if [o['origin'] for o in plan['origins']] != configured:
        raise ValueError('canonical literature corpus origins required')
    _unique(plan['documents'], 'document')
    seen = {}
    for doc in plan['documents']:
        if (doc['source'] is None) == (doc['source_reason'] is None):
            raise ValueError('exactly one declared original or reason for its absence required')
        if doc['version'] is not None and doc['source'] is None:
            raise ValueError('a versioned document requires its declared original')
        if doc['metadata']['response'] not in responses:
            raise ValueError('document metadata must locate a pinned selection response')
        if QUERY_TAG in doc['labels']:
            raise ValueError('reserved literature corpus label')
        lc.knowledge._labels(doc['labels'])
        found = _identities(doc['identifiers'])
        for key, values in found.items():
            for value in values:
                if seen.setdefault((key, value), doc['id']) != doc['id']:
                    raise ValueError('one plan document per original identity required')
        if doc['version'] is not None and found['arxiv'] and not any(
                re.fullmatch(re.escape(a) + r'v[1-9][0-9]*', doc['version']) for a in found['arxiv']):
            raise ValueError('declared version must be an exact version of the declared identity')
        if doc['source'] is not None:
            _, origin = lc._url(doc['source']['url'])
            if origin not in configured:
                raise ValueError('document original must use a configured paced origin')
            if len(doc['source']['url'].encode()) > 2048:
                raise ValueError('bounded original URL required')
        if doc['terms'] != terms(doc['terms']['licence'], doc['terms']['provenance']):
            raise ValueError('declared terms differ from the recorded licence classification')
        if len(_licence_text(doc).encode()) > 2048:
            raise ValueError('bounded licence statement and provenance required')
    screen = plan['screen']
    # One refused document may meet several rules; counts are per rule and check.
    if screen is not None and (screen['admitted'] != len(plan['documents'])
                               or screen['screened'] != screen['admitted'] + screen['refused_documents']
                               or bool(screen['refused']) != bool(screen['refused_documents'])
                               or any(v > screen['refused_documents'] for v in screen['refused'].values())):
        raise ValueError('literature corpus screen census differs from its documents')
    return plan


def validate_exclusion(exclusion):
    """Closed exclusion list: canonical source-policy rows plus declared closure."""
    exclusion = _schema(exclusion, 'exclusion')
    rules = source_policy.canonical(exclusion['rules'])
    if any(type(row.get('id')) is not str or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', row['id']) for row in rules):
        raise ValueError('every exclusion rule needs a bounded identity')
    _unique(rules, 'rule')
    _unique(exclusion['evidence'], 'evidence')
    for row in rules:
        for key, values in row.get('identifiers', {}).items():
            for value in values:
                canonical_identifier(key, value)
    located = dict(_located(rules))
    closure = exclusion['closure']
    # References are provider record lists, so a citation closure needs a record identity.
    if (any(r not in located for r in closure['text'])
            or any(r not in located or not located[r]['inspire'] for r in closure['cited'])):
        raise ValueError('closure must name exclusion rules that locate the identity it follows')
    exclusion['rules'] = rules
    return exclusion


def _located(rules):
    """Canonical identities each located rule names (all four policy kinds)."""
    located = []
    for row in rules:
        found = _identities(row.get('identifiers', {}))
        if any(found.values()):
            located.append((row['id'], found))
    return located


_SEP = r'[\s_\-\u2010-\u2015]*'  # Spaces, underscores, ASCII and typographic hyphens.


def _pattern(found):
    """Literal identifier spellings in running text; conservative, not semantic."""
    parts = []
    for value in sorted(found['arxiv']):
        # Links (``/abs/<number>``) and the registered DOI (``arXiv.<number>``) name the number too.
        parts.append(r'(?:(?<=arxiv\.)|(?<![0-9a-z.-]))' + re.escape(value) + r'(?:v[0-9]+)?(?![0-9])')
    for value in sorted(found['analysis']):
        tokens = [re.escape(t) for t in value.split('-')]
        forms = [tokens[0] + (r'(?:' + _SEP + r'[a-z]{2,5})?' + _SEP + _SEP.join(tokens[1:]) if len(tokens) > 1 else '')]
        if len(tokens) >= 4:
            forms.append(_SEP.join(tokens[1:]))
        parts.extend(r'(?<![a-z0-9])' + form + r'(?![a-z0-9])' for form in forms)
    for value in sorted(found['inspire']):
        parts.append(r'(?:inspirehep\.net/(?:api/)?(?:literature|record)/|recid\s*[:=/]?\s*|inspire\s*:\s*)'
                     + value + r'(?![0-9])')
    for value in sorted(found['hepdata']):
        parts.append(r'(?<![a-z0-9])' + value + r'(?![0-9])')
    for value in sorted(found['doi']):
        parts.append(re.escape(value) + r'(?![0-9a-z])')
    return re.compile('|'.join(parts), re.IGNORECASE) if parts else None


def _refusals(document, exclusion, texts):
    """Identity under every rule; citation and text closure under named rules only.

    An enumerated set of citing records is an identity rule. Naming it in a
    closure would also refuse whatever cites those records, a second order the
    list must declare by naming that rule explicitly.
    """
    rules = exclusion['rules']
    reasons = [{'rule': row['id'], 'check': 'identity'}
               for row in source_policy.read_receipt(rules, descriptor(document, rules))['rules']]
    closure = exclusion['closure']
    if closure['cited']:
        references = document['references']
        if references['status'] == 'unknown':
            if closure['unknown_references'] == 'refuse':
                reasons.append({'rule': None, 'check': 'unknown-references'})
        else:
            cited = set(references['inspire'])
            reasons.extend({'rule': rule, 'check': 'cited'} for rule, found in _located(rules)
                           if rule in closure['cited'] and cited & found['inspire'])
    if closure['text']:
        for rule, found in _located(rules):
            if rule not in closure['text']:
                continue
            pattern = _pattern(found)
            if pattern is not None and any(pattern.search(text) for text in texts):
                reasons.append({'rule': rule, 'check': 'text'})
    return reasons


def _count(refusals):
    counts = {}
    for row in refusals:
        for reason in row['reasons']:
            key = (reason['rule'] or 'closure') + ':' + reason['check']
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def screen(plan, exclusion):
    """Admit plan documents the exclusion list does not refuse.

    The admitted plan keeps only counts per rule and check; the refusals, with
    the refused identities, are returned for supervisor custody only.
    """
    plan, exclusion = validate_plan(plan), validate_exclusion(exclusion)
    admitted, refusals = [], []
    for doc in plan['documents']:
        reasons = _refusals(doc, exclusion, [doc['title']])
        if reasons:
            refusals.append({'document': deepcopy(doc), 'reasons': reasons})
        else:
            admitted.append(doc)
    previous = plan['screen']['refused_documents'] if plan['screen'] else 0
    if plan['screen'] is not None and plan['screen']['exclusion_sha256'] != digest(exclusion):
        raise ValueError('plan was admitted under another exclusion list')
    refused = _count(refusals)
    if plan['screen'] is not None:
        for key, value in plan['screen']['refused'].items():
            refused[key] = refused.get(key, 0) + value
    result = {**plan, 'documents': admitted,
              'screen': {'exclusion_sha256': digest(exclusion), 'screened': len(plan['documents']) + previous,
                         'admitted': len(admitted), 'refused_documents': len(refusals) + previous,
                         'refused': dict(sorted(refused.items()))}}
    return {'plan': validate_plan(result), 'refusals': refusals, 'claims': deepcopy(CLAIMS)}


def _admitted(plan, exclusion):
    if plan['screen'] is None or plan['screen']['exclusion_sha256'] != digest(exclusion):
        raise ValueError('acquisition requires a plan admitted under this exclusion list')
    if screen(plan, exclusion)['refusals']:
        raise ValueError('admitted plan contains a document the exclusion list refuses')


def _document_json(reader, pin, maximum):
    _, raw = reader.read(pin, maximum)
    return lc.knowledge._json(raw)


def _pin(path, base):
    path = lc._path(path, base)
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def located_version(document):
    return document['version'] or 'Unversioned original; its exact identity is the acquired content SHA256'


def _task(document, plan):
    return {'obligation_id': document['id'], 'query': 'Acquire and locate corpus document ' + document['id'] + '.',
            'source_scope': 'The declared public original in corpus plan ' + plan['id'] + ' only.', 'claim_ids': [],
            'failure_or_missing': 'An unacquired corpus original stays missing; no other source may stand in.'}


def _licence_text(document):
    t = document['terms']
    licence = t['licence']
    stated = 'No licence statement recorded' if licence is None else licence['statement'] + (
        ' <' + licence['url'] + '>' if licence['url'] else '')
    return stated + ' (' + t['provenance'] + '). ' + t['basis']


def _row(document, plan, *, status, pin=None, reason=None, acquisition=None, extraction=None):
    source = document['source']
    return {'id': document['id'], 'pin': pin, 'citation': source['url'] if source else 'Corpus plan ' + plan['id'] + ' document ' + document['id'],
            'version': located_version(document), 'license': _licence_text(document),
            'access': 'Public original through a configured paced origin; local use under the recorded terms.',
            'format': source['format'] if source else 'text', 'status': status, 'reason': reason, 'parents': [],
            'extraction': extraction, 'acquisition': acquisition, 'tags': list(document['labels']), 'domain': [],
            'conventions': [], 'task_ids': [document['id']]}


def _locate(root, binding, directory, document, plan, row, tools):
    request = {'schema_version': 1, 'kind': 'literature-context-request', 'id': 'corpus-' + document['id'],
               'cycle_binding': binding, 'documents': [row],
               'query': {'text': 'Corpus build forest', 'tags': [QUERY_TAG], 'roots': [], 'domain': [], 'max_nodes': 512},
               'annotations': [], 'hypotheses': [], 'edges': [], 'acquisition_tasks': [_task(document, plan)]}
    pin = _write(directory / 'location-request.json', request)
    return tools.prepare_literature_context(root, pin, directory / 'located',
        reason='Corpus build: retain the located forest and every missing or unresolved population.')


def _write(path, value):
    """Write once: the complete bytes appear under ``path`` or nothing does."""
    raw = lc._raw(value)
    temporary = path.with_name('.' + path.name + '.partial')
    with temporary.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()
    return lc._pin(path, raw)


def _brief(exc):
    return (type(exc).__name__ + ': ' + str(exc))[:2000]


def _received(document, plan, acquisition, extraction, *, base):
    """Outcome fields and the located-request row derived from current receipts."""
    fields = {'status': 'located', 'stage': 'complete', 'reason': None, 'acquisition': acquisition,
              'extraction': extraction, 'product': None, 'unresolved': 0}
    if document['source'] is None:
        reason = document['source_reason']
        return ({**fields, 'status': 'unsupported', 'stage': 'acquisition', 'reason': reason},
                _row(document, plan, status='unsupported', reason=reason))
    acquired = lc.consume_acquisition(acquisition, base_dir=base)
    if acquired['status'] != 'acquired':
        return ({**fields, 'status': 'failed', 'stage': 'acquisition', 'reason': acquired['failure']},
                _row(document, plan, status='failed', reason=acquired['failure'], acquisition=acquisition))
    if extraction is not None:
        extracted = lc.consume_pdf(extraction, base_dir=base)
        if extracted['status'] == 'failed':
            fields.update(status='failed', stage='extraction', reason=extracted['failure'])
        elif extracted['status'] == 'partial':
            fields.update(status='located-partial', reason=PARTIAL)
    return fields, _row(document, plan, status='supplied', pin=acquired['source_artifact'],
                        acquisition=acquisition, extraction=extraction)


def _process(document, plan, *, root, binding, directory, host, pace, prior=None):
    """One document through the existing tools; returns the outcome fields.

    With ``prior`` (an earlier outcome that failed at location) only location
    runs again, over that outcome's own acquisition and extraction receipts.
    """
    from . import research_tools as tools
    limits, source = plan['limits'], document['source']
    acquisition = extraction = None
    deferred = {'status': 'deferred', 'stage': 'campaign', 'acquisition': None, 'extraction': None,
                'product': None, 'unresolved': 0}
    if prior is not None:
        acquisition, extraction = prior['acquisition'], prior['extraction']
    elif source is not None:
        request = {'schema_version': 1, 'kind': 'literature-acquisition', 'url': source['url'], 'format': source['format'],
                   'expected_sha256': source['sha256'], 'max_bytes': limits['max_source_bytes'],
                   'max_seconds': limits['max_seconds'], 'tasks': [_task(document, plan)]}
        pin = _write(directory / 'acquisition-request.json', request)
        pace(lc._url(source['url'])[1])
        try:
            acquired = tools.acquire_literature(root, pin, directory / 'acquisition', host,
                                                max_wall_seconds=limits['max_seconds'])
        except (ValueError, OSError, RuntimeError) as exc:
            return {**deferred, 'reason': _brief(exc)}
        acquisition = acquired['binding']
        if acquired['status'] == 'acquired' and source['format'] == 'pdf':
            request = {'schema_version': 1, 'kind': 'literature-pdf-extraction', 'source': acquired['source_artifact'],
                       'max_pages': limits['max_pages'], 'max_text_bytes': limits['max_text_bytes'],
                       'max_seconds': limits['max_seconds']}
            pin = _write(directory / 'extraction-request.json', request)
            try:
                extraction = tools.extract_literature_pdf(root, pin, directory / 'extraction', host,
                                                          max_wall_seconds=limits['max_seconds'])['binding']
            except (ValueError, OSError, RuntimeError) as exc:
                return {**deferred, 'acquisition': acquisition, 'reason': _brief(exc)}
    fields, row = _received(document, plan, acquisition, extraction, base=binding['base'])
    try:
        located = _locate(root, {k: binding[k] for k in ('root', 'contract_sha256')}, directory, document, plan, row, tools)
    except Exception as exc:  # One unlocatable original never stops the build; its error type is retained.
        reason = ((fields['reason'] + ' ') if fields['reason'] else '') + 'Location: ' + _brief(exc)
        return {**fields, 'status': 'failed', 'stage': 'location', 'reason': reason[:8000]}
    fields['product'] = located['product']
    fields['unresolved'] = len(located['context']['missing_and_unresolved'])
    return fields


def _campaign(campaign_root):
    from . import research_cycle as cycle
    root = cycle._ordinary(campaign_root)
    _, state = cycle._load(root)
    return root, state, {'root': str(root), 'contract_sha256': cycle.ce.digest(state['contract']),
                         'base': state['base_dir']}


def acquire(plan_pin, exclusion_pin, *, campaign_root, host, out, previous=(), relocate=False,
            sleep=time.sleep, clock=time.monotonic):
    """Acquire, extract and locate admitted plan documents in plan order.

    At most ``documents_per_campaign`` documents per output directory. A
    document with a recorded outcome here, or a final one in a ``previous``
    record of the same plan, is not attempted again. A tool that cannot run
    (budget, wall clock, Host policy) defers that document and stops the run;
    an earlier interrupted attempt is deferred too. A fresh campaign output
    retries deferred documents. With ``relocate``, a document whose latest
    previous outcome failed at location is located again from that outcome's
    acquisition and extraction receipts, without a new request. Requests to one
    origin are spaced by its declared interval, starting one interval after the
    call. Returns the recomputed record.
    """
    root, state, binding = _campaign(campaign_root)
    reader = lc._Reader(state['base_dir'])
    plan = validate_plan(_document_json(reader, plan_pin, MAX_PLAN_BYTES))
    exclusion = validate_exclusion(_document_json(reader, exclusion_pin, MAX_PLAN_BYTES))
    _admitted(plan, exclusion)
    reader.finish()
    latest = {}
    for pin in previous:
        value, _, outcomes = _load_record(pin, base_dir=state['base_dir'])
        if value['plan']['sha256'] != _pin(plan_pin['path'], state['base_dir'])['sha256'] or \
                value['exclusion']['sha256'] != _pin(exclusion_pin['path'], state['base_dir'])['sha256']:
            raise ValueError('previous corpus record belongs to another plan or exclusion list')
        latest.update((o['document']['id'], o) for o in outcomes if o['status'] != 'deferred')
    prior = {k: o for k, o in latest.items() if relocate and (o['status'], o['stage']) == ('failed', 'location')}
    done = set(latest) - set(prior)
    out = lc._path(out, root)
    if not out.is_relative_to(root) or out == root:
        raise ValueError('corpus output must be inside its campaign')
    out.mkdir(parents=True, exist_ok=True)
    intervals = {o['origin']: o['min_interval_seconds'] for o in plan['origins']}
    last = {origin: clock() for origin in intervals}

    def pace(origin):
        wait = last[origin] + intervals[origin] - clock()
        if wait > 0:
            sleep(wait)
        last[origin] = clock()

    def emit(directory, document, fields):
        outcome = {'schema_version': 1, 'kind': 'literature-corpus-outcome', 'plan_sha256': digest(plan),
                   'exclusion_sha256': digest(exclusion), 'document': deepcopy(document), **fields}
        _write(directory / 'outcome.json', _schema(outcome, 'outcome'))

    started = sum(1 for path in out.iterdir() if path.is_dir())
    for document in plan['documents']:
        directory = out / document['id']
        if (directory / 'outcome.json').exists() or (document['id'] in done and not directory.exists()):
            continue
        if directory.exists():
            # Partial outputs of an interrupted attempt are retained, never adopted.
            emit(directory, document, {'status': 'deferred', 'stage': 'campaign', 'acquisition': None,
                 'extraction': None, 'product': None, 'unresolved': 0,
                 'reason': 'Interrupted earlier attempt; its partial outputs are retained and a fresh campaign output retries it.'})
            continue
        if started >= plan['limits']['documents_per_campaign']:
            break
        started += 1
        directory.mkdir()
        fields = _process(document, plan, root=root, binding=binding, directory=directory, host=host, pace=pace,
                          prior=prior.get(document['id']))
        emit(directory, document, fields)
        if fields['status'] == 'deferred':
            break
    return record(plan_pin, exclusion_pin, out=out, base_dir=state['base_dir'])


def consume_outcome(pin, *, base_dir):
    """Recompute an outcome's status, stage and receipts; failures stay failures."""
    return _consume_outcome(pin, base_dir=base_dir)[0]


def _consume_outcome(pin, *, base_dir):
    """The outcome and its current located context (None without a product)."""
    reader = lc._Reader(base_dir)
    outcome = _schema(_document_json(reader, pin, lc.MAX_JSON_BYTES), 'outcome')
    reader.finish()
    document, source = outcome['document'], outcome['document']['source']
    acquired = extracted = context = None
    if outcome['acquisition'] is not None:
        acquired = lc.consume_acquisition(outcome['acquisition'], base_dir=base_dir)
        if (source is None or acquired['request_value']['url'] != source['url']
                or acquired['request_value']['format'] != source['format']
                or [t['obligation_id'] for t in acquired['request_value']['tasks']] != [document['id']]):
            raise ValueError('corpus acquisition belongs to another declared original')
    if outcome['extraction'] is not None:
        extracted = lc.consume_pdf(outcome['extraction'], base_dir=base_dir)
        if acquired is None or acquired['status'] != 'acquired' or extracted['source'] != acquired['source_artifact']:
            raise ValueError('corpus extraction belongs to another acquired original')
    if outcome['product'] is not None:
        context = lc.consume(outcome['product'], base_dir=base_dir)['context']
        rows = context['documents']
        if (len(rows) != 1 or rows[0]['id'] != document['id'] or rows[0]['version'] != located_version(document)
                or rows[0]['acquisition'] != outcome['acquisition'] or rows[0]['extraction'] != outcome['extraction']
                or len(context['missing_and_unresolved']) != outcome['unresolved']):
            raise ValueError('corpus located product differs from its outcome')
    if outcome['status'] == 'deferred':
        if (outcome['stage'] != 'campaign' or context is not None or extracted is not None
                or (acquired is not None and acquired['status'] != 'acquired')):
            raise ValueError('a deferred corpus document has no completed later stage')
        return outcome, None
    if source is None:
        expected, reason = ('unsupported', 'acquisition'), document['source_reason']
    elif acquired is None:
        raise ValueError('acquired corpus outcome requires its acquisition receipt')
    elif acquired['status'] == 'failed':
        expected, reason = ('failed', 'acquisition'), acquired['failure']
    elif source['format'] == 'pdf' and extracted is None:
        raise ValueError('PDF corpus outcome requires its extraction receipt')
    elif extracted is not None and extracted['status'] == 'failed':
        expected, reason = ('failed', 'extraction'), extracted['failure']
    elif extracted is not None and extracted['status'] == 'partial':
        expected, reason = ('located-partial', 'complete'), PARTIAL
    else:
        expected, reason = ('located', 'complete'), None
    if context is None:
        expected = ('failed', 'location')
        if not (outcome['reason'] or '').startswith(((reason + ' ') if reason else '') + 'Location: '):
            raise ValueError('corpus location failure must keep its earlier outcome and reason')
    elif outcome['reason'] != reason:
        raise ValueError('corpus outcome reason differs from its receipts')
    if (outcome['status'], outcome['stage']) != expected or (context is None and outcome['unresolved']):
        raise ValueError('corpus outcome status differs from its receipts')
    return outcome, context


def census(plan, outcomes):
    """Failed-source census over a plan and its recorded outcomes."""
    def count(rows, key):
        values = [key(r) for r in rows]
        return {v: values.count(v) for v in sorted(set(values))}
    recorded = {o['document']['id'] for o in outcomes}
    return {'planned': len(plan['documents']), 'recorded': len(outcomes),
            'not_attempted': len([d for d in plan['documents'] if d['id'] not in recorded]),
            'status': count(outcomes, lambda o: o['status']),
            'stage': count([o for o in outcomes if o['stage'] != 'complete'], lambda o: o['stage']),
            'origins': count([o for o in outcomes if o['document']['source']],
                             lambda o: lc._url(o['document']['source']['url'])[1]),
            'unresolved': sum(o['unresolved'] for o in outcomes),
            'redistribution': count(outcomes, lambda o: o['document']['terms']['redistribution']),
            'derivatives': count(outcomes, lambda o: o['document']['terms']['derivatives']),
            'failures': [{'document': o['document']['id'], 'status': o['status'], 'stage': o['stage'], 'reason': o['reason']}
                         for o in outcomes if o['status'] != 'located'],
            'screen': deepcopy(plan['screen'])}


def _record_value(plan_pin, exclusion_pin, *, out, base_dir, visit=None):
    """Recompute a record; ``visit(pin, outcome, context)`` sees each outcome once."""
    reader = lc._Reader(base_dir)
    plan = validate_plan(_document_json(reader, plan_pin, MAX_PLAN_BYTES))
    exclusion = validate_exclusion(_document_json(reader, exclusion_pin, MAX_PLAN_BYTES))
    reader.finish()
    out = lc._path(out, base_dir)
    order = {d['id']: i for i, d in enumerate(plan['documents'])}
    pins, outcomes = [], []
    for directory in sorted((p for p in out.iterdir() if p.is_dir()), key=lambda p: order.get(p.name, len(order))):
        if directory.name not in order:
            raise ValueError('corpus output holds a document outside its plan')
        pin = _pin(directory / 'outcome.json', base_dir)
        outcome, context = _consume_outcome(pin, base_dir=base_dir)
        if (outcome['plan_sha256'] != digest(plan) or outcome['exclusion_sha256'] != digest(exclusion)
                or outcome['document'] != plan['documents'][order[directory.name]]):
            raise ValueError('corpus outcome belongs to another plan or exclusion list')
        pins.append(pin)
        outcomes.append(outcome)
        if visit is not None:
            visit(pin, outcome, context)
    return {'schema_version': 1, 'kind': 'literature-corpus-record', 'plan': _pin(plan_pin['path'], base_dir),
            'exclusion': _pin(exclusion_pin['path'], base_dir), 'outcomes': pins,
            'census': census(plan, outcomes), 'claims': deepcopy(CLAIMS)}


def record(plan_pin, exclusion_pin, *, out, base_dir):
    """Recompute every outcome under ``out`` and write ``record.json`` beside them.

    The outcomes are authoritative; the record is a rewritable summary that
    ``admit_build`` recomputes before use.
    """
    value = _record_value(plan_pin, exclusion_pin, out=out, base_dir=base_dir)
    from . import state_io
    state_io.atomic_json(lc._path(out, base_dir) / 'record.json', value)
    return value


def _relative(pin, base):
    path = lc._path(pin['path'], base)
    return {'path': path.relative_to(lc._path(base, Path.cwd())).as_posix(), 'sha256': pin['sha256'],
            'size': pin['size'], 'receipt_id': None}


def _load_record(record_pin, *, base_dir, visit=None):
    """A record recomputed from its outcomes (each consumed once), with its plan."""
    reader = lc._Reader(base_dir)
    value = _document_json(reader, record_pin, MAX_PLAN_BYTES)
    reader.finish()
    lc._keys(value, ('schema_version', 'kind', 'plan', 'exclusion', 'outcomes', 'census', 'claims'))
    out = lc._path(record_pin['path'], base_dir).parent
    if value['kind'] != 'literature-corpus-record' or value != _record_value(
            value['plan'], value['exclusion'], out=out, base_dir=base_dir, visit=visit):
        raise ValueError('corpus record differs from its recorded outcomes')
    reader = lc._Reader(base_dir)
    plan = validate_plan(_document_json(reader, value['plan'], MAX_PLAN_BYTES))
    reader.finish()
    outcomes = [_schema(json.loads(lc._path(p['path'], base_dir).read_bytes()), 'outcome') for p in value['outcomes']]
    return value, plan, outcomes


def admit_build(record_pins, exclusion_pin, *, base_dir):
    """Products and bibliography rows that may enter an index build.

    Each record is recomputed from its outcomes in one pass; all records share
    one plan and a document has at most one final outcome across them. Records
    are read in the order given, so a relocation's record follows the record
    whose location failure it replaces. The
    supplied build-time exclusion list, which may be newer than the acquisition
    list, screens each document again; each located product's acquisition URL
    must be its declared original, and its located text is scanned for
    identifiers the list locates. A refused product stays in custody but is
    never handed to the builder; refused identities are returned for supervisor
    custody only.
    """
    reader = lc._Reader(base_dir)
    exclusion = validate_exclusion(_document_json(reader, exclusion_pin, MAX_PLAN_BYTES))
    reader.finish()
    if not record_pins:
        raise ValueError('at least one corpus record required')
    final, deferred, superseded = {}, {}, []

    def visit(pin, outcome, context):
        document = outcome['document']
        if outcome['status'] == 'deferred':
            deferred[document['id']] = outcome
            return
        if document['id'] in final:
            earlier = final[document['id']][0]
            # Only a relocation over the same receipts replaces a location failure.
            if ((earlier['status'], earlier['stage']) != ('failed', 'location')
                    or [earlier['acquisition'], earlier['extraction']] != [outcome['acquisition'], outcome['extraction']]):
                raise ValueError('corpus document has more than one final outcome: ' + document['id'])
            superseded.append(document['id'])
        reasons = None
        if context is not None:
            reasons = [{'rule': None, 'check': 'lineage'} for row in context['documents']
                       if row.get('acquisition_outcome') is not None
                       and row['acquisition_outcome']['url'] != document['source']['url']]
            texts = [document['title']] + [u['text'] for u in context['units'] if u['kind'] in ('document', 'page')]
            reasons.extend(_refusals(document, exclusion, texts))
        final[document['id']] = outcome, reasons

    plan = plan_pin = None
    for record_pin in record_pins:
        value, current, _ = _load_record(record_pin, base_dir=base_dir, visit=visit)
        if plan is not None and current != plan:
            raise ValueError('corpus records belong to different plans')
        plan, plan_pin = current, value['plan']
    from . import literature_provider
    products, bibliography, refusals, without = [], [], [], 0
    for document in plan['documents']:
        if document['id'] not in final:
            continue
        outcome, reasons = final[document['id']]
        if outcome['product'] is None:
            without += 1
        elif reasons:
            refusals.append({'document': deepcopy(document), 'reasons': reasons})
        else:
            products.append(deepcopy(outcome['product']))
            lineage = {'pin': _relative(plan_pin, base_dir),
                       'identifiers': {**descriptor(document, exclusion['rules'])['identifiers'], 'document': [document['id']]},
                       'quantities': [], 'classes': sorted(document['labels']), 'kind': 'source'}
            literature_provider._validate(lineage, 'descriptor')
            bibliography.append({'document_id': document['id'], 'version': located_version(document),
                                 'title': document['title'], 'lineage': [lineage]})
    outcomes = [o for o, _ in final.values()] + [o for k, o in deferred.items() if k not in final]
    return {'products': products, 'bibliography': bibliography, 'refusals': refusals,
            'census': {'exclusion_sha256': digest(exclusion), 'admitted': len(products), 'without_product': without,
                       'refused': _count(refusals), 'relocated': sorted(superseded),
                       'acquisition': census(plan, outcomes)},
            'claims': deepcopy(CLAIMS)}


BUILD_RECORD = 'literature-index-build-record'


def _settings_section(settings):
    from . import literature_settings
    section = literature_settings.validate_settings(literature_settings._json_file(settings))
    if section['provider'] == 'off':
        raise ValueError('retrieval settings switch the provider off; nothing is built')
    missing = [k for k in ('index_root', 'source_root', 'qualification', 'cursor_key') if section[k] is None]
    if missing:
        raise ValueError('an index build requires retrieval.' + ', retrieval.'.join(missing))
    return section


def _cursor_key(path):
    from . import broker as core
    path = core.ordinary(path)
    if not path.is_file() or not 32 <= path.stat().st_size <= 4096:
        raise ValueError('cursor key must be an ordinary file of 32 to 4096 bytes')
    return path.read_bytes()


def build_from_records(record_pins, exclusion_pin, *, settings, embedder, reranker_identity, receipt_ids,
                       provider_factory, index_settings=None, evidence=(), batch_size=32):
    """Trusted lineage driver from corpus records to a qualified serving configuration.

    ``settings`` is the installation retrieval settings document (the file
    ``literature_settings.from_settings`` reads); its validated section supplies
    the index, source and qualification locations and any ``excluded_roots``,
    never a worker or run. The current ``exclusion_pin`` re-screens every record
    (``admit_build``); admitted products and the alias-closed bibliography compile
    with the trusted ``receipt_ids`` into the located corpus, failed and
    unsupported documents included as papers with their status. The pinned index
    is built with the exclusion roots and source root, ``provider_factory(snapshot,
    cursor_key=...)`` builds the provider over it, and its ``qualify`` record is
    written where the settings name it, so the settings loader can bind the
    result. The build record (beside the snapshots) keeps the denominator,
    failures, per-rule refusal counts and local-use terms; refused identities are
    returned for supervisor custody only and enter no record, envelope or packet.
    Nothing is acquired, fetched or summarised here.
    """
    from . import literature_build, literature_index, literature_serving, literature_settings, state_io
    section = _settings_section(settings)
    origins = literature_settings.excluded_origins(section)
    base = Path(section['source_root'])
    roots = literature_index.normalize_excluded_roots(section.get('excluded_roots') or None)
    for pin in [*record_pins, exclusion_pin]:
        if roots and literature_index.excluded(pin['path'], roots, base):
            raise ValueError('a corpus record or exclusion list lies under an excluded root')
    admitted = admit_build(record_pins, exclusion_pin, base_dir=base)
    corpus = literature_index.corpus_from_products(admitted['products'], base_dir=base, receipt_ids=receipt_ids,
                                                   bibliography=admitted['bibliography'],
                                                   excluded_roots=[str(r) for r in roots])
    snapshot = literature_build.build_index(section['index_root'], corpus, embedder=embedder,
                                            reranker_identity=reranker_identity, settings=index_settings,
                                            batch_size=batch_size, excluded_roots=[str(r) for r in roots],
                                            source_root=base, excluded_origins=origins)
    manifest = snapshot['manifest']
    pinned = section['index_manifest_sha256']
    if pinned is not None and pinned != manifest['manifest_sha256']:
        raise ValueError('retrieval settings pin another index manifest; update the pin before qualifying this build')
    provider = provider_factory(snapshot, cursor_key=_cursor_key(section['cursor_key']))
    qualification = literature_serving.qualify(provider, snapshot, evidence=list(evidence))
    serving = literature_serving.Serving(provider, snapshot=snapshot, qualification=qualification,
                                         source_root=base, index_root=section['index_root'],
                                         budgets=section['budgets'], ceilings=section['ceilings'],
                                         allowance=section['allowance'], excluded_origins=origins)
    papers = snapshot['corpus']['papers']
    acquisition = admitted['census']['acquisition']
    local = any(k != 'permitted' for k in (*acquisition['derivatives'], *acquisition['redistribution']))
    record_value = {
        'schema_version': 1, 'kind': BUILD_RECORD,
        'index': {'id': manifest['id'], 'manifest_sha256': manifest['manifest_sha256']},
        'records': [deepcopy(p) for p in record_pins], 'exclusion': deepcopy(exclusion_pin),
        'census': {key: deepcopy(value) for key, value in admitted['census'].items()},
        'papers': {'total': len(papers), 'units': len(snapshot['corpus']['units']),
                   'status': {s: sum(p['acquisition_status'] == s for p in papers)
                              for s in sorted({p['acquisition_status'] for p in papers})}},
        'terms': {'index': 'local-only' if local else 'permitted',
                  'basis': ('At least one source permits local use only; the index, its excerpts and derivatives '
                            'are not redistributed.' if local else
                            'Every recorded source licence permits redistribution of derivatives with notices.')},
        'excluded_roots': [str(r) for r in roots],
        'qualification_sha256': qualification['qualification_sha256'], 'claims': deepcopy(CLAIMS)}
    records = Path(section['index_root']) / 'records'
    records.mkdir(exist_ok=True)
    record_path = records / (manifest['manifest_sha256'] + '.json')
    state_io.atomic_json(record_path, record_value)
    state_io.atomic_json(Path(section['qualification']), qualification)
    return {'snapshot': snapshot, 'serving': serving, 'qualification': qualification, 'record': record_value,
            'record_path': str(record_path), 'refusals': deepcopy(admitted['refusals'])}
