#!/usr/bin/env python3
"""Compute-cost preflight: events x points x walltime x disk BEFORE any generation.

CHECK-IN 1's budget line comes from HERE, not from prose recall (charter F5). The model is
the repo's own measured numbers (steps/08-scan.md compute reality):

  native backend   full-chain point ~30-50 min wall (measured ~49 min @ 20k events; the
                   MadGraph stage scales with nevents, the rest is ~flat), points run in
                   PARALLEL (--max, default 4); transient ~6 GB/point (LHE+HepMC+Delphes,
                   freed per point after harvest); persistent ~5 MB/point curated.
  container        ~9 h/point, STRICTLY SEQUENTIAL (shared VM); legacy fallback only.

The LADDER (the contract's compute_plan): none -> dry (render cards only, no generation)
-> smoke (1 point, ~1k events: minutes — the CHECK-IN 2 waypoint fuel) -> full (1 point,
full stats) -> scan (N points). Climb it; never jump to scan pre-approval.

Stdlib-only. Usage:
  cost_preflight.py --mode scan --points 52 [--events 20000] [--backend native] [--parallel 4]
  cost_preflight.py --mode smoke                     # the waypoint rung
  cost_preflight.py --mode full --events 50000 --json
"""
import argparse
import json
import os
import sys

# measured anchors (steps/08-scan.md + the fig3 scan RESULT): minutes per native point
NATIVE_PT_MIN_LO, NATIVE_PT_MIN_HI = 30.0, 50.0     # full chain @ ~20k events
NATIVE_REF_EVENTS = 20000.0                          # the measured anchor
NATIVE_FLAT_MIN = 12.0                               # non-MG stages, roughly event-independent
CONTAINER_PT_H = 9.0                                 # legacy, sequential
TRANSIENT_GB_PT = 6.0                                # LHE+HepMC+Delphes before cleanup
PERSISTENT_MB_PT = 5.0                               # exclusion.json/config/logs kept


def estimate(mode, points, events, backend, parallel):
    if mode == "none":
        return {"mode": mode, "walltime_h": [0.0, 0.0], "disk_gb_peak": 0.0,
                "note": "no generation (survey/summary from published material)"}
    if mode == "dry":
        return {"mode": mode, "walltime_h": [0.0, 0.1], "disk_gb_peak": 0.0,
                "note": "render cards/configs only; fail-loud placeholder scan; no generation"}
    if mode == "smoke":
        ev = min(events or 1000, 1000)
        return {"mode": mode, "points": 1, "events_per_point": ev,
                "walltime_h": [0.1, 0.35], "disk_gb_peak": 1.0,
                "note": "1 point at smoke statistics — the CHECK-IN 2 waypoint rung"}
    pts = max(1, int(points or 1))
    ev = float(events or NATIVE_REF_EVENTS)
    if backend == "container":
        wall_h = pts * CONTAINER_PT_H
        return {"mode": mode, "points": pts, "events_per_point": int(ev),
                "backend": backend, "parallel": 1,
                "walltime_h": [round(wall_h * 0.9, 1), round(wall_h * 1.2, 1)],
                "disk_gb_peak": round(TRANSIENT_GB_PT + pts * PERSISTENT_MB_PT / 1024, 1),
                "note": "container backend is SEQUENTIAL (~9 h/point) — use only when no "
                        "native port exists (PRODUCT-CONTRACT section 2)"}
    # native: MG stage scales ~linearly with events around the anchor; the rest is flat
    scale = ev / NATIVE_REF_EVENTS
    pt_lo = NATIVE_FLAT_MIN + (NATIVE_PT_MIN_LO - NATIVE_FLAT_MIN) * scale
    pt_hi = NATIVE_FLAT_MIN + (NATIVE_PT_MIN_HI - NATIVE_FLAT_MIN) * scale
    par = max(1, int(parallel or 4))
    waves = -(-pts // par)  # ceil
    est = {"mode": mode, "points": pts, "events_per_point": int(ev), "backend": "native",
           "parallel": par,
           "per_point_min": [round(pt_lo), round(pt_hi)],
           "walltime_h": [round(waves * pt_lo / 60, 1), round(waves * pt_hi / 60, 1)],
           "disk_gb_peak": round(par * TRANSIENT_GB_PT + pts * PERSISTENT_MB_PT / 1024, 1),
           "disk_note": f"~{TRANSIENT_GB_PT:g} GB/point transient x {par} concurrent — clean "
                        f"per point after harvest (keep exclusion.json/config; step 8 rule)",
           }
    if est["walltime_h"][1] > 14:
        est["warning"] = (f"{pts} points > overnight on this host — consider the published "
                          f"lattice subset / a coarser grid first, or cluster the dense plane")
    elif est["walltime_h"][1] > 6:
        est["note"] = "overnight-scale scan: maintain the run's RESUME.md checkpoint (charter 4c)"
    return est


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", required=True, choices=("none", "dry", "smoke", "full", "scan"))
    ap.add_argument("--points", type=int, default=1, help="grid points (scan mode)")
    ap.add_argument("--events", type=int, default=None, help="events/point (default 20k)")
    ap.add_argument("--backend", default="native", choices=("native", "container"))
    ap.add_argument("--parallel", type=int, default=4, help="native --max concurrency")
    ap.add_argument("--json", action="store_true", help="machine output only")
    ap.add_argument("--rundir", default=None,
                    help="ALSO write inputs/cost_preflight.json under this run dir (H4: the budget "
                         "must be an ARTIFACT -- the approval gate requires it)")
    args = ap.parse_args()

    est = estimate(args.mode, args.points, args.events, args.backend, args.parallel)
    if args.rundir:
        os.makedirs(os.path.join(args.rundir, "inputs"), exist_ok=True)
        rec = {"schema_version": 1, "generated_by": "cost_preflight.py",
               "generated_utc": os.environ.get("COST_PREFLIGHT_UTC", "")}
        rec.update(est)
        out = os.path.join(args.rundir, "inputs", "cost_preflight.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2)
        print(f"cost_preflight artifact -> {out}")
    if args.json:
        print(json.dumps(est, indent=2))
        return
    print(f"cost preflight [{est['mode']}]"
          + (f"  {est.get('points')} pt x {est.get('events_per_point')} evt"
             f" ({est.get('backend', '-')}, parallel={est.get('parallel', '-')})"
             if est.get("points") else ""))
    lo, hi = est["walltime_h"]
    print(f"  walltime : {lo}-{hi} h" + (f"  ({est['per_point_min'][0]}-{est['per_point_min'][1]}"
                                         f" min/point)" if est.get("per_point_min") else ""))
    print(f"  disk peak: {est['disk_gb_peak']} GB")
    for k in ("disk_note", "note", "warning"):
        if est.get(k):
            print(f"  {'WARNING' if k == 'warning' else 'note'}   : {est[k]}")
    print("  ladder   : none -> dry -> smoke (waypoint) -> full -> scan; heavy compute only "
          "after CHECK-IN 1 approval")


if __name__ == "__main__":
    main()
