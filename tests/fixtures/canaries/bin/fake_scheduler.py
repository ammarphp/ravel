"""HTCondor stand-in for integration canaries that runs each submitted job as a batch node would.

Install this file under the supported command names ``condor_submit``,
``condor_q``, ``condor_history`` and ``condor_rm``. Each wrapper passes the
state path first and its own command path second.

``condor_submit`` records the descriptor and starts the described job as a detached
process in its own session: the executable and arguments come from the descriptor
(``executable = /bin/sh`` with ``arguments = '<script>'``, or a plain executable path),
the working directory is ``initialdir`` (else the descriptor's directory), standard
output and error are appended to the descriptor's ``output`` and ``error`` paths (else
to files in a per-job directory next to the state file) and standard input is
``/dev/null``. The environment is only the descriptor's ``environment`` value
(HTCondor's double-quoted new syntax), with ``PATH=/usr/bin:/bin`` and a per-job
``HOME`` added when the descriptor names neither; ``getenv = False`` holds because
nothing else is inherited. As the real starter does, the stand-in gives each job an owned
scratch directory holding its job ad (``_CONDOR_SCRATCH_DIR``, ``_CONDOR_JOB_AD``). A small shell wrapper records the job's exit code in its
job directory. The job row gains ``pid``, ``pgid``, ``job_dir`` and ``started_utc``.

Every ``condor_q`` or ``condor_history`` query derives the status of a started job
whose recorded status is still 2: an exit file gives 4 with its code, a live process
stays 2, and a process that vanished without an exit file gives 4 with an undefined
ExitCode (a lost job). ``condor_rm`` terminates the job's process group (SIGTERM,
then SIGKILL after two seconds) and records status 3. Tests may still pin completion
with the state's ``new_job_status``/``new_job_exit_code`` or by editing a job's
``status`` and ``exit_code`` fields; any recorded status other than 2 wins over the
derivation.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time


ACTIVE_STATUSES = {1, 2, 5, 6, 7}


def _load(path):
    if not path.is_file():
        return {'next': 100, 'jobs': [], 'removed': [], 'events': []}
    state = json.loads(path.read_text())
    state.setdefault('next', 100)
    state.setdefault('jobs', [])
    state.setdefault('removed', [])
    state.setdefault('events', [])
    return state


def _save(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(state, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _descriptor(path):
    values = {}
    if not path or not Path(path).is_file():
        return values
    for line in Path(path).read_text(errors='replace').splitlines():
        if ' = ' not in line:
            continue
        key, value = line.split(' = ', 1)
        values[key.strip()] = value.strip().strip('"')
    return values


def _new_syntax_words(raw):
    """Words of an HTCondor new-syntax value: whitespace-separated, ``'...'`` quoting, ``''`` a quote."""
    text = (raw or '').strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1].replace('""', '"')
    words, current, quoted, started, index = [], [], False, False, 0
    while index < len(text):
        char = text[index]
        if quoted:
            if char == "'" and text[index + 1:index + 2] == "'":
                current.append("'")
                index += 1
            elif char == "'":
                quoted = False
            else:
                current.append(char)
        elif char == "'":
            quoted = started = True
        elif char.isspace():
            if started:
                words.append(''.join(current))
                current, started = [], False
        else:
            current.append(char)
            started = True
        index += 1
    if quoted:
        raise ValueError('unterminated single quote in descriptor value')
    if started:
        words.append(''.join(current))
    return words


def _raw_fields(text):
    """Descriptor values before quote stripping; the last assignment of a key wins."""
    values = {}
    for line in text.splitlines():
        match = re.match(r'\s*([^=\s]+)\s*=\s*(.*?)\s*$', line)
        if match:
            values[match.group(1).lower()] = match.group(2)
    return values


def _job_environment(raw, home):
    environment = {}
    for word in _new_syntax_words(raw):
        name, separator, value = word.partition('=')
        if not separator or not name:
            raise ValueError('environment item is not NAME=value: ' + word)
        environment[name] = value
    environment.setdefault('PATH', '/usr/bin:/bin')
    if 'HOME' not in environment:
        home.mkdir(parents=True, exist_ok=True)
        environment['HOME'] = str(home)
    return environment


def _utc_now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _start(cluster, description_path, descriptor_text, state_path, job):
    """Start the described job detached; returns the job-row additions or None for no executable."""
    raw = _raw_fields(descriptor_text)
    executable = _new_syntax_words(raw['executable'])[0] if raw.get('executable') else None
    if not executable:
        return None
    submit_dir = Path(os.getcwd())
    description_dir = Path(description_path).absolute().parent if description_path else submit_dir
    initialdir = _new_syntax_words(raw['initialdir'])[0] if raw.get('initialdir') else None
    cwd = Path(initialdir) if initialdir else description_dir
    if not cwd.is_absolute():
        cwd = submit_dir / cwd
    if not cwd.is_dir():
        raise ValueError('initialdir is not a directory: ' + str(cwd))
    program = Path(executable)
    if not program.is_absolute():
        program = submit_dir / program
    argv = [str(program), *_new_syntax_words(raw.get('arguments', ''))]
    job_dir = state_path.parent / (state_path.stem + '-jobs') / str(cluster)
    job_dir.mkdir(parents=True, exist_ok=True)

    def stream(key, fallback):
        value = _new_syntax_words(raw[key])[0] if raw.get(key) else None
        path = Path(value) if value else job_dir / fallback
        if not path.is_absolute():
            path = cwd / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    stdout_path, stderr_path = stream('output', 'stdout'), stream('error', 'stderr')
    environment = _job_environment(raw.get('environment', ''), job_dir / 'home')
    # The starter's facts a worker slot provides: an owned scratch directory holding the job ad.
    scratch = job_dir / 'scratch'
    scratch.mkdir(parents=True, exist_ok=True)
    os.chmod(scratch, 0o700)
    ad = scratch / '.job.ad'
    ad.write_text(f'ClusterId = {cluster}\nProcId = 0\nJobUniverse = 5\nIwd = "{cwd}"\n'
                  f'Cmd = "{argv[0]}"\nRavelTag = "{job.get("tag", "")}"\n')
    environment.setdefault('_CONDOR_SCRATCH_DIR', str(scratch))
    environment.setdefault('_CONDOR_JOB_AD', str(ad))
    exit_path = job_dir / 'exit'
    command = (' '.join(shlex.quote(word) for word in argv) + '; code=$?; echo "$code" > '
               + shlex.quote(str(exit_path) + '.part') + ' && mv -f ' + shlex.quote(str(exit_path) + '.part')
               + ' ' + shlex.quote(str(exit_path)))
    with open(stdout_path, 'ab') as out, open(stderr_path, 'ab') as err:
        process = subprocess.Popen(['/bin/sh', '-c', command], cwd=str(cwd), env=environment,
                                   stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                   close_fds=True, start_new_session=True)
    return {'pid': process.pid, 'pgid': process.pid, 'job_dir': str(job_dir), 'started_utc': _utc_now(),
            'job_argv': argv, 'job_cwd': str(cwd), 'stdout_path': str(stdout_path),
            'stderr_path': str(stderr_path), 'job_environment': environment}


def _alive(pid, pgid=None):
    """Whether ``pid`` is a live, non-zombie process (of group ``pgid`` when given)."""
    try:
        os.waitpid(pid, os.WNOHANG)  # reaps only when this process is the parent
    except (ChildProcessError, OSError):
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        if pgid is not None and os.getpgid(pid) != pgid:
            return False  # the identifier now belongs to an unrelated process
    except ProcessLookupError:
        return False
    proc = Path('/proc') / str(pid) / 'stat'
    try:
        if proc.is_file():
            return proc.read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    except (OSError, IndexError):
        pass
    for ps in ('/bin/ps', '/usr/bin/ps'):
        if os.path.exists(ps):
            done = subprocess.run([ps, '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True,
                                  check=False)
            stat = done.stdout.strip()
            return bool(stat) and not stat.startswith('Z')
    return True


def _group_alive(pgid):
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return _alive(pgid, pgid) or _any_member(pgid)


def _any_member(pgid):
    for ps in ('/bin/ps', '/usr/bin/ps'):
        if os.path.exists(ps):
            done = subprocess.run([ps, '-A', '-o', 'pgid=,stat='], capture_output=True, text=True,
                                  check=False)
            return any(len(row.split()) >= 2 and row.split()[0] == str(pgid)
                       and not row.split()[1].startswith('Z') for row in done.stdout.splitlines())
    return True


def _derive(job):
    """Refresh a started job whose recorded status is still running; a pinned status wins."""
    if 'pid' not in job or int(job.get('status', 2)) != 2:
        return
    exit_path = Path(job['job_dir']) / 'exit'
    if exit_path.is_file():
        text = exit_path.read_text().strip()
        job['status'] = 4
        job['exit_code'] = int(text) if re.fullmatch(r'-?\d+', text) else None
        job.setdefault('finished_utc', _utc_now())
    elif not _alive(int(job['pid']), int(job.get('pgid', job['pid']))):
        if exit_path.is_file():  # finished between the two observations
            _derive(job)
            return
        job['status'] = 4
        job['exit_code'] = None
        job['lost'] = True
        job.setdefault('finished_utc', _utc_now())


def _terminate(job):
    pgid = job.get('pgid')
    if pgid is None:
        return
    pgid = int(pgid)
    if not _alive(int(job['pid']), pgid) and not _any_member(pgid):
        return
    for sig, wait in ((signal.SIGTERM, 2.0), (signal.SIGKILL, 2.0)):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            return
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if not _group_alive(pgid):
                return
            time.sleep(0.05)


def _job_view(job, command):
    return {
        'ClusterId': job['cluster'],
        'ProcId': 0,
        'JobStatus': int(job.get('status', 2)),
        'ExitCode': job.get('exit_code'),
        'HoldReasonCode': job.get('hold_reason_code', 0),
        'RavelPause': job.get('ravel_pause', 0),
        'RavelTag': job.get('tag', ''),
        'RavelProject': job.get('project', ''),
    }


def _matches_constraint(job, constraint):
    if not constraint:
        return True
    view = _job_view(job, 'condor_q')
    tag = re.search(r'RavelTag\s*==\s*"([^"]*)"', constraint)
    project = re.search(r'RavelProject\s*==\s*"([^"]*)"', constraint)
    ids = re.findall(r'ClusterId\s*==\s*(\d+)\s*&&\s*ProcId\s*==\s*(\d+)', constraint)
    if tag and view['RavelTag'] != tag.group(1):
        return False
    if project and view['RavelProject'] != project.group(1):
        return False
    if ids and not any(str(view['ClusterId']) == cluster and str(view['ProcId']) == proc
                       for cluster, proc in ids):
        return False
    return True


def _query(command, args, state):
    constraint = args[args.index('-constraint') + 1] if '-constraint' in args else None
    selected_id = None
    if args and re.fullmatch(r'\d+(?:\.\d+)?', args[0]):
        selected_id = int(args[0].split('.', 1)[0])
    jobs = []
    for job in state['jobs']:
        _derive(job)
        status = int(job.get('status', 2))
        removed = str(job['cluster']) in {str(value) for value in state.get('removed', [])}
        if selected_id is not None and job['cluster'] != selected_id:
            continue
        if command == 'condor_q' and (removed or status not in ACTIVE_STATUSES):
            continue
        if not _matches_constraint(job, constraint):
            continue
        jobs.append(job)
    if '-json' in args:
        return json.dumps([_job_view(job, command) for job in jobs]) + ('\n' if jobs else '')
    if '-af' in args:
        fields = args[args.index('-af') + 1:]
        lines = []
        for job in jobs:
            view = _job_view(job, command)
            values = []
            for field in fields:
                value = view.get(field)
                values.append('undefined' if value is None else str(value))
            lines.append(' '.join(values))
        return '\n'.join(lines) + ('\n' if lines else '')
    return ''.join(json.dumps(_job_view(job, command)) + '\n' for job in jobs)


def _run(command, args, state, state_path):
    if command == 'condor_submit':
        description_path = next((arg for arg in reversed(args) if not arg.startswith('-')), None)
        descriptor_text = Path(description_path).read_text(errors='replace') if description_path else ''
        fields = _descriptor(description_path)
        executable = fields.get('executable')
        launcher_path = Path(executable) if executable else None
        launcher_bytes = launcher_path.read_bytes() if launcher_path and launcher_path.is_file() else b''
        script_candidate = executable
        if executable in ('/bin/sh', '/bin/bash'):
            arguments = shlex.split(fields.get('arguments', ''))
            script_candidate = arguments[0] if arguments else None
        script_path = Path(script_candidate) if script_candidate else None
        if script_path and not script_path.is_absolute() and fields.get('initialdir'):
            script_path = Path(fields['initialdir']) / script_path
        script_bytes = (script_path.read_bytes() if script_path and script_path.is_file()
                        and not script_path.is_symlink() else b'')
        if fields.get('initialdir') and not Path(fields['initialdir']).is_dir():
            raise ValueError('initialdir is not a directory: ' + fields['initialdir'])
        cluster = int(state['next'])
        state['next'] = cluster + 1
        status = int(state.get('new_job_status', 2))
        exit_code = state.get('new_job_exit_code')
        job = {
            'cluster': cluster,
            'proc': 0,
            'status': status,
            'exit_code': exit_code,
            'hold_reason_code': 0,
            'ravel_pause': 0,
            'tag': fields.get('+RavelTag', fields.get('batch_name', '')),
            'project': fields.get('+RavelProject', ''),
            'argv': list(args),
            'description_path': str(Path(description_path).absolute()) if description_path else None,
            'description_sha256': hashlib.sha256(descriptor_text.encode()).hexdigest(),
            'description_text': descriptor_text,
            # Retain the original fixture fields; they pin the submitted description.
            'sha256': hashlib.sha256(descriptor_text.encode()).hexdigest(),
            'text': descriptor_text[:8192],
            'script_path': str(script_path.absolute()) if script_path else None,
            'script_sha256': hashlib.sha256(script_bytes).hexdigest(),
            'script_text': script_bytes.decode(errors='replace'),
            'launcher_path': str(launcher_path.absolute()) if launcher_path else None,
            'launcher_sha256': hashlib.sha256(launcher_bytes).hexdigest(),
            'cwd': fields.get('initialdir', os.getcwd()),
            'submitted_cwd': os.getcwd(),
        }
        if 'new_job_status' in state or 'new_job_exit_code' in state:
            job['pinned_status'] = True  # a test-modelled outcome; the payload is not started
        else:
            started = _start(cluster, description_path, descriptor_text, state_path, job)
            if started:
                job.update(started)
        state['jobs'].append(job)
        return f'{cluster}.0 - {cluster}.0\n'
    if command in ('condor_q', 'condor_history'):
        return _query(command, args, state)
    if command == 'condor_rm':
        job_ids = [arg for arg in args if re.fullmatch(r'\d+(?:\.\d+)?', arg)]
        for identifier in job_ids:
            cluster = int(identifier.split('.', 1)[0])
            if str(cluster) not in {str(value) for value in state['removed']}:
                state['removed'].append(str(cluster))
            for job in state['jobs']:
                if job['cluster'] == cluster:
                    _terminate(job)
                    job['status'] = 3
                    job.setdefault('removed_utc', _utc_now())
        return ''.join(f'Removed job {identifier}\n' for identifier in job_ids)
    return ''


def main(argv):
    state_path, command, args = Path(argv[0]), Path(argv[1]).name, argv[2:]
    if command not in {'condor_submit', 'condor_q', 'condor_history', 'condor_rm'}:
        print('unsupported inert scheduler command: ' + command, file=sys.stderr)
        return 2
    lock_path = state_path.with_suffix(state_path.suffix + '.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = _load(state_path)
        try:
            stdout, stderr, code = _run(command, args, state, state_path), '', 0
        except (OSError, ValueError) as exc:
            stdout, stderr, code = '', 'ERROR: ' + str(exc) + '\n', 1
        state['events'].append({'sequence': len(state['events']) + 1, 'command': command,
                                'args': list(args), 'cwd': os.getcwd(), 'returncode': code,
                                'stdout': stdout, **({'stderr': stderr} if stderr else {})})
        _save(state_path, state)
    sys.stdout.write(stdout)
    sys.stderr.write(stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
