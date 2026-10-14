#!/usr/bin/env python
"""Render supplied scan data with a declarative plot specification.

Axes bind to the supplied column schema. Layers, comparison populations, labels,
scales and exact output paths belong to the selected contract. Numerical helpers
retain limit statuses, masked lattice support and exact reference matching.
"""
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.plotting"

import argparse
import copy
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from ravel.limits import read_limits, point_value
from . import mplhep_style as house

LINT_ALLOW = False


class MissingLimitColumn(ValueError):
    """A table lacks the requested observed/expected column, rather than malformed data."""


def die(msg):
    sys.exit(f"scan_contour: {msg}")


def load_scan(path):
    if not os.path.exists(path):
        die(f"scan.json not found: {path} (run scan_orchestrator.py assemble first)")
    with open(path) as fh:
        try:
            scan = json.load(fh)
        except json.JSONDecodeError as e:
            die(f"scan.json invalid JSON ({e})")
    pts = scan.get("points")
    if not pts:
        die("scan.json has no points")
    for p in pts:
        for k in ("m_parent", "m_lsp", "dm"):
            if p.get(k) is None:
                die(f"scan point {p.get('tag')} missing '{k}'")
            value = p[k]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
                die(f"scan point {p.get('tag')} has nonfinite or nonnumeric '{k}'")
            if value < 0 or (k != "m_lsp" and value == 0):
                die(f"scan point {p.get('tag')} has nonphysical '{k}'")
        try:
            read_limits(p)
        except (ValueError, TypeError) as exc:
            die(f"scan point {p.get('tag')} has invalid observed/expected limit or band: {exc}")
        if not np.isclose(p["m_parent"] - p["m_lsp"], p["dm"], atol=1e-5, rtol=0):
            die(f"scan point {p.get('tag')} has inconsistent masses and splitting")
    if len({(p["m_parent"], p["dm"]) for p in pts}) != len(pts):
        die("scan.json has duplicate mass coordinates")
    flagged = [p.get("tag") for p in pts if p.get("quality")]
    if flagged:
        print(f"  note: {len(flagged)} scan point(s) carry a limit-quality flag (floored/capped: "
              f"bounds, not limits): {flagged}", file=sys.stderr)
    return scan


def _plot_value(point, kind="observed"):
    value = point_value(point, kind, allow_legacy=True)
    return value if value is not None else np.nan


def _legacy_note(scan):
    if any(any(c.status == "legacy_reported" for c in
               [read_limits(p).observed, *read_limits(p).expected]) for p in scan["points"]):
        return ["Historical reported limits; numerical root evidence unavailable"]
    return []


def _normalization_note(scan):
    """Annotation for the supplied basis transformation or correction recorded by the scan."""
    if scan.get("model_basis"):
        return r"$\mu$ on the supplied target $\sigma$ basis"
    if scan.get("normalization"):
        return r"signal $\sigma$: supplied correction contract"
    return None


def interp_crossing(xs, ys, level=1.0):
    """Return the sorted list of x where y crosses `level` (linear interpolation between samples)."""
    xs = np.asarray(xs, float); ys = np.asarray(ys, float)
    order = np.argsort(xs); xs, ys = xs[order], ys[order]
    out = []
    for i in range(len(xs) - 1):
        y0, y1 = ys[i] - level, ys[i + 1] - level
        if y0 == 0.0:
            out.append(xs[i])
        if y0 * y1 < 0:  # sign change -> a crossing in (xs[i], xs[i+1])
            t = y0 / (y0 - y1)
            out.append(xs[i] + t * (xs[i + 1] - xs[i]))
    if ys[-1] - level == 0.0:
        out.append(xs[-1])
    return sorted(out)


def excluded_intervals(dms, mu, level=1.0):
    """Return disjoint excluded spans; nonfinite values split support into pieces."""
    order = np.argsort(dms)
    x, y = np.asarray(dms, float)[order], np.asarray(mu, float)[order]
    if len(np.unique(x)) != len(x):
        raise ValueError("duplicate splitting coordinates in a line scan")
    spans = []
    for x0, x1, y0, y1 in zip(x[:-1], x[1:], y[:-1], y[1:]):
        if not np.isfinite(y0) or not np.isfinite(y1) or min(y0, y1) >= level:
            continue
        lo, hi = x0, x1
        if y0 >= level:
            lo = x0 + (level - y0) / (y1 - y0) * (x1 - x0)
        elif y1 >= level:
            hi = x0 + (level - y0) / (y1 - y0) * (x1 - x0)
        if spans and spans[-1][1] == lo:
            spans[-1] = (spans[-1][0], float(hi))
        else:
            spans.append((float(lo), float(hi)))
    return spans


def excluded_interval(dms, mu, level=1.0):
    """Compatibility helper for a genuinely single contiguous excluded interval."""
    spans = excluded_intervals(dms, mu, level)
    if len(spans) > 1:
        raise ValueError("exclusion is disconnected; use excluded_intervals")
    return spans[0] if spans else None


def setup(args):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    hep = house.apply_style(args.experiment)
    return plt, hep


def resolve_axis(flag, declared, default):
    """One axis's effective log state (True=log, False=linear). Precedence
    (plot-guidelines.md): explicit CLI flag (--logx/--linx/--logy/--liny) > the figure contract's
    declared PUBLISHED scale (--figure-target; the published scales are facts read at declaration)
    > the renderer's default. `flag` is True/False/None; `declared` is 'linear'/'log'/None."""
    if flag is not None:
        return bool(flag)
    if declared in ("linear", "log"):
        return declared == "log"
    return default


def header(ax, hep, args):
    # Experiment typography does not make this an experiment-authored result.
    # Keep the owner and beam/luminosity context visible with either style backend.
    ax.text(0, 1.015, f"RAVEL · {args.experiment}",
            transform=ax.transAxes, ha="left", va="bottom", fontsize=12)
    context = []
    if args.lumi is not None:
        context.append(rf"{args.lumi:g} fb$^{{-1}}$")
    if args.com is not None:
        context.append(f"({args.com:g} TeV)")
    if context:
        ax.text(1, 1.015, " ".join(context), transform=ax.transAxes,
                ha="right", va="bottom", fontsize=12)


def save(fig, outputs):
    """Write exactly the declared destinations and formats after layout validation."""
    house.enforce_lint(fig, where='supplied scan plot', allow=LINT_ALLOW)
    for output in outputs:
        path = Path(output['path']); path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, format=output['format'], dpi=200, bbox_inches='tight')



def atlas_dm_reach(atlas_contours, m_parent):
    """Largest exact polyline intersection at this mass, without nearest extrapolation."""
    intersections = []
    for role, path, x, y, xn, yn in atlas_contours:
        if not role.startswith("observed"):
            continue
        xx, yy = _orient_dm(x, y, xn, yn)
        for x0, x1, y0, y1 in zip(xx[:-1], xx[1:], yy[:-1], yy[1:]):
            if not all(np.isfinite(v) for v in (x0, x1, y0, y1)):
                continue
            if x0 == x1 == m_parent:
                intersections.extend([y0, y1])
            elif x0 != x1 and min(x0, x1) <= m_parent <= max(x0, x1):
                intersections.append(y0 + (m_parent - x0) / (x1 - x0) * (y1 - y0))
    return max(intersections) if intersections else None


def _has_contour(contour):
    """Matplotlib can return a nonempty list containing only empty segments."""
    return any(len(segment) >= 2 and np.all(np.isfinite(segment))
               for level in getattr(contour, "allsegs", []) for segment in level)


def _orient_dm(x, y, xn, yn):
    """Orient a HEPData contour polyline to (m, Delta m) from its variable headers: swap if x is the
    Delta m column; derive Delta m = m_parent - m_lsp if it is a mass-mass contour."""
    def is_dm(nm):
        return bool(nm) and ("delta" in nm.lower() or "\\Delta" in nm or "Δ" in nm)
    xx, yy = np.asarray(x, float), np.asarray(y, float)
    if is_dm(xn) and not is_dm(yn):
        xx, yy = yy, xx
    elif not is_dm(xn) and not is_dm(yn):
        yy = xx - yy
    return xx, yy


def _supported_triangulation(mpar, dm, z, logy=True):
    """Linear support on the observed rectangular lattice; missing vertices stay holes.

    Infill interior lattice holes from repeated mass/splitting axes, then mask
    triangles touching absent/invalid values. Removing bad points first would
    bridge holes. A rectangular completion outside the recorded convex hull would
    instead invent missing boundary sites and erase supported boundary triangles.
    One-off refinement coordinates do not create a whole missing row.
    """
    import matplotlib.tri as mtri
    mpar, dm, z = (np.asarray(v, float) for v in (mpar, dm, z))
    if not (mpar.ndim == dm.ndim == z.ndim == 1 and len(mpar) == len(dm) == len(z)):
        raise ValueError("contour coordinates and values must be equal-length vectors")
    if not np.all(np.isfinite(mpar)) or not np.all(np.isfinite(dm)) or (logy and np.any(dm <= 0)):
        raise ValueError("contour coordinates must be finite (and positive on a log axis)")
    coords = list(zip(mpar, dm))
    if len(set(coords)) != len(coords):
        raise ValueError("duplicate scan coordinates cannot define an unambiguous contour")
    xx, xcounts = np.unique(mpar, return_counts=True)
    yy, ycounts = np.unique(dm, return_counts=True)
    if len(xx) < 2 or len(yy) < 2:
        raise ValueError("contour needs at least two distinct coordinates on each axis")
    domain = mtri.Triangulation(mpar, np.log10(dm) if logy else dm).get_trifinder()
    interior_lattice = {(mass, split) for mass in xx[xcounts >= 2] for split in yy[ycounts >= 2]
                        if domain(mass, np.log10(split) if logy else split) >= 0}
    sites = sorted(set(coords) | interior_lattice)
    lookup = dict(zip(coords, z))
    values = np.array([lookup.get(site, np.nan) for site in sites])
    tri = mtri.Triangulation([site[0] for site in sites],
                             [np.log10(site[1]) if logy else site[1] for site in sites])
    tri.set_mask(~np.all(np.isfinite(values[tri.triangles]), axis=1))
    if np.all(tri.mask):
        raise ValueError("no triangle has three supported finite scan points")
    return tri, np.nan_to_num(values, nan=0.0)


def _smooth_field(mpar, dm, z, nx=200, ny=200, logy=True):
    """Piecewise linear field, masked outside supported triangles, without overshoot.

    A linear interpolant is bounded by its triangle's vertex values: it cannot
    invent a mu=1 crossing when all three limits lie on the same side of one.
    """
    import matplotlib.tri as mtri
    tri, values = _supported_triangulation(mpar, dm, z, logy=logy)
    Xi, Yi = np.meshgrid(np.linspace(tri.x.min(), tri.x.max(), nx),
                         np.linspace(tri.y.min(), tri.y.max(), ny))
    Zi = mtri.LinearTriInterpolator(tri, values)(Xi, Yi)
    return Xi, (10.0 ** Yi if logy else Yi), Zi


def comparison_data(scan, limit_grid, kind="observed"):
    """One accountable population for every quantitative reference comparison."""
    mu_key = {"observed": "mu95_obs", "expected": "mu95_exp"}[kind]
    records = []
    seen = set()
    for point in scan["points"]:
        record = {"tag": point.get("tag"), "m_parent": point.get("m_parent"),
                  "dm": point.get("dm"), "status": "eligible"}
        for coordinate_name in ("m_parent", "dm"):
            v = record[coordinate_name]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v):
                record[coordinate_name] = None
        reason = None
        try:
            limits = read_limits(point)
            curve = limits.curve(kind)
            record.update(limit_status=curve.status, limit_bracket=curve.to_dict()["bracket"],
                          limit_origin=limits.origin, historical_only=curve.status == "legacy_reported")
            if not curve.usable(allow_legacy=True):
                reason = "quality_flag"
        except (ValueError, TypeError) as exc:
            reason = "invalid_input"
            record["limit_error"] = str(exc)
        for key in ("m_parent", "dm", mu_key, "sigma_ref_fb"):
            value = point.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or value <= 0:
                reason = reason or "invalid_input"
        coordinate = (point.get("m_parent"), point.get("dm"))
        if coordinate in seen:
            raise ValueError(f"duplicate scan coordinate: {coordinate}")
        seen.add(coordinate)
        if reason:
            record["status"] = reason
        else:
            reference = _exact_grid_lookup(*limit_grid, [point["m_parent"]], [point["dm"]])[0]
            if not np.isfinite(reference):
                record["status"] = "unmatched_reference"
            else:
                prediction = point[mu_key] * point["sigma_ref_fb"]
                residual = prediction / reference - 1
                if not np.isfinite(prediction) or not np.isfinite(residual):
                    record["status"] = "invalid_input"
                else:
                    record.update(status="matched", reference_fb=float(reference),
                                  limit_fb=float(prediction), residual=float(residual))
        records.append(record)
    counts = {key: sum(r["status"] == key for r in records)
              for key in ("matched", "quality_flag", "invalid_input", "unmatched_reference")}
    planned = scan.get("n_planned", len(records))
    if isinstance(planned, bool) or not isinstance(planned, int) or planned < len(records):
        raise ValueError("n_planned must be an integer at least as large as the recorded population")
    residuals = [abs(r["residual"]) for r in records if r["status"] == "matched"]
    return {"schema_version": 1, "kind": kind, "planned": planned, "recorded": len(records),
            "missing_scan_points": planned - len(records), "counts": counts,
            "matched_fraction_of_plan": counts["matched"] / planned if planned else 0,
            "median_absolute_residual": float(np.median(residuals)) if residuals else None,
            "reference_matching": "exact, 0.05 GeV tolerance; no interpolation or extrapolation",
            "contour_interpolation": "piecewise linear; triangles touching unsupported lattice vertices masked",
            "records": records}


def read_limit_grid(path, kind="observed"):
    """Read a HEPData per-point upper-limit GRID (2 independent vars = the two masses; 1 dependent = the
    σ upper limit) into (m, dm, sigma_ul_fb). Orients to (mass, Δm) by the variable headers, picks the
    dependent column matching `kind` (LIKE-COLUMNS rule: 'observed' → the Observed UL, 'expected' → the
    Expected UL — compare like to like, never mixed), and converts σUL to fb from the dep header units
    (pb→×1000). General over any such HEPData table (e.g. ATLAS 'upper cross-section limits' figures)."""
    import yaml
    with open(path) as fh:
        doc = yaml.safe_load(fh)
    iv = doc.get("independent_variables", []) or []
    dv = doc.get("dependent_variables", []) or []
    if len(iv) != 2 or not dv:
        die(f"--atlas-limit {path}: expected a 2-D per-point limit grid (2 independent mass vars + a "
            f"dependent UL), got {len(iv)} indep / {len(dv)} dep. Pick the 'upper-cross-section-limits' "
            f"table (kind=limit in hepdata_manifest.json), not the exclusion-contour boundary.")

    def hdr(v):
        return v.get("header", {}) or {}

    def is_dm(v):
        nm = hdr(v).get("name", "") or ""
        return "delta" in nm.lower() or "\\Delta" in nm or "Δ" in nm
    key = {"observed": "observ", "expected": "expect"}[kind]
    candidates = [i for i, v in enumerate(dv) if key in (hdr(v).get("name", "") or "").lower()]
    if len(candidates) > 1:
        die(f"--atlas-limit {path}: ambiguous '{kind}' columns; select an explicit median-only table")
    di = candidates[0] if candidates else None
    if di is None:
        raise MissingLimitColumn(f"--atlas-limit {path}: no dependent column matching '{kind}' "
                                 f"(columns: {[hdr(v).get('name') for v in dv]})")
    for column in (*iv, dv[di]):
        for row in column.get("values", []):
            value = row.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                die(f"--atlas-limit {path}: grid values must be numbers, not booleans or strings")
    x0 = np.array([r["value"] for r in iv[0]["values"]], float)
    x1 = np.array([r["value"] for r in iv[1]["values"]], float)
    sig = np.array([r["value"] for r in dv[di]["values"]], float)
    if not (len(x0) == len(x1) == len(sig)) or not len(sig):
        die(f"--atlas-limit {path}: coordinate and limit columns must have equal nonzero lengths")
    if is_dm(iv[0]) and is_dm(iv[1]):
        die(f"--atlas-limit {path}: both independent variables identify a mass splitting")
    for column in iv:
        if (hdr(column).get("units", "") or "").lower() != "gev":
            die(f"--atlas-limit {path}: mass coordinate units must explicitly be GeV")
    m, dm = _orient_dm(x0, x1, hdr(iv[0]).get("name"), hdr(iv[1]).get("name"))
    units = (hdr(dv[di]).get("units", "") or "").lower()
    if units == "pb":
        sig = sig * 1000.0
    elif units != "fb":
        die(f"--atlas-limit {path}: unsupported or missing cross-section units '{units}'; require pb or fb")
    if not all(np.all(np.isfinite(v)) for v in (m, dm, sig)) or np.any(sig <= 0) or np.any(dm <= 0) or np.any(m <= 0):
        die(f"--atlas-limit {path}: masses, splittings and limits must be finite and positive")
    if np.any(dm > m):
        die(f"--atlas-limit {path}: splitting exceeds parent mass (negative daughter mass)")
    if len(set(zip(m, dm))) != len(m):
        die(f"--atlas-limit {path}: duplicate reference coordinates")
    return m, dm, sig


def _exact_grid_lookup(gx, gy, gz, qx, qy, atol=0.05):
    """EXACT (tolerance-snapped, default 0.05 GeV) lookup of a published per-point grid: NaN wherever
    the query is not a lattice point. The exact residual comparator uses this lookup — a published UL
    grid is a set of exact statements at its own lattice; interpolating (let alone nearest-neighbour
    extrapolating) a quantity that varies ~10x between adjacent Delta m rows fabricates reference
    values that were never published (never-interpolate-the-reference rule,
    docs/workflow/checklists/scan-and-contour.md)."""
    gx = np.asarray(gx, float); gy = np.asarray(gy, float); gz = np.asarray(gz, float)
    if not (len(gx) == len(gy) == len(gz)) or len(qx) != len(qy):
        raise ValueError("reference and query coordinates must have matching lengths")
    if not all(np.all(np.isfinite(v)) for v in (gx, gy, gz)) or np.any(gz <= 0):
        raise ValueError("reference grid must be finite with positive limits")
    out = np.full(len(qx), np.nan)
    for i, (x, y) in enumerate(zip(qx, qy)):
        hit = np.where((np.abs(gx - x) <= atol) & (np.abs(gy - y) <= atol))[0]
        if hit.size == 1:
            out[i] = gz[hit[0]]
        elif hit.size > 1:
            print(f"  (exact lookup: {hit.size} reference points within {atol} GeV of "
                  f"({x:g},{y:g}) -- ambiguous, leaving unmatched)")
    return out

class PlotInputError(ValueError):
    """Typed supplied-input refusal shared by plotting and comparison admission."""

    def __init__(self, field, code='missing_plot_input'):
        self.code = code
        self.field = field
        super().__init__(f'{code}: {field}')


def _required(document, field):
    if not isinstance(document, dict) or field not in document or document[field] is None:
        raise PlotInputError(field)
    return document[field]


def _finite(value, field, *, positive=False):
    if type(value) not in (int, float) or not np.isfinite(value) or (positive and value <= 0):
        raise PlotInputError(field, 'invalid_plot_input')
    return value


def validate_spec(scan, spec, comparison_axes=None):
    """Validate the whole input before creating artists or writing any output.

    The scan-axes interface is a column schema with quantity and unit per column;
    point records use those same literal column keys. No coordinate is inferred.
    """
    if _required(spec, 'schema_version') != 1:
        raise PlotInputError('schema_version', 'invalid_plot_input')
    axes = _required(spec, 'axes')
    if not isinstance(axes, dict) or set(axes) != {'x', 'y'}:
        raise PlotInputError('axes.x/y')
    columns = _required(_required(scan, 'data_schema'), 'columns')
    for key, axis in axes.items():
        for field in ('column', 'quantity', 'unit', 'label', 'scale'):
            value = _required(axis, field)
            if not isinstance(value, str) or (not value.strip() and field != 'unit'):
                raise PlotInputError(f'axes.{key}.{field}', 'invalid_plot_input')
        declared = columns.get(axis['column']) if isinstance(columns, dict) else None
        if not isinstance(declared, dict) or any(declared.get(k) != axis[k] for k in ('quantity', 'unit')):
            raise PlotInputError(f'axes.{key}', 'axis_schema_mismatch')
        if axis['scale'] not in ('linear', 'log'):
            raise PlotInputError(f'axes.{key}.scale', 'invalid_plot_input')
        if comparison_axes is not None:
            requested = comparison_axes[key]
            if any(requested.get(k) != axis[k] for k in ('quantity', 'unit', 'scale')):
                raise PlotInputError(f'comparison.axes.{key}', 'axis_schema_mismatch')
    points = _required(scan, 'points')
    if not isinstance(points, list) or not points:
        raise PlotInputError('points')
    coordinates = []
    for point in points:
        coordinates.append(tuple(_finite(_required(point, axes[k]['column']),
                                        axes[k]['column'], positive=axes[k]['scale'] == 'log')
                                 for k in ('x', 'y')))
        read_limits(point)
    if len(set(coordinates)) != len(coordinates):
        raise PlotInputError('duplicate scan coordinates', 'invalid_plot_input')
    planned = _required(scan, 'n_planned')
    if type(planned) is not int or planned < len(points):
        raise PlotInputError('n_planned', 'invalid_plot_input')
    presentation = _required(spec, 'presentation')
    experiment = _required(presentation, 'experiment')
    if not isinstance(experiment, str) or not experiment.strip():
        raise PlotInputError('presentation.experiment')
    for key in ('com', 'lumi'):
        _finite(_required(presentation, key), f'presentation.{key}', positive=True)
    outputs = _required(spec, 'outputs')
    if not isinstance(outputs, list) or not outputs:
        raise PlotInputError('outputs')
    paths = []
    for output in outputs:
        fmt, path = _required(output, 'format'), _required(output, 'path')
        if fmt not in ('png', 'pdf', 'svg') or not isinstance(path, str) or not path.strip():
            raise PlotInputError('output path/format', 'invalid_plot_input')
        if Path(path).suffix.lower() != '.' + fmt:
            raise PlotInputError('output extension differs from format', 'invalid_plot_input')
        paths.append(str(Path(path).resolve()))
    if len(set(paths)) != len(paths):
        raise PlotInputError('duplicate output paths', 'invalid_plot_input')
    layers = _required(spec, 'layers')
    if not isinstance(layers, list) or not layers:
        raise PlotInputError('layers')
    if comparison_axes is not None and not any(isinstance(layer, dict) and layer.get('kind') in ('reference-contour', 'residual') for layer in layers):
        raise PlotInputError('comparison reference layer')
    for layer in layers:
        kind = _required(layer, 'kind')
        label = _required(layer, 'label')
        if not isinstance(label, str) or not label.strip():
            raise PlotInputError('layer.label')
        if kind in ('points', 'contour', 'line', 'band', 'residual'):
            if _required(layer, 'quantity') not in ('observed', 'expected'):
                raise PlotInputError('layer.quantity', 'invalid_plot_input')
        if kind in ('line', 'band'):
            xs = [p[axes['x']['column']] for p in points]
            if len(set(xs)) != len(xs):
                raise PlotInputError('line requires one point per x coordinate', 'invalid_plot_input')
            if kind == 'line' and axes['y']['scale'] == 'log':
                values = [_plot_value(p, layer['quantity']) for p in points]
                if any(np.isfinite(v) and v <= 0 for v in values):
                    raise PlotInputError('line crosses zero on log axis', 'invalid_plot_input')
        if kind == 'contour':
            _finite(_required(layer, 'level'), 'contour.level')
        elif kind == 'band':
            indices = _required(layer, 'indices')
            if (not isinstance(indices, list) or len(indices) != 2
                    or any(type(i) is not int or not 0 <= i < 5 for i in indices) or indices[0] >= indices[1]):
                raise PlotInputError('band.indices', 'invalid_plot_input')
        elif kind in ('reference-contour', 'residual'):
            reference = _required(layer, 'reference')
            if _required(reference, 'quantity') != _required(layer, 'quantity'):
                raise PlotInputError('reference quantity differs from scan quantity', 'comparison_mismatch')
            if _required(reference, 'axes') != {k: {f: axes[k][f] for f in ('quantity', 'unit')} for k in axes}:
                raise PlotInputError('reference.axes', 'axis_schema_mismatch')
            rows = _required(reference, 'records')
            if not isinstance(rows, list) or not rows:
                raise PlotInputError('reference.records')
            refcoords = []
            for row in rows:
                refcoords.append(tuple(_finite(_required(row, k), f'reference.{k}',
                                              positive=axes[k]['scale'] == 'log') for k in ('x', 'y')))
            if len(set(refcoords)) != len(refcoords):
                raise PlotInputError('duplicate reference coordinates', 'invalid_plot_input')
            if _required(reference, 'basis') != _required(scan, 'model_basis'):
                raise PlotInputError('reference contour basis differs', 'comparison_mismatch')
            if kind == 'residual':
                _finite(_required(layer, 'match_tolerance'), 'match_tolerance')
                if layer['match_tolerance'] < 0:
                    raise PlotInputError('match_tolerance', 'invalid_plot_input')
                normalization = _required(layer, 'normalization')
                field = _required(normalization, 'field')
                basis = _required(scan, 'model_basis')
                if _required(reference, 'basis') != basis or _required(normalization, 'basis') != basis:
                    raise PlotInputError('comparison basis differs', 'comparison_mismatch')
                if _required(reference, 'unit') != _required(normalization, 'unit'):
                    raise PlotInputError('comparison units differ', 'comparison_mismatch')
                for point in points:
                    _finite(_required(point, field), field, positive=True)
                for row in rows:
                    _finite(_required(row, 'value'), 'reference.value', positive=True)
        elif kind not in ('points', 'line'):
            raise PlotInputError('unsupported layer kind', 'invalid_plot_input')
    return spec


def _residual_records(scan, spec, layer):
    axes = spec['axes']; reference = layer['reference']['records']
    grid = tuple([r[k] for r in reference] for k in ('x', 'y', 'value'))
    records = []
    for point in scan['points']:
        x, y = (point[axes[k]['column']] for k in ('x', 'y'))
        record = {'x': x, 'y': y, 'tag': point.get('tag')}
        mu = _plot_value(point, layer['quantity'])
        if not np.isfinite(mu):
            record['status'] = 'quality_flag'
        else:
            value = _exact_grid_lookup(*grid, [x], [y], atol=layer['match_tolerance'])[0]
            if not np.isfinite(value):
                record['status'] = 'unmatched_reference'
            else:
                with np.errstate(over='ignore', invalid='ignore'):
                    prediction = mu * point[layer['normalization']['field']]
                    residual = prediction / value - 1
                if not np.isfinite(prediction) or not np.isfinite(residual):
                    record['status'] = 'invalid_input'
                else:
                    record.update(status='matched', reference=value, prediction=prediction, residual=residual)
        records.append(record)
    return records


def render_spec(scan, spec, *, write=True):
    """Render a selected contract while preserving the caller's style context."""
    import matplotlib as mpl
    with mpl.rc_context():
        return _render_spec(scan, spec, write=write)


def _render_spec(scan, spec, *, write=True):
    """One renderer for supplied axes, complete populations and selected layers."""
    validate_spec(scan, spec)
    args = SimpleNamespace(**spec['presentation'])
    plt, hep = setup(args)
    fig, ax = plt.subplots(figsize=spec.get('figsize', (9, 7)))
    axes = spec['axes']; points = scan['points']
    x, y = (np.array([p[axes[k]['column']] for p in points], float) for k in ('x', 'y'))
    report = {'schema_version': 1, 'analysis_id': scan.get('analysis_id'), 'axes': copy.deepcopy(axes),
              'recorded': len(points), 'planned': scan['n_planned'],
              'missing_scan_points': scan['n_planned'] - len(points),
              'outputs': copy.deepcopy(spec['outputs']), 'layers': [],
              'population': [{'coordinates': {k: p[axes[k]['column']] for k in axes},
                              'tag': p.get('tag'), 'limits': read_limits(p).to_dict()} for p in points]}
    try:
        for layer in spec['layers']:
            kind = layer['kind']; result = {'kind': kind, 'label': layer['label']}
            color = layer.get('color', 'black')
            if kind == 'reference-contour':
                rows = layer['reference']['records']
                ax.plot([r['x'] for r in rows], [r['y'] for r in rows],
                        color=color, linestyle=layer.get('linestyle', '--'), label=layer['label'])
                result['records'] = copy.deepcopy(rows)
            else:
                mu = np.array([_plot_value(p, layer['quantity']) for p in points])
                valid = np.isfinite(mu); result['eligible'] = int(valid.sum())
                if kind in ('points', 'line') and not valid.any():
                    raise PlotInputError('no measured limits', 'invalid_plot_input')
                if kind == 'points':
                    artist = ax.scatter(x[valid], y[valid], c=mu[valid], cmap=layer.get('cmap', 'viridis'),
                                        label=layer['label'])
                    fig.colorbar(artist, ax=ax, label=layer['label'])
                    if (~valid).any():
                        ax.scatter(x[~valid], y[~valid], marker='x', color='0.5', label='Bounds or missing limits')
                elif kind in ('line', 'band'):
                    order = np.argsort(x)
                    if len(set(x)) != len(x):
                        raise PlotInputError('line requires one point per x coordinate', 'invalid_plot_input')
                    if kind == 'line':
                        ax.plot(x[order], mu[order], color=color, label=layer['label'])
                    else:
                        low, high = (np.array([_plot_value(p, i) for p in points]) for i in layer['indices'])
                        if axes['y']['scale'] == 'log' and any(np.any(v[np.isfinite(v)] <= 0) for v in (low, high)):
                            raise PlotInputError('band crosses zero on log axis', 'invalid_plot_input')
                        ax.fill_between(x[order], low[order], high[order], color=color,
                                        alpha=layer.get('alpha', .3), label=layer['label'])
                elif kind == 'contour':
                    tx = np.log10(x) if axes['x']['scale'] == 'log' else x
                    try:
                        tri, values = _supported_triangulation(tx, y, mu, logy=axes['y']['scale'] == 'log')
                    except ValueError as error:
                        result['unavailable'] = str(error)
                    else:
                        result['masked_triangles'] = int(np.count_nonzero(tri.mask))
                        # Triangulate in displayed coordinates; preserve the validated topology.
                        import matplotlib.tri as mtri
                        drawn = mtri.Triangulation(10 ** tri.x if axes['x']['scale'] == 'log' else tri.x,
                                                   10 ** tri.y if axes['y']['scale'] == 'log' else tri.y,
                                                   triangles=tri.triangles, mask=tri.mask)
                        if np.nanmin(mu) <= layer['level'] <= np.nanmax(mu):
                            contour = ax.tricontour(drawn, values, levels=[layer['level']], colors=[color])
                            result['drawn'] = _has_contour(contour)
                            if result['drawn']:
                                ax.plot([], [], color=color, label=layer['label'])
                        else:
                            result['drawn'] = False
                elif kind == 'residual':
                    records = _residual_records(scan, spec, layer); result['records'] = records
                    matched = [r for r in records if r['status'] == 'matched']
                    result['counts'] = {status: sum(r['status'] == status for r in records)
                                        for status in ('matched', 'quality_flag', 'unmatched_reference', 'invalid_input')}
                    result['matched_fraction_of_plan'] = len(matched) / scan['n_planned']
                    if matched:
                        artist = ax.scatter([r['x'] for r in matched], [r['y'] for r in matched],
                                            c=[r['residual'] for r in matched], cmap=layer.get('cmap', 'coolwarm'),
                                            label=layer['label'], vmin=layer.get('vmin'), vmax=layer.get('vmax'))
                        fig.colorbar(artist, ax=ax, label=layer['label'])
                    result['median_absolute_residual'] = float(np.median([abs(r['residual']) for r in matched])) if matched else None
            report['layers'].append(result)
        for key in axes:
            axis = axes[key]
            getattr(ax, 'set_' + key + 'label')(axis['label'])
            getattr(ax, 'set_' + key + 'scale')(axis['scale'])
        # Contour artists set sticky boundaries; retain complete endpoint markers.
        ax.use_sticky_edges = False
        ax.margins(x=.05, y=.05)
        header(ax, hep, args)
        handles, _ = ax.get_legend_handles_labels()
        if handles:
            ax.legend(loc='upper center', bbox_to_anchor=(.5, -.16), fontsize=10)
        fig.subplots_adjust(bottom=.30, top=.88)
        notes = [str(scan.get('analysis_id') or 'Supplied scan'),
                 f"{len(points)}/{scan['n_planned']} recorded points",
                 'Bounds excluded from numerical layers', *_legacy_note(scan)]
        for layer in report['layers']:
            if layer.get('unavailable'):
                notes.append(layer['label'] + ': ' + layer['unavailable'])
            if 'counts' in layer:
                notes.append(layer['label'] + ': ' + ', '.join(f"{key.replace('_', ' ')}={value}" for key, value in layer['counts'].items()))
        fig.text(.1, .02, '\n'.join(notes), fontsize=9, va='bottom')
        if write:
            save(fig, spec['outputs'])
        return report
    finally:
        plt.close(fig)


def render_line(scan, reference_contours, args):
    """Compatibility call requiring the same explicitly supplied specification."""
    spec = getattr(args, 'plot_spec', None)
    if spec is None:
        raise PlotInputError('plot_spec')
    return render_spec(scan, spec)


def render_grid(scan, reference_contours, args):
    """Compatibility call requiring the same explicitly supplied specification."""
    return render_line(scan, reference_contours, args)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scan', required=True, help='supplied point records and data_schema.columns')
    parser.add_argument('--plot-spec', type=Path, help='required declarative plot contract JSON')
    parser.add_argument('--experiment', required=True)
    parser.add_argument('--com', required=True, type=float)
    parser.add_argument('--lumi', required=True, type=float)
    parser.add_argument('--out', help='compatibility argument; output paths are selected in --plot-spec')
    parser.add_argument('--no-lint', action='store_true')
    args, unknown = parser.parse_known_args(argv)
    if args.plot_spec is None:
        raise PlotInputError('plot_spec')
    if unknown:
        raise PlotInputError('unsupported arguments: ' + ' '.join(unknown), 'invalid_plot_input')
    spec = json.loads(args.plot_spec.read_text())
    scan = json.loads(Path(args.scan).read_text())
    inputs = {Path(args.scan).resolve(), args.plot_spec.resolve()}
    for output in spec.get('outputs', []):
        if isinstance(output, dict) and isinstance(output.get('path'), str) and Path(output['path']).resolve() in inputs:
            raise PlotInputError(output['path'], 'input_output_collision')
    if spec.get('presentation') != {k: getattr(args, k) for k in ('experiment', 'com', 'lumi')}:
        raise PlotInputError('CLI and plot presentation differ', 'comparison_mismatch')
    global LINT_ALLOW
    LINT_ALLOW = args.no_lint
    report = render_spec(scan, spec)
    print(json.dumps(report, allow_nan=False))
    return report


if __name__ == '__main__':
    main()
