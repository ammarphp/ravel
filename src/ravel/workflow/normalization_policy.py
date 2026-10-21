"""Claim-level normalization audit disposition from request-plan lineage.

This classifies review applicability only; it creates no normalization inputs or
ledger and does not certify the claim. Callers supply an admitted request plan.
Incomplete lineage can never establish the pure-analytic binned exception.
"""
from __future__ import annotations

import re

from ravel.validation.validate_request_plan import ancestors, computed_bases, signatures


def _normalization_term(value):
    parts = re.split(r'[/._\-\s]+', str(value).casefold())
    return (any(p in {'normalization', 'normalisation', 'luminosity', 'weights',
                      'weight', 'sumw', 'sumw2'} for p in parts)
            or 'crosssection' in parts
            or any(a == 'cross' and b == 'section' for a, b in zip(parts, parts[1:])))


def _facts(value, pointer=''):
    """Find typed property names and JSON pointers, never free prose or labels."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = pointer + '/' + str(key).replace('~', '~0').replace('/', '~1')
            if (_normalization_term(key)
                    or key == 'pointer' and _normalization_term(item)
                    or key in {'kind', 'type'} and isinstance(item, str) and _normalization_term(item)):
                found.append({'pointer': path, 'value': item})
            found.extend(_facts(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_facts(item, pointer + '/' + str(index)))
    return found


def normalization_disposition(plan: dict, claim: dict | str, *, reg=None, bases=None) -> dict:
    """Return a deterministic typed disposition and its exact lineage evidence.

    ``reg`` and ``bases`` allow callers already deriving reviews to reuse the
    validated signature registry and computed bases. Declared analytic labels do
    not prove the exception; analytic contributions must come from the graph.
    """
    reg = signatures() if reg is None else reg
    if isinstance(claim, str):
        claim = next(c for c in plan.get('claims', []) if c['id'] == claim)
    cid = claim['id']
    upstream = ancestors(plan, cid)
    nodes = {n['id']: n for n in plan.get('nodes', [])}
    inputs = {i['id']: i for i in plan.get('inputs', [])}
    claims = {c['id']: c for c in plan.get('claims', [])}
    records = {**inputs, **nodes, **claims}
    computed = (computed_bases(plan, reg) if bases is None else bases).get(cid, [])
    elements = {r['element'] for r in computed} | set(claim.get('basis_declared', []))
    node_ids = sorted(upstream & nodes.keys())
    checks = []
    facts = []
    for ref in sorted(upstream | {cid}):
        for fact in _facts(records.get(ref, {})):
            facts.append({'ref': ref, **fact})
    for edge in plan.get('edges', []):
        if edge.get('to', {}).get('ref') in upstream | {cid}:
            for fact in _facts(edge.get('require', {}), '/require'):
                facts.append({'ref': edge.get('id'), **fact})
    for ref in node_ids:
        node = nodes[ref]
        signature = reg.get(node.get('operation'))
        if signature is not None:
            checks.append({'node_id': ref, 'operation': node.get('operation'),
                           'checks': list(signature.get('review', {}).get('checks', []))})
    triggers = []
    if elements & {'simulated_acceptance', 'generated_prediction'}:
        triggers.append('simulation_basis')
    if claim.get('absolute_yield'):
        triggers.append('absolute_yield')
    if any('normalization_ledger' in c['checks'] for c in checks):
        triggers.append('signature_normalization_ledger')
    if facts:
        triggers.append('typed_normalization_facts')
    evidence = {'ancestor_node_ids': node_ids, 'ancestor_ids': sorted(upstream),
                'computed_basis': computed, 'signature_checks': checks,
                'normalization_facts': facts, 'triggers': triggers}

    def result(applicable, reason):
        return {'claim_id': cid, 'applicable': applicable,
                'disposition': 'applicable' if applicable else 'not_applicable',
                'reason': reason, 'evidence': evidence}

    if (claim.get('deliverable') or {}).get('artifact') != 'binned_values':
        applicable = any(t in triggers for t in ('simulation_basis', 'absolute_yield'))
        return result(applicable, 'normalization_required_by_claim_lineage' if applicable
                      else 'no_normalization_trigger')
    if triggers:
        return result(True, 'normalization_required_by_claim_lineage')

    unresolved = []
    analytic_via = {ref for row in computed if row['element'] == 'analytic'
                    for ref in row.get('via', [])}
    if not analytic_via:
        unresolved.append({'ref': cid, 'reason': 'no_computed_analytic_basis'})
    for ref in sorted(upstream):
        record = records.get(ref)
        if record is None:
            unresolved.append({'ref': ref, 'reason': 'unknown_lineage_reference'})
        elif ref in inputs:
            if not (record.get('provides') or {}).get('kind'):
                unresolved.append({'ref': ref, 'reason': 'untyped_input'})
        elif ref in nodes:
            signature = reg.get(record.get('operation'))
            if record.get('kind', 'operation') != 'operation' or signature is None or ref not in analytic_via:
                unresolved.append({'ref': ref, 'reason': 'not_registered_analytic_operation'})
                continue
            incoming = [e for e in plan.get('edges', []) if e.get('to', {}).get('ref') == ref]
            for slot in signature.get('consumes', []):
                if not slot.get('optional') and not any(e['to'].get('slot') == slot['slot'] for e in incoming):
                    unresolved.append({'ref': ref, 'reason': 'missing_required_input', 'slot': slot['slot']})
    for edge in plan.get('edges', []):
        if edge.get('to', {}).get('ref') in upstream | {cid} and edge.get('resolution') != 'compatible':
            unresolved.append({'ref': edge.get('id'), 'reason': 'unresolved_edge'})
    if 'unclassified' in elements:
        unresolved.append({'ref': cid, 'reason': 'unclassified_basis'})
    evidence['unresolved_lineage'] = unresolved
    if unresolved:
        return result(True, 'binned_lineage_not_proven_pure_analytic')
    evidence['missing_normalization'] = {
        'cross_section_facts': 'absent', 'luminosity_facts': 'absent',
        'weights_facts': 'absent', 'normalization_facts': 'absent',
        'normalization_ledger_signature_check': 'absent',
    }
    return result(False, 'proven_pure_analytic_binned_values')
