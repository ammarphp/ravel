"""Delivery parity rows over the shared physics normalization ledger."""
import math
from ravel.physics import normalization_ledger as physics


def parity_rows(ledger, *, delivered, applied_factors=None, certifier_sigma_fb=None):
    report = physics.check(ledger, delivered=delivered, certifier_sigma_fb=certifier_sigma_fb)
    factors = report['factors']
    rows = []
    if applied_factors is not None:
        if set(applied_factors) != set(factors):
            raise ValueError('parity factor observation must contain the complete normalization chain')
        for name, expected in factors.items():
            observed = physics._num(applied_factors[name], 'observed ' + name)
            passed = math.isclose(expected, observed, rel_tol=1e-12, abs_tol=0)
            rows.append({'stage': name, 'expected': expected, 'observed': observed,
                         'status': 'pass' if passed else 'fail', 'causes': [] if passed else [name]})
    causes = [r['code'] for r in report['failures']]
    for region, expected in report['expected'].items():
        values = delivered.get(region, [])
        for i, value in enumerate(expected['values']):
            observed = values[i] if i < len(values) else None
            passed = observed is not None and math.isclose(value, observed, rel_tol=report['rel_tol'], abs_tol=0)
            rows.append({'stage': 'delivered_yield', 'region': region, 'bin': i, 'expected': value,
                         'observed': observed, 'status': 'pass' if passed and report['passed'] else 'fail',
                         'causes': [] if passed and report['passed'] else causes})
    return rows
