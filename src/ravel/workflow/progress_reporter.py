#!/usr/bin/env python3
"""progress_reporter.py -- emit ONE progress line for a running scan/point (G7). Scheduled via
ScheduleWakeup every ~30 min for any long compute so a run self-reports WITHOUT a nudge (the
abandoned-ScheduleWakeup fix). Reads scan_manifest.json (per-point output/exclusion.json / STATUS.txt
/ *.failure.json) or a single run's logs/STATUS.txt. stdlib-only, read-only, never gates.
Usage: progress_reporter.py --rundir <dir> [--json]  |  progress_reporter.py --selftest
Exit: 0 always * 2 usage/not-a-dir."""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.workflow"

import argparse, glob, json, os, sys

def _free_gb(path="."):
    try:
        st = os.statvfs(path); return st.f_bavail * st.f_frsize / 1e9
    except Exception:
        return 0.0

def _point_state(run_dir):
    if os.path.isfile(os.path.join(run_dir, "output", "exclusion.json")):
        return "done"
    if glob.glob(os.path.join(run_dir, "logs", "*.failure.json")):
        return "failed"
    status = os.path.join(run_dir, "logs", "STATUS.txt")
    if os.path.isfile(status):
        lines = open(status).read().strip().splitlines()
        last = lines[-1] if lines else ""
        if "FAIL" in last or "STOPPED" in last:
            return "failed"
        if any(k in last for k in ("START", "PASS", "pipeline start", "COMPLETE")):
            return "running"
    return "pending"

def report(rundir):
    base = os.path.basename(os.path.normpath(rundir))
    man_path = os.path.join(rundir, "scan_manifest.json")
    counts = {"done": 0, "running": 0, "failed": 0, "pending": 0}
    total = 0
    last = ""
    if os.path.isfile(man_path):
        try:
            man = json.load(open(man_path))
        except Exception:
            man = {"points": []}
        for mp in man.get("points", []):
            rd = mp.get("run_dir", "")
            if rd and not os.path.isabs(rd):
                rd = os.path.join(os.path.dirname(os.path.dirname(rundir)), rd)
            counts[_point_state(rd)] = counts.get(_point_state(rd), 0) + 1
            total += 1
    else:
        total = 1
        st = _point_state(rundir); counts[st] = counts.get(st, 0) + 1
        sp = os.path.join(rundir, "logs", "STATUS.txt")
        if os.path.isfile(sp):
            ls = open(sp).read().strip().splitlines(); last = ls[-1] if ls else ""
    return {"rundir": base, "total": total, "done": counts["done"], "running": counts["running"],
            "failed": counts["failed"], "pending": counts["pending"],
            "free_gb": round(_free_gb(rundir), 0), "last": last}

def _line(r):
    return (f"[progress] {r['rundir']} done={r['done']}/{r['total']} running={r['running']} "
            f"failed={r['failed']} pending={r['pending']} free={r['free_gb']:.0f}GB"
            + (f" last='{r['last']}'" if r['last'] else ""))

def selftest():
    import tempfile
    fails = []
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "logs"))
        pt = os.path.join(td, "pt_m150_dm10"); os.makedirs(os.path.join(pt, "output"))
        open(os.path.join(pt, "output", "exclusion.json"), "w").write("{}")
        json.dump({"points": [{"tag": "m150_dm10", "run_dir": pt}]},
                  open(os.path.join(td, "scan_manifest.json"), "w"))
        r = report(td)
        ok = r["done"] == 1 and r["total"] == 1
        print(f"[selftest] scan done-count: {r['done']}/{r['total']}  {'ok' if ok else 'FAIL'}")
        if not ok: fails.append("scan done count wrong")
    if fails:
        for f in fails: print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("progress_reporter selftest: PASS (1 case)")
    return 0

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rundir"); ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.rundir:
        print(__doc__, file=sys.stderr); return 2
    if not os.path.isdir(args.rundir):
        print(f"progress_reporter: not a directory: {args.rundir}", file=sys.stderr); return 2
    r = report(args.rundir)
    print(json.dumps(r, indent=2) if args.json else _line(r))
    return 0

if __name__ == "__main__":
    sys.exit(main())
