"""CHECK-IN 1 of a judgment-route plan: the route's part of the view and the content rows it discharges.

The controller asks the plan's route for its part of a typed check-in view (the adapter function
``checkin(kind, context)``; ``context`` holds the store, run directory, plan, state, reading and
contract). For a judgment-route plan the CHECK-IN 1 view adds a required ``bounds`` section (the
plan's highest rung, its stages and its summed step budgets: the cost an approval covers) and every
numbered assumption of the accepted question frame as a numbered flag with its basis.

Once the CHECK-IN 1 plan review is credited, the content rows of node ``authority.ci1`` are
recorded with that review's credit record and a ``judgment-checkin`` record of what was checked:

- A06: the plan's steps and deliverables, its cost bounds and every numbered assumption are in the view;
- C03: every section the route supplies has substantive content (the authority also refuses a hollow
  required section before assent);
- C14: not applicable when the frame states no result-sensitive (physics-critical) assumption; left
  open otherwise, because a frame assumption carries its basis but no alternatives;
- C04: not applicable: the judgment route declares no check-in variant to select.

A decide step's C01 (method ladder) and E28 (operating protocol) are discharged by its RDJ case: the case the
plan-approval mapping credits on the step's exact spec (credited from its observed blind seat, approving), and only
when the packet that seat was delivered (its instruction delivery receipt) carried the method ladder and every
operating-protocol unit the step's triggers require. Otherwise both stay pending.

A decide step's judgment record is stored in one place, by the governed step's validate node (the judgment service's
``record_judgment``). The controller's decide close runs first: it holds a decision without its stored record and runs
its RDJ seat. Only then does ``decided`` check the STORED record against the step as planned (its planned triggers and
protocols, ``records.check_record``); a refused record holds the decision. Its C08 (an adopted physics-critical
default has a pinned justified default record) is satisfied by that stored record when the decision adopted a default
with its P7 record, and not applicable, citing it, when the decision adopted none.

The recipe ledger (``recipe_ledger.build``: every requested recipe value with its effective value or ``unknown``) is
snapshotted when a plan is approved (CHECK-IN 1, or a deviation's renewed approval) and again at CHECK-IN 3, each
snapshot a ``judgment-recipe-ledger`` record whose digest the check-in view pins; the CHECK-IN 3 snapshot names the
approval snapshot it continues. CHECK-IN 3 records JR04 (every plan step ran through the governed step graph: its
latest ``step-outcome``), shows every current unknown and deviated recipe row, and records C36 (node
``authority.ci3``): satisfied when every row the approval snapshot held is still there with its requested side
unchanged (a status that moved, for example from unknown to matched, is evidence, not a change), violated naming the
rows it lost otherwise, and left pending when the approved plan has no approval snapshot to compare with. A ledger
that cannot be rebuilt is disclosed (a CHECK-IN 1 flag, a CHECK-IN 3 section line) and evidences nothing.
"""
from __future__ import annotations

from copy import deepcopy

from .records import digest

NODE = 'authority.ci1'
FACT = 'judgment-checkin'
PROVIDER = 'judgment.checkins'
REVIEW_STEP = 'plan_review'
RECIPE = 'judgment-recipe-ledger'
FINAL_NODE = 'authority.ci3'
APPROVALS = ('approve_plan', 'checkin1', 'deviation')


def _records(store, kind):
    from ravel.controller.step.services import records
    return records(store, kind)


def _frame(store, plan):
    """The accepted question frame the plan was decomposed from, read by its digest from the run store."""
    from .control import FRAME_KIND
    wanted = ((plan.get('parameters') or {}).get('judgment') or {}).get('frame_sha256')
    for row in reversed(_records(store, FRAME_KIND)):
        if row.get('sha256') == wanted and type(row.get('frame')) is dict:
            return row['frame']
    return None


def _credit(store, plan):
    """The store id of the latest credited CHECK-IN 1 plan review of this exact plan, or None."""
    for row in reversed(_records(store, 'step-credit')):
        own = row.get('own') or {}
        if (row.get('step_id') == REVIEW_STEP and row.get('credited') is True and own.get('credited') is True
                and (own.get('query') or {}).get('subject_sha256') == plan.get('sha256')):
            return row.get('_record_id')
    return None


def _flag(assumption):
    text = f"{assumption['number']}. {assumption['statement']} (basis: {assumption['basis']})"
    return {'kind': 'assumption', 'text': text + (' [physics-critical]' if assumption.get('physics_critical') else '')}


def _bounds_lines(plan):
    from ravel.controller.graph import plan_bounds
    bounds = plan_bounds(plan)
    budget = ', '.join(f'{k}={v}' for k, v in sorted(bounds['budget'].items()))
    return [f"Highest rung: {bounds['rung']}", 'Stages: ' + ', '.join(bounds['stages']),
            'Budget: ' + (budget or 'no step budget beyond the operator envelope')]


def _record(store, rows, status, evidence):
    from ravel.controller import graph as controller_graph
    ledger = controller_graph.service('ledger')
    pending, record_many = getattr(ledger, 'pending', None), getattr(ledger, 'record_many', None)
    if not callable(pending) or not callable(record_many):
        return []
    keys = [k for k in pending(store, node=NODE) if k.split('@', 1)[0] in rows]
    if not keys:
        return []
    try:
        record_many(store, [(key, status, deepcopy(evidence)) for key in keys])
    except Exception as exc:
        if type(exc).__name__ not in ('LedgerError', 'CatalogueError'):
            raise
        store.append('route-ledger-refusal', {'node': NODE, 'status': status, 'entries': keys,
                                              'reason': str(exc)[:1000], 'provider': PROVIDER})
        return []
    return keys


def _recipe_rows(run_dir):
    """The run's current recipe ledger rows (``recipe_ledger.build``); none without recipe inputs."""
    from ravel.validation.validate_checkin import _sibling_contract
    from ravel.workflow import recipe_ledger
    if not recipe_ledger._has_inputs(run_dir, _sibling_contract(run_dir)):
        return []
    return recipe_ledger.build(run_dir)['rows']


def _snapshot(store, run_dir, plan, kind, previous=None):
    """``(record id, record)`` of the recipe ledger this check-in shows, stored once per content."""
    rows = _recipe_rows(run_dir)
    record = {'schema_version': 1, 'checkin': kind, 'plan_sha256': plan.get('sha256'), 'ledger_sha256': digest(rows),
              'rows': rows, 'previous': previous}
    found = next((r['_record_id'] for r in _records(store, RECIPE)
                  if digest({k: r.get(k) for k in record}) == digest(record)), None)
    return found or store.append(RECIPE, record), record


def _requested(row):
    from ravel.workflow import recipe_ledger
    return None if row is None else {k: row.get(k) for k in recipe_ledger._REQUESTED_VIEW}


def _recipe_line(row):
    return f"{row.get('status')}: {row.get('id')} ({row.get('layer')} {row.get('field')})"


def _final(context):
    """CHECK-IN 3: every current unknown and deviated recipe row, and C36 from the approval snapshot's comparison."""
    store, run_dir, plan = context.get('store'), context.get('run_dir'), context.get('plan') or {}
    empty = {'kind': 'final', 'errors': [], 'sections': [], 'required_sections': []}
    if store is None or run_dir is None:
        return empty
    approved = ((context.get('state') or {}).get('plan') or {}).get('approved_sha256') or plan.get('sha256')
    start = next((r for r in reversed(_records(store, RECIPE))
                  if r.get('checkin') in APPROVALS and r.get('plan_sha256') == approved), None)
    try:
        record_id, record = _snapshot(store, run_dir, plan, 'final', previous=(start or {}).get('_record_id'))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Unreadable recipe evidence is shown, and nothing evidences C36: the row stays pending and the ledger keeps
        # the delivery transition shut.
        return {**empty, 'sections': [{'id': 'recipe_ledger', 'title': 'Recipe ledger', 'lines': [
            f'The recipe ledger cannot be rebuilt: {exc}'[:500]]}], 'required_sections': ['recipe_ledger']}
    shown = [r for r in record['rows'] if r.get('status') in ('unknown', 'deviated')]
    sections = [{'id': 'recipe_ledger', 'title': 'Recipe ledger',
                 'lines': [_recipe_line(r) for r in shown] or [
                     f"No unknown or deviated recipe ledger row ({len(record['rows'])} row(s) recorded)."]}]
    if start is not None:
        current = {r.get('id'): r for r in record['rows']}
        lost = sorted(r.get('id') for r in start['rows'] if _requested(r) != _requested(current.get(r.get('id'))))
        evidence = {'record': record_id, 'approval_record': start['_record_id'], 'sha256': record['ledger_sha256'],
                    'approved_sha256': start['ledger_sha256'], 'shown': [r.get('id') for r in shown],
                    'mechanism': PROVIDER}
        if lost:
            evidence.update(reason='the CHECK-IN 3 recipe ledger drops or alters rows its approval held', rows=lost)
        _record_rows_at(store, FINAL_NODE, None, {'C36'}, 'violated' if lost else 'satisfied', evidence)
    _fanout(store, plan)
    return {**empty, 'sections': sections, 'required_sections': ['recipe_ledger'],
            'pins': {'recipe_ledger_sha256': record['ledger_sha256']}}


def _fanout(store, plan):
    """JR04 at CHECK-IN 3: every step of the plan ran through the governed step graph, shown by its latest
    ``step-outcome`` (only the governed step writes one). A step without one leaves the row pending."""
    outcomes = {}
    for row in _records(store, 'step-outcome'):
        outcomes[row.get('step_id')] = row.get('_record_id')
    steps = [s['id'] for s in plan.get('steps') or () if type(s) is dict and type(s.get('id')) is str]
    if not steps or any(sid not in outcomes for sid in steps):
        return
    _record_rows_at(store, 'judgment.fanout', None, {'JR04'}, 'satisfied',
                    {'record': outcomes[steps[-1]], 'outcomes': {sid: outcomes[sid] for sid in steps},
                     'graph': 'controller.step', 'mechanism': PROVIDER})


def checkin(kind, context) -> dict:
    """The judgment route's part of a typed check-in view; ``errors`` hold the authority point."""
    empty = {'kind': kind, 'errors': [], 'sections': [], 'required_sections': []}
    if kind == 'final':
        return _final(context)
    if kind not in APPROVALS:
        return empty
    store, plan, pins, unreadable = context.get('store'), context.get('plan') or {}, {}, []
    if store is not None and context.get('run_dir') is not None:
        # The approval binds the recipe ledger it was shown; CHECK-IN 3 compares the ledger with this snapshot (C36).
        # A ledger that cannot be rebuilt is flagged, and with no snapshot C36 cannot be satisfied later.
        try:
            _, snapshot = _snapshot(store, context['run_dir'], plan, kind)
            pins['recipe_ledger_sha256'] = snapshot['ledger_sha256']
        except (OSError, ValueError, KeyError, TypeError) as exc:
            unreadable.append({'kind': 'risk', 'text': f'The recipe ledger cannot be rebuilt: {exc}'[:500]})
    if kind == 'deviation':
        return {**empty, 'pins': pins, 'flags': unreadable}
    sections = [{'id': 'bounds', 'title': 'Bounds this approval covers', 'lines': _bounds_lines(plan)}]
    frame = _frame(store, plan)
    if frame is None:
        # Without its frame the view cannot show the numbered assumptions: no content row is recorded, so the
        # ledger keeps the CHECK-IN 1 transition shut.
        return {**empty, 'sections': sections, 'required_sections': ['bounds'], 'pins': pins, 'flags': unreadable}
    flags = [_flag(a) for a in frame['assumptions']] + unreadable
    critical = [a['number'] for a in frame['assumptions'] if a.get('physics_critical')]
    checked = {'schema_version': 1, 'plan_sha256': plan.get('sha256'),
               'frame_sha256': ((plan.get('parameters') or {}).get('judgment') or {}).get('frame_sha256'),
               'sections': deepcopy(sections), 'flags': deepcopy(flags),
               'steps': len(plan.get('steps') or ()), 'deliverables': len(plan.get('deliverables') or ()),
               'physics_critical_assumptions': critical,
               'checkin_variants': [c.get('id') for c in plan.get('checkins') or () if c.get('variants')]}
    # One record per checked content: a poll or a second view of the same plan reuses it.
    fact = next((r['_record_id'] for r in _records(store, FACT)
                 if digest({k: r.get(k) for k in checked}) == digest(checked)), None) or store.append(FACT, checked)
    evidence = {'sha256': plan.get('sha256'), 'record': fact, 'mechanism': PROVIDER}
    if not any(c.get('variants') for c in plan.get('checkins') or ()):
        _record(store, {'C04'}, 'not_applicable', {**evidence, 'reason': 'not_applicable:route_declares_no_checkin_variant'})
    credit = _credit(store, plan)
    complete = bool(plan.get('steps')) and bool(plan.get('deliverables')) and all(s['lines'] for s in sections)
    if credit and complete:
        _record(store, {'A06', 'C03'}, 'satisfied', {**evidence, 'credit': credit})
        if not critical:
            _record(store, {'C14'}, 'not_applicable',
                    {**evidence, 'credit': credit, 'reason': 'not_applicable:no_result_sensitive_assumption'})
    _decide_rows(store, plan)
    return {'kind': kind, 'errors': [], 'sections': sections, 'required_sections': ['bounds'], 'flags': flags,
            'pins': pins}


DECIDE_NODES = (('C01', 'judgment.method_ladder'), ('E28', 'judgment.protocol'))


def _delivered(store, step_id):
    """``(delivery receipt, unit ids)`` of the latest instruction packet a step's worker session was delivered."""
    deliveries = [r for r in _records(store, 'instruction-delivery') if r.get('step_id') == step_id
                  and r.get('kind') == 'instruction-delivery-session' and r.get('delivery')]
    if not deliveries:
        return None, set()
    latest = deliveries[-1]
    packets = [r for r in _records(store, 'instruction-packet') if r.get('step_id') == step_id
               and (r.get('manifest') or {}).get('sha256') == latest.get('manifest_sha256')]
    units = {u['id'] for u in (packets[-1]['manifest'].get('units') or ()) if type(u) is dict} if packets else set()
    return latest['delivery'], units


def _decide_rows(store, plan):
    """C01 and E28 of every decide step of ``plan``, from its credited RDJ case and the duties its seat was delivered."""
    from ravel.controller import graph as controller_graph
    from ravel.controller.instructions import catalogue as instruction_catalogue
    from ravel.workflow import rdj_approval
    from . import protocols, steps
    ledger = controller_graph.service('ledger')
    pending, record_many = getattr(ledger, 'pending', None), getattr(ledger, 'record_many', None)
    if not callable(pending) or not callable(record_many):
        return
    catalogue = instruction_catalogue.installed()
    for step in plan.get('steps') or ():
        if type(step) is not dict or step.get('kind') != 'decide':
            continue
        found, reason = rdj_approval.case(store, rdj_approval.subject(step))
        if reason is not None:
            continue
        triggers = ((step.get('parameters') or {}).get('judgment') or {}).get('triggers') or []
        duties = {'C01': set(catalogue.resolve(steps.METHOD_LADDER)), 'E28': set(catalogue.resolve('protocol:common'))}
        for protocol in protocols.protocol_ids_for(triggers):
            duties['E28'] |= set(catalogue.resolve(f'protocol:{protocol}'))
        receipt, units = _delivered(store, found['step_id'])
        for row, node in DECIDE_NODES:
            if not receipt or not duties[row] <= units:
                continue  # the RDJ seat was not delivered this duty: nothing discharges the row
            keys = [k for k in pending(store, node=node, step=step['id']) if k.split('@', 1)[0] == row]
            evidence = {'credit': found['credit'], 'instruction_receipt': receipt, 'rdj_step': found['step_id'],
                        'session': found.get('session'), 'units': sorted(duties[row]), 'mechanism': PROVIDER,
                        'sha256': rdj_approval.subject(step)}
            try:
                if keys:
                    record_many(store, [(key, 'satisfied', deepcopy(evidence)) for key in keys])
            except Exception as exc:
                if type(exc).__name__ not in ('LedgerError', 'CatalogueError'):
                    raise
                store.append('route-ledger-refusal', {'node': node, 'status': 'satisfied', 'entries': keys,
                                                      'reason': str(exc)[:1000], 'provider': PROVIDER})


def decided(step, record, context) -> list:
    """The route's check of a decide step whose STORED judgment record the controller's decide close found
    (``record``: the stored body with its ``judgment_id``): it must satisfy the step as planned; C08 is recorded from it.
    Returns the problems, which hold the decision; it stores nothing and never fails a step."""
    from . import records
    if type(step) is not dict or step.get('kind') != 'decide' or type(record) is not dict:
        return []
    judgment = (step.get('parameters') or {}).get('judgment') or {}
    as_planned = {'id': step['id'], 'kind': 'decide', 'protocols': list(step.get('protocols') or []),
                  'triggers': list(judgment.get('triggers') or [])}
    body = {k: v for k, v in record.items() if k not in ('record_sha256', 'judgment_id')}
    problems = records.check_record(body, step=as_planned)
    if problems:
        return [f'decide step {step["id"]} judgment record: {p}' for p in problems]
    adopted = (body.get('default_option') is not None and body['chosen'] == body['default_option']) \
        or 'adopt_default' in records.effective_triggers(body, as_planned)
    evidence = {'record': record.get('judgment_id'), 'sha256': record.get('record_sha256'), 'chosen': body['chosen'],
                'mechanism': PROVIDER}
    if adopted and body.get('default'):
        status, evidence = 'satisfied', {**evidence, 'default_option': body.get('default_option')}
    elif adopted:
        return [f'decide step {step["id"]} adopted a default without its P7 record']
    else:
        status, evidence = 'not_applicable', {**evidence, 'reason': 'not_applicable:no_default_adopted'}
    _record_rows_at(context.get('store'), 'judgment.default', step['id'], {'C08'}, status, evidence)
    return []


def _record_rows_at(store, node, step_id, rows, status, evidence):
    from ravel.controller import graph as controller_graph
    ledger = controller_graph.service('ledger')
    pending, record_many = getattr(ledger, 'pending', None), getattr(ledger, 'record_many', None)
    if not callable(pending) or not callable(record_many):
        return []
    keys = [k for k in pending(store, node=node, step=step_id) if k.split('@', 1)[0] in rows]
    if not keys:
        return []
    try:
        record_many(store, [(key, status, deepcopy(evidence)) for key in keys])
    except Exception as exc:
        if type(exc).__name__ not in ('LedgerError', 'CatalogueError'):
            raise
        store.append('route-ledger-refusal', {'node': node, 'status': status, 'entries': keys,
                                              'reason': str(exc)[:1000], 'provider': PROVIDER})
        return []
    return keys

