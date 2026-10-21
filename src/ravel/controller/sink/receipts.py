"""The architecture receipt of a controller run, computed from controller evidence.

Every field is derived from the run's store records, the ledger, the authority service, the
confinement records, the engagement policy, the host governance label and the sink's own
inventory; an absent source stays ``None`` or ``unknown``, never zero or success.
``architecture_complete`` is derived from named predicates (controller mode with governed code and
a controller-owned run directory, qualified confinement, an intact custody chain, every
result-path obligation met, every review seat credited, every instruction acknowledged, authority
recorded for the plan and the final disposition, an engagement envelope that allows acceptance, a
sink-rendered delivery and an accepted label). No caller, fixture or worker sets it. The receipt
also carries the authority issuer's own account of its authentication and residual risk; terminal
identity is never attested.
"""
from __future__ import annotations

from . import common

PREDICATES = ('controller_mode', 'confinement_qualified', 'custody_chain', 'ledger_result_path', 'review_complete',
              'instructions_acknowledged', 'authority_recorded', 'sink_rendered', 'accepted_delivery',
              'engagement_complete')
MAX_ROWS = 500
SEVERITY = (common.NOT_GOVERNED, common.QUALIFIED, common.DIAGNOSTIC, common.REVIEW_INCOMPLETE, common.UNCONFINED)


def _bounded(rows, limit=MAX_ROWS):
    rows = list(rows or [])
    return rows[:limit]


def governance(ev):
    """Host governance's label, reasons, host findings and recorded host events for the run directory."""
    found = ev['governance']
    return {'available': found['available'], 'label': found['label'], 'controller_run': found['controller_run'],
            'this_run': found['controller_run'] is not None and found['controller_run'] == ev['run_id'],
            'reasons': found['reasons'], 'host_findings': found['host_findings'],
            'host_events': found['host_events'], 'error': found['error']}


def host(ev, findings):
    gaps = []
    for launch in ev['launches']:
        if launch['kind'] in ('unconfined', 'unknown', 'unqualified') and launch['finished'] is not None:
            gaps.append(f"launch {launch['id']} ({launch['step_id']}): {launch['kind']}")
        if launch['errors']:
            gaps.append(f"launch {launch['id']}: confinement finish errors")
    inventory = []
    for observation in ev['observations']:
        tools = observation.get('tool_inventory')
        inventory.append({'step_id': observation.get('step_id'), 'seat': observation.get('seat'),
                          'attempt': observation.get('attempt'), 'transport': observation.get('transport'),
                          'status': observation.get('status'), 'inventory': common.plain(tools)})
        if observation.get('status') == 'ok' and not tools:
            gaps.append(f"worker session of {observation.get('step_id')}: no observed tool inventory")
    identity = ev['identity']
    if identity.get('governed') is not True:
        gaps.append('controller code identity: ' + '; '.join(identity.get('problems') or ['not governed']))
    for problem in (ev['binding'] or []) + (ev['store_problems'] or []):
        gaps.append(problem)
    if ev['binding'] is None:
        gaps.append('run binding unknown')
    if ev['store_problems'] is None:
        gaps.append('store chain unknown')
    live = identity.get('live') or {}
    return {'mode': 'controller' if ev['run_dir'] is not None and ev['request'] is not None else 'unrestricted-host',
            'tool_inventory': inventory,
            'whole_host_enforcement': 'controller' if not gaps else {'gaps': _bounded(gaps, 100)},
            'code_identity': {'kind': live.get('kind'), 'version': live.get('version'), 'digest': live.get('digest'),
                              'governed': identity.get('governed'), 'label': identity.get('label'),
                              'pinned_digest': ((identity.get('pinned') or {}).get('identity') or
                                                (identity.get('pinned') or {})).get('digest')},
            'custody_boundary': common.CUSTODY_BOUNDARY, 'governance': governance(ev),
            'errors': _bounded(ev['errors'], 100)}


def work(ev, ledger, findings):
    refused = []
    for row in ev['refusals']:
        refused.append({'source': 'step', 'step_id': row.get('step_id'), 'attempt': row.get('attempt'),
                        'seat': row.get('seat'), 'reason': row.get('reason')})
    for launch in ev['launches']:
        if launch['refused'] is not None:
            refused.append({'source': 'launch', 'step_id': launch['step_id'], 'attempt': launch['attempt'],
                            'reason': launch['refused'].get('reason')})
    summary = (ledger or {}).get('summary') or {}
    for event in summary.get('refusal_events') or ():
        refused.append({'source': 'ledger', **{k: v for k, v in (event if type(event) is dict else {}).items()
                                               if k in ('entry', 'id', 'reason', 'code', 'time_ns')}})
    chain = (summary.get('chain') or {}).get('verified')
    complete = 'complete' if chain is True and ev['store_problems'] == [] else 'incomplete'
    holds = [{'step_id': k, 'status': v.get('status'), 'reason': v.get('reason')}
             for k, v in sorted(ev['outcomes'].items()) if v.get('status') not in ('completed',)]
    return {'refused': _bounded(refused), 'refused_count': len(refused), 'refusal_history_completeness': complete,
            'holds': _bounded(holds), 'current_refusals': _bounded(findings.refusals)}


def costs(ev):
    dims = ev['budget']['dimensions']

    def whole(name):
        row = dims[name]
        return None if row['unknown_attempts'] else row['measured']
    unknown = sorted(d for d, v in dims.items() if v['unknown_attempts'])
    total = whole('cost_usd')
    return {'total': total, 'currency': 'USD' if total is not None else None, 'model_calls': whole('model_calls'),
            'tokens': whole('tokens'), 'wall_seconds': whole('wall_seconds'), 'attempts': ev['budget']['attempts'],
            'measured_partial': {d: v['measured'] for d, v in dims.items()},
            'charged': {d: v['charged'] for d, v in dims.items()}, 'unknown': unknown,
            'open_reservations': ev['budget']['open'], 'coverage': 'complete' if not unknown else 'partial'}


def ledger_section(ledger, unmet, decisions):
    summary = (ledger or {}).get('summary') or {}
    keys = ('by_status', 'by_class', 'by_ledger_class', 'head', 'events', 'catalogue_sha256', 'catalogue_current',
            'refusals', 'waivers', 'violations', 'not_applicable', 'deliverables', 'current', 'superseded',
            'instances', 'plan_revision')
    section = {k: common.plain(summary.get(k)) for k in keys}
    section.update(available=bool((ledger or {}).get('available')), error=(ledger or {}).get('error'),
                   chain_verified=(summary.get('chain') or {}).get('verified'),
                   unmet=_bounded(common.plain(unmet), 200) if unmet is not None else None,
                   unmet_count=len(unmet) if unmet is not None else None, decisions=common.plain(decisions))
    return section


def authority(ev):
    auth = ev['authority']
    records = auth.get('records')
    mode = auth.get('mode') or {}
    return {'available': auth.get('available'),
            'mode': {'mode': mode.get('mode'), 'delegation': mode.get('delegation'),
                     'operator_source': mode.get('operator_source'), 'record_id': mode.get('id') or mode.get('uid'),
                     'allow_unconfined': mode.get('allow_unconfined')} if mode else None,
            'records': _bounded(common.plain(records)) if records is not None else None,
            'labels': sorted({r.get('label') for r in records or [] if r.get('label')}) if records is not None else None,
            'deviations': common.plain(auth.get('deviations')), 'pending_requests': common.plain(auth.get('requests')),
            'stop_state': auth.get('stop'), 'current': common.plain(auth.get('current')),
            'errors': auth.get('errors')}


def latest_validations(ev):
    """The latest validation of each step and seat (a superseded attempt no longer decides)."""
    found = {}
    for row in ev['validations']:
        key = (row.get('step_id'), row.get('seat'))
        if key not in found or (row.get('attempt') or 0) >= (found[key].get('attempt') or 0):
            found[key] = row
    return list(found.values())


def unacknowledged(ev):
    rows = [{k: row.get(k) for k in ('step_id', 'seat', 'attempt')}
            for row in ev['instruction_observations'] if row['errors']]
    for row in latest_validations(ev):
        codes = {e.get('code') for e in row.get('errors') or () if type(e) is dict}
        held = {e.get('code') for e in row.get('held') or () if type(e) is dict}
        if 'instruction_ack' in codes or 'checklist_blocked' in held:
            rows.append({'step_id': row.get('step_id'), 'seat': row.get('seat'), 'attempt': row.get('attempt')})
    return rows


def undelivered_sessions(ev):
    """Completed worker sessions with no instruction delivery receipt for their step, seat and attempt."""
    return [{k: row.get(k) for k in ('step_id', 'seat', 'attempt')}
            for row in ev['instruction_observations'] if not row['delivered']]


def instructions(ev):
    deliveries = [{'step_id': d.get('step') or d.get('step_id'), 'seat': d.get('seat'), 'attempt': d.get('attempt'),
                   'kind': d.get('kind'), 'manifest_sha256': d.get('manifest_sha256'),
                   'packet_sha256': d.get('packet_sha256'), 'session': d.get('session')} for d in ev['deliveries']]
    incomplete = unacknowledged(ev)
    sessions = [o for o in ev['observations'] if o.get('status') == 'ok']
    undelivered = undelivered_sessions(ev)
    if not sessions:
        status = 'unknown' if not ev['validations'] else ('incomplete' if incomplete else 'complete')
    else:
        status = 'incomplete' if incomplete or undelivered else 'complete'
    return {'deliveries': _bounded(deliveries), 'observed_acknowledgements': _bounded(ev['instruction_observations']),
            'acknowledgement': status, 'incomplete': _bounded(incomplete),
            'sessions_without_delivery_receipt': _bounded(undelivered), 'worker_sessions': len(sessions)}


def confinement(ev):
    launches = [{'id': l['id'], 'step_id': l['step_id'], 'attempt': l['attempt'], 'backend': l['backend'],
                 'kind': l['kind'], 'label': l['label'], 'exit_status': l['exit_status'],
                 'qualification': l.get('qualification'), 'errors': l['errors'][:5],
                 'resource_enforcement': l.get('resource_enforcement'),
                 'limits_enforced': l.get('limits_enforced'),
                 'limit_scopes': l.get('limit_scopes')} for l in ev['launches']]
    unconfined = sum(1 for l in launches if l['kind'] == 'unconfined')
    unknown = sum(1 for l in launches if l['kind'] == 'unknown')
    unqualified = sum(1 for l in launches if l['kind'] == 'unqualified')
    remote = [{'launch_id': s.get('launch_id'), 'policy': 'remote confinement: facility policy',
               'jobscript_sha256': s.get('jobscript_sha256')} for s in ev['wms']]
    status = ('unconfined' if unconfined else 'unknown' if unknown or any(l['errors'] for l in launches)
              else 'unqualified' if unqualified else 'qualified' if launches else 'no launches')
    return {'launches': _bounded(launches), 'unconfined': unconfined, 'unknown': unknown, 'unqualified': unqualified,
            'provider_egress': _bounded([{'step_id': row.get('step_id'), 'attempt': row.get('attempt'),
                                        'transport': row.get('transport'), 'egress': row.get('provider_egress')}
                                       for row in ev.get('observations', [])]),
            'remote': _bounded(remote), 'status': status,
            'allow_unconfined': ((ev['authority'].get('mode') or {}).get('allow_unconfined'))}


def authority_security(ev):
    """The authority issuer's own account (``issuer.receipt()``, its keys unchanged: authentication, key
    location, residual same-user risk), whether it is installed, and the denial-probe qualification observed
    for the run's launches. Terminal identity is never attested, whatever any source says."""
    issuer = ev['issuer']
    launches = [l for l in ev['launches'] if l['finished'] is not None and l['kind'] != 'unconfined']
    confirmed = [l['id'] for l in launches if (l.get('qualification') or {}).get('confirmed') is True]
    return {**(issuer['description'] or {}), 'issuer_available': issuer['available'], 'issuer_error': issuer['error'],
            'terminal_identity_attested': False,
            'confinement_probe': {'launches': len(launches), 'confirmed': len(confirmed),
                                  'unconfirmed': _bounded([l['id'] for l in launches if l['id'] not in confirmed], 100),
                                  'backends': sorted({str((l.get('qualification') or {}).get('backend'))
                                                      for l in launches if l['id'] in confirmed})}}


def engagement(ev):
    """The engagement policy's receipt section: tier, decision, seat plan, envelope checks and labels."""
    section = dict(ev['engagement'])
    for key in ('escalations', 'envelope_checks'):
        if type(section.get(key)) is list:
            section[key] = section[key][-MAX_ROWS:]
    return common.plain(section)


def review(findings):
    seats = [{'step_id': c['step_id'], 'seat': c['seat'], 'role': c['role'], 'attempt': c['attempt'],
              'credited': c['credited'], 'verdict': c['verdict'], 'family_relation': c['family_relation'],
              'label': c['label'], 'evidence_boundary': c['boundary'], 'record_id': c['record_id']}
             for c in getattr(findings, 'credits', [])]
    rounds = {purpose: {'attempt': row.get('attempt'), 'seats': common.plain(row.get('seats'))}
              for purpose, row in (getattr(findings, 'rounds', {}) or {}).items()}
    return {'seats': _bounded(seats), 'rounds': rounds,
            'missing': [s for s in seats if not s['credited']]}


def judgments(ev, findings):
    classes = {}
    for record in ev['judgments']:
        classes[record.get('class') or 'unknown'] = classes.get(record.get('class') or 'unknown', 0) + 1
    return {'count': len(ev['judgments']), 'by_class': classes,
            'adopted_defaults': _bounded(common.plain(getattr(findings, 'defaults', [])))}


def labels(findings, extra=()):
    """Every label the sink renders, most severe first, each once."""
    found = [*extra, *[entry['label'] for entry in findings.labels]]
    ordered = [label for label in SEVERITY if label in found]
    for label in found:
        if label not in ordered:
            ordered.append(label)
    return ordered


def predicates(ev, ledger, unmet, decisions, findings, section, delivered_label, rendered):
    summary = (ledger or {}).get('summary') or {}
    auth = ev['authority'].get('current') or {}
    usage_known = section['costs']['coverage'] == 'complete' and not section['costs']['open_reservations'] \
        and not any(o.get('status') == 'ok' and (o.get('usage') or {}).get('reported') is not True
                    for o in ev['observations'])
    owned = section['host']['governance']
    return {
        'controller_mode': bool(section['host']['mode'] == 'controller' and ev['identity'].get('governed') is True
                                and ev['binding'] == [] and owned['available'] and owned['label'] is None
                                and owned['this_run']),
        'confinement_qualified': section['confinement']['status'] in ('qualified', 'no launches')
        and not any(o.get('status') == 'ok' and not o.get('tool_inventory') for o in ev['observations']),
        'custody_chain': ev['store_problems'] == [] and (summary.get('chain') or {}).get('verified') is True,
        'ledger_result_path': bool((ledger or {}).get('available')) and unmet == [] and not any(
            d.get('errors') for d in (decisions or {}).values()),
        'review_complete': not any(r['code'] in ('review_incomplete', 'review_evidence_boundary',
                                                 'review_credit_missing', 'figure_review_missing')
                                   for r in findings.refusals),
        'instructions_acknowledged': section['instructions']['acknowledgement'] == 'complete',
        'authority_recorded': bool(ev['authority'].get('mode') and auth.get('approve_plan') and auth.get('final')),
        'sink_rendered': bool(rendered),
        'accepted_delivery': delivered_label == 'accepted',
        'engagement_complete': bool(section['engagement'].get('available')
                                    and section['engagement'].get('architecture_complete_allowed') is True
                                    and usage_known),
    }


def build(ev, plan, classification, findings, *, ledger, unmet, decisions, label, delivery, extra_labels=(),
          rendered=False, qualified=False):
    """The receipt dictionary (without its digest); ``finalize`` adds ``sha256``."""
    section = {'host': host(ev, findings), 'work': work(ev, ledger, findings), 'costs': costs(ev),
               'ledger': ledger_section(ledger, unmet, decisions), 'authority': authority(ev),
               'authority_security': authority_security(ev), 'terminal_identity_attested': False,
               'instructions': instructions(ev), 'confinement': confinement(ev), 'review': review(findings),
               'judgments': judgments(ev, findings), 'engagement': engagement(ev)}
    shown = labels(findings, extra_labels)
    preds = predicates(ev, ledger, unmet, decisions, findings, section, label, rendered)
    complete = all(preds[name] for name in PREDICATES) and not qualified
    receipt = {'schema_version': common.RECEIPT_SCHEMA, 'kind': common.RECEIPT_KIND, 'run_id': ev['run_id'],
               'run': str(ev['run_dir']) if ev['run_dir'] is not None else None,
               'trust_basis': 'controller store evidence and the run bytes, recomputed by the sole sink',
               'trust_limit': common.CUSTODY_BOUNDARY,
               'plan': {'sha256': (plan or {}).get('sha256'), 'record_id': ev['plan']['record_id'],
                        'revision': ev['plan']['revision'], 'route': ((plan or {}).get('route') or {}).get('id')},
               'request': {'sha256': (ev['request'] or {}).get('sha256'), 'channel': (ev['request'] or {}).get('channel')},
               **section,
               'statistic': common.plain(getattr(findings, 'statistic', None)),
               'imports': common.plain(getattr(findings, 'imports', [])),
               'assumptions': common.plain(getattr(findings, 'assumptions', [])),
               'delivery': delivery, 'label': label, 'qualified': bool(qualified or label != 'accepted'),
               'labels': shown, 'notices': shown, 'label_details': _bounded(findings.labels, 300),
               'architecture_predicates': preds, 'architecture_complete': complete,
               'accepted': label == 'accepted' and not qualified}
    return common.plain(receipt)


def rederive(receipt, *, rendered):
    """Recompute ``architecture_complete`` from the predicates after the delivery was (or was not) rendered."""
    preds = dict(receipt['architecture_predicates'], sink_rendered=bool(rendered))
    complete = all(preds[name] for name in PREDICATES) and not receipt.get('qualified') and receipt['label'] == 'accepted'
    return dict(receipt, architecture_predicates=preds, architecture_complete=complete)


def finalize(receipt):
    receipt = {k: v for k, v in receipt.items() if k != 'sha256'}
    receipt['sha256'] = common.digest(receipt)
    return receipt


def verify_saved(receipt):
    """Integrity only: a matching digest never promotes a label (recompute the receipt for that)."""
    if type(receipt) is not dict or receipt.get('kind') != common.RECEIPT_KIND or \
            receipt.get('sha256') != common.digest({k: v for k, v in receipt.items() if k != 'sha256'}):
        raise ValueError('controller receipt changed or is absent')
    return receipt
