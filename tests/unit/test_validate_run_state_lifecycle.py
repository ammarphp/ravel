"""Lifecycle-invariant tests for validate_run_state.py (Phase 4 / L5b: D11/D12/D13/D14/N2/N4 + provenance).
Import the module under test BY FILE PATH (the repo-root py.py shadows the `py` package); run from /tmp:
    REPO="$(pwd)" && cd /tmp && python3 -m pytest "$REPO/tests/unit/test_validate_run_state_lifecycle.py" -q
"""
import importlib.util
import os
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VRS = REPO / "src" / "ravel" / "validation" / "validate_run_state.py"


def _load():
    spec = importlib.util.spec_from_file_location("validate_run_state_lifecycle_uut", VRS)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_ladder_order_fails_without_smoke_rung():
    vrs = _load()
    with tempfile.TemporaryDirectory() as td:
        rd, contract = vrs._fixture_scan_no_smoke_ladder(td)
        result = vrs.evaluate(rd, contract)
        inv = {i["name"]: i for i in result["invariants"]}
        assert inv["ladder-order"]["status"] == "FAIL", inv["ladder-order"]
        assert result["verdict"] == "FAIL" and result["exit"] == 1
        # PASS once a smoke-rung PASS artifact exists
        vrs._write_json(os.path.join(rd, "logs", "ladder.json"),
                        {"schema_version": 1, "generated_by": "cost_preflight.py",
                         "rungs": [{"rung": "smoke", "status": "PASS"}]})
        inv2 = {i["name"]: i for i in vrs.evaluate(rd, contract)["invariants"]}
        assert inv2["ladder-order"]["status"] == "PASS", inv2["ladder-order"]


def test_certify_before_limit_fails_on_fail_cert():
    vrs = _load()
    with tempfile.TemporaryDirectory() as td:
        rd, contract = vrs._fixture_reproduce_cert_fail(td)
        result = vrs.evaluate(rd, contract)
        inv = {i["name"]: i for i in result["invariants"]}
        # the analysis STAGE only WARNs on a FAIL cert; the D12 invariant is the hard block
        by_name = {s["name"]: s for s in result["stages"]}
        assert by_name["analysis"]["status"] == "WARN"
        assert inv["certify-before-limit"]["status"] == "FAIL", inv["certify-before-limit"]
        assert result["exit"] == 1
        # flip the cert to WARN -> D12 passes (WARN is delivery-allowed)
        vrs._write_json(os.path.join(rd, "outputs", "cutflow_cert.json"),
                        {"routine": "TEST", "label": "t", "verdict": "WARN",
                         "driving_tol": 0.15, "mu95_bound": 0.2, "rows": []})
        inv2 = {i["name"]: i for i in vrs.evaluate(rd, contract)["invariants"]}
        assert inv2["certify-before-limit"]["status"] == "PASS", inv2["certify-before-limit"]


def test_certify_before_limit_scan_attestation_insufficient():
    vrs = _load()
    with tempfile.TemporaryDirectory() as td:
        rd, contract = vrs._fixture_scan_cert_attestation_only(td)
        result = vrs.evaluate(rd, contract)
        inv = {i["name"]: i for i in result["invariants"]}
        # scan IS a limit-shipping mode: a COMPLETE scan with NO acc*eff cert hard-FAILs D12
        assert inv["certify-before-limit"]["status"] == "FAIL", inv["certify-before-limit"]
        # scan.json point attestation must NOT count as the cert
        assert "attestation" in inv["certify-before-limit"]["detail"]
        assert result["exit"] == 1
        facts = vrs.discover_facts(rd, contract)
        assert vrs._find_limit_cert(rd, contract, facts) is None


def test_trap_obligations_pending_blocks():
    vrs = _load()
    with tempfile.TemporaryDirectory() as td:
        rd, contract = vrs._fixture_trap_obligation_pending(td)
        result = vrs.evaluate(rd, contract)
        inv = {i["name"]: i for i in result["invariants"]}
        assert inv["trap-obligations-discharged"]["status"] == "FAIL", inv["trap-obligations-discharged"]
        assert "T8" in inv["trap-obligations-discharged"]["detail"]
        assert result["exit"] == 1
        # flip the T8 obligation to PASS -> the invariant clears
        doc = vrs.load_json_safe(rd, "inputs/trap_sweep.json")[0]
        doc["obligations"][0]["status"] = "PASS"
        vrs._write_json(os.path.join(rd, "inputs", "trap_sweep.json"), doc)
        inv2 = {i["name"]: i for i in vrs.evaluate(rd, contract)["invariants"]}
        assert inv2["trap-obligations-discharged"]["status"] == "PASS", inv2["trap-obligations-discharged"]


def test_implausible_sr_plausibility_fails_statistics():
    vrs = _load()
    with tempfile.TemporaryDirectory() as td:
        rd, contract = vrs._fixture_implausible_stats(td)
        result = vrs.evaluate(rd, contract)
        by_name = {s["name"]: s for s in result["stages"]}
        assert by_name["statistics"]["status"] == "FAIL", by_name["statistics"]
        assert any(c["name"] == "sr-plausibility" and c["level"] == "FAIL"
                   for c in by_name["statistics"]["checks"])
        assert result["exit"] == 1
        # emit a plausible verdict instead -> statistics no longer FAILs on plausibility
        vrs._write_json(os.path.join(rd, "outputs", "sr_plausibility.json"),
                        {"schema_version": 1, "generated_by": "sr_plausibility.py",
                         "input_fingerprint": "x", "verdict": "plausible", "reasons": []})
        by2 = {s["name"]: s for s in vrs.evaluate(rd, contract)["stages"]}
        assert not any(c["name"] == "sr-plausibility" and c["level"] == "FAIL"
                       for c in by2["statistics"]["checks"])


def test_outputs_in_tree_fails_on_tmp_point():
    vrs = _load()
    with tempfile.TemporaryDirectory() as td:
        rd, contract = vrs._fixture_scan_output_in_tmp(td)
        result = vrs.evaluate(rd, contract)
        inv = {i["name"]: i for i in result["invariants"]}
        assert inv["outputs-in-tree"]["status"] == "FAIL", inv["outputs-in-tree"]
        assert "p2" in inv["outputs-in-tree"]["detail"]
        assert result["exit"] == 1
        # move p2 in-tree (under the rundir) -> PASS
        doc = vrs.load_json_safe(rd, "scan_manifest.json")[0]
        doc["points"][1]["run_dir"] = os.path.join(rd, "p2_run")
        vrs._write_json(os.path.join(rd, "scan_manifest.json"), doc)
        inv2 = {i["name"]: i for i in vrs.evaluate(rd, contract)["invariants"]}
        assert inv2["outputs-in-tree"]["status"] == "PASS", inv2["outputs-in-tree"]


def test_producer_barrier_fails_on_event_count_mismatch():
    vrs = _load()
    with tempfile.TemporaryDirectory() as td:
        rd, contract = vrs._fixture_lhe_mid_write(td)
        result = vrs.evaluate(rd, contract)
        inv = {i["name"]: i for i in result["invariants"]}
        assert inv["producer-complete"]["status"] == "FAIL", inv["producer-complete"]
        assert "count mismatch" in inv["producer-complete"]["detail"] or \
               "counted" in inv["producer-complete"]["detail"]
        assert result["exit"] == 1


def test_verify_provenance_rejects_handwritten_artifact():
    vrs = _load()
    with tempfile.TemporaryDirectory() as td:
        rd = os.path.join(td, "2026-07-09_prov_handwritten")
        vrs._write_json(os.path.join(rd, "outputs", "sr_yields.json"),
                        [{"name": "SR1", "n": 5, "b": 4.0, "db": 1.0, "s": 3.0}])
        vrs._write_json(os.path.join(rd, "outputs", "pyhf_exclusion", "exclusion.json"),
                        {"obs_limit": 0.7, "exp_limits": [0.4, 0.55, 0.7, 0.95, 1.3], "per_sr": {},
                         "best_sr": "SR1"})
        # hand-written sr_plausibility.json: no generated_by
        vrs._write_json(os.path.join(rd, "outputs", "sr_plausibility.json"),
                        {"schema_version": 1, "verdict": "plausible"})
        contract = vrs._base_contract(task_mode="reproduce", stat_mode="best-sr-counting",
                                      compute_plan="full", detector_mode="simpleanalysis-delphes-native",
                                      cost_estimate={"mode": "full", "points": 1, "walltime_h": [1, 2]})
        facts = vrs.discover_facts(rd, contract)
        violations = vrs.verify_provenance_lifecycle(rd, contract, facts)
        assert any("generated_by" in v for v in violations), violations


def test_verify_provenance_rejects_fingerprint_mismatch():
    vrs = _load()
    import importlib.util
    sp_path = REPO / "src" / "ravel" / "validation" / "sr_plausibility.py"
    sp_spec = importlib.util.spec_from_file_location("sr_plausibility_for_prov", sp_path)
    sp = importlib.util.module_from_spec(sp_spec)
    sp_spec.loader.exec_module(sp)
    with tempfile.TemporaryDirectory() as td:
        rd = os.path.join(td, "2026-07-09_prov_fingerprint")
        vrs._write_json(os.path.join(rd, "outputs", "sr_yields.json"),
                        [{"name": "SR1", "n": 5, "b": 4.0, "db": 1.0, "s": 3.0}])
        vrs._write_json(os.path.join(rd, "outputs", "pyhf_exclusion", "exclusion.json"),
                        {"obs_limit": 0.7, "exp_limits": [0.4, 0.55, 0.7, 0.95, 1.3], "per_sr": {},
                         "best_sr": "SR1"})
        # faithfully EMIT (generated_by + a matching input_fingerprint)
        assert sp.main(["--rundir", rd]) == 0
        contract = vrs._base_contract(task_mode="reproduce", stat_mode="best-sr-counting",
                                      compute_plan="full", detector_mode="simpleanalysis-delphes-native",
                                      cost_estimate={"mode": "full", "points": 1, "walltime_h": [1, 2]})
        facts = vrs.discover_facts(rd, contract)
        assert vrs.verify_provenance_lifecycle(rd, contract, facts) == []   # faithful -> clean
        # TAMPER an input after emission -> the recompute no longer matches
        vrs._write_json(os.path.join(rd, "outputs", "sr_yields.json"),
                        [{"name": "SR1", "n": 999, "b": 4.0, "db": 1.0, "s": 3.0}])
        facts2 = vrs.discover_facts(rd, contract)
        viol = vrs.verify_provenance_lifecycle(rd, contract, facts2)
        assert any("input_fingerprint" in v for v in viol), viol


# ------------------------------------------------- Task 4 (A7/A8): sensitivity semantics + cert
def _a78_run(tmp_path, method=None, with_cert=False, dirname="2026-08-03_TEST_sens"):
    vrs = _load()
    rd = tmp_path / dirname
    (rd / "inputs").mkdir(parents=True)
    (rd / "outputs").mkdir()
    contract = vrs._base_contract(task_mode="anomaly_search", stat_mode="sensitivity-expected-only",
                                  compute_plan="none", detector_mode="particle-level")
    vrs._write_json(str(rd / "inputs" / "task_contract.json"), contract)
    sens = {"schema_version": 1, "windows": {}}
    if method is not None:
        sens["method"] = method
    vrs._write_json(str(rd / "sensitivity.json"), sens)
    if with_cert:
        vrs._write_json(str(rd / "outputs" / "cutflow_cert.json"),
                        {"routine": "TEST", "verdict": "PASS", "rows": []})
    return vrs, str(rd), contract


def test_sensitivity_without_pyhf_method_fails(tmp_path):
    """QM.4: an A×ε-scale borrow of a published limit is NOT an expected limit."""
    vrs, rd, contract = _a78_run(tmp_path, method=None)
    facts = vrs.discover_facts(rd, contract)
    status, _, checks = vrs.check_statistics(rd, contract, facts, "R", False)
    assert status == "FAIL"
    assert any(c["name"] == "method" and "pyhf" in c["msg"] for c in checks)


def test_sensitivity_with_pyhf_method_and_cert_passes(tmp_path):
    vrs, rd, contract = _a78_run(tmp_path, method="pyhf-counting-expected", with_cert=True)
    facts = vrs.discover_facts(rd, contract)
    status, _, checks = vrs.check_statistics(rd, contract, facts, "R", False)
    assert status == "PASS", checks
    inv_status, detail = vrs.inv_certify_before_limit(rd, contract, facts, False, False)
    assert inv_status == "PASS", detail


def test_certify_required_for_sensitivity_mode(tmp_path):
    """QM.2: the trial shipped sensitivity numbers with ZERO A×ε certification."""
    vrs, rd, contract = _a78_run(tmp_path, method="pyhf-counting-expected", with_cert=False)
    facts = vrs.discover_facts(rd, contract)
    inv_status, detail = vrs.inv_certify_before_limit(rd, contract, facts, False, False)
    assert inv_status == "FAIL", detail


def test_sensitivity_borrow_legacy_warns(tmp_path):
    vrs, rd, contract = _a78_run(tmp_path, method=None, dirname="2026-06-02_TEST_sens_legacy")
    facts = vrs.discover_facts(rd, contract)
    status, _, checks = vrs.check_statistics(rd, contract, facts, "R", True)
    assert status == "WARN"
    assert any(c["name"] == "method" and c["level"] == "WARN" for c in checks)
