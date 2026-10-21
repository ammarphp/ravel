"""Confined execution for controller-run work.

No authored code or domain operation of a controller-owned run starts outside this package:

- ``popen(spec, **popen_kwargs)``: the one launcher (``launcher``): no network, an allowlisted
  environment, declared writes only, no store, credentials or RAVEL install; a typed hold
  (``LaunchHeld``) when no qualified sandbox exists, unless the operator allows labelled
  unconfined execution.
- ``probe(kind, target)``: the observed tools, mounts, environment names and network of a
  worker or a launch, compared with the admitted sets (``probe``).
- ``backends()``: which launch backends this host offers.
- ``mint_capability`` / ``verify_capability``: the per-launch capability a facility
  submission must present (``capability``).
- ``require_governed_install``: controller mode runs only installed or sealed code (``identity``).

``spec_for_stage`` builds the launch spec of a supervised stage from its approved stage
specification; the journaled command stays the approved argv.
"""
from __future__ import annotations

from pathlib import Path

from .capability import CapabilityRefused, mint_capability, revoke_capability, verify_capability
from .environment import capsule_from
from .identity import NOT_GOVERNED, UngovernedInstall, code_identity, require_governed_install
from .launcher import (CONFINED, UNCONFINED, UNCONFINED_LABEL, ConfinementRefused, LaunchHeld, Plan, backends,
                       custody_digest, finish, machine_grant, popen, prepare, start)
from .brokers import entry_point
from .probe import probe
from .runs import allow_unconfined, owner, owner_of

__all__ = ['CONFINED', 'UNCONFINED', 'UNCONFINED_LABEL', 'NOT_GOVERNED', 'CapabilityRefused', 'ConfinementRefused',
           'LaunchHeld', 'Plan', 'UngovernedInstall', 'allow_unconfined', 'backends', 'capsule_from', 'code_identity',
           'custody_digest', 'entry_point', 'finish', 'machine_grant', 'mint_capability', 'owner', 'owner_of', 'popen', 'prepare',
           'probe', 'require_governed_install', 'revoke_capability', 'spec_for_stage', 'start', 'verify_capability']


def spec_for_stage(root, command, *, context, cwd=None, env=None, attempt_dir=None, channels=(), limits=None):
    """The launch spec of a supervised stage from its approved ``context['stage_spec']``.

    Reads are the exact approved inputs and the execution custody ledger, never the whole
    run. The environment and input snapshot come from the admitted stage capsule.
    """
    import os
    stage_spec = context.get('stage_spec') or {}
    from ravel.workflow import execution
    from . import brokers
    root = Path(root).resolve()
    inputs = [str(execution.resolve_path(root, p)) for p in stage_spec.get('inputs', [])]
    snapshot = context.get('input_snapshot')
    if snapshot is not None and execution.snapshot(root, inputs) != snapshot:
        raise ConfinementRefused('approved stage inputs changed; nothing was started')
    digests = {}
    for value, fact in (snapshot or {}).items():
        for row in fact.get('files', []):
            path = Path(value) if row['name'] == '.' else Path(value) / row['name']
            digests[str(path)] = row['sha256']
    custody_reads = []
    # Only package workers need to observe registration as the supervisor advances it.
    if brokers.module_invocation(command):
        ledger = root / execution.STATE_NAME
        if ledger.is_file():
            custody_reads.append(str(ledger))
    capsule = context.get('environment_capsule')
    if capsule is None:
        capsule = capsule_from(dict(os.environ if env is None else env))
    stage_limits = dict(context.get('limits') or {})
    if context.get('max_seconds') is not None:
        stage_limits['wall_seconds'] = context['max_seconds']
    stage_limits.update(limits or {})
    spec = {'argv': [str(part) for part in command], 'env': capsule,
            'run_dir': str(Path(root).resolve()), 'stage': context.get('stage'),
            'reads': inputs + custody_reads, 'writes': list(stage_spec.get('outputs', [])),
            'input_digests': digests, 'withheld': list(context.get('withheld', [])),
            'cwd': str(cwd) if cwd else None, 'label': context.get('kind'),
            'controller': {'run_id': owner(root)} if owner(root) else None}
    if attempt_dir is not None:
        spec['attempt_dir'] = str(attempt_dir)
    if channels:
        spec['channels'] = [str(c) for c in channels]
    if stage_limits:
        spec['limits'] = stage_limits
    return {k: v for k, v in spec.items() if v is not None}
