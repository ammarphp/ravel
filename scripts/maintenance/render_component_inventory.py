#!/usr/bin/env python3
"""Render declared components using installed distribution metadata, without imports."""
from __future__ import annotations

import argparse
from importlib import metadata
import json
from pathlib import Path
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path('docs/reference/component-inventory.md')


def requirement_name(requirement):
    match = re.match(r'^([A-Za-z0-9][A-Za-z0-9._-]*)', requirement)
    if not match:
        raise ValueError('expected a named distribution: ' + requirement)
    return match.group(1)


def requirements(root):
    """Retain every declaration, including ranges and optional dependency groups."""
    project = tomllib.loads((root / 'pyproject.toml').read_text())['project']
    rows = {}
    def add(requirement, source):
        name = requirement_name(requirement)
        key = re.sub(r'[-_.]+', '-', name).lower(), requirement
        rows.setdefault(key, set()).add(source)
    for line in (root / 'requirements-full.txt').read_text().splitlines():
        line = line.split('#', 1)[0].strip()
        if line and line != '.':
            add(line, 'full host profile')
    for requirement in project.get('dependencies', []):
        add(requirement, 'base package')
    for group, declarations in sorted(project.get('optional-dependencies', {}).items()):
        for requirement in declarations:
            add(requirement, 'extra: ' + group)
    return [(requirement, ', '.join(sorted(sources)))
            for (_, requirement), sources in sorted(rows.items())]


def declared_license(record):
    """Use the distribution's fields in priority order; never infer missing terms."""
    for field in ('License-Expression', 'License'):
        value = record.get(field, '').strip()
        if value:
            return value.splitlines()[0].strip()
    classifiers = sorted(c for c in record.get_all('Classifier', [])
                         if c.startswith('License ::'))
    return '; '.join(classifiers) or 'unknown'


def distribution_record(requirement):
    try:
        distribution = metadata.distribution(requirement_name(requirement))
    except metadata.PackageNotFoundError:
        return 'metadata not installed', 'metadata not installed'
    return distribution.version, declared_license(distribution.metadata)


def installation_boundary(group):
    """Describe literal install steps, without treating declarations as executions."""
    boundaries = set()
    for step in group.get('steps', []):
        if step['kind'] == 'conda_env':
            boundaries.add('own environment: {ENVS}/' + step['name'])
        if step['kind'] in ('container_pull', 'container_build'):
            boundaries.add('separate container image')
        if step['kind'] == 'pip':
            boundaries.add('pip interpreter: ' + step['python'])
        # Destination tokens report the installer layout, not source URLs or prose.
        for field in ('dest', 'path', 'outputs'):
            values = step.get(field, [])
            for value in ([values] if isinstance(values, str) else values):
                environment = re.match(r'^(\{[A-Z_]+\}/.+)/bin/(?:python[0-9.]*|ravel)$', value)
                if environment:
                    boundaries.add('declared environment output: ' + environment.group(1))
                token = re.match(r'^(\{[A-Z_]+\})/', value)
                if token:
                    boundaries.add('prefix destination: ' + token.group(1))
    if not boundaries:
        return 'boundary not explicit; see manifest' if group.get('steps') else 'no install steps'
    return '; '.join(sorted(boundaries))


def cell(value):
    return str(value).replace('&', '&amp;').replace('|', '&#124;').replace('<', '&lt;').replace('>', '&gt;').replace('`', '&#96;').replace('\n', ' ')


def render(root=ROOT):
    lines = [
        '# Component inventory', '',
        'Rendered by `python scripts/maintenance/render_component_inventory.py`.',
        'Run it with `--check` in the same full-profile environment to detect drift.',
        'The Python rows record declared requirements and metadata visible to the generating',
        'interpreter. Version compatibility is established through the declared checks.',
        'Licence fields use License-Expression, then License (first line only), then licence',
        'classifiers. Missing fields are `unknown`; absent metadata is `metadata not installed`.',
        'Native rows report licence names and installation boundaries declared in the manifest,',
        'not an installed-tool census. These are packaging and installation facts.',
        'See [tool licences](tool-licences.md) for process boundaries and',
        '[copied material](../../THIRD-PARTY-NOTICES.md) for files retained in the source tree.', '',
        '| Python requirement | Declared in | Installed version | Metadata licence |',
        '|---|---|---|---|',
    ]
    for requirement, sources in requirements(root):
        version, license_name = distribution_record(requirement)
        lines.append('| ' + ' | '.join(map(cell, (requirement, sources, version, license_name))) + ' |')
    lines.extend(['', '| Native group | Manifest licences | Declared installation boundary |', '|---|---|---|'])
    sys.path.insert(0, str(root / 'src'))
    from ravel.setup import manifest as toolchain  # the merged view: the main manifest and its fragments
    merged = toolchain.view(root)
    held = toolchain.unreleased_groups(merged)  # groups the manifest withholds from a release have no row
    for group in sorted((g for g in merged['groups'] if g['id'] not in held), key=lambda g: g['id']):
        licenses = sorted({entry['spdx'] for entry in group.get('licenses', [])})
        lines.append('| ' + ' | '.join(map(cell, (group['id'], '; '.join(licenses) or 'none declared', installation_boundary(group)))) + ' |')
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='exit 1 if the output differs')
    parser.add_argument('--output', type=Path, help='write/check a different output path')
    args = parser.parse_args(argv)
    output = args.output or ROOT / OUTPUT
    expected = render()
    if args.check:
        if not output.is_file() or output.read_text() != expected:
            print('stale component inventory: ' + str(output), file=sys.stderr)
            return 1
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(expected)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
