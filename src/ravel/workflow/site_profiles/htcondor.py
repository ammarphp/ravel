"""Configurable, unqualified HTCondor adapter for cluster-generic job scripts.

Native invocation is explicit through this adapter, never through profile render
or procedure export. Unit tests replace every subprocess with inert results.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

JOB_ID = re.compile(r'[0-9]+\.[0-9]+\Z')


def _invoke(argv):
    done = subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)
    if done.returncode: raise ValueError('HTCondor command failed: ' + argv[0])
    return done.stdout.strip()


def _quote(value):
    if any(c in value for c in '\n\r\x00'): raise ValueError('single-line job path required')
    return '"' + value.replace('"', '""') + '"'


def submit(jobscript):
    jobscript = Path(jobscript).absolute()
    if not jobscript.is_file() or jobscript.is_symlink(): raise ValueError('ordinary job script required')
    properties = {}
    for line in jobscript.read_text().splitlines():
        if line.startswith('# properties = '): properties = json.loads(line[len('# properties = '):]); break
    threads = properties.get('threads', 1)
    if type(threads) is not int or threads < 1: raise ValueError('positive job threads required')
    directory = jobscript.parent / '.ravel-condor'; directory.mkdir(exist_ok=True)
    stem = hashlib.sha256(str(jobscript).encode()).hexdigest()
    descriptor = directory / (stem + '.sub')
    lines = ['universe = vanilla', 'executable = /bin/sh', 'arguments = ' + _quote("'" + str(jobscript).replace("'", "''") + "'"),
             'initialdir = ' + _quote(str(Path.cwd())), 'request_cpus = ' + str(threads),
             'output = ' + _quote(str(directory / (stem + '.out'))),
             'error = ' + _quote(str(directory / (stem + '.err'))),
             'log = ' + _quote(str(directory / (stem + '.log'))), 'queue 1']
    resources = properties.get('resources', {})
    for key, directive in [('mem_mb', 'request_memory'), ('disk_mb', 'request_disk')]:
        if key in resources:
            if type(resources[key]) is not int or resources[key] <= 0: raise ValueError('positive declared job resource required')
            lines.insert(-1, directive + ' = ' + str(resources[key]) + 'MB')
    descriptor.write_text('\n'.join(lines) + '\n')
    result = _invoke(['condor_submit', '-terse', str(descriptor)])
    match = re.fullmatch(r'([0-9]+\.[0-9]+)(?: - \1)?', result)
    if not match: raise ValueError('one exact HTCondor job id required')
    return match.group(1)


def status(job_id):
    if not JOB_ID.fullmatch(job_id): raise ValueError('literal HTCondor job id required')
    value = _invoke(['condor_q', job_id, '-autoformat', 'JobStatus', 'ExitCode'])
    if not value: value = _invoke(['condor_history', job_id, '-limit', '1', '-autoformat', 'JobStatus', 'ExitCode'])
    fields = value.split()
    # History can lag the queue; an unknown job is never declared successful.
    if not fields: return 'running'
    if fields[0] == '4': return 'success' if len(fields) == 2 and fields[1] == '0' else 'failed'
    if fields[0] in ('3', '5'): return 'failed'
    if fields[0] in ('1', '2', '6', '7'): return 'running'
    raise ValueError('unrecognized HTCondor job state')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('submit', 'status')); parser.add_argument('target')
    args = parser.parse_args(argv)
    try:
        print(submit(args.target) if args.command == 'submit' else status(args.target)); return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
