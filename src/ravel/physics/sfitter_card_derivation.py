"""Supplied reviewed card transformations with complete source and row lineage."""
from copy import deepcopy
import json
from pathlib import Path
from . import reviewed_source as records


def derive(root, name, manifest=None):
    value, sources, inputs, capture = records.load(manifest, root, 'repair-manifest', 'missing_repair_manifest')
    original_path = Path(root).absolute() / name
    if '..' in original_path.parts or not original_path.is_relative_to(Path(root).absolute()):
        raise records.SourceRecordError('source_scope_mismatch','selected card must lie in source root')
    source = value['card_source']
    selected_path = Path(inputs[0]['path']).parent / value['sources'].get(source,{}).get('path','')
    if source not in sources or original_path != selected_path.absolute():
        raise records.SourceRecordError('source_scope_mismatch', 'selected card differs from repair manifest')
    original = records.document(sources[source])
    derived = deepcopy(original)
    from . import sfitter_higgs_support
    support = sfitter_higgs_support.require_supported(root, original, value['defect_registry'])
    if len(original.get('observations', [])) != len(original.get('predictions', [])):
        raise records.SourceRecordError('source_scope_mismatch', 'complete paired card required')
    lineage = [[index] for index in range(len(original['observations']))]
    changes = []
    for change in value['transforms']:
        operation = change['operation']
        if 'evidence' in change:
            evidence = change['evidence']
            if evidence['source'] not in sources:
                raise records.SourceRecordError('invalid_source_record','transformation evidence source absent')
            lines = sources[evidence['source']].splitlines()
            first, last = evidence['line_start'], evidence['line_end']
            quote = b'\n'.join(lines[first-1:last])
            import hashlib
            if (not first <= last <= len(lines) or quote != evidence['quote'].encode()
                    or hashlib.sha256(quote).hexdigest() != evidence['quote_sha256']):
                raise records.SourceRecordError('source_scope_mismatch','reviewed source explanation differs')
        before = deepcopy(records.select(derived, change['path']))
        if operation == 'replace':
            records.replace(derived, change['path'], change['expected'], change['value'])
        elif operation == 'copy':
            if change['source'] not in sources:
                raise records.SourceRecordError('invalid_source_record','copy source absent')
            source_value = records.select(records.document(sources[change['source']]), change['source_path'])
            records.replace(derived, change['path'], change['expected'], source_value)
        elif operation == 'coalesce':
            keep, remove = change['keep'], change['remove']
            if not 0 <= keep < remove < len(lineage):
                raise records.SourceRecordError('source_scope_mismatch', 'ordered paired coalescence indices required')
            from .sfitter_higgs_support import _physical_value
            for field in ('observations', 'predictions'):
                # Identical means equal typed records with exact rational numbers: the literal
                # spellings 0 and 0.0 of one coefficient are the same value; names, strings,
                # booleans and ordering stay distinct.
                if _physical_value(derived[field][keep]) != _physical_value(derived[field][remove]):
                    raise records.SourceRecordError('source_scope_mismatch', 'coalescence requires identical paired rows')
                del derived[field][remove]
            lineage[keep].extend(lineage.pop(remove))
        elif operation == 'project-last':
            modifiers = records.select(derived, change['path'])
            if records.encoded(modifiers) != records.encoded(change['expected']):
                raise records.SourceRecordError('source_scope_mismatch', 'complete modifier population changed')
            winners = {m[change['key']]: i for i, m in enumerate(modifiers)}
            projected = [m for i, m in enumerate(modifiers) if winners[m[change['key']]] == i]
            records.replace(derived, change['path'], modifiers, projected)
        elif operation == 'retain':
            if records.encoded(before) != records.encoded(change['expected']):
                raise records.SourceRecordError('source_scope_mismatch', 'retained field changed')
        changes.append({**deepcopy(change), 'before': before,
                        'after': deepcopy(records.select(derived, change['path']))})
    if len(derived['observations']) != len(lineage) or len(derived['predictions']) != len(lineage):
        raise records.SourceRecordError('source_scope_mismatch','transformation changed paired population without lineage')
    aliases = []
    for index, (observation, prediction) in enumerate(zip(derived['observations'], derived['predictions'])):
        if observation['ID'] != prediction['ID'] or observation['name'] != prediction['name']:
            raise records.SourceRecordError('source_scope_mismatch', 'remaining paired identity defect')
        old = observation['ID']
        identity = value['identity_template'].format(identity=old, row=lineage[index][0])
        observation['ID'] = prediction['ID'] = identity
        aliases.append({'derived_index': index, 'original_indices': lineage[index],
                        'original_ID': original['observations'][lineage[index][0]]['ID'],
                        'corrected_ID': old, 'native_ID': identity, 'name': observation['name']})
    if len({row['native_ID'] for row in aliases}) != len(aliases):
        raise records.SourceRecordError('source_scope_mismatch', 'identity template must preserve unique rows')
    capture.finish()
    proof = {'schema_version': 1, 'kind': 'sfitter_explicit_source_card_derivation',
             'original_name': name, 'repair_manifest': inputs[0], 'inputs': inputs + support['reviewed_inputs'],
             'context': deepcopy(value['context']), 'review': deepcopy(value['review']),
             'changes': changes, 'rows': aliases, 'scientific_input_holds': support['scientific_input_holds'],
             'original_observations': len(original['observations']), 'derived_observations': len(aliases),
             'original_bins': sum(len(o['Meas']['data']) for o in original['observations']),
             'derived_bins': sum(len(o['Meas']['data']) for o in derived['observations']),
             'physics_validated': False, 'scientific_card_review': 'required_separately'}
    return derived, proof


def profile_census(card, root, profile, run_pin, run_raw, base):
    """Assembly seam: use the selected review from captured run-card bytes."""
    import hashlib
    from . import sfitter_profiles, sfitter_inputs
    if hashlib.sha256(run_raw).hexdigest() != run_pin['sha256']:
        raise records.SourceRecordError('source_scope_mismatch','captured run settings differ')
    value = sfitter_profiles.yaml_document(run_raw)
    review = value.get('source_review')
    if review is not None:
        review = {**review,'path':str((Path(base)/Path(run_pin['path'])).absolute().parent/Path(review['path']))}
    return sfitter_inputs.inspect_profile_datacard(card,root,profile,source_review=review)


def materialize(root, name, output, manifest=None):
    from ravel.workflow.state_io import atomic_json
    document, lineage = derive(root, name, manifest)
    out = Path(output).absolute()
    if out.exists() or out.is_symlink() or any(p.is_symlink() for p in out.parents) or '..' in out.parts:
        raise ValueError('fresh ordinary derived-card directory required')
    if out.is_relative_to(Path(root).absolute()):
        raise ValueError('preserve original source tree')
    filename = lineage['context'].get('card_output')
    if not isinstance(filename,str):
        raise records.SourceRecordError('missing_card_output','explicit card output filename required')
    if Path(filename).name != filename or filename in ('', '.', '..', 'derivation.json'):
        raise ValueError('safe distinct card output filename required')
    card_path = out / filename
    output_format = lineage['context'].get('output_format')
    if output_format not in ('json','jsonl'):
        raise records.SourceRecordError('missing_output_format','explicit json or jsonl card output format required')
    out.mkdir(parents=True, exist_ok=False)
    import os, tempfile
    fd, temporary = tempfile.mkstemp(prefix='.card-',dir=out)
    try:
        with os.fdopen(fd,'w') as stream:
            stream.write(json.dumps(document,sort_keys=True,indent=2 if output_format=='json' else None,allow_nan=False)+'\n')
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,card_path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    import hashlib
    lineage['derived_card'] = {'path': str(card_path), 'sha256': hashlib.sha256(card_path.read_bytes()).hexdigest()}
    if derive(root, name, manifest) != (document, {k:v for k,v in lineage.items() if k != 'derived_card'}):
        raise ValueError('source derivation changed during materialization')
    atomic_json(out / 'derivation.json', lineage)
    return lineage


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True)
    parser.add_argument('--card', required=True, help='selected source card path relative to source root')
    parser.add_argument('--repair-manifest', required=True)
    parser.add_argument('--repair-manifest-sha256', required=True)
    parser.add_argument('--output', required=True)
    a = parser.parse_args(argv)
    materialize(a.source_root, a.card, a.output,
                {'path': a.repair_manifest, 'sha256': a.repair_manifest_sha256})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
