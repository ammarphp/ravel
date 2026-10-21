"""Run-bound knowledge actions using the trusted broker registry and custody.

SourceBoundBroker extends source matching only; the broker core owns dispatch,
fd-safe IO, call budgets, replay and receipt custody. Bundle builders use
filter_sources before opening any member. Worker inventory uses filter_inputs.
Every source-bound broker also carries the literature serving actions
(literature_serving); without a trusted retrieval configuration they refuse
each call with a receipt and the knowledge actions are unchanged.
"""
from __future__ import annotations

from copy import copy, deepcopy
import json
import os
from pathlib import Path

from . import broker as core, knowledge, source_policy
from .knowledge_atlas import encode, digest as bytes_digest
from .state_io import atomic_json, file_lock, read_json


def run_id(rundir):
    return core.digest(str(core.ordinary(rundir)))


def policy_rows(rundir):
    run = core.ordinary(rundir)
    contracts = [core.confined(run, p) for p in ('inputs/task_contract.json', 'task_contract.json')]
    present = [p for p in contracts if p.is_file()]
    rows = [source_policy.canonical(read_json(p).get('forbidden_sources', [])) for p in present]
    if rows and any(r != rows[0] for r in rows):
        raise ValueError('run has conflicting source restrictions')
    return rows[0] if rows else []


def policy_digest(rundir):
    return source_policy.digest(policy_rows(rundir))


def _aliases(path):
    """A logical path, then its input-root-relative names, including a live workspace's."""
    names = [path]
    parts = [p for p in path.split('/') if p not in ('', '.')]
    if len(parts) >= 4 and parts[0] == core.WORK:
        parts = parts[3:]
        names.append('/'.join(parts))
    if parts[:1] == ['inputs'] and len(parts) > 1:
        names.append('/'.join(parts[1:]))
    return names


def _sources(value, inherited=None):
    """All structured source pins, including originals inside inventory aliases."""
    if isinstance(value, dict):
        facts = dict(inherited or {})
        for key in ('quantities', 'classes', 'class', 'identifiers', 'analysis', 'inspire', 'arxiv', 'hepdata'):
            if key in value:
                facts[key] = value[key]
        candidate = {**facts, **value}
        if any(k in value for k in ('path', 'quantities', 'classes', 'class', 'identifiers', 'analysis', 'inspire', 'arxiv', 'hepdata')):
            yield candidate
            if isinstance(value.get('path'), str):
                yield from ({**candidate, 'path': a} for a in _aliases(value['path'])[1:])
        if isinstance(value.get('as'), str):
            yield from ({**facts, 'path': a} for a in _aliases(value['as']))
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from _sources(child, facts)
    elif isinstance(value, list):
        for child in value:
            yield from _sources(child, inherited)


MALFORMED_SOURCE = {'kind': 'forbidden-source', 'statement': 'malformed source descriptor', 'origin': 'harness',
                    'classes': [], 'identifiers': {}, 'paths': [], 'evidence': []}


def _portable(path):
    try:
        source_policy._relative(path)
    except ValueError:
        return False
    return True


def _metadata_path(rundir, node_id, attempt):
    return core.custody(rundir) / (core.digest([node_id, attempt]) + '.knowledge-inputs.json')


class SourceBoundBroker(core.Broker):
    """Provider-side policy extension; no broker-core mutation or authority bypass."""
    def __init__(self, rundir, workspace, *, role, atlas_path=None, may_query=None, retrieval=None, **options):
        legacy = options.pop('forbidden_sources', ())
        if not all(isinstance(p, str) for p in legacy):
            raise ValueError('legacy descriptor restrictions must be path strings')
        self.rows = policy_rows(rundir)
        self.legacy_patterns = tuple(legacy)
        self.policy_sha256 = source_policy.digest(self.rows)
        # Path-only, case-folded probes: a case-insensitive volume opens REFS/x as refs/x.
        self._folded = [(r, {'kind': 'forbidden-source', 'statement': r['statement'], 'origin': 'harness', 'evidence': [],
                             'paths': [p.casefold() for p in r['paths']]}) for r in self.rows if r.get('paths')]
        self._digests = None
        self.role = role
        self.atlas_path = atlas_path  # trusted registration only, never a call argument
        # The ops this worker's toolbelt offers (None: every op, for trusted in-process callers).
        self.may_query = None if may_query is None else frozenset(may_query)
        super().__init__(rundir, workspace, forbidden_sources=self.rows, **options)
        metadata = _metadata_path(rundir, self.node_id, self.attempt)
        self.input_sources = read_json(metadata) if metadata.is_file() else {}
        self.guards.append(self._policy_guard)
        register(self)
        # Trusted installation configuration only (literature_serving.Serving), never a call argument.
        from . import literature_serving
        literature_serving.register(self, retrieval)

    def _policy_guard(self, action, args, workspace):
        if policy_digest(self.rundir) != self.policy_sha256:
            return {'code': 'forbidden_source', 'message': 'run source policy changed; rebind the worker'}

    def _path_rows(self, path):
        names = [a.casefold() for a in _aliases(path)]
        return [r for r, probe in self._folded if any(source_policy.matches([probe], {'path': n}) for n in names)]

    def withheld_digests(self):
        """Content digests of run files a path glob withholds, so a copy, hard link or
        case variant under another name is withheld too. Only matched files are hashed."""
        if self._digests is None:
            found = {}
            for folder, _, files in (os.walk(self.rundir) if self._folded else ()):
                for name in files:
                    path = Path(folder) / name
                    if path.is_symlink() or not path.is_file():
                        continue
                    rows = self._path_rows(path.relative_to(self.rundir).as_posix())
                    if rows:
                        known = found.setdefault(core.sha(path), [])
                        known.extend(r for r in rows if r not in known)
            self._digests = found
        return self._digests

    def violations(self, item):
        found = []
        for source in _sources(item):
            if isinstance(source.get('path'), str) and not _portable(source['path']):
                # An absolute or dotted path (an atlas example) cannot name a run input, and no
                # input-root-relative policy glob can match it; identity rows still apply.
                source = {k: v for k, v in source.items() if k != 'path'}
            try:
                rows = source_policy.matches(self.rows, source) if self.rows else []
            except ValueError:
                # A malformed descriptor (an atlas record, not a run input) is withheld while any
                # restriction is in force: it cannot be shown to be outside the policy.
                rows = [MALFORMED_SOURCE]
            if isinstance(source.get('path'), str):
                rows += self._path_rows(source['path'])
            if isinstance(source.get('sha256'), str):
                rows += self.withheld_digests().get(source['sha256'], [])
            for row in rows:
                if row not in found:
                    found.append(row)
        return found

    def _refusal(self, rows):
        ids = ','.join(core.digest(r) for r in rows)
        return core.Refusal('forbidden_source', 'source excluded by policy ' + self.policy_sha256 + '; rows ' + ids)

    def _canonical(self, rel, *, write=False):
        # Reuse core normalization, granted roots and legacy pattern behavior.
        # A shallow view changes no live policy, including under concurrent calls.
        view = copy(self); view.forbidden_sources = self.legacy_patterns
        parts = core.Broker._canonical(view, rel, write=write)
        normalized = '/'.join(parts)
        candidate = {'path': normalized}
        if not write and normalized in self.input_sources:
            candidate['source'] = self.input_sources[normalized]
        rows = self.violations(candidate)
        if rows:
            raise self._refusal(rows)
        return parts

    def filter_sources(self, items, *, surface):
        """Remove restricted members; custody-receipt every omission before IO.

        Bundle builders and supplied-input inventories consume the returned
        allowlist. Withheld records contain an ID and row hashes, never an excerpt.
        """
        if surface not in ('inventory', 'bundle'):
            raise ValueError('unknown source-filter surface')
        visible, withheld = [], []
        for index, item in enumerate(items):
            rows = self.violations(item)
            if not rows:
                visible.append(deepcopy(item)); continue
            action = 'knowledge.source_check'
            # Dispatcher-only action: temporarily grant it for this custody call.
            was_allowed = action in self.allowed_actions
            self.allowed_actions.add(action)
            try:
                reply = self.call({'call_id': surface + '-' + core.digest(item)[:32] + '-' + str(index),
                                   'action': action, 'args': {'source': item}})
            finally:
                if not was_allowed:
                    self.allowed_actions.remove(action)
            if reply['status'] != 'refused' or reply['error']['code'] != 'forbidden_source':
                raise ValueError('source exclusion did not obtain a refusal receipt')
            withheld.append({'id': item.get('id', item.get('as', item.get('path', '?'))),
                             'reason': 'forbidden_source', 'rows': [core.digest(r) for r in rows],
                             'receipt_id': reply['receipt_id']})
        return visible, withheld

    def source_check(self, args):
        if set(args) != {'source'}:
            raise core.Refusal('invalid_args', 'source check requires one source')
        rows = self.violations(args['source'])
        if rows:
            raise self._refusal(rows)
        return {'source': {'uri': 'ravel-knowledge://policy', 'record_id': self.policy_sha256}}

    def _served(self, op, args, result=None, refusal=None):
        record = {'op': op, 'args_sha256': core.digest(args), 'role': self.role,
                  'node_id': self.node_id, 'attempt': self.attempt, 'run_id': run_id(self.rundir),
                  'source_restriction_sha256': self.policy_sha256,
                  'item_ids': (result or {}).get('served_ids', []),
                  'item_digests': {r['id']: bytes_digest(encode(r)) for r in (result or {}).get('results', [])},
                  'result_sha256': (result or {}).get('result_sha256'), 'refusal': refusal}
        core.append_ledger(self.rundir, 'knowledge-served', record)
        path = core.confined(self.rundir, 'knowledge/served.jsonl')
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(core.confined(self.rundir, 'knowledge/served.lock')):
            with core.ordinary(path).open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + '\n')
                stream.flush(); os.fsync(stream.fileno())

    def query(self, op, args):
        # Retrieval takes only inline data: workers cannot choose privileged files,
        # lower the calibrated floor, or forge a binding in the answer envelope.
        allowed = {'show': {'id', 'operation'}, 'find': {'text', 'query', 'kinds', 'kind', 'limit'},
                   'for_node': {'operation', 'mode', 'node', 'node_facts', 'validation_tier'},
                   'for_failure': {'tool', 'failure_class'}, 'plan_check': {'plan'},
                   'coverage': set(), 'xsec': set(), 'constants': set(), 'conventions': set()}
        if op not in allowed or set(args) - (allowed.get(op, set()) | {'max_bytes'}):
            raise core.Refusal('invalid_args', 'knowledge requires declared inline arguments')
        if op == 'plan_check' and not isinstance(args.get('plan', {}), dict):
            raise core.Refusal('invalid_args', 'knowledge plans must be inline objects')
        result = knowledge.query(op, **args, atlas_path=self.atlas_path)
        visible, withheld = [], []
        reviewer = any(term in self.role.split('-') for term in ('reviewer', 'critic', 'verifier'))
        for item in result['results']:
            rows = self.violations(item)
            lesson_denied = reviewer and (item.get('kind') == 'lesson' or item.get('id', '').startswith('lesson:'))
            if rows or lesson_denied:
                withheld.append({'id': item['id'], 'reason': 'reviewer_lessons' if lesson_denied else 'forbidden_source',
                                 'rows': [core.digest(r) for r in rows]})
            else:
                visible.append(item)
        # Apply policy before ranking and limits as well as at the response
        # boundary. The filtered index stays in supervisor-only custody.
        if op != 'show':
            atlas = knowledge.load_atlas(self.atlas_path)
            permitted = [r for r in atlas['entries'] if not self.violations(r)
                         and not (reviewer and (r.get('kind') == 'lesson' or r.get('id', '').startswith('lesson:')))]
            ids = {r['id'] for r in permitted}
            for entry in permitted:
                for key, links in list(entry.get('links', {}).items()):
                    entry['links'][key] = ([i for i in links if i in ids] if isinstance(links, list)
                                           else links if links in ids else [])
            filtered = {**atlas, 'entries': permitted}
            filtered_path = core.custody(self.rundir) / ('knowledge-atlas-' + bytes_digest(encode(filtered)) + '.json')
            if not filtered_path.exists():
                atomic_json(filtered_path, filtered)
            original_sha256 = result['atlas_sha256']
            result = knowledge.query(op, **args, atlas_path=filtered_path)
            result['filtered_atlas_sha256'] = result['atlas_sha256']
            result['atlas_sha256'] = original_sha256
            visible = result['results']
        result['results'] = visible
        result['served_ids'] = [r['id'] for r in visible]
        allowed_ids = set(result['served_ids'])
        for node in result.get('nodes', []):
            node['served_ids'] = [i for i in node['served_ids'] if i in allowed_ids]
        result['withheld'] = withheld
        result['binding'] = {'run_id': run_id(self.rundir), 'node_id': self.node_id,
                             'attempt': self.attempt, 'role': self.role,
                             'source_restriction_sha256': self.policy_sha256}
        if op == 'show' and withheld:
            self._served(op, args, refusal=withheld)
            raise self._refusal([r for r in self.rows if core.digest(r) in withheld[0]['rows']])
        max_bytes = args.get('max_bytes', 32768)
        # Rehash and enforce the original bound after the binding/census is added.
        while True:
            allowed_ids = set(result['served_ids'])
            for node in result.get('nodes', []):
                node['served_ids'] = [i for i in node['served_ids'] if i in allowed_ids]
            result.pop('result_sha256', None)
            result['result_sha256'] = bytes_digest(encode(result))
            if len(encode(result)) <= max_bytes:
                break
            if result['results']:
                result['results'].pop(); result['served_ids'].pop()
                result['omitted']['count'] += 1
                reasons = result['omitted']['reasons']; reasons['budget'] = reasons.get('budget', 0) + 1
            elif result['withheld']:
                result['withheld'].pop()
                result['omitted']['count'] += 1
                reasons = result['omitted']['reasons']; reasons['withheld_budget'] = reasons.get('withheld_budget', 0) + 1
            else:
                raise core.Refusal('budget_exhausted', 'bound query envelope exceeds max_bytes')
        relative = 'outputs/knowledge/' + result['result_sha256'] + '.json'
        # Worker-writable output directories need the core's descriptor-safe IO.
        self._write({'path': relative, 'content': encode(result).decode()})
        self._served(op, args, result)
        return {'stdout': json.dumps({'result_sha256': result['result_sha256'], 'served_ids': result['served_ids']}),
                'output_paths': [relative], 'source': {'uri': 'ravel-knowledge://atlas/' + result['atlas_sha256'],
                                                     'record_id': result['atlas_sha256']}}


def register(broker):
    """Trusted registration seam for the tool gate and the MCP adapter; no allowlist grants.

    ``knowledge query`` takes the one shape the toolbelt sends, ``{op, args}``, and
    refuses an op outside the broker's ``may_query`` (the worker's toolbelt ops).
    """
    def narrowed(op):
        if broker.may_query is not None and op not in broker.may_query:
            raise core.Refusal('not_allowlisted', f'knowledge op {op!r} is outside the worker toolbelt')

    def single(args, op):
        narrowed(op)
        return broker.query(op, args)
    for op in knowledge.OPS:
        broker.register('knowledge.' + op, lambda args, op=op: single(args, op),
                        derivation='retrieval', read_only=True)
    def dispatch(args):
        if set(args) != {'op', 'args'} or not isinstance(args['args'], dict):
            raise core.Refusal('invalid_args', 'knowledge requires op and args')
        narrowed(args['op'])
        return broker.query(args['op'], args['args'])
    for name in ('knowledge', 'knowledge query'):
        broker.register(name, dispatch, derivation='retrieval', read_only=True)
    broker.register('knowledge.source_check', broker.source_check, derivation='retrieval', read_only=True)


def create(rundir, workspace, *, role, atlas_path=None, retrieval=None, **options):
    return SourceBoundBroker(rundir, workspace, role=role, atlas_path=atlas_path, retrieval=retrieval, **options)


def filter_inputs(rundir, workspace, spec):
    """Worker seam: filter original pins and aliases before any bytes are copied."""
    inputs = spec['inputs']
    for item in inputs:
        if not isinstance(item, dict) or set(item) != {'pin', 'as'}:
            raise ValueError('input copy requires pin and as')
        if not isinstance(item['as'], str) or not isinstance(item['pin'], dict):
            raise ValueError('input copy requires a path and pin')
    tool = create(rundir, workspace, role=spec['role']['id'], node_id=spec['node_id'], attempt=spec['attempt'],
                  allowed_actions=[], max_calls=spec['budgets']['max_broker_calls'])
    metadata = {item['as']: deepcopy(item['pin']) for item in inputs if isinstance(item, dict) and 'as' in item and 'pin' in item}
    atomic_json(_metadata_path(rundir, spec['node_id'], spec['attempt']), metadata)
    return tool.filter_sources(inputs, surface='inventory')[0]
