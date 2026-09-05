"""Adversarial intake contracts must fail before the lifecycle or generation runs.

Run from outside the repository because its legacy py.py shadows pytest's dependency.
"""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
INFRA = REPO / "trial-runs" / "_infrastructure"
spec = importlib.util.spec_from_file_location("task_contract_under_test", INFRA / "validate_task_contract.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def contract(**overrides):
    value = {
        "schema_version": 1, "prompt": "Reproduce the published exclusion.",
        "task_mode": "reproduce", "detector_mode": "particle-level",
        "stat_mode": "best-sr-counting", "required_user_inputs": [], "assumptions": [],
        "compute_plan": "full", "approval_required": True,
        "targets": {"model": None, "masses_gev": [0, 100], "lumi_fb": 139},
        "cost_estimate": {"mode": "full", "points": 1, "walltime_h": [1, 2]},
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize("version", [None, True, False, 1.0, "1", 0, 2, 999])
def test_schema_version_is_an_exact_supported_integer(version):
    assert any("schema_version" in e for e in validator.validate(contract(schema_version=version)))


def test_missing_version_is_not_silently_grandfathered():
    value = contract()
    del value["schema_version"]
    assert any("schema_version" in e for e in validator.validate(value))


@pytest.mark.parametrize("overrides,needle", [
    ({"cost_estimate": "approved"}, "cost_estimate"),
    ({"cost_estimate": []}, "cost_estimate"),
    ({"cost_estimate": {}}, "cost_estimate"),
    ({"targets": []}, "targets"),
    ({"targets": {"masses_gev": [True]}}, "masses_gev"),
    ({"targets": {"lumi_fb": -139}}, "lumi_fb"),
    ({"task_mode": "unsupported", "blocking": [False]}, "blocking"),
    ({"approval_require": False}, "approval_require"),
    ({"targets": {"mass_gev": [100]}}, "mass_gev"),
    ({"prompt": " \n\t"}, "prompt"),
    ({"notes": ["not text"]}, "notes"),
    ({"required_user_inputs": [None]}, "required_user_inputs"),
    ({"assumptions": [""]}, "assumptions"),
    ({"blocking": "refused"}, "blocking"),
    ({"escalate": {"detector_mode": "unknown"}}, "escalate"),
])
def test_malformed_optional_and_required_fields_are_rejected(overrides, needle):
    assert any(needle in e for e in validator.validate(contract(**overrides)))


@pytest.mark.parametrize("field", ["analysis", "arxiv", "inspire", "figures"])
@pytest.mark.parametrize("value", ["one", [1], [True], [{}], [" "]])
def test_target_identifiers_are_lists_of_nonblank_strings(field, value):
    assert any(field in e for e in validator.validate(contract(targets={field: value})))


@pytest.mark.parametrize("bad", [True, False, "100", -1, float("nan"), float("inf"), -float("inf")])
def test_mass_values_are_finite_nonnegative_numbers(bad):
    assert any("masses_gev[0]" in e for e in validator.validate(contract(targets={"masses_gev": [bad]})))


@pytest.mark.parametrize("bad", [True, "139", 0, -1, float("nan"), float("inf")])
def test_luminosity_is_positive_and_finite_or_explicitly_unresolved(bad):
    assert any("lumi_fb" in e for e in validator.validate(contract(targets={"lumi_fb": bad})))


@pytest.mark.parametrize("field", ["points", "events_per_point", "parallel"])
@pytest.mark.parametrize("bad", [True, False, 0, -1, 1.0, "4", float("nan"), float("inf")])
def test_cost_counts_are_positive_exact_integers(field, bad):
    value = contract()
    value["cost_estimate"][field] = bad
    assert any(field in e for e in validator.validate(value))


@pytest.mark.parametrize("interval", [[2, 1], [-1, 2], [True, 2], [1], [1, 2, 3], "1-2", [0, float("nan")], [0, float("inf")]])
def test_budget_intervals_cannot_hide_invalid_or_reversed_values(interval):
    value = contract()
    value["cost_estimate"]["walltime_h"] = interval
    assert any("walltime_h" in e for e in validator.validate(value))


@pytest.mark.parametrize("change", [
    {"mode": "none"}, {"mode": "full", "points": 1},
    {"mode": "full", "walltime_h": [1, 2]},
    {"mode": "full", "points": 1, "walltime_h": [0, 0]},
    {"mode": "full", "points": 1, "walltime_h": [1, 2], "disk_gb_peak": -1},
    {"mode": "full", "points": 1, "walltime_h": [1, 2], "walltime_hours": [1, 2]},
])
def test_compute_budget_is_structured_and_matches_requested_work(change):
    assert any("cost_estimate" in e for e in validator.validate(contract(cost_estimate=change)))


@pytest.mark.parametrize("blocking", [[], [""], [" \n"]])
def test_unsupported_requires_a_real_refusal_reason(blocking):
    assert validator.validate(contract(task_mode="unsupported", compute_plan="none", cost_estimate={"mode": "none", "walltime_h": [0, 0]}, blocking=blocking))


def test_existing_cross_field_compute_blocks_remain_enforced():
    for overrides in ({"approval_required": 1}, {"task_mode": "survey"},
                      {"task_mode": "summary_plot"}, {"stat_mode": "blocked-shape-fit"},
                      {"task_mode": "unsupported", "blocking": ["Discovery request refused."]}):
        assert validator.validate(contract(**overrides)), overrides


def test_valid_minimal_contract_and_unresolved_targets_are_not_filled_in():
    value = contract(targets={"model": None, "process": None, "lumi_fb": None, "masses_gev": [0, 100.5]})
    before = copy.deepcopy(value)
    assert validator.validate(value) == []
    assert value == before
    for key in ("targets", "cost_estimate"):
        value.pop(key, None)
    value["compute_plan"] = "smoke"
    assert validator.validate(value) == []  # cost was historically optional before full/scan


def test_real_router_and_cost_producer_contracts_validate():
    # Importing the CLI via its documented entry point also checks its integration gate.
    for prompt in ("Survey ATLAS searches for a slepton.",
                   "Reproduce SUSY-2018-16 for the slepton-bino model.",
                   "Reproduce Fig.5 of arXiv:2408.00049 with wider Z' widths.",
                   "Discover a new particle at 5 sigma."):
        result = subprocess.run([sys.executable, str(INFRA / "route_prompt.py"), "--prompt", prompt, "--print"], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert validator.validate(json.loads(result.stdout)) == []


def test_all_committed_trial_contracts_have_known_strict_or_archive_status():
    historical_missing_points = {
        "2026-07-08_PROJ_hvt-zprime-ww-isr-boosted",
        "2026-07-11_REPRO_atlas14636_hvt-zprime-ww",
    }
    paths = sorted((REPO / "trial-runs").glob("*/inputs/task_contract.json"))
    if not paths:
        pytest.skip("Public distributions omit development trial artifacts")
    for path in paths:
        value = json.loads(path.read_text())
        errors = validator.validate(value)
        if path.parents[1].name in historical_missing_points:
            assert errors == ["cost_estimate.points is required for compute_plan=scan"]
            with pytest.warns(UserWarning, match="ARCHIVE ONLY"):
                assert validator.validate(value, legacy=True) == []
        else:
            assert errors == [], str(path)


def test_archival_waiver_is_explicit_narrow_and_never_infers_numbers():
    value = contract(cost_estimate={"mode": "full", "walltime_h": [1, 2],
                                   "disk_gb_peak": 10, "note": "Historical cost note."})
    original = copy.deepcopy(value)
    assert validator.validate(value) == ["cost_estimate.points is required for compute_plan=full"]
    with pytest.warns(UserWarning, match="not a valid live-compute contract"):
        assert validator.validate(value, legacy=True) == []
    assert value == original
    for key in ("note", "disk_gb_peak"):
        damaged = copy.deepcopy(value)
        del damaged["cost_estimate"][key]
        assert validator.validate(damaged, legacy=True)
    for invalid in (contract(schema_version=True), contract(approval_required=False),
                    contract(targets={"masses_gev": [float("nan")]}),
                    contract(cost_estimate={"mode": "full", "points": False, "walltime_h": [1, 2]})):
        assert validator.validate(invalid, legacy=True)


def test_archival_cli_does_not_call_it_a_valid_live_contract(tmp_path):
    value = contract(cost_estimate={"mode": "full", "walltime_h": [1, 2],
                                   "disk_gb_peak": 10, "note": "Historical cost note."})
    path = tmp_path / "archived-contract.json"
    path.write_text(json.dumps(value))
    strict = subprocess.run([sys.executable, str(INFRA / "validate_task_contract.py"), str(path)], capture_output=True, text=True)
    archive = subprocess.run([sys.executable, str(INFRA / "validate_task_contract.py"), "--legacy", str(path)], capture_output=True, text=True)
    assert strict.returncode == 1
    assert archive.returncode == 0
    assert "NOT live-compute validation" in archive.stdout
    assert "ARCHIVE ONLY" in archive.stderr


@pytest.mark.parametrize("cost", [
    {"mode": "scan", "points": 30, "walltime_h_naive": [4, 6.7],
     "walltime_h_with_lhe_reuse": [2.5, 4], "lhe_reuse_note": "Reuse at fixed ME mass."},
    {"mode": "scan", "points": 52, "walltime_h": [26, 43.3]},
])
def test_historical_named_budget_formats_are_validated_without_coercion(cost):
    value = contract(compute_plan="scan", cost_estimate=cost)
    original = copy.deepcopy(value)
    assert validator.validate(value) == []
    assert value == original
    for key in ("walltime_h", "walltime_h_naive", "walltime_h_with_lhe_reuse"):
        if key in cost:
            bad = copy.deepcopy(value)
            bad["cost_estimate"][key] = [2, 1]
            assert any(key in error for error in validator.validate(bad))


def test_svj_alternate_budget_requires_both_scenarios_and_the_explanation():
    cost = {"mode": "scan", "points": 30, "walltime_h_naive": [4, 6.7],
            "walltime_h_with_lhe_reuse": [2.5, 4], "lhe_reuse_note": "Reuse at fixed ME mass."}
    for missing in ("walltime_h_naive", "walltime_h_with_lhe_reuse", "lhe_reuse_note"):
        bad = {key: value for key, value in cost.items() if key != missing}
        assert validator.validate(contract(compute_plan="scan", cost_estimate=bad))


@pytest.mark.parametrize("raw,needle", [
    ('{"schema_version": 1, "schema_version": 1}', "duplicate"),
    ('{"targets": {"lumi_fb": 139, "lumi_fb": 1}}', "duplicate"),
    ('{"targets": {"lumi_fb": NaN}}', "non-finite"),
    ('{"targets": {"lumi_fb": Infinity}}', "non-finite"),
])
def test_cli_rejects_ambiguous_or_nonstandard_json(tmp_path, raw, needle):
    path = tmp_path / "contract.json"
    path.write_text(raw)
    result = subprocess.run([sys.executable, str(INFRA / "validate_task_contract.py"), str(path)], capture_output=True, text=True)
    assert result.returncode == 1
    assert needle in (result.stdout + result.stderr).lower()
    assert "Traceback" not in result.stderr


def test_cli_catches_exponent_overflow_as_nonfinite(tmp_path):
    raw = json.dumps(contract()).replace('"lumi_fb": 139', '"lumi_fb": 1e9999')
    path = tmp_path / "contract.json"
    path.write_text(raw)
    result = subprocess.run([sys.executable, str(INFRA / "validate_task_contract.py"), str(path)], capture_output=True, text=True)
    assert result.returncode == 1
    assert "finite" in result.stdout + result.stderr


def test_schema_is_machine_readable_and_carries_compatibility_policy():
    result = subprocess.run([sys.executable, str(INFRA / "validate_task_contract.py"), "--schema"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    schema = json.loads(result.stdout)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert "schema_version" in schema["required"]
    assert "compatibility" in schema["$comment"].lower()


@pytest.mark.parametrize("overrides,needle", [
    ({"targets": {"model": {"name": "SUSY"}}}, "model"),
    ({"targets": {"process": False}}, "process"),
    ({"traps_hit": [{"id": "T7", "evidence": "paper", "consequence": "gate", "flag_number": True}]}, "flag_number"),
    ({"traps_hit": [{"id": "T7"}]}, "evidence"),
    ({"traps_procedural": [{"id": "T11", "note": False}]}, "note"),
    ({"channels_under_consideration": {"semileptonic": ["channel"]}}, "semileptonic"),
    ({"published_dark_sector_fixed": {"nFlav_HV": 1.0}}, "nFlav_HV"),
    ({"published_dark_sector_fixed": {"Lambda_d_gev": 0}}, "Lambda_d_gev"),
    ({"published_dark_sector_fixed": {"m_qdark_gev": True}}, "m_qdark_gev"),
    ({"option_c_caps": [False]}, "option_c_caps"),
])
def test_historical_annotations_are_typed_not_a_schema_escape(overrides, needle):
    assert any(needle in e for e in validator.validate(contract(**overrides)))


@pytest.mark.parametrize("field,bad", [("disk_gb", True), ("walltime_h", [2, 1]), ("walltime_h", [0, float("nan")])])
def test_nested_waypoint_cost_is_checked(field, bad):
    value = contract()
    value["cost_estimate"]["waypoint_smoke"] = {"disk_gb": 1, "walltime_h": [0.1, 0.35], field: bad}
    assert any("waypoint_smoke" in e for e in validator.validate(value))


def _lifecycle():
    spec = importlib.util.spec_from_file_location("contract_lifecycle_under_test", INFRA / "validate_run_state.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("value", [None, [], contract(schema_version=True), contract(approval_required=False), contract(targets={"lumi_fb": -1})])
def test_lifecycle_library_entry_cannot_bypass_contract_validation(tmp_path, value):
    result = _lifecycle().evaluate(str(tmp_path), value, stage_limit="task_contract")
    assert result["exit"] == 3
    assert result["verdict"] == "FAIL"
    assert result["stages"][0]["name"] == "task_contract"
    assert all(check["level"] == "FAIL" for check in result["stages"][0]["checks"])


@pytest.mark.parametrize("raw", ['{"schema_version": 1, "schema_version": 1}', '{"value": NaN}', '{"value": Infinity}'])
def test_live_contract_loader_uses_strict_json(tmp_path, raw):
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "task_contract.json").write_text(raw)
    value, _path, error = _lifecycle().load_contract_for(str(tmp_path), None)
    assert value is None
    assert error and "cannot read/parse contract" in error


def test_advancing_to_first_stage_cannot_bypass_schema(tmp_path):
    (tmp_path / "inputs").mkdir()
    path = tmp_path / "inputs" / "task_contract.json"
    path.write_text(json.dumps(contract(compute_plan="smoke", cost_estimate={"mode": "smoke", "walltime_h": [0.1, 0.35]})))
    cmd = [sys.executable, str(INFRA / "workflow_state.py")]
    init = subprocess.run([*cmd, "init", "--rundir", str(tmp_path)], capture_output=True, text=True)
    assert init.returncode == 0, init.stderr
    before = (tmp_path / "run_state.json").read_bytes()
    path.write_text(json.dumps(contract(schema_version=True)))
    advance = subprocess.run([*cmd, "advance", "--rundir", str(tmp_path), "--to", "task_contract"], capture_output=True, text=True)
    assert advance.returncode == 1
    assert "schema_version" in advance.stderr
    assert (tmp_path / "run_state.json").read_bytes() == before
