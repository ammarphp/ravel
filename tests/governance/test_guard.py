"""Unit tests for the delivery guard (slice design §7).

Every artifact, input and submission below is a SYNTHETIC fixture built for these
tests; no value is a physics result or an oracle output.
"""
import ast
import copy
from pathlib import Path

import pytest

from governance import guard
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
        "Permitted actions: recompute through fit/convert/report; retract the claim; state a refusal with its reason.")
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
    assert imported == {("__future__", 0), ("bisect", 0), ("re", 0), ("decimal", 0), ("canonical", 1)}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not names & {"open", "Path", "os", "subprocess", "__import__", "eval", "exec"}


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
