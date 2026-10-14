"""Refuse certification by an oracle used in a fit or candidate selection.

Provenance is a pinned DAG: a fit or selection record declares ``inputs``;
intermediate JSON records can declare their own inputs, and leaf files are
opaque. Selection or tuning oracles must be among those inputs. Content identity
rather than path identity catches copied references. An incomplete/unreadable or
stale closure cannot establish independence.
"""
from __future__ import annotations

import hashlib
import json
import re

from ravel.workflow.world_digest import read_bound, encode


def _read(root, pin):
    if not isinstance(pin, dict) or set(pin) != {'path', 'sha256'} or not isinstance(pin['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', pin['sha256']):
        raise ValueError('input closure requires a path/sha256 pin')
    raw, sha = read_bound(root, pin['path'])
    if sha != pin['sha256']:
        raise ValueError('input-closure pin changed: ' + pin['path'])
    return raw


def check(root, fit, reference):
    """Compute reachable input pins and refuse a reachable certifying reference."""
    closure, errors, seen, active = [], [], {}, set()
    try:
        _read(root, reference)

        def visit(pin, *, is_fit=False):
            raw = _read(root, pin)
            name = pin['path']
            if name in active:
                raise ValueError('input-closure cycle: ' + name)
            if name in seen:
                if seen[name] != pin['sha256']:
                    raise ValueError('conflicting input pins: ' + name)
                return
            seen[name] = pin['sha256']
            active.add(name)
            closure.append(dict(pin))
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                value = None
            if is_fit and (not isinstance(value, dict) or 'inputs' not in value):
                raise ValueError('fit or selection record must declare its inputs')
            if isinstance(value, dict) and 'inputs' in value:
                inputs = value['inputs']
                if not isinstance(inputs, list):
                    raise ValueError('input closure inputs must be a pin list')
                for child in inputs:
                    visit(child)
            active.remove(name)

        visit(fit, is_fit=True)
        if any(pin['sha256'] == reference['sha256'] for pin in closure):
            errors.append('reference_in_input_closure')
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        errors.append('input_closure_invalid: ' + str(exc))
    value = {'schema_version': 1, 'kind': 'input-closure-check', 'fit': fit,
             'reference': reference, 'closure': sorted(closure, key=lambda p: p['path']),
             'independent': not errors, 'errors': errors}
    return {**value, 'sha256': hashlib.sha256(encode(value)).hexdigest()}


def gate_errors(rundir, gate, action):
    """Verifier seam: inspect plan-bound certifications, never action overrides."""
    if gate not in {'checkin2_accept', 'delivery', 'final_task', 'export'}:
        return []
    from ravel.workflow.review_points import _facts
    from ravel.workflow.decision_gate import GateError
    facts = _facts(rundir)
    if facts.get('agent_layer_epoch') != 2:
        return []
    errors = []
    from ravel.workflow.spawn_rows import review_metadata
    certifications = list(facts['plan'].get('certifications', []))
    certifications += [row for node in facts['plan'].get('nodes', [])
                       for row in review_metadata(node).get('certifications', [])]
    for row in certifications:
        result = check(rundir, row['fit'], row['reference'])
        for reason in result['errors']:
            code = 'reference_in_input_closure' if reason == 'reference_in_input_closure' else 'input_closure_invalid'
            errors.append(GateError(code, gate, 'input_closure', reason,
                                    'Reserve a reference that neither fitted nor selected the candidate.',
                                    (row['fit']['path'], row['reference']['path'])))
    return errors
