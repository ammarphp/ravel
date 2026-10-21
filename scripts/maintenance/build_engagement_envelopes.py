#!/usr/bin/env python3
"""Rebuild engagement projections from installed route and instruction bytes.

No models or scientific execution. --check compares exact bytes, including all
source pins. Missing peer packages produce an explicit unavailable inventory.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from ravel.controller.engagement.builder import (InstalledInstructions, PacketScopeUnavailable,  # noqa: F401
                                                 build_tier, installed_instructions, math_tokens)
from ravel.controller.engagement.envelope import project  # noqa: F401
from ravel.controller.engagement.policy import load_policy, role_cards
from ravel.controller.engagement.records import TIERS, EngagementRefused, digest


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()


def route_specs(root):
    result, pins = [], {}
    for path in sorted(root.glob('*.json')):
        raw = path.read_bytes()
        pins[path.name] = sha256(raw).hexdigest()
        document = json.loads(raw)
        result.extend(document.get('specs', [document]))
    identities = [r['id'] for r in result]
    if len(identities) != len(set(identities)):
        raise EngagementRefused('duplicate route spec identity')
    return sorted(result, key=lambda r: r['id']), pins


def build(specs, *, cards, instructions, policy, calibration, source_pins):
    """Compile actual packets; unsupported reductions retain the complete full-seat upper bound."""
    routes, packets = {}, {}
    for spec in sorted(specs, key=lambda r: r['id']):
        # Template deliverables are selectors. Give each a stable identity for complete coverage.
        plan = {**deepcopy(spec), 'route': {'id': spec['id']}}
        plan['deliverables'] = [{**d, 'id': d.get('id', f'deliverable-{i}')} for i, d in enumerate(spec.get('deliverables', []))]
        routes[spec['id']], packets[spec['id']] = {}, {}
        for tier in TIERS:
            try:
                entry, sessions = build_tier(plan, spec, tier, cards, instructions, policy, calibration)
            except PacketScopeUnavailable as exc:
                # Preserve the scope check: compile and validate the full roster instead.
                # This is an upper bound until the installed renderer supports reduction.
                entry, sessions = build_tier(plan, spec, 'full', cards, instructions, policy, calibration)
                entry['projection_tier'] = 'full'
                entry['scope_reason'] = str(exc)
            routes[spec['id']][tier] = entry
            packets[spec['id']][tier] = sessions
    body = {'schema_version': 1, 'status': 'ready' if specs else 'unavailable',
            'reason': None if specs else 'no installed route specs; regenerate after integration',
            'policy_sha256': policy['sha256'], 'calibration_sha256': digest(calibration),
            'source_pins': source_pins, 'routes': routes, 'packets': packets}
    return {**body, 'sha256': digest(body)}


def source_inventory(data_root):
    pins = {}
    # Include catalogue/manifests/source policy, cards/registration, route membership and method rungs.
    for relative in ('instructions', 'roles', 'methods'):
        for path in sorted((data_root / relative).rglob('*.json')):
            pins[path.relative_to(data_root).as_posix()] = sha256(path.read_bytes()).hexdigest()
    # A changed builder affects packet bytes even if the catalogue itself did not change.
    for package in ('instructions', 'engagement'):
        for path in sorted((ROOT / 'src/ravel/controller' / package).glob('*.py')):
            pins['code/' + package + '/' + path.name] = sha256(path.read_bytes()).hexdigest()
    # Capability data changes the complete index in every packet. Bind its
    # package source population too, including future inventory registrations.
    from ravel.workflow.capability_catalogue import catalogue
    capabilities = catalogue()
    pins['capabilities'] = {row['path'].removeprefix('src/ravel/'): row['sha256']
                            for row in capabilities['sources'] if row['path'].startswith('src/ravel/')}
    pins['builder'] = sha256(Path(__file__).read_bytes()).hexdigest()
    return pins


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--routes', type=Path, default=ROOT / 'src/ravel/data/controller/routes')
    parser.add_argument('--out', type=Path, default=ROOT / 'src/ravel/data/controller/engagement/envelopes.json')
    args = parser.parse_args(argv)
    policy = load_policy()
    calibration = json.loads((ROOT / 'src/ravel/data/controller/engagement/calibration.json').read_text())
    specs, route_pins = route_specs(args.routes)
    pins = source_inventory(ROOT / 'src/ravel/data')
    pins['routes'] = route_pins
    try:
        if specs:
            instructions = installed_instructions()
            cards = role_cards()
        else:
            instructions, cards = None, {}
        result = build(specs, cards=cards, instructions=instructions, policy=policy,
                       calibration=calibration, source_pins=pins)
    except (ImportError, ValueError) as exc:
        print('engagement envelope build refused: ' + str(exc), file=sys.stderr)
        return 1
    raw = encode(result)
    if args.check:
        if not args.out.is_file() or args.out.read_bytes() != raw:
            print('engagement envelopes stale: rebuild after route, catalogue or calibration changes', file=sys.stderr)
            return 1
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(raw)
    print(f"engagement envelopes: {result['status']}; {len(specs)} route specs")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
