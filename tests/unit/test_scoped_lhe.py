"""Falsification cases for whole-file LO event and effective-recipe validation."""
import gzip
import xml.etree.ElementTree as ET

import pytest

from ravel.physics.scoped import audit_lhe


def sample():
    generation = {
        "model": "sm-no_b_mass", "definitions": {"p": "g u d u~ d~"},
        "process": "p p > e+ e-", "events": 2, "seed": 1729, "beam_pdg": [2212, 2212],
        "run_settings": {"ebeam1": 6500, "ebeam2": 6500, "pdlabel": "cteq6l1", "lhaid": 10042},
        "observable": {"kind": "final_state_mass", "final_state_pdg": [-11, 11],
                       "bin_edges_gev": [40, 80, 120], "min_pt_gev": 10,
                       "max_abs_eta": 2.5, "min_mass_gev": 40},
    }
    event = """
<event>
4 1 1.0 100 0.007 0.118
2 -1 0 0 1 0 0 0 50 50 0 0 9
-2 -1 0 0 0 1 0 0 -50 50 0 0 9
11 1 1 2 0 0 30 0 40 50 0 0 9
-11 1 1 2 0 0 -30 0 -40 50 0 0 9
</event>
"""
    text = """<LesHouchesEvents version="1.0">
<header>
<MGRunCard>
6500=ebeam1
6500=ebeam2
cteq6l1=pdlabel
10042=lhaid
2=nevents
1729=iseed
False=use_syst
none=systematics_program
0=ickkw
4=dynamical_scale_choice
</MGRunCard>
<MG5ProcCard>
set gauge unitary
set complex_mass_scheme False
import model sm-no_b_mass
define p = g u d u~ d~
generate p p &gt; e+ e-
</MG5ProcCard>
<slha>
BLOCK MASS
23 91.188
</slha>
</header>
<init>
2212 2212 6500 6500 0 0 10042 10042 -4 1
760 6.5 1 1
</init>
""" + event * 2 + "\n</LesHouchesEvents>"
    return text, generation


def test_every_event_and_recipe(tmp_path):
    text, spec = sample()
    p = tmp_path / "sample.lhe.gz"
    p.write_bytes(gzip.compress(text.encode()))
    result = audit_lhe(p, spec)
    assert result["passed"] and result["events"] == 2
    assert result["masses_gev"] == [100, 100]
    assert result["recipe"]["run_settings"]["dynamical_scale_choice"] == 4
    assert "set gauge unitary" in result["recipe"]["process_card"]
    assert "iseed" not in result["recipe"]["run_settings"]


@pytest.mark.parametrize("old,new", [
    ("</LesHouchesEvents>", ""),
    ("</event>", ""),
    ("LesHouchesEvents", "OtherDocument"),
    ("2212 2212", "11 -11"),
    ("6500 6500 0 0", "6500 7000 0 0"),
    ("10042 10042 -4", "10042 9999 -4"),
    ("10042 -4 1", "10042 1 1"),
    ("760 6.5", "-760 6.5"),
    ("760 6.5", "760 -6.5"),
    ("4 1 1.0", "4 1 -1.0"),
    ("4 1 1.0", "4 1 nan"),
    ("4 1 1.0", "5 1 1.0"),
    ("-11 1 1 2", "-13 1 1 2"),
    ("30 0 40 50", "30 0 40 51"),
    ("1729=iseed", "1730=iseed"),
    ("2=nevents", "3=nevents"),
    ("cteq6l1=pdlabel", "lhapdf=pdlabel"),
    ("0=ickkw", "1=ickkw"),
    ("generate p p &gt; e+ e-", "generate p p &gt; mu+ mu-"),
    ("import model sm-no_b_mass", "import model sm"),
    ("define p = g u d u~ d~", "define p = g u d u~ d~\ndefine p = g"),
    ("</event>", "<rwgt><wgt id='1'>1</wgt></rwgt></event>"),
    ("91.188", "inf"),
])
def test_corruptions_fail_closed(tmp_path, old, new):
    text, spec = sample()
    p = tmp_path / "bad.lhe"
    p.write_text(text.replace(old, new))
    with pytest.raises((ValueError, ET.ParseError)):
        audit_lhe(p, spec)


def test_second_event_is_audited(tmp_path):
    text, spec = sample()
    first, rest = text.split("</event>", 1)
    p = tmp_path / "second.lhe"
    p.write_text(first + "</event>" + rest.replace("4 1 1.0", "4 1 2.0"))
    with pytest.raises(ValueError, match="variable nominal"):
        audit_lhe(p, spec)


def test_truncated_gzip_fails(tmp_path):
    text, spec = sample()
    p = tmp_path / "truncated.lhe.gz"
    p.write_bytes(gzip.compress(text.encode())[:-5])
    with pytest.raises((EOFError, OSError)):
        audit_lhe(p, spec)


@pytest.mark.parametrize("key,value", [("min_pt_gev", 31), ("max_abs_eta", .1), ("min_mass_gev", 101)])
def test_kinematic_controls_are_enforced(tmp_path, key, value):
    text, spec = sample()
    spec["observable"][key] = value
    p = tmp_path / "valid.lhe"
    p.write_text(text)
    with pytest.raises(ValueError, match="control"):
        audit_lhe(p, spec)
