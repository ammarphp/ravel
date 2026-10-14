"""Explicit, byte-bound selection packages; discovery never executes source bodies."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import types

from ravel.workflow.state_io import _unique

PACKAGE_ENV = 'RAVEL_ANALYSIS_PACKAGE'
DISCOVERY_ENV = 'RAVEL_ANALYSIS_PACKAGES'


class PackageInputError(ValueError):
    def __init__(self, reason, detail=''):
        self.reason = reason
        super().__init__(reason + (': ' + detail if detail else ''))


class MissingSelectionAttribute(PackageInputError, AttributeError):
    """No package is selected; optional-hook probes see an absent attribute."""


def selected_attribute(name):
    """Module ``__getattr__`` for compatibility surfaces of the explicitly selected package."""
    if name.startswith('__'):
        raise AttributeError(name)
    try:
        routine = load_routine()
    except PackageInputError as exc:
        if exc.reason != 'missing_analysis_package':
            raise
        raise MissingSelectionAttribute(exc.reason, name) from None
    return getattr(routine, name)


def _read(path):
    path = Path(path).absolute()
    if path.is_symlink() or not path.is_file():
        raise PackageInputError('invalid_package_source', str(path))
    if any(parent.is_symlink() for parent in path.parents):
        raise PackageInputError('invalid_package_source', 'symlink ancestor')
    raw = path.read_bytes()
    if not raw or len(raw) > 16 * 1024 * 1024:
        raise PackageInputError('invalid_package_source', 'empty or oversized file')
    return raw


def _json(raw):
    def nonfinite(value):
        raise PackageInputError('invalid_package_source', 'nonfinite JSON')
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=nonfinite)


def _pin(base, row):
    if not isinstance(row, dict) or not isinstance(row.get('path'), str):
        raise PackageInputError('missing_package_source')
    relative = Path(row['path'])
    if relative.is_absolute() or '..' in relative.parts:
        raise PackageInputError('invalid_package_source', 'package members must be relative')
    path = base / relative
    raw = _read(path)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != row.get('sha256'):
        raise PackageInputError('package_source_changed', str(path))
    return {'path': str(path), 'sha256': digest}, raw


def _texts(values, label):
    if (not isinstance(values, list) or not values
            or any(not isinstance(v, str) or not v.strip() for v in values) or len(values) != len(set(values))):
        raise PackageInputError('invalid_package_manifest', label)
    return values


def load_package(path=None, *, require_qualification=False):
    path = path or os.environ.get(PACKAGE_ENV)
    if not path:
        raise PackageInputError('missing_analysis_package')
    path = Path(path).absolute()
    if path.is_dir():
        path = path / 'manifest.json'
    raw = _read(path)
    path = path.resolve()
    document = _json(raw)
    if (not isinstance(document, dict) or document.get('schema_version') != 1
            or document.get('kind') != 'analysis-package'):
        raise PackageInputError('invalid_package_manifest', 'analysis-package/v1 required')
    for key in ('package_id', 'package_version'):
        if not isinstance(document.get(key), str) or not document[key].strip():
            raise PackageInputError('invalid_package_manifest', key)
    _texts(document.get('analysis_ids'), 'analysis_ids')
    compatibility = document.get('compatibility')
    if not isinstance(compatibility, dict) or set(compatibility) != {'models', 'preparations', 'detectors', 'statistics'}:
        raise PackageInputError('missing_package_compatibility')
    for key, values in compatibility.items():
        _texts(values, key)
    routine = document.get('routine', {})
    if routine.get('kind') not in ('counting', 'two-pass', 'calibrated'):
        raise PackageInputError('unsupported_routine_interface')
    _texts(routine.get('regions'), 'regions')
    flags = routine.get('flavour_flags')
    if not isinstance(flags, list) or any(not isinstance(v, str) or not v for v in flags) or len(flags) != len(set(flags)):
        raise PackageInputError('invalid_package_manifest', 'flavour_flags')
    if routine['kind'] == 'counting' and len(flags) != 2:
        raise PackageInputError('unsupported_routine_interface', 'counting/v1 carries two flags')
    if type(routine.get('accepts_parameters', False)) is not bool:
        raise PackageInputError('invalid_package_manifest', 'accepts_parameters')
    for field in ('helper_outputs', 'arguments'):
        if not isinstance(routine.get(field), list) or any(not isinstance(v, str) for v in routine[field]):
            raise PackageInputError('invalid_package_manifest', field)
    for output in routine['helper_outputs']:
        p = Path(output)
        if p.is_absolute() or '..' in p.parts or not output:
            raise PackageInputError('invalid_package_manifest', 'helper output path')
    source_pin, _ = _pin(path.parent, routine)
    pins = [{'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}, source_pin]
    for member in document.get('dependencies', []):
        pin, _ = _pin(path.parent, member)
        pins.append(pin)
    qualification = document.get('qualification', {})
    if not isinstance(qualification.get('evidence'), list) or qualification.get('status') not in ('pending', 'qualified'):
        raise PackageInputError('invalid_package_manifest', 'qualification')
    reports = []
    for evidence in qualification['evidence']:
        pin, report_raw = _pin(path.parent, evidence)
        pins.append(pin)
        report = _json(report_raw)
        if (report.get('schema_version') != 1 or report.get('kind') != 'routine-qualification'
                or report.get('status') != 'passed' or report.get('interface_version') != 1
                or report.get('selection_sha256') != source_pin['sha256']
                or report.get('compatibility') != compatibility
                or not isinstance(report.get('checks'), list) or not report['checks']
                or any(check.get('passed') is not True for check in report['checks'])):
            raise PackageInputError('invalid_package_qualification')
        for check in report['checks']:
            if not {'name', 'reference', 'computed', 'rtol', 'atol', 'passed'} <= set(check):
                raise PackageInputError('invalid_package_qualification')
            values = [check[key] for key in ('reference', 'computed', 'rtol', 'atol')]
            if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values)
                    or check['rtol'] < 0 or check['atol'] < 0
                    or not math.isclose(check['computed'], check['reference'], rel_tol=check['rtol'], abs_tol=check['atol'])):
                raise PackageInputError('invalid_package_qualification')
        reports.append(report)
    if require_qualification and (qualification['status'] != 'qualified' or not reports):
        raise PackageInputError('missing_package_qualification')
    return {**document, 'manifest_path': str(path), 'source_pins': pins,
            'physics_certified': False, 'compute_authorized': False}


def discover(roots=None):
    """Read only explicit search roots; duplicate identities refuse rather than win by order."""
    if roots is None:
        roots = [p for p in os.environ.get(DISCOVERY_ENV, '').split(os.pathsep) if p]
    result = {}
    for given in roots:
        root = Path(given)
        paths = [root] if root.is_file() else sorted(root.glob('*/manifest.json'))
        if root.is_dir() and (root / 'manifest.json').is_file():
            paths = [root / 'manifest.json']
        for path in paths:
            package = load_package(path)
            name = package['package_id']
            if name in result:
                raise PackageInputError('ambiguous_analysis_package', name)
            result[name] = package
    return result


def load_routine(path=None, *, require_qualification=False):
    """Load an explicitly selected source snapshot, retaining pins for launch admission."""
    package = load_package(path, require_qualification=require_qualification)
    pin = package['source_pins'][1]
    raw = _read(pin['path'])
    if hashlib.sha256(raw).hexdigest() != pin['sha256']:
        raise PackageInputError('package_source_changed')
    module = types.ModuleType('_ravel_supplied_selection_' + pin['sha256'])
    module.__file__ = pin['path']
    module.__package__ = 'ravel.physics'
    exec(compile(raw, pin['path'], 'exec'), module.__dict__)
    if not callable(getattr(module, 'sr_order', None)) or list(module.sr_order()) != package['routine']['regions']:
        raise PackageInputError('routine_interface_mismatch', 'region order')
    if package['routine']['kind'] == 'counting':
        if not callable(getattr(module, 'select', None)) or list(getattr(module, 'FLAVOUR_FLAGS', ())) != package['routine']['flavour_flags']:
            raise PackageInputError('routine_interface_mismatch', 'selection or flags')
    if package['routine']['kind'] == 'calibrated':
        for name in ('select_regions', 'validate_state', 'validate_generation', '_eras', 'stable_era'):
            if not callable(getattr(module, name, None)):
                raise PackageInputError('routine_interface_mismatch', name)
        if not isinstance(getattr(module, 'IMPLEMENTATION', None), str) or not isinstance(getattr(module, 'RESPONSE_COMPONENTS', None), (set, list, tuple)):
            raise PackageInputError('routine_interface_mismatch', 'calibrated metadata')
    module.NAME = package['package_id']
    module.ANALYSIS_PACKAGE = package
    # Recheck all pinned inputs after executing the supplied body.
    for member in package['source_pins']:
        if hashlib.sha256(_read(member['path'])).hexdigest() != member['sha256']:
            raise PackageInputError('package_source_changed')
    return module


def evaluate_contract(contract):
    """Pure counting evaluation over the supplied population and named parameter points."""
    for field in ('study_id', 'analysis_package', 'parameter_points', 'dataset', 'output'):
        if field not in contract:
            raise PackageInputError('missing_' + field)
    if not isinstance(contract['study_id'], str) or not contract['study_id']:
        raise PackageInputError('missing_study_id')
    points = contract['parameter_points']
    if not isinstance(points, list) or not points or any(not isinstance(p, dict) for p in points):
        raise PackageInputError('missing_parameter_points')
    dataset = contract['dataset']
    if not isinstance(dataset, dict) or set(dataset) != {'arrays', 'weights'}:
        raise PackageInputError('missing_dataset')
    arrays, weights = dataset['arrays'], dataset['weights']
    if not isinstance(arrays, dict) or not arrays or not isinstance(weights, list) or not weights:
        raise PackageInputError('missing_dataset')
    if any(len(values) != len(weights) for values in arrays.values()):
        raise PackageInputError('dataset_shape_mismatch')
    if any(isinstance(w, bool) or not isinstance(w, (int, float)) or not math.isfinite(w) for w in weights):
        raise PackageInputError('invalid_event_weight')
    output = contract['output']
    if not isinstance(output, dict) or output.get('format') not in ('json', 'jsonl') or not output.get('path'):
        raise PackageInputError('missing_output')
    routine = load_routine(contract['analysis_package'])
    if routine.ANALYSIS_PACKAGE['routine']['kind'] != 'counting':
        raise PackageInputError('unsupported_routine_interface')
    names = routine.sr_order()
    rows = []
    for point in points:
        contributions = {name: [] for name in names}
        counts = dict.fromkeys(names, 0)
        for i, weight in enumerate(weights):
            kwargs = {'parameters': point} if routine.ANALYSIS_PACKAGE['routine'].get('accepts_parameters') else {}
            if point and not kwargs:
                raise PackageInputError('unsupported_routine_parameters')
            selected = routine.select(arrays, i, **kwargs)
            if selected is None:
                continue
            accepted = selected[0]
            if not set(accepted) <= set(names):
                raise PackageInputError('routine_interface_mismatch', 'undeclared region')
            for name in accepted:
                counts[name] += 1
                contributions[name].append(weight)
        rows.append({'parameters': point, 'raw': counts,
                     'sumw': {name: math.fsum(values) for name, values in contributions.items()},
                     'sumw2': {name: math.fsum(w*w for w in values) for name, values in contributions.items()}})
    result = {'study_id': contract['study_id'], 'events': len(weights), 'points': rows,
              'analysis_package': routine.ANALYSIS_PACKAGE['source_pins'][0], 'physics_validated': False}
    path = Path(output['path'])
    with path.open('x') as stream:
        if output['format'] == 'json':
            json.dump(result, stream, allow_nan=False)
        else:
            for row in rows:
                stream.write(json.dumps({'study_id': result['study_id'], 'events': result['events'], **row}, allow_nan=False) + '\n')
    return result



def selection_source_from_metadata(metadata):
    """Bind a trace to its selected package rather than an installed frontend file."""
    pin = metadata.get('analysis_package')
    if not isinstance(pin, dict) or not pin.get('path'):
        raise PackageInputError('missing_analysis_package')
    raw = _read(pin['path'])
    if hashlib.sha256(raw).hexdigest() != pin.get('sha256'):
        raise PackageInputError('package_source_changed')
    package = load_package(pin['path'])
    return package['source_pins'][1], package['source_pins']

def qualify_package(path, *, reference, computed, tolerances, output):
    """Compare supplied numerical references; this never runs an upstream executable."""
    package = load_package(path)
    if (not isinstance(reference, dict) or not reference or not isinstance(computed, dict)
            or not isinstance(tolerances, dict) or set(reference) != set(computed)
            or set(reference) != set(tolerances)):
        raise PackageInputError('missing_qualification_values')
    checks = []
    for name in sorted(reference):
        policy = tolerances[name]
        if not isinstance(policy, dict) or set(policy) != {'rtol', 'atol'}:
            raise PackageInputError('missing_qualification_tolerance', name)
        values = [reference[name], computed[name], policy['rtol'], policy['atol']]
        if (any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in values)
                or policy['rtol'] < 0 or policy['atol'] < 0):
            raise PackageInputError('invalid_qualification_values', name)
        passed = math.isclose(computed[name], reference[name], rel_tol=policy['rtol'], abs_tol=policy['atol'])
        checks.append({'name': name, 'reference': reference[name], 'computed': computed[name], **policy, 'passed': passed})
    report = {'schema_version': 1, 'kind': 'routine-qualification', 'interface_version': 1,
              'status': 'passed' if all(check['passed'] for check in checks) else 'failed',
              'selection_sha256': package['routine']['sha256'], 'compatibility': package['compatibility'],
              'checks': checks, 'physics_certified': False}
    with Path(output).open('x') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write('\n')
    return report


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('qualify', help='compare supplied values; no native tools are executed')
    p.add_argument('--manifest', required=True)
    p.add_argument('--reference', required=True)
    p.add_argument('--computed', required=True)
    p.add_argument('--tolerances', required=True)
    p.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    report = qualify_package(args.manifest, reference=_json(_read(args.reference)),
                             computed=_json(_read(args.computed)), tolerances=_json(_read(args.tolerances)),
                             output=args.output)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
