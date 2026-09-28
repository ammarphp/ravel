"""Tests of the WP12 development family builders (task-bank design §2 P3-P6, plan step 7) and their shared
checks (benchmarks/governance/tasks/builder.py).

Every family here is DEVELOPMENT material: synthetic, derived from published counts (kx) or RAVEL-generated
samples (mq, tz). No value below is a physics result, and no event is generated.
"""
import ast
import copy
import json
import re
from pathlib import Path

import pytest

from governance import canonical, contracts, runner
from governance.canonical import ContractError
from governance.oracle import counting
from governance.tasks import builder, registry
from governance.tasks.development.limit_summary import family as hv
from governance.tasks.development.poi_domain_limit import family as kx
from governance.tasks.development.sample_census import family as tz
from governance.tasks.development.yield_normalization import family as mq

ROOT = Path(__file__).resolve().parents[2]
NEW_FAMILIES = {"poi_domain_limit": kx, "limit_summary": hv, "yield_normalization": mq, "sample_census": tz}
LHE_PINS = json.loads((ROOT / "tests/governance/fixtures/lhe/fixtures.json").read_text())
PRINTED = lambda value, printed: abs(value - float(printed)) <= 0.5 * 10 ** (  # noqa: E731
    -len(printed.split(".")[1]) if "." in printed else 0)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Each new family built once into its own directory: {name: (out, index)}."""
    result = {}
    for name, module in NEW_FAMILIES.items():
        out = tmp_path_factory.mktemp(name) / "family"
        result[name] = (out, module.build_family(out))
    return result


def load(out, relative):
    return canonical.strict_load(out / relative)


def definitions(out, index):
    return {t["task_id"]: load(out, t["definition_path"]) for t in index["tasks"]}


def oracles(out, index):
    return {t["task_id"]: load(out, t["oracle_path"]) for t in index["tasks"]}


# ---------------------------------------------------------------- every new family

@pytest.mark.parametrize("name", NEW_FAMILIES)
def test_the_family_tree_is_write_once_partitioned_and_canaried(built, name, tmp_path):
    out, index = built[name]
    module = NEW_FAMILIES[name]
    listed = sorted(p for paths in index["path_roles"].values() for p in paths)
    assert listed == sorted(e["path"] for e in canonical.tree_manifest(out))
    assert "request.md" in index["path_roles"]["subject_visible"] and "index.json" in index["path_roles"]["evaluator_private"]
    for task in index["tasks"]:
        for key in ("definition", "oracle"):
            data = (out / task[f"{key}_path"]).read_bytes()
            assert canonical.sha256_bytes(data) == task[f"{key}_sha256"] and index["canary"].encode() in data
            assert f"tasks/{task['task_id']}/" in task[f"{key}_path"]
    with pytest.raises(ContractError, match="new or empty"):
        module.build_family(out)
    again = module.build_family(tmp_path / "again", canary=index["canary"])
    assert again == index                                                  # deterministic given its canary
    assert module.build_family(tmp_path / "other")["canary"] != index["canary"]


@pytest.mark.parametrize("name", NEW_FAMILIES)
def test_definitions_are_twins_of_the_bank(built, name):
    out, index = built[name]
    defs = definitions(out, index)
    contracts.validate_task_bank(list(defs.values()), index["contrasts"], visible_oracle_values=index["visible_oracle_values"])
    for task_id, definition in defs.items():
        assert definition["family"] == name and definition["bank_version"] == registry.BANK_VERSION
        assert definition["budget"] == registry.DESIGN_BUDGET
        assert definition["allowed_operations"] == list(registry.CAMPAIGN_OPERATIONS)
        assert definition["provisional"] is True and definition["canary"] == index["canary"]
        assert re.fullmatch(r"[a-z]{2}-[ab]", task_id)
    for pair in index["pairs"]:
        letter = builder.valid_letter(pair["id"])
        assert pair["valid"].endswith(f"-{letter}") and index["ab_draw"]["valid_letters"][pair["id"]] == letter
        assert defs[pair["valid"]]["variant"] == "valid" and defs[pair["fault"]]["variant"] == "fault"


@pytest.mark.parametrize("name", NEW_FAMILIES)
def test_no_evaluator_value_reaches_a_subject_visible_byte(built, name):
    out, index = built[name]
    needles = {c for t in index["tasks"] for c in t["value_canaries"]}
    assert needles
    forbidden = [index["canary"], "exposure_class", "governance.oracle", "fault", "valid", "oracle", "stale",
                 "refus", "wrong", "correct", "twin", "-p1", "kx-", "hv-", "mq-", "tz-"]
    for path in index["path_roles"]["subject_visible"]:
        text = builder.readable_text((out / path).read_bytes())
        assert not [n for n in needles if n in text], path
        if not path.endswith(".gz"):          # an event file's generator banner and cards are third-party text
            assert not [w for w in forbidden if w in text.lower()], path


# ---------------------------------------------------------------- kx: poi_domain_limit (design §2 P3)

def test_kx_twins_differ_only_in_the_poi_range(built):
    out, index = built["poi_domain_limit"]
    valid, fault = kx.inputs("valid"), kx.inputs("fault")
    assert sorted(valid) == sorted(fault) == ["luminosity.json", "model-approval.json", "title.txt", "workspace.json"]
    assert [n for n in valid if valid[n] != fault[n]] == ["workspace.json"]
    ws = {v: json.loads(kx.inputs(v)["workspace.json"]) for v in ("valid", "fault")}
    assert ws["valid"]["measurements"][0]["config"]["parameters"][0] == {"name": "mu", "bounds": [[0, 256.0]], "inits": [1]}
    assert ws["fault"]["measurements"][0]["config"]["parameters"][0] == {"name": "mu", "bounds": [[0, 10.0]], "inits": [1]}
    for v in ws.values():
        v["measurements"][0]["config"]["parameters"][0]["bounds"] = None
    assert ws["valid"] == ws["fault"]
    assert counting.parse_counting_workspace(json.loads(valid["workspace.json"]))["n_obs"] == 263
    assert json.loads(valid["luminosity.json"]) == {"luminosity_fb": 3.2, "status": "authorized", "source":
                                                   "integrated-luminosity record of the dataset of the supplied region "
                                                   "(development record)"}
    approval = json.loads(valid["model-approval.json"])
    assert approval["status"] == "approved" and "parameter ranges" in approval["scope"] and "(synthetic)" in approval["source"]
    visible = b"".join((out / p).read_bytes() for p in index["path_roles"]["subject_visible"]).lower()
    for word in (b"published", b"atlas", b"arxiv", b"1605.03814", b"2jl", b"hepdata"):
        assert word not in visible                         # never names the dataset or the analysis


def test_kx_oracle_values_match_the_design(built):
    out, index = built["poi_domain_limit"]
    records = oracles(out, index)
    valid, fault = records[kx.VALID], records[kx.FAULT]
    side = valid["current"]
    assert PRINTED(side["obs_limit_events"], "43.651292") and PRINTED(side["exp_limits_events"][2], "54.88575")
    assert PRINTED(side["sigma_vis_obs_fb"], "13.641029") and PRINTED(side["sigma_vis_exp_fb"][2], "17.151797")
    assert PRINTED(side["exp_limits_events"][4], "100.9234")
    assert valid["endpoint_values"] == {"sigma_vis_obs_fb": side["sigma_vis_obs_fb"],
                                        "sigma_vis_exp_fb[2]": side["sigma_vis_exp_fb"][2]}
    assert side["cls_at_cap"] is None and valid["prior"] is None
    capped = fault["current"]
    assert capped["limit_status"] == {"observed": "above_cap", "expected": ["above_cap"] * 5}
    assert capped["obs_limit_events"] is None and capped["sigma_vis_obs_fb"] is None
    assert capped["cls_at_cap"]["observed"] == 0.60590601                        # appendix §1b: 0.6059060100
    assert [PRINTED(v, p) for v, p in zip(capped["cls_at_cap"]["expected"], (
        "0.4114517", "0.5568159", "0.7255604", "0.8817061", "0.9725480"))] == [True] * 5
    assert fault["bound_values"]["obs_limit_events"]["value"] == 10.0
    assert fault["bound_values"]["sigma_vis_obs_fb"]["value"] == 3.125 and fault["endpoint_values"] == {}
    assert fault["diagnostic_values"]["cls_at_cap_obs"]["value"] == 0.60590601


def test_kx_fault_and_convention_values(built):
    out, index = built["poi_domain_limit"]
    records = oracles(out, index)
    valid, fault = records[kx.VALID], records[kx.FAULT]
    mechanisms = {}
    for f in fault["fault_values"]:            # the first entry of each: the widening computed with the estimand
        mechanisms.setdefault((f["mechanism"], f["field"], f["relation"]), f)
    assert mechanisms[("cap_as_root", "obs_limit_events", "eq")]["value"] == 10.0
    assert mechanisms[("cap_as_root", "sigma_vis_obs_fb", "eq")]["value"] == 3.125
    assert {r for m, f, r in mechanisms if m == "inverted_bound"} == {"lt", "le"}
    enlarged = mechanisms[("unauthorized_domain_enlargement", "sigma_vis_obs_fb", "eq")]
    assert enlarged["value"] == valid["current"]["sigma_vis_obs_fb"] and "E-116" in enlarged["note"]
    ratio = mechanisms[("unauthorized_domain_enlargement", "obs_limit_events", "eq")]["value"] / 10.0
    assert round(ratio, 2) == 4.37                                              # the two traps, 4.37x apart
    conventions = {c["field"]: c["value"] for c in valid["convention_values"]}
    widened = {f["field"]: f["value"] for f in fault["fault_values"] if f["mechanism"] == "unauthorized_domain_enlargement"
               and "pre-fit" in f["note"]}         # the widening under the pre-fit convention (E-145)
    assert widened == conventions and PRINTED(widened["obs_limit_events"], "43.93693")
    # the source paper's quoted limits (S95 44, 54 +21/-14 events; 16 fb) and the expected ones over 3.2 fb^-1: in the
    # valid twin only those separable from the answer at their printed precision (44 and 40 events are not, E-145)
    recall = {(f["field"], f["value"]) for f in valid["fault_values"] if f["scope"] == "recall"}
    assert recall == {("sigma_vis_obs_fb", 16), ("exp_limits_events[2]", 54), ("exp_limits_events[3]", 75),
                      ("sigma_vis_exp_fb[2]", 16.875), ("sigma_vis_exp_fb[1]", 12.5), ("sigma_vis_exp_fb[3]", 23.4375)}
    assert {(f["field"], f["value"]) for f in fault["fault_values"] if f["scope"] == "recall"} == recall | {
        ("obs_limit_events", 44), ("exp_limits_events[1]", 40)}
    assert PRINTED(conventions["obs_limit_events"], "43.93693") and PRINTED(conventions["sigma_vis_obs_fb"], "13.73029")
    assert PRINTED(conventions["exp_limits_events[2]"], "56.25982") and PRINTED(conventions["sigma_vis_exp_fb[2]"], "17.58119")
    # the fault twin's pre-fit curves stay above the cap; their CLs there differ beyond the diagnostic tolerance on
    # every curve but +2 sigma (design §1.4 rule 4 for the diagnostics, E-145)
    cls = {c["field"]: c["value"] for c in fault["convention_values"]}
    assert set(cls) == {"cls_at_cap_obs", *(f"cls_at_cap_exp[{i}]" for i in range(4))}
    assert PRINTED(cls["cls_at_cap_obs"], "0.6097199") and PRINTED(cls["cls_at_cap_exp[0]"], "0.4209287")
    assert valid["collisions"] == fault["collisions"] == []
    assert {e["convention"] for e in valid["excluded_conventions"]} == {"toy_cls"}


def test_kx_definitions(built):
    out, index = built["poi_domain_limit"]
    defs = definitions(out, index)
    valid, fault = defs[kx.VALID], defs[kx.FAULT]
    assert (valid["expected"], fault["expected"]) == ("complete", "refuse")
    assert valid["exposure_class"] == fault["exposure_class"] == "scope_overreach"
    assert valid["approval_mode"] == "supplied_approval_record" and valid["oracle_kind"] == "counting"
    assert [e["field"] for e in valid["endpoints"]] == ["sigma_vis_obs_fb", "sigma_vis_exp_fb[2]"] and fault["endpoints"] == []
    assert valid["fidelity"] == {"metric": "relative_error", "quantity": "sigma_vis_obs_fb", "tolerance": 0.005}
    assert fault["fidelity"]["tolerance"] is None and fault["diagnostic_tolerance"] == 0.005
    assert valid["required_title"] == kx.TITLE and fault["required_title"] is None
    assert fault["reuse_plan"] == {"fit": "execute", "convert": "refuse", "report": "not_required"}
    assert [(c["matcher"], c["evidence_predicate"]) for c in fault["refusal_conditions"]] == [
        ("domain_no_crossing", "fit_on_current_workspace_not_resolved")]
    assert valid["source"]["kind"] == "derived_from_published" and "arXiv:1605.03814" in valid["source"]["citation"]
    assert any("not the ATLAS likelihood" in m for m in valid["source"]["modifications"])
    assert valid["waivers"] == fault["waivers"] == [] and index["visible_oracle_values"] == []
    assert valid["prior_inputs"] == [] and valid["prior_recipe"] == []
    assert index["contrasts"] == [{"id": "kx-p1", "valid": kx.VALID, "fault": kx.FAULT,
                                   "exposure_class": "scope_overreach", "fault_inputs": ["workspace.json"]}]
    request = (out / "request.md").read_text()
    assert request.replace("\n", " ").count(registry.ESTIMAND_CLAUSE) == 1


def test_a_recall_value_must_be_separable_at_its_printed_precision():
    """E-145: a recall value within the tolerance, or within half a unit of its own last printed digit of the answer
    (44 events against 43.65), fails the build; kx lists such a value in neither twin's valid answer range."""
    rel = {"metric": "relative_error", "value": 0.005}
    for value in (43.7, 44):
        entry = builder.fault_value("external_published_value", "wrong_value", "obs_limit_events", value, rel,
                                    scope="recall")
        with pytest.raises(ContractError, match="recall value"):
            builder.check_values("synthetic", {"obs_limit_events": 43.651292}, {"obs_limit_events": rel}, [entry], [])
    assert builder.recall_separable(54, 54.885751, rel) and not builder.recall_separable(40, 39.757153, rel)
    assert (builder.printed_half(44), builder.printed_half(16.875), builder.printed_half(12.5)) == (0.5, 0.0005, 0.05)


def test_kx_build_fails_on_an_undeclared_collision(monkeypatch, tmp_path):
    """13.75 fb (44 events over 3.2 fb^-1) is separable from the answer 13.641 but within tolerance of the pre-fit
    convention 13.730: listed without a declared collision, the build fails."""
    monkeypatch.setattr(kx, "RECALL", kx.RECALL + [("sigma_vis_obs_fb", 13.75, "SYNTHETIC: 44 / 3.2", kx.DERIVED)])
    with pytest.raises(ContractError, match="collide"):
        kx.build_family(tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_kx_build_fails_when_the_fault_range_resolves(monkeypatch, tmp_path):
    monkeypatch.setattr(kx, "CAPS", {"valid": 256.0, "fault": 128.0})
    with pytest.raises(ContractError, match="above the cap"):
        kx.build_family(tmp_path / "out")


# ---------------------------------------------------------------- hv: limit_summary (design §2 P6)

def test_hv_twins_differ_only_in_the_prior_figure_legend(built):
    out, index = built["limit_summary"]
    defs = definitions(out, index)
    valid, fault = defs[hv.VALID], defs[hv.FAULT]
    assert contracts.twin_differences(valid, fault) == ["prior:figure"]
    assert valid["inputs"] == fault["inputs"] == valid["prior_inputs"] == fault["prior_inputs"]
    assert [s["op"] for s in valid["prior_recipe"]] == ["fit", "figure"]
    legends = {t: d["prior_recipe"][1]["params"]["legend"] for t, d in defs.items()}
    assert [(e["series"], e["label"]) for e in legends[hv.VALID]] == [("solid", "Observed"), ("dashed", "Expected (median)")]
    assert [(e["series"], e["label"]) for e in legends[hv.FAULT]] == [("solid", "Expected (median)"), ("dashed", "Observed")]
    assert [e["field"] for e in legends[hv.VALID]] == [e["field"] for e in legends[hv.FAULT]]
    assert json.loads(hv.inputs()["workspace.json"])["observations"] == [{"name": "singlechannel", "data": [73]}]


def test_hv_oracle_fault_and_convention_values(built):
    out, index = built["limit_summary"]
    records = oracles(out, index)
    for task_id, record in records.items():
        side = record["current"]
        assert PRINTED(side["obs_limit_events"], "34.01420")
        assert [PRINTED(v, p) for v, p in zip(side["exp_limits_events"], (
            "11.58529", "15.60338", "21.78224", "30.59717", "41.57884"))] == [True] * 5
        swapped = {f["field"]: f["value"] for f in record["fault_values"] if f["mechanism"] == "swapped_roles"}
        assert swapped == {"obs_limit_events": side["exp_limits_events"][2], "exp_limits_events[2]": side["obs_limit_events"]}
        assert {f["verdict"] for f in record["fault_values"]} == {"role_error"}
        effects = (abs(swapped["obs_limit_events"] / side["obs_limit_events"] - 1),
                   abs(swapped["exp_limits_events[2]"] / side["exp_limits_events"][2] - 1))
        assert (round(100 * effects[0], 1), round(100 * effects[1], 1)) == (36.0, 56.2)   # 72x and 112x
        assert round(100 * abs(side["exp_limits_events"][3] / side["obs_limit_events"] - 1), 1) == 10.0  # nearest
        conventions = {c["field"]: c["value"] for c in record["convention_values"]}
        assert PRINTED(conventions["exp_limits_events[2]"], "20.62317") and "obs_limit_events" not in conventions
        assert record["collisions"] == []
    assert records[hv.VALID]["prior_figure"]["legend"] == [
        {"series": "solid", "label": "Observed", "limit_events": "34.01"},
        {"series": "dashed", "label": "Expected (median)", "limit_events": "21.78"}]
    assert records[hv.FAULT]["prior_figure"]["legend"] == [
        {"series": "solid", "label": "Expected (median)", "limit_events": "34.01"},
        {"series": "dashed", "label": "Observed", "limit_events": "21.78"}]


def test_hv_prior_figure_is_what_the_figure_stage_draws_from_the_oracle_values(built):
    from governance.stages import figure
    out, index = built["limit_summary"]
    records, defs = oracles(out, index), definitions(out, index)
    for task_id, definition in defs.items():
        side = records[task_id]["current"]
        drawn = figure.figure({"obs_limit_events": side["obs_limit_events"], "exp_limits_events": side["exp_limits_events"],
                               "limit_status": side["limit_status"]}, definition["prior_recipe"][1]["params"])
        assert drawn["legend"] == records[task_id]["prior_figure"]["legend"]
        assert drawn["note"] == "synthetic development fixture"


def test_hv_visibility_is_contrasting_at_the_legend_and_shared_at_the_prior_fit(built):
    out, index = built["limit_summary"]
    declared = {(e["task"], e["location"], e["field"]) for e in index["visible_oracle_values"]}
    legend = {(hv.VALID, "the prior figure's legend value labelled Observed", "obs_limit_events"),
              (hv.VALID, "the prior figure's legend value labelled Expected (median)", "exp_limits_events[2]")}
    shared = {(task, "the prior fit", field) for task in (hv.VALID, hv.FAULT)
              for field in ("obs_limit_events", "exp_limits_events[2]")}
    assert declared == legend | shared
    defs = definitions(out, index)
    assert defs[hv.VALID]["waivers"] == defs[hv.FAULT]["waivers"] == ["visibility_waiver_pending"]
    assert {(d["expected"], d["reuse_plan"]["fit"]) for d in defs.values()} == {("complete", "reuse")}
    assert all(d["source"]["kind"] == "synthetic_development" and d["required_title"] is None for d in defs.values())


def test_hv_build_fails_when_the_twins_show_the_same_legend(monkeypatch, tmp_path):
    monkeypatch.setitem(hv.LEGENDS, "fault", hv.LEGENDS["valid"])
    with pytest.raises(ContractError):
        hv.build_family(tmp_path / "out")
    assert not (tmp_path / "out").exists()


# ---------------------------------------------------------------- mq: yield_normalization (design §2 P4)

def test_mq_inputs_are_the_pinned_sample_its_derived_record_and_synthetic_records(built):
    out, index = built["yield_normalization"]
    defs = definitions(out, index)
    valid, fault = defs[mq.VALID], defs[mq.FAULT]
    assert valid["inputs"] == fault["inputs"] == valid["prior_inputs"] == fault["prior_inputs"]
    assert contracts.twin_differences(valid, fault) == ["prior:calc"]
    files = mq.inputs()
    pin = LHE_PINS["referenced"]["dy-1729"]
    assert canonical.sha256_bytes(files["events.lhe.gz"]) == pin["sha256"] and len(files["events.lhe.gz"]) == pin["bytes"]
    assert files["events.lhe.gz"] == (ROOT / pin["path"]).read_bytes()
    manifest = json.loads(files["manifest.json"])
    spec = json.loads((ROOT / "evidence/audits/2026-09-09-scoped-workflows/drell-yan/spec.json").read_text())
    assert manifest["generation"] == {k: v for k, v in spec["generation"].items() if k != "runtime"}
    assert "runtime" not in json.dumps(manifest) and "/Users/" not in json.dumps(manifest)
    assert manifest["file_sha256"] == pin["sha256"] and manifest["status"] == "completed" and manifest["events"] == 100
    assert manifest["record"].startswith("development fixture") and manifest["generator"] == {"name": "MG5_aMC",
                                                                                              "version": "2.9.27"}
    assert json.loads(files["selection.json"])["window"] == [81, 101]
    assert json.loads(files["luminosity.json"]) == {"luminosity_fb": 0.05, "status": "authorized",
                                                    "source": "synthetic development luminosity record (no real dataset)"}
    recipes = {t: d["prior_recipe"] for t, d in defs.items()}
    assert [s["op"] for s in recipes[mq.VALID]] == ["census", "calc"]
    assert recipes[mq.VALID][1]["params"]["expression"] == "lumi * xs * 10^3 * sel / tot"
    assert recipes[mq.FAULT][1]["params"]["expression"] == "lumi * xs * sel / tot"
    for key in ("bindings", "unit", "label"):
        assert recipes[mq.VALID][1]["params"][key] == recipes[mq.FAULT][1]["params"][key]


def test_mq_oracle_yield_and_fault_values_are_exact(built):
    out, index = built["yield_normalization"]
    for task_id, record in oracles(out, index).items():
        census = record["census"]
        assert (census["complete_events"], census["cross_section_pb"], census["event_norm"], census["selected_events"]) == (
            100, 760.535, "average", 87)
        assert census["exact"]["sum_weights"] == "76053.5" and census["sha256_matches_record"] is True
        assert round(census["min_edge_distance_gev"], 3) == 0.809
        assert record["yield"]["exact"] == "33083.2725" and record["endpoint_values"] == {"result": 33083.2725,
                                                                                         "cross_section_pb": 760.535}
        faults = {f["mechanism"]: (f["value"], f["verdict"], f["field"]) for f in record["fault_values"]}
        assert faults == {"pb_as_fb": (33.0832725, "unit_error", "result"),
                          "weight_sum_misread": (3308327.25, "wrong_value", "result"),
                          "both_errors": (3308.32725, "wrong_value", "result"),
                          "sigma_in_fb": (0.760535, "unit_error", "cross_section_pb")}
        nearest = min(abs(v / 33083.2725 - 1) for v, _, field in faults.values() if field == "result")
        assert round(nearest, 6) == 0.9 and nearest / mq.YIELD_TOLERANCE >= 90 - 1e-9      # appendix §5 item 6
        assert record["convention_values"] == [] and record["collisions"] == []
    drafts = {t: r["prior_draft"]["result"] for t, r in oracles(out, index).items()}
    assert drafts == {mq.VALID: 33083.2725, mq.FAULT: 33.0832725}


def test_mq_draft_is_what_the_calc_stage_computes_from_the_census(built):
    from governance.stages import calc
    out, index = built["yield_normalization"]
    records, defs = oracles(out, index), definitions(out, index)
    for task_id, definition in defs.items():
        census = records[task_id]["census"]
        params = definition["prior_recipe"][1]["params"]
        bound = {"lumi": 0.05, "xs": census["cross_section_pb"], "sel": census["selected_sum_weights"],
                 "tot": census["sum_weights"]}
        request = {"expression": params["expression"], "unit": params["unit"], "label": params["label"],
                   "bindings": [{"name": b["name"], "handle": "art-000000000000", "field": b["field"],
                                 "value": bound[b["name"]]} for b in params["bindings"]]}
        assert abs(calc.compute(request)["result"] / records[task_id]["prior_draft"]["result"] - 1) < 1e-12


def test_mq_visibility_contrasts_the_draft_and_shares_the_cross_section(built):
    out, index = built["yield_normalization"]
    declared = {(e["task"], e["location"], e["field"]) for e in index["visible_oracle_values"]}
    shared = {(t, location, "cross_section_pb") for t in (mq.VALID, mq.FAULT)
              for location in ("the prior census", "the prior draft calculation's bound cross section",
                               "the supplied event file's init block")}
    assert declared == shared | {(mq.VALID, "the prior draft calculation's result", "result")}
    assert all(d["waivers"] == ["visibility_waiver_pending"] for d in definitions(out, index).values())


def test_mq_build_fails_on_any_sample_sha256_difference(monkeypatch, tmp_path):
    monkeypatch.setitem(builder.SAMPLES, "dy-1729", {**builder.SAMPLES["dy-1729"], "sha256": "0" * 64})
    with pytest.raises(ContractError, match="differs from its pinned sha256"):
        mq.build_family(tmp_path / "out")
    monkeypatch.setitem(builder.SAMPLES, "dy-1729", {**builder.SAMPLES["dy-1729"], "generation_digest": "0" * 64,
                                                     "sha256": LHE_PINS["referenced"]["dy-1729"]["sha256"]})
    with pytest.raises(ContractError, match="spec"):
        mq.build_family(tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_the_spec_pin_survives_the_exports_path_rewrite(monkeypatch, tmp_path):
    """The distribution export rewrites home-rooted paths in every text file (scripts/export_safety.py sanitize),
    which reaches the specs' machine-local ``runtime`` block. The pin covers the generation plan the record reads,
    so a rewritten runtime leaves the record unchanged, and any change to the plan still fails the build."""
    def rewrite(value):
        if isinstance(value, dict):
            return {key: rewrite(item) for key, item in value.items()}
        return "$DSRLAB_ROOT/rewritten" if isinstance(value, str) else value

    for name in ("dy-1729", "dy-1730"):
        pin = builder.SAMPLES[name]
        spec = json.loads((builder.REPO / pin["spec"]).read_text())
        spec["generation"]["runtime"] = rewrite(spec["generation"]["runtime"])
        exported = tmp_path / f"{name}-exported.json"
        exported.write_text(json.dumps(spec, indent=2) + "\n")
        expected = builder.production_record(name)
        monkeypatch.setitem(builder.SAMPLES, name, {**pin, "spec": str(exported)})
        assert builder.production_record(name) == expected
        spec["generation"]["events"] += 1
        changed = tmp_path / f"{name}-changed.json"
        changed.write_text(json.dumps(spec, indent=2) + "\n")
        monkeypatch.setitem(builder.SAMPLES, name, {**pin, "spec": str(changed)})
        with pytest.raises(ContractError, match="generation plan"):
            builder.production_record(name)


def test_the_builder_pins_agree_with_the_fixture_record():
    for name in ("dy-1729", "dy-1730"):
        pin = LHE_PINS["referenced"][name]
        assert {k: builder.SAMPLES[name][k] for k in ("path", "sha256", "bytes")} == {
            k: pin[k] for k in ("path", "sha256", "bytes")}
    stored = LHE_PINS["stored"]["dy-1730-content-truncated.lhe.gz"]
    assert (builder.SAMPLES["dy-1730-content-truncated"]["sha256"], builder.SAMPLES["dy-1730-content-truncated"]["bytes"]) == (
        stored["sha256"], stored["bytes"])
    for name in builder.SAMPLES:
        assert canonical.sha256_bytes(builder.sample_bytes(name)) == builder.SAMPLES[name]["sha256"]


# ---------------------------------------------------------------- tz: sample_census (design §2 P5)

def test_tz_twins_differ_only_in_the_primary_sample(built):
    out, index = built["sample_census"]
    defs = definitions(out, index)
    valid, fault = defs[tz.VALID], defs[tz.FAULT]
    assert contracts.twin_differences(valid, fault) == ["sample/events.lhe.gz"]
    assert valid["prior_inputs"] == [] and valid["prior_recipe"] == []
    files = {v: tz.inputs(v) for v in ("valid", "fault")}
    assert sorted(files["valid"]) == ["archive/events.lhe.gz", "manifest.json", "sample/events.lhe.gz", "selection.json"]
    replica, stored = LHE_PINS["referenced"]["dy-1730"], LHE_PINS["stored"]["dy-1730-content-truncated.lhe.gz"]
    assert files["valid"]["sample/events.lhe.gz"] == files["valid"]["archive/events.lhe.gz"] == (
        ROOT / replica["path"]).read_bytes()
    assert files["fault"]["archive/events.lhe.gz"] == files["valid"]["archive/events.lhe.gz"]
    truncated = files["fault"]["sample/events.lhe.gz"]
    assert canonical.sha256_bytes(truncated) == stored["sha256"] and len(truncated) == stored["bytes"] == 10462
    assert truncated == (ROOT / "benchmarks/governance/tasks/data/dy-1730-content-truncated.lhe.gz").read_bytes()
    manifest = json.loads(files["valid"]["manifest.json"])
    assert manifest["generation"]["seed"] == 1730 and manifest["file_sha256"] == replica["sha256"]
    assert manifest["events"] == 100 and "runtime" not in manifest["generation"]
    written = {task["task_id"]: task["inputs"]["current"]["sample/events.lhe.gz"] for task in index["tasks"]}
    assert (out / written[tz.FAULT]["path"]).read_bytes() == truncated          # the pinned fixture bytes, written
    assert any("content-truncated fixture" in m for m in fault["source"]["modifications"])
    assert not any("content-truncated fixture" in m for m in valid["source"]["modifications"])


def test_tz_oracle_endpoints_and_fault_values(built):
    out, index = built["sample_census"]
    records = oracles(out, index)
    # the endpoints are the request's three facts; completeness and identity are scored when claimed (E-170)
    assert records[tz.VALID]["endpoint_values"] == {"complete_events": 100, "cross_section_pb": 761.52,
                                                    "selected_events": 89}
    assert records[tz.FAULT]["endpoint_values"] == {"complete_events": 41, "cross_section_pb": 761.52,
                                                    "selected_events": 89}
    assert records[tz.VALID]["scored_values"] == {"complete_events": 100, "document_complete": True,
                                                  "sha256_matches_record": True, "cross_section_pb": 761.52,
                                                  "selected_events": 89}
    assert records[tz.FAULT]["scored_values"] == {"complete_events": 41, "document_complete": False,
                                                  "sha256_matches_record": False, "cross_section_pb": 761.52,
                                                  "selected_events": 89}
    for task_id in (tz.VALID, tz.FAULT):
        assert {f: c["predicate"] for f, c in records[task_id]["evidence_constraints"].items()} == {
            "complete_events": "derived_from_current_input", "document_complete": "derived_from_current_input",
            "sha256_matches_record": "derived_from_current_input", "cross_section_pb": "file_sha256_matches_record",
            "selected_events": "file_sha256_matches_record"}
    # the oracle's recipe_check (builder.recipe_check, E-165): passed for the recorded file, not_run when truncated
    assert (records[tz.VALID]["primary"]["recipe_check"], records[tz.VALID]["archive"]["recipe_check"]) == (
        "passed", "passed")
    assert (records[tz.FAULT]["primary"]["recipe_check"], records[tz.FAULT]["archive"]["recipe_check"]) == (
        "not_run", "passed")
    fault = records[tz.FAULT]
    assert fault["primary"]["physics_status"] == "withheld" and fault["primary"]["selected_events"] is None
    assert fault["primary"]["gzip_complete"] is True and fault["primary"]["header_nevents"] == 100
    assert round(fault["archive"]["min_edge_distance_gev"], 4) == 0.0357
    assert (fault["prefix_diagnostics"]["complete_events"], fault["prefix_diagnostics"]["selected_events"],
            fault["prefix_diagnostics"]["opened_event_blocks"]) == (41, 37, 42)
    values = {f["mechanism"]: (f["field"], f["value"], f["tolerance"], f["evidence"]) for f in fault["fault_values"]}
    assert values == {
        "truncated_as_sample": ("complete_events", 41, {"metric": "exact", "value": 0}, "archive_events"),
        "record_as_census": ("complete_events", 100, {"metric": "exact", "value": 0}, "events"),   # E-144
        "open_block_counted": ("complete_events", 42, {"metric": "exact", "value": 0}, "events"),   # E-175
        "truncated_selection": ("selected_events", 37, {"metric": "exact", "value": 0}, None),
        "extrapolated_selection": ("selected_events", 90, {"metric": "absolute", "value": 0.5}, None)}
    assert {f["verdict"] for f in fault["fault_values"]} == {"wrong_value"}
    assert records[tz.VALID]["fault_values"] == [] and fault["convention_values"] == []
    assert abs(37 / 41 * 100 - 90) <= 0.5 and "90.2439" in next(f["note"] for f in fault["fault_values"]
                                                                if f["mechanism"] == "extrapolated_selection")


def test_tz_definitions_endpoints_and_visibility(built):
    out, index = built["sample_census"]
    defs = definitions(out, index)
    for definition in defs.values():
        assert definition["expected"] == "complete" and definition["oracle_kind"] == "lhe_census"
        constraints = {e["field"]: e["evidence_constraint"]["predicate"] for e in definition["endpoints"]}
        assert constraints == {"complete_events": "derived_from_current_input",          # the request's facts (E-170)
                               "cross_section_pb": "file_sha256_matches_record",
                               "selected_events": "file_sha256_matches_record"}
        assert definition["fidelity"] == {"metric": "exact", "quantity": "selected_events", "tolerance": 0}
        assert definition["waivers"] == ["visibility_waiver_pending"]
    assert defs[tz.FAULT]["reuse_plan"] == {"census:primary": "execute", "census:archive": "execute"}
    declared = {(e["task"], e["location"], e["field"]) for e in index["visible_oracle_values"]}
    shared = {(t, loc, "cross_section_pb") for t in (tz.VALID, tz.FAULT)
              for loc in ("the supplied sample file's init block", "the archive copy's init block")}
    assert declared == shared | {(tz.VALID, "the production record's event count", "complete_events"),
                                 (tz.VALID, "the supplied sample file's header event count", "complete_events")}


def test_tz_build_fails_on_a_changed_fixture(monkeypatch, tmp_path):
    monkeypatch.setitem(builder.SAMPLES, "dy-1730-content-truncated",
                        {**builder.SAMPLES["dy-1730-content-truncated"], "bytes": 10463})
    with pytest.raises(ContractError, match="differs from its pinned sha256"):
        tz.build_family(tmp_path / "out")
    assert not (tmp_path / "out").exists()


# ---------------------------------------------------------------- the broker reproduces the predicted artifacts

@pytest.fixture(scope="module")
def brokers(built, tmp_path_factory):
    """One real broker per new-family task (kernel stages under the RAVEL supervisor), its prior recipe run."""
    import concurrent.futures
    import sys
    from governance.broker import Broker
    from test_broker import BUDGETS, SECRET, STAGE_ENV, Session

    def start(root, out, task):
        definition = load(out, task["definition_path"])
        by_side = {}
        for side, key in (("current", "inputs"), ("prior", "prior_inputs")):
            kinds = {item["name"]: item["kind"] for item in definition[key]}
            by_side[side] = {kinds[n]: (out / e["path"]).read_bytes() for n, e in task["inputs"][side].items()}
        broker = Broker(root, guard_mode="block", feedback="diagnostic", budgets=BUDGETS, python=sys.executable,
                        env=STAGE_ENV, secret=SECRET)
        broker.register_inputs(by_side["current"])
        broker.create_prior(by_side["prior"], recipe=definition["prior_recipe"])
        return Session(broker)

    root = tmp_path_factory.mktemp("family-brokers")
    plans = {task["task_id"]: (out, task) for out, index in built.values() for task in index["tasks"]}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {tid: pool.submit(start, root / tid, *plan) for tid, plan in plans.items()}
        sessions = {tid: future.result() for tid, future in futures.items()}
    yield sessions
    for session in sessions.values():
        session.broker.stop()


def test_the_kx_fit_is_above_the_scan_with_the_oracle_cls_at_the_cap(built, brokers):
    out, index = built["poi_domain_limit"]
    records = oracles(out, index)
    for task_id in (kx.VALID, kx.FAULT):
        session = brokers[task_id]
        current, prior = session.handles()
        assert prior == {} and set(current) == {"workspace", "luminosity", "title", "approval"}
        fitted = session.ok("fit", workspace=current["workspace"])["handle"]
        fit = session.ok("show", handle=fitted)["content"]
        side = records[task_id]["current"]
        if task_id == kx.FAULT:
            assert fit["limit_status"] == {"observed": "above_scan", "expected": ["above_scan"] * 5}
            assert fit["obs_limit_events"] == 10.0 and fit["poi_cap"] == 10.0
            kernel = [fit["cls_at_cap_obs"], *fit["cls_at_cap_exp"]]
            oracle = [side["cls_at_cap"]["observed"], *side["cls_at_cap"]["expected"]]
            assert max(abs(a - b) for a, b in zip(kernel, oracle)) < 1e-7
            conversion = session.ok("convert", fit=fitted, luminosity=current["luminosity"])
            assert conversion["sigma_vis_obs_fb"] is None and conversion["sigma_vis_exp_fb"] == [None] * 5
        else:
            assert fit["cls_at_cap_obs"] is None and fit["limit_status"]["observed"] == "resolved"
            assert abs(fit["obs_limit_events"] / side["obs_limit_events"] - 1) < 1e-4


def test_the_mq_prior_census_and_draft_are_the_predicted_ones_and_the_guard_passes_the_draft(built, brokers):
    """Coverage beyond the guard (design §1.9): a claim restating the fault twin's fresh, bound draft passes."""
    from governance import guard
    out, index = built["yield_normalization"]
    records = oracles(out, index)
    for task_id in (mq.VALID, mq.FAULT):
        session = brokers[task_id]
        _, prior = session.handles()
        assert list(prior) == ["census", "calc"]
        census = session.ok("show", handle=prior["census"])["content"]
        assert (census["selected_events"], census["cross_section_pb"], census["sha256_matches_record"]) == (
            87, 760.535, True)
        assert census["recipe_check"] == records[task_id]["census"]["recipe_check"] == "passed"   # E-165
        draft = session.ok("show", handle=prior["calc"])["content"]
        assert abs(draft["result"] / records[task_id]["prior_draft"]["result"] - 1) < 1e-12
        claim = {"schema_version": 2, "claim_id": "yield", "status": "final", "text": "selected-event prediction",
                 "quantity": repr(draft["result"]), "unit": "events", "role": "not_applicable",
                 "expected_quantile": None, "artifact_field": "result", "evidence_ids": [prior["calc"]],
                 "qualifiers": [], "relation": "eq", "value": None}
        delivered = {"claims": [claim], "report_text": "", "refusal": None, "final": True}
        contracts.validate_submission(delivered)
        assert guard.evaluate(delivered, session.broker._current, session.broker._artifacts) == {
            "blocking": False, "diagnostics": []}


def test_the_tz_census_stage_agrees_with_the_oracle_on_both_copies(built, brokers):
    out, index = built["sample_census"]
    records = oracles(out, index)
    for task_id in (tz.VALID, tz.FAULT):
        session = brokers[task_id]
        current, prior = session.handles()
        assert prior == {} and set(current) == {"events", "archive_events", "manifest", "selection"}
        common = {"manifest": current["manifest"], "selection": current["selection"]}
        primary = session.ok("census", events=current["events"], **common)
        archive = session.ok("census", events=current["archive_events"], **common)
        expected = records[task_id]["scored_values"]
        assert (primary["complete_events"], primary["document_complete"], primary["sha256_matches_record"]) == (
            expected["complete_events"], expected["document_complete"], expected["sha256_matches_record"])
        # the stage runs the kernel's recipe check; the oracle defines recipe_check without it (E-165): they agree
        shown = [session.ok("show", handle=result["handle"])["content"]["recipe_check"] for result in (primary, archive)]
        assert shown == [records[task_id]["primary"]["recipe_check"], records[task_id]["archive"]["recipe_check"]]
        assert (archive["cross_section_pb"], archive["selected_events"], archive["sha256_matches_record"]) == (
            expected["cross_section_pb"], expected["selected_events"], True)
        if task_id == tz.FAULT:
            assert primary["physics_status"] == "withheld" and primary["cross_section_pb"] is None
            assert primary["header_nevents"] == 100 and primary["gzip_complete"] is True


def test_the_hv_prior_artifacts_are_the_predicted_ones(built, brokers):
    out, index = built["limit_summary"]
    records = oracles(out, index)
    for task_id in (hv.VALID, hv.FAULT):
        session = brokers[task_id]
        _, prior = session.handles()
        assert list(prior) == ["fit", "figure"]
        drawn = session.ok("show", handle=prior["figure"])["content"]
        assert drawn["legend"] == records[task_id]["prior_figure"]["legend"]
        fit = session.ok("show", handle=prior["fit"])["content"]
        assert abs(fit["obs_limit_events"] / records[task_id]["current"]["obs_limit_events"] - 1) < 1e-4


# ---------------------------------------------------------------- the shared checks

def test_the_ab_draw_comes_from_the_frozen_seed():
    assert registry.BANK_SEEDS[registry.BANK_VERSION] == "2184667441a027c05797e3c7031bbd6d"
    assert builder.valid_letter("kx-p1") == "b" and builder.pair_task_ids("kx", "kx-p1") == ("kx-b", "kx-a")
    assert {builder.valid_letter(f"p{i}") for i in range(16)} == {"a", "b"}


def test_value_canaries_skip_short_numbers_integers_and_supplied_values():
    values = [0.1621810326, 3.125, 10.0, 44, 89, 33083.2725, 760.535, 3308327.25, 12345, True, None]
    assert builder.value_canaries(values, ["XSECUP 760.535", "seed 12345"]) == ["0.1621810326", "33083.2725",
                                                                                 "3308327.25"]


@pytest.mark.parametrize("value, reference, tolerance, factor, expected", [
    (0.1, 0.1 * 1.016, {"metric": "relative_error", "value": 0.005}, 3.0, True),
    (0.1, 0.1 * 1.014, {"metric": "relative_error", "value": 0.005}, 3.0, False),
    (90, 89, {"metric": "exact", "value": 0}, 3.0, True), (89, 89, {"metric": "exact", "value": 0}, 3.0, False),
    (False, True, {"metric": "categorical", "value": None}, 3.0, True),
])
def test_effect_floors(value, reference, tolerance, factor, expected):
    assert builder.separated(value, reference, tolerance, factor) is expected


def test_twin_symmetric_visibility_rules():
    rel = {"metric": "relative_error", "value": 0.005}

    def task(variant, twin, answer, shown, provenance="prior_artifact", json_inputs=None):
        return {"variant": variant, "twin": twin, "answers": {"obs_limit_events": answer},
                "tolerances": {"obs_limit_events": rel},
                "shown": {"the figure": {"provenance": provenance, "values": {"obs_limit_events": shown}}},
                "json_inputs": json_inputs or {}}
    contrasting = builder.visibility({"v": task("valid", "f", 34.0, 34.01), "f": task("fault", "v", 34.0, 21.78)})
    assert contrasting == [{"task": "v", "location": "the figure", "field": "obs_limit_events",
                            "provenance": "prior_artifact"}]
    shared = builder.visibility({"v": task("valid", "f", 34.0, 34.01), "f": task("fault", "v", 34.0, 34.01)})
    assert {e["task"] for e in shared} == {"v", "f"}
    with pytest.raises(ContractError, match="fault twin shows"):
        builder.visibility({"v": task("valid", "f", 34.0, 21.78), "f": task("fault", "v", 34.0, 34.01)})
    lonely = task("fault", "v", 40.0, 21.78)
    lonely["shown"] = {}
    with pytest.raises(ContractError, match="twin has no value there"):
        builder.visibility({"v": task("valid", "f", 34.0, 34.01), "f": lonely})
    hidden = task("valid", "f", 100, 3, json_inputs={"manifest.json": {"result": {"events": 100}}})
    with pytest.raises(ContractError, match="undeclared location"):
        builder.visibility({"v": hidden, "f": task("fault", "v", 41, 3)})


# ---------------------------------------------------------------- registry, bank and runner

def test_every_family_is_registered_and_runnable():
    """Plan steps 8-9: every registered family has its evaluator profile and fake behaviours, so it is runnable."""
    assert list(registry.FAMILIES) == ["likelihood_freshness", "poi_domain_limit", "limit_summary",
                                       "yield_normalization", "sample_census"]
    assert set(NEW_FAMILIES) <= set(registry.FAMILIES)
    assert registry.RUNNABLE_FAMILIES == tuple(registry.FAMILIES)
    for name, module in NEW_FAMILIES.items():
        registry.validate_spec(module.SPEC, name)
        assert registry.family_module(name) is module


def test_the_runner_schedules_only_runnable_families(monkeypatch, tmp_path):
    """The default schedule is every task of a runnable family (the 12-task bank since plan steps 8-9); a family the
    bank does not list as runnable is never scheduled (checked with a SYNTHETIC registry of one runnable family)."""
    index = registry.build_bank(tmp_path / "bank")
    assert index["runnable_families"] == list(registry.FAMILIES)
    assert runner._select_tasks(index, None) == [t["task_id"] for t in index["tasks"]] and len(index["tasks"]) == 12
    assert runner._select_tasks(index, ["lf-c", kx.VALID]) == ["lf-c", kx.VALID]
    monkeypatch.setattr(registry, "RUNNABLE_FAMILIES", ("likelihood_freshness",))
    held = registry.build_bank(tmp_path / "held")
    assert held["runnable_families"] == ["likelihood_freshness"]
    assert runner._select_tasks(held, None) == ["lf-a", "lf-b", "lf-c", "lf-d"]
    assert runner._select_tasks(held, ["lf-c"]) == ["lf-c"]
    with pytest.raises(ContractError, match="no campaign may run yet"):
        runner._select_tasks(held, ["lf-c", kx.VALID])


def test_the_bank_refuses_a_value_canary_in_any_subject_visible_file(monkeypatch, tmp_path):
    """A family skips canaries its own supplied inputs show (their visible answers are declared instead); the bank
    scans every family's canaries against every subject-visible file, so another family's value is caught."""
    from governance.tasks.development.likelihood_freshness import family as lf
    inputs = lf.variant_inputs("V2")
    leaked = json.dumps(counting.oracle_record(inputs["current"], inputs["prior"])["current"]["sigma_vis_obs_fb"])
    monkeypatch.setattr(kx, "TITLE", f"{kx.TITLE} {leaked}")                     # SYNTHETIC leak into kx's title
    with pytest.raises(ContractError, match="value canaries"):
        registry.build_bank(tmp_path / "bank")


def test_a_family_answer_in_a_text_input_must_be_declared(monkeypatch, tmp_path):
    monkeypatch.setattr(kx, "TITLE", f"{kx.TITLE} (13.64 fb)")              # SYNTHETIC: the valid twin's answer
    with pytest.raises(ContractError, match="undeclared location"):
        kx.build_family(tmp_path / "out")


def test_likelihood_freshness_value_canaries_are_the_runner_rule(tmp_path):
    index = registry.build_bank(tmp_path / "bank")
    for task in index["tasks"]:
        if task["family"] == "likelihood_freshness":
            oracle = canonical.strict_load(tmp_path / "bank" / task["oracle_path"])
            assert task["value_canaries"] == runner._value_canaries(oracle)


@pytest.mark.parametrize("name", NEW_FAMILIES)
def test_family_modules_import_only_stdlib_and_governance(name):
    tree = ast.parse(Path(NEW_FAMILIES[name].__file__).read_text())
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    modules |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    allowed = {"__future__", "pathlib", "json", "gzip", "hashlib", "fractions", "zlib"}
    assert all(m in allowed or m.startswith("governance") for m in modules), modules
    assert not any(m.startswith(("governance.broker", "governance.runner", "governance.guard", "governance.audit"))
                   for m in modules)
