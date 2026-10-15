"""Synthetic interpreter and array-custody controls; no native ML execution."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture
def bound(tmp_path, monkeypatch):
    prefix = tmp_path / 'prefix'
    python = prefix / 'tools/miniforge3/envs/ml/bin/python'
    python.parent.mkdir(parents=True)
    python.write_text(f'#!{sys.executable}\n' + '''import json, sys
from pathlib import Path
with Path(__file__).with_name('calls.log').open('a') as calls:
    calls.write(sys.argv[3] + chr(10))
if sys.argv[3] == 'probe':
    print(json.dumps({'torch': True, 'torch-geometric': True,
                      'versions': {'torch': '0.0', 'torch-geometric': '0.0'}}))
else:
    import numpy as np
    request = json.loads(Path(sys.argv[4]).read_text())
    with np.load(request['arrays'], allow_pickle=False) as arrays:
        if request['action'] == 'fit':
            assert set(arrays.files) == {'train_x', 'train_y', 'train_weight'}
            np.savez(request['output'], mean=np.zeros(2), scale=np.ones(2),
                     w=np.ones(2), b=np.zeros(1))
        else:
            assert arrays.files == ['predict_x']
            np.savez(request['output'], scores=np.full(len(arrays['predict_x']), .5))
''')
    python.chmod(0o755)
    monkeypatch.setenv('RAVEL_NATIVE_BUILD', str(prefix))
    return python


def test_bound_interpreter_available_without_host_torch(bound, monkeypatch):
    from ravel.physics import ml_backends, ml_runtime
    original = ml_backends.find_spec
    def host(package):
        if package in ('torch', 'torch_geometric'):
            pytest.fail('host ML package probe')
        return original(package)
    monkeypatch.setattr(ml_backends, 'find_spec', host)
    assert ml_runtime.available() == {'torch': True, 'torch-geometric': True}
    assert ml_backends.available()['torch-geometric'] is True


def test_missing_environment_returns_install_command(tmp_path, monkeypatch):
    from ravel.physics import ml_runtime
    monkeypatch.setenv('RAVEL_NATIVE_BUILD', str(tmp_path / 'missing'))
    result = ml_runtime.available(details=True)
    assert result['available'] == {'torch': False, 'torch-geometric': False}
    assert result['install_command'][0] == 'bash'
    assert result['install_command'][1].endswith('scripts/setup/install.sh')
    assert result['install_command'][-2:] == ['--prefix', str(tmp_path / 'missing')]


def test_availability_probe_runs_once_per_installed_interpreter(bound):
    from ravel.physics import ml_backends
    x = np.array([[-1., 0.], [1., 0.], [-2., 1.], [2., 1.]]); y = np.array([0., 1., 0., 1.])
    for _ in range(3):
        assert ml_backends.available()['torch'] is True
    # A host arm consults availability; it must not launch the ML interpreter again.
    ml_backends.fit({'backend': 'numpy', 'architecture': 'logistic', 'config': {'learning_rate': .1}},
                    x, y, np.ones(4), 1, 2, lambda: None)
    assert bound.with_name('calls.log').read_text().split() == ['probe']
    # A replaced interpreter is a different installation and is probed afresh.
    bound.write_text(f'#!{sys.executable}\nimport json\n'
                     'print(json.dumps({"torch": False, "torch-geometric": False, "versions": {}}))\n')
    assert ml_backends.available()['torch'] is False


def test_unresolved_binding_reports_native_unavailable_and_keeps_host_backends(tmp_path, monkeypatch):
    from ravel.physics import ml_backends, ml_runtime
    from ravel.setup import manifest
    monkeypatch.setattr(manifest, 'manifest_path', lambda repo=None: tmp_path / 'absent.json')
    result = ml_runtime.available(details=True)
    assert result['available'] == {'torch': False, 'torch-geometric': False}
    assert result['interpreter'] is None and result['install_command'] is None
    assert 'binding' in result['reason']
    host = ml_backends.available()
    assert host['numpy'] is True and host['torch'] is False and host['torch-geometric'] is False


def test_worker_environment_ignores_modules_beside_the_script(tmp_path):
    import subprocess
    from ravel.physics import ml_runtime
    (tmp_path / 'json.py').write_text('raise SystemExit(9)\n')
    script = tmp_path / 'script.py'
    script.write_text('import json\n')
    proc = subprocess.run([sys.executable, '-B', str(script)], env=ml_runtime._environment(), timeout=20)
    assert proc.returncode == 0


@pytest.mark.parametrize('planted', ['test_x', 'test_y', 'test_weight', 'test_split', 'renamed'])
def test_worker_refuses_unlisted_arrays_before_backend_import(tmp_path, monkeypatch, planted):
    from ravel.physics import ml_worker
    arrays = tmp_path / 'arrays.npz'
    np.savez(arrays, train_x=np.zeros((4, 2)), train_y=np.array([0., 1., 0., 1.]),
             train_weight=np.ones(4), **{planted: np.ones(4)})
    monkeypatch.setattr(ml_worker, '_local_backends', lambda: pytest.fail('backend imported before custody'))
    with pytest.raises(ValueError, match='arrays'):
        ml_worker.execute(fit_request(arrays, tmp_path / 'out.npz'))
    assert not (tmp_path / 'out.npz').exists()


def fit_request(arrays, output):
    return {'schema_version': 1, 'action': 'fit', 'arrays': str(arrays),
            'output': str(output), 'arm': {'backend': 'torch', 'architecture': 'logistic',
            'config': {'learning_rate': .1}}, 'seed': 1, 'epochs': 2}


def test_worker_train_and_validation_only(tmp_path, monkeypatch):
    from ravel.physics import ml_worker
    arrays = tmp_path / 'arrays.npz'
    data = {name + '_' + key: value for name in ('train', 'val') for key, value in
            {'x': np.zeros((4, 2)), 'y': np.array([0., 1., 0., 1.]), 'weight': np.ones(4)}.items()}
    np.savez(arrays, **data)
    seen = []
    def fit(arm, x, y, weight, seed, epochs, deadline):
        seen.append((x, y, weight))
        return {'mean': np.zeros(2), 'scale': np.ones(2), 'w': np.ones(2), 'b': np.zeros(1)}
    monkeypatch.setattr(ml_worker, '_local_backends', lambda: SimpleNamespace(
        FAMILIES={'torch': {'logistic'}}, _runtime_local_fit=fit))
    ml_worker.execute(fit_request(arrays, tmp_path / 'out.npz'))
    assert len(seen) == 1
    np.testing.assert_array_equal(seen[0][0], data['train_x'])


@pytest.mark.parametrize('backend', ['torch', 'torch-geometric'])
def test_fit_predict_use_bound_worker_and_array_files(bound, monkeypatch, backend):
    from ravel.physics import ml_runtime, ml_backends
    monkeypatch.setattr(ml_runtime, '_admit', lambda: 2.)
    x = np.ones((4, 2)); y = np.array([0., 1., 0., 1.])
    arm = {'backend': backend, 'architecture': 'gnn' if backend == 'torch-geometric' else 'logistic',
           'config': {'learning_rate': .1}}
    checks = []
    state = ml_backends.fit(arm, x, y, np.ones(4), 1, 2, lambda: checks.append(True))
    assert str(state['_runtime_backend']) == backend
    np.testing.assert_array_equal(ml_backends.predict(state, x), np.full(4, .5))
    assert checks


def test_unadmitted_fit_refuses_before_process_launch(bound, monkeypatch):
    from ravel.physics import ml_runtime
    monkeypatch.setattr(ml_runtime.subprocess, 'Popen', lambda *a, **k: pytest.fail('unadmitted launch'))
    with pytest.raises(ValueError, match='supervised'):
        ml_runtime.fit({'backend': 'torch'}, np.zeros((4, 2)), np.zeros(4), np.ones(4), 1, 2, lambda: None)


def test_manifest_registration_fragment_is_idempotent():
    from ravel.setup import manifest
    root = manifest.repo_root()
    doc = json.loads((root / 'src/ravel/data/tools/registration/ml-training.manifest-operation.json').read_text())
    assert doc['operations'] == [{'mode': 'ml-training', 'groups': ['python-host', 'ml']}]
    assert doc['merge'] == 'upsert-identical-or-refuse'
    current = manifest.read_json(manifest.manifest_path(root))
    assert [r for r in current['operations'] if r['mode'] == 'ml-training'] == doc['operations']


def test_unknown_checkpoint_array_refused_before_backend_import(tmp_path, monkeypatch):
    from ravel.physics import ml_worker
    arrays, state = tmp_path / 'arrays.npz', tmp_path / 'state.npz'
    np.savez(arrays, predict_x=np.ones((4, 2)))
    np.savez(state, mean=np.zeros(2), scale=np.ones(2), w=np.ones(2), b=np.zeros(1), renamed=np.ones(4))
    monkeypatch.setattr(ml_worker, '_local_backends', lambda: pytest.fail('undeclared state reached backend'))
    with pytest.raises(ValueError, match='state'):
        ml_worker.execute({'schema_version': 1, 'action': 'predict', 'arrays': str(arrays),
                           'state': str(state), 'output': str(tmp_path / 'out.npz'), 'backend': 'torch'})


def test_deadline_cleans_up_only_started_worker(bound, monkeypatch):
    from ravel.physics import ml_runtime
    bound.write_text(f'#!{sys.executable}\nimport time\ntime.sleep(30)\n')
    original = ml_runtime.subprocess.Popen
    processes = []
    def launch(*args, **kwargs):
        proc = original(*args, **kwargs); processes.append(proc)
        return proc
    monkeypatch.setattr(ml_runtime.subprocess, 'Popen', launch)
    monkeypatch.setattr(ml_runtime, '_admit', lambda: 2.)
    def deadline():
        if processes:
            raise ValueError('synthetic deadline exhausted')
    with pytest.raises(ValueError, match='synthetic deadline'):
        ml_runtime.fit({'backend': 'torch', 'architecture': 'logistic', 'config': {'learning_rate': .1}},
                       np.zeros((4, 2)), np.array([0., 1., 0., 1.]), np.ones(4), 1, 2, deadline)
    assert len(processes) == 1 and processes[0].poll() is not None


def test_admission_uses_method_and_current_worker_custody(tmp_path, monkeypatch):
    from ravel.physics import ml_runtime
    from ravel.workflow import science, method_selection
    monkeypatch.setattr(sys.modules['__main__'], '__spec__', SimpleNamespace(name='ravel.physics.science_worker'))
    monkeypatch.setattr(sys, 'argv', ['science_worker.py', str(tmp_path)])
    calls = []
    monkeypatch.setattr(method_selection, 'require_launch', lambda root, plan: calls.append(('method', root, plan)))
    monkeypatch.setattr(science, 'verify_worker', lambda root: calls.append(('custody', root)) or {'max_seconds': 7})
    monkeypatch.setattr(science, 'execution_spec', lambda root: {'mode': 'ml-training'})
    assert ml_runtime._admit() == 7
    assert calls == [('method', tmp_path.resolve(), 'science'), ('custody', tmp_path.resolve())]
    monkeypatch.setattr(science, 'verify_worker', lambda root: (_ for _ in ()).throw(ValueError('custody refused')))
    with pytest.raises(ValueError, match='custody refused'):
        ml_runtime._admit()


def test_worker_cli_refuses_test_arrays(tmp_path):
    import subprocess
    from ravel.physics import ml_runtime
    arrays = tmp_path / 'arrays.npz'
    np.savez(arrays, train_x=np.zeros((4, 2)), train_y=np.zeros(4), train_weight=np.ones(4), test_x=np.ones((4, 2)))
    request = tmp_path / 'request.json'
    request.write_text(json.dumps(fit_request(arrays, tmp_path / 'output.npz')))
    proc = subprocess.run([sys.executable, '-B', str(ml_runtime.WORKER), 'execute', str(request)],
                          env=ml_runtime._environment(), capture_output=True, text=True, timeout=5)
    assert proc.returncode != 0 and 'custody' in proc.stderr
    assert not (tmp_path / 'output.npz').exists()
