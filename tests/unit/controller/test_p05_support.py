"""Shared P05 fakes: a controller store, run ownership and an operator configuration.

They follow the store ownership and authority configuration/current-resource-bound
signatures; the tests install them as modules so production imports resolve to them.
"""
import json
from pathlib import Path
import sys
import types

import pytest


class FakeStore:
    """Append-only JSON-lines store per run, outside every run directory."""
    roots = {}

    def __init__(self, run_id, *, root=None):
        self.run_id = run_id
        self.root = Path(root or FakeStore.roots[run_id])
        self.root.mkdir(parents=True, exist_ok=True)

    def _file(self, kind):
        return self.root / f'{kind}.jsonl'

    def append(self, kind, record):
        record_id = f'{kind}-{len(self.scan(kind)) + 1:06d}'
        with self._file(kind).open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'id': record_id, 'kind': kind, 'record': record}, sort_keys=True) + '\n')
        return record_id

    def read(self, kind, record_id):
        return next(row['record'] for row in self.scan(kind) if row['id'] == record_id)

    def scan(self, kind):
        path = self._file(kind)
        return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []

    def checkpointer(self):
        raise NotImplementedError('the P05 fake has no checkpointer')

    def path(self, *parts):
        return self.root.joinpath(*parts)


def own(monkeypatch, store_root, runs):
    """Make every run directory in ``runs`` (path -> run id) controller-owned, its store under ``store_root``."""
    owned = {str(Path(path).resolve()): run_id for path, run_id in runs.items()}
    for run_id in owned.values():
        FakeStore.roots[run_id] = Path(store_root) / run_id
    module = types.ModuleType('ravel.controller.store')
    module.RunStore = FakeStore
    module.controller_owned = lambda run_dir: owned.get(str(Path(run_dir).resolve()))
    monkeypatch.setitem(sys.modules, 'ravel.controller.store', module)
    return {run_id: FakeStore(run_id) for run_id in owned.values()}


@pytest.fixture
def sandboxed():
    """This host's OS sandbox, qualified by the launcher's own probe; skipped only where it is unavailable.

    A sandbox that runs but fails a denial probe is a failure, not a skip.
    """
    from ravel.controller.confine import launcher
    from ravel.workflow import sandbox
    kind = sandbox.available()
    if kind is None:
        pytest.skip('sandbox-blocked: no sandbox-exec or bwrap on this host')
    try:
        launcher.qualify(kind)
    except sandbox.SandboxUnavailable as exc:
        pytest.skip(f'sandbox-blocked: {exc}')
    return kind


def operator(monkeypatch, config):
    """Install the fixture operator configuration and its current resource envelope."""
    module = types.ModuleType('ravel.controller.authority')
    module.operator_config = lambda: dict(config)
    module.effective_bounds = lambda store: {'budgets': dict(config.get('budgets') or {})}
    monkeypatch.setitem(sys.modules, 'ravel.controller.authority', module)


def test_fake_authority_preserves_the_declared_retained_storage_requirement(monkeypatch):
    operator(monkeypatch, {'budgets': {'retained_disk_bytes': 1024}})
    from ravel.controller.authority import effective_bounds
    assert effective_bounds(object()) == {'budgets': {'retained_disk_bytes': 1024}}


def test_fake_store_appends_scans_and_owns_only_its_runs(tmp_path, monkeypatch):
    run = tmp_path / 'run'
    run.mkdir()
    stores = own(monkeypatch, tmp_path / 'store', {run: 'run-a'})
    from ravel.controller.confine import runs
    assert runs.owner(run) == 'run-a' and runs.owner(tmp_path) is None
    assert runs.owner_of(run / 'deeper' / 'path') == ('run-a', run.resolve())
    first = stores['run-a'].append('kind', {'n': 1})
    assert stores['run-a'].read('kind', first) == {'n': 1}
    assert [row['record'] for row in runs.store('run-a').scan('kind')] == [{'n': 1}]


def test_absent_controller_modules_mean_no_ownership_and_no_permission(tmp_path, monkeypatch):
    monkeypatch.delitem(sys.modules, 'ravel.controller.store', raising=False)
    monkeypatch.delitem(sys.modules, 'ravel.controller.authority', raising=False)
    from ravel.controller.confine import runs
    original_import = runs.importlib.import_module
    def unavailable(name):
        if name in ('ravel.controller.store', 'ravel.controller.authority') and name not in sys.modules:
            raise ModuleNotFoundError('fixture module unavailable: ' + name, name=name)
        return original_import(name)
    monkeypatch.setattr(runs.importlib, 'import_module', unavailable)
    assert runs.owner(tmp_path) is None and runs.owner_of(tmp_path) is None
    operator(monkeypatch, {})
    assert runs.operator_settings() == {} and runs.allow_unconfined() is False
    operator(monkeypatch, {'allow_unconfined': 'yes'})
    assert runs.allow_unconfined() is False, 'only the literal true permits it'
    operator(monkeypatch, {'allow_unconfined': True})
    assert runs.allow_unconfined() is True


def test_a_controller_store_that_fails_to_import_is_not_read_as_absent(monkeypatch):
    def broken(name):
        raise ModuleNotFoundError("No module named 'a_dependency'", name='a_dependency')
    from ravel.controller.confine import runs
    monkeypatch.setattr(runs.importlib, 'import_module', broken)
    with pytest.raises(ModuleNotFoundError):
        runs.owner('/nonexistent')
