#!/usr/bin/env python
"""Shared house style for pipeline figures (one place, so every figure looks the same).

Used by overlay_on_data.py and plot_simpleanalysis.py. Centralizes:
  - the mplhep ATLAS/CMS style (Helvetica / TeX-Gyre-Heros, four-side inward ticks) with a graceful
    fallback if mplhep is absent (warn, keep going -- a figure beats a crash);
  - TrueType font embedding for vector output (pdf.fonttype=42 / ps.fonttype=42, never Type-3);
  - the Okabe-Ito colourblind-safe palette + a consistent SM-process -> colour map (the same process
    gets the same colour in every figure of every run);
  - tick hygiene (density control on linear and log axes; ratio-panel x kept in lockstep with the
    main panel via sharex + a single MaxNLocator; offset/exponent text kept off the axis title);
  - deterministic collision-aware legend placement (occupancy count in candidate corners; ties break
    to 'upper right'; the mplhep experiment-label corner is penalized so the legend never sits on it).

Import idiom for sibling scripts (they are run by path, not as a package):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mplhep_style as house
"""
import sys
import numpy as np

# ---------------------------------------------------------------- palette
# Okabe & Ito (2008) colourblind-safe palette.
OKABE_ITO = {
    "orange":        "#E69F00",
    "skyblue":       "#56B4E9",
    "bluishgreen":   "#009E73",
    "yellow":        "#F0E442",
    "blue":          "#0072B2",
    "vermillion":    "#D55E00",
    "redpurple":     "#CC79A7",
    "black":         "#000000",
}
# Stable SM-process -> colour mapping (keys matched case/punctuation-insensitively).
PROCESS_COLORS = {
    "wjets":     OKABE_ITO["skyblue"],
    "w+jets":    OKABE_ITO["skyblue"],
    "zjets":     OKABE_ITO["blue"],
    "z+jets":    OKABE_ITO["blue"],
    "ttbar":     OKABE_ITO["orange"],
    "top":       OKABE_ITO["orange"],
    "singletop": OKABE_ITO["yellow"],
    "diboson":   OKABE_ITO["bluishgreen"],
    "multijet":  OKABE_ITO["redpurple"],
    "qcd":       OKABE_ITO["redpurple"],
    "other":     "#999999",
}
# Cycle for processes not in the map (deterministic order).
STACK_CYCLE = [OKABE_ITO[k] for k in
               ("skyblue", "orange", "bluishgreen", "blue", "yellow", "redpurple", "vermillion")]

SIGNAL_COLOR = OKABE_ITO["vermillion"]   # the signal+background line, every figure


def process_color(label, fallback_index=0):
    """Consistent colour for a background process label; deterministic cycle otherwise."""
    key = "".join(ch for ch in label.lower() if ch.isalnum() or ch == "+")
    for k, c in PROCESS_COLORS.items():
        if k in key or key in k:
            return c
    return STACK_CYCLE[fallback_index % len(STACK_CYCLE)]


# ---------------------------------------------------------------- style
def apply_style(experiment="ATLAS"):
    """Apply the mplhep house style + TrueType embedding. Returns the mplhep module or None."""
    import matplotlib
    import matplotlib.pyplot as plt
    hep = None
    try:
        import mplhep as hep
        plt.style.use(getattr(hep.style, experiment))
    except Exception as e:  # missing mplhep must not kill the figure
        print(f"WARNING: mplhep style unavailable ({e}); falling back to matplotlib defaults",
              file=sys.stderr)
    # Embed TrueType (Type-42) fonts in PDF/PS -- journals reject Type-3.
    matplotlib.rcParams["pdf.fonttype"] = 42
    matplotlib.rcParams["ps.fonttype"] = 42
    matplotlib.rcParams["axes.formatter.use_mathtext"] = True
    return hep


# ---------------------------------------------------------------- ticks
def tick_hygiene(ax, axr=None, logy=False, logx=False, x_nbins=7, ratio_nbins=4):
    """Tick-density + offset hygiene for a main panel (+ optional ratio panel sharing x).

    - x (linear): one MaxNLocator drives both panels (sharex keeps them aligned; the locator keeps
      the labels sparse enough not to overlap); minor ticks on.
    - log-x: LogLocator capped by the spanned decades (so decade labels never crowd), minor ticks at
      2..9 unlabelled; the axis title still names the variable + units, never log(variable) (the
      caller owns the title text). A log x-axis with a shared ratio panel is rare for these figures,
      so the log-x branch is applied to the bottom axis (main or ratio) directly.
    - log-y: LogLocator with numticks capped by the spanned decades, so labels never crowd;
      minor ticks at 2..9 with no labels.
    - linear-y: MaxNLocator; ratio panel prunes its top label so it cannot collide with the
      main panel's bottom label.
    - offset/exponent text: disabled on x (axis values are physical, e.g. GeV -- an offset would
      detach the numbers from the axis title); y offset text, if any, drawn small and clear of
      the axis title.
    """
    from matplotlib.ticker import (MaxNLocator, LogLocator, NullFormatter, ScalarFormatter)

    bottom = axr if axr is not None else ax
    if logx:
        lo, hi = ax.get_xlim()
        decades = max(1, int(np.ceil(np.log10(max(hi, 1e-300) / max(lo, 1e-300)))))
        bottom.xaxis.set_major_locator(LogLocator(base=10, numticks=min(decades + 2, 10)))
        bottom.xaxis.set_minor_locator(LogLocator(base=10, subs=tuple(np.arange(2, 10) * 0.1),
                                                  numticks=100))
        bottom.xaxis.set_minor_formatter(NullFormatter())
    else:
        bottom.xaxis.set_major_locator(MaxNLocator(nbins=x_nbins, steps=[1, 2, 2.5, 5, 10],
                                                   min_n_ticks=4))
        sf = ScalarFormatter(useMathText=True)
        sf.set_useOffset(False)              # never an 'x10^3 + offset' on a GeV axis
        bottom.xaxis.set_major_formatter(sf)

    if logy:
        lo, hi = ax.get_ylim()
        decades = max(1, int(np.ceil(np.log10(hi / max(lo, 1e-300)))))
        ax.yaxis.set_major_locator(LogLocator(base=10, numticks=min(decades + 2, 10)))
        ax.yaxis.set_minor_locator(LogLocator(base=10, subs=tuple(np.arange(2, 10) * 0.1),
                                              numticks=100))
        ax.yaxis.set_minor_formatter(NullFormatter())
    else:
        ax.yaxis.set_major_locator(MaxNLocator(nbins=6))

    if axr is not None:
        axr.yaxis.set_major_locator(MaxNLocator(nbins=ratio_nbins, prune="upper"))
        # keep panel separation honest: no x labels on the main panel (sharex usually does this)
        for lab in ax.get_xticklabels():
            lab.set_visible(False)

    # keep any y offset text small and away from the ylabel
    ot = ax.yaxis.get_offset_text()
    ot.set_size("small")
    ot.set_x(-0.06)


# ---------------------------------------------------------------- legend
def smart_legend(ax, handles=None, labels=None, fontsize=12, reserve_label_corner=True,
                 candidates=None, reserved_corners=("lower right",), **kw):
    """Deterministic collision-aware legend.

    Counts drawn-data occupancy (lines, collections, bar/stairs patches, in axes fraction) inside
    candidate boxes and picks the least occupied; ties break in candidate-dict order. The default
    candidate set is the three TOP corners -- upper right / upper left / upper center -- which suits a
    distribution overlay (data rises from the bottom, so the legend belongs at the top). A caller whose
    data can fill the top (e.g. a mass-plane exclusion contour that spans the whole frame) passes its
    own `candidates` dict including LOWER corners so the scorer can pick a genuinely empty corner; pass
    `reserved_corners` for corners another artist already owns (e.g. the mass-plane annotation box in
    'lower right'), which are penalized like the label corner. The upper-LEFT corner is penalized when
    an mplhep experiment label lives there (reserve_label_corner). After placement the legend's
    *measured* bbox is compared against every text artist on the axes (the ATLAS/CMS label + lumi
    header live there); on overlap the legend is re-anchored just below the offending text. framealpha
    keeps any residual underlap readable. Everything is deterministic (no randomized 'best').
    """
    cand = candidates if candidates is not None else {
        "upper right":  (0.58, 1.00, 0.55, 1.00),
        "upper left":   (0.00, 0.42, 0.55, 1.00),
        "upper center": (0.30, 0.70, 0.55, 1.00),
    }
    pts = _occupancy_points(ax)
    scores = {}
    for loc, (x0, x1, y0, y1) in cand.items():
        inside = ((pts[:, 0] >= x0) & (pts[:, 0] <= x1) &
                  (pts[:, 1] >= y0) & (pts[:, 1] <= y1)).sum() if len(pts) else 0
        if loc == "upper left" and reserve_label_corner:
            inside += max(10, int(0.1 * len(pts)))    # the ATLAS/CMS label owns this corner
        if loc in reserved_corners:
            inside += max(10, int(0.1 * len(pts)))    # a caller-owned artist (e.g. annotation box)
        scores[loc] = inside
    best = min(cand, key=lambda l: (scores[l], list(cand).index(l)))
    args = []
    if handles is not None and labels is not None:
        args = [handles, labels]
    kw.setdefault("frameon", True)        # mplhep styles default to frameless; the soft white
    kw.setdefault("framealpha", 0.85)     # frame keeps legend glyphs unambiguous over the canvas
    kw.setdefault("fancybox", False)
    kw.setdefault("edgecolor", "none")
    leg = ax.legend(*args, loc=best, fontsize=fontsize, **kw)

    # measured collision check against the axes' text artists (experiment label, lumi header, ...)
    try:
        fig = ax.figure

        def _colliding_ymins(legend):
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            lb = legend.get_window_extent(renderer)
            texts = list(ax.texts) + [t for a in fig.axes for t in a.texts if a is not ax]
            ymins = []
            for t in texts:
                if not t.get_text():
                    continue
                tb = t.get_window_extent(renderer)
                if (lb.x0 < tb.x1 and lb.x1 > tb.x0 and lb.y0 < tb.y1 and lb.y1 > tb.y0):
                    ymins.append(tb.y0)
            return ymins

        # 1) prefer shrinking the font (keeps the legend at the top, clear of the data)
        ymins = _colliding_ymins(leg)
        for fs in (fontsize - 1.5, fontsize - 3):
            if not ymins:
                break
            leg = ax.legend(*args, loc=best, fontsize=fs, **kw)
            ymins = _colliding_ymins(leg)
        # 2) last resort: drop the legend just below the lowest colliding text. Only meaningful for an
        #    UPPER corner (a lower-corner legend doesn't collide with the top ATLAS/lumi text); the
        #    x-anchor lookup defaults to the box centre for any non-upper corner so it never KeyErrors.
        if ymins:
            inv = ax.transAxes.inverted()
            y_anchor = inv.transform((0, min(ymins)))[1] - 0.02
            xa = {"upper right": 1.0, "upper left": 0.0, "upper center": 0.5}.get(best, 0.5)
            leg = ax.legend(*args, loc=best, fontsize=max(fontsize - 3, 8),
                            bbox_to_anchor=(xa, max(0.3, y_anchor)),
                            bbox_transform=ax.transAxes, **kw)
            fig.canvas.draw()
        # final honesty check: warn if the placed legend still sits on drawn data
        lb = leg.get_window_extent(fig.canvas.get_renderer())
        inv = ax.transAxes.inverted()
        (lx0, ly0), (lx1, ly1) = inv.transform(lb.get_points())
        pts = _occupancy_points(ax)
        n_in = int(((pts[:, 0] >= lx0) & (pts[:, 0] <= lx1) &
                    (pts[:, 1] >= ly0) & (pts[:, 1] <= ly1)).sum()) if len(pts) else 0
        if n_in > 3:
            print(f"WARNING: legend occludes ~{n_in} drawn-data samples "
                  f"(box x[{lx0:.2f},{lx1:.2f}] y[{ly0:.2f},{ly1:.2f}] axes-frac); "
                  f"shorten the label or move the legend", file=sys.stderr)
    except Exception as e:
        print(f"WARNING: legend collision check skipped ({e})", file=sys.stderr)
    return leg


def smart_annotate(ax, lines, fontsize=10, linespacing=1.4, candidates=None,
                   avoid_legend=True, **box_kw):
    """Occupancy-scored corner annotation box — the annotation-side smart_legend (CR-016).

    Places a (multi-line) annotation at the least-occupied of four inside corners: the box is
    drawn once to MEASURE its extent, every candidate anchor is scored by the drawn-data
    occupancy inside the would-be box (same sampler as smart_legend) plus a hard penalty for
    overlapping the already-placed legend or any existing text artist, and the box moves to the
    winner. Deterministic; ties break in candidate order. Callers that draw a legend must do so
    BEFORE calling this. `lines` is a list of strings (or one pre-joined string).
    """
    fig = ax.figure
    text = lines if isinstance(lines, str) else "\n".join(lines)
    cand = candidates or {
        "lower left":  (0.035, 0.035, "left",  "bottom"),
        "lower right": (0.965, 0.035, "right", "bottom"),
        "upper right": (0.965, 0.965, "right", "top"),
        "upper left":  (0.035, 0.965, "left",  "top"),
    }
    bk = dict(boxstyle="round,pad=0.5", fc="white", ec="0.6", alpha=0.9)
    bk.update(box_kw)
    cx0, cy0, ha0, va0 = next(iter(cand.values()))
    t = ax.text(cx0, cy0, text, transform=ax.transAxes, ha=ha0, va=va0,
                fontsize=fontsize, linespacing=linespacing, bbox=bk, zorder=6)
    try:
        fig.canvas.draw()
        rend = fig.canvas.get_renderer()
        ext = t.get_window_extent(rend)
        bp = t.get_bbox_patch()
        if bp is not None:                          # include the round-box padding
            try:
                ext = bp.get_window_extent(rend)
            except Exception:
                pass
        inv = ax.transAxes.inverted()
        (bx0, by0), (bx1, by1) = inv.transform(ext.get_points())
        w, h = bx1 - bx0, by1 - by0
        pts = _occupancy_points(ax)
        reserved = []                               # axes-fraction rectangles the box must not cover
        leg = ax.get_legend()
        if avoid_legend and leg is not None:
            (lx0, ly0), (lx1, ly1) = inv.transform(leg.get_window_extent(rend).get_points())
            reserved.append((lx0, ly0, lx1, ly1))
        for ot in ax.texts:
            if ot is t or not ot.get_text().strip():
                continue
            try:
                (ox0, oy0), (ox1, oy1) = inv.transform(ot.get_window_extent(rend).get_points())
                reserved.append((ox0, oy0, ox1, oy1))
            except Exception:
                pass
        scores = {}
        for name, (cx, cy, cha, cva) in cand.items():
            gx0 = cx if cha == "left" else cx - w
            gy0 = cy if cva == "bottom" else cy - h
            gx1, gy1 = gx0 + w, gy0 + h
            n = int(((pts[:, 0] >= gx0) & (pts[:, 0] <= gx1) &
                     (pts[:, 1] >= gy0) & (pts[:, 1] <= gy1)).sum()) if len(pts) else 0
            for (rx0, ry0, rx1, ry1) in reserved:
                if gx0 < rx1 and gx1 > rx0 and gy0 < ry1 and gy1 > ry0:
                    n += 10000                      # never sit on the legend / another label
            scores[name] = n
        best = min(cand, key=lambda k: (scores[k], list(cand).index(k)))
        if scores[best] > 3:
            # NO inside corner is clean (full-plane data, e.g. a whole-grid scatter): place the
            # box UNDER the axes in the caption position — occupancy lives in [0,1] axes
            # fraction, so a below-axes box occludes nothing by construction. bbox_inches=tight
            # at save time grows the canvas to include it.
            t.set_position((0.0, -0.16))
            t.set_horizontalalignment("left")
            t.set_verticalalignment("top")
            print(f"smart_annotate: every inside corner occluded (best {best}: "
                  f"~{scores[best] % 10000} samples) — placed below the axes as a caption",
                  file=sys.stderr)
        else:
            cx, cy, cha, cva = cand[best]
            t.set_position((cx, cy))
            t.set_horizontalalignment(cha)
            t.set_verticalalignment(cva)
    except Exception as e:
        print(f"WARNING: smart_annotate scoring skipped ({e})", file=sys.stderr)
    return t


def lint_figure(fig, tol_points=3, tol_box_overlap=0.10, saves_tight=True):
    """The plot-criteria MACHINE GATE (CAPABILITY-ROADMAP §7, CR-016): returns a list of
    violation strings, empty = clean. Renderers call this before saving and fail loud.

    Checks per axes: (a) the legend and every BOXED annotation (a text with a bbox patch)
    against drawn-DATA occupancy (curves, markers, scatter, error bars, unfilled contour lines;
    full-canvas FILLS such as pcolormesh/contourf are exempt — a framed box over a fill is
    legible and standard; BARE texts are exempt too: in-plot feature labels that sit on the line
    they name are conventional); (b) box↔box overlap (legend vs annotations vs labels, boxed or
    not); (c) successive tick-label overlap on each axis (the plot-criteria known defect);
    (d) boxes escaping the figure canvas — SKIPPED when `saves_tight` (the default: every house
    renderer saves with bbox_inches="tight", which grows the canvas around outside captions);
    pass saves_tight=False from any fixed-canvas saver to arm it.
    """
    viols = []
    try:
        fig.canvas.draw()
        rend = fig.canvas.get_renderer()
    except Exception as e:
        return [f"lint could not draw the figure: {e}"]
    fbox = fig.bbox
    for iax, ax in enumerate(fig.axes):
        pts = _occupancy_points(ax)
        inv = ax.transAxes.inverted()
        boxes = []                          # (label, x0, y0, x1, y1, window_extent, gated)
        leg = ax.get_legend()
        if leg is not None:
            try:
                we = leg.get_window_extent(rend)
                (x0, y0), (x1, y1) = inv.transform(we.get_points())
                boxes.append((f"ax{iax} legend", x0, y0, x1, y1, we, True))
            except Exception:
                pass
        for t in ax.texts:
            if not t.get_text().strip():
                continue
            try:
                bp = t.get_bbox_patch()
                we = bp.get_window_extent(rend) if bp is not None else t.get_window_extent(rend)
                (x0, y0), (x1, y1) = inv.transform(we.get_points())
                snippet = t.get_text().split("\n")[0][:28]
                boxes.append((f"ax{iax} text '{snippet}'", x0, y0, x1, y1, we, bp is not None))
            except Exception:
                pass
        for (name, x0, y0, x1, y1, _we, gated) in boxes:                # (a) boxed only
            if gated and len(pts):
                n = int(((pts[:, 0] >= x0) & (pts[:, 0] <= x1) &
                         (pts[:, 1] >= y0) & (pts[:, 1] <= y1)).sum())
                if n > tol_points:
                    viols.append(f"{name} occludes ~{n} drawn-data samples "
                                 f"(box x[{x0:.2f},{x1:.2f}] y[{y0:.2f},{y1:.2f}] axes-frac)")
        for a in range(len(boxes)):                                     # (b)
            for b in range(a + 1, len(boxes)):
                na, ax0, ay0, ax1, ay1, _, _ = boxes[a]
                nb, bx0, by0, bx1, by1, _, _ = boxes[b]
                ox = max(0.0, min(ax1, bx1) - max(ax0, bx0))
                oy = max(0.0, min(ay1, by1) - max(ay0, by0))
                if ox > 0 and oy > 0:
                    smaller = min((ax1 - ax0) * (ay1 - ay0), (bx1 - bx0) * (by1 - by0))
                    if smaller > 0 and (ox * oy) / smaller > tol_box_overlap:
                        viols.append(f"{na} overlaps {nb} "
                                     f"({100 * ox * oy / smaller:.0f}% of the smaller box)")
        for which, labels in (("x", ax.get_xticklabels()),              # (c)
                              ("y", ax.get_yticklabels())):
            exts = []
            for lab in labels:
                if not lab.get_visible() or not lab.get_text().strip():
                    continue
                try:
                    exts.append((lab.get_text(), lab.get_window_extent(rend)))
                except Exception:
                    pass
            for (t1, e1), (t2, e2) in zip(exts, exts[1:]):
                if e1.overlaps(e2):
                    ox = min(e1.x1, e2.x1) - max(e1.x0, e2.x0)
                    oy = min(e1.y1, e2.y1) - max(e1.y0, e2.y0)
                    if ox > 1.0 and oy > 1.0:                           # >1px each way, not kerning slack
                        viols.append(f"ax{iax} {which}-tick labels '{t1}'/'{t2}' overlap")
        if not saves_tight:                                             # (d)
            for (name, _x0, _y0, _x1, _y1, we, _g) in boxes:
                if (we.x0 < fbox.x0 - 1 or we.y0 < fbox.y0 - 1 or
                        we.x1 > fbox.x1 + 1 or we.y1 > fbox.y1 + 1):
                    viols.append(f"{name} extends beyond the figure canvas")
    return viols


def enforce_lint(fig, where="", allow=False):
    """Run lint_figure and FAIL LOUD (exit 4) on violations unless `allow` (--no-lint) is set.
    Returns the violation list either way so callers can log it."""
    viols = lint_figure(fig)
    for v in viols:
        print(f"PLOT-LINT {'WARN' if allow else 'FAIL'}{' [' + where + ']' if where else ''}: {v}",
              file=sys.stderr)
    if viols and not allow:
        print("plot-lint: figure violates workflow/checklists/plot-criteria.md; "
              "fix the layout or rerun with --no-lint to override (records a WARN).",
              file=sys.stderr)
        sys.exit(4)
    return viols


def _occupancy_points(ax):
    """Sample drawn artists in axes fractions, including sparse Line2D segments.

    Line paths are transformed before interpolation (log scales, steps, and mixed
    axes/data coordinates). Sampling is bounded to the visible rectangle and
    roughly 1% of the axes diagonal, rather than depending on data magnitudes.
    """
    pts = []
    trans = ax.transData
    to_axes = ax.transAxes.inverted()

    def add(xs, ys):
        xs = np.asarray(xs, float); ys = np.asarray(ys, float)
        ok = np.isfinite(xs) & np.isfinite(ys)
        if not ok.any():
            return
        xy = trans.transform(np.column_stack([xs[ok], ys[ok]]))
        pts.append(to_axes.transform(xy))

    from matplotlib.collections import LineCollection
    try:
        from matplotlib.contour import ContourSet
    except Exception:                              # very old matplotlib
        ContourSet = ()

    from matplotlib.path import Path
    from matplotlib.transforms import Bbox

    spacing = max(1.0, 0.01 * np.hypot(ax.bbox.width, ax.bbox.height))
    for ln in ax.lines:
        if not ln.get_visible() or ln.get_alpha() == 0:
            continue
        # Marker-only artists must not gain a fictitious connecting stroke.
        stroke = ln.get_linestyle().lower() not in ("none", "", " ") and ln.get_linewidth() > 0
        marker = ln.get_marker() not in ("None", "none", "", " ", None) and ln.get_markersize() > 0
        clip = ax.bbox if ln.get_clip_on() else ax.figure.bbox
        if ln.get_clip_on() and ln.get_clip_box() is not None:
            clip = Bbox.intersection(clip, ln.get_clip_box())
            if clip is None:
                continue
        if marker:
            xy = ln.get_transform().transform(ln.get_xydata())
            ok = (np.isfinite(xy).all(axis=1) & (xy[:, 0] >= clip.x0) & (xy[:, 0] <= clip.x1)
                  & (xy[:, 1] >= clip.y0) & (xy[:, 1] <= clip.y1))
            if ok.any():
                pts.append(to_axes.transform(xy[ok]))
        if not stroke:
            continue
        path = ln.get_transform().transform_path(ln.get_path())
        previous = first = None
        # iter_segments preserves MOVETO breaks at NaN/masked data; removing bad
        # vertices ourselves would incorrectly join separate finite subpaths.
        for vertices, code in path.iter_segments(remove_nans=True, clip=clip.extents,
                                                  simplify=False, curves=False):
            point = vertices[-2:] if code != Path.CLOSEPOLY else first
            if point is None or not np.isfinite(point).all():
                previous = None
                continue
            if code == Path.MOVETO:
                previous = first = point
                continue
            if previous is not None and code in (Path.LINETO, Path.CLOSEPOLY):
                count = min(257, max(2, int(np.ceil(np.hypot(*(point - previous)) / spacing)) + 1))
                xy = np.linspace(previous, point, count)
                pts.append(to_axes.transform(xy))
            previous = point
    for coll in ax.collections:
        got = False
        try:
            off = coll.get_offsets()
            if len(off):
                add(off[:, 0], off[:, 1])
                got = True
        except Exception:
            pass
        if got:
            continue
        # contour LINES occupy space a box must not cover; FILLS (contourf/pcolormesh) do not --
        # a framed box over a color fill is legible and standard (the lint exemption)
        line_like = isinstance(coll, LineCollection) or (
            ContourSet and isinstance(coll, ContourSet) and not getattr(coll, "filled", True))
        if line_like:
            try:
                for pth in coll.get_paths():
                    v = pth.vertices
                    if len(v):
                        step = max(1, len(v) // 200)
                        add(v[::step, 0], v[::step, 1])
            except Exception:
                pass
    for p in ax.patches:                       # bars / stairs / histogram patches
        if hasattr(p, "get_data"):             # StepPatch (ax.stairs): sample the step tops
            try:
                sd = p.get_data()
                vals = np.asarray(sd[0], float); edg = np.asarray(sd[1], float)
                add(0.5 * (edg[:-1] + edg[1:]), vals)
                continue
            except Exception:
                pass
        try:
            (x0, y0), (x1, y1) = p.get_bbox().get_points()
            add([0.5 * (x0 + x1)], [max(y0, y1)])
        except Exception:
            pass
    if not pts:
        return np.empty((0, 2))
    return np.vstack(pts)
