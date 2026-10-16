"""Python statistics seams for supplied workspaces and shared binned yields.

These functions do no native execution or input acquisition. They retain units,
moments and model identity, and do not manufacture experimental covariance.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math

from ravel.physics import binned_values


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def search_yields(document):
    """Project absolute independent-bin event yields into the search core.

    Correlated finite-MC covariance needs a different model; never diagonalize
    it silently. All bins must carry moments from their producer.
    """
    doc = binned_values.validate(deepcopy(document))
    normalization = doc.get('normalization', {})
    absolute = normalization.get('kind') == 'absolute' or (
        normalization.get('kind') == 'normalized' and normalization.get('original_kind') == 'absolute')
    if doc['unit'] != 'events' or doc['representation'] != 'integrated' or not absolute:
        raise ValueError('search requires absolute integrated event yields')
    if any(b['value'] < 0 for b in doc['bins']):
        raise ValueError('search requires nonnegative nominal yields')
    covariance = doc.get('covariance')
    if covariance is not None and any(v != 0 for i,row in enumerate(covariance) for j,v in enumerate(row) if i != j):
        raise ValueError('correlated covariance cannot enter the independent-bin search interface')
    moments = doc.get('sumw2')
    if moments is None:
        if not all('sumw2' in b for b in doc['bins']):
            raise ValueError('search requires producer sumw2 for every bin')
        moments = [b['sumw2'] for b in doc['bins']]
    if covariance is not None and any(covariance[i][i] != moment for i,moment in enumerate(moments)):
        raise ValueError('covariance diagonal differs from producer sumw2')
    return {'values':[b['value'] for b in doc['bins']], 'sumw2':list(moments),
            **({'quantity': deepcopy(doc['quantity'])} if 'quantity' in doc else {})}


def measurement_prediction(document):
    """Supply aligned prediction/covariance records to the measurement core.

    The returned covariance is producer sampling covariance, not an invented
    experimental covariance or a declaration of independent theory errors.
    """
    doc = binned_values.validate(deepcopy(document))
    ids = doc.get('provenance', {}).get('bin_ids')
    if not isinstance(ids, list) or len(ids) != len(doc['bins']) or any(not isinstance(i,str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('measurement needs explicit unique producer bin_ids')
    matrix = doc.get('covariance')
    if matrix is None:
        raise ValueError('measurement needs explicit producer covariance')
    import numpy as np
    scale = max(float(np.max(np.abs(matrix))), 1e-300)
    if float(np.linalg.eigvalsh(matrix).min()) < -1e-12 * scale:
        raise ValueError('producer covariance is not positive semidefinite')
    return {'prediction':{'bin_ids':ids,'unit':doc['unit'],'values':[b['value'] for b in doc['bins']]},
            'covariance':{'bin_ids':ids,'unit':f"({doc['unit']})^2",'matrix':matrix},
            'representation':doc['representation'], 'bins':doc['bins'],
            'normalization':doc.get('normalization'), 'provenance':doc.get('provenance'),
            'source_sha256':_digest(doc),
            **({'quantity': deepcopy(doc['quantity'])} if 'quantity' in doc else {})}


def profile_likelihood(workspace, *, poi_values, measurement=None, released=None):
    """Fit a supplied HistFactory workspace and profile explicit POI points.

    Profiles are delta(-2 log L), without a threshold, confidence region or
    asymptotic coverage assertion. A supplied released contract is checked
    before fitting. Fit exceptions and nonfinite results propagate as failures.
    pyhf uses process-global backends: callers must serialize this function.
    """
    if not isinstance(poi_values, (list,tuple)) or not 1 <= len(poi_values) <= 256:
        raise ValueError('profile needs 1..256 explicit POI coordinates')
    for value in poi_values:
        binned_values.number(value, 'profile coordinate')
    parity = None
    if released is not None:
        from ravel.validation.patch_parity import patch_parity
        parity = patch_parity(released['background'], released['patchset'], workspace,
                              patch_name=released['patch_name'], record_id=released['record_id'])
        if parity['status'] != 'pass':
            raise ValueError('patch parity failed: ' + json.dumps(parity['mismatches'], sort_keys=True))
    import numpy as np
    import pyhf
    previous = pyhf.get_backend()
    # Importing the engine installs its backend; the finally block restores the caller's.
    from ravel.physics import pyhf_exclude as engine
    guard = engine.robust_optimizer
    escalated_before = guard.escalated
    counters = ('n_fits', 'n_fallback', 'n_nan_flagged', 'n_escalated')
    start = {key: getattr(guard, key) for key in counters}
    spec = deepcopy(workspace)
    try:
        # SLSQP with guarded-MIGRAD fallback; trust is scoped to this one model.
        guard.escalated = False
        pyhf.set_backend('numpy', guard(maxiter=200000))
        ws = pyhf.Workspace(spec)
        names = [m['name'] for m in spec['measurements']]
        if measurement is None:
            if len(names) != 1:
                raise ValueError('select an unambiguous measurement')
            measurement = names[0]
        if names.count(measurement) != 1:
            raise ValueError('selected measurement is missing or ambiguous')
        model = ws.model(measurement_name=measurement)
        data = ws.data(model)
        index = model.config.poi_index
        if index is None or model.config.suggested_fixed()[index]:
            raise ValueError('profile requires a free POI')
        low, high = model.config.suggested_bounds()[index]
        if any(not low <= value <= high for value in poi_values):
            raise ValueError('profile coordinate outside POI bounds')

        def fit_record(parameters, objective):
            parameters = np.asarray(parameters, dtype=float)
            value = float(np.asarray(objective).ravel()[0])
            if not np.all(np.isfinite(parameters)) or not math.isfinite(value):
                raise RuntimeError('nonfinite profile fit result')
            return {'parameters':parameters.tolist(), 'twice_nll':value}

        best = fit_record(*pyhf.infer.mle.fit(data, model, return_fitted_val=True))
        profiles = []
        for coordinate in poi_values:
            row = fit_record(*pyhf.infer.mle.fixed_poi_fit(float(coordinate), data, model, return_fitted_val=True))
            delta = row['twice_nll'] - best['twice_nll']
            if delta < -1e-5:
                raise RuntimeError('profile objective below best-fit objective')
            profiles.append({'poi':float(coordinate), **row, 'delta_twice_nll':max(0.,delta),
                             'raw_delta_twice_nll':delta})
        return {'schema_version':1, 'kind':'profile-likelihood', 'status':'passed', 'engine':'pyhf',
                'engine_version':pyhf.__version__, 'workspace_sha256':_digest(spec), 'measurement':measurement,
                'poi':{'name':model.config.poi_name,'index':index,'bounds':[low,high]},
                'parameter_names':model.config.par_names, 'data':list(data), 'best_fit':best, 'profiles':profiles,
                'patch_parity':parity,
                'optimizer':{'name':'robust_optimizer', 'maxiter':200000, 'starts':'pyhf suggested initialization',
                             'escalated':bool(guard.escalated),
                             'n_minimizations':guard.n_fits - start['n_fits'],
                             'n_fallback':guard.n_fallback - start['n_fallback'],
                             'n_nan_flagged':guard.n_nan_flagged - start['n_nan_flagged'],
                             'n_escalated':guard.n_escalated - start['n_escalated']},
                'scope':'Supplied-model profile fits; no confidence threshold or coverage validation',
                'limitations':['Single-start local fits do not establish a global optimum.',
                               'Negative delta(-2 log L) within 1e-5 is clipped to zero; signed raw differences are retained.'],
                'physics_validated':False}
    finally:
        guard.escalated = escalated_before
        pyhf.set_backend(*previous)


def main(argv=None):
    import argparse
    from pathlib import Path
    from ravel.physics.published_model import _json
    from ravel.workflow.state_io import atomic_json
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workspace', required=True)
    ap.add_argument('--poi-values', type=float, nargs='+', required=True)
    ap.add_argument('--measurement')
    ap.add_argument('--released', help='JSON object with background, patchset, patch_name and record_id')
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)
    result = profile_likelihood(_json(Path(args.workspace).read_bytes()), poi_values=args.poi_values,
                                measurement=args.measurement,
                                released=_json(Path(args.released).read_bytes()) if args.released else None)
    atomic_json(Path(args.out), result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
