"""Payload custody through a native backend: proven link by link, never assumed."""
from __future__ import annotations

import json
import sys

import pytest

from ravel.workflow import execution, execution_backend as eb, machine_lease as ml, stage_supervisor
from test_checkin2_gate import _run, _ws


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('WORKFLOW_STATE_UTC', '2026-10-08T00:00:00Z')
    monkeypatch.delenv(ml.ENV, raising=False)
    eb._INSTANCES.clear()


def probe_spec(root, code):
    return {'schema_version': 1, 'backend': 'native', 'stage': 'probe',
            'argv': [sys.executable, '-c', code, str(root)],
            'outputs': [{'name': 'custody.json', 'destination': 'outputs/custody.json'}],
            'resources': {'cpus': 1, 'memory_mib': 128, 'wall_seconds': 60},
            'inherit_runtime_environment': True}


def pinned_plan(tmp_path, code):
    """An approved run whose backend plan was pinned before CHECK-IN 1 approval."""
    root = _run(tmp_path, plan='smoke', approve=False, checkin2=False)
    (root / 'logs').mkdir(parents=True, exist_ok=True)
    (root / 'inputs/backend-plans').mkdir()
    plan = eb.write_plan(eb.prepare(probe_spec(root, code)), root / 'inputs/backend-plans/probe.json')
    result = _ws('approve', '--rundir', root, '--quote', 'Yes, run the plan', '--plan', 'smoke')
    assert result.returncode == 0, result.stderr
    return root, plan


def run_payload(tmp_path, code):
    root, plan = pinned_plan(tmp_path, code)
    code = stage_supervisor.supervise('probe', root, 10, 'logs/probe.log', None, kill_secs=60.0,
                                      poll=0.1, grace=3.0, backend_plan=plan, required_plan='smoke')
    return code, root


WRITE = ('import json,os,sys\n'
         'from pathlib import Path\n'
         'out = Path(os.environ["RAVEL_OUTPUT_DIR"]) / "custody.json"\n'
         'def report(value): out.write_text(json.dumps(value))\n')

DIRECT_PAYLOAD = WRITE + (
    'from ravel.workflow import execution\n'
    'try:\n'
    '    report(execution.await_worker_registration(sys.argv[1], "probe"))\n'
    'except ValueError as exc:\n'
    '    report({"refused": str(exc)})\n')

GRANDCHILD = WRITE + (
    'import subprocess\n'
    'child = ("import json,sys\\nfrom ravel.workflow import execution\\n"\n'
    '         "try:\\n    print(json.dumps(execution.await_worker_registration(sys.argv[1], \'probe\', timeout=0.5)))\\n"\n'
    '         "except ValueError as exc:\\n    print(json.dumps({\'refused\': str(exc)}))\\n")\n'
    'report(json.loads(subprocess.check_output([sys.executable, "-c", child, sys.argv[1]], text=True)))\n')

OTHER_JOB = WRITE + (
    'from ravel.workflow import execution\n'
    'os.environ["RAVEL_BACKEND_JOB"] = str(Path(sys.argv[1]) / "elsewhere/job")\n'
    'try:\n'
    '    report(execution.await_worker_registration(sys.argv[1], "probe", timeout=0.5))\n'
    'except ValueError as exc:\n'
    '    report({"refused": str(exc)})\n')

FORGED_ACK = WRITE + (
    'from ravel.workflow import execution\n'
    'job = Path(os.environ["RAVEL_BACKEND_JOB"])\n'
    'import time\n'
    'while not (job / "payload.json").exists(): time.sleep(0.01)\n'
    '(job / "payload.json").write_text(json.dumps({"pid": 1, "identity": "forged"}))\n'
    'try:\n'
    '    report(execution.await_worker_registration(sys.argv[1], "probe", timeout=0.5))\n'
    'except ValueError as exc:\n'
    '    report({"refused": str(exc)})\n')


FORGED_PLAN = WRITE + (
    'from ravel.workflow import execution\n'
    'job = Path(os.environ["RAVEL_BACKEND_JOB"])\n'
    'plan = job.parent / "plan.json"\n'
    'plan.write_bytes(plan.read_bytes() + b" ")\n'
    'try:\n'
    '    report(execution.await_worker_registration(sys.argv[1], "probe", timeout=0.5))\n'
    'except ValueError as exc:\n'
    '    report({"refused": str(exc)})\n')


def custody(root):
    return json.loads((root / 'outputs/custody.json').read_text())


def test_the_launcher_child_proves_its_backend_custody(tmp_path):
    code, root = run_payload(tmp_path, DIRECT_PAYLOAD)
    record = custody(root)
    assert code == 0, (root / 'logs/probe.log').read_text()
    stage = execution.load_execution(root)['stages']['probe']
    assert record['mode'] == 'backend'
    assert record['supervisor_pid'] == stage['supervisor_pid'] and record['worker_pid'] == stage['child_pid']
    handle = json.loads(eb.stage_handles(root, 'probe')[0].read_text())
    assert record['launcher_pid'] == handle['remote']['pid'] and record['payload_pid'] != record['launcher_pid']


@pytest.mark.parametrize('payload,reason', [
    (GRANDCHILD, 'not the child of the recorded launcher'),
    (OTHER_JOB, "not the current attempt's job"),
    (FORGED_ACK, 'did not acknowledge this payload'),
    (FORGED_PLAN, 'not the pinned plan'),
])
def test_a_broken_custody_link_is_refused(tmp_path, payload, reason):
    code, root = run_payload(tmp_path, payload)
    record = custody(root)
    assert code == 0, (root / 'logs/probe.log').read_text()
    assert 'refused' in record and reason in record['refused']


def test_an_unplaced_process_with_a_job_name_is_refused(tmp_path, monkeypatch):
    root = tmp_path / 'run'
    root.mkdir()
    monkeypatch.setenv('RAVEL_BACKEND_JOB', str(root / 'logs/execution/probe/x/backend/job'))
    with pytest.raises(ValueError):
        execution.worker_custody(root, 'probe', {'status': 'running', 'attempt_id': 'x', 'supervisor_pid': 999999999})


def test_a_plan_changed_between_the_attempt_and_the_worker_is_refused(tmp_path, monkeypatch):
    from ravel.workflow import launch_authorization
    root, plan = pinned_plan(tmp_path, DIRECT_PAYLOAD)
    swapped = eb.prepare({**probe_spec(root, DIRECT_PAYLOAD), 'resources': {'cpus': 1, 'memory_mib': 256,
                                                                             'wall_seconds': 60}})
    original_prepare = launch_authorization._prepare_popen_authorization

    def prepared_then_swap(*args, **kwargs):
        # The swap lands after the launch authorization and before the worker reads the plan.
        event = original_prepare(*args, **kwargs)
        plan.write_text(json.dumps(swapped))
        return event
    monkeypatch.setattr(launch_authorization, '_prepare_popen_authorization', prepared_then_swap)
    code = stage_supervisor.supervise('probe', root, 10, 'logs/probe.log', None, kill_secs=60.0,
                                      poll=0.1, grace=3.0, backend_plan=plan, required_plan='smoke')
    log = (root / 'logs/probe.log').read_text()
    assert code == 2 and 'changed after the supervised attempt pinned it' in log, log
    assert eb.stage_handles(root, 'probe') == []
