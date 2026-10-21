"""Mandatory epoch-two review points computed from typed plan facts.

This module owns derivation and receipt inspection, not worker execution. The
review graph consumes stable pending points and their missing role counts.
"""
from __future__ import annotations
from copy import deepcopy
from importlib.resources import files
import hashlib
import json
from pathlib import Path, PurePosixPath

from .state_io import read_json, atomic_json
from .decision_case import ATTESTATION_RANK, independent, label_for, jdigest


def matches_at(point, at):
    """Select an exact review point or the complete CHECK-IN 2 population."""
    actual = point['when']['at']
    return actual == at or (at == 'checkin2' and (
        actual.startswith('checkin2:') or point.get('gate') == 'checkin2_accept'))


def population(facts):
    """Core review points and conditional staffing, retaining each policy identity."""
    from . import spawn_rows
    return [*derive(facts), *spawn_rows.derive(facts)]


def _catalogue():
    return json.loads(files('ravel').joinpath('data/review_points.json').read_text())


def delegated_contract(contract, root=None) -> bool:
    """Whether the run records a delegation.

    The delegation record is the contract's ``autonomy`` pin (written at intake) or, for a
    delegation granted in the CHECK-IN 1 response, the transition beside the contract
    (``scientific_autonomy.effective_document``): the contract is byte-bound to its run_init
    snapshot, so a later delegation can only be that sidecar. The older ``delegated`` and
    ``delegation`` keys still count. A transition that does not belong to this contract is
    refused, never read as "not delegated".
    """
    if contract.get('autonomy') or contract.get('delegated') or contract.get('delegation'):
        return True
    if root is None:
        return False
    from . import scientific_autonomy
    try:
        return 'autonomy' in scientific_autonomy.effective_document(contract, Path(root))
    except (OSError, KeyError, TypeError) as exc:
        raise ValueError(f'CI1 authority transition cannot be read: {exc}') from None


def _facts(rundir: Path) -> dict:
    """Single intake seam: read the contract and its byte-bound request plan."""
    root = Path(rundir)
    path = root / 'inputs/task_contract.json'
    from . import rdj_custody
    raw = path.read_bytes()
    contract = json.loads(raw)
    if not isinstance(contract, dict):
        raise ValueError('task contract must be an object')
    from ravel.controller.routes.study import child_contract
    child_contract.paths(root)
    epoch = contract.get('agent_layer_epoch', 1)
    if type(epoch) is not int or epoch not in {1, 2}:
        raise ValueError('agent_layer_epoch must be integer 1 or 2')
    original = rdj_custody.snapshot_digest(root, 'inputs/task_contract.json', event='run_init')
    has_snapshot = any(row['record']['event'] == 'run_init' for row in rdj_custody.rows(root, 'inputs'))
    if has_snapshot and hashlib.sha256(raw).hexdigest() != original:
        raise ValueError('task contract differs from run_init snapshot')
    if epoch == 1:
        return {'agent_layer_epoch': 1}
    pin = contract.get('request_plan')
    if not isinstance(pin, dict):
        raise ValueError('epoch two requires request_plan pin')
    path = (root / pin['path']).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('request plan must be confined to the run')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != pin['sha256']:
        raise ValueError('request-plan pin changed')
    plan = json.loads(raw)
    if not isinstance(plan, dict):
        raise ValueError('request plan must be an object')
    value = deepcopy(plan)
    value.update(agent_layer_epoch=2, delegated=delegated_contract(contract, root), contract=contract, plan=plan)
    from . import project_instructions
    pinned = project_instructions.for_run(root)
    if pinned is not None:
        value['project_instructions'] = pinned
    value['machine_assumptions'] = machine_assumptions(root)
    return value


def machine_assumptions(root):
    """How many machine assumptions, alternative branches and machine-taken defaults the controller recorded."""
    from .review_independence import controller_store
    store = controller_store(root)
    if store is None:
        return 0
    return sum(1 for row in store.scan('assumption') if row['record'].get('phase') in ('proposed', 'alternative', 'default_taken',
                                                                                'conditional_approval'))


def _safe_write(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or '..' in path.parts or str(path) == '.':
        raise ValueError('parallel write sets must be distinct confined relative paths')
    return path


def parallel_safety(node: dict) -> dict:
    """Compute fan-out admissibility; a declared parallel_safe flag has no effect."""
    fan = node.get('fan_out') or (node if node.get('kind') == 'map' else None)
    if not fan:
        return {'safe': True, 'parallel': False}
    workers = fan.get('workers')
    # Existing native partition plans use axes/subgraph/aggregate. They do not
    # dispatch agent workers and remain under the backend's single-native lease.
    if workers is None and node.get('kind') != 'map' and 'axes' in fan:
        return {'safe': True, 'parallel': False, 'executor': 'backend'}
    if not isinstance(workers, list) or len(workers) < 2:
        raise ValueError('parallel fan-out requires the explicit worker population')
    seen_paths, receipt_ids = [], set()
    for worker in workers:
        writes, inputs = worker.get('write_set'), worker.get('inputs')
        if not writes or not isinstance(inputs, list) or not inputs:
            raise ValueError('parallel workers require write sets and pinned inputs')
        for pin in inputs:
            sha = pin.get('sha256', '')
            if not pin.get('path') or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
                raise ValueError('parallel worker input is not pinned')
        rid = worker.get('receipt_id')
        if not rid or rid in receipt_ids:
            raise ValueError('parallel outputs require separate receipt ids')
        receipt_ids.add(rid)
        current = [_safe_write(value) for value in writes]
        for path in current:
            if any(path == other or path in other.parents or other in path.parents for other in seen_paths):
                raise ValueError('parallel workers have overlapping write sets')
        seen_paths.extend(current)
    join = fan.get('join', {})
    if not isinstance(join, dict) or join.get('kind') not in {'computed_comparison', 'reviewed_selection'}:
        raise ValueError('parallel join requires computed comparison or reviewed selection')
    if join['kind'] == 'reviewed_selection' and not join.get('receipt_id'):
        raise ValueError('reviewed selection must name its review receipt')
    arm = fan.get('single_worker', {})
    cap = fan.get('budget_cap')
    if (not isinstance(arm, dict) or arm.get('kind') not in {'arm', 'estimate'} or cap is None
            or arm.get('budget_cap') != cap):
        raise ValueError('parallel work requires a single-worker arm or estimate at the same cap')
    return {'safe': True, 'parallel': True, 'receipt_ids': sorted(receipt_ids), 'join': deepcopy(join)}


def _calibrations(node):
    fields = {f.get('pointer'): f.get('value') for f in node.get('fields', [])}
    provenance = node.get('parameter_provenance') or fields.get('/parameter_provenance') or fields.get('/task/parameter_provenance') or []
    result = list(provenance)
    result = [p for p in result if p.get('basis') in {'agreement_with_observed', 'observed_data'} or p.get('tuning_to_observed')]
    if node.get('tuning_to_observed') or fields.get('/task/tuning_to_observed') is True:
        result.append({'choice': node.get('id'), **(node.get('calibration') or {})})
    return result


def _observed(node):
    from ravel.validation.validate_request_plan import signatures
    fields = {f.get('pointer'): f.get('value') for f in node.get('fields', [])}
    operation = node.get('operation')
    statistical = any(p['kind'] == 'inference' for p in signatures().get(operation, {}).get('produces', []))
    level = node.get('level') or fields.get('/level') or fields.get('/task/level')
    observed = any(fields.get(p) is True for p in ('/observed', '/task/observed', '/observed_statistic', '/task/observed_statistic'))
    return (node.get('observed_statistic') is True or operation in {'observed-statistic', 'unblind'} or
            statistical and (level == 'observed' or observed))


def derive(facts: dict) -> list[dict]:
    if facts.get('agent_layer_epoch') != 2:
        return []
    from ravel.validation.validate_request_plan import computed_bases, certificate_relevant, signatures
    from .normalization_policy import normalization_disposition
    data = _catalogue(); rows = {r['row']: r for r in data['rows']}
    plan = deepcopy(facts.get('plan', facts))
    for node in plan.get('nodes', []):
        node.setdefault('kind', 'operation')
        node.setdefault('authored', None)
        node.setdefault('fields', [])
    nodes, claims = plan.get('nodes', []), plan.get('claims', [])
    delegated = facts.get('delegated', False)
    for node in nodes:
        parallel_safety(node)
    bases = computed_bases(plan, signatures())
    result = []

    def add(row, scope, at, *, roles=None, suffix='', group=None, **extra):
        source = rows[row]
        names = source['roles'] if roles is None else roles
        # ``distinct_family_from`` is retired and always empty; it stays so approved point digests do not change.
        entries = [{'role': role, 'count': 1, 'distinct_family_from': []} if isinstance(role, str) else role for role in names]
        point = {'id': f'RP{row}:{scope}' + (':' + suffix if suffix else ''), 'row': row,
                 'when': {'trigger': source['trigger'], 'at': at}, 'roles': entries,
                 'mode': source['mode'], 'blocking': row not in {1, 3, 15}, 'gate': source['gate'],
                 'parallel_group': group, 'attestation_min': 'transport' if delegated else 'self', **extra}
        result.append(point)
        return point

    if any(n.get('operation') or n.get('authored') is not None for n in nodes):
        add(1, 'plan', 'checkin1', blocking=delegated, mode='voting' if delegated else 'advisory')
    for node in sorted(nodes, key=lambda n: n['id']):
        nid = node['id']
        if node.get('authored') is not None:
            kind = node.get('authors', node.get('artifact_kind', 'spec'))
            role = data['author_roles'].get(kind, 'spec-author')
            add(2, nid, 'node:' + nid, roles=[role], node_id=nid,
                blocking=node.get('rung') in {'full', 'scan'})
        tool = node.get('tool') or node.get('operation')
        if tool and (node.get('rung') == 'full' or node.get('status') == 'failed'):
            add(3, nid, ('on_failure:' if node.get('status') == 'failed' else 'node:') + nid,
                roles=['consult-' + tool], node_id=nid, blocking=node.get('status') == 'failed')
        calibration = _calibrations(node)
        if calibration:
            add(16, nid, 'checkin2:' + nid, node_id=nid, rdj_class='R2', decision_class='calibration',
                calibration_choices=calibration, receipt_gate='checkin2_accept')
        if _observed(node):
            add(17, nid, 'node:' + nid, node_id=nid, rdj_class='R3', human_approval=True, receipt_gate='unblind')
    for claim in sorted(claims, key=lambda c: c['id']):
        cid = claim['id']; at = 'checkin2:' + cid; group = 'ci2:' + cid + ':first-pass'
        for role in rows[4]['roles']:
            add(4, cid, at, roles=[role], suffix=role, group=group if role == 'physics-critic' else None,
                claim_id=cid)
        computed = bases.get(cid, [])
        elements = {r['element'] for r in computed} | set(claim.get('basis_declared', []))
        normalization = normalization_disposition(plan, claim, reg=signatures(), bases=bases)
        if normalization['applicable']:
            add(5, cid, at, group=group, claim_id=cid, requires_certificate=certificate_relevant(computed))
        if (any(r['element'] == 'simulated_acceptance' and r.get('origin') in {'reimplemented', 'designed'} for r in computed)
                or 'authored_code' in elements):
            add(6, cid, at, roles=['object-selection-mapper'], group=group, claim_id=cid)
            add(6, cid, at, roles=[{'role': 'analysis-author', 'count': 2, 'distinct_family_from': []}],
                suffix='divergence', group='implementation:' + cid, claim_id=cid, mode='producer',
                comparison_required=True)
        if claim.get('kind') == 'agreement' or claim.get('reference_deviation') is not None:
            add(7, cid, at, group=group, claim_id=cid)
        if facts.get('trap_sweep') or plan.get('trap_sweep'):
            add(8, cid, at, group=group, claim_id=cid)
        if (claim.get('deliverable') or {}).get('artifact') in {'figure', 'plot'} or claim.get('figure'):
            add(10, cid, 'delivery', claim_id=cid)
        if claim.get('kind') == 'document':
            add(14, cid, 'delivery', claim_id=cid)
    if facts.get('failed_stage') or facts.get('failed_trigger') or any(n.get('status') == 'failed' for n in nodes):
        add(9, 'failure', 'on_decision:correction')
    # Every run is a potential parent delivery, including summary-only work.
    for role in rows[11]['roles']:
        add(11, 'parent', 'checkin3', roles=[role], suffix=role)
    for decision in facts.get('decisions', []):
        add(12, decision['id'], 'on_decision:' + decision['gate'], gate=decision['gate'],
            rdj_class=decision.get('risk_class', 'R1'))
    if (facts.get('route') == 'E' or any(c.get('kind') == 'method_performance' for c in claims)
            or any(n.get('operation') in {'method-study', 'anomaly-search', 'research'} for n in nodes)):
        from .research_protocol import default_protocol
        for stage in default_protocol()['stages']:
            add(13, stage['id'], 'protocol:' + stage['id'], roles=stage['roles'], protocol_stage=stage['id'])
    if facts.get('upstream_self_review'):
        add(15, 'upstream', 'checkin2', generated_claim=True)
    for point in result:
        point['depends_on'] = []
        if point['row'] not in {4, 11}: continue
        role = point['roles'][0]['role']
        same = [p for p in result if (p.get('claim_id') == point.get('claim_id')
                and (p['row'] == 11) == (point['row'] == 11))]
        if role == 'skeptical-verifier':
            point['depends_on'] = [p['id'] for p in same if p['id'] != point['id'] and
                (p['parallel_group'] is not None or p['roles'] and p['roles'][0]['role'] == 'physics-critic')]
        elif role == 'physics-decider':
            point['depends_on'] = [p['id'] for p in same if p['roles'] and
                p['roles'][0]['role'] in {'physics-critic', 'skeptical-verifier'}]
    order = {'physics-critic': 0, 'skeptical-verifier': 1, 'physics-decider': 2}
    return sorted(result, key=lambda p: (p['row'], p.get('claim_id', ''),
        order.get(p['roles'][0]['role'], 0) if p['roles'] else 0, p['id']))


REVIEW_RECEIPT_VERSIONS = (2, 3)
# Point modes whose credit needs an actor: one dispatcher-assigned worker session per credited receipt.
ACTOR_MODES = ('specialist', 'voting', 'producer')
REVIEWER_MODES = ('specialist', 'voting')


def subject_digest(facts, point):
    """Bind a review to the exact current claim/node and its stable point ID."""
    plan = facts.get('plan', facts)
    if point.get('claim_id'):
        subject = next(c for c in plan['claims'] if c['id'] == point['claim_id'])
    elif point.get('node_id'):
        subject = next(n for n in plan['nodes'] if n['id'] == point['node_id'])
    else:
        subject = plan
    return jdigest({'point_id': point['id'], 'subject': subject})


def subject_scope(point):
    """The claim-scope id a review subject names: the point's claim, its node, or the plan."""
    if point.get('claim_id'):
        return 'claim:' + point['claim_id']
    if point.get('node_id'):
        return 'node:' + point['node_id']
    return 'plan'


def review_subject(facts, point):
    """The ``review_subject`` a version-2 worker receipt must carry to earn credit for ``point``."""
    return {'scope': subject_scope(point), 'sha256': subject_digest(facts, point)}


def reviewed_by_seats(role, seats=()):
    """The review seats a producer's card owes (``reviewed_by``), minus those already held.

    Seat derivation adds one seat per named reviewer that ``seats`` (role ids or seat records)
    does not hold; a caller-supplied seat list can add seats but never remove these. Each seat
    is a specialist or voting seat of the reviewer card, blocking delivery until credited.
    """
    from . import role_registry
    card = role_registry.load(role)
    held = {s.get('role') if type(s) is dict else s for s in seats}
    owed = []
    for reviewer in card.get('reviewed_by') or []:
        if reviewer in held:
            continue
        kind = role_registry.load(reviewer)['independence']['kind']
        owed.append({'role': reviewer, 'count': 1, 'mode': kind if kind in REVIEWER_MODES else 'specialist',
                     'blocking': True, 'gate': 'delivery', 'reason': 'reviewed_by:' + role})
    return owed


def must_check_missing(items, final_record):
    """The ``must_check`` items a reviewer's output leaves without a verdict; empty when complete.

    Each item needs one checklist row ``{unit: <item>, status, evidence, note}`` in the output: ``done``
    with an evidence pointer, or ``not_applicable`` with a note. ``blocked``, a missing row or an empty
    pointer leaves the item open, and the seat earns no credit while any item is open.
    """
    rows = (final_record or {}).get('checklist') if type(final_record) is dict else None
    rows = [r for r in rows if type(r) is dict] if type(rows) is list else []
    missing = []
    for item in items:
        mine = [r for r in rows if r.get('unit') == item]
        status = mine[-1].get('status') if mine else None
        evidence, note = (mine[-1].get('evidence'), mine[-1].get('note')) if mine else (None, None)
        if not (status == 'done' and type(evidence) is str and evidence.strip()
                or status == 'not_applicable' and type(note) is str and note.strip()):
            missing.append(item)
    return missing


def credit_refusal(receipt, facts, point):
    """Why a registered worker receipt earns no credit for ``point``; None when its subject matches.

    Readers dispatch on the receipt version. Version 1 predates ``review_subject``: it stays
    valid for its original use but earns no review credit. Versions 2 and 3 must name this
    point's current subject scope and digest.
    """
    if receipt.get('kind') != 'agent-worker-receipt':
        return 'receipt_invalid'
    if receipt.get('schema_version') == 1:
        return 'receipt_predates_review_subject'
    if receipt.get('schema_version') not in REVIEW_RECEIPT_VERSIONS:
        return 'receipt_invalid'
    if point is None or receipt.get('review_subject') != review_subject(facts, point):
        return 'review_subject'
    pinned = facts.get('project_instructions')
    if pinned is not None:
        # The run pins a project instruction document: a session that was not shown it earns no credit.
        from . import project_instructions
        if project_instructions.receipt_problem(receipt, pinned) is not None:
            return 'project_instructions'
    return None


def approve(rundir):
    """Record the derived obligations as part of the approval-owned policy."""
    root = Path(rundir)
    if not (root / 'inputs/task_contract.json').exists():
        return None  # Older approval routes may use the root-level contract layout.
    facts = _facts(root)
    if facts['agent_layer_epoch'] != 2:
        return None
    path = root / 'inputs/review_points_approval.json'
    points = derive(facts)
    value = {'schema_version': 1, 'derived_points_sha256': jdigest(points),
             'subjects': {p['id']: subject_digest(facts, p) for p in points}}
    from . import review_rubric
    rubric = review_rubric.selected(root)
    if (rubric or {}).get('executable_checks'):
        value['executable_rubric_sha256'] = review_rubric.digest(rubric)
    atomic_json(path, value)
    return value


def invalid_input_diagnostics(rundir, gate, action):
    """Additional refusals only: changed untrusted bytes can never grant credit.

    The caller has already refused gate_inputs_invalid. Preserve useful subject
    and obligation diagnostics even when plan/contract pins fail first.
    """
    root = Path(rundir).resolve()
    contract = read_json(root / 'inputs/task_contract.json')
    if type(contract.get('agent_layer_epoch')) is not int or contract['agent_layer_epoch'] != 2:
        return []
    approval = read_json(root / 'inputs/review_points_approval.json')
    path = (root / contract['request_plan']['path']).resolve()
    if not path.is_relative_to(root):
        return []
    plan = read_json(path)
    facts = {**plan, 'plan': plan, 'agent_layer_epoch': 2, 'delegated': delegated_contract(contract, root)}
    points = derive(facts)
    errors = []
    if approval.get('derived_points_sha256') != jdigest(points):
        errors.append(_error(gate, 'obligations_changed', ['approval:derived_points_sha256'],
                             'Changed untrusted plan bytes also change the approved obligations.'))
    for point in points:
        if point.get('claim_id') and (gate != 'checkin2_accept' or action.get('claim_id') in {None, point['claim_id']}):
            if approval.get('subjects', {}).get(point['id']) != subject_digest(facts, point):
                errors.append(_error(gate, 'review_point_pending', [point['id'] + ':review_subject'],
                                     'Changed claim bytes invalidate its review subject.'))
    from . import rdj_loop
    errors.extend(rdj_loop.gate_errors(root, gate, action))
    return errors


def attestation_label(receipt, registered_verified_label=None):
    mode = receipt.get('execution_mode')
    if mode == 'human_manual':
        # No human-review provenance producer exists yet. A body claim, even
        # registered as a worker receipt, is not a registered human review.
        return 'self_attested'
    # Even an observed HTTP mode must come from a custody registration with a
    # dispatcher-verified label. Receipt fields never confer this authority.
    if registered_verified_label is None:
        return 'self_attested'
    derived = label_for(mode, registered_verified_label)
    if registered_verified_label not in ATTESTATION_RANK:
        return 'self_attested'
    return min((derived, registered_verified_label), key=ATTESTATION_RANK.__getitem__)


def worker_label(receipt, registered_verified_label=None):
    """The label of a registered receipt. The worker dispatcher registers each review receipt
    with the label it computed from the transport's own verification; that registration is the
    authority, never the receipt's ``attestation`` field. A version-3 receipt also carries the
    launch mode the dispatcher observed, and its label is the weaker of the two. A version-2
    receipt written before the mode existed takes the registered label."""
    if receipt.get('schema_version') == 2 and 'execution_mode' not in receipt:
        from .rdj_custody import WORKER_LABELS
        return registered_verified_label if registered_verified_label in WORKER_LABELS else 'self_attested'
    return attestation_label(receipt, registered_verified_label)


def registered_actor(receipt, registration):
    """The actor the worker dispatcher assigned to this receipt's worker session, or None.

    The custody registration is the authority: it carries the transport id, model id, worker
    session id and attempt id the dispatcher bound at spawn, and their sha256. The receipt's
    ``actor_id`` must equal that digest, and the bound attempt and transport must be the
    receipt's own. A receipt that only declares an ``actor_id`` has no actor.
    """
    from .rdj_custody import ACTOR_FIELDS, actor_id
    actor = (registration or {}).get('actor')
    if type(actor) is not dict:
        return None
    try:
        expected = actor_id(*(actor.get(k) for k in ACTOR_FIELDS))
    except ValueError:
        return None
    if actor.get('actor_id') != expected or receipt.get('actor_id') != expected:
        return None
    if actor['attempt_id'] != f"{receipt.get('node_id')}/{receipt.get('attempt')}":
        return None
    transport = receipt.get('transport')
    if type(transport) is dict and transport.get('id') not in (None, actor['transport_id']):
        return None
    # The registered family is the trusted one. A receipt that states another family is not this actor's.
    stated = (receipt.get('model') or {}).get('family')
    if stated is not None and actor.get('family') is not None and stated != actor['family']:
        return None
    return dict(actor)


def _is_producer(receipt, point):
    return (receipt.get('final_record') or {}).get('schema') == 'producer.v1' or (point or {}).get('mode') == 'producer'


def _session_keys(rec):
    """What makes one credited worker session distinct: its observed session on its transport, its
    actor and the worker session the dispatcher drew. The actor is the registered one."""
    actor = rec['_actor']
    return {('session', actor['transport_id'], rec.get('session_id')), ('actor', actor['actor_id']),
            ('worker_session', actor['worker_session_id'])}


def _claim_nodes(plan):
    """For each claim, the plan nodes its result is computed from: the nodes it inherits and
    every node upstream of them along the plan's edges."""
    parents = {}
    for edge in plan.get('edges') or []:
        source, target = (edge.get('from') or {}).get('ref'), (edge.get('to') or {}).get('ref')
        if source and target:
            parents.setdefault(target, set()).add(source)
    found = {}
    for claim in plan.get('claims') or []:
        nodes, queue = set(), list(claim.get('inherits') or [])
        while queue:
            node = queue.pop()
            if node not in nodes:
                nodes.add(node)
                queue.extend(parents.get(node, ()))
        found[claim['id']] = nodes
    return found


def output_scopes(point, plan):
    """The outputs a point concerns: its claim with the nodes that claim is computed from, its
    node with the claims computed from it, or (``*``) the whole plan."""
    nodes = _claim_nodes(plan or {})
    if point.get('claim_id'):
        return {'claim:' + point['claim_id'], *('node:' + n for n in nodes.get(point['claim_id'], ()))}
    if point.get('node_id'):
        return {'node:' + point['node_id'], *('claim:' + c for c, used in nodes.items() if point['node_id'] in used)}
    return {'*'}


def producer_sessions(records, points, facts=None):
    """For each reviewer point, the session keys of the producers of the output it reviews.

    A producer's actor never reviews its own output. A producer is known only from verified
    custody: a registered receipt with the actor the dispatcher assigned. A record that is
    unregistered, or only states an actor, names no producer and removes no credit. The
    exclusion follows the output: a producer of one claim or node is excluded from the points
    that review that claim or node (and from a point that reviews the whole plan), not from the
    review of an independent claim.
    """
    plan = (facts or {}).get('plan') or {}
    by_id = {p['id']: p for p in points}
    producers = []
    for rec in records:
        point = by_id.get(rec.get('review_point_id'))
        if rec.get('_actor') is None or not _is_producer(rec, point):
            continue
        made = output_scopes(point if point is not None else {'node_id': rec.get('node_id')}, plan)
        producers.append((_session_keys(rec), made))
    excluded = {}
    for point in points:
        if point['mode'] not in REVIEWER_MODES:
            continue
        reviewed = output_scopes(point, plan)
        excluded[point['id']] = set().union(*(keys for keys, made in producers
                                              if '*' in made or '*' in reviewed or made & reviewed))
    return excluded


def finding_record(finding):
    """Adapt old review records to the canonical RDJ evidence vocabulary."""
    if 'evidence_class' in finding:
        return finding
    kind = next((k for k in ('new_receipt', 'code_check', 'evidence_request') if finding.get(k)), 'opinion')
    value = finding.get(kind) or {}
    return {**finding, 'materiality': finding.get('severity', 'A' if finding.get('blocking') else 'C'),
            'evidence_class': kind, 'evidence_locators': [value['id']] if value.get('id') else []}


def blocking_finding(root, finding):
    """Resolve evidence; neither an opinion nor a self-declared check blocks."""
    from . import rdj_loop
    f = finding_record(finding)
    if f.get('status') in {'closed', 'resolved'} or f.get('materiality') not in {'A', 'B'}:
        return False
    if f['evidence_class'] in {'new_receipt', 'code_check'}:
        return rdj_loop.critic_basis(root, None, f) == 'verified'
    if f['evidence_class'] == 'evidence_request':
        return any(not rdj_loop.evidence_request_answered(root, item_id) for item_id in f['evidence_locators'])
    return False


def _receipt_records(root, facts):
    from . import rdj_custody
    from . import review_rubric
    root = Path(root).resolve()
    points = {p['id']: p for p in population(facts)}
    rubric = review_rubric.selected(root)
    approval = root / 'inputs/review_points_approval.json'
    approved = read_json(approval).get('executable_rubric_sha256') if approval.exists() else None
    if approved is not None and (rubric is None or review_rubric.digest(rubric) != approved):
        raise ValueError('the approved executable review rubric changed or is absent')
    check_contracts = (rubric or {}).get('executable_checks', [])
    for path in sorted((root / 'agent-work').glob('*/*/receipt.json')):
        rel = path.relative_to(root).as_posix()
        value = read_json(path)
        value['_path'] = rel
        value['_eligible'] = False
        value['_label'] = 'self_attested'
        value['_actor'] = None
        from . import review_independence
        value['_independence'] = review_independence.advisory('receipt_unregistered')
        reason = 'receipt_unregistered'
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.resolve().is_relative_to(root) and rdj_custody.worker_registered(root, rel, digest):
            registration = rdj_custody.worker_row(root, rel, digest)
            value['_label'] = worker_label(value, registration.get('verified_label'))
            value['_actor'] = registered_actor(value, registration)
            reason = 'receipt_invalid'
            final = value.get('final_record') or {}
            point = points.get(value.get('review_point_id'))
            if (value.get('kind') == 'agent-worker-receipt' and value.get('schema_version') in (1, *REVIEW_RECEIPT_VERSIONS)
                    and final.get('path')):
                target = (path.parent / final['path']).resolve()
                if (target.is_relative_to(path.parent.resolve()) and target.is_relative_to(root) and target.is_file()
                        and hashlib.sha256(target.read_bytes()).hexdigest() == final.get('sha256')):
                    value['findings'] = read_json(target).get('findings', [])
                    reason = credit_refusal(value, facts, point)
                    required = [row for row in check_contracts if value.get('role', {}).get('id') in row['roles']]
                    if reason is None and required and point['mode'] in REVIEWER_MODES:
                        value['_executable_checks'] = [_executable_check(root, value, row) for row in required]
                        if any(row['execution'] != 'completed' for row in value['_executable_checks']):
                            reason = 'executable_check_missing'
                        elif any(row['status'] != 'passed' for row in value['_executable_checks']):
                            reason = 'executable_check_failed'
                        elif any(row['require_distinct_method'] and row['method_independence'] != 'verified'
                                 for row in value['_executable_checks']):
                            reason = 'method_separation_unverified'
                    value['_eligible'] = reason is None
                    if reason is None and point['mode'] in ACTOR_MODES and value['_actor'] is None:
                        # Still listed for its findings; it earns no credit at this point.
                        reason = 'actor_unassigned'
                    if reason is None and point['mode'] in REVIEWER_MODES and not independent(value['_label']):
                        # The label refusal is reported as itself; no dispatch can make it independent.
                        value['_independence'] = review_independence.advisory('self_attested')
                    elif reason is None and point['mode'] in REVIEWER_MODES:
                        value['_independence'] = review_independence.decide(
                            review_independence.worker_query(root, value, digest,
                                subject_sha256=review_subject(facts, point)['sha256']))
                        if not value['_independence']['independent']:
                            reason = value['_independence']['advisory']
                            # Ordinary receipt eligibility retains its findings.
                            # Only the seat matcher grants independent credit.
        value['_advisory'] = reason
        yield value


def _executable_check(root, receipt, contract):
    """Verify a reviewer's own executed check of an exact projected subject.

    This inspects dispatcher and broker custody, never self-reported execution or
    method labels. Callable difference records software-route separation only.
    The current checker registry supplies no authenticated relationship between
    methods or quantities, so that difference cannot satisfy a method requirement.
    """
    from . import agent_worker, broker, review_projection, review_projection_checks as checks
    report = {'id': contract['id'], 'check_id': contract['check_id'], 'execution': 'not_verified', 'executed': False,
              'status': None, 'method_separation': 'unknown', 'producer_method': None, 'reviewer_method': None,
              'method_independence': 'unverified',
              'require_distinct_method': contract['require_distinct_method'], 'scientific_independence_proven': False}
    methods = {row['id']: (row['module'], row['function']) for row in checks.allowlist()['validators']}
    try:
        subject = contract['subject']
        current = broker.confined(root, subject['path'])
        if not current.is_file() or broker.sha(current) != subject['sha256']:
            raise ValueError('check subject changed')
        node, attempt = receipt['node_id'], receipt['attempt']
        materialized = agent_worker._record(root, node, attempt)
        spec = materialized['spec']
        if (spec['role']['id'] != receipt['role']['id']
                or spec['parent']['review_point_id'] != receipt['review_point_id']
                or spec['parent'].get('review_subject') != receipt.get('review_subject')):
            raise ValueError('materialized reviewer subject does not match its receipt')
        packet = materialized.get('packet')
        if packet is None:
            raise ValueError('check has no dispatcher-pinned review packet')
        manifest, _ = review_projection.load(packet)
        entries = [row for row in manifest['artifacts'] if row['source_path'] == subject['path']
                   and row['source_sha256'] == subject['sha256'] and row['sha256'] == subject['sha256']
                   and row['projection'] == review_projection.SUBJECT]
        if len(entries) != 1 or manifest['role'] != receipt['role']['id']:
            raise ValueError('check input is not an exact projected subject of this reviewer')
        copied = 'inputs/packet/' + entries[0]['path']
        if {'path': copied, 'sha256': subject['sha256']} not in materialized['input_copies']:
            raise ValueError('subject was not among the dispatcher-pinned input copies')
        expected = {'path': f'agent-work/{node}/{attempt}/' + copied, 'sha256': subject['sha256']}
        if broker.sha(broker.locate(root, expected['path'])) != expected['sha256']:
            raise ValueError('projected check input changed after execution')
        arguments = broker.digest({'check_id': contract['check_id'], 'paths': [copied]})

        def reset_execution(pin, *, executed):
            report.update(execution='not_verified', executed=executed, status=None,
                          reviewer_method=None, receipt=pin)
            report.pop('output', None)
            report.pop('reason', None)

        for row in broker.ledger(root, 'broker'):
            bound = row['record']
            if bound['node_id'] != node or bound['attempt'] != attempt:
                continue
            pin = {'path': bound['path'], 'sha256': bound['sha256']}
            try:
                body = broker.verify_broker_receipt(root, pin)
            except (OSError, ValueError, KeyError, TypeError):
                # Broken later custody cannot retain an earlier verified pass.
                reset_execution(pin, executed=False)
                raise
            if (body.get('action') != 'check run' or body.get('derivation') != 'registered_validator'
                    or body.get('validator_id') != contract['check_id']):
                continue
            if body.get('input_pins') != [expected]:
                if not body.get('input_pins'):
                    # A raised validator has no normalized subject pin. Exact
                    # arguments identify this subject; another digest cannot
                    # exclude a path alias, so neither case retains old credit.
                    reset_execution(pin, executed=True)
                    if body.get('args_sha256') != arguments:
                        report['reason'] = 'later validator has no authenticated subject pin'
                continue
            # Completed calls bind their subject through normalized input pins;
            # equivalent path spellings need not have equal argument digests.
            reset_execution(pin, executed=True)
            if (body.get('status') not in {'ok', 'failed'}
                    or len(body.get('output_pins', [])) != 1):
                continue
            report['output'] = deepcopy(body['output_pins'][0])
            output = body['output_pins'][0]
            result = read_json(broker.locate(root, output['path']))
            if (type(result) is not dict or result.get('kind') != checks.CHECK_RESULT_KIND
                    or result.get('producer') != checks.PRODUCER or result.get('check_id') != contract['check_id']
                    or type(result.get('findings')) is not list
                    or any(type(f) is not dict for f in result['findings'])):
                continue
            report['status'] = result.get('status')
            if result.get('status') == 'inconclusive':
                report['execution'] = 'inconclusive'
                continue
            if result.get('status') not in {'passed', 'failed'} or (result['status'] == 'passed') != (body.get('exit_status') == 0):
                continue
            if not (result.get('diagnostics') or result.get('findings')):
                report['execution'] = 'no_substantive_result'
                continue
            if result['status'] == 'passed' and any(f.get('materiality') in {'A', 'B'} for f in result['findings']):
                report['execution'] = 'conflicting_result'
                continue
            report.update(execution='completed', status=result['status'], receipt=pin, output=deepcopy(output),
                          reviewer_method=list(methods[contract['check_id']]))
        producer = contract['producer_receipt']
        if report['execution'] == 'completed' and producer is not None:
            body = broker.verify_broker_receipt(root, producer)
            if body.get('action') == 'check run' and body.get('derivation') == 'registered_validator' and body.get('validator_id') in methods \
                    and body.get('status') == 'ok' and body.get('exit_status') == 0 \
                    and len(body.get('output_pins', [])) == 1 and len(body.get('input_pins', [])) == 1 \
                    and body['input_pins'][0]['sha256'] == subject['sha256'] \
                    and all(broker.sha(broker.locate(root, pin['path'])) == pin['sha256'] for pin in body.get('input_pins', [])):
                result = read_json(broker.locate(root, body['output_pins'][0]['path']))
                if (type(result) is dict and result.get('kind') == checks.CHECK_RESULT_KIND
                        and result.get('producer') == checks.PRODUCER
                        and result.get('check_id') == body['validator_id'] and result.get('status') == 'passed'
                        and (result.get('diagnostics') or result.get('findings'))
                        and type(result.get('findings')) is list
                        and all(type(f) is dict and f.get('materiality') not in {'A', 'B'} for f in result['findings'])):
                    report['producer_method'] = list(methods[body['validator_id']])
                    report['method_separation'] = ('distinct_callable' if report['producer_method'] != report['reviewer_method']
                                                    else 'same_callable')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        report['reason'] = str(exc)
    return report


def _receipts(root, facts=None):
    facts = _facts(Path(root)) if facts is None else facts
    return (r for r in _receipt_records(root, facts) if r['_eligible'])


def _candidates(point, role, receipts, excluded):
    """The receipts that could fill a seat of ``role`` at ``point``, each checked on its own."""
    ranks = ATTESTATION_RANK
    found, seen = [], set()
    for rec in receipts:
        identity = (rec.get('node_id'), rec.get('attempt'))
        if (identity in seen or rec.get('review_point_id') != point['id']
                or rec.get('role', {}).get('id') != role['role']
                or rec.get('status') != 'ok' or rec.get('run_tree', {}).get('modified') is not False
                or rec.get('final_record', {}).get('valid') is not True):
            continue
        label = rec['_label']
        if point['mode'] in ACTOR_MODES and not independent(label):
            continue
        if point['mode'] in REVIEWER_MODES and not rec.get('_independence', {}).get('independent', False):
            continue
        if ranks[label] < {'self': 0, 'host': 1, 'transport': 2}[point['attestation_min']]:
            continue
        if point['mode'] in ACTOR_MODES:
            if not rec.get('session_id') or rec.get('_actor') is None:
                continue
            if point['mode'] in REVIEWER_MODES and (_session_keys(rec) & excluded or _is_producer(rec, None)):
                continue
        seen.add(identity)
        found.append(rec)
    return found


def _credit(members, receipts, producers):
    """Fill the role seats of the points of one scope with the largest consistent set of receipts.

    Constraints: a receipt fills one seat; the sessions credited at actor points of the scope
    are pairwise distinct. Model families are never compared: two sessions of one family fill two
    seats, and a role entry's retired ``distinct_family_from`` list changes nothing (the credited
    receipt carries its family label). The choice is a search over points and receipts in a canonical order (point id, then
    receipt node and attempt), so it depends on neither the order the points were derived in
    nor the order the receipts were read in: a fresh retry is used when the first receipt of a
    role cannot satisfy every role, and equal inputs always credit the same seats.
    """
    from itertools import combinations
    groups = []
    for point in sorted(members, key=lambda p: p['id']):
        for index, role in enumerate(point['roles']):
            found = _candidates(point, role, receipts, producers.get(point['id'], set()))
            groups.append({'point': point, 'index': index, 'role': role,
                           'candidates': sorted(found, key=lambda r: (str(r.get('node_id')), str(r.get('attempt'))))})
    capacity = [sum(min(g['role']['count'], len(g['candidates'])) for g in groups[i:]) for i in range(len(groups) + 1)]
    best = {'filled': -1, 'choice': None}
    budget = [20000]

    def admissible(group, picked, keys):
        used = set(keys)
        for rec in picked:
            if group['point']['mode'] in ACTOR_MODES:
                own = _session_keys(rec)
                if own & used:
                    return None
                used |= own
        return used

    def search(position, chosen, keys, filled):
        if filled + capacity[position] <= best['filled'] or budget[0] <= 0:
            return
        if position == len(groups):
            best.update(filled=filled, choice=list(chosen))
            return
        group = groups[position]
        limit = min(group['role']['count'], len(group['candidates']))
        for size in range(limit, -1, -1):
            for picked in combinations(group['candidates'], size):
                budget[0] -= 1
                used = admissible(group, picked, keys)
                if used is None:
                    continue
                chosen.append((group, picked))
                search(position + 1, chosen, used, filled + size)
                chosen.pop()
                if best['filled'] == capacity[0] or budget[0] <= 0:
                    return

    search(0, [], set(), 0)
    counts = {point['id']: [0] * len(point['roles']) for point in members}
    for group, picked in best['choice'] or []:
        counts[group['point']['id']][group['index']] = len(picked)
    return counts


def _missing(points, receipts, producers=()):
    """Role counts each point still lacks. ``producers`` is ``producer_sessions`` of the run.

    At a specialist, voting or producer point a receipt is credited only for an actor the
    dispatcher assigned: one worker session, fresh and distinct from every other credited
    session in the same scope. A session is its observed session id on its transport. The
    producer of an output earns no reviewer credit for that output. Any model family fills any
    seat; a credited receipt reports its family label (``_receipt_report``).
    """
    producers = producers if isinstance(producers, dict) else {}
    scopes = {}
    for point in points:
        scope = point.get('claim_id') or ('parent' if point['row'] == 11 else point['id'])
        scopes.setdefault(scope, []).append(point)
    counts = {}
    for members in scopes.values():
        counts.update(_credit(members, receipts, producers))
    return {point['id']: [{**role, 'count': role['count'] - filled}
                          for role, filled in zip(point['roles'], counts[point['id']]) if filled < role['count']]
            for point in points}


def _receipt_report(receipt):
    decision = receipt.get('_independence') or {}
    report = {'path': receipt['_path'], 'attestation': receipt['_label'],
            'independent': receipt['_eligible'] and receipt['_advisory'] is None
                and decision.get('independent', False),
            'advisory': receipt['_advisory'] or ('self_attested' if not independent(receipt['_label']) else None)}
    if report['independent']:
        # A label, never a condition: "separate session, same model family" when that is what happened.
        report['family_relation'] = decision.get('family_relation', 'unknown')
        from .review_independence import family_label
        report['label'] = family_label(report['family_relation'])
    if receipt.get('_executable_checks'):
        report['executable_checks'] = deepcopy(receipt['_executable_checks'])
    return report


def pending(rundir: Path) -> list[dict]:
    facts = _facts(Path(rundir)); points = derive(facts)
    records = list(_receipt_records(rundir, facts))
    missing = _missing(points, [r for r in records if r['_eligible']], producer_sessions(records, points, facts))
    result = []
    for p in points:
        reports = [_receipt_report(r) for r in records if r.get('review_point_id') == p['id']]
        if missing[p['id']] or p['mode'] == 'rdj' and p['blocking']:
            result.append({**p, 'roles': missing[p['id']], 'receipts': reports,
                           'transport_advisories': [] if p['blocking'] else [
                               {'code': 'review_transport_advisory', 'role': r['role'], 'blocking': False} for r in p['roles']],
                           'ready': not any(missing.get(dep) for dep in p['depends_on'])})
    return result


def legacy_accept_refusal(rundir):
    """Why an epoch-two run refuses a legacy physics-review acceptance; None when it may stand.

    The legacy cycle names its three reviewers by the policy's declared actors, which nothing
    authenticates. On an epoch-two run an acceptance stands only on the attested worker
    receipts that credit the run's CHECK-IN 2 review points: dispatcher-assigned actors in
    fresh sessions and isolated workspaces. ``physics_review`` applies this when a reviewer
    submits ``accept`` and again wherever a recorded acceptance is consumed. A run without an
    epoch-two contract retains readable advice, never independent acceptance credit.
    """
    root = Path(rundir)
    if not (root / 'inputs/task_contract.json').is_file() or _facts(root).get('agent_layer_epoch') != 2:
        return 'declared-name legacy reviews are advisory; trusted independent dispatch evidence required'
    lacking = [p['id'] for p in pending(root) if p['blocking'] and p['gate'] == 'checkin2_accept' and p['roles']]
    return 'accept requires the attested receipts: ' + ', '.join(lacking) if lacking else None


def satisfied(rundir: Path, point_id: str) -> bool:
    facts = _facts(Path(rundir)); points = derive(facts)
    point = next((p for p in points if p['id'] == point_id), None)
    if point is None:
        raise ValueError('unknown review point: ' + point_id)
    if point['mode'] == 'rdj':
        # RDJ satisfaction depends on the exact action. Only gate_errors can
        # decide it; an empty worker-role list is never RDJ authorization.
        return False
    records = list(_receipt_records(rundir, facts))
    return not _missing(points, [r for r in records if r['_eligible']], producer_sessions(records, points, facts))[point_id]


def checkin3_section(rundir):
    facts = _facts(Path(rundir))
    return {'calibration_choices': [{'point_id': p['id'], 'node_id': p['node_id'], 'choices': p['calibration_choices']}
                                   for p in derive(facts) if p['row'] == 16],
            'review_receipts': [{'review_point_id': r['review_point_id'], **_receipt_report(r)}
                                for r in _receipt_records(rundir, facts) if r.get('review_point_id')]}


def _error(gate, code, ids, message, fix='Supply and validate the named evidence before retrying this gate.'):
    from .decision_gate import GateError
    return GateError(code, gate, 'review_points', message, fix, tuple(ids))


def accept_checkin2(rundir, action):
    """Record a successful exact CHECK-IN 2 transition in system custody.

    Callers use this only at actual acceptance. Gate inspection stays
    read-only. Downstream calibration rechecks replay these same receipts.
    """
    from . import decision_gate, rdj_custody, rdj_loop
    errors = decision_gate.check(rundir, 'checkin2_accept', action)
    if errors:
        raise ValueError('CHECK-IN 2 acceptance refused: ' + '; '.join(e.message for e in errors))
    facts = _facts(Path(rundir))
    accepted = []
    for point in derive(facts):
        if point['row'] != 16:
            continue
        result = rdj_loop.authorizing_receipt(rundir, 'checkin2_accept',
                                             {**action, 'floor': point['rdj_class']})
        if result is None:
            raise ValueError('calibration authorization changed during acceptance')
        accepted.append({'point_id': point['id'], 'subject_sha256': subject_digest(facts, point),
                         'receipt_id': result['receipt']['receipt_id'],
                         'receipt_sha256': result['receipt_sha256']})
    return rdj_custody.append(rundir, 'review_acceptances', {
        'gate': 'checkin2_accept', 'action': deepcopy(action),
        'request_plan': facts.get('contract', {}).get('request_plan'), 'calibrations': accepted})


def _accepted_calibration(root, point):
    from . import rdj_custody, rdj_loop
    facts = _facts(Path(root))
    for row in reversed(rdj_custody.rows(root, 'review_acceptances')):
        record = row['record']
        if record.get('gate') != 'checkin2_accept' or record.get('request_plan') != facts['contract']['request_plan']:
            continue
        for calibration in record.get('calibrations', []):
            if (calibration.get('point_id') != point['id'] or
                    calibration.get('subject_sha256') != subject_digest(facts, point)):
                continue
            action = {**record['action'], 'floor': point['rdj_class']}
            result = rdj_loop.authorizing_receipt(root, 'checkin2_accept', action)
            if (result is not None and result['receipt']['receipt_id'] == calibration['receipt_id']
                    and result['receipt_sha256'] == calibration['receipt_sha256']):
                return result
    return None


def _rdj_errors(root, point, gate, action):
    """Consume the RDJ public provider; never authorize a loose JSON receipt."""
    from .decision_gate import providers
    rid = f'rdj:{point.get("decision_class", point["gate"])}:{point.get("node_id", point["id"])}:{action.get("digest", "action")}'
    if not any(p['id'] == 'rdj' and p['active'] for p in providers(gate)):
        return [_error(gate, 'rdj_receipt_missing', [rid], 'required ' + point.get('rdj_class', 'R1') + ' receipt is unavailable')]
    from . import rdj_loop
    requested = {**action, 'floor': point.get('rdj_class', 'R1')}
    if point.get('row') == 16 and gate in {'delivery', 'final_task', 'export'}:
        accepted = _accepted_calibration(root, point)
    else:
        accepted = rdj_loop.authorizing_receipt(root, point.get('receipt_gate', gate), requested)
    if accepted is not None:
        receipt, case = accepted['receipt'], accepted['case']
        tuning_ok = (not point.get('decision_class') or
                     case.get('decision_point', {}).get('tuning', {}).get('class') == point['decision_class'])
        human_ok = (not point.get('human_approval')
                    or (accepted.get('review_independence') or {}).get('human_approver') is True)
        if tuning_ok and human_ok:
            return []
    return [_error(gate, 'rdj_receipt_missing', [rid], 'Required scoped RDJ authorization has not passed replay, class or human approval.')]


# A controller run credits a review point only from the seats the controller dispatches and credits itself (its
# ``step-credit`` records), never from a worker receipt: the review of the current plan by each of the point's roles at
# the controller step that reviews what the point's gate decides. A CHECK-IN 1 point is reviewed at the plan review;
# a CHECK-IN 2 point uses its waypoint seat at that gate and still uses final review at later gates. Other points
# use final review, where the controller seats the CI3 triad and every other role a
# final task or delivery owes (``controller_seats``). A point of any other mode has no controller seat.
CONTROLLER_SEAT_MODES = ('specialist', 'voting', 'advisory')
CONTROLLER_FINAL_GATES = ('final_task', 'delivery')


def _weighs(point, gate, action):
    """Whether the decision ``gate`` on ``action`` weighs ``point``."""
    relevant = point['gate'] == gate
    if gate in {'delivery', 'final_task', 'export'} and point['gate'] == 'checkin2_accept':
        relevant = True
    if point['row'] == 17 and gate == 'launch' and (action.get('node_id') in {None, point['node_id']}):
        relevant = True
    if gate in {'launch', 'failed_stage_feedback'} and action.get('node_id') and point.get('node_id') and action['node_id'] != point['node_id']:
        relevant = False
    if gate == 'checkin2_accept' and action.get('claim_id') and point.get('claim_id') not in {None, action['claim_id']}:
        relevant = False
    if gate == 'research_choice' and point.get('protocol_stage') and point['protocol_stage'] != action.get('scope'):
        relevant = False
    return relevant


CERTIFICATE_CHECK = 'check:validation.certificates.validate_certificate'


def certificate_classification(rundir):
    """The policy's own certificate relevance for this run: ``{epoch, derived_points_sha256, checks}`` naming the
    certificate check, which applies when a derived point ``requires_certificate`` (a certificate-relevant claim)
    and does not apply, with that reason and evidence, when none does. ``check_classification`` never decides it."""
    facts = _facts(Path(rundir))
    points = derive(facts)
    relevant = [p for p in points if p.get('requires_certificate')]
    row = {'applies': bool(relevant), 'rows': sorted({p['row'] for p in relevant}),
           'points': sorted(p['id'] for p in relevant)}
    if not relevant:
        row.update(reason='no_certificate_relevant_claim', evidence={
            'policy': 'certificates_are_owed_for_certificate_relevant_claims',
            'derived_points_sha256': jdigest(points)})
    return {'epoch': facts.get('agent_layer_epoch'), 'derived_points_sha256': jdigest(points),
            'checks': {CERTIFICATE_CHECK: row}}


def check_classification(rundir, check_ids, *, step=None):
    """The review policy's classification of reviewer checks for this run.

    A check's applicability is the policy's own: the specialist rows whose specialist reviewer cards owe the check
    (``must_check``) decide it. It applies when the policy derives a point of one of those rows for this run, and does
    not apply when it derives none (for example, no claim rests on a generated prediction, so no normalization audit is
    owed). A check no specialist reviewer owes is not classified: the policy never says it does not apply. Returns
    ``{epoch, derived_points_sha256, checks: {check id: {applies, rows, points}}}``."""
    from . import role_registry
    facts = _facts(Path(rundir))
    points = derive(facts)
    owed = {}
    for row in _catalogue()['rows']:
        if row['mode'] != 'specialist':
            continue
        for role in row['roles']:
            card = role_registry.load(role)
            if card['independence']['kind'] != 'specialist':
                continue  # a producer seated by a specialist row owes its checks as a producer, not as this review
            for check in role_registry.resolve_self_checks(card['must_check']):
                owed.setdefault(check, set()).add(row['row'])
    checks = {}
    for check in check_ids:
        rows = sorted(owed.get(check, ()))
        if rows:
            derived = sorted(p['id'] for p in points if p['row'] in rows)
            checks[check] = {'applies': bool(derived), 'rows': rows, 'points': derived}
    normalization_check = 'check:physics.normalization_ledger.check'
    if normalization_check in checks:
        from .normalization_policy import normalization_disposition
        plan = facts.get('plan', facts)
        binned = [normalization_disposition(plan, claim) for claim in plan.get('claims', [])
                  if (claim.get('deliverable') or {}).get('artifact') == 'binned_values']
        if binned:
            checks[normalization_check]['evidence'] = {'claim_dispositions': binned}
            if not checks[normalization_check]['applies']:
                checks[normalization_check]['reason'] = 'no_normalized_binned_claim'
    if step is not None:
        from .operation_check_policy import dispositions
        for check, row in dispositions(step, check_ids).items():
            # An operation's physical outputs can add obligations even when no claim
            # has been assembled yet. A run-level obligation can never be removed.
            existing = checks.get(check, {'applies': False, 'rows': [], 'points': []})
            if existing['applies']:
                continue
            checks[check] = {**existing, **row}
    return {'epoch': facts.get('agent_layer_epoch'), 'derived_points_sha256': jdigest(points), 'checks': checks}


def _controller_step(point, gate=None, role=None):
    """Keep default final staffing; resolve a role's waypoint seat only at its CHECK-IN 2 gate."""
    from ravel.controller.graph import REVIEW_SEATS, canonical_role
    if gate == point['gate'] == 'checkin2_accept' and role is not None:
        return REVIEW_SEATS['waypoint'][0] + '.' + canonical_role(role)
    return REVIEW_SEATS['plan' if point['gate'] == 'approve_plan' else 'final'][0]


def controller_seats(rundir):
    """The roles a controller run's final review seats for its review policy: every role of each blocking point a
    final task or delivery weighs that a review seat fills (``CONTROLLER_SEAT_MODES``), in the policy's order, once
    each. A run without an epoch-two contract owes none."""
    root = Path(rundir)
    if not (root / 'inputs/task_contract.json').is_file():
        return []
    roles = []
    from . import spawn_rows
    facts = _facts(root)
    for point in population(facts):
        if (point['blocking'] and point['mode'] in CONTROLLER_SEAT_MODES and _controller_step(point) == 'final_review'
                and any(_weighs(point, gate, {}) for gate in CONTROLLER_FINAL_GATES)):
            roles += [row['role'] for row in point['roles']]
    return list(dict.fromkeys(roles))


def _waypoint_review(store, plan, action, role, n=1):
    """Credit only the pinned latest waypoint round on current accepted custody bytes."""
    from ravel.controller import graph
    from ravel.controller.step import custody
    from . import rdj_approval, review_dispatch
    try:
        pins = action.get('view_pins')
        if (type(pins) is not dict or action.get('digest') != jdigest(pins)
                or pins.get('plan_sha256') != plan['sha256']):
            raise ValueError('the waypoint action does not bind the current plan and exact view pins')
        waypoints = plan.get('waypoints') or []
        if not waypoints or len(waypoints) != len(set(waypoints)):
            raise ValueError('the current plan has no distinct waypoint population')
        outcomes, accepted = custody.outcomes(store), custody.custody_index(store)
        for step in waypoints:
            outcome = outcomes.get(step) or {}
            outputs = outcome.get('outputs') or []
            if outcome.get('status') != 'completed' or not outputs:
                raise ValueError('a current waypoint has no completed output subject')
            seen = set()
            for output in outputs:
                artifact = output.get('artifact')
                current = accepted.get(artifact) or {}
                if (not artifact or artifact in seen or current.get('status') != 'accepted'
                        or current.get('step_id') != step
                        or any(output.get(key) != current.get(key)
                               for key in ('path', 'sha256', 'artifact_id', 'attempt'))
                        or output.get('record_id') != current.get('_record_id')
                        or not output.get('record_id')
                        or custody._verify(accepted, artifact, store.run_dir, set(), 0, store)):
                    raise ValueError('a waypoint output differs from its current accepted custody record')
                seen.add(artifact)
        subject = graph.waypoint_pins(waypoints, outcomes)
        if {key: value for key, value in pins.items() if key.startswith('waypoint:')} != subject:
            raise ValueError('the action waypoint pins differ from current accepted outputs')
        rounds = [row for row in store.scan('review') if row['record'].get('purpose') == 'waypoint'
                  and row['record'].get('plan_sha256') == plan['sha256']]
        if not rounds or rounds[-1]['id'] != pins.get('checkin2_review'):
            raise ValueError('the action does not name the latest waypoint review round')
        row = rounds[-1]['record']
        attempt = row.get('attempt')
        if (type(attempt) is not int or attempt < 1 or row.get('subject') != subject
                or row.get('subject_sha256') != jdigest(subject)):
            raise ValueError('the waypoint review round covers another output subject')
        role = graph.canonical_role(role)
        step_id = graph.review_step_id('waypoint', role, n)
        verdict = (row.get('seats') or {}).get(graph.review_seat_key(role, n)) or {}
        if (verdict.get('status') != 'completed' or verdict.get('credited') is not True
                or verdict.get('verdict') != 'accept' or verdict.get('step') != step_id):
            raise ValueError('the current waypoint round has no completed accepting credit for this role')
        found, reason = rdj_approval.seat_review(store, step_id, role, plan['sha256'], blind=False,
                                                label='waypoint review')
        if reason is not None:
            return None, reason
        credit = store.read('step-credit', found['credit'])['record']
        observed = store.read('review-session', found['session_record'])['record']
        if (credit.get('step_id') != step_id or credit.get('attempt') != attempt
                or graph.canonical_role((credit.get('own') or {}).get('query', {}).get('role')) != role
                or observed.get('session_id') != found.get('session')
                or observed.get('step_id') != step_id or graph.canonical_role(observed.get('role')) != role):
            raise ValueError('the credited observed seat does not belong to the current waypoint round')
        workers = [entry['record'] for entry in store.scan('worker-session')
                   if review_dispatch._session({'session_id': entry['record'].get('session_id'),
                       'transport': {'id': observed.get('transport_id')}}) == found['session']]
        if len(workers) != 1:
            raise ValueError('the credited waypoint seat has no unique observed worker session')
        worker = workers[0]
        spec = worker.get('step_spec') or {}
        parameters = spec.get('parameters') or {}
        if (worker.get('run_id') != store.run_id or worker.get('step') != step_id
                or worker.get('attempt') != attempt or not worker.get('receipt_sha256')
                or spec.get('id') != step_id or graph.canonical_role(spec.get('role')) != role
                or parameters.get('purpose') != 'waypoint'
                or parameters.get('subject_sha256') != row['subject_sha256']
                or parameters.get('subject_plan_sha256') != plan['sha256']):
            raise ValueError('the observed waypoint seat did not review this round and exact current subject')
        return found, None
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as exc:
        return None, str(exc)[:400]


def _conditional_review(store, plan, point, role, n, gate, action, found):
    """Authenticate an exact planned point against its own current root review occurrence."""
    from ravel.controller import graph
    from . import review_dispatch
    purpose = 'waypoint' if gate == 'checkin2_accept' else ('plan' if gate == 'approve_plan' else 'final')
    try:
        bindings = graph.review_point_bindings(plan, purpose, role, n)
        expected = {'point': point, 'n': n, 'sha256': jdigest(point)}
        if expected not in bindings:
            raise ValueError('point_policy_required: the installed plan does not bind this exact review point')
        rounds = [row for row in store.scan('review') if row['record'].get('purpose') == purpose]
        if not rounds:
            raise ValueError('review_round_required: no current root review round')
        row = rounds[-1]['record']
        attempt = row.get('attempt')
        step_id = graph.review_step_id(purpose, role, n)
        verdict = (row.get('seats') or {}).get(graph.review_seat_key(role, n)) or {}
        if (row.get('plan_sha256') != plan['sha256'] or type(attempt) is not int or attempt < 1
                or verdict.get('step') != step_id or verdict.get('status') != 'completed'
                or verdict.get('credited') is not True or verdict.get('verdict') != 'accept'):
            raise ValueError('review_round_stale: no current accepting occurrence for this role')
        if purpose == 'final':
            pins = action.get('view_pins') or {}
            if (action.get('digest') != jdigest(pins) or pins.get('plan_sha256') != plan['sha256']
                    or not pins.get('steps_sha256') or row.get('subject') != {'steps_sha256': pins['steps_sha256']}
                    or row.get('subject_sha256') != pins['steps_sha256']):
                raise ValueError('review_subject_stale: final action does not bind the reviewed result')
        credit = store.read('step-credit', found['credit'])['record']
        observed = store.read('review-session', found['session_record'])['record']
        if (credit.get('attempt') != attempt or credit.get('step_id') != step_id
                or observed.get('step_id') != step_id or graph.canonical_role(observed.get('role')) != role):
            raise ValueError('review_round_stale: credited session belongs to another round or role')
        workers = [entry['record'] for entry in store.scan('worker-session')
                   if review_dispatch._session({'session_id': entry['record'].get('session_id'),
                       'transport': {'id': observed.get('transport_id')}}) == found['session']]
        if len(workers) != 1:
            raise ValueError('review_session_required: no unique observed worker session')
        worker = workers[0]
        spec = worker.get('step_spec') or {}
        parameters = spec.get('parameters') or {}
        if (worker.get('run_id') != store.run_id or worker.get('step') != step_id
                or worker.get('attempt') != attempt or not worker.get('receipt_sha256')
                or spec.get('id') != step_id or graph.canonical_role(spec.get('role')) != role
                or parameters.get('purpose') != purpose
                or parameters.get('subject_plan_sha256') != plan['sha256']
                or parameters.get('review_points') != bindings
                or (purpose != 'plan' and parameters.get('subject_sha256') != row.get('subject_sha256'))):
            raise ValueError('point_policy_required: observed worker did not review this exact policy, occurrence and subject')
        return None
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return str(exc)[:400]


def _controller_missing(rundir, points, gate=None, action=None):
    """``(missing, evidence)`` of a controller run: per point, the roles no credited controller seat fills (each with
    its ``reason``) and the seat evidence of those one does (``rdj_approval.seat_review``: the latest credit of that
    role's review of the current plan at the point's seat step, credited, approving, and from an observed session that
    read the authenticated projection its card declares). CHECK-IN 2 additionally binds the current accepted
    waypoint outputs and the action's latest review round."""
    from . import rdj_approval
    try:
        store, plan = rdj_approval.controller_plan(rundir)
    except Exception as exc:  # an unreadable controller store credits nothing
        reason = f'the controller store binds no verifiable plan: {type(exc).__name__}: {exc}'[:300]
        return {p['id']: [{**r, 'reason': reason} for r in p['roles']] for p in points}, {}
    from ravel.controller import graph
    missing, evidence = {}, {}
    for point in points:
        missing[point['id']], evidence[point['id']] = [], []
        used_sessions, used_credits = set(), set()
        for role in point['roles']:
            canonical = graph.canonical_role(role['role'])
            absent, reasons = 0, []
            for n in range(1, role['count'] + 1):
                purpose = 'waypoint' if gate == point['gate'] == 'checkin2_accept' else \
                    ('plan' if point['gate'] == 'approve_plan' else 'final')
                step_id = graph.review_step_id(purpose, canonical, n)
                found, reason = None, None
                conditional = isinstance(point['row'], str) or role['count'] > 1
                if point['mode'] not in CONTROLLER_SEAT_MODES:
                    reason = f"no controller seat fills a {point['mode']} point"
                elif conditional and (point.get('comparison_required') or point.get('tolerance_required')):
                    # The root findings contract has no authenticated numerical-result join.
                    # Ordinary receipt consumers retain their separate comparison path.
                    reason = 'comparison_evidence_required: root findings do not supply the required numerical comparison'
                elif purpose == 'waypoint':
                    found, reason = _waypoint_review(store, plan, action or {}, canonical, n)
                else:
                    found, reason = rdj_approval.seat_review(store, step_id, canonical, plan['sha256'], blind=False,
                                                             label=step_id.replace('_', ' '))
                if reason is None and conditional:
                    reason = _conditional_review(store, plan, point, canonical, n, gate, action or {}, found)
                if reason is None and (found['session'] in used_sessions or found['credit'] in used_credits):
                    reason = 'review_session_reused: one observed review cannot fill two required seats'
                if reason is not None:
                    absent += 1
                    reasons.append(reason)
                else:
                    used_sessions.add(found['session'])
                    used_credits.add(found['credit'])
                    evidence[point['id']].append({**found, 'step_id': step_id, **({'n': n} if conditional else {})})
            if absent:
                missing[point['id']].append({**role, 'count': absent, 'reason': '; '.join(dict.fromkeys(reasons)),
                    **({'code': 'comparison_evidence_required'} if any(r.startswith('comparison_evidence_required')
                                                                     for r in reasons) else {})})
    return missing, evidence


def controller_delivery(rundir):
    """What a controller run delivers, from its own records: ``{plan_sha256, outputs, descoped}``.

    Each mapped deliverable of the current plan delivers its accepted output (the latest custody record of
    ``<step>:<output>``, status ``accepted``) with the requirement ids its reading deliverable binds
    (``obligation_ids``: the request's obligations, each carrying its evidence spans). A deliverable the plan keeps
    open with a stated reason descopes each requirement it binds that no delivered output answers: the approved plan
    is that descope's record. A mapped deliverable without an accepted output delivers nothing and descopes nothing.
    """
    from . import rdj_approval
    store, plan = rdj_approval.controller_plan(rundir)
    reading = json.loads(store.get_blob(plan['reading_sha256']))
    bound = {row['id']: [i for i in row.get('obligation_ids') or () if type(i) is str]
             for row in reading.get('deliverables') or () if type(row) is dict and type(row.get('id')) is str}
    custody = {}
    for row in store.scan('custody'):
        custody[row['record'].get('artifact')] = row['record']
    outputs, kept_open = [], []
    for deliverable in plan.get('deliverables') or ():
        ids = bound.get(deliverable.get('id'), [])
        if deliverable.get('status') != 'mapped':
            kept_open.append((deliverable, ids))
            continue
        found = custody.get(f"{deliverable.get('step')}:{deliverable.get('output')}") or {}
        if found.get('status') == 'accepted' and type(found.get('destination')) is str and type(found.get('sha256')) is str:
            outputs.append({'artifact': {'path': found['destination'], 'sha256': found['sha256']},
                            'requirement_ids': ids, 'deliverable': deliverable['id']})
    answered = {i for row in outputs for i in row['requirement_ids']}
    descoped = [{'requirement_id': i, 'deliverable': d['id'], 'reason': d['reason'], 'plan_sha256': plan['sha256']}
                for d, ids in kept_open if type(d.get('reason')) is str and d['reason'].strip()
                for i in ids if i not in answered]
    return {'plan_sha256': plan['sha256'], 'outputs': outputs, 'descoped': descoped}


def delivery_action(rundir):
    """``{outputs, descoped}`` a controller decision on the final task or a delivery carries (``controller_delivery``);
    both empty when the delivery cannot be derived, so request fidelity refuses it."""
    try:
        found = controller_delivery(rundir)
    except Exception:
        return {'outputs': [], 'descoped': []}
    return {'outputs': found['outputs'], 'descoped': found['descoped']}


def _key(value):
    return json.dumps(value, sort_keys=True)


def _fidelity(facts, action, gate, rundir=None):
    """Request fidelity: every original requirement, its evidence spans intact, maps to an accepted output the action
    carries (its bytes verified) or, in a controller run, to a descope the action carries. A controller run's outputs
    and descopes count only as its own records derive them (``controller_delivery``)."""
    contract = facts.get('contract', {})
    obligations = contract.get('task_requirements', {}).get('obligations', [])
    outputs = action.get('outputs', [])
    mapped, derived = set(), None
    from . import rdj_approval
    if rundir is not None and rdj_approval.applies(rundir):
        try:
            derived = controller_delivery(rundir)
        except Exception:  # an underivable delivery maps nothing
            derived = {'outputs': [], 'descoped': []}
        own = {_key({'artifact': row['artifact'], 'requirement_ids': row['requirement_ids']}) for row in derived['outputs']}
        outputs = [o for o in outputs if type(o) is dict
                   and _key({'artifact': o.get('artifact'), 'requirement_ids': o.get('requirement_ids')}) in own]
        recorded = {_key(row) for row in derived['descoped']}
        mapped.update(row['requirement_id'] for row in action.get('descoped') or () if type(row) is dict
                      and _key(row) in recorded)
    for output in outputs:
        pin = output.get('artifact', output)
        if not pin.get('path') or not pin.get('sha256'):
            continue
        target = Path(pin['path'])
        if not target.is_absolute():
            if rundir is None: continue
            target = Path(rundir) / target
        try:
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != pin['sha256']:
                continue
        except OSError:
            continue
        mapped.update(output.get('requirement_ids', []))
    errors = []
    for requirement in obligations:
        identity = requirement['id']
        spans = requirement.get('evidence', [])
        prompt = contract.get('prompt', '')
        valid = bool(spans) and all(isinstance(s.get('start'), int) and isinstance(s.get('end'), int)
                    and 0 <= s['start'] < s['end'] <= len(prompt) and prompt[s['start']:s['end']] == s.get('text') for s in spans)
        if identity not in mapped or not valid:
            errors.append(_error(gate, 'request_fidelity', ['requirement:' + identity],
                                 'No accepted output maps to the original requirement span: ' + identity
                                 + ('' if derived is None else ' (nor a descope the approved plan records)')))
    return errors


def gate_errors(rundir: Path, gate: str, action: dict) -> list:
    facts = _facts(rundir)
    if facts.get('agent_layer_epoch') != 2:
        return []
    try:
        points = derive(facts)
    except ValueError as exc:
        return [_error(gate, 'parallel_unsafe', ['plan:parallel_safety'], str(exc))]
    from . import rdj_approval
    if rdj_approval.applies(rundir):
        # A controller run: only the controller's own credited seats fill a point (D-R5b of the integration record).
        receipts = []
        missing, _ = _controller_missing(rundir, [p for p in points if p['blocking'] and _weighs(p, gate, action)],
                                          gate=gate, action=action)
    else:
        records = list(_receipt_records(rundir, facts)); receipts = [r for r in records if r['_eligible']]
        missing = _missing(points, receipts, producer_sessions(records, points, facts))
    errors = []
    approval = Path(rundir) / 'inputs/review_points_approval.json'
    if approval.exists() and read_json(approval).get('derived_points_sha256') != jdigest(points):
        errors.append(_error(gate, 'obligations_changed', ['approval:derived_points_sha256'],
                             'Derived review obligations differ from the approved policy.'))
    if gate in {'checkin2_accept', 'delivery', 'final_task', 'export'}:
        if action.get('node_id') and action['node_id'] not in {n['id'] for n in facts['plan'].get('nodes', [])}:
            errors.append(_error(gate, 'action_scope_invalid', ['node:' + action['node_id']], 'Action names no plan node.'))
        if gate == 'checkin2_accept' and action.get('claim_id') and action['claim_id'] not in {c['id'] for c in facts['plan'].get('claims', [])}:
            errors.append(_error(gate, 'action_scope_invalid', ['claim:' + action['claim_id']], 'Action names no plan claim.'))
    # Unblinding is itself an observed-statistic action; an undeclared plan node
    # must not drop the R3 human-approval requirement.
    if gate == 'unblind' and not any(p['row'] == 17 and action.get('node_id') in {None, p['node_id']} for p in points):
        errors += _rdj_errors(rundir, {'id': 'RP17:action', 'row': 17, 'gate': 'unblind',
                                       'node_id': action.get('node_id') or 'action', 'rdj_class': 'R3',
                                       'human_approval': True, 'receipt_gate': 'unblind'}, gate, action)
    trusted_checks = []
    for point in points:
        if not _weighs(point, gate, action) or not point['blocking']:
            continue
        for role in missing[point['id']]:
            ids = [f'{point["id"]}:{role["role"]}:{i+1}' for i in range(role['count'])]
            message = ('Required review seats are not credited: ' + ', '.join(ids) + f" ({role['reason']})"
                       if role.get('reason') else 'Required review receipts are missing: ' + ', '.join(ids))
            errors.append(_error(gate, 'review_point_pending', ids, message))
        if point['mode'] == 'rdj':
            errors += _rdj_errors(rundir, point, gate, action)
        if point['row'] == 16:
            for index, choice in enumerate(point['calibration_choices']):
                if not choice.get('non_overlap') and not choice.get('added_uncertainty'):
                    errors.append(_error(gate, 'calibration_separation_missing', [f'{point["id"]}:calibration:{index}:separation'],
                        'Tuning to observed data requires declared non-overlap or an added uncertainty.'))
        for rec in receipts:
            if rec.get('review_point_id') != point['id']:
                continue
            if rec.get('findings') and not trusted_checks:
                # A sandboxed reviewer cannot register a check result; RAVEL runs the registered
                # ledger validator itself, once per ledger state, before it weighs any finding.
                from ravel.physics import normalization_ledger
                normalization_ledger.ensure_recorded(rundir)
                trusted_checks.append(True)
            for finding in rec.get('findings', []):
                if blocking_finding(rundir, finding):
                    evidence = finding_record(finding)['evidence_locators']
                    errors.append(_error(gate, 'blocking_finding', evidence, 'Unresolved evidence-bearing finding.'))
    if gate == 'approve_plan':
        errors += dispatchability(rundir, points)
    if gate in {'delivery', 'final_task', 'report_integrity', 'export'}:
        errors += _fidelity(facts, action, gate, rundir)
    return errors


def gate_evidence(rundir, gate, action):
    """What discharged this provider's requirement of a passed controller decision, for the ledger's decision record:
    the controller seat credits that filled each blocking point the decision weighs, and the outputs and descopes that
    answer each original requirement. None for any other run."""
    from . import rdj_approval
    if not rdj_approval.applies(rundir) or not (Path(rundir) / 'inputs/task_contract.json').is_file():
        return None  # no epoch-two review policy: nothing to name
    facts = _facts(Path(rundir))
    if facts.get('agent_layer_epoch') != 2:
        return None
    points = [p for p in derive(facts) if p['blocking'] and _weighs(p, gate, action)]
    _, seats = _controller_missing(rundir, points, gate=gate, action=action)
    value = {'mechanism': 'review_points.controller_seats', 'points': {k: v for k, v in seats.items() if v}}
    if gate in {'delivery', 'final_task', 'report_integrity', 'export'}:
        delivery = controller_delivery(rundir)
        value['delivery'] = {'plan_sha256': delivery['plan_sha256'], 'outputs': delivery['outputs'],
                             'descoped': delivery['descoped']}
    return value



def _controller_preferences(store):
    """The agent preferences the run's frozen operating mode holds (a controller run never reads a run-tree copy)."""
    from ravel.controller.authority import mode
    return deepcopy(mode.frozen(store).get('agent_preferences'))


def _seat_preferences(frozen, card):
    """Selection preferences for one seat of a controller run: the frozen order restricted to admitted transports."""
    from ravel.controller.step import seats
    from ravel.controller.step.services import StepHold
    try:
        return seats.preferences({'agent_preferences': frozen}, card)[0]
    except StepHold as exc:
        raise ValueError(f'{exc.reason}: {exc}') from None


def dispatchability(rundir, points=None, *, advisories=None):
    """Read stored probes and role cards; never probe a transport at a gate.

    A controller run's seats are judged as the governed step fills them: the frozen agent preferences of the
    run's operating mode, admitted transports only, and the operator-run qualifications in the run's store.
    """
    from . import transport_registry
    root = Path(rundir)
    points = derive(_facts(root)) if points is None else points
    from .review_independence import controller_store
    try:
        store = controller_store(root)
        selection_context = {} if store is None else {
            'controller': True, 'qualifications': transport_registry.store_qualifications(store)}
        frozen = None if store is None else _controller_preferences(store)
    except Exception:
        return [_error('approve_plan', 'review_transport_missing', ['controller:store'],
                       'Controller review qualification evidence is unavailable.')]
    preferences_path = root / 'inputs/agent_preferences.json'
    preferences = read_json(preferences_path) if store is None and preferences_path.exists() else {}
    errors = []; seen = set()
    for point in points:
        if not point['blocking']:
            if advisories is not None:
                advisories.extend({'code': 'review_transport_advisory', 'role': r['role'], 'blocking': False} for r in point['roles'])
            continue
        for role in point['roles']:
            name = role['role']
            if name in seen: continue
            seen.add(name)
            try:
                from . import role_registry
                card = deepcopy(role_registry.load(name))
            except (ImportError, OSError, ValueError, KeyError) as exc:
                errors.append(_error('approve_plan', 'review_transport_missing', ['role:' + name],
                    'Required role registry card is unavailable: ' + name + ': ' + str(exc)))
                continue
            card.setdefault('requires', {})['attestation_min'] = point['attestation_min']
            try:
                # Any model family serves any seat: selection never compares families.
                chosen = preferences if store is None else _seat_preferences(frozen, card)
                transport_registry.select(card, chosen, **selection_context)
            except transport_registry.TransportRefusal as exc:
                errors.append(_error('approve_plan', 'review_transport_missing',
                    ['capability:' + name + ':' + str(item) for item in exc.missing], str(exc)))
            except ValueError as exc:
                errors.append(_error('approve_plan', 'review_transport_missing', ['capability:' + name + ':preferences'],
                                     str(exc)))
    return errors


def deliver(rundir, request):
    """Inspect a proposed review delivery; no fabricated worker receipt is written.

    Human-manual is a disclosure label. It does not grant a delegated worker
    receipt or authorize execution; the ordinary human approval gate still runs.
    """
    root = Path(rundir)
    if request.get('verdict') == 'accept':
        approver = request.get('human_approver')
        if isinstance(approver, dict) and approver.get('id') and approver.get('approval_id'):
            return {'attestation': 'human_manual', 'approval_id': approver['approval_id'],
                    'execution_authorized': False, 'pending': pending(root)}
        points = [p for p in pending(root) if p['blocking'] and p['gate'] == request.get('gate', 'checkin2_accept')]
        if points:
            raise ValueError('accept requires the attested receipts: ' + ', '.join(p['id'] for p in points))
    return {'attestation': 'self_attested', 'execution_authorized': False, 'pending': pending(root)}


def main(argv=None):
    import argparse
    import sys
    from . import physics_review
    arguments = list(sys.argv[1:] if argv is None else argv)
    commands = {'pending', 'deliver', 'dispatch', 'accept'}
    selected = next((arg for arg in arguments if arg in commands), None)
    # Preserve the legacy review CLI, but close its direct accept bypass for
    # epoch-two delegated runs before it can append a legacy self-attested vote.
    if selected is None:
        legacy = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
        legacy.add_argument('--rundir'); legacy.add_argument('--request')
        known, _ = legacy.parse_known_args(arguments)
        if 'review' in arguments and known.rundir and known.request:
            root = Path(known.rundir)
            if _facts(root).get('agent_layer_epoch') == 2:
                request = read_json(known.request)
                disclosed = deliver(root, request)
                if disclosed['attestation'] == 'human_manual':
                    print(json.dumps(disclosed, indent=2)); return 0
        return physics_review.main(arguments)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=sorted(commands))
    parser.add_argument('--rundir', type=Path, required=True)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--request', type=Path)
    args = parser.parse_args(arguments)
    try:
        if args.action == 'pending':
            value = pending(args.rundir)
        elif args.action == 'accept':
            if args.request is None: raise ValueError('accept requires --request with the exact action')
            value = accept_checkin2(args.rundir, read_json(args.request))
        elif args.action == 'deliver':
            if args.request is None: raise ValueError('deliver requires --request')
            value = deliver(args.rundir, read_json(args.request))
        else:
            raise ValueError('review dispatch requires the review.points graph executor; pending lists its exact input obligations')
        print(json.dumps(value, indent=2, allow_nan=False)); return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print('review: ' + str(exc), file=sys.stderr); return 1
