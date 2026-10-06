#!/usr/bin/env python3
"""Read preserved compressed outputs and check all 141 SRs after Event alignment.

Requires the source checkout's retained files and numpy/uproot. This does not
regenerate outputs, rerun selections, fit a model, or certify acceptance.
"""
import argparse
import csv
import datetime
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import uproot


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('output exists; preserve earlier verification')
    repo = args.repo.resolve()
    sys.path.insert(0, str(repo/'src'))
    from ravel.physics import native_simpleanalysis as native
    sources = ['src/ravel/physics/native_simpleanalysis.py',
               'src/ravel/physics/compressed_validation.py',
               'src/ravel/physics/sa2json_native.py']
    pins = {name: sha(repo/name) for name in sources}
    record = {'schema_version': 1, 'checked_utc': datetime.datetime.now(datetime.UTC).isoformat(),
              'scope': 'Read-only recheck of earlier retained-event selection outputs; 141 SR branch parity and CR moment transport, not a new selection replay or physics certificate.',
              'runtime': {'python': sys.version, 'numpy': np.__version__, 'uproot': uproot.__version__},
              'engine_sha256': pins, 'cases': []}
    cases = [('m150_dm20', 1000, 'trial-runs/2026-08-28_SUSY-2018-16_slepton-fig3-fresh/smoke_m150_dm20/output'),
             ('m200_dm50', 10000, 'trial-runs/CR005_refactor_smoke/output')]
    for label, exposure, previous in cases:
        previous = repo/previous
        current = repo/'local-runs/rrr-closure/signal-model'/(label+'_current')
        paths = [previous/'analysis/Delphes2SA.root', previous/'EwkCompressed2018.root',
                 previous/'EwkCompressed2018.txt', *sorted(p for p in current.iterdir() if p.is_file())]
        before = {str(p.relative_to(repo)): sha(p) for p in paths}
        metadata = json.loads((current/'compressed_validation.json').read_text())['source_metadata']
        assert metadata['input_events'] == exposure
        assert metadata['input_sha256'] == sha(previous/'analysis/Delphes2SA.root')
        assert metadata['selection_source_sha256'] == pins[sources[0]]
        assert metadata['diagnostic_source_sha256'] == pins[sources[1]]
        with uproot.open(previous/'EwkCompressed2018.root') as stream:
            old = stream['ntuple'].arrays(library='np')
        with uproot.open(current/'EwkCompressed2018.root') as stream:
            new = stream['ntuple'].arrays(library='np')
        old_index = {int(event): i for i, event in enumerate(old['Event'])}
        new_index = {int(event): i for i, event in enumerate(new['Event'])}
        assert len(old_index) == len(old['Event']) and len(new_index) == len(new['Event'])
        assert new_index.keys() <= old_index.keys()
        aligned = np.asarray([old_index[int(event)] for event in new['Event']])
        absent = np.asarray([i for event, i in old_index.items() if event not in new_index], dtype=int)
        branches = []
        for name in native.sr_order():
            lhs, rhs = old[name][aligned], new[name]
            equal = np.array_equal(lhs, rhs)
            storage_equal = lhs.dtype == rhs.dtype and lhs.tobytes() == rhs.tobytes()
            promoted_equal = lhs.astype(np.float64).tobytes() == rhs.astype(np.float64).tobytes()
            omitted_nonzero = int(np.count_nonzero(old[name][absent]))
            assert equal and promoted_equal and omitted_nonzero == 0, name
            branches.append({'region': name, 'aligned_values_exactly_equal': bool(equal),
                             'historical_dtype': str(lhs.dtype), 'current_dtype': str(rhs.dtype),
                             'aligned_storage_bytes_equal': storage_equal,
                             'float64_promoted_bytes_equal': promoted_equal,
                             'original_only_nonzero_rows': omitted_nonzero})
        with (current/'EwkCompressed2018.txt').open() as stream:
            counts = {row['SR']: int(row['events']) for row in csv.DictReader(stream)}
        controls = []
        for name in native.cr_order():
            weights = new[name]
            active = weights != 0
            controls.append({'region': name, 'raw_selected': counts[name],
                'sumw_pb': float(weights.sum()), 'sumw2_pb2': float(np.square(weights).sum()),
                'negative_weights': int(np.count_nonzero(weights < 0)),
                'different_flavour': int(np.count_nonzero(active & (new['isee'] == 0) & (new['ismm'] == 0)))})
        after = {str(p.relative_to(repo)): sha(p) for p in paths}
        assert before == after
        record['cases'].append({'label': label, 'input_events': exposure, 'old_rows': len(old['Event']),
            'new_rows': len(new['Event']), 'original_only_rows': len(absent),
            'comparison_policy': 'Align by unique Event ID; require exact numerical weight equality and identical bytes after lossless float64 promotion on shared rows, and all SR weights zero on original-only rows. Original storage dtypes can differ.',
            'sr_branches_compared': len(branches), 'sr_branches_equal': len(branches),
            'branches': branches, 'controls': controls, 'artifacts_sha256': before,
            'inputs_preserved': True, 'selection_rerun_in_this_check': False,
            'selection_source_binding': metadata})
    assert pins == {name: sha(repo/name) for name in sources}
    args.out.write_text(json.dumps(record, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'cases': len(record['cases']), 'sr_branches_equal': [c['sr_branches_equal'] for c in record['cases']], 'out': str(args.out)}))


if __name__ == '__main__':
    main()
