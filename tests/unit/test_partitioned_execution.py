"""Partitioned execution: split, run through a backend, merge additive outputs."""
from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
import json
import shutil
import os
import time
from pathlib import Path
import sys

import pytest

from ravel.workflow import execution_backend as eb
from ravel.workflow import partitioned_execution as pe

PAYLOAD = r'''
import json, os, sys
inputs = json.load(open(sys.argv[1]))
out = os.environ["RAVEL_OUTPUT_DIR"]
fail_marker = sys.argv[2] if len(sys.argv) > 2 else None
values = [0.0, 0.0]
sumw2 = [0.0, 0.0]
raw = 0
for member in inputs["members"]:
    path = member["path"]
    if fail_marker and "bad" in path and not os.path.exists(fail_marker):
        open(fail_marker, "w").write("failed once")
        sys.exit(5)
    for line in open(path):
        x, w = map(float, line.split())
        b = 0 if x < 1.0 else 1
        values[b] += w; sumw2[b] += w * w; raw += 1
json.dump({"schema_version": 1, "kind": "binned_values", "axes": [{"name": "x", "unit": "GeV"}],
           "unit": "events", "representation": "integrated",
           "bins": [{"low": [0.0], "high": [1.0], "value": values[0], "sumw2": sumw2[0]},
                    {"low": [1.0], "high": [2.0], "value": values[1], "sumw2": sumw2[1]}],
           "overflow": 0.0, "underflow": 0.0}, open(os.path.join(out, "hist.json"), "w"))
json.dump({"regions": [{"name": "all", "cuts": [{"name": "read", "weighted": sum(values), "raw": raw}]}]},
          open(os.path.join(out, "cutflow.json"), "w"))
'''


# These tests exercise the partition mechanics; the approval gate is replaced by an
# explicit test double here and exercised for real in test_compute_driver_approval.
AUTHORITY = {'rundir': '/approved/run', 'stage': 'parts'}


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setattr(eb, 'require_approved_stage',
                        lambda rundir, stage, pinned=(): {'rundir': rundir, 'stage': stage, 'test_double': True,
                                                          'events': 10 ** 6, 'max_seconds': 10 ** 6})
    eb._INSTANCES.clear()


def run(spec, work, **kwargs):
    # The library run binds the supplied specification to the stage's pinned specification file.
    path = Path(work).parent / f'{Path(work).name}-spec.json'
    path.write_text(json.dumps(spec))
    return pe.run(spec, work, authority={**AUTHORITY, 'spec': str(path)}, **kwargs)


def population(tmp_path, n=5, bad=False):
    files = []
    for i in range(n):
        name = f'bad{i}.txt' if bad and i == 2 else f'f{i}.txt'
        path = tmp_path / 'data' / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(''.join(f'{(i + k) % 3 * 0.7} {1.0 + 0.5 * k}\n' for k in range(4)))
        files.append(str(path))
    return files


def member(path):
    text = Path(path).read_text()
    return {'path': path, 'checksum': 'sha256:' + eb.file_sha256(path), 'entries': len(text.splitlines())}


def spec(tmp_path, files, *, per=2, concurrent=2, attempts=1, extra_argv=()):
    script = tmp_path / 'payload.py'
    script.write_text(PAYLOAD)
    return {'schema_version': 1, 'name': 'histogram-pass',
            'population': {'members': [member(f) for f in files]},
            'partitioning': {'members_per_partition': per},
            'stage': {'backend': 'native', 'argv': [sys.executable, str(script), '{partition_inputs}', *extra_argv],
                      'inputs': [{'path': str(script)}],
                      'resources': {'cpus': 1, 'memory_mib': 128, 'wall_seconds': 120}},
            'outputs': [{'name': 'hist.json', 'merge': 'binned_values'}, {'name': 'cutflow.json', 'merge': 'cutflow'}],
            'max_concurrent': concurrent, 'max_attempts': attempts}


def single_pass(files):
    values, sumw2, raw = [0.0, 0.0], [0.0, 0.0], 0
    for f in files:
        for line in Path(f).read_text().splitlines():
            x, w = map(float, line.split())
            b = 0 if x < 1.0 else 1
            values[b] += w; sumw2[b] += w * w; raw += 1
    return values, sumw2, raw


def test_partitions_cover_population_exactly_once(tmp_path):
    files = population(tmp_path, n=5)
    parts = pe.plan_partitions(pe.validate(spec(tmp_path, files)))
    assert [p['id'] for p in parts] == ['p00000', 'p00001', 'p00002']
    flat = [m['path'] for p in parts for m in p['members']]
    assert flat == files
    again = pe.plan_partitions(pe.validate(spec(tmp_path, files)))
    assert [p['sha256'] for p in parts] == [p['sha256'] for p in again]


def test_dry_run_dag_with_fifty_partitions(tmp_path):
    members = [{'uri': f'root://eos.example//store/file{i}.root', 'entries': 1000 + i} for i in range(100)]
    document = spec(tmp_path, [])
    document['population'] = {'members': members}
    document['partitioning'] = {'partitions': 50}
    parts = pe.plan_partitions(pe.validate(document))
    assert len(parts) == 50 and all(len(p['members']) == 2 for p in parts)
    assert sum(p['entries'] for p in parts) == sum(m['entries'] for m in members)


def test_run_and_merge_equals_single_pass(tmp_path):
    files = population(tmp_path, n=5)
    work = tmp_path / 'work'
    summary = run(spec(tmp_path, files), work, poll=0.05)
    assert summary['status'] == 'complete' and summary['succeeded'] == 3
    merged = pe.merge(work)
    hist = json.loads((work / 'merged/hist.json').read_text())
    values, sumw2, raw = single_pass(files)
    assert [b['value'] for b in hist['bins']] == pytest.approx(values)
    assert [b['sumw2'] for b in hist['bins']] == pytest.approx(sumw2)
    cutflow = json.loads((work / 'merged/cutflow.json').read_text())
    assert cutflow['regions'][0]['cuts'][0]['raw'] == raw
    receipt = json.loads((work / 'merge-receipt.json').read_text())
    assert len(receipt['partitions']) == 3 and receipt == merged
    for row in receipt['partitions']:
        assert set(row['outputs']) == {'hist.json', 'cutflow.json'}


def test_failure_is_isolated_and_retried_within_bound(tmp_path):
    files = population(tmp_path, n=5, bad=True)
    marker = tmp_path / 'failed-once'
    work = tmp_path / 'work'
    summary = run(spec(tmp_path, files, attempts=2, extra_argv=(str(marker),)), work, poll=0.05)
    assert summary['status'] == 'complete'
    ledger = json.loads((work / pe.LEDGER).read_text())
    attempts = {pid: len(row['attempts']) for pid, row in ledger['partitions'].items()}
    assert attempts == {'p00000': 1, 'p00001': 2, 'p00002': 1}
    assert ledger['partitions']['p00001']['attempts'][0]['state'] == 'failed'


def test_exhausted_retries_block_merge_and_name_the_partition(tmp_path):
    files = population(tmp_path, n=5, bad=True)
    work = tmp_path / 'work'
    summary = run(spec(tmp_path, files, attempts=1, extra_argv=(str(tmp_path / 'm'),)), work, poll=0.05)
    assert summary['status'] == 'incomplete' and summary['failed'] == ['p00001']
    with pytest.raises(ValueError, match='p00001'):
        pe.merge(work)
    assert (work / 'partitions/p00000/hist.json').is_file()


def test_rerun_resumes_only_unfinished_partitions(tmp_path):
    files = population(tmp_path, n=5, bad=True)
    work = tmp_path / 'work'
    marker = tmp_path / 'm'
    run(spec(tmp_path, files, attempts=1, extra_argv=(str(marker),)), work, poll=0.05)
    summary = run(spec(tmp_path, files, attempts=2, extra_argv=(str(marker),)), work, poll=0.05)
    assert summary['status'] == 'complete'
    ledger = json.loads((work / pe.LEDGER).read_text())
    assert len(ledger['partitions']['p00000']['attempts']) == 1


def test_changed_specification_is_refused_on_resume(tmp_path):
    files = population(tmp_path, n=4)
    work = tmp_path / 'work'
    run(spec(tmp_path, files), work, poll=0.05)
    with pytest.raises(ValueError, match='specification'):
        run(spec(tmp_path, files, per=1), work, poll=0.05)


def test_merge_refusals():
    a = {'schema_version': 1, 'kind': 'binned_values', 'axes': [{'name': 'x', 'unit': 'GeV'}], 'unit': 'events',
         'representation': 'integrated', 'bins': [{'low': [0.0], 'high': [1.0], 'value': 1.0}]}
    b = json.loads(json.dumps(a))
    b['bins'][0]['high'] = [2.0]
    with pytest.raises(ValueError, match='edges'):
        pe.merge_documents('binned_values', [a, b])
    c = json.loads(json.dumps(a))
    c['normalization'] = {'kind': 'per-partition', 'scale': 0.5}
    with pytest.raises(ValueError, match='normaliz'):
        pe.merge_documents('binned_values', [a, c])
    d = json.loads(json.dumps(a))
    d['bins'][0]['uncertainty'] = 0.3
    e = json.loads(json.dumps(d))
    e['bins'][0]['uncertainty'] = 0.4
    merged = pe.merge_documents('binned_values', [d, e])
    assert merged['bins'][0]['uncertainty'] == pytest.approx(0.5)
    with pytest.raises(ValueError, match='cut'):
        pe.merge_documents('cutflow', [{'regions': [{'name': 'r', 'cuts': [{'name': 'a', 'weighted': 1, 'raw': 1}]}]},
                                       {'regions': [{'name': 'r', 'cuts': [{'name': 'b', 'weighted': 1, 'raw': 1}]}]}])
    assert pe.merge_documents('counts', [{'n': 1, 'w': 0.5}, {'n': 2, 'w': 0.25}]) == {'n': 3, 'w': 0.75}


def test_forecast_from_a_pilot(tmp_path):
    files = population(tmp_path, n=6)
    work = tmp_path / 'work'
    run(spec(tmp_path, files, per=2), work, poll=0.05, only=['p00000'])
    forecast = pe.forecast(work)
    assert forecast['pilot_partitions'] == ['p00000']
    assert forecast['remaining_partitions'] == 2
    assert forecast['estimated_core_hours'] >= 0 and forecast['calibration'] == 'measured pilot'


def test_cli_plan_and_status(tmp_path, capsys):
    files = population(tmp_path, n=3)
    path = tmp_path / 'spec.json'
    path.write_text(json.dumps(spec(tmp_path, files)))
    assert pe.main(['plan', '--spec', str(path)]) == 0
    assert '"partitions": 2' in capsys.readouterr().out
    # The command line runs partitions only as an approved supervised stage (test_compute_driver_approval).
    assert pe.main(['run', '--spec', str(path), '--workdir', str(tmp_path / 'w'), '--poll', '0.05', '--merge']) == 2
    assert not (tmp_path / 'w').exists()
    run(spec(tmp_path, files), tmp_path / 'w', poll=0.05)
    assert pe.main(['merge', '--workdir', str(tmp_path / 'w')]) == 0
    assert (tmp_path / 'w/merged/hist.json').is_file()
    assert pe.main(['status', '--workdir', str(tmp_path / 'w')]) == 0


# ---------------------------------------------------------------- approval, one job, data binding, failure paths
def test_run_refuses_without_an_approved_stage_authority(tmp_path):
    files = population(tmp_path, n=2)
    with pytest.raises(ValueError, match='approved supervised stage'):
        pe.run(spec(tmp_path, files), tmp_path / 'w', poll=0.05)
    assert not (tmp_path / 'w').exists()


def test_local_partitions_run_one_native_job_at_a_time(tmp_path):
    files = population(tmp_path, n=4)
    log = tmp_path / 'intervals.txt'
    script = tmp_path / 'slow.py'
    script.write_text('import json,os,sys,time\n'
                      f'log={str(log)!r}\n'
                      'open(log,"a").write(f"start {time.monotonic()}\\n");time.sleep(0.3)\n'
                      'open(log,"a").write(f"end {time.monotonic()}\\n")\n'
                      'json.dump({"n":1},open(os.path.join(os.environ["RAVEL_OUTPUT_DIR"],"counts.json"),"w"))\n')
    document = spec(tmp_path, files, per=1, concurrent=8)
    document['stage'].update(argv=[sys.executable, str(script), '{partition_inputs}'], inputs=[{'path': str(script)}])
    document['outputs'] = [{'name': 'counts.json', 'merge': 'counts'}]
    assert run(document, tmp_path / 'w', poll=0.05)['status'] == 'complete'
    events = [line.split() for line in log.read_text().splitlines()]
    assert [kind for kind, _ in events] == ['start', 'end'] * 4


def test_a_member_changed_after_approval_is_refused(tmp_path):
    files = population(tmp_path, n=2)
    document = spec(tmp_path, files)
    Path(files[1]).write_text('0.1 9.0\n')
    with pytest.raises(ValueError, match='approved checksum'):
        run(document, tmp_path / 'w', poll=0.05)


def test_a_local_member_needs_a_checksum(tmp_path):
    files = population(tmp_path, n=2)
    document = spec(tmp_path, files)
    del document['population']['members'][0]['checksum']
    with pytest.raises(ValueError, match='checksum'):
        pe.validate(document)


def test_an_edited_partition_inputs_file_is_refused_on_resume(tmp_path):
    files = population(tmp_path, n=4)
    work = tmp_path / 'w'
    run(spec(tmp_path, files), work, poll=0.05, only=['p00000'])
    inputs = work / 'partitions/p00001/inputs.json'
    inputs.write_text(json.dumps({'partition': 'p00001', 'members': [{'path': files[0]}]}))
    with pytest.raises(ValueError, match='inputs.json differs'):
        run(spec(tmp_path, files), work, poll=0.05)


def test_a_partition_whose_cancel_does_not_finish_is_not_resubmitted(tmp_path, monkeypatch):
    from ravel.workflow import execution, machine_lease
    from ravel.workflow.backends import native
    files = population(tmp_path, n=2)
    script = tmp_path / 'sleep.py'
    script.write_text('import time;time.sleep(30)\n')
    document = spec(tmp_path, files, per=2, attempts=2)
    document['stage'].update(argv=[sys.executable, str(script), '{partition_inputs}'], inputs=[{'path': str(script)}],
                             resources={'cpus': 1, 'memory_mib': 128, 'wall_seconds': 1})
    real_cancel = native.NativeBackend.cancel
    monkeypatch.setattr(native.NativeBackend, 'cancel', lambda self, plan, handle, grace=5.0: {'signalled': False})
    work = tmp_path / 'w'
    summary = run(document, work, poll=0.05, cancel_wait=0.3)
    row = json.loads((work / pe.LEDGER).read_text())['partitions']['p00000']
    groups = [json.loads((Path(a['attempt_dir']) / 'job/launcher.json').read_text())['pgid'] for a in row['attempts']]
    try:
        assert summary['unresolved'] == ['p00000'] and len(row['attempts']) == 1
        with pytest.raises(machine_lease.LeaseBusy, match='still running'):
            run(document, work, poll=0.05)
    finally:
        for pgid in groups:
            os.killpg(pgid, 9)
    deadline = time.monotonic() + 10
    while any(execution.process_group_members(g) for g in groups) and time.monotonic() < deadline:
        time.sleep(0.05)
    # Once the job is gone, the next run reconciles the attempt from its handle (it was cancelled)
    # and only then spends the remaining attempt; this one finishes within its wall clock.
    monkeypatch.setattr(native.NativeBackend, 'cancel', real_cancel)
    script.write_text('pass\n')
    rerun = run(document, work, poll=0.05)
    row = json.loads((work / pe.LEDGER).read_text())['partitions']['p00000']
    assert rerun['unresolved'] == [] and row['attempts'][0]['state'] in ('cancelled', 'failed')
    assert 'reconciled_utc' in row['attempts'][0] and len(row['attempts']) == 2


def test_an_error_in_the_partition_loop_cancels_active_jobs(tmp_path, monkeypatch):
    files = population(tmp_path, n=2)
    marker = tmp_path / 'pid.txt'
    script = tmp_path / 'sleep.py'
    script.write_text(f'import os,time;open({str(marker)!r},"w").write(str(os.getpid()));time.sleep(30)\n')
    document = spec(tmp_path, files, per=2)
    document['stage'].update(argv=[sys.executable, str(script), '{partition_inputs}'], inputs=[{'path': str(script)}])
    original = eb.observe

    def failing(plan, handle):
        if marker.exists():
            raise RuntimeError('observation store failed')
        return original(plan, handle)
    monkeypatch.setattr(eb, 'observe', failing)
    with pytest.raises(RuntimeError, match='observation store failed'):
        run(document, tmp_path / 'w', poll=0.05, cancel_wait=3.0)
    monkeypatch.setattr(eb, 'observe', original)
    pid = int(marker.read_text())
    from ravel.workflow import execution
    assert execution.process_identity(pid) is None or pid not in execution.process_group_members(os.getpgid(pid))
    row = json.loads((tmp_path / 'w' / pe.LEDGER).read_text())['partitions']['p00000']
    assert row['status'] in ('interrupted', 'unresolved') and 'error' in row['attempts'][-1]['detail']


def test_an_unresolved_partition_keeps_the_next_one_from_starting(tmp_path, monkeypatch):
    from ravel.workflow import execution
    from ravel.workflow.backends import native
    files = population(tmp_path, n=4)
    script = tmp_path / 'sleep.py'
    script.write_text('import time;time.sleep(30)\n')
    document = spec(tmp_path, files, per=2, attempts=1)
    document['stage'].update(argv=[sys.executable, str(script), '{partition_inputs}'], inputs=[{'path': str(script)}],
                             resources={'cpus': 1, 'memory_mib': 128, 'wall_seconds': 1})
    monkeypatch.setattr(native.NativeBackend, 'cancel', lambda self, plan, handle, grace=5.0: {'signalled': False})
    work = tmp_path / 'w'
    summary = run(document, work, poll=0.05, cancel_wait=0.3)
    ledger = json.loads((work / pe.LEDGER).read_text())['partitions']
    groups = [json.loads((Path(a['attempt_dir']) / 'job/launcher.json').read_text())['pgid']
              for row in ledger.values() for a in row['attempts'] if (Path(a['attempt_dir']) / 'job/launcher.json').exists()]
    try:
        assert summary['unresolved'] == ['p00000'] and len(groups) == 1, (summary, groups)
        assert ledger['p00001']['attempts'] == [] and ledger['p00001']['status'] == 'pending'
    finally:
        for pgid in groups:
            os.killpg(pgid, 9)
    deadline = time.monotonic() + 10
    while any(execution.process_group_members(g) for g in groups) and time.monotonic() < deadline:
        time.sleep(0.05)


def _parts(document):
    return pe.plan_partitions(pe.validate(document))


def test_the_approved_bound_is_required_and_counts_selected_attempts(tmp_path):
    files = population(tmp_path, n=4)  # four entries per member, two members per partition
    document = spec(tmp_path, files, per=2, attempts=2)
    parts = _parts(document)
    with pytest.raises(ValueError, match='does not bound'):
        pe._within_approval(document, parts, {'events': None, 'max_seconds': 600}, attempts=1)
    with pytest.raises(ValueError, match='does not bound'):
        pe._within_approval(document, parts, {'events': 100, 'max_seconds': None}, attempts=1)
    # Sixteen entries in all; a one-partition pilot needs eight, and two attempts double the charge.
    pe._within_approval(document, parts[:1], {'events': 8, 'max_seconds': 600}, attempts=1)
    with pytest.raises(ValueError, match='covers 8 events'):
        pe._within_approval(document, parts[:1], {'events': 8, 'max_seconds': 600}, attempts=2)
    with pytest.raises(ValueError, match='covers 15 events'):
        pe._within_approval(document, parts, {'events': 15, 'max_seconds': 600}, attempts=1)


def test_a_partition_left_running_by_a_killed_driver_is_adopted_not_rerun(tmp_path):
    files = population(tmp_path, n=2)
    document = spec(tmp_path, files, per=2)
    work = tmp_path / 'w'
    run(document, work, poll=0.05)
    path = work / pe.LEDGER
    ledger = json.loads(path.read_text())
    row = ledger['partitions']['p00000']
    attempt = Path(row['attempts'][-1]['attempt_dir'])
    # A driver killed after the job finished but before it recorded the result.
    (attempt / eb.RECEIPT_NAME).unlink()
    handle = eb.read_handle(attempt)
    handle['state'] = 'submitted'
    eb.write_handle(handle)
    for name in ('hist.json', 'cutflow.json'):
        (work / 'partitions/p00000' / name).unlink()
    shutil.rmtree(attempt / 'staging')
    row['status'] = 'running'
    row['attempts'][-1]['state'] = 'submitted'
    path.write_text(json.dumps(ledger))
    summary = run(document, work, poll=0.05)
    row = json.loads(path.read_text())['partitions']['p00000']
    assert summary['status'] == 'complete' and len(row['attempts']) == 1
    assert row['attempts'][0]['state'] == 'succeeded' and 'reconciled_utc' in row['attempts'][0]


def test_a_launch_that_started_nothing_does_not_spend_the_partition_attempt(tmp_path):
    files = population(tmp_path, n=2)
    document = spec(tmp_path, files, per=2, attempts=1)
    work = tmp_path / 'w'
    run(document, work, poll=0.05, only=['p00000'])
    path = work / pe.LEDGER
    ledger = json.loads(path.read_text())
    # A driver killed after recording the attempt and before the backend handle existed.
    ledger['partitions']['p00000'] = {**ledger['partitions']['p00000'], 'status': 'running', 'attempts': [
        {'attempt_dir': str(work / 'partitions/p00000/attempt-9'), 'plan_sha256': 'x', 'state': 'submitted'}]}
    path.write_text(json.dumps(ledger))
    for name in ('hist.json', 'cutflow.json'):
        (work / 'partitions/p00000' / name).unlink()
    summary = run(document, work, poll=0.05)
    row = json.loads(path.read_text())['partitions']['p00000']
    assert summary['status'] == 'complete'
    assert [a['state'] for a in row['attempts']] == ['never-started', 'succeeded']


# ---------------------------------------------------------------- round-3 recovery, budget and binding
def _approve(monkeypatch, **bounds):
    monkeypatch.setattr(eb, 'require_approved_stage',
                        lambda rundir, stage, pinned=(): {'rundir': rundir, 'stage': stage, 'test_double': True,
                                                          'events': 10 ** 6, 'max_seconds': 10 ** 6, **bounds})


def _killed_after_finish(work):
    """A driver killed after its job finished but before it recorded the result."""
    path = work / pe.LEDGER
    ledger = json.loads(path.read_text())
    row = ledger['partitions']['p00000']
    attempt = Path(row['attempts'][-1]['attempt_dir'])
    (attempt / eb.RECEIPT_NAME).unlink()
    handle = eb.read_handle(attempt)
    handle['state'] = 'submitted'
    eb.write_handle(handle)
    for name in ('hist.json', 'cutflow.json'):
        (work / 'partitions/p00000' / name).unlink()
    shutil.rmtree(attempt / 'staging')
    row['status'] = 'running'
    row['attempts'][-1]['state'] = 'submitted'
    path.write_text(json.dumps(ledger))
    return path


def test_recovery_checks_the_specification_before_it_touches_the_work_directory(tmp_path):
    files = population(tmp_path, n=2)
    work = tmp_path / 'w'
    run(spec(tmp_path, files, per=2), work, poll=0.05)
    path = _killed_after_finish(work)
    before = path.read_bytes()
    with pytest.raises(ValueError, match='specification changed'):
        run(spec(tmp_path, files, per=1), work, poll=0.05)
    assert path.read_bytes() == before and not (work / 'partitions/p00000/hist.json').exists()
    manifest = work / 'partitions/p00000/inputs.json'
    manifest.write_text(json.dumps({'partition': 'p00000', 'members': []}))
    with pytest.raises(ValueError, match='inputs.json differs'):
        run(spec(tmp_path, files, per=2), work, poll=0.05)
    assert path.read_bytes() == before and not (work / 'partitions/p00000/hist.json').exists()


def test_the_library_run_binds_the_supplied_specification_to_the_pinned_file(tmp_path):
    files = population(tmp_path, n=2)
    document = spec(tmp_path, files)
    with pytest.raises(ValueError, match='pinned specification'):
        pe.run(document, tmp_path / 'w', authority=AUTHORITY)
    pinned = tmp_path / 'pinned.json'
    pinned.write_text(json.dumps(spec(tmp_path, files, per=1)))
    with pytest.raises(ValueError, match='differs from the pinned specification'):
        pe.run(document, tmp_path / 'w', authority={**AUTHORITY, 'spec': str(pinned)})
    assert not (tmp_path / 'w').exists()


def test_attempts_already_spent_count_against_the_approved_events(tmp_path, monkeypatch):
    files = population(tmp_path, n=4)  # two partitions of eight entries
    document = spec(tmp_path, files, per=2)
    _approve(monkeypatch, events=8)
    work = tmp_path / 'w'
    run(document, work, poll=0.05, only=['p00000'])
    with pytest.raises(ValueError, match='covers 8 events'):
        run(document, work, poll=0.05, only=['p00001'])
    assert len(json.loads((work / pe.LEDGER).read_text())['partitions']['p00001']['attempts']) == 0


def _remote_left_running(tmp_path, monkeypatch, seconds_ago):
    """A remote partition an earlier driver left running, ``seconds_ago`` after it started."""
    files = population(tmp_path, n=2)
    document = spec(tmp_path, files, per=2)
    document['stage']['resources']['wall_seconds'] = 60
    work = tmp_path / 'w'
    run(document, work, poll=0.05)
    path = work / pe.LEDGER
    ledger = json.loads(path.read_text())
    row = ledger['partitions']['p00000']
    started = (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()
    row['status'] = 'unresolved'
    row['attempts'][-1].update(state='unresolved', started_utc=started)
    path.write_text(json.dumps(ledger))
    handle = eb.read_handle(Path(row['attempts'][-1]['attempt_dir']))
    eb.write_handle({**handle, 'state': 'submitted', 'resolution': None})
    calls = []

    class Remote:
        def is_local(self, stage):
            return False
    monkeypatch.setattr(eb, 'get', lambda kind: Remote())
    monkeypatch.setattr(eb, 'is_local', lambda plan: False)
    monkeypatch.setattr(eb, 'load_plan', lambda path, verify_inputs=False: json.loads(Path(path).read_text()))
    monkeypatch.setattr(eb, 'remote_slot', lambda holder: contextlib.nullcontext())
    monkeypatch.setattr(eb, 'observe', lambda plan, handle: calls.append('observe') or {'state': 'running',
                                                                                        'exit_code': None})
    monkeypatch.setattr(eb, 'cancel', lambda plan, handle, wait_seconds=0: calls.append('cancel') or {
        'state': 'cancelled', 'exit_code': None})

    def no_sleep(seconds):
        raise AssertionError('observation slept past the adopted job\'s original deadline')
    monkeypatch.setattr(pe.time, 'sleep', no_sleep)
    return document, work, path, calls


def test_an_adopted_remote_job_keeps_its_original_wall_clock_deadline(tmp_path, monkeypatch):
    document, work, path, calls = _remote_left_running(tmp_path, monkeypatch, seconds_ago=3600)
    run(document, work, poll=0.05)
    assert calls[-1] == 'cancel' and 'sleep' not in calls
    entry = json.loads(path.read_text())['partitions']['p00000']['attempts'][-1]
    assert 'wall-clock ceiling' in entry['detail']


def test_an_adopted_remote_job_counts_against_the_approved_wall_clock(tmp_path, monkeypatch):
    document, work, path, calls = _remote_left_running(tmp_path, monkeypatch, seconds_ago=0)
    _approve(monkeypatch, max_seconds=1)
    with pytest.raises(ValueError, match='ceiling is 1 s'):
        run(document, work, poll=0.05)
    assert 'cancel' not in calls
    assert json.loads(path.read_text())['partitions']['p00000']['status'] == 'unresolved'


def _failing_submit(monkeypatch, exc, calls, cancel_state):
    def submit(plan, attempt, authority=None):
        attempt = Path(attempt)
        attempt.mkdir(parents=True, exist_ok=True)
        eb.write_handle({'attempt_dir': str(attempt), 'tag': 't', 'state': 'submitted', 'backend': 'native',
                         'remote': {'pid': 1, 'pgid': 1, 'identity': 'synthetic'}, 'resolution': None})
        raise exc
    monkeypatch.setattr(eb, 'submit', submit)
    monkeypatch.setattr(eb, 'cancel', lambda plan, handle, wait_seconds=0: calls.append('cancel') or {
        'state': cancel_state, 'exit_code': None})


@pytest.mark.parametrize('exc', [OSError('connection lost after the job started'),
                                 pe.machine_lease.LeaseBusy('busy after the handle was written', None)])
def test_a_submission_that_failed_after_writing_an_identity_is_cancelled_not_retried(tmp_path, monkeypatch, exc):
    files = population(tmp_path, n=2)
    document = spec(tmp_path, files, per=2, attempts=3)
    calls = []
    _failing_submit(monkeypatch, exc, calls, cancel_state='running')
    work = tmp_path / 'w'
    run(document, work, poll=0.05)
    row = json.loads((work / pe.LEDGER).read_text())['partitions']['p00000']
    assert calls == ['cancel']
    assert row['status'] == 'unresolved' and len(row['attempts']) == 1
    assert row['attempts'][0]['state'] == 'unresolved'


def test_an_operator_cleared_job_with_a_known_identity_is_settled_not_observed(tmp_path, monkeypatch):
    document, work, path, calls = _remote_left_running(tmp_path, monkeypatch, seconds_ago=0)
    attempt = Path(json.loads(path.read_text())['partitions']['p00000']['attempts'][-1]['attempt_dir'])
    eb.write_handle({**eb.read_handle(attempt), 'resolution': 'operator-cleared'})
    run(document, work, poll=0.05)
    entry = json.loads(path.read_text())['partitions']['p00000']['attempts'][-1]
    assert calls == [] and entry['state'] == 'failed' and 'operator cleared' in entry['detail']
