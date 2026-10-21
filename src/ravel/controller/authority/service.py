"""The authority service: decisions for a controller-owned run, and the gates that consume them.

``request`` grants or withholds authority for one decision. The source is fixed by the run's
frozen operating mode, never by the caller:

- physicist-in-the-loop: controller-issued terminal challenges produce unattested evidence;
  they cannot prove human identity or authorize effects. An explicit authenticated operator
  answer can approve the retained request, with operator_command provenance.
- autonomous: operator-delegated check-ins resolve inside every frozen and current bound.
  R3 actions and questions escalate. An effectful conservative default needs explicit option
  bounds within delegation; other unresolved reasons hold. No machine default waives obligations.

Physicist approval is never synthesised. Gates (``verify``, ``current``, ``authorize_effect``)
read record ids from the store only; an approval-shaped file anywhere in the run tree is not
authority. The final disposition never authorizes an effect and never credits review.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import os
import subprocess
import sys

from . import checkin as checkin_mod
from . import common, stop, retained
from . import mode as mode_mod
from .operator import controller_home, validate_argv

AUTHORIZING = {'approve_plan': ('approve',), 'go': ('go',), 'deviation': ('approve',), 'final': (),
               'r3_action': ('approve', 'default'), 'escalation': ('answer', 'default'), 'steering': ('approve',)}
GATES_R3 = ('unblind', 'spend_above_ceiling')
DIRECTIONS = ('tighten', 'loosen', 'input', 'plan', 'scope')
CHANGE_KEYS = ('parameter', 'from', 'to', 'why', 'touches', 'direction')

# Resource ownership by the canonical step branch. Subgraphs reserve their workers and
# launches too; review rounds belong to subgraph admission, not an individual launch or
# worker session. Unlisted dimensions retain the full-scope check (fail closed).
RESOURCE_BRANCHES = frozenset(('launch', 'worker', 'subgraph'))
RESOURCE_CONSUMERS = {key: RESOURCE_BRANCHES for key in (
    'wall_seconds', 'model_calls', 'tokens', 'cost_usd', 'core_hours', 'events', 'children',
    'input_bytes', 'input_files', 'batch_cpu_hours', 'batch_jobs')}
RESOURCE_CONSUMERS['review_rounds'] = frozenset(('subgraph',))


# ------------------------------------------------------------------ subject preparation

def _subject(kind, subject, store):
    if type(subject) is not dict or 'view' not in subject:
        raise ValueError(f'a {kind} request carries the run-state view it is decided on')
    allowed = {'view', 'checkin', 'gate', 'change', 'policy', 'conservative_default', 'request_pins',
               'inferred_critical_facts', 'obligations', 'machine_assumption'}
    extra = set(subject) - allowed
    if extra:
        raise ValueError('unknown request subject fields: ' + ', '.join(sorted(extra)))
    view = subject['view']
    if type(view) is not dict or view.get('run_id') != common.run_id(store):
        raise common.AuthorityRefused('the check-in view names a different run')
    return view


ASSUMPTION_KEYS = {'record', 'option', 'conditional', 'alternatives'}


def _machine_assumption(kind, value, default):
    """The machine assumption a question's default carries (``controller.graph`` assumptions), validated, or None.

    It names the store record of the governed judgment step that proposed it, the option it takes (the request's
    conservative default), whether the result is conditional on it (a physics-critical ambiguity) and the number of
    alternatives that step considered. Only a question carries one."""
    if value is None:
        return None
    if kind != 'escalation':
        raise ValueError('only a question carries a machine assumption')
    if (type(value) is not dict or set(value) != ASSUMPTION_KEYS or type(value['record']) is not str
            or not value['record'] or value['option'] != default or type(value['conditional']) is not bool
            or type(value['alternatives']) is not int or value['alternatives'] < 1):
        raise ValueError('a machine assumption names its record, the default option it takes, whether the result is '
                         'conditional on it and how many alternatives were considered')
    return deepcopy(value)


def _prepare(store, kind, subject, bounds):
    """Validated, rendered decision material; ``errors`` holds reasons to hold before asking."""
    supplied_view = _subject(kind, subject, store)
    try:
        snapshot = retained.current(store, kind)
    except common.AuthorityRefused as exc:
        return {'errors': [str(exc)]}
    view = snapshot['view']
    errors = []
    if supplied_view != view:
        errors.append('check-in view differs from authenticated retained plan and reading')
        # Keep precise section/flag diagnostics in addition to the independent comparison.
        try:
            errors += checkin_mod.validate(checkin_mod.render(kind, supplied_view), view)
            errors += checkin_mod.validate(checkin_mod.render(kind, supplied_view), supplied_view)
        except ValueError as exc:
            errors.append(str(exc))
    pins = view.get('pins') or {}
    if kind == 'approve_plan' and 'plan_sha256' not in pins:
        errors.append('CHECK-IN 1 binds the current plan digest (pin plan_sha256)')
    if kind == 'go':
        if 'approve_plan' not in pins:
            errors.append('CHECK-IN 2 binds the current CHECK-IN 1 authority record (pin approve_plan)')
        if not any(name.startswith('waypoint') for name in pins):
            errors.append('CHECK-IN 2 binds the executed waypoint evidence (waypoint pins)')
    if kind in ('deviation', 'final') and 'approve_plan' not in pins:
        errors.append(f'a {kind} check-in binds the current CHECK-IN 1 authority record (pin approve_plan)')
    change = subject.get('change')
    if kind == 'deviation':
        if (type(change) is not dict or set(change) != set(CHANGE_KEYS) or change['direction'] not in DIRECTIONS
                or any(type(change[k]) is not str or not change[k].strip() for k in ('parameter', 'why'))
                or type(change['touches']) is not list or not change['touches']):
            errors.append('a deviation states one exact parameter/from/to/why/touches/direction row')
    elif change is not None:
        raise ValueError('only a deviation carries a change row')
    policy = subject.get('policy')
    if kind == 'steering':
        if type(policy) is not dict or not policy:
            errors.append('a steering request carries the budgets and bounds it sets')
    elif policy is not None:
        raise ValueError('only a steering request carries a policy')
    obligations = subject.get('obligations', [])
    if (type(obligations) is not list or len(obligations) > 256 or len(set(obligations)) != len(obligations)
            or any(type(o) is not str or not o.strip() for o in obligations)):
        raise ValueError('obligations name distinct ledger rows (catalogue ids or instance keys)')
    if obligations and kind not in ('r3_action', 'steering', 'deviation', 'approve_plan'):
        raise ValueError(f'a {kind} decision cannot waive obligations')
    gate = subject.get('gate')
    if gate is not None and (kind != 'r3_action' or gate not in GATES_R3):
        raise ValueError('gate names unblind or spend_above_ceiling on an R3 action')
    options = view.get('options') or []
    default = subject.get('conservative_default')
    if default is not None:
        option = next((o for o in options if o.get('id') == default), None)
        if kind not in ('r3_action', 'escalation') or option is None:
            raise ValueError('a conservative default names one offered option of an R3 action or question')
        if gate in GATES_R3 and option.get('effect', True):
            raise ValueError(f'the conservative default of a {gate} decision cannot take its effect')
    assumption = _machine_assumption(kind, subject.get('machine_assumption'), default)
    try:
        artifact = checkin_mod.render(kind, view)
    except ValueError as exc:
        return {'errors': [str(exc)]}
    supplied = subject.get('checkin')
    if supplied is not None:
        errors += checkin_mod.validate(supplied, view)
    else:
        errors += checkin_mod.validate(artifact, view)
    if type(bounds) is not dict:
        raise ValueError('request bounds are an object (rung, stages, budget)')
    if set(bounds) - {'rung', 'stages', 'budget', 'policy'}:
        raise ValueError('request bounds hold rung, stages, budget and policy only')
    material = {'kind': kind, 'pins': artifact['pins'], 'checkin_sha256': artifact['sha256'],
                'gate': gate, 'change': deepcopy(change), 'policy': deepcopy(policy),
                'options': deepcopy(options), 'conservative_default': default,
                'request_pins': {**deepcopy(subject.get('request_pins') or {}),
                                 **deepcopy(snapshot['reading']['request_pins'])},
                'inferred_critical_facts': deepcopy(snapshot['reading']['inferred_critical_facts'])
                                           + deepcopy(subject.get('inferred_critical_facts') or []),
                'obligations': sorted(obligations), 'bounds': deepcopy(bounds)}
    if assumption is not None:
        # The default is a machine-reasoned assumption, not a plan-declared P7 default: the record names it so.
        material['machine_assumption'] = assumption
    if kind == 'approve_plan':
        from .rdj import classification
        # Class changes renew the subject even when the view pins did not change.
        material['approval_class'] = classification(store, material['pins'])[0]
    if kind == 'final' and getattr(store, 'run_dir', None) is not None:
        from .rdj import classification, final_action
        material['final_task_class'] = classification(store, material['pins'], 'final_task')[0]
        material['final_task_digest'] = final_action(material['pins'])['digest']
    if not errors:
        from .event_rows import validated
        validated(store, kind, artifact, snapshot['id'])
    # Render the structured decision payload itself; caller prose cannot hide the actual bounds.
    decision_text = checkin_mod.text(artifact) + '\nApproval bounds: ' + common.canonical(bounds) + '\n'
    if change is not None:
        decision_text += 'Exact change: ' + common.canonical(change) + '\n'
    if policy is not None:
        decision_text += 'Steering policy: ' + common.canonical(policy) + '\n'
    decision_text += 'Request comparisons: ' + common.canonical(material['request_pins']) + '\n'
    decision_text += 'Inferred critical facts: ' + common.canonical(material['inferred_critical_facts']) + '\n'
    if assumption is not None:
        decision_text += ('Machine assumption proposed by the governed judgment step (taken by the operator\'s '
                          'configured machine authority only if nobody answers within the wait bound; never a human '
                          'answer): ' + common.canonical(assumption) + '\n')
    if kind == 'approve_plan':
        decision_text += 'Computed approval class: ' + material['approval_class'] + '\n'
    if 'final_task_class' in material:
        decision_text += 'Computed final-task class: ' + material['final_task_class'] + '\n'
        decision_text += 'Exact final-task action: ' + material['final_task_digest'] + '\n'
    material['context_record'] = snapshot['id']
    return {'errors': errors, 'artifact': artifact, 'text': decision_text, 'material': material,
            'subject_sha256': common.digest(material), 'bounds': deepcopy(bounds)}


# ------------------------------------------------------------------ record helpers

def _authority_records(store):
    return [r for r in common.scan(store, common.AUTHORITY, common.SCHEMA) if r.get('run_id') == common.run_id(store)]


def _requests(store):
    return [r for r in common.scan(store, common.REQUESTS, common.REQUEST_SCHEMA)
            if r.get('run_id') == common.run_id(store)]


def _option(material, option):
    """The offered option ``option`` (None when it is not offered)."""
    return next((o for o in material.get('options') or [] if o.get('id') == option), None)


def _option_decision(kind, material, option):
    """The decision a chosen option records: an R3 option without its effect declines the action."""
    if kind != 'r3_action':
        return 'answer'
    chosen = _option(material, option)
    return 'approve' if chosen is not None and chosen.get('effect', True) is True else 'reject'


def _record(store, kind, prepared, mode, *, decision, label, source, evidence, option=None, comment=None,
            request=None):
    material = prepared['material']
    authorizes = decision in AUTHORIZING[kind] and kind != 'final'
    if label == common.LEGACY_TERMINAL:
        authorizes = False
    if option is not None:
        # An option without its effect (keep blinded, hold) authorizes nothing, whoever chose it.
        chosen = _option(material, option)
        authorizes = authorizes and chosen is not None and chosen.get('effect', True) is True
    body = {'schema': common.SCHEMA, 'schema_version': 1, 'uid': common.uid(), 'run_id': common.run_id(store),
            'kind': kind, 'decision': decision, 'option': option, 'comment': comment,
            'subject': {'pins': deepcopy(material['pins']), 'checkin_sha256': material['checkin_sha256'],
                        'gate': material['gate'], 'change': deepcopy(material['change']),
                        'obligations': list(material.get('obligations') or []),
                        'context_record': material['context_record']},
            'subject_sha256': prepared['subject_sha256'], 'bounds': deepcopy(prepared['bounds']),
            'source': source, 'label': label, 'evidence': evidence, 'request': request, 'reason': None,
            'mode_record': mode['id'], 'supersedes': None,
            'authorizes_effects': authorizes,
            'review_credit': False, 'human_identity_authenticated': False, 'time_ns': common.now_ns()}
    if kind == 'approve_plan':
        body['evidence'] = {**deepcopy(evidence), 'approval_class': material['approval_class']}
    if 'final_task_class' in material:
        body['evidence'] = {**deepcopy(evidence), **{k: material[k] for k in ('final_task_class', 'final_task_digest')}}
    if option is not None and _option(material, option).get('bounds') is not None:
        body['bounds'] = deepcopy(_option(material, option)['bounds'])
    previous = [r for r in _authority_records(store) if r['kind'] == kind and r.get('subject_sha256') != body['subject_sha256']]
    if previous:
        body['supersedes'] = previous[-1]['id']
    if kind == 'steering' and decision == 'approve':
        body['bounds'] = {**body['bounds'], 'policy': deepcopy(material['policy'])}
    return common.append(store, common.AUTHORITY, body)


def _resolution(store, kind, prepared):
    """An earlier decision of exactly this subject: a terminal answer, a machine decision, an
    operator answer to its pending request, or its recorded conservative default."""
    for record in reversed(_authority_records(store)):
        if record['kind'] == kind and record.get('subject_sha256') == prepared['subject_sha256']:
            return record
    return None


def _source(mode):
    return {'operator_ledger_root': 'operator_ledger_root', 'operator_ledger': 'operator_ledger'}.get(
        mode['operator_source'], 'operator_default')


# ------------------------------------------------------------------ escalation

def _utc(ns):
    return datetime.fromtimestamp(ns / 1e9, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _notify(mode, run, message):
    command = validate_argv(mode.get('notify_command'))
    if command is None:
        return {'status': 'disabled'}
    try:
        home = controller_home()
        completed = subprocess.run([*command, run, message], shell=False, timeout=10, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   cwd=home if home.is_dir() else None, check=False,
                                   env={k: os.environ[k] for k in ('PATH', 'LANG') if k in os.environ})
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'status': 'failed', 'error': type(exc).__name__}
    return {'status': 'sent' if completed.returncode == 0 else 'failed', 'returncode': completed.returncode}


def _pending(store, kind, prepared, mode, *, reason, needed, notify=True, answerable=False):
    """The pending request of this subject and wait (created once, notified once) as ``{"pending": ...}``.

    An explicit escalation is answerable through ``ravel operator answer``. A paused or
    stopped run waits for resume. Unattested terminal input requires explicit operator authority.
    """
    # Operator commands are authenticated by the external issuer in either frozen mode.
    # They never claim human identity and never enable automatic decisions in interactive mode.
    existing = next((r for r in reversed(_requests(store))
                     if r['kind'] == kind and r['subject_sha256'] == prepared['subject_sha256']
                     and r['needed'] == needed), None)
    if existing is None:
        code = common.nonce()
        since = common.now_ns()
        run = common.run_id(store)
        line = f'WAITING FOR A HUMAN since {_utc(since)}: {reason}, {needed}'
        answer = (f'answer with: ravel operator answer --run {run} --request <id> --code {code} --decision <decision>'
                  if answerable else needed)
        # The notification channel leaves the controller's host: it carries the run name and a state code only.
        notification = _notify(mode, run, f'WAITING_FOR_HUMAN {kind}') if notify else {'status': 'not_sent'}
        body = {'schema': common.REQUEST_SCHEMA, 'schema_version': 1, 'uid': common.uid(), 'run_id': run,
                'kind': kind, 'subject_sha256': prepared['subject_sha256'],
                'subject': deepcopy(prepared['material']), 'bounds': deepcopy(prepared['bounds']),
                'reason': reason, 'needed': needed, 'since_ns': since, 'answerable': answerable,
                'nonce_sha256': hashlib.sha256(code.encode()).hexdigest() if answerable else None,
                'notification': notification, 'mode_record': mode['id'],
                # The operator reads the check-in with ``ravel operator status``; the notification never carries it.
                'checkin_text': prepared['text'],
                'checkin_text_sha256': hashlib.sha256(prepared['text'].encode()).hexdigest()}
        existing = common.append(store, common.REQUESTS, body)
        print(line + ' -- ' + answer.replace('<id>', existing['id']), file=sys.stderr, flush=True)
    waited = (common.now_ns() - existing['since_ns']) / 1e9
    return {'pending': {'request': existing['id'], 'kind': kind, 'reason': existing['reason'],
                        'needed': existing['needed'], 'since_ns': existing['since_ns'], 'waited_seconds': waited,
                        'wait_bound_seconds': mode['wait_bound_seconds'],
                        'notification': existing['notification'], 'mode': mode['mode'],
                        'status_line': f'WAITING FOR A HUMAN since {_utc(existing["since_ns"])}: '
                                       f'{existing["reason"]}, {existing["needed"]}'}}


def _human_reasons(store, kind, prepared, mode, view):
    """Why an autonomous run cannot decide this by machine (empty when it can)."""
    material, bounds, reasons = prepared['material'], prepared['bounds'], []
    if view['revoked']:
        reasons.append('the operator revoked machine authority for this run')
    if kind == 'r3_action':
        reasons.append(f'R3 decision ({material["gate"] or "consequence class R3"})')
    if kind == 'approve_plan':
        from .rdj import classification
        cls, _ = classification(store, material['pins'])
        if cls == 'R3':
            reasons.append('R3 decision (approval action requires attested operator authority)')
    if material.get('final_task_class') == 'R3' and not _final_delegated(mode):
        reasons.append('R3 decision (final-task action requires renewed attested operator authority)')
    if kind == 'escalation':
        reasons.append('a question only a human can answer')
    from . import autonomy
    # The grant, its deadline and the run's boundaries are read again at every check-in: no machine decision is
    # taken under an expired, revoked, replaced or out-of-scope grant (N1).
    for row in autonomy.findings(store, include_pause=False):
        reasons.append(f'{row["code"]}: {row["reason"]}')
    if kind in ('approve_plan', 'go', 'deviation', 'final') and kind not in mode['machine_checkins']:
        reasons.append(f'the operator keeps {kind} for a human')
    change = material['change'] or {}
    if kind == 'deviation' and change.get('direction') in ('loosen', 'scope'):
        reasons.append('loosening a certification control or changing scope needs renewed exact authority')
    effective = mode_mod.effective_bounds(store)
    try:
        _check_limits(bounds, effective, operator=True)
    except common.AuthorityRefused as exc:
        reasons.append(str(exc))
    if kind == 'steering':
        try:
            widened = mode_mod.policy_widens(effective, material['policy'])
        except ValueError as exc:
            raise common.AuthorityRefused(str(exc)) from None
        if widened:
            reasons.append('steering widens ' + ', '.join(widened))
    plan = bounds.get('rung')
    if plan is not None and plan not in effective['bounds']['rungs']:
        reasons.append(f'compute plan {plan} is outside the operator bounds')
    stages = bounds.get('stages') or []
    if stages and not mode_mod._names_within(stages, effective['bounds']['allowed_stages']):
        reasons.append('stages outside the operator bounds')
    from .operator import NULLABLE_BUDGETS
    for key, value in (bounds.get('budget') or {}).items():
        limit = effective['budgets'].get(key, 0)
        if limit is None and key in NULLABLE_BUDGETS:
            continue
        if type(value) not in (int, float) or value != value or value < 0 or value > (limit or 0):
            reasons.append(f'budget {key}={value} exceeds the operator ceiling {limit}')
    pins = material['request_pins'] or {}
    for name, pair in pins.items():
        if type(pair) is not dict or set(pair) != {'requested', 'planned'}:
            raise ValueError('request_pins map a name to {requested, planned}')
        if pair['requested'] != pair['planned']:
            reasons.append(f'the plan changes the requested {name}')
    if material.get('obligations'):
        reasons.append('waiving ledger obligations needs the physicist or the operator: '
                       + ', '.join(material['obligations'])[:400])
    if material['inferred_critical_facts'] and not _conditional_approval(kind, mode):
        # Reasons reach the notification command, which receives no request text or scientific data:
        # the facts stay in the pending request in the store.
        reasons.append(f'inferred critical facts cannot become approved defaults '
                       f'({len(material["inferred_critical_facts"])} listed)')
    return reasons


def _escalate(store, kind, prepared, mode, reasons):
    needed = ('an operator answer' if mode['mode'] == 'autonomous' else 'the physicist at the controller terminal')
    default = prepared['material']['conservative_default']
    # A machine default never waives an obligation: a waiver waits for the physicist or the operator.
    waiver = bool(prepared['material'].get('obligations'))
    chosen = _option(prepared['material'], default)
    # R3/question status alone can default. All other escalation causes are hard holds
    # for an option with effects, including omitted facts and out-of-envelope resources.
    defaultable = all(r.startswith(('R3 decision (', 'a question only a human')) for r in reasons)
    if chosen is not None and chosen.get('effect', True):
        actual = chosen.get('bounds')
        if type(actual) is not dict or not {'rung', 'stages', 'budget'} <= actual.keys():
            defaultable = False
        else:
            try:
                _check_limits(actual, mode_mod.effective_bounds(store), operator=True, for_effect=True)
                _check_limits(actual, prepared['bounds'], for_effect=True)
            except common.AuthorityRefused:
                defaultable = False
    eligible = (chosen is not None and not waiver and not stop.control(store)['revoked']
                and (chosen.get('effect', True) is False or defaultable))
    assumption = prepared['material'].get('machine_assumption')
    if assumption is not None and not (mode['mode'] == 'autonomous' and 'assumption' in mode['machine_checkins']):
        # A machine-reasoned assumption is taken only under the operator's configured delegation; otherwise the
        # question waits for a human (the proposal stays visible in the check-in).
        eligible = False
    immediate = eligible and mode['r3_policy'] == 'conservative_default'
    # A default taken at once leaves nothing waiting for a human, so nobody is notified.
    pending = _pending(store, kind, prepared, mode, reason='; '.join(reasons), needed=needed, answerable=True,
                       notify=not immediate)
    elapsed = pending['pending']['waited_seconds']
    if eligible and (immediate or elapsed >= mode['wait_bound_seconds']):
        return _record(store, kind, prepared, mode, decision='default', option=default, label=common.MACHINE,
                       source=_source(mode), request=pending['pending']['request'],
                       evidence={'r3_policy': mode['r3_policy'], 'waited_seconds': elapsed,
                                 'wait_bound_seconds': mode['wait_bound_seconds'],
                                 'operator_entry': deepcopy(mode['operator_entry']), 'reasons': reasons,
                                 **({'machine_assumption': deepcopy(assumption)} if assumption is not None else {})})
    return pending


def _ask(store, kind, prepared, mode):
    from . import terminal
    options = [o['id'] for o in prepared['material']['options']]
    if kind in ('r3_action', 'escalation'):
        offered = options + ['reject']
    else:
        offered = [d for d in common.DECISIONS[kind] if d != 'default']
    timeout = mode['wait_bound_seconds'] or None
    try:
        answer = terminal.ask(prepared['text'], decisions=offered, timeout=timeout)
    except terminal.TerminalUnavailable as exc:
        return _pending(store, kind, prepared, mode, reason=str(exc),
                        needed='an authenticated operator answer or an unattested terminal response', answerable=True)
    except terminal.TerminalRefused as exc:
        return _pending(store, kind, prepared, mode, reason=str(exc),
                        needed='an authenticated operator answer or an unattested terminal response', answerable=True)
    chosen, option = answer['decision'], None
    if kind in ('r3_action', 'escalation') and chosen != 'reject':
        option, chosen = chosen, _option_decision(kind, prepared['material'], chosen)
    evidence = {'terminal': answer['device'], 'prompt_sha256': answer['prompt_sha256'],
                'nonce_sha256': answer['nonce_sha256'], 'response_sha256': answer['response_sha256'],
                'attempts': answer['attempts']}
    record = _record(store, kind, prepared, mode, decision=chosen, option=option, comment=answer['comment'],
                     label=common.LEGACY_TERMINAL, source='controller_terminal', evidence=evidence)
    if ((chosen in AUTHORIZING[kind]
         and (option is None or _option(prepared['material'], option).get('effect', True)))
            or (kind == 'final' and chosen == 'accept')):
        pending = _pending(store, kind, prepared, mode, reason='terminal identity is unattested; no approval granted',
                           needed='an authenticated operator answer', answerable=True)
        return {**pending, 'unattested_record': record['id']}
    return record


# ------------------------------------------------------------------ ordering

def _ordering_errors(store, kind, prepared):
    pins = prepared['material']['pins']
    if kind in ('go', 'deviation', 'final'):
        try:
            verify(store, pins.get('approve_plan', ''), kind='approve_plan')
        except (common.AuthorityRefused, KeyError) as exc:
            return [f'{kind} needs the current CHECK-IN 1 authority first: {exc}']
    if kind == 'final' and 'go' in pins:
        try:
            verify(store, pins['go'], kind='go')
        except (common.AuthorityRefused, KeyError) as exc:
            return [f'the final check-in names a CHECK-IN 2 GO that is not current: {exc}']
    return []


# ------------------------------------------------------------------ public API

def request(store, kind, subject, bounds):
    """Grant authority for one decision, or say what it waits for.

    Returns an ``authority-record.v1`` (with ``id``) or ``{"pending": {...}}``. Raises
    ``AuthorityRefused`` for a request the graph should never make (wrong run, skipped or
    reordered check-in). A check-in that fails validation holds before any assent is solicited.
    """
    register_ledger_reader()
    kind = common.kind_of(kind)
    if kind in common.CONTROLS:
        return _terminal_control(store, kind, subject)
    mode = mode_mod.frozen(store)
    prepared = _prepare(store, kind, subject, bounds or {})
    if 'artifact' not in prepared or prepared['errors']:
        return {'pending': {'request': None, 'kind': kind, 'reason': 'check-in incomplete',
                            'needed': 'a complete typed check-in rendered from current run state',
                            'errors': prepared['errors'], 'mode': mode['mode']}}
    view = stop.control(store)
    if view['state'] != 'running':
        return _pending(store, kind, prepared, mode, reason=f'the run is {view["state"].replace("_", " ")}',
                        needed='the operator or the physicist to resume the run', notify=False)
    resolved = _resolution(store, kind, prepared)
    if resolved is not None:
        try:
            _current_record(store, resolved)
            if (resolved['label'] == common.LEGACY_TERMINAL
                    and ((resolved['decision'] in AUTHORIZING[kind]
                          and (resolved.get('option') is None
                               or _option(prepared['material'], resolved['option']).get('effect', True)))
                         or (kind == 'final' and resolved['decision'] == 'accept'))):
                pending = _pending(store, kind, prepared, mode,
                                   reason='terminal identity is unattested; no approval granted',
                                   needed='an authenticated operator answer', answerable=True)
                return {**pending, 'unattested_record': resolved['id']}
            if resolved['authorizes_effects']:
                verify(store, resolved['id'], kind=kind)
                _check_limits(resolved['bounds'], mode_mod.effective_bounds(store), operator=True)
            if kind == 'final':
                _final_class(store, resolved)
            return resolved
        except common.AuthorityRefused:
            return _pending(store, kind, prepared, mode, reason='the previous decision is no longer current',
                            needed='renewed authority on the current scope', notify=False)
    order = _ordering_errors(store, kind, prepared)
    if order:
        raise common.AuthorityRefused('; '.join(order))
    if mode['mode'] == 'physicist-in-the-loop':
        return _ask(store, kind, prepared, mode)
    reasons = _human_reasons(store, kind, prepared, mode, view)
    if reasons:
        return _escalate(store, kind, prepared, mode, reasons)
    label = common.DELEGATED if mode['delegation'] == 'request_stated' else common.MACHINE
    source = 'request_delegation' if label == common.DELEGATED else _source(mode)
    evidence = {'mode_record': mode['id'], 'operator_entry': deepcopy(mode['operator_entry']),
                'request_statement': deepcopy(mode['request_statement']),
                'checkin_sha256': prepared['material']['checkin_sha256']}
    if prepared['material'].get('final_task_class') == 'R3':
        # Only the operator's configured R3 delegation reaches here (``_human_reasons``); the record names it.
        evidence['r3_delegation'] = 'final_task'
    if kind == 'approve_plan' and prepared['material']['inferred_critical_facts']:
        # Only a conditional approval reaches here (``_conditional_approval``): the facts stay inferred, not approved.
        evidence['conditional_on'] = deepcopy(prepared['material']['inferred_critical_facts'])
    record = _record(store, kind, prepared, mode, decision=common.POSITIVE[kind], label=label, source=source,
                     evidence=evidence)
    if kind == 'deviation':
        # A course change is disclosed at once, even when the operator's bounds let the machine approve it.
        # The notification names the record only; its change row is read from the store (``deviations``).
        _notify(mode, common.run_id(store), 'DEVIATION_RECORDED')
    return record


def _terminal_control(store, kind, subject):
    """Stop, pause, resume or revoke asked at the controller terminal (the operator CLI writes its own)."""
    from . import terminal
    reason = (subject or {}).get('reason') if isinstance(subject, dict) else None
    if type(reason) is not str or not reason.strip():
        raise ValueError(f'a {kind} request states its reason')
    try:
        answer = terminal.ask(f'Confirm {kind} of run {common.run_id(store)}: {reason}\n', decisions=['confirm', 'cancel'])
    except (terminal.TerminalUnavailable, terminal.TerminalRefused) as exc:
        return {'pending': {'request': None, 'kind': kind, 'reason': str(exc),
                            'needed': f'`ravel operator {kind} --run {common.run_id(store)}` or the controller terminal'}}
    if answer['decision'] != 'confirm':
        return {'pending': {'request': None, 'kind': kind, 'reason': 'cancelled at the terminal', 'needed': 'nothing'}}
    if kind == 'resume':
        return {'pending': {'request': None, 'kind': kind, 'reason': 'terminal identity is unattested',
                            'needed': 'an authenticated operator resume command'}}
    return stop.record_control(store, kind, label=common.LEGACY_TERMINAL, source='controller_terminal', reason=reason,
                               evidence={'terminal': answer['device'], 'prompt_sha256': answer['prompt_sha256'],
                                         'nonce_sha256': answer['nonce_sha256']})


def _current_record(store, record):
    stop.check(store, 'authority read')
    rows = [r for r in _authority_records(store) if r['kind'] == record['kind']]
    if not rows or rows[-1]['id'] != record['id']:
        raise common.AuthorityRefused('authority was superseded by a later decision')
    if record['label'] in (common.MACHINE, common.DELEGATED) and stop.control(store)['revoked']:
        raise common.AuthorityRefused('machine authority was revoked')
    if record.get('mode_record') != mode_mod.frozen(store)['id']:
        raise common.AuthorityRefused('authority belongs to another mode epoch')
    context_id = record.get('subject', {}).get('context_record')
    if context_id != retained.current(store, record['kind'])['id']:
        raise common.AuthorityRefused('authority belongs to a superseded plan or reading epoch')
    pins = record.get('subject', {}).get('pins', {})
    if record['kind'] in ('go', 'deviation', 'final'):
        verify(store, pins.get('approve_plan', ''), kind='approve_plan')
    if record['kind'] == 'go':
        history = _authority_records(store)
        index = next(i for i, r in enumerate(history) if r['id'] == record['id'])
        if any(r['kind'] == 'deviation' and r['decision'] == 'approve' and r['authorizes_effects']
               for r in history[index + 1:]):
            raise common.AuthorityRefused('a later approved amendment invalidated this GO')


def disposition(store, record_id, *, kind, subject):
    """Authenticate a current decision and its pins without granting or exercising effects.

    Unlike ``verify``, this accepts non-authorizing decisions, including a final disposition.
    An unattested terminal response remains evidence only and cannot pass this gate.
    """
    kind = common.kind_of(kind)
    if type(record_id) is not str or not record_id:
        raise common.AuthorityRefused(f'no {kind} authority record named')
    try:
        record = common.read(store, common.AUTHORITY, record_id, common.SCHEMA)
    except KeyError:
        raise common.AuthorityRefused(f'{kind} authority {record_id!r} is not in the controller store') from None
    if record.get('run_id') != common.run_id(store):
        raise common.AuthorityRefused('the authority record belongs to a different run')
    if record.get('kind') != kind:
        raise common.AuthorityRefused(f'record {record_id} is {record.get("kind")} authority, not {kind}')
    if kind in common.CONTROLS:
        if stop.control(store)['record'] != record['id']:
            raise common.AuthorityRefused('control authority was superseded by a later control')
    else:
        _current_record(store, record)
    if record.get('label') == common.TERMINAL:
        raise common.AuthorityRefused('human terminal attestation is unavailable on this platform')
    if record.get('label') not in common.LABELS:
        raise common.AuthorityRefused('the unattested authority label authorizes nothing')
    if subject is not None:
        bound = (record.get('subject') or {})
        if kind not in common.CONTROLS:
            bound = bound.get('pins') or {}
        if type(subject) is not dict:
            raise ValueError('current pins are an object')
        for name, value in subject.items():
            if bound.get(name) != value:
                raise common.AuthorityRefused(f'{kind} authority {record_id} is stale: pin {name} changed')
    if record['label'] in (common.MACHINE, common.DELEGATED):
        view = stop.control(store)
        if view['revoked']:
            raise common.AuthorityRefused('machine authority for this run was revoked by the operator')
    if kind == 'final':
        _final_class(store, record)
    return record


def _conditional_approval(kind, mode):
    """Whether a plan approval may proceed CONDITIONAL on facts the intake inferred as physics-critical: autonomous mode
    with the operator's ``assumption`` delegation. The facts are never approved as fact: the machine record names them
    (``conditional_on``) and every result of the run is labelled conditional on them."""
    return kind == 'approve_plan' and mode.get('mode') == 'autonomous' and 'assumption' in (mode.get('machine_checkins')
                                                                                            or ())


def _final_delegated(mode):
    """Whether the frozen mode delegates acceptance of an R3 final task to machine authority (operator-configured)."""
    return (mode.get('mode') == 'autonomous' and 'final_task' in (mode.get('r3_delegation') or ())
            and 'final' in (mode.get('machine_checkins') or ()))


def delegated_final(store, record):
    """Whether ``record`` is a machine acceptance of the current R3 final task under the frozen R3 delegation.

    The record must be the machine label of this run's frozen mode, name the delegation, and carry the R3 class and
    the exact digest of the final-task action recomputed now: an older record, a lower class or another action never
    passes.
    """
    from .rdj import classification, final_action
    mode = mode_mod.frozen(store)
    evidence = record.get('evidence') or {}
    pins = (record.get('subject') or {}).get('pins') or {}
    return (record.get('label') == common.MACHINE and record.get('kind') == 'final' and _final_delegated(mode)
            and record.get('mode_record') == mode['id'] and evidence.get('mode_record') == mode['id']
            and evidence.get('r3_delegation') == 'final_task' and evidence.get('final_task_class') == 'R3'
            and classification(store, pins, 'final_task')[0] == 'R3'
            and evidence.get('final_task_digest') == final_action(pins)['digest'])


def _final_class(store, record):
    """Recompute final-task class; old machine or lower-class answers cannot be reused at R3.

    At R3 the acceptance is renewed attested operator authority for the exact action, or a machine acceptance of
    that exact action under the operator's configured R3 delegation (``delegated_final``).
    """
    if getattr(store, 'run_dir', None) is None or record.get('decision') != 'accept':
        return
    from .rdj import classification, final_action
    pins = record['subject']['pins']
    cls, _ = classification(store, pins, 'final_task')
    if cls != 'R3' or delegated_final(store, record):
        return
    if (record['label'] != common.OPERATOR_COMMAND
            or record['evidence'].get('final_task_class') != 'R3'
            or record['evidence'].get('final_task_digest') != final_action(pins)['digest']):
        raise common.AuthorityRefused('R3 final task requires renewed attested operator authority for its exact action')


def verify(store, record_id, *, kind, subject=None):
    """Return a current authorizing record, refusing final or negative dispositions."""
    kind = common.kind_of(kind)
    record = disposition(store, record_id, kind=kind, subject=subject)
    if record.get('decision') not in AUTHORIZING.get(kind, ()) or not record.get('authorizes_effects'):
        raise common.AuthorityRefused(f'{kind} record {record_id} decided {record.get("decision")!r}, which authorizes nothing')
    if kind == 'approve_plan':
        from .rdj import classification
        cls, _ = classification(store, record['subject']['pins'])
        if cls == 'R3':
            if record['label'] != common.OPERATOR_COMMAND:
                raise common.AuthorityRefused('R3 approval requires attested operator authority')
            if record['evidence'].get('approval_class') != 'R3':
                raise common.AuthorityRefused('R3 approval requires renewed attested authority for its current class')
    _check_limits(record['bounds'], mode_mod.effective_bounds(store), operator=True)
    return record


def current(store, kind, subject=None):
    """The latest record authorizing ``kind`` for the current ``subject`` pins, or None."""
    kind = common.kind_of(kind)
    for record in reversed(_authority_records(store)):
        if record['kind'] != kind:
            continue
        bound = (record.get('subject') or {}).get('pins') or {}
        if subject is not None and any(bound.get(k) != v for k, v in subject.items()):
            continue
        try:
            return verify(store, record['id'], kind=kind, subject=subject)
        except common.AuthorityRefused:
            return None
    return None


def _plan_authority(store, pins, depth=64):
    """Current plan authority, retaining prior amendments only as authenticated lineage.

    Historical amendments cannot authorize old effects. They remain necessary evidence for
    the current amendment's ancestry and for intersection of all approved resource bounds.
    """
    ci1 = current(store, 'approve_plan')
    if ci1 is None:
        return None, None
    rows = [r for r in _authority_records(store) if r['kind'] == 'deviation'
            and r['subject'].get('pins', {}).get('approve_plan') == ci1['id']]
    approved = [r for r in rows if r['decision'] == 'approve' and r['authorizes_effects']]
    if not approved:
        bound = ci1['subject']['pins']
        return (ci1, None) if all(bound.get(k) == v for k, v in pins.items()) else (None, None)
    renewal = current(store, 'deviation')
    if renewal is None or renewal['id'] != approved[-1]['id']:
        return None, None
    active = {**ci1['subject']['pins'], **renewal['subject']['pins']}
    if any(active.get(k) != v for k, v in pins.items()):
        return None, None
    step, lineage, seen = renewal, [], set()
    for _ in range(depth):
        if step['id'] in seen or step['label'] not in common.LABELS or step['label'] == common.TERMINAL:
            return None, None
        if step['mode_record'] != ci1['mode_record']:
            return None, None
        seen.add(step['id'])
        lineage.append(step['bounds'])
        found_pins = step['subject']['pins']
        # The controller's deviation view names the plan it amends as ``approved_plan_sha256``.
        previous = found_pins.get('previous_plan_sha256') or found_pins.get('approved_plan_sha256')
        if previous == ci1['subject']['pins'].get('plan_sha256'):
            return ci1, {**renewal, '_lineage_bounds': lineage}
        earlier = approved[:next(i for i, r in enumerate(approved) if r['id'] == step['id'])]
        step = next((r for r in reversed(earlier) if r['subject']['pins'].get('plan_sha256') == previous), None)
        if step is None:
            return None, None
    return None, None


def plan_authority(store, pins):
    """Return ``(CHECK-IN 1, current amendment or None)`` for an authenticated plan chain.

    Missing, stale or broken lineage returns ``(None, None)``; amendments carry their
    intersecting ``_lineage_bounds``. This lookup does not authorize a new effect.
    """
    if type(pins) is not dict or not pins.get('plan_sha256'):
        raise ValueError('plan authority needs current plan pins')
    return _plan_authority(store, pins)


def read_authority(store, record_id):
    """Authenticated, current authorizing reader for the ledger's waiver hook."""
    try:
        record = common.read(store, common.AUTHORITY, record_id, common.SCHEMA)
    except KeyError:
        raise common.AuthorityRefused(f'authority {record_id!r} is not in the controller store') from None
    return verify(store, record['id'], kind=record['kind'])


def register_ledger_reader():
    """Explicit composition hook; return false until the ledger reader hook is installed."""
    from ravel.controller.graph import service
    register = getattr(service('ledger'), 'register_authority_reader', None)
    if register is None:
        return False
    register(read_authority)
    return True


def ledger_evidence(store):
    """Mechanism evidence from authenticated authority records, without importing the ledger.

    A frozen mode proves the external configuration and retained-history boundary. Steering,
    terminal, R3, stop and deviation rows need their corresponding executed record; their
    absence is not evidence of execution. These references grant no effects or review credit.
    """
    mode = mode_mod.frozen(store)
    history = _authority_records(store)
    requests = _requests(store)
    observations = common.scan(store, common.OBSERVATIONS, common.OBSERVATION_SCHEMA)
    mode_mod.effective_bounds(store)
    stop.control(store)
    evidence = {row: {'authority': mode['id']} for row in ('A02', 'A03', 'C09', 'SW01', 'SW02')}

    def cite(rows, record):
        for row in rows:
            evidence[row] = {'authority': record['id']}

    for record in history:
        kind = record['kind']
        if (record.get('label') == common.LEGACY_TERMINAL
                and record.get('source') == 'controller_terminal' and not record.get('authorizes_effects')):
            cite(('CT07',), record)
        if kind in common.CONTROLS:
            cite(('A10', 'G06', 'B05', 'C40', 'SW05'), record)
        if record.get('mode_record') != mode['id'] or record.get('label') not in common.LABELS:
            continue
        if kind == 'steering' and record.get('decision') == 'approve' and record.get('authorizes_effects'):
            cite(('C37', 'C38', 'C39', 'SW03'), record)
        if kind == 'r3_action' and record.get('subject', {}).get('gate') in GATES_R3:
            cite(('A11', 'G11'), record)
        change = record.get('subject', {}).get('change')
        if (kind == 'deviation' and record.get('decision') == 'approve' and record.get('authorizes_effects')
                and type(change) is dict and set(change) == set(CHANGE_KEYS)):
            cite(('A09', 'C20', 'C21', 'C32'), record)
    for record in requests:
        if (record.get('mode_record') == mode['id'] and record['kind'] == 'r3_action'
                and record.get('subject', {}).get('gate') in GATES_R3):
            cite(('A11', 'G11'), record)
    for record in observations:
        if record.get('control') in {r['id'] for r in history if r['kind'] in common.CONTROLS}:
            cite(('B05', 'C40', 'SW05'), record)
    return evidence


def _effect_branch(store, effect, approval):
    """The approved step's declared branch, never a caller-supplied classification.

    An amendment's retained plan is the current one. Missing, ambiguous or untyped
    step declarations cannot narrow approved bounds; historical callers stay full-scope.
    """
    from ..step import spec
    context = common.read(store, retained.KIND, approval['subject']['context_record'], retained.SCHEMA)
    plan = context['plan']
    if plan.get('sha256') != (effect.get('pins') or {}).get('plan_sha256'):
        return None
    steps = [step for step in plan.get('steps', [])
             if type(step) is dict and step.get('id') == effect.get('id')]
    if len(steps) != 1 or steps[0].get('kind') not in spec.KINDS:
        return None
    return spec.branch(steps[0])


def _check_limits(effect, limits, *, operator=False, for_effect=False, branch=None):
    """Apply restrictions by presence: an explicit empty set grants no scope."""
    from .operator import RUNGS, BUDGET_KEYS, _number, budget_integer
    rung = effect.get('rung', effect.get('plan'))
    if operator:
        scope, budgets = limits['bounds'], limits['budgets']
        if rung is not None and rung not in scope['rungs']:
            raise common.AuthorityRefused('effect rung is outside current operator/steering bounds')
        stages = scope['allowed_stages']
    else:
        budgets = limits.get('budget', {})
        approved = limits.get('rung')
        if approved is not None and (rung not in RUNGS or approved not in RUNGS
                                    or RUNGS.index(rung) > RUNGS.index(approved)):
            raise common.AuthorityRefused('effect exceeds the approved compute rung')
        stages = limits.get('stages', ['*'])
    wanted = effect.get('stages', [effect['stage']] if 'stage' in effect else [])
    if (type(wanted) is not list or type(stages) is not list or not mode_mod._names_within(wanted, stages)
            or (for_effect and '*' not in stages and not wanted)):
        raise common.AuthorityRefused('effect stages are outside approved bounds')
    if for_effect and not operator:
        required = {key for key in budgets if branch not in RESOURCE_BRANCHES
                    or key not in RESOURCE_CONSUMERS or branch in RESOURCE_CONSUMERS[key]}
        if required - set(effect.get('budget') or {}):
            raise common.AuthorityRefused('effect omits an explicitly approved resource budget')
    for key, value in (effect.get('budget') or {}).items():
        if key not in BUDGET_KEYS or not _number(value, integer=budget_integer(key)):
            raise common.AuthorityRefused('effect budget must use known finite nonnegative resources')
        if key in budgets and budgets[key] is not None and value > budgets[key]:
            raise common.AuthorityRefused(f'effect budget {key}={value} exceeds the ceiling {budgets[key]}')
    stage_wall = budgets.get('stage_wall_seconds') if operator else None
    wall = (effect.get('budget') or {}).get('wall_seconds')
    if stage_wall is not None and type(wall) in (int, float) and wall > stage_wall:
        # One effect's own driver wall time; a batch launch's job time is counted in batch_cpu_hours instead.
        raise common.AuthorityRefused(f'effect wall_seconds={wall} exceeds the per-stage ceiling {stage_wall}')


def authorize_effect(store, effect):
    """Check the authority for one effect before it starts; raise ``AuthorityRefused`` when absent.

    ``effect``: ``rung`` (none, dry, smoke, pilot, full, scan; ``plan`` is accepted as an alias), ``pins`` (current plan pins,
    at least ``plan_sha256``), ``go_pins`` (current waypoint pins for full and scan),
    ``requires_go`` (false only for routes without CHECK-IN 2), ``stage``, ``budget`` and an
    optional ``started_ns`` (a GO never authorizes an effect that started before it).
    """
    from .operator import RUNGS
    if type(effect) is not dict:
        raise ValueError('an effect is an object')
    stop.check(store, f'effect {effect.get("id", "")}'.strip())
    from . import autonomy
    # Every launch admission reads the grant again: an edited, replaced, revoked or expired grant, a deadline
    # margin reached or a wait for a human refuses the effect before it starts (N1, N2, N7).
    autonomy.admit(store, f'effect {effect.get("id", "")}'.strip())
    plan = effect.get('rung', effect.get('plan'))
    if 'rung' in effect and 'plan' in effect and effect['rung'] != effect['plan']:
        raise common.AuthorityRefused('the effect names two different rungs; nothing started')
    if plan not in RUNGS:
        raise common.AuthorityRefused('an effect names its rung (' + ', '.join(RUNGS) + '); nothing started')
    result = {'approve_plan': None, 'go': None, 'labels': [], 'mode_record': mode_mod.frozen(store)['id']}
    effective = mode_mod.effective_bounds(store)
    _check_limits(effect, effective, operator=True, for_effect=True)
    if plan in ('none', 'dry'):
        return result
    pins = effect.get('pins') or {}
    if 'plan_sha256' not in pins:
        raise common.AuthorityRefused('an effect names the current plan digest it executes')
    ci1, renewal = _plan_authority(store, pins)
    if ci1 is None:
        raise common.AuthorityRefused(f'{plan} refused: no current CHECK-IN 1 authority for this plan; nothing started')
    order = {name: i for i, name in enumerate(RUNGS)}
    approved = (ci1.get('bounds') or {}).get('rung')
    if approved is None or order[plan] > order.get(approved, -1):
        raise common.AuthorityRefused(f'{plan} exceeds the approved compute plan {approved}')
    branch = _effect_branch(store, effect, renewal or ci1)
    _check_limits(effect, ci1['bounds'], for_effect=True, branch=branch)
    result['approve_plan'] = ci1['id']
    result['labels'].append(ci1['label'])
    if renewal is not None:
        for limits in renewal['_lineage_bounds']:
            _check_limits(effect, limits, for_effect=True, branch=branch)
        result['deviation'] = renewal['id']
        result['labels'].append(renewal['label'])
    if plan in ('full', 'scan') and effect.get('requires_go', True) is not False:
        go = current(store, 'go', {**(effect.get('go_pins') or {}), 'approve_plan': ci1['id']})
        if go is None:
            raise common.AuthorityRefused(f'{plan} refused: no current CHECK-IN 2 GO bound to this approval and the '
                                          'executed waypoint evidence; nothing started')
        amended = [r for r in _authority_records(store) if r['kind'] == 'deviation' and r['decision'] == 'approve'
                   and r['time_ns'] > go['time_ns']]
        if amended:
            raise common.AuthorityRefused('an approved amendment invalidated the CHECK-IN 2 GO; a new GO on the '
                                          'current waypoint evidence is required')
        started = effect.get('started_ns')
        if started is not None and go['time_ns'] > started:
            raise common.AuthorityRefused('a GO recorded after an effect started cannot authorize it retrospectively')
        _check_limits(effect, go['bounds'], for_effect=True, branch=branch)
        result['go'] = go['id']
        result['labels'].append(go['label'])
    return result


def answer(store, request_id, code, decision, *, text=''):
    """The operator's answer to a pending request (``ravel operator answer``), labelled ``operator_command``.

    The operator must possess the issuer key outside workers and quote the retained request's
    code. This explicit command also lets an interactive run continue when its terminal input
    is unattested; it is never labelled as a human response.
    """
    from ravel.workflow.approval_authority import AGENT_MARKERS
    present = [name for name in AGENT_MARKERS if name in os.environ]
    if present:
        raise common.AuthorityRefused(f'an operator answer is refused in an agent session ({present[0]})')
    stop.check(store, 'operator answer')
    mode = mode_mod.frozen(store)
    try:
        pending = common.read(store, common.REQUESTS, request_id, common.REQUEST_SCHEMA)
    except KeyError:
        raise common.AuthorityRefused(f'no pending request {request_id!r} in this run') from None
    if pending.get('answerable') is not True or not pending.get('nonce_sha256'):
        raise common.AuthorityRefused('this request waits for the run to resume or for the controller terminal; '
                                      'it takes no operator answer')
    if hashlib.sha256(str(code).strip().upper().encode()).hexdigest() != pending['nonce_sha256']:
        raise common.AuthorityRefused('the answer does not quote the code of this request; nothing was recorded')
    kind = pending['kind']
    context = retained.current(store, kind)
    if pending['subject'].get('context_record') != context['id']:
        raise common.AuthorityRefused('pending request belongs to a superseded plan or reading')
    if any(r.get('subject_sha256') == pending['subject_sha256'] and r['kind'] == kind
           and r['label'] != common.LEGACY_TERMINAL for r in _authority_records(store)):
        raise common.AuthorityRefused('this request is already decided')
    options = [o['id'] for o in pending['subject'].get('options') or []]
    option = None
    if kind in ('r3_action', 'escalation'):
        if decision != 'reject' and decision not in options:
            raise common.AuthorityRefused('answer with one of the offered options or reject: ' + ', '.join(options))
        if decision != 'reject':
            option, decision = decision, _option_decision(kind, pending['subject'], decision)
    elif decision not in [d for d in common.DECISIONS[kind] if d != 'default']:
        raise common.AuthorityRefused(f'{decision!r} is not a decision of a {kind} request')
    prepared = {'material': pending['subject'], 'subject_sha256': pending['subject_sha256'], 'bounds': pending['bounds']}
    if decision in AUTHORIZING[kind] and (option is None or _option(pending['subject'], option).get('effect', True)):
        _check_limits(pending['bounds'], mode_mod.effective_bounds(store), operator=True)
    evidence = {'request': pending['id'], 'operator_uid': os.getuid(),
                'tty': os.ttyname(0) if os.isatty(0) else None, 'pid': os.getpid()}
    return _record(store, kind, prepared, mode, decision=decision, option=option, comment=text or None,
                   label=common.OPERATOR_COMMAND, source='operator_cli', evidence=evidence, request=pending['id'])


def notify(store, message):
    """Send one line through the operator's notification command frozen at intake (bounded endings,
    escalations); returns the delivery status. It reports; it never approves or resumes. The line
    carries no request text, findings or scientific data (the notification command's contract)."""
    if type(message) is not str or not message.strip():
        raise ValueError('a notification states its message')
    return _notify(mode_mod.frozen(store), common.run_id(store), ' '.join(message.split())[:4000])


def records(store):
    """Every authority record of the run, for the receipt (ids, kinds, labels, decisions).

    A plan approval given conditional on facts the intake inferred also carries those recorded facts
    (``evidence.conditional_on``, exactly as recorded), so every reader can label the results conditional on them.
    No other evidence is projected.
    """
    rows = []
    for r in _authority_records(store):
        row = {k: r.get(k) for k in ('id', 'uid', 'kind', 'decision', 'option', 'label', 'source', 'time_ns',
                                     'authorizes_effects', 'request')}
        evidence = r.get('evidence') if type(r.get('evidence')) is dict else {}
        if 'conditional_on' in evidence:
            row['evidence'] = {'conditional_on': deepcopy(evidence['conditional_on'])}
        rows.append(row)
    return rows


def deviations(store):
    """Every deviation decision with its exact change row, for the user-visible disclosure."""
    return [{'id': r['id'], 'decision': r['decision'], 'label': r['label'], 'change': r['subject'].get('change'),
             'time_ns': r['time_ns']} for r in _authority_records(store) if r['kind'] == 'deviation']
