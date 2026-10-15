"""Bounded feature populations and pinned, held-out NumPy model predictions.

Population labels are sample-role metadata, never truth columns. Weighted exports
retain their magnitudes and explicitly require the ML weighted qualification route.
"""
from __future__ import annotations

import hashlib
import heapq
import io
import json
from pathlib import Path
import zipfile

import awkward as ak
import numpy as np

MAX_EVENTS = 100_000
MAX_BYTES = 64 * 1024**2


def _keys(spec, required, optional=()):
    if not isinstance(spec, dict) or set(required) - spec.keys() or spec.keys() - set(required) - set(optional):
        raise ValueError(f'feature contract requires {required}; optional {optional}')


def _folds(spec):
    _keys(spec, ('k', 'salt'))
    if type(spec['k']) is not int or not 2 <= spec['k'] <= 100 or not isinstance(spec['salt'], str) or not spec['salt']:
        raise ValueError('folds require k from 2 to 100 and a nonempty salt')


def compile_features(spec, descriptor, regions, names, steps):
    _keys(spec, ('region', 'observables', 'label', 'event_id', 'group_id', 'max_events', 'sampling_seed', 'weight_policy'), ('folds',))
    if not isinstance(spec['region'], str) or spec['region'] not in regions:
        raise ValueError('features.region must name a declared region')
    obs = spec['observables']
    if not isinstance(obs, list) or not obs or any(not isinstance(n, str) or n not in names for n in obs) or len(set(obs)) != len(obs):
        raise ValueError('features.observables must be unique declared observables')
    if not isinstance(spec['label'], str) or not spec['label'].strip():
        raise ValueError('features.label must declare a sample role')
    for key in ('event_id', 'group_id'):
        if not isinstance(spec[key], str) or spec[key] not in descriptor.event:
            raise ValueError(f'features.{key} must name a declared event field')
    if type(spec['max_events']) is not int or not 3 <= spec['max_events'] <= MAX_EVENTS:
        raise ValueError('features.max_events must be from 3 to 100000')
    if type(spec['sampling_seed']) is not int:
        raise ValueError('features.sampling_seed must be an integer')
    policy = spec['weight_policy']
    _keys(policy, ('negative', 'unequal'))
    if policy['negative'] not in ('refuse', 'drop', 'absolute') or policy['unequal'] not in ('refuse', 'weighted-qualification'):
        raise ValueError('weight_policy requires negative refuse/drop/absolute and unequal refuse/weighted-qualification')
    if any(s.kind == 'efficiency' and s.spec.get('application') == 'enumerate' for s in steps):
        raise ValueError('features refuse enumerated replicas of an event')
    result = json.loads(json.dumps(spec))
    result.setdefault('folds', {'k': 5, 'salt': 'features-v1'})
    _folds(result['folds'])
    return result


def identities(values):
    """Canonical integer/string IDs; refuse float identities that may have rounded."""
    a = np.asarray(values)
    if np.ma.isMaskedArray(values) and np.any(values.mask):
        raise ValueError('missing event/group identity')
    if a.ndim != 1:
        raise ValueError('event/group identity must be a scalar column')
    if a.dtype.kind == 'f':
        if not np.all(np.isfinite(a)) or np.any(a != np.floor(a)) or np.any(np.abs(a) >= 2**53):
            raise ValueError('event/group identity must be an exact integer or string')
        a = a.astype(np.int64)
    if a.dtype.kind not in 'iuUS':
        raise ValueError('event/group identity must be an exact integer or string')
    a = a.astype(str)
    if np.any(a == ''):
        raise ValueError('empty event/group identity')
    return a


def event_columns(plan, chunk, view, variation=None):
    """Preserve raw ROOT identity precision without changing the format reader."""
    fields = set()
    if plan.features:
        fields.update(plan.features[k] for k in ('event_id', 'group_id'))
    fields.update(o.spec['group_id'] for o in plan.observables if o.op == 'model_score')
    result = {}
    for field in fields:
        spec = plan.descriptor.event[field]
        if plan.descriptor.format == 'root' and 'branch' in spec:
            if spec['scale'] != 1:
                raise ValueError('identity fields cannot be scaled')
            raw = chunk.arrays[plan.descriptor._branch(spec['branch'], variation, chunk.available)]
            if spec['reduce'] == 'first':
                raw = ak.firsts(raw)
            result[field] = identities(ak.to_numpy(raw))
        else:
            result[field] = identities(view.event[field])
    return result


def _arrays(rows, width):
    return {'x': np.array([r[3] for r in rows], dtype=float).reshape(len(rows), width),
            'region': np.zeros(len(rows), dtype=np.int64),
            'weight': np.array([r[4] for r in rows], dtype=float),
            'event_id': np.array([r[1] for r in rows], dtype=str),
            'group_id': np.array([r[2] for r in rows], dtype=str)}


def _population_bytes(arrays):
    buf = io.BytesIO()
    np.savez(buf, **arrays)
    raw = buf.getvalue()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        expanded = sum(i.file_size for i in z.infolist())
    return raw, expanded


class Collector:
    """Keep the lowest seeded identity hashes, independent of chunks and merges."""
    def __init__(self, spec):
        self.spec = spec
        self.heap = []
        self.counts = dict(selected=0, negative=0, dropped_negative=0, eligible=0)
        self.weight_min = self.weight_max = None

    def _offer(self, event, group, x, weight):
        rank = int(hashlib.sha256(f'{self.spec["sampling_seed"]}:{event}'.encode()).hexdigest(), 16)
        row = (-rank, str(event), str(group), list(x), float(weight))
        if len(self.heap) < self.spec['max_events']:
            heapq.heappush(self.heap, row)
        elif row > self.heap[0]:
            heapq.heapreplace(self.heap, row)

    def append(self, values, event, weight, mask):
        s = self.spec
        w = np.asarray(weight, float)[mask]
        x = np.column_stack([values[o][mask] for o in s['observables']])
        ids = identities(event[s['event_id']])[mask]
        groups = identities(event[s['group_id']])[mask]
        if not np.all(np.isfinite(x)) or not np.all(np.isfinite(w)):
            raise ValueError('features and weights must be finite in the selected region')
        self.counts['selected'] += len(w)
        negative = w < 0
        self.counts['negative'] += int(negative.sum())
        policy = s['weight_policy']
        if negative.any() and policy['negative'] == 'refuse':
            raise ValueError('negative feature weights refused by declared policy')
        if np.any(w == 0):
            raise ValueError('zero feature weights refused by ML population contract')
        keep = ~negative if policy['negative'] == 'drop' else np.ones(len(w), bool)
        self.counts['dropped_negative'] += int((~keep).sum())
        w = np.abs(w[keep])
        self.counts['eligible'] += len(w)
        if len(w):
            self.weight_min = float(w.min()) if self.weight_min is None else min(self.weight_min, float(w.min()))
            self.weight_max = float(w.max()) if self.weight_max is None else max(self.weight_max, float(w.max()))
            self._check_weights()
        for eid, gid, row, value in zip(ids[keep], groups[keep], x[keep], w):
            self._offer(eid, gid, row, value)

    def _check_weights(self):
        if self.spec['weight_policy']['unequal'] == 'refuse' and self.weight_min != self.weight_max:
            raise ValueError('unequal feature weights require weighted-qualification')

    def partial(self):
        return {'spec': self.spec, 'counts': self.counts, 'weight_min': self.weight_min,
                'weight_max': self.weight_max,
                'rows': [[str(-r[0]), *r[1:]] for r in sorted(self.heap, reverse=True)]}


def merge(populations):
    first, *rest = list(populations)
    collector = Collector(first['spec'])
    for p in (first, *rest):
        if p['spec'] != collector.spec:
            raise ValueError('feature populations have different contracts')
        for k in collector.counts:
            collector.counts[k] += p['counts'][k]
        if p['weight_min'] is not None:
            collector.weight_min = p['weight_min'] if collector.weight_min is None else min(collector.weight_min, p['weight_min'])
            collector.weight_max = p['weight_max'] if collector.weight_max is None else max(collector.weight_max, p['weight_max'])
        for _, eid, gid, x, w in p['rows']:
            collector._offer(eid, gid, x, w)
    collector._check_weights()
    return collector.partial()


def write(population, directory, *, inputs, recipe_sha256):
    """Write the exact five-array loader schema and a separately pinned sidecar."""
    from ravel.physics.ml_crossfit import fold_map, load_events
    p = merge([population])
    rows = p['rows']
    # Keep a prefix in hash order, including when the byte bound is tighter than N.
    width = len(p['spec']['observables'])
    arrays = _arrays(rows, width)
    if sum(a.nbytes for a in arrays.values()) > MAX_BYTES - 4096:
        used = 0
        for i, row in enumerate(rows):
            used += width * 8 + 16 + 4 * (arrays['event_id'].dtype.itemsize // 4 + arrays['group_id'].dtype.itemsize // 4)
            if used > MAX_BYTES - 4096:
                rows = rows[:i]
                break
        arrays = _arrays(rows, width)
    if len(rows) < 3:
        raise ValueError('bounded feature population requires at least three eligible events')
    if len(set(arrays['event_id'])) != len(rows):
        raise ValueError('duplicate event identity in feature population')
    raw, expanded = _population_bytes(arrays)
    if expanded > MAX_BYTES or len(raw) > MAX_BYTES:
        raise ValueError('feature population exceeds 64 MiB')
    directory = Path(directory)
    path = directory / 'features.npz'
    pin = {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest()}
    with path.open('xb') as f:
        f.write(raw)
    try:
        load_events(pin, directory, width,
                    allow_sampling_weights=p['spec']['weight_policy']['unequal'] == 'weighted-qualification')
    except Exception:
        path.unlink()
        raise
    groups = np.unique(arrays['group_id'])
    folds = p['spec']['folds']
    meta = {'schema_version': 1, 'kind': 'columnar-feature-population', 'population': pin,
            'recipe_sha256': recipe_sha256, 'inputs': inputs, 'spec': p['spec'], 'counts': p['counts'],
            'exported': len(rows), 'expanded_bytes': expanded, 'region_encoding': {p['spec']['region']: 0},
            'negative_fraction': p['counts']['negative'] / max(1, p['counts']['selected']),
            'dropped_negative_fraction': p['counts']['dropped_negative'] / max(1, p['counts']['selected']),
            'sampling': {'algorithm': 'lowest-sha256-seed-event-id', 'seed': p['spec']['sampling_seed'],
                         'eligible': p['counts']['eligible'], 'retained': len(rows),
                         'sampled_out': p['counts']['eligible'] - len(rows)},
            'requires_weighted_qualification': p['spec']['weight_policy']['unequal'] == 'weighted-qualification',
            'fold_by_group': dict(zip(groups.tolist(), fold_map(groups, folds['k'], folds['salt']).tolist()))}
    sidecar = directory / 'features.json'
    with sidecar.open('x') as f:
        json.dump(meta, f, sort_keys=True, allow_nan=False)
    return path, sidecar


class FrozenModel:
    """Pinned ML checkpoints, transforms and explicit train/test group custody."""
    def __init__(self, pin, features, base):
        from ravel.physics import ml_training as ml
        from ravel.physics.ml_crossfit import audit_models
        self.input_files = []

        def read(pin):
            ml._pin(pin)
            raw = ml._bytes(pin, base)
            if not pin['path'].startswith('sealed://'):
                self.input_files.append(ml._path(pin, base).resolve())
            return raw

        record = json.loads(read(pin))
        _keys(record, ('schema_version', 'kind', 'features', 'checkpoint', 'transform', 'group_scope', 'folds', 'freeze'))
        if record['schema_version'] != 1 or record['kind'] != 'columnar-frozen-model':
            raise ValueError('pinned frozen model record required')
        if record['features'] != features:
            raise ValueError('model feature list differs from observable features')
        freeze = json.loads(read(record['freeze']))
        if record['checkpoint'] not in freeze.get('models', []):
            raise ValueError('checkpoint is absent from pinned freeze')
        raw = read(record['checkpoint'])
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_BYTES:
                raise ValueError('expanded model exceeds 64 MiB')
        with np.load(io.BytesIO(raw), allow_pickle=False) as z:
            self.state = {key: z[key] for key in z.files}
        if 'architecture' not in self.state or 'layers' not in self.state:
            raise ValueError('selected ML NumPy checkpoint required')
        self.transform = json.loads(read(record['transform']))
        if self.transform.get('kind') not in ('standardize', 'region_quantile'):
            raise ValueError('unsupported frozen preprocessing')
        self.scope = json.loads(read(record['group_scope']))
        _keys(self.scope, ('train_groups', 'validation_groups', 'preprocessing_groups', 'test_groups'))
        if any(not isinstance(v, list) or any(not isinstance(g, str) for g in v) for v in self.scope.values()):
            raise ValueError('model scope requires string group identities')
        if not audit_models([self.scope])['passed']:
            raise ValueError('model group scope leaks held-out groups')
        self.test_groups = frozenset(self.scope['test_groups'])
        self.forbidden_groups = frozenset(self.scope['train_groups'] + self.scope['validation_groups'] + self.scope['preprocessing_groups'])
        self.folds = record['folds']
        _keys(self.folds, ('k', 'salt', 'test_fold'))
        _folds({k: self.folds[k] for k in ('k', 'salt')})
        if type(self.folds['test_fold']) is not int or not 0 <= self.folds['test_fold'] < self.folds['k']:
            raise ValueError('invalid held-out fold')
        histories = []
        for pin in freeze.get('histories', []):
            history = json.loads(read(pin))
            if history.get('checkpoint') == record['checkpoint']:
                histories.append(history)
        if len(histories) != 1 or any(histories[0].get(k) != record[k] for k in ('transform', 'group_scope')):
            raise ValueError('frozen history must bind checkpoint, preprocessing and group scope')
        if histories[0].get('fold') != self.folds['test_fold'] or histories[0].get('salt') != self.folds['salt']:
            raise ValueError('frozen history differs from held-out fold contract')
        architecture = str(self.state['architecture'])
        if architecture not in ('logistic', 'quadratic_logistic', 'mlp'):
            raise ValueError('unsupported selected model architecture')
        layers = self.state['layers']
        if layers.shape != () or layers.dtype.kind not in 'iu' or not 1 <= int(layers) <= 32:
            raise ValueError('bounded selected model layers required')
        width = len(features)
        if architecture == 'quadratic_logistic':
            width += width * (width + 1) // 2
        expected = {'architecture', 'layers'}
        for i in range(int(layers)):
            w, b = self.state.get(f'w{i}'), self.state.get(f'b{i}')
            if w is None or b is None or w.ndim != 2 or w.shape[0] != width or b.shape != (w.shape[1],):
                raise ValueError('checkpoint feature/layer shape differs from frozen record')
            if w.dtype.kind not in 'fiu' or b.dtype.kind not in 'fiu' or not np.all(np.isfinite(w)) or not np.all(np.isfinite(b)):
                raise ValueError('finite numeric checkpoint required')
            width = w.shape[1]
            expected.update((f'w{i}', f'b{i}'))
        if width != 1 or set(self.state) != expected:
            raise ValueError('single-score checkpoint schema required')
        if self.transform['kind'] == 'standardize':
            mean, scale = (np.asarray(self.transform[k], float) for k in ('mean', 'scale'))
            if mean.shape != (len(features),) or scale.shape != mean.shape or not np.all(np.isfinite(mean)) or not np.all(np.isfinite(scale)) or np.any(scale <= 0):
                raise ValueError('frozen standardization differs from feature dimensions')

    def predict(self, x, groups, regions=None):
        from ravel.physics.ml_crossfit import apply_transform, fold_map
        from ravel.physics.ml_backends import predict_selected
        groups = identities(groups)
        if any(g in self.forbidden_groups or g not in self.test_groups for g in groups):
            raise ValueError('model_score refuses in-fold or unknown evaluation groups')
        if np.any(fold_map(groups, self.folds['k'], self.folds['salt']) != self.folds['test_fold']):
            raise ValueError('model_score refuses events outside the held-out fold')
        if not np.all(np.isfinite(x)):
            raise ValueError('model_score requires finite features')
        if self.transform['kind'] == 'region_quantile' and regions is None:
            raise ValueError('region_quantile model_score requires a region observable')
        regions = np.zeros(len(x), dtype=np.int64) if regions is None else np.asarray(regions)
        if regions.shape != (len(x),) or regions.dtype.kind not in 'fiu' or not np.all(np.isfinite(regions)) or np.any(regions != np.floor(regions)) or np.any(np.abs(regions) >= 2**53):
            raise ValueError('model_score region observable must contain exact integer indices')
        regions = regions.astype(np.int64)
        score = predict_selected(self.state, apply_transform(self.transform, x, regions))
        if score.shape != (len(x),):
            raise ValueError('model_score prediction shape differs from event population')
        return score
