# SPDX-License-Identifier: Apache-2.0
"""Verify the separately licensed component package and export its patched upstream tree.

This recipe contains no upstream or overlay program code.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'src'))
from ravel import addons

MARKER = '.ravel-overlay.json'


def tree_identity(root):
    rows = {}
    for path in sorted(Path(root).rglob('*')):
        rel = path.relative_to(root)
        if '.git' in rel.parts or rel.as_posix() == MARKER:
            continue
        if path.is_symlink():
            raise ValueError(f'symlink refused in source or overlay: {path}')
        if path.is_file():
            rows[rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return rows


def verify_upstream_pins(source, component):
    """The overlay relies on these upstream files (their interfaces and common-block layouts)."""
    if 'upstream-api.json' not in component.manifest['files']:
        return
    pins = json.loads(component.path('upstream-api.json').read_text()).get('source_files', {})
    for rel, digest in sorted(pins.items()):
        path = Path(source) / rel
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f'upstream file {rel} differs from the add-on pin; the overlay was not exported')


def prepare(source, dest, addon, installed_addon=None):
    source, dest = Path(source).resolve(), Path(dest).absolute()
    component = addons.load(addon)  # Checks EVERY declared member before copying.
    if dest.is_symlink() or source == dest or source in dest.parents or dest in source.parents:
        raise ValueError('source and overlay must be disjoint real trees')
    verify_upstream_pins(source, component)
    expected = {'schema_version': 1, 'kind': 'ravel-overlay', 'source': str(source),
                'source_files': tree_identity(source), 'addon': component.identity()}
    if dest.exists() and any(dest.iterdir()):
        marker = dest / MARKER
        if not marker.is_file():
            raise ValueError(f'foreign non-empty destination refused: {dest}')
        record = json.loads(marker.read_text())
        if any(record.get(k) != v for k, v in expected.items()) or record.get('outputs') != tree_identity(dest):
            raise ValueError(f'owned overlay changed: {dest}; move it aside and rerun')
    else:
        partial = dest.with_name(dest.name + '.partial-' + uuid.uuid4().hex)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, partial, ignore=shutil.ignore_patterns('.git'), symlinks=False)
        result = subprocess.run(['patch', '--batch', '--forward', '-p1', '-i', str(component.path('lowint-capture.patch'))],
                                cwd=partial, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise ValueError(f'overlay patch failed; retained {partial}: {result.stdout} {result.stderr}')
        target = partial / 'ravel'
        target.mkdir(exist_ok=True)
        for member in component.manifest['overlay']:
            src = component.path(member)
            output = target / member
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, output)
        cmake = partial / 'CMakeLists.txt'
        include = 'include(ravel/CMakeLists-ravel.cmake)'
        with cmake.open('a') as handle:
            handle.write('\n' + include + '\n')
        record = {**expected, 'outputs': tree_identity(partial)}
        (partial / MARKER).write_text(json.dumps(record, indent=2) + '\n')
        if dest.exists():
            dest.rmdir()  # Empty directory only.
        os.replace(partial, dest)
    if installed_addon:
        installed = Path(installed_addon)
        if installed.exists():
            found = addons.load(installed)
            if found.manifest != component.manifest:
                raise ValueError(f'foreign or changed installed component package: {installed}')
        else:
            installed.parent.mkdir(parents=True, exist_ok=True)
            partial = installed.with_name(installed.name + '.partial-' + uuid.uuid4().hex)
            partial.mkdir()
            for member in [addons.MANIFEST, *component.members()]:
                output = partial / member
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(component.root / member, output)
            os.replace(partial, installed)
            addons.load(installed)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in ('source', 'dest', 'addon'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--installed-addon', type=Path)
    args = parser.parse_args()
    prepare(args.source, args.dest, args.addon, args.installed_addon)


if __name__ == '__main__':
    main()
