"""CHECK-IN 1 agent ceilings and locked, append-only invocation charges."""
from __future__ import annotations
from copy import deepcopy
import json
import math
import hashlib
import time
import os
from pathlib import Path
from .state_io import read_json, file_lock

RECORD = 'inputs/agent_ceilings.json'
LEDGER = 'agent-work/ledger.jsonl'


class CeilingExceeded(ValueError):
    pass


def default(run_shape: str) -> dict:
    if run_shape not in {'analysis', 'research'}:
        raise ValueError('run_shape must be analysis or research')
    return {'schema_version': 1, 'kind': 'agent-ceilings', 'run_shape': run_shape,
            'max_concurrent_workers': 6, 'max_invocations': 120 if run_shape == 'research' else 72,
            'max_investigations_per_review': 3, 'worker_wall_seconds': {'producer': 2700, 'reviewer': 1200},
            'native_jobs': 1, 'usd_caps': {}, 'source': 'default'}


def _response_binding(rundir):
    """Return the trusted recording time for the exact CHECK-IN 1 response bytes."""
    from . import rdj_custody
    root = Path(rundir)
    path = root / RECORD
    if not path.is_file():
        return None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    for row in reversed(rdj_custody.rows(root, 'inputs')):
        record = row['record']
        excluded = set(record.get('unvouched', ())) | set(record['ravel_written'])
        if record['event'] == 'checkin1' and RECORD not in excluded and record['files'].get(RECORD) == digest:
            return row['ns']
    # The response producer may record the exact ceiling JSON as user text.
    # A copied or modified response never binds a different ceiling document.
    try:
        _, response_digest, row = rdj_custody.user_text(root, 'checkin1_response', rdj_custody.CI1_RESPONSE)
        if response_digest == digest:
            return row['ns']
    except (OSError, ValueError):
        pass
    approval_path = root / 'inputs/checkin1_approval.json'
    if approval_path.is_file():
        from . import workflow_state
        from datetime import datetime
        approval = read_json(approval_path)
        # Current approvals bind the ordered input set via an aggregate digest.
        if (str(path.resolve()) in {str(Path(p).resolve()) for p in workflow_state.approval_input_paths(str(root))}
                and not workflow_state.verify_approval(str(root), approval)):
            return int(datetime.fromisoformat(approval['generated_utc'].replace('Z', '+00:00')).timestamp() * 1e9)
    return None


def _default_for_run(rundir):
    from .review_points import _facts, derive
    contract = Path(rundir) / 'inputs/task_contract.json'
    if not os.path.lexists(contract):
        # A run without a task contract pins no plan and so derives no review
        # point: it gets the smaller analysis default, never the research one.
        return default('analysis')
    if contract.is_symlink() or not contract.is_file():
        raise ValueError('task contract must be a regular file')
    return default('research' if any(p['row'] == 13 for p in derive(_facts(Path(rundir)))) else 'analysis')


def resolve(rundir: Path) -> dict:
    path = Path(rundir) / RECORD
    if path.exists():
        value = read_json(path)
    else:
        value = _default_for_run(rundir)
    if (set(value) != set(default('analysis')) or value.get('schema_version') != 1
            or value.get('kind') != 'agent-ceilings' or value.get('run_shape') not in {'analysis', 'research'}
            or value.get('source') not in {'default', 'checkin1_response'}):
        raise ValueError('invalid agent ceilings record')
    for key in ('max_concurrent_workers', 'max_invocations', 'max_investigations_per_review', 'native_jobs'):
        if type(value[key]) is not int or value[key] < 1:
            raise ValueError('positive integer ceiling required: ' + key)
    if value['native_jobs'] != 1:
        raise ValueError('native_jobs must remain one')
    if set(value['worker_wall_seconds']) != {'producer', 'reviewer'} or any(
            type(v) is not int or v < 1 for v in value['worker_wall_seconds'].values()):
        raise ValueError('positive producer and reviewer wall ceilings required')
    if not isinstance(value['usd_caps'], dict) or any(type(v) not in {int, float} or not math.isfinite(v) or v < 0
                                                    for v in value['usd_caps'].values()):
        raise ValueError('USD caps must be finite nonnegative numbers')
    if value['source'] == 'checkin1_response' and _response_binding(rundir) is None:
        return _default_for_run(rundir)
    if value['source'] == 'default':
        # The record's own run_shape is agent-writable; derive the shape from the pinned plan.
        baseline = _default_for_run(rundir)
        for key in ('max_concurrent_workers', 'max_invocations', 'max_investigations_per_review'):
            value[key] = min(value[key], baseline[key])
        for key in value['worker_wall_seconds']:
            value['worker_wall_seconds'][key] = min(value['worker_wall_seconds'][key], baseline['worker_wall_seconds'][key])
    return deepcopy(value)


def checkin_section(rundir: Path) -> dict:
    from .review_points import _facts
    facts = _facts(Path(rundir)); record = resolve(rundir)
    transports = facts.get('selected_transports', [])
    missing = sorted('usd_cap:' + t['id'] for t in transports if t.get('billing') == 'api' and t['id'] not in record['usd_caps'])
    return {'record': record, 'path': RECORD, 'missing_evidence_ids': missing, 'valid': not missing}


def _ledger(rundir):
    path = Path(rundir) / LEDGER
    if not path.exists():
        return []
    result = []
    for index, line in enumerate(path.read_text().splitlines(), 1):
        row = json.loads(line)
        if (row.get('sequence') != index or type(row.get('n')) is not int or row['n'] < 1
                or row.get('kind') not in {'worker', 'http-model', 'map-item', 'rdj'}):
            raise ValueError('invalid invocation ledger at entry ' + str(index))
        result.append(row)
    return result


def charge(rundir: Path, kind: str, n: int = 1) -> None:
    if kind not in {'worker', 'http-model', 'map-item', 'rdj'} or type(n) is not int or n < 1:
        raise ValueError('positive invocation count and declared invocation kind required')
    root = Path(rundir)
    with file_lock(root / 'agent-work/ledger.lock'):
        record = resolve(root); rows = _ledger(root)
        if sum(r['n'] for r in rows) + n > record['max_invocations']:
            raise CeilingExceeded('max_invocations exceeded; obtain a new CHECK-IN 1 ceiling')
        with (root / LEDGER).open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'sequence': len(rows) + 1, 'kind': kind, 'n': n, 'ns': time.time_ns(),
                                     'ceilings': record}, allow_nan=False) + '\n')
            stream.flush(); os.fsync(stream.fileno())


def gate_errors(rundir: Path, gate: str, action: dict) -> list:
    from .decision_gate import GateError
    section = checkin_section(rundir); record = section['record']; ids = list(section['missing_evidence_ids'])
    used = sum(r['n'] for r in _ledger(rundir))
    requested = action.get('invocations', 1 if gate in {'launch', 'research_choice'} else 0)
    if type(requested) is not int or requested < 0:
        ids.append('ceiling:invocations')
    elif used + requested > record['max_invocations']:
        ids.append('ceiling:max_invocations')
    for key in ('max_concurrent_workers', 'max_investigations_per_review', 'native_jobs'):
        demand = action.get(key, 0)
        if type(demand) is not int or demand < 0 or demand > record[key]:
            ids.append('ceiling:' + key)
    path = Path(rundir) / RECORD
    response = path.is_file() and read_json(path).get('source') == 'checkin1_response'
    recorded = _response_binding(rundir) if response else None
    if response and recorded is None:
        ids.append('ceiling:checkin1_response')
    if gate == 'spend_above_ceiling':
        rows = _ledger(rundir)
        used_before = 0
        raised = False
        for row in rows:
            used_before += row['n']
            old = row.get('ceilings', {}).get('max_invocations')
            if (type(old) is int and used_before >= old and record['max_invocations'] > old
                    and type(row.get('ns')) is int and recorded is not None and row['ns'] < recorded):
                raised = True
        if not raised:
            ids.append('ceiling:checkin1_response')

    return [GateError('ceiling_exceeded' if not identity.startswith('usd_cap:') else 'usd_cap_missing', gate, 'ceilings',
                     'Agent resource admission requires ' + identity,
                     'Declare or revise this ceiling in CHECK-IN 1 before dispatch.', (identity,)) for identity in ids]
