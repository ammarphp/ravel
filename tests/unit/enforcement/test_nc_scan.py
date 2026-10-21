"""Scan rows: every approved grid point stays in the result, as a value or as an explicit hole.

The adversary harvests a scan with a manifested point silently left out. The oracle is the scan
launch audit's refusal naming the omitted point; the positive control reports every point.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nc_cases import CONTROLLER, case, require_controller
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, passes_through, register

OMITTED = 'scan result omits manifest point(s)'


def _two_point_scan(nc):
    aggregate = nc.root / 'scan'
    aggregate.mkdir()
    points = []
    for tag in ('point-a', 'point-b'):
        run = nc.root / 'points' / tag
        (run / 'inputs').mkdir(parents=True)
        (run / 'inputs/native_execution_plan.json').write_text(json.dumps(
            {'required_compute_plan': 'scan', 'plan_sha256': hashlib.sha256(tag.encode()).hexdigest()}))
        points.append({'tag': tag, 'run_dir': str(run)})
    return aggregate, points


@case('SW33', binding=CONTROLLER)
def test_SW33_a_scan_result_that_omits_a_manifested_point_is_refused(nc):
    require_controller()
    from ravel.workflow import launch_authorization, workflow_state
    aggregate, points = _two_point_scan(nc)
    # The per-point GO and launch-history audits are their own cases (G12); here they answer clean.
    nc.patch.setattr(workflow_state, 'verify_checkin2_go', lambda path: [])
    nc.patch.setattr(launch_authorization, 'audit_launches', lambda path, **kwargs: [])

    def audit(reported):
        return launch_authorization.audit_scan_launches(aggregate, {'points': points},
                                                        {'points': [{'tag': tag} for tag in reported]})
    errors = audit(['point-a'])
    assert errors and any(OMITTED in e and 'point-b' in e for e in errors), errors
    assert audit(['point-a', 'point-b']) == []  # positive control: every manifested point is in the result


register(Mutation('SW33', 'ravel.workflow.launch_authorization:audit_scan_launches',
                  passes_through(lambda errors, *a, **k: [e for e in errors if OMITTED not in e]), ('SW33',),
                  binding=MUTATION_CONTROLLER, why='an omitted grid point is not reported'))
