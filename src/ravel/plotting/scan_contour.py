#!/usr/bin/env python
"""Render a grid SCAN (scan.json) into the RRR exclusion CONTOUR -- the paper's actual deliverable.

This is the renderer the corrected mental model points at (docs/workflow/steps/08-scan.md). It does NOT plot
a single tested point on someone else's published contour (that is mass_plane_overlay.py's unit-level
quick-look). It plots the contour the SCAN itself produced -- the mu95_obs = 1 crossing interpolated
across the grid of model points assembled by scan_orchestrator.py -- which is what RRR Fig 3/6/8/10 are.

Layouts, auto-selected by the scan's shape and the references supplied:
  * LINE scan  (one m_parent, several Delta m): mu95_obs vs Delta m, with the +/-1sigma expected band if
    present, the mu95 = 1 exclusion line, and the interpolated excluded-Delta m interval shaded. This is
    the honest, compute-affordable PoC: a 1-D slice through the contour. If an ATLAS reference contour
    is supplied (--atlas-contour), its Delta m reach AT THIS m_parent is drawn as a vertical reference
    and the relative difference of the reach (mapyde-ATLAS)/ATLAS is annotated -- the 1-D analogue of
    the paper's color map.
  * GRID scan (>=2 m_parent AND >=2 Delta m): the mapyde mu95_obs = 1 exclusion CONTOUR (tricontour) in
    the (m_parent, Delta m) plane, scanned points scattered + colored by mu95_obs, and -- when an ATLAS
    HEPData contour is supplied -- the ATLAS contour overlaid so "the mapyde exclusion contour follows
    the corresponding ATLAS contour" (Sec 3.3) can be read directly.
  * FIG-3 single panel (the HEADLINE artifact, written to <out>__fig3.{png,pdf} whenever BOTH
    --atlas-contour AND --atlas-limit are supplied with a 2-D grid): RRR Fig 3's actual FORM -- ONE
    panel with the (mapyde-ATLAS)/ATLAS relative-difference color map as the FILL, the ATLAS observed
    contour (black solid; expected dashed if given), and the mapyde mu95=1 contour overlaid, on the
    ATLAS compressed-plane convention (LOG Delta m axis -- docs/workflow/checklists/plot-guidelines.md).
    Both fields are smoothly interpolated (matplotlib.tri cubic, linear fallback) from the scattered
    scan points onto a fine regular grid in (m, log10 Delta m) space, masked outside the convex hull
    of the scanned points, so the contour is a smooth curve, not lattice-jagged. The two-panel outputs
    above are still written as diagnostics. --limit-kind observed|expected|both picks which limit
    column BOTH sides use (like-columns rule; expected -> <out>__fig3_expected, RRR's own convention);
    the fill colors ONLY exact (tolerance-snapped) matches to the published grid -- the reference is
    never interpolated; scanned cells without a published point are white + gray circle (stated on
    the figure), unscanned cells are holes.

AXIS SCALES (docs/workflow/checklists/plot-guidelines.md -- the published figure's scales are FACTS,
not defaults): when a figure contract exists, pass --figure-target <rundir-or-figure_target.json>
and the grid/fig3 layouts CONSUME the axes recorded there at declaration ({"x","y"} in
linear|log); explicit --logx/--linx/--logy/--liny always win over the contract. With neither, the
current defaults hold: grid = linear/linear, fig3 = linear m + LOG Delta m (the ATLAS
compressed-plane convention), line = mu95 log-y only when it spans >~1.5 decades. The line layout
draws (Delta m, mu95) -- not the published plane -- so it honors only the explicit flags.

It sets a 95% CL EXCLUSION, never a discovery. Reuses read_contour() + the house style from the
sibling modules so the figure is in the experiment's published style.

Usage:
  scan_contour.py --scan <scandir>/scan.json \
    --experiment ATLAS --com 13 --lumi 139 \
    --atlas-contour observed=outputs/hepdata/.../exclusion_obs.yaml \
    [--figure-target <rundir>] [--logx|--linx] [--logy|--liny] \
    --out <scandir>/plots/sleptonscan__contour

See docs/workflow/steps/08-scan.md and docs/workflow/checklists/scan-and-contour.md.
"""

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.plotting"

import argparse
import json
import os
import sys

import numpy as np

from . import mplhep_style as house
from .mass_plane_overlay import read_contour, parse_contour_args, texify


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
        for k in ("m_parent", "m_lsp", "dm", "mu95_obs"):
            if p.get(k) is None:
                die(f"scan point {p.get('tag')} missing '{k}'")
    flagged = [p.get("tag") for p in pts if p.get("quality")]
    if flagged:
        print(f"  note: {len(flagged)} scan point(s) carry a limit-quality flag (floored/capped: "
              f"CR-001 bounds, not limits): {flagged}", file=sys.stderr)
    return scan


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


def excluded_interval(dms, mu, level=1.0):
    """For a 1-D Delta m slice, the contiguous excluded (mu<level) Delta m span as (lo, hi) or None."""
    dms = np.asarray(dms, float); mu = np.asarray(mu, float)
    order = np.argsort(dms); dms, mu = dms[order], mu[order]
    below = dms[mu < level]
    if below.size == 0:
        return None
    cr = interp_crossing(dms, mu, level)
    lo = min(below.min(), min(cr) if cr else below.min())
    hi = max(below.max(), max(cr) if cr else below.max())
    return float(lo), float(hi)


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
    if hep is not None:
        explabel = getattr(hep, args.experiment.lower()).label
        try:
            explabel(ax=ax, data=True, text="", lumi=args.lumi, com=args.com)
        except TypeError:
            explabel(ax=ax, data=True, label="", lumi=args.lumi, com=args.com)


LINT_ALLOW = False       # set by --no-lint; save() gates every figure through the house lint


def save(fig, stem):
    house.enforce_lint(fig, where=os.path.basename(stem), allow=LINT_ALLOW)   # CR-016 gate
    for ext in (".pdf", ".png"):
        p = stem if stem.endswith(ext) else (
            stem.rsplit(".", 1)[0] if "." in os.path.basename(stem) else stem) + ext
        os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
        fig.savefig(p, dpi=200, bbox_inches="tight")
        print(f"wrote {p}")


def atlas_dm_reach(atlas_contours, m_parent):
    """For a line scan, the ATLAS contour's Delta m reach at this m_parent (max Delta m on the boundary
    near m_parent). Returns the reach in GeV or None. The contour is a polyline in (m, Delta m) or
    (m, m_lsp); we orient to (m, Delta m) and take the boundary Delta m at the nearest m column."""
    best = None
    for role, path, x, y, xn, yn in atlas_contours:
        # orient so y = Delta m
        def is_dm(nm):
            return bool(nm) and ("delta" in nm.lower() or "\\Delta" in nm or "Δ" in nm)
        xx, yy = np.asarray(x, float), np.asarray(y, float)
        if is_dm(xn) and not is_dm(yn):
            xx, yy = yy, xx
        elif not is_dm(xn) and not is_dm(yn):
            # mass-mass contour: Delta m = m_parent - m_lsp (y is m_lsp)
            yy = xx - yy
        # nearest boundary vertices in m, take the max Delta m there
        if xx.size == 0:
            continue
        win = np.abs(xx - m_parent) <= max(5.0, 0.05 * m_parent)
        cand = yy[win] if win.any() else yy[np.argsort(np.abs(xx - m_parent))[:3]]
        if cand.size:
            r = float(np.nanmax(cand))
            best = r if best is None else max(best, r)
    return best


# ----------------------------------------------------------------- LINE layout (1-D Delta m slice)
def render_line(scan, atlas_contours, args):
    plt, hep = setup(args)
    pts = sorted(scan["points"], key=lambda r: r["dm"])
    m_parent = pts[0]["m_parent"]
    dms = [p["dm"] for p in pts]
    mu_obs = [p["mu95_obs"] for p in pts]
    mu_exp = [p.get("mu95_exp") for p in pts]
    band = [p.get("mu95_exp_band") for p in pts]

    fig, ax = plt.subplots(figsize=(8, 6))
    # +/-1,2 sigma expected band, if every point shipped a 5-entry band [-2,-1,med,+1,+2]
    if all(isinstance(b, (list, tuple)) and len(b) == 5 for b in band):
        b = np.array(band, float)
        ax.fill_between(dms, b[:, 0], b[:, 4], color=house.OKABE_ITO["yellow"], alpha=0.5,
                        lw=0, label=r"expected $\pm2\sigma$")
        ax.fill_between(dms, b[:, 1], b[:, 3], color=house.OKABE_ITO["bluishgreen"], alpha=0.5,
                        lw=0, label=r"expected $\pm1\sigma$")
    if all(m is not None for m in mu_exp):
        ax.plot(dms, mu_exp, color=house.OKABE_ITO["blue"], ls="--", lw=1.8,
                label=r"expected median $\mu_{95}$")
    ax.plot(dms, mu_obs, color="black", marker="o", ms=6, lw=2.0, label=r"observed $\mu_{95}$ (mapyde)")
    ax.axhline(1.0, color=house.OKABE_ITO["vermillion"], ls=":", lw=1.5)
    ax.text(dms[0], 1.0, r" $\mu_{95}=1$ (exclusion)", color=house.OKABE_ITO["vermillion"],
            va="bottom", ha="left", fontsize=10)

    interval = excluded_interval(dms, mu_obs)
    if interval:
        lo, hi = interval
        ax.axvspan(lo, hi, color=house.OKABE_ITO["bluishgreen"], alpha=0.12, lw=0)
        # place the label in the empty mid-height of the shaded band (the ATLAS label owns the top)
        ax.text(0.5 * (lo + hi), ax.get_ylim()[1] * 0.55,
                rf"excluded$\ \Delta m\in[{lo:.1f},{hi:.1f}]$ GeV", ha="center", va="center",
                rotation=90, fontsize=9.5, color=house.OKABE_ITO["bluishgreen"])

    # ATLAS reference reach at this m_parent (the 1-D analogue of the color map)
    note = None
    if atlas_contours:
        reach = atlas_dm_reach(atlas_contours, m_parent)
        if reach is not None:
            ax.axvline(reach, color="0.4", ls="-.", lw=1.4)
            ax.text(reach, ax.get_ylim()[1] * 0.80, " ATLAS reach", rotation=90, va="top",
                    ha="right", color="0.4", fontsize=9)
            if interval:
                rel = (interval[1] - reach) / reach
                # keep the percent OUT of mathtext ($...$): matplotlib mathtext chokes on a bare '%'
                note = (rf"reach $\Delta m$: mapyde {interval[1]:.1f} vs ATLAS {reach:.1f} GeV "
                        rf"($\Rightarrow$ {rel*100:+.0f} percent)")

    ax.set_xlabel(r"$\Delta m(\tilde{\ell},\tilde{\chi}^0_1)$ [GeV]")
    ax.set_ylabel(r"95% CL upper limit on $\mu_{95}$")
    # axis scales: this layout's axes are (Delta m, mu95) -- NOT the published plane -- so the
    # figure-contract axes do not apply here; explicit --logx/--logy/--linx/--liny still win over
    # the span heuristic (log-y only when mu95 spans >~1.5 decades, plot-guidelines.md).
    log_x = resolve_axis(args.logx, None, False)
    log_y = resolve_axis(args.logy, None,
                         (max(mu_obs) / max(min(mu_obs), 1e-3)) >= 30)
    if log_x:
        ax.set_xscale("log")
    ax.set_yscale("log" if log_y else "linear")
    header(ax, hep, args)
    lines = [rf"$\mathbf{{{(scan.get('analysis_id') or '').replace('_', chr(92)+'_')}}}$",
             rf"slepton-bino line  $m_{{\tilde\ell}}={m_parent:g}$ GeV",
             f"{scan['n_done']}/{scan['n_planned']} grid points",
             "95% CL exclusion (CLs), not a discovery"]
    if note:
        lines.insert(3, note)
    # legend FIRST (scored over every corner), then the annotation box scores the remainder --
    # both are occupancy-aware, so neither sits on the curves/band (plot-criteria, CR-016)
    house.smart_legend(ax, fontsize=10, reserved_corners=(),
                       candidates={"upper right": (0.58, 1.00, 0.55, 1.00),
                                   "upper left": (0.00, 0.42, 0.55, 1.00),
                                   "upper center": (0.30, 0.70, 0.55, 1.00),
                                   "lower left": (0.00, 0.42, 0.00, 0.40),
                                   "lower center": (0.30, 0.70, 0.00, 0.40)})
    house.smart_annotate(ax, lines, fontsize=10)
    house.tick_hygiene(ax, axr=None, logy=log_y, logx=log_x)
    save(fig, args.out)
    print(f"line scan: m={m_parent:g}, {len(pts)} points, "
          f"excluded Delta m {interval if interval else 'none'}")


# ----------------------------------------------------------------- GRID layout (2-D contour)
def render_grid(scan, atlas_contours, args):
    plt, hep = setup(args)
    import matplotlib.tri as mtri
    pts = scan["points"]
    mpar = np.array([p["m_parent"] for p in pts], float)
    dm = np.array([p["dm"] for p in pts], float)
    mu = np.array([p["mu95_obs"] for p in pts], float)

    fig, ax = plt.subplots(figsize=(8, 7))
    # scatter colored by mu95_obs (log-normalized; excluded points mu<1 stand out)
    sc = ax.scatter(mpar, dm, c=mu, s=60, cmap="viridis_r",
                    norm=__import__("matplotlib").colors.LogNorm(vmin=max(mu.min(), 1e-2),
                                                                 vmax=mu.max()),
                    edgecolors="black", linewidths=0.5, zorder=4)
    cb = fig.colorbar(sc, ax=ax, pad=0.02)
    cb.set_label(r"observed $\mu_{95}$ (mapyde)")
    # the mapyde exclusion contour: mu95_obs = 1 (needs a triangulable point cloud).
    # NOTE: matplotlib >=3.8 removed ContourSet.collections; check allsegs and add a proxy legend
    # handle (the contour lines are drawn by tricontour regardless of how we label them).
    from matplotlib.lines import Line2D
    drew_contour = False
    if len({(a, b) for a, b in zip(mpar, dm)}) >= 3 and len(np.unique(mpar)) >= 2 \
            and len(np.unique(dm)) >= 2:
        try:
            tri = mtri.Triangulation(mpar, dm)
            cs = ax.tricontour(tri, mu, levels=[1.0], colors=[house.OKABE_ITO["vermillion"]],
                               linewidths=2.4, zorder=6)
            segs = getattr(cs, "allsegs", [[]])
            if segs and segs[0]:  # at least one polyline at the mu=1 level
                ax.add_line(Line2D([], [], color=house.OKABE_ITO["vermillion"], lw=2.4,
                                   label=r"mapyde 95% CL excl. ($\mu_{95}=1$)"))
                drew_contour = True
            else:
                print("  (no mu95=1 crossing within the scanned grid -- contour not drawn)")
        except Exception as e:  # noqa: BLE001 -- degenerate triangulation -> fall back to scatter only
            print(f"  (tricontour skipped: {e})")
    # ATLAS reference contour(s), oriented to (m, Delta m)
    for role, path, x, y, xn, yn in atlas_contours:
        def is_dm(nm):
            return bool(nm) and ("delta" in nm.lower() or "\\Delta" in nm or "Δ" in nm)
        xx, yy = np.asarray(x, float), np.asarray(y, float)
        if is_dm(xn) and not is_dm(yn):
            xx, yy = yy, xx
        elif not is_dm(xn) and not is_dm(yn):
            yy = xx - yy
        ls = "-" if role.startswith("observed") else "--"
        ax.plot(xx, yy, color="black", ls=ls, lw=1.8, zorder=5,
                label=f"ATLAS {role.replace('_', ' ')}")

    ax.set_xlabel(r"$m_{\tilde{\ell}}$ [GeV]")
    ax.set_ylabel(r"$\Delta m(\tilde{\ell},\tilde{\chi}^0_1)$ [GeV]")
    # axis scales: explicit flags > the figure contract's declared published scales
    # (--figure-target) > the linear/linear default this layout has always had.
    log_x = resolve_axis(args.logx, (args.contract_axes or {}).get("x"), False)
    log_y = resolve_axis(args.logy, (args.contract_axes or {}).get("y"), False)
    if log_x:
        ax.set_xscale("log")
    if log_y:
        ax.set_yscale("log")
    # the scatter + contours occupy most of the panel, so the experiment label goes ABOVE the
    # axes (mplhep loc=0) instead of inside top-left, where the 2026-08-28 Tier-B panel found it
    # overdrawn by markers; the legend gets explicit corner candidates (incl. the lower ones)
    # so it never sits on the scatter (same treatment render_fig3 already had).
    if hep is not None:
        explabel = getattr(hep, args.experiment.lower()).label
        try:
            explabel(ax=ax, data=True, text="", lumi=args.lumi, com=args.com, loc=0)
        except TypeError:
            header(ax, hep, args)
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        house.smart_legend(ax, fontsize=10, reserved_corners=(),
                           candidates={"upper right": (0.58, 1.00, 0.55, 1.00),
                                       "upper left": (0.00, 0.42, 0.55, 1.00),
                                       "lower right": (0.58, 1.00, 0.00, 0.45),
                                       "lower left": (0.00, 0.42, 0.00, 0.45)})
    house.smart_annotate(
        ax, [rf"$\mathbf{{{(scan.get('analysis_id') or '').replace('_', chr(92)+'_')}}}$",
             f"{scan['n_done']}/{scan['n_planned']} grid points",
             "95% CL exclusion (CLs), not a discovery"], fontsize=10)
    house.tick_hygiene(ax, axr=None, logy=log_y, logx=log_x)
    save(fig, args.out)
    cstate = "drawn" if drew_contour else "NOT drawn (no mu95=1 crossing or too few points)"
    print(f"grid scan: {len(pts)} points, mapyde contour {cstate}; "
          f"axes x={'log' if log_x else 'linear'} y={'log' if log_y else 'linear'}; "
          f"{len(atlas_contours)} ATLAS contour(s)")


def _basis_guard(scan, what):
    """Warn LOUDLY when a sigma-UL comparison is about to be rendered from a scan whose sigma_ref
    is (probably) still the SAMPLE sigma rather than the published model sigma. A rebased scan
    carries scan['model_basis'] (scan_orchestrator.py rebase). Returns True if rebased."""
    if scan.get("model_basis"):
        return True
    print(f"  WARNING ({what}): scan.json has NO model_basis -- sigma_ref_fb is then typically the "
          f"SAMPLE sigma (e.g. the ISR-tagged subset from logs/madgraph.log), while --atlas-limit "
          f"is the UL on the experiment's INCLUSIVE simplified-model sigma. The rel-diff map would "
          f"compare ULs on DIFFERENT bases (apples-to-oranges, mass-dependent tilt). Run "
          f"`scan_orchestrator.py rebase <scandir> --process <p>` first (comparison-basis rule, "
          f"docs/workflow/checklists/scan-and-contour.md Normalization).")
    return False


# ----------------------------------------------------------------- FIG-3 single panel (headline)
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


def _smooth_field(mpar, dm, z, nx=200, ny=200, logy=True):
    """Interpolate a scattered (m, Delta m) -> z field onto a fine regular grid in the space the
    figure is DRAWN in -- (m, log10 Delta m) when the Delta m axis is log (logy=True, the ATLAS
    compressed-plane default), plain (m, Delta m) when the resolved axis is linear -- so smoothness
    is smoothness ON the figure. matplotlib.tri only (no scipy dependency in the rivet env):
    CubicTriInterpolator (kind='geom'), falling back to LinearTriInterpolator PER CELL where cubic
    is ill-conditioned (masked/non-finite), and wholesale if cubic cannot be built. Points outside
    the convex hull of the scanned lattice stay MASKED (no extrapolation artifacts). Returns
    (M, DM, Z) with Z a masked array on the fine grid."""
    import matplotlib.tri as mtri
    mpar = np.asarray(mpar, float)
    ldm = np.log10(np.asarray(dm, float)) if logy else np.asarray(dm, float)
    z = np.asarray(z, float)
    tri = mtri.Triangulation(mpar, ldm)
    xi = np.linspace(mpar.min(), mpar.max(), nx)
    yi = np.linspace(ldm.min(), ldm.max(), ny)
    Xi, Yi = np.meshgrid(xi, yi)
    lin = mtri.LinearTriInterpolator(tri, z)(Xi, Yi)     # defines the hull mask
    try:
        cub = mtri.CubicTriInterpolator(tri, z, kind="geom")(Xi, Yi)
        bad = np.ma.getmaskarray(cub) | ~np.isfinite(cub.filled(np.nan))
        Zi = np.ma.where(bad, lin, cub)
        Zi.mask = np.ma.getmaskarray(lin)                # hull-only mask
    except Exception as e:  # noqa: BLE001 -- degenerate triangulation for cubic -> linear everywhere
        print(f"  (fig3: cubic interpolation unavailable ({e}); using linear)")
        Zi = lin
    return Xi, (10.0 ** Yi if logy else Yi), Zi


def render_fig3(scan, atlas_contours, limit_grid, args, kind="observed"):
    """THE headline artifact, RRR Fig 3's actual FORM -- ONE panel: the (mapyde-ATLAS)/ATLAS
    relative-difference color map as the FILL + the ATLAS reference contour + the mapyde mu95=1
    contour. Axis scales resolve per plot-guidelines.md (the published figure's scales are FACTS):
    explicit --logx/--linx/--logy/--liny > the figure contract's declared axes (--figure-target)
    > the DEFAULT x = m_slepton linear, y = Delta m LOG (the ATLAS compressed-plane convention --
    the RRR slepton target IS log-Delta m, so that case renders identically with no flags). The mu
    field feeding the CONTOUR is interpolated smoothly (see _smooth_field, in the space the figure
    is drawn in) as log10(mu) from ALL scanned points, so the mu=1 contour is a smooth curve, not
    lattice-jagged. Writes <out>__fig3.{png,pdf} for kind="observed",
    <out>__fig3_expected.{png,pdf} for kind="expected".

    LIKE-COLUMNS RULE (kind): compare expected-to-expected or observed-to-observed, never mixed --
    `kind` selects BOTH the scan mu column (mu95_obs / mu95_exp) and the reference dependent
    column (read_limit_grid). RRR Fig 3 itself is the EXPECTED-vs-expected comparison; render both
    variants and lead with the one matching the published figure.

    NEVER-INTERPOLATE-THE-REFERENCE RULE (fill): a published per-point UL grid is exact at its
    lattice and NOTHING between (sigma-UL varies ~10x between adjacent Delta m rows) -- so the fill
    colors ONLY scan points that exactly (tolerance-snap, 0.05 GeV) match a published grid point.
    Mesh rows are restricted to Delta m values with at least one exact match; a meshed cell with no
    published point is drawn WHITE with a gray open marker and the annotation says what white
    means (no published reference there -- NOT "agrees within 5%", NOT a hole, NOT interpolated;
    RRR leaves the two whites ambiguous, we do not). All scanned points -- matched or not -- still
    feed the mu=1 contour.

    COMPARISON-BASIS RULE: the fill is only meaningful if mu95 x sigma_ref_fb is the UL on the
    SAME model sigma the published grid quotes (the experiment's inclusive simplified-model sigma).
    A sample-sigma sigma_ref (e.g. an ISR-TAGGED subset sigma from the MadGraph log) is a DIFFERENT
    basis and bakes a mass-dependent tilt into the map (the 2026-07 slepton fix: tagged-6-state vs
    inclusive-4-state = 0.56..1.01 across m). Run `scan_orchestrator.py rebase` first; scans carry
    scan['model_basis'] once rebased, and _basis_guard() warns loudly when it is absent. Under a
    pure sigma re-NORMALIZATION (mu and sigma_ref scaled inversely, e.g. the NLO renorm) the fill
    is invariant; under the basis REBASE it moves -- that is the point."""
    plt, hep = setup(args)
    _basis_guard(scan, f"fig3 {kind}")
    # resolve the axis scales FIRST -- the mesh-edge geometry and the smooth-field space below
    # must be built in the same space the axes are drawn in.
    log_x = resolve_axis(args.logx, (args.contract_axes or {}).get("x"), False)
    log_y = resolve_axis(args.logy, (args.contract_axes or {}).get("y"), True)
    mu_key = {"observed": "mu95_obs", "expected": "mu95_exp"}[kind]
    rows = [p for p in scan["points"]
            if p.get("sigma_ref_fb") and p.get("dm", 0) > 0 and p.get(mu_key) is not None]
    # CR-001: quality-flagged points (floored / capped / floored-legacy, tagged at harvest) carry
    # an upper BOUND or a scan ceiling, not a measured limit -- never color them as measurements
    # and never feed them to the smooth mu-contour field. Drawn as gray 'x' + counted in the note.
    flagged = [p for p in rows if p.get("quality")]
    if flagged:
        kinds_f = sorted({p["quality"] for p in flagged})
        print(f"  (fig3 {kind}: {len(flagged)} point(s) carry a limit-quality flag {kinds_f} -- "
              f"bounds, not limits; drawn as 'x', excluded from fill+contour: "
              f"{[p.get('tag') for p in flagged]})")
        rows = [p for p in rows if not p.get("quality")]
    if len(rows) < 4:
        die(f"fig3 layout needs >=4 points with sigma_ref_fb, {mu_key} and Delta m>0, got {len(rows)}")
    skipped = [p["tag"] for p in scan["points"] if p not in rows]
    if skipped:
        print(f"  (fig3 {kind}: {len(skipped)} point(s) lack sigma_ref_fb/{mu_key} or have "
              f"Delta m<=0, skipped: {skipped})")
    mpar = np.array([p["m_parent"] for p in rows], float)
    dm = np.array([p["dm"] for p in rows], float)
    mu = np.array([p[mu_key] for p in rows], float)
    mapyde_sul = mu * np.array([p["sigma_ref_fb"] for p in rows], float)
    # EXACT reference lookup -- no interpolation, no extrapolation (rule above): NaN off-lattice
    atlas_sul = _exact_grid_lookup(*limit_grid, mpar, dm)
    rel = (mapyde_sul - atlas_sul) / atlas_sul
    matched = np.isfinite(rel)

    # THE FILL, RRR Fig 3's ACTUAL form (verified against the extracted figure, arXiv:2306.11055
    # p.6): a SPARSE, BLOCKY per-cell map on the scan lattice -- flat rectangles, mostly WHITE
    # (|diff| < 0.05 is the central white band), a few pale red/blue cells, a DISCRETE banded
    # colorbar in 0.10 steps saturating at +/-0.55. NOT a smooth interpolated heatmap (the first
    # implementation's mistake: rendered from the caption without looking at the figure).
    from matplotlib.colors import BoundaryNorm, ListedColormap
    import matplotlib.cm as mcm
    bounds = np.concatenate([np.arange(-0.55, -0.049, 0.10), [0.05],
                             np.arange(0.15, 0.551, 0.10)])           # white band spans -0.05..0.05
    # CR-026 critique fix #1: the PUBLISHED palette is the saturated pure red/white/blue 'bwr'
    # family, not the muted RdBu_r — the cell colors are this figure's payload, so the hue
    # family is a style FACT (figure-critique-fig3.md, degrades-level mismatch).
    base = mcm.get_cmap("bwr")
    colors = [base(v) for v in np.linspace(0.02, 0.44, 5)] + [(1, 1, 1, 1)] + \
             [base(v) for v in np.linspace(0.56, 0.98, 5)]
    cmap = ListedColormap(colors)
    cmap.set_under(base(0.0)); cmap.set_over(base(1.0))               # outliers saturate
    norm = BoundaryNorm(bounds, cmap.N)

    # cell edges = midpoints between adjacent lattice values, computed in the space each axis is
    # drawn in (log-space midpoints on a log axis, linear midpoints on a linear one)
    def _edges(vals, log=False):
        v = np.unique(vals)
        w = np.log10(v) if log else v
        mid = (w[:-1] + w[1:]) / 2
        e = np.concatenate([[w[0] - (mid[0] - w[0])], mid, [w[-1] + (w[-1] - mid[-1])]])
        return 10 ** e if log else e
    # mesh ONLY the Delta m rows the reference grid actually has (>=1 exact match at that dm);
    # scan-only rows are NOT drawn as fill (they would need reference interpolation) but every
    # scanned point still feeds the mu=1 contour below.
    m_vals = np.unique(mpar)
    dm_vals = np.unique(dm[matched])
    dropped_rows = sorted(set(np.unique(dm)) - set(dm_vals))
    if dropped_rows:
        print(f"  (fig3 {kind}: Delta m rows {[f'{d:g}' for d in dropped_rows]} have no published "
              f"reference point at any mass -- excluded from the fill, kept in the contour)")
    if len(dm_vals) < 2:
        die(f"fig3 {kind}: <2 Delta m rows exactly match the reference grid -- the scan lattice "
            f"and the published UL grid do not overlap (check the grid spec / --atlas-limit table)")
    m_e, dm_e = _edges(m_vals, log=log_x), _edges(dm_vals, log=log_y)
    # white-vs-hole semantics, three states per meshed cell:
    #   scanned + published point  -> colored by rel
    #   scanned + NO published pt  -> WHITE fill + gray open circle (0.0 sits in the white band;
    #                                 the annotation says white-with-circle = missing reference,
    #                                 NOT "agrees within 5%", NOT interpolated)
    #   not scanned                -> masked hole (not computed; filling it would fabricate)
    CELL = np.full((len(dm_vals), len(m_vals)), np.nan)
    SCANNED = np.zeros_like(CELL, bool)
    in_mesh = np.isin(dm, dm_vals)
    for mm, dd, rr in zip(mpar[in_mesh], dm[in_mesh], rel[in_mesh]):
        i, j = np.searchsorted(dm_vals, dd), np.searchsorted(m_vals, mm)
        CELL[i, j] = rr
        SCANNED[i, j] = True
    missing_ref = SCANNED & ~np.isfinite(CELL)
    n_missing = int(missing_ref.sum())
    FILL = np.ma.masked_where(~SCANNED, np.where(missing_ref, 0.0, CELL))

    fig, ax = plt.subplots(figsize=(8.5, 7))
    pc = ax.pcolormesh(m_e, dm_e, FILL, cmap=cmap, norm=norm, zorder=1)
    if n_missing:
        miss_dm, miss_m = np.where(missing_ref)
        ax.plot(m_vals[miss_m], dm_vals[miss_dm], ls="none", marker="o", ms=6, mfc="none",
                mec="0.55", mew=1.1, zorder=3)
    if flagged:
        ax.plot([p["m_parent"] for p in flagged], [p["dm"] for p in flagged], ls="none",
                marker="x", ms=7, color="0.35", mew=1.6, zorder=3)
    cb = fig.colorbar(pc, ax=ax, pad=0.02, ticks=bounds, extend="both")
    cb.ax.set_yticklabels([f"{b:.2f}" for b in bounds])
    cb.set_label(r"Limits on $\mu_{\mathrm{SUSY}}$: (mapyde $-$ ATLAS) / ATLAS")

    from matplotlib.lines import Line2D
    handles = []
    # the mapyde exclusion contour, a smooth LINE (like RRR's "DELPHES, tuned" blue line):
    # log10(mu)=0 on the smoothly-interpolated grid (not the lattice)
    _, _, LMU = _smooth_field(mpar, dm, np.log10(np.clip(mu, 1e-12, None)), logy=log_y)
    M, DM, _ = _smooth_field(mpar, dm, rel, logy=log_y)
    cs = ax.contour(M, DM, LMU, levels=[0.0], colors=[house.OKABE_ITO["blue"]],
                    linewidths=2.0, zorder=6)
    if getattr(cs, "allsegs", [[]])[0]:
        handles.append(Line2D([], [], color=house.OKABE_ITO["blue"], lw=2.0,
                              label=f"mapyde (native), 95% CL {kind[:3]}."))
    else:
        print(f"  (fig3 {kind}: no mu95=1 crossing inside the scanned hull -- mapyde contour not drawn)")
    # ATLAS published contour: observed as round DOTS (RRR's "ATLAS" blue dots); expected dashed
    for role, path, x, y, xn, yn in atlas_contours:
        xx, yy = _orient_dm(x, y, xn, yn)
        if role.startswith("observed"):
            ax.plot(xx, yy, ls="none", marker="o", ms=3.2, color=house.OKABE_ITO["blue"],
                    mec="none", zorder=5)
            # label the dots by COLUMN, not just "ATLAS" (RRR's own bare label): on the
            # expected-variant panel the dots are still the published OBSERVED contour, and an
            # unlabeled mixed overlay reads as like-columns when it is not (Tier-B 2026-08-28
            # finding 4). The FILL stays like-columns in both variants.
            handles.append(Line2D([], [], marker="o", ls="none", ms=5,
                                  color=house.OKABE_ITO["blue"], mec="none",
                                  label="ATLAS observed"))
        else:
            ax.plot(xx, yy, color="0.35", ls="--", lw=1.2, zorder=5)
            handles.append(Line2D([], [], color="0.35", ls="--", lw=1.2,
                                  label=f"ATLAS {role.replace('_', ' ')}"))

    # axes: the RESOLVED scales (contract/flags above; default = ATLAS compressed-plane
    # convention, LOG Delta m + linear m). A log axis is floored at the smallest positive value
    # among everything plotted (log cannot show 0); a linear Delta m axis keeps a 0 baseline.
    all_dm = np.concatenate([dm] + [ _orient_dm(x, y, xn, yn)[1]
                                     for _, _, x, y, xn, yn in atlas_contours])
    all_m = np.concatenate([mpar] + [ _orient_dm(x, y, xn, yn)[0]
                                      for _, _, x, y, xn, yn in atlas_contours])
    if log_y:
        dm_floor = float(all_dm[all_dm > 0].min())
        ax.set_yscale("log")
        ax.set_ylim(0.9 * dm_floor, 1.25 * float(all_dm.max()))
    else:
        dm_hi = float(all_dm.max())
        dm_lo = float(all_dm.min())
        ax.set_ylim(max(0.0, dm_lo - 0.05 * (dm_hi - dm_lo)), dm_hi + 0.25 * (dm_hi - dm_lo))
    if log_x:
        m_floor = float(all_m[all_m > 0].min())
        ax.set_xscale("log")
        ax.set_xlim(0.95 * min(float(mpar.min()), m_floor), 1.05 * max(float(mpar.max()),
                                                                       float(all_m.max())))
    else:
        ax.set_xlim(min(mpar.min(), all_m.min()) - 5, max(mpar.max(), all_m.max()) + 5)
    ax.set_xlabel(r"$m_{\tilde{\ell}}$ [GeV]")
    ax.set_ylabel(r"$\Delta m(\tilde{\ell},\tilde{\chi}^0_1)$ [GeV]")
    # the fill occupies the WHOLE panel, so the experiment label goes ABOVE the axes (mplhep
    # loc=0) instead of inside top-left, where it would sit on the color map + ATLAS contour
    if hep is not None:
        explabel = getattr(hep, args.experiment.lower()).label
        try:
            explabel(ax=ax, data=True, text="", lumi=args.lumi, com=args.com, loc=0)
        except TypeError:
            header(ax, hep, args)
    # explicit proxy handles need labels too (smart_legend forwards both or neither); the
    # experiment label sits ABOVE the axes here (loc=0), so the inside top-left is a real
    # candidate — and the exclusion contours sweep the TOP of the plane, so the LOWER corners
    # (fill-only regions) must be candidates too (the smart_legend docstring's mass-plane case)
    house.smart_legend(ax, handles=handles, labels=[h.get_label() for h in handles],
                       fontsize=10, reserve_label_corner=False, reserved_corners=(),
                       candidates={"upper right": (0.58, 1.00, 0.55, 1.00),
                                   "upper left": (0.00, 0.42, 0.55, 1.00),
                                   "lower right": (0.58, 1.00, 0.00, 0.45),
                                   "lower left": (0.00, 0.42, 0.00, 0.45)})
    med = 100 * float(np.nanmedian(np.abs(rel)))
    lines = [rf"$\mathbf{{{(scan.get('analysis_id') or '').replace('_', chr(92)+'_')}}}$  vs ATLAS",
             f"{kind} limits, both sides",
             f"{scan['n_done']}/{scan['n_planned']} grid points",
             f"median |rel diff| = {med:.1f} percent ({int(matched.sum())} ref-matched cells)",
             "95% CL exclusion (CLs), not a discovery"]
    if n_missing:
        lines.insert(4, rf"$\circ$ white cell: no published ref point")
    if flagged:
        lines.insert(4, rf"$\times$ floored/capped $\mu_{{95}}$: bound, not a limit (CR-001)")
    if scan.get("model_basis"):
        lines.insert(1, r"$\mu$ on incl. model $\sigma$ (WG NLO+NLL)")
    elif scan.get("nlo_renorm"):
        lines.insert(1, r"signal $\sigma$: NLO+NLL (per-mass $k$)")
    house.smart_annotate(ax, lines, fontsize=10)   # scored corners; sees the legend + contours
    house.tick_hygiene(ax, axr=None, logy=log_y, logx=log_x)
    if log_y:
        # a ~2-decade log axis labels only 1 and 10 by default -- too sparse to read Delta m off
        # the figure; label the 1-2-5 sequence instead (plot-guidelines: control density, keep
        # readable). FuncFormatter, not ScalarFormatter: the latter rounds sub-decade ticks
        # (0.5 -> "0") on log. (Linear axes keep tick_hygiene's MaxNLocator density control.)
        from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter
        ax.yaxis.set_major_locator(LogLocator(base=10, subs=(1.0, 2.0, 5.0)))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:g}"))
        ax.yaxis.set_minor_formatter(NullFormatter())
    save(fig, args.out + ("__fig3" if kind == "observed" else f"__fig3_{kind}"))
    print(f"fig3 single panel ({kind}): axes x={'log' if log_x else 'linear'} "
          f"y={'log' if log_y else 'linear'}; {len(rows)} points, {int(matched.sum())} exactly on the "
          f"published grid ({n_missing} meshed-but-unpublished -> white+circle), "
          f"median |rel diff| = {med:.1f}%, "
          f"mapyde mu=1 contour {'drawn' if handles and 'mapyde' in handles[0].get_label() else 'MISSING'}, "
          f"{len(atlas_contours)} ATLAS contour(s)")


# ----------------------------------------------------------------- ATLAS per-point limit grid (diff map)
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
    if len(iv) < 2 or not dv:
        die(f"--atlas-limit {path}: expected a 2-D per-point limit grid (2 independent mass vars + a "
            f"dependent UL), got {len(iv)} indep / {len(dv)} dep. Pick the 'upper-cross-section-limits' "
            f"table (kind=limit in hepdata_manifest.json), not the exclusion-contour boundary.")

    def hdr(v):
        return v.get("header", {}) or {}

    def is_dm(v):
        nm = hdr(v).get("name", "") or ""
        return "delta" in nm.lower() or "\\Delta" in nm or "Δ" in nm
    key = {"observed": "observ", "expected": "expect"}[kind]
    di = next((i for i, v in enumerate(dv) if key in (hdr(v).get("name", "") or "").lower()), None)
    if di is None:
        if kind == "observed" and len(dv) == 1:
            di = 0   # single unnamed UL column: treat as observed (the common HEPData minimal case)
        else:
            die(f"--atlas-limit {path}: no dependent column matching '{kind}' "
                f"(columns: {[hdr(v).get('name') for v in dv]})")
    x0 = np.array([r["value"] for r in iv[0]["values"]], float)
    x1 = np.array([r["value"] for r in iv[1]["values"]], float)
    sig = np.array([r["value"] for r in dv[di]["values"]], float)
    m, dm = (x1, x0) if (is_dm(iv[0]) and not is_dm(iv[1])) else (x0, x1)
    units = (hdr(dv[di]).get("units", "") or "").lower()
    if units == "pb":
        sig = sig * 1000.0
    elif units not in ("fb", ""):
        print(f"  (warning: --atlas-limit dep units '{units}' not pb/fb; assuming fb)")
    return m, dm, sig


def _exact_grid_lookup(gx, gy, gz, qx, qy, atol=0.05):
    """EXACT (tolerance-snapped, default 0.05 GeV) lookup of a published per-point grid: NaN wherever
    the query is not a lattice point. The fig3 fill uses THIS, never _interp_grid — a published UL
    grid is a set of exact statements at its own lattice; interpolating (let alone nearest-neighbour
    extrapolating) a quantity that varies ~10x between adjacent Delta m rows fabricates reference
    values that were never published (never-interpolate-the-reference rule,
    docs/workflow/checklists/scan-and-contour.md)."""
    gx = np.asarray(gx, float); gy = np.asarray(gy, float); gz = np.asarray(gz, float)
    out = np.full(len(qx), np.nan)
    for i, (x, y) in enumerate(zip(qx, qy)):
        hit = np.where((np.abs(gx - x) <= atol) & (np.abs(gy - y) <= atol))[0]
        if hit.size == 1:
            out[i] = gz[hit[0]]
        elif hit.size > 1:
            print(f"  (exact lookup: {hit.size} reference points within {atol} GeV of "
                  f"({x:g},{y:g}) -- ambiguous, leaving unmatched)")
    return out


def _interp_grid(gx, gy, gz, qx, qy):
    """Interpolate scattered grid (gx,gy)->gz onto query points (qx,qy): linear, nearest fallback for
    points outside the convex hull. scipy if present, else pure-numpy nearest neighbour. DIAGNOSTIC
    use only (the __reldiff two-panel); the headline fig3 fill uses _exact_grid_lookup instead."""
    try:
        from scipy.interpolate import griddata
        out = griddata((gx, gy), gz, (qx, qy), method="linear")
        nan = ~np.isfinite(out)
        if nan.any():
            out[nan] = griddata((gx, gy), gz, (qx[nan], qy[nan]), method="nearest")
        return out
    except ImportError:
        out = np.empty(len(qx))
        for i, (x, y) in enumerate(zip(qx, qy)):
            out[i] = gz[int(np.argmin((gx - x) ** 2 + (gy - y) ** 2))]
        return out


def render_diffmap(scan, atlas_contours, limit_grid, args):
    """The RRR Fig-3 figure-of-merit: the (mapyde−ATLAS)/ATLAS relative difference in the σ upper limit
    (≡ the difference in the signal-strength limit µ — but ONLY when both σ-ULs are quoted on the SAME
    model σ, which then cancels in the ratio; see _basis_guard and the scan-and-contour checklist).
    mapyde σ_UL = µ95_obs × σ_ref (both from scan.json); ATLAS σ_UL is the published per-point grid,
    interpolated onto the scanned points. 2-D grid → tricontourf color map; a 1-D line → a rel-diff curve."""
    plt, hep = setup(args)
    _basis_guard(scan, "diff map")
    rows = [p for p in scan["points"] if p.get("sigma_ref_fb")]
    missing = [p["tag"] for p in scan["points"] if not p.get("sigma_ref_fb")]
    if not rows:
        die("the difference map needs sigma_ref_fb per point (σ_UL = µ95×σ_ref). Re-assemble the scan "
            "after the runs (scan_orchestrator reads it from logs/madgraph.log×kfactor); the contour "
            "overlay still renders without --atlas-limit.")
    if missing:
        print(f"  (diff map: {len(missing)} point(s) lack sigma_ref_fb, skipped: {missing})")
    mpar = np.array([p["m_parent"] for p in rows], float)
    dm = np.array([p["dm"] for p in rows], float)
    mapyde_sul = np.array([p["mu95_obs"] * p["sigma_ref_fb"] for p in rows], float)
    atlas_sul = _interp_grid(*limit_grid, mpar, dm)
    rel = (mapyde_sul - atlas_sul) / atlas_sul
    twoD = (len(np.unique(mpar)) >= 2 and len(np.unique(dm)) >= 2 and len(rows) >= 3)

    fig, ax = plt.subplots(figsize=(8, 7) if twoD else (8, 6))
    # ROBUST color scale: a few corner points (very light sleptons / tiny Δm) can blow the rel-diff to
    # many-hundred % (LO σ + fast-sim break down there); scaling to the max washes out the bulk. Clamp to
    # a robust percentile so the typical ~±tens-of-% structure is visible; outliers SATURATE (extend=both).
    absr = np.abs(rel[np.isfinite(rel)]) if len(rel) else np.array([1.0])
    vmax = float(np.nanpercentile(absr, 85)) if absr.size else 1.0
    vmax = min(max(vmax, 0.1), 1.5)
    if twoD:
        import matplotlib.tri as mtri
        tri = mtri.Triangulation(mpar, dm)
        tcf = ax.tricontourf(tri, np.clip(rel, -vmax, vmax), levels=np.linspace(-vmax, vmax, 21),
                             cmap="RdBu_r", extend="both")
        cb = fig.colorbar(tcf, ax=ax, pad=0.02)
        cb.set_label(r"$(\mu_{95}^{\mathrm{mapyde}}-\mu_{95}^{\mathrm{ATLAS}})/\mu_{95}^{\mathrm{ATLAS}}$")
        ax.plot(mpar, dm, "k.", ms=4, zorder=4)
        try:
            cs = ax.tricontour(tri, np.array([p["mu95_obs"] for p in rows], float), levels=[1.0],
                               colors=[house.OKABE_ITO["bluishgreen"]], linewidths=2.2, zorder=6)
            if getattr(cs, "allsegs", [[]])[0]:
                from matplotlib.lines import Line2D
                ax.add_line(Line2D([], [], color=house.OKABE_ITO["bluishgreen"], lw=2.2,
                                   label=r"mapyde 95% CL excl."))
        except Exception:
            pass
        for role, path, x, y, xn, yn in atlas_contours:
            xx, yy = np.asarray(x, float), np.asarray(y, float)
            def _isdm(nm): return bool(nm) and ("delta" in nm.lower() or "\\Delta" in nm or "Δ" in nm)
            if _isdm(xn) and not _isdm(yn): xx, yy = yy, xx
            elif not _isdm(xn) and not _isdm(yn): yy = xx - yy
            ax.plot(xx, yy, "k-" if role.startswith("observed") else "k--", lw=1.8, zorder=5,
                    label=f"ATLAS {role.replace('_', ' ')}")
        ax.set_xlabel(r"$m_{\tilde{\ell}}$ [GeV]"); ax.set_ylabel(r"$\Delta m$ [GeV]")
        if ax.get_legend_handles_labels()[0]:
            house.smart_legend(ax, fontsize=10, reserved_corners=(),
                               candidates={"upper right": (0.58, 1.00, 0.55, 1.00),
                                           "upper left": (0.00, 0.42, 0.55, 1.00),
                                           "lower right": (0.58, 1.00, 0.00, 0.45),
                                           "lower left": (0.00, 0.42, 0.00, 0.45)})
    else:  # 1-D line: rel-diff vs Δm at the single mass
        order = np.argsort(dm)
        ax.axhline(0, color="0.5", lw=1)
        ax.plot(dm[order], 100 * rel[order], "o-", color=house.OKABE_ITO["vermillion"], lw=2, ms=6)
        ax.set_xlabel(r"$\Delta m(\tilde{\ell},\tilde{\chi}^0_1)$ [GeV]")
        ax.set_ylabel(r"$(\sigma_{\mathrm{UL}}^{\mathrm{mapyde}}-\sigma_{\mathrm{UL}}^{\mathrm{ATLAS}})"
                      r"/\sigma_{\mathrm{UL}}^{\mathrm{ATLAS}}$  [%]")
        ax.text(0.5, 0.04, f"m={mpar[0]:g} GeV  ·  1-D slice of the difference map (need a 2-D grid for "
                f"the color map)", transform=ax.transAxes, ha="center", va="bottom", fontsize=9, color="0.4")
    # the fill occupies the whole panel -> experiment label ABOVE the axes (as in render_fig3);
    # inside-axes placement was found overdrawn by the 2026-08-28 Tier-B panel.
    if hep is not None:
        explabel = getattr(hep, args.experiment.lower()).label
        try:
            explabel(ax=ax, data=True, text="", lumi=args.lumi, com=args.com, loc=0)
        except TypeError:
            header(ax, hep, args)
    house.smart_annotate(ax, [
        rf"$\mathbf{{{(scan.get('analysis_id') or '').replace('_', chr(92)+'_')}}}$  vs ATLAS",
        "rel. diff in the 95% CL limit (RRR Fig-3 figure-of-merit)",
        "smoothly INTERPOLATED between lattice points" if twoD else "1-D slice",
        "(diagnostic; exact per-cell map: __fig3)",
        f"median |rel diff| = {100*float(np.nanmedian(np.abs(rel))):.1f} percent"], fontsize=10)
    house.tick_hygiene(ax, axr=None, logy=False, logx=False)
    stem = args.out + "__reldiff"
    save(fig, stem)
    print(f"difference map ({'2-D color map' if twoD else '1-D line slice'}): "
          f"{len(rows)} points, median |(mapyde-ATLAS)/ATLAS| = {100*float(np.nanmedian(np.abs(rel))):.1f}%")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan", required=True, help="scan.json from scan_orchestrator.py assemble")
    ap.add_argument("--atlas-contour", action="append", default=[], metavar="ROLE=PATH",
                    help="optional ATLAS HEPData reference contour(s) to overlay (RRR comparison)")
    ap.add_argument("--atlas-limit", default=None, metavar="HEPDATA_UL.yaml",
                    help="optional ATLAS per-point σ upper-limit grid (HEPData 'upper cross-section "
                         "limits' table) → also render the (mapyde−ATLAS)/ATLAS difference map (RRR Fig 3b)")
    ap.add_argument("--limit-kind", choices=["observed", "expected", "both"], default="both",
                    help="which limit column(s) the fig3 fill compares (LIKE-COLUMNS rule: the scan's "
                         "mu95_obs against the reference's Observed UL, mu95_exp against Expected — "
                         "never mixed). 'both' renders the two variants (__fig3 = observed, "
                         "__fig3_expected = expected); RRR Fig 3 itself is expected-vs-expected. "
                         "A variant is skipped with a warning if either side lacks that column.")
    ap.add_argument("--experiment", default="ATLAS", choices=["ATLAS", "CMS"])
    ap.add_argument("--com", type=float, default=13)
    ap.add_argument("--lumi", type=float, default=None)
    ap.add_argument("--out", required=True, help="output stem (.pdf + .png)")
    ap.add_argument("--layout", choices=["auto", "line", "grid"], default="auto")
    # ---- axis scales (plot-guidelines.md: the published figure's scales are FACTS, not
    #      defaults). --figure-target consumes the axes DECLARED in the run's figure contract
    #      (figure_target.py declare --axes-x/--axes-y); the explicit per-axis flags override
    #      even that. With neither, each layout keeps its historical default (fig3 = log Delta m,
    #      the ATLAS compressed-plane convention; grid = linear/linear; line = span heuristic).
    ap.add_argument("--figure-target", default=None, metavar="RUNDIR_OR_JSON",
                    help="rundir (or figure_target.json path) whose declared published axes the "
                         "grid/fig3 layouts must match")
    ap.add_argument("--figure-id", default=None,
                    help="which contract target's axes to use (default: the primary target)")
    gx = ap.add_mutually_exclusive_group()
    gx.add_argument("--logx", dest="logx", action="store_const", const=True, default=None,
                    help="force the x axis logarithmic (overrides the contract axes)")
    gx.add_argument("--linx", dest="logx", action="store_const", const=False,
                    help="force the x axis linear (overrides the contract axes)")
    gy = ap.add_mutually_exclusive_group()
    gy.add_argument("--logy", dest="logy", action="store_const", const=True, default=None,
                    help="force the y axis logarithmic (overrides the contract axes)")
    gy.add_argument("--liny", dest="logy", action="store_const", const=False,
                    help="force the y axis linear (overrides the contract axes)")
    ap.add_argument("--no-lint", action="store_true",
                    help="downgrade the CR-016 plot-lint gate to WARN (violations still printed)")
    args = ap.parse_args()
    global LINT_ALLOW
    LINT_ALLOW = args.no_lint

    # declared published axes from the figure contract (consumed by the grid/fig3 layouts,
    # which draw the published plane; None = no contract given / no axes recorded)
    args.contract_axes = None
    if args.figure_target:
        from . import figure_target
        args.contract_axes = figure_target.read_axes(args.figure_target,
                                                     figure_id=args.figure_id)
        if args.contract_axes:
            print(f"axes from figure contract: x={args.contract_axes.get('x')} "
                  f"y={args.contract_axes.get('y')} "
                  f"(source: {args.contract_axes.get('source')})")
        else:
            print("(figure contract declares no axes record -- renderer defaults apply; "
                  "record the published scales with figure_target.py declare --axes-x/--axes-y)")

    scan = load_scan(args.scan)
    atlas = []
    if args.atlas_contour:
        for role, path in parse_contour_args(args.atlas_contour):
            if not os.path.exists(path):
                die(f"--atlas-contour not found: {path}")
            x, y, xn, yn = read_contour(path)
            atlas.append((role, path, x, y, xn, yn))

    pts = scan["points"]
    n_m = len({round(p["m_parent"], 3) for p in pts})
    n_dm = len({round(p["dm"], 3) for p in pts})
    layout = args.layout
    if layout == "auto":
        layout = "grid" if (n_m >= 2 and n_dm >= 2) else "line"
    if layout == "line":
        if n_dm < 2:
            die(f"line layout needs >=2 distinct Delta m, got {n_dm}")
        render_line(scan, atlas, args)
    else:
        render_grid(scan, atlas, args)

    # the (mapyde−ATLAS)/ATLAS difference map — the two-panel diagnostic (observed, interpolated)
    limit_grid = None
    if args.atlas_limit:
        if not os.path.exists(args.atlas_limit):
            die(f"--atlas-limit not found: {args.atlas_limit}")
        limit_grid = read_limit_grid(args.atlas_limit, kind="observed")
        render_diffmap(scan, atlas, limit_grid, args)

    # RRR Fig 3's actual FORM — the DEFAULT headline artifact whenever both references are
    # available with a 2-D grid: ONE panel = rel-diff fill (EXACT reference matches only) + ATLAS
    # contour + mapyde mu=1 contour on a LOG-Delta-m axis. kinds per --limit-kind (LIKE-COLUMNS
    # rule): observed → <out>__fig3, expected → <out>__fig3_expected (the RRR Fig-3 convention).
    # The two-panel outputs above remain as diagnostics.
    if layout == "grid" and atlas and limit_grid is not None:
        kinds = ["observed", "expected"] if args.limit_kind == "both" else [args.limit_kind]
        for kind in kinds:
            if kind == "expected" and not any(p.get("mu95_exp") is not None for p in scan["points"]):
                print("  (fig3 expected: scan.json has no mu95_exp -- variant skipped)")
                continue
            if kind == "observed":
                grid_k = limit_grid
            else:
                try:
                    grid_k = read_limit_grid(args.atlas_limit, kind=kind)
                except SystemExit:
                    if args.limit_kind == "both":   # default sweep: table simply lacks the column
                        print("  (fig3 expected: --atlas-limit table has no Expected column -- "
                              "variant skipped)")
                        continue
                    raise
            render_fig3(scan, atlas, grid_k, args, kind=kind)


if __name__ == "__main__":
    main()
