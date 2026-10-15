"""Light shared-filesystem HTCondor submit and cached status clients."""
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
import subprocess
import tempfile
import time

from .options import identifier, normalize, single_line, unpack, workflow_dir

JOB_ID = re.compile(r'[0-9]+\.[0-9]+\Z')
FIELDS = ['ClusterId', 'ProcId', 'JobStatus', 'ExitCode', 'HoldReasonCode', 'RavelPause']


def _invoke(argv):
    done = subprocess.run(argv, capture_output=True, text=True, timeout=20, check=False,
                          stdin=subprocess.DEVNULL)
    if done.returncode:
        raise ValueError('HTCondor command failed: ' + argv[0])
    return done.stdout.strip()


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


def submit(jobscript, *, profile=None):
    project, options = unpack(profile)
    jobscript = Path(jobscript).absolute()
    if not jobscript.is_file() or jobscript.is_symlink():
        raise ValueError('ordinary job script required')
    properties = {}
    for line in jobscript.read_text().splitlines():
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
    directory = _directory(options, 'log_dir', jobscript.parent / '.ravel-condor')
    output = _directory(options, 'output_dir', directory)
    error = _directory(options, 'error_dir', directory)
    stem = hashlib.sha256(str(jobscript).encode()).hexdigest()
    descriptor = directory / (stem + '.sub')
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
    if options['x509userproxy_env']:
        path = os.environ.get(options['x509userproxy_env'])
        if not path:
            raise ValueError('credential path environment variable is absent')
        lines.append('x509userproxy = ' + _quote(path))
    lines += [key + ' = ' + str(value) for key, value in sorted(options['site_options'].items())]
    lines.append('queue 1')
    for folder in (directory, output, error):
        folder.mkdir(parents=True, exist_ok=True)
    descriptor.write_text('\n'.join(lines) + '\n')
    result = _invoke(['condor_submit', '-terse', str(descriptor)])
    match = re.fullmatch(r'([0-9]+\.[0-9]+)(?: - \1)?', result)
    if not match:
        raise ValueError('one exact HTCondor job id required')
    job_id = match.group(1)
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
    now = time.time() if now is None else now
    state_dir = workflow_dir(options) / '.ravel-condor'
    with _lock(state_dir, project_id) as key:
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
        print(submit(args.target, profile=profile) if command == 'submit'
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
