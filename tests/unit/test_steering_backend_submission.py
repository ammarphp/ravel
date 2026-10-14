"""Live steering at backend submission: a pause stops queued submissions and running jobs drain.

The partition driver, the backend worker's submission and the launcher command each reach
``execution_backend`` after their stage was authorized; steering is decided again at every
submission, on the run that owns the stage.
"""
import json
import sys
import time

import pytest

from ravel.workflow import execution_backend as eb, gate_wiring as gw, partitioned_execution as pe
from test_execution_backend import native_spec, wait_terminal
from test_partitioned_execution import population, spec as partition_spec


@pytest.fixture
def run(tmp_path, monkeypatch):
    from ravel.workflow import agent_worker as aw, graph_substrate as gs
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setattr(gs, 'stop', lambda *a, **kw: {})
    monkeypatch.setattr(aw, 'stop', lambda *a, **kw: {})
    monkeypatch.setattr(eb, 'require_approved_stage',
                        lambda rundir, stage, pinned=(): {'rundir': str(rundir), 'stage': stage, 'test_double': True,
                                                          'events': 10 ** 6, 'max_seconds': 10 ** 6})
    eb._INSTANCES.clear()
    root = tmp_path / 'approved-run'
    (root / 'inputs').mkdir(parents=True)
    return root


def pause(run):
    return gw.record_steering(run, 'Pause the study.', effect='pause')


def resume(run):
    event = gw.record_steering(run, 'Continue the study.', effect='resume')
    gw.ack_steering(run, event['event_id'], interpretation='Continue within the approved scope.')


def drive(run, tmp_path, document, work):
    path = tmp_path / 'partition-spec.json'
    path.write_text(json.dumps(document))
    return pe.run(document, work, authority={'rundir': str(run), 'stage': 'parts', 'spec': str(path)}, poll=0.05)


def test_pause_stops_queued_partitions_and_the_running_one_drains(run, tmp_path, monkeypatch):
    document = partition_spec(tmp_path, population(tmp_path, n=5), concurrent=1)
    work = tmp_path / 'work'
    submitted, real = [], eb.submit

    def submit_then_pause(plan, attempt, **options):
        handle = real(plan, attempt, **options)
        submitted.append(str(attempt))
        if len(submitted) == 1:
            pause(run)  # the pause lands while the first partition is running
        return handle
    monkeypatch.setattr(eb, 'submit', submit_then_pause)
    summary = drive(run, tmp_path, document, work)
    # The partition that was already running drained to success; nothing queued was submitted.
    assert len(submitted) == 1
    assert summary['succeeded'] == 1 and summary['failed'] == [] and summary['unresolved'] == []
    assert summary['pending'] == ['p00001', 'p00002'] and summary['status'] == 'incomplete'
    ledger = json.loads((work / pe.LEDGER).read_text())
    assert ledger['partitions']['p00000']['status'] == 'succeeded'
    for identity in ('p00001', 'p00002'):
        assert ledger['partitions'][identity] == {**ledger['partitions'][identity], 'status': 'pending', 'attempts': []}
    assert 'paused' in ledger['blocked'][-1]['detail'] and ledger['blocked'][-1]['steering'] is True
    assert not (work / 'partitions/p00001/attempt-1').exists()  # no handle, no job directory
    state = gw.steering_state(run)
    assert state['paused'] and state['pause_requested']
    # After the acknowledged resume the same driver finishes the queued partitions.
    monkeypatch.setattr(eb, 'submit', real)
    resume(run)
    summary = drive(run, tmp_path, document, work)
    assert summary['status'] == 'complete' and summary['succeeded'] == 3


def test_submission_under_a_pause_writes_nothing_and_starts_nothing(run, tmp_path):
    plan = eb.prepare(native_spec(tmp_path))
    with eb.machine_lease('steering submission test', rundir=str(run), node_id='count-lines'):
        pause(run)
        with pytest.raises(gw.SteeringRefused, match='paused'):
            eb.submit(plan, tmp_path / 'attempt')
        assert not (tmp_path / 'attempt').exists()
        resume(run)
        handle = eb.submit(plan, tmp_path / 'attempt')
        assert wait_terminal(plan, handle)['state'] == 'succeeded'


def test_submission_is_refused_for_a_vetoed_stage_and_admitted_for_another_branch(run, tmp_path):
    (run / 'graph_spec.json').write_text(json.dumps({'nodes': [
        {'id': 'build', 'depends_on': [], 'stage': {'name': 'count-lines'}},
        {'id': 'other', 'depends_on': [], 'stage': {'name': 'detector'}}]}))
    plan = eb.prepare(native_spec(tmp_path))
    with eb.machine_lease('steering submission test', rundir=str(run), node_id='count-lines'):
        gw.record_steering(run, 'Stop the independent branch.', effect='veto', affected_nodes=['other'])
        handle = eb.submit(plan, tmp_path / 'attempt')
        assert wait_terminal(plan, handle)['state'] == 'succeeded'
        gw.record_steering(run, 'Stop this branch.', effect='veto', affected_nodes=['build'])
        with pytest.raises(gw.SteeringRefused, match='veto'):
            eb.submit(plan, tmp_path / 'second-attempt')
        assert not (tmp_path / 'second-attempt').exists()


def test_backend_worker_submission_is_refused_under_a_pause(run, tmp_path):
    import io
    plan = eb.prepare(native_spec(tmp_path))
    box = {'handle': None}
    with eb.machine_lease('steering worker test', rundir=str(run), node_id='count-lines'):
        pause(run)
        with pytest.raises(gw.SteeringRefused, match='paused'):
            eb._drive(plan, None, tmp_path / 'attempt', run, box, 0.05, 1.0, io.StringIO())
    assert box['handle'] is None and not (tmp_path / 'attempt').exists()


def test_job_already_running_is_not_cancelled_by_a_drain_pause(run, tmp_path):
    marker = tmp_path / 'finished'
    argv = [sys.executable, '-c', f'import time; time.sleep(0.6); open({str(marker)!r}, "w").write("done")']
    plan = eb.prepare(native_spec(tmp_path, argv=argv, outputs=[], quantities=[]))
    with eb.machine_lease('steering drain test', rundir=str(run), node_id='count-lines'):
        handle = eb.submit(plan, tmp_path / 'attempt')
        time.sleep(0.1)
        pause(run)
        assert wait_terminal(plan, handle)['state'] == 'succeeded'
    assert marker.read_text() == 'done'


def launcher_command(run, tmp_path, monkeypatch, started):
    from ravel.workflow.backends import oci_local
    launcher = tmp_path / 'launcher.json'
    launcher.write_text('{}')
    work = tmp_path / 'launch-work'
    work.mkdir(exist_ok=True)
    marker = tmp_path / 'container-ran'
    monkeypatch.setattr(oci_local, 'launcher_command',
                        lambda *a, **kw: [sys.executable, '-c', f'open({str(marker)!r}, "w").write("ran")'])
    monkeypatch.setattr(oci_local, 'cleanup_launch', lambda *a, **kw: started.append('cleanup') or {})
    code = eb.main(['launch', '--rundir', str(run), '--stage', 'container', '--launcher', str(launcher),
                    '--workdir', str(work), '--execute', '--', '/bin/true'])
    return code, marker


def test_launcher_command_does_not_start_its_container_under_a_pause(run, tmp_path, monkeypatch, capsys):
    started = []
    pause(run)
    code, marker = launcher_command(run, tmp_path, monkeypatch, started)
    assert code == 2 and not marker.exists()
    assert 'paused' in capsys.readouterr().err
    resume(run)
    code, marker = launcher_command(run, tmp_path, monkeypatch, started)
    assert code == 0 and marker.read_text() == 'ran'
