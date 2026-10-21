"""Light shared-filesystem HTCondor submit and cached status clients.

The ``ravel-wms-condor-submit`` console script submits only for a live governed launch: it
must present that launch's capability (``wms_policy.CAPABILITY_ENV``) and descend from the
process that holds the launch record, as the executor the launch starts does; the job must
belong to a task the launch authorizes and the profile must be the launch's frozen pin. A
controller run's capability is also checked against the run's store (scope, job count,
revocation). A direct invocation, a stale or foreign capability, a job outside the launch or
a changed profile submits nothing. The in-process ``submit`` function is the executor's
implementation, not a separate entry point.
"""
import argparse
import base64
import binascii
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import sys
import subprocess
import tempfile
import time

from .options import identifier, normalize, single_line, unpack, workflow_dir

JOB_ID = re.compile(r'[0-9]+\.[0-9]+\Z')
RECORD_LIMIT = 64 * 1024
MAX_SUBMIT_RECORDS = 10000
FIELDS = ['ClusterId', 'ProcId', 'JobStatus', 'ExitCode', 'HoldReasonCode', 'RavelPause']


def write_governed_profile(project, *, jobs, options=None):
    """Export a project profile outside workflow/profiles for a pinned RAVEL launch."""
    from . import write_profile
    project = Path(project).resolve()
    effective = dict(options or {})
    if effective.get('workflow_dir', str(project / 'workflow')) != str(project / 'workflow'):
        raise ValueError('governed profile workflow_dir must be the project workflow')
    if effective.get('lease_scope', 'batch-slot') != 'batch-slot':
        raise ValueError('governed HTCondor workers require batch-slot leases')
    effective.update(workflow_dir=str(project / 'workflow'), lease_scope='batch-slot')
    return write_profile(project / '.ravel-site' / 'profiles', 'htcondor', jobs=jobs, options=effective)


def _invoke(argv):
    done = subprocess.run(argv, capture_output=True, text=True, timeout=20, check=False,
                          stdin=subprocess.DEVNULL)
    if done.returncode:
        raise ValueError('HTCondor command failed: ' + argv[0])
    return done.stdout.strip()


def validation_only(argv):
    """Only the non-submitting form, with no overrides and no output file writes."""
    return (isinstance(argv, list) and len(argv) == 4 and argv[0] == 'condor_submit'
            and argv[1:3] == ['-dry-run', '/dev/null']
            and isinstance(argv[3], str) and bool(argv[3]) and not argv[3].startswith('-')
            and not any(c in argv[3] for c in '=\n\r\x00$`'))


def submission_records(options, task=None):
    """Keep governed submissions in the task run, outside scheduler scratch state."""
    wf = workflow_dir(options)
    if task is not None and (wf / 'index.json').is_file():
        rows = json.loads((wf / 'index.json').read_text())['tasks']
        matches = [row for row in rows if row['id'] == task]
        if len(matches) != 1:
            raise ValueError('submission task must resolve to one indexed run')
        return Path(matches[0]['rundir']) / 'logs' / 'htcondor-submit'
    return wf / '.ravel-condor' / 'submissions'


def _submit_invoke(descriptor, record_dir):
    """Drain both pipes while retaining at most 64 KiB each, including on timeout."""
    argv = ['condor_submit', '-terse', str(descriptor)]
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    truncated = dict.fromkeys(buffers, False)
    error, code = None, None
    try:
        with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              stdin=subprocess.DEVNULL,
                              env={k: v for k, v in os.environ.items() if k != 'RAVEL_WMS_CAPABILITY'}) as proc:
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(proc.stdout, selectors.EVENT_READ, 'stdout')
                    selector.register(proc.stderr, selectors.EVENT_READ, 'stderr')
                    deadline = time.monotonic() + 20
                    while selector.get_map():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise subprocess.TimeoutExpired(argv, 20)
                        for key, _ in selector.select(min(remaining, .1)):
                            chunk = os.read(key.fileobj.fileno(), 8192)
                            if not chunk:
                                selector.unregister(key.fileobj)
                                continue
                            name = key.data
                            available = RECORD_LIMIT - len(buffers[name])
                            buffers[name].extend(chunk[:available])
                            truncated[name] |= len(chunk) > available
                code = proc.wait(timeout=max(.001, deadline - time.monotonic()))
            except BaseException:
                proc.kill()
                proc.wait()
                raise
    except (OSError, subprocess.SubprocessError) as exc:
        error = str(exc)[:RECORD_LIMIT]
    for name, content in buffers.items():
        (record_dir / name).write_bytes(content)
    stdout = buffers['stdout'].decode(errors='replace').strip()
    stderr = buffers['stderr'].decode(errors='replace').strip()
    valid = re.fullmatch(r'([0-9]+\.[0-9]+)(?: - \1)?', stdout)
    if code != 0 or error or not valid or truncated['stdout']:
        error = (error or (stderr or stdout)[:4096] or 'no diagnostic output')
        error = ('condor_submit failed (exit ' + str(code) + '): ' + error
                 if code != 0 else 'invalid condor_submit response: ' + error)
    record = {'schema_version': 1, 'argv': argv, 'exit_code': code, 'error': error,
              'job_id': valid.group(1) if valid and not error else None,
              'truncated': truncated, 'submit_file': str(descriptor),
              'stdout': str(record_dir / 'stdout'), 'stderr': str(record_dir / 'stderr')}
    _atomic_json(record_dir / 'receipt.json', record)
    if error:
        raise ValueError(error + '; submit records: ' + str(record_dir))
    return record['job_id']


def _quote(value):
    return '"' + single_line(value).replace('"', '""') + '"'


def _json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def _atomic_json(path, value):
    fd, filename = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write('\n')
        os.replace(filename, path)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


@contextmanager
def _lock(directory, project):
    directory.mkdir(parents=True, exist_ok=True)
    # Prefix distinguishes project ids from the unscoped client.
    key = 'project-' + project if project is not None else 'unscoped'
    with (directory / (key + '.lock')).open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield key
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _directory(options, name, default):
    value = options[name]
    path = Path(value) if value is not None else default
    if not path.is_absolute():
        path = workflow_dir(options) / path
    return path.absolute()


def _tags(properties, project, options):
    if project is None:
        return None
    rule = properties.get('rule', '')
    match = re.fullmatch(r'(?:task_|ravel_verify_)([A-Za-z0-9_.-]{1,64})', rule)
    if not match:
        raise ValueError('project job must name a task rule in run-keys.json')
    task = identifier(match.group(1), 'task id')
    index = json.loads((workflow_dir(options) / 'run-keys.json').read_text())
    if not isinstance(index, dict) or task not in index:
        raise ValueError('task has no run key in run-keys.json')
    return task, identifier(index[task], 'run key')


def _environment(options):
    # Submitter variables are selected by name; no inherited general environment.
    values = {'PATH': options['analysis_bin'] + ':/usr/bin:/bin',
              'HOME': os.environ.get('HOME', str(Path.home()))}
    for name in options['ravel_env']:
        if name == 'RAVEL_WMS_CAPABILITY':
            raise ValueError('a launch capability cannot be exported to batch workers')
        if name in os.environ:
            values[name] = os.environ[name]
    if options['lease_scope'] == 'batch-slot':
        values['RAVEL_LEASE_SCOPE'] = 'batch-slot'
    words = []
    for name, value in sorted(values.items()):
        single_line(value)
        escaped = value if re.fullmatch(r'[A-Za-z0-9_./:=-]+', value) else "'" + value.replace("'", "''") + "'"
        words.append(name + '=' + escaped)
    # HTCondor's new environment syntax doubles embedded quotes.
    return _quote(' '.join(words))


def _publish_script(admission, options):
    """Trusted byte copy to the shared filesystem, never an export of the run store.

    Workers need read access only to the published leaf, with no write grant to its
    directory. Actual remote shared-filesystem delivery remains a site policy obligation;
    mode bits alone cannot stop the owning Unix user from modifying a file.
    """
    source = Path(admission['snapshot_path'])
    captured = source.read_bytes()
    expected = admission['jobscript_sha256']
    if hashlib.sha256(captured).hexdigest() != expected:
        raise ValueError('captured job script digest changed; nothing was submitted')
    root = workflow_dir(options).resolve().parent / '.ravel-controller-submissions'
    store_root = Path(admission['store_path'])
    if root.resolve().is_relative_to(store_root) or store_root.is_relative_to(root.resolve()):
        raise ValueError('controller submission publication must not overlap the run store; nothing was submitted')
    root.mkdir(mode=0o700, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != os.geteuid() or root.stat().st_mode & 0o777 != 0o700:
        raise ValueError('private controller submission directory required; nothing was submitted')
    folder = Path(tempfile.mkdtemp(prefix='job-', dir=root))
    path = folder / 'job.sh'
    with path.open('xb') as stream:
        stream.write(captured)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o400)
    if path.stat().st_nlink != 1 or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('published job script digest changed; nothing was submitted')
    from ravel.controller.confine.locations import package_root
    resources = admission['resources']
    output = workflow_dir(options).resolve() / '.ravel-job-output' / (
        admission['launch_id'] + '-' + str(admission['submissions']).zfill(6))
    descriptor = {'schema_version': 1, 'script_path': str(path), 'script_sha256': expected,
                  'reads': admission['input_digests'], 'output_dir': str(output),
                  'resources': {'cpus': resources['threads'], 'memory_mib': resources['mem_mb'],
                                'wall_seconds': resources['runtime'] * 60}}
    job_descriptor = folder / 'job.json'
    job_descriptor.write_text(json.dumps(descriptor, sort_keys=True, allow_nan=False) + '\n')
    job_descriptor.chmod(0o400)
    code = ('import sys;sys.path.insert(0,' + repr(str(package_root())) + ');'
            'from ravel.controller.confine.job import main;raise SystemExit(main(sys.argv[1:]))')
    wrapper = folder / 'run.sh'
    wrapper.write_text('#!/bin/sh\nexec ' + shlex.join([str(Path(sys.executable).absolute()), '-I', '-c', code,
                                                      str(job_descriptor)]) + '\n')
    wrapper.chmod(0o400)
    folder.chmod(0o500)
    admission['published_script_path'] = str(path)
    admission['job_descriptor_path'] = str(job_descriptor)
    return wrapper


def check_credential(profile=None):
    """Inspect an opted-in proxy immediately before its submission admission."""
    _, options = unpack(profile)
    name = options['x509userproxy_env']
    from ..wms_policy import CAPABILITY_ENV
    if name == CAPABILITY_ENV:
        raise ValueError('a launch capability cannot be exported as a credential')
    if name or options['use_x509userproxy']:
        path = os.environ.get(name) if name else None
        if name and not path:
            raise ValueError('credential path environment variable is absent')
        from ravel.controller.routes.study.site import require_credential
        require_credential(path)


def submit(jobscript, *, profile=None, _admission=None):
    check_credential(profile)
    project, options = unpack(profile)
    from .. import wms_policy
    from ravel.controller.confine import runs
    token = os.environ.get(wms_policy.CAPABILITY_ENV, '')
    controlled = runs.owner_of(workflow_dir(options)) is not None
    index = workflow_dir(options) / 'index.json'
    if index.exists():
        for row in wms_policy._rows(index, True):
            if runs.owner_of(row['rundir']) is not None:
                controlled = True
    if _admission is None and (controlled or token.startswith('rwc1.')):
        _admission = bind_submission(jobscript, profile)
    admitted = (_admission or {}).get('admission')
    if admitted is not None:
        effective = hashlib.sha256(json.dumps(profile, sort_keys=True, allow_nan=False).encode()).hexdigest()
        if admitted['submission_profile_sha256'] != effective:
            raise ValueError('effective submission profile changed after admission; nothing was submitted')
        jobscript = _publish_script(admitted, options)
    jobscript = Path(jobscript).absolute()
    if not jobscript.is_file() or jobscript.is_symlink():
        raise ValueError('ordinary job script required')
    properties = {}
    script_bytes = Path(admitted['published_script_path']).read_bytes() if admitted is not None else jobscript.read_bytes()
    if admitted is not None and hashlib.sha256(script_bytes).hexdigest() != admitted['jobscript_sha256']:
        raise ValueError('published job script changed after admission; nothing was submitted')
    for line in script_bytes.decode('utf-8').splitlines():
        if line.startswith('# properties = '):
            properties = json.loads(line[len('# properties = '):])
            break
    if not isinstance(properties, dict):
        raise ValueError('job properties must be a JSON object')
    threads = properties.get('threads', 1)
    if type(threads) is not int or threads < 1:
        raise ValueError('positive job threads required')
    tags = _tags(properties, project, options)
    resources = properties.get('resources', {})
    if not isinstance(resources, dict):
        raise ValueError('job resources must be a JSON object')
    amounts = {key: resources.get(key, options[key]) for key in ('mem_mb', 'runtime')}
    if 'disk_mb' in resources:
        amounts['disk_mb'] = resources['disk_mb']
    if any(type(v) is not int or v <= 0 for v in amounts.values()):
        raise ValueError('positive integer job resources required')
    default_log = workflow_dir(options) / '.ravel-condor' if admitted is not None else jobscript.parent / '.ravel-condor'
    directory = _directory(options, 'log_dir', default_log)
    output = _directory(options, 'output_dir', directory)
    error = _directory(options, 'error_dir', directory)
    stem = hashlib.sha256(str(jobscript).encode()).hexdigest()
    lines = ['universe = vanilla', 'executable = /bin/sh',
             'arguments = ' + _quote("'" + str(jobscript).replace("'", "''") + "'"),
             'initialdir = ' + _quote(str(workflow_dir(options))), 'request_cpus = ' + str(threads),
             'request_memory = ' + str(amounts['mem_mb']) + 'MB',
             options['runtime_attribute'] + ' = ' + str(amounts['runtime'] * 60),
             'output = ' + _quote(str(output / (stem + '.out'))),
             'error = ' + _quote(str(error / (stem + '.err'))),
             'log = ' + _quote(str(directory / (stem + '.log'))),
             'getenv = False', 'environment = ' + _environment(options), 'should_transfer_files = NO',
             'periodic_remove = (JobStatus == 5) && (HoldReasonCode =!= 1) && (HoldReasonCode =!= 15) && '
             '(RavelPause =?= undefined) && ((time() - EnteredCurrentStatus) > ' + str(options['hold_grace_seconds']) + ')']
    if 'disk_mb' in amounts:
        lines.append('request_disk = ' + str(amounts['disk_mb']) + 'MB')
    if tags:
        task, run = tags
        lines += ['+RavelProject = "' + project + '"', '+RavelRun = "' + run + '"',
                  '+RavelTask = "' + task + '"', 'batch_name = "' + run + '"']
    if options['flavour'] is not None:
        lines.append('+JobFlavour = ' + json.dumps(options['flavour']))
    if options['use_x509userproxy']:
        lines.append('use_x509userproxy = true')
    if options['x509userproxy_env'] == wms_policy.CAPABILITY_ENV:
        raise ValueError('a launch capability cannot be exported as a credential')
    if options['x509userproxy_env']:
        path = os.environ.get(options['x509userproxy_env'])
        if not path:
            raise ValueError('credential path environment variable is absent')
        lines.append('x509userproxy = ' + _quote(path))
    lines += [key + ' = ' + str(value) for key, value in sorted(options['site_options'].items())]
    lines.append('queue 1')
    for folder in (directory, output, error):
        folder.mkdir(parents=True, exist_ok=True)
    content = ('\n'.join(lines) + '\n').encode()
    if len(content) > RECORD_LIMIT:
        raise ValueError('submit description exceeds 64 KiB record limit')
    record_task = tags[0] if tags else None
    if record_task is None and (workflow_dir(options) / 'index.json').is_file():
        match = re.fullmatch(r'(?:task_|ravel_verify_)([A-Za-z0-9_.-]{1,64})', properties.get('rule', ''))
        if not match:
            raise ValueError('indexed submission must identify its task run')
        record_task = match.group(1)
    records = submission_records(options, record_task)
    # Reserve under the existing project lock; never prune evidence to make room.
    with _lock(records, project):
        if sum(p.is_dir() for p in records.iterdir()) >= MAX_SUBMIT_RECORDS:
            raise ValueError('submit record limit reached; preserve records and escalate')
        attempt = Path(tempfile.mkdtemp(prefix='submit-', dir=records))
    descriptor = attempt / 'job.sub'
    descriptor.write_bytes(content)
    if admitted is not None:
        _atomic_json(attempt / 'script.json', {'path': str(jobscript),
                     'sha256': admitted['jobscript_sha256'],
                     'captured_script_path': admitted['published_script_path'],
                     'job_descriptor_path': admitted['job_descriptor_path'], 'run_id': admitted['run_id'],
                     'launch_id': admitted['launch_id']})
    job_id = _submit_invoke(descriptor, attempt)
    state_dir = workflow_dir(options) / '.ravel-condor'
    with _lock(state_dir, project) as key:
        index_path = state_dir / (key + '.jobs.json')
        index = _json(index_path, {'jobs': {}})
        index['options'] = options
        index['jobs'][job_id] = {'log_dir': str(directory)}
        # A recorded answer belongs to an earlier job with this id.
        index.get('settled', {}).pop(job_id, None)
        _atomic_json(index_path, index)
        (state_dir / (key + '.snapshot.json')).unlink(missing_ok=True)
    return job_id


def _state(fields):
    if not fields:
        return None
    state = fields[0]
    if state == '4':
        return 'success' if len(fields) > 1 and fields[1] == '0' else 'failed'
    if state == '5':
        reason = fields[2] if len(fields) > 2 else 'undefined'
        pause = fields[3] if len(fields) > 3 else 'undefined'
        return 'running' if reason in ('1', '15') or pause != 'undefined' else 'failed'
    if state == '3':
        return 'failed'
    if state in ('1', '2', '6', '7'):
        return 'running'
    return None


def _rows(value):
    rows = {}
    for line in value.splitlines():
        fields = line.split()
        if len(fields) >= 6 and fields[0].isdigit() and fields[1].isdigit():
            rows[fields[0] + '.' + fields[1]] = fields[2:6]
    return rows


def _missing(job_id, directory, options, now):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (job_id + '.missing')
    if not path.exists():
        path.write_text(str(float(now)) + '\n')
    first = float(path.read_text())
    return 'running' if now - first < options['missing_grace_seconds'] else 'failed'


def status(job_id, *, project_id=None, now=None, profile=None):
    """Answer one job using a project snapshot under a shared POSIX file lock."""
    if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
        raise ValueError('literal HTCondor job id required')
    profile_project, options = unpack(profile)
    if project_id is None:
        project_id = profile_project
    elif profile_project is not None and profile_project != project_id:
        raise ValueError('status project differs from profile')
    if project_id is not None:
        identifier(project_id, 'project_id')
    state_dir = workflow_dir(options) / '.ravel-condor'
    with _lock(state_dir, project_id) as key:
        # Observe time in lock order: a caller that waited must not mistake a
        # competing caller's newer snapshot for a backwards clock jump.
        now = time.time() if now is None else now
        index_path = state_dir / (key + '.jobs.json')
        index = _json(index_path, {'jobs': {}})
        if profile is None and 'options' in index:
            options = normalize(index['options'])
        fallback = _directory(options, 'log_dir', state_dir)
        log_dir = Path(index['jobs'].get(job_id, {}).get('log_dir', fallback))
        if project_id is None:
            fields = ['-af', *FIELDS[2:]]
            value = _invoke(['condor_q', job_id, *fields])
            if not value:
                value = _invoke(['condor_history', job_id, '-limit', '1', *fields])
            parts = value.splitlines()[0].split() if value else []
        else:
            cache_path = state_dir / (key + '.snapshot.json')
            snapshot = _json(cache_path, {})
            age = now - snapshot.get('at', float('-inf'))
            if not snapshot or age < 0 or age >= options['status_cache_seconds']:
                constraint = 'RavelProject == "' + project_id + '"'
                rows = _rows(_invoke(['condor_q', '-constraint', constraint, '-af', *FIELDS]))
                # History answers and expired missing jobs are settled: recorded once
                # and left out of later history queries. A queued job is never settled.
                settled = index.get('settled', {})
                recorded = {j: row for j, row in settled.items() if j not in rows}
                missing = (set(index['jobs']) | {job_id}) - set(rows) - set(recorded)
                if missing:
                    # Restrict history to the missing ids, so unrelated old project
                    # jobs cannot consume the bounded result count.
                    ids = ' || '.join('(ClusterId == ' + j.split('.')[0] + ' && ProcId == ' + j.split('.')[1] + ')'
                                     for j in sorted(missing))
                    history_constraint = constraint + ' && (' + ids + ')'
                    recorded.update(_rows(_invoke(['condor_history', '-constraint', history_constraint,
                                                   '-limit', str(len(missing)), '-af', *FIELDS])))
                if recorded != settled:
                    index['settled'] = recorded
                    _atomic_json(index_path, index)
                snapshot = {'at': now, 'jobs': {**recorded, **rows}}
                _atomic_json(cache_path, snapshot)
            parts = snapshot['jobs'].get(job_id, [])
        result = _state(parts)
        if result is None:
            result = _missing(job_id, log_dir, options, now)
            if result == 'failed' and project_id is not None and job_id not in index.get('settled', {}):
                index.setdefault('settled', {})[job_id] = []
                _atomic_json(index_path, index)
            return result
        (log_dir / (job_id + '.missing')).unlink(missing_ok=True)
        return result


def bind_submission(jobscript, profile, profile_path=None):
    """The governed launch admitting this job, or a ValueError; nothing is submitted on refusal."""
    from .. import wms_policy
    project, options = unpack(profile)
    record = wms_policy.governed_submission(workflow_dir(options))
    pinned = record.get('site_profile')
    current = None
    if pinned is not None or profile_path:
        from .. import wms_site
        folder = Path(profile_path).absolute().parent if profile_path else None
        try:
            current = wms_site.profile_pin(folder) if folder is not None else None
        except ValueError:
            current = None
        if current is not None and json.loads(Path(profile_path).read_text()) != profile:
            raise ValueError('effective options differ from the frozen site profile; nothing was submitted')
        if pinned is not None and (current is None or str(folder) != str(Path(pinned['path'])) or current != pinned):
            raise ValueError('the submit profile is not the launch\'s frozen site profile; nothing was submitted')
    admission = None
    if record.get('controller_run') is not None:
        from ravel.controller.routes.study import site
        from ravel.controller.confine import verify_capability
        options_for_admission = {
            'profile_sha256': current['sha256'] if current else None,
            'resource_defaults': {k: options[k] for k in ('mem_mb', 'runtime')},
            'authorized_tasks': record.get('exports') or {}}
        # These are alternative final guards. Each calls the consuming verifier
        # once; submission below uses its captured script without re-verifying.
        if site.active_launch(run_id=record['controller_run']):
            admission = site.require_capability(Path(jobscript).absolute(),
                run_id=record['controller_run'], **options_for_admission)
        else:
            admission = verify_capability(os.environ.get(wms_policy.CAPABILITY_ENV),
                Path(jobscript).absolute(), **options_for_admission)
        admission['submission_profile_sha256'] = hashlib.sha256(
            json.dumps(profile, sort_keys=True, allow_nan=False).encode()).hexdigest()
        properties = admission['properties']
    else:
        path = Path(jobscript).absolute()
        if not path.is_file() or path.is_symlink():
            raise ValueError('ordinary job script required; nothing was submitted')
        from ravel.controller.confine.capability import job_properties
        properties = job_properties(path)
    tags = _tags(properties, project, options) if isinstance(properties, dict) else None
    task = tags[0] if tags else None
    if task is None and project is None and isinstance(properties, dict):
        match = re.fullmatch(r'(?:task_|ravel_verify_)([A-Za-z0-9_.-]{1,64})', str(properties.get('rule', '')))
        task = match.group(1) if match else None
    if task is None or task not in (record.get('exports') or {}):
        raise ValueError(f'the job of task {task!r} is outside the live launch of task {record.get("task")!r}; '
                         'nothing was submitted')
    record = {**record, 'task': task}
    if admission is not None:
        record['admission'] = admission
    return record


def _cli(command, argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-id')
    parser.add_argument('--options-json')
    parser.add_argument('--options-base64')
    parser.add_argument('--profile', help='profile.json from write_profile')
    parser.add_argument('target')
    args = parser.parse_args(argv)
    try:
        if sum(value is not None for value in (args.profile, args.options_json, args.options_base64)) > 1:
            raise ValueError('choose one profile options source')
        encoded = base64.b64decode(args.options_base64, altchars=b'-_', validate=True).decode() if args.options_base64 else None
        profile = json.loads(Path(args.profile).read_text()) if args.profile else {
            'options': json.loads(encoded or args.options_json) if encoded or args.options_json else {}}
        if args.project_id is not None:
            if profile.get('project_id') not in (None, args.project_id):
                raise ValueError('command project differs from profile')
            profile['project_id'] = args.project_id
        admission = bind_submission(args.target, profile, args.profile) if command == 'submit' else None
        print(submit(args.target, profile=profile, _admission=admission) if command == 'submit'
              else status(args.target, project_id=args.project_id, profile=profile))
        return 0
    except (OSError, ValueError, binascii.Error, subprocess.SubprocessError) as exc:
        parser.exit(1, str(exc) + '\n')


def submit_main(argv=None):
    return _cli('submit', argv)


def status_main(argv=None):
    return _cli('status', argv)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('submit', 'status'))
    args, rest = parser.parse_known_args(argv)
    return _cli(args.command, rest)


if __name__ == '__main__':
    raise SystemExit(main())
