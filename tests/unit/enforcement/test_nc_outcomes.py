"""Exercise the actual collection and outcome hooks in isolated, inert pytest processes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

PLUGIN = Path(__file__).with_name('conftest.py')
CASE_FILE = 'tests/unit/enforcement/test_nc_toy.py'


def _run(tmp_path, body, *, installed=False, missing=False, added_population=False, peer=False):
    root = tmp_path / 'toy-suite'
    cases = root / 'tests' / 'unit' / 'enforcement'
    cases.mkdir(parents=True)
    declarations = [{'id': 'Q01', 'status': 'implemented', 'binding': 'installed',
                     'test': f'{CASE_FILE}::test_Q01'}]
    if missing:
        declarations.append({'id': 'Q02', 'status': 'implemented', 'binding': 'installed',
                             'test': f'{CASE_FILE}::test_Q02'})
    document = {'bespoke': declarations, 'groups': {}, 'parameterized': {}}
    (root / 'bindings.json').write_text(json.dumps(document))
    (root / 'pytest.ini').write_text('[pytest]\n')
    # The real hook module is loaded unchanged; only its registry inputs describe this tiny suite.
    (cases / 'conftest.py').write_text(f'''
import importlib.util
import json
from pathlib import Path
import sys
import types

sys.path.insert(0, {str(PLUGIN.parent)!r})
cases = types.ModuleType('nc_cases')
cases.ROOT = Path({str(root)!r})
cases.PENDING_INTEGRATION = 'pending-integration:'
cases.SANDBOX_BLOCKED = 'sandbox-blocked:'
cases.bindings = lambda: json.loads((cases.ROOT / 'bindings.json').read_text())
cases.collection_bindings = cases.bindings
cases.installed_population = lambda: {({'TOOL-toy-new'} if added_population else set())!r}
cases.controller_installed = lambda: {installed!r}
sys.modules['nc_cases'] = cases
spec = importlib.util.spec_from_file_location('toy_enforcement_plugin', {str(PLUGIN)!r})
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
pytest_plugins = ['toy_enforcement_plugin']
''')
    sentinel = root / 'effects.txt'
    (cases / 'test_nc_toy.py').write_text(f'''
from pathlib import Path
import pytest

@pytest.mark.nc_case(rows=('Q01',), binding='installed')
{'@pytest.mark.nc_peer_case' if peer else ''}
def test_Q01():
    Path({str(sentinel)!r}).write_text('started')
    {body}
''')
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    env.pop('PYTEST_ADDOPTS', None)
    env.pop('PYTEST_PLUGINS', None)
    process = subprocess.run([sys.executable, '-B', '-m', 'pytest', '-q', '-c', str(root / 'pytest.ini'),
                              '--confcutdir', str(root), str(cases)], cwd=root, env=env,
                             capture_output=True, text=True, timeout=45)
    return process, sentinel


def test_compliant_case_completes_with_one_observed_effect(tmp_path):
    result, sentinel = _run(tmp_path, 'assert True')
    assert result.returncode == 0, result.stdout + result.stderr
    assert sentinel.read_text() == 'started'
    assert 'collected=1 completed=1 passed=1 failed=0 blocked=0 unfinished=0' in result.stdout


@pytest.mark.parametrize('attack', ['missing', 'added_population'])
def test_population_mutation_refuses_before_any_test_effect(tmp_path, attack):
    result, sentinel = _run(tmp_path, 'assert True', **{attack: True})
    assert result.returncode == 4, result.stdout + result.stderr
    assert 'non-compliance collection refused' in result.stderr
    assert not sentinel.exists()


def test_declared_integration_skip_is_blocked_not_completed(tmp_path):
    result, sentinel = _run(tmp_path, "pytest.skip('pending-integration: toy controller absent')")
    assert result.returncode == 0, result.stdout + result.stderr
    assert sentinel.exists()
    assert 'collected=1 completed=0 passed=0 failed=0 blocked=1 unfinished=0' in result.stdout


@pytest.mark.parametrize('body', ["pytest.skip('unexplained')", "pytest.xfail('known defect')"])
def test_unexpected_skip_and_xfail_are_failures(tmp_path, body):
    result, _ = _run(tmp_path, body)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'collected=1 completed=1 passed=0 failed=1 blocked=0 unfinished=0' in result.stdout


def test_integration_skip_after_installation_is_a_failure(tmp_path):
    result, _ = _run(tmp_path, "pytest.skip('pending-integration: toy')", installed=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'unexpected skip' in result.stdout


def test_unavailable_confinement_is_explicitly_blocked(tmp_path):
    result, _ = _run(tmp_path, "pytest.skip('sandbox-blocked: toy host')", installed=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'completed=0 passed=0 failed=0 blocked=1' in result.stdout


def test_explicit_peer_contract_cannot_skip_waiting_for_integration(tmp_path):
    result, _ = _run(tmp_path, "pytest.skip('pending-integration: toy')", peer=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'unexpected skip' in result.stdout
