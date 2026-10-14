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


def _catalogue():
    return json.loads(files('ravel').joinpath('data/review_points.json').read_text())


def _facts(rundir: Path) -> dict:
    """Single intake seam: read the contract and its byte-bound request plan."""
    root = Path(rundir)
    path = root / 'inputs/task_contract.json'
    from . import rdj_custody
    raw = path.read_bytes()
    contract = json.loads(raw)
    if not isinstance(contract, dict):
        raise ValueError('task contract must be an object')
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
    value.update(agent_layer_epoch=2, delegated=bool(contract.get('delegated') or contract.get('delegation')),
                 contract=contract, plan=plan)
    return value


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
        if elements & {'simulated_acceptance', 'generated_prediction'} or claim.get('absolute_yield') or (claim.get('deliverable') or {}).get('artifact') == 'binned_values':
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


def credit_refusal(receipt, facts, point):
    """Why a registered worker receipt earns no credit for ``point``; None when its subject matches.

    Readers dispatch on the receipt version. Version 1 predates ``review_subject``: it stays
    valid for its original use but earns no review credit. Version 2 must name this point's
    current subject scope and digest.
    """
    if receipt.get('kind') != 'agent-worker-receipt':
        return 'receipt_invalid'
    if receipt.get('schema_version') == 1:
        return 'receipt_predates_review_subject'
    if receipt.get('schema_version') != 2:
        return 'receipt_invalid'
    if point is None or receipt.get('review_subject') != review_subject(facts, point):
        return 'review_subject'
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
    facts = {**plan, 'plan': plan, 'agent_layer_epoch': 2,
             'delegated': bool(contract.get('delegated') or contract.get('delegation'))}
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
    """The label of a registered receipt. The worker dispatcher writes version-2 receipts with no
    execution mode and registers each with the label it computed from the transport's own
    verification; that registration is the authority, never the receipt's ``attestation`` field."""
    if receipt.get('schema_version') == 2 and 'execution_mode' not in receipt:
        from .rdj_custody import WORKER_LABELS
        return registered_verified_label if registered_verified_label in WORKER_LABELS else 'self_attested'
    return attestation_label(receipt, registered_verified_label)


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
    root = Path(root).resolve()
    points = {p['id']: p for p in derive(facts)}
    for path in sorted((root / 'agent-work').glob('*/*/receipt.json')):
        rel = path.relative_to(root).as_posix()
        value = read_json(path)
        value['_path'] = rel
        value['_eligible'] = False
        value['_label'] = 'self_attested'
        reason = 'receipt_unregistered'
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.resolve().is_relative_to(root) and rdj_custody.worker_registered(root, rel, digest):
            registration = rdj_custody.worker_row(root, rel, digest)
            value['_label'] = worker_label(value, registration.get('verified_label'))
            reason = 'receipt_invalid'
            final = value.get('final_record') or {}
            point = points.get(value.get('review_point_id'))
            if value.get('kind') == 'agent-worker-receipt' and value.get('schema_version') in (1, 2) and final.get('path'):
                target = (path.parent / final['path']).resolve()
                if (target.is_relative_to(path.parent.resolve()) and target.is_relative_to(root) and target.is_file()
                        and hashlib.sha256(target.read_bytes()).hexdigest() == final.get('sha256')):
                    value['findings'] = read_json(target).get('findings', [])
                    reason = credit_refusal(value, facts, point)
                    value['_eligible'] = reason is None
        value['_advisory'] = reason
        yield value


def _receipts(root, facts=None):
    facts = _facts(Path(root)) if facts is None else facts
    return (r for r in _receipt_records(root, facts) if r['_eligible'])


def _missing(points, receipts):
    ranks = ATTESTATION_RANK
    result = {}
    # Session/actor reuse in one voting panel is not independent review.
    sessions = {}; actors = {}; credited = set()
    for point in points:
        missing = []
        scope = point.get('claim_id') or ('parent' if point['row'] == 11 else point['id'])
        for role in point['roles']:
            count = 0
            for rec in receipts:
                identity = (rec.get('node_id'), rec.get('attempt'))
                role_id = rec.get('role', {}).get('id')
                if (identity in credited or rec.get('review_point_id') != point['id'] or role_id != role['role']
                        or rec.get('status') != 'ok' or rec.get('run_tree', {}).get('modified') is not False
                        or rec.get('final_record', {}).get('valid') is not True):
                    continue
                label = rec['_label']
                if point['mode'] in {'specialist', 'voting', 'producer'} and not independent(label):
                    continue
                if ranks[label] < {'self': 0, 'host': 1, 'transport': 2}[point['attestation_min']]:
                    continue
                session, actor = rec.get('session_id'), rec.get('actor_id')
                if point['mode'] in {'specialist', 'voting', 'producer'}:
                    if not session or not actor or session in sessions.get(scope, set()) or actor in actors.get(scope, set()):
                        continue
                    if rec.get('model', {}).get('family') in role.get('distinct_family_from', []):
                        continue
                    sessions.setdefault(scope, set()).add(session); actors.setdefault(scope, set()).add(actor)
                credited.add(identity); count += 1
                if count == role['count']:
                    break
            if count < role['count']:
                missing.append({**role, 'count': role['count'] - count})
        result[point['id']] = missing
    return result


def _receipt_report(receipt):
    return {'path': receipt['_path'], 'attestation': receipt['_label'],
            'independent': receipt['_eligible'] and independent(receipt['_label']),
            'advisory': receipt['_advisory'] or ('self_attested' if not independent(receipt['_label']) else None)}


def pending(rundir: Path) -> list[dict]:
    facts = _facts(Path(rundir)); points = derive(facts)
    records = list(_receipt_records(rundir, facts))
    missing = _missing(points, [r for r in records if r['_eligible']])
    result = []
    for p in points:
        reports = [_receipt_report(r) for r in records if r.get('review_point_id') == p['id']]
        if missing[p['id']] or p['mode'] == 'rdj' and p['blocking']:
            result.append({**p, 'roles': missing[p['id']], 'receipts': reports,
                           'transport_advisories': [] if p['blocking'] else [
                               {'code': 'review_transport_advisory', 'role': r['role'], 'blocking': False} for r in p['roles']],
                           'ready': not any(missing.get(dep) for dep in p['depends_on'])})
    return result


def satisfied(rundir: Path, point_id: str) -> bool:
    points = derive(_facts(Path(rundir)))
    point = next((p for p in points if p['id'] == point_id), None)
    if point is None:
        raise ValueError('unknown review point: ' + point_id)
    if point['mode'] == 'rdj':
        # RDJ satisfaction depends on the exact action. Only gate_errors can
        # decide it; an empty worker-role list is never RDJ authorization.
        return False
    return not _missing(points, list(_receipts(rundir)))[point_id]


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
        human_ok = not point.get('human_approval') or receipt.get('attestation_summary', {}).get('human_approver')
        if tuning_ok and human_ok:
            return []
    return [_error(gate, 'rdj_receipt_missing', [rid], 'Required scoped RDJ authorization has not passed replay, class or human approval.')]


def _fidelity(facts, action, gate, rundir=None):
    contract = facts.get('contract', {})
    obligations = contract.get('task_requirements', {}).get('obligations', [])
    outputs = action.get('outputs', [])
    mapped = set()
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
                                 'No accepted output maps to the original requirement span: ' + identity))
    return errors


def gate_errors(rundir: Path, gate: str, action: dict) -> list:
    facts = _facts(rundir)
    if facts.get('agent_layer_epoch') != 2:
        return []
    try:
        points = derive(facts)
    except ValueError as exc:
        return [_error(gate, 'parallel_unsafe', ['plan:parallel_safety'], str(exc))]
    receipts = list(_receipts(rundir)); missing = _missing(points, receipts)
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
    for point in points:
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
        if not relevant or not point['blocking']:
            continue
        for role in missing[point['id']]:
            ids = [f'{point["id"]}:{role["role"]}:{i+1}' for i in range(role['count'])]
            errors.append(_error(gate, 'review_point_pending', ids, 'Required review receipts are missing: ' + ', '.join(ids)))
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
            for finding in rec.get('findings', []):
                if blocking_finding(rundir, finding):
                    evidence = finding_record(finding)['evidence_locators']
                    errors.append(_error(gate, 'blocking_finding', evidence, 'Unresolved evidence-bearing finding.'))
    if gate == 'approve_plan':
        errors += dispatchability(rundir, points)
    if gate in {'delivery', 'final_task', 'report_integrity', 'export'}:
        errors += _fidelity(facts, action, gate, rundir)
    return errors



def dispatchability(rundir, points=None, *, advisories=None):
    """Read stored probes and role cards; never probe a transport at a gate."""
    from . import transport_registry
    root = Path(rundir)
    points = derive(_facts(root)) if points is None else points
    preferences_path = root / 'inputs/agent_preferences.json'
    preferences = read_json(preferences_path) if preferences_path.exists() else {}
    errors = []; assigned = {}; seen = set()
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
                assigned[name] = transport_registry.select(card, preferences, assigned=assigned)
            except transport_registry.TransportRefusal as exc:
                errors.append(_error('approve_plan', 'review_transport_missing',
                    ['capability:' + name + ':' + str(item) for item in exc.missing], str(exc)))
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
