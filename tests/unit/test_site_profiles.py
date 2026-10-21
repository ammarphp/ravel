"""Shared-filesystem scheduler contracts with inert tools on a temporary PATH."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from contextlib import contextmanager

import pytest

from ravel.workflow.site_profiles import htcondor as hc, render, write_profiles


@pytest.fixture
def scheduler(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / 'bin'; folder.mkdir()
    fixture = tmp_path / 'scheduler.json'
    fixture.write_text(json.dumps({'queue': '', 'history': '', 'submit': '12.0 - 12.0\n'}))
    calls = tmp_path / 'calls.jsonl'
    code = f'''#!{sys.executable}
import json, pathlib, sys
with pathlib.Path({str(calls)!r}).open('a') as out:
    out.write(json.dumps(sys.argv) + '\\n')
data = json.loads(pathlib.Path({str(fixture)!r}).read_text())
name = pathlib.Path(sys.argv[0]).name
print(data[{{'condor_submit':'submit','condor_q':'queue','condor_history':'history'}}[name]], end='')
if name == 'condor_submit':
    print(data.get('stderr', ''), end='', file=sys.stderr)
    raise SystemExit(data.get('code', 0))
'''
    for name in ('condor_submit', 'condor_q', 'condor_history'):
        tool = folder / name; tool.write_text(code); tool.chmod(0o755)
    monkeypatch.setenv('PATH', str(folder))
    def set_data(**data):
        old = json.loads(fixture.read_text()); old.update(data); fixture.write_text(json.dumps(old))
    def read_calls():
        return [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
    return set_data, read_calls


def job(tmp_path, rule='task_alpha', resources=None):
    path = tmp_path / 'job script.sh'
    props = {'threads': 2, 'rule': rule, 'resources': resources or {}}
    path.write_text('#!/bin/sh\n# properties = ' + json.dumps(props) + '\nexit 0\n')
    return path


def profile(tmp_path, **options):
    (tmp_path / 'run-keys.json').write_text(json.dumps({'alpha': '012abc'}))
    return render('htcondor', project_id='project-a', options={'workflow_dir': str(tmp_path), **options})


def descriptor(tmp_path):
    return next(tmp_path.rglob('*.sub')).read_text()


def test_submit_resources_tags_clean_environment_and_hold_policy(tmp_path, scheduler):
    hc.submit(job(tmp_path, resources={'runtime': 120, 'mem_mb': 4000}), profile=profile(tmp_path))
    text = descriptor(tmp_path)
    for line in ('request_cpus = 2', 'request_memory = 4000MB', '+MaxRuntime = 7200',
                 'getenv = False', 'should_transfer_files = NO', 'RAVEL_LEASE_SCOPE=batch-slot',
                 '+RavelProject = "project-a"', '+RavelRun = "012abc"', '+RavelTask = "alpha"',
                 'batch_name = "012abc"', 'environment = ',
                 'periodic_remove = (JobStatus == 5) && (HoldReasonCode =!= 1) && (HoldReasonCode =!= 15) && (RavelPause =?= undefined) && ((time() - EnteredCurrentStatus) > 1800)'):
        assert line in text
    assert len(scheduler[1]()) == 1


@pytest.mark.parametrize('rule,index', [('ordinary', {'alpha':'012abc'}), ('task_beta', {'alpha':'012abc'}),
                                       ('ravel_verify_beta', {}), ('task_alpha', {'alpha':'/private/run'})])
def test_project_refuses_unresolved_tags(tmp_path, scheduler, rule, index):
    p = profile(tmp_path)
    (tmp_path / 'run-keys.json').write_text(json.dumps(index))
    with pytest.raises(ValueError): hc.submit(job(tmp_path, rule), profile=p)
    assert scheduler[1]() == []


def test_verify_rule_and_resource_defaults(tmp_path, scheduler):
    hc.submit(job(tmp_path, 'ravel_verify_alpha'), profile=profile(tmp_path, runtime=30, mem_mb=2048,
              runtime_attribute='+SiteWallSeconds', flavour='short', hold_grace_seconds=90))
    text = descriptor(tmp_path)
    assert '+RavelTask = "alpha"' in text and '+SiteWallSeconds = 1800' in text
    assert 'request_memory = 2048MB' in text and '+JobFlavour = "short"' in text
    assert '> 90)' in text


@pytest.mark.parametrize('options', [{'site_options': {'requirements': 'x\ny'}}, {'site_options': {'bad=key':'x'}},
    {'site_options': {'bad key':'x'}}, {'site_options': {'request_cpus':'99'}},
    {'site_options': {'GETENV':'True'}}, {'site_options': {'+RavelProject':'other'}},
    {'site_options': {'+MaxRuntime':'0'}}, {'flavour':'x\ny'}, {'runtime_attribute':'+RavelRun'},
    {'site_options': {'requirements':'x\ry'}},
    # Raw-attribute and alternate spellings of the fixed lines are the same override.
    {'site_options': {'+PeriodicRemove':'true'}}, {'site_options': {'MY.PeriodicRemove':'true'}},
    {'site_options': {'PeriodicRemove':'true'}}, {'site_options': {'my.RavelPause':'undefined'}},
    {'site_options': {'MY.RavelProject':'"other"'}}, {'site_options': {'+RavelRun':'"other"'}},
    {'site_options': {'+Environment':'""'}}, {'site_options': {'env':'A=1'}},
    {'site_options': {'+RequestCpus':'99'}}, {'site_options': {'+Iwd':'"/elsewhere"'}},
    {'site_options': {'+Cmd':'"/bin/true"'}}, {'site_options': {'+JobBatchName':'"other"'}},
    {'runtime_attribute':'+PeriodicRemove'}, {'runtime_attribute':'+Periodic_Remove'},
    {'runtime_attribute':'+RequestMemory'}, {'runtime_attribute':'+queue'}])
def test_unsafe_options_refused(tmp_path, scheduler, options):
    with pytest.raises(ValueError):
        hc.submit(job(tmp_path), profile=profile(tmp_path, **options))
    assert scheduler[1]() == []


@pytest.mark.parametrize('handoff', ['default', 'proxy', 'path'])
def test_opt_in_credential_directives_only(tmp_path, scheduler, monkeypatch, handoff):
    tool = tmp_path / 'bin/voms-proxy-info'
    tool.write_text('#!' + sys.executable + '\nprint(3600)\n')
    tool.chmod(0o700)
    proxy = tmp_path / 'proxy'; proxy.write_text('NEVER-COPY-THIS-CONTENT')
    monkeypatch.setenv('SYNTHETIC_PROXY_PATH', str(proxy))
    options = {'use_x509userproxy':True} if handoff == 'proxy' else (
        {'x509userproxy_env':'SYNTHETIC_PROXY_PATH'} if handoff == 'path' else {})
    hc.submit(job(tmp_path), profile=profile(tmp_path, **options))
    text = descriptor(tmp_path)
    assert 'NEVER-COPY-THIS-CONTENT' not in text
    assert ('use_x509userproxy = true' in text) == (handoff == 'proxy')
    assert ('x509userproxy = "' + str(proxy) + '"' in text) == (handoff == 'path')


def test_missing_proxy_environment_refused(tmp_path, scheduler):
    with pytest.raises(ValueError):
        hc.submit(job(tmp_path), profile=profile(tmp_path, x509userproxy_env='ABSENT_PROXY_PATH'))
    assert scheduler[1]() == []


@pytest.mark.parametrize('row,expected', [('5 undefined 1 undefined','running'), ('5 undefined 15 undefined','running'),
    ('5 undefined 3 true','running'), ('5 undefined 3 false','running'),
    ('5 undefined 3 undefined','failed'), ('4 0 undefined undefined','success'),
    ('4 1 undefined undefined','failed'), ('3 undefined undefined undefined','failed'),
    ('2 undefined undefined undefined','running')])
def test_condor_states(tmp_path, scheduler, row, expected):
    scheduler[0](queue=row+'\n')
    assert hc.status('1.0') == expected


@pytest.mark.parametrize('row', ['5 undefined 1 undefined', '5 undefined 15 undefined',
                                 '5 undefined 3 true', '5 undefined 34 paused by request'])
def test_project_snapshot_never_fails_or_loses_paused_and_user_held_jobs(tmp_path, scheduler, row):
    p = profile(tmp_path, missing_grace_seconds=30, status_cache_seconds=10, hold_grace_seconds=60)
    hc.submit(job(tmp_path), profile=p)
    scheduler[0](queue='12 0 ' + row + '\n')
    # Far beyond the hold, missing and cache intervals the answer stays running.
    for now in (100, 200, 10**6):
        assert hc.status('12.0', project_id='project-a', now=now) == 'running'
    assert not list(tmp_path.rglob('*.missing'))
    # The fixture PATH holds no removal or release tool; only submit and queue ran.
    assert {Path(c[0]).name for c in scheduler[1]()} == {'condor_submit', 'condor_q'}


def test_hold_removal_rule_is_written_once_and_keeps_every_exemption(tmp_path, scheduler):
    hc.submit(job(tmp_path), profile=profile(tmp_path, hold_grace_seconds=5, site_options={
        'requirements': '(Memory >= 1)', '+SiteGroup': '"group-a"'}))
    rules = [line for line in descriptor(tmp_path).splitlines() if 'remove' in line.lower()]
    assert len(rules) == 1
    for clause in ('(HoldReasonCode =!= 1)', '(HoldReasonCode =!= 15)', '(RavelPause =?= undefined)',
                   '(JobStatus == 5)', '> 5)'):
        assert clause in rules[0]


def test_unknown_missing_has_bounded_grace(tmp_path, scheduler):
    assert hc.status('1.0', now=100) == 'running'
    assert (tmp_path / '.ravel-condor/1.0.missing').read_text().strip() == '100.0'
    assert hc.status('1.0', now=699) == 'running'
    assert hc.status('1.0', now=701) == 'failed'
    scheduler[0](queue='4 undefined undefined undefined\n')
    assert hc.status('1.0', now=702) == 'failed'
    assert not (tmp_path / '.ravel-condor/1.0.missing').exists()


def test_fifty_jobs_share_one_queue_and_bounded_history_query(tmp_path, scheduler):
    # Known submitted ids enter the registry before the first status sweep.
    p = profile(tmp_path)
    for i in range(50):
        scheduler[0](submit=f'{i+1}.0\n')
        hc.submit(job(tmp_path), profile=p)
    scheduler[0](queue=''.join(f'{i+1} 0 2 undefined undefined undefined\n' for i in range(49)),
                 history='50 0 4 0 undefined undefined\n')
    for i in range(50):
        assert hc.status(f'{i+1}.0', project_id='project-a', now=100) == ('success' if i == 49 else 'running')
    calls = scheduler[1]()
    q = [c for c in calls if Path(c[0]).name == 'condor_q']
    h = [c for c in calls if Path(c[0]).name == 'condor_history']
    assert len(q) == len(h) == 1
    assert q[0][1:3] == ['-constraint', 'RavelProject == "project-a"']
    assert '-limit' in h[0]
    assert int(h[0][h[0].index('-limit')+1]) <= 1000
    hc.status('1.0', project_id='project-a', now=121)
    assert len([c for c in scheduler[1]() if Path(c[0]).name == 'condor_q']) == 2


def test_history_answers_are_recorded_and_not_queried_again(tmp_path, scheduler):
    p = profile(tmp_path, status_cache_seconds=10)
    for job_id in ('1.0', '2.0'):
        scheduler[0](submit=job_id + '\n')
        hc.submit(job(tmp_path), profile=p)
    scheduler[0](queue='2 0 2 undefined undefined undefined\n', history='1 0 4 0 undefined undefined\n')
    assert hc.status('1.0', project_id='project-a', now=100) == 'success'
    assert hc.status('2.0', project_id='project-a', now=120) == 'running'
    assert hc.status('1.0', project_id='project-a', now=140) == 'success'
    calls = [Path(c[0]).name for c in scheduler[1]()]
    assert calls.count('condor_q') == 3 and calls.count('condor_history') == 1
    # A reused id is a new job: its recorded answer is dropped at submission.
    scheduler[0](submit='1.0\n', queue='', history='')
    hc.submit(job(tmp_path), profile=p)
    assert hc.status('1.0', project_id='project-a', now=141) == 'running'


def test_lost_job_fails_after_grace_and_leaves_later_sweeps_without_history(tmp_path, scheduler):
    p = profile(tmp_path, missing_grace_seconds=30, status_cache_seconds=10)
    for job_id in ('1.0', '2.0'):
        scheduler[0](submit=job_id + '\n')
        hc.submit(job(tmp_path), profile=p)
    scheduler[0](queue='2 0 2 undefined undefined undefined\n')
    assert hc.status('1.0', project_id='project-a', now=100) == 'running'
    assert hc.status('1.0', project_id='project-a', now=131) == 'failed'
    before = [Path(c[0]).name for c in scheduler[1]()].count('condor_history')
    assert hc.status('2.0', project_id='project-a', now=150) == 'running'
    assert hc.status('1.0', project_id='project-a', now=170) == 'failed'
    assert [Path(c[0]).name for c in scheduler[1]()].count('condor_history') == before


def test_complete_queue_needs_no_history(tmp_path, scheduler):
    scheduler[0](queue='1 0 2 undefined undefined undefined\n')
    assert hc.status('1.0', project_id='project-a', now=100) == 'running'
    assert len(scheduler[1]()) == 1


def test_separate_shared_log_directories_and_environment(tmp_path, scheduler, monkeypatch):
    monkeypatch.setenv('RAVEL_TEST_MODE', 'synthetic')
    monkeypatch.setenv('UNRELATED_VARIABLE', 'not-in-job')
    log = tmp_path / 'logs'; out = tmp_path / 'stdout'; err = tmp_path / 'stderr'
    hc.submit(job(tmp_path), profile=profile(tmp_path, log_dir=str(log), output_dir=str(out),
              error_dir=str(err), analysis_bin='/opt/analysis/bin', ravel_env=['RAVEL_TEST_MODE']))
    text = descriptor(tmp_path)
    assert str(log) in text and str(out) in text and str(err) in text
    assert 'PATH=/opt/analysis/bin:/usr/bin:/bin' in text
    assert 'RAVEL_TEST_MODE=synthetic' in text and 'UNRELATED_VARIABLE' not in text
    assert hc.status('12.0', project_id='project-a', now=10) == 'running'
    assert (log / '12.0.missing').exists()


def test_console_commands_release_status_and_rate():
    p = render('htcondor', project_id='project-a')
    assert p['config']['cluster-generic-submit-cmd'] == 'ravel-submit.sh'
    assert p['config']['cluster-generic-status-cmd'] == 'ravel-status.sh'
    assert '--project-id project-a' in p['scripts']['ravel-status.sh']
    assert p['release_status'] == 'tester-qualification' and p['qualified'] is False
    assert 'awaits site qualification' in p['label']
    # One sweep per snapshot interval; per-job calls inside a sweep read the snapshot
    # and are not throttled to one job per interval.
    assert p['config']['seconds-between-status-checks'] == 20
    assert p['config']['max-status-checks-per-second'] >= 1
    assert render('htcondor', options={'status_cache_seconds': 45})['config']['seconds-between-status-checks'] == 45
    assert 'snakemake-executor-plugin-cluster-generic' in p['requirements']
    assert 'snakemake-interface-executor-plugins>=9.3.2,<10' in p['requirements']


def test_status_import_is_light_and_fast():
    code = '''import sys,time,json
start=time.perf_counter()
from ravel.workflow.site_profiles.htcondor import status_main
print(json.dumps({'seconds':time.perf_counter()-start,'heavy':[m for m in sys.modules if m.startswith(('ravel.physics','numpy'))]}))'''
    result = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True, check=True)
    measured = json.loads(result.stdout)
    print('status import seconds:', measured['seconds'])
    assert measured['seconds'] < .3 and measured['heavy'] == []


def test_slurm_withheld_and_writer_pins(tmp_path):
    from ravel.workflow.site_profiles import write_profile
    with pytest.raises(ValueError, match='not available in this release'): render('slurm')
    assert [p['name'] for p in write_profiles(tmp_path/'all')] == ['local','htcondor']
    assert not (tmp_path/'all/slurm').exists()
    result = write_profile(tmp_path/'one', 'htcondor', cores=2, jobs=50, project_id='project-a')
    assert result['profile']['config']['jobs'] == 50
    assert Path(result['path']).is_dir()
    for row in result['files']:
        assert hashlib.sha256(Path(row['path']).read_bytes()).hexdigest() == row['sha256']
    assert {Path(r['path']).name for r in result['files']} == {'config.yaml','profile.json','ravel-submit.sh','ravel-status.sh'}


@pytest.mark.parametrize('project_id', ['bad/name', 'bad name', '', 'x'*65, 'bad\nname'])
def test_bad_project_id_refused(project_id):
    with pytest.raises(ValueError): render('htcondor', project_id=project_id)


def test_invalid_job_id_never_invokes_scheduler(tmp_path, scheduler):
    with pytest.raises(ValueError): hc.status('1.0; unsafe')
    assert scheduler[1]() == []


def test_real_cluster_generic_profile_requires_executor_plugin():
    if importlib.util.find_spec('snakemake_executor_plugin_cluster_generic') is None:
        pytest.skip('Snakemake 9.27.0 test environment has no cluster-generic executor plugin; real site qualification is required')
    pytest.skip('Real scheduler qualification is queued by the site owner; this suite uses inert commands only')


def test_rendered_commands_accept_workflow_formatting_and_relocation(tmp_path, scheduler):
    from ravel.workflow.site_profiles import write_profile
    import shutil
    p = profile(tmp_path, status_cache_seconds=45, site_options={'+queue': '"short"'})
    exported = write_profile(tmp_path / 'original', 'htcondor', project_id=p['project_id'], options=p['options'])
    relocated = tmp_path / 'relocated profile'
    shutil.move(exported['path'], relocated)
    script = job(tmp_path)
    from ravel.workflow import wms_policy
    # A facility submission runs only from inside a live governed launch (SW12).
    with wms_policy.launch_authorization(tmp_path, 'alpha', 1, {'alpha': 'a' * 64}):
        for key, entry, target, command in [
                ('cluster-generic-submit-cmd', 'submit_main', str(script), 'submit'),
                ('cluster-generic-status-cmd', 'status_main', '12.0', 'status')]:
            tool = tmp_path / 'bin' / ('ravel-wms-condor-' + command)
            tool.write_text(f'#!{sys.executable}\nfrom ravel.workflow.site_profiles.htcondor import {entry}\nraise SystemExit({entry}())\n')
            tool.chmod(0o755)
            wrapper = relocated / p['config'][key].format(jobid='12.0')
            result = subprocess.run([str(wrapper), target], capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
    assert '+queue = "short"' in descriptor(tmp_path)
    index = json.loads((tmp_path / '.ravel-condor/project-project-a.jobs.json').read_text())
    assert index['options'] == p['options']


def test_batch_name_and_maximum_length_tags(tmp_path, scheduler):
    task, run, project = 'a'*64, 'b'*64, 'c'*64
    p = render('htcondor', project_id=project, options={'workflow_dir':str(tmp_path)})
    (tmp_path / 'run-keys.json').write_text(json.dumps({task:run}))
    hc.submit(job(tmp_path, 'task_'+task), profile=p)
    batch = next(line for line in descriptor(tmp_path).splitlines() if line.startswith('batch_name ='))
    assert len(batch.split(' = ')[1].strip('"')) <= 64


def test_status_cache_refresh_missing_grace_and_job_reappearance(tmp_path, scheduler):
    p = profile(tmp_path, missing_grace_seconds=30, status_cache_seconds=10)
    hc.submit(job(tmp_path), profile=p)
    assert hc.status('12.0', project_id='project-a', now=100) == 'running'
    assert hc.status('12.0', project_id='project-a', now=131) == 'failed'
    scheduler[0](queue='12 0 2 undefined undefined undefined\n')
    assert hc.status('12.0', project_id='project-a', now=142) == 'running'
    assert not (tmp_path / '.ravel-condor/12.0.missing').exists()


def test_site_options_and_disk_resource(tmp_path, scheduler):
    hc.submit(job(tmp_path, resources={'disk_mb':1200}), profile=profile(tmp_path,
              site_options={'requirements':'(Memory >= 2048)', '+SiteGroup':'"group-a"'}))
    text = descriptor(tmp_path)
    assert 'request_disk = 1200MB' in text and 'requirements = (Memory >= 2048)' in text
    assert '+SiteGroup = "group-a"' in text


@pytest.mark.parametrize('resource,value', [('runtime',0),('runtime',-1),('runtime',True),
                                          ('mem_mb', '4000'),('disk_mb',-1)])
def test_bad_resources_refused(tmp_path, scheduler, resource, value):
    with pytest.raises(ValueError): hc.submit(job(tmp_path, resources={resource:value}), profile=profile(tmp_path))
    assert scheduler[1]() == []


def test_status_samples_cache_clock_after_acquiring_project_lock(tmp_path, scheduler, monkeypatch):
    scheduler[0](queue='1 0 2 undefined undefined undefined\n')
    assert hc.status('1.0', project_id='project-a', now=101) == 'running'
    clock = [100]
    original_lock = hc._lock

    @contextmanager
    def delayed_lock(directory, project):
        with original_lock(directory, project) as key:
            # Another caller published at 101 while this caller was waiting.
            clock[0] = 102
            yield key

    monkeypatch.setattr(hc.time, 'time', lambda: clock[0])
    monkeypatch.setattr(hc, '_lock', delayed_lock)
    assert hc.status('1.0', project_id='project-a') == 'running'
    assert len(scheduler[1]()) == 1


def test_parallel_status_processes_share_snapshot(tmp_path, scheduler):
    scheduler[0](queue=''.join(f'{i} 0 2 undefined undefined undefined\n' for i in range(1,9)))
    # Keep every reader in the same cache interval regardless of process startup time.
    code = 'import sys; from ravel.workflow.site_profiles.htcondor import status; print(status(sys.argv[1],project_id="project-a",now=100))'
    processes = [subprocess.Popen([sys.executable,'-B','-c',code,f'{i}.0'], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) for i in range(1,9)]
    for proc in processes:
        out, err = proc.communicate(timeout=20)
        assert proc.returncode == 0 and out.strip() == 'running', err
    assert len(scheduler[1]()) == 1


def test_scheduler_instructions_and_packaged_scripts():
    import tomllib
    from workflow_instruction_inventory_fixture import assert_scheduler_profile_instruction
    project = Path(__file__).resolve().parents[2]
    assert_scheduler_profile_instruction(project)
    scripts = tomllib.loads((project / 'pyproject.toml').read_text())['project']['scripts']
    assert scripts['ravel-wms-condor-submit'] == 'ravel.workflow.site_profiles.htcondor:submit_main'
    assert scripts['ravel-wms-condor-status'] == 'ravel.workflow.site_profiles.htcondor:status_main'


@pytest.mark.parametrize('key', ['+queue', '+Queue', '+QUEUE'])
def test_declared_custom_queue_attribute(tmp_path, scheduler, key):
    hc.submit(job(tmp_path), profile=profile(tmp_path, site_options={key: '"short"'}))
    text = descriptor(tmp_path)
    assert key + ' = "short"' in text
    assert text.splitlines()[-1] == 'queue 1'


@pytest.mark.parametrize('key', ['queue', 'QUEUE', 'MY.Queue', 'que_ue', '+que_ue', '+Executable',
                               '+Environment', '+RequestCpus', '+RavelPause'])
def test_queue_statement_and_other_protected_fields_stay_protected(tmp_path, scheduler, key):
    with pytest.raises(ValueError):
        hc.submit(job(tmp_path), profile=profile(tmp_path, site_options={key: '"short"'}))
    assert scheduler[1]() == []


@pytest.mark.parametrize('code,stderr,stdout', [(0, 'warning retained', '12.0\n'),
    (1, 'ERROR: rejected submit policy', ''), (0, '', 'invalid response')])
def test_kept_submit_diagnostics_survive_scratch_cleanup(tmp_path, scheduler, code, stderr, stdout):
    scheduler[0](code=code, stderr=stderr, submit=stdout)
    scratch = tmp_path / 'scratch'; scratch.mkdir()
    script = job(scratch)
    p = profile(tmp_path)
    if code or stdout == 'invalid response':
        with pytest.raises(ValueError, match=stderr or 'invalid response'):
            hc.submit(script, profile=p)
    else:
        assert hc.submit(script, profile=p) == '12.0'
    import shutil
    shutil.rmtree(scratch)
    receipt = next((tmp_path / '.ravel-condor/submissions').glob('submit-*/receipt.json'))
    record = json.loads(receipt.read_text())
    assert Path(record['submit_file']).read_text().endswith('queue 1\n')
    assert Path(record['stdout']).read_text() == stdout
    assert Path(record['stderr']).read_text() == stderr
    assert record['exit_code'] == code
    assert bool(record['error']) == (code != 0 or stdout == 'invalid response')


def test_submit_diagnostics_are_bounded_and_attempts_are_never_overwritten(tmp_path, scheduler):
    scheduler[0](code=1, stderr='ERROR: refused\n' + 'x' * (hc.RECORD_LIMIT * 2))
    for _ in range(2):
        with pytest.raises(ValueError, match='ERROR: refused'):
            hc.submit(job(tmp_path), profile=profile(tmp_path))
    records = list((tmp_path / '.ravel-condor/submissions').glob('submit-*/receipt.json'))
    assert len(records) == 2
    for path in records:
        record = json.loads(path.read_text())
        assert record['truncated']['stderr'] is True
        assert Path(record['stderr']).stat().st_size == hc.RECORD_LIMIT


def test_record_budget_refuses_before_submission(tmp_path, scheduler, monkeypatch):
    monkeypatch.setattr(hc, 'MAX_SUBMIT_RECORDS', 1)
    hc.submit(job(tmp_path), profile=profile(tmp_path))
    with pytest.raises(ValueError, match='record limit'):
        hc.submit(job(tmp_path), profile=profile(tmp_path))
    assert len(scheduler[1]()) == 1



def test_submit_cli_surfaces_refusal_and_record_path(tmp_path, scheduler, capsys):
    scheduler[0](code=1, stderr='ERROR: diagnostic for agent', submit='')
    from ravel.workflow import wms_policy
    with wms_policy.launch_authorization(tmp_path, 'alpha', 1, {'alpha': 'a' * 64}), pytest.raises(SystemExit) as exc:
        hc.submit_main(['--options-json', json.dumps(profile(tmp_path)['options']), str(job(tmp_path))])
    assert exc.value.code == 1
    output = capsys.readouterr()
    assert not output.out
    assert 'diagnostic for agent' in output.err and 'submit records:' in output.err


def test_large_warning_does_not_turn_success_into_refusal(tmp_path, scheduler):
    scheduler[0](stderr='warning ' * hc.RECORD_LIMIT)
    assert hc.submit(job(tmp_path), profile=profile(tmp_path)) == '12.0'
    receipt = next((tmp_path / '.ravel-condor/submissions').glob('submit-*/receipt.json'))
    record = json.loads(receipt.read_text())
    assert record['truncated']['stderr'] and record['error'] is None


def test_missing_submit_executable_keeps_descriptor_and_error(tmp_path, scheduler):
    (tmp_path / 'bin/condor_submit').unlink()
    with pytest.raises(ValueError, match='condor_submit failed'):
        hc.submit(job(tmp_path), profile=profile(tmp_path))
    receipt = next((tmp_path / '.ravel-condor/submissions').glob('submit-*/receipt.json'))
    record = json.loads(receipt.read_text())
    assert record['exit_code'] is None and 'No such file' in record['error']
    assert Path(record['submit_file']).is_file()


def test_timeout_keeps_submit_record(tmp_path, scheduler, monkeypatch):
    ticks = iter((0, 21))
    monkeypatch.setattr(hc.time, 'monotonic', lambda: next(ticks, 21))
    with pytest.raises(ValueError, match='timed out'):
        hc.submit(job(tmp_path), profile=profile(tmp_path))
    receipt = next((tmp_path / '.ravel-condor/submissions').glob('submit-*/receipt.json'))
    record = json.loads(receipt.read_text())
    assert record['error'] and Path(record['submit_file']).is_file()
    assert all(Path(record[name]).is_file() for name in ('stdout', 'stderr'))


def test_oversized_submit_description_refuses_before_scheduler(tmp_path, scheduler):
    with pytest.raises(ValueError, match='64 KiB'):
        hc.submit(job(tmp_path), profile=profile(tmp_path, site_options={'+SiteText': 'x' * hc.RECORD_LIMIT}))
    assert scheduler[1]() == []
