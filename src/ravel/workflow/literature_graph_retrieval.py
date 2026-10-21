"""Graph-scoped literature search with a reserved, recorded rescue search.

Typed exact-identifier graph queries select candidate documents. The installed
provider ranks inside that scope, and a rescue search covers the permitted view
outside it. Both searches receive the broker's source view, so restrictions
apply before graph traversal, ranking and counts. Missing graph metadata cannot
be observed from scoped results, so every search holds back a share of its
budgets for the rescue. Graph paths explain navigation; they are not evidence.
This module performs no acquisition, model-service call or scientific inference.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import math
import time

from . import literature_provider as contract
from .literature_relations import GraphQuery, LiteratureGraph, scope_retrieval

KIND = 'literature-graph-guided-search'
MAX_QUERIES = 8
MAX_LINEAGE = 64
TRIGGERS = ('reserved', 'graph_unavailable', 'graph_budget', 'scope_truncated',
            'lineage_overflow', 'scoped_underfilled', 'scoped_budget', 'scoped_timeout')
FLAGS = {'physics_verified': False, 'execution_authorized': False}


def _digest(value):
    return hashlib.sha256(contract.canonical(value)).hexdigest()


def normalize_settings(settings=None):
    """Trusted profile values; the rescue reserve can be resized, never removed.

    ``always`` runs the rescue in its reserve on every search. ``insufficient``
    runs it only on an observable trigger: no permitted graph scope, an
    incomplete or overflowing scope, or a scoped search that timed out, was
    budget-limited or returned fewer rows than requested. Either way the
    scoped search cannot spend the reserved expansions and time. A one-result
    search has no reserved slot.
    """
    defaults = dict(rescue_fraction=0.25, rescue_trigger='always', max_paths_per_result=4)
    if settings is not None:
        if not isinstance(settings, dict) or set(settings) - set(defaults):
            raise ValueError('unknown graph retrieval settings')
        defaults.update(settings)
    fraction, paths = defaults['rescue_fraction'], defaults['max_paths_per_result']
    if (type(fraction) not in (int, float) or not math.isfinite(fraction) or not 0 < fraction <= 0.5
            or defaults['rescue_trigger'] not in ('always', 'insufficient')
            or type(paths) is not int or not 1 <= paths <= 64):
        raise ValueError('invalid graph retrieval settings')
    defaults['rescue_fraction'] = float(fraction)
    return defaults


def rescue_slots(top_k, fraction):
    """Result slots the rescue keeps whenever it runs; one slot stays with the scope."""
    return 0 if top_k < 2 else min(top_k - 1, max(1, math.floor(top_k * fraction)))


def _queries(queries):
    if type(queries) not in (list, tuple) or len(queries) > MAX_QUERIES:
        raise ValueError('bounded typed graph query list required')
    result = []
    for query in queries:
        if type(query) is dict:
            query = GraphQuery.from_dict(query)
        if not isinstance(query, GraphQuery):
            raise ValueError('typed graph queries required; query languages are unsupported')
        query.validate()
        if query not in result:
            result.append(query)
    return result


def _query_record(query):
    return dict(asdict(query), relation_types=list(query.relation_types))


def _issue(code, ident, reason):
    return dict(code=code, id=ident, reason=reason)


def _phase_issues(phase, issues):
    # Provider issues stay visible, labelled by the search that reported them.
    out = []
    for issue in issues:
        ident = phase + ':' + issue['id']
        out.append(dict(issue, id=ident if len(ident) <= 2048 else phase + ':' + _digest(issue['id'])))
    return out


def _unique(rows):
    seen, out = set(), []
    for row in rows:
        key = contract.canonical(row)
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def _descriptors(row):
    # The provider's projection law: complete lineage plus the row's own pins.
    rows = list(row['lineage'])
    for pin, kind in ((row['original'], 'source'), (row['extraction'], 'extracted')):
        if pin is not None:
            rows.append(dict(pin=pin, identifiers=row['identifiers'], quantities=row['quantities'],
                             classes=row['classes'], kind=kind))
    return rows


def _permitted(view, descriptors):
    try:
        values = [view.permits(deepcopy(row)) for row in descriptors]
    except Exception:
        raise ValueError('retrieval source policy evaluation failed') from None
    if any(type(value) is not bool for value in values):
        raise ValueError('retrieval source policy must return explicit booleans')
    return all(values)


def _span(row):
    loc = row['location']
    return (row['document_id'], row['version'], row['excerpt_sha256'], loc['space'],
            loc['page_index'], loc['byte_start'], loc['byte_end'])


def _content(row):
    return deepcopy({key: value for key, value in row.items() if key != 'scores'})


def _subrequest(request, phase, scope, top_k, expansions, seconds):
    # Sub-envelopes are internal. The caller's byte and token caps, and the
    # rescue share within them, bind the served envelope instead.
    sub = deepcopy(request)
    sub['request_id'] = 'graph-guided:' + phase + ':' + _digest([request['request_id'], phase])
    sub['args'].update(document_scope=deepcopy(scope), top_k=top_k)
    sub['budgets'].update(max_expansions=expansions, max_seconds=seconds,
                          max_bytes=contract.MAX_BYTES, max_tokens=contract.MAX_BYTES)
    return contract.validate_request(sub)


class GraphGuidedSearch:
    """Search over one trusted provider within one pinned graph generation.

    Provider, graph pin, bindings and settings are trusted configuration; a
    request cannot select them. ``search`` returns ``envelope``, a validated
    search candidate for the composed provider ID and the provider's admitted
    index, and ``trace``, the supervisor record of graph scope, allocations,
    rescue triggers and the origin of every served row. Scoped rows carry their
    graph paths and graph lineage; rescue rows carry no graph paths. Provider
    integrity and policy errors propagate; only a scoped-search timeout passes
    to the rescue, whose time the scoped search cannot spend.
    """

    def __init__(self, provider, graph, *, graph_sha256, source_bindings, document_bindings,
                 settings=None, clock=time.monotonic):
        inner = getattr(provider, 'provider_id', None)
        if (type(inner) is not str or not 0 < len(inner) <= 2000
                or not callable(getattr(provider, 'search', None))):
            raise ValueError('trusted retrieval provider required')
        if not isinstance(graph, LiteratureGraph) or graph.sha256 != graph_sha256:
            raise ValueError('graph differs from the pinned generation')
        if type(source_bindings) not in (list, tuple) or type(document_bindings) not in (list, tuple):
            raise ValueError('explicit retrieval bindings required')
        self._provider, self._graph, self._clock = provider, graph, clock
        self._sources, self._documents = list(source_bindings), list(document_bindings)
        # Bindings shape the scope, so replay pins them alongside the graph.
        try:
            self._bindings_sha256 = _digest([[asdict(b) for b in self._sources],
                                             [asdict(b) for b in self._documents]])
        except (TypeError, ValueError):
            raise ValueError('explicit retrieval bindings required') from None
        self._settings = normalize_settings(settings)
        self.inner_provider_id = inner
        self.provider_id = 'graph-guided/' + inner

    def _search(self, sub, view, index):
        found = contract.validate_candidates(self._provider.search(sub, view=view), sub,
                                             provider_id=self.inner_provider_id, index=index)
        if found['metadata']:
            # Provisional search metadata has no slot rule here; refuse, never drop.
            raise ValueError('graph-guided search requires evidence-only provider results')
        return found

    def search(self, request, *, view, index, queries=(), denied_sources=frozenset(),
               denied_identifiers=frozenset()):
        start = self._clock()
        request = contract.validate_request(request)
        if request['operation'] != 'search':
            raise ValueError('graph-guided retrieval is defined only for search')
        index = contract._validate(index, 'index')
        if not isinstance(view, contract.SourceView) or index['policy_view_sha256'] != view.policy_sha256:
            raise ValueError('retrieval policy view changed')
        for policy in (denied_sources, denied_identifiers):
            if type(policy) is not frozenset or any(type(k) is not str for k in policy):
                raise ValueError('explicit frozen denial set required')
        queries = _queries(queries)
        settings, budgets, args = self._settings, request['budgets'], request['args']
        fraction, policy, top_k = settings['rescue_fraction'], settings['rescue_trigger'], args['top_k']
        caller, reserved = args['document_scope'], rescue_slots(top_k, fraction)
        # Graph traversal and the scoped search never spend the rescue reserve.
        reserve_expansions = math.ceil(budgets['max_expansions'] * fraction)
        scope_expansions = budgets['max_expansions'] - reserve_expansions
        scope_deadline = budgets['max_seconds'] * (1 - fraction)

        def elapsed():
            return max(0.0, self._clock() - start)

        def remaining(deadline):
            return deadline - elapsed()
        receipt = 'graph-guided:' + _digest([request, index, self._graph.sha256, self._bindings_sha256,
                                             sorted(denied_sources), sorted(denied_identifiers),
                                             [_query_record(q) for q in queries], settings,
                                             view.run_id, view.node_id, view.role, view.attempt])
        used, triggers, omitted, failures = 0, [], [], []

        graph_rows, matches, graph_start = [], {}, elapsed()
        for query in queries:
            left, wall = scope_expansions - used, remaining(scope_deadline)
            row = dict(query=_query_record(query), status='budget_exhausted', truncated=True,
                       expansions=0, documents=0)
            graph_rows.append(row)
            if left < 1 or wall < 0.001:
                continue
            sub = deepcopy(request)
            # The scope record is internal too; each typed query keeps its own byte bound.
            sub['budgets'].update(max_expansions=left, max_seconds=wall,
                                  max_bytes=contract.MAX_BYTES, max_tokens=contract.MAX_BYTES)
            scoped = scope_retrieval(self._graph, query, sub, view=view, source_bindings=self._sources,
                                     document_bindings=self._documents, denied_sources=denied_sources,
                                     denied_identifiers=denied_identifiers)
            used += scoped['usage']['expansions']
            row.update(status=scoped['status'], truncated=scoped['truncated'],
                       expansions=scoped['usage']['expansions'], documents=len(scoped['document_scope']))
            for match in scoped['matches']:
                entry = matches.setdefault((match['document_id'], match['version']),
                                           dict(graph_paths=[], lineage=[]))
                for field in ('graph_paths', 'lineage'):
                    for item in match[field]:
                        if item not in entry[field]:
                            entry[field].append(deepcopy(item))
        graph_usage = dict(expansions=used, elapsed_seconds=elapsed() - graph_start)
        keys = sorted(matches)
        truncated = len(keys) > 512 or any(r['truncated'] for r in graph_rows if r['status'] != 'budget_exhausted')
        keys = keys[:512]
        scope, in_scope = [dict(document_id=d, version=v) for d, v in keys], set(keys)
        scope_lineage = _unique(d for key in keys for d in matches[key]['lineage'])
        graph_budget = any(r['status'] == 'budget_exhausted' for r in graph_rows)
        graph_status = ('not_requested' if not queries else 'matched' if scope
                        else 'budget_exhausted' if graph_budget else 'unmatched')
        if not scope:
            triggers.append('graph_unavailable')
            omitted.append(_issue('missing', 'graph-scope', 'No graph query was supplied; results come from the rescue search.'
                                  if not queries else 'No permitted graph-bound document matched; results come from the rescue search.'))
        if graph_budget:
            triggers.append('graph_budget')
        if truncated:
            triggers.append('scope_truncated')
        if graph_budget or truncated:
            omitted.append(_issue('budget', 'graph-scope', 'The graph scope is incomplete within its budgets; '
                                  'the rescue search covers the permitted view outside it.'))

        scoped_rows, originals = [], {}
        phase = dict(status='not_run', request_id=None, receipt_id=None, expansion_cap=0, expansions=0,
                     elapsed_seconds=0.0, returned=0, lineage_overflow=0, served=0)
        if scope:
            left, wall = scope_expansions - used, remaining(scope_deadline)
            phase.update(status='budget_exhausted', expansion_cap=max(0, left))
            if left < 1 or wall < 0.001:
                triggers.append('scoped_budget')
                omitted.append(_issue('budget', 'scope', 'The graph-scoped search could not run within its allocation.'))
            else:
                sub = _subrequest(request, 'scope', scope, top_k, left, wall)
                phase['request_id'], phase_start = sub['request_id'], elapsed()
                try:
                    found = self._search(sub, view, index)
                except TimeoutError:
                    # An interrupted search may have spent its whole allocation.
                    used += left
                    phase.update(status='timeout', expansions=left, elapsed_seconds=elapsed() - phase_start)
                    triggers.append('scoped_timeout')
                    failures.append(_issue('timeout', 'scope', 'The graph-scoped search exhausted its time '
                                           'allocation; the rescue search used its reserve.'))
                else:
                    used += found['usage']['expansions']
                    omitted += _phase_issues('scope', found['omitted'])
                    failures += _phase_issues('scope', found['failures'])
                    phase.update(status='completed', receipt_id=found['receipt_id'], returned=len(found['results']),
                                 expansions=found['usage']['expansions'], elapsed_seconds=elapsed() - phase_start)
                    if any(issue['code'] == 'budget' for issue in found['omitted']):
                        triggers.append('scoped_budget')
                    for row in found['results']:
                        originals[row['id']] = _content(row)
                        match = matches[(row['document_id'], row['version'])]
                        lineage = row['lineage'] + [d for d in match['lineage'] if d not in row['lineage']]
                        if len(lineage) > MAX_LINEAGE:
                            # Complete lineage is never truncated; the rescue may still serve the row.
                            phase['lineage_overflow'] += 1
                            continue
                        row['lineage'] = lineage
                        row['scores']['graph_paths'] = sorted(match['graph_paths'], key=lambda p: (len(p), p))[
                            :settings['max_paths_per_result']]
                        scoped_rows.append(row)
                    if phase['lineage_overflow']:
                        triggers.append('lineage_overflow')
                        omitted.append(_issue('unsupported', 'graph-scope', 'Scoped evidence whose complete lineage '
                                              'exceeds the evidence contract was left to the rescue search.'))
                    if len(scoped_rows) < top_k - (reserved if policy == 'always' else 0):
                        triggers.append('scoped_underfilled')

        if policy == 'always' and reserved:
            triggers.insert(0, 'reserved')
        searched = phase['status'] == 'completed'
        # Provider scopes are allow-lists: an explicit caller scope gives an exact
        # complement; an unrestricted one gives a global search without repeats.
        outside = [i for i in caller if (i['document_id'], i['version']) not in in_scope] if searched else deepcopy(caller)
        rescue = dict(policy=policy, triggers=list(triggers), status='not_triggered',
                      coverage='complement' if searched and caller else 'caller_scope' if caller else 'global',
                      request_id=None, receipt_id=None, expansion_cap=0, expansions=0, elapsed_seconds=0.0,
                      returned=0, duplicates=0, served=0, served_outside_scope=0)
        rescue_rows, need = [], max(reserved, top_k - len(scoped_rows))
        if triggers:
            left, wall = budgets['max_expansions'] - used, remaining(budgets['max_seconds'])
            rescue['expansion_cap'] = max(0, left)
            if searched and caller and not outside:
                rescue['status'] = 'no_outside_population'
            elif need < 1:
                # Only a one-slot request already filled by the scope reaches this.
                rescue['status'] = 'no_slots'
            elif left < 1 or wall < 0.001:
                rescue['status'] = 'budget_exhausted'
                omitted.append(_issue('budget', 'rescue', 'The rescue search could not run within the remaining budget.'))
            else:
                headroom = len(scoped_rows) if searched and not caller else 0
                sub = _subrequest(request, 'rescue', outside, min(512, need + headroom), left, wall)
                rescue['request_id'], rescue_start = sub['request_id'], elapsed()
                # A rescue timeout exhausts the whole request deadline; it propagates.
                found = self._search(sub, view, index)
                used += found['usage']['expansions']
                omitted += _phase_issues('rescue', found['omitted'])
                failures += _phase_issues('rescue', found['failures'])
                served_ids, spans = {r['id'] for r in scoped_rows}, {_span(r) for r in scoped_rows}
                for row in found['results']:
                    if row['id'] in originals and originals[row['id']] != _content(row):
                        raise ValueError('provider evidence identity changed between searches')
                    if row['id'] in served_ids or _span(row) in spans:
                        rescue['duplicates'] += 1
                    else:
                        row['scores']['graph_paths'] = []
                        rescue_rows.append(row)
                if searched:
                    # The reserve goes first to evidence outside the graph scope (stable order).
                    rescue_rows.sort(key=lambda r: (r['document_id'], r['version']) in in_scope)
                rescue.update(status='completed', receipt_id=found['receipt_id'], returned=len(found['results']),
                              expansions=found['usage']['expansions'], elapsed_seconds=elapsed() - rescue_start)

        ran = rescue['status'] == 'completed'
        take = min(reserved, len(rescue_rows)) if ran else 0
        chosen = [['scope', row] for row in scoped_rows[:top_k - take]]
        chosen += [['rescue', row] for row in rescue_rows[:top_k - len(chosen)]]
        for item in chosen:
            item.append(len(contract.canonical(item[1])) + 1)
        envelope = dict(schema_version=1, operation='search', request_id=request['request_id'],
                        provider_id=self.provider_id, index=index, results=[], metadata=[], groups=[],
                        next_cursor=None, omitted=_unique(omitted), failures=_unique(failures),
                        usage=dict(elapsed_seconds=0.0, expansions=used, token_accounting='utf8-byte-upper-bound'),
                        receipt_id=receipt)
        # Fit the complete envelope by omitting whole rows. The rescue keeps its
        # byte share while it has rows; either pool may use the other's spare.
        cap, dropped = min(budgets['max_bytes'], budgets['max_tokens']), 0
        while True:
            envelope['results'] = [row for _, row, _ in chosen]
            for rank, row in enumerate(envelope['results'], 1):
                row['scores']['rank'] = rank
            envelope['usage']['elapsed_seconds'] = elapsed()
            if len(contract.canonical(envelope)) <= cap:
                break
            if not chosen:
                raise ValueError('graph-guided envelope cannot fit requested budgets')
            if not dropped:
                envelope['omitted'].append(_issue('budget', 'graph-guided', 'Whole evidence omitted to fit '
                                                  'the complete envelope within the scope and rescue shares.'))
            available = cap - len(contract.canonical(dict(envelope, results=[])))
            share = math.floor(available * fraction) if ran else 0
            pools = {origin: sum(size for o, _, size in chosen if o == origin) for origin in ('scope', 'rescue')}
            pool = ('scope' if pools['scope'] and (not pools['rescue'] or
                    pools['scope'] > available - min(pools['rescue'], share)) else 'rescue')
            chosen.pop(max(i for i, item in enumerate(chosen) if item[0] == pool))
            dropped += 1
        if envelope['usage']['elapsed_seconds'] > budgets['max_seconds']:
            raise TimeoutError('graph-guided retrieval deadline exhausted')
        # A fresh projection immediately before return catches a changed view.
        if (any(not _permitted(view, _descriptors(row)) for row in envelope['results'])
                or not _permitted(view, scope_lineage)):
            raise ValueError('literature source view changed during retrieval')
        result = contract.validate_candidates(envelope, request, provider_id=self.provider_id, index=index)

        served = [dict(id=row['id'], origin=origin, in_graph_scope=(row['document_id'], row['version']) in in_scope)
                  for origin, row, _ in chosen]
        phase['served'] = sum(row['origin'] == 'scope' for row in served)
        rescue.update(triggers=list(triggers), served=sum(row['origin'] == 'rescue' for row in served),
                      served_outside_scope=sum(row['origin'] == 'rescue' and not row['in_graph_scope'] for row in served))
        trace = dict(schema_version=1, kind=KIND, receipt_id=receipt, request_id=request['request_id'],
                     provider_id=self.provider_id, inner_provider_id=self.inner_provider_id, index=deepcopy(index),
                     graph_sha256=self._graph.sha256, bindings_sha256=self._bindings_sha256, settings=deepcopy(settings),
                     graph=dict(status=graph_status, queries=graph_rows, truncated=truncated, document_scope=scope,
                                lineage=scope_lineage, **graph_usage),
                     allocation=dict(top_k=top_k, rescue_slots=reserved, rescue_byte_fraction=fraction if ran else 0.0,
                                     max_expansions=budgets['max_expansions'], reserve_expansions=reserve_expansions,
                                     max_seconds=budgets['max_seconds'], scope_deadline_seconds=scope_deadline),
                     scope_search=phase, rescue=rescue, served=served, budget_omissions=dropped,
                     usage=deepcopy(result['usage']), **FLAGS)
        return dict(envelope=result, trace=trace)


def summarize(traces):
    """Batch counts for evaluating the rescue: measurements, not relevance judgments."""
    total = dict(searches=0, graph_matched=0, scoped_completed=0, triggers=dict.fromkeys(TRIGGERS, 0),
                 rescue_status={}, served_scope=0, served_rescue=0, served_rescue_outside_scope=0,
                 rescue_duplicates=0, budget_omissions=0)
    for trace in traces:
        if not isinstance(trace, dict) or trace.get('kind') != KIND or trace.get('schema_version') != 1:
            raise ValueError('graph-guided search traces required')
        total['searches'] += 1
        total['graph_matched'] += trace['graph']['status'] == 'matched'
        total['scoped_completed'] += trace['scope_search']['status'] == 'completed'
        status = trace['rescue']['status']
        total['rescue_status'][status] = total['rescue_status'].get(status, 0) + 1
        for trigger in trace['rescue']['triggers']:
            total['triggers'][trigger] += 1
        total['served_scope'] += trace['scope_search']['served']
        total['served_rescue'] += trace['rescue']['served']
        total['served_rescue_outside_scope'] += trace['rescue']['served_outside_scope']
        total['rescue_duplicates'] += trace['rescue']['duplicates']
        total['budget_omissions'] += trace['budget_omissions']
    return total
