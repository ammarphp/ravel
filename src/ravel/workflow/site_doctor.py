"""Readiness checks for a Linux analysis site (for example lxplus or an analysis facility).

``ravel site doctor`` reports whether the pieces a long agent-driven analysis
needs are present: Python 3.12, a grid proxy with enough lifetime, a Kerberos
ticket, write access to an EOS work directory, CVMFS repositories, a batch
scheduler, TeX, Node and an agent CLI, plus rucio, apptainer, tmux and XRootD.
It never prints credential contents: it runs ``klist -s`` (exit status only)
and ``voms-proxy-info --timeleft`` (seconds only). The EOS probe writes one small
file in the directory you name and removes it.

``ravel site install-plan`` prints the no-root installation commands: a
Miniforge Python 3.12 in your work space, then the RAVEL site profiles.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

PROFILES = ('lxplus', 'generic')
DEFAULT_CVMFS = ('/cvmfs/sft.cern.ch', '/cvmfs/atlas.cern.ch')
LONG_SESSION = (
    'Long sessions: start the agent inside tmux (tmux new -s ravel; reattach with tmux attach -t ravel). '
    'Renew Kerberos in the background with krenew -b -K 60 (or k5reauth) after kinit, and create a '
    'long proxy with voms-proxy-init --voms <vo> --valid 96:00. Keep outputs and the RAVEL checkout on '
    'EOS or AFS work space, not in /tmp.')
MINIFORGE_URL = 'https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-{arch}.sh'


class Host:
    """Real probes. Tests substitute an object with the same three methods."""

    def which(self, name):
        return shutil.which(name)

    def run(self, argv):
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 127, str(exc)
        return proc.returncode, proc.stdout + proc.stderr

    def exists(self, path):
        return Path(path).exists()


def _check(name, status, detail, fix=None):
    row = {'name': name, 'status': status, 'detail': detail}
    if fix:
        row['fix'] = fix
    return row


def _tool_version(host, name, flag='--version'):
    if not host.which(name):
        return None
    code, out = host.run([name, flag])
    return (out.strip().splitlines() or [''])[0][:200] if code == 0 else ''


def doctor(*, profile='lxplus', eos_dir=None, min_proxy_hours=2.0, cvmfs=DEFAULT_CVMFS, host=None):
    if profile not in PROFILES:
        raise ValueError(f'profile must be one of {PROFILES}')
    host = host or Host()
    cern = profile == 'lxplus'
    required = 'fail'
    optional = 'warn'
    checks = []

    version = _tool_version(host, 'python3.12')
    checks.append(_check('python 3.12', 'ok' if version else required, version or 'python3.12 not on PATH',
                         None if version else 'Install Miniforge in your work space (no root): ravel site install-plan'))

    if cern:
        if host.which('voms-proxy-info'):
            code, out = host.run(['voms-proxy-info', '--timeleft'])
            try:
                seconds = int(out.strip().split()[0]) if code == 0 else 0
            except (ValueError, IndexError):
                seconds = 0
            ok = seconds >= min_proxy_hours * 3600
            checks.append(_check('grid proxy', 'ok' if ok else required,
                                 f'{seconds / 3600:.1f} h left' if code == 0 else 'no valid proxy',
                                 None if ok else 'voms-proxy-init --voms <vo> --valid 96:00'))
        else:
            checks.append(_check('grid proxy', required, 'voms-proxy-info not found', 'Set up the grid client (for example via CVMFS)'))
        if host.which('klist'):
            code, _ = host.run(['klist', '-s'])
            checks.append(_check('kerberos', 'ok' if code == 0 else required,
                                 'valid ticket' if code == 0 else 'no valid ticket', None if code == 0 else 'kinit'))
        else:
            checks.append(_check('kerberos', required, 'klist not found', 'Install the Kerberos client'))
        renew = host.which('krenew') or host.which('k5reauth')
        checks.append(_check('ticket renewal', 'ok' if renew else optional, 'available' if renew else 'krenew/k5reauth not found',
                             None if renew else 'Use krenew or k5reauth for sessions longer than the ticket lifetime'))
    else:
        checks.append(_check('grid proxy', 'skip', 'not required by the generic profile'))
        checks.append(_check('kerberos', 'skip', 'not required by the generic profile'))

    if eos_dir is not None:
        checks.append(_eos_probe(Path(eos_dir)))
    else:
        checks.append(_check('eos write', 'skip', 'pass --eos-dir to test write access'))

    for repo in (cvmfs if cern else ()):
        present = host.exists(repo)
        checks.append(_check(f'cvmfs {repo}', 'ok' if present else required, 'mounted' if present else 'not mounted',
                             None if present else 'Run on a node with CVMFS mounted'))

    if host.which('condor_q'):
        code, _ = host.run(['condor_q', '-totals'])
        checks.append(_check('batch scheduler', 'ok' if code == 0 else required,
                             'HTCondor schedd reachable' if code == 0 else 'condor_q failed', None if code == 0 else 'Check HTCondor access'))
    elif host.which('sbatch') and host.which('squeue'):
        checks.append(_check('batch scheduler', 'ok', 'SLURM client available'))
    else:
        checks.append(_check('batch scheduler', required if cern else optional, 'no HTCondor or SLURM client',
                             'Run on a submit node'))

    tex = _tool_version(host, 'pdflatex') or _tool_version(host, 'latex')
    checks.append(_check('TeX', 'ok' if tex else optional, tex or 'pdflatex not found',
                         None if tex else 'Load TeX Live from CVMFS or install it in your work space'))
    node = _tool_version(host, 'node')
    major = int(node.lstrip('v').split('.')[0]) if node and node.lstrip('v').split('.')[0].isdigit() else 0
    checks.append(_check('node', 'ok' if major >= 18 else optional, node or 'node not found',
                         None if major >= 18 else 'Install Node 18 or newer in user space (conda install nodejs)'))
    agents = [n for n in ('claude', 'codex') if host.which(n)]
    checks.append(_check('agent CLI', 'ok' if agents else optional, ', '.join(agents) or 'neither claude nor codex found',
                         None if agents else 'npm install -g @anthropic-ai/claude-code (or the Codex CLI) with a user prefix'))
    for name, tool in (('rucio', 'rucio'), ('apptainer', 'apptainer'), ('xrootd', 'xrdcp')):
        found = _tool_version(host, tool)
        if tool == 'apptainer' and not found:
            found = _tool_version(host, 'singularity')
        checks.append(_check(name, 'ok' if found else optional, found or f'{tool} not found'))
    tmux = host.which('tmux')
    checks.append(_check('tmux', 'ok' if tmux else optional, 'available' if tmux else 'tmux not found'))

    ready = not any(c['status'] == 'fail' for c in checks)
    return {'profile': profile, 'platform': f'{platform.system()} {platform.machine()}', 'ready': ready,
            'checks': checks, 'long_session': LONG_SESSION}


def _eos_probe(directory):
    probe = directory / f'.ravel-site-doctor-{os.getpid()}'
    try:
        if not directory.is_dir():
            raise OSError(f'{directory} is not a directory')
        probe.write_bytes(b'ravel site doctor probe\n')
        ok = probe.read_bytes() == b'ravel site doctor probe\n'
        probe.unlink()
        return _check('eos write', 'ok' if ok else 'fail', f'wrote and removed a probe in {directory}')
    except OSError as exc:
        try:
            if probe.exists():
                probe.unlink()
        except OSError:
            pass
        return _check('eos write', 'fail', str(exc), 'Check the EOS path, quota and Kerberos ticket')


def install_plan(env_prefix, checkout, *, arch=None):
    """No-root Python 3.12 installation in work space, then the RAVEL site profiles."""
    arch = arch or ('aarch64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x86_64')
    env_prefix, checkout = str(env_prefix), str(checkout)
    url = MINIFORGE_URL.format(arch=arch)
    commands = [
        f'curl -L -o Miniforge3.sh {url}',
        f'bash Miniforge3.sh -b -p {env_prefix}/miniforge',
        f'{env_prefix}/miniforge/bin/conda create -y -p {env_prefix}/py312 python=3.12 nodejs',
        f'export PATH={env_prefix}/py312/bin:$PATH',
        f'cd {checkout} && python3.12 scripts/setup/site_installation.py --plan',
        f'cd {checkout} && python3.12 scripts/setup/site_installation.py --install',
        'ravel site doctor --profile lxplus --eos-dir <your EOS work directory>',
    ]
    return {'root_required': False, 'env_prefix': env_prefix, 'checkout': checkout, 'commands': commands,
            'note': 'Review the Miniforge download before running it; nothing here changes global shell configuration.'}


def main(argv=None):
    ap = argparse.ArgumentParser(prog='ravel site', description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='command', required=True)
    d = sub.add_parser('doctor', help='check site readiness without printing credentials')
    d.add_argument('--profile', choices=PROFILES, default='lxplus')
    d.add_argument('--eos-dir', type=Path)
    d.add_argument('--min-proxy-hours', type=float, default=2.0)
    d.add_argument('--cvmfs', action='append', help='CVMFS repository path to require (repeatable)')
    d.add_argument('--json', action='store_true')
    p = sub.add_parser('install-plan', help='print no-root installation commands for a Linux site')
    p.add_argument('--env-prefix', required=True, help='work-space directory for Miniforge and Python 3.12')
    p.add_argument('--checkout', required=True, help='RAVEL checkout on the site')
    args = ap.parse_args(argv)
    try:
        if args.command == 'install-plan':
            plan = install_plan(args.env_prefix, args.checkout)
            print('\n'.join(plan['commands']))
            return 0
        report = doctor(profile=args.profile, eos_dir=args.eos_dir, min_proxy_hours=args.min_proxy_hours,
                        cvmfs=tuple(args.cvmfs) if args.cvmfs else DEFAULT_CVMFS, host=Host())
    except (OSError, ValueError) as exc:
        print(f'ravel site: {exc}', file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for row in report['checks']:
            print(f"{row['status']:>4}  {row['name']}: {row['detail']}" + (f"  -> {row['fix']}" if 'fix' in row else ''))
        print('\n' + report['long_session'])
    return 0 if report['ready'] else 1


if __name__ == '__main__':
    sys.exit(main())
