#!/usr/bin/env python3
"""Move one inline group into its own fragment without changing the merged document."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import sys

# This maintenance helper works from a source checkout before package installation.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from ravel.setup import manifest as mf


def _group_bytes(raw, gid):
    """Preserve the exact JSON text of the inline group inside the new wrapper."""
    decoder = json.JSONDecoder()
    # Locate the top-level groups value, without matching keys inside group objects.
    cursor = raw.index('{') + 1
    while True:
        cursor = re.match(r'\s*', raw[cursor:]).end() + cursor
        key, end = decoder.raw_decode(raw, cursor)
        cursor = end + re.match(r'\s*:\s*', raw[end:]).end()
        if key == 'groups':
            cursor += 1
            while True:
                cursor += re.match(r'\s*', raw[cursor:]).end()
                if raw[cursor] == ']':
                    break
                value, end = decoder.raw_decode(raw, cursor)
                if value['id'] == gid:
                    return raw[cursor:end]
                cursor = end + re.match(r'\s*,?\s*', raw[end:]).end()
            break
        _, end = decoder.raw_decode(raw, cursor)
        cursor = end + re.match(r'\s*,?\s*', raw[end:]).end()
    raise mf.ManifestError('inline group not found: ' + gid)


def split_group(root, group_id, *, check=False):
    """Plan/perform an identity-preserving split, writing only under native/setup."""
    root = Path(root)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]*', group_id):
        raise mf.ManifestError('unsafe group id: ' + group_id)
    path = mf.manifest_path(root)
    before = mf.view(root)
    main = mf.read_json(path)
    fragment_path = root / 'native/setup/groups' / (group_id + '.json')
    group = next((g for g in main['groups'] if g['id'] == group_id), None)
    if group is None:
        if fragment_path.is_file() and group_id in mf.by_id(before):
            return 'unchanged: ' + group_id + ' already lives in ' + str(fragment_path)
        raise mf.ManifestError('inline group not found: ' + group_id)
    proposed = copy.deepcopy(main)
    proposed.setdefault('group_order', [g['id'] for g in before['groups']])
    proposed['groups'] = [g for g in proposed['groups'] if g['id'] != group_id]
    wrappers = [(p, mf._read_fragment(p)) for p in mf._fragment_files(root)]
    wrappers.append((fragment_path, {'group': group}))
    wrappers.sort(key=lambda row: row[0].name)
    after, _ = mf._assemble(proposed, path, wrappers)
    if mf.canonical_sha256(before) != mf.canonical_sha256(after):
        raise mf.ManifestError('split changes canonical digest for ' + group_id + '; no files written')
    if check:
        return 'would split: ' + group_id + '; canonical digest unchanged'
    raw_group = _group_bytes(path.read_text(), group_id)
    fragment_path.parent.mkdir(parents=True, exist_ok=True)
    # Both proposed documents have been parsed and compared before either write.
    fragment_path.write_text('{\n "group": ' + raw_group + '\n}\n')
    try:
        path.write_text(json.dumps(proposed, indent=1) + '\n')
    except OSError:
        fragment_path.unlink()
        raise
    return 'split: ' + group_id + '; canonical digest unchanged'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('group_id')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        print(split_group(args.root, args.group_id, check=args.check))
        return 0
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
