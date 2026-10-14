"""Closed Podman transport for source-built AnalysisBase jobs.

This module neither acquires images nor boots a VM. The routine-build adapter
supplies an approved source-bound job, an independently qualified immutable image
and its resource budget. Every client command and failed cleanup is retained.
The outer supervisor must call recover after killing a worker: killing a Podman
client does not stop its container.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import time

from ravel.analysis_sources import digest
from ravel.physics.routine_build import executable_identity
from ravel.workflow.state_io import atomic_json, read_json

_SHA = re.compile(r'[0-9a-f]{64}')
_CID = re.compile(r'[0-9a-f]{64}')
_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}')
_ENVIRONMENT = {'PATH', 'HOME', 'TMPDIR', 'LC_ALL', 'LC_CTYPE',
                'PYTHONCOERCECLOCALE', 'PYTHONUTF8', '__CF_USER_TEXT_ENCODING',
                'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'CONTAINERS_MACHINE_PROVIDER'}


def _sha(value):
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError('exact SHA256 required')
    return value


def _relative(value):
    p = PurePosixPath(value) if isinstance(value, str) else None
    if p is None or p.is_absolute() or not p.parts or any(x in ('', '.', '..') for x in p.parts) or str(p) != value:
        raise ValueError('normalized relative input pathname required')
    return value


def tree_facts(directory):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('ordinary input tree required')
    facts = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError('container transfer rejects symlinks and special files')
        if path.is_file():
            facts[path.relative_to(directory).as_posix()] = {'sha256': digest(path), 'size': path.stat().st_size}
    return facts


def routine_bindings(capsule, base, compile_units):
    """Positive native DefineAnalysis bindings, with complete source identity.

    Parse literal invocations in actual compile units only. Strings, comments,
    header macro definitions and metadata names never grant routine admission.
    This deliberately does not claim a complete C++ dependency parser.
    """
    from ravel import analysis_sources as sources
    root, _ = sources.source_files(capsule, base)
    roles = {f['path']: f['role'] for f in capsule['files']}
    if capsule['framework'] != 'simpleanalysis' or not isinstance(compile_units, list) or len(set(compile_units)) != len(compile_units) or any(roles.get(p) != 'compile' for p in compile_units):
        raise ValueError('explicit SimpleAnalysis compile-unit denominator required')
    tokens = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/'
    bindings = {}
    for fact in capsule['files']:
        if fact['path'] not in compile_units:
            continue
        code = re.sub(tokens, ' ', (root/fact['path']).read_text(errors='strict'))
        for name in re.findall(r'\bDefineAnalysis\s*\(\s*([A-Za-z][A-Za-z0-9_]*)\s*\)', code):
            if name in bindings:
                raise ValueError('duplicate literal SimpleAnalysis registration: ' + name)
            bindings[name] = {'registration':'literal-DefineAnalysis', 'source_files':[fact]}
    if capsule['routine'] not in bindings:
        raise ValueError('selected routine lacks literal registration in a declared compile unit')
    return bindings


def verify_listing(raw_stdout, bindings):
    """Verify the actual upstream -l listing's exact denominator, not substrings."""
    text = raw_stdout.decode('utf-8') if isinstance(raw_stdout, bytes) else raw_stdout
    lines = text.splitlines()
    starts = [i for i,line in enumerate(lines) if line == 'Select analyses among:']
    if len(starts) != 1:
        raise ValueError('one actual canonical SimpleAnalysis listing required')
    names = [line.strip() for line in lines[starts[0]+1:] if line.strip()]
    if len(names) != len(set(names)) or set(names) != set(bindings):
        raise ValueError('native listing differs from source-bound routine denominator')
    return sorted(names)


def validate_transport(config, *, for_recovery=False):
    if not isinstance(config, dict) or set(config) != {'schema_version', 'client', 'client_artifacts', 'connection', 'environment', 'image', 'qualification'} or config['schema_version'] != 1:
        raise ValueError('invalid closed container transport')
    if executable_identity(config['client']['path']) != config['client']:
        raise ValueError('container client alias or bytes changed')
    if not _NAME.fullmatch(config['connection']):
        raise ValueError('explicit named Podman connection required')
    env = config['environment']
    if not isinstance(env, dict) or set(env) - _ENVIRONMENT or any(not isinstance(v, str) or '\x00' in v for v in env.values()):
        raise ValueError('invalid closed client environment')
    required = {'PATH', 'HOME', 'TMPDIR', 'LC_ALL', 'LC_CTYPE', 'PYTHONCOERCECLOCALE', 'PYTHONUTF8', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'CONTAINERS_MACHINE_PROVIDER'}
    if not required <= set(env) or env['LC_ALL'] != 'C' or env['LC_CTYPE'] != 'C' or env['PYTHONCOERCECLOCALE'] != '0' or env['PYTHONUTF8'] != '1':
        raise ValueError('explicit portable locale and isolated client directories required')
    if any(env.get(key) != '1' for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS')):
        raise ValueError('one client worker required')
    image = config['image']
    if set(image) != {'reference', 'manifest_sha256', 'config_sha256', 'platform', 'user'} or image['platform'] != 'linux/amd64' or image['user'] != 'atlas':
        raise ValueError('qualified AnalysisBase Linux amd64 atlas image required')
    _sha(image['manifest_sha256']); _sha(image['config_sha256'])
    if not image['reference'].endswith('@sha256:' + image['manifest_sha256']):
        raise ValueError('immutable manifest image reference required')
    for fact in [*config['client_artifacts'], *([] if for_recovery else [config['qualification']])]:
        if not isinstance(fact, dict) or set(fact) != {'path', 'sha256', 'size'}:
            raise ValueError('bound client and qualification file facts required')
        p = Path(fact['path'])
        if p.is_symlink() or not p.is_file() or p.stat().st_size != fact['size'] or digest(p) != _sha(fact['sha256']):
            raise ValueError('container transport support file changed')
    if for_recovery:
        # Cleanup authority is the immutable prelaunch job's namespace/image
        # and observed ownership labels. Mutable science/qualification bytes
        # cannot prevent safe termination of that already owned resource.
        return config
    qualification = read_json(config['qualification']['path'])
    # The native qualification records observed emulator/procfs semantics. They
    # cannot be deduced from the requested platform or a previous CMS image.
    qualified_image=qualification.get('image',{})
    emulation=qualification.get('emulation_observation',{})
    if qualification.get('status') != 'passed' or {key:qualified_image.get(key) for key in image} != image or not qualification.get('native_process_observation') or emulation.get('procfs_semantics_observed') is not True or emulation.get('emulator_binary_identity_complete') is not True or qualification.get('cleanup',{}).get('requires_recovery') is not False:
        raise ValueError('actual image/native/emulator qualification required')
    return config


def make_plan(transport, input_directory, *, max_seconds, memory_mib=3072, cpus=1):
    validate_transport(transport)
    if type(cpus) is not int or cpus not in (1, 2) or type(max_seconds) is not int or not 30 <= max_seconds <= 86400 or type(memory_mib) is not int or not 128 <= memory_mib <= (4096 if cpus == 1 else 8192):
        raise ValueError('explicit bounded container resources required')
    inputs = tree_facts(input_directory)
    if 'run.sh' not in inputs or not inputs['run.sh']['size']:
        raise ValueError('bound guest entrypoint required')
    plan = {'schema_version': 1, 'kind': 'simpleanalysis-container-job', 'transport': transport,
            'input_directory': str(Path(input_directory).resolve()), 'input_files': inputs,
            'guest_entrypoint': ['/bin/bash', '/tmp/ravel-input/run.sh'],
            'resources': {'max_seconds': max_seconds, 'workers': 1, 'memory_mib': memory_mib, 'pids': 256, 'network': 'none', 'pull': 'never'},
            'physics_validated': False}
    if cpus == 2:
        plan['schema_version'] = 2
        plan['resources']['cpus'] = cpus
    return plan


def plan_hash(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _create_arguments(plan, output, name):
    return ['create', '--name', name, '--cidfile', str(output/'container.cid'),
        '--label', 'org.ravel.plan=' + plan_hash(plan), '--label', 'org.ravel.job=' + name,
        '--platform', 'linux/amd64', '--pull', 'never', '--network', 'none', '--cpus', str(plan['resources'].get('cpus', 1)),
        '--memory', str(plan['resources']['memory_mib']) + 'm', '--pids-limit', '256', '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges', '--user', 'atlas',
        '--entrypoint', '/bin/bash', plan['transport']['image']['reference'], '/tmp/ravel-input/run.sh']


class _Client:
    def __init__(self, transport, output, deadline):
        self.transport, self.output, self.deadline = transport, Path(output), deadline
        self.journal = self.output / 'container-client.jsonl'

    def call(self, arguments, *, cleanup=False, check=True):
        if executable_identity(self.transport['client']['path']) != self.transport['client']:
            raise ValueError('container client changed before invocation')
        remaining = max(0., self.deadline - time.monotonic())
        timeout = min(20., remaining) if cleanup else remaining
        if timeout <= 0:
            raise TimeoutError('container job deadline exhausted')
        command = [self.transport['client']['path'], '--connection', self.transport['connection'], *arguments]
        fact = {'argv': command, 'cwd': str(self.output.resolve()), 'environment': self.transport['environment'],
                'started_ns': time.time_ns(), 'timeout_seconds': timeout, 'cleanup': cleanup}
        try:
            p = subprocess.run(command, cwd=self.output, env=self.transport['environment'], capture_output=True, timeout=timeout)
            fact.update(returncode=p.returncode, stdout_base64=base64.b64encode(p.stdout).decode(), stderr_base64=base64.b64encode(p.stderr).decode())
        except subprocess.TimeoutExpired as exc:
            fact.update(error='timeout', stdout_base64=base64.b64encode(exc.stdout or b'').decode(), stderr_base64=base64.b64encode(exc.stderr or b'').decode())
            raise
        except BaseException as exc:
            fact.update(error=type(exc).__name__ + ': ' + str(exc))
            raise
        finally:
            fact['finished_ns'] = time.time_ns()
            with self.journal.open('a') as stream:
                stream.write(json.dumps(fact, sort_keys=True) + '\n'); stream.flush(); os.fsync(stream.fileno())
        if check and p.returncode:
            raise RuntimeError('container client command failed: ' + arguments[0] + ' exit ' + str(p.returncode))
        return p


def _inspect(client, identity, *, cleanup=False):
    result = client.call(['container', 'inspect', identity], cleanup=cleanup)
    data = json.loads(result.stdout)
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise ValueError('single actual container observation required')
    return data[0]


def _owned(observation, plan, name, cid=None):
    labels = observation.get('Config', {}).get('Labels', {}) or {}
    image = observation.get('Image', '').removeprefix('sha256:')
    if observation.get('Name', '').lstrip('/') != name or labels.get('org.ravel.plan') != plan_hash(plan) or labels.get('org.ravel.job') != name or image != plan['transport']['image']['config_sha256']:
        raise ValueError('observed container is not the approved owned resource')
    if not _CID.fullmatch(observation.get('Id', '')) or cid is not None and observation['Id'] != cid:
        raise ValueError('container identity changed')
    if not isinstance(observation.get('State', {}).get('Running'), bool):
        raise ValueError('actual container running-state observation required')
    return observation['Id']


def _observed_resources(observation, plan):
    # Resource admission is distinct from namespace ownership: a resource
    # mismatch must never prevent cleanup of an already owned container.
    if plan.get('schema_version') == 2:
        host = observation.get('HostConfig', {})
        if host.get('NanoCpus') != plan['resources']['cpus'] * 10**9 or host.get('Memory') != plan['resources']['memory_mib'] * 1024**2 or host.get('PidsLimit') != 256:
            raise ValueError('actual container CPU/memory/PID resources differ from approved plan')


def recover(plan, output, *, max_seconds=60, journal_directory=None):
    """Outer-supervisor cleanup, deriving all commands from the approved plan.

    No command, image or connection is taken from the mutable worker journal.
    The deterministic job name is written before create, covering the interval
    where create succeeded but its host client was killed before returning a CID.
    """
    validate_transport(plan['transport'], for_recovery=True)
    output = Path(output)
    journal = Path(journal_directory) if journal_directory is not None else output
    journal.mkdir(parents=True, exist_ok=True)
    name = 'ravel-sa-' + hashlib.sha256((plan_hash(plan) + str(output.resolve())).encode()).hexdigest()[:24]
    client = _Client(plan['transport'], journal, time.monotonic() + max_seconds)
    result = {'schema_version': 1, 'job_name': name, 'plan_sha256': plan_hash(plan), 'requires_recovery': True, 'errors': []}
    try:
        exists = client.call(['container', 'exists', name], cleanup=True, check=False)
        if exists.returncode == 1:
            result.update(state='absent', requires_recovery=False)
        elif exists.returncode != 0:
            raise RuntimeError('container existence query failed')
        else:
            observation = _inspect(client, name, cleanup=True)
            cid = _owned(observation, plan, name)
            result['before'] = observation
            if observation['State']['Running']:
                client.call(['container', 'stop', '--time', '5', cid], cleanup=True)
            after = _inspect(client, cid, cleanup=True); _owned(after, plan, name, cid)
            result['after'] = after
            if after['State']['Running'] or after['State'].get('Pid', 0) != 0:
                raise RuntimeError('owned container has not reached observed quiescence')
            result.update(state='stopped', requires_recovery=False)
    except BaseException as exc:
        result['errors'].append({'type': type(exc).__name__, 'message': str(exc)})
    atomic_json(journal / 'container-cleanup.json', result)
    return result


def execute(plan, output):
    validate_transport(plan['transport'])
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=True)
    if set(plan) != {'schema_version', 'kind', 'transport', 'input_directory', 'input_files', 'guest_entrypoint', 'resources', 'physics_validated'} or plan['schema_version'] not in (1, 2) or plan['kind'] != 'simpleanalysis-container-job' or plan['guest_entrypoint'] != ['/bin/bash', '/tmp/ravel-input/run.sh'] or plan['physics_validated'] is not False:
        raise ValueError('invalid closed container job plan')
    source = Path(plan['input_directory'])
    if tree_facts(source) != plan['input_files']:
        raise ValueError('approved guest inputs changed')
    if (output/'container-resource.json').exists():
        raise ValueError('preserve earlier owned container job; explicit recovery/new attempt required')
    resources = plan['resources']
    allowed = {'max_seconds', 'workers', 'memory_mib', 'pids', 'network', 'pull'} | ({'cpus'} if plan['schema_version'] == 2 else set())
    if (plan['schema_version'] == 2 and (type(resources.get('cpus')) is not int or resources['cpus'] != 2)) or set(resources) != allowed or resources['workers'] != 1 or resources['pids'] != 256 or resources['network'] != 'none' or resources['pull'] != 'never' or type(resources['max_seconds']) is not int or not 30 <= resources['max_seconds'] <= 86400 or type(resources['memory_mib']) is not int or not 128 <= resources['memory_mib'] <= (4096 if plan['schema_version'] == 1 else 8192):
        raise ValueError('invalid closed resource envelope')
    # Leave a bounded cleanup reserve inside the approved wall-clock budget.
    final_deadline = time.monotonic() + resources['max_seconds']
    deadline = final_deadline - 20
    client = _Client(plan['transport'], output, deadline)
    name = 'ravel-sa-' + hashlib.sha256((plan_hash(plan) + str(output)).encode()).hexdigest()[:24]
    atomic_json(output/'container-resource.json', {'schema_version': 1, 'plan_sha256': plan_hash(plan), 'job_name': name, 'state': 'planned', 'physics_validated': False})
    staged = output/'container-input'; shutil.copytree(source, staged)
    if tree_facts(staged) != plan['input_files']:
        raise ValueError('private guest input transfer differs')
    receipt = {'schema_version': 1, 'plan_sha256': plan_hash(plan), 'job_name': name, 'status': 'failed', 'physics_validated': False}
    error = None
    try:
        created = client.call(_create_arguments(plan, output, name))
        cid = (output/'container.cid').read_text().strip()
        if not _CID.fullmatch(cid) or created.stdout.decode().strip() != cid:
            raise ValueError('created container ID/cidfile differ')
        before = _inspect(client, cid); _owned(before, plan, name, cid)
        _observed_resources(before, plan)
        receipt.update(container_id=cid, before=before)
        client.call(['cp', str(staged), cid + ':/tmp/ravel-input'])
        if tree_facts(staged) != plan['input_files'] or tree_facts(source) != plan['input_files']:
            raise ValueError('guest input changed during transfer')
        started = client.call(['start', '--attach', cid], check=False)
        waited = client.call(['wait', cid])
        if not re.fullmatch(rb'[0-9]+\s*', waited.stdout):
            raise ValueError('actual native container exit code required')
        native_code = int(waited.stdout)
        after = _inspect(client, cid); _owned(after, plan, name, cid)
        _observed_resources(after, plan)
        receipt.update(native_exit_code=native_code, attach_returncode=started.returncode, after=after)
        if after['State']['Running'] or after['State'].get('Pid', 0) != 0 or after['State'].get('ExitCode') != native_code:
            raise ValueError('container wait/inspect quiescence differs')
        guest = output/'container-output'; guest.mkdir()
        copied = client.call(['cp', cid + ':/tmp/ravel-output/.', str(guest)], check=False)
        receipt['output_copy_returncode'] = copied.returncode
        receipt['output_files'] = tree_facts(guest)
        if started.returncode or native_code or copied.returncode:
            raise RuntimeError('native job or retained output transfer failed')
        receipt['status'] = 'passed'
    except BaseException as exc:
        error = exc
        receipt['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        receipt['cleanup'] = recover(plan, output, max_seconds=max(0., final_deadline-time.monotonic()))
        if 'output_files' not in receipt and receipt['cleanup'].get('state') == 'stopped':
            guest = output/'container-output'; guest.mkdir(exist_ok=True)
            try:
                cleanup_client = _Client(plan['transport'], output, final_deadline)
                copied = cleanup_client.call(['cp', receipt['cleanup']['after']['Id'] + ':/tmp/ravel-output/.', str(guest)], cleanup=True, check=False)
                receipt['output_copy_returncode'] = copied.returncode
                receipt['output_files'] = tree_facts(guest)
            except BaseException as exc:
                receipt['output_copy_error'] = {'type': type(exc).__name__, 'message': str(exc)}
        receipt['input_files_after'] = tree_facts(staged)
        if receipt['cleanup']['requires_recovery']:
            receipt['status'] = 'failed'
            error = error or RuntimeError('container cleanup requires recovery')
        atomic_json(output/'container-receipt.json', receipt)
    if error is not None:
        raise error
    return receipt


def verify_receipt(receipt, plan, output):
    """Read-only admission of the retained closed transport, including raw calls.

    This checks an actual supervised execution's retained evidence. It does not
    authenticate arbitrary caller-written JSON or establish native source/build
    correspondence; the build adapter additionally verifies compiler/ELF facts.
    """
    validate_transport(plan['transport'])
    output = Path(output).resolve()
    name = 'ravel-sa-' + hashlib.sha256((plan_hash(plan) + str(output)).encode()).hexdigest()[:24]
    fields = {'schema_version','plan_sha256','job_name','status','physics_validated',
              'container_id','before','native_exit_code','attach_returncode','after',
              'output_copy_returncode','output_files','cleanup','input_files_after'}
    if not isinstance(receipt,dict) or set(receipt)!=fields or receipt['schema_version']!=1 or receipt['plan_sha256']!=plan_hash(plan) or receipt['job_name']!=name or receipt['status']!='passed' or receipt['physics_validated'] is not False:
        raise ValueError('successful exact container receipt required')
    if read_json(output/'container-receipt.json')!=receipt:
        raise ValueError('retained container receipt differs')
    if receipt['input_files_after']!=plan['input_files'] or tree_facts(plan['input_directory'])!=plan['input_files'] or tree_facts(output/'container-input')!=plan['input_files']:
        raise ValueError('approved/transferred guest input bytes differ')
    if tree_facts(output/'container-output')!=receipt['output_files']:
        raise ValueError('retained native output bytes differ')
    cid=receipt['container_id'];_owned(receipt['before'],plan,name,cid);_owned(receipt['after'],plan,name,cid)
    for phase in ('before','after'):
        _observed_resources(receipt[phase],plan)
    if (output/'container.cid').read_text().strip()!=cid:
        raise ValueError('retained native container ID differs')
    if any(type(receipt[key]) is not int or receipt[key]!=0 for key in ('native_exit_code','attach_returncode','output_copy_returncode')) or receipt['after']['State']['Running'] or receipt['after']['State'].get('Pid')!=0 or receipt['after']['State'].get('ExitCode')!=0:
        raise ValueError('successful native exit and observed quiescence required')
    cleanup=receipt['cleanup']
    if read_json(output/'container-cleanup.json')!=cleanup or cleanup.get('state')!='stopped' or cleanup.get('requires_recovery') is not False or cleanup.get('errors')!=[] or cleanup.get('job_name')!=name or cleanup.get('plan_sha256')!=plan_hash(plan):
        raise ValueError('exact successful outer cleanup required')
    for phase in ('before','after'):
        _owned(cleanup[phase],plan,name,cid)
        if cleanup[phase]['State']['Running'] or cleanup[phase]['State'].get('Pid')!=0:
            raise ValueError('cleanup has no observed native quiescence')
    expected=[_create_arguments(plan,output,name),['container','inspect',cid],
        ['cp',str(output/'container-input'),cid+':/tmp/ravel-input'],['start','--attach',cid],
        ['wait',cid],['container','inspect',cid],
        ['cp',cid+':/tmp/ravel-output/.',str(output/'container-output')],
        ['container','exists',name],['container','inspect',name],['container','inspect',cid]]
    rows=[json.loads(line) for line in (output/'container-client.jsonl').read_text().splitlines()]
    if len(rows)!=len(expected):
        raise ValueError('closed native transport has missing or extra client calls')
    prefix=[plan['transport']['client']['path'],'--connection',plan['transport']['connection']]
    last=0;decoded=[]
    for index,(row,arguments) in enumerate(zip(rows,expected)):
        if set(row)!={'argv','cwd','environment','started_ns','timeout_seconds','cleanup','returncode','stdout_base64','stderr_base64','finished_ns'} or row['argv']!=prefix+arguments or row['cwd']!=str(output) or row['environment']!=plan['transport']['environment'] or row['returncode']!=0 or row['cleanup'] is not (index>=7):
            raise ValueError('raw client command/environment differs from closed plan')
        if type(row['started_ns']) is not int or type(row['finished_ns']) is not int or not last<=row['started_ns']<=row['finished_ns'] or not 0<row['timeout_seconds']<=plan['resources']['max_seconds'] or index>=7 and row['timeout_seconds']>20:
            raise ValueError('invalid sequential native client timing')
        last=row['finished_ns']
        try:
            decoded.append(base64.b64decode(row['stdout_base64'],validate=True))
            base64.b64decode(row['stderr_base64'],validate=True)
        except (ValueError,TypeError) as exc:
            raise ValueError('invalid raw native client observation') from exc
    if decoded[0].decode().strip()!=cid or decoded[4].strip()!=b'0':
        raise ValueError('raw create/wait observation differs from native receipt')
    for index,observation in ((1,receipt['before']),(5,receipt['after']),(8,cleanup['before']),(9,cleanup['after'])):
        if json.loads(decoded[index])!=[observation]:
            raise ValueError('raw inspect differs from retained native observation')
    return {'status':'passed','container_id':cid,'image':plan['transport']['image'],
            'observed_exit_code':0,'requires_recovery':False,'physics_validated':False}
