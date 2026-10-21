"""Expected/observed comparison with evidence gaps kept visible."""
from __future__ import annotations

from collections import Counter
from contextlib import nullcontext
from copy import deepcopy
import json
import re
from types import SimpleNamespace

from .canary import fault_verdicts, receipt_section
from .observed import body, observe
from .records import DiagnosticsRefused, digest, pinned, private_file

SUCCESS = ('completed', 'succeeded', 'ok')
HOLDS = ('held', 'escalated', 'budget_exhausted', 'stopped', 'refused')
CODE = re.compile(r'[a-z][a-z0-9_]*(?:[:,][A-Za-z0-9_.-]+)*\Z')


def _node(row):
    return row.get('diagnostics_node_id') or row.get('step_id') or row.get('step') or row.get('node_id')


def _seat(row):
    seat = row.get('seat') or 'producer'
    return seat.split(':')[1] if seat.startswith('seat:') and len(seat.split(':')) == 3 else seat


def _reason(row):
    reason = row.get('reason') or row.get('failure') or row.get('error')
    if isinstance(reason, dict) and reason.get('code'):
        return deepcopy(reason)
    # The step controller records a typed hold as its reason code, with the detail beside it.
    if isinstance(reason, str) and CODE.match(reason):
        detail = row.get('detail')
        return {'code': reason, 'message': detail if isinstance(detail, str) else ''}
    return {'code': 'untyped_hold', 'message': str(reason or 'No typed reason was recorded.')}


def _seat_outcome_node(row, known):
    """The expected node of a seat outcome recorded under a derived step id, else None.

    The step controller records a review seat's outcome under ``<step>:...`` with its seat key.
    """
    step = row.get('step_id')
    if not row.get('seat') or not isinstance(step, str) or step in known:
        return None
    if row.get('diagnostics_node_id') in known:
        return row['diagnostics_node_id']
    parents = [node for node in known if step.startswith(node + ':')]
    return max(parents, key=len) if parents else None


def _same_worker(dispatch, row):
    """Whether a session record belongs to ``dispatch``: by worker node id when both carry one."""
    if row.get('attempt', 1) != dispatch.get('attempt', 1):
        return False
    if dispatch.get('node_id') and row.get('node_id'):
        return row['node_id'] == dispatch['node_id']
    return _node(row) == _node(dispatch) and _seat(row) == _seat(dispatch)


def _row(identifier, node, kind, status, evidence=(), differences=(), reason=None):
    return {'id': identifier, 'node_id': node, 'kind': kind, 'status': status,
            'differences': list(differences), 'reason': reason, 'evidence': list(evidence)}


def _ledger(expected, records):
    actual = {}
    for event in records['ledger']:
        value = body(event).get('body', {})
        if value.get('event') == 'materialise':
            for instance in value.get('instances', []):
                actual.setdefault(instance['key'], {'key': instance['key'], 'row': instance['id'],
                                                   'status': 'pending', 'evidence': [],
                                                   'record_ids': [event['id']]})
        elif value.get('event') == 'status':
            for change in value.get('changes', []):
                key = change['key']
                if key not in actual:
                    actual[key] = {'key': key, 'row': None, 'record_ids': [], 'status': 'unknown'}
                actual[key].update(status=change['to'], evidence=deepcopy(change.get('evidence')))
                actual[key]['record_ids'].append(event['id'])
    result = []
    for row in expected['obligations']:
        current = actual.pop(row['key'], None)
        result.append({**deepcopy(row), **(current or {}),
                       'status': current['status'] if current else 'pending',
                       'materialised': current is not None,
                       'evidence': current.get('evidence', []) if current else [],
                       'record_ids': current.get('record_ids', []) if current else []})
    result.extend({**row, 'extra': True, 'materialised': True} for row in actual.values())
    return result


def compare(expected, observed, *, instructions=None, completion_store=None):
    """Pure comparison. Missing records never become a successful check."""
    if instructions is None:
        from ravel.controller import instructions
    from .records import verify
    verify(expected)
    records = observed['records']
    rows, used_dispatches = [], set()
    dispatches, observations = records['step-dispatch'], records['step-observation']
    session_counts = Counter(body(e).get('session_id') for e in observations if body(e).get('session_id'))
    outcomes = records['step-outcome'] + records['step-result']
    outcomes.sort(key=lambda e: e['seq'])
    known_nodes = {n['id'] for n in expected['nodes']}
    seat_outcomes = {e['id']: node for e in outcomes
                     if (node := _seat_outcome_node(body(e), known_nodes)) is not None}
    node_outcomes = [e for e in outcomes if e['id'] not in seat_outcomes]
    used_outcomes = set()
    ended = bool(records['ending'] or records['receipt'])
    for node in expected['nodes']:
        name = node['id']
        found = [e for e in node_outcomes if _node(body(e)) == name]
        if node['kind'] == 'checkin':
            found += [e for e in records['authority'] if _node(body(e)) == name
                      or (body(e).get('subject') or {}).get('checkin') == name]
        if not found:
            rows.append(_row(name, name, node['kind'], 'skipped',
                             differences=['No outcome recorded.' + ('' if ended else ' Run is unfinished.')]))
            continue
        found.sort(key=lambda e: e['seq'])
        last = body(found[-1])
        status = last.get('status')
        if node['kind'] == 'checkin' and 'decision' in last:
            status = 'completed' if last.get('authorizes_effects') else 'held'
        if status in HOLDS:
            rows.append(_row(name, name, node['kind'], 'held', [e['id'] for e in found],
                             reason=_reason(last)))
        else:
            differences = [] if status in SUCCESS else ['Outcome: ' + str(status)]
            if len(found) > 1:
                differences.append(f'{len(found)} recorded attempts/outcomes; initial design expected one.')
            rows.append(_row(name, name, node['kind'], 'ran-differently' if differences else 'ran-as-designed',
                             [e['id'] for e in found], differences))
    for seat in expected['seats']:
        matches = [e for e in dispatches if body(e).get('diagnostics_seat_id') == seat['id'] or
                   (_node(body(e)) == seat['node_id'] and _seat(body(e)) == seat['seat'])]
        mine = [e for e in outcomes if seat_outcomes.get(e['id']) == seat['node_id'] and (
                body(e).get('diagnostics_seat_id') == seat['id'] or body(e).get('seat') == seat['id']
                or _seat(body(e)) == seat['seat'])]
        used_outcomes.update(e['id'] for e in mine)
        if not matches:
            condition = seat.get('conditional')
            seat_holds = [e for e in mine if body(e).get('status') in HOLDS]
            parent_holds = [e for e in node_outcomes if _node(body(e)) == seat['node_id'] and body(e).get('status') in HOLDS]
            if seat_holds or parent_holds:
                last_hold = (seat_holds or parent_holds)[-1]
                rows.append(_row(seat['id'], seat['node_id'], 'seat', 'held', [last_hold['id']],
                                 ['Seat was held before dispatch.' if seat_holds else
                                  'Seat did not start because its node held.'], _reason(body(last_hold))))
                continue
            rows.append(_row(seat['id'], seat['node_id'], 'seat', 'held' if condition else 'skipped',
                             differences=[] if condition else ['Expected seat was never dispatched.'],
                             reason={'code': 'conditional_not_observed', 'message': str(condition)} if condition else None))
            continue
        used_dispatches.update(e['id'] for e in matches)
        differences, evidence, last = [], [], {}
        for dispatch in matches:
            d = body(dispatch)
            evidence.append(dispatch['id'])
            if d.get('role') != seat['role']:
                differences.append('Role differs or was not recorded: ' + str(d.get('role')))
            obs = [e for e in observations if _same_worker(d, body(e))]
            if len(obs) != 1:
                differences.append('Expected exactly one session observation for this dispatch.')
                continue
            last = body(obs[0])
            evidence.append(obs[0]['id'])
            if last.get('role') != seat['role']:
                differences.append('Observed role differs or was not recorded: ' + str(last.get('role')))
            if not last.get('session_id'):
                differences.append('Worker session identity missing.')
            elif session_counts[last['session_id']] > 1:
                differences.append('Worker session identity was reused across observations.')
            # A receipt names the step that acted: the dispatched node or the observed seat step.
            deliveries = [e for e in records['instruction-delivery']
                          if _node(body(e)) in {_node(d), d.get('step_id'), last.get('step_id')}
                          and _seat(body(e)) == _seat(d)
                          and body(e).get('attempt', 1) == d.get('attempt', 1)
                          and body(e).get('kind') != 'instruction-delivery-session']
            if len(deliveries) != 1:
                differences.append('Expected exactly one instruction receipt.')
            else:
                delivery = body(deliveries[0])
                evidence.append(deliveries[0]['id'])
                if delivery.get('manifest_sha256') != seat['manifest']['sha256']:
                    differences.append('Instruction manifest differs from expected units.')
                if d.get('packet_sha256') != delivery.get('packet_sha256'):
                    differences.append('Dispatch packet differs from instruction receipt.')
                if 'units' in delivery:
                    received = delivery['units']
                    # Instruction receipts carry ids; their manifest digest binds the unit bytes.
                    if not isinstance(received, list):
                        same = False
                    elif all(isinstance(u, str) for u in received):
                        same = sorted(received) == sorted(u['id'] for u in seat['instruction_units'])
                    elif all(isinstance(u, dict) and u.get('id') and u.get('sha256') for u in received):
                        same = sorted((u['id'], u['sha256']) for u in received) == sorted(
                            (u['id'], u['sha256']) for u in seat['instruction_units'])
                    else:
                        same = False
                    if not same:
                        differences.append('Received instruction unit population differs.')
            completion = [e for e in records['worker-completion']
                          if body(e).get('session') == last.get('session_id') and last.get('session_id')]
            if len(completion) != 1:
                differences.append('Observed instruction acknowledgement missing.')
            else:
                evidence.append(completion[0]['id'])
                final = body(completion[0])
                scope = (instructions.observed_completion(completion_store, session=last['session_id'],
                         completion_id=completion[0]['id']) if completion_store is not None
                         and hasattr(instructions, 'observed_completion') else nullcontext())
                with scope:
                    errors = instructions.check_ack(seat['manifest'], final.get('final_record', {}),
                                                    [a['path'] if isinstance(a, dict) else a
                                                     for a in final.get('artifacts', [])])
                differences.extend('Acknowledgement: ' + str(error) for error in errors)
        if len(matches) > 1:
            differences.append(f'{len(matches)} dispatches for this seat.')
        outcome = body(mine[-1]) if mine else {}
        evidence.extend(e['id'] for e in mine)
        if mine and outcome.get('status') not in SUCCESS + HOLDS:
            differences.append('Seat outcome: ' + str(outcome.get('status')))
        status = ('held' if last.get('status') in HOLDS or outcome.get('status') in HOLDS else
                  'ran-differently' if differences or last.get('status') not in SUCCESS else 'ran-as-designed')
        reason = None
        if status == 'held':
            reason = _reason(outcome if outcome.get('status') in HOLDS else last)
        rows.append(_row(seat['id'], seat['node_id'], 'seat', status, evidence, sorted(set(differences)), reason))
    for dispatch in dispatches:
        if dispatch['id'] not in used_dispatches:
            rows.append(_row('extra:' + dispatch['id'], _node(body(dispatch)), 'seat', 'extra', [dispatch['id']],
                             ['Dispatch has no expected seat.']))
    for observation in observations:
        o = body(observation)
        if not any(_same_worker(body(e), o) for e in dispatches):
            rows.append(_row('extra:' + observation['id'], _node(o), 'session', 'extra', [observation['id']],
                             ['Worker observation has no recorded dispatch.']))
    for outcome in outcomes:
        if outcome['id'] in seat_outcomes:
            if outcome['id'] not in used_outcomes:
                rows.append(_row('extra:' + outcome['id'], seat_outcomes[outcome['id']], 'seat', 'extra',
                                 [outcome['id']], ['Seat outcome has no expected seat.']))
        elif _node(body(outcome)) not in known_nodes:
            rows.append(_row('extra:' + outcome['id'], _node(body(outcome)), 'step', 'extra', [outcome['id']],
                             ['Outcome has no expected node.']))
    for event in records['plan']:
        plan_sha = body(event).get('plan_sha256')
        if plan_sha and plan_sha != expected['plan_sha256']:
            rows.append(_row('plan:' + event['id'], 'run', 'plan', 'ran-differently', [event['id']],
                             ['Recorded plan differs from the initial expected-run design.']))
    for event in records['engagement-escalation']:
        rows.append(_row('engagement:' + event['id'], body(event).get('step_id') or 'run', 'engagement',
                         'ran-differently', [event['id']], ['Recorded engagement escalation: ' +
                          str(body(event).get('new_tier'))]))
    for case in expected['rdj_cases']:
        found = []
        for event in records['judgment-event']:
            review = (body(event).get('rdj') or {}).get(case['node_id'])
            if review:
                found.append((event, review))
        for event in records['rdj-receipt']:
            if _node(body(event)) == case['node_id']:
                found.append((event, body(event)))
        if not found:
            rows.append(_row(case['id'], case['node_id'], 'rdj', 'skipped',
                             differences=['Expected consequence-class review has no recorded case.']))
        else:
            found.sort(key=lambda pair: pair[0]['seq'])
            event, review = found[-1]
            differences = []
            if review.get('credited') is not True:
                differences.append('RDJ case was not credited.')
            if review.get('subject_sha256') != case['subject_sha256']:
                differences.append('RDJ case covers a different subject.')
            effects = [e for e in dispatches + outcomes if _node(body(e)) == case['node_id']]
            if effects and event['seq'] >= min(e['seq'] for e in effects):
                differences.append('RDJ case was recorded after the node began execution.')
            if case['authority_required'] and effects:
                first = min(e['seq'] for e in effects)
                authority = [e for e in records['authority'] if _node(body(e)) == case['node_id']
                             and body(e).get('authorizes_effects') is True and e['seq'] < first]
                if not authority:
                    differences.append('R3 authority was not observed before the effect.')
            rows.append(_row(case['id'], case['node_id'], 'rdj',
                             'ran-differently' if differences else 'ran-as-designed', [event['id']], differences))
    # Tool broker evidence and model broker requests are different populations.
    counts = {'expected_seats': sum(not s.get('conditional') for s in expected['seats']),
              'conditional_seats': sum(bool(s.get('conditional')) for s in expected['seats']),
              'dispatched_seats': len(dispatches), 'observed_sessions': len(observations),
              'unique_sessions': len(session_counts),
              'broker_tool_calls': len(records['broker-evidence']),
              'broker_model_calls': len(records['broker-model-call']),
              'controller_model_calls': 0, 'controller_tool_calls': 0}
    unknown_model = unknown_tools = False
    for observation in observations:
        o = body(observation)
        usage = o.get('usage') or {}
        calls = o.get('calls') or {}
        if usage.get('reported') is True and type(usage.get('turns')) is int:
            counts['controller_model_calls'] += usage['turns']
        else:
            unknown_model = True
        if type(calls.get('broker_calls')) is int:
            counts['controller_tool_calls'] += calls['broker_calls']
        else:
            unknown_tools = True
    if unknown_model:
        counts['controller_model_calls'] = None
    if unknown_tools:
        counts['controller_tool_calls'] = None
    for kind, metric in (('broker-evidence', 'broker_calls'), ('broker-model-call', 'turns')):
        used = Counter()
        for call in records[kind]:
            c = body(call)
            linked = [e for e in observations if body(e).get('node_id') == c.get('node_id')
                      and body(e).get('attempt', 1) == c.get('attempt', 1) and c.get('node_id')]
            if len(linked) != 1:
                rows.append(_row('extra:' + call['id'], _node(c), kind, 'extra', [call['id']],
                                 ['Broker call has no unique observed worker seat.']))
            else:
                key = (c['node_id'], c.get('attempt', 1))
                used[key] += 1
                observed_worker = body(linked[0])
                counted = (observed_worker.get('calls') or {}) if kind == 'broker-evidence' else (observed_worker.get('usage') or {})
                limit = counted.get(metric)
                if type(limit) is int and used[key] > limit:
                    rows.append(_row('extra:' + call['id'], _node(observed_worker), kind, 'extra',
                                     [call['id'], linked[0]['id']],
                                     ['Broker call exceeds the session observation count.']))
    checks = records['envelope-check']
    envelope = deepcopy(body(checks[-1])) if checks else {'status': 'unknown', 'reason': 'No envelope check recorded.'}
    if checks:
        census = {name: [{**body(e), 'record_id': e['id']} for e in records[kind]]
                  for name, kind in (('dispatches', 'step-dispatch'), ('observations', 'step-observation'),
                                     ('settlements', 'budget-settlement'))}
        census['deliveries'] = [{**body(e), 'record_id': e['id']} for e in records['instruction-delivery']
                                if body(e).get('kind') == 'instruction-delivery-session']
        if envelope.get('usage_sha256') != digest(census):
            envelope = {**envelope, 'recorded_status': envelope.get('status'), 'status': 'unknown',
                        'reason': 'Envelope check is stale or lacks a binding to the current usage census.'}
    counts['tool_counts_equal'] = counts['controller_tool_calls'] == counts['broker_tool_calls'] if not unknown_tools else None
    counts['model_counts_equal'] = (counts['controller_model_calls'] == counts['broker_model_calls']
                                   if records['broker-model-call'] and not unknown_model else None)
    obligations = _ledger(expected, records)
    fault_rows = fault_verdicts(observed)
    statuses = dict(Counter(r['status'] for r in rows))
    bad = sum(statuses.get(s, 0) for s in ('skipped', 'held', 'extra', 'ran-differently'))
    obligation_counts = dict(Counter(o['status'] for o in obligations))
    summary = (f"{len(rows)} node and seat observations: {statuses.get('ran-as-designed', 0)} ran as designed; "
               f"{statuses.get('ran-differently', 0)} differed, {statuses.get('skipped', 0)} skipped, "
               f"{statuses.get('held', 0)} held, {statuses.get('extra', 0)} extra. "
               f"Envelope: {envelope.get('status', 'unknown')}. "
               f"Obligations: {obligation_counts.get('pending', 0)} pending, "
               f"{obligation_counts.get('violated', 0)} violated, {obligation_counts.get('waived', 0)} waived.")
    if fault_rows:
        summary += f" Faults detected as expected: {sum(f['detected'] for f in fault_rows)}/{len(fault_rows)}."
    if counts['tool_counts_equal'] is False or counts['model_counts_equal'] is False:
        summary += ' Broker and controller call counts differ.'
    if observed['gaps']:
        summary += f" {len(observed['gaps'])} evidence source(s) missing or unreadable."
    node_timeline = {}
    for event in observed['timeline']:
        node_timeline.setdefault(event['node_id'] or 'run', {'journal': [], 'graph': []})['journal'].append(event)
    for event in observed['graph_events']:
        node_timeline.setdefault(event.get('node') or 'run', {'journal': [], 'graph': []})['graph'].append(event)
    return {'schema': 'diagnostics-report.v1', 'run_id': observed['run_id'], 'summary': summary,
            'journal_cutoff_seq': observed['journal_cutoff_seq'],
            'expected_sha256': expected['sha256'], 'observed_sha256': observed['sha256'],
            'route': expected['route'], 'tier': expected['engagement_tier'],
            'rows': rows, 'status_counts': statuses, 'counts': counts, 'obligations': obligations,
            'envelope': envelope, 'faults': fault_rows, 'evidence_gaps': observed['gaps'],
            'unfinished': not ended, 'differences_present': bool(bad),
            'timeline': observed['timeline'], 'graph_events': observed['graph_events'],
            'checkpoints': observed['checkpoints'], 'node_timeline': node_timeline}


def _cell(value):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
    return text.replace('|', '\\|').replace('\n', ' ')


def markdown(report):
    """Plain-language summary first; tables carry the exact same rows as the JSON."""
    lines = [report['summary'], '',
             f"Run `{report['run_id']}`; route `{report['route']}`; tier `{report['tier']}`.", '',
             'These diagnostics describe recorded execution. Missing evidence remains unknown.', '',
             '| Node / seat | Kind | Status | Difference or hold reason | Evidence |',
             '|---|---|---|---|---|']
    for row in report['rows']:
        lines.append('| ' + ' | '.join(_cell(v) for v in (row['id'], row['kind'], row['status'],
                     row['reason'] or row['differences'], row['evidence'])) + ' |')
    lines += ['', '| Count | Value |', '|---|---|']
    lines += [f'| {_cell(k)} | {_cell(v)} |' for k, v in report['counts'].items()]
    lines += ['', '| Obligation | Discharging node | Status | Materialised | Evidence |', '|---|---|---|---|---|']
    for row in report['obligations']:
        lines.append('| ' + ' | '.join(_cell(row.get(k)) for k in
                     ('key', 'discharge_node', 'status', 'materialised', 'evidence')) + ' |')
    lines += ['', '| Injected fault | Expected response | Observed response | Detected | Evidence |', '|---|---|---|---|---|']
    for row in report['faults']:
        lines.append('| ' + ' | '.join(_cell(row[k]) for k in
                     ('fault', 'expected_response', 'observed_response', 'detected', 'evidence')) + ' |')
    lines += ['', 'Envelope: ' + _cell(report['envelope']), '', 'Evidence gaps: ' + _cell(report['evidence_gaps']), '']
    return '\n'.join(lines)


def report(store, *, instructions=None, write=True):
    pin = pinned(store)
    observed = observe(store)
    result = compare(pin['record'], observed, instructions=instructions, completion_store=store)
    result['expected_record_id'] = pin['id']
    snapshot = SimpleNamespace(scan=lambda kind: deepcopy(observed['records'].get(kind, [])))
    result['instrumentation'] = receipt_section(snapshot)
    checksum = digest(result)
    if write:
        for suffix, content in (('json', json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False).encode() + b'\n'),
                                ('md', markdown(result).encode())):
            parts = ('diagnostics', 'reports', checksum + '.' + suffix)
            path = store.path(*parts)
            if not path.exists():
                private_file(store, parts, content)
            elif path.read_bytes() != content:
                raise DiagnosticsRefused('report artifact differs from its content address')
        result['artifacts'] = {'json': str(store.path('diagnostics', 'reports', checksum + '.json')),
                               'markdown': str(store.path('diagnostics', 'reports', checksum + '.md'))}
    return result
