"""One source-bound synchronous step in an existing allocation, no scheduler.

Current controller records, source-defined launch handshake and final records
remain distinct from client exit/local groups. No unknown group is cancelled.
Native queries are invoked only by an admitted adapter; pure controls inject an
explicit inert command observer. Installed JSON fields/version are supplied and
source-bound rather than guessed from the latest online manual.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
import time
from ravel.physics.cosmic_evolution_core import keys, integer, loads, name

JOB_FIELDS = {'job_id', 'uid', 'submit', 'start', 'restarts', 'state', 'nodes'}
STEP_FIELDS = {'job_id', 'step_id', 'uid', 'start', 'state', 'nodes'}
TERMINAL = {'COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'NODE_FAIL', 'OUT_OF_MEMORY'}


def _path(value, path):
    if type(path) is not list or not path or len(path) > 16:
        raise ValueError('explicit bounded installed JSON field path required')
    for key in path:
        if type(key) is str and type(value) is dict and key in value: value = value[key]
        elif type(key) is int and type(value) is list and 0 <= key < len(value): value = value[key]
        else: raise ValueError('installed Slurm response schema differs')
    return value


def record(raw, schema, kind, *, expand_nodes=None):
    keys(schema, ('records', 'fields', 'timestamp_format'), 'installed controller schema')
    fields = JOB_FIELDS if kind == 'job' else STEP_FIELDS
    if type(schema['fields']) is not dict or set(schema['fields']) != fields:
        raise ValueError('complete controller identity field mapping required')
    values = _path(loads(raw), schema['records'])
    if type(values) is not list or len(values) != 1: raise ValueError('one exact current controller record required')
    result = {k: _path(values[0], v) for k, v in schema['fields'].items()}
    for k in ('job_id', 'uid', *(('restarts',) if kind == 'job' else ('step_id',))): integer(result[k], k, 0)
    for k in ('submit', 'start') if kind == 'job' else ('start',):
        if schema['timestamp_format'] == 'unix-seconds': result[k] = integer(result[k], k, 0)
        elif schema['timestamp_format'] == 'iso8601':
            if type(result[k]) is not str: raise ValueError('source-declared timestamp format differs')
            value = datetime.fromisoformat(result[k].replace('Z', '+00:00'))
            if value.tzinfo is None: raise ValueError('explicit scheduler timezone required')
            result[k] = int(value.timestamp())
        else: raise ValueError('explicit installed timestamp format required')
    if type(result['state']) is not str or not result['state']: raise ValueError('current controller state required')
    if type(result['nodes']) is str:
        if expand_nodes is None: raise ValueError('installed compact hostlist requires bounded native expansion')
        result['nodes'] = expand_nodes(result['nodes'])
    if type(result['nodes']) is not list or not result['nodes'] or any(type(n) is not str or not n for n in result['nodes']) or len(set(result['nodes'])) != len(result['nodes']):
        raise ValueError('complete source-defined node-name population required')
    return result


class OwnedStep:
    """Allocation/step ownership state is per call, stored in existing outputs."""
    def __init__(self, allocation, schemas, observe, *, clock=time.time, expand_nodes=None):
        keys(allocation, ('cluster', 'job_id', 'uid', 'submit', 'start', 'restarts', 'nodes'), 'existing allocation')
        keys(schemas, ('job', 'step'), 'installed controller schemas')
        for k in ('job_id', 'uid', 'submit', 'start', 'restarts'): integer(allocation[k], k, 0)
        if type(allocation['cluster']) is not str or not allocation['cluster'] or type(allocation['nodes']) is not list or not allocation['nodes'] or len(set(allocation['nodes'])) != len(allocation['nodes']):
            raise ValueError('explicit existing cluster/full node population required')
        self.expected = deepcopy(allocation); self.schemas = schemas; self.observe = observe
        self.initial = None; self.owned = None; self.evidence = []
        self.clock = clock; self.not_before = None; self.ranks = None
        self.expand_nodes = expand_nodes

    def job(self):
        raw = self.observe('job', self.expected['job_id'], None)
        current = record(raw, self.schemas['job'], 'job', expand_nodes=self.expand_nodes)
        self.evidence.append({'operation': 'job', 'raw_utf8': raw.decode('utf-8'), 'record': current})
        expected = {k: v for k, v in self.expected.items() if k != 'cluster'}
        if any(current[k] != v for k, v in expected.items()) or current['state'] != 'RUNNING':
            raise ValueError('current owned allocation/run identity differs')
        return current

    def begin(self, uid, environment_job_id, payload):
        if type(uid) is not int or uid != self.expected['uid'] or str(self.expected['job_id']) != environment_job_id:
            raise ValueError('existing site-local allocation owner/environment differs')
        self.job(); self.initial = deepcopy(payload); self.not_before = int(self.clock())

    def bind(self, handshakes, ranks, nonce, payload):
        if self.initial != payload or type(handshakes) is not list or len(handshakes) != ranks:
            raise ValueError('complete prospective payload/rank handshake required')
        ids = []; step = None
        for row in handshakes:
            keys(row, ('nonce', 'job_id', 'step_id', 'uid', 'rank', 'node', 'payload'), 'rank handshake')
            for k in ('job_id', 'step_id', 'uid', 'rank'): integer(row[k], k, 0)
            if (row['nonce'] != nonce or row['payload'] != payload or row['job_id'] != self.expected['job_id'] or row['uid'] != self.expected['uid'] or row['node'] not in self.expected['nodes']):
                raise ValueError('rank/payload handshake differs')
            integer(row['step_id'], 'step id', 0); integer(row['rank'], 'rank', 0)
            if step is not None and row['step_id'] != step: raise ValueError('mixed step incarnations')
            step = row['step_id']; ids.append(row['rank'])
        if sorted(ids) != list(range(ranks)): raise ValueError('complete unique rank population required')
        self.job()
        raw = self.observe('step', self.expected['job_id'], step)
        current = record(raw, self.schemas['step'], 'step', expand_nodes=self.expand_nodes)
        if (current['job_id'] != self.expected['job_id'] or current['step_id'] != step or current['uid'] != self.expected['uid'] or
                current['state'] != 'RUNNING' or not set(current['nodes']) <= set(self.expected['nodes']) or
                set(current['nodes']) != {r['node'] for r in handshakes} or current['start'] < self.not_before):
            raise ValueError('actual created step ownership/node census differs')
        self.owned = current; self.ranks = ranks
        self.evidence.append({'operation': 'step-bind', 'raw_utf8': raw.decode('utf-8'), 'record': current})
        return {'nonce': nonce, 'payload': deepcopy(payload), 'job_id': current['job_id'], 'step_id': current['step_id'], 'uid': current['uid'], 'start': current['start']}

    def _current(self):
        if self.owned is None: raise ValueError('step identity never observed; cleanup held')
        self.job()
        raw = self.observe('step', self.owned['job_id'], self.owned['step_id'])
        current = record(raw, self.schemas['step'], 'step', expand_nodes=self.expand_nodes)
        if any(current[k] != self.owned[k] for k in STEP_FIELDS - {'state'}):
            raise ValueError('step incarnation changed; no guessed cleanup')
        self.evidence.append({'operation': 'step-current', 'raw_utf8': raw.decode('utf-8'), 'record': current})
        return current

    def cancel(self):
        current = self._current()
        if current['state'] not in TERMINAL:
            # The only mutation is exact observed JOB.STEP; never JOB/allocation.
            raw = self.observe('cancel', self.owned['job_id'], self.owned['step_id'])
            self.evidence.append({'operation': 'cancel-owned-step', 'raw_utf8': raw.decode('utf-8')})
        ended = self._current()
        if ended['state'] not in TERMINAL: raise ValueError('owned step cleanup unresolved')
        return {'state': ended['state'], 'allocation_cancelled': False, 'scheduler_terminal_observed': True, 'local_groups_absent': None}

    def finish(self, rank_exits):
        if type(rank_exits) is not list or self.ranks is None or len(rank_exits) != self.ranks or sorted(r.get('rank') for r in rank_exits) != list(range(self.ranks)):
            raise ValueError('complete terminal rank population required')
        for row in rank_exits:
            keys(row, ('rank', 'exit_code', 'job_id', 'step_id'), 'rank terminal')
            for k in ('rank', 'job_id', 'step_id'): integer(row[k], k, 0)
            if type(row['exit_code']) is not int or row['exit_code'] != 0 or self.owned is None or row['job_id'] != self.owned['job_id'] or row['step_id'] != self.owned['step_id']:
                raise ValueError('native rank failed or step identity differs')
        current = self._current()
        if current['state'] != 'COMPLETED': raise ValueError('distributed step is not observed completed')
        return {'allocation': deepcopy(self.expected), 'step': deepcopy(current), 'rank_exits': deepcopy(rank_exits),
                'controller_observations': deepcopy(self.evidence), 'physics_verified': False,
                'distributed_memory_peak': None, 'accounting_complete': False, 'local_group_absence_is_not_remote_proof': True}
