"""Hostile authored script for governed-launch cases (inert: no model, no provider, no real network).

    python hostile.py <attempts.json> <report path>

Performs each scripted attempt (write a protected path, read a credential or withheld source,
open a socket, start a program, dump the environment, leave a detached process) and writes what
it observed to the report, its one declared output. The report is the adversary's own account;
cases never trust it and count effects from outside the launch.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys


def attempt(op, func):
    try:
        return {'op': op, 'ok': True, 'result': func()}
    except BaseException as exc:
        return {'op': op, 'ok': False, 'error': f'{type(exc).__name__}: {exc}'}


def write(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text)
    return path


def connect(host, port):
    with socket.create_connection((host, port), timeout=2):
        return 'connected'


def main(argv):
    attempts = json.loads(Path(argv[0]).read_text())
    report = []
    for item in attempts:
        op = item['op']
        if op == 'write':
            report.append(attempt(op, lambda: write(item['path'], item.get('text', 'hostile'))))
        elif op == 'append':
            report.append(attempt(op, lambda: Path(item['path']).open('a').write(item.get('text', 'hostile'))))
        elif op == 'read':
            report.append(attempt(op, lambda: Path(item['path']).read_text(errors='replace')))
        elif op == 'listdir':
            report.append(attempt(op, lambda: sorted(os.listdir(item['path']))))
        elif op == 'symlink_write':
            def through_link():
                os.symlink(item['target'], item['link'])
                return write(item['link'], item.get('text', 'hostile'))
            report.append(attempt(op, through_link))
        elif op == 'connect':
            report.append(attempt(op, lambda: connect(item.get('host', '127.0.0.1'), item['port'])))
        elif op == 'exec':
            report.append(attempt(op, lambda: subprocess.run(item['argv'], capture_output=True, text=True,
                                                             timeout=20).returncode))
        elif op == 'spawn':
            report.append(attempt(op, lambda: subprocess.Popen(item['argv'], start_new_session=True,
                                                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                               stderr=subprocess.DEVNULL).pid))
        elif op == 'env':
            report.append(attempt(op, lambda: dict(os.environ)))
        else:
            report.append({'op': op, 'ok': False, 'error': 'unknown scripted attempt'})
    write(argv[1], json.dumps(report, indent=1, sort_keys=True, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
