"""Offline premise checks and source-bound conventions, available before inference.

``firing(facts_or_plan)`` returns check-required rows. Facts use ``operation``
(or ``mode``), ``claim_kind``, ``basis``, ``tags`` and ``observables``; a plan
contains ``nodes`` with these facts. Explicit true semantic flags also count
as tags. Titles, prose, identifiers and execution state never trigger checks.
Predicates are data-only disjunctions of exact operation/tag matches; a ``tags_all`` clause
is one conjunction of tags. They are
review prompts, not exhaustive physics classification or discharged obligations.

``query('find', text=...)``, ``query('show', id=...)``,
``query('for_node', **facts)`` and ``query('conventions', tags=[...])`` return
the knowledge-result/v1 envelope. The atlas/broker can consume these functions;
this module neither registers a second CLI nor changes inference or approval.

Seven shipped graphs use the existing physics_knowledge kernel. Their evidence
is pinned, located RAVEL-authored text, with primary bibliographic locators in
the registry. External source text and scientific qualification are not implied.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from . import physics_knowledge

DATA = Path(__file__).resolve().parents[1] / 'data' / 'knowledge'
SHARDS = ('generation', 'normalization', 'statistics', 'interference-cp',
          'theory-procedures', 'reinterpretation', 'detector-models', 'higgs')
_SEMANTIC = ('tags', 'observables', 'claim_kind', 'basis')
_FLAGS = ('interference', 'broad_resonance', 'wide_resonance', 'single_charge',
          'signed_weights', 'compressed', 'displaced', 'unfolding', 'eft')


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _pin(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {'path': str(path), 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def _read(path):
    raw = Path(path).read_bytes()
    if len(raw) > physics_knowledge.MAX_DOCUMENT_BYTES:
        raise ValueError('premise document exceeds bounded source size')
    from .higgs_registration import compose
    return compose(physics_knowledge._json(raw), path)


def _concerns():
    # Read the canonical literal without importing its scientific execution stack.
    tree = ast.parse(Path(__file__).with_name('sfitter_review_protocol.py').read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'CONCERNS' for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError('canonical review concerns missing')


def registry() -> dict:
    """Return a fresh registry, resolving canonical references without execution."""
    document = _read(DATA / 'premises.json')
    if document.get('schema_version') != 1 or document.get('license') != 'Apache-2.0':
        raise ValueError('licensed premise registry/v1 required')
    rows = document['premises'] + document['conventions']
    if len(rows) > physics_knowledge.MAX_NODES or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('bounded unique premise identities required')
    conventions = {r['id']: r for r in document['conventions']}
    concerns = _concerns()
    interpretation = {r['id']: r for r in _read(
        DATA.parent / 'inference' / 'interpretation_traps.json')['traps']}
    from .trap_sweep import TRAP_IDS
    groups = {kind: {r['canonical']['id'] for r in document['premises']
                     if r['canonical']['kind'] == kind}
              for kind in ('sweep', 'interpretation', 'concern')}
    if (groups['sweep'] != set(TRAP_IDS) or groups['interpretation'] != set(interpretation)
            or groups['concern'] != set(concerns)):
        raise ValueError('canonical trap or review population differs from registry')
    for row in rows:
        for field in ('id', 'statement', 'predicate', 'operations', 'severity', 'check', 'citation'):
            if field not in row:
                raise ValueError('premise schema requires ' + field)
        if row['license'] != 'Apache-2.0' or not row['citation']:
            raise ValueError('authored licence and located citations required')
        for citation in row['citation']:
            if not citation.get('locator') or not citation.get('license'):
                raise ValueError('located licensed reference required')
            if citation['license'] == 'LicenseRef-locator-only' and 'excerpt' in citation:
                raise ValueError('locator-only references cannot ship excerpts')
        _predicate(row['predicate'], set(), set())
    for row in document['premises']:
        canonical = row['canonical']
        if canonical['kind'] == 'interpretation':
            source = conventions[row['conventions'][0]]
            row['statement'], row['check'] = source['statement'], source['check']
            row['obligations'] = deepcopy(source['obligations'])
            row['canonical']['statement'] = interpretation[canonical['id']]['statement']
            row['canonical']['check'] = interpretation[canonical['id']]['check']
            row['canonical_source_pin'] = _pin(DATA.parent / 'inference' / 'interpretation_traps.json')
        elif canonical['kind'] == 'concern':
            phase, check = concerns[canonical['id']]
            row['statement'] = row['check'] = check
            row['obligations'] = [{'id': 'obligation:' + row['id'],
                                   'description': check, 'resource_class': 'source_inspection',
                                   'check': None}]
            row['canonical']['phase'] = phase
            row['canonical_source_pin'] = _pin(Path(__file__).with_name('sfitter_review_protocol.py'))
    return document


def _labels(value, label):
    if isinstance(value, str) and label not in ('tags', 'observables'):
        value = [value]
    if (not isinstance(value, list) or len(value) > 64
            or any(not isinstance(v, str) or not v.strip() or len(v) > 200 for v in value)):
        raise ValueError('bounded text list required for ' + label)
    return {re.sub(r'[\s_]+', '-', v.strip().casefold()) for v in value}


def _facts(node):
    if not isinstance(node, dict):
        raise ValueError('node facts must be an object')
    operations, tags = set(), set()
    # These are typed fact containers, not arbitrary recursive keyword search.
    containers = [node]
    for key in ('facts', 'spec', 'scope'):
        if key in node:
            if not isinstance(node[key], dict):
                raise ValueError(key + ' facts must be an object')
            containers.append(node[key])
    for container in containers:
        for key in ('operation', 'mode'):
            if key in container:
                operations |= _labels(container[key], key)
        for key in _SEMANTIC:
            if key in container:
                tags |= _labels(container[key], key)
        for key in _FLAGS:
            if key in container:
                if type(container[key]) is not bool:
                    raise ValueError('explicit boolean required for ' + key)
                if container[key]:
                    tags.add(key.replace('_', '-'))
    return operations, tags


def _predicate(predicate, operations, tags):
    if (not isinstance(predicate, dict) or set(predicate) != {'any'}
            or not isinstance(predicate['any'], list) or not predicate['any']):
        raise ValueError('premise predicate requires a nonempty any list')
    matched = []
    for clause in predicate['any']:
        if not isinstance(clause, dict) or len(clause) != 1:
            raise ValueError('one exact selector per premise clause required')
        key, values = next(iter(clause.items()))
        if key not in ('tags_any', 'tags_all', 'operations_any'):
            raise ValueError('unknown premise selector: ' + key)
        expected = _labels(values, 'tags')
        overlap = (expected if expected <= tags else set()) if key == 'tags_all' else \
            expected & (tags if key == 'tags_any' else operations)
        if overlap:
            matched.append(key + ':' + ','.join(sorted(overlap)))
    return matched


def firing(facts_or_plan: dict) -> list[dict]:
    """Select review obligations from planned facts, independent of run results.

    Returned rows keep the exact matching node IDs and reasons. An empty result
    means no declared predicate matched; it does not certify the absence of traps.
    """
    if not isinstance(facts_or_plan, dict):
        raise ValueError('facts or plan must be an object')
    nodes = facts_or_plan.get('nodes', [facts_or_plan])
    if not isinstance(nodes, list) or len(nodes) > physics_knowledge.MAX_NODES:
        raise ValueError('bounded plan nodes required')
    parsed, seen = [], set()
    for index, node in enumerate(nodes):
        operations, tags = _facts(node)
        identity = node.get('id', 'node:' + str(index))
        if not isinstance(identity, str) or not identity.strip() or identity in seen:
            raise ValueError('unique nonempty node identities required')
        seen.add(identity)
        parsed.append((identity, operations, tags))
    document = registry()
    selected = []
    for row in document['premises'] + document['conventions']:
        matches = [(identity, _predicate(row['predicate'], operations, tags))
                   for identity, operations, tags in parsed]
        matches = [(identity, reasons) for identity, reasons in matches if reasons]
        if matches:
            selected.append({**row, 'kind': row['id'].split(':')[0],
                             'status': 'check_required',
                             'node_ids': [identity for identity, _ in matches],
                             'why': '; '.join(identity + '=' + ','.join(reasons)
                                              for identity, reasons in matches)})
    return selected


def shard_request(name: str, *, text='physics conventions', tags=None, roots=None,
                  data_dir=None) -> dict:
    """Build a portable request for physics_knowledge.retrieve(request, base)."""
    if name not in SHARDS:
        raise ValueError('unknown convention shard')
    base = Path(data_dir) if data_dir is not None else DATA
    path = base / 'conventions' / (name + '.json')
    if roots == 'all':
        roots = [r['id'] for r in _read(path)['nodes']]
    return {'schema_version': 1, 'knowledge': _pin(path),
            'query': {'text': text, 'tags': tags or [], 'roots': roots or [],
                      'domain': [], 'max_nodes': physics_knowledge.MAX_NODES}}


def _result(op, args, rows):
    from .higgs_registration import premise_pin
    pin = _pin(DATA / 'premises.json')
    results = [{**r, 'kind': r['id'].split(':')[0], 'summary': r['statement'],
                'source_pin': premise_pin(r, pin),
                'why': r.get('why', 'Located convention or canonical premise reference')}
               for r in rows]
    result = {'schema_version': 1, 'kind': 'knowledge-result', 'op': op,
              'args': deepcopy(args), 'results': results,
              'served_ids': [r['id'] for r in results]}
    result['result_sha256'] = hashlib.sha256(_canonical(result)).hexdigest()
    return result


def query(op: str, **args) -> dict:
    """Read-only producer for the atlas query-result schema; no broker side effects."""
    document = registry()
    rows = document['premises'] + document['conventions']
    if op == 'for_node':
        return _result(op, args, firing(args))
    if op == 'show':
        if set(args) != {'id'}:
            raise ValueError('show requires exactly id')
        rows = [r for r in rows if r['id'] == args['id']]
        if not rows:
            raise ValueError('unknown premise or convention id')
    elif op in ('find', 'conventions'):
        if set(args) - {'text', 'tags'}:
            raise ValueError('query accepts text and tags only')
        text = args.get('text', '')
        if not isinstance(text, str) or len(text) > 8000:
            raise ValueError('bounded query text required')
        tags = _labels(args.get('tags', []), 'tags')
        if not text.strip() and not tags:
            raise ValueError('query text or tags required')
        if op == 'conventions':
            selected, evidence = set(), {}
            for name in SHARDS:
                packet = physics_knowledge.retrieve(shard_request(
                    name, text=text or 'tag selection', tags=sorted(tags)), DATA)
                for node in packet['nodes']:
                    selected.add(node['id'])
                    evidence[node['id']] = node['source_evidence']
            rows = [{**r, 'source_evidence': evidence[r['id']]}
                    for r in document['conventions'] if r['id'] in selected]
        else:
            words = set(re.findall(r'[\w-]+', text.casefold()))
            scored = []
            for row in rows:
                tokens = set(re.findall(r'[\w-]+', ' '.join(
                    [row['id'], row['title'], row['statement'], *row['tags']]).casefold()))
                score = len(words & tokens) + 3 * len(tags & set(row['tags']))
                if score:
                    scored.append((score, row))
            rows = [{**row, 'why': 'literal_or_tag_matches:' + str(score)}
                    for score, row in sorted(scored, key=lambda x: (-x[0], x[1]['id']))]
    else:
        raise ValueError('unknown premise query operation')
    return _result(op, args, rows)
