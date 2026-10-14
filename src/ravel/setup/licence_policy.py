"""Offline licence lint and side-file pin resolution; never executes upstream code."""
from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path
import re
import shlex

from ravel.setup.manifest import ManifestError, read_json, repo_root

_ACQUISITIONS = {'git', 'archive', 'download', 'svn', 'pip', 'conda_env', 'container_pull', 'miniforge', 'pdf_sets'}
_RESTRICTIVE = ('GPL', 'LGPL', 'AGPL', 'MPL', 'LicenseRef')


def load_pin(key, *, document=None, repo=None):
    """Resolve only a complete, evidence-bearing source. Pending rows are holds."""
    doc = document if document is not None else read_json(Path(repo or repo_root()) / 'native/setup/tools-pins.json')
    try:
        row = doc['tools'][key]
    except KeyError as exc:
        raise ManifestError('unknown source pin: ' + key) from exc
    if row.get('status') != 'filled':
        raise ManifestError('source pin pending: ' + key)
    required = {'git': ['commit'], 'archive': ['sha256', 'size'], 'conda': ['sha256', 'size'],
                'svn': ['revision'], 'image': ['digest']}
    if row.get('kind') not in required:
        raise ManifestError('unknown pin kind: ' + key)
    for field in ['licence_file', 'licence_text_sha256', 'fetched_utc'] + required[row['kind']]:
        if not row.get(field):
            raise ManifestError('source pin missing ' + field + ': ' + key)
    patterns = {'commit': r'[0-9a-f]{40}', 'sha256': r'[0-9a-f]{64}',
                'digest': r'sha256:[0-9a-f]{64}', 'licence_text_sha256': r'[0-9a-f]{64}',
                'fetched_utc': r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z'}
    for field in ['licence_text_sha256', 'fetched_utc'] + required[row['kind']]:
        value = row[field]
        if field in patterns and not re.fullmatch(patterns[field], str(value)):
            raise ManifestError('malformed source pin ' + field + ': ' + key)
        if field in ('size', 'revision') and (type(value) is not int or value <= 0):
            raise ManifestError('positive integer source pin ' + field + ' required: ' + key)
    if re.search(r'\*|pending|matched|select|latest|\{|[0-9]\.?[xX]|or-newest', row.get('version', '')):
        raise ManifestError('source pin version is unresolved: ' + key)
    licence_path = Path(row['licence_file'])
    if licence_path.is_absolute() or '..' in licence_path.parts:
        raise ManifestError('licence file must be inside upstream tree: ' + key)
    # Schema validation stays optional for the stdlib-only installer; check it at lint time.
    if row.get('licence', {}).get('evidence_status') != 'verified':
        raise ManifestError('source pin has unverified licence: ' + key)
    return dict(row)


def licence_entries(keys, *, document=None, repo=None, require_verified=False):
    """Return manifest licence entries for component keys, including byte evidence."""
    doc = document if document is not None else read_json(Path(repo or repo_root()) / 'native/setup/tools-pins.json')
    entries = []
    for key in keys:
        if key not in doc['tools']:
            raise ManifestError('unknown licence key: ' + key)
        row = load_pin(key, document=doc) if require_verified else doc['tools'][key]
        entries.append(dict(row['licence'], component=row['tool'], source=row['url'],
                            tool_key=key, licence_file=row['licence_file'],
                            licence_text_sha256=row['licence_text_sha256']))
    return entries


def _name(value):
    return re.sub(r'[^a-z0-9]', '', str(value).lower())


def _host_python(value):
    return '.venv' in str(value).replace('\\', '/').split('/') or str(value) == '{HOST_PYTHON}'


def _copy_sources(text):
    """Parse COPY (shell/JSON form, flags, continuations); malformed COPY fails closed."""
    text = re.sub(r'\\\s*\n\s*', '', text)
    for line in text.splitlines():
        match = re.match(r'^\s*COPY\s+(.+)', line, re.I)
        if not match:
            continue
        rest = match[1].strip()
        while rest.startswith('--'):
            parts = rest.split(None, 1)
            if len(parts) != 2:
                raise ValueError('COPY has no source')
            rest = parts[1]
        fields = json.loads(rest) if rest.startswith('[') else shlex.split(rest)
        if not isinstance(fields, list) or len(fields) < 2 or not all(isinstance(v, str) for v in fields):
            raise ValueError('COPY requires sources and destination')
        yield from fields[:-1]


def _overlaps(source, candidate):
    src = source.replace('\\', '/').rstrip('/').removeprefix('./')
    cand = candidate.replace('\\', '/').rstrip('/').removeprefix('./')
    if src in ('.', '', '*', '**'):
        return True
    # A source directory may contain a restricted tool; globs can select its files.
    return (cand == src or cand.startswith(src + '/') or src.startswith(cand + '/')
            or fnmatch.fnmatch(cand, src) or fnmatch.fnmatch(Path(cand).name, src)
            or any(_name(part) == _name(cand) for part in src.split('/')))


def check(document, *, ledger=None, containerfiles=None):
    """Return findings for a manifest/fragment and optional Containerfile text mapping.

    The fragment assembler passes groups via ``document`` and recipe bytes via
    ``containerfiles``. ``ledger`` is tools-pins' tools mapping. Infrastructure
    groups with no acquisition steps need no third-party licence declaration.
    """
    errors = []
    groups = document.get('groups', [document] if 'id' in document else [])
    if not isinstance(groups, list):
        return ['licence policy: groups must be a list']
    restricted_paths = set()
    for key, row in (ledger or {}).items():
        licence = row.get('licence', {})
        if not licence.get('redistribute', True):
            restricted_paths.update((key, row.get('tool', key)))
    for group in groups:
        gid = group.get('id', '?')
        licences = group.get('licenses', [])
        steps = group.get('steps', [])
        if not licences and any(s.get('kind') in _ACQUISITIONS or s.get('kind') == 'container_build' for s in steps):
            errors.append(gid + ': licence entry required for acquired tools')
        for licence in licences:
            if not licence.get('component') or not licence.get('spdx'):
                errors.append(gid + ': licence component and SPDX required')
                continue
            component = licence['component']
            overlay = next((r.get('licence', {}) for k, r in (ledger or {}).items()
                            if _name(component) in (_name(k), _name(r.get('tool', '')))), {})
            policy = dict(licence, **overlay)
            if policy.get('redistribute') is False:
                restricted_paths.add(component)
                for step in steps:
                    if step.get('dest'):
                        restricted_paths.add(step['dest'])
                if policy.get('container_publish', 'never') != 'never':
                    errors.append(gid + ': non-redistributable tool cannot be published')
            if str(policy['spdx']).startswith(_RESTRICTIVE) or policy.get('import_into_ravel') == 'never':
                # Fail closed at group granularity: GPL groups may not install through host Python.
                for step in steps:
                    if step.get('kind') == 'pip' and _host_python(step.get('python', '')):
                        errors.append(gid + ': licence forbids restricted Python module in .venv')
                    argv = step.get('argv', [])
                    if step.get('kind') == 'command' and argv and _host_python(argv[0]) and 'pip' in argv:
                        errors.append(gid + ': licence forbids host Python pip command')
    for name, text in (containerfiles or {}).items():
        try:
            for source in _copy_sources(text):
                if any(_overlaps(source, p) for p in restricted_paths):
                    errors.append(str(name) + ': COPY selects a non-redistributable tool: ' + source)
        except (ValueError, TypeError) as exc:
            errors.append(str(name) + ': cannot lint COPY: ' + str(exc))
    return sorted(set(errors))


def validate(document, **kwargs):
    errors = check(document, **kwargs)
    if errors:
        raise ManifestError('; '.join(errors))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--pins', type=Path)
    parser.add_argument('--containerfile', type=Path, action='append', default=[])
    args = parser.parse_args(argv)
    root = repo_root()
    manifest = read_json(args.manifest or root / 'native/setup/toolchain-manifest.json')
    pins = read_json(args.pins or root / 'native/setup/tools-pins.json')
    from jsonschema import Draft202012Validator
    schema = read_json(root / 'native/setup/tools-pins.schema.json')
    errors = [e.message for e in Draft202012Validator(schema).iter_errors(pins)]
    errors += check(manifest, ledger=pins['tools'],
                    containerfiles={str(p): p.read_text() for p in args.containerfile})
    print('\n'.join(errors) if errors else 'Licence policy OK; pending pins remain acquisition holds')
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
