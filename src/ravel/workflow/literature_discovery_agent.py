"""Bounded literature discovery over trusted sources: a crawler/selector loop on the existing client.

A typed scope (question, criteria, query variants, seeds, dated universe, limits and source
restrictions) drives a breadth-first crawl. Every source page is one ordinary charged
request through ``research_tools.discover_literature``; cited-by and reference pages use the
provider's citation operators. Candidates are screened by ``source_policy`` before they are
presented, expanded or reported. A criterion selector judges each wave of candidates in one
governed Graph call: this module writes the request and the one-node Graph, the caller runs
it through ``research_cycle.execute_graph`` and ``advance`` admits the recorded reply. The
call's instructions are the protocol of a registered role card. Without a selector the crawl
stays deterministic and every candidate remains unresolved.

The ledger is append-only and hash-chained; the state is a replay of it, so a resumed run
plans the same next step. The completeness report classifies every encountered record as
demonstrated, plausible-needs-validation, unresolved, rejected, outside the universe or
withheld, and lists the dated search universe and every search gap. It is a lower bound:
Discovery metadata is secondary, a selector decision is a candidate disposition and the
primary source, HEPData and implementation follow-ups remain open.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import time
import uuid

from . import literature_context as lc, literature_discovery as discovery, research_cycle as cycle
from . import source_policy, state_io, literature_discovery_sources as sources
# Compatibility exports for existing callers of the original metadata helpers.
from .literature_discovery_sources import (
    _list, _record_identifiers, _query_identifiers, _strings, _field, _years,
    _hepdata_rows, _linked_references, _ARXIV, inspire_record)
from .discovery_http import record_json_url

VERSION = 'inspire-crawler-selector/v1'
SCOPE_KIND = 'literature-discovery-scope'
STEP_KIND = 'literature-discovery-step'
REQUEST_KIND = 'literature-discovery-selection-request'
CHOICE_KIND = 'literature-discovery-selection'
REPORT_KIND = 'literature-discovery-report'
# The registered role card whose protocol instructs the selector call.
ROLE = 'literature-discovery-selector'
NODE = 'select'
INPUT_ID = 'selection-request'
# Source-independent traversal directions.
DIRECTIONS = ('cited_by', 'references')
CRITERION_KINDS = ('required', 'exclusion', 'preferred')
JUDGMENTS = ('met', 'unmet', 'uncertain')
FIELDS = ('title', 'abstract')
CONCEPT_FIELDS = {'title': 't "{}"', 'any': '"{}"'}
ADAPTERS = ('model', 'responses', 'command', 'external', 'anthropic', 'gemini', 'chat_completions')
LIMITS = {'max_variants': 6, 'max_pages': 1, 'page_size': 10, 'max_depth': 1, 'max_expansions': 8,
          'max_requests': 24, 'max_candidates': 200, 'selection_batch': 10, 'max_selection_calls': 6,
          'max_abstract_chars': 3000, 'max_excerpt_chars': 300, 'request_seconds': 20,
          'max_response_bytes': discovery.MAX_RESPONSE_BYTES}
_BOUNDS = {'max_variants': (0, 16), 'max_pages': (1, 4), 'page_size': (1, 25), 'max_depth': (0, 3),
           'max_expansions': (0, 64), 'max_requests': (1, 128), 'max_candidates': (1, 1000),
           'selection_batch': (1, 25), 'max_selection_calls': (0, 32), 'max_abstract_chars': (0, 8000),
           'max_excerpt_chars': (16, 1000), 'request_seconds': (1, 300),
           'max_response_bytes': (1024, discovery.MAX_RESPONSE_BYTES)}
MAX_STEPS = 1024
MIN_EXCERPT = 4
# A record kind the policy may restrict by class; over-withholding is preferred to leakage.
CLASSES = ('literature-metadata', 'public-metadata', 'metadata')
CLAIMS = {**discovery.CLAIMS, 'completeness_verified': False, 'primary_source_read': False}
_ID = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')


class _Refusal(ValueError):
    """A selector reply that cannot be admitted; ``code`` is the recorded reason."""

    def __init__(self, code, detail=None):
        super().__init__(code + (': ' + detail if detail else ''))
        self.code = code


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _keys(value, required, what='record'):
    if type(value) is not dict or set(value) != set(required):
        raise ValueError(what + ' fields must be exactly ' + ', '.join(sorted(required)))


def _text(value, maximum, what):
    if (type(value) is not str or not value.strip() or len(value) > maximum
            or any(ord(c) < 32 and c not in '\t\n' for c in value)):
        raise ValueError('bounded nonblank ' + what + ' required')
    return value


def _ident(value, what):
    if type(value) is not str or len(value) > 32 or not _ID.match(value):
        raise ValueError('lower-case hyphenated ' + what + ' ID required')
    return value


def _unique(rows, what):
    if len(set(rows)) != len(rows):
        raise ValueError('duplicate ' + what)
    return rows


# Typed scope -------------------------------------------------------------------------------

def _limits(value):
    if type(value) is not dict or set(value) - set(LIMITS):
        raise ValueError('limits accept only ' + ', '.join(sorted(LIMITS)))
    result = {**LIMITS, **value}
    for key, (low, high) in _BOUNDS.items():
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ValueError(f'{key} outside {low}..{high}')
    return result


def _universe(value, source):
    _keys(value, ('provider', 'years', 'document_types'), what='universe')
    if value['provider'] != source.id:
        raise ValueError('the configured provider universe is ' + source.id)
    _keys(value['years'], ('from', 'to'), what='universe years')
    years = value['years']
    for bound in years.values():
        if bound is not None and (type(bound) is not int or not 1000 <= bound <= 9999):
            raise ValueError('four-digit year bounds or null required')
    if None not in years.values() and years['from'] > years['to']:
        raise ValueError('empty year window')
    types = value['document_types']
    if types is not None and (type(types) is not list or not 1 <= len(types) <= 16
                              or any(type(t) is not str or not _text(t, 64, 'document type') for t in types)):
        raise ValueError('document types are null or a nonempty list of provider type names')
    if types is not None: _unique(types, 'document type')
    return value


def validate_scope(value, *, source=None):
    """Return a canonical copy of a typed discovery scope with its effective limits."""
    _keys(value, ('schema_version', 'kind', 'id', 'question', 'criteria', 'concepts', 'queries', 'seeds',
                  'universe', 'follow', 'limits', 'source_restrictions', 'tasks'), what='discovery scope')
    if type(value['schema_version']) is not int or value['schema_version'] != 1 or value['kind'] != SCOPE_KIND:
        raise ValueError(SCOPE_KIND + '/v1 required')
    source = sources.source_for(source)
    scope = deepcopy(value)
    _ident(scope['id'], 'scope')
    _text(scope['question'], 2048, 'question')
    criteria = scope['criteria']
    if type(criteria) is not list or not 1 <= len(criteria) <= 8:
        raise ValueError('one to eight criteria required')
    for row in criteria:
        _keys(row, ('id', 'kind', 'statement'), what='criterion')
        _ident(row['id'], 'criterion')
        if row['kind'] not in CRITERION_KINDS:
            raise ValueError('criterion kind is one of ' + ', '.join(CRITERION_KINDS))
        _text(row['statement'], 512, 'criterion statement')
    _unique([r['id'] for r in criteria], 'criterion ID')
    if not any(r['kind'] == 'required' for r in criteria):
        raise ValueError('at least one required criterion defines a demonstrated candidate')
    concepts = scope['concepts']
    if type(concepts) is not list or len(concepts) > 6:
        raise ValueError('at most six concepts')
    for row in concepts:
        _keys(row, ('id', 'field', 'forms'), what='concept')
        _ident(row['id'], 'concept')
        if row['field'] not in CONCEPT_FIELDS:
            raise ValueError('concept field is title or any')
        if type(row['forms']) is not list or not 1 <= len(row['forms']) <= 6:
            raise ValueError('one to six forms per concept')
        for form in row['forms']:
            if '"' in _text(form, 128, 'concept form') or form != form.strip():
                raise ValueError('a concept form is a trimmed literal phrase without quotation marks')
        _unique(row['forms'], 'concept form')
    _unique([r['id'] for r in concepts], 'concept ID')
    queries = scope['queries']
    if type(queries) is not list or len(queries) > 16:
        raise ValueError('at most sixteen explicit queries')
    for row in queries:
        _keys(row, ('id', 'text'), what='query')
        if _ident(row['id'], 'query').startswith('concepts-'):
            raise ValueError('query IDs starting with concepts- are reserved for concept variants')
        _text(row['text'], 2048, 'query text')
    _unique([r['id'] for r in queries], 'query ID')
    seeds = scope['seeds']
    if type(seeds) is not list or len(seeds) > 16 or any(not sources.valid_seed(source, s) for s in seeds):
        raise ValueError('at most sixteen literal provider record IDs as seeds')
    _unique(seeds, 'seed')
    if not (queries or concepts or seeds):
        raise ValueError('a scope needs a query, a concept or a seed')
    _universe(scope['universe'], source)
    follow = scope['follow']
    if type(follow) is not list or any(d not in DIRECTIONS for d in follow):
        raise ValueError('follow lists citation directions: ' + ', '.join(DIRECTIONS))
    _unique(follow, 'direction')
    scope['limits'] = _limits(scope['limits'])
    scope['source_restrictions'] = source_policy.canonical(scope['source_restrictions'])
    tasks = scope['tasks']
    if type(tasks) is not list or not 1 <= len(tasks) <= 8:
        raise ValueError('one to eight scout obligations served by this discovery')
    return scope


def variants(scope):
    """Explicit queries, then one-at-a-time concept form variants, in a fixed order."""
    rows = [{'id': q['id'], 'query': q['text'], 'origin': 'scope'} for q in scope['queries']]
    concepts = scope['concepts']
    if concepts:
        base = [c['forms'][0] for c in concepts]
        choices = [list(base)]
        for i, concept in enumerate(concepts):
            for form in concept['forms'][1:]:
                choices.append([form if j == i else b for j, b in enumerate(base)])
        for n, forms in enumerate(choices):
            text = ' and '.join(CONCEPT_FIELDS[c['field']].format(f) for c, f in zip(concepts, forms))
            rows.append({'id': 'concepts-' + str(n), 'query': text, 'origin': 'concepts'})
    return rows


# Source policy -----------------------------------------------------------------------------

def _normal(namespace, value):
    value = str(value).strip()
    if namespace in ('inspire', 'hepdata'):
        match = re.fullmatch(r'(?:inspire:|recid:|ins)?([1-9][0-9]{0,15})', value, re.I)
        return (namespace, match.group(1)) if match else (namespace, value.casefold())
    if namespace == 'arxiv':
        match = _ARXIV.fullmatch(value)
        return ('arxiv', match.group(1).casefold()) if match else ('arxiv', value.casefold())
    return (namespace, value.casefold())


def _aliases(rows):
    """Each row identifier by its normalized identity, so a descriptor carries the row's own spelling."""
    found = {}
    for row in rows:
        for namespace, values in row.get('identifiers', {}).items():
            for value in values:
                found.setdefault(_normal(namespace, value), set()).add(value)
    return found


def _descriptor(rows, identifiers, classes=CLASSES, quantities=True):
    """A conservative descriptor: documented spellings plus every row spelling of the same identity.

    Every scoped quantity is declared, so a located value-extraction ban withholds the whole record.
    """
    aliases = _aliases(rows)
    result = {}
    for namespace, values in identifiers.items():
        spelled = set()
        for value in values:
            spelled.add(value)
            spelled |= aliases.get(_normal(namespace, value), set())
        if spelled:
            result[namespace] = sorted(spelled)
    named = sorted({q for r in rows for q in r.get('scope', {}).get('quantities', [])}) if quantities else []
    return {'identifiers': result, 'classes': list(classes), 'quantities': named}


def _screen(rows, identifiers, classes=CLASSES):
    return source_policy.read_receipt(rows, _descriptor(rows, identifiers, classes))


def _screen_query(rows, text):
    """A query is not a source: only rows locating an identifier the query names can refuse it."""
    located = [r for r in rows if any(r.get('identifiers', {}).values())]
    if not located:
        return None
    receipt = source_policy.read_receipt(located, _descriptor(located, _query_identifiers(text), (), False))
    return None if receipt['allowed'] else receipt


# Ledger ------------------------------------------------------------------------------------

def _write(path, value):
    """Write canonical bytes once and atomically; an existing file is never replaced."""
    raw = lc._raw(value)
    path = Path(path)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()
    return {'path': str(path), 'sha256': _digest(raw), 'size': len(raw)}


def _steps(out):
    ledger = Path(out) / 'ledger'
    names = sorted(p.name for p in ledger.iterdir() if not p.name.startswith('.'))
    if names != [f'{i:04d}.json' for i in range(len(names))] or not names or len(names) > MAX_STEPS:
        raise ValueError('contiguous discovery ledger required')
    steps, previous = [], None
    for i, name in enumerate(names):
        path = ledger / name
        if path.is_symlink():
            raise ValueError('ordinary discovery ledger files required')
        raw = path.read_bytes()
        step = lc.knowledge._json(raw)
        _keys(step, ('schema_version', 'kind', 'source', 'index', 'previous_sha256', 'recorded_at', 'event'), what='ledger step')
        if (step['schema_version'] != 1 or step['kind'] != STEP_KIND or step['index'] != i
                or step['previous_sha256'] != previous or lc._raw(step) != raw):
            raise ValueError('discovery ledger chain broken at step ' + str(i))
        if step['source'] != step['event']['source'] or (steps and step['source'] != steps[0]['source']):
            raise ValueError('discovery source differs between ledger steps')
        steps.append(step); previous = _digest(raw)
    return steps, previous


def _append(out, steps, head, event):
    source = steps[0]['source'] if steps else event['source']
    event = {**event, 'source': source}
    step = {'schema_version': 1, 'kind': STEP_KIND, 'source': source, 'index': len(steps), 'previous_sha256': head,
            'recorded_at': _now(), 'event': event}
    pin = _write(Path(out) / 'ledger' / f'{len(steps):04d}.json', step)
    return step, pin['sha256']


# Selector call -----------------------------------------------------------------------------

def _card_instructions(role, roles=None):
    """The registered card's protocol, the only instruction source; ``roles`` overrides the registry document."""
    from . import role_registry
    try:
        card = role_registry.load(role, document=roles)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise _Refusal('role_card_unavailable', str(exc)) from None
    protocol = card.get('protocol')
    if type(protocol) is not list or not protocol or any(type(p) is not str or not p.strip() for p in protocol):
        raise _Refusal('role_card_unavailable', 'a nonempty protocol is required: ' + str(role))
    return ' '.join(protocol)


def _selector(value):
    if value is None:
        return None
    _keys(value, ('model', 'reasoning_effort', 'adapter', 'max_output_tokens', 'max_wall_seconds'), what='selector')
    if any(type(value[k]) is not str or not value[k].strip() for k in ('model', 'reasoning_effort')):
        raise ValueError('explicit actual selector model and effort required')
    if value['adapter'] not in ADAPTERS:
        raise ValueError('existing configured model transport required')
    if type(value['max_output_tokens']) is not int or not 256 <= value['max_output_tokens'] <= 16384:
        raise ValueError('selector output token bound outside 256..16384')
    if type(value['max_wall_seconds']) is not int or not 30 <= value['max_wall_seconds'] <= 600:
        raise ValueError('selector wall bound outside 30..600 seconds (the role card stop)')
    return deepcopy(value)


def _presented(candidate, limits):
    candidate = candidate if 'title' in candidate else inspire_record(candidate)
    title = candidate['title']
    abstract = candidate['abstract']
    cut = limits['max_abstract_chars']
    types = candidate.get('document_type')
    return {'key': candidate['recid'], 'title': title,
            'abstract': None if abstract is None or not cut else abstract[:cut],
            'abstract_truncated': abstract is not None and len(abstract) > cut,
            'years': candidate['years'], 'document_type': list(types) if _strings(types) else None,
            'field_pointers': candidate.get('field_pointers', {'title': '/title', 'abstract': '/abstract'})}


def selection_request(scope, candidates, *, role=ROLE, roles=None):
    """The complete input of one selector call: question, criteria and presented metadata only."""
    _card_instructions(role, roles)
    return {'schema_version': 1, 'kind': REQUEST_KIND, 'scope_sha256': _digest(lc._raw(scope)), 'role': role,
            'question': scope['question'], 'criteria': deepcopy(scope['criteria']),
            'limits': {'max_excerpt_chars': scope['limits']['max_excerpt_chars']},
            'candidates': [_presented(c, scope['limits']) for c in candidates]}


def graph_spec(request_pin, request, selector, *, graph_id, roles=None):
    """One bounded registered-role call, one attempt and a closed criterion-decision schema; no reworks.

    A governed seat may use the original role card's broker tools.
    """
    from . import agent_graph
    instructions = _card_instructions(request['role'], roles)
    keys = [c['key'] for c in request['candidates']]
    criteria = [c['id'] for c in request['criteria']]
    judgment = {'type': 'object', 'additionalProperties': False,
                'required': ['criterion', 'judgment', 'field', 'excerpt'], 'properties': {
                    'criterion': {'type': 'string', 'enum': criteria},
                    'judgment': {'type': 'string', 'enum': list(JUDGMENTS)},
                    'field': {'type': ['string', 'null'], 'enum': [*FIELDS, None]},
                    'excerpt': {'type': ['string', 'null'], 'maxLength': request['limits']['max_excerpt_chars']}}}
    schema = {'type': 'object', 'additionalProperties': False,
              'required': ['kind', 'request_sha256', 'decisions'], 'properties': {
                  'kind': {'type': 'string', 'const': CHOICE_KIND},
                  'request_sha256': {'type': 'string', 'const': request_pin['sha256']},
                  'decisions': {'type': 'array', 'maxItems': len(keys), 'items': {
                      'type': 'object', 'additionalProperties': False, 'required': ['candidate', 'judgments'],
                      'properties': {'candidate': {'type': 'string', 'enum': keys},
                                     'judgments': {'type': 'array', 'maxItems': len(criteria), 'items': judgment}}}}}}
    spec = {'schema_version': 1, 'graph_id': graph_id,
            'budget': {'max_nodes': 1, 'max_calls': 1, 'max_output_tokens': selector['max_output_tokens'],
                       'max_wall_seconds': selector['max_wall_seconds'], 'max_reworks': 0},
            'nodes': [{'id': NODE, 'kind': 'model', 'role': 'proposer', 'registry_role': ROLE, 'depends_on': [],
                       'inputs': [{'id': INPUT_ID, 'path': request_pin['path'], 'sha256': request_pin['sha256']}],
                       'packet': None, 'action': selector['adapter'], 'max_attempts': 1,
                       'parameters': {'model': selector['model'], 'reasoning_effort': selector['reasoning_effort'],
                                      'max_output_tokens': selector['max_output_tokens'], 'output_schema': schema,
                                      'instructions': instructions}}]}
    agent_graph.validate(spec)
    return spec


def _locate(presented, field, excerpt, maximum):
    if field is None or excerpt is None:
        return None, 'no_excerpt'
    text = presented.get(field)
    if type(excerpt) is not str or len(excerpt.strip()) < MIN_EXCERPT or len(excerpt) > maximum:
        return None, 'excerpt_out_of_bounds'
    if type(text) is not str:
        return None, 'field_absent'
    start = text.find(excerpt)
    if start < 0:
        return None, 'excerpt_not_in_field'
    pointer = presented.get('field_pointers', {
        'title': '/metadata/titles/0/title', 'abstract': '/metadata/abstracts/0/value'})[field]
    return {'field': field, 'pointer': pointer, 'start': start, 'end': start + len(excerpt), 'excerpt': excerpt}, None


def admit(root, request_pin, graph_root, selector, *, roles=None):
    """Admit the recorded reply of the exact charged selector Graph, or refuse it with a reason code."""
    from . import agent_graph
    sha = request_pin.get('sha256') if type(request_pin) is dict else None
    sha = sha if type(sha) is str and _SHA.match(sha) else None
    try:
        path = Path(request_pin['path'])
        raw = path.read_bytes()
        if _digest(raw) != request_pin['sha256'] or len(raw) != request_pin['size']:
            raise _Refusal('request_pin_mismatch')
        document = lc.knowledge._json(raw)
        graph_root = cycle._ordinary(graph_root)
        try:
            spec, _ = agent_graph._load(graph_root)
        except (ValueError, KeyError, TypeError, OSError):
            raise _Refusal('graph_result_unavailable') from None
        try:
            expected = graph_spec(request_pin, document, selector, graph_id=spec['graph_id'], roles=roles)
        except _Refusal:
            raise
        except (ValueError, KeyError, TypeError):
            raise _Refusal('graph_spec_mismatch') from None
        _, campaign = cycle._load(root)
        # The campaign adds its own parent assignment to every Graph it executes.
        inherited = campaign['contract'].get('goal_binding')
        if spec.get('goal_binding', inherited) != inherited or {k: v for k, v in spec.items() if k != 'goal_binding'} != expected:
            raise _Refusal('graph_spec_mismatch')
        if ('graph:' + str(graph_root) not in {r['id'] for r in campaign['resource_ledger']}
                or str(graph_root) not in {g['root'] for g in campaign['graphs']}):
            raise _Refusal('not_charged')
        try:
            origin = cycle._graph_result(graph_root, NODE)
        except (ValueError, KeyError, TypeError, OSError):
            raise _Refusal('graph_result_unavailable') from None
        value = origin['value']
        if origin['node_kind'] != 'model' or type(value) is not dict or value.get('kind') != 'model_result':
            raise _Refusal('not_a_model_result')
        choice = value.get('value')
        try:
            _keys(choice, ('kind', 'request_sha256', 'decisions'), what='selection')
        except ValueError:
            raise _Refusal('invalid_choice') from None
        if choice['kind'] != CHOICE_KIND or choice['request_sha256'] != request_pin['sha256']:
            raise _Refusal('other_request')
        presented = {c['key']: c for c in document['candidates']}
        criteria = {c['id'] for c in document['criteria']}
        maximum = document['limits']['max_excerpt_chars']
        decisions = {}
        if type(choice['decisions']) is not list:
            raise _Refusal('invalid_choice')
        for row in choice['decisions']:
            if type(row) is not dict or set(row) != {'candidate', 'judgments'} or row['candidate'] not in presented \
                    or row['candidate'] in decisions or type(row['judgments']) is not list:
                raise _Refusal('invalid_choice')
            judged = {}
            for item in row['judgments']:
                if (type(item) is not dict or set(item) != {'criterion', 'judgment', 'field', 'excerpt'}
                        or item['criterion'] not in criteria or item['criterion'] in judged
                        or item['judgment'] not in JUDGMENTS or item['field'] not in (*FIELDS, None)
                        or (item['excerpt'] is not None and type(item['excerpt']) is not str)):
                    raise _Refusal('invalid_choice')
                located, failure = _locate(presented[row['candidate']], item['field'], item['excerpt'], maximum)
                judged[item['criterion']] = {'judgment': item['judgment'], 'located': located,
                                             'location_failure': failure if item['judgment'] == 'met' else None}
            decisions[row['candidate']] = judged
    except _Refusal as refusal:
        return {'status': 'refused', 'reason': refusal.code, 'request_sha256': sha}
    except OSError:
        return {'status': 'refused', 'reason': 'request_unavailable', 'request_sha256': sha}
    except (ValueError, KeyError, TypeError):
        return {'status': 'refused', 'reason': 'invalid_request', 'request_sha256': sha}
    return {'status': 'admitted', 'request_sha256': request_pin['sha256'], 'receipt': deepcopy(origin['receipt']),
            'binding_sha256': origin['binding_sha256'], 'decisions': decisions}


def classify(judgments, criteria):
    """Demonstrated, plausible-needs-validation or rejected, with every reason; preferred criteria only count."""
    reasons, located, preferred = [], [], 0
    rank = {'demonstrated': 0, 'plausible': 1, 'rejected': 2}
    status = 'demonstrated'

    def worse(new, reason):
        nonlocal status
        reasons.append(reason)
        if rank[new] > rank[status]:
            status = new
    for criterion in criteria:
        row, cid = judgments.get(criterion['id']), criterion['id']
        if criterion['kind'] == 'preferred':
            if row is not None and row['judgment'] == 'met' and row['located'] is not None:
                preferred += 1; located.append({'criterion': cid, **row['located']})
            continue
        if row is None:
            worse('plausible', 'not_judged:' + cid); continue
        if criterion['kind'] == 'required':
            if row['judgment'] == 'unmet': worse('rejected', 'required_unmet:' + cid)
            elif row['judgment'] == 'uncertain': worse('plausible', 'required_uncertain:' + cid)
            elif row['located'] is None: worse('plausible', 'required_unlocated:' + cid + ':' + row['location_failure'])
            else: located.append({'criterion': cid, **row['located']})
        elif row['judgment'] == 'met':
            if row['located'] is None: worse('plausible', 'exclusion_unlocated:' + cid + ':' + row['location_failure'])
            else:
                worse('rejected', 'exclusion_applies:' + cid); located.append({'criterion': cid, **row['located']})
        elif row['judgment'] == 'uncertain':
            worse('plausible', 'exclusion_uncertain:' + cid)
    return {'status': status, 'reasons': reasons, 'located': located, 'preferred_met': preferred}


# Metadata ----------------------------------------------------------------------------------

def _outside(metadata, universe):
    """The universe filter reason, or None; unknown years or types stay inside and are noted."""
    record = metadata if 'years' in metadata else inspire_record({'recid': '1', 'metadata': metadata})
    notes = []
    window = universe['years']
    if window['from'] is not None or window['to'] is not None:
        years = record['years']
        low, high = window['from'] or 1000, window['to'] or 9999
        if not years: notes.append('year_unknown')
        elif not any(low <= y <= high for y in years): return 'outside_years', notes
    if universe['document_types'] is not None:
        types = record.get('document_type')
        if not _strings(types) or not types: notes.append('document_type_unknown')
        elif not set(types) & set(universe['document_types']): return 'outside_document_types', notes
    return None, notes


# Replay ------------------------------------------------------------------------------------

class _State:
    """The crawl state as a pure replay of the ledger."""

    def __init__(self, root, out, steps, roles, source=None):
        self.root, self.out, self.roles = root, Path(out), roles
        _, campaign = cycle._load(root)
        self.base = Path(campaign['base_dir'])
        self.binding = {'root': str(cycle._ordinary(root)), 'contract_sha256': cycle.ce.digest(campaign['contract'])}
        begin = steps[0]['event']
        if begin.get('type') != 'start':
            raise ValueError('discovery ledger must begin with its start')
        self.source = sources.source_for(begin['source'])
        if source is not None and sources.source_for(source).id != self.source.id:
            raise ValueError('discovery source differs from its start')
        if begin['capabilities'] != self.source.capabilities:
            raise ValueError('discovery source capabilities differ from its start')
        reader = lc._Reader(self.base)
        _, scope = reader.document(begin['scope'])
        self.scope = validate_scope(scope, source=self.source.id)
        if scope != self.scope or begin['cycle_binding'] != self.binding:
            raise ValueError('discovery scope or campaign assignment differs from its start')
        self.start = begin
        self.selector = _selector(begin['selector'])
        self.graph = None
        if begin['graph'] is not None:
            from .literature_relations import LiteratureGraph
            _, snapshot = reader.document(begin['graph'])
            self.graph = LiteratureGraph(snapshot, expected_sha256=begin['graph_sha256'])
        self.rows = self.scope['source_restrictions']
        self.limits = self.scope['limits']
        self.variants = variants(self.scope)
        self.candidates = {}       # recid -> candidate, in first-seen order
        self.overflow = {}         # recid -> request key, beyond the candidate cap
        self.withheld = {}         # recid -> violated rule digests; identities are never reported
        self.requests = {}         # request key -> executed outcome
        self.decisions = {}        # recid -> admitted judgments
        self.attempted = {}        # recid -> why a selection attempt gave no decision
        self.selections = []
        self.pending = None
        self.stopped = None if self.selector and self.limits['max_selection_calls'] else (
            'selector_disabled' if not self.selector else 'selection_budget_zero')
        self.halted = None
        self.complete = None
        self._query_receipts = {}
        self.seed_screen = {s: _screen(self.rows, sources.seed_identifiers(self.source, s))
                            for s in self.scope['seeds']}
        for step in steps[1:]:
            self._apply(step)

    def _apply(self, step):
        event = step['event']
        if step['source'] != self.source.id or event['source'] != self.source.id:
            raise ValueError('discovery source differs between ledger steps')
        kind = event.get('type')
        if self.complete is not None or (self.halted is not None and kind != 'complete'):
            raise ValueError('discovery ledger continues after its end')
        if kind == 'request':
            self._request(event)
        elif kind == 'selection_request':
            if self.pending is not None or event['batch'] != self.next_batch():
                raise ValueError('ledger selection differs from the deterministic plan')
            self.pending = {'index': step['index'], **deepcopy(event)}
        elif kind == 'selection':
            self._selection(event)
        elif kind == 'halt':
            self.halted = event['reason']
        elif kind == 'complete':
            self.complete = event['report']
        else:
            raise ValueError('unknown discovery ledger event')

    def _request(self, event):
        planned = self.plan_next()
        if planned is None or self.next_batch() or self.pending is not None or any(
                planned[k] != event[k] for k in ('key', 'query', 'page')):
            raise ValueError('ledger request differs from the deterministic plan')
        outcome = {'source': self.source.id, 'key': event['key'], 'purpose': deepcopy(planned['purpose']), 'query': event['query'],
                   'page': event['page'], 'size': planned['size'], 'issued_at': event['issued_at'],
                   'returned_at': event['returned_at'], 'product': deepcopy(event['product']),
                   'status': 'failed', 'reason': event['failure'], 'remote_total': None,
                   'remote_total_relation': 'unknown', 'hits': [], 'next': None}
        if event['product'] is not None:
            result = sources.consume_page(self.source, event['product'], base_dir=self.base, row=planned,
                                          expected_request=_request_document(self, planned, 0))
            if result['operation'] != 'query' or result['source'] != self.source.id or result['request_url'] != self.source.query_url(planned):
                raise ValueError('discovery product differs from its planned query page')
            outcome.update(status=result['status'], remote_total=result['remote_total'],
                           remote_total_relation=result['remote_total_relation'], reason=result['reason'],
                           hits=[h['recid'] for h in result['records']], next=result['next'])
            for rank, hit in enumerate(result['records']):
                self._hit(hit, planned, rank, event['product'])
        self.requests[event['key']] = outcome

    def _hit(self, hit, planned, rank, product):
        recid = hit['recid']
        known = self.candidates.get(recid)
        if known is not None:
            known['origins'].append({'key': planned['key'], 'rank': rank})
            if hit.get('updated') not in known['epochs']: known['epochs'].append(hit.get('updated'))
            return
        if recid in self.overflow or recid in self.withheld:
            return
        receipt = _screen(self.rows, self.source.identifiers(hit))
        if not receipt['allowed']:
            self.withheld[recid] = [_digest(lc._raw(r)) for r in receipt['rules']]
            return
        if len(self.candidates) >= self.limits['max_candidates']:
            self.overflow[recid] = planned['key']; return
        outside, notes = _outside(hit, self.scope['universe'])
        self.candidates[recid] = {**deepcopy(hit), 'source': self.source.id, 'updated': hit.get('updated'),
                                  'epochs': [hit.get('updated')], 'depth': planned['depth'],
                                  'origins': [{'key': planned['key'], 'rank': rank}],
                                  'first': {'product': deepcopy(product), 'key': planned['key'], 'rank': rank},
                                  'seed': recid in self.scope['seeds'], 'outside': outside, 'notes': notes}

    def _selection(self, event):
        if self.pending is None or event['request'] != self.pending['request']:
            raise ValueError('selection outcome without its pending request')
        batch, outcome = self.pending['batch'], deepcopy(event['outcome'])
        if outcome['status'] == 'admitted':
            current = admit(self.root, event['request'], self.pending['graph_root'], self.selector, roles=self.roles)
            if current != outcome:
                raise ValueError('admitted selection differs from its recorded charged reply')
            for recid in batch:
                if recid in outcome['decisions']: self.decisions[recid] = outcome['decisions'][recid]
                else: self.attempted[recid] = 'selector_gave_no_decision'
        else:
            reason = 'selection_' + outcome['status'] + ':' + outcome['reason']
            for recid in batch: self.attempted[recid] = reason
            self.stopped = 'stopped_after_' + reason
        self.selections.append({'source': self.source.id, 'index': self.pending['index'], 'batch': list(batch), 'request': event['request'],
                                'graph_root': self.pending['graph_root'], 'status': outcome['status'],
                                'reason': outcome.get('reason')})
        self.pending = None

    # Classification and planning.
    def status_of(self, recid):
        c = self.candidates[recid]
        if c['outside']: return 'outside_universe', [c['outside']]
        if recid in self.decisions:
            verdict = classify(self.decisions[recid], self.scope['criteria'])
            return verdict['status'], verdict['reasons']
        if recid in self.attempted: return 'unresolved', [self.attempted[recid]]
        if self.stopped is not None: return 'unresolved', [self.stopped]
        if len(self.selections) >= self.limits['max_selection_calls']: return 'unresolved', ['selection_budget']
        return 'unresolved', ['halted_before_selection' if self.halted else 'not_selected']

    def eligible(self, recid):
        """Expansion follows seeds and every candidate judged demonstrated or plausible; unjudged ones are gaps."""
        return self.candidates[recid]['seed'] or self.status_of(recid)[0] in ('demonstrated', 'plausible')

    def _selectable(self):
        return [r for r, c in self.candidates.items() if not c['outside'] and r not in self.decisions
                and r not in self.attempted]

    def refused(self, row):
        """The pre-access refusal of a variant naming a restricted source, or None."""
        if row['purpose']['kind'] == 'expansion' and not self.source.capabilities['citations']:
            return {'allowed': False, 'reason': 'source_lacks_citations', 'rules': []}
        if row['purpose']['kind'] != 'variant': return None
        if row['query'] not in self._query_receipts:
            self._query_receipts[row['query']] = _screen_query(self.rows, row['query'])
        return self._query_receipts[row['query']]

    def planned(self):
        """Every request the scope implies, in execution order, as far as the state allows."""
        size, rows = self.limits['page_size'], []
        allowed = [s for s in self.scope['seeds'] if self.seed_screen[s]['allowed']]
        for n in range(0, len(allowed), size):
            chunk = allowed[n:n + size]
            rows.append({'key': f'seed:{n // size}', 'query': ' or '.join(chunk),
                         'page': 1, 'size': len(chunk), 'depth': 0, 'purpose': {'kind': 'seed', 'seeds': chunk}})
            rows[-1]['query'] = sources.planned_query(self.source, rows[-1])
        for variant in self.variants[:self.limits['max_variants']]:
            self._pages(rows, f'variant:{variant["id"]}', variant['query'], 0,
                        {'kind': 'variant', 'variant': variant['id']})
        for depth in range(1, self.limits['max_depth'] + 1):
            if not self._settled(rows, depth - 1): break
            for recid, c in self.candidates.items():
                if c['depth'] != depth - 1 or not self.eligible(recid): continue
                for direction in self.scope['follow']:
                    self._pages(rows, f'expand:{direction}:{recid}', recid, depth,
                                {'kind': 'expansion', 'direction': direction, 'node': recid})
        return rows

    def _pages(self, rows, prefix, query, depth, purpose):
        size = self.limits['page_size']
        for page in range(1, self.limits['max_pages'] + 1):
            rows.append({'key': f'{prefix}:p{page}', 'query': query, 'page': page, 'size': size, 'depth': depth,
                         'purpose': deepcopy(purpose)})
            rows[-1]['query'] = sources.planned_query(self.source, rows[-1])
            if page > 1:
                rows[-1]['cursor'] = cursor
            done = self.requests.get(rows[-1]['key'])
            # A further page follows only a complete page that the provider says has successors.
            if not (done and done['status'] == 'discovered' and len(done['hits']) == size
                    and done['next'] is not None):
                break
            cursor = done['next']

    def executable(self, rows):
        """Executed keys, then planned keys in order within the remaining request and expansion budgets."""
        keys = {r['key'] for r in rows if r['key'] in self.requests}
        total = len(keys)
        expansions = sum(1 for r in rows if r['key'] in keys and r['purpose']['kind'] == 'expansion')
        for row in rows:
            if row['key'] in keys or self.refused(row) is not None: continue
            expansion = row['purpose']['kind'] == 'expansion'
            if total >= self.limits['max_requests'] or (expansion and expansions >= self.limits['max_expansions']):
                continue
            total += 1; expansions += expansion; keys.add(row['key'])
        return keys

    def _settled(self, rows, depth):
        executable = self.executable(rows)
        if any(r['depth'] == depth and r['key'] not in self.requests and r['key'] in executable for r in rows):
            return False
        return not (self._selection_open() and any(self.candidates[r]['depth'] <= depth for r in self._selectable()))

    def _selection_open(self):
        return self.stopped is None and len(self.selections) < self.limits['max_selection_calls']

    def plan_next(self):
        rows = self.planned()
        executable = self.executable(rows)
        return next((r for r in rows if r['key'] not in self.requests and r['key'] in executable), None)

    def next_batch(self):
        """The next wave's selectable candidates once every request that could add to the wave has run."""
        if not self._selection_open() or self.pending is not None:
            return []
        rows = self.planned()
        executable = self.executable(rows)
        waiting = [r['depth'] for r in rows if r['key'] not in self.requests and r['key'] in executable]
        frontier = min(waiting) if waiting else None
        ready = [r for r in self._selectable() if frontier is None or self.candidates[r]['depth'] < frontier]
        return ready[:self.limits['selection_batch']]


def _request_url(row):
    """Compatibility spelling of the default source's request law."""
    return sources.source_for().query_url(row)


# Public steps ------------------------------------------------------------------------------

def start(root, scope_pin, out, *, source=None, selector=None, graph=None, roles=None):
    """Validate the scope, bind it to the campaign and begin the ledger in a fresh ``out`` in the campaign.

    ``selector`` is ``None`` (deterministic crawl) or the explicit model, effort, adapter and bounds of
    the criterion selector; ``graph`` is an optional ``literature_relations.LiteratureGraph`` for
    implementation and published-artifact joins.
    """
    from . import research_tools as tools
    _, campaign = cycle._load(root)
    _, value = lc._Reader(campaign['base_dir']).document(scope_pin)
    source = sources.source_for(source)
    scope = validate_scope(value, source=source.id)
    selector = _selector(selector)
    if selector is not None:
        _card_instructions(ROLE, roles)
    out = tools._destination(root, out); out.mkdir()
    (out / 'ledger').mkdir()
    canonical = _write(out / 'scope.json', scope)
    graph_pin = graph_sha = None
    if graph is not None:
        snapshot = graph.to_dict()
        graph_pin, graph_sha = _write(out / 'graph.json', snapshot), snapshot['graph_sha256']
    _append(out, [], None, {
        'type': 'start', 'source': source.id, 'capabilities': deepcopy(source.capabilities), 'scope': canonical, 'supplied_scope': deepcopy(scope_pin), 'selector': selector,
        'graph': graph_pin, 'graph_sha256': graph_sha,
        'cycle_binding': {'root': str(cycle._ordinary(root)), 'contract_sha256': cycle.ce.digest(campaign['contract'])},
        'agent_version': VERSION, 'client_version': discovery.VERSION})
    return status(root, out, roles=roles)


def _request_document(state, row, index):
    return sources.request_document(state.source, state.binding, state.scope, row, index)


def _owned(folder, name, document):
    """The request file at the next ledger position: written once, or the identical earlier write."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    if path.exists():
        pin = cycle._pin(path)
        if pin['sha256'] != _digest(lc._raw(document)):
            raise ValueError('an unrecorded foreign request occupies the next ledger position')
        return pin
    return _write(path, document)


def _issue(state, steps, head, row, host):
    """One planned page through the existing charged client; an interrupted earlier attempt is never repeated."""
    from . import research_tools as tools
    index = len(steps)
    folder = state.out / 'requests' / f'{index:04d}'
    run = folder / 'run'
    event = {'type': 'request', 'key': row['key'], 'query': row['query'], 'page': row['page'], 'request': None,
             'product': None, 'failure': None, 'issued_at': _now(), 'returned_at': None, 'recovered': False}
    event['request'] = _owned(folder, 'request.json', _request_document(state, row, index))
    failure = None
    if run.exists():
        event['recovered'] = True
        try:
            product = cycle._pin(run / 'metadata' / 'product.json')
            sources.consume_page(state.source, product, base_dir=state.base, row=row,
                                 expected_request=_request_document(state, row, index))
            event['product'] = product
        except (ValueError, OSError, KeyError, TypeError) as exc:
            event['failure'] = 'interrupted before a complete product: ' + (str(exc) or type(exc).__name__)[:300]
    else:
        try:
            returned = sources.execute_page(state.source, state.root, event['request'], run, host, row,
                                            max_wall_seconds=state.limits['request_seconds'])
            event['product'] = deepcopy(returned['product'])
        except (ValueError, OSError, RuntimeError) as exc:
            failure = event['failure'] = (type(exc).__name__ + ': ' + str(exc))[:500]
    event['returned_at'] = _now()
    step, head = _append(state.out, steps, head, event)
    return step, head, failure


def _awaiting(state):
    pending = state.pending
    _, document = lc._Reader(state.base).document(pending['request'])
    spec = graph_spec(pending['request'], document, state.selector,
                      graph_id=f'{state.scope["id"]}-select-{pending["index"]:04d}', roles=state.roles)
    return {'source': state.source.id, 'status': 'select', 'index': pending['index'], 'request': deepcopy(pending['request']),
            'graph_root': pending['graph_root'], 'graph_spec': spec, 'batch': list(pending['batch'])}


def advance(root, out, host, *, selection=None, decline=None, roles=None):
    """Run planned work until a selector call is needed or the crawl ends.

    ``selection`` is the pending call's ``graph_root`` after the caller executed its ``graph_spec``
    through ``research_cycle.execute_graph``; ``decline`` instead records why it was not run, which
    stops selection. Returns ``{'status': 'select', 'graph_spec', 'graph_root', ...}`` or, when the
    crawl completes or halts, ``{'status', 'report'}``. A charged request that raises halts the
    crawl with a qualified report; nothing is retried.
    """
    out = cycle._ordinary(out)
    with state_io.file_lock(out / 'advance.lock', blocking=False):
        return _advance(root, out, host, selection, decline, roles)


def _advance(root, out, host, selection, decline, roles):
    steps, head = _steps(out)
    state = _State(root, out, steps, roles)
    if state.complete is not None:
        if selection is not None or decline is not None:
            raise ValueError('discovery already ended')
        return {'source': state.source.id, 'status': 'halted' if state.halted else 'complete', 'report': deepcopy(state.complete)}
    if state.pending is not None and (selection is not None or decline is not None):
        if decline is not None:
            outcome = {'status': 'declined', 'reason': _text(decline, 512, 'decline reason'),
                       'request_sha256': state.pending['request']['sha256']}
        elif str(cycle._ordinary(selection)) != state.pending['graph_root']:
            raise ValueError('the selection must be the pending Graph at its declared root')
        elif not Path(selection).is_dir():
            raise ValueError('the pending selector Graph was never created; execute its graph_spec or decline')
        else:
            outcome = admit(root, state.pending['request'], selection, state.selector, roles=roles)
        step, head = _append(out, steps, head, {'type': 'selection', 'request': deepcopy(state.pending['request']),
                                                'outcome': outcome})
        steps.append(step); state._apply(step)
    elif selection is not None or decline is not None:
        raise ValueError('no selector call is pending')
    while state.halted is None:
        if state.pending is not None:
            return _awaiting(state)
        batch = state.next_batch()
        if batch:
            index = len(steps)
            document = selection_request(state.scope, [state.candidates[r] for r in batch], roles=roles)
            folder = out / 'selections' / f'{index:04d}'
            pin = _owned(folder, 'request.json', document)
            step, head = _append(out, steps, head, {'type': 'selection_request', 'batch': batch, 'request': pin,
                                                    'graph_root': str(folder / 'graph')})
            steps.append(step); state._apply(step)
            continue
        row = state.plan_next()
        if row is None:
            break
        step, head, failure = _issue(state, steps, head, row, host)
        steps.append(step); state._apply(step)
        if failure is not None:
            step, head = _append(out, steps, head, {'type': 'halt', 'reason': 'charged request failed: ' + failure})
            steps.append(step); state._apply(step)
    document = report(root, out, roles=roles, _state=state)
    pin = _owned(out, 'report.json', document)
    _append(out, steps, head, {'type': 'complete', 'report': pin})
    return {'source': state.source.id, 'status': document['status'], 'report': pin}


def status(root, out, *, roles=None):
    """A read-only replay summary; no request or call is made."""
    out = cycle._ordinary(out)
    state = _State(root, out, _steps(out)[0], roles)
    counts = {}
    for recid in state.candidates:
        name = state.status_of(recid)[0]
        counts[name] = counts.get(name, 0) + 1
    return {'source': state.source.id, 'status': 'complete' if state.complete else 'halted' if state.halted else
            'select' if state.pending else 'ready', 'requests': len(state.requests),
            'selection_calls': len(state.selections), 'candidates': len(state.candidates),
            'withheld': len(state.withheld), 'counts': counts, 'halt_reason': state.halted}


# Report ------------------------------------------------------------------------------------

DEFINITIONS = {
    'demonstrated': 'Every required criterion judged met by the admitted charged selector reply, each with an '
                    'exact excerpt located in the presented title or abstract, and no located exclusion.',
    'plausible_needs_validation': 'No required criterion judged unmet and no located exclusion, but at least one '
                                  'judgment is uncertain, missing or unlocated.',
    'unresolved': 'No admitted selector decision, a seed the provider did not return, or a record beyond the '
                  'candidate cap.',
    'rejected': 'A required criterion judged unmet, or an exclusion judged met with a located excerpt.',
    'outside_universe': 'Outside the declared year window or document types by provider metadata.',
    'withheld': 'Refused by the source restrictions before presentation, expansion or reporting; only per-rule '
                'counts are kept.'}


def _entry(state, recid, status, reasons):
    c = state.candidates[recid]
    entry = {'source': state.source.id, 'recid': recid, 'title': c['title'], 'years': c['years'],
             'depth': c['depth'], 'seed': c['seed'], 'origins': deepcopy(c['origins']), 'status': status,
             'reasons': list(reasons), 'notes': list(c['notes']), 'record_updated': c['updated'],
             'record_changed_during_search': len(c['epochs']) > 1, 'lookup_url': sources.record_url(state.source, recid, c),
             'first_seen': deepcopy(c['first'])}
    if recid in state.decisions:
        verdict = classify(state.decisions[recid], state.scope['criteria'])
        entry.update(located=verdict['located'], preferred_met=verdict['preferred_met'])
    return entry


def _graph_denials(rows):
    from .literature_relations import identifier
    denied = set()
    for row in rows:
        for namespace, values in row.get('identifiers', {}).items():
            for value in values:
                forms = (value, value.casefold())
                if namespace == 'arxiv':  # the unversioned publication node closes over its versions
                    forms += tuple(re.sub(r'v[1-9][0-9]*\Z', '', f) for f in forms)
                for spelled in forms:
                    try:
                        if namespace in ('inspire', 'arxiv', 'analysis'): denied.add(identifier(namespace, spelled))
                        elif re.fullmatch(r'ins[0-9]+', spelled, re.I): denied.add(identifier('inspire', spelled.lower()))
                    except ValueError:
                        pass
    return frozenset(denied)


def _follow_ups(state, recid):
    """HEPData and implementation joins as candidates for a next governed step, never as findings."""
    candidate, rows = state.candidates[recid], []
    identifiers = state.source.identifiers(candidate)
    listed = candidate['linked_hepdata']
    for row in listed:
        ref = row['ref']
        linked_ids = row.get('identifiers', {**identifiers, 'hepdata': [ref]})
        if not _screen(state.rows, linked_ids, classes=('hepdata',))['allowed']:
            rows.append({'kind': 'hepdata-record', 'status': 'withheld'}); continue
        rows.append({'kind': 'hepdata-record', 'status': 'candidate', 'ref': ref, 'basis': 'provider-listed',
                     'pointer': row.get('pointer'),
                     'lookup_url': record_json_url(ref) if re.fullmatch(r'(?:ins)?[0-9]+', ref) else None})
    if not listed:
        rows.append({'kind': 'hepdata-record', 'status': 'not_listed',
                     'note': 'Absence from provider metadata does not establish that no record exists.'})
    if state.graph is None:
        rows.append({'kind': 'implementation', 'status': 'graph_unavailable'})
        return rows
    from .literature_relations import GraphQuery, identifier
    names = []
    for namespace, values in candidate.get('graph_identifiers', identifiers).items():
        for value in values:
            try: name = identifier(namespace, value)
            except ValueError: continue
            if name not in names: names.append(name)
    seen, denied = set(), _graph_denials(state.rows)
    for name in names:
        for operation in ('implementations', 'published_artifacts'):
            result = state.graph.query(GraphQuery(operation, name, max_results=20), denied_identifiers=denied)
            for hit in result['results']:
                node = hit['node']
                if node['id'] in seen: continue
                seen.add(node['id'])
                namespace, _, value = node['id'].partition(':')
                ids = {namespace: [value]} if namespace in ('inspire', 'arxiv', 'hepdata', 'analysis') else {}
                if not _screen(state.rows, ids, classes=(node['kind'],))['allowed']:
                    rows.append({'kind': node['kind'], 'status': 'withheld'}); continue
                rows.append({'kind': node['kind'], 'status': 'candidate', 'node': node['id'], 'via': name,
                             'operation': operation, 'graph_sha256': result['graph_sha256'],
                             'path_length': len(hit['path'])})
            if result['truncated']:
                rows.append({'kind': operation, 'status': 'truncated', 'via': name})
    if not seen:
        rows.append({'kind': 'implementation', 'status': 'no_graph_match',
                     'note': 'A missing mapping is unknown, not an unsupported analysis.'})
    return rows


def _rule_counts(groups):
    """Withheld records per violated restriction row digest; never which record."""
    counts = {}
    for rules in groups:
        for rule in rules:
            counts[rule] = counts.get(rule, 0) + 1
    return dict(sorted(counts.items()))


def _gaps(state, rows):
    executable, keys, gaps = state.executable(rows), {r['key'] for r in rows}, []
    for row in rows:
        done = state.requests.get(row['key'])
        if done is not None:
            if done['status'] != 'discovered':
                gaps.append({'kind': 'request_' + done['status'], 'key': row['key'], 'reason': done['reason']})
                continue
            fetched = (row['page'] - 1) * row['size'] + len(done['hits'])
            following = row['key'].rsplit(':p', 1)[0] + ':p' + str(row['page'] + 1)
            if following not in keys and (done['next'] is not None or (
                    done['remote_total'] is not None and done['remote_total'] > fetched)):
                gaps.append({'kind': 'unfetched_pages', 'key': row['key'], 'remote_total': done['remote_total'],
                             'remote_total_relation': done['remote_total_relation'], 'fetched': fetched})
            if done['remote_total_relation'] == 'gte':
                gaps.append({'kind': 'provider_total_lower_bound', 'key': row['key'],
                             'remote_total': done['remote_total']})
            if done['remote_total'] is None:
                gaps.append({'kind': 'provider_total_unknown', 'key': row['key']})
        elif state.refused(row) is not None:
            if state.refused(row).get('reason') == 'source_lacks_citations':
                gaps.append({'kind': 'citation_refused', 'key': row['key'], 'status': 'refused',
                             'reason': 'source_lacks_citations', 'source': state.source.id})
                continue
            gaps.append({'kind': 'query_withheld', 'key': row['key'],
                         'by_rule': _rule_counts([[_digest(lc._raw(r)) for r in state.refused(row)['rules']]])})
        else:
            gaps.append({'kind': 'halted' if state.halted else 'budget_exhausted' if row['key'] not in executable
                         else 'not_executed', 'key': row['key']})
    for variant in state.variants[state.limits['max_variants']:]:
        gaps.append({'kind': 'variant_budget', 'variant': variant['id']})
    withheld = [[_digest(lc._raw(r)) for r in s['rules']] for s in state.seed_screen.values() if not s['allowed']]
    if withheld:
        gaps.append({'kind': 'seeds_withheld', 'count': len(withheld), 'by_rule': _rule_counts(withheld)})
    expanded = {r['purpose']['node'] for r in rows if r['purpose']['kind'] == 'expansion'}
    for recid, c in state.candidates.items():
        if not state.scope['follow'] or recid in expanded:
            continue
        eligible = state.eligible(recid)
        # A rejected or outside-universe record is deliberately not followed; an unjudged one is a gap.
        if not eligible and state.status_of(recid)[0] != 'unresolved':
            continue
        reason = ('depth_limit' if c['depth'] >= state.limits['max_depth'] else
                  'not_judged' if not eligible else 'halted' if state.halted else 'wave_unsettled')
        gaps.append({'kind': 'frontier_not_expanded', 'recid': recid, 'reason': reason, 'depth': c['depth']})
    return gaps


def _disagreements(state, rows):
    """Provider totals for citation pages against the node's own metadata counts."""
    found = []
    for row in rows:
        done = state.requests.get(row['key'])
        if (row['purpose']['kind'] != 'expansion' or row['page'] != 1 or done is None
                or done['status'] != 'discovered' or done['remote_total_relation'] != 'eq'):
            continue
        node = state.candidates.get(row['purpose']['node'])
        if node is None: continue
        if row['purpose']['direction'] == 'references':
            linked = len(node['references'])
            if linked != done['remote_total']:
                found.append({'kind': 'reference_count', 'recid': node['recid'], 'provider_total': done['remote_total'],
                              'metadata_linked_references': linked})
        else:
            cited = node.get('citation_count')
            if type(cited) is int and cited != done['remote_total']:
                found.append({'kind': 'citation_count', 'recid': node['recid'], 'provider_total': done['remote_total'],
                              'metadata_citation_count': cited})
    return found


def report(root, out, *, source=None, roles=None, _state=None):
    """The completeness report as a pure function of the ledger, its products and its admitted replies."""
    out = cycle._ordinary(out)
    state = _state or _State(root, out, _steps(out)[0], roles, source=source)
    rows = state.planned()
    names = {'demonstrated': 'demonstrated', 'plausible': 'plausible_needs_validation', 'unresolved': 'unresolved',
             'rejected': 'rejected', 'outside_universe': 'outside_universe'}
    population = {name: [] for name in names.values()}
    follow = []
    for recid in state.candidates:
        verdict, reasons = state.status_of(recid)
        population[names[verdict]].append(_entry(state, recid, verdict, reasons))
        if verdict in ('demonstrated', 'plausible'):
            follow.append({'source': state.source.id, 'recid': recid, 'candidates': _follow_ups(state, recid)})
    for recid, key in state.overflow.items():
        population['unresolved'].append({'source': state.source.id, 'recid': recid, 'status': 'unresolved', 'reasons': ['candidate_cap'],
                                         'origins': [{'key': key}], 'lookup_url': sources.record_url(state.source, recid)})
    seen = set(state.candidates) | set(state.withheld) | set(state.overflow)
    for seed in state.scope['seeds']:
        if state.seed_screen[seed]['allowed'] and seed not in seen:
            population['unresolved'].append({'source': state.source.id, 'recid': seed, 'status': 'unresolved', 'seed': True,
                                             'reasons': ['seed_not_returned'], 'lookup_url': sources.record_url(state.source, seed)})
    issued = sorted(d['issued_at'] for d in state.requests.values())
    returned = sorted(d['returned_at'] for d in state.requests.values() if d['returned_at'])
    queries = [{'source': state.source.id, **{k: deepcopy(d[k]) for k in ('key', 'purpose', 'query', 'page', 'size', 'status', 'remote_total',
                                               'remote_total_relation', 'issued_at')}, 'hits': len(d['hits'])}
               for d in state.requests.values()]
    counts = {name: len(entries) for name, entries in population.items()}
    counts['withheld'] = len(state.withheld)
    counts['withheld_seeds'] = sum(1 for s in state.seed_screen.values() if not s['allowed'])
    counts['encountered'] = sum(counts.values())
    return {'schema_version': 1, 'kind': REPORT_KIND, 'source': state.source.id,
            'capabilities': deepcopy(state.source.capabilities), 'status': 'halted' if state.halted else 'complete',
            'halt_reason': state.halted, 'scope': deepcopy(state.start['scope']), 'scope_id': state.scope['id'],
            'question': state.scope['question'], 'criteria': deepcopy(state.scope['criteria']),
            'search_universe': {
                'source': state.source.id, 'provider': state.source.id,
                **sources.source_metadata(state.source),
                'agent_version': VERSION, 'first_request_at': issued[0] if issued else None,
                'last_response_at': returned[-1] if returned else None,
                'clock': 'Agent UTC clock at each request; the provider index state is not otherwise attested.',
                'years': deepcopy(state.scope['universe']['years']),
                'document_types': deepcopy(state.scope['universe']['document_types']),
                'follow': list(state.scope['follow']), 'limits': deepcopy(state.limits), 'queries': queries,
                'disagreements': _disagreements(state, rows),
                'source_restriction_sha256': source_policy.digest(state.rows),
                'graph_sha256': state.start['graph_sha256'], 'lower_bound': True,
                'statement': 'A lower bound: only the listed provider queries and pages, as served when issued.'},
            'population': population,
            'withheld': {'count': len(state.withheld), 'by_rule': _rule_counts(state.withheld.values())},
            'counts': counts, 'gaps': [{'source': state.source.id, **gap} for gap in _gaps(state, rows)], 'follow_up': follow,
            'selection': {'selector': deepcopy(state.selector), 'calls': deepcopy(state.selections),
                          'stopped': state.stopped},
            'usage': {'requests': len(state.requests),
                      'expansions': sum(1 for d in state.requests.values() if d['purpose']['kind'] == 'expansion'),
                      'selection_calls': len(state.selections)},
            'definitions': deepcopy(DEFINITIONS), 'primary_source_required': True, 'claims': deepcopy(CLAIMS)}


def consume(root, out, *, roles=None):
    """Recompute the written report from its ledger; any difference is refused."""
    out = cycle._ordinary(out)
    steps, _ = _steps(out)
    end = steps[-1]['event']
    if end.get('type') != 'complete':
        raise ValueError('discovery has not ended')
    state = _State(root, out, steps, roles)
    document = report(root, out, roles=roles, _state=state)
    if cycle._pin(end['report']['path']) != end['report'] or lc._raw(document) != Path(end['report']['path']).read_bytes():
        raise ValueError('discovery report differs from its ledger replay')
    return document
