"""Socket-scoped trusted node admission; no provider, gate or tool substitutes."""
from contextlib import contextmanager
import json
import socket
import threading
from types import SimpleNamespace

import pytest

from ravel.workflow import broker


@pytest.fixture
def side(tmp_path):
    calls = []
    def call(request):
        calls.append(request)
        return {'status': 'ok', 'echo': request}
    return SimpleNamespace(socket_path=tmp_path / 's', call=call, calls=calls)


@contextmanager
def connected(side):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        client.connect(str(side.socket_path))
        with client.makefile('rwb', buffering=0) as stream:
            yield stream


def send(stream, document):
    stream.write(json.dumps(document).encode() + b'\n')


def read(stream):
    return json.loads(stream.readline())


def admit(node='model'):
    return {'schema_version': 1, 'kind': 'worker-node-admission', 'node': node}


def release(identifier='admission-1'):
    return {'schema_version': 1, 'kind': 'worker-node-release', 'admission_id': identifier}


def callback(events, closed, record=None):
    @contextmanager
    def context(node):
        events.append(('enter', node, threading.get_ident()))
        try:
            yield {'id': 'admission-1', 'parent_node': 'seat-1'} if record is None else record
        finally:
            events.append(('exit', node, threading.get_ident()))
            closed.set()
    return context


def test_admission_lifetime_release_and_context_stay_on_one_handler_thread(side):
    events, closed = [], threading.Event()
    with broker.serve(side, node_admission=callback(events, closed)):
        with connected(side) as stream:
            send(stream, admit())
            assert read(stream) == {'status': 'ok', 'admission': {'id': 'admission-1', 'parent_node': 'seat-1'}}
            assert [e[0] for e in events] == ['enter'] and not closed.is_set()
            assert not side.calls
            send(stream, release())
            assert read(stream) == {'status': 'ok', 'released': 'admission-1'}
            assert closed.is_set()
            assert stream.readline() == b''
        assert [e[0] for e in events] == ['enter', 'exit']
        assert events[0][2] == events[1][2] != threading.get_ident()
    assert not side.calls


def test_admission_without_callback_is_refused_without_tool_dispatch(side):
    with broker.serve(side), connected(side) as stream:
        send(stream, admit())
        assert read(stream) == {'status': 'refused', 'reason': 'node_admission_unavailable'}
        assert stream.readline() == b''
    assert not side.calls


@pytest.mark.parametrize('document', [
    {**admit(), 'extra': 'tool'}, {**admit(), 'schema_version': True},
    admit(''), admit('../escape'), admit('has space'), admit('a' * 101), admit(7),
    release(), {**admit(), 'action': 'shell', 'args': {}},
])
def test_malformed_admission_never_enters_callback_or_dispatches_tool(side, document):
    events, closed = [], threading.Event()
    with broker.serve(side, node_admission=callback(events, closed)), connected(side) as stream:
        send(stream, document)
        assert read(stream) == {'status': 'refused', 'reason': 'node_admission_invalid'}
    assert not events and not side.calls


def test_eof_always_exits_admission_context(side):
    events, closed = [], threading.Event()
    with broker.serve(side, node_admission=callback(events, closed)):
        with connected(side) as stream:
            send(stream, admit())
            assert read(stream)['status'] == 'ok'
        assert closed.wait(2)
    assert [e[0] for e in events] == ['enter', 'exit'] and not side.calls


@pytest.mark.parametrize('message', [release('wrong-id'), {**release(), 'schema_version': True},
                                   {**release(), 'extra': 1}, {'action': 'read', 'args': {}}])
def test_wrong_release_refuses_and_cleans_up_without_tool_dispatch(side, message):
    events, closed = [], threading.Event()
    with broker.serve(side, node_admission=callback(events, closed)), connected(side) as stream:
        send(stream, admit())
        assert read(stream)['status'] == 'ok'
        send(stream, message)
        assert read(stream) == {'status': 'refused', 'reason': 'node_release_invalid'}
        assert closed.is_set()
    assert not side.calls


def test_malformed_release_json_cleans_up(side):
    events, closed = [], threading.Event()
    with broker.serve(side, node_admission=callback(events, closed)), connected(side) as stream:
        send(stream, admit())
        assert read(stream)['status'] == 'ok'
        stream.write(b'{invalid json\n')
        assert read(stream)['reason'] == 'node_release_invalid'
        assert closed.is_set()
    assert not side.calls


def test_callback_refusal_is_sanitized_and_never_executes_tool(side):
    @contextmanager
    def refuse(node):
        raise PermissionError('secret custody path /do-not-expose')
        yield
    with broker.serve(side, node_admission=refuse), connected(side) as stream:
        send(stream, admit())
        response = read(stream)
        assert response == {'status': 'refused', 'reason': 'node_admission_error', 'error': 'PermissionError'}
        assert 'secret' not in json.dumps(response)
    assert not side.calls


def test_callback_exit_error_is_not_acknowledged_as_success(side):
    @contextmanager
    def refuse_exit(node):
        yield {'id': 'admission-1'}
        raise PermissionError('private exit failure')
    with broker.serve(side, node_admission=refuse_exit), connected(side) as stream:
        send(stream, admit())
        assert read(stream)['status'] == 'ok'
        send(stream, release())
        assert read(stream) == {'status': 'refused', 'reason': 'node_admission_error', 'error': 'PermissionError'}
    assert not side.calls


def test_regular_persistent_broker_requests_are_unchanged_and_cannot_switch_protocol(side):
    events, closed = [], threading.Event()
    with broker.serve(side, node_admission=callback(events, closed)), connected(side) as stream:
        for request in ({'action': 'read', 'args': {'path': 'a'}}, {'action': 'write', 'args': {'path': 'b'}}):
            send(stream, request)
            assert read(stream) == {'status': 'ok', 'echo': request}
        send(stream, admit())
        assert read(stream) == {'status': 'refused', 'reason': 'node_admission_invalid'}
    assert len(side.calls) == 2 and not events
