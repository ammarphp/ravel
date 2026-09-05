"""Sparse rendered segments must count even when every source vertex misses a box."""
import importlib.util
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "trial-runs/_infrastructure/mplhep_style.py"
spec = importlib.util.spec_from_file_location("plot_lint_segment_style", SCRIPT)
house = importlib.util.module_from_spec(spec)
spec.loader.exec_module(house)


@pytest.fixture
def axes():
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.set(xlim=(0, 1), ylim=(0, 1))
    yield fig, ax
    plt.close(fig)


def centered_legend(ax):
    return ax.legend(loc="center", bbox_to_anchor=(0.5, 0.5), framealpha=0.85)


def legend_collisions(fig):
    return [v for v in house.lint_figure(fig) if "legend occludes" in v]


def test_sparse_line_crossing_legend_fails_with_no_vertices_inside(axes):
    fig, ax = axes
    line, = ax.plot([0.1, 0.9], [0.5, 0.5], label="sparse curve")
    legend = centered_legend(ax)
    fig.canvas.draw()
    rectangle = legend.get_window_extent(fig.canvas.get_renderer())
    assert not any(rectangle.contains(*p) for p in line.get_transform().transform(line.get_xydata()))
    assert legend_collisions(fig)
    with pytest.raises(SystemExit) as exc:
        house.enforce_lint(fig)
    assert exc.value.code == 4


def test_sparse_non_crossing_line_stays_clean(axes):
    fig, ax = axes
    ax.plot([0.1, 0.9], [0.1, 0.1], label="clear curve")
    centered_legend(ax)
    assert house.lint_figure(fig) == []


def test_segment_sampling_uses_line_transform_for_mixed_axes_data_coordinates(axes):
    fig, ax = axes
    ax.set_xlim(10, 20)
    ax.axhline(0.5, xmin=0.1, xmax=0.9, label="axes-fraction x")
    centered_legend(ax)
    assert legend_collisions(fig)


def test_log_axes_sample_the_rendered_segment_not_linear_data_spacing(axes):
    fig, ax = axes
    ax.set(xscale="log", yscale="log", xlim=(1, 1e12), ylim=(1, 1e12))
    ax.plot([1, 1e12], [1, 1e12], label="log curve")
    centered_legend(ax)
    assert legend_collisions(fig)
    assert np.isfinite(house._occupancy_points(ax)).all()


@pytest.mark.parametrize("gap", [np.nan, np.inf])
def test_nonfinite_gap_is_not_bridged_into_a_phantom_line(axes, gap):
    fig, ax = axes
    ax.plot([0.1, 0.2, gap, 0.8, 0.9], [0.5, 0.5, gap, 0.5, 0.5], label="disconnected")
    centered_legend(ax)
    assert not legend_collisions(fig)
    assert np.isfinite(house._occupancy_points(ax)).all()


def test_step_drawstyle_is_not_replaced_by_a_diagonal(axes):
    fig, ax = axes
    ax.plot([0.1, 0.9], [0.1, 0.9], drawstyle="steps-post", label="step curve")
    centered_legend(ax)
    assert not legend_collisions(fig)


@pytest.mark.parametrize("options", [{"linestyle": "none", "marker": "o"},
                                      {"visible": False}, {"alpha": 0}])
def test_undrawn_segments_do_not_create_collisions(axes, options):
    fig, ax = axes
    ax.plot([0.1, 0.9], [0.5, 0.5], label="no visible segment", **options)
    centered_legend(ax)
    assert not legend_collisions(fig)


def test_huge_off_axes_endpoints_are_clipped_before_bounded_sampling(axes):
    fig, ax = axes
    ax.plot([-1e8, 1e8], [0.5, 0.5], label="clipped crossing")
    centered_legend(ax)
    assert legend_collisions(fig)
    points = house._occupancy_points(ax)
    assert 4 < len(points) < 1000
    assert np.isfinite(points).all()
