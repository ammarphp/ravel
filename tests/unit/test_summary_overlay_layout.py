"""Fabricated layout witnesses, with the actual renderer and strict plot gate.

No actual P1 series, source intake, scientific authority or delivery is exercised.
"""
from copy import deepcopy
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pytest

from ravel.plotting import mplhep_style as house
from ravel.plotting import summary_overlay


def dense_manifest():
    masses = np.linspace(100, 700, 25).tolist()
    curves = []
    for index in range(3):
        values = (10 ** (np.sin(np.linspace(0, 3 * np.pi, 25) + index) + index * .3)).tolist()
        curves.append({
            "survey_id": f"fabricated-{index}",
            "source": f"Fabricated source {index}, explicit production and final state, full provenance label",
            "draw": "crosscheck" if index == 2 else "primary",
            "provenance": "digitized", "lumi_fb": 1 + index,
            "resolved": {"mass_gev": masses, "obs": values,
                         "exp": [None if i % 3 == 0 else v * 1.4 for i, v in enumerate(values)]},
        })
    return {"target_basis": {"quantity": "Fabricated upper limit [pb]", "model": "No physics claim"},
            "window_gev": [100, 700], "curves": curves,
            "coverage_gaps": [],
            "annotations": ["Fabricated dense curves test every inside legend corner.",
                            "Complete labels are retained; samples are not measured limits."]}


@pytest.mark.parametrize("logy", [True, False])
def test_dense_long_labels_outside_axes_pass_strict_gate(tmp_path, monkeypatch, logy):
    # Exercise the documented fallback even on systems which have mplhep.
    monkeypatch.setitem(sys.modules, "mplhep", None)
    manifest = dense_manifest()
    original = deepcopy(manifest)
    observed = {}
    real_gate = house.enforce_lint

    def inspect_and_gate(fig, **kwargs):
        assert kwargs["allow"] is False
        fig.canvas.draw()
        ax = fig.axes[0]
        renderer = fig.canvas.get_renderer()
        legend = ax.get_legend()
        extent = legend.get_window_extent(renderer)
        assert extent.x0 > ax.get_window_extent(renderer).x1
        assert [text.get_text() for text in legend.get_texts()] == ax.get_legend_handles_labels()[1]
        assert len(legend.get_texts()) == 6
        assert all("(digitized)" in text.get_text() for text in legend.get_texts())
        assert ax.get_xlim() == (100., 700.)
        # Source ordering and literal values/null gaps survive the layout change.
        for curve, observed_line, expected_line in zip(manifest["curves"], ax.lines[::2], ax.lines[1::2]):
            np.testing.assert_array_equal(observed_line.get_xdata(), curve["resolved"]["mass_gev"])
            np.testing.assert_array_equal(observed_line.get_ydata(), curve["resolved"]["obs"])
            np.testing.assert_array_equal(expected_line.get_ydata(),
                [np.nan if value is None else value for value in curve["resolved"]["exp"]])
        assert ax.lines[4].get_linestyle() == "--" and ax.lines[4].get_alpha() == .75
        observed["strict_gate"] = real_gate(fig, **kwargs)
        observed["legend_width"] = extent.width
        observed["tight_width"] = fig.get_tightbbox(renderer).width * fig.dpi

    monkeypatch.setattr(house, "enforce_lint", inspect_and_gate)
    result = summary_overlay.render_manifest(manifest, str(tmp_path / "synthetic"), experiment="CMS", com=17, lumi=7, logy=logy)
    assert observed["strict_gate"] == []
    assert observed["tight_width"] > observed["legend_width"]
    assert result["plot_lint"] == "passed" and len(result["series"]) == 6
    assert manifest == original
    assert (tmp_path / "synthetic.png").read_bytes().startswith(b"\x89PNG")
    assert (tmp_path / "synthetic.pdf").read_bytes().startswith(b"%PDF")


def test_inside_dense_legend_witness_still_refuses_and_retains_gate():
    # Held-out control proves the shared gate has not been loosened.
    fig, ax = plt.subplots()
    for index in range(12):
        ax.plot([0, 1], [index / 12, index / 12], label=f"Full fabricated source label {index}")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.legend(loc="center")
    try:
        assert any("legend occludes" in value for value in house.lint_figure(fig))
        with pytest.raises(SystemExit) as failure:
            house.enforce_lint(fig, allow=False)
        assert failure.value.code == 4
    finally:
        plt.close(fig)


def test_coverage_only_renderer_needs_no_empty_legend(tmp_path, monkeypatch):
    manifest = dense_manifest()
    manifest["curves"] = []
    manifest["coverage_gaps"] = [{"lo_gev": 100, "hi_gev": 700, "note": "Fabricated census has no retained curves"}]
    real_gate = house.enforce_lint
    observed = {}

    def inspect_and_gate(fig, **kwargs):
        observed["legend"] = fig.axes[0].get_legend()
        return real_gate(fig, **kwargs)

    monkeypatch.setattr(house, "enforce_lint", inspect_and_gate)
    result = summary_overlay.render_manifest(manifest, str(tmp_path / "coverage"), experiment="CMS", com=17, lumi=7)
    assert observed["legend"] is None
    assert result["series"] == [] and result["drawn_curves"] == 0
    assert result["plot_lint"] == "passed"
    assert (tmp_path / "coverage.png").stat().st_size > 0
