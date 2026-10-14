"""Finite attributed compatibility delta for SFitterAgents6072a79e (MIT).

Only the copied SMC FitResults constructor and singleton no-pair branch change. The original tree is
retained. SMC/CRAFT do not emit flow importance-weight histograms; None means
unavailable, and cannot be passed off as an empty or fabricated histogram.
"""
import hashlib
from pathlib import Path

RELATIVE='sfitter/sfitter/fit/smc_fitter.py'
BEFORE='            marginal_effective_size=eff_size,\n'
AFTER=('            marginal_effective_size=eff_size,\n'
       '            w_bins_lin=None, w_hist_lin=None, w_bins_log=None, w_hist_log=None\n')

PAIR_BEFORE=('        if strategy_2d == "histogram":\n'
             '            profile_2d, bins_2d = self.profile_2d_histogram()\n')
PAIR_AFTER=('        if self.likelihood.dims_parameter == 1:\n'
            '            if strategy_2d not in ("histogram", "annealing"):\n'
            '                raise ValueError("Unknown profiling strategy " + str(strategy_2d))\n'
            '            profile_2d = []\n'
            '            bins_2d = np.linspace(self.lower_bounds, self.upper_bounds,\n'
            '                                  self.profile_2d_params["n_points"] + 1, axis=1)\n'
            '        elif strategy_2d == "histogram":\n'
            '            profile_2d, bins_2d = self.profile_2d_histogram()\n')

def projected_source(raw, expected):
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('original SMC source preimage differs')
    text=raw.decode('utf-8')
    if text.count(BEFORE)!=1 or text.count(PAIR_BEFORE)!=1:raise ValueError('exact constructor and absent-pair source joins required')
    return text.replace(BEFORE,AFTER).replace(PAIR_BEFORE,PAIR_AFTER).encode('utf-8')

def apply(root, expected):
    path=Path(root)/RELATIVE;original=path.read_bytes()
    derived=projected_source(original,expected)
    path.write_bytes(derived)
    if path.read_bytes()!=derived:raise ValueError('copied SMC compatibility emission differs')
    return {'relative':RELATIVE,'original_sha256':expected,
            'derived_sha256':hashlib.sha256(derived).hexdigest(),
            'reason':'required FitResults fields and mathematically absent singleton pair work',
            'unavailable_weight_histograms':True,'singleton_pairs':'empty pair arrays; original coordinate bin geometry retained',
            'numerical_algorithm_changed':False,
            'source_commit':'6072a79e0f132d61a927f11ed482a401b34f6e3f','license':'MIT'}
