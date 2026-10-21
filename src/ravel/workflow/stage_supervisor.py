#!/usr/bin/env python3
"""stage_supervisor.py -- CATCH watchdog wrapping ONE pipeline stage command (G6/D6).
Stock macOS has no `timeout`; this is the python subprocess supervisor that replaces the inner
`( "$@" )` of run-pipeline-native.sh:run_stage. It launches the stage command, polls wall-clock +
progress-stall + exit-0-plausibility against per-stage kill thresholds DERIVED FROM cost_preflight,
and on a hang SIGTERM/SIGKILLs it, writes logs/<stage>.failure.json (+ a next-action), records it to
the run ledger (workflow_state.py record --kind failure), and returns nonzero so the existing
stage_done writes the FAIL/STOPPED STATUS.txt line -> the bg job COMPLETES ->
the harness completion-notification fires. stdlib-only, fail-loud.
Usage: stage_supervisor.py --stage <n> --rundir <d> --events <e> --log <rel> -- <cmd...>  |  --selftest
Exit codes: the wrapped rc on clean exit (0 PASS) * 124 killed-hang * 3 exit-0-implausible * 2 usage."""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.workflow"

import argparse, hashlib, json, os, signal, subprocess, sys, time
from contextlib import contextmanager
import threading
from pathlib import Path
from datetime import datetime, timezone
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from ravel.workflow import cost_preflight as cp  # noqa: E402
from ravel.workflow import execution
# Only these fixed inert commands may run the engineering self-test inside an
# agent session. Arbitrary engineering commands retain the session refusal.
_ENGINEERING_SELFTEST = object()
_ENGINEERING_SELFTEST_COMMANDS = (
    (sys.executable, '-c', 'import time; time.sleep(60)'),
    (sys.executable, '-c', "print('done')"),
    (sys.executable, '-c', 'import sys; sys.exit(0)'),
)
from ravel.workflow.state_io import atomic_json, file_lock


class _OperationOwner:
    """Sample a source-declared operation using this existing stage owner.

    The scientific parent worker, constructor and observed descendants enter
    one aggregate RSS sum. Sampling cannot establish an instantaneous maximum
    or discover an unobserved short-lived detached process.
    """
    def __init__(self, limits, started, outer_seconds):
        import math
        if (type(limits) is not dict or set(limits)!={'max_seconds','max_ram_mib','source'}
                or type(limits['max_seconds']) not in (int,float) or not math.isfinite(limits['max_seconds'])
                or not 0<limits['max_seconds']<=outer_seconds or type(limits['max_ram_mib']) is not int
                or not 256<=limits['max_ram_mib']<=16384):
            raise ValueError('finite source-bound complete-operation owner limits required')
        source=limits['source']
        if type(source) is not dict or set(source)!={'path','sha256'} or execution.file_hash(source['path'])!=source['sha256']:
            raise ValueError('operation resource source differs from its admitted input')
        self.limits=limits;self.clock={'started_monotonic':started,'deadline_monotonic':started+limits['max_seconds']}
        self.owner_pid=os.getpid();self.owner_group=os.getpgrp();self.proc=None;self.observed={};self.groups={}
        self.samples=0;self.peak=0.;self.last=[]
        self.sample()

    def _table(self,deadline=None):
        remaining=(self.clock['deadline_monotonic'] if deadline is None else deadline)-time.monotonic()
        if remaining<=0:raise ValueError('complete-operation original deadline exhausted')
        try:raw=subprocess.check_output(['/bin/ps','-axo','pid=,ppid=,pgid=,rss=,stat=,lstart='],text=True,timeout=min(.5,remaining))
        except (OSError,subprocess.SubprocessError) as exc:raise ValueError('operation process observation unavailable: '+str(exc)) from exc
        if len(raw.encode())>8*1024**2:raise ValueError('operation process observation byte ceiling')
        table={}
        for line in raw.splitlines():
            z=line.split(None,5)
            if len(z)!=6 or not all(x.isdecimal() for x in z[:4]):raise ValueError('malformed operation process observation')
            if z[4].startswith('Z'):continue
            pid,ppid,pgid,rss=map(int,z[:4])
            if pid<=0 or pid in table or not z[5].strip():raise ValueError('ambiguous operation process observation')
            table[pid]={'pid':pid,'ppid':ppid,'pgid':pgid,'rss_kib':rss,'identity':z[5].strip()}
        if len(table)>32768:raise ValueError('operation process observation count ceiling')
        return table

    def attach(self,proc,identity):
        if not identity:raise ValueError('operation worker launch identity unavailable')
        self.proc=proc;self.observed[proc.pid]={'pid':proc.pid,'identity':identity}
        self.sample()

    def sample(self):
        table=self._table()
        if self.owner_pid not in table:raise ValueError('operation owner process observation absent')
        selected={self.owner_pid}|{p for p,r in self.observed.items() if p in table and table[p]['identity']==r['identity']}
        for _ in range(len(table)):
            new=selected|{p for p,r in table.items() if r['ppid'] in selected}
            if new==selected:break
            selected=new
        self.last=sorted(selected & table.keys())
        for p in self.last:
            row=table[p];self.observed[p]=row
            if row['pgid']==p and row['pgid']!=self.owner_group:self.groups[p]=row['identity']
        if len(self.groups)>64:raise ValueError('finite observed operation group ceiling exceeded')
        total=sum(table[p]['rss_kib'] for p in self.last)/1024.;self.peak=max(self.peak,total);self.samples+=1
        if total>self.limits['max_ram_mib']:raise ValueError('complete-operation sampled owner plus descendant RSS ceiling exceeded')
        if time.monotonic()>=self.clock['deadline_monotonic']:raise ValueError('complete-operation original deadline exhausted')
        return total

    def report(self):
        return {'limits':self.limits,'clock':self.clock,'owner_pid':self.owner_pid,'worker_pid':None if self.proc is None else self.proc.pid,
                'peak_sampled_aggregate_rss_mib':self.peak,'samples':self.samples,'observed_processes':self.observed,
                'sampling':'existing stage owner, poll sleep capped at 0.1s plus bounded observation latency; owner/scientific parent worker/observed descendants; no instantaneous-memory guarantee',
                'process_identity_scope':'existing local ps start identity; not a remote or continuous-revocation proof'}

    def close_extra_groups(self,grace):
        rows=[];cleanup_deadline=time.monotonic()+2*grace
        for pgid,identity in self.groups.items():
            if pgid==self.owner_group or self.proc is not None and pgid==self.proc.pid:continue
            if time.monotonic()>=cleanup_deadline:
                rows.append({'process_group':pgid,'remaining_group_members':None,'requires_recovery':True,'error':'finite cleanup deadline exhausted; no signal'});continue
            table=self._table(cleanup_deadline)
            members=sorted(p for p,r in table.items() if r['pgid']==pgid)
            if not members:
                rows.append({'process_group':pgid,'remaining_group_members':[],'requires_recovery':False});continue
            if table.get(pgid,{}).get('identity')!=identity:
                rows.append({'process_group':pgid,'remaining_group_members':members,'requires_recovery':True,'had_active_members':True,'error':'owned group leader identity absent or replaced; no signal'});continue
            def observe_group(selected):
                current=self._table(cleanup_deadline)
                return sorted(p for p,r in current.items() if r['pgid']==selected)
            result=_terminate_owned_group(pgid,min(grace,max(0.,(cleanup_deadline-time.monotonic())/2)),
                observer=observe_group,cleanup_deadline=cleanup_deadline)
            rows.append({**result,'had_active_members':True})
        return rows

SCHEMA_VERSION = 1
KILL_MARGIN = 3.0          # kill at 3x the modelled stage budget
PYHF_MEASURED_MIN = 20.0   # MEASURED, not modelled (2026-08-28 compressed-slepton waypoint m150_dm20:
                           # 1036 s = 17.3 min SOLO full-stat on the 141-SR Slepton workspace;
                           # smoke rung 18.5 min). The 12-min flat-rest model under-budgets pyhf:
                           # its CLs scan is workspace-sized, event-count-independent. Budget 20 min
                           # -> stall 20 min (heartbeat lands every ~45-90 s, so stall only fires on
                           # a real hang) and kill 60 min (3x), headroom for parallel=3 contention.
FLOOR_SECS = 300.0         # never kill before 5 min (protect legitimately fast stages)
POLL_SECS = 5.0
GRACE_SECS = 10.0          # SIGTERM -> wait -> SIGKILL
CONTAINER_CLEANUP_SECS = 60.0  # Separate source-declared guest reserve, not host TERM grace.
CLEANUP_CENSUS_SCOPE = "non-zombie process-group members reported by ps; zombies excluded"
MUST_PRODUCE = ("madgraph", "pythia", "delphes", "analysis", "simpleanalysis", "sa2json", "pyhf")

def _resolve_timestamp(rundir=None):
    if rundir is not None and _controller_run(rundir) is not None:
        return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    ov = os.environ.get("GATE_TIMESTAMP")
    return ov if ov else execution.utc_now()

def stage_budget_min(stage, events):
    """Modelled wall-clock budget (minutes) for a stage. Only quantified data is cost_preflight's
    {MadGraph-linear-in-events, 12-min-flat-rest} split -- there is no finer per-stage table."""
    scale = (float(events) if events else cp.NATIVE_REF_EVENTS) / cp.NATIVE_REF_EVENTS
    if stage == "madgraph":
        return (cp.NATIVE_PT_MIN_HI - cp.NATIVE_FLAT_MIN) * scale
    if stage == "pyhf":
        return max(cp.NATIVE_FLAT_MIN, PYHF_MEASURED_MIN)
    return cp.NATIVE_FLAT_MIN

def _fingerprint(cmd):
    return hashlib.sha256((" ".join(cmd)).encode("utf-8")).hexdigest()

def write_failure(rundir, stage, reason, elapsed, kill_secs, cmd, logrel, *, cleanup=None):
    rec = {
        "schema_version": SCHEMA_VERSION, "generated_by": "stage_supervisor.py",
        "generator": "stage_supervisor.py", "generated_utc": _resolve_timestamp(rundir),
        "input_fingerprint": _fingerprint(cmd), "stage": stage, "status": "open",
        "reason": reason, "elapsed_s": round(elapsed, 1), "kill_threshold_s": round(kill_secs, 1),
        "logfile": logrel,
        "next_action": (f"stage '{stage}' failed after {round(elapsed)}s ({reason}). "
                        f"Inspect {logrel} and execution_state.json; fix the input or tool "
                        "and resume the declared pipeline. Earlier attempts are retained; "
                        "deleting a status file is not evidence of recovery."),
    }
    if cleanup is not None:
        rec["cleanup"] = cleanup
    path = os.path.join(rundir, "logs", f"{stage}.failure.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_json(path, rec)
    # Durably record the open failure in the run ledger so the Stop CATCH branch's
    # FALLBACK (`workflow_state.py status` -> open_failure_records) sees it. Best-effort: never let a
    # ledger hiccup (missing/older run_state, CLI drift) mask the stage failure the caller surfaces.
    ws = os.path.join(HERE, "workflow_state.py")
    controller_run = _controller_run(rundir)
    if controller_run is not None:
        from ravel.controller.confine import runs
        runs.store(controller_run).append('stage-failure', rec)
    elif os.path.isfile(ws):
        try:
            subprocess.run([sys.executable, ws, "record", "--kind", "failure",
                            "--rundir", rundir, "--what", os.path.relpath(path, rundir)],
                           capture_output=True, text=True, timeout=30)
        except Exception:
            pass
    return path

def _cleanup_error(result, operation, exc):
    result["errors"].append({"operation": operation, "type": type(exc).__name__,
                             "message": str(exc)})


_REAPER_LOCK = threading.RLock()
_REAPER_USERS = 0
_REAPER_PREVIOUS = 0


@contextmanager
def _child_reaper():
    """Adopt orphaned grandchildren on Linux so cleanup can actually wait for them."""
    global _REAPER_USERS, _REAPER_PREVIOUS
    if not sys.platform.startswith('linux'):
        yield
        return
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    with _REAPER_LOCK:
        if not _REAPER_USERS:
            previous = ctypes.c_int()
            if libc.prctl(37, ctypes.byref(previous), 0, 0, 0) or libc.prctl(36, 1, 0, 0, 0):
                raise ValueError('cannot establish descendant reaping; stage held')
            _REAPER_PREVIOUS = previous.value
        _REAPER_USERS += 1
    try:
        yield
    finally:
        with _REAPER_LOCK:
            _REAPER_USERS -= 1
            if not _REAPER_USERS:
                if libc.prctl(36, _REAPER_PREVIOUS, 0, 0, 0):
                    raise ValueError('cannot restore descendant reaper state')


def _reap_group(result, proc=None):
    reaped = result.setdefault('reaped_descendants', [])
    while True:
        try:
            pid, status = os.waitpid(-result['process_group'], os.WNOHANG)
        except ChildProcessError:
            return False
        except OSError as exc:
            _cleanup_error(result, 'reap_descendant', exc)
            result['reaping_error'] = True
            return True
        if not pid:
            return True
        if pid == result['process_group']:
            result['leader_returncode'] = os.waitstatus_to_exitcode(status)
            if proc is not None:
                proc.returncode = result['leader_returncode']
        elif pid not in reaped:
            reaped.append(pid)


def _observe_group(result,observer=None,proc=None):
    # execution's census excludes zombies. "empty" means no active members in
    # this group, not proof that every OS process-table entry has disappeared.
    if observer is None:
        _reap_group(result, proc)
    try:
        members = (execution.process_group_members(result["process_group"]) if observer is None
                   else observer(result["process_group"]))
    except (Exception, KeyboardInterrupt) as exc:
        _cleanup_error(result, "query_process_group", exc)
        members = None
    result["remaining_group_members"] = members
    result["group_state"] = "unknown" if members is None else ("active" if members else "empty")
    pending = _reap_group(result, proc) if observer is None else False
    result["requires_recovery"] = members is None or bool(members) or pending or result.get('reaping_error', False)
    return members


def _terminate_owned_group(pid, grace, proc=None, *, observer=None, cleanup_deadline=None):
    """Bound cleanup without confusing a signal attempt with observed quiescence.

    Each signal has at most one grace interval, plus a bounded leader wait. Process
    queries also have their own timeout in execution.process_group_members. A denied
    signal or failed query is retained and held for explicit recovery, not retried in
    an exception handler. In particular, a dead wrapper is not proof of dead children.
    """
    result = {"process_group": pid, "signals": [], "errors": [],
              "census_scope": CLEANUP_CENSUS_SCOPE,
              "remaining_group_members": None, "group_state": "unknown",
              "leader_returncode": None, "requires_recovery": True}
    def poll_leader():
        if proc is not None:
            try:
                result["leader_returncode"] = proc.poll()
            except (Exception, KeyboardInterrupt) as exc:
                _cleanup_error(result, "poll_leader", exc)
    # Reap our own exited child before each census, while still inspecting any
    # surviving descendants. Reaping a wrapper cannot establish an empty group.
    poll_leader()
    members = _observe_group(result,observer,proc)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not members:  # Empty is finished; unknown is held without blind escalation.
            break
        if cleanup_deadline is not None and time.monotonic()>=cleanup_deadline:
            result['errors'].append({'operation':'cleanup_deadline','type':'Timeout','message':'finite cleanup deadline exhausted; no signal'})
            result['requires_recovery']=True
            break
        action = {"signal": sig.name}
        result["signals"].append(action)
        try:
            os.killpg(pid, sig)
            action["outcome"] = "sent"
        except ProcessLookupError:
            action["outcome"] = "not_found"
        except (Exception, KeyboardInterrupt) as exc:
            action["outcome"] = "error"
            _cleanup_error(result, sig.name, exc)
        if action["outcome"] != "sent":
            _observe_group(result,observer,proc)
            break
        deadline = time.monotonic() + grace
        if cleanup_deadline is not None:deadline=min(deadline,cleanup_deadline)
        while True:
            poll_leader()
            members = _observe_group(result,observer,proc)
            remaining = deadline - time.monotonic()
            if not members or remaining <= 0:
                break
            try:
                time.sleep(min(0.1, remaining))
            except (Exception, KeyboardInterrupt) as exc:
                _cleanup_error(result, "wait_for_group", exc)
                result["requires_recovery"] = True
                return result
    if proc is not None:
        wait_failed = False
        try:
            result["leader_returncode"] = proc.wait(timeout=grace if cleanup_deadline is None else max(0.,min(grace,cleanup_deadline-time.monotonic())))
        except (Exception, KeyboardInterrupt) as exc:
            _cleanup_error(result, "wait_for_leader", exc)
            wait_failed = True
        # The bounded wait can change group membership. Report this later observed
        # state without retroactively claiming that a denied signal succeeded.
        _observe_group(result,observer,proc)
        result["requires_recovery"] |= wait_failed
    return result


def _terminate_group(proc, grace):
    return _terminate_owned_group(proc.pid, grace, proc)


def _safe_cleanup(proc, grace):
    # Even an unexpected cleanup implementation failure must not erase the primary
    # stage failure or leave its durable attempt recorded as running.
    try:
        return _terminate_group(proc, grace)
    except (Exception, KeyboardInterrupt) as exc:
        result = {"process_group": proc.pid, "signals": [], "errors": [],
                  "census_scope": CLEANUP_CENSUS_SCOPE,
                  "remaining_group_members": None, "group_state": "unknown",
                  "leader_returncode": None, "requires_recovery": True}
        _cleanup_error(result, "cleanup", exc)
        return result


def _container_attempt_directory(root, record):
    """Only the outer attempt namespace can carry guest recovery authority."""
    import re
    if (not execution.NAME.fullmatch(record['stage'])
            or not re.fullmatch('[0-9a-f]{32}', record['attempt_id'])):
        raise ValueError('invalid container recovery attempt identity')
    expected = root / 'logs/execution' / record['stage'] / record['attempt_id']
    if root / record['attempt_record'] != expected / 'record.json':
        raise ValueError('container recovery attempt namespace differs')
    if any(p.is_symlink() for p in (expected, *expected.parents)):
        raise ValueError('container recovery attempt namespace is symlinked')
    return expected


def _container_pin(root, record, pin, name):
    directory = _container_attempt_directory(root, record)
    path = directory / name
    if (set(pin) != {'path', 'sha256'} or root / pin['path'] != path
            or any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file()
            or execution.file_hash(path) != pin['sha256']):
        raise ValueError('retained container recovery evidence changed')
    return execution.read_json(path)


def _container_snapshot(root, record):
    value = _container_pin(root, record, record['container_recovery_plan'], 'container-recovery-plan.json')
    keys = {'schema_version', 'stage', 'attempt_id', 'fingerprint', 'output', 'job',
            'job_input', 'science_plan_sha256', 'science_approval_sha256',
            'cleanup_seconds', 'worker_seconds', 'stage_binding'}
    if (set(value) != keys or value['schema_version'] != 1
            or any(value[k] != record[k] for k in ('stage', 'attempt_id', 'fingerprint'))
            or len(record['outputs']) != 1
            or value['output'] != str(execution.resolve_path(root, record['outputs'][0], output=True))
            or type(value['cleanup_seconds']) not in (int, float) or not 0 < value['cleanup_seconds'] <= 60
            or type(value['worker_seconds']) not in (int, float) or value['worker_seconds'] <= 0):
        raise ValueError('retained container recovery scope differs')
    import base64
    binding = value['stage_binding']
    if (binding.get('fingerprint') != record['fingerprint']
            or execution.digest({k: v for k, v in binding.items() if k != 'fingerprint'}) != record['fingerprint']
            or any(binding[k] != record[k] for k in binding)):
        raise ValueError('retained container stage binding differs')
    raw = base64.b64decode(value['job_input']['raw_base64'], validate=True)
    fact = value['job_input']['file']
    if (len(raw) != fact['size'] or hashlib.sha256(raw).hexdigest() != fact['sha256']
            or json.loads(raw) != value['job']):
        raise ValueError('retained container job bytes differ from approved input')
    bound = record['input_snapshot'].get(value['job_input']['path'])
    if (bound != {'kind': 'file', 'files': [value['job_input']['file']]}
            or execution.digest(value['job']) != value['job_input']['canonical_sha256']):
        raise ValueError('container recovery job differs from approved input binding')
    return value


def _prepare_container_recovery(root, stage, specification, record, kill_secs, guest_cleanup_secs):
    """Read-only admission followed by durable, exclusive capture BEFORE Popen.

    Qualification/science inputs are checked here. Recovery later uses this job,
    not worker output, and still checks the executable and observed ownership.
    """
    from . import science
    from ravel.physics import routine_build
    spec = science.execution_spec(root)
    if spec['mode'] != 'analyze':
        return
    backend = spec['task'].get('backend')
    if backend not in ('routine-build', 'simpleanalysis-built'):
        return
    proposal = execution.read_json(root / science.PLAN)
    base = Path(proposal['base_dir'])
    if backend == 'routine-build' and not routine_build._native_container_task(spec['task'], base):
        return
    selected = science.launch_binding(root, stage)
    if selected['binding'] != specification or len(selected['stage']['outputs']) != 1:
        raise ValueError('container recovery requires the exact approved single-output stage')
    output = execution.resolve_path(root, selected['stage']['outputs'][0], output=True)
    if backend == 'routine-build':
        built = routine_build.build_plan(spec['task'], base, output)
        planned_output = built['output_root']
        job_input = built['container_plan']
    else:
        from ravel.physics import simpleanalysis_events
        built = simpleanalysis_events.execution_plan(spec['task'], base, output)
        planned_output = built['output_directory']
        jp = science.regular(spec['task']['container_plan'], base)
        job_input = {'path': str(jp), 'sha256': execution.file_hash(jp)}
    if planned_output != str(output):
        raise ValueError('container recovery output differs from the approved stage')
    job = built['container_job']
    if guest_cleanup_secs != CONTAINER_CLEANUP_SECS:
        raise ValueError("container recovery requires its declared60second guest reserve")
    cleanup = CONTAINER_CLEANUP_SECS
    worker_seconds = kill_secs - cleanup
    if job['resources']['max_seconds'] > worker_seconds:
        raise ValueError('container stage lacks a prospective outer guest cleanup reserve')
    jp = Path(job_input['path'])
    bound = specification['input_snapshot'].get(str(jp))
    if (not bound or bound['kind'] != 'file' or len(bound['files']) != 1
            or bound['files'][0]['sha256'] != job_input['sha256']
            or execution.file_hash(jp) != job_input['sha256']
            or execution.read_json(jp) != job):
        raise ValueError('container recovery job is not the approved source input')
    import base64
    value = {'schema_version': 1, 'stage': stage, 'attempt_id': record['attempt_id'],
        'fingerprint': specification['fingerprint'], 'output': str(output), 'job': job,
        'job_input': {'path': str(jp), 'file': bound['files'][0], 'canonical_sha256': execution.digest(job),
                      'raw_base64': base64.b64encode(jp.read_bytes()).decode()},
        'stage_binding': specification,
        'science_plan_sha256': execution.file_hash(root / science.PLAN),
        'science_approval_sha256': execution.file_hash(root / science.APPROVAL),
        'cleanup_seconds': cleanup, 'worker_seconds': worker_seconds}
    directory = _container_attempt_directory(root, record)
    path = directory / 'container-recovery-plan.json'
    # Exclusive creation, fsync and read-only bytes; the durable record binds the
    # digest before any host client is launched. This is custody, not a signature.
    with path.open('xb') as f:
        f.write((json.dumps(value, sort_keys=True, allow_nan=False) + '\n').encode())
        f.flush(); os.fsync(f.fileno())
    path.chmod(0o444)
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    record['container_recovery_plan'] = {'path': str(path.relative_to(root)), 'sha256': execution.file_hash(path)}
    execution._update(root, stage, record)


def _recover_container(root, record, phase):
    """Observe guest quiescence independently of host PID/client outcome."""
    from ravel.physics import simpleanalysis_container
    import uuid
    snapshot = _container_snapshot(root, record)
    directory = _container_attempt_directory(root, record)
    journal = directory / ('container-recovery-' + phase + '-' + uuid.uuid4().hex)
    journal.mkdir()
    try:
        result = simpleanalysis_container.recover(snapshot['job'], snapshot['output'],
            max_seconds=snapshot['cleanup_seconds'], journal_directory=journal)
    except (Exception, KeyboardInterrupt) as exc:
        result = {'requires_recovery': True, 'errors': [{'type': type(exc).__name__, 'message': str(exc)}]}
        atomic_json(journal / 'container-cleanup.json', result)
    path = journal / 'container-cleanup.json'
    # Retain append-only outer observations without touching the worker receipt.
    pin = {'path': str(path.relative_to(root)), 'sha256': execution.file_hash(path)}
    record.setdefault('container_recovery_observations', []).append(pin)
    record['container_cleanup'] = {'requires_recovery': result.get('requires_recovery') is not False,
                                   'observation': pin}
    execution._update(root, record['stage'], record)
    return record['container_cleanup']


def _recover_container_orphan(root, stage):
    old = execution.load_execution(root)['stages'].get(stage, {})
    if not old:
        return
    if not old.get('container_recovery_plan'):
        if (_container_attempt_directory(root, old) / 'container-recovery-plan.json').exists():
            raise ValueError('retained container recovery authority is missing from its record')
        return
    _container_snapshot(root, old)  # Validate even a reusable successful record.
    terminal = old.get('container_cleanup')
    if old.get('status') == 'succeeded' and terminal and terminal.get('requires_recovery') is False:
        pin = terminal['observation']
        directory = _container_attempt_directory(root, old)
        candidate = root / pin['path']
        if candidate.parent.parent != directory or not candidate.parent.name.startswith('container-recovery-'):
            raise ValueError('container quiescence observation namespace differs')
        observation = _container_pin(root, old, pin, str(candidate.relative_to(directory)))
        if observation.get('requires_recovery') is not False:
            raise ValueError('container quiescence observation differs')
        return
    observed = _recover_container(root, old, 'resume')
    if observed['requires_recovery']:
        raise ValueError('previous owned container is unresolved; stage held')



# This is a bound on recovery metadata, not a scientific-output admission cap.
INTERRUPTED_RECORD_MAX_BYTES = 64 * 1024 * 1024


def _interrupted_record_bytes(path):
    """Consume a bounded regular metadata file without following a swapped link."""
    import stat
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('interrupted recovery metadata is symlinked; stage held')
    before = path.stat()
    def identity(row):
        return (row.st_dev, row.st_ino, row.st_mode, row.st_nlink, row.st_size,
                row.st_mtime_ns, row.st_ctime_ns)
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= INTERRUPTED_RECORD_MAX_BYTES:
        raise ValueError('interrupted recovery metadata must be a bounded regular file; stage held')
    # A post-stat replacement may be a FIFO/device, not merely a symlink.
    # Nonblocking descriptor admission precedes fstat; no stream open can wait
    # on that replacement before its regular-file identity is established.
    if not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_NONBLOCK'):
        raise ValueError('safe interrupted recovery descriptor admission unavailable; stage held')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                         | getattr(os, 'O_CLOEXEC', 0))
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or identity(opened) != identity(before):
            raise ValueError('interrupted recovery metadata changed at open; stage held')
        chunks = []
        remaining = before.st_size + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b''.join(chunks)
        ending = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (len(raw) != before.st_size or identity(ending) != identity(before)
            or identity(path.lstat()) != identity(before)
            or any(p.is_symlink() for p in (path, *path.parents))):
        raise ValueError('interrupted recovery metadata changed during read; stage held')
    return raw


def _interrupted_recovery_hold(root, old):
    """A negative terminal status never authorizes a relaunch or proves containment."""
    marker = old['interrupted_finalization']
    directory = _container_attempt_directory(root, old)
    expected = directory / 'interrupted-preterminal.json'
    pin = marker.get('preterminal', {}) if type(marker) is dict else {}
    raw = _interrupted_record_bytes(expected)
    if (pin != {'path': str(expected.relative_to(root)),
                'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
            or marker.get('requires_recovery') is not True
            or marker.get('descendant_containment') != 'not_established'):
        raise ValueError('interrupted finalization custody differs; stage held')
    raise ValueError('interrupted attempt is failed but recovery remains held: complete descendant '
                     'containment is not established; retain the spent attempt and inspect its '
                     'preterminal snapshot and external supervision evidence before any scoped operator recovery')


def _negative_finalize_interrupted(root, stage, observation):
    """Record failure only after the existing host/guest recovery barrier.

    ESRCH and an empty recorded group are scoped observations. A child can have
    escaped into another group, so this record deliberately remains unrecoverable
    through the generic resume path. No output receipt or new attempt is created.
    """
    current = execution.load_execution(root)['stages'].get(stage, {})
    if current.get('status') != 'running':
        return
    if current.get('stage') != stage:
        raise ValueError('interrupted ledger stage identity differs; stage held')
    if (not observation or observation.get('leader_state') != 'absent'
            or observation.get('group_state') != 'empty'
            or observation.get('process_group') != current.get('child_pid')):
        raise ValueError('previous RUNNING attempt lacks an identifiable stopped producer; stage held')
    directory = _container_attempt_directory(root, current)
    raw = _interrupted_record_bytes(directory / 'record.json')
    if json.loads(raw) != current:
        raise ValueError('interrupted attempt record and execution ledger differ; stage held')
    snapshot = directory / 'interrupted-preterminal.json'
    # Commit the observed preterminal bytes; never rebase a snapshot on a later read.
    if snapshot.exists() or snapshot.is_symlink():
        if _interrupted_record_bytes(snapshot) != raw:
            raise ValueError('retained interrupted preterminal snapshot differs; stage held')
    else:
        with snapshot.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        snapshot.chmod(0o444)
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    if _interrupted_record_bytes(snapshot) != raw:
        raise ValueError('interrupted preterminal snapshot persistence differs; stage held')
    if (execution.load_execution(root)['stages'].get(stage) != current
            or _interrupted_record_bytes(directory / 'record.json') != raw):
        raise ValueError('interrupted attempt changed before negative finalization; stage held')
    pin = {'path': str(snapshot.relative_to(root)),
           'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    current['interrupted_finalization'] = {
        'schema_version': 1, 'kind': 'interrupted-attempt-negative-finalization',
        'preterminal': pin, 'observed_host': observation,
        'descendant_containment': 'not_established', 'requires_recovery': True,
        'scientific_acceptance': False}
    current['cleanup'] = {**current.get('cleanup', {}),
        'process_group': observation['process_group'],
        'signals': current.get('cleanup', {}).get('signals', []), 'recovery_signals': [],
        'census_scope': CLEANUP_CENSUS_SCOPE, 'remaining_group_members': [],
        'group_state': 'empty', 'requires_recovery': True,
        'descendant_containment': 'not_established',
        'note': 'Leader absent and recorded group empty; escaped descendants remain unaccounted for. '
                'Negative finalization preserves the spent attempt and does not grant relaunch authority.'}
    execution.finish_attempt(root, current, 130,
        'interrupted producer absent; failed without scientific acceptance; descendant recovery held')
    _interrupted_recovery_hold(root, current)


def _recover_previous_attempt(root, stage, grace):
    """Fence the old host producer BEFORE the final old guest observation.

    Guest absence while a producer lives is not recovery. Even if host custody
    fails, inspect a known owned guest, then hold without signaling an unrelated
    or unidentified host. Current-input planning occurs only after this barrier.
    """
    prior = execution.load_execution(root)['stages'].get(stage, {})
    if not prior:
        return
    host_error = None
    host_observation = None
    try:
        host_observation = _recover_orphan(root, stage, grace)
    except (Exception, KeyboardInterrupt) as exc:
        host_error = exc
    if (prior.get('container_recovery_plan') and prior.get('status') != 'succeeded'
            and prior.get('child_pid') is None):
        host_error = ValueError('prior container producer has no retained host identity; stage held')
    guest_error = None
    try:
        _recover_container_orphan(root, stage)
    except (Exception, KeyboardInterrupt) as exc:
        guest_error = exc
    if host_error is not None:
        current = execution.load_execution(root)['stages'].get(stage, {})
        if current.get('container_recovery_plan'):
            current['container_producer_fence'] = {
                'requires_recovery': True, 'host_pid': prior.get('child_pid'),
                'error': str(host_error), 'guest_observation_is_only_instantaneous': True}
            # A quiescent instant guest observation cannot resolve a producer.
            if current.get('container_cleanup'):
                current['container_cleanup']['producer_requires_recovery'] = True
                current['container_cleanup']['requires_recovery'] = True
            execution._update(root, stage, current)
        raise ValueError('prior host producer remains unresolved; stage held: ' + str(host_error)) from host_error
    if guest_error is not None:
        raise guest_error
    _negative_finalize_interrupted(root, stage, host_observation)


def _recover_orphan(rundir, stage, grace):
    old = execution.load_execution(rundir)["stages"].get(stage, {})
    if 'interrupted_finalization' in old:
        _interrupted_recovery_hold(Path(rundir), old)
    if not old.get("child_pid"):
        if old.get("status") == "running":
            raise ValueError('previous RUNNING attempt has no recorded child identity; stage held')
        return
    pid = old["child_pid"]
    if old.get("cleanup", {}).get("requires_recovery"):
        # A terminal failed record can still own live descendants. Never turn that
        # status into permission for another launch, or signal a possibly reused PID.
        try:
            members = execution.process_group_members(pid)
        except Exception as exc:
            raise ValueError(f"previous group {pid} cannot be checked; stage {stage} held") from exc
        if members:
            raise ValueError(f"previous group {pid} remains active; stage {stage} held")
        return
    if old.get("status") != "running":
        return
    identity = execution.process_identity(pid)
    if identity is None:
        # An unreadable identity proves nothing while some process holds the pid (ps may have failed or timed
        # out): that process may now lead an unrelated group of this user. A pid no process holds (ESRCH) proves
        # nothing about a group of that id either: after pid reuse a later process can create a group with that
        # id and exit, leaving members that are not this stage's. Without a live leader to compare with the
        # recorded identity nothing is signalled: an active leaderless group holds the stage, its members are
        # recorded for a human, and a resume proceeds only once that group is observed empty.
        try:
            os.kill(pid, 0)   # existence probe only: signal 0 is never delivered
            held = True
        except ProcessLookupError:
            held = False
        except OSError:
            held = True
        if held:
            raise ValueError(f"cannot establish ownership of previous process {pid} (its identity is unreadable); "
                             f"stage {stage} held")
        members = execution.process_group_members(pid)
        if not members:
            return {'leader_pid': pid, 'leader_state': 'absent', 'process_group': pid,
                    'group_state': 'empty', 'remaining_group_members': [],
                    'census_scope': CLEANUP_CENSUS_SCOPE,
                    'descendant_containment': 'not_established'}
        old["cleanup"] = {"process_group": pid, "signals": [], "errors": [],
                          "census_scope": CLEANUP_CENSUS_SCOPE, "remaining_group_members": members,
                          "group_state": "active", "leader_returncode": None, "requires_recovery": True,
                          "note": "the recorded leader is gone, so the group's identity cannot be proven (a later "
                                  "process may have taken its id); nothing was signalled: a human must identify "
                                  "these members"}
        execution.finish_attempt(rundir, old, 130, "leaderless orphan group held for a human (nothing signalled)")
        raise ValueError(f"previous group {pid} has no leader to prove its identity and remains active "
                         f"(members {members}); nothing was signalled; stage {stage} held")
    elif identity != old.get("child_identity") or os.getpgid(pid) != pid:
        raise ValueError(f"cannot establish ownership of previous process {pid}; stage {stage} held")
    try:
        old["cleanup"] = _terminate_owned_group(pid, grace)
    except (Exception, KeyboardInterrupt) as exc:
        old["cleanup"] = {"process_group": pid, "signals": [], "errors": [],
                          "census_scope": CLEANUP_CENSUS_SCOPE,
                          "remaining_group_members": None, "group_state": "unknown",
                          "leader_returncode": None, "requires_recovery": True}
        _cleanup_error(old["cleanup"], "cleanup", exc)
    if old["cleanup"]["requires_recovery"]:
        execution.finish_attempt(rundir, old, 130, "owned orphan cleanup unresolved during resume")
        raise ValueError(f"previous group {pid} cleanup unresolved; stage {stage} held")
    # Only an observed absence of active group members establishes this scoped
    # quiescence. Signal delivery alone does not.
    old.update(status="interrupted", finished_utc=execution.utc_now(),
               error="owned orphan has no active group members after resume cleanup")
    execution._update(rundir, stage, old)


def recover_previous_attempt(rundir, stage, *, grace=GRACE_SECS):
    """Bounded recovery only: never approve, create an attempt or launch a worker."""
    import math
    root = Path(rundir).resolve()
    if not root.is_dir() or not execution.NAME.fullmatch(stage):
        raise ValueError('invalid recovery-only stage/root')
    if type(grace) not in (int, float) or not math.isfinite(grace) or grace <= 0:
        raise ValueError('recovery host grace must be positive and finite')
    # Called while science.run owns science.lock; order is science -> stage ->
    # ledger, matching ordinary launch. Legacy execution retains its own route.
    with file_lock(root / 'logs/execution' / f'{stage}.lock', blocking=False):
        _recover_previous_attempt(root, stage, grace)


def backend_stage(root, stage, cmd, inputs, outputs, backend_plan, *, poll=POLL_SECS, grace=GRACE_SECS):
    """Command, inputs and outputs of a stage that runs through an execution backend.

    The supervised command is the backend worker; the plan file is a pinned input,
    so its digest (image, site, resources) joins the stage fingerprint. Approval,
    authorization and recovery treat it as any other supervised command.
    """
    from . import execution_backend
    plan_path = Path(backend_plan).resolve()
    plan = execution_backend.load_plan(plan_path)
    if plan['spec']['stage'] != stage:
        raise ValueError('backend plan stage differs from the supervised stage name')
    expected = execution_backend.worker_command(root, stage, plan_path, poll=min(poll, POLL_SECS),
                                                cancel_wait=max(1.0, grace - 2.0))
    if cmd and list(cmd) != expected:
        raise ValueError('a backend stage runs the backend worker command; omit the command or pass exactly ' + ' '.join(expected))
    inputs = list(inputs or [])
    if not any(execution.resolve_path(root, value) == plan_path for value in inputs):
        inputs.append(str(plan_path))
    declared = [row['destination'] for row in plan['spec']['outputs'] if 'destination' in row]
    if outputs and sorted(outputs) != sorted(declared):
        raise ValueError('stage outputs must equal the backend plan destinations')
    return expected, inputs, declared


def _local_launch(backend_plan):
    """True unless the stage runs on a remote backend, which takes a remote slot instead.

    Locality comes from the backend adapter, never from the plan's own description.
    """
    if backend_plan is None:
        return True
    from . import execution_backend
    return execution_backend.is_local(execution_backend.load_plan(Path(backend_plan).resolve(), verify_inputs=False))


def lease_wait_seconds(lease_wait, kill_secs):
    """The lease wait bound: explicit, else RAVEL_LEASE_WAIT_SECONDS capped by the stage ceiling."""
    from . import machine_lease
    if lease_wait is not None:
        return lease_wait
    return min(machine_lease.default_wait_seconds(), kill_secs) if kill_secs is not None else machine_lease.default_wait_seconds()


def _stage_binding(root, stage, *, required_plan, authorization_plan, scoped_likelihood, science_review):
    """The approved stage this launch takes the machine lease for, or None (no approval route holds).

    In the machine lock domain a launch without one gets no lease and does not start.
    """
    from . import execution_backend, physics_review
    if science_review or physics_review._science_run(root):
        route, rung = 'science', None
    elif scoped_likelihood:
        route, rung = 'scoped-likelihood', None
    elif authorization_plan is not None or (root / "inputs/native_execution_plan.json").is_file():
        route, rung = 'native-plan', None
    elif required_plan is not None:
        route, rung = 'checkin1', required_plan
    elif physics_review.active(root) and (root / "inputs/checkin1_approval.json").is_file():
        route, rung = 'checkin1', execution.read_json(root / "inputs/checkin1_approval.json").get("approved_plan")
    else:
        return None
    try:
        return execution_backend.approved_binding(root, stage, route, rung)
    except (OSError, ValueError, KeyError) as exc:
        print(f"stage {stage}: no approved stage binding for the machine lease ({exc})", file=sys.stderr, flush=True)
        return None


def _machine_lease(root, stage, backend_plan, lease_wait, *, nested=False, binding=None):
    """Hold the machine lease for one local launch, waiting for an earlier holder."""
    from contextlib import nullcontext
    from . import machine_lease
    if not _local_launch(backend_plan):
        return nullcontext()
    def waiting(record):
        held = f" ({record.get('holder')}, since {record.get('since_utc')})" if isinstance(record, dict) else ''
        print(f"stage {stage}: waiting for the machine lease held by another native job{held}; "
              f"waiting up to {lease_wait:g} s", file=sys.stderr, flush=True)
    return machine_lease.held(f'{root}:{stage}', rundir=str(root), node_id=stage, nested=nested,
                              binding=None if nested else binding, wait_seconds=lease_wait, on_wait=waiting)


def _cancel_backend_job(root, record, grace):
    """After the worker group is gone, cancel this attempt's backend job if it has not ended."""
    from . import execution_backend as eb
    directory = eb.attempt_backend_dir(root, record['stage'], record['attempt_id'])
    if not (directory / eb.HANDLE_NAME).is_file():
        return None
    handle = eb.read_handle(directory)
    if eb.handle_resolved(handle):
        return None
    plan = eb.load_plan(directory / 'plan.json', verify_inputs=False)
    if handle.get('remote') is None:
        eb.recover(plan, handle)
        if handle.get('remote') is None:
            return {'state': 'unknown', 'tag': handle['tag'], 'requires_recovery': not eb.handle_resolved(handle)}
    observation = eb.cancel(plan, handle, wait_seconds=max(1.0, grace))
    return {'state': observation['state'], 'tag': handle['tag'], 'requires_recovery': not eb.handle_resolved(handle)}


def _authorized_branch(root, required_plan, authorization_plan, scoped_likelihood):
    """True when the launch below goes through launch authorization rather than a plain Popen."""
    from . import physics_review, science
    if scoped_likelihood or required_plan is not None or authorization_plan is not None:
        return True
    if (root / "inputs/native_execution_plan.json").is_file():
        return True
    if physics_review._science_run(root):
        return True
    return physics_review.active(root)


def _research_child_study(root):
    """A derived task contract keeps the scientific-study route only for its authenticated campaign child.

    Any other contracted run still declares an explicit compute rung. A forged or stale
    campaign origin raises here, before anything is started.
    """
    from . import physics_review, research_cycle
    if not (physics_review._science_run(root) and (root / research_cycle.CHILD_CONTRACT_ORIGIN).exists()):
        return False
    research_cycle.verify_experiment_contract(root)
    return True


def _controller_run(root):
    """The run id when ``root`` lies in a run the controller owns, else None."""
    from ravel.controller.confine import runs
    found = runs.owner_of(Path(root))
    return found[0] if found else None


def _controller_check(root, action='stage dispatch'):
    from ravel.controller import authority
    from ravel.controller.confine import runs
    found = runs.owner_of(root)
    return authority.check(runs.store(found[0]), action) if found else None


def _controller_drain(root, record, proc):
    """A request triggers observation; it is never itself evidence of termination."""
    from ravel.controller import authority
    from ravel.controller.confine import runs
    found = runs.owner_of(root)
    if not found or proc is None:
        return False
    store = runs.store(found[0])
    view = authority.control(store)  # includes authenticated ancestor controls
    if view['state'] == 'running':
        return False
    if 'controller_stop' not in record:
        members = execution.process_group_members(proc.pid)
        record['controller_stop'] = view
        authority.observe_stop(store, 'draining', {'stage': record['stage'], 'process_group': proc.pid,
            'remaining_group_members': members, 'verified_gone': False})
    return True


def _controller_stopped(root, record, proc):
    if not record.get('controller_stop') or proc is None:
        return
    cleanup = record.get('cleanup')
    if not cleanup or cleanup.get('requires_recovery'):
        return
    _observe_group(cleanup, proc=proc)
    if cleanup['requires_recovery'] or proc.poll() is None:
        return
    for key in ('registered_helper_cleanup', 'operation_extra_group_cleanup'):
        values = record.get(key) or []
        if isinstance(values, dict) or any(v.get('requires_recovery') for v in values):
            return
    for key in ('backend_cancel', 'container_cleanup', 'confinement_finish'):
        value = record.get(key) or {}
        if value.get('requires_recovery') or value.get('errors'):
            return
        if key == 'backend_cancel' and value and value.get('state') not in ('succeeded', 'failed', 'cancelled'):
            return
    # A stage cannot certify a whole run stopped while another recorded producer is running.
    if any(v.get('status') == 'running' for k, v in execution.load_execution(root)['stages'].items()
           if k != record['stage']):
        return
    from . import execution_backend as backend, machine_lease
    for path in backend.stage_handles(root):
        handle = execution.read_json(path)
        if (not backend.handle_resolved(handle) or handle.get('resolution') == 'operator-cleared'
                and handle.get('state') not in (*backend.TERMINAL, 'fetched')):
            return  # Clearing a capacity fence is not observation of remote termination.
    reservation = record.get('reservation')
    if reservation and machine_lease.job_processes(reservation):
        return
    from ravel.controller import authority
    from ravel.controller.confine import runs
    authority.observe_stop(runs.store(_controller_run(root)), 'stopped', {
        'stage': record['stage'], 'process_group': proc.pid, 'remaining_group_members': [],
        'reaped_descendants': cleanup.get('reaped_descendants', []), 'verified_gone': True})


def _controller_launch(root, stage, cmd, context, cwd, *, legacy_science):
    """How a stage of a controller-owned run starts, decided before anything is reserved.

    A registered controller-side entry point (a RAVEL broker whose payloads are confined where
    they start) keeps the controller's environment; every other command gets a confined launch
    plan. A version-one study does not run in a controller-owned run.
    """
    from ravel.controller import confine
    if legacy_science:
        raise confine.ConfinementRefused('a version-one scientific study does not run in a controller-owned run; '
                                         'nothing was started')
    broker = confine.entry_point(root, cmd)
    if broker is not None:
        return broker
    return confine.prepare(confine.spec_for_stage(root, cmd, context=context, cwd=cwd))



def _controller_launch_context(context, specification, kill_secs, operation_resources=None):
    """Carry actual committed stage facts into the controller launch, without inventing limits."""
    runtime = {name: value for name, value in execution.runtime_environment().items()
               if isinstance(value, str)}
    context.update(environment_capsule=runtime, input_snapshot=specification['input_snapshot'],
                   max_seconds=kill_secs)
    declared = operation_resources if isinstance(operation_resources, dict) else {}
    limits = {name: declared[name] for name in ('cpus', 'memory_mib', 'wall_seconds') if name in declared}
    if 'cpus' not in limits:
        threads = runtime.get('OMP_NUM_THREADS')
        if threads and threads.isdecimal() and int(threads) > 0:
            limits['cpus'] = int(threads)
    if limits:
        context['limits'] = limits
    return context


def _refresh_controller_grant(launch):
    """Rebind CPU affinity to the grant held after lease acquisition, before any attempt."""
    from ravel.controller import confine
    if isinstance(launch, confine.Plan) and 'cpus' in launch.limits:
        grant = confine.machine_grant()
        cpus = launch.limits['cpus']
        if cpus > len(grant):
            raise confine.ConfinementRefused(
                f'the launch asks for {cpus} CPUs; the acquired machine grant has {len(grant)}')
        launch.limits['cpu_set'] = grant[:cpus]


def _approved_plan_location(root, backend_plan):
    """Backend plans that CHECK-IN 1 approval binds (workflow_state.approval_input_paths)."""
    path = Path(backend_plan).resolve()
    return path == root / "inputs/backend-plan.json" or (
        path.parent == root / "inputs/backend-plans" and path.suffix == ".json")


def supervise(stage, rundir, events, logrel, cmd=None, kill_secs=None, stall_secs=None,
              poll=POLL_SECS, grace=GRACE_SECS, *, inputs=None, outputs=None,
              depends_on=None, resume=False, cwd=None, authorization_plan=None, required_plan=None, output_policy=None, helper_declaration=None, operation_resources=None,
              backend_plan=None, lease_wait=None, nested_under=None, node_id=None, science_rung=None, _engineering_only=False):
    """Run one declared stage; resume only a content-identical successful attempt.

    Log silence is not a default failure signal. A caller may supply stall_secs only
    for tools with a documented live progress stream. Scientific postconditions use
    explicit output artifacts; legacy callers retain the empty-producing-log check.
    backend_plan names an execution-backend plan; the stage then runs through
    that backend (see ravel.workflow.execution_backend).
    Every local launch holds the machine lease for its lifetime and waits up to
    lease_wait seconds (default RAVEL_LEASE_WAIT_SECONDS, one day) for an earlier
    holder; a remote backend plan takes a remote slot in its worker instead.
    A backend plan launches only with an approval: the run's own CHECK-IN 1
    authorization, or ``nested_under=(rundir, stage)`` naming the approved stage
    whose proven worker drives this stage (its lease is then nested in that job's).
    Steering decides on the plan node that owns the stage: the node the plan binds to the
    stage name. ``node_id`` is the node a production launch names; it must agree with the plan.
    """
    root = Path(rundir).resolve()
    _controller_check(root)
    from . import method_selection, physics_review, wms_policy
    # Every approval route is governed; only a stage with no approval route is outside this check.
    if physics_review._science_run(root) or _authorized_branch(
            root, required_plan, authorization_plan, (root / 'inputs/scoped-plan.json').exists()):
        wms_policy.require_dispatch(root)
    controller_run = _controller_run(root)
    if _engineering_only and controller_run is not None:
        raise ValueError('engineering-only dispatch is unavailable for a controller-owned run; nothing was started')
    if _engineering_only:
        from .approval_authority import AGENT_MARKERS
        inert_selftest = _engineering_only is _ENGINEERING_SELFTEST and tuple(cmd or ()) in _ENGINEERING_SELFTEST_COMMANDS
        if ((any(name in os.environ for name in AGENT_MARKERS) and not inert_selftest) or required_plan is not None
                or authorization_plan is not None or backend_plan is not None or nested_under is not None
                or operation_resources is not None or events != 0 or physics_review.active(root)
                or any((root / p).exists() for p in ('inputs/task_contract.json', 'task_contract.json',
                    'inputs/science.json', 'inputs/scoped-plan.json', 'inputs/native_execution_plan.json'))):
            raise ValueError('engineering-only dispatch cannot carry scientific authority or an agent session')
    elif not _authorized_branch(root, required_plan, authorization_plan, (root / 'inputs/scoped-plan.json').is_file()) and nested_under is None:
        raise ValueError('unchecked scientific dispatch refused; declare its compute rung and approval. '
                         'The separate engineering-only path is unavailable to scientific agent dispatch.')
    if not _engineering_only:
        method_selection.require_launch(root, required_plan)
        if authorization_plan is not None:
            method_selection.require_launch(root, authorization_plan.get('compute_plan'))
        if nested_under is not None:
            method_selection.require_launch(nested_under[0])
    if backend_plan is not None:
        if not execution.NAME.fullmatch(stage):
            raise ValueError("invalid stage name")
        cmd, inputs, outputs = backend_stage(root, stage, cmd, inputs, outputs, backend_plan, poll=poll, grace=grace)
    if not cmd:
        raise ValueError("stage command required")
    scoped_path = root / 'inputs/scoped-plan.json'
    scoped_likelihood = scoped_path.exists() and execution.read_json(scoped_path).get('mode') == 'likelihood'
    if scoped_likelihood:
        method_selection.require_launch(root, 'full')
    if scoped_likelihood and (authorization_plan is not None or required_plan not in (None, 'full')):
        raise ValueError('scoped likelihood requires its actual full CHECK-IN 1 envelope')
    if operation_resources is not None:
        from . import operation_resources as resources
        if required_plan != "full" or authorization_plan is not None or scoped_likelihood or kill_secs is None:
            raise ValueError("solver resources require an explicit ordinary full stage and time ceiling")
        resources.binding(root, operation_resources, stage=stage, command=cmd, cwd=cwd or os.getcwd(),
                          inputs=inputs or [], outputs=outputs or [], events=events, max_seconds=kill_secs)
    budget_min = stage_budget_min(stage, events)
    if required_plan is not None:
        if required_plan not in ("smoke", "full", "scan"):
            raise ValueError("generic checked stage needs smoke, full or scan compute rung")
        if (type(events) is not int or (events <= 0 and not scoped_likelihood and operation_resources is None)
                or (required_plan == "smoke" and events > 1000)):
            raise ValueError("generic checked stage event count exceeds its declared compute rung")
    if kill_secs is None:
        kill_secs = max(FLOOR_SECS, budget_min * KILL_MARGIN * 60.0)
    import math
    for name, value in (("kill_secs", kill_secs), ("poll", poll), ("grace", grace),
                        ("stall_secs", stall_secs)):
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value <= 0):
            raise ValueError(f"{name} must be positive and finite")
    if not root.is_dir():
        raise ValueError("run directory does not exist")
    parent_authority = None
    if nested_under is not None:
        from . import execution_backend
        parent_authority = execution_backend.require_approved_stage(*nested_under)
        method_selection.require_launch(parent_authority['rundir'], parent_authority.get('required_plan'))
    if backend_plan is not None and parent_authority is None and not _authorized_branch(
            root, required_plan, authorization_plan, scoped_likelihood):
        raise ValueError("a backend stage launches only inside an approved run (CHECK-IN 1 and a compute rung) "
                         "or nested under an approved stage's worker; nothing was started")
    if backend_plan is not None and parent_authority is None and not _approved_plan_location(root, backend_plan):
        raise ValueError(f"backend plan {backend_plan} is not an approved input: pin it as inputs/backend-plan.json "
                         "or under inputs/backend-plans/ before CHECK-IN 1 approval; nothing was started")
    approved_science_rung = False
    if science_rung is not None:
        from . import science
        from ravel.controller.routes.study.child_contract import compute_rung, ComputeRungUnavailable
        if (stage != 'science' or events != 0 or not physics_review._science_run(root) or not science.review_enabled(root)
                or required_plan is not None or authorization_plan is not None or scoped_likelihood
                or compute_rung(root, max_seconds=kill_secs) != science_rung):
            raise ComputeRungUnavailable('scientific stage differs from its approved ordinary compute rung')
        approved_science_rung = True
    if (required_plan is None and authorization_plan is None
            and (root / "inputs/task_contract.json").exists()
            and not (root / "inputs/native_execution_plan.json").exists() and not scoped_likelihood
            and not _research_child_study(root) and not approved_science_rung):
        raise ValueError("a contracted generic stage requires an explicit compute rung (--required-plan smoke|full|scan)")
    if not execution.NAME.fullmatch(stage):
        raise ValueError("invalid stage name")
    logpath = execution.log_path(root, logrel)
    logpath.parent.mkdir(parents=True, exist_ok=True)
    from contextlib import ExitStack
    with file_lock(root / "logs/execution" / f"{stage}.lock", blocking=False), ExitStack() as lease_scope:
        if controller_run is not None:
            lease_scope.enter_context(_child_reaper())
        if output_policy is not None:
            from . import physics_review, science
            if not physics_review._science_run(root) or not science.review_enabled(root):
                raise ValueError('explicit output policy requires a prospective version 2 scientific study')
            execution.validate_output_policy(root, outputs or [], output_policy, execution.resolve_path)
        _recover_previous_attempt(root, stage, grace)
        specification = execution.plan_stage(root, stage, list(cmd), inputs or [], outputs or [],
                                             depends_on or [], cwd or os.getcwd(),
                                             **({'output_policy': output_policy} if output_policy is not None else {}),
                                             **({'helper_declaration': helper_declaration} if helper_declaration is not None else {}),
                                             **({'operation_resources': operation_resources} if operation_resources is not None else {}))
        from . import review_enforcement, physics_review
        from . import science
        science_review = physics_review._science_run(root) and science.review_enabled(root)
        legacy_science = physics_review._science_run(root) and not science_review
        if legacy_science:
            proposal = science.verify_plan(root, approved=True)
            declared = proposal['stages'][0]
            if (stage != declared['stage'] or list(cmd) != declared['command']
                    or specification['cwd'] != declared['cwd']
                    or specification['inputs'] != proposal['stage_binding']['inputs']
                    or specification['outputs'] != declared['outputs']
                    or specification['parents'] != proposal['stage_binding']['parents']
                    or kill_secs != proposal['max_seconds'] or events != 0):
                raise ValueError('legacy scientific dispatch must match its approved stage recipe and ceiling')
        if science_review and (authorization_plan is not None or required_plan is not None):
            raise ValueError("scientific study cannot borrow a native compute authorization")
        if science_review and scoped_likelihood:
            raise ValueError('scientific study cannot borrow a scoped likelihood envelope')
        if scoped_likelihood:
            from . import scoped
            scoped.verify_supervised_stage(root, stage, list(cmd), specification['inputs'], specification['outputs'],
                list(specification['parents']), specification['cwd'], logrel, kill_secs, events, resume=resume)
        correction_id = review_enforcement.before_stage(root, stage, list(cmd), specification["inputs"],
            specification["outputs"], list(specification["parents"]), specification["cwd"], logrel, resume=resume, **execution.helper_declaration_fields(specification))
        if correction_id is None and resume and execution.reusable(root, stage, specification):
            print(f"REUSED {stage}: inputs, dependencies and outputs verified", flush=True)
            return 0
        if resume and correction_id is None:
            review_enforcement.before_stage(root, stage, list(cmd), specification["inputs"],
                specification["outputs"], list(specification["parents"]), specification["cwd"], logrel, resume=False, **execution.helper_declaration_fields(specification))
        from . import gate_wiring
        # The launch context carries the plan node that owns this stage; a stage the plan gives
        # no single owner keeps its own name and holds conservatively under steering.
        plan_node = gate_wiring.launch_node(root, stage, declared=node_id)
        review_context = {"stage": stage, "node_id": plan_node or stage, "review_action": "correction" if correction_id else "bulk",
            "stage_spec": {"stage": stage, "command": list(cmd), "cwd": specification["cwd"], "log": str(logpath),
                "inputs": sorted(str(execution.resolve_path(root, p)) for p in specification["inputs"]),
                "outputs": sorted(str(execution.resolve_path(root, p, output=True)) for p in specification["outputs"]),
                "depends_on": list(specification["parents"]), **execution.output_policy_fields(specification), **execution.helper_declaration_fields(specification), **execution.operation_resource_fields(specification)}}
        if science_review:
            review_context["max_seconds"] = kill_secs
            review_context["plan_sha256"] = execution.file_hash(root / science.PLAN)
            errors = science.verify_launch(root, stage, cmd, review_context)
            if errors:
                raise ValueError("scientific launch refused: " + "; ".join(errors))
        elif scoped_likelihood:
            review_context.update(max_seconds=kill_secs, events=events,
                                  plan_sha256=execution.file_hash(root / scoped.PLAN))
        operation_authority = None
        if operation_resources is not None:
            operation_authority = resources.authority(root, operation_resources, stage=stage, command=cmd,
                cwd=specification["cwd"], inputs=specification["inputs"], outputs=specification["outputs"], events=events, max_seconds=kill_secs)
            review_context.update(events=events, max_seconds=kill_secs, operation_authority=operation_authority)
        if controller_run is not None:
            _controller_launch_context(review_context, specification, kill_secs, operation_resources)
        controller_launch = (_controller_launch(root, stage, cmd, review_context, specification['cwd'],
                                                legacy_science=legacy_science)
                             if controller_run is not None else None)
        binding = None if parent_authority is not None else _stage_binding(
            root, stage, required_plan=required_plan, authorization_plan=authorization_plan,
            scoped_likelihood=scoped_likelihood, science_review=science_review)
        lease = lease_scope.enter_context(_machine_lease(root, stage, backend_plan,
                                                         lease_wait_seconds(lease_wait, kill_secs),
                                                         nested=parent_authority is not None, binding=binding))
        if controller_launch is not None:
            _refresh_controller_grant(controller_launch)
        record = execution.begin_attempt(root, stage, specification, logrel)
        if controller_launch is not None:
            # The custody digest is in the attempt record before the child can look for it.
            from ravel.controller import confine
            if isinstance(controller_launch, confine.Plan):
                controller_launch.attempt_dir = root / "logs/execution" / stage / record["attempt_id"]
                record["confinement"] = controller_launch.record
            else:
                record["confinement"] = controller_launch
            execution._update(root, stage, record)
        if lease is not None:
            from . import machine_lease
            allocation = machine_lease.allocation_identity()
            if allocation is not None:
                # The host or Slurm allocation whose lease this attempt ran under.
                record["allocation"] = allocation
        if parent_authority is not None:
            record["parent_authority"] = parent_authority
        if operation_authority is not None:
            record["operation_authority"] = operation_authority
        t0 = time.monotonic()
        proc = None
        steering_root = root  # the run whose steering decides this launch and holds its process record
        helper_owner = None
        operation_owner = None
        launch_env = None
        job_token = None
        reason = None
        code = 2
        previous_handlers = {}
        def interrupted(signum, frame):
            raise KeyboardInterrupt(f"signal {signum}")
        try:
            # Native pipeline commands run in the main thread. Library callers in another
            # thread still receive timeout/exception cleanup without process-global handlers.
            import threading
            if threading.current_thread() is threading.main_thread():
                for sig in (signal.SIGTERM, signal.SIGINT):
                    previous_handlers[sig] = signal.signal(sig, interrupted)
            if science_review:
                _prepare_container_recovery(root, stage, specification, record, kill_secs, CONTAINER_CLEANUP_SECS)
            worker_limit = (
                _container_snapshot(root, record)["worker_seconds"]
                if record.get("container_recovery_plan") else kill_secs)
            if science_review:
                actual_spec=science.execution_spec(root)
                hook=getattr(science.adapter(actual_spec),'owner_limits',None)
                if hook is not None:
                    actual_plan=execution.read_json(root/science.PLAN)
                    operation_owner=_OperationOwner(hook(actual_spec['task'],actual_plan['base_dir']),t0,worker_limit)
                    worker_limit=min(worker_limit,operation_owner.limits['max_seconds'])
                    record['operation_supervision']=operation_owner.report()
            if helper_declaration is not None:
                from . import helper_registration
                helper_owner=helper_registration.HelperOwner(helper_declaration,
                    root/"logs/execution"/stage/record["attempt_id"]/"helper-registration",
                    deadline=t0+worker_limit)
                launch_env=os.environ.copy();launch_env[helper_registration.ENV]=helper_owner.descriptor_pin["path"]
                if controller_launch is not None and not isinstance(controller_launch, dict):
                    controller_launch.channels.append(Path(helper_owner.socket_path))
                    controller_launch.record["channels"] = [str(c) for c in controller_launch.channels]
                record["helper_owner_descriptor"]=helper_owner.descriptor_pin
                execution._update(root,stage,record)
            launch_kwargs={"env":launch_env} if helper_owner is not None else {}
            with logpath.open("wb") as log:
                if lease is not None:
                    # The fence exists before the child does: the log is the job's hold (the child and
                    # every descendant inherit it as their output) and the child carries the job token.
                    from . import machine_lease
                    machine_lease.take_hold(log)
                    job_token = machine_lease.reserve(lease.lease_id, hold=logpath,
                                                      label=f'{root}:{stage} supervised stage')
                    record['reservation'] = {'token': job_token, 'lease_id': lease.lease_id, 'hold': str(logpath)}
                    execution._update(root, stage, record)
                    launch_env = launch_env if launch_env is not None else os.environ.copy()
                    launch_env[machine_lease.JOB_ENV] = job_token
                    launch_kwargs = {"env": launch_env}
                if controller_launch is not None and not isinstance(controller_launch, dict):
                    # Late channel variables (helper owner, job token) of this attempt join the capsule.
                    from ravel.controller.confine import environment as confine_environment
                    controller_launch.env.update({name: value for name, value in (launch_env or {}).items()
                                                  if name in confine_environment.channels()})
                # A run the controller does not own keeps the legacy launch call unchanged.
                confined_kwargs = {"confinement": controller_launch} if controller_launch is not None else {}
                if authorization_plan is None and (root / "inputs/native_execution_plan.json").is_file():
                    from ravel.physics.native_pipeline import load_plan
                    authorization_plan = load_plan(root / "inputs/native_execution_plan.json")
                if not _engineering_only:
                    method_selection.require_launch(root, required_plan)
                    if parent_authority is not None:
                        method_selection.require_launch(parent_authority['rundir'], parent_authority.get('required_plan'))
                _controller_check(root, 'stage dispatch before process creation')
                if science_review:
                    from .launch_authorization import authorized_popen
                    proc = authorized_popen(root, "science", cmd, context={"kind": "science-stage", **review_context},
                        stdout=log, stderr=subprocess.STDOUT, cwd=cwd, start_new_session=True,
                        **confined_kwargs, **launch_kwargs)
                    record["authorization_receipt"] = proc.ravel_authorization
                elif scoped_likelihood:
                    from .launch_authorization import authorized_popen
                    proc = authorized_popen(root, 'full', cmd, context={'kind': 'scoped-likelihood-stage', **review_context},
                        stdout=log, stderr=subprocess.STDOUT, cwd=cwd, start_new_session=True,
                        **confined_kwargs, **launch_kwargs)
                    record['authorization_receipt'] = proc.ravel_authorization
                elif legacy_science or _engineering_only or (
                        parent_authority is not None and authorization_plan is None and required_plan is None
                        and not physics_review.active(root)):
                    # Three direct launches remain, each checked above. The version-one study has its
                    # own exact byte-bound plan, verified here immediately before dispatch; it cannot
                    # use the engineering fallback or a generic command. A backend stage nested under a
                    # verified approved stage carries that stage's authority and method admission; its
                    # store has no CHECK-IN of its own. Steering is consulted for every one of them.
                    if legacy_science:
                        science.verify_plan(root, approved=True)
                    # A nested backend stage's store has no steering of its own: the run and stage
                    # that own it (its verified parent authority) decide and hold its process record.
                    steering_root, steering_node = (root, review_context["node_id"]) if parent_authority is None else (
                        Path(parent_authority['rundir']),
                        gate_wiring.launch_node(parent_authority['rundir'], parent_authority['stage']) or parent_authority['stage'])
                    with gate_wiring.steering_dispatch(steering_root, steering_node):
                        if controller_launch is None:
                            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                                    cwd=cwd, start_new_session=True, **launch_kwargs)
                        elif isinstance(controller_launch, dict):
                            from ravel.controller.confine import brokers
                            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=cwd,
                                                    start_new_session=True,
                                                    env=brokers.environment(launch_kwargs.get('env')))
                        else:
                            from ravel.controller import confine
                            proc = confine.start(controller_launch, subprocess.Popen, stdout=log,
                                                 stderr=subprocess.STDOUT, cwd=cwd, start_new_session=True)
                        gate_wiring.register_steering_process(steering_root, proc, review_context)
                elif authorization_plan is None:
                    from .launch_authorization import authorized_popen
                    approved = required_plan or execution.read_json(root / "inputs/checkin1_approval.json")["approved_plan"]
                    # The approved volume and ceiling travel with the launch, so a compute driver
                    # inside the stage (partitions run) can be held to them.
                    review_context.setdefault("events", events)
                    review_context.setdefault("max_seconds", kill_secs)
                    proc = authorized_popen(root, approved, cmd, context={"kind": "scientific-stage", **review_context},
                        stdout=log, stderr=subprocess.STDOUT, cwd=cwd, start_new_session=True,
                        **confined_kwargs, **launch_kwargs)
                    record["authorization_receipt"] = proc.ravel_authorization
                else:
                    from ravel.physics.native_pipeline import verify_execution_approval
                    verify_execution_approval(authorization_plan)
                    declared = next((s for s in authorization_plan["stages"] if s["stage"] == stage), None)
                    if declared is None or list(cmd) != declared["command"] or events != authorization_plan["nevents"]:
                        raise ValueError("supervised command or event scope differs from the approved native stage")
                    from .launch_authorization import authorized_popen
                    proc = authorized_popen(root, authorization_plan["required_compute_plan"], cmd,
                                            context={"kind": "native-stage", **review_context,
                                                     "max_seconds": kill_secs, "events": events,
                                                     "plan_sha256": authorization_plan["plan_sha256"]},
                                            stdout=log, stderr=subprocess.STDOUT, cwd=cwd, start_new_session=True,
                                            **confined_kwargs, **launch_kwargs)
                    record["authorization_receipt"] = proc.ravel_authorization
                if operation_owner is not None:
                    # Publish owner/worker identity once, before registration
                    # wakes the worker's exact-ledger source admission.
                    operation_owner.attach(proc,execution.process_identity(proc.pid))
                    record['operation_supervision']=operation_owner.report()
                if lease is not None:
                    # Completes the reservation with the stage's group (the hold already fences it).
                    machine_lease.fence(lease.lease_id, proc.pid, label=f'{root}:{stage} supervised stage',
                                        token=job_token)
                execution.record_process(root, record, proc.pid)
                if helper_owner is not None:helper_owner.attach_worker(proc.pid)
                while proc.poll() is None:
                    if controller_run is not None and _controller_drain(root, record, proc):
                        reason = 'controller-' + record['controller_stop']['state']
                        break
                    if helper_owner is not None:helper_owner.service()
                    if operation_owner is not None:operation_owner.sample()
                    elapsed = time.monotonic() - t0
                    if elapsed > worker_limit:
                        reason = "wall-clock"
                    elif stall_secs is not None and time.time() - logpath.stat().st_mtime > stall_secs:
                        reason = "progress-stall"
                    if reason:
                        code = 124
                        break
                    delay=.025 if helper_owner is not None else poll
                    if operation_owner is not None:
                        delay=min(delay,.1,max(0.,operation_owner.clock['deadline_monotonic']-time.monotonic()))
                    time.sleep(delay)
            if controller_run is not None and _controller_drain(root, record, proc):
                reason = reason or 'controller-' + record['controller_stop']['state']
            code = (130 if record.get('controller_stop') else 124) if reason else (
                proc.returncode if proc.returncode >= 0 else 128 - proc.returncode)
            if code and not reason:
                reason = f"exit-{code}"
            if code == 0 and execution.process_group_members(proc.pid):
                code, reason = 3, "descendants remained active after the stage leader exited"
            if code == 0 and job_token is not None:
                from . import machine_lease
                ties = machine_lease.job_processes({'hold': str(logpath), 'token': job_token})
                if ties:
                    code, reason = 3, ("a descendant outside the stage's process group remained active "
                                       f"(it holds {', '.join(sorted(ties))}); the machine stays fenced until it ends")
            if code == 0 and not outputs and stage in MUST_PRODUCE and logpath.stat().st_size == 0:
                code, reason = 3, "exit-0-implausible"
            if operation_owner is not None:operation_owner.sample()
        except KeyboardInterrupt:
            if not reason:
                code, reason = 130, "interrupted"
        except Exception as exc:
            if not reason:
                code, reason = 2, str(exc)
            if proc is None and getattr(exc, 'launch_refused', False):
                # Steering refused at the serialized launch boundary: no process of this attempt
                # exists, so a caller may treat its reserved attempt as unspent.
                record["prelaunch_refusal"] = {"by": getattr(exc, "refused_by", "steering"), "reason": str(exc)}
        finally:
            if controller_run is not None and proc is not None:
                try:
                    _controller_drain(root, record, proc)
                except (OSError, ValueError) as exc:
                    record['controller_observation_error'] = str(exc)
            if job_token is not None and proc is None:
                # Authorization or Popen failed after the reservation: nothing started and the hold
                # closed with the log, so this live supervisor must not keep the machine reserved.
                try:
                    from . import machine_lease
                    record["reservation_released"] = machine_lease.unreserve(job_token)
                except (Exception, KeyboardInterrupt) as exc:
                    record["reservation_released"] = {"requires_recovery": True, "error": str(exc)}
            if operation_owner is not None:
                record['operation_supervision']=operation_owner.report()
                try:
                    record['operation_extra_group_cleanup']=operation_owner.close_extra_groups(grace)
                    if any(r['requires_recovery'] or r.get('had_active_members') for r in record['operation_extra_group_cleanup']) and not code:
                        code,reason=3,'operation descendant ownership/cleanup unresolved'
                except Exception as exc:
                    record['operation_extra_group_cleanup']={'requires_recovery':True,'error':str(exc)}
                    if not code:code,reason=3,'operation descendant cleanup failed'
            # Always clean acknowledged detached sessions, including nominal worker exit.
            if helper_owner is not None:
                try:
                    record["registered_helper_cleanup"]=helper_owner.close()
                    record["registered_helper_errors"]=helper_owner.errors
                    record["registered_helper_kernel_calls"]=helper_owner.observer.calls
                    if any(r["requires_recovery"] for r in record["registered_helper_cleanup"]) or helper_owner.errors:
                        if not code:code,reason=3,"registered helper ownership/cleanup unresolved"
                except BaseException as exc:
                    record["registered_helper_cleanup"]={"requires_recovery":True,"error":str(exc)}
                    if not code:code,reason=3,"registered helper cleanup failed"
            if proc is not None and code:
                if helper_owner is None:
                    record["cleanup"] = _safe_cleanup(proc, grace)
                else:
                    record["cleanup"] = helper_owner.cleanup_worker(proc)
                    record["registered_helper_kernel_calls"]=helper_owner.observer.calls
                if backend_plan is not None:
                    try:
                        record["backend_cancel"] = _cancel_backend_job(root, record, grace)
                    except (Exception, KeyboardInterrupt) as exc:
                        record["backend_cancel"] = {"requires_recovery": True, "error": str(exc)}
            if proc is not None and getattr(proc, "ravel_confinement", None) is not None:
                # After the process is gone and before the outputs are snapshotted: adopt the declared
                # outputs, quarantine every other file the stage created, remove its scratch.
                try:
                    from ravel.controller import confine
                    record["confinement_finish"] = confine.finish(proc)
                    if record["confinement_finish"].get("errors") and not code:
                        code, reason = 3, "confined outputs could not be adopted or quarantined"
                except (Exception, KeyboardInterrupt) as exc:
                    record["confinement_finish"] = {"requires_recovery": True, "error": str(exc)}
                    if not code:
                        code, reason = 3, "confined launch could not be finished"
            if record.get("container_recovery_plan"):
                try:
                    observed = _recover_container(root, record, "final")
                except (Exception, KeyboardInterrupt) as exc:
                    observed = {"requires_recovery": True, "error": str(exc)}
                    record["container_cleanup"] = observed
                if observed["requires_recovery"] and not code:
                    code, reason = 3, "owned container cleanup unresolved"
            if proc is not None:
                try:
                    from . import gate_wiring
                    gate_wiring.observe_steering_process(steering_root, proc)
                except (OSError, ValueError) as exc:
                    record['steering_observation_error'] = str(exc)
            if controller_run is not None and not record.get('controller_observation_error'):
                try:
                    _controller_stopped(root, record, proc)
                except (OSError, ValueError) as exc:
                    record['controller_observation_error'] = str(exc)
            for sig, handler in previous_handlers.items():
                try:
                    signal.signal(sig, handler)
                except (Exception, KeyboardInterrupt) as exc:
                    record.setdefault("supervision_errors", []).append(str(exc))
                    if not code:
                        code, reason = 2, "could not restore supervisor signal handlers"
        def ending_operation_check():
            operation_owner.sample();record['operation_supervision']=operation_owner.report()
        code = execution.finish_attempt(root, record, code, reason,
            **({'ending_check':ending_operation_check} if operation_owner is not None else {}))
        if code:
            review_enforcement.finish_correction_failure(root, correction_id, record.get("error") or f"exit-{code}")
            write_failure(str(root), stage, record.get("error") or f"exit-{code}",
                          time.monotonic() - t0, kill_secs, cmd, logrel,
                          cleanup={"host": record.get("cleanup"), "container": record["container_cleanup"]}
                          if record.get("container_recovery_plan") else record.get("cleanup"))
        else:
            # Successful supervision, not a bare library finish, owns the
            # immutable receipt registration consumed by decision anchors.
            from . import rdj_custody
            if not rdj_custody.stage_receipt_registered(root, stage, record['attempt_id'], record):
                rdj_custody.register_stage_receipt(root, stage, record['attempt_id'])
            failure = root / "logs" / f"{stage}.failure.json"
            if failure.exists():
                # Preserve the original failed receipt, then record how it was resolved.
                old = execution.read_json(failure)
                old.update(status="resolved", resolved_by_attempt=record["attempt_id"],
                           resolved_utc=execution.utc_now())
                atomic_json(failure, old)
        return code

def selftest():
    import tempfile
    from . import machine_lease
    fails = []
    with tempfile.TemporaryDirectory() as domain, tempfile.TemporaryDirectory() as td:
        # The selftest's plain stages run in a private test lock domain this process selects, never
        # the machine's; a child it starts gets the domain only through this process's grant.
        (Path(domain) / machine_lease.TEST_MARKER).write_text("stage supervisor selftest\n")
        grants = machine_lease.test_domain_grants()
        previous = grants.enter(os.path.realpath(domain))
        try:
            return _selftest_cases(td, fails)
        finally:
            machine_lease.leave_test_domain(previous)


def _selftest_cases(td, fails):
    if True:
        os.makedirs(os.path.join(td, "logs"), exist_ok=True)
        rc = supervise("pythia", td, 0, "logs/pythia.log",
                       [sys.executable, "-c", "import time; time.sleep(60)"],
                       kill_secs=1.0, stall_secs=1000.0, poll=0.2, grace=1.0, _engineering_only=_ENGINEERING_SELFTEST)
        fj = os.path.join(td, "logs", "pythia.failure.json")
        ok = (rc == 124) and os.path.isfile(fj)
        if ok:
            r = json.load(open(fj))
            ok = r.get("status") == "open" and r.get("reason") == "wall-clock" and bool(r.get("next_action"))
        print(f"[selftest] 1 wall-clock kill: rc={rc}  {'ok' if ok else 'FAIL'}")
        if not ok: fails.append("wall-clock kill / failure.json wrong")
        rc2 = supervise("delphes", td, 0, "logs/delphes.log",
                        [sys.executable, "-c", "print('done')"],
                        kill_secs=10.0, stall_secs=10.0, poll=0.2, grace=1.0, _engineering_only=_ENGINEERING_SELFTEST)
        ok2 = (rc2 == 0) and not os.path.isfile(os.path.join(td, "logs", "delphes.failure.json"))
        print(f"[selftest] 2 clean stage: rc={rc2}  {'ok' if ok2 else 'FAIL'}")
        if not ok2: fails.append("clean stage returned nonzero / wrote a spurious failure.json")
        rc3 = supervise("madgraph", td, 0, "logs/madgraph.log",
                        [sys.executable, "-c", "import sys; sys.exit(0)"],
                        kill_secs=10.0, stall_secs=10.0, poll=0.2, grace=1.0, _engineering_only=_ENGINEERING_SELFTEST)
        ok3 = (rc3 == 3) and os.path.isfile(os.path.join(td, "logs", "madgraph.failure.json"))
        print(f"[selftest] 3 exit-0-implausible: rc={rc3}  {'ok' if ok3 else 'FAIL'}")
        if not ok3: fails.append("empty-log rc0 producing stage not flagged implausible")
    if fails:
        for f in fails: print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("stage_supervisor selftest: PASS (3 cases)")
    return 0

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--rundir", required=True)
    ap.add_argument("--events", type=int, default=0)
    ap.add_argument("--log", required=True, help="log path relative to rundir")
    ap.add_argument("--kill-secs", type=float, default=None)
    ap.add_argument("--stall-secs", type=float, default=None)
    ap.add_argument("--input", action="append", default=[], dest="inputs")
    ap.add_argument("--output", action="append", default=[], dest="outputs")
    ap.add_argument("--depends-on", action="append", default=[])
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--cwd", help="working directory for the stage command")
    ap.add_argument("--required-plan", choices=("smoke", "full", "scan"),
                    help="required compute rung for a contracted generic stage; smoke is limited to 1000 events")
    ap.add_argument("--backend-plan", help="execution-backend plan JSON; the stage runs through that backend")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    cmd = args.cmd[1:] if (args.cmd and args.cmd[0] == "--") else args.cmd
    if not cmd and not args.backend_plan:
        print("stage_supervisor: no command after --", file=sys.stderr); return 2
    if not os.path.isdir(args.rundir):
        print(f"stage_supervisor: not a directory: {args.rundir}", file=sys.stderr); return 2
    try:
        return supervise(args.stage, args.rundir, args.events, args.log, cmd,
                         kill_secs=args.kill_secs, stall_secs=args.stall_secs,
                         inputs=args.inputs, outputs=args.outputs, depends_on=args.depends_on,
                         resume=args.resume, cwd=args.cwd, required_plan=args.required_plan,
                         backend_plan=args.backend_plan)
    except (OSError, ValueError) as exc:
        print(f"stage_supervisor: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
