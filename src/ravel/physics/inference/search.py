"""Search statistics with pyhf: SR/CR/VR models, discovery significance, CLs and fit diagnostics.

The input declares regions with roles (SR, CR, VR), background samples with
per-region yields and MC moments (sum of weights and sum of squared weights),
optional per-background normalisation factors, signal points, the MC-statistics
treatment, an optional systematics registry and the data mode:

- ``observed``: the declared observed counts (a blinded SR has none);
- ``mc-pseudo-data``: the sum of background yields, each scaled by an optional
  declared injection factor (for closure tests).

Validation regions never enter a fit. The background-only fit uses the CR
channels with iminuit (MIGRAD and HESSE) and reports normalisation factors,
pulls, the correlation matrix and post-fit predictions with residuals in every
region. Expected quantities use an Asimov dataset built from the nominal or
background-only-fitted parameters (``asimov_source``). Discovery uses q0;
exclusion uses CLs with the guarded optimizer of ``pyhf_exclude``.
"""
from __future__ import annotations

from copy import deepcopy
import math

import numpy as np

from .systematics import Registry

ROLES = ('SR', 'CR', 'VR')
MC_STATISTICS = ('staterror', 'shapesys', 'none')
DATA_MODES = ('observed', 'mc-pseudo-data')
ASIMOV_SOURCES = ('nominal', 'background-only-fit')
POI = 'mu'


def _pyhf():
    import pyhf
    from ravel.physics import pyhf_exclude
    pyhf.set_backend('numpy', pyhf_exclude.robust_optimizer(maxiter=200000))
    return pyhf, pyhf_exclude


def _array(values, label, *, nonnegative=False):
    if type(values) is not list or not values:
        raise ValueError(label + ' must be a nonempty list')
    out = np.array(values, float)
    if not np.all(np.isfinite(out)) or (nonnegative and np.any(out < 0)):
        raise ValueError(label + ' must be finite' + (' and nonnegative' if nonnegative else ''))
    return out


def _yields(raw, regions, label, mc_statistics):
    if type(raw) is not dict:
        raise ValueError(label + ' yields must map regions to values')
    unknown = set(raw) - set(regions)
    if unknown:
        raise ValueError(label + ' has yields for undeclared regions: ' + ', '.join(sorted(unknown)))
    out = {}
    for region, row in raw.items():
        if type(row) is not dict or 'values' not in row or set(row) - {'values', 'sumw2'}:
            raise ValueError(label + f' yields in {region} need values and sumw2')
        values = _array(row['values'], f'{label} {region} values')
        if len(values) != regions[region]:
            raise ValueError(label + f' yields in {region} have {len(values)} bins, the region has {regions[region]}')
        if 'sumw2' in row:
            sumw2 = _array(row['sumw2'], f'{label} {region} sumw2', nonnegative=True)
            if len(sumw2) != len(values):
                raise ValueError(label + f' sumw2 in {region} has the wrong length')
        elif mc_statistics != 'none':
            raise ValueError(label + f' yields in {region} need sumw2 for the {mc_statistics} treatment')
        else:
            sumw2 = None
        out[region] = {'values': values, 'sumw2': sumw2}
    return out


class SearchModel:
    def __init__(self, document):
        d = deepcopy(document)
        required = {'regions', 'backgrounds', 'signal_points', 'mc_statistics', 'systematics', 'data',
                    'computations', 'asimov_source', 'cls_level', 'mc_adequacy', 'contours'}
        if type(d) is not dict or set(d) != required:
            raise ValueError('search document needs exactly: ' + ', '.join(sorted(required)))
        self.document = d
        if d['mc_statistics'] not in MC_STATISTICS:
            raise ValueError('mc_statistics must be staterror, shapesys or none')
        if d['asimov_source'] not in ASIMOV_SOURCES:
            raise ValueError('asimov_source must be nominal or background-only-fit')
        level = d['cls_level']
        if type(level) not in (int, float) or not 0 < level < 1:
            raise ValueError('cls_level must be between zero and one')
        self.regions, self.roles, self.observed = {}, {}, {}
        for r in d['regions']:
            if type(r) is not dict or set(r) - {'name', 'role', 'observed', 'bins', 'description'} or r.get('role') not in ROLES:
                raise ValueError('regions need name, role (SR, CR or VR) and observed (null when blinded)')
            name = r['name']
            if type(name) is not str or not name.strip() or name in self.regions or name == POI:
                raise ValueError('regions need unique names')
            observed = None if r.get('observed') is None else _array(r['observed'], f'observed counts in {name}', nonnegative=True)
            bins = r.get('bins', None if observed is None else len(observed))
            self.roles[name], self.observed[name] = r['role'], observed
            self.regions[name] = bins
        self.backgrounds = []
        for bkg in d['backgrounds']:
            if type(bkg) is not dict or set(bkg) - {'name', 'yields', 'normfactor', 'source'}:
                raise ValueError('backgrounds need name, yields and normfactor')
            nf = bkg.get('normfactor')
            if nf is not None and (type(nf) is not str or not nf.strip() or nf == POI):
                raise ValueError('normfactor must be a parameter name other than mu, or null')
            self._infer_bins(bkg['yields'])
            self.backgrounds.append({'name': bkg['name'], 'normfactor': nf,
                                     'yields': _yields(bkg['yields'], self.regions, f'background {bkg["name"]}',
                                                       d['mc_statistics'])})
        names = [b['name'] for b in self.backgrounds]
        if not names or len(set(names)) != len(names) or 'signal' in names:
            raise ValueError('backgrounds need unique names (not "signal")')
        for region, bins in self.regions.items():
            if bins is None:
                raise ValueError(f'region {region} has no bins from observed counts or yields')
            if not any(region in b['yields'] for b in self.backgrounds):
                raise ValueError(f'region {region} has no background yields')
        self.points = []
        for point in d['signal_points']:
            if type(point) is not dict or set(point) - {'id', 'coordinates', 'yields', 'source'}:
                raise ValueError('signal points need id, coordinates and yields')
            self.points.append({'id': str(point['id']), 'coordinates': dict(point.get('coordinates') or {}),
                                'yields': _yields(point['yields'], self.regions, f'signal point {point["id"]}',
                                                  d['mc_statistics'])})
        if len({p['id'] for p in self.points}) != len(self.points):
            raise ValueError('signal point ids must be unique')
        self.registry = None if d['systematics'] is None else Registry(d['systematics'])
        data = d['data']
        if type(data) is not dict or data.get('mode') not in DATA_MODES or set(data) - {'mode', 'injections'}:
            raise ValueError('data needs mode observed or mc-pseudo-data, and injections')
        injections = data.get('injections') or {}
        if set(injections) - set(names) or any(type(v) not in (int, float) or not v >= 0 for v in injections.values()):
            raise ValueError('injections scale declared backgrounds by nonnegative factors')
        self.data_mode, self.injections = data['mode'], dict(injections)
        if self.data_mode == 'observed':
            missing = [r for r, role in self.roles.items() if role == 'CR' and self.observed[r] is None]
            if missing:
                raise ValueError('observed mode needs observed counts in every control region: ' + ', '.join(missing))
            if any(self.observed[r] is not None and len(self.observed[r]) != self.regions[r] for r in self.regions):
                raise ValueError('observed counts have the wrong number of bins')
            self.blinded = [r for r, role in self.roles.items() if role == 'SR' and self.observed[r] is None]
            if self.blinded and not d['computations'].get('allow_blinded_signal_regions', False):
                raise ValueError('observed mode with blinded signal regions ' + ', '.join(self.blinded)
                                 + ' needs computations.allow_blinded_signal_regions')
        else:
            self.blinded = [r for r, role in self.roles.items() if role == 'SR']
        computations = d['computations']
        allowed = {'discovery', 'cls_at_nominal', 'cls_limits', 'background_only_fit', 'allow_blinded_signal_regions'}
        if type(computations) is not dict or set(computations) - allowed or any(type(v) is not bool for v in computations.values()):
            raise ValueError('computations are booleans: ' + ', '.join(sorted(allowed)))
        if d['asimov_source'] == 'background-only-fit' and not any(role == 'CR' for role in self.roles.values()):
            raise ValueError('a background-only-fit Asimov source needs control regions')
        adequacy = d['mc_adequacy']
        if (type(adequacy) is not dict or set(adequacy) != {'max_relative_uncertainty', 'min_effective_entries'}
                or any(type(v) not in (int, float) or v <= 0 for v in adequacy.values())):
            raise ValueError('mc_adequacy needs positive max_relative_uncertainty and min_effective_entries')

    def _infer_bins(self, yields):
        if type(yields) is not dict:
            return
        for region, row in yields.items():
            if region in self.regions and self.regions[region] is None and type(row) is dict and type(row.get('values')) is list:
                self.regions[region] = len(row['values'])

    # ------------------------------------------------------------------ workspace
    def _mc_modifiers(self, sample, region, values, sumw2):
        mode = self.document['mc_statistics']
        if mode == 'none' or sumw2 is None:
            return []
        sigma = np.sqrt(sumw2)
        if mode == 'staterror':
            return [{'name': f'staterror_{region}', 'type': 'staterror', 'data': [float(x) for x in sigma]}]
        if np.any((sigma > 0) & (values <= 0)):
            raise ValueError(f'shapesys needs positive yields where {sample} in {region} has MC uncertainty')
        if np.all(sigma == 0):
            return []
        # A zero-uncertainty bin is kept fixed by a vanishingly small relative width.
        safe = np.where(sigma > 0, sigma, values * 1e-9 + 1e-12)
        return [{'name': f'shapesys_{sample}_{region}', 'type': 'shapesys', 'data': [float(x) for x in safe]}]

    def _sample(self, name, region, row, extra):
        mods = list(extra) + self._mc_modifiers(name, region, row['values'], row['sumw2'])
        if self.registry is not None:
            mods += self.registry.modifiers(name, region, row['values'])
        return {'name': name, 'data': [float(x) for x in row['values']], 'modifiers': mods}

    def workspace(self, point=None, roles=('SR', 'CR')):
        channels = []
        for region, bins in self.regions.items():
            if self.roles[region] not in roles:
                continue
            samples = []
            for bkg in self.backgrounds:
                if region in bkg['yields']:
                    extra = ([{'name': bkg['normfactor'], 'type': 'normfactor', 'data': None}]
                             if bkg['normfactor'] else [])
                    samples.append(self._sample(bkg['name'], region, bkg['yields'][region], extra))
            if point is not None and region in point['yields']:
                samples.append(self._sample('signal', region, point['yields'][region],
                                            [{'name': POI, 'type': 'normfactor', 'data': None}]))
            channels.append({'name': region, 'samples': samples})
        return {'channels': channels}

    def model(self, point=None, roles=('SR', 'CR')):
        pyhf, pyhf_exclude = _pyhf()
        spec = self.workspace(point, roles)
        poi = POI if point is not None and any(s['name'] == 'signal' for c in spec['channels'] for s in c['samples']) else None
        return pyhf.Model(spec, poi_name=poi, modifier_settings=pyhf_exclude.MODIFIER_SETTINGS,
                          validate=True), spec

    def pseudo_counts(self, region):
        total = np.zeros(self.regions[region])
        for bkg in self.backgrounds:
            if region in bkg['yields']:
                total = total + bkg['yields'][region]['values'] * self.injections.get(bkg['name'], 1.0)
        return total

    def counts(self, region):
        """Counts used as data in a region, or None when blinded."""
        if self.data_mode == 'mc-pseudo-data':
            return None if self.roles[region] == 'SR' else self.pseudo_counts(region)
        return self.observed[region]

    # ------------------------------------------------------------------ diagnostics
    def mc_adequacy(self):
        limits = self.document['mc_adequacy']
        flags = []
        rows = [(b['name'], b['yields']) for b in self.backgrounds] + [(f'signal:{p["id"]}', p['yields']) for p in self.points]
        for sample, yields in rows:
            for region, row in yields.items():
                if row['sumw2'] is None:
                    continue
                for i, (w, w2) in enumerate(zip(row['values'], row['sumw2'])):
                    reasons = []
                    if w <= 0:
                        reasons.append('nonpositive_yield' if w2 > 0 or w < 0 else 'empty_bin')
                    else:
                        if math.sqrt(w2) / w > limits['max_relative_uncertainty']:
                            reasons.append('relative_mc_uncertainty')
                        if w2 > 0 and w * w / w2 < limits['min_effective_entries']:
                            reasons.append('effective_entries')
                    if reasons:
                        flags.append({'sample': sample, 'region': region, 'bin': i, 'sumw': float(w), 'sumw2': float(w2),
                                      'flags': reasons})
        for region in self.regions:
            total = sum(b['yields'][region]['values'] for b in self.backgrounds if region in b['yields'])
            for i, v in enumerate(np.atleast_1d(total)):
                if v <= 0:
                    flags.append({'sample': 'total background', 'region': region, 'bin': i, 'sumw': float(v),
                                  'flags': ['nonpositive_total_background']})
        return flags

    @staticmethod
    def _mle(model, data, init, bounds, names=None):
        """iminuit MIGRAD (strategy 1, then 2 if invalid) on -ln L of a pyhf model."""
        import iminuit
        objective = lambda pars: float(-model.logpdf(np.asarray(pars), data)[0])
        minuit = iminuit.Minuit(objective, init, name=names)
        minuit.errordef = iminuit.Minuit.LIKELIHOOD
        minuit.limits = bounds
        minuit.strategy = 1
        minuit.migrad()
        if not minuit.fmin.is_valid:
            minuit.strategy = 2
            minuit.migrad()
        return minuit

    def background_only_fit(self, goodness_of_fit=None):
        """CR-only background fit with iminuit; predictions with uncertainties in every region.

        The saturated goodness of fit of the control-region fit is always reported;
        ``goodness_of_fit`` (toys, seed, max_seconds) adds per-toy auxiliary refits.
        """
        from . import gof
        pyhf, _ = _pyhf()
        cr_model, _ = self.model(None, roles=('CR',))
        data_main = np.concatenate([self.counts(c) for c in cr_model.config.channels])
        data = np.concatenate([data_main, np.asarray(cr_model.config.auxdata, float)])
        init = np.asarray(cr_model.config.suggested_init(), float)
        bounds = cr_model.config.suggested_bounds()
        names = _labels(cr_model)
        minuit = self._mle(cr_model, data, init, bounds, names)
        minuit.hesse()
        valid = bool(minuit.fmin.is_valid and minuit.accurate)
        values = np.array(minuit.values, float)
        covariance = np.array(minuit.covariance, float)
        errors = np.sqrt(np.clip(np.diag(covariance), 0, None))
        with np.errstate(divide='ignore', invalid='ignore'):
            correlation = covariance / np.outer(errors, errors)
        parameters = []
        for name, value, error, prior in zip(names, values, errors, _priors(cr_model)):
            row = {'name': name, 'value': float(value), 'error': float(error), 'prefit': prior}
            if prior['constrained']:
                row['pull'] = float((value - prior['nominal']) / prior['width']) if prior['width'] > 0 else None
            parameters.append(row)
        full, _ = self.model(None, roles=ROLES)
        mapped, mapped_cov = _transfer(cr_model, values, covariance, full)
        predictions = []
        main = _main_by_channel(full, mapped)
        jac = _jacobian(lambda p: np.asarray(full.expected_actualdata(p), float), mapped)
        cov_main = jac @ mapped_cov @ jac.T
        offset = 0
        for channel in full.config.channels:
            n = full.config.channel_nbins[channel]
            pred = main[channel]
            sigma = np.sqrt(np.clip(np.diag(cov_main)[offset:offset + n], 0, None))
            counts = self.counts(channel)
            row = {'region': channel, 'role': self.roles[channel], 'used_in_fit': self.roles[channel] == 'CR',
                   'prediction': pred.tolist(), 'prediction_uncertainty': sigma.tolist(),
                   'data': None if counts is None else counts.tolist()}
            if counts is not None:
                denominator = np.sqrt(pred + sigma ** 2)
                with np.errstate(divide='ignore', invalid='ignore'):
                    row['residuals'] = [float(x) for x in np.where(denominator > 0, (counts - pred) / denominator, np.nan)]
                row['residual_definition'] = '(data - prediction) / sqrt(prediction + prediction_uncertainty^2)'
            predictions.append(row)
            offset += n
        def refit(toy_data):
            m = self._mle(cr_model, toy_data, values, bounds, names)
            return np.array(m.values, float) if m.fmin.is_valid else None
        free = sum(1 for prior in _priors(cr_model) if not prior['constrained'])
        goodness = gof.evaluate(
            gof.pyhf_statistic(cr_model, values, data), ndf=len(data_main) - free,
            toy=gof.pyhf_toy(cr_model, values, refit), request=goodness_of_fit,
            statistic='saturated -2 ln lambda of the control-region fit',
            data_description=self.data_mode)
        return {'status': 'converged' if valid else 'not_converged', 'minimizer': 'iminuit MIGRAD + HESSE',
                'goodness_of_fit': goodness,
                'edm': float(minuit.fmin.edm), 'fit_channels': list(cr_model.config.channels),
                'twice_nll': float(2 * minuit.fval), 'parameters': parameters,
                'correlation': [[float(x) for x in row] for row in correlation], 'parameter_order': names,
                'region_predictions': predictions, 'mapped_parameters': mapped.tolist()}, mapped

    # ------------------------------------------------------------------ point statistics
    def _data_for(self, model, background_pars):
        """Main counts per channel: data where available, else the background prediction."""
        prediction = _main_by_channel(model, background_pars)
        main = []
        for channel in model.config.channels:
            counts = self.counts(channel)
            main.append(prediction[channel] if counts is None else counts)
        return np.concatenate(main + [np.asarray(model.config.auxdata, float)])

    def point(self, point, background_fit_pars=None, full_background=None):
        pyhf, pyhf_exclude = _pyhf()
        model, spec = self.model(point, roles=('SR', 'CR'))
        if model.config.poi_index is None:
            raise ValueError(f'signal point {point["id"]} has no yields in any fit region')
        pars = np.asarray(model.config.suggested_init(), float)
        if background_fit_pars is not None:
            pars = _copy_named(full_background, background_fit_pars, model, pars)
        bkg_pars = pars.copy(); bkg_pars[model.config.poi_index] = 0.0
        computations = self.document['computations']
        out = {'id': point['id'], 'coordinates': point['coordinates'], 'blinded_signal_regions': list(self.blinded)}
        expected_data = self._data_for(model, bkg_pars)
        observed_available = self.data_mode == 'observed' and not self.blinded
        init, bounds = model.config.suggested_init(), model.config.suggested_bounds()
        fixed = model.config.suggested_fixed()
        if computations.get('discovery'):
            signal_pars = pars.copy(); signal_pars[model.config.poi_index] = 1.0
            asimov = np.asarray(model.expected_data(signal_pars), float)
            q0 = float(pyhf.infer.test_statistics.q0(0.0, asimov, model, init, bounds, fixed))
            disc = {'expected_significance': math.sqrt(max(q0, 0.0)), 'expected_q0': q0,
                    'asimov': f'signal strength 1, {self.document["asimov_source"]} parameters'}
            if observed_available:
                q0_obs = float(pyhf.infer.test_statistics.q0(0.0, expected_data, model, init, bounds, fixed))
                disc.update(observed_q0=q0_obs, observed_significance=math.sqrt(max(q0_obs, 0.0)))
            out['discovery'] = disc
        if computations.get('cls_at_nominal'):
            cls_obs, band = pyhf.infer.hypotest(1.0, expected_data, model, init, bounds, fixed,
                                                test_stat='qtilde', return_expected_set=True)
            out['cls_at_nominal'] = {'observed': float(cls_obs) if observed_available else None,
                                     'expected': [float(x) for x in band],
                                     'expected_order': ['-2 sigma', '-1 sigma', 'median', '+1 sigma', '+2 sigma'],
                                     'level': self.document['cls_level'],
                                     'excluded_expected_median': bool(float(band[2]) < self.document['cls_level'])}
        if computations.get('cls_limits'):
            result = pyhf_exclude.compute(model, expected_data, level=self.document['cls_level'])
            out['cls_limits'] = {
                'parameter': 'signal strength', 'level': self.document['cls_level'],
                'observed': ({'value': float(result['obs_limit']), 'status': result['limit_status']['observed']}
                             if observed_available else None),
                'expected': {'values': [float(x) for x in result['exp_limits']],
                             'status': list(result['limit_status']['expected']),
                             'order': ['-2 sigma', '-1 sigma', 'median', '+1 sigma', '+2 sigma']},
                'flags': {k: bool(result.get(k)) for k in ('median_at_cap', 'band_degenerate', 'at_mu_floor')},
                'optimizer': result.get('optimizer')}
        out['workspace_channels'] = [c['name'] for c in spec['channels']]
        return out


def _labels(model):
    names = []
    for name in model.config.par_order:
        n = model.config.param_set(name).n_parameters
        names += [name] if n == 1 else [f'{name}[{i}]' for i in range(n)]
    return names


def _priors(model):
    out = []
    for name in model.config.par_order:
        ps = model.config.param_set(name)
        init = ps.suggested_init
        width = ps.width() if getattr(ps, 'constrained', False) else [None] * ps.n_parameters
        for i in range(ps.n_parameters):
            out.append({'constrained': bool(getattr(ps, 'constrained', False)), 'nominal': float(init[i]),
                        'width': None if width[i] is None else float(width[i])})
    return out


def _transfer(source, values, covariance, target):
    """Copy fitted parameters by name into the target model; others stay at their priors."""
    pars = np.asarray(target.config.suggested_init(), float)
    cov = np.zeros((len(pars), len(pars)))
    priors = _priors(target)
    for i, prior in enumerate(priors):
        if prior['constrained'] and prior['width']:
            cov[i, i] = prior['width'] ** 2
    index = []
    for name in source.config.par_order:
        if name in target.config.par_order:
            s, t = source.config.par_slice(name), target.config.par_slice(name)
            index += list(zip(range(s.start, s.stop), range(t.start, t.stop)))
    for si, ti in index:
        pars[ti] = values[si]
        for sj, tj in index:
            cov[ti, tj] = covariance[si, sj]
    return pars, cov


def _copy_named(source_model, values, target, pars):
    pars = pars.copy()
    for name in source_model.config.par_order:
        if name in target.config.par_order and name != POI:
            pars[target.config.par_slice(name)] = values[source_model.config.par_slice(name)]
    return pars


def _main_by_channel(model, pars):
    main = np.asarray(model.expected_actualdata(pars), float)
    out, offset = {}, 0
    for channel in model.config.channels:
        n = model.config.channel_nbins[channel]
        out[channel] = main[offset:offset + n]
        offset += n
    return out


def _jacobian(function, x, step=1e-6):
    x = np.asarray(x, float)
    base = function(x)
    jac = np.empty((len(base), len(x)))
    for i in range(len(x)):
        h = step * max(1.0, abs(x[i]))
        up, down = x.copy(), x.copy()
        up[i] += h; down[i] -= h
        jac[:, i] = (function(up) - function(down)) / (2 * h)
    return jac


def systematics_selfcheck(model):
    """Per-source self-check of the declared systematic variations on the background templates."""
    from ravel.validation import regression_triggers
    rows = []
    for source in model.registry.sources:
        nominal, up, down = [], [], []
        for bkg in model.backgrounds:
            for region, row in bkg['yields'].items():
                if not model.registry._applies(source, bkg['name'], region):
                    continue
                key = model.registry.parameter(source, bkg['name'], region)
                hi, lo = model.registry.variations(bkg['name'], region, row['values'])[key]
                nominal.extend(np.asarray(row['values'], float)); up.extend(hi); down.extend(lo)
        if nominal:
            rows.append({'name': source['name'], 'kind': source['kind'], 'nominal': nominal, 'up': up, 'down': down})
    shape = any(n > 1 for n in model.regions.values())
    return regression_triggers.systematics_selfcheck(rows, shape_measurement=shape)


def run(document, *, goodness_of_fit=None):
    model = SearchModel(document)
    result = {'mc_adequacy_flags': model.mc_adequacy(), 'data_mode': model.data_mode,
              'injections': model.injections, 'blinded_signal_regions': list(model.blinded),
              'regions': [{'name': r, 'role': model.roles[r], 'bins': model.regions[r]} for r in model.regions],
              'systematics': None if model.registry is None else model.registry.summary()}
    fit_pars = full = None
    if document['computations'].get('background_only_fit') or document['asimov_source'] == 'background-only-fit':
        fit, fit_pars = model.background_only_fit(goodness_of_fit)
        full, _ = model.model(None, roles=ROLES)
        result['background_only_fit'] = fit
        if document['asimov_source'] == 'background-only-fit' and fit['status'] != 'converged':
            raise ValueError('the background-only fit did not converge; the Asimov source is unavailable')
    if document['asimov_source'] == 'nominal':
        fit_pars = full = None
    result['points'] = [model.point(p, fit_pars, full) for p in model.points]
    if model.registry is not None:
        comparisons = {}
        for bkg in model.backgrounds:
            rows = model.registry.alternative_comparison(bkg['name'], {r: v['values'] for r, v in bkg['yields'].items()})
            if rows:
                comparisons[bkg['name']] = rows
        result['alternative_sample_comparison'] = comparisons
        result['systematics_selfcheck'] = systematics_selfcheck(model)
    return result
