"""Opt-in literature tools and bounded role packets over the governed broker.

The controller supplies requests and an already source-bound broker. Neither a
role card nor a worker request selects a provider, index, source root or model.
Old cards and cold knowledge bundles are unchanged when no requests are supplied.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from . import knowledge_broker, literature_provider as contract, literature_serving as serving

MAX_REQUESTS = 16


def operations(card):
    """A closed, explicit role declaration; absent declarations grant nothing."""
    declared = card.get('knowledge', {}).get('literature_operations', [])
    if (not isinstance(declared, list) or any(not isinstance(op, str) for op in declared)
            or len(declared) != len(set(declared)) or set(declared) - set(contract.OPERATIONS)):
        raise ValueError('literature_operations must be a unique list of admitted operations')
    if declared and (serving.ACTION not in card['tools']['ravel_actions']
                     or card['requires']['tools'] == 'none'):
        raise ValueError('literature operations require the governed broker action and a tool-capable role')
    return tuple(op for op in contract.OPERATIONS if op in declared)


def tools(card, row, *, executable):
    """Rows for the existing toolbelt and MCP server; replay is supervisor-only."""
    allowed = operations(card)
    if serving.ACTION not in executable:
        return []
    return [tool for tool in serving.tools(row) if tool['executes_through']['fixed_args']['op'] in allowed]


def _binding(broker, card, node_id):
    if broker.role != card['id'] or broker.node_id != node_id:
        raise ValueError('literature packet requires the receiving role and node broker binding')
    if getattr(broker, '_literature_serving', None) is None:
        raise ValueError('literature packet requires the registered governed broker')


def packet(broker, card, node_id, requests, *, budget_tokens):
    """Return an optional bundle section and exact workspace payloads.

    Required knowledge is materialized first. The caller gives only its remaining
    UTF-8 byte budget here. Whole envelopes are included or explicitly omitted;
    excerpts, ranking, failures and metadata are never rewritten. Refusals remain
    broker receipts. The packet lists included IDs separately from all evidence
    served to the attempt, including later interactive retrieval.
    """
    allowed = operations(card)
    _binding(broker, card, node_id)
    if type(budget_tokens) is not int or budget_tokens < 0:
        raise ValueError('literature packet budget must be a nonnegative integer')
    if not isinstance(requests, list) or len(requests) > MAX_REQUESTS:
        raise ValueError('literature packet requests must be a bounded list')
    # Validate the complete population before producing any broker effect.
    for request in requests:
        if (not isinstance(request, dict) or set(request) != {'op', 'args'}
                or request['op'] not in allowed or not isinstance(request['args'], dict)):
            raise ValueError('literature packet request is outside the receiving role declaration')
    section = {'schema_version': 1, 'kind': 'literature-role-packet', 'requests': [],
               'binding': {'run_id': knowledge_broker.run_id(broker.rundir), 'role': broker.role,
                           'node_id': broker.node_id, 'attempt': broker.attempt},
               'omitted': [], 'served_ids': [], 'used_tokens': 0, 'budget_tokens': budget_tokens,
               'token_accounting': 'utf8_bytes_upper_bound', 'physics_verified': False,
               'execution_authorized': False}
    payloads = {}
    for number, request in enumerate(requests):
        if section['used_tokens'] >= budget_tokens:
            section['omitted'].append({'request': number, 'reason': 'budget'})
            continue
        reply = serving.call(broker, request['op'], request['args'])
        row = {'request': number, 'operation': request['op'], 'status': reply['status'],
               'receipt_id': reply['receipt_id']}
        if reply['status'] != 'ok':
            section['omitted'].append({**row, 'reason': (reply.get('error') or {}).get('code', 'refused')})
            continue
        raw = serving.load(broker.rundir, reply)
        sha = hashlib.sha256(raw).hexdigest()
        path = 'inputs/knowledge/literature/' + sha + '.json'
        charge = 0 if path in payloads else len(raw)
        if section['used_tokens'] + charge > budget_tokens:
            section['omitted'].append({**row, 'reason': 'budget'})
            continue
        envelope = json.loads(raw)
        identities = list(dict.fromkeys(r['id'] for r in envelope['results'] + envelope['metadata']))
        section['requests'].append({**row, 'path': path, 'sha256': sha, 'ids': identities})
        section['served_ids'] = list(dict.fromkeys(section['served_ids'] + identities))
        section['used_tokens'] += charge
        payloads[path] = raw
    return section, payloads


def supplement(index, card, node_facts, binding):
    """Knowledge-materializer seam: no selected requests means byte-identical legacy output."""
    requests = binding.get('literature_requests', [])
    if not isinstance(requests, list):
        raise ValueError('literature packet requests must be a bounded list')
    if not requests:
        return index, {}
    broker = binding.get('literature_broker')
    if broker is None:
        raise ValueError('selected literature requests require a trusted bound broker')
    from pathlib import Path
    if Path(binding['workspace']).resolve() != broker.workspace.resolve():
        raise ValueError('literature packet broker belongs to another workspace')
    section, payloads = packet(broker, card, index['node_id'], requests,
                               budget_tokens=max(0, index['budget_tokens'] - index['used_tokens']))
    result = deepcopy(index)
    result['literature'] = section
    result['used_tokens'] += section['used_tokens']
    return result, payloads


def validate_citations(record, index, broker):
    """Citations need current attempt custody, including later interactive retrieval.

    Packet inclusion is context provenance, not an allowlist for follow-up tools.
    An explicit final use declaration is never inferred from either population.
    """
    cited = record.get('literature_used', [])
    if not isinstance(cited, list) or any(not isinstance(identity, str) for identity in cited):
        raise ValueError('literature_used must be an ID list')
    section = index.get('literature', {})
    if broker.role != index['card_id'] or broker.node_id != index['node_id']:
        raise ValueError('literature citation broker belongs to another role or node')
    binding = {'run_id': knowledge_broker.run_id(broker.rundir), 'role': broker.role,
               'node_id': broker.node_id, 'attempt': broker.attempt}
    if cited and section and section.get('binding') != binding:
        raise ValueError('literature citation packet belongs to another attempt')
    serving.check_citations(broker.rundir, cited, node_id=broker.node_id, attempt=broker.attempt)
    return list(dict.fromkeys(cited))
