"""Executable reviewer items of staged ML training: leakage, split, overtraining, budget and test custody.

Each item is code that recomputes its verdict from pinned arrays and stage records; no item takes a
verdict from a worker, a receipt or a literal ``pass``. An item returns ``{"id", "verdict", "evidence",
"thresholds"}`` with ``verdict`` one of ``pass``, ``fail`` or ``unresolved``; only ``pass`` passes.

- ``check:ml-label-leakage``: on the training partition only, a declared feature named like the label,
  weight or identity columns, or one whose single-feature weighted ROC AUC (either orientation) reaches
  the declared ceiling, is leakage. A feature the specification declares as expected to separate remains unresolved
  until a source-backed exception is admitted; a justification alone cannot pass the gate.
- ``check:ml-split-disjoint`` and ``check:ml-duplicate-identities``: no event or group identity is shared
  between partitions and none repeats inside one.
- ``check:ml-duplicate-rows``: identical feature rows shared by the training partition and a held-out
  partition, as a fraction of the held-out rows, stay below the declared tolerance.
- ``check:ml-preprocessing-scope``: the recorded standardisation equals the one recomputed from the
  training partition alone.
- ``check:ml-overtraining``: per trained replicate, the training-minus-test ROC AUC gap stays below its
  ceiling, and the weighted Kolmogorov-Smirnov comparison of training and test scores, per class, does
  not show both a small p-value and a large distance.
- ``check:ml-equal-budget``, ``check:ml-replicate-count``, ``check:ml-test-once``,
  ``check:ml-statistics-sizing`` and ``check:ml-metric-recompute`` read the stage records.

The thresholds come from the approved specification within fixed bounds (``thresholds``); the defaults
apply when it names none. A Kolmogorov-Smirnov p-value uses effective counts (sum of weights squared over
the sum of squared weights); it is an approximation for weighted samples and is reported as one.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math

import numpy as np

VERDICTS = ('pass', 'fail', 'unresolved')
# Identifier, default and closed bounds of each declared threshold.
THRESHOLDS = {
    'leakage_auc_max': (0.999, 0.9, 0.99999),
    'duplicate_row_fraction_max': (0.01, 0.0, 0.2),
    'overtraining_auc_gap_max': (0.05, 0.001, 0.3),
    'overtraining_ks_pvalue_min': (0.001, 1.e-9, 0.1),
    'overtraining_ks_distance_min': (0.1, 0.01, 0.5),
    'min_class_count': (20, 1, 10**9),
    'metric_tolerance': (1.e-9, 0.0, 1.e-3),
}
ITEMS = ('check:ml-label-leakage', 'check:ml-split-disjoint', 'check:ml-duplicate-identities',
         'check:ml-duplicate-rows', 'check:ml-preprocessing-scope', 'check:ml-statistics-sizing',
         'check:ml-equal-budget', 'check:ml-replicate-count', 'check:ml-test-once', 'check:ml-overtraining',
         'check:ml-metric-recompute')
RESERVED_NAMES = ('label', 'weight', 'event_id', 'group_id', 'partition')


def thresholds(spec):
    """The declared thresholds within their bounds; an out-of-bound value is refused, never clipped."""
    declared = ((spec or {}).get('checks') or {}) if type(spec) is dict else {}
    if type(declared) is not dict:
        raise ValueError('checks must be an object of declared thresholds')
    unknown = sorted(set(declared) - set(THRESHOLDS) - {'separating_features'})
    if unknown:
        raise ValueError('unknown check thresholds: ' + ', '.join(unknown))
    result = {}
    for key, (default, low, high) in THRESHOLDS.items():
        value = declared.get(key, default)
        if type(value) not in (int, float) or isinstance(value, bool) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{key} must be a finite number in [{low}, {high}]')
        result[key] = value
    allowed = declared.get('separating_features', [])
    if (type(allowed) is not list or len(allowed) > 64 or any(
            type(r) is not dict or set(r) != {'feature', 'justification'} or type(r['feature']) is not str
            or type(r['justification']) is not str or len(r['justification'].strip()) < 20 for r in allowed)):
        raise ValueError('separating_features rows name a feature and a justification of at least 20 characters')
    result['separating_features'] = deepcopy(allowed)
    return result


def item(check_id, verdict, evidence=None, limits=None, note=None):
    if check_id not in ITEMS or verdict not in VERDICTS:
        raise ValueError(f'unknown reviewer item or verdict: {check_id} {verdict}')
    row = {'id': check_id, 'verdict': verdict, 'evidence': deepcopy(evidence or {}),
           'thresholds': deepcopy(limits or {})}
    if note:
        row['note'] = note
    return row


# ---- statistics ---------------------------------------------------------------------------------

def roc_auc(y, score, weight):
    """Weighted, tie-grouped ROC AUC; None when a class has no positive weight."""
    y = np.asarray(y, dtype=float)
    score = np.asarray(score, dtype=float)
    weight = np.asarray(weight, dtype=float)
    positive, negative = weight[y == 1].sum(), weight[y == 0].sum()
    if positive <= 0 or negative <= 0:
        return None
    order = np.argsort(-score, kind='stable')
    yy, ss, ww = y[order], score[order], weight[order]
    ends = np.r_[np.flatnonzero(np.diff(ss) != 0), len(ss) - 1]
    tpr = np.r_[0, np.cumsum(ww * (yy == 1))[ends] / positive]
    fpr = np.r_[0, np.cumsum(ww * (yy == 0))[ends] / negative]
    return float(np.trapz(tpr, fpr))


def separability(y, values, weight):
    """Single-variable separation in either orientation: ``max(AUC, 1 - AUC)``."""
    auc = roc_auc(y, values, weight)
    return None if auc is None else max(auc, 1.0 - auc)


def effective_count(weight):
    weight = np.asarray(weight, dtype=float)
    squares = float(np.sum(weight ** 2))
    return 0.0 if squares <= 0 else float(weight.sum()) ** 2 / squares


def kolmogorov_sf(value):
    """``P(K > value)`` of the Kolmogorov distribution (alternating series; 1 where it does not converge)."""
    if value <= 0:
        return 1.0
    if value < 0.2:
        return 1.0
    total, sign, previous = 0.0, 1.0, 0.0
    for k in range(1, 101):
        term = sign * 2.0 * math.exp(-2.0 * k * k * value * value)
        total += term
        if abs(term) <= 1.e-3 * previous or abs(term) <= 1.e-12 * abs(total):
            return min(1.0, max(0.0, total))
        sign, previous = -sign, abs(term)
    return 1.0


def ks_weighted(a, wa, b, wb):
    """Weighted two-sample Kolmogorov-Smirnov distance and its asymptotic p-value with effective counts."""
    a, wa, b, wb = (np.asarray(v, dtype=float) for v in (a, wa, b, wb))
    if not len(a) or not len(b) or wa.sum() <= 0 or wb.sum() <= 0:
        return {'distance': None, 'p_value': None, 'effective_counts': [0.0, 0.0]}
    oa, ob = np.argsort(a, kind='stable'), np.argsort(b, kind='stable')
    a, wa, b, wb = a[oa], wa[oa], b[ob], wb[ob]
    grid = np.unique(np.concatenate([a, b]))
    ca = np.r_[0, np.cumsum(wa)] / wa.sum()
    cb = np.r_[0, np.cumsum(wb)] / wb.sum()
    distance = float(np.max(np.abs(ca[np.searchsorted(a, grid, side='right')]
                                   - cb[np.searchsorted(b, grid, side='right')])))
    na, nb = effective_count(wa), effective_count(wb)
    n = na * nb / (na + nb)
    root = math.sqrt(n)
    return {'distance': distance, 'p_value': kolmogorov_sf((root + 0.12 + 0.11 / root) * distance),
            'effective_counts': [na, nb], 'approximation': 'asymptotic, effective counts'}


def row_hashes(x):
    """One 64-bit digest prefix per feature row, equal for equal values whatever their dtype; -0 equals +0."""
    x = np.asarray(x, dtype='<f8')
    x = np.where(x == 0, 0.0, x)
    rows = np.ascontiguousarray(x.reshape(len(x), -1))
    return np.array([int.from_bytes(hashlib.sha256(row.tobytes()).digest()[:8], 'little') for row in rows],
                    dtype=np.uint64)


# ---- items --------------------------------------------------------------------------------------

def label_leakage(x, y, weight, features, columns, limits):
    """``check:ml-label-leakage`` on the training partition."""
    x = np.asarray(x, dtype=float)
    allowed = {row['feature']: row['justification'] for row in limits['separating_features']}
    rows, failing, declared = [], [], []
    reserved = {str(columns.get(k)).lower() for k in RESERVED_NAMES if columns.get(k)} | set(RESERVED_NAMES)
    for index, name in enumerate(features):
        values = x[:, index]
        finite = bool(np.isfinite(values).all())
        value = separability(y, values, weight) if finite else None
        row = {'feature': name, 'separability': value, 'finite': finite,
               'constant': bool(finite and np.ptp(values) == 0)}
        if name.lower() in reserved:
            row['finding'] = 'reserved column used as a feature'
            failing.append(name)
        elif value is not None and value >= limits['leakage_auc_max']:
            if name in allowed:
                row['finding'] = 'declared separating feature'
                row['justification'] = allowed[name]
                declared.append(name)
            else:
                row['finding'] = 'single-feature separation at or above the leakage ceiling'
                failing.append(name)
        rows.append(row)
    verdict = 'fail' if failing else ('unresolved' if declared else 'pass')
    return item('check:ml-label-leakage', verdict, {'features': rows, 'failing': failing, 'declared': declared,
                                                     'partition': 'train'},
                {'leakage_auc_max': limits['leakage_auc_max']},
                note=('declared separating features need the reviewer\'s acknowledgement' if declared else None))


def split_disjoint(identities):
    """``check:ml-split-disjoint``: ``identities`` maps a partition to ``{"event_id": [...], "group_id": [...]}``."""
    names = sorted(identities)
    shared = []
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            for column in ('event_id', 'group_id'):
                common = set(map(str, identities[first][column])) & set(map(str, identities[second][column]))
                if common:
                    shared.append({'partitions': [first, second], 'column': column, 'count': len(common),
                                   'examples': sorted(common)[:5]})
    return item('check:ml-split-disjoint', 'fail' if shared else 'pass', {'shared': shared, 'partitions': names})


def duplicate_identities(identities):
    found = []
    for name in sorted(identities):
        events = [str(v) for v in identities[name]['event_id']]
        repeated = len(events) - len(set(events))
        if repeated:
            found.append({'partition': name, 'repeated_event_ids': repeated})
    return item('check:ml-duplicate-identities', 'fail' if found else 'pass', {'repeated': found})


def duplicate_rows(train_hashes, held_out, limits):
    """``held_out`` maps a partition name to its row hashes."""
    seen = np.unique(np.asarray(train_hashes, dtype=np.uint64))
    rows, failing = [], []
    for name in sorted(held_out):
        hashes = np.asarray(held_out[name], dtype=np.uint64)
        shared = int(np.isin(hashes, seen).sum())
        fraction = shared / len(hashes) if len(hashes) else 0.0
        rows.append({'partition': name, 'shared_rows': shared, 'rows': len(hashes), 'fraction': fraction})
        if fraction > limits['duplicate_row_fraction_max']:
            failing.append(name)
    return item('check:ml-duplicate-rows', 'fail' if failing else 'pass', {'partitions': rows, 'failing': failing},
                {'duplicate_row_fraction_max': limits['duplicate_row_fraction_max']})


def standardisation(x, weight):
    x = np.asarray(x, dtype=float)
    weight = np.asarray(weight, dtype=float)
    mean = np.average(x, axis=0, weights=weight)
    scale = np.sqrt(np.average((x - mean) ** 2, axis=0, weights=weight))
    scale = np.where(scale > 1.e-12, scale, 1.0)
    return {'mean': mean.tolist(), 'scale': scale.tolist()}


def preprocessing_scope(train_x, train_w, recorded, limits):
    expected = standardisation(train_x, train_w)
    tolerance = max(limits['metric_tolerance'], 1.e-12)
    same = (type(recorded) is dict and recorded.get('fitted_on') == 'train'
            and all(len(recorded.get(k) or []) == len(expected[k]) and np.allclose(recorded[k], expected[k],
                                                                                    rtol=tolerance, atol=tolerance)
                    for k in ('mean', 'scale')))
    return item('check:ml-preprocessing-scope', 'pass' if same else 'fail',
                {'fitted_on': (recorded or {}).get('fitted_on') if type(recorded) is dict else None,
                 'recomputed_on': 'train'})


def statistics_sizing(counts, limits):
    """``counts``: partition -> {"signal": n, "background": n, "signal_effective": .., "background_effective": ..}."""
    short = []
    for name in sorted(counts):
        for cls in ('signal', 'background'):
            effective = counts[name].get(cls + '_effective', counts[name][cls])
            if counts[name][cls] < limits['min_class_count'] or effective < limits['min_class_count']:
                short.append({'partition': name, 'class': cls, 'count': counts[name][cls], 'effective': effective})
    return item('check:ml-statistics-sizing', 'fail' if short else 'pass', {'counts': deepcopy(counts), 'short': short},
                {'min_class_count': limits['min_class_count']})


def equal_budget(training):
    rows = [r for r in training.get('replicates') or () if r.get('kind') != 'cut_based']
    budgets = {(r.get('epochs'), r.get('wall_cap_seconds')) for r in rows if r.get('status') == 'completed'}
    declared = training.get('budget') or {}
    ok = len(budgets) <= 1 and all(r.get('epochs') == declared.get('epochs') for r in rows if r.get('status') == 'completed')
    return item('check:ml-equal-budget', 'pass' if ok else 'fail',
                {'distinct_budgets': sorted([list(b) for b in budgets], key=str), 'declared': deepcopy(declared)})


def replicate_count(training, spec):
    expected = {(arm['id'], seed) for arm in spec['arms'] for seed in (spec['seeds'] if arm.get('kind') != 'cut_based' else [0])}
    done = {(r['arm'], r['seed']) for r in training.get('replicates') or () if r.get('status') == 'completed'}
    missing = sorted([list(k) for k in expected - done], key=str)
    return item('check:ml-replicate-count', 'pass' if not missing and training.get('status') == 'completed' else 'fail',
                {'expected': len(expected), 'completed': len(done & expected), 'missing': missing[:50],
                 'training_status': training.get('status')})


def test_once(admission, training, evaluation):
    """The withheld partition reached only the evaluation, exactly once, as the admitted population."""
    withheld = (admission.get('partitions') or {}).get('test') or {}
    problems = []
    if 'test' in (training.get('inputs') or {}):
        problems.append('the training stage read the withheld partition')
    if evaluation.get('test_reads') != 1:
        problems.append('the evaluation records other than one read of the withheld partition')
    if not withheld.get('identity_sha256') or evaluation.get('test_identity_sha256') != withheld.get('identity_sha256'):
        problems.append('the evaluated population differs from the admitted withheld partition')
    if evaluation.get('models_sha256') != training.get('models_sha256'):
        problems.append('the evaluated models differ from the frozen training output')
    return item('check:ml-test-once', 'fail' if problems else 'pass', {'problems': problems,
                                                                       'identity_sha256': withheld.get('identity_sha256')})


def overtraining(scores, replicates, limits):
    """``scores``: key -> {"train": (y, s, w), "test": (y, s, w)}; ``replicates``: keys of trained models."""
    rows, failing = [], []
    for key in replicates:
        found = scores.get(key)
        if found is None:
            rows.append({'replicate': key, 'finding': 'scores missing'})
            failing.append(key)
            continue
        train, test = found['train'], found['test']
        auc_train, auc_test = roc_auc(*train), roc_auc(*test)
        gap = None if auc_train is None or auc_test is None else auc_train - auc_test
        classes = {}
        for label, name in ((1, 'signal'), (0, 'background')):
            a, b = train[0] == label, test[0] == label
            classes[name] = ks_weighted(train[1][a], train[2][a], test[1][b], test[2][b])
        reasons = []
        if gap is None:
            reasons.append('AUC undefined')
        elif gap > limits['overtraining_auc_gap_max']:
            reasons.append('training-minus-test AUC gap above the ceiling')
        for name, ks in classes.items():
            if ks['p_value'] is None:
                reasons.append(f'{name} distribution comparison undefined')
            elif ks['p_value'] < limits['overtraining_ks_pvalue_min'] and ks['distance'] > limits['overtraining_ks_distance_min']:
                reasons.append(f'{name} training and test scores differ (KS)')
        rows.append({'replicate': key, 'auc_train': auc_train, 'auc_test': auc_test, 'auc_gap': gap,
                     'ks': classes, 'reasons': reasons})
        if reasons:
            failing.append(key)
    return item('check:ml-overtraining', 'fail' if failing else 'pass', {'replicates': rows, 'failing': failing},
                {k: limits[k] for k in ('overtraining_auc_gap_max', 'overtraining_ks_pvalue_min',
                                        'overtraining_ks_distance_min')})


def metric_recompute(recorded, recomputed, limits):
    """Recorded per-replicate test metrics equal the ones recomputed from the stored scores."""
    tolerance = limits['metric_tolerance']
    differing = []
    for key, values in sorted(recomputed.items()):
        stored = (recorded.get(key) or {})
        for metric, value in values.items():
            other = stored.get(metric)
            numbers = all(type(v) in (int, float) and not isinstance(v, bool) for v in (value, other))
            if not numbers:
                if value != other:
                    differing.append({'replicate': key, 'metric': metric, 'recorded': other, 'recomputed': value})
            elif abs(value - other) > tolerance * max(1.0, abs(value)):
                differing.append({'replicate': key, 'metric': metric, 'recorded': other, 'recomputed': value})
    missing = sorted(set(recorded) ^ set(recomputed))
    ok = not differing and not missing
    return item('check:ml-metric-recompute', 'pass' if ok else 'fail',
                {'differing': differing[:50], 'missing': missing}, {'metric_tolerance': tolerance})


def summary(items):
    """``{"passed", "failing", "unresolved", "items"}`` over reviewer items."""
    failing = [r['id'] for r in items if r['verdict'] == 'fail']
    unresolved = [r['id'] for r in items if r['verdict'] == 'unresolved']
    return {'passed': not failing and not unresolved, 'failing': failing, 'unresolved': unresolved,
            'items': deepcopy(items)}
