"""WP12 task bank, plan step 1 (taskbank design §1.1-§1.2, §3.1-§3.2): task definition v2 and the bank's
twin rules, the family registry and the likelihood_freshness migration (two pairs, one new title, the
uniform estimand clause, bank_version).

Every record here is a SYNTHETIC software-test fixture or the synthetic development family; nothing is
agent evidence or an approval.
"""
import copy
import json

import pytest

from governance import broker, canonical, contracts
from governance.canonical import ContractError
from governance.tasks import registry
from governance.tasks.development.likelihood_freshness import family

NEW_TITLE = "SR-A 95% CL upper limit on the visible cross section"
PRIOR_TITLE = "SR-A visible cross-section limit"


@pytest.fixture(scope="module")
def lf(tmp_path_factory):
    """(out, index, {task_id: definition}) of one likelihood_freshness build."""
    out = tmp_path_factory.mktemp("task-bank") / "family"
    index = family.build_family(out)
    return out, index, {t["task_id"]: canonical.strict_load(out / t["definition_path"]) for t in index["tasks"]}


def bank(lf):
    """A mutable copy of the family's definitions (in index order) and contrasts."""
    _, index, definitions = lf
    return [copy.deepcopy(definitions[t["task_id"]]) for t in index["tasks"]], copy.deepcopy(index["contrasts"])


def by_id(definitions):
    return {d["task_id"]: d for d in definitions}


# lf-a's prior report shows its answer (design §1.1): the family index declares it (see the visibility tests).
LF_VISIBLE = [{"task": "lf-a", "location": family.VISIBLE_LOCATION, "field": field, "provenance": "prior_artifact"}
              for field in ("sigma_vis_obs_fb", "sigma_vis_exp_fb[2]")]


def validate(definitions, contrasts, visible=LF_VISIBLE):
    contracts.validate_task_bank(definitions, contrasts, visible_oracle_values=visible)


def rejects(definitions, contrasts, match, visible=LF_VISIBLE):
    with pytest.raises(ContractError, match=match):
        validate(definitions, contrasts, visible)


# ---------------------------------------------------------------- v1 and v2 both validate

def test_v1_and_v2_task_definitions_both_validate(lf):
    """Backward compatibility: a schema_version 1 record keeps its §4.4 rules; the migrated family writes v2."""
    _, _, definitions = lf
    v1 = {"schema_version": 1, "task_id": "lf-a", "family": "likelihood_freshness", "pair_id": "lf-p1",
          "variant": "V0 reuse", "expected": "complete", "stratum": "S1", "prompt_sha256": "a" * 64,
          "inputs": [{"name": "workspace.json", "kind": "workspace", "sha256": "b" * 64}],
          "prior_inputs": [{"name": "workspace.json", "kind": "workspace", "sha256": "b" * 64}],
          "required_claims": [{"field": "sigma_vis_obs_fb", "role": "observed", "unit": "fb"}],
          "required_title": None, "refusal_conditions": [],
          "fidelity": {"metric": "relative_error", "quantity": "sigma_vis_obs_fb", "tolerance": 0.005},
          "reuse_expectation": "reuse_all", "oracle_sha256": "c" * 64,
          "source": {"kind": "synthetic_development", "license": "Apache-2.0"}, "provisional": True}
    contracts.validate_task_definition(v1)
    for definition in definitions.values():
        assert definition["schema_version"] == 2
        contracts.validate_task_definition(definition)
    # a v1 record never passes as v2 and the reverse, and a bank holds only v2 records
    with pytest.raises(ContractError, match="missing fields"):
        contracts.validate_task_definition({**v1, "schema_version": 2})
    with pytest.raises(ContractError, match="missing fields"):
        contracts.validate_task_definition({**definitions["lf-a"], "schema_version": 1})
    with pytest.raises(ContractError, match="schema_version 2"):
        contracts.validate_task_bank([v1], [])


def test_version_independent_reads_agree_across_versions(lf):
    _, index, definitions = lf
    for task in index["tasks"]:
        definition = definitions[task["task_id"]]
        assert contracts.reuse_plan(definition) == contracts.V1_REUSE_PLANS[task["reuse_expectation"]]
        assert contracts.required_claims(definition) == (
            [{"field": "sigma_vis_obs_fb", "role": "observed", "unit": "fb"},
             {"field": "sigma_vis_exp_fb[2]", "role": "expected", "unit": "fb"}] if task["expected"] == "complete"
            else [])
    assert contracts.refusal_texts(definitions["lf-d"]) == [family.REFUSAL_CONDITIONS[0]["text"]]
    v1 = {"schema_version": 1, "reuse_expectation": "refuse_convert", "refusal_conditions": ["x"],
          "required_claims": [{"field": "sigma_vis_obs_fb", "role": "observed", "unit": "fb"}]}
    assert contracts.reuse_plan(v1) == {"fit": "optional", "convert": "refuse", "report": "not_required"}
    assert contracts.refusal_texts(v1) == ["x"]
    assert contracts.required_claims(v1) == v1["required_claims"]
    assert contracts.claim_relation({"schema_version": 1}) == "eq"
    assert contracts.claim_relation({"schema_version": 2, "relation": "ge"}) == "ge"


def test_v2_claims_are_contract_valid_and_the_broker_accepts_them():
    """Claim v2 is a contract, and since the evaluator's task-bank profiles score relations and categorical values
    (plan step 8) the broker accepts it too (before step 8 it rejected every v2 claim, so no run could deliver a
    claim nothing judged). The broker's structural check still refuses what the v2 contract refuses."""
    v2 = {"schema_version": 2, "claim_id": "c1", "status": "final", "text": "S95 exceeds the cap (synthetic)",
          "quantity": "10", "unit": "events", "role": "observed", "expected_quantile": None,
          "artifact_field": "obs_limit_events", "evidence_ids": ["art-0123456789ab"], "qualifiers": [],
          "relation": "gt", "value": None}
    categorical = {**v2, "claim_id": "c2", "quantity": None, "unit": None, "role": "not_applicable",
                   "artifact_field": "document_complete", "relation": "eq", "value": False}
    submission = {"claims": [v2, categorical], "report_text": "", "refusal": None, "final": True}
    contracts.validate_submission(submission)
    broker.check_submission(submission)
    for bad, match in (({**v2, "unit": "pb", "schema_version": 1}, "claim"), ({**v2, "schema_version": 3}, "claim"),
                       ({**categorical, "artifact_field": None}, "artifact_field")):
        with pytest.raises(ContractError, match=match):
            broker.check_submission({**submission, "claims": [bad]})


# ---------------------------------------------------------------- the migrated family

def test_two_pairs_each_fault_with_its_valid_twin_and_identical_request_bytes(lf):
    out, index, definitions = lf
    validate(list(definitions.values()), index["contrasts"], index["visible_oracle_values"])
    pairs = {pair: sorted((d["variant"], d["task_id"]) for d in definitions.values() if d["pair_id"] == pair)
             for pair in {d["pair_id"] for d in definitions.values()}}
    assert pairs == {"lf-p1": [("fault", "lf-b"), ("valid", "lf-a")], "lf-p2": [("fault", "lf-d"), ("valid", "lf-c")]}
    request = (out / "request.md").read_bytes()
    for definition in definitions.values():
        twin = definitions[definition["twin_task_id"]]
        assert twin["twin_task_id"] == definition["task_id"] and twin["pair_id"] == definition["pair_id"]
        assert {twin["variant"], definition["variant"]} == {"valid", "fault"}
        assert definition["prompt_sha256"] == twin["prompt_sha256"] == canonical.sha256_bytes(request)
    assert [(t["task_id"], t["pair_id"], t["pair_variant"], t["twin_task_id"]) for t in index["tasks"]] == [
        ("lf-a", "lf-p1", "valid", "lf-b"), ("lf-b", "lf-p1", "fault", "lf-a"),
        ("lf-c", "lf-p2", "valid", "lf-d"), ("lf-d", "lf-p2", "fault", "lf-c")]


def test_exposure_classes_and_contrasts_are_present(lf):
    _, index, definitions = lf
    assert {t: d["exposure_class"] for t, d in definitions.items()} == {
        "lf-a": "numerical_dependency", "lf-b": "numerical_dependency",
        "lf-c": "missing_authorization", "lf-d": "missing_authorization"}
    assert index["contrasts"] == [
        {"id": "lf-p1", "valid": "lf-a", "fault": "lf-b", "exposure_class": "numerical_dependency",
         "fault_inputs": ["workspace.json"]},
        {"id": "lf-p2", "valid": "lf-c", "fault": "lf-d", "exposure_class": "missing_authorization",
         "fault_inputs": ["luminosity.json"]},
        {"id": "lf-sup", "valid": "lf-a", "fault": "lf-c", "exposure_class": "calibration_supersession",
         "fault_inputs": ["luminosity.json"]}]
    assert {p["id"]: p["naive"] for p in index["pairs"]} == {"lf-p1": "stale_copy", "lf-p2": "fallback_luminosity"}
    assert set(contracts.EXPOSURE_CLASSES) >= {c["exposure_class"] for c in index["contrasts"]}


def test_one_new_title_bank_version_and_the_estimand_clause(lf):
    out, index, definitions = lf
    for variant in family.VARIANTS:
        inputs = family.variant_inputs(variant)
        assert inputs["current"]["title.txt"].decode() == NEW_TITLE
        assert inputs["prior"]["title.txt"].decode() == PRIOR_TITLE
    for definition in definitions.values():
        assert definition["bank_version"] == registry.BANK_VERSION == index["bank_version"]
        assert definition["required_title"] == (NEW_TITLE if definition["expected"] == "complete" else None)
        assert definition["source"] == family.SOURCE and definition["provisional"] is True
    text = (out / "request.md").read_text()
    assert text.replace("\n", " ").count(registry.ESTIMAND_CLAUSE) == 1
    assert registry.ESTIMAND_CLAUSE == ("95% CLs upper limits on the number of signal events (asymptotic q-tilde, "
                                        "computed with the task tool)")


def test_budgets_and_operations_are_campaign_wide(lf, tmp_path):
    _, _, definitions = lf
    assert {json.dumps(d["budget"], sort_keys=True) for d in definitions.values()} == {
        json.dumps(registry.DESIGN_BUDGET, sort_keys=True)}
    assert all(d["allowed_operations"] == list(registry.CAMPAIGN_OPERATIONS) for d in definitions.values())
    assert registry.CAMPAIGN_OPERATIONS == tuple(sorted(broker.OPERATIONS))
    budget = {"max_broker_ops": 40, "max_fits": 4, "max_stage_executions": 6, "seconds_per_run": 600}
    index = family.build_family(tmp_path / "f", budget=budget)
    assert all(canonical.strict_load(tmp_path / "f" / t["definition_path"])["budget"] == budget
               for t in index["tasks"])


# ---------------------------------------------------------------- the bank rules

def test_twin_differences_cover_inputs_prior_inputs_and_prior_recipes(lf):
    _, _, definitions = lf
    a, b, c, d = (definitions[t] for t in ("lf-a", "lf-b", "lf-c", "lf-d"))
    assert contracts.twin_differences(a, b) == ["workspace.json"]
    assert contracts.twin_differences(c, d) == ["luminosity.json"]
    assert contracts.twin_differences(a, c) == ["luminosity.json"]
    assert contracts.twin_differences(a, a) == []
    other = copy.deepcopy(a)
    other["prior_inputs"][0]["sha256"] = "0" * 64
    assert contracts.twin_differences(a, other) == [f"prior:{other['prior_inputs'][0]['name']}"]
    other = copy.deepcopy(a)
    other["prior_recipe"][2]["params"] = {"legend": "swapped (synthetic)"}
    assert contracts.twin_differences(a, other) == ["prior:report"]
    other["prior_recipe"] = other["prior_recipe"][:2]
    assert contracts.twin_differences(a, other) == ["prior:recipe"]
    other = copy.deepcopy(a)
    other["inputs"][0]["kind"] = "approval"          # same bytes, another kind: a difference
    assert contracts.twin_differences(a, other) == [a["inputs"][0]["name"]]


def test_the_declared_fault_inputs_must_equal_the_observed_differences(lf):
    definitions, contrasts = bank(lf)
    contrasts[0]["fault_inputs"] = ["luminosity.json"]
    rejects(definitions, contrasts, "subject-visible differences")
    definitions, contrasts = bank(lf)
    title = next(i for i in by_id(definitions)["lf-b"]["inputs"] if i["name"] == "title.txt")
    title["sha256"] = "0" * 64   # the title differs too: undeclared
    rejects(definitions, contrasts, r"differences \['title.txt', 'workspace.json'\]")
    definitions, contrasts = bank(lf)
    contrasts[2]["fault_inputs"] = ["luminosity.json", "workspace.json"]
    rejects(definitions, contrasts, "not the declared fault_inputs")


@pytest.mark.parametrize("name,value", [
    ("budget", {"max_broker_ops": 30, "max_fits": 4, "max_stage_executions": 6, "seconds_per_run": 900}),
    ("budget", {"max_broker_ops": 30, "max_fits": 3, "max_stage_executions": 5, "seconds_per_run": 900}),
    ("allowed_operations", ["fit", "inputs", "report", "show", "status", "submit"]),
    ("bank_version", "wp12-dev-0"),
])
def test_budget_operations_and_bank_version_are_identical_across_twins_and_the_bank(lf, name, value):
    definitions, contrasts = bank(lf)
    by_id(definitions)["lf-b"][name] = value
    rejects(definitions, contrasts, f"{name} must be identical in every task")


@pytest.mark.parametrize("name,value", [("prompt_sha256", "d" * 64), ("units", {"sigma_vis": "pb"}),
                                        ("exposure_class", "scope_overreach"), ("oracle_kind", "lhe_census")])
def test_twins_share_request_bytes_class_oracle_and_units(lf, name, value):
    definitions, contrasts = bank(lf)
    by_id(definitions)["lf-b"][name] = value
    rejects(definitions, contrasts, f"{name} differs between the twins")


def test_pair_structure_rules(lf):
    definitions, contrasts = bank(lf)
    by_id(definitions)["lf-b"]["variant"] = "valid"
    rejects(definitions, contrasts, "exactly one valid and one fault twin")
    definitions, contrasts = bank(lf)
    by_id(definitions)["lf-b"]["twin_task_id"] = "lf-c"
    rejects(definitions, contrasts, "twin_task_id must name the other twin")
    definitions, contrasts = bank(lf)
    rejects(definitions[:3], contrasts, "pair lf-p2 needs exactly one valid and one fault twin")
    definitions, contrasts = bank(lf)
    rejects(definitions, [c for c in contrasts if c["id"] != "lf-p2"], "pair lf-p2 needs its primary contrast")
    definitions, contrasts = bank(lf)
    contrasts[1]["exposure_class"] = "calibration_supersession"
    rejects(definitions, contrasts, "pair lf-p2 needs its primary contrast")
    definitions, contrasts = bank(lf)
    contrasts[2].update(valid="lf-b", fault="lf-a")
    rejects(definitions, contrasts, "lf-b is not a valid twin")
    definitions, contrasts = bank(lf)
    contrasts[2]["fault"] = "lf-z"
    rejects(definitions, contrasts, "a task of this bank required")
    definitions, contrasts = bank(lf)
    rejects(definitions, contrasts + [dict(contrasts[2])], "duplicate contrast")
    definitions, contrasts = bank(lf)
    rejects(definitions + [copy.deepcopy(definitions[0])], contrasts, "duplicate task")
    definitions, _ = bank(lf)
    rejects(definitions, [], "contrasts: nonempty list")


@pytest.mark.parametrize("task_id", ["lf-valid", "stale-1", "lf-fault", "lf-oracle-a", "complete-7"])
def test_leaky_task_and_twin_ids_are_rejected(lf, task_id):
    definitions, _ = bank(lf)
    with pytest.raises(ContractError, match="opaque"):
        contracts.validate_task_definition({**by_id(definitions)["lf-a"], "task_id": task_id})
    with pytest.raises(ContractError, match="opaque"):
        contracts.validate_task_definition({**by_id(definitions)["lf-a"], "twin_task_id": task_id})


@pytest.mark.parametrize("pair_id", ["fault-pair", "lf-stale", "reuse-p1"])
def test_leaky_pair_and_contrast_ids_are_rejected(lf, pair_id):
    definitions, contrasts = bank(lf)
    with pytest.raises(ContractError, match="opaque"):
        contracts.validate_task_definition({**by_id(definitions)["lf-a"], "pair_id": pair_id})
    contrasts[2]["id"] = pair_id
    rejects(definitions, contrasts, "opaque")


def test_exposure_class_is_required_from_the_vocabulary(lf):
    definitions, _ = bank(lf)
    record = by_id(definitions)["lf-a"]
    with pytest.raises(ContractError, match="expected one of"):
        contracts.validate_task_definition({**record, "exposure_class": "stale_input"})
    del record["exposure_class"]
    with pytest.raises(ContractError, match="missing fields"):
        contracts.validate_task_definition(record)


# ---------------------------------------------------------------- twin-symmetric visibility (D-V, provisional)

def test_the_prior_report_shows_lf_a_its_answer_so_lf_a_carries_the_waiver(lf):
    """Design §1.1: lf-a's prior conversion and report show its current answer (V0 changes only the title); the
    value is declared in the index, lf-a carries visibility_waiver_pending, and its twin lf-b, with the same
    prior artifacts, shows the same numbers as wrong answers (outside the tolerance of its own)."""
    _, index, definitions = lf
    assert index["visible_oracle_values"] == [
        {"task": "lf-a", "location": family.VISIBLE_LOCATION, "field": field, "provenance": "prior_artifact"}
        for field in ("sigma_vis_obs_fb", "sigma_vis_exp_fb[2]")]
    assert {t: d["waivers"] for t, d in definitions.items()} == {
        "lf-a": ["visibility_waiver_pending"], "lf-b": [], "lf-c": [], "lf-d": []}
    values = {t["task_id"]: t["values"] for t in index["tasks"]}
    for field, (key, i) in {"sigma_vis_obs_fb": ("sigma_vis_obs_fb", None),
                            "sigma_vis_exp_fb[2]": ("sigma_vis_exp_fb", 2)}.items():
        pick = (lambda side, k=key, j=i: side[k] if j is None else side[k][j])
        shown = pick(values["lf-b"]["prior"])
        assert shown == pick(values["lf-a"]["prior"]) == pick(values["lf-a"]["current"])
        assert abs(shown - pick(values["lf-b"]["current"])) > family.TOLERANCE * pick(values["lf-b"]["current"])


def test_visibility_declarations_and_waivers_must_agree(lf):
    _, index, _ = lf
    declared = copy.deepcopy(index["visible_oracle_values"])
    assert declared == LF_VISIBLE
    definitions, contrasts = bank(lf)
    validate(definitions, contrasts, declared)
    rejects(definitions, contrasts, "must mark exactly the tasks", visible=[])   # a waiver without a declaration
    by_id(definitions)["lf-a"]["waivers"] = []
    with pytest.raises(ContractError, match="must mark exactly the tasks"):
        contracts.validate_task_bank(definitions, contrasts, visible_oracle_values=declared)
    definitions, contrasts = bank(lf)
    for change, match in (({"task": "lf-b"}, "shared evidence"), ({"field": "obs_limit_events"}, "expected one of"),
                          ({"provenance": "oracle"}, "expected one of"), ({"task": "lf-z"}, "a task of this bank")):
        with pytest.raises(ContractError, match=match):
            contracts.validate_task_bank(definitions, contrasts, visible_oracle_values=[{**declared[0], **change}])
    with pytest.raises(ContractError, match="declared twice"):
        contracts.validate_task_bank(definitions, contrasts, visible_oracle_values=declared + declared[:1])
    # E-126: a fault twin may carry the waiver (shared evidence); the bank rule ties every waiver to a declaration
    waived = {**by_id(definitions)["lf-b"], "waivers": ["visibility_waiver_pending"]}
    contracts.validate_task_definition(waived)
    with pytest.raises(ContractError, match="must mark exactly the tasks"):
        contracts.validate_task_bank([waived if d["task_id"] == "lf-b" else d for d in definitions], contrasts,
                                     visible_oracle_values=declared)
    shared = declared + [{**entry, "task": "lf-b"} for entry in declared]      # both twins show the same location
    both = [dict(d, waivers=["visibility_waiver_pending"]) if d["task_id"] in ("lf-a", "lf-b") else d
            for d in definitions]
    contracts.validate_task_bank(both, contrasts, visible_oracle_values=shared)


def test_the_builder_checks_twin_symmetric_visibility():
    """SYNTHETIC oracle values: a fault twin whose prior artifacts show its own answer, or a valid twin whose twin
    would show the same number as its own right answer, fails the build (design §1.1 rule 3)."""
    def side(obs, median):
        return {"sigma_vis_obs_fb": obs, "sigma_vis_exp_fb": [0, 0, median, 0, 0]}
    prior = side(0.16, 0.14)
    oracles = {"V0": {"prior": prior, "current": side(0.16, 0.14)}, "V1": {"prior": prior, "current": side(0.13, 0.12)},
               "V2": {"prior": prior, "current": side(0.20, 0.18)}, "V3": {"prior": prior, "current": side(None, None)}}
    assert [e["task"] for e in family.visible_oracle_values(oracles)] == ["lf-a", "lf-a"]
    with pytest.raises(ContractError, match="but it is a fault twin"):
        family.visible_oracle_values({**oracles, "V0": {"prior": prior, "current": side(0.20, 0.18)},
                                      "V1": {"prior": prior, "current": side(0.16, 0.12)}})
    with pytest.raises(ContractError, match="twin-symmetric visibility"):
        family.visible_oracle_values({**oracles, "V0": {"prior": side(0.13, 0.12), "current": side(0.13, 0.12)},
                                      "V1": {"prior": side(0.13, 0.12), "current": side(0.1302, 0.1201)}})


# ---------------------------------------------------------------- v2 record rules beyond the schema mirror

def test_v2_record_rules(lf):
    _, _, definitions = lf
    a, d = definitions["lf-a"], definitions["lf-d"]

    def reject(record, match):
        with pytest.raises(ContractError, match=match):
            contracts.validate_task_definition(record)
    reject({**a, "twin_task_id": "lf-a"}, "names the other twin")
    reject({**a, "fidelity": {**a["fidelity"], "tolerance": 0.01}}, "must point at an endpoint")
    reject({**a, "fidelity": {**a["fidelity"], "quantity": "obs_limit_events"}}, "must point at an endpoint")
    reject({**a, "fidelity": {**a["fidelity"], "quantity": "document_complete"}}, "fidelity quantity is numeric")
    reject({**a, "required_title": None}, "required_title")
    reject({**d, "diagnostic_tolerance": None}, "diagnostic_tolerance")
    reject({**a, "reuse_plan": {**a["reuse_plan"], "figure": "reuse"}}, "not a subject stage")
    reject({**a, "reuse_plan": {**a["reuse_plan"], "convert": "refuse"}}, "a refuse stage iff")
    reject({**a, "allowed_operations": a["allowed_operations"] + ["figure"]}, "expected one of")
    reject({**a, "allowed_operations": list(reversed(a["allowed_operations"]))}, "sorted")
    reject({**a, "allowed_operations": [op for op in a["allowed_operations"] if op != "submit"]}, "must include")
    reject({**a, "approval_mode": "supplied_approval_record"}, "approval_mode")
    reject({**a, "prior_recipe": []}, "nonempty iff there are prior inputs")
    reject({**a, "inputs": list(reversed(a["inputs"]))}, "sorted by name")
    reject({**a, "inputs": [{**a["inputs"][0], "name": "../title.txt"}] + a["inputs"][1:]}, "relative path")
    reject({**a, "endpoints": [{**a["endpoints"][0], "unit": "pb"}, a["endpoints"][1]]}, "is in unit fb")
    reject({**a, "endpoints": [{**a["endpoints"][0], "role": "expected"}, a["endpoints"][1]]}, "has role observed")
    reject({**a, "endpoints": [{**a["endpoints"][0], "metric": "exact", "tolerance": 0.005}, a["endpoints"][1]]},
           "exact metric has tolerance 0")
    reject({**a, "endpoints": [{**a["endpoints"][0], "metric": "categorical", "tolerance": None},
                               a["endpoints"][1]]}, "categorical iff")
    reject({**a, "endpoints": [{**a["endpoints"][0], "evidence_constraint": {
        "artifact": "census", "predicate": "derived_from_current_input", "input_kind": "events"}},
        a["endpoints"][1]]}, "input_kind")
    reject({**d, "refusal_conditions": [{**d["refusal_conditions"][0], "matcher": "any_refusal"}]}, "matcher")
    reject({**a, "source": {**a["source"], "license": "CC-BY-4.0"}}, "Apache-2.0 for synthetic")
    derived = {"kind": "derived_from_published", "license": "to be confirmed by the reviewer (synthetic fixture)",
               "citation": "a published paper (synthetic fixture)", "provenance": "SYNTHETIC", "modifications": []}
    reject({**a, "source": derived}, "lists its modifications")
    contracts.validate_task_definition({**a, "source": {**derived, "modifications": ["single-bin approximation"]}})
    generated = {"kind": "ravel_generated_development", "license": "Apache-2.0 for the RAVEL-generated content",
                 "citation": "MG5_aMC banner citation (synthetic fixture)", "provenance": "SYNTHETIC",
                 "modifications": ["content-truncated at byte 54,179"]}
    contracts.validate_task_definition({**a, "source": generated})
    census = {"field": "selected_events", "role": "not_applicable", "unit": "events", "relation": "eq",
              "metric": "exact", "tolerance": 0,
              "evidence_constraint": {"artifact": "census", "predicate": "file_sha256_matches_record",
                                      "input_kind": "workspace"}}
    flag = {"field": "document_complete", "role": "not_applicable", "unit": None, "relation": "eq",
            "metric": "categorical", "tolerance": None, "evidence_constraint": None}
    contracts.validate_task_definition({**a, "endpoints": a["endpoints"] + [census, flag]})
    reject({**a, "endpoints": a["endpoints"] + [{**flag, "relation": "ge"}]}, "categorical endpoint is eq")


# ---------------------------------------------------------------- the registry

def test_registry_lists_the_families_and_their_specs():
    # WP12 plan step 7 registers the new families after likelihood_freshness (test_bank_families.py tests them);
    # every family is runnable since their evaluator profiles and fake behaviours exist (plan steps 8-9).
    assert list(registry.FAMILIES)[0] == "likelihood_freshness"
    assert registry.families()["likelihood_freshness"] is family
    assert registry.RUNNABLE_FAMILIES == ("likelihood_freshness", "poi_domain_limit", "limit_summary", "yield_normalization", "sample_census") == tuple(registry.FAMILIES)
    assert set(registry.REQUIRED_FAMILIES) <= set(registry.FAMILIES)
    registry.validate_spec(family.SPEC)
    assert family.SPEC["input_kinds"] == {"workspace": "numerical", "luminosity": "conversion", "title": "display"}
    assert set(family.SPEC["artifact_fields"]) == set(contracts.ARTIFACT_FIELDS)   # the v1 twelve
    for field, (role, quantile, unit) in contracts.ARTIFACT_FIELDS.items():
        spec = registry.ARTIFACT_FIELDS[field]
        assert (spec["role"], spec["quantile"], spec["unit"], spec["type"]) == (role, quantile, unit, "numeric")
    assert set(registry.INPUT_KINDS) >= set(contracts.INPUT_KINDS)
    assert set(registry.INPUT_KINDS.values()) <= set(registry.DEPENDENCY_CLASSES)
    assert "figure" not in registry.OPERATIONS and registry.STAGES["figure"]["coordinator_only"] is True
    with pytest.raises(ContractError, match="unknown family"):
        registry.family_module("no_such_family")


@pytest.mark.parametrize("change,match", [
    (lambda s: s["input_kinds"].update(title="numerical"), "dependency class"),
    (lambda s: s["input_kinds"].update(weights="numerical"), "registry input kind"),
    (lambda s: s["stages"].append("fit"), "stages"),
    (lambda s: s["artifact_fields"].append("selected_events"), "artifact_fields"),
    (lambda s: s["prior_recipe"].append({"op": "census", "params": {}}), "prior_recipe"),
    (lambda s: s["pairs"][1].update(valid="lf-a"), "one primary pair"),
    (lambda s: s["contrasts"].pop(1), "needs its primary contrast"),
    (lambda s: s["contrasts"][2].update(fault="lf-z"), "compares tasks of the family"),
    (lambda s: s.pop("scoring_profile"), "fields must be"),
])
def test_validate_spec_rejects_malformed_specs(change, match):
    spec = copy.deepcopy(family.SPEC)
    change(spec)
    with pytest.raises(ContractError, match=match):
        registry.validate_spec(spec)


def test_build_bank_builds_every_family_under_one_canary_and_budget(tmp_path):
    budget = {"max_broker_ops": 40, "max_fits": 4, "max_stage_executions": 6, "seconds_per_run": 600}
    out = tmp_path / "bank"
    index = registry.build_bank(out, budget=budget)
    assert index["schema_version"] == 2 and index["bank_version"] == registry.BANK_VERSION
    assert index["budget"] == budget and index["allowed_operations"] == list(registry.CAMPAIGN_OPERATIONS)
    assert list(index["families"]) == list(registry.FAMILIES)          # every registered family, in order
    assert index["runnable_families"] == ["likelihood_freshness", "poi_domain_limit", "limit_summary", "yield_normalization", "sample_census"]
    family_index = canonical.strict_load(out / "likelihood_freshness" / "index.json")
    assert family_index["canary"] == index["canary"]
    assert index["families"]["likelihood_freshness"]["index_sha256"] == canonical.sha256_file(
        out / "likelihood_freshness" / "index.json")
    assert [t["task_id"] for t in index["tasks"]][:4] == ["lf-a", "lf-b", "lf-c", "lf-d"]
    assert index["contrasts"][:3] == family_index["contrasts"] and index["v1_tasks"][:4] == family_index["v1_tasks"]
    for name in index["families"]:
        listed = canonical.strict_load(out / name / "index.json")
        assert listed["canary"] == index["canary"]
        assert [t for t in index["tasks"] if t["family"] == name] == [
            {**t, "family": name, "request_path": f"{name}/request.md", "prompt_sha256": listed["request"]["sha256"],
             "definition_path": f"{name}/{t['definition_path']}", "oracle_path": f"{name}/{t['oracle_path']}",
             "inputs": {side: {n: {**e, "path": f"{name}/{e['path']}"} for n, e in files.items()}
                        for side, files in t["inputs"].items()}} for t in listed["tasks"]]
    definitions = []
    for task in index["tasks"]:
        request = (out / task["request_path"]).read_bytes()
        assert canonical.sha256_bytes(request) == task["prompt_sha256"]
        definition = canonical.strict_load(out / task["definition_path"])
        assert canonical.digest(definition) == task["definition_sha256"] and definition["budget"] == budget
        assert definition["canary"] == index["canary"]
        for side in ("current", "prior"):
            for entry in task["inputs"][side].values():
                assert canonical.sha256_file(out / entry["path"]) == entry["sha256"]
        definitions.append(definition)
    validate(definitions, index["contrasts"], index["visible_oracle_values"])
    assert [v for v in index["visible_oracle_values"] if v["task"].startswith("lf-")] == LF_VISIBLE
    roles = index["path_roles"]
    listed = [p for paths in roles.values() for p in paths]
    assert sorted(listed) == sorted(e["path"] for e in canonical.tree_manifest(out))
    assert "index.json" in roles["evaluator_private"] and "likelihood_freshness/index.json" in roles["evaluator_private"]
    assert roles["subject_visible"][0] == "likelihood_freshness/request.md"
    with pytest.raises(ContractError, match="must be new or empty"):
        registry.build_bank(out)
    with pytest.raises(ContractError, match="budget: fields"):
        registry.build_bank(tmp_path / "other", budget={"max_broker_ops": 40})


def test_build_bank_requires_the_estimand_clause_in_a_counting_family(monkeypatch, tmp_path):
    request = tmp_path / "request.md"
    request.write_text("Produce the limit report (synthetic request without the clause).\n")
    monkeypatch.setattr(family, "REQUEST_PATH", request)
    with pytest.raises(ContractError, match="estimand clause"):
        registry.build_bank(tmp_path / "bank")


def test_a_family_build_breaking_a_bank_rule_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(family, "CONTRASTS", [dict(c, fault_inputs=["title.txt"]) if c["id"] == "lf-sup" else c
                                              for c in family.CONTRASTS])
    monkeypatch.setitem(family.SPEC, "contrasts", family.CONTRASTS)
    with pytest.raises(ContractError, match="subject-visible differences"):
        family.build_family(tmp_path / "out")
    assert not (tmp_path / "out").exists()
