"""Governed broker serving for the candidate literature provider.

Every surface reaches one trusted handler through ``broker.Broker.call``: the
CLI and role-bundle builders through ``call``, workers through ``ravel work
call``, the MCP face or in-graph role tools. Admission, receipts and served
bytes are therefore the same on every surface. Each decision is appended to a
supervisor-custody ledger before its effect: a denial before the provider runs
or anything is written, an admission before the provider runs, and a served
record before the result file exists. A result is the content-addressed
located envelope (the provider envelope without its wall-clock time); a replay
re-runs the recorded request under the recorded binding and must reproduce
those bytes exactly. Serving grants neither scientific verification nor
execution authority. Without a bound configuration every call is a receipted
``retrieval_unavailable`` refusal and the existing knowledge queries are
unchanged.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from fnmatch import fnmatchcase
import hashlib
from importlib.resources import files
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import threading
import time

from . import broker as core, knowledge_broker, literature_build, literature_provider as contract
from . import literature_graph_retrieval as graph_retrieval, restriction_guard, source_policy
from .literature_relations import GraphQuery, RetrievalDocumentBinding, RetrievalSourceBinding
from .state_io import read_json

ACTION = 'literature query'
REPLAY_ACTION = 'literature.replay'
LEDGER = 'literature-serving'
OUTPUTS = 'outputs/literature'
VIEW_LAW = 'literature-serving-view/1'
QUALIFICATION_KIND = 'literature-provider-qualification'
TOOL_NAMES = {op: 'literature_' + op for op in contract.OPERATIONS}
DEFAULT_BUDGETS = {'max_tokens': 32768, 'max_bytes': 32768, 'max_seconds': 10.0, 'max_expansions': 256}
DEFAULT_CEILINGS = {'max_tokens': 131072, 'max_bytes': 131072, 'max_seconds': 60.0, 'max_expansions': 4096,
                    'max_results': 64}
DEFAULT_ALLOWANCE = {'max_requests': 64, 'max_bytes': 2 * 1024 * 1024, 'max_seconds': 900.0}
MESSAGES = {
    'retrieval_unavailable': 'no literature index is configured; existing knowledge queries are unchanged',
    'schema_violation': 'literature request violates the retrieval request schema',
    'provider_unqualified': 'the configured literature provider is not qualified for this operation and index',
    'stale_index': 'the literature index differs from the pinned index manifest; rebind before retrieval',
    'policy_changed': 'run source policy changed since this worker was bound; rebind the worker',
    'policy_unavailable': 'the run source policy view could not be established; nothing was served',
    'forbidden_source': 'literature request or result involves a source withheld by run policy {policy}',
    'budget_exceeded': 'literature request budgets exceed the serving ceilings',
    'budget_exhausted': 'literature serving allowance of this worker attempt is exhausted',
    'provider_failed': 'literature provider failed; nothing was served',
    'provider_schema_violation': 'literature provider returned a result outside the retrieval contract; nothing was served',
    'unauthenticated_evidence': 'literature result differs from the admitted index or current source bytes; nothing was served',
    'replay_unavailable': 'no delivered literature result with this serving identity can be replayed',
    'replay_mismatch': 'replayed literature results differ from the recorded located results',
    'output_failed': 'literature result could not be written; nothing was served',
}
TIMEOUT = 'literature retrieval exhausted its time budget; nothing was served'
_SERVING_ID = re.compile(r'\[(serving:[1-9][0-9]*)\]\Z')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _implementation(provider):
    return type(provider).__module__ + '.' + type(provider).__qualname__


def _descriptors(row):
    """The complete policy lineage of one paper or evidence row, as providers check it."""
    found = list(row['lineage'])
    for pin, kind in ((row['original'], 'source'), (row['extraction'], 'extracted')):
        if pin is not None:
            found.append({'pin': pin, 'identifiers': row['identifiers'], 'quantities': row['quantities'],
                          'classes': row['classes'], 'kind': kind})
    return found


def _identities(identifiers):
    """Identity values with their equivalent spellings and URL-derived record identities."""
    found = {}
    for key, values in identifiers.items() if isinstance(identifiers, dict) else ():
        for value in values if isinstance(values, list) else ():
            if not isinstance(value, str) or not value:
                continue
            found.setdefault(key, set()).add(value)
            if key == 'url':
                try:
                    derived = restriction_guard._url_ids(value)
                except ValueError:
                    derived = {}
                for name, ids in derived.items():
                    found.setdefault(name, set()).update(ids)
    spelled = restriction_guard.equivalent_identities({k: sorted(v) for k, v in found.items()})
    return {k: sorted(v) for k, v in spelled.items()}


def _merge(*maps):
    result = {}
    for ids in maps:
        for key, values in ids.items():
            result[key] = sorted(set(result.get(key, ())) | set(values))
    return result


def _literature_rows(rows):
    """Run policy rows as literature serving applies them.

    Identities include their equivalent spellings. A quantity-scoped ban that
    selects a source by identity or class withholds that whole document: no
    admitted partition shows its excerpts free of the scoped quantity.
    """
    result = []
    for row in deepcopy(rows):
        if row.get('identifiers'):
            row['identifiers'] = restriction_guard.equivalent_identities(row['identifiers'])
        if row.get('scope') and (any(row.get('identifiers', {}).values()) or row.get('classes')):
            row.pop('scope')
        result.append(row)
    return result


def _named(rows, values):
    """Whether a selector value names a restricted identity (of any kind) or an unlocated restricted class."""
    for row in rows:
        identities = row.get('identifiers', {})
        if any(identities.values()):
            spelled = _identities({key: list(values) for key in identities})
            if any(set(identities.get(key, ())) & set(found) for key, found in spelled.items()):
                return True
        elif row.get('classes') and set(row['classes']) & set(values):
            return True
    return False


def _located_fields(row):
    """Evidence content an index admits; ranking, grouping and provider row IDs are excluded."""
    return {key: value for key, value in row.items() if key not in ('id', 'scores', 'group_id')}


def _located(envelope):
    """The deterministic located envelope: everything except measured wall-clock time."""
    located = deepcopy(envelope)
    located['usage'] = {k: v for k, v in located['usage'].items() if k != 'elapsed_seconds'}
    return contract.canonical(located)


def _directory(path):
    path = core.ordinary(path)
    if not path.is_dir():
        raise ValueError('literature serving roots must be ordinary directories')
    return path


def _json_file(path):
    path = core.ordinary(path)
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError('literature index record is not an ordinary bounded file')
    return read_json(path)


def _pinned(root, pin, cache):
    """Current bytes of an admitted relative pin, opened without following any link."""
    key = (pin['path'], pin['sha256'], pin['size'])
    if key in cache:
        return cache[key]
    parts = pin['path'].split('/')
    if any(part in ('', '.', '..') for part in parts) or not 0 < pin['size'] <= contract.MAX_SOURCE_BYTES:
        raise ValueError('literature source pin is not an admitted relative path')
    directory = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(root, directory)
    try:
        for name in parts[:-1]:
            following = os.open(name, directory, dir_fd=fd)
            os.close(fd)
            fd = following
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)
    with os.fdopen(leaf, 'rb') as stream:
        observed = os.fstat(stream.fileno())
        if not stat.S_ISREG(observed.st_mode) or observed.st_size != pin['size']:
            raise ValueError('literature source differs from its pin')
        raw = stream.read(pin['size'] + 1)
    if len(raw) != pin['size'] or _sha(raw) != pin['sha256']:
        raise ValueError('literature source differs from its pin')
    cache[key] = raw
    return raw


def _pin_identities(snapshot):
    """Each admitted pin carries the identities of every paper containing it."""
    identities = {}
    for paper in snapshot['corpus']['papers']:
        descriptors = _descriptors(paper)
        union = _merge(*(_identities(d['identifiers']) for d in descriptors))
        for descriptor in descriptors:
            sha256 = descriptor['pin']['sha256']
            identities[sha256] = _merge(identities.get(sha256, {}), union)
    return identities


def _limits(value, defaults, *, integers, reals, highs):
    if value is not None and (not isinstance(value, dict) or set(value) - set(defaults)):
        raise ValueError('unknown literature serving limits')
    result = dict(defaults, **(value or {}))
    for key in integers:
        if type(result[key]) is not int or not 1 <= result[key] <= highs[key]:
            raise ValueError('invalid literature serving limit ' + key)
    for key in reals:
        if (type(result[key]) not in (int, float) or not math.isfinite(result[key])
                or not 0.001 <= result[key] <= highs[key]):
            raise ValueError('invalid literature serving limit ' + key)
        result[key] = float(result[key])
    return result


def _ceilings(value):
    return _limits(value, DEFAULT_CEILINGS, integers=('max_tokens', 'max_bytes', 'max_expansions', 'max_results'),
                   reals=('max_seconds',), highs={'max_tokens': contract.MAX_BYTES, 'max_bytes': contract.MAX_BYTES,
                                                  'max_expansions': 100000, 'max_results': 512, 'max_seconds': 300.0})


def _budgets(value, ceilings):
    if value is None:
        value = {key: min(default, ceilings[key]) for key, default in DEFAULT_BUDGETS.items()}
    result = contract._validate(value, 'budgets')
    if any(result[key] > ceilings[key] for key in result):
        raise ValueError('default literature budgets exceed the serving ceilings')
    return result


def _allowance(value):
    return _limits(value, DEFAULT_ALLOWANCE, integers=('max_requests', 'max_bytes'), reals=('max_seconds',),
                   highs={'max_requests': 100000, 'max_bytes': 1024 ** 4, 'max_seconds': 86400.0 * 30})


def _qualification(record):
    keys = {'schema_version', 'kind', 'provider_id', 'implementation', 'index', 'operations',
            'policy_scoped', 'evidence', 'qualification_sha256'}
    if not isinstance(record, dict) or set(record) not in (keys, keys | {'graph'}):
        raise ValueError('literature qualification record required')
    if 'graph' in record and (not isinstance(record['graph'], dict) or set(record['graph']) != set(GRAPH_PINS)
                              or not all(isinstance(v, str) and re.fullmatch(r'[0-9a-f]{64}', v)
                                         for v in record['graph'].values())):
        raise ValueError('invalid literature qualification graph pins')
    index, operations, evidence = record['index'], record['operations'], record['evidence']
    if (record['schema_version'] != 1 or type(record['schema_version']) is not int
            or record['kind'] != QUALIFICATION_KIND
            or not all(isinstance(record[k], str) and 0 < len(record[k]) <= 2048 for k in ('provider_id', 'implementation'))
            or not isinstance(index, dict) or set(index) != {'id', 'manifest_sha256'}
            or not isinstance(index['id'], str) or not index['id']
            or not isinstance(index['manifest_sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', index['manifest_sha256'])
            or not isinstance(operations, list) or not operations
            or operations != [op for op in contract.OPERATIONS if op in operations]
            or type(record['policy_scoped']) is not bool
            or not isinstance(evidence, list) or len(evidence) > 64
            or not all(isinstance(e, str) and 0 < len(e) <= 2048 for e in evidence)):
        raise ValueError('invalid literature qualification record')
    if core.digest({k: v for k, v in record.items() if k != 'qualification_sha256'}) != record['qualification_sha256']:
        raise ValueError('literature qualification record changed')
    return deepcopy(record)


def qualify(provider, snapshot, *, operations=contract.OPERATIONS, policy_scoped=True, evidence=()):
    """The trusted provisioning record of one provider over one admitted index.

    An installation writes it after the provider passes its conformance run; a
    worker can never supply or widen one. It binds the provider identity and
    implementation, the index manifest, the qualified operations and the
    provider's guarantee to apply the source view before ranking. A graph-guided
    profile is qualified only for its pinned graph generation, bindings and settings.
    """
    manifest = literature_build.validate_snapshot(snapshot)['manifest']
    record = {'schema_version': 1, 'kind': QUALIFICATION_KIND, 'provider_id': provider.provider_id,
              'implementation': _implementation(provider),
              'index': {'id': manifest['id'], 'manifest_sha256': manifest['manifest_sha256']},
              'operations': [op for op in contract.OPERATIONS if op in operations],
              'policy_scoped': policy_scoped, 'evidence': list(evidence)}
    if isinstance(provider, GraphGuidedProfile):
        record['graph'] = deepcopy(provider.pins)
    record['qualification_sha256'] = core.digest(record)
    return _qualification(record)


class Serving:
    """Trusted installation configuration for serving one admitted index.

    The dispatcher builds it from installation settings, never from worker
    arguments. ``snapshot`` is the admitted immutable index; its manifest is the
    pinned identity every request and replay must match. ``qualification`` is
    the record from ``qualify``. ``source_root`` holds the admitted original and
    extraction bytes that every served excerpt is checked against.
    ``index_root``, when given, is the build store whose current pointer must
    still name the pinned manifest. ``budgets`` are the defaults for requests
    that name none, ``ceilings`` bound one request and ``allowance`` bounds one
    worker attempt.
    """

    def __init__(self, provider, *, snapshot, qualification, source_root, index_root=None,
                 budgets=None, ceilings=None, allowance=None, excluded_origins=None):
        from .literature_index import normalize_excluded_origins
        self.provider = provider
        # Evaluator-supplied origins (trusted settings): withheld from every view and every served row.
        self.excluded_origins = normalize_excluded_origins(excluded_origins)
        self.snapshot = literature_build.validate_snapshot(snapshot)
        manifest = self.snapshot['manifest']
        self.index = {'id': manifest['id'], 'manifest_sha256': manifest['manifest_sha256']}
        self.qualification = deepcopy(qualification)
        self.source_root = _directory(source_root)
        self.index_root = None if index_root is None else _directory(index_root)
        self.ceilings = _ceilings(ceilings)
        self.budgets = _budgets(budgets, self.ceilings)
        self.allowance = _allowance(allowance)
        corpus = self.snapshot['corpus']
        self.papers = {(p['document_id'], p['version']): p for p in corpus['papers']}
        self.documents = {}
        for paper in corpus['papers']:
            self.documents.setdefault(paper['document_id'], []).append(paper)
        self.units = {(u['evidence']['document_id'], u['evidence']['version'], u['evidence']['unit_id']): u['evidence']
                      for u in corpus['units']}
        # A pin carries the identities of every admitted paper that contains it, so a
        # descriptor without its own identifiers is still judged as that paper.
        self.identities = _pin_identities(self.snapshot)
        # Every pin of a paper or unit that descends from an excluded origin (or is derived without
        # ancestry) is withheld from the view, so it never reaches ranking, statistics or counts.
        self.origin_pins = set()
        if self.excluded_origins:
            from .literature_index import excluded_origin, transformed_without_ancestry
            for row in [*corpus['papers'], *(u['evidence'] for u in corpus['units'])]:
                if excluded_origin(row, self.excluded_origins) or transformed_without_ancestry(row):
                    self.origin_pins.update(d['pin']['sha256'] for d in _descriptors(row))


GRAPH_PINS = ('graph_sha256', 'bindings_sha256', 'settings_sha256')
GRAPH_POLICY = ('policy_view_sha256', 'denials_sha256')
GRAPH_QUERIES = 'graph_queries'


class ProfileRefusal(ValueError):
    """A graph profile refusal carrying the serving code it maps to; nothing is searched instead."""

    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code


def _hex(value, what):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError(what + ' must be a pinned SHA-256 digest')
    return value


def _all_permitted(view, descriptors):
    try:
        values = [view.permits(deepcopy(d)) for d in descriptors]
    except Exception:
        return False
    return all(value is True for value in values)


def graph_denials(view, source_bindings, document_bindings):
    """Graph sources and graph items whose bound descriptors the source view withholds."""
    if not isinstance(view, contract.SourceView):
        raise ValueError('trusted source view required')
    sources = frozenset(b.source_id for b in source_bindings if not _all_permitted(view, b.descriptors))
    items = frozenset(b.node_id for b in document_bindings if not _all_permitted(view, b.descriptors))
    return sources, items


def _denials_sha256(sources, identifiers):
    return core.digest([sorted(sources), sorted(identifiers)])


class _Recorder:
    """The inner provider as the graph search sees it; keeps each served row's admitted lineage."""

    def __init__(self, provider):
        self.provider_id, self._provider, self.lineage = provider.provider_id, provider, {}

    def search(self, request, *, view):
        found = self._provider.search(request, view=view)
        for row in found.get('results', ()) if isinstance(found, dict) else ():
            if isinstance(row, dict) and isinstance(row.get('id'), str):
                self.lineage.setdefault(row['id'], deepcopy(row.get('lineage')))
        return found


class GraphGuidedProfile:
    """Qualified trusted search profile: graph-guided search behind the provider protocol.

    Built by ``graph_profile`` from trusted configuration only: the served index
    identity, the pinned graph generation and bindings digests, the source view
    the denial sets are derived from, and the profile settings. ``search``
    composes ``GraphGuidedSearch`` with the request's own budgets; the other
    operations stay on the inner provider unchanged. Served rows keep their
    admitted provider lineage, so the serving authentication is unchanged; the
    graph lineage that selected a row stays in the supervisor trace, which
    serving checks against the run view and records in custody. Every
    integrity, policy or budget failure is a refusal; nothing falls back to
    another search.
    """

    def __init__(self, provider, graph, *, index, graph_sha256, bindings_sha256, source_bindings,
                 document_bindings, view, denied_sources=frozenset(), denied_identifiers=frozenset(),
                 settings=None, clock=time.monotonic):
        if not isinstance(provider, contract.RetrievalProvider) or isinstance(provider, GraphGuidedProfile):
            raise ValueError('trusted inner retrieval provider required')
        if not isinstance(index, dict) or set(index) != {'id', 'manifest_sha256'} or not isinstance(index['id'], str):
            raise ValueError('served index identity required')
        _hex(index['manifest_sha256'], 'index manifest')
        if not isinstance(view, contract.SourceView):
            raise ValueError('trusted source view required')
        _hex(view.policy_sha256, 'policy view')
        for denied in (denied_sources, denied_identifiers):
            if type(denied) is not frozenset or any(type(k) is not str for k in denied):
                raise ValueError('explicit frozen denial set required')
        if (not all(isinstance(b, RetrievalSourceBinding) for b in source_bindings)
                or not all(isinstance(b, RetrievalDocumentBinding) for b in document_bindings)):
            raise ValueError('typed retrieval bindings required')
        self._inner, self._graph, self._recorder = provider, graph, _Recorder(provider)
        self._search = graph_retrieval.GraphGuidedSearch(
            self._recorder, graph, graph_sha256=_hex(graph_sha256, 'graph generation'),
            source_bindings=list(source_bindings), document_bindings=list(document_bindings),
            settings=settings, clock=clock)
        if self._search._bindings_sha256 != _hex(bindings_sha256, 'retrieval bindings'):
            raise ValueError('retrieval bindings differ from their pinned digest')
        derived_sources, derived_items = graph_denials(view, source_bindings, document_bindings)
        self.provider_id, self.inner_provider_id = self._search.provider_id, provider.provider_id
        self.index = deepcopy(index)
        self.source_bindings, self.document_bindings = tuple(source_bindings), tuple(document_bindings)
        self.denied_sources = frozenset(denied_sources | derived_sources)
        self.denied_identifiers = frozenset(denied_identifiers | derived_items)
        self.settings = graph_retrieval.normalize_settings(settings)
        self.pins = {'graph_sha256': graph_sha256, 'bindings_sha256': bindings_sha256,
                     'settings_sha256': core.digest(self.settings)}
        self.policy = {'policy_view_sha256': view.policy_sha256,
                       'denials_sha256': _denials_sha256(self.denied_sources, self.denied_identifiers)}
        self._lock = threading.Lock()

    def index_identity(self, view):
        identity = getattr(self._inner, 'index_identity', None)
        current = identity(view) if callable(identity) else None
        if not isinstance(current, dict) or any(current.get(k) != self.index[k] for k in self.index):
            raise ValueError('the inner provider does not serve the configured index')
        return {**self.index, 'policy_view_sha256': view.policy_sha256}

    def search_traced(self, request, *, view, queries=(), denied_sources=frozenset(),
                      denied_identifiers=frozenset()):
        """The graph-guided envelope and its supervisor trace, under at least the configured denials."""
        with self._lock:
            if self._graph.sha256 != self.pins['graph_sha256']:
                raise ProfileRefusal('stale_index', 'the graph generation differs from its pin')
            if not isinstance(view, contract.SourceView) or view.policy_sha256 != self.policy['policy_view_sha256']:
                raise ProfileRefusal('policy_changed', 'the source view differs from the profile view')
            try:
                index = self.index_identity(view)
            except Exception as exc:
                raise ProfileRefusal('stale_index', 'index identity: ' + type(exc).__name__) from None
            self._recorder.lineage = {}
            out = self._search.search(request, view=view, index=index, queries=[GraphQuery.from_dict(q) if
                                      isinstance(q, dict) else q for q in queries],
                                      denied_sources=frozenset(self.denied_sources | denied_sources),
                                      denied_identifiers=frozenset(self.denied_identifiers | denied_identifiers))
            envelope, trace = out['envelope'], out['trace']
            if trace['graph_sha256'] != self.pins['graph_sha256'] or trace['bindings_sha256'] != self.pins['bindings_sha256']:
                raise ProfileRefusal('stale_index', 'the graph search used another graph generation or bindings')
            graph_lineage = trace['graph']['lineage']
            for row in envelope['results']:
                admitted = self._recorder.lineage.get(row['id'])
                if (not isinstance(admitted, list) or row['lineage'][:len(admitted)] != admitted
                        or any(d not in graph_lineage for d in row['lineage'][len(admitted):])):
                    raise ValueError('graph-guided row lineage is not its provider lineage plus graph lineage')
                row['lineage'] = deepcopy(admitted)
            envelope = contract.validate_candidates(envelope, request, provider_id=self.provider_id, index=index)
            return {'envelope': envelope, 'trace': trace}

    def search(self, request, *, view, queries=()):
        return self.search_traced(request, view=view, queries=queries)['envelope']

    def get_paper(self, request, *, view):
        return self._inner.get_paper(request, view=view)

    def list_papers(self, request, *, view):
        return self._inner.list_papers(request, view=view)

    def compare_measurements(self, request, *, view):
        return self._inner.compare_measurements(request, view=view)


def graph_profile(provider, graph, *, index, graph_sha256, bindings_sha256, source_bindings, document_bindings,
                  view, denied_sources=frozenset(), denied_identifiers=frozenset(), settings=None,
                  clock=time.monotonic):
    """Trusted factory of the graph-guided search profile; never reachable from worker arguments.

    ``index`` is the served index identity (``id``, ``manifest_sha256``);
    ``graph_sha256`` and ``bindings_sha256`` are the pins the installation
    records with the index manifest; ``view`` is the run source view
    (``source_view``), from which the graph denial sets are derived and to which
    trusted extra denials are added. Qualify the result with ``qualify``.
    """
    return GraphGuidedProfile(provider, graph, index=index, graph_sha256=graph_sha256,
                              bindings_sha256=bindings_sha256, source_bindings=source_bindings,
                              document_bindings=document_bindings, view=view, denied_sources=denied_sources,
                              denied_identifiers=denied_identifiers, settings=settings, clock=clock)


def source_view(broker, snapshot):
    """The run source view a broker's literature handlers apply, for trusted profile configuration."""
    state = register(broker)
    snapshot = literature_build.validate_snapshot(snapshot)
    return state.view(node_id=broker.node_id, role=broker.role, attempt=broker.attempt,
                      identities=_pin_identities(snapshot))


def _graph_queries(value):
    if type(value) is not list or len(value) > graph_retrieval.MAX_QUERIES:
        raise ValueError('at most %d typed graph queries required' % graph_retrieval.MAX_QUERIES)
    return [graph_retrieval._query_record(GraphQuery.from_dict(q)) for q in value]


class ConfigurationRefusal:
    """A selected retrieval configuration that the trusted loader could not admit.

    ``from_settings`` returns it instead of silently changing engines or falling
    back to the unconfigured path: every literature call on a broker bound to it
    is a receipted refusal with ``code`` (``provider_unqualified`` or
    ``stale_index``); ``detail`` stays in supervisor custody.
    """

    def __init__(self, code, detail):
        if code not in ('provider_unqualified', 'stale_index'):
            raise ValueError('a configuration refusal is provider_unqualified or stale_index')
        self.code, self.detail = code, str(detail)[:1024]
        self.budgets = {key: min(default, DEFAULT_CEILINGS[key]) for key, default in DEFAULT_BUDGETS.items()}


def _qualification_problem(serving, op):
    try:
        record = _qualification(serving.qualification)
    except (ValueError, TypeError, KeyError):
        return 'qualification record is missing or invalid'
    provider = serving.provider
    if not isinstance(provider, contract.RetrievalProvider):
        return 'provider lacks the retrieval protocol'
    if record['provider_id'] != getattr(provider, 'provider_id', None):
        return 'provider identity differs from its qualification'
    if record['implementation'] != _implementation(provider):
        return 'provider implementation differs from its qualification'
    if record['index'] != serving.index:
        return 'qualification names another index manifest'
    if op not in record['operations']:
        return 'operation is not qualified'
    if record['policy_scoped'] is not True:
        return 'provider does not apply the source view before ranking'
    if isinstance(provider, GraphGuidedProfile) != ('graph' in record):
        return 'graph-guided qualification and provider profile differ'
    return None


def _index_problem(serving, view):
    identity = getattr(serving.provider, 'index_identity', None)
    if callable(identity):
        try:
            current = identity(view)
        except Exception:
            return 'provider index identity is unavailable'
        if not isinstance(current, dict) or any(current.get(k) != serving.index[k] for k in ('id', 'manifest_sha256')):
            return 'provider serves another index manifest'
    if isinstance(serving.provider, GraphGuidedProfile):
        if serving.provider.pins != serving.qualification.get('graph'):
            return 'the graph generation, bindings or settings differ from the qualified pins'
    if serving.index_root is not None:
        sha256 = serving.index['manifest_sha256']
        try:
            if _json_file(serving.index_root / 'current.json') != {'id': sha256}:
                return 'the installation index moved to another manifest'
            if _json_file(serving.index_root / 'snapshots' / sha256 / 'manifest.json') != serving.snapshot['manifest']:
                return 'the pinned manifest changed in the index store'
        except (OSError, ValueError):
            return 'the installation index store is unreadable'
    return None


def _ceiling_problem(ceilings, request):
    budgets, args, op = request['budgets'], request['args'], request['operation']
    for key in ('max_tokens', 'max_bytes', 'max_seconds', 'max_expansions'):
        if budgets[key] > ceilings[key]:
            return key
    count = (args['top_k'] if op == 'search' else args['limit'] if op in ('get_paper', 'list_papers')
             else len(args['groups']) * args['top_k_per_group'])
    return 'max_results' if count > ceilings['max_results'] else None


class _Binding:
    """The literature handlers of one source-bound broker."""

    def __init__(self, broker):
        self.broker = broker
        self.serving = None

    # ---- identity, custody and refusal

    def binding(self):
        broker = self.broker
        return {'run_id': knowledge_broker.run_id(broker.rundir), 'node_id': broker.node_id,
                'attempt': broker.attempt, 'role': broker.role}

    def policy_current(self):
        try:
            return knowledge_broker.policy_digest(self.broker.rundir) == self.broker.policy_sha256
        except (OSError, ValueError):
            return False

    def bound_view(self, base, *, node_id, role, attempt):
        try:
            return self.view(node_id=node_id, role=role, attempt=attempt)
        except (OSError, ValueError) as exc:
            self.deny('policy_unavailable', 'admission', base, type(exc).__name__)

    def append(self, record):
        return core.append_ledger(self.broker.rundir, LEDGER, {**record, 'utc': core.utc()})

    def deny(self, code, stage, base, detail, *, serving_id=None, message=None):
        """Receipt a denial in custody, then refuse; the broker adds its own refusal receipt."""
        record = {**base, 'event': 'denied', 'stage': stage, 'code': code, 'detail': detail}
        if serving_id is not None:
            record['serving_id'] = serving_id
        row = self.append(record)
        identity = serving_id or 'serving:%d' % row['n']
        text = (message or MESSAGES[code]).format(policy=self.broker.policy_sha256)
        raise core.Refusal(code, text + ' [' + identity + ']')

    # ---- the source view

    def view(self, *, node_id, role, attempt, identities=None):
        """Run policy as a provider view, applied before ranking, statistics, expansion and counts."""
        broker = self.broker
        identities = self.serving.identities if identities is None else identities
        rows = _literature_rows(broker.rows)
        located = [row for row in rows if any(row.get('identifiers', {}).values())]
        law = {'law': VIEW_LAW, 'source_restriction_sha256': broker.policy_sha256,
               'legacy': list(broker.legacy_patterns), 'withheld': sorted(broker.withheld_digests())}
        origins = getattr(self.serving, 'excluded_origins', ()) if self.serving is not None else ()
        if origins:
            from .literature_index import excluded_origins_sha256
            law['excluded_origins_sha256'] = excluded_origins_sha256(origins)
        digest = core.digest(law)
        memo = {}

        def permits(descriptor):
            try:
                key = contract.canonical(descriptor)
            except (TypeError, ValueError, RecursionError, OverflowError):
                return False
            if key not in memo:
                memo[key] = self._permits(descriptor, rows, located, identities)
            return memo[key]
        return contract.SourceView(policy_sha256=digest, run_id=knowledge_broker.run_id(broker.rundir),
                                   node_id=node_id, role=role, attempt=attempt, permits=permits)

    def _permits(self, descriptor, rows, located, identities):
        if (not isinstance(descriptor, dict) or set(descriptor) != {'pin', 'identifiers', 'quantities', 'classes', 'kind'}
                or not isinstance(descriptor['pin'], dict) or not isinstance(descriptor['identifiers'], dict)
                or not all(isinstance(descriptor[k], list) and all(isinstance(v, str) for v in descriptor[k])
                           for k in ('quantities', 'classes'))):
            return False
        pin = descriptor['pin']
        if not isinstance(pin.get('path'), str) or not isinstance(pin.get('sha256'), str):
            return False
        if any(fnmatchcase(pin['path'], pattern) for pattern in self.broker.legacy_patterns):
            return False
        ids = _merge(_identities(descriptor['identifiers']), identities.get(pin['sha256'], {}))
        origins = getattr(self.serving, 'excluded_origins', ()) if self.serving is not None else ()
        if origins:
            from .literature_index import excluded_origin
            if pin['sha256'] in self.serving.origin_pins or excluded_origin({'pin': pin, 'identifiers': ids}, origins):
                return False
        source = {'path': pin['path'], 'sha256': pin['sha256'], 'identifiers': ids,
                  'quantities': list(descriptor['quantities']), 'classes': list(descriptor['classes'])}
        try:
            # The broker law (rows, case-folded paths, content copies), then spelled whole-document rows.
            if self.broker.violations(source) or (rows and source_policy.matches(rows, source)):
                return False
        except (ValueError, TypeError):
            return False
        # A document recording none of an identity restriction's kinds cannot be
        # shown to be another source; it is withheld (fail closed).
        return all(any(ids.get(key) for key, values in row['identifiers'].items() if values) for row in located)

    def withheld_documents(self, view):
        return {paper['document_id'] for paper in self.serving.snapshot['corpus']['papers']
                if not all(view.permits(d) for d in _descriptors(paper))}

    # ---- admission

    def request(self, args, serving, base):
        op, inner = args.get('op'), args.get('args')
        if set(args) != {'op', 'args'} or op not in contract.OPERATIONS or not isinstance(inner, dict):
            self.deny('schema_violation', 'admission', base, 'literature calls take one operation and its arguments')
        inner = deepcopy(inner)
        budgets = inner.pop('budgets', None)
        budgets = deepcopy(serving.budgets) if budgets is None else budgets
        queries = inner.pop(GRAPH_QUERIES, None) if op == 'search' else None
        if queries is not None:
            # The serving layer's own closed field; the retrieval request schema is unchanged.
            if not isinstance(getattr(serving, 'provider', None), GraphGuidedProfile):
                self.deny('schema_violation', 'admission', base, 'typed graph queries need a qualified graph profile')
            try:
                queries = _graph_queries(queries)
            except (ValueError, TypeError):
                self.deny('schema_violation', 'admission', base, 'typed graph queries violate their closed fields')
        identity = [op, inner, budgets] if queries is None else [op, inner, budgets, queries]
        request = {'schema_version': contract.SCHEMA_VERSION, 'operation': op,
                   'request_id': 'literature:' + core.digest(identity), 'budgets': budgets, 'args': inner}
        try:
            return contract.validate_request(request), queries or []
        except (ValueError, TypeError):
            self.deny('schema_violation', 'admission', base, 'request violates the retrieval request schema')

    def graph_denials(self, profile, view):
        """Denials derived from the current view, plus graph items a restricted identity names."""
        sources, items = graph_denials(view, profile.source_bindings, profile.document_bindings)
        rows = _literature_rows(self.broker.rows)
        named = {b.node_id for b in profile.document_bindings if rows and _named(rows, [b.node_id])}
        return sources, items, frozenset(items | named)

    def _graph_problem(self, serving, request, queries, view):
        """A graph profile's policy, typed-query source and typed-query budget checks, in that order."""
        profile = serving.provider
        if not isinstance(profile, GraphGuidedProfile) or request['operation'] != 'search':
            return None
        if view.policy_sha256 != profile.policy['policy_view_sha256']:
            return 'policy_changed', 'the source view differs from the graph profile view'
        sources, items, denied = self.graph_denials(profile, view)
        if not (sources <= profile.denied_sources and items <= profile.denied_identifiers):
            return 'policy_changed', 'the graph denials differ from the graph profile configuration'
        rows, withheld = _literature_rows(self.broker.rows), self.withheld_documents(view)
        bound = {}
        for binding in profile.document_bindings:
            bound.setdefault(binding.node_id, set()).add(binding.document_id)
        for query in queries:
            name = query['identifier']
            if (name in denied or name in profile.denied_identifiers or name in withheld
                    or bound.get(name, set()) & withheld or (rows and _named(rows, [name]))):
                return 'forbidden_source', 'a typed graph query names a withheld source'
        budgets = request['budgets']
        if (sum(q['max_expansions'] for q in queries) > budgets['max_expansions']
                or any(q['max_bytes'] > min(budgets['max_bytes'], budgets['max_tokens']) for q in queries)):
            return 'budget_exceeded', 'typed graph queries exceed the request budgets'
        return None

    def _selector_problem(self, serving, request, view):
        op, args = request['operation'], request['args']
        rows = _literature_rows(self.broker.rows)
        filters = args.get('filters', {})
        named = [(s['document_id'], s['version']) for s in args.get('document_scope', [])]
        if op == 'get_paper':
            named.append((args['document_id'], args['version']))
        named += [(document, None) for document in filters.get('document_id', [])]
        for document, version in named:
            if rows and _named(rows, [document]):
                return 'a selector names a restricted identity'
            for paper in serving.documents.get(document, ()):
                if version in (None, paper['version']) and not all(view.permits(d) for d in _descriptors(paper)):
                    return 'a selector names a withheld document'
        values = [v for key, found in filters.items() if key not in ('document_id', 'version', 'acquisition_status')
                  for v in found]
        if op == 'compare_measurements':
            values += args['groups']
        if values and rows and _named(rows, values):
            return 'a selector names a restricted identity or class'
        return None

    def _allowance_problem(self, serving, request):
        binding = self.binding()
        opened, terminal = {}, {}
        for row in core.ledger(self.broker.rundir, LEDGER):
            record = row['record']
            if record['action'] != ACTION or record['binding'] != binding:
                continue
            if 'serving_id' in record:
                terminal.setdefault(record['serving_id'], []).append(record)
            elif record['event'] == 'admitted':
                opened['serving:%d' % row['n']] = record
        used = 0
        for identity, record in opened.items():
            events = terminal.get(identity, [])
            served = [e for e in events if e['event'] == 'served']
            # Served bytes are charged; an admission without an outcome keeps its reservation.
            used += sum(e['charge']['bytes'] for e in served) if served else (0 if events else record['charge']['bytes'])
        seconds = sum(record['charge']['seconds'] for record in opened.values())
        budgets, allowance = request['budgets'], serving.allowance
        if len(opened) >= allowance['max_requests']:
            return 'request count'
        if used + budgets['max_bytes'] > allowance['max_bytes']:
            return 'served bytes'
        if seconds + budgets['max_seconds'] > allowance['max_seconds'] * (1 + 1e-12):
            return 'retrieval seconds'
        return None

    def admit(self, serving, request, view, base, *, allowance, queries=()):
        """Every pre-dispatch check, in order; the first failure is receipted and refused."""
        op, args = request['operation'], request['args']
        graph = self._graph_problem(serving, request, queries, view)
        problem = _qualification_problem(serving, op)
        if problem:
            self.deny('provider_unqualified', 'admission', base, problem)
        problem = _index_problem(serving, view)
        if problem:
            self.deny('stale_index', 'admission', base, problem)
        if not self.policy_current():
            self.deny('policy_changed', 'admission', base, 'run policy differs from the bound policy')
        if graph and graph[0] == 'policy_changed':
            self.deny(*graph[:1], 'admission', base, graph[1])
        cursor = args.get('cursor')
        if cursor is not None:
            if any(cursor[key] != serving.index[key] for key in ('id', 'manifest_sha256')):
                self.deny('stale_index', 'admission', base, 'cursor belongs to another index manifest')
            if cursor['policy_view_sha256'] != view.policy_sha256:
                self.deny('policy_changed', 'admission', base, 'cursor belongs to another source view')
            if cursor['selector_sha256'] != contract.selector_digest(request):
                self.deny('schema_violation', 'admission', base, 'cursor belongs to other selectors')
        problem = self._selector_problem(serving, request, view)
        if problem:
            self.deny('forbidden_source', 'admission', base, problem)
        if graph and graph[0] == 'forbidden_source':
            self.deny('forbidden_source', 'admission', base, graph[1])
        problem = _ceiling_problem(serving.ceilings, request)
        if problem:
            self.deny('budget_exceeded', 'admission', base, 'request exceeds the serving ceiling ' + problem)
        if graph:
            self.deny(graph[0], 'admission', base, graph[1])
        if allowance:
            problem = self._allowance_problem(serving, request)
            if problem:
                self.deny('budget_exhausted', 'admission', base, 'allowance exhausted: ' + problem)

    # ---- retrieval and serving checks

    def _policy_problem(self, checked, view):
        origins = getattr(self.serving, 'excluded_origins', ()) if self.serving is not None else ()
        for row in [*checked['results'], *checked['metadata']]:
            if not all(view.permits(d) for d in _descriptors(row)):
                return 'served row ' + row['id'] + ' is withheld by the source view'
            if origins:
                from .literature_index import excluded_origin, transformed_without_ancestry
                if excluded_origin(row, origins):
                    return 'served row ' + row['id'] + ' descends from an excluded origin'
                if transformed_without_ancestry(row):
                    return 'served row ' + row['id'] + ' is derived without ancestry'
        names = [e for row in checked['results'] for path in row['scores']['graph_paths'] for e in path]
        names += [issue['id'] for issue in [*checked['omitted'], *checked['failures']]]
        prose = [i['reason'] for i in [*checked['omitted'], *checked['failures'], *checked['groups']] if i['reason']]
        if names or prose:
            withheld, rows = self.withheld_documents(view), _literature_rows(self.broker.rows)
            for name in names:
                if name in withheld or (rows and _named(rows, [name])):
                    return 'a graph path or issue names a withheld source'
            # Provider prose must not mention a withheld document or a restricted identity either.
            mentioned = withheld | {v for row in rows for found in row.get('identifiers', {}).values() for v in found}
            if any(name in text for text in prose for name in mentioned):
                return 'provider prose names a withheld source'
        return None

    def _authentication_problem(self, serving, checked):
        for row in checked['results']:
            stored = serving.units.get((row['document_id'], row['version'], row['unit_id']))
            if stored is None or _located_fields(row) != _located_fields(stored):
                return 'evidence ' + row['id'] + ' is not an admitted located unit'
        for row in checked['metadata']:
            stored = serving.papers.get((row['document_id'], row['version']))
            if stored is None or {k: v for k, v in row.items() if k != 'id'} != {k: v for k, v in stored.items() if k != 'id'}:
                return 'metadata ' + row['id'] + ' is not an admitted paper record'
        cache = {}
        try:
            for row in checked['results']:
                original = _pinned(serving.source_root, row['original'], cache)
                extraction = None if row['extraction'] is None else _pinned(serving.source_root, row['extraction'], cache)
                contract.verify_excerpt(row, original=original, extraction=extraction)
            for row in checked['metadata']:
                for pin in (row['original'], row['extraction']):
                    if pin is not None:
                        _pinned(serving.source_root, pin, cache)
        except (OSError, ValueError) as exc:
            return 'current source bytes do not support the served row: ' + type(exc).__name__
        return None

    def retrieve(self, serving, request, view, base, serving_id, *, queries=()):
        """Run the provider once, then check the complete envelope before anything is served."""
        op = request['operation']
        expected = {**serving.index, 'policy_view_sha256': view.policy_sha256}
        profile = serving.provider if isinstance(serving.provider, GraphGuidedProfile) else None
        provider_id, trace = serving.provider.provider_id, None
        if profile is not None and op != 'search':
            provider_id = profile.inner_provider_id
        try:
            if profile is not None and op == 'search':
                _, _, denied = self.graph_denials(profile, view)
                out = profile.search_traced(deepcopy(request), view=view, queries=deepcopy(queries),
                                            denied_identifiers=denied)
                candidate, trace = out['envelope'], out['trace']
            else:
                candidate = getattr(serving.provider, op)(deepcopy(request), view=view)
        except TimeoutError as exc:
            self.deny('budget_exhausted', 'retrieval', base, 'TimeoutError: ' + str(exc)[:512],
                      serving_id=serving_id, message=TIMEOUT)
        except ProfileRefusal as exc:
            self.deny(exc.code, 'retrieval', base, str(exc)[:512], serving_id=serving_id)
        except Exception as exc:
            self.deny('provider_failed', 'retrieval', base, type(exc).__name__ + ': ' + str(exc)[:512],
                      serving_id=serving_id)
        index = candidate.get('index') if isinstance(candidate, dict) else None
        named = [index.get(k) for k in ('id', 'manifest_sha256')] if isinstance(index, dict) else []
        if all(isinstance(v, str) for v in named) and named and named != [serving.index['id'], serving.index['manifest_sha256']]:
            self.deny('stale_index', 'serving', base, 'envelope names another index manifest', serving_id=serving_id)
        try:
            checked = contract.validate_candidates(candidate, request, provider_id=provider_id, index=expected)
        except Exception as exc:  # any failure to validate provider output is a contract violation
            self.deny('provider_schema_violation', 'serving', base, type(exc).__name__ + ': ' + str(exc)[:512],
                      serving_id=serving_id)
        if not self.policy_current():
            self.deny('policy_changed', 'serving', base, 'run policy changed during retrieval', serving_id=serving_id)
        problem = self._policy_problem(checked, view)
        if problem is None and trace is not None and not all(view.permits(d) for d in trace['graph']['lineage']):
            # The graph lineage that selected served rows stays in custody; it is policed all the same.
            problem = 'the graph lineage of the scope is withheld by the source view'
        if problem:
            self.deny('forbidden_source', 'serving', base, problem, serving_id=serving_id)
        problem = self._authentication_problem(serving, checked)
        if problem:
            self.deny('unauthenticated_evidence', 'serving', base, problem, serving_id=serving_id)
        custody = None if trace is None else {'graph': {**profile.pins, **profile.policy, 'trace': trace}}
        return checked, _located(checked), custody

    def deliver(self, serving, checked, raw, base, serving_id, *, event, extra=None, custody=None):
        """Record the served result in custody, then write its content-addressed bytes."""
        located_sha256 = _sha(raw)
        path = OUTPUTS + '/' + located_sha256 + '.json'
        try:
            self.broker._canonical(path, write=True)
        except core.Refusal:
            self.deny('forbidden_source', 'output', base, 'the result path is withheld by policy', serving_id=serving_id)
        self.append({**base, **(extra or {}), **(custody or {}), 'event': event, 'serving_id': serving_id,
                     'located_sha256': located_sha256, 'output': {'path': path, 'sha256': located_sha256},
                     'results': [{'id': r['id'], 'document_id': r['document_id'], 'version': r['version'],
                                  'unit_id': r['unit_id'], 'excerpt_sha256': r['excerpt_sha256'],
                                  'group_id': r['group_id'], 'scores': r['scores']} for r in checked['results']],
                     'metadata': [{'id': r['id'], 'document_id': r['document_id'], 'version': r['version'],
                                   'acquisition_status': r['acquisition_status']} for r in checked['metadata']],
                     'groups': checked['groups'], 'omitted': checked['omitted'], 'failures': checked['failures'],
                     'next_cursor': checked['next_cursor'] is not None, 'usage': checked['usage'],
                     'charge': {'bytes': len(raw)}})
        try:
            self.broker._write({'path': path, 'content': raw.decode('utf-8')})
        except Exception as exc:
            code = exc.code if isinstance(exc, core.Refusal) else 'output_failed'
            self.deny('output_failed', 'output', base, code, serving_id=serving_id)
        summary = {'serving_id': serving_id, 'located_sha256': located_sha256, 'path': path,
                   'operation': checked['operation'], 'results': len(checked['results']),
                   'metadata': len(checked['metadata']), 'groups': len(checked['groups']),
                   'next_cursor': checked['next_cursor'] is not None, **(extra or {})}
        return {'stdout': json.dumps(summary, sort_keys=True), 'output_paths': [path],
                'source': {'uri': 'ravel-literature://index/' + serving.index['manifest_sha256'],
                           'record_id': located_sha256}}

    # ---- the two trusted handlers

    def query(self, args):
        base = {'action': ACTION, 'binding': self.binding(), 'args_sha256': core.digest(args),
                'op': args.get('op') if isinstance(args.get('op'), str) else None}
        serving = self.serving
        if serving is None:
            self.deny('retrieval_unavailable', 'admission', base, 'no trusted serving configuration is bound')
        request, queries = self.request(args, serving, base)
        if isinstance(serving, ConfigurationRefusal):
            self.deny(serving.code, 'admission', base, serving.detail)
        broker = self.broker
        view = self.bound_view(base, node_id=broker.node_id, role=broker.role, attempt=broker.attempt)
        base.update(op=request['operation'], request_sha256=core.digest(request), policy_view_sha256=view.policy_sha256)
        self.admit(serving, request, view, base, allowance=True, queries=queries)
        opened = self.append({**base, 'event': 'admitted', 'request': request, 'index': serving.index,
                              'provider_id': serving.provider.provider_id,
                              'qualification_sha256': serving.qualification['qualification_sha256'],
                              **_graph_admission(serving, request, queries),
                              'charge': {'bytes': request['budgets']['max_bytes'],
                                         'seconds': request['budgets']['max_seconds']}})
        serving_id = 'serving:%d' % opened['n']
        checked, raw, custody = self.retrieve(serving, request, view, base, serving_id, queries=queries)
        return self.deliver(serving, checked, raw, base, serving_id, event='served', custody=custody)

    def replay(self, args):
        """Re-run a delivered request under its recorded binding; its located bytes must be reproduced."""
        base = {'action': REPLAY_ACTION, 'binding': self.binding(), 'args_sha256': core.digest(args), 'op': None}
        serving = self.serving
        if serving is None:
            self.deny('retrieval_unavailable', 'admission', base, 'no trusted serving configuration is bound')
        if set(args) != {'serving_id'} or not isinstance(args['serving_id'], str):
            self.deny('schema_violation', 'admission', base, 'replay takes one serving identity')
        if isinstance(serving, ConfigurationRefusal):
            self.deny(serving.code, 'admission', base, serving.detail)
        wanted, run = args['serving_id'], knowledge_broker.run_id(self.broker.rundir)
        admitted, outcomes = None, []
        for row in core.ledger(self.broker.rundir, LEDGER):
            record = row['record']
            if record['action'] != ACTION or record['binding']['run_id'] != run:
                continue
            if 'serving_id' not in record and record['event'] == 'admitted' and 'serving:%d' % row['n'] == wanted:
                admitted = record
            elif record.get('serving_id') == wanted:
                outcomes.append(record)
        base['replay_of'] = wanted
        if admitted is None or [o['event'] for o in outcomes] != ['served']:
            self.deny('replay_unavailable', 'admission', base, 'no single delivered result has this identity')
        original, request, recorded = outcomes[0], admitted['request'], admitted['binding']
        view = self.bound_view(base, node_id=recorded['node_id'], role=recorded['role'], attempt=recorded['attempt'])
        base.update(op=request['operation'], request_sha256=core.digest(request), policy_view_sha256=view.policy_sha256,
                    recorded_binding=recorded)
        if admitted['index'] != serving.index:
            self.deny('stale_index', 'admission', base, 'the recorded result used another index manifest')
        current = serving.qualification.get('qualification_sha256') if isinstance(serving.qualification, dict) else None
        if admitted['qualification_sha256'] != current:
            self.deny('provider_unqualified', 'admission', base, 'the recorded result used another qualification')
        if admitted['policy_view_sha256'] != view.policy_sha256:
            self.deny('policy_changed', 'admission', base, 'the recorded result used another source view')
        recorded_graph = admitted.get('graph')
        current_graph = _graph_admission(serving, request, (recorded_graph or {}).get('queries', [])).get('graph')
        if recorded_graph != current_graph:
            # Replay pins the graph generation, bindings, settings, profile view and denials it recorded.
            changed = [k for k in GRAPH_PINS if (recorded_graph or {}).get(k) != (current_graph or {}).get(k)]
            code = 'stale_index' if changed or not recorded_graph or not current_graph else 'policy_changed'
            self.deny(code, 'admission', base, 'the recorded result used another graph profile configuration')
        queries = (recorded_graph or {}).get('queries', [])
        self.admit(serving, request, view, base, allowance=False, queries=queries)
        opened = self.append({**base, 'event': 'admitted', 'request': request, 'index': serving.index,
                              'provider_id': serving.provider.provider_id,
                              'qualification_sha256': serving.qualification['qualification_sha256'],
                              **_graph_admission(serving, request, queries),
                              'charge': {'bytes': request['budgets']['max_bytes'],
                                         'seconds': request['budgets']['max_seconds']}})
        serving_id = 'serving:%d' % opened['n']
        checked, raw, custody = self.retrieve(serving, request, view, base, serving_id, queries=queries)
        if _sha(raw) != original['located_sha256']:
            self.deny('replay_mismatch', 'replay', {**base, 'reproduced_sha256': _sha(raw)},
                      'located bytes differ from ' + original['located_sha256'], serving_id=serving_id)
        return self.deliver(serving, checked, raw, base, serving_id, event='replayed',
                            extra={'replay_of': wanted, 'reproduced': True}, custody=custody)


def _graph_admission(serving, request, queries):
    """The graph pins an admitted search records for its replay; empty for other providers."""
    profile = serving.provider
    if not isinstance(profile, GraphGuidedProfile) or request['operation'] != 'search':
        return {}
    return {'graph': {**profile.pins, **profile.policy, 'queries': deepcopy(list(queries))}}


def register(broker, serving=None):
    """Trusted seam: install the literature handlers on a source-bound broker.

    The handlers are installed once per broker; ``serving`` binds that
    broker's configuration once and is never taken from a call argument.
    Unbound handlers refuse every call with a receipt.
    """
    if not isinstance(broker, knowledge_broker.SourceBoundBroker):
        raise ValueError('literature serving requires a source-bound broker')
    if serving is not None and not isinstance(serving, (Serving, ConfigurationRefusal)):
        raise ValueError('literature serving requires a trusted Serving configuration')
    state = getattr(broker, '_literature_serving', None)
    if state is None:
        if ACTION in broker.actions or REPLAY_ACTION in broker.actions:
            raise ValueError('literature actions must be registered by their trusted adapter')
        state = _Binding(broker)
        broker.register(ACTION, state.query, derivation='retrieval', read_only=True)
        broker.register(REPLAY_ACTION, state.replay, derivation='retrieval', read_only=True)
        broker._literature_serving = state
    if serving is not None:
        if state.serving is not None and state.serving is not serving:
            raise ValueError('literature serving is already bound for this broker')
        state.serving = serving
    return state


def _dispatch(broker, action, args, call_id):
    if getattr(broker, '_literature_serving', None) is None:
        raise ValueError('literature serving is not registered on this broker')
    granted = action in broker.allowed_actions
    broker.allowed_actions.add(action)
    try:
        if call_id is None:
            call_id = 'lit-' + str(len(broker.verify_ledger()) + 1) + '-' + core.digest([action, args])[:24]
        return broker.call({'call_id': call_id, 'action': action, 'args': args})
    finally:
        if not granted:
            broker.allowed_actions.discard(action)


def call(broker, op, args, *, call_id=None):
    """Dispatcher seam for the CLI and role-bundle builders: the worker tools' action and receipts."""
    return _dispatch(broker, ACTION, {'op': op, 'args': deepcopy(args)}, call_id)


def replay(broker, serving_id, *, call_id=None):
    """Dispatcher-only replay of a delivered result; workers' toolbelts never offer it."""
    return _dispatch(broker, REPLAY_ACTION, {'serving_id': serving_id}, call_id)


def _receipt(rundir, reply):
    wanted = reply.get('receipt_id') if isinstance(reply, dict) else None
    for row in core.ledger(rundir, 'broker') if isinstance(wanted, str) else ():
        record = row['record']
        if not wanted.startswith(f"{record['node_id']}/{record['attempt']}/"):
            continue
        receipt = core.verify_broker_receipt(rundir, {'path': record['path'], 'sha256': record['sha256']},
                                             verify_outputs=False)
        if receipt['receipt_id'] == wanted:
            if receipt['reply'] == reply:
                return receipt
            break
    raise ValueError('literature reply has no matching broker receipt in custody')


def load(rundir, reply):
    """Located bytes of a delivered reply, checked against its broker receipt and output pin."""
    if not isinstance(reply, dict) or reply.get('status') != 'ok' or len(reply.get('outputs') or []) != 1:
        raise ValueError('a delivered literature reply has exactly one output')
    receipt = _receipt(rundir, reply)
    if receipt['action'] not in (ACTION, REPLAY_ACTION) or receipt['output_pins'] != reply['outputs']:
        raise ValueError('reply is not a delivered literature result')
    raw = core.locate(rundir, reply['outputs'][0]['path']).read_bytes()
    if _sha(raw) != reply['outputs'][0]['sha256']:
        raise ValueError('literature output changed after custody')
    return raw


def _reply_serving_id(reply):
    if reply.get('status') == 'ok':
        try:
            return json.loads(reply.get('stdout_tail') or '{}').get('serving_id')
        except ValueError:
            return None
    match = _SERVING_ID.search(((reply.get('error') or {}).get('message')) or '')
    return match[1] if match else None


def audit(rundir):
    """Census of every literature broker call and serving decision of one run (supervisor use).

    A call is delivered only when custody records it served, nothing withdrew
    it and an ok broker receipt names it. Broker-level refusals (budget, stop,
    allowlist, guard) never reach a handler and are listed separately, as are
    broker receipts that no longer verify (for example a removed workspace).
    """
    calls = {}
    rows = core.ledger(rundir, LEDGER)
    for row in rows:
        record = row['record']
        identity = record.get('serving_id', 'serving:%d' % row['n'])
        entry = calls.setdefault(identity, {'serving_id': identity, 'action': record['action'], 'op': record.get('op'),
                                            'binding': record['binding'], 'replay_of': record.get('replay_of'),
                                            'events': [], 'receipts': []})
        entry['events'].append({'n': row['n'], 'event': record['event'], 'stage': record.get('stage'),
                                'code': record.get('code'), 'located_sha256': record.get('located_sha256')})
    broker_only, unverified = [], []
    for row in core.ledger(rundir, 'broker'):
        record = row['record']
        try:
            receipt = core.verify_broker_receipt(rundir, {'path': record['path'], 'sha256': record['sha256']},
                                                 verify_outputs=False)
        except (OSError, ValueError):
            unverified.append({'path': record['path'], 'sha256': record['sha256']})
            continue
        if receipt['action'] not in (ACTION, REPLAY_ACTION):
            continue
        reply = receipt['reply']
        summary = {'receipt_id': receipt['receipt_id'], 'status': receipt['status'],
                   'code': (reply.get('error') or {}).get('code')}
        identity = _reply_serving_id(reply)
        if identity in calls:
            calls[identity]['receipts'].append(summary)
        else:
            broker_only.append({**summary, 'action': receipt['action']})
    for entry in calls.values():
        last = entry['events'][-1]['event']
        if last in ('served', 'replayed') and any(r['status'] == 'ok' for r in entry['receipts']):
            entry['outcome'] = 'delivered'
        else:
            entry['outcome'] = 'denied' if last == 'denied' else 'unresolved'
    return {'schema_version': 1, 'kind': 'literature-serving-audit', 'ledger_rows': len(rows),
            'calls': list(calls.values()), 'broker_only': broker_only, 'unverified_receipts': unverified}


def served_ids(rundir, *, node_id, attempt):
    """Evidence and metadata IDs delivered to one worker attempt."""
    run, delivered, withdrawn = knowledge_broker.run_id(rundir), {}, set()
    for row in core.ledger(rundir, LEDGER):
        record = row['record']
        binding = record['binding']
        if (record['action'] != ACTION or binding['run_id'] != run or binding['node_id'] != node_id
                or binding['attempt'] != attempt):
            continue
        if record['event'] == 'served':
            delivered[record['serving_id']] = record
        elif record['event'] == 'denied' and record.get('stage') == 'output':
            withdrawn.add(record['serving_id'])
    return {r['id'] for identity, record in delivered.items() if identity not in withdrawn
            for r in [*record['results'], *record['metadata']]}


def check_citations(rundir, cited, *, node_id, attempt):
    """Refuse a final record that cites literature evidence never served to its attempt."""
    unknown = sorted(set(cited) - served_ids(rundir, node_id=node_id, attempt=attempt))
    if unknown:
        raise ValueError('literature citations name evidence never served to this attempt: ' + ', '.join(unknown[:8]))
    return sorted(set(cited))


def tool_schema(op):
    """Worker-facing arguments of one operation: its retrieval.json arguments plus optional budgets."""
    schema = json.loads(files('ravel.data').joinpath('knowledge/schema/retrieval.json').read_text())
    args = deepcopy(schema['$defs'][op + '_args'])
    args['properties']['budgets'] = {'$ref': '#/$defs/budgets'}
    return {**args, '$defs': schema['$defs']}


def tools(row):
    """Toolbelt rows for the four operations, on the given atlas row (the shape ``toolbelt.build`` emits)."""
    from . import toolbelt
    return [toolbelt._tool(TOOL_NAMES[op], row, lead=f'Retrieve located literature candidates ({op}).',
                           args_schema=tool_schema(op), action=ACTION, fixed_args={'op': op},
                           args_key=toolbelt.KNOWLEDGE_ARGS_KEY, derivation='retrieval')
            for op in contract.OPERATIONS]


COMMANDS = {'search': 'search', 'get-paper': 'get_paper', 'list-papers': 'list_papers',
            'compare-measurements': 'compare_measurements'}


def _request_file(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > contract.MAX_BYTES:
        raise ValueError('literature request must be a bounded JSON file')
    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError('literature request must be a JSON object of operation arguments')
    return value


def main(argv=None, *, serving=None):
    """``ravel literature <operation>``: the same broker action and receipts as worker tools.

    The trusted caller supplies ``serving`` from installation settings; without
    it every retrieval is a receipted ``retrieval_unavailable`` refusal.
    """
    ap = argparse.ArgumentParser(prog='ravel literature', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = ap.add_subparsers(dest='command', required=True)
    for name in (*COMMANDS, 'replay'):
        sub = commands.add_parser(name)
        sub.add_argument('--rundir', type=Path, required=True)
        sub.add_argument('--workspace', type=Path,
                         help='broker workspace (default: the run work root for --node and --attempt)')
        sub.add_argument('--role', default='literature-scout')
        sub.add_argument('--node', default='literature')
        sub.add_argument('--attempt', type=int, default=1)
        sub.add_argument('--max-calls', type=int, default=80)
        if name == 'replay':
            sub.add_argument('--serving-id', required=True)
        else:
            sub.add_argument('--request', type=Path, required=True,
                             help='JSON object of operation arguments, optionally with budgets')
    commands.add_parser('audit').add_argument('--rundir', type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        if args.command == 'audit':
            print(json.dumps(audit(args.rundir), indent=2, sort_keys=True))
            return 0
        workspace = args.workspace or core.work_root(args.rundir) / args.node / str(args.attempt)
        workspace.mkdir(parents=True, exist_ok=True)
        tool = knowledge_broker.create(args.rundir, workspace, role=args.role, node_id=args.node,
                                       attempt=args.attempt, allowed_actions=[], max_calls=args.max_calls)
        register(tool, serving)
        reply = (replay(tool, args.serving_id) if args.command == 'replay'
                 else call(tool, COMMANDS[args.command], _request_file(args.request)))
        if reply['status'] != 'ok':
            print(json.dumps(reply, sort_keys=True))
            return 2
        sys.stdout.write(load(args.rundir, reply).decode('utf-8') + '\n')
        return 0
    except (OSError, ValueError) as exc:
        print(f'ravel literature: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
