#!/usr/bin/env python3
"""Refuse restricted source material in a tree before it ships.

The owner keeps a deny list outside every repository and passes it with --deny-list or the
RAVEL_RESTRICTED_SOURCES environment variable. It is JSON:

    {"schema_version": 1, "kind": "restricted-sources",
     "documents": [{"label": "...", "sha256": "<64 hex>"}],
     "fingerprints": ["short text the owner chooses"]}

A finding is any scanned file that cites a listed document hash or contains a listed fingerprint
(both case-insensitive), and any Python file under src/ that cites a document by sha256 in a comment
or string constant with no public URL within three lines. The scanner never prints a fingerprint or
a full hash, so its output can go into a public log.

Usage: restricted_source_scan.py [--deny-list PATH] [--root DIR] [--hash-citations-only] [PATH ...]
Exit 0 when clean, 1 on any finding, 2 when the deny list is missing, invalid or inside a scanned path.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

# Support direct invocation from an uninstalled source checkout.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from ravel.validation.check_generality import archive_contents

ENV = 'RAVEL_RESTRICTED_SOURCES'
HEX64 = re.compile(r'(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])')
URL = re.compile(r'https?://')
# Words that make a hash a document citation rather than a software or data pin. Underscores count
# as separators so INPUTS_PDF_SHA and doc_sha256 match.
DOCUMENT_CUE = re.compile(r'(?i)(?<![a-z])(pdf|docx?|document|slides?|paper|note|manual|specification|'
                          r'spec|tarball|brief|handout|plenary|deliverables?)(?![a-z])')
PATHLIKE = re.compile(r'\S*/\S*')
SKIP_DIRS = {'.git', '__pycache__', '.mypy_cache', '.pytest_cache', 'node_modules', '.venv'}
MAX_BYTES = 64 * 1024 * 1024
WINDOW = 3


def load_deny_list(path):
    path = Path(path)
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ValueError(f'cannot read the deny list: {error}') from None
    if not isinstance(doc, dict) or doc.get('schema_version') != 1 or doc.get('kind') != 'restricted-sources':
        raise ValueError('the deny list needs schema_version 1 and kind restricted-sources')
    if set(doc) - {'schema_version', 'kind', 'documents', 'fingerprints', 'note'}:
        raise ValueError('the deny list accepts only documents, fingerprints and note')
    documents = doc.get('documents', [])
    fingerprints = doc.get('fingerprints', [])
    if not isinstance(documents, list) or not isinstance(fingerprints, list):
        raise ValueError('documents and fingerprints must be lists')
    for row in documents:
        if not (isinstance(row, dict) and set(row) == {'label', 'sha256'} and isinstance(row['label'], str)
                and row['label'].strip() and isinstance(row['sha256'], str)
                and re.fullmatch(r'[0-9a-f]{64}', row['sha256'])):
            raise ValueError('each document needs a label and a lower-case sha256')
    for value in fingerprints:
        if not isinstance(value, str) or len(value.strip()) < 6:
            raise ValueError('each fingerprint must be text of at least six characters')
    return {'documents': [dict(r) for r in documents], 'fingerprints': [v.strip() for v in fingerprints]}


def _files(paths):
    for path in paths:
        path = Path(path)
        if path.is_symlink():
            continue
        if path.is_file():
            yield path
        elif path.is_dir():
            for parent, dirs, names in os.walk(path):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not Path(parent, d).is_symlink())
                for name in sorted(names):
                    child = Path(parent, name)
                    if not child.is_symlink() and child.is_file():
                        yield child


def _relative(path, root):
    if root is None:
        return Path(path)
    try:
        return Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return Path(path)


def _cue(line):
    """A document cue outside path-like tokens (a file inside a pinned source tree is not a document)."""
    return DOCUMENT_CUE.search(PATHLIKE.sub(' ', line)) is not None


def _uncited_document_hashes(lines):
    """Line numbers where a comment or string constant cites a document hash with no public URL nearby."""
    found = []
    for index, line in enumerate(lines):
        match = HEX64.search(line)
        if match is None:
            continue
        comment = line.find('#')
        in_comment = 0 <= comment < match.start()
        in_string = any(q in line[:match.start()] for q in ('"', "'"))
        if not (in_comment or in_string):
            continue
        above = []
        for previous in reversed(lines[max(0, index - WINDOW):index]):
            if not previous.lstrip().startswith('#'):
                break
            above.append(previous)
        if _cue(line) or any(_cue(c) for c in above):
            if not any(URL.search(w) for w in lines[max(0, index - WINDOW):index + WINDOW + 1]):
                found.append(index + 1)
    return found


def scan(paths, deny_list, *, root=None):
    """Findings for every file under ``paths``: listed hashes, fingerprints and uncited src/ document hashes.

    ``deny_list`` is the loaded owner list, or None for the src/ citation rule alone.
    """
    hashes = {} if deny_list is None else {r['sha256']: r['label'] for r in deny_list['documents']}
    fingerprints = [] if deny_list is None else [f.lower() for f in deny_list['fingerprints']]
    findings = []
    for path in _files(paths):
        rel = _relative(path, root)
        try:
            if path.stat().st_size > MAX_BYTES:
                findings.append({'path': str(rel), 'line': None, 'kind': 'unscanned-large-file',
                                 'detail': 'larger than the scan limit; review it by hand'})
                continue
            data = path.read_bytes()
        except OSError as error:
            findings.append({'path': str(rel), 'line': None, 'kind': 'unreadable', 'detail': str(error)})
            continue
        for member, payload, rule in archive_contents(str(rel), data):
            if rule:
                findings.append({'path': member, 'line': None, 'kind': rule,
                                 'detail': 'archive content could not be completely scanned'})
            # Scan member names as well as their content, without exposing fingerprints.
            if member == str(rel) and payload is None and rule is None:
                # Retain the original raw-byte scan (including container comments).
                text = data.decode('latin-1')
            else:
                text = member if payload is None else payload.decode('latin-1')
            lower = text.lower()
            for digest, label in hashes.items():
                at = lower.find(digest)
                if at >= 0:
                    findings.append({'path': member, 'line': lower.count('\n', 0, at) + 1, 'kind': 'listed-hash',
                                     'detail': f'cites the restricted document labelled {label!r}'})
            for number, fingerprint in enumerate(fingerprints, 1):
                at = lower.find(fingerprint)
                if at >= 0:
                    findings.append({'path': member, 'line': lower.count('\n', 0, at) + 1, 'kind': 'fingerprint',
                                     'detail': f'contains deny-list fingerprint #{number}'})
            if Path(member.split('!', 1)[0]).parts[:1] == ('src',) and member.endswith('.py'):
                lines = text.splitlines()
                for number in _uncited_document_hashes(lines):
                    findings.append({'path': member, 'line': number, 'kind': 'uncited-document-hash',
                                     'detail': 'a document is cited by sha256 without a public URL'})
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('paths', nargs='*', help='files or directories to scan (default: the root)')
    parser.add_argument('--deny-list', help=f'owner deny list (default: ${ENV})')
    parser.add_argument('--root', default='.', help='tree root; src/ is resolved against it')
    parser.add_argument('--hash-citations-only', action='store_true',
                        help='run only the src/ document-hash citation rule, without a deny list')
    args = parser.parse_args(argv)
    paths = args.paths or [args.root]
    deny_path = args.deny_list or os.environ.get(ENV)
    deny_list = None
    if not args.hash_citations_only:
        if not deny_path:
            print(f'restricted_source_scan: no deny list; pass --deny-list or set {ENV}', file=sys.stderr)
            return 2
        resolved = Path(deny_path).resolve()
        for scanned in paths:
            base = Path(scanned).resolve()
            if resolved == base or base in resolved.parents:
                print('restricted_source_scan: the deny list must live outside every scanned tree', file=sys.stderr)
                return 2
        try:
            deny_list = load_deny_list(resolved)
        except ValueError as error:
            print(f'restricted_source_scan: {error}', file=sys.stderr)
            return 2
    findings = scan(paths, deny_list, root=args.root)
    for f in findings:
        where = f['path'] if f['line'] is None else f"{f['path']}:{f['line']}"
        print(f"{where}: {f['kind']}: {f['detail']}")
    print(f'restricted_source_scan: {len(findings)} finding(s)', file=sys.stderr)
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main())
