"""Export recorded analysis runtimes and a separate hash-locked WMS recipe.

No interpreter environment is captured here and no installation is executed.
Different versions across isolated environments are permitted. Conflicting
analysis stages, malformed locks and accidental WMS/analysis mixing are refused.
"""
import hashlib
from pathlib import Path
import re

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from . import env_snapshot

WMS_LOCK = Path(__file__).resolve().parents[3] / 'requirements-site-wms.lock'
RAVEL_DISTRIBUTIONS = {'ravel-hep', 'ravel'}
SETUP = '''#!/bin/sh
# Run explicitly from the relocated package; export never executes this script.
set -eu
cd "$(CDPATH= cd -P "$(dirname "$0")/.." && pwd)"
if [ ! -f environment/ravel-requirements.txt ]; then
    echo "Missing separate RAVEL distribution/source pin: environment/ravel-requirements.txt" >&2
    exit 1
fi
if [ -e .venv-analysis ] || [ -L .venv-analysis ] || [ -e .venv-wms ] || [ -L .venv-wms ] || [ -e .bin ] || [ -L .bin ]; then
    echo "Fresh .venv-analysis, .venv-wms and .bin paths required; existing environments are retained" >&2
    exit 1
fi
python3 -m venv .venv-analysis
.venv-analysis/bin/python -m pip install -r environment/analysis-requirements.txt
.venv-analysis/bin/python -m pip install --no-deps -r environment/ravel-requirements.txt
python3 -m venv .venv-wms
.venv-wms/bin/python -m pip install --require-hashes -r environment/wms-requirements.lock
test -f .venv-analysis/bin/ravel
test -f .venv-wms/bin/snakemake
mkdir .bin
ln -s ../.venv-analysis/bin/ravel .bin/ravel
ln -s ../.venv-wms/bin/snakemake .bin/snakemake
printf '%s\\n' 'From the package directory, use: export PATH="$PWD/.bin:$PATH"'
'''


def _lock(path):
    """Accept only exact named pins with SHA256 hashes, never pip directives."""
    raw = path.read_bytes()
    text = raw.decode('utf-8')
    lines = [line.split('#', 1)[0].strip() for line in text.splitlines()]
    joined = '\n'.join(lines).replace('\\\n', ' ')
    packages = {}
    for line in joined.splitlines():
        if not line.strip():
            continue
        hashes = re.findall(r'--hash=sha256:[0-9a-f]{64}(?=\s|$)', line)
        if not hashes:
            raise ValueError('WMS lock requires SHA256 hashes for every exact pin')
        requirement = re.sub(r'--hash=sha256:[0-9a-f]{64}(?=\s|$)', '', line).strip()
        try:
            parsed = Requirement(requirement)
        except ValueError as exc:
            raise ValueError('invalid hash-locked WMS requirement') from exc
        specs = list(parsed.specifier)
        if parsed.url or parsed.extras or len(specs) != 1 or specs[0].operator != '==' or '*' in specs[0].version:
            raise ValueError('WMS lock requires exact package versions and hashes')
        name = canonicalize_name(parsed.name)
        if name in packages:
            raise ValueError('duplicate WMS lock package: ' + name)
        packages[name] = specs[0].version
    if not {'snakemake', 'packaging'} <= packages.keys():
        raise ValueError('WMS lock must pin snakemake and packaging')
    if Version(packages['packaging']) >= Version('26'):
        raise ValueError('WMS snakemake lock requires packaging<26 in its separate environment')
    return raw, packages


def write(package_dir, runtime_snapshots, wms_lock=None, *, allow_fixture_lock=False):
    """Write package-relative files; return their byte pins.

    runtime_snapshots are verified source pins from env_snapshot.runtime_snapshots.
    The repository lock is mandatory in production. Tests may explicitly supply
    a synthetic lock with allow_fixture_lock=True; there is no unlocked fallback.
    A released tree carries environment/ravel-requirements.txt for the separate RAVEL pin.
    """
    root = env_snapshot._ordinary(package_dir)
    lock = env_snapshot._ordinary(wms_lock if wms_lock is not None else WMS_LOCK)
    if not lock.is_file():
        raise ValueError('hash-locked site WMS lock is absent: ' + str(lock))
    if lock != WMS_LOCK.absolute() and not allow_fixture_lock:
        raise ValueError('supplied fixture WMS lock requires allow_fixture_lock=True')
    lock_raw, wms = _lock(lock)
    packages, files = {}, {}
    for pin in runtime_snapshots:
        document = env_snapshot.read_runtime(pin)
        path = Path(pin['path'])
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != pin['sha256'] or len(raw) != pin['size']:
            raise ValueError('runtime snapshot changed during export')
        target = f"environment/runtime/{document['stage']}-{document['attempt']}.json"
        if target in files:
            raise ValueError('duplicate runtime stage/attempt: ' + target)
        files[target] = raw
        for row in env_snapshot._packages(document['packages']):
            name, version = row['name'], row['version']
            if name in RAVEL_DISTRIBUTIONS:
                continue
            # Prevent requirement-line injection or unresolved/local versions.
            parsed = Requirement(f'{name}=={version}')
            if parsed.url or parsed.marker or parsed.extras or len(list(parsed.specifier)) != 1:
                raise ValueError('runtime package requires one exact version: ' + name)
            Version(version)
            if name in packages and packages[name] != version:
                raise ValueError('conflicting runtime versions for package ' + name + ': ' + packages[name] + ' / ' + version)
            packages[name] = version
    if not files:
        raise ValueError('recorded runtime snapshots required; cannot capture the exporting interpreter')
    if 'snakemake' in packages:
        conflicts = sorted(name for name in packages.keys() & wms.keys() if packages[name] != wms[name])
        if conflicts:
            raise ValueError('snakemake mixed into analysis with conflicting WMS pins: ' + ', '.join(conflicts))
    files['environment/analysis-requirements.txt'] = ''.join(f'{name}=={packages[name]}\n' for name in sorted(packages)).encode()
    files['environment/wms-requirements.lock'] = lock_raw
    files['environment/setup.sh'] = SETUP.encode()
    for relative in files:
        target = env_snapshot._ordinary(root / relative)
        if target.exists():
            raise ValueError('environment export never overwrites package file: ' + relative)
    pins, created = [], []
    try:
        for relative, raw in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                created.append(path)
                stream.write(raw)
            if relative.endswith('/setup.sh'):
                path.chmod(0o755)
            pins.append({'path': relative, 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)})
    except BaseException:
        for path in created:
            path.unlink()
        raise
    return pins
