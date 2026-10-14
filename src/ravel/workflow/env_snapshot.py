"""Content-addressed Python environment capture and offline comparison.

Only package metadata, runtime versions and supplied records are read. Container
markers are allowlisted; credentials and native tools are never inspected or executed.
"""
import argparse
from datetime import datetime, timezone
from importlib import metadata
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
import uuid

CONTAINER_MARKERS = ('APPTAINER_CONTAINER', 'APPTAINER_NAME', 'SINGULARITY_CONTAINER',
                     'SINGULARITY_NAME', 'container', 'OCI_IMAGE_DIGEST')


def _packages(rows):
    packages = {}
    for row in rows:
        if type(row) is not dict or not all(type(row.get(k)) is str and row[k].strip() for k in ('name', 'version')):
            raise ValueError('package name and version required')
        name = re.sub(r'[-_.]+', '-', row['name']).lower()
        if name in packages:
            raise ValueError('duplicate normalized package name: ' + name)
        packages[name] = {'name': name, 'version': row['version']}
    return [packages[k] for k in sorted(packages)]


def snapshot_id(document):
    if document.get('schema_version') != 1 or document.get('kind') != 'ravel-environment-snapshot':
        raise ValueError('environment snapshot schema required')
    content = {k: v for k, v in document.items() if k not in ('snapshot_id', 'captured_utc')}
    content['packages'] = _packages(document['packages'])
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def capture(*, packages=None):
    from ravel import __version__
    if packages is None:
        packages = [{'name': d.metadata['Name'], 'version': d.version} for d in metadata.distributions() if d.metadata['Name']]
    document = {'schema_version': 1, 'kind': 'ravel-environment-snapshot',
                'captured_utc': datetime.now(timezone.utc).isoformat(), 'ravel_version': __version__,
                'python': {'version': platform.python_version(), 'implementation': platform.python_implementation()},
                'platform': {'system': platform.system(), 'release': platform.release(), 'machine': platform.machine()},
                'packages': _packages(packages)}
    document['snapshot_id'] = snapshot_id(document)
    return document


def _ordinary(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('ordinary environment record path required: ' + str(path))
    return path


def _pin(path, document):
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw),
            'snapshot_id': document['snapshot_id']}


def _record(record):
    """Read a supplied JSON record or a pinned record, never a shell helper."""
    if isinstance(record, dict) and not {'path', 'sha256', 'size'} <= record.keys():
        return record
    path = _ordinary(record['path'] if isinstance(record, dict) else record)
    raw = path.read_bytes()
    if isinstance(record, dict) and (hashlib.sha256(raw).hexdigest() != record['sha256'] or len(raw) != record['size']):
        raise ValueError('environment source record changed')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('environment source record must be an object')
    return value


def read_runtime(pin):
    """Revalidate both source bytes and snapshot identity at every consumption."""
    value = _record(pin)
    if value.get('snapshot_id') != snapshot_id(value) or pin.get('snapshot_id') != value['snapshot_id']:
        raise ValueError('runtime environment snapshot content changed')
    for key in ('stage', 'attempt'):
        if not isinstance(value.get(key), str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', value[key]):
            raise ValueError('runtime snapshot requires safe stage and attempt')
    return value


def capture_runtime(rundir, stage, *, doctor_record=None, image_record=None):
    """Capture inside the executing stage process, not its exporting caller.

    Each call owns a fresh attempt identity. The step runner invokes this.
    Doctor JSON can be supplied explicitly or retained as logs/site-doctor.json
    or logs/site-doctor/*.json; the most recently modified retained record wins.
    Missing doctor/image records stay explicit unknowns, without tool probes.
    """
    root = _ordinary(rundir)
    if not isinstance(stage, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', stage):
        raise ValueError('safe stage name required')
    value = capture()
    value['python']['executable'] = str(Path(sys.executable).resolve())
    value['platform']['libc'] = list(platform.libc_ver())
    value.update(stage=stage, attempt=uuid.uuid4().hex)
    # Prefer the executing interpreter's installation, then the run/check-out.
    roots = dict.fromkeys((Path(sys.prefix), *Path(sys.prefix).parents, root, *root.parents,
                          Path(__file__).resolve().parents[3]))
    binding = next((p / '.ravel-site/lcg-view.json' for p in roots
                    if (p / '.ravel-site/lcg-view.json').is_file()), None)
    value['facility_view'] = _record(binding) if binding else None
    if doctor_record is None:
        candidates = [p for p in (root / 'logs/site-doctor.json', *(root / 'logs/site-doctor').glob('*.json'))
                      if p.is_file()]
        doctor_record = max(candidates, key=lambda p: (p.stat().st_mtime_ns, p.name)) if candidates else None
    doctor = _record(doctor_record) if doctor_record is not None else None
    versions = doctor.get('versions', doctor.get('native_tools', {})) if doctor is not None else {}
    if doctor is not None and not versions:
        versions = {row['name']: row['detail'] for row in doctor.get('checks', [])
                    if row.get('status') == 'ok' and row.get('name') in
                    ('python 3.12', 'TeX', 'node', 'rucio', 'apptainer', 'xrootd', 'ROOT', 'root-config')}
    if not isinstance(versions, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in versions.items()):
        raise ValueError('doctor tool versions must be strings')
    value['native_tools'] = versions
    value['doctor_record_available'] = doctor is not None
    markers = {key: os.environ[key] for key in CONTAINER_MARKERS if key in os.environ}
    value['container'] = {'image': _record(image_record) if image_record is not None else None,
                          'markers': markers} if markers or image_record is not None else None
    value['snapshot_id'] = snapshot_id(value)
    directory = _ordinary(root / 'logs/environment'); directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stage}-{value['attempt']}.json"
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')
    return _pin(path, value)


def runtime_snapshots(rundir):
    """Return verified pins for all retained runtime attempts, in path order."""
    directory = _ordinary(Path(rundir) / 'logs/environment')
    pins = []
    for path in sorted(directory.glob('*.json')):
        value = _record(path)
        pin = _pin(path, value)
        read_runtime(pin)
        if path.name != f"{value['stage']}-{value['attempt']}.json":
            raise ValueError('runtime snapshot filename differs from stage/attempt')
        pins.append(pin)
    return pins


def diff(before, after):
    for document in (before, after):
        if document.get('snapshot_id') != snapshot_id(document):
            raise ValueError('environment snapshot content changed')
    a, b = ({p['name']: p['version'] for p in _packages(d['packages'])} for d in (before, after))
    changed = [{'name': k, 'before': a[k], 'after': b[k]} for k in sorted(a.keys() & b.keys()) if a[k] != b[k]]
    keys = ('python', 'platform', 'ravel_version', 'facility_view', 'container', 'native_tools')
    runtime = {k: {'before': before.get(k), 'after': after.get(k)} for k in keys if before.get(k) != after.get(k)}
    return {'schema_version': 1, 'kind': 'environment-diff', 'before': before['snapshot_id'], 'after': after['snapshot_id'],
            'identical': before['snapshot_id'] == after['snapshot_id'], 'changed': changed,
            'added': [{'name': k, 'version': b[k]} for k in sorted(b.keys() - a.keys())],
            'removed': [{'name': k, 'version': a[k]} for k in sorted(a.keys() - b.keys())], 'runtime': runtime}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel env', description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    snap = commands.add_parser('snapshot'); snap.add_argument('--out', type=Path, required=True)
    compare = commands.add_parser('diff')
    compare.add_argument('--before', type=Path, required=True); compare.add_argument('--after', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'snapshot':
            result = capture()
            with args.out.open('x') as stream: stream.write(json.dumps(result, indent=2, sort_keys=True) + '\n')
        else:
            result = diff(json.loads(args.before.read_text()), json.loads(args.after.read_text()))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f'environment snapshot: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
