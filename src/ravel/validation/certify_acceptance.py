#!/usr/bin/env python
"""Compare SimpleAnalysis/Delphes acceptance times efficiency with published maps.

This checks point-estimate agreement for the complete generation, shower,
detector and selection chain. It does not isolate a detector defect, justify
retuning, propagate MC/published uncertainties, or establish statistical coverage.
Normalization cancellation requires the same generated-process and decay basis.

Input: SimpleAnalysis CSV (SR,events,acceptance,err) or a per-SR JSON object.
The selected-event yield is preserved as a real number for weighted samples.
Nonfinite/negative values, duplicate CSV regions and invalid denominators fail.
The CSV err column is not propagated; reports explicitly state this limitation.

Published A×ε comes from an explicit acceptance-times-efficiency table, or from
separate acceptance and efficiency tables at matching lookup nodes. Acceptance
alone is not an A×ε reference. --acc-unit-scale applies only to separate acceptance
tables; the default 1e-3 convention must match the particular HEPData publication.
The second grid axis is a splitting: pass --dm or --m-lsp, never both.

Lookup: node within 1 GeV; local 1-D interpolation with a bounded span; otherwise
NEAREST for diagnosis only. A nearest-node driving comparison cannot pass even
inside the outer grid boundary. Interpolation uncertainty is not estimated.

Driving regions are the most occupied bins and bins within --driving-factor,
or explicit --driving-sr-override choices. Occupancy is a validation heuristic,
not an inferred ordering of statistical sensitivity. Tails are report-only.
All requested rows remain in the comparison counts. The worst residual is the
maximum over every driving row. Missing driving references/yields, no driving
region, or unmatched driving references fail. Zero acceptance is a real deficit.

The legacy mu95_impact name denotes an acceptance residual proxy, not a limit
uncertainty. inverse_signal_limit_shift reports conditional 1/ratio - 1 algebra
for uniform signal rescaling only. Similar residuals across regions trigger a
normalization/efficiency diagnostic prompt; they do not establish a physical cause.

Exit code 0 means a report was produced; consumers MUST read its PASS/WARN/FAIL
verdict. Parse/validation errors exit nonzero. Output is Markdown + JSON.

Example:
  certify_acceptance.py --acceptance EwkCompressed2018.txt --tables-dir HEPData-yaml
      --grid slepton --m-parent 200 --dm 50 --srs SR_S_iMT2a,SR_S_high_iMT2a
      --out acceptance-certification.md
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.validation"


import argparse, glob, json, math, os, re, sys
from .validate_cutflow import (
    finite_nonnegative, comparison_metadata, comparison_ratio, inverse_signal_shift, unique_json_object,
)



# --------------------------------------------------------------------------------------------------
# Published map: locate + read one grid table, then combine acceptance x efficiency.
# --------------------------------------------------------------------------------------------------

def _read_grid_table(base, data_file, m_parent, splitting, node_tol, interp_max_span):
    """Read a 2-D HEPData grid table at (m_parent, splitting) -> (value, node_descriptor, off_grid).

    Mirrors validate_cutflow.published_axe's 3-tier node lookup (exact / 1-D interp / flagged nearest),
    but on a generic (parent, splitting) grid table. `off_grid` is True only when the nearest-node
    fallback fired AND the requested point lies outside the published splitting range at that parent
    mass (a genuine extrapolation, not merely an interior non-node point), so the verdict can flag it.
    """
    import yaml
    d = yaml.safe_load(open(os.path.join(base, data_file), errors="replace"))
    iv = d["independent_variables"]; dv = d["dependent_variables"][0]["values"]
    pm = [x["value"] for x in iv[0]["values"]]
    lm = [x["value"] for x in iv[1]["values"]]
    if not pm or len(pm) != len(lm) or len(pm) != len(dv):
        raise ValueError("published acceptance grid has empty or misaligned columns")
    pts = [(finite_nonnegative(pm[i], "published parent mass"),
            finite_nonnegative(lm[i], "published splitting"),
            finite_nonnegative(dv[i]["value"], "published acceptance/efficiency"))
           for i in range(len(pm))]
    x = splitting
    # 1) exact node
    for a, b, v in pts:
        if abs(a - m_parent) < node_tol and abs(b - x) < node_tol:
            return v, f"grid node (m_parent={a:.0f}, split={b:g})", False
    # 2) 1-D bracket interpolation along the splitting axis at fixed parent mass
    same = sorted((b, v) for a, b, v in pts if abs(a - m_parent) < node_tol)
    lo = max(((xx, vv) for xx, vv in same if xx <= x), default=None)
    hi = min(((xx, vv) for xx, vv in same if xx >= x), default=None)
    if lo and hi and lo[0] != hi[0] and (hi[0] - lo[0]) <= interp_max_span:
        f = (x - lo[0]) / (hi[0] - lo[0])
        val = lo[1] + f * (hi[1] - lo[1])
        return val, f"interp@m_parent={m_parent:g}: split {lo[0]:g}->{hi[0]:g}", False
    # 3) nearest-node fallback — and decide whether the request is genuinely off the grid
    best, bd = None, 1e18
    for a, b, v in pts:
        dist = (a - m_parent) ** 2 + (b - x) ** 2
        if dist < bd:
            bd, best = dist, (a, b, v)
    # off-grid if, at the (nearest) parent mass slice, the requested splitting is outside [min,max]
    if same:
        smin, smax = same[0][0], same[-1][0]
    else:
        col = sorted(b for a, b, v in pts)
        smin, smax = (col[0], col[-1]) if col else (x, x)
    off_grid = (x < smin - node_tol) or (x > smax + node_tol)
    tag = ("point outside published acc×eff grid" if off_grid else "no exact node or 1-D bracket")
    desc = (f"NEAREST grid node (m_parent={best[0]:.0f}, split={best[1]:g}) — {tag} at "
            f"(m_parent={m_parent:g}, split={x:g}); coarse-grid caution")
    return best[2], desc, off_grid


def _find_table(base, sub_docs, kind_re, region_re, grid_re):
    """Return the data_file whose submission description matches kind (acceptance/efficiency),
    the published signal-region phrase, and the grid (model) string. None if not found."""
    for doc in sub_docs:
        if not isinstance(doc, dict):
            continue
        desc = doc.get("description") or ""
        if kind_re.search(desc) and region_re.search(desc) and grid_re.search(desc):
            return doc.get("data_file")
    return None


def published_acceff(tables_dir, region, grid, m_parent, splitting,
                     acc_unit_scale=1e-3, node_tol=1.0, interp_max_span=200.0):
    """Published A×ε for a signal region = acceptance(scaled) x efficiency at (m_parent, splitting).

    `region` is the published signal-region phrase as it appears in the HEPData description, e.g.
    'SR-S', 'SR-S-high', 'SR-S-low'. The function finds the acceptance table (description contains
    'acceptance ... <region> ... <grid>') and, if present, the efficiency table ('efficiency ...
    <region> ... <grid>'), reads both at the grid point, scales the acceptance by acc_unit_scale (the
    z-axis 1e-3 convention noted in the headers), and returns their product. If only an explicit
    'acceptance times efficiency' table exists, that single value is used directly (acc_unit_scale=1).

    Returns (value, node_descriptor, off_grid). value is None when no acceptance table is found.
    The region match is anchored so 'SR-S' does not also match 'SR-S-high'/'SR-S-low'.
    """
    import yaml
    subs = glob.glob(os.path.join(tables_dir, "**", "submission.yaml"), recursive=True)
    if not subs:
        return None, "no submission.yaml", False
    base = os.path.dirname(subs[0])
    sub_docs = list(yaml.safe_load_all(open(subs[0], errors="replace")))
    grid_re = re.compile(re.escape(grid), re.I)
    # Anchor the region: require a non-word/dash boundary AFTER it so 'SR-S' != 'SR-S-high'.
    region_re = re.compile(re.escape(region) + r"(?![\w-])", re.I)

    # Preferred: a single explicit "acceptance times efficiency" table (validate_cutflow convention).
    axe_re = re.compile(r"acceptance\s+times\s+efficiency", re.I)
    axe_file = _find_table(base, sub_docs, axe_re, region_re, grid_re)
    if axe_file:
        v, node, og = _read_grid_table(base, axe_file, m_parent, splitting, node_tol, interp_max_span)
        return v, node + " [acc×eff table]", og

    # Otherwise: separate acceptance and efficiency tables -> elementwise product.
    # "acceptance" but NOT "acceptance times efficiency" (already handled above).
    acc_re = re.compile(r"\bacceptance\b", re.I)
    eff_re = re.compile(r"\befficiency\b", re.I)
    acc_file = _find_table(base, sub_docs, acc_re, region_re, grid_re)
    if not acc_file:
        return None, f"no acceptance table for '{region}' in '{grid}'", False
    av, anode, aog = _read_grid_table(base, acc_file, m_parent, splitting, node_tol, interp_max_span)
    eff_file = _find_table(base, sub_docs, eff_re, region_re, grid_re)
    if not eff_file:
        # Acceptance and acceptance×efficiency are different observables. Missing
        # efficiency is missing comparison evidence, never an implicit efficiency of one.
        return None, anode + " [missing efficiency table; acceptance alone is not A×ε]", aog
    ev, enode, eog = _read_grid_table(base, eff_file, m_parent, splitting, node_tol, interp_max_span)
    if anode != enode:
        return None, f"acceptance and efficiency lookup nodes differ: {anode}; {enode}", True
    finite_nonnegative(acc_unit_scale, "acc_unit_scale", positive=True)
    return (av * acc_unit_scale) * ev, anode + " [acc×eff]", (aog or eog)


# --------------------------------------------------------------------------------------------------
# My side: read per-SR acceptance from the SimpleAnalysis yields file (txt or json).
# --------------------------------------------------------------------------------------------------

def read_my_acceptance(path):
    """Parse the per-SR acceptance file -> {sr: (acceptance, events)}.

    Two supported formats:
      - SimpleAnalysis CSV (e.g. EwkCompressed2018.txt): header `SR,events,acceptance,err`,
        one row per signal region. acceptance = selected/generated (= A×ε), events = raw selected.
      - sr_yields-style json: {"<SR>": {"acceptance": .., "events": ..}} or
        {"<SR>": {"acceptance": ..}} or a flat {"<SR>": <acceptance float>}.
    """
    out = {}
    def record(sr, acc, events):
        if not isinstance(sr, str) or not sr.strip() or sr in out:
            raise ValueError(f"empty or duplicate signal region: {sr!r}")
        out[sr] = (finite_nonnegative(acc, f"{sr}.acceptance") if acc is not None else None,
                   finite_nonnegative(events, f"{sr}.events") if events is not None else None)
    if path.endswith(".json"):
        data = json.load(open(path), object_pairs_hook=unique_json_object)
        srs = data.get("sr_yields", data) if isinstance(data, dict) else data
        if not isinstance(srs, dict):
            raise ValueError("acceptance JSON must map signal regions to records")
        for sr, rec in srs.items():
            if isinstance(rec, dict):
                acc = rec.get("acceptance")
                if acc is None and "events" in rec and "n_generated" in rec:
                    denominator = finite_nonnegative(rec["n_generated"], f"{sr}.n_generated", positive=True)
                    acc = finite_nonnegative(rec["events"], f"{sr}.events") / denominator
                record(sr, acc, rec.get("events"))
            else:
                record(sr, rec, None)
        return out
    # CSV
    with open(path) as fh:
        header = fh.readline().strip().split(",")
        idx = {name: i for i, name in enumerate(header)}
        i_sr = idx.get("SR", 0)
        i_acc = idx.get("acceptance")
        i_ev = idx.get("events")
        for line in fh:
            line = line.strip()
            if not line:
                continue
            f = line.split(",")
            sr = f[i_sr]
            acc = float(f[i_acc]) if i_acc is not None and f[i_acc] != "" else None
            ev = None
            if i_ev is not None and f[i_ev] != "":
                ev = float(f[i_ev])  # weighted selected yields must not be truncated to integers
            record(sr, acc, ev)
    return out


# Map a SimpleAnalysis SR bin name to its published signal-region phrase (Fig 32 family).
# The published map publishes only the INCLUSIVE SR-S / SR-S-high / SR-S-low for the slepton model.
def infer_published_region(sr):
    """Best-effort map a routine SR bin name (e.g. 'SR_S_high_iMT2a') -> published region phrase.

    Returns the published phrase (e.g. 'SR-S-high') or None if no slepton SR-S region is recognised.
    Override per-SR with --region-map SR=REGION,... when the heuristic is wrong.
    """
    u = sr.upper()
    if "SR_S_HIGH" in u or "SR-S-HIGH" in u:
        return "SR-S-high"
    if "SR_S_LOW" in u or "SR-S-LOW" in u:
        return "SR-S-low"
    if "SR_S_" in u or u.endswith("SR_S") or "SR-S" in u:
        return "SR-S"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--acceptance", required=True,
                    help="SimpleAnalysis per-SR acceptance file: CSV (SR,events,acceptance,err) or json")
    ap.add_argument("--tables-dir", required=True, help="HEPData yaml dir (indexed by submission.yaml)")
    ap.add_argument("--grid", required=True, help="model phrase in the HEPData descriptions, e.g. 'slepton'")
    ap.add_argument("--m-parent", type=float, required=True)
    ap.add_argument("--m-lsp", type=float, help="LSP mass; Δm = m_parent - m_lsp (use this OR --dm)")
    ap.add_argument("--dm", type=float, help="mass splitting Δm directly (the published 2nd axis)")
    ap.add_argument("--srs", required=True, help="comma list of routine SR names (not a path)")
    ap.add_argument("--region-map", default="",
                    help="comma list SR=REGION overrides for the published-region inference, e.g. "
                         "'SR_S_iMT2a=SR-S,SR_S_high_iMT2a=SR-S-high'")
    ap.add_argument("--acc-unit-scale", type=float, default=1e-3,
                    help="scale applied to the published ACCEPTANCE table (z-axis 1e-3 convention); "
                         "set 1.0 if the table is already an absolute fraction")
    ap.add_argument("--tail-events", type=int, default=5,
                    help="SRs with fewer selected events are tail (report-only); mirrors validate_cutflow")
    ap.add_argument("--driving-factor", type=float, default=1.5,
                    help="SRs with selected events >= best/factor are also driving")
    ap.add_argument("--driving-sr-override", default="", help="comma list of SRs to FORCE role=driving")
    ap.add_argument("--driving-tol", type=float, default=0.15)
    ap.add_argument("--contributing-tol", type=float, default=0.25)
    ap.add_argument("--mu95-bound", type=float, default=0.10,
                    help="max allowed driving residual before the verdict drops below PASS")
    ap.add_argument("--interp-max-span", type=float, default=200.0,
                    help="widest splitting bracket (GeV) across which off-node 1-D interpolation is trusted")
    ap.add_argument("--label", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--certification-context", help="JSON mapping every reported SR to explicit point identity/basis")
    args = ap.parse_args()

    try:
        for name in ("acc_unit_scale", "driving_factor", "driving_tol", "contributing_tol", "mu95_bound", "interp_max_span"):
            finite_nonnegative(getattr(args, name), name, positive=True)
        finite_nonnegative(args.tail_events, "tail_events")
        finite_nonnegative(args.m_parent, "m_parent")
        for name in ("m_lsp", "dm"):
            if getattr(args, name) is not None:
                finite_nonnegative(getattr(args, name), name)
    except ValueError as exc:
        ap.error(str(exc))
    if args.driving_factor < 1:
        ap.error("driving_factor must be >= 1")
    if args.m_lsp is not None and args.dm is not None:
        ap.error("pass only one of --m-lsp and --dm")

    if args.m_lsp is None and args.dm is None:
        sys.exit("ERROR: pass --m-lsp or --dm (the published 2nd axis is the mass splitting)")
    splitting = args.dm if args.dm is not None else (args.m_parent - args.m_lsp)
    if splitting < 0:
        sys.exit(f"ERROR: Δm = {splitting:g} < 0 (m_lsp > m_parent?)")

    # Parse the routine acceptance file behind a clean error: a malformed CSV value / broken JSON /
    # unreadable path must surface as a one-line ERROR naming the file, not a raw Python traceback.
    try:
        mine_all = read_my_acceptance(args.acceptance)
    except (OSError, ValueError, KeyError, IndexError, json.JSONDecodeError) as e:
        sys.exit(f"ERROR: cannot parse acceptance file '{args.acceptance}': {type(e).__name__}: {e}")
    override = {s.strip() for s in args.driving_sr_override.split(",") if s.strip()}
    region_map = {}
    for kv in args.region_map.split(","):
        kv = kv.strip()
        if "=" in kv:
            k, v = kv.split("=", 1)
            region_map[k.strip()] = v.strip()

    srs = [s.strip() for s in args.srs.split(",") if s.strip()]
    if not srs or len(srs) != len(set(srs)):
        ap.error("--srs must contain distinct nonempty signal regions")

    # First pass: read my A×ε + events, look up the published value.
    raw = []
    for sr in srs:
        acc, ev = mine_all.get(sr, (None, None))
        region = region_map.get(sr) or infer_published_region(sr)
        if region is None:
            pub, node, off_grid = None, "no published region mapped (use --region-map)", False
        else:
            pub, node, off_grid = published_acceff(
                args.tables_dir, region, args.grid, args.m_parent, splitting,
                acc_unit_scale=args.acc_unit_scale, interp_max_span=args.interp_max_span)
        raw.append(dict(sr=sr, mine=acc, events=ev, region=region, pub=pub, node=node, off_grid=off_grid))

    # Driving = SR with the most selected events (and any within driving_factor), unless overridden.
    evs = [(r["sr"], r["events"]) for r in raw if r["events"] is not None]
    best_sr = max(evs, key=lambda t: t[1])[0] if evs else None
    best_ev = dict(evs).get(best_sr) if best_sr else None

    def classify(r):
        if r["sr"] in override:
            return "driving"
        ev = r["events"]
        if ev is not None and ev < args.tail_events:
            return "tail"
        if best_ev and ev is not None and ev >= best_ev / args.driving_factor:
            return "driving"
        return "contributing"

    def cause_class(r, ratio):
        if r["off_grid"]:
            return "off-grid"
        if ratio is None:
            return "selection-mapping"
        if r["events"] is not None and r["events"] < args.tail_events:
            return "statistics"
        return "unresolved"  # acceptance agreement alone cannot isolate detector response.

    rows = []
    for r in raw:
        role = classify(r)
        ratio = comparison_ratio(r["mine"], r["pub"])
        tol = (args.driving_tol if role == "driving"
               else (args.contributing_tol if role == "contributing" else None))
        resid = abs(1 - ratio) if ratio is not None else None
        # No computable ratio (missing routine yield, or no/unmapped published value): report-only for
        # non-driving SRs (rendered '-', like a tail — mirrors validate_cutflow's missing-SR handling);
        # for a DRIVING SR it stays unevaluated (ok=False), which correctly forces driving_ok→FAIL.
        if resid is None:
            ok = (tol is None) or (role != "driving")
        else:
            ok = (tol is None) or (resid <= tol)
        mu95_impact = resid if (role == "driving" and resid is not None) else None
        attribution = None
        flag_off = role == "driving" and r["off_grid"]
        unevaluable = ratio is None and role != "tail"
        if (resid is not None and tol is not None and resid > tol) or flag_off or unevaluable:
            attribution = {"sr": r["sr"], "region": r["region"],
                           "ratio": (round(ratio, 3) if ratio is not None else None), "role": role,
                           "residual_pct": (round(resid * 100) if resid is not None else None),
                           "cause_class": cause_class(r, ratio),
                           "mu95_impact_pct": (round(mu95_impact * 100) if mu95_impact is not None else None),
                           "note": "diagnostic hypothesis only; physical cause requires independent evidence"}
        rows.append(dict(sr=r["sr"], region=r["region"], mine=r["mine"], pub=r["pub"], events=r["events"],
                         ratio=ratio, role=role, tol=tol, ok=ok, mu95_impact=mu95_impact,
                         node=r["node"], off_grid=r["off_grid"], attribution=attribution,
                         inverse_signal_limit_shift=inverse_signal_shift(ratio)))

    driving = [r for r in rows if r["role"] == "driving"]
    # The worst driving residual is an HONEST None when no driving SR yielded a computable residual —
    # NOT 0.0. A default of 0.0 here is the laundering bug: it makes an unusable comparison (dead-sim,
    # wrong --grid, missing tables, empty file → every driving residual unevaluable) look like a
    # perfect 0% residual that sails under the bound into WARN. Keep it None so the gate below can tell
    # 'no residual' apart from 'a real 0% residual'.
    driving_resids = [r["mu95_impact"] for r in driving if r["mu95_impact"] is not None]
    best_resid = max(driving_resids, default=None)
    driving_ok = all(r["ok"] for r in driving) if driving else None
    driving_off_grid = any(r["off_grid"] for r in driving)
    driving_nearest = any(r["node"].startswith("NEAREST") for r in driving)
    worst_driving = best_resid

    # CR-140 denominator-basis guard (catalogue A4 at the cert surface; see the docstring recipe).
    # Similar ratios motivate checking common normalization and efficiency factors;
    # they do not identify a unique cause. This is a diagnostic prompt, not attribution.
    basis_suspicion = None
    evald = [r for r in rows if r["ratio"] is not None and r["ratio"] > 0 and r["role"] != "tail"]
    if len(evald) >= 2:
        rats = sorted(r["ratio"] for r in evald)
        if rats[-1] / rats[0] <= 1.25:
            gm = math.exp(sum(math.log(x) for x in rats) / len(rats))
            if gm >= 1.2:
                basis_suspicion = (
                    f"uniform ~{gm:.2f}× EXCESS across all {len(evald)} evaluated SRs — the A4 "
                    "pattern is compatible with a common normalization or efficiency mismatch. "
                    "Check whether the generated-sample denominator and published denominator use "
                    "the same process and decay basis. Do not apply a normalization correction "
                    "without establishing that mismatch independently")
            elif gm <= 1 / 1.2:
                basis_suspicion = (
                    f"uniform ~{gm:.2f}× DEFICIT across all {len(evald)} evaluated SRs — a single "
                    "normalization or efficiency mismatch is one possibility, alongside correlated "
                    "selection or generation effects. Separate these using controls before "
                    "changing normalization, cuts, or detector response")

    # HARD-FAIL gate, evaluated BEFORE the PASS/WARN/FAIL ladder. A certification is only meaningful if
    # there is a driving SR AND it was actually evaluated (a real residual against a real published
    # value). Any of these means the comparison is unusable and must FAIL LOUDLY, never WARN:
    #   • no driving SR at all (e.g. an all-zero dead-sim where every SR fell below --tail-events), or
    #   • driving_ok is False — either a driving SR could not be evaluated (missing/unmapped published
    #     value from a wrong --grid or absent tables, or a missing routine yield) OR it was evaluated
    #     and missed --driving-tol; the fail_reason below names which cause actually fired, or
    #   • best_resid is None (no driving SR produced a computable residual — the 0.0 laundering case).
    # This is the LOUD failure a physicist needs: a blank/wrong comparison can never read as 'bounded'.
    if not driving or driving_ok is False or best_resid is None or driving_nearest:
        verdict = "FAIL"
    elif driving_ok and best_resid <= args.mu95_bound and not driving_off_grid:
        verdict = "PASS"
    elif best_resid <= 1.5 * args.mu95_bound and not driving_off_grid:
        verdict = "WARN"   # bounded + attributed, on-grid
    else:
        verdict = "FAIL"   # driving SR off enough that the detector model is unreliable, or off-grid

    # Why the hard-fail fired (named for the reader), when it did. '-' worst residual is the honest
    # rendering of 'no evaluated driving residual' — it must never print as 0%.
    # driving_ok=False covers two OPPOSITE situations — a driving SR with no computable ratio (the
    # comparison is unusable: fix the inputs) vs a driving SR evaluated at a real published node whose
    # residual missed the tolerance (the comparison worked: fix the physics). Printing the first
    # message for the second case sent readers hunting for a --grid/--region-map problem that did not
    # exist (observed 4× across the CR-005 certs) — split them.
    if not driving:
        fail_reason = ("no driving SR could be identified (every SR fell below the tail threshold — a "
                       "dead/empty simulation, or selected-event counts are all missing) — nothing to "
                       "certify")
    elif driving_ok is False:
        uneval = [r["sr"] for r in driving if r["ratio"] is None]
        overtol = [r for r in driving if r["ratio"] is not None and not r["ok"]]
        parts = []
        if uneval:
            parts.append(f"driving SR(s) {', '.join(uneval)} could not be evaluated against a "
                         "published value (missing/unmapped published acc×eff — check --grid, "
                         "--region-map, and that the HEPData tables for this region exist) — "
                         "comparison unusable")
        if overtol:
            worst_ot = max(abs(1 - r["ratio"]) for r in overtol)
            parts.append(f"driving SR(s) {', '.join(r['sr'] for r in overtol)} evaluated against the "
                         f"published acc×eff but outside the ±{args.driving_tol*100:.0f}% driving "
                         f"tolerance (worst driving residual {worst_ot*100:.0f}%) — the comparison is "
                         "usable and the run failed the fidelity gate (detector model / merging / σ "
                         "basis — see the attribution rows), not a lookup failure")
        fail_reason = "; AND ".join(parts)
    elif best_resid is None:
        fail_reason = ("no computable driving residual (routine yield and/or published value absent) — "
                       "comparison unusable")
    elif verdict == "FAIL":
        # the ladder FAIL: driving SR(s) evaluated and inside --driving-tol, but unbounded/off-grid
        why = []
        if best_resid > 1.5 * args.mu95_bound:
            why.append(f"the worst driving residual {best_resid*100:.0f}% exceeds 1.5× the µ95 bound "
                       f"({1.5*args.mu95_bound*100:.0f}%)")
        if driving_off_grid:
            why.append("the driving SR was compared OFF the published grid (extrapolation, not a node)")
        elif driving_nearest:
            why.append("the driving SR uses a different published mass point (NEAREST); diagnostic residual only")
        fail_reason = "driving SR(s) evaluated within tolerance but " + " AND ".join(why)
    else:
        fail_reason = None
    worst_s = "-" if worst_driving is None else f"{worst_driving*100:.0f}%"

    split_label = (f"Δm={splitting:g}" if args.dm is not None
                   else f"m_LSP={args.m_lsp:.0f} (Δm={splitting:g})")
    lines = [f"# A×ε certification (SimpleAnalysis/Delphes path, tiered + attribution) — {args.label}", "",
             f"A×ε = (selected events)/(generated events); published = '{args.grid}' acceptance×efficiency "
             f"at (m_parent={args.m_parent:.0f}, {split_label}). Driving SRs ≤{args.driving_tol*100:.0f}%, "
             f"contributing ≤{args.contributing_tol*100:.0f}%, tail (<{args.tail_events} events) "
             f"report-only; driving residual bound {args.mu95_bound*100:.0f}%. Driving SR = the most-"
             f"occupied bin (and within {args.driving_factor:g}×). Published acc×eff = acceptance(×"
             f"{args.acc_unit_scale:g}) × efficiency at the same grid node.", "",
             "| SR | region | role | my A×ε | pub A×ε | node | ratio | tol | ok | residual |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        mine_s = "-" if r["mine"] is None else f"{r['mine']:.4g}"
        pub_s = "-" if r["pub"] is None else f"{r['pub']:.4g}"
        rat_s = "-" if r["ratio"] is None else f"{r['ratio']:.2f}"
        tol_s = "-" if r["tol"] is None else f"{r['tol']*100:.0f}%"
        res_s = "-" if r["mu95_impact"] is None else f"{r['mu95_impact']*100:.0f}%"
        ok_s = "OK" if r["ok"] else "x"
        reg_s = r["region"] or "-"
        lines.append(f"| {r['sr']} | {reg_s} | {r['role']} | {mine_s} | {pub_s} | {r['node']} | "
                     f"{rat_s} | {tol_s} | {ok_s} | {res_s} |")
    attribs = [r["attribution"] for r in rows if r["attribution"]]
    if attribs:
        lines += ["", "## Attribution (residuals above tier tolerance / off-grid driving SRs)", ""]
        for a in attribs:
            rp = "-" if a["residual_pct"] is None else f"{a['residual_pct']}%"
            mp = "-" if a["mu95_impact_pct"] is None else f"{a['mu95_impact_pct']}%"
            rr = "-" if a["ratio"] is None else a["ratio"]
            lines.append(f"- **{a['sr']}** ({a['role']}, {a['region']}): ratio {rr}, residual {rp} → "
                         f"`{a['cause_class']}`, residual-impact {mp}. {a['note']}")
    if basis_suspicion:
        lines += ["", f"## Basis guard (CR-140 / A4)", "", f"⚠ BASIS SUSPICION: {basis_suspicion}."]
    lines += ["", f"**Verdict: {verdict}.** Driving SR(s) "
              f"{'within' if driving_ok else 'NOT within'} ±{args.driving_tol*100:.0f}%; "
              f"worst driving residual = {worst_s} (bound {args.mu95_bound*100:.0f}%)"
              + (f"; driving SR compared OFF the published grid (extrapolation, not a node)."
                 if driving_off_grid else ".")
              + (f" FAIL CAUSE: {fail_reason}." if fail_reason else "")
              + " This checks point-estimate selection agreement at the stated normalization; it "
                "does not isolate detector response or certify statistical coverage. MC and published "
                "uncertainties are not propagated. A discrepancy requires diagnosis of selection, "
                "normalization, generation and detector response before any retuning."]
    certification_metadata = {}
    if args.certification_context:
        from ravel.validation.certificates import acceptance_points, read_json, digest
        certification_metadata["validation_points"] = acceptance_points(rows, read_json(args.certification_context))
        certification_metadata["certification_producer"] = {"module": "ravel.validation.certify_acceptance",
                                                            "sha256": digest(__file__)}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    open(args.out, "w").write("\n".join(lines) + "\n")
    json.dump({"label": args.label, "grid": args.grid, "m_parent": args.m_parent, "splitting": splitting,
               **comparison_metadata(rows), **certification_metadata,
               "verdict": verdict, "driving_tol": args.driving_tol, "mu95_bound": args.mu95_bound,
               "worst_driving_residual": worst_driving, "driving_off_grid": driving_off_grid,
               "driving_reference_unmatched": driving_nearest,
               "fail_reason": fail_reason, "basis_suspicion": basis_suspicion,
               "rows": [{k: r[k] for k in ("sr", "region", "role", "mine", "pub", "events", "node",
                                           "ratio", "ok", "mu95_impact", "off_grid", "attribution", "inverse_signal_limit_shift")}
                        for r in rows]},
              open(args.out.replace(".md", ".json"), "w"), indent=2, allow_nan=False)
    print(f"{verdict}: driving={'ok' if driving_ok else 'OFF'} worst-residual={worst_s} "
          f"({len(attribs)} attributed){' OFF-GRID' if driving_off_grid else ''} -> {args.out}")
    if fail_reason:
        print(f"  FAIL CAUSE: {fail_reason}")
    if basis_suspicion:
        print(f"  BASIS SUSPICION (CR-140/A4): {basis_suspicion}")
    for r in rows:
        node_flag = "" if (r["node"] or "").startswith("grid node") else f"  [{r['node']}]"
        print(f"  {r['sr']:20s} {r['role']:12s} ratio={'-' if r['ratio'] is None else round(r['ratio'],2)} "
              f"{'OK' if r['ok'] else 'x'}{node_flag}")


if __name__ == "__main__":
    main()
