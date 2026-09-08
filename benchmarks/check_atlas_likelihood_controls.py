#!/usr/bin/env python3
"""Two bounded, cached ATLAS controls of the common inference engine.

Run single-threaded. These test a counting approximation and a released-workspace
free fit, not new simulation, detector agreement or full-plane reproduction.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ravel.physics import pyhf_exclude as exclude


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    exclude.pyhf.set_backend('numpy', exclude.robust_optimizer(maxiter=200000, tolerance=1e-9), precision='64b')
    # s=1 event makes the POI an S95 in events, independent of simulated signal.
    inputs = dict(n=263, b=283., db=24., s=1.)
    model, data = exclude.model_from_counting(inputs)
    counting = exclude.compute(model, data, n_curve=5)
    case = next(c for c in json.loads((ROOT/'benchmarks/cases.json').read_text())['cases']
                if c['case_id'] == 'ins1458270_squark_800_100')
    expected, observed = case['published']['s95_exp'], case['published']['s95_obs']
    counting_result = {'analysis': 'ATLAS_2016_I1458270', 'region': '2jl', 'input': inputs,
                       'reference_observed': observed, 'reference_expected': expected,
                       'observed_ratio': counting['obs_limit']/observed,
                       'median_expected_ratio': counting['exp_limits'][2]/expected,
                       'scope': 'Published fitted-background single-bin approximation; missing full likelihood correlations.',
                       'result': counting}
    # Exercise the actual released three-lepton likelihood's known false-success
    # failure without repeating a full six-root multi-bin inference campaign.
    fixture = ROOT/'src/ravel/data/fixtures/susy-2018-06'
    bkg, patch = fixture/'BkgOnly.json', fixture/'patch_ERJR_300p0_100p0.json'
    model, data = exclude.model_from_likelihood(str(bkg), str(patch))
    exclude.robust_optimizer.escalated = False
    pars, objective = exclude.pyhf.infer.mle.fit(data, model, return_fitted_val=True)
    nll, mu = float(objective), float(pars[model.config.poi_index])
    freefit = {'analysis': 'ATLAS-SUSY-2018-06', 'point': 'ERJR_300p0_100p0',
               'twice_nll': nll, 'mu_hat': mu,
               'regression_reference': {'twice_nll': 271.786, 'mu_hat': .2446},
               'passed': abs(nll-271.786)<.01 and abs(mu-.2446)<.02,
               'scope': 'Free-fit regression only; full observed/expected limits not rerun.'}
    passed = (counting['limit_status'] == {'observed': 'resolved', 'expected': ['resolved']*5}
              and abs(counting_result['observed_ratio']-1)<.03
              and abs(counting_result['median_expected_ratio']-1)<.03 and freefit['passed'])
    paths = [bkg, patch, ROOT/'benchmarks/cases.json', Path(__file__),
             ROOT/'src/ravel/physics/pyhf_exclude.py']
    record = {'scope': 'Fresh cached-input numerical controls across two ATLAS analyses; no events generated',
              'counting': counting_result, 'published_workspace_free_fit': freefit,
              'passed': passed, 'wall_seconds': time.monotonic()-started,
              'runtime': {'python': platform.python_version(), **{k: importlib.metadata.version(k)
                          for k in ('pyhf', 'numpy', 'scipy', 'iminuit')}},
              'inputs_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2)+'\n')
    print(json.dumps({'passed': passed, 'counting_observed': counting['obs_limit'],
                      'counting_expected': counting['exp_limits'][2], 'free_fit': freefit,
                      'wall_seconds': record['wall_seconds']}))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
