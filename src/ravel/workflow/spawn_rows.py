"""Data-registered staffing extension for the mandatory review engine.

``derive`` returns the review-point shape; ``pending`` uses the same custody and
counting rules as the core engine. The core derivation owner can compose these
rows without changing their policy. No worker is launched by derivation.
"""
from __future__ import annotations

from copy import deepcopy
import json
import hashlib
import math
from pathlib import Path

from ravel.paths import package_data_path
from . import review_points as reviews
from .decision_case import jdigest


def catalogue():
    value = json.loads(package_data_path('knowledge', 'spawn_rows.json').read_text())
    if value.get('schema_version') != 1 or value.get('kind') != 'spawn-row-catalogue':
        raise ValueError('unsupported spawn row catalogue')
    from .higgs_registration import compose
    return compose(value, package_data_path('knowledge', 'spawn_rows.json'))


def review_metadata(node):
    """Use the existing plan field schema instead of adding undeclared node keys."""
    result = {}
    for field in node.get('fields', []):
        pointer = field.get('pointer', '')
        if pointer.startswith('/review/'):
            key = pointer[len('/review/'):]
            if key in result:
                raise ValueError('duplicate review metadata: ' + pointer)
            result[key] = field['value']
    return result


def derive(facts):
    if facts.get('agent_layer_epoch') != 2:
        return []
    from ravel.validation.validate_request_plan import computed_bases, signatures
    plan = deepcopy(facts.get('plan', facts))
    nodes = plan.get('nodes', [])
    for node in nodes:
        node.setdefault('kind', 'operation'); node.setdefault('fields', [])
    bases = computed_bases(plan, signatures())
    # Run facts the request plan cannot state (the controller's machine assumptions) reach the K8 row only.
    plan['machine_assumptions'] = facts.get('machine_assumptions', 0)
    rows = {r['row']: r for r in catalogue()['rows']}
    from .role_registry import registry_document
    registry = registry_document()
    points = []

    def add(row_id, scope, *, node=None, claim=None, roles=None, **extra):
        row = rows[row_id]
        group = 'spawn:' + scope
        entries = deepcopy(row['roles'] if roles is None else roles)
        for role in entries:
            role.setdefault('distinct_family_from', [])
        point = {'id': row_id + ':' + scope, 'row': row_id,
                 'when': {'trigger': row['trigger'], 'at': ('node:' if node else 'checkin2:') + scope},
                 'roles': entries, 'mode': row['mode'], 'blocking': True,
                 'gate': row['gate'], 'parallel_group': group, 'depends_on': [],
                 'attestation_min': 'transport', **extra}
        if node: point['node_id'] = node
        if claim: point['claim_id'] = claim
        points.append(point)
        return point

    for node in sorted(nodes, key=lambda n: n['id']):
        metadata = review_metadata(node)
        authored = node.get('authored') or {}
        draft = node.get('draft') or authored.get('draft') or authored.get('specification') or node.get('spec_template')
        tool = node.get('tool')
        tools = [tool] if tool else signatures().get(node.get('operation'), {}).get('tools', [])
        if draft and node.get('rung') in {'smoke', 'full'}:
            # Tool aliases resolve to one registered consult family; an unknown tool stays visible.
            consults = {}
            for tool in sorted(set(tools)):
                name = 'consult-' + tool
                consults.setdefault(registry['aliases'].get(name, name), []).append(tool)
            for role, names in sorted(consults.items()):
                add('K1', node['id'] + ':' + role.removeprefix('consult-'), node=node['id'],
                    roles=[{'role': role, 'count': 1}], tools=names, fix_or_waive_in_work_order=True)
        evaluator = metadata.get('evaluator', node.get('evaluator', authored.get('signature', {}).get('evaluator', {})))
        if node.get('authored') is not None and isinstance(evaluator, dict) and evaluator.get('kind') == 'deterministic':
            row = rows['K4']
            count = row['deadline_count'] if metadata.get('deadline', plan.get('deadline')) is True else row['candidate_count']
            author_kind = metadata.get('author_kind', node.get('authors', node.get('artifact_kind')))
            if author_kind is None:
                author_kind = {'authored-analysis': 'analysis_code', 'routine-build': 'routine',
                               'model-authoring': 'model'}.get(node.get('implementation'), 'spec')
            role = reviews._catalogue()['author_roles'].get(author_kind, 'spec-author')
            add('K4', node['id'], node=node['id'], roles=[{'role': role, 'count': count}],
                min_model_families=row['min_model_families'], selection_record_required=True)
            add('K6', node['id'], node=node['id'])
    for claim in sorted(plan.get('claims', []), key=lambda c: c['id']):
        computed = bases.get(claim['id'], [])
        elements = {r['element'] for r in computed} | set(claim.get('basis_declared', []))
        if elements & {'generated_prediction', 'simulated_acceptance'} or claim.get('absolute_yield'):
            add('K5', claim['id'], claim=claim['id'], blind_to_producer_numbers=True,
                disagreement_action='open_rca_ticket', tolerance_required=True)
            add('K6', claim['id'], claim=claim['id'])
        analytic = [r for r in computed if r['element'] == 'analytic' and r.get('from') in {'stated_inputs', 'cited_formula'}]
        primary_ids = [c for n in nodes for c in review_metadata(n).get('primary_claims', [])]
        primary = claim.get('primary', claim['id'] in primary_ids if primary_ids else
                            claim.get('kind') in {'calculation', 'prediction'})
        if primary is True and analytic:
            add('K7', claim['id'], claim=claim['id'],
                forbidden_method_nodes=sorted({v for r in analytic for v in r['via']}),
                comparison_required=True, tolerance_required=True)
    panels = list(plan.get('panels', [])) + [p for n in nodes for p in review_metadata(n).get('panels', [])]
    for panel in sorted(panels, key=lambda p: p['id']):
        attempts = panel.get('attempts', [])
        ids = [a['id'] if isinstance(a, dict) else a for a in attempts]
        if len(set(ids)) >= 2:
            add('K6', 'panel:' + panel['id'], panel_id=panel['id'])
    from .spawn_rows_roles import derive_roles
    derive_roles(plan, nodes, bases, rows, points, add, review_metadata)
    from .higgs_registration import derive_higgs
    derive_higgs(nodes, rows, add, review_metadata)
    from ravel.validation.sm_checks import derive_review_points
    points.extend(derive_review_points(facts))
    return sorted(points, key=lambda p: (p['row'], p['id']))


def report(rundir, *, gate=None, action=None):
    """Staffing observations, including family labels on filled points; loose verdicts never count."""
    from . import rdj_custody
    root = Path(rundir)
    facts = reviews._facts(root)
    points = derive(facts)
    by_id = {p['id']: p for p in points}
    receipts = []; every = []
    for path in sorted((root / 'agent-work').glob('*/*/receipt.json')):
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        relative = path.relative_to(root).as_posix()
        rec = json.loads(raw)
        every.append(rec)
        registration = rdj_custody.worker_row(root, relative, sha)
        # A producer is known only from verified custody: the registered actor, never a stated one.
        rec['_actor'] = reviews.registered_actor(rec, registration) if registration is not None else None
        if registration is None:
            continue
        point = by_id.get(rec.get('review_point_id'))
        if not point or reviews.credit_refusal(rec, facts, point) is not None:
            continue
        final = rec.get('final_record') or {}
        target = (path.parent / final.get('path', '')).resolve()
        if not target.is_relative_to(path.parent.resolve()) or not target.is_file():
            continue
        if hashlib.sha256(target.read_bytes()).hexdigest() != final.get('sha256'):
            continue
        rec['_label'] = reviews.worker_label(rec, registration.get('verified_label'))
        from . import review_independence
        rec['_independence'] = review_independence.decide(
            review_independence.worker_query(root, rec, sha,
                subject_sha256=reviews.review_subject(facts, point)['sha256']))
        rec['findings'] = json.loads(target.read_bytes()).get('findings', [])
        receipts.append(rec)
    missing = reviews._missing(points, receipts,
                               reviews.producer_sessions(every, [*reviews.derive(facts), *points], facts))
    from . import rdj_approval
    if rdj_approval.applies(root):
        conditional = [p for p in points if missing[p['id']] and p['row'] != 'K8'
                       and p['mode'] in reviews.CONTROLLER_SEAT_MODES
                       and p['gate'] in ('approve_plan', 'checkin2_accept', 'delivery', 'final_task')
                       and (gate is None or reviews._weighs(p, gate, action or {}))]
        controlled, _ = reviews._controller_missing(root, conditional, gate=gate, action=action)
        missing.update(controlled)
    result = []
    for point in points:
        findings = [f for rec in receipts if rec.get('review_point_id') == point['id'] for f in rec['findings']
                    if reviews.blocking_finding(root, f)]
        families = {r['_actor'].get('family') for r in receipts
                    if r.get('review_point_id') == point['id'] and r.get('status') == 'ok'
                    and r.get('run_tree', {}).get('modified') is False
                    and r.get('final_record', {}).get('valid') is True
                    and r.get('session_id') and r.get('_actor')
                    and reviews.independent(r['_label'])
                    and (point['mode'] not in reviews.REVIEWER_MODES
                         or r.get('_independence', {}).get('independent', False))}
        # Family is descriptive, including when unknown. Candidate counts, distinct sessions,
        # custody and blocking findings remain admission requirements.
        row = {**point, 'roles': missing[point['id']], 'blocking_findings': findings,
               'pending': bool(missing[point['id']] or findings), 'family_diversity_pending': False}
        if 'min_model_families' in point:
            row['family_label'] = family_label(families)
        from . import rdj_approval
        if point['row'] == 'K8' and rdj_approval.applies(root):
            from ravel.controller.graph import delivery_assumption_evidence
            observed = delivery_assumption_evidence(root)
            row.update(observed, pending=observed['status'] != 'satisfied' or bool(findings))
            if not row['pending']:
                row['roles'] = []
        result.append(row)
    return result


def pending(rundir, *, gate=None, action=None):
    """The unfilled rows of report(), preserving the legacy pending-row shape."""
    return [{k: v for k, v in row.items() if k != 'pending'}
            for row in report(rundir, gate=gate, action=action) if row['pending']]


def family_label(families):
    """The candidate-family label of an evaluated-author point (K4): a statement, never a hold."""
    if not families or None in families or '' in families or 'unknown' in families:
        return 'model family unknown'
    return 'single model family' if len(families) == 1 else 'several model families'


def gate_errors(rundir, gate, action):
    from .decision_gate import GateError
    from . import rdj_approval
    controlled = rdj_approval.applies(rundir)
    return [GateError('spawn_review_pending', gate, 'spawn_rows', 'Required staffing pending: ' + p['id'],
                      'Dispatch the derived roles and register their independent receipts.', (p['id'],))
            for p in pending(rundir, gate=gate, action=action)
            if (reviews._weighs(p, gate, action) if controlled and p['row'] != 'K8' else p['gate'] == gate)
            and p['blocking']
            and (not action.get('node_id') or action['node_id'] == p.get('node_id'))
            and (not action.get('claim_id') or action['claim_id'] == p.get('claim_id'))]


def compare_analytic(first, second, *, relative_tolerance, absolute_tolerance=0):
    """Compare extracted scalar outputs with declared common units and tolerance.

    Callers extract the contracted quantity from resonance-width/formula-grid
    output records; uncertainty or method independence is not inferred here.
    """
    def number(value):
        if type(value) not in {int, float} or not math.isfinite(value):
            raise ValueError('analytic comparison requires finite numeric values')
        return value
    a, b = number(first['value']), number(second['value'])
    rel, absolute = number(relative_tolerance), number(absolute_tolerance)
    if rel < 0 or absolute < 0 or not first.get('unit') or first.get('unit') != second.get('unit'):
        raise ValueError('analytic comparison requires common units and nonnegative tolerances')
    delta = abs(a - b)
    value = {'schema_version': 1, 'kind': 'analytic-comparison', 'first': first, 'second': second,
             'relative_tolerance': rel, 'absolute_tolerance': absolute, 'difference': delta,
             'passed': delta <= absolute + rel * max(abs(a), abs(b))}
    return {**value, 'sha256': jdigest(value)}


def compare_outputs(root, first, second, *, pointer, unit, relative_tolerance, absolute_tolerance=0, second_pointer=None):
    """Extract one declared JSON-pointer quantity from byte-pinned method outputs."""
    from ravel.validation.input_closure import _read
    second_pointer = pointer if second_pointer is None else second_pointer
    if any(not isinstance(p, str) or not p.startswith('/') for p in (pointer, second_pointer)):
        raise ValueError('analytic output comparison requires JSON pointers')
    values = []
    for pin, quantity_pointer in zip((first, second), (pointer, second_pointer)):
        value = json.loads(_read(root, pin))
        try:
            for token in quantity_pointer[1:].split('/'):
                token = token.replace('~1', '/').replace('~0', '~')
                value = value[int(token)] if isinstance(value, list) else value[token]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError('analytic output quantity is unavailable: ' + quantity_pointer) from exc
        values.append({'value': value, 'unit': unit})
    result = compare_analytic(*values, relative_tolerance=relative_tolerance, absolute_tolerance=absolute_tolerance)
    result.update(first_pin=deepcopy(first), second_pin=deepcopy(second), pointer=pointer, second_pointer=second_pointer)
    result.pop('sha256')
    return {**result, 'sha256': jdigest(result)}
