"""The comparison and certificate producer, and its fail-closed ``comparison`` gate provider (B4 R2/R3 item 5).

Producers (RAVEL's own check runner; each writes a ``ravel-check-result`` record under
``checks/`` and registers it in custody through ``rdj_custody.register_check_result``):

- ``produce_comparison(rundir, point_id, left=, right=, tolerance=)``: an implementation
  comparison for a ``comparison_required`` review point. Both operands are run-relative JSON
  objects of named finite numbers (or a JSON pointer to one); every name present in either
  side is compared by relative difference. The record is ``comparison.<point>``.
- ``produce_certificate(rundir, claim_id, plan=)``: ``validation.certificates.create_certificate``
  for a ``requires_certificate`` point, recorded as ``certificate.<claim>``.

Consumer: ``gate_errors`` at ``checkin2_accept`` when the action's RDJ class is R2 or R3 (the
class at which ``decision_gate`` requires this provider). Every such point of the action's
claim needs its registered record whose bytes still verify; a comparison outside its
tolerance or a certificate that no longer recomputes to PASS refuses. A record certifies
the declared comparison only, never the truth of either implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

from .decision_gate import GateError
from .state_io import atomic_json, read_json

PROVIDER = 'comparison'
CHECKS = 'checks'
KIND = 'ravel-check-result'


def check_id(prefix, identity):
    return prefix + '.' + re.sub(r'[^A-Za-z0-9_.-]', '_', identity)[:100]


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _operand(root, rel, pointer=None):
    from .work_order_fidelity import _pointer
    path = Path(root) / rel
    if '..' in Path(rel).parts or Path(rel).is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError(f'comparison operand must be a regular run file: {rel}')
    value = _pointer(read_json(path), pointer or '')
    if type(value) is not dict or not value:
        raise ValueError(f'comparison operand {rel} must be a nonempty object of named numbers')
    for name, number in value.items():
        if type(number) not in (int, float) or not math.isfinite(number):
            raise ValueError(f'comparison operand {rel} value {name} is not a finite number')
    return value, {'path': rel, 'sha256': _sha(path), 'pointer': pointer or ''}


def _register(root, rel, record):
    from . import rdj_custody
    atomic_json(Path(root) / rel, record)
    rdj_custody.register_check_result(root, rel)
    return {'check_id': record['check_id'], 'path': rel, 'sha256': _sha(Path(root) / rel)}


def produce_comparison(rundir, point_id, *, left, right, tolerance, left_pointer=None, right_pointer=None):
    """Compare two implementations' named results; record and register ``comparison.<point>``."""
    root = Path(rundir).resolve()
    if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError('a comparison declares a finite nonnegative relative tolerance')
    a, pin_a = _operand(root, left, left_pointer)
    b, pin_b = _operand(root, right, right_pointer)
    rows = []
    for name in sorted(set(a) | set(b)):
        if name not in a or name not in b:
            rows.append({'name': name, 'left': a.get(name), 'right': b.get(name), 'relative': None, 'within': False})
            continue
        scale = max(abs(a[name]), abs(b[name]))
        relative = 0.0 if scale == 0 else abs(a[name] - b[name]) / scale
        rows.append({'name': name, 'left': a[name], 'right': b[name], 'relative': relative,
                     'within': relative <= tolerance})
    identity = check_id('comparison', point_id)
    record = {'schema_version': 1, 'kind': KIND, 'check_id': identity, 'check': 'implementation_comparison',
              'point_id': point_id, 'operands': [pin_a, pin_b], 'tolerance': tolerance, 'rows': rows,
              'passed': all(r['within'] for r in rows), 'scientific_acceptance': False}
    return _register(root, f'{CHECKS}/comparison/{identity}.json', record)


def produce_certificate(rundir, claim_id, *, plan):
    """Create the claim's reference certificate and record ``certificate.<claim>``."""
    from ..validation import certificates
    root = Path(rundir).resolve()
    identity = check_id('certificate', claim_id)
    out = f'{CHECKS}/certificate/{identity}.cert.json'
    cert = certificates.create_certificate(root, plan, out)
    record = {'schema_version': 1, 'kind': KIND, 'check_id': identity, 'check': 'reference_certificate',
              'claim_id': claim_id, 'certificate': {'path': out, 'sha256': _sha(root / out), 'kind': cert['kind']},
              'passed': cert['verdict'] == 'PASS', 'scientific_acceptance': False}
    return _register(root, f'{CHECKS}/certificate/{identity}.json', record)


def _record(root, identity):
    from . import rdj_custody
    return rdj_custody.check_result(root, identity)


def _point_errors(root, gate, point):
    from ..validation import certificates
    found = []

    def error(code, message, identity):
        found.append(GateError(code, gate, PROVIDER, message,
                               f'produce it with ravel.workflow.comparison ({identity}) after the implementations finish',
                               ('check:' + identity,)))
    if point.get('comparison_required'):
        identity = check_id('comparison', point['id'])
        try:
            record = _record(root, identity)
            for operand in record['operands']:
                if _sha(root / operand['path']) != operand['sha256']:
                    raise ValueError(f'comparison operand {operand["path"]} changed after the comparison')
            if not record['passed']:
                error('comparison_failed', f'{point["id"]}: the implementations disagree beyond the declared '
                      'tolerance; open an RCA ticket', identity)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            error('comparison_missing', f'{point["id"]}: {exc}', identity)
    if point.get('requires_certificate') and point.get('claim_id'):
        identity = check_id('certificate', point['claim_id'])
        try:
            record = _record(root, identity)
            cert = record['certificate']
            if _sha(root / cert['path']) != cert['sha256']:
                raise ValueError('certificate changed after it was recorded')
            result = certificates.validate_certificate(root, cert['path'], kind=cert['kind'])
            if result['status'] != 'PASS':
                error('certificate_failed', f'{point["id"]}: ' + '; '.join(result['errors']), identity)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            error('certificate_missing', f'{point["id"]}: {exc}', identity)
    return found


def gate_errors(rundir, gate, action):
    """Provider ``comparison``: fail closed on R2/R3 ``checkin2_accept`` without the required records."""
    if gate != 'checkin2_accept' or not isinstance(action, dict):
        return []
    from .rdj_loop import compute_class
    from .review_points import _facts, derive
    root = Path(rundir).resolve()
    if compute_class(root, gate, action)[0] not in {'R2', 'R3'}:
        return []
    claim = action.get('claim_id')
    errors = []
    for point in derive(_facts(root)):
        if not (point.get('comparison_required') or point.get('requires_certificate')):
            continue
        if claim is not None and point.get('claim_id') not in (None, claim):
            continue
        errors.extend(_point_errors(root, gate, point))
    return errors


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m ravel.workflow.comparison', description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='command', required=True)
    command = sub.add_parser('compare', help='record an implementation comparison for a review point')
    command.add_argument('--rundir', type=Path, required=True)
    command.add_argument('--point', required=True)
    command.add_argument('--left', required=True)
    command.add_argument('--right', required=True)
    command.add_argument('--tolerance', type=float, required=True)
    command = sub.add_parser('certify', help='record a reference certificate for a claim')
    command.add_argument('--rundir', type=Path, required=True)
    command.add_argument('--claim', required=True)
    command.add_argument('--plan', required=True)
    args = ap.parse_args(argv)
    try:
        if args.command == 'compare':
            value = produce_comparison(args.rundir, args.point, left=args.left, right=args.right, tolerance=args.tolerance)
        else:
            value = produce_certificate(args.rundir, args.claim, plan=args.plan)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'comparison: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
