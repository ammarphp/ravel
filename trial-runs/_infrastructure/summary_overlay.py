#!/usr/bin/env python
"""summary_overlay -- render the SUMMARY-PLOT track's overlay from a basis manifest (CR-023).

The renderer half of `workflow/checklists/summary-plot.md`: consumes ONLY the run's
`inputs/basis_manifest.json` (the gate artifact — nothing renders unmapped) and draws every
resolved curve on the ONE declared target basis, with COVERAGE GAPS drawn first-class (shaded +
annotated, never silently absent). House style + the CR-016 lint gate.

Manifest additions consumed here (beyond the checklist's schema): each curve carries
  "resolved": {"mass_gev": [...], "obs": [...], "exp": [...] (optional), "style": {...}}
and the manifest may carry "coverage_gaps": [{"lo_gev": .., "hi_gev": .., "note": ".."}] and
"window_gev": [lo, hi] (the ask's mass window; curves are drawn where they have points).

Two more curve fields, added for the summary_audit.py gate (rules R-SA5/R-SA6) and HONORED here
so a run that passes the gate is rendered the way the gate certified it:
  "draw": "primary" (default; solid, full-weight, cycled house color -- a co-equal curve) |
          "crosscheck" (drawn faint dashed grey -- present for comparison, not co-equal; the
          disposition a superseded candidate's curve must carry) | "none" (not drawn at all).
  "provenance": "digitized" -- appends "(digitized)" to the curve's legend label so a
          hand-digitized curve is never visually indistinguishable from a HEPData-machine one.

Usage: summary_overlay.py --manifest <rundir>/inputs/basis_manifest.json --out stem
       [--logy] [--no-lint] [--experiment ATLAS]
"""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--logy", action="store_true", default=True)
    ap.add_argument("--experiment", default="ATLAS")
    ap.add_argument("--com", type=float, default=13)
    ap.add_argument("--no-lint", action="store_true")
    args = ap.parse_args()

    man = json.load(open(args.manifest))
    tgt = man["target_basis"]
    curves = [c for c in man["curves"]
              if c.get("resolved") and c.get("draw", "primary") != "none"]
    dropped = [c for c in man["curves"]
               if not c.get("resolved") or c.get("draw", "primary") == "none"]
    if not curves:
        sys.exit("summary_overlay: no resolved curves in the manifest — the basis gate did its "
                 "job; resolve transformations first (checklists/summary-plot.md §3)")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import mplhep_style as house
    hep = house.apply_style(args.experiment)
    fig, ax = plt.subplots(figsize=(9, 6.5))

    colors = list(house.OKABE_ITO.values())
    color_i = 0
    for c in curves:
        r = c["resolved"]
        m = np.asarray(r["mass_gev"], float)
        draw = c.get("draw", "primary")
        prov_suffix = " (digitized)" if c.get("provenance") == "digitized" else ""
        if draw == "crosscheck":
            # faint dashed grey -- present for comparison, never co-equal with a primary curve
            col, alpha = "0.55", 0.75
            obs_ls, exp_ls, lw_obs, lw_exp = "--", ":", 1.4, 1.1
        else:
            col, alpha = colors[color_i % len(colors)], 1.0
            obs_ls, exp_ls, lw_obs, lw_exp = "-", "--", 2.2, 1.6
            color_i += 1
        if r.get("obs"):
            obs = np.asarray([v if v is not None else np.nan for v in r["obs"]], float)
            ax.plot(m, obs, obs_ls, color=col, lw=lw_obs, alpha=alpha,
                    label=f"{c['source']}{prov_suffix} obs. ({c.get('lumi_fb', '?')} fb$^{{-1}}$)")
        if r.get("exp"):
            exp = np.asarray([v if v is not None else np.nan for v in r["exp"]], float)
            ax.plot(m, exp, exp_ls, color=col, lw=lw_exp, alpha=alpha,
                    label=f"{c['source']}{prov_suffix} exp.")
        if r.get("theory"):
            th = np.asarray([v if v is not None else np.nan for v in r["theory"]], float)
            ax.plot(m, th, ":", color="0.25", lw=2.0, label=r.get("theory_label", "theory"))

    win = man.get("window_gev")
    if win:
        ax.set_xlim(win)
    for g in man.get("coverage_gaps", []):
        lo = g.get("lo_gev", ax.get_xlim()[0])
        hi = g.get("hi_gev", ax.get_xlim()[1])
        ax.axvspan(lo, hi, color="0.85", alpha=0.6, zorder=0)
        ax.text(0.5 * (lo + hi), 0.965, g.get("note", "no published limit"),
                transform=ax.get_xaxis_transform(), ha="center", va="top", fontsize=9.5,
                color="0.25", rotation=90 if (hi - lo) < 0.12 * (ax.get_xlim()[1] -
                                                                 ax.get_xlim()[0]) else 0)
    if args.logy:
        ax.set_yscale("log")
    ax.set_xlabel(tgt.get("x_label", r"$m$ [GeV]"))
    ax.set_ylabel(tgt.get("quantity", "95% CL UL"))
    try:
        explabel = getattr(hep, args.experiment.lower()).label
        explabel(ax=ax, data=True, text="", com=args.com, loc=0)
    except Exception:
        pass
    house.smart_legend(ax, fontsize=10.5,
                       candidates={"upper right": (0.58, 1.00, 0.55, 1.00),
                                   "upper left": (0.00, 0.42, 0.55, 1.00),
                                   "lower left": (0.00, 0.42, 0.00, 0.45),
                                   "lower right": (0.58, 1.00, 0.00, 0.45)})
    lines = [f"target basis: {tgt.get('quantity', '?')}",
             f"{tgt.get('model', '')}",
             f"{len(curves)} published limit set(s), re-expressed on one basis",
             "published limits only — no new limit derived here"]
    if dropped:
        lines.append(f"{len(dropped)} candidate(s) dropped: see manifest reasons")
    house.smart_annotate(ax, [l for l in lines if l], fontsize=9.5)
    house.tick_hygiene(ax, axr=None, logy=args.logy, logx=False)
    house.enforce_lint(fig, where=os.path.basename(args.out), allow=args.no_lint)
    for ext in (".png", ".pdf"):
        fig.savefig(args.out + ext, dpi=200, bbox_inches="tight")
        print(f"wrote {args.out}{ext}")
    print(f"summary overlay: {len(curves)} curves on '{tgt.get('quantity')}'; "
          f"{len(man.get('coverage_gaps', []))} coverage gap(s) drawn first-class; "
          f"labels: none-survey, published-limits-only")


if __name__ == "__main__":
    main()
