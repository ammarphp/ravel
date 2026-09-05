"""summary_audit.py -- the SUMMARY-PLOT physics-completeness gate (Task 4.1, R-SA1..8).

Pins: the embedded --selftest fixtures (clean=all-PASS, defective=all 8 rules trip); the CLI's
exit codes (0 PASS, 2 usage/missing-artifact, 3 physics-FAIL); the machine JSON it writes
(schema_version, per-rule status+offenders, overall verdict); and one targeted unit check per
rule via `audit()` directly, using tiny synthetic fixtures (no per-paper literals -- this gate
must stay general).

Import the module under test by file path, not by package import: the repo root carries a
`py.py` file that shadows the real `py` package pytest depends on internally if the repo root
ends up on sys.path. Run this file from OUTSIDE the repo:
    cd /tmp && python3 -m pytest <this file's abspath> -q
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SUMMARY_AUDIT_PY = REPO / "src" / "ravel" / "validation" / "summary_audit.py"


def _load_summary_audit():
    spec = importlib.util.spec_from_file_location("summary_audit_under_test", SUMMARY_AUDIT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
#  CLI-level
# --------------------------------------------------------------------------- #

def test_selftest_passes():
    result = subprocess.run([sys.executable, str(SUMMARY_AUDIT_PY), "--selftest"],
                             cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "clean fixture: verdict=PASS" in result.stdout
    assert "defective fixture: verdict=FAIL" in result.stdout
    assert "trips all 8 rules R-SA1..8" in result.stdout


def test_usage_error_no_paths():
    result = subprocess.run([sys.executable, str(SUMMARY_AUDIT_PY)],
                             cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "need --rundir" in result.stderr


def test_usage_error_missing_files(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SUMMARY_AUDIT_PY),
         "--survey", str(tmp_path / "nope_survey.json"),
         "--manifest", str(tmp_path / "nope_manifest.json")],
        cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "not found" in result.stderr


def test_clean_fixture_cli_exits_zero_and_writes_pass_json(tmp_path):
    sa = _load_summary_audit()
    survey, manifest = sa._clean_fixture()
    survey_path = tmp_path / "survey.json"
    manifest_path = tmp_path / "basis_manifest.json"
    survey_path.write_text(json.dumps(survey))
    manifest_path.write_text(json.dumps(manifest))
    out_path = tmp_path / "summary_audit.json"

    result = subprocess.run(
        [sys.executable, str(SUMMARY_AUDIT_PY), "--survey", str(survey_path),
         "--manifest", str(manifest_path), "--out", str(out_path), "--check"],
        cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "verdict=PASS" in result.stdout

    assert out_path.is_file()
    rec = json.loads(out_path.read_text())
    assert rec["schema_version"] == 1
    assert rec["verdict"] == "PASS"
    assert len(rec["rules"]) == 8
    assert all(r["status"] == "PASS" for r in rec["rules"])


def test_defective_fixture_cli_exits_three_and_names_every_rule(tmp_path):
    sa = _load_summary_audit()
    survey, manifest = sa._defective_fixture()
    survey_path = tmp_path / "survey.json"
    manifest_path = tmp_path / "basis_manifest.json"
    survey_path.write_text(json.dumps(survey))
    manifest_path.write_text(json.dumps(manifest))
    out_path = tmp_path / "summary_audit.json"

    result = subprocess.run(
        [sys.executable, str(SUMMARY_AUDIT_PY), "--survey", str(survey_path),
         "--manifest", str(manifest_path), "--out", str(out_path)],
        cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "verdict=FAIL" in result.stdout

    rec = json.loads(out_path.read_text())
    assert rec["verdict"] == "FAIL"
    by_id = {r["id"]: r for r in rec["rules"]}
    assert set(by_id) == {f"R-SA{i}" for i in range(1, 9)}
    for rule_id, r in by_id.items():
        assert r["status"] == "FAIL", f"{rule_id} expected FAIL, got {r['status']}"
        assert r["offenders"], f"{rule_id} FAIL but named no offenders"


def test_rundir_default_paths(tmp_path):
    sa = _load_summary_audit()
    survey, manifest = sa._clean_fixture()
    rundir = tmp_path / "2026-07-08_TEST_rundir"
    (rundir / "outputs").mkdir(parents=True)
    (rundir / "inputs").mkdir(parents=True)
    (rundir / "outputs" / "survey.json").write_text(json.dumps(survey))
    (rundir / "inputs" / "basis_manifest.json").write_text(json.dumps(manifest))

    result = subprocess.run(
        [sys.executable, str(SUMMARY_AUDIT_PY), "--rundir", str(rundir)],
        cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (rundir / "outputs" / "summary_audit.json").is_file()


# --------------------------------------------------------------------------- #
#  unit-level: one isolated instance per rule via audit() directly
# --------------------------------------------------------------------------- #

def _candidate(id_, final_state="l-nu-qq semileptonic", mass_range=(300, 3000),
                provenance="hepdata-machine", disposition=None):
    c = {"id": id_, "final_state": final_state, "mass_range_gev": list(mass_range),
         "provenance": provenance}
    if disposition is not None:
        c["disposition"] = disposition
    return c


def _curve(survey_id, source="a search", provenance="hepdata-machine", draw="primary",
           native_basis="x", transformation="IDENTITY", identity_check="NONE"):
    c = {"source": source, "provenance": provenance, "draw": draw,
         "native_basis": native_basis, "transformation": transformation,
         "identity_check": identity_check}
    if survey_id is not None:
        c["survey_id"] = survey_id
    return c


def _survey(*candidates):
    return {"schema_version": 1, "candidates": list(candidates)}


def _manifest(*curves, coverage_gaps=None):
    m = {"schema_version": 1, "target_basis": {"quantity": "x"}, "curves": list(curves)}
    if coverage_gaps is not None:
        m["coverage_gaps"] = coverage_gaps
    return m


def test_r_sa1_missing_survey_id_fails():
    sa = _load_summary_audit()
    survey = _survey(_candidate("C1", disposition={"state": "plotted"}))
    manifest = _manifest(_curve(None, source="orphan curve"))
    rec = sa.audit(survey, manifest)
    r1 = next(r for r in rec["rules"] if r["id"] == "R-SA1")
    assert r1["status"] == "FAIL"
    assert any("no survey_id" in o for o in r1["offenders"])


def test_r_sa2_missing_disposition_fails():
    sa = _load_summary_audit()
    survey = _survey(_candidate("C1"))  # no disposition kwarg -> key absent
    manifest = _manifest(_curve("C1"))
    rec = sa.audit(survey, manifest)
    r2 = next(r for r in rec["rules"] if r["id"] == "R-SA2")
    assert r2["status"] == "FAIL"
    assert any("no disposition" in o for o in r2["offenders"])


def test_r_sa3_keyword_reason_class_fails():
    sa = _load_summary_audit()
    survey = _survey(_candidate("C1", disposition={
        "state": "excluded", "reason": "dropped", "reason_class": "keyword",
        "reviewer": "agent:test"}))
    manifest = _manifest()
    rec = sa.audit(survey, manifest)
    r3 = next(r for r in rec["rules"] if r["id"] == "R-SA3")
    assert r3["status"] == "FAIL"
    assert any("reason_class='keyword'" in o for o in r3["offenders"])


def test_r_sa4_mislabel_fails():
    sa = _load_summary_audit()
    survey = _survey(_candidate("C1", final_state="l-nu-qq semileptonic",
                                 disposition={"state": "plotted"}))
    manifest = _manifest(_curve("C1", source="a search, fully leptonic dilepton"))
    rec = sa.audit(survey, manifest)
    r4 = next(r for r in rec["rules"] if r["id"] == "R-SA4")
    assert r4["status"] == "FAIL"
    assert any("contradicts candidate final_state" in o for o in r4["offenders"])


def test_r_sa4_recognized_own_family_never_forbids_itself():
    """A curve labelled with tokens from its OWN family must never be flagged (regression guard
    against an off-by-one in the forbidden-set construction)."""
    sa = _load_summary_audit()
    survey = _survey(_candidate("C1", final_state="l-nu-qq semileptonic",
                                 disposition={"state": "plotted"}))
    manifest = _manifest(_curve("C1", source="a search, l-nu-qq semileptonic"))
    rec = sa.audit(survey, manifest)
    r4 = next(r for r in rec["rules"] if r["id"] == "R-SA4")
    assert r4["status"] == "PASS"


def test_r_sa5_superseded_drawn_primary_fails():
    sa = _load_summary_audit()
    survey = _survey(
        _candidate("C1", disposition={"state": "plotted"}),
        _candidate("C2", disposition={"state": "superseded", "reason": "old",
                                       "reviewer": "agent:test", "superseded_by": "C1"}),
    )
    manifest = _manifest(_curve("C1"), _curve("C2", draw="primary"))
    rec = sa.audit(survey, manifest)
    r5 = next(r for r in rec["rules"] if r["id"] == "R-SA5")
    assert r5["status"] == "FAIL"
    assert any("draw=primary" in o for o in r5["offenders"])


def test_r_sa6_digitized_without_qualifier_fails():
    sa = _load_summary_audit()
    survey = _survey(_candidate("C1", provenance="digitized",
                                 disposition={"state": "plotted"}))
    manifest = _manifest(_curve("C1", provenance="digitized",
                                 native_basis="HEPData Table 3"))
    rec = sa.audit(survey, manifest)
    r6 = next(r for r in rec["rules"] if r["id"] == "R-SA6")
    assert r6["status"] == "FAIL"
    assert any("digitiz" in o for o in r6["offenders"])


def test_r_sa7_coverage_gap_overlap_fails():
    sa = _load_summary_audit()
    survey = _survey(_candidate("C1", mass_range=(200, 3000),
                                 disposition={"state": "plotted"}))
    manifest = _manifest(_curve("C1"),
                          coverage_gaps=[{"lo_gev": 0, "hi_gev": 300,
                                          "note": "no published limit below 300 GeV"}])
    rec = sa.audit(survey, manifest)
    r7 = next(r for r in rec["rules"] if r["id"] == "R-SA7")
    assert r7["status"] == "FAIL"
    assert any("overlaps coverage gap" in o for o in r7["offenders"])


def test_r_sa7_free_text_below_n_gev_parsed():
    """The 'below N GeV' free-text floor parser (no structured lo_gev/hi_gev on the gap entry)."""
    sa = _load_summary_audit()
    survey = _survey(_candidate("C1", mass_range=(200, 3000),
                                 disposition={"state": "plotted"}))
    manifest = _manifest(_curve("C1"),
                          coverage_gaps=[{"note": "no published limit below 300 GeV"}])
    rec = sa.audit(survey, manifest)
    r7 = next(r for r in rec["rules"] if r["id"] == "R-SA7")
    assert r7["status"] == "FAIL"


def test_r_sa8_missing_transformation_fails():
    sa = _load_summary_audit()
    survey = _survey(_candidate("C1", disposition={"state": "plotted"}))
    manifest = _manifest(_curve("C1", transformation=""))
    rec = sa.audit(survey, manifest)
    r8 = next(r for r in rec["rules"] if r["id"] == "R-SA8")
    assert r8["status"] == "FAIL"
    assert any("no transformation" in o for o in r8["offenders"])


def test_draw_none_curve_exempt_from_sa4_and_sa8():
    """A curve explicitly marked draw=none (withheld, not drawn) is not held to the label/
    transformation checks meant for what actually appears on the figure."""
    sa = _load_summary_audit()
    survey = _survey(_candidate("C1", final_state="l-nu-qq semileptonic",
                                 disposition={"state": "plotted"}))
    manifest = _manifest(_curve("C1", source="fully leptonic dilepton mislabel",
                                 draw="none", transformation=""))
    rec = sa.audit(survey, manifest)
    by_id = {r["id"]: r for r in rec["rules"]}
    assert by_id["R-SA4"]["status"] == "PASS"
    assert by_id["R-SA8"]["status"] == "PASS"
