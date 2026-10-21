"""Run one governed worker through ``launch`` and ``supervise`` with inert seams.

The dispatcher's whole path runs: the launch reservation, the actor it assigns at spawn, the
supervisor's completion and the receipt registration. Only the outer edges are replaced: the
supervisor runs in this process, the sandbox profile, the broker socket and the control
socket are inert, the child is an interpreter that exits at once, and the CLI adapter's
observation of that child is supplied by the test. No model, network or native tool runs.
"""
import contextlib
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import threading
from unittest import mock

from ravel.workflow import agent_worker
from ravel.workflow.transports import cli_worker

TRANSPORT = 'synthetic-cli'
MODEL = 'synthetic-model'
# The seams are module attributes; a graph that dispatches from several threads takes turns here.
_SEAMS = threading.RLock()


class _Supervisor:
    pid = 2 ** 22 + 7


class _Server:
    def __init__(self, path, handler):
        Path(path).touch()

    def serve_forever(self):
        pass

    def shutdown(self):
        pass

    def server_close(self):
        pass


def descriptor(*, transport_id=TRANSPORT, model_id=MODEL, family='synthetic', kind='cli-worker'):
    """A trusted launch descriptor for an inert child."""
    return {'argv': [sys.executable, '-S', '-c', 'pass'],
            'transport': {'id': transport_id, 'transport_kind': kind, 'declaration_sha256': None,
                          'probe_sha256': None},
            'model': {'requested': model_id, 'observed': None, 'family': family, 'effort': None}}


def review_packet(rundir, point_id, role, n=1, round_=0):
    """The role projection the review graph hands reviewer ``n`` of ``point_id`` (``review_projection.packet_for``).

    A review worker earns independent credit only with this RAVEL-built packet; pass it to
    ``supervised(..., packet=...)`` as the review graph passes it to the dispatcher.
    """
    from ravel.workflow import review_points, review_projection
    facts = review_points._facts(rundir)
    point = next(p for p in review_points.derive(facts) if p['id'] == point_id)
    item = {'key': f'r{round_}:{point_id}:{role}:{n}', 'point_id': point_id, 'role': role, 'n': n, 'round': round_,
            'at': point['when']['at'], 'subject_sha256': review_points.subject_digest(facts, point),
            'claim_id': point.get('claim_id'), 'node_id': point.get('node_id'), 'gate': point['gate'],
            'mode': point['mode'], 'findings': {}}
    return review_projection.packet_for(rundir, item)


def reserved(rundir, spec, launch_spec=None):
    """The dispatcher's launch reservation alone: the actor is assigned and the launch is on record,
    and no supervisor runs. A stub adapter that then hands ``finish`` its own execution record
    stands for a transport the dispatcher launched and observed."""
    launch_spec = descriptor() if launch_spec is None else launch_spec
    with _SEAMS, mock.patch.object(agent_worker.sandbox, 'available', lambda: 'inert-test-seam'), \
            mock.patch.object(agent_worker.subprocess, 'Popen', lambda argv, **kwargs: _Supervisor()):
        return agent_worker.launch(rundir, spec, launch_spec=launch_spec, wait=False)


def supervised(rundir, spec, *, final, session, attestation='transport_attested', launch_spec=None,
               observed=None, **options):
    """Launch and supervise one worker; ``attestation`` and ``session`` are what the adapter observed."""
    launch_spec = descriptor() if launch_spec is None else launch_spec

    def start(argv, **kwargs):
        # Only the supervisor command is replaced; it runs in this process below.
        if 'ravel.workflow.agent_worker' in argv:
            return _Supervisor()
        return popen(argv, **kwargs)

    def observe(run, described, ws, worker_spec, execution):
        return {'final': deepcopy(final), 'session_id': session, 'attestation': attestation,
                'transport': deepcopy(described['transport']), 'model': deepcopy(described['model']),
                **(observed or {})}

    seams = [(agent_worker.sandbox, 'available', lambda: 'inert-test-seam'),
             (agent_worker.sandbox, 'probe', lambda *a, **k: {'backend': 'inert-test-seam', 'confirmed': True}),
             (agent_worker.sandbox, 'command', lambda ws, argv, **k: argv),
             (agent_worker.broker, 'serve', lambda made: contextlib.nullcontext()),
             (agent_worker.socketserver, 'ThreadingUnixStreamServer', _Server),
             (agent_worker.signal, 'signal', lambda *a: None),
             (agent_worker.subprocess, 'Popen', start),
             (cli_worker, 'observe', observe)]
    with _SEAMS, contextlib.ExitStack() as stack:
        popen = subprocess.Popen
        for target, name, value in seams:
            stack.enter_context(mock.patch.object(target, name, value))
        state = agent_worker.launch(rundir, spec, launch_spec=launch_spec, wait=False,
                                    **{k: v for k, v in options.items() if k in ('packet', 'protected', 'effect')})
        if state['status'] == 'running':
            agent_worker.supervise(Path(rundir), spec['node_id'], spec['attempt'])
    return agent_worker.load_receipt(rundir, spec['node_id'], spec['attempt'])
