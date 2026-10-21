"""Runtime recovery: a step that cannot complete for a recoverable reason gets a governed recovery plan.

When a step's attempts are exhausted (or it holds) for a recoverable typed reason, the controller does not stop
at that step: it asks the judgment route for a recovery plan (a replan request of kind ``recovery``) that names
the alternatives it considered, with their evidence, and the one it chose: another source of the same quantity,
another method, a bounded approximation, or an explicit descope of the deliverable. The chosen recovery is a
deviation and passes the existing deviation check-in: a substitute source or method within the operator's bounds
is approved by machine authority in autonomous mode, a descope or anything outside the bounds waits for a human.
When the per-run recovery budget (operator budget ``recoveries``) is spent or no alternative exists, the rest of
the run completes and the qualified ending names each gap with the alternatives tried.

Recoverable reasons are an explicit vocabulary (``RECOVERABLE``): a missing or unresolvable input, a validator
left inconclusive by a missing input, an unavailable reader or data source, an external service's refusal, batch
jobs the scheduler removed without this run asking (``batch_jobs`` observer; its condition first waits for the
operator's acknowledgement). Batch jobs held at the scheduler are an operator wait, never a recovery.
Everything else stays what it is: a safety, authority, confinement, provider, ledger, gate, stop or budget
refusal or hold is never routed to recovery. Nothing here proposes an alternative; the judgment step does, from
the run's evidence and declared capabilities.
"""
from __future__ import annotations

from copy import deepcopy

KIND = 'recovery'
RECOVERABLE = ('run_input_missing', 'predecessor_unreceipted', 'supplied_input_missing', 'manuscript_input_missing',
               'validators_inconclusive', 'resource_unavailable', 'input_unresolvable', 'reader_unavailable',
               'source_unavailable', 'service_refused', 'batch_jobs_removed')
# Inconclusive validator reasons that come from an input the step could not obtain.
INPUT_INCONCLUSIVE = ('validator_input_missing', 'validator_input_invalid')
ALTERNATIVE_KINDS = ('source', 'method', 'approximation', 'descope')
DEFAULT_BUDGET = 2


def code_of(reason):
    """The typed code of a step reason (``code: detail`` or ``code:qualifier``)."""
    return str(reason or '').split(':', 1)[0].strip()


def classify(row, outcome=None):
    """``{recoverable, code, why}`` for a step row whose attempts are over (``failed``) or that holds (``held``)."""
    status = (row or {}).get('status')
    code = code_of((row or {}).get('reason') or (outcome or {}).get('reason'))
    if status not in ('failed', 'held'):
        return {'recoverable': False, 'code': code, 'why': f'status {status} is not an exhausted failure or a hold'}
    if code in RECOVERABLE:
        return {'recoverable': True, 'code': code, 'why': 'a recoverable reason: an input, reader, source or service'}
    return {'recoverable': False, 'code': code,
            'why': 'not a recoverable reason; safety, authority, confinement, provider, ledger, gate, stop and budget '
                   'refusals stay refusals or holds'}


def _records(store):
    return [row['record'] if type(row.get('record')) is dict else row for row in store.scan(KIND)]


def budget(mode):
    """The run's recovery budget from its frozen operator budgets (``recoveries``), else the default."""
    found = ((mode or {}).get('budgets') or {}).get('recoveries')
    return found if type(found) is int and found >= 0 else DEFAULT_BUDGET


def used(store):
    return sum(1 for r in _records(store) if r.get('phase') == 'requested')


def tried(store, step_id):
    """Alternatives already considered for ``step_id`` (every proposed recovery's rows)."""
    rows = []
    for record in _records(store):
        if record.get('step') == step_id and record.get('phase') in ('proposed', 'none'):
            rows.extend(deepcopy(record.get('alternatives') or []))
    return rows


def request(store, mode, step, row, outcome, *, run_inputs, tools):
    """A pending recovery request for ``step``, or None (not recoverable, already asked, or budget spent).

    Records ``requested`` (or ``budget_exhausted`` once) in the store. The request carries the failed step, its
    typed reason and evidence, the run's declared inputs and tools, and the alternatives already tried.
    """
    found = classify(row, outcome)
    if not found['recoverable']:
        return None
    attempt = row.get('attempts')
    asked = [r for r in _records(store) if r.get('step') == step['id'] and r.get('attempt') == attempt
             and r.get('phase') in ('requested', 'budget_exhausted')]
    if asked:
        return None
    limit = budget(mode)
    evidence = {'reason': row.get('reason'), 'detail': deepcopy((outcome or {}).get('detail')),
                'receipts': list((outcome or {}).get('receipts') or []), 'attempts': attempt}
    if used(store) >= limit:
        store.append(KIND, {'schema_version': 1, 'phase': 'budget_exhausted', 'step': step['id'], 'attempt': attempt,
                            'code': found['code'], 'budget': limit, 'evidence': evidence})
        return None
    store.append(KIND, {'schema_version': 1, 'phase': 'requested', 'step': step['id'], 'attempt': attempt,
                        'code': found['code'], 'budget': limit, 'evidence': evidence})
    return {'status': 'pending', 'kind': KIND,
            'reason': f"recovery of step {step['id']}: {found['code']}",
            'request': {'why': f"step {step['id']} cannot complete ({found['code']}); a recovery plan is needed",
                        'recovery': {'failed_step': step['id'], 'code': found['code'], 'evidence': evidence,
                                     'step': {k: deepcopy(step.get(k)) for k in ('kind', 'inputs', 'outputs',
                                                                                 'operation', 'description')},
                                     'run_inputs': deepcopy(run_inputs), 'tools': deepcopy(tools),
                                     'tried': tried(store, step['id']),
                                     'alternative_kinds': list(ALTERNATIVE_KINDS)}}}


def proposal_errors(proposal, failed_step):
    """Why a planner's ``recovery`` block cannot be taken (empty when it can)."""
    if type(proposal) is not dict:
        return ['the recovery plan states no recovery block']
    errors = []
    if proposal.get('failed_step') != failed_step:
        errors.append('the recovery block names another failed step')
    rows = proposal.get('alternatives')
    if type(rows) is not list or not rows:
        return errors + ['the recovery block lists no alternatives considered']
    ids = [r.get('id') for r in rows if type(r) is dict]
    if len(ids) != len(rows) or len(set(ids)) != len(ids):
        errors.append('alternatives need distinct ids')
    for item in rows:
        if type(item) is not dict:
            continue
        if item.get('kind') not in ALTERNATIVE_KINDS:
            errors.append(f"alternative {item.get('id')} has an unknown kind")
        if type(item.get('evidence')) is not list or not item['evidence']:
            errors.append(f"alternative {item.get('id')} cites no evidence")
        if item.get('kind') == 'approximation' and not item.get('bound'):
            errors.append(f"approximation {item.get('id')} states no bound")
        if item.get('id') != proposal.get('chosen') and not item.get('rejection'):
            errors.append(f"alternative {item.get('id')} was not chosen and states no rejection reason")
    chosen = proposal.get('chosen')
    if chosen is not None and chosen not in ids:
        errors.append('the chosen alternative is not among those considered')
    return errors


def chosen(proposal):
    """The chosen alternative row of a valid proposal, or None (no alternative)."""
    if type(proposal) is not dict or proposal.get('chosen') is None:
        return None
    return next((r for r in proposal.get('alternatives') or () if r.get('id') == proposal['chosen']), None)


def direction(alternative):
    """The deviation direction of a chosen alternative: a descope changes scope; a source is an input change."""
    kind = (alternative or {}).get('kind')
    return {'descope': 'scope', 'source': 'input'}.get(kind, 'plan')


def record_proposal(store, step_id, proposal, problems=()):
    """The planner's alternatives and rejection reasons, kept in the store (``proposed`` or ``none``)."""
    phase = 'none' if not problems and chosen(proposal) is None else ('refused' if problems else 'proposed')
    return store.append(KIND, {'schema_version': 1, 'phase': phase, 'step': step_id,
                               'alternatives': deepcopy((proposal or {}).get('alternatives') or []),
                               'chosen': (proposal or {}).get('chosen'), 'problems': list(problems)})


def gaps(store):
    """Per step without a completed recovery: the reason, the alternatives tried and why it stopped."""
    found = {}
    for record in _records(store):
        name = record.get('step')
        row = found.setdefault(name, {'step': name, 'code': None, 'alternatives': [], 'outcome': None})
        if record.get('code'):
            row['code'] = record['code']
        if record.get('phase') in ('proposed', 'none', 'refused'):
            row['alternatives'].extend(record.get('alternatives') or [])
        row['outcome'] = record.get('phase')
    return [row for row in found.values() if row['outcome'] in ('budget_exhausted', 'none', 'refused', 'requested',
                                                                 'declined')]


def summary(store):
    """One line naming each gap, for the qualified ending's reason (None when there is none)."""
    rows = gaps(store)
    if not rows:
        return None
    texts = []
    for row in rows:
        tried_ = ', '.join(f"{a.get('id')} ({a.get('rejection') or 'not taken'})" for a in row['alternatives']) or 'none'
        why = {'budget_exhausted': 'the recovery budget was exhausted', 'none': 'no alternative was found',
               'refused': 'the recovery plan was refused', 'requested': 'the recovery did not complete',
               'declined': 'the recovery deviation was not approved'}[row['outcome']]
        texts.append(f"step {row['step']} ({row['code']}): {why}; alternatives tried: {tried_}")
    return 'recovery: ' + ' | '.join(texts)
