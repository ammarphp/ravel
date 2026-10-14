#!/usr/bin/env python
"""plot_lint -- the MACHINE GATE behind docs/workflow/checklists/plot-criteria.md.

The gate itself lives in mplhep_style.lint_figure/enforce_lint and runs INSIDE every renderer at
save time (a saved PNG cannot be linted post-hoc -- the check needs the live artists). Renderers
wired in: scan_contour.py (fail-loud, --no-lint to downgrade), overlay_on_data.py,
mass_plane_overlay.py. This CLI exists for two things:

  plot_lint.py --selftest     build a deliberately colliding figure (expect violations) and a
                              clean smart_legend+smart_annotate figure (expect none); exit 0
                              only if BOTH behave. Run under the rivet env:
                              $CONDA run -n rivet python src/ravel/validation/plot_lint.py --selftest

What it checks (mplhep_style.lint_figure docstring is authoritative): legend/boxed-annotation
occlusion of drawn data (fills exempt; bare in-plot feature labels exempt), box-box overlap,
successive tick-label overlap, boxes escaping the canvas.

A requested plot style is a typed constraint, ``figure_spec`` (WALKTHROUGH Δ-Wa4, SG-25):
axis ranges, scales, aspect, binning and label text. ``figure_spec_errors`` checks the spec
itself and ``lint_figure_spec`` checks a live figure against it; a renderer that was given a
spec runs both before saving, beside ``lint_figure``.
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.validation"

import math
import sys

FIGURE_SPEC_KEYS = ("x_range", "y_range", "x_scale", "y_scale", "aspect", "binning", "x_label", "y_label",
                    "title", "axes")
SCALES = ("linear", "log", "symlog", "logit")


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def figure_spec_errors(spec):
    """Structural errors in a figure_spec; [] when every stated constraint is well formed."""
    if not isinstance(spec, dict):
        return ["a figure_spec is an object"]
    errors = [f"unknown figure_spec field {k!r}" for k in sorted(set(spec) - set(FIGURE_SPEC_KEYS))]
    for key in ("x_range", "y_range"):
        if key in spec:
            pair = spec[key]
            if not (isinstance(pair, list) and len(pair) == 2 and all(_finite(v) for v in pair) and pair[0] < pair[1]):
                errors.append(f"{key} is [low, high] with finite low < high")
    for key in ("x_scale", "y_scale"):
        if key in spec and spec[key] not in SCALES:
            errors.append(f"{key} is one of {SCALES}")
    if "aspect" in spec and not (spec["aspect"] in ("auto", "equal") or (_finite(spec["aspect"]) and spec["aspect"] > 0)):
        errors.append("aspect is auto, equal or a positive number")
    if "binning" in spec:
        edges = spec["binning"]
        if not (isinstance(edges, list) and len(edges) >= 2 and all(_finite(e) for e in edges)
                and all(a < b for a, b in zip(edges, edges[1:]))):
            errors.append("binning is a list of at least two strictly increasing edges")
    for key in ("x_label", "y_label", "title"):
        if key in spec and not (isinstance(spec[key], str) and spec[key].strip()):
            errors.append(f"{key} is nonempty text the rendered label must contain")
    if "axes" in spec and not (type(spec["axes"]) is int and spec["axes"] >= 0):
        errors.append("axes is the index of the constrained axes")
    return errors


def _close(a, b, rel_tol):
    return math.isclose(a, b, rel_tol=rel_tol, abs_tol=rel_tol * max(1.0, abs(a), abs(b)))


def _drawn_edges(ax):
    """Bin edges of the histogram artists on ``ax``: step patches and bar containers."""
    found = []
    for patch in ax.patches:
        data = getattr(patch, "get_data", None)
        if callable(data):
            edges = getattr(data(), "edges", None)
            if edges is not None:
                found.append([float(e) for e in edges])
    for container in ax.containers:
        rects = [r for r in container if hasattr(r, "get_x") and hasattr(r, "get_width")]
        if rects and len(rects) == len(container):
            lows = sorted((r.get_x(), r.get_x() + r.get_width()) for r in rects)
            found.append([lows[0][0]] + [high for _, high in lows])
    return found


def lint_figure_spec(fig, spec, rel_tol=1e-6):
    """Violations of a figure_spec by a live figure; empty means the figure meets every stated constraint."""
    errors = figure_spec_errors(spec)
    if errors:
        return [f"figure_spec: {e}" for e in errors]
    index = spec.get("axes", 0)
    if index >= len(fig.axes):
        return [f"figure_spec names axes {index}; the figure has {len(fig.axes)}"]
    ax = fig.axes[index]
    viols = []
    for key, getter in (("x_range", ax.get_xlim), ("y_range", ax.get_ylim)):
        if key in spec:
            drawn = sorted(getter())
            if not all(_close(a, b, rel_tol) for a, b in zip(drawn, spec[key])):
                viols.append(f"{key}: drawn {drawn}, requested {spec[key]}")
    for key, getter in (("x_scale", ax.get_xscale), ("y_scale", ax.get_yscale)):
        if key in spec and getter() != spec[key]:
            viols.append(f"{key}: drawn {getter()}, requested {spec[key]}")
    if "aspect" in spec:
        drawn = ax.get_aspect()
        wanted = 1.0 if spec["aspect"] == "equal" else spec["aspect"]
        if (drawn == "auto") != (wanted == "auto") or (wanted != "auto" and not _close(float(drawn), wanted, rel_tol)):
            viols.append(f"aspect: drawn {drawn}, requested {spec['aspect']}")
    if "binning" in spec:
        drawn = _drawn_edges(ax)
        if not any(len(e) == len(spec["binning"]) and all(_close(a, b, rel_tol) for a, b in zip(e, spec["binning"]))
                   for e in drawn):
            viols.append(f"binning: no histogram drawn with the requested edges {spec['binning']}"
                         + (f" (drawn {drawn})" if drawn else " (no histogram drawn)"))
    for key, text in (("x_label", ax.get_xlabel()), ("y_label", ax.get_ylabel()), ("title", ax.get_title())):
        if key in spec and spec[key].strip() not in text:
            viols.append(f"{key}: drawn {text!r} does not contain {spec[key]!r}")
    return viols


def _selftest():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from ravel.plotting import mplhep_style as house

    failures = []

    # 1) DELIBERATE COLLISION: a curve through the upper-right corner + a raw legend and a raw
    #    boxed annotation forced onto it -> the lint MUST object (both occlusion and overlap).
    fig, ax = plt.subplots(figsize=(6, 4))
    x = np.linspace(0, 1, 300)
    ax.plot(x, 0.55 + 0.42 * x, label="climbing curve", lw=2)
    ax.legend(loc="upper right", fontsize=10)
    ax.text(0.97, 0.97, "boxed note\nover the data", transform=ax.transAxes, ha="right",
            va="top", fontsize=10, bbox=dict(boxstyle="round,pad=0.5", fc="white", ec="0.6"))
    viols = house.lint_figure(fig)
    if not viols:
        failures.append("colliding figure produced ZERO violations (gate is blind)")
    else:
        print(f"[selftest] colliding figure: {len(viols)} violation(s) as expected:")
        for v in viols:
            print(f"           - {v}")
    plt.close(fig)

    # 2) CLEAN: same data through the house helpers -> the lint MUST pass.
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(x, 0.55 + 0.42 * x, label="climbing curve", lw=2)
    house.smart_legend(ax, fontsize=10, reserve_label_corner=False)
    house.smart_annotate(ax, ["boxed note", "placed by the scorer"], fontsize=10)
    viols = house.lint_figure(fig)
    if viols:
        failures.append("house-helper figure FAILED the lint: " + "; ".join(viols))
    else:
        print("[selftest] house-helper figure: clean, as expected")
    plt.close(fig)

    if failures:
        for f in failures:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("plot_lint selftest: PASS (gate objects to collisions, passes house placement)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
    sys.exit(0)
