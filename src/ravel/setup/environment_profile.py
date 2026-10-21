"""Observe host capabilities and persist private, pinned site settings."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import stat
import subprocess
import tempfile
import threading
from urllib.parse import urlparse

SCHEMA = 'ravel-environment-profile.v1'
SITE_SCHEMA = 'ravel-site-profile.v1'
REASONS = ('not_installed', 'unlicensed', 'unconfigured', 'version_mismatch',
           'unsupported_platform', 'remote_only', 'excluded', 'unqualified_platform', 'unobserved')


def _error(exc):
    return f'{type(exc).__name__}: {exc}'[:300]


def _utc(now=None):
    value = datetime.now(timezone.utc) if now is None else now
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def probe_resources(roots: dict) -> dict:
    """Read host capacity and free space at each requested filesystem root."""
    try:
        usable = len(os.sched_getaffinity(0))
    except (AttributeError, OSError, ValueError):
        usable = None
    try:
        page_size, pages = os.sysconf('SC_PAGE_SIZE'), os.sysconf('SC_PHYS_PAGES')
        memory = page_size * pages if page_size > 0 and pages > 0 else None
    except (AttributeError, OSError, ValueError):
        memory = None
    disk = []
    for name, root in roots.items():
        if root is None:
            continue
        path = Path(root).absolute()
        try:
            while not path.exists() and path.parent != path:
                path = path.parent
            if path.exists():
                usage = shutil.disk_usage(path)
                disk.append({'root': name, 'path': str(path), 'free_bytes': usage.free,
                             'total_bytes': usage.total})
        except OSError:
            continue
    return {'cpus': os.cpu_count(), 'cpus_usable': usable, 'memory_bytes': memory, 'disk': disk}


def probe_gpus(*, which=shutil.which, run=None) -> dict:
    """Read device names without starting a workload."""
    executable = which('nvidia-smi')
    if not executable:
        return {'count': 0, 'source': 'none-detected', 'names': []}
    try:
        result = (run or subprocess.run)([executable, '-L'], capture_output=True, text=True,
                                         timeout=10, check=False)
        if result.returncode == 0:
            names = [line.partition(':')[2].split(' (', 1)[0].strip()
                     for line in result.stdout.splitlines() if line.startswith('GPU ')]
            return {'count': len(names), 'source': 'nvidia-smi', 'names': names}
    except Exception:
        pass
    return {'count': None, 'source': 'not-probed', 'names': []}


def probe_network(*, endpoints=None, timeout=3.0, connect=None) -> dict:
    """Bound TCP-only checks, including connectors blocked in name lookup."""
    if endpoints is None:
        from ravel.workflow import discovery_http
        endpoints = [(urlparse(url).hostname, 443)
                     for url in (discovery_http.HEPDATA, discovery_http.INSPIRE)]
    connector = socket.create_connection if connect is None else connect
    checks = []

    def check(address, result):
        try:
            connection = connector(address, timeout=timeout)
            connection.close()
            result.update(ok=True, error=None)
        except Exception as exc:
            result.update(ok=False, error=_error(exc))

    for host, port in endpoints:
        result = {}
        thread = threading.Thread(target=check, args=((host, port), result), daemon=True)
        thread.start()
        thread.join(timeout + 1)
        if thread.is_alive():
            row = {'ok': False, 'error': 'TimeoutError: network check timed out'}
        else:
            row = dict(result)
        checks.append({'host': host, 'port': port, **row})
    egress = 'available' if any(row['ok'] for row in checks) else 'none' if checks else 'unknown'
    return {'egress': egress, 'source': 'probe', 'checks': checks}


def probe_batch(*, environ=None, which=shutil.which, scheduler=None) -> dict:
    """Inspect scheduler clients and job markers without executing clients."""
    from ravel.workflow.backends.site_batch import COMMANDS
    environ = os.environ if environ is None else environ
    available = [name for name, commands in COMMANDS.items() if all(which(c) for c in commands)]
    inside = ('slurm' if 'SLURM_JOB_ID' in environ else
              'htcondor' if '_CONDOR_JOB_AD' in environ or '_CONDOR_SCRATCH_DIR' in environ else None)
    system = scheduler if scheduler is not None else (
        inside or (available[0] if len(available) == 1 else 'multiple' if available else 'none'))
    return {'system': system, 'available': available, 'inside_job': inside,
            'source': 'site-profile' if scheduler is not None else 'detected'}


def probe_sandbox() -> dict:
    from ravel.workflow import sandbox
    from ravel.controller.confine import launcher
    return {'backend': sandbox.available(), 'backends': launcher.backends()}


def probe_containers(*, which=shutil.which) -> dict:
    return {name: which(name) for name in ('podman', 'apptainer', 'singularity', 'docker')}


def probe_tools(*, prefix=None, repo=None, doctor=None, only=None) -> dict:
    """Project existing doctor observations; perform no independent tool probes.

    ``only`` (census ids) re-checks just those rows, as a step's preflight does for the tools its plan bound.
    """
    from ravel.setup import manifest
    repo = Path(repo) if repo is not None else manifest.repo_root()
    if not manifest.manifest_path(repo).is_file():
        return {'observed': False, 'source': 'doctor-census', 'prefix': None,
                'reason': 'toolchain manifest unavailable', 'rows': {}}
    if doctor is None:
        from ravel.setup.doctor import Doctor
        from ravel.setup.installer import resolve_prefix
        document, catalog = manifest.load(repo)
        resolved = resolve_prefix(repo, prefix, None)
        doctor = Doctor(repo, resolved, manifest.detect_platform(), document, catalog)
    groups = manifest.by_id(doctor.manifest)
    rows = {}
    if only is None:
        report = doctor.census_report()
    else:
        from ravel.workflow.tool_census import load_census
        census = load_census(catalog=None)
        wanted = set(only)
        report = doctor.census_report({**census, 'tools': [t for t in census['tools'] if t['id'] in wanted]})
    for row in report:
        checks = row.get('checks', [])
        versions = (check['found'] for check in checks if check.get('found'))
        licences, group_ids = [], []
        for observation in checks:
            binding = observation.get('binding', {})
            if binding.get('kind') != 'manifest':
                continue
            group_id = binding['group']
            if group_id not in group_ids:
                group_ids.append(group_id)
            check = next((item for item in groups[group_id]['checks']
                          if item['id'] == binding['check']), {})
            if check.get('kind') == 'wolfram':
                status = observation.get('status')
                licences.append('licensed' if status == 'ready' else
                                'unlicensed' if status == 'unconfigured' and
                                'not activated' in str(observation.get('detail', '')).lower() else 'unknown')
        licence = ('unlicensed' if 'unlicensed' in licences else 'unknown' if 'unknown' in licences
                   else 'licensed' if licences else 'not_applicable')
        reasons = [manifest.platform_qualification_reason(groups[gid], doctor.platform)
                   for gid in group_ids
                   if (groups[gid].get('qualification') or {}).get('required_per_platform')]
        rows[row['id']] = {'readiness': row.get('readiness'), 'status': row.get('status'),
                           'version': next(versions, None), 'licence': licence,
                           'platform_qualification': '; '.join(reason for reason in reasons if reason)}
    return {'observed': True, 'source': 'doctor-census', 'prefix': str(doctor.prefix),
            'reason': None, 'rows': rows}


def tool_status(profile: dict, census_id: str) -> dict:
    unknown = {'available': False, 'reason': 'unobserved', 'readiness': None, 'version': None}
    if not isinstance(profile, dict) or not isinstance(census_id, str):
        return unknown
    tools = profile.get('tools')
    if not isinstance(tools, dict) or tools.get('observed') is not True:
        return unknown
    rows = tools.get('rows')
    row = rows.get(census_id) if isinstance(rows, dict) else None
    if not isinstance(row, dict):
        return unknown
    readiness, version = row.get('readiness'), row.get('version')
    reasons = {'ready': None, 'remote_route': 'remote_only', 'missing': 'not_installed',
               'manual_required': 'not_installed', 'version_mismatch': 'version_mismatch',
               'unconfigured': 'unlicensed' if row.get('licence') == 'unlicensed' else 'unconfigured',
               'unsupported': 'unsupported_platform', 'excluded': 'excluded'}
    if (not isinstance(readiness, str) or readiness not in reasons
            or version is not None and not isinstance(version, str)
            or not isinstance(row.get('status', ''), str)
            or not isinstance(row.get('platform_qualification', ''), str)
            or row.get('licence', 'unknown') not in ('licensed', 'unlicensed', 'not_applicable', 'unknown')):
        return unknown
    reason = reasons[readiness]
    if readiness == 'ready' and row.get('platform_qualification'):
        reason = 'unqualified_platform'
    return {'available': reason is None, 'reason': reason, 'readiness': readiness, 'version': version}


def _probe_host():
    return {'system': platform.system(), 'release': platform.release(),
            'machine': platform.machine(), 'python': platform.python_version()}


def _probe_platform():
    from ravel.setup.manifest import detect_platform
    return detect_platform()


PROBES = {'host': _probe_host, 'platform': _probe_platform, 'resources': probe_resources,
          'gpus': probe_gpus, 'network': probe_network, 'batch': probe_batch,
          'sandbox': probe_sandbox, 'containers': probe_containers, 'tools': probe_tools}


def observe(*, run_dir=None, store_root=None, prefix=None, site=None, probes=None, tools=True) -> dict:
    """Observe each capability once, retaining independent probe failures."""
    from ravel import __version__
    table = {**PROBES, **(probes or {})}
    roots = {name: str(Path(path).expanduser().absolute()) for name, path in
             (('run_dir', run_dir), ('store_root', store_root), ('toolchain_prefix', prefix),
              ('tmp', tempfile.gettempdir())) if path is not None}
    document, pin = site if isinstance(site, tuple) else (site, None)
    document = document or {}
    errors = []

    def probe(name, fallback, *args, **kwargs):
        try:
            return table[name](*args, **kwargs)
        except Exception as exc:
            errors.append({'probe': name, 'error': _error(exc)})
            return fallback

    host = probe('host', dict.fromkeys(('system', 'release', 'machine', 'python'), 'unknown'))
    platform_key = probe('platform', 'unknown')
    resources = dict(probe('resources', {'cpus': None, 'cpus_usable': None,
                                       'memory_bytes': None, 'disk': []}, roots))
    resources['gpus'] = probe('gpus', {'count': None, 'source': 'not-probed', 'names': []})
    policy = document.get('network', {}).get('policy', 'auto')
    network = ({'egress': 'none' if policy == 'offline' else 'available',
                'source': 'site-profile', 'checks': []} if policy in ('offline', 'online') else
               probe('network', {'egress': 'unknown', 'source': 'not-probed', 'checks': []}))
    scheduler = document.get('settings', {}).get('scheduler')
    batch = probe('batch', {'system': scheduler or 'none', 'available': [], 'inside_job': None,
                            'source': 'site-profile' if scheduler else 'detected'}, scheduler=scheduler)
    if scheduler is not None:
        batch = {**batch, 'system': scheduler, 'source': 'site-profile'}
    return {'schema': SCHEMA, 'observed_utc': _utc(), 'ravel_version': __version__,
            'platform': platform_key, 'host': host, 'resources': resources,
            'filesystem': {'roots': roots}, 'network': network, 'batch': batch,
            'sandbox': probe('sandbox', {'backend': None, 'backends': {}}),
            'containers': probe('containers', dict.fromkeys(('podman', 'apptainer', 'singularity', 'docker'))),
            'tools': probe('tools', {'observed': False, 'source': 'doctor-census', 'prefix': None,
                                     'reason': 'probe failed', 'rows': {}}, prefix=prefix) if tools else
                     {'observed': False, 'reason': 'not requested'},
            'sources': {'mirror': (document.get('sources') or {}).get('mirror')},
            'site_profile': pin, 'probe_errors': errors}


def site_profile_path() -> Path:
    from ravel.controller.authority.operator import controller_home
    return controller_home() / 'site' / 'profile.json'


def validate_site_profile(document) -> list[str]:
    """Return all site-setting errors, including unknown and missing keys."""
    from ravel.workflow.site_doctor import PROFILES
    errors = []

    def keys(value, expected, label):
        if not isinstance(value, dict):
            errors.append(f'{label} must be an object.')
            return False
        for key in sorted(expected - value.keys()):
            errors.append(f'{label}.{key} is required.')
        for key in sorted(value.keys() - expected, key=str):
            errors.append(f'{label}.{key} is unknown.')
        return True

    def absolute(value):
        return isinstance(value, str) and '\x00' not in value and Path(value).is_absolute()

    if not keys(document, {'schema', 'name', 'created_utc', 'seed', 'settings', 'network', 'sources',
                           'observed'}, 'profile'):
        return errors
    if document.get('schema') != SITE_SCHEMA:
        errors.append('profile.schema must identify a site profile.')
    name = document.get('name')
    if not isinstance(name, str) or re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,63}', name) is None:
        errors.append('profile.name must be a lowercase identifier of at most 64 characters.')
    if document.get('seed') not in PROFILES:
        errors.append('profile.seed must be a supported seed.')
    created = document.get('created_utc')
    try:
        if not isinstance(created, str) or not created.endswith('Z'):
            raise ValueError
        if datetime.fromisoformat(created[:-1] + '+00:00').utcoffset() is None:
            raise ValueError
    except ValueError:
        errors.append('profile.created_utc must be a UTC ISO 8601 timestamp ending in Z.')
    settings = document.get('settings')
    if keys(settings, {'scheduler', 'requires_proxy', 'requires_kerberos', 'requires_afs', 'cvmfs'}, 'settings'):
        if settings.get('scheduler') not in ('htcondor', 'slurm', None):
            errors.append('settings.scheduler must be htcondor, slurm or null.')
        for key in ('requires_proxy', 'requires_kerberos', 'requires_afs'):
            if type(settings.get(key)) is not bool:
                errors.append(f'settings.{key} must be a boolean.')
        if settings.get('requires_afs') is True and settings.get('requires_kerberos') is not True:
            errors.append('settings.requires_afs requires settings.requires_kerberos.')
        paths = settings.get('cvmfs')
        if not isinstance(paths, list) or any(not absolute(path) for path in paths):
            errors.append('settings.cvmfs must be a list of absolute paths.')
    network = document.get('network')
    if keys(network, {'policy'}, 'network') and network.get('policy') not in ('auto', 'offline', 'online'):
        errors.append('network.policy must be auto, offline or online.')
    sources = document.get('sources')
    if keys(sources, {'mirror'}, 'sources'):
        mirror = sources.get('mirror')
        if mirror is not None and not absolute(mirror):
            errors.append('sources.mirror must be an absolute path or null.')
    observed = document.get('observed')
    if observed is not None and (not isinstance(observed, dict) or observed.get('schema') != SCHEMA):
        errors.append('profile.observed must be an environment profile or null.')
    return errors


def site_profile_document(*, name, seed, settings, network_policy='auto', mirror=None,
                          observed=None, now=None) -> dict:
    document = {'schema': SITE_SCHEMA, 'name': name, 'created_utc': _utc(now), 'seed': seed,
                'settings': deepcopy(settings), 'network': {'policy': network_policy},
                'sources': {'mirror': str(mirror) if isinstance(mirror, Path) else mirror},
                'observed': deepcopy(observed)}
    errors = validate_site_profile(document)
    if errors:
        raise ValueError('Invalid site profile: ' + ' '.join(errors))
    return document


def _ordinary_profile_path(path):
    path = Path(path if path is not None else site_profile_path()).absolute()
    for component in reversed((path, *path.parents)):
        if component.is_symlink():
            raise ValueError(f'Site profile path must not contain a symlink: {component}')
    return path


def _pin(path, raw, document):
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'name': document['name']}


def save_site_profile(document, path=None) -> dict:
    errors = validate_site_profile(document)
    if errors:
        raise ValueError('Invalid site profile: ' + ' '.join(errors))
    try:
        raw = (json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid site profile: document must be JSON serializable.') from exc
    path = _ordinary_profile_path(path)
    if path.exists() and not path.is_file():
        raise ValueError(f'Site profile must be a regular file: {path}')
    # Only directories this call creates are made private; an existing directory keeps its mode.
    for parent in reversed((path.parent, *path.parent.parents)):
        if not parent.exists():
            parent.mkdir(mode=0o700)
            parent.chmod(0o700)
    descriptor, temporary = tempfile.mkstemp(prefix='.profile-', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return _pin(path, raw, document)


def load_site_profile(path=None) -> tuple:
    path = _ordinary_profile_path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        raise ValueError(f'Invalid site profile path: {_error(exc)}') from exc
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f'Site profile must be a regular file: {path}')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f'Non-finite JSON value: {value}')

    try:
        raw = path.read_bytes()
        document = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f'Invalid site profile: {_error(exc)}') from exc
    errors = validate_site_profile(document)
    if errors:
        raise ValueError('Invalid site profile: ' + ' '.join(errors))
    return document, _pin(path, raw, document)
