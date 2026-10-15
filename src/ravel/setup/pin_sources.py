"""Bind group source templates to verified local pin ledgers, without acquisition."""
from __future__ import annotations

from pathlib import Path

from ravel.setup.manifest import ManifestError, read_json
from ravel.setup.licence_policy import load_pin


def resolve(document, root):
    from ravel.setup.gpl_isolation import validate
    root = Path(root).resolve()
    for group in document.get('groups', []):
        if 'pin_file' not in group:
            continue
        validate({'groups': [group]})
        path = Path(group['pin_file'])
        if path.is_absolute() or '..' in path.parts or not str(path).startswith('native/setup/'):
            raise ManifestError(group['id'] + ': pin_file must be inside native/setup')
        target = root / path
        if not target.resolve().is_relative_to(root) or target.is_symlink():
            raise ManifestError(group['id'] + ': pin_file symlink refused')
        ledger = read_json(target) if target.exists() else {'schema_version': 1, 'tools': {}}
        if ledger.get('schema_version') != 1 or not isinstance(ledger.get('tools'), dict):
            raise ManifestError(group['id'] + ': source ledger schema 1 required')
        pending = []
        for check in group.get('checks', []):
            version_key = check.get('version_pin')
            version_row = ledger['tools'].get(version_key)
            if version_row is not None and version_row.get('status') == 'filled':
                version_row = load_pin(version_key, document=ledger)
                if not check.get('probe', {}).get('regex'):
                    raise ManifestError(group['id'] + ': version pin requires a probe regex')
                check['probe']['expect'] = version_row['version']
            key = check.get('image_pin')
            if key is None:
                continue
            row = ledger['tools'].get(key)
            if row is None or row.get('status') == 'pending':
                pending.append(key)
                # Never infer image readiness from an unqualified local receipt file.
                check['probe'] = {'argv': ['{INSTALLER_PYTHON}', '-c', 'raise SystemExit(1)']}
                continue
            row = load_pin(key, document=ledger)
            if row['kind'] != 'image' or '@' in row['url'] or ':' in row['url'].split('/')[-1]:
                raise ManifestError(group['id'] + ': image pin needs an untagged image and digest')
            check.update(kind='container_image', image=row['url'], digest=row['digest'])
            check.pop('path', None)
            check.pop('probe', None)
        bound = []
        licenses = {l.get('tool_key'): l for l in group.get('licenses', [])}
        for step in group['steps']:
            key = step.get('pin')
            if key is None:
                bound.append(step)
                continue
            if key not in licenses:
                raise ManifestError(group['id'] + ': licence entry required for source ' + key)
            row = ledger['tools'].get(key)
            if row is None or row.get('status') == 'pending':
                pending.append(key)
                continue
            row = load_pin(key, document=ledger)
            if not isinstance(row.get('licence'), dict) or not row['licence'].get('spdx'):
                raise ManifestError(group['id'] + ': licence entry required for source ' + key)
            if row['licence']['spdx'] != licenses[key]['spdx']:
                raise ManifestError(group['id'] + ': source licence differs from declared licence: ' + key)
            if row['kind'] != step['kind']:
                raise ManifestError(group['id'] + ': source kind differs: ' + key)
            resolved = {k: v for k, v in step.items() if k != 'pin'}
            resolved.update({k: row[k] for k in ('url', 'sha256', 'size', 'commit', 'digest') if row.get(k)})
            bound.append(resolved)
            licenses[key].update(row['licence'], source=row['url'], licence_file=row['licence_file'],
                                 licence_text_sha256=row['licence_text_sha256'])
        if pending:
            # An always-failing inert probe prevents a stale directory satisfying the hold.
            group['steps'] = [{'id': 'source-pins-pending', 'kind': 'manual',
                               'probe': {'argv': ['{INSTALLER_PYTHON}', '-c', 'raise SystemExit(1)']},
                               'instruction': 'Supply verified source and licence pins in ' + str(path)
                               + ': ' + ', '.join(pending)}]
        else:
            group['steps'] = bound
    return document
