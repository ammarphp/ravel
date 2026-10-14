"""Reference identity must not depend on row order or a physical 1 GeV window."""
import json

import pytest

from ravel.validation import certify_acceptance, validate_cutflow


def table(tmp_path, rows):
    (tmp_path/"submission.yaml").write_text(
        "description: acceptance times efficiency SRX model\ndata_file: grid.yaml\n")
    (tmp_path/"grid.yaml").write_text(json.dumps({
        "independent_variables": [
            {"values": [{"value": a} for a, _, _ in rows]},
            {"values": [{"value": b} for _, b, _ in rows]}],
        "dependent_variables": [{"values": [{"value": v} for _, _, v in rows]}]}))


def lookup(engine, path, x, y, **kwargs):
    if engine == "cutflow":
        return validate_cutflow.published_axe(str(path), "X", "model", x, y, **kwargs)[:2]
    return certify_acceptance.published_acceff(str(path), "SRX", "model", x, y, **kwargs)[:2]


@pytest.mark.parametrize("engine", ["cutflow", "acceptance"])
@pytest.mark.parametrize("reverse", [False, True])
def test_subgev_nodes_are_distinct_and_row_order_independent(tmp_path, engine, reverse):
    rows = [(100., .3, .001), (100., .5, .005), (100., 1., .020)]
    table(tmp_path, rows[::-1] if reverse else rows)
    value, label = lookup(engine, tmp_path, 100., .5)
    assert value == .005
    assert "grid node" in label and "0.5" in label


@pytest.mark.parametrize("engine", ["cutflow", "acceptance"])
def test_floating_representation_is_not_a_different_grid_point(tmp_path, engine):
    table(tmp_path, [(150., 25.7, .012)])
    value, label = lookup(engine, tmp_path, 150., 150.-124.3)
    assert value == .012 and label.startswith("grid node")


@pytest.mark.parametrize("engine", ["cutflow", "acceptance"])
def test_between_close_nodes_is_interpolation_not_an_exact_match(tmp_path, engine):
    table(tmp_path, [(100., .3, .001), (100., .5, .005)])
    value, label = lookup(engine, tmp_path, 100., .4)
    assert value == pytest.approx(.003)
    assert label.startswith("interp")


@pytest.mark.parametrize("engine", ["cutflow", "acceptance"])
def test_large_explicit_tolerance_cannot_choose_arbitrary_node(tmp_path, engine):
    table(tmp_path, [(100., .3, .001), (100., .5, .005)])
    with pytest.raises(ValueError, match="ambiguous reference-grid node"):
        lookup(engine, tmp_path, 100., .5, node_tol=1.)


@pytest.mark.parametrize("engine", ["cutflow", "acceptance"])
def test_interpolation_cannot_mix_distinct_nearby_fixed_coordinates(tmp_path, engine):
    table(tmp_path, [(100., 1., .001), (100.5, 3., .003)])
    with pytest.raises(ValueError, match="ambiguous reference-grid slice"):
        lookup(engine, tmp_path, 100.25, 2., node_tol=.9)


@pytest.mark.parametrize("engine", ["cutflow", "acceptance"])
def test_duplicate_reference_coordinates_fail(tmp_path, engine):
    table(tmp_path, [(100., .5, .001), (100., .5, .005)])
    with pytest.raises(ValueError, match="duplicate reference-grid"):
        lookup(engine, tmp_path, 100., .5)


@pytest.mark.parametrize("engine", ["cutflow", "acceptance"])
def test_off_grid_point_is_not_labeled_exact(tmp_path, engine):
    table(tmp_path, [(100., .3, .001), (100., .5, .005)])
    _, label = lookup(engine, tmp_path, 100.1, .4)
    assert label.startswith("NEAREST")


@pytest.mark.parametrize("engine", ["cutflow", "acceptance"])
def test_fractional_parent_identity_is_not_rounded_away(tmp_path, engine):
    table(tmp_path, [(100.25, .5, .001)])
    _, label = lookup(engine, tmp_path, 100.25, .5)
    assert "100.25" in label


def test_separate_acceptance_efficiency_nodes_cannot_alias_in_description(tmp_path):
    table(tmp_path, [(100.0000009, .5, .001)])
    (tmp_path/"grid.yaml").rename(tmp_path/"acceptance.yaml")
    table(tmp_path, [(100.0000001, .5, .4)])
    (tmp_path/"grid.yaml").rename(tmp_path/"efficiency.yaml")
    (tmp_path/"submission.yaml").write_text(
        "description: acceptance SRX model\ndata_file: acceptance.yaml\n---\n"
        "description: efficiency SRX model\ndata_file: efficiency.yaml\n")
    value, label, _ = certify_acceptance.published_acceff(
        str(tmp_path), "SRX", "model", 100.0000005, .5)
    assert value is None and "lookup nodes differ" in label
