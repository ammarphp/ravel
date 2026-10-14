"""Run a native SimpleAnalysis routine port on flat reconstructed ntuples.

A supplied format descriptor maps the ntuple's branches to the routine object
model: per-object kinematics, the energy unit, the flags that select stored
objects, and which flags set which SimpleAnalysis ID and isolation bits. The
event weight is the product of the named weight branches. Nothing about the
ntuple format is assumed in code; a bit name must exist in the routine's
SimpleAnalysis vocabulary.

Science mode ``reco-ntuple-routine``; task:
  {"descriptor": path, "ntuples": [path, ...], "routine": <registered routine>,
   "max_events": int | null}

The result holds raw counts and weighted sums (sumw, sumw2) per routine region
over the supplied events. Normalisation to a cross section and luminosity is a
separate step with its own declared inputs.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from . import sa_native_core as core

DESCRIPTOR_KEYS = ('schema_version', 'kind', 'tree', 'energy_unit', 'event_number', 'weights', 'sort_by_pt',
                   'collections', 'met')
COLLECTIONS = ('electron', 'muon', 'jet')
OBJECT_KEYS = ('pt', 'eta', 'phi', 'charge', 'mass', 'require', 'id_bits', 'default_bits')
UNITS = {'MeV': 1e-3, 'GeV': 1.0}
ALL_BITS = 0x7FFFFFFF
SCOPE = 'Routine regions on supplied reconstructed ntuples through a supplied branch map'


def _pin(path):
    path = Path(path).absolute()
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def _bit(name):
    value = getattr(core, name, None) if type(name) is str and not name.startswith('_') else None
    if type(value) is not int or value <= 0 or name in {'ELECTRON', 'MUON', 'NotBit'} or value > ALL_BITS:
        raise ValueError(f'unknown SimpleAnalysis ID bit name: {name!r}')
    return value


def _bits(spec):
    if spec == 'all':
        return ALL_BITS
    if type(spec) is not list or any(type(x) is not str for x in spec):
        raise ValueError('bit lists are lists of SimpleAnalysis bit names, or "all"')
    value = 0
    for name in spec:
        value |= _bit(name)
    return value


def validate_descriptor(value):
    if type(value) is not dict or set(value) != set(DESCRIPTOR_KEYS):
        raise ValueError('reco ntuple descriptor requires exactly ' + ', '.join(DESCRIPTOR_KEYS))
    if value['schema_version'] != 1 or value['kind'] != 'reco-ntuple-format':
        raise ValueError('reco-ntuple-format/v1 descriptor required')
    if type(value['tree']) is not str or not value['tree']:
        raise ValueError('tree name required')
    if value['energy_unit'] not in UNITS:
        raise ValueError('energy_unit must be MeV or GeV')
    if value['event_number'] is not None and type(value['event_number']) is not str:
        raise ValueError('event_number is a branch name or null')
    if type(value['weights']) is not list or not value['weights'] or any(type(x) is not str or not x for x in value['weights']):
        raise ValueError('name the event-weight branches explicitly; unit weights are never assumed')
    if type(value['sort_by_pt']) is not bool:
        raise ValueError('sort_by_pt must be stated')
    if type(value['collections']) is not dict or set(value['collections']) != set(COLLECTIONS):
        raise ValueError('electron, muon and jet collections are all required')
    for name, row in value['collections'].items():
        if type(row) is not dict or set(row) != set(OBJECT_KEYS):
            raise ValueError(f'{name} collection requires exactly ' + ', '.join(OBJECT_KEYS))
        for key in ('pt', 'eta', 'phi'):
            if type(row[key]) is not str or not row[key]:
                raise ValueError(f'{name}.{key} branch required')
        if name in ('electron', 'muon') and (type(row['charge']) is not str or not row['charge']):
            raise ValueError(f'{name}.charge branch required')
        if name == 'jet' and (type(row['mass']) is not str or not row['mass']):
            raise ValueError('jet.mass branch required; jet masses are never assumed')
        if type(row['require']) is not list or any(type(x) is not str for x in row['require']):
            raise ValueError(f'{name}.require is a list of flag branches')
        if type(row['id_bits']) is not list:
            raise ValueError(f'{name}.id_bits is a list')
        for entry in row['id_bits']:
            if type(entry) is not dict or set(entry) != {'flag', 'bits'} or type(entry['flag']) is not str:
                raise ValueError(f'{name}.id_bits entries are {{flag, bits}}')
            _bits(entry['bits'])
        _bits(row['default_bits'])
    met = value['met']
    if type(met) is not dict or set(met) not in ({'pt', 'phi'}, {'px', 'py'}) or any(type(v) is not str for v in met.values()):
        raise ValueError('met maps either {pt, phi} or {px, py} branches')
    return value


def branches(descriptor):
    names = list(descriptor['weights'])
    if descriptor['event_number']:
        names.append(descriptor['event_number'])
    for row in descriptor['collections'].values():
        names += [row[k] for k in ('pt', 'eta', 'phi', 'charge', 'mass') if row[k]]
        names += row['require'] + [e['flag'] for e in row['id_bits']]
    names += list(descriptor['met'].values())
    return list(dict.fromkeys(names))


def _split(values, counts):
    import numpy as np
    out = np.empty(len(counts), dtype=object)
    offsets = np.concatenate([[0], np.cumsum(counts)])
    for i in range(len(counts)):
        out[i] = values[offsets[i]:offsets[i + 1]]
    return out


def convert(descriptor, table):
    """Flat-ntuple arrays -> the routine's Delphes2SA-style per-event arrays."""
    import awkward as ak
    import numpy as np
    scale = UNITS[descriptor['energy_unit']]
    n = len(table[descriptor['weights'][0]])
    arrays = {}
    prefixes = {'electron': 'el', 'muon': 'mu', 'jet': 'jet'}
    for name, row in descriptor['collections'].items():
        pt = ak.values_astype(table[row['pt']], np.float64) * scale
        keep = ak.ones_like(pt, dtype=bool)
        for flag in row['require']:
            keep = keep & (table[flag] != 0)
        bits = ak.values_astype(ak.zeros_like(pt), np.int64) + _bits(row['default_bits'])
        for entry in row['id_bits']:
            bits = bits | ak.where(table[entry['flag']] != 0, _bits(entry['bits']), 0)
        fields = {'pt': pt, 'eta': ak.values_astype(table[row['eta']], np.float64),
                  'phi': ak.values_astype(table[row['phi']], np.float64), 'id': bits}
        if row['charge']:
            fields['charge'] = ak.values_astype(table[row['charge']], np.float64)
        if row['mass']:
            fields['m'] = ak.values_astype(table[row['mass']], np.float64) * scale
        fields = {k: v[keep] for k, v in fields.items()}
        if descriptor['sort_by_pt']:
            order = ak.argsort(fields['pt'], ascending=False, stable=True)
            fields = {k: v[order] for k, v in fields.items()}
        counts = ak.to_numpy(ak.num(fields['pt']))
        prefix = prefixes[name]
        for key, values in fields.items():
            flat = ak.to_numpy(ak.flatten(values))
            arrays[f'{prefix}_{key}'] = _split(flat.astype(np.int64) if key == 'id' else flat, counts)
    met = descriptor['met']
    if 'pt' in met:
        arrays['met_pt'] = ak.to_numpy(table[met['pt']]).astype(np.float64) * scale
        arrays['met_phi'] = ak.to_numpy(table[met['phi']]).astype(np.float64)
    else:
        px = ak.to_numpy(table[met['px']]).astype(np.float64) * scale
        py = ak.to_numpy(table[met['py']]).astype(np.float64) * scale
        arrays['met_pt'], arrays['met_phi'] = np.hypot(px, py), np.arctan2(py, px)
    weight = np.ones(n, dtype=np.float64)
    for name in descriptor['weights']:
        weight = weight * ak.to_numpy(table[name]).astype(np.float64)
    events = (ak.to_numpy(table[descriptor['event_number']]).astype(np.int64) if descriptor['event_number']
              else np.arange(n, dtype=np.int64))
    arrays['Event'] = events
    arrays['mcWeights'] = _split(weight, np.ones(n, dtype=np.int64))
    return arrays, weight, events


def read(descriptor, paths, max_events=None):
    import awkward as ak
    import uproot
    tables = []
    remaining = max_events
    for path in paths:
        tree = uproot.open(path)[descriptor['tree']]
        missing = [b for b in branches(descriptor) if b not in tree.keys()]
        if missing:
            raise ValueError(f'{path}: branches named by the descriptor are missing: ' + ', '.join(missing))
        stop = None if remaining is None else min(remaining, tree.num_entries)
        tables.append(tree.arrays(branches(descriptor), entry_stop=stop, library='ak'))
        if remaining is not None:
            remaining -= len(tables[-1])
            if remaining <= 0:
                break
    return ak.concatenate(tables) if len(tables) > 1 else tables[0]


def _routine(name):
    from .sa_routines import resolve_routine, REGISTRY
    from .native_capabilities import load_aliases
    name = load_aliases().get(name, {}).get("adapter", name)
    if name not in REGISTRY:
        raise ValueError('routine must be one of the registered native ports: ' + ', '.join(sorted(REGISTRY)))
    return resolve_routine(name)


def validate(task):
    if type(task) is not dict or set(task) != {'descriptor', 'ntuples', 'routine', 'max_events'}:
        raise ValueError('reco-ntuple-routine requires descriptor, ntuples, routine and max_events')
    if type(task['descriptor']) is not str or not task['descriptor']:
        raise ValueError('descriptor path required')
    if type(task['ntuples']) is not list or not task['ntuples'] or any(type(p) is not str or not p for p in task['ntuples']):
        raise ValueError('at least one ntuple path required')
    if len(set(task['ntuples'])) != len(task['ntuples']):
        raise ValueError('an ntuple may be named once')
    if task['max_events'] is not None and (type(task['max_events']) is not int or task['max_events'] <= 0):
        raise ValueError('max_events is a positive integer or null')
    if type(task['routine']) is not str or not task['routine']:
        raise ValueError('explicit routine identity required')


def _path(value, base):
    path = Path(value)
    return (path if path.is_absolute() else Path(base) / path).absolute()


def inputs(task, base):
    validate(task)
    routine = _routine(task['routine'])
    return [_path(task['descriptor'], base), *[_path(p, base) for p in task['ntuples']],
            *(Path(pin['path']) for pin in routine.ANALYSIS_PACKAGE['source_pins']), Path(core.__file__), Path(__file__)]


def run(task, base, output):
    validate(task)
    descriptor_path = _path(task['descriptor'], base)
    descriptor = validate_descriptor(json.loads(descriptor_path.read_text()))
    paths = [_path(p, base) for p in task['ntuples']]
    routine = _routine(task['routine'])
    table = read(descriptor, paths, task['max_events'])
    arrays, weight, events = convert(descriptor, table)
    order = routine.sr_order()
    counts = {sr: 0 for sr in order}
    sumw = {sr: 0.0 for sr in order}
    sumw2 = {sr: 0.0 for sr in order}
    for i in range(len(weight)):
        selected = routine.select(arrays, i)
        if selected is None:
            continue
        accepted = selected[0]
        w = float(weight[i])
        for sr in accepted:
            counts[sr] += 1
            sumw[sr] += w
            sumw2[sr] += w * w
    totals = core.summarize_weights(weight)
    if output is not None:
        out = Path(output)
        out.mkdir(parents=True, exist_ok=True)
        core.write_txt(out / f'{routine.NAME}.txt', counts, order,
                       {**totals, 'w_all': weight, 'Ngen': len(weight)}, sumw=sumw, sumw2=sumw2)
        from .yield_hub import write_regions
        write_regions(out / 'binned-values.json', order, sumw, sumw2,
                      provenance={'descriptor': _pin(descriptor_path), 'routine': _pin(routine.__file__)})
    if not all(math.isfinite(v) for v in (*sumw.values(), *sumw2.values())):
        raise ValueError('non-finite weighted region sums')
    return {'schema_version': 1, 'kind': 'reco-ntuple-routine-result', 'status': 'passed', 'status_scope': SCOPE,
            'routine': routine.NAME, 'events_read': int(len(weight)),
            'sum_weights_read': totals['sumW'], 'sum_weights_squared_read': totals['sumW2'],
            'regions': [{'id': sr, 'raw': counts[sr], 'sumw': sumw[sr], 'sumw2': sumw2[sr]} for sr in order],
            'descriptor': _pin(descriptor_path), 'ntuples': [_pin(p) for p in paths],
            'routine_source': _pin(routine.__file__), 'physics_validated': False,
            'limitations': [
                'The branch map and the ID and isolation flag-to-bit mapping are supplied data; their equivalence to the routine\'s original object definitions is not established here.',
                'The routine port was validated on its original input format; agreement on these ntuples is a separate comparison.',
                'Weighted sums cover the events read; normalisation to a cross section and luminosity needs separately declared inputs.']}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel reco-ntuple', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    c = commands.add_parser('check', help='validate a descriptor against ntuple branches; no selection is run')
    c.add_argument('--descriptor', type=Path, required=True)
    c.add_argument('--ntuple', type=Path, action='append', default=[])
    commands.add_parser('routines', help='list registered native routine ports')
    args = parser.parse_args(argv)
    try:
        if args.command == 'routines':
            from .sa_routines import REGISTRY
            result = {'routines': sorted(REGISTRY)}
        else:
            descriptor = validate_descriptor(json.loads(args.descriptor.read_text()))
            result = {'descriptor': _pin(args.descriptor), 'branches': branches(descriptor), 'ntuples': []}
            if args.ntuple:
                import uproot
                for path in args.ntuple:
                    tree = uproot.open(path)[descriptor['tree']]
                    missing = [b for b in branches(descriptor) if b not in tree.keys()]
                    result['ntuples'].append({'path': str(path), 'entries': tree.num_entries, 'missing_branches': missing})
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'reco ntuple: {exc}\n')
    print(json.dumps(result, indent=2))
    return 0 if all(not r['missing_branches'] for r in result.get('ntuples', [])) else 1


if __name__ == '__main__':
    raise SystemExit(main())
