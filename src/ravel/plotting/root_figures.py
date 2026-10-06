#!/usr/bin/env python
"""Colleague-facing ROOT MIRROR of the two key reinterpretation figures (recast env, PyROOT).

mplhep is the PRIMARY publication renderer (overlay_on_data.py, mass_plane_overlay.py, the per-SR
overlay). This module is the ROOT-native MIRROR of two of those figures, drawn from the SAME source of
truth so colleagues who live in ROOT can re-plot, restyle, and open the .root canvas themselves:

  yields    -- the per-SR yield overlay (a COUNTING analysis has no differential distribution; the
               publishable figure is data points + SM-background band + signal+background across SRs).
               Source of truth: sr_yields.json (the {name,n,b,db,s} per-SR rows that the rest of the
               pipeline already trusts -- same numbers the mplhep per-SR overlay and pyhf consume).
  massplane -- the 95% CL exclusion contour in the m(parent)-m(LSP) plane (observed solid + expected
               dashed) with the tested point starred (green excluded / red allowed by obs mu95).
               Source of truth: the published HEPData YAML contour tables (data14=observed,
               data13=expected) -- exactly what mass_plane_overlay.py reads, read the SAME way
               (vertex order preserved; a boundary polyline is NEVER sorted by x).

Each subcommand writes three files from ONE TCanvas: STEM.pdf (vector, for a paper), STEM.png (quick
view), STEM.root (the live canvas a colleague can open in a ROOT session).

A minimal ATLAS-like TStyle is set inline (no external rootlogon): four-side INWARD ticks
(SetPadTickX/Y(1)), no stat box (SetOptStat(0)), no title box (SetOptTitle(0)), Helvetica-ish font
42/43, and a TLatex header "#bf{#it{ATLAS}}" + sqrt(s)+L. The exclusion figure carries the explicit
"95% CL exclusion (CLs), not a discovery" line. Colours are the Okabe-Ito hexes mirrored from
mplhep_style.py (signal = vermillion #D55E00) so a series is the same colour in both renderers.

Usage (anchors -- absolute paths shown for the report; docs use placeholders):
  root_figures.py yields    --srs <rundir>/outputs/sr_yields.json \
                            --analysis ATLAS_2016_I1458270 --com 13 --lumi 36.1 \
                            --out <rundir>/plots/named/ATLAS_2016_I1458270__sr-yields__root
  root_figures.py massplane --contour-obs <...>/data14.yaml --contour-exp <...>/data13.yaml \
                            --point 300,100 --mu95-obs 2.13 --mu95-exp 1.06 \
                            --analysis ATLAS_2018_I1676551 --com 13 --lumi 36.1 \
                            --parent-label 'm(#tilde{#chi}_{1}^{#pm}/#tilde{#chi}_{2}^{0})' \
                            --lsp-label 'm(#tilde{#chi}_{1}^{0})' \
                            --out <rundir>/plots/named/ATLAS_2018_I1676551__massplane__root

See docs/workflow/steps/05-visualize.md and .claude/rules/plots.md. Run in the `recast` env (ROOT 6.40).
"""

if not __package__:  # Direct file execution uses the same package implementation.
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.plotting"

import argparse
import json
import math
import os
import sys



from functools import lru_cache


@lru_cache(maxsize=1)
def _root():
    import ROOT
    return ROOT


def _reject_nonfinite(value, field, where):
    """sys.exit (clear, non-zero) if `value` is NaN/+-Inf -- a non-finite n/b/db/s silently paints a
    BLANK figure (ROOT skips the bad bin, the axis range collapses), so a physicist must never get one.
    Names the offending SR/field so the problem is obvious. Returns the value unchanged when finite."""
    if not math.isfinite(value):
        sys.exit(f"{where}: non-finite value {value!r} in field '{field}' -- refusing to draw a "
                 f"blank/garbled figure; fix the source so this value is a finite number")
    return value


def _safe_latex(text, where):
    """Validate a ROOT-TLatex label before it reaches TLatex/axis-title/legend. A malformed label
    (unbalanced braces/brackets, control chars) makes ROOT emit a garbled glyph string with only a
    stderr 'Error in <TLatex::PaintLatex1>' -- an authoritative-looking figure with a wrong label and
    exit 0. Reject it loudly instead, naming the option. Returns the text unchanged when well-formed."""
    if text is None:
        return None
    if any(ord(ch) < 0x20 for ch in text):
        sys.exit(f"{where}: label contains a control character -- refusing to pass it to TLatex "
                 f"(would render a garbled label); got {text!r}")
    # balanced {} and [] (the only TLatex grouping that, when unbalanced, ROOT renders wrong silently)
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        if text.count(open_ch) != text.count(close_ch):
            sys.exit(f"{where}: unbalanced '{open_ch}{close_ch}' in TLatex label {text!r} "
                     f"({text.count(open_ch)}x '{open_ch}' vs {text.count(close_ch)}x '{close_ch}') -- "
                     f"refusing to render a garbled label")
    return text


# ----------------------------------------------------------------- Okabe-Ito palette (mirrored from
# mplhep_style.OKABE_ITO so a series is the same colour in the ROOT mirror and the mplhep primary).
OKABE_ITO = {
    "orange":      "#E69F00",
    "skyblue":     "#56B4E9",
    "bluishgreen": "#009E73",
    "yellow":      "#F0E442",
    "blue":        "#0072B2",
    "vermillion":  "#D55E00",
    "redpurple":   "#CC79A7",
    "black":       "#000000",
}
SIGNAL_HEX = OKABE_ITO["vermillion"]   # the signal+background curve, every figure


def tcolor(hex_str):
    """A ROOT colour index for a #RRGGBB hex (TColor.GetColor handles the conversion + caching)."""
    return _root().TColor.GetColor(hex_str)


# ----------------------------------------------------------------- ATLAS-like TStyle (inline)
def atlas_style():
    """A minimal ATLAS-house TStyle set inline (no external rootlogon needed).

    Four-side inward ticks, no stat box, no title box, Helvetica-ish font 42 (and 43 for fixed-size
    text), tidy margins. Mirrors the mplhep ATLAS look + the mass_plane_overlay.py conventions.
    """
    st = _root().TStyle("ATLASmirror", "ATLAS-like house style (ROOT mirror)")
    # ticks on all four sides, pointing inward
    st.SetPadTickX(1)
    st.SetPadTickY(1)
    # no chartjunk
    st.SetOptStat(0)
    st.SetOptTitle(0)
    st.SetOptFit(0)
    # white canvas/pads, thin frame
    st.SetCanvasColor(0)
    st.SetPadColor(0)
    st.SetFrameFillColor(0)
    st.SetFrameBorderMode(0)
    st.SetCanvasBorderMode(0)
    st.SetPadBorderMode(0)
    st.SetLegendBorderSize(0)
    st.SetLegendFillColor(0)
    # Helvetica-ish: 42 = scalable Helvetica, 43 = Helvetica at a fixed pixel size
    for setter in ("SetTextFont", "SetLabelFont", "SetTitleFont", "SetLegendFont"):
        fn = getattr(st, setter, None)
        if fn is None:
            continue
        try:
            fn(42, "xyz")       # axis-scoped setters take an axis string
        except TypeError:
            fn(42)
    st.SetLabelSize(0.04, "xyz")
    st.SetTitleSize(0.045, "xyz")
    st.SetTitleOffset(1.2, "x")
    st.SetTitleOffset(1.4, "y")
    # generous margins so axis titles + the ATLAS header have room
    st.SetPadLeftMargin(0.14)
    st.SetPadBottomMargin(0.13)
    st.SetPadRightMargin(0.06)
    st.SetPadTopMargin(0.07)
    st.SetMarkerStyle(20)
    st.SetEndErrorSize(3)
    _root().g_root().SetStyle("ATLASmirror")
    _root().g_root().ForceStyle()
    return st


def atlas_header(com=None, lumi=None, x=0.16, y=0.88, extra=None):
    """Draw the bold-italic ATLAS label + sqrt(s)+L header (+ optional extra line). Returns the kept
    TLatex objects so the caller holds a reference (ROOT would GC them otherwise)."""
    keep = []
    lat = _root().TLatex()
    lat.SetNDC(True)
    lat.SetTextFont(42)
    lat.SetTextSize(0.045)
    lat.DrawLatex(x, y, "#bf{#it{ATLAS}}")
    keep.append(lat)
    parts = []
    if com is not None:
        # integers print clean (13 TeV, not 13.0 TeV)
        cs = f"{com:g}"
        parts.append(f"#sqrt{{s}} = {cs} TeV")
    if lumi is not None:
        parts.append(f"{lumi:g} fb^{{-1}}")
    if parts:
        sub = _root().TLatex()
        sub.SetNDC(True)
        sub.SetTextFont(42)
        sub.SetTextSize(0.034)
        sub.DrawLatex(x, y - 0.055, ", ".join(parts))
        keep.append(sub)
    if extra:
        ex = _root().TLatex()
        ex.SetNDC(True)
        ex.SetTextFont(42)
        ex.SetTextSize(0.030)
        ex.DrawLatex(x, y - 0.105, extra)
        keep.append(ex)
    return keep


def export_canvas(canvas, stem):
    """Write STEM.pdf + STEM.png + STEM.root from one TCanvas (strips any extension on STEM first)."""
    base = stem
    if "." in os.path.basename(base):
        base = base.rsplit(".", 1)[0]
    d = os.path.dirname(os.path.abspath(base))
    os.makedirs(d, exist_ok=True)
    written = []
    for ext in (".pdf", ".png"):
        p = base + ext
        canvas.SaveAs(p)
        written.append(p)
    rp = base + ".root"
    f = _root().TFile(rp, "RECREATE")
    canvas.Write()
    f.Close()
    written.append(rp)
    for p in written:
        print(f"wrote {p}")
    return written


# ----------------------------------------------------------------- HEPData contour I/O
# Mirrors mass_plane_overlay.read_contour EXACTLY: x = independent_variables[0].values (m parent),
# y = dependent_variables[0].values (m LSP). Vertex order is the boundary polyline -- NEVER sorted.
def read_contour(path):
    try:
        import yaml
        with open(path) as fh:
            doc = yaml.safe_load(fh)
    except ImportError:
        sys.exit("PyYAML not importable in this env; run root_figures.py in the `recast` env "
                 "(PyYAML 6.x confirmed there) or convert the contour to JSON first.")
    try:
        iv = doc["independent_variables"][0]
        dv = doc["dependent_variables"][0]
    except (KeyError, IndexError, TypeError) as e:
        sys.exit(f"contour {path}: not a HEPData contour table ({e})")
    x = [float(row["value"]) for row in iv["values"]]
    y = [float(row["value"]) for row in dv["values"]]
    if len(x) != len(y):
        sys.exit(f"contour {path}: x ({len(x)}) and y ({len(y)}) length mismatch")
    # a contour is a boundary polyline: a 0- or 1-vertex table cannot be drawn (TGraph with <1 point
    # errors, a single point gives a zero-extent axis) -- both silently yield a BLANK massplane.
    if len(x) < 2:
        sys.exit(f"contour {path}: only {len(x)} vertex/vertices -- need >=2 to draw a boundary "
                 f"polyline; refusing to write a blank mass plane")
    for arr, field in ((x, "m(parent)"), (y, "m(LSP)")):
        for v in arr:
            _reject_nonfinite(v, field, f"contour {path}")
    # a degenerate contour (all vertices share one x or one y) collapses an axis to zero width -- ROOT
    # then prints 'illegal axis coordinates range' and paints nothing. Require a real extent on both.
    if max(x) <= min(x) or max(y) <= min(y):
        sys.exit(f"contour {path}: degenerate extent (x in [{min(x)},{max(x)}], "
                 f"y in [{min(y)},{max(y)}]) -- need max>min on both axes; refusing a blank mass plane")
    xname = iv.get("header", {}).get("name", "m(parent) [GeV]")
    yname = dv.get("header", {}).get("name", "m(LSP) [GeV]")
    return x, y, xname, yname


# ================================================================= subcommand: per-SR yields
def cmd_yields(args):
    with open(args.srs) as fh:
        # parse_constant forbids the JSON extensions NaN/Infinity/-Infinity at parse time, so a
        # source emitting a literal NaN fails HERE (named) rather than silently painting a blank figure.
        def _bad_const(tok):
            sys.exit(f"{args.srs}: JSON contains the non-finite literal {tok!r} -- refusing to draw "
                     f"a blank/garbled figure; fix the source so every n/b/db/s is a finite number")
        rows = json.load(fh, parse_constant=_bad_const)
    if not isinstance(rows, list) or not rows:
        sys.exit(f"{args.srs}: expected a non-empty JSON list of per-SR dicts")
    names = [str(r["name"]) for r in rows]
    # finite-check every field (also catches a NaN/Inf that arrives already-parsed, e.g. via a float)
    n_obs = [_reject_nonfinite(float(r["n"]), "n", f"{args.srs} SR '{r['name']}'") for r in rows]
    bkg = [_reject_nonfinite(float(r["b"]), "b", f"{args.srs} SR '{r['name']}'") for r in rows]
    dbkg = [_reject_nonfinite(float(r["db"]), "db", f"{args.srs} SR '{r['name']}'") for r in rows]
    sig = [_reject_nonfinite(float(r["s"]), "s", f"{args.srs} SR '{r['name']}'") for r in rows]
    nsr = len(rows)

    # validate the only user-supplied TLatex label before it reaches the header (a malformed label
    # would otherwise render garbled with exit 0). The header's own "_"->"#lower[0.0]{_}" rewrite is
    # applied AFTER this, so it can never mask a user-supplied brace/bracket imbalance.
    _safe_latex(args.analysis, "--analysis")

    # ---- log-y needs >=1 strictly-positive value across the drawn content (bkg/data/signal). With
    #      none, ROOT's THStack PaintInit fails on the log pad and the later stack.GetXaxis() call
    #      SEGFAULTS on the unpainted stack. Decide the y-scale BEFORE SetLogy, never after a paint.
    positive = [v for v in (bkg + n_obs + sig) if v > 0]
    use_logy = bool(args.logy)
    if args.logy and not positive:
        if args.liny_fallback:
            print(f"warning: {args.srs} has no positive content -- falling back to a linear y axis "
                  f"(log-y is undefined)", file=sys.stderr)
            use_logy = False
        else:
            sys.exit(f"{args.srs}: no positive content for log-y (all of n/b/s are <=0) -- refusing "
                     f"to paint a blank/segfaulting figure; pass --liny for a linear axis if intended")

    atlas_style()
    c = _root().TCanvas("c_yields", "per-SR yields (ROOT mirror)", 900, 700)
    if use_logy:
        c.SetLogy(True)

    # ---- background as a TH1 with one bin per SR (SR names as bin labels). This is the THStack base
    #      (a single SM-total layer; if a per-process stack is ever passed, add layers here).
    h_bkg = _root().TH1F("h_bkg", "", nsr, 0.0, float(nsr))
    h_sig = _root().TH1F("h_sig", "", nsr, 0.0, float(nsr))   # signal stacked ON TOP of background
    for i in range(nsr):
        h_bkg.SetBinContent(i + 1, bkg[i])
        h_bkg.GetXaxis().SetBinLabel(i + 1, names[i])
        h_sig.SetBinContent(i + 1, sig[i])
        h_sig.GetXaxis().SetBinLabel(i + 1, names[i])
    h_bkg.SetFillColor(_root().TColor.GetColorTransparent(tcolor("#999999"), 0.85))
    h_bkg.SetLineColor(tcolor("#666666"))
    h_bkg.SetLineWidth(1)
    h_sig.SetFillColorAlpha(tcolor(SIGNAL_HEX), 0.55)
    h_sig.SetLineColor(tcolor(SIGNAL_HEX))
    h_sig.SetLineWidth(2)

    stack = _root().THStack("hs", "")
    stack.Add(h_bkg)        # SM background (bottom)
    stack.Add(h_sig)        # signal stacked on top => the top edge is signal+background

    # ---- background-uncertainty band: a hatched TH1 drawn with E2 over the background bins.
    h_band = _root().TH1F("h_band", "", nsr, 0.0, float(nsr))
    for i in range(nsr):
        h_band.SetBinContent(i + 1, bkg[i])
        h_band.SetBinError(i + 1, dbkg[i])
    h_band.SetFillColor(tcolor("#666666"))
    h_band.SetFillStyle(3354)        # hatched
    h_band.SetMarkerSize(0)
    h_band.SetLineWidth(0)

    # ---- observed data: black points with sqrt-N (Poisson-ish) error bars at bin centres.
    gx = _root().std.vector("double")()
    gy = _root().std.vector("double")()
    gex = _root().std.vector("double")()
    gey = _root().std.vector("double")()
    for i in range(nsr):
        gx.push_back(i + 0.5)
        gy.push_back(n_obs[i])
        gex.push_back(0.0)
        gey.push_back(n_obs[i] ** 0.5)
    g_data = _root().TGraphErrors(nsr, gx.data(), gy.data(), gex.data(), gey.data())
    g_data.SetMarkerStyle(20)
    g_data.SetMarkerSize(1.1)
    g_data.SetMarkerColor(_root().kBlack)
    g_data.SetLineColor(_root().kBlack)
    g_data.SetLineWidth(2)

    # ---- y-range: cover data+errors and signal+background, with headroom (log needs a positive floor).
    tops = [n_obs[i] + n_obs[i] ** 0.5 for i in range(nsr)] + \
           [bkg[i] + sig[i] for i in range(nsr)] + [bkg[i] + dbkg[i] for i in range(nsr)]
    ymax = max(tops)
    if use_logy:
        # `positive` is guaranteed non-empty here (use_logy is only True when it was)
        ymin = max(0.3, 0.5 * min(positive))
        ymax *= 3.0
    else:
        ymin = 0.0
        # all-zero content on a linear axis collapses the frame to [0,0]; give a unit ceiling so the
        # (empty) figure is still a readable axis rather than a blank degenerate range.
        ymax = ymax * 1.35 if ymax > 0 else 1.0

    # ---- draw: stack first (sets the frame + bin labels), then band, then data points on top.
    stack.Draw("HIST")
    stack.SetMinimum(ymin)
    stack.SetMaximum(ymax)
    stack.GetXaxis().SetTitle("Signal region")
    stack.GetYaxis().SetTitle("Events")
    stack.GetXaxis().SetLabelSize(0.045)
    stack.GetXaxis().LabelsOption("h")     # horizontal SR labels (readable, no rotation)
    h_band.Draw("E2 SAME")
    g_data.Draw("P SAME")
    _root().gPad.RedrawAxis()                  # ticks on top of the filled stack

    # ---- legend (top-right empty corner) + ATLAS header (top-left).
    leg = _root().TLegend(0.62, 0.70, 0.93, 0.92)
    leg.SetTextFont(42)
    leg.SetTextSize(0.032)
    leg.AddEntry(g_data, "Data", "pe")
    leg.AddEntry(h_bkg, "SM background", "f")
    leg.AddEntry(h_band, "Bkg. uncertainty", "f")
    leg.AddEntry(h_sig, "Signal + background", "f")
    leg.Draw()
    keep = atlas_header(com=args.com, lumi=args.lumi, x=0.17, y=0.89,
                        extra=args.analysis.replace("_", "#lower[0.0]{_}") if args.analysis else None)

    c.Update()
    written = export_canvas(c, args.out)
    print(f"per-SR yields (ROOT mirror): {nsr} SRs {names}; "
          f"signal stacked on SM background; data as black points (sqrt-N); "
          f"logy={use_logy}; source {args.srs}")
    return written


# ================================================================= subcommand: mass plane
def cmd_massplane(args):
    obs = read_contour(args.contour_obs)
    exp = read_contour(args.contour_exp) if args.contour_exp else None
    xo, yo, xname, yname = obs

    try:
        mpar, mlsp = (float(v) for v in args.point.split(","))
    except ValueError:
        sys.exit(f"--point must be 'm_parent,m_lsp' in GeV, got {args.point!r}")
    _reject_nonfinite(mpar, "m_parent", "--point")
    _reject_nonfinite(mlsp, "m_lsp", "--point")
    if not math.isfinite(args.mu95_obs):
        sys.exit(f"--mu95-obs must be finite, got {args.mu95_obs!r}")
    if args.mu95_exp is not None and not math.isfinite(args.mu95_exp):
        sys.exit(f"--mu95-exp must be finite, got {args.mu95_exp!r}")
    # validate every user-supplied TLatex label before it reaches an axis title / legend / header
    # (a malformed label otherwise renders garbled with exit 0).
    _safe_latex(args.parent_label, "--parent-label")
    _safe_latex(args.lsp_label, "--lsp-label")
    _safe_latex(args.model_label, "--model-label")
    _safe_latex(args.analysis, "--analysis")

    atlas_style()
    c = _root().TCanvas("c_massplane", "mass-plane exclusion (ROOT mirror)", 800, 750)

    # ---- axis frame from the data extent (+ headroom). y floor at 0.
    all_x = list(xo) + [mpar]
    all_y = list(yo) + [mlsp]
    if exp:
        all_x += list(exp[0])
        all_y += list(exp[1])
    if args.xlim:
        xlo, xhi = (float(v) for v in args.xlim.split(","))
    else:
        span = max(all_x) - min(all_x)
        xlo = max(0.0, min(all_x) - 0.08 * span)
        xhi = max(all_x) + 0.08 * span
    if args.ylim:
        ylo, yhi = (float(v) for v in args.ylim.split(","))
    else:
        ylo = 0.0
        yhi = max(all_y) + 0.12 * (max(all_y) - min(all_y))

    frame = c.DrawFrame(xlo, ylo, xhi, yhi)
    xtitle = args.parent_label if args.parent_label else (xname or "m(parent)")
    ytitle = args.lsp_label if args.lsp_label else (yname or "m(LSP)")
    frame.GetXaxis().SetTitle(f"{xtitle} [GeV]")
    frame.GetYaxis().SetTitle(f"{ytitle} [GeV]")
    frame.GetXaxis().SetTitleOffset(1.2)
    frame.GetYaxis().SetTitleOffset(1.5)

    keep = []   # hold references so ROOT does not GC the primitives

    # ---- kinematically-forbidden region m(LSP) > m(parent): shade above the y=x diagonal.
    d0 = max(xlo, ylo)
    d1 = min(xhi, yhi)
    if d1 > d0:
        # filled polygon for the forbidden triangle (clipped to the frame)
        poly = _root().TGraph(4)
        poly.SetPoint(0, d0, d0)
        poly.SetPoint(1, d1, d1)
        poly.SetPoint(2, xlo, yhi)
        poly.SetPoint(3, xlo, max(d0, ylo))
        poly.SetFillColorAlpha(_root().kGray, 0.45)
        poly.SetLineWidth(0)
        poly.Draw("F SAME")
        keep.append(poly)
        diag = _root().TLine(d0, d0, d1, d1)
        diag.SetLineColor(_root().kGray + 1)
        diag.SetLineStyle(2)
        diag.SetLineWidth(1)
        diag.Draw("SAME")
        keep.append(diag)
        dl = _root().TLatex()
        dl.SetTextFont(42)
        dl.SetTextSize(0.026)
        dl.SetTextColor(_root().kGray + 2)
        dl.SetTextAngle(45)
        xt = xlo + 0.32 * (xhi - xlo)
        if ylo <= xt <= yhi:
            dl.DrawLatex(xt, xt, "  m_{LSP} = m_{parent}")
        keep.append(dl)

    # ---- contours as TGraphs in VERTEX ORDER (a boundary polyline; NEVER sorted).
    def make_graph(x, y):
        vx = _root().std.vector("double")()
        vy = _root().std.vector("double")()
        for a, b in zip(x, y):
            vx.push_back(a)
            vy.push_back(b)
        return _root().TGraph(len(x), vx.data(), vy.data())

    g_obs = make_graph(xo, yo)
    g_obs.SetLineColor(_root().kBlack)
    g_obs.SetLineWidth(3)
    g_obs.SetLineStyle(1)              # observed = solid
    g_obs.Draw("L SAME")
    keep.append(g_obs)

    g_exp = None
    if exp:
        g_exp = make_graph(exp[0], exp[1])
        g_exp.SetLineColor(tcolor(OKABE_ITO["blue"]))
        g_exp.SetLineWidth(3)
        g_exp.SetLineStyle(2)         # expected = dashed
        g_exp.Draw("L SAME")
        keep.append(g_exp)

    # ---- tested point: a star, green if excluded (obs mu95 < 1) else red.
    excluded = args.mu95_obs < 1.0
    pt_hex = OKABE_ITO["bluishgreen"] if excluded else OKABE_ITO["vermillion"]
    verdict = "excluded" if excluded else "allowed"
    star = _root().TMarker(mpar, mlsp, 29)   # 29 = filled five-point star
    star.SetMarkerColor(tcolor(pt_hex))
    star.SetMarkerSize(2.6)
    star.Draw("SAME")
    keep.append(star)
    star_edge = _root().TMarker(mpar, mlsp, 30)   # 30 = open star, drawn over for a black outline
    star_edge.SetMarkerColor(_root().kBlack)
    star_edge.SetMarkerSize(2.6)
    star_edge.Draw("SAME")
    keep.append(star_edge)

    _root().gPad.RedrawAxis()

    # ---- legend (upper-right) + ATLAS header (upper-left).
    leg = _root().TLegend(0.55, 0.74, 0.93, 0.92)
    leg.SetTextFont(42)
    leg.SetTextSize(0.030)
    leg.AddEntry(g_obs, "Observed limit (95% CL)", "l")
    if g_exp:
        leg.AddEntry(g_exp, "Expected limit (95% CL)", "l")
    pt_label = args.model_label if args.model_label else f"tested ({mpar:g},{mlsp:g})"
    leg.AddEntry(star, pt_label, "p")
    leg.Draw()
    keep.append(leg)
    keep += atlas_header(com=args.com, lumi=args.lumi, x=0.17, y=0.89,
                         extra=args.analysis.replace("_", "#lower[0.0]{_}") if args.analysis else None)

    # ---- annotation box (lower-right): tested point, mu95 verdict, and the explicit 95%-CL line.
    #      Sits above the x-axis tick labels (y0=0.155) so the GeV labels never collide with the box.
    note = _root().TPaveText(0.50, 0.155, 0.93, 0.355, "NDC")
    note.SetFillColor(0)
    note.SetFillStyle(1001)
    note.SetBorderSize(1)
    note.SetTextFont(42)
    note.SetTextSize(0.027)
    note.SetTextAlign(12)
    note.AddText(f"tested point ({mpar:g}, {mlsp:g}) GeV")
    mu_line = f"obs. #mu_{{95}} = {args.mu95_obs:.2f}"
    if args.mu95_exp is not None:
        mu_line += f",  exp. #mu_{{95}} = {args.mu95_exp:.2f}"
    note.AddText(mu_line)
    note.AddText(f"#Rightarrow point {verdict} (#mu_{{95}} {'<' if excluded else '#geq'} 1)")
    note.AddText("95% CL exclusion (CLs), not a discovery")
    note.Draw()
    keep.append(note)

    c.Update()
    written = export_canvas(c, args.out)
    print(f"mass plane (ROOT mirror): point ({mpar:g},{mlsp:g}) -> {verdict} "
          f"(obs mu95={args.mu95_obs:.3f}); obs contour {len(xo)} vertices"
          + (f", exp contour {len(exp[0])} vertices" if exp else "")
          + f"; axes x='{xname}' y='{yname}' (vertex order preserved)")
    return written


# ================================================================= CLI
def main():
    _root().g_root().SetBatch(True)
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    py = sub.add_parser("yields", help="per-SR yield overlay from sr_yields.json")
    py.add_argument("--srs", required=True, help="sr_yields.json (list of {name,n,b,db,s})")
    py.add_argument("--analysis", default=None, help="analysis id for the header, e.g. ATLAS_2016_I1458270")
    py.add_argument("--com", type=float, default=13, help="sqrt(s) in TeV")
    py.add_argument("--lumi", type=float, default=None, help="integrated luminosity in fb^-1")
    py.add_argument("--logy", action="store_true", default=True, help="log y axis (default on)")
    py.add_argument("--liny", dest="logy", action="store_false", help="linear y axis")
    py.add_argument("--liny-fallback", action="store_true", default=False,
                    help="if log-y is requested but there is no positive content, fall back to a "
                         "linear axis (warn) instead of exiting non-zero")
    py.add_argument("--out", required=True, help="output STEM (writes .pdf, .png, .root)")
    py.set_defaults(func=cmd_yields)

    pm = sub.add_parser("massplane", help="exclusion contour in the (m_parent, m_LSP) plane")
    pm.add_argument("--contour-obs", required=True, help="observed-contour HEPData YAML (e.g. data14.yaml)")
    pm.add_argument("--contour-exp", default=None, help="expected-contour HEPData YAML (e.g. data13.yaml)")
    pm.add_argument("--point", required=True, metavar="m_parent,m_lsp", help="tested point, e.g. 300,100")
    pm.add_argument("--mu95-obs", type=float, required=True,
                    help="observed mu95 (verdict: <1 excluded => green star; >=1 allowed => red)")
    pm.add_argument("--mu95-exp", type=float, default=None, help="expected (median) mu95")
    pm.add_argument("--analysis", default=None, help="analysis id for the header")
    pm.add_argument("--com", type=float, default=13, help="sqrt(s) in TeV")
    pm.add_argument("--lumi", type=float, default=None, help="integrated luminosity in fb^-1")
    pm.add_argument("--parent-label", default=None, help="ROOT-TLatex label for the parent mass axis")
    pm.add_argument("--lsp-label", default=None, help="ROOT-TLatex label for the LSP mass axis")
    pm.add_argument("--model-label", default=None, help="legend label for the tested point")
    pm.add_argument("--xlim", default=None, help="x range 'lo,hi'; auto from contours if omitted")
    pm.add_argument("--ylim", default=None, help="y range 'lo,hi'; auto if omitted")
    pm.add_argument("--out", required=True, help="output STEM (writes .pdf, .png, .root)")
    pm.set_defaults(func=cmd_massplane)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
