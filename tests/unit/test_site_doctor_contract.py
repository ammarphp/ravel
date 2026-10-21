"""Site readiness with stored synthetic records and a read-only Host double."""
import json
from pathlib import Path

import pytest

from ravel.workflow import site_doctor as sd
from site_install_fixture import lock_text, VERSIONS, SOURCE


class Host:
    def __init__(self, home, *, quota='homefs 100M 0 1G 0 0 0', free_kb=20_000_000,
                 missing=(), versions=None, filesystem='ext4'):
        self.home_dir = home
        self.quota = quota
        self.free_kb = free_kb
        self.missing = set(missing)
        self.versions = VERSIONS if versions is None else versions
        self.filesystem = filesystem
        self.calls = []

    def which(self, name):
        if name.startswith('ravel-wms-condor-'):
            # Profile console scripts are found only where the site installation put them.
            script = Path(self.console_bin) / name if getattr(self, 'console_bin', None) else None
            return str(script) if script is not None and script.is_file() and name not in self.missing else None
        return None if name in self.missing else f'/synthetic/bin/{name}'

    def exists(self, path):
        return Path(path).exists()

    # The planned-location and login probes of the doctor; these checks read the run() probes above.
    def home(self):
        return self.home_dir

    def storage(self, path):
        return {'free_bytes': self.free_kb * 1024, 'quota_remaining_bytes': None, 'quota_status': 'unlimited'}

    def non_graphical(self):
        return False

    def run(self, argv):
        self.calls.append(argv)
        if argv[0] == 'quota':
            return 0, 'Filesystem space quota limit grace files quota limit grace\n' + self.quota
        if argv[:2] == ['fs', 'listquota']:
            return 0, 'Volume Name Quota Used %Used Partition\nsynthetic 1000000 999000 99% 50%\n'
        if argv[:2] == ['df', '-Pk']:
            fs='homefs' if Path(argv[-1]).is_relative_to(self.home_dir) else 'workfs'
            return 0, f'Filesystem 1024-blocks Used Available Capacity Mounted on\n{fs} 40000000 1000 {self.free_kb} 1% /work\n'
        if argv[:2] == ['df', '-PT']:
            return 0, f'Filesystem Type 1024-blocks Used Available Capacity Mounted on\nsynthetic {self.filesystem} 40000000 1000 20000000 1% /work\n'
        if '-c' in argv:
            return 0, json.dumps(self.versions)
        if argv[-1] == '--version':
            if argv[0].endswith('ravel-snakemake'):
                return 0, self.versions.get('snakemake', '')
            return 0, 'Python 3.12.1' if 'python' in argv[0] else 'v20.0.0'
        return 0, ''


def installed(tmp_path, monkeypatch):
    prefix = tmp_path / 'work'
    records = prefix / '.ravel-site'; records.mkdir(parents=True)
    lock = records / 'requirements-site-wms.lock'; lock.write_text(lock_text())
    import hashlib
    (records / 'wms.json').write_text(json.dumps({'schema_version': 1, 'release': 'synthetic-a',
        'version': '9.27.0', 'plugins': {'snakemake-executor-plugin-cluster-generic': '1.0.9'},
        'packages': VERSIONS, 'lock_sha256': hashlib.sha256(lock.read_bytes()).hexdigest(),
        'snakemake': str(records / 'site-wms/bin/snakemake'), 'shim': str(prefix / 'bin/ravel-snakemake'),
        'analysis_python': str(records / 'site-analysis/bin/python'), 'lock': str(lock)}))
    (records / 'lcg-view.json').write_text(json.dumps({'schema_version': 1, 'choice': 'none',
                                                     'path': None, 'platform': None, 'release': None}))
    for path in ('bin/ravel-snakemake', '.ravel-site/site-wms/bin/snakemake',
                 '.ravel-site/site-wms/bin/python', '.ravel-site/site-analysis/bin/python'):
        target = prefix / path; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('#!/bin/sh\nexit 0\n'); target.chmod(0o755)
    # Installing the release into site-analysis writes its declared profile console scripts.
    analysis = records / 'site-analysis/bin'
    for name in ('ravel-wms-condor-submit', 'ravel-wms-condor-status'):
        script = analysis / name; script.write_text('#!' + str(analysis / 'python') + '\n'); script.chmod(0o755)
    home = tmp_path / 'home'; home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.delenv('PYTHONPATH', raising=False)
    monkeypatch.setattr(sd, '_agent_cli_readiness', lambda host, prefix, environ=None: {
        'status': 'ready', 'transport_qualified': True, 'transport': 'synthetic-cli-worker', 'detail': 'stored qualification'})
    monkeypatch.setattr(sd, '_lease_domain', lambda: {'path': str(tmp_path / 'lease'), 'scope': 'host',
        'lock_mode': 'local', 'reason': 'synthetic', 'policy': {'batch_slot_dir_env': 'JOB_SCRATCH'}})
    host = Host(home); host.console_bin = analysis
    return prefix, host


def rows(report):
    return {row['name']: row for row in report['checks']}


def test_doctor_green_prefix_no_tex_and_caches(tmp_path, monkeypatch):
    prefix, host = installed(tmp_path, monkeypatch)
    report = sd.doctor(profile='generic', prefix=prefix, host=host)
    assert report['ready'], report
    checks = rows(report)
    assert 'TeX' not in checks
    for name in ('apptainer cache', 'apptainer temporary'):
        assert checks[name]['status'] == 'ok' and str(prefix) in checks[name]['detail']


@pytest.mark.parametrize('versions,name', [
    (dict(VERSIONS, snakemake='9.26.0'), 'site snakemake'),
    ({k: v for k, v in VERSIONS.items() if k != 'snakemake-executor-plugin-cluster-generic'}, 'site executor plugin'),
    (dict(VERSIONS, **{'snakemake-executor-plugin-cluster-generic': '1.0.8'}), 'site executor plugin'),
    (dict(VERSIONS, **{'snakemake-interface-executor-plugins': '10.0.0'}), 'site executor interface'),
])
def test_wrong_runtime_versions_fail(tmp_path, monkeypatch, versions, name):
    prefix, host = installed(tmp_path, monkeypatch); host.versions = versions
    report = sd.doctor(profile='generic', prefix=prefix, host=host)
    assert rows(report)[name]['status'] == 'fail' and not report['ready']


def test_recorded_view_removed_fails(tmp_path, monkeypatch):
    prefix, host = installed(tmp_path, monkeypatch)
    view = tmp_path / 'view'; view.mkdir(); (view / 'setup.sh').write_text('# synthetic\n')
    (prefix / '.ravel-site/lcg-view.json').write_text(json.dumps({'schema_version': 1, 'choice': str(view),
        'path': str(view), 'release': 'LCG_200', 'platform': 'x86_64-opt'}))
    assert rows(sd.doctor(profile='generic', prefix=prefix, host=host))['lcg view']['status'] == 'ok'
    (view / 'setup.sh').unlink()
    assert rows(sd.doctor(profile='generic', prefix=prefix, host=host))['lcg view']['status'] == 'fail'


@pytest.mark.parametrize('argument', ['prefix', 'runs_dir', 'transcripts_dir'])
def test_low_home_quota_fails_each_location(tmp_path, monkeypatch, argument):
    prefix, host = installed(tmp_path, monkeypatch)
    options = dict(prefix=prefix, runs_dir=tmp_path / 'runs', transcripts_dir=tmp_path / 'transcripts')
    options[argument] = host.home_dir / argument
    report = sd.doctor(profile='generic', host=host, **options)
    name = {'prefix': 'prefix location', 'runs_dir': 'runs location', 'transcripts_dir': 'transcripts location'}[argument]
    check = rows(report)[name]
    assert check['status'] == 'fail' and 'work area' in check['fix']
    assert 'quota' in check['detail'] and 'free' in check['detail']


def test_work_area_and_space_and_unknown_quota(tmp_path, monkeypatch):
    prefix, host = installed(tmp_path, monkeypatch)
    assert rows(sd.doctor(profile='generic', prefix=prefix, host=host))['prefix location']['status'] == 'ok'
    host.free_kb = 100
    assert rows(sd.doctor(profile='generic', prefix=prefix, host=host))['prefix location']['status'] == 'fail'
    host.free_kb = 20_000_000; host.quota = ''
    assert sd.location_check('prefix', host.home_dir / 'tools', host=host, threshold_gb=4)['status'] == 'fail'


def test_installer_refuses_low_home_quota(tmp_path, monkeypatch):
    from site_install_fixture import fixture
    helper, root, calls = fixture(tmp_path, monkeypatch)
    home = tmp_path / 'home'; home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    with pytest.raises(ValueError, match='work area'):
        helper.install(root, prefix=home / 'tools', lcg_view='none', host=Host(home))
    assert not calls


def test_lease_network_local_warns_and_no_policy_names_command(tmp_path, monkeypatch):
    prefix, host = installed(tmp_path, monkeypatch); host.filesystem = 'afs'
    monkeypatch.setattr(sd, '_lease_domain', lambda: {'path': str(tmp_path / 'lease'),
        'scope': 'host', 'lock_mode': 'local', 'reason': 'synthetic', 'policy': None})
    checks = rows(sd.doctor(profile='generic', prefix=prefix, host=host))
    assert checks['lease filesystem']['status'] == 'warn'
    assert checks['batch lease policy']['status'] == 'warn'
    assert 'ravel lease policy set --scope host --batch-slot-dir-env' in checks['batch lease policy']['fix']


def test_pythonpath_bwrap_and_unqualified_transport_fixes(tmp_path, monkeypatch):
    prefix, host = installed(tmp_path, monkeypatch); host.missing.add('bwrap')
    monkeypatch.setenv('PYTHONPATH', '/fake/view')
    monkeypatch.setattr(sd, '_agent_cli_readiness', lambda host, prefix, environ=None: {
        'status': 'ready', 'transport_qualified': False, 'transport': 'synthetic-cli-worker', 'detail': 'unqualified'})
    checks = rows(sd.doctor(profile='generic', prefix=prefix, host=host))
    assert checks['calling pythonpath']['status'] == 'warn'
    assert str(prefix / 'bin/ravel-snakemake') in checks['calling pythonpath']['fix']
    assert checks['worker sandbox']['status'] == 'fail' and 'bwrap' in checks['worker sandbox']['fix']
    assert checks['worker transport']['status'] == 'fail'
    assert 'ravel transport qualify synthetic-cli-worker' in checks['worker transport']['fix']


def test_plan_pins_miniforge_and_verifies_before_install():
    manifest = json.loads((SOURCE / 'native/setup/toolchain-manifest.json').read_text())['miniforge']
    for arch in ('x86_64', 'aarch64'):
        commands = sd.install_plan('/synthetic/work', '/synthetic/source', arch=arch)['commands']
        assert manifest['version'] in commands[0] and 'releases/latest' not in '\n'.join(commands)
        assert manifest['assets']['linux-' + arch]['sha256'] in commands[1] and 'sha256sum -c' in commands[1]


def test_setup_doctor_prints_site_qualification_command():
    from ravel.setup.doctor import group_label, format_report
    group = {'id': 'site-root-wms', 'qualification': {'status': 'tester-qualification', 'basis': 'facility user'}}
    entry = dict(group='site-root-wms', status='ready', checks=[], **group_label(group, 'ready', []))
    report = dict(platform='linux-x86_64', prefix='/synthetic/work', groups=[entry], conflicts=[], ready=True)
    text = format_report(report)
    assert 'ravel site doctor' in text and 'docs/reference/site-workflows.md' in text
    assert entry['qualification'] == 'built-unqualified' and entry['scientific_acceptance'] is False


@pytest.mark.parametrize('damage',['lock','schema','plugin','path'])
def test_record_tampering_fails_and_runtime_does_not_use_it(tmp_path,monkeypatch,damage):
    from ravel.workflow import wms_runtime
    prefix,host=installed(tmp_path,monkeypatch)
    path=prefix/'.ravel-site/wms.json'
    value=json.loads(path.read_text())
    if damage=='lock':(prefix/'.ravel-site/requirements-site-wms.lock').write_text(lock_text()+'# changed\n')
    elif damage=='schema':value['schema_version']=2
    elif damage=='plugin':value['plugins']={}
    else:value['shim']='/synthetic/unrelated/bin/snakemake'
    path.write_text(json.dumps(value))
    monkeypatch.setenv('RAVEL_NATIVE_BUILD',str(prefix))
    assert wms_runtime._site_wms_record() is None
    assert rows(sd.doctor(profile='generic',prefix=prefix,host=host))['site wms record']['status']=='fail'


def test_console_scripts_bind_analysis_interpreter_and_fail_foreign_python(tmp_path,monkeypatch):
    prefix,host=installed(tmp_path,monkeypatch)
    script=tmp_path/'ravel-wms-condor-submit'
    script.write_text('#!'+str(prefix/'.ravel-site/site-analysis/bin/python')+'\n')
    old=host.which
    host.which=lambda name:str(script) if name=='ravel-wms-condor-submit' else old(name)
    assert rows(sd.doctor(profile='generic',prefix=prefix,host=host))['ravel-wms-condor-submit']['status']=='ok'
    script.write_text('#!/synthetic/global/python\n')
    assert rows(sd.doctor(profile='generic',prefix=prefix,host=host))['ravel-wms-condor-submit']['status']=='fail'


def test_declared_console_scripts_are_required_and_found_in_the_analysis_environment(tmp_path,monkeypatch):
    # This release declares both scheduler-profile console scripts, so the doctor requires them.
    assert {'ravel-wms-condor-submit','ravel-wms-condor-status'} <= sd._profile_console_scripts()
    prefix,host=installed(tmp_path,monkeypatch)
    report=rows(sd.doctor(profile='generic',prefix=prefix,host=host))
    assert report['ravel-wms-condor-submit']['status']==report['ravel-wms-condor-status']['status']=='ok'
    (prefix/'.ravel-site/site-analysis/bin/ravel-wms-condor-status').unlink()
    report=sd.doctor(profile='generic',prefix=prefix,host=host)
    assert rows(report)['ravel-wms-condor-status']['status']=='fail' and report['ready'] is False


def test_afs_quota_and_wrapped_quota_rows():
    assert sd._quota_free('Volume Name Quota Used %Used Partition\nsynthetic 1000000 999000 99% 50%',afs=True)==1000*1024
    assert sd._quota_free('Filesystem space quota limit grace files quota limit grace\n/synthetic/home\n 100M 1G 2G 0 0 0 0')==924*1024**2
    assert sd._quota_free('homefs 100M 1G 2G 0 0 0\nworkfs 100M 20G 25G 0 0 0',filesystem='workfs')==20*1024**3-100*1024**2


def test_missing_group_still_prints_qualification_command():
    from ravel.setup.doctor import format_report,group_label
    group={'id':'site-access','qualification':{'status':'tester-qualification','basis':'facility user'}}
    checks=[{'id':'access','status':'missing','fix':'install access'}]
    entry=dict(group='site-access',status='missing',checks=checks,**group_label(group,'missing',checks))
    assert 'ravel site doctor' in format_report(dict(platform='linux-x86_64',prefix='/synthetic/work',
        groups=[entry],conflicts=[],ready=False))


def test_shared_agent_cli_helper_reads_records_without_live_qualification(tmp_path,monkeypatch):
    from ravel.workflow import transport_registry as registry
    import hashlib
    executable=tmp_path/'claude';executable.write_text('# inert CLI\n')
    # The owner's dedicated file-backed worker login; the helper checks it with a prompt-free status call.
    login=tmp_path/'claude-login';login.mkdir(mode=0o700)
    (login/'.credentials.json').write_text('opaque-owner-fixture');(login/'.credentials.json').chmod(0o600)
    environ={'PATH':'/usr/bin:/bin','CLAUDE_CONFIG_DIR':str(login)}
    class CLIHost:
        def which(self,name):return str(executable) if name=='claude' else None
        def run(self,argv):
            if argv==[str(executable),'auth','status','--json']:
                return 0,json.dumps({'loggedIn':True,'authMethod':'claude.ai'})
            assert argv==[str(executable),'--version']
            return 0,'2.1.296'
    record={'unusable':False,'executable_sha256':hashlib.sha256(executable.read_bytes()).hexdigest(),
            'executable_path':str(executable)}
    from ravel.controller.step import seats
    monkeypatch.setattr(seats, 'wired_transports', lambda: {'wired': ['claude-cli-worker'], 'excluded': [], 'kinds': ['cli-worker']})
    monkeypatch.setattr(registry,'read_probe',lambda identity:record)
    monkeypatch.setattr(registry,'probe_problem',lambda record,document:None)
    monkeypatch.setattr(registry,'qualification_status',lambda document,record:'live_qualified')
    qualification = {key: None for key in registry.QUALIFICATION_RECORD_KEYS}
    qualification.update(schema_version=1, kind='transport-qualification', status='live_qualified',
        observed={'requested_model': 'synthetic-model', 'model': 'synthetic-model'},
        steps=[{'step': step, 'passed': True} for step in sorted(registry.QUALIFICATION_STEPS)])
    monkeypatch.setattr(registry, 'read_qualification', lambda document, record: qualification)
    assert sd._agent_cli_readiness(CLIHost(),tmp_path,environ)['transport_qualified'] is True
    executable.write_text('# changed inert CLI\n')
    assert sd._agent_cli_readiness(CLIHost(),tmp_path,environ)['transport_qualified'] is False
    # Without the owner's login the helper reports the login remedy, never a qualified transport.
    missing=sd._agent_cli_readiness(CLIHost(),tmp_path,{'PATH':'/usr/bin:/bin'})
    assert missing['status']=='unconfigured' and missing.get('transport_qualified') is not True
    assert missing['authentication']=='login_required'


@pytest.mark.parametrize('threshold',[float('nan'),float('inf'),-1])
def test_threshold_requires_finite_positive_size(tmp_path,monkeypatch,threshold):
    prefix,host=installed(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='positive'):
        sd.doctor(profile='generic',prefix=prefix,host=host,min_free_gb=threshold)


def test_setup_doctor_prints_shared_site_warnings():
    from ravel.setup.doctor import format_report
    check={'id':'site-install-contract','status':'ready','warnings':['lease filesystem: local mode on afs']}
    text=format_report(dict(platform='linux-x86_64',prefix='/synthetic/work',
        groups=[dict(group='site-root-wms',status='ready',checks=[check])],conflicts=[],ready=True))
    assert 'lease filesystem: local mode on afs' in text
