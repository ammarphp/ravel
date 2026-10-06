#!/usr/bin/env python
"""Publication-grade overlay of a model's signal on the experiment's published distribution.

The test a scientist reads a hypothesis off: the experiment's data + SM background, with the new
model's signal+background drawn on top — if it rises above the data in a region, the model would have
shown up there. Built to the ATLAS/CMS plot style (via mplhep, through the shared mplhep_style.py
house module): Helvetica (TeX Gyre Heros), inward ticks on all four sides, the bold-italic experiment
label + "√s, L" sub-label, a total-uncertainty band on the background, a ratio panel, log-y,
TrueType-embedded PDF fonts, tick-density control, deterministic collision-aware legend.
See `docs/workflow/checklists/plot-criteria.md`.

Reads the routine's bundled REF (y01 = observed data, y02 = SM background) + the signal YODA. An
optional per-process stack JSON ({label: [bin values], ...}) draws the stacked background breakdown
(Okabe-Ito colourblind-safe palette, consistent process->colour map); the stacked sum is validated
against the published total background (stderr warning if any bin deviates >2%).

The signal YODA is normally LO-normalized (MadGraph σ_LO × lumi). If the legend label claims a
higher-order normalization (e.g. "NLO+NNLL"), pass the verified k-factor via --sig-scale so the
drawn curve matches the claim.

Usage:
  overlay_on_data.py --signal SIG.yoda --ref REF.yoda.gz --routine NAME --table dNN-x01 \
      --label "model" --experiment ATLAS --lumi 3.2 --com 13 --xlabel "m_eff [GeV]" \
      [--sig-scale K] [--stack bkg_components.json] --out OUT.png
"""

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.plotting"

import argparse, json, os, sys
import numpy as np

from . import mplhep_style as house


def series(obj):
    los, his, vals, errs = [], [], [], []
    for b in obj.bins():
        los.append(b.xMin()); his.append(b.xMax()); vals.append(b.val())
        try:
            errs.append(b.errAvg())
        except Exception:
            errs.append(0.0)
    return np.array(los + [his[-1]]), np.array(vals), np.array(errs)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--signal", required=True); ap.add_argument("--ref", required=True)
    ap.add_argument("--routine", required=True); ap.add_argument("--table", required=True)
    ap.add_argument("--label", default="signal"); ap.add_argument("--out", required=True)
    ap.add_argument("--experiment", default="ATLAS", choices=["ATLAS", "CMS"])
    ap.add_argument("--lumi", type=float, default=None); ap.add_argument("--com", type=float, default=13)
    ap.add_argument("--data-y", default="y01"); ap.add_argument("--bkg-y", default="y02")
    ap.add_argument("--xlabel", default="observable"); ap.add_argument("--stack", help="per-process JSON")
    ap.add_argument("--sig-scale", type=float, default=1.0,
                    help="multiply the signal histogram (e.g. the NLO k-factor when the YODA is "
                         "LO-normalized and the label claims NLO)")
    ap.add_argument("--no-lint", action="store_true",
                    help="downgrade the CR-016 plot-lint gate to WARN")
    args = ap.parse_args()

    import yoda
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    hep = house.apply_style(args.experiment)

    sig = yoda.read(args.signal); ref = yoda.read(args.ref)
    skey = f"/{args.routine}/{args.table}-{args.data_y}"
    dkey = f"/REF/{args.routine}/{args.table}-{args.data_y}"
    bkey = f"/REF/{args.routine}/{args.table}-{args.bkg_y}"
    for k, src in ((skey, sig), (dkey, ref), (bkey, ref)):
        if k not in src:
            sys.exit(f"missing object {k}")
    edges, s, _ = series(sig[skey]); _, d, _ = series(ref[dkey]); _, b, db = series(ref[bkey])
    s = s * args.sig_scale
    mids = 0.5 * (edges[:-1] + edges[1:]); widths = np.diff(edges); sb = s + b

    fig, (ax, axr) = plt.subplots(2, 1, figsize=(8, 7), sharex=True,
                                  gridspec_kw={"height_ratios": [3, 1], "hspace": 0.07})
    # background: per-process stack if provided, else the published total
    if args.stack:
        st = json.load(open(args.stack)); bottom = np.zeros_like(b)
        for i, (lab, vals) in enumerate(st.items()):
            v = np.array(vals[: len(b)], float)
            ax.bar(mids, v, width=widths, bottom=bottom, label=lab,
                   color=house.process_color(lab, i), lw=0)
            bottom = bottom + v
        # stack fidelity: the per-process sum must reproduce the published total background
        with np.errstate(divide="ignore", invalid="ignore"):
            rel = np.abs(bottom - b) / np.where(b > 0, b, np.nan)
        bad = np.where(np.nan_to_num(rel) > 0.02)[0]
        if len(bad):
            print(f"WARNING: stacked background deviates >2% from the published total in "
                  f"{len(bad)} bin(s): "
                  + ", ".join(f"[{edges[i]:g},{edges[i+1]:g}] {rel[i]*100:.1f}%" for i in bad),
                  file=sys.stderr)
    else:
        ax.stairs(b, edges, fill=True, color="0.85", label="SM background (published)")
    ax.bar(mids, 2 * db, width=widths, bottom=b - db, color="none", hatch="////",
           edgecolor="0.4", lw=0, label="SM total uncertainty")
    # wrap a long model label onto its own legend line: the legend must stay narrow enough to
    # sit top-right without reaching the experiment/lumi header (mplhep legends are frameless)
    siglab = f"signal+bkg ({args.label})"
    if len(siglab) > 34:
        siglab = f"signal+bkg\n({args.label})"
    ax.stairs(sb, edges, color=house.SIGNAL_COLOR, lw=2.0, label=siglab)
    ax.errorbar(mids, d, yerr=np.sqrt(np.maximum(d, 0)), fmt="ko", ms=4, label="Data", zorder=5)
    ax.set_yscale("log")
    lo = b[b > 0].min() if (b > 0).any() else 1e-2
    ax.set_ylim(max(1e-2, 0.3 * lo), 8 * max(sb.max(), d.max()))
    ax.set_ylabel("Events / bin")
    if hep is not None:
        explabel = getattr(hep, args.experiment.lower()).label
        try:
            explabel(ax=ax, data=True, text="", lumi=args.lumi, com=args.com)
        except TypeError:                      # older mplhep: kwarg was `label`
            explabel(ax=ax, data=True, label="", lumi=args.lumi, com=args.com)

    safe = np.where(b > 0, b, np.nan)
    axr.axhline(1.0, color="0.5", lw=1)
    axr.bar(mids, 2 * db / safe, width=widths, bottom=1 - db / safe, color="none", hatch="////",
            edgecolor="0.4", lw=0)
    axr.errorbar(mids, d / safe, yerr=np.sqrt(np.maximum(d, 0)) / safe, fmt="ko", ms=4)
    axr.stairs(sb / safe, edges, color=house.SIGNAL_COLOR, lw=1.8)
    axr.set_ylabel("Ratio to bkg", fontsize=13)
    axr.set_xlabel(args.xlabel)
    axr.set_ylim(0, min(np.nanmax(sb / safe) * 1.15, 12) if (b > 0).any() else 2)

    house.tick_hygiene(ax, axr=axr, logy=True)
    house.smart_legend(ax, fontsize=12)

    house.enforce_lint(fig, where=os.path.basename(args.out), allow=args.no_lint)   # CR-016 gate
    fig.savefig(args.out, dpi=200, bbox_inches="tight")
    if not args.out.endswith(".pdf"):
        fig.savefig(args.out.rsplit(".", 1)[0] + ".pdf", bbox_inches="tight")
    print(f"wrote {args.out} (mplhep {args.experiment} house style; sig-scale {args.sig_scale:g})")


if __name__ == "__main__":
    main()
