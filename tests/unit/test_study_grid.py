"""Synthetic allocation grids, durable retries, declared-axis harvest and refusal controls."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import itertools
import json
from pathlib import Path
import sys

import pytest

from ravel import cli
from ravel.workflow import allocation_study as al
from ravel.workflow import machine_lease as ml
from ravel.workflow import study_grid as sg


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))
    return path


@pytest.fixture
def grid(tmp_path, monkeypatch):
    venv = tmp_path / 'venv'
    (venv / 'bin').mkdir(parents=True)
    (venv / 'bin/python').write_text('')
    cells = []
    for index, (u, v, scenario) in enumerate(itertools.product([1, 2], [3, 4], ['baseline', 'variation'])):
        root = tmp_path / f'cell-{index}'
        spec = write(root / 'inputs/science.json', {'schema_version': 1, 'task': {'coordinate': [u, v]}})
        cells.append(dict(id=f'cell-{index}', axes=dict(u=u, v=v), scenario=scenario,
                          study_spec=str(spec), rundir=str(root), agent=['synthetic-agent']))
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    manifest = write(tmp_path / 'grid.json', dict(
        schema_version=1, axes=[dict(name='u', values=[1, 2]), dict(name='v', values=[3, 4])],
        scenarios=['baseline', 'variation'], cells=cells,
        approval=dict(rundir=cells[0]['rundir'], route='checkin1', rung='none', approval_files={}, expires_utc=expiry),
        budget=dict(max_submissions=12, max_cpu_minutes=120, expires_utc=expiry),
        allocation=dict(account='synthetic', partition='batch', cpus=1, minutes=10,
                        venv=str(venv), checkout=str(tmp_path), collect_to=str(tmp_path / 'collected')),
        concurrency=8, quantities=[dict(name='quantity', source='outputs/result.json', field='value')]))
    sbatch = tmp_path / 'sbatch'
    sbatch.write_text('#!/bin/sh\nn=0\n[ ! -f "$0.count" ] || n=$(cat "$0.count")\nn=$((n + 1))\n'
                      'echo "$n" > "$0.count"\necho "$n;synthetic"\n')
    sbatch.chmod(0o755)
    actual_submit = al.submit
    monkeypatch.setattr(al, 'submit', lambda directory, **kw: actual_submit(directory, sbatch=str(sbatch)))
    monkeypatch.setattr(al, '_scheduler_state', lambda job: 'pending')
    monkeypatch.setattr(al, '_scope_records', lambda destination: {})
    return manifest, tmp_path / 'grid-state'


def change(grid, **updates):
    doc = sg.read_json(grid[0])
    doc.update(updates)
    write(grid[0], doc)
    return doc


def finish(grid, monkeypatch, *, only=None, exit_code=0, result=True):
    ledger = sg.read_json(grid[1] / sg.LEDGER)
    previous, finished = al._scheduler_state, set()
    for index, (cid, row) in enumerate(ledger['cells'].items()):
        if not row['attempts'] or (only is not None and cid not in only):
            continue
        attempt = row['attempts'][-1]
        directory = Path(attempt['request_dir'])
        request = sg.read_json(directory / 'request.json')
        root = Path(request['rundir'])
        job = attempt['job_id']
        monkeypatch.setattr(ml, 'slurm_allocation', lambda *a, job=job, **kw: {'cluster': 'synthetic', 'job_id': job})
        monkeypatch.setattr(ml, 'allocation_identity', lambda job=job: {'scope': f'synthetic-{job}', 'job_id': job})
        class Child:
            def __init__(self, *args, **kwargs):
                if result:
                    result_doc = {'value': float(index + 1)}
                    if request.get('point_override'):
                        result_doc['point_receipt_sha256'] = request['point_override']['record']['receipt_sha256']
                        assert kwargs['env']['RAVEL_POINT_RECEIPT_SHA256'] == result_doc['point_receipt_sha256']
                    write(root / 'outputs/result.json', result_doc)
            def wait(self):
                return exit_code
        assert al.run(directory / 'request.json', popen=Child) == exit_code
        finished.add(job)
    monkeypatch.setattr(al, '_scheduler_state', lambda job: 'completed' if job in finished else previous(job))


def test_complete_grid_submission_collection_and_typed_harvest(grid, monkeypatch):
    ledger = sg.submit(*grid)
    assert len({c['attempts'][0]['job_id'] for c in ledger['cells'].values()}) == 8
    finish(grid, monkeypatch)
    harvest = sg.harvest(*grid)
    assert isinstance(harvest, sg.GridHarvest)
    assert len(harvest.cells) == 8
    assert {c.status for c in harvest.cells} == {'completed'}
    for cell in harvest.cells:
        artifact = cell.artifacts['quantity']
        assert artifact.sha256 == al._sha(artifact.path)
        assert '/collected/' in artifact.path
        assert cell.scenario in ('baseline', 'variation') and set(cell.axes) == {'u', 'v'}


def test_duplicate_refusal_even_after_completion(grid, monkeypatch):
    sg.submit(*grid)
    with pytest.raises(ValueError, match='duplicate'):
        sg.submit(*grid)
    finish(grid, monkeypatch)
    with pytest.raises(ValueError, match='duplicate'):
        sg.submit(*grid)
    ledger = sg.submit(*grid, resume=True)
    assert all(len(c['attempts']) == 1 for c in ledger['cells'].values())


def test_resume_after_partial_submit_and_enforce_concurrency(grid, monkeypatch):
    doc = sg.read_json(grid[0])
    change(grid, concurrency=2)
    ledger = sg.submit(*grid)
    assert sum(bool(c['attempts']) for c in ledger['cells'].values()) == 2
    ledger = sg.submit(*grid, resume=True)
    assert sum(bool(c['attempts']) for c in ledger['cells'].values()) == 2
    finish(grid, monkeypatch)
    ledger = sg.submit(*grid, resume=True)
    assert sum(bool(c['attempts']) for c in ledger['cells'].values()) == 4
    assert all(len(c['attempts']) <= 1 for c in ledger['cells'].values())
    assert doc['cells'][0]['id'] in ledger['cells']


def test_crash_after_scheduler_submit_recovers_submission_without_resubmit(grid, monkeypatch):
    original = al.submit
    def interrupted(directory, **kw):
        original(directory, **kw)
        raise RuntimeError('synthetic caller crash after scheduler acceptance')
    monkeypatch.setattr(al, 'submit', interrupted)
    with pytest.raises(RuntimeError):
        sg.submit(*grid)
    ledger = sg.status(*grid)
    assert ledger['cells']['cell-0']['attempts'][0]['job_id'] == '1'
    monkeypatch.setattr(al, 'submit', original)
    ledger = sg.submit(*grid, resume=True)
    assert all(len(c['attempts']) == 1 for c in ledger['cells'].values())


def test_ambiguous_submission_is_not_automatically_retried(grid, monkeypatch):
    def interrupted(*a, **kw):
        raise RuntimeError('synthetic lost reply')
    monkeypatch.setattr(al, 'submit', interrupted)
    with pytest.raises(RuntimeError):
        sg.submit(*grid)
    ledger = sg.status(*grid)
    assert ledger['cells']['cell-0']['attempts'][0]['status'] == 'unknown'
    with pytest.raises(ValueError, match='only terminal'):
        sg.submit(*grid, resume=True, supersede=['cell-0'])


def test_refused_submission_is_a_failed_cell_that_frees_its_slot(grid, tmp_path):
    (tmp_path / 'sbatch').write_text('#!/bin/sh\necho refused >&2\nexit 1\n')
    with pytest.raises(ValueError, match='refused'):
        sg.submit(*grid)
    ledger = sg.status(*grid)
    attempt = ledger['cells']['cell-0']['attempts'][0]
    assert attempt['status'] == 'failed' and attempt['job_id'] is None and 'refused' in attempt['error']
    # No job exists, so the cell is explicit, charged, and may be superseded deliberately.
    assert sum(a['cpu_minutes'] for c in ledger['cells'].values() for a in c['attempts']) == 10


@pytest.mark.parametrize('state', ['failed', 'cancelled', 'timed-out', 'missing', 'unknown'])
def test_failed_and_missing_cells_remain_explicit_without_retry(grid, monkeypatch, state):
    sg.submit(*grid)
    monkeypatch.setattr(al, '_scheduler_state', lambda job: state)
    harvest = sg.harvest(*grid)
    assert {c.status for c in harvest.cells} == {state}
    assert all(not c.values for c in harvest.cells)
    ledger = sg.submit(*grid, resume=True)
    assert all(len(c['attempts']) == 1 for c in ledger['cells'].values())


def test_missing_result_stays_a_hole_despite_successful_agent(grid, monkeypatch):
    sg.submit(*grid)
    finish(grid, monkeypatch, result=False)
    harvest = sg.harvest(*grid)
    assert all(c.status == 'missing' and not c.values and c.detail for c in harvest.cells)


def test_scheduler_completion_without_collection_is_missing(grid, monkeypatch):
    sg.submit(*grid)
    monkeypatch.setattr(al, '_scheduler_state', lambda job: 'completed')
    assert {c.status for c in sg.harvest(*grid).cells} == {'missing'}


def test_explicit_supersession_preserves_original_attempt_and_budget(grid, monkeypatch):
    sg.submit(*grid)
    monkeypatch.setattr(al, '_scheduler_state', lambda job: 'failed')
    ledger = sg.submit(*grid, resume=True, supersede=['cell-0'])
    row = ledger['cells']['cell-0']['attempts']
    assert len(row) == 2 and row[0]['superseded'] and row[0]['job_id'] != row[1]['job_id']
    assert sum(a['cpu_minutes'] for c in ledger['cells'].values() for a in c['attempts']) == 90


@pytest.mark.parametrize('budget', [dict(max_submissions=1), dict(max_cpu_minutes=10)])
def test_budget_exhaustion_stops_further_submission(grid, budget):
    doc = sg.read_json(grid[0])
    change(grid, budget=doc['budget'] | budget)
    with pytest.raises(ValueError, match='budget exhausted'):
        sg.submit(*grid)
    ledger = sg.read_json(grid[1] / sg.LEDGER)
    assert sum(len(c['attempts']) for c in ledger['cells'].values()) == 1


@pytest.mark.parametrize('which', ['approval', 'budget'])
def test_expiry_is_rechecked_between_submissions(grid, monkeypatch, which):
    doc = sg.read_json(grid[0])
    clock = datetime.now(timezone.utc)
    expiry = clock + timedelta(minutes=1)
    doc[which]['expires_utc'] = expiry.isoformat()
    write(grid[0], doc)
    class Clock:
        fromisoformat = datetime.fromisoformat
        @staticmethod
        def now(tz):
            return clock
    monkeypatch.setattr(sg, 'datetime', Clock)
    original = al.submit
    def advance(*a, **kw):
        nonlocal clock
        job = original(*a, **kw)
        clock = expiry + timedelta(seconds=1)
        return job
    monkeypatch.setattr(al, 'submit', advance)
    with pytest.raises(ValueError, match=f'{which} expired'):
        sg.submit(*grid)
    ledger = sg.read_json(grid[1] / sg.LEDGER)
    assert sum(len(c['attempts']) for c in ledger['cells'].values()) == 1


def test_actual_approval_change_stops_next_cell(grid, monkeypatch, tmp_path):
    sys.path.insert(0, str(Path(__file__).parent))
    import test_checkin2_gate as gate
    doc = sg.read_json(grid[0])
    for index, cell in enumerate(doc['cells']):
        root = gate._run(tmp_path / f'approved-{index}', plan='smoke', approve=True, checkin2=False)
        cell['rundir'] = str(root)
    parent = Path(doc['cells'][0]['rundir'])
    _, pins = al._approval(parent, 'checkin1', 'smoke')
    doc['approval'].update(rundir=str(parent), rung='smoke', approval_files=pins)
    write(grid[0], doc)
    original = al.submit
    def revoke(*a, **kw):
        job = original(*a, **kw)
        approval = parent / 'inputs/checkin1_approval.json'
        approval.write_text(approval.read_text().replace('Yes, run the plan', 'Yes, run the plan!'))
        return job
    monkeypatch.setattr(al, 'submit', revoke)
    with pytest.raises(ValueError):
        sg.submit(*grid)
    ledger = sg.read_json(grid[1] / sg.LEDGER)
    assert sum(len(c['attempts']) for c in ledger['cells'].values()) == 1


def test_changed_manifest_or_prepared_spec_refuses_resume(grid):
    change(grid, concurrency=1)
    sg.submit(*grid)
    doc = sg.read_json(grid[0])
    change(grid, concurrency=2)
    with pytest.raises(ValueError, match='manifest changed'):
        sg.submit(*grid, resume=True)
    write(grid[0], doc)
    # Retain a terminal observation to release the only slot.
    ledger = sg.read_json(grid[1] / sg.LEDGER)
    ledger['cells']['cell-0']['attempts'][0]['status'] = 'failed'
    write(grid[1] / sg.LEDGER, ledger)
    Path(doc['cells'][1]['study_spec']).write_text('{}')
    with pytest.raises(ValueError, match='specification changed'):
        sg.submit(*grid, resume=True)


def test_cli_all_four_operations(grid, monkeypatch, capsys):
    tail = ['--manifest', str(grid[0]), '--grid-dir', str(grid[1])]
    assert cli.main(['study-grid', 'submit', *tail]) == 0
    assert cli.main(['study-grid', 'submit', *tail]) == 2
    assert cli.main(['study-grid', 'status', *tail]) == 0
    assert cli.main(['study-grid', 'resume', *tail]) == 0
    assert cli.main(['study-grid', 'harvest', *tail]) == 0
    assert 'study-grid-harvest' in capsys.readouterr().out


@pytest.mark.parametrize('edit', [
    lambda d: d.update(concurrency=0),
    lambda d: d['cells'].pop(),
    lambda d: d['cells'][1].update(id='cell-0'),
    lambda d: d['cells'][0]['axes'].update(u=99),
    lambda d: d['quantities'][0].update(source='../outside.json'),
    lambda d: d['axes'][0].update(values=[1, 1]),
    lambda d: d['approval'].update(expires_utc='2030-01-01'),
])
def test_manifest_refuses_invalid_domain_and_inputs(grid, edit):
    doc = sg.read_json(grid[0])
    edit(doc)
    write(grid[0], doc)
    with pytest.raises(ValueError):
        sg.GridManifest.load(grid[0])


def test_harvest_feeds_declared_axes_plot_and_preserves_holes(grid, monkeypatch, tmp_path):
    from ravel.plotting import parameter_plane as pp
    from ravel.plotting.reference_metrics import _Recorder
    import numpy as np
    sg.submit(*grid)
    finish(grid, monkeypatch)
    doc = asdict(sg.harvest(*grid))
    doc['cells'][0].update(status='failed', values={})
    doc['cells'][2].update(status='missing', values={})
    write(grid[1] / 'harvest.json', doc)
    source = dict(study_grid=str(grid[1] / 'harvest.json'), scenario='baseline', x='u', y='v',
                  surfaces={'observed': 'quantity'}, shade=False)
    resolved, metadata = pp._grid_from_study_harvest(source, tmp_path, _Recorder())
    assert np.isnan(resolved['observed'][0, 0]) and np.isnan(resolved['observed'][1, 0])
    assert metadata['missing_cells'] == 2
    assert pp.grid_contours([1, 2], [3, 4], resolved['observed'], 4) == []
    spec = write(tmp_path / 'plane.json', dict(schema_version=1,
        axes={'x': {'label': 'First coordinate', 'unit': ''}, 'y': {'label': 'Second coordinate', 'unit': ''}},
        panels=[{'grid': source}]))
    receipt = pp.run_spec(spec, tmp_path / 'figure')
    assert receipt['panels'][0]['grid_source']['missing_cells'] == 2
    assert receipt['plot_lint'] == 'PASS'
    pin = doc['cells'][4]['artifacts']['quantity']['path']
    write(Path(pin), {'value': 999})
    with pytest.raises(ValueError, match='differs from harvest'):
        pp._grid_from_study_harvest(source, tmp_path, _Recorder())


def test_non_numeric_result_artifact_is_pinned(grid, monkeypatch):
    change(grid, artifacts=['outputs/summary.bin'])
    sg.submit(*grid)
    finish(grid, monkeypatch)
    for row in sg.read_json(grid[1] / sg.LEDGER)['cells'].values():
        request = sg.read_json(Path(row['attempts'][0]['request_dir']) / 'request.json')
        copy = Path(request['collect_to']) / f"{Path(request['rundir']).name}-{request['run']['run_id']}"
        (copy / 'outputs/summary.bin').write_bytes(b'\x00\x01\xff')
    harvest = sg.harvest(*grid)
    assert all(c.status == 'completed' for c in harvest.cells)
    assert all(c.artifacts['outputs/summary.bin'].field is None for c in harvest.cells)


def test_missing_submission_can_be_explicitly_superseded_at_capacity(grid, monkeypatch):
    change(grid, concurrency=1)
    sg.submit(*grid)
    monkeypatch.setattr(al, '_scheduler_state', lambda job: 'missing')
    ledger = sg.submit(*grid, resume=True, supersede=['cell-0'])
    assert len(ledger['cells']['cell-0']['attempts']) == 2
    assert ledger['cells']['cell-1']['status'] == 'not-submitted'


def test_terminal_observation_survives_accounting_loss(grid, monkeypatch):
    sg.submit(*grid)
    monkeypatch.setattr(al, '_scheduler_state', lambda job: 'timed-out')
    sg.status(*grid)
    monkeypatch.setattr(al, '_scheduler_state', lambda job: 'missing')
    assert {c.status for c in sg.harvest(*grid).cells} == {'timed-out'}


def test_higher_dimensional_plot_requires_an_explicit_slice(grid, monkeypatch, tmp_path):
    from ravel.plotting import parameter_plane as pp
    from ravel.plotting.reference_metrics import _Recorder
    sg.submit(*grid)
    finish(grid, monkeypatch)
    doc = asdict(sg.harvest(*grid))
    doc['axes'] = list(doc['axes']) + [dict(name='w', values=[0, 1])]
    for cell in doc['cells']:
        cell['axes']['w'] = 0
    write(grid[1] / 'harvest.json', doc)
    source = dict(study_grid=str(grid[1] / 'harvest.json'), scenario='baseline', x='u', y='v',
                  surfaces={'observed': 'quantity'})
    with pytest.raises(ValueError, match='every other'):
        pp._grid_from_study_harvest(source, tmp_path, _Recorder())
    source['fixed'] = {'w': 0}
    resolved, _ = pp._grid_from_study_harvest(source, tmp_path, _Recorder())
    assert resolved['observed'].shape == (2, 2)


def test_ledger_lock_refuses_a_second_writer_without_submitting(grid):
    from ravel.workflow.state_io import file_lock
    # Nonblocking lock seam validates the same lock used by every grid operation.
    with file_lock(grid[1] / '.lock'):
        with pytest.raises(ValueError, match='another process'):
            with file_lock(grid[1] / '.lock', blocking=False):
                pytest.fail('second writer acquired grid lock')


def test_entirely_missing_grid_can_be_rendered_without_inventing_values(grid, monkeypatch, tmp_path):
    from ravel.plotting import parameter_plane as pp
    sg.submit(*grid)
    monkeypatch.setattr(al, '_scheduler_state', lambda job: 'missing')
    sg.harvest(*grid)
    source = dict(study_grid=str(grid[1] / 'harvest.json'), scenario='baseline', x='u', y='v',
                  surfaces={'observed': 'quantity'})
    spec = write(tmp_path / 'empty.json', dict(schema_version=1,
        axes={'x': {'label': 'First coordinate'}, 'y': {'label': 'Second coordinate'}}, panels=[{'grid': source}]))
    receipt = pp.run_spec(spec, tmp_path / 'empty-figure')
    panel = receipt['panels'][0]
    assert panel['excluded_fraction'] is None
    assert panel['contours']['observed']['segments'] == []
    assert panel['grid_source']['missing_cells'] == 4


def test_ordinary_figure_planning_binds_harvest_and_selected_result_inputs(grid, monkeypatch, tmp_path):
    from ravel.physics import figure_comparison
    sg.submit(*grid)
    finish(grid, monkeypatch)
    doc = asdict(sg.harvest(*grid))
    harvest = grid[1] / 'harvest.json'
    plane = write(tmp_path / 'planned-plane.json', dict(schema_version=1, panels=[{'grid': dict(
        study_grid=str(harvest), scenario='baseline', x='u', y='v', surfaces={'observed': 'quantity'})}]))
    task = {'operations': [{'name': 'plane', 'kind': 'parameter-plane', 'specification': str(plane)}]}
    files = set(figure_comparison.inputs(task, tmp_path))
    assert files == {plane, harvest} | {
        Path(c['artifacts']['quantity']['path']) for c in doc['cells'] if c['scenario'] == 'baseline'}


def test_finished_agent_does_not_release_a_still_running_allocation(grid, monkeypatch):
    sg.submit(*grid)
    finish(grid, monkeypatch)
    monkeypatch.setattr(al, '_scheduler_state', lambda job: 'running')
    ledger = sg.status(*grid)
    assert {c['status'] for c in ledger['cells'].values()} == {'running'}
    monkeypatch.setattr(al, '_scheduler_state', lambda job: 'completed')
    assert {c.status for c in sg.harvest(*grid).cells} == {'completed'}


@pytest.mark.parametrize('raw,expected', [
    ('PENDING', 'pending'), ('RUNNING', 'running'), ('COMPLETED', 'completed'),
    ('FAILED', 'failed'), ('CANCELLED by 42', 'cancelled'), ('TIMEOUT', 'timed-out'),
    ('UNRECOGNIZED', 'unknown'), ('', 'missing'),
])
def test_scheduler_collection_parser_uses_queue_then_accounting(monkeypatch, raw, expected):
    import types
    calls = []
    def execute(argv, **kw):
        calls.append(argv)
        return types.SimpleNamespace(returncode=0, stdout='' if argv[0] == 'squeue' else raw, stderr='')
    monkeypatch.setattr(al.subprocess, 'run', execute)
    assert al._scheduler_state('42') == expected
    assert [c[0] for c in calls] == ['squeue', 'sacct']
    assert all('42' in c for c in calls)


def test_scheduler_query_failure_remains_unknown(monkeypatch):
    def unavailable(*a, **kw):
        raise OSError('synthetic unavailable scheduler')
    monkeypatch.setattr(al.subprocess, 'run', unavailable)
    assert al._scheduler_state('42') == 'unknown'


def test_categorical_axis_is_preserved_in_general_harvest(grid, monkeypatch):
    doc = sg.read_json(grid[0])
    doc['axes'][0]['values'] = ['first', 'second']
    for cell in doc['cells']:
        cell['axes']['u'] = 'first' if cell['axes']['u'] == 1 else 'second'
    write(grid[0], doc)
    sg.submit(*grid)
    finish(grid, monkeypatch)
    assert {c.axes['u'] for c in sg.harvest(*grid).cells} == {'first', 'second'}


def test_lost_request_artifact_is_an_explicit_missing_cell(grid):
    ledger = sg.submit(*grid)
    Path(ledger['cells']['cell-0']['attempts'][0]['request_dir'], 'request.json').unlink()
    harvest = sg.harvest(*grid)
    assert harvest.cells[0].status == 'missing' and not harvest.cells[0].values
    assert harvest.cells[0].attempts[0]['error'] == 'allocation request artifact missing'


def test_ledger_submission_id_survives_lost_submission_copy(grid):
    ledger = sg.submit(*grid)
    Path(ledger['cells']['cell-0']['attempts'][0]['request_dir'], 'submission.json').unlink()
    ledger = sg.status(*grid)
    assert ledger['cells']['cell-0']['status'] == 'pending'
    assert ledger['cells']['cell-0']['attempts'][0]['job_id'] == '1'
