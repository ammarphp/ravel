"""The comparison scorer rejects missing/wrong scientific deliverables cheaply."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "benchmarks/comparative/audit_drell_yan.py"
spec = importlib.util.spec_from_file_location("independent_lhe_audit", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def lhe():
    event = """<event>
4 1 10.0 91.0 0.01 0.1
1 -1 0 0 501 0 0 0 30 30 0 0 9
-1 -1 0 0 0 501 0 0 -30 30 0 0 9
11 1 1 2 0 0 30 0 0 30 0 0 9
-11 1 1 2 0 0 -30 0 0 30 0 0 9
</event>
"""
    return """<LesHouchesEvents version="3.0">
<header>
1729 = iseed
cteq6l1 = pdlabel
</header>
<init>
2212 2212 6500 6500 0 0 10042 10042 -4 1
10.0 1.0 10.0 1
<generator name="MadGraph5_aMC@NLO" version="2.9.27" />
</init>
""" + event * 100 + "</LesHouchesEvents>"


def test_constant_cross_section_weights_are_not_mistaken_for_weighted_sampling():
    result = audit.audit_text(lhe())
    assert result["passed"]
    assert result["events"] == 100
    assert result["cross_section_pb"] == 10.0
    assert result["integration_error_pb"] == 1.0
    assert result["dilepton_masses_gev"] == [60.0] * 100
    assert result["weight_convention"] == -4


@pytest.mark.parametrize("old,new,check", [
    ("2212 2212 6500 6500", "2212 2212 7000 7000", "beam_energies"),
    ("2212 2212 6500 6500", "11 -11 6500 6500", "proton_beams"),
    ("1729 = iseed", "0 = iseed", "seed_in_banner"),
    ("cteq6l1 = pdlabel", "lhapdf = pdlabel", "cteq6l1_in_banner"),
    ("10042 10042", "230000 230000", "cteq6l1_pdf_ids"),
    ("10.0 1.0 10.0 1", "10.0 -1.0 10.0 1", "positive_cross_section_and_error"),
    ("11 1 1 2", "13 1 1 2", "final_state_and_cuts"),
    ("30 0 0 30", "5 0 0 5", "final_state_and_cuts"),
    ("4 1 10.0 91.0", "4 1 -10.0 91.0", "positive_constant_weights"),
])
def test_wrong_physics_record_is_not_a_success(old, new, check):
    result = audit.audit_text(lhe().replace(old, new))
    assert not result["passed"]
    assert result["checks"][check] is False


def test_missing_event_is_failure_and_unmatched_weights_are_failure():
    text = lhe()
    start = text.index("<event>")
    end = text.index("</event>", start) + len("</event>")
    result = audit.audit_text(text[:start] + text[end:])
    assert not result["passed"]
    assert result["events"] == 99
    assert not audit.audit_text(text.replace("4 1 10.0 91.0", "4 1 9.0 91.0", 1))["passed"]


def test_nonfinite_or_truncated_records_do_not_score():
    with pytest.raises(ValueError, match="nonfinite"):
        audit.audit_text(lhe().replace("4 1 10.0", "4 1 NaN", 1))
    with pytest.raises(ValueError, match="census"):
        audit.audit_text(lhe().replace("-4 1", "-4 2", 1))
    with pytest.raises(ValueError, match="truncated"):
        audit.audit_text(lhe().replace("4 1 10.0", "5 1 10.0", 1))


@pytest.mark.parametrize("suffix", ["<event>\n4 1 10.0", "</event>"])
def test_extra_incomplete_event_cannot_hide_behind_100_valid_events(suffix):
    broken = lhe().replace("</LesHouchesEvents>", suffix + "\n</LesHouchesEvents>")
    assert not audit.audit_text(broken)["checks"]["complete_event_framing"]


def test_missing_file_terminator_is_not_complete_delivery():
    assert not audit.audit_text(lhe().replace("</LesHouchesEvents>", ""))["passed"]
