"""Compare a constructed signal model with one released patch's structure.

Parity covers channels, signal samples and modifier name/type pairs. Signal
coefficients and modifier responses may differ for a new model. A pass is not
a density, uncertainty-size, acceptance or numerical calibration check.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

def canonical_background_digest(*args, **kwargs):
    from ravel.physics.published_model import canonical_background_digest as implementation
    return implementation(*args, **kwargs)


def _digest(doc):
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _named(rows, label):
    if not isinstance(rows, list):
        raise ValueError(label + ' must be a list')
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('name'), str) or not row['name'].strip():
            raise ValueError(label + ' needs nonempty names')
        if row['name'] in result:
            raise ValueError('duplicate ' + label + ': ' + row['name'] + '; names must be unique')
        result[row['name']] = row
    return result


def _modifiers(sample):
    result = set()
    names = set()
    rows = sample.get('modifiers')
    if not isinstance(rows, list):
        raise ValueError('sample needs modifiers')
    for row in rows:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k].strip() for k in ('name','type')):
            raise ValueError('modifier needs a name and type')
        if row['name'] in names:
            raise ValueError('duplicate modifier: ' + row['name'])
        names.add(row['name'])
        result.add((row['name'], row['type']))
    return result


def patch_parity(background, patchset, produced_workspace, *, patch_name, record_id):
    """Return named mismatches, refusing unknown/ambiguous source identities.

The selected patch must add samples to a digest-bound background. Compare the
actual added samples, including control channels; background-only channels do
not satisfy a released signal addition. Never union different patch points.
"""
    if not isinstance(record_id, str) or not record_id.strip():
        raise ValueError('record identity must be explicit')
    metadata = patchset.get('metadata', {})
    if metadata.get('references', {}).get('hepdata') != record_id:
        raise ValueError('released patchset record identity mismatch')
    if metadata.get('digests', {}).get('sha256') != canonical_background_digest(background):
        raise ValueError('released patchset background digest mismatch')
    patches = patchset.get('patches')
    if not isinstance(patches, list) or not patches:
        raise ValueError('released patchset needs patches')
    catalogue = _named([dict(p.get('metadata', {})) for p in patches], 'patch')
    if not isinstance(patch_name, str) or patch_name not in catalogue:
        raise ValueError('selected released patch is absent')
    selected = next(p for p in patches if p['metadata']['name'] == patch_name)
    channels = _named(background.get('channels'), 'background channel')
    if not channels:
        raise ValueError('background channels must be nonempty')
    expected = deepcopy(background)
    operations = selected.get('patch')
    if not isinstance(operations, list) or not operations:
        raise ValueError('selected patch needs signal additions')
    for op in operations:
        match = re.fullmatch(r'/channels/(0|[1-9][0-9]*)/samples/(0|[1-9][0-9]*|-)', str(op.get('path')))
        if op.get('op') != 'add' or match is None or set(op) != {'op','path','value'}:
            raise ValueError('only signal-sample add operations are supported')
        i = int(match[1])
        if i >= len(expected['channels']):
            raise ValueError('released patch channel index outside background')
        samples = expected['channels'][i]['samples']
        existing = _named(samples, 'sample')
        sample = op['value']
        _named([sample], 'signal sample')
        _modifiers(sample)
        if sample['name'] in existing:
            raise ValueError('released patch duplicates sample: ' + sample['name'])
        j = len(samples) if match[2] == '-' else int(match[2])
        if j > len(samples):
            raise ValueError('released sample index outside background')
        samples.insert(j, deepcopy(sample))
    reference = _named(expected['channels'], 'reference channel')
    actual = _named(produced_workspace.get('channels'), 'produced channel')
    mismatches = []

    def mismatch(check, channel, **details):
        mismatches.append({'check':check, 'channel':channel, **details})

    for name in sorted(set(reference) - set(actual)):
        mismatch('missing_channel', name)
    for name in sorted(set(actual) - set(reference)):
        mismatch('extra_channel', name)
    for name in sorted(set(reference) & set(actual)):
        before = _named(channels[name].get('samples'), 'background sample')
        wanted = _named(reference[name].get('samples'), 'reference sample')
        got = _named(actual[name].get('samples'), 'produced sample')
        for sample in sorted(set(wanted) - set(got)):
            mismatch('missing_background_sample' if sample in before else 'missing_signal_sample', name, sample=sample)
        for sample in sorted(set(got) - set(wanted)):
            mismatch('extra_sample', name, sample=sample)
        for sample in sorted(set(wanted) & set(got)):
            expected_mods, actual_mods = _modifiers(wanted[sample]), _modifiers(got[sample])
            for modifier, kind in sorted(expected_mods - actual_mods):
                mismatch('missing_modifier', name, sample=sample, modifier=modifier, type=kind)
            for modifier, kind in sorted(actual_mods - expected_mods):
                mismatch('extra_modifier', name, sample=sample, modifier=modifier, type=kind)
    return {'schema_version':1, 'kind':'patch-parity', 'status':'fail' if mismatches else 'pass',
            'record_id':record_id, 'patch_name':patch_name, 'mismatches':mismatches,
            'inputs_sha256':{'background':_digest(background), 'patchset':_digest(patchset), 'produced_workspace':_digest(produced_workspace)},
            'scope':'Channel/sample and modifier name/type parity; coefficients and responses are not compared',
            'physics_validated':False}


def main(argv=None):
    import argparse
    from pathlib import Path
    from ravel.physics.published_model import _json
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('background','patchset','produced','patch-name','record-id','out'):
        ap.add_argument('--' + name, required=True)
    args = ap.parse_args(argv)
    result = patch_parity(*[_json(Path(p).read_bytes()) for p in (args.background,args.patchset,args.produced)],
                          patch_name=args.patch_name, record_id=args.record_id)
    from ravel.workflow.state_io import atomic_json
    atomic_json(Path(args.out), result)
    return 0 if result['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
