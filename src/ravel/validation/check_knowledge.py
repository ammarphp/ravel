"""Check generated knowledge completeness, source drift and typed link resolution."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
from ravel.workflow.knowledge_atlas import ATLAS, encode, generate, source_root
from ravel.workflow.knowledge_lessons import lesson_errors
from ravel.workflow.lesson_store import promotion_errors

LESSONS = 'src/ravel/data/knowledge/lessons'
# Trees whose text must state physics, never paraphrase the request that prompted it.
ANTI_BENCH_TREES = ('src/ravel/data/knowledge', 'docs/workflow/checklists',
                    'src/ravel/data/workflow/docs/workflow/checklists')
# Request deixis: a quoted request phrase, or prose that points at "the ask/request".
_DEIXIS = tuple(re.compile(p, re.I) for p in (
    r'["\u201c][^"\u201d\n]{3,80}["\u201d]\s+(?:ask|request|prompt|query)\b',
    r'\bthe\s+(?:ask|request|prompt)\s+(?:goes|extends|reaches|covers)\b',
    r'\b[\w+/-]+\s+(?:ask|request)\s+(?:goes|extends|reaches)\b'))


def request_paraphrase_errors(root=None, literals=()):
    """Files under the knowledge and checklist trees that paraphrase a request.

    Generic deixis patterns always apply. Held-out request phrases are supplied through
    ``literals`` or a one-phrase-per-line file named by RAVEL_BENCH_LITERALS; none is kept here.
    """
    root = Path(root or source_root())
    phrases = [p.casefold() for p in literals]
    listing = os.environ.get('RAVEL_BENCH_LITERALS')
    if listing and Path(listing).is_file():
        phrases += [l.strip().casefold() for l in Path(listing).read_text().splitlines() if l.strip()]
    errors = []
    for tree in ANTI_BENCH_TREES:
        for path in sorted((root / tree).rglob('*')) if (root / tree).is_dir() else []:
            if not path.is_file() or path.suffix not in ('.json', '.md', '.txt'):
                continue
            text = path.read_text(errors='replace')
            folded = text.casefold()
            relative = path.relative_to(root).as_posix()
            for pattern in _DEIXIS:
                match = pattern.search(text)
                if match:
                    errors.append(f'{relative}: request paraphrase: {match.group(0)[:60]!r}')
            errors += [f'{relative}: registered request phrase present' for p in phrases if p in folded]
    return errors


def lesson_store_errors(root=None, check_ids=None):
    """Schema and rule errors of every shipped lesson record."""
    root = Path(root or source_root())
    store = root / LESSONS
    if not store.is_dir():
        return []
    from jsonschema import Draft202012Validator
    schema_path = root / 'src/ravel/data/knowledge/schema/lesson.json'
    validator = Draft202012Validator(json.loads(schema_path.read_text())) if schema_path.is_file() else None
    errors = []
    for path in sorted(store.glob('*.json')):
        try:
            row = json.loads(path.read_text())
        except ValueError as exc:
            errors.append(path.name + ': unreadable lesson: ' + str(exc)); continue
        if validator is not None:
            errors += [f'{row.get("id", path.name)}: schema: {e.message}' for e in validator.iter_errors(row)]
        errors += lesson_errors(row, check_ids=check_ids)
        errors += promotion_errors(row)
    return errors


def reference_row_errors(root=None):
    """Validate published comparator directories without fetching missing sources."""
    root = Path(root or source_root())
    directory = root / 'src/ravel/data/knowledge/qualification'
    if not directory.is_dir():
        return []
    from ravel.validation.qualification_rows import check_directory
    return check_directory(directory, source_cache=os.environ.get('RAVEL_SOURCE_CACHE'))


def validate(root=None, atlas=None, *, require_curation=True):
    root = Path(root or source_root())
    errors = []
    try:
        expected = generate(root)
        actual = atlas if atlas is not None else json.loads((root / ATLAS).read_text())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return ['cannot generate/read knowledge: ' + str(exc)]
    if encode(actual) != encode(expected): errors.append('atlas source drift or omission: regenerate knowledge_atlas --write')
    from jsonschema import Draft202012Validator
    schema = json.loads((root / 'src/ravel/data/knowledge/schema/entry.json').read_text())
    validator = Draft202012Validator(schema)
    rows = actual.get('entries', [])
    for row in rows:
        errors.extend(str(row.get('id')) + ': schema: ' + e.message for e in validator.iter_errors(row))
    errors += lesson_store_errors(root, {row.get('id') for row in rows if row.get('kind') == 'check'})
    errors += reference_row_errors(root)
    errors += request_paraphrase_errors(root)
    ids = [row.get('id') for row in rows]
    if len(ids) != len(set(ids)): errors.append('duplicate atlas IDs')
    by_id = {row.get('id'):row for row in rows}
    for row in rows:
        for key, values in row.get('links', {}).items():
            for identity in values if isinstance(values,list) else [values]:
                if identity not in by_id: errors.append(f'{row["id"]}: unresolved {key} link {identity}')
        if row.get('kind') == 'op':
            card = row.get('catalogue', {})
            if card.get('kind')=='science-mode' and not card.get('adapter_exists'): errors.append(row['id'] + ': adapter source absent')
            if card.get('kind')=='science-mode' and not card.get('worker_destination'): errors.append(row['id'] + ': worker absent')
            if not row['links'].get('docs'): errors.append(row['id'] + ': docs mention absent')
            for hb in row['links'].get('handbooks', []):
                if row['id'] not in by_id.get(hb, {}).get('links', {}).get('operations', []):
                    errors.append(row['id'] + ': handbook map not inverse')
            if card.get('kind')=='science-mode' and (require_curation or row.get('curation_source')):
                if not row['op'].get('use_when') or not row['op'].get('examples'):
                    errors.append(row['id'] + ': curation requires use_when and examples')
                if not row['op'].get('do_not_use_when'):
                    errors.append(row['id'] + ': curation requires do_not_use_when')
            for example in row['op'].get('examples', []):
                try:
                    from ravel.workflow.science import adapter
                    spec = example['spec']
                    if spec['mode'] != row['id'][3:]: raise ValueError('example mode differs from card')
                    adapter(spec).validate(spec['task'])
                except (ImportError, KeyError, TypeError, ValueError) as exc:
                    errors.append(row['id'] + ': offline example refused: ' + str(exc))
            if set(row['op'].get('effects', [])) & {'generates_events','executes_native','runs_authored_code'}:
                if not row['links'].get('checks') and not row['links'].get('consult_role'):
                    errors.append(row['id'] + ': consequential operation lacks a check or consult')
        if row.get('kind') == 'hb' and '#' not in row['id']:
            for op in row['links'].get('operations', []):
                if row['id'] not in by_id.get(op, {}).get('links', {}).get('handbooks', []):
                    errors.append(row['id'] + ': operation map not inverse')
    return sorted(set(errors))


def report(root=None, *, require_curation=True):
    root=Path(root or source_root()); errors=validate(root, require_curation=require_curation)
    try: rows=json.loads((root / ATLAS).read_text())['entries']
    except (OSError, ValueError, KeyError): rows=[]
    ops=[r for r in rows if r['kind']=='op' and r.get('catalogue',{}).get('kind')=='science-mode']; pitfalls=[r for r in rows if r['kind']=='hb' and '#' in r['id']]
    return {'valid':not errors,'errors':errors,'entries':len(rows),'advisories':{
        'uncurated_operations':[r['id'] for r in ops if not r['op'].get('examples')],
        'declared_vocabulary':[r['id'] for r in ops if r['op']['vocabulary_status']=='declared_vocabulary'],
        'advisory_pitfall_share':sum(r.get('advisory',False) for r in pitfalls)/len(pitfalls) if pitfalls else 0}}


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--root',type=Path); ap.add_argument('--json',action='store_true'); ap.add_argument('--structural', action='store_true', help='Check the atlas structure; report operation-curation gaps as advisories')
    args=ap.parse_args(argv)
    try: result=report(args.root,require_curation=not args.structural)
    except FileNotFoundError as exc: print(str(exc),file=__import__('sys').stderr); return 2
    print(json.dumps(result,indent=2) if args.json else '\n'.join(result['errors']) if result['errors'] else f'Knowledge atlas OK: {result["entries"]} entries; {len(result["advisories"]["uncurated_operations"])} await curated examples')
    return 0 if result['valid'] else 1

if __name__=='__main__':raise SystemExit(main())
