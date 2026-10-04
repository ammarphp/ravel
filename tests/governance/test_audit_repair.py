"""Development tests of the evaluator repair after the real-host smoke (decision E-188) and of its review (E-190), and of
the pilot request's two false-clean paths (E-200, at the end), beside the held-out check
(test_audit_heldout.py) and the smoke regression cases (test_audit_smoke.py). Unit-level: the number reader's
annotations, field-name labels and header-aware tables, the quantile-notation reading of refusal validity, the
rejected-quotation guards, the doubting frame and the stray pass's carried unit. Every text here is a SYNTHETIC fragment
written for this file."""
import importlib.util
import time
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
    # a cross-section unit names a cross section: the two values are unclassified mentions (fail toward null); the label
    # 0 of the quantile label list is no number since E-220 (it was a coarse mention before)
    assert mentions("Band [−2σ, −1σ, 0, +1σ, +2σ] (fb): 0.0712, 0.0963.") == [False, False]
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


# ---- E-200: a doubting or negating frame, and the stray pass's carried unit ------------------------------------------

@pytest.mark.parametrize("sentence, expected", [
    ("The previous {p_obs} fb was not used.", ["historical"]),                       # asserted (control)
    ("There is no doubt that the previous {p_obs} fb was superseded.", ["unresolved"]),   # "no doubt" counts (recorded)
    ("The previous {p_obs} fb was not used. Not sure.", ["unresolved"]),             # a short doubting next sentence
    ("The previous {p_obs} fb was not used; I cannot confirm it.", ["unresolved"]),  # a semicolon clause refers back
    ("The previous {p_obs} fb was not used. I cannot say why the fit moved.", ["historical"]),   # about something else
    ("It may be that the previous {p_obs} fb was superseded.", ["unresolved"]),
    ("As far as I know, the previous {p_obs} fb was not used.", ["unresolved"]),
    ("The observed limit changed from {p_obs} fb to {obs} fb, I believe.", ["unresolved", "supported"]),
    ("I did not use the previous {p_obs} fb, since I could not verify it.", ["unresolved"]),   # a tag that refers back
    # a doubt about something else, in another clause, governs nothing
    ("The current luminosity is unknown, so the previous {p_obs} fb was not used.", ["historical"]),
    ("Because the updated background is not yet verified, I did not reuse the previous {p_obs} fb.", ["historical"]),
    ("The previous {p_obs} fb was not used, but I cannot say why the fit moved.", ["historical"]),
])
def test_a_doubting_frame_marks_nothing(tasks, sentence, expected):
    oracle = tasks["lf-b"]["oracle"]
    scale = audit._Scale(oracle, 0.005)
    values = {"p_obs": f"{oracle['prior']['sigma_vis_obs_fb']:.5g}", "obs": f"{oracle['current']['sigma_vis_obs_fb']:.5g}"}
    assert [v[1] for v in verdicts(scale, sentence.format(**values))] == expected


def test_the_doubting_frame_is_read_per_clause():
    text = "The previous 0.1 fb was not used. I cannot confirm this."
    doubts = audit._Doubts(text, audit._spans(text))
    assert doubts.at(0, 13) is True and doubts.at(1, 40) is True           # the next sentence is a tag
    text = "The luminosity is unknown, so the old 0.1 fb was not used; it is final."
    doubts = audit._Doubts(text, audit._spans(text))
    assert doubts.at(0, text.index("0.1")) is False and doubts.at(0, 5) is True   # another clause, not a tag
    assert audit._Doubts("A. B.", audit._spans("A. B.")).at(0, 0) is False


def test_a_stray_value_is_read_in_the_unit_its_heading_names(tasks):
    oracle = tasks["lf-b"]["oracle"]
    scale = audit._Scale(oracle, 0.005)
    prior = oracle["prior"]["sigma_vis_obs_fb"]
    in_pb, in_fb = f"{prior / 1000:.5g}", f"{prior:.5g}"
    # a pb heading scales the value to fb: the prior value is stale, reported in fb
    [(value, verdict, field)] = verdicts(scale, f"Results (pb):\n- observed: {in_pb}")
    assert (verdict, field) == ("stale_value", "sigma_vis_obs_fb") and float(value) == pytest.approx(float(in_fb))
    # the fb digits under a pb heading scale to no known value, but as written they state the prior value: judged
    # unit-ambiguous, unresolved, as "- observed: <n> pb" is (E-210; E-200 dropped it, and E-190 read it as fb)
    [(value, verdict, field)] = verdicts(scale, f"Results (pb):\n- observed: {in_fb}")
    assert (verdict, field) == ("unresolved", None) and float(value) == pytest.approx(float(in_fb) * 1000)
    assert [v[1] for v in verdicts(scale, f"- observed: {in_fb} pb")] == ["unresolved"]
    # digits that state nothing known under a pb heading are still not read
    assert verdicts(scale, "Results (pb):\n- observed: 0.4711") == []
    # two units: unit-ambiguous, unresolved
    assert [v[1] for v in verdicts(scale, f"Results (fb) (pb):\n- observed: {in_fb}")] == ["unresolved"]
    # the likelihood_freshness profile admits no stray integer
    assert verdicts(scale, "Results (events):\n- observed: 19") == []


@pytest.mark.parametrize("shape", ["value {p_obs}, ", "- observed: {p_obs}\n", "Results (fb): observed {p_obs}; "])
def test_the_stray_pass_reads_a_megabyte_in_linear_time(tasks, shape):
    oracle = tasks["lf-b"]["oracle"]
    scale = audit._Scale(oracle, 0.005)
    line = shape.format(p_obs=f"{oracle['prior']['sigma_vis_obs_fb']:.5g}")
    text = line * (audit.MAX_TEXT_CHARS // len(line))
    started = time.process_time()
    findings = audit._text_findings(text, scale, "final_message", None, None, True, [], [], [])
    assert time.process_time() - started < 20 and findings, len(text)       # the E-190 rescan took hours


# ---- E-210: the review of E-200 (embedding frames, the frame's reach, reversals, the carried unit's scaled miss) ------

@pytest.mark.parametrize("sentence, expected", [
    # the writer's own assertive frames stay historical
    ("I confirm that the previous {p_obs} fb was not used.", ["historical"]),
    ("We can confirm that the previous {p_obs} fb was not used.", ["historical"]),
    ("It is true that the previous {p_obs} fb was not used.", ["historical"]),
    ("I am certain that the previous {p_obs} fb was not used.", ["historical"]),
    # any other embedding frame, a listed doubt or none, leaves it unresolved
    ("The log shows the previous {p_obs} fb was not used.", ["unresolved"]),
    ("It should be noted that the previous {p_obs} fb was not used.", ["unresolved"]),
    ("I confirm that the draft says the previous {p_obs} fb was not used.", ["unresolved"]),   # the second frame counts
    ("I do not confirm that the previous {p_obs} fb was not used.", ["unresolved"]),
    # a frame after the number in its clause does not govern it; "or so" is no clause break
    ("The previous {p_obs} fb was not used, so the draft claims nothing.", ["historical"]),
    ("The previous {p_obs} fb was not used, or so it seems.", ["unresolved"]),
    # reach: a framing sentence covers its paragraph, or the next one when it ends its own; a blank line stops a tag
    ("I cannot confirm the following:\n\nThe previous {p_obs} fb was not used.", ["unresolved"]),
    ("I cannot confirm the following.\n\nNothing else changed.\n\nThe previous {p_obs} fb was not used.", ["historical"]),
    ("The previous {p_obs} fb was not used.\n\nThe logs are incomplete. I cannot confirm this.", ["historical"]),
    ("The previous {p_obs} fb was not used. The fit converged. The logs are complete. I cannot confirm this.",
     ["historical"]),                                                                 # beyond DOUBT_REACH
    # a reversal opens the next sentence of the paragraph only
    ("The previous {p_obs} fb was not used. It was.", ["unresolved"]),
    ("The previous {p_obs} fb was not used.\n\nActually, the fit converged.", ["historical"]),
    ("The previous {p_obs} fb was not used. The fit converged. Actually, it was fast.", ["historical"]),
    # a back-referring delivery predicate in the next sentence reasserts; a negated one or one without a back-reference
    # does not
    ("The previous {p_obs} fb is outdated. I report it as the observed limit.", ["unresolved"]),
    ("The previous {p_obs} fb is outdated. I did not use it.", ["historical"]),
    ("The previous {p_obs} fb is outdated; I report {obs} fb as the observed limit.", ["historical", "supported"]),
    # a first-person doubt closing its clause is a tag; one with its own object is not
    ("The previous {p_obs} fb was not used, though I have not checked.", ["unresolved"]),
    ("The previous {p_obs} fb was not used, though I have not checked the fit logs.", ["historical"]),
])
def test_embedding_frames_reach_and_reversals(tasks, sentence, expected):
    oracle = tasks["lf-b"]["oracle"]
    scale = audit._Scale(oracle, 0.005)
    values = {"p_obs": f"{oracle['prior']['sigma_vis_obs_fb']:.5g}", "obs": f"{oracle['current']['sigma_vis_obs_fb']:.5g}"}
    assert [v[1] for v in verdicts(scale, sentence.format(**values))] == expected


def test_an_ignored_span_is_the_statement_not_a_frame():
    """audit_bank.corrected passes its marker as ``ignore``: "the draft is wrong" is the correction, not a doubt over it;
    another doubt of its clause, or a tag in another clause, still counts."""
    text = "The draft gives 33 events, and the draft is wrong."
    doubts, marker = audit._Doubts(text, audit._spans(text)), text.index("wrong")
    assert doubts.at(0, marker) is True and doubts.at(0, marker, ignore=(marker, marker + 5)) is False
    text = "The draft gives 33 events, and I am not sure the draft is wrong."
    marker = text.index("wrong")
    assert audit._Doubts(text, audit._spans(text)).at(0, marker, ignore=(marker, marker + 5)) is True
    text = "The draft is wrong, I think."
    marker = text.index("wrong")
    assert audit._Doubts(text, audit._spans(text)).at(0, marker, ignore=(marker, marker + 5)) is True


def test_the_framing_pass_reads_many_sentences_in_linear_time():
    text = "I cannot confirm the following. The previous 0.16218 fb was not used. " * 20000
    sentences = audit._Sentences(text)
    doubts = audit._Doubts(text, sentences.spans)
    started = time.process_time()
    last = text.rindex("0.16218")
    assert doubts.at(sentences.index(last), last) is True
    assert time.process_time() - started < 20
