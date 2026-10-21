"""likelihood_appropriateness: the coded appropriateness check for a published likelihood.

Synthetic workspace with three single-bin channels (SR_a, SR_b, CR_x) and inert signal patches.
"""
import copy
import json

import pytest

from ravel.validation import likelihood_appropriateness as la


def workspace():
    channels = [{"name": name, "samples": [{"name": "bkg", "data": [b],
                                            "modifiers": [{"name": "bkg_norm", "type": "normsys",
                                                           "data": {"hi": 1.1, "lo": 0.9}}]}]}
                for name, b in (("SR_a", 10.0), ("SR_b", 8.0), ("CR_x", 200.0))]
    return {"channels": channels,
            "observations": [{"name": c["name"], "data": [c["samples"][0]["data"][0]]} for c in channels],
            "measurements": [{"name": "meas", "config": {"poi": "mu_sig", "parameters": []}}],
            "version": "1.0.0"}


def add(index, *, poi="mu_sig", bins=1, extra=()):
    modifiers = [{"name": poi, "type": "normfactor", "data": None}, *extra]
    return {"op": "add", "path": f"/channels/{index}/samples/1",
            "value": {"name": "signal", "data": [1.0] * bins, "modifiers": modifiers}}


FULL = [add(0), add(1), add(2)]
SR_ONLY = [add(0), add(1)]
MAP_CR_NULL = {"SR_a": {"region": "A"}, "SR_b": {"region": "B"}, "CR_x": None}
MODEL = {"process": "p p > X X", "final_state": "2 leptons + MET", "parameters": ["m_X"]}


def codes(record, severity=None):
    return sorted(f["code"] for f in record["findings"] if severity in (None, f["severity"]))


def test_full_patch_with_agreeing_metadata_is_appropriate():
    record = la.assess(workspace(), FULL,
                       declared={"signal_model": MODEL, "selection_identity": "sel-1"},
                       selection={"identity": "sel-1",
                                  "signal_model": {"process": "P P > x x", "final_state": "2 Leptons+met",
                                                   "parameters": ["m_X"]}})
    assert record["verdict"] == "appropriate", record["findings"]
    assert record["kind"] == "likelihood-appropriateness" and record["schema_version"] == 1
    assert record["thresholds"] == {"max_unmodelled_control_fraction": 0.05}
    assert {c["name"] for c in record["checks"]} == set(la.CHECK_NAMES)
    assert all(c["status"] == "pass" for c in record["checks"])
    assert "does not establish acceptance" in record["scope"]
    assert la.validate_record(record) == []


def test_missing_metadata_gives_cautions_not_a_pass():
    record = la.assess(workspace(), FULL)
    assert record["verdict"] == "appropriate-with-cautions"
    assert codes(record) == ["selection-unverified", "signal-model-undeclared"]
    status = {c["name"]: c["status"] for c in record["checks"]}
    assert status["signal-model"] == status["selection-identity"] == "not-evaluated"


def test_sr_only_patch_leaves_control_region_without_signal():
    record = la.assess(workspace(), SR_ONLY, channel_map=MAP_CR_NULL)
    finding = next(f for f in record["findings"] if f["code"] == "control-regions-without-signal")
    assert finding["severity"] == "caution" and finding["evidence"]["channels"] == ["CR_x"]
    assert finding["evidence"]["declared_zero"] == ["CR_x"]
    assert "cr-signal-contamination-unknown" in codes(record, "info")
    assert "missing-channels" not in codes(record)
    assert record["verdict"] == "appropriate-with-cautions"


@pytest.mark.parametrize("s, b, blocking", [(1.0, 200.0, False), (20.0, 200.0, True), (0.5, 0.0, True)])
def test_unmodelled_control_fraction_threshold(s, b, blocking):
    record = la.assess(workspace(), SR_ONLY, channel_map=MAP_CR_NULL, signal_yields={"CR_x": {"s": s, "b": b}})
    finding = next(f for f in record["findings"] if f["code"] == "control-regions-without-signal")
    assert finding["severity"] == ("blocking" if blocking else "caution")
    assert (record["verdict"] == "inappropriate") is blocking
    assert "cr-signal-contamination-unknown" not in codes(record)
    assert finding["evidence"]["max_unmodelled_control_fraction"] == 0.05


def test_threshold_is_configurable_and_recorded():
    record = la.assess(workspace(), SR_ONLY, channel_map=MAP_CR_NULL, signal_yields={"CR_x": {"s": 20.0, "b": 200.0}},
                       thresholds={"max_unmodelled_control_fraction": 0.2})
    assert record["thresholds"]["max_unmodelled_control_fraction"] == 0.2
    assert "inappropriate" != record["verdict"]


def test_unpatched_signal_region_is_missing_without_a_map():
    record = la.assess(workspace(), [add(0), add(2)])
    finding = next(f for f in record["findings"] if f["code"] == "missing-channels")
    assert finding["severity"] == "blocking" and finding["evidence"]["missing"] == ["SR_b"]
    assert record["verdict"] == "inappropriate"


def test_channel_map_decides_missing_channels():
    mapping = {"SR_a": {"region": "A"}, "SR_b": {"region": "B"}, "CR_x": {"region": "X"}}
    record = la.assess(workspace(), SR_ONLY, channel_map=mapping)
    finding = next(f for f in record["findings"] if f["code"] == "missing-channels")
    assert finding["evidence"]["missing"] == ["CR_x"] and finding["evidence"]["basis"] == "channel-map"
    # an SR declared zero by the map is not missing, but it is a channel without signal
    declared_zero = {"SR_a": {"region": "A"}, "SR_b": None, "CR_x": None}
    record = la.assess(workspace(), [add(0)], channel_map=declared_zero)
    assert "missing-channels" not in codes(record)
    cr = next(f for f in record["findings"] if f["code"] == "control-regions-without-signal")
    assert cr["evidence"]["channels"] == ["SR_b", "CR_x"]


def test_channel_map_that_does_not_cover_the_workspace_is_blocking():
    record = la.assess(workspace(), FULL, channel_map={"SR_a": {"region": "A"}, "SR_z": None})
    finding = next(f for f in record["findings"] if f["code"] == "missing-channels")
    assert finding["evidence"]["map_channels_not_in_workspace"] == ["SR_z"]
    assert finding["evidence"]["workspace_channels_not_in_map"] == ["SR_b", "CR_x"]


def test_patch_with_no_signal_is_blocking():
    record = la.assess(workspace(), [], channel_map=MAP_CR_NULL)
    finding = next(f for f in record["findings"] if f["code"] == "missing-channels")
    assert finding["evidence"]["no_channel_receives_signal"] is True
    assert record["verdict"] == "inappropriate"


def test_wrong_poi_name_differs_in_parameterisation():
    record = la.assess(workspace(), [add(0, poi="mu_other"), add(1), add(2)])
    finding = next(f for f in record["findings"] if f["code"] == "parameterisation-differs")
    assert finding["evidence"]["workspace_pois"] == ["mu_sig"]
    assert finding["evidence"]["signal_without_poi_normfactor"][0]["channel"] == "SR_a"
    assert record["verdict"] == "inappropriate"


def test_unsupported_modifier_type_differs_in_parameterisation():
    shape = {"name": "free_shape", "type": "shapefactor", "data": None}
    record = la.assess(workspace(), [add(0, extra=[shape]), add(1), add(2)])
    finding = next(f for f in record["findings"] if f["code"] == "parameterisation-differs")
    assert finding["evidence"]["unsupported_modifier_types"] == [
        {"channel": "SR_a", "sample": "signal", "types": ["shapefactor"]}]


def test_workspace_without_measurement_poi_is_blocking():
    ws = workspace()
    del ws["measurements"]
    record = la.assess(ws, FULL)
    assert "parameterisation-differs" in codes(record, "blocking")


@pytest.mark.parametrize("patch", [
    [{"op": "add", "path": "/channels/7/samples/1", "value": {"name": "s", "data": [1.0], "modifiers": []}}],
    [{"op": "add", "path": "/measurements/0", "value": {}}],
    [add(0, bins=2), add(1), add(2)],
])
def test_bad_paths_and_bin_counts_target_outside_the_workspace(patch):
    record = la.assess(workspace(), patch)
    assert "patch-targets-outside-workspace" in codes(record, "blocking")
    assert record["verdict"] == "inappropriate"


def test_signal_model_and_selection_differences_are_blocking():
    other = dict(MODEL, final_state="1 lepton + jets")
    record = la.assess(workspace(), FULL,
                       declared={"signal_model": MODEL, "selection_identity": "sel-1"},
                       selection={"identity": "sel-2", "signal_model": other})
    assert codes(record, "blocking") == ["selection-changed", "signal-model-differs"]
    differs = next(f for f in record["findings"] if f["code"] == "signal-model-differs")
    assert differs["evidence"]["fields"] == ["final_state"]
    assert differs["evidence"]["declared"] == MODEL and differs["evidence"]["selection"] == other


@pytest.mark.parametrize("kwargs", [
    {"declared": {"signal_model": MODEL, "unknown": 1}},
    {"selection": {"identity": 3}},
    {"thresholds": {"max_unmodelled_control_fraction": -1}},
    {"thresholds": {"other": 0.1}},
    {"signal_yields": {"CR_y": {"s": 1.0, "b": 1.0}}},
    {"signal_yields": {"CR_x": {"s": 1.0}}},
    {"channel_map": ["SR_a"]},
])
def test_malformed_inputs_are_refused(kwargs):
    with pytest.raises(ValueError):
        la.assess(workspace(), FULL, **kwargs)


def test_inputs_are_not_mutated():
    ws, patch = workspace(), copy.deepcopy(SR_ONLY)
    before = (json.dumps(ws, sort_keys=True), json.dumps(patch, sort_keys=True))
    la.assess(ws, patch, channel_map=MAP_CR_NULL)
    assert before == (json.dumps(ws, sort_keys=True), json.dumps(patch, sort_keys=True))


def test_validate_record_rejects_a_verdict_its_findings_contradict():
    record = la.assess(workspace(), [add(0, poi="mu_other"), add(1), add(2)])
    assert la.validate_record(record) == []
    assert la.blocking_codes(record) == ["parameterisation-differs"]
    assert la.validate_record(dict(record, verdict="appropriate"))


def _write(tmp_path, name, value):
    path = tmp_path / name
    path.write_text(json.dumps(value))
    return str(path)


def test_cli_exit_codes_and_record(tmp_path, capsys):
    bkg = _write(tmp_path, "bkg.json", workspace())
    full = _write(tmp_path, "full.json", FULL)
    out = tmp_path / "out" / "likelihood_appropriateness.json"
    declared = _write(tmp_path, "declared.json", {"signal_model": MODEL, "selection_identity": "sel-1"})
    selection = _write(tmp_path, "selection.json", {"identity": "sel-1", "signal_model": MODEL})
    assert la.main(["--bkg", bkg, "--patch", full, "--declared", declared, "--selection", selection,
                    "--out", str(out)]) == 0
    record = json.loads(out.read_text())
    assert record["verdict"] == "appropriate"
    assert [pin["path"] for pin in record["inputs"]] == [bkg, full, declared, selection]
    assert all(len(pin["sha256"]) == 64 for pin in record["inputs"])

    cautions = _write(tmp_path, "sr_only.json", SR_ONLY)
    cmap = _write(tmp_path, "map.json", MAP_CR_NULL)
    assert la.main(["--bkg", bkg, "--patch", cautions, "--channel-map", cmap, "--out", str(out)]) == 0
    assert json.loads(out.read_text())["verdict"] == "appropriate-with-cautions"

    yields = _write(tmp_path, "yields.json", {"CR_x": {"s": 30.0, "b": 200.0}})
    assert la.main(["--bkg", bkg, "--patch", cautions, "--channel-map", cmap, "--signal-yields", yields,
                    "--out", str(out)]) == 1
    assert json.loads(out.read_text())["verdict"] == "inappropriate"
    assert la.main(["--bkg", bkg, "--patch", cautions, "--channel-map", cmap, "--signal-yields", yields,
                    "--threshold-unmodelled-control-fraction", "0.5", "--out", str(out)]) == 0
    assert json.loads(out.read_text())["thresholds"]["max_unmodelled_control_fraction"] == 0.5


def test_cli_usage_and_unreadable_inputs_exit_2(tmp_path):
    bkg = _write(tmp_path, "bkg.json", workspace())
    full = _write(tmp_path, "full.json", FULL)
    out = str(tmp_path / "x.json")
    assert la.main(["--bkg", bkg, "--out", out]) == 2
    assert la.main(["--bkg", str(tmp_path / "absent.json"), "--patch", full, "--out", out]) == 2
    (tmp_path / "broken.json").write_text("{")
    assert la.main(["--bkg", str(tmp_path / "broken.json"), "--patch", full, "--out", out]) == 2
    assert la.main(["--bkg", bkg, "--patch", full, "--shipped-channel-map", "no-such-map", "--out", out]) == 2
    assert la.main(["--bkg", bkg, "--patch", full, "--channel-map", bkg, "--shipped-channel-map", "x",
                    "--out", out]) == 2


def test_cli_resolves_a_shipped_channel_map_through_the_registry(tmp_path):
    from ravel.physics.sa2json_native import published_likelihoods, shipped_channel_map
    map_id = published_likelihoods()["likelihoods"][0]["channel_maps"][0]["id"]
    mapping, shipped = shipped_channel_map(map_id)
    channels = [{"name": name, "samples": [{"name": "bkg", "data": [5.0], "modifiers": []}]} for name in mapping]
    ws = {"channels": channels, "observations": [{"name": n, "data": [5.0]} for n in mapping],
          "measurements": [{"name": "m", "config": {"poi": "mu_sig", "parameters": []}}], "version": "1.0.0"}
    patch = [add(i) for i, (name, entry) in enumerate(mapping.items()) if entry is not None]
    out = tmp_path / "r.json"
    assert la.main(["--bkg", _write(tmp_path, "ws.json", ws), "--patch", _write(tmp_path, "p.json", patch),
                    "--shipped-channel-map", map_id, "--out", str(out)]) == 0
    record = json.loads(out.read_text())
    assert record["inputs"][-1] == {"path": shipped["path"], "sha256": shipped["sha256"],
                                    "shipped_channel_map": map_id}
    assert "missing-channels" not in codes(record)
