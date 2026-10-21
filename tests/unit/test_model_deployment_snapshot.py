"""Deployment changes must retain the real generality gate and engagement source pins."""
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_deployment_runtime_passes_the_generality_gate():
    # The raw source checkout also contains private release inventories and upstream citation
    # records, which the release exporter handles under its own provenance contract. This
    # check covers the runtime, its tests and its documentation, including new untracked files.
    targets = ['src/ravel/controller', 'src/ravel/workflow', 'src/ravel/transports', 'src/ravel/setup',
               'src/ravel/data/agents', 'src/ravel/data/models', 'tests', 'docs']
    targets = [p for p in targets if (ROOT / p).exists()]
    result = subprocess.run([sys.executable, 'src/ravel/validation/check_generality.py', '--summary', *targets],
                            cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr


def test_deployment_keeps_engagement_projection_source_pins_current():
    result = subprocess.run([sys.executable, 'scripts/maintenance/build_engagement_envelopes.py', '--check'],
                            cwd=ROOT, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
