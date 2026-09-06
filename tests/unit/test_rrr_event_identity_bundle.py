"""Portable evidence checks against denominator, missingness and custody corruption."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT/"evidence/audits/2026-09-06-rrr-event-identity"
SPEC = importlib.util.spec_from_file_location("rrr_event_identity_verify", BUNDLE/"verify.py")
verify = importlib.util.module_from_spec(SPEC)
exec(compile((BUNDLE/"verify.py").read_bytes(), str(BUNDLE/"verify.py"), "exec"), verify.__dict__)


@pytest.fixture
def data():
    return verify.read(BUNDLE/"data/evidence.json")


def test_complete_offline_bundle():
    result = verify.verify()
    assert result["limit_roots"] == 6
    assert result["raw_event_payloads_read"] == 0
    assert result["selected_source_projection_checked"] is False


@pytest.mark.parametrize("path,value", [
    (("scope", "physics_certified"), True),
    (("scope", "partition_predeclared_equivalence_test"), True),
    (("fresh10098", "reference", "parent_GeV"), 150),
    (("fresh10098", "reference", "public_uncertainty"), 0),
    (("fresh10098", "reference", "expected_bands"), []),
    (("fresh10098", "inclusive", "sigma_lo_pb"), .1350625),
    (("fresh10098", "native", "K"), 1.18**2),
    (("fresh10098", "limits", 0, "inclusive_sigma95_fb"), 238.13),
    (("fresh10098", "limits", 0, "mu95"), True),
    (("fresh10098", "limits", 0, "residual_percent"), 0),
    (("fresh10098", "limits", 1, "ratio_to_reference"), 1),
    (("fresh10098", "limits", 0, "inclusive_generator_integration_only_error_pb"), 0),
    (("fresh10098", "unions", 1, "original_denominator"), 11),
    (("fresh10098", "unions", 1, "selected_events"), 400),
    (("fresh10098", "unions", 1, "histogram_relative_mc"), .05),
    (("fresh10098", "bins", 0, "selected_events"), 20001),
    (("fresh10098", "numerical", "fresh_check_evaluations"), 0),
    (("lower150140", "original_generated_events"), 9046),
    (("lower150140", "hard_population", "below50"), 10953),
    (("lower150140", "join_evidence", "LHE_HepMC_unique_content"), 19999),
    (("lower150140", "rows", 0, "original_exposure_estimates", "atleast50", "original_generated_events"), 9046),
    (("lower150140", "rows", 0, "original_exposure_estimates", "atleast50", "streams", 0, "N"), 9046),
    (("lower150140", "rows", 0, "nominal_60k", "streams", 0, "N"), 40000),
    (("lower150140", "rows", 0, "nominal_60k", "precision_status"), "certified"),
    (("lower150140", "rows", 0, "upper_slice_over_nominal", "conditional_standard_error"), 0),
    (("lower150140", "rows", 0, "upper_slice_over_nominal", "conditional_plus_integration_95pct_interval"), [.9, 1.1]),
    (("lower150140", "rows", 0, "upper_slice_over_nominal", "decision"), "equivalent"),
    (("replay", "joined_events"), 19999),
    (("replay", "new_hard_events"), 20000),
    (("replay", "streams", 1, "sha256"), "0"*64),
    (("replay", "streams", 1, "complete_eof"), False),
])
def test_invalid_scientific_evidence_rejects(data, path, value):
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        verify.validate(data)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "NaN", False])
def test_invalid_root_type_or_value_rejects(data, value):
    data["fresh10098"]["limits"][0]["mu95"] = value
    with pytest.raises(ValueError):
        verify.validate(data)


@pytest.mark.parametrize("population", ["roots", "fresh", "partition", "regions"])
def test_missing_population_rejects(data, population):
    groups = {"roots": data["fresh10098"]["limits"], "fresh": data["fresh10098"]["bins"],
              "partition": data["lower150140"]["rows"], "regions": data["lower150140"]["native_region_moments"]}
    group = groups[population]
    if isinstance(group, dict):
        group.pop(next(iter(group)))
    else:
        group.pop()
    with pytest.raises(ValueError):
        verify.validate(data)


def test_zero_selected_is_not_precise(data):
    row = next(row for row in data["fresh10098"]["bins"] if not row["selected_events"])
    row["histogram_relative_mc"] = 0
    with pytest.raises(ValueError):
        verify.validate(data)


def test_native_region_complementary_moments_are_checked(data):
    region = next(p for p in data["lower150140"]["native_region_moments"].values() if p["all"]["selected"])
    region["all"]["sumw_pb"] *= 2
    with pytest.raises(ValueError):
        verify.validate(data)


def test_complementary_counts_cannot_exceed_original_population(data):
    region = next(iter(data["lower150140"]["native_region_moments"].values()))
    region["all"]["selected"] = 40000
    region["below50"]["selected"] = region["atleast50"]["selected"] = 20000
    with pytest.raises(ValueError):
        verify.validate(data)


def test_consistent_wrong_union_cannot_replace_high_region(data):
    rows = data["lower150140"]["rows"]
    index = next(i for i, row in enumerate(rows) if row["category"] == "SR_high")
    rows[index] = copy.deepcopy(next(row for row in rows if row["category"] == "SR_low"))
    rows[index]["category"] = "SR_high"
    with pytest.raises(ValueError):
        verify.validate(data)


def test_signed_integration_error_cannot_be_coherently_relabelled(data):
    data["fresh10098"]["inclusive"]["integration_error_pb"] *= -1
    for row in data["fresh10098"]["limits"]:
        row["inclusive_generator_integration_only_error_pb"] *= -1
    with pytest.raises(ValueError):
        verify.validate(data)


def test_source_map_cannot_omit_copied_figures(tmp_path):
    target = tmp_path/"bundle"
    shutil.copytree(BUNDLE, target)
    sources = verify.read(target/"source-map.json")
    sources["copied_files"] = {}
    (target/"source-map.json").write_text(json.dumps(sources))
    manifest = verify.read(target/"manifest.json")
    manifest["files"]["source-map.json"] = verify.sha(target/"source-map.json")
    (target/"manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="three copied"):
        verify.verify(target)


def test_invented_sparse_interval_rejects(data):
    row = next(row for row in data["lower150140"]["rows"] if
               row["upper_slice_over_nominal"]["conditional_95pct_interval"] is None)
    row["upper_slice_over_nominal"]["conditional_95pct_interval"] = [.9, 1.1]
    with pytest.raises(ValueError):
        verify.validate(data)


def test_csv_covariance_is_recomputed(data, tmp_path):
    source = (BUNDLE/"tables/hard-slice-rates.csv").read_text()
    rows = source.splitlines()
    values = rows[1].split(",")
    values[-1] = "0"
    rows[1] = ",".join(values)
    path = tmp_path/"bad.csv"
    path.write_text("\n".join(rows)+"\n")
    with pytest.raises(ValueError):
        verify.validate_partition_csv(path, data)


def test_standalone_relocated_without_ravel(tmp_path):
    target = tmp_path/"evidence"
    shutil.copytree(BUNDLE, target)
    before = sorted(str(p.relative_to(target)) for p in target.rglob("*") if p.is_file())
    result = subprocess.run([sys.executable, "-I", "-S", "-B", str(target/"verify.py")],
                            cwd=tmp_path, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["status"] == "PASS"
    assert before == sorted(str(p.relative_to(target)) for p in target.rglob("*") if p.is_file())


def test_explicit_source_check_never_skips_missing_originals(tmp_path):
    with pytest.raises((ValueError, FileNotFoundError)):
        verify.verify(source_root=tmp_path)


def test_unmanifested_bundle_file_rejects(tmp_path):
    target = tmp_path/"evidence"
    shutil.copytree(BUNDLE, target)
    (target/"unexpected.txt").write_text("extra")
    with pytest.raises(ValueError, match="inventory"):
        verify.verify(target)


def test_duplicate_json_key_rejects(tmp_path):
    path = tmp_path/"duplicate.json"
    path.write_text('{"status": 1, "status": 2}')
    with pytest.raises(ValueError, match="Duplicate"):
        verify.read(path)
