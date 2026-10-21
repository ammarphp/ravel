"""Second-method, assumption-audit, model-critic and explore/exploit staffing rows.

``spawn_rows.derive`` calls ``derive_roles`` once with its own ``add`` so these
rows share its review-point shape, custody and gate. Thresholds, operations and
the default split are data in ``knowledge/spawn_rows.json``. No worker is launched.
"""
from __future__ import annotations


def explore_exploit_split(row, metadata):
    """Return the round's integer split of its attempt budget, declared or default.

    A declared split must name exactly ``exploit`` and ``explore`` counts that sum
    to the budget. The default rounds the exploit share down; the remainder goes
    to the row's ``remainder_to`` side.
    """
    budget = metadata.get('attempt_budget', row['default_attempt_budget'])
    if type(budget) is not int or budget < 1:
        raise ValueError('explore/exploit split requires a positive integer attempt budget')
    declared = metadata.get('explore_exploit')
    if declared is None:
        exploit = int(budget * row['default_exploit_fraction'])
        if row['remainder_to'] == 'exploit':
            exploit = budget - int(budget * (1 - row['default_exploit_fraction']))
        return {'attempt_budget': budget, 'exploit': exploit, 'explore': budget - exploit, 'declared': False}
    if not isinstance(declared, dict) or set(declared) != {'exploit', 'explore'}:
        raise ValueError('explore/exploit split must declare exactly exploit and explore counts')
    if any(type(v) is not int or v < 0 for v in declared.values()) or sum(declared.values()) != budget:
        raise ValueError('explore/exploit split counts must be nonnegative integers summing to the attempt budget')
    return {'attempt_budget': budget, 'exploit': declared['exploit'], 'explore': declared['explore'], 'declared': True}


def derive_roles(plan, nodes, bases, rows, points, add, review_metadata):
    staffed = {p['claim_id'] for p in points if p['row'] == 'K7'}
    row = rows['K7S']
    elements = {b['element'] for b in row['basis']}
    for claim in sorted(plan.get('claims', []), key=lambda c: c['id']):
        if claim['id'] in staffed:
            continue  # K7's re-deriver already carries the first-method prohibition here.
        computed = [r for r in bases.get(claim['id'], []) if r['element'] in elements]
        if computed:
            add('K7S', claim['id'], claim=claim['id'],
                forbidden_method_nodes=sorted({v for r in computed for v in r['via']}),
                comparison_required=True, tolerance_required=True)
    # The delivery's assumptions are audited whenever a result is claimed, and whenever the run took a machine
    # assumption or holds a conditional result (``controller.graph`` assumptions), claims or not.
    if plan.get('claims') or plan.get('machine_assumptions'):
        row = rows['K8']
        add('K8', 'run', when={'trigger': row['trigger'], 'at': 'delivery:run'},
            severity_floor=row['severity_floor'], severity_max=row['severity_max'],
            uncontrolled_at_floor_in_result=True)
    model, research = rows['K10'], rows['K11']
    for node in sorted(nodes, key=lambda n: n['id']):
        metadata = review_metadata(node)
        author_kind = metadata.get('author_kind', node.get('authors'))
        if (node.get('implementation') in model['implementations'] or node.get('operation') in model['operations']
                or author_kind in model['author_kinds']):
            add('K10', node['id'], node=node['id'])
        if (node.get('kind') in research['node_kinds'] or node.get('implementation') in research['implementations']
                or 'attempt_budget' in metadata or 'explore_exploit' in metadata):
            split = explore_exploit_split(research, metadata)
            roles = [{'role': research[side + '_role'], 'count': split[side]}
                     for side in ('exploit', 'explore') if split[side]]
            add('K11', node['id'], node=node['id'], roles=roles, budget_split=split,
                when={'trigger': research['trigger'], 'at': 'research_choice:' + node['id']})
