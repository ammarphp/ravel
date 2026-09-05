"""audit.py::c_capability as a status-RATIFYING reconciler (Task 5, PRODUCT-CONTRACT section 5 /
CR-035): a `served`/`served-with-refusal` prompt in capability-matrix.json only earns its 1.0 R9
credit while its named `gate` is actually GREEN (an artifact's verdict field, or a selftest's
exit code); a `decision`/`deferred` gate can NEVER credit a prompt as served. This is the
anti-gaming property -- editing one JSON status string from 'partial' to 'served' must NOT move
R9 unless the underlying evidence is really green.

Pins:
  - served + green gate (artifact verdict==PASS, or selftest exit==0) -> credited 1.0
  - served + a decision/deferred gate (illegitimate by construction) -> credited 0.5 + a FAIL
    line names the prompt, AND flipping a real partial prompt's status to 'served' while
    keeping its decision gate does not raise the matrix's overall score at all
  - served + missing artifact / nonzero-exit selftest -> credited 0.5 + a FAIL line
  - a selftest gate that can't even run (bad ref) does not crash the reconciler -- treated red
  - a served prompt with no gate field at all -> migration WARN, credited as claimed (not a
    hard red), so mid-rollout matrices don't spuriously tank R9
  - the live framework/capability-matrix.json + framework/audit.py integration: readiness stays
    96%, R9 stays 0.64 (P1 summary_audit PASS + P4 shape_fit --selftest exit 0, both green today)

Import audit.py by file path, not by package import: the repo root carries a `py.py` file that
shadows the real `py` package pytest depends on internally if the repo root ends up on sys.path.
Run this file from OUTSIDE the repo:
    cd /tmp && python3 -m pytest <this file's abspath> -q
"""
import copy
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AUDIT_PY = REPO / "framework" / "audit.py"
MATRIX_JSON = REPO / "framework" / "capability-matrix.json"


def _load_audit():
    spec = importlib.util.spec_from_file_location("audit_under_test", AUDIT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _matrix():
    return json.loads(MATRIX_JSON.read_text())


# --------------------------------------------------------------------------- #
#  green gates (the honest-today state must be credited in full)
# --------------------------------------------------------------------------- #

def test_p1_artifact_gate_is_green_and_credited_full():
    """P1's gate reads trial-runs/.../summary_audit.json's verdict field; it is PASS today."""
    audit = _load_audit()
    m = _matrix()
    p1 = m["prompts"]["P1_hvt_zprime_ww_summary"]
    assert p1["status"] == "served"
    green, why = audit._gate_verdict(p1["gate"])
    assert green is True, why
    assert "PASS" in why


def test_p4_selftest_gate_is_green_and_credited_full():
    """P4's gate runs shape_fit.py --selftest; it exits 0 today."""
    audit = _load_audit()
    m = _matrix()
    p4 = m["prompts"]["P4_dijet_photon_widths"]
    assert p4["status"] == "served"
    green, why = audit._gate_verdict(p4["gate"])
    assert green is True, why
    assert "exit=0" in why


def test_served_green_gate_credits_1_0_in_reconciler():
    audit = _load_audit()
    m = _matrix()
    row = audit._score_capability(m)
    ev = row[5]
    p1_line = next(l for l in ev if l.startswith("P1_hvt_zprime_ww_summary:"))
    p4_line = next(l for l in ev if l.startswith("P4_dijet_photon_widths:"))
    assert "GREEN" in p1_line
    assert "GREEN" in p4_line
    assert "RED" not in p1_line
    assert "RED" not in p4_line


# --------------------------------------------------------------------------- #
#  the anti-gaming property: a decision/deferred gate can never credit 'served'
# --------------------------------------------------------------------------- #

def test_flipping_partial_to_served_does_not_raise_the_score():
    """The core anti-gaming proof: P3 is genuinely 'partial' with a decision gate. Hand-editing
    its status string to 'served' (leaving the decision gate untouched, exactly the cheap attack
    this task defends against) must NOT move the matrix's overall R9 score, because a
    decision-gated prompt can never be credited as served -- it still lands at 0.5."""
    audit = _load_audit()
    m_before = _matrix()
    assert m_before["prompts"]["P3_svj_expansion_tagger"]["status"] == "partial"
    assert m_before["prompts"]["P3_svj_expansion_tagger"]["gate"]["kind"] == "decision"
    row_before = audit._score_capability(m_before)

    m_after = copy.deepcopy(m_before)
    m_after["prompts"]["P3_svj_expansion_tagger"]["status"] = "served"
    row_after = audit._score_capability(m_after)

    assert row_before[2] == row_after[2], (
        "gaming a decision-gated prompt's status string to 'served' must not move R9's score"
    )

    fail_lines = [l for l in row_after[5] if l.startswith("R9: prompt P3_svj_expansion_tagger")]
    assert fail_lines, "a served claim riding a decision gate must emit a named FAIL line"
    assert "RED" in fail_lines[0]
    assert "credited as partial" in fail_lines[0]


def test_decision_gate_never_resolves_green():
    audit = _load_audit()
    gate = {"kind": "decision", "flip_when": "something happens"}
    green, why = audit._gate_verdict(gate)
    assert green is False
    assert "never credit a served status" in why


def test_deferred_gate_never_resolves_green():
    audit = _load_audit()
    gate = {"kind": "deferred", "flip_when": "something happens"}
    green, why = audit._gate_verdict(gate)
    assert green is False


# --------------------------------------------------------------------------- #
#  red gates from real evidence gaps (not just decision/deferred)
# --------------------------------------------------------------------------- #

def test_served_missing_artifact_credited_partial_and_flagged():
    audit = _load_audit()
    m = {"prompts": {
        "PX_fake": {
            "status": "served",
            "gate": {"kind": "artifact", "artifact": "trial-runs/does/not/exist.json",
                      "green_when": "verdict==PASS"},
        }
    }}
    row = audit._score_capability(m)
    assert row[2] == 0.5
    fail_lines = [l for l in row[5] if l.startswith("R9: prompt PX_fake")]
    assert fail_lines
    assert "RED" in fail_lines[0]
    assert "artifact missing" in fail_lines[0]


def test_served_artifact_wrong_verdict_credited_partial_and_flagged(tmp_path):
    audit = _load_audit()
    art = tmp_path / "bad_verdict.json"
    art.write_text(json.dumps({"verdict": "FAIL"}))
    m = {"prompts": {
        "PX_fake": {
            "status": "served",
            "gate": {"kind": "artifact", "artifact": str(art), "green_when": "verdict==PASS"},
        }
    }}
    row = audit._score_capability(m)
    assert row[2] == 0.5
    fail_lines = [l for l in row[5] if l.startswith("R9: prompt PX_fake")]
    assert fail_lines
    assert "credited as partial" in fail_lines[0]


def test_served_selftest_nonzero_exit_credited_partial_and_flagged(tmp_path):
    audit = _load_audit()
    bad_script = tmp_path / "bad_selftest.py"
    bad_script.write_text(textwrap.dedent("""
        import sys
        if "--selftest" in sys.argv:
            sys.exit(1)
        sys.exit(0)
    """))
    m = {"prompts": {
        "PX_fake": {
            "status": "served",
            "gate": {"kind": "selftest", "ref": str(bad_script), "green_when": "exit==0"},
        }
    }}
    row = audit._score_capability(m)
    assert row[2] == 0.5
    fail_lines = [l for l in row[5] if l.startswith("R9: prompt PX_fake")]
    assert fail_lines
    assert "exit=1" in fail_lines[0]


def test_served_selftest_green_exit_credited_full(tmp_path):
    audit = _load_audit()
    good_script = tmp_path / "good_selftest.py"
    good_script.write_text(textwrap.dedent("""
        import sys
        sys.exit(0)
    """))
    m = {"prompts": {
        "PX_fake": {
            "status": "served",
            "gate": {"kind": "selftest", "ref": str(good_script), "green_when": "exit==0"},
        }
    }}
    row = audit._score_capability(m)
    assert row[2] == 1.0
    assert not [l for l in row[5] if l.startswith("R9:")]


def test_selftest_that_cannot_run_does_not_crash_and_is_red():
    """A bad ref (nonexistent script) must be caught, not raise out of the reconciler."""
    audit = _load_audit()
    m = {"prompts": {
        "PX_fake": {
            "status": "served",
            "gate": {"kind": "selftest", "ref": "trial-runs/_infrastructure/no_such_script.py",
                      "green_when": "exit==0"},
        }
    }}
    row = audit._score_capability(m)   # must not raise
    assert row[2] == 0.5
    fail_lines = [l for l in row[5] if l.startswith("R9: prompt PX_fake")]
    assert fail_lines


# --------------------------------------------------------------------------- #
#  migration safety + unchanged non-served credit
# --------------------------------------------------------------------------- #

def test_served_with_no_gate_field_is_migration_warn_not_hard_red():
    audit = _load_audit()
    m = {"prompts": {"PX_fake": {"status": "served"}}}
    row = audit._score_capability(m)
    assert row[2] == 1.0   # credited as claimed during migration
    ev = row[5]
    assert any("NO GATE" in l and "migration WARN" in l for l in ev)


def test_partial_and_unbuilt_credit_unchanged():
    audit = _load_audit()
    m = {"prompts": {
        "PA": {"status": "partial", "gate": {"kind": "decision", "flip_when": "x"}},
        "PB": {"status": "unbuilt"},
        "PC": {"status": "decision-pending"},
    }}
    row = audit._score_capability(m)
    assert row[2] == (0.5 + 0.0 + 0.0) / 3


# --------------------------------------------------------------------------- #
#  full-matrix integration: the honest state today must be preserved
# --------------------------------------------------------------------------- #

def test_live_matrix_report_matches_current_inventory_and_coverage():
    # A historical readiness percentage must not force later failures out of the denominator.
    # Check report/source consistency; individual capability behavior is covered above.
    audit = _load_audit()
    rows = [check() for check in audit.CHECKS]
    expected = round(100 * sum(row[2] for row in rows) / len(rows))
    result = subprocess.run([sys.executable, str(AUDIT_PY)], cwd=REPO,
                             capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert f"readiness {expected}%" in result.stdout
    assert "R9 Capability coverage" in result.stdout
    assert "(0.64)" in result.stdout
