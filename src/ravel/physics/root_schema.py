"""Read-only inspection of ROOT event files and a draft branch and weight contract.

``inspect(path)`` opens a file with uproot, lists every TTree and, for each leaf branch,
its type, interpretation, whether it is jagged (and the per-event length range), and,
from at most ``max_entries`` entries, the fraction of finite and of zero values and the
value range. Branches whose name contains ``weight`` get their sum, sum of squares and
negative fraction over the entries read. Nothing is written.

``draft_contract(report, tree)`` turns the report into a draft format descriptor for the
columnar engine (the branch contract) and a weight contract. A draft is a proposal for
CHECK-IN 1: it groups jagged branches by prefix into collections, maps recognisable
kinematic suffixes to fields, and lists every choice it could not make (a missing mass,
an undetermined energy unit, an ambiguous weight) under ``unresolved``. It never fills a
value it cannot read from the file.
"""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path

import awkward as ak
import numpy as np

MAX_BRANCHES = 5000
SUFFIXES = {'pt': 'pt', 'eta': 'eta', 'phi': 'phi', 'm': 'mass', 'mass': 'mass', 'e': 'energy', 'charge': 'charge',
            'q': 'charge', 'btag': 'btag', 'tautag': 'tautag', 'pdgid': 'pdg_id', 'pid': 'pdg_id'}


def _pin(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return {'path': str(Path(path).resolve()), 'sha256': h.hexdigest(), 'size': Path(path).stat().st_size}


def _numeric(values):
    try:
        flat = ak.to_numpy(ak.flatten(values, axis=None))
    except Exception:  # records, strings and other non-numeric layouts
        return None
    if flat.dtype.kind not in 'biuf':
        return None
    return flat.astype(float)


def _branch_report(branch, stop):
    row = {'name': branch.name, 'typename': branch.typename, 'interpretation': str(branch.interpretation)}
    try:
        values = branch.array(entry_stop=stop, library='ak')
    except Exception as exc:  # an unreadable branch is reported, not fatal
        row['readable'] = False
        row['error'] = type(exc).__name__
        return row
    row['readable'] = True
    jagged = values.ndim > 1 if hasattr(values, 'ndim') else False
    row['jagged'] = bool(jagged)
    if jagged:
        counts = ak.to_numpy(ak.num(values, axis=1))
        row['length'] = {'min': int(counts.min()) if counts.size else 0, 'max': int(counts.max()) if counts.size else 0}
    flat = _numeric(values)
    if flat is None:
        row['numeric'] = False
        return row
    row['numeric'] = True
    finite = np.isfinite(flat)
    row['values_read'] = int(flat.size)
    row['finite_fraction'] = float(finite.mean()) if flat.size else None
    row['zero_fraction'] = float((flat == 0).mean()) if flat.size else None
    if finite.any():
        good = flat[finite]
        row['range'] = [float(good.min()), float(good.max())]
        row['median'] = float(np.median(good))
    if 'weight' in branch.name.lower() and not jagged:
        row['weight'] = {'sum': float(flat[finite].sum()), 'sum_of_squares': float((flat[finite] ** 2).sum()),
                         'negative_fraction': float((flat < 0).mean()) if flat.size else None}
    return row


def inspect(path, *, max_entries=10_000, trees=None):
    """Report trees and branches of a ROOT file from at most `max_entries` entries."""
    import uproot
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'input must be a regular file: {path}')
    if type(max_entries) is not int or max_entries < 1:
        raise ValueError('max_entries must be a positive integer')
    report = {'schema_version': 1, 'kind': 'root-schema-report', 'file': _pin(path), 'max_entries': max_entries,
              'trees': [], 'writes': 'none'}
    with uproot.open(path) as f:
        names = sorted({key.split(';')[0] for key, cls in f.classnames().items() if cls == 'TTree'})
        for name in names:
            if trees is not None and name not in trees:
                continue
            tree = f[name]
            stop = min(tree.num_entries, max_entries)
            leaves = [b for b in tree.itervalues(recursive=True) if not b.branches]
            if len(leaves) > MAX_BRANCHES:
                raise ValueError(f'tree {name!r} has {len(leaves)} leaf branches; inspect fewer with --tree')
            report['trees'].append({'name': name, 'entries': int(tree.num_entries), 'entries_read': int(stop),
                                    'branches': [_branch_report(b, stop) for b in leaves]})
    return report


def _split(name):
    """('prefix', 'suffix') for names such as el_pt, Electron.PT or jet_pt_NOSYS."""
    base = re.sub(r'_NOSYS$', '', name)
    for sep in ('.', '_'):
        if sep in base:
            prefix, _, suffix = base.rpartition(sep)
            if prefix:
                return prefix, suffix.lower()
    return None, base.lower()


def draft_contract(report, tree=None):
    """A draft format descriptor and weight contract; unresolved choices are listed."""
    trees = report['trees'] if tree is None else [t for t in report['trees'] if t['name'] == tree]
    if len(trees) != 1:
        raise ValueError('name one tree with --tree; the file has ' + ', '.join(t['name'] for t in report['trees']))
    t = trees[0]
    unresolved = []
    groups = {}
    flat = {}
    for b in t['branches']:
        if not b.get('readable') or not b.get('numeric'):
            continue
        prefix, suffix = _split(b['name'])
        if b.get('jagged') and prefix:
            groups.setdefault(prefix, {})[suffix] = b
        elif not b.get('jagged'):
            flat[b['name']] = b
    collections = {}
    for prefix, members in sorted(groups.items()):
        fields = {}
        for suffix, b in sorted(members.items()):
            key = SUFFIXES.get(suffix, re.sub(r'[^a-z0-9_]', '_', suffix.lower()))
            if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', key) or key in fields:
                continue
            fields[key] = b['name']
        if not {'pt', 'eta', 'phi'} <= set(fields):
            continue
        name = re.sub(r'[^a-z0-9_]', '_', prefix.lower())
        collections[name] = {'fields': fields}
        if 'mass' not in fields:
            unresolved.append(f'collection {name!r}: no mass branch; declare a fixed mass with its source or a branch')
        pt = next((b for s, b in members.items() if SUFFIXES.get(s) == 'pt'), None)
        if pt and pt.get('median') is not None and pt['median'] > 1000:
            unresolved.append(f'collection {name!r}: median transverse momentum {pt["median"]:.4g}; '
                              'if the file stores MeV, declare scale 0.001 for every energy field')
    met = None
    for name in sorted(flat):
        prefix, suffix = _split(name)
        if prefix and 'met' in prefix.lower() and suffix in ('met', 'et', 'pt'):
            phi = next((n for n in flat if _split(n) == (prefix, 'phi')), None)
            if phi:
                met = {'magnitude': name, 'phi': phi}
                break
    if met is None:
        unresolved.append('missing transverse momentum: no flat magnitude and phi branch pair was recognised')
    weights = {n: b for n, b in flat.items() if 'weight' in n.lower()}
    event = {re.sub(r'[^a-z0-9_]', '_', n.lower()): n for n in sorted(weights)}
    if not weights:
        unresolved.append('event weight: no branch named like a weight; declare the generator weight or none')
    elif len(weights) > 1:
        unresolved.append('event weight: several weight branches; declare which is the generator weight and which '
                          'are factors')
    descriptor = {'schema_version': 1, 'kind': 'columnar-format', 'name': f'draft for {Path(report["file"]["path"]).name}',
                  'source': f'drafted by ravel root-schema from {report["file"]["sha256"]}; review before use',
                  'format': 'root', 'tree': t['name'], 'collections': collections, 'event': event}
    if met:
        descriptor['met'] = met
    weight_contract = {'candidates': [{'branch': n, **b['weight'], 'finite_fraction': b['finite_fraction'],
                                       'entries_read': t['entries_read']} for n, b in sorted(weights.items())],
                       'entries': t['entries'], 'entries_read': t['entries_read'],
                       'sums_cover_all_entries': t['entries_read'] == t['entries']}
    for c in weight_contract['candidates']:
        if c['sum'] == 0:
            unresolved.append(f'event weight {c["branch"]!r}: every value read is zero')
    return {'schema_version': 1, 'kind': 'root-schema-draft', 'status': 'draft_requires_review',
            'file': report['file'], 'branch_contract': descriptor, 'weight_contract': weight_contract,
            'unresolved': unresolved}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel root-schema', description=__doc__.splitlines()[0])
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--tree', action='append', help='inspect only this tree (repeatable)')
    parser.add_argument('--max-entries', type=int, default=10_000)
    parser.add_argument('--draft', action='store_true', help='also print a draft branch and weight contract')
    args = parser.parse_args(argv)
    try:
        report = inspect(args.input, max_entries=args.max_entries, trees=args.tree)
        out = {'report': report}
        if args.draft:
            out['draft'] = draft_contract(report, args.tree[0] if args.tree and len(args.tree) == 1 else None)
        print(json.dumps(out, indent=2, allow_nan=False, default=lambda x: None if isinstance(x, float) and math.isnan(x) else x))
    except (OSError, ValueError) as exc:
        parser.exit(1, f'root-schema refused: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
