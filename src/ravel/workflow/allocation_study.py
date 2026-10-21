"""One RAVEL study per batch allocation: the driving agent and RAVEL run inside one batch job.

``ravel site study-job submit`` writes a request and a job script into the run's
``logs/allocations/requests/<request id>/`` and submits it: an sbatch script for Slurm
(the default), or an HTCondor submit description (``study.sub``) and its wrapper
(``study.sh``) with ``--scheduler htcondor``. Inside the job the script sets up the
environment (modules, native prefix, virtual environment) and calls
``ravel site study-job run``, which re-verifies the request, records the allocation identity,
runs the agent command headless in the study directory and collects the run directory.

Inside the allocation RAVEL behaves as on a laptop: a local supervisor and local custody,
with the allocation's CPUs. The machine lease is scoped to the allocation
(``machine_lease.lease_scope``), so studies in separate jobs run in parallel and each
allocation still runs one native scientific job at a time.

HTCondor. A ``vanilla`` job runs on an execute node in its own slot; the wrapper selects the
batch-slot lease, so the slot is the machine. A ``local`` job runs on the access point the
request was submitted from, takes no slot and keeps that host's ordinary lease; it can submit
further jobs (``ravel wms launch``) and is the route for a driver that coordinates batch work.
The job proves itself from its own job ad: ``_CONDOR_JOB_AD`` must name the ad inside the
job's owned ``_CONDOR_SCRATCH_DIR`` and the ad must carry ``RavelStudyRequest`` with this
request's id, so a copied variable or another job's ad starts nothing. A site that enforces
no wall time still gets one: the agent's process group is stopped (SIGTERM, then SIGKILL after
a grace period) when ``--time`` runs out, and the receipt records the ending as ``deadline``.
An HTCondor job may be started again after an eviction or an access-point restart; each start
is one attempt in the receipt, the agent sees ``RAVEL_ALLOCATION_ATTEMPT`` (so its command can
resume rather than begin again) and a start beyond ``--max-attempts`` (default 1) runs nothing
and exits ``ATTEMPTS_EXHAUSTED``. A recorded ending is never run again.

Approval. ``--rung none`` admits planning work only: the agent may run intake and prepare
CHECK-IN 1, and the machine lease refuses every heavy stage because the run has no approval.
``--rung smoke|full|scan`` needs the run's approval for that rung through its approval route
(``execution_backend.verify_stage_binding``) when the request is written and again when the job
starts; the approval files' digests are carried in the request, so an approval changed or
withdrawn between submission and start refuses the job before the agent runs. Approval itself
stays a separate, earlier human step; this module never records one.

Controller-owned runs. A request for a directory inside a controller-owned run is written, submitted
and started only while that run is running (its stop, pause and revocation controls). It is submitted
only through the trusted launch capability of the parent site step: the capability admits the exact
job script bytes once, and the scheduler receives that frozen copy. The capability never reaches the
job's environment. Inside the job the run's controls are read again while the agent runs: after a stop
the agent has ``STOP_DRAIN_SECONDS`` to reach its own bounded ending before its group is stopped, and
the receipt records ``stopped``. A run without a controller keeps the behaviour described above.

Lease. The request cannot set the variables that choose the machine lease or the agent's identity
(``RESERVED_ENV``). An HTCondor job starts only when its job ad's universe is the request's and its
lease matches it: the batch-slot lease for ``vanilla``, the access point's host lease for ``local``.

Credentials. The request names no secret. Variables that look like credentials are refused;
``--claude-config-dir`` passes only the path of a login the owner created interactively.

Receipts. ``logs/allocations/<scope>/allocation.json`` records the allocation identity
(cluster, job id, node list, CPUs), the run id, the binding and the agent's exit; every stage
attempt run under the allocation's lease also records ``allocation`` in its execution record.
An HTCondor receipt is keyed ``htcondor-<schedd>-<cluster>.<proc>`` and also lists its attempts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid

from . import machine_lease
from .state_io import atomic_json, read_json

SCHEMA = 1
RUNGS = ('none', 'smoke', 'full', 'scan')
ROUTES = ('checkin1', 'native-plan', 'science', 'likelihood')
NODE = 'allocation-study'
APPROVAL_FILES = {
    'checkin1': ('inputs/checkin1_approval.json', 'inputs/task_contract.json'),
    'native-plan': ('inputs/native_execution_plan.json',),
    'science': ('inputs/science-approval.json', 'inputs/science-plan.json', 'inputs/science.json'),
    'likelihood': ('inputs/scoped-plan.json',),
}
REQUESTS = 'logs/allocations/requests'
SECRET_NAME = re.compile(r'(TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|API_?KEY|AUTH|COOKIE|SESSION_?KEY)', re.I)
PLAIN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+/-]{0,127}')
SLURM_WORD = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')
ENV_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,63}')
SCHEDULERS = ('slurm', 'htcondor')
UNIVERSES = ('vanilla', 'local')
# A path an HTCondor submit description carries literally, without quoting rules.
CONDOR_PATH = re.compile(r'/[A-Za-z0-9._/+,@:=-]*')
CONDOR_KEY = re.compile(r'\+?[A-Za-z][A-Za-z0-9_.]{0,63}')
# Submit commands RAVEL writes or that change how the job starts, ends, restarts or reports.
CONDOR_FIXED = {'kill_sig', 'remove_kill_sig', 'hold_kill_sig', 'on_exit_remove', 'on_exit_hold', 'max_retries',
                'retry_until', 'success_exit_code', 'periodic_remove', 'periodic_hold', 'periodic_release',
                'periodic_vacate', 'leave_in_queue', 'transfer_executable', 'transfer_input_files',
                'transfer_output_files', 'when_to_transfer_output', 'notification', 'notify_user',
                'ravelstudyrequest', 'deferral_time', 'cron_minute', 'cron_hour', 'cron_day_of_month',
                'cron_month', 'cron_day_of_week', 'on_exit_hold_reason', 'job_max_vacate_time',
                'max_job_retirement_time', 'allowed_job_duration', 'allowed_execute_duration', 'want_graceful_removal'}
SECONDS_PER_MINUTE = 60
DEADLINE_GRACE_SECONDS = 120
ATTEMPTS_EXHAUSTED = 75  # an HTCondor start beyond the request's attempt bound: nothing was run
CONDOR_STATES = {1: 'pending', 2: 'running', 3: 'cancelled', 4: 'completed', 5: 'held', 6: 'running', 7: 'pending'}
# Variables RAVEL sets for the job, its machine lease and its agent; a request never replaces them.
RESERVED_ENV = {'HOME', 'PATH', 'VIRTUAL_ENV', 'CLAUDE_CONFIG_DIR', 'RAVEL_NATIVE_BUILD', 'RAVEL_JOBS', 'RAVEL_RUN_ID',
                'RAVEL_LEASE_SCOPE', 'RAVEL_MACHINE_LEASE', 'RAVEL_STATE_DIR', 'RAVEL_JOB_TOKEN', 'RAVEL_WMS_CAPABILITY'}
RESERVED_ENV_PREFIXES = ('RAVEL_ALLOCATION_', 'RAVEL_POINT_', 'RAVEL_TEST_', 'SLURM_', '_CONDOR_')
WRAPPER_PIN = re.compile(r'# wrapper sha256 ([0-9a-f]{64})')
STOPPED = 130  # the controller run is stopped, paused or revoked: the agent was not started or was stopped
STOP_POLL_SECONDS = 15
STOP_DRAIN_SECONDS = 600  # a stopped run's agent gets this long to reach its own bounded ending


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _run_identity(rundir):
    from . import rdj_custody
    run_id = rdj_custody.run_identity(rundir)
    if run_id:
        return {'run_id': run_id, 'source': 'run'}
    # The custody store's own key for a run without a bound identity.
    return {'run_id': 'path-' + hashlib.sha256(str(rundir).encode()).hexdigest()[:32], 'source': 'path'}


def _approval(rundir, route, rung):
    """The verified binding and the digests of the files that carry its approval; empty for ``none``."""
    if rung == 'none':
        return None, {}
    from .execution_backend import verify_stage_binding
    binding = {'rundir': str(rundir), 'node_id': NODE, 'route': route, 'rung': rung}
    try:
        verify_stage_binding(binding)
    except ValueError as exc:
        raise ValueError(f'the run has no approval for the {rung} rung through {route} ({exc}); a heavy stage '
                         'needs its CHECK-IN 1 approval before the allocation is requested. Submit with --rung none '
                         'for planning work') from None
    from . import gate_wiring
    try:
        # A stage dispatch needs the run's steering custody; refuse now, not after the queue wait.
        gate_wiring._steering_journal(rundir)
    except ValueError as exc:
        raise ValueError(f'the run cannot dispatch stages here: {exc}') from None
    digests = {name: _sha(rundir / name) for name in APPROVAL_FILES[route] if (rundir / name).is_file()}
    if not digests:
        raise ValueError(f'the {route} approval route names no approval file in the run; nothing was submitted')
    return binding, digests


def _checkout_commit(checkout):
    try:
        out = subprocess.run(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], capture_output=True, text=True,
                             timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _environment(pairs):
    env = {}
    for pair in pairs or ():
        name, sep, value = pair.partition('=')
        if not sep or not ENV_NAME.fullmatch(name):
            raise ValueError(f'--env takes NAME=VALUE, not {pair!r}')
        if SECRET_NAME.search(name):
            raise ValueError(f'--env {name} looks like a credential; the request carries no secret. Log the agent '
                             'in interactively once on the cluster and pass --claude-config-dir instead')
        if name in RESERVED_ENV or name.startswith(RESERVED_ENV_PREFIXES):
            raise ValueError(f'--env {name} is set by RAVEL for the job, its machine lease or its agent; '
                             'use the corresponding option instead')
        env[name] = value
    return env


def _controller(rundir):
    """``(run id, store)`` of the controller run that owns ``rundir``, else None."""
    from ravel.controller.confine import runs
    found = runs.owner_of(Path(rundir))
    return (found[0], runs.store(found[0])) if found else None


def _check_running(owner, action):
    """Refuse ``action`` unless the controller run is running (its stop, pause and revocation controls)."""
    from ravel.controller import authority
    try:
        return authority.check(owner[1], action)
    except ValueError as exc:
        raise ValueError(f'{action} refused for controller run {owner[0]}: {exc}') from None


def _control(owner):
    """The controller run's current stop view; an unreadable view counts as not running."""
    from ravel.controller import authority
    try:
        return authority.control(owner[1])
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return {'state': 'unreadable', 'error': str(exc)[:300]}


def _halted(view):
    return view.get('state') != 'running' or bool(view.get('ancestor') and view.get('revoked'))


def _condor_field(key):
    # `+Name`, `MY.Name`, `Name` and `na_me` reach the same job attribute.
    key = key.lower()
    return (key[3:] if key.startswith('my.') else key).lstrip('+').replace('_', '')


def _condor_fixed():
    """Normalized names of the submit fields RAVEL writes or controls (the site's job flavour stays open)."""
    from .site_profiles import options as condor
    return {_condor_field(k) for k in (*condor.RESERVED, *condor.ALIASES, *CONDOR_FIXED)} - {'jobflavour'}


def _condor_options(pairs, runtime_attribute):
    """Site submit commands (``KEY=VALUE``) and custom attributes (``+Name=VALUE``) the job may carry."""
    fixed = _condor_fixed()
    if runtime_attribute != 'none':
        fixed.add(_condor_field(runtime_attribute))
    chosen, seen = {}, set()
    for pair in pairs or ():
        key, sep, value = str(pair).partition('=')
        key, value = key.strip(), value.strip()
        if not sep or not CONDOR_KEY.fullmatch(key) or not value:
            raise ValueError(f'--submit-option takes KEY=VALUE or +Attribute=VALUE, not {pair!r}')
        field = _condor_field(key)
        # The submit statement `queue` is RAVEL's; a site's custom `+queue` job attribute is not.
        if field in fixed and key.lower() not in ('+queue', 'my.queue'):
            raise ValueError(f'--submit-option {key} would replace a field RAVEL writes or controls')
        # A trailing backslash would continue the value onto the next submit line.
        if any(c in value for c in '\n\r\x00$') or value.count('"') % 2 or value.endswith('\\'):
            raise ValueError(f'--submit-option {key} needs a single-line value without submit macros, with '
                             'balanced quotes and without a trailing backslash')
        if field in seen:
            raise ValueError(f'--submit-option {key} is given twice')
        seen.add(field)
        chosen[key] = value
    return dict(sorted(chosen.items()))


def _scheduler_resources(scheduler, *, account, partition, cpus, minutes, job_name, universe, memory_mib,
                         runtime_attribute, submit_options, use_x509userproxy, max_attempts):
    """``(resources, restart)`` of one request; scheduler fields never cross to the other scheduler."""
    if scheduler not in SCHEDULERS:
        raise ValueError(f'--scheduler is one of {SCHEDULERS}')
    if not SLURM_WORD.fullmatch(str(job_name or 'ravel')):
        raise ValueError(f'--job-name {job_name!r} is not a plain name')
    condor_only = {'--universe': universe is not None, '--memory': memory_mib is not None,
                   '--runtime-attribute': runtime_attribute is not None, '--submit-option': bool(submit_options),
                   '--use-x509userproxy': bool(use_x509userproxy), '--max-attempts': max_attempts is not None}
    if scheduler == 'slurm':
        given = [label for label, present in condor_only.items() if present]
        if given:
            raise ValueError(f'{", ".join(given)} are HTCondor fields; add --scheduler htcondor or leave them out')
        if account is None or partition is None:
            raise ValueError('a Slurm request needs --account and --partition')
        for label, word in (('--account', account), ('--partition', partition)):
            if not SLURM_WORD.fullmatch(str(word)):
                raise ValueError(f'{label} {word!r} is not a plain Slurm name')
        return {'scheduler': 'slurm', 'account': account, 'partition': partition, 'cpus': cpus, 'minutes': minutes,
                'nodes': 1, 'job_name': job_name or 'ravel-study'}, None
    if account is not None or partition is not None:
        raise ValueError('--account and --partition are Slurm fields; an HTCondor request names its site '
                         'settings with --submit-option')
    universe = 'vanilla' if universe is None else universe
    if universe not in UNIVERSES:
        raise ValueError(f'--universe is one of {UNIVERSES}')
    if memory_mib is not None and (type(memory_mib) is not int or not 1 <= memory_mib <= 4194304):
        raise ValueError('--memory is 1-4194304 MiB')
    runtime_attribute = '+MaxRuntime' if runtime_attribute is None else runtime_attribute
    if runtime_attribute != 'none' and (
            not isinstance(runtime_attribute, str) or not CONDOR_KEY.fullmatch(runtime_attribute)
            or not runtime_attribute.startswith('+')
            or (_condor_field(runtime_attribute) != 'maxruntime' and _condor_field(runtime_attribute) in _condor_fixed())):
        raise ValueError('--runtime-attribute is the site ClassAd that carries the wall time, such as +MaxRuntime, '
                         'or none')
    if type(use_x509userproxy) is not bool:
        raise ValueError('--use-x509userproxy is a flag')
    max_attempts = 1 if max_attempts is None else max_attempts
    if type(max_attempts) is not int or not 1 <= max_attempts <= 10:
        raise ValueError('--max-attempts is 1-10')
    return {'scheduler': 'htcondor', 'universe': universe, 'cpus': cpus, 'minutes': minutes,
            'memory_mib': memory_mib, 'runtime_attribute': runtime_attribute,
            'use_x509userproxy': use_x509userproxy, 'nodes': 1, 'job_name': job_name or 'ravel-study',
            'submit_options': _condor_options(submit_options, runtime_attribute)}, {'max_attempts': max_attempts}


def prepare(rundir, agent, *, cpus, minutes, account=None, partition=None, rung='none', route='checkin1',
            checkout=None, venv=None, prefix=None, modules=(), env=(), claude_config_dir=None, collect_to=None,
            job_name=None, point_override=None, scheduler='slurm', universe=None, memory_mib=None,
            runtime_attribute=None, submit_options=(), use_x509userproxy=False, max_attempts=None):
    """Write the request and its job script; return the request directory. Nothing is submitted.

    Slurm requests get ``study.sbatch``; HTCondor requests get ``study.sub`` and its wrapper ``study.sh``.
    """
    rundir = Path(rundir).resolve()
    if not rundir.is_dir():
        raise ValueError(f'the study directory {rundir} does not exist; create it with ravel initiate first')
    if not agent:
        raise ValueError('give the agent command after --')
    owner = _controller(rundir)
    if owner is not None:
        _check_running(owner, 'an allocation study request')
    if rung not in RUNGS or route not in ROUTES:
        raise ValueError(f'--rung is one of {RUNGS} and --route one of {ROUTES}')
    if type(cpus) is not int or not 1 <= cpus <= 1024 or type(minutes) is not int or not 1 <= minutes <= 43200:
        raise ValueError('--cpus is 1-1024 and --time 1-43200 minutes')
    resources, restart = _scheduler_resources(
        scheduler, account=account, partition=partition, cpus=cpus, minutes=minutes, job_name=job_name,
        universe=universe, memory_mib=memory_mib, runtime_attribute=runtime_attribute,
        submit_options=submit_options, use_x509userproxy=use_x509userproxy, max_attempts=max_attempts)
    if scheduler == 'htcondor' and not CONDOR_PATH.fullmatch(str(rundir)):
        raise ValueError(f'the study directory {rundir} is not a plain path an HTCondor submit description can '
                         'carry literally (letters, digits and ._/+,@:=- only); move the study')
    for module in modules:
        if not PLAIN.fullmatch(module):
            raise ValueError(f'--module {module!r} is not a plain module name')
    checkout = Path(checkout or Path(__file__).resolve().parents[3]).resolve()
    venv = Path(venv).resolve() if venv else checkout / '.venv'
    for label, path in (('--checkout', checkout), ('--venv', venv), ('--prefix', prefix),
                        ('--claude-config-dir', claude_config_dir), ('--collect-to', collect_to)):
        if path is not None and not Path(path).is_absolute():
            raise ValueError(f'{label} must be an absolute path')
    if collect_to is not None and Path(collect_to).resolve().is_relative_to(rundir):
        raise ValueError('--collect-to must lie outside the study directory')
    if not (venv / 'bin/python').exists():
        raise ValueError(f'{venv} has no bin/python; name the RAVEL virtual environment with --venv')
    variables = _environment(env)
    binding, approvals = _approval(rundir, route, rung)
    request_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    directory = rundir / REQUESTS / request_id
    directory.mkdir(parents=True)
    request = {
        'schema_version': SCHEMA, 'kind': 'allocation-study-request', 'request_id': request_id,
        'created_utc': utc_now(), 'rundir': str(rundir), 'run': _run_identity(rundir),
        'rung': rung, 'route': route, 'binding': binding, 'approval_files': approvals,
        'agent': {'argv': list(agent)},
        'resources': resources,
        'environment': {'checkout': str(checkout), 'checkout_commit': _checkout_commit(checkout),
                        'venv': str(venv), 'prefix': str(prefix) if prefix else None, 'modules': list(modules),
                        'variables': variables,
                        'claude_config_dir': str(claude_config_dir) if claude_config_dir else None},
        'collect_to': str(collect_to) if collect_to else None,
    }
    if restart is not None:
        request['restart'] = restart
        # HTCondor starts the wrapper without the submitter's environment; the agent's login lives at home.
        request['environment']['home'] = pwd.getpwuid(os.getuid()).pw_dir
    if point_override is not None:
        from .point_overrides import verify, pin
        verify(point_override['record'], point_override['settings'])
        request['point_override'] = point_override
        request['point_settings'] = pin(point_override['settings'])
    atomic_json(directory / 'request.json', request)
    if scheduler == 'htcondor':
        description, wrapper = render_htcondor(request, directory)
        (directory / 'study.sh').write_text(wrapper)
        (directory / 'study.sub').write_text(description)
    else:
        (directory / 'study.sbatch').write_text(render(request, directory))
    return directory


def render(request, directory):
    """The sbatch script for one request; every value is quoted."""
    q = shlex.quote
    res, envd = request['resources'], request['environment']
    lines = ['#!/bin/bash',
             f"#SBATCH --job-name={res['job_name']}",
             f"#SBATCH --account={res['account']}",
             f"#SBATCH --partition={res['partition']}",
             '#SBATCH --nodes=1', '#SBATCH --ntasks=1',
             f"#SBATCH --cpus-per-task={res['cpus']}",
             f"#SBATCH --time={res['minutes']}",
             f"#SBATCH --output={directory}/slurm-%j.out",
             f'# RAVEL allocation study request {request["request_id"]} for run {request["run"]["run_id"]}',
             '# The request beside this script is the record; write a new request instead of editing this file.',
             '[ -f /etc/profile ] && . /etc/profile >/dev/null 2>&1',
             'set -euo pipefail', *_setup_lines(request),
             # Build parallelism follows the allocation, never the node's CPU count.
             'export RAVEL_JOBS="${SLURM_CPUS_PER_TASK:-1}"',
             f"cd {q(request['rundir'])}",
             f"exec {q(envd['venv'] + '/bin/python')} -m ravel site study-job run --request "
             f"{q(str(Path(directory) / 'request.json'))}"]
    return '\n'.join(lines) + '\n'


def _setup_lines(request):
    """Shell lines every job script shares: modules, native prefix, login, variables, environment."""
    q = shlex.quote
    envd = request['environment']
    lines = [f'module load {q(module)}' for module in envd['modules']]
    if envd['prefix']:
        lines.append(f"export RAVEL_NATIVE_BUILD={q(envd['prefix'])}")
        lines.append(f"if [ -f {q(envd['checkout'] + '/native/scripts/paths.sh')} ]; then "
                     f"set +u; . {q(envd['checkout'] + '/native/scripts/paths.sh')}; set -u; fi")
    if envd['claude_config_dir']:
        lines.append(f"export CLAUDE_CONFIG_DIR={q(envd['claude_config_dir'])}")
    for name, value in sorted(envd['variables'].items()):
        lines.append(f'export {name}={q(value)}')
    return lines + [f"export VIRTUAL_ENV={q(envd['venv'])}", f"export PATH={q(envd['venv'] + '/bin')}:\"$PATH\""]


def render_htcondor(request, directory):
    """``(submit description, wrapper)`` for one HTCondor request.

    The description carries only plain paths (``prepare`` refuses others) and RAVEL's fixed fields, then the
    site's submit options; the wrapper quotes every value. A vanilla job asks for its slot and the site's
    wall-time attribute and selects the batch-slot lease; a local job runs on the access point.
    """
    q = shlex.quote
    res, directory = request['resources'], Path(directory)
    vanilla = res['universe'] == 'vanilla'
    header = [f'# RAVEL allocation study request {request["request_id"]} for run {request["run"]["run_id"]}',
              '# The request beside this file is the record; write a new request instead of editing this file.']
    wrapper = ['#!/bin/bash', *header,
               # The job starts without the submitter's environment; the profile, modules and path helper read HOME.
               f"export HOME={q(request['environment']['home'])}",
               '[ -f /etc/profile ] && . /etc/profile >/dev/null 2>&1', 'set -euo pipefail', *_setup_lines(request),
               # Build parallelism follows the request, never the node's CPU count.
               f"export RAVEL_JOBS={res['cpus']}"]
    if vanilla:
        wrapper.append('export RAVEL_LEASE_SCOPE=batch-slot')
    wrapper += [f"cd {q(request['rundir'])}",
                f"exec {q(request['environment']['venv'] + '/bin/python')} -m ravel site study-job run --request "
                f"{q(str(directory / 'request.json'))}"]
    wrapper_text = '\n'.join(wrapper) + '\n'
    lines = [*header, f'# wrapper sha256 {hashlib.sha256(wrapper_text.encode()).hexdigest()}',
             f"universe = {res['universe']}", 'executable = /bin/bash',
             f"arguments = {directory / 'study.sh'}", f"initialdir = {request['rundir']}",
             f'output = {directory}/condor-$(ClusterId).$(ProcId).out',
             f'error = {directory}/condor-$(ClusterId).$(ProcId).err',
             f"log = {directory / 'condor.log'}", 'getenv = False', f"batch_name = {res['job_name']}",
             f'+RavelStudyRequest = "{request["request_id"]}"']
    if vanilla:
        lines += ['should_transfer_files = NO', f"request_cpus = {res['cpus']}"]
        if res['memory_mib'] is not None:
            lines.append(f"request_memory = {res['memory_mib']}")
        if res['runtime_attribute'] != 'none':
            lines.append(f"{res['runtime_attribute']} = {res['minutes'] * 60}")
    if res['use_x509userproxy']:
        lines.append('use_x509userproxy = true')
    lines += [f'{key} = {value}' for key, value in res['submit_options'].items()]
    lines.append('queue 1')
    return '\n'.join(lines) + '\n', wrapper_text


class NotSubmitted(ValueError):
    """The scheduler was refused or never reached: no job exists for the request."""


def submit(directory, *, sbatch='sbatch', condor_submit='condor_submit'):
    """Submit a prepared request (``sbatch --parsable`` or ``condor_submit -terse``); record and return the job id.

    A request of a controller-owned run is submitted only while the run is running and only through
    the trusted launch capability of its parent site step, which admits the exact job script bytes
    once (``wms_launch.controller_submission``); the scheduler receives that frozen copy.
    """
    directory = Path(directory)
    request = read_json(directory / 'request.json')
    try:
        _recheck(request)
    except ValueError as exc:
        raise NotSubmitted(str(exc)) from None
    htcondor = _scheduler(request) == 'htcondor'
    script = directory / ('study.sub' if htcondor else 'study.sbatch')
    owner = _controller(request['rundir'])
    if owner is None:
        job = _submit_script(directory, script, htcondor, sbatch=sbatch, condor_submit=condor_submit)
        admission = None
    else:
        try:
            _check_running(owner, 'an allocation study submission')
        except ValueError as exc:
            raise NotSubmitted(str(exc)) from None
        from .wms_launch import controller_submission
        reached = []

        def scheduler(snapshot):
            reached.append(snapshot)
            return _submit_script(directory, Path(snapshot), htcondor, sbatch=sbatch, condor_submit=condor_submit)
        try:
            job = controller_submission(script.absolute(), scheduler, run_id=owner[0])
        except NotSubmitted:
            raise
        except ValueError as exc:
            if reached:
                raise
            raise NotSubmitted(f'the controller run {owner[0]} admits no submission of this request without its '
                               f'trusted launch capability: {exc}') from None
        admission = {'controller_run': owner[0], 'jobscript_sha256': _sha(reached[0]), 'snapshot': str(reached[0])}
    record = {'request_id': request['request_id'], 'job_id': job}
    if htcondor:
        record.update(scheduler='htcondor', submitted_utc=utc_now(), condor_submit=condor_submit)
    else:
        record.update(submitted_utc=utc_now(), sbatch=sbatch)
    if admission is not None:
        record['admission'] = admission
    atomic_json(directory / 'submission.json', record)
    return job


def _scheduler_environment():
    """The submitter's environment without the launch capability: the job never receives it."""
    from .wms_policy import CAPABILITY_ENV
    return {name: value for name, value in os.environ.items() if name != CAPABILITY_ENV}


def _submit_script(directory, script, htcondor, *, sbatch, condor_submit):
    """Hand ``script`` to the scheduler; the job id, or ``NotSubmitted`` when nothing can exist."""
    if htcondor:
        pinned = WRAPPER_PIN.search(Path(script).read_text())
        wrapper = directory / 'study.sh'
        if (pinned is None or wrapper.is_symlink() or not wrapper.is_file()
                or _sha(wrapper) != pinned.group(1)):
            raise NotSubmitted('the wrapper study.sh differs from the digest its submit description pins; '
                               'write a new request')
        out = subprocess.run([condor_submit, '-terse', str(script)], capture_output=True, text=True,
                             timeout=300, stdin=subprocess.DEVNULL, env=_scheduler_environment())
        match = re.fullmatch(r'\s*([0-9]+\.[0-9]+)(?: - \1)?\s*', out.stdout) if out.returncode == 0 else None
        if match is None:
            # A nonzero exit is a refusal; an unparsable reply after exit 0 may still hide a job.
            raise (NotSubmitted if out.returncode else ValueError)(
                f'condor_submit refused the request (rc {out.returncode}): '
                f'{(out.stderr.strip() or out.stdout.strip())[-800:]}')
        return match.group(1)
    out = subprocess.run([sbatch, '--parsable', str(script)], capture_output=True, text=True,
                         timeout=300, env=_scheduler_environment())
    job = out.stdout.strip().split(';')[0] if out.returncode == 0 else ''
    if not re.fullmatch(r'[0-9]+', job):
        # A nonzero exit is a refusal; an unparsable reply after exit 0 may still hide a job.
        raise (NotSubmitted if out.returncode else ValueError)(f'sbatch refused the request (rc {out.returncode}): {out.stderr.strip()[-800:]}')
    return job


def _recheck(request):
    """The request's run, binding and approval files, as they hold now."""
    rundir = Path(request['rundir'])
    if not rundir.is_dir():
        raise ValueError(f'the study directory {rundir} is gone')
    if _run_identity(rundir) != request['run']:
        raise ValueError('the study directory names another run than the request; nothing was started')
    if request.get('point_override'):
        from .point_overrides import verify, check_pin
        check_pin(request['point_settings'])
        verify(request['point_override']['record'], request['point_override']['settings'])
    if request['rung'] == 'none':
        return
    binding, digests = _approval(rundir, request['route'], request['rung'])
    if binding != request['binding'] or digests != request['approval_files']:
        raise ValueError('the run approval changed after the request was written; write a new request')


def _scope_records(destination):
    """Copy this allocation's lease records into the run, then remove the scope when nothing holds it.

    A batch slot's lease lives in the job's scratch directory, which the scheduler deletes with the job.
    """
    scope = machine_lease.scope()
    source = Path(scope['directory'])
    copied = []
    if scope['kind'] in ('slurm-job', 'batch-slot') and source.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        for item in sorted(source.iterdir()):
            if item.is_file() and not item.is_symlink():
                shutil.copy2(item, destination / item.name)
                copied.append(item.name)
        held = machine_lease.holder()
        if not (held and held.get('alive')):
            shutil.rmtree(source, ignore_errors=True)
    return {'scope': scope, 'copied': copied}


def _scheduler(request):
    return request['resources'].get('scheduler', 'slurm')


def _name(text):
    """A file-name-safe rendering of a scheduler name."""
    return re.sub(r'[^A-Za-z0-9._-]', '_', text)[:64].lstrip('.') or 'unnamed'


def htcondor_job(request_id, environ=None):
    """The HTCondor job this process runs in, proven by its own job ad; None when not that job.

    The starter names the job ad in ``_CONDOR_JOB_AD`` inside the job's scratch directory
    ``_CONDOR_SCRATCH_DIR``, owned by this user. The ad must carry ``RavelStudyRequest`` with
    ``request_id``: copied variables, an ad elsewhere or another request's job prove nothing.
    """
    environ = os.environ if environ is None else environ
    scratch_text, ad_text = environ.get('_CONDOR_SCRATCH_DIR', ''), environ.get('_CONDOR_JOB_AD', '')
    if not scratch_text or not ad_text:
        return None
    scratch, ad = Path(scratch_text), Path(ad_text)
    try:
        if (not scratch.is_absolute() or scratch.is_symlink() or not scratch.is_dir()
                or scratch.stat().st_uid != os.getuid() or ad.parent != scratch or ad.is_symlink() or not ad.is_file()):
            return None
        text = ad.read_text(errors='replace')
    except OSError:
        return None
    fields = {}
    for line in text.splitlines():
        name, sep, value = line.partition('=')
        if sep:
            value = value.strip()
            fields[name.strip()] = value[1:-1] if len(value) >= 2 and value[0] == value[-1] == '"' else value
    cluster, proc = fields.get('ClusterId', ''), fields.get('ProcId', '')
    if (fields.get('RavelStudyRequest') != request_id or not re.fullmatch(r'[0-9]{1,12}', cluster)
            or not re.fullmatch(r'[0-9]{1,9}', proc)):
        return None
    global_id = fields.get('GlobalJobId') or None
    schedd = global_id.split('#', 1)[0] if global_id and '#' in global_id else None
    universe = {'5': 'vanilla', '12': 'local'}.get(fields.get('JobUniverse', ''), fields.get('JobUniverse') or None)
    return {'key': '-'.join(['htcondor'] + ([_name(schedd)] if schedd else []) + [f'{cluster}.{proc}']),
            'schedd': schedd, 'cluster': cluster, 'proc': proc, 'global_job_id': global_id, 'universe': universe}


def _begin_attempt(path, receipt, request):
    """``(receipt, attempt, ending)`` for one start of an HTCondor job.

    A start after a recorded ending runs nothing and returns that ending; a start after an ending
    nobody recorded (an eviction, a killed process, a restarted access point) is a new attempt
    within the request's bound, and beyond it the receipt records ``attempts-exhausted``.
    """
    previous = read_json(path) if path.is_file() else None
    attempts = []
    if previous is not None:
        if previous.get('request_id') != request['request_id'] or previous.get('run') != request['run']:
            raise ValueError('the allocation receipt of this job belongs to another request; nothing was started')
        if previous.get('state') not in ('running', 'interrupted'):
            code = previous.get('agent_exit')
            return previous, None, code if type(code) is int else (
                STOPPED if previous.get('state') == 'stopped' else ATTEMPTS_EXHAUSTED)
        attempts = [dict(a) for a in previous.get('attempts') or []]
        if not attempts:
            attempts = [{'attempt': 1, 'started_utc': previous.get('started_utc'), 'state': 'interrupted'}]
        elif attempts[-1].get('state') == 'running':
            attempts[-1]['state'] = 'interrupted'
        if len(attempts) >= request['restart']['max_attempts']:
            previous.update(state='attempts-exhausted', attempts=attempts, ended_utc=utc_now())
            atomic_json(path, previous)
            return previous, None, ATTEMPTS_EXHAUSTED
    attempt = len(attempts) + 1
    attempts.append({'attempt': attempt, 'started_utc': receipt['started_utc'], 'state': 'running'})
    return receipt | {'attempt': attempt, 'max_attempts': request['restart']['max_attempts'],
                      'attempts': attempts}, attempt, None


def _wait_bounded(child, wall_seconds, *, grace_seconds=None):
    """``(exit code, deadline reached)``: wait for the agent, stopping its process group when the wall time ends.

    At the bound the group gets SIGTERM, and SIGKILL when it is still there after the grace period.
    """
    try:
        return child.wait(timeout=wall_seconds), False
    except subprocess.TimeoutExpired:
        pass
    return _terminate(child, grace_seconds), True


def _terminate(child, grace_seconds=None):
    """Stop the agent's process group: SIGTERM, then SIGKILL after the grace period; its exit code."""
    grace = DEADLINE_GRACE_SECONDS if grace_seconds is None else grace_seconds
    for signum, timeout in ((signal.SIGTERM, grace), (signal.SIGKILL, None)):
        try:
            os.killpg(child.pid, signum)
        except OSError:
            pass
        try:
            return child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            continue


def _wait_controlled(child, wall_seconds, owner, *, grace_seconds=None, poll_seconds=None, drain_seconds=None):
    """``(exit code, ending, stop view)`` for an agent of a controller-owned run.

    ``ending`` is ``finished``, ``deadline`` (the wall time, when one is given) or ``stopped``. A stop,
    pause or revocation of the run, or an unreadable control view, gives the agent the drain period to
    reach its own bounded ending; a group still running at its end is stopped. A resume within the
    period cancels it. The view seen last is returned.
    """
    poll = STOP_POLL_SECONDS if poll_seconds is None else poll_seconds
    drain = STOP_DRAIN_SECONDS if drain_seconds is None else drain_seconds
    deadline = None if wall_seconds is None else time.monotonic() + wall_seconds
    halted_since, seen = None, None
    while True:
        wait = poll if deadline is None else max(0.0, min(poll, deadline - time.monotonic()))
        try:
            return child.wait(timeout=wait), 'finished', seen
        except subprocess.TimeoutExpired:
            pass
        now = time.monotonic()
        if deadline is not None and now >= deadline:
            return _terminate(child, grace_seconds), 'deadline', seen
        view = _control(owner)
        if _halted(view):
            seen = view
            halted_since = now if halted_since is None else halted_since
            if now - halted_since >= drain:
                return _terminate(child, grace_seconds), 'stopped', seen
        else:
            halted_since = None


def _lease_matches(request, job):
    """An HTCondor job keeps the lease its universe stands for: one native job per slot or per access point."""
    universe = request['resources']['universe']
    if job.get('universe') != universe:
        raise ValueError(f'the job ad runs in the {job.get("universe")} universe, not the {universe} universe of '
                         'this request; nothing was started')
    batch_slot = os.environ.get('RAVEL_LEASE_SCOPE') == 'batch-slot'
    if batch_slot != (universe == 'vanilla') or (
            batch_slot and machine_lease.lease_scope().get('kind') != 'batch-slot'):
        raise ValueError('the machine lease scope does not match the job: a vanilla job holds its batch-slot lease '
                         'and a local job the access point\'s host lease; nothing was started')


def run(request_path, *, popen=subprocess.Popen):
    """Inside the allocation: verify, record the allocation, run the agent, collect. Returns the agent's exit."""
    request_path = Path(request_path).resolve()
    request = read_json(request_path)
    if request.get('kind') != 'allocation-study-request' or request.get('schema_version') != SCHEMA:
        raise ValueError(f'{request_path} is not an allocation study request')
    htcondor = _scheduler(request) == 'htcondor'
    if htcondor:
        job = htcondor_job(request['request_id'])
        if job is None:
            raise ValueError('this process is not inside the HTCondor job of this request (the job ad named by '
                             '_CONDOR_JOB_AD, inside the owned _CONDOR_SCRATCH_DIR, must carry its '
                             'RavelStudyRequest); submit the request with ravel site study-job submit '
                             '--scheduler htcondor')
        key = job['key']
    else:
        allocation = machine_lease.slurm_allocation()
        if allocation is None:
            raise ValueError('this process is not inside a Slurm allocation (SLURM_JOB_ID with its job cgroup); '
                             'submit the request with ravel site study-job submit')
        key = machine_lease.allocation_key(allocation)
    _recheck(request)
    if htcondor:
        _lease_matches(request, job)
    rundir = Path(request['rundir'])
    owner = _controller(rundir)
    receipt_dir = rundir / 'logs/allocations' / key
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt = {'schema_version': SCHEMA, 'kind': 'allocation-study-receipt', 'request_id': request['request_id'],
               'request_sha256': _sha(request_path), 'run': request['run'], 'rundir': str(rundir),
               'rung': request['rung'], 'route': request['route'], 'binding': request['binding'],
               'approval_files': request['approval_files'], 'allocation': machine_lease.allocation_identity(),
               'lease_directory': str(machine_lease.machine_dir()), 'started_utc': utc_now(),
               'agent': {'argv': request['agent']['argv'], 'log': str(receipt_dir / 'agent.log')},
               'state': 'running'}
    if owner is not None:
        receipt['controller_run'] = owner[0]
    attempt = None
    if htcondor:
        receipt['scheduler'] = 'htcondor'
        receipt['job'] = {name: value for name, value in job.items() if name != 'key'}
        receipt, attempt, ending = _begin_attempt(receipt_dir / 'allocation.json', receipt, request)
        if ending is not None:
            print(json.dumps({'rundir': str(rundir), 'receipt': str(receipt_dir / 'allocation.json'),
                              'state': receipt.get('state'), 'agent_exit': receipt.get('agent_exit')}))
            return ending
    if owner is not None:
        try:
            _check_running(owner, 'an allocation study start')
        except ValueError as exc:
            # A stopped run starts nothing; the ending is recorded so a restart never runs it.
            receipt.update(state='stopped', agent_exit=None, ended_utc=utc_now(), controller_stop=str(exc)[:600])
            if htcondor:
                receipt['attempts'][-1].update(state='stopped', ended_utc=receipt['ended_utc'])
            atomic_json(receipt_dir / 'allocation.json', receipt)
            print(json.dumps({'rundir': str(rundir), 'receipt': str(receipt_dir / 'allocation.json'),
                              'state': 'stopped', 'agent_exit': None}))
            return STOPPED
    atomic_json(receipt_dir / 'allocation.json', receipt)
    env = dict(os.environ)
    from .wms_policy import CAPABILITY_ENV
    env.pop(CAPABILITY_ENV, None)  # a submitter's launch capability never reaches the agent
    env.update(RAVEL_ALLOCATION_REQUEST=str(request_path), RAVEL_ALLOCATION_RECEIPT=str(receipt_dir / 'allocation.json'),
               RAVEL_RUN_ID=request['run']['run_id'], RAVEL_ALLOCATION_RUNG=request['rung'],
               RAVEL_JOBS=os.environ.get('SLURM_CPUS_PER_TASK') or str(request['resources']['cpus']))
    if htcondor:
        env.update(RAVEL_ALLOCATION_ATTEMPT=str(attempt), RAVEL_JOBS=str(request['resources']['cpus']))
    if request.get('point_override'):
        env['RAVEL_POINT_RECEIPT_SHA256'] = request['point_override']['record']['receipt_sha256']
        env['RAVEL_POINT_SETTINGS'] = request['point_override']['settings']
    received = []
    with (receipt_dir / 'agent.log').open('ab') as log:
        try:
            child = popen(request['agent']['argv'], cwd=rundir, env=env, stdout=log, stderr=subprocess.STDOUT,
                          stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            receipt.update(state='not-started', error=str(exc), ended_utc=utc_now())
            if htcondor:
                receipt['attempts'][-1].update(state='not-started', ended_utc=receipt['ended_utc'])
            atomic_json(receipt_dir / 'allocation.json', receipt)
            raise ValueError(f'the agent command did not start: {exc}') from None

        def forward(signum, _frame):
            # The scheduler's time limit, removal or eviction reaches this process first; the agent's group follows.
            received.append(signum)
            try:
                os.killpg(child.pid, signum)
            except OSError:
                pass
        previous = {s: signal.signal(s, forward) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGUSR1)}
        stopped = None
        try:
            if owner is not None:
                code, ending, stopped = _wait_controlled(
                    child, request['resources']['minutes'] * SECONDS_PER_MINUTE if htcondor else None, owner)
                reached = ending == 'deadline'
                stopped = stopped if ending == 'stopped' else None
            elif htcondor:
                code, reached = _wait_bounded(child, request['resources']['minutes'] * SECONDS_PER_MINUTE)
            else:
                code, reached = child.wait(), False
        finally:
            for s, handler in previous.items():
                signal.signal(s, handler)
    state = ('deadline' if reached else 'stopped' if stopped is not None
             else 'interrupted' if htcondor and received else 'finished')
    receipt.update(state=state, agent_exit=code, ended_utc=utc_now(),
                   lease=_scope_records(receipt_dir / 'lease-scope'))
    if stopped is not None:
        receipt['controller_stop'] = stopped
    if htcondor:
        receipt['attempts'][-1].update(state=state, agent_exit=code, ended_utc=receipt['ended_utc'],
                                       deadline_reached=reached,
                                       signal=signal.Signals(received[0]).name if received else None)
    if request.get('collect_to') and state not in ('interrupted', 'stopped'):
        # Named by run id as well: two studies may share a directory name.
        target = Path(request['collect_to']) / f"{rundir.name}-{request['run']['run_id']}"
        receipt['collected_to'] = str(target)
        atomic_json(receipt_dir / 'allocation.json', receipt)
        shutil.copytree(rundir, target, symlinks=True, dirs_exist_ok=True)
    else:
        atomic_json(receipt_dir / 'allocation.json', receipt)
    print(json.dumps({'rundir': str(rundir), 'receipt': str(receipt_dir / 'allocation.json'),
                      'collected_to': receipt.get('collected_to'), 'agent_exit': code}))
    return code


def add_parser(sub):
    p = sub.add_parser('study-job', help='run one study per batch allocation (Slurm or HTCondor): write, submit '
                                         'and run a request')
    verbs = p.add_subparsers(dest='verb', required=True)
    s = verbs.add_parser('submit', help='write the request and job script, then submit (--dry-run writes only)')
    s.add_argument('--rundir', required=True, help='the study (run) directory; it must already exist')
    s.add_argument('--scheduler', choices=SCHEDULERS, default='slurm')
    s.add_argument('--account', help='Slurm account')
    s.add_argument('--partition', help='Slurm partition')
    s.add_argument('--universe', choices=UNIVERSES,
                   help='HTCondor: vanilla (an execute-node slot; default) or local (the access point; no slot, '
                        'can submit batch work)')
    s.add_argument('--memory', type=int, dest='memory_mib', help='HTCondor: request_memory in MiB (vanilla)')
    s.add_argument('--submit-option', action='append', default=[], dest='submit_options',
                   help='HTCondor: one site submit command KEY=VALUE or custom attribute +Name=VALUE, for '
                        'example +queue="long" (repeatable); RAVEL-controlled fields are refused')
    s.add_argument('--runtime-attribute',
                   help='HTCondor: site ClassAd that carries the wall time in seconds (default +MaxRuntime; '
                        'none leaves it out)')
    s.add_argument('--max-attempts', type=int,
                   help='HTCondor: starts allowed in total, the first included; later starts follow evictions or '
                        'access-point restarts (default 1, at most 10)')
    s.add_argument('--use-x509userproxy', action='store_true',
                   help='HTCondor: let the scheduler hand the submitter\'s grid proxy to the job')
    s.add_argument('--cpus', type=int, required=True)
    s.add_argument('--time', type=int, required=True, dest='minutes', help='wall time in minutes')
    s.add_argument('--rung', choices=RUNGS, default='none',
                   help='none: planning only (heavy stages refused); smoke/full/scan need the approval')
    s.add_argument('--route', choices=ROUTES, default='checkin1')
    s.add_argument('--checkout', help='RAVEL checkout on the cluster (default: this package\'s checkout)')
    s.add_argument('--venv', help='RAVEL virtual environment (default: <checkout>/.venv)')
    s.add_argument('--prefix', help='native toolchain prefix (RAVEL_NATIVE_BUILD)')
    s.add_argument('--module', action='append', default=[], dest='modules', help='environment module to load')
    s.add_argument('--env', action='append', default=[], help='NAME=VALUE for the job (never a credential)')
    s.add_argument('--claude-config-dir', help='CLAUDE_CONFIG_DIR of the owner\'s interactive cluster login')
    s.add_argument('--collect-to', help='directory that receives a copy of the run directory at the end')
    s.add_argument('--job-name')
    s.add_argument('--dry-run', action='store_true')
    s.add_argument('agent', nargs=argparse.REMAINDER, help='-- then the agent command, run in the study directory')
    r = verbs.add_parser('run', help='inside the allocation (called by the job script)')
    r.add_argument('--request', required=True)
    return p


def main_args(args):
    if args.verb == 'run':
        return run(args.request)
    agent = args.agent[1:] if args.agent[:1] == ['--'] else args.agent
    directory = prepare(args.rundir, agent, account=args.account, partition=args.partition, cpus=args.cpus,
                        minutes=args.minutes, rung=args.rung, route=args.route, checkout=args.checkout,
                        venv=args.venv, prefix=args.prefix, modules=args.modules, env=args.env,
                        claude_config_dir=args.claude_config_dir, collect_to=args.collect_to, job_name=args.job_name,
                        scheduler=args.scheduler, universe=args.universe, memory_mib=args.memory_mib,
                        runtime_attribute=args.runtime_attribute, submit_options=args.submit_options,
                        use_x509userproxy=args.use_x509userproxy, max_attempts=args.max_attempts)
    if args.scheduler == 'htcondor':
        result = {'request': str(directory / 'request.json'), 'script': str(directory / 'study.sub'),
                  'wrapper': str(directory / 'study.sh')}
    else:
        result = {'request': str(directory / 'request.json'), 'script': str(directory / 'study.sbatch')}
    if not args.dry_run:
        result['job_id'] = submit(directory)
    print(json.dumps(result, indent=2))
    return 0


def collect(directory, *, scheduler=None, job_id=None):
    """Read the ordinary allocation/collection receipts and current scheduler state.

    Missing accounting is unknown, never evidence that a submission can be retried.
    ``scheduler(job_id)`` is an injectable read-only observation seam.
    """
    directory = Path(directory)
    request = read_json(directory / 'request.json')
    submission = read_json(directory / 'submission.json') if (directory / 'submission.json').is_file() else {}
    job = submission.get('job_id', job_id)
    if job_id is not None and job != job_id:
        raise ValueError('submission identity differs from collection caller')
    roots = [Path(request['rundir'])]
    if request.get('collect_to'):
        roots.append(Path(request['collect_to']) / f"{roots[0].name}-{request['run']['run_id']}")
    receipt = None
    for root in roots:
        for path in sorted((root / 'logs/allocations').glob('*/allocation.json')):
            row = read_json(path)
            if row.get('request_id') == request['request_id'] and row.get('run') == request['run']:
                if row.get('request_sha256') != _sha(directory / 'request.json'):
                    raise ValueError('allocation receipt request digest differs')
                receipt = {'path': str(path), 'sha256': _sha(path), 'record': row}
    reader = scheduler or (_condor_state if _scheduler(request) == 'htcondor' else _scheduler_state)
    observed = reader(job) if job else 'unknown'
    if receipt:
        row = receipt['record']
        if row.get('state') == 'finished':
            if observed in ('completed', 'missing'):
                observed = 'completed' if row.get('agent_exit') == 0 else 'failed'
        elif row.get('state') == 'deadline':
            if observed in ('completed', 'missing'):
                observed = 'timed-out'
        elif row.get('state') == 'stopped':
            if observed in ('completed', 'missing'):
                observed = 'cancelled'
        elif row.get('state') in ('not-started', 'attempts-exhausted'):
            if observed not in ('pending', 'running', 'unknown'):
                observed = 'failed'
    # A scheduler exit alone does not establish successful agent execution/collection.
    if observed == 'completed' and not (receipt and receipt['record'].get('state') == 'finished'):
        observed = 'missing'
    return {'status': observed, 'job_id': job, 'receipt': receipt,
            'result_root': str(roots[-1] if roots[-1].is_dir() else roots[0])}


def _scheduler_state(job):
    from .backends.site_batch import SLURM_STATES
    for command in (['squeue', '-h', '-j', job, '-o', '%T'],
                    ['sacct', '-j', job, '-n', '-P', '-X', '-o', 'State']):
        try:
            out = subprocess.run(command, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return 'unknown'
        if out.returncode:
            return 'unknown'
        if out.stdout.strip():
            state = out.stdout.strip().splitlines()[0].split('|')[0].split()[0].rstrip('+')
            if state == 'TIMEOUT':
                return 'timed-out'
            mapped = SLURM_STATES.get(state, 'unknown')
            return 'completed' if mapped == 'exited' else mapped
    return 'missing'


def _condor_state(job):
    """The HTCondor state of one job, from the queue and then the history; read-only."""
    for command in (['condor_q', job, '-af', 'JobStatus'], ['condor_history', job, '-limit', '1', '-af', 'JobStatus']):
        try:
            out = subprocess.run(command, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return 'unknown'
        if out.returncode:
            return 'unknown'
        if out.stdout.strip():
            status = out.stdout.split()[0]
            return CONDOR_STATES.get(int(status), 'unknown') if status.isdigit() else 'unknown'
    return 'missing'
