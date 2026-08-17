#!/usr/bin/env python3
"""effmap_fold -- per-object efficiency-map folding (step 4 . Option D2, the LLP/no-Delphes route).

The route for objects the standard chain cannot reconstruct (long-lived/displaced -- physics trap
T2) and for routine-less fast recasts: instead of simulating detector response, fold the
analysis's PUBLISHED per-object efficiency maps (HEPData-style YAML/JSON binned grids) over
truth-level objects. Per-event weight = prod over folded objects of eps(object) x the upstream
truth-selection flag; per-SR expected yield = sigma_pb x 1000 x lumi_fb x <weight> (generator
weights honoured when present). A per-event weights file is written for downstream pyhf counting
(pyhf_exclude.py counting mode).

Scope and failure modes (what this tool refuses to do):
  * NO extrapolation. A lookup outside any axis's validity envelope returns None -- never clamped
    to the nearest bin, never silently zeroed at lookup level. The affected event folds to
    weight 0 (conservative UNDER-coverage, the SModelS convention) and every exclusion is
    COUNTED and REPORTED loudly, per axis and per map.
  * NO silent holes. An in-envelope query falling in a gap of a sparse grid is counted
    separately ('in-range-hole'), as are grid rows dropped at load for non-numeric efficiency
    values. Overlapping grid rows are a map defect and abort the run.
  * NO physics selection of its own. Contract: upstream truth code decides WHICH objects enter
    the product (the event's "objects" list carries exactly those) and precomputes the per-event
    truth-selection verdict ("selected"). Object kinds absent from the fold spec are ignored and
    counted loudly; events with zero folded objects are counted loudly (their weight is the bare
    selection flag).
  * NO validation bypass. Every non-selftest run prints the R5 gate (verification-ladder R5;
    effmap-folding.md D2 step 4): no reinterpretation ships until this tool reproduces the
    target analysis's own published limit at >=2 published points within the map's documented
    accuracy.
  * Map-value uncertainties are NOT propagated; the map's documented accuracy (template:
    ATLAS-EXOT-2019-23's ~25%) enters the result as a systematic, stated with the deliverable.
    Efficiencies > 1 draw a LOUD warning (percent-unit maps must be converted upstream -- this
    tool never rescales silently).

Map format (HEPData table export, YAML or JSON): a dict with 'independent_variables' (one entry
per axis: 'header' {name, units} + per-ROW 'values' carrying {low, high} bin edges, or point
{'value': v} entries from which edges are synthesized at midpoints between the sorted unique
values) and 'dependent_variables' (the efficiency; pick one with --dep or the spec's
'dependent_variable' when a table carries several). Every axis lists one entry per grid row (the
HEPData row-wise convention: len(axis.values) == len(dep.values)); 1-D..N-D grids supported
(exercised 1-D..3-D). Bins are half-open [low, high), the last bin of each axis closed.

Events file: JSONL (one JSON object per line) or a JSON list (or {"events": [...]}) of
  {"objects": [{"kind": "muon", "pt": 43.1, "abseta": 1.2, ...}, ...],
   "weight": 1.0,           # optional generator weight (default 1.0)
   "selected": true}        # optional upstream truth-selection verdict (default true)

Fold spec (YAML or JSON; 'file' paths resolve relative to the spec file's directory):
  {"sr_name": "SR-displaced-...",
   "maps":    {"mu2d": {"file": "muon_eff.yaml", "dependent_variable": 0}},
   "objects": {"muon": {"map": "mu2d", "axes": ["pt", "abseta"]}}}
'axes' is positional (the object attribute feeding each map axis, in map-axis order) or a dict
keyed by map axis header name. Run `inspect --map` first to see a map's axes/binning/envelope.

Usage:
  effmap_fold.py --selftest [--workdir DIR] [--keep]
  effmap_fold.py inspect --map MAP.yaml [--dep 0]
  effmap_fold.py fold --events EV.jsonl --spec SPEC.json --sigma-pb X --lumi-fb X --out DIR
                      [--sr-name NAME]

Stdlib + numpy + yaml only; no network, no ssl. Fail-loud: structural defects (schema errors,
overlapping/degenerate bins, missing attributes, NaN kinematics) exit non-zero naming the
offending row/event; data anomalies (envelope exclusions, ignored kinds, zero-object events)
never exit but are always counted and reported.
"""
import argparse
import datetime
import json
import math
import os
import re
import shutil
import sys
import tempfile

import numpy as np
import yaml

R5_GATE = """\
+------------------------------------------------------------------------------+
| R5 VALIDATION GATE (verification-ladder R5 ; effmap-folding.md D2 step 4)    |
| NO reinterpretation ships until this tool reproduces the target LLP          |
| analysis's OWN published limit at >= 2 published points within the map's     |
| documented accuracy. Record the map version + validity envelope in the       |
| basis manifest; envelope-excluded points are flagged, never extrapolated.    |
+------------------------------------------------------------------------------+"""


def die(msg):
    sys.exit(f"effmap_fold: ERROR: {msg}")


# --------------------------------------------------------------------------- #
# map reader + envelope-honest lookup
# --------------------------------------------------------------------------- #
class EffMap:
    """One HEPData-style row-wise binned efficiency grid.

    lookup(coords) -> (value, None) inside the envelope, (None, reason) outside it, where
    reason is 'below-min:<axis>' / 'above-max:<axis>' / 'in-range-hole' / 'nan:<axis>'.
    Never clamps, never extrapolates, never returns 0 for an unmapped point.
    """

    def __init__(self, name, source, axis_names, axis_units, lows, highs, eff, holes_dropped):
        self.name = name
        self.source = source
        self.axis_names = axis_names
        self.axis_units = axis_units
        self.lows = lows        # per axis: float64 array of len n_rows
        self.highs = highs
        self.eff = eff          # float64 array of len n_rows
        self.ndim = len(axis_names)
        self.n_rows = int(eff.size)
        self.axis_min = [float(l.min()) for l in lows]
        self.axis_max = [float(h.max()) for h in highs]
        self.holes_dropped = holes_dropped

    # -- construction ------------------------------------------------------- #
    @classmethod
    def from_file(cls, path, dep=0, name=None):
        if not os.path.exists(path):
            die(f"map file not found: {path}")
        text = open(path).read()
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            try:
                doc = yaml.safe_load(text)
            except yaml.YAMLError as e:
                die(f"map file {path}: neither JSON nor YAML ({e})")
        if not isinstance(doc, dict):
            die(f"map file {path}: top level must be a dict with independent_variables/"
                f"dependent_variables (got {type(doc).__name__})")
        for key in ("independent_variables", "dependent_variables"):
            if key not in doc or not doc[key]:
                die(f"map file {path}: missing/empty '{key}'")
        indep = doc["independent_variables"]
        deps = doc["dependent_variables"]

        # pick the dependent variable (index or header-name match)
        dep_names = [str((d.get("header") or {}).get("name", f"dep{i}"))
                     for i, d in enumerate(deps)]
        if isinstance(dep, str) and dep.lstrip("-").isdigit():
            dep = int(dep)
        if isinstance(dep, int):
            if not 0 <= dep < len(deps):
                die(f"map file {path}: dependent_variable index {dep} out of range "
                    f"(have {len(deps)}: {dep_names})")
            dvar, dname = deps[dep], dep_names[dep]
        else:
            hits = [i for i, n in enumerate(dep_names) if _norm(n) == _norm(str(dep))]
            if len(hits) != 1:
                die(f"map file {path}: dependent_variable '{dep}' matches {len(hits)} of "
                    f"{dep_names} -- pick by index")
            dvar, dname = deps[hits[0]], dep_names[hits[0]]
        if len(deps) > 1:
            print(f"effmap_fold: note: map {path} has {len(deps)} dependent variables "
                  f"{dep_names}; using '{dname}'")

        n_rows = len(dvar.get("values") or [])
        if n_rows == 0:
            die(f"map file {path}: dependent variable '{dname}' has no values")

        # efficiency column; non-numeric entries (None, '-', '<0.01', ...) become dropped holes
        eff, keep = np.empty(n_rows), np.ones(n_rows, bool)
        for i, v in enumerate(dvar["values"]):
            raw = v.get("value") if isinstance(v, dict) else v
            try:
                eff[i] = float(raw)
            except (TypeError, ValueError):
                keep[i] = False

        axis_names, axis_units, lows, highs = [], [], [], []
        for a, ivar in enumerate(indep):
            hdr = ivar.get("header") or {}
            aname = str(hdr.get("name", f"axis{a}"))
            vals = ivar.get("values") or []
            if len(vals) != n_rows:
                die(f"map file {path}: axis '{aname}' has {len(vals)} rows but the dependent "
                    f"variable has {n_rows} (HEPData row-wise convention violated)")
            lo, hi = cls._axis_edges(path, aname, vals)
            axis_names.append(aname)
            axis_units.append(str(hdr.get("units", "") or ""))
            lows.append(lo)
            highs.append(hi)

        n_holes = int((~keep).sum())
        if n_holes:
            print(f"effmap_fold: NOTE: map {path}: {n_holes}/{n_rows} rows carry a non-numeric "
                  f"efficiency -> dropped as unmapped holes (in-envelope queries hitting them "
                  f"count as 'in-range-hole', never 0)")
        eff = eff[keep]
        lows = [l[keep] for l in lows]
        highs = [h[keep] for h in highs]
        if eff.size == 0:
            die(f"map file {path}: no usable rows after dropping non-numeric efficiencies")
        if np.any(eff > 1.0 + 1e-9) or np.any(eff < 0.0):
            print(f"effmap_fold: LOUD WARNING: map {path}: efficiency range "
                  f"[{eff.min():g}, {eff.max():g}] leaves [0,1] -- percent units or A*eps "
                  f"mis-read? NOT rescaling; fix the map or the spec upstream.")
        return cls(name or os.path.basename(path), path, axis_names, axis_units,
                   lows, highs, eff, n_holes)

    @staticmethod
    def _axis_edges(path, aname, vals):
        """Per-row (low, high) arrays; synthesizes edges for point-'value' axes."""
        has_lh = all(isinstance(v, dict) and "low" in v and "high" in v for v in vals)
        has_pt = all(isinstance(v, dict) and "value" in v for v in vals)
        if not (has_lh or has_pt):
            die(f"map file {path}: axis '{aname}': rows must ALL carry low/high or ALL carry "
                f"value (mixed/missing entries found)")
        if has_lh:
            try:
                lo = np.array([float(v["low"]) for v in vals])
                hi = np.array([float(v["high"]) for v in vals])
            except (TypeError, ValueError) as e:
                die(f"map file {path}: axis '{aname}': non-numeric bin edge ({e})")
            bad = np.flatnonzero(~(lo < hi))
            if bad.size:
                die(f"map file {path}: axis '{aname}': degenerate/inverted bin at row "
                    f"{bad[0]} (low={lo[bad[0]]:g}, high={hi[bad[0]]:g})")
            return lo, hi
        # point values: edges at midpoints between sorted unique values, ends mirrored
        try:
            pv = np.array([float(v["value"]) for v in vals])
        except (TypeError, ValueError) as e:
            die(f"map file {path}: axis '{aname}': non-numeric point value ({e})")
        uniq = np.unique(pv)
        if uniq.size < 2:
            die(f"map file {path}: axis '{aname}': only one distinct point value "
                f"({uniq[0]:g}) -- no bin width/envelope is derivable; publish-style low/high "
                f"edges are required for this axis")
        mids = 0.5 * (uniq[1:] + uniq[:-1])
        edges = np.concatenate(([2.0 * uniq[0] - mids[0]], mids, [2.0 * uniq[-1] - mids[-1]]))
        pos = np.searchsorted(uniq, pv)
        return edges[pos], edges[pos + 1]

    # -- lookup ------------------------------------------------------------- #
    def lookup(self, coords):
        """coords: sequence of self.ndim floats -> (efficiency, None) | (None, reason)."""
        if len(coords) != self.ndim:
            raise ValueError(f"map '{self.name}': lookup got {len(coords)} coords, "
                             f"map is {self.ndim}-D ({self.axis_names})")
        for a, x in enumerate(coords):
            if math.isnan(x):
                return None, f"nan:{self.axis_names[a]}"
        for a, x in enumerate(coords):
            if x < self.axis_min[a]:
                return None, f"below-min:{self.axis_names[a]}"
            if x > self.axis_max[a]:
                return None, f"above-max:{self.axis_names[a]}"
        mask = np.ones(self.n_rows, bool)
        for a, x in enumerate(coords):
            m = (self.lows[a] <= x) & (x < self.highs[a])
            if x == self.axis_max[a]:                      # closure of each axis's last bin
                m |= (self.highs[a] == x) & (self.lows[a] <= x)
            mask &= m
        idx = np.flatnonzero(mask)
        if idx.size == 0:
            return None, "in-range-hole"
        if idx.size > 1:
            raise RuntimeError(f"map '{self.name}' ({self.source}): {idx.size} overlapping grid "
                               f"rows contain point {tuple(coords)} -- map defect, refusing to "
                               f"pick one")
        return float(self.eff[idx[0]]), None

    # -- reporting ---------------------------------------------------------- #
    def describe(self):
        lines = [f"map '{self.name}' ({self.source}): {self.ndim}-D, {self.n_rows} rows"
                 + (f" ({self.holes_dropped} hole rows dropped)" if self.holes_dropped else "")]
        for a in range(self.ndim):
            unit = f" [{self.axis_units[a]}]" if self.axis_units[a] else ""
            nbin = np.unique(np.stack([self.lows[a], self.highs[a]]), axis=1).shape[1]
            lines.append(f"  axis {a} '{self.axis_names[a]}'{unit}: envelope "
                         f"[{self.axis_min[a]:g}, {self.axis_max[a]:g}], {nbin} unique bins")
        lines.append(f"  efficiency: range [{self.eff.min():g}, {self.eff.max():g}]; bins "
                     f"[low, high) half-open, last bin closed; outside envelope -> None "
                     f"(counted + reported, NEVER clamped/zeroed)")
        return "\n".join(lines)

    def envelope_dict(self):
        return {"axes": [{"name": n, "units": u, "min": lo, "max": hi}
                         for n, u, lo, hi in zip(self.axis_names, self.axis_units,
                                                 self.axis_min, self.axis_max)],
                "n_rows": self.n_rows, "hole_rows_dropped": self.holes_dropped,
                "source": self.source}


def _norm(s):
    """Header-name normalization for spec matching: casefold, strip a trailing [units]."""
    return re.sub(r"\s*\[[^\]]*\]\s*$", "", str(s)).strip().casefold()


# --------------------------------------------------------------------------- #
# events + spec
# --------------------------------------------------------------------------- #
def load_events(path):
    """JSONL, JSON list, or {"events": [...]} -> list of event dicts."""
    if not os.path.exists(path):
        die(f"events file not found: {path}")
    text = open(path).read()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("events"), list):
            return data["events"]
        if isinstance(data, dict) and isinstance(data.get("objects"), list):
            return [data]                    # a one-line JSONL file parses as one event dict
        die(f"events file {path}: JSON top level must be a list, {{'events': [...]}}, "
            f"or a single event dict")
    except json.JSONDecodeError:
        pass
    events = []
    for ln, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as e:
            die(f"events file {path} line {ln}: not valid JSON ({e})")
    if not events:
        die(f"events file {path}: parsed zero events")
    return events


def resolve_axes(spec_axes, effmap, kind):
    """Spec 'axes' (positional list, or dict keyed by map axis name/index) -> attr list."""
    if isinstance(spec_axes, list):
        if len(spec_axes) != effmap.ndim:
            die(f"fold spec: kind '{kind}': 'axes' lists {len(spec_axes)} attributes but map "
                f"'{effmap.name}' is {effmap.ndim}-D ({effmap.axis_names})")
        return [str(a) for a in spec_axes]
    if isinstance(spec_axes, dict):
        attrs = [None] * effmap.ndim
        for key, attr in spec_axes.items():
            hits = [i for i, n in enumerate(effmap.axis_names) if _norm(n) == _norm(key)]
            if not hits and str(key).lstrip("-").isdigit() and 0 <= int(key) < effmap.ndim:
                hits = [int(key)]
            if len(hits) != 1:
                die(f"fold spec: kind '{kind}': axes key '{key}' matches {len(hits)} of map "
                    f"'{effmap.name}' axes {effmap.axis_names} -- use exact names or indices")
            attrs[hits[0]] = str(attr)
        missing = [effmap.axis_names[i] for i, a in enumerate(attrs) if a is None]
        if missing:
            die(f"fold spec: kind '{kind}': no object attribute mapped for map axes {missing}")
        return attrs
    die(f"fold spec: kind '{kind}': 'axes' must be a list or dict")


def load_spec(spec, spec_dir):
    """Spec dict -> ({map_name: EffMap}, {kind: (map_name, [attrs])}, sr_name)."""
    if not isinstance(spec, dict) or not isinstance(spec.get("maps"), dict) or not spec["maps"]:
        die("fold spec: needs a non-empty 'maps' dict")
    if not isinstance(spec.get("objects"), dict) or not spec["objects"]:
        die("fold spec: needs a non-empty 'objects' dict (object kind -> map + axes)")
    maps = {}
    for mname, m in spec["maps"].items():
        if not isinstance(m, dict) or "file" not in m:
            die(f"fold spec: map '{mname}' needs a 'file'")
        fpath = m["file"]
        if not os.path.isabs(fpath):
            fpath = os.path.normpath(os.path.join(spec_dir, fpath))
        maps[mname] = EffMap.from_file(fpath, dep=m.get("dependent_variable", 0), name=mname)
    kinds = {}
    for kind, o in spec["objects"].items():
        if not isinstance(o, dict) or "map" not in o or "axes" not in o:
            die(f"fold spec: objects entry '{kind}' needs 'map' and 'axes'")
        if o["map"] not in maps:
            die(f"fold spec: objects entry '{kind}' references unknown map '{o['map']}' "
                f"(have {sorted(maps)})")
        kinds[kind] = (o["map"], resolve_axes(o["axes"], maps[o["map"]], kind))
    return maps, kinds, str(spec.get("sr_name", "SR"))


# --------------------------------------------------------------------------- #
# the fold
# --------------------------------------------------------------------------- #
def run_fold(events_path, spec, spec_dir, sigma_pb, lumi_fb, out_dir, sr_name=None, quiet=False):
    """Fold the events through the spec's maps -> result dict; writes fold_result.json +
    event_weights.jsonl under out_dir. Envelope-excluded events fold to weight 0 (conservative
    under-coverage) and are counted; the mean runs over the FULL generated sample."""
    maps, kinds, spec_sr = load_spec(spec, spec_dir)
    sr_name = sr_name or spec_sr
    events = load_events(events_path)

    if not quiet:
        for m in maps.values():
            print(m.describe())
        for kind, (mname, attrs) in sorted(kinds.items()):
            pairs = ", ".join(f"'{ax}' <- obj['{at}']"
                              for ax, at in zip(maps[mname].axis_names, attrs))
            print(f"fold basis: kind '{kind}' -> map '{mname}': {pairs}")

    n_unselected = n_env_excluded = n_zero_obj = n_folded_objects = 0
    out_reasons, ignored_kinds = {}, {}
    gw_arr, fw_arr, rows = [], [], []

    for i, ev in enumerate(events):
        if not isinstance(ev, dict) or not isinstance(ev.get("objects"), list):
            die(f"event {i}: each event must be a dict with an 'objects' list")
        sel = ev.get("selected", True)
        if not isinstance(sel, bool):
            die(f"event {i}: 'selected' must be true/false (got {sel!r})")
        try:
            gw = float(ev.get("weight", 1.0))
        except (TypeError, ValueError):
            die(f"event {i}: non-numeric 'weight' ({ev.get('weight')!r})")

        env_ok, n_obj, w = True, 0, 1.0
        if not sel:
            n_unselected += 1
            fw = 0.0
        else:
            for j, obj in enumerate(ev["objects"]):
                if not isinstance(obj, dict) or "kind" not in obj:
                    die(f"event {i} object {j}: each object needs a 'kind'")
                kind = str(obj["kind"])
                if kind not in kinds:
                    ignored_kinds[kind] = ignored_kinds.get(kind, 0) + 1
                    continue
                mname, attrs = kinds[kind]
                coords = []
                for attr in attrs:
                    if attr not in obj:
                        die(f"event {i} object {j} (kind '{kind}'): missing attribute "
                            f"'{attr}' required by map '{mname}'")
                    try:
                        coords.append(float(obj[attr]))
                    except (TypeError, ValueError):
                        die(f"event {i} object {j} (kind '{kind}'): attribute '{attr}' is "
                            f"non-numeric ({obj[attr]!r})")
                val, reason = maps[mname].lookup(coords)
                if val is None:
                    if reason.startswith("nan:"):
                        die(f"event {i} object {j} (kind '{kind}'): NaN kinematics "
                            f"({reason}) -- corrupt input, refusing to fold")
                    key = f"{mname}:{reason}"
                    out_reasons[key] = out_reasons.get(key, 0) + 1
                    env_ok = False        # keep scanning the event's objects for full stats
                else:
                    w *= val
                    n_obj += 1
            if not env_ok:
                n_env_excluded += 1
                fw = 0.0
            else:
                fw = w
                n_folded_objects += n_obj
                if n_obj == 0:
                    n_zero_obj += 1
        gw_arr.append(gw)
        fw_arr.append(fw)
        rows.append({"index": i, "gen_weight": gw, "fold_weight": fw, "selected": sel,
                     "envelope_ok": env_ok, "n_objects_folded": n_obj})

    gw_arr, fw_arr = np.array(gw_arr), np.array(fw_arr)
    sum_gw = float(gw_arr.sum())
    if sum_gw <= 0:
        die(f"sum of generator weights is {sum_gw:g} -- cannot form a mean weight")
    mean_w = float((gw_arr * fw_arr).sum() / sum_gw)
    mean_w_err = float(np.sqrt((gw_arr**2 * (fw_arr - mean_w)**2).sum()) / sum_gw)
    n_out_objects = sum(out_reasons.values())
    expected_yield = sigma_pb * 1000.0 * lumi_fb * mean_w
    yield_err = sigma_pb * 1000.0 * lumi_fb * mean_w_err

    os.makedirs(out_dir, exist_ok=True)
    weights_path = os.path.join(out_dir, "event_weights.jsonl")
    with open(weights_path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    result = {
        "tool": "effmap_fold", "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "sr_name": sr_name, "events_file": os.path.abspath(events_path),
        "n_events": len(events), "sigma_pb": sigma_pb, "lumi_fb": lumi_fb,
        "sum_gen_weights": sum_gw,
        "mean_fold_weight": mean_w, "mean_fold_weight_stat_err": mean_w_err,
        "expected_yield": expected_yield, "expected_yield_stat_err": yield_err,
        "yield_formula": "sigma_pb * 1000 * lumi_fb * mean_fold_weight",
        "counts": {
            "n_events_selected_false": n_unselected,
            "n_events_envelope_excluded": n_env_excluded,
            "n_events_zero_folded_objects": n_zero_obj,
            "n_objects_folded": n_folded_objects,
            "n_objects_out_of_envelope": n_out_objects,
            "out_of_envelope_reasons": out_reasons,
            "ignored_object_kinds": ignored_kinds,
        },
        "envelope_policy": "excluded events fold to weight 0 over the FULL-sample mean "
                           "(conservative under-coverage); lookups are never clamped or "
                           "extrapolated",
        "maps": {n: m.envelope_dict() for n, m in maps.items()},
        "weights_file": os.path.abspath(weights_path),
        "r5_gate": "NOT satisfied by this run alone -- see verification-ladder R5 / "
                   "effmap-folding.md D2 step 4",
    }
    result_path = os.path.join(out_dir, "fold_result.json")
    json.dump(result, open(result_path, "w"), indent=1)

    if not quiet:
        print(f"\nfolded {len(events)} events (sum gen weights {sum_gw:g}) -> SR '{sr_name}'")
        print(f"  mean fold weight    = {mean_w:.6g} +- {mean_w_err:.2g} (MC stat)")
        print(f"  expected yield      = sigma_pb({sigma_pb:g}) x 1000 x lumi_fb({lumi_fb:g}) "
              f"x <w> = {expected_yield:.6g} +- {yield_err:.2g}")
        if n_env_excluded or n_out_objects:
            bang = "!" * 78
            print(bang)
            print(f"!! OUT-OF-ENVELOPE: {n_env_excluded}/{len(events)} events "
                  f"({n_env_excluded / len(events):.2%}) carried {n_out_objects} objects "
                  f"outside map validity")
            print(f"!! -> those events folded to weight 0 (conservative UNDER-coverage); "
                  f"never clamped.")
            for k, c in sorted(out_reasons.items()):
                print(f"!!    {k}: {c} objects")
            print(bang)
        else:
            print("  envelope: all folded objects inside all map envelopes (0 exclusions)")
        if n_unselected:
            print(f"  note: {n_unselected} events had selected=false (weight 0, no lookups)")
        if n_zero_obj:
            print(f"  LOUD NOTE: {n_zero_obj} selected events had ZERO foldable objects -> "
                  f"weight 1.0 x selection flag; is the events file/spec kind list right?")
        for k, c in sorted(ignored_kinds.items()):
            print(f"  note: object kind '{k}' not in fold spec: {c} objects ignored")
        print(f"  wrote {result_path}")
        print(f"  wrote {weights_path} (per-event weights for pyhf counting)")
    return result


# --------------------------------------------------------------------------- #
# selftest: synthetic closure against a known analytic efficiency
# --------------------------------------------------------------------------- #
def _selftest_map(path):
    """2-D map on pt x |eta|: eps = clip(0.01*pt, 0, 0.8) * (1 - 0.3*|eta|/2.5),
    100 x 1 GeV bins x 25 x 0.1 bins, value at bin centre. Both factors are linear within
    every bin (the clip kink at pt=80 lies ON a bin edge), so bin-centre == bin-average and
    the binned map integrates EXACTLY like the analytic form: any folded-vs-analytic gap is
    pure MC statistics of the seeded draw."""
    pt_e, eta_e = np.linspace(0.0, 100.0, 101), np.linspace(0.0, 2.5, 26)
    ptv, etav, effv = [], [], []
    for i in range(100):
        for j in range(25):
            ptc = 0.5 * (pt_e[i] + pt_e[i + 1])
            etac = 0.5 * (eta_e[j] + eta_e[j + 1])
            ptv.append({"low": float(pt_e[i]), "high": float(pt_e[i + 1])})
            etav.append({"low": float(eta_e[j]), "high": float(eta_e[j + 1])})
            effv.append({"value": float(_eps_true(ptc, etac))})
    doc = {"independent_variables": [
               {"header": {"name": "pt", "units": "GeV"}, "values": ptv},
               {"header": {"name": "abseta"}, "values": etav}],
           "dependent_variables": [{"header": {"name": "efficiency"}, "values": effv}]}
    yaml.safe_dump(doc, open(path, "w"), default_flow_style=True, width=200)


def _eps_true(pt, abseta):
    return min(max(0.01 * pt, 0.0), 0.8) * (1.0 - 0.3 * abseta / 2.5)


def _write_events(path, rows):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def run_selftest(workdir=None, keep=False):
    print("== effmap_fold --selftest (deterministic, seed 20260707) ==")
    wd = workdir or tempfile.mkdtemp(prefix="effmap_selftest_")
    os.makedirs(wd, exist_ok=True)
    print(f"workdir: {wd}")
    checks = []
    try:
        map_path = os.path.join(wd, "map2d.yaml")
        _selftest_map(map_path)
        m = EffMap.from_file(map_path)
        spec = {"sr_name": "SELFTEST-SR",
                "maps": {"m2d": {"file": map_path}},
                "objects": {"probe": {"map": "m2d", "axes": ["pt", "abseta"]}}}

        # (a) analytic closure: uniform events, folded <w> vs the closed-form integral
        rng = np.random.default_rng(20260707)
        n = 50000
        pt = rng.uniform(5.0, 95.0, n)
        eta = rng.uniform(0.0, 2.5, n)
        _write_events(os.path.join(wd, "ev_a.jsonl"),
                      [{"objects": [{"kind": "probe", "pt": float(p), "abseta": float(e)}]}
                       for p, e in zip(pt, eta)])
        print(f"\n-- (a) analytic closure fold: {n} events, pt~U(5,95) x |eta|~U(0,2.5) --")
        res_a = run_fold(os.path.join(wd, "ev_a.jsonl"), spec, wd, sigma_pb=0.002,
                         lumi_fb=139.0, out_dir=os.path.join(wd, "out_a"), quiet=False)
        # closed form: E[clip(.01 pt,0,.8)] over U(5,95) = (1/90)(int_5^80 .01p dp + .8*15)
        #            = (31.875+12)/90 = 0.4875 ; E[1-.12|eta|] over U(0,2.5) = 0.85
        analytic = 0.4875 * 0.85                                   # = 0.4143750
        mean_w = res_a["mean_fold_weight"]
        rel = abs(mean_w / analytic - 1.0)
        binned_only = abs(mean_w / float(np.mean([_eps_true(p, e)
                                                  for p, e in zip(pt, eta)])) - 1.0)
        print(f"(a) folded <w> = {mean_w:.6f} | analytic integral = {analytic:.7f} | "
              f"rel dev = {rel:.4%} (< 1% required; MC-stat ~0.09%)")
        print(f"    binning-limited residual vs per-event analytic eps: {binned_only:.4%}")
        assert rel < 0.01, f"(a) FAIL: |folded/analytic - 1| = {rel:.4%} >= 1%"
        assert math.isclose(res_a["expected_yield"],
                            0.002 * 1000.0 * 139.0 * mean_w, rel_tol=1e-12), \
            "(a) FAIL: yield != sigma_pb*1000*lumi_fb*<w>"
        checks.append("(a) analytic closure <1%")

        # (b) validity envelope: planted out-of-range events are counted, not folded
        print("\n-- (b) envelope: 10 in-range + planted 7 above pt-max, 5 above |eta|-max, "
              "3 below pt-min --")
        v, r = m.lookup((150.0, 1.0))
        assert v is None and r == "above-max:pt", f"(b) FAIL: got ({v}, {r})"
        assert m.lookup((-2.0, 1.0)) == (None, "below-min:pt"), "(b) FAIL below-min"
        assert m.lookup((50.0, 3.2)) == (None, "above-max:abseta"), "(b) FAIL above-max eta"
        v_edge, r_edge = m.lookup((100.0, 2.5))     # exact envelope corner: IN (last-bin closure)
        assert r_edge is None and math.isclose(v_edge, 0.8 * (1 - 0.3 * 2.45 / 2.5)), \
            f"(b) FAIL: envelope corner lookup gave ({v_edge}, {r_edge})"
        ev_b = ([{"objects": [{"kind": "probe", "pt": 50.0, "abseta": 1.0}]}] * 10
                + [{"objects": [{"kind": "probe", "pt": 150.0, "abseta": 1.0}]}] * 7
                + [{"objects": [{"kind": "probe", "pt": 50.0, "abseta": 3.2}]}] * 5
                + [{"objects": [{"kind": "probe", "pt": -2.0, "abseta": 1.0}]}] * 3)
        _write_events(os.path.join(wd, "ev_b.jsonl"), ev_b)
        res_b = run_fold(os.path.join(wd, "ev_b.jsonl"), spec, wd, sigma_pb=1.0, lumi_fb=1.0,
                         out_dir=os.path.join(wd, "out_b"), quiet=False)
        cb = res_b["counts"]
        assert cb["n_events_envelope_excluded"] == 15, cb
        assert cb["n_objects_out_of_envelope"] == 15, cb
        assert cb["out_of_envelope_reasons"] == {"m2d:above-max:pt": 7,
                                                 "m2d:above-max:abseta": 5,
                                                 "m2d:below-min:pt": 3}, cb
        wrows = [json.loads(l) for l in open(res_b["weights_file"])]
        assert len(wrows) == 25
        assert all(w["fold_weight"] == 0.0 and not w["envelope_ok"] for w in wrows[10:]), \
            "(b) FAIL: excluded events must carry weight 0 and envelope_ok=false"
        assert all(w["fold_weight"] > 0.0 and w["envelope_ok"] for w in wrows[:10]), \
            "(b) FAIL: in-range events must fold normally"
        eps_in = m.lookup((50.0, 1.0))[0]
        assert math.isclose(res_b["mean_fold_weight"], 10 * eps_in / 25, rel_tol=1e-12), \
            "(b) FAIL: mean must average excluded events as 0 over the FULL sample"
        print("(b) counters == planted (7/5/3), excluded events folded to 0, reported loudly")
        checks.append("(b) envelope counted, not folded")

        # (c) multi-object product: 2-object event weight == product of the two lookups EXACTLY
        print("\n-- (c) 2-object product exactness --")
        o1, o2 = (37.3, 1.07), (81.6, 0.33)
        l1, l2 = m.lookup(o1)[0], m.lookup(o2)[0]
        _write_events(os.path.join(wd, "ev_c.jsonl"),
                      [{"objects": [{"kind": "probe", "pt": o1[0], "abseta": o1[1]},
                                    {"kind": "probe", "pt": o2[0], "abseta": o2[1]}]}])
        res_c = run_fold(os.path.join(wd, "ev_c.jsonl"), spec, wd, sigma_pb=1.0, lumi_fb=1.0,
                         out_dir=os.path.join(wd, "out_c"), quiet=True)
        assert res_c["mean_fold_weight"] == l1 * l2, \
            f"(c) FAIL: {res_c['mean_fold_weight']!r} != {l1!r} * {l2!r}"
        print(f"(c) event weight {res_c['mean_fold_weight']:.10f} == "
              f"eps{o1} x eps{o2} = {l1:.6f} x {l2:.6f} (bitwise equal)")
        checks.append("(c) product exact")

        # (d) 1-D point-'value' map: synthesized edges + envelope semantics
        map1d = os.path.join(wd, "map1d.yaml")
        yaml.safe_dump({"independent_variables": [
                            {"header": {"name": "x"}, "values": [{"value": 10.0},
                                                                 {"value": 20.0},
                                                                 {"value": 30.0}]}],
                        "dependent_variables": [{"header": {"name": "eff"},
                                                 "values": [{"value": 0.2}, {"value": 0.5},
                                                            {"value": 0.7}]}]},
                       open(map1d, "w"))
        m1 = EffMap.from_file(map1d)
        assert (m1.axis_min[0], m1.axis_max[0]) == (5.0, 35.0), "(d) FAIL: synthesized edges"
        assert m1.lookup((17.0,)) == (0.5, None) and m1.lookup((5.0,)) == (0.2, None)
        assert m1.lookup((35.0,)) == (0.7, None), "(d) FAIL: last-bin closure"
        assert m1.lookup((4.99,)) == (None, "below-min:x")
        assert m1.lookup((35.01,)) == (None, "above-max:x")
        print("\n(d) 1-D 'value'-format map: edges synthesized to [5,15,25,35], "
              "lookups + envelope correct")
        checks.append("(d) 1-D value-format map")

        # (e) selected=false zeroes the weight without touching the maps
        _write_events(os.path.join(wd, "ev_e.jsonl"),
                      [{"selected": False,
                        "objects": [{"kind": "probe", "pt": 150.0, "abseta": 9.0}]}])
        res_e = run_fold(os.path.join(wd, "ev_e.jsonl"), spec, wd, sigma_pb=1.0, lumi_fb=1.0,
                         out_dir=os.path.join(wd, "out_e"), quiet=True)
        assert res_e["mean_fold_weight"] == 0.0
        assert res_e["counts"]["n_events_selected_false"] == 1
        assert res_e["counts"]["n_objects_out_of_envelope"] == 0, \
            "(e) FAIL: unselected events must not be looked up"
        print("(e) selected=false -> weight 0, no lookups performed")
        checks.append("(e) selection flag")

    except AssertionError as e:
        print(f"\nSELFTEST: FAIL -- {e}")
        print(f"(workdir kept for inspection: {wd})")
        return 1
    if not keep and workdir is None:
        shutil.rmtree(wd, ignore_errors=True)
    print(f"\nSELFTEST: PASS ({len(checks)}/5) -- " + " ; ".join(checks))
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--selftest" in argv:
        p = argparse.ArgumentParser(prog="effmap_fold.py --selftest")
        p.add_argument("--selftest", action="store_true")
        p.add_argument("--workdir", default=None, help="run in this dir (kept) instead of a tmpdir")
        p.add_argument("--keep", action="store_true", help="keep the tmpdir")
        a = p.parse_args(argv)
        return run_selftest(a.workdir, a.keep)

    parser = argparse.ArgumentParser(
        description="Per-object efficiency-map folding (Option D2). See the module docstring.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("inspect", help="print a map's axes, binning and validity envelope")
    pi.add_argument("--map", required=True)
    pi.add_argument("--dep", default=0, help="dependent variable index or header name")
    pf = sub.add_parser("fold", help="fold truth events through the spec's maps")
    pf.add_argument("--events", required=True, help="JSONL / JSON list of truth events")
    pf.add_argument("--spec", required=True, help="fold spec (YAML/JSON)")
    pf.add_argument("--sigma-pb", required=True, type=float, help="model cross-section [pb]")
    pf.add_argument("--lumi-fb", required=True, type=float, help="integrated luminosity [fb^-1]")
    pf.add_argument("--out", required=True, help="output dir (fold_result.json + weights)")
    pf.add_argument("--sr-name", default=None, help="override the spec's sr_name")
    args = parser.parse_args(argv)

    print(R5_GATE)
    if args.cmd == "inspect":
        print(EffMap.from_file(args.map, dep=args.dep).describe())
        return 0
    spec_path = os.path.abspath(args.spec)
    try:
        spec = yaml.safe_load(open(spec_path).read())
    except (OSError, yaml.YAMLError) as e:
        die(f"fold spec {spec_path}: {e}")
    run_fold(args.events, spec, os.path.dirname(spec_path), args.sigma_pb, args.lumi_fb,
             args.out, sr_name=args.sr_name, quiet=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
