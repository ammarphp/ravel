"""Pilot-measured cost forecasts for supervised generation, and the cost record approval accepts.

A pilot is an ordinary approved run, executed by the supervisor on this machine.
``observe`` reads its completed stage receipts (start and finish times), the
units of work it did (a mode declares its scaling unit: events, points, ...),
the disk its outputs use and the machine it ran on. ``forecast`` scales one or
more pilots of the same process profile to a target specification. ``record``
turns a forecast into a schema-3 ``cost_preflight.json`` with
``calibration_status: measured`` and its basis pinned by hash; the lifecycle
admits that record for full and scan launches. Nothing here launches compute.

Scaling. With one pilot the forecast is bounded below by the pilot's wall time
and above by proportional scaling (fixed costs scaled too), times the declared
margin. With two or more pilot sizes a least-squares line wall = a + b * units
gives the central value; the upper bound is the larger of that and the most
conservative proportional scaling, times the margin.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys

from . import execution
from .state_io import read_json
from .cost_records import make_record, observation_profile, append_observation, catalogue_observations, aggregate_resources, resource_vector

# Spec fields a pilot may change relative to production (the pilot transformer):
# event counts, seeds, the batch of points (cost per point is assumed alike and
# the assumption is recorded), resource ceilings and prose.
SCOPED_VARIABLE = (("generation", "events"), ("generation", "seed"), ("generation", "parameter_points"),
                   ("max_seconds",), ("approval_mode",), ("source",), ("assumptions",))
MAX_MARGIN = 100.0


def machine_identity():
    u = os.uname()
    return {"system": u.sysname, "machine": u.machine, "hostname": u.nodename, "logical_cpus": os.cpu_count(),
            "platform": platform.platform()}


def _pin(path):
    path = Path(path).absolute()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}


def _without(spec, fields):
    copy = deepcopy(spec)
    for path in fields:
        target = copy
        for key in path[:-1]:
            target = target.get(key, {})
        if isinstance(target, dict):
            target.pop(path[-1], None)
    return copy


# Location spellings that differ between a source specification and its frozen
# plan; they are replaced by content identities in the profile.
SCOPED_LOCATIONS = (("generation", "runtime"), ("generation", "generator"), ("generation", "model_origin"),
                    ("generation", "lhe_transform"), ("generation", "parameter_card"), ("generation", "shower", "python"))


def _file_digest(value, base):
    path = Path(value)
    path = path if path.is_absolute() else Path(base) / path
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scoped_profile(spec, base):
    """Digest of everything that sets the cost of a scoped generation, except the pilot's free fields."""
    g = spec["generation"]
    identity = {}
    if "runtime" in g:
        from ravel.physics.generator_versions import runtime_version
        tree = Path(g["runtime"]["madgraph"])
        identity["madgraph"] = runtime_version(tree if tree.is_absolute() else Path(base) / tree)
    else:
        from ravel.physics import beam_content, generator_versions
        beams, _ = beam_content.content(g)
        chosen, _ = generator_versions.select(g["generator"]["version"], (beams or {}).get("minimum_generator_version"),
                                              generator_versions.installed_madgraph())
        identity["madgraph"] = chosen["version"]
    for key in ("parameter_card", "lhe_transform"):
        if key in g:
            identity[key] = _file_digest(g[key], base)
    if "model_origin" in g:
        handoff = json.loads((Path(g["model_origin"]) if Path(g["model_origin"]).is_absolute()
                              else Path(base) / g["model_origin"]).read_bytes())
        identity["model_origin"] = handoff["ufo_manifest"]["sha256"]
    return execution.digest({"spec": _without(spec, SCOPED_VARIABLE + SCOPED_LOCATIONS), "identity": identity})


def scaling(route, spec, base=None):
    """(unit, units of work, profile digest, varied-fields note) for a run specification."""
    if route == "scoped":
        if spec.get("mode") != "generate":
            raise ValueError("only scoped generation has a cost scaling unit")
        g = spec["generation"]
        points = len(g.get("parameter_points") or [None])
        profile = scoped_profile(spec, base)
        note = "events x points; points of one batch are assumed to cost alike" if points > 1 else "events"
        return "events", g["events"] * points, profile, note
    mode = spec.get("mode")
    if mode == "model-events":
        from .generation_efficiency import process_profile
        profile = process_profile(spec["task"], base)
        return "events", profile["events"], profile["profile_sha256"], "events of one model-events configuration"
    from .science import adapter
    module = adapter(spec)
    if not hasattr(module, "cost_units"):
        raise ValueError(f"science mode {mode} declares no cost scaling unit (cost_units)")
    unit, units, profile = module.cost_units(spec["task"], base)
    return unit, units, profile, f"{unit} declared by the {mode} adapter"


def _route(rd):
    if (rd / "inputs/scoped-plan.json").is_file():
        return "scoped"
    if (rd / "inputs/science-plan.json").is_file():
        return "science"
    raise ValueError(f"{rd} is neither a scoped nor a science run")


def _completed(rd, route):
    if route == "scoped":
        from . import scoped
        proposal = scoped.verify_plan(rd, require_approval=True)
        spec, base = read_json(rd / scoped.SPEC), rd
    else:
        from . import science
        proposal = science.verify_plan(rd, approved=True)
        spec, base = read_json(rd / science.SPEC), Path(proposal["base_dir"])
    errors = execution.validate_completed_execution(rd, proposal["stages"])
    if errors:
        raise ValueError("pilot did not complete; failed attempts are not cost evidence: " + "; ".join(errors))
    return proposal, spec, base


def _bytes(paths):
    total = 0
    for path in paths:
        path = Path(path)
        if path.is_file():
            total += path.stat().st_size
        elif path.is_dir():
            total += sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink())
    return total


def observe(rundir, *, catalogue=None):
    """Measured cost of a completed, approved pilot run on this machine."""
    rd = Path(rundir).absolute()
    route = _route(rd)
    proposal, spec, base = _completed(rd, route)
    unit, units, profile, note = scaling(route, spec, base)
    records = execution.load_execution(rd)["stages"]
    wall, platforms = 0.0, set()
    for stage in proposal["stages"]:
        record = records[stage["stage"]]
        elapsed = (datetime.fromisoformat(record["finished_utc"]) - datetime.fromisoformat(record["started_utc"])).total_seconds()
        if not math.isfinite(elapsed) or elapsed <= 0:
            raise ValueError(f"stage {stage['stage']} has no positive measured wall time")
        wall += elapsed
        platforms.add((record.get("runtime") or {}).get("platform"))
    here = machine_identity()
    if platforms != {here["platform"]}:
        raise ValueError(f"pilot ran on {sorted(map(str, platforms))}, not on this machine ({here['platform']})")
    outputs = [execution.resolve_path(rd, out, output=True) for stage in proposal["stages"] for out in stage["outputs"]]
    result = {"schema_version": 1, "kind": "supervised_pilot_observation", "rundir": str(rd), "route": route,
            "mode": spec.get("mode"), "unit": unit, "units": units, "scaling_note": note, "profile_sha256": profile,
            "wall_seconds": wall, "output_bytes": _bytes(outputs), "machine": here,
            "plan_sha256": execution.file_hash(rd / ("inputs/scoped-plan.json" if route == "scoped" else "inputs/science-plan.json")),
            "measurement": "supervisor stage start/finish times of the completed approved attempt",
            "receipts": [_pin(rd / records[s['stage']]['attempt_record']) for s in proposal['stages']]}
    measured = aggregate_resources([resource_vector(**records[s['stage']].get('resource_vector', {}))
                                    for s in proposal['stages']])
    measured.update(wall_hours=wall / 3600, disk_gb=result['output_bytes'] / 1e9,
                    events=units if unit == 'events' else None)
    result.update(make_record(_method_class(spec), 'calibrated', observation_profile(result), result['measurement'],
                             **measured))
    result['resource_scope'] = 'Stage elapsed duration and retained output footprint; other dimensions require explicit receipt measurements.'
    if catalogue is not None:
        append_observation(catalogue, result)
    return result



def _method_class(spec):
    decision = spec.get('method_decision') or {}
    return (decision.get('selected') or {}).get('method') or (
        'new_generation' if spec.get('mode') in ('generate', 'model-events') else 'unknown')


def forecast_from_catalogue(catalogue, target_spec, *, route, margin, base=None, ceiling_seconds=None):
    """Use only same-profile, same-machine completed observations."""
    _, _, profile, _ = scaling(route, target_spec, base)
    observations = catalogue_observations(catalogue, profile, machine_identity())
    return forecast(observations, target_spec, route=route, margin=margin, base=base,
                    ceiling_seconds=ceiling_seconds)

def forecast(observations, target_spec, *, route, margin, base=None, ceiling_seconds=None):
    """Scale pilot observations (dicts from ``observe``) to a target specification."""
    if type(margin) not in (int, float) or not math.isfinite(margin) or not 1 <= margin <= MAX_MARGIN:
        raise ValueError(f"declare a finite margin between 1 and {MAX_MARGIN:g}")
    if not observations:
        raise ValueError("at least one completed pilot is required; an uncalibrated plan stays refused for bulk launch")
    unit, units, profile, note = scaling(route, target_spec, base)
    if type(units) not in (int, float) or not math.isfinite(units) or units <= 0:
        raise ValueError('positive target scaling units required')
    if ceiling_seconds is not None and (type(ceiling_seconds) not in (int, float)
            or not math.isfinite(ceiling_seconds) or ceiling_seconds <= 0):
        raise ValueError('positive finite ceiling required')
    here = machine_identity()
    for obs in observations:
        if obs.get("kind") != "supervised_pilot_observation":
            raise ValueError("pilot observation record required")
        if any(type(obs.get(key)) not in (int, float) or not math.isfinite(obs[key]) or obs[key] <= 0
               for key in ('units', 'wall_seconds')):
            raise ValueError('positive measured pilot units and duration required')
        resource_vector(disk_gb=obs['output_bytes'] / 1e9)
        if obs["profile_sha256"] != profile:
            raise ValueError(f"pilot {obs['rundir']} differs from the target in more than events, seeds or points")
        if obs["unit"] != unit:
            raise ValueError("pilot and target scale in different units")
        if {k: obs["machine"][k] for k in ("system", "machine", "hostname", "logical_cpus")} != {
                k: here[k] for k in ("system", "machine", "hostname", "logical_cpus")}:
            raise ValueError(f"pilot {obs['rundir']} was measured on another machine")
        if obs["units"] > units:
            raise ValueError("a pilot larger than the target cannot calibrate it")
    proportional = [obs["wall_seconds"] * units / obs["units"] for obs in observations]
    sizes = sorted({obs["units"] for obs in observations})
    central, fit = max(o["wall_seconds"] for o in observations), None
    method = "single pilot size: lower bound is the pilot wall time, upper bound is proportional scaling"
    if len(sizes) >= 2:
        n = len(observations)
        mx = sum(o["units"] for o in observations) / n
        my = sum(o["wall_seconds"] for o in observations) / n
        sxx = sum((o["units"] - mx) ** 2 for o in observations)
        slope = sum((o["units"] - mx) * (o["wall_seconds"] - my) for o in observations) / sxx
        if slope > 0:
            intercept = my - slope * mx
            central = intercept + slope * units
            method = "least-squares line over pilot sizes " + ", ".join(map(str, sizes))
            fit = {"fixed_seconds": intercept, "seconds_per_unit": slope}
        else:
            method = ("pilot wall times do not resolve a per-unit cost (fixed costs dominate); "
                      "proportional scaling of every pilot bounds the forecast")
    lower = max(central, max(o["wall_seconds"] for o in observations))
    upper = margin * max(central, max(proportional))
    disk = margin * max(o["output_bytes"] * units / o["units"] for o in observations)
    decision = "fits_ceiling" if ceiling_seconds is None or upper <= ceiling_seconds else "exceeds_ceiling"
    result = {"schema_version": 1, "kind": "supervised_pilot_forecast", "route": route, "mode": target_spec.get("mode"),
            "unit": unit, "target_units": units, "scaling_note": note, "profile_sha256": profile,
            "pilots": [{"rundir": o["rundir"], "units": o["units"], "wall_seconds": o["wall_seconds"],
                        "output_bytes": o["output_bytes"], "plan_sha256": o["plan_sha256"]} for o in observations],
            "method": method, "fit": fit, "margin": margin, "wall_seconds": [lower, upper], "disk_bytes_peak": disk,
            "ceiling_seconds": ceiling_seconds, "decision": decision, "machine": here,
            "scope": "Local measured cost on this machine; not a guaranteed ceiling and not a physics result.",
            "execution_authorized": False}
    result.update(make_record(_method_class(target_spec), 'calibrated',
        {'process': target_spec.get('mode'), 'configuration': profile, 'machine': here}, method,
        wall_hours=lower / 3600, disk_gb=disk / 1e9, events=units if unit == 'events' else None,
        uncertainty={'wall_hours': [lower / 3600, upper / 3600]}))
    result['uncertainty_scope'] = 'Conservative pilot scaling bounds with declared margin; not a statistical confidence interval.'
    return result


def record(forecast_path, *, mode, points=1, parallel=1, events_per_point=None):
    """A schema-3 cost record (calibration_status measured) bound to a forecast file."""
    if mode not in ("smoke", "full", "scan"):
        raise ValueError("a measured cost record is for smoke, full or scan plans")
    pin = _pin(forecast_path)
    doc = json.loads(Path(forecast_path).read_bytes())
    if doc.get("kind") == "supervised_pilot_forecast":
        if doc["decision"] != "fits_ceiling":
            raise ValueError(f"the forecast {doc['wall_seconds'][1]:.0f} s exceeds the ceiling {doc['ceiling_seconds']} s; "
                             "replan the budget before approval")
        wall, disk, machine, pilots, unit = doc["wall_seconds"], doc["disk_bytes_peak"], doc["machine"], len(doc["pilots"]), doc["unit"]
        margin = doc["margin"]
    elif doc.get("kind") == "generation_empirical_forecast":
        if doc.get("decision") != "production_cost_forecast_available":
            raise ValueError("the generation forecast requires a budget replan")
        wall, disk, pilots, unit, margin = doc["forecast_seconds"], None, len(doc["pilots"]), "events", doc["wall_margin"]
        observed = doc["profile"]["machine"]
        machine = {"system": observed["system"], "machine": observed["machine"], "hostname": observed["hostname"],
                   "logical_cpus": observed["logical_cpus"], "platform": None}
    else:
        raise ValueError("unsupported forecast; produce one with `ravel pilot-cost forecast` or generation-efficiency")
    if parallel != 1:
        raise ValueError("one native job runs at a time on this machine; parallel must be 1")
    result = {"schema_version": 3, "generated_by": "cost_preflight.py", "generated_utc": execution.utc_now(),
            "mode": mode, "points": points, "events_per_point": events_per_point, "backend": "native", "parallel": 1,
            "calibration_status": "measured",
            "walltime_h": [wall[0] / 3600, wall[1] / 3600],
            "disk_gb_peak": None if disk is None else disk / 1e9,
            "basis": {"kind": doc["kind"], "forecast": pin, "unit": unit, "pilots": pilots,
                      "machine": machine, "margin": margin},
            "production_feasibility_established": False,
            "note": "Measured from completed pilots on this machine and scaled by the declared margin. "
                    "The supervisor still enforces the approved wall-time ceiling."}
    profile = doc.get('profile') if doc.get('kind') == 'supervised_pilot_forecast' else None
    if profile is None:
        profile = {'process': doc.get('mode'), 'configuration': doc.get('profile_sha256'), 'machine': machine}
    if doc.get('kind') == 'generation_empirical_forecast':
        profile = {'process': deepcopy((doc['profile'].get('protected') or {}).get('generation')),
                   'configuration': doc['profile'].get('profile_sha256'), 'machine': machine}
    resources = resource_vector(**doc.get('resource_vector', {}))
    resources.update(wall_hours=wall[0] / 3600, disk_gb=None if disk is None else disk / 1e9)
    if doc.get('kind') == 'generation_empirical_forecast':
        resources['events'] = doc['profile'].get('events')
    extra = make_record(doc.get('cost_class', 'single_point_chain' if mode != 'scan' else 'justified_scan'),
        'calibrated', profile, result['note'],
        uncertainty={'wall_hours': [wall[0] / 3600, wall[1] / 3600]}, **resources)
    # Keep the legacy approval basis object; richer records expose a prose basis separately.
    extra['forecast_basis'] = extra.pop('basis')
    result.update(extra)
    return result


def verify_record(budget):
    """Approval-time checks of a measured record: basis bytes unchanged, same machine."""
    if budget.get("schema_version") != 3:
        return []
    errors = []
    basis = budget.get("basis") or {}
    pin = basis.get("forecast") or {}
    try:
        if _pin(pin["path"]) != pin:
            errors.append("cost forecast basis changed since the cost record was written")
    except (OSError, KeyError, TypeError):
        errors.append("cost forecast basis is missing")
    here = machine_identity()
    machine = basis.get("machine") or {}
    if any(machine.get(k) != here[k] for k in ("system", "machine", "hostname", "logical_cpus")):
        errors.append("measured cost comes from another machine; measure a pilot here")
    if not errors and 'resource_vector' in budget:
        try:
            expected = record(pin['path'], mode=budget['mode'], points=budget['points'],
                              parallel=budget['parallel'], events_per_point=budget.get('events_per_point'))
            for key in ('cost_class', 'status', 'profile', 'resource_vector', 'uncertainty'):
                if budget.get(key) != expected[key]:
                    errors.append(f'cost {key} differs from its pinned forecast')
        except (OSError, KeyError, TypeError, ValueError) as exc:
            errors.append('cost forecast cannot reproduce the resource profile: ' + str(exc))
    return errors


def _write(value, destination):
    path = Path(destination).absolute()
    with path.open("x") as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + "\n")
    return _pin(path)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ravel pilot-cost",
                                     description="Measure completed pilots and forecast the cost of a larger run (no compute is launched).")
    sub = parser.add_subparsers(dest="action", required=True)
    obs = sub.add_parser("observe", help="record the measured cost of a completed approved pilot run")
    obs.add_argument("--rundir", required=True, type=Path)
    obs.add_argument("--output", required=True, type=Path)
    obs.add_argument("--catalogue", type=Path, help="append completed receipt-backed usage to a local catalogue")
    fc = sub.add_parser("forecast", help="scale pilot observations to a target specification")
    fc.add_argument("--pilot", action="append", type=Path, help="observation JSON (repeat)")
    fc.add_argument("--catalogue", type=Path, help="read matched completed observations from the catalogue")
    fc.add_argument("--target", required=True, type=Path, help="target scoped or science specification")
    fc.add_argument("--route", choices=("scoped", "science"), required=True)
    fc.add_argument("--margin", required=True, type=float)
    fc.add_argument("--ceiling-seconds", type=float)
    fc.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.action == "observe":
        print(json.dumps(_write(observe(args.rundir, catalogue=args.catalogue), args.output)))
        return 0
    target = read_json(args.target)
    if bool(args.pilot) == bool(args.catalogue):
        parser.error("choose --pilot or --catalogue")
    pilots = [read_json(p) for p in (args.pilot or [])]
    ceiling = args.ceiling_seconds if args.ceiling_seconds is not None else target.get("max_seconds")
    if args.catalogue:
        result = forecast_from_catalogue(args.catalogue, target, route=args.route, margin=args.margin,
                                        base=args.target.parent, ceiling_seconds=ceiling)
    else:
        result = forecast(pilots, target, route=args.route, margin=args.margin, base=args.target.parent,
                          ceiling_seconds=ceiling)
    print(json.dumps(_write(result, args.output)))
    return 0 if result["decision"] == "fits_ceiling" else 1


if __name__ == "__main__":
    sys.exit(main())
