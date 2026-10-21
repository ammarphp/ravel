"""The sole sink's binding interface: ``deliver``, ``bounded_end`` and ``receipt``.

``deliver(store, plan)`` has the engagement envelope checked for this delivery, inventories the
run's bytes, evaluates every delivery obligation and the route packages' delivery checks,
materialises the ledger's ``deliver`` rows and records each with its evidence, takes the
``delivery`` and ``final_task`` decisions through the ledger, and gates ``deliver[accepted]``.
Only when the ledger, both decisions and every sink check pass does the delivery carry the
accepted label; otherwise it is delivered qualified or diagnostic, with every reason rendered.
``bounded_end(store, reason)`` writes a qualified delivery that states every obligation's status,
keeps every finding, renders every route's ending record, delivers the artifacts a route selected
for the ending only after verifying them again (labelled, never accepted), adopts no claim,
notifies the operator once and never raises.
``receipt(store)`` returns the latest receipt with a fresh check of the delivered bytes.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import unquote

from . import checks, common, evidence, inventory, receipts, render
from .common import QUALIFIED, records

DECISION_GATES = ('delivery', 'final_task')
DELIVERY_ROWS = ('GATE-delivery', 'GATE-final_task', 'GATE-report_integrity', 'GATE-export')
ARTIFACT_ROWS = ('C27', 'C33', 'D01', 'D02', 'D06', 'D08', 'E20', 'E25', 'E26')  # refusals about the bytes themselves
ENDING_CODES = (('grant expired', 'authority_expired'), ('revoked the grant', 'authority_revoked'),
                ('budget', 'budget_exhausted'), ('exhaust', 'budget_exhausted'), ('deadline', 'deadline'),
                ('stop', 'stopped'), ('drain', 'stopped'), ('revok', 'stopped'), ('escalat', 'escalation'),
                ('waiting', 'escalation'), ('review', 'review_incomplete'), ('obligation', 'obligations_unmet'),
                ('hold', 'hold'), ('fail', 'failure'))


# ---- ledger discharge -----------------------------------------------------------------------------

def _parse_key(key):
    row, _, rest = str(key).partition('@')
    scope = {}
    for part in rest.split('/')[1:]:
        name, sep, value = part.partition('=')
        if sep:
            scope[name] = unquote(value)
    return row, scope


def discharge(store, ev, plan, classification, findings, *, export=False):
    """Materialise and record the deliver rows, decide the delivery gates and gate ``deliver[accepted]``."""
    ledger = common.module('ledger')
    state = {'available': ledger is not None, 'keys': [], 'recorded': 0, 'pending': [], 'record_errors': [],
             'decisions': {}, 'unmet': None}
    if ledger is None:
        findings.refuse('diagnostic', code='ledger_absent', message='the obligation ledger is not installed')
        state['view'] = evidence.ledger_view(store)
        return state
    artifacts = [row['artifact'] for row in classification['declared']]
    claims = [c['id'] for c in getattr(findings, 'claims', None) or [] if type(c.get('id')) is str]
    try:
        state['keys'] = list(ledger.materialise(store, 'deliver', {'artifacts': artifacts, 'claims': claims}) or [])
    except Exception as exc:
        findings.refuse('diagnostic', code='ledger_materialise', message=f'{type(exc).__name__}: {exc}')
    changes = []
    listing, listing_error = ledger_listing(store)
    current = {row.get('key'): row.get('status') for row in listing or [] if type(row) is dict}
    try:
        ending_keys = list(ledger.pending(store, node='controller.bounded_end')) if hasattr(ledger, 'pending') else []
    except Exception:
        ending_keys = []
    for key in ending_keys:
        changes.append((key, 'not_applicable', {'reason': 'the run delivered through the sink without reaching a '
                                                          'bound; no bounded ending applies'}))
    for key in state['keys']:
        row, scope = _parse_key(key)
        found = findings.rows.get((row, scope.get('artifact')))
        if found is None:
            if current.get(key, 'pending') == 'pending':
                state['pending'].append(key)
            continue
        if current.get(key) == found['status']:
            continue  # a delivery resumed after its rows were recorded: nothing changes
        if listing_error is None and current.get(key) != 'pending' and found['status'] != 'violated':
            continue  # closed rows are never promoted; a new violation must still be recorded
        changes.append((key, found['status'], found['evidence']))
    many = getattr(ledger, 'record_many', None)
    try:
        if callable(many):
            many(store, changes)
        else:
            for change in changes:
                ledger.record(store, *change)
        state['recorded'] = len(changes)
    except Exception:
        # One refused change must not hide the others: record what the ledger accepts, report the rest.
        for change in changes:
            try:
                ledger.record(store, *change)
                state['recorded'] += 1
            except Exception as exc:
                state['record_errors'].append({'entry': change[0], 'status': change[1],
                                               'error': f'{type(exc).__name__}: {exc}'[:500]})
        for error in state['record_errors']:
            findings.refuse('diagnostic', code='ledger_record', message=f"{error['entry']}: {error['error']}")
    run_dir = ev['run_dir']
    action = {'plan_sha256': (plan or {}).get('sha256'), 'artifacts': [r['artifact'] for r in classification['declared']
                                                                        if r['status'] == 'accepted']}
    # Each decision names what the delivery answers the request with: every accepted output with its original
    # requirement ids, and every requirement the approved plan descopes (request fidelity verifies both).
    points = common.module('review_points')
    action.update(points.delivery_action(run_dir) if points is not None else {'outputs': [], 'descoped': []})
    occurrence = len(records(store, common.STORE_RECEIPT)) + 1
    gates = [(gate, {}) for gate in DECISION_GATES]
    gates.append(('report_integrity', {'event': f'report:{occurrence}'}))
    if export:
        gates.append(('export', {'event': f'export:results-file:{occurrence}'}))
    decide = getattr(ledger, 'decide', None)
    authority = common.module('authority')
    record_standing = getattr(authority, 'record_delivery_rows', None)
    if callable(record_standing):
        try:
            record_standing(store, action)
        except Exception as exc:
            findings.refuse('diagnostic', code='standing_rows_unverified',
                            message=f'{type(exc).__name__}: {exc}')
    final_action = getattr(authority, 'final_task_action', None)
    for gate, extra in gates:
        if not callable(decide):
            state['decisions'][gate] = {'errors': [{'code': 'decision_gate_absent', 'provider': 'sink',
                                                    'message': 'the ledger offers no decision gate'}]}
            continue
        try:
            # The final task is decided on the authority's retained exact action (its digest), carrying what the
            # delivery answers the request with, as at CHECK-IN 3.
            decided_action = (dict(final_action(store), outputs=action['outputs'], descoped=action['descoped'], **extra)
                              if gate in ('final_task', 'delivery', 'report_integrity') and callable(final_action)
                              else dict(action, gate=gate, **extra))
            errors = decide(store, run_dir, gate, decided_action) or []
            state['decisions'][gate] = {'errors': [_error_row(e) for e in errors], **extra}
        except Exception as exc:
            state['decisions'][gate] = {'errors': [{'code': 'decision_failed', 'provider': 'sink',
                                                    'message': f'{type(exc).__name__}: {exc}'[:1000]}], **extra}
    try:
        state['unmet'] = common.plain(ledger.gate(store, 'deliver[accepted]') or [])
    except Exception as exc:
        state['unmet'] = [{'entry': 'ledger', 'reason': 'gate_failed', 'consequence': 'diagnostic',
                           'message': f'{type(exc).__name__}: {exc}'[:1000]}]
    state['view'] = evidence.ledger_view(store)
    return state


def _error_row(error):
    """A decision-gate error as ``{code, provider, message}`` (a ``GateError``, a mapping or text).

    A ``detail`` the provider gave is kept in the message, after its own text.
    """
    if type(error) is dict:
        message = str(error.get('message') or error)
        if error.get('message') and error.get('detail'):
            message = f"{message} ({error['detail']})"
        return {'code': str(error.get('code') or 'refused'), 'provider': str(error.get('provider') or ''),
                'message': message[:1000]}
    if hasattr(error, 'code') and hasattr(error, 'message'):
        detail = getattr(error, 'detail', None)
        return {'code': str(error.code), 'provider': str(getattr(error, 'provider', '') or ''),
                'message': (str(error.message) + (f' ({detail})' if detail else ''))[:1000]}
    return {'code': 'refused', 'provider': '', 'message': str(error)[:1000]}


def _from_ledger(error):
    """A decision refused only because the ledger shows unmet obligations (its rows are reported themselves)."""
    return error['provider'] == 'ledger' and error['code'].startswith('ledger_') or error['code'] == 'obligation_unmet'


def decide_label(findings, state):
    """``accepted`` only when every gate and check passes; else ``qualified`` or ``diagnostic`` by consequence.

    A delivery is ``qualified`` only when everything that withholds acceptance could be waived by
    the physicist or the operator; anything nobody may waive (custody, confinement, review credit,
    the sink's own refusals, a decision-gate provider refusal or a ledger fault) makes it
    ``diagnostic``. A decision row left pending because its decision refused over the other unmet
    rows does not decide the label by itself.
    """
    if not state['available'] or state['unmet'] is None:
        return 'diagnostic'
    errors = [e for d in state['decisions'].values() for e in d['errors']]
    unmet = state['unmet']
    if not findings.refusals and not unmet and not errors:
        return 'accepted'
    if any(r['consequence'] != 'qualified' for r in findings.refusals):
        return 'diagnostic'
    if any(not _from_ledger(e) for e in errors):
        return 'diagnostic'
    if errors and not unmet:
        return 'diagnostic'  # a decision names unmet obligations the ledger gate does not show: a ledger fault
    rest = [u for u in unmet if (u or {}).get('id') not in DELIVERY_ROWS]
    if any((u or {}).get('consequence') != 'qualified' for u in rest):
        return 'diagnostic'
    if not rest and len(rest) != len(unmet) and not findings.refusals:
        return 'diagnostic'  # a decision row is pending with nothing else unmet: the decision itself failed
    return 'qualified'


# ---- claims and review findings ---------------------------------------------------------------------

def _load(path):
    try:
        if Path(path).stat().st_size > common.TEXT_LIMIT:
            return None
        return json.loads(Path(path).read_bytes())
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def review_findings(ev):
    """Items of the final review seats' adopted findings documents (latest attempt of each)."""
    rows, latest = [], {}
    for artifact, record in ev['custody'].items():
        if record.get('step_id') != checks.FINAL or record.get('status') != 'accepted':
            continue
        latest[artifact] = record
    run_dir = ev['run_dir']
    for artifact, record in sorted(latest.items()):
        document = _load(Path(run_dir) / record['destination']) if type(record.get('destination')) is str else None
        if type(document) is not dict:
            continue
        verdicts = {v.get('item'): v.get('verdict') for v in document.get('item_verdicts') or ()
                    if type(v) is dict}
        for item in document.get('items') or ():
            if type(item) is dict:
                rows.append({'seat': artifact, 'id': item.get('id'), 'severity': item.get('severity'),
                             'verdict': verdicts.get(item.get('id')),
                             'text': str(item.get('summary') or item.get('text') or item.get('finding') or '')[:300],
                             'classification': item.get('classification'), 'item': item})
    return rows


def unresolved_findings(ev, classification, findings):
    """Retain review items and open defects in adopted documents with their original scope."""
    rows = [{k: r.get(k) for k in ('seat', 'id', 'severity', 'verdict', 'text')}
            for r in findings.review_findings]
    for row in classification['declared']:
        if row['status'] != 'accepted' or not row['destination'].lower().endswith('.json'):
            continue
        path = Path(ev['run_dir']) / row['destination']
        try:
            if common.sha256_file(path) != row['sha256']:
                continue  # changed bytes are never new findings evidence
            document = _load(path)
        except (OSError, ValueError):
            continue
        for item in checks._objects(document):
            declared = item.get('classification') if type(item.get('classification')) is dict else {}
            kind = item.get('kind') if type(item.get('kind')) is str else declared.get('kind')
            status = str(item.get('status') or item.get('disposition') or '').lower()
            if kind == 'defect' and (not status or status in checks.OPEN_DEFECT):
                rows.append({'artifact': row['artifact'], 'id': item.get('id'), 'severity': item.get('severity'),
                             'verdict': status or 'unresolved',
                             'text': str(item.get('summary') or item.get('text') or item.get('finding') or
                                         item.get('id') or 'unresolved defect'), 'item': common.plain(item)})
    return rows


def claims(ev, classification, findings, *, ending=False):
    """Validate a delivered claim-disposition package (judgment-protocols claim packages); render its rows."""
    validator = common.module('claims')
    items = [r['item'] for r in getattr(findings, 'review_findings', []) or []]
    limited = [i for i in items if type(i.get('classification')) is dict and i['classification'].get('kind') == 'limitation']
    package, where = None, None
    for row in classification['declared']:
        if row['status'] != 'accepted' or not row['destination'].lower().endswith('.json'):
            continue
        document = _load(Path(ev['run_dir']) / row['destination'])
        if type(document) is dict and {'plan', 'rows', 'value', 'evidence'} <= set(document):
            package, where = document, row['artifact']
            break
    if package is None:
        if limited and not ending:
            findings.refuse('qualified', code='claims_package_missing',
                            message='the final review retains limitations but no claim-disposition package is delivered')
        return []
    rows = package.get('rows') if type(package.get('rows')) is list else []
    shown = [{'id': r.get('planned_claim_id'), 'disposition': r.get('disposition') if not ending else
              f"not adopted (qualified ending; planned disposition {r.get('disposition')})",
              'reason': r.get('reason')} for r in rows if type(r) is dict]
    if ending:
        return shown
    try:
        value = package['value'] if type(package['value']) is dict else {}
        figures = {f['id']: f for f in value.get('figures') or () if type(f) is dict and 'id' in f
                   and type(f.get('evidence_ids')) is list}
        if validator is None:
            raise ValueError('the claim-disposition contract is not installed')
        validator.validate(package['plan'], rows, value, package['evidence'], final=True, figures=figures,
                           review_findings=items)
    except Exception as exc:
        findings.refuse('qualified', code='claims_invalid', artifact=where,
                        message=f'the claim-disposition package does not validate: {exc}')
    return shown


# ---- receipts in the store ----------------------------------------------------------------------------

def _record(store, final, *, kind, reason=None, results=None, notification=None):
    blob = store.put_blob(render._json_bytes(final))
    compact = {'kind': kind, 'label': final['label'], 'qualified': final['qualified'], 'accepted': final['accepted'],
               'labels': final['labels'], 'architecture_complete': final['architecture_complete'],
               'receipt_sha256': final['sha256'], 'receipt_blob': blob,
               'delivery_dir': (final.get('delivery') or {}).get('directory'),
               'inventory_sha256': (final.get('delivery') or {}).get('inventory_sha256'),
               'artifacts': [{k: f.get(k) for k in ('artifact', 'path', 'sha256')}
                             for f in ((final.get('delivery') or {}).get('artifacts') or [])][:200],
               'reason': reason, 'results_file': results, 'notification': notification,
               'plan_sha256': (final.get('plan') or {}).get('sha256')}
    return store.append(common.STORE_RECEIPT, common.plain(compact))


def _rounding(plan):
    value = ((plan or {}).get('parameters') or {}).get('rounding')
    relative = value.get('relative') if type(value) is dict else None
    return float(relative) if type(relative) in (int, float) and 0 <= relative < 1 else None


def _assess(store, plan, *, ending=False):
    ev = evidence.gather(store, plan)
    ev['store'] = store
    run_dir = ev['run_dir']
    if run_dir is None or not Path(run_dir).is_dir() or Path(run_dir).is_symlink():
        raise common.SinkRefused('the store names no run directory, or it is missing or replaced by a link')
    plan_doc = ev['plan']['plan']
    walked = inventory.walk(run_dir)
    hashes = inventory.Hashes(run_dir)
    classification = inventory.classify(ev, plan_doc, walked, hashes)
    findings = checks.evaluate(store, ev, plan_doc, classification, hashes, relative_rounding=_rounding(plan_doc))
    findings.review_findings = review_findings(ev)
    findings.claims = claims(ev, classification, findings, ending=ending)
    from ravel.controller import result_import
    findings.imports = result_import.delivery_labels(store, plan_doc, classification, findings)
    from . import procedure
    try:
        findings.procedure = procedure.prepare_delivery(store, plan_doc, run_dir)
    except Exception as exc:
        findings.procedure = None
        findings.refuse('diagnostic', code='manuscript_procedure_invalid',
                        message=f'the procedure requires current assembly and source custody: {type(exc).__name__}: {exc}')
    try:
        from ravel.controller.assumptions import recorded
        findings.assumptions = recorded(store, plan_doc)
    except Exception as exc:
        findings.assumptions = []
        findings.refuse('diagnostic', code='assumptions_unreadable',
                        message=f'the complete recorded assumption census requires repair: {type(exc).__name__}: {exc}')
    try:
        condition_labels(store, plan_doc, classification, findings)
    except Exception as exc:  # an unreadable condition is named, never dropped silently
        findings.refuse('qualified', code='conditions_unreadable',
                        message=f'the run\'s machine assumptions could not be read: {type(exc).__name__}: {exc}')
    return ev, plan_doc, walked, classification, findings, hashes


CONDITIONAL = 'CONDITIONAL RESULT'
ALTERNATIVE = 'ALTERNATIVE INTERPRETATION'


ASSUMPTION_KIND = 'assumption'  # the controller's store kind of machine assumption events (``controller.graph``)


def conditions(store):
    """The run's conditions, read from the controller's ``assumption`` records: each physics-critical machine
    assumption proposed for a question (with its alternative branch, or why none ran) and each CHECK-IN 1 approval
    given conditional on facts the intake inferred (``step`` None: every result is conditional on it)."""
    rows = [(r.get('id'), r['record']) for r in store.scan(ASSUMPTION_KIND)]
    found = []
    for identifier, record in rows:
        if record.get('phase') == 'conditional_approval':
            found.append({'record': identifier, 'step': None, 'option': None, 'taken': True, 'alternative': None,
                          'statement': ' '.join(a['statement'] for a in record.get('assumptions') or ())})
            continue
        if record.get('phase') != 'proposed' or not record.get('conditional'):
            continue
        branch = [r for _, r in rows if r.get('phase') in ('alternative', 'alternative_skipped')
                  and r.get('record') == identifier]
        taken = [r for _, r in rows if r.get('phase') == 'taken' and r.get('record') == identifier]
        found.append({'record': identifier, 'step': record.get('step'), 'option': record.get('option'),
                      'statement': (record.get('assumptions') or [{}])[0].get('statement'), 'taken': bool(taken),
                      'alternative': deepcopy(branch[-1]) if branch else None})
    return found


def condition_labels(store, plan_doc, classification, findings):
    """Label the receipt and every affected deliverable with each physics-critical machine assumption the run's
    results are conditional on, and the deliverables of its alternative branch as the alternative interpretation
    (``controller.graph.conditions``). A deliverable is affected when its producing step depends on the question's
    step; nothing here changes whether the delivery is accepted."""
    for row in records(store, 'research-subgraph'):
        result = row.get('result') or {}
        qualification = result.get('qualification') or {}
        if row.get('status') == 'completed' and qualification.get('kind') == 'bounded_sub_question':
            from ravel.workflow.bounded_research import LABEL
            findings.label(LABEL, text='Step ' + row['step_id'] +
                           ' retains unfinished scientific duties: ' +
                           ', '.join(qualification.get('pending_protocol_stages') or []))
    rows = conditions(store)
    if not rows:
        return []
    depends = {s['id']: set(s.get('depends_on') or ()) for s in (plan_doc or {}).get('steps') or () if 'id' in s}

    def downstream(root):
        found, changed = {root}, True
        while changed:
            changed = False
            for name, parents in depends.items():
                if name not in found and parents & found:
                    found.add(name)
                    changed = True
        return found
    for condition in rows:
        alternative = condition.get('alternative') or {}
        branch = set(alternative.get('added_steps') or ()) if alternative.get('phase') == 'alternative' else set()
        # A conditional plan approval (no question step) conditions every result of the run.
        affected = set(depends) if condition['step'] is None else downstream(condition['step'])
        findings.label(CONDITIONAL, text=condition.get('statement'))
        if branch:
            findings.label(ALTERNATIVE, text=f"the alternative option {alternative.get('alternative_option')} of the "
                                             f"question of step {condition['step']} was also run (steps "
                                             f"{', '.join(sorted(branch))}); both results are reported")
        elif alternative:
            findings.label(ALTERNATIVE, text=f"the alternative interpretation was not run: {alternative.get('reason')}")
        declared = {row.get('artifact') for row in classification.get('declared') or ()}
        for record in store.scan('custody') if branch else ():
            body = record['record']
            if body.get('step_id') in branch and body.get('status') == 'accepted' and body.get('artifact') not in declared:
                # The alternative interpretation's own result, reported beside the deliverable (never accepted as it).
                findings.label(ALTERNATIVE, artifact=body.get('artifact'),
                               text=f"result under option {alternative.get('alternative_option')} of the question of "
                                    f"step {condition['step']}; reported beside the deliverable, not accepted as it")
        for row in classification.get('declared') or ():
            if row.get('step') in branch:
                findings.label(ALTERNATIVE, artifact=row['artifact'],
                               text=f"derived under option {alternative.get('alternative_option')} of the question "
                                    f"of step {condition['step']}")
            elif row.get('step') in affected:
                findings.label(CONDITIONAL, artifact=row['artifact'],
                               text=(f"conditional on the machine assumption of step {condition['step']} "
                                     f"(option {condition['option']}, record {condition['record']})")
                               if condition['step'] is not None else
                               f"conditional on facts the intake inferred (record {condition['record']})")
    return rows


def _results_target(ev, results_file):
    targets = [common.body(t) for t in ev['targets']]
    named = targets[-1] if targets else None
    if results_file is not None and named is not None and results_file != named:
        raise common.SinkRefused('the results file named by the caller differs from the one pinned at intake')
    return results_file or named


def _harness_problem(store, ev):
    """For a harness run, why its results may not be written: the bound session must still hold.

    The results come only from this accepted receipt; the harness session the entry bound (its
    executable, model, effort and retained record) must be present and unchanged. None otherwise.
    """
    if (ev.get('request') or {}).get('channel') != 'harness':
        return None
    rows = store.scan('harness-session') if hasattr(store, 'scan') else []
    if len(rows) != 1:
        return 'a harness run needs exactly one bound harness session record'
    from ..entry import verify_harness_binding
    record = rows[0].get('record') if type(rows[0]) is dict and 'record' in rows[0] else rows[0]
    return verify_harness_binding(record)


def _write_results(store, ev, classification, final, target):
    """Fill the trusted-side results file from the accepted deliverable it names (accepted deliveries only)."""
    spec = target if type(target) is dict else {'path': target}
    wanted = spec.get('deliverable')
    rows = [r for r in classification['declared'] if r['status'] == 'accepted'
            and (wanted is None or wanted in r['deliverables'])]
    if len(rows) != 1:
        return {'status': 'refused', 'reason': 'the results file needs exactly one accepted deliverable'
                + (f' named {wanted!r}' if wanted else '') + f' ({len(rows)} found)'}
    try:
        written = render.write_results_file(spec.get('path'), Path(ev['run_dir']) / rows[0]['destination'],
                                            run_dir=ev['run_dir'], store_root=getattr(store, 'store_root', None),
                                            expected_sha256=rows[0]['sha256'])
    except (OSError, ValueError) as exc:
        return {'status': 'failed', 'reason': str(exc)[:500]}
    return {**written, 'deliverable': rows[0]['deliverables'], 'artifact': rows[0]['artifact']}


def deliver(store, plan, *, results_file=None):
    """The ``deliver`` node: an accepted delivery when every gate and check passes, else qualified or diagnostic.

    ``results_file`` is a trusted-side output (a path, or ``{"path", "deliverable"}``) the caller's
    trusted side names, such as a harness results template; a ``delivery-target`` record pinned at
    intake names it too. It is filled only for an accepted delivery, after the ``export`` decision.
    """
    run_dir = common.run_dir(store)
    if run_dir is None or not Path(run_dir).is_dir() or Path(run_dir).is_symlink():
        return _undeliverable(store, 'the run directory bound to this store is missing')
    target = None
    # The engagement envelope is checked for this delivery before anything reads it (the receipt
    # section and the ledger's deliver[accepted] gate take the latest delivery-stage check).
    engagement_error = evidence.engagement_check(store)
    ev, plan_doc, walked, classification, findings, _ = _assess(store, plan)
    if engagement_error:
        findings.refuse('diagnostic', code='engagement_check', message=engagement_error)
    try:
        target = _results_target(ev, results_file)
    except common.SinkRefused as exc:
        findings.refuse('diagnostic', code='results_target', message=str(exc))
    state = discharge(store, ev, plan_doc, classification, findings, export=target is not None)
    checks.ledger_chain(findings, state['view'])
    checks.ledger_labels(findings, state['view'])
    label = decide_label(findings, state)
    extra = {'accepted': [], 'qualified': [common.QUALIFIED_DELIVERY], 'diagnostic': [common.DIAGNOSTIC]}[label]
    delivery = {'status': 'delivered', 'declared': len(classification['declared']),
                'delivered': sum(1 for r in classification['declared'] if r['status'] == 'accepted'),
                'holes': [r['deliverable'] for r in classification['open']],
                'excluded_count': classification['excluded_count'],
                'results_file': None if target is None else {'status': 'pending'}}
    built = receipts.build(ev, plan_doc, classification, findings, ledger=state['view'], unmet=state['unmet'],
                           decisions=state['decisions'], label=label, delivery=delivery, extra_labels=extra)
    final = render.write(run_dir, built, classification, findings, inventory=_walk_summary(walked))
    results = None
    if target is not None:
        export_errors = (state['decisions'].get('export') or {}).get('errors')
        if label != 'accepted':
            results = {'status': 'untouched', 'reason': f'the delivery is {label}; the results file is filled only '
                                                        'for an accepted delivery'}
        elif export_errors:
            results = {'status': 'refused', 'reason': 'the export decision refused: '
                       + '; '.join(e['message'] for e in export_errors)[:500]}
        elif _harness_problem(store, ev):
            results = {'status': 'refused', 'reason': _harness_problem(store, ev)}
        else:
            results = _write_results(store, ev, classification, final, target)
        final = render.rewrite_receipt(run_dir, dict(final, delivery=dict(final['delivery'], results_file=results)),
                                       classification, findings)
    record_id = _record(store, final, kind='delivery', results=results)
    return {**final, 'id': record_id}


def _walk_summary(walked):
    return {'counts': walked['counts'], 'files': len(walked['files'])}


def _undeliverable(store, reason):
    record = {'kind': 'delivery', 'label': 'diagnostic', 'qualified': True, 'accepted': False,
              'labels': [common.DIAGNOSTIC, f'NOT DELIVERED: {reason}'], 'architecture_complete': False,
              'reason': reason, 'delivered': False}
    record['id'] = store.append(common.STORE_RECEIPT, record)
    return record


# ---- the bounded ending ------------------------------------------------------------------------------

def ending_code(reason):
    text = str(reason or '').lower()
    for needle, code in ENDING_CODES:
        if needle in text:
            return code
    return 'other'


def obligation_states(ev, plan, classification, findings, ledger):
    """Each original obligation as satisfied, negative, partial or blocked (task-completion semantics)."""
    rows = []
    summary = (ledger or {}).get('summary') or {}
    expected = list((summary.get('deliverables') or {}).get('expected') or [])
    reading = ev['intake'].get('reading') or {}
    for item in reading.get('deliverables') or ():
        if type(item) is dict and type(item.get('id')) is str and item['id'] not in expected:
            expected.append(item['id'])
    declared = {d: row for row in classification['declared'] for d in row['deliverables']}
    opened = {row['deliverable']: row for row in classification['open']}
    refused = {r['artifact'] for r in findings.refusals if r.get('artifact') and r.get('row') in ARTIFACT_ROWS}
    for deliverable in expected or list(declared) + list(opened):
        row = declared.get(deliverable)
        if row is None:
            reason = (opened.get(deliverable) or {}).get('reason') or 'no plan step produces it'
            rows.append({'id': deliverable, 'state': 'blocked', 'reason': reason})
            continue
        if row['status'] == 'accepted':
            document = _load(Path(ev['run_dir']) / row['destination']) if row['destination'].endswith('.json') else None
            negative = type(document) is dict and str(document.get('outcome') or document.get('result_status')) == 'negative'
            state = 'negative' if negative else 'satisfied'
            reason = 'accepted contribution only; no new acceptance by this ending'
            if row['artifact'] in refused:
                state, reason = 'partial', 'delivered with sink refusals: ' + '; '.join(
                    r['message'] for r in findings.refusals if r.get('artifact') == row['artifact']
                    and r.get('row') in ARTIFACT_ROWS)[:500]
            rows.append({'id': deliverable, 'state': state, 'reason': reason, 'artifact': row['artifact']})
            continue
        outcome = ev['outcomes'].get(row['step']) or {}
        partial = row['status'] in ('step_not_completed', 'lineage', 'diagnostic_promotion', 'changed') and \
            row.get('custody') is not None
        rows.append({'id': deliverable, 'state': 'partial' if partial else 'blocked',
                     'reason': '; '.join(row['reasons']) or f"step {row['step']} {outcome.get('status') or 'not run'}"
                     + (f" ({outcome.get('reason')})" if outcome.get('reason') else ''), 'artifact': row['artifact']})
    return rows


def ledger_listing(store):
    """Public pending entries and disclosed exceptions; complete status counts stay in the summary.

    The public API does not enumerate satisfied identities. Never infer them from counts or
    import the ledger's private folded state. A bounded ending retains the full status census.
    """
    ledger = common.module('ledger')
    if ledger is None:
        return None, 'the obligation ledger is not installed'
    try:
        summary = ledger.summary(store)
        rows = [{'id': _parse_key(key)[0], 'key': key, 'status': 'pending', 'scope': _parse_key(key)[1]}
                for key in ledger.pending(store)]
        for field, status in (('violations', 'violated'), ('waivers', 'waived'),
                              ('not_applicable', 'not_applicable')):
            for row in summary.get(field) or []:
                if row.get('superseded') is True:
                    continue
                key = row.get('entry')
                rows.append({**common.plain(row), 'key': key, 'status': status,
                             'scope': _parse_key(key)[1]})
        return rows, None
    except Exception as exc:
        return None, f'{type(exc).__name__}: {exc}'


def _record_ending_rows(store, ending_id):
    """Discharge the bounded-ending rows (B03, JR10) with the qualified-ending record as evidence."""
    ledger = common.module('ledger')
    if ledger is None or not hasattr(ledger, 'pending'):
        return []
    errors = []
    try:
        keys = ledger.pending(store, node='controller.bounded_end')
    except Exception as exc:
        return [f'{type(exc).__name__}: {exc}']
    for key in keys:
        try:
            ledger.record(store, key, 'satisfied', {'record': ending_id, 'mechanism': 'sink.bounded_end'})
        except Exception as exc:
            errors.append(f'{key}: {type(exc).__name__}: {exc}'[:500])
    return errors


def bounded_end(store, reason):
    """A qualified delivery stating every obligation's status; it never raises and never adopts a claim."""
    reason = str(reason or 'bounded ending')[:2000]
    try:
        return _bounded_end(store, reason)
    except Exception as exc:  # the ending is always reachable: fall back to a minimal record
        try:
            record = {'kind': 'qualified-ending', 'label': 'qualified', 'qualified': True, 'accepted': False,
                      'labels': [QUALIFIED, 'NOT DELIVERED: the qualified delivery could not be written'],
                      'architecture_complete': False, 'reason': reason, 'delivered': False,
                      'error': f'{type(exc).__name__}: {exc}'[:2000]}
            record['id'] = store.append(common.STORE_RECEIPT, record)
            return record
        except Exception as inner:
            return {'id': None, 'kind': 'qualified-ending', 'label': 'qualified', 'qualified': True, 'accepted': False,
                    'labels': [QUALIFIED, 'NOT RECORDED: the controller store refused the ending'],
                    'architecture_complete': False, 'reason': reason,
                    'error': f'{type(exc).__name__}: {exc}; {type(inner).__name__}: {inner}'[:2000]}


def _recovery_gaps(store):
    try:
        from ravel.controller import recovery
        return common.plain(recovery.gaps(store))
    except Exception as exc:  # the ending is always written; an unreadable record is named
        return [{'error': f'{type(exc).__name__}: {exc}'[:500]}]


def qualified_artifacts(store, ev, plan, walked, hashes, classification, findings):
    """Artifacts a route's ending selected for this qualified delivery, verified again: ``(delivered, refused)``.

    The latest qualifying ending record of a route names them. The route's own selection is
    computed again and must name the same set, and each artifact must pass the sink's custody,
    byte, lineage and promotion checks; otherwise it is listed with its reasons and not delivered.
    A delivered one is never an accepted result: it carries ``QUALIFIED ARTIFACT`` with the route's
    qualification in every notice.
    """
    delivered, refused = [], []
    declared = {row['artifact'] for row in classification['declared']}
    for kind, interface in common.QUALIFYING_ENDINGS:
        endings = [e for e in ev['endings'] if e['kind'] == kind and type(e.get('result')) is dict]
        if not endings:
            continue
        latest = endings[-1]
        named = latest['result'].get('artifacts')
        named = [a for a in named if type(a) is str] if type(named) is list else []
        if latest['result'].get('qualified') is not True or not named:
            continue
        qualification = str(latest['result'].get('qualification') or 'qualified')[:200]
        source = latest['source'] or kind
        problem = None
        module = common.module(interface)
        select = getattr(module, 'qualified_artifacts', None) if module is not None else None
        if not callable(select):
            problem = f'the {source} route cannot select its qualified artifacts again: it is not installed'
        else:
            try:
                again = sorted({str(r.get('artifact')) for r in select(store, plan, ev['run_dir']) or ()
                                if type(r) is dict})
                if again != sorted(set(named)):
                    problem = f'the {source} route now selects {again}, not the {sorted(set(named))} its ending recorded'
            except Exception as exc:  # a failing selection delivers nothing
                problem = f'the {source} route could not select its qualified artifacts: {type(exc).__name__}: {exc}'
        for row in inventory.qualified(ev, named, walked, hashes):
            if row['artifact'] in declared:
                continue  # a declared deliverable is delivered, or refused, as such
            row.update(source=source, qualification=qualification, ending_record=latest['record'])
            if problem:
                row.update(status='unverified', reasons=[problem] + row['reasons'])
            if row['status'] == 'accepted':
                findings.label(f'{common.QUALIFIED_ARTIFACT}: {qualification}', artifact=row['artifact'],
                               text=f'selected by the {source} route for a qualified ending; not an accepted result')
                delivered.append(row)
            else:
                refused.append(row)
    return delivered, refused


def _qualified_rows(rows):
    return [{k: row.get(k) for k in ('artifact', 'step', 'output', 'sha256', 'status', 'reasons', 'source',
                                     'qualification', 'ending_record')} for row in rows]


def _bounded_end(store, reason):
    run_dir = common.run_dir(store)
    if run_dir is None or not Path(run_dir).is_dir() or Path(run_dir).is_symlink():
        raise common.SinkRefused('the run directory bound to this store is missing')
    engagement_error = evidence.engagement_check(store)
    ev, plan_doc, walked, classification, findings, hashes = _assess(store, None, ending=True)
    if engagement_error:
        findings.label('ENGAGEMENT CHECK FAILED', text=engagement_error)
    delivered, unverified = qualified_artifacts(store, ev, plan_doc, walked, hashes, classification, findings)
    shown = {row['artifact'] for row in delivered}
    classification['extras'] = [row for row in classification['extras'] if row.get('artifact') not in shown]
    classification['qualified'] = _qualified_rows(delivered + unverified)
    ledger = evidence.ledger_view(store)
    module = common.module('ledger')
    integrity = None
    if module is not None:
        try:
            integrity = common.plain(module.gate(store, 'bounded_end->deliver') or [])
        except Exception as exc:
            integrity = [{'reason': 'gate_failed', 'message': f'{type(exc).__name__}: {exc}'[:500]}]
    if integrity:
        findings.label('LEDGER INTEGRITY FAULT', text='; '.join(str(i.get('message') or i) for i in integrity[:5]))
    code = ending_code(reason)
    ending = {'schema_version': 1, 'kind': 'qualified-task-delivery', 'reason': reason, 'code': code,
              'obligations': obligation_states(ev, plan_doc, classification, findings, ledger),
              'ledger_obligations': None, 'ledger_listing_error': None,
              'ledger_counts': ((ledger.get('summary') or {}).get('by_status')),
              'unresolved_findings': unresolved_findings(ev, classification, findings),
              'claims': getattr(findings, 'claims', []), 'scientific_claims_adopted': [],
              'syntheses': [{k: s.get(k) for k in ('kind', 'source', 'record', 'result')} for s in ev['endings']],
              'qualified_artifacts': classification['qualified'],
              'stop_state': ev['authority'].get('stop'),
              # Every step the run could not recover: its reason, the alternatives considered and why it stopped.
              'recovery': _recovery_gaps(store),
              'pending_requests': ev['authority'].get('requests'),
              'parent_task_accepted': False, 'execution_authorized': False}
    ending_id = store.append(common.STORE_ENDING, common.plain({k: v for k, v in ending.items()
                                                                if k not in ('ledger_obligations',)}))
    row_errors = _record_ending_rows(store, ending_id)
    if row_errors:
        findings.label('LEDGER RECORD REFUSED', text='; '.join(row_errors[:5]))
    # Every obligation's status, read after the ending's own rows were discharged.
    ending['ledger_obligations'], ending['ledger_listing_error'] = ledger_listing(store)
    ledger = evidence.ledger_view(store)
    ending['ledger_counts'] = (ledger.get('summary') or {}).get('by_status')
    checks.ledger_chain(findings, ledger)
    checks.ledger_labels(findings, ledger)
    delivery = {'status': 'qualified ending', 'declared': len(classification['declared']),
                'delivered': sum(1 for r in classification['declared'] if r['status'] == 'accepted'),
                'holes': [r['deliverable'] for r in classification['open']],
                'excluded_count': classification['excluded_count'], 'ending_record': ending_id,
                'qualified_artifacts': len(delivered), 'qualified_artifacts_refused': len(unverified),
                'results_file': {'status': 'untouched', 'reason': 'a qualified ending never fills the results file'}}
    built = receipts.build(ev, plan_doc, classification, findings, ledger=ledger, unmet=None, decisions={},
                           label='qualified', delivery=delivery, extra_labels=[QUALIFIED], qualified=True)
    final = render.write(run_dir, built, classification, findings, ending=ending, inventory=_walk_summary(walked),
                         qualified=delivered)
    previous = [r for r in records(store, common.STORE_RECEIPT) if r.get('kind') == 'qualified-ending'
                and (r.get('notification') or {}).get('status') == 'sent']
    notification = {'status': 'already sent'} if previous else _notify(store, code)
    final = render.rewrite_receipt(run_dir, dict(final, notification=notification), classification, findings, ending)
    record_id = _record(store, final, kind='qualified-ending', reason=reason, notification=notification)
    return {**final, 'id': record_id}


def _notify(store, code):
    """One line to the operator's notifier: the run and a state code, never the reason text."""
    authority = common.module('authority')
    notify = getattr(authority, 'notify', None) if authority is not None else None
    if not callable(notify):
        return {'status': 'unavailable'}
    try:
        return common.plain(notify(store, f'{QUALIFIED} {code}'))
    except Exception as exc:
        return {'status': 'failed', 'error': type(exc).__name__}


# ---- the receipt ----------------------------------------------------------------------------------

def receipt(store):
    """The latest receipt, with a fresh check that the delivered bytes and the store are unchanged.

    A saved receipt is a report, never a credential: when the delivery changed after the receipt
    was written, or the store chain no longer verifies, the returned view is neither accepted nor
    architecture-complete and carries the reason. Before any delivery, a fresh observation of
    the run (with no ledger writes) is returned.
    """
    rows = records(store, common.STORE_RECEIPT)
    if not rows:
        return observe_store(store)
    latest = rows[-1]
    if type(latest.get('receipt_blob')) is not str:
        # The last ending could not be written in full: report exactly what was recorded.
        return dict(common.body(latest), id=latest.get('_id'),
                    verification={'delivery_intact': False, 'problems': ['no complete receipt was written']})
    saved = receipts.verify_saved(json.loads(store.get_blob(latest['receipt_blob']).decode('utf-8')))
    if saved.get('sha256') != latest.get('receipt_sha256'):
        raise ValueError('the stored receipt blob does not match its record')
    run_dir = common.run_dir(store)
    problems = [] if run_dir is not None else ['the run directory bound to this store is unknown']
    for item in ((saved.get('delivery') or {}).get('artifacts') or ()) if run_dir is not None else ():
        path = Path(run_dir) / common.DELIVERY_DIR / item['path']
        try:
            if path.is_symlink() or common.sha256_file(path) != item['sha256']:
                problems.append(f"{item['path']} changed after the receipt")
        except OSError:
            problems.append(f"{item['path']} is missing")
        sidecar = item.get('provenance_sidecar')
        if sidecar:
            sidepath = Path(run_dir) / common.DELIVERY_DIR / sidecar['path']
            try:
                if (sidepath.is_symlink() or not common.inside(Path(run_dir) / common.DELIVERY_DIR, sidepath)
                        or sidepath.stat().st_size != sidecar['size']
                        or common.sha256_file(sidepath) != sidecar['sha256']):
                    problems.append(f"{sidecar['path']} provenance changed after the receipt")
            except OSError:
                problems.append(f"{sidecar['path']} provenance is missing")
    verify = getattr(store, 'verify', None)
    chain = list(verify()) if callable(verify) else ['the store offers no verification']
    problems.extend(chain)
    view = deepcopy(saved)
    view['id'] = latest.get('_id')
    view['verification'] = {'delivery_intact': not problems, 'problems': problems[:50]}
    if problems:
        view.update(accepted=False, architecture_complete=False,
                    labels=list(view.get('labels') or []) + ['DELIVERY CHANGED AFTER RECEIPT'])
        view['notices'] = view['labels']
    return view


PRESENTATION_TRACE = 'presentation-trace'


def trace_presentation(store, plan):
    """Tier A tracing of the final presentation before acceptance, read only (nothing is delivered or recorded in the
    ledger): the sink's own number and lineage checks (D01, E20) over every accepted deliverable artifact of ``plan``.
    Returns ``{'record', 'passed', 'artifacts'}``; the result is kept as a ``presentation-trace`` record. A plan with
    no accepted deliverable has no presentation, which never passes."""
    _, plan_doc, _, classification, findings, _ = _assess(store, plan)
    rows = [dict(row) for (name, _), row in sorted(findings.rows.items(), key=lambda kv: (kv[0][0], str(kv[0][1])))
            if name in ('D01', 'E20') and row.get('artifact')]
    delivered = sorted(r['artifact'] for r in classification['declared'] if r['status'] == 'accepted')
    untraced = [r for r in rows if r['status'] == 'violated']
    passed = bool(delivered) and not untraced
    record = {'schema_version': 1, 'plan_sha256': (plan_doc or {}).get('sha256'), 'artifacts': delivered,
              'rows': rows, 'passed': passed}
    return {'record': store.append(PRESENTATION_TRACE, record), 'passed': passed, 'artifacts': delivered}


def observe_store(store, plan=None):
    """A fresh receipt of the run as it stands, without ledger writes or delivery (nothing delivered yet)."""
    ev, plan_doc, walked, classification, findings, _ = _assess(store, plan)
    ledger = evidence.ledger_view(store)
    checks.ledger_labels(findings, ledger)
    delivery = {'status': 'not delivered', 'declared': len(classification['declared']),
                'deliverable': sum(1 for r in classification['declared'] if r['status'] == 'accepted')}
    built = receipts.build(ev, plan_doc, classification, findings, ledger=ledger, unmet=None, decisions={},
                           label='diagnostic', delivery=delivery, extra_labels=['NOT DELIVERED'])
    return receipts.finalize(built)


def observe(run_dir):
    """The controller receipt of a controller-owned run directory (read-only)."""
    store_module = common.module('store')
    if store_module is None or not hasattr(store_module, 'store_for'):
        raise common.SinkRefused('the controller store is not installed; the run cannot be observed')
    return receipt(store_module.store_for(Path(run_dir)))
