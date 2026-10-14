"""Site backend: HTCondor (for example lxplus) or SLURM batch jobs.

The job directory must sit on a filesystem the batch nodes share with the
submitting host (AFS or EOS FUSE on lxplus, the cluster file system on SLURM).
RAVEL writes a POSIX shell wrapper that runs the plan argv, records the exit code
in ``exit.json`` and, for outputs declared with a ``remote_uri`` (for example an
EOS path), copies them there without overwriting. The submission description
carries the resource ceilings and the RAVEL tag, so an interrupted submission can
be found again by tag. Scheduler commands are looked up on PATH and pinned by
path and sha256 in the plan. Credentials (Kerberos, grid proxies) stay with the
site; RAVEL only reports whether they are present (see ``ravel site doctor``).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

from ravel.workflow import execution_backend as eb

COMMANDS = {'htcondor': ('condor_submit', 'condor_q', 'condor_history', 'condor_rm'),
            'slurm': ('sbatch', 'squeue', 'sacct', 'scancel')}
CONDOR_STATES = {1: 'pending', 2: 'running', 3: 'cancelled', 4: 'exited', 5: 'held', 6: 'running', 7: 'pending'}
SLURM_STATES = {'PENDING': 'pending', 'CONFIGURING': 'pending', 'REQUEUED': 'pending', 'SUSPENDED': 'pending',
                'RUNNING': 'running', 'COMPLETING': 'running', 'COMPLETED': 'exited',
                'FAILED': 'failed', 'TIMEOUT': 'failed', 'OUT_OF_MEMORY': 'failed', 'NODE_FAIL': 'failed',
                'BOOT_FAIL': 'failed', 'DEADLINE': 'failed', 'PREEMPTED': 'failed', 'CANCELLED': 'cancelled'}
_OPTION = re.compile(r'^[A-Za-z+][A-Za-z0-9_.+-]{0,63}$')


def _tool(name):
    path = shutil.which(name)
    if not path:
        raise ValueError(f'{name} not found on PATH')
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': eb.file_sha256(path)}


def _copy_command(source, uri):
    quoted = shlex.quote(uri)
    if uri.startswith('root://'):
        return f'xrdcp --nopbar {shlex.quote(source)} {quoted}'
    return f'test ! -e {quoted} && mkdir -p "$(dirname {quoted})" && cp -R {shlex.quote(source)} {quoted}'


def wrapper(plan):
    spec = plan['spec']
    env_lines = [f'export {name}={shlex.quote(value)}' for name, value in sorted(spec.get('env', {}).items())]
    for fact in plan['readonly_trees']:
        if 'env' in fact:
            env_lines.append(f"export {fact['env']}={shlex.quote(fact['path'])}")
    threads = spec['resources']['cpus']
    copies = []
    for row in spec['outputs']:
        if 'remote_uri' in row:
            copies.append(f"  {_copy_command('output/' + row['name'], row['remote_uri'])} || code=75")
    lines = ['#!/bin/sh', '# Batch script of plan ' + plan['plan_sha256'] + '; do not edit.', 'set -u',
             'cd "$(dirname "$0")"', 'mkdir -p output work', 'export RAVEL_OUTPUT_DIR="$PWD/output"',
             f'export OMP_NUM_THREADS={threads}', *env_lines,
             '(cd work && exec ' + shlex.join(spec['argv']) + ') >> job.log 2>&1', 'code=$?']
    if copies:
        lines += ['if [ "$code" -eq 0 ]; then', *copies, 'fi']
    lines += ['printf \'{"exit_code": %d}\\n\' "$code" > exit.json.tmp && mv exit.json.tmp exit.json', 'exit "$code"', '']
    return '\n'.join(lines)


def render(plan, job_dir, tag):
    """Submission description for the plan's scheduler."""
    spec, site = plan['spec'], plan['spec']['site']
    job_dir = Path(job_dir).resolve()
    resources = spec['resources']
    options = site.get('options', {})
    if site['scheduler'] == 'htcondor':
        lines = [f'executable = {job_dir / "job.sh"}', f'initialdir = {job_dir}', 'universe = vanilla',
                 f'output = {job_dir / "scheduler.out"}', f'error = {job_dir / "scheduler.err"}',
                 f'log = {job_dir / "scheduler.log"}', f'request_cpus = {resources["cpus"]}',
                 f'request_memory = {resources["memory_mib"]}', f'+MaxRuntime = {resources["wall_seconds"]}',
                 f'batch_name = {tag}', f'+RavelTag = "{tag}"', 'should_transfer_files = NO',
                 'getenv = False']
        if 'disk_mib' in resources:
            lines.append(f'request_disk = {resources["disk_mib"] * 1024}')
        for key, value in sorted(options.items()):
            lines.append(f'{key} = {value}')
        lines.append('queue 1')
        return '\n'.join(lines) + '\n'
    hours, rest = divmod(resources['wall_seconds'], 3600)
    minutes, seconds = divmod(rest, 60)
    lines = ['#!/bin/sh', f'#SBATCH --job-name={tag}', f'#SBATCH --cpus-per-task={resources["cpus"]}',
             f'#SBATCH --mem={resources["memory_mib"]}M', f'#SBATCH --time={hours:d}:{minutes:02d}:{seconds:02d}',
             f'#SBATCH --output={job_dir / "scheduler.out"}', f'#SBATCH --error={job_dir / "scheduler.err"}',
             f'#SBATCH --chdir={job_dir}']
    if 'disk_mib' in resources:
        lines.append(f'#SBATCH --tmp={resources["disk_mib"]}M')
    for key, value in sorted(options.items()):
        lines.append(f'#SBATCH --{key}={value}')
    lines += [f'exec /bin/sh {shlex.quote(str(job_dir / "job.sh"))}', '']
    return '\n'.join(lines)


class SiteBackend(eb.Backend):
    kind = 'site'
    local = False

    def validate(self, spec):
        site = spec.get('site')
        if not isinstance(site, dict):
            raise ValueError('site backend needs a site block with the scheduler')
        eb._keys(site, ('scheduler',), ('options', 'site_id', 'shared_filesystem'), 'site')
        if site['scheduler'] not in COMMANDS:
            raise ValueError('site scheduler must be htcondor or slurm')
        options = site.get('options', {})
        if not isinstance(options, dict) or any(not _OPTION.fullmatch(k) or not isinstance(v, (str, int))
                                                or '\n' in str(v) for k, v in options.items()):
            raise ValueError('site options must be plain scheduler keys with single-line values')
        reserved = {'executable', 'initialdir', 'queue', 'output', 'error', 'log', 'job-name', 'chdir', 'batch_name', '+RavelTag'}
        if reserved & set(options):
            raise ValueError('site options cannot replace RAVEL-controlled submission fields')
        if 'image' in spec:
            raise ValueError('the site backend runs the site environment; run containers through the site setup instead')
        return spec

    def describe(self, spec):
        site = spec['site']
        return {'kind': self.kind, 'local': False, 'scheduler': site['scheduler'], 'site_id': site.get('site_id'),
                'commands': {name: _tool(name) for name in COMMANDS[site['scheduler']]},
                'limits_enforced': {'cpus': 'scheduler', 'memory_mib': 'scheduler', 'wall_seconds': 'scheduler and worker'}}

    def doctor(self):
        checks = []
        for scheduler, names in COMMANDS.items():
            found = [n for n in names if shutil.which(n)]
            checks.append({'name': scheduler, 'ok': len(found) == len(names),
                           'detail': 'available' if len(found) == len(names) else
                           'missing ' + ', '.join(n for n in names if n not in found)})
        return {'backend': self.kind, 'ready': any(c['ok'] for c in checks), 'checks': checks}

    def _call(self, plan, handle, name, arguments, *, check=True, timeout=300):
        tool = plan['backend']['commands'][name]
        if eb.file_sha256(tool['path']) != tool['sha256']:
            raise ValueError(f'{name} changed since the plan was prepared')
        proc = subprocess.run([tool['path'], *arguments], capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
        row = {'argv': [tool['path'], *arguments], 'returncode': proc.returncode, 'utc': eb.utc_now(),
               'stdout': eb.redact(proc.stdout)[-20000:], 'stderr': eb.redact(proc.stderr)[-20000:]}
        with (Path(handle['attempt_dir']) / 'scheduler-client.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, sort_keys=True) + '\n')
        if check and proc.returncode:
            raise ValueError(f'{name} failed with exit {proc.returncode}: {row["stderr"][-300:]}')
        return proc

    def submit(self, plan, handle):
        job = Path(handle['job_dir'])
        (job / 'output').mkdir(parents=True)
        (job / 'work').mkdir()
        script = job / 'job.sh'
        script.write_text(wrapper(plan))
        script.chmod(0o755)
        scheduler = plan['spec']['site']['scheduler']
        description = job / ('job.sub' if scheduler == 'htcondor' else 'job.sbatch')
        description.write_text(render(plan, job, handle['tag']))
        if scheduler == 'htcondor':
            proc = self._call(plan, handle, 'condor_submit', ['-terse', str(description)])
            match = re.match(r'\s*(\d+)\.\d+', proc.stdout)
            if not match:
                raise ValueError('condor_submit did not report a cluster id')
            return {'scheduler': 'htcondor', 'job_id': match.group(1)}
        proc = self._call(plan, handle, 'sbatch', ['--parsable', str(description)])
        match = re.match(r'\s*(\d+)', proc.stdout)
        if not match:
            raise ValueError('sbatch did not report a job id')
        return {'scheduler': 'slurm', 'job_id': match.group(1)}

    def _exit(self, handle):
        path = Path(handle['job_dir']) / 'exit.json'
        if path.is_file():
            return eb.read_json(path).get('exit_code')
        return None

    def _finish(self, handle, scheduler_state, detail):
        code = self._exit(handle)
        if scheduler_state == 'cancelled':
            return {'state': 'cancelled' if handle.get('cancel_requested') else 'failed', 'exit_code': code, 'detail': detail}
        if scheduler_state == 'exited':
            if code is None:
                return {'state': 'failed', 'exit_code': None, 'detail': detail + '; no exit record in the job directory'}
            return {'state': 'succeeded' if code == 0 else 'failed', 'exit_code': code, 'detail': detail}
        return {'state': 'failed', 'exit_code': code, 'detail': detail}

    def observe(self, plan, handle):
        remote = handle['remote']
        if remote['scheduler'] == 'htcondor':
            fields = ['-af', 'JobStatus', 'ExitCode', 'RavelTag']
            proc = self._call(plan, handle, 'condor_q', [f"{remote['job_id']}.0", *fields], check=False)
            line = proc.stdout.strip()
            if not line:
                proc = self._call(plan, handle, 'condor_history', [f"{remote['job_id']}.0", '-limit', '1', *fields], check=False)
                line = proc.stdout.strip()
            if not line:
                return {'state': 'unknown', 'exit_code': None, 'detail': 'job not found in queue or history'}
            parts = line.split()
            if parts[-1].strip('"') != handle['tag']:
                raise ValueError('scheduler job does not carry this handle tag; refusing to adopt it')
            state = CONDOR_STATES.get(int(parts[0]), 'unknown')
            if state == 'held':
                return {'state': 'failed', 'exit_code': None, 'detail': 'held by the scheduler', 'requires_cancel': True}
            if state in ('pending', 'running', 'unknown'):
                return {'state': state, 'exit_code': None}
            return self._finish(handle, state, f'condor status {parts[0]}')
        proc = self._call(plan, handle, 'squeue', ['-h', '-j', remote['job_id'], '-o', '%T|%j'], check=False)
        line = proc.stdout.strip()
        if line:
            state, name = line.split('|', 1)
            if name != handle['tag']:
                raise ValueError('scheduler job does not carry this handle tag; refusing to adopt it')
            mapped = SLURM_STATES.get(state.split()[0], 'running')
            return {'state': mapped if mapped == 'pending' else 'running', 'exit_code': None}
        proc = self._call(plan, handle, 'sacct', ['-j', remote['job_id'], '-n', '-P', '-X', '-o', 'State,ExitCode,JobName'], check=False)
        line = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ''
        if not line:
            return {'state': 'unknown', 'exit_code': None, 'detail': 'job not found by squeue or sacct'}
        state, _, name = line.split('|')
        if name != handle['tag']:
            raise ValueError('scheduler job does not carry this handle tag; refusing to adopt it')
        mapped = SLURM_STATES.get(state.split()[0], 'unknown')
        if mapped in ('pending', 'running', 'unknown'):
            return {'state': mapped, 'exit_code': None}
        return self._finish(handle, mapped, f'slurm state {state}')

    def logs(self, plan, handle):
        path = Path(handle['job_dir']) / 'job.log'
        return path.read_text(errors='replace') if path.is_file() else ''

    def cancel(self, plan, handle):
        remote = handle['remote']
        if remote['scheduler'] == 'htcondor':
            self._call(plan, handle, 'condor_rm', [f"{remote['job_id']}.0"])
        else:
            self._call(plan, handle, 'scancel', [remote['job_id']])

    def find(self, plan, handle):
        scheduler = plan['spec']['site']['scheduler']
        found = set()
        if scheduler == 'htcondor':
            constraint = f'RavelTag == "{handle["tag"]}"'
            for name in ('condor_q', 'condor_history'):
                proc = self._call(plan, handle, name, ['-constraint', constraint, '-af', 'ClusterId'], check=False)
                found |= {line.strip() for line in proc.stdout.splitlines() if line.strip().isdigit()}
        else:
            proc = self._call(plan, handle, 'squeue', ['-h', '-n', handle['tag'], '-o', '%i'], check=False)
            found |= {line.strip() for line in proc.stdout.splitlines() if line.strip().isdigit()}
            proc = self._call(plan, handle, 'sacct', ['-n', '-P', '-X', '--name', handle['tag'], '-o', 'JobID'], check=False)
            found |= {line.strip() for line in proc.stdout.splitlines() if line.strip().isdigit()}
        if len(found) > 1:
            raise ValueError('more than one scheduler job carries this tag; refusing to choose')
        return {'scheduler': scheduler, 'job_id': found.pop()} if found else None

    def retrieve(self, plan, handle, staging):
        output = Path(handle['job_dir']) / 'output'
        for row in plan['spec']['outputs']:
            source = output / row['name']
            if 'destination' not in row or not source.exists():
                continue
            target = staging / row['name']
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, symlinks=True)
            else:
                shutil.copy2(source, target, follow_symlinks=False)

    def stat_remote(self, plan, handle, output):
        uri = output['remote_uri']
        if uri.startswith('root://'):
            match = re.match(r'(root://[^/]+)/(/.*)', uri)
            if not match or not shutil.which('xrdfs'):
                return {'exists': False, 'detail': 'xrdfs unavailable or URI not of the form root://host//path'}
            proc = subprocess.run(['xrdfs', match.group(1), 'stat', match.group(2)], capture_output=True, text=True, timeout=120)
            size = re.search(r'Size:\s+(\d+)', proc.stdout)
            return {'exists': proc.returncode == 0, 'size': int(size.group(1)) if size else None,
                    'custody': 'declared remote output; bytes stay on the storage element'}
        path = Path(uri)
        return {'exists': path.exists(), 'size': path.stat().st_size if path.is_file() else None,
                'custody': 'declared remote output; bytes stay on the storage element'}
