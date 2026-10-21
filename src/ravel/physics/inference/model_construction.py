"""Build the search-statistics HistFactory model through cabinetry and check it against the native builder.

cabinetry (scikit-hep) turns a declarative configuration plus template histograms into a
pyhf workspace. ``SearchModel.workspace`` builds the same model directly from the declared
yields, MC moments and systematics registry. A constructed model is built by BOTH builders;
the parity record is the construction's validator:

- channels, samples, nominal yields, MC-statistics widths, normalisation factors and the set
  of constrained parameters must agree exactly;
- every systematic's templates must agree at the plus and minus one-sigma points of its
  parameter (relative tolerance 1e-9);
- the background-only expected data must agree.

A failure of any of those is a ``mismatch`` and the construction is refused. When the two
specs are byte-identical after canonicalisation the status is ``identical``. When they agree
at one sigma but represent a shape systematic differently (cabinetry's NormPlusShape splits a
variation into a normalisation factor and a yield-normalised shape, the native builder keeps
one absolute histosys template) the status is ``equivalent-at-one-sigma`` and the CLs at unit
signal strength of both representations is recorded together with its relative difference.
Interpolation between the one-sigma points is a modelling convention, not a defect; the record
makes it visible instead of hiding it.

MC statistics: cabinetry represents them as ``staterror``; a document that asks for
``shapesys`` cannot be built through cabinetry and is refused with that reason.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

CABINETRY_VERSION = '0.6.0'
BUILDERS = ('native', 'cabinetry')
TEMPLATE_RTOL = 1e-9
POI = 'mu'


def _cabinetry():
    import cabinetry
    if cabinetry.__version__ != CABINETRY_VERSION:
        raise RuntimeError(f'model construction is verified with cabinetry=={CABINETRY_VERSION}; '
                           f'found {cabinetry.__version__}; other versions require a compatibility review')
    return cabinetry


def validate_construction(raw):
    """The optional ``model_construction`` block of a search document."""
    if raw is None:
        return None
    if type(raw) is not dict or set(raw) != {'builder'} or raw['builder'] not in BUILDERS:
        raise ValueError('model_construction needs exactly builder: native or cabinetry')
    return dict(raw)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _canonical_channels(channels):
    """Channel list with modifiers sorted by (name, type): modifier order is not part of the model."""
    ordered = []
    for channel in channels:
        samples = []
        for sample in channel['samples']:
            modifiers = sorted(sample['modifiers'], key=lambda m: (m['name'], m['type']))
            samples.append({**sample, 'modifiers': modifiers})
        ordered.append({**channel, 'samples': samples})
    return _canonical(ordered)


def _edges(n):
    return [float(i) for i in range(n + 1)]


class _Writer:
    """Writes cabinetry template histograms under one folder and records what it wrote."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.written = []

    def save(self, region, sample, systematic, template, values, stdev):
        from cabinetry import histo
        values = np.asarray(values, float)
        stdev = np.zeros_like(values) if stdev is None else np.asarray(stdev, float)
        name = histo.name({'Name': region}, {'Name': sample}, systematic, template=template)
        path = self.folder / name
        histo.Histogram.from_arrays(_edges(len(values)), values, stdev).save(path)
        self.written.append(name + '.npz')
        return name


def cabinetry_config(search_model, point, roles, folder):
    """The cabinetry configuration (and written histograms) for one search model and signal point."""
    if search_model.document['mc_statistics'] == 'shapesys':
        raise ValueError('cabinetry represents MC statistics as staterror; declare mc_statistics staterror or none '
                         'for a cabinetry construction')
    writer = _Writer(folder)
    regions = [r for r in search_model.regions if search_model.roles[r] in roles]
    if not regions:
        raise ValueError('no regions with the requested roles')
    staterror = search_model.document['mc_statistics'] == 'staterror'
    samples = [{'Name': 'Data', 'Data': True}]
    normfactors = {}
    systematics = []

    def add_normfactor(name, sample):
        normfactors.setdefault(name, {'Name': name, 'Samples': []})
        normfactors[name]['Samples'].append(sample)

    for region in regions:
        counts = search_model.counts(region)
        data = counts if counts is not None else search_model.pseudo_counts(region)
        writer.save(region, 'Data', {}, None, data, np.sqrt(np.asarray(data, float)))

    def add_sample(name, yields, normfactor):
        present = [r for r in regions if r in yields]
        if not present:
            return
        samples.append({'Name': name, 'Regions': present, 'DisableStaterror': not staterror})
        if normfactor:
            add_normfactor(normfactor, name)
        for region in present:
            row = yields[region]
            nominal = np.asarray(row['values'], float)
            sumw2 = row.get('sumw2')
            writer.save(region, name, {}, None, nominal,
                        None if sumw2 is None else np.sqrt(np.asarray(sumw2, float)))
            for estimate in search_model.abcd:
                if estimate['background'] == name and estimate['region'] == region and estimate['relative_variance'] > 0:
                    width = math.sqrt(math.log1p(estimate['relative_variance']))
                    systematics.append({'Name': f'abcd_{region}', 'Type': 'Normalization',
                                        'Samples': [name], 'Regions': [region],
                                        'Up': {'Normalization': math.exp(width) - 1},
                                        'Down': {'Normalization': math.exp(-width) - 1}})
            if search_model.registry is None:
                continue
            for source in search_model.registry.sources:
                if not search_model.registry._applies(source, name, region):
                    continue
                key = search_model.registry.parameter(source, name, region)
                entry = {'Name': f'{key}__{name}__{region}', 'ModifierName': key,
                         'Samples': [name], 'Regions': [region]}
                if source['kind'] == 'normsys':
                    up, down = search_model.registry.factors(source, region)
                    entry.update(Type='Normalization', Up={'Normalization': up - 1}, Down={'Normalization': down - 1})
                else:
                    hi, lo = search_model.registry._histo(source, region, nominal)
                    systematic = {'Name': entry['Name']}
                    writer.save(region, name, systematic, 'Up', hi, None)
                    writer.save(region, name, systematic, 'Down', lo, None)
                    entry.update(Type='NormPlusShape', Up={}, Down={})
                systematics.append(entry)

    for bkg in search_model.backgrounds:
        add_sample(bkg['name'], bkg['yields'], bkg['normfactor'])
    if point is not None:
        add_sample('signal', point['yields'], POI)
    config = {'General': {'Measurement': 'constructed', 'POI': POI if POI in normfactors else '',
                          'InputPath': str(writer.folder), 'HistogramFolder': str(writer.folder)},
              'Regions': [{'Name': r} for r in regions], 'Samples': samples,
              'NormFactors': list(normfactors.values()), 'Systematics': systematics}
    return config, writer.written


def cabinetry_channels(search_model, point, roles, folder):
    """pyhf channels built by cabinetry from the written templates."""
    cabinetry = _cabinetry()
    config, written = cabinetry_config(search_model, point, roles, folder)
    cabinetry.configuration.validate(config)
    workspace = cabinetry.workspace.build(config, with_validation=False)
    return workspace['channels'], config, written


def native_channels(search_model, point, roles):
    return search_model.workspace(point, roles)['channels']


def _model(channels, poi):
    import pyhf
    from ravel.physics import pyhf_exclude
    return pyhf.Model({'channels': channels}, poi_name=poi, modifier_settings=pyhf_exclude.MODIFIER_SETTINGS,
                      validate=True)


def _sample_index(channels):
    return {(c['name'], s['name']): s for c in channels for s in c['samples']}


def _parameters(channels):
    out = {}
    for c in channels:
        for s in c['samples']:
            for m in s['modifiers']:
                out.setdefault(m['name'], set()).add(m['type'])
    return out


def _close(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    return a.shape == b.shape and bool(np.allclose(a, b, rtol=TEMPLATE_RTOL, atol=1e-12))


def _expected(model, pars, name=None, value=0.0):
    pars = np.asarray(pars, float).copy()
    if name is not None:
        pars[model.config.par_slice(name)] = value
    return np.asarray(model.expected_actualdata(pars), float)


def parity(native, cabinetry, *, poi=POI, level=0.05):
    """Compare two channel lists for the same declared model; see the module docstring."""
    checks = []

    def check(name, ok, detail):
        checks.append({'name': name, 'status': 'pass' if ok else 'fail', 'detail': detail})
        return ok

    ok = check('channels', [c['name'] for c in native] == [c['name'] for c in cabinetry],
               {'native': [c['name'] for c in native], 'cabinetry': [c['name'] for c in cabinetry]})
    n_index, c_index = _sample_index(native), _sample_index(cabinetry)
    ok &= check('samples', set(n_index) == set(c_index),
                {'only_native': sorted(set(n_index) - set(c_index)), 'only_cabinetry': sorted(set(c_index) - set(n_index))})
    if ok:
        bad = [list(k) for k in n_index if not _close(n_index[k]['data'], c_index[k]['data'])]
        ok &= check('nominal-yields', not bad, {'differing': bad})
        widths = []
        for key in n_index:
            n_stat = [m['data'] for m in n_index[key]['modifiers'] if m['type'] == 'staterror']
            c_stat = [m['data'] for m in c_index[key]['modifiers'] if m['type'] == 'staterror']
            if len(n_stat) != len(c_stat) or any(not _close(a, b) for a, b in zip(n_stat, c_stat)):
                widths.append(list(key))
        ok &= check('mc-statistics-widths', not widths, {'differing': widths})
        n_norm = {k: sorted(m['name'] for m in s['modifiers'] if m['type'] == 'normfactor') for k, s in n_index.items()}
        c_norm = {k: sorted(m['name'] for m in s['modifiers'] if m['type'] == 'normfactor') for k, s in c_index.items()}
        ok &= check('normalisation-factors', n_norm == c_norm,
                    {'differing': [list(k) for k in n_norm if n_norm[k] != c_norm.get(k)]})
    n_pars, c_pars = _parameters(native), _parameters(cabinetry)
    ok &= check('parameters', set(n_pars) == set(c_pars),
                {'only_native': sorted(set(n_pars) - set(c_pars)), 'only_cabinetry': sorted(set(c_pars) - set(n_pars))})
    record = {'status': 'mismatch', 'checks': checks,
              'identical_spec': _canonical_channels(native) == _canonical_channels(cabinetry),
              'representation': {
                  'native': 'absolute histosys templates (code4p) and normsys factors (code4)',
                  'cabinetry': 'NormPlusShape: normsys yield ratio plus a yield-normalised histosys shape; '
                               'Normalization: normsys'},
              'template_rtol': TEMPLATE_RTOL}
    if not ok:
        return record
    has_poi = poi in n_pars
    n_model, c_model = _model(native, poi if has_poi else None), _model(cabinetry, poi if has_poi else None)
    n_init, c_init = np.asarray(n_model.config.suggested_init(), float), np.asarray(c_model.config.suggested_init(), float)
    differing = []
    for name in sorted(n_pars):
        if n_model.config.param_set(name).n_parameters != 1 or not n_model.config.param_set(name).constrained:
            continue
        if name not in c_model.config.par_order:
            differing.append({'parameter': name, 'reason': 'absent from the cabinetry model'})
            continue
        for value in (-1.0, 1.0):
            a, b = _expected(n_model, n_init, name, value), _expected(c_model, c_init, name, value)
            if not _close(a, b):
                differing.append({'parameter': name, 'at': value,
                                  'max_relative_difference': float(np.max(np.abs(a - b) / np.maximum(np.abs(a), 1e-300)))})
    ok &= check('one-sigma-templates', not differing, {'differing': differing})
    nominal_ok = _close(_expected(n_model, n_init), _expected(c_model, c_init))
    ok &= check('expected-data-nominal', nominal_ok, {})
    if has_poi:
        bkg_n, bkg_c = n_init.copy(), c_init.copy()
        bkg_n[n_model.config.poi_index] = 0.0
        bkg_c[c_model.config.poi_index] = 0.0
        ok &= check('expected-data-background-only', _close(_expected(n_model, bkg_n), _expected(c_model, bkg_c)), {})
    if not ok:
        return record
    record['status'] = 'identical' if record['identical_spec'] else 'equivalent-at-one-sigma'
    if has_poi and not record['identical_spec']:
        import pyhf
        from ravel.physics import pyhf_exclude
        values = {}
        for label, model, init in (('native', n_model, n_init), ('cabinetry', c_model, c_init)):
            bkg = init.copy()
            bkg[model.config.poi_index] = 0.0
            data = np.concatenate([_expected(model, bkg), np.asarray(model.config.auxdata, float)])
            values[label] = float(pyhf.infer.hypotest(1.0, data, model, test_stat='qtilde'))
        difference = abs(values['native'] - values['cabinetry']) / max(abs(values['native']), 1e-300)
        record['cls_at_unit_signal_on_background_asimov'] = {**values, 'relative_difference': float(difference),
                                                             'calculator': 'asymptotic qtilde', 'level': level}
    return record


def construct(search_model, point, roles, folder, builder):
    """Channels from the requested builder plus the parity record against the other one.

    Raises ValueError on a parity mismatch: a constructed model never ships with
    disagreeing builders.
    """
    if builder not in BUILDERS:
        raise ValueError('builder must be native or cabinetry')
    native = native_channels(search_model, point, roles)
    tag = f'{point["id"] if point is not None else "background"}-{"+".join(roles)}'
    channels, config, written = cabinetry_channels(search_model, point, roles, Path(folder) / tag)
    record = parity(native, channels, poi=POI)
    record.update(builder=builder, cabinetry_version=CABINETRY_VERSION, point=None if point is None else point['id'],
                  roles=list(roles), histograms={'folder': str(Path(folder) / tag), 'files': written},
                  config_sha256=hashlib.sha256(_canonical(config).encode()).hexdigest())
    if record['status'] == 'mismatch':
        failed = [c['name'] for c in record['checks'] if c['status'] == 'fail']
        raise ValueError('model construction parity failed: ' + ', '.join(failed))
    return (channels if builder == 'cabinetry' else native), record
