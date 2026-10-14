"""Resolve the Snakemake executable used to parse or run exported workflows.

Resolution order: explicit argument, RAVEL_SNAKEMAKE, RAVEL_TEST_SNAKEMAKE (under
pytest only), the site-wms record (seam), then PATH. Nothing is looked up next to
sys.executable. An empty list means no Snakemake was found.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def _site_wms_record():
    """Seam for the site-wms record that a later package adds; returns an argv or None."""
    return None


def _usable(value):
    if not value:
        return None
    path = Path(value)
    if path.is_absolute() or os.sep in value:
        return [str(path)] if path.is_file() and os.access(path, os.X_OK) else None
    found = shutil.which(value)
    return [found] if found else None


def snakemake_argv(explicit=None):
    candidates = [explicit, os.environ.get('RAVEL_SNAKEMAKE')]
    if 'pytest' in sys.modules:
        candidates.append(os.environ.get('RAVEL_TEST_SNAKEMAKE'))
    for value in candidates:
        argv = _usable(value)
        if argv:
            return argv
    argv = _site_wms_record()
    if argv:
        return list(argv)
    found = shutil.which('snakemake')
    return [found] if found else []


def snakemake_version(argv):
    """Version string from `--version`, or None when it cannot be read."""
    if not argv:
        return None
    try:
        done = subprocess.run([*argv, '--version'], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'\d+(?:\.\d+)+\S*', done.stdout) if done.returncode == 0 else None
    return match.group(0) if match else None
