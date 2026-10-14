"""Code-owned evaluation/stop records and shared exposure dispatch.

Numbers are projected from ordinary observed result and attempt pins using the
prospective design. No receipt file can substitute for a journal observation.
"""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json
from . import state_io


def _p():
    from . import research_protocol
    return research_protocol


def validate_declaration(value):
    """Refuse a malformed prospective evaluation at design, before any execution."""
    p = _p()
    if not isinstance(value, dict):
        raise ValueError('prospective evaluation declaration required')
    try:
        for key in ('candidate', 'family', 'purpose', 'generation'):
            p._required_text(value.get(key), 'evaluation ' + key)
        if value['purpose'] not in p.PURPOSES or type(value.get('round')) is not int or value['round'] < 1:
            raise ValueError('prospective evaluation purpose and round required')
        p._exposure_identity(value)
        pins = value.get('population_pins')
        if type(pins) is not list or not pins or any(not isinstance(x, dict) for x in pins):
            raise ValueError('prospective evaluation population pins required')
        pointers = value.get('value_pointers') or [value.get('value_pointer')]
        optional = [value[k] for k in ('p_value_pointer', 'decision_pointer') if value.get(k) is not None]
        if any(not isinstance(x, str) or not x.startswith('/') for x in [*pointers, *optional]):
            raise ValueError('prospective evaluator value pointer required')
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('invalid prospective evaluation: ' + str(exc)) from exc


def declaration(state, experiment):
    """Default designs carry evaluation; staged designs derive their cell map."""
    if experiment.get('evaluation') is not None:
        return deepcopy(experiment['evaluation'])
    p = _p()
    bound = p._bound(state)
    if not bound:
        return None
    stages = p._stage_ids(bound[0], experiment['id'])
    if not stages:
        return None  # comparison operation, never an extra selection attempt
    # The incumbent baseline can also be a full stage of the same execution.
    stage = next((s for s in stages if s['purpose'] == 'full'), stages[0])
    assignments = [a for a in stage['cells'] if a['experiment_id'] == experiment['id']]
    cells = [next(c for c in bound[0]['cells'] if c['id'] == a['cell_id']) for a in assignments]
    if not cells:
        raise ValueError('complete evaluation cell assignment required')
    return {'candidate': stage['candidate'], 'family': cells[0]['regime'], 'round': 1,
            'purpose': stage['purpose'], 'cells': [c['id'] for c in cells],
            'seeds': sorted({str(s) for c in cells for s in c.get('seeds', [])}),
            'generation': cells[0].get('generation'), 'population_pins': [c['population'] for c in cells],
            'value_pointers': [a['value_pointer'] for a in assignments],
            'decision_pointer': '/decision', 'p_value_pointer': None}


def _elapsed(attempt):
    if 'wall_seconds' in attempt:
        value = attempt['wall_seconds']
    else:
        try:
            value = (datetime.fromisoformat(attempt['finished_utc'].replace('Z', '+00:00')) -
                     datetime.fromisoformat(attempt['started_utc'].replace('Z', '+00:00'))).total_seconds()
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError('observed attempt has no measured execution cost') from exc
    if _p()._finite_number(value, 'observed wall seconds') < 0:
        raise ValueError('observed execution cost cannot be negative')
    return value


def derive(state, experiment):
    p = _p(); c = p._cycle()
    metadata = declaration(state, experiment)
    if metadata is None:
        return None
    observation = experiment.get('observation')
    if not observation:
        raise ValueError('evaluation requires an actual experiment observation')
    for key in ('candidate', 'family', 'purpose'):
        p._required_text(metadata.get(key), 'evaluation ' + key)
    if metadata['purpose'] not in p.PURPOSES or type(metadata.get('round')) is not int or metadata['round'] < 1:
        raise ValueError('prospective evaluation purpose and round required')
    exposure = p._exposure_identity(metadata)
    attempt = c._read(observation['receipt'], state['base_dir'])
    successful = c.ExecutionStatus.normalize(observation['execution_status']) == c.ExecutionStatus.SUCCESS
    successful &= not observation.get('packet', {}).get('errors')
    source = observation.get('result')
    result = c._read(source, state['base_dir']) if source else None
    score = probability = None
    decision = 'unknown'
    if successful and result is not None:
        pointers = metadata.get('value_pointers') or [metadata.get('value_pointer')]
        if any(not isinstance(x, str) or not x.startswith('/') for x in pointers):
            raise ValueError('prospective evaluator value pointer required')
        values = [p._finite_number(c._pointer(result, pointer), 'observed evaluation') for pointer in pointers]
        score = sum(values) / len(values)
        if metadata.get('p_value_pointer'):
            probability = p._finite_number(c._pointer(result, metadata['p_value_pointer']), 'observed p value')
            if not 0 <= probability <= 1:
                raise ValueError('observed p value out of range')
        if metadata.get('decision_pointer'):
            decision = c._pointer(result, metadata['decision_pointer'])
            if decision not in p.DECISIONS:
                raise ValueError('observed decision differs from declared evaluator contract')
    status = 'success' if successful and score is not None else (
        'failed' if c.ExecutionStatus.normalize(observation['execution_status']) == c.ExecutionStatus.FAILED else 'unresolved')
    fidelity = {'screen': 'adaptive_screen', 'confirm': 'withheld_confirmation'}.get(metadata['purpose'], 'adaptive_full')
    return {'kind': 'research-select-result', 'id': experiment['id'], 'candidate': metadata['candidate'],
            'family': metadata['family'], 'round': metadata['round'], 'purpose': metadata['purpose'],
            **exposure, 'exposure': fidelity, 'value': score, 'p_value': probability,
            'status': status, 'decision': decision, 'cost': _elapsed(attempt),
            'source': deepcopy(source), 'attempt': deepcopy(observation['receipt']),
            'evaluation_contract_sha256': p.ce.digest(metadata)}


def record_observation(state, experiment):
    record = derive(state, experiment)
    if record is not None:
        state['events'].append({'kind': 'research_evaluation_observed', 'revision': state['revision'] + 1,
                                'experiment_id': experiment['id'], 'evaluation': record})
        stop = stop_state(state)
        if stop and stop['reason'] and not any(e['kind'] == 'research_computed_stop' and e['stop'] == stop for e in state['events']):
            state['events'].append({'kind': 'research_computed_stop', 'revision': state['revision'] + 1,
                                    'stop': stop})


def records(state, *, purposes=None):
    """Reconcile every actual observation with its code-written projection."""
    rows = []
    for experiment in state.get('experiments', []):
        if not experiment.get('observation'):
            continue
        metadata = declaration(state, experiment)
        if metadata is None:
            # Unclassified default observations cannot be silently left out of N.
            if not _p()._bound(state):
                raise ValueError('observed evaluation missing prospective classification')
            continue
        try:
            _p()._cycle()._current_evidence(state, experiment, accepted=False)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError('evaluation observation custody invalid: ' + str(exc)) from exc
        row = derive(state, experiment)
        events = [e for e in state['events'] if e['kind'] == 'research_evaluation_observed'
                  and e['experiment_id'] == experiment['id']]
        if len(events) != 1 or events[0]['evaluation'] != row:
            raise ValueError('evaluation differs from recorded experiment observation')
        if purposes is None or row['purpose'] in purposes:
            rows.append(row)
    return rows


def selection_request(state, request):
    """Reject submitted census/pins; values only come from the complete journal."""
    rows = records(state, purposes={'screen', 'full'})
    expected = [{'id': row['id'], 'candidate': row['candidate'], 'result': row['source'] or row['attempt']} for row in rows]
    if not expected or sorted(request['trials'], key=lambda r: r['id']) != sorted(expected, key=lambda r: r['id']):
        raise ValueError('selection census must equal all recorded evaluation observations')
    return rows


def stop_records(state):
    """Current decision-authorized segment; older receipts remain in the journal."""
    continuations = [e for e in state['events'] if e['kind'] == 'research_stop_continuation']
    after = continuations[-1]['after_revision'] if continuations else -1
    ids = {e['experiment_id'] for e in state['events'] if e['kind'] == 'research_evaluation_observed'
           and e.get('revision', 0) > after}
    return [r for r in records(state, purposes={'full'}) if r['id'] in ids]


def stop_state(state):
    method = state.get('methodology') or {}
    if not method.get('preregistration'):
        return None
    rule = _p()._method_json(method['preregistration'], state['base_dir']).get('stop_rule')
    if not rule:
        return None
    # A continuation is a recorded decision over the exact prior stop, not a flag.
    continuations = [e for e in state['events'] if e['kind'] == 'research_stop_continuation']
    start = -1
    if continuations:
        latest = continuations[-1]
        rule, start = latest['stop_rule'], latest['after_revision']
    rows = [e['evaluation'] for e in state['events'] if e['kind'] == 'research_evaluation_observed'
            and e.get('revision', 0) > start and e['evaluation']['purpose'] == 'full']
    successes, covered, cost, reason = set(), set(), 0., None
    for row in rows:
        cost += row['cost']; covered.add(row['family'])
        if row['status'] == 'success' and row['decision'] == 'better': successes.add(row['candidate'])
        rounds = len({r['round'] for r in rows if r['round'] <= row['round']})
        all_in_round_done = not any(not e.get('observation') and (declaration(state, e) or {}).get('purpose') == 'full'
                                    and (declaration(state, e) or {}).get('round') == row['round']
                                    for e in state.get('experiments', []))
        reason = ('successes' if len(covered) >= rule['coverage_floor'] and len(successes) >= rule['successes'] else
                  'max_rounds' if rounds >= rule['max_rounds'] and all_in_round_done else
                  'budget' if cost >= rule['budget'] else None)
        if reason:
            if len(covered) < rule['coverage_floor']: reason = 'coverage_unmet'
            break
    result = {'reason': reason, 'cost': cost, 'successes': len(successes),
              'evaluations': len(rows), 'covered_families': sorted(covered),
              'uncovered_families': sorted(set(rule['families']) - covered), 'rule': rule}
    result['sha256'] = _p().ce.digest(result)
    return result


def enforce_dispatch_stop(state, identity):
    experiment = next(e for e in state['experiments'] if e['id'] == identity)
    metadata = declaration(state, experiment) or {}
    if metadata.get('purpose') in {'confirm', 'objection_test'}:
        return
    if metadata.get('purpose') == 'full':
        for earlier in state['experiments']:
            other = declaration(state, earlier) or {}
            if (other.get('purpose') == 'full' and other.get('round', 0) < metadata.get('round', 0)
                    and not earlier.get('observation')):
                raise ValueError('previous evaluation round remains unobserved before stop check')
    stop = stop_state(state)
    if stop and stop['reason']:
        raise ValueError('continuing past computed stop requires a recorded decision: ' + stop['reason'])


def reserve_study_exposure(study, action, *, selection_sha256=None):
    from ravel.physics import ml_exposure
    _p()._exposure_identity(action)
    return ml_exposure.reserve_research(_p().ce.digest(study), action.get('populations', []),
        context=_p().ce.digest(action), selection_sha256=selection_sha256)


def population_identity(pin, base):
    from ravel.physics import ml_exposure
    path = Path(pin['path']); path = path if path.is_absolute() else Path(base)/path
    if path.suffix == '.npz':
        return ml_exposure.identity(pin, base)
    if path.suffix == '.jsonl':
        # A JSON-lines cohort is its decoded records, one object per line: the events and
        # groups they name, and each record's measured content without those labels.
        raw = _p()._method_pin(pin, base)
        try:
            rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
        except ValueError as exc:
            raise ValueError('JSON-lines population requires one JSON record per line') from exc
        if not rows or any(not isinstance(row, dict) for row in rows):
            raise ValueError('JSON-lines population requires one JSON record per line')
        labels = ('event_id', 'id', 'group_id')
        events = [row.get('event_id', row.get('id')) for row in rows]
        if any(v is None for v in events) or len({str(v) for v in events}) != len(events):
            raise ValueError('JSON-lines population requires one distinct event identity per record')
        return {'sha256': _p().ce.digest(rows), 'byte_sha256': pin['sha256'],
                'event_ids': sorted(str(v) for v in events),
                'group_ids': sorted({str(row['group_id']) for row in rows if 'group_id' in row}),
                'value_hashes': [_p().ce.digest({k: v for k, v in row.items() if k not in labels}) for row in rows]}
    # For JSON cohorts, identity is decoded canonical content, not file encoding.
    value = _p()._method_json(pin, base)
    ids = value.get('event_ids', value.get('ids', [])) if isinstance(value, dict) else []
    return {'sha256': _p().ce.digest(value), 'byte_sha256': pin['sha256'],
            'event_ids': sorted({str(v) for v in ids}), 'group_ids': [],
            'value_hashes': [_p().ce.digest(value)]}


def dispatch(root, state, identity):
    p = _p(); experiment = next(e for e in state['experiments'] if e['id'] == identity)
    enforce_dispatch_stop(state, identity)
    metadata = declaration(state, experiment)
    if metadata is None:
        if state.get('methodology'):
            raise ValueError('prospective evaluation and exposure declaration required')
        return state
    # Older staged contracts without confirmation have no read-once promise.
    bound = p._bound(state)
    if bound and not any(c['exposure'] == 'withheld_confirmation' for c in bound[0]['cells']) and not experiment.get('evaluation'):
        return state
    action = {k: deepcopy(metadata[k]) for k in ('candidate', 'cells', 'seeds', 'generation')}
    receipt, reads = p._selection_state(state)
    confirming = metadata['purpose'] == 'confirm'
    if confirming:
        errors = p.confirmation_errors(receipt, reads, action)
        if errors: raise ValueError(errors[0])
    p._exposure_identity(action)
    pins = metadata.get('population_pins', [])
    if not pins:
        raise ValueError('prospective population pins required for study exposure')
    populations = [population_identity(pin, state['base_dir']) for pin in pins]
    if bound:
        withheld = [c for c in bound[0]['cells'] if c['exposure'] == 'withheld_confirmation']
    else:
        prereg = p._method_json(state['methodology']['preregistration'], state['base_dir']) if state.get('methodology') else {}
        withheld = prereg.get('withheld_cells', [])
    from ravel.physics.ml_exposure import overlaps
    hidden = [population_identity(c['population'], state['base_dir']) for c in withheld]
    # Check the complete ordinary input closure, including omitted baseline/diagnostic inputs.
    hidden_hashes = {c['population']['sha256'] for c in withheld}
    ordinary_pins = experiment.get('input_pins', [])
    for pin in ordinary_pins:
        path = Path(pin['path'])
        if path.suffix == '.npz':
            populations.append(population_identity(pin, state['base_dir']))
        elif path.suffix == '.json':
            value = p._method_json(pin, state['base_dir'])
            if isinstance(value, dict) and any(k in value for k in ('ids', 'event_ids')):
                populations.append(population_identity(pin, state['base_dir']))
    populations = list({p.ce.digest(row): row for row in populations}.values())
    exposed_hidden = (set(action['cells']) & {c['id'] for c in withheld}
                      or any(overlaps(a, b) for a in populations for b in hidden)
                      or any(pin['sha256'] in hidden_hashes for pin in ordinary_pins))
    if not confirming and exposed_hidden:
        raise ValueError('confirm_cell_in_selection_inputs')
    if confirming and (not hidden or not all(any(overlaps(a, b) for b in hidden) for a in populations)):
        raise ValueError('confirmation must use prospectively withheld populations')
    action['populations'] = populations
    action['purpose'] = metadata['purpose']
    if state.get('methodology') or confirming:
        errors = p.decision_errors(root, action)
        if errors: raise ValueError('; '.join(e.code for e in errors))
    # Each metadata population must also be an ordinary pinned study input.
    if {pin['sha256'] for pin in pins} - {pin['sha256'] for pin in ordinary_pins}:
        raise ValueError('evaluation population missing from ordinary study inputs')
    ledger = reserve_study_exposure(state['contract'].get('context_request', state['contract']), action,
                                   selection_sha256=receipt['sha256'] if confirming else None)
    read = {**action, 'experiment_id': identity, 'ledger': ledger,
            'selection_sha256': receipt['sha256'] if confirming else None}
    return p._cycle()._commit(Path(root), state,
        'research_confirm_read' if confirming else 'research_adaptive_read', read=read)


def verify_run_dispatch(rundir):
    path = Path(rundir)/'inputs/research-experiment.json'
    plan_path = Path(rundir)/'inputs/science-plan.json'
    plan = state_io.read_json(plan_path) if plan_path.exists() else {}
    expected = plan.get('research_binding')
    if expected is None and not path.exists():
        return
    if expected is None or not path.exists():
        raise ValueError('research dispatch binding missing from immutable plan or reservation')
    binding = state_io.read_json(path)
    if binding != expected:
        raise ValueError('research dispatch binding differs from immutable plan')
    state = _p()._cycle()._load(binding['root'])[1]
    experiment = next(e for e in state['experiments'] if e['id'] == binding['experiment_id'])
    if Path(experiment['rundir']).resolve() != Path(rundir).resolve():
        raise ValueError('research run binding differs')
    events = [e for e in state['events'] if e['kind'] == 'ordinary_study_dispatch_boundary'
              and e['experiment_id'] == experiment['id']]
    if not events or experiment.get('observation') is not None:
        raise ValueError('research dispatch must reserve exposure before ordinary execution')
    metadata = declaration(state, experiment)
    if metadata:
        reads = [e for e in state['events'] if e['kind'] in {'research_confirm_read', 'research_adaptive_read'}
                 and e['read'].get('experiment_id') == experiment['id']]
        if not reads:
            raise ValueError('research dispatch has no study exposure reservation')
