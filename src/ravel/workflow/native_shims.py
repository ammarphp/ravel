"""Approval-checked PATH entry points; absolute executable paths remain outside this boundary."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import sys

from ravel.paths import package_data_path


def executables():
    return json.loads(package_data_path('agent_surface', 'hooks.json').read_text())['native_executables']


def render():
    """Portable wrappers resolve local interpreter settings relative to their own path."""
    prefix = ('#!/bin/sh\n'
              'RAVEL_SHIM_PROJECT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)" || exit 2\n'
              '[ -r "$RAVEL_SHIM_PROJECT/.ravel/hook-runtime.sh" ] || { echo "BLOCKED: missing RAVEL runtime" >&2; exit 2; }\n'
              '. "$RAVEL_SHIM_PROJECT/.ravel/hook-runtime.sh"\n')
    return {'.ravel/bin/' + name: prefix + 'exec "${RAVEL_PYTHON:-python3}"'
            ' -m ravel.workflow.native_shims --project "$RAVEL_SHIM_PROJECT"'
            ' --program ' + shlex.quote(name) + ' -- "$@"\n' for name in executables()}


def admit(project, command, *, rundir=None, cwd=None, session=None):
    from . import active_run, execution_guard, gate_wiring, host_gate
    result = execution_guard.decide(command, project, cwd)
    if not result['allowed']:
        return [result['why']]
    rd = Path(rundir) if rundir else active_run.resolve(session or active_run.session_from_env(), cwd or os.getcwd(), project)
    if rd is None:
        return ['native execution requires a registered run and current CHECK-IN 1 approval']
    return host_gate._approval_errors(rd, None) + gate_wiring.launch_errors(rd, None, [], {})


def target(program, project, search_path=None):
    shim_dir = (Path(project) / '.ravel/bin').resolve()
    paths = []
    for entry in (os.environ.get('PATH', '') if search_path is None else search_path).split(os.pathsep):
        folder = Path(entry or os.curdir).resolve()
        if folder != shim_dir:
            paths.append(str(folder))
    found = shutil.which(program, path=os.pathsep.join(paths))
    if not found or Path(found).resolve().parent == shim_dir:
        raise ValueError('native executable unavailable beyond PATH shims: ' + program)
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--program', choices=executables(), required=True)
    parser.add_argument('--rundir', type=Path)
    parser.add_argument('args', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    tail = args.args[1:] if args.args[:1] == ['--'] else args.args
    try:
        command = shlex.join([args.program, *tail])
        errors = admit(args.project, command, rundir=args.rundir)
        if errors:
            raise ValueError('; '.join(errors))
        real = target(args.program, args.project)
    except Exception as exc:
        print('BLOCKED (native execution guard): ' + str(exc), file=sys.stderr)
        return 2
    os.execv(real, [real, *tail])


if __name__ == '__main__':
    raise SystemExit(main())
