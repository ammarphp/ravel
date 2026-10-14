"""Placement: the optional ``execution.backend_plan`` pin of science and scoped specs.

A spec may place its one supervised stage on an execution backend::

    "execution": {"backend_plan": {"backend": "native",
                                   "resources": {"cpus": 2, "memory_mib": 4096}}}

At planning time RAVEL composes the backend stage specification from the
placement and the stage's own worker command, pins it as a backend plan inside
the run (``inputs/backend-plan.json``) and makes the supervised command the
backend worker for that plan. The plan file is a stage input and the command
changes, so a changed placement changes the stage fingerprint and the plan digest
that CHECK-IN 1 approval binds. CHECK-IN 1 shows the placement.

Placement ``env`` and ``readonly_trees`` are shown at CHECK-IN 1 with the
resources and the machine-lease wait bound. ``env`` may not set RAVEL control
variables, ``HOME``, ``TMPDIR``, ``PYTHON*`` or the runtime keys the payload
verifies at registration; those stay the approved environment.

The scientific worker then runs as the backend job's payload and proves its
custody chain at registration (``execution.worker_custody``). Payload custody is
implemented for the native backend; container and site placement of a RAVEL
worker are refused until their payload identity can be proven the same way.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

PLAN = 'inputs/backend-plan.json'
SUPPORTED = ('native',)
_KEYS = {'backend', 'resources', 'env', 'readonly_trees'}
# The scientific stages run under supervise(poll=.2, grace=2); backend_stage
# derives the worker command from them in the same way.
WORKER_POLL = 0.2
WORKER_CANCEL_WAIT = 1.0


_FORBIDDEN_EXACT = {'HOME', 'TMPDIR', 'TMP', 'TEMP', 'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                    'NUMEXPR_NUM_THREADS'}
_FORBIDDEN_PREFIXES = ('RAVEL_', 'PYTHON')


def _forbidden_env(name):
    from .execution import RUNTIME_ENVIRONMENT_KEYS
    return (name in _FORBIDDEN_EXACT or name in RUNTIME_ENVIRONMENT_KEYS
            or any(name.startswith(prefix) for prefix in _FORBIDDEN_PREFIXES))


def validate(execution):
    """Validate a spec's ``execution`` field; returns the placement or raises."""
    if not isinstance(execution, dict) or set(execution) != {'backend_plan'}:
        raise ValueError('execution requires exactly backend_plan')
    placement = execution['backend_plan']
    if not isinstance(placement, dict) or not {'backend', 'resources'} <= set(placement) <= _KEYS:
        raise ValueError('backend_plan requires backend and resources, optionally env and readonly_trees')
    if placement['backend'] not in SUPPORTED:
        raise ValueError(f"placement of a RAVEL scientific worker supports {', '.join(SUPPORTED)}; "
                         f"{placement['backend']!r} cannot yet prove its payload custody")
    resources = placement['resources']
    if not isinstance(resources, dict) or 'wall_seconds' in resources:
        raise ValueError('placement resources are cpus, memory_mib and optional disk_mib; '
                         'the wall clock is the study max_seconds')
    names = list(placement.get('env', {}) if isinstance(placement.get('env', {}), dict) else [])
    names += [row.get('env') for row in placement.get('readonly_trees', []) if isinstance(row, dict) and row.get('env')]
    refused = sorted({name for name in names if isinstance(name, str) and _forbidden_env(name)})
    if refused:
        raise ValueError('placement env may not set ' + ', '.join(refused) + '; RAVEL control variables, HOME, TMPDIR, '
                         'PYTHON* and the verified runtime keys stay the approved environment')
    return placement


def stage_spec(placement, stage, argv, outputs, wall_seconds):
    """The backend stage specification for one supervised stage."""
    from . import execution_backend as eb
    spec = {'schema_version': eb.SCHEMA_VERSION, 'backend': placement['backend'], 'stage': stage,
            'argv': list(argv), 'inputs': [],
            'outputs': [{'name': Path(o).name, 'kind': 'directory', 'destination': o} for o in outputs],
            'resources': {**deepcopy(placement['resources']), 'wall_seconds': int(wall_seconds)},
            # The payload re-verifies its approved runtime environment; keep it exact.
            'inherit_runtime_environment': True}
    for key in ('env', 'readonly_trees'):
        if key in placement:
            spec[key] = deepcopy(placement[key])
    return eb.validate_spec(spec)


def pin(rd, stage, argv, outputs, placement, wall_seconds):
    """Write the run's backend plan; return the placed (command, plan path)."""
    from . import execution_backend as eb
    path = Path(rd) / PLAN
    if path.exists():
        raise ValueError('a backend plan already exists in this run')
    plan = eb.prepare(stage_spec(placement, stage, argv, outputs, wall_seconds), base=rd)
    eb.write_plan(plan, path)
    return worker_command(rd, stage), PLAN


def worker_command(rd, stage):
    from . import execution_backend as eb
    return eb.worker_command(Path(rd).resolve(), stage, Path(rd).resolve() / PLAN,
                             poll=WORKER_POLL, cancel_wait=WORKER_CANCEL_WAIT)


def verify(rd, stage, argv, outputs, placement, wall_seconds):
    """The pinned plan still describes this placement of this exact payload."""
    from . import execution_backend as eb
    plan = eb.load_plan(Path(rd) / PLAN, verify_inputs=False)
    expected = stage_spec(placement, stage, argv, outputs, wall_seconds)
    if plan['spec'] != expected or plan['backend'] != eb.get(expected['backend']).describe(expected):
        raise ValueError('pinned backend plan differs from the declared placement or the stage payload')
    return plan


def checkin(rd):
    """The CHECK-IN 1 placement section for a placed run."""
    from . import execution_backend as eb
    path = Path(rd) / PLAN
    from . import machine_lease
    plan = eb.load_plan(path, verify_inputs=False)
    local = eb.is_local(plan)
    wall = plan['spec']['resources']['wall_seconds']
    wait = min(machine_lease.default_wait_seconds(), wall)
    return {'backend': plan['backend']['kind'], 'local': local,
            'resources': plan['spec']['resources'], 'plan': PLAN, 'plan_sha256': plan['plan_sha256'],
            'env': dict(plan['spec'].get('env', {})),
            'readonly_trees': [{k: f[k] for k in ('path', 'sha256', 'env') if k in f} for f in plan['readonly_trees']],
            'lease_wait_seconds': wait if local else None,
            'machine_lease': (f'one native job on this machine; a later launch waits up to {wait:g} s '
                              '(capped by the study max_seconds), then refuses') if local
                             else 'remote slot under the owner-set ceiling'}


def describe(rd):
    section = checkin(rd)
    resources = section['resources']
    env = ', '.join(f'{k}={v}' for k, v in sorted(section['env'].items())) or 'none'
    trees = ', '.join(f"{t['path']} (sha256 {t['sha256'][:12]}{', env ' + t['env'] if 'env' in t else ''})"
                      for t in section['readonly_trees']) or 'none'
    return (f"Placement: {section['backend']} backend, {resources['cpus']} CPU(s), "
            f"{resources['memory_mib']} MiB memory, {resources['wall_seconds']} s wall; "
            f"backend plan {section['plan']} (sha256 {section['plan_sha256'][:12]}). "
            f"Placement environment: {env}. Read-only trees: {trees}. "
            f"Machine lease: {section['machine_lease']}.\n\n")
