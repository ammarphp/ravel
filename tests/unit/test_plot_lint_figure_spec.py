"""figure_spec: a requested plot style as a typed constraint that plot_lint checks on the rendered figure."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pytest

from ravel.validation import plot_lint

SPEC = {"x_range": [0, 300], "y_range": [0.1, 1000], "x_scale": "linear", "y_scale": "log",
        "binning": [0, 100, 200, 300], "x_label": "x_obs [GeV]", "y_label": "Events", "title": "Synthetic"}


@pytest.fixture
def figure():
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.stairs([500, 50, 5], [0, 100, 200, 300])
    ax.set(xlim=(0, 300), ylim=(0.1, 1000), yscale="log", xlabel="x_obs [GeV]", ylabel="Events / 100 GeV",
           title="Synthetic selection")
    yield fig, ax
    plt.close(fig)


def test_a_figure_that_meets_its_spec_passes(figure):
    fig, _ = figure
    assert plot_lint.figure_spec_errors(SPEC) == []
    assert plot_lint.lint_figure_spec(fig, SPEC) == []


@pytest.mark.parametrize("change,needle", [
    ({"x_range": [0, 250]}, "x_range"),
    ({"y_scale": "linear"}, "y_scale"),
    ({"binning": [0, 150, 300]}, "binning"),
    ({"x_label": "m_obs"}, "x_label"),
    ({"aspect": "equal"}, "aspect"),
    ({"axes": 3}, "names axes 3"),
])
def test_each_departure_from_the_spec_is_a_violation(figure, change, needle):
    fig, _ = figure
    viols = plot_lint.lint_figure_spec(fig, dict(SPEC, **change))
    assert viols and any(needle in v for v in viols), viols


def test_bar_histograms_count_as_binning(figure):
    fig, ax = figure
    ax.cla()
    ax.bar([0, 100, 200], [1, 2, 3], width=100, align="edge")
    assert plot_lint.lint_figure_spec(fig, {"binning": [0, 100, 200, 300]}) == []


@pytest.mark.parametrize("spec,needle", [
    ({"x_range": [5, 1]}, "x_range"), ({"y_scale": "cubic"}, "y_scale"), ({"binning": [1]}, "binning"),
    ({"x_label": ""}, "x_label"), ({"colour": "red"}, "unknown"), ({"aspect": -1}, "aspect"),
])
def test_malformed_specs_are_refused(figure, spec, needle):
    assert any(needle in e for e in plot_lint.figure_spec_errors(spec))
    assert plot_lint.lint_figure_spec(figure[0], spec)[0].startswith("figure_spec:")
