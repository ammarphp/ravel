"""One study per Slurm allocation: the request, its approval binding, the sbatch script and the in-job run."""
import json
from pathlib import Path
import sys

import pytest

from ravel.workflow import allocation_study as al
from ravel.workflow import machine_lease as ml
from ravel.workflow import site_doctor

sys.path.insert(0, str(Path(__file__).parent))
import test_checkin2_gate as gate  # noqa: E402

RES = dict(account='lab-account', partition='standard', cpus=4, minutes=30)


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


def test_a_planning_request_writes_a_quoted_script_without_memory(tmp_path, venv):
    root = _planning_run(tmp_path)
    directory = al.prepare(root, ['claude', '-p', "read docs/workflow/start.md; don't approve"], venv=venv,
                           checkout=tmp_path, prefix='/vast/p/linux-x/prefix', modules=['apptainer/1.4.1'],
                           env=['RAVEL_LEASE_WAIT_SECONDS=60'], claude_config_dir='/net/homes/u/.claude-ravel',
                           **RES)
    request = json.loads((directory / 'request.json').read_text())
    assert request['rung'] == 'none' and request['binding'] is None and request['approval_files'] == {}
    assert request['run']['source'] == 'path' and request['run']['run_id'].startswith('path-')
    assert request['agent']['argv'][2] == "read docs/workflow/start.md; don't approve"
    script = (directory / 'study.sbatch').read_text()
    assert '#SBATCH --cpus-per-task=4' in script and '#SBATCH --account=lab-account' in script
    assert '--mem' not in script
    assert 'module load apptainer/1.4.1' in script and 'export RAVEL_NATIVE_BUILD=/vast/p/linux-x/prefix' in script
    assert 'export CLAUDE_CONFIG_DIR=/net/homes/u/.claude-ravel' in script
    assert 'RAVEL_JOBS="${SLURM_CPUS_PER_TASK:-1}"' in script
    assert script.rstrip().endswith(f"-m ravel site study-job run --request {directory / 'request.json'}")
    assert directory.parent == root / al.REQUESTS


def test_a_heavy_rung_without_approval_is_refused_before_anything_is_written(tmp_path, venv):
    root = _planning_run(tmp_path)
    with pytest.raises(ValueError, match='no approval for the smoke rung'):
        al.prepare(root, ['agent'], venv=venv, checkout=tmp_path, rung='smoke', **RES)
    assert not (root / al.REQUESTS).exists()


def test_an_approved_rung_carries_its_binding_and_a_changed_approval_refuses_submission(tmp_path, venv):
    root = _approved_run(tmp_path)
    directory = al.prepare(root, ['agent'], venv=venv, checkout=tmp_path, rung='smoke', **RES)
    request = json.loads((directory / 'request.json').read_text())
    assert request['binding'] == {'rundir': str(root.resolve()), 'node_id': al.NODE, 'route': 'checkin1',
                                  'rung': 'smoke'}
    assert set(request['approval_files']) == {'inputs/checkin1_approval.json', 'inputs/task_contract.json'}
    approval = root / 'inputs/checkin1_approval.json'
    approval.write_text(approval.read_text().replace('Yes, run the plan', 'Yes, run the plan!'))
    sbatch = tmp_path / 'sbatch'
    sbatch.write_text('#!/bin/sh\necho submitted >> "$0.calls"; echo 77\n')
    sbatch.chmod(0o755)
    with pytest.raises(ValueError):
        al.submit(directory, sbatch=str(sbatch))
    assert not (tmp_path / 'sbatch.calls').exists() and not (directory / 'submission.json').exists()


def test_submission_records_the_job_id(tmp_path, venv):
    root = _planning_run(tmp_path)
    directory = al.prepare(root, ['agent'], venv=venv, checkout=tmp_path, **RES)
    sbatch = tmp_path / 'sbatch'
    sbatch.write_text('#!/bin/sh\necho "$@" > "$0.args"; echo "9100001;clustera"\n')
    sbatch.chmod(0o755)
    assert al.submit(directory, sbatch=str(sbatch)) == '9100001'
    assert (tmp_path / 'sbatch.args').read_text().split() == ['--parsable', str(directory / 'study.sbatch')]
    assert json.loads((directory / 'submission.json').read_text())['job_id'] == '9100001'


@pytest.mark.parametrize('pair', ['ANTHROPIC_API_KEY=x', 'GH_TOKEN=x', 'MY_PASSWORD=x', 'novalue'])
def test_credentials_and_malformed_variables_are_refused(tmp_path, venv, pair):
    with pytest.raises(ValueError):
        al.prepare(_planning_run(tmp_path), ['agent'], venv=venv, checkout=tmp_path, env=[pair], **RES)


@pytest.mark.parametrize('change', [dict(account='a b'), dict(cpus=0), dict(minutes=0), dict(modules=['x; rm'])])
def test_unsafe_resource_words_are_refused(tmp_path, venv, change):
    with pytest.raises(ValueError):
        al.prepare(_planning_run(tmp_path), ['agent'], venv=venv, checkout=tmp_path, **(RES | change))


def test_collection_inside_the_study_is_refused(tmp_path, venv):
    root = _planning_run(tmp_path)
    with pytest.raises(ValueError, match='outside the study'):
        al.prepare(root, ['agent'], venv=venv, checkout=tmp_path, collect_to=str(root / 'copy'), **RES)


def test_the_job_refuses_outside_an_allocation(tmp_path, venv, monkeypatch):
    directory = al.prepare(_planning_run(tmp_path), ['agent'], venv=venv, checkout=tmp_path, **RES)
    monkeypatch.setattr(ml, 'slurm_allocation', lambda *a, **k: None)
    with pytest.raises(ValueError, match='not inside a Slurm allocation'):
        al.run(directory / 'request.json')


def test_the_job_runs_the_agent_in_the_study_records_the_allocation_and_collects(tmp_path, venv, monkeypatch):
    root = _planning_run(tmp_path)
    agent = [sys.executable, '-c', 'import os,pathlib;pathlib.Path("agent-was-here").write_text('
             'os.environ["RAVEL_RUN_ID"]+" "+os.environ["RAVEL_ALLOCATION_RUNG"]);print("stub agent")']
    collect = tmp_path / 'collected'
    directory = al.prepare(root, agent, venv=venv, checkout=tmp_path, collect_to=str(collect), **RES)
    monkeypatch.setattr(ml, 'slurm_allocation', lambda *a, **k: {'cluster': 'clustera', 'job_id': '9100002'})
    monkeypatch.setattr(ml, 'allocation_identity', lambda: {'scope': 'slurm-clustera-9100002', 'job_id': '9100002'})
    request = json.loads((directory / 'request.json').read_text())
    assert al.run(directory / 'request.json') == 0
    assert (root / 'agent-was-here').read_text() == request['run']['run_id'] + ' none'
    receipt = json.loads((root / 'logs/allocations/slurm-clustera-9100002/allocation.json').read_text())
    assert receipt['state'] == 'finished' and receipt['agent_exit'] == 0
    assert receipt['allocation']['job_id'] == '9100002' and receipt['run'] == request['run']
    assert 'stub agent' in (root / 'logs/allocations/slurm-clustera-9100002/agent.log').read_text()
    copy = collect / f"{root.name}-{request['run']['run_id']}"
    assert receipt['collected_to'] == str(copy) and (copy / 'agent-was-here').is_file()
    assert (copy / 'logs/allocations/slurm-clustera-9100002/allocation.json').is_file()


def test_the_job_refuses_when_the_run_identity_changed(tmp_path, venv, monkeypatch):
    root = _planning_run(tmp_path)
    directory = al.prepare(root, ['agent'], venv=venv, checkout=tmp_path, **RES)
    request = json.loads((directory / 'request.json').read_text())
    request['run']['run_id'] = 'path-0000'
    (directory / 'request.json').write_text(json.dumps(request))
    monkeypatch.setattr(ml, 'slurm_allocation', lambda *a, **k: {'cluster': 'clustera', 'job_id': '1'})
    with pytest.raises(ValueError, match='another run'):
        al.run(directory / 'request.json')


def test_the_site_command_dry_run(tmp_path, venv, capsys):
    root = _planning_run(tmp_path)
    code = site_doctor.main(['study-job', 'submit', '--rundir', str(root), '--account', 'a', '--partition', 'p',
                             '--cpus', '2', '--time', '10', '--venv', str(venv), '--checkout', str(tmp_path),
                             '--dry-run', '--', 'claude', '-p', 'hello'])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert 'job_id' not in out and Path(out['script']).is_file()
    assert json.loads(Path(out['request']).read_text())['agent']['argv'] == ['claude', '-p', 'hello']
    assert site_doctor.main(['study-job', 'submit', '--rundir', str(root), '--account', 'a', '--partition', 'p',
                             '--cpus', '2', '--time', '10', '--venv', str(venv), '--checkout', str(tmp_path),
                             '--rung', 'full', '--dry-run', '--', 'claude']) == 2


def test_a_heavy_rung_needs_the_runs_steering_custody(tmp_path, venv, monkeypatch):
    from ravel.workflow import gate_wiring
    root = _approved_run(tmp_path)
    monkeypatch.setattr(gate_wiring, '_test_lock_domain', lambda: False)
    with pytest.raises(ValueError, match='steering custody is absent'):
        al.prepare(root, ['agent'], venv=venv, checkout=tmp_path, rung='smoke', **RES)
    gate_wiring.initialize_steering(root, route='operator')
    assert al.prepare(root, ['agent'], venv=venv, checkout=tmp_path, rung='smoke', **RES).is_dir()


def test_two_studies_with_one_directory_name_are_collected_apart(tmp_path, venv, monkeypatch):
    monkeypatch.setattr(ml, 'slurm_allocation', lambda *a, **k: {'cluster': None, 'job_id': '9100004'})
    monkeypatch.setattr(ml, 'allocation_identity', lambda: None)
    collect, copies = tmp_path / 'collected', set()
    for name in ('a', 'b'):
        root = _planning_run(tmp_path / name)
        directory = al.prepare(root, [sys.executable, '-c', f'open("mine","w").write("{name}")'], venv=venv,
                               checkout=tmp_path, collect_to=str(collect), **RES)
        assert al.run(directory / 'request.json') == 0
        receipt = json.loads((root / 'logs/allocations/slurm-9100004/allocation.json').read_text())
        copies.add(receipt['collected_to'])
        assert (Path(receipt['collected_to']) / 'mine').read_text() == name
    assert len(copies) == 2
