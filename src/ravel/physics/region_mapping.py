"""Exact, explicit signal/CR injection into supplied HistFactory workspaces."""
from copy import deepcopy
import math
from pathlib import Path

from ravel.workflow.science import regular
from ravel.workflow.state_io import read_json, atomic_json


def apply_mapping(mapping, selections, base, out):
    fields = {'workspace', 'poi', 'weight_name', 'normalization', 'channels', 'omitted_regions', 'mc_modifier'}
    if set(mapping) != fields:
        raise ValueError('mapping requires exact workspace, POI, weight, normalization, channels, omissions and MC modifier')
    norm = mapping['normalization']
    if set(norm) != {'kind', 'factor', 'source'} or norm['kind'] != 'events_per_input_weight' or not isinstance(norm['source'], str) or not norm['source'].strip():
        raise ValueError('normalization requires a documented events-per-input-weight conversion')
    factor = norm['factor']
    if type(factor) not in (float, int) or not math.isfinite(factor) or factor <= 0:
        raise ValueError('normalization factor must be finite and positive')
    regions = selections['region_names']
    if mapping['weight_name'] not in selections['weight_names']:
        raise ValueError('mapping weight stream is missing')
    workspace = read_json(regular(mapping['workspace'], base))
    result = deepcopy(workspace)
    poi = mapping['poi']
    if not isinstance(poi, str) or not poi:
        raise ValueError('explicit POI required')
    targets = {}
    for channel in result['channels']:
        for sample in channel['samples']:
            if any(m['name'] == poi and m['type'] == 'normfactor' for m in sample['modifiers']):
                key = (channel['name'], sample['name'])
                if key in targets:
                    raise ValueError('duplicate likelihood channel/sample')
                targets[key] = sample
    if not targets:
        raise ValueError('workspace has no samples controlled by declared POI')
    mappings, used = {}, []
    for row in mapping['channels']:
        if set(row) != {'channel', 'sample', 'regions', 'role'} or row['role'] not in ('signal', 'control', 'validation'):
            raise ValueError('each mapping requires explicit channel, sample, bin regions and role')
        key = (row['channel'], row['sample'])
        if key in mappings or key not in targets or len(row['regions']) != len(targets[key]['data']):
            raise ValueError('channel/sample mapping missing, duplicated or has wrong bin count')
        if any(r not in regions for r in row['regions']):
            raise ValueError('unknown selection region')
        mappings[key] = row
        used.extend(row['regions'])
    if mappings.keys() != targets.keys():
        raise ValueError('every POI-controlled sample, including control-region signal, must be mapped')
    if len(used) != len(set(used)):
        raise ValueError('a selection region cannot populate multiple independent likelihood bins')
    omitted = mapping['omitted_regions']
    if not isinstance(omitted, dict) or set(omitted) != set(regions) - set(used) or any(not isinstance(v, str) or not v.strip() for v in omitted.values()):
        raise ValueError('each unmapped region needs an explicit omission reason')
    for i, a in enumerate(used):
        for b in used[i+1:]:
            if selections['region_overlap_counts'][a][b]:
                raise ValueError(f'overlapping regions cannot be independent HistFactory bins: {a}, {b}')
    name = mapping['mc_modifier']
    if not isinstance(name, str) or not name or name == poi:
        raise ValueError('explicit non-POI MC modifier name required')
    existing = {m['name'] for c in result['channels'] for s in c['samples'] for m in s['modifiers']}
    if name in existing:
        raise ValueError('MC modifier name collides with supplied model')
    ys = selections['yields'][mapping['weight_name']]
    cov = selections['covariance'][mapping['weight_name']]
    for i, a in enumerate(used):
        for b in used[i+1:]:
            if cov[regions.index(a)][regions.index(b)] != 0:
                raise ValueError('correlated event groups require a covariance-aware MC model; independent staterror is insufficient')
    zero_bins = []
    for key, row in mappings.items():
        sample = targets[key]
        # Relative rate systematics transfer. Absolute templates must be supplied
        # again for the new signal, never inherited from another mass/model.
        if any(m['type'] not in ('normfactor', 'normsys') for m in sample['modifiers']):
            raise ValueError('signal carries non-transferable shape/absolute modifiers; supply model-specific systematics')
        indices = [regions.index(r) for r in row['regions']]
        values = [ys[i] * factor for i in indices]
        if any(v < 0 or not math.isfinite(v) for v in values):
            raise ValueError('signed signal bins cannot be clipped into a Poisson model')
        errors = [math.sqrt(cov[i][i]) * factor for i in indices]
        if any(v == 0 and error > 0 for v, error in zip(values, errors)):
            raise ValueError('zero signal from signed-weight cancellation cannot carry a relative HistFactory MC uncertainty')
        sample['data'] = values
        sample['modifiers'].append({'name': name, 'type': 'staterror', 'data': errors})
        zero_bins.extend({'channel': key[0], 'region': regions[i]} for i in indices if cov[i][i] == 0)
    try:
        import pyhf
    except ImportError as exc:
        raise ValueError('likelihood mapping requires the ravel-hep[replay] extra') from exc
    ws = pyhf.Workspace(result)
    if not any(m['config']['poi'] == poi for m in result['measurements']):
        raise ValueError('mapped POI has no measurement in the workspace')
    # Validate every model instead of accepting JSON shape alone.
    for m in result['measurements']:
        ws.model(measurement_name=m['name'])
    atomic_json(Path(out) / 'mapped-workspace.json', result)
    return {'workspace': 'mapped-workspace.json', 'channels': mapping['channels'], 'omitted_regions': omitted,
            'zero_mc_bins': zero_bins, 'inference_ready': not zero_bins, 'physics_validated': False,
            'scope': 'Exact supplied signal/CR mapping; detector/systematic and zero-selected-bin precision validation remain separate'}
