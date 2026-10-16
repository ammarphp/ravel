"""Partitioned execution of a compiled recipe and its governed outputs.

``analyse(partition, plan)`` reads the files and entry ranges of one partition and returns
*additive* sums: cutflows (raw count, sum of weights, sum of squared weights after each
cut), histogram contents (sumw, sumw2 and entries per bin, with underflow, overflow and
undefined values kept apart), efficiency-map counts, the generator-weight sums used for
normalisation and an optional per-event record. Any split of the inputs into partitions
gives the same merged sums. ``merge(partials)`` adds them, refusing overlapping entry
ranges, and ``finalize(merged, plan, normalization)`` applies the declared normalisation and
writes:

- ``histograms/<name>.json``: ``binned_values`` documents that ``ravel fill-template`` reads
  (one per histogram and variation; variations are suffixed ``__<systematic>``);
- ``cutflow.json``: ordered cuts with raw counts, weighted sums and yields per region;
- ``analysis-result.json``: every sum, the normalisation and its sources, MC precision,
  efficiency-map counts and full provenance (input, recipe, descriptor and map hashes and
  the engine source hash);
- ``event-record.jsonl`` when the recipe asks for one.
- ``features.npz`` and ``features.json`` for a bounded nominal feature population.

A partition is ``{"inputs": [{"path", "file_index", "entry_start", "entry_stop"}],
"chunk_size": N}``; ``file_index`` identifies the file within the sample and keys the
reproducible random numbers used by efficiency selection.
"""
import hashlib
import json
import math
import os
import time
import zlib
from pathlib import Path

import awkward as ak
import numpy as np

from . import efficiency as eff_lib
from . import kinematics as kin
from .observables import Context, evaluate, pair_selection
from .recipe import slug

SCHEMA = 1
NOMINAL = 'nominal'


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def engine_version():
    """ravel version and a hash of this package's source files."""
    from ravel import __version__
    h = hashlib.sha256()
    for p in sorted(Path(__file__).parent.glob('*.py')):
        h.update(p.name.encode()); h.update(p.read_bytes())
    return {'ravel_version': __version__, 'columnar_source_sha256': h.hexdigest()}


# ---------------------------------------------------------------- object steps
def _fields(record):
    return {f: record[f] for f in record.fields if not f.startswith('_')}


def _sort(record):
    return record[ak.argsort(record.pt, axis=1, ascending=False, stable=True)]


def _apply_select(record, expression):
    if expression is None:
        return record
    return record[expression.evaluate_cut(_fields(record))]


class _Weights:
    """Per-event weight factors from object efficiencies.

    After an ``enumerate`` step each event is replaced by its keep/drop subsets:
    ``index`` maps every replica to its source event and ``probability`` holds the
    replica's probability (the replicas of one event sum to one).
    """
    def __init__(self, n):
        self.factor = np.ones(n)
        self.index = None
        self.probability = None


def _enumerate_subsets(objects, name, efficiencies, cap, label):
    """Replicate every collection so each event appears once per keep/drop subset of `name`."""
    a = objects[name]
    n = ak.to_numpy(ak.num(a, axis=1)).astype(np.int64)
    if n.size and n.max() > cap:
        raise ValueError(f'efficiency step {label!r}: an event has {int(n.max())} objects, above max_objects {cap}; '
                         'raise max_objects (at most 12) or use the select application')
    replicas = np.left_shift(np.int64(1), n)
    index = np.repeat(np.arange(len(n)), replicas)
    starts = np.cumsum(replicas) - replicas
    subset = np.arange(int(replicas.sum()), dtype=np.int64) - np.repeat(starts, replicas)
    replicated = {k: v[index] for k, v in objects.items()}
    counts = n[index]
    local = np.arange(int(counts.sum()), dtype=np.int64) - np.repeat(np.cumsum(counts) - counts, counts)
    keep_flat = ((np.repeat(subset, counts) >> local) & 1).astype(bool)
    eff_flat = ak.to_numpy(ak.flatten(efficiencies[index], axis=None)).astype(float)
    factor = np.where(keep_flat, eff_flat, 1.0 - eff_flat)
    probability = np.ones(len(index))
    if factor.size:
        owner = np.repeat(np.arange(len(index)), counts)
        np.multiply.at(probability, owner, factor)
    replicated[name] = replicated[name][ak.unflatten(keep_flat, counts)]
    return replicated, index, probability


def build_objects(plan, view, *, weights, file_index, variation, counts):
    """Run the object steps for one view; returns the named object collections."""
    objects = {}
    entries, met, met_phi = np.asarray(view.entries), view.met_magnitude, view.met_phi
    alt_maps = {s['step']: s['map'] for s in plan.systematics if s['kind'] == 'efficiency-map' and s['name'] == variation}
    for step in plan.steps:
        spec, ex = step.spec, step.expressions
        if step.kind == 'define':
            record = _apply_select(view.collections[spec['from']], ex['select'])
            objects[spec['name']] = _sort(record) if spec.get('sort', 'pt') == 'pt' else record
        elif step.kind == 'subset':
            record = _apply_select(objects[spec['from_object']], ex['select'])
            objects[spec['name']] = _sort(record) if spec.get('sort', 'pt') == 'pt' else record
        elif step.kind == 'union':
            names = sorted(plan.object_fields[spec['name']]) + ['_idx', '_src']
            parts = [objects[x][names] for x in spec['union']]
            merged = _sort(ak.concatenate(parts, axis=1))
            objects[spec['name']] = _apply_select(merged, ex['select'])
        elif step.kind == 'overlap':
            a, b = objects[spec['remove']], objects[spec['near']]
            pairs = ak.cartesian({'a': a, 'b': b}, axis=1, nested=True)
            dr = kin.delta_r(pairs.a.eta, pairs.a.phi, pairs.b.eta, pairs.b.phi)
            threshold = spec['dr'] if not isinstance(spec['dr'], str) else ex['dr'].evaluate(_fields(a))
            close = dr < threshold
            if ex.get('near_select') is not None:
                near_ok = ex['near_select'].evaluate_cut(_fields(b))
                close = close & ak.cartesian({'a': a.pt, 'b': near_ok}, axis=1, nested=True).b
            removed = ak.any(close, axis=2)
            if ex.get('remove_select') is not None:
                removed = removed & ex['remove_select'].evaluate_cut(_fields(a))
            objects[spec['remove']] = a[~removed]
        elif step.kind == 'isolation':
            a, b = objects[spec['object']], objects[spec['against']]
            if ex.get('against_select') is not None:
                b = b[ex['against_select'].evaluate_cut(_fields(b))]
            pairs = ak.cartesian({'a': a, 'b': b}, axis=1, nested=True)
            dr = kin.delta_r(pairs.a.eta, pairs.a.phi, pairs.b.eta, pairs.b.phi)
            same = (pairs.a._src == pairs.b._src) & (pairs.a._idx == pairs.b._idx)
            inside = (dr <= spec['cone']) & (dr > spec.get('min_cone', 0.0)) & ~same
            total = ak.sum(ak.where(inside, pairs.b.pt, 0.0), axis=2)
            if spec['relative']:
                total = total / a.pt
            objects[spec['object']] = ak.with_field(a, total, spec['field'])
        elif step.kind == 'efficiency':
            a = objects[spec['object']]
            emap = plan.maps[alt_maps.get(spec['name'], spec['map'])]
            flat_counts = ak.num(a, axis=1)
            coords = [ak.to_numpy(ak.flatten(ex[f'c{k}'].evaluate(_fields(a)), axis=None)).astype(float)
                      for k in range(len(emap.axes))]
            values, axis_counts = emap.lookup(coords)
            record = counts.setdefault(spec['name'], {'objects': 0, 'axes': {}})
            record['objects'] += int(len(values))
            for axis_name, c in axis_counts.items():
                slot = record['axes'].setdefault(axis_name, {'below': 0, 'above': 0, 'clamped': 0, 'zeroed': 0})
                for k2, v in c.items():
                    slot[k2] += v
            per_object = ak.unflatten(values, flat_counts)
            if spec['application'] == 'all-required-weight':
                weights.factor = weights.factor * ak.to_numpy(ak.prod(per_object, axis=1))
            elif spec['application'] == 'enumerate':
                from .recipe import DEFAULT_ENUMERATED
                objects, index, probability = _enumerate_subsets(
                    objects, spec['object'], per_object, spec.get('max_objects', DEFAULT_ENUMERATED), spec['name'])
                weights.factor = weights.factor[index] * probability
                weights.probability = probability if weights.probability is None else weights.probability[index] * probability
                weights.index = index if weights.index is None else weights.index[index]
                entries, met, met_phi = entries[index], np.asarray(met)[index], np.asarray(met_phi)[index]
            else:
                object_entries = ak.to_numpy(ak.flatten(ak.broadcast_arrays(entries, a.pt)[0], axis=None))
                keys = ak.to_numpy(ak.flatten(a._src * 1_000_003 + a._idx, axis=None))
                u = eff_lib.uniforms(spec['seed'], np.full(len(keys), file_index), object_entries, keys,
                                     stream=zlib.crc32(spec['name'].encode()))
                keep = ak.unflatten(u < values, flat_counts)
                objects[spec['object']] = a[keep]
        elif step.kind == 'pair_split':
            parent = objects[spec['from']]
            ctx = Context(objects, met, met_phi)
            first, second, _ = pair_selection(ctx, spec['from'], rule=spec['choose'], target=spec.get('target_mass'),
                                              ossf=spec['charge'] == 'opposite' and spec['flavour'] == 'same')
            if not (spec['charge'] == 'opposite' and spec['flavour'] == 'same') and (spec['charge'] == 'opposite' or spec['flavour'] == 'same'):
                first, second = _constrained_pair(ctx, spec)
            index = ak.local_index(parent.pt, axis=1)
            in_pair = (index == first) | (index == second)
            objects[spec['pair']] = parent[in_pair]
            objects[spec['rest']] = parent[~in_pair]
    return objects


def _constrained_pair(ctx, spec):
    """Pairs with only one of the charge or flavour conditions."""
    from .observables import _pairs, _choose, _mass4
    ii, jj, vec = _pairs(ctx, spec['from'], None)
    count = vec.shape[1]
    exists = np.isfinite(vec[..., 3])
    valid = exists[:, ii] & exists[:, jj]
    if spec['charge'] == 'opposite':
        c = ctx.padded(spec['from'], count, 'charge'); valid &= c[:, ii] * c[:, jj] < 0
    if spec['flavour'] == 'same':
        f = ctx.padded(spec['from'], count, 'flavour'); valid &= f[:, ii] == f[:, jj]
    column = _choose({'mass': _mass4(vec[:, ii, :] + vec[:, jj, :])}, valid, spec['choose'], spec.get('target_mass'))
    safe = np.where(column >= 0, column, 0)
    return np.where(column >= 0, ii[safe], -1), np.where(column >= 0, jj[safe], -1)


# ---------------------------------------------------------------- accumulation
def _empty_variation(plan):
    return {
        'events': {'n': 0, 'sum_generator': 0.0, 'sum_generator2': 0.0, 'positive': 0, 'negative': 0, 'zero': 0},
        'cutflows': {r: [[0, 0.0, 0.0] for _ in range(len(c) + 1)] for r, c in plan.regions.items()},
        'histograms': {h.name: {'sumw': [0.0] * math.prod(h.shape), 'sumw2': [0.0] * math.prod(h.shape),
                                'entries': [0] * math.prod(h.shape), 'underflow': [0, 0.0, 0.0],
                                'overflow': [0, 0.0, 0.0], 'outside': [0, 0.0, 0.0], 'undefined': [0, 0.0, 0.0]}
                       for h in plan.histograms},
        'efficiency': {},
        'event_weights': {s['name']: {'rows': 0, 'axes': {
            a['name']: {'below': 0, 'above': 0, 'clamped': 0, 'one': 0}
            for a in plan.maps[s['map']].axes}} for s in plan.event_weights},
        'undefined_observables': {o.name: 0 for o in plan.observables},
    }


def _weights_for(plan, view, variation_spec):
    w = plan.doc['weights']
    gen_field = w['generator']
    factors = [e for e in plan.weight_entries if e['kind'] == 'event-field']
    if variation_spec is not None and variation_spec['kind'] == 'weight-factor':
        factors = [{**e, 'field': variation_spec.get('replace', {}).get(e['field'], e['field'])} for e in factors]
        factors += [{'kind': 'event-field', 'field': f} for f in variation_spec.get('multiply', [])]
        gen_field = variation_spec.get('generator', gen_field)
    n = len(view.entries)
    generator = np.ones(n) if gen_field is None else np.asarray(view.event[gen_field], float)
    if not np.all(np.isfinite(generator)):
        raise ValueError(f'event weight {gen_field!r} is missing or not finite in some events')
    product = generator.copy()
    for factor in factors:
        f = factor['field']
        active = _factor_mask(factor, view.event, n)
        if f not in view.event and factor.get('optional_in_files'):
            continue
        value = np.asarray(view.event[f], float)
        if not np.all(np.isfinite(value[active])):
            raise ValueError(f'weight factor {f!r} is not finite in some active events')
        product *= np.where(active, value, 1.0)
    if not np.isfinite(product).all():
        raise ValueError('event weight product is not finite')
    return generator, product


def _event_weight_factors(plan, ctx, entries, acc, variation_spec, file_index):
    """Event-observable corrections, including enumerated reconstruction subsets.

    Diagnostics count evaluated rows (subsets when enumerating); moments below still
    sum the subsets of each original event before squaring. Generator exposure is
    unchanged. The event application's policy overrides the map's object policy.
    """
    factor = np.ones(ctx.n)
    for spec in plan.event_weights:
        key = spec['map']
        if (variation_spec is not None and variation_spec['kind'] == 'event-weight-map'
                and variation_spec['weight'] == spec['name']):
            key = variation_spec['map']
        emap = plan.maps[key]
        safe, use_one = [], np.zeros(ctx.n, bool)
        counts = acc[spec['name']]
        counts['rows'] += ctx.n
        for observable, axis, edges in zip(spec['observables'], emap.axes, emap.edges):
            x = np.broadcast_to(np.asarray(ctx.values[observable], float), (ctx.n,))
            invalid = ~np.isfinite(x)
            below, above = x < edges[0], x >= edges[-1]
            outside = below | above
            refused = invalid | (outside if spec['out_of_range'] == 'refuse' else False)
            if refused.any():
                row = int(np.flatnonzero(refused)[0])
                raise ValueError(f'event weight {spec["name"]!r}: file_index {file_index}, '
                                 f'event index {int(entries[row])}, observable {observable!r} '
                                 f'is undefined or outside [{edges[0]}, {edges[-1]}); '
                                 f'policy {spec["out_of_range"]}')
            entry = counts['axes'][axis['name']]
            entry['below'] += int(below.sum()); entry['above'] += int(above.sum())
            if spec['out_of_range'] == 'clamp':
                entry['clamped'] += int(outside.sum())
            elif spec['out_of_range'] == 'one':
                entry['one'] += int(outside.sum())
                use_one |= outside
            safe.append(np.clip(x, edges[0], np.nextafter(edges[-1], edges[0])))
        values, _ = emap.lookup(safe)
        factor *= np.where(use_one, 1.0, values)
    if not np.isfinite(factor).all():
        raise ValueError('event weight map product is not finite')
    return factor


def _factor_mask(factor, event, n):
    condition = factor.get('applies_when')
    if condition is None:
        return np.ones(n, bool)
    periods = np.asarray(event[condition['field']])
    if not np.isfinite(periods).all():
        raise ValueError(f'weight period field {condition["field"]!r} is not finite')
    return np.isin(periods, condition['in'])


def _object_weights(plan, view, objects, index):
    """Evaluate typed collection factors after all object steps and subset replication."""
    entries = np.asarray(view.entries) if index is None else np.asarray(view.entries)[index]
    event = view.event if index is None else {k: np.asarray(v)[index] for k, v in view.event.items()}
    product = np.ones(len(entries))
    for factor in plan.weight_entries:
        kind = factor['kind']
        if kind == 'event-field':
            continue
        active = _factor_mask(factor, event, len(entries))
        obj = objects[factor['objects']][active]
        if kind == 'object_product':
            value = obj[factor['field']]
            bad = ak.to_numpy(ak.any(ak.fill_none(~np.isfinite(value), True), axis=1))
            if bad.any():
                raise ValueError(f'object_product: invalid weight at event index {entries[active][np.flatnonzero(bad)[0]]}')
            factor_value = ak.to_numpy(ak.prod(value, axis=1))
        elif kind == 'trigger_or_sf':
            acceptances = []
            for field in ('data_eff', 'mc_eff'):
                value = obj[factor[field]]
                invalid = ak.fill_none((~np.isfinite(value)) | (value < 0) | (value > 1), True)
                bad = ak.to_numpy(ak.any(invalid, axis=1))
                if bad.any():
                    raise ValueError(f'trigger_or_sf: {field} must be in [0, 1] at event index '
                                     f'{entries[active][np.flatnonzero(bad)[0]]}')
                # log1p/expm1 preserve small nonzero acceptances that 1-prod rounds to zero.
                with np.errstate(divide='ignore'):
                    acceptances.append(-np.expm1(ak.to_numpy(ak.sum(np.log1p(-value), axis=1))))
            data, mc = acceptances
            if (mc == 0).any():
                raise ValueError(f'trigger_or_sf: zero MC denominator at event index '
                                 f'{entries[active][np.flatnonzero(mc == 0)[0]]}')
            factor_value = data / mc
        else:
            raise ValueError(f'unsupported compiled weight entry kind {kind!r}')
        product[active] *= factor_value
    if not np.isfinite(product).all():
        raise ValueError('object weight product is not finite')
    return product


def _accumulate(plan, view, acc, *, file_index, variation_name, variation_spec, record,
                raw_chunk=None, feature_collector=None):
    n = len(view.entries)
    if n == 0:
        return {region: np.zeros(0, bool) for region in plan.regions}, np.zeros(0)
    generator, base = _weights_for(plan, view, variation_spec)
    weights = _Weights(n)
    objects = build_objects(plan, view, weights=weights, file_index=file_index, variation=variation_name,
                            counts=acc['efficiency'])
    ev = acc['events']
    ev['n'] += n
    ev['sum_generator'] += math.fsum(generator.tolist()); ev['sum_generator2'] += math.fsum((generator ** 2).tolist())
    for label, mask in (('positive', generator > 0), ('negative', generator < 0), ('zero', generator == 0)):
        ev[label] += int(mask.sum())
    index, probability = weights.index, weights.probability
    met, met_phi = view.met_magnitude, view.met_phi
    if index is not None:
        # Enumerated subsets: counts become expected counts (sums of subset probabilities). The
        # squared weights of the subsets of one event are added as one correlated term below.
        base, met, met_phi = base[index], np.asarray(met)[index], np.asarray(met_phi)[index]
    w = base * weights.factor * _object_weights(plan, view, objects, index)
    if not np.isfinite(w).all():
        raise ValueError('combined event weight is not finite')
    rows_n = len(w)
    ctx = Context(objects, met, met_phi)
    if raw_chunk is not None:
        from .features import event_columns
        branch_variation = variation_spec['variation'] if variation_spec and variation_spec['kind'] == 'branch-variation' else None
        ctx.event = event_columns(plan, raw_chunk, view, branch_variation)

    def count(mask=None):
        if probability is None:
            return int(rows_n if mask is None else mask.sum())
        return float(probability.sum() if mask is None else probability[mask].sum())

    def squares(mask):
        if index is None:
            return float((w[mask] ** 2).sum())
        per_event = np.bincount(index[mask], weights=w[mask], minlength=n)
        return float((per_event ** 2).sum())

    for obs in plan.observables:
        values = evaluate(obs, ctx)
        undefined = np.isnan(values)
        acc['undefined_observables'][obs.name] += count(np.broadcast_to(undefined, (rows_n,)))
    entries = view.entries if index is None else view.entries[index]
    w *= _event_weight_factors(plan, ctx, entries, acc['event_weights'], variation_spec, file_index)
    masks = {}
    everything = np.ones(rows_n, bool)
    for region, cuts in plan.regions.items():
        mask = everything.copy()
        rows = acc['cutflows'][region]
        rows[0][0] += n; rows[0][1] += float(w.sum()); rows[0][2] += squares(everything)
        for k, (_, cut) in enumerate(cuts):
            namespace = ctx.values
            if getattr(cut, 'uses_event_fields', False):
                namespace = view.event if index is None else {k: np.asarray(v)[index] for k, v in view.event.items()}
            mask &= np.broadcast_to(np.asarray(cut.evaluate_cut(namespace), bool), (rows_n,))
            rows[k + 1][0] += count(mask); rows[k + 1][1] += float(w[mask].sum()); rows[k + 1][2] += squares(mask)
        masks[region] = mask
    if feature_collector is not None:
        feature_collector.append(ctx.values, ctx.event, w, masks[plan.features['region']])
    for h in plan.histograms:
        _fill(h, acc['histograms'][h.name], [ctx.values[o] for o in h.observables], w, masks[h.region],
              probability=probability, index=index)
    if record is not None:
        spec = plan.record
        take = min(spec['max_events'] - len(record), rows_n)
        for i in range(max(take, 0)):
            source = i if index is None else int(index[i])
            row = {'file_index': file_index, 'entry': int(view.entries[source]), 'weight': float(w[i])}
            if probability is not None:
                row['subset_probability'] = float(probability[i])
            for name in spec['observables']:
                value = float(ctx.values[name][i])
                row[name] = None if math.isnan(value) else value
            row['regions'] = [r for r in spec.get('regions', plan.regions) if masks[r][i]]
            record.append(row)
    return masks, w


def _fill(h, store, values, w, mask, *, probability=None, index=None):
    """Add one chunk to a histogram store.

    With enumerated subsets (``index`` maps rows to events) the entries are expected counts
    and each event's rows in one bin add as one correlated weight in sumw2.
    """
    rows = np.flatnonzero(mask)
    values = [np.asarray(v, float)[mask] for v in values]
    undefined = np.zeros(len(rows), bool)
    for v in values:
        undefined |= np.isnan(v)
    size = math.prod(h.shape)
    # Bin code per row: 0..size-1 inside, then underflow, overflow, outside and undefined slots.
    code = np.full(len(rows), size + 3, np.int64)
    defined = ~undefined
    if len(values) == 1:
        x, edges = values[0], h.edges[0]
        under = defined & (x < edges[0])
        over = defined & (x >= edges[-1])
        inside = defined & ~(under | over)
        code[under], code[over] = size, size + 1
        code[inside] = np.searchsorted(edges, x[inside], side='right') - 1
    else:
        outside = np.zeros(len(rows), bool)
        for x, edges in zip(values, h.edges):
            outside |= defined & ((x < edges[0]) | (x >= edges[-1]))
        inside = defined & ~outside
        code[outside] = size + 2
        if inside.any():
            indices = [np.searchsorted(edges, x[inside], side='right') - 1 for x, edges in zip(values, h.edges)]
            code[inside] = np.ravel_multi_index(indices, h.shape)
    weights = w[rows]
    slots = size + 4
    sumw = np.bincount(code, weights=weights, minlength=slots)
    if index is None:
        sumw2 = np.bincount(code, weights=weights * weights, minlength=slots)
        entries = np.bincount(code, minlength=slots).astype(np.int64)
    else:
        key = index[rows].astype(np.int64) * slots + code
        unique, inverse = np.unique(key, return_inverse=True)
        per_event = np.bincount(inverse, weights=weights, minlength=len(unique))
        sumw2 = np.bincount(unique % slots, weights=per_event * per_event, minlength=slots)
        entries = np.bincount(code, weights=probability[rows], minlength=slots)
    as_number = (lambda x: int(x)) if index is None else float
    for slot, name in ((size, 'underflow'), (size + 1, 'overflow'), (size + 2, 'outside'), (size + 3, 'undefined')):
        store[name][0] += as_number(entries[slot]); store[name][1] += float(sumw[slot]); store[name][2] += float(sumw2[slot])
    store['sumw'] = (np.asarray(store['sumw']) + sumw[:size]).tolist()
    store['sumw2'] = (np.asarray(store['sumw2']) + sumw2[:size]).tolist()
    if index is None:
        store['entries'] = (np.asarray(store['entries'], np.int64) + entries[:size]).tolist()
    else:
        store['entries'] = (np.asarray(store['entries'], float) + entries[:size]).tolist()


# ---------------------------------------------------------------- public API
def analyse(partition, plan, *, skim_dir=None):
    """Analyse a partition; a skim needs a new directory or RAVEL_OUTPUT_DIR."""
    from . import skim
    writer = None
    if plan.skim is not None:
        directory = skim_dir or os.environ.get('RAVEL_OUTPUT_DIR')
        if directory is None:
            raise ValueError('skim output needs skim_dir or RAVEL_OUTPUT_DIR')
        writer = skim.Writer(Path(directory) / 'skim', plan)
    started = time.perf_counter()
    try:
        result = _analyse(partition, plan, writer=writer)
        if writer is not None:
            result['skims'] = [writer.finish(result['inputs'])]
        if 'throughput' in result:
            result['throughput']['wall_seconds'] = time.perf_counter() - started
        return result
    finally:
        if writer is not None:
            writer.close()


def _analyse(partition, plan, *, writer):
    """Additive sums for one partition (see the module docstring)."""
    if not isinstance(partition, dict) or set(partition) - {'inputs', 'chunk_size'} or 'inputs' not in partition:
        raise ValueError('a partition has inputs and chunk_size')
    chunk = partition.get('chunk_size', 100_000)
    if type(chunk) is not int or chunk < 1:
        raise ValueError('chunk_size must be a positive integer')
    variations = {NOMINAL: None, **{s['name']: s for s in plan.systematics}}
    accs = {name: _empty_variation(plan) for name in variations}
    record = [] if plan.record is not None else None
    from .features import Collector
    feature_collector = Collector(plan.features) if plan.features else None
    inputs = []
    bytes_read, columns = 0, set()
    for item in partition['inputs']:
        if not isinstance(item, dict) or set(item) - {'path', 'file_index', 'entry_start', 'entry_stop', 'expected_entries', 'source_checksum'} or 'path' not in item:
            raise ValueError('each partition input has path, file_index and an optional entry range')
        remote = isinstance(item['path'], str) and item['path'].startswith('root://')
        path = item['path'] if remote else Path(item['path'])
        file_index = item.get('file_index', 0)
        if type(file_index) is not int or file_index < 0:
            raise ValueError('file_index must be a non-negative integer')
        if not remote and path.suffix.lower() == '.json':
            from . import skim
            if any(k in item for k in ('entry_start', 'entry_stop', 'expected_entries', 'source_checksum')):
                raise ValueError('skim manifest inputs consume the complete pinned population; entry ranges are not supported')
            source_hash = _sha256(path)
            document = json.loads(path.read_bytes())
            source_pins = (document['partitions'] if document.get('kind') == 'columnar-skim-manifest'
                           else [{'path': str(path), 'sha256': source_hash}])
            source_ranges = [r for pin in source_pins for i in json.loads(Path(pin['path']).read_bytes())['inputs']
                             for r in i.get('source_ranges', [i])]
            count = 0
            from ravel.validation.event_accounting import moments
            source_moments = moments([])
            for chunk_data, entries, original_index in skim.read_manifest(path, plan, chunk):
                view = plan.descriptor.view(chunk_data)
                view.entries = entries
                generator, _ = _weights_for(plan, view, None)
                observed = moments(generator.tolist())
                source_moments = {k: math.fsum([source_moments[k], observed[k]]) if k in ('sumw', 'sumw2')
                                  else source_moments[k] + observed[k] for k in observed}
                count += len(entries)
                bytes_read += chunk_data.extra['decoded_bytes_read']
                columns.update(chunk_data.extra['columns_read'])
                for name, spec in variations.items():
                    masks, weight = _accumulate(plan, view, accs[name], file_index=original_index,
                                                variation_name=name, variation_spec=spec,
                                                record=record if name == NOMINAL else None, raw_chunk=chunk_data,
                                                feature_collector=feature_collector if name == NOMINAL else None)
                    if name == NOMINAL and writer is not None:
                        writer.append(chunk_data, view, masks[plan.skim['region']], weight, original_index)
            if _sha256(path) != source_hash:
                raise ValueError('skim manifest changed during the pass')
            inputs.append({'path': str(path.resolve()), 'file_index': file_index, 'entry_start': 0,
                           'entry_stop': count, 'entries_in_file': count, 'sha256': source_hash,
                           'skim_manifest_sha256': source_hash, 'weight_moments': source_moments,
                           'source_ranges': source_ranges})
            continue
        report = plan.descriptor.check_file(path, variations=plan.variations, collections=plan.source_collections,
                                            event_fields=plan.event_fields)
        total = report['entries']
        if 'expected_entries' in item and total != item['expected_entries']:
            raise ValueError('dataset member event count differs from original membership')
        start = item.get('entry_start') or 0
        stop = total if item.get('entry_stop') is None else item['entry_stop']
        if type(start) is not int or type(stop) is not int or not 0 <= start <= stop <= total:
            raise ValueError(f'{path}: entry range {start}-{stop} is outside its {total} entries')
        entry = {'path': path if remote else str(path.resolve()), 'file_index': file_index, 'entry_start': start, 'entry_stop': stop,
                 'entries_in_file': total}
        if 'optional_weights_missing' in report:
            entry['optional_weights_missing'] = report['optional_weights_missing']
        if 'source_checksum' in item:
            checksum = item['source_checksum']; entry['source_checksum'] = checksum
            if not remote:
                if checksum['algorithm'] == 'sha256':
                    value = _sha256(path)
                else:
                    value = 1
                    with path.open('rb') as stream:
                        for block in iter(lambda: stream.read(1 << 20), b''):
                            value = zlib.adler32(block, value)
                    value = f'{value & 0xffffffff:08x}'
                if value != checksum['value']:
                    raise ValueError('dataset member checksum differs from original membership')
            entry['checksum_verified'] = not remote
        if (start == 0 or writer is not None or feature_collector is not None) and not remote:
            entry['sha256'] = _sha256(path)
        if writer is not None and remote and not item.get('source_checksum'):
            raise ValueError('remote skim input requires a declared source_checksum pin')
        if feature_collector is not None and remote and not item.get('source_checksum'):
            raise ValueError('remote feature input requires a declared source_checksum pin')
        from ravel.validation.event_accounting import moments
        entry['weight_moments'] = moments([])
        inputs.append(entry)
        if writer is not None:
            from .skim import source_chunks
            chunks = source_chunks(path, plan, step=chunk, entry_start=start, entry_stop=stop)
        else:
            chunks = plan.descriptor.read(path, collections=plan.source_collections, event_fields=plan.event_fields,
                                          step=chunk, entry_start=start, entry_stop=stop, variations=plan.variations)
        for chunk_data in chunks:
            if plan.descriptor.format == 'root':
                bytes_read += sum(a.nbytes for a in chunk_data.arrays.values())
                columns.update(chunk_data.arrays)
            for name, spec in variations.items():
                branch_variation = spec['variation'] if spec is not None and spec['kind'] == 'branch-variation' else None
                view = plan.descriptor.view(chunk_data, variation=branch_variation)
                if name == NOMINAL:
                    generator, _ = _weights_for(plan, view, None)
                    observed = moments(generator.tolist())
                    entry['weight_moments'] = {k: math.fsum([entry['weight_moments'][k], observed[k]])
                        if k in ('sumw', 'sumw2') else entry['weight_moments'][k] + observed[k] for k in observed}
                masks, weight = _accumulate(plan, view, accs[name], file_index=file_index, variation_name=name,
                                            variation_spec=spec, record=record if name == NOMINAL else None,
                                            raw_chunk=chunk_data,
                                            feature_collector=feature_collector if name == NOMINAL else None)
                if name == NOMINAL and writer is not None:
                    writer.append(chunk_data, view, masks[plan.skim['region']], weight, file_index)
        if (writer is not None or feature_collector is not None) and not remote and _sha256(path) != entry['sha256']:
            raise ValueError('columnar source checksum changed during the pass')
    result = {'schema_version': SCHEMA, 'kind': 'columnar-partial', 'plan_identity': plan.identity,
            'recipe_sha256': plan.recipe_sha256, 'inputs': inputs, 'variations': accs,
            'event_record': record, 'event_record_limit': None if plan.record is None else plan.record['max_events']}
    if feature_collector is not None:
        result['features'] = feature_collector.partial()
    if plan.descriptor.format == 'root':
        result['throughput'] = {'entries': accs[NOMINAL]['events']['n'], 'bytes_read': bytes_read,
                                'byte_basis': 'decoded-column-bytes', 'columns_read': sorted(columns)}
    return result


def _sum(a, b, label):
    if isinstance(a, dict):
        if set(a) != set(b):
            raise ValueError(f'partials have different {label} entries')
        return {k: _sum(a[k], b[k], f'{label}.{k}') for k in a}
    if isinstance(a, list):
        if len(a) != len(b):
            raise ValueError(f'partials have different {label} shapes')
        return [_sum(x, y, label) for x, y in zip(a, b)]
    return a + b


def merge(partials):
    """Add partial sums; refuses mixed plans and overlapping entry ranges."""
    partials = list(partials)
    if not partials:
        raise ValueError('nothing to merge')
    first = partials[0]
    for p in partials:
        if p.get('kind') != 'columnar-partial' or p.get('schema_version') != SCHEMA:
            raise ValueError('only columnar partial results can be merged')
        if p['plan_identity'] != first['plan_identity']:
            raise ValueError('partials come from different recipes, descriptors or efficiency maps')
    inputs = [i for p in partials for i in p['inputs']]
    by_file = {}
    for item in inputs:
        by_file.setdefault((item['path'], item['file_index']), []).append(item)
    indices = {}
    for (path, index), items in by_file.items():
        if indices.setdefault(index, path) != path:
            raise ValueError(f'file_index {index} is used for two different files')
        ranges = sorted((i['entry_start'], i['entry_stop']) for i in items)
        for (a1, b1), (a2, b2) in zip(ranges, ranges[1:]):
            if a2 < b1:
                raise ValueError(f'{path}: entry ranges {a1}-{b1} and {a2}-{b2} overlap')
        hashes = {i['sha256'] for i in items if 'sha256' in i}
        if len(hashes) > 1:
            raise ValueError(f'{path}: partitions saw different file contents')
    variations = first['variations']
    for p in partials[1:]:
        variations = _sum(variations, p['variations'], 'variations')
    record, limit = None, first.get('event_record_limit')
    if first.get('event_record') is not None:
        rows = sorted((r for p in partials for r in p['event_record']), key=lambda r: (r['file_index'], r['entry']))
        record = rows[:limit]
    result = {'schema_version': SCHEMA, 'kind': 'columnar-partial', 'plan_identity': first['plan_identity'],
            'recipe_sha256': first['recipe_sha256'], 'inputs': inputs, 'variations': variations, 'event_record': record,
            'event_record_limit': limit}
    pins = [pin for p in partials for pin in p.get('skims', [])]
    if any('features' in p for p in partials):
        from .features import merge as merge_features
        if not all('features' in p for p in partials):
            raise ValueError('every feature partial must carry a population')
        result['features'] = merge_features(p['features'] for p in partials)
    if pins:
        from .skim import merge as merge_skims, validate_partition
        for p in partials:
            if not p.get('skims'):
                raise ValueError('every skim partial must carry partition custody pins')
            custody_inputs = [i for pin in p['skims'] for i in validate_partition(pin)['inputs']]
            key = lambda i: json.dumps(i, sort_keys=True)
            if sorted(custody_inputs, key=key) != sorted(p['inputs'], key=key):
                raise ValueError('skim custody inputs differ from partial inputs')
        result['skim_manifest'] = merge_skims(pins)
        result['skims'] = pins
    return result


# ---------------------------------------------------------------- normalisation
def _coverage(inputs):
    files = {}
    for item in inputs:
        files.setdefault((item['path'], item['file_index']), {'entries': item['entries_in_file'], 'ranges': [], 'sha256': None})
        f = files[(item['path'], item['file_index'])]
        f['ranges'].append((item['entry_start'], item['entry_stop']))
        if 'optional_weights_missing' in item:
            missing = item['optional_weights_missing']
            if 'optional_weights_missing' in f and f['optional_weights_missing'] != missing:
                raise ValueError('optional weight availability differs between partitions of one file')
            f['optional_weights_missing'] = missing
        if 'sha256' in item:
            f['sha256'] = item['sha256']
        if 'source_checksum' in item:
            identity = {'source_checksum': item['source_checksum'], 'checksum_verified': item['checksum_verified']}
            if any(key in f and f[key] != value for key, value in identity.items()):
                raise ValueError('dataset member checksum evidence differs between partitions')
            f.update(identity)
    out = []
    for (path, index), f in sorted(files.items(), key=lambda kv: kv[0][1]):
        ranges = sorted(f['ranges'])
        covered = sum(b - a for a, b in ranges)
        complete = covered == f['entries'] and ranges[0][0] == 0 and all(b1 == a2 for (_, b1), (a2, _) in zip(ranges, ranges[1:]))
        out.append({'path': path, 'file_index': index, 'entries_in_file': f['entries'], 'entries_read': covered,
                    'complete': complete, 'sha256': f['sha256'],
                    **{key: f[key] for key in ('source_checksum', 'checksum_verified', 'optional_weights_missing') if key in f}})
    return out


def _pointer(document, pointer):
    value = document
    for part in pointer.lstrip('/').split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def _ledger_split(ledger):
    """(sigma x k in pb, prod(BR) x filter, record) from a normalization ledger."""
    from ravel.physics import normalization_ledger as nl
    ledger = {k: v for k, v in ledger.items() if k != 'applied_sigma_pb'}
    nl.validate(ledger)
    f = nl.factors(ledger)
    record = {'sample': ledger['sample'], 'sigma_pb': f['sigma_pb'], 'k': f['k'], 'br_product': f['br_product'],
              'filter': f['filter'], 'applied_sigma_pb': nl.applied_sigma_pb(ledger),
              'sigma_convention': {k: ledger['sigma'][k] for k in ('order', 'tool', 'pdf', 'scales', 'process_basis')},
              'sigma_source': ledger['sigma']['source'], 'ledger': ledger}
    return f['sigma_pb'] * f['k'], f['br_product'] * f['filter'], record


def _declared_cross_section(xs, base):
    """Cross section, factor and provenance from a production receipt, a ledger or the registry.

    ``{"production_receipt": path}`` reads the receipt's ``sigma`` block: when it embeds a
    normalization ledger, sigma x k is the cross section and prod(BR) x filter the factor
    (they must reproduce the receipt's applied value). ``{"normalization_ledger": path}``
    splits a ledger file the same way and ``{"cross_section_registry": request}`` looks the
    value up in the pinned cross-section registry.
    """
    def read(path):
        path = Path(path)
        path = path if path.is_absolute() or base is None else Path(base) / path
        raw = path.read_bytes()
        return json.loads(raw), {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest()}
    if set(xs) == {'cross_section_result'}:
        pin = xs['cross_section_result']
        if type(pin) is not dict or set(pin) != {'path', 'sha256'}:
            raise ValueError('cross_section_result requires a path and sha256 pin')
        document, actual = read(pin['path'])
        if actual['sha256'] != pin['sha256']:
            raise ValueError('cross_section_result pin sha256 differs')
        if document.get('kind') != 'cross-section' or document.get('schema_version') != 1 or document.get('status') != 'passed':
            raise ValueError('passed cross-section result kind and schema_version 1 required')
        found = document['cross_section']
        from ravel.physics.normalization_ledger import from_cross_section
        convention = from_cross_section(found)
        return found['sigma_pb'], 1., {'cross_section_result': actual, 'convention': found['convention'],
                                     'basis': found['basis'], 'sigma': convention}
    if set(xs) == {'production_receipt'}:
        receipt, pin = read(xs['production_receipt'])
        sigma = receipt.get('sigma') if isinstance(receipt, dict) else None
        if not isinstance(sigma, dict) or type(sigma.get('value_pb')) not in (int, float):
            raise ValueError('the production receipt has no sigma block with value_pb')
        source = {'production_receipt': pin['path'], 'pointer': '/sigma', 'sha256': pin['sha256']}
        if 'normalization_ledger' in sigma:
            value, factor, record = _ledger_split(sigma['normalization_ledger'])
            if not math.isclose(value * factor, sigma['value_pb'], rel_tol=1e-12):
                raise ValueError('the receipt cross section differs from its normalization ledger (sigma x k x BR x filter)')
            return value, factor, {**source, 'normalization_ledger': record}
        if 'cross_section_lookup' in sigma:
            source['cross_section_registry'] = sigma['cross_section_lookup'].get('table')
        if 'generation_receipt' in sigma:
            source['generation_receipt'] = sigma['generation_receipt']
        return float(sigma['value_pb']), 1.0, source
    if set(xs) == {'normalization_ledger'}:
        ledger, pin = read(xs['normalization_ledger'])
        value, factor, record = _ledger_split(ledger)
        return value, factor, {'normalization_ledger': {**pin, **record}}
    if set(xs) == {'cross_section_registry'}:
        from ravel.physics import cross_sections
        found = cross_sections.lookup(xs['cross_section_registry'])
        return found['sigma_pb'], 1.0, {'cross_section_registry': {'table': found['table'], 'convention': found['convention'],
                                                                    'interpolation': found['interpolation'],
                                                                    'request': xs['cross_section_registry']}}
    return None


def resolve_normalization(spec, merged, plan, *, input_files=None, base=None, variation=NOMINAL):
    """The scale from weighted sums to yields, with every value and its source."""
    if not isinstance(spec, dict) or spec.get('mode') not in ('cross-section', 'event-weights-in-pb', 'none'):
        raise ValueError('normalization mode must be cross-section, event-weights-in-pb or none')
    events = merged['variations'][variation]['events']
    coverage = _coverage(merged['inputs'])
    if spec['mode'] == 'none':
        if set(spec) != {'mode'}:
            raise ValueError('normalization none takes no other keys')
        return {'mode': 'none', 'scale': 1.0, 'unit': 'sum of event weights', 'coverage': coverage}
    allowed = {'mode', 'luminosity_ifb', 'luminosity_source', 'factor'}
    if spec['mode'] == 'cross-section':
        allowed |= {'cross_section_pb', 'cross_section_source', 'sum_of_weights', 'sum_of_weights_source'}
    else:
        allowed |= {'divide_by', 'event_count', 'event_count_source'}
    if set(spec) - allowed:
        raise ValueError(f'normalization {spec["mode"]} accepts only {sorted(allowed)}')
    lumi = spec.get('luminosity_ifb')
    if type(lumi) not in (int, float) or not lumi > 0 or not isinstance(spec.get('luminosity_source'), str) or not spec['luminosity_source'].strip():
        raise ValueError('normalization needs a positive luminosity_ifb and its luminosity_source')
    factor = 1.0
    if 'factor' in spec:
        f = spec['factor']
        if not isinstance(f, dict) or set(f) != {'value', 'source'} or type(f['value']) not in (int, float) or not f['value'] > 0:
            raise ValueError('factor needs a positive value and its source')
        factor = float(f['value'])
    out = {'mode': spec['mode'], 'luminosity_ifb': float(lumi), 'luminosity_source': spec['luminosity_source'],
           'factor': spec.get('factor'), 'coverage': coverage, 'unit': 'events'}

    def complete_or_refuse():
        if any('skim_manifest_sha256' in item for item in merged['inputs']):
            raise ValueError('normalization of skim inputs requires an explicit original-population denominator')
        missing = [c for c in coverage if not c['complete']]
        if missing:
            raise ValueError(f'normalisation by all input events needs every entry of every file; {missing[0]["path"]} '
                             f'has {missing[0]["entries_read"]} of {missing[0]["entries_in_file"]} read')
    if spec['mode'] == 'cross-section':
        xs = spec.get('cross_section_pb')
        if not isinstance(spec.get('cross_section_source'), str) or not spec['cross_section_source'].strip():
            raise ValueError('cross-section normalisation needs cross_section_source')
        if isinstance(xs, dict) and set(xs) == {'lhe_init'} and xs['lhe_init'] is True:
            if plan.descriptor.format != 'lhe' or not input_files:
                raise ValueError('a cross section from the LHE init block needs LHE input files')
            values = {plan.descriptor.check_file(p)['cross_section_pb'] for p in input_files}
            if len(values) != 1 or None in values:
                raise ValueError('the LHE files do not state one common cross section')
            xs = values.pop()
            out['cross_section_from'] = 'LHE init block (sum of XSECUP)'
        elif isinstance(xs, dict) and set(xs) == {'production_receipt', 'pointer'}:
            receipt = Path(xs['production_receipt'])
            receipt = receipt if receipt.is_absolute() or base is None else Path(base) / receipt
            raw = receipt.read_bytes()
            xs_value = _pointer(json.loads(raw), xs['pointer'])
            out['cross_section_from'] = {'production_receipt': str(receipt.resolve()), 'pointer': xs['pointer'],
                                         'sha256': hashlib.sha256(raw).hexdigest()}
            xs = xs_value
        elif isinstance(xs, dict):
            declared = _declared_cross_section(xs, base)
            if declared is None:
                raise ValueError('cross_section_pb sources are {"lhe_init": true}, {"production_receipt", "pointer"}, '
                                 '{"production_receipt"}, {"normalization_ledger"} or {"cross_section_registry"}')
            xs, ledger_factor, out['cross_section_from'] = declared
            if ledger_factor != 1.0:
                if 'factor' in spec:
                    raise ValueError('the normalization ledger already carries prod(BR) x filter; a declared factor '
                                     'would apply them twice')
                factor = ledger_factor
                out['factor'] = {'value': ledger_factor, 'source': 'normalization ledger: branching fractions x filter efficiency'}
        if type(xs) not in (int, float) or not xs > 0:
            raise ValueError('cross_section_pb must be a positive number, {"lhe_init": true} or a production-receipt pointer')
        total = spec.get('sum_of_weights')
        if total == 'all-input-events':
            complete_or_refuse()
            total = events['sum_generator']
            out['sum_of_weights_from'] = 'sum of generator weights over every input event'
        elif type(total) in (int, float) and total > 0:
            if not isinstance(spec.get('sum_of_weights_source'), str) or not spec['sum_of_weights_source'].strip():
                raise ValueError('a declared sum_of_weights needs sum_of_weights_source')
            out['sum_of_weights_from'] = spec['sum_of_weights_source']
        else:
            raise ValueError('sum_of_weights must be "all-input-events" or a positive declared number')
        if not total > 0:
            raise ValueError('the sum of generator weights is not positive')
        out.update(cross_section_pb=float(xs), cross_section_source=spec['cross_section_source'], sum_of_weights=float(total),
                   scale=float(xs) * 1000.0 * float(lumi) * factor / float(total))
    else:
        divide = spec.get('divide_by')
        if divide not in ('event-count', 'none'):
            raise ValueError('event-weights-in-pb needs divide_by event-count or none')
        count = 1.0
        if divide == 'event-count':
            declared = spec.get('event_count', 'all-input-events')
            if declared == 'all-input-events':
                complete_or_refuse()
                count = float(events['n'])
                out['event_count_from'] = 'number of input events'
            elif type(declared) is int and declared > 0 and isinstance(spec.get('event_count_source'), str):
                count = float(declared)
                out['event_count_from'] = spec['event_count_source']
            else:
                raise ValueError('event_count must be "all-input-events" or a positive integer with event_count_source')
        out.update(divide_by=divide, event_count=count, scale=1000.0 * float(lumi) * factor / count)
    return out


# ---------------------------------------------------------------- finalisation
def _histogram_result(h, store, scale, value_unit_default):
    sumw, sumw2 = np.asarray(store['sumw'], float), np.asarray(store['sumw2'], float)
    over, under = store['overflow'], store['underflow']
    volumes = np.ones(math.prod(h.shape))
    for axis, edges in enumerate(h.edges):
        widths = np.diff(edges)
        shape = [1] * len(h.shape); shape[axis] = len(widths)
        volumes = volumes * np.broadcast_to(widths.reshape(shape), h.shape).ravel()
    if h.slice_width is not None:
        volumes = volumes * h.slice_width
    norm = h.normalization
    flows = {'overflow': over[1], 'underflow': under[1], 'overflow_sumw2': over[2], 'underflow_sumw2': under[2]}
    fold_over, fold_under = h.overflow == 'last-bin', h.underflow == 'first-bin'
    content, content2 = sumw.copy(), sumw2.copy()
    if fold_over:
        content[-1] += over[1]; content2[-1] += over[2]
    if fold_under:
        content[0] += under[1]; content2[0] += under[2]
    representation = 'integrated'
    if norm in ('yield', 'raw', 'yield-per-width'):
        s = scale if norm != 'raw' else 1.0
        values, errors = s * content, s * np.sqrt(content2)
        over_v, under_v = s * over[1], s * under[1]
        unit = 'events' if norm != 'raw' else 'sum of event weights'
        if norm == 'yield-per-width':
            values, errors = values / volumes, errors / volumes
            representation = 'differential'
            unit = 'events/' + '/'.join(h.units) if len(h.units) == 1 else 'events per bin volume'
    else:
        total = sumw.sum() + (over[1] + under[1] + store['outside'][1] if h.fraction_denominator == 'all' else 0.0)
        total2 = sumw2.sum() + (over[2] + under[2] + store['outside'][2] if h.fraction_denominator == 'all' else 0.0)
        if not total > 0:
            raise ValueError(f'histogram {h.name!r}: the fraction denominator is not positive')
        f = content / total
        var = (content2 * (1 - 2 * f) + f * f * total2) / (total * total)
        values, errors = f, np.sqrt(np.maximum(var, 0.0))
        over_v, under_v = over[1] / total, under[1] / total
        unit = 'fraction of events'
        if norm == 'density':
            values, errors = values / volumes, errors / volumes
            representation = 'differential'
            unit = '1/' + h.units[0] if len(h.units) == 1 else 'per bin volume'
    unit = h.value_unit or unit
    bins = []
    for flat in range(len(values)):
        idx = np.unravel_index(flat, h.shape)
        bins.append({'low': [float(h.edges[a][i]) for a, i in enumerate(idx)],
                     'high': [float(h.edges[a][i + 1]) for a, i in enumerate(idx)],
                     'value': float(values[flat]), 'uncertainty': float(errors[flat])})
    doc = {'schema_version': 1, 'kind': 'binned_values',
           'quantity': {'weight_convention': 'signed'},
           'axes': [{'name': label, 'unit': unit_} for label, unit_ in zip(h.labels, h.units)],
           'unit': unit, 'representation': representation, 'bins': bins,
           'description': f'{h.name}: {h.normalization} in region {h.region}; uncertainty is the Monte Carlo statistical '
                          'uncertainty; bins are low-inclusive.'}
    # These are finalized yields, even if a numerical scale happens to be one.
    doc['normalization'] = {'kind': 'normalized', 'scale': scale, 'histogram_mode': h.normalization}
    doc['provenance'] = {'raw_sumw': sumw.tolist(), 'raw_sumw2': sumw2.tolist()}
    doc['sumw2'] = [b['uncertainty'] ** 2 for b in bins]
    if len(h.shape) == 1 and representation == 'integrated':
        if fold_over:
            doc['overflow_in_last_bin'] = True
        else:
            doc['overflow'] = float(over_v)
        if fold_under:
            doc['underflow_in_first_bin'] = True
        else:
            doc['underflow'] = float(under_v)
    rel = np.where(sumw > 0, np.sqrt(sumw2) / np.where(sumw > 0, sumw, 1.0), np.nan)
    precision = {'target': h.precision_target, 'relative_uncertainty': [None if math.isnan(x) else float(x) for x in rel],
                 'effective_entries': [float(a * a / b) if b > 0 else 0.0 for a, b in zip(sumw, sumw2)]}
    if h.precision_target is not None:
        precision['bins_above_target'] = [i for i, x in enumerate(rel) if math.isnan(x) or x > h.precision_target]
    summary = {'sumw': sumw.tolist(), 'sumw2': sumw2.tolist(), 'entries': store['entries'],
               'underflow': {'entries': under[0], 'sumw': under[1], 'sumw2': under[2]},
               'overflow': {'entries': over[0], 'sumw': over[1], 'sumw2': over[2]},
               'outside': {'entries': store['outside'][0], 'sumw': store['outside'][1], 'sumw2': store['outside'][2]},
               'undefined': {'entries': store['undefined'][0], 'sumw': store['undefined'][1], 'sumw2': store['undefined'][2]},
               'values': values.tolist(), 'uncertainties': errors.tolist(), 'unit': unit, 'mc_precision': precision}
    return doc, summary


def _write(path, document, files, out_dir):
    raw = (json.dumps(document, indent=2, sort_keys=False, allow_nan=False) + '\n').encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
    files.append({'path': path.relative_to(out_dir).as_posix(), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)})


def finalize(merged, plan, normalization, *, out_dir, input_files=None, base=None):
    """Write the governed outputs into a new directory and return the summary."""
    if merged.get('plan_identity') != plan.identity:
        raise ValueError('the partial results were not produced by this recipe, descriptor and maps')
    accounting = _event_accounting(merged)
    if accounting.get('passed') is False:
        raise ValueError('event_accounting refused: input counts or signed moments differ from the analysis accumulator')
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=False)
    files = []
    if plan.features is not None:
        from .features import write as write_features
        if 'features' not in merged or merged['features']['spec'] != plan.features:
            raise ValueError('feature partial does not match the compiled recipe')
        for path in write_features(merged['features'], out_dir, inputs=merged['inputs'], recipe_sha256=plan.recipe_sha256):
            files.append({'path': path.name, 'sha256': _sha256(path), 'size': path.stat().st_size})
    if merged.get('skims'):
        from .skim import merge as merge_skims
        _write(out_dir / 'skim-manifest.json', merge_skims(merged['skims']), files, out_dir)
    norms = {}
    for name in merged['variations']:
        spec = next((s for s in plan.systematics if s['name'] == name), None)
        use = NOMINAL if spec is not None and spec['kind'] == 'weight-factor' and spec.get('sum_of_weights') == 'nominal' else name
        if spec is not None and spec['kind'] != 'weight-factor':
            use = NOMINAL
        norms[name] = resolve_normalization(normalization, merged, plan, input_files=input_files, base=base, variation=use)
    nominal_norm = norms[NOMINAL]
    histograms = {}
    for h in plan.histograms:
        entry = {'region': h.region, 'observables': h.observables, 'normalization': h.normalization,
                 'overflow_convention': h.overflow, 'underflow_convention': h.underflow,
                 'variations': [v for v in merged['variations'] if v != NOMINAL]}
        for variation, acc in merged['variations'].items():
            doc, summary = _histogram_result(h, acc['histograms'][h.name], norms[variation]['scale'], None)
            stem = slug(h.name) + ('' if variation == NOMINAL else '__' + slug(variation))
            _write(out_dir / 'histograms' / f'{stem}.json', doc, files, out_dir)
            summary['file'] = f'histograms/{stem}.json'
            entry[variation] = summary
        histograms[h.name] = entry
    regions_out = {}
    for variation, acc in merged['variations'].items():
        scale = norms[variation]['scale']
        regions_out[variation] = [
            {'name': region, 'cuts': [
                {'name': name, 'expression': expr, 'raw': row[0], 'sumw': row[1], 'sumw2': row[2],
                 'yield': scale * row[1], 'yield_uncertainty': scale * math.sqrt(row[2])}
                for (name, expr), row in zip([('all events', None)] + [(c[0], c[1].text) for c in cuts],
                                             acc['cutflows'][region])]}
            for region, cuts in plan.regions.items()]
    cutflow = {'schema_version': 1, 'kind': 'cutflow', 'quantity': {'weight_convention': 'signed'}, 'recipe': plan.doc['name'], 'unit': nominal_norm['unit'],
               'normalization_scale': nominal_norm['scale'], 'regions': regions_out[NOMINAL],
               'note': 'Rows are cumulative: each cut applies after all earlier cuts of its region.'}
    _write(out_dir / 'cutflow.json', cutflow, files, out_dir)
    record = merged.get('event_record')
    if plan.record is not None and record is not None:
        rows = record[:plan.record['max_events']]
        raw = ''.join(json.dumps(r, allow_nan=False) + '\n' for r in rows).encode()
        with (out_dir / 'event-record.jsonl').open('xb') as stream:
            stream.write(raw)
        files.append({'path': 'event-record.jsonl', 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)})
    descriptor = plan.descriptor
    provenance = {
        'recipe_sha256': plan.recipe_sha256, 'plan_identity': plan.identity,
        'descriptor': {'name': descriptor.doc['name'], 'sha256': descriptor.sha256, 'origin': descriptor.origin},
        'efficiency_maps': {k: m.provenance for k, m in plan.maps.items()},
        'detector_card_check': plan.card_report,
        'expected_counts': any(s.spec['application'] == 'enumerate' for s in plan.steps if s.kind == 'efficiency'),
        'inputs': nominal_norm['coverage'], 'engine': engine_version(),
        'bin_convention': 'bins are low-inclusive [low, high); a value equal to the last edge is overflow'}
    result = {
        'schema_version': 1, 'kind': 'columnar-analysis-result', 'recipe': plan.doc['name'],
        'normalization': nominal_norm, 'variation_normalizations': {k: v for k, v in norms.items() if k != NOMINAL},
        'events': merged['variations'][NOMINAL]['events'],
        'cutflows': regions_out, 'histograms': histograms,
        'efficiency': {k: v['efficiency'] for k, v in merged['variations'].items()},
        'event_weights': {k: v['event_weights'] for k, v in merged['variations'].items()},
        'undefined_observables': merged['variations'][NOMINAL]['undefined_observables'],
        'systematics': plan.systematics, 'provenance': provenance, 'files': files,
        'physics_validated': False,
        'scope': 'Declared selection, histograms and normalisation applied to the supplied events. Detector '
                 'fidelity, generator accuracy and agreement with any published result are not established here.'}
    from ravel.physics.yield_hub import columnar_delivery_checks
    result['check_results'] = columnar_delivery_checks(out_dir, normalization, nominal_norm, merged, regions_out[NOMINAL], base)
    result['event_accounting'] = accounting
    raw = (json.dumps(result, indent=2, allow_nan=False) + '\n').encode()
    with (out_dir / 'analysis-result.json').open('xb') as stream:
        stream.write(raw)
    result['result_sha256'] = hashlib.sha256(raw).hexdigest()
    return result


def _event_accounting(merged):
    from ravel.validation.event_accounting import check, FIELDS
    inputs = merged['inputs']; events = merged['variations'][NOMINAL]['events']
    if any('weight_moments' not in row for row in inputs) or any(k not in events for k in ('positive', 'negative', 'zero')):
        return {'check': 'event_accounting', 'status': 'missing_input', 'passed': None,
                'detail': 'legacy partial lacks independently retained source signed moments'}
    source = {k: math.fsum(row['weight_moments'][k] for row in inputs) if k in ('sumw', 'sumw2')
              else sum(row['weight_moments'][k] for row in inputs) for k in FIELDS}
    source['count'] = sum(row['entry_stop'] - row['entry_start'] for row in inputs)
    output = {'count': events['n'], 'sumw': events['sum_generator'], 'sumw2': events['sum_generator2'],
              **{k: events[k] for k in ('positive', 'negative', 'zero')}}
    try:
        return check({'schema_version': 1, 'input': source, 'output': output, 'transformation': {'kind': 'identity'}})
    except ValueError as exc:
        raise ValueError('event_accounting refused: ' + str(exc)) from exc
