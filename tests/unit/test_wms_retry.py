"""Parallel workflow-manager fan-out of partitions and RAVEL-level bounded retries.

Synthetic fake-reader fixture only: no ROOT, site, scheduler or physics qualification.
Scheduler commands are fakes on a temporary PATH; real Snakemake runs only on
synthetic exports under the test directory when RAVEL_TEST_SNAKEMAKE is set.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import pytest
from ravel.physics import root_stream as s, root_stream_partitions as p
from ravel.workflow import science, site_workflow, wms_retry, machine_lease, research_cycle as cycle
from ravel.workflow.state_io import read_json, atomic_json
from root_stream_fixture import put, pin
from root_partition_ordinary_fixture import prepare_fixture, ordinary, contract, WRAPPER
from method_decision_fixture import admit_method

WMS = {'engine': 'snakemake', 'version': '9.27.0', 'retries': 0}


def local(cores=1, jobs=1):
    return {**WMS, 'profile': 'local', 'cores': cores, 'jobs': jobs, 'remote_ceiling': 1}


def source(tmp_path, monkeypatch, *, background_entries=None, seconds=400, fail_reader=False):
    """The ordinary partition fixture with a larger time ceiling and, optionally, more entries."""
    root = tmp_path / 'source'
    ds, a, cfg, spec, proof = prepare_fixture(root, monkeypatch, fail_reader=fail_reader)
    if background_entries is not None:
        sample = ds['samples'][0]; sample['members'][0]['entries'] = background_entries
        original = read_json(sample['normalization']['original_population']['path'])
        original['members'][0]['entries'] = background_entries
        sample['normalization']['original_population'] = put(root, 'large-original.json', original)
        normalization = read_json(sample['normalization']['source']['path'])
        normalization['original_population_sha256'] = sample['normalization']['original_population']['sha256']
        sample['normalization']['source'] = put(root, 'large-normalization.json', normalization)
        ds['membership_authority'] = put(root, 'large-members.json', {'schema_version': 1, 'samples': ds['samples']})
        cfg['dataset'] = put(root, 'large-dataset.json', ds)
    cfg['limits'].update(max_seconds=seconds, max_chunks=1000)
    value = read_json(spec['path']); value['task']['config'] = put(root, 'scaled-config.json', cfg); value['max_seconds'] = seconds
    owner = contract(root); owner['budget'].update(wall_seconds=10000, native_attempts=1000)
    cycle.create(root / 'scaled-cycle', owner, base_dir=root, evaluation_harness=True)
    return root, ds, a, put(root, 'scaled-spec.json', value), proof


def request(root, spec, proof, *, entries, budget, fanout=None):
    value = {'schema_version': 1, 'specification': spec, 'partition_entries': entries, 'max_partitions': 200,
             'grouping': {'kind': 'independent_entries', 'source': proof, 'statement': 'Pinned synthetic independent entry premise'},
             'owner': {'kind': 'research_cycle', 'cycle': str(root / 'scaled-cycle')}, 'budget': budget}
    if fanout is not None:
        value['fanout'] = fanout
    return value


def export_request(root, a, proof, tasks, wms, fanin=None):
    blind = put(root, 'export-policy.json', {'schema_version': 1, 'policy': 'exclude_signal_region_data_from_model_and_analysis',
                                            'review_source': proof, 'original_domain': a['blinding']['source']})
    value = {'schema_version': 1, 'site_id': 'synthetic-fanout', 'python': pin(sys.executable), 'tasks': tasks,
             'audit': {'prompts': [proof], 'model_build': 'none-pure-software', 'timestamps': ['2026-10-09T00:00:00Z'],
                       'token_accounting': proof, 'environment': proof, 'tracked_skill_sources': [proof], 'blinding_policy': blind},
             'wms': wms}
    if fanin is not None:
        value['fanin'] = fanin
    return value


def task_row(identity, rd):
    return {'id': identity, 'rundir': str(rd), 'plan': pin(rd / science.PLAN), 'owner': {'kind': 'ordinary'}, 'depends_on': []}


# ---------------------------------------------------------------- 1. bounded profile and the lease

def test_local_cores_above_the_host_lease_are_refused_naming_the_lease(monkeypatch):
    monkeypatch.delattr(machine_lease, 'slots', raising=False)
    with pytest.raises(ValueError, match='machine lease'):
        site_workflow.validate_wms(local(cores=4, jobs=4))
    monkeypatch.setattr(machine_lease, 'slots', lambda: 2, raising=False)
    assert site_workflow.validate_wms(local(cores=2, jobs=2))['cores'] == 2
    with pytest.raises(ValueError, match='machine lease'):
        site_workflow.validate_wms(local(cores=4, jobs=4))


def test_snakemake_retries_are_refused_and_name_the_ravel_retry_route():
    for wms in ({**local(), 'retries': 1}, {'engine': 'snakemake', 'version': '9.27.0', 'cores': 1, 'retries': 1}):
        with pytest.raises(ValueError, match='ravel wms retry'):
            site_workflow.validate_wms(wms)


def test_remote_jobs_are_bounded_by_the_owner_set_remote_ceiling(monkeypatch):
    monkeypatch.setenv('RAVEL_REMOTE_JOB_CEILING', '4')
    remote = {**WMS, 'profile': 'htcondor', 'cores': 64, 'jobs': 4, 'remote_ceiling': 4}
    assert site_workflow.validate_wms(remote)['jobs'] == 4
    for change in ({'jobs': 5}, {'remote_ceiling': 8, 'jobs': 8}):
        with pytest.raises(ValueError, match='remote ceiling'):
            site_workflow.validate_wms({**remote, **change})
    with pytest.raises(ValueError, match='profile'):
        site_workflow.validate_wms({**remote, 'profile': 'cloud'})


def test_legacy_one_core_profile_keeps_its_original_meaning():
    legacy = {'engine': 'snakemake', 'version': '9.27.0', 'cores': 1, 'retries': 0}
    assert site_workflow.validate_wms(legacy) == legacy
    assert site_workflow.wms_profile(legacy) == {'profile': 'local', 'cores': 1, 'jobs': 1, 'remote_ceiling': 1}


# ---------------------------------------------------------------- 2. fan-out shown at CHECK-IN 1, bound to approval

def test_fanout_is_shown_at_checkin_and_a_changed_jobs_value_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_REMOTE_JOB_CEILING', '8')
    root, ds, a, spec, proof = source(tmp_path, monkeypatch)
    plan = {'max_attempts': 2, 'wms': {'profile': 'htcondor', 'cores': 8, 'jobs': 4, 'remote_ceiling': 8}}
    prepared = p.prepare(request(root, spec, proof, entries=5, budget={'partition_seconds': 20, 'merge_seconds': 20,
                         'max_total_seconds': 140}, fanout=plan), root, tmp_path / 'master')
    part = prepared['partition_specifications'][0]; rd = tmp_path / 'partition'
    science.plan(rd, part['specification']['path']); admit_method(rd)
    section = read_json(rd / 'inputs/checkin1.json')['sections']['partition_fanout']
    assert {k: section[k] for k in ('partitions', 'max_attempts', 'profile', 'cores', 'jobs', 'remote_ceiling', 'workflow_manager_retries')} == \
        {'partitions': 3, 'max_attempts': 2, 'profile': 'htcondor', 'cores': 8, 'jobs': 4, 'remote_ceiling': 8, 'workflow_manager_retries': 0}
    # The fan-out is in the master, which the branch configuration pins: any change is a new plan digest.
    config = read_json(read_json(rd / science.SPEC)['task']['config']['path'])
    assert config['partitioning']['master'] == prepared['master']
    assert read_json(prepared['master']['path'])['fanout'] == plan
    science.approve(rd, 'Synthetic scripted assent; not expert review', scripted=True)
    approved = {**WMS, **plan['wms']}
    exported = site_workflow.export(export_request(root, a, proof, [task_row('part', rd)], approved), root, tmp_path / 'wms')
    assert exported['wms_profile']['jobs'] == 4 and '--jobs' in exported['wms_argv']
    stale = {**approved, 'jobs': 8}
    with pytest.raises(ValueError, match='fan-out approved at CHECK-IN 1'):
        site_workflow.export(export_request(root, a, proof, [task_row('part', rd)], stale), root, tmp_path / 'stale')
    assert not (tmp_path / 'stale').exists()
    # A self-consistent export carrying the changed profile still refuses at run-step.
    forged = tmp_path / 'forged'; forged.mkdir(); (forged / 'completed').mkdir()
    document = read_json(exported['manifest']['path']); document['wms'] = stale
    manifest = s.write_new(forged / 'workflow.json', document)
    (forged / 'Snakefile').write_bytes(site_workflow._snakefile(forged / 'workflow.json', document))
    s.write_new(forged / 'export-closure.json', {'schema_version': 1, 'files': [manifest, pin(forged / 'Snakefile')]})
    with pytest.raises(ValueError, match='fan-out approved at CHECK-IN 1'):
        site_workflow.run_step(manifest['path'], 'part', manifest['sha256'])
    assert science.execution.load_execution(rd)['stages'].get('science') is None


def test_retry_budget_must_cover_every_bounded_attempt(tmp_path, monkeypatch):
    root, ds, a, spec, proof = source(tmp_path, monkeypatch)
    plan = {'max_attempts': 2, 'wms': {'profile': 'local', 'cores': 1, 'jobs': 1, 'remote_ceiling': 1}}
    with pytest.raises(ValueError, match='every bounded attempt'):
        p.prepare(request(root, spec, proof, entries=5, budget={'partition_seconds': 20, 'merge_seconds': 20,
                  'max_total_seconds': 80}, fanout=plan), root, tmp_path / 'master')


# ---------------------------------------------------------------- 3. 50 partition rules and one merge rule

def test_fifty_partition_master_exports_fifty_rules_and_one_merge_rule(tmp_path, monkeypatch):
    root, ds, a, spec, proof = source(tmp_path, monkeypatch, background_entries=43)
    prepared = p.prepare(request(root, spec, proof, entries=1, budget={'partition_seconds': 2, 'merge_seconds': 2,
                         'max_total_seconds': 150}), root, tmp_path / 'master')
    assert len(prepared['partition_specifications']) == 50
    tasks = []
    for i, part in enumerate(prepared['partition_specifications']):
        rd = tmp_path / 'runs' / f'p{i:02d}'; science.plan(rd, part['specification']['path']); admit_method(rd); tasks.append(task_row(f'p{i:02d}', rd))
    exported = site_workflow.export(export_request(root, a, proof, tasks, {'engine': 'snakemake', 'version': '9.27.0', 'cores': 1, 'retries': 0},
                                    fanin=[{'id': 'merge', 'master': prepared['master'], 'output': str(tmp_path / 'merge-draft')}]),
                                    root, tmp_path / 'wms')
    text = (tmp_path / 'wms/Snakefile').read_text()
    assert len(re.findall(r'^rule task_p\d\d:', text, re.M)) == 50 and len(re.findall(r'^rule fanin_', text, re.M)) == 1
    merge_rule = text.split('rule fanin_merge:')[1]
    assert all(f'completed/p{i:02d}.json' in merge_rule for i in range(50)) and 'retries: 0' in merge_rule
    # The merge rule cannot be exported without every partition of its master.
    with pytest.raises(ValueError, match='every partition'):
        site_workflow.export(export_request(root, a, proof, tasks[:49], {'engine': 'snakemake', 'version': '9.27.0', 'cores': 1, 'retries': 0},
                             fanin=[{'id': 'merge', 'master': prepared['master'], 'output': str(tmp_path / 'other-draft')}]),
                             root, tmp_path / 'partial')
    executable = os.environ.get('RAVEL_TEST_SNAKEMAKE')
    if not executable:
        pytest.skip('set RAVEL_TEST_SNAKEMAKE to run real Snakemake')
    done = subprocess.run([executable, '-n', '--snakefile', str(tmp_path / 'wms/Snakefile'), '--directory', str(tmp_path / 'wms'),
                           '--cores', '1'], capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
    listed = done.stdout + done.stderr
    assert len(set(re.findall(r'task_p\d\d', listed))) == 50 and 'fanin_merge' in listed


def test_merge_rule_over_delivered_partitions_equals_a_single_pass(tmp_path, monkeypatch):
    root, ds, a, spec, proof = source(tmp_path, monkeypatch, seconds=3600)
    # Generous declared ceilings keep a loaded host from hitting the branch or master deadline.
    prepared = p.prepare(request(root, spec, proof, entries=5, budget={'partition_seconds': 600, 'merge_seconds': 900,
                         'max_total_seconds': 3000}), root, tmp_path / 'master')
    tasks = []
    for i, part in enumerate(prepared['partition_specifications']):
        rd = tmp_path / f'part{i}'; science.plan(rd, part['specification']['path']); admit_method(rd)
        science.approve(rd, 'Synthetic scripted assent; not expert review', scripted=True); tasks.append(task_row(f'part{i}', rd))
    exported = site_workflow.export(export_request(root, a, proof, tasks, {'engine': 'snakemake', 'version': '9.27.0', 'cores': 1, 'retries': 0},
                                    fanin=[{'id': 'merge', 'master': prepared['master'], 'output': str(tmp_path / 'merge-draft')}]),
                                    root, tmp_path / 'wms')
    manifest, digest = exported['manifest']['path'], exported['manifest']['sha256']
    with pytest.raises(ValueError, match='every partition delivered'):
        site_workflow.run_fanin(manifest, 'merge', digest)
    for row in tasks:
        assert site_workflow.run_step(manifest, row['id'], digest)['status'] == 'delivered'
    marker = site_workflow.run_fanin(manifest, 'merge', digest)
    assert marker['status'] == 'merge-draft-written' and marker['execution_authorized'] is False
    assert sorted(marker['consumed_attempts'].values()) == sorted(row['rundir'] for row in tasks)
    merge_rd = tmp_path / 'merge'; science.plan(merge_rd, marker['outputs'][0]['path']); admit_method(merge_rd)
    science.approve(merge_rd, 'Synthetic scripted assent; not expert review', scripted=True)
    merged = ordinary_run(merge_rd)
    single = ordinary(spec, tmp_path / 'single')
    def quantities(receipt):
        return [{k: row[k] for k in ('id', 'quantities')} for row in receipt['result']['delivery']['samples'] if row['kind'] != 'data']
    assert quantities(merged) == quantities(single)


def ordinary_run(rd):
    science.run(rd)
    return s.ordinary_delivery(rd)


# ---------------------------------------------------------------- 4. RAVEL-level retries

def failing_command(monkeypatch, root):
    """Plan attempts whose worker fails after its claim (a fake reader failure) until the returned call.

    Each run dir keeps the command it was first planned with, so an approved plan stays
    verifiable after the switch: a project export verifies the plans of the runs it binds.
    """
    folder = root / 'failing'; folder.mkdir(exist_ok=True)
    (folder / 'ordinary_reader.py').write_text(WRAPPER.replace("    raw=w.read_pinned", "    raise ValueError('synthetic attempt failure')\n    raw=w.read_pinned"))
    (folder / 'events.json').write_bytes((root / 'runtime/events.json').read_bytes())
    wrapper = folder / 'ordinary_reader.py'; source_root = Path(s.__file__).parents[2]
    original = science.module_command; failing = {'now': True}; planned = {}
    def command(module, *args, python=None):
        assert module == 'ravel.physics.science_worker'
        if not planned.setdefault(str(Path(args[0]).absolute()), failing['now']):
            return original(module, *args, python=python)
        return [sys.executable, '-B', str(wrapper), str(source_root), *(str(x) for x in args)]
    monkeypatch.setattr(science, 'module_command', command)
    return lambda: failing.update(now=False)


def governed_project(project, root, a, proof):
    """`ravel wms init` on the project: its run dirs run only through their indexed exports."""
    from ravel.workflow import wms_launch
    audit = export_request(root, a, proof, [], local())['audit']
    plain = {k: [row['path'] for row in v] if isinstance(v, list) and v and isinstance(v[0], dict)
             else v['path'] if isinstance(v, dict) else v for k, v in audit.items()}
    project.mkdir(exist_ok=True)
    wms_launch.init(project, audit=plain, python=sys.executable)
    return wms_launch


def retry_project(tmp_path, monkeypatch, *, max_attempts=2):
    """One-partition governed project whose first attempt is planned with a worker that fails after its claim."""
    root, ds, a, spec, proof = source(tmp_path, monkeypatch)
    plan = {'max_attempts': max_attempts, 'wms': {'profile': 'local', 'cores': 1, 'jobs': 1, 'remote_ceiling': 1}}
    prepared = p.prepare(request(root, spec, proof, entries=100, budget={'partition_seconds': 90, 'merge_seconds': 90,
                         'max_total_seconds': 90 * max_attempts + 90}, fanout=plan), root, tmp_path / 'master')
    project = tmp_path / 'project'; wms_launch = governed_project(project, root, a, proof)
    part = prepared['partition_specifications'][0]; rd = project / 'runs' / 'part'
    restore = failing_command(monkeypatch, root)
    science.plan(rd, part['specification']['path']); admit_method(rd)
    science.approve(rd, 'Synthetic scripted assent; not expert review', scripted=True)
    wms_launch.add(project, rd, task='part')
    added = []
    def add(project_dir, rundir, after=(), *, task=None):
        row = wms_launch.add(project_dir, rundir, after, task=task); added.append(row); return row
    monkeypatch.setattr(wms_retry, '_registrar', lambda: add)
    return root, prepared, project, rd, part, added, restore


def run_failed(rd, project=None, task=None):
    """Run an attempt that fails after its claim: through its indexed export when a project governs it."""
    try:
        science.run(rd) if project is None else dispatch(project, task)
    except (ValueError, RuntimeError):
        pass
    assert science.execution.load_execution(rd)['stages']['science']['status'] == 'failed'


def test_failed_partition_retries_in_a_fresh_attempt_and_the_merge_consumes_it(tmp_path, monkeypatch):
    root, prepared, project, rd, part, added, restore = retry_project(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='no attempt yet'):
        wms_retry.retry(project, 'part')
    run_failed(rd, project, 'part'); restore()
    planned = wms_retry.retry(project, 'part')
    fresh = Path(planned['rundir'])
    assert planned['status'] == 'planned' and planned['attempt'] == 2 and fresh != rd and rd.is_dir()
    with pytest.raises(ValueError, match='not approved'):
        wms_retry.retry(project, 'part')
    science.approve(fresh, 'Synthetic scripted assent; not expert review', scripted=True)
    registered = wms_retry.retry(project, 'part')
    assert registered['status'] == 'registered' and registered['task'] == 'part_a2' and added[-1]['rundir'] == str(fresh)
    assert dispatch(project, 'part_a2')['status'] == 'delivered'
    drafted = p.fanin(prepared['master'], tmp_path, tmp_path / 'merge-draft')
    assert drafted['consumed_attempts'] == {part['partition_id']: str(fresh)}
    master = p.read_master(prepared['master'], tmp_path); _, state = p.owner_state(master)
    claims = p.master_claims(master, state)
    assert [row['rundir'] for row in claims] == [str(rd), str(fresh)]
    ledger = read_json(registered['ledger'])
    assert [row['rundir'] for row in ledger['attempts']] == [str(rd)] and ledger['attempts'][0]['state'] == 'failed'
    assert [step['action'] for step in ledger['steps']] == ['planned', 'registered']
    assert science.execution.load_execution(rd)['stages']['science']['status'] == 'failed'
    with pytest.raises(ValueError, match='delivered'):
        wms_retry.retry(project, 'part_a2')


def test_retry_beyond_max_attempts_is_refused(tmp_path, monkeypatch):
    root, prepared, project, rd, part, added, restore = retry_project(tmp_path, monkeypatch)
    run_failed(rd, project, 'part')
    fresh = Path(wms_retry.retry(project, 'part')['rundir'])
    science.approve(fresh, 'Synthetic scripted assent', scripted=True)
    wms_retry.retry(project, 'part'); run_failed(fresh, project, 'part_a2')
    with pytest.raises(ValueError, match='all 2 approved attempt'):
        wms_retry.retry(project, 'part_a2')
    # A direct run of a third attempt run dir is refused at the claim, not only by the retry command.
    third = tmp_path / 'third'; science.plan(third, part['specification']['path']); admit_method(third); science.approve(third, 'Synthetic', scripted=True)
    run_failed(third)
    master = p.read_master(prepared['master'], tmp_path); _, state = p.owner_state(master)
    assert len(p.master_claims(master, state)) == 2


def test_retry_while_an_attempt_is_unresolved_is_refused(tmp_path, monkeypatch):
    root, prepared, project, rd, part, added, restore = retry_project(tmp_path, monkeypatch)
    run_failed(rd, project, 'part'); restore()
    ledger = rd / science.execution.STATE_NAME; original = ledger.read_bytes()
    state = json.loads(original); state['stages']['science']['status'] = 'running'; ledger.write_text(json.dumps(state))
    with pytest.raises(ValueError, match='unresolved'):
        wms_retry.retry(project, 'part')
    ledger.write_bytes(b'{"truncated":true}\n')
    with pytest.raises(ValueError, match='unresolved'):
        wms_retry.retry(project, 'part')
    assert not list(rd.parent.glob('part-attempt*'))
    ledger.write_bytes(original)
    assert wms_retry.retry(project, 'part')['status'] == 'planned'


def test_retry_registers_through_the_project_workflow_add_route():
    from ravel.workflow import wms_launch
    assert callable(wms_launch.add) and wms_retry._registrar() is wms_launch.add


def test_project_command_routes_retry_to_the_retry_operation(tmp_path, monkeypatch, capsys):
    from ravel import cli
    # A refusal of the retry itself, not an unknown subcommand of the project command.
    assert cli.main(['wms', 'retry', '--project', str(tmp_path), '--task', 'part']) == 2
    assert 'ravel wms init' in capsys.readouterr().err
    calls = []
    monkeypatch.setattr(wms_retry, 'retry', lambda project, task: calls.append((project, task)) or {'status': 'planned'})
    assert cli.main(['wms', 'retry', '--project', str(tmp_path), '--task', 'part']) == 0
    assert calls == [(tmp_path, 'part')] and json.loads(capsys.readouterr().out) == {'status': 'planned'}


# ---------------------------------------------------------------- 5. remote profile with fake HTCondor

def test_htcondor_profile_submits_ten_partitions_through_fake_condor_only(tmp_path, monkeypatch):
    from ravel.workflow.site_profiles import htcondor
    monkeypatch.setenv('RAVEL_REMOTE_JOB_CEILING', '3')
    remote = {**WMS, 'profile': 'htcondor', 'cores': 3, 'jobs': 3, 'remote_ceiling': 3}
    argv = site_workflow.wms_argv(site_workflow.validate_wms(remote), tmp_path / 'Snakefile', tmp_path)
    assert argv[argv.index('--jobs') + 1] == '3' and argv[argv.index('--executor') + 1] == 'cluster-generic'
    assert argv[argv.index('--retries') + 1] == '0'
    bin_dir = tmp_path / 'bin'; bin_dir.mkdir(); log = tmp_path / 'submitted.log'
    fake = bin_dir / 'condor_submit'
    fake.write_text('#!/bin/sh\nn=$(wc -l < "%s" 2>/dev/null || echo 0)\necho "$2" >> "%s"\necho "$((n + 1)).0"\n' % (log, log))
    fake.chmod(0o755)
    for name in ('condor_q', 'condor_history', 'condor_rm', 'sbatch', 'squeue'):
        guard = bin_dir / name; guard.write_text('#!/bin/sh\necho unexpected >&2\nexit 9\n'); guard.chmod(0o755)
    monkeypatch.setenv('PATH', str(bin_dir) + os.pathsep + '/usr/bin:/bin')
    monkeypatch.chdir(tmp_path)
    jobs = []
    for i in range(10):
        script = tmp_path / 'jobs' / f'p{i:02d}.sh'; script.parent.mkdir(exist_ok=True)
        script.write_text('#!/bin/sh\n# properties = ' + json.dumps({'rule': f'task_p{i:02d}', 'threads': 1, 'resources': {}}) + '\ntrue\n')
        jobs.append(htcondor.submit(script))
    assert jobs == [f'{i}.0' for i in range(1, 11)] and len(log.read_text().splitlines()) == 10
    executable = os.environ.get('RAVEL_TEST_SNAKEMAKE')
    probe = subprocess.run([executable, '--help'], capture_output=True, text=True, timeout=120) if executable else None
    if probe is None or 'cluster-generic' not in probe.stdout:
        pytest.skip('real Snakemake with the cluster-generic executor plugin is needed to observe the jobs bound')

# Delivery publication and host-aware negative controls.
@pytest.mark.parametrize('status', ['interrupted', 'failed'])
def test_interrupted_remote_or_unrecorded_host_cannot_admit_retry(tmp_path, monkeypatch, status):
    import socket
    record = {'status': status, 'child_pid': 43210, 'child_identity': 'synthetic-start',
              'child_identity_host': 'another-host'}
    monkeypatch.setattr(science.execution, 'load_execution', lambda rd: {'stages': {'science': record}})
    monkeypatch.setattr(science.execution, 'process_identity', lambda pid: None)
    assert p.attempt_state(tmp_path) == 'unresolved'
    def gone(pid, signal): raise ProcessLookupError('synthetic absent child')
    monkeypatch.setattr(os, 'kill', gone)
    record['child_identity_host'] = socket.gethostname()
    assert p.attempt_state(tmp_path) == 'failed'
    record['status'] = 'running'
    assert p.attempt_state(tmp_path) == 'unresolved'
    record['status'] = 'failed'; record.pop('child_identity_host')
    assert p.attempt_state(tmp_path) == 'unresolved'


def test_unresolved_refusal_names_existing_recovery_command(tmp_path, monkeypatch):
    monkeypatch.setattr(p, 'master_fanout', lambda m: {'max_attempts': 2})
    monkeypatch.setattr(p, 'attempt_state', lambda rd: 'unresolved')
    reason = p.retry_admission({}, [{'task_id': 'p', 'rundir': str(tmp_path)}], 'p')
    assert f'ravel run --rundir {tmp_path} --resume' in reason


def test_succeeded_execution_without_ordinary_delivery_can_retry_only_within_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(science.execution, 'load_execution', lambda rd: {'stages': {'science': {'status': 'succeeded'}}})
    def refused(*args, **kwargs):
        raise ValueError('synthetic refused result')
    monkeypatch.setattr(s, 'ordinary_delivery', refused)
    monkeypatch.setattr(p, 'master_fanout', lambda m: {'max_attempts': 2})
    claim = {'task_id': 'p', 'rundir': str(tmp_path)}
    monkeypatch.setattr(p, 'master_claims', lambda m, state: [claim])
    master = {'partitions': [{'id': 'p'}]}
    assert p.attempt_state(tmp_path) == 'ran but did not deliver'
    assert p.delivered_attempts(master, {}) == {'p': None}
    assert p.retry_admission(master, [claim], 'p') is None
    assert 'all 2 approved attempt' in p.retry_admission(master, [claim, claim], 'p')


def exported_retry_project(tmp_path, monkeypatch, max_attempts=2, failing=(1,)):
    root, ds, a, spec, proof = source(tmp_path, monkeypatch, seconds=10000)
    prepared = p.prepare(request(root, spec, proof, entries=5,
        budget={'partition_seconds': 600, 'merge_seconds': 900, 'max_total_seconds': 1800*max_attempts+900},
        fanout={'max_attempts': max_attempts, 'wms': site_workflow.wms_profile(local())}), root, tmp_path / 'master')
    project = tmp_path / 'project'; wf = project / 'workflow'; wms_launch = governed_project(project, root, a, proof)
    restore = failing_command(monkeypatch, root); restore()
    failed_rundirs = {str(project/'runs'/f'part{i}') for i in failing}
    def command(module, *args, python=None):
        assert module == 'ravel.physics.science_worker'
        wrapper = root / ('failing' if str(Path(args[0]).absolute()) in failed_rundirs else 'runtime') / 'ordinary_reader.py'
        return [sys.executable, '-B', str(wrapper), str(Path(s.__file__).parents[2]), *(str(x) for x in args)]
    command.failed_rundirs = failed_rundirs
    monkeypatch.setattr(science, 'module_command', command)
    tasks = []
    for i, part in enumerate(prepared['partition_specifications']):
        rd = project / 'runs' / f'part{i}'; science.plan(rd, part['specification']['path']); admit_method(rd)
        science.approve(rd, 'Synthetic scripted assent; not expert review', scripted=True)
        tasks.append(task_row(f'part{i}', rd)); wms_launch.add(project, rd, task=f'part{i}')
    # The export with the merge rule binds the same original tasks; their indexed exports run them.
    exported = site_workflow.export(export_request(root, a, proof, tasks, local(),
        fanin=[{'id': 'merge', 'master': prepared['master'], 'output': str(tmp_path / 'merge-draft')}]),
        root, wf / 'exports' / 'study')
    return root, a, proof, spec, prepared, project, tasks, exported


@pytest.mark.parametrize('max_attempts,failing', [(2, (1,)), (3, (1,)), (2, (0, 1))])
def test_original_export_merges_delivered_retries_without_repeating_spend(tmp_path, monkeypatch, max_attempts, failing):
    root, a, proof, spec, prepared, project, tasks, exported = exported_retry_project(tmp_path, monkeypatch, max_attempts, failing)
    manifest, digest = exported['manifest']['path'], exported['manifest']['sha256']
    calls = []; original_run = science.run
    def counted(rd, **kwargs):
        calls.append(str(rd)); return original_run(rd, **kwargs)
    monkeypatch.setattr(science, 'run', counted)
    selected = {}; saved = {}
    # A governed project: the merge export's own partition rule may not dispatch an original.
    with pytest.raises(ValueError, match='index does not list this export'):
        site_workflow.run_step(manifest, tasks[0]['id'], digest)
    assert calls == []
    for i, task in enumerate(tasks):
        if i in failing:
            with pytest.raises((ValueError, RuntimeError)):
                dispatch(project, task['id'])
        else:
            dispatch(project, task['id'])
            saved[task['id']] = ((Path(manifest).parent / 'completed' / (task['id']+'.json')).read_bytes(),
                                 s.ordinary_delivery(task['rundir'])['outputs'])
            selected[prepared['partition_specifications'][i]['partition_id']] = task['rundir']
    spent = {task['id']: pin(Path(task['rundir']) / science.execution.STATE_NAME) for task in tasks}
    for i in failing:
        task = tasks[i]
        with pytest.raises(ValueError, match='ravel wms retry'):
            site_workflow.run_fanin(manifest, 'merge', digest)
        for attempt in range(2, max_attempts+1):
            if attempt < max_attempts:
                science.module_command.failed_rundirs.add(task['rundir']+f'-attempt{attempt}')
            planned = wms_retry.retry(project, task['id']); fresh = Path(planned['rundir'])
            science.approve(fresh, 'Synthetic scripted assent; not expert review', scripted=True)
            registered = wms_retry.retry(project, task['id'])
            if attempt < max_attempts:
                with pytest.raises((ValueError, RuntimeError)):
                    dispatch(project, registered['task'])
            else:
                dispatch(project, registered['task'])
                ledger = read_json(registered['ledger'])
                assert ledger['steps'][-1]['action'] == 'delivery-published'
                assert ledger['steps'][-1]['attempt'] == attempt and ledger['steps'][-1]['utc']
                selected[prepared['partition_specifications'][i]['partition_id']] = str(fresh)
    # The merge after the retry is driven through the command the exported merge rule runs.
    assert site_workflow.main(rule_argv(manifest, 'fanin_merge')) == 0
    result = read_json(Path(manifest).parent / 'completed' / 'merge.json')
    assert result['status'] == 'merge-draft-written' and result['consumed_attempts'] == selected
    assert len(calls) == len(set(calls))
    for task in tasks:
        assert Path(task['rundir']).is_dir()
        assert pin(Path(task['rundir']) / science.execution.STATE_NAME) == spent[task['id']]
        if task['id'] in saved:
            assert (Path(manifest).parent / 'completed' / (task['id']+'.json')).read_bytes() == saved[task['id']][0]
            assert s.ordinary_delivery(task['rundir'])['outputs'] == saved[task['id']][1]
    master = p.read_master(prepared['master'], tmp_path); _, state = p.owner_state(master)
    assert len(p.master_claims(master, state)) == len(calls)
    site_workflow.verify(manifest, digest)
    snake = (Path(manifest).parent / 'Snakefile').read_text()
    assert snake.count('retries: 0') == len(tasks)+2
    merge_rd = tmp_path / 'merge'; science.plan(merge_rd, result['outputs'][0]['path']); admit_method(merge_rd)
    science.approve(merge_rd, 'Synthetic scripted assent; not expert review', scripted=True)
    merged = ordinary_run(merge_rd); single = ordinary(spec, tmp_path / 'single')
    def quantities(receipt):
        return [{k: row[k] for k in ('id', 'quantities')} for row in receipt['result']['delivery']['samples'] if row['kind'] != 'data']
    assert quantities(merged) == quantities(single)


def test_handwritten_retry_delivery_record_is_refused_before_merge(tmp_path, monkeypatch):
    root, a, proof, spec, prepared, project, tasks, exported = exported_retry_project(tmp_path, monkeypatch)
    manifest, digest = exported['manifest']['path'], exported['manifest']['sha256']
    task = tasks[1]; path = Path(manifest).parent / 'completed' / (task['id']+'.json')
    atomic_json(path, {'schema_version': 1, 'kind': 'partition-delivery', 'task': task['id'],
        'export_sha256': digest, 'rundir': task['rundir'], 'master': prepared['master'],
        'partition_id': prepared['partition_specifications'][1]['partition_id'], 'outputs': []})
    with pytest.raises(ValueError):
        site_workflow.run_fanin(manifest, 'merge', digest)
    assert not (tmp_path / 'merge-draft').exists()


def test_two_delivered_attempts_are_refused_by_the_existing_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(p, 'master_claims', lambda m, state: [
        {'task_id': 'p', 'rundir': str(tmp_path / 'one')}, {'task_id': 'p', 'rundir': str(tmp_path / 'two')}])
    monkeypatch.setattr(p, 'attempt_state', lambda rd: 'succeeded')
    with pytest.raises(ValueError, match='more than one delivered attempt'):
        p.delivered_attempts({'partitions': [{'id': 'p'}]}, {})


def publication_fixture(tmp_path, monkeypatch, max_attempts=2, failing=(1,)):
    """Inert execution/physics providers; actual retry, publication and merge-rule code.

    This exercises workflow custody and the DAG without launching a supervisor.
    Ordinary-lifecycle controls above retain the independent execution boundary.
    """
    from ravel.workflow import method_selection
    root = tmp_path / 'project'; wf = root / 'workflow'; wf.mkdir(parents=True)
    master_dir = tmp_path / 'master'; master_dir.mkdir()
    mp = put(master_dir, 'master.json', {'partitions': [{'id': f'p{i}'} for i in range(3)]})
    master = {'master_pin': mp, 'partitions': [{'id': f'p{i}'} for i in range(3)], 'base_config': mp}
    claims = []; receipts = {}; executions = {}; calls = []
    monkeypatch.setattr(p, 'read_master', lambda *args, **kwargs: master)
    monkeypatch.setattr(p, 'owner_state', lambda m: (None, {}))
    monkeypatch.setattr(p, 'master_claims', lambda m, state: list(claims))
    monkeypatch.setattr(p, 'master_fanout', lambda m: {'max_attempts': max_attempts})
    monkeypatch.setattr(p, 'dispatch_master', lambda task, base, cap: (master, task['partition_id']))
    monkeypatch.setattr(s, '_load', lambda *args: (None, {}, {}, {}))
    monkeypatch.setattr(science.execution, 'load_execution', lambda rd: {'stages': {'science': executions[str(rd)]}})
    def delivery(rd, **kwargs):
        value = receipts.get(str(rd))
        if value is None: raise ValueError('synthetic attempt did not deliver')
        assert value['outputs'] == [pin(Path(row['path'])) for row in value['outputs']]
        return value
    monkeypatch.setattr(s, 'ordinary_delivery', delivery)
    def plan(rd, specification):
        rd = Path(rd); rd.mkdir(parents=True)
        atomic_json(rd / science.SPEC, read_json(specification))
        atomic_json(rd / science.PLAN, {'synthetic': True})
        admit_method(rd, refresh=False)
    monkeypatch.setattr(science, 'plan', plan)
    def disclose(rd):
        # This fixture's planner/approval are inert; keep the method validator
        # real and supply the corresponding synthetic disclosure document.
        method_selection.require_launch(rd)
        value = {'synthetic': True, 'method_decision_sha256': pin(Path(rd) / method_selection.DECISION_PATH)['sha256']}
        atomic_json(Path(rd) / 'inputs/checkin1.json', value)
        return value
    monkeypatch.setattr(method_selection, 'refresh_checkin', disclose)
    def approve(rd, statement, *, scripted=False):
        assert scripted
        atomic_json(Path(rd)/'inert-approval.json', {'approval_mode':'scripted_yes', 'expert_review':False, 'statement':statement})
    def verify_plan(rd, *, approved=False, **kwargs):
        if approved:
            if not (Path(rd)/'inert-approval.json').is_file(): raise ValueError('synthetic plan not approved')
            assert read_json(Path(rd)/'inert-approval.json')['approval_mode']=='scripted_yes'
        return {}
    monkeypatch.setattr(science, 'approve', approve)
    monkeypatch.setattr(science, 'verify_plan', verify_plan)
    tasks = []
    for i in range(3):
        sp = put(master_dir, f'p{i}-spec.json', {'mode': 'root-stream', 'task': {'partition_id': f'p{i}'}})
        rd = root / 'runs' / f'part{i}'; plan(rd, sp['path'])
        approve(rd,'Synthetic scripted assent; not expert review',scripted=True); tasks.append(task_row(f'part{i}', rd))
    documents = {}
    def inert_export(name, rows, fanin=None):
        out = wf / 'exports' / name; (out / 'completed').mkdir(parents=True)
        doc = {'tasks': [{**t, 'output_directory': 'outputs'} for t in rows], 'python': pin(sys.executable)}
        if fanin is not None: doc['fanin'] = [fanin]
        manifest = s.write_new(out / 'workflow.json', doc)
        (out / 'Snakefile').write_bytes(site_workflow._snakefile(out / 'workflow.json', doc))
        documents[manifest['path']] = (doc, pin(out / 'Snakefile'))
        return manifest
    def indexed(row):
        # As `ravel wms add` writes it: the run is governed from the start, through its one-task export.
        return {**row, 'after': [], 'export': inert_export(row['id'], [row])}
    atomic_json(wf / 'index.json', {'tasks': [indexed(t) for t in tasks]})
    def add(project, rundir, after=(), *, task=None):
        row = indexed(task_row(task, Path(rundir))); index = read_json(wf / 'index.json')
        index['tasks'].append(row); atomic_json(wf / 'index.json', index); return row
    monkeypatch.setattr(wms_retry, '_registrar', lambda: add)
    row = {'id': 'merge', 'master': mp, 'output': str(tmp_path / 'draft'), 'depends_on': [t['id'] for t in tasks],
           'partition_tasks': {t['id']: f'p{i}' for i, t in enumerate(tasks)}}
    manifest = inert_export('study', tasks, row)
    def verify(path, digest):
        assert pin(path)['sha256'] == digest
        snake = pin(Path(path).parent / 'Snakefile')
        if str(Path(path).absolute()) not in documents: raise ValueError('synthetic unverifiable export')
        doc, snake_pin = documents[str(Path(path).absolute())]
        assert snake == snake_pin
        return doc
    monkeypatch.setattr(site_workflow, 'verify', verify)
    def run(rd, **kwargs):
        rd = Path(rd); verify_plan(rd,approved=True); calls.append(str(rd)); pid = read_json(rd / science.SPEC)['task']['partition_id']
        number = 1 + sum(r['task_id'] == pid for r in claims)
        assert p.retry_admission(master, claims, pid) is None
        claim = {'task_id': pid, 'rundir': str(rd), 'attempt_id': f'{pid}-{number}', 'fingerprint': f'{pid}-{number}', 'seconds': 1}
        claims.append(claim)
        if int(pid[1:]) in failing and number < max_attempts:
            executions[str(rd)] = {'status': 'failed', 'exit_code': 1, 'finished_utc': 'synthetic-terminal'}
            return 1
        folder = rd / 'outputs'; folder.mkdir()
        outputs = [put(folder, 'result.json', {'status': 'passed', 'physics_validated': False}),
                   put(folder, 'verification.json', {'passed': True, 'physics_validated': False})]
        executions[str(rd)] = {'status': 'succeeded', 'attempt_id': claim['attempt_id']}
        receipts[str(rd)] = {'outputs': outputs, 'fingerprint': claim['fingerprint']}
        return 0
    monkeypatch.setattr(science, 'run', run)
    def record(master_pin, pid, rd, path):
        p.require_claim(master, rd, pid, delivery(rd))
        return put(Path(path).parent, Path(path).name, {'master': master_pin, 'partition_id': pid,
                    'rundir': str(rd), 'outputs': delivery(rd)['outputs']})
    monkeypatch.setattr(p, 'record', record)
    def completion(declaration, base, m, ds, a, cap):
        value = cap.document(declaration, base); receipt = delivery(value['rundir'])
        assert value['master'] == mp and value['outputs'] == receipt['outputs']
        p.require_claim(m, value['rundir'], value['partition_id'], receipt)
        return value, {}, receipt
    monkeypatch.setattr(p, 'completion', completion)
    def fanin(master_pin, base, output):
        selected = p.delivered_attempts(master, {}); assert all(selected.values())
        output = Path(output); output.mkdir()
        sp = put(output, 'spec.json', {}); closure = put(output, 'closure.json', {})
        return {'specification': sp, 'closure': closure, 'completions': [],
                'consumed_attempts': {pid: c['rundir'] for pid, c in selected.items()}}
    monkeypatch.setattr(p, 'fanin', fanin)
    return root, tasks, manifest, claims, calls, receipts, executions


@pytest.mark.parametrize('max_attempts,failing', [(2, (1,)), (3, (1,)), (2, (0, 1))])
def test_inert_export_retry_publication_composes_with_merge_rule(tmp_path, monkeypatch, max_attempts, failing):
    project, tasks, manifest, claims, calls, receipts, executions = publication_fixture(tmp_path, monkeypatch, max_attempts, failing)
    path, digest = manifest['path'], manifest['sha256']; saved = {}
    for i, row in enumerate(tasks):
        if i in failing:
            with pytest.raises(ValueError, match='did not deliver'): dispatch(project, row['id'])
        else:
            dispatch(project, row['id'])
            saved[row['id']] = (Path(path).parent / 'completed' / (row['id']+'.json')).read_bytes()
    with pytest.raises(ValueError, match='ravel wms retry'): site_workflow.run_fanin(path, 'merge', digest)
    for i in failing:
        for attempt in range(2, max_attempts+1):
            planned = wms_retry.retry(project, tasks[i]['id']); rd = Path(planned['rundir'])
            with pytest.raises(ValueError,match='not approved'): wms_retry.retry(project,tasks[i]['id'])
            science.approve(rd,'Synthetic scripted assent; not expert review',scripted=True)
            registered = wms_retry.retry(project, tasks[i]['id'])
            # The launch seam publishes only after this registered attempt delivers.
            assert science.run(rd) == (1 if attempt < max_attempts else 0)
            if attempt == max_attempts:
                wms_retry.publish_registered_attempt(project, rd)
                step = read_json(registered['ledger'])['steps'][-1]
                assert step['action'] == 'delivery-published' and step['attempt'] == attempt and step['utc']
    # The merge after the retry is driven through the command the exported merge rule runs.
    assert site_workflow.main(rule_argv(path, 'fanin_merge')) == 0
    result = read_json(Path(path).parent / 'completed' / 'merge.json')
    selected = {f'p{i}': next(r['rundir'] for r in reversed(claims) if r['task_id']==f'p{i}') for i in range(3)}
    assert result['consumed_attempts'] == selected and len(calls) == len(set(calls))
    assert len(claims) == 3 + len(failing)*(max_attempts-1)
    for task in tasks:
        with pytest.raises(ValueError, match='spent WMS step'): site_workflow.run_step(path,task['id'],digest)
    assert len(calls) == len(set(calls))
    for row in tasks:
        assert Path(row['rundir']).is_dir()
        if row['id'] in saved:
            assert (Path(path).parent / 'completed' / (row['id']+'.json')).read_bytes() == saved[row['id']]
            assert receipts[row['rundir']]['outputs'] == [pin(Path(pn['path'])) for pn in receipts[row['rundir']]['outputs']]
    site_workflow.verify(path, digest)


@pytest.mark.parametrize('mutation', ['handwritten', 'failed_attempt', 'result_pin', 'verification_pin', 'another_master'])
def test_retry_delivery_publication_refuses_forged_records(tmp_path, monkeypatch, mutation):
    project, tasks, manifest, claims, calls, receipts, executions = publication_fixture(tmp_path, monkeypatch)
    path, digest = manifest['path'], manifest['sha256']
    for i, row in enumerate(tasks):
        if i == 1:
            with pytest.raises(ValueError): dispatch(project, row['id'])
        else: dispatch(project, row['id'])
    planned = wms_retry.retry(project, 'part1'); rd = Path(planned['rundir'])
    science.approve(rd,'Synthetic scripted assent; not expert review',scripted=True); wms_retry.retry(project, 'part1')
    assert science.run(rd) == 0
    wms_retry.publish_registered_attempt(project, rd)
    marker = Path(path).parent / 'completed/part1.json'; publication = Path(path).parent / 'published/part1.json'
    if mutation == 'handwritten': publication.unlink()
    elif mutation == 'another_master':
        value = read_json(publication); value['master']['sha256'] = '0'*64; atomic_json(publication, value)
    else:
        value = read_json(marker)
        if mutation == 'failed_attempt': value['rundir'] = tasks[1]['rundir']
        else: value['outputs'][1 if mutation=='verification_pin' else 0]['sha256'] = '0'*64
        atomic_json(marker, value)
    with pytest.raises(ValueError): site_workflow.run_fanin(path, 'merge', digest)
    assert not (tmp_path / 'draft').exists()


def test_hand_placed_original_delivery_marker_needs_issued_publication(tmp_path, monkeypatch):
    project, tasks, manifest, claims, calls, receipts, executions = publication_fixture(tmp_path, monkeypatch, failing=())
    path, digest = manifest['path'], manifest['sha256']
    for task in tasks:
        science.run(task['rundir'])
        atomic_json(Path(path).parent / 'completed' / (task['id']+'.json'),
            {'schema_version': 1, 'task': task['id'], 'export_sha256': digest, 'status': 'delivered',
             'outputs': receipts[task['rundir']]['outputs'], 'scientific_acceptance_inferred': False})
    with pytest.raises(ValueError, match='not published'): site_workflow.run_fanin(path, 'merge', digest)
    assert not (tmp_path / 'draft').exists()


def test_unreadable_local_identity_is_unresolved_and_needs_recovery(tmp_path, monkeypatch):
    import socket
    record = {'status': 'interrupted', 'child_pid': 43210, 'child_identity': 'synthetic-start',
              'child_identity_host': socket.gethostname()}
    monkeypatch.setattr(science.execution, 'load_execution', lambda rd: {'stages': {'science': record}})
    monkeypatch.setattr(science.execution, 'process_identity', lambda pid: None)
    def denied(pid, signal): raise PermissionError('synthetic unreadable process')
    monkeypatch.setattr(os, 'kill', denied)
    assert p.attempt_state(tmp_path) == 'unresolved'
    monkeypatch.setattr(p, 'master_fanout', lambda m: {'max_attempts': 2})
    assert f'ravel run --rundir {tmp_path} --resume' in p.retry_admission({}, [{'task_id':'p','rundir':str(tmp_path)}], 'p')


def test_refused_result_is_not_merged_and_actual_retry_keeps_the_attempt_bound(tmp_path, monkeypatch):
    project, tasks, manifest, claims, calls, receipts, executions = publication_fixture(tmp_path, monkeypatch, failing=())
    rd = tasks[1]['rundir']; assert science.run(rd) == 0; del receipts[rd]
    assert p.attempt_state(rd) == 'ran but did not deliver'
    assert p.delivered_attempts({'partitions':[{'id':'p1'}]}, {}) == {'p1':None}
    with pytest.raises(ValueError, match='p1.*ravel wms retry'):
        site_workflow.run_fanin(manifest['path'], 'merge', manifest['sha256'])
    fresh = Path(wms_retry.retry(project, 'part1')['rundir'])
    science.approve(fresh,'Synthetic scripted assent; not expert review',scripted=True); wms_retry.retry(project, 'part1')
    assert science.run(fresh) == 0; del receipts[str(fresh)]
    with pytest.raises(ValueError, match='all 2 approved attempt.*ran but did not deliver'):
        wms_retry.retry(project, 'part1_a2')
    assert not (tmp_path / 'draft').exists()


def test_unresolved_partition_merge_names_supervised_recovery(tmp_path, monkeypatch):
    project, tasks, manifest, claims, calls, receipts, executions = publication_fixture(tmp_path, monkeypatch)
    rd = tasks[1]['rundir']; assert science.run(rd) == 1; executions[rd]['status'] = 'running'
    # Outside a workflow-manager project the supervised recovery command is the next step.
    index = project / 'workflow' / 'index.json'; governed = index.read_bytes()
    rows = read_json(index); rows['tasks'] = [row for row in rows['tasks'] if row['rundir'] != rd]; atomic_json(index, rows)
    with pytest.raises(ValueError, match=f'p1 is unresolved; run `ravel run --rundir {rd} --resume` on the recording host'):
        site_workflow.run_fanin(manifest['path'], 'merge', manifest['sha256'])
    index.write_bytes(governed)
    with pytest.raises(ValueError, match='p1.*unresolved and held.*governed by a workflow-manager project') as refused:
        site_workflow.run_fanin(manifest['path'], 'merge', manifest['sha256'])
    assert 'on the recording host' not in str(refused.value)
    assert not (tmp_path / 'draft').exists()


def test_governed_attempt_cannot_enter_recovery_through_the_run_command_and_refusals_state_the_hold(tmp_path, monkeypatch):
    import socket
    from ravel.workflow import stage_supervisor
    run = science.run  # the ordinary entry, before the fixture replaces it with an inert run
    project, tasks, manifest, claims, calls, receipts, executions = publication_fixture(tmp_path, monkeypatch)
    rd = tasks[1]['rundir']; assert science.run(rd) == 1
    # An indexed attempt whose supervisor ended while its child's state is unknown; inert process observations.
    executions[rd] = {'status': 'running', 'child_pid': 43210, 'child_identity': 'synthetic-start',
                      'child_identity_host': socket.gethostname()}
    monkeypatch.setattr(science.execution, 'process_identity', lambda pid: None)
    def gone(pid, signal): raise ProcessLookupError('synthetic absent child')
    monkeypatch.setattr(os, 'kill', gone)
    recovered = []
    monkeypatch.setattr(stage_supervisor, 'recover_previous_attempt', lambda *a, **k: recovered.append(a))
    record = json.dumps(executions[rd], sort_keys=True)
    assert p.attempt_state(rd) == 'unresolved'
    # The advertised command is refused by the project before supervised recovery starts.
    with pytest.raises(ValueError, match='governed by the workflow-manager project'): run(rd, resume=True)
    assert recovered == [] and json.dumps(executions[rd], sort_keys=True) == record
    command = f'ravel run --rundir {rd} --resume'
    for refusal in (lambda: wms_retry.retry(project, 'part1'), lambda: site_workflow.run_fanin(manifest['path'], 'merge', manifest['sha256'])):
        with pytest.raises(ValueError, match='p1.*unresolved and held') as refused:
            refusal()
        text = str(refused.value)
        assert f'refuses `{command}` before supervised recovery starts' in text and 'stays charged' in text
        assert 'before a retry' not in text and 'on the recording host' not in text
    assert not list(Path(rd).parent.glob('part1-attempt*')) and not (tmp_path / 'draft').exists()
    assert len(claims) == 1 and recovered == []


def test_real_workflow_manager_relaunch_runs_only_the_merge_rule(tmp_path, monkeypatch):
    """Actual registrar and exported commands, with only the native reader supplied as a fake.

    The initial export runs before the project is governed. Registration then uses
    the project route; its retry launch publishes into the immutable initial export.
    The isolated rule interpreter must resolve this exact installed source tree.
    """
    executable = os.environ.get('RAVEL_TEST_SNAKEMAKE')
    if not executable:
        pytest.skip('set RAVEL_TEST_SNAKEMAKE to run real local Snakemake')
    monkeypatch.delenv('RAVEL_SNAKEMAKE', raising=False)
    monkeypatch.delenv('SNAKEMAKE_PROFILE', raising=False)
    probe = subprocess.run([sys.executable, '-I', '-B', '-c',
        'from ravel.workflow import wms_retry; print(wms_retry.__file__)'],
        capture_output=True, text=True, timeout=30)
    assert probe.returncode == 0 and Path(probe.stdout.strip()).resolve() == Path(wms_retry.__file__).resolve(), (
        'run this test in an environment whose installed ravel is this source; exported rules use -I; '
        + probe.stdout + probe.stderr)
    from ravel.paths import module_command
    from ravel.workflow import wms_launch
    root, ds, analysis, spec, proof = source(tmp_path, monkeypatch, seconds=10000)
    # Undo the fixture's science-command substitution. All rules and supervised
    # science stages use the installed implementation and its ordinary bootstrap.
    monkeypatch.setattr(science, 'module_command', module_command)
    project = tmp_path / 'project'; project.mkdir()
    failed_origin = project / 'runs/part1'
    cfg = read_json(read_json(spec['path'])['task']['config']['path'])
    runtime = root / 'runtime'
    fake = runtime / 'python'
    reader = WRAPPER[WRAPPER.index('def synthetic_reader'):WRAPPER.index('reinterpret_db.execute_native=')]
    fake.write_text('#!' + sys.executable + ' -I\n'
        + 'import sys,json\nfrom pathlib import Path\n'
        + 'from ravel.physics import root_stream_worker as w, root_stream as s\n'
        + 'wrapper=Path(__file__)\n' + reader
        + 'request=Path(sys.argv[-2]); raw=w.read_pinned(request,sys.argv[-1],64*1024**2)\n'
        + 'document=json.loads(raw)\n'
        + 'if Path(' + repr(str(failed_origin)) + ') in request.parents: raise SystemExit(1)\n'
        + 'synthetic_reader(sys.argv[-2:],Path(document["output"]),document["config"]["limits"])\n')
    fake.chmod(0o755)
    cfg['runtime']['python'] = pin(fake)
    cfg['runtime']['trees'][0]['manifest'] = put(root, 'manager-runtime.json', {
        'schema_version': 1, 'files': {p.name: {k: pin(p)[k] for k in ('sha256', 'size')}
                                     for p in runtime.iterdir() if p.is_file()}})
    value = read_json(spec['path']); value['task']['config'] = put(root, 'manager-config.json', cfg)
    spec = put(root, 'manager-spec.json', value)
    prepared = p.prepare(request(root, spec, proof, entries=5,
        budget={'partition_seconds': 600, 'merge_seconds': 900, 'max_total_seconds': 4500},
        fanout={'max_attempts': 2, 'wms': site_workflow.wms_profile(local())}), root, tmp_path / 'master')
    tasks = []
    for i, part in enumerate(prepared['partition_specifications']):
        rd = project / 'runs' / f'part{i}'
        science.plan(rd, part['specification']['path']); admit_method(rd)
        science.approve(rd, 'Synthetic scripted assent; not expert review', scripted=True)
        tasks.append(task_row(f'part{i}', rd))
    assert len(tasks) == 3
    out = project / 'workflow/exports/study'; out.parent.mkdir(parents=True)
    exported = site_workflow.export(export_request(root, analysis, proof, tasks, local(),
        fanin=[{'id': 'merge', 'master': prepared['master'], 'output': str(tmp_path / 'merge-draft')}]), root, out)
    manifest, digest = exported['manifest']['path'], exported['manifest']['sha256']
    original_bytes = [(out / name).read_bytes() for name in ('workflow.json', 'Snakefile')]
    argv = [executable, '--snakefile', str(out / 'Snakefile'), '--directory', str(out),
            '--cores', '1', '--retries', '0', '--keep-going', '--executor', 'local']
    first = subprocess.run(argv, capture_output=True, text=True, timeout=900)
    assert first.returncode != 0, first.stdout + first.stderr
    assert science.execution.load_execution(failed_origin)['stages']['science']['status'] == 'failed'
    assert not (out / 'completed/merge.json').exists()
    saved = {row['id']: (out / 'completed' / (row['id'] + '.json')).read_bytes()
             for row in tasks if row['rundir'] != str(failed_origin)}
    assert len(saved) == 2, first.stdout + first.stderr
    retained = {row['id']: pin(Path(row['rundir']) / science.execution.STATE_NAME) for row in tasks}
    audit = export_request(root, analysis, proof, [], local())['audit']
    plain_audit = {k: [row['path'] for row in v] if isinstance(v, list) and v and isinstance(v[0], dict)
                   else v['path'] if isinstance(v, dict) else v for k, v in audit.items()}
    wms_launch.init(project, audit=plain_audit, python=sys.executable)
    for row in tasks:
        wms_launch.add(project, row['rundir'], task=row['id'])
    planned = wms_retry.retry(project, 'part1'); fresh = Path(planned['rundir'])
    assert (fresh / 'inputs/method-decision.json').read_bytes() == (failed_origin / 'inputs/method-decision.json').read_bytes()
    science.approve(fresh, 'Synthetic scripted assent; not expert review', scripted=True)
    registered = wms_retry.retry(project, 'part1')
    assert registered['task'] == 'part1_a2'
    assert (project / 'workflow/rules/part1_a2.smk').is_file()
    launched = wms_launch.launch(project, registered['task'])
    assert launched['exit_code'] == 0, Path(launched['log']['path']).read_text()
    assert launched['snakemake_locks_present_during_step'] == [True]
    assert not (out / 'completed/merge.json').exists()
    second = subprocess.run(argv, capture_output=True, text=True, timeout=900)
    assert second.returncode == 0, second.stdout + second.stderr
    marker = read_json(out / 'completed/merge.json')
    expected = {part['partition_id']: str(fresh) if i == 1 else tasks[i]['rundir']
                for i, part in enumerate(prepared['partition_specifications'])}
    assert marker['consumed_attempts'] == expected
    assert 'localrule fanin_merge:' in second.stdout + second.stderr
    assert not re.search(r'(?:local)?rule task_part[0-9]+:', second.stdout + second.stderr)
    for row in tasks:
        assert pin(Path(row['rundir']) / science.execution.STATE_NAME) == retained[row['id']]
        if row['id'] in saved:
            assert (out / 'completed' / (row['id'] + '.json')).read_bytes() == saved[row['id']]
    master = p.read_master(prepared['master'], tmp_path); _, state = p.owner_state(master)
    assert len(p.master_claims(master, state)) == 4
    assert [(out / name).read_bytes() for name in ('workflow.json', 'Snakefile')] == original_bytes
    site_workflow.verify(manifest, digest)


def test_real_manager_retry_gate_names_its_required_variable(tmp_path, monkeypatch):
    monkeypatch.delenv('RAVEL_TEST_SNAKEMAKE', raising=False)
    with pytest.raises(pytest.skip.Exception, match='RAVEL_TEST_SNAKEMAKE'):
        test_real_workflow_manager_relaunch_runs_only_the_merge_rule(tmp_path, monkeypatch)


@pytest.mark.parametrize('phase', ['marker', 'visibility'])
def test_retry_publication_can_finish_after_interruption_without_repeating_spend(tmp_path, monkeypatch, phase):
    project, tasks, manifest, claims, calls, receipts, executions = publication_fixture(tmp_path, monkeypatch)
    path, digest = manifest['path'], manifest['sha256']
    for i, task in enumerate(tasks):
        if i == 1:
            with pytest.raises(ValueError): dispatch(project, task['id'])
        else: dispatch(project, task['id'])
    fresh=Path(wms_retry.retry(project,'part1')['rundir'])
    science.approve(fresh,'Synthetic scripted assent; not expert review',scripted=True); registered=wms_retry.retry(project,'part1')
    assert science.run(fresh)==0
    original_write=s.write_new; original_record=wms_retry.record_delivery_publication
    def interrupted(path, value):
        if phase=='marker' and Path(path)==Path(manifest['path']).parent/'completed/part1.json': raise OSError('synthetic publication interruption')
        return original_write(path,value)
    def interrupt_visibility(*args, **kwargs):
        if phase=='visibility' and kwargs.get('visible'): raise OSError('synthetic visibility interruption')
        return original_record(*args, **kwargs)
    monkeypatch.setattr(s,'write_new',interrupted)
    monkeypatch.setattr(wms_retry,'record_delivery_publication',interrupt_visibility)
    with pytest.raises(OSError): wms_retry.publish_registered_attempt(project,fresh)
    assert not any(step['action']=='delivery-published' for step in read_json(registered['ledger'])['steps'])
    if phase=='visibility':
        with pytest.raises(ValueError,match='publication is unfinished'): site_workflow.run_fanin(path,'merge',digest)
        assert not (tmp_path/'draft').exists()
    monkeypatch.setattr(s,'write_new',original_write)
    monkeypatch.setattr(wms_retry,'record_delivery_publication',original_record)
    wms_retry.publish_registered_attempt(project,fresh)
    result=site_workflow.run_fanin(path,'merge',digest)
    assert result['consumed_attempts']['p1']==str(fresh)
    assert len(calls)==4 and len(claims)==4
    steps=read_json(registered['ledger'])['steps']
    assert len([step for step in steps if step['action']=='delivery-published'])==1


def test_marker_alone_does_not_call_a_refused_result_delivered(tmp_path, monkeypatch):
    project, tasks, manifest, claims, calls, receipts, executions = publication_fixture(tmp_path, monkeypatch, failing=())
    rd=tasks[1]['rundir']; assert science.run(rd)==0; del receipts[rd]
    marker=project/'workflow/exports/part1/completed/part1.json'
    atomic_json(marker, {'status':'delivered'})
    planned=wms_retry.retry(project,'part1')
    assert planned['status']=='planned' and planned['attempt']==2
    assert read_json(planned['ledger'])['attempts'][0]['state']=='ran but did not deliver'
    assert marker.read_bytes()==b'{\n  "status": "delivered"\n}\n'


# Publication under a concurrent retry, foreign indexes, unrelated exports and refusal wording.

def rule_argv(manifest, rule):
    """Arguments of the command an exported rule runs, read from its Snakefile."""
    import ast, shlex
    text = (Path(manifest).parent / 'Snakefile').read_text()
    shell = ast.literal_eval(re.search(r'^    shell: (.+)$', text[text.index(f'rule {rule}:'):], re.M).group(1))
    argv = shlex.split(shell.replace('{{', '{').replace('}}', '}'))
    assert argv[1:4] == ['-I', '-B', '-m']
    return argv[argv.index('ravel.workflow.site_workflow') + 1:]


def dispatch(project, task):
    """Run one indexed task as `ravel wms launch` does, with Snakemake replaced by its run-step call.

    The project index lists the task's own export; run-step admits it only inside a live
    launch authorization that names the task and that export.
    """
    from ravel.workflow import wms_policy
    wf = Path(project) / 'workflow'
    entry = next(row for row in read_json(wf / 'index.json')['tasks'] if row['id'] == task)
    with wms_policy.launch_authorization(wf, task, 1, {task: entry['export']['sha256']}):
        return site_workflow.run_step(entry['export']['path'], task, entry['export']['sha256'])


def delivered_retry(tmp_path, monkeypatch):
    """Inert project whose second partition failed once and then delivered in a registered attempt."""
    project, tasks, manifest, claims, calls, receipts, executions = publication_fixture(tmp_path, monkeypatch)
    path, digest = manifest['path'], manifest['sha256']
    for i, row in enumerate(tasks):
        if i == 1:
            with pytest.raises(ValueError): dispatch(project, row['id'])
        else: dispatch(project, row['id'])
    fresh = Path(wms_retry.retry(project, 'part1')['rundir'])
    science.approve(fresh, 'Synthetic scripted assent; not expert review', scripted=True); wms_retry.retry(project, 'part1')
    assert science.run(fresh) == 0
    return project, path, digest, fresh


def test_retry_publication_waits_for_a_concurrent_retry_command(tmp_path, monkeypatch):
    import threading
    from ravel.workflow.state_io import file_lock
    project, path, digest, fresh = delivered_retry(tmp_path, monkeypatch)
    held = threading.Event(); release = threading.Event()
    def hold():
        with file_lock(project / 'workflow' / '.wms-retry.lock'):
            held.set(); release.wait(30)
    holder = threading.Thread(target=hold); holder.start(); assert held.wait(30)
    timer = threading.Timer(0.5, release.set); timer.start()
    try:
        wms_retry.publish_registered_attempt(project, fresh)
    finally:
        release.set(); holder.join(); timer.cancel()
    assert site_workflow.run_fanin(path, 'merge', digest)['consumed_attempts']['p1'] == str(fresh)


@pytest.mark.parametrize('foreign', ['["not a project index"]', 'not json', '{"tasks": 3}', '{"tasks": ["text"]}'])
def test_run_step_handoff_skips_a_foreign_workflow_index(tmp_path, monkeypatch, foreign):
    project, path, digest, fresh = delivered_retry(tmp_path, monkeypatch)
    other = fresh.parent / 'workflow'; other.mkdir(); (other / 'index.json').write_text(foreign)
    assert [row['rundir'] for row in wms_retry.publish_registered_attempt_for_run(fresh)] == [str(fresh)]
    assert site_workflow.run_fanin(path, 'merge', digest)['consumed_attempts']['p1'] == str(fresh)


def test_retry_planning_reads_only_the_exports_of_its_own_partition(tmp_path, monkeypatch):
    project, tasks, manifest, claims, calls, receipts, executions = publication_fixture(tmp_path, monkeypatch)
    path, digest = manifest['path'], manifest['sha256']
    with pytest.raises(ValueError, match='did not deliver'): dispatch(project, 'part1')
    exports = project / 'workflow' / 'exports'
    for name, value in (('other', {'tasks': [{'id': 'elsewhere', 'rundir': str(tmp_path / 'elsewhere')}]}),
                        ('list', ['not an export']), ('shape', {'tasks': 3})):
        (exports / name).mkdir(); atomic_json(exports / name / 'workflow.json', value)
    (exports / 'broken').mkdir(); (exports / 'broken' / 'workflow.json').write_text('not json')
    planned = wms_retry.retry(project, 'part1')
    assert planned['status'] == 'planned' and [row['path'] for row in planned['merge_exports']] == [path]


def test_retry_planning_refuses_an_unverifiable_export_of_its_own_partition(tmp_path, monkeypatch):
    project, tasks, manifest, claims, calls, receipts, executions = publication_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='did not deliver'): dispatch(project, 'part1')
    copy = project / 'workflow' / 'exports' / 'copy'; copy.mkdir()
    atomic_json(copy / 'workflow.json', {'tasks': [{'id': 'part1', 'rundir': tasks[1]['rundir']}]})
    with pytest.raises((ValueError, OSError)): wms_retry.retry(project, 'part1')
    assert not list(Path(tasks[1]['rundir']).parent.glob('part1-attempt*'))


def test_delivered_but_unpublished_attempt_names_its_publication_not_a_retry(tmp_path, monkeypatch):
    project, path, digest, fresh = delivered_retry(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='not published') as refused:
        site_workflow.run_fanin(path, 'merge', digest)
    text = str(refused.value)
    assert 'p1' in text and str(fresh) in text and 'publish_registered_attempt' in text and 'ravel wms retry' not in text
    assert not (tmp_path / 'draft').exists()
    with pytest.raises(ValueError, match='already delivered'): wms_retry.retry(project, 'part1')


def test_merge_rule_selects_delivered_attempts_once_per_pass(tmp_path, monkeypatch):
    project, path, digest, fresh = delivered_retry(tmp_path, monkeypatch)
    wms_retry.publish_registered_attempt(project, fresh)
    selections = []; original = p.delivered_attempts
    def counted(master, state):
        selections.append(1); return original(master, state)
    monkeypatch.setattr(p, 'delivered_attempts', counted)
    assert site_workflow.run_fanin(path, 'merge', digest)['consumed_attempts']['p1'] == str(fresh)
    # One selection by the merge rule and one by the merge preparation, for any number of partitions.
    assert len(selections) == 2


@pytest.mark.parametrize('host', ['absent', 'local', 'other'])
def test_terminal_failure_with_a_live_matching_child_stays_unresolved(tmp_path, monkeypatch, host):
    import socket
    record = {'status': 'failed', 'exit_code': 1, 'finished_utc': 'synthetic-terminal',
              'child_pid': 43210, 'child_identity': 'synthetic-start'}
    if host != 'absent': record['child_identity_host'] = socket.gethostname() if host == 'local' else 'another-host'
    monkeypatch.setattr(science.execution, 'load_execution', lambda rd: {'stages': {'science': record}})
    monkeypatch.setattr(science.execution, 'process_identity', lambda pid: 'synthetic-start')
    assert p.attempt_state(tmp_path) == 'unresolved'
    monkeypatch.setattr(science.execution, 'process_identity', lambda pid: 'synthetic-later-process')
    assert p.attempt_state(tmp_path) == 'failed'


# Retries approved and run outside `ravel wms retry`, dependent tasks after a retry, and the lost-supervisor hold.

ASSENT = 'Synthetic scripted assent; not expert review'


def failed_once(tmp_path, monkeypatch, **options):
    """Inert project whose second partition failed its run-step; the others delivered."""
    project, tasks, manifest, claims, calls, receipts, executions = publication_fixture(tmp_path, monkeypatch, **options)
    path, digest = manifest['path'], manifest['sha256']; spent_guard(monkeypatch, calls)
    for i, row in enumerate(tasks):
        if i == 1:
            with pytest.raises(ValueError, match='did not deliver'): dispatch(project, row['id'])
        else: dispatch(project, row['id'])
    return project, tasks, path, digest, claims, calls, receipts


def spent_guard(monkeypatch, calls):
    """Give the inert run the ordinary rule that a run directory dispatches once."""
    inert = science.run
    def run(target, **kwargs):
        if str(target) in calls: raise ValueError('attempt is spent')
        return inert(target, **kwargs)
    monkeypatch.setattr(science, 'run', run)


def direct_attempt(tmp_path, name='part1-direct'):
    """A fresh attempt of the failed partition from the same master specification, with no retry command."""
    fresh = tmp_path / 'direct' / name
    science.plan(fresh, str(tmp_path / 'master' / 'p1-spec.json')); admit_method(fresh); science.approve(fresh, ASSENT, scripted=True)
    return fresh


@pytest.mark.parametrize('route', ['exported-rule', 'publication-call'])
def test_retry_run_outside_the_retry_command_reaches_the_original_merge_rule(tmp_path, monkeypatch, route):
    project, tasks, path, digest, claims, calls, receipts = failed_once(tmp_path, monkeypatch)
    out = Path(path).parent; saved = {i: (out / 'completed' / f'part{i}.json').read_bytes() for i in (0, 2)}
    fresh = direct_attempt(tmp_path); assert science.run(fresh) == 0
    if route == 'exported-rule':
        # Relaunching the export runs the failed partition's own rule: it publishes, it does not dispatch.
        assert site_workflow.main(rule_argv(path, 'task_part1')) == 0
    else:
        site_workflow.publish_partition_delivery(path, 'part1', digest, fresh)
    marker = read_json(out / 'completed' / 'part1.json'); published = read_json(out / 'published' / 'part1.json')
    assert marker['kind'] == 'partition-delivery' and marker['rundir'] == str(fresh)
    assert marker['outputs'] == receipts[str(fresh)]['outputs']
    assert published['retry_ledger'] is None and published['claim']['rundir'] == str(fresh)
    assert site_workflow.main(rule_argv(path, 'fanin_merge')) == 0
    merged = read_json(out / 'completed' / 'merge.json')
    assert merged['consumed_attempts'] == {'p0': tasks[0]['rundir'], 'p1': str(fresh), 'p2': tasks[2]['rundir']}
    # One run per run directory, the failed attempt stays charged, and nothing spent ran again.
    assert len(calls) == len(set(calls)) == 4 and len(claims) == 4 and Path(tasks[1]['rundir']).is_dir()
    assert all((out / 'completed' / f'part{i}.json').read_bytes() == saved[i] for i in (0, 2))
    assert not (project / 'workflow' / 'retries').exists()
    with pytest.raises(ValueError, match='spent WMS step'): site_workflow.run_step(path, 'part1', digest)
    site_workflow.verify(path, digest)


def test_campaign_owned_partition_retried_as_a_new_experiment_reaches_the_merge_rule(tmp_path, monkeypatch):
    project, tasks, manifest, claims, calls, receipts, executions = publication_fixture(tmp_path, monkeypatch)
    path, digest = manifest['path'], manifest['sha256']; document = site_workflow.verify(path, digest)
    spent_guard(monkeypatch, calls); experiments = {'first': tasks[1]['rundir']}; dispatched = []
    owner = {'kind': 'research_cycle', 'cycle': str(tmp_path / 'cycle'), 'experiment': 'first'}
    entry = next(row for row in read_json(project / 'workflow' / 'index.json')['tasks'] if row['id'] == 'part1')
    document['tasks'][1]['owner'] = owner
    site_workflow.verify(entry['export']['path'], entry['export']['sha256'])['tasks'][0]['owner'] = owner
    def run_experiment(root, experiment, resume=False):
        # Stand-in for the campaign route: its admission is the claim boundary the inert run reaches.
        assert root == str(tmp_path / 'cycle') and resume is False
        dispatched.append(experiment); return science.run(experiments[experiment])
    monkeypatch.setattr(cycle, 'run_experiment', run_experiment)
    for i, row in enumerate(tasks):
        if i == 1:
            with pytest.raises(ValueError, match='did not deliver'): dispatch(project, row['id'])
        else: dispatch(project, row['id'])
    # The retry command refuses a campaign-owned partition; its retry is a new campaign experiment.
    index = project / 'workflow' / 'index.json'; rows = read_json(index)
    rows['tasks'][1]['owner'] = document['tasks'][1]['owner']; atomic_json(index, rows)
    with pytest.raises(ValueError, match='new campaign experiment'): wms_retry.retry(project, 'part1')
    experiments['second'] = str(direct_attempt(tmp_path, 'part1-second-experiment'))
    assert cycle.run_experiment(str(tmp_path / 'cycle'), 'second') == 0
    assert site_workflow.main(rule_argv(path, 'task_part1')) == 0
    assert site_workflow.main(rule_argv(path, 'fanin_merge')) == 0
    assert read_json(Path(path).parent / 'completed' / 'merge.json')['consumed_attempts']['p1'] == experiments['second']
    assert dispatched == ['first', 'second'] and len(calls) == len(set(calls)) == 4


def test_original_rule_still_refuses_while_no_other_attempt_delivered(tmp_path, monkeypatch):
    project, tasks, path, digest, claims, calls, receipts = failed_once(tmp_path, monkeypatch, max_attempts=3)
    fresh = direct_attempt(tmp_path); assert science.run(fresh) == 1
    # The failed original and a failed second attempt: the rule publishes nothing and runs nothing.
    # The merge export's rule may not dispatch a governed run; its own indexed rule refuses the spent attempt.
    with pytest.raises(ValueError, match='index does not list this export'): site_workflow.run_step(path, 'part1', digest)
    with pytest.raises(ValueError, match='attempt is spent'): dispatch(project, 'part1')
    assert not (Path(path).parent / 'completed' / 'part1.json').exists()
    assert not (Path(path).parent / 'published' / 'part1.json').exists()
    assert calls.count(tasks[1]['rundir']) == 1 and calls.count(str(fresh)) == 1
    with pytest.raises(ValueError, match='p1.*ravel wms retry'): site_workflow.run_fanin(path, 'merge', digest)
    with pytest.raises(ValueError, match='did not deliver'):
        site_workflow.publish_partition_delivery(path, 'part1', digest, fresh)


@pytest.mark.parametrize('mutation', ['failed_attempt', 'result_pin', 'unpublished'])
def test_direct_retry_publication_refuses_forged_records(tmp_path, monkeypatch, mutation):
    project, tasks, path, digest, claims, calls, receipts = failed_once(tmp_path, monkeypatch)
    fresh = direct_attempt(tmp_path); assert science.run(fresh) == 0
    site_workflow.publish_partition_delivery(path, 'part1', digest, fresh)
    out = Path(path).parent; marker = out / 'completed' / 'part1.json'; publication = out / 'published' / 'part1.json'
    if mutation == 'unpublished': publication.unlink()
    elif mutation == 'failed_attempt':
        value = read_json(publication); value['claim']['rundir'] = tasks[1]['rundir']; atomic_json(publication, value)
    else:
        value = read_json(marker); value['outputs'][0]['sha256'] = '0' * 64; atomic_json(marker, value)
    with pytest.raises(ValueError): site_workflow.run_fanin(path, 'merge', digest)
    assert not (tmp_path / 'draft').exists()


def test_registered_retry_cannot_drop_its_ledger_for_direct_custody(tmp_path, monkeypatch):
    project, path, digest, fresh = delivered_retry(tmp_path, monkeypatch)
    wms_retry.publish_registered_attempt(project, fresh)
    publication = Path(path).parent / 'published' / 'part1.json'
    value = read_json(publication); assert value['retry_ledger'] is not None
    value['retry_ledger'] = None; atomic_json(publication, value)
    with pytest.raises(ValueError, match='registered retry'): site_workflow.run_fanin(path, 'merge', digest)
    assert not (tmp_path / 'draft').exists()


# A project governed from the start: each original runs through its own indexed export.

def test_governed_originals_and_a_retry_reach_the_exported_merge_rule(tmp_path, monkeypatch):
    project, tasks, manifest, claims, calls, receipts, executions = publication_fixture(tmp_path, monkeypatch)
    path, digest = manifest['path'], manifest['sha256']; out = Path(path).parent; spent_guard(monkeypatch, calls)
    # The merge export's partition rule may not dispatch a governed run.
    with pytest.raises(ValueError, match='index does not list this export'): site_workflow.run_step(path, 'part0', digest)
    assert calls == [] and claims == []
    for i, row in enumerate(tasks):
        if i == 1:
            with pytest.raises(ValueError, match='did not deliver'): dispatch(project, row['id'])
        else: dispatch(project, row['id'])
    # Each delivered original reaches the merge export through its own run-step.
    for i in (0, 2):
        marker = read_json(out / 'completed' / f'part{i}.json')
        assert marker['outputs'] == receipts[tasks[i]['rundir']]['outputs'] and 'kind' not in marker
        assert read_json(out / 'published' / f'part{i}.json')['claim']['rundir'] == tasks[i]['rundir']
    assert not (out / 'completed' / 'part1.json').exists()
    saved = {i: (out / 'completed' / f'part{i}.json').read_bytes() for i in (0, 2)}
    spent = json.dumps([executions[row['rundir']] for row in tasks], sort_keys=True); charged = [dict(c) for c in claims]
    with pytest.raises(ValueError, match='p1.*ravel wms retry'): site_workflow.main(rule_argv(path, 'fanin_merge'))
    fresh = Path(wms_retry.retry(project, 'part1')['rundir'])
    science.approve(fresh, ASSENT, scripted=True); registered = wms_retry.retry(project, 'part1')
    assert dispatch(project, registered['task'])['status'] == 'delivered'
    assert read_json(registered['ledger'])['steps'][-1]['action'] == 'delivery-published'
    assert site_workflow.main(rule_argv(path, 'fanin_merge')) == 0
    merged = read_json(out / 'completed' / 'merge.json')
    assert merged['consumed_attempts'] == {'p0': tasks[0]['rundir'], 'p1': str(fresh), 'p2': tasks[2]['rundir']}
    # Nothing spent ran again and every spent attempt record is unchanged.
    assert len(calls) == len(set(calls)) == 4 and claims[:3] == charged and len(claims) == 4
    assert json.dumps([executions[row['rundir']] for row in tasks], sort_keys=True) == spent
    assert all((out / 'completed' / f'part{i}.json').read_bytes() == saved[i] for i in (0, 2))
    for row in tasks:
        with pytest.raises(ValueError, match='spent WMS step'): site_workflow.run_step(path, row['id'], digest)
    site_workflow.verify(path, digest)


@pytest.mark.parametrize('stopped', ['merge-export-marker', 'indexed-marker'])
def test_delivered_original_whose_completion_marker_was_never_written_is_published_without_running_again(
        tmp_path, monkeypatch, stopped):
    project, tasks, manifest, claims, calls, receipts, executions = publication_fixture(tmp_path, monkeypatch, failing=())
    path, digest = manifest['path'], manifest['sha256']; out = Path(path).parent; spent_guard(monkeypatch, calls)
    entry = next(row for row in read_json(project / 'workflow' / 'index.json')['tasks'] if row['id'] == 'part0')
    target = (out if stopped == 'merge-export-marker' else Path(entry['export']['path']).parent) / 'completed' / 'part0.json'
    original_write = s.write_new
    def interrupted(where, value):
        if Path(where) == target: raise OSError('synthetic interruption before the completion marker')
        return original_write(where, value)
    monkeypatch.setattr(s, 'write_new', interrupted)
    with pytest.raises(OSError, match='synthetic interruption'): dispatch(project, 'part0')
    monkeypatch.setattr(s, 'write_new', original_write)
    for row in tasks[1:]: dispatch(project, row['id'])
    assert not (out / 'completed' / 'part0.json').exists()
    with pytest.raises((ValueError, OSError)): site_workflow.run_fanin(path, 'merge', digest)
    assert not (tmp_path / 'draft').exists()
    spent = json.dumps(executions[tasks[0]['rundir']], sort_keys=True); charged = [dict(c) for c in claims]
    # Relaunching the merge export runs the partition's own rule: it publishes the delivered original.
    assert site_workflow.main(rule_argv(path, 'task_part0')) == 0
    marker = read_json(out / 'completed' / 'part0.json')
    assert marker['outputs'] == receipts[tasks[0]['rundir']]['outputs'] and 'kind' not in marker
    assert site_workflow.main(rule_argv(path, 'fanin_merge')) == 0
    assert read_json(out / 'completed' / 'merge.json')['consumed_attempts'] == {f'p{i}': tasks[i]['rundir'] for i in range(3)}
    assert calls == [row['rundir'] for row in tasks] and claims == charged and len(claims) == 3
    assert json.dumps(executions[tasks[0]['rundir']], sort_keys=True) == spent
    site_workflow.verify(path, digest)


def dependent_task(tmp_path, monkeypatch, path, digest, receipts, calls):
    """Add one ordinary task that depends on the second partition to the inert export."""
    document = site_workflow.verify(path, digest); rd = tmp_path / 'project' / 'runs' / 'after'
    science.plan(rd, str(tmp_path / 'master' / 'p1-spec.json')); admit_method(rd); science.approve(rd, ASSENT, scripted=True)
    document['tasks'].append({**task_row('after', rd), 'depends_on': ['part1'], 'output_directory': 'outputs'})
    partition_run = science.run
    def run(target, **kwargs):
        if Path(target) != rd: return partition_run(target, **kwargs)
        calls.append(str(rd)); folder = rd / 'outputs'; folder.mkdir()
        receipts[str(rd)] = {'outputs': [put(folder, 'result.json', {'status': 'passed', 'physics_validated': False}),
                                         put(folder, 'verification.json', {'passed': True, 'physics_validated': False})],
                             'fingerprint': 'after-1'}
        return 0
    monkeypatch.setattr(science, 'run', run)
    return rd


@pytest.mark.parametrize('custody', ['registered', 'direct'])
def test_ordinary_task_depending_on_a_retried_partition_runs_after_its_publication(tmp_path, monkeypatch, custody):
    project, tasks, path, digest, claims, calls, receipts = failed_once(tmp_path, monkeypatch)
    rd = dependent_task(tmp_path, monkeypatch, path, digest, receipts, calls)
    # Before any attempt delivered, the dependent task is refused and does not run.
    with pytest.raises(ValueError, match='p1.*ravel wms retry'): site_workflow.run_step(path, 'after', digest)
    if custody == 'registered':
        fresh = Path(wms_retry.retry(project, 'part1')['rundir'])
        science.approve(fresh, ASSENT, scripted=True); wms_retry.retry(project, 'part1')
        assert science.run(fresh) == 0
        with pytest.raises(ValueError, match='not published'): site_workflow.run_step(path, 'after', digest)
        wms_retry.publish_registered_attempt(project, fresh)
    else:
        fresh = direct_attempt(tmp_path); assert science.run(fresh) == 0
        site_workflow.publish_partition_delivery(path, 'part1', digest, fresh)
    assert str(rd) not in calls
    assert site_workflow.run_step(path, 'after', digest)['status'] == 'delivered'
    assert calls.count(str(rd)) == 1 and calls.count(tasks[1]['rundir']) == 1


def test_ordinary_task_refuses_a_forged_retry_marker_of_its_partition_dependency(tmp_path, monkeypatch):
    project, tasks, path, digest, claims, calls, receipts = failed_once(tmp_path, monkeypatch)
    rd = dependent_task(tmp_path, monkeypatch, path, digest, receipts, calls)
    fresh = direct_attempt(tmp_path); assert science.run(fresh) == 0
    site_workflow.publish_partition_delivery(path, 'part1', digest, fresh)
    marker = Path(path).parent / 'completed' / 'part1.json'
    value = read_json(marker); value['rundir'] = tasks[1]['rundir']; atomic_json(marker, value)
    with pytest.raises(ValueError): site_workflow.run_step(path, 'after', digest)
    assert str(rd) not in calls


def later_export(tmp_path, monkeypatch, path, digest, receipts, calls):
    """A second inert export whose ordinary task names the second partition of the first export in `after`."""
    rd = dependent_task(tmp_path, monkeypatch, path, digest, receipts, calls)
    site_workflow.verify(path, digest)['tasks'].pop()
    out = Path(path).parent.parent / 'later'; (out / 'completed').mkdir(parents=True)
    doc = {'tasks': [{**task_row('after', rd), 'after': [{'task': 'part1', 'export': path, 'export_sha256': digest}],
                      'output_directory': 'outputs'}], 'python': pin(sys.executable)}
    manifest = s.write_new(out / 'workflow.json', doc)
    (out / 'Snakefile').write_bytes(site_workflow._snakefile(out / 'workflow.json', doc))
    earlier = site_workflow.verify
    monkeypatch.setattr(site_workflow, 'verify', lambda p, d: doc if Path(p) == out / 'workflow.json' and d == manifest['sha256'] else earlier(p, d))
    return manifest['path'], manifest['sha256'], rd


@pytest.mark.parametrize('custody', ['registered', 'direct'])
def test_task_of_a_later_export_consumes_a_retried_partition_through_its_after_row(tmp_path, monkeypatch, custody):
    project, tasks, path, digest, claims, calls, receipts = failed_once(tmp_path, monkeypatch)
    later, later_digest, rd = later_export(tmp_path, monkeypatch, path, digest, receipts, calls)
    # Before any attempt delivered, the later task is refused, names the retry and does not run.
    with pytest.raises(ValueError, match='p1.*ravel wms retry'): site_workflow.run_step(later, 'after', later_digest)
    if custody == 'registered':
        fresh = Path(wms_retry.retry(project, 'part1')['rundir'])
        science.approve(fresh, ASSENT, scripted=True); wms_retry.retry(project, 'part1')
        assert science.run(fresh) == 0
        with pytest.raises(ValueError, match='not published'): site_workflow.run_step(later, 'after', later_digest)
        wms_retry.publish_registered_attempt(project, fresh)
    else:
        fresh = direct_attempt(tmp_path); assert science.run(fresh) == 0
        site_workflow.publish_partition_delivery(path, 'part1', digest, fresh)
    assert str(rd) not in calls
    assert site_workflow.run_step(later, 'after', later_digest)['status'] == 'delivered'
    assert calls.count(str(rd)) == 1 and calls.count(tasks[1]['rundir']) == 1


@pytest.mark.parametrize('forgery', ['marker-rundir', 'unpublished', 'dropped-ledger', 'unfinished-visibility'])
def test_task_of_a_later_export_refuses_a_forged_retry_publication(tmp_path, monkeypatch, forgery):
    project, tasks, path, digest, claims, calls, receipts = failed_once(tmp_path, monkeypatch)
    later, later_digest, rd = later_export(tmp_path, monkeypatch, path, digest, receipts, calls)
    fresh = Path(wms_retry.retry(project, 'part1')['rundir'])
    science.approve(fresh, ASSENT, scripted=True); registered = wms_retry.retry(project, 'part1')
    assert science.run(fresh) == 0
    if forgery == 'unfinished-visibility':
        original = wms_retry.record_delivery_publication
        def interrupted(*args, **kwargs):
            if kwargs.get('visible'): raise OSError('synthetic visibility interruption')
            return original(*args, **kwargs)
        monkeypatch.setattr(wms_retry, 'record_delivery_publication', interrupted)
        with pytest.raises(OSError): wms_retry.publish_registered_attempt(project, fresh)
        monkeypatch.setattr(wms_retry, 'record_delivery_publication', original)
    else: wms_retry.publish_registered_attempt(project, fresh)
    out = Path(path).parent; marker = out / 'completed' / 'part1.json'; publication = out / 'published' / 'part1.json'
    if forgery == 'marker-rundir':
        value = read_json(marker); value['rundir'] = tasks[1]['rundir']; atomic_json(marker, value)
    elif forgery == 'unpublished': publication.unlink()
    elif forgery == 'dropped-ledger':
        value = read_json(publication); value['retry_ledger'] = None; atomic_json(publication, value)
    with pytest.raises(ValueError): site_workflow.run_step(later, 'after', later_digest)
    assert str(rd) not in calls and not (Path(later).parent / 'completed' / 'after.json').exists()


def lost_supervisor_record():
    """The execution record that supervised recovery leaves when the leader and its group are absent."""
    import socket
    return {'status': 'failed', 'exit_code': 130, 'finished_utc': 'synthetic-terminal', 'child_pid': 43210,
            'child_identity': 'synthetic-start', 'child_identity_host': socket.gethostname(),
            'interrupted_finalization': {'schema_version': 1, 'kind': 'interrupted-attempt-negative-finalization',
                                         'descendant_containment': 'not_established', 'requires_recovery': True,
                                         'scientific_acceptance': False},
            'cleanup': {'group_state': 'empty', 'remaining_group_members': [], 'requires_recovery': True,
                        'descendant_containment': 'not_established'}}


def test_lost_supervisor_recovery_hold_is_reported_as_a_hold_not_as_a_pending_command(tmp_path, monkeypatch):
    record = lost_supervisor_record()
    monkeypatch.setattr(science.execution, 'load_execution', lambda rd: {'stages': {'science': record}})
    monkeypatch.setattr(science.execution, 'process_identity', lambda pid: None)
    monkeypatch.setattr(p, 'master_fanout', lambda m: {'max_attempts': 2})
    assert p.attempt_state(tmp_path) == 'unresolved'
    refusal = p.retry_admission({}, [{'task_id': 'p', 'rundir': str(tmp_path)}], 'p')
    command = f'ravel run --rundir {tmp_path} --resume'
    assert 'held' in refusal and 'descendant' in refusal and 'does not make this attempt retryable' in refusal
    assert command in refusal and 'before a retry' not in refusal
    # A record that recovery has not yet finalized still names the command as the next step.
    record.pop('interrupted_finalization'); record['cleanup'] = {}; record.update(status='running', exit_code=None)
    pending = p.retry_admission({}, [{'task_id': 'p', 'rundir': str(tmp_path)}], 'p')
    assert f'run `{command}` on the recording host before a retry' in pending and 'held' not in pending


def test_merge_rule_names_the_lost_supervisor_hold(tmp_path, monkeypatch):
    project, tasks, manifest, claims, calls, receipts, executions = publication_fixture(tmp_path, monkeypatch)
    rd = tasks[1]['rundir']; assert science.run(rd) == 1; executions[rd] = lost_supervisor_record()
    monkeypatch.setattr(science.execution, 'process_identity', lambda pid: None)
    with pytest.raises(ValueError, match='p1.*held.*does not make this attempt retryable') as refused:
        site_workflow.run_fanin(manifest['path'], 'merge', manifest['sha256'])
    assert 'on the recording host' not in str(refused.value)
    assert not (tmp_path / 'draft').exists()


def test_reference_states_the_lost_supervisor_limitation():
    packaged = Path(site_workflow.__file__).resolve().parents[1] / 'data' / 'workflow'
    text = ' '.join(next(packaged.rglob('site-workflows.md')).read_text().split())
    assert 'does not establish that its descendants ended' in text
    assert 'does not make the attempt retryable' in text
