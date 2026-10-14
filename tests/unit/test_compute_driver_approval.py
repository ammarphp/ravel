"""`ravel partitions run` and `ravel backend launch --execute` run only inside an approved supervised stage."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from ravel.workflow import execution, execution_backend as eb, partitioned_execution as pe, stage_supervisor
from ravel.workflow.state_io import atomic_json
from test_checkin2_gate import _run
from test_partitioned_execution import population, spec as partition_spec


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('WORKFLOW_STATE_UTC', '2026-10-08T00:00:00Z')
    eb._INSTANCES.clear()


def partitions_command(root, spec_path, work):
    return [sys.executable, '-m', 'ravel.workflow.partitioned_execution', 'run', '--rundir', str(root),
            '--stage', 'parts', '--spec', str(spec_path), '--workdir', str(work)]


def prepared(tmp_path):
    files = population(tmp_path, n=4)
    spec_path = tmp_path / 'partitions.json'
    atomic_json(spec_path, partition_spec(tmp_path, files))
    return spec_path, tmp_path / 'work'


def test_partitions_run_refuses_outside_a_supervised_stage(tmp_path, capsys):
    spec_path, work = prepared(tmp_path)
    assert pe.main(['run', '--spec', str(spec_path), '--workdir', str(work)]) == 2
    assert 'approved run' in capsys.readouterr().err
    root = _run(tmp_path, plan='smoke', checkin2=False)
    assert pe.main(['run', '--rundir', str(root), '--stage', 'parts', '--spec', str(spec_path),
                    '--workdir', str(work)]) == 2
    assert not work.exists()


def test_partitions_run_refuses_an_unauthorized_supervised_stage(tmp_path):
    spec_path, work = prepared(tmp_path)
    root = tmp_path / 'plain'
    (root / 'logs').mkdir(parents=True)
    code = stage_supervisor.supervise('parts', root, 0, 'logs/parts.log', partitions_command(root, spec_path, work),
                                      kill_secs=60.0, poll=0.1, grace=3.0, inputs=[str(spec_path)], _engineering_only=True)
    assert code == 2
    assert 'without an approved-run launch authorization' in (root / 'logs/parts.log').read_text()
    assert not work.exists()


def test_partitions_run_proceeds_as_an_approved_supervised_stage(tmp_path):
    spec_path, work = prepared(tmp_path)
    root = _run(tmp_path, plan='smoke', checkin2=False)
    code = stage_supervisor.supervise('parts', root, 100, 'logs/parts.log', partitions_command(root, spec_path, work),
                                      kill_secs=300.0, poll=0.1, grace=3.0, inputs=[str(spec_path)],
                                      required_plan='smoke')
    assert code == 0, (root / 'logs/parts.log').read_text()
    assert json.loads((work / pe.LEDGER).read_text())['authority']['stage'] == 'parts'
    assert pe.summary(work)['status'] == 'complete'


def test_partitions_run_refuses_a_spec_that_is_not_the_pinned_input(tmp_path):
    spec_path, work = prepared(tmp_path)
    other = tmp_path / 'other.json'
    other.write_bytes(spec_path.read_bytes())
    root = _run(tmp_path, plan='smoke', checkin2=False)
    code = stage_supervisor.supervise('parts', root, 10, 'logs/parts.log', partitions_command(root, other, work),
                                      kill_secs=60.0, poll=0.1, grace=3.0, inputs=[str(spec_path)],
                                      required_plan='smoke')
    assert code == 2
    assert 'not a pinned input' in (root / 'logs/parts.log').read_text()


def test_backend_launch_execute_refuses_without_an_approved_stage(tmp_path, capsys):
    launcher = tmp_path / 'launcher.json'
    launcher.write_text('{}')
    argv = ['launch', '--launcher', str(launcher), '--workdir', str(tmp_path), '--execute', '--', 'true']
    assert eb.main(argv) == 2
    assert 'approved run' in capsys.readouterr().err
    root = _run(tmp_path, plan='smoke', checkin2=False)
    assert eb.main(['launch', '--rundir', str(root), '--stage', 'container', *argv[1:]]) == 2
    assert 'ravel backend:' in capsys.readouterr().err


def test_partition_volume_above_the_approved_rung_is_refused(tmp_path):
    files = population(tmp_path, n=2)
    document = partition_spec(tmp_path, files)
    document['population'] = {'members': [{'uri': f'root://store.example/f{i}.root', 'entries': 1}
                                          for i in range(10000)]}
    spec_path = tmp_path / 'large.json'
    atomic_json(spec_path, document)
    work = tmp_path / 'work'
    root = _run(tmp_path, plan='smoke', checkin2=False)
    code = stage_supervisor.supervise('parts', root, 10, 'logs/parts.log', partitions_command(root, spec_path, work),
                                      kill_secs=120.0, poll=0.1, grace=3.0, inputs=[str(spec_path)],
                                      required_plan='smoke')
    assert code == 2 and 'the approved stage covers 10 events' in (root / 'logs/parts.log').read_text()
    assert not work.exists()


def test_partitions_run_refuses_an_authority_it_cannot_verify(tmp_path):
    spec_path, work = prepared(tmp_path)
    root = _run(tmp_path, plan='smoke', checkin2=False)
    with pytest.raises(ValueError):
        pe.run(json.loads(spec_path.read_text()), work, authority={'rundir': str(root), 'stage': 'parts'})
    assert not work.exists()


LATE_PLAN = ('import sys\n'
             'from pathlib import Path\n'
             'from ravel.workflow import execution_backend as eb\n'
             'plans = Path(sys.argv[1], "inputs/backend-plans")\n'
             'plans.mkdir(parents=True, exist_ok=True)\n'
             '(plans / "late.json").write_text("{}")\n'
             'try:\n'
             '    eb.require_approved_stage(sys.argv[1], "late")\n'
             '    print("ADMITTED")\n'
             'except ValueError as exc:\n'
             '    print("REFUSED", exc)\n')


def test_a_backend_plan_pinned_after_approval_revokes_compute_admission(tmp_path):
    root = _run(tmp_path, plan='smoke', checkin2=False)
    code = stage_supervisor.supervise('late', root, 10, 'logs/late.log', [sys.executable, '-c', LATE_PLAN, str(root)],
                                      kill_secs=60.0, poll=0.1, grace=3.0, required_plan='smoke')
    log = (root / 'logs/late.log').read_text()
    assert code == 0 and 'REFUSED' in log and 'ADMITTED' not in log, log


def test_drive_with_the_real_backend_module_needs_an_approved_stage(tmp_path):
    from ravel.physics import backend_driver
    spec = {'schema_version': 1, 'backend': 'native', 'stage': 'probe', 'argv': [sys.executable, '-c', 'pass'],
            'outputs': [], 'resources': {'cpus': 1, 'memory_mib': 128, 'wall_seconds': 30}}
    for backend in (None, eb):
        with pytest.raises(ValueError, match='approved supervised stage'):
            backend_driver.drive(spec, tmp_path / 'attempt', tmp_path, backend=backend, poll=0.1)
    assert not (tmp_path / 'attempt').exists()


# Engineering dispatch runs outside any inherited agent session.
pytestmark = pytest.mark.usefixtures("engineering_session")
