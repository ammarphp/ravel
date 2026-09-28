"""Unit tests for the delivery guard (slice design §7).

Every artifact, input and submission below is a SYNTHETIC fixture built for these
tests; no value is a physics result or an oracle output.
"""
import ast
import copy
import json
import re
from pathlib import Path

import pytest

from governance import contracts, guard
from governance.tasks import registry
from governance.canonical import ContractError

GUARD_SOURCE = Path(guard.__file__)
W_OLD, W_NEW = "0a" * 32, "0b" * 32          # synthetic workspace digests
L_OLD, L_NEW = "1a" * 32, "1b" * 32          # synthetic luminosity digests
T_OLD, T_NEW = "2a" * 32, "2b" * 32          # synthetic title digests
SYNTHETIC_FIT_NEW = {"obs_limit_events": 19.46171760332139,
                     "exp_limits_events": [8.670412559311172, 11.722882414269712, 16.465009996534928,
                                           23.332617193622113, 32.052917468162974]}
SYNTHETIC_FIT_OLD = {"obs_limit_events": 23.914072181, "exp_limits_events": [10.02, 13.61, 19.17, 27.3, 37.64]}
STATUS = {"observed": "resolved", "expected": ["resolved"] * 5}


def conversion(fit, lumi):
    return {"synthetic": True, **fit, "limit_status": STATUS, "luminosity_fb": lumi,
            "sigma_vis_obs_fb": fit["obs_limit_events"] / lumi,
            "sigma_vis_exp_fb": [v / lumi for v in fit["exp_limits_events"]]}


def record(handle, kind, derived, content):
    return {"handle": handle, "kind": kind, "content": content, "content_sha256": "f" * 64,
            "derived_from": derived, "produced_by_seq": 1, "origin": "prior"}


def counting_workspace(n_obs, background, uncertainty, poi_cap=256.0):
    """Same JSON as the scoped route's counting workspace (synthetic numbers)."""
    return {"version": "1.0.0", "channels": [{"name": "singlechannel", "samples": [
        {"name": "signal", "data": [1.0], "modifiers": [{"name": "mu", "type": "normfactor", "data": None}]},
        {"name": "background", "data": [background],
         "modifiers": [{"name": "uncorr_bkguncrt", "type": "shapesys", "data": [uncertainty]}]}]}],
        "observations": [{"name": "singlechannel", "data": [n_obs]}],
        "measurements": [{"name": "counting", "config": {"poi": "mu", "parameters": [
            {"name": "mu", "bounds": [[0, poi_cap]], "inits": [min(1, poi_cap / 2)]}]}}]}


ARTIFACTS = {
    "art-00000000000a": record("art-00000000000a", "workspace", {"workspace": W_NEW}, counting_workspace(42.0, 38.0, 5.0)),
    "art-00000000000b": record("art-00000000000b", "luminosity", {"luminosity": L_NEW}, {"luminosity_fb": 117.6}),
    "art-00000000000c": record("art-00000000000c", "title", {"title": T_NEW}, "SR-A synthetic title\n"),
    "art-0000000000f1": record("art-0000000000f1", "fit", {"workspace": W_NEW},
                               {"synthetic": True, **SYNTHETIC_FIT_NEW, "limit_status": STATUS}),
    "art-0000000000c1": record("art-0000000000c1", "conversion", {"workspace": W_NEW, "luminosity": L_NEW},
                               conversion(SYNTHETIC_FIT_NEW, 117.6)),
    "art-0000000000e1": record("art-0000000000e1", "report", {"workspace": W_NEW, "luminosity": L_NEW, "title": T_NEW},
                               {**conversion(SYNTHETIC_FIT_NEW, 117.6), "title": "SR-A synthetic title", "text": "x"}),
    "art-0000000000f0": record("art-0000000000f0", "fit", {"workspace": W_OLD},
                               {"synthetic": True, **SYNTHETIC_FIT_OLD, "limit_status": STATUS}),
    "art-0000000000c0": record("art-0000000000c0", "conversion", {"workspace": W_OLD, "luminosity": L_OLD},
                               conversion(SYNTHETIC_FIT_OLD, 120.0)),
    "art-0000000000c2": record("art-0000000000c2", "conversion", {"workspace": W_NEW, "luminosity": L_OLD},
                               conversion(SYNTHETIC_FIT_NEW, 120.0)),
    "art-0000000000e2": record("art-0000000000e2", "report", {"workspace": W_NEW, "luminosity": L_NEW, "title": T_OLD},
                               {**conversion(SYNTHETIC_FIT_NEW, 117.6), "title": "old synthetic title", "text": "x"}),
}
CURRENT = {"workspace": {"handle": "art-00000000000a", "sha256": W_NEW, "content": counting_workspace(42.0, 38.0, 5.0)},
           "luminosity": {"handle": "art-00000000000b", "sha256": L_NEW, "content": {"luminosity_fb": 117.6}},
           "title": {"handle": "art-00000000000c", "sha256": T_NEW, "content": "SR-A synthetic title\n"}}
NO_LUMINOSITY = {k: v for k, v in CURRENT.items() if k != "luminosity"}


def value(handle, field):
    key, index, *_ = guard.field_spec(field)
    content = ARTIFACTS[handle]["content"]
    return content[key] if index is None else content[key][index]


def claim(cid, field, handles, quantity=None, **overrides):
    key, index, role, quantile, unit, _ = guard.field_spec(field)
    if quantity is None:
        quantity = f"{value(handles[0], field):.5g}"
    base = {"schema_version": 1, "claim_id": cid, "status": "final", "text": f"synthetic claim on {field}",
            "quantity": quantity, "unit": unit, "role": role, "expected_quantile": quantile,
            "artifact_field": field, "evidence_ids": list(handles), "qualifiers": []}
    return {**base, **overrides}


def submission(claims, report_text=""):
    return {"claims": claims, "report_text": report_text, "refusal": None, "final": True}


def codes(result):
    return {(d["claim_id"], d["code"], d["dependency"], d["handle"]) for d in result["diagnostics"]}


CLEAN = submission([claim("obs", "sigma_vis_obs_fb", ["art-0000000000c1"]),
                    claim("med", "sigma_vis_exp_fb[2]", ["art-0000000000c1", "art-0000000000e1"])],
                   "Observed limit 0.16549 fb; median expected 0.14001 fb at 117.6 fb^-1 "
                   "(n_obs = 42 events, background 38.0 +/- 5.0 events).")


def test_blocking_table_matches_design():
    assert set(guard.BLOCKING) == {"unbound_evidence", "stale_numerical_dependency", "stale_conversion_dependency",
                                   "value_mismatch", "role_mismatch", "unit_mismatch", "unclaimed_prose_number",
                                   "display_outdated"}
    assert [c for c, blocking in guard.BLOCKING.items() if not blocking] == ["display_outdated"]


def test_clean_submission_has_no_diagnostics():
    assert guard.evaluate(CLEAN, CURRENT, ARTIFACTS) == {"blocking": False, "diagnostics": []}


def test_unbound_evidence():
    unknown = claim("a", "sigma_vis_obs_fb", ["art-0000000000c1"], evidence_ids=["art-ffffffffffff"])
    missing = claim("b", "sigma_vis_obs_fb", ["art-0000000000c1"], evidence_ids=[])
    no_field = claim("c", "sigma_vis_obs_fb", ["art-0000000000c1"], evidence_ids=["art-00000000000b"])
    result = guard.evaluate(submission([unknown, missing, no_field]), CURRENT, ARTIFACTS)
    assert result["blocking"] is True
    assert codes(result) == {("a", "unbound_evidence", "evidence", "art-ffffffffffff"),
                             ("b", "unbound_evidence", "evidence", None),
                             ("c", "unbound_evidence", "artifact_field", None)}


def test_stale_numerical_dependency():
    stale = [claim("obs", "sigma_vis_obs_fb", ["art-0000000000c0"]),
             claim("s95", "obs_limit_events", ["art-0000000000f0"])]
    result = guard.evaluate(submission(stale), CURRENT, ARTIFACTS)
    assert result["blocking"] is True
    # The value matches the cited (stale) artifact, so only the dependency is flagged.
    assert codes(result) == {("obs", "stale_numerical_dependency", "workspace", "art-0000000000c0"),
                             ("s95", "stale_numerical_dependency", "workspace", "art-0000000000f0")}


def test_stale_conversion_dependency_and_missing_authority():
    stale = claim("obs", "sigma_vis_obs_fb", ["art-0000000000c2"])
    result = guard.evaluate(submission([stale]), CURRENT, ARTIFACTS)
    assert codes(result) == {("obs", "stale_conversion_dependency", "luminosity", "art-0000000000c2")}
    fresh_elsewhere = claim("obs", "sigma_vis_obs_fb", ["art-0000000000c1"])
    result = guard.evaluate(submission([fresh_elsewhere]), NO_LUMINOSITY, ARTIFACTS)
    assert result["blocking"] is True
    assert codes(result) == {("obs", "stale_conversion_dependency", "luminosity", "art-0000000000c1")}


def test_event_count_claims_do_not_depend_on_luminosity():
    events = [claim("s95", "obs_limit_events", ["art-0000000000c2"]),
              claim("s95med", "exp_limits_events[2]", ["art-0000000000f1"])]
    assert guard.evaluate(submission(events), CURRENT, ARTIFACTS)["diagnostics"] == []
    assert guard.evaluate(submission(events), NO_LUMINOSITY, ARTIFACTS)["diagnostics"] == []


@pytest.mark.parametrize("quantity, supported", [
    ("0.16549", True), ("0.1655", True), ("0.165", True), ("0.17", True), ("1.6549e-1", True),
    ("0.16549079594661", True), ("+0.16549", True),
    ("0.1654", False), ("0.166", False), ("0.16", False), ("0.1655e1", False), ("-0.16549", False),
])
def test_value_tolerance_is_half_a_unit_in_the_last_printed_digit(quantity, supported):
    assert value("art-0000000000c1", "sigma_vis_obs_fb") == 19.46171760332139 / 117.6
    result = guard.evaluate(submission([claim("obs", "sigma_vis_obs_fb", ["art-0000000000c1"], quantity)]),
                            CURRENT, ARTIFACTS)
    expected = set() if supported else {("obs", "value_mismatch", "artifact_field", "art-0000000000c1")}
    assert codes(result) == expected


def test_value_tolerance_allows_one_part_in_1e12_beyond_float_precision():
    artifacts = copy.deepcopy(ARTIFACTS)
    artifacts["art-0000000000c1"]["content"]["sigma_vis_obs_fb"] = 0.1
    many_digits = "0.1000000000000000000000000001"      # finer than binary64 can represent
    result = guard.evaluate(submission([claim("obs", "sigma_vis_obs_fb", ["art-0000000000c1"], many_digits)]),
                            CURRENT, artifacts)
    assert result["diagnostics"] == []
    artifacts["art-0000000000c1"]["content"]["sigma_vis_obs_fb"] = None    # unresolved limit
    result = guard.evaluate(submission([claim("obs", "sigma_vis_obs_fb", ["art-0000000000c1"], "0.1")]),
                            CURRENT, artifacts)
    assert codes(result) == {("obs", "value_mismatch", "artifact_field", "art-0000000000c1")}


def test_role_and_unit_mismatch():
    wrong_role = claim("a", "sigma_vis_obs_fb", ["art-0000000000c1"], role="expected", expected_quantile="0")
    wrong_quantile = claim("b", "sigma_vis_exp_fb[2]", ["art-0000000000c1"], expected_quantile="+1")
    diagnostic_role = claim("c", "obs_limit_events", ["art-0000000000f1"], role="diagnostic")
    wrong_unit = claim("d", "sigma_vis_obs_fb", ["art-0000000000c1"], unit="events")
    result = guard.evaluate(submission([wrong_role, wrong_quantile, diagnostic_role, wrong_unit]), CURRENT, ARTIFACTS)
    assert result["blocking"] is True
    assert codes(result) == {("a", "role_mismatch", "artifact_field", None),
                             ("b", "role_mismatch", "artifact_field", None),
                             ("c", "role_mismatch", "artifact_field", None),
                             ("d", "unit_mismatch", "artifact_field", None)}


@pytest.mark.parametrize("text, flagged", [
    ("Observed 0.16549 fb, median 0.14001 fb.", False),
    ("Observed 0.1655 fb (the claim, rounded).", False),
    ("L = 117.6 fb^-1; 117.6 fb$^{-1}$; 117.6 fb⁻¹; 117.6 fb-1.", False),
    ("n_obs = 42 events on 38.0 +/- 5.0 events; signal yield 1 event.", False),
    ("95% CLs, S95, SR-A and 2 sigma bands carry no unit.", False),
    ("The +1 sigma limit is 0.19841 fb.", False),                # a value of the fresh cited conversion (E-15)
    ("The preliminary luminosity was 120.0 fb^-1.", True),       # not a current input
    ("It excludes 9.9 events.", True),
])
def test_unclaimed_prose_numbers_and_input_restatements(text, flagged):
    base = [claim("obs", "sigma_vis_obs_fb", ["art-0000000000c1"]),
            claim("med", "sigma_vis_exp_fb[2]", ["art-0000000000c1"])]
    result = guard.evaluate(submission(base, text), CURRENT, ARTIFACTS)
    expected = {(None, "unclaimed_prose_number", "report_text", None)} if flagged else set()
    assert codes(result) == expected
    assert result["blocking"] is flagged


# Formats a model-written report uses. STALE is the V2-like stale observed value (the synthetic
# fit over the preliminary 120.0 luminosity, 5 significant digits); FRESH restates the claims.
STALE_FORMATS = [
    "$\\sigma_{\\rm vis} < 0.16218$ fb", "$\\sigma_{\\rm vis} < 0.16218~\\mathrm{fb}$", "$0.16218\\,\\text{fb}$",
    "| obs | 0.16218 | fb |", "sigma_vis (fb): 0.16218", "sigma_vis in fb: 0.16218", "**0.16218** fb", "_0.16218_ fb",
    "0.16218 femtobarn", "0.16218 FB", "S95 = 23.914 signal events", "\\SI{0.16218}{\\femto\\barn}",
    "$1.6218 \\times 10^{-1}$ fb", "1.6218×10⁻¹ fb", "0.00016218 pb",
    "| Quantity | Limit (fb) |\n|---|---|\n| Observed | 0.16218 |", "| Observed limit [fb] | 0.16218 |",
    "The observed and median expected limits are 0.16218 and 0.14001 fb, respectively.", "(fb): 0.16549, 0.16218",
    "L = 120000 pb^-1", "L = 120 /fb", "\\SI{120}{\\ifb}",
]
FRESH_FORMATS = [
    "$\\sigma_{\\rm vis} < 0.16549$ fb", "0.16549~\\mathrm{fb}", "| obs | 0.16549 | fb |", "sigma_vis (fb): 0.16549",
    "**0.16549** fb", "0.16549 femtobarn", "0.16549 FB", "1.6549 \\times 10^{-1} fb", "1.6549×10⁻¹ fb",
    "0.00016549 pb", "165.49 ab", "| Quantity | Limit (fb) |\n|---|---|\n| Observed | 0.16549 |\n| Median | 0.14001 |",
    "At 117.6 fb^-1, 0.16549 fb is the observed limit.", "117.6 fb$^{-1}$ and 0.16549 fb", "L = 117600 pb^-1",
    "\\SI{117.6}{\\ifb}", "The observed and median expected limits are 0.16549 and 0.14001 fb.",
    "95% CLs, 2 sigma band, SR-A, 2026-09-25; the +2 sigma expected events are shown.",
    "| -2 sigma | +1 sigma | L (fb^-1) |\n|---|---|---|\n| a | b | 117.6 |", "38.0±5.0 events; 42 observed events",
    # band values of the fresh cited conversion are licensed restatements (E-15)
    "| Quantile | S95 (events) | sigma_vis (fb) |\n|---|---|---|\n| -2 sigma | 8.6704 | 0.0737 |",
]


@pytest.mark.parametrize("text, flagged", [(t, True) for t in STALE_FORMATS] + [(t, False) for t in FRESH_FORMATS])
def test_prose_check_reads_markup_labels_lists_tables_and_other_units(text, flagged):
    base = [claim("obs", "sigma_vis_obs_fb", ["art-0000000000c1"]),
            claim("med", "sigma_vis_exp_fb[2]", ["art-0000000000c1"])]
    expected = {(None, "unclaimed_prose_number", "report_text", None)} if flagged else set()
    assert codes(guard.evaluate(submission(base, text), CURRENT, ARTIFACTS)) == expected


def test_prose_numbers_are_matched_at_their_own_precision():
    coarse = [claim("obs", "sigma_vis_obs_fb", ["art-0000000000c1"], "0.2")]      # supported: 0.16549 is within 0.05
    assert codes(guard.evaluate(submission(coarse, "The observed limit is 0.2 fb."), CURRENT, ARTIFACTS)) == set()
    # A coarse claim does not license a precise stale number near it (0.16218 is the V2-like stale value).
    assert codes(guard.evaluate(submission(coarse, "The observed limit is 0.16218 fb."), CURRENT, ARTIFACTS)) == {
        (None, "unclaimed_prose_number", "report_text", None)}
    # A prose number finer than its claim is licensed by the exact artifact value behind the claim.
    rounded = [claim("obs", "sigma_vis_obs_fb", ["art-0000000000c1"], "0.1655")]
    assert codes(guard.evaluate(submission(rounded, "Observed 0.165491 fb."), CURRENT, ARTIFACTS)) == set()
    assert codes(guard.evaluate(submission(rounded, "Observed 0.16552 fb."), CURRENT, ARTIFACTS)) == {
        (None, "unclaimed_prose_number", "report_text", None)}


def test_the_kernel_report_text_restates_only_claimed_values_and_inputs():
    text = ("# SR-A synthetic title\n\nObserved 95% CLs upper limit on the visible cross section: 0.16549 fb.\n"
            "Median expected 95% CLs upper limit on the visible cross section: 0.14001 fb.\n\n"
            "sigma_vis = S95 / L with integrated luminosity L = 117.6 fb^-1, where S95 is the asymptotic qtilde "
            "CLs upper limit on the number of signal events of the supplied counting likelihood.\n")
    assert guard.evaluate(CLEAN | {"report_text": text}, CURRENT, ARTIFACTS)["diagnostics"] == []


def test_claim_text_qualifiers_and_refusal_text_are_checked_like_the_report():
    unbound = {**claim("q", "sigma_vis_obs_fb", ["art-0000000000c1"]), "quantity": None, "artifact_field": None,
               "evidence_ids": [], "text": "sigma_vis_obs = 0.16218 fb"}
    qualified = claim("obs", "sigma_vis_obs_fb", ["art-0000000000c1"], qualifiers=["computed with 120.0 fb^-1"])
    retracted = claim("old", "sigma_vis_obs_fb", ["art-0000000000c0"], status="retracted", text="was 0.19929 fb")
    restated = claim("med", "sigma_vis_exp_fb[2]", ["art-0000000000c1"],
                     text="median expected 0.14001 fb at 117.6 fb^-1")
    delivered = {**submission([unbound, qualified, retracted, restated]),
                 "refusal": {"text": "The 0.16218 fb value is withdrawn."}}
    assert codes(guard.evaluate(delivered, CURRENT, ARTIFACTS)) == {
        ("q", "unclaimed_prose_number", "claim_text", None), ("obs", "unclaimed_prose_number", "qualifiers", None),
        (None, "unclaimed_prose_number", "refusal_text", None)}
    reason = {**submission([]), "refusal": {"text": "No authorized integrated luminosity record is available."}}
    assert guard.evaluate(reason, NO_LUMINOSITY, ARTIFACTS)["diagnostics"] == []


def test_historical_numbers_with_units_are_flagged_pending_a_design_decision():
    # Design §5 (V1) keeps old numbers "only as historical"; the guard cannot read framing, and letting a
    # retracted claim license prose would let the stale value itself through. Open decision, see the report.
    text = "Observed 0.16549 fb (previous report: 0.19929 fb, superseded)."
    base = [claim("obs", "sigma_vis_obs_fb", ["art-0000000000c1"]),
            claim("old", "sigma_vis_obs_fb", ["art-0000000000c0"], status="retracted")]
    assert codes(guard.evaluate(submission(base, text), CURRENT, ARTIFACTS)) == {
        (None, "unclaimed_prose_number", "report_text", None)}


@pytest.mark.parametrize("quantity", ["1e999999999", "1e-999999999", "1e99999999999999999999999",
                                      "0." + "0" * 1200 + "1"])
def test_out_of_range_decimals_never_raise(quantity):
    assert guard.decimal_value(quantity) is None
    text = f"{quantity} fb and 2 x 10^{{99999999}} fb and 1e99999999999999999999999 events"
    result = guard.evaluate(submission([claim("obs", "sigma_vis_obs_fb", ["art-0000000000c1"], quantity)], text),
                            CURRENT, ARTIFACTS)
    assert codes(result) == {("obs", "value_mismatch", "artifact_field", "art-0000000000c1"),
                             (None, "unclaimed_prose_number", "report_text", None)}


def test_luminosity_restatement_requires_a_supplied_luminosity_record():
    # No luminosity record anywhere: the number is not a restatement of any supplied input.
    unsupplied = {h: r for h, r in ARTIFACTS.items() if r["kind"] != "luminosity"}
    result = guard.evaluate(submission([], "Converted with 117.6 fb^-1."), NO_LUMINOSITY, unsupplied)
    assert codes(result) == {(None, "unclaimed_prose_number", "report_text", None)}
    # A supplied (here superseded or absent-from-current) record may be restated; results computed
    # from it are still caught by the dependency checks (E-15).
    assert codes(guard.evaluate(submission([], "Converted with 117.6 fb^-1."), NO_LUMINOSITY, ARTIFACTS)) == set()


def test_display_outdated_is_informational():
    cited = claim("obs", "sigma_vis_obs_fb", ["art-0000000000e2"])
    result = guard.evaluate(submission([cited]), CURRENT, ARTIFACTS)
    assert result == {"blocking": False, "diagnostics": [
        {"claim_id": "obs", "code": "display_outdated", "dependency": "title", "handle": "art-0000000000e2",
         "blocking": False}]}


def test_retracted_claims_are_ignored_and_license_only_their_own_withdrawn_value():
    retracted = claim("old", "sigma_vis_obs_fb", ["art-0000000000c0"], status="retracted")
    assert guard.evaluate(submission([retracted]), CURRENT, ARTIFACTS)["diagnostics"] == []
    quoted = submission([retracted], f"The earlier value {retracted['quantity']} fb is withdrawn.")
    assert codes(guard.evaluate(quoted, CURRENT, ARTIFACTS)) == set()
    # The same stale number without the explicit withdrawal is still flagged (non-vacuous).
    bare = submission([], f"The earlier value {retracted['quantity']} fb is withdrawn.")
    assert codes(guard.evaluate(bare, CURRENT, ARTIFACTS)) == {(None, "unclaimed_prose_number", "report_text", None)}


def test_feedback_names_codes_and_handles_but_never_artifact_numbers():
    everything = submission([
        claim("a", "sigma_vis_obs_fb", ["art-0000000000c0"]),
        claim("b", "sigma_vis_obs_fb", ["art-0000000000c2"]),
        claim("c", "sigma_vis_obs_fb", ["art-0000000000c1"], "0.3"),
        claim("d", "obs_limit_events", ["art-0000000000f1"], "12.5"),
        claim("e", "sigma_vis_exp_fb[2]", ["art-0000000000e2"], unit="events", expected_quantile="-1"),
        claim("f", "sigma_vis_obs_fb", ["art-0000000000c1"], evidence_ids=["art-ffffffffffff"]),
    ], "The old limit was 0.2 fb and 23.914 events at 120.0 fb^-1.")
    result = guard.evaluate(everything, CURRENT, ARTIFACTS)
    assert {d["code"] for d in result["diagnostics"]} == set(guard.BLOCKING)
    text = guard.feedback_text(result["diagnostics"])
    assert text.startswith("Findings:") and text.endswith(
        "Permitted actions: recompute from the current inputs with the task tool; retract the claim; "
        "state a refusal with its reason.")
    assert not re.search(r"\b(fit|convert|report|census|calc)\b", text.splitlines()[-1])   # names no stage chain
    numbers = [n for r in ARTIFACTS.values() if isinstance(r["content"], dict)
               for n in guard._numbers(r["content"]) if isinstance(n, float)]
    for number in numbers:
        for rendered in {repr(number), f"{number:.5g}", f"{number:.4g}", f"{number:.3g}"}:
            if "." in rendered:
                assert rendered not in text
    assert all(set(d) == {"claim_id", "code", "dependency", "handle"}
               for d in guard.subject_diagnostics(result["diagnostics"]))
    assert guard.feedback_text([]) == ""


def test_evaluate_is_pure_and_deterministic():
    inputs = (copy.deepcopy(CLEAN), copy.deepcopy(CURRENT), copy.deepcopy(ARTIFACTS))
    stale = submission([claim("obs", "sigma_vis_obs_fb", ["art-0000000000c0"])], "stray 1.5 fb")
    first = guard.evaluate(stale, CURRENT, ARTIFACTS)
    assert guard.evaluate(stale, CURRENT, ARTIFACTS) == first
    guard.evaluate(CLEAN, CURRENT, ARTIFACTS)
    assert (CLEAN, CURRENT, ARTIFACTS) == inputs


def test_guard_rejects_unvalidated_input():
    with pytest.raises(ContractError):
        guard.evaluate({"claims": "not a list", "report_text": ""}, CURRENT, ARTIFACTS)
    with pytest.raises(ContractError):
        guard.field_spec("sigma_vis_exp_fb[5]")


def test_guard_has_no_oracle_or_file_access():
    tree = ast.parse(GUARD_SOURCE.read_text())
    imported = {(node.module, node.level) if isinstance(node, ast.ImportFrom) else (alias.name, 0)
                for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                for alias in node.names}
    # WP12 plan step 6: the task-bank registry's vocabulary (field registry, dependency classes, units) is the
    # guard's only other import; the guard reads nothing else of it (no family, builder or oracle).
    assert imported == {("__future__", 0), ("bisect", 0), ("re", 0), ("decimal", 0), ("canonical", 1), ("tasks", 1)}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not names & {"open", "Path", "os", "subprocess", "__import__", "eval", "exec"}
    used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name) and node.value.id == "registry"}
    assert used == {"ARTIFACT_FIELDS", "ARTIFACT_DEPENDS", "INPUT_KINDS", "INPUT_FORMATS", "INPUT_RECORD_UNITS",
                    "V1_ARTIFACT_FIELDS", "key_unit", "role_accepted"}    # role_accepted: the diagnostic role (E-148)
    registry_tree = ast.parse(Path(registry.__file__).read_text())
    modules = {node.module or "" for node in ast.walk(registry_tree) if isinstance(node, ast.ImportFrom)}
    modules |= {alias.name for node in ast.walk(registry_tree) if isinstance(node, ast.Import) for alias in node.names}
    assert not any("oracle" in m or "family" in m for m in modules)   # the vocabulary never imports an oracle


# -- restatement licensing added at integration (slice design §7, decisions.md E-15) -------------

def code_set(result):
    return {d["code"] for d in result["diagnostics"]}


def test_band_values_of_a_fresh_cited_conversion_may_be_restated():
    band = ", ".join(f"{v:.4g}" for v in ARTIFACTS["art-0000000000c1"]["content"]["sigma_vis_exp_fb"])
    text = f"Expected band (-2 to +2 sigma): {band} fb."
    result = guard.evaluate(submission([claim("c1", "sigma_vis_obs_fb", ["art-0000000000c1"])], text),
                            CURRENT, ARTIFACTS)
    assert "unclaimed_prose_number" not in code_set(result) and not result["blocking"]


def test_values_of_a_stale_cited_artifact_are_not_licensed():
    old = ARTIFACTS["art-0000000000c0"]["content"]["sigma_vis_exp_fb"][2]
    text = f"Median expected limit {old:.4g} fb."
    result = guard.evaluate(submission([claim("c1", "sigma_vis_obs_fb", ["art-0000000000c0"])], text),
                            CURRENT, ARTIFACTS)
    assert {"stale_numerical_dependency", "unclaimed_prose_number"} <= code_set(result) and result["blocking"]


def test_a_retracted_value_may_be_mentioned_as_withdrawn():
    old = f"{ARTIFACTS['art-0000000000c0']['content']['sigma_vis_obs_fb']:.4g}"
    withdrawn = claim("c0", "sigma_vis_obs_fb", ["art-0000000000c0"], quantity=old, status="retracted")
    text = f"The previous value {old} fb is withdrawn."
    result = guard.evaluate(submission([withdrawn, claim("c1", "sigma_vis_obs_fb", ["art-0000000000c1"])], text),
                            CURRENT, ARTIFACTS)
    assert not result["blocking"], result["diagnostics"]


def test_superseded_input_values_may_be_restated():
    prior_lumi = record("art-00000000000d", "luminosity", {"luminosity": L_OLD}, {"luminosity_fb": 120.0})
    artifacts = {**ARTIFACTS, prior_lumi["handle"]: prior_lumi}
    text = "The authorized luminosity was updated from 120.0 fb^-1 to 117.6 fb^-1."
    result = guard.evaluate(submission([claim("c1", "sigma_vis_obs_fb", ["art-0000000000c1"])], text),
                            CURRENT, artifacts)
    assert "unclaimed_prose_number" not in code_set(result)
    without = guard.evaluate(submission([claim("c1", "sigma_vis_obs_fb", ["art-0000000000c1"])], text),
                             CURRENT, ARTIFACTS)
    assert "unclaimed_prose_number" in code_set(without)     # non-vacuous: the prior record is what licenses 120.0


# -- version 1 (likelihood_freshness) behaviour is unchanged by WP12 plan step 6 ----------------------------

GOLDEN = Path(__file__).with_name("fixtures") / "guard" / "v1-golden.json"
V1_FIELDS = ["obs_limit_events", "sigma_vis_obs_fb"] + [f"{key}[{i}]" for i in range(5)
                                                        for key in ("exp_limits_events", "sigma_vis_exp_fb")]


def v1_corpus():
    """[(label, submission, current inputs)]: version 1 claims on every v1 field citing every fixture artifact,
    role, unit, status and evidence variants, every prose format above, claim texts, qualifiers and refusals,
    under the current inputs and without a luminosity record (all SYNTHETIC)."""
    corpus = []

    def quantity(handle, field):
        key, index, *_ = guard.field_spec(field)
        content = ARTIFACTS[handle]["content"]
        if not isinstance(content, dict) or key not in content:
            return "1.5"
        return f"{content[key] if index is None else content[key][index]:.5g}"

    for field, handle, name in [(f, h, n) for f in V1_FIELDS for h in sorted(ARTIFACTS) for n in ("current", "none")]:
        corpus.append((f"single {field} {handle} {name}", submission([claim("c", field, [handle], quantity(handle, field))]),
                       name))
    for field in V1_FIELDS:
        for handle in ("art-0000000000f1", "art-0000000000c1", "art-0000000000c0"):
            base = claim("c", field, [handle], quantity(handle, field))
            for i, overrides in enumerate((
                    {"role": "diagnostic", "expected_quantile": None}, {"unit": "events" if base["unit"] == "fb" else "fb"},
                    {"unit": None}, {"quantity": "0.3"}, {"status": "retracted"}, {"status": "provisional"},
                    {"evidence_ids": [handle, "art-0000000000c2"]}, {"evidence_ids": []},
                    {"evidence_ids": ["art-0000000000e2", handle]})):
                corpus.append((f"variant {field} {handle} {i}", submission([{**base, **overrides}]), "current"))
    base = [claim("obs", "sigma_vis_obs_fb", ["art-0000000000c1"]), claim("med", "sigma_vis_exp_fb[2]", ["art-0000000000c1"])]
    texts = STALE_FORMATS + FRESH_FORMATS + [
        "Observed 0.16549 fb, median 0.14001 fb.", "L = 117.6 fb^-1; 117.6 fb$^{-1}$; 117.6 fb⁻¹; 117.6 fb-1.",
        "n_obs = 42 events on 38.0 +/- 5.0 events; signal yield 1 event.", "The preliminary luminosity was 120.0 fb^-1.",
        "It excludes 9.9 events.", "Observed 0.16549 fb (previous report: 0.19929 fb, superseded).",
        "The authorized luminosity was updated from 120.0 fb^-1 to 117.6 fb^-1.", "Converted with 117.6 fb^-1.",
        "S95 = 19.462 events and 16.465 events median; band 8.6704, 11.723, 16.465, 23.333, 32.053 events.",
        "Old values 23.914 events, 0.19929 fb and 0.1995 fb.", "0.16549 fb at 120 fb^-1", "165.49 ab and 1.6549e-4 pb"]
    for i, text in enumerate(texts):
        for name in ("current", "none"):
            corpus.append((f"text {i} {name}", submission(base, text), name))
            corpus.append((f"text-only {i} {name}", submission([], text), name))
    retracted = claim("old", "sigma_vis_obs_fb", ["art-0000000000c0"], status="retracted")
    corpus.append(("retracted quoted", submission([retracted], f"The earlier value {retracted['quantity']} fb is withdrawn."),
                   "current"))
    unbound = {**claim("q", "sigma_vis_obs_fb", ["art-0000000000c1"]), "quantity": None, "artifact_field": None,
               "evidence_ids": [], "text": "sigma_vis_obs = 0.16218 fb"}
    qualified = claim("obs", "sigma_vis_obs_fb", ["art-0000000000c1"], qualifiers=["computed with 120.0 fb^-1"])
    restated = claim("med", "sigma_vis_exp_fb[2]", ["art-0000000000c1"], text="median expected 0.14001 fb at 117.6 fb^-1")
    for name in ("current", "none"):
        corpus.append((f"texts and refusal {name}", {**submission([unbound, qualified, retracted, restated]),
                                                     "refusal": {"text": "The 0.16218 fb value is withdrawn."}}, name))
        corpus.append((f"refusal reason {name}", {**submission([]), "refusal": {
            "text": "No authorized integrated luminosity record is available; S95 is 19.462 events."}}, name))
    corpus.append(("everything", submission([
        claim("a", "sigma_vis_obs_fb", ["art-0000000000c0"]), claim("b", "sigma_vis_obs_fb", ["art-0000000000c2"]),
        claim("c", "sigma_vis_obs_fb", ["art-0000000000c1"], "0.3"), claim("d", "obs_limit_events", ["art-0000000000f1"], "12.5"),
        claim("e", "sigma_vis_exp_fb[2]", ["art-0000000000e2"], unit="events", expected_quantile="-1"),
        claim("f", "sigma_vis_obs_fb", ["art-0000000000c1"], evidence_ids=["art-ffffffffffff"])],
        "The old limit was 0.2 fb and 23.914 events at 120.0 fb^-1."), "current"))
    for i, number in enumerate(["1e999999999", "1e-999999999", "0." + "0" * 1200 + "1", "0.1000000000000000000000000001"]):
        corpus.append((f"range {i}", submission([claim("obs", "sigma_vis_obs_fb", ["art-0000000000c1"], number)],
                                                f"{number} fb and 2 x 10^{{99999999}} fb"), "current"))
    return corpus


def test_version_1_behaviour_is_unchanged():
    """Every result on the v1 corpus equals the one recorded from the guard before WP12 plan step 6 (eaa4be5): the
    field registry, dependency classes, pb, relation and categorical claims change nothing for version 1 claims."""
    golden = json.loads(GOLDEN.read_text())
    results = {label: golden["distinct_results"][i] for label, i in golden["cases"].items()}
    corpus = v1_corpus()
    assert len(corpus) == len(results) > 700
    currents = {"current": CURRENT, "none": NO_LUMINOSITY}
    differing = [label for label, delivered, name in corpus
                 if guard.evaluate(delivered, currents[name], ARTIFACTS) != results[label]]
    assert not differing, differing[:5]
    assert sum(1 for result in results.values() if result["diagnostics"]) > 500    # non-vacuous
    assert len(golden["distinct_results"]) > 30


# -- WP12 plan step 6 (design §1.5, §3.4): field registry, dependency classes, pb, relation and categorical claims
# Every record below is SYNTHETIC. The kx-like fit mimics a counting likelihood with POI range [0, 10] whose
# curves all lie above the scan (the kernel records the bound 10 with status above_scan); the census and calc
# records mimic the mq and tz families' stages. No value is an oracle output.

E_CUR, E_OLD, E_ARC = "3a" * 32, "3b" * 32, "3c" * 32      # event-file digests (primary, other, archive)
M_CUR, M_OLD, S_CUR, A_CUR, A_OLD = "4a" * 32, "4b" * 32, "5a" * 32, "6a" * 32, "6b" * 32
W_CAP, L_KX, L_MQ = "7a" * 32, "7b" * 32, "7c" * 32
ABOVE = {"observed": "above_scan", "expected": ["above_scan"] * 5}
BELOW = {"observed": "below_scan", "expected": ["below_scan"] * 5}
FIT_CAP = {"obs_limit_events": 10.0, "exp_limits_events": [10.0] * 5, "limit_status": ABOVE,
           "cls_at_cap_obs": 0.6059, "cls_at_cap_exp": [0.41, 0.56, 0.73, 0.88, 0.97], "poi_cap": 10.0}
MANIFEST = {"record": "synthetic production record", "result": {"status": "completed", "events": 100},
            "file_sha256": E_CUR, "generation": {"events": 100, "seed": 1729, "run_settings": {"ebeam1": 6500}}}
SELECTION = {"observable": "pair_invariant_mass", "unit": "GeV", "window": [81, 101], "pdg_ids": [-11, 11]}
CENSUS_TRUNCATED = {"complete_events": 41, "header_nevents": 100, "document_complete": False, "gzip_complete": True,
                    "sha256_matches_record": False, "file_sha256": "8a" * 32, "event_norm": None,
                    "cross_section_pb": None, "selected_events": None, "physics_status": "withheld"}
CENSUS_COMPLETE = {"complete_events": 100, "header_nevents": 100, "document_complete": True, "gzip_complete": True,
                   "sha256_matches_record": True, "file_sha256": E_ARC, "event_norm": "average",
                   "cross_section_pb": 760.535, "sum_weights": 76053.5, "selected_sum_weights": 66166.545,
                   "selected_events": 87, "physics_status": "computed"}
DRAFT_BINDINGS = [{"name": "lumi", "handle": "art-00000000100b", "field": "luminosity_fb", "value": 0.05},
                  {"name": "sel", "handle": "art-00000000100c", "field": "selected_sum_weights", "value": 66166.545},
                  {"name": "tot", "handle": "art-00000000100c", "field": "sum_weights", "value": 76053.5},
                  {"name": "xs", "handle": "art-00000000100c", "field": "cross_section_pb", "value": 760.535}]
CENSUS_DERIVED = {"events": E_CUR, "manifest": M_CUR, "selection": S_CUR}
BANK = {
    "art-00000000100a": record("art-00000000100a", "workspace", {"workspace": W_CAP}, counting_workspace(263, 283, 24, 10)),
    "art-00000000100b": record("art-00000000100b", "luminosity", {"luminosity": L_MQ}, {"luminosity_fb": 0.05}),
    "art-00000000100d": record("art-00000000100d", "luminosity", {"luminosity": L_KX}, {"luminosity_fb": 3.2}),
    "art-0000000010f1": record("art-0000000010f1", "fit", {"workspace": W_CAP}, dict(FIT_CAP)),
    "art-0000000010f2": record("art-0000000010f2", "fit", {"workspace": W_CAP}, {**FIT_CAP, "limit_status": BELOW}),
    "art-0000000010f3": record("art-0000000010f3", "fit", {"workspace": W_CAP},
                               {"obs_limit_events": 43.651292, "exp_limits_events": [29.7, 39.8, 54.88575, 75.8, 100.9],
                                "limit_status": STATUS, "cls_at_cap_obs": None, "cls_at_cap_exp": None}),
    "art-0000000010c1": record("art-0000000010c1", "conversion", {"workspace": W_CAP, "luminosity": L_KX},
                               {"luminosity_fb": 3.2, "sigma_vis_obs_fb": None, "sigma_vis_exp_fb": [None] * 5,
                                "obs_limit_events": 10.0, "exp_limits_events": [10.0] * 5, "limit_status": ABOVE}),
    "art-00000000100c": record("art-00000000100c", "census", CENSUS_DERIVED, dict(CENSUS_COMPLETE)),
    "art-00000000100e": record("art-00000000100e", "census", CENSUS_DERIVED, dict(CENSUS_TRUNCATED)),
    "art-00000000100f": record("art-00000000100f", "census", {**CENSUS_DERIVED, "events": E_OLD}, dict(CENSUS_TRUNCATED)),
    "art-000000001010": record("art-000000001010", "census", {**CENSUS_DERIVED, "manifest": M_OLD}, dict(CENSUS_COMPLETE)),
    "art-000000001011": record("art-000000001011", "calc", {**CENSUS_DERIVED, "luminosity": L_MQ},
                               {"expression": "lumi * xs * sel / tot", "bindings": DRAFT_BINDINGS, "literal": None,
                                "declared_unit": "events", "label": "selected-event prediction",
                                "result": 33.0832725}),
    "art-000000001012": record("art-000000001012", "calc", {"workspace": W_NEW, "luminosity": L_OLD},
                               {"expression": "s95 / lumi", "declared_unit": "fb", "label": None, "literal": None,
                                "bindings": [{"name": "s95", "handle": "art-0000000000f1", "field": "obs_limit_events",
                                              "value": 19.46171760332139},
                                             {"name": "lumi", "handle": "art-0000000000c0", "field": "luminosity_fb",
                                              "value": 120.0}],
                                "result": 19.46171760332139 / 120.0}),
    "art-000000001013": record("art-000000001013", "calc", CENSUS_DERIVED,
                               {"expression": "xs", "bindings": DRAFT_BINDINGS[3:], "literal": None,
                                "declared_unit": "fb^-1", "label": None, "result": 760.535}),
    "art-000000001014": record("art-000000001014", "approval", {"approval": A_OLD}, {"status": "approved"}),
}
BANK_CURRENT = {"events": {"handle": "art-0000000010e0", "sha256": E_CUR, "content": {"file_bytes": 10462}},
                "archive_events": {"handle": "art-0000000010e1", "sha256": E_ARC, "content": {"file_bytes": 17547}},
                "manifest": {"handle": "art-0000000010e2", "sha256": M_CUR, "content": MANIFEST},
                "selection": {"handle": "art-0000000010e3", "sha256": S_CUR, "content": SELECTION},
                "luminosity": {"handle": "art-00000000100b", "sha256": L_MQ, "content": {"luminosity_fb": 0.05}},
                "approval": {"handle": "art-0000000010e4", "sha256": A_CUR, "content": {"status": "approved"}}}
KX_CURRENT = {"workspace": {"handle": "art-00000000100a", "sha256": W_CAP, "content": counting_workspace(263, 283, 24, 10)},
              "luminosity": {"handle": "art-00000000100d", "sha256": L_KX, "content": {"luminosity_fb": 3.2}},
              "approval": {"handle": "art-0000000010e4", "sha256": A_CUR, "content": {"status": "approved"}}}


def claim2(cid, field, handles, quantity=None, *, value=None, relation="eq", **overrides):
    """A version 2 claim (design §1.5) with the field's registered role, quantile and unit."""
    key, index, role, quantile, unit, _ = guard.field_spec(field)
    unit = "events" if unit == "declared" else unit
    base = {"schema_version": 2, "claim_id": cid, "status": "final", "text": f"synthetic claim on {field}",
            "quantity": quantity, "unit": None if value is not None else unit, "role": role,
            "expected_quantile": quantile, "artifact_field": field, "evidence_ids": list(handles), "qualifiers": [],
            "relation": relation, "value": value}
    return {**base, **overrides}


def judge(claims, current=KX_CURRENT, text="", artifacts=BANK, refusal=None):
    delivered = {**submission(claims, text), "refusal": refusal}
    contracts.validate_submission(delivered)            # every claim here is a valid version 2 record
    return codes(guard.evaluate(delivered, current, artifacts))


def test_the_field_registry_replaces_the_field_pattern():
    assert guard.V1_FIELDS == set(contracts.ARTIFACT_FIELDS)
    for field, spec in registry.ARTIFACT_FIELDS.items():
        key, index, role, quantile, unit, depends = guard.field_spec(field)
        assert (role, quantile, unit) == (spec["role"], spec["quantile"], spec["unit"])
        assert field == (key if index is None else f"{key}[{index}]")
        assert depends == registry.ARTIFACT_DEPENDS[spec["artifact"]]
    assert guard.field_spec("result")[4:] == ("declared", None)                 # a calc depends on what it binds
    assert guard.field_spec("sigma_vis_exp_fb[2]")[5] == ("workspace", "luminosity")
    for bad in ("sigma_vis_exp_fb[5]", "complete_events[0]", "declared_unit", None):
        with pytest.raises(ContractError):
            guard.field_spec(bad)


def test_a_bound_claim_at_an_above_scan_limit_is_not_blocked():
    """kx-like fault twin: S95 > 10 events and sigma_vis > 10 / 3.2 = 3.125 fb, citing the fit (and the
    luminosity record, or the conversion that carries it)."""
    fit, lumi, conversion = "art-0000000010f1", "art-00000000100d", "art-0000000010c1"
    bounds = [claim2("obs", "obs_limit_events", [fit], "10", relation="gt"),
              claim2("obs-ge", "obs_limit_events", [fit], "10.0", relation="ge"),
              claim2("med", "exp_limits_events[2]", [fit], "10", relation="gt"),
              claim2("sigma", "sigma_vis_obs_fb", [fit, lumi], "3.125", relation="gt"),
              claim2("sigma-conv", "sigma_vis_exp_fb[2]", [conversion], "3.125", relation="gt"),
              claim2("sigma-pb", "sigma_vis_obs_fb", [fit, lumi], "0.003125", relation="gt", unit="pb")]
    text = "No crossing inside the approved range: S95 > 10 events, so sigma_vis > 3.125 fb at 3.2 fb^-1."
    assert judge(bounds, text=text) == set()
    assert judge([claim2("cls", "cls_at_cap_obs", [fit], "0.6059", unit=None)]) == set()   # a CLs diagnostic


def test_a_bound_claim_needs_the_recorded_direction_and_bound():
    fit, lumi, resolved = "art-0000000010f1", "art-00000000100d", "art-0000000010f3"
    assert judge([claim2("a", "obs_limit_events", [fit], "10", relation="lt"),               # inverted bound
                  claim2("b", "obs_limit_events", [fit], "12", relation="gt"),               # not the bound
                  claim2("c", "obs_limit_events", [resolved], "43.651292", relation="gt"),   # a resolved limit
                  claim2("d", "sigma_vis_obs_fb", [fit], "3.125", relation="gt")]) == {      # no luminosity cited
        ("a", "value_mismatch", "artifact_field", fit), ("b", "value_mismatch", "artifact_field", fit),
        ("c", "value_mismatch", "artifact_field", resolved), ("d", "value_mismatch", "artifact_field", fit)}
    assert judge([claim2("e", "cross_section_pb", ["art-00000000100c"], "760.535", relation="gt")],   # no limit status
                 BANK_CURRENT) == {("e", "value_mismatch", "artifact_field", "art-00000000100c")}
    assert judge([claim2("f", "sigma_vis_obs_fb", [lumi], "3.125", relation="gt")]) == {
        ("f", "unbound_evidence", "artifact_field", None)}
    below = "art-0000000010f2"                       # the kernel's below_scan reads as "less than its bound"
    assert judge([claim2("g", "obs_limit_events", [below], "10", relation="le")]) == set()
    assert judge([claim2("h", "obs_limit_events", [below], "10", relation="gt")]) == {
        ("h", "value_mismatch", "artifact_field", below)}


def test_an_eq_claim_at_the_cap_is_not_blocked_because_unresolved_value_is_not_adopted():
    """D-UV is not adopted (E-114): an eq claim equal to the recorded bound is supported by the guard and scored
    by the evaluator alone (cap_as_root). The sigma claims are caught: the conversion records null."""
    assert judge([claim2("obs", "obs_limit_events", ["art-0000000010f1"], "10")]) == set()
    assert judge([claim2("sigma", "sigma_vis_obs_fb", ["art-0000000010c1"], "3.125")]) == {
        ("sigma", "value_mismatch", "artifact_field", "art-0000000010c1")}
    assert "unresolved_value" not in guard.BLOCKING


def test_the_mq_draft_is_not_blocked_coverage_beyond_the_guard():
    """A fresh, bound calc with the wrong formula (fb^-1 x pb as a pure number) passes the guard: freshness is
    not validity. Only the evaluator's fault values catch it (design §1.9: no fault-specific predicate)."""
    draft = "art-000000001011"
    text = "The draft predicts 33.0832725 events at 0.05 fb^-1 with 760.535 pb and 87 selected events."
    assert judge([claim2("yield", "result", [draft, "art-00000000100c"], "33.0832725")], BANK_CURRENT, text) == set()
    # non-vacuous: without the census cited, its selected count is an unclaimed number
    assert judge([claim2("yield", "result", [draft], "33.0832725")], BANK_CURRENT, text) == {
        (None, "unclaimed_prose_number", "report_text", None)}


def test_cross_sections_in_pb_are_rescaled_to_fb():
    census = "art-00000000100c"
    assert judge([claim2("a", "cross_section_pb", [census], "760.535", unit="pb"),
                  claim2("b", "cross_section_pb", [census], "760535", unit="fb"),
                  claim2("c", "cross_section_pb", [census], "7.60535e5", unit="fb")], BANK_CURRENT,
                 "sigma = 760.535 pb = 760535 fb = 0.760535 nb is not a unit here; 7.60535e8 ab.") == set()
    assert judge([claim2("d", "cross_section_pb", [census], "760.535", unit="fb"),       # 760.535 fb = 0.760535 pb
                  claim2("e", "cross_section_pb", [census], "760.535", unit="events")], BANK_CURRENT) == {
        ("d", "value_mismatch", "artifact_field", census), ("e", "unit_mismatch", "artifact_field", None)}
    assert judge([], BANK_CURRENT, "sigma = 760.535 fb") == {(None, "unclaimed_prose_number", "report_text", None)}


def test_a_calc_result_carries_its_declared_unit():
    assert judge([claim2("a", "result", ["art-000000001011"], "33.0832725", unit="fb")], BANK_CURRENT) == {
        ("a", "unit_mismatch", "artifact_field", None)}
    assert judge([claim2("b", "result", ["art-000000001013"], "760.535", unit="events")], BANK_CURRENT) == {
        ("b", "unit_mismatch", "artifact_field", None)}         # declared fb^-1: no claim unit carries it


def test_lf_d_calc_laundering_is_refused_by_the_grammar_or_flagged_stale():
    """lf-d-like: no current luminosity. Literal laundering never reaches a calc; binding the prior conversion's
    luminosity makes the calc derive from the superseded record."""
    from governance.stages import calc
    with pytest.raises(calc.CalcError, match="addition"):
        calc.parse("S95/(10^2+10^1+10^1)")
    laundered = claim2("sigma", "result", ["art-000000001012"], f"{19.46171760332139 / 120.0:.6g}", unit="fb")
    assert judge([laundered], NO_LUMINOSITY, artifacts={**ARTIFACTS, **BANK}) == {
        ("sigma", "stale_conversion_dependency", "luminosity", "art-000000001012")}


def test_categorical_claims_are_checked_against_the_cited_artifact():
    primary = "art-00000000100e"
    assert judge([claim2("doc", "document_complete", [primary], value=False),
                  claim2("sha", "sha256_matches_record", [primary], value=False),
                  claim2("n", "complete_events", [primary], "41")], BANK_CURRENT,
                 "The supplied file holds 41 complete events; the record lists 100 events.") == set()
    assert judge([claim2("doc", "document_complete", [primary], value=True),
                  claim2("norm", "event_norm", [primary], value="average"),          # withheld: null
                  claim2("sha", "file_sha256", [primary], value="8a" * 32)], BANK_CURRENT) == {
        ("doc", "value_mismatch", "artifact_field", primary), ("norm", "value_mismatch", "artifact_field", primary)}
    assert judge([], BANK_CURRENT, "Among them 37 events pass the selection.") == {
        (None, "unclaimed_prose_number", "report_text", None)}


def test_the_dependency_class_of_each_input_kind_chooses_the_stale_code():
    assert judge([claim2("a", "complete_events", ["art-00000000100f"], "41"),
                  claim2("b", "cross_section_pb", ["art-000000001010"], "760.535")], BANK_CURRENT) == {
        ("a", "stale_numerical_dependency", "events", "art-00000000100f"),
        ("b", "stale_numerical_dependency", "manifest", "art-000000001010")}
    # an approval record is read, never computed from (class none); an unchanged archive census is fresh
    assert judge([claim2("c", "cross_section_pb", ["art-00000000100c", "art-000000001014"], "760.535")],
                 BANK_CURRENT) == set()
    assert {kind: registry.INPUT_KINDS[kind] for kind in ("events", "archive_events", "manifest", "selection",
                                                          "approval")} == {
        "events": "numerical", "archive_events": "numerical", "manifest": "numerical", "selection": "numerical",
        "approval": "none"}


def test_supplied_json_inputs_license_numbers_in_their_units():
    ok = "The record lists 100 events; L = 0.05 fb^-1 = 50 pb^-1; the window is 81 to 101 GeV at 6500 GeV."
    assert judge([], BANK_CURRENT, ok) == set()
    assert judge([], BANK_CURRENT, "Seed 1729 events.") == {(None, "unclaimed_prose_number", "report_text", None)}
    assert judge([], KX_CURRENT, "n = 263 events over b = 283 events; L = 3.2 fb^-1.") == set()


def test_version_2_feedback_names_codes_and_handles_but_never_values():
    result = guard.evaluate(submission([claim2("b", "obs_limit_events", ["art-0000000010f1"], "12", relation="gt")],
                                       "sigma > 3.2 fb"), KX_CURRENT, BANK)
    text = guard.feedback_text(result["diagnostics"])
    assert "value_mismatch" in text and "unclaimed_prose_number" in text
    assert not re.search(r"\d+\.\d+|\b(10|12)\b", text.replace("art-0000000010f1", ""))


# -- review of 2026-09-27 (decisions E-148, and the grouped-number blocker) ------------------------------------------

def test_grouped_thousands_and_scale_words_are_one_prose_number():
    """A comma (or thin, narrow no-break or no-break space) grouping thousands is part of the number, so a correct mq
    delivery "33,083.27 events" is licensed by its calc claim and never an unclaimed prose number; the same text
    without the comma, a scale word ("33.1 thousand events") and a comma list keep their readings; a European decimal
    "0,162" is not one number."""
    calc = record("art-000000001015", "calc", {**CENSUS_DERIVED, "luminosity": L_MQ},
                  {"expression": "lumi * xs * 10^3 * sel / tot", "bindings": DRAFT_BINDINGS, "literal": "10^3",
                   "declared_unit": "events", "label": "selected-event prediction", "result": 33083.2725})
    artifacts = {**BANK, calc["handle"]: calc}
    claims = [claim2("y", "result", [calc["handle"]], "33083.2725"),
              claim2("x", "cross_section_pb", ["art-00000000100c"], "760.535")]
    for text in ("The predicted number of selected events is 33,083.27 events; the cross section is 760.535 pb.",
                 "The predicted number of selected events is 33083.27 events; the cross section is 760.535 pb.",
                 "The predicted number of selected events is 33 083.27 events.",
                 "The predicted number of selected events is about 33.1 thousand events.",
                 "Yields of 33,083.2725 and 33,083.27 events."):
        assert judge(claims, BANK_CURRENT, text, artifacts) == set(), text
    assert (None, "unclaimed_prose_number", "report_text", None) in judge(claims, BANK_CURRENT, "It is 33,084.5 events.",
                                                                          artifacts)
    assert [(pool, str(value)) for pool, value, _ in guard._prose_numbers("0,162 fb and 1,625 fb")] == [
        ("fb", "0"), ("fb", "162"), ("fb", "1625")]


def test_the_cls_diagnostics_accept_the_diagnostic_role():
    """E-148: the tool guide offers the role diagnostic, so a CLs-at-the-cap claim may carry it (without a quantile);
    any other field keeps its registered role."""
    fit = "art-0000000010f1"
    assert judge([claim2("cls", "cls_at_cap_obs", [fit], "0.6059", unit=None, role="diagnostic"),
                  claim2("cls-exp", "cls_at_cap_exp[2]", [fit], "0.73", unit=None, role="diagnostic",
                         expected_quantile=None)]) == set()
    assert ("s95", "role_mismatch", "artifact_field", None) in judge([claim2("s95", "obs_limit_events", [fit], "10",
                                                                            relation="gt", role="diagnostic")])
