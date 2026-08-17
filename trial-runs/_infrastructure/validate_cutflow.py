#!/usr/bin/env python
"""Certify a run's signal acceptance×efficiency against the analysis's PUBLISHED values.

This is the physics-validation gate (R1): the pipeline is only trustworthy for new models if it
reproduces the experiment's own acceptance×efficiency for a benchmark the authors did publish.
A×ε is a ratio (selected/generated), so it is independent of cross-section and luminosity — it
isolates the fidelity of the generation→shower→detector→selection chain.

For each signal region:
  my A×ε   = (routine's normalised SR yield) / (sigma[fb] * lumi[fb])   [= selected_weight/sumW]
  pub A×ε  = the published "acceptance times efficiency for <SR> in <model> direct decay" grid,
             read at the model's (parent, LSP) mass point (nearest grid node).
Reports per-SR ratio + an overall verdict (default tolerance 30%, per reinterpretation practice),
and writes a certification md+json under framework/validation/.

SR reader (pluggable; see the EWK jigsaw run's STUMBLES S6/S8 — folds in the run-local adapter):
  `--sr-reader auto|counter|cutflow` selects how the routine's per-SR A×ε is read from the YODA:
  - **counter** (the historic path): `/routine/<SR>` is a **scalar** counter (`Estimate0D`, has
    `.val()`) holding signal events at lumi; A×ε = val/(σ·lumi).
  - **cutflow**: `/routine/<SR>` is a **Cutflow** (`BinnedEstimate1D`, has `.bins()`) — e.g. a
    recursive-jigsaw EWK search books only cutflows, no scalar counter. Its per-SR A×ε is the
    **last/first cutflow bin** (a ratio of two bins of the SAME cutflow ⇒ invariant under the
    routine's `normalizeFirst(scale)` in finalize(); first bin = pre-selection stage, last = full SR).
    The events-at-lumi used for tail classification is then A×ε·σ·lumi (the counter relation, inverted).
  - **auto** (default): per SR, look up `/routine/<SR>` and dispatch by object kind — `.val()` ⇒
    counter, else `.bins()` ⇒ cutflow. Mixed routines resolve per object. Both readers feed the SAME
    tiered + attribution + µ₉₅-bound cert below unchanged; the counter case is bit-identical to before.
  This makes the run-local `certify_axe.py` adapter (which clones this file's verdict logic for the
  cutflow case) unnecessary for any routine whose published grid `published_axe()` can resolve.
  - Grid lookup (upgraded Session 2/S4): `published_axe()` uses an exact node when one exists
    (bit-identical to the historic nearest-node behaviour there), else a **1-D linear interpolation**
    when the requested point is bracketed along ONE axis by nodes sharing the other coordinate
    (fixed-LSP interpolation along the splitting axis preferred — the physically correct direction,
    mirroring the adapter above; brackets wider than --interp-max-span are not trusted), else the
    legacy nearest node, flagged `NEAREST` in the per-SR `node` field (output rows + JSON) because
    on a coarse/edge grid it can compare against the wrong mass-splitting and flip the verdict.

SR roles come from --exclusion (driving = best/near-best expected µ). For a demo/variant run with
no exclusion.json of its own (or a foreign one), --driving-sr-override forces named SRs to driving.

Exit codes: 0 whenever a certification was produced (PASS/WARN/FAIL is the `verdict` field in the
JSON — the benchmark gate parses that, not the exit code); nonzero only for unusable inputs
(σ≤0, lumi≤0, unreadable files).

Usage:
  validate_cutflow.py --signal SIG.yoda --routine NAME --sigma-pb S --lumi-fb L \
      --tables-dir DIR --grid "gluino direct decay" --m-parent 1000 --m-lsp 100 \
      --srs 2jl,2jm,2jt,4jt,5j,6jm,6jt --label "gluino(1000,100)" --out framework/validation/NAME.md
"""
import argparse, glob, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def published_axe(tables_dir, sr, grid, m_parent, m_lsp, node_tol=1.0, interp_max_span=200.0):
    """Find the acc×eff table for <sr> in <grid> and return (value, node_descriptor).

    Lookup order (the descriptor records which path was taken — it lands in the output rows):
      1. EXACT grid node (both coordinates within node_tol, ~1 GeV): identical value and
         descriptor to the historic nearest-node lookup there (bit-identical certifications).
      2. 1-D linear interpolation when the point is bracketed along ONE axis by two nodes
         sharing the other coordinate: fixed-LSP interpolation along the parent/splitting axis
         preferred (A×ε varies fastest with the mass splitting — the physically correct 1-D
         interpolation, as the ins1676551 run-local adapter does), else fixed-parent along LSP.
         No extrapolation outside the bracketing nodes, and ONLY across brackets no wider than
         interp_max_span (default 200 GeV ≈ one cell of the published checkerboard grids):
         linear interpolation is only valid where the grid is locally fine — across a 600 GeV
         gap A×ε changes ~5× and is strongly nonlinear (observed: ins1458270 gluino grid at
         m_gluino=1000 has only m_LSP ∈ {0,600,800}).
      3. Legacy nearest node, flagged NEAREST: on a coarse/edge grid this can compare against
         the wrong mass-splitting and bias or flip the verdict (observed on ins1676551, and on
         the ins1458270 gluino point (1000,100) which has NO exact node — nearest is (1000,0),
         a distance-100 tie with (1100,100) resolved by file order) — inspect it.
    """
    import yaml
    subs = glob.glob(os.path.join(tables_dir, "**", "submission.yaml"), recursive=True)
    if not subs:
        return None, "no submission.yaml"
    base = os.path.dirname(subs[0])
    want = re.compile(rf"acceptance times efficiency.*\bSR{re.escape(sr)}\b.*{re.escape(grid)}", re.I)
    target = None
    for doc in yaml.safe_load_all(open(subs[0], errors="replace")):
        if isinstance(doc, dict) and want.search((doc.get("description") or "")):
            target = doc.get("data_file")
            break
    if not target:
        return None, f"no acc×eff table for {sr} in '{grid}'"
    d = yaml.safe_load(open(os.path.join(base, target), errors="replace"))
    iv = d["independent_variables"]; dv = d["dependent_variables"][0]["values"]
    pm = [x["value"] for x in iv[0]["values"]]; lm = [x["value"] for x in iv[1]["values"]]
    pts = [(pm[i], lm[i], dv[i]["value"]) for i in range(len(pm))]
    # 1) exact node — same value + descriptor as the historic nearest-node lookup at a node
    for a, b, v in pts:
        if abs(a - m_parent) < node_tol and abs(b - m_lsp) < node_tol:
            return v, f"grid node (m_parent={a:.0f}, m_lsp={b:.0f})"
    # 2) 1-D bracket interpolation, fixed-LSP (splitting axis) first, then fixed-parent
    for axis in ("lsp", "parent"):
        if axis == "lsp":
            same = sorted((a, v) for a, b, v in pts if abs(b - m_lsp) < node_tol)
            x = m_parent
        else:
            same = sorted((b, v) for a, b, v in pts if abs(a - m_parent) < node_tol)
            x = m_lsp
        lo = max(((xx, vv) for xx, vv in same if xx <= x), default=None)
        hi = min(((xx, vv) for xx, vv in same if xx >= x), default=None)
        if lo and hi and lo[0] != hi[0] and (hi[0] - lo[0]) <= interp_max_span:
            f = (x - lo[0]) / (hi[0] - lo[0])
            val = lo[1] + f * (hi[1] - lo[1])
            if axis == "lsp":
                return val, f"interp@m_lsp={m_lsp:g}: m_parent {lo[0]:g}->{hi[0]:g}"
            return val, f"interp@m_parent={m_parent:g}: m_lsp {lo[0]:g}->{hi[0]:g}"
    # 3) legacy nearest-node fallback — flagged, since it can flip the verdict on coarse grids
    best, bd = None, 1e18
    for a, b, v in pts:
        dist = (a - m_parent) ** 2 + (b - m_lsp) ** 2
        if dist < bd:
            bd, best = dist, (a, b, v)
    return best[2], (f"NEAREST grid node (m_parent={best[0]:.0f}, m_lsp={best[1]:.0f}) — "
                     f"no exact node or 1-D bracket ≤{interp_max_span:g} GeV at "
                     f"({m_parent:g},{m_lsp:g}); coarse-grid caution")


def read_sr_axe(obj, sr_reader, sigma_fb, lumi_fb):
    """Read one SR object → (axe, signal_events_at_lumi).

    Returns (None, None) when the object is absent or unreadable, so the existing formatter
    renders '-' and `classify` treats it as a tail (mirrors the historic missing-SR behaviour).

      counter: obj is a scalar counter (Estimate0D, `.val()` = signal events at lumi);
               A×ε = val/(σ·lumi)  [the historic, bit-identical path].
      cutflow: obj is a Cutflow (BinnedEstimate1D, `.bins()`); A×ε = last_bin/first_bin
               (normalisation-invariant); events-at-lumi = A×ε·σ·lumi (counter relation, inverted).
      auto:    `.val()` ⇒ counter, else `.bins()` ⇒ cutflow; resolved per object.
    """
    if obj is None:
        return None, None
    denom = sigma_fb * lumi_fb
    has_val = hasattr(obj, "val")
    has_bins = hasattr(obj, "bins")
    mode = sr_reader
    if mode == "auto":
        mode = "counter" if has_val else ("cutflow" if has_bins else None)
    if mode == "counter":
        if not has_val:
            return None, None
        norm = obj.val()                       # signal events at lumi
        return (norm / denom if denom else None), norm
    if mode == "cutflow":
        if not has_bins:
            return None, None
        vals = [b.val() for b in obj.bins()]
        if not vals or vals[0] == 0:
            return None, None
        axe = vals[-1] / vals[0]               # last/first = selected/generated (σ-independent)
        return axe, axe * denom                # events at lumi via the counter relation
    return None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--signal", required=True)
    ap.add_argument("--routine", required=True)
    ap.add_argument("--sigma-pb", type=float, required=True)
    ap.add_argument("--lumi-fb", type=float, required=True)
    ap.add_argument("--tables-dir", required=True)
    ap.add_argument("--grid", required=True, help="e.g. 'gluino direct decay' or 'squark direct decay'")
    ap.add_argument("--m-parent", type=float, required=True)
    ap.add_argument("--m-lsp", type=float, required=True)
    ap.add_argument("--srs", required=True)
    ap.add_argument("--sr-reader", choices=("auto", "counter", "cutflow"), default="auto",
                    help="how to read each /routine/<SR> object: 'counter' (scalar Estimate0D, the "
                         "historic path), 'cutflow' (Cutflow BinnedEstimate1D → A×ε=last/first bin, "
                         "e.g. recursive-jigsaw EWK searches), or 'auto' (default: .val()⇒counter "
                         "else .bins()⇒cutflow, resolved per object). Both feed the same cert below.")
    ap.add_argument("--label", default="")
    ap.add_argument("--exclusion", help="the run's exclusion.json (per-SR µ → SR roles)")
    ap.add_argument("--driving-sr-override", default="",
                    help="comma list of SR names to FORCE role=driving — for demo/variant runs "
                         "certified without their own exclusion.json (none supplied, or a foreign "
                         "run's). Certified production runs should pass --exclusion instead; the "
                         "override wins over the exclusion-derived role for the named SRs.")
    ap.add_argument("--driving-tol", type=float, default=0.15, help="tolerance for exclusion-driving SRs")
    ap.add_argument("--contributing-tol", type=float, default=0.25)
    ap.add_argument("--mu95-bound", type=float, default=0.10, help="max allowed |Δµ₉₅|/µ₉₅ from a driving residual")
    ap.add_argument("--interp-max-span", type=float, default=200.0,
                    help="widest bracket (GeV) across which the off-node 1-D grid interpolation is "
                         "trusted (≈ one cell of the published grid); wider gaps fall back to the "
                         "flagged nearest node — linear interp across a sparse-grid chasm is not physical")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.sigma_pb <= 0:
        sys.exit(f"ERROR: --sigma-pb must be > 0 (got {args.sigma_pb}) — A×ε = yield/(σ·lumi) is undefined")
    if args.lumi_fb <= 0:
        sys.exit(f"ERROR: --lumi-fb must be > 0 (got {args.lumi_fb})")

    import yoda
    sig = yoda.read(args.signal)
    sigma_fb = args.sigma_pb * 1000.0
    override = {s.strip() for s in args.driving_sr_override.split(",") if s.strip()}

    # SR roles from the exclusion: driving = best-expected SR + any within 1.5x its expected µ
    per_sr, best_sr = {}, None
    if args.exclusion and os.path.exists(args.exclusion):
        ex = json.load(open(args.exclusion))
        per_sr = ex.get("per_sr", {}); best_sr = ex.get("best_sr")
    best_exp = per_sr.get(best_sr, {}).get("exp_median") if best_sr else None

    def classify(sr, signal_events):
        if sr in override:
            return "driving"
        info = per_sr.get(sr, {})
        if signal_events is not None and signal_events < 5:
            return "tail"
        if sr == best_sr or (best_exp and info.get("exp_median") and info["exp_median"] <= 1.5 * best_exp):
            return "driving"
        return "contributing"

    def cause_class(sr, ratio):
        if ratio is None: return "selection-mapping"
        if ratio < 1 and any(j in sr for j in ("4j", "5j", "6j", "7j", "8j")):
            return "merging"            # high-jet-multiplicity deficit ⇒ missing ME multiplicity
        if any(l in sr.lower() for l in ("l-", "ll", "lep", "ee", "mm", "3l", "2l")):
            return "fast-sim-floor"     # lepton SRs ⇒ soft-lepton efficiency / fast-sim
        return "fast-sim-floor"

    rows = []
    for sr in args.srs.split(","):
        sr = sr.strip()
        o = sig.get(f"/{args.routine}/{sr}")
        mine, norm = read_sr_axe(o, args.sr_reader, sigma_fb, args.lumi_fb)       # A×ε, signal events at lumi
        pub, node = published_axe(args.tables_dir, sr, args.grid, args.m_parent, args.m_lsp,
                                  interp_max_span=args.interp_max_span)
        ratio = (mine / pub) if (mine and pub) else None
        role = classify(sr, norm)
        tol = args.driving_tol if role == "driving" else (args.contributing_tol if role == "contributing" else None)
        resid = abs(1 - ratio) if ratio is not None else None
        ok = (tol is None) or (resid is not None and resid <= tol)
        mu95_impact = resid if (role == "driving" and resid is not None) else None  # µ95 ∝ 1/driving-signal
        attribution = None
        if resid is not None and tol is not None and resid > tol:
            attribution = {"sr": sr, "ratio": round(ratio, 3), "role": role,
                           "residual_pct": round(resid * 100), "cause_class": cause_class(sr, ratio),
                           "mu95_impact_pct": (round(mu95_impact * 100) if mu95_impact is not None else None),
                           "note": "[Opus to confirm physical cause]"}
        rows.append(dict(sr=sr, mine=mine, pub=pub, ratio=ratio, role=role, tol=tol, ok=ok,
                         signal=norm, mu95_impact=mu95_impact, node=node, attribution=attribution))

    driving = [r for r in rows if r["role"] == "driving"]
    # the counting-model µ₉₅ is set by the single most-sensitive (best) SR, so the limit's
    # reliability is that SR's residual; near-best driving SRs are checked too but do not move µ₉₅.
    best_row = next((r for r in rows if r["sr"] == best_sr), None)
    best_resid = best_row["mu95_impact"] if (best_row and best_row["mu95_impact"] is not None) else \
                 (max((r["mu95_impact"] for r in driving if r["mu95_impact"] is not None), default=0.0))
    driving_ok = all(r["ok"] for r in driving) if driving else None
    worst_driving = best_resid
    if driving and driving_ok and best_resid <= args.mu95_bound:
        verdict = "PASS"
    elif best_resid <= 1.5 * args.mu95_bound:
        verdict = "WARN"   # the limit-setting SR is within 1.5× the bound; residuals bounded + attributed
    else:
        verdict = "FAIL"   # the best SR is off enough that µ₉₅ (and maybe the verdict) is unreliable

    lines = [f"# A×ε certification (tiered + attribution) — {args.routine} · {args.label}", "",
             f"A×ε = (routine SR yield)/(σ·lumi); published = '{args.grid}' acc×eff at "
             f"(m_parent={args.m_parent:.0f}, m_LSP={args.m_lsp:.0f}). Driving SRs ≤{args.driving_tol*100:.0f}%, "
             f"contributing ≤{args.contributing_tol*100:.0f}%, tail report-only; driving |Δµ₉₅| ≤"
             f"{args.mu95_bound*100:.0f}%. Driving SR(s) from exclusion.json best/near-best expected µ.", "",
             "| SR | role | my A×ε | pub A×ε | node | ratio | tol | ok | µ₉₅ impact |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        mine_s = "-" if r['mine'] is None else f"{r['mine']:.4g}"
        pub_s  = "-" if r['pub'] is None else f"{r['pub']:.4g}"
        rat_s  = "-" if r['ratio'] is None else f"{r['ratio']:.2f}"
        tol_s  = "-" if r['tol'] is None else f"{r['tol']*100:.0f}%"
        mu_s   = "-" if r['mu95_impact'] is None else f"{r['mu95_impact']*100:.0f}%"
        ok_s   = "✓" if r['ok'] else "✗"
        lines.append(f"| {r['sr']} | {r['role']} | {mine_s} | {pub_s} | {r['node']} | {rat_s} | {tol_s} | {ok_s} | {mu_s} |")
    attribs = [r["attribution"] for r in rows if r["attribution"]]
    if attribs:
        lines += ["", "## Attribution (residuals above tier tolerance)", ""]
        for a in attribs:
            lines.append(f"- **{a['sr']}** ({a['role']}): ratio {a['ratio']}, residual {a['residual_pct']}% → "
                         f"`{a['cause_class']}`, µ₉₅ impact {a['mu95_impact_pct']}%. {a['note']}")
    lines += ["", f"**Verdict: {verdict}.** Driving SR(s) {'within' if driving_ok else 'NOT within'} "
              f"±{args.driving_tol*100:.0f}%; worst driving |Δµ₉₅| = {worst_driving*100:.0f}% "
              f"(bound {args.mu95_bound*100:.0f}%). A×ε is σ-independent — this certifies selection fidelity; "
              "the absolute limit uses the NLO+NLL σ (`nlo_xsec.py`)."]
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    open(args.out, "w").write("\n".join(lines) + "\n")
    json.dump({"routine": args.routine, "label": args.label, "verdict": verdict,
               "driving_tol": args.driving_tol, "mu95_bound": args.mu95_bound,
               "worst_driving_mu95_impact": worst_driving,
               "rows": [{k: r[k] for k in ("sr", "role", "mine", "pub", "node", "ratio", "ok", "mu95_impact", "attribution")}
                        for r in rows]},
              open(args.out.replace(".md", ".json"), "w"), indent=2)
    print(f"{verdict}: driving={'ok' if driving_ok else 'OFF'} worst|Δµ95|={worst_driving*100:.0f}% "
          f"({len(attribs)} attributed) -> {args.out}")
    for r in rows:
        node_flag = "" if (r['node'] or "").startswith("grid node") else f"  [{r['node']}]"
        print(f"  {r['sr']:5s} {r['role']:12s} ratio={'-' if r['ratio'] is None else round(r['ratio'],2)} "
              f"{'OK' if r['ok'] else 'x'}{node_flag}")


if __name__ == "__main__":
    main()
