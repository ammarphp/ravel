"""RAVEL entry points that run beside the controller, not inside a launch sandbox.

A few RAVEL commands perform governed operations themselves: they take machine leases, run
nested supervised launches and submit work to an execution backend. They cannot run inside a
launch sandbox, and they do not need to: none of them executes authored code or a domain
operation in its own process. Every payload they start runs confined where it starts (a
supervised launch through this package, the native backend's confined payload, a
network-less OCI container or a site batch job).

A command is one of them only when it runs this controller's own interpreter and installed
RAVEL (literal paths: another environment that shares the base interpreter is another
installation) and names a registered module and action. Anything else is confined.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import sysconfig

ENTRY_POINTS = {
    ('ravel.physics.native_pipeline', 'run'):
        'native orchestration: every stage it runs is its own confined governed launch',
    ('ravel.workflow.execution_backend', 'worker'):
        'execution-backend broker: a native payload runs in the launch sandbox, an OCI payload in a '
        'network-less container and a site payload at the site',
    ('ravel.workflow.partitioned_execution', 'run'):
        'partition driver: every partition runs through the execution backend',
}
SCIENCE_WORKER = 'ravel.physics.science_worker'
# Approved science modes whose adapter submits all of its work through the execution backend.
SCIENCE_BACKEND_MODES = frozenset({'amplitude-integration', 'amplitude-crosscheck', 'event-production',
                                   'weighted-events'})
# `ravel <command>` console forms of the module entry points (``cli.FOCUSED_COMMANDS``).
CONSOLE_COMMANDS = {'partitions': 'ravel.workflow.partitioned_execution',
                    'backend': 'ravel.workflow.execution_backend'}


def _bootstrap():
    from ravel import paths
    return str(Path(paths.__file__).with_name('_bootstrap.py'))


def module_invocation(command):
    """``(module, arguments)`` when ``command`` runs a RAVEL module with this controller's own
    interpreter and installation, else None."""
    command = [str(part) for part in command]
    if len(command) < 2:
        return None
    executable = os.path.abspath(command[0])
    if executable == os.path.abspath(sys.executable) and len(command) >= 3:
        if command[1] == '-m' or os.path.abspath(command[1]) == _bootstrap():
            return command[2], command[3:]
        return None
    if executable == str(Path(sysconfig.get_path('scripts')) / 'ravel') and command[1] in CONSOLE_COMMANDS:
        return CONSOLE_COMMANDS[command[1]], command[2:]
    return None


def _approved_science_mode(root):
    try:
        from ravel.workflow.state_io import read_json
        return read_json(Path(root) / 'inputs/science.json').get('mode')
    except (OSError, ValueError, AttributeError, TypeError):
        return None


def entry_point(root, command):
    """The registered controller-side entry point ``command`` runs, or None (the launch is confined)."""
    invocation = module_invocation(command)
    if invocation is None:
        return None
    module, arguments = invocation
    action = arguments[0] if arguments else None
    reason = ENTRY_POINTS.get((module, action))
    if reason is not None:
        return {'class': 'controller-side', 'entry_point': f'{module} {action}', 'reason': reason}
    if module == SCIENCE_WORKER:
        mode = _approved_science_mode(root)
        if mode in SCIENCE_BACKEND_MODES:
            return {'class': 'controller-side', 'entry_point': f'{module} ({mode})',
                    'reason': f'approved science mode {mode} submits all of its work through the execution backend'}
    return None


def environment(source=None):
    """Scrub startup hooks and secrets even in the trusted orchestration process.

    Its package path is fixed to this installation. Only the authenticated lease and custody
    channels survive; payloads independently receive their admitted environment capsule.
    """
    from . import environment as capsule, locations
    from ravel.workflow import machine_lease
    source = os.environ if source is None else source
    env, _ = capsule.scrub(capsule.capsule_from(source))
    for name in ('LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'CONDA_PREFIX'):
        env.pop(name, None)
    for name in (machine_lease.ENV,):
        if source.get(name):
            env[name] = source[name]
    env['PYTHONPATH'] = str(locations.package_root())
    env['PYTHONNOUSERSITE'] = '1'
    env['PYTHONSAFEPATH'] = '1'
    return env
