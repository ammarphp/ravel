"""Scheduler commands of a confined workflow child, served by its controller's submission broker.

A brokered site profile's ``ravel-submit.sh``, ``ravel-status.sh`` and ``ravel-cancel.sh``
run this module. The child holds no launch capability, no scheduler command and no run
store access; it names one job script or job handle in a narrow typed request over the
controller-owned Unix socket in ``RAVEL_WMS_BROKER`` and receives only a handle, a job state
or a refusal. Standard library only.

``submit <jobscript>`` prints the job handle (exit 0) or the refusal on stderr (exit 1).
``status <job>`` prints ``running``, ``success`` or ``failed``; an unreachable broker or an
unreadable answer is ``failed``, never success. ``cancel <job>...`` requests removal.
"""
import json
import os
import socket
import sys

BROKER_ENV = 'RAVEL_WMS_BROKER'
PYTHON_ENV = 'RAVEL_WMS_BROKER_PYTHON'
MESSAGE_LIMIT = 64 * 1024
CONNECT_SECONDS = 20
READ_SECONDS = 60
STATES = ('running', 'success', 'failed')


def request(message, *, path=None):
    """Send one JSON request to the broker and return its decoded JSON reply."""
    path = path if path is not None else os.environ.get(BROKER_ENV, '')
    if not path or not os.path.isabs(path):
        raise OSError(BROKER_ENV + ' must name the absolute path of the controller submission broker')
    data = (json.dumps(message, sort_keys=True, allow_nan=False) + '\n').encode()
    if len(data) > MESSAGE_LIMIT:
        raise ValueError('broker request exceeds 64 KiB')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stream:
        stream.settimeout(CONNECT_SECONDS)
        stream.connect(path)
        stream.settimeout(READ_SECONDS)
        stream.sendall(data)
        stream.shutdown(socket.SHUT_WR)
        received = bytearray()
        while b'\n' not in received:
            chunk = stream.recv(8192)
            if not chunk:
                break
            received.extend(chunk)
            if len(received) > MESSAGE_LIMIT:
                raise ValueError('broker reply exceeds 64 KiB')
    line, newline, _ = bytes(received).partition(b'\n')
    if not newline:
        raise ValueError('the broker closed the connection without a complete reply')
    reply = json.loads(line.decode())
    if not isinstance(reply, dict) or type(reply.get('ok')) is not bool:
        raise ValueError('the broker reply is not a typed answer')
    return reply


def _error(reply):
    return str(reply.get('error') or 'the broker refused the request')


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    command, operands = (argv[0], argv[1:]) if argv else (None, [])
    if command == 'submit' and len(operands) == 1:
        try:
            reply = request({'op': 'submit', 'jobscript': os.path.abspath(operands[0])})
        except (OSError, ValueError) as exc:
            print('submission broker unavailable: ' + str(exc), file=sys.stderr)
            return 1
        job = reply.get('job')
        if reply['ok'] and isinstance(job, str) and job and '\n' not in job:
            print(job)
            return 0
        print(_error(reply) if not reply['ok'] else 'the broker returned no job handle', file=sys.stderr)
        return 1
    if command == 'status' and len(operands) == 1:
        try:
            reply = request({'op': 'status', 'job': operands[0]})
        except (OSError, ValueError) as exc:
            print('submission broker unavailable: ' + str(exc), file=sys.stderr)
            reply = {'ok': False}
        state = reply.get('state') if reply.get('ok') else None
        if not reply.get('ok') and reply.get('error'):
            print(_error(reply), file=sys.stderr)
        # An unreachable broker or an unreadable state never reads as success.
        print(state if state in STATES else 'failed')
        return 0
    if command == 'cancel' and operands:
        try:
            reply = request({'op': 'cancel', 'jobs': operands})
        except (OSError, ValueError) as exc:
            print('submission broker unavailable: ' + str(exc), file=sys.stderr)
            return 1
        if not reply['ok']:
            print(_error(reply), file=sys.stderr)
            return 1
        if reply.get('failed'):
            print('cancellation was not accepted for: ' + ' '.join(map(str, reply['failed'])), file=sys.stderr)
            return 1
        return 0
    print('usage: wms_broker_client submit <jobscript> | status <job> | cancel <job>...', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
