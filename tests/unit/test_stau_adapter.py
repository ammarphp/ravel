"""Weighted all-region projection, source boundaries, and adversarial custody."""
from copy import deepcopy
import hashlib
import json
import math

import pytest

from ravel.physics import stau_adapter as stau

from analysis_package_fixtures import selected_manifest, selected_source, manifest_pin

@pytest.fixture(autouse=True)
def supplied_selection(monkeypatch):
    monkeypatch.setenv('RAVEL_ANALYSIS_PACKAGE', str(selected_manifest('selection-d')))



def state(region="low"):
    tau = lambda pt, charge, ident="tight", phi=0: {"pt": pt, "eta": 0, "phi": phi, "mass": 0,
        "charge": charge, "prongs": 1, "id": ident}
    value = {"taus": [tau(110, 1), tau(80, -1, phi=2)], "muons": [], "n_electrons": 0, "n_bjets": 0,
        "met_pt": 100, "met_phi": 4, "mt2": {"loose_pair": 90, "medium_pair": 90, "mu_tau": 50},
        "top_tagged": False, "triggers": {"asym_ditau": True, "ditau_met": True, "single_muon": False},
        "response_weights": dict.fromkeys(stau.CHANNELS, 1)}
    if region in ("high", "qhigh"):
        value["met_pt"] = 180
    if region in ("qlow", "qhigh"):
        value["taus"][1]["charge"] = 1
    if region == "wcr":
        value.update(taus=[tau(200, 1, "medium", -2)],
            muons=[{"pt": 80, "eta": 0, "phi": 0, "mass": 0, "charge": -1, "isolated": True}],
            met_pt=100, met_phi=1.2)
        value["triggers"]["single_muon"] = True
    if region == "rejected":
        value["n_bjets"] = 1
    return value


def contract(weights, *, variations=(), assignment="luminosity_mixture"):
    pin = {"path": "source.txt", "sha256": "0" * 64}
    return {"schema_version": 1, "implementation": stau.IMPLEMENTATION, "dataset_id": "source-production-id",
        "source": "Synthetic arithmetic witness of paper selections, not detector validation", "grounding": [pin], "events": pin,
        "response": {"stage": "calibrated_post_overlap_removal", "components": {key: "Explicit synthetic test semantics" for key in stau.RESPONSE_COMPONENTS}, "evidence": [pin]},
        "generation": {"process": "synthetic witness", "decays": "all tau decays represented", "tau_decay_coverage": "inclusive",
            "spin_correlations": "not applicable to feature witness", "filter": "complete test census", "evidence": [pin]},
        "normalization": {"cross_section_pb": .001, "cross_section_basis": "inclusive_production", "branching_ratio_factor": 1,
            "filter_efficiency": 1, "denominator_basis": "before_filter", "expected_sumw": weights, "evidence": [pin]},
        "eras": [{"name": "2015-17", "luminosity_fb": 80.5, "trigger_epoch": "early"},
                 {"name": "2018", "luminosity_fb": 58.5, "trigger_epoch": "late"}],
        "era_assignment": {"kind": assignment, "seed": "frozen-one"}, "variations": list(variations),
        "uncertainty_model": "poissonized_independent_groups_conditional_denominator",
        "analysis_package": manifest_pin('selection-d'),
        "output": {"prediction": "stau_prediction.json", "contract": "stau_contract.json",
                   "decisions": "stau_event_decisions.jsonl", "format": "json"}}


def record(eid, weight, region="low", group=None, streams=None):
    weights = {"nominal": weight} if streams is None else streams
    return {"event_id": eid, "group_id": group or eid, "generator_filter_pass": True, "weights": weights,
        "states": {era: {stream: state(region) for stream in weights} for era in ("2015-17", "2018")}}


@pytest.mark.parametrize("region,channel", [("qlow", "QCR1cut_cuts"), ("qhigh", "QCR2cut_cuts"),
    ("low", "SR1cut_cuts"), ("high", "SR2cut_cuts"), ("wcr", "WCRcut_cuts")])
def test_source_channel_mapping_and_all_five_topologies(region, channel):
    selected = stau.select_regions(state(region))
    assert selected == {name: name == channel for name in stau.CHANNELS}


def test_qcr_accepts_same_sign_medium_pair_and_vetoes_medium_opposite_sign():
    qcr = state("qlow")
    assert stau.select_regions(qcr)["QCR1cut_cuts"]
    qcr["taus"][1]["charge"] = -1
    assert not stau.select_regions(qcr)["QCR1cut_cuts"]
    qcr["taus"][1]["id"] = "loose"
    assert stau.select_regions(qcr)["QCR1cut_cuts"]


def test_wcr_demands_explicit_top_veto_and_only_one_tau_candidate():
    wcr = state("wcr")
    wcr["top_tagged"] = True
    assert not stau.select_regions(wcr)["WCRcut_cuts"]
    del wcr["top_tagged"]
    with pytest.raises(ValueError, match="top_tagged"):
        stau.select_regions(wcr)
    wcr = state("wcr")
    wcr["taus"].append({**wcr["taus"][0], "pt": 25, "id": "loose"})
    assert not stau.select_regions(wcr)["WCRcut_cuts"]


def test_paper_muon_baseline_must_be_applied_before_supplied_state():
    wcr = state("wcr")
    wcr["muons"][0]["pt"] = 12
    with pytest.raises(ValueError, match="baseline acceptance"):
        stau.select_regions(wcr)


def massive_boundary_state(region, eta):
    value = state(region)
    value["taus"] = [{"pt": 100, "eta": eta, "phi": 0, "mass": 1.777,
                      "charge": 1, "prongs": 1, "id": "tight"}]
    value.update(met_phi=1.4, mt2={"loose_pair": 100, "medium_pair": 100, "mu_tau": 50})
    if region == "wcr":
        value.update(met_pt=200, muons=[{"pt": 60, "eta": -eta, "phi": .5,
            "mass": .105658, "charge": -1, "isolated": True}])
    else:
        value["taus"].append({"pt": 80, "eta": -eta, "phi": .9, "mass": 1.777,
            "charge": 1 if region in ("qlow", "qhigh") else -1, "prongs": 1, "id": "tight"})
    return value


@pytest.mark.parametrize("region,channel", [("low", "SR1cut_cuts"), ("high", "SR2cut_cuts"),
    ("qlow", "QCR1cut_cuts"), ("qhigh", "QCR2cut_cuts")])
def test_paper_rapidity_accepts_massive_ditau_at_sr_and_qcr_upper_boundary(region, channel):
    value = massive_boundary_state(region, 1.5354152584887255)
    a, b = value["taus"]
    assert math.hypot(a["eta"] - b["eta"], .9) > 3.2
    assert stau._dr(a, b) == pytest.approx(3.199646260112018, abs=2e-15)
    assert stau.select_regions(value)[channel]
    # Massless objects at the same coordinates reproduce the eta distance.
    for obj in value["taus"]:
        obj["mass"] = 0
    assert not stau.select_regions(value)[channel]


@pytest.mark.parametrize("eta,expected_distance,selected", [
    (.4330127076657219, .9999437104542794, False),
    (1.7320508126206922, 3.4998518118482393, True)])
def test_paper_rapidity_controls_both_massive_wcr_boundaries(eta, expected_distance, selected):
    value = massive_boundary_state("wcr", eta)
    a, b = value["taus"][0], value["muons"][0]
    assert (1 < math.hypot(2 * eta, .5) < 3.5) is not selected
    assert stau._dr(a, b) == pytest.approx(expected_distance, abs=2e-15)
    assert stau.select_regions(value)["WCRcut_cuts"] is selected
    a["mass"] = b["mass"] = 0
    assert stau.select_regions(value)["WCRcut_cuts"] is not selected


@pytest.mark.parametrize("pt,mass,eta", [(21, 1.777, 2.499999), (15, .105658, -2.699999),
    (100, 120, 1.2), (100, 0, -2.4), (100, 1e-12, 2.4), (80, 1.777, 0)])
def test_rapidity_agrees_with_independent_energy_longitudinal_momentum_definition(pt, mass, eta):
    obj = {"pt": pt, "mass": mass, "eta": eta}
    pz = pt * math.sinh(eta)
    energy = math.sqrt(pt * pt + pz * pz + mass * mass)
    expected = .5 * math.log((energy + pz) / (energy - pz))
    assert stau._rapidity(obj) == pytest.approx(expected, abs=3e-14)
    if mass == 0:
        assert stau._rapidity(obj) == eta


def test_rapidity_distance_is_invariant_under_common_longitudinal_boost():
    a = {"pt": 80, "mass": 20, "eta": .3, "phi": 3.05}
    b = {"pt": 65, "mass": 8, "eta": -.6, "phi": -3.05}
    def boost(obj, beta):
        pz = obj["pt"] * math.sinh(obj["eta"])
        energy = math.sqrt(obj["pt"] ** 2 + obj["mass"] ** 2 + pz ** 2)
        boosted_pz = (pz + beta * energy) / math.sqrt(1 - beta * beta)
        return {**obj, "eta": math.asinh(boosted_pz / obj["pt"])}
    for beta in (-.5, .6):
        aa, bb = boost(a, beta), boost(b, beta)
        assert stau._rapidity(aa) - stau._rapidity(a) == pytest.approx(math.atanh(beta), abs=3e-15)
        assert stau._dr(aa, bb) == pytest.approx(stau._dr(a, b), abs=3e-15)
        assert math.hypot(aa["eta"] - bb["eta"], stau._dphi(aa["phi"], bb["phi"])) != pytest.approx(
            math.hypot(a["eta"] - b["eta"], stau._dphi(a["phi"], b["phi"])), abs=1e-4)


def test_rapidity_ratio_is_finite_when_unscaled_transverse_mass_overflows():
    obj = {"pt": 1.7e308, "mass": 1.7e308, "eta": 2.499999}
    assert math.isinf(math.hypot(obj["pt"], obj["mass"]))
    assert stau._rapidity(obj) == pytest.approx(math.asinh(math.sinh(obj["eta"]) / math.sqrt(2)), abs=1e-15)


@pytest.mark.parametrize("field", ["pt", "mass", "eta", "phi"])
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_object_inputs_are_rejected_before_selection(field, invalid):
    value = state()
    value["taus"][0][field] = invalid
    with pytest.raises(ValueError, match="finite"):
        stau.select_regions(value)


@pytest.mark.parametrize("eta", [1.4, 2.5, -2.5])
def test_rapidity_correction_preserves_pseudorapidity_calibration_acceptance(eta):
    value = state()
    value["taus"][0].update(eta=eta, mass=200)
    assert abs(stau._rapidity(value["taus"][0])) < abs(eta)
    with pytest.raises(ValueError, match="baseline acceptance"):
        stau.select_regions(value)


def test_selection_identity_changes_without_reshuffling_existing_era_draws():
    assert stau.IMPLEMENTATION.endswith("-weighted-paper-v2")
    assert stau._ERA_HASH_NAMESPACE.endswith("-weighted-paper-v1")
    eras = contract({"nominal": 1})["eras"]
    for i in range(64):
        key = json.dumps([stau._ERA_HASH_NAMESPACE, "dataset", str(i), "seed"],
                         sort_keys=True, separators=(",", ":")).encode()
        uniform = int.from_bytes(hashlib.sha256(key).digest(), "big") / 2**256
        expected = "2015-17" if uniform < 80.5 / 139 else "2018"
        assert stau.stable_era("dataset", str(i), eras, "seed") == expected


def test_nonunit_signed_weights_and_group_cross_channel_covariance_are_retained():
    rows = [record("a", 2, group="g1"), record("b", -1, "qlow", group="g1"),
            record("c", -3, group="g2"), record("d", 3, "rejected", group="g3")]
    doc = contract({"nominal": 1})
    doc["normalization"]["cross_section_pb"] = 1 / 139000
    result = stau.project(doc, rows)
    nominal = result["predictions"]["nominal"]
    assert nominal["scale"] == pytest.approx(1)
    assert nominal["yields"] == pytest.approx([-1, 0, -1, 0, 0])
    assert nominal["mc_covariance"][0][0] == pytest.approx(1)
    assert nominal["mc_covariance"][2][2] == pytest.approx(13)
    assert nominal["mc_covariance"][0][2] == pytest.approx(-2)
    assert result["negative_nominal_weights"] == 2
    assert result["template_ready_nonnegative"] is False
    assert result["mc_likelihood_admitted"] is False


def test_era_assignment_is_order_partition_and_group_stable():
    doc = contract({"nominal": 32}, assignment="stable_hash")
    rows = [record(str(i), 1, group=str(i // 2)) for i in range(32)]
    for row in rows:
        for era in row["states"].values():
            era["nominal"]["taus"][1]["pt"] = 70  # survives early, not late
    result = stau.project(doc, rows)
    permuted = stau.project(doc, rows[::2] + rows[1::2])
    assert result == permuted
    audit = {row["event_id"]: row["assigned_era"] for row in result["event_audit"]}
    for index in range(0, 32, 2):
        assert audit[str(index)] == audit[str(index + 1)]
    # Assignment computed independently for each partition matches a whole pass.
    for part in (rows[:7], rows[7:]):
        for row in part:
            assert stau.stable_era(doc["dataset_id"], row["group_id"], list(reversed(doc["eras"])), "frozen-one") == audit[row["event_id"]]


def test_exact_luminosity_mixture_and_response_weight_avoid_random_era_bias():
    doc, rows = contract({"nominal": 2}), [record("a", 2)]
    for era in rows[0]["states"].values():
        era["nominal"]["taus"][1]["pt"] = 70
        era["nominal"]["response_weights"]["SR1cut_cuts"] = .8
    result = stau.project(doc, rows)
    assert result["predictions"]["nominal"]["yields"][2] == pytest.approx(80.5 * .8)


def test_absolute_variation_migrates_events_between_sr_and_preserves_normalization_choice():
    variation = {"name": "MET_scale", "up": "up", "down": "down", "normalization": "nominal_denominator", "description": "source absolute migration witness"}
    rows = [record("a", 2, streams={"nominal": 2, "up": 3, "down": 1})]
    doc = contract({"nominal": 2, "up": 3, "down": 1}, variations=[variation])
    for era in rows[0]["states"].values():
        era["nominal"]["met_pt"] = 149
        era["up"]["met_pt"] = 151
        era["down"]["n_bjets"] = 1
    result = stau.project(doc, rows)
    assert result["predictions"]["nominal"]["yields"] == pytest.approx([0, 0, 139, 0, 0])
    assert result["absolute_variations"]["MET_scale"]["hi_data"] == pytest.approx([0, 0, 0, 208.5, 0])
    assert result["absolute_variations"]["MET_scale"]["lo_data"] == [0] * 5
    doc["variations"][0]["normalization"] = "own_denominator"
    assert stau.project(doc, rows)["absolute_variations"]["MET_scale"]["hi_data"][3] == pytest.approx(139)


def test_before_and_after_generator_filter_conventions_agree_without_double_counting():
    passing, rejected = record("pass", 2), record("reject", 3)
    rejected["generator_filter_pass"] = False
    rejected["states"] = {era: {"nominal": None} for era in passing["states"]}
    before = stau.project(contract({"nominal": 5}), [passing, rejected])
    after_doc = contract({"nominal": 2})
    after_doc["normalization"].update(denominator_basis="after_filter", filter_efficiency=.4)
    after = stau.project(after_doc, [passing])
    assert before["predictions"]["nominal"]["yields"] == after["predictions"]["nominal"]["yields"]
    after_doc["normalization"]["denominator_basis"] = "before_filter"
    with pytest.raises(ValueError, match="filter efficiency again"):
        stau.project(after_doc, [passing])


@pytest.mark.parametrize("fault", ["missing_era", "missing_stream", "missing_channel", "wrong_sumw", "duplicate", "hadronic_only", "double_br"])
def test_missing_prediction_or_false_normalization_is_never_implicit_zero(fault):
    doc, rows = contract({"nominal": 1}), [record("one", 1)]
    if fault == "missing_era": del rows[0]["states"]["2018"]
    elif fault == "missing_stream": rows[0]["states"]["2018"] = {}
    elif fault == "missing_channel": del rows[0]["states"]["2018"]["nominal"]["response_weights"]["WCRcut_cuts"]
    elif fault == "wrong_sumw": doc["normalization"]["expected_sumw"]["nominal"] = 2
    elif fault == "duplicate": rows *= 2
    elif fault == "hadronic_only": doc["generation"]["tau_decay_coverage"] = "hadronic_only"
    else: doc["normalization"].update(cross_section_basis="specified_decays", branching_ratio_factor=.5)
    with pytest.raises(ValueError): stau.project(doc, rows)


def test_zero_or_negative_denominator_is_rejected():
    for weight in (0, -1):
        with pytest.raises(ValueError, match="positive generator denominator"):
            stau.project(contract({"nominal": weight}), [record("a", weight)])


def test_run_pins_every_source_and_retains_all_decisions(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("Synthetic paper selection, response, decay and normalization witness.\n")
    pin = {"path": "source.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    events = tmp_path / "events.json"
    events.write_text(json.dumps([record("a", 1, "wcr")]))
    doc = contract({"nominal": 1})
    doc["grounding"] = [pin]
    for section in ("response", "generation", "normalization"):
        doc[section]["evidence"] = [pin]
    doc["events"] = {"path": "events.json", "sha256": hashlib.sha256(events.read_bytes()).hexdigest()}
    path = tmp_path / "input.json"
    path.write_text(json.dumps(doc))
    task = {"input": "input.json"}
    assert set(stau.inputs(task, tmp_path)) == {source, events, path, selected_manifest('selection-d'), selected_source('selection-d')}
    result = stau.run(task, tmp_path, tmp_path / "out")
    assert result["status"] == "passed" and result["physics_validated"] is False
    prediction = json.loads((tmp_path / "out" / "stau_prediction.json").read_text())
    assert prediction["predictions"]["nominal"]["yields"][4] == pytest.approx(139)
    assert len((tmp_path / "out" / "stau_event_decisions.jsonl").read_text().splitlines()) == 1
    source.write_text("changed")
    with pytest.raises(ValueError, match="source bytes changed"):
        stau.inputs(task, tmp_path)


def bridge_fixture(tmp_path):
    """A supplied five-region feature prediction into a distinct toy likelihood.

    The statistical model is deliberately synthetic; real official modifier
    identity checks are exercised separately by test_signal_templates.py.
    """
    from ravel.physics import published_model as published, signal_templates
    variation = {"name": "response", "up": "up", "down": "down", "normalization": "nominal_denominator", "description": "absolute calibrated response control"}
    rows = [record(str(i), 1, region, streams={"nominal": 1, "up": 1, "down": 1})
            for i, region in enumerate(("qlow", "qhigh", "low", "high", "wcr"))]
    for row in rows:
        for era in row["states"].values():
            era["up"]["response_weights"] = dict.fromkeys(stau.CHANNELS, 1.2)
            era["down"]["response_weights"] = dict.fromkeys(stau.CHANNELS, .7)
    prediction = stau.project(contract({"nominal": 5, "up": 5, "down": 5}, variations=[variation]), rows)
    path = tmp_path / "prediction.json"
    path.write_text(json.dumps(prediction))
    pin = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    workspace = {"version": "1.0.0", "channels": [], "observations": [],
        "measurements": [{"name": "M", "config": {"poi": "mu", "parameters": []}}]}
    for name in stau.CHANNELS:
        signal = {"name": "signal", "data": [1], "modifiers": [
            {"name": "mu", "type": "normfactor", "data": None},
            {"name": "response", "type": "normsys", "data": {"hi": 1.1, "lo": .9}},
            {"name": "response", "type": "histosys", "data": {"hi_data": [1], "lo_data": [1]}},
            {"name": "stat_" + name, "type": "staterror", "data": [.1]}]}
        workspace["channels"].append({"name": name, "samples": [signal, {"name": "background", "data": [100], "modifiers": []}]})
        workspace["observations"].append({"name": name, "data": [100]})
    manifest = {"workspace_compact_sha256": hashlib.sha256(published._compact(workspace)).hexdigest(),
        "channel_order": list(stau.CHANNELS), "measurement": workspace["measurements"][0],
        "signal": [{"channel": name, "present": True, "sample_names": ["signal"]} for name in stau.CHANNELS],
        "modifier_name_type_sharing": {}, "parameter_name_sharing": {}}
    source = published.PublishedModelContract(published._compact(manifest), b"{}", b"{}", b"[]", published._compact(workspace))
    template = signal_templates.identity_template(source, "distinct-projected-template")
    for index, channel in enumerate(template["channels"]):
        sample = channel["samples"][0]
        sample["data"] = [prediction["predictions"]["nominal"]["yields"][index]]
        variance = prediction["predictions"]["nominal"]["mc_covariance"][index][index]
        sample["provenance"] = {"kind": "supplied_prediction", "description": "Synthetic feature projection", "evidence": [pin], "normalization_shape": "source_decomposition"}
        sample["mc_stat"] = {"mode": "supplied", "description": "Independent nonnegative MC groups", "weight_model": "nonnegative", "sumw": sample["data"], "sumw2": [variance]}
        for modifier in sample["modifiers"]:
            if modifier["type"] == "normsys": modifier["data"] = {"hi": 1.2, "lo": .7}
            if modifier["type"] == "histosys": modifier["data"] = {"hi_data": sample["data"], "lo_data": sample["data"]}
            if modifier["type"] == "staterror": modifier["data"] = [math.sqrt(variance)]
    return source, pin, template


def test_all_region_prediction_compiles_into_fit_consumable_template(tmp_path):
    from ravel.physics import signal_templates
    source, pin, template = bridge_fixture(tmp_path)
    bound = stau.build_signal_template_from_projection(source, pin, template)
    model, data, compiled = signal_templates.compile_signal_template(bound)
    assert model.expected_actualdata(model.config.suggested_init()).tolist() == pytest.approx([127.8] * 5)
    assert len(data) == compiled["nmaindata"] + compiled["nauxdata"]
    assert bound.manifest()["workspace_compact_sha256"] != source.manifest()["workspace_compact_sha256"]


@pytest.mark.parametrize("fault", ["double_count", "wrong_nominal", "wrong_mc", "missing_nuisance", "borrowed_identity", "signed", "cross_covariance"])
def test_projection_bridge_rejects_unjustified_inference_changes(tmp_path, fault):
    source, pin, template = bridge_fixture(tmp_path)
    sample = template["channels"][0]["samples"][0]
    if fault == "double_count":
        next(m for m in sample["modifiers"] if m["type"] == "normsys")["data"]["hi"] = 1.44
    elif fault == "wrong_nominal": sample["data"] = [50]
    elif fault == "wrong_mc": sample["mc_stat"]["sumw2"] = [1]
    elif fault == "missing_nuisance": sample["modifiers"] = [m for m in sample["modifiers"] if m["name"] != "response"]
    elif fault == "borrowed_identity": sample["provenance"]["kind"] = "source_identity"
    else:
        path = tmp_path / "prediction.json"
        prediction = json.loads(path.read_text())
        if fault == "signed": prediction["generator_weight_model"] = "signed"
        else: prediction["predictions"]["nominal"]["mc_covariance"][0][2] = 1
        path.write_text(json.dumps(prediction))
        pin["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        stau.build_signal_template_from_projection(source, pin, template)
