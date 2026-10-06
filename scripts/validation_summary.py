#!/usr/bin/env python3
"""Derive scoped validation facts from the committed historical benchmark baseline.

Never discard failed, unscorable, or missing cases from the denominator.
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_baseline(root=ROOT):
    registry = json.loads((Path(root) / 'benchmarks/cases.json').read_text())
    baseline = json.loads((Path(root) / 'benchmarks/results.json').read_text())
    cases, rows = registry['cases'], baseline['cases']
    ids, result_ids = [c['case_id'] for c in cases], [r['case_id'] for r in rows]
    if len(ids) != len(set(ids)) or len(result_ids) != len(set(result_ids)):
        raise ValueError('duplicate benchmark case_id')
    if set(ids) != set(result_ids):
        raise ValueError(f'registry/baseline mismatch: missing={sorted(set(ids)-set(result_ids))}, '
                         f'extra={sorted(set(result_ids)-set(ids))}')
    return cases, {r['case_id']: r for r in rows}, baseline


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def summarize(cases, results):
    s95, axe, unscorable = [], [], []
    for c in cases:
        r = results[c['case_id']]
        metrics = r.get('metrics') or {}
        lim = metrics.get('limit') or {}
        stored_ratio = lim.get('s95_ratio_obs')
        reference = c['published']['s95_obs']
        if reference is not None:
            observed = lim.get('s95_obs')
            if not finite_number(reference) or reference <= 0:
                raise ValueError(f"{c['case_id']}: invalid published S95")
            if not finite_number(observed) or observed <= 0 or not finite_number(stored_ratio):
                raise ValueError(f"{c['case_id']}: eligible S95 comparison missing/invalid")
            ratio = observed / reference
            # The committed baseline rounds independent fields to six significant figures.
            if not math.isclose(stored_ratio, ratio, rel_tol=1e-5, abs_tol=1e-6):
                raise ValueError(f"{c['case_id']}: stored S95 ratio disagrees with source values")
            s95.append({'case_id': c['case_id'], 'analysis_id': c['analysis_id'],
                        'delta_pct': abs(1-ratio)*100, 'baseline_status': r.get('status')})
        elif stored_ratio is not None:
            raise ValueError(f"{c['case_id']}: S95 ratio has no published reference")
        cert = metrics.get('axe')
        if c['cert']['engine'] == 'none':
            unscorable.append(c['case_id'])
        elif not isinstance(cert, dict) or not finite_number(cert.get('residual')):
            raise ValueError(f"{c['case_id']}: missing/invalid acceptance baseline")
        elif cert.get('cert_verdict') not in ('PASS', 'WARN', 'FAIL') or cert['residual'] < 0:
            raise ValueError(f"{c['case_id']}: invalid acceptance verdict/residual")
        else:
            axe.append({'case_id': c['case_id'], 'verdict': cert['cert_verdict'],
                        'tier': cert.get('tier'), 'residual_pct': 100*cert['residual']})
    if not s95:
        raise ValueError('no observed model-independent S95 comparisons')
    return {
        'scope': 'committed historical baseline; not a fresh replay or simulation',
        'registry_cases': len(cases),
        'statistical_layer': {'metric': 'driving-SR model-independent observed S95 in events',
                              'comparisons': len(s95),
                              'eligible_comparisons': sum(c['published']['s95_obs'] is not None for c in cases),
                              'reference_unavailable': sum(c['published']['s95_obs'] is None for c in cases),
                              'missing_results': 0,
                              'distinct_searches': len({r['analysis_id'] for r in s95}),
                              'worst_delta_pct': round(max(r['delta_pct'] for r in s95), 1),
                              'cases': s95},
        'acceptance_layer': {'scorable': len(axe), 'unscorable': len(unscorable),
                             'unscorable_cases': unscorable,
                             'verdict_counts': {v: sum(r['verdict'] == v for r in axe)
                                                for v in ('PASS', 'WARN', 'FAIL')},
                             'cases': axe},
    }


def benchmark_headline(summary):
    stats = summary['statistical_layer']
    return (f"{stats['comparisons']} observed S95 comparisons within "
            f"{stats['worst_delta_pct']:.1f}% (statistical layer)")


if __name__ == '__main__':
    cases, results, _ = load_baseline()
    print(json.dumps(summarize(cases, results), indent=2, allow_nan=False))
