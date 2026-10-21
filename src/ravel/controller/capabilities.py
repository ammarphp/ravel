"""The capability catalogue every deciding seat receives: what RAVEL can do, generated from its registries.

``catalogue`` lists every installed route spec (and the controller's own judgment route), every registered
operation and every registered tool of the knowledge atlas, each with the applicability facts and the cost
information its registry records. It is generated from code and data, never written by hand, and sealed by its
digest. ``applicable`` evaluates those applicability facts against a request's intake facts
(``routes.select.view``): a route whose match predicate holds, an operation whose outputs or claim kinds a
requested deliverable needs (or that the request names), a tool identified by a declared name or ID and its
declared operations. Capabilities compose: every
applicable capability is reported, never one route or tool per request.

The catalogue informs a decision; it admits nothing. Admission, authority and review stay with the controller.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import json

SCHEMA = 'ravel-capability-catalogue.v1'
LEVELS = ('low', 'central', 'high')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def _select():
    return importlib.import_module('ravel.controller.routes.select')


def _projection():
    """Installed engagement projections by route and tier (central and high cost), or {} when stale."""
    try:
        from ravel.controller.engagement import envelope
        routes = envelope.installed_projection()['routes']
    except Exception:  # a stale projection is reported as unknown cost, never as zero
        return {}
    return {route: {tier: {level: row[level]['cost_usd'] for level in LEVELS}
                    for tier, row in tiers.items() if isinstance(row, dict) and row.get('status') == 'ready'}
            for route, tiers in routes.items()}


def _routes(specs, projection):
    select = _select()
    rows = []
    for spec in [*select.BUILTIN, *specs]:
        steps = spec.get('steps') or []
        rows.append({'id': spec['id'], 'match': deepcopy(spec.get('match')),
                     'description': spec.get('description') or spec.get('reason'),
                     'adapter': spec.get('adapter'),
                     'deliverables': [deepcopy(d.get('match')) for d in spec.get('deliverables') or []],
                     'step_kinds': sorted({s.get('kind') for s in steps if s.get('kind')}),
                     'operations': sorted({s['operation'] for s in steps if s.get('operation')}),
                     'roles': sorted({s['role'] for s in steps if s.get('role')}),
                     'projected_cost_usd': deepcopy(projection.get(spec['id'])) or None})
    return rows


def _signatures():
    """The whole registered operation signature table, read as the production executor reads it."""
    from ravel.workflow import production_executor
    from ravel.workflow.state_io import read_json
    return read_json(production_executor.SIGNATURES)['operations']


def _operations(atlas, signatures):
    """Every registered operation: the signature registry, joined with its knowledge-atlas entry when it has one."""
    entries = {e['title']: e for e in atlas['entries'] if e.get('kind') == 'op'}
    rows = []
    for name in sorted(set(signatures) | set(entries)):
        signature, entry = signatures.get(name) or {}, entries.get(name) or {}
        op = entry.get('op') or {}
        outputs = signature.get('produces') or op.get('outputs') or []
        rows.append({'id': name, 'atlas_id': entry.get('id'), 'registered_signature': name in signatures,
                     'status': entry.get('status') or ('registered' if name in signatures else None),
                     'summary': signature.get('summary') or entry.get('summary'),
                     'use_when': deepcopy(op.get('use_when') or []),
                     'do_not_use_when': deepcopy(op.get('do_not_use_when') or []),
                     'claim_kinds': sorted(op.get('claim_kinds') or []),
                     'effects': sorted(signature.get('effects') or op.get('effects') or []),
                     'output_kinds': sorted({o.get('kind') for o in outputs if o.get('kind')}),
                     'input_kinds': sorted({i.get('kind') for i in signature.get('consumes') or op.get('inputs') or []
                                            if i.get('kind')}),
                     'tools': sorted(signature.get('tools') or []),
                     'cost': deepcopy(signature.get('cost') or op.get('cost_class')),
                     'validation_tier': op.get('validation_tier')})
    return rows


def _tools(atlas):
    return [{'id': entry['id'], 'name': entry['id'].split(':', 1)[-1], 'title': entry.get('title'),
             'status': entry.get('status'), 'qualification_status': entry.get('qualification_status'),
             'installer_group': entry.get('installer_group'),
             'operations': sorted({name.removeprefix('op:')
                                   for name in (entry.get('links') or {}).get('operations', [])})}
            for entry in atlas['entries'] if entry.get('kind') == 'tool']


def _tool_names(row):
    """Exact declared tool identities, normalized for request spelling."""
    return {value.casefold() for key in ('id', 'name', 'title')
            if isinstance(value := row.get(key), str) and value}


def catalogue(*, atlas=None, specs=None, signatures=None):
    """The sealed catalogue of every registered route, operation and tool."""
    from ravel.workflow import toolbelt
    atlas = atlas if atlas is not None else toolbelt.load_atlas()
    specs = specs if specs is not None else _select().load_specs()
    signatures = signatures if signatures is not None else _signatures()
    body = {'schema': SCHEMA, 'routes': _routes(specs, _projection()), 'operations': _operations(atlas, signatures),
            'tools': _tools(atlas),
            'scope': 'Registered capabilities with their applicability facts and costs. Availability is not '
                     'admission, qualification or scientific validity; the controller admits every effect.'}
    return {**body, 'sha256': digest(body)}


def request_facts(contract, reading, supplied=()):
    """The intake facts applicability reads: the same view route selection evaluates."""
    return _select().view(contract, reading, list(supplied))


def applicable(catalogue_document, facts):
    """Every capability the request's facts call for: routes, operations and tools, each with the facts used."""
    select = _select()
    artifacts, claims = set(facts.get('artifact_kinds') or ()), set(facts.get('claim_kinds') or ())
    named = {facts.get('operation')} | set(facts.get('requested_tools') or ())
    named_tools = {name.casefold() for name in named if isinstance(name, str)}
    selected_tools = [row for row in catalogue_document['tools'] if _tool_names(row) & named_tools]
    tool_names = named_tools | {name for row in selected_tools for name in _tool_names(row)}
    tool_operations = {operation for row in selected_tools for operation in row.get('operations', [])}
    routes = []
    for row in catalogue_document['routes']:
        when = (row.get('match') or {}).get('when')
        if when is not None and select.evaluate(when, facts):
            routes.append({'id': row['id'], 'because': 'its match predicate holds for the request facts'})
    operations = []
    for row in catalogue_document['operations']:
        why = []
        if artifacts & set(row['output_kinds']):
            why.append('produces requested artifact kinds ' + ', '.join(sorted(artifacts & set(row['output_kinds']))))
        if claims & set(row['claim_kinds']):
            why.append('supports requested claim kinds ' + ', '.join(sorted(claims & set(row['claim_kinds']))))
        if row['id'] in named:
            why.append('named by the request')
        if (row['id'] in tool_operations
                or tool_names & {name.casefold() for name in row.get('tools', [])}):
            why.append('declared operation for a named tool')
        if why:
            operations.append({'id': row['id'], 'because': '; '.join(why)})
    tools = [{'id': row['id'], 'because': 'named by the request'} for row in selected_tools]
    return {'catalogue_sha256': catalogue_document['sha256'], 'routes': routes, 'operations': operations,
            'tools': tools}


def view(contract, reading, supplied=()):
    """What a deciding seat receives: the whole catalogue and what the request's facts call for."""
    document = catalogue()
    return {'catalogue': document, 'applicable': applicable(document, request_facts(contract, reading, supplied))}


__all__ = ['applicable', 'catalogue', 'request_facts', 'view']
