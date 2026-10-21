"""The controller build under test, reached through its binding interfaces only.

Every CONTROLLER case gets the modules it needs from ``require_controller`` (the declared
``pending-integration:`` skip while ``ravel.controller`` is absent; an error once it is
installed). What a case needs beyond the binding signatures (record kinds, receipt fields) is named
here, in one place, so the oracles do not depend on a package's internals.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from nc_cases import FIXTURES, require_controller

HOSTILE = FIXTURES / 'scripts' / 'hostile.py'
STORE_ROOT = 'store'
DEFAULT_PROMPT = 'Compute the fictional observable of the toy model at one parameter point.'
MACHINE_CHECKINS = ('approve_plan', 'go', 'deviation', 'final')


def store_root(env):
    return env.root / STORE_ROOT


class Operator:
    """The operator's own channel: ``ravel operator`` run outside every worker, in the case's domain."""

    def __init__(self, env):
        self.env = env
        self.cli = require_controller('authority.cli')
        self.initialized = False

    def __call__(self, *argv):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            status = self.cli.main(list(argv))
        return status, out.getvalue()

    def init(self, mode='physicist-in-the-loop', *extra):
        status, text = self('init', '--mode', mode, '--store-root', str(store_root(self.env)), *extra)
        assert status == 0, text
        self.initialized = True
        return text

    def autonomous(self, *extra):
        return self.init('autonomous', '--machine-checkins', ','.join(MACHINE_CHECKINS), *extra)


def operator(env):
    if getattr(env, 'operator', None) is None:
        env.operator = Operator(env)
    return env.operator


def controller_run(env, name='nc-run-one', *, mode=None, prompt=DEFAULT_PROMPT, freeze=True):
    """A controller-owned run under the operator-configured store root, its mode frozen at intake.

    The operator ledger is written first (``mode``, default physicist-in-the-loop) when the case has
    not written one; a case that needs other settings calls ``operator(env)`` itself first.
    """
    store_module = require_controller('store')
    op = operator(env)
    if not op.initialized:
        op.init(mode or 'physicist-in-the-loop') if mode != 'autonomous' else op.autonomous()
    run_dir = env.root / 'runs' / name
    store = store_module.RunStore.create(run_dir, run_id=name)
    if freeze:
        authority = require_controller('authority')
        authority.freeze_mode(store, {'prompt': prompt}, project=env.root)
    return store, run_dir


CHECKIN_SECTIONS = {
    'approve_plan': [{'id': 'preamble', 'title': 'Plain-language preamble',
                      'lines': ['Compute the fictional observable for the toy model at one point.']}],
    'go': [{'id': 'preamble', 'title': 'Preamble', 'lines': ['The waypoint ran.']},
           {'id': 'waypoint', 'title': 'Waypoint evidence', 'lines': ['Smoke yields within tolerance.']}],
    'deviation': [{'id': 'preamble', 'title': 'Preamble', 'lines': ['An approved input changed.']},
                  {'id': 'change', 'title': 'Change', 'lines': ['tolerance 0.10 -> 0.05']}],
    'final': [{'id': 'preamble', 'title': 'Preamble', 'lines': ['Results are ready.']},
              {'id': 'results', 'title': 'Results', 'lines': ['Observable value 1.0 +- 0.1 (fictional).']}],
    'r3_action': [{'id': 'preamble', 'title': 'Preamble', 'lines': ['An R3 action is proposed.']},
                  {'id': 'action', 'title': 'Action', 'lines': ['Open the blinded region.']}],
}


def checkin_view(store, kind, **pins):
    """Capture fictional compiler/reading evidence before returning its rendered view.

    The trusted fixture models the controller capture boundary. ``request`` does
    not authenticate caller-supplied views; callers can still mutate this return
    value to exercise that refusal.
    """
    view = {'run_id': store.run_id, 'pins': pins or {'plan_sha256': 'a' * 64}, 'sections': CHECKIN_SECTIONS[kind],
            'flags': [{'kind': 'assumption', 'text': 'The toy model has unit coupling.'},
                      {'kind': 'question', 'text': 'Is one point enough?'}],
            'items': {'steps': ['s01 derive the observable'], 'deliverables': ['one number with uncertainty'],
                      'boundaries': ['one model point only']}}
    if kind == 'r3_action':
        view['options'] = [{'id': 'hold', 'text': 'keep the region blinded', 'effect': False},
                           {'id': 'proceed', 'text': 'open the region', 'effect': True}]
    return capture_view(store, kind, view)


def capture_view(store, kind, view):
    """Trusted fixture capture of a complete compiler/reading view, before tampering.

    Call explicitly for custom fixture views. Never pass an adversarial mutation to
    this helper: production request() must refuse unretained caller material.
    """
    from copy import deepcopy
    retained = require_controller('authority.retained')
    authority = require_controller('authority')
    view = deepcopy(view)
    items = view.get('items', {})
    pins = authority.frozen(store).get('request_pins', {})
    plan = {'sha256': view['pins'].get('plan_sha256'),
            **{key: deepcopy(items.get(key, [])) for key in ('steps', 'deliverables', 'boundaries')},
            'request_pins': deepcopy(pins)}
    reading = {'request_pins': {}, 'inferred_critical_facts': [],
               'flags': deepcopy(view.get('flags', [])),
               'items': {key: deepcopy(value) for key, value in items.items()
                         if key not in ('steps', 'deliverables', 'boundaries')}}
    return retained.capture(store, kind, plan=plan, reading=reading, view=view)['view']


class HostileLaunch:
    """One governed launch of ``hostile.py`` through ``confine.popen`` with counters around it."""

    def __init__(self, env, *, run_name='nc-run-one'):
        self.confine = require_controller('confine')
        self.env = env
        self.store, self.run_dir = controller_run(env, run_name)
        self.inputs = self.run_dir / 'inputs'
        self.outputs = self.run_dir / 'outputs' / 'stage-one'
        self.inputs.mkdir(parents=True)
        self.outputs.mkdir(parents=True)
        self.script = self.inputs / 'hostile.py'
        shutil.copy(HOSTILE, self.script)
        self.report = self.outputs / 'report.json'
        self.tools = env.root / 'tools'
        self.tools.mkdir(exist_ok=True)
        self.calls = env.root / 'effects' / 'model-calls'
        self.calls.mkdir(parents=True, exist_ok=True)

    def fake_model_cli(self):
        """A stand-in model CLI on PATH: any start would connect to the listener and leave a call file."""
        cli = self.tools / 'claude'
        port = self.env.effects.listener.port
        cli.write_text(f'#!{sys.executable} -B\n'
                       'import socket, sys, uuid\n'
                       f'open({str(self.calls / "call-")!r} + uuid.uuid4().hex, "w").write("called")\n'
                       f'socket.create_connection(("127.0.0.1", {port}), timeout=2).close()\n')
        cli.chmod(0o755)
        return cli

    def run(self, attempts, *, reads=(), withheld=(), env=None, digests=None, limits=None):
        plan = self.inputs / 'attempts.json'
        plan.write_text(json.dumps(attempts))
        capsule = {'PATH': f'{self.tools}:/usr/bin:/bin', 'LANG': 'C'}
        capsule.update(env or {})
        spec = {'argv': [sys.executable, '-B', str(self.script), str(plan), str(self.report)],
                'env': capsule, 'reads': [str(self.inputs), *map(str, reads)], 'writes': [str(self.report)],
                'run_dir': str(self.run_dir), 'stage': 'stage-one', 'withheld': [str(p) for p in withheld],
                'limits': dict(limits or {'wall_seconds': 120}), 'label': 'nc-hostile'}
        if digests:
            spec['input_digests'] = {**digests,
                str(self.script): hashlib.sha256(self.script.read_bytes()).hexdigest(),
                str(plan): hashlib.sha256(plan.read_bytes()).hexdigest()}
        process = self.confine.popen(spec, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        plan = getattr(process, 'ravel_confinement', None)
        self.record = dict(plan.record) if plan is not None else {}
        stdout, stderr = process.communicate(timeout=180)
        finished = self.confine.finish(process)
        self.returncode, self.stderr = process.returncode, stderr.decode(errors='replace')
        return finished

    def observed(self):
        """The adversary's own report (never an oracle by itself)."""
        return json.loads(self.report.read_text()) if self.report.is_file() else None


def run_cli(argv, *, env_extra=None, cwd=None, timeout=120):
    """``python -m ravel.cli <argv>`` in a child process with the case's environment."""
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, '-B', '-m', 'ravel.cli', *argv], capture_output=True, text=True,
                          env=env, cwd=cwd, timeout=timeout)
