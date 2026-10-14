"""Supplied reviewed repair records for the fixed source fixture.

The package holds no repair record of its own: every transformation, hold and
placement below is test-supplied, byte-bound input. Software controls only.
"""
import hashlib
import json
from pathlib import Path
from source_record_fixtures import defect_registry, pin, reviewed, write

CARDS = 'sfitter/data'
TOP = CARDS + '/Top_Full.json'
NOTE_LINE = 284
MIXED_OLD, MIXED_NEW = 'D6qq18x6qt8', 'D6qq18xD6qt8'
HOLD_ID = 'FIXTURE-RESPONSE-HOLD'


def records_directory(tmp, label):
    """One directory per record: the builders write fixed file names."""
    directory = Path(tmp) / ('records-' + label)
    directory.mkdir()
    return directory


def experimental(modifiers):
    return sorted(json.dumps(m, sort_keys=True, separators=(',', ':'))
                  for m in modifiers if m['type'] not in ('theo', 'pois'))


def top_manifest(tmp, root, *, label='repair', context=None):
    """Explicit repair manifest for the fixture's complete top card; returns (binding, manifest)."""
    directory = records_directory(tmp, label)
    path = Path(root) / TOP
    earlier = Path(root) / CARDS / 'TopLikelihood_22WC.json'
    note = Path(root) / 'sfitteragents/docs/CONFLICTS_AND_NOTES.md'
    card = json.loads(path.read_bytes())
    older = json.loads(earlier.read_bytes())
    quote = note.read_bytes().splitlines()[NOTE_LINE - 1].decode()
    evidence = {'source': 'note', 'line_start': NOTE_LINE, 'line_end': NOTE_LINE, 'quote': quote,
                'quote_sha256': hashlib.sha256(quote.encode()).hexdigest()}
    row = card['observations'][1]
    transforms = [
        # The mispaired row takes the earlier card's measurement with the same experimental modifiers.
        {'operation': 'copy', 'path': '/observations/1/ID', 'expected': row['ID'],
         'source': 'earlier', 'source_path': '/observations/1/ID'},
        {'operation': 'copy', 'path': '/observations/1/name', 'expected': row['name'],
         'source': 'earlier', 'source_path': '/observations/1/name'},
        {'operation': 'copy', 'path': '/observations/1/Meas/data', 'expected': [32.9],
         'source': 'earlier', 'source_path': '/observations/1/data'},
        {'operation': 'replace', 'path': '/observations/1/modifiers', 'expected': row['modifiers'],
         'value': [m for m in older['observations'][1]['modifiers'] if m['type'] == 'theo']}]
    for index in (3, 18):
        position = next(i for i, m in enumerate(card['predictions'][index]['modifiers']) if m['name'] == MIXED_OLD)
        transforms.append({'operation': 'replace', 'path': f'/predictions/{index}/modifiers/{position}/name',
                           'expected': MIXED_OLD, 'value': MIXED_NEW, 'evidence': evidence})
    for index in (13, 27):
        transforms.append({'operation': 'project-last', 'path': f'/predictions/{index}/modifiers',
                           'expected': card['predictions'][index]['modifiers'], 'key': 'name'})
    transforms.append({'operation': 'retain', 'path': '/observations/15/Meas/modifiers/7',
                       'expected': card['observations'][15]['Meas']['modifiers'][7]})
    registry = defect_registry(directory, card, sources={'card': pin(path)})
    manifest = reviewed(directory, 'repair-manifest',
        {'card': pin(path), 'earlier': pin(earlier), 'note': pin(note)},
        context=context or {'identity': 'ANA-0001', 'card_output': 'derived-card.json', 'output_format': 'json'},
        card_source='card', defect_registry=registry, identity_template='{identity}__sourceRow{row:03d}',
        transforms=transforms)
    return write(directory / 'manifest.json', manifest), manifest


def derived_review(tmp, root, derived, *, label='derived-review'):
    """Reviewed coverage of the derived card, with the retained unused measurement nuisance placed."""
    evaluator = Path(root) / 'sfitter/sfitter/likelihood/datacard.py'
    placement = {'path': '/observations/15/Meas/modifiers/7',
                 'expected': derived['observations'][15]['Meas']['modifiers'][7],
                 'native_disposition': 'retained_unused', 'evidence': ['evaluator']}
    return defect_registry(records_directory(tmp, label), derived, sources={'evaluator': pin(evaluator)},
                           support={'nuisance_placements': [placement]}), placement


def held_manifest(tmp, root, name, row, *, label='held'):
    """Manifest whose defect registry holds one located row of a supplied card; returns (binding, registry)."""
    directory = records_directory(tmp, label)
    path = Path(root) / CARDS / name
    card = json.loads(path.read_bytes())
    defect = {'id': HOLD_ID, 'source': 'card', 'observation_pointer': f'/observations/{row}',
              'prediction_pointer': f'/predictions/{row}',
              'reason': 'Paired measurement and prediction name different responses.',
              'resolution_required': 'Independent source evidence for the intended response.'}
    registry = defect_registry(directory, card, defects=[defect], sources={'card': pin(path)})
    manifest = reviewed(directory, 'repair-manifest', {'card': pin(path)},
        context={'identity': 'ANA-0002', 'card_output': 'derived-card.json', 'output_format': 'json'},
        card_source='card', defect_registry=registry, identity_template='{identity}__sourceRow{row:03d}',
        transforms=[])
    return write(directory / 'manifest.json', manifest), registry
