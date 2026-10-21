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
MAX_DISCOVERY_TOYS = 10000
MC_STATISTICS = ('staterror', 'shapesys', 'none')
DATA_MODES = ('observed', 'mc-pseudo-data')
ASIMOV_SOURCES = ('nominal', 'background-only-fit')
POI = 'mu'


def toy_options(raw):
    from scipy.stats import norm
    if raw is None:
        return None
    if type(raw) is not dict or set(raw) - {'count', 'seed', 'required_significance'} or not {'count', 'seed'} <= set(raw):
        raise ValueError('discovery toys need count, seed and optional required_significance')
    n, seed = raw['count'], raw['seed']
    if type(n) is not int or not 1 <= n <= MAX_DISCOVERY_TOYS:
        raise ValueError(f'discovery toy count exceeds cap or is invalid (1..{MAX_DISCOVERY_TOYS})')
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError('discovery toy seed must be an integer in [0, 2^32)')
    z = raw.get('required_significance')
    if z is not None:
        if type(z) not in (int, float) or not math.isfinite(z) or z < 0:
            raise ValueError('required_significance must be finite and nonnegative')
        if norm.sf(z) < 1 / MAX_DISCOVERY_TOYS:
            raise ValueError('requested significance needs more toys than the cap allows')
        if norm.sf(z) < 1 / n:
            raise ValueError('requested significance needs more toys than the declared count')
    return dict(raw)


def toy_discovery(model, background_pars, thresholds, request):
    """Conditional null toys, drawing main and auxiliary counts and profiling q0.

    pyhf uses NumPy's legacy RNG; restore its state even after a failed fit.
    Clopper-Pearson intervals describe finite-toy tail uncertainty. Zero tails
    supply a bound rather than a finite discovery significance.
    """
    from scipy.stats import beta, norm
    pyhf, _ = _pyhf()
    opts = toy_options(request)
    n = opts['count']
    state = np.random.get_state()
    try:
        np.random.seed(opts['seed'])
        samples = np.asarray(model.make_pdf(background_pars).sample((n,)), float)
    finally:
        np.random.set_state(state)
    init, bounds, fixed = model.config.suggested_init(), model.config.suggested_bounds(), model.config.suggested_fixed()
    q = []
    for data in samples:
        value = float(pyhf.infer.test_statistics.q0(0.0, data, model, init, bounds, fixed))
        if not math.isfinite(value):
            raise ValueError('discovery toy fit produced a nonfinite statistic')
        q.append(value)
    out = {}
    alpha = 1 - 0.682689492137
    for name, threshold in thresholds.items():
        k = int(np.count_nonzero(np.asarray(q) >= threshold))
        p = k / n
        lo = 0.0 if k == 0 else float(beta.ppf(alpha / 2, k, n - k + 1))
        hi = 1.0 if k == n else float(beta.ppf(1 - alpha / 2, k + 1, n - k))
        out[name] = {'method': 'conditional-null-toys', 'count': n, 'seed': opts['seed'],
                     'minimum_resolved_p_value': 1 / n,
                     'q0': threshold, 'tail_count': k, 'p_value': p,
                     'p_value_mc_uncertainty': max(p - lo, hi - p),
                     'p_value_interval': [lo, hi], 'interval_confidence': 1 - alpha,
                     'significance': None if k == 0 else max(0.0, float(norm.isf(p))),
                     'significance_interval': [max(0.0, float(norm.isf(hi))),
                                               None if lo == 0 else max(0.0, float(norm.isf(lo)))],
                     'status': 'tail_unresolved' if k == 0 else 'resolved',
                     'nuisance_treatment': 'plug-in null parameters; main and auxiliary toys; q0 refit'}
    return out


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
        if type(d) is not dict or not required <= set(d) or set(d) - required - {'toys', 'reference_contour', 'model_construction', 'background_covariance', 'cls_calculator', 'cls_toys', 'statistics_choices'}:
            raise ValueError('search document needs exactly: ' + ', '.join(sorted(required)))
        self.background_covariance = d.get('background_covariance')
        if 'background_covariance' in d:
            if not isinstance(self.background_covariance, dict):
                raise ValueError('background_covariance must be a covariance document')
            if any(r.get('role') != 'SR' for r in d['regions']):
                raise ValueError('background_covariance requires SR regions only; CR and VR regions are not represented')
            if d['systematics'] is not None:
                raise ValueError('background_covariance requires systematics to be null')
            if d['mc_statistics'] != 'none':
                raise ValueError('background_covariance requires mc_statistics none: signal MC statistics are not represented')
            if d['computations'].get('discovery'):
                raise ValueError('discovery is not supported with a background covariance')
            if d['asimov_source'] != 'nominal':
                raise ValueError('background_covariance requires asimov_source nominal')
            if d['computations'].get('background_only_fit'):
                raise ValueError('background_only_fit is not supported with a background covariance')
            if any(b.get('normfactor') is not None for b in d['backgrounds']):
                raise ValueError('background normfactors are not represented with a background covariance')
            if 'model_construction' in d:
                raise ValueError('model_construction builds a HistFactory model; a background covariance is a simplified likelihood')
        self.cls_calculator = d.get('cls_calculator', 'asymptotic')
        if self.cls_calculator not in ('asymptotic', 'auto', 'toybased'):
            raise ValueError('cls_calculator must be asymptotic, auto or toybased')
        self.cls_toys = None
        if self.cls_calculator == 'asymptotic':
            if 'cls_toys' in d:
                raise ValueError('cls_toys requires cls_calculator auto or toybased')
        else:
            from .toy_cls import _validate_options
            opts = d.get('cls_toys')
            if (type(opts) is not dict or not {'count', 'seed'} <= set(opts)
                    or set(opts) - {'count', 'seed', 'max_fits', 'max_seconds'}):
                raise ValueError('cls_toys needs count, seed and optional max_fits, max_seconds')
            _validate_options(opts['count'], opts['seed'], opts.get('max_fits'), opts.get('max_seconds'))
            self.cls_toys = opts
        if self.cls_calculator != 'asymptotic' and 'background_covariance' in d:
            raise ValueError('cls_calculator toys apply to pyhf models; a background covariance uses the spey asymptotic engine')
        self.toys = toy_options(d.get('toys'))
        from .model_construction import validate_construction
        self.construction = validate_construction(d.get('model_construction'))
        self.construction_folder = None
        self.construction_records = []
        if self.toys and not d['computations'].get('discovery'):
            raise ValueError('discovery toys require computations.discovery')
        self.abcd = []
        from ravel.physics.statistical_model import abcd_estimate
        sidebands = set()
        for region in d['regions']:
            if region.get('role') != 'abcd':
                continue
            estimate = abcd_estimate(region.get('abcd'))
            if region.get('bins', 1) != 1:
                raise ValueError('abcd estimates currently require a single-bin target')
            identities = {row['observation_id'] for row in estimate['controls'].values()}
            fitted = {r.get('observation_id', r['name']) for r in d['regions'] if r.get('role') != 'VR'}
            if identities & (sidebands | fitted):
                raise ValueError('abcd sidebands must be disjoint from fitted regions and other sidebands')
            sidebands |= identities
            candidates = [b for b in d['backgrounds'] if b['name'] == estimate['background']]
            if len(candidates) != 1:
                raise ValueError('abcd background must name exactly one declared sample')
            bkg = candidates[0]
            if region['name'] in bkg['yields']:
                raise ValueError('abcd target yield must be estimated, not supplied twice')
            bkg['yields'][region['name']] = {'values': [estimate['prediction']], 'sumw2': [0.0]}
            estimate['region'] = region['name']
            self.abcd.append(estimate)
        self.document = d
        self.background_fit = None
        if d['mc_statistics'] not in MC_STATISTICS:
            raise ValueError('mc_statistics must be staterror, shapesys or none')
        if d['asimov_source'] not in ASIMOV_SOURCES:
            raise ValueError('asimov_source must be nominal or background-only-fit')
        level = d['cls_level']
        if type(level) not in (int, float) or not 0 < level < 1:
            raise ValueError('cls_level must be between zero and one')
        self.regions, self.roles, self.observed = {}, {}, {}
        for r in d['regions']:
            if (type(r) is not dict or set(r) - {'name', 'role', 'observed', 'bins', 'description', 'abcd', 'observation_id'}
                    or r.get('role') not in (*ROLES, 'abcd')):
                raise ValueError('regions need name, role (SR, CR or VR) and observed (null when blinded)')
            if r['role'] != 'abcd' and 'abcd' in r:
                raise ValueError('abcd estimate requires region role abcd')
            name = r['name']
            if type(name) is not str or not name.strip() or name in self.regions or name == POI:
                raise ValueError('regions need unique names')
            observed = None if r.get('observed') is None else _array(r['observed'], f'observed counts in {name}', nonnegative=True)
            bins = r.get('bins', None if observed is None else len(observed))
            self.roles[name], self.observed[name] = ('SR' if r['role'] == 'abcd' else r['role']), observed
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
        if self.background_covariance is not None:
            self._prepare_covariance()
            # Validate every signal and the covariance before any backend execution.
            for point in self.points or [None]:
                self._simplified_engine(point)

    def _prepare_covariance(self):
        from .simplified import _labels, _vector
        d = deepcopy(self.background_covariance)
        allowed = {'regions', 'covariance', 'correlation', 'errors', 'third_moments', 'source', 'blocks'}
        if set(d) - allowed:
            raise ValueError('unknown background_covariance fields')
        regions = _labels(d.get('regions'), 'background_covariance regions')
        if set(regions) != set(self.regions):
            raise ValueError('covariance region set must equal the SR region set')
        labels = {r: [r] if self.regions[r] == 1 else [f'{r}[{i}]' for i in range(self.regions[r])]
                  for r in regions}
        self._covariance_regions = regions
        self._covariance_labels = labels
        flat = [label for r in regions for label in labels[r]]
        self._covariance_errors = [0.] * len(flat)
        if 'correlation' in d:
            if 'errors' not in d:
                raise ValueError('background_covariance correlation requires explicit per-bin errors')
            errors = _vector(d.pop('errors'), 'background_covariance errors')
            if len(errors) != len(flat):
                raise ValueError('background_covariance errors must match total bin count')
            self._covariance_errors = errors.tolist()
        elif 'errors' in d:
            raise ValueError('background_covariance errors apply only to correlation')
        blocks = d.get('blocks', [regions])
        if not isinstance(blocks, list) or not blocks:
            raise ValueError('blocks must partition regions')
        for block in blocks:
            _labels(block, 'block regions')
        names = [r for block in blocks for r in block]
        if len(set(names)) != len(names) or set(names) != set(regions):
            raise ValueError('blocks must partition regions exactly')
        d['regions'] = flat
        d['blocks'] = [[label for r in block for label in labels[r]] for block in blocks]
        self._covariance_document = {'schema_version': 1, 'kind': 'background-covariance', **d}

    def _simplified_engine(self, point):
        from .simplified import from_document
        rows, offset = [], 0
        observed = self.data_mode == 'observed' and not self.blinded
        for region in self._covariance_regions:
            background = sum(b['yields'][region]['values'] for b in self.backgrounds if region in b['yields'])
            signal = (point['yields'][region]['values'] if point is not None and region in point['yields']
                      else np.zeros(self.regions[region]))
            for i, label in enumerate(self._covariance_labels[region]):
                rows.append({'name': label, 'n': float(self.observed[region][i]) if observed else None,
                             'b': float(background[i]), 's': float(signal[i]),
                             'db': self._covariance_errors[offset]})
                offset += 1
        return from_document(self._covariance_document, rows)

    def _simplified_point(self, point):
        from .simplified import EXPECTED_ORDER
        engine = self._simplified_engine(point)
        computations = self.document['computations']
        observed = self.data_mode == 'observed' and not self.blinded
        out = {'id': point['id'], 'coordinates': point['coordinates'],
               'blinded_signal_regions': list(self.blinded),
               'signal_yields': {r: row['values'].tolist() for r, row in point['yields'].items()},
               'workspace_channels': list(self._covariance_regions)}
        if computations.get('cls_at_nominal'):
            band = engine.cls(1.0, 'apriori')
            out['cls_at_nominal'] = {'engine': 'spey-simplified-likelihood',
                'observed': engine.cls(1.0, 'observed')[0] if observed else None,
                'observed_on_pseudo_data': None, 'expected': band, 'expected_order': EXPECTED_ORDER,
                'level': self.document['cls_level'],
                'excluded_expected_median': band[2] < self.document['cls_level']}
        if computations.get('cls_limits'):
            result = engine.limits(level=self.document['cls_level'])
            out['cls_limits'] = {'engine': 'spey-simplified-likelihood',
                'parameter': 'signal strength', 'level': self.document['cls_level'],
                'status': _limit_status(result, observed),
                'observed': ({'value': result['obs_limit'], 'status': result['limit_status']['observed']}
                             if observed else None),
                'expected': {'values': result['exp_limits'], 'status': result['limit_status']['expected'],
                             'order': EXPECTED_ORDER},
                'flags': {k: result[k] for k in ('at_poi_cap', 'median_at_cap', 'band_degenerate', 'at_mu_floor')},
                'limits': result['limits'], 'numerical_evidence': result['numerical_evidence'],
                'inference': result['inference'], 'optimizer': None}
            from . import situations, uncertainty
            from ravel.limits import read_limits
            limits = read_limits(result)
            facts = self.simplified_statistics_facts(point)
            assessment = situations.assess(facts)
            detected = {r['situation'] for r in assessment['situations']}
            # Toy CLs does not apply to a simplified likelihood; the catalogue records that and qualifies.
            choices = {k: v for k, v in self.document.get('statistics_choices', {}).items() if k in detected}
            out['statistics'] = situations.record(
                facts, {'limits': {'observed': limits.observed.status if observed else 'missing',
                                   'median': limits.expected[2].status}, 'mc_statistics': 'none'},
                decision=situations.decide(assessment, choices))
            out['cls_limits']['uncertainty'] = uncertainty.for_limits(
                _reported_limits(result, observed), sources={'systematic': list(self._covariance_regions)},
                signal_types=[], stat_only={'status': 'not-evaluated',
                                            'reason': 'the covariance engine has no fixed-nuisance reference'},
                not_included=self._omissions())
        return out

    def simplified_statistics_facts(self, point):
        """Facts for the existing covariance backend, which has no pyhf model."""
        from . import situations
        bins = []
        for region in self.regions:
            backgrounds = [b['yields'][region] for b in self.backgrounds if region in b['yields']]
            for i in range(self.regions[region]):
                background = float(sum(b['values'][i] for b in backgrounds))
                bins.append({'channel': region, 'bin': i, 'role': self.roles[region],
                             'observed': float(self.counts(region)[i]) if self.counts(region) is not None else background,
                             'background': background,
                             'signal': float(point['yields'][region]['values'][i]) if region in point['yields'] else 0.0,
                             'mc': {'sumw': background, 'sumw2': float(sum(b['sumw2'][i] for b in backgrounds))}
                             if all(b['sumw2'] is not None for b in backgrounds) else 'absent'})
        return situations.make_facts(
            deliverables=['exclusion'] if self.document['computations'].get('cls_limits') else [],
            model_origin='simplified', bins=bins, mc_statistics='none',
            likelihood={'covariance': True, 'covariance_source': self.background_covariance.get('source')})

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
        for estimate in self.abcd:
            if estimate['background'] == name and estimate['region'] == region and estimate['relative_variance'] > 0:
                width = math.sqrt(math.log1p(estimate['relative_variance']))
                mods.append({'name': f'abcd_{region}', 'type': 'normsys',
                             'data': {'hi': math.exp(width), 'lo': math.exp(-width)}})
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
        if self.construction is not None:
            # Both builders run; the parity record is the construction's validator and a
            # mismatch refuses the model (model_construction.construct raises).
            from .model_construction import construct
            if self.construction_folder is None:
                raise ValueError('model_construction needs an output folder for the template histograms')
            channels, record = construct(self, point, roles, self.construction_folder, self.construction['builder'])
            self.construction_records.append(record)
            spec = {'channels': channels}
        else:
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
    def _mle(model, data, init, bounds, names=None, fixed=None):
        """iminuit MIGRAD (strategy 1, then 2 if invalid) on -ln L of a pyhf model."""
        import iminuit
        objective = lambda pars: float(-model.logpdf(np.asarray(pars), data)[0])
        minuit = iminuit.Minuit(objective, init, name=names)
        minuit.errordef = iminuit.Minuit.LIKELIHOOD
        minuit.limits = bounds
        for index, value in (fixed or {}).items():
            minuit.values[index] = value
            minuit.fixed[index] = True
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
            prefit = np.asarray(full.config.suggested_init(), float)
            pre_samples = np.asarray(full.main_model.expected_data(prefit, return_by_sample=True), float)
            post_samples = np.asarray(full.main_model.expected_data(mapped, return_by_sample=True), float)
            row = {'region': channel, 'role': self.roles[channel], 'used_in_fit': self.roles[channel] == 'CR',
                   'prediction': pred.tolist(), 'prediction_uncertainty': sigma.tolist(),
                   'total_prediction_uncertainty': float(np.sqrt(max(0.0, np.sum(cov_main[offset:offset+n, offset:offset+n])))),
                   'processes': [{'name': name, 'prefit': pre_samples[i, offset:offset+n].tolist(),
                                  'postfit': post_samples[i, offset:offset+n].tolist()}
                                 for i, name in enumerate(full.config.samples)],
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
        self.background_fit = {'status': 'converged' if valid else 'not_converged', 'minimizer': 'iminuit MIGRAD + HESSE',
                'goodness_of_fit': goodness,
                'edm': float(minuit.fmin.edm), 'fit_channels': list(cr_model.config.channels),
                'twice_nll': float(2 * minuit.fval), 'parameters': parameters,
                'correlation': [[float(x) for x in row] for row in correlation], 'parameter_order': names,
                'region_predictions': predictions, 'mapped_parameters': mapped.tolist()}
        return self.background_fit, mapped

    # ------------------------------------------------------------------ point statistics
    def statistics_facts(self, model, data):
        """Model counts plus supplied MC moments, registry correlations and region roles.

        VR rows carry their identity only: they are validation evidence, never
        main likelihood bins or inputs to the small-count calculator policy.
        """
        from . import situations
        deliverables = [name for key, name in (('cls_limits', 'exclusion'), ('discovery', 'discovery'))
                        if self.document['computations'].get(key)]
        facts = situations.facts_from_model(model, data, origin='constructed', deliverables=deliverables)
        for row in facts['bins']:
            region, index = row['channel'], row['bin']
            row['role'] = self.roles[region]
            backgrounds = [b['yields'][region] for b in self.backgrounds if region in b['yields']]
            row['mc'] = ({'sumw': float(sum(b['values'][index] for b in backgrounds)),
                          'sumw2': float(sum(b['sumw2'][index] for b in backgrounds))}
                         if all(b['sumw2'] is not None for b in backgrounds) else 'absent')
        facts['bins'] += [{'channel': r, 'bin': i, 'role': 'VR'} for r in self.regions
                          if self.roles[r] == 'VR' for i in range(self.regions[r])]
        facts['mc_statistics'] = self.document['mc_statistics']
        if self.registry is not None:
            facts['systematics'] = [
                {'name': source['name'], 'correlation': source['correlation'],
                 'regions': [r for r in self.regions if
                             (source['regions'] == 'all' or r in source['regions']) and
                             any((source['samples'] == 'all' or name in source['samples']) and r in yields
                                 for name, yields in [(b['name'], b['yields']) for b in self.backgrounds]
                                 + [('signal', p['yields']) for p in self.points])]}
                for source in self.registry.sources]
        return facts

    def _omissions(self):
        rows = deepcopy(self.registry.absent) if self.registry is not None else []
        if self.blinded:
            rows.append({'component': 'blinded signal regions',
                         'reason': 'No observed result in ' + ', '.join(self.blinded)})
        if self.data_mode == 'mc-pseudo-data':
            rows.append({'component': 'experimental observations',
                         'reason': 'MC pseudo-data use supplied background yields and declared injections'})
        return rows

    def _statistics(self, model, data, result, observed, discovery=None):
        """Record the executed calculator and evaluate evidence owed by the decision.

        Toys run only within a declared budget: without ``cls_toys`` (the calculator then defaults
        to asymptotic) or discovery ``toys``, a small-count situation records the toy method as
        refused by that budget, so its asymptotic result is qualified rather than silently trusted.
        """
        from . import model_checks, situations
        from ravel.limits import read_limits
        facts = self.statistics_facts(model, data)
        calculator = (result or {}).get('calculator') or {}
        toys = calculator.get('toys')
        availability, evidence = {}, {'mc_statistics': situations.facts_from_model(
            model, data, origin='constructed')['mc_statistics']}
        refusals = []
        if discovery is not None:
            evidence['discovery'] = {k: discovery[k] for k in ('expected_q0', 'observed_q0') if k in discovery}
            if 'toys' in discovery:
                evidence['discovery_toys'] = deepcopy(discovery['toys'])
        if result is not None:
            limits = read_limits(result)
            evidence['limits'] = {'observed': limits.observed.status if observed else 'missing',
                                  'median': limits.expected[2].status}
        if isinstance(toys, dict):
            if toys.get('status') == 'run':
                intervals = result.get('limit_mc_interval') or {}
                evidence['toys'] = {'status': 'run', 'observed': result['obs_limit'] if observed else None,
                                    'median': result['exp_limits'][2],
                                    'observed_mc_interval': intervals.get('observed') if observed else None,
                                    'median_mc_interval': (intervals.get('expected') or [None] * 5)[2]}
            else:
                evidence['toys'] = {'status': toys.get('status'), 'reason': toys.get('reason')}
                if toys.get('reason') == 'budget':
                    availability['toy-cls'] = {'available': False, 'reason': 'budget: declared toy resource cap'}
                    refusals.append({'method': 'toy-cls', **deepcopy(toys)})
        detected = {r['situation'] for r in situations.assess(facts)['situations']}
        choices = {k: v for k, v in self.document.get('statistics_choices', {}).items() if k in detected}
        if 'low-counts' in detected and calculator.get('requested') == 'asymptotic':
            if 'cls_calculator' in self.document:
                choices.setdefault('low-counts', {'method': 'asymptotic-cls',
                                                 'justification': 'the document requests cls_calculator asymptotic'})
            else:
                availability['toy-cls'] = {'available': False,
                                           'reason': 'budget: the document declares no CLs toy budget'}
                refusals.append({'method': 'toy-cls', 'status': 'not_run', 'reason': 'budget',
                                 'bound': 'undeclared'})
        if 'low-count-significance' in detected and 'discovery_toys' not in evidence:
            availability['toy-significance'] = {'available': False,
                                                'reason': 'budget: the document declares no discovery toys'}
            refusals.append({'method': 'toy-significance', 'status': 'not_run', 'reason': 'budget',
                             'bound': 'undeclared'})
        if refusals:
            evidence['budget_refusals'] = refusals
        assessment = situations.assess(facts, availability=availability)
        decision = situations.decide(assessment, choices)
        chosen = {r['situation']: r['method'] for r in decision['choices']}
        if self.background_fit is not None:
            evidence['pulls'] = {p['name']: p['pull'] for p in self.background_fit['parameters']
                                 if p.get('pull') is not None}
            evidence['validation_residuals'] = {
                r['region']: max(abs(x) for x in r['residuals'])
                for r in self.background_fit['region_predictions']
                if r['role'] == 'VR' and r.get('residuals')}
        elif chosen.get('systematic-nuisances') == 'profiled-nuisances':
            try:
                start = np.asarray(model.config.suggested_init(), float)
                start[model.config.poi_index] = 0.0
                fixed = {i: float(start[i]) for i, frozen in enumerate(model.config.suggested_fixed()) if frozen}
                fixed[model.config.poi_index] = 0.0
                fit = self._mle(model, data, start, model.config.suggested_bounds(),
                                fixed=fixed)
                fit.hesse()
                evidence['pulls'] = {name: float((fit.values[i] - prior['nominal']) / prior['width'])
                                     for i, (name, prior) in enumerate(zip(_labels(model), _priors(model)))
                                     if prior['constrained'] and prior['width'] and
                                     getattr(model.config.param_set(name.split('[')[0]), 'pdf_type', 'normal') == 'normal'}
                evidence['pull_fit_valid'] = bool(fit.fmin.is_valid)
            except Exception as exc:
                evidence['pulls_error'] = f'{type(exc).__name__}: {exc}'[:500]
        if chosen.get('model-validation') == 'signal-injection':
            median = result['exp_limits'][2] if result is not None else None
            strengths = sorted({1.0, *([float(median)] if median and math.isfinite(median) else [])})
            try:
                evidence['injection'] = model_checks.signal_injection(model, injected=strengths)
            except Exception as exc:
                evidence['injection_error'] = f'{type(exc).__name__}: {exc}'[:500]
        return situations.record(facts, evidence, availability=availability, decision=decision)

    def _data_for(self, model, background_pars):
        """Main counts per channel: data where available, else the background prediction."""
        prediction = _main_by_channel(model, background_pars)
        main = []
        for channel in model.config.channels:
            counts = self.counts(channel)
            main.append(prediction[channel] if counts is None else counts)
        return np.concatenate(main + [np.asarray(model.config.auxdata, float)])

    def point(self, point, background_fit_pars=None, full_background=None):
        if self.background_covariance is not None:
            return self._simplified_point(point)
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
        out['signal_yields'] = {r: row['values'].tolist() for r, row in point['yields'].items()}
        expected_data = self._data_for(model, bkg_pars)
        observed_available = self.data_mode == 'observed' and not self.blinded
        init, bounds = model.config.suggested_init(), model.config.suggested_bounds()
        fixed = model.config.suggested_fixed()
        result = None
        if computations.get('discovery'):
            signal_pars = pars.copy(); signal_pars[model.config.poi_index] = 1.0
            asimov = np.asarray(model.expected_data(signal_pars), float)
            q0 = float(pyhf.infer.test_statistics.q0(0.0, asimov, model, init, bounds, fixed))
            disc = {'expected_significance': math.sqrt(max(q0, 0.0)), 'expected_q0': q0,
                    'asimov': f'signal strength 1, {self.document["asimov_source"]} parameters'}
            if observed_available:
                q0_obs = float(pyhf.infer.test_statistics.q0(0.0, expected_data, model, init, bounds, fixed))
                disc.update(observed_q0=q0_obs, observed_significance=math.sqrt(max(q0_obs, 0.0)))
            if self.toys:
                thresholds = {'expected': q0}
                if observed_available:
                    thresholds['observed'] = disc['observed_q0']
                disc['toys'] = toy_discovery(model, bkg_pars, thresholds, self.toys)
            out['discovery'] = disc
        if computations.get('cls_at_nominal'):
            cls_obs, band = pyhf.infer.hypotest(1.0, expected_data, model, init, bounds, fixed,
                                                test_stat='qtilde', return_expected_set=True)
            pseudo_cls = None
            if self.data_mode == 'mc-pseudo-data':
                pseudo = np.concatenate([self.pseudo_counts(c) for c in model.config.channels]
                                        + [np.asarray(model.config.auxdata, float)])
                pseudo_cls = float(pyhf.infer.hypotest(1.0, pseudo, model, init, bounds, fixed, test_stat='qtilde'))
            out['cls_at_nominal'] = {'observed': float(cls_obs) if observed_available else None,
                                     'observed_on_pseudo_data': pseudo_cls,
                                     'expected': [float(x) for x in band],
                                     'expected_order': ['-2 sigma', '-1 sigma', 'median', '+1 sigma', '+2 sigma'],
                                     'level': self.document['cls_level'],
                                     'excluded_expected_median': bool(float(band[2]) < self.document['cls_level'])}
        if computations.get('cls_limits'):
            from . import toy_cls
            result = pyhf_exclude.compute(model, expected_data, level=self.document['cls_level'])
            opts = self.cls_toys or {}
            toy_cls.apply(model, expected_data, result, requested=self.cls_calculator,
                          ntoys=opts.get('count', 2000), seed=opts.get('seed', 1),
                          max_fits=opts.get('max_fits'), max_seconds=opts.get('max_seconds'))
            out['cls_limits'] = {
                'parameter': 'signal strength', 'level': self.document['cls_level'],
                'status': _limit_status(result, observed_available),
                'observed': ({'value': float(result['obs_limit']), 'status': result['limit_status']['observed']}
                             if observed_available else None),
                'expected': {'values': [float(x) for x in result['exp_limits']],
                             'status': list(result['limit_status']['expected']),
                             'order': ['-2 sigma', '-1 sigma', 'median', '+1 sigma', '+2 sigma']},
                'flags': {k: bool(result.get(k)) for k in ('median_at_cap', 'band_degenerate', 'at_mu_floor')},
                'optimizer': result.get('optimizer'), 'calculator': result['calculator']}
            if result['calculator']['applied'] == 'toybased':
                reference = result['asymptotic_reference']
                out['cls_limits']['asymptotic_reference'] = {
                    'observed': ({'value': reference['obs_limit'], 'status': reference['limit_status']['observed']}
                                 if observed_available else None),
                    'expected': {'values': reference['exp_limits'], 'status': reference['limit_status']['expected']}}
                intervals = result['limit_mc_interval']
                out['cls_limits']['mc_interval'] = {
                    'observed': intervals['observed'] if observed_available else None,
                    'expected': intervals['expected']}
            from . import uncertainty
            parameters = model.config.npars
            stat_only = {'status': 'not-evaluated',
                         'reason': f'the model has {parameters} parameters; automatic breakdown is limited to '
                                   f'{uncertainty.BREAKDOWN_PARAMETER_LIMIT}'}
            if parameters <= uncertainty.BREAKDOWN_PARAMETER_LIMIT:
                try:
                    stat_only = uncertainty.stat_only_expected(
                        model, expected_data, lambda m, d: pyhf_exclude.compute(m, d, level=self.document['cls_level']))
                except Exception as exc:
                    stat_only = {'status': 'not-evaluated',
                                 'reason': f'the statistical-only reference failed: {type(exc).__name__}: {exc}'[:400]}
            # Suppress the internally computed observed root when data are blinded.
            reported = _reported_limits(result, observed_available)
            out['cls_limits']['uncertainty'] = uncertainty.for_limits(
                reported, sources=uncertainty.model_sources(model), signal_types=uncertainty.signal_modifiers(model),
                stat_only=stat_only, not_included=self._omissions())
        if computations.get('cls_limits') or computations.get('discovery'):
            out['statistics'] = self._statistics(model, expected_data, result, observed_available,
                                                 out.get('discovery'))
        out['workspace_channels'] = [c['name'] for c in spec['channels']]
        return out


def _limit_status(result, observed):
    """Validity of the reported headline roots; censored roots stay unresolved."""
    status = result['limit_status']
    return ('resolved' if status['expected'][2] == 'resolved' and
            (not observed or status['observed'] == 'resolved') else 'unresolved')


def _reported_limits(result, observed):
    """Remove the internal observed reference when only expected limits are reported."""
    from dataclasses import replace
    from ravel.limits import LimitCurve, attach_limits, read_limits
    reported = deepcopy(result)
    if not observed:
        limits = read_limits(result)
        reported['obs_limit'] = None
        if 'at_poi_cap' in reported:
            reported['at_poi_cap'] = False
        if 'at_mu_floor' in reported:
            reported['at_mu_floor'] = bool(reported['at_mu_floor'] and any(
                c.status in ('below_scan', 'unverified') for c in limits.expected))
        if all(c.usable(allow_legacy=True) or c.status == 'missing' for c in limits.expected):
            reported.pop('quality', None)
        attach_limits(reported, result=replace(limits, observed=LimitCurve(None, 'missing')))
    return reported


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


def run(document, *, goodness_of_fit=None, construction_folder=None):
    model = SearchModel(document)
    model.construction_folder = construction_folder
    result = {'mc_adequacy_flags': model.mc_adequacy(), 'data_mode': model.data_mode,
              'injections': model.injections, 'blinded_signal_regions': list(model.blinded),
              'regions': [{'name': r, 'role': model.roles[r], 'bins': model.regions[r]} for r in model.regions],
              'systematics': None if model.registry is None else model.registry.summary(), 'abcd': model.abcd}
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
    if model.construction is not None:
        result['model_construction'] = {'builder': model.construction['builder'],
                                        'records': model.construction_records}
    return result
