"""Literature query expansion: a curated generic vocabulary and one optional governed choice.

The deterministic expansion finds curated notation, abbreviations and synonyms
(``data/knowledge/query_expansion.json``) in a query and appends the other forms
of each matched concept. Without a model, the result is a pure function of the
query, the vocabulary bytes and the limits.

A model contributes only through one recorded, charged Graph call
(``request_document`` -> ``write_request`` -> ``graph_spec`` -> ``agent_graph.execute``).
The call's instructions are the protocol of a registered role card, never text
written here, so the call is unavailable until that card is registered.
``expand`` reads that call back through ``admit``. The model chooses curated
entries from a closed list. It may also propose a few short terms, which are kept
only when each lexical token occurs in the caller's allowed-source vocabulary. A
missing, stale or invalid reply is refused with a reason, and the deterministic
expansion stands. Expansion terms are search hints, never evidence. The retrieval
provider's ``search`` stays free of model calls.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

from .knowledge import _tokens as _lexical  # the BM25 tokenizer literature search applies to the query

KIND = 'literature-query-expansion'
REQUEST_KIND = 'literature-query-expansion-request'
CHOICE_KIND = 'literature-query-expansion-choice'
VOCABULARY_KIND = 'literature-query-vocabulary'
VOCABULARY = Path(__file__).resolve().parents[1] / 'data/knowledge/query_expansion.json'
NODE = 'expand'
INPUT_ID = 'expansion-request'
MAX_QUERY_CHARS = 2048  # retrieval.json search_args query bound
MAX_REQUEST_BYTES = 1 << 20
MAX_TERM_CHARS, MAX_TERM_WORDS = 48, 5
LIMITS = {'max_terms': 16, 'max_terms_per_entry': 6, 'max_model_entries': 4, 'max_model_terms': 4}
_BOUNDS = {'max_terms': (0, 64), 'max_terms_per_entry': (1, 16), 'max_model_entries': (0, 16), 'max_model_terms': (0, 16)}
CLASSES = frozenset({'observable', 'condition', 'quantity', 'statistics', 'region', 'method', 'model', 'theory',
                     'object', 'particle', 'final-state', 'process'})
_ID = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
# Notation symbols become words, so Z′, Z' and "Z prime" agree; combining tildes and bars mark sparticles.
_SYMBOLS = {"'": 'prime', '\u2019': 'prime', '\u2032': 'prime', '\u221a': 'sqrt', '\u00b1': 'pm', '\u2213': 'pm',
            '\u00d7': 'times', '\u0303': 'tilde', '\u0304': 'bar', '\u0305': 'bar',
            '\u2113': 'ell'}
_GREEK = dict(zip('αβγδεζηθικλμνξπρσςτυφχψω', 'alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu '
                  'nu xi pi rho sigma sigma tau upsilon phi chi psi omega'.split()))
# Typesetting commands carry no meaning: E_{\mathrm{T}}^{\mathrm{miss}} reads as E_T^miss.
_TYPESETTING = frozenset('mathrm textrm text rm mathit mathbf bf boldsymbol mathcal mathsf operatorname displaystyle'.split())
_TERM_CHARACTERS = frozenset(" -+'/^_{}().,\\\u00b1\u00d7\u2032")
# The registered role card whose protocol instructs the one governed expansion call.
ROLE = 'literature-query-expander'


class _Refusal(ValueError):
    """A governed reply that cannot be admitted; ``code`` is the recorded reason."""

    def __init__(self, code, detail=None):
        super().__init__(code + (': ' + detail if detail else ''))
        self.code = code


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def _loads(raw):
    def unique(pairs):
        value = dict(pairs)
        if len(value) != len(pairs):
            raise ValueError('duplicate JSON key')
        return value
    def constant(name):
        raise ValueError('nonfinite JSON number: ' + name)
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
    except RecursionError:
        raise ValueError('JSON nesting exceeds the interpreter bound') from None


def _keys(value, required, optional=(), what='record'):
    if type(value) is not dict or not set(required) <= set(value) <= set(required) | set(optional):
        raise ValueError('exact fields required: ' + what)


def _words(text):
    """Case-preserving notation tokens: symbols and Greek letters spelled out, accents and typesetting dropped.

    A spelled combining mark precedes its base, as ``\\tilde{g}`` is written, so g̃ reads as \\tilde{g}.
    A change between ordinary, superscript and subscript characters separates tokens, as ``^`` and ``_`` do.
    """
    out, base, level = [], None, None
    for character in text:
        script = unicodedata.decomposition(character).split(' ')[0]
        script = script if script in ('<super>', '<sub>') else None
        if script != level:
            out.append(' ')
            level = script
        pieces = character if character in _SYMBOLS else unicodedata.normalize(
            'NFD', unicodedata.normalize('NFKC', character))
        for ch in pieces:
            word = _SYMBOLS.get(ch) or _GREEK.get(ch.casefold())
            if word and unicodedata.combining(ch) and base is not None:
                out.insert(base, ' ' + word + ' ')  # an outer mark lands before an inner one: \bar{\tilde{x}}
            elif word or not unicodedata.combining(ch):
                base = len(out)
                out.append(' ' + word + ' ' if word else ch)
    return [w for w in re.findall(r'[^\W_]+', ''.join(out)) if w.casefold() not in _TYPESETTING]


def _fold(word):
    word = word.casefold()
    # Plural folding, applied to query and form alike: jets/jet, leptons/lepton; not miss or CLs.
    return word[:-1] if len(word) > 3 and word.endswith('s') and not word.endswith(('ss', 'us', 'is')) else word


def _tokenize(text):
    return [(w, _fold(w)) for w in _words(text)]


def _key(text, exact):
    # In an exact form only words carrying a capital letter keep their case: "MET significance".
    return tuple((w, _fold(w), exact and any(c.isupper() for c in w)) for w in _words(text))


def _match_at(words, start, key):
    """None, or the number of capitalised plurals (LLPs for LLP) needed to match ``key`` at ``start``."""
    if not key or start + len(key) > len(words):
        return None
    plurals = 0
    for offset, (key_raw, key_fold, exact) in enumerate(key):
        raw, fold = words[start + offset]
        if not exact:
            if fold != key_fold:
                return None
        elif raw != key_raw:
            if raw != key_raw + 's' or not key_raw.isupper():
                return None
            plurals += 1
    return plurals


def _occurs(words, key):
    return any(_match_at(words, i, key) is not None for i in range(len(words)))


def _compile(document):
    _keys(document, {'schema_version', 'kind', 'note', 'entries'}, what='query vocabulary')
    if document['schema_version'] != 1 or type(document['schema_version']) is not int or document['kind'] != VOCABULARY_KIND:
        raise ValueError('unsupported query vocabulary')
    if type(document['note']) is not str or not document['note'].strip():
        raise ValueError('query vocabulary note required')
    if type(document['entries']) is not list or not 1 <= len(document['entries']) <= 1024:
        raise ValueError('finite query vocabulary entries required')
    entries, ids, triggers, owners = [], set(), {}, {}
    for e_index, entry in enumerate(document['entries']):
        _keys(entry, {'id', 'class', 'forms'}, what='query vocabulary entry')
        if type(entry['id']) is not str or not _ID.match(entry['id']) or entry['id'] in ids:
            raise ValueError('unique slug query vocabulary entry ID required')
        if type(entry['class']) is not str or entry['class'] not in CLASSES:
            raise ValueError('known query vocabulary class required: ' + entry['id'])
        if type(entry['forms']) is not list or not 2 <= len(entry['forms']) <= 16:
            raise ValueError('two to sixteen forms required: ' + entry['id'])
        ids.add(entry['id'])
        forms, folded = [], set()
        for f_index, form in enumerate(entry['forms']):
            _keys(form, {'text'}, {'case', 'trigger'}, what='query vocabulary form')
            text, case, trigger = form['text'], form.get('case', 'fold'), form.get('trigger', True)
            if (type(text) is not str or not 1 <= len(text) <= 64 or text != text.strip()
                    or any(unicodedata.category(c).startswith('C') for c in text)):
                raise ValueError('bounded printable form text required: ' + entry['id'])
            if case not in ('fold', 'exact') or type(trigger) is not bool:
                raise ValueError('form case fold/exact and boolean trigger required: ' + entry['id'])
            if case == 'exact' and not any(c.isupper() for c in text):
                raise ValueError('an exact-case form needs a capital letter: ' + entry['id'])
            key = _key(text, case == 'exact')
            plain = tuple(k[1] for k in key)
            if not key or plain in folded:
                raise ValueError('distinct nonempty form tokens required: ' + entry['id'])
            folded.add(plain)
            compiled = {'text': text, 'key': key, 'trigger': trigger}
            if trigger:
                if sum(len(k) for k in plain) < 2:
                    raise ValueError('a one-character form cannot trigger expansion: ' + entry['id'])
                if owners.setdefault(plain, entry['id']) != entry['id']:
                    raise ValueError('ambiguous trigger form shared by two entries: ' + entry['id'])
                triggers.setdefault(plain[0], []).append((e_index, f_index, compiled))
            forms.append(compiled)
        if not any(f['trigger'] for f in forms):
            raise ValueError('an entry needs a trigger form: ' + entry['id'])
        entries.append({'id': entry['id'], 'class': entry['class'], 'forms': tuple(forms)})
    return {'entries': tuple(entries), 'by_id': {e['id']: e for e in entries},
            'triggers': {k: tuple(v) for k, v in triggers.items()}}


@lru_cache(maxsize=8)
def _compiled(sha256, raw):
    try:
        document = _loads(raw)
    except ValueError as exc:
        raise ValueError('query vocabulary is not finite JSON') from exc
    return {**_compile(document), 'sha256': sha256}


def _vocabulary(path=None):
    raw = Path(path or VOCABULARY).read_bytes()
    if len(raw) > MAX_REQUEST_BYTES:
        raise ValueError('query vocabulary exceeds its byte bound')
    return _compiled(_digest(raw), raw)


def load_vocabulary(path=None):
    """The validated curated vocabulary: its sha256 and every entry's id, class and forms."""
    vocabulary = _vocabulary(path)
    return {'sha256': vocabulary['sha256'], 'entries': [
        {'id': e['id'], 'class': e['class'], 'forms': [
            {'text': f['text'], 'trigger': f['trigger'], 'exact': any(k[2] for k in f['key'])} for f in e['forms']]}
        for e in vocabulary['entries']]}


def source_vocabulary(texts):
    """Lexical tokens of already policy-filtered source texts; the only basis for a model-proposed term."""
    if isinstance(texts, (str, bytes)):
        raise ValueError('source vocabulary takes an iterable of texts')
    tokens = set()
    for text in texts:
        if type(text) is not str:
            raise ValueError('source vocabulary takes text')
        tokens.update(_lexical(text))
    return frozenset(tokens)


def _query(value):
    if type(value) is not str or not value.strip() or len(value) > MAX_QUERY_CHARS:
        raise ValueError(f'literature query must be nonblank text of at most {MAX_QUERY_CHARS} characters')
    return value


def _limits(value=None):
    merged = dict(LIMITS)
    if value is not None:
        if type(value) is not dict or set(value) - set(LIMITS):
            raise ValueError('unknown query expansion limit')
        merged.update(value)
    for key, (low, high) in _BOUNDS.items():
        if type(merged[key]) is not int or not low <= merged[key] <= high:
            raise ValueError('query expansion limit outside bound: ' + key)
    return merged


def _matches(words, vocabulary):
    """Leftmost-longest, non-overlapping trigger matches; ties prefer no plural folding, then vocabulary order."""
    found, start = [], 0
    while start < len(words):
        fold = words[start][1]
        candidates = vocabulary['triggers'].get(fold, ()) + (vocabulary['triggers'].get(fold[:-1], ()) if fold.endswith('s') else ())
        best = None
        for e_index, f_index, form in candidates:
            plurals = _match_at(words, start, form['key'])
            if plurals is not None:
                rank = (-len(form['key']), plurals, e_index, f_index)
                if best is None or rank < best[0]:
                    best = (rank, e_index, form)
        if best is None:
            start += 1
            continue
        _, e_index, form = best
        found.append({'entry': vocabulary['entries'][e_index]['id'], 'form': form['text'],
                      'tokens': [start, start + len(form['key'])]})
        start += len(form['key'])
    return found


class _Terms:
    def __init__(self, query, limits):
        self.limits, self.expanded = limits, query
        self.tokens = set(_lexical(query))
        self.terms, self.omitted, self.per_entry = [], [], {}

    def omit(self, text, entry, origin, reason):
        self.omitted.append({'text': text, 'entry': entry, 'origin': origin, 'reason': reason})

    def offer(self, text, entry, origin, *, present=False):
        new = {t for t in _lexical(text) if len(t) > 1} - self.tokens
        reason = ('present_in_query' if present else 'no_new_lexical_token' if not new
                  else 'entry_cap' if entry is not None and self.per_entry.get(entry, 0) >= self.limits['max_terms_per_entry']
                  else 'term_cap' if len(self.terms) >= self.limits['max_terms']
                  else 'query_length_cap' if len(self.expanded) + 2 + len(text) > MAX_QUERY_CHARS else None)
        if reason:
            return self.omit(text, entry, origin, reason)
        self.terms.append({'text': text, 'entry': entry, 'origin': origin})
        self.tokens |= new
        self.expanded += '; ' + text
        if entry is not None:
            self.per_entry[entry] = self.per_entry.get(entry, 0) + 1

    def entry(self, entry, origin, words):
        for form in entry['forms']:
            self.offer(form['text'], entry['id'], origin, present=_occurs(words, form['key']))


def _term_shape(text):
    return (type(text) is str and 2 <= len(text) <= MAX_TERM_CHARS and text == text.strip()
            and len(text.split()) <= MAX_TERM_WORDS and any(c.isalnum() for c in text)
            and all(c.isalnum() or c in _TERM_CHARACTERS for c in text))


def expand(query, *, governed=None, known_tokens=None, limits=None, vocabulary=None, roles=None, campaign_root=None):
    """Expand ``query`` deterministically, adding an admitted governed model choice when supplied.

    ``governed`` is ``{'request': <request pin>, 'graph_root': <executed graph>}``; it is read
    only through ``admit``. ``known_tokens`` is the lexical vocabulary of the allowed source
    view, built after source filtering (``source_vocabulary`` over policy-filtered units), so a
    withheld source cannot admit a term. Model-proposed terms are dropped without it; its
    digest is recorded for replay. ``expanded_query`` fits the retrieval search query bound.
    """
    query = _query(query)
    limits = _limits(limits)
    compiled = _vocabulary(vocabulary)
    source = None
    if known_tokens is not None:
        if isinstance(known_tokens, (str, bytes)):
            raise ValueError('known source tokens must be an iterable of tokens')
        known_tokens = frozenset(known_tokens)
        if any(type(t) is not str for t in known_tokens):
            raise ValueError('known source tokens must be text')
        source = {'sha256': _digest(_canonical(sorted(known_tokens))), 'tokens': len(known_tokens)}
    words = _tokenize(query)
    matches = _matches(words, compiled)
    terms = _Terms(query, limits)
    expanded_entries = []
    for match in matches:
        if match['entry'] not in expanded_entries:
            expanded_entries.append(match['entry'])
            terms.entry(compiled['by_id'][match['entry']], 'vocabulary', words)
    model = {'status': 'not_requested'}
    if governed is not None:
        if type(governed) is not dict or set(governed) != {'request', 'graph_root'}:
            raise ValueError('governed expansion takes exactly a request pin and a graph root')
        model = admit(governed['request'], governed['graph_root'], vocabulary=vocabulary, roles=roles,
                      campaign_root=campaign_root)
        if model['status'] == 'admitted' and model['query'] != query:
            model = {'status': 'refused', 'reason': 'other_query', 'request_sha256': model['request_sha256']}
    if model['status'] == 'admitted':
        for index, identity in enumerate(model['entries']):
            if index >= limits['max_model_entries']:
                terms.omit(None, identity, 'model_entry', 'model_entry_cap')
            elif identity in expanded_entries:
                terms.omit(None, identity, 'model_entry', 'already_expanded')
            else:
                expanded_entries.append(identity)
                terms.entry(compiled['by_id'][identity], 'model_entry', words)
        for index, text in enumerate(model['terms']):
            lexical = set(_lexical(text)) if _term_shape(text) else set()
            reason = ('model_term_cap' if index >= limits['max_model_terms'] else 'invalid_term' if not _term_shape(text)
                      else 'no_source_vocabulary' if known_tokens is None
                      else 'not_in_source_vocabulary' if not lexical or not lexical <= known_tokens
                      else None)
            if reason:
                terms.omit(text, None, 'model_term', reason)
            else:
                terms.offer(text, None, 'model_term', present=_occurs(words, _key(text, False)))
    result = {'schema_version': 1, 'kind': KIND, 'query': query, 'expanded_query': terms.expanded,
              'vocabulary_sha256': compiled['sha256'], 'source_vocabulary': source, 'limits': limits, 'matches': matches,
              'terms': terms.terms, 'omitted': terms.omitted, 'model': model, 'search_hint_only': True}
    result['sha256'] = _digest(_canonical(result))
    return result


def _card_instructions(role, roles=None):
    """The registered card's protocol, the only instruction source; ``roles`` is a registry document override."""
    from . import role_registry
    try:
        card = role_registry.load(role, document=roles)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise _Refusal('role_card_unavailable', str(exc)) from None
    protocol = card.get('protocol')
    if type(protocol) is not list or not protocol or any(type(p) is not str or not p.strip() for p in protocol):
        raise _Refusal('role_card_unavailable', 'a nonempty protocol is required: ' + str(role))
    return ' '.join(protocol)


def request_document(query, *, role=ROLE, limits=None, vocabulary=None, roles=None):
    """The complete input of the one governed expansion call: query, closed vocabulary, caps and card."""
    query, limits, compiled = _query(query), _limits(limits), _vocabulary(vocabulary)
    if not limits['max_model_entries'] and not limits['max_model_terms']:
        raise ValueError('a governed expansion request needs a model entry or term allowance')
    if type(role) is not str or not _ID.match(role):
        raise ValueError('registered role card ID required')
    _card_instructions(role, roles)
    matched = []
    for match in _matches(_tokenize(query), compiled):
        if match['entry'] not in matched:
            matched.append(match['entry'])
    return {'schema_version': 1, 'kind': REQUEST_KIND, 'query': query, 'vocabulary_sha256': compiled['sha256'],
            'role': role, 'matched_entries': matched,
            'limits': {'max_entries': limits['max_model_entries'], 'max_terms': limits['max_model_terms'],
                       'max_term_chars': MAX_TERM_CHARS, 'max_term_words': MAX_TERM_WORDS},
            'entries': [{'id': e['id'], 'class': e['class'], 'forms': [f['text'] for f in e['forms']]}
                        for e in compiled['entries']]}


def _request(document, vocabulary=None, roles=None):
    _keys(document, {'schema_version', 'kind', 'query', 'vocabulary_sha256', 'role', 'matched_entries', 'limits',
                     'entries'}, what='query expansion request')
    if document['schema_version'] != 1 or type(document['schema_version']) is not int or document['kind'] != REQUEST_KIND:
        raise ValueError('unsupported query expansion request')
    if document['vocabulary_sha256'] != _vocabulary(vocabulary)['sha256']:
        raise _Refusal('vocabulary_changed')
    _keys(document['limits'], {'max_entries', 'max_terms', 'max_term_chars', 'max_term_words'}, what='request limits')
    expected = request_document(document['query'], role=document['role'], vocabulary=vocabulary, roles=roles, limits={
        **LIMITS, 'max_model_entries': document['limits']['max_entries'],
        'max_model_terms': document['limits']['max_terms']})
    if document != expected:
        raise ValueError('query expansion request differs from its vocabulary projection')
    return document


def write_request(path, document, *, vocabulary=None, roles=None):
    """Write a fresh request file and return its pin; an existing file or symlinked parent is refused."""
    raw = (json.dumps(_request(document, vocabulary, roles), indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode()
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('ordinary request destination required')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
    return {'path': str(path.resolve()), 'sha256': _digest(raw), 'size': len(raw)}


def _read_request(pin, vocabulary=None, roles=None):
    if type(pin) is not dict or type(pin.get('path')) is not str or not _SHA.match(str(pin.get('sha256'))):
        raise _Refusal('invalid_request_pin')
    path = Path(pin['path'])
    if path.stat().st_size > MAX_REQUEST_BYTES:
        raise _Refusal('request_pin_mismatch')
    raw = path.read_bytes()
    if _digest(raw) != pin['sha256']:
        raise _Refusal('request_pin_mismatch')
    return _request(_loads(raw), vocabulary, roles)


def graph_spec(request_pin, *, graph_id, model, reasoning_effort, adapter='responses', max_output_tokens=1024,
               max_wall_seconds=300, vocabulary=None, roles=None):
    """One bounded registered-role call with one attempt and a closed reply schema; no reworks.

    The instructions are the request's registered role card protocol, rendered at build time.
    A governed seat may use the original role card's broker tools.
    """
    from . import agent_graph
    document = _read_request(request_pin, vocabulary, roles)
    instructions = _card_instructions(document['role'], roles)
    if adapter not in ('model', 'responses', 'command', 'external', 'anthropic', 'gemini', 'chat_completions'):
        raise ValueError('existing configured model transport required')
    if any(type(v) is not str or not v.strip() for v in (model, reasoning_effort)):
        raise ValueError('explicit actual model/effort required')
    if type(max_output_tokens) is not int or not 64 <= max_output_tokens <= 4096:
        raise ValueError('expansion output token bound outside 64..4096')
    limits = document['limits']
    schema = {'type': 'object', 'additionalProperties': False,
              'required': ['kind', 'request_sha256', 'entries', 'terms'], 'properties': {
                  'kind': {'type': 'string', 'const': CHOICE_KIND},
                  'request_sha256': {'type': 'string', 'const': request_pin['sha256']},
                  'entries': {'type': 'array', 'maxItems': limits['max_entries'],
                              'items': {'type': 'string', 'enum': [e['id'] for e in document['entries']]}},
                  'terms': {'type': 'array', 'maxItems': limits['max_terms'],
                            'items': {'type': 'string', 'minLength': 2, 'maxLength': MAX_TERM_CHARS}}}}
    spec = {'schema_version': 1, 'graph_id': graph_id,
            'budget': {'max_nodes': 1, 'max_calls': 1, 'max_output_tokens': max_output_tokens,
                       'max_wall_seconds': max_wall_seconds, 'max_reworks': 0},
            'nodes': [{'id': NODE, 'kind': 'model', 'role': 'proposer', 'registry_role': ROLE, 'depends_on': [],
                       'inputs': [{'id': INPUT_ID, 'path': str(Path(request_pin['path']).absolute()),
                                   'sha256': request_pin['sha256']}],
                       'packet': None, 'action': adapter, 'max_attempts': 1,
                       'parameters': {'model': model, 'reasoning_effort': reasoning_effort,
                                      'max_output_tokens': max_output_tokens, 'output_schema': schema,
                                      'instructions': instructions}}]}
    agent_graph.validate(spec)
    return spec


def admit(request_pin, graph_root, *, vocabulary=None, roles=None, campaign_root=None):
    """Admit the recorded reply of the exact bounded expansion Graph, or refuse it with a reason code.

    The expected Graph is rebuilt from the current request, vocabulary and role card, so a changed
    card protocol, budget, schema or input refuses the recorded call.
    """
    from . import agent_graph
    from .research_cycle import _graph_result
    sha = request_pin.get('sha256') if type(request_pin) is dict else None
    sha = sha if type(sha) is str and _SHA.match(sha) else None
    try:
        document = _read_request(request_pin, vocabulary, roles)
        root = Path(graph_root).absolute()
        try:
            spec, _ = agent_graph._load(root)
        except (ValueError, KeyError, TypeError, OSError):
            raise _Refusal('graph_result_unavailable') from None
        try:
            node = spec['nodes'][0]
            expected = graph_spec(request_pin, graph_id=spec['graph_id'], model=node['parameters']['model'],
                                  reasoning_effort=node['parameters']['reasoning_effort'], adapter=node['action'],
                                  max_output_tokens=node['parameters']['max_output_tokens'],
                                  max_wall_seconds=spec['budget']['max_wall_seconds'], vocabulary=vocabulary,
                                  roles=roles)
        except _Refusal:
            raise
        except (ValueError, KeyError, IndexError, TypeError, OSError):
            raise _Refusal('graph_spec_mismatch') from None
        from .research_cycle import matches_campaign_graph
        try:
            matches = matches_campaign_graph(campaign_root, root, spec, expected)
        except (ValueError, KeyError, TypeError, OSError):
            matches = False
        if not matches:
            raise _Refusal('graph_spec_mismatch')
        try:
            origin = _graph_result(root, NODE)
        except (ValueError, KeyError, TypeError, OSError):
            raise _Refusal('graph_result_unavailable') from None
        value = origin['value']
        if origin['node_kind'] != 'model' or type(value) is not dict or value.get('kind') != 'model_result':
            raise _Refusal('not_a_model_result')
        choice = value.get('value')
        try:
            _keys(choice, {'kind', 'request_sha256', 'entries', 'terms'}, what='expansion choice')
        except ValueError:
            raise _Refusal('invalid_choice') from None
        if choice['kind'] != CHOICE_KIND or choice['request_sha256'] != request_pin['sha256']:
            raise _Refusal('other_request')
        known = {e['id'] for e in document['entries']}
        entries, terms = choice['entries'], choice['terms']
        if (type(entries) is not list or len(entries) > document['limits']['max_entries']
                or any(type(e) is not str or e not in known for e in entries)
                or type(terms) is not list or len(terms) > document['limits']['max_terms']
                or any(type(t) is not str or not 2 <= len(t) <= MAX_TERM_CHARS for t in terms)):
            raise _Refusal('invalid_choice')
    except _Refusal as refusal:
        return {'status': 'refused', 'reason': refusal.code, 'request_sha256': sha}
    except OSError:
        return {'status': 'refused', 'reason': 'request_unavailable', 'request_sha256': sha}
    except ValueError:
        return {'status': 'refused', 'reason': 'invalid_request', 'request_sha256': sha}
    unique_terms = []
    for term in terms:
        if term.casefold() not in {t.casefold() for t in unique_terms}:
            unique_terms.append(term)
    return {'status': 'admitted', 'query': document['query'], 'request_sha256': request_pin['sha256'],
            'receipt': deepcopy(origin['receipt']), 'binding_sha256': origin['binding_sha256'],
            'entries': list(dict.fromkeys(entries)), 'terms': unique_terms}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Deterministic literature query expansion (no model call).')
    parser.add_argument('--query', required=True)
    parser.add_argument('--limits', help='JSON object overriding ' + ', '.join(sorted(LIMITS)))
    parser.add_argument('--vocabulary', help='curated vocabulary path (default: the shipped list)')
    args = parser.parse_args(argv)
    try:
        result = expand(args.query, limits=_loads(args.limits) if args.limits else None, vocabulary=args.vocabulary)
    except (ValueError, OSError) as exc:
        print(f'literature_query: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
