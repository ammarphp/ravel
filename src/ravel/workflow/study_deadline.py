"""A study's declared delivery deadline, the time left and the one action at its margin.

A task contract may carry an optional ``deadline``:

- ``{"utc": "2026-01-01T12:00:00Z", "margin_s": 3600}`` names an absolute UTC time;
- ``{"budget_s": 86400, "start_utc": "...", "margin_s": 3600}`` names a wall budget from
  the recorded run start.

``margin_s`` is the delivery margin before the deadline. Inside it, ``ravel status``
warns and names the single action that delivers something valid: a reviewed fill when
the review has accepted, otherwise a labelled provisional fill of a receipt-pinned
output, otherwise finishing the open review. The deadline never accepts a result,
never shortens a review and never authorizes compute; it only permits the explicitly
labelled provisional delivery in ``result_templates``.
"""
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path

KEYS = {'utc', 'budget_s', 'start_utc', 'margin_s'}
# Review states in which a result is still under its first, unresolved review.
OPEN_REVIEW = ('awaiting_review',)


def _utc(value, label):
    from .launch_authorization import parse_utc
    try:
        return parse_utc(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} must be an ISO UTC time: {exc}') from None


def _seconds(value, label, *, positive):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f'{label} must be a finite {"positive" if positive else "nonnegative"} number of seconds')
    return float(value)


def _resolve(value):
    """Return (deadline datetime, margin seconds, source) or raise ValueError."""
    if not isinstance(value, dict) or set(value) - KEYS or 'margin_s' not in value:
        raise ValueError('deadline needs margin_s and either utc or budget_s with start_utc')
    margin = _seconds(value['margin_s'], 'deadline.margin_s', positive=False)
    if ('utc' in value) == ('budget_s' in value):
        raise ValueError('deadline declares exactly one of utc or budget_s')
    if 'utc' in value:
        if 'start_utc' in value:
            raise ValueError('deadline.start_utc belongs to a budget deadline')
        return _utc(value['utc'], 'deadline.utc'), margin, 'contract.deadline.utc'
    if 'start_utc' not in value:
        raise ValueError('a budget deadline needs the recorded run start_utc')
    budget = _seconds(value['budget_s'], 'deadline.budget_s', positive=True)
    if margin > budget:
        raise ValueError('deadline.margin_s exceeds deadline.budget_s')
    start = _utc(value['start_utc'], 'deadline.start_utc')
    return start + timedelta(seconds=budget), margin, 'contract.deadline.budget_s'


def contract_errors(value):
    """Cross-field errors of a contract ``deadline`` (the schema checks its types)."""
    try:
        _resolve(value)
    except ValueError as exc:
        return [str(exc)]
    return []


def declare(*, margin_s, utc=None, budget_s=None, start_utc=None):
    """Build a contract ``deadline``; a budget is stamped with the run start (now by default)."""
    value = {'margin_s': margin_s}
    if utc is not None:
        value['utc'] = utc
    if budget_s is not None:
        from .launch_authorization import operational_utc
        value.update(budget_s=budget_s, start_utc=start_utc or operational_utc())
    errors = contract_errors(value)
    if errors:
        raise ValueError(errors[0])
    return value


def _contract(rundir):
    from ravel.validation import validate_run_state
    contract, _, error = validate_run_state.load_contract_for(str(Path(rundir)), None)
    if error:
        raise ValueError(error)
    return contract


def read(rundir, *, contract=None):
    """``{deadline_utc, margin_s, source}`` from the run contract, or None when none is declared."""
    contract = _contract(rundir) if contract is None else contract
    if 'deadline' not in contract:
        return None
    when, margin, source = _resolve(contract['deadline'])
    return {'deadline_utc': when.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'margin_s': margin, 'source': source}


def _now(now):
    if now is None:
        from .launch_authorization import operational_utc
        now = operational_utc()
    if isinstance(now, datetime):
        if now.tzinfo is None:
            raise ValueError('now must carry a UTC timezone')
        return now
    return _utc(now, 'now')


def _action(rundir, review, execution_errors):
    """The single action that delivers something valid inside the margin."""
    from . import execution, physics_review
    root = Path(rundir).resolve()
    review = physics_review.status(root) if review is None else review
    if review.get('state') == 'accepted':
        return {'kind': 'reviewed-fill', 'claim_scope': review.get('claim_scope'),
                'command': 'ravel fill-template --rundir RUN --claim-scope SCOPE --result RESULT '
                           '--template TEMPLATE --out OUT --deliver-into REQUESTER_FILE',
                'why': 'the review has accepted; deliver the reviewed values'}
    errors = execution.validate_execution(root) if execution_errors is None else execution_errors
    stages = execution.load_execution(root)['stages'] if not errors else {}
    succeeded = sorted(n for n, r in stages.items() if isinstance(r, dict) and r.get('status') == 'succeeded')
    if review.get('state') in OPEN_REVIEW and succeeded:
        return {'kind': 'provisional-fill', 'open_review': {'state': review['state'], 'cycle_id': review.get('cycle_id')},
                'stages': succeeded,
                'command': 'ravel fill-template --provisional --rundir RUN --claim-scope SCOPE --result RESULT '
                           '--template TEMPLATE --out OUT --deliver-into REQUESTER_FILE',
                'why': 'no reviewed result exists; deliver receipt-pinned values labelled provisional; '
                       'a later reviewed fill supersedes them'}
    return {'kind': 'finish-review', 'open_review': {'state': review.get('state'), 'cycle_id': review.get('cycle_id')},
            'why': 'no reviewed result and no receipt-pinned output under an open review; '
                   'finish the review (or produce and open one) before delivery'}


def state(rundir, now=None, *, contract=None, review=None, execution_errors=None):
    """``{seconds_left, in_margin, action}`` plus the declared deadline; None when none is declared."""
    declared = read(rundir, contract=contract)
    if declared is None:
        return None
    current = _now(now)
    left = (_utc(declared['deadline_utc'], 'deadline') - current).total_seconds()
    in_margin = left <= declared['margin_s']
    out = {**declared, 'now_utc': current.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
           'seconds_left': left, 'in_margin': in_margin, 'overdue': left < 0,
           'action': _action(rundir, review, execution_errors) if in_margin else None}
    if in_margin:
        out['warning'] = (f"study deadline {'passed' if left < 0 else 'margin reached'}: "
                          f"{abs(left):.0f} s {'over' if left < 0 else 'left'}; next: {out['action']['kind']}")
    return out


def packet_block(rundir, *, contract, review=None, execution_errors=None):
    """The status packet's view of the deadline; a malformed deadline is reported, not raised."""
    try:
        return state(rundir, contract=contract, review=review, execution_errors=execution_errors)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'error': str(exc), 'in_margin': None, 'action': None}


def require_margin(rundir, now=None):
    """The deadline state when the margin has been reached; refuse otherwise."""
    current = state(rundir, now)
    if current is None:
        raise ValueError('a provisional fill needs a deadline declared in the task contract')
    if not current['in_margin']:
        raise ValueError(f"the deadline margin has not been reached ({current['seconds_left']:.0f} s left, "
                         f"margin {current['margin_s']:.0f} s); a provisional fill is refused before it")
    return current
