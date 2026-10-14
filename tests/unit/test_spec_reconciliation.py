"""Physics intent against simulation cards: one fixture per generator trap."""
import json

import pytest

from ravel.workflow import spec_reconciliation as sr

PARAM = """BLOCK MASS
  23 9.118800e+01
  9000005 1.500000e+03
BLOCK NPCOUPLINGS
  1 5.000000e-01
  2 0.000000e+00
DECAY 23 2.441404e+00
DECAY 9000005 1.000000e+01
"""


def sim(processes=("p p > e+ e-",), run=None, param=PARAM, definitions="define p = g u d u~ d~"):
    settings = {"ebeam1": 6500.0, "ebeam2": 6500.0, "lhaid": 82400, "ptl": 10.0, "etal": 2.5, "mmll": 0.0,
                "bwcutoff": 15.0, "ptj": 0.0}
    settings.update(run or {})
    lines = ["import model sm", definitions] + [("generate " if i == 0 else "add process ") + p for i, p in enumerate(processes)]
    return sr.simulation_from_cards(lines, settings, param)


def intent(**extra):
    base = {"processes": ["p p > e+ e-"], "conjugates": "inclusive", "pdf": {"lhaid": 82400}, "sqrt_s_gev": 13000,
            "fiducial": {"lepton": {"pt_min_gev": 25, "abs_eta_max": 2.5}}}
    base.update(extra)
    return base


def test_clean_configuration_is_satisfied():
    record = sr.reconcile(intent(), sim(), stage="post-run")
    assert record["satisfied"], record["violations"]
    assert not record["violations"]


def test_missing_charge_conjugate_is_a_violation():
    record = sr.reconcile(intent(processes=["p p > w+ j"]), sim(["p p > w+ j"], definitions="define j = g u d u~ d~\ndefine p = g u d u~ d~"),
                          stage="pre-launch")
    assert any("conjugate process absent" in v for v in record["violations"])
    both = sr.reconcile(intent(processes=["p p > w+ j", "p p > w- j"]),
                        sim(["p p > w+ j", "p p > w- j"]), stage="pre-launch")
    assert not any("conjugate" in v for v in both["violations"])
    as_written = sr.reconcile(intent(processes=["p p > w+ j"], conjugates="as_written"), sim(["p p > w+ j"]), stage="pre-launch")
    assert not any("conjugate" in v for v in as_written["violations"])


def test_coupling_orders_must_match():
    record = sr.reconcile(intent(processes=["p p > e+ e- QED<=2"], orders={"QED": "<=4"}),
                          sim(["p p > e+ e- QED<=2"]), stage="pre-launch")
    assert any("coupling orders" in v for v in record["violations"])
    ok = sr.reconcile(intent(processes=["p p > e+ e- QED=2 NP^2<=2"], orders={"QED": "<=2", "NP^2": "<=2"}),
                      sim(["p p > e+ e- QED=2 NP^2<=2"]), stage="pre-launch")
    assert not any("coupling orders" in v for v in ok["violations"])


def test_generator_cut_tighter_than_fiducial_is_a_violation():
    record = sr.reconcile(intent(), sim(run={"ptl": 30.0}), stage="post-run")
    assert any("ptl=30.0 must be looser" in v for v in record["violations"])
    record = sr.reconcile(intent(), sim(run={"etal": 2.0}), stage="post-run")
    assert any("etal" in v for v in record["violations"])
    record = sr.reconcile(intent(), sim(run={"etal": -1.0}), stage="post-run")
    assert not any("etal" in v for v in record["violations"])


def test_generator_cut_without_fiducial_counterpart_is_unknown():
    record = sr.reconcile(intent(), sim(run={"ptj": 20.0}), stage="post-run")
    assert record["satisfied"] and any("ptj" in u for u in record["unknowns"])


def test_stale_width_under_a_declared_mass_is_flagged():
    record = sr.reconcile(intent(masses_gev={"9000005": 1500.0}), sim(), stage="post-run")
    assert any("width (10.0) is not" in v for v in record["violations"])
    fixed = sr.reconcile(intent(masses_gev={"9000005": 1500.0}, widths={"9000005": {"mode": "fixed", "value_gev": 10.0}}),
                         sim(), stage="post-run")
    assert fixed["satisfied"], fixed["violations"]
    auto = sr.reconcile(intent(masses_gev={"9000005": 1500.0}, widths={"9000005": {"mode": "auto"}}),
                        sim(), stage="pre-launch")
    assert any("declared Auto" in v for v in auto["violations"])


def test_bwcutoff_must_cover_the_virtuality_window():
    record = sr.reconcile(intent(virtuality_windows_gev={"23": [40.0, 140.0]}), sim(run={"bwcutoff": 5.0}), stage="post-run")
    assert any("bwcutoff 23" in v for v in record["violations"])
    ok = sr.reconcile(intent(virtuality_windows_gev={"23": [60.0, 120.0]}), sim(), stage="post-run")
    assert ok["satisfied"], ok["violations"]


def test_undecayed_particle_needs_branching_ratio_rows():
    record = sr.reconcile(intent(undecayed_unstable=[9000005]), sim(), stage="post-run")
    assert any("branching-ratio rows" in v for v in record["violations"])
    with_rows = PARAM + "  1.0 2 11 -11\n"
    ok = sr.reconcile(intent(undecayed_unstable=[9000005]), sim(param=with_rows), stage="post-run")
    assert ok["satisfied"], ok["violations"]


def test_undeclared_nonzero_bsm_coupling_is_a_violation():
    record = sr.reconcile(intent(bsm_blocks=["NPCOUPLINGS"]), sim(), stage="post-run")
    assert any("nonzero entries [[1]]" in v for v in record["violations"])
    declared = sr.reconcile(intent(bsm_blocks=["NPCOUPLINGS"],
                                   active_parameters=[{"block": "NPCOUPLINGS", "code": [1], "value": 0.5}]),
                            sim(), stage="post-run")
    assert declared["satisfied"], declared["violations"]
    defaults = sr.reconcile(intent(bsm_blocks=["NPCOUPLINGS"], accept_model_defaults=True), sim(), stage="post-run")
    assert defaults["satisfied"]


def test_pdf_and_energy_mismatch():
    record = sr.reconcile(intent(pdf={"lhaid": 260000}, sqrt_s_gev=14000), sim(), stage="post-run")
    assert any("PDF set" in v for v in record["violations"])
    assert any("collision energy" in v for v in record["violations"])


def test_missing_parameter_card_is_unknown_not_satisfied():
    record = sr.reconcile(intent(masses_gev={"23": 91.188}), sim(param=None), stage="pre-launch")
    assert record["satisfied"] and any("parameter card" in u for u in record["unknowns"])


def test_invalid_intent_is_refused():
    with pytest.raises(ValueError, match="unknown physics-intent field"):
        sr.reconcile({"process": "p p > e+ e-"}, sim(), stage="post-run")


def test_science_mode_writes_record_and_refuses_violations(tmp_path):
    (tmp_path / "intent.json").write_text(json.dumps(intent(pdf={"lhaid": 260000})))
    (tmp_path / "proc_card.dat").write_text("import model sm\ndefine p = g u d u~ d~\ngenerate p p > e+ e-\n")
    (tmp_path / "run_card.dat").write_text("6500 = ebeam1\n6500 = ebeam2\n82400 = lhaid\n10 = ptl\n2.5 = etal\n")
    task = {"intent": "intent.json", "proc_card": "proc_card.dat", "run_card": "run_card.dat"}
    assert len(sr.inputs(task, tmp_path)) == 3
    with pytest.raises(ValueError, match="PDF set"):
        sr.run(task, tmp_path, tmp_path / "out")
    saved = json.loads((tmp_path / "out/spec-reconciliation.json").read_text())
    assert saved["status"] == "failed" and saved["violations"]
