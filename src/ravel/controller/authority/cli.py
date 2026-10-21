"""``ravel operator``: the operator's configuration and run controls, outside every worker.

``init`` and ``set`` write the operator ledger (mode, budgets, R3 policy, wait bound,
notification command, unconfined policy, store root); ``show`` prints the effective
configuration. ``stop``, ``pause``, ``resume`` and ``revoke`` write a control record into one
run's protected store; ``stop`` and ``revoke`` then cancel the run's own journalled batch jobs
and verify each ended (exit status 3 when one is not verified ended; running the stop again is
safe). ``answer`` resolves an escalation of an autonomous run, quoting the code of its pending
request. Agent sessions are refused. Nothing here approves a physicist decision.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import common, operator as ledger


def _assignments(rows, kind):
    """``KEY=VALUE`` pairs; values parse as JSON when they can (numbers, null, lists)."""
    result = {}
    for row in rows or []:
        key, sep, value = row.partition('=')
        if not sep or not key:
            raise ValueError(f'{kind} takes KEY=VALUE, not {row!r}')
        try:
            result[key] = json.loads(value)
        except ValueError:
            result[key] = value
    return result


def _bounds(args):
    bounds = {}
    if args.rungs:
        bounds['rungs'] = [p for p in args.rungs.split(',') if p]
    if args.stages:
        bounds['allowed_stages'] = [s for s in args.stages.split(',') if s]
    return bounds


def _notify(value):
    if value is None:
        return None
    command = json.loads(value)
    return ledger.validate_argv(command)


def _nonnegative_integer(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError('must be an integer greater than or equal to zero')
    return number


def _common_settings(parser, *, initial):
    if initial:
        parser.add_argument('--mode', required=True, choices=common.MODES)
    else:
        parser.add_argument('--mode', choices=common.MODES)
    parser.add_argument('--budget', action='append', metavar='KEY=VALUE',
                        help='budget envelope: ' + ', '.join(ledger.BUDGET_KEYS))
    parser.add_argument('--rungs', help='comma list of machine-delegable rungs: ' + ', '.join(ledger.RUNGS))
    parser.add_argument('--stages', help='comma list of machine-delegable stages or operations (* for any)')
    parser.add_argument('--machine-checkins', help='comma list of check-ins the machine may resolve in autonomous mode')
    parser.add_argument('--r3-policy', choices=common.R3_POLICIES)
    parser.add_argument('--wait-bound', type=int, metavar='SECONDS')
    parser.add_argument('--notify-command', metavar='JSON_ARGV', help='e.g. \'["/usr/local/bin/notify"]\'')
    parser.add_argument('--allow-unconfined', choices=('true', 'false'))
    parser.add_argument('--allow-request-delegation', choices=('true', 'false'))
    parser.add_argument('--store-root')
    parser.add_argument('--harness', metavar='JSON')
    parser.add_argument('--engagement', metavar='JSON')
    parser.add_argument('--compute-policy', metavar='JSON', help='operator cost tolerance: bounded, generous or adaptive')
    parser.add_argument('--restricted-sources', metavar='ABSOLUTE_PATH_OR_NULL')
    parser.add_argument('--remote-job-ceiling', type=_nonnegative_integer)
    parser.add_argument('--procedure-byte-ceiling', type=_nonnegative_integer)
    parser.add_argument('--agent-preferences', metavar='JSON')
    parser.add_argument('--site-resource-ceilings', metavar='JSON')
    parser.add_argument('--expires-at', metavar='UTC_TIME_OR_null',
                        help='when the grant ends, YYYY-MM-DDTHH:MM:SSZ (null: no expiry)')
    parser.add_argument('--project-scope', metavar='PATHS_OR_null',
                        help='comma list of absolute project paths the grant covers (null: any)')
    parser.add_argument('--deadline', metavar='UTC_TIME_OR_null', help='the runs\' deadline, YYYY-MM-DDTHH:MM:SSZ')
    parser.add_argument('--deadline-margin', type=_nonnegative_integer, metavar='SECONDS',
                        help='stop new work this long before the deadline (with --deadline)')
    parser.add_argument('--instruction-document', metavar='ABSOLUTE_PATH_OR_null',
                        help='the project instruction document pinned for every agent of every run')
    parser.add_argument('--r3-delegation', metavar='NAMES',
                        help='comma list of R3 decisions the machine may take in autonomous mode: '
                             + ', '.join(ledger.R3_DELEGATIONS) + ' (empty: none)')
    parser.add_argument('--review-sandbox-fallback', choices=ledger.REVIEW_SANDBOX_FALLBACKS,
                        help='review seats where the OS worker sandbox cannot run them: none (hold) or '
                             'restricted-unsandboxed (run the broker-only reviewer unconfined, labelled; the '
                             'delivery stays qualified)')
    parser.add_argument('--disk-free-floor', type=_nonnegative_integer, metavar='BYTES',
                        help='wait for a human when free space falls below this many bytes')


def parser():
    ap = argparse.ArgumentParser(prog='ravel operator', description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='command', required=True)
    _common_settings(sub.add_parser('init', help='write the first operator configuration'), initial=True)
    _common_settings(sub.add_parser('set', help='change the operator configuration (later runs only)'), initial=False)
    sub.add_parser('show', help='print the effective operator configuration and its source')
    for name, text in (('stop', 'drain a run to its bounded ending'), ('pause', 'drain a run and wait'),
                       ('resume', 'resume a stopped or paused run'), ('revoke', 'withdraw machine authority and stop')):
        control = sub.add_parser(name, help=text)
        control.add_argument('--run', required=True, help='controller run id')
        control.add_argument('--reason', required=True)
        if name in ('stop', 'revoke'):
            # Both also drain the run's journalled batch jobs (``batch_jobs.stop_jobs``).
            control.add_argument('--now', action='store_true',
                                 help='also end the run\'s registered process groups now and report what is left')
    revoke = sub.add_parser('revoke-grant', help='withdraw the operator grant for every run frozen under it')
    revoke.add_argument('--reason', required=True)
    status = sub.add_parser('status', help='print one run\'s control state and pending requests')
    status.add_argument('--run', required=True)
    reply = sub.add_parser('answer', help='answer an escalation with authenticated operator authority')
    reply.add_argument('--run', required=True)
    reply.add_argument('--request', required=True, help='pending request id from the WAITING line')
    reply.add_argument('--code', required=True, help='the code shown with the request')
    reply.add_argument('--decision', required=True, help='an offered option, a check-in decision, or reject')
    reply.add_argument('--text', default='')
    export = sub.add_parser('export-run', help='export a quiescent verified run and protected state')
    export.add_argument('--run', required=True)
    export.add_argument('--out', required=True)
    export.add_argument('--share-only', action='store_true', help='read-only evidence; cannot restore authority')
    restore = sub.add_parser('restore-run', help='restore an authenticated backup at its original locators')
    restore.add_argument('--bundle', required=True)
    return ap


class PreferencesRefused(ValueError):
    """Agent preferences naming models the model catalogue does not admit; one remedy per model."""

    def __init__(self, messages):
        super().__init__('; '.join(messages))
        self.messages = list(messages)


def _settings(args):
    changes = {}
    if args.mode is not None:
        changes['mode'] = args.mode
    if args.budget:
        changes['budgets'] = _assignments(args.budget, '--budget')
    bounds = _bounds(args)
    if bounds:
        changes['bounds'] = bounds
    if args.machine_checkins is not None:
        changes['machine_checkins'] = [c for c in args.machine_checkins.split(',') if c]
    if args.r3_policy is not None:
        changes['r3_policy'] = args.r3_policy
    if args.wait_bound is not None:
        changes['wait_bound_seconds'] = args.wait_bound
    if args.notify_command is not None:
        changes['notify_command'] = _notify(args.notify_command)
    for name in ('allow_unconfined', 'allow_request_delegation'):
        value = getattr(args, name)
        if value is not None:
            changes[name] = value == 'true'
    if args.store_root is not None:
        changes['store_root'] = args.store_root
    for name in ('harness', 'engagement', 'compute_policy', 'agent_preferences', 'site_resource_ceilings'):
        value = getattr(args, name)
        if value is not None:
            changes[name] = json.loads(value)
    if 'agent_preferences' in changes:
        problems = ledger.agent_preference_problems(changes['agent_preferences'])
        if problems:
            raise PreferencesRefused(problems)
    if args.restricted_sources is not None:
        changes['restricted_sources'] = None if args.restricted_sources == 'null' else args.restricted_sources
    for name in ('remote_job_ceiling', 'procedure_byte_ceiling'):
        value = getattr(args, name)
        if value is not None:
            changes[name] = value
    for name in ('expires_at', 'instruction_document'):
        value = getattr(args, name)
        if value is not None:
            changes[name] = None if value == 'null' else value
    if args.project_scope is not None:
        changes['project_scope'] = (None if args.project_scope == 'null'
                                    else [p for p in args.project_scope.split(',') if p])
    if args.deadline is not None:
        if args.deadline == 'null':
            changes['deadline'] = None
        elif args.deadline_margin is None:
            raise ValueError('--deadline needs --deadline-margin')
        else:
            changes['deadline'] = {'at': args.deadline, 'margin_seconds': args.deadline_margin}
    elif args.deadline_margin is not None:
        raise ValueError('--deadline-margin goes with --deadline')
    if args.r3_delegation is not None:
        changes['r3_delegation'] = [n for n in args.r3_delegation.split(',') if n]
    if args.disk_free_floor is not None:
        changes['disk_free_floor_bytes'] = args.disk_free_floor
    if args.review_sandbox_fallback is not None:
        changes['review_sandbox_fallback'] = args.review_sandbox_fallback
    return changes


def _operator_evidence(action):
    return {'operator_uid': os.getuid(), 'pid': os.getpid(), 'tty': os.ttyname(0) if os.isatty(0) else None,
            'command': f'ravel operator {action}'}


def main(argv=None):
    args = parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        if args.command == 'init':
            changes = _settings(args)
            result = ledger.init(mode=changes.pop('mode'), budgets=changes.pop('budgets', None),
                                 bounds=changes.pop('bounds', None),
                                 machine_checkins=changes.pop('machine_checkins', None),
                                 **{k: v for k, v in changes.items()})
        elif args.command == 'set':
            result = ledger.set_values(_settings(args))
        elif args.command == 'show':
            result = ledger.operator_config()
        elif args.command == 'revoke-grant':
            result = ledger.revoke_grant(args.reason)
        elif args.command in common.CONTROLS:
            ledger._refuse_agent(f'ravel operator {args.command}')
            from . import stop
            store = common.open_store(args.run)
            result = stop.record_control(store, args.command, label=common.OPERATOR_COMMAND, source='operator_cli',
                                         evidence=_operator_evidence(args.command), reason=args.reason)
            from . import autonomy
            # What the stop has not reached yet: registered process groups still alive (read, never signalled).
            ended = autonomy.terminate(store) if getattr(args, 'now', False) else []
            batch = None
            if args.command in ('stop', 'revoke'):
                # The stop drains the run's own journalled batch jobs itself (verified, idempotent); a running
                # driver's poll may drain them too, and a second removal request is harmless.
                from ..batch_jobs import stop_jobs
                batch = stop_jobs(store)
            result = {'record': result['id'], 'kind': result['kind'], 'state': stop.stop_state(store),
                      'terminated': ended, 'alive': autonomy.alive(store),
                      **({'batch_jobs': batch} if batch is not None else {})}
            if batch is not None and not batch['verified']:
                print(json.dumps(result, indent=2, sort_keys=True, default=str))
                print('ravel operator: batch jobs not verified ended: ' + ', '.join(map(str, batch['unverified']))
                      + '; run the stop again or remove them at the scheduler', file=sys.stderr)
                return 3
        elif args.command == 'status':
            from . import autonomy, service, stop
            store = common.open_store(args.run)
            pending = [r for r in service._requests(store)
                       if not any(a.get('subject_sha256') == r['subject_sha256'] and a['kind'] == r['kind'] and a['label'] != common.LEGACY_TERMINAL
                                  for a in service._authority_records(store))]
            # The check-in, its options and the deviation rows are read here: notifications never carry them.
            result = {'control': stop.control(store),
                      'pending': [{'request': r['id'], 'kind': r['kind'], 'reason': r['reason'],
                                   'needed': r['needed'], 'since_ns': r['since_ns'], 'answerable': r['answerable'],
                                   'options': r['subject'].get('options') or [], 'text': r.get('checkin_text')}
                                  for r in pending],
                      'deviations': service.deviations(store),
                      # Read only: a status poll never notifies (each wait notified once, when it opened).
                      'waits': [{k: w.get(k) for k in ('code', 'reason', 'remedy', 'since_ns', 'id')}
                                for w in autonomy.open_waits(store)],
                      'alive': autonomy.alive(store), 'boundary': autonomy.boundary_statement()}
        elif args.command == 'export-run':
            from ..run_bundle import export_run
            result = export_run(common.open_store(args.run), args.out, share_only=args.share_only)
        elif args.command == 'restore-run':
            from ..run_bundle import restore_run
            result = restore_run(args.bundle)
        else:
            from . import service
            store = common.open_store(args.run)
            record = service.answer(store, args.request, args.code, args.decision, text=args.text)
            result = {'record': record['id'], 'kind': record['kind'], 'decision': record['decision'],
                      'option': record['option'], 'label': record['label']}
    except PreferencesRefused as exc:
        for message in exc.messages:
            print(f'ravel operator: {message}', file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError) as exc:
        print(f'ravel operator: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
