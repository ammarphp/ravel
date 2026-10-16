"""Site doctor with mocked environment probes."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ravel.workflow import site_doctor as sd
import pytest
from site_install_fixture import VERSIONS
from test_site_doctor_contract import installed


@pytest.fixture(autouse=True)
def site_records(tmp_path_factory,monkeypatch):
    # The installed site prefix lives outside each test's own tmp_path, which tests inspect.
    prefix,_=installed(tmp_path_factory.mktemp('site-install'),monkeypatch)
    monkeypatch.setenv('RAVEL_NATIVE_BUILD',str(prefix))
    monkeypatch.setattr(FakeHost,'console_bin',prefix/'.ravel-site/site-analysis/bin',raising=False)


class FakeHost:
    def __init__(self, tools=(), outputs=None, paths=(), python=(3, 12)):
        self.tools = set(tools)
        self.outputs = outputs or {}
        self.paths = set(paths)
        self.python = python
        self.calls = []

    def which(self, name):
        if name.startswith('ravel-wms-condor-'):
            # Profile console scripts are found only where the site installation put them.
            script = Path(self.console_bin) / name
            return str(script) if script.is_file() else None
        return f'/usr/bin/{name}' if name in self.tools else None

    def run(self, argv):
        self.calls.append(argv)
        key = ' '.join(argv)
        if argv[:2]==['df','-Pk']:
            return 0,'Filesystem 1024-blocks Used Available Capacity Mounted on\nsynthetic 40000000 1 20000000 1% /work\n'
        if argv[:2]==['df','-PT']:
            return 0,'Filesystem Type 1024-blocks Used Available Capacity Mounted on\nsynthetic ext4 40000000 1 20000000 1% /work\n'
        if '-c' in argv:return 0,json.dumps(VERSIONS)
        if argv[0].endswith('/ravel-snakemake'):return 0,'9.27.0'
        return self.outputs.get(key, (0, ''))

    def exists(self, path):
        return str(path) in self.paths

    def home(self):
        return Path('/synthetic/home')

    def storage(self, path):
        return {'free_bytes': 100 * 2**30, 'quota_remaining_bytes': 100 * 2**30, 'quota_status': 'known'}

    def non_graphical(self):
        return False


LXPLUS_TOOLS = ('python3.12', 'bwrap', 'voms-proxy-info', 'klist', 'krenew', 'aklog', 'condor_q', 'pdflatex', 'node', 'claude',
                'rucio', 'apptainer', 'tmux', 'xrdcp')


def lxplus_host(**changes):
    outputs = {'voms-proxy-info --timeleft': (0, '86000\n'), 'klist -s': (0, ''), 'condor_q -totals': (0, 'Total for query: 0 jobs'),
               'node --version': (0, 'v20.11.1\n'), 'pdflatex --version': (0, 'pdfTeX 3.141592653'),
               'claude --version': (0, '2.1.0 (Claude Code)'), 'rucio --version': (0, 'rucio 35.0.0'),
               'apptainer --version': (0, 'apptainer version 1.3.4'), 'xrdcp --version': (0, 'v5.7.1'),
               'python3.12 --version': (0, 'Python 3.12.7')}
    outputs.update(changes.pop('outputs', {}))
    return FakeHost(tools=changes.pop('tools', LXPLUS_TOOLS), outputs=outputs,
                    paths=changes.pop('paths', {'/cvmfs/sft.cern.ch', '/cvmfs/atlas.cern.ch'}), **changes)


def statuses(report):
    return {c['name']: c['status'] for c in report['checks']}


def test_ready_lxplus_profile(tmp_path):
    eos = tmp_path / 'eos'
    eos.mkdir()
    report = sd.doctor(profile='lxplus', eos_dir=eos, host=lxplus_host())
    assert report['ready'] is True, report
    status = statuses(report)
    assert status['grid proxy'] == 'ok' and status['kerberos'] == 'ok' and status['eos write'] == 'ok'
    assert status['cvmfs /cvmfs/sft.cern.ch'] == 'ok' and status['batch scheduler'] == 'ok'
    assert not list(eos.iterdir()), 'the probe file is removed'
    assert 'tmux' in report['long_session']


def test_short_proxy_and_missing_ticket_fail_on_lxplus(tmp_path):
    host = lxplus_host(outputs={'voms-proxy-info --timeleft': (0, '600\n'), 'klist -s': (1, '')})
    report = sd.doctor(profile='lxplus', host=host)
    status = statuses(report)
    assert status['grid proxy'] == 'fail' and status['kerberos'] == 'fail'
    assert report['ready'] is False
    fixes = ' '.join(c.get('fix', '') for c in report['checks'])
    assert 'voms-proxy-init' in fixes and 'kinit' in fixes


def test_missing_tools_are_reported_with_fixes(tmp_path):
    host = lxplus_host(tools=('klist', 'condor_q'), paths=set())
    report = sd.doctor(profile='lxplus', host=host)
    status = statuses(report)
    assert status['python 3.12'] == 'fail'
    assert status['cvmfs /cvmfs/sft.cern.ch'] == 'fail'
    assert status['agent CLI'] == 'warn' and status['node'] == 'warn' and 'TeX' not in status
    python = next(c for c in report['checks'] if c['name'] == 'python 3.12')
    assert 'miniforge' in python['fix'].lower()


def test_generic_profile_does_not_require_cern_services():
    host = FakeHost(tools=('python3.12', 'bwrap', 'sbatch', 'squeue'), outputs={'python3.12 --version': (0, 'Python 3.12.1')})
    report = sd.doctor(profile='generic', host=host)
    status = statuses(report)
    assert report['ready'] is True
    assert status['kerberos'] == 'skip' and status['batch scheduler'] == 'ok'


def test_eos_write_failure_is_reported(tmp_path):
    report = sd.doctor(profile='lxplus', eos_dir=tmp_path / 'missing', host=lxplus_host())
    assert statuses(report)['eos write'] == 'fail'


def test_no_credential_contents_are_printed():
    host = lxplus_host(outputs={'klist -s': (0, ''), 'voms-proxy-info --timeleft': (0, '90000')})
    text = json.dumps(sd.doctor(profile='lxplus', host=host))
    assert not any(['klist'] == call for call in host.calls), 'only klist -s is run'
    assert 'principal' not in text.lower()


def test_cli_json(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(sd, 'Host', lambda: FakeHost(tools=('python3.12','bwrap'), outputs={'python3.12 --version': (0, 'Python 3.12.0')}))
    code = sd.main(['doctor', '--profile', 'generic', '--json'])
    out = json.loads(capsys.readouterr().out)
    assert out['profile'] == 'generic' and code == 0


def test_install_plan_for_no_root_site():
    plan = sd.install_plan('/synthetic/work/env', '/synthetic/work/checkout', host=FakeHost())
    text = '\n'.join(plan['commands'])
    assert 'Miniforge3' in text and 'python=3.12' in text and 'scripts/setup/install.sh --profile site' in text
    assert plan['root_required'] is False


def test_planned_home_quota_pdfinfo_and_long_session(tmp_path):
    host = lxplus_host()
    host.home = lambda: tmp_path / 'home'
    host.storage = lambda path: {'free_bytes': 100 * 2**30, 'quota_remaining_bytes': 2**30,
                                 'quota_status': 'known'}
    report = sd.doctor(host=host, prefix=host.home() / 'env', run_root=host.home() / 'runs',
                       transcript=host.home() / 'logs', work_dir=tmp_path / 'work',
                       planned_install_bytes=2 * 2**30, min_home_free_bytes=4 * 2**30,
                       run_hours=48, ticket_lifetime_hours=10)
    status = statuses(report)
    assert status['install location'] == status['run location'] == status['transcript location'] == 'fail'
    assert status['pdfinfo'] == 'warn'
    assert not report['ready']
    assert str(tmp_path / 'work') in next(c for c in report['checks'] if c['name'] == 'install location')['fix']
    assert "tmux new-session -s ravel 'krenew -K 60 -t -- sh'" in json.dumps(report)


def test_install_plan_refuses_small_home(tmp_path):
    host = FakeHost()
    host.home = lambda: tmp_path
    host.storage = lambda path: {'free_bytes': 2**30, 'quota_remaining_bytes': 2**30, 'quota_status': 'known'}
    with pytest.raises(ValueError, match='work'):
        sd.install_plan(tmp_path / 'env', tmp_path / 'checkout', host=host, min_home_free_bytes=2 * 2**30)


def test_run_duration_controls_proxy_requirement():
    report = sd.doctor(host=lxplus_host(), run_hours=48, ticket_lifetime_hours=10)
    row = next(c for c in report['checks'] if c['name'] == 'grid proxy')
    assert row['status'] == 'fail' and 'required 48 h' in row['detail']
    assert '--valid 48:00' in row['fix']
    host = lxplus_host(outputs={'voms-proxy-info --timeleft': (0, '172800')})
    assert statuses(sd.doctor(host=host, run_hours=48))['grid proxy'] == 'ok'


@pytest.mark.parametrize('output', [(1, '0'), (0, 'invalid'), (0, '0'), (0, '-1')])
def test_invalid_proxy_never_passes_even_with_zero_requested_hours(output):
    host = lxplus_host(outputs={'voms-proxy-info --timeleft': output})
    assert statuses(sd.doctor(host=host, min_proxy_hours=0))['grid proxy'] == 'fail'


def test_long_session_requires_renewal_tools_and_afs_refresh():
    host = lxplus_host(tools=tuple(n for n in LXPLUS_TOOLS if n != 'krenew'))
    assert statuses(sd.doctor(host=host, run_hours=48, ticket_lifetime_hours=10))['ticket renewal'] == 'fail'
    assert statuses(sd.doctor(host=host, run_hours=1, ticket_lifetime_hours=10))['ticket renewal'] == 'warn'
    host = lxplus_host(tools=tuple(n for n in LXPLUS_TOOLS if n != 'aklog'))
    report = sd.doctor(host=host, run_hours=48, ticket_lifetime_hours=10)
    assert statuses(report)['ticket renewal'] == statuses(report)['AFS renewal'] == 'fail'
    assert not any(call[0] in ('krenew', 'aklog', 'kinit', 'tokens') for call in host.calls)


def test_unknown_ticket_lifetime_is_explicit_and_short_ticket_uses_short_interval():
    report = sd.doctor(host=lxplus_host(), run_hours=48)
    row = next(c for c in report['checks'] if c['name'] == 'ticket renewal')
    assert row['status'] == 'warn' and 'not declared' in row['detail']
    report = sd.doctor(host=lxplus_host(), run_hours=48, ticket_lifetime_hours=0.5)
    assert 'krenew -K 15 -t -- sh' in json.dumps(report)


def test_analysis_facility_uses_slurm_even_when_condor_is_present():
    host = lxplus_host(tools=(*LXPLUS_TOOLS, 'sbatch', 'squeue', 'pdfinfo'))
    report = sd.doctor(profile='analysis-facility', host=host, run_hours=4, ticket_lifetime_hours=1)
    status = statuses(report)
    assert report['ready'] and status['pdfinfo'] == status['kerberos'] == 'ok'
    assert ['squeue', '-h'] in host.calls and ['condor_q', '-totals'] not in host.calls
    assert 'SLURM' in next(c for c in report['checks'] if c['name'] == 'batch scheduler')['detail']
    assert 'krenew -K 30 -- sh' in json.dumps(report)
    host = lxplus_host()
    assert statuses(sd.doctor(profile='analysis-facility', host=host))['batch scheduler'] == 'fail'


def test_ssh_login_routes_are_from_help_and_never_executed():
    host = FakeHost(tools=('codex', 'claude'), outputs={
        'codex login --help': (0, 'Options: --device-auth --with-api-key'),
        'claude auth login --help': (0, 'Options: --device-code'),
    })
    host.non_graphical = lambda: True
    report = sd.doctor(profile='generic', host=host)
    text = json.dumps(report)
    assert 'codex login --device-auth' in text and 'codex login --with-api-key' in text
    assert 'claude auth login --device-code' in text
    # The login checks only read help and version text; the runtime checks' read-only probes are separate.
    assert all(call[-1] in ('--help', '--version') for call in host.calls if call[0] in ('codex', 'claude'))


def test_login_unknown_help_does_not_invent_route_or_echo_output():
    host = FakeHost(tools=('codex',), outputs={'codex login --help': (1, 'untrusted-help'),
                                             'codex --help': (0, 'unsupported-route')})
    host.non_graphical = lambda: True
    report = sd.doctor(profile='generic', host=host)
    assert statuses(report)['codex SSH login'] == 'warn'
    assert 'untrusted-help' not in json.dumps(report) and 'unsupported-route' not in json.dumps(report)
    assert 'login --device-auth' not in json.dumps(report)


def test_help_advertised_api_environment_route():
    host = FakeHost(tools=('claude',), outputs={'claude --help': (0, 'Set ANTHROPIC_API_KEY to use an API key')})
    host.non_graphical = lambda: True
    report = sd.doctor(profile='generic', host=host)
    assert statuses(report)['claude SSH login'] == 'ok'
    assert 'Set ANTHROPIC_API_KEY' in json.dumps(report)
    assert [call for call in host.calls if call[0] == 'claude'] == [['claude', 'auth', 'login', '--help'], ['claude', '--help']]


def test_unknown_quota_refuses_planned_home_but_reports_work_capacity(tmp_path):
    host = FakeHost()
    host.home = lambda: tmp_path / 'home'
    host.storage = lambda path: {'free_bytes': 100 * sd.GIB, 'quota_status': 'unknown'}
    rows = sd.location_checks(host, prefix=host.home() / 'env', run_root=tmp_path / 'work/runs',
                              transcript=host.home() / 'logs', planned_install_bytes=3 * sd.GIB)
    assert {r['name']: r['status'] for r in rows} == {'home space': 'warn', 'install location': 'fail',
                                                    'run location': 'warn', 'transcript location': 'fail'}
    assert rows[1]['required_bytes'] == 10 * sd.GIB
    assert rows[2]['free_bytes'] == 100 * sd.GIB


def test_unlimited_quota_and_exact_capacity_boundary(tmp_path):
    host = FakeHost()
    host.home = lambda: tmp_path
    host.storage = lambda path: {'free_bytes': 10 * sd.GIB, 'quota_status': 'unlimited', 'quota_remaining_bytes': None}
    rows = sd.location_checks(host, prefix=tmp_path / 'env', planned_install_bytes=10 * sd.GIB)
    assert all(r['status'] == 'ok' for r in rows)
    rows = sd.location_checks(host, prefix=tmp_path / 'env', planned_install_bytes=10 * sd.GIB + 1)
    assert rows[1]['status'] == 'fail'


def test_outside_home_install_uses_smaller_of_disk_and_quota(tmp_path):
    host = FakeHost()
    host.home = lambda: tmp_path / 'home'
    host.storage = lambda path: {'free_bytes': 2 * sd.GIB, 'quota_status': 'known', 'quota_remaining_bytes': 100 * sd.GIB}
    rows = sd.location_checks(host, prefix=tmp_path / 'work', planned_install_bytes=3 * sd.GIB)
    assert rows[1]['status'] == 'fail' and not rows[1]['home_area']


def test_location_symlink_into_home_cannot_bypass_check(tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    link = tmp_path / 'work-alias'
    link.symlink_to(home, target_is_directory=True)
    host = FakeHost()
    host.home = lambda: home
    host.storage = lambda path: {'free_bytes': sd.GIB, 'quota_remaining_bytes': sd.GIB, 'quota_status': 'known'}
    rows = sd.location_checks(host, run_root=link / 'new-runs')
    assert rows[1]['status'] == 'fail' and rows[1]['home_area']


def test_capacity_failure_refuses_plan(tmp_path):
    host = FakeHost()
    host.storage = lambda path: (_ for _ in ()).throw(OSError('synthetic storage failure'))
    rows = sd.location_checks(host, transcript=tmp_path / 'logs')
    assert rows[1]['status'] == 'fail'


def test_quota_parsers_do_not_confuse_filesystems_or_unlimited():
    assert sd._afs_quota('Volume Name Quota Used %Used\nsynthetic.volume 1000 750 75%') == {
        'quota_status': 'known', 'quota_remaining_bytes': 250 * 1024}
    assert sd._afs_quota('synthetic.volume 0 750 0%')['quota_status'] == 'unlimited'
    assert sd._afs_quota('unrecognized format') == {}
    text = 'Filesystem blocks quota limit grace files quota limit\n/dev/fake 900* 1000 1200 0 0 0'
    assert sd._unix_quota(text, '/dev/fake')['quota_remaining_bytes'] == 100 * 1024
    assert sd._unix_quota(text, '/dev/other') == {}
    assert sd._unix_quota('/dev/fake 200 0 0 0 0 0', '/dev/fake')['quota_status'] == 'unlimited'


def test_host_storage_probes_nearest_existing_ancestor_without_writes(tmp_path, monkeypatch):
    host = sd.Host()
    calls = []
    monkeypatch.setattr(host, 'which', lambda name: name if name == 'quota' else None)

    def run(argv):
        calls.append(argv)
        if argv[0] == 'df':
            return 0, 'Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/fake 1000 100 900 10% /work'
        return 0, 'Filesystem blocks quota limit grace files quota limit\n/dev/fake 750 1000 1200 0 0 0'

    monkeypatch.setattr(host, 'run', run)
    result = host.storage(tmp_path / 'not-created/env')
    assert result['anchor'] == str(tmp_path.resolve())
    assert result['quota_remaining_bytes'] == 250 * 1024
    assert calls == [['df', '-P', str(tmp_path.resolve())], ['quota', '-w', '-v']]
    assert not list(tmp_path.iterdir())


def test_host_non_graphical_detection(monkeypatch):
    for name in ['SSH_CONNECTION', 'SSH_TTY', 'DISPLAY', 'WAYLAND_DISPLAY']:
        monkeypatch.delenv(name, raising=False)
    assert sd.Host().non_graphical()
    monkeypatch.setenv('DISPLAY', ':synthetic')
    assert not sd.Host().non_graphical()
    monkeypatch.setenv('SSH_CONNECTION', 'synthetic connection')
    assert sd.Host().non_graphical()


@pytest.mark.parametrize('arguments', [{'run_hours': -1}, {'run_hours': float('nan')}, {'run_hours': True},
                                      {'min_proxy_hours': float('inf')}, {'ticket_lifetime_hours': -1},
                                      {'planned_install_bytes': -1}, {'min_home_free_bytes': 1.5}])
def test_invalid_duration_and_storage_declarations(arguments):
    with pytest.raises(ValueError):
        sd.doctor(host=FakeHost(), **arguments)


def test_cli_exposes_plan_and_shared_record(tmp_path, monkeypatch, capsys):
    host = lxplus_host(tools=(*LXPLUS_TOOLS, 'sbatch', 'squeue'))
    monkeypatch.setattr(sd, 'Host', lambda: host)
    site = tmp_path / 'site.json'
    site.write_text(json.dumps({'scheduler': 'slurm', 'environment_allowlist': ['A'], 'environment': {'A': '1'}}))
    code = sd.main(['doctor', '--profile', 'analysis-facility', '--site-record', str(site),
                    # The installed site prefix of the autouse fixture: its capacity and its runtime are checked.
                    '--prefix', os.environ['RAVEL_NATIVE_BUILD'], '--run-root', str(tmp_path / 'runs'),
                    '--transcript', str(tmp_path / 'transcript'), '--planned-install-gib', '2',
                    '--min-home-free-gib', '4', '--run-hours', '4', '--ticket-lifetime-hours', '10', '--json'])
    report = json.loads(capsys.readouterr().out)
    assert code == 0 and report['profile'] == 'analysis-facility'
    assert all('id' in row for row in report['checks'])
    assert statuses(report)['install location'] == statuses(report)['transcript location'] == 'ok'
    assert ['squeue', '-h'] in host.calls


def test_cli_refuses_small_home_and_invalid_record(tmp_path, monkeypatch, capsys):
    host = FakeHost()
    host.home = lambda: tmp_path
    host.storage = lambda path: {'free_bytes': sd.GIB, 'quota_status': 'known', 'quota_remaining_bytes': sd.GIB}
    monkeypatch.setattr(sd, 'Host', lambda: host)
    assert sd.main(['install-plan', '--prefix', str(tmp_path / 'env'), '--checkout', str(tmp_path)]) == 2
    assert 'work' in capsys.readouterr().err
    site = tmp_path / 'site.json'
    site.write_text('[]')
    assert sd.main(['doctor', '--site-record', str(site)]) == 2
    assert 'object' in capsys.readouterr().err


def test_help_flag_prefix_is_not_a_supported_login_route():
    host = FakeHost(tools=('codex',), outputs={'codex login --help': (0, '--device-auth-other --with-api-key-other')})
    host.non_graphical = lambda: True
    assert statuses(sd.doctor(profile='generic', host=host))['codex SSH login'] == 'warn'


def test_declared_proxy_path_is_checked_without_contents(tmp_path, monkeypatch):
    proxy = tmp_path / 'fake-proxy'
    proxy.touch()
    host = lxplus_host(outputs={f'voms-proxy-info --file {proxy} --timeleft': (0, '90000')})
    real_open = Path.open
    monkeypatch.setattr(Path, 'open', lambda self, *a, **k: pytest.fail('credential file must not be opened')
                        if Path(self) == proxy else real_open(self, *a, **k))
    report = sd.doctor(host=host, site_record={'scheduler': 'htcondor', 'proxy_path': str(proxy)})
    assert statuses(report)['grid proxy'] == 'ok'
    assert ['voms-proxy-info', '--file', str(proxy), '--timeleft'] in host.calls
    proxy.unlink()
    host.calls.clear()
    report = sd.doctor(host=host, site_record={'scheduler': 'htcondor', 'proxy_path': str(proxy)})
    assert statuses(report)['grid proxy path'] == 'fail'
    assert not any(call[0] == 'voms-proxy-info' for call in host.calls)


def test_install_plan_quotes_paths_and_forwards_prefix(tmp_path):
    prefix = tmp_path / 'work area/env'
    checkout = tmp_path / 'source area'
    plan = sd.install_plan(prefix, checkout, host=FakeHost(), planned_install_bytes=3 * sd.GIB)
    assert f"--prefix '{prefix}' --plan" in '\n'.join(plan['commands'])
    assert f"cd '{checkout}'" in '\n'.join(plan['commands'])


def test_host_afs_quota_probe_does_not_run_authentication(monkeypatch):
    host = sd.Host()
    calls = []
    monkeypatch.setattr(Path, 'exists', lambda self: True)
    monkeypatch.setattr(Path, 'is_dir', lambda self: True)
    monkeypatch.setattr(sd.shutil, 'disk_usage', lambda path: type('Usage', (), {'free': 100 * sd.GIB})())
    monkeypatch.setattr(host, 'which', lambda name: name if name == 'fs' else None)

    def run(argv):
        calls.append(argv)
        return 0, 'Volume Name Quota Used %Used\nsynthetic.volume 1000 750 75%'

    monkeypatch.setattr(host, 'run', run)
    result = host.storage('/afs/synthetic/home')
    assert result['quota_remaining_bytes'] == 250 * 1024
    assert calls == [['fs', 'listquota', '-path', '/afs/synthetic/home']]


def test_existing_file_is_not_an_install_or_run_directory(tmp_path):
    file = tmp_path / 'existing-file'
    file.touch()
    rows = sd.location_checks(FakeHost(), prefix=file, run_root=file, transcript=file)
    assert {r['name']: r['status'] for r in rows} == {'home space': 'ok', 'install location': 'fail',
                                                    'run location': 'fail', 'transcript location': 'ok'}


def test_identical_site_record_drives_doctor_and_batch(tmp_path):
    from ravel.workflow.backends import site_batch
    proxy = tmp_path / 'fake-proxy'
    proxy.touch()
    site = {'scheduler': 'htcondor', 'job_length_classes': {'extended': 10800}, 'job_flavour': 'extended',
            'proxy_path': str(proxy), 'environment_allowlist': ['A'], 'environment': {'A': '1'}}
    host = lxplus_host(outputs={f'voms-proxy-info --file {proxy} --timeleft': (0, '90000')})
    report = sd.doctor(host=host, site_record=site, run_hours=2, ticket_lifetime_hours=10)
    job = {'site': site, 'resources': {'wall_seconds': 7200, 'cpus': 1, 'memory_mib': 2000}}
    text = site_batch.render({'spec': job}, tmp_path, 'synthetic-job')
    assert report['ready'] and '+JobFlavour = "extended"' in text and str(proxy) in text
    assert 'environment = "A=1"' in text


def test_htcondor_facility_record_overrides_default_scheduler_and_credentials():
    host = FakeHost(tools=('condor_q', 'voms-proxy-info'),
                    outputs={'voms-proxy-info --timeleft': (0, '86400\n')})
    report = sd.doctor(profile='analysis-facility', host=host, site_record={
        'scheduler': 'htcondor', 'requires_proxy': True, 'requires_kerberos': False, 'requires_afs': False})
    checks = statuses(report)
    assert checks['batch scheduler'] == 'ok'
    assert ['condor_q', '-totals'] in host.calls
    assert ['squeue', '-h'] not in host.calls and ['klist', '-s'] not in host.calls
