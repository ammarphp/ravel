"""Local OCI backend: run a stage in a digest-pinned podman container.

All podman state lives inside the RAVEL container home (``RAVEL_CONTAINER_HOME``,
default ``<native build>/containers``): the client runs with its own
``XDG_CONFIG_HOME``, ``XDG_DATA_HOME`` and ``CONTAINERS_CONF``, so the user's
global podman configuration is never read or written. The podman executable is
pinned by path and sha256 in the plan.

Containers get a deterministic name (the handle tag) and RAVEL labels, run with
``--network none``, ``--pull never``, dropped capabilities, and CPU, memory and
PID limits. Inputs and declared tool trees (for example an LHAPDF data directory)
are bind-mounted read-only; only the attempt's output directory is writable.
The image architecture must match the host unless the plan declares emulation.
Every client call is journalled with redacted output.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time

from ravel.workflow import execution_backend as eb
from ravel.workflow.state_io import atomic_json

GUEST_OUTPUT = '/ravel/output'
GUEST_WORK = '/ravel/work'
PIDS_LIMIT = 4096
_FROM = re.compile(r'^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?\s*$', re.I | re.M)


def container_home():
    configured = os.environ.get('RAVEL_CONTAINER_HOME')
    if configured:
        return Path(configured).expanduser().resolve()
    from ravel.paths import native_build_root
    return native_build_root() / 'containers'


def client_environment(home=None):
    """Isolated podman client environment inside the RAVEL prefix."""
    home = Path(home) if home else container_home()
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': os.environ.get('HOME', str(home)),
           'TMPDIR': os.environ.get('TMPDIR', '/tmp'), 'LC_ALL': 'C', 'LANG': 'C',
           'XDG_CONFIG_HOME': str(home / 'config'), 'XDG_DATA_HOME': str(home / 'data'),
           'XDG_RUNTIME_DIR': str(home / 'run')}
    conf = home / 'containers.conf'
    if conf.is_file():
        env['CONTAINERS_CONF'] = str(conf)
    for name in ('CONTAINERS_MACHINE_PROVIDER',):
        if os.environ.get(name):
            env[name] = os.environ[name]
    return env


def host_platform():
    machine = platform.machine().lower()
    return 'linux/arm64' if machine in ('arm64', 'aarch64') else 'linux/amd64'


def resolve_client(path=None):
    resolved = path or shutil.which('podman')
    if not resolved or not Path(resolved).is_file():
        raise ValueError('podman client not found; install it in the RAVEL environment or set site.client')
    resolved = Path(resolved).resolve()
    return {'path': str(resolved), 'sha256': eb.file_sha256(resolved)}


class _Client:
    def __init__(self, client, connection, journal):
        self.client, self.connection, self.journal = client, connection, Path(journal)

    def call(self, arguments, *, check=True, timeout=120, connection=True):
        if eb.file_sha256(self.client['path']) != self.client['sha256']:
            raise ValueError('podman client bytes changed since the plan was prepared')
        argv = [self.client['path'], *(['--connection', self.connection] if connection and self.connection else []), *arguments]
        row = {'argv': argv, 'started_utc': eb.utc_now()}
        try:
            proc = subprocess.run(argv, env=client_environment(), capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            row['error'] = 'timeout'
            self._write(row)
            raise ValueError('podman call timed out: ' + ' '.join(arguments[:2]))
        row.update(returncode=proc.returncode, stdout=eb.redact(proc.stdout.decode(errors='replace'))[-20000:],
                   stderr=eb.redact(proc.stderr.decode(errors='replace'))[-20000:])
        self._write(row)
        if check and proc.returncode:
            raise ValueError(f'podman {arguments[0]} failed with exit {proc.returncode}: {row["stderr"][-400:]}')
        return proc

    def _write(self, row):
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        with self.journal.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, sort_keys=True) + '\n')


def _client_for(plan, handle):
    site = plan['backend']
    return _Client(site['client'], site['connection'], Path(handle['attempt_dir']) / 'container-client.jsonl')


class OciLocalBackend(eb.Backend):
    kind = 'oci-local'
    local = True

    def validate(self, spec):
        if 'image' not in spec:
            raise ValueError('oci-local needs an image pinned by digest')
        image = spec['image']
        if image['platform'] != host_platform() and not image.get('emulation'):
            raise ValueError(f"image platform {image['platform']} differs from this host ({host_platform()}); "
                             'declare image.emulation true to accept emulation')
        site = spec.get('site', {})
        eb._keys(site, (), ('client', 'connection', 'network'), 'oci-local site')
        if site.get('network', 'none') not in ('none',):
            raise ValueError('oci-local stages run without network')
        for row in spec.get('inputs', []) + spec.get('readonly_trees', []):
            if 'mount' not in row:
                raise ValueError(f"oci-local input {row['path']} needs a guest mount path")
        return spec

    def describe(self, spec):
        site = spec.get('site', {})
        return {'kind': self.kind, 'local': True, 'client': resolve_client(site.get('client')),
                'connection': site.get('connection', 'ravel'), 'host_platform': host_platform(),
                'container_home': str(container_home()),
                'limits_enforced': {'cpus': True, 'memory_mib': True, 'pids': PIDS_LIMIT, 'network': 'none',
                                    'wall_seconds': 'worker'}}

    def doctor(self):
        checks = []
        try:
            client = resolve_client()
            checks.append({'name': 'client', 'ok': True, 'detail': client['path']})
        except ValueError as exc:
            return {'backend': self.kind, 'ready': False, 'checks': [{'name': 'client', 'ok': False, 'detail': str(exc)}]}
        env = client_environment()
        checks.append({'name': 'container home', 'ok': True, 'detail': str(container_home())})
        version = subprocess.run([client['path'], '--version'], env=env, capture_output=True, text=True, timeout=30)
        checks.append({'name': 'version', 'ok': version.returncode == 0, 'detail': version.stdout.strip()})
        machines = subprocess.run([client['path'], 'machine', 'list', '--format', 'json'], env=env,
                                  capture_output=True, text=True, timeout=30)
        try:
            rows = json.loads(machines.stdout or '[]')
        except json.JSONDecodeError:
            rows = []
        running = [r.get('Name') for r in rows if r.get('Running')]
        checks.append({'name': 'machine', 'ok': bool(running) or platform.system() == 'Linux',
                       'detail': ('running: ' + ', '.join(running)) if running else
                       'no running podman machine in the RAVEL container home; run `ravel backend machine init` then `start`'})
        return {'backend': self.kind, 'ready': all(c['ok'] for c in checks), 'checks': checks}

    def create_arguments(self, plan, handle):
        spec = plan['spec']
        image = spec['image']
        job = Path(handle['job_dir'])
        arguments = ['create', '--name', handle['tag'],
                     '--label', 'org.ravel.plan=' + plan['plan_sha256'], '--label', 'org.ravel.tag=' + handle['tag'],
                     '--platform', image['platform'], '--pull', 'never', '--network', 'none',
                     '--cpus', str(spec['resources']['cpus']), '--memory', f"{spec['resources']['memory_mib']}m",
                     '--pids-limit', str(PIDS_LIMIT), '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges']
        for fact in [*plan['inputs'], *plan['readonly_trees']]:
            arguments += ['-v', f"{fact['path']}:{fact['mount']}:ro"]
            if 'env' in fact:
                arguments += ['-e', f"{fact['env']}={fact['mount']}"]
        arguments += ['-v', f"{job / 'output'}:{GUEST_OUTPUT}:rw", '-v', f"{job / 'work'}:{GUEST_WORK}:rw"]
        for name, value in sorted(spec.get('env', {}).items()):
            arguments += ['-e', f'{name}={value}']
        threads = str(spec['resources']['cpus'])
        arguments += ['-e', f'RAVEL_OUTPUT_DIR={GUEST_OUTPUT}', '-e', f'OMP_NUM_THREADS={threads}']
        arguments += ['-w', spec.get('workdir', GUEST_WORK)]
        arguments += [image.get('reference') or image['id'], *spec['argv']]
        return arguments

    def submit(self, plan, handle):
        job = Path(handle['job_dir'])
        (job / 'output').mkdir(parents=True)
        (job / 'work').mkdir()
        client = _client_for(plan, handle)
        created = client.call(self.create_arguments(plan, handle))
        cid = created.stdout.decode().strip().splitlines()[-1] if created.stdout.strip() else ''
        if not re.fullmatch(r'[0-9a-f]{64}', cid):
            raise ValueError('podman create did not return a container id')
        observation = self._inspect(client, handle['tag'])
        self._owned(plan, handle, observation, cid)
        client.call(['start', cid])
        return {'container_id': cid, 'name': handle['tag']}

    def _inspect(self, client, ident):
        proc = client.call(['container', 'inspect', ident])
        rows = json.loads(proc.stdout)
        if not isinstance(rows, list) or len(rows) != 1:
            raise ValueError('expected one container observation')
        return rows[0]

    def _owned(self, plan, handle, observation, cid=None):
        labels = (observation.get('Config') or {}).get('Labels') or {}
        if (observation.get('Name', '').lstrip('/') != handle['tag'] or labels.get('org.ravel.plan') != plan['plan_sha256']
                or labels.get('org.ravel.tag') != handle['tag']):
            raise ValueError('observed container is not the one this plan owns')
        if cid is not None and observation.get('Id') != cid:
            raise ValueError('container identity changed')
        image = plan['spec']['image']
        if 'reference' in image and observation.get('ImageDigest') != image['reference'].split('@', 1)[1]:
            raise ValueError('container image digest differs from the plan')
        if 'id' in image and observation.get('Image', '').removeprefix('sha256:') != image['id'].removeprefix('sha256:'):
            raise ValueError('container image id differs from the plan')
        host = observation.get('HostConfig') or {}
        resources = plan['spec']['resources']
        if host.get('NanoCpus') != resources['cpus'] * 10 ** 9 or host.get('Memory') != resources['memory_mib'] * 1024 ** 2 \
                or host.get('PidsLimit') != PIDS_LIMIT:
            raise ValueError('container resource limits differ from the plan')
        return observation

    def observe(self, plan, handle):
        client = _client_for(plan, handle)
        observation = self._inspect(client, handle['remote']['container_id'])
        self._owned(plan, handle, observation, handle['remote']['container_id'])
        state = observation['State']
        status = state.get('Status')
        if state.get('Running') or status in ('running', 'paused', 'stopping'):
            return {'state': 'running', 'exit_code': None}
        if status in ('created', 'configured', 'initialized'):
            return {'state': 'pending', 'exit_code': None}
        code = state.get('ExitCode')
        if handle.get('cancel_requested') and code != 0:
            return {'state': 'cancelled', 'exit_code': code}
        return {'state': 'succeeded' if code == 0 else 'failed', 'exit_code': code}

    def logs(self, plan, handle):
        proc = _client_for(plan, handle).call(['logs', handle['remote']['container_id']], check=False)
        return (proc.stdout + proc.stderr).decode(errors='replace')

    def cancel(self, plan, handle):
        client = _client_for(plan, handle)
        observation = self._inspect(client, handle['remote']['container_id'])
        self._owned(plan, handle, observation, handle['remote']['container_id'])
        client.call(['stop', '--time', '10', handle['remote']['container_id']], timeout=60)

    def find(self, plan, handle):
        client = _client_for(plan, handle)
        exists = client.call(['container', 'exists', handle['tag']], check=False)
        if exists.returncode == 1:
            return None
        if exists.returncode != 0:
            raise ValueError('podman container exists query failed')
        observation = self._owned(plan, handle, self._inspect(client, handle['tag']))
        if observation.get('State', {}).get('Status') == 'created':
            client.call(['start', observation['Id']])
        return {'container_id': observation['Id'], 'name': handle['tag']}

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

    def release(self, plan, handle):
        _client_for(plan, handle).call(['rm', handle['remote']['container_id']], check=False)


# ---------------------------------------------------------------- machine and images
def machine(action, *, name='ravel', cpus=4, memory_mib=8192, disk_gib=40, execute=False, client=None):
    """Podman machine life cycle inside the RAVEL container home. Dry run by default."""
    home = container_home()
    arguments = {'init': ['machine', 'init', '--cpus', str(cpus), '--memory', str(memory_mib),
                          '--disk-size', str(disk_gib), name],
                 'start': ['machine', 'start', name], 'stop': ['machine', 'stop', name],
                 'status': ['machine', 'list', '--format', 'json']}[action]
    resolved = resolve_client(client)
    result = {'action': action, 'container_home': str(home), 'argv': [resolved['path'], *arguments],
              'environment': {k: v for k, v in client_environment(home).items() if k.startswith(('XDG_', 'CONTAINERS_'))},
              'executed': False}
    if not execute and action != 'status':
        result['note'] = 'dry run; pass --execute after the owner approves this machine action'
        return result
    for sub in ('config', 'data', 'run'):
        (home / sub).mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(result['argv'], env=client_environment(home), capture_output=True, text=True, timeout=1800)
    result.update(executed=True, returncode=proc.returncode, stdout=eb.redact(proc.stdout)[-4000:],
                  stderr=eb.redact(proc.stderr)[-4000:])
    return result


def containerfile_bases(text):
    """Every FROM must be digest-pinned or refer to an earlier build stage."""
    stages, bases = set(), []
    for match in _FROM.finditer(text):
        base, alias = match.group(1), match.group(2)
        if base in stages:
            pass
        elif not eb._DIGEST_REFERENCE.fullmatch(base):
            raise ValueError(f'Containerfile base {base!r} is not pinned by digest (name@sha256:<64 hex>)')
        else:
            bases.append(base)
        if alias:
            stages.add(alias)
    if not bases:
        raise ValueError('Containerfile has no digest-pinned FROM line')
    return bases


def build_image(containerfile, context, tag, *, receipt, platform=None, connection='ravel', execute=False, client=None):
    """Build an image from a digest-pinned Containerfile and write a build receipt."""
    containerfile, context, receipt = Path(containerfile).resolve(), Path(context).resolve(), Path(receipt)
    text = containerfile.read_text()
    bases = containerfile_bases(text)
    platform = platform or host_platform()
    if receipt.exists():
        raise ValueError(f'build receipt already exists: {receipt}')
    resolved = resolve_client(client)
    arguments = ['build', '--platform', platform, '--pull=missing', '-f', str(containerfile), '-t', tag, str(context)]
    record = {'schema_version': 1, 'kind': 'ravel-image-build', 'containerfile': {'path': str(containerfile),
              'sha256': eb.file_sha256(containerfile)}, 'context': eb.identity(context), 'bases': bases,
              'platform': platform, 'tag': tag, 'argv': [resolved['path'], '--connection', connection, *arguments],
              'client': resolved, 'executed': False}
    if not execute:
        record['note'] = 'dry run; pass --execute after the owner approves this image build'
        return record
    journal = receipt.with_suffix('.client.jsonl')
    calls = _Client(resolved, connection, journal)
    started = time.monotonic()
    calls.call(arguments, timeout=6 * 3600)
    inspected = json.loads(calls.call(['image', 'inspect', tag]).stdout)[0]
    record.update(executed=True, image={'id': 'sha256:' + inspected['Id'].removeprefix('sha256:'),
                  'digest': inspected.get('Digest'), 'architecture': inspected.get('Architecture'),
                  'os': inspected.get('Os')}, build_seconds=round(time.monotonic() - started, 3),
                  built_utc=eb.utc_now())
    atomic_json(receipt, record)
    return record


# ---------------------------------------------------------------- launcher for native adapters
LAUNCHER_REQUIRED = ('kind', 'image', 'client', 'connection', 'cpus', 'memory_mib')


def validate_launcher(launcher):
    """A container launcher declared by a native adapter's runtime document.

    The adapter keeps its own process ownership and census; the launcher only
    runs the same argv inside a digest-pinned image with the host paths mounted
    at identical guest paths (read-only trees, one writable working directory).
    """
    eb._keys(launcher, LAUNCHER_REQUIRED, ('env',), 'container launcher')
    if launcher['kind'] != 'oci-local':
        raise ValueError('container launcher kind must be oci-local')
    image = eb.validate_image(launcher['image'])
    if image['platform'] != host_platform() and not image.get('emulation'):
        raise ValueError(f"launcher image platform {image['platform']} differs from this host; declare emulation to accept it")
    client = launcher['client']
    eb._keys(client, ('path', 'sha256'), (), 'launcher client')
    if not Path(client['path']).is_file() or eb.file_sha256(client['path']) != client['sha256']:
        raise ValueError('launcher podman client is missing or its bytes changed')
    if not isinstance(launcher['connection'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', launcher['connection']):
        raise ValueError('launcher connection must be a plain podman connection name')
    eb._integer(launcher['cpus'], 1, 256, 'launcher cpus')
    eb._integer(launcher['memory_mib'], 128, 1 << 22, 'launcher memory_mib')
    for name, value in launcher.get('env', {}).items():
        eb._env_name(name)
        if not isinstance(value, str):
            raise ValueError('launcher environment values must be strings')
    return launcher


def launcher_command(launcher, argv, *, workdir, readonly=(), writable=(), name):
    """argv wrapped in ``podman run`` with the RAVEL client environment."""
    validate_launcher(launcher)
    env = client_environment()
    prefix = ['/usr/bin/env', *[f'{k}={env[k]}' for k in ('XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_RUNTIME_DIR', 'CONTAINERS_CONF') if k in env]]
    image = launcher['image']
    command = [*prefix, launcher['client']['path'], '--connection', launcher['connection'], 'run', '--rm',
               '--name', name, '--label', 'org.ravel.launch=' + name, '--platform', image['platform'],
               '--pull', 'never', '--network', 'none', '--cpus', str(launcher['cpus']),
               '--memory', f"{launcher['memory_mib']}m", '--pids-limit', str(PIDS_LIMIT), '--cap-drop', 'ALL',
               '--security-opt', 'no-new-privileges', '--stop-timeout', '10']
    for path in readonly:
        command += ['-v', f'{Path(path).resolve()}:{Path(path).resolve()}:ro']
    for path in writable:
        command += ['-v', f'{Path(path).resolve()}:{Path(path).resolve()}:rw']
    for key, value in sorted(launcher.get('env', {}).items()):
        command += ['-e', f'{key}={value}']
    command += ['-w', str(Path(workdir).resolve()), image.get('reference') or image['id'], *argv]
    return command


def cleanup_launch(launcher, name, *, timeout=60):
    """Stop and remove a launched container left behind by a killed client."""
    client = launcher['client']['path']
    env = client_environment()
    base = [client, '--connection', launcher['connection']]
    result = {'container_name': name, 'requires_recovery': True}
    try:
        exists = subprocess.run([*base, 'container', 'exists', name], env=env, capture_output=True, timeout=timeout)
        if exists.returncode == 1:
            result.update(state='absent', requires_recovery=False)
            return result
        inspect = subprocess.run([*base, 'container', 'inspect', name], env=env, capture_output=True, timeout=timeout)
        labels = (json.loads(inspect.stdout or b'[{}]')[0].get('Config') or {}).get('Labels') or {}
        if labels.get('org.ravel.launch') != name:
            result.update(state='foreign', detail='a container with this name is not a RAVEL launch; left untouched')
            return result
        subprocess.run([*base, 'stop', '--time', '5', name], env=env, capture_output=True, timeout=timeout)
        subprocess.run([*base, 'rm', name], env=env, capture_output=True, timeout=timeout)
        gone = subprocess.run([*base, 'container', 'exists', name], env=env, capture_output=True, timeout=timeout)
        result.update(state='stopped', requires_recovery=gone.returncode != 1)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        result['error'] = str(exc)
    return result
