"""Protected paths: a learning loop cannot weaken the checks it is judged by.

``src/ravel/data/governance/protected_paths.json`` names the sources and record fields that
judge a run. This module supplies the predicates other packages call:

- ``is_protected(path)``: the path is a protected source (also when it names an installed
  copy under ``.../ravel/...``). The broker is to refuse a write to it.
- ``suppression_rule(text, known_ids=...)``: the do-not-learn rule. It returns the sentences
  that name a target (a check, trap, gate, premise or review-point id, a known bare id, a
  protected file or field, or a weakening flag) and weaken it: remove, skip, stub, patch,
  rewrite, set a threshold, mark as not applicable, call it optional or too strict. A nonempty
  result means the lesson or fix is refused (root-cause analysis and ``knowledge_lessons``).
- ``fix_errors(fix)``: an RCA fix that edits a protected path or field, or suppresses a check.
- ``evaluator_snapshot()`` / ``seal_worker_receipt(receipt, before, after)``: hashes of every
  protected file before and after a worker; a change voids that worker's receipt.
- ``investigator_bundle(results)``: what an RCA investigator sees of a check, its id and
  verdict, never its source.
- ``scan(roots)``: run-time artefacts that write a protected path, carry a suppression lesson
  or leak check source into an investigator bundle. The CLI exits 1 on any finding.

"Never skip check:x" strengthens a check and passes. A sentence that describes when a check
fails passes; one that edits, removes or weakens it is refused. Prose matching screens lessons;
the structural protection is the manifest: ``fix_errors`` refuses an edit to a protected path,
to a protected field, to an ancestor of one, or a new value that carries one. Standard library
only, so CI can run it without the scientific stack.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1]
# A source checkout keeps the package at <root>/src/ravel; an installed copy at <site-packages>/ravel.
INSTALLED = PACKAGE_DIR.parent.name != 'src'
SOURCE_ROOT = PACKAGE_DIR.parent if INSTALLED else PACKAGE_DIR.parents[1]
MANIFEST = PACKAGE_DIR / 'data' / 'governance' / 'protected_paths.json'
INVESTIGATOR_KEYS = ('check_id', 'verdict', 'finding_id', 'receipt_id')
MAX_SCAN_BYTES = 5_000_000
_HEX64 = re.compile(r'[0-9a-f]{64}')

_ID = re.compile(r'(?<![\w:])(?:(?:check|trap|gate|premise|invariant|review[-_ ]?point|rp)\s*[:/]\s*'
                 r'[A-Za-z0-9][\w.-]*|RP\d+(?::[\w.-]+)?)', re.IGNORECASE)
# A weakening flag is its own target: "use --no-lint" needs no check id.
_FLAG = re.compile(r'(?<![\w-])--(?:no|skip|disable|ignore|allow)-[\w-]+|(?<![\w-])--force\b', re.IGNORECASE)
# Actions that weaken a target; "never <action>" or "do not <action>" strengthens instead.
_ACTION = re.compile(
    r"\b(?:skip(?:s|ped|ping)?|bypass(?:es|ed|ing)?|ignor(?:e|es|ed|ing)|disabl(?:e|es|ed|ing)|"
    r"suppress(?:es|ed|ing)?|silenc(?:e|es|ed|ing)|waiv(?:e|es|ed|ing)|exempt(?:s|ed|ing)?|"
    r"relax(?:es|ed|ing)?|loosen(?:s|ed|ing)?|weaken(?:s|ed|ing)?|"
    r"overrid(?:e|es|ing)|overridden|mut(?:e|es|ed|ing)|deactivat(?:e|es|ed|ing)|downgrad(?:e|es|ed|ing)|"
    # Third-person forms of these verbs describe a check ("fails when the filter drops events"); omitted.
    r"remov(?:e|ed|ing)|delet(?:e|ed|ing)|drop(?:ped|ping)?|omit(?:ted|ting)?|exclud(?:e|ed|ing)|"
    r"stub(?:bed|bing)?|mock(?:ed|ing)?|patch(?:ed|ing)?|rewrit(?:e|ing)|rewritten|"
    r"hard-?cod(?:e|ed|ing)|forc(?:e|ed|ing)|edit|modify|replace|"
    r"(?<!is )(?<!are )(?<!was )set(?:ting)? (?:\S+ ){0,6}to|"
    r"comment(?:s|ed|ing)? out|turn(?:s|ed|ing)? off|switch(?:es|ed|ing)? off|leave (?:\S+ ){0,3}out|"
    r"(?:raise|lower|widen|increase|decrease)[sd]? (?:the |its )?(?:threshold|tolerance|bound|limit)|"
    r"(?:treat|mark|count)(?:s|ed|ing)? (?:\S+ ){0,3}as (?:pass(?:ed|ing)?|green|ok|satisfied)|"
    r"pass(?:es)? (?:it|them|this)|let (?:it|them|this) pass|auto-?pass(?:es|ed)?)\b"
    r"|(?<![\w-])--(?:no|skip|disable|ignore|allow)-[\w-]+|(?<![\w-])--force\b",
    re.IGNORECASE)
# Phrases that weaken a target whatever precedes them.
_ALWAYS = re.compile(
    r"\b(?:(?:do not|don't|never|no need to|need not|needn't) (?:run|check|apply|enforce|require)|"
    r"not applicable|n/a|left out|no longer|(?:is|be|are|as|made?) optional|unnecessary|not (?:be )?(?:required|needed|necessary)|"
    r"too (?:strict|tight|conservative|sensitive|aggressive)|returns? (?:no findings|pass|true|ok)|"
    r"only fires? (?:above|below|over|beyond))\b",
    re.IGNORECASE)
_NEGATED = re.compile(r"(?:\bnever|\bnot|n't|\bno)\s+(?:\w+\s+)?$", re.IGNORECASE)
_PRONOUN = re.compile(r'\b(?:it|this|that|them|these|those)\b', re.IGNORECASE)
_SENTENCE = re.compile(r'(?<=[.;!?])\s+|\n+')


# ----------------------------------------------------------------------------- manifest

def load_manifest(path=None) -> dict:
    """The manifest after a structural check; raises ValueError on a malformed file."""
    manifest = json.loads(Path(path or MANIFEST).read_text())
    if manifest.get('schema_version') != 1 or manifest.get('kind') != 'protected-path-manifest':
        raise ValueError('protected-path manifest needs schema_version 1 and its kind')
    seen = set()
    for entry in manifest.get('entries') or []:
        if not isinstance(entry, dict) or not entry.get('id') or entry['id'] in seen:
            raise ValueError('every manifest entry needs a unique id')
        seen.add(entry['id'])
        if not entry.get('paths') or not all(isinstance(p, str) and p and not p.startswith('/') and '..' not in p
                                             for p in entry['paths']):
            raise ValueError(f'{entry["id"]}: paths must be nonempty repository-relative globs')
        if not isinstance(entry.get('fields', []), list):
            raise ValueError(f'{entry["id"]}: fields must be a list')
        if entry.get('required') and entry.get('pending'):
            raise ValueError(f'{entry["id"]}: an entry is either required or pending')
    if not seen:
        raise ValueError('protected-path manifest has no entries')
    return manifest


def _match(pattern, path):
    def walk(ps, xs):
        if not ps:
            return not xs
        if ps[0] == '**':
            return any(walk(ps[1:], xs[i:]) for i in range(len(xs) + 1))
        return bool(xs) and fnmatch.fnmatchcase(xs[0], ps[0]) and walk(ps[1:], xs[1:])
    return walk(pattern.split('/'), path.split('/'))


def _spellings(text):
    parts = [p for p in os.path.normpath(text).replace('\\', '/').split('/') if p not in ('', '.')]
    if '..' in parts:
        return None
    out = ['/'.join(parts)]
    out += ['src/' + '/'.join(parts[i:]) for i, p in enumerate(parts) if p == 'ravel']
    return out


def _candidates(path, root):
    """Repository-relative spellings of a path, its resolved target and an installed ``ravel`` package copy.

    A relative path is also resolved against ``root`` (a run or the repository), so a symlink in
    either place is matched by the file it reaches. An empty list means an unresolvable ``..``.
    """
    text = os.fspath(path).replace('\\', '/')
    base = os.path.realpath(root)
    absolute = text if os.path.isabs(text) else os.path.join(base, text)
    real = os.path.realpath(absolute)
    spelled = []
    for i, form in enumerate((text, real)):
        if os.path.isabs(form):
            rel = os.path.relpath(form, base).replace('\\', '/')
            form = rel if not rel.startswith('../') and rel != '..' else form
        found = _spellings(form)
        if found is None and i == 0:
            return []
        spelled += found or []
    if real != os.path.normpath(absolute):
        # A link that leaves the root: match the target against the evaluator's own source tree.
        rel = os.path.relpath(real, SOURCE_ROOT).replace('\\', '/')
        if not rel.startswith('../') and rel != '..':
            spelled += _spellings(rel) or []
    return list(dict.fromkeys(spelled))


def protecting_entries(path, *, manifest=None, root=None) -> list[str]:
    """Ids of the manifest entries that protect ``path``."""
    manifest = manifest or load_manifest()
    candidates = _candidates(path, root or SOURCE_ROOT)
    return [e['id'] for e in manifest['entries']
            if any(_match(p, c) for p in e['paths'] for c in candidates)]


def is_protected(path, *, manifest=None, root=None) -> bool:
    """True when a run-time artefact may not write ``path``; an unresolvable ``..`` path counts as protected."""
    if not _candidates(path, root or SOURCE_ROOT):
        return True
    return bool(protecting_entries(path, manifest=manifest, root=root))


def protected_fields(manifest=None) -> set[str]:
    """Dotted record keys that no lesson or fix may edit."""
    return {f for e in (manifest or load_manifest())['entries'] for f in e.get('fields', [])}


def _segments(pointer):
    """Key segments of a JSON pointer or dotted key; array indices are dropped."""
    return [x for x in re.split(r'[/.]', str(pointer)) if x and not x.isdigit()]


def field_is_protected(pointer, *, manifest=None) -> str | None:
    """The protected field a JSON pointer or dotted key reaches, else None."""
    segments = _segments(pointer)
    for field in sorted(protected_fields(manifest)):
        want = field.split('.')
        if any(segments[i:i + len(want)] == want for i in range(len(segments))):
            return field
    return None


def _keys(value, prefix=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield prefix + (str(key),)
            yield from _keys(item, prefix + (str(key),))
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item, prefix)


def edit_field(pointer, value=None, *, manifest=None) -> str | None:
    """The protected field an edit reaches: at or below ``pointer``, inside its new value, or below it."""
    segments = _segments(pointer or '')
    fields = sorted(protected_fields(manifest))
    for field in fields:
        want = field.split('.')
        # Replacing or deleting an ancestor (``/review`` or the whole record) replaces the field too.
        if not segments or any(len(segments) - i < len(want) and want[:len(segments) - i] == segments[i:]
                               for i in range(len(segments))):
            return field
    for keys in _keys(value):
        hit = field_is_protected('/'.join(segments + list(keys)), manifest=manifest)
        if hit:
            return hit
    return field_is_protected('/'.join(segments), manifest=manifest)


def manifest_errors(manifest=None, root=None) -> list[str]:
    """Required entries must match at least one tracked file; pending entries are reported only."""
    manifest, root = manifest or load_manifest(), Path(root or SOURCE_ROOT)
    files = [p.relative_to(root).as_posix() for p in root.rglob('*')
             if p.is_file() and not any(part in ('.git', '.venv', 'local-runs', 'node_modules', '__pycache__')
                                        for part in p.relative_to(root).parts)]
    return [f'{e["id"]}: no file matches {e["paths"]}' for e in manifest['entries']
            if e.get('required') and not any(_match(p, f) for p in e['paths'] for f in files)]


# ----------------------------------------------------------------------------- do-not-learn

def _targets(manifest, known_ids):
    """Patterns for what a lesson may not weaken: ids, protected file names and protected fields."""
    names = set()
    for entry in manifest['entries']:
        for pattern in entry['paths']:
            last = pattern.rsplit('/', 1)[-1]
            if last != '**' and '.' in last:
                names.add(re.escape(last).replace(r'\*', r'[\w.-]*'))
        names.update(re.escape(f) for f in entry.get('fields', []) if '.' in f or '_' in f)
    names.update(re.escape(k) for k in known_ids)
    bare = re.compile(r'(?<![\w:-])(?:' + '|'.join(sorted(names)) + r')(?![\w-])', re.IGNORECASE) if names else None
    return [p for p in (_ID, _FLAG, bare) if p]


def _weakens(sentence):
    if _ALWAYS.search(sentence):
        return True
    return any(not _NEGATED.search(sentence[:m.start()]) for m in _ACTION.finditer(sentence))


def suppression_rule(text, *, known_ids=(), manifest=None) -> list[str]:
    """Sentences that would weaken a check, trap, gate, threshold or protected file; nonempty means refuse.

    A sentence is refused when it names a target (an id such as ``check:x``, a known bare id, a
    protected file name or field, or a weakening flag such as ``--no-lint``) and weakens it: a
    removal, edit, skip, stub or threshold change, or a phrase such as "not applicable" or "too
    strict". "Never skip check:x" strengthens and passes. A sentence that weakens "it" or "this"
    is refused when the previous sentence named a target.
    """
    if not isinstance(text, str):
        text = json.dumps(text, sort_keys=True) if text is not None else ''
    targets = _targets(manifest or load_manifest(), known_ids)
    hits, previous = [], False
    for sentence in _SENTENCE.split(text.replace('`', ' ')):
        named = any(t.search(sentence) for t in targets)
        if _weakens(sentence) and (named or (previous and _PRONOUN.search(sentence))):
            hits.append(sentence.strip()[:200])
        previous = named
    return hits


def fix_errors(fix, *, manifest=None, root=None, known_ids=()) -> list[str]:
    """Reasons an RCA fix or other learned edit is refused; empty means it touches nothing protected."""
    if not isinstance(fix, dict):
        return ['fix must be an object']
    manifest = manifest or load_manifest()
    errors = []
    for edit in fix.get('edits') or []:
        path = edit.get('path') if isinstance(edit, dict) else edit
        if path and is_protected(path, manifest=manifest, root=root):
            errors.append(f'edits protected path {path} ({", ".join(protecting_entries(path, manifest=manifest, root=root)) or "unresolvable"})')
        pointer = edit.get('pointer') if isinstance(edit, dict) else None
        field = pointer is not None and edit_field(pointer, edit.get('value'), manifest=manifest)
        if field:
            errors.append(f'edits protected field {field} at {pointer}')
    text = ' \n'.join(str(fix.get(k) or '') for k in ('required_fix', 'rationale', 'body', 'root_cause'))
    errors += [f'do-not-learn: {s}' for s in suppression_rule(text, known_ids=known_ids, manifest=manifest)]
    return errors


# ----------------------------------------------------------------------------- evaluator hashes

def _sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def _layout(root):
    """``(layout, package directory)`` for a source checkout or an installed ``site-packages`` root."""
    root = Path(root)
    if (root / 'src' / 'ravel').is_dir() or not (root / 'ravel').is_dir():
        return 'source', None
    return 'installed', root / 'ravel'


def evaluator_snapshot(root=None, *, manifest=None) -> dict:
    """sha256 of every existing protected file; take one before and one after each worker.

    In an installed (non-editable) package the ``src/ravel/**`` entries are read from the
    installed ``ravel`` directory and keyed by their source spelling; entries outside the package
    (agent instructions, tests, CI) do not exist there and the snapshot says ``layout: installed``.
    A snapshot that resolves no protected file is refused: it could not detect any change.
    """
    manifest, root = manifest or load_manifest(), Path(root or SOURCE_ROOT)
    layout, package = _layout(root)
    files = {}
    for entry in manifest['entries']:
        for pattern in entry['paths']:
            base_root, local, prefix = root, pattern, ''
            if package is not None:
                if not pattern.startswith('src/ravel/'):
                    continue
                base_root, local, prefix = package, pattern[len('src/ravel/'):], 'src/ravel/'
            fixed = local.split('/')
            base = base_root.joinpath(*fixed[:next((i for i, s in enumerate(fixed) if any(c in s for c in '*?[')), len(fixed))])
            pool = [base] if base.is_file() else (base.rglob('*') if base.is_dir() else [])
            for p in pool:
                rel = p.relative_to(base_root).as_posix()
                if p.is_file() and '__pycache__' not in p.parts and _match(local, rel):
                    files[prefix + rel] = _sha(p)
    if not files:
        raise ValueError(f'no protected file resolves under {root}; an empty evaluator snapshot cannot seal a receipt')
    files = dict(sorted(files.items()))
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {'schema_version': 1, 'kind': 'evaluator-snapshot', 'layout': layout, 'root': str(root),
            'digest': digest, 'files': files}


def seal_worker_receipt(receipt, before, after) -> dict:
    """A copy of the receipt with both evaluator digests; a changed evaluator voids it."""
    if not before.get('files') or not after.get('files'):
        raise ValueError('an evaluator snapshot with no protected file cannot seal a receipt')
    sealed = dict(receipt)
    sealed['evaluator'] = {'before': before['digest'], 'after': after['digest'],
                           'layout': after.get('layout', 'source')}
    if before['digest'] != after['digest']:
        a, b = before['files'], after['files']
        changed = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        sealed['void'] = {'code': 'evaluator_changed', 'changed': changed}
    return sealed


def receipt_void_reason(receipt) -> str | None:
    """Why a worker receipt is void: an evaluator change, a missing seal or a seal that is not two sha256 digests."""
    if isinstance(receipt.get('void'), dict):
        return receipt['void'].get('code') or 'void'
    seal = receipt.get('evaluator')
    if not isinstance(seal, dict) or not seal.get('before') or not seal.get('after'):
        return 'evaluator_unsealed'
    if not all(isinstance(seal[k], str) and _HEX64.fullmatch(seal[k]) for k in ('before', 'after')):
        return 'evaluator_seal_malformed'
    return 'evaluator_changed' if seal['before'] != seal['after'] else None


# ----------------------------------------------------------------------------- RCA investigators

def investigator_bundle(results) -> list[dict]:
    """Check id and verdict (plus finding and receipt ids) per result; never source, predicate or threshold."""
    bundle = []
    for row in results:
        if not isinstance(row, dict) or not row.get('check_id') or 'verdict' not in row:
            raise ValueError('every check result needs check_id and verdict')
        bundle.append({k: row[k] for k in INVESTIGATOR_KEYS if k in row})
    return bundle


def bundle_errors(bundle) -> list[str]:
    """Keys in an investigator bundle beyond id and verdict, which could carry check source."""
    rows = bundle.get('checks') if isinstance(bundle, dict) else bundle
    if not isinstance(rows, list):
        return ['investigator bundle needs a list of checks']
    return [f'check {row.get("check_id", "?") if isinstance(row, dict) else "?"} carries {sorted(set(row) - set(INVESTIGATOR_KEYS)) if isinstance(row, dict) else "a non-object"}'
            for row in rows if not isinstance(row, dict) or set(row) - set(INVESTIGATOR_KEYS)]


# ----------------------------------------------------------------------------- run-time artefact scan

def _writes(record):
    for key in ('output_pins', 'outputs', 'declared_outputs', 'writes'):
        for row in record.get(key) or []:
            path = row.get('path') if isinstance(row, dict) else row
            if isinstance(path, str):
                yield key, path


def artefact_errors(record, *, manifest=None, root=None) -> list[str]:
    """Findings for one run-time record: protected writes, protected edits, suppression, leaked source."""
    if not isinstance(record, dict):
        return []
    manifest, kind = manifest or load_manifest(), str(record.get('kind', ''))
    errors = [f'{key} writes protected path {path}' for key, path in _writes(record)
              if is_protected(path, manifest=manifest, root=root)]
    if record.get('edits') or kind in ('rca-fix', 'learned-fix'):
        errors += fix_errors(record, manifest=manifest, root=root)
    elif any(record.get(k) for k in ('required_fix', 'root_cause')):
        # RCA text under any record kind (a broker receipt carrying a fix, for example).
        errors += fix_errors({k: record.get(k) for k in ('required_fix', 'root_cause')}, manifest=manifest, root=root)
    if isinstance(record.get('rca'), dict):
        errors += fix_errors({k: record['rca'].get(k) for k in ('required_fix', 'root_cause', 'edits')},
                             manifest=manifest, root=root)
    if kind == 'lesson' or ('confirming_check' in record and 'trigger' in record):
        errors += [f'do-not-learn: {s}' for s in suppression_rule(' \n'.join(str(record.get(k) or '') for k in ('title', 'body')))]
    if kind == 'rca-investigator-bundle':
        errors += bundle_errors(record)
    if kind in ('agent-worker-receipt', 'worker-receipt') and record.get('evaluator') is not None and receipt_void_reason(record) \
            and not record.get('void'):
        errors.append(f'worker receipt is not void although {receipt_void_reason(record)}')
    return errors


def scan(roots, *, manifest=None, root=None) -> list[str]:
    """Findings over every JSON or JSONL run-time artefact under ``roots``."""
    manifest = manifest or load_manifest()
    findings = []
    for top in roots:
        top = Path(top)
        pool = [top] if top.is_file() else sorted(top.rglob('*.json*')) if top.is_dir() else []
        for path in pool:
            if path.suffix not in ('.json', '.jsonl') or path.stat().st_size > MAX_SCAN_BYTES:
                continue
            try:
                text = path.read_text()
                records = [json.loads(line) for line in text.splitlines() if line.strip()] if path.suffix == '.jsonl' \
                    else [json.loads(text)]
            except (OSError, ValueError):
                continue
            for record in records:
                findings += [f'{path}: {e}' for e in artefact_errors(record, manifest=manifest, root=root)]
    return findings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('roots', nargs='*', type=Path, help='run-time artefact files or directories to scan')
    ap.add_argument('--root', type=Path, default=SOURCE_ROOT, help='source checkout the manifest is relative to')
    ap.add_argument('--manifest', type=Path, default=MANIFEST)
    ap.add_argument('--check-manifest', action='store_true', help='also require every required entry to match a file')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args(argv)
    manifest = load_manifest(args.manifest)
    findings = manifest_errors(manifest, args.root) if args.check_manifest else []
    findings += scan(args.roots, manifest=manifest, root=args.root)
    if args.json:
        print(json.dumps({'ok': not findings, 'findings': findings}, indent=1))
    else:
        print('\n'.join(findings) if findings else 'protected paths: ok')
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main())
