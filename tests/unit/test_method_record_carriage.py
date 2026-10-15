"""Every route that starts governed work from an existing record carries the method decision.

A workflow-manager launch, a replay and a retry each start a full scientific stage from a run
directory that already exists. Each one either finds inputs/method-decision.json in the
directory it launches or is refused before any stage process starts.

Synthetic fake-reader fixture only: no ROOT, site, scheduler or physics qualification.
"""
import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest

from ravel.physics import root_stream as stream, root_stream_partitions as partitions
from ravel.workflow import method_selection, science, site_workflow, stage_supervisor, wms_launch
from ravel.workflow.state_io import atomic_json, read_json
from method_decision_fixture import admit_method
from root_partition_ordinary_fixture import WRAPPER, ordinary, prepare_fixture
from root_stream_fixture import put

RECORD = method_selection.DECISION_PATH
ASSENT = 'Synthetic software fixture; scripted assent is not expert review'
REFUSAL = 'Scientific full launch refused'


def absent(module):
    return importlib.util.find_spec(module) is None


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assert_carried(origin, created, *bindings):
    """The created directory holds the origin's record: the same bytes, or a record a binding document pins."""
    record = Path(created) / RECORD
    assert record.is_file(), f'{created} was created without {RECORD}'
    assert method_selection.launch_errors(created, 'full') == []
    original = digest(Path(origin) / RECORD)
    bound = any(original in Path(document).read_text() for document in bindings if Path(document).is_file())
    assert digest(record) == original or bound


def no_stage_process(monkeypatch):
    """Fail the test if any supervised stage reaches its process launch."""
    def started(*args, **kwargs):
        pytest.fail('a stage process was started without the method decision')
    monkeypatch.setattr(stage_supervisor.subprocess, 'Popen', started)


def audit_files(root):
    proof = put(root, 'audit/proof.json', {'synthetic': 'software only'})
    return proof, {'prompts': [proof['path']], 'model_build': 'exact-synthetic-build', 'timestamps': ['2026-10-09T00:00:00Z'],
                   'token_accounting': proof['path'], 'environment': proof['path'], 'tracked_skill_sources': [proof['path']]}


def governed_project(tmp_path, monkeypatch):
    """A workflow-manager project over the ordinary fake-reader study, built with `wms init`."""
    root = tmp_path / 'project'
    root.mkdir()
    _, analysis, _, spec, proof = prepare_fixture(root / 'source', monkeypatch)
    _, audit = audit_files(root)
    audit['blinding_policy'] = put(root, 'audit/blind-policy.json', {
        'schema_version': 1, 'policy': 'exclude_signal_region_data_from_model_and_analysis',
        'review_source': proof, 'original_domain': analysis['blinding']['source']})['path']
    wms_launch.init(root, audit=audit)
    return root, spec


def approved_run(rd, spec):
    science.plan(rd, spec['path'])
    admit_method(rd)
    science.approve(rd, ASSENT, scripted=True)
    return rd


def no_snakemake(monkeypatch):
    """A resolvable workflow manager that fails the test if the launch reaches it."""
    monkeypatch.setattr(wms_launch.wms_runtime, 'snakemake_argv', lambda explicit=None: ['/synthetic/snakemake'])
    monkeypatch.setattr(wms_launch.wms_runtime, 'snakemake_version', lambda argv: '9.27.0')

    def execute(argv, cwd):
        pytest.fail('the workflow manager was started without the method decision')
    monkeypatch.setattr(wms_launch, '_execute', execute)


# ---------------------------------------------------------------- 1. workflow-manager runs

def test_workflow_manager_task_with_the_record_passes_the_launch_check(tmp_path, monkeypatch):
    project, spec = governed_project(tmp_path, monkeypatch)
    rd = approved_run(project / 'runs/study', spec)
    entry = wms_launch.add(project, rd)
    assert entry['rundir'] == str(rd.resolve()) and (rd / RECORD).is_file()
    assert method_selection.launch_errors(rd, 'full') == []
    assert wms_launch.status(project)['tasks'][0]['delivered'] is False


def test_workflow_manager_launch_without_the_record_is_refused_and_starts_nothing(tmp_path, monkeypatch):
    project, spec = governed_project(tmp_path, monkeypatch)
    rd = approved_run(project / 'runs/study', spec)
    entry = wms_launch.add(project, rd)
    assert entry['id'] == 'study'
    (rd / RECORD).unlink()
    assert method_selection.launch_errors(rd, 'full')[0].startswith(REFUSAL)
    no_snakemake(monkeypatch)
    no_stage_process(monkeypatch)
    with pytest.raises(ValueError, match=REFUSAL) as refusal:
        wms_launch.launch(project, 'study')
    assert 'Nothing was started' in str(refusal.value) and str(rd / RECORD) in str(refusal.value)
    assert not any((project / 'workflow/launches').iterdir()) and not (project / 'workflow/exports/study/dispatch').exists()
    assert not (rd / 'execution_state.json').exists() and not (rd / 'outputs').exists()
    view = wms_launch.status(project)['tasks'][0]
    assert view['delivered'] is False and view['launches'] == 0 and view['dispatches'] == 0
    # The run step itself, called as the workflow manager would call it, is refused as well.
    with pytest.raises(ValueError):
        site_workflow.run_step(entry['export']['path'], entry['id'], entry['export']['sha256'])
    assert not (rd / 'execution_state.json').exists() and not (project / 'workflow/exports/study/dispatch').exists()


def test_direct_run_of_an_ungoverned_copy_without_the_record_is_refused(tmp_path, monkeypatch):
    """The refusal belongs to the launch itself, not to the workflow manager."""
    root = tmp_path / 'source'
    _, _, _, spec, _ = prepare_fixture(root, monkeypatch)
    rd = approved_run(tmp_path / 'study', spec)
    (rd / RECORD).unlink()
    no_stage_process(monkeypatch)
    with pytest.raises(ValueError, match=REFUSAL):
        science.run(rd)
    assert not (rd / 'execution_state.json').exists()


# ---------------------------------------------------------------- 2. replays

def test_replay_run_directory_carries_the_record_of_the_completed_run(tmp_path, monkeypatch):
    from ravel.workflow import replay
    _, _, _, spec, _ = prepare_fixture(tmp_path / 'source', monkeypatch)
    ordinary(spec, tmp_path / 'original')
    original = science.root(tmp_path / 'original')
    prepared = replay.prepare(original, tmp_path / 'replay')
    replayed = Path(prepared['rundir'])
    assert_carried(original, replayed, replayed / replay.RECORD)


def test_replay_launch_without_the_record_is_refused_and_starts_nothing(tmp_path, monkeypatch):
    from ravel.workflow import replay
    _, _, _, spec, _ = prepare_fixture(tmp_path / 'source', monkeypatch)
    ordinary(spec, tmp_path / 'original')
    replayed = Path(replay.prepare(science.root(tmp_path / 'original'), tmp_path / 'replay')['rundir'])
    if not (replayed / RECORD).is_file():
        admit_method(replayed)  # the approval below is of a complete directory; the record is removed after it
    science.approve(replayed, ASSENT, scripted=True)
    (replayed / RECORD).unlink()
    no_stage_process(monkeypatch)
    with pytest.raises(ValueError):
        replay.launch(replayed)
    assert method_selection.launch_errors(replayed, 'full')[0].startswith(REFUSAL)
    assert not (replayed / 'execution_state.json').exists()


# ---------------------------------------------------------------- 3. retries

def failed_partition_task(tmp_path, monkeypatch):
    """One-partition project whose first attempt ran and failed after its claim.

    The attempt runs before the project index lists it: an indexed run directory
    is dispatched only by the workflow manager, which this fixture does not start.
    """
    from ravel.workflow import research_cycle as cycle, wms_retry
    from root_partition_ordinary_fixture import contract
    root = tmp_path / 'source'
    _, _, cfg, spec, proof = prepare_fixture(root, monkeypatch)
    cfg['limits'].update(max_seconds=400, max_chunks=1000)
    value = read_json(spec['path'])
    value['task']['config'] = put(root, 'scaled-config.json', cfg)
    value['max_seconds'] = 400
    owner = contract(root)
    owner['budget'].update(wall_seconds=10000, native_attempts=1000)
    cycle.create(root / 'scaled-cycle', owner, base_dir=root, evaluation_harness=True)
    request = {'schema_version': 1, 'specification': put(root, 'scaled-spec.json', value), 'partition_entries': 100,
               'max_partitions': 200,
               'grouping': {'kind': 'independent_entries', 'source': proof, 'statement': 'Pinned synthetic independent entry premise'},
               'owner': {'kind': 'research_cycle', 'cycle': str(root / 'scaled-cycle')},
               'budget': {'partition_seconds': 90, 'merge_seconds': 90, 'max_total_seconds': 270},
               'fanout': {'max_attempts': 2, 'wms': {'profile': 'local', 'cores': 1, 'jobs': 1, 'remote_ceiling': 1}}}
    prepared = partitions.prepare(request, root, tmp_path / 'master')
    project = tmp_path / 'project'
    workflow = project / 'workflow'
    workflow.mkdir(parents=True)
    rd = project / 'runs/part'
    failing = root / 'failing'
    failing.mkdir()
    (failing / 'ordinary_reader.py').write_text(WRAPPER.replace(
        "    raw=w.read_pinned", "    raise ValueError('synthetic attempt failure')\n    raw=w.read_pinned"))
    (failing / 'events.json').write_bytes((root / 'runtime/events.json').read_bytes())
    source_root = Path(stream.__file__).parents[2]
    working = science.module_command
    monkeypatch.setattr(science, 'module_command', lambda module, *args, python=None: [
        sys.executable, '-B', str(failing / 'ordinary_reader.py'), str(source_root), *(str(x) for x in args)])
    science.plan(rd, prepared['partition_specifications'][0]['specification']['path'])
    admit_method(rd)
    science.approve(rd, ASSENT, scripted=True)
    try:
        science.run(rd)
    except (ValueError, RuntimeError):
        pass
    assert science.execution.load_execution(rd)['stages']['science']['status'] == 'failed'
    monkeypatch.setattr(science, 'module_command', working)
    atomic_json(workflow / 'index.json', {'schema_version': 1, 'tasks': [
        {'id': 'part', 'rundir': str(rd), 'owner': {'kind': 'ordinary'}}]})
    return wms_retry, project, rd


def test_retry_attempt_directory_carries_the_record_of_the_failed_attempt(tmp_path, monkeypatch):
    wms_retry, project, rd = failed_partition_task(tmp_path, monkeypatch)
    planned = wms_retry.retry(project, 'part')
    fresh = Path(planned['rundir'])
    assert planned['status'] == 'planned' and fresh != rd
    assert_carried(rd, fresh, planned['ledger'])
    assert (fresh / RECORD).read_bytes() == (rd / RECORD).read_bytes()
    assert planned['method_decision_sha256'] == digest(rd / RECORD)
    assert read_json(planned['ledger'])['steps'][-1]['method_decision_sha256'] == digest(rd / RECORD)


def test_retry_attempt_without_the_record_is_refused_and_starts_nothing(tmp_path, monkeypatch):
    wms_retry, project, rd = failed_partition_task(tmp_path, monkeypatch)
    fresh = Path(wms_retry.retry(project, 'part')['rundir'])
    if not (fresh / RECORD).is_file():
        admit_method(fresh)  # the approval below is of a complete directory; the record is removed after it
    science.approve(fresh, ASSENT, scripted=True)
    (fresh / RECORD).unlink()
    no_stage_process(monkeypatch)
    with pytest.raises(ValueError, match=REFUSAL):
        science.run(fresh)
    assert not (fresh / 'execution_state.json').exists()


def test_retry_without_origin_method_record_refuses_before_planning(tmp_path, monkeypatch):
    wms_retry, project, rd = failed_partition_task(tmp_path, monkeypatch)
    (rd / RECORD).unlink()
    no_stage_process(monkeypatch)
    with pytest.raises(ValueError, match=REFUSAL):
        wms_retry.retry(project, 'part')
    assert not list(rd.parent.glob('part-attempt*'))
    assert not (project / 'workflow/retries').exists()


def test_retry_registration_refuses_changed_carried_method_record(tmp_path, monkeypatch):
    wms_retry, project, rd = failed_partition_task(tmp_path, monkeypatch)
    planned = wms_retry.retry(project, 'part')
    fresh = Path(planned['rundir'])
    # A valid but differently serialized record must not replace the origin bytes.
    if not (fresh / RECORD).exists():
        admit_method(fresh)
    (fresh / RECORD).write_bytes((rd / RECORD).read_bytes() + b'\n')
    method_selection.refresh_checkin(fresh)
    science.approve(fresh, ASSENT, scripted=True)
    calls = []
    monkeypatch.setattr(wms_retry, '_registrar', lambda: lambda *a, **k: calls.append(a) or {'id': 'part_a2'})
    with pytest.raises(ValueError, match='method.decision.*differ'):
        wms_retry.retry(project, 'part')
    assert calls == []


def test_retry_registration_uses_the_real_project_add_route(tmp_path, monkeypatch):
    wms_retry, project, rd = failed_partition_task(tmp_path, monkeypatch)
    spec = read_json(rd / science.SPEC)
    cap = stream.core.Capture()
    _, _, _, analysis = stream._load(spec['task'], rd, cap)
    cap.finish()
    proof, audit = audit_files(project)
    audit['blinding_policy'] = put(project, 'audit/blind-policy.json', {
        'schema_version': 1, 'policy': 'exclude_signal_region_data_from_model_and_analysis',
        'review_source': proof, 'original_domain': analysis['blinding']['source']})['path']
    wms_launch.init(project, audit=audit)
    fresh = Path(wms_retry.retry(project, 'part')['rundir'])
    science.approve(fresh, ASSENT, scripted=True)
    receipt = wms_retry.retry(project, 'part')
    assert wms_retry._registrar() is wms_launch.add
    entry = read_json(project / 'workflow/index.json')['tasks'][-1]
    assert receipt['task'] == entry['id'] == 'part_a2'
    assert receipt['method_decision_sha256'] == digest(rd / RECORD) == digest(fresh / RECORD)
    assert (project / 'workflow/rules/part_a2.smk').is_file()
    assert site_workflow.verify(entry['export']['path'], entry['export']['sha256'])['tasks'][0]['rundir'] == str(fresh)
