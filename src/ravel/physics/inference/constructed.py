"""The constructed-likelihood rung: a HistFactory model from published per-region yields and a
declared systematics registry, for the recasting route (``pyhf_exclude.py constructed``).

Inputs are the existing per-region yield record (``name``, ``n``, ``b``, ``db``, ``s``) and a
systematics registry (``ravel.physics.inference.systematics``) whose sources apply to the
single ``background`` sample. Each registry source is one constrained parameter under its
declared correlation model, so a component listed for several regions is correlated across
them. The published total background uncertainty ``db`` is preserved: the part of ``db`` not
accounted for by the declared components is added as an uncorrelated per-region remainder
and recorded; declared components that exceed ``db`` are refused, never rescaled.

The model fits every region simultaneously, which is valid only for mutually exclusive
regions. The caller declares that (``regions_exclusive=True``) after checking the published
region definitions; the declaration is recorded, never inferred from yields.

Signal MC-statistical uncertainties are not part of the yield record and are therefore not in
the model; the record says so. This module builds the model; the limit comes from
``pyhf_exclude.compute`` and its guarded optimizer.
"""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path

import numpy as np

from .systematics import Registry

SAMPLE = 'background'
POINT = 'nominal'
RESIDUAL_PREFIX = 'residual_'
EXCESS_RTOL = 1e-9


def _yield_rows(srs):
    from ravel.physics.pyhf_exclude import _counting_inputs
    if type(srs) is not list or not srs:
        raise ValueError('constructed model needs a nonempty list of regions')
    rows, names = [], []
    for sr in srs:
        row = _counting_inputs(sr)
        name = sr.get('name')
        if type(name) is not str or not name.strip() or name in names or name == 'mu' or name.startswith(RESIDUAL_PREFIX):
            raise ValueError('region names must be distinct nonempty strings not starting with ' + RESIDUAL_PREFIX)
        names.append(name)
        rows.append({'name': name, **{k: float(row[k]) for k in ('n', 'b', 'db', 's')}})
    return rows


def _declared_variance(registry, name, region, nominal):
    """Sum of squared one-sigma shifts of the declared components in one region (single bin)."""
    total = 0.0
    for key, (up, down) in registry.variations(name, region, np.asarray([nominal], float)).items():
        shift = max(abs(float(up[0]) - nominal), abs(float(down[0]) - nominal))
        total += shift * shift
    return total


def residuals(rows, registry):
    """Per-region remainder of the published total uncertainty after the declared components."""
    out = []
    for row in rows:
        declared = _declared_variance(registry, SAMPLE, row['name'], row['b'])
        total = row['db'] ** 2
        if declared > total * (1 + EXCESS_RTOL) + 1e-300:
            raise ValueError(f'{row["name"]}: declared systematic components ({math.sqrt(declared):.6g}) exceed the published '
                             f'total background uncertainty ({row["db"]:.6g}); inconsistent inputs are not rescaled')
        remainder = math.sqrt(max(total - declared, 0.0))
        relative = None
        if remainder > 0:
            if row['b'] <= 0:
                raise ValueError(f'{row["name"]}: a background uncertainty on a zero background cannot be a normalisation '
                                 'factor; use counting mode for that region')
            relative = remainder / row['b']
            if relative >= 1:
                raise ValueError(f'{row["name"]}: the remaining background uncertainty is at or above 100% of the background; '
                                 'a Gaussian normalisation factor cannot represent it; use counting mode for that region')
        out.append({'region': row['name'], 'total_uncertainty': row['db'], 'declared_quadrature': math.sqrt(declared),
                    'remainder': remainder, 'relative': relative})
    return out


def document(srs, registry_document, *, regions_exclusive, builder='cabinetry'):
    """The search-statistics document for the constructed model, with the residual sources appended."""
    if regions_exclusive is not True:
        raise ValueError('a simultaneous model over all regions needs regions_exclusive=True, declared after checking the '
                         'published region definitions')
    rows = _yield_rows(srs)
    names = [r['name'] for r in rows]
    registry = Registry(registry_document)
    for source in registry.sources:
        if source['samples'] != 'all' and source['samples'] != [SAMPLE]:
            raise ValueError(f'{source["name"]}: constructed-model sources apply to "all" or ["{SAMPLE}"]')
        if source['regions'] != 'all' and set(source['regions']) - set(names):
            raise ValueError(f'{source["name"]}: applies to regions absent from the yield record: '
                             + ', '.join(sorted(set(source['regions']) - set(names))))
        if source['kind'] == 'histosys':
            alternatives = [source.get('alternative'), source.get('alternative_up'), source.get('alternative_down')]
            for table in alternatives:
                if table is not None and set(table) - set(names):
                    raise ValueError(f'{source["name"]}: alternative yields for regions absent from the yield record')
    remainders = residuals(rows, registry)
    extra = []
    for row in remainders:
        if row['relative'] is None:
            continue
        extra.append({'name': RESIDUAL_PREFIX + row['region'], 'kind': 'normsys', 'relative': row['relative'],
                      'applies_to': {'samples': [SAMPLE], 'regions': [row['region']]}, 'correlation': 'correlated',
                      'origin': 'requester-assumption',
                      'statement': f'remainder of the published total background uncertainty in {row["region"]} '
                                   'after the declared components, taken uncorrelated with every other region'})
    full_registry = deepcopy(registry_document)
    full_registry['sources'] = list(full_registry.get('sources', [])) + extra
    doc = {'regions': [{'name': r['name'], 'role': 'SR', 'observed': [r['n']]} for r in rows],
           'backgrounds': [{'name': SAMPLE, 'normfactor': None, 'yields': {r['name']: {'values': [r['b']]} for r in rows}}],
           'signal_points': [{'id': POINT, 'coordinates': {}, 'yields': {r['name']: {'values': [r['s']]} for r in rows}}],
           'mc_statistics': 'none', 'systematics': full_registry,
           'data': {'mode': 'observed', 'injections': {}},
           'computations': {'discovery': False, 'cls_at_nominal': False, 'cls_limits': True, 'background_only_fit': False},
           'asimov_source': 'nominal', 'cls_level': 0.05,
           'mc_adequacy': {'max_relative_uncertainty': 1.0, 'min_effective_entries': 1}, 'contours': None,
           'model_construction': {'builder': builder}}
    return doc, {'regions': names, 'residuals': remainders, 'yields': rows}


def build(srs, registry_document, *, folder, builder='cabinetry', regions_exclusive):
    """(pyhf model, data, record) for the constructed likelihood over all regions."""
    from . import search
    doc, info = document(srs, registry_document, regions_exclusive=regions_exclusive, builder=builder)
    search_model = search.SearchModel(doc)
    search_model.construction_folder = Path(folder)
    point = search_model.points[0]
    model, spec = search_model.model(point, roles=('SR',))
    if model.config.poi_index is None:
        raise ValueError('the constructed model has no signal in any region')
    pars = np.asarray(model.config.suggested_init(), float)
    pars[model.config.poi_index] = 0.0
    data = search_model._data_for(model, pars)
    parity = search_model.construction_records[-1]
    record = {'builder': builder, 'cabinetry_version': parity['cabinetry_version'], 'parity': parity,
              'regions': info['regions'], 'residuals': info['residuals'],
              'systematics': search_model.registry.summary(),
              'mutual_exclusivity': 'declared by the caller after checking the published region definitions',
              'signal_mc_statistics': 'not included: absent from the yield record',
              'mc_statistics': 'none', 'data': 'observed counts of every region',
              'constraint_model': 'one constrained parameter per declared component under its correlation model; '
                                  'per-region uncorrelated remainder of the published total uncertainty'}
    return model, data, record, doc


MAX_BRACKETED = 6
BRACKET_CORRELATIONS = ("correlated", "per-region")


def variant_registry(registry_document, bracket=None):
    """The registry a result was reported with: each bracketed unknown correlation at its reported extreme."""
    document = deepcopy(registry_document)
    for source in document.get('sources') or ():
        if bracket and source.get('name') in bracket['reported_assignment']:
            source['correlation'] = bracket['reported_assignment'][source['name']]
    return document


def bracket_correlations(srs, registry_document, *, folder, compute, builder='cabinetry', regions_exclusive):
    """Evaluate correlated and independent assignments and report their weakest expected variant.

    Each unknown-correlation source is built once fully correlated across the regions it lists and
    once independent per region. Every combination (at most 2**6) is built and computed with
    ``compute(model, data)`` (an exclusion result). The variant with the weakest expected median
    limit is reported; the rule is decided on the expected limit, never on the observed one, so the
    data do not choose the treatment. Every variant's limits are kept as a method uncertainty.

    Returns ``((model, data, record, document, result), bracket)``.
    """
    import itertools
    registry = Registry(registry_document)
    unknown = registry.unknown_correlations()
    if not unknown:
        raise ValueError('no systematic source declares an unknown correlation; nothing to bracket')
    if len(unknown) > MAX_BRACKETED:
        raise ValueError(f'{len(unknown)} sources with unknown correlations exceed the bracketing limit of '
                         f'{MAX_BRACKETED}; declare some of them')
    variants, built, assignments = {}, {}, {}
    for index, corner in enumerate(itertools.product(BRACKET_CORRELATIONS, repeat=len(unknown))):
        variant = deepcopy(registry_document)
        for source in variant['sources']:
            if source['name'] in unknown:
                source['correlation'] = corner[unknown.index(source['name'])]
        key = ','.join(f'{name}={value}' for name, value in zip(unknown, corner))
        assignments[key] = dict(zip(unknown, corner))
        model, data, record, document = build(srs, variant, folder=Path(folder) / f'variant-{index}',
                                              builder=builder, regions_exclusive=regions_exclusive)
        result = compute(model, data)
        built[key] = (model, data, record, document, result)
        variants[key] = result
    expected = {key: float(result['exp_limits'][2]) for key, result in variants.items()}
    statuses = {key: result['limit_status']['expected'][2] for key, result in variants.items()}
    chosen = max(expected, key=expected.get)
    bracket = {'sources': unknown, 'extremes': list(BRACKET_CORRELATIONS), 'variants': expected,
               'domain': {'kind': 'finite-assignments', 'coverage': 'endpoint-sensitivity',
                          'assignments': list(BRACKET_CORRELATIONS), 'sources': list(unknown),
                          'continuous_envelope': False},
               'expected_median_status': statuses,
               'observed': {key: result['obs_limit'] for key, result in variants.items()},
               'rule': 'max', 'decided_on': 'expected median limit', 'reported': expected[chosen],
               'reported_variant': chosen, 'reported_assignment': assignments[chosen],
               'spread': {'min': min(expected.values()), 'max': max(expected.values())}}
    return built[chosen], bracket
