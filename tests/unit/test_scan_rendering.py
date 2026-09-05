"""Regression counterexamples for scan labels, reference columns, and numeric support."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from ravel.plotting import scan_contour as renderer


def point(mass=100, dm=10, mu=2, **updates):
    return {"tag": f"m{mass}_dm{dm}", "m_parent": mass, "m_lsp": mass - dm,
            "dm": dm, "mu95_obs": mu, "mu95_exp": 3, "sigma_ref_fb": 5, **updates}


def scan(points=None):
    points = points if points is not None else [
        point(mass, dm) for mass in (100, 200) for dm in (10, 20)]
    return {"points": points, "n_done": len(points), "n_planned": len(points),
            "model_basis": {"basis": "fixture model cross section"}}


def reference(points=None, columns=None):
    points = points if points is not None else scan()["points"]
    columns = columns if columns is not None else [("Observed limit", 10)]
    return {"independent_variables": [
        {"header": {"name": "Parent mass", "units": "GeV"},
         "values": [{"value": p["m_parent"]} for p in points]},
        {"header": {"name": "Delta m", "units": "GeV"},
         "values": [{"value": p["dm"]} for p in points]}],
        "dependent_variables": [
            {"header": {"name": name, "units": "fb"},
             "values": [{"value": value} for _ in points]} for name, value in columns]}


def write_reference(tmp_path, doc):
    path = tmp_path / "reference.yaml"
    path.write_text(yaml.safe_dump(doc))
    return path


def write_scan(tmp_path, doc):
    path = tmp_path / "scan.json"
    path.write_text(json.dumps(doc))
    return path


@pytest.fixture
def plots(monkeypatch, tmp_path):
    """Keep real plotting and arithmetic; bypass only style placement and image I/O."""
    recorded = SimpleNamespace(saved=[], annotations=[], legends=[])
    monkeypatch.setattr(renderer, "setup", lambda args: (plt, None))
    monkeypatch.setattr(renderer, "save", lambda fig, stem: recorded.saved.append((fig, stem)))
    monkeypatch.setattr(renderer.house, "smart_annotate",
                        lambda ax, lines, **kwargs: recorded.annotations.extend(lines))

    def legend(ax, **kwargs):
        labels = kwargs.get("labels")
        if labels is None:
            labels = ax.get_legend_handles_labels()[1]
        recorded.legends.extend(labels)

    monkeypatch.setattr(renderer.house, "smart_legend", legend)
    recorded.args = SimpleNamespace(out=str(tmp_path / "plot"), logx=None, logy=None,
                                    contract_axes=None, experiment="ATLAS", lumi=139, com=13)
    yield recorded
    plt.close("all")


@pytest.mark.parametrize("kind", ["observed", "expected"])
def test_multiple_matching_limit_columns_are_not_silently_selected(tmp_path, kind):
    doc = reference(columns=[(f"{kind.title()} limit +1 sigma", 20),
                             (f"{kind.title()} limit", 10)])
    with pytest.raises(SystemExit, match="ambiguous"):
        renderer.read_limit_grid(write_reference(tmp_path, doc), kind=kind)


@pytest.mark.parametrize("field", ["mass", "splitting", "limit"])
def test_boolean_reference_values_are_not_cast_to_physics_numbers(tmp_path, field):
    doc = reference()
    column = (doc["dependent_variables"][0] if field == "limit" else
              doc["independent_variables"][0 if field == "mass" else 1])
    column["values"][0]["value"] = True
    with pytest.raises(SystemExit, match="boolean"):
        renderer.read_limit_grid(write_reference(tmp_path, doc))


@pytest.mark.parametrize("second_axis,second_value", [("Delta m", 110), ("LSP mass", -10)])
def test_reference_cannot_imply_a_negative_daughter_mass(tmp_path, second_axis, second_value):
    doc = reference(points=[point()])
    doc["independent_variables"][1]["header"]["name"] = second_axis
    doc["independent_variables"][1]["values"][0]["value"] = second_value
    with pytest.raises(SystemExit, match="negative daughter mass"):
        renderer.read_limit_grid(write_reference(tmp_path, doc))


@pytest.mark.parametrize("updates,reference_limit", [
    ({"mu95_obs": 1e308, "sigma_ref_fb": 1e308}, 10),
    ({"mu95_obs": 1e308, "sigma_ref_fb": 1}, 1e-308),
    ({"m_parent": float("nan")}, 10),
    ({"dm": float("inf")}, 10),
])
def test_invalid_numeric_records_retain_denominator_in_strict_json(updates, reference_limit):
    with np.errstate(over="ignore", invalid="ignore"):
        report = renderer.comparison_data({"points": [point(**updates)], "n_planned": 2},
                                          ([100], [10], [reference_limit]))
    assert report["counts"]["invalid_input"] == 1
    assert report["counts"]["matched"] == 0
    assert report["recorded"] == 1 and report["missing_scan_points"] == 1
    assert report["matched_fraction_of_plan"] == 0
    assert report["median_absolute_residual"] is None
    assert "residual" not in report["records"][0]
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("mode", ["grid", "fig3"])
@pytest.mark.parametrize("limits,should_cross", [([2, 2, 2, 2], False),
    ([.1, .1, .1, .1], False), ([.5, .5, 2, 2], True)])
def test_only_actual_contour_segments_get_exclusion_legends(plots, capsys, mode, limits, should_cross):
    doc = scan()
    for p, mu in zip(doc["points"], limits):
        p["mu95_obs"] = mu
    if mode == "grid":
        renderer.render_grid(doc, [], plots.args)
    else:
        grid = ([p["m_parent"] for p in doc["points"]],
                [p["dm"] for p in doc["points"]], [10] * 4)
        renderer.render_fig3(doc, [], grid, plots.args)
    assert plots.saved
    assert any("Ravel" in label and "95% CL" in label for label in plots.legends) == should_cross
    if not should_cross:
        assert "contour drawn" not in capsys.readouterr().out


@pytest.mark.parametrize("mode", ["line", "grid"])
def test_all_bound_population_has_a_clear_no_measurements_failure(plots, mode):
    points = ([point(100, dm) for dm in (10, 20, 30)] if mode == "line" else scan()["points"])
    for p in points:
        p["quality"] = "capped"
    with pytest.raises(SystemExit, match="no measured limits"):
        getattr(renderer, "render_" + mode)(scan(points), [], plots.args)
    assert not plots.saved


@pytest.mark.parametrize("include_contour", [False, True])
def test_default_both_renders_available_expected_column(tmp_path, monkeypatch, plots, include_contour):
    doc = scan()
    scan_path = write_scan(tmp_path, doc)
    reference_path = write_reference(tmp_path, reference(columns=[("Expected limit", 15)]))
    argv = ["scan_contour", "--scan", str(scan_path), "--atlas-limit", str(reference_path),
            "--out", plots.args.out]
    if include_contour:
        contour = tmp_path / "contour.yaml"
        contour.write_text("fixture read through a patched contour parser")
        monkeypatch.setattr(renderer, "read_contour", lambda path: ([100, 200], [15, 15], "mass", "Delta m"))
        argv.extend(["--atlas-contour", "expected=" + str(contour)])
    monkeypatch.setattr(sys, "argv", argv)
    renderer.main()
    report = json.loads(Path(plots.args.out + "__reldiff_expected.json").read_text())
    assert report["kind"] == "expected"
    assert report["counts"]["matched"] == 4
    # Expected 3 x 5 fb agrees exactly; observed 2 x 5 fb would not.
    assert all(row["limit_fb"] == 15 and row["residual"] == 0 for row in report["records"])
    assert not Path(plots.args.out + "__reldiff.json").exists()
    stems = [stem for _, stem in plots.saved]
    assert (plots.args.out + "__fig3_expected" in stems) == include_contour
    assert plots.args.out + "__fig3" not in stems


@pytest.mark.parametrize("limits,measured_reach", [([.5, .5, .5], False),
                                                   ([.5, .5, 2], True)])
def test_line_reach_comparison_requires_a_bracketed_upper_crossing(plots, limits, measured_reach):
    doc = scan([point(100, dm, mu) for dm, mu in zip((1, 2, 3), limits)])
    contour = [("observed", "fixture", [90, 110], [4, 4], "mass", "Delta m")]
    renderer.render_line(doc, contour, plots.args)
    comparisons = [line for line in plots.annotations if "Ravel" in line and "vs ATLAS" in line]
    assert bool(comparisons) == measured_reach
    if not measured_reach:
        assert not any("percent" in line for line in plots.annotations)


def test_forced_line_layout_cannot_connect_different_parent_masses(tmp_path, monkeypatch, plots):
    doc = scan([point(mass, dm) for mass, dm in zip((100, 150, 200), (1, 2, 3))])
    path = write_scan(tmp_path, doc)
    monkeypatch.setattr(sys, "argv", ["scan_contour", "--scan", str(path),
                                      "--layout", "line", "--out", plots.args.out])
    with pytest.raises(SystemExit):
        renderer.main()
    assert not plots.saved


@pytest.mark.parametrize("kind,other", [("observed", "expected"), ("expected", "observed")])
def test_fig3_never_overlays_an_unlike_reference_contour(plots, kind, other):
    doc = scan()
    grid = ([p["m_parent"] for p in doc["points"]],
            [p["dm"] for p in doc["points"]], [10] * 4)
    contours = [(other, "fixture", [100, 200], [15, 15], "mass", "Delta m")]
    renderer.render_fig3(doc, contours, grid, plots.args, kind=kind)
    assert not any(label.startswith("ATLAS") for label in plots.legends)
    assert any(f"No {kind} reference contour supplied" in line for line in plots.annotations)


@pytest.mark.parametrize("kind", ["observed", "expected"])
def test_fig3_selects_matching_reference_from_both_families(plots, kind):
    doc = scan()
    grid = ([p["m_parent"] for p in doc["points"]],
            [p["dm"] for p in doc["points"]], [10] * 4)
    contours = [(role, "fixture", [100, 200], [15, 15], "mass", "Delta m")
                for role in ("observed", "expected")]
    renderer.render_fig3(doc, contours, grid, plots.args, kind=kind)
    assert [label for label in plots.legends if label.startswith("ATLAS")] == [f"ATLAS {kind}"]


@pytest.mark.parametrize("value", [-1, 0, float("nan"), float("inf"), True, "3"])
def test_invalid_expected_medians_are_rejected_at_load(tmp_path, value):
    doc = scan()
    doc["points"][0]["mu95_exp"] = value
    with pytest.raises(SystemExit, match="expected"):
        renderer.load_scan(write_scan(tmp_path, doc))


@pytest.mark.parametrize("band", [[5, 4, 3, 2, 1], [1, 2, 3, 4],
    [True, 2, 3, 4, 5], [1, 2, 3, 4, float("nan")], [-1, 2, 3, 4, 5], [0, 2, 3, 4, 5]])
def test_invalid_expected_bands_are_rejected_at_load(tmp_path, band):
    doc = scan()
    doc["points"][0]["mu95_exp_band"] = band
    with pytest.raises(SystemExit, match="band"):
        renderer.load_scan(write_scan(tmp_path, doc))


def test_valid_expected_band_and_absent_optional_expected_values_load(tmp_path):
    doc = scan()
    doc["points"][0]["mu95_exp_band"] = [1, 2, 3, 4, 5]
    doc["points"][1]["mu95_exp"] = None
    doc["points"][1]["mu95_exp_band"] = None
    assert renderer.load_scan(write_scan(tmp_path, doc)) == doc


def test_one_sparse_refinement_point_does_not_create_an_unsupported_row():
    mass, dm = np.meshgrid([100, 150, 200], [10, 20, 30])
    mass = np.append(mass.ravel(), 125)
    dm = np.append(dm.ravel(), 25)
    _, split_grid, field = renderer._smooth_field(mass, dm, np.ones(len(mass)),
                                                 nx=101, ny=101, logy=False)
    row = int(np.argmin(np.abs(split_grid[:, 0] - 25)))
    assert split_grid[row, 0] == pytest.approx(25)
    # The established 3x3 support remains continuous through the sparse refinement.
    assert not np.ma.getmaskarray(field)[row, 1:-1].any()
    assert np.allclose(field[row, 1:-1], 1)
