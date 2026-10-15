"""Refuse restricted tool installation or imports in the RAVEL interpreter."""
from __future__ import annotations

import argparse
import json
import re

from ravel.setup.manifest import ManifestError


def check(document):
    errors = []
    for group in document.get('groups', []):
        restricted = [l for l in group.get('licenses', [])
                      if str(l.get('spdx', '')).startswith(('GPL', 'AGPL', 'LicenseRef'))
                      or l.get('import_into_ravel') == 'never']
        if not restricted:
            continue
        modules = {re.sub(r'[^a-z0-9_]', '', l['component'].lower().replace('-', sep))
                   for l in restricted for sep in ('', '_')}
        modules.update(str(m).lower() for m in group.get('restricted_modules', []))
        for step in group.get('steps', []):
            text = json.dumps(step)
            host_path = re.search(r'(?:^|[/"\s])\.venv(?:[/"\s]|$)|\{HOST_PYTHON\}', text)
            if not host_path:
                continue
            argv = step.get('argv', [])
            if (step.get('kind') == 'command' and argv[1:3] == ['-m', 'venv']
                    and not re.search(r'(?:^|[/"\s])\.venv(?:[/"\s]|$)', json.dumps(argv[3:]))):
                continue
            importing = any(re.search(r'\b(?:import|from)\s+' + re.escape(m) + r'\b', text, re.I)
                            for m in modules)
            # A host interpreter handed to a recipe as an argument can install into it.
            handed = any(re.search(r'(?:^|/)\.venv(?:/|$)|\{HOST_PYTHON\}', str(a)) for a in argv[1:])
            installing = (step.get('kind') == 'pip' or 'pip' in argv or 'venv' in argv or handed
                          or any(k in step for k in ('dest', 'python', 'target')))
            if importing or installing:
                errors.append(group['id'] + '/' + step.get('id', '?')
                              + ': gpl_isolation forbids restricted tools in the RAVEL environment')
    return errors


def validate(document):
    errors = check(document)
    if errors:
        raise ManifestError('; '.join(errors))


def main(argv=None):
    from ravel.setup import manifest
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root')
    args = parser.parse_args(argv)
    errors = check(manifest.view(args.root))
    print('\n'.join(errors) if errors else 'gpl_isolation: OK')
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
