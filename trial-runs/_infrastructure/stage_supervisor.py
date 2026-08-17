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
import argparse, hashlib, json, os, signal, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import cost_preflight as cp  # noqa: E402

SCHEMA_VERSION = 1
KILL_MARGIN = 3.0          # kill at 3x the modelled stage budget
FLOOR_SECS = 300.0         # never kill before 5 min (protect legitimately fast stages)
POLL_SECS = 5.0
GRACE_SECS = 10.0          # SIGTERM -> wait -> SIGKILL
MUST_PRODUCE = ("madgraph", "pythia", "delphes", "analysis", "simpleanalysis", "sa2json", "pyhf")

def _resolve_timestamp():
    ov = os.environ.get("GATE_TIMESTAMP")
    return ov if ov else "1970-01-01T00:00:00Z"

def stage_budget_min(stage, events):
    """Modelled wall-clock budget (minutes) for a stage. Only quantified data is cost_preflight's
    {MadGraph-linear-in-events, 12-min-flat-rest} split -- there is no finer per-stage table."""
    scale = (float(events) if events else cp.NATIVE_REF_EVENTS) / cp.NATIVE_REF_EVENTS
    if stage == "madgraph":
        return (cp.NATIVE_PT_MIN_HI - cp.NATIVE_FLAT_MIN) * scale
    return cp.NATIVE_FLAT_MIN

def _fingerprint(cmd):
    return hashlib.sha256((" ".join(cmd)).encode("utf-8")).hexdigest()

def write_failure(rundir, stage, reason, elapsed, kill_secs, cmd, logrel):
    rec = {
        "schema_version": SCHEMA_VERSION, "generated_by": "stage_supervisor.py",
        "generator": "stage_supervisor.py", "generated_utc": _resolve_timestamp(),
        "input_fingerprint": _fingerprint(cmd), "stage": stage, "status": "open",
        "reason": reason, "elapsed_s": round(elapsed, 1), "kill_threshold_s": round(kill_secs, 1),
        "logfile": logrel,
        "next_action": (f"stage '{stage}' was killed after {round(elapsed)}s ({reason}); the point "
                        f"is now FAILED. Inspect {logrel}, then reset the point (remove "
                        f"logs/STATUS.txt so the babysitter re-runs it) or diagnose+fix the hang "
                        f"before relaunch."),
    }
    path = os.path.join(rundir, "logs", f"{stage}.failure.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(rec, fh, indent=2)
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

def supervise(stage, rundir, events, logrel, cmd, kill_secs=None, stall_secs=None,
              poll=POLL_SECS, grace=GRACE_SECS):
    budget_min = stage_budget_min(stage, events)
    if kill_secs is None:
        kill_secs = max(FLOOR_SECS, budget_min * KILL_MARGIN * 60.0)
    if stall_secs is None:
        stall_secs = max(FLOOR_SECS, budget_min * 60.0)   # no log write for a whole budget => stalled
    logpath = os.path.join(rundir, logrel)
    os.makedirs(os.path.dirname(logpath), exist_ok=True)
    log = open(logpath, "wb")
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
    reason = None
    while True:
        rc = proc.poll()
        if rc is not None:
            break
        now = time.time()
        elapsed = now - t0
        try:
            mtime = os.path.getmtime(logpath)
        except OSError:
            mtime = t0
        if elapsed > kill_secs:
            reason = "wall-clock"
        elif elapsed > FLOOR_SECS and (now - mtime) > stall_secs:
            reason = "progress-stall"
        if reason:
            proc.send_signal(signal.SIGTERM)
            t_term = time.time()
            while proc.poll() is None and (time.time() - t_term) < grace:
                time.sleep(0.2)
            if proc.poll() is None:
                proc.send_signal(signal.SIGKILL)
                proc.wait()
            log.flush(); log.close()
            write_failure(rundir, stage, reason, time.time() - t0, kill_secs, cmd, logrel)
            return 124
        time.sleep(poll)
    log.flush(); log.close()
    elapsed = time.time() - t0
    if rc == 0 and stage in MUST_PRODUCE:
        try:
            size = os.path.getsize(logpath)
        except OSError:
            size = 0
        if size == 0:
            write_failure(rundir, stage, "exit-0-implausible", elapsed, kill_secs, cmd, logrel)
            return 3
    return rc

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
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    cmd = args.cmd[1:] if (args.cmd and args.cmd[0] == "--") else args.cmd
    if not cmd:
        print("stage_supervisor: no command after --", file=sys.stderr); return 2
    if not os.path.isdir(args.rundir):
        print(f"stage_supervisor: not a directory: {args.rundir}", file=sys.stderr); return 2
    return supervise(args.stage, args.rundir, args.events, args.log, cmd,
                     kill_secs=args.kill_secs, stall_secs=args.stall_secs)

if __name__ == "__main__":
    sys.exit(main())
