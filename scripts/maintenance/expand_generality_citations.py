#!/usr/bin/env python3
"""Expand retained citation prefixes to complete identifiers from their cited source bytes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from ravel.validation import check_generality as cg


def expand(root, document):
    from functools import lru_cache
    valid = lru_cache(maxsize=32768)(cg.citable_identifier)
    result = json.loads(json.dumps(document))
    token = re.compile(r'[A-Za-z0-9_./()-]')
    for field in ('files', 'withheld_files'):
        for name, strings in result.get(field, {}).items():
            texts = []
            for path, data, gap in cg.archive_contents(name, (Path(root) / name).read_bytes()):
                if gap:
                    raise ValueError(f'{name}: complete citation expansion requires complete source inspection')
                texts.extend([path, cg._decode(data) if data is not None else ''])
            expanded = set()
            for identifier in strings:
                found = set()
                for text in texts:
                    cursor = 0
                    while (start := text.find(identifier, cursor)) >= 0:
                        cursor = end = start + len(identifier)
                        left = start
                        while left and token.fullmatch(text[left - 1]):
                            if left >= 2 and text[left - 2] == '\\' and text[left - 1] in 'nrt':
                                break
                            left -= 1
                        while end < len(text) and token.fullmatch(text[end]):
                            end += 1
                        starts = [left, start] + [i + 1 for i in range(left, start) if text[i] in '/(']
                        accepted = []
                        for begin in sorted(set(starts)):
                            candidate = text[begin:end].rstrip('./-')
                            while candidate.endswith(')') and candidate.count(')') > candidate.count('('):
                                candidate = candidate[:-1]
                            for stop in range(len(candidate), start + len(identifier) - begin - 1, -1):
                                value = candidate[:stop]
                                boundary = begin + len(value)
                                if boundary < len(text) and re.fullmatch(r'[A-Za-z0-9_-]', text[boundary]):
                                    continue
                                if valid(value) and cg._citation_pattern(value).match(text, begin):
                                    accepted.append(value)
                                    break
                        if accepted:
                            found.add(max(accepted, key=len))
                if not found:
                    raise ValueError(f'{name}: {identifier!r} requires a complete source identifier')
                expanded.update(found)
            result[field][name] = sorted(expanded)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--citations', type=Path, default=cg.CITATIONS)
    parser.add_argument('--source-citations', type=Path, help='retained citation policy to migrate')
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    original = args.citations.read_text()
    source = args.source_citations.read_text() if args.source_citations else original
    rendered = json.dumps(expand(args.root, json.loads(source)), indent=1) + '\n'
    if args.write:
        args.citations.write_text(rendered)
    return 0 if args.write or original == rendered else 1


if __name__ == '__main__':
    raise SystemExit(main())
