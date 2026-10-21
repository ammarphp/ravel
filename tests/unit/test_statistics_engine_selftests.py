"""Execute the required statistics engine selftests through the test runner."""
import subprocess
import sys

import pytest


@pytest.mark.parametrize("module,argument", [
    ("ravel.physics.pyhf_exclude", "selftest"),
    ("ravel.physics.project_limits", "--selftest"),
])
def test_statistics_engine_selftest(module, argument):
    result = subprocess.run([sys.executable, "-m", module, argument],
                            text=True, capture_output=True, timeout=600)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout, result.stdout + result.stderr
