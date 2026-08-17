"""lhe_check.py sidecar artifact + the lhe-check-before-shower invariant (A1, trial QM.2).

lhe_check.py must ALWAYS leave a JSON sidecar (default <lhe>.lhe_check.json, --json-out
overrides) whose verdict is EARNED ("FAIL" unless every collected check passed — never
defaults passing), and validate_run_state.py must gate shower products on that sidecar:
*.hepmc/*.hepmc.gz on disk with no *.lhe_check.json (or none recording verdict=PASS) is a
FAIL of the lhe-check-before-shower invariant; legacy (pre-epoch) runs are waived.

Import the modules under test by file path, not by package import: the repo root carries a
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
LHE_CHECK_PY = REPO / "trial-runs" / "_infrastructure" / "lhe_check.py"
VALIDATE_RUN_STATE_PY = REPO / "trial-runs" / "_infrastructure" / "validate_run_state.py"

MINIMAL_LHE = ("<LesHouchesEvents version=\"3.0\">\n<init>\n</init>\n"
               "<event>\n 1 1 1.0 1.0 0.0075 0.118\n</event>\n</LesHouchesEvents>\n")


def _load_module():
    spec = importlib.util.spec_from_file_location("validate_run_state_under_test", VALIDATE_RUN_STATE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
#  the sidecar emitter (lhe_check.py)
# --------------------------------------------------------------------------- #

def test_sidecar_written_and_verdict_earned(tmp_path):
    lhe = tmp_path / "events.lhe"
    lhe.write_text(MINIMAL_LHE)
    r = subprocess.run([sys.executable, str(LHE_CHECK_PY), str(lhe)],
                       cwd=REPO, capture_output=True, text=True)
    side = tmp_path / "events.lhe.lhe_check.json"
    assert side.is_file(), r.stdout + r.stderr
    doc = json.loads(side.read_text())
    assert doc["generated_by"] == "lhe_check.py"
    assert doc["schema_version"] == 1
    assert doc["lhe"] == str(lhe)
    assert doc["verdict"] in ("PASS", "FAIL")
    assert doc["checks"], "checks list must be populated"
    for c in doc["checks"]:
        assert set(c) >= {"name", "level", "msg"}
    # this clean single-weight LHE has no failing check -> the verdict is earned as PASS
    assert doc["verdict"] == "PASS"
    assert r.returncode == 0, r.stdout + r.stderr


def test_sidecar_verdict_fail_on_failed_check(tmp_path):
    # a --expect-mass for a PDG absent from event+banner is a FAIL check -> verdict FAIL,
    # exit nonzero, and the sidecar still gets written (never defaults passing)
    lhe = tmp_path / "events.lhe"
    lhe.write_text(MINIMAL_LHE)
    r = subprocess.run([sys.executable, str(LHE_CHECK_PY), str(lhe),
                        "--expect-mass", "1000021:1000"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode != 0
    doc = json.loads((tmp_path / "events.lhe.lhe_check.json").read_text())
    assert doc["verdict"] == "FAIL"
    assert any(c["level"] == "FAIL" for c in doc["checks"])


def test_json_out_override(tmp_path):
    lhe = tmp_path / "events.lhe"
    lhe.write_text(MINIMAL_LHE)
    out = tmp_path / "elsewhere" / "guard.json"
    out.parent.mkdir()
    r = subprocess.run([sys.executable, str(LHE_CHECK_PY), str(lhe), "--json-out", str(out)],
                       cwd=REPO, capture_output=True, text=True)
    assert out.is_file(), r.stdout + r.stderr
    assert not (tmp_path / "events.lhe.lhe_check.json").exists()
    assert json.loads(out.read_text())["generated_by"] == "lhe_check.py"


# --------------------------------------------------------------------------- #
#  the invariant (validate_run_state.py :: inv_lhe_check_before_shower)
# --------------------------------------------------------------------------- #

def _shower_rundir(tmp_path, vrs, name="2026-08-01_TEST_shower-no-check"):
    rd = tmp_path / name
    (rd / "inputs").mkdir(parents=True)
    contract = vrs._base_contract(task_mode="reproduce", compute_plan="smoke")
    vrs._write_json(str(rd / "inputs" / "task_contract.json"), contract)
    (rd / "outputs").mkdir()
    (rd / "outputs" / "showered.hepmc.gz").write_bytes(b"\x1f\x8b")
    return rd, contract


def test_invariant_fails_when_shower_ran_without_lhe_check(tmp_path):
    vrs = _load_module()          # validate_run_state via file-path spec
    rd, contract = _shower_rundir(tmp_path, vrs)
    facts = vrs.discover_facts(str(rd), contract)
    assert facts["hepmc_hits"] == ["outputs/showered.hepmc.gz"]
    assert facts["lhe_check_artifacts"] == []
    status, detail = vrs.inv_lhe_check_before_shower(str(rd), contract, facts, False, False)
    assert status == "FAIL" and "lhe_check" in detail


def test_invariant_passes_with_pass_sidecar(tmp_path):
    vrs = _load_module()
    rd, contract = _shower_rundir(tmp_path, vrs)
    vrs._write_json(str(rd / "outputs" / "unweighted_events.lhe.lhe_check.json"),
                    {"schema_version": 1, "generated_by": "lhe_check.py",
                     "generated_utc": "", "lhe": "x.lhe", "verdict": "PASS", "checks": []})
    facts = vrs.discover_facts(str(rd), contract)
    status, detail = vrs.inv_lhe_check_before_shower(str(rd), contract, facts, False, False)
    assert status == "PASS", detail


def test_invariant_fails_on_fail_verdict_sidecar(tmp_path):
    vrs = _load_module()
    rd, contract = _shower_rundir(tmp_path, vrs)
    vrs._write_json(str(rd / "outputs" / "unweighted_events.lhe.lhe_check.json"),
                    {"schema_version": 1, "generated_by": "lhe_check.py",
                     "generated_utc": "", "lhe": "x.lhe", "verdict": "FAIL", "checks": []})
    facts = vrs.discover_facts(str(rd), contract)
    status, detail = vrs.inv_lhe_check_before_shower(str(rd), contract, facts, False, False)
    assert status == "FAIL" and "FAIL" in detail


def test_invariant_fails_when_no_sidecar_records_pass(tmp_path):
    # a sidecar exists but its verdict is unreadable/absent -> must NOT default to passing
    vrs = _load_module()
    rd, contract = _shower_rundir(tmp_path, vrs)
    vrs._write_json(str(rd / "outputs" / "unweighted_events.lhe.lhe_check.json"),
                    {"schema_version": 1, "generated_by": "lhe_check.py"})   # no verdict key
    facts = vrs.discover_facts(str(rd), contract)
    status, detail = vrs.inv_lhe_check_before_shower(str(rd), contract, facts, False, False)
    assert status == "FAIL" and "PASS" in detail


def test_invariant_waived_for_legacy_run(tmp_path):
    vrs = _load_module()
    rd, contract = _shower_rundir(tmp_path, vrs)
    facts = vrs.discover_facts(str(rd), contract)
    status, detail = vrs.inv_lhe_check_before_shower(str(rd), contract, facts, True, False)
    assert status == "waived-legacy"


def test_invariant_passes_with_no_shower_products(tmp_path):
    vrs = _load_module()
    rd = tmp_path / "2026-08-01_TEST_no-shower"
    (rd / "inputs").mkdir(parents=True)
    contract = vrs._base_contract(task_mode="reproduce", compute_plan="smoke")
    vrs._write_json(str(rd / "inputs" / "task_contract.json"), contract)
    facts = vrs.discover_facts(str(rd), contract)
    status, detail = vrs.inv_lhe_check_before_shower(str(rd), contract, facts, False, False)
    assert status == "PASS" and "no shower products" in detail


def test_registered_in_invariants_and_selftest_case_green():
    vrs = _load_module()
    assert any(name == "lhe-check-before-shower" and target == "generation"
               for name, target, _fn in vrs.INVARIANTS)
    r = subprocess.run([sys.executable, str(VALIDATE_RUN_STATE_PY), "--selftest"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "lhe-check-before-shower" in r.stdout or "lhe_check" in r.stdout
