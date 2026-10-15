"""Shipped reviewed records for the released SFitter cards, bound to a selected source root.

The records under ``data/sfitter/published-records`` carry the published card repairs,
defect holds and evaluator conventions as ``repair-manifest`` and ``defect-registry``
documents whose source pins name root-relative files and exact sha256 values. ``bind``
writes copies whose pins are absolute for one selected source root, after checking that
the root holds the pinned card bytes, and returns the byte pins the existing derivation,
profile census and native-contract interfaces take. Nothing here repairs a card itself.
"""
import argparse
import hashlib
import json
from pathlib import Path
from . import reviewed_source as records

DIRECTORY = Path(__file__).resolve().parents[1] / 'data' / 'sfitter' / 'published-records'


def _read(name):
    raw = (DIRECTORY / name).read_bytes()
    return raw, records.document(raw)


def _pin(path):
    return {'path': str(path), 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def cards():
    """Released card names with a shipped record, and the card bytes each one binds."""
    index = _read('index.json')[1]
    return {name: dict(row['card']) for name, row in index['cards'].items()}


def _bound_sources(value, root):
    for label, pin in value['sources'].items():
        source = root / pin['path']
        if hashlib.sha256(_ordinary(source).read_bytes()).hexdigest() != pin['sha256']:
            raise records.SourceRecordError('source_scope_mismatch', 'pinned source bytes differ: ' + pin['path'])
        value['sources'][label] = {'path': str(source), 'sha256': pin['sha256']}


def _ordinary(path):
    if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise records.SourceRecordError('source_scope_mismatch', 'ordinary pinned source file required: ' + str(path))
    return path


def bind(source_root, card_name, output):
    """Write the bound repair manifest, defect registry and evidence note into a fresh directory."""
    index = _read('index.json')[1]
    row = index['cards'].get(card_name)
    if row is None:
        raise records.SourceRecordError('missing_repair_manifest', 'no shipped record for card ' + str(card_name))
    root = Path(source_root).absolute()
    if '..' in root.parts:
        raise ValueError('canonical absolute source root required')
    out = Path(output).absolute()
    if out.exists() or out.is_symlink() or any(p.is_symlink() for p in out.parents) or '..' in out.parts:
        raise ValueError('fresh ordinary bound-record directory required')
    if out.is_relative_to(root):
        raise ValueError('bound records stay outside the source tree')
    card = _ordinary(root / row['card']['path'])
    if hashlib.sha256(card.read_bytes()).hexdigest() != row['card']['sha256']:
        raise records.SourceRecordError('source_scope_mismatch', 'card bytes differ from the shipped record: ' + card_name)
    registry_raw, registry = _read(row['defect_registry'])
    manifest_raw, manifest = _read(row['repair_manifest'])
    if hashlib.sha256(registry_raw).hexdigest() != manifest['defect_registry']['sha256']:
        raise records.SourceRecordError('invalid_source_record', 'shipped registry differs from its manifest pin')
    note_raw = (DIRECTORY / 'review-note.md').read_bytes()
    for value in (registry, manifest):
        if [e['sha256'] for e in value['review']['evidence']] != [hashlib.sha256(note_raw).hexdigest()]:
            raise records.SourceRecordError('invalid_source_record', 'shipped evidence note differs from its pin')
        _bound_sources(value, root)
    out.mkdir(parents=True, exist_ok=False)
    (out / 'review-note.md').write_bytes(note_raw)
    registry_path = out / row['defect_registry']
    registry_path.write_text(json.dumps(registry, indent=1, allow_nan=False) + '\n')
    manifest['defect_registry'] = _pin(registry_path)
    manifest_path = out / row['repair_manifest']
    manifest_path.write_text(json.dumps(manifest, indent=1, allow_nan=False) + '\n')
    return {'card': card_name, 'repair_manifest': _pin(manifest_path), 'defect_registry': _pin(registry_path),
            'original_fingerprint': row['original_fingerprint'], 'derived_fingerprint': row['derived_fingerprint']}


def derive(source_root, card_name, output):
    """Derive the card with the shipped records bound into ``output``; returns (card, proof)."""
    from . import sfitter_card_derivation
    bound = bind(source_root, card_name, output)
    relative = _read('index.json')[1]['cards'][card_name]['card']['path']
    return sfitter_card_derivation.derive(source_root, relative, bound['repair_manifest'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True)
    parser.add_argument('--card', required=True, choices=sorted(cards()))
    parser.add_argument('--output', required=True, help='fresh directory for the bound records')
    args = parser.parse_args(argv)
    print(json.dumps(bind(args.source_root, args.card, args.output), indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
