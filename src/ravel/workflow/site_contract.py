"""Portable install-record contracts shared by site installation and readiness."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

PLUGIN = 'snakemake-executor-plugin-cluster-generic'
INTERFACE = 'snakemake-interface-executor-plugins'


def lock_packages(path):
    """Read exact, hashed package entries; pip verifies distribution bytes at install."""
    try:
        raw = Path(path).read_text()
    except OSError as error:
        raise ValueError('WMS hash lock missing; run bash scripts/setup/lock_site_wms.sh before installation') from error
    packages = {}
    entries = raw.replace('\\\n', ' ').splitlines()
    for entry in entries:
        entry = entry.strip()
        if not entry or entry.startswith('#'):
            continue
        match = re.match(r'^([A-Za-z0-9_.-]+)==([^\s;]+)', entry)
        if not match or not re.search(r'--hash=sha256:[0-9a-f]{64}(?:\s|$)', entry):
            raise ValueError('WMS lock requires exact versions and sha256 hashes for every package')
        spec = entry.split('--hash=',1)[0].strip()
        if ';' in spec:
            try:
                from packaging.markers import Marker, default_environment
            except ImportError:
                try:
                    from pip._vendor.packaging.markers import Marker, default_environment
                except ImportError as error:
                    raise ValueError('Install pip in the Linux Python 3.12 bootstrap environment to read lock markers') from error
            environment=default_environment()
            environment.update(python_version='3.12',python_full_version='3.12.0',
                               platform_system='Linux',sys_platform='linux',os_name='posix')
            if not Marker(spec.split(';',1)[1].strip()).evaluate(environment):continue
        name = re.sub(r'[-_.]+', '-', match[1]).lower()
        if name in packages and packages[name] != match[2]:
            raise ValueError('WMS lock has ambiguous platform versions: ' + name)
        packages[name] = match[2]
    if packages.get('snakemake') != '9.27.0' or packages.get('packaging') != '25.0' or PLUGIN not in packages:
        raise ValueError('WMS hash lock must include Snakemake 9.27.0, packaging 25.0 and the cluster-generic plugin')
    if not interface_supported(packages.get(INTERFACE)):
        raise ValueError('WMS executor interface must satisfy >=9.3.2,<10')
    return packages


def interface_supported(version):
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', version):
        return False
    parts = tuple(int(x) for x in version.split('.'))
    parts = (*parts, *(0 for _ in range(3 - len(parts))))
    return (9, 3, 2) <= parts < (10, 0, 0)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_wms_record(prefix):
    """A record is accepted only with its unchanged lock and prefix-local paths."""
    prefix = Path(prefix).absolute()
    owned = prefix / '.ravel-site'
    try:
        if any(part.is_symlink() for part in (owned/'wms.json',*(owned/'wms.json').parents)):
            raise ValueError('Ordinary prefix-owned WMS record required')
        value = json.loads((owned / 'wms.json').read_text())
        if value.get('schema_version') != 1 or not value.get('release'):
            raise ValueError('WMS record schema or release is missing')
        expected = {'shim': prefix / 'bin/ravel-snakemake',
                    'snakemake': owned / 'site-wms/bin/snakemake',
                    'analysis_python': owned / 'site-analysis/bin/python',
                    'lock': owned / 'requirements-site-wms.lock'}
        for key, path in expected.items():
            if value.get(key) != str(path):
                raise ValueError('WMS record path differs from installed prefix: ' + key)
            if any(part.is_symlink() for part in (path,*path.parents)):
                raise ValueError('Ordinary prefix-owned WMS record paths required: ' + key)
        if sha256(expected['lock']) != value.get('lock_sha256'):
            raise ValueError('WMS record lock sha256 differs')
        packages = lock_packages(expected['lock'])
        plugins = {k: v for k, v in packages.items() if k.startswith('snakemake-executor-plugin-')}
        if (value.get('version') != packages['snakemake'] or value.get('plugins') != plugins
                or value.get('packages') != packages):
            raise ValueError('WMS record versions differ from hash lock')
        return value
    except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as error:
        raise ValueError('WMS installation record missing or invalid: ' + str(error)) from error


def versions_script(names):
    """Query distribution metadata using only the WMS interpreter's stdlib."""
    return ('import importlib.metadata as m,json,re; '\
            'installed={re.sub("[-_.]+","-",d.metadata["Name"]).lower():d.version for d in m.distributions()}; '\
            'print(json.dumps({n:installed.get(n) for n in ' + repr(list(names)) + '}))')
