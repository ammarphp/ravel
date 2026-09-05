#!/usr/bin/env python
"""SINGLE-POINT quick-look: locate ONE tested model point on a published SUSY mass-plane contour.

  >>> SCOPE NOTE (read docs/workflow/steps/08-scan.md). This is the UNIT-LEVEL / SANITY view: it takes ONE
  >>> model point and its one pyhf mu95, and marks it (green=excluded / red=allowed) on the EXPERIMENT'S
  >>> ALREADY-PUBLISHED contour. It does NOT reproduce that contour -- it treats the published curve as
  >>> ground truth and locates our point relative to it. That is useful as a sanity check, but it is NOT
  >>> the RRR deliverable. RRR's deliverable is a GRID SCAN whose own mu95 values are interpolated into a
  >>> contour (reproduction: mapyde-vs-ATLAS; reinterpretation: a brand-new region). That scanned contour
  >>> is rendered by `scan_contour.py` (fed by `scan_orchestrator.py`), NOT here. Use this for a quick
  >>> "is my one point inside the published exclusion?"; use scan_contour.py for the actual reproduction.

The canonical summary figure for a SUSY exclusion search is the mass plane: the 95% CL exclusion
contour in the m(parent)-m(LSP) plane, with the tested point marked. NO detector-level Rivet/
SimpleAnalysis routine emits this figure (they emit per-SR yields / cutflows), so this quick-look fills
that gap for a SINGLE point -- the headline figure a referee reads one hypothesis off at a glance.

This is a faithful-FORM reproduction, NOT a raster overlay onto the published PNG: we re-plot the
PUBLISHED contour NUMBERS (from HEPData) correctly, in the experiment's house style (mplhep, via the
shared mplhep_style.py module), and graft the tested model point + this reproduction's mu95 verdict on
top. The published observed limit is the solid contour; the expected limit is the dashed contour (with
the +/-1sigma band if it is shipped, else synthesized from the pyhf expected band and labelled
honestly). The tested point is a star -- GREEN if obs mu95 < 1 (excluded by this reproduction) else
RED (allowed). The kinematically-forbidden region m(LSP) > m(parent) is shaded.

It sets a 95% CL EXCLUSION, never a 5sigma discovery -- the header says so.

The plotter is GENERAL (not hard-wired to one analysis): contours are read from HEPData YAML files
(one independent_variables[0] list = x = m(parent), one dependent_variables[0] list = y = m(LSP); the
vertex order is the polyline tracing the boundary and is NOT sorted -- sorting scrambles a boundary
that doubles back). Multiple contours can be passed (observed / expected / channel variants) each with
its own role + style.

Usage (anchor case -- C1N2 wino->WZ, the recon-chosen example):
  mass_plane_overlay.py \
    --contour observed=outputs/hepdata/tables/.../data14.yaml \
    --contour expected=outputs/hepdata/tables/.../data13.yaml \
    --point 300,100 --mu95-obs 2.130 --mu95-exp 1.060 \
    --analysis ATLAS_2018_I1676551 --experiment ATLAS --com 13 --lumi 36.1 \
    --parent-label 'm(#tilde{chi}_{1}^{#pm}/#tilde{chi}_{2}^{0})' --lsp-label 'm(#tilde{chi}_{1}^{0})' \
    --model-label 'wino C1N2(300,100)->WZ' \
    --exp-band-lo 0.544 --exp-band-hi 2.191 \
    --out <rundir>/plots/named/ATLAS_2018_I1676551__massplane__C1N2-300-100

A --contour argument is ROLE=PATH where ROLE in {observed, expected, observed_aux, expected_aux}.
`observed`/`expected` are the headline solid/dashed curves; `*_aux` are thin per-channel overlays.

AXIS SCALING (docs/workflow/checklists/plot-guidelines.md): the PUBLISHED figure's axis scales are FACTS,
not defaults. When the run declared them in the figure contract (figure_target.py declare
--axes-x/--axes-y), pass --figure-target <rundir-or-figure_target.json> and this plotter CONSUMES
the declared scales. Resolution per axis: explicit --logx/--logy/--linx/--liny > the contract's
declared axes (--figure-target) > the per-plane auto default (--log-auto): LOG Delta m on the
compressed (dm) plane (spans ~0.4-40 GeV ~2 decades, and the published ATLAS compressed-spectrum
figures are log), LINEAR on the mass-mass plane (<1 decade). The >~1.5-decade span heuristic applies
ONLY when there is no published reference. On a log axis the lower limit is floored to the smallest
positive data value (log(<=0) is undefined), and the axis title still names the variable + units
(never log(variable)).

See docs/workflow/steps/05-visualize.md, docs/workflow/checklists/plot-guidelines.md, and .claude/rules/plots.md.
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
from ravel.limits import read_limits, LimitCurve, LimitResult, STATUSES

from . import mplhep_style as house


# ----------------------------------------------------------------- HEPData contour I/O
def read_contour(path):
    """Read a HEPData-YAML exclusion-contour table into (x, y) polyline arrays.

    x = independent_variables[0].values (m(parent), e.g. "M(NLSP) [GeV]")
    y = dependent_variables[0].values   (m(LSP),    e.g. "M(LSP) [GeV]")

    The vertex order is the ordered boundary polyline -- returned AS-IS (never sorted; the boundary can
    double back, and sorting by x would scramble it). Returns (x, y, xname, yname).
    """
    import yaml
    with open(path) as fh:
        doc = yaml.safe_load(fh)
    try:
        iv = doc["independent_variables"][0]
        dv = doc["dependent_variables"][0]
    except (KeyError, IndexError, TypeError) as e:
        sys.exit(f"contour {path}: not a HEPData contour table ({e})")
    x = np.array([row["value"] for row in iv["values"]], float)
    y = np.array([row["value"] for row in dv["values"]], float)
    if len(x) != len(y):
        sys.exit(f"contour {path}: x ({len(x)}) and y ({len(y)}) length mismatch")
    xname = iv.get("header", {}).get("name", "m(parent) [GeV]")
    yname = dv.get("header", {}).get("name", "m(LSP) [GeV]")
    return x, y, xname, yname


def parse_contour_args(specs):
    """Parse ROLE=PATH strings into an ordered list of (role, path). Defaults bare paths to observed."""
    out = []
    for s in specs:
        if "=" in s:
            role, path = s.split("=", 1)
            role = role.strip().lower()
        else:
            role, path = "observed", s
        if role not in ("observed", "expected", "observed_aux", "expected_aux"):
            sys.exit(f"--contour role '{role}' not in observed/expected/observed_aux/expected_aux")
        out.append((role, path))
    return out


# ----------------------------------------------------------------- TeX-ify ROOT-style labels
def texify(s):
    """Render common ROOT-style mass labels as matplotlib mathtext; pass through if already TeX/plain.

    Accepts e.g. 'm(#tilde{chi}_{1}^{#pm}/#tilde{chi}_{2}^{0})' and produces a $...$ mathtext string.
    """
    if s is None:
        return s
    if s.startswith("$") and s.endswith("$"):
        return s
    repl = {
        "#tilde": r"\tilde", "#chi": r"\chi", "#pm": r"\pm", "#mp": r"\mp",
        "#nu": r"\nu", "#ell": r"\ell", "#tau": r"\tau", "#mu": r"\mu",
        "#Delta": r"\Delta", "#rightarrow": r"\rightarrow", "#to": r"\to",
        "#geq": r"\geq", "#leq": r"\leq", "#times": r"\times",
    }
    has_macro = "#" in s or any(t in s for t in ("_{", "^{", "\\"))
    body = s
    for k, v in repl.items():
        body = body.replace(k, v)
    if not has_macro:
        return s  # plain text -- let matplotlib draw it as-is
    body = body.replace(" ", r"\ ")
    return f"${body}$"


# ----------------------------------------------------------------- the plot
def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contour", action="append", required=True, metavar="ROLE=PATH",
                    help="HEPData YAML contour; ROLE in observed/expected/observed_aux/expected_aux "
                         "(bare path => observed). Repeatable.")
    ap.add_argument("--point", required=True, metavar="X,Y",
                    help="tested point in GeV, in the PLANE's coordinates: 'm_parent,m_lsp' on the "
                         "mass plane; 'm,Delta_m' on --plane dm (e.g. 300,100 or 150,20)")
    ap.add_argument("--mu95-obs", type=float,
                    help="legacy reported observed value; prefer --limit-artifact to retain numerical status")
    ap.add_argument("--mu95-exp", type=float, default=None, help="expected (median) mu95 from pyhf")
    ap.add_argument("--limit-artifact", help="exclusion/result JSON carrying per-curve statuses and brackets")
    ap.add_argument("--mu95-obs-status", choices=sorted(STATUSES), default="legacy_reported")
    ap.add_argument("--mu95-exp-status", choices=sorted(STATUSES), default="legacy_reported")
    ap.add_argument("--analysis", required=True, help="analysis id, e.g. ATLAS_2018_I1676551")
    ap.add_argument("--experiment", default="ATLAS", choices=["ATLAS", "CMS"])
    ap.add_argument("--com", type=float, default=13, help="sqrt(s) in TeV")
    ap.add_argument("--lumi", type=float, default=None, help="integrated luminosity in fb^-1")
    ap.add_argument("--parent-label", default="m(parent)",
                    help="ROOT/TeX label for the parent mass axis (without [GeV])")
    ap.add_argument("--lsp-label", default="m(LSP)",
                    help="ROOT/TeX label for the LSP mass axis (without [GeV])")
    ap.add_argument("--model-label", default="tested point", help="legend label for the marked point")
    ap.add_argument("--exp-band-lo", type=float, default=None,
                    help="if the +/-1sigma expected band is NOT shipped in HEPData, give the pyhf "
                         "expected -1sigma mu95 to SYNTHESIZE the band (labelled as synthesized)")
    ap.add_argument("--exp-band-hi", type=float, default=None,
                    help="pyhf expected +1sigma mu95 (paired with --exp-band-lo)")
    ap.add_argument("--xlim", default=None, help="x range 'lo,hi' (GeV); auto from contours if omitted")
    ap.add_argument("--ylim", default=None, help="y range 'lo,hi' (GeV); auto if omitted")
    ap.add_argument("--plane", choices=["mass", "dm", "auto"], default="auto",
                    help="mass = m(parent) vs m(LSP) (draws the m_LSP=m_parent diagonal); "
                         "dm = compressed plane m(sparticle) vs Delta m (no diagonal); "
                         "auto detects 'Delta m' in a contour axis header")
    # ---- axis scaling. The decisive rule (docs/workflow/checklists/plot-guidelines.md): the PUBLISHED
    #      figure's axis scales are FACTS -- when the figure contract declared them, consume them
    #      via --figure-target. Per-axis resolution: explicit --logx/--logy/--linx/--liny > the
    #      contract's declared axes > the per-plane auto default (compressed dm plane = LOG Delta m,
    #      ~2 decades + the published ATLAS compressed-spectrum figures are log; mass-mass plane =
    #      LINEAR, <1 decade; regression-safe for C1N2).
    ap.add_argument("--figure-target", default=None, metavar="RUNDIR_OR_JSON",
                    help="rundir (or figure_target.json path) whose DECLARED published axes this "
                         "figure must match (figure_target.py declare --axes-x/--axes-y); explicit "
                         "--logx/--logy/--linx/--liny still override")
    ap.add_argument("--figure-id", default=None,
                    help="which contract target's axes to use (default: the primary target)")
    lx = ap.add_mutually_exclusive_group()
    lx.add_argument("--logx", dest="logx", action="store_const", const=True, default=None,
                    help="force the x axis logarithmic (overrides --log-auto)")
    lx.add_argument("--linx", dest="logx", action="store_const", const=False,
                    help="force the x axis linear (overrides --log-auto)")
    ly = ap.add_mutually_exclusive_group()
    ly.add_argument("--logy", dest="logy", action="store_const", const=True, default=None,
                    help="force the y axis logarithmic (overrides --log-auto)")
    ly.add_argument("--liny", dest="logy", action="store_const", const=False,
                    help="force the y axis linear (overrides --log-auto)")
    ap.add_argument("--log-auto", action="store_true", default=True,
                    help="(default) auto axis scaling: LOG Delta m on the dm plane, LINEAR mass-mass")
    ap.add_argument("--out", required=True, help="output stem (writes .pdf AND .png)")
    ap.add_argument("--no-lint", action="store_true",
                    help="downgrade the CR-016 plot-lint gate to WARN")
    args = ap.parse_args()
    try:
        if args.limit_artifact:
            with open(args.limit_artifact) as fh:
                limits = read_limits(json.load(fh))
            for given, curve in ((args.mu95_obs, limits.observed), (args.mu95_exp, limits.expected[2])):
                if given is not None and given != curve.value:
                    raise ValueError("CLI scalar conflicts with limit artifact")
            args.mu95_obs, args.mu95_exp = limits.observed.value, limits.expected[2].value
        else:
            if args.mu95_obs is None:
                ap.error("provide --limit-artifact or an explicitly reported --mu95-obs")
            expected = [LimitCurve(None, "missing") for _ in range(5)]
            if args.mu95_exp is not None:
                expected[2] = LimitCurve(args.mu95_exp, args.mu95_exp_status)
            limits = LimitResult(LimitCurve(args.mu95_obs, args.mu95_obs_status), tuple(expected))
        if limits.observed.value is None:
            raise ValueError("observed limit is missing; no tested-point verdict can be plotted")
    except (ValueError, TypeError, OSError) as exc:
        ap.error(str(exc))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    hep = house.apply_style(args.experiment)

    contours = parse_contour_args(args.contour)
    raw = []
    for role, path in contours:
        if not os.path.exists(path):
            sys.exit(f"--contour file not found: {path}")
        x, y, xn, yn = read_contour(path)
        raw.append((role, path, x, y, xn, yn))

    def _is_dm(nm):
        return bool(nm) and ("delta" in nm.lower() or r"\Delta" in nm or "Δ" in nm)
    if args.plane == "dm":
        dm_plane = True
    elif args.plane == "mass":
        dm_plane = False
    else:  # auto: a compressed (Delta m) plane if either axis header says so
        dm_plane = any(_is_dm(xn) or _is_dm(yn) for *_, xn, yn in raw)

    # ---- resolve effective per-axis log state (docs/workflow/checklists/plot-guidelines.md: the
    #      published figure's scales are FACTS, not defaults). Precedence per axis:
    #      explicit --logx/--logy/--linx/--liny > the figure contract's DECLARED published axes
    #      (--figure-target, recorded at declaration off the extracted figure) > the per-plane
    #      auto default (dm plane = LOG Delta m, ~2 decades + published ATLAS compressed figures
    #      are log; mass-mass plane = LINEAR on both axes; regression-safe for C1N2).
    contract_axes = None
    if args.figure_target:
        from . import figure_target
        contract_axes = figure_target.read_axes(args.figure_target, figure_id=args.figure_id)
        if contract_axes:
            print(f"axes from figure contract: x={contract_axes.get('x')} "
                  f"y={contract_axes.get('y')} (source: {contract_axes.get('source')})")
        else:
            print("(figure contract declares no axes record -- per-plane auto default applies; "
                  "record the published scales with figure_target.py declare --axes-x/--axes-y)")

    def _axis_state(flag, declared, default):
        if flag is not None:
            return bool(flag)
        if declared in ("linear", "log"):
            return declared == "log"
        return default

    ca = contract_axes or {}
    log_x = _axis_state(args.logx, ca.get("x"), False)
    log_y = _axis_state(args.logy, ca.get("y"), dm_plane)

    # Orient every contour so x = the mass axis and y = Delta m, regardless of HEPData's
    # independent/dependent ordering (some records store Delta m as the independent variable).
    loaded = []
    xname = yname = None
    for role, path, x, y, xn, yn in raw:
        if dm_plane and _is_dm(xn) and not _is_dm(yn):
            x, y, xn, yn = y, x, yn, xn
        loaded.append((role, path, x, y))
        if xname is None:
            xname, yname = xn, yn

    try:
        mpar, mlsp = (float(v) for v in args.point.split(","))
    except ValueError:
        sys.exit("--point must be 'x,y' in GeV (mass plane 'm_parent,m_lsp'; dm plane 'm,Delta_m'), "
                 f"got {args.point!r}")

    fig, ax = plt.subplots(figsize=(8, 7))

    # ---- styles per role (headline obs solid / exp dashed; aux thin)
    role_style = {
        "observed":     dict(color="black", ls="-", lw=2.2, zorder=6,
                             label="Observed limit (95% CL)"),
        "expected":     dict(color=house.OKABE_ITO["blue"], ls="--", lw=2.0, zorder=5,
                             label="Expected limit (95% CL)"),
        "observed_aux": dict(color="0.45", ls="-", lw=1.0, zorder=3, label=None),
        "expected_aux": dict(color="0.45", ls=":", lw=1.0, zorder=3, label=None),
    }

    # collect data extent for auto axis limits
    all_x = [mpar]
    all_y = [mlsp]
    for _, _, x, y in loaded:
        all_x.extend(x.tolist())
        all_y.extend(y.tolist())

    # ---- optional synthesized expected +/-1sigma band (NOT shipped in HEPData for many records).
    # The band is in mu (signal-strength) space, not directly in the mass plane, so we cannot draw a
    # true mass band from a single nominal expected curve. We instead annotate the band honestly in the
    # text box and, if the caller passes the pyhf expected band, note it -- we do NOT fabricate a mass
    # contour band (that would be misleading). The expected CURVE is drawn from HEPData as-is.
    synth_band_note = None
    if args.exp_band_lo is not None and args.exp_band_hi is not None:
        synth_band_note = (rf"exp. $\mu_{{95}}$ band $[{args.exp_band_lo:.2f},"
                           rf"{args.exp_band_hi:.2f}]$ (pyhf $\pm1\sigma$)")

    # ---- draw contours (vertex order preserved -- a polyline, not y(x))
    legend_handles = []
    legend_labels = []
    seen_roles = set()
    for role, path, x, y in loaded:
        st = dict(role_style[role])
        lab = st.pop("label", None)
        ax.plot(x, y, **st)
        if lab and role not in seen_roles:
            legend_handles.append(Line2D([0], [0], color=st["color"], ls=st["ls"], lw=st["lw"]))
            legend_labels.append(lab)
            seen_roles.add(role)

    # ---- axis box. On a LOG axis the lower limit must be strictly positive (log(<=0) is undefined),
    #      so we floor it to the smallest published data value (a small margin below) rather than 0;
    #      this is exactly the compressed-Delta_m case (smallest published Delta m ~0.4 GeV).
    def _pos_min(vals):
        pos = [v for v in vals if v > 0]
        return min(pos) if pos else 1e-3

    if args.xlim:
        xlo, xhi = (float(v) for v in args.xlim.split(","))
    elif log_x:
        xmin = _pos_min(all_x)
        xlo = xmin / 1.15                       # one notch below the smallest positive x
        xhi = max(all_x) * 1.10
    else:
        xlo = max(0.0, min(all_x) - 0.08 * (max(all_x) - min(all_x)))
        xhi = max(all_x) + 0.08 * (max(all_x) - min(all_x))
    if args.ylim:
        ylo, yhi = (float(v) for v in args.ylim.split(","))
    elif log_y:
        ymin = _pos_min(all_y)
        ylo = ymin / 1.15                       # smallest published Delta m, not 0 (illegal on log)
        yhi = max(all_y) * 1.15
    else:
        ylo = 0.0
        yhi = max(all_y) + 0.12 * (max(all_y) - min(all_y))
    if log_x:
        ax.set_xscale("log")
    if log_y:
        ax.set_yscale("log")
    ax.set_xlim(xlo, xhi)
    ax.set_ylim(ylo, yhi)

    # ---- kinematically-forbidden region. Mass plane: m(LSP) > m(parent), above the y=x diagonal.
    #      dm plane: Delta m < 0 (below y=0) -- normally off-canvas (ylo=0), so nothing is shaded and
    #      NO diagonal is drawn (a y=x line is meaningless when y is a mass splitting, not a mass).
    if not dm_plane:
        diag = np.array([max(xlo, ylo), min(xhi, yhi)])
        ax.plot(diag, diag, color="0.55", ls="--", lw=1.0, zorder=2)
        xx = np.linspace(xlo, xhi, 200)
        ax.fill_between(xx, np.clip(xx, ylo, yhi), yhi, where=(xx <= yhi),
                        color="0.85", alpha=0.7, lw=0, zorder=1)
        xt = xlo + 0.30 * (xhi - xlo)
        if ylo <= xt <= yhi:
            ax.text(xt, xt, r"$m_{\mathrm{LSP}} = m_{\mathrm{parent}}$",
                    rotation=np.degrees(np.arctan2((yhi - ylo), (xhi - xlo))),
                    rotation_mode="anchor", ha="left", va="bottom", fontsize=10, color="0.4", zorder=2)

    # ---- tested point: green if excluded (obs mu95<1), red if allowed
    excluded = limits.observed.exclusion()
    pt_color = (house.OKABE_ITO["bluishgreen"] if excluded is True else
                house.OKABE_ITO["vermillion"] if excluded is False else "0.5")
    verdict = "excluded" if excluded is True else "not excluded" if excluded is False else "unresolved"
    ax.plot([mpar], [mlsp], marker="*", ms=20, mfc=pt_color, mec="black", mew=1.0,
            ls="none", zorder=10)
    legend_handles.append(Line2D([0], [0], marker="*", ms=14, mfc=pt_color, mec="black",
                                 ls="none"))
    legend_labels.append(f"{texify(args.model_label)}")

    # ---- axis titles with GeV units. In the dm plane, default to the contour's own axis headers
    #      (already TeX, with the correct physics) unless the caller overrode the labels.
    if dm_plane:
        xtex = texify(args.parent_label) if args.parent_label != "m(parent)" else texify(xname or "m(sparticle)")
        ytex = texify(args.lsp_label) if args.lsp_label != "m(LSP)" else texify(yname or r"$\Delta m$")
    else:
        xtex = texify(args.parent_label)
        ytex = texify(args.lsp_label)
    ax.set_xlabel(f"{xtex} [GeV]")
    ax.set_ylabel(f"{ytex} [GeV]")

    # ---- experiment header (bold-italic label + sqrt(s) + L); 95% CL, NOT discovery
    if hep is not None:
        explabel = getattr(hep, args.experiment.lower()).label
        try:
            explabel(ax=ax, data=True, text="", lumi=args.lumi, com=args.com)
        except TypeError:
            explabel(ax=ax, data=True, label="", lumi=args.lumi, com=args.com)

    # ---- annotation box: analysis id, mu95 verdict (honest about LO/NLO being the caller's choice),
    #      the synthesized-band note, and the explicit "95% CL exclusion, not discovery" line.
    lines = [
        rf"$\mathbf{{{args.analysis.replace('_', chr(92)+'_')}}}$",
        (rf"tested point $(m={mpar:.0f},\ \Delta m={mlsp:.0f})$ GeV" if dm_plane
         else f"tested point $({mpar:.0f},{mlsp:.0f})$ GeV"),
        f"obs. mu95 {args.mu95_obs:.2f} ({limits.observed.status})",
        (f"exp. mu95 {args.mu95_exp:.2f} ({limits.expected[2].status})" if args.mu95_exp is not None else "expected limit missing"),
        f"Point {verdict} under this upper-limit test",
    ]
    if synth_band_note:
        lines.append(synth_band_note)
    lines.append("95% CL exclusion (CLs), not a discovery")
    # anchor the box in the lower-right empty corner so it never sits on the tested-point marker
    # (which is interior) nor on the legend (top); ha=right keeps it off the right spine.
    ax.text(0.965, 0.035, "\n".join(lines), transform=ax.transAxes, ha="right", va="bottom",
            fontsize=10.5, linespacing=1.45,
            bbox=dict(boxstyle="round,pad=0.5", fc="white", ec="0.6", alpha=0.9), zorder=11)

    # ---- legend: collision-aware placement from the house module. A mass-plane exclusion contour can
    #      fill the TOP of the frame (especially the log-Delta_m dm plane, where the contour spans the
    #      decades), so we offer the scorer LOWER corners too and let it pick the genuinely emptiest
    #      one -- the colleague's point: the legend must never sit on the contour or the tested point.
    #      The annotation box owns 'lower right' (reserved) and the ATLAS label owns 'upper left'.
    # candidate boxes are matplotlib loc strings -> their axes-fraction extent. We include the MID
    # corners ('center left'/'center right'/'lower center') because an exclusion contour often leaves
    # an empty pocket mid-frame (the open mouth of a 'C'-shaped compressed-plane contour) while filling
    # all four true corners. The scorer picks the emptiest; 'lower right' is reserved for the box.
    legend_cands = {
        "upper right":   (0.58, 1.00, 0.62, 1.00),
        "center left":   (0.00, 0.40, 0.36, 0.64),
        "center right":  (0.60, 1.00, 0.36, 0.64),
        "lower left":    (0.00, 0.40, 0.00, 0.38),
        "lower center":  (0.32, 0.68, 0.00, 0.38),
        "upper left":    (0.00, 0.42, 0.62, 1.00),
        "upper center":  (0.30, 0.70, 0.62, 1.00),
    }
    house.smart_legend(ax, handles=legend_handles, labels=legend_labels, fontsize=11.5,
                       candidates=legend_cands, reserved_corners=("lower right",))

    # ---- four-side inward ticks (mplhep style already does this) + tick-density hygiene.
    #      Pass the resolved log state so a LOG axis gets decade LogLocator ticks (the dm-plane
    #      Delta m axis), while a linear axis keeps the MaxNLocator density control.
    house.tick_hygiene(ax, axr=None, logy=log_y, logx=log_x)

    # ---- export BOTH .pdf (vector, Type-42) and .png
    house.enforce_lint(fig, where=os.path.basename(args.out), allow=args.no_lint)   # CR-016 gate
    stem = args.out
    for ext in (".pdf", ".png"):
        p = stem if stem.endswith(ext) else (stem.rsplit(".", 1)[0] if "." in os.path.basename(stem)
                                             else stem) + ext
        os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
        fig.savefig(p, dpi=200, bbox_inches="tight")
        print(f"wrote {p}")
    print(f"mass plane: {args.experiment} house style; plane={'dm' if dm_plane else 'mass'}; "
          f"x-scale={'log' if log_x else 'linear'} y-scale={'log' if log_y else 'linear'}; "
          f"point ({mpar:.0f},{mlsp:.0f}) -> {verdict} (obs mu95={args.mu95_obs:.3f}); "
          f"{len(loaded)} contour(s); axes x='{xname}' y='{yname}'")


if __name__ == "__main__":
    main()
