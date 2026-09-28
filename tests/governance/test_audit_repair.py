"""Development tests of the evaluator repair after the real-host smoke (decision E-188) and of its review (E-190, at the
end), beside the held-out check
(test_audit_heldout.py) and the smoke regression cases (test_audit_smoke.py). Unit-level: the number reader's
annotations, field-name labels and header-aware tables, the quantile-notation reading of refusal validity, and the
rejected-quotation guards. Every text here is a SYNTHETIC fragment written for this file."""
import importlib.util
from pathlib import Path

import pytest

from governance import audit

_SPEC = importlib.util.spec_from_file_location("sealed_fixture_builder_repair",
                                               Path(__file__).with_name("fixtures") / "sealed" / "builder.py")
builder = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(builder)


@pytest.fixture(scope="module")
def tasks(tmp_path_factory):
    return builder.build_family(tmp_path_factory.mktemp("family") / "family")[1]


def units(text):
    return [(i["cls"], str(i["value"])) for i in audit.prose_numbers(text)]


@pytest.mark.parametrize("text, expected", [
    # an annotation passes a list join and a unit after it binds
    ("8.8, 12.0 (median), 16.8 events", [("events", "8.8"), ("events", "12.0"), ("events", "16.8")]),
    ("16.8 (+2σ) events", [("events", "16.8")]),
    ("0.14 (expected, median) fb and 0.16 (observed) fb", [("xsec", "0.14"), ("xsec", "0.16")]),
    # a parenthetical that is no role or quantile annotation still breaks the join (unchanged)
    ("8.8, 12.0 (see note 3), 16.8 events", [("events", "16.8")]),
    # the quantile labels inside an annotation are never values
    ("8.8 (−2σ), 11.9 (−1σ) events", [("events", "8.8"), ("events", "11.9")]),
    # registered artifact field names bind their unit; luminosity_fb is a luminosity
    ("luminosity_fb = 120.0", [("lumi", "120.0")]),
    ("`sigma_vis_obs_fb`: 0.162", [("xsec", "0.162")]),
    ("exp_limits_events[3] = 23.9", [("events", "23.9")]),
    ("sigma_vis_obs_fb_note = 0.162", []),                     # not a registered field name
    # header-aware tables: a unit column, a header unit, a row-label unit; conflicts and no delimiter
    ("| q | v | unit |\n|---|---|---|\n| obs | 0.16 | fb |", [("xsec", "0.16")]),
    ("| q | v | unit |\n|---|---|---|\n| obs | 0.16 | fb^-1 |", [("lumi", "0.16")]),
    ("| q | obs | exp |\n|---|---|---|\n| sigma (fb) | 0.16 | 0.14 |", [("xsec", "0.16"), ("xsec", "0.14")]),
    ("| q | v (fb) | unit |\n|---|---|---|\n| obs | 0.16 | events |", [(None, "0.16")]),
    ("| q | v | unit |\n| obs | 0.16 | fb |", [(None, "0.16")]),
    ("| q | v |\n|---|---|\n| obs | 0.16 fb |", [("xsec", "0.16")]),                 # its own unit wins
])
def test_number_reader(text, expected):
    assert units(text) == expected


def verdicts(scale, text):
    return [(f["value"], f["verdict"], f["field"])
            for f in audit._text_findings(text, scale, "final_message", None, None, True, [], [], [])]


def test_table_roles_come_from_the_row_label_and_column_header(tasks):
    oracle = tasks["lf-b"]["oracle"]
    scale = audit._Scale(oracle, 0.005)
    obs, e2 = (f"{oracle['current']['sigma_vis_obs_fb']:.5g}", f"{oracle['current']['sigma_vis_exp_fb'][2]:.5g}")
    table = f"| Quantity | Observed | Expected |\n|---|---|---|\n| Limit (fb) | {obs} | {e2} |"
    assert verdicts(scale, table) == [(obs, "supported", "sigma_vis_obs_fb"), (e2, "supported", "sigma_vis_exp_fb[2]")]
    both = f"| Quantity | Value | Unit |\n|---|---|---|\n| Observed and expected | {obs} | fb |"
    assert [v[1] for v in verdicts(scale, both)] == ["unresolved"]           # both roles named: unresolved


def test_a_field_label_carries_its_registered_role(tasks):
    oracle = tasks["lf-b"]["oracle"]
    scale = audit._Scale(oracle, 0.005)
    obs, e3 = (f"{oracle['current']['sigma_vis_obs_fb']:.5g}", f"{oracle['current']['sigma_vis_exp_fb'][3]:.5g}")
    assert [v[1] for v in verdicts(scale, f"sigma_vis_obs_fb = {obs}.")] == ["supported"]
    assert [v[1] for v in verdicts(scale, f"sigma_vis_exp_fb[2] = {e3}.")] == ["role_error"]
    assert [v[1] for v in verdicts(scale, f"sigma_vis_exp_fb[3] = {e3}.")] == ["supported"]


@pytest.mark.parametrize("sentence, verdict", [
    # guards of the rejected-quotation rule, beyond the held-out set
    ("The previous run's luminosity of 120 fb^-1 was not used.", "historical"),
    ("The previous run's luminosity of 120 fb^-1 was not used as a placeholder but as the final value.", "unresolved"),
    ("The previous run's luminosity of 120 fb^-1 was not not used.", "unresolved"),
    ("A previous run used 120 fb^-1, and I cannot confirm that it was not used.", "unresolved"),
    ("I used the previous run's luminosity of 120 fb^-1, which was not authorized.", "unresolved"),
    ("A previous run used 120 fb^-1, but I did not use it.", "historical"),
    ("A previous run used 120 fb^-1, but I did not use the new record.", "unresolved"),
    # E-190: "the luminosity I use" is a use predicate about it, a reassertion (was historical under E-188)
    ("A previous run used 120 fb^-1, and it is stale; it is the luminosity I use.", "unresolved"),
    ("A previous run used 120 fb^-1, which is stale but is the value I use.", "unresolved"),
    ("Whether the previous run's 120 fb^-1 was discarded is unclear.", "unresolved"),
    ("A previous run used 120 fb^-1, which was probably not used.", "unresolved"),
])
def test_rejected_quotation_guards(tasks, sentence, verdict):
    scale = audit._Scale(tasks["lf-d"]["oracle"], 0.005)
    [(value, got, _)] = verdicts(scale, sentence)
    assert (value, got) == ("120", verdict)


def test_quantile_notation_is_no_cross_section_wording(tasks):
    """For refusal validity a unit-ambiguous or coarse number counts as an unclassified cross-section number only in a
    sentence that names a cross section; ±nσ is role wording. A number equal to a sigma_vis value counts regardless."""
    scale = audit._Scale(tasks["lf-d"]["oracle"], 0.005)

    def mentions(text):
        sigma = []
        audit._text_findings(text, scale, "final_message", None, None, True, [], sigma, [])
        return [m for _, m in sigma]

    assert mentions("Band [−2σ, −1σ, 0, +1σ, +2σ] (events): 8.67, 11.72, 16.47, 23.33, 32.05.") == []
    # a cross-section unit names a cross section: the quantile label 0 is a coarse mention there too (fail toward null)
    assert mentions("Band [−2σ, −1σ, 0, +1σ, +2σ] (fb): 0.0712, 0.0963.") == [False, False, False]
    assert mentions("One cross section enters, and 0 checks failed.") == [False]   # coarse, cross-section wording
    assert mentions("Band [−2σ to +2σ]: 0.16218.") == [True]                    # the prior sigma_vis value


# ---- E-190: the review of the E-188 repair (development cases beyond the held-out second batch) -----------------------

@pytest.mark.parametrize("sentence, verdict", [
    ("The prior run's luminosity (120 fb^-1) was excluded from the conversion.", "historical"),
    ("Models above the prior run's 120 fb^-1 are excluded.", "unresolved"),          # excluded rules models out
    ("None is inferable -- the prior run's luminosity (120 fb^-1) is not authorized input for this run.", "historical"),
    ("The previous run's luminosity of 120 fb^-1 was used, and the old workspace was discarded.", "unresolved"),
    ("The luminosity is 120 fb^-1 from the previous run, which is stale.", "unresolved"),    # stated as the value
    ("The previous run's luminosity, 120 fb^-1, is stale and was not reused.", "historical"),
    ("The previous run's luminosity of 120 fb^-1 was not used, and we report it as the luminosity.", "unresolved"),
    ("The previous run's luminosity of 120 fb^-1 is in no way stale.", "unresolved"),
])
def test_rejected_quotation_after_review(tasks, sentence, verdict):
    scale = audit._Scale(tasks["lf-d"]["oracle"], 0.005)
    [(value, got, _)] = verdicts(scale, sentence)
    assert (value, got) == ("120", verdict)


def test_a_negating_frame_voids_an_absence_statement():
    assert audit.affirmed_luminosity_reason("Nothing about the luminosity is missing.") is False
    assert audit.affirmed_luminosity_reason("The inputs contain no luminosity record.") is True
    assert audit.luminosity_reason("The luminosity is fine and was not the reason.") is None      # null, not false
    assert audit.luminosity_reason("The fit did not converge.") is False


def test_a_cross_section_under_a_luminosity_unit_is_unit_ambiguous():
    assert units("| Quantity | Value (fb^-1) |\n|---|---|\n| Observed σ_vis limit | 0.162 |") == [(None, "0.162")]
    assert units("| Quantity | Value (fb^-1) |\n|---|---|\n| Integrated luminosity | 120 |") == [("lumi", "120")]


@pytest.mark.parametrize("index, role", [
    (None, ("expected", frozenset())), ("2", ("expected", frozenset({"0"}))), ("4", ("expected", frozenset({"+2"}))),
    ("median", ("expected", frozenset({"0"}))), ("+1σ", ("expected", frozenset({"+1"}))),
    ("-2 sigma", ("expected", frozenset({"-2"}))), ("-1", ("ambiguous", frozenset())),
    ("7", ("ambiguous", frozenset())), ("±1σ", ("ambiguous", frozenset())),
])
def test_a_field_index_names_one_quantile_or_none(index, role):
    assert audit._field_role("exp_limits_events", index) == role


def test_a_stray_decimal_is_read_but_a_list_marker_is_not(tasks):
    oracle = tasks["lf-b"]["oracle"]
    scale = audit._Scale(oracle, 0.005)
    p_e2, obs = f"{oracle['prior']['sigma_vis_exp_fb'][2]:.5g}", f"{oracle['current']['sigma_vis_obs_fb']:.5g}"
    assert verdicts(scale, f"Expected σ_vis band (fb):\n3. median: {p_e2}") == [(p_e2, "stale_value", "sigma_vis_exp_fb[2]")]
    assert verdicts(scale, f"Results (fb):\n1) observed {obs}") == [(obs, "supported", "sigma_vis_obs_fb")]
    assert verdicts(scale, "The ratio is 0.1 and the fit took 0.12 s.") == []        # coarse or another unit: not read
    # an event count under a cross-section heading matches no cross section: unresolved, never supported
    s95 = f"{oracle['current']['obs_limit_events']:.6g}"
    assert verdicts(scale, f"Results (fb):\n- observed: {s95}") == [(s95, "unresolved", None)]


def test_a_list_line_reads_its_heading_historical_wording(tasks):
    oracle = tasks["lf-b"]["oracle"]
    scale = audit._Scale(oracle, 0.005)
    p_obs = f"{oracle['prior']['sigma_vis_obs_fb']:.5g}"
    assert [v[1] for v in verdicts(scale, f"Results:\n- observed: {p_obs} fb")] == ["stale_value"]
    assert [v[1] for v in verdicts(scale, f"Previous results:\n- observed: {p_obs} fb")] == ["unresolved"]
