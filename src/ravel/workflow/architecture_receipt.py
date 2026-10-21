"""Read-only architecture observations and a common scientific delivery decision.

This module reads existing supervisor and review custody; it grants no authority
and runs no tools. Saved receipts are reports, never credentials. Consumers must
recompute the decision against current bytes. Local custody cannot prove that an
unrestricted process under the same OS user obeyed the workflow.

For a run the controller owns, the receipt is the controller's: ``build_receipt``
returns the sole sink's receipt computed from the controller store, and the legacy
delivery labelling refuses (only the sink delivers). Every other run is NOT GOVERNED:
its receipt says so, and ``architecture_complete`` is derived from predicates that
include controller mode, so it is never true outside the controller.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from . import execution, host_governance, launch_authorization, rdj_anchor

ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError)
LABELS = ('diagnostic', 'governed', 'accepted')
NOT_GOVERNED = 'NOT GOVERNED'
LEGACY_PREDICATES = ('controller_mode', 'research_join_complete', 'required_roles_credited')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def _stage_observations(root):
    """Join current registered output bytes to their exact launch, not a filename."""
    rows, errors = [], []
    try:
        events = launch_authorization._events(root)
        authorized = {e['sequence']: e for e in events if e['event'] == 'authorized'}
        launched = {e['sequence']: e for e in events if e['event'] == 'launched'}
        stages = execution.load_execution(root)['stages']
    except ERRORS as exc:
        return [], [str(exc)]
    for name, candidate in sorted(stages.items()):
        row = {'stage': name, 'receipt_id': None, 'governed': False,
               'outputs': [], 'reason': None}
        try:
            receipt_id = f"stage:{name}:{candidate['attempt_id']}"
            record = rdj_anchor.stage_receipt(root, receipt_id)
            pin = record.get('authorization_receipt') or {}
            launch = launched.get(pin.get('sequence'))
            if launch is None or launch['sha256'] != pin.get('sha256'):
                raise ValueError('no matching governed launch receipt')
            auth = authorized.get(launch.get('authorization_sequence'))
            if auth is None or auth['sha256'] != launch.get('authorization_sha256'):
                raise ValueError('launch has no matching authorization')
            launch_authorization._historical_errors(auth)
            if (launch.get('pid') != record.get('child_pid')
                    or type(launch.get('pid')) is not int or launch['pid'] <= 0
                    or auth.get('command') != record.get('command')
                    or auth.get('context', {}).get('stage') != name):
                raise ValueError('launch differs from the registered stage')
            for base, entry in record.get('output_snapshot', {}).items():
                for member in entry.get('files', []):
                    path = Path(base) if member['name'] == '.' else Path(base) / member['name']
                    path = path if path.is_absolute() else root / path
                    _, relative = rdj_anchor.inside(root, str(path))
                    row['outputs'].append({'path': relative, 'sha256': member['sha256']})
            row.update(receipt_id=receipt_id, governed=True, parents=list(record.get('parents', {})),
                       launch={'sequence': launch['sequence'], 'sha256': launch['sha256']},
                       command=record['command'])
        except ERRORS as exc:
            row['reason'] = str(exc)
        rows.append(row)
    # A valid final stage cannot launder an ungoverned registered predecessor.
    by_name = {row['stage']: row for row in rows}
    changed = True
    while changed:
        changed = False
        for row in rows:
            if row['governed'] and any(not by_name.get(parent, {}).get('governed')
                                       for parent in row.get('parents', [])):
                row.update(governed=False, reason='predecessor lacks a governed launch receipt')
                changed = True
    return rows, errors


def _role_observations(root):
    """Use the existing credit decision; do not add a second independence rule."""
    from . import rdj_custody, review_points as rp
    try:
        facts = rp._facts(root)
        # An unbound plan cannot define away required seats.
        if not rdj_custody.snapshot_digest(root, 'inputs/task_contract.json', event='run_init'):
            raise ValueError('required-role contract has no initialization custody')
        if facts.get('agent_layer_epoch') != 2:
            raise ValueError('required-role coverage is unknown for this contract version')
        points = rp.derive(facts)
        records = list(rp._receipt_records(root, facts))
        missing = rp._missing(points, [r for r in records if r['_eligible'] and
                              (not any(p['id'] == r.get('review_point_id') and p['mode'] in rp.REVIEWER_MODES
                                       for p in points) or rp._receipt_report(r)['independent'])],
                              rp.producer_sessions(records, points, facts))
        roles = []
        for point in points:
            for role in point['roles']:
                absent = next((r['count'] for r in missing[point['id']]
                               if r['role'] == role['role']), 0)
                roles.append({'point': point['id'], 'role': role['role'],
                              'required': role['count'], 'credited': role['count'] - absent,
                              'missing': absent})
        dispatched = []
        for record in records:
            # Unregistered files are visible as advisory, never counted as dispatch.
            pin = record['_path']
            registered = rdj_custody.worker_registered(root, pin, rdj_anchor.sha256_file(root / pin))
            dispatched.append({'path': pin, 'registered_dispatch': registered,
                               'role': record.get('role'), 'point': record.get('review_point_id'),
                               'reported_usage': record.get('usage') if registered else None,
                               'packet': record.get('request_sha256') if registered else None,
                               **rp._receipt_report(record)})
        for role in roles:
            role['dispatched'] = sum(1 for r in dispatched if r['registered_dispatch']
                and r['point'] == role['point'] and (r['role'] or {}).get('id') == role['role'])
        blocked = [p['id'] for p in rp.pending(root) if p.get('blocking')]
        return {'status': 'observed', 'roles': roles, 'dispatches': dispatched,
                'missing': [r for r in roles if r['missing']], 'blocking_points': blocked,
                'errors': []}
    except ERRORS as exc:
        return {'status': 'unknown', 'roles': None, 'dispatches': None,
                'missing': None, 'blocking_points': None, 'errors': [str(exc)]}


def _review_observation(root):
    from . import physics_review
    try:
        status = physics_review.status(root)
        errors = list(status.get('live_errors', status.get('errors', [])))
        accepted = status.get('state') == 'accepted' and not errors
        pins = []
        if accepted:
            reg, events = physics_review._read(root)
            pins = physics_review._view(reg, events)['cycle']['snapshots']
        return {'state': status.get('state', 'unknown'), 'accepted': accepted,
                'claim_scope': status.get('claim_scope'), 'errors': errors, 'artifacts': pins}
    except ERRORS as exc:
        return {'state': 'unknown', 'accepted': False, 'claim_scope': None, 'errors': [str(exc)], 'artifacts': []}


def _autonomy_observation(root):
    from . import rdj_custody, scientific_autonomy
    try:
        path = root / 'inputs/task_contract.json'
        if rdj_anchor.sha256_file(path) != rdj_custody.snapshot_digest(
                root, 'inputs/task_contract.json', event='run_init'):
            raise ValueError('autonomy contract has no current initialization custody')
        doc = scientific_autonomy.effective_document(json.loads(path.read_text()), root)
        if 'autonomy' not in doc:
            return {'mode': 'human_checkins', 'authority': 'not_assessed'}
        # Effective-document verification alone does not authenticate the delegation.
        approval = scientific_autonomy.plan_authority(root)
        return {'mode': 'delegated', 'authority': 'validated_user_delegation',
                'scope': approval['value']['bounds']}
    except ERRORS as exc:
        return {'mode': 'unknown', 'authority': None, 'reason': str(exc)}


def scientific_admissibility(rundir, artifacts):
    """Check the complete caller-supplied numerical/figure population in one pass.

    Each item is {path, kind}; an optional sha256 pins previously captured bytes.
    A stage declaration without current supervisor custody AND launch approval
    never covers a file. No path suffix, diagnostic flag, or saved receipt is an
    exemption. An empty population is not evidence of a governed delivery.
    """
    root = Path(rundir).resolve()
    if not isinstance(artifacts, (list, tuple)):
        raise ValueError('explicit delivery artifact population required')
    stages, errors = _stage_observations(root)
    coverage = {}
    for stage in stages:
        if stage['governed']:
            for pin in stage['outputs']:
                coverage.setdefault((pin['path'], pin['sha256']), []).append(stage['receipt_id'])
    rows = []
    for item in artifacts:
        row = {'path': None, 'kind': None, 'sha256': None, 'governed': False, 'receipts': []}
        try:
            if type(item) is not dict or item.get('kind') not in ('number', 'figure'):
                raise ValueError('each delivered artifact needs a path and number/figure kind')
            row.update(path=item.get('path'), kind=item['kind'])
            path, relative = rdj_anchor.inside(root, item['path'])
            sha = rdj_anchor.sha256_file(path)
            row.update(path=relative, sha256=sha)
            if path.suffix == '.json':
                try:
                    document = json.loads(path.read_bytes())
                except (ValueError, UnicodeError):
                    document = None
                if isinstance(document, dict) and (document.get('delivery_label') == 'diagnostic'
                        or document.get('scientific_acceptance') is False):
                    raise ValueError('diagnostic output cannot be promoted to governed or accepted delivery')
            if 'sha256' in item and sha != item['sha256']:
                raise ValueError('delivered bytes differ from their pin')
            row['receipts'] = coverage.get((relative, sha), [])
            if not row['receipts']:
                raise ValueError('delivered bytes have no current governed launch receipt')
            row['governed'] = True
        except ERRORS as exc:
            row['reason'] = str(exc)
        rows.append(row)
    if not rows:
        errors.append('delivery artifact population is empty or unknown')
    return {'artifacts': rows, 'stages': stages, 'errors': errors,
            'governed': bool(rows) and not errors and all(r['governed'] for r in rows)}


def _controller_run(root):
    from ravel.controller.sink import legacy
    return legacy.owner(root)


def build_receipt(rundir, artifacts=()):
    """Fresh observations; absent facts stay null/unknown, never zero or success.

    A controller-owned run gets the sole sink's receipt (its population comes from the
    plan and the store, never from ``artifacts``). Any other run is NOT GOVERNED.
    """
    from . import production_executor
    root = Path(rundir).resolve()
    if _controller_run(root) is not None:
        from ravel.controller.sink import observe
        return observe(root)
    admissibility = scientific_admissibility(root, artifacts)
    from . import research_architecture
    research = research_architecture.observe(root, artifacts, admissibility)
    roles = _role_observations(root)
    review = _review_observation(root)
    host_errors = []
    try:
        enforcement = host_governance.enforcement_record(root)
    except ERRORS as exc:
        enforcement = None
        host_errors.append(str(exc))
    try:
        waived = production_executor.host_authored_nodes(root)
    except ERRORS as exc:
        waived = None
        host_errors.append('waiver evidence: ' + str(exc))
    complete = (roles['status'] == 'observed' and not roles['missing']
                and not roles['blocking_points'])
    # Diagnostic acceptance never promotes the scientific scope.
    reviewed = {(str((root / p['path']).resolve()), p['sha256']) for p in review['artifacts']}
    all_reviewed = all((str((root / r['path']).resolve()), r['sha256']) in reviewed
                       for r in admissibility['artifacts'] if r['path'])
    accepted = (admissibility['governed'] and all_reviewed and complete and review['accepted']
                and review['claim_scope'] not in (None, 'diagnostic'))
    # The ordinary scientific Graph calls have their own receipt shape. Observe
    # their exact accepted CI3 role/packet/cycle custody without manufacturing
    # agent-worker receipts or changing the original scientific acceptance rule.
    if roles['status'] == 'observed':
        from .ordinary_review_observations import final_roles
        ordinary = final_roles(root)
        roles = deepcopy(roles)
        roles['ordinary_final'] = ordinary
        if ordinary['status'] == 'observed':
            by_role = {row['role']: row for row in ordinary['roles']}
            for row in roles['roles']:
                if row['point'].startswith('RP11:') and row['required'] == 1 and row['role'] in by_role:
                    row.update(credited=1, missing=0, ordinary_source=by_role[row['role']])
            roles['missing'] = [row for row in roles['roles'] if row['missing']]
            covered = {row['point'] for row in roles['roles'] if row['point'].startswith('RP11:')
                       and not any(other['missing'] for other in roles['roles'] if other['point'] == row['point'])}
            roles['blocking_points'] = [point for point in roles['blocking_points'] if point not in covered]
    complete = (roles['status'] == 'observed' and not roles['missing'] and not roles['blocking_points'])
    notices = []
    if not complete or not review['accepted'] or not all_reviewed:
        notices.append('INDEPENDENT REVIEW INCOMPLETE')
    # A run the controller does not own is never governed by it, whatever its custody shows.
    governance = {'label': NOT_GOVERNED, 'controller_run': None,
                  'reasons': ['the controller does not own this run; legacy commands produced it']}
    reported = (enforcement or {}).get('governance') if isinstance(enforcement, dict) else None
    if isinstance(reported, dict):
        governance['reasons'] += [str(r) for r in reported.get('reasons') or [] if str(r) not in governance['reasons']]
        if reported.get('label') and reported['label'] != NOT_GOVERNED:
            governance['host_label'] = reported['label']
    notices.append(NOT_GOVERNED)
    notices.append(f"{NOT_GOVERNED}: " + '; '.join(governance['reasons']))
    if not admissibility['governed']:
        notices.append('NOT GOVERNED: delivered numbers or figures lack governed launch receipts')
    # Existing host names/hook configurations cannot attest whole-host mediation.
    notices.append('RESTRICTED HOST: whole-host enforcement is unverified; direct scientific execution is refused')
    predicates = {'controller_mode': False, 'research_join_complete': bool(research['complete']),
                  'required_roles_credited': bool(complete)}
    receipt = {'schema_version': 1, 'kind': 'ravel-architecture-receipt',
        'run': str(root), 'trust_basis': 'recomputed supervisor and review custody',
        'trust_limit': 'same-user unrestricted processes are outside the custody boundary',
        'host': {'reported_enforcement': enforcement,
                 'governing_project': str(host_governance.project_root(root)), 'whole_host_enforcement': 'unknown',
                 'mode': 'restricted', 'tool_inventory': None,
                 'observed_stage_commands': [r['command'] for r in admissibility['stages'] if r['governed']],
                 'errors': host_errors},
        'autonomy': _autonomy_observation(root), 'roles': roles, 'review': review,
        'review_strength': 'credited-required-roles' if complete else 'incomplete-or-unknown',
        'work': {'waived': waived, 'refused': None,
                 'refusal_history_completeness': 'unknown',
                 'current_refusals': [*admissibility['errors'], *roles['errors'], *review['errors'],
                     *[r['reason'] for r in admissibility['artifacts'] if r.get('reason')]]},
        'costs': {'total': None, 'currency': None, 'model_calls': None,
                  'registered_worker_reports': [{'path': r['path'], 'usage': r['reported_usage']}
                      for r in (roles['dispatches'] or []) if r['registered_dispatch']],
                  'coverage': 'partial reports only; whole-run totals unknown'},
        'admissibility': admissibility, 'accepted': accepted,
        'research': research, 'governance': governance, 'architecture_predicates': predicates,
        'architecture_complete': all(predicates[name] for name in LEGACY_PREDICATES), 'notices': notices}
    receipt['sha256'] = _digest(receipt)
    return receipt


def require_label(receipt, label):
    """Internal decision consumer. External callers must obtain a fresh receipt."""
    if label not in LABELS:
        raise ValueError('unknown delivery label')
    if label == 'governed' and not receipt['admissibility']['governed']:
        raise ValueError('NOT GOVERNED: delivered numbers or figures lack governed launch receipts')
    if label == 'accepted' and not receipt['accepted']:
        raise ValueError('INDEPENDENT REVIEW INCOMPLETE / NOT GOVERNED: accepted delivery refused')


def label_delivery(rundir, artifacts, *, label='diagnostic'):
    from ravel.controller.sink import legacy
    legacy.refuse_controller_owned(rundir, 'legacy delivery labelling')
    receipt = build_receipt(rundir, artifacts)
    require_label(receipt, label)
    return {'delivery_label': label, 'architecture_receipt': receipt,
            'notices': list(receipt['notices'])}


def checkin_section(context):
    if isinstance(context, dict):
        rundir = context.get('rundir') or context.get('base_dir')
        if rundir is None:
            return {'title': 'Architecture and enforcement',
                    'text': 'INDEPENDENT REVIEW INCOMPLETE / NOT GOVERNED: run context unknown'}
    else:
        rundir = context
    receipt = build_receipt(rundir)
    return {'title': 'Architecture and enforcement',
            'text': '\n'.join(receipt['notices']), 'architecture_receipt': receipt}


def require_host_action(rundir, action):
    """Restricted-host contract: never offer a direct-shell scientific fallback.

    Governed launch remains the responsibility of the existing authorized launcher;
    this read-only API cannot grant launch or review authority.
    """
    if action not in ('inspect', 'diagnostic_delivery'):
        raise ValueError('RESTRICTED HOST: action requires its governed service; '
                         'direct execution and independent-review substitution are refused')
    return checkin_section(rundir)


def pack_artifacts(result, figures=None):
    """Fixed result-pack census: all numerical sources and every declared figure.

    Saved documents may be malformed; a non-object entry stays in the population
    as an unresolvable artifact, so it can only fail admissibility.
    """
    def mapping(value):
        return value if isinstance(value, dict) else {}

    def entries(value):
        return [item if isinstance(item, dict) else {} for item in value] if isinstance(value, list) else []

    result, figures = mapping(result), mapping(figures)
    pointers = mapping(result.get('pointers'))
    rows = [{'path': pointers.get(key), 'kind': 'number'} for key in ('sr_yields', 'exclusion', 'cert')]
    for item in entries(figures.get('figures')):
        rows.append({'path': item.get('filename'), 'kind': 'figure'})
        if item.get('pdf'):
            rows.append({'path': item['pdf'], 'kind': 'figure'})
    for target in entries(mapping(figures.get('figure_target')).get('targets')):
        for key in ('generated_counterpart', 'side_by_side'):
            pin = target.get(key)
            if isinstance(pin, dict) and pin.get('path'):
                rows.append({'path': pin['path'], 'kind': 'figure'})
    for item in entries(result.get('deliverables')):
        rows.append({'path': item.get('path'), 'kind': 'figure' if item.get('kind') == 'figure' else 'number'})
    return rows


def claimed_label(document):
    """Recognize explicit scientific-governance claims, including older callers."""
    label = document.get('delivery_label', 'diagnostic')
    if document.get('accepted') is True or document.get('scientific_acceptance') is True:
        return 'accepted'
    if document.get('governed') is True and label == 'diagnostic':
        return 'governed'
    return label


def verify_saved_receipt(receipt):
    """Integrity only; a matching digest is never authority for label promotion."""
    if (not isinstance(receipt, dict) or receipt.get('kind') != 'ravel-architecture-receipt'
            or receipt.get('sha256') != _digest({k: v for k, v in receipt.items() if k != 'sha256'})):
        raise ValueError('architecture receipt changed or is absent')
