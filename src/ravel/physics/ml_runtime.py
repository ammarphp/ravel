"""Bind native ML calls to the manifest interpreter within a supervised study.

The executor retains split exposure and selection authority. This transport
accepts only explicitly named adaptive arrays for fit and unlabeled features
for prediction. Array names are a protocol boundary, not proof of provenance.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import numpy as np

NATIVE = ('torch', 'torch-geometric')
WORKER = Path(__file__).with_name('ml_worker.py')
_READY = {}  # one complete probe response, keyed by the interpreter file identity


def binding(*, repo=None, prefix=None):
    """Resolve the installed interpreter using the installer's prefix rules."""
    from ravel.setup import manifest as mf
    from ravel.setup.installer import resolve_prefix
    repo = Path(repo or mf.repo_root())
    prefix = resolve_prefix(repo, prefix)
    document = mf.read_json(mf.manifest_path(repo))
    group = mf.by_id(document)['ml']
    paths = {step['python'] for step in group['steps'] if step['kind'] == 'pip'}
    if len(paths) != 1:
        raise ValueError('manifest requires one ML interpreter')
    values = mf.variables(prefix, repo, mf.detect_platform())
    interpreter = Path(mf.expand(paths.pop(), values))
    return {'interpreter': str(interpreter), 'install_command':
            ['bash', str(repo / 'scripts/setup/install.sh'), '--only', 'ml', '--prefix', str(prefix)]}


def _environment():
    # Keep the supervisor job token; use this source tree in the separate env.
    # Safe-path mode keeps modules beside the worker script off its import path.
    env = dict(os.environ, PYTHONPATH=str(WORKER.resolve().parents[2]), PYTHONDONTWRITEBYTECODE='1',
               PYTHONSAFEPATH='1')
    for key in ('PYTHONHOME', 'PYTHONSTARTUP'):
        env.pop(key, None)
    return env


def available(*, details=False):
    """Probe installed ML imports, never the RAVEL host's package population.

    ``details=True`` also returns the interpreter, versions and install command.
    A readiness probe neither trains a model nor grants launch authority.
    """
    result = {'interpreter': None, 'install_command': None, 'available': dict.fromkeys(NATIVE, False),
              'versions': {}, 'reason': 'missing ML interpreter'}
    try:
        result.update(binding())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Host backends stay usable where no manifest or platform route resolves.
        result['reason'] = f'ML interpreter binding unresolved: {type(exc).__name__}'
        return result if details else result['available']
    python = Path(result['interpreter'])
    if python.is_file() and os.access(python, os.X_OK):
        try:
            stat = python.stat()
            key = (str(python), stat.st_ino, stat.st_size, stat.st_mtime_ns)
            record = _READY.get(key)
            if record is None:
                probe = subprocess.run([str(python), '-B', str(WORKER), 'probe'],
                                       env=_environment(), capture_output=True, text=True, timeout=10, check=True)
                record = json.loads(probe.stdout)
                if any(type(record[name]) is not bool for name in NATIVE):
                    raise ValueError('invalid ML availability response')
            result['available'] = {'torch': record['torch'],
                                   'torch-geometric': record['torch'] and record['torch-geometric']}
            result['versions'] = record.get('versions', {})
            result['reason'] = '' if all(result['available'].values()) else 'ML imports unavailable'
            if all(result['available'].values()):
                # Host arms consult availability on every fit. Retain only a complete
                # installation; an absent, partial or failed one is probed again.
                _READY.clear()
                _READY[key] = record
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
            result['reason'] = f'ML interpreter probe failed: {type(exc).__name__}'
    return result if details else result['available']


def _admit():
    """Reuse actual science-worker custody, method decision and admission.

    There is no standalone training launch path. The worker inherits its
    supervisor process group, machine lease and hard wall-time enforcement.
    """
    from ravel.workflow import science, method_selection
    main = sys.modules.get('__main__')
    if getattr(getattr(main, '__spec__', None), 'name', None) != 'ravel.physics.science_worker' or len(sys.argv) < 2:
        raise ValueError('ML calls require the admitted supervised science worker')
    root = Path(sys.argv[1]).resolve()
    method_selection.require_launch(root, 'science')
    proposal = science.verify_worker(root)
    if science.execution_spec(root)['mode'] != 'ml-training':
        raise ValueError('ML calls require the supervised ML operation')
    return float(proposal['max_seconds'])


def _exchange(request, arrays, *, state=None, check_deadline=lambda: None):
    ceiling = _admit()
    check_deadline()
    python = binding()['interpreter']
    if not Path(python).is_file() or not os.access(python, os.X_OK):
        raise ValueError('ML interpreter missing; run ' + ' '.join(binding()['install_command']))
    from .ml_worker import load_arrays, validate_arrays, validate_state
    validate_arrays(arrays, request['action'])
    if state is not None:
        validate_state(state)
    with tempfile.TemporaryDirectory(prefix='ravel-ml-') as directory:
        root = Path(directory)
        inputs, output = root / 'arrays.npz', root / 'output.npz'
        np.savez(inputs, **arrays)
        request = {**request, 'schema_version': 1, 'arrays': str(inputs), 'output': str(output)}
        if state is not None:
            checkpoint = root / 'state.npz'
            np.savez(checkpoint, **state)
            request['state'] = str(checkpoint)
        control = root / 'request.json'
        control.write_text(json.dumps(request, allow_nan=False))
        started = time.monotonic()
        # File-backed logs prevent a pipe deadlock or unbounded captured output.
        with (root / 'worker.log').open('w+b') as log:
            proc = subprocess.Popen([python, '-B', str(WORKER), 'execute', str(control)],
                                    env=_environment(), stdout=log, stderr=subprocess.STDOUT)
            try:
                while True:
                    check_deadline()
                    if time.monotonic() - started > ceiling:
                        raise ValueError('ML worker wall budget exhausted')
                    try:
                        code = proc.wait(timeout=.05)
                        break
                    except subprocess.TimeoutExpired:
                        pass
                check_deadline()
                if code:
                    raise ValueError(f'ML worker failed with exit code {code}')
                result = load_arrays(output)
                if request['action'] == 'predict':
                    if set(result) != {'scores'}:
                        raise ValueError('invalid ML worker scores')
                    scores = result['scores']
                    if scores.shape != (len(arrays['predict_x']),) or not np.isfinite(scores).all() or np.any((scores < 0) | (scores > 1)):
                        raise ValueError('invalid ML worker scores')
                else:
                    validate_state(result)
                return result
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=1)


def fit(arm, x, y, weights, seed, epochs, check_deadline, *, validation=None):
    arrays = {'train_x': x, 'train_y': y, 'train_weight': weights}
    if validation is not None:
        if set(validation) != {'x', 'y', 'weight'}:
            raise ValueError('validation arrays require x, y, weight only')
        arrays.update({'val_' + key: value for key, value in validation.items()})
    state = _exchange({'action': 'fit', 'arm': arm, 'seed': seed, 'epochs': epochs}, arrays,
                      check_deadline=check_deadline)
    return {**state, '_runtime_backend': np.array(arm['backend'])}


def predict(state, x):
    backend = str(state['_runtime_backend'])
    if backend not in NATIVE:
        raise ValueError('unsupported ML runtime backend')
    model = {k: v for k, v in state.items() if k != '_runtime_backend'}
    return _exchange({'action': 'predict', 'backend': backend}, {'predict_x': x}, state=model)['scores']


def bind(namespace):
    """Single backend seam, leaving the local algorithms available to the worker."""
    local_fit, local_predict = namespace['fit'], namespace['predict']
    namespace['_runtime_local_fit'], namespace['_runtime_local_predict'] = local_fit, local_predict
    # The worker executes these same source algorithms under the bound env.
    if Path(sys.argv[0]).resolve() == WORKER.resolve():
        return

    def bound_available():
        host = {name: namespace['find_spec'](package) is not None
                for name, package in namespace['PACKAGES'].items() if name not in NATIVE}
        return {**host, **available()}

    def bound_fit(arm, x, y, weights, seed, epochs, check_deadline):
        if arm.get('backend') in NATIVE:
            return fit(arm, x, y, weights, seed, epochs, check_deadline)
        return local_fit(arm, x, y, weights, seed, epochs, check_deadline)

    def bound_predict(state, x):
        if '_runtime_backend' in state:
            return predict(state, x)
        return local_predict(state, x)

    namespace.update(available=bound_available, fit=bound_fit, predict=bound_predict)
