"""Resolve the Snakemake executable used to parse or run exported workflows.

Resolution order: explicit argument, RAVEL_SNAKEMAKE, RAVEL_TEST_SNAKEMAKE (under
pytest only), the site-wms record (seam), then PATH. Nothing is looked up next to
sys.executable. An empty list means no Snakemake was found.

``declared_entry`` is separate: the console entry of the workflow manager this
installation declares as a runtime dependency. A controller that prepares a
governed launch names that entry explicitly; the resolution above never uses it.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def _site_wms_record():
    """Resolve the installed prefix's validated record to its isolated shim."""
    from .site_contract import read_wms_record
    prefix = os.environ.get('RAVEL_SITE_PREFIX') or os.environ.get('RAVEL_NATIVE_BUILD')
    if not prefix and Path(sys.prefix).parent.name == '.ravel-site':
        prefix = str(Path(sys.prefix).parent.parent)
    if not prefix:
        from ravel.paths import native_build_root
        prefix = native_build_root()
    try:
        record = read_wms_record(prefix)
    except ValueError:
        return None
    return _usable(record['shim'])


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


def declared_entry():
    """The console entry of the installation's declared workflow manager, or an empty list.

    The entry lies in the prefix that holds the installed package (an environment whose
    site-packages this interpreter inherits counts), else in this interpreter's prefixes.
    Only a controller preparing a governed launch uses it, and it passes the entry explicitly.
    """
    import importlib.util
    prefixes = []
    try:
        spec = importlib.util.find_spec('snakemake')
    except (ImportError, ValueError):
        spec = None
    origin = Path(spec.origin) if spec is not None and spec.origin else None
    if origin is not None:
        parents = origin.resolve().parents
        for index, parent in enumerate(parents):
            if parent.name in ('site-packages', 'dist-packages') and index + 3 < len(parents):
                prefixes.append(parents[index + 3])  # <prefix>/lib/pythonX.Y/site-packages
                break
    prefixes += [Path(sys.prefix), Path(sys.base_prefix)]
    for prefix in dict.fromkeys(prefixes):
        argv = _usable(str(prefix / 'bin' / 'snakemake'))
        if argv:
            return argv
    return []


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
