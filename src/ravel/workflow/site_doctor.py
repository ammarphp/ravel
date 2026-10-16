"""Readiness checks for an HTCondor analysis facility or other Linux batch site.

``ravel site doctor`` reports whether the pieces a long agent-driven analysis
needs are present: Python 3.12, a grid proxy with enough lifetime, a Kerberos
ticket, write access to an EOS work directory, CVMFS repositories, a batch
scheduler, Node and an agent CLI, plus rucio, apptainer, tmux and XRootD.
With ``--prefix`` it also checks the installed site runtime: the locked workflow
manager and plugins, the recorded LCG view, caches, lease, sandbox and worker transport.
Declare ``--run-hours`` and ``--ticket-lifetime-hours`` for renewal guidance.
Use ``--prefix``, ``--run-root`` and ``--transcript`` with
``--planned-install-gib`` and ``--min-home-free-gib`` to check a storage plan.
``--site-record`` reads the same JSON site block as the batch backend. Named
``analysis-facility`` defaults to Slurm; ``--site-record`` overrides that default,
including scheduler and credential requirements for an HTCondor analysis facility.
It never prints credential contents: it runs ``klist -s`` (exit status only)
and ``voms-proxy-info --timeleft`` (seconds only). The EOS probe writes one small
file in the directory you name and removes it.

``ravel site install-plan`` prints the no-root installation commands: a
Miniforge Python 3.12 in your work space, then the RAVEL site profiles.

``ravel site study-job`` runs one study per Slurm allocation (``allocation_study``).
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys

PROFILES = ('lxplus', 'analysis-facility', 'generic')
PROFILE_SETTINGS = {
    'lxplus': {'scheduler': 'htcondor', 'requires_proxy': True, 'requires_kerberos': True, 'requires_afs': True},
    'analysis-facility': {'scheduler': 'slurm', 'requires_proxy': True, 'requires_kerberos': True, 'requires_afs': False},
    'generic': {'scheduler': None, 'requires_proxy': False, 'requires_kerberos': False, 'requires_afs': False},
}
GIB = 2**30
DEFAULT_CVMFS = ('/cvmfs/sft.cern.ch', '/cvmfs/atlas.cern.ch')
LONG_SESSION = (
    'Long sessions: start the agent inside tmux (tmux new -s ravel; reattach with tmux attach -t ravel). '
    'Use the reported renewal wrapper after obtaining a renewable ticket; its renew-until time must cover '
    'the declared session. Request a proxy covering the run length. Keep environments, outputs and transcripts '
    'in a site work or EOS area with sufficient quota. No login or renewal command is executed by this doctor.')
from .site_contract import PLUGIN, INTERFACE, interface_supported, read_wms_record, versions_script

MANIFEST = Path(__file__).resolve().parents[3] / 'native/setup/toolchain-manifest.json'
MIN_FREE_GB = 4.0


class Host:
    """Real read-only probes, apart from the explicitly requested EOS write probe."""

    def which(self, name):
        return shutil.which(name)

    def run(self, argv):
        try:
            env = dict(os.environ)
            if '/.ravel-site/site-wms/' in str(argv[0]):
                for key in ('PYTHONPATH','PYTHONHOME','PYTHONSTARTUP'):env.pop(key,None)
                env['PYTHONNOUSERSITE']='1'
            proc = subprocess.run(argv, env=env,capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 127, str(exc)
        return proc.returncode, proc.stdout + proc.stderr

    def exists(self, path):
        return Path(path).exists()

    def home(self):
        return Path.home()

    def non_graphical(self):
        return bool(os.environ.get('SSH_CONNECTION') or os.environ.get('SSH_TTY')) or not (
            os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))

    def storage(self, path):
        anchor = Path(path).resolve()
        while not anchor.exists() and anchor != anchor.parent:
            anchor = anchor.parent
        if not anchor.is_dir():
            anchor = anchor.parent
        result = {'free_bytes': shutil.disk_usage(anchor).free, 'quota_remaining_bytes': None,
                  'quota_status': 'unknown', 'anchor': str(anchor)}
        if str(anchor).startswith('/afs/') and self.which('fs'):
            code, out = self.run(['fs', 'listquota', '-path', str(anchor)])
            if code == 0:
                result.update(_afs_quota(out))
        elif self.which('quota'):
            # Linux quota reports KiB blocks by default. Match only this filesystem;
            # unrecognized formats remain unknown rather than assuming unlimited space.
            code, out = self.run(['df', '-P', str(anchor)])
            rows = out.splitlines()
            filesystem = rows[-1].split()[0] if code == 0 and len(rows) >= 2 else None
            code, out = self.run(['quota', '-w', '-v'])
            if code == 0 and filesystem:
                result.update(_unix_quota(out, filesystem))
        return result


def _quota_headroom(used, limits):
    limits = [n for n in limits if n > 0]
    return {'quota_status': 'known' if limits else 'unlimited',
            'quota_remaining_bytes': max(0, min(limits) - used) * 1024 if limits else None}


def _afs_quota(text):
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[1].isdigit() and fields[2].isdigit():
            return _quota_headroom(int(fields[2]), [int(fields[1])])
    return {}


def _unix_quota(text, filesystem):
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[0] == filesystem and all(n.rstrip('*').isdigit() for n in fields[1:4]):
            return _quota_headroom(int(fields[1].rstrip('*')), [int(n.rstrip('*')) for n in fields[2:4]])
    return {}


def _check(name, status, detail, fix=None):
    row = {'id': re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_'), 'name': name, 'status': status, 'detail': detail}
    if fix:
        row['fix'] = fix
    return row


def _tool_version(host, name, flag='--version'):
    if not host.which(name):
        return None
    code, out = host.run([name, flag])
    return (out.strip().splitlines() or [''])[0][:200] if code == 0 else ''


def location_checks(host, *, prefix=None, run_root=None, transcript=None, planned_install_bytes=0,
                    min_home_free_bytes=10 * GIB, work_dir=None, eos_dir=None):
    """Check effective capacity (filesystem free space and quota) without creating paths.

    Zero planned install bytes checks the location floor only; it estimates no
    installation size. Unknown home quota refuses a declared location plan.
    """
    for name, value in [('planned_install_bytes', planned_install_bytes), ('min_home_free_bytes', min_home_free_bytes)]:
        if type(value) is not int or value < 0:
            raise ValueError(f'{name} must be nonnegative integer bytes')
    home = Path(host.home()).expanduser().resolve()
    alternative = str(work_dir or eos_dir or '<site work or EOS area>')
    checks = []
    for name, value in [('home space', home), ('install location', prefix), ('run location', run_root),
                        ('transcript location', transcript)]:
        if value is None:
            continue
        path = Path(value).expanduser().resolve()
        in_home = path.is_relative_to(home)
        planned = name != 'home space'
        minimum = max(planned_install_bytes if name == 'install location' else 0,
                      min_home_free_bytes if in_home else 0)
        try:
            if name in ('install location', 'run location') and path.exists() and not path.is_dir():
                raise ValueError('planned directory is an existing file')
            facts = host.storage(path)
            free = facts['free_bytes']
            quota = facts.get('quota_remaining_bytes')
            known = facts.get('quota_status') in ('known', 'unlimited')
            if (type(free) is not int or free < 0 or
                    (quota is not None and (type(quota) is not int or quota < 0)) or
                    (facts.get('quota_status') == 'known' and quota is None)):
                raise ValueError('invalid storage capacity probe')
            available = min(free, quota) if quota is not None else free
            unsafe = available < minimum or (planned and in_home and not known)
            status = ('fail' if planned else 'warn') if unsafe else ('ok' if known else 'warn')
            detail = (f'{path}: filesystem free {free / GIB:.2f} GiB; quota ' +
                      (f'headroom {quota / GIB:.2f} GiB' if quota is not None else facts.get('quota_status', 'unknown')) +
                      f'; required {minimum / GIB:.2f} GiB' + ('; home area' if in_home else '; outside home'))
            if name == 'install location':
                detail += (f'; planned install {planned_install_bytes / GIB:.2f} GiB' if planned_install_bytes else
                           '; install size not declared (location floor only)')
            row = _check(name, status, detail, f'Use {alternative}; declare and verify quota there' if status != 'ok' else None)
            row.update({'path': str(path), 'home_area': in_home, 'free_bytes': free, 'quota_remaining_bytes': quota,
                        'quota_status': facts.get('quota_status', 'unknown'), 'required_bytes': minimum})
            checks.append(row)
        except (OSError, ValueError) as exc:
            checks.append(_check(name, 'fail' if planned else 'warn', f'{path}: capacity unavailable ({exc})',
                                 f'Use {alternative}; verify filesystem free space and quota'))
    return checks


def _hours(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f'{name} must be finite nonnegative hours')
    return value


def _advertised_flag(help_text, flag):
    return re.search(r'(?<![\w-])' + re.escape(flag) + r'(?![\w-])', help_text) is not None


def _login_checks(host, agents):
    if not host.non_graphical():
        return [_check('agent SSH login', 'skip', 'graphical session; SSH login guidance not required')]
    checks = []
    for agent in agents:
        argv = [agent, 'login', '--help'] if agent == 'codex' else [agent, 'auth', 'login', '--help']
        code, help_text = host.run(argv)
        routes = []
        if code == 0:
            for flag in ('--device-auth', '--device-code'):
                if _advertised_flag(help_text, flag):
                    routes.append(shlex.join(argv[:-1] + [flag]))
            if agent == 'codex' and _advertised_flag(help_text, '--with-api-key'):
                routes.append('printenv OPENAI_API_KEY | codex login --with-api-key')
        if not routes:
            code, help_text = host.run([agent, '--help'])
            variable = 'OPENAI_API_KEY' if agent == 'codex' else 'ANTHROPIC_API_KEY'
            if code == 0 and re.search(r'\b' + variable + r'\b', help_text):
                routes.append(f'Set {variable} through secure external configuration, then start {agent}; no key is read here')
        checks.append(_check(f'{agent} SSH login', 'ok' if routes else 'warn',
                             'non-graphical session; route advertised by login --help' if routes else
                             'non-graphical session; no supported device/API-key route found in login --help',
                             ' OR '.join(routes) if routes else 'Consult the installed CLI login help on a graphical host'))
    if not agents:
        checks.append(_check('agent SSH login', 'warn', 'non-graphical session; no agent CLI available'))
    return checks


def site_disk_gb():
    from ravel.setup.manifest import view
    # The main file is read with its group fragments.
    return float(view(_manifest_path().parents[2])['profiles']['site']['disk_gb'])


def _manifest_path():
    if MANIFEST.is_file():return MANIFEST
    from ravel.setup.manifest import manifest_path
    return manifest_path()


def _existing_parent(path, host):
    path = Path(path).absolute()
    while not host.exists(str(path)) and path != path.parent:
        path = path.parent
    return str(path)


def _blocks(value):
    match = re.fullmatch(r'(\d+(?:\.\d+)?)([KMGT]?)\*?', value, re.I)
    if not match:
        return None
    return float(match[1]) * (1024 ** ('KMGT'.index(match[2].upper()) + 1) if match[2] else 1024)


def _quota_free(output, *, afs=False, filesystem=None):
    """Parse AFS KiB quota/used or quota -s space/soft/hard rows."""
    candidates = []
    current_filesystem = None
    for line in output.splitlines():
        fields = line.split()
        if not fields:
            continue
        if _blocks(fields[0]) is None:
            current_filesystem=fields[0]
            values=fields[1:]
        else:values=fields
        if not afs and filesystem is not None and current_filesystem != filesystem:continue
        if afs and len(values) >= 2:
            limit, used = _blocks(values[0]), _blocks(values[1])
            if limit is not None and used is not None and limit > 0:
                candidates.append(max(0, limit - used))
        elif len(values) >= 3:
            used, soft, hard = (_blocks(x) for x in values[:3])
            if used is not None and soft is not None and hard is not None:
                limits = [x for x in (soft, hard) if x > 0]
                if limits:
                    candidates.append(max(0, min(limits) - used))
    return min(candidates) if candidates else None


def location_check(name, path, *, host, threshold_gb, home=None):
    """Read quota and df through Host without writing to the inspected location."""
    if not math.isfinite(threshold_gb) or threshold_gb <= 0:raise ValueError('free-space threshold must be finite and positive')
    path = Path(path).absolute()
    home = Path(home or os.environ.get('HOME') or Path.home()).resolve()
    in_home = path.resolve().is_relative_to(home)
    probe_path = _existing_parent(path, host)
    afs = path.as_posix().startswith('/afs/')
    argv = ['fs', 'listquota', '-path', probe_path] if afs else ['quota', '-s']
    quota_code, quota_output = host.run(argv) if host.which(argv[0]) else (127, '')
    code, output = host.run(['df', '-Pk', probe_path])
    free = None
    filesystem = None
    if code == 0:
        for line in reversed(output.splitlines()):
            fields = line.split()
            if len(fields) >= 6 and fields[-3].isdigit():
                free = int(fields[-3]) * 1024
                filesystem=fields[0]
                break
    quota = _quota_free(quota_output,afs=afs,filesystem=filesystem) if quota_code == 0 else None
    available = [v for v in (free, quota) if v is not None]
    threshold = threshold_gb * 1024 ** 3
    low = bool(available) and min(available) < threshold
    missing = free is None or (in_home and quota is None)
    status = 'fail' if low or missing else 'ok'
    detail = (f'{path}; {"home area" if in_home else "work area"}; '
              f'free space {free / 1024 ** 3:.2f} GiB' if free is not None else f'{path}; free space unknown')
    detail += f'; quota free {quota / 1024 ** 3:.2f} GiB' if quota is not None else '; quota unknown'
    detail += f'; required {threshold_gb:g} GiB'
    row = _check(name + ' location', status, detail,
                 'Choose a work area with enough free space and quota; pass --prefix, --runs-dir and --transcripts-dir there'
                 if status == 'fail' else None)
    row.update(path=str(path), home_area=in_home, free_bytes=free, quota_free_bytes=quota, threshold_gb=threshold_gb)
    return row


def _lease_domain():
    """Use only the public lease-domain API; legacy domain() is not a location policy."""
    from . import machine_lease
    reader = getattr(machine_lease, 'lease_domain', None)
    return reader() if reader is not None else None


def _agent_cli_readiness(host, prefix):
    """Reuse setup's stored-probe helper; never launch a probe or qualification."""
    from ravel.setup.doctor import Doctor
    adapter = object.__new__(Doctor)
    adapter.which = host.which
    adapter._probe = lambda argv, **kwargs: host.run(argv)
    return adapter._agent_cli_check({'id':'site-worker-transport'})


def _lease_checks(host):
    domain = _lease_domain()
    if not isinstance(domain, dict):
        rows=[_check('lease domain', 'warn', 'Public lease_domain API is not installed',
                     'Install the release that provides the lease policy API'),
              _check('lease filesystem','skip','Lease location API is pending')]
        if host.which('condor_submit') or host.which('condor_q'):
            rows.append(_check('batch lease policy','warn','No batch-slot policy is available through the public API',
                               'ravel lease policy set --scope host --batch-slot-dir-env _CONDOR_SCRATCH_DIR --reason <text> --operator <name>'))
        return rows
    path = domain.get('path')
    mode = domain.get('lock_mode', domain.get('mode'))
    checks = [_check('lease domain', 'ok' if path and mode else 'warn',
                     f"path {path}; scope {domain.get('scope')}; lock mode {mode}; reason {domain.get('reason')}")]
    code, output = host.run(['df','-PT',_existing_parent(path,host)]) if path else (127,'')
    fs = next((row.split()[1] for row in output.splitlines()[1:] if len(row.split()) >= 7), None) if code == 0 else None
    network = fs in ('afs','nfs','nfs4','cifs','lustre','gpfs','fuse.eos','eos')
    checks.append(_check('lease filesystem','warn' if mode == 'local' and network or fs is None else 'ok',
                         f'{fs or "unknown filesystem"}; lock mode {mode}',
                         'Use a local lease directory or configure the facility lock policy' if mode == 'local' and network else None))
    policy = domain.get('policy')
    # Consume a public slots() response when the lease stream publishes it.
    if policy is None:
        from . import machine_lease
        slots = getattr(machine_lease, 'slots', None)
        policy = slots() if slots is not None else None
    batch = isinstance(policy, dict) and bool(policy.get('batch_slot_dir_env') or policy.get('batch-slot-dir-env') or policy.get('batch'))
    if host.which('condor_submit') or host.which('condor_q'):
        checks.append(_check('batch lease policy','ok' if batch else 'warn',
                             'batch-slot entry recorded' if batch else 'No batch-slot lease policy recorded for HTCondor',
                             None if batch else 'ravel lease policy set --scope host --batch-slot-dir-env _CONDOR_SCRATCH_DIR '
                             '--reason <text> --operator <name>'))
    return checks


def installation_checks(prefix, *, host=None, environ=None):
    """Read the installed WMS and view records and inspect their isolated runtime."""
    host = host or Host()
    environ = os.environ if environ is None else environ
    prefix = Path(prefix).absolute()
    fix = 'Install this release into a work prefix: bash scripts/setup/install.sh --profile site --prefix <work-prefix> --lcg-view <view-path-or-none>'
    checks = []
    try:
        record = read_wms_record(prefix)
        checks.append(_check('site wms record','ok',f"release {record['release']}; lock sha256 {record['lock_sha256']}"))
        argv = [str(prefix/'.ravel-site/site-wms/bin/python'),'-I','-B','-c',versions_script(record['packages'])]
        code, output = host.run(argv)
        installed = json.loads(output) if code == 0 else {}
        if not isinstance(installed,dict):installed={}
        code, version = host.run([record['shim'],'--version'])
        snake_ok = code == 0 and version.strip() == record['version'] and installed.get('snakemake') == record['version']
        checks.append(_check('site snakemake','ok' if snake_ok else 'fail',
                             f"expected {record['version']}; found {installed.get('snakemake')}; executable {version.strip()[:100]}",None if snake_ok else fix))
        plugin_ok = all(installed.get(name) == version for name,version in record['plugins'].items())
        checks.append(_check('site executor plugin','ok' if plugin_ok else 'fail',
                             f"locked plugins {record['plugins']}; found {installed.get(PLUGIN)}",None if plugin_ok else fix))
        interface = installed.get(INTERFACE)
        supported = interface_supported(interface) and interface == record['packages'][INTERFACE]
        checks.append(_check('site executor interface','ok' if supported else 'fail',
                             f'{interface}; required locked version and >=9.3.2,<10',None if supported else fix))
    except (ValueError,OSError,KeyError,TypeError) as error:
        checks.append(_check('site wms record','fail',str(error),fix))
    try:
        view = json.loads((prefix/'.ravel-site/lcg-view.json').read_text())
        valid = view.get('schema_version') == 1 and (
            view.get('choice') == 'none' and view.get('path') is None or
            isinstance(view.get('path'),str) and Path(view['path']).is_absolute() and host.exists(str(Path(view['path'])/'setup.sh')))
        checks.append(_check('lcg view','ok' if valid else 'fail',str(view.get('path') or view.get('choice')),None if valid else 'Restore the recorded LCG view or start a new campaign in a new prefix'))
    except (OSError,ValueError,AttributeError,TypeError) as error:
        checks.append(_check('lcg view','fail','Missing or invalid explicit view record: '+str(error),fix))
    for name, key, relative in (('apptainer cache','APPTAINER_CACHEDIR','cache/apptainer'),
                                ('apptainer temporary','APPTAINER_TMPDIR','tmp/apptainer')):
        path = Path(environ.get(key) or prefix/relative).absolute()
        ok = path.resolve().is_relative_to(prefix.resolve())
        checks.append(_check(name,'ok' if ok else 'fail',str(path),None if ok else 'Source '+str(prefix/'config/ravel-env.sh')))
    calling = bool(environ.get('PYTHONPATH'))
    checks.append(_check('calling pythonpath','warn' if calling else 'ok',
                         'PYTHONPATH is set in the calling shell' if calling else 'PYTHONPATH is unset',
                         'Run '+str(prefix/'bin/ravel-snakemake') if calling else None))
    return checks


def _console_checks(prefix, host):
    """Profile console scripts declared by this release must use the site-analysis interpreter."""
    checks = []
    python = str(Path(prefix)/'.ravel-site/site-analysis/bin/python')
    declared=_profile_console_scripts()
    for name in ('ravel-wms-condor-submit','ravel-wms-condor-status'):
        script = host.which(name)
        if script is None:
            required=name in declared
            checks.append(_check(name,'fail' if required else 'skip',
                                 'Required profile console script is missing' if required else 'Profile console script is not installed in this release',
                                 'Put '+str(Path(prefix)/'.ravel-site/site-analysis/bin')+' on PATH' if required else None))
            continue
        try:
            first = Path(script).read_text().splitlines()[0]
            ok = first == '#!'+python or first == '#!'+python+'3.12'
        except (OSError,IndexError):
            ok = False
        checks.append(_check(name,'ok' if ok else 'fail',str(script),None if ok else
                             'Use the profile console scripts installed by '+python))
    return checks


def _profile_console_scripts():
    from ravel.paths import repository_root
    import tomllib
    root=repository_root()
    if root is not None:
        return set(tomllib.loads((root/'pyproject.toml').read_text())['project'].get('scripts',{}))
    import importlib.metadata
    return {point.name for point in importlib.metadata.entry_points(group='console_scripts')}


def runtime_checks(prefix, *, host, environ=None):
    """Installed site checks shared with the toolchain manifest's doctor."""
    checks=installation_checks(prefix,host=host,environ=environ)
    checks.extend(_lease_checks(host))
    checks.extend(_console_checks(prefix,host))
    bwrap=host.which('bwrap')
    checks.append(_check('worker sandbox','ok' if bwrap else 'fail',bwrap or 'bwrap is missing',
                         None if bwrap else 'Install bubblewrap (bwrap) on the Linux worker host'))
    agent=_agent_cli_readiness(host,prefix)
    qualified=agent.get('transport_qualified') is True
    transport=agent.get('transport') or 'claude-cli-worker'
    checks.append(_check('worker transport','ok' if qualified else 'fail',agent.get('detail') or agent['status'],
                         None if qualified else agent.get('fix') or 'ravel transport qualify '+transport))
    return checks


def doctor(*, profile='lxplus', eos_dir=None, min_proxy_hours=2.0, cvmfs=DEFAULT_CVMFS, host=None,
           site_record=None, run_hours=0, ticket_lifetime_hours=None, prefix=None, run_root=None, transcript=None,
           planned_install_bytes=0, min_home_free_bytes=10 * GIB, work_dir=None,
           runs_dir=None, transcripts_dir=None, min_free_gb=MIN_FREE_GB):
    if profile not in PROFILES:
        raise ValueError(f'profile must be one of {PROFILES}')
    host = host or Host()
    settings = dict(PROFILE_SETTINGS[profile])
    if site_record is not None:
        if not isinstance(site_record, dict):
            raise ValueError('site_record must be an object')
        for key in ('requires_proxy', 'requires_kerberos', 'requires_afs'):
            if key in site_record:
                if type(site_record[key]) is not bool:
                    raise ValueError(f'{key} must be boolean')
                settings[key] = site_record[key]
        if 'scheduler' in site_record:
            if site_record['scheduler'] not in ('htcondor', 'slurm'):
                raise ValueError('site scheduler must be htcondor or slurm')
            settings['scheduler'] = site_record['scheduler']
    if settings['requires_afs'] and not settings['requires_kerberos']:
        raise ValueError('AFS renewal requires Kerberos')
    run_hours = _hours(run_hours, 'run_hours')
    min_proxy_hours = _hours(min_proxy_hours, 'min_proxy_hours')
    if ticket_lifetime_hours is not None:
        _hours(ticket_lifetime_hours, 'ticket_lifetime_hours')
    required = 'fail'
    optional = 'warn'
    if not math.isfinite(min_free_gb) or min_free_gb <= 0:raise ValueError('min-free-gb must be finite and positive')
    checks = location_checks(host, prefix=prefix, run_root=run_root, transcript=transcript,
                             planned_install_bytes=planned_install_bytes, min_home_free_bytes=min_home_free_bytes,
                             work_dir=work_dir, eos_dir=eos_dir)
    # The installed site runtime and its locations; without --prefix the declared site or native build.
    if prefix is None:
        from ravel.paths import native_build_root
        prefix = os.environ.get('RAVEL_SITE_PREFIX') or os.environ.get('RAVEL_NATIVE_BUILD') or native_build_root()
    prefix=Path(prefix).absolute()
    checks.extend(runtime_checks(prefix,host=host))
    for name,path,threshold in (('prefix',prefix,max(site_disk_gb(),min_free_gb)),
                                ('runs',runs_dir or prefix/'runs',min_free_gb),
                                ('transcripts',transcripts_dir or prefix/'transcripts',min_free_gb)):
        checks.append(location_check(name,path,host=host,threshold_gb=threshold))

    version = _tool_version(host, 'python3.12')
    checks.append(_check('python 3.12', 'ok' if version else required, version or 'python3.12 not on PATH',
                         None if version else 'Install Miniforge in your work space (no root): ravel site install-plan'))

    if settings['requires_proxy']:
        proxy_args = []
        proxy_ok = True
        if site_record and 'proxy_path' in site_record:
            from ravel.workflow.backends.site_batch import validate_proxy_path
            try:
                proxy_args = ['--file', validate_proxy_path(site_record['proxy_path'])]
            except ValueError as exc:
                proxy_ok = False
                checks.append(_check('grid proxy path', required, str(exc)))
        if host.which('voms-proxy-info'):
            code, out = host.run(['voms-proxy-info', *proxy_args, '--timeleft']) if proxy_ok else (1, '')
            try:
                seconds = int(out.strip().split()[0]) if code == 0 else 0
            except (ValueError, IndexError):
                seconds = 0
            hours = max(min_proxy_hours, run_hours)
            ok = code == 0 and seconds > 0 and seconds >= hours * 3600
            checks.append(_check('grid proxy', 'ok' if ok else required,
                                 f'{seconds / 3600:.1f} h left; required {hours:g} h' if code == 0 else 'no valid proxy',
                                 None if ok else f'voms-proxy-init --voms <vo> --valid {math.ceil(hours)}:00'))
        else:
            checks.append(_check('grid proxy', required, 'voms-proxy-info not found', 'Set up the grid client (for example via CVMFS)'))
    else:
        checks.append(_check('grid proxy', 'skip', f'not required by the {profile} profile'))
    if settings['requires_kerberos']:
        if host.which('klist'):
            code, _ = host.run(['klist', '-s'])
            checks.append(_check('kerberos', 'ok' if code == 0 else required,
                                 'valid ticket' if code == 0 else 'no valid ticket', None if code == 0 else 'kinit'))
        else:
            checks.append(_check('kerberos', required, 'klist not found', 'Install the Kerberos client'))
        renew = host.which('krenew')
        afs = settings['requires_afs']
        renewal_ready = bool(renew and (not afs or host.which('aklog')))
        required_renewal = run_hours > 0 and (ticket_lifetime_hours is None or run_hours > ticket_lifetime_hours)
        interval = max(1, min(60, int(ticket_lifetime_hours * 30))) if ticket_lifetime_hours is not None else 60
        renewal_command = f'krenew -K {interval}' + (' -t' if afs else '') + ' -- sh'
        # Renewal belongs inside the persistent tmux session; wrapping the tmux
        # client would stop renewing when that client detaches on SSH disconnect.
        wrapper_command = ('tmux new-session -s ravel ' + shlex.quote(renewal_command)
                           if host.which('tmux') else renewal_command)
        detail = ('renewal wrapper available' if renewal_ready else 'krenew' + ('/aklog' if afs else '') + ' not available')
        detail += ('; ticket lifetime not declared' if ticket_lifetime_hours is None else
                   f'; declared ticket lifetime {ticket_lifetime_hours:g} h; run {run_hours:g} h')
        renewal_status = ('warn' if run_hours and ticket_lifetime_hours is None else 'ok') if renewal_ready else (
            required if required_renewal else optional)
        checks.append(_check('ticket renewal', renewal_status, detail,
                             wrapper_command + '; first obtain a renewable ticket whose renew-until time covers the run' if renew else
                             'Install krenew' + (' and aklog for AFS renewal' if afs else '') + ' in the site environment'))
        if afs:
            checks.append(_check('AFS renewal', 'ok' if renewal_ready else (required if required_renewal else optional),
                                 'krenew -t refreshes tokens using aklog; no token contents inspected' if renewal_ready else
                                 'AFS renewal requires both krenew and aklog', wrapper_command if renewal_ready else 'Load krenew and aklog'))
    else:
        checks.append(_check('kerberos', 'skip', f'not required by the {profile} profile'))

    if eos_dir is not None:
        checks.append(_eos_probe(Path(eos_dir)))
    else:
        checks.append(_check('eos write', 'skip', 'pass --eos-dir to test write access'))

    for repo in (cvmfs if profile != 'generic' else ()):
        present = host.exists(repo)
        checks.append(_check(f'cvmfs {repo}', 'ok' if present else required, 'mounted' if present else 'not mounted',
                             None if present else 'Run on a node with CVMFS mounted'))

    scheduler = settings['scheduler']
    if scheduler in (None, 'htcondor') and host.which('condor_q'):
        code, _ = host.run(['condor_q', '-totals'])
        checks.append(_check('batch scheduler', 'ok' if code == 0 else required,
                             'HTCondor schedd reachable' if code == 0 else 'condor_q failed', None if code == 0 else 'Check HTCondor access'))
    elif scheduler in (None, 'slurm') and host.which('sbatch') and host.which('squeue'):
        code, _ = host.run(['squeue', '-h'])
        checks.append(_check('batch scheduler', 'ok' if code == 0 else required,
                             'SLURM scheduler reachable' if code == 0 else 'squeue failed'))
    else:
        checks.append(_check('batch scheduler', required if scheduler else optional, f'no {scheduler or "HTCondor or SLURM"} client',
                             'Run on a submit node'))

    pdfinfo = host.which('pdfinfo')
    checks.append(_check('pdfinfo', 'ok' if pdfinfo else optional, 'available' if pdfinfo else 'pdfinfo not found',
                         None if pdfinfo else 'Install Poppler in your work area for PDF page counts'))
    node = _tool_version(host, 'node')
    major = int(node.lstrip('v').split('.')[0]) if node and node.lstrip('v').split('.')[0].isdigit() else 0
    checks.append(_check('node', 'ok' if major >= 18 else optional, node or 'node not found',
                         None if major >= 18 else 'Install Node 18 or newer in user space (conda install nodejs)'))
    agents = [n for n in ('claude', 'codex') if host.which(n)]
    checks.append(_check('agent CLI', 'ok' if agents else optional, ', '.join(agents) or 'neither claude nor codex found',
                         None if agents else 'npm install -g @anthropic-ai/claude-code (or the Codex CLI) with a user prefix'))
    checks.extend(_login_checks(host, agents))
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


def install_plan(env_prefix, checkout, *, arch=None, host=None, planned_install_bytes=0,
                 min_home_free_bytes=10 * GIB, work_dir=None):
    """No-root Python 3.12 installation in work space, then the RAVEL site profiles."""
    arch = arch or ('aarch64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x86_64')
    checks = location_checks(host or Host(), prefix=env_prefix, planned_install_bytes=planned_install_bytes,
                             min_home_free_bytes=min_home_free_bytes, work_dir=work_dir)
    refusal = [row for row in checks if row['name'] == 'install location' and row['status'] == 'fail']
    if refusal:
        raise ValueError(refusal[0]['detail'] + '; ' + refusal[0]['fix'])
    env_prefix, checkout = str(Path(env_prefix).expanduser().resolve()), str(Path(checkout).expanduser().resolve())
    from ravel.setup.manifest import view
    manifest = view(_manifest_path().parents[2])['miniforge']
    if arch not in ('x86_64','aarch64'):raise ValueError('Supported Linux architectures: x86_64, aarch64')
    asset = manifest['assets']['linux-'+arch]
    url = manifest['url'].format(asset=asset['name'])
    p=shlex.quote(env_prefix)
    checkout_arg=shlex.quote(checkout)
    commands = [
        f'mkdir -p {p}/downloads && curl -L -o {p}/downloads/Miniforge3.sh {url}',
        f"printf '%s  %s\\n' {asset['sha256']} {p}/downloads/Miniforge3.sh | sha256sum -c -",
        f'export APPTAINER_CACHEDIR={p}/cache/apptainer APPTAINER_TMPDIR={p}/tmp/apptainer TMPDIR={p}/tmp CONDA_PKGS_DIRS={p}/pkgs CONDA_REGISTER_ENVS=false PIP_CACHE_DIR={p}/cache/pip XDG_CACHE_HOME={p}/cache',
        f'mkdir -p {p}/cache/apptainer {p}/tmp/apptainer',
        f'bash {p}/downloads/Miniforge3.sh -b -p {p}/miniforge',
        f'{p}/miniforge/bin/conda create -y -p {p}/py312 python=3.12 nodejs',
        f'export PATH={p}/py312/bin:$PATH',
        f'cd {checkout_arg} && bash scripts/setup/install.sh --profile site --prefix {p} --plan',
        f'cd {checkout_arg} && bash scripts/setup/install.sh --profile site --prefix {p} --lcg-view none',
        f'ravel site doctor --profile lxplus --prefix {p} --runs-dir {p}/runs --transcripts-dir {p}/transcripts',
    ]
    return {'root_required': False, 'env_prefix': env_prefix, 'checkout': checkout, 'commands': commands,
            'checks': checks,
            'note': 'Review the Miniforge download before running it; nothing here changes global shell configuration.'}


def main(argv=None):
    ap = argparse.ArgumentParser(prog='ravel site', description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='command', required=True)
    d = sub.add_parser('doctor', help='check site readiness without printing credentials')
    d.add_argument('--profile', choices=PROFILES, default='lxplus')
    d.add_argument('--eos-dir', type=Path)
    d.add_argument('--min-proxy-hours', type=float, default=2.0)
    d.add_argument('--run-hours', type=float, default=0, help='declared duration of the agent run')
    d.add_argument('--ticket-lifetime-hours', type=float, help='declared ticket lifetime; no ticket contents read')
    d.add_argument('--site-record', type=Path, help='JSON site record shared with batch/profile configuration')
    d.add_argument('--prefix', type=Path, help='site installation prefix: its planned capacity and, once installed, its runtime')
    d.add_argument('--runs-dir', type=Path)
    d.add_argument('--transcripts-dir', type=Path)
    d.add_argument('--min-free-gb', type=float, default=MIN_FREE_GB,
                   help='minimum free GiB for runs and transcripts; prefix also needs the install size')
    d.add_argument('--run-root', type=Path, help='planned run-directory root')
    d.add_argument('--transcript', type=Path, help='planned transcript file or directory')
    d.add_argument('--planned-install-gib', type=float, default=0)
    d.add_argument('--min-home-free-gib', type=float, default=10)
    d.add_argument('--work-dir', type=Path, help='suggested alternative to home storage')
    d.add_argument('--cvmfs', action='append', help='CVMFS repository path to require (repeatable)')
    d.add_argument('--json', action='store_true')
    p = sub.add_parser('install-plan', help='print no-root installation commands for a Linux site')
    p.add_argument('--env-prefix', '--prefix', dest='env_prefix', required=True, help='work-space directory for Miniforge and Python 3.12')
    p.add_argument('--checkout', required=True, help='RAVEL checkout on the site')
    p.add_argument('--planned-install-gib', type=float, default=0)
    p.add_argument('--min-home-free-gib', type=float, default=10)
    p.add_argument('--work-dir', type=Path)
    from . import allocation_study
    allocation_study.add_parser(sub)
    args = ap.parse_args(argv)
    try:
        if args.command == 'study-job':
            return allocation_study.main_args(args)
        storage_args = {'planned_install_bytes': int(_hours(args.planned_install_gib, 'planned_install_gib') * GIB),
                        'min_home_free_bytes': int(_hours(args.min_home_free_gib, 'min_home_free_gib') * GIB),
                        'work_dir': args.work_dir}
        if args.command == 'install-plan':
            plan = install_plan(args.env_prefix, args.checkout, **storage_args)
            print('\n'.join(plan['commands']))
            return 0
        report = doctor(profile=args.profile, eos_dir=args.eos_dir, min_proxy_hours=args.min_proxy_hours,
                        cvmfs=tuple(args.cvmfs) if args.cvmfs else DEFAULT_CVMFS, host=Host(),
                        site_record=json.loads(args.site_record.read_text()) if args.site_record else None,
                        run_hours=args.run_hours, ticket_lifetime_hours=args.ticket_lifetime_hours,
                        prefix=args.prefix, run_root=args.run_root, transcript=args.transcript,
                        runs_dir=args.runs_dir, transcripts_dir=args.transcripts_dir, min_free_gb=args.min_free_gb,
                        **storage_args)
    except (OSError, ValueError, OverflowError) as exc:
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
