"""Trusted reconciliation and custody checks for the site's declared step.

Worker-authored reconciliation text is never scheduler evidence. Only recorded
backend handles and the backend's actual fetched output pins enter this record.
"""
from __future__ import annotations

from pathlib import Path

from .contracts import digest, records
from . import site


def _untracked(store):
    tracked = {row['launch_id'] for row in records(store, 'study-remote')}
    rows = records(store, 'study-site')
    return sorted({row['launch_id'] for row in rows
        if row.get('event') == 'dispatch_started' and row['launch_id'] not in tracked
        and not any(other.get('event') == 'outcome' and other['launch_id'] == row['launch_id']
                    for other in rows)})


def capture(context):
    """Bind placed science handles from the approved ordinary child only."""
    operation = next((row for row in context.get('plan', {}).get('steps', []) if row['id'] == 'operate'), None)
    if operation is None or not (operation.get('parameters') or {}).get('ordinary'):
        return []
    from ravel.workflow import execution
    from . import backend, runtime
    try:
        ordinary, child, module, _ = runtime._ordinary(operation, context, approved=False)
        if ordinary['kind'] != 'science':
            return []
        from ravel.workflow.state_io import read_json
        spec = read_json(child / module.SPEC)
        if 'execution' not in spec:
            return []
        stage = execution.load_execution(child)['stages'].get('science')
        if not stage or not stage.get('attempt_id'):
            return []
        runtime._ordinary(operation, context)  # every placed attempt retains its current approval
        backend.track(context['store'], operation['id'], rundir=child,
                      stage='science', plan_path=child / 'inputs/backend-plan.json')
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return [{'code': 'site_backend_binding_invalid', 'message': str(exc)}]
    return []


def _base(context, launch_id):
    bindings = [row for row in records(context['store'], 'study-backend-binding')
                if row['launch_id'] == launch_id]
    return Path(bindings[-1]['rundir'] if bindings else context['run_dir'])


def check(context):
    """Rehash completed adoptions without initiating a fetch or observation."""
    store = context['store']
    errors = capture(context)
    errors.extend({'code': 'site_dispatch_uncertain', 'launch_id': launch_id}
                  for launch_id in _untracked(store))
    adoptions = records(store, 'study-adoption')
    for row in records(store, 'study-remote'):
        launch_id = row['launch_id']
        previous = [item for item in adoptions if item['launch_id'] == launch_id]
        if not previous or previous[-1].get('event') != 'fetched' or 'receipt' not in previous[-1]:
            errors.append({'code': 'site_adoption_pending', 'launch_id': launch_id})
            continue
        try:
            # Existing fetched rows take the replay branch, which performs
            # local identity checks and never calls backend.recover or fetch.
            site.adopt(store, launch_id, base=_base(context, launch_id))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            errors.append({'code': 'site_adoption_invalid', 'launch_id': launch_id, 'message': str(exc)})
    return errors


def complete(context):
    """Observe the recorded attempts and fetch only their successful outputs."""
    from ravel.controller import authority
    store = context['store']
    if authority.stop_state(store) != 'running':
        return [{'code': 'site_reconciliation_held', 'message': 'operator state prevents output adoption'}]
    errors = capture(context)
    errors.extend({'code': 'site_dispatch_uncertain', 'launch_id': launch_id}
                  for launch_id in _untracked(store))
    result = site.reconcile(store, drain=False)
    for attempt in result['attempts']:
        launch_id = attempt['launch_id']
        if (not attempt.get('resolved')
                or (attempt.get('observation') or {}).get('state') != 'succeeded'):
            errors.append({'code': 'site_remote_incomplete', 'launch_id': launch_id,
                           'observation': attempt.get('observation'), 'message': attempt.get('error')})
            continue
        try:
            site.adopt(store, launch_id, base=_base(context, launch_id))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            errors.append({'code': 'site_adoption_invalid', 'launch_id': launch_id, 'message': str(exc)})
    errors.extend(check(context))
    store.append('study-site-custody', {'reconciliation_sha256': digest(result),
        'adoptions': [{'launch_id': row['launch_id'], 'receipt_sha256': digest(row['receipt'])}
                      for row in records(store, 'study-adoption') if row.get('event') == 'fetched'],
        'errors': errors, 'scientific_acceptance_inferred': False})
    return errors
