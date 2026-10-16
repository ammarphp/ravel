"""One RAVEL study per batch allocation: the driving agent and RAVEL run inside one Slurm job.

``ravel site study-job submit`` writes a request and an sbatch script into the run's
``logs/allocations/requests/<request id>/`` and submits it. Inside the allocation the script
sets up the environment (modules, native prefix, virtual environment) and calls
``ravel site study-job run``, which re-verifies the request, records the allocation identity,
runs the agent command headless in the study directory and collects the run directory.

Inside the allocation RAVEL behaves as on a laptop: a local supervisor and local custody,
with the allocation's CPUs. The machine lease is scoped to the allocation
(``machine_lease.lease_scope``), so studies in separate jobs run in parallel and each
allocation still runs one native scientific job at a time.

Approval. ``--rung none`` admits planning work only: the agent may run intake and prepare
CHECK-IN 1, and the machine lease refuses every heavy stage because the run has no approval.
``--rung smoke|full|scan`` needs the run's approval for that rung through its approval route
(``execution_backend.verify_stage_binding``) when the request is written and again when the job
starts; the approval files' digests are carried in the request, so an approval changed or
withdrawn between submission and start refuses the job before the agent runs. Approval itself
stays a separate, earlier human step; this module never records one.

Credentials. The request names no secret. Variables that look like credentials are refused;
``--claude-config-dir`` passes only the path of a login the owner created interactively.

Receipts. ``logs/allocations/<scope>/allocation.json`` records the allocation identity
(cluster, job id, node list, CPUs), the run id, the binding and the agent's exit; every stage
attempt run under the allocation's lease also records ``allocation`` in its execution record.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
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
        env[name] = value
    return env


def prepare(rundir, agent, *, account, partition, cpus, minutes, rung='none', route='checkin1', checkout=None,
            venv=None, prefix=None, modules=(), env=(), claude_config_dir=None, collect_to=None, job_name=None, point_override=None):
    """Write the request and its sbatch script; return the request directory. Nothing is submitted."""
    rundir = Path(rundir).resolve()
    if not rundir.is_dir():
        raise ValueError(f'the study directory {rundir} does not exist; create it with ravel initiate first')
    if not agent:
        raise ValueError('give the agent command after --')
    if rung not in RUNGS or route not in ROUTES:
        raise ValueError(f'--rung is one of {RUNGS} and --route one of {ROUTES}')
    if type(cpus) is not int or not 1 <= cpus <= 1024 or type(minutes) is not int or not 1 <= minutes <= 43200:
        raise ValueError('--cpus is 1-1024 and --time 1-43200 minutes')
    for label, word in (('--account', account), ('--partition', partition), ('--job-name', job_name or 'ravel')):
        if not SLURM_WORD.fullmatch(str(word)):
            raise ValueError(f'{label} {word!r} is not a plain Slurm name')
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
    binding, approvals = _approval(rundir, route, rung)
    request_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    directory = rundir / REQUESTS / request_id
    directory.mkdir(parents=True)
    request = {
        'schema_version': SCHEMA, 'kind': 'allocation-study-request', 'request_id': request_id,
        'created_utc': utc_now(), 'rundir': str(rundir), 'run': _run_identity(rundir),
        'rung': rung, 'route': route, 'binding': binding, 'approval_files': approvals,
        'agent': {'argv': list(agent)},
        'resources': {'scheduler': 'slurm', 'account': account, 'partition': partition, 'cpus': cpus,
                      'minutes': minutes, 'nodes': 1, 'job_name': job_name or 'ravel-study'},
        'environment': {'checkout': str(checkout), 'checkout_commit': _checkout_commit(checkout),
                        'venv': str(venv), 'prefix': str(prefix) if prefix else None, 'modules': list(modules),
                        'variables': _environment(env),
                        'claude_config_dir': str(claude_config_dir) if claude_config_dir else None},
        'collect_to': str(collect_to) if collect_to else None,
    }
    if point_override is not None:
        from .point_overrides import verify, pin
        verify(point_override['record'], point_override['settings'])
        request['point_override'] = point_override
        request['point_settings'] = pin(point_override['settings'])
    atomic_json(directory / 'request.json', request)
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
             'set -euo pipefail']
    for module in envd['modules']:
        lines.append(f'module load {q(module)}')
    if envd['prefix']:
        lines.append(f"export RAVEL_NATIVE_BUILD={q(envd['prefix'])}")
        lines.append(f"if [ -f {q(envd['checkout'] + '/native/scripts/paths.sh')} ]; then "
                     f"set +u; . {q(envd['checkout'] + '/native/scripts/paths.sh')}; set -u; fi")
    if envd['claude_config_dir']:
        lines.append(f"export CLAUDE_CONFIG_DIR={q(envd['claude_config_dir'])}")
    for name, value in sorted(envd['variables'].items()):
        lines.append(f'export {name}={q(value)}')
    lines += [f"export VIRTUAL_ENV={q(envd['venv'])}",
              f"export PATH={q(envd['venv'] + '/bin')}:\"$PATH\"",
              # Build parallelism follows the allocation, never the node's CPU count.
              'export RAVEL_JOBS="${SLURM_CPUS_PER_TASK:-1}"',
              f"cd {q(request['rundir'])}",
              f"exec {q(envd['venv'] + '/bin/python')} -m ravel site study-job run --request "
              f"{q(str(Path(directory) / 'request.json'))}"]
    return '\n'.join(lines) + '\n'


class NotSubmitted(ValueError):
    """The scheduler was refused or never reached: no job exists for the request."""


def submit(directory, *, sbatch='sbatch'):
    """Submit a prepared request with ``sbatch --parsable``; record and return the job id."""
    directory = Path(directory)
    request = read_json(directory / 'request.json')
    try:
        _recheck(request)
    except ValueError as exc:
        raise NotSubmitted(str(exc)) from None
    out = subprocess.run([sbatch, '--parsable', str(directory / 'study.sbatch')], capture_output=True, text=True,
                         timeout=300)
    job = out.stdout.strip().split(';')[0] if out.returncode == 0 else ''
    if not re.fullmatch(r'[0-9]+', job):
        # A nonzero exit is a refusal; an unparsable reply after exit 0 may still hide a job.
        raise (NotSubmitted if out.returncode else ValueError)(f'sbatch refused the request (rc {out.returncode}): {out.stderr.strip()[-800:]}')
    atomic_json(directory / 'submission.json', {'request_id': request['request_id'], 'job_id': job,
                                                 'submitted_utc': utc_now(), 'sbatch': sbatch})
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
    """Copy this allocation's lease records into the run, then remove the scope when nothing holds it."""
    scope = machine_lease.scope()
    source = Path(scope['directory'])
    copied = []
    if scope['kind'] == 'slurm-job' and source.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        for item in sorted(source.iterdir()):
            if item.is_file() and not item.is_symlink():
                shutil.copy2(item, destination / item.name)
                copied.append(item.name)
        held = machine_lease.holder()
        if not (held and held.get('alive')):
            shutil.rmtree(source, ignore_errors=True)
    return {'scope': scope, 'copied': copied}


def run(request_path, *, popen=subprocess.Popen):
    """Inside the allocation: verify, record the allocation, run the agent, collect. Returns the agent's exit."""
    request_path = Path(request_path).resolve()
    request = read_json(request_path)
    if request.get('kind') != 'allocation-study-request' or request.get('schema_version') != SCHEMA:
        raise ValueError(f'{request_path} is not an allocation study request')
    allocation = machine_lease.slurm_allocation()
    if allocation is None:
        raise ValueError('this process is not inside a Slurm allocation (SLURM_JOB_ID with its job cgroup); '
                         'submit the request with ravel site study-job submit')
    _recheck(request)
    rundir = Path(request['rundir'])
    receipt_dir = rundir / 'logs/allocations' / machine_lease.allocation_key(allocation)
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt = {'schema_version': SCHEMA, 'kind': 'allocation-study-receipt', 'request_id': request['request_id'],
               'request_sha256': _sha(request_path), 'run': request['run'], 'rundir': str(rundir),
               'rung': request['rung'], 'route': request['route'], 'binding': request['binding'],
               'approval_files': request['approval_files'], 'allocation': machine_lease.allocation_identity(),
               'lease_directory': str(machine_lease.machine_dir()), 'started_utc': utc_now(),
               'agent': {'argv': request['agent']['argv'], 'log': str(receipt_dir / 'agent.log')},
               'state': 'running'}
    atomic_json(receipt_dir / 'allocation.json', receipt)
    env = dict(os.environ)
    env.update(RAVEL_ALLOCATION_REQUEST=str(request_path), RAVEL_ALLOCATION_RECEIPT=str(receipt_dir / 'allocation.json'),
               RAVEL_RUN_ID=request['run']['run_id'], RAVEL_ALLOCATION_RUNG=request['rung'],
               RAVEL_JOBS=os.environ.get('SLURM_CPUS_PER_TASK') or str(request['resources']['cpus']))
    if request.get('point_override'):
        env['RAVEL_POINT_RECEIPT_SHA256'] = request['point_override']['record']['receipt_sha256']
        env['RAVEL_POINT_SETTINGS'] = request['point_override']['settings']
    with (receipt_dir / 'agent.log').open('ab') as log:
        try:
            child = popen(request['agent']['argv'], cwd=rundir, env=env, stdout=log, stderr=subprocess.STDOUT,
                          stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            receipt.update(state='not-started', error=str(exc), ended_utc=utc_now())
            atomic_json(receipt_dir / 'allocation.json', receipt)
            raise ValueError(f'the agent command did not start: {exc}') from None

        def forward(signum, _frame):
            # Slurm's time limit and scancel reach this process first; the agent's own group follows.
            try:
                os.killpg(child.pid, signum)
            except OSError:
                pass
        previous = {s: signal.signal(s, forward) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGUSR1)}
        try:
            code = child.wait()
        finally:
            for s, handler in previous.items():
                signal.signal(s, handler)
    receipt.update(state='finished', agent_exit=code, ended_utc=utc_now(),
                   lease=_scope_records(receipt_dir / 'lease-scope'))
    if request.get('collect_to'):
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
    p = sub.add_parser('study-job', help='run one study per Slurm allocation: write, submit and run a request')
    verbs = p.add_subparsers(dest='verb', required=True)
    s = verbs.add_parser('submit', help='write the request and sbatch script, then submit (--dry-run writes only)')
    s.add_argument('--rundir', required=True, help='the study (run) directory; it must already exist')
    s.add_argument('--account', required=True)
    s.add_argument('--partition', required=True)
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
    r = verbs.add_parser('run', help='inside the allocation (called by the sbatch script)')
    r.add_argument('--request', required=True)
    return p


def main_args(args):
    if args.verb == 'run':
        return run(args.request)
    agent = args.agent[1:] if args.agent[:1] == ['--'] else args.agent
    directory = prepare(args.rundir, agent, account=args.account, partition=args.partition, cpus=args.cpus,
                        minutes=args.minutes, rung=args.rung, route=args.route, checkout=args.checkout,
                        venv=args.venv, prefix=args.prefix, modules=args.modules, env=args.env,
                        claude_config_dir=args.claude_config_dir, collect_to=args.collect_to, job_name=args.job_name)
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
    observed = (scheduler or _scheduler_state)(job) if job else 'unknown'
    if receipt:
        row = receipt['record']
        if row.get('state') == 'finished':
            if observed in ('completed', 'missing'):
                observed = 'completed' if row.get('agent_exit') == 0 else 'failed'
        elif row.get('state') == 'not-started':
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
