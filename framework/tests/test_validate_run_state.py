"""validate_run_state.py -- the lifecycle ordering/completeness/invariant gate (Task 3.2).

Mirrors the --selftest fixtures (good/bad run-dirs in temp dirs): a fully-populated survey
run PASSes; a scan missing resource_census.json while scan.json exists FAILs
(resource-census-before-route); a shape-fit run whose shape_fit.json.r5_status=="held" FAILs
(R5-before-limit-ships) even though a result-pack exists; a legacy run (dir date <
GATE_EPOCH, no inputs/) missing the new artifacts WARNs (waived-legacy) rather than FAILing;
and `--stage figure_contract` on an in-progress run validates only that prefix and PASSes.

Import the module under test by file path, not by package import: the repo root carries a
`py.py` file that shadows the real `py` package pytest depends on internally if the repo root
ends up on sys.path. Run this file from OUTSIDE the repo:
    cd /tmp && python3 -m pytest <this file's abspath> -q
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VALIDATE_RUN_STATE_PY = REPO / "trial-runs" / "_infrastructure" / "validate_run_state.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("validate_run_state_under_test", VALIDATE_RUN_STATE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_selftest_passes():
    result = subprocess.run([sys.executable, str(VALIDATE_RUN_STATE_PY), "--selftest"],
                             cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "selftest:" in result.stdout
    assert "SELFTEST FAIL" not in result.stderr
    assert result.stdout.count("  FAIL\n") == 0    # every per-case '... ok/FAIL' line ends 'ok'


def test_rundir_not_a_directory_exits_2():
    result = subprocess.run(
        [sys.executable, str(VALIDATE_RUN_STATE_PY), "--rundir", "/does/not/exist/anywhere"],
        cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 2, result.stdout + result.stderr


def test_invalid_contract_exits_3(tmp_path):
    vrs = _load_module()
    contract = vrs._base_contract(approval_required=False)   # invalid on its face
    rd = tmp_path / "2026-07-08_bad_contract"
    vrs._write_json(str(rd / "inputs" / "task_contract.json"), contract)
    result = subprocess.run(
        [sys.executable, str(VALIDATE_RUN_STATE_PY), "--rundir", str(rd)],
        cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "approval_required" in result.stdout + result.stderr


def test_survey_fixture_passes():
    vrs = _load_module()
    with tempfile.TemporaryDirectory() as td:
        rd, contract = vrs._fixture_survey_pass(td)
        result = vrs.evaluate(rd, contract)
        assert result["verdict"] == "PASS", result
        assert result["exit"] == 0
        by_name = {s["name"]: s for s in result["stages"]}
        assert by_name["resource_census"]["status"] == "PASS"
        assert by_name["trap_sweep"]["status"] == "PASS"
        assert by_name["result_pack"]["status"] == "PASS"
        assert by_name["verification"]["status"] == "PASS"


def test_scan_missing_resource_census_fails_the_invariant():
    vrs = _load_module()
    with tempfile.TemporaryDirectory() as td:
        rd, contract = vrs._fixture_scan_missing_census(td)
        result = vrs.evaluate(rd, contract)
        assert result["verdict"] == "FAIL"
        assert result["exit"] == 1
        by_name = {s["name"]: s for s in result["stages"]}
        assert by_name["resource_census"]["status"] == "FAIL"
        inv = {i["name"]: i for i in result["invariants"]}
        assert inv["resource-census-before-route"]["status"] == "FAIL"


def test_shape_fit_r5_held_fails_r5_before_limit_ships():
    vrs = _load_module()
    with tempfile.TemporaryDirectory() as td:
        rd, contract = vrs._fixture_shape_fit_r5_held(td)
        result = vrs.evaluate(rd, contract)
        assert result["verdict"] == "FAIL"
        assert result["exit"] == 1
        inv = {i["name"]: i for i in result["invariants"]}
        assert inv["R5-before-limit-ships"]["status"] == "FAIL"
        assert "held" in inv["R5-before-limit-ships"]["detail"]


def test_legacy_fixture_waives_missing_new_artifacts_to_warn():
    vrs = _load_module()
    with tempfile.TemporaryDirectory() as td:
        rd, contract = vrs._fixture_legacy(td)
        assert vrs.is_legacy(rd) is True
        result = vrs.evaluate(rd, contract)
        assert result["verdict"] == "WARN"
        assert result["exit"] == 0
        by_name = {s["name"]: s for s in result["stages"]}
        assert by_name["resource_census"]["status"] == "waived-legacy"
        assert by_name["trap_sweep"]["status"] == "waived-legacy"
        assert by_name["verification"]["status"] == "waived-legacy"
        assert not any(s["status"] == "FAIL" for s in result["stages"])
        assert not any(i["status"] == "FAIL" for i in result["invariants"])


def test_stage_prefix_validates_in_progress_run_as_pass():
    vrs = _load_module()
    with tempfile.TemporaryDirectory() as td:
        rd, contract = vrs._fixture_in_progress_scan(td)
        result = vrs.evaluate(rd, contract, stage_limit="figure_contract")
        assert result["verdict"] == "PASS"
        assert result["exit"] == 0
        assert [s["name"] for s in result["stages"]] == [
            "task_contract", "resource_census", "trap_sweep", "route", "figure_contract"]
        inv = {i["name"]: i for i in result["invariants"]}
        # stages beyond the prefix are not gated (in-progress run validates its prefix only)
        assert inv["trap-sweep-recorded"]["status"] == "N/A"
        assert inv["R5-before-limit-ships"]["status"] == "N/A"


def test_new_run_gets_no_legacy_waiver_for_missing_census():
    """A run dated at/after GATE_EPOCH with an inputs/ dir is NOT legacy -- a missing
    resource_census.json must hard-FAIL, not waive."""
    vrs = _load_module()
    with tempfile.TemporaryDirectory() as td:
        rd, contract = vrs._fixture_scan_missing_census(td)
        assert vrs.is_legacy(rd) is False
        result = vrs.evaluate(rd, contract)
        by_name = {s["name"]: s for s in result["stages"]}
        assert by_name["resource_census"]["status"] == "FAIL"


def test_backfill_plan_writes_nothing(tmp_path):
    vrs = _load_module()
    with tempfile.TemporaryDirectory() as td:
        rd, contract = vrs._fixture_scan_missing_census(td)
        before = sorted(Path(rd).rglob("*"))
        plan = vrs.backfill_plan(rd, contract)
        after = sorted(Path(rd).rglob("*"))
        assert before == after                      # nothing written
        assert "resource_census.json" in plan
        assert "trap_sweep.json" in plan


# --------------------------------------------------------------------------- #
#  Task 3.2 fix regressions (4 findings)
# --------------------------------------------------------------------------- #

def test_non_date_prefixed_dir_with_inputs_is_not_legacy_and_hard_fails(tmp_path):
    """Fix 1 [CRITICAL]: is_legacy() used to return True for ANY dir lacking a parseable date
    prefix, waiving resource_census/trap_sweep/verification on genuinely current runs (the repo
    has 60+ such active dirs). A non-date-prefixed dir that HAS an inputs/ dir must be held to
    full requirements: a complete scan-style run missing resource_census.json must hard-FAIL,
    not be silently waived as legacy."""
    vrs = _load_module()
    with tempfile.TemporaryDirectory() as td:
        rd = Path(td) / "sleptonscan_no_date_prefix"   # no YYYY-MM-DD prefix at all
        contract = vrs._base_contract(
            task_mode="scan", stat_mode="best-sr-counting", compute_plan="scan",
            detector_mode="simpleanalysis-delphes-native",
            cost_estimate={"mode": "scan", "points": 4, "walltime_h": [1, 2]})
        vrs._write_json(str(rd / "inputs" / "task_contract.json"), contract)
        vrs._write_json(str(rd / "scan.json"),
                         {"schema_version": 1, "n_planned": 2, "n_done": 2, "n_missing": 0,
                          "points": [{"tag": "p1"}, {"tag": "p2"}], "missing_tags": []})
        # deliberately NO inputs/resource_census.json
        assert vrs.is_legacy(str(rd)) is False
        result = vrs.evaluate(str(rd), contract)
        assert result["verdict"] == "FAIL", result
        assert result["exit"] == 1
        by_name = {s["name"]: s for s in result["stages"]}
        assert by_name["resource_census"]["status"] == "FAIL"    # not "waived-legacy"


def test_coverage_regex_ignores_incidental_ratio_but_catches_real_mismatch():
    """Fix 2 [IMPORTANT]: the unanchored COVERAGE_RE matched incidental ratios in prose (e.g.
    "1.47/0.74" tokenized as "47/0"), producing a false coverage FAIL on real RESULT.md prose.
    A coverage-context word must now be within ~30 chars of the match. An incidental ratio next
    to a genuine, correct "52/52 grid points" claim must not trip the check; a genuinely wrong
    coverage claim must still be caught."""
    vrs = _load_module()
    with tempfile.TemporaryDirectory() as td:
        rd = Path(td) / "coverage_regex_run"
        contract = vrs._base_contract(
            task_mode="scan", stat_mode="best-sr-counting", compute_plan="scan",
            detector_mode="simpleanalysis-delphes-native",
            cost_estimate={"mode": "scan", "points": 52, "walltime_h": [1, 2]})
        vrs._write_json(str(rd / "inputs" / "task_contract.json"), contract)
        vrs._write_json(str(rd / "scan.json"),
                         {"schema_version": 1, "n_planned": 52, "n_done": 52, "n_missing": 0,
                          "points": [], "missing_tags": []})

        vrs._write_text(str(rd / "RESULT.md"),
                         "The observed signal strength ratio S95 = 1.47/0.74 fb is quoted for "
                         "reference only.\nScan coverage: 52/52 grid points completed.\n")
        facts = vrs.discover_facts(str(rd), contract)
        status, detail = vrs.inv_result_prose_matches(str(rd), contract, facts, False, False)
        assert status != "FAIL", detail    # no false coverage FAIL from the incidental ratio

        vrs._write_text(str(rd / "RESULT.md"),
                         "The observed signal strength ratio S95 = 1.47/0.74 fb is quoted for "
                         "reference only.\nScan coverage: 40/52 points recorded.\n")
        facts = vrs.discover_facts(str(rd), contract)
        status, detail = vrs.inv_result_prose_matches(str(rd), contract, facts, False, False)
        assert status == "FAIL", detail
        assert "40/52" in detail


def test_route_tbd_judgment_requires_naming_the_specific_field():
    """Fix 3 [IMPORTANT]: check_route used to pass a TBD-judgment field if ANY escalate[] entry
    merely contained the word "judgment", even if it never named the field. The escalate list
    must NAME the specific TBD field (or a defined synonym)."""
    vrs = _load_module()
    contract = vrs._base_contract(
        detector_mode="TBD-judgment", stat_mode="TBD-judgment",
        escalate=["detector_mode needs physicist judgment"])
    status, _artifact, checks = vrs.check_route(None, contract, {}, "R", False)
    by_name = {c["name"]: c for c in checks}
    assert by_name["detector_mode"]["level"] == "WARN"
    assert by_name["stat_mode"]["level"] == "FAIL"     # named nowhere, generic "judgment" no longer counts
    assert status == "FAIL"

    contract["escalate"].append("stat_mode routing deferred")
    status, _artifact, checks = vrs.check_route(None, contract, {}, "R", False)
    by_name = {c["name"]: c for c in checks}
    assert by_name["stat_mode"]["level"] == "WARN"
    assert status == "PASS"


def test_blocked_shape_fit_refusal_must_be_documented():
    """Fix 4 [IMPORTANT]: stat_mode=="blocked-shape-fit" means statistics N/A + the refusal must
    be RECORDED (footnote 9), but nothing previously checked that the refusal was actually
    documented. Require blocking[] non-empty OR a DEVIATIONS.md with a refusal note."""
    vrs = _load_module()
    with tempfile.TemporaryDirectory() as td:
        rd = Path(td) / "no_routine_blocked_shape_fit"
        contract = vrs._base_contract(
            task_mode="no_routine", stat_mode="blocked-shape-fit", compute_plan="none",
            detector_mode="particle-level", blocking=[])
        vrs._write_json(str(rd / "inputs" / "task_contract.json"), contract)

        facts = vrs.discover_facts(str(rd), contract)
        status, detail = vrs.inv_blocked_shape_fit_refusal_recorded(str(rd), contract, facts, False, False)
        assert status == "FAIL", detail

        contract["blocking"] = ["PRODUCT-CONTRACT section 6.1: the ~40% shape-fit boundary "
                                 "refuses this statistical paradigm"]
        facts = vrs.discover_facts(str(rd), contract)
        status, detail = vrs.inv_blocked_shape_fit_refusal_recorded(str(rd), contract, facts, False, False)
        assert status == "PASS", detail


# --------------------------------------------------------------------------- #
#  Task 3.3 fix regression: scan aggregator, per-point artifacts in SIBLINGS
# --------------------------------------------------------------------------- #

def test_scan_aggregator_without_sibling_intermediates_passes_generation_and_analysis():
    """A dogfooding backfill found a real discovery gap: for task_mode=scan, the aggregator
    run dir (e.g. trial-runs/sleptonscan_fig3_SCAN) carries scan.json + scan_manifest.json, but
    the per-point generation/analysis artifacts live in SIBLING directories named by
    scan_manifest.json:points[].run_dir -- never under the aggregator --rundir. Because
    generation_artifacts()/analysis_artifact() only walk within --rundir, they used to find
    nothing and hard-FAIL the generation+analysis stages even though the scan was complete and
    correct (all 5 *_SCAN dirs hit this). A valid scan.json (points[] carrying mu95/exclusion
    data) plus a scan_manifest.json (non-empty points[]) together ATTEST that every point ran
    the full native chain -- the sibling run_dir's must NOT be required on disk."""
    vrs = _load_module()
    with tempfile.TemporaryDirectory() as td:
        rd = Path(td) / "scanagg_fig3_SCAN"
        contract = vrs._base_contract(
            task_mode="scan", stat_mode="published-likelihood", compute_plan="scan",
            detector_mode="simpleanalysis-delphes-native",
            cost_estimate={"mode": "scan", "points": 2, "walltime_h": [1, 2]})
        vrs._write_json(str(rd / "inputs" / "task_contract.json"), contract)
        vrs._write_json(str(rd / "inputs" / "resource_census.json"), vrs._resource_census_doc())
        vrs._write_json(str(rd / "inputs" / "trap_sweep.json"), vrs._trap_sweep_doc())
        vrs._write_json(str(rd / "inputs" / "figure_target.json"),
                         {"schema_version": 1, "targets": [{"figure_id": "Figure 3", "role": "scan-contour"}]})
        # ladder provenance (D11 inv_ladder_order): a complete scan climbed dry->smoke->full->scan,
        # so the aggregator carries a smoke-rung PASS record. Kept under inputs/ (not logs/) so it is
        # a run-level provenance artifact, NOT a per-point generation artifact -- generation still
        # PASSes via the scan.json+scan_manifest attestation path this test exercises.
        vrs._write_json(str(rd / "inputs" / "ladder.json"),
                         {"schema_version": 1, "generated_by": "cost_preflight.py",
                          "rungs": [{"rung": "smoke", "status": "PASS"}]})
        vrs._write_json(str(rd / "scan.json"), {
            "schema_version": 1, "n_planned": 2, "n_done": 2, "n_missing": 0, "missing_tags": [],
            "points": [
                {"tag": "m50_dm2", "m_parent": 50.0, "m_lsp": 48.0, "dm": 2.0,
                 "mu95_obs": 0.09, "mu95_exp": 0.09, "mu95_exp_band": [0.08, 0.085, 0.09, 0.095, 0.1],
                 "excluded_obs": True},
                {"tag": "m60_dm2", "m_parent": 60.0, "m_lsp": 58.0, "dm": 2.0,
                 "mu95_obs": 1.5, "mu95_exp": 1.4, "mu95_exp_band": [1.2, 1.3, 1.4, 1.5, 1.6],
                 "excluded_obs": False},
            ],
        })
        # per-point run_dirs are IN-TREE (under the rundir) but deliberately do NOT exist on disk
        # (a complete scan whose per-point dirs were cleaned; inv_outputs_in_tree N2 accepts in-tree
        # references regardless of existence, and FAILs only out-of-tree /tmp-scratchpad evidence)
        vrs._write_json(str(rd / "scan_manifest.json"), {
            "schema_version": 1, "name": "test-scan", "n_points": 2,
            "points": [
                {"tag": "m50_dm2", "m_parent": 50.0, "m_lsp": 48.0, "dm": 2.0,
                 "run_dir": str(rd / "m50_dm2"), "config": "config/m50_dm2.toml"},
                {"tag": "m60_dm2", "m_parent": 60.0, "m_lsp": 58.0, "dm": 2.0,
                 "run_dir": str(rd / "m60_dm2"), "config": "config/m60_dm2.toml"},
            ],
        })
        vrs._write_json(str(rd / "inputs" / "validations.json"), {
            "schema_version": 1, "generated_by": "validate_parameters.py", "input_fingerprint": "",
            "params": [{"name": "m_slepton", "kind": "param_validation", "role": "varied",
                        "trap": None, "check": "mass in grid", "status": "PASS"}]})
        vrs._write_json(str(rd / "verification.json"), vrs._verification_doc())
        vrs._write_text(str(rd / "VERIFICATION-LADDER.md"),
                         "| Rung | Checkpoint | Status | Notes |\n|---|---|---|---|\n"
                         "| R6 | checked-pass | checked-pass | - |\n")
        vrs._write_text(str(rd / "DEVIATIONS.md"), "# Deviations\nnone\n")
        # D12/G14 (inv_certify_before_limit): a limit-shipping scan needs a discoverable non-FAIL
        # acc*eff cert. The aggregator carries the aggregate cert (a run-level artifact under
        # outputs/); scan.json point attestation does NOT by itself satisfy the cert requirement.
        vrs._write_json(str(rd / "outputs" / "cutflow_cert.json"),
                         {"routine": "TEST", "label": "scan-aggregate", "verdict": "PASS",
                          "driving_tol": 0.15, "mu95_bound": 0.2, "rows": []})

        # the aggregate acc*eff cert is the ONLY run-level artifact under outputs/; NO per-point
        # GENERATION intermediates (sr_yields*.json / output/ / logs/) live under the aggregator
        assert not list((rd / "outputs").glob("**/sr_yields*.json"))
        assert not (rd / "output").exists()
        assert not (rd / "logs").exists()
        # and the manifest's run_dir siblings deliberately do NOT exist on disk
        assert not (rd / "m50_dm2").exists()
        assert not (rd / "m60_dm2").exists()

        result = vrs.evaluate(str(rd), contract)
        by_name = {s["name"]: s for s in result["stages"]}
        assert by_name["generation"]["status"] == "PASS", by_name["generation"]
        assert by_name["analysis"]["status"] == "PASS", by_name["analysis"]
        assert result["exit"] == 0, result
        # verdict may be WARN (a likelihood-selection-pairing WARN is expected and acceptable:
        # the bkg-only workspace / signal patch also live in the per-point siblings, not under
        # the aggregator) but must never be FAIL
        assert result["verdict"] in ("PASS", "WARN"), result
        assert not any(s["status"] == "FAIL" for s in result["stages"])
        assert not any(i["status"] == "FAIL" for i in result["invariants"])


# --------------------------------------------------------------------------- #
#  Task 4.2 fix regression: summary_plot's figure_contract level R -> O
# --------------------------------------------------------------------------- #

def test_summary_plot_figure_contract_is_optional():
    """Fix 3 [Important]: STAGE_MATRIX used to mark figure_contract R (required) for
    summary_plot, but a none-survey summary synthesizes MANY published limits into one overlay
    -- it does not reproduce a single published figure. figure_target.json is genuinely
    OPTIONAL here; completeness is carried by basis_manifest[R] + the separate
    summary_audit.py gate. A summary_plot fixture with basis_manifest.json + outputs/survey.json
    but NO inputs/figure_target.json must PASS (figure_contract resolves N/A, not FAIL)."""
    vrs = _load_module()
    base = vrs._base_contract(task_mode="summary_plot", stat_mode="none-survey", compute_plan="none")
    assert vrs.resolve_level("figure_contract", "summary_plot", base, {}) == "O"

    with tempfile.TemporaryDirectory() as td:
        rd = Path(td) / "2026-07-08_summary_plot_no_figure_target"
        contract = vrs._base_contract(
            task_mode="summary_plot", stat_mode="none-survey", compute_plan="none",
            detector_mode="particle-level")
        vrs._write_json(str(rd / "inputs" / "task_contract.json"), contract)
        vrs._write_json(str(rd / "inputs" / "resource_census.json"), vrs._resource_census_doc())
        vrs._write_json(str(rd / "inputs" / "trap_sweep.json"), vrs._trap_sweep_doc())
        # deliberately NO inputs/figure_target.json
        vrs._write_json(str(rd / "inputs" / "basis_manifest.json"), vrs._basis_manifest_doc())
        vrs._write_json(str(rd / "outputs" / "survey.json"), {"schema_version": 1, "candidates": []})
        vrs._write_json(str(rd / "verification.json"), vrs._verification_doc())
        vrs._write_text(str(rd / "VERIFICATION-LADDER.md"),
                         "| Rung | Checkpoint |\n|---|---|\n| R6 | checked-pass |\n")
        vrs._write_text(str(rd / "DEVIATIONS.md"), "# Deviations\nnone\n")

        assert not (rd / "inputs" / "figure_target.json").exists()
        result = vrs.evaluate(str(rd), contract)
        by_name = {s["name"]: s for s in result["stages"]}
        assert by_name["figure_contract"]["status"] != "FAIL", by_name["figure_contract"]
        assert result["verdict"] == "PASS", result
        assert result["exit"] == 0, result


def test_reproduce_figure_contract_still_required_without_figure_target():
    """The summary_plot R->O downgrade above must NOT leak to any other task_mode: reproduce
    (and every other figure-reproducing mode) stays R and still hard-FAILs without
    inputs/figure_target.json."""
    vrs = _load_module()
    base = vrs._base_contract(task_mode="reproduce", stat_mode="best-sr-counting", compute_plan="none")
    assert vrs.resolve_level("figure_contract", "reproduce", base, {}) == "R"

    with tempfile.TemporaryDirectory() as td:
        rd = Path(td) / "2026-07-08_reproduce_no_figure_target"
        contract = vrs._base_contract(
            task_mode="reproduce", stat_mode="best-sr-counting", compute_plan="none",
            detector_mode="particle-level")
        vrs._write_json(str(rd / "inputs" / "task_contract.json"), contract)
        vrs._write_json(str(rd / "inputs" / "resource_census.json"), vrs._resource_census_doc())
        vrs._write_json(str(rd / "inputs" / "trap_sweep.json"), vrs._trap_sweep_doc())
        # deliberately NO inputs/figure_target.json
        vrs._write_json(str(rd / "outputs" / "cutflow_cert.json"), {"verdict": "PASS"})
        vrs._write_json(str(rd / "exclusion.json"),
                         {"obs_limit": 0.5, "exp_limits": [0.2, 0.3, 0.4, 0.5, 0.6], "per_sr": {}})
        vrs._write_json(str(rd / "result.json"), {"schema_version": 1})
        vrs._write_json(str(rd / "figures.json"), {"schema_version": 1, "n_figures": 0, "figures": []})
        vrs._write_json(str(rd / "verification.json"), vrs._verification_doc())
        vrs._write_text(str(rd / "VERIFICATION-LADDER.md"),
                         "| Rung | Checkpoint |\n|---|---|\n| R6 | checked-pass |\n")
        vrs._write_text(str(rd / "DEVIATIONS.md"), "# Deviations\nnone\n")

        assert not (rd / "inputs" / "figure_target.json").exists()
        result = vrs.evaluate(str(rd), contract)
        by_name = {s["name"]: s for s in result["stages"]}
        assert by_name["figure_contract"]["status"] == "FAIL", by_name["figure_contract"]
        assert result["verdict"] == "FAIL", result
        assert result["exit"] == 1, result


def test_primary_missing_side_by_side_fails_in_non_reproduce_mode():
    """D9/G10: a scan-mode run whose PRIMARY figure target has a generated_counterpart but NO
    composed side_by_side must FAIL the invariant -- even though the figure_contract STAGE (level O,
    non-reproduce) does not check side_by_side. Non-primary targets stay advisory."""
    vrs = _load_module()
    with tempfile.TemporaryDirectory() as td:
        rd, contract = vrs._fixture_primary_unfulfilled(td)
        result = vrs.evaluate(rd, contract, stage_limit="figure_contract")
        assert result["verdict"] == "FAIL", result
        assert result["exit"] == 1
        inv = {i["name"]: i for i in result["invariants"]}
        assert inv["figure-contract-fulfilled"]["status"] == "FAIL"
        assert "side_by_side" in inv["figure-contract-fulfilled"]["detail"]
        # the figure_contract STAGE itself PASSes (non-reproduce doesn't stage-check side_by_side)
        by_name = {s["name"]: s for s in result["stages"]}
        assert by_name["figure_contract"]["status"] == "PASS"


def test_scan_with_pending_param_validation_fails():
    """D10/G12: a scan that is shipping (scan.json present) with a PENDING (or absent) parameter
    validation must FAIL inv_param_validated_before_scan; all-PASS obligations clear it."""
    vrs = _load_module()
    with tempfile.TemporaryDirectory() as td:
        rd, contract = vrs._fixture_scan_param_pending(td)
        result = vrs.evaluate(rd, contract, stage_limit="analysis")
        inv = {i["name"]: i for i in result["invariants"]}
        assert inv["param-validated-before-scan"]["status"] == "FAIL", inv
        assert result["exit"] == 1
        # flip the obligation to PASS -> the invariant clears
        vpath = str(Path(rd) / "inputs" / "validations.json")
        doc = json.load(open(vpath))
        for p in doc["params"]:
            p["status"] = "PASS"
        json.dump(doc, open(vpath, "w"))
        facts = vrs.discover_facts(rd, contract)
        status, _ = vrs.inv_param_validated_before_scan(rd, contract, facts, False, False)
        assert status == "PASS"


def test_baselined_input_edit_without_deviation_row_fails():
    """D15/G17 (post-hoc half): run_state.json records a CHECK-IN-1 baseline + a later edit to
    inputs/task_contract.json; a DEVIATIONS.md that does not NAME the changed file FAILs the
    invariant. A DEVIATIONS.md referencing it clears the FAIL."""
    vrs = _load_module()
    with tempfile.TemporaryDirectory() as td:
        rd, contract = vrs._fixture_baselined_edit_no_deviation(td)
        result = vrs.evaluate(rd, contract)
        inv = {i["name"]: i for i in result["invariants"]}
        assert inv["DEVIATIONS-on-change"]["status"] == "FAIL", inv
        assert result["verdict"] == "FAIL"
        # a DEVIATIONS.md that NAMES the changed input clears it
        vrs._write_text(str(Path(rd) / "DEVIATIONS.md"),
                        "# Deviations\n- task_contract.json edited post-CHECK-IN-1: lumi corrected.\n")
        facts = vrs.discover_facts(rd, contract)
        status, _ = vrs.inv_deviations_on_change(rd, contract, facts, False, False)
        assert status == "PASS"


def test_deviations_invariant_unchanged_without_run_state():
    """The broaden must not regress the existing behavior: a survey run with no run_state.json and no
    trap/stat/escalate trigger still PASSes DEVIATIONS-on-change."""
    vrs = _load_module()
    with tempfile.TemporaryDirectory() as td:
        rd, contract = vrs._fixture_survey_pass(td)
        facts = vrs.discover_facts(rd, contract)
        status, _ = vrs.inv_deviations_on_change(rd, contract, facts, False, False)
        assert status == "PASS"
