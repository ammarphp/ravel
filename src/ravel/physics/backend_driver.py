"""Run one native stage through the execution backend and wait for its declared outputs.

``drive(spec, attempt_dir, base)`` prepares a backend plan from the stage
specification, takes the machine lease (local backends) or a remote slot,
submits, observes until a terminal state or the declared wall time, cancels on
overrun and fetches the declared outputs. Nothing runs outside the backend.

Both drivers run only for the proven worker of an approved supervised stage
(``calling_authority``): the caller must work under that stage's machine lease
and pass ``execution_backend.require_approved_stage``. This holds for every
``backend`` argument, including the real backend module; tests that drive an
in-process double replace ``calling_authority`` explicitly. The sub-stage's lease
is nested in the approved stage's job, so it is never a second concurrent native
job. Any error or interruption after submission cancels the job before the
lease scope ends.

``drive_stage(spec, base)`` runs the same stage as a supervised stage of
``base`` through ``stage_supervisor.backend_stage``: the plan is pinned as a
stage input, the stage receipt, lease and backend handle are those of every
other supervised launch. Each sub-stage's plan is pinned by stage name in
``base/backend-plans/<stage>.json``; a changed plan for an existing stage is
refused (a changed stage is a changed study). A plan new to the store is admitted
only when every input lies in the store or is a pinned input of the approving
stage, and its wall time fits that stage's approved ceiling. The sub-stage record
carries the approving stage's authority. A submission that fails after recording a
job identity cancels that job.
"""
from __future__ import annotations

from pathlib import Path
import time

TERMINAL = ('succeeded', 'failed', 'cancelled')


class StageFailed(RuntimeError):
    def __init__(self, message, observation):
        super().__init__(message)
        self.observation = observation


def backend_module():
    from ravel.workflow import execution_backend
    return execution_backend


def calling_authority():
    """The approved supervised stage whose proven worker this process is; refuse otherwise."""
    from ravel.workflow import execution_backend, machine_lease
    lease = machine_lease.inherited()
    if lease is None or lease.rundir is None or lease.node_id is None:
        raise ValueError('a native backend stage runs only inside an approved supervised stage that holds '
                         'the machine lease; nothing was started')
    return execution_backend.require_approved_stage(lease.rundir, lease.node_id)


def drive(spec, attempt_dir, base, *, backend=None, poll=5.0, grace_seconds=60.0, clock=time.monotonic,
          sleep=time.sleep, holder=None):
    calling_authority()
    eb = backend if backend is not None else backend_module()
    plan = eb.prepare(spec, base=base)
    capacity = getattr(eb, 'capacity', None)
    holder = holder or f'ravel:{spec["stage"]}'
    if capacity is None:
        return _run(eb, plan, spec, attempt_dir, base, poll, grace_seconds, clock, sleep)
    with capacity(plan, holder, nested=True):
        return _run(eb, plan, spec, attempt_dir, base, poll, grace_seconds, clock, sleep)


def _cancel_partial(eb, plan, attempt_dir):
    """A submission that failed after recording a job identity: cancel that job before the lease scope ends."""
    try:
        if (Path(attempt_dir) / eb.HANDLE_NAME).is_file():
            handle = eb.read_handle(attempt_dir)
            if handle.get('remote') is not None:
                eb.cancel(plan, handle)
    except Exception:
        pass  # the handle stays for recovery; the original error is raised


def _run(eb, plan, spec, attempt_dir, base, poll, grace_seconds, clock, sleep):
    try:
        handle = eb.submit(plan, attempt_dir)
    except BaseException:
        _cancel_partial(eb, plan, attempt_dir)
        raise
    deadline = clock() + spec['resources']['wall_seconds'] + grace_seconds
    try:
        while True:
            observation = eb.observe(plan, handle)
            if observation['state'] in TERMINAL:
                break
            if clock() > deadline:
                observation = eb.cancel(plan, handle)
                raise StageFailed(f'stage {spec["stage"]} exceeded its wall time and was cancelled', observation)
            sleep(poll)
    except StageFailed:
        raise
    except BaseException:
        # An error or interruption while the job runs cancels it before the lease scope ends.
        try:
            eb.cancel(plan, handle)
        except Exception:
            pass
        raise
    if observation['state'] != 'succeeded':
        raise StageFailed(f'stage {spec["stage"]} ended {observation["state"]}', observation)
    receipt = eb.fetch(plan, handle, base)
    return {'plan_sha256': plan['plan_sha256'], 'observation': observation, 'receipt': receipt}


def _bind_child(spec, base, authority):
    """A new child plan derives from the approving stage: every input lies in the store the approved
    worker writes, or is a pinned input of that stage, and its wall time fits the approved ceiling."""
    from ravel.workflow import execution
    record = execution.load_execution(authority['rundir'])['stages'].get(authority['stage']) or {}
    approved = set(record.get('input_snapshot') or {})
    for item in spec.get('inputs', []):
        source = Path(item['path']).resolve()
        if not (source.is_relative_to(base) or str(source) in approved):
            raise ValueError(f'input {source} of stage {spec["stage"]} is neither in the store nor among the '
                             f'approved inputs of stage {authority["stage"]}; nothing was started')
    ceiling = authority.get('max_seconds')
    if isinstance(ceiling, (int, float)) and not isinstance(ceiling, bool) \
            and spec['resources']['wall_seconds'] > ceiling:
        raise ValueError(f'stage {spec["stage"]} asks for {spec["resources"]["wall_seconds"]} s; the approved '
                         f'stage ceiling is {ceiling:g} s; nothing was started')


def drive_stage(spec, base, *, poll=5.0, grace_seconds=60.0):
    """Run one backend stage as a supervised stage of ``base`` (stage_supervisor.backend_stage)."""
    from ravel.workflow import execution_backend as eb, stage_supervisor
    from ravel.workflow.state_io import read_json
    authority = calling_authority()
    base = Path(base).resolve()
    plan = eb.prepare(spec, base=base)
    path = base / 'backend-plans' / f'{spec["stage"]}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if eb.load_plan(path, verify_inputs=False)['plan_sha256'] != plan['plan_sha256']:
            raise ValueError(f'the pinned backend plan of stage {spec["stage"]} ({path}) differs from this stage; '
                             'a changed stage is a changed study; use a new store')
    else:
        _bind_child(spec, base, authority)
        eb.write_plan(plan, path)
    (base / 'logs').mkdir(exist_ok=True)
    stage = spec['stage']
    code = stage_supervisor.supervise(stage, str(base), 0, f'logs/{stage}.log', None,
                                      kill_secs=spec['resources']['wall_seconds'] + grace_seconds,
                                      poll=min(poll, stage_supervisor.POLL_SECS), backend_plan=str(path),
                                      nested_under=(authority['rundir'], authority['stage']))
    if code:
        raise StageFailed(f'stage {stage} ended with exit {code}; see {base / "logs" / (stage + ".log")}',
                          {'state': 'failed', 'exit_code': code})
    from ravel.workflow import execution
    attempt = execution.load_execution(base)['stages'][stage]['attempt_id']
    receipt_path = eb.attempt_backend_dir(base, stage, attempt) / eb.RECEIPT_NAME
    if not receipt_path.is_file() or read_json(receipt_path)['plan_sha256'] != plan['plan_sha256']:
        raise StageFailed(f'stage {stage} succeeded without its backend fetch receipt', {'state': 'failed', 'exit_code': None})
    return {'plan_sha256': plan['plan_sha256'], 'plan': str(path), 'observation': {'state': 'succeeded', 'exit_code': 0},
            'receipt': read_json(receipt_path)}
