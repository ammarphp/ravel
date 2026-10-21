"""A governed external-workflow request: adopted and planned before CHECK-IN 1, inspected and run only after it.

The controller's prepare launch adopts the supplied workflow (a static scan and pins), writes the pinned site
profile and plans one governed study (``inspect-run``); it parses, runs and approves nothing. The approved
study first repeats the four dry runs of an inspection and runs only when that inspection passes and, for a
batch site, schedules exactly the approved job count as one fan-out. The stand-in manager of the adoption tests
executes the Snakefile's leading Python the way a parse does, so its parse witness means the same thing here.
"""
import json
from pathlib import Path

import pytest

from ravel.workflow import method_selection, science, wms_adopt, wms_site
from test_wms_adopt import (REAL, WITNESS, calls, launched, log_of, study, supervised,  # noqa: F401
                            workflow)


def _request(site=None, **extra):
    task = {'schema_version': 1, 'operation': 'run', 'snakefile': 'wf/Snakefile', 'targets': ['final.txt'],
            'cores': 1, **extra}
    if site is not None:
        task['site'] = site
    return task


def _prepare(workflow, task, *, document=None):
    base = workflow['base']
    child, root = base / 'run/children/study', base / 'run/children/study.workflow'
    result = wms_adopt.prepare_governed(task, document or study(), base=base, child=child, workflow_root=root,
                                        snakemake=workflow['snakemake'])
    return result, child, root


def _nothing_ran(workflow, root):
    return not (root / 'work' / WITNESS).exists() and (REAL or calls(workflow) == [])


def test_preparation_adopts_and_plans_but_parses_runs_and_approves_nothing(workflow):
    result, child, root = _prepare(workflow, _request({'scheduler': 'htcondor', 'jobs': 2}))
    assert _nothing_ran(workflow, root) and sorted(p.name for p in (root / 'work').iterdir()) == []
    assert result['snakefile_parsed'] is False and result['execution_authorized'] is False
    assert not (child / science.APPROVAL).exists(), 'the controller approves the study after CHECK-IN 1'
    assert (child / method_selection.DECISION_PATH).is_file(), 'the method choice is part of the proposal'
    task = json.loads((child / science.SPEC).read_text())['task']
    record = json.loads((root / 'adoption/adoption.json').read_text())
    assert task['operation'] == 'inspect-run' and task['jobs'] == 2
    assert task['commands'] == wms_adopt.inspection_commands(record)
    assert all('--dry-run' in argv for argv in task['commands'].values())
    assert task['command'] == wms_adopt.run_command(record) and '--dry-run' not in task['command']
    profile = json.loads((Path(result['site']['profile_dir']) / 'profile.json').read_text())
    assert profile['options']['submission'] == 'broker'
    assert profile['options']['workflow_dir'] == str(root / 'work')
    launch = result['site_launch']
    assert launch['batch'] == 2 and launch['wms_scope']['max_jobs'] == 2
    assert launch['wms_scope']['rules'] == sorted({row['name'] for row in record['rules']}) == ['all', 'first', 'second']
    assert launch['wms_scope']['profile_sha256'] == wms_site.profile_pin(result['site']['profile_dir'])['sha256']
    assert launch['site_broker'] == {'profile_dir': result['site']['profile_dir'],
                                     'publish_dir': str((root / 'work').resolve().parent / '.ravel-controller-submissions')}
    assert result['adoption'] == wms_adopt._pin(root / 'adoption/adoption.json')


def test_a_local_request_plans_a_governed_study_without_a_site_launch(workflow):
    result, child, root = _prepare(workflow, _request())
    assert result['site'] is None and result['site_launch'] is None
    task = json.loads((child / science.SPEC).read_text())['task']
    assert task['operation'] == 'inspect-run' and task['jobs'] is None
    assert not (root / 'profiles').exists() and _nothing_ran(workflow, root)


@pytest.mark.parametrize('damage, message', [
    ('approval', 'approval_mode must say scripted_yes'),
    ('reused', 'fresh'),
    ('absolute', 'plain relative path'),
    ('site', 'scheduler and jobs'),
])
def test_preparation_refusals_create_nothing(workflow, damage, message):
    task, document = _request(), study()
    base = workflow['base']
    if damage == 'approval':
        document['approval_mode'] = 'expert'
    elif damage == 'reused':
        (base / 'run/children/study').mkdir(parents=True)
        (base / 'run/children/study/leftover.txt').write_text('an earlier attempt\n')
    elif damage == 'absolute':
        task['snakefile'] = str(workflow['snakefile'])
    else:
        task['site'] = {'scheduler': 'htcondor', 'jobs': 2, 'queue': 'any'}
    with pytest.raises(ValueError, match=message):
        _prepare(workflow, task, document=document)
    assert not (base / 'run/children/study.workflow').exists() and (REAL or calls(workflow) == [])


def _governed(workflow, **options):
    """An adoption record and its governed task, for the adapter's own inspect-run step."""
    if REAL:
        pytest.skip('stand-in executable only')
    wms_adopt.adopt(workflow['snakefile'], workflow['workdir'], workflow['rundir'], study(),
                    snakemake=workflow['snakemake'], **options)
    path = workflow['rundir'] / 'adoption.json'
    record = json.loads(path.read_text())
    return path, record, wms_adopt._governed_task(record)


def test_inspect_run_inspects_with_dry_runs_then_runs_and_binds_its_inspection(workflow, tmp_path):
    path, record, task = _governed(workflow, targets=['final.txt'], outputs=['final.txt'])
    folder = tmp_path / 'stage-out'
    folder.mkdir()
    receipt, inspection = wms_adopt._inspect_run(path, record, task, folder)
    assert inspection['status'] == 'passed' and inspection['jobs_run'] == 0
    assert json.loads((folder / 'inspection' / wms_adopt.INSPECTION).read_text()) == inspection
    assert receipt['status'] == 'passed' and receipt['exit_code'] == 0
    assert (workflow['workdir'] / 'final.txt').read_text() == 'first\n'
    dry = [argv for argv in calls(workflow) if '--dry-run' in argv or '--list-rules' in argv]
    assert len(dry) == 5, 'four inspection calls, then the preflight dry run of the run'
    assert len(launched(workflow)) == 1


def test_inspect_run_refuses_a_failed_inspection_before_any_job(workflow, tmp_path, monkeypatch):
    path, record, task = _governed(workflow)
    folder = tmp_path / 'stage-out'
    folder.mkdir()
    monkeypatch.setattr(wms_adopt, '_inspect', lambda path, record, folder: {
        'status': 'failed', 'problems': ['the `jobs` call exited 1'], 'roster': {'jobs': []}})
    monkeypatch.setattr(wms_adopt, '_run', lambda *args: pytest.fail('a failed inspection never runs'))
    with pytest.raises(ValueError, match='did not pass: the `jobs` call exited 1. Nothing was submitted or run'):
        wms_adopt._inspect_run(path, record, task, folder)


def test_a_batch_inspect_run_starts_only_for_one_fan_out_of_the_approved_job_count(workflow, tmp_path, monkeypatch):
    path, record, task = _governed(workflow)
    monkeypatch.setattr(wms_adopt, '_run', lambda *args: pytest.fail('a refused bound never runs'))
    folder = tmp_path / 'chain'
    folder.mkdir()
    # The synthetic workflow is a chain (second consumes first): not one immediate fan-out.
    with pytest.raises(ValueError, match="consume another batch job's output"):
        wms_adopt._inspect_run(path, record, {**task, 'jobs': 2}, folder)
    folder = tmp_path / 'count'
    folder.mkdir()
    monkeypatch.setattr(wms_adopt, 'require_fanout', lambda inspection: [{'rule': 'first'}, {'rule': 'second'}])
    with pytest.raises(ValueError, match='schedules 2 batch job\\(s\\); the approved plan bounds this run to 3'):
        wms_adopt._inspect_run(path, record, {**task, 'jobs': 3}, folder)


def test_the_governed_task_is_validated_and_bound_to_its_adoption(workflow, tmp_path):
    path, record, task = _governed(workflow)
    wms_adopt.validate(task)
    for broken in ({**task, 'roster': {}}, {**task, 'jobs': 0}, {**task, 'jobs': '2'},
                   {key: value for key, value in task.items() if key != 'commands'}):
        with pytest.raises(ValueError):
            wms_adopt.validate(broken)
    base = workflow['rundir']
    assert [str(p) for p in wms_adopt.inputs(task, base)][0] == str(path)
    with pytest.raises(ValueError, match='different run command'):
        wms_adopt.inputs({**task, 'command': [*task['command'], '--forceall']}, base)
    with pytest.raises(ValueError, match='different inspection commands'):
        wms_adopt.inputs({**task, 'commands': {**task['commands'], 'jobs': ['changed']}}, base)
    with pytest.raises(ValueError, match='batch job count'):
        wms_adopt.inputs({**task, 'jobs': 4}, base)


def test_the_approved_governed_study_inspects_then_runs_as_one_supervised_stage(workflow):
    supervised()
    result, child, root = _prepare(workflow, _request(outputs=['final.txt']))
    assert _nothing_ran(workflow, root)
    # The controller's own approval after CHECK-IN 1 (here: the scripted assent the study declares).
    science.approve(child, 'Approved synthetic governed workflow control', scripted=True)
    assert science.run(child) == 0, log_of(child)
    out = child / 'outputs/attempt-1'
    stage = json.loads((out / 'result.json').read_text())
    assert stage['status'] == 'passed' and stage['operation'] == 'inspect-run' and stage['physics_validated'] is False
    inspection = json.loads((out / 'external-workflow/inspection' / wms_adopt.INSPECTION).read_text())
    assert inspection['status'] == 'passed' and stage['inspection']['sha256'] == wms_adopt._pin(
        out / 'external-workflow/inspection' / wms_adopt.INSPECTION)['sha256']
    receipt = json.loads((out / 'external-workflow' / wms_adopt.RECEIPT).read_text())
    assert receipt['status'] == 'passed' and receipt['outputs'][0]['output'] == 'final.txt'
    assert (root / 'work/final.txt').read_text() == 'first\n'
