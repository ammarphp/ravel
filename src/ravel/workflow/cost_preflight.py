#!/usr/bin/env python3
"""Fresh process-aware compute-cost preflight.

Generation cost is uncalibrated until actual same-process/model/settings/machine
pilots exist. Historical slepton anchors are retained only for historical replay
and named reference use, never silently applied to new loop processes.
Explicit wall/RAM/event ceilings are authorization limits, not forecasts.
A measured record (schema 3) comes only from completed pilots on this machine:
`ravel pilot-cost observe/forecast`, then `--from-forecast <forecast.json>`.
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
import sys

from .cost_records import make_record, forecast_for, render

# measured anchors (steps/08-scan.md + the fig3 scan RESULT): minutes per native point
NATIVE_PT_MIN_LO, NATIVE_PT_MIN_HI = 30.0, 50.0     # full chain @ ~20k events
NATIVE_REF_EVENTS = 20000.0                          # the measured anchor
NATIVE_FLAT_MIN = 12.0                               # non-MG stages, roughly event-independent
CONTAINER_PT_H = 9.0                                 # legacy, sequential
TRANSIENT_GB_PT = 6.0                                # LHE+HepMC+Delphes before cleanup
PERSISTENT_MB_PT = 5.0                               # exclusion.json/config/logs kept


def _historical_reference_estimate(mode, points, events, backend, parallel):
    if mode == "none":
        return {"mode": mode, "walltime_h": [0.0, 0.0], "disk_gb_peak": 0.0,
                "note": "no generation (survey/summary from published material)"}
    if mode == "dry":
        return {"mode": mode, "walltime_h": [0.0, 0.1], "disk_gb_peak": 0.0,
                "note": "render cards/configs only; fail-loud placeholder scan; no generation"}
    if mode == "smoke":
        ev = min(events or 1000, 1000)
        return {"mode": mode, "points": 1, "events_per_point": ev,
                "backend": backend, "parallel": 1,
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
                        "native port exists (docs/reference/scope.md section 2)"}
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
        est["warning"] = (f"{pts} points > overnight at the measured rate — consider the published "
                          f"lattice subset / a coarser grid first, or cluster the dense plane")
    elif est["walltime_h"][1] > 6:
        est["note"] = "overnight-scale scan: maintain the run's RESUME.md checkpoint (run-scan skill)"
    return est



def historical_reference_estimate(mode, points, events, backend, parallel):
    """Retain historical reference values without claiming current calibration."""
    result = _historical_reference_estimate(mode, points, events, backend, parallel)
    wall = result['walltime_h']
    result.update(make_record(_cost_class(mode), 'historical',
        {'process': 'historical_generation_reference', 'configuration': backend, 'machine': None},
        'Historical reference only; no current process/configuration/machine match.',
        wall_hours=None if mode in ('none', 'dry') else sum(wall) / 2,
        disk_gb=None if mode in ('none', 'dry') else result['disk_gb_peak'],
        events=0 if mode in ('none', 'dry') else result.get('points', 1) * result.get('events_per_point', 0)))
    return result


def _cost_class(mode):
    return {'none': 'existing_result', 'dry': 'transform_or_render',
            'smoke': 'single_point_chain', 'full': 'single_point_chain', 'scan': 'justified_scan'}[mode]

def estimate(mode, points, events, backend, parallel):
    """Fresh generation has no universal calibrated process cost.

    Historical records and the named reference function remain available for
    replay; their slepton anchor is not an estimate for another matrix element.
    """
    if mode in ('none', 'dry'):
        result = historical_reference_estimate(mode, points, events, backend, parallel)
        result.update(make_record(_cost_class(mode), 'unknown', None,
            'No measured wall, CPU, disk or model usage. No new events requested.', events=0))
        result['walltime_h'] = None
        result['disk_gb_peak'] = None
        return result
    if mode not in ('smoke', 'full', 'scan') or backend not in ('native', 'container'):
        raise ValueError('known compute mode/backend required')
    if (type(points) is not int or points < 1 or type(parallel) is not int or parallel < 1
            or events is not None and (type(events) is not int or events < 1)):
        raise ValueError('explicit positive requested population required')
    return {**make_record(_cost_class(mode), 'uncalibrated', None,
                'No process/configuration/machine-matched pilot.',
                events=None if events is None else (1 if mode == 'smoke' else points) * events),
            'schema_version': 2, 'mode': mode, 'points': 1 if mode == 'smoke' else points,
            'events_per_point': events, 'backend': backend, 'parallel': parallel,
            'calibration_status': 'uncalibrated', 'walltime_h': None, 'disk_gb_peak': None,
            'next_api': 'ravel.workflow.generation_efficiency.prepare_pilot',
            'note': 'No process/model/settings/machine-matched pilot. Supply a complete bounded ordinary pilot specification; no runtime interval is inferred from the historical slepton anchor.',
            'production_feasibility_established': False}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", required=True, choices=("none", "dry", "smoke", "full", "scan"))
    ap.add_argument("--points", type=int, default=1, help="grid points (scan mode)")
    ap.add_argument("--events", type=int, default=None, help="events/point (default 20k)")
    ap.add_argument("--backend", default="native", choices=("native", "container"))
    ap.add_argument("--parallel", type=int, default=None, help="native --max concurrency (default 4; 1 for a measured record)")
    ap.add_argument("--json", action="store_true", help="machine output only")
    ap.add_argument("--from-forecast", default=None, metavar="FORECAST_JSON",
                    help="write a measured (schema 3) record from a pilot forecast instead of an estimate")
    ap.add_argument("--rundir", default=None,
                    help="ALSO write inputs/cost_preflight.json under this run dir (the budget "
                         "must be an ARTIFACT -- the approval gate requires it)")
    args = ap.parse_args(argv)

    if args.from_forecast:
        from ravel.workflow.pilot_cost import record
        if not args.rundir:
            ap.error("--from-forecast writes inputs/cost_preflight.json and needs --rundir")
        rec = record(args.from_forecast, mode=args.mode, points=args.points, parallel=args.parallel or 1,
                     events_per_point=args.events)
        out = os.path.join(args.rundir, "inputs", "cost_preflight.json")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2)
        print(json.dumps(rec, indent=2) if args.json else f"measured cost_preflight artifact -> {out}")
        return 0
    est = estimate(args.mode, args.points, args.events, args.backend, args.parallel or 4)
    if args.rundir:
        os.makedirs(os.path.join(args.rundir, "inputs"), exist_ok=True)
        rec = {"schema_version": est.get('schema_version', 1), "generated_by": "cost_preflight.py",
               "generated_utc": os.environ.get("COST_PREFLIGHT_UTC", "")}
        rec.update(est)
        from .completion_lifecycle import seal_cost
        rec = seal_cost(args.rundir, rec)
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
    print(render(est))
    if est.get('walltime_h') is None:
        print('  walltime : unknown; authorized ceilings are separate')
        if est.get('next_api'):
            print('  next     : ' + est['next_api'])
        print('  note     : ' + est['note'])
        return
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
