#!/usr/bin/env python
"""plot_lint -- the MACHINE GATE behind docs/workflow/checklists/plot-criteria.md (CR-016).

The gate itself lives in mplhep_style.lint_figure/enforce_lint and runs INSIDE every renderer at
save time (a saved PNG cannot be linted post-hoc -- the check needs the live artists). Renderers
wired tonight: scan_contour.py (fail-loud, --no-lint to downgrade), overlay_on_data.py,
mass_plane_overlay.py. This CLI exists for two things:

  plot_lint.py --selftest     build a deliberately colliding figure (expect violations) and a
                              clean smart_legend+smart_annotate figure (expect none); exit 0
                              only if BOTH behave. Run under the rivet env:
                              $CONDA run -n rivet python src/ravel/validation/plot_lint.py --selftest

What it checks (mplhep_style.lint_figure docstring is authoritative): legend/boxed-annotation
occlusion of drawn data (fills exempt; bare in-plot feature labels exempt), box-box overlap,
successive tick-label overlap, boxes escaping the canvas.
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.validation"

import sys


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
