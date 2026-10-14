#!/usr/bin/env python3
"""Plot the results of a SimpleAnalysis + pyhf run (mplhep ATLAS house style via mplhep_style.py).
Usage: plot_simpleanalysis.py <run_output_dir> <analysis_name> <sigma_pb> <kfactor> <lumi_pb-1> <out_dir>
Produces: kinematics.png (signal distributions), sr_yields.png (expected events per SR),
exclusion.png (CLs vs mu). Reads <analysis>.root (event ntuple), <analysis>.txt (SR acceptances),
muscan_results.json (the limit scan)."""

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.plotting"

import json
import os
import sys


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output_root")
    p.add_argument("analysis")
    p.add_argument("sigma_pb", type=float)
    p.add_argument("kfactor", type=float)
    p.add_argument("lumi_pb", type=float)
    p.add_argument("out")
    args = p.parse_args(argv)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import uproot

    from . import mplhep_style as house

    out_root, analysis, sigma_pb, kfac, lumi, outdir = args.output_root, args.analysis, args.sigma_pb, args.kfactor, args.lumi_pb, args.out
    norm = sigma_pb * kfac * lumi                       # total expected events before selection
    lumi_fb = lumi / 1000.0                             # argv is pb^-1; labels quote fb^-1
    os.makedirs(outdir, exist_ok=True)
    house.apply_style("ATLAS")

    # ---- 1. signal kinematic distributions (events passing the baseline selection) ----
    t = uproot.open(f"{out_root}/{analysis}.root")["ntuple"]
    arr = t.arrays(["met_Et", "mll", "lep1Pt", "lep2Pt", "pass_common_cuts", "eventWeight"], library="np")
    sel = arr["pass_common_cuts"].astype(bool)
    w = arr["eventWeight"][sel]
    fig, ax = plt.subplots(2, 2, figsize=(11, 8))
    panels = [("met_Et", "missing $E_T$ [GeV]", (0, 400)),
              ("mll", "$m_{\\ell\\ell}$ [GeV]", (0, 80)),
              ("lep1Pt", "leading lepton $p_T$ [GeV]", (0, 60)),
              ("lep2Pt", "sub-leading lepton $p_T$ [GeV]", (0, 40))]
    for a, (br, xl, rng) in zip(ax.flat, panels):
        a.hist(arr[br][sel], bins=30, range=rng, weights=w, histtype="step",
               color=house.OKABE_ITO["blue"], lw=1.8)
        a.set_xlabel(xl, fontsize=11); a.set_ylabel("Events / bin", fontsize=11)
        a.tick_params(labelsize=10)
        house.tick_hygiene(a, x_nbins=5)
    fig.suptitle(f"Signal kinematics after baseline selection — {analysis}", fontsize=13)
    fig.tight_layout(); fig.savefig(f"{outdir}/kinematics.png", dpi=200); plt.close(fig)

    # ---- 2. expected signal yield per signal region (top regions) ----
    rows = []
    with open(f"{out_root}/{analysis}.txt") as f:
        next(f)
        for line in f:
            p = line.strip().split(",")
            if len(p) >= 3 and p[0] != "All":
                rows.append((p[0], float(p[2]) * norm))   # acceptance * normalization = expected events
    rows.sort(key=lambda r: r[1], reverse=True)
    top = rows[:15][::-1]                                 # horizontal bars: best SR at the top
    fig, a = plt.subplots(figsize=(9, 7))
    a.barh(range(len(top)), [r[1] for r in top], color=house.OKABE_ITO["orange"])
    a.set_yticks(range(len(top)))
    a.set_yticklabels([r[0] for r in top], fontsize=11)   # horizontal labels: readable, no rotation
    a.set_xlabel(f"Expected signal events ({lumi_fb:g} fb$^{{-1}}$)")
    a.set_title(f"Signal yield per signal region (top {len(top)}) — {analysis}", fontsize=12)
    from matplotlib.ticker import MaxNLocator
    a.xaxis.set_major_locator(MaxNLocator(nbins=6))
    fig.tight_layout(); fig.savefig(f"{outdir}/sr_yields.png", dpi=200); plt.close(fig)
    top = top[::-1]                                       # restore best-first order for the report line

    # ---- 3. exclusion: CLs vs mu ----
    d = json.load(open(f"{out_root}/muscan_results.json"))
    mu = d["scan"]; res = d["results"]
    cls_obs = [r[0] for r in res]; cls_exp = [r[1][2] for r in res]
    band_lo = [r[1][1] for r in res]; band_hi = [r[1][3] for r in res]
    fig, a = plt.subplots(figsize=(8, 6))
    a.fill_between(mu, band_lo, band_hi, color=house.OKABE_ITO["yellow"], alpha=0.7,
                   label="expected $\\pm1\\sigma$")
    a.plot(mu, cls_exp, "k--", lw=1.6, label="expected CLs")
    a.plot(mu, cls_obs, "o-", color=house.OKABE_ITO["blue"], ms=5, label="observed CLs")
    a.axhline(0.05, color=house.OKABE_ITO["vermillion"], ls=":", lw=1.6, label="95% CL (CLs = 0.05)")
    a.set_xlabel("signal strength $\\mu$"); a.set_ylabel("CLs"); a.set_ylim(0, 1.05)
    house.tick_hygiene(a, x_nbins=7)
    a.legend(fontsize=11, framealpha=0.85, edgecolor="none")
    a.set_title(f"Exclusion scan — {analysis}", fontsize=12)
    fig.tight_layout(); fig.savefig(f"{outdir}/exclusion.png", dpi=200); plt.close(fig)

    print(f"wrote 3 plots to {outdir}; total expected events (pre-sel) = {norm:.1f}; "
          f"max SR yield = {top[0][1]:.2f} ({top[0][0]})")


if __name__ == "__main__":
    main()
