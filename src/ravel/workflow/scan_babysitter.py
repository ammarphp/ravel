#!/usr/bin/env python
"""scan_babysitter -- keep a native scan alive, self-cleaning, and disk-safe (2026-07-07).

A native mass-plane scan runs many points, each leaving ~6 GB of REGENERABLE intermediates
(MadGraph procdir + event files, Delphes ROOT, HepMC). On this laptop that fills the disk in a few
dozen points -- the CR-004 rescan lost 8 points to `NoSpaceLeftError` this way. It also needs a
live driver to keep parallelism topped up and to retry points killed mid-stage (a process exit
leaves a truncated delphes.root -> ZeroDivisionError downstream). This babysitter does all three:

  1. CLEAN: for every COMPLETED point (curated `output/exclusion.json` present), delete the heavy
     regenerable subdirs (`output/{madgraph,delphes,PROC_madgraph,analysis}`) -- the curated trio
     (exclusion.json / *.txt / *_patch.json / *.png) is preserved (the .gitignore curation policy).
  2. HEAL: a point whose STATUS.txt shows FAIL/STOPPED, or that is "running" with NO live process
     and a stale (> --stale-min) STATUS mtime, is reset to pending (its STATUS.txt removed +
     partial intermediates cleaned) so it re-runs cleanly.
  3. FEED: keep `--parallel` points live by launching pending points via scan_orchestrator, but
     ONLY while free disk >= --min-free-gb (never start a point that would run the disk dry).

Loops until done+failed==all with nothing left to heal, or --once. Read-only w.r.t. curated data.

Usage:
  scan_babysitter.py <scandir> [--parallel 4] [--min-free-gb 30] [--stale-min 25]
                      [--interval 180] [--once] [--backend native] [--pdf cteq6l1|nnpdf30]
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.workflow"

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
from pathlib import Path
from ravel.paths import repository_root
REPO = str(repository_root() or Path.cwd())
ORCH = os.path.join(HERE, "scan_orchestrator.py")
HEAVY = ("madgraph", "delphes", "PROC_madgraph", "analysis")


def free_gb(path="."):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / 1e9


def live_points(ps_output=None):
    """Set of point tags with a live native process (from ps). Returns BOTH the full run-token tag
    AND the short manifest tag (m<..>_dm<..>, with 'p' for a decimal dm) so a membership test against
    manifest mp['tag'] is MEANINGFUL. The old regex _m\\d+_dm\\d+ (a) missed fractional dm like dm2p5
    and (b) only yielded the full tag -> `tag not in live` was always-true (SHARED-CONVENTIONS J).
    Both are fixed here. `ps_output` is a test seam."""
    import re
    if ps_output is None:
        try:
            ps_output = subprocess.run(["ps", "ax", "-o", "command"],
                                       capture_output=True, text=True).stdout
        except Exception:
            return set()
    procs = ("run-pipeline-native", "mg5_aMC", "DelphesHepMC", "pythia_shower",
             "native_simpleanalysis", "rjr_resolve", "delphes2sa")
    tags = set()
    for line in ps_output.splitlines():
        if "scan_babysitter" in line:                 # never count the babysitter itself
            continue
        if any(k in line for k in procs):
            short = re.search(r"(m[\dp]+_dm[\dp]+)", line)
            if short:
                tags.add(short.group(1))
            full = re.search(r"([A-Za-z0-9]+_m[\dp]+_dm[\dp]+)", line)
            if full:
                tags.add(full.group(1))
    return tags


def clean_heavy(run_dir):
    freed = 0
    outdir = os.path.join(run_dir, "output")
    for sub in HEAVY:
        p = os.path.join(outdir, sub)
        if os.path.isdir(p):
            try:
                freed += sum(s.st_size for s in _walk(p))
                shutil.rmtree(p)
            except OSError:
                pass
    return freed


def _walk(p):
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                yield os.stat(os.path.join(root, f))
            except OSError:
                pass


def load_manifest(scandir):
    man = os.path.join(REPO, scandir, "scan_manifest.json") if not os.path.isabs(scandir) \
        else os.path.join(scandir, "scan_manifest.json")
    with open(man) as f:
        return json.load(f)


def point_state(run_dir):
    """(state, run_dir) using the same rules as scan_orchestrator.point_status, locally."""
    excl = os.path.join(run_dir, "output", "exclusion.json")
    if os.path.isfile(excl):
        return "done"
    status = os.path.join(run_dir, "logs", "STATUS.txt")
    if os.path.isfile(status):
        lines = open(status).read().strip().splitlines()
        last = lines[-1] if lines else ""
        if "FAIL" in last or "STOPPED" in last:
            return "failed"
        if any(k in last for k in ("START", "PASS", "pipeline start", "COMPLETE")):
            return "running"
    return "pending"


def reset_point(run_dir):
    clean_heavy(run_dir)
    status = os.path.join(run_dir, "logs", "STATUS.txt")
    if os.path.isfile(status):
        os.remove(status)


def stall_heal_due(mtime, tag, live, now, stale_min):
    """A 'running' point is stale-dead iff its STATUS.txt mtime is older than stale_min AND no live
    pipeline process carries its (short) tag. With live_points() now returning the short manifest
    tag, `tag not in live` is a REAL liveness guard (previously always-true, SHARED-CONVENTIONS J):
    a genuinely-live 30-50 min MadGraph stage (frozen STATUS mtime) is NOT falsely healed, while a
    died-mid-stage point (no live proc, stale STATUS) IS."""
    return (tag not in live) and ((now - mtime) > stale_min * 60)


def cycle(scandir, man, args):
    live = live_points()
    counts = {"done": 0, "running": 0, "failed": 0, "pending": 0, "stale": 0, "healed": 0}
    freed = 0
    now = time.time()
    for mp in man["points"]:
        run_dir = os.path.join(REPO, mp["run_dir"])
        tag = mp["tag"]
        st = point_state(run_dir)
        if st == "done":
            counts["done"] += 1
            freed += clean_heavy(run_dir)                      # 1. CLEAN
            continue
        if st == "failed":
            reset_point(run_dir); counts["healed"] += 1        # 2. HEAL (failed -> pending)
            continue
        if st == "running":
            status = os.path.join(run_dir, "logs", "STATUS.txt")
            mtime = os.path.getmtime(status) if os.path.isfile(status) else 0
            if stall_heal_due(mtime, tag, live, now, args.stale_min):
                reset_point(run_dir); counts["stale"] += 1; counts["healed"] += 1   # stale -> pending
            else:
                counts["running"] += 1
            continue
        counts["pending"] += 1
    return counts, freed / 1e9


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scandir")
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--min-free-gb", type=float, default=30.0)
    ap.add_argument("--stale-min", type=float, default=25.0)
    ap.add_argument("--interval", type=float, default=180.0)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--backend", default="native")
    ap.add_argument("--pdf", default="cteq6l1", choices=["cteq6l1", "nnpdf30"])
    args = ap.parse_args()
    man = load_manifest(args.scandir)
    ntot = len(man["points"])

    while True:
        counts, freed = cycle(args.scandir, man, args)
        live_n = len(live_points())
        fg = free_gb(REPO)
        print(f"[babysit] done={counts['done']} running={counts['running']} "
              f"pending={counts['pending']} healed={counts['healed']} (stale={counts['stale']})  "
              f"live_proc={live_n}  free={fg:.0f}GB  reclaimed_this_cycle={freed:.0f}GB", flush=True)

        remaining = counts["pending"] + counts["running"]
        if remaining == 0 and counts["healed"] == 0:
            print(f"[babysit] SCAN COMPLETE: {counts['done']}/{ntot} done. Nothing pending/running.",
                  flush=True)
            return 0

        # 3. FEED: launch pending up to the parallelism cap, disk permitting
        slots = max(0, args.parallel - live_n)
        if slots > 0 and counts["pending"] > 0 and fg >= args.min_free_gb:
            cmd = [sys.executable, ORCH, "launch", args.scandir, "--backend", args.backend,
                   "--max", str(slots), "--go"]
            if args.backend == "native":
                cmd += ["--pdf", args.pdf]
            subprocess.run(cmd, capture_output=True, text=True)
            print(f"[babysit] fed {slots} point(s) (free {fg:.0f}GB >= {args.min_free_gb})", flush=True)
        elif fg < args.min_free_gb:
            print(f"[babysit] HOLDING: free {fg:.0f}GB < {args.min_free_gb}GB floor "
                  "(cleaning continues; not starting new points)", flush=True)

        if args.once:
            return 0
        time.sleep(args.interval)


def _selftest():
    fails = []
    ps = ("99999 python /r/trial-runs/2026_sleptonscan_m150_dm2p5/output/"
          "native_simpleanalysis.py --input x\n")
    lp = live_points(ps_output=ps)
    if "m150_dm2p5" not in lp: fails.append("live_points missed fractional-dm short tag")
    if "sleptonscan_m150_dm2p5" not in lp: fails.append("live_points missed the full tag")
    now = 1e6
    if not stall_heal_due(now - 40 * 60, "m150_dm2p5", set(), now, 25.0):
        fails.append("dead+stale point not healed")
    if stall_heal_due(now - 40 * 60, "m150_dm2p5", {"m150_dm2p5"}, now, 25.0):
        fails.append("LIVE point falsely healed")
    if stall_heal_due(now - 60, "m150_dm2p5", set(), now, 25.0):
        fails.append("fresh-mtime point healed")
    if fails:
        for f in fails: print("SELFTEST FAIL:", f, file=sys.stderr)
        return 1
    print("scan_babysitter selftest: PASS (5 checks)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main())
