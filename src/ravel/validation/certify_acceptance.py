#!/usr/bin/env python
"""Certify a SimpleAnalysis/Delphes run's per-SR acceptance×efficiency against the PUBLISHED map.

This is the SimpleAnalysis/Delphes-path analog of `validate_cutflow.py` (the Rivet-path R1 gate): the
*measurable detector-fidelity gate*. The fast-sim (Delphes) object efficiencies are the dominant lever
on acceptance for soft-lepton analyses; if they are not matched to the analysis's published efficiency
curves, the per-SR A×ε comes out wrong and the limit is untrustworthy. Rather than hand-tune per
analysis, this tool turns "did the detector model reproduce the published A×ε?" into a number, with the
same tiered + attribution + three-state verdict schema as `validate_cutflow.py` so it slots into the
same benchmark gate (which parses the `verdict` JSON field).

A×ε is a ratio (selected/generated), so it is cross-section- and luminosity-independent — it isolates
the fidelity of the generation -> shower -> detector -> selection chain.

For each signal region:
  my A×ε   = the routine's per-SR acceptance = (selected events)/(generated events).
             SimpleAnalysis writes this directly as the `acceptance` column of its yields file.
  pub A×ε  = published acceptance x efficiency at the model's (parent mass, mass-splitting) point.
             Some HEPData records (e.g. ins1767649 Fig 32) publish ACCEPTANCE and EFFICIENCY as two
             separate tables per signal region; the published A×ε is then the ELEMENTWISE PRODUCT
             acc x eff at the SAME grid node (see --acc-unit-scale for the z-axis 1e-3 convention).
Reports per-SR ratio + an overall verdict and writes a certification md+json.

Published-map lookup (`published_acceff`, mirrors validate_cutflow.py's 3-tier `published_axe`):
  Locates the acceptance table and (optionally) the efficiency table for a published signal region by
  regex-matching the submission.yaml `description`, reads each at the requested (m_parent, m_lsp/Δm)
  grid point, and multiplies. The node lookup is three-tier and the chosen path is recorded in the
  per-SR `node` descriptor (which lands in the md rows and the json):
    1. EXACT grid node (both coordinates within node_tol ~1 GeV).
    2. 1-D LINEAR INTERPOLATION when bracketed along ONE axis by two nodes sharing the other
       coordinate (fixed-mass interpolation along the splitting axis preferred — A×ε varies fastest
       with the mass splitting), only across brackets <= --interp-max-span.
    3. Legacy NEAREST node, FLAGGED, when there is no exact node and no valid bracket. This is the
       honest off-grid case: e.g. a Δm=50 point requested against a published map whose maximum
       published Δm is 40 is an EXTRAPOLATION, not a node and not a bracket — the descriptor says so
       ("NEAREST ... point outside published acc×eff grid; coarse-grid caution") and the verdict
       carries that flag so the reader never mistakes an off-grid comparison for an on-grid one.

SR axis convention: the grid is indexed by (parent mass, splitting). Pass the splitting as either
--m-lsp (LSP mass; Δm = m_parent - m_lsp) or --dm (the splitting directly). The published Fig 32 family
is indexed by (m(slepton), Δm) so --dm maps to the second axis directly; if --m-lsp is given and the
table's second axis is the splitting, Δm = m_parent - m_lsp is used.

Tiers (identical policy to validate_cutflow.py): a SR with < --tail-events selected events is a TAIL
(report-only, no tolerance — at single-digit occupancy the per-SR A×ε is statistically meaningless);
the SR with the most selected events is DRIVING (and any within --driving-factor x its yield), checked
to --driving-tol; the rest are CONTRIBUTING, checked to --contributing-tol. --driving-sr-override forces
named SRs to driving. Every residual above its tier tolerance emits an attribution row with a
cause_class (here `fast-sim-floor` for the soft-lepton-efficiency / Delphes-card mismatch this gate is
built to catch, plus `merging` / `selection-mapping` / `off-grid` / `statistics`).

Verdict: a HARD-FAIL gate runs FIRST — the comparison must be USABLE before any PASS/WARN is possible.
It FAILs immediately when there is no driving SR (e.g. an all-zero dead-sim where every SR is below the
tail threshold), when driving_ok is False, or when no computable driving residual exists. driving_ok is
False for TWO distinct reasons and the printed FAIL CAUSE names which one fired (they demand opposite
fixes): (a) UNEVALUABLE — a driving SR has no computable ratio (wrong --grid, missing/unmapped tables,
missing routine yield) → the comparison is unusable, fix the INPUTS; (b) EVALUATED-BUT-OVER-TOLERANCE —
the driving SR was read at a real published node and its residual missed --driving-tol → the comparison
WORKED and the run failed the fidelity gate, fix the PHYSICS (detector model / merging / σ basis), not
the lookup. A blank or wrong comparison is NEVER laundered into WARN, and a worst-residual of '-' (no
residual) is never shown as 0%. If the comparison is usable: PASS = a driving SR exists, all driving SRs within tol, AND
the worst driving residual <= --mu95-bound, AND no driving SR fell back to an off-grid NEAREST node;
WARN = bounded (worst driving <= 1.5x the bound) and attributed; FAIL otherwise (or when the only
comparison available is off-grid). Exit code is 0 whenever a certification is produced (PASS/WARN/FAIL
is the `verdict` JSON field, which the benchmark gate parses); nonzero only for unusable inputs (an
unparseable acceptance file exits non-zero with a one-line ERROR, not a traceback).

Denominator-basis guard (CR-140, catalogue A4 at the cert surface): my A×ε divides by the GENERATED
event count — i.e. by whatever σ-slice was actually generated. If the sample was generation-TAGGED
(an ISR-jet-tagged or decay-filtered subprocess, σ_tag from logs/madgraph.log) while the published
A×ε is normalized to the INCLUSIVE simplified-model σ, every SR comes out high by the SAME factor
≈ σ_incl/σ_tag (the flagship re-hit was a uniform ~2.7× excess). This tool cannot see the generation
log, so it fingerprints the symptom instead (mirroring scan_contour._basis_guard's role at the limit
surface): a uniform ratio (max/min ≤ 1.25) across ≥2 evaluated non-tail SRs, with the common ratio
≥20% from unity, prints a loud BASIS SUSPICION warning — excess direction names the A4 tagged-vs-
inclusive trap, deficit direction names the global single-cause suspects (merging / k-factor / fast-
sim floor). The warning also lands in the md and as `basis_suspicion` in the json; it never changes
the verdict. Conversion recipe before re-certifying on the inclusive basis:
A×ε_incl = A×ε_tag × f with f = σ_tag/σ_incl_LO, BOTH from the same σ table the scan rebase uses
(`scan_orchestrator.py rebase <scandir> --process <p>`); never mix a generation-log σ with a
model-σ table.

Usage:
  certify_acceptance.py --acceptance EwkCompressed2018.txt --tables-dir HEPData-...-yaml \
      --grid slepton --m-parent 200 --dm 50 \
      --srs SR_S_iMT2a,SR_S_high_iMT2a,SR_S_low_iMT2a \
      --label "slepton(200,150) Δm=50" --out evidence/validation/studies/slepton_acceff.md
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.validation"


import argparse, glob, json, math, os, re, sys



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
    pts = [(pm[i], lm[i], dv[i]["value"]) for i in range(len(pm))]
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
        # acceptance only (no separate efficiency published) — return scaled acceptance, note it.
        return av * acc_unit_scale, anode + " [acceptance only, no eff table]", aog
    ev, enode, eog = _read_grid_table(base, eff_file, m_parent, splitting, node_tol, interp_max_span)
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
    if path.endswith(".json"):
        data = json.load(open(path))
        srs = data.get("sr_yields", data) if isinstance(data, dict) else data
        for sr, rec in srs.items():
            if isinstance(rec, dict):
                acc = rec.get("acceptance")
                if acc is None and "events" in rec and "n_generated" in rec:
                    acc = rec["events"] / rec["n_generated"] if rec["n_generated"] else None
                out[sr] = (acc, rec.get("events"))
            else:
                out[sr] = (float(rec), None)
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
                try:
                    ev = int(float(f[i_ev]))
                except ValueError:
                    ev = None
            out[sr] = (acc, ev)
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
    args = ap.parse_args()

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
        # this gate exists for soft-lepton fast-sim efficiency mismatch (the Delphes-card lever)
        return "fast-sim-floor"

    rows = []
    for r in raw:
        role = classify(r)
        ratio = (r["mine"] / r["pub"]) if (r["mine"] and r["pub"]) else None
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
                           "note": "[Opus to confirm physical cause]"}
        rows.append(dict(sr=r["sr"], region=r["region"], mine=r["mine"], pub=r["pub"], events=r["events"],
                         ratio=ratio, role=role, tol=tol, ok=ok, mu95_impact=mu95_impact,
                         node=r["node"], off_grid=r["off_grid"], attribution=attribution))

    driving = [r for r in rows if r["role"] == "driving"]
    best_row = next((r for r in rows if r["sr"] == best_sr), None)
    # The worst driving residual is an HONEST None when no driving SR yielded a computable residual —
    # NOT 0.0. A default of 0.0 here is the laundering bug: it makes an unusable comparison (dead-sim,
    # wrong --grid, missing tables, empty file → every driving residual unevaluable) look like a
    # perfect 0% residual that sails under the bound into WARN. Keep it None so the gate below can tell
    # 'no residual' apart from 'a real 0% residual'.
    driving_resids = [r["mu95_impact"] for r in driving if r["mu95_impact"] is not None]
    if best_row and best_row["mu95_impact"] is not None:
        best_resid = best_row["mu95_impact"]
    elif driving_resids:
        best_resid = max(driving_resids)
    else:
        best_resid = None
    driving_ok = all(r["ok"] for r in driving) if driving else None
    driving_off_grid = any(r["off_grid"] for r in driving)
    worst_driving = best_resid

    # CR-140 denominator-basis guard (catalogue A4 at the cert surface; see the docstring recipe).
    # A UNIFORM ratio across every evaluated non-tail SR fingerprints a single GLOBAL-normalization
    # cause, not per-SR selection physics. Excess direction = the tagged-sample-denominator trap
    # (my A×ε high by ≈ σ_incl/σ_tag everywhere); deficit direction = a global suspect (merging /
    # k-factor basis / fast-sim floor). Warn loudly; never changes the verdict.
    basis_suspicion = None
    evald = [r for r in rows if r["ratio"] is not None and r["ratio"] > 0 and r["role"] != "tail"]
    if len(evald) >= 2:
        rats = sorted(r["ratio"] for r in evald)
        if rats[-1] / rats[0] <= 1.25:
            gm = math.exp(sum(math.log(x) for x in rats) / len(rats))
            if gm >= 1.2:
                basis_suspicion = (
                    f"uniform ~{gm:.2f}× EXCESS across all {len(evald)} evaluated SRs — the A4 "
                    "σ-basis signature: the acceptance denominator is likely the TAGGED generated "
                    "sample (generation-log σ) while the published A×ε denominator is the INCLUSIVE "
                    "model σ. Convert before re-certifying: A×ε_incl = A×ε_tag × f, "
                    "f = σ_tag/σ_incl_LO, both from the same σ table the scan rebase uses "
                    "(scan_orchestrator.py rebase <scandir> --process <p>)")
            elif gm <= 1 / 1.2:
                basis_suspicion = (
                    f"uniform ~{gm:.2f}× DEFICIT across all {len(evald)} evaluated SRs — a single "
                    "global cause (ME/PS merging missing, k-factor/σ basis, fast-sim efficiency "
                    "floor) rather than per-SR selection mapping; decompose the global "
                    "normalization before touching cuts")

    # HARD-FAIL gate, evaluated BEFORE the PASS/WARN/FAIL ladder. A certification is only meaningful if
    # there is a driving SR AND it was actually evaluated (a real residual against a real published
    # value). Any of these means the comparison is unusable and must FAIL LOUDLY, never WARN:
    #   • no driving SR at all (e.g. an all-zero dead-sim where every SR fell below --tail-events), or
    #   • driving_ok is False — either a driving SR could not be evaluated (missing/unmapped published
    #     value from a wrong --grid or absent tables, or a missing routine yield) OR it was evaluated
    #     and missed --driving-tol; the fail_reason below names which cause actually fired, or
    #   • best_resid is None (no driving SR produced a computable residual — the 0.0 laundering case).
    # This is the LOUD failure a physicist needs: a blank/wrong comparison can never read as 'bounded'.
    if (driving is None) or (not driving) or (driving_ok is False) or (best_resid is None):
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
              + " A×ε is σ-independent — this certifies the detector-model fidelity (the Delphes "
                "object efficiencies); a FAIL here means tune the fast-sim efficiencies to the "
                "published curves and re-certify (or, for an unusable comparison, fix the inputs above)."]
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    open(args.out, "w").write("\n".join(lines) + "\n")
    json.dump({"label": args.label, "grid": args.grid, "m_parent": args.m_parent, "splitting": splitting,
               "verdict": verdict, "driving_tol": args.driving_tol, "mu95_bound": args.mu95_bound,
               "worst_driving_residual": worst_driving, "driving_off_grid": driving_off_grid,
               "fail_reason": fail_reason, "basis_suspicion": basis_suspicion,
               "rows": [{k: r[k] for k in ("sr", "region", "role", "mine", "pub", "events", "node",
                                           "ratio", "ok", "mu95_impact", "off_grid", "attribution")}
                        for r in rows]},
              open(args.out.replace(".md", ".json"), "w"), indent=2)
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
