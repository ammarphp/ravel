"""Controller evidence for one run, read from its protected store.

Only records the controller's own nodes appended count: the run binding, the request and intake
pins, the plan, step outcomes, custody, launches with their confinement qualification, worker
observations and dispatches, validations, review credits, refusals, instruction deliveries,
budget reservations and settlements, authority and mode records, judgments, engagement
decisions and envelope checks, facility submissions, route ending records and the obligation
ledger, plus the host governance label of the run directory and the authority issuer's
description of itself. A file in the run directory is never read as evidence about any of them;
a worker's list, receipt or notice is never consulted. A package that is not installed, or a
record that cannot be read, is reported as unknown, never as a pass.
"""
from __future__ import annotations

from copy import deepcopy
import importlib
import json
import sys

from . import common
from .common import records

DIMENSIONS = ('wall_seconds', 'model_calls', 'tokens', 'cost_usd', 'core_hours', 'events', 'children')
SETTLED = ('settled', 'released', 'reconciled')
UNCONFINED_KINDS = ('unconfined',)
PLANNING_SOURCES = ('judgment-planning',)  # plans the judgment graph binds only to run its own seats


def _latest(rows, key):
    found = {}
    for row in rows:
        value = row.get(key)
        if type(value) is str:
            found[value] = row
    return found


def _binding(store):
    check = getattr(store, 'check_binding', None)
    if not callable(check):
        return None  # unknown: the store offers no binding check
    try:
        return list(check())
    except (OSError, ValueError, KeyError) as exc:
        return [f'the run binding cannot be checked: {exc}']


def _verify(store):
    verify = getattr(store, 'verify', None)
    if not callable(verify):
        return None
    try:
        return list(verify())
    except (OSError, ValueError, KeyError) as exc:
        return [f'the store chain cannot be verified: {exc}']


def _blob_json(store, digest):
    return json.loads(store.get_blob(digest).decode('utf-8'))


def _intake(store, errors):
    rows = records(store, 'intake')
    if not rows:
        return {'record': None, 'contract': None, 'reading': None, 'prompt': None}
    record = rows[-1]
    found = {'record': common.body(record), 'record_id': record.get('_id'), 'contract': None, 'reading': None,
             'prompt': None}
    for key, blob in (('contract', 'contract_blob'), ('reading', 'reading_blob')):
        try:
            found[key] = _blob_json(store, record[blob])
        except (KeyError, OSError, ValueError, TypeError) as exc:
            errors.append(f'intake {key} unreadable: {exc}')
    try:
        found['prompt'] = store.get_blob(record['request_sha256']).decode('utf-8')
    except (KeyError, OSError, ValueError, TypeError, UnicodeDecodeError) as exc:
        errors.append(f'request bytes unreadable: {exc}')
    return found


def _plan(store, given, errors):
    """The run's plan: the given plan when it is the latest one the controller pinned, else the latest pinned.

    Internal planning plans (the judgment graph binds them to run its own review seats) are never
    the run's plan, whatever their order in the store.
    """
    rows = [r for r in records(store, 'plan') if type(r.get('blob')) is str]
    pinned = [r for r in rows if r.get('source') not in PLANNING_SOURCES]
    latest, problems, stored = pinned[-1] if pinned else None, [], None
    record = latest
    if given is not None:
        matching = [r for r in rows if r.get('plan_sha256') == given.get('sha256')]
        record = matching[-1] if matching else None
        if record is None:
            problems.append('the plan given to the sink has no plan record in the controller store')
        elif record.get('source') in PLANNING_SOURCES:
            problems.append('the plan given to the sink is an internal planning plan, not the run\'s plan')
        elif latest is not None and record.get('plan_sha256') != latest.get('plan_sha256'):
            problems.append('the plan given to the sink is not the latest plan the controller pinned')
    if record is not None:
        try:
            stored = _blob_json(store, record['blob'])
        except (OSError, ValueError, TypeError) as exc:
            problems.append(f'the pinned plan cannot be read: {exc}')
    if given is None:
        plan = stored
    else:
        plan = deepcopy(given)
        expected = stored
        if 'engagement' in given and record is not None and type(record.get('applied_blob')) is str:
            # The engagement decision's applied view is pinned in the same plan record, beside the scientific bytes:
            # a view handed over is checked against that pinned view.
            try:
                expected = _blob_json(store, record['applied_blob'])
            except (OSError, ValueError, TypeError) as exc:
                problems.append(f'the pinned applied view cannot be read: {exc}')
        if expected is not None and common.canonical(given) != common.canonical(expected):
            problems.append('the plan given to the sink differs from the plan record of its digest')
    if plan is not None and stored is not None and plan.get('sha256') != (record or {}).get('plan_sha256'):
        problems.append('the plan digest differs from the pinned plan record')
    if plan is None:
        problems.append('no plan is pinned for this run')
    errors.extend(problems)
    return {'plan': plan, 'sha256': (plan or {}).get('sha256'), 'record_id': (record or {}).get('_id'),
            'revision': (record or {}).get('revision'), 'problems': problems}


def launch_kind(finished):
    """``confined``, ``unconfined``, ``unqualified`` or ``unknown`` for a finished launch record.

    A launch is confined only when its plan names a backend and carries confined execution's
    denial-probe qualification for that backend, confirmed; a backend without it is ``unqualified``.
    """
    if finished is None:
        return 'unknown'
    plan = finished.get('plan') if type(finished.get('plan')) is dict else {}
    if plan.get('kind') in UNCONFINED_KINDS or plan.get('label_text') == common.UNCONFINED:
        return 'unconfined'
    backend = finished.get('backend') or plan.get('backend')
    if type(backend) is not str or not backend:
        return 'unknown'
    probe = plan.get('qualification') if type(plan.get('qualification')) is dict else {}
    return 'confined' if probe.get('confirmed') is True and probe.get('backend') == backend else 'unqualified'


def _launches(store):
    rows = records(store, 'step-launch')
    launches, order = {}, []
    for row in rows:
        if row.get('phase') == 'started':
            launches[row['_id']] = {'id': row['_id'], 'step_id': row.get('step_id'), 'attempt': row.get('attempt'),
                                    'started': row, 'refused': None, 'finished': None}
            order.append(row['_id'])
    for row in rows:
        phase = row.get('phase')
        if phase in ('refused', 'finished'):
            entry = launches.get(row.get('started'))
            if entry is None:
                entry = {'id': row.get('_id'), 'step_id': row.get('step_id'), 'attempt': row.get('attempt'),
                         'started': None, 'refused': None, 'finished': None, 'orphan': True}
                launches[row.get('_id')] = entry
                order.append(row.get('_id'))
            entry[phase] = row
    out = []
    for key in order:
        entry = launches[key]
        finished = entry['finished']
        plan = (finished or {}).get('plan') if type((finished or {}).get('plan')) is dict else {}
        entry['kind'] = 'refused' if entry['refused'] and finished is None else launch_kind(finished)
        entry['backend'] = (finished or {}).get('backend') or plan.get('backend')
        probe = plan.get('qualification') if type(plan.get('qualification')) is dict else None
        entry['qualification'] = None if probe is None else {
            'backend': probe.get('backend'), 'confirmed': probe.get('confirmed') is True,
            'checks': common.plain(probe.get('checks')), 'unavailable': probe.get('unavailable')}
        entry['label'] = plan.get('label_text') if entry['kind'] == 'unconfined' else None
        entry['exit_status'] = (finished or {}).get('exit_status')
        entry['errors'] = list(((finished or {}).get('confinement') or {}).get('errors') or [])
        entry['resource_enforcement'] = common.plain(plan.get('resource_enforcement'))
        entry['limits_enforced'] = common.plain(plan.get('limits_enforced'))
        entry['limit_scopes'] = common.plain(plan.get('limit_scopes'))
        out.append(entry)
    return out


def _budget(store):
    """Per dimension: measured and charged sums, and how many attempts left it unmeasured (never zero-filled)."""
    reservations = _latest(records(store, 'budget-reservation'), 'key')
    settlements = _latest(records(store, 'budget-settlement'), 'key')
    dims = {}
    for dimension in DIMENSIONS:
        measured, charged, unknown = 0, 0, 0
        for key, reservation in reservations.items():
            settlement = settlements.get(key)
            amounts = reservation.get('amounts') or {}
            if settlement is None or settlement.get('status') not in SETTLED:
                value = amounts.get(dimension)
                charged += value if type(value) in (int, float) else 0
                unknown += 1
                continue
            observed = (settlement.get('measured') or {}).get(dimension)
            cost = (settlement.get('charged') or {}).get(dimension)
            charged += cost if type(cost) in (int, float) else 0
            if settlement.get('status') == 'released':
                continue  # nothing started: nothing to measure
            if type(observed) in (int, float):
                measured += observed
            else:
                unknown += 1
        dims[dimension] = {'measured': measured, 'charged': charged, 'unknown_attempts': unknown}
    return {'attempts': len(reservations), 'dimensions': dims,
            'open': sorted(k for k in reservations if (settlements.get(k) or {}).get('status') not in SETTLED)}


def _service(name):
    """Use an active controller's services without loading its execution graph for an observation."""
    graph = sys.modules.get('ravel.controller.graph')
    if graph is not None:
        return graph.service(name)
    if name == 'instructions':
        return importlib.import_module('ravel.controller.instructions')
    return common.module(name)


def _authority(store, errors, plan):
    mod = _service('authority')
    found = {'available': mod is not None, 'records': None, 'mode': None, 'deviations': None, 'stop': None,
             'requests': [], 'errors': []}
    raw = records(store, 'authority')
    try:
        if mod is not None and hasattr(mod, 'records'):
            found['records'] = mod.records(store)
        else:
            found['records'] = [{k: r.get(k) for k in ('uid', 'kind', 'decision', 'option', 'label', 'source',
                                                       'time_ns', 'authorizes_effects', 'request')} | {'id': r.get('uid')}
                                for r in raw if r.get('schema') in (None, 'authority-record.v1')]
    except Exception as exc:  # an authority fault is reported, never treated as authority
        found['errors'].append(f'authority records: {type(exc).__name__}: {exc}')
    try:
        if mod is not None and hasattr(mod, 'frozen'):
            found['mode'] = mod.frozen(store, required=False)
        else:
            modes = records(store, 'mode')
            found['mode'] = common.body(modes[-1]) if modes else None
    except Exception as exc:
        found['errors'].append(f'operating mode: {type(exc).__name__}: {exc}')
    try:
        if mod is not None and hasattr(mod, 'deviations'):
            found['deviations'] = mod.deviations(store)
        else:
            found['deviations'] = [{'id': r.get('uid'), 'decision': r.get('decision'), 'label': r.get('label'),
                                    'change': (r.get('subject') or {}).get('change')}
                                   for r in raw if r.get('kind') == 'deviation']
    except Exception as exc:
        found['errors'].append(f'deviations: {type(exc).__name__}: {exc}')
    try:
        if mod is not None and hasattr(mod, 'stop_state'):
            found['stop'] = mod.stop_state(store)
    except Exception as exc:
        found['errors'].append(f'stop state: {type(exc).__name__}: {exc}')
    found['requests'] = [{k: r.get(k) for k in ('uid', 'kind', 'reason', 'needed', 'since_ns', 'answerable')}
                         for r in records(store, 'authority-request')]
    found['defaults'] = [{'id': r.get('uid'), 'kind': r.get('kind'), 'option': r.get('option'),
                          'label': r.get('label'), 'comment': r.get('comment'), 'request': r.get('request')}
                         for r in raw if r.get('decision') == 'default']
    found['current'] = {'approve_plan': None, 'final': None}
    if plan.get('sha256') and not plan['problems']:
        pins = {'plan_sha256': plan['sha256']}
        for kind, method in (('approve_plan', 'verify'), ('final', 'disposition')):
            check = getattr(mod, method, None)
            if not callable(check):
                found['errors'].append(f'current {kind}: authority {method} is unavailable')
                continue
            for row in reversed(found['records'] or []):
                if row.get('kind') != kind:
                    continue
                try:
                    accepted = check(store, row.get('id'), kind=kind, subject=pins)
                    if (type(accepted) is dict and accepted.get('kind') == kind
                            and accepted.get('decision') == ('accept' if kind == 'final' else 'approve')
                            and (kind == 'final' or accepted.get('authorizes_effects') is True)):
                        found['current'][kind] = accepted.get('id') or row.get('id')
                except Exception as exc:
                    found['errors'].append(f'current {kind}: {type(exc).__name__}: {exc}')
                break  # a later refusal or disposition cannot resurrect an older acceptance
        lineage = getattr(mod, 'plan_authority', None)
        if found['current']['approve_plan'] is None and callable(lineage):
            # A plan amended by an approved deviation (a replan, a recovery) is approved by its CHECK-IN 1 and the
            # current amendment the authority service authenticates as one lineage ending in this exact plan.
            try:
                approval, amendment = lineage(store, pins)
                if approval is not None and amendment is not None:
                    found['current']['approve_plan'] = approval.get('id')
                    found['current']['deviation'] = amendment.get('id')
            except Exception as exc:
                found['errors'].append(f'current plan lineage: {type(exc).__name__}: {exc}')
    errors.extend(found['errors'])
    return found


def instruction_observations(store, observations, dispatches):
    """Recheck acknowledgements in current, controller-observed instruction completions.

    The delivery-session projection is accounting only. Instruction custody binds the internal
    session to a run, step, attempt, packet, final record and the observed artifact bytes.
    """
    instructions = _service('instructions')
    sessions = records(store, 'worker-session')
    completions = records(store, 'worker-completion')
    deliveries = records(store, 'instruction-delivery')
    latest = {}

    def worker(row):
        # One worker node per seat: a seat of a producer step observes under its own step id, while its dispatch
        # names the producer's step, so the node identifies the seat in both.
        return row.get('node_id') or (row.get('step_id'), row.get('seat'))
    for row in observations:
        key = worker(row)
        if key not in latest or (row.get('attempt') or 0) >= (latest[key].get('attempt') or 0):
            latest[key] = row
    for row in dispatches:
        key = worker(row)
        if key not in latest or (row.get('attempt') or 0) > (latest[key].get('attempt') or 0):
            latest[key] = {**row, 'status': 'ok', 'session_id': None}
    result = []
    for row in latest.values():
        if row.get('status') != 'ok':
            continue
        found = {k: row.get(k) for k in ('step_id', 'seat', 'attempt')}
        found.update(delivered=False, errors=[])
        try:
            matching = [s for s in sessions if s.get('session_id') == row.get('session_id')
                        and s.get('step') == row.get('step_id') and s.get('attempt') == row.get('attempt')
                        and s.get('seat') == row.get('seat')]
            if not row.get('session_id') or len(matching) != 1:
                raise ValueError('exactly one controller-observed instruction session is required')
            session = matching[0]
            identity = session['_id']
            manifest = instructions.manifest(session['step_spec'], session['card'])
            bound = dict(run_id=store.run_id, step=row['step_id'], attempt=row['attempt'],
                         manifest_sha256=manifest['sha256'], packet_sha256=session['packet']['sha256'])
            delivered = [d for d in deliveries if d.get('kind') == 'instruction-delivery'
                         and d.get('session') == identity]
            expected = instructions.receipt(manifest, session['packet'], session=identity)
            expected.update(run_id=store.run_id, attempt=row['attempt'])
            if len(delivered) != 1 or any(delivered[0].get(k) != v for k, v in expected.items()):
                raise ValueError('the observed instruction delivery differs from its session or packet')
            found['delivered'] = True
            completed = [c for c in completions if c.get('session') == identity]
            if len(completed) != 1 or any(completed[0].get(k) != v for k, v in bound.items()):
                raise ValueError('exactly one completion bound to the step attempt and packet is required')
            completion = completed[0]
            with instructions.observed_completion(store, session=identity, completion_id=completion['_id']):
                errors_ = instructions.check_ack(manifest, completion['final_record'],
                                                [a['path'] for a in completion['artifacts']])
            if type(errors_) is not list:
                raise ValueError('the instruction verifier returned no error list')
            found['errors'] = [str(e) for e in errors_]
        except Exception as exc:
            found['errors'] = [f'{type(exc).__name__}: {exc}']
        result.append(found)
    return result


def _identity(store, errors):
    """The running code's identity (confined execution) and the identity the run pinned at intake, when it did."""
    found = {'live': None, 'pinned': None, 'governed': None, 'label': None, 'problems': []}
    confine = common.module('confine')
    if confine is None or not hasattr(confine, 'code_identity'):
        found['problems'].append('the code identity of the running controller is unknown')
    else:
        try:
            live = confine.code_identity()
            if hasattr(confine, 'require_governed_install'):
                live = confine.require_governed_install(development=True, identity=live)
            found['live'] = common.plain(live)
            found['governed'] = bool(live.get('governed'))
            found['label'] = live.get('label')
            found['problems'].extend(live.get('problems') or [])
        except Exception as exc:
            found['problems'].append(f'code identity: {type(exc).__name__}: {exc}')
    pinned = records(store, 'code-identity')
    if pinned:
        found['pinned'] = common.body(pinned[0])
        want = (found['pinned'].get('identity') or found['pinned']).get('digest')
        have = (found['live'] or {}).get('digest')
        if want and have and want != have:
            found['problems'].append('the running code differs from the code this run pinned at intake')
            found['governed'] = False
        if found['pinned'].get('label') == common.NOT_GOVERNED:
            found['governed'] = False
            found['label'] = common.NOT_GOVERNED
    errors.extend(found['problems'])
    return found


def _governance(run_dir):
    """Host governance's label for the run directory: ``NOT GOVERNED`` when the controller does not own it.

    The label, its reasons, the host findings observed now and the host events recorded for the run
    come from host governance; the sink only renders them. Absent or failing, it is unknown.
    """
    found = {'available': False, 'label': None, 'controller_run': None, 'reasons': [], 'host_findings': [],
             'host_events': [], 'error': None}
    mod = common.module('governance')
    label_of = getattr(mod, 'governance_label', None) if mod is not None else None
    if not callable(label_of):
        found['error'] = 'the host governance label is not installed'
        return found
    if run_dir is None:
        found['error'] = 'the store names no run directory'
        return found
    try:
        value = label_of(run_dir)
    except Exception as exc:  # a governance fault is reported, never treated as governed
        found['error'] = f'host governance: {type(exc).__name__}: {exc}'[:500]
        return found
    if type(value) is not dict:
        found['error'] = 'host governance returned no governance object'
        return found
    listed = lambda key: list(value.get(key)) if type(value.get(key)) in (list, tuple) else []  # noqa: E731
    found.update(available=True, label=None if value.get('label') is None else str(value['label']),
                 controller_run=value.get('controller_run') if type(value.get('controller_run')) is str else None,
                 reasons=[str(r) for r in listed('reasons')][:100], host_findings=common.plain(listed('host_findings')[:50]),
                 host_events=common.plain(listed('host_events')[:50]))
    return found


def _issuer():
    """The authority issuer's own description of its authentication and residual risk, or why it is absent."""
    mod = common.module('issuer')
    describe = getattr(mod, 'receipt', None) if mod is not None else None
    if not callable(describe):
        return {'available': False, 'description': None, 'error': 'the authority issuer is not installed'}
    try:
        value = describe()
    except Exception as exc:
        return {'available': False, 'description': None, 'error': f'{type(exc).__name__}: {exc}'[:500]}
    if type(value) is not dict:
        return {'available': False, 'description': None, 'error': 'the authority issuer described nothing'}
    return {'available': True, 'description': common.plain(value), 'error': None}


def _engagement_refusals(section):
    """Recorded floor breaches survive rechecks; broker evidence must remain current."""
    checks = section.get('envelope_checks') or []
    breaches = [row for row in checks if row.get('failures') or row.get('status') == 'below_floor']
    reasons = []
    if breaches:
        reasons.append({'code': 'engagement_breach_recorded',
                        'message': 'a recorded engagement floor breach forbids acceptance'})
    used_broker = any((row.get('broker') or {}).get('available') is True for row in checks)
    last = checks[-1] if checks else {}
    if used_broker and (last.get('stage') != 'deliver'
                        or (last.get('broker') or {}).get('available') is not True
                        or (not breaches and section.get('accepted_allowed') is not True)):
        reasons.append({'code': 'engagement_broker_unavailable',
                        'message': 'this run used a broker but has no current delivery accounting verdict'})
    return reasons


def engagement_view(store):
    """The engagement policy's receipt section (read only), or why it is unknown.

    Acceptance needs the policy's own verdict on a current delivery-stage envelope check
    (``accepted_allowed``); an absent policy, a failing read or a missing verdict allows nothing.
    """
    found = {'available': False, 'error': None, 'labels': [], 'envelope_status': 'unknown',
             'accepted_allowed': False, 'architecture_complete_allowed': False}
    mod = common.module('engagement')
    section_of = getattr(mod, 'receipt_section', None) if mod is not None else None
    if not callable(section_of):
        found['error'] = 'the engagement policy is not installed'
        return found
    try:
        section = section_of(store)
    except Exception as exc:  # an engagement fault is reported, never a pass
        found['error'] = f'{type(exc).__name__}: {exc}'[:500]
        return found
    if type(section) is not dict:
        found['error'] = 'the engagement policy returned no receipt section'
        return found
    found.update({k: v for k, v in common.plain(section).items() if k not in found})
    found.update(available=True, envelope_status=str(section.get('envelope_status') or 'unknown'),
                 labels=[str(x) for x in section.get('labels') or () if type(x) is str],
                 accepted_allowed=section.get('accepted_allowed') is True,
                 architecture_complete_allowed=section.get('architecture_complete_allowed') is True)
    found['refusal_reasons'] = _engagement_refusals(section)
    if found['refusal_reasons']:
        found.update(accepted_allowed=False, architecture_complete_allowed=False)
        if any(reason['code'] == 'engagement_breach_recorded' for reason in found['refusal_reasons']):
            found['envelope_status'] = 'below_floor'
            found['labels'] = sorted(set(found['labels']) | {'ENGAGEMENT BELOW FLOOR'})
        if any(reason['code'] == 'engagement_broker_unavailable' for reason in found['refusal_reasons']):
            found['labels'] = sorted(set(found['labels']) | {'USAGE UNKNOWN'})
            if found['envelope_status'] != 'below_floor':
                found['envelope_status'] = 'unknown'
    return found


def engagement_check(store):
    """Require current engagement evidence for delivery; return any refusal reason.

    Called by ``deliver`` and ``bounded_end`` before evidence gathering. A current, verified
    broker accounting verdict is retained; missing or stale broker evidence and recorded
    breaches refuse acceptance. Runs without broker history receive a fresh policy check.
    """
    mod = common.module('engagement')
    check = getattr(mod, 'check_envelope', None) if mod is not None else None
    if not callable(check):
        return None
    try:
        section_of = getattr(mod, 'receipt_section', None)
        section = section_of(store) if callable(section_of) else {}
        if type(section) is not dict:
            return 'engagement_evidence_invalid: the engagement policy returned no receipt section'
        refusals = _engagement_refusals(section)
        if refusals:
            return '; '.join(reason['code'] + ': ' + reason['message'] for reason in refusals)
        # receipt_section verifies the decision, escalation and complete usage census bindings.
        # Reuse its current broker verdict: calling with broker=None would discard H5 evidence.
        checks = section.get('envelope_checks') or []
        if checks and (checks[-1].get('broker') or {}).get('available') is True:
            return None
        check(store, 'deliver')
    except Exception as exc:
        return f'the engagement envelope check failed: {type(exc).__name__}: {exc}'[:1000]
    return None


def route_endings(store):
    """Every route ending record in store order, with the route that wrote it, each content once.

    ``ending-synthesis`` records name their source and carry ``result``; the route adapters' own
    ending records are rendered whole. A synthesis repeating a route's own record is shown once.
    """
    rows = []
    for kind, source in common.ROUTE_ENDINGS:
        for row in records(store, kind):
            if row.get('_malformed'):
                rows.append((row.get('_seq') or 0, {'kind': kind, 'source': source, 'record': None,
                                                    'result': None, 'malformed': True}))
                continue
            named = row.get('source') or row.get('route') if kind == common.ENDING_SYNTHESIS else source
            result = row.get('result', common.body(row)) if kind == common.ENDING_SYNTHESIS else common.body(row)
            rows.append((row.get('_seq') or 0, {'kind': kind, 'source': named, 'record': row.get('_id'),
                                                'result': result}))
    out, seen = [], set()
    for _, row in sorted(rows, key=lambda pair: pair[0]):
        key = common.digest(common.plain([row['source'], row['result']]))
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def ledger_view(store):
    """The obligation ledger's summary for the receipt, or why it is unknown."""
    mod = common.module('ledger')
    if mod is None:
        return {'available': False, 'summary': None, 'error': 'the obligation ledger is not installed'}
    try:
        return {'available': True, 'summary': mod.summary(store), 'error': None}
    except Exception as exc:
        return {'available': True, 'summary': None, 'error': f'{type(exc).__name__}: {exc}'}


def gather(store, plan=None):
    """Everything the sink knows about the run, from the store only (plus the live code identity)."""
    errors = []
    ev = {'run_id': getattr(store, 'run_id', None), 'run_dir': common.run_dir(store), 'errors': errors}
    ev['binding'] = _binding(store)
    ev['store_problems'] = _verify(store)
    requests = records(store, 'request')
    ev['request'] = common.body(requests[-1]) if requests else None
    ev['intake'] = _intake(store, errors)
    ev['plan'] = _plan(store, plan, errors)
    ev['outcome_rows'] = records(store, 'step-outcome')
    ev['outcomes'] = _latest(ev['outcome_rows'], 'step_id')
    ev['custody_rows'] = records(store, 'custody')
    ev['custody'] = _latest(ev['custody_rows'], 'artifact')
    from ravel.controller.step import host_operations
    ev['host_receipt_errors'] = {name: host_operations.custody_errors(store, row)
                                 for name, row in ev['custody'].items()}
    ev['launches'] = _launches(store)
    ev['observations'] = records(store, 'step-observation')
    ev['dispatches'] = records(store, 'step-dispatch')
    ev['validations'] = records(store, 'step-validation')
    ev['credits'] = records(store, 'step-credit')
    ev['refusals'] = records(store, 'step-refusal')
    ev['deliveries'] = records(store, 'instruction-delivery')
    ev['instruction_observations'] = instruction_observations(store, ev['observations'], ev['dispatches'])
    ev['escalations'] = records(store, 'step-escalation')
    ev['flags'] = records(store, 'checkin-flag')
    ev['budget'] = _budget(store)
    try:
        from ravel.controller import model_cost
        ev['model_cost'] = model_cost.summary(store)
    except Exception as exc:
        ev['model_cost'] = {'status': 'unknown', 'error': type(exc).__name__}
    ev['authority'] = _authority(store, errors, ev['plan'])
    ev['judgments'] = records(store, 'judgment-record')
    ev['judgment_outcomes'] = records(store, 'judgment-outcome')
    ev['wms'] = records(store, 'wms-submission')
    # Review seats the operator's restricted unsandboxed reviewer fallback served (no OS worker sandbox).
    ev['review_fallbacks'] = records(store, 'review-sandbox-fallback')
    ev['endings'] = route_endings(store)
    ev['bounded'] = records(store, 'ending')
    ev['targets'] = records(store, common.DELIVERY_TARGET)
    ev['receipts'] = records(store, common.STORE_RECEIPT)
    ev['identity'] = _identity(store, errors)
    ev['governance'] = _governance(ev['run_dir'])
    ev['issuer'] = _issuer()
    ev['engagement'] = engagement_view(store)
    return ev
