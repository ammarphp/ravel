"""Scan fan-out and population equality against the approved grid (P04, E24, G12, SW33; E21-E23).

The scan route plans one governed step per approved grid point (``parameters.adapter ==
"scan.point"``, ``parameters.point_id``), so each point runs as its own ``controller.step``
invocation with its own authority check, receipts and failure status, and one assembly step
(``scan.assemble``) that consumes the completed points. The approved grid is pinned in the plan
(``parameters.grid``: axes, point ids and digest), so CHECK-IN 1 and the CHECK-IN 2 GO bind it.

Population equality is checked three ways, never by inspecting only what was reported:

- plan membership: every approved point has exactly one point step with the approved coordinates,
  and no point step lies outside the grid;
- run population: every approved point is completed or an explicit hole with its failure status;
- assembled population: the assembled document lists every approved point exactly once with the
  status the controller observed, claims no completed point the controller did not see complete,
  lists no unmanifested point, and never claims full coverage while a hole exists.
"""
from __future__ import annotations

from copy import deepcopy

from . import common
from .common import error

POINT = "scan.point"
ASSEMBLE = "scan.assemble"
TERMINAL_FAILURES = ("failed", "held", "escalated", "budget_exhausted", "stopped", "skipped")


def approved_grid(plan) -> dict | None:
    """The grid the plan pins (``parameters.grid``), or None for a plan without a scan."""
    found = ((plan or {}).get("parameters") or {}).get("grid")
    return found if isinstance(found, dict) else None


def point_of(step) -> tuple:
    """``(point id, coordinates)`` of a scan point step (the compiler's ``parameters.item`` or ``point``)."""
    params = (step or {}).get("parameters") or {}
    item = params.get("item") if isinstance(params.get("item"), dict) else {}
    point_id = params.get("point_id") or item.get("id")
    coordinates = params.get("point") if isinstance(params.get("point"), dict) else item.get("parameters")
    return (str(point_id) if point_id is not None else None), coordinates


def point_steps(plan) -> dict:
    """``point id -> [plan steps]`` for every scan point step of the plan."""
    found = {}
    for step in (plan or {}).get("steps") or ():
        params = step.get("parameters") or {}
        if params.get("adapter") == POINT:
            found.setdefault(str(point_of(step)[0]), []).append(step)
    return found


def assembly_steps(plan) -> list:
    return [s for s in (plan or {}).get("steps") or () if (s.get("parameters") or {}).get("adapter") == ASSEMBLE]


def population_holes(expected, actual) -> list:
    """Members of ``expected`` that ``actual`` lacks, with multiplicity (the ledger's population equality)."""
    ledger = common.ledger()
    if ledger is not None:
        return list(ledger.population_equality(list(expected), list(actual)))
    remaining = {}
    for item in actual:
        remaining[item] = remaining.get(item, 0) + 1
    holes = []
    for item in expected:
        if remaining.get(item, 0) > 0:
            remaining[item] -= 1
        else:
            holes.append(item)
    return holes


def _duplicates(items) -> list:
    seen, repeated = set(), []
    for item in items:
        if item in seen and item not in repeated:
            repeated.append(item)
        seen.add(item)
    return repeated


def membership_errors(plan, *, gate=None) -> list:
    """The plan's point steps against its pinned grid (G12 at plan time)."""
    grid = approved_grid(plan)
    steps = point_steps(plan)
    if grid is None:
        if steps:
            return [error("scan_grid_unpinned", "the plan has scan point steps but pins no approved grid", gate=gate,
                          row="G12")]
        return []
    if not grid.get("complete") or not grid.get("points"):
        problems = "; ".join(grid.get("problems") or ["the grid has no points"])
        return [error("scan_grid_open", f"the scan grid is not fixed: {problems}", gate=gate, row="E24",
                      fix="fix the grid from the request or a cited source before CHECK-IN 1")]
    expected = [p["id"] for p in grid["points"]]
    errors = []
    if common.digest({"axes": grid.get("axes"), "points": expected}) != grid.get("sha256"):
        errors.append(error("scan_grid_digest", "the pinned grid does not match its digest", gate=gate, row="G12"))
    holes = population_holes(expected, list(steps))
    extras = [p for p in steps if p not in expected]
    repeated = sorted(p for p, rows in steps.items() if len(rows) > 1)
    if holes:
        errors.append(error("scan_point_unplanned", f"{len(holes)} approved point(s) have no point step: "
                            + ", ".join(holes[:20]), gate=gate, row="SW33", pins=holes[:50]))
    if extras:
        errors.append(error("scan_point_unmanifested", "point steps outside the approved grid: "
                            + ", ".join(extras[:20]), gate=gate, row="G12", pins=extras[:50]))
    if repeated:
        errors.append(error("scan_point_duplicate", "points planned more than once: " + ", ".join(repeated[:20]),
                            gate=gate, row="G12", pins=repeated[:50]))
    by_id = {p["id"]: p.get("parameters") for p in grid["points"]}
    for point_id, rows in steps.items():
        for step in rows:
            if point_id in by_id and point_of(step)[1] != by_id[point_id]:
                errors.append(error("scan_point_coordinates", f"step {step['id']} does not carry the approved "
                                    f"coordinates of {point_id}", gate=gate, row="G12", step=step["id"]))
            if step.get("rung") != "scan":
                errors.append(error("scan_point_rung", f"point step {step['id']} is at rung {step.get('rung')}, not "
                                    "scan", gate=gate, row="E21", step=step["id"]))
    return errors


def population(plan, context) -> dict:
    """The run population of the approved grid from the controller's own step states."""
    grid = approved_grid(plan) or {}
    expected = [p["id"] for p in grid.get("points") or ()]
    steps = point_steps(plan)
    rows, completed, failed, pending = [], [], [], []
    for point_id in expected:
        candidates = steps.get(point_id) or []
        status = common.step_status(context, candidates[0]["id"]) if len(candidates) == 1 else None
        row = {"point": point_id, "step": candidates[0]["id"] if len(candidates) == 1 else None,
               "status": status or "pending"}
        state = common.state_steps(context).get(row["step"]) if row["step"] else None
        if isinstance(state, dict):
            row["reason"] = state.get("reason")
            row["receipts"] = list(state.get("receipts") or [])
            row["attempts"] = state.get("attempts")
        rows.append(row)
        (completed if status == "completed" else failed if status in TERMINAL_FAILURES else pending).append(point_id)
    return {"grid_sha256": grid.get("sha256"), "expected": expected, "completed": completed, "failed": failed,
            "pending": pending, "holes": [p for p in expected if p not in completed], "rows": rows}


def _population_rows(document):
    rows = document.get("point_population") if isinstance(document, dict) else None
    return rows if isinstance(rows, list) else None


def assembled_errors(document, plan, context, *, step_id=None, gate=None) -> list:
    """The assembled scan document against the approved grid and the controller-observed point statuses."""
    grid = approved_grid(plan)
    if grid is None or not grid.get("points"):
        return [error("scan_grid_unpinned", "the assembly has no approved grid to check against", gate=gate,
                      row="SW33", step=step_id)]
    expected = [p["id"] for p in grid["points"]]
    by_id = {p["id"]: p.get("parameters") for p in grid["points"]}
    run = population(plan, context)
    rows = _population_rows(document)
    if rows is None:
        return [error("scan_population_missing", "the assembled scan lists no point_population; every approved "
                      "point must appear with its status", gate=gate, row="SW33", step=step_id)]
    tags = [r.get("tag") for r in rows if isinstance(r, dict)]
    errors = []
    if len(tags) != len(rows) or not all(isinstance(t, str) for t in tags):
        errors.append(error("scan_population_invalid", "every population row names its point tag", gate=gate,
                            row="SW33", step=step_id))
        tags = [t for t in tags if isinstance(t, str)]
    holes = population_holes(expected, tags)
    extras = [t for t in tags if t not in by_id]
    repeated = _duplicates(tags)
    if holes:
        errors.append(error("scan_point_omitted", f"{len(holes)} approved point(s) are missing from the assembled "
                            "population: " + ", ".join(holes[:20]), gate=gate, row="SW33", step=step_id,
                            pins=holes[:50], fix="list every approved point; a point that did not complete stays "
                            "an explicit hole with its failure status"))
    if extras:
        errors.append(error("scan_point_unmanifested", "the assembly lists points outside the approved grid: "
                            + ", ".join(extras[:20]), gate=gate, row="G12", step=step_id, pins=extras[:50]))
    if repeated:
        errors.append(error("scan_point_duplicate", "the assembly lists points twice: " + ", ".join(repeated[:20]),
                            gate=gate, row="G12", step=step_id, pins=repeated[:50]))
    observed = {r["point"]: r["status"] for r in run["rows"]}
    for row in rows:
        if not isinstance(row, dict) or row.get("tag") not in by_id:
            continue
        tag = row["tag"]
        if isinstance(row.get("parameters"), dict) and row["parameters"] and row["parameters"] != by_id[tag]:
            errors.append(error("scan_point_coordinates", f"the assembly gives {tag} other coordinates than the "
                                "approved grid", gate=gate, row="G12", step=step_id, pins=[tag]))
        claimed = row.get("status")
        if claimed != observed.get(tag) and claimed != "completed" and observed.get(tag) != "completed":
            errors.append(error("scan_point_status", f"the assembly reports {tag} as {claimed!r}; the controller "
                                f"observed {observed.get(tag)!r}", gate=gate, row="SW33", step=step_id, pins=[tag]))
        if claimed == "completed" and observed.get(tag) != "completed":
            errors.append(error("scan_point_substituted", f"the assembly claims {tag} completed but the controller "
                                f"observed {observed.get(tag) or 'no completed point step'}", gate=gate, row="G12",
                                step=step_id, pins=[tag]))
        if claimed != "completed" and observed.get(tag) == "completed":
            errors.append(error("scan_point_dropped", f"the assembly drops the completed point {tag} as {claimed}",
                                gate=gate, row="SW33", step=step_id, pins=[tag]))
    result_tags = [r.get("tag") for r in (document.get("points") or []) if isinstance(r, dict)]
    completed = [p for p in expected if observed.get(p) == "completed"]
    result_holes = population_holes(completed, [t for t in result_tags if isinstance(t, str)])
    if result_holes or _duplicates([t for t in result_tags if isinstance(t, str)]):
        errors.append(error("scan_results_population", "result rows must list every completed approved point "
                            "exactly once", gate=gate, row="SW33", step=step_id, pins=result_holes[:50]))
    stray = [t for t in result_tags if observed.get(t) != "completed"]
    if stray:
        errors.append(error("scan_result_unobserved", "result rows for points the controller did not see complete: "
                            + ", ".join(sorted(set(map(str, stray)))[:20]), gate=gate, row="G12", step=step_id))
    missing = [p for p in expected if observed.get(p) != "completed"]
    for name, count in (("n_planned", len(expected)), ("n_done", len(completed)), ("n_missing", len(missing))):
        if name in document and (type(document[name]) is not int or document[name] != count):
            errors.append(error("scan_population_count", f"{name} is {document[name]!r}; controller population "
                                f"requires {count}", gate=gate, row="E24", step=step_id))
    if document.get("n_missing") == 0 and missing:
        errors.append(error("scan_coverage_overclaimed", f"the assembly claims full coverage with {len(missing)} "
                            "hole(s)", gate=gate, row="E24", step=step_id, pins=missing[:50]))
    if isinstance(document.get("missing_tags"), list) and sorted(map(str, document["missing_tags"])) != \
            sorted(p for p in expected if p not in [r.get("tag") for r in rows if isinstance(r, dict)
                                                     and r.get("status") == "completed"]):
        errors.append(error("scan_missing_tags", "missing_tags differs from the population's non-completed points",
                            gate=gate, row="E24", step=step_id))
    return errors


def point_errors(step, outcome, plan, *, gate=None) -> list:
    """One point step's membership in the approved grid (checked when its outcome is joined)."""
    grid = approved_grid(plan) or {}
    params = step.get("parameters") or {}
    by_id = {p["id"]: p.get("parameters") for p in grid.get("points") or ()}
    point_id, coordinates = point_of(step)
    if point_id not in by_id:
        return [error("scan_point_unmanifested", f"step {step['id']} runs point {point_id}, which the approved grid "
                      "does not contain", gate=gate, row="G12", step=step["id"])]
    if coordinates != by_id[point_id]:
        return [error("scan_point_coordinates", f"step {step['id']} carries other coordinates than the approved "
                      f"point {point_id}", gate=gate, row="G12", step=step["id"])]
    if params.get("grid_sha256") not in (None, grid.get("sha256")):
        return [error("scan_grid_changed", f"step {step['id']} names another grid than the approved one", gate=gate,
                      row="G12", step=step["id"])]
    return []


def hole_reason(point_id, status, reason) -> str:
    """The recorded reason of a point that did not complete: it stays an explicit hole of the approved grid."""
    return f"point {point_id} {status}: {reason or 'no reason recorded'}; explicit hole in the approved grid"


def point_evidence(store, plan, step, outcome) -> dict:
    """What the controller retains for one point: membership, authority, receipts and status (P04)."""
    point_id, coordinates = point_of(step)
    grid = approved_grid(plan) or {}
    from . import checkins
    authority = [checkins.latest_authority(store, kind, plan=plan) for kind in ("approve_plan", "go")]
    launches = [r.get("_record_id") for r in common.records(store, common.LAUNCH) if r.get("step_id") == step["id"]]
    return {"point": point_id, "step": step["id"], "grid_sha256": grid.get("sha256"),
            "parameters": deepcopy(coordinates), "status": (outcome or {}).get("status"),
            "reason": (outcome or {}).get("reason"), "receipts": list((outcome or {}).get("receipts") or []),
            "authority": [a for a in authority if a], "launches": [l for l in launches if l],
            "effect_checks": [r for r in common.records(store, "step-authority")
                              if r.get("step_id") == step["id"] and r.get("point") == point_id
                              and r.get("plan_sha256") == plan.get("sha256")]}
