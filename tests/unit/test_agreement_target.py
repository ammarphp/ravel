"""an agreement claim carries one target record, and CHECK-IN 1 refuses it otherwise.

Every fixture is synthetic: a supplied reference table on a two-parameter toy lattice.
"""
import json
from copy import deepcopy

import pytest

from ravel.validation import validate_checkin as vc

import intake_sidecar_fixtures as fx

PROMPT = ("Compare the computed expected signal-strength limits of a synthetic toy model "
          "with the supplied reference table on its parameter lattice.")
REFERENCE_BYTES = b'{"synthetic": "reference table"}\n'
PIN = {"locator": "inputs/reference_table.json", "sha256": __import__("hashlib").sha256(REFERENCE_BYTES).hexdigest()}
LATTICE = [[100.0, 10.0], [100.0, 20.0], [200.0, 10.0], [200.0, 20.0]]


def agreement_claim(claim_id="C1", **overrides):
    row = fx.claim(claim_id, kind="agreement", statement="agreement of the toy limits with the supplied table",
                   deliverable={"artifact": "table", "template": None}, level="expected",
                   statistic={"source": "declared", "definition": "relative difference per node",
                              "evidence": [], "secondary": []},
                   comparison={"target": "supplied", "locator": "supplied reference table",
                               "metric": "relative difference", "tolerance": {"max_abs": 0.2}},
                   basis_declared=["supplied_inputs"])
    row.update(deepcopy(overrides))
    return row


def target(claim_id="C1", **overrides):
    row = {
        "claim_id": claim_id,
        "reference": {"kind": "supplied", "locator": "supplied reference table", "pins": [PIN],
                      "recipe_pins": [], "claim_id": None},
        "quantity": {"result": {"name": "mu95", "basis": "signal_strength", "unit": "1"},
                     "reference": {"name": "mu95", "basis": "signal_strength", "unit": "1"}},
        "conversion": None,
        "family": {"reference": "expected"},
        "nodes": {"coordinates": ["m_a", "m_b"], "reference_lattice": deepcopy(LATTICE),
                  "compared": deepcopy(LATTICE[:3])},
        "tolerance_rule": {"metric": "relative difference", "threshold": 0.2, "aggregation": "per_node",
                           "definition": "|r - ref| / ref at every compared node"},
        "noise_model": {"definition": "per-node Monte Carlo statistical spread from replicas", "pin": None},
    }
    row.update(deepcopy(overrides))
    return row


def run(tmp_path, claims=None, targets=None):
    rd = tmp_path / "run"
    claims = claims or [agreement_claim()]
    coverage = [{"obligation_id": "original-request", "by": ["N1", *[c["id"] for c in claims]]}]
    contract, reading, plan = fx.pinned_run(rd, prompt=PROMPT,
                                            plan_overrides={"claims": claims, "coverage": coverage})
    (rd / "inputs/reference_table.json").write_bytes(REFERENCE_BYTES)
    if targets is not None:
        (rd / "inputs/agreement_targets.json").write_text(json.dumps(
            {"schema_version": 1, "kind": "agreement-targets", "targets": targets}))
    return rd, fx.checkin1(plan, reading)


def errors(rd, checkin):
    return vc.validate(checkin, base_dir=str(rd))


def composed(rd, checkin):
    return json.loads(vc.checkin_bytes(checkin, str(rd)))


def test_valid_target_composes_and_validates(tmp_path):
    rd, checkin = run(tmp_path, targets=[target()])
    assert errors(rd, composed(rd, checkin)) == []


def test_agreement_claim_without_target_is_refused_naming_the_record(tmp_path):
    rd, checkin = run(tmp_path)
    errs = errors(rd, composed(rd, checkin))
    assert any("C1" in e and "agreement-target record" in e and "inputs/agreement_targets.json" in e
               for e in errs), errs


def test_uncomposed_checkin_is_refused_too(tmp_path):
    rd, checkin = run(tmp_path, targets=[target()])
    assert any("(agreement_targets)" in e for e in errors(rd, checkin))


def test_observed_result_against_expected_reference_is_refused(tmp_path):
    rd, checkin = run(tmp_path, claims=[agreement_claim(level="observed")], targets=[target()])
    errs = errors(rd, composed(rd, checkin))
    assert any("C1" in e and "observed" in e and "expected" in e and "family" in e for e in errs), errs


def test_cross_section_to_signal_strength_without_conversion_is_refused(tmp_path):
    quantity = {"result": {"name": "sigma95", "basis": "cross_section", "unit": "fb"},
                "reference": {"name": "mu95", "basis": "signal_strength", "unit": "1"}}
    rd, checkin = run(tmp_path, targets=[target(quantity=quantity)])
    errs = errors(rd, composed(rd, checkin))
    assert any("C1" in e and "conversion" in e and "cross_section" in e and "signal_strength" in e
               for e in errs), errs
    conversion = {"from": "cross_section", "to": "signal_strength",
                  "definition": "mu = sigma95 / sigma_model at each node", "pins": [PIN]}
    rd2, checkin2 = run(tmp_path / "declared", targets=[target(quantity=quantity, conversion=conversion)])
    assert errors(rd2, composed(rd2, checkin2)) == []


def test_unit_change_needs_a_conversion(tmp_path):
    quantity = {"result": {"name": "sigma95", "basis": "cross_section", "unit": "pb"},
                "reference": {"name": "sigma95", "basis": "cross_section", "unit": "fb"}}
    rd, checkin = run(tmp_path, targets=[target(quantity=quantity)])
    assert any("conversion" in e for e in errors(rd, composed(rd, checkin)))


def test_published_reproduction_without_recipe_pins_is_refused(tmp_path):
    claim = agreement_claim(comparison={"target": "published_table", "locator": "table T1",
                                        "metric": "relative difference", "tolerance": {"max_abs": 0.2}})
    reference = {"kind": "published_reproduction", "locator": "table T1", "pins": [PIN],
                 "recipe_pins": [], "claim_id": None}
    noise = {"definition": "per-node statistical spread", "pin": PIN}
    rd, checkin = run(tmp_path, claims=[claim], targets=[target(reference=reference, noise_model=noise)])
    errs = errors(rd, composed(rd, checkin))
    assert any("C1" in e and "published_reproduction" in e and "recipe pins" in e for e in errs), errs
    reference["recipe_pins"] = [PIN]
    rd2, checkin2 = run(tmp_path / "pinned", claims=[claim], targets=[target(reference=reference, noise_model=noise)])
    assert errors(rd2, composed(rd2, checkin2)) == []


def test_node_coverage_is_in_checkin_bytes(tmp_path):
    rd, checkin = run(tmp_path, targets=[target()])
    raw = vc.checkin_bytes(checkin, str(rd))
    row = json.loads(raw)["sections"]["agreement_targets"]["claims"][0]
    assert row["node_coverage"] == {"reference_nodes": 4, "compared_nodes": 3, "covered_nodes": 3,
                                    "fraction": 0.75, "missing": [[200.0, 20.0]], "off_lattice": []}
    assert b'"node_coverage"' in raw


def test_off_lattice_comparison_is_refused(tmp_path):
    nodes = {"coordinates": ["m_a", "m_b"], "reference_lattice": LATTICE, "compared": [[150.0, 10.0]]}
    rd, checkin = run(tmp_path, targets=[target(nodes=nodes)])
    assert any("off the reference lattice" in e for e in errors(rd, composed(rd, checkin)))


def test_two_comparators_on_one_claim_are_refused(tmp_path):
    second = target(reference={"kind": "supplied", "locator": "second table", "pins": [PIN],
                               "recipe_pins": [], "claim_id": None})
    rd, checkin = run(tmp_path, targets=[target(), second])
    errs = errors(rd, composed(rd, checkin))
    assert any("C1" in e and "two claims" in e for e in errs), errs


def test_two_comparators_as_two_claims_validate(tmp_path):
    claims = [agreement_claim("C1"), agreement_claim("C2")]
    rd, checkin = run(tmp_path, claims=claims, targets=[target("C1"), target("C2")])
    rendered = composed(rd, checkin)
    assert errors(rd, rendered) == []
    assert [r["claim_id"] for r in rendered["sections"]["agreement_targets"]["claims"]] == ["C1", "C2"]


def test_target_for_an_undeclared_claim_is_refused(tmp_path):
    rd, checkin = run(tmp_path, targets=[target(), target("C9")])
    assert any("C9" in e and "not an agreement claim" in e for e in errors(rd, composed(rd, checkin)))


def test_reference_kind_must_match_the_claim_comparison(tmp_path):
    reference = {"kind": "published_result", "locator": "table T1", "pins": [PIN], "recipe_pins": [],
                 "claim_id": None}
    rd, checkin = run(tmp_path, targets=[target(reference=reference)])
    assert any("published_result" in e and "supplied" in e for e in errors(rd, composed(rd, checkin)))


def test_tolerance_metric_must_match_the_claim(tmp_path):
    rule = {"metric": "absolute difference", "threshold": 0.2, "aggregation": "per_node", "definition": "x"}
    rd, checkin = run(tmp_path, targets=[target(tolerance_rule=rule)])
    assert any("metric" in e for e in errors(rd, composed(rd, checkin)))


def test_missing_noise_model_is_refused_by_schema(tmp_path):
    row = target()
    del row["noise_model"]
    rd, checkin = run(tmp_path, targets=[row])
    assert any("noise_model" in e for e in errors(rd, composed(rd, checkin)))


def test_changed_target_after_composition_is_refused(tmp_path):
    rd, checkin = run(tmp_path, targets=[target()])
    rendered = composed(rd, checkin)
    path = rd / "inputs/agreement_targets.json"
    record = json.loads(path.read_text())
    record["targets"][0]["tolerance_rule"]["threshold"] = 0.5
    path.write_text(json.dumps(record))
    assert any("(agreement_targets)" in e for e in errors(rd, rendered))


def test_run_without_agreement_claims_has_no_section(tmp_path):
    claim = fx.claim(statement="the expected exclusion status of the toy point",
                     comparison={"target": "none", "locator": None, "metric": None, "tolerance": None})
    rd, checkin = run(tmp_path, claims=[claim])
    rendered = composed(rd, checkin)
    assert errors(rd, rendered) == []
    assert "agreement_targets" not in rendered["sections"]


# ---- CJ-F: the compared result's family as the plan drafter produces it ----------------------

DRAFT_PROMPT = ("Reproduce the observed 95% CLs exclusion contour of a synthetic toy model and compare it "
                "with the published figure.")


def drafted_claims(prompt=DRAFT_PROMPT):
    from ravel.workflow import request_plan, request_reading
    plan = request_plan.draft(request_reading.document(prompt), {"prompt": prompt})
    return plan["claims"]


def published_target(claim_id, family, **overrides):
    reference = {"kind": "published_result", "locator": "published figure", "pins": [PIN],
                 "recipe_pins": [], "claim_id": None}
    overrides.setdefault("noise_model", {"definition": "per-node statistical spread", "pin": PIN})
    return target(claim_id, reference=reference, family={"reference": family},
                  tolerance_rule={"metric": "relative difference", "threshold": 0.2, "aggregation": "per_node",
                                  "definition": "|r - ref| / ref at every compared node"}, **overrides)


def drafted_run(tmp_path, family):
    claims = drafted_claims()
    agreement = [c for c in claims if c["kind"] == "agreement"]
    limits = [c for c in claims if c["kind"] == "exclusion"]
    assert agreement and all(c["level"] == "not_applicable" for c in agreement)
    assert [c["level"] for c in limits] == ["observed"]
    targets = [published_target(c["id"], family) for c in agreement]
    return run(tmp_path, claims=claims, targets=targets)


def test_drafted_observed_limit_against_expected_reference_is_refused(tmp_path):
    rd, checkin = drafted_run(tmp_path, "expected")
    errs = errors(rd, composed(rd, checkin))
    assert any("observed-family result" in e and "expected-family reference" in e for e in errs), errs


def test_drafted_observed_limit_against_not_applicable_reference_is_refused(tmp_path):
    rd, checkin = drafted_run(tmp_path, "not_applicable")
    errs = errors(rd, composed(rd, checkin))
    assert any("observed-family result" in e for e in errs), errs


def test_drafted_observed_limit_against_observed_reference_has_no_family_error(tmp_path):
    rd, checkin = drafted_run(tmp_path, "observed")
    errs = errors(rd, composed(rd, checkin))
    assert not any("family" in e for e in errs), errs


def test_ambiguous_compared_family_requires_the_compared_claim(tmp_path):
    claims = [agreement_claim("C1", level="not_applicable",
                              comparison={"target": "published_figure", "locator": "figure",
                                          "metric": "relative difference", "tolerance": None}),
              fx.claim("C2", level="observed"), fx.claim("C3", level="expected")]
    rd, checkin = run(tmp_path, claims=claims, targets=[published_target("C1", "observed")])
    errs = errors(rd, composed(rd, checkin))
    assert any("compares" in e and "C2" in e and "C3" in e for e in errs), errs
    rd2, checkin2 = run(tmp_path / "named", claims=claims,
                        targets=[published_target("C1", "observed", compares="C2")])
    assert not any("family" in e for e in errors(rd2, composed(rd2, checkin2)))
    rd3, checkin3 = run(tmp_path / "wrong", claims=claims,
                        targets=[published_target("C1", "observed", compares="C3")])
    assert any("expected-family result" in e for e in errors(rd3, composed(rd3, checkin3)))


def test_drafter_emits_no_agreement_claim_without_a_target():
    assert [c["id"] for c in drafted_claims() if c["kind"] == "agreement"
            and c["comparison"]["target"] in (None, "none")] == []


# ---- CJ-F: pins, tolerance, quantity identity and noise model --------------------------------

def test_missing_or_mismatched_run_relative_pin_is_refused(tmp_path):
    missing = {"locator": "inputs/absent_table.json", "sha256": "b" * 64}
    reference = {"kind": "supplied", "locator": "supplied reference table", "pins": [missing],
                 "recipe_pins": [], "claim_id": None}
    rd, checkin = run(tmp_path, targets=[target(reference=reference)])
    assert any("inputs/absent_table.json" in e and "missing" in e for e in errors(rd, composed(rd, checkin)))
    wrong = {"locator": "inputs/reference_table.json", "sha256": "c" * 64}
    reference["pins"] = [wrong]
    rd2, checkin2 = run(tmp_path / "wrong", targets=[target(reference=reference)])
    assert any("inputs/reference_table.json" in e and "sha256" in e for e in errors(rd2, composed(rd2, checkin2)))


def test_remote_pin_is_listed_as_unverified(tmp_path):
    remote = {"locator": "https://example.org/synthetic/table.json", "sha256": "d" * 64}
    reference = {"kind": "supplied", "locator": "supplied reference table", "pins": [remote],
                 "recipe_pins": [], "claim_id": None}
    rd, checkin = run(tmp_path, targets=[target(reference=reference)])
    doc = composed(rd, checkin)
    assert errors(rd, doc) == []
    row = doc["sections"]["agreement_targets"]["claims"][0]
    assert row["unverified_pins"] == ["https://example.org/synthetic/table.json"]


def test_tolerance_rule_must_match_the_plan_tolerance(tmp_path):
    loose = {"metric": "relative difference", "threshold": 0.9, "aggregation": "median_abs",
             "definition": "median |r - ref| / ref"}
    rd, checkin = run(tmp_path, targets=[target(tolerance_rule=loose)])
    assert any("tolerance" in e and "0.2" in e for e in errors(rd, composed(rd, checkin)))
    same = {"metric": "relative difference", "threshold": 0.2, "aggregation": "max_abs",
            "definition": "max |r - ref| / ref"}
    rd2, checkin2 = run(tmp_path / "same", targets=[target(tolerance_rule=same)])
    assert errors(rd2, composed(rd2, checkin2)) == []


def test_different_quantity_names_need_a_conversion(tmp_path):
    quantity = {"result": {"name": "mu95", "basis": "signal_strength", "unit": "1"},
                "reference": {"name": "mu68", "basis": "signal_strength", "unit": "1"}}
    rd, checkin = run(tmp_path, targets=[target(quantity=quantity)])
    assert any("mu95" in e and "mu68" in e for e in errors(rd, composed(rd, checkin)))


def test_published_reference_needs_a_pinned_noise_model(tmp_path):
    claims = [agreement_claim(comparison={"target": "published_table", "locator": "table T1",
                                          "metric": "relative difference", "tolerance": {"max_abs": 0.2}})]
    row = published_target("C1", "expected", noise_model={"definition": "tbd", "pin": None})
    rd, checkin = run(tmp_path, claims=claims, targets=[row])
    assert any("noise model" in e for e in errors(rd, composed(rd, checkin)))


def test_partial_lattice_coverage_is_flagged(tmp_path):
    rd, checkin = run(tmp_path, targets=[target()])
    row = composed(rd, checkin)["sections"]["agreement_targets"]["claims"][0]
    assert any("3 of 4" in flag for flag in row["flags"]), row


# ---- the compared family must resolve, and the plan tolerance must bound the claim ----

def test_not_applicable_reference_without_a_compared_family_is_refused(tmp_path):
    claims = [agreement_claim(level="not_applicable")]
    rd, checkin = run(tmp_path, claims=claims, targets=[target(family={"reference": "not_applicable"})])
    errs = errors(rd, composed(rd, checkin))
    assert any("family" in e and "unresolved" in e for e in errs), errs


def test_published_reference_against_a_familyless_compared_claim_is_refused(tmp_path):
    claims = [agreement_claim("C1", level="not_applicable",
                              comparison={"target": "published_figure", "locator": "figure",
                                          "metric": "relative difference", "tolerance": {"max_abs": 0.2}}),
              fx.claim("C2", level="not_applicable")]
    rd, checkin = run(tmp_path, claims=claims,
                      targets=[published_target("C1", "not_applicable", compares="C2")])
    errs = errors(rd, composed(rd, checkin))
    assert any("family" in e and "unresolved" in e for e in errs), errs


def test_named_compared_claim_decides_the_family_over_the_claims_own_level(tmp_path):
    claims = [agreement_claim("C1", level="expected",
                              comparison={"target": "published_figure", "locator": "figure",
                                          "metric": "relative difference", "tolerance": {"max_abs": 0.2}}),
              fx.claim("C2", level="observed")]
    rd, checkin = run(tmp_path, claims=claims, targets=[published_target("C1", "expected", compares="C2")])
    errs = errors(rd, composed(rd, checkin))
    assert any("C2" in e and "observed" in e and "expected" in e for e in errs), errs


def test_plan_tolerance_with_extra_keys_is_still_reconciled(tmp_path):
    claims = [agreement_claim(comparison={"target": "supplied", "locator": "supplied reference table",
                                          "metric": "relative difference",
                                          "tolerance": {"max_abs": 0.01, "note": "strict"}})]
    rd, checkin = run(tmp_path, claims=claims, targets=[target()])
    errs = errors(rd, composed(rd, checkin))
    assert any("tolerance" in e and "0.01" in e for e in errs), errs
    vague = [agreement_claim(comparison={"target": "supplied", "locator": "supplied reference table",
                                         "metric": "relative difference", "tolerance": {"note": "close"}})]
    rd2, checkin2 = run(tmp_path / "vague", claims=vague, targets=[target()])
    assert any("tolerance" in e and "aggregation" in e for e in errors(rd2, composed(rd2, checkin2)))


def test_drafted_null_tolerance_is_refused_for_a_certified_claim(tmp_path):
    rd, checkin = drafted_run(tmp_path, "observed")
    agreement = [c["id"] for c in drafted_claims() if c["kind"] == "agreement"]
    assert all(row["fidelity"] == "of record" for row in checkin["sections"]["claims"] if row["id"] in agreement)
    errs = errors(rd, composed(rd, checkin))
    assert any(cid in e and "tolerance" in e and "certified" in e for cid in agreement for e in errs), errs


def test_drafted_null_tolerance_is_flagged_for_an_uncertified_claim(tmp_path):
    rd, checkin = drafted_run(tmp_path, "observed")
    agreement = [c["id"] for c in drafted_claims() if c["kind"] == "agreement"]
    for row in checkin["sections"]["claims"]:
        if row["id"] in agreement:
            row.update(fidelity="uncertified: no executed comparison yet",
                       explanation="The agreement is planned but no comparison has been executed against the figure.",
                       certifiable_route="Declare a plan tolerance and execute the comparison.")
            checkin["sections"]["v"].append({"id": f"F{len(checkin['sections']['v']) + 1}",
                                             "text": f"{row['id']}: uncertified: no executed comparison yet"})
    doc = composed(rd, checkin)
    assert not any("tolerance" in e and "certified" in e for e in errors(rd, doc))
    rows = doc["sections"]["agreement_targets"]["claims"]
    assert all(any("no tolerance" in f for f in row["flags"]) for row in rows)
