"""Governed replay: prepare, fresh approval, run and compare of a completed ordinary science run.

The terminal adapter and worker are a tiny synthetic fixture. Planning, approval, launch
authorization, supervision, the execution ledger and the replay records are the real ones.
Numbers are synthetic and carry no physics meaning.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ravel.workflow import replay, science, execution, method_selection
from ravel.workflow.state_io import atomic_json, read_json
from method_decision_fixture import admit_method

WORKER = r'''
import json, os, random, sys, uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
package, rd = sys.argv[1], Path(sys.argv[2])
sys.path.insert(0, package)
from ravel.workflow import science, execution
def inputs(task, base):
    return [Path(base) / task['payload'], Path(__file__).resolve()]
science.adapter = lambda _: SimpleNamespace(validate=lambda _: None, inputs=inputs,
                                            _validation_inputs=lambda t, b, s: inputs(t, b))
science.module_command = lambda module, *args, python=None: [sys.executable, '-B', sys.argv[0], package,
                                                             *(str(a) for a in args)]
proposal = science.verify_worker(rd)
plan = json.loads((rd / 'inputs/science-plan.json').read_text())
payload = json.loads((Path(plan['base_dir']) / plan['execution_task']['payload']).read_text())
out = Path(proposal['output_directory']); out.mkdir(parents=True)
weights = payload['weights']
bins = [[w for w in weights if i <= w * 10 % 4 < i + 1] for i in range(4)]
result = {'status': 'passed', 'physics_validated': False,
          'generated_utc': datetime.now(timezone.utc).isoformat(), 'job_uuid': str(uuid.uuid4()),
          'attempt_id': os.environ.get('RAVEL_ATTEMPT_ID', str(os.getpid())),
          'histogram': {'sumw': [sum(b) for b in bins], 'sumw2': [sum(w * w for w in b) for b in bins],
                        'counts': [len(b) for b in bins]},
          'limit': {'mu95': sum(weights) / 7.0}}
if payload.get('sampled'):
    seed = int.from_bytes(os.urandom(4), 'big')
    rng = random.Random(seed)
    draws = [rng.gauss(10.0, 1.0) for _ in range(400)]
    mean = sum(draws) / len(draws)
    result['sampled'] = {'mean': mean, 'error': 1.0 / len(draws) ** .5}
    if payload['sampled'] == 'seeded':
        result['sampled']['seed'] = seed
(out / 'result.json').write_text(json.dumps(result, indent=2))
digest = execution.file_hash(out / 'result.json')
(out / 'verification.json').write_text(json.dumps({'passed': True, 'scope': plan['mode'], 'physics_validated': False,
    'expert_review': False, 'result_sha256': digest}))
'''

POLICY = {'schema_version': 1, 'actors': {'proposer': 'producer', 'executor': 'executor', 'physics_critic': 'critic',
          'skeptical_verifier': 'skeptic', 'physics_decider': 'decider'}, 'max_redos': 0, 'allowed_changed_paths': [],
          'allowed_stages': ['science'], 'required_checks': [{'id': 'integrity', 'kind': 'integrity'}],
          'claim_scopes': {'engineering': {'checks': ['integrity'], 'actions': ['delivery']}}}
MACHINE = 'Scripted machine assent to an identical replay plan; not expert or physicist review'


def patch(monkeypatch, worker):
    package = str(Path(science.__file__).resolve().parents[2])
    def inputs(task, base):
        return [Path(base) / task['payload'], worker]
    def command(module, *args, python=None):
        assert module == 'ravel.physics.science_worker'
        return [sys.executable, '-B', str(worker), package, *(str(a) for a in args)]
    monkeypatch.setattr(science, 'module_command', command)
    monkeypatch.setattr(science, 'adapter', lambda spec: SimpleNamespace(
        validate=lambda task: None, inputs=inputs, _validation_inputs=lambda t, b, s: inputs(t, b)))


def source(base, *, sampled=None):
    base.mkdir(parents=True)
    payload = {'weights': [0.125, 0.25, 0.5, 1.5, 2.25, 3.0, -0.75], **({'sampled': sampled} if sampled else {})}
    atomic_json(base / 'payload.json', payload)
    spec = {'schema_version': 2, 'mode': 'likelihood-parity', 'source': 'Synthetic replay control',
            'assumptions': ['Synthetic numbers; no physics calculation'], 'max_seconds': 60, 'max_attempts': 1,
            'approval_mode': 'scripted_yes', 'task': {'payload': 'payload.json'},
            'review_policy': {'schema_version': 1, 'policy': POLICY,
                              'correction_contract': {'task_fields': [], 'input_slots': []}}}
    atomic_json(base / 'spec.json', spec)
    return base / 'spec.json'


def complete(rd, spec):
    science.plan(rd, spec)
    admit_method(rd)
    science.approve(rd, 'Scripted assent to a synthetic replay control', scripted=True)
    science.run(rd)
    assert execution.load_execution(rd)['stages']['science']['status'] == 'succeeded', \
        (Path(rd) / 'logs/science-worker-1.log').read_text()
    return Path(rd).resolve()


def prepared(original, into, **options):
    return replay.prepare(original, into, **options)


def disclosure(record):
    """The statement clauses for the recorded differences: environment names, then locations."""
    names = set(record['disclosed_differences'])
    environment, locations = sorted(names - {'base_dir', 'rundir'}), sorted(names & {'base_dir', 'rundir'})
    return (('environment differs: ' + ', '.join(environment) if environment else 'no environment difference recorded')
            + ('; locations differ: ' + ', '.join(locations) if locations else ''))


@pytest.fixture(scope='module')
def worker(tmp_path_factory):
    path = tmp_path_factory.mktemp('replay-runtime') / 'worker.py'
    path.write_text(WORKER)
    return path.resolve()


@pytest.fixture(scope='module')
def original(tmp_path_factory, worker):
    root = tmp_path_factory.mktemp('replay-original')
    with pytest.MonkeyPatch.context() as mp:
        # A module fixture works in the module's own test lock domain (tests/conftest.py).
        patch(mp, worker)
        rd = complete(root / 'original', source(root / 'source'))
    return root, rd


@pytest.fixture(autouse=True)
def synthetic_adapter(monkeypatch, worker):
    patch(monkeypatch, worker)


def test_prepare_refuses_a_recorded_input_whose_digest_changed(original, tmp_path):
    root, rd = original
    payload = root / 'source/payload.json'
    before = payload.read_bytes()
    payload.write_bytes(before.replace(b'0.125', b'0.126'))
    try:
        with pytest.raises(ValueError, match=r'recorded inputs differ.*<BASE>/payload\.json'):
            prepared(rd, tmp_path / 'replay')
        assert not (tmp_path / 'replay').exists()
    finally:
        payload.write_bytes(before)


def test_prepare_writes_replay_record_and_checkin_line(original, tmp_path):
    root, rd = original
    result = prepared(rd, tmp_path / 'replay')
    into = Path(result['rundir'])
    record = read_json(into / replay.RECORD)
    assert record['original']['plan_sha256'] == execution.file_hash(rd / science.PLAN)
    assert record['original']['approval']['sha256'] == execution.file_hash(rd / science.APPROVAL)
    assert {Path(p['path']).name for p in record['original']['result_pins']} == {'result.json', 'verification.json'}
    assert len(record['original']['attempt_journal_pins']) == 1
    assert record['original_approval_reused'] is False and record['execution_authorized'] is False
    section = read_json(into / 'inputs/checkin1.json')['sections']['replay']
    assert section['statement'] == f'replay of {rd}: identical plan; ' + disclosure(record)
    assert 'Replay of' in (into / 'CHECKIN1.md').read_text()
    assert not (into / science.APPROVAL).exists() and not (into / 'execution_state.json').exists()
    # The original run is untouched and its CHECK-IN 1 has no replay line.
    assert 'replay' not in read_json(rd / 'inputs/checkin1.json')['sections']
    science.verify_plan(rd, approved=True)


def test_prepare_carries_the_method_decision_of_the_original(original, tmp_path):
    root, rd = original
    into = Path(prepared(rd, tmp_path / 'replay')['rundir'])
    decision = method_selection.DECISION_PATH
    assert (into / decision).read_bytes() == (rd / decision).read_bytes()
    record = read_json(into / replay.RECORD)
    assert record['method_decision'] == {'path': decision, 'sha256': execution.file_hash(rd / decision),
                                         'original': str(rd / decision)}
    assert 'method_decision' in read_json(into / 'inputs/checkin1.json')['sections']
    assert method_selection.launch_errors(into, 'full') == []


def test_prepare_refuses_an_original_without_its_method_decision(tmp_path):
    rd = complete(tmp_path / 'original', source(tmp_path / 'source'))
    (rd / method_selection.DECISION_PATH).unlink()
    with pytest.raises(ValueError, match='method decision'):
        prepared(rd, tmp_path / 'replay')
    assert not (tmp_path / 'replay').exists()


def test_replay_without_fresh_approval_and_with_copied_original_approval_is_refused(original, tmp_path):
    root, rd = original
    into = Path(prepared(rd, tmp_path / 'replay')['rundir'])
    with pytest.raises((OSError, ValueError)):
        science.run(into)
    with pytest.raises(ValueError, match='ravel approve'):
        replay.approval_gate(into)
    shutil.copyfile(rd / science.APPROVAL, into / science.APPROVAL)
    with pytest.raises(ValueError, match='stale study approval'):
        science.run(into)
    with pytest.raises(ValueError, match=r'ravel approve --rundir'):
        replay.approval_gate(into)
    assert not (into / 'execution_state.json').exists()


def test_tampered_replay_record_cannot_be_approved(original, tmp_path):
    root, rd = original
    into = Path(prepared(rd, tmp_path / 'replay')['rundir'])
    record = read_json(into / replay.RECORD)
    record['original']['source'] = str(tmp_path / 'elsewhere')
    (into / replay.RECORD).write_text(json.dumps(record))
    with pytest.raises(ValueError, match='check-in does not describe'):
        science.approve(into, MACHINE, scripted=True)


def test_end_to_end_replay_compares_equal(original, tmp_path):
    root, rd = original
    into = Path(prepared(rd, tmp_path / 'replay')['rundir'])
    science.approve(into, MACHINE, scripted=True)
    gate = replay.approval_gate(into)
    assert gate['approval_mode'] == 'scripted_yes' and gate['expert_review'] is False
    assert gate['original_approval_reused'] is False
    receipt = replay.launch(into)
    assert receipt['route'] == 'ordinary-run' and receipt['physics_validated'] is False
    # The synthetic worker writes no CHECK-IN 2 or review, so neither lifecycle passes; both must agree.
    verdicts = [science.packet(r)['lifecycle_verdict'] for r in (rd, into)]
    assert verdicts[0] == verdicts[1] and receipt['exit_code'] == (0 if verdicts[1] == 'PASS' else 3), (verdicts, receipt)
    assert execution.load_execution(into)['stages']['science']['status'] == 'succeeded'
    a, b = read_json(rd / 'outputs/attempt-1/result.json'), read_json(into / 'outputs/attempt-1/result.json')
    assert a['job_uuid'] != b['job_uuid'] and a['generated_utc'] != b['generated_utc']
    comparison = replay.compare(rd, into)
    assert comparison['verdict'] == 'equal', comparison['mismatches']
    assert comparison['physics_validated'] is False and comparison['replay_record_names_original'] is True
    assert comparison['leaves_compared'] > 10
    # A spent replay attempt is never reopened.
    with pytest.raises(ValueError, match='attempt is spent'):
        science.run(into)


@pytest.mark.parametrize('seeded', [True, False])
def test_sampled_quantity_needs_recorded_seeds(tmp_path, seeded):
    spec = source(tmp_path / 'source', sampled='seeded' if seeded else 'unseeded')
    rd = complete(tmp_path / 'original', spec)
    into = Path(prepared(rd, tmp_path / 'replay')['rundir'])
    science.approve(into, MACHINE, scripted=True)
    replay.launch(into)
    rule = {'document': 'result.json', 'pointer': '/sampled/mean', 'seed_pointer': '/sampled/seed',
            'n_sigma': 5, 'uncertainty_pointer': '/sampled/error'}
    atomic_json(tmp_path / 'tolerances.json', {'schema_version': 1, 'statistical': [rule]})
    comparison = replay.compare(rd, into, tmp_path / 'tolerances.json')
    if seeded:
        assert comparison['verdict'] == 'equal', comparison['mismatches']
        assert any(r['reason'] == 'recorded seed of a sampled quantity' for r in comparison['ignored'])
    else:
        assert comparison['verdict'] == 'not_comparable' and comparison['equal'] is False
        assert comparison['not_comparable'] == [{'document': 'result.json', 'pointer': '/sampled/mean',
                                                 'reason': 'not comparable: seed not recorded'}]


def test_packaged_run_prepares_with_relocated_inputs(original, tmp_path):
    root, rd = original
    package = tmp_path / 'package'
    (package / 'results').mkdir(parents=True)
    atomic_json(package / 'submission.json', {'schema_version': 1})
    for path in sorted(rd.rglob('*')):
        relative = path.relative_to(rd)
        if path.is_file() and (len(relative.parts) == 1 or relative.parts[0] == 'inputs'
                               or (relative.parts[0] == 'logs' and relative.parts[1] == 'execution' and path.name == 'record.json')):
            (package / 'run' / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, package / 'run' / relative)
    shutil.copyfile(rd / 'outputs/attempt-1/result.json', package / 'results/result.json')
    fetched = tmp_path / 'fetched'
    shutil.copytree(root / 'source', fetched)
    result = prepared(package, tmp_path / 'replay', inputs_root=fetched)
    record = read_json(Path(result['rundir']) / replay.RECORD)
    assert record['original']['kind'] == 'package'
    assert record['disclosed_differences']['base_dir'] == {'original': str(root / 'source'), 'replay': str(fetched)}
    assert [Path(p['path']).name for p in record['original']['result_pins']] == ['result.json']
    # The run holds a document the package lacks; a package original reports it as a directory does.
    comparison = replay.compare(package, rd)
    assert comparison['verdict'] == 'mismatch'
    assert comparison['mismatches'] == [{'document': 'verification.json', 'pointer': '',
                                         'reason': 'document absent from the original'}]
    shutil.copyfile(rd / 'outputs/attempt-1/verification.json', package / 'results/verification.json')
    assert replay.compare(package, rd)['verdict'] == 'equal'


def test_research_bound_experiment_is_refused_with_its_owner(original, tmp_path):
    root, rd = original
    fake = tmp_path / 'experiment'
    shutil.copytree(rd, fake, ignore=shutil.ignore_patterns('*.lock'))
    plan_value = read_json(fake / science.PLAN)
    plan_value['research_binding'] = {'root': str(tmp_path / 'cycle'), 'experiment_id': 'synthetic'}
    atomic_json(fake / science.PLAN, plan_value)
    with pytest.raises(ValueError, match='research cycle'):
        replay.prepare(fake, tmp_path / 'replay')


def test_root_stream_partition_child_is_refused_with_its_owner(tmp_path, monkeypatch):
    from ravel.physics import root_stream_partitions as partitions
    from root_partition_ordinary_fixture import prepare_fixture
    monkeypatch.undo()
    source_dir = tmp_path / 'source'
    _, _, _, spec, proof = prepare_fixture(source_dir, monkeypatch)
    request = {'schema_version': 1, 'specification': spec, 'partition_entries': 100, 'max_partitions': 100,
               'grouping': {'kind': 'independent_entries', 'source': proof, 'statement': 'Synthetic entry premise'},
               'owner': {'kind': 'research_cycle', 'cycle': str(source_dir / 'cycle')},
               'budget': {'partition_seconds': 20, 'merge_seconds': 20, 'max_total_seconds': 40}}
    part = partitions.prepare(request, source_dir, tmp_path / 'master')['partition_specifications'][0]
    science.plan(tmp_path / 'child', part['specification']['path'])
    with pytest.raises(ValueError, match='partition child'):
        replay.prepare(tmp_path / 'child', tmp_path / 'replay')
    assert not (tmp_path / 'replay').exists()


def test_incomplete_original_is_refused(tmp_path):
    rd = tmp_path / 'planned'
    science.plan(rd, source(tmp_path / 'source'))
    with pytest.raises(ValueError, match='completed original'):
        replay.prepare(rd, tmp_path / 'replay')


def test_cli_routes_replay_operations_and_refuses_a_bare_replay(original, tmp_path, capsys):
    from ravel import cli
    assert cli.main(['replay', 'template']) == 0
    assert capsys.readouterr().out == replay.template_text()
    root, rd = original
    assert cli.main(['replay', 'compare', '--original', str(rd), '--replay', str(rd),
                     '--out', str(tmp_path / 'self.json')]) == 0
    assert read_json(tmp_path / 'self.json')['verdict'] == 'equal'
    assert cli.main(['replay', 'approval-gate', '--rundir', str(rd)]) == 2
    assert 'is not a prepared replay' in capsys.readouterr().err
    protected = tmp_path / 'exists'
    protected.mkdir()
    with pytest.raises(SystemExit) as refused:
        cli.main(['replay', '--out', str(protected)])
    assert refused.value.code == 2


@pytest.mark.skipif(not os.environ.get('RAVEL_TEST_SNAKEMAKE'), reason='set RAVEL_TEST_SNAKEMAKE to run real Snakemake')
def test_template_dry_runs_and_approval_gate_names_ravel_approve(tmp_path):
    from ravel.workflow import wms_runtime
    snakemake = wms_runtime.snakemake_argv()
    work = tmp_path / 'work'
    work.mkdir()
    (work / 'replay.smk').write_text(replay.template_text())
    ravel = f'{sys.executable} -m ravel'
    config = ['--config', f'original={tmp_path / "original"}', f'replay={tmp_path / "replay"}', f'ravel={ravel}']
    dry = subprocess.run([*snakemake, '-n', '--snakefile', str(work / 'replay.smk'), '--directory', str(work),
                          '--cores', '1', *config], capture_output=True, text=True, timeout=300)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    for rule in ('replay_prepare', 'replay_approval_gate', 'replay_run', 'replay_compare'):
        assert rule in dry.stdout + dry.stderr
    (work / 'replay-prepared.json').write_text('{}\n')
    env = dict(os.environ, PYTHONPATH=str(Path(replay.__file__).resolve().parents[2]))
    gate = subprocess.run([*snakemake, '--snakefile', str(work / 'replay.smk'), '--directory', str(work),
                           '--cores', '1', 'replay-approved.json', *config], capture_output=True, text=True,
                          timeout=300, env=env)
    assert gate.returncode != 0
    assert 'ravel approve --rundir' in gate.stdout + gate.stderr
    assert not (work / 'replay-approved.json').exists()


def test_end_to_end_through_the_workflow_manager(original, tmp_path):
    if replay._wms() is None:
        pytest.xfail('awaits SMK-03')
    if not os.environ.get('RAVEL_TEST_SNAKEMAKE'):
        pytest.skip('set RAVEL_TEST_SNAKEMAKE to run real Snakemake')
    from ravel.workflow import wms_launch
    root, rd = original
    project = tmp_path / 'project'
    project.mkdir()
    record = project / 'audit.json'
    atomic_json(record, {'synthetic': 'software only'})
    policy = project / 'blind-policy.json'
    atomic_json(policy, {'schema_version': 1, 'policy': 'exclude_signal_region_data_from_model_and_analysis',
                         'review_source': {'path': str(record), 'sha256': execution.file_hash(record),
                                           'size': record.stat().st_size}, 'original_domain': None})
    wms_launch.init(project, audit={'prompts': [str(record)], 'model_build': 'synthetic-build',
                                    'timestamps': ['2026-01-01T00:00:00Z'], 'token_accounting': str(record),
                                    'environment': str(record), 'tracked_skill_sources': [str(record)],
                                    'blinding_policy': str(policy)}, python=sys.executable)
    into = Path(prepared(rd, project / 'replay')['rundir'])
    science.approve(into, MACHINE, scripted=True)
    receipt = replay.launch(into, project=project, task='replay')
    assert receipt['route'] == 'workflow-manager' and receipt['exit_code'] == 0
    assert replay.compare(rd, into)['verdict'] == 'equal'


@pytest.fixture
def recorded_original(tmp_path):
    """Real planned/approved records with inert synthetic outputs; no worker launch."""
    rd = tmp_path / 'recorded-original'
    science.plan(rd, source(tmp_path / 'recorded-source'))
    admit_method(rd)
    science.approve(rd, MACHINE, scripted=True)
    atomic_json(rd / 'outputs/attempt-1/result.json', {'quantity': 1.73})
    atomic_json(rd / 'execution_state.json', {'schema_version': 1, 'revision': 1, 'stages': {
        'science': {'status': 'succeeded', 'outputs': ['outputs/attempt-1']}}})
    return rd


def environment_fingerprints(monkeypatch, original, *, different):
    fingerprint = replay._fingerprint
    def changed(plan, records, base):
        value, disclosed = fingerprint(plan, records, base)
        # Keep location disclosures equal to isolate the synthetic package census.
        disclosed = {'runtime': {'packages': {'synthetic-package': '1.0'}}, 'interpreter': None}
        if different and Path(records) != original:
            disclosed['runtime']['packages']['synthetic-package'] = '2.0'
        return value, disclosed
    monkeypatch.setattr(replay, '_fingerprint', changed)


@pytest.mark.parametrize('different', [False, True])
def test_checkin_discloses_environment_values(recorded_original, tmp_path, monkeypatch, different):
    environment_fingerprints(monkeypatch, recorded_original, different=different)
    into = Path(prepared(recorded_original, tmp_path / 'replay')['rundir'])
    record = read_json(into / replay.RECORD)
    section = read_json(into / 'inputs/checkin1.json')['sections']['replay']
    line = (into / 'CHECKIN1.md').read_text()
    assert section['disclosed_differences'] == record['disclosed_differences']
    if different:
        assert 'identical plan; environment differs: runtime' in section['statement']
        assert 'identical plan; environment differs: runtime' in line
        for value in ('synthetic-package', '1.0', '2.0'):
            assert value in json.dumps(section) and value in line
    else:
        assert 'no environment difference recorded' in section['statement']
        assert 'no environment difference recorded' in line


def test_a_new_run_directory_is_a_location_not_an_environment_difference(recorded_original, tmp_path):
    into = Path(prepared(recorded_original, tmp_path / 'replay')['rundir'])
    record = read_json(into / replay.RECORD)
    assert sorted(record['disclosed_differences']) == ['rundir']
    section = read_json(into / 'inputs/checkin1.json')['sections']['replay']
    statement = (f'replay of {recorded_original}: identical plan; no environment difference recorded; '
                 'locations differ: rundir')
    assert section['statement'] == statement
    assert section['disclosed_differences'] == {'rundir': {'original': str(recorded_original), 'replay': str(into)}}
    line = (into / 'CHECKIN1.md').read_text()
    assert statement[len('replay of '):] in line and 'environment differs' not in line
    assert f'- rundir: original "{recorded_original}"; replay "{into}"' in line


def test_editing_environment_disclosures_refuses_approval(recorded_original, tmp_path, monkeypatch):
    environment_fingerprints(monkeypatch, recorded_original, different=True)
    into = Path(prepared(recorded_original, tmp_path / 'replay')['rundir'])
    record = read_json(into / replay.RECORD)
    record['disclosed_differences']['runtime']['replay']['packages']['synthetic-package'] = '3.0'
    atomic_json(into / replay.RECORD, record)
    with pytest.raises(ValueError, match='check-in does not describe'):
        science.approve(into, MACHINE, scripted=True)


def test_omitting_environment_disclosure_refuses_approval(recorded_original, tmp_path, monkeypatch):
    environment_fingerprints(monkeypatch, recorded_original, different=True)
    into = Path(prepared(recorded_original, tmp_path / 'replay')['rundir'])
    checkin = read_json(into / 'inputs/checkin1.json')
    checkin['sections']['replay'].get('disclosed_differences', {}).pop('runtime', None)
    atomic_json(into / 'inputs/checkin1.json', checkin)
    with pytest.raises(ValueError, match='check-in does not describe'):
        science.approve(into, MACHINE, scripted=True)


def undisclosed_edit(record, field, tmp_path):
    """Change one part of the replay record that no CHECK-IN line names."""
    if field == 'spec_sha256':
        record['original']['spec_sha256'] = '0' * 64
    elif field == 'result_pins':
        record['original']['result_pins'][0]['sha256'] = '0' * 64
    else:
        record['original']['attempt_journal_pins'].append(
            {'path': str(tmp_path / 'synthetic-attempt.json'), 'sha256': '0' * 64, 'size': 1})
    return record


@pytest.mark.parametrize('field', ['result_pins', 'attempt_journal_pins', 'spec_sha256'])
def test_editing_any_part_of_the_replay_record_refuses_approval(recorded_original, tmp_path, field):
    into = Path(prepared(recorded_original, tmp_path / 'replay')['rundir'])
    atomic_json(into / replay.RECORD, undisclosed_edit(read_json(into / replay.RECORD), field, tmp_path))
    with pytest.raises(ValueError, match='check-in does not describe'):
        science.approve(into, MACHINE, scripted=True)
    assert not (into / science.APPROVAL).exists()


@pytest.mark.parametrize('field', ['result_pins', 'attempt_journal_pins', 'spec_sha256'])
def test_editing_the_replay_record_after_approval_invalidates_it(recorded_original, tmp_path, field):
    into = Path(prepared(recorded_original, tmp_path / 'replay')['rundir'])
    science.approve(into, MACHINE, scripted=True)
    assert replay.approval_gate(into)['approved'] is True
    approved_record = read_json(into / replay.RECORD)
    atomic_json(into / replay.RECORD, undisclosed_edit(read_json(into / replay.RECORD), field, tmp_path))
    with pytest.raises(ValueError, match='check-in does not describe'):
        science.verify_plan(into, approved=True)
    with pytest.raises(ValueError, match='no fresh approval of its own plan'):
        replay.approval_gate(into)
    with pytest.raises(ValueError, match='no fresh approval of its own plan'):
        replay.launch(into)
    assert not (into / 'execution_state.json').exists()
    # The approved CHECK-IN binds the complete record, not only the fields its statement names.
    section = read_json(into / 'inputs/checkin1.json')['sections']['replay']
    assert section['record_sha256'] == replay._digest(approved_record)


@pytest.mark.parametrize('refusal', ['different', 'unreadable'])
def test_refused_prepare_can_retry_without_identical_plan_claim(recorded_original, tmp_path, monkeypatch, refusal):
    target = tmp_path / 'replay'
    fingerprint = replay._fingerprint
    def changed(plan, records, base):
        value, disclosed = fingerprint(plan, records, base)
        if Path(records) != recorded_original:
            if refusal == 'unreadable':
                raise ValueError('replay refused: synthetic fingerprint unreadable')
            value['mode'] = 'different-synthetic-mode'
        return value, disclosed
    with monkeypatch.context() as mp:
        mp.setattr(replay, '_fingerprint', changed)
        with pytest.raises(ValueError, match='replay refused'):
            prepared(recorded_original, target)
    assert not any('identical plan' in p.read_text() for p in target.rglob('*') if p.is_file())
    assert prepared(recorded_original, target)['identical_plan'] is True


def test_template_compare_fails_closed_and_quotes_tolerances():
    text = replay.template_text().split('rule replay_compare:')[1]
    assert '--exit-zero' not in text
    assert '{params.tolerances:q}' in text


@pytest.mark.skipif(not os.environ.get('RAVEL_TEST_SNAKEMAKE'), reason='set RAVEL_TEST_SNAKEMAKE to run real Snakemake')
def test_template_mismatch_fails_with_retained_receipt_and_quoted_path(recorded_original, tmp_path):
    from ravel.workflow import wms_runtime
    other = tmp_path / 'other'
    shutil.copytree(recorded_original, other)
    atomic_json(other / 'outputs/attempt-1/result.json', {'quantity': 99.0})
    work = tmp_path / 'workflow'
    work.mkdir()
    (work / 'replay.smk').write_text(replay.template_text())
    for name in ('replay-prepared.json', 'replay-approved.json', 'replay-run.json'):
        (work / name).write_text('{}\n')
    rules = tmp_path / "tolerances with spaces ' and $literal.json"
    atomic_json(rules, {'schema_version': 1})
    command = [*wms_runtime.snakemake_argv(), '--snakefile', str(work / 'replay.smk'),
               '--directory', str(work), '--cores', '1', '--executor', 'local', '--config',
               f'original={recorded_original}', f'replay={other}', f'ravel={sys.executable} -B -m ravel',
               f'tolerances={rules}']
    done = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert done.returncode != 0, done.stdout + done.stderr
    receipt = read_json(other / replay.COMPARISON)
    assert receipt['verdict'] == 'mismatch'
    assert receipt['mismatches'][0]['document'] == 'result.json'
