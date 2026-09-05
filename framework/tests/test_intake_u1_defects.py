# Regression tests for the 2026-08-27 U1-leptoquark head-to-head intake defects
# (framework/RELATED-WORK-ADJUDICATION.md section II.4 honesty ledger, items 1 and 6):
#   1a. task_mode keyword rules fired "projection" on "left-handed projection operator"
#       inside a user-pasted Lagrangian glossary (model-description text, not a task ask).
#   1b. the mass extractor pulled sqrt(s)=13000 and an mT bin edge (3200) as candidate
#       masses and missed the comma-separated 9-value grid sharing one trailing unit.
#   2.  detector_mode had no value for "custom Delphes, uncertified" (CR-134): the run had
#       to be recorded particle-level with the route nuance buried in assumptions[].
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
INFRA = REPO / "trial-runs" / "_infrastructure"
U1_PROMPT = (REPO / "trial-runs"
             / "2026-08-27_taunu-recast-ins1649273-ins1684340_U1-leptoquark"
             / "inputs" / "request_verbatim.txt")
U1_GRID = [750, 1000, 1250, 1500, 2000, 2500, 3000, 4000, 5000]


def _mod(name):
    spec = importlib.util.spec_from_file_location(name, INFRA / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# --------------------------------------------------------------- 1a + 1b: the verbatim prompt
def test_u1_verbatim_prompt_routes_scan_with_the_9_mass_grid():
    if not U1_PROMPT.is_file():
        pytest.skip("U1 run record not in this tree (distribution export)")
    rp = _mod("route_prompt")
    c = rp.route(U1_PROMPT.read_text())
    assert c["task_mode"] == "scan", f"want scan, got {c['task_mode']}"
    assert c["targets"]["masses_gev"] == U1_GRID, c["targets"]["masses_gev"]
    assert _mod("validate_task_contract").validate(c) == []


# --------------------------------------------------------------- 1a: word-context guards
def test_glossary_projection_operator_does_not_route_projection():
    rp = _mod("route_prompt")
    p = ("Initiate: perform a mass scan for my model over the grid below.\n"
         "- $P_L$ is the left-handed projection operator.\n"
         "- masses: 700, 800, 900 GeV\n")
    assert rp.route(p)["task_mode"] == "scan"


def test_inline_projection_operator_phrase_does_not_route_projection():
    rp = _mod("route_prompt")
    p = ("Initiate: the coupling uses the left-handed projection operator P_L; "
         "scan the mass plane from 100 to 500 GeV for arXiv:2401.00001.")
    assert rp.route(p)["task_mode"] == "scan"


def test_genuine_projection_ask_still_routes_projection():
    rp = _mod("route_prompt")
    p = ("Construct an expected Run-3 (400 fb-1) exclusion contour for the ATLAS "
         "displaced-track analysis (arXiv:2401.14046).")
    assert rp.route(p)["task_mode"] == "projection"


# --------------------------------------------------------------- 1b: mass plausibility
def test_comma_list_with_one_trailing_unit_is_parsed():
    rp = _mod("route_prompt")
    c = rp.route("Initiate: reinterpret arXiv:2401.00001 with a mass scan at "
                 "750, 1000, 1250 GeV")
    assert c["targets"]["masses_gev"] == [750, 1000, 1250]


def test_sqrt_s_and_bin_edges_are_not_masses():
    rp = _mod("route_prompt")
    p = ("Initiate: reinterpret arXiv:2401.00001 for a 2 TeV Z' at the 13 TeV LHC; "
         "the mT distribution has 22 bins from 250 to 3200 GeV.")
    assert rp.route(p)["targets"]["masses_gev"] == [2000]


def test_markdown_table_values_are_not_masses():
    rp = _mod("route_prompt")
    p = ("Initiate: reinterpret arXiv:2401.00001 -- is a slepton at 300 GeV excluded?\n"
         "| mT bin | yield |\n"
         "| 320-500 GeV | 1203 |\n")
    assert rp.route(p)["targets"]["masses_gev"] == [300]


def test_route_prompt_selftest_still_green():
    r = subprocess.run([sys.executable, str(INFRA / "route_prompt.py"), "--selftest"],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# --------------------------------------------------------------- CR-131: run_state init at intake
def test_contract_write_initializes_run_state(tmp_path):
    out = tmp_path / "inputs" / "task_contract.json"
    r = subprocess.run([sys.executable, str(INFRA / "route_prompt.py"),
                        "--prompt", "Initiate: is supersymmetry dead?",
                        "--out", str(out)],
                       cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    state_path = tmp_path / "run_state.json"
    assert state_path.is_file(), "route_prompt --out must init run_state.json (CR-131/N11)"
    state = json.loads(state_path.read_text())
    assert state["open_defect_notes"] == []
    assert "session_id" in state


# --------------------------------------------------------------- 2: detector_mode enum + threading
def _contract_custom_delphes():
    return {"schema_version": 1,
            "prompt": "Initiate: recast the tau_h+MET searches vs the U1 leptoquark",
            "task_mode": "reinterpret",
            "detector_mode": "delphes-custom-uncertified",
            "stat_mode": "sensitivity-expected-only",
            "required_user_inputs": [], "assumptions": ["F1: custom Delphes selection"],
            "compute_plan": "smoke", "approval_required": True,
            "escalate": ["figure target: [judgment] at CHECK-IN 1"]}


def test_task_contract_accepts_delphes_custom_uncertified():
    vtc = _mod("validate_task_contract")
    assert "delphes-custom-uncertified" in vtc.DETECTOR_MODES
    assert vtc.validate(_contract_custom_delphes()) == []


def test_result_pack_enum_carries_delphes_custom_uncertified():
    assert "delphes-custom-uncertified" in _mod("result_pack").DETECTOR_MODES


def test_run_state_route_gate_warns_on_uncertified_custom_delphes(tmp_path):
    vrs = _mod("validate_run_state")
    status, _path, checks = vrs.check_route(str(tmp_path), _contract_custom_delphes(),
                                            {}, "S", False)
    assert status == "WARN"
    row = next(c for c in checks if c["name"] == "detector_mode")
    assert row["level"] == "WARN"
    assert "uncertified" in row["msg"].lower()
    assert "exclusion of record" in row["msg"].lower()


def _checkin1(extra_iv=""):
    return {"schema_version": 1, "kind": "checkin1", "sections": {
        "i": "preamble", "i-b": "census", "ii": "gallery (no files cited)",
        "iii": {"figure_id": "Fig. 3", "waypoint": "A x eff vs published Table 7"},
        "iv": "plan" + extra_iv, "v": [{"id": "F1", "why": "x"}],
        "vi": ["answer", "ask", "propose"]}}


def test_checkin1_must_surface_uncertified_detector_route(tmp_path):
    vc = _mod("validate_checkin")
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "task_contract.json").write_text(
        json.dumps(_contract_custom_delphes()))
    errs = vc.validate(_checkin1(), base_dir=str(tmp_path))
    assert any("uncertified" in e for e in errs), errs
    ok = vc.validate(_checkin1(" -- detector route: custom Delphes, UNCERTIFIED; "
                               "proxy only, no exclusion of record until certified"),
                     base_dir=str(tmp_path))
    assert ok == []


def test_checkin1_without_custom_delphes_contract_unaffected(tmp_path):
    vc = _mod("validate_checkin")
    (tmp_path / "inputs").mkdir()
    plain = _contract_custom_delphes()
    plain["detector_mode"] = "particle-level"
    (tmp_path / "inputs" / "task_contract.json").write_text(json.dumps(plain))
    assert vc.validate(_checkin1(), base_dir=str(tmp_path)) == []
