#!/usr/bin/env python
"""Compare a run's selection acceptance times efficiency with published values.

This is a benchmark point-estimate comparison of the generation, shower, detector
and selection chain. It does not isolate detector efficiency or establish CLs
coverage. Cross-section cancellation requires a consistent generated-process and
normalization basis on both sides.

--sr-reader counter reads A×ε = normalized SR yield / (sigma[fb] * lumi[fb]).
--sr-reader cutflow reads last/first bin. The first bin MUST count the uncut
generated sample; otherwise this is conditional acceptance. This tool cannot
verify that semantic assumption from anonymous bin values. auto chooses by the
YODA object interface (.val() for counter, otherwise .bins() for cutflow).

Published reference lookup uses a node within 1 GeV, then local 1-D linear
interpolation across at most --interp-max-span. Interpolation is an approximation
without propagated interpolation uncertainty. A NEAREST reference is retained
for diagnosis but cannot certify a driving region at a different mass point.

Driving regions come from --exclusion (best/near-best expected sensitivity), or
--driving-sr-override. The maximum residual across ALL driving regions controls
the verdict. Missing driving evidence, no driving region, or an unmatched driving
reference means FAIL. Zero selected acceptance against positive published
acceptance is a measured 100% deficit, never missing data. Tails are report-only.

The legacy mu95_impact fields store abs(mine/published - 1), a selection residual
proxy. The separate inverse_signal_limit_shift is 1/ratio - 1, valid only for a
uniform rescaling of the complete signal template with the model otherwise fixed.
Neither quantity is a propagated likelihood uncertainty. MC and published
uncertainties are not propagated, and discrepancy causes remain unresolved.

Exit code 0 means a report was produced; consumers MUST read its PASS/WARN/FAIL
verdict. Input parse/validation failures exit nonzero. Output is Markdown + JSON.

Example:
  validate_cutflow.py --signal SIG.yoda --routine NAME --sigma-pb S --lumi-fb L
      --tables-dir DIR --grid "gluino direct decay" --m-parent 1000 --m-lsp 100
      --srs 2jl,2jm,2jt,4jt,5j,6jm,6jt --out acceptance-certification.md
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.validation"


import argparse, glob, json, math, numbers, os, re, sys


def finite_nonnegative(value, name, *, positive=False):
    """Validate measurements without converting booleans, strings, or NaN into evidence."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return value


def unique_json_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def comparison_metadata(rows):
    """Point-estimate acceptance agreement is neither a fit nor detector certification."""
    evaluated = sum(r["ratio"] is not None for r in rows)
    return {
        "comparison_counts": {"requested": len(rows), "evaluated": evaluated,
                              "missing": len(rows) - evaluated},
        "scope": "selection acceptance times efficiency at the stated benchmark and normalization",
        "uncertainty_treatment": "point-estimate residuals; MC and published uncertainties are not propagated",
        "attribution_status": "diagnostic hypotheses only; no physical cause is established by this comparison",
        "mu95_impact_semantics": "legacy name for abs(mine/published - 1), an acceptance residual proxy; "
                                 "not a likelihood-derived limit uncertainty",
        "inverse_signal_limit_shift_semantics": "signed 1/ratio - 1: exact only if the complete signal "
                                                "template rescales uniformly with background/model fixed; "
                                                "not a multiregion uncertainty estimate",
    }


def comparison_ratio(mine, published):
    if mine is not None:
        finite_nonnegative(mine, "measured A×ε")
    if published is not None:
        finite_nonnegative(published, "published A×ε")
    if mine is None or published is None or published == 0:
        return None
    return finite_nonnegative(mine / published, "A×ε ratio")


def inverse_signal_shift(ratio):
    """Conditional algebraic rescaling, kept separate from the residual gate."""
    if ratio is None or ratio == 0:
        return None
    shift = 1 / ratio - 1
    return shift if math.isfinite(shift) else None



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
         a distance-100 tie with (1100,100) resolved by file order). Its numerical residual
         is diagnostic only: a driving nearest-node comparison cannot certify this mass point.
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
    if not pm or len(pm) != len(lm) or len(pm) != len(dv):
        raise ValueError("published A×ε table has empty or misaligned grid columns")
    pts = [(finite_nonnegative(pm[i], "published parent mass"),
            finite_nonnegative(lm[i], "published LSP mass"),
            finite_nonnegative(dv[i]["value"], "published A×ε")) for i in range(len(pm))]
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
    sigma_fb = finite_nonnegative(sigma_fb, "sigma_fb", positive=True)
    lumi_fb = finite_nonnegative(lumi_fb, "lumi_fb", positive=True)
    denom = sigma_fb * lumi_fb
    finite_nonnegative(denom, "sigma*lumi", positive=True)
    has_val = hasattr(obj, "val")
    has_bins = hasattr(obj, "bins")
    mode = sr_reader
    if mode == "auto":
        mode = "counter" if has_val else ("cutflow" if has_bins else None)
    if mode == "counter":
        if not has_val:
            return None, None
        norm = finite_nonnegative(obj.val(), "SR yield")  # signal events at lumi
        return (norm / denom if denom else None), norm
    if mode == "cutflow":
        if not has_bins:
            return None, None
        vals = [finite_nonnegative(b.val(), "cutflow bin") for b in obj.bins()]
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

    try:
        for name in ("sigma_pb", "lumi_fb", "driving_tol", "contributing_tol", "mu95_bound", "interp_max_span"):
            finite_nonnegative(getattr(args, name), name, positive=True)
        for name in ("m_parent", "m_lsp"):
            finite_nonnegative(getattr(args, name), name)
    except ValueError as exc:
        ap.error(str(exc))
    srs = [sr.strip() for sr in args.srs.split(",") if sr.strip()]
    if not srs or len(srs) != len(set(srs)):
        ap.error("--srs must contain distinct nonempty signal regions")

    import yoda
    sig = yoda.read(args.signal)
    sigma_fb = args.sigma_pb * 1000.0
    override = {s.strip() for s in args.driving_sr_override.split(",") if s.strip()}

    # SR roles from the exclusion: driving = best-expected SR + any within 1.5x its expected µ
    per_sr, best_sr = {}, None
    if args.exclusion:
        if not os.path.isfile(args.exclusion):
            ap.error(f"exclusion file does not exist: {args.exclusion}")
        ex = json.load(open(args.exclusion), object_pairs_hook=unique_json_object)
        per_sr = ex.get("per_sr", {}); best_sr = ex.get("best_sr")
        if not isinstance(per_sr, dict) or not isinstance(best_sr, str) or best_sr not in per_sr:
            ap.error("exclusion must name a best_sr present in its per_sr records")
        for sr, record in per_sr.items():
            if not isinstance(record, dict):
                ap.error(f"invalid per_sr record in exclusion: {sr}")
            if "exp_median" in record:
                finite_nonnegative(record["exp_median"], f"{sr}.exp_median", positive=True)
        if "exp_median" not in per_sr[best_sr]:
            ap.error("best_sr has no median expected limit")
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
        return "unresolved"  # SR names and residual direction cannot identify a physical cause.

    rows = []
    for sr in srs:
        o = sig.get(f"/{args.routine}/{sr}")
        mine, norm = read_sr_axe(o, args.sr_reader, sigma_fb, args.lumi_fb)       # A×ε, signal events at lumi
        pub, node = published_axe(args.tables_dir, sr, args.grid, args.m_parent, args.m_lsp,
                                  interp_max_span=args.interp_max_span)
        ratio = comparison_ratio(mine, pub)
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
                           "note": "diagnostic hypothesis only; physical cause requires independent evidence"}
        rows.append(dict(sr=sr, mine=mine, pub=pub, ratio=ratio, role=role, tol=tol, ok=ok,
                         signal=norm, mu95_impact=mu95_impact, node=node, attribution=attribution,
                         inverse_signal_limit_shift=inverse_signal_shift(ratio)))

    driving = [r for r in rows if r["role"] == "driving"]
    # Every driving comparison remains in the certification denominator. The best
    # expected SR can set a counting limit but is not the worst acceptance residual.
    best_resid = max((r["mu95_impact"] for r in driving if r["mu95_impact"] is not None), default=None)
    driving_ok = all(r["ok"] for r in driving) if driving else None
    driving_nearest = any(r["node"].startswith("NEAREST") for r in driving)
    worst_driving = best_resid
    if not driving or not driving_ok or best_resid is None or driving_nearest:
        verdict = "FAIL"
    elif best_resid <= args.mu95_bound:
        verdict = "PASS"
    elif best_resid <= 1.5 * args.mu95_bound:
        verdict = "WARN"   # the limit-setting SR is within 1.5× the bound; residuals bounded + attributed
    else:
        verdict = "FAIL"   # the best SR is off enough that µ₉₅ (and maybe the verdict) is unreliable
    worst_s = "-" if worst_driving is None else f"{worst_driving*100:.0f}%"
    fail_reason = None
    if not driving:
        fail_reason = "no driving SR identified; no acceptance certification is possible"
    elif any(r["ratio"] is None for r in driving):
        fail_reason = "driving SR comparison missing or published reference is zero; comparison unusable"
    elif driving_nearest:
        fail_reason = "driving SR uses a different published mass point (NEAREST); diagnostic residual only"
    elif verdict == "FAIL":
        fail_reason = "driving acceptance residual exceeds the stated tolerance or residual bound"

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
              f"±{args.driving_tol*100:.0f}%; worst driving acceptance residual = {worst_s} "
              f"(bound {args.mu95_bound*100:.0f}%). This checks point-estimate selection agreement at "
              "the stated normalization; it does not certify detector response or statistical coverage. "
              "MC and published uncertainties are not propagated. The legacy µ95-impact field is an "
              "acceptance-residual proxy, not an inferred uncertainty on a limit."]
    if fail_reason:
        lines += ["", f"FAIL CAUSE: {fail_reason}."]
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    open(args.out, "w").write("\n".join(lines) + "\n")
    json.dump({"routine": args.routine, "label": args.label, "verdict": verdict, **comparison_metadata(rows),
               "driving_tol": args.driving_tol, "mu95_bound": args.mu95_bound,
               "worst_driving_mu95_impact": worst_driving,
               "fail_reason": fail_reason, "driving_reference_unmatched": driving_nearest,
               "acceptance_denominator": "counter: supplied sigma*lumi; cutflow: first bin, which must represent "
                                         "the uncut generated sample (not independently verified)",
               "rows": [{k: r[k] for k in ("sr", "role", "mine", "pub", "node", "ratio", "ok", "mu95_impact", "attribution", "inverse_signal_limit_shift")}
                        for r in rows]},
              open(args.out.replace(".md", ".json"), "w"), indent=2, allow_nan=False)
    print(f"{verdict}: driving={'ok' if driving_ok else 'OFF'} worst-residual={worst_s} "
          f"({len(attribs)} attributed) -> {args.out}")
    for r in rows:
        node_flag = "" if (r['node'] or "").startswith("grid node") else f"  [{r['node']}]"
        print(f"  {r['sr']:5s} {r['role']:12s} ratio={'-' if r['ratio'] is None else round(r['ratio'],2)} "
              f"{'OK' if r['ok'] else 'x'}{node_flag}")


if __name__ == "__main__":
    main()
