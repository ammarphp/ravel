"""Measured JSON cutflows use the real reference comparison without a YODA reader."""
import builtins
import copy
import json
import math

import pytest

from ravel.validation import validate_cutflow


def measured_cutflow(selected=50):
    scale = .02

    def cut(name, expression, count):
        return {"name": name, "expression": expression, "raw": count,
                "sumw": count, "sumw2": count, "yield": scale * count,
                "yield_uncertainty": scale * math.sqrt(count)}

    return {"schema_version": 1, "kind": "cutflow",
            "quantity": {"weight_convention": "signed"}, "recipe": "selection",
            "unit": "events", "normalization_scale": scale,
            "regions": [{"name": "X", "cuts": [cut("all events", None, 100),
                                                    cut("selected", "pt > 10", selected)]}]}


def reference_tables(path):
    path.mkdir()
    (path / "submission.yaml").write_text(json.dumps({
        "description": "acceptance times efficiency SRX model", "data_file": "grid.yaml"}))
    (path / "grid.yaml").write_text(json.dumps({
        "independent_variables": [{"values": [{"value": 100}]},
                                  {"values": [{"value": 1}]}],
        "dependent_variables": [{"values": [{"value": .5}]}]}))


def arguments(tmp_path, signal, reader="auto"):
    tables = tmp_path / "tables"
    reference_tables(tables)
    out = tmp_path / "comparison.md"
    return ["--signal", str(signal), "--routine", "selection", "--sigma-pb", ".002",
            "--lumi-fb", ".001", "--tables-dir", str(tables), "--grid", "model",
            "--m-parent", "100", "--m-lsp", "1", "--srs", "X",
            "--driving-sr-override", "X", "--sr-reader", reader, "--out", str(out)], out


def block_yoda(monkeypatch, *, unavailable=False):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "yoda" or name.startswith("yoda."):
            if unavailable:
                raise ModuleNotFoundError("No module named 'yoda'", name="yoda")
            raise AssertionError("JSON cutflows must not import YODA")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)


def run_json(tmp_path, monkeypatch, document, *, reader="auto", raw_text=None):
    block_yoda(monkeypatch)
    signal = tmp_path / "cutflow.json"
    signal.write_text(json.dumps(document) if raw_text is None else raw_text)
    argv, out = arguments(tmp_path, signal, reader)
    result = validate_cutflow.main(argv)
    return result, json.loads(out.with_suffix(".json").read_text()), out, signal


def assert_refused(result, report, out, signal, reason):
    assert result == 2
    assert report["status"] == "refused"
    assert report["reason"] == reason
    assert report["artifact"] == str(signal)
    assert report["verdict"] == "FAIL"
    assert not report.get("rows")
    assert "FAIL" in out.read_text()
    assert reason in out.read_text()
    assert str(signal) in out.read_text()


@pytest.mark.parametrize("reader", ["auto", "cutflow"])
def test_json_cutflow_compares_real_published_reference_without_yoda(tmp_path, monkeypatch, reader):
    result, report, out, _ = run_json(tmp_path, monkeypatch, measured_cutflow(), reader=reader)
    assert result in (None, 0)
    assert report["verdict"] == "PASS"
    assert report["comparison_counts"] == {"requested": 1, "evaluated": 1, "missing": 0}
    row, = report["rows"]
    assert row["mine"] == pytest.approx(.5)
    assert row["pub"] == pytest.approx(.5)
    assert row["ratio"] == pytest.approx(1)
    assert row["role"] == "driving" and row["ok"] is True
    assert row["node"].startswith("grid node")
    assert "Verdict: PASS" in out.read_text()


def test_json_changed_selection_fails_existing_driving_residual_gate(tmp_path, monkeypatch):
    result, report, _, _ = run_json(tmp_path, monkeypatch, measured_cutflow(25))
    assert result in (None, 0)
    assert report["verdict"] == "FAIL"
    row, = report["rows"]
    assert row["mine"] == pytest.approx(.25)
    assert row["ratio"] == pytest.approx(.5)
    assert row["ok"] is False
    assert report["worst_driving_mu95_impact"] == pytest.approx(.5)


def test_json_counter_reader_is_typed_mismatch(tmp_path, monkeypatch):
    result, report, out, signal = run_json(tmp_path, monkeypatch, measured_cutflow(), reader="counter")
    assert_refused(result, report, out, signal, "cutflow_reader_mismatch")


@pytest.mark.parametrize("case", [
    "schema", "kind", "weight", "recipe", "unit", "scale_zero", "scale_nan",
    "empty_regions", "duplicate_region", "one_cut", "duplicate_cut", "first_name",
    "first_expression", "raw_bool", "raw_negative", "raw_fraction", "sumw_negative",
    "sumw_nan", "sumw2_negative", "yield_negative", "uncertainty_negative",
    "yield_inconsistent", "uncertainty_inconsistent", "zero_denominator",
    "missing_cut_field", "missing_top_field", "bad_expression", "empty_cut_name",
])
def test_malformed_measured_json_is_typed_refusal(tmp_path, monkeypatch, case):
    document = measured_cutflow()
    first, final = document["regions"][0]["cuts"]
    if case == "schema": document["schema_version"] = 2
    elif case == "kind": document["kind"] = "histogram"
    elif case == "weight": document["quantity"]["weight_convention"] = "absolute"
    elif case == "recipe": document["recipe"] = "another-selection"
    elif case == "unit": document["unit"] = ""
    elif case == "scale_zero": document["normalization_scale"] = 0
    elif case == "scale_nan": document["normalization_scale"] = float("nan")
    elif case == "empty_regions": document["regions"] = []
    elif case == "duplicate_region": document["regions"].append(copy.deepcopy(document["regions"][0]))
    elif case == "one_cut": document["regions"][0]["cuts"] = [first]
    elif case == "duplicate_cut": final["name"] = first["name"]
    elif case == "first_name": first["name"] = "preselected"
    elif case == "first_expression": first["expression"] = "pt > 0"
    elif case == "raw_bool": final["raw"] = True
    elif case == "raw_negative": final["raw"] = -1
    elif case == "raw_fraction": final["raw"] = 2.5
    elif case == "sumw_negative": final["sumw"] = -1
    elif case == "sumw_nan": final["sumw"] = float("nan")
    elif case == "sumw2_negative": final["sumw2"] = -1
    elif case == "yield_negative": final["yield"] = -1
    elif case == "uncertainty_negative": final["yield_uncertainty"] = -1
    elif case == "yield_inconsistent": final["yield"] = 123
    elif case == "uncertainty_inconsistent": final["yield_uncertainty"] = 123
    elif case == "zero_denominator": first.update(raw=0, sumw=0, sumw2=0, **{"yield": 0, "yield_uncertainty": 0})
    elif case == "missing_cut_field": del final["sumw2"]
    elif case == "missing_top_field": del document["quantity"]
    elif case == "bad_expression": final["expression"] = []
    elif case == "empty_cut_name": final["name"] = ""
    result, report, out, signal = run_json(tmp_path, monkeypatch, document)
    assert_refused(result, report, out, signal, "cutflow_input_invalid")


@pytest.mark.parametrize("raw_text", ["{broken", '{"kind":"cutflow","kind":"cutflow"}'])
def test_unparseable_or_duplicate_key_json_is_typed_refusal(tmp_path, monkeypatch, raw_text):
    result, report, out, signal = run_json(tmp_path, monkeypatch, None, raw_text=raw_text)
    assert_refused(result, report, out, signal, "cutflow_input_invalid")


def test_unavailable_yoda_reader_writes_typed_refusal_naming_artifact(tmp_path, monkeypatch):
    block_yoda(monkeypatch, unavailable=True)
    signal = tmp_path / "signal.yoda"
    signal.write_text("Reader is unavailable; no substitute reader is supplied.\n")
    argv, out = arguments(tmp_path, signal)
    result = validate_cutflow.main(argv)
    report = json.loads(out.with_suffix(".json").read_text())
    assert_refused(result, report, out, signal, "yoda_reader_unavailable")
