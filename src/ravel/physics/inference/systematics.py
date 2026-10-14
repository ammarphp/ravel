"""A declared registry of systematic uncertainties and its application to templates.

Each source has a name, a kind, the samples and regions it applies to, a
correlation model and its provenance:

- ``origin: cited`` with a ``citation`` (paper, note, table), or
- ``origin: requester-assumption`` with the requester's ``statement``.

Kinds:

- ``normsys``: a normalisation factor, from ``relative`` (symmetric) or ``up``/``down``;
- ``histosys``: a shape variation built from an alternative sample's yields per
  region. ``one-sided-symmetrised`` mirrors the alternative about the nominal;
  ``one-sided`` keeps the nominal as the other side; ``two-sided`` takes explicit
  ``alternative_up`` and ``alternative_down`` yields.

Correlation models: ``correlated`` (one parameter everywhere), ``per-region``,
``per-sample`` and ``per-sample-and-region`` (separate parameters). The registry
must list components that are known to be missing in ``absent`` (possibly an
empty list). A mirrored variation that goes negative is refused, never clipped.
"""
from __future__ import annotations

from copy import deepcopy
import math

import numpy as np

from .formula import NAME

KINDS = ('normsys', 'histosys')
CORRELATIONS = ('correlated', 'per-region', 'per-sample', 'per-sample-and-region')
CONSTRUCTIONS = ('one-sided-symmetrised', 'one-sided', 'two-sided')


def _text(value, label):
    if type(value) is not str or not value.strip():
        raise ValueError(label)
    return value


def _positive(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(label + ' must be a positive finite number')
    return float(value)


def _selection(value, label):
    if value == 'all':
        return 'all'
    if type(value) is not list or not value or any(type(v) is not str or not v.strip() for v in value):
        raise ValueError(label + ' must be "all" or a nonempty list of names')
    return list(value)


def _yields(value, label):
    if type(value) is not dict or not value:
        raise ValueError(label + ' must map regions to yield lists')
    out = {}
    for region, values in value.items():
        if type(values) is not list or not values or any(
                type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError(label + f' for {region} must be finite numbers')
        out[region] = np.array(values, float)
    return out


class Registry:
    def __init__(self, document):
        if type(document) is not dict or document.get('schema_version') != 1:
            raise ValueError('systematics registry schema_version 1 required')
        if set(document) - {'schema_version', 'sources', 'absent', 'description'}:
            raise ValueError('systematics registry has unsupported fields')
        if 'absent' not in document:
            raise ValueError('the registry must list absent components explicitly (an empty list if none)')
        absent = document['absent']
        if type(absent) is not list or any(type(a) is not dict or set(a) != {'component', 'reason'}
                                           or not str(a['component']).strip() or not str(a['reason']).strip()
                                           for a in absent):
            raise ValueError('absent components need component and reason')
        sources = document.get('sources')
        if type(sources) is not list:
            raise ValueError('registry sources must be a list')
        self.document = deepcopy(document)
        self.sources, names = [], set()
        for raw in sources:
            self.sources.append(self._source(raw, names))
        self.absent = deepcopy(absent)

    @staticmethod
    def _source(raw, names):
        if type(raw) is not dict:
            raise ValueError('registry sources must be objects')
        name = raw.get('name')
        if type(name) is not str or not NAME.fullmatch(name) or name in names:
            raise ValueError('registry sources need unique identifier names')
        names.add(name)
        kind = raw.get('kind')
        if kind not in KINDS:
            raise ValueError(f'{name}: kind must be normsys or histosys')
        common = {'name', 'kind', 'applies_to', 'correlation', 'origin', 'citation', 'statement', 'description'}
        specific = ({'relative', 'up', 'down'} if kind == 'normsys'
                    else {'construction', 'alternative', 'alternative_up', 'alternative_down'})
        if set(raw) - common - specific:
            raise ValueError(f'{name}: unsupported fields ' + ', '.join(sorted(set(raw) - common - specific)))
        origin = raw.get('origin')
        if origin == 'cited':
            _text(raw.get('citation'), f'{name}: a cited value needs a citation')
        elif origin == 'requester-assumption':
            _text(raw.get('statement'), f'{name}: a requester assumption needs the requester statement')
        else:
            raise ValueError(f'{name}: origin must be cited or requester-assumption')
        applies = raw.get('applies_to')
        if type(applies) is not dict or set(applies) != {'samples', 'regions'}:
            raise ValueError(f'{name}: applies_to needs samples and regions')
        if raw.get('correlation') not in CORRELATIONS:
            raise ValueError(f'{name}: correlation must be one of ' + ', '.join(CORRELATIONS))
        source = {'name': name, 'kind': kind, 'correlation': raw['correlation'], 'origin': origin,
                  'provenance': raw.get('citation') if origin == 'cited' else raw.get('statement'),
                  'samples': _selection(applies['samples'], f'{name}: samples'),
                  'regions': _selection(applies['regions'], f'{name}: regions')}
        if kind == 'normsys':
            if 'relative' in raw:
                if 'up' in raw or 'down' in raw:
                    raise ValueError(f'{name}: give relative or up/down, not both')
                r = _positive(raw['relative'], f'{name}: relative')
                if r >= 1:
                    raise ValueError(f'{name}: a relative uncertainty of 100% or more needs explicit up/down factors')
                source['up'], source['down'] = 1 + r, 1 - r
            else:
                source['up'] = _positive(raw.get('up'), f'{name}: up')
                source['down'] = _positive(raw.get('down'), f'{name}: down')
        else:
            construction = raw.get('construction')
            if construction not in CONSTRUCTIONS:
                raise ValueError(f'{name}: construction must be one of ' + ', '.join(CONSTRUCTIONS))
            source['construction'] = construction
            if construction == 'two-sided':
                source['alternative_up'] = _yields(raw.get('alternative_up'), f'{name}: alternative_up')
                source['alternative_down'] = _yields(raw.get('alternative_down'), f'{name}: alternative_down')
            else:
                source['alternative'] = _yields(raw.get('alternative'), f'{name}: alternative')
        return source

    @staticmethod
    def _applies(source, sample, region):
        return ((source['samples'] == 'all' or sample in source['samples'])
                and (source['regions'] == 'all' or region in source['regions']))

    @staticmethod
    def parameter(source, sample, region):
        c = source['correlation']
        return (source['name'] if c == 'correlated' else f'{source["name"]}_{region}' if c == 'per-region'
                else f'{source["name"]}_{sample}' if c == 'per-sample' else f'{source["name"]}_{sample}_{region}')

    def _histo(self, source, region, nominal):
        name = source['name']
        if source['construction'] == 'two-sided':
            if region not in source['alternative_up'] or region not in source['alternative_down']:
                raise ValueError(f'{name}: no alternative yields for region {region}')
            up, down = source['alternative_up'][region], source['alternative_down'][region]
        else:
            if region not in source['alternative']:
                raise ValueError(f'{name}: no alternative yields for region {region}')
            up = source['alternative'][region]
            down = 2 * nominal - up if source['construction'] == 'one-sided-symmetrised' else nominal.copy()
        if up.shape != nominal.shape or down.shape != nominal.shape:
            raise ValueError(f'{name}: alternative yields for {region} have the wrong number of bins')
        if np.any(down < 0) or np.any(up < 0):
            raise ValueError(f'{name}: the variation in {region} is negative; it is not clipped')
        return up, down

    def variations(self, sample, region, nominal):
        """Absolute up/down templates per parameter for one sample in one region."""
        nominal = np.asarray(nominal, float)
        out = {}
        for source in self.sources:
            if not self._applies(source, sample, region):
                continue
            key = self.parameter(source, sample, region)
            if source['kind'] == 'normsys':
                out[key] = (nominal * source['up'], nominal * source['down'])
            else:
                out[key] = self._histo(source, region, nominal)
        return out

    def modifiers(self, sample, region, nominal):
        nominal = np.asarray(nominal, float)
        mods = []
        for source in self.sources:
            if not self._applies(source, sample, region):
                continue
            key = self.parameter(source, sample, region)
            if source['kind'] == 'normsys':
                mods.append({'name': key, 'type': 'normsys', 'data': {'hi': source['up'], 'lo': source['down']}})
            else:
                up, down = self._histo(source, region, nominal)
                mods.append({'name': key, 'type': 'histosys',
                             'data': {'hi_data': [float(x) for x in up], 'lo_data': [float(x) for x in down]}})
        return mods

    def alternative_comparison(self, sample, nominal_by_region):
        out = {}
        for source in self.sources:
            if source['kind'] != 'histosys' or not (source['samples'] == 'all' or sample in source['samples']):
                continue
            alternatives = source.get('alternative') or source.get('alternative_up')
            rows = {}
            for region, alt in alternatives.items():
                if region not in nominal_by_region:
                    continue
                nominal = np.asarray(nominal_by_region[region], float)
                with np.errstate(divide='ignore', invalid='ignore'):
                    rel = np.where(nominal != 0, (alt - nominal) / nominal, np.nan)
                rows[region] = {'nominal': nominal.tolist(), 'alternative': alt.tolist(),
                                'relative_difference': [None if not np.isfinite(x) else float(x) for x in rel]}
            out[source['name']] = rows
        return out

    def summary(self):
        return {'sources': [{'name': s['name'], 'kind': s['kind'], 'correlation': s['correlation'],
                             'origin': s['origin'], 'provenance': s['provenance'],
                             'samples': s['samples'], 'regions': s['regions'],
                             **({'up': s['up'], 'down': s['down']} if s['kind'] == 'normsys'
                                else {'construction': s['construction']})} for s in self.sources],
                'absent': deepcopy(self.absent)}
