"""Package initializer registration in complete trees and in closed staged copies.

Synthetic package trees around a byte copy of the real initializer; each case
imports in its own interpreter. No scientific module is loaded.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
import ravel

INITIALIZER = Path(ravel.__file__)
REGISTRY = "def register_surface_extension():\n    print('registered')\n    return True\n"
GOVERNANCE = 'SURFACE_EXTENSIONS = ()\n'


def imported(tmp_path, members, code='import ravel'):
    package = tmp_path / 'tree/ravel'
    (package / 'workflow').mkdir(parents=True)
    shutil.copyfile(INITIALIZER, package / '__init__.py')
    (package / 'workflow/__init__.py').write_text('')
    for name, text in members.items():
        (package / 'workflow' / name).write_text(text)
    env = {k: v for k, v in os.environ.items() if not k.startswith('PYTHON')}
    env.update(PYTHONPATH=str(tmp_path / 'tree'), PYTHONDONTWRITEBYTECODE='1')
    return subprocess.run([sys.executable, '-B', '-c', code], cwd=tmp_path, env=env, capture_output=True, text=True)


def test_complete_tree_registers_exactly_once(tmp_path):
    done = imported(tmp_path, {'role_registry.py': REGISTRY, 'host_governance.py': GOVERNANCE},
                    "import ravel\nassert not hasattr(ravel, '_role_registry') and not hasattr(ravel, '_importlib')")
    assert done.returncode == 0 and done.stdout == 'registered\n', done.stderr


def test_closed_copy_without_registry_and_governance_imports_without_registration(tmp_path):
    done = imported(tmp_path, {}, "import ravel, sys\nassert callable(ravel.validate_task_contract)\n"
                    "assert sorted(n for n in sys.modules if n.startswith('ravel')) == ['ravel', 'ravel.workflow']")
    assert done.returncode == 0 and done.stdout == '', done.stderr


def test_tree_with_governance_cannot_lose_its_registry(tmp_path):
    done = imported(tmp_path, {'host_governance.py': GOVERNANCE})
    assert done.returncode != 0 and "No module named 'ravel.workflow.role_registry'" in done.stderr


@pytest.mark.parametrize('governed', [False, True])
def test_registry_with_a_missing_dependency_is_not_an_absent_registry(tmp_path, governed):
    members = {'role_registry.py': 'import ravel_dependency_that_does_not_exist\n' + REGISTRY}
    if governed: members['host_governance.py'] = GOVERNANCE
    done = imported(tmp_path, members)
    assert done.returncode != 0 and "No module named 'ravel_dependency_that_does_not_exist'" in done.stderr
    assert 'registered' not in done.stdout


def test_real_package_import_alone_registers_the_role_surface(tmp_path):
    env = {**os.environ, 'PYTHONPATH': str(INITIALIZER.parents[1]), 'PYTHONDONTWRITEBYTECODE': '1'}
    code = ("import ravel, sys\ngovernance = sys.modules['ravel.workflow.host_governance']\n"
            "registry = sys.modules['ravel.workflow.role_registry']\n"
            "assert registry.owned_paths in governance.SURFACE_EXTENSIONS\n")
    done = subprocess.run([sys.executable, '-B', '-c', code], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
