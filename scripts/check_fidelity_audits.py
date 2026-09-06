#!/usr/bin/env python3
"""Check that the current fidelity demonstrations match their inputs and implementation.

This verifies integrity and arithmetic. It does not certify detector fidelity or
replace the retained-event replay / numerical tests recorded in each audit.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ravel.evidence_layout import resolve
from ravel.workflow.state_io import read_json

REQUIRED_ADDITIONAL_NATIVE_ENGINES = {
    'src/ravel/physics/native_event_io.py',
    'src/ravel/physics/pool_replicas.py',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_paths(audits):
    """Select explicit dated revalidations without rewriting historical evidence."""
    registry = json.loads((audits / 'current.json').read_text())
    if (set(registry) != {'schema_version', 'native', 'scan', 'statistical'}
            or type(registry['schema_version']) is not int or registry['schema_version'] != 1):
        raise ValueError('invalid current fidelity audit registry')
    paths = {}
    for kind in ('native', 'scan', 'statistical'):
        name = registry[kind]
        if not isinstance(name, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}-'+kind+r'-fidelity', name):
            raise ValueError(f'invalid dated {kind} audit directory')
        paths[kind] = audits / name
    return paths


def additional_native_engine_errors(root, pins):
    """Bind the current native audit's additional sources within this repository.

    These two interfaces are part of the current audit's recorded scope. Removing
    a pin cannot silently narrow that scope; further declared sources are checked
    too. Historical audit records are preserved but do not waive current bindings.
    """
    if type(pins) is not dict or not pins:
        return ['native audit additional_engine_sha256 must be a nonempty object']
    errors = [f'native audit additional engine pin missing: {name}'
              for name in sorted(REQUIRED_ADDITIONAL_NATIVE_ENGINES - pins.keys())]
    root = Path(root).resolve()
    for name, expected in pins.items():
        if (type(name) is not str or not name or '\\' in name or '\0' in name
                or re.match(r'^[A-Za-z]:', name)):
            errors.append(f'native audit additional engine path is not repository-relative: {name!r}')
            continue
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or relative.as_posix() != name or name == '.':
            errors.append(f'native audit additional engine path is not repository-relative: {name!r}')
            continue
        if type(expected) is not str or not re.fullmatch(r'[0-9a-f]{64}', expected):
            errors.append(f'native audit additional engine SHA-256 is malformed: {name}')
            continue
        try:
            path = (root / name).resolve()
            if not path.is_relative_to(root):
                errors.append(f'native audit additional engine path escapes repository: {name}')
            elif not path.is_file():
                errors.append(f'native audit additional engine file unavailable: {name}')
            elif sha(path) != expected:
                errors.append(f'native audit additional implementation changed: {name}')
        except (OSError, ValueError, RuntimeError) as exc:
            errors.append(f'native audit additional engine file unavailable: {name}: {exc}')
    return errors


def check(root=ROOT, audits=None):
    audits = audits or root / 'evidence/audits'
    paths = audit_paths(audits)
    errors = []
    native = paths['native']
    verification = read_json(native / 'verification.json')
    differential = json.loads((native / 'erjr_differential.json').read_text())
    for name, expected in verification['engine_sha256'].items():
        if sha(root / 'src/ravel/physics' / name) != expected:
            errors.append(f'native audit implementation changed: {name}')
    errors.extend(additional_native_engine_errors(root, verification.get('additional_engine_sha256')))
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
    scan = paths['scan']
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
    statistical = json.loads((paths['statistical'] / 'audit.json').read_text())
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
