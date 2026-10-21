"""Work adoption byte-fidelity seam for the production dispatcher.

The production executors supply next_order/dispatch and worker receipt/waiver authority. This
module adopts only a sealed order's checked bytes; it grants no execution credit,
launch authorization or scientific acceptance. The executor provider must still
verify the worker receipt through the worker interface before admitting a stage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from . import work_order_fidelity as fidelity


def _node(node_id, attempt=1):
    if (not isinstance(node_id, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]*', node_id)
            or '..' in node_id or type(attempt) is not int or attempt < 1):
        raise ValueError('bounded node identity and positive attempt required')


def derive_obligations(order):
    """Derive content obligations from the card and prospective review points.

    The production executor seals the order. CHECK-IN 1 pins this derivation before any worker runs;
    worker-supplied obligation lists are never the source of the derived set.
    """
    from . import role_registry
    role = order['role']
    checks = role_registry.self_checks(role)
    points = order.get('review_points', [])
    if not isinstance(points, list):
        raise ValueError('review_points must be a list')
    required_json = [row for row in order['declared_outputs']
                     if row.get('required') is True and row['path'].endswith('.json')]
    output = order.get('obligation_output')
    if output is None:
        output = next((row['path'] for row in required_json if row.get('kind') == 'obligations'),
                      required_json[0]['path'] if required_json else None)
    if output not in [row['path'] for row in required_json]:
        raise ValueError('required JSON obligation sidecar missing')
    if not output:
        raise ValueError('required obligation output missing')
    result = []
    for identity, source in [(identity, {'self_check': identity}) for identity in checks] + [
            (point['id'], {'review_point': point}) for point in points]:
        if not isinstance(identity, str) or not identity.strip():
            raise ValueError('nonempty derived obligation identity required')
        token = identity.replace('~', '~0').replace('/', '~1')
        result.append({'id': identity, 'output': output, 'pointer': '/obligations/' + token, **source})
    if len({row['id'] for row in result}) != len(result):
        raise ValueError('duplicate derived obligation identity')
    return sorted(result, key=lambda row: row['id'])


def _basis(order):
    from . import role_registry
    return {'role': role_registry.load(order['role'])['id'],
            'card_sha256': role_registry.card_sha256(order['role']),
            'review_points': order.get('review_points', []), 'declared_outputs': order['declared_outputs'],
            'obligation_output': order.get('obligation_output'),
            'obligations': derive_obligations(order)}


def _regular(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('regular work-order authority inputs required')


def pin_obligations(rundir):
    """Write once at CHECK-IN 1, before its approval fingerprint is emitted."""
    root = Path(rundir).absolute()
    target = root / 'inputs/work-obligations.json'
    if target.exists() or target.is_symlink():
        raise ValueError('work obligations already pinned')
    if any((root / p).exists() for p in ('inputs/checkin1_approval.json', 'inputs/science-approval.json')):
        raise ValueError('work obligations must be pinned before CHECK-IN 1 approval')
    checkin_path = root / 'inputs/checkin1.json'
    _regular(checkin_path)
    checkin = fidelity.read_json(checkin_path)
    nodes = {}
    for path in sorted((root / 'inputs/work-orders').glob('*.json')):
        _regular(path)
        order = fidelity.read_json(path)
        _node(order['node_id'])
        if path.stem != order['node_id'] or order.get('order_sha256') != fidelity.digest(order):
            raise ValueError('work-order fidelity: order identity/digest differs')
        nodes[order['node_id']] = _basis(order)
    if not nodes:
        raise ValueError('sealed work orders required before pin-obligations')
    value = {'schema_version': 1, 'kind': 'work-obligations', 'nodes': nodes}
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2).encode() + b'\n'
    _regular(target)
    with target.open('xb') as stream:
        stream.write(raw)
    checkin['work_obligations_sha256'] = hashlib.sha256(raw).hexdigest()
    from .state_io import atomic_json
    atomic_json(checkin_path, checkin)
    return {'path': 'inputs/work-obligations.json', 'sha256': checkin['work_obligations_sha256']}


def approval_input_paths(rundir):
    """Optional legacy-compatible input; a pinned CHECK-IN never drops its path."""
    root = Path(rundir)
    checkin = root / 'inputs/checkin1.json'
    pin = root / 'inputs/work-obligations.json'
    if pin.exists() or checkin.is_file() and 'work_obligations_sha256' in fidelity.read_json(checkin):
        return [str(pin)]
    return []


def checkin_content(record, rundir=None, *, sources=None, session=None):
    """Strip only a byte-verified supplemental pin for proposal shape comparison."""
    value = dict(record)
    if 'steering_policy' in value.get('sections', {}):
        from . import gate_wiring
        if rundir is None or value['sections']['steering_policy'] != gate_wiring.steering_policy(rundir):
            raise ValueError('CHECK-IN 1 steering policy differs from custody')
        value['sections'] = dict(value['sections'])
        value['sections'].pop('steering_policy')
    pin = value.pop('work_obligations_sha256', None)
    if pin is not None:
        path = Path(rundir) / 'inputs/work-obligations.json'
        if sources is None:
            _regular(path)
            observed = session.hash_file(path) if session is not None else hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            raw = sources[str(path)]
            observed = hashlib.sha256(raw).hexdigest()
        if observed != pin:
            raise ValueError('work obligations differ from CHECK-IN 1 pin')
    return value


def verify_obligations_pin(rundir):
    root = Path(rundir)
    path = root / 'inputs/work-obligations.json'
    checkin = root / 'inputs/checkin1.json'
    for member in (path, checkin):
        _regular(member)
        if not member.is_file():
            raise ValueError('work-order fidelity: CHECK-IN 1 obligations pin missing')
    pinned = fidelity.read_json(checkin).get('work_obligations_sha256')
    raw = path.read_bytes()
    if not isinstance(pinned, str) or hashlib.sha256(raw).hexdigest() != pinned:
        raise ValueError('work-order fidelity: obligations sidecar differs from CHECK-IN 1 pin')
    from . import workflow_state
    if (root / 'inputs/checkin1_approval.json').is_file():
        _regular(root / 'inputs/checkin1_approval.json')
        errors = workflow_state.verify_approval(str(root))
    elif (root / 'inputs/science-approval.json').is_file():
        _regular(root / 'inputs/science-approval.json')
        from . import science
        errors = science.verify_approval_envelope(root)
    else:
        raise ValueError('work-order fidelity: CHECK-IN 1 approval missing')
    if errors:
        raise ValueError('work-order fidelity: ' + '; '.join(errors))
    if path.read_bytes() != raw:
        raise ValueError('work-order fidelity: obligations changed during approval verification')
    return json.loads(raw, object_pairs_hook=fidelity._pairs)


def adopt(rundir: Path, node_id: str, attempt: int) -> dict:
    _node(node_id, attempt)
    root = Path(rundir).absolute()
    from .agent_worker import controller_run
    if controller_run(root):
        # A controller-owned run adopts only inside its governed step, from the store's custody records.
        raise ValueError('work-order fidelity: a controller-owned run adopts outputs only inside its governed step')
    workspace = root / 'agent-work' / node_id / str(attempt)
    order_path = root / 'inputs/work-orders' / (node_id + '.json')
    obligations_path = root / 'inputs/work-obligations.json'
    for path in (order_path, obligations_path):
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('regular work-order authority inputs required')
    order = fidelity.read_json(order_path)
    pin = verify_obligations_pin(root)
    if order.get('node_id') != node_id or order.get('order_sha256') != fidelity.digest(order):
        raise ValueError('work-order fidelity: order identity/digest differs')
    basis = _basis(order)
    if pin.get('kind') != 'work-obligations' or pin.get('schema_version') != 1 or pin['nodes'].get(node_id) != basis:
        raise ValueError('work-order fidelity: derived obligations differ from approved basis')
    expected = basis['obligations']
    # Refuse missing/empty content before snapshot or creation of a run output.
    fidelity.require_fidelity(order, workspace, expected_obligations=expected)
    members = fidelity.snapshot(order, workspace)
    checks = fidelity.require_fidelity(order, workspace, expected_obligations=expected, members=members)
    targets = {relative: root / relative for relative in members}
    for relative, target in targets.items():
        if any(p.is_symlink() for p in (target, *target.parents)):
            raise ValueError('adoption destination must be regular: ' + relative)
        if target.exists() and (not target.is_file() or target.read_bytes() != members[relative]):
            raise ValueError('adoption would replace existing content: ' + relative)
    copied = []
    for relative, raw in members.items():
        target = targets[relative]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with target.open('xb') as stream:
                stream.write(raw)
        copied.append({'from': str(workspace / relative), 'to': str(target), 'sha256': hashlib.sha256(raw).hexdigest()})
    return {'node_id': node_id, 'attempt': attempt, 'copied': copied, 'contract_checks': checks}


def main(argv=None):
    ap = argparse.ArgumentParser(prog='ravel work', description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    command = sub.add_parser('adopt', help='check sealed work-order obligations and adopt exact output bytes')
    command.add_argument('--rundir', required=True, type=Path)
    command.add_argument('--node-id', required=True)
    command.add_argument('--attempt', required=True, type=int)
    pin = sub.add_parser('pin-obligations', help='pin card self-checks and order review points at CHECK-IN 1')
    pin.add_argument('--rundir', required=True, type=Path)
    args = ap.parse_args(argv)
    try:
        value = (pin_obligations(args.rundir) if args.command == 'pin-obligations'
                 else adopt(args.rundir, args.node_id, args.attempt))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'adopted': False, 'error': str(exc)}))
        return 1
    print(json.dumps(value, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
