#!/usr/bin/env python3
"""Refresh an already-applied guard fragment against unrelated current-source edits.

Every hunk's complete postimage must occur exactly once. The tool reverses only
those exact bytes, regenerates the diff and pins both images; it never edits the
product source or changes the guard. Run its proving controls after generation.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
HUNK = re.compile(r'^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def reverse_exact(installed, fragment):
    lines = fragment.splitlines(keepends=True)
    if len(lines) < 3 or not lines[0].startswith('--- a/') or not lines[1].startswith('+++ b/'):
        raise ValueError('one ordinary unified fragment required')
    before, after, hunks = [], [], []
    for line in lines[2:]:
        if HUNK.match(line):
            if before or after:
                hunks.append((''.join(before), ''.join(after)))
            before, after = [], []
        elif line.startswith((' ', '+', '-')):
            if line[0] in ' -':
                before.append(line[1:])
            if line[0] in ' +':
                after.append(line[1:])
        else:
            raise ValueError('unsupported fragment line')
    if before or after:
        hunks.append((''.join(before), ''.join(after)))
    if not hunks:
        raise ValueError('fragment has no hunks')
    preimage = installed
    for old, new in reversed(hunks):
        if not new or preimage.count(new) != 1:
            raise ValueError('guard postimage is absent or ambiguous; review source changes')
        preimage = preimage.replace(new, old, 1)
    return preimage


def refreshed(root, patch_name):
    if Path(patch_name).name != patch_name or not patch_name.endswith('.patch'):
        raise ValueError('patch must be a local fragment filename')
    folder = root / 'tests/fixtures/enforcement/patches'
    manifest_path = folder / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    rows = [row for row in manifest['patches'] if row['patch'] == patch_name]
    if len(rows) != 1:
        raise ValueError('fragment must have exactly one manifest row')
    row = rows[0]
    target = Path(row['target'])
    if target.is_absolute() or '..' in target.parts or target.parts[0] != 'src':
        raise ValueError('fragment target must be a relative product source')
    path = folder / patch_name
    fragment = path.read_text()
    headers = fragment.splitlines()[:2]
    if headers != ['--- a/' + row['target'], '+++ b/' + row['target']]:
        raise ValueError('fragment target differs from its manifest')
    installed = (root / target).read_text()
    preimage = reverse_exact(installed, fragment)
    updated = ''.join(difflib.unified_diff(preimage.splitlines(keepends=True), installed.splitlines(keepends=True),
                                         fromfile='a/' + row['target'], tofile='b/' + row['target']))
    row.update(source_sha256=digest(preimage.encode()), result_sha256=digest(installed.encode()),
               patch_sha256=digest(updated.encode()))
    return {path: updated, manifest_path: json.dumps(manifest, indent=1) + '\n'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--patch', required=True)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    changes = refreshed(args.root, args.patch)
    stale = [path for path, content in changes.items() if path.read_text() != content]
    if args.write:
        for path in stale:
            path.write_text(changes[path])
    print(('refreshed' if args.write else 'stale') + ': ' + ', '.join(str(path) for path in stale))
    return 0 if args.write or not stale else 1


if __name__ == '__main__':
    raise SystemExit(main())
