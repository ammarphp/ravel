"""Verify portable count, moment and shape arithmetic without a physics rerun.

This cannot authenticate raw events that are retained outside this public bundle.
"""
from pathlib import Path
import argparse
import json
import math

import numpy as np


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(value):
    require(value['generated_events'] == 20000, 'Changed exposure')
    require(value['mt2_edges_GeV'] == [100, 100.5, 101, 102, 105, 110, 120, 130, 140], 'Changed bins')
    for name in ('historical', 'fresh', 'official'):
        for band in ('high', 'low'):
            row = value[name][band] if name == 'official' else value[name]['bands'][band]
            if name == 'official':
                y, variance = np.array(row['nominal_yields']), np.array(row['mc_variance'])
            else:
                counts = np.array(row['counts'])
                require(counts.shape == (8,) and np.all(counts >= 0) and np.all(counts == counts.astype(int)), 'Invalid counts')
                require(int(counts.sum()) == row['count_total'], 'Count total differs')
                require(sum(f['total'] for f in row['flavors'].values()) == row['count_total'], 'Flavor total differs')
                require(np.array_equal(np.sum([f['counts'] for f in row['flavors'].values()], axis=0), counts), 'Flavor bins differ')
                weight = value[name]['per_row_weight_pb']
                require(weight > 0, 'Nonpositive uniform weight')
                y, variance = np.array(row['sumw_pb']), np.array(row['sumw2_pb2'])
                require(np.allclose(y, counts * weight, rtol=1e-11, atol=0), 'Count/weight mismatch')
                require(np.allclose(variance, counts * weight**2, rtol=1e-11, atol=0), 'Squared-weight mismatch')
            require(y.shape == (8,) and variance.shape == (8,) and y.sum() > 0, 'Invalid moment shape')
            require(np.all(np.isfinite(y)) and np.all(np.isfinite(variance)) and np.all(variance >= 0), 'Invalid moments')
            f = y / y.sum()
            jac = (np.eye(8) - f[:, None]) / y.sum()
            cov = (jac * variance) @ jac.T
            require(np.allclose(f, row['fraction'], rtol=1e-12, atol=1e-14), 'Fraction mismatch')
            require(np.allclose(cov, row['covariance'], rtol=1e-11, atol=1e-14), 'Covariance mismatch')
            require(np.allclose(np.sqrt(np.maximum(np.diag(cov), 0)), row['standard_error'], rtol=1e-11, atol=1e-14), 'Error mismatch')
    census = value['production_state_census']
    require(sum(row['generated_events'] for row in census.values()) == 20000, 'Incomplete production census')
    for band in ('high', 'low'):
        require(np.array_equal(np.sum([row[band] for row in census.values()], axis=0), value['fresh']['bands'][band]['counts']), 'Census/selection mismatch')
    light = np.sum([row['high'] for name, row in census.items() if not name.startswith('stau')], axis=0)
    require(np.array_equal(light, value['composition_controls']['without_staus_high_counts']), 'Wrong stau removal')
    require(math.isclose(light[2] / light.sum(), value['composition_controls']['without_staus_primary_fraction'], abs_tol=1e-12), 'Wrong stau fraction')
    require(value['trace']['input_events'] == 20000, 'Incomplete reconstructed trace')
    require(value['trace']['stages']['final_high']['mt2_counts'] == value['fresh']['bands']['high']['counts'], 'Trace/ROOT disagreement')
    require(set(value['stage_seconds']) == {'prepare', 'madgraph', 'unpack_lhe', 'lhe_check', 'pythia', 'normalization', 'delphes', 'analysis', 'simpleanalysis', 'native_report'}, 'Changed execution scope')
    require(all(value[key] is False for key in ('physics_certified', 'acceptance_certified', 'full_plane_reproduced')), 'Unjustified certification')
    return {'status': 'passed', 'scope': 'Portable aggregate arithmetic only; raw-event and physics certification remain unavailable', 'physics_certified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path(__file__).with_name('measurements.json'))
    args = parser.parse_args()
    print(json.dumps(verify(json.loads(args.input.read_text())), indent=2))
