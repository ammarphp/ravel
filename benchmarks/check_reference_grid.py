#!/usr/bin/env python3
"""Exercise real ATLAS compressed-grid lookups without simulation or fitting.

The copied publication tables are the oracle. The legacy first-within-1-GeV
algorithm below is a diagnostic counterfactual, never a reference correction.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ravel.validation.certify_acceptance import _read_grid_table, published_acceff
from ravel.validation.reference_grid import NODE_TOLERANCE_GEV


def rows(table):
    iv = table['independent_variables']
    return [(x['value'], y['value'], z['value']) for x, y, z in zip(
        iv[0]['values'], iv[1]['values'], table['dependent_variables'][0]['values'], strict=True)]


def inspect(reference):
    result = {'scope': 'published-reference identity and units; no detector or limit certification',
              'tables': [], 'products': [], 'queries': 0, 'failures': []}
    tables = {f'figure_32{c}.yaml': yaml.safe_load((reference / f'figure_32{c}.yaml').read_text())
              for c in 'abcdef'}
    for name, table in tables.items():
        points = rows(table)
        item = {'table': name, 'nodes': len(points), 'legacy_wrong_coordinates': {},
                'legacy_wrong_values': {}, 'legacy_mismatches': {}, 'current_failures': 0}
        for order in ('original', 'reversed'):
            ordered = points if order == 'original' else points[::-1]
            mismatches = []
            for a, b, v in points:
                old = next(p for p in ordered if abs(p[0]-a) < 1 and abs(p[1]-b) < 1)
                if old[:2] != (a, b):
                    mismatches.append({'requested': [a, b], 'selected': list(old[:2]),
                                       'expected': v, 'legacy_value': old[2]})
            item['legacy_wrong_coordinates'][order] = len(mismatches)
            item['legacy_wrong_values'][order] = sum(m['expected'] != m['legacy_value'] for m in mismatches)
            item['legacy_mismatches'][order] = mismatches
        result['tables'].append(item)
    # Reorder the actual YAML values and exercise the production reader and the
    # separate acceptance/efficiency product adapter, including their unit scale.
    for reverse in (False, True):
        with tempfile.TemporaryDirectory(prefix='ravel-reference-grid-') as tmp:
            base = Path(tmp)
            (base / 'submission.yaml').write_bytes((reference / 'submission.yaml').read_bytes())
            for name, table in tables.items():
                transformed = copy.deepcopy(table)
                if reverse:
                    for column in transformed['independent_variables'] + transformed['dependent_variables']:
                        column['values'].reverse()
                (base / name).write_text(yaml.safe_dump(transformed))
                item = next(t for t in result['tables'] if t['table'] == name)
                for a, b, expected in rows(table):
                    value, label, off = _read_grid_table(base, name, a, b, NODE_TOLERANCE_GEV, 200.)
                    result['queries'] += 1
                    if value != expected or off or not label.startswith('grid node'):
                        item['current_failures'] += 1
                        result['failures'].append([name, a, b, reverse, value, expected, label])
            for region, acceptance, efficiency in [('SR-S', 'a', 'b'), ('SR-S-high', 'c', 'd'),
                                                   ('SR-S-low', 'e', 'f')]:
                acc = rows(tables[f'figure_32{acceptance}.yaml'])
                eff = {(a, b): v for a, b, v in rows(tables[f'figure_32{efficiency}.yaml'])}
                failures = 0
                for a, b, av in acc:
                    expected = (av * 1e-3) * eff[a, b]
                    value, label, off = published_acceff(str(base), region, 'slepton', a, b)
                    result['queries'] += 1
                    if value != expected or off or not label.startswith('grid node'):
                        failures += 1
                        result['failures'].append([region, a, b, reverse, value, expected, label])
                result['products'].append({'region': region, 'reversed': reverse,
                                           'nodes': len(acc), 'failures': failures})
    result['inputs_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted(reference.iterdir()) if p.is_file()}
    result['passed'] = not result['failures']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, default=ROOT / 'evidence/audits/2026-09-08-statistical-fidelity/reference')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = inspect(args.reference)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'queries': result['queries'], 'failures': len(result['failures']),
                      'legacy_wrong_coordinates': {
                          order: sum(t['legacy_wrong_coordinates'][order] for t in result['tables'])
                          for order in ('original', 'reversed')}}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
