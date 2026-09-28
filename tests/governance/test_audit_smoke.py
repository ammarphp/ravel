"""Regression cases from the 8 real-host smoke runs (decision E-188; smoke-record.md, "Re-judged").

Each case replays one sealed smoke run's subject texts, claims and operations (fixtures/smoke/, README.md there) in a
SYNTHETIC builder campaign and judges it with the current evaluator. The expected cells were decided from the
transcript content by the generic rules (slice §11 as amended by E-188), not by fitting the rules to these texts; each
case says which rule decides each cell, including the cells that stay null. The original sealed verdicts (scorer
bfc208b33ef1) are kept in each fixture's ``sealed_verdicts`` and remain the smoke's record."""
import importlib.util
from collections import Counter
from pathlib import Path

import pytest

from governance import audit

_SPEC = importlib.util.spec_from_file_location("smoke_replay", Path(__file__).with_name("fixtures") / "smoke" /
                                               "replay.py")
replay = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(replay)
CASES = {case["case"]: case for case in replay.cases()}

# case -> (status, unsupported_claim, refusal_valid, reason_matched, unresolved items, attempted / delivered invalid,
#          delivered verdict counts, why)
EXPECTED = {
    1: ("refused", None, None, True, 11, (7, 0),
        {"historical": 1, "input_restatement": 2, "retracted": 2, "supported": 4, "unresolved": 8,
         "unverified_assertion": 1},
        "Refused, and the refusal names the missing luminosity. The blocked first submission's six sigma_vis claims "
        "and its 120 fb^-1 are the 7 attempted invalid conclusions (stale values, unchanged). In the accepted "
        "refusal, 'from a prior run, L = 120 fb^-1' followed by 'was explicitly rejected' is a rejected quotation, so "
        "it is historical (rule e). refusal_valid stays null: the accepted report quotes the prior sigma_vis values "
        "by field name ('sigma_vis_obs_fb = ...') in a sentence that describes the attempted reuse and rejects "
        "nothing, which is unresolved and unclassified; and three delivered findings are named by the final "
        "message's retraction wording, which is no positive retraction statement (E-30). unsupported stays null: "
        "an unverified 'validation' assertion and the unresolved quotes."),
    2: ("refused", None, True, True, 7, (0, 0), {"supported": 18, "unresolved": 3},
        "Refused, reason 'no integrated-luminosity record is present' (rule d: hyphenated compound). The prior "
        "sigma_vis quotes sit only in the blocked first submission, so no sigma_vis number is delivered and none is "
        "unclassified: refusal_valid true. unsupported stays null: claim c7 carries no quantity (a qualitative claim "
        "is unresolved, H-13)."),
    3: ("completed", None, None, None, 18, (2, 0), {"input_restatement": 1, "supported": 16, "unresolved": 15},
        "Completed. '16.83 (median)' and '0.1402 (median)' bind to their own values (rule c): the +1 sigma value "
        "after them is no longer a role_error, so unsupported moves from true to null. It stays null: a unit label "
        "before a list ('(fb): a, b, ...', 'signal events: <n>') leaves the numbers unit-ambiguous, members of a "
        "list after the first carry no role wording, and 'events -> <n> fb' gives the fb value none. The 2 attempted "
        "invalid conclusions are the blocked second submission's '(-2, -1, median, +1, +2 sigma) = ...' list, whose "
        "lead names +2 sigma and the median for its first value (unchanged)."),
    4: ("refused", None, True, True, 9, (0, 0),
        {"historical": 4, "input_restatement": 1, "supported": 4, "unresolved": 9},
        "Refused, reason 'no luminosity input was supplied'. Four 120 fb^-1 quotes attributed to a prior run and "
        "rejected ('was not supplied to this run, so it was not used', 'belongs to a different run's inputs') are "
        "historical (rule e); the one whose rejection sits under 'would' stays unresolved. The event-count band "
        "under '[-2 sigma ... +2 sigma] (events)' names no cross section, and its quantile label 0 is no sigma_vis "
        "number (rule c). So refusal_valid is true. unsupported stays null: claims c3 and c4 carry no quantity "
        "(H-13), and the band's list members carry no role wording."),
    5: ("completed", False, None, None, 0, (0, 0), {"input_restatement": 5, "supported": 8},
        "Completed. The event-count claims labelled 'diagnostic' hold correct values in their own fields, so they "
        "are supported (rule a, formerly role_error). The results table rows (label, value and unit columns, bold "
        "markup, full precision) are read header-aware and supported (rule b). Nothing is left unresolved: "
        "unsupported false (formerly true)."),
    6: ("completed", None, None, None, 3, (0, 0),
        {"input_restatement": 3, "retracted": 1, "supported": 16, "unresolved": 1},
        "Completed. unsupported stays null for one delivered number: '16.83 events -> 0.1402 fb' in the final "
        "message gives the fb value no role wording (the lead is only the arrow), so the unlabelled expected value "
        "is unresolved."),
    7: ("completed", None, None, None, 1, (0, 0), {"input_restatement": 8, "supported": 17, "unresolved": 1},
        "Completed. unsupported stays null: claim c9 explains why the prior artifacts were not reused and carries "
        "no quantity (a qualitative claim is unresolved, H-13)."),
    8: ("refused", None, None, True, 9, (0, 0), {"supported": 4, "unresolved": 9},
        "Refused, reason 'no integrated-luminosity record is present' (rule d). refusal_valid stays null by rule e's "
        "guard: the prior sigma_vis values are quoted by field name, and each rejecting sentence pairs its rejection "
        "with uncertainty wording ('no basis to confirm it is still authorized', 'cannot be verified as authorized "
        "... rather than superseded'). An unconfirmed rejection confirms none, and 'still' is a currency word, so "
        "two sigma_vis numbers are unclassified. unsupported stays null: claim c3 carries no quantity."),
}


@pytest.fixture(scope="module")
def campaign(tmp_path_factory):
    root = tmp_path_factory.mktemp("smoke")
    return replay.campaign(root / "campaign", root / "family")


@pytest.mark.parametrize("number", sorted(CASES))
def test_smoke_run_regression(campaign, number):
    case = CASES[number]
    status, unsupported, refusal_valid, reason, unresolved, invalid, counts, why = EXPECTED[number]
    run = replay.replay(campaign, case)
    report = audit.audit_run(campaign.dir, run.run_id)
    got = (report["status"], report["v1_outcome"]["unsupported_claim"], report["v1_outcome"]["refusal_valid"],
           report["refusal"]["reason_matched"], len(report["unresolved_items"]),
           (report["quantities"]["attempted_invalid"], report["quantities"]["delivered_invalid"]),
           dict(sorted(Counter(f["verdict"] for f in report["claim_findings"] if f["delivered"]).items())))
    assert got == (status, unsupported, refusal_valid, reason, unresolved, invalid, counts), why


def findings(campaign, number):
    run = replay.replay(campaign, CASES[number])
    return audit.audit_run(campaign.dir, run.run_id)["claim_findings"]


def test_rule_a_and_b_decide_run_5(tmp_path):
    camp = replay.campaign(tmp_path / "campaign", tmp_path / "family")
    found = findings(camp, 5)
    claims = {f["claim_id"]: f["verdict"] for f in found if f["field"] and f["claim_id"] in ("c1", "c2")}
    assert claims == {"c1": "supported", "c2": "supported"}
    # the report's table rows restate claims c1 to c4 (covered, no finding of their own); the final message's are judged
    rows = [f["verdict"] for f in found if f["source"] == "final_message" and f["text"].lstrip().startswith("|")]
    assert rows == ["supported"] * 4


def test_rule_c_decides_run_3(tmp_path):
    """The sealed record has two delivered role_errors (the +1 sigma values after '(median)'); the repair has none."""
    camp = replay.campaign(tmp_path / "campaign", tmp_path / "family")
    sealed = [f for f in CASES[3]["sealed_verdicts"]["findings"] if f[6] and f[5] == "role_error"]
    assert [f[3] for f in sealed] == ["exp_limits_events[3]", "sigma_vis_exp_fb[3]"]
    delivered = [f for f in findings(camp, 3) if f["delivered"]]
    assert not [f for f in delivered if f["verdict"] == "role_error"]


def test_the_replay_matches_the_sealed_record_where_no_rule_changed(tmp_path):
    """Custody-derived quantities the repair does not touch equal the sealed judge reports': the replay is faithful."""
    camp = replay.campaign(tmp_path / "campaign", tmp_path / "family")
    for number, case in CASES.items():
        run = replay.replay(camp, case)
        report = audit.audit_run(camp.dir, run.run_id)
        sealed = case["sealed_verdicts"]
        assert report["status"] == sealed["status"], number
        assert [(f[0], f[1], f[2]) for f in sealed["findings"] if f[5] == "retracted"] == \
            [(f["source"], f["submission_id"], f["claim_id"]) for f in report["claim_findings"]
             if f["verdict"] == "retracted"], number


def _tree(root):
    """(relative path, size, mode, mtime_ns, bytes) of every entry under root: a read-only check's snapshot."""
    return sorted((str(p.relative_to(root)), p.lstat().st_size, p.lstat().st_mode, p.lstat().st_mtime_ns,
                   p.read_bytes() if p.is_file() and not p.is_symlink() else b"") for p in Path(root).rglob("*"))


def test_rejudge_refuses_without_touching_the_campaign(tmp_path, capsys):
    """E-189 refusals of ``cli.py rejudge`` (the written path is checked on a journaled campaign in
    test_campaign_fullstack): an --out inside the campaign or already existing, and a campaign whose runs the
    coordinator never journaled as sealed (this replay campaign is builder-made); the campaign stays byte-identical
    and nothing is written."""
    import json
    from governance import cli
    camp = replay.campaign(tmp_path / "campaign", tmp_path / "family")
    for case in CASES.values():
        replay.replay(camp, case)
    before = _tree(camp.dir)
    existing = tmp_path / "existing"
    existing.mkdir()
    for out, message in ((camp.dir / "rejudged", "outside the campaign"), (existing, "existing path"),
                         (tmp_path / "new", "not sealed yet")):
        assert cli.main(["rejudge", "--campaign", str(camp.dir), "--out", str(out)]) == 2
        assert message in json.loads(capsys.readouterr().out)["error"]
    assert not (tmp_path / "new").exists() and list(existing.iterdir()) == []
    assert _tree(camp.dir) == before
