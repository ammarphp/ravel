"""Standalone arithmetic and selected-source projection check; no event replay."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import struct

BUNDLE = Path(__file__).resolve().parent
QUANTILES = ["observed", "expected_minus2", "expected_minus1", "expected_median", "expected_plus1", "expected_plus2"]
NORMAL_FIELDS = ["inclusive", "native", "limits", "bins", "unions", "numerical", "reference"]
PARTITION_FIELDS = ["original_generated_events", "sigma_pb", "K", "hard_population",
                    "native_region_moments", "rows", "join_evidence"]
ESTIMATE_FIELDS = ["streams", "original_generated_events", "selected_events", "selected_rate_pb",
    "fixed_N_conditional_rate_variance_pb2", "integration_rate_variance_pb2",
    "retained_histogram_selected_rate_pb", "histogram_sumw2_pb2", "histogram_relative_mc_error",
    "histogram_5pct_floor_passed", "precision_status"]
SOURCE_BASE = "local-runs/rrr-closure/physics-review/"
PROJECTION_PATHS = [SOURCE_BASE+name for name in [
    "fresh10098-normalization-v1/result-v1/comparison.json",
    "lower-parton-hard-slice-v4/result-v1/partition.json",
    "lhe-hepmc-replay-v2/run-v1/COMPLETE.json",
    "lhe-hepmc-replay-v2/run-v1/output/byte-proof.json",
    "lhe-hepmc-replay-v2/run-v1/output/content-join.json"]]
COPY_PATHS = {name: SOURCE_BASE+"lower-parton-hard-slice-actual-independent/"+source for name, source in [
    ("figures/hard-slice-comparison.png", "hard-slice-comparison.png"),
    ("figures/hard-slice-comparison.pdf", "hard-slice-comparison.pdf"),
    ("tables/hard-slice-rates.csv", "source-data.csv")]}


def channel_map():
    result = {}
    for region in ("VV", "tau", "top"):
        for level, suffix in (("high", "hghmet"), ("low", "lowmet")):
            result[f"CR{region}_MT2_{suffix}_cuts"] = {"region": f"CR_S_{region}_{level}"}
    for flavour in ("ee", "mm"):
        for letter in "abcdefgh":
            for level, suffix in (("high", "hghmet"), ("low", "lowmet_V2")):
                result[f"SR{flavour}_eMT2{letter}_{suffix}_cuts"] = {
                    "region": f"SR_S_{level}_eMT2{letter}", "flavour": "is"+flavour}
    return result


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    result = json.loads(Path(path).read_text(), object_pairs_hook=unique,
                        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    json.dumps(result, allow_nan=False)
    return result


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def number(value):
    require(type(value) in (int, float) and math.isfinite(value), "Finite numeric value required")
    return value


def count(value, minimum=0):
    require(type(value) is int and value >= minimum, "Exact nonnegative integer required")
    return value


def close(actual, expected, *, rtol=2e-10, atol=1e-24):
    require(math.isclose(number(actual), number(expected), rel_tol=rtol, abs_tol=atol),
            f"Arithmetic differs: {actual} != {expected}")


def project(originals):
    """Explicit field selection; private paths, process identities and approvals do not ship."""
    normal, partition, replay, byte_proof, joined = originals
    require(normal["status"] == "completed_stored_scalar_comparison", "Normalization incomplete")
    require(partition["status"] == "complete_retained_hard_partition", "Partition incomplete")
    require(replay["status"] == "complete_original_lha_provenance", "Outer replay incomplete")
    require(byte_proof["status"] == "passed" and joined["status"] == "content_join_passed", "Replay proof incomplete")
    result = {
        "schema_version": 1,
        "scope": {"physics_certified": False, "coverage_validated": False,
                  "new_contour": False, "partition_predeclared_equivalence_test": False,
                  "public_raw_event_replay": False},
        "fresh10098": {key: normal[key] for key in NORMAL_FIELDS},
        "lower150140": {key: partition[key] for key in PARTITION_FIELDS},
        "replay": {
            "status": replay["status"], "receipt_sha256": replay["execution"]["receipt_sha256"],
            "original_events": joined["original_events"], "joined_events": joined["joined_events"],
            "new_hard_events": 0, "first_difference": byte_proof["first_difference"],
            "read_error": byte_proof["read_error"],
            "streams": [{key: stream[key] for key in
                         ("role", "sha256", "bytes", "complete_eof", "complete_framing", "events")}
                        for stream in byte_proof["streams"]],
            "original_event_sequence_verified": all(stream["event_numbers"] == list(range(20000))
                                                     for stream in byte_proof["streams"]),
        },
    }
    # Retain only estimator fields whose meanings and arithmetic are checked here.
    result = json.loads(json.dumps(result, allow_nan=False))
    for row in result["lower150140"]["rows"]:
        row["nominal_60k"] = {key: row["nominal_60k"][key] for key in ESTIMATE_FIELDS}
        row["original_exposure_estimates"] = {label: {key: value[key] for key in ESTIMATE_FIELDS}
                                               for label, value in row["original_exposure_estimates"].items()}
    return result


def estimate(value):
    require(set(value) == set(ESTIMATE_FIELDS), "Declared estimator fields differ")
    streams = value["streams"]
    require(type(streams) is list and len(streams) in (1, 2), "One stream or two independent parents required")
    exposure = sum(count(row["N"], 1) for row in streams)
    require(value["original_generated_events"] == exposure, "Original exposure changed")
    rate = variance = integration = sumw = sumw2 = 0.0
    supported = True
    for row in streams:
        n, selected = row["N"], count(row["selected"])
        require(selected <= n, "Selected population exceeds original exposure")
        q = number(row["K"]) * number(row["sigma_pb"])
        require(q > 0 and number(row["integration_error_pb"]) >= 0, "Invalid positive LO rate")
        rate += q * selected / exposure
        variance += q*q * selected * (1-selected/n) / exposure**2
        integration += (row["K"]*row["integration_error_pb"]*selected/exposure)**2
        sumw += n/exposure * number(row["retained_sumw_pb"])
        sumw2 += (n/exposure)**2 * number(row["retained_sumw2_pb2"])
        supported &= min(selected, n-selected) >= 10
    require(value["selected_events"] == sum(row["selected"] for row in streams), "Selected sum differs")
    require(value["precision_status"] == ("supported_plugin_Gaussian_diagnostic" if supported else
            "precision_unresolved_sparse_or_boundary"), "Estimator precision label differs")
    close(value["selected_rate_pb"], rate)
    close(value["fixed_N_conditional_rate_variance_pb2"], variance)
    close(value["integration_rate_variance_pb2"], integration)
    close(value["retained_histogram_selected_rate_pb"], sumw)
    close(value["histogram_sumw2_pb2"], sumw2)
    if sumw:
        error = math.sqrt(sumw2)/sumw
        close(value["histogram_relative_mc_error"], error)
        require(value["histogram_5pct_floor_passed"] is (error <= .05), "False histogram precision")
    else:
        require(value["histogram_relative_mc_error"] is None and
                value["histogram_5pct_floor_passed"] is False, "Zero selection is unresolved")
    return rate, variance, integration, supported


def partition_moments(parts):
    require(set(parts) == {"all", "below50", "atleast50"}, "Complementary partitions required")
    for label, part in parts.items():
        n = count(part["selected"])
        require(n <= {"all": 20000, "below50": 10954, "atleast50": 9046}[label], "Partition count exceeds population")
        weight, squared = number(part["sumw_pb"]), number(part["sumw2_pb2"])
        require(weight >= 0 and squared >= 0, "Positive-weight evidence required")
        if n:
            require(weight > 0 and squared > 0, "Selected population has no moments")
            error = math.sqrt(squared)/weight
            close(part["histogram_relative_mc_error"], error)
            require(part["histogram_5pct_floor_passed"] is (error <= .05), "False partition precision")
            require(part["precision_status"] == "stored-positive-weight-moments", "Partition precision label differs")
        else:
            require(weight == squared == 0 and part["histogram_relative_mc_error"] is None and
                    part["histogram_5pct_floor_passed"] is False, "Empty partition is unresolved")
            require(part["precision_status"] == "zero-selected/precision-unresolved", "Empty partition precision label differs")
    for key in ("selected", "sumw_pb", "sumw2_pb2"):
        close(parts["all"][key], parts["below50"][key]+parts["atleast50"][key])


def validate(data):
    require(type(data["schema_version"]) is int and data["schema_version"] == 1, "Schema changed")
    require(data["scope"] == {"physics_certified": False, "coverage_validated": False,
            "new_contour": False, "partition_predeclared_equivalence_test": False,
            "public_raw_event_replay": False}, "Scientific scope changed")
    normal = data["fresh10098"]
    ref = normal["reference"]
    require((ref["parent_GeV"], ref["lsp_GeV"], ref["zero_based_source_row"],
             ref["official_patchset_index"]) == (100., 98., 5, 11), "Released point identity differs")
    require(ref["public_uncertainty"] is None and ref["expected_bands"] is None, "Invented reference uncertainty")
    close(ref["observed_fb"], 238.13); close(ref["median_expected_fb"], 203.96)
    inc, native = normal["inclusive"], normal["native"]
    require(count(inc["original_events"]) == 1000, "Inclusive exposure changed")
    require(number(inc["integration_error_pb"]) >= 0, "Negative integration uncertainty")
    close(inc["sigma_lo_pb"], .574784); close(native["K"], 1.18)
    close(native["one_parton_sigma_after_K_pb"], native["one_parton_sigma_lo_pb"]*native["K"])
    require([row["quantile"] for row in normal["limits"]] == QUANTILES, "All six quantiles required")
    for row in normal["limits"]:
        mu = number(row["mu95"])
        require(mu > 0, "Resolved positive root required")
        pb = mu * inc["sigma_lo_pb"] * native["K"]
        close(row["inclusive_sigma95_pb"], pb); close(row["inclusive_sigma95_fb"], 1000*pb)
        close(row["generated_one_parton_sigma95_pb"], mu*native["one_parton_sigma_after_K_pb"])
        close(row["inclusive_generator_integration_only_error_pb"], mu*native["K"]*inc["integration_error_pb"])
        reference = ref["observed_fb"] if row["quantile"] == "observed" else ref["median_expected_fb"] if row["quantile"] == "expected_median" else None
        if reference is None:
            require(all(row[key] is None for key in ("ratio_to_reference", "residual_percent", "reference_sigma95_pb")), "Invented band comparison")
        else:
            close(row["reference_sigma95_pb"], reference/1000)
            close(row["ratio_to_reference"], 1000*pb/reference)
            close(row["residual_percent"], 100*(1000*pb/reference-1))
        require(row["public_uncertainty"] is None, "Invented limit comparison uncertainty")
    bins = normal["bins"]
    require(len(bins) == 38 and len({row["channel"] for row in bins}) == 38, "All unique channels required")
    require({row["channel"]: row["mapping"] for row in bins} == channel_map(), "Exact38 channel map differs")
    require(sum(row["selected_events"] == 0 for row in bins) == 22, "Zero-selected population differs")
    for row in bins:
        selected = count(row["selected_events"])
        require(selected <= 20000, "Fresh selection exceeds original exposure")
        weight, squared = number(row["sumw_pb"]), number(row["sumw2_pb2"])
        require(weight >= 0 and squared >= 0, "Unsupported signed moments in this positive-only evidence")
        close(row["nominal_yield"], 139000*weight)
        quantum = struct.unpack("f", struct.pack("f", native["one_parton_sigma_after_K_pb"]/20000))[0]
        close(weight, selected*quantum)
        close(squared, selected*quantum*quantum)
        if weight:
            error = math.sqrt(squared)/weight
            close(row["histogram_relative_mc"], error)
            require(row["diagnostic_5percent"] == ("meets_target" if error <= .05 else "exceeds_target"), "False fresh precision")
            require(bool(row["likelihood_mc_constraint"]), "Nonzero native MC constraint missing")
        else:
            require(row["selected_events"] == squared == 0 and row["histogram_relative_mc"] is None and
                    row["likelihood_mc_constraint"] is None, "Zero-selected precision/constraint invented")
            require(row["diagnostic_5percent"] == "unresolved", "False zero-bin precision status")
    constraints = [row["likelihood_mc_constraint"] for row in bins if row["selected_events"]]
    require(len(constraints) == len(set(constraints)) == 16, "Independent native MC constraints differ")
    require([row["category"] for row in normal["unions"]] == ["SR_high", "SR_low"], "Both primary unions required")
    for union in normal["unions"]:
        require(union["original_denominator"] == 20000, "Fresh original exposure differs")
        high = union["category"] == "SR_high"
        members = [row for row in bins if row["channel"].startswith("SR") and ("hghmet" in row["channel"]) is high]
        require(union["selected_events"] == sum(row["selected_events"] for row in members), "Union population differs")
        for key in ("sumw_pb", "sumw2_pb2"):
            close(union[key], sum(row[key] for row in members))
        close(union["histogram_relative_mc"], math.sqrt(union["sumw2_pb2"])/union["sumw_pb"])
        require(union["diagnostic_target"] == .05, "Diagnostic threshold differs")
    require(normal["numerical"]["fresh_check_evaluations"] == 16 and
            0 <= number(normal["numerical"]["root_cls_max_error"]) <= 1e-4, "Stored numerical check failed")
    lower = data["lower150140"]
    require(lower["original_generated_events"] == 20000 and
            lower["hard_population"] == {"below50": 10954, "atleast50": 9046}, "Full partition exposure changed")
    require(len(lower["native_region_moments"]) == 147, "All native regions required")
    for parts in lower["native_region_moments"].values():
        partition_moments(parts)
    join = lower["join_evidence"]
    require(join["LHE_HepMC_unique_content"] == join["HepMC_Delphes_exact_Event"] ==
            join["Delphes_native_trace_exact_Event"] == 20000, "Incomplete cross-stage identity population")
    require(sum(count(n) for n in join["production_modes"].values()) == 20000 and
            join["validated_slepton_decays"] == 40000, "Production/decay population differs")
    rows = lower["rows"]
    require(len(rows) == 40 and {row["category"] for row in rows} ==
            {row["channel"] for row in bins} | {"SR_high", "SR_low"}, "All40 categories required")
    by_name = {row["category"]: row for row in rows}
    mapping = channel_map()
    for region in {entry["region"] for entry in mapping.values()}:
        members = [by_name[name]["partition"] for name, entry in mapping.items() if entry["region"] == region]
        for part in ("all", "below50", "atleast50"):
            for key in ("selected", "sumw_pb", "sumw2_pb2"):
                close(lower["native_region_moments"][region][part][key], sum(member[part][key] for member in members))
    for level in ("high", "low"):
        members = [by_name[name]["partition"] for name, entry in mapping.items()
                   if entry["region"].startswith("SR_S_"+level+"_")]
        require(len(members) == 16, "Each primary union must contain16 model bins")
        for part in ("all", "below50", "atleast50"):
            for key in ("selected", "sumw_pb", "sumw2_pb2"):
                close(by_name["SR_"+level]["partition"][part][key], sum(member[part][key] for member in members))
    for row in rows:
        parts = row["partition"]
        partition_moments(parts)
        for key in ("all", "below50", "atleast50"):
            value = row["original_exposure_estimates"][key]
            require(value["original_generated_events"] == 20000 and len(value["streams"]) == 1,
                    "A selected subset cannot replace original exposure")
            require(value["selected_events"] == parts[key]["selected"], "Partition selected count differs")
            stream = value["streams"][0]
            close(stream["sigma_pb"], lower["sigma_pb"]); close(stream["K"], lower["K"])
            close(stream["retained_sumw_pb"], parts[key]["sumw_pb"])
            close(stream["retained_sumw2_pb2"], parts[key]["sumw2_pb2"])
            estimate(value)
        values = row["original_exposure_estimates"]
        covariance = -(lower["sigma_pb"]*lower["K"])**2*parts["below50"]["selected"]*parts["atleast50"]["selected"]/20000**3
        close(values["all"]["fixed_N_conditional_rate_variance_pb2"],
              values["below50"]["fixed_N_conditional_rate_variance_pb2"] +
              values["atleast50"]["fixed_N_conditional_rate_variance_pb2"] + 2*covariance)
        numerator = estimate(row["original_exposure_estimates"]["atleast50"])
        denominator = estimate(row["nominal_60k"])
        require([s["N"] for s in row["nominal_60k"]["streams"]] == [20000, 40000], "Original nominal parents differ")
        ratio = row["upper_slice_over_nominal"]
        if not denominator[0]:
            require(ratio["ratio"] is None, "Zero denominator has no ratio")
        else:
            value = numerator[0]/denominator[0]
            close(ratio["ratio"], value)
        supported = numerator[3] and denominator[3] and bool(denominator[0])
        if supported:
            conditional = math.sqrt(numerator[1]/denominator[0]**2 + numerator[0]**2*denominator[1]/denominator[0]**4)
            integration = math.sqrt(numerator[2]/denominator[0]**2 + numerator[0]**2*denominator[2]/denominator[0]**4)
            close(ratio["conditional_standard_error"], conditional)
            close(ratio["integration_standard_error"], integration)
        else:
            require(ratio.get("conditional_standard_error") is None and ratio.get("integration_standard_error") is None,
                    "Unresolved standard error invented")
        for key, include_integration in (("conditional_95pct_interval", False),
                                         ("conditional_plus_integration_95pct_interval", True)):
            if not supported:
                require(ratio[key] is None, "Sparse interval invented")
                continue
            vn = numerator[1] + (numerator[2] if include_integration else 0)
            vd = denominator[1] + (denominator[2] if include_integration else 0)
            error = math.sqrt(vn/denominator[0]**2 + numerator[0]**2*vd/denominator[0]**4)
            close(ratio[key][0], value-1.959963984540054*error)
            close(ratio[key][1], value+1.959963984540054*error)
        require(ratio["decision"] == "not_tested_post_comparison_descriptive_partition", "Post-comparison partition is descriptive")
    replay = data["replay"]
    require(replay["original_events"] == replay["joined_events"] == 20000 and
            replay["new_hard_events"] == 0 and replay["first_difference"] is None and
            replay["read_error"] is None and replay["original_event_sequence_verified"] is True, "Replay scope/population differs")
    require([s["role"] for s in replay["streams"]] == ["original", "replayed"], "Both replay streams required")
    require(len({s["sha256"] for s in replay["streams"]}) == 1, "Replay content differs")
    for stream in replay["streams"]:
        require(stream["bytes"] == 4510402635 and stream["events"] == 20000 and
                stream["complete_eof"] is True and stream["complete_framing"] is True, "Complete replay population differs")


def limits_csv(data):
    output = io.StringIO(newline="")
    fields = ["quantile", "mu95", "inclusive_sigma95_fb", "reference_sigma95_pb", "residual_percent"]
    writer = csv.DictWriter(output, fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows({key: row[key] for key in fields} for row in data["fresh10098"]["limits"])
    return output.getvalue()


def validate_partition_csv(path, data):
    with Path(path).open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    source = data["lower150140"]
    require([row["category"] for row in rows] == [row["category"] for row in source["rows"]], "All40 CSV rows/order required")
    for row, original in zip(rows, source["rows"]):
        parts, estimates = original["partition"], original["original_exposure_estimates"]
        ratio = original["upper_slice_over_nominal"]
        interval = ratio["conditional_plus_integration_95pct_interval"]
        expected = {"original_N": 20000, "below_count": parts["below50"]["selected"],
                    "upper_count": parts["atleast50"]["selected"], "all_count": parts["all"]["selected"],
                    "below_rate_fb": estimates["below50"]["selected_rate_pb"]*1000,
                    "upper_rate_fb": estimates["atleast50"]["selected_rate_pb"]*1000,
                    "all_rate_fb": estimates["all"]["selected_rate_pb"]*1000,
                    "nominal_rate_fb": original["nominal_60k"]["selected_rate_pb"]*1000,
                    "upper_over_nominal": ratio["ratio"], "ratio_low": interval[0] if interval else None,
                    "ratio_high": interval[1] if interval else None,
                    "upper_hist_relative_error": parts["atleast50"]["histogram_relative_mc_error"],
                    "below_upper_fixed_N_covariance_pb2": -(source["sigma_pb"]*source["K"])**2*
                        parts["below50"]["selected"]*parts["atleast50"]["selected"]/20000**3}
        for key, value in expected.items():
            if value is None:
                require(row[key] == "", "Missing CSV value invented")
            else:
                close(float(row[key]), value)
        require(row["upper_5pct_floor"] == str(parts["atleast50"]["histogram_5pct_floor_passed"]), "CSV precision differs")
        require(row["ratio_precision"] == ("supported_conditional_Gaussian" if interval else "sparse_or_zero_unresolved"), "CSV interval scope differs")


def verify(bundle=BUNDLE, source_root=None):
    bundle = Path(bundle)
    manifest = read(bundle/"manifest.json")
    actual = {str(p.relative_to(bundle)) for p in bundle.rglob("*") if p.is_file()}
    require(actual == set(manifest["files"]) | {"manifest.json"}, "Bundle inventory differs")
    for name, digest in manifest["files"].items():
        path = bundle/name
        require(not path.is_symlink() and path.resolve(strict=True).is_relative_to(bundle.resolve()) and
                sha(path) == digest, "Bundled file changed: "+name)
    data = read(bundle/"data/evidence.json")
    validate(data)
    validate_partition_csv(bundle/"tables/hard-slice-rates.csv", data)
    require((bundle/"tables/fresh10098-limits.csv").read_text() == limits_csv(data), "Limit CSV differs")
    sources = read(bundle/"source-map.json")
    require(type(sources["schema_version"]) is int and sources["schema_version"] == 1, "Source schema differs")
    require([item["path"] for item in sources["projection_inputs"]] == PROJECTION_PATHS, "Exactly five ordered projection roles required")
    require(set(sources["copied_files"]) == set(COPY_PATHS), "Exactly three copied roles required")
    for item in [*sources["projection_inputs"], *sources["copied_files"].values()]:
        require(set(item) == {"path", "sha256"} and type(item["path"]) is str and
                not Path(item["path"]).is_absolute() and ".." not in Path(item["path"]).parts and
                type(item["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]), "Unsafe source pin")
    for name, item in sources["copied_files"].items():
        require(item["path"] == COPY_PATHS[name] and item["sha256"] == sha(bundle/name), "Copied artifact source commitment differs")
    if source_root is not None:
        root = Path(source_root).resolve(strict=True)
        originals = []
        for item in sources["projection_inputs"]:
            path = root/item["path"]
            require(path.resolve(strict=True).is_relative_to(root) and sha(path) == item["sha256"], "Original source differs")
            originals.append(read(path))
        require(project(originals) == data, "Public projection differs from selected originals")
        for name, item in sources["copied_files"].items():
            path = root/item["path"]
            require(path.resolve(strict=True).is_relative_to(root) and sha(path) == item["sha256"] == sha(bundle/name), "Copied source differs")
    return {"status": "PASS", "limit_roots": 6, "fresh_channels": 38,
            "partition_categories": 40, "raw_event_payloads_read": 0,
            "selected_source_projection_checked": source_root is not None,
            "scope": "Arithmetic and selected evidence projection only; no raw-event replay or physics certification"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(source_root=args.source_root), indent=2))
