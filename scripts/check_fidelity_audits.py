#!/usr/bin/env python3
"""Check that the current fidelity demonstrations match their inputs and implementation.

This verifies integrity and arithmetic. It does not certify detector fidelity or
replace the retained-event replay / numerical tests recorded in each audit.
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ravel.evidence_layout import resolve


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(root=ROOT, audits=None):
    audits = audits or root / 'evidence/audits'
    errors = []
    native = audits / '2026-09-05-native-fidelity'
    verification = json.loads((native / 'verification.json').read_text())
    differential = json.loads((native / 'erjr_differential.json').read_text())
    for name, expected in verification['engine_sha256'].items():
        if sha(root / 'src/ravel/physics' / name) != expected:
            errors.append(f'native audit implementation changed: {name}')
    recorded = verification['retained_erjr_replay']
    for key, mode, region in [('sr_low_historical', 'historical', 'SRlow'),
                               ('sr_low_paper', 'paper', 'SRlow'),
                               ('sr_isr_historical', 'historical', 'SRISR'),
                               ('sr_isr_paper', 'paper', 'SRISR')]:
        if recorded[key] != differential['counts'][mode][region]:
            errors.append(f'native differential count drift: {key}')
    if len(differential['changed_events']) != recorded['changed_events']:
        errors.append('native changed-event denominator drift')
    if differential['entries'] != recorded['entries']:
        errors.append('native input-event denominator drift')
    for mode, counts in differential['counts'].items():
        for name, count in counts.items():
            # This audit's sample has uniform positive nominal weights, explicitly recorded.
            expected = count / differential['entries']
            if abs(differential['acceptance'][mode][name] - expected) > 1e-12:
                errors.append(f'native acceptance arithmetic drift: {mode}/{name}')
    scan = audits / '2026-09-05-scan-fidelity'
    provenance = json.loads((scan / 'provenance.json').read_text())
    for name, expected in provenance['inputs'].items():
        if sha(resolve(root, name)) != expected:
            errors.append(f'scan demonstration input changed: {name}')
    for name, expected in provenance['outputs'].items():
        if sha(scan / name) != expected:
            errors.append(f'scan demonstration output changed: {name}')
    from ravel.plotting.scan_contour import comparison_data, read_limit_grid
    source = json.loads(resolve(root, 'evidence/scans/slepton-bino-figure-3/scan.json').read_text())
    derived = comparison_data(source, read_limit_grid(scan / 'atlas-limit-grid.yaml'))
    if derived != json.loads((scan / 'scan__reldiff.json').read_text()):
        errors.append('scan comparison population or numerical residual drift')
    statistical = json.loads((audits / '2026-09-05-statistical-fidelity/audit.json').read_text())
    for name, expected in statistical['engine_sha256'].items():
        if sha(root / name) != expected:
            errors.append(f'statistical audit implementation changed: {name}')
    replay = statistical['cached_replay']
    if len(replay['cases']) != replay['population'] or sum(bool(c['gate_ok']) for c in replay['cases']) != replay['passed_cases']:
        errors.append('statistical replay population or pass-count drift')
    example = statistical['root_precision_example']
    relative = example['refined_observed_limit'] / example['reference_observed_limit'] - 1
    if abs(relative - example['refined_relative_error']) > 1e-12:
        errors.append('statistical root-error arithmetic drift')
    return errors


def main():
    try:
        errors = check()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors = [f'audit cannot be checked: {exc}']
    for error in errors:
        print('[FAIL] ' + error)
    print('fidelity audits: ' + ('FAIL' if errors else 'OK (integrity and arithmetic; not physics certification)'))
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
