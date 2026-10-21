"""Sandbox loop nodes borrow their supervisor's steering custody over the broker socket.

The connection owns one admission until release or EOF. The child receives no custody
paths or authority and cannot change its parent step, attempt, budget or toolbelt.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path
import socket

_BOUND = ContextVar('ravel_loop_node_admission', default=None)


@contextmanager
def bound(scope_root, socket_path):
    token = _BOUND.set((str(Path(scope_root).absolute()), str(socket_path)))
    try:
        yield
    finally:
        _BOUND.reset(token)


def remote_admission(scope_root, node_id):
    target = _BOUND.get()
    if target is None or str(Path(scope_root).absolute()) != target[0]:
        return None
    return _admitted(target[1], node_id)


@contextmanager
def _admitted(socket_path, node_id):
    from .. import broker

    def send(stream, value):
        stream.write(json.dumps(value, allow_nan=False).encode() + b'\n')
        stream.flush()
        raw = stream.readline(broker.MAX_MESSAGE + 1)
        if len(raw) > broker.MAX_MESSAGE or not raw.endswith(b'\n'):
            raise ValueError('worker node admission returned no complete receipt')
        result = json.loads(raw)
        if type(result) is not dict or result.get('status') != 'ok':
            raise ValueError('worker node steering admission refused')
        return result

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(10)
        connection.connect(socket_path)
        with connection.makefile('rwb') as stream:
            result = send(stream, {'schema_version': 1, 'kind': 'worker-node-admission', 'node': node_id})
            record = result.get('admission')
            if type(record) is not dict or type(record.get('id')) is not str or not record['id']:
                raise ValueError('worker node admission identity missing')
            try:
                yield record['id']
            finally:
                reply = send(stream, {'schema_version': 1, 'kind': 'worker-node-release',
                                      'admission_id': record['id']})
                if reply.get('released') != record['id']:
                    raise ValueError('worker node admission release identity differs')


def supervisor_admission(run, node_id, attempt, *, max_nodes=100000):
    """Code-owned admission factory: the worker can name only its inner node, never a parent."""
    from .. import broker, gate_wiring
    import threading
    lock, counts = threading.Lock(), {'nodes': 0}
    if type(max_nodes) is not int or not 1 <= max_nodes <= 400012:
        raise ValueError('finite worker node admission budget required')

    @contextmanager
    def admitted(subnode):
        with lock:
            if counts['nodes'] >= max_nodes:
                raise ValueError('worker node admission budget exhausted')
            counts['nodes'] += 1
        with gate_wiring.steering_admitted(run, node_id, role='worker-graph-node') as identifier:
            record = {'schema_version': 1, 'id': identifier, 'node_id': node_id, 'attempt': attempt,
                      'subnode': subnode, 'phase': 'admitted', 'utc': broker.utc()}
            broker.append_ledger(run, 'worker-node-admissions', record)
            try:
                yield record
            finally:
                broker.append_ledger(run, 'worker-node-admissions', {**record, 'phase': 'ended', 'utc': broker.utc()})

    return admitted
