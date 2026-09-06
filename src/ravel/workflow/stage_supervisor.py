#!/usr/bin/env python3
"""stage_supervisor.py -- CATCH watchdog wrapping ONE pipeline stage command (G6/D6).
No `timeout` on this macOS host; this is the python subprocess supervisor that replaces the inner
`( "$@" )` of run-pipeline-native.sh:run_stage. It launches the stage command, polls wall-clock +
progress-stall + exit-0-plausibility against per-stage kill thresholds DERIVED FROM cost_preflight,
and on a hang SIGTERM/SIGKILLs it, writes logs/<stage>.failure.json (+ a next-action), records it to
the run ledger (workflow_state.py record --kind failure, D-3), and returns nonzero so the existing
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
from pathlib import Path
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from ravel.workflow import cost_preflight as cp  # noqa: E402
from ravel.workflow import execution
from ravel.workflow.state_io import atomic_json, file_lock

SCHEMA_VERSION = 1
KILL_MARGIN = 3.0          # kill at 3x the modelled stage budget
PYHF_MEASURED_MIN = 20.0   # MEASURED, not modelled (2026-08-28 fresh-flagship waypoint m150_dm20:
                           # 1036 s = 17.3 min SOLO full-stat on the 141-SR Slepton workspace;
                           # smoke rung 18.5 min). The 12-min flat-rest model under-budgets pyhf:
                           # its CLs scan is workspace-sized, event-count-independent. Budget 20 min
                           # -> stall 20 min (heartbeat lands every ~45-90 s, so stall only fires on
                           # a real hang) and kill 60 min (3x), headroom for parallel=3 contention.
FLOOR_SECS = 300.0         # never kill before 5 min (protect legitimately fast stages)
POLL_SECS = 5.0
GRACE_SECS = 10.0          # SIGTERM -> wait -> SIGKILL
CLEANUP_CENSUS_SCOPE = "non-zombie process-group members reported by ps; zombies excluded"
MUST_PRODUCE = ("madgraph", "pythia", "delphes", "analysis", "simpleanalysis", "sa2json", "pyhf")

def _resolve_timestamp():
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
        "generator": "stage_supervisor.py", "generated_utc": _resolve_timestamp(),
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
    # RECONCILE D-3: durably record the open failure in the run ledger so the Stop CATCH branch's
    # FALLBACK (`workflow_state.py status` -> open_failure_records) sees it. Best-effort: never let a
    # ledger hiccup (missing/older run_state, CLI drift) mask the stage failure the caller surfaces.
    ws = os.path.join(HERE, "workflow_state.py")
    if os.path.isfile(ws):
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


def _observe_group(result):
    # execution's census excludes zombies. "empty" means no active members in
    # this group, not proof that every OS process-table entry has disappeared.
    try:
        members = execution.process_group_members(result["process_group"])
    except (Exception, KeyboardInterrupt) as exc:
        _cleanup_error(result, "query_process_group", exc)
        members = None
    result["remaining_group_members"] = members
    result["group_state"] = "unknown" if members is None else ("active" if members else "empty")
    result["requires_recovery"] = members is None or bool(members)
    return members


def _terminate_owned_group(pid, grace, proc=None):
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
    members = _observe_group(result)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not members:  # Empty is finished; unknown is held without blind escalation.
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
            _observe_group(result)
            break
        deadline = time.monotonic() + grace
        while True:
            poll_leader()
            members = _observe_group(result)
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
            result["leader_returncode"] = proc.wait(timeout=grace)
        except (Exception, KeyboardInterrupt) as exc:
            _cleanup_error(result, "wait_for_leader", exc)
            wait_failed = True
        # The bounded wait can change group membership. Report this later observed
        # state without retroactively claiming that a denied signal succeeded.
        _observe_group(result)
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


def _recover_orphan(rundir, stage, grace):
    old = execution.load_execution(rundir)["stages"].get(stage, {})
    if not old.get("child_pid"):
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
        if not execution.process_group_members(pid):
            return
        if not old.get("child_identity"):
            raise ValueError(f"cannot establish ownership of previous group {pid}; stage {stage} held")
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


def supervise(stage, rundir, events, logrel, cmd, kill_secs=None, stall_secs=None,
              poll=POLL_SECS, grace=GRACE_SECS, *, inputs=None, outputs=None,
              depends_on=None, resume=False, cwd=None):
    """Run one declared stage; resume only a content-identical successful attempt.

    Log silence is not a default failure signal. A caller may supply stall_secs only
    for tools with a documented live progress stream. Scientific postconditions use
    explicit output artifacts; legacy callers retain the empty-producing-log check.
    """
    budget_min = stage_budget_min(stage, events)
    if kill_secs is None:
        kill_secs = max(FLOOR_SECS, budget_min * KILL_MARGIN * 60.0)
    import math
    for name, value in (("kill_secs", kill_secs), ("poll", poll), ("grace", grace),
                        ("stall_secs", stall_secs)):
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value <= 0):
            raise ValueError(f"{name} must be positive and finite")
    root = Path(rundir).resolve()
    if not root.is_dir():
        raise ValueError("run directory does not exist")
    if not execution.NAME.fullmatch(stage):
        raise ValueError("invalid stage name")
    logpath = execution.log_path(root, logrel)
    logpath.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(root / "logs/execution" / f"{stage}.lock", blocking=False):
        specification = execution.plan_stage(root, stage, list(cmd), inputs or [], outputs or [],
                                             depends_on or [], cwd or os.getcwd())
        if resume and execution.reusable(root, stage, specification):
            print(f"REUSED {stage}: inputs, dependencies and outputs verified", flush=True)
            return 0
        _recover_orphan(root, stage, grace)
        record = execution.begin_attempt(root, stage, specification, logrel)
        t0 = time.monotonic()
        proc = None
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
            with logpath.open("wb") as log:
                proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                        cwd=cwd, start_new_session=True)
                execution.record_process(root, record, proc.pid)
                while proc.poll() is None:
                    elapsed = time.monotonic() - t0
                    if elapsed > kill_secs:
                        reason = "wall-clock"
                    elif stall_secs is not None and time.time() - logpath.stat().st_mtime > stall_secs:
                        reason = "progress-stall"
                    if reason:
                        code = 124
                        break
                    time.sleep(poll)
            code = 124 if reason else (proc.returncode if proc.returncode >= 0 else 128 - proc.returncode)
            if code and not reason:
                reason = f"exit-{code}"
            if code == 0 and execution.process_group_members(proc.pid):
                code, reason = 3, "descendants remained active after the stage leader exited"
            if code == 0 and not outputs and stage in MUST_PRODUCE and logpath.stat().st_size == 0:
                code, reason = 3, "exit-0-implausible"
        except KeyboardInterrupt:
            if not reason:
                code, reason = 130, "interrupted"
        except Exception as exc:
            if not reason:
                code, reason = 2, str(exc)
        finally:
            if proc is not None and code:
                record["cleanup"] = _safe_cleanup(proc, grace)
            for sig, handler in previous_handlers.items():
                try:
                    signal.signal(sig, handler)
                except (Exception, KeyboardInterrupt) as exc:
                    record.setdefault("supervision_errors", []).append(str(exc))
                    if not code:
                        code, reason = 2, "could not restore supervisor signal handlers"
        code = execution.finish_attempt(root, record, code, reason)
        if code:
            write_failure(str(root), stage, record.get("error") or f"exit-{code}",
                          time.monotonic() - t0, kill_secs, cmd, logrel,
                          cleanup=record.get("cleanup"))
        else:
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
    fails = []
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "logs"), exist_ok=True)
        rc = supervise("pythia", td, 20000, "logs/pythia.log",
                       [sys.executable, "-c", "import time; time.sleep(60)"],
                       kill_secs=1.0, stall_secs=1000.0, poll=0.2, grace=1.0)
        fj = os.path.join(td, "logs", "pythia.failure.json")
        ok = (rc == 124) and os.path.isfile(fj)
        if ok:
            r = json.load(open(fj))
            ok = r.get("status") == "open" and r.get("reason") == "wall-clock" and bool(r.get("next_action"))
        print(f"[selftest] 1 wall-clock kill: rc={rc}  {'ok' if ok else 'FAIL'}")
        if not ok: fails.append("wall-clock kill / failure.json wrong")
        rc2 = supervise("delphes", td, 20000, "logs/delphes.log",
                        [sys.executable, "-c", "print('done')"],
                        kill_secs=10.0, stall_secs=10.0, poll=0.2, grace=1.0)
        ok2 = (rc2 == 0) and not os.path.isfile(os.path.join(td, "logs", "delphes.failure.json"))
        print(f"[selftest] 2 clean stage: rc={rc2}  {'ok' if ok2 else 'FAIL'}")
        if not ok2: fails.append("clean stage returned nonzero / wrote a spurious failure.json")
        rc3 = supervise("madgraph", td, 20000, "logs/madgraph.log",
                        [sys.executable, "-c", "import sys; sys.exit(0)"],
                        kill_secs=10.0, stall_secs=10.0, poll=0.2, grace=1.0)
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
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    cmd = args.cmd[1:] if (args.cmd and args.cmd[0] == "--") else args.cmd
    if not cmd:
        print("stage_supervisor: no command after --", file=sys.stderr); return 2
    if not os.path.isdir(args.rundir):
        print(f"stage_supervisor: not a directory: {args.rundir}", file=sys.stderr); return 2
    try:
        return supervise(args.stage, args.rundir, args.events, args.log, cmd,
                         kill_secs=args.kill_secs, stall_secs=args.stall_secs,
                         inputs=args.inputs, outputs=args.outputs, depends_on=args.depends_on,
                         resume=args.resume, cwd=args.cwd)
    except (OSError, ValueError) as exc:
        print(f"stage_supervisor: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
