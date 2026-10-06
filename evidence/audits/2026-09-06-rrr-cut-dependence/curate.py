#!/usr/bin/env python3
"""Reproduce this bundle's projections from its selected, pinned originals.

Default is read-only comparison. --write explicitly creates/refreshes only this
bundle's derived files. No workflow, event reader, optimizer or network is used.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import verify as v

HERE = Path(__file__).resolve().parent


class Sources:
    def __init__(self, root, bundle):
        self.root = Path(root)
        self.mapping = v.read_json(Path(bundle)/"source-map.json")
        self.entries = v.validate_sources(self.mapping)
        self.contents = {}
        for key, pin in self.entries.items():
            content = v.path_under(self.root, pin["path"]).read_bytes()
            v.require(v.digest(content) == pin["sha256"] and len(content) == pin["bytes"],
                      "Selected original source changed: " + key)
            self.contents[key] = content

    def get(self, key):
        return json.loads(self.contents[key], object_pairs_hook=v._pairs)

    def sha(self, key):
        return self.entries[key]["sha256"]


def canonical_sha(value):
    return v.digest(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def original_path_matches(original, repository_relative):
    """Compare an original host path by its pinned repository-relative suffix.

    Source bytes are already SHA-checked. This permits relocating the selected
    original archive without rewriting its historical absolute pointers.
    """
    parts = Path(repository_relative).parts
    return Path(original).is_absolute() and Path(original).parts[-len(parts):] == parts


def receipt(source, key):
    record = source.get(key)
    v.require(record["status"] == "succeeded" and record["exit_code"] == 0
              and record["error"] is None, "Original stage is not successful")
    return {"record_source": key, "status": record["status"], "exit_code": record["exit_code"],
            "stage": record["stage"], "receipt_sha256": record["receipt_sha256"],
            "fingerprint": record["fingerprint"], "parents": record["parents"],
            "started_utc": record["started_utc"], "finished_utc": record["finished_utc"],
            "producer_supervisor_runtime": record["runtime"],
            "input_snapshot_sha256": canonical_sha(record["input_snapshot"]),
            "output_snapshot_sha256": canonical_sha(record["output_snapshot"])}


def fit_projection(result, key, *, wrapper=None):
    values = [result["obs_limit"], *result["exp_limits"]]
    canonical = [result["limits"]["observed"], *result["limits"]["expected"]]
    v.require(len(canonical) == 6 and len(values) == 6, "Source six-root population differs")
    roots = []
    for i, (q, mu, limit) in enumerate(zip(v.QUANTILES, values, canonical)):
        v.close(limit["value"], mu)
        v.require(limit["status"] == "resolved", "Source root censored")
        j = result["scan_mu"].index(mu)
        cls = result["scan_cls_obs"][j] if i == 0 else result["scan_cls_exp"][j][i-1]
        roots.append({"quantile": q, "mu": mu, "status": limit["status"],
                      "bracket": limit["bracket"], "scan_cls": cls,
                      "absolute_cls_residual": abs(cls-.05)})
    evaluations = None
    earlier = None
    scope = "Native result stores root scan and reported count; full final evaluation vectors are not retained here"
    if wrapper is not None:
        all_evaluations = wrapper["diagnostics"]["evaluations"]
        count = result["inference"]["fresh_check_evaluations"]
        evaluations = [{k: row[k] for k in ("mu","cls","status","profile_consistency")}
                       for row in all_evaluations[-count:]]
        earlier = sum(row.get("profile_consistency", {}).get("passed") is False
                      for row in all_evaluations[:-count])
        scope = "All final recorded official root/bound evaluations, not saved conditional parameter vectors or an independent refit"
    optimizer_counts = {k: value for k, value in result["optimizer"].items()
                        if type(value) is int and k != "escalated"}
    return {"result_source": key, "mu": dict(zip(v.QUANTILES, values)),
            "limit_status": result["limit_status"], "roots": roots,
            "flags": {k: result[k] for k in ("at_poi_cap","median_at_cap","at_mu_floor","band_degenerate","cls_monotonic")},
            "inference": result["inference"],
            "engine_sha256": wrapper["engine_sha256"] if wrapper is not None else result["execution_provenance"]["engine_sha256"],
            "n_parameters": len(result["fit_diagnostics"]["parameters"]),
            "profile_consistency": result["fit_diagnostics"]["profile_consistency"],
            "final_evaluations": evaluations, "evaluation_record_scope": scope,
            "earlier_profile_consistency_rejections_retained": earlier,
            "optimizer_diagnostic_counts": optimizer_counts}


def build(root, bundle=HERE):
    source = Sources(root, bundle)
    table = source.get("native_table")
    lower = source.get("lower_comparison")
    official = source.get("official_table")
    official_protocol = source.get("official_protocol")
    pool = source.get("pool_metadata")
    replicas = source.get("pool_replica_manifest")
    inclusive = source.get("inclusive_control")
    refs = source.get("reference_52")
    matched = [p for p in refs["points"] if p["point_id"] == "m150_m140"]
    v.require(len(matched) == 1 and matched[0] == table["reference"], "Reference row binding differs")
    v.close(inclusive["rate"]["cross_section_pb"], table["inclusive_LO_pb"])
    v.close(inclusive["rate"]["integration_uncertainty_pb"], table["inclusive_integration_error_pb"])
    v.require(inclusive["rate"]["kfactor_applied"] is False
              and inclusive["rate"]["luminosity_applied"] is False, "Inclusive rate already corrected")
    v.require(pool["luminosity_applied"] is False and pool["original_generated_events"] == 60000
              and pool["acceptance_certified"] is False, "Pool normalization/scope differs")
    v.close(pool["physics"]["kfactor"], table["K"])
    parents = ["nominal_20k", "nominal_40k"]
    v.require(len(pool["replicas"]) == 2
              and pool["input_manifest"]["sha256"] == source.sha("pool_replica_manifest")
              and original_path_matches(pool["input_manifest"]["path"],
                                        source.entries["pool_replica_manifest"]["path"])
              and replicas["schema_version"] == 1
              and replicas["input_combination"] == "pool-independent-replicas"
              and [r["plan"] for r in replicas["replicas"]] == [r["plan"] for r in pool["replicas"]],
              "Pool manifest differs")
    for parent, row, n in zip(parents, pool["replicas"], (20000,40000)):
        v.require(row["plan"]["sha256"] == source.sha(parent+"_plan")
                  and row["original_generated_events"] == n, "Pool parent identity differs")
        v.require(original_path_matches(row["plan"]["path"],source.entries[parent+"_plan"]["path"]),
                  "Pool parent order/path differs")
    native = []
    lineage = []
    original_names = ("nominal_20k", "nominal_40k", "nominal_pool_60k", "leading_parton_20GeV_20k")
    for name, original_name, row in zip(v.NATIVE_IDS, original_names, table["samples"]):
        v.require(row["sample"] == original_name, "Native table ordering differs")
        result = source.get(name+"_result")
        item = fit_projection(result, name+"_result")
        v.require([row["observed_mu"], *row["expected_mu"]] == list(item["mu"].values()), "Native table/root mismatch")
        item.update(id=name, source_sample_id=original_name, original_events=row["original_events"],
                    sigma95_fb=dict(zip(v.QUANTILES, [row["observed_sigma95_fb"],*row["expected_sigma95_fb"]])),
                    observed_residual_fraction=row["observed_residual_fraction"],
                    median_expected_residual_fraction=row["median_expected_residual_fraction"])
        native.append(item)
        stages = v.POOL_STAGES if name == "pooled_60k" else v.NATIVE_STAGES
        state = source.get(name+"_state")
        v.require(set(state["stages"]) == set(stages), "Original stage inventory incomplete")
        projected = {}
        for stage in stages:
            key = name+"_receipt_"+stage
            v.require(state["stages"][stage] == source.get(key), "State/immutable receipt differs")
            projected[stage] = receipt(source, key)
        lineage.append({"id":name,"plan_sha256":source.sha(name+"_plan"),
                        "stages":projected,"producer_runtime": "v5" if name in ("pooled_60k","lower_20k") else "v4"})
    arms = []
    for name, reported in zip(v.OFFICIAL_IDS, official["arms"]):
        wrapper = source.get("official_"+name+"_result")
        v.require(wrapper["status"] == "succeeded" and wrapper["arm"] == name
                  and wrapper["manifest_sha256"] == source.sha("official_protocol"), "Official result identity differs")
        item = fit_projection(wrapper["result"], "official_"+name+"_result", wrapper=wrapper)
        v.require(reported["mu"] == item["mu"] and reported["n_parameters"] == item["n_parameters"], "Official report/root mismatch")
        item.update(id=name, label=reported["label"], wall_seconds=wrapper["wall_seconds"],
                    receipt=receipt(source,"official_"+name+"_receipt"))
        arms.append(item)
    generations = []
    for name, norm in zip(("nominal_20k","nominal_40k","lower_20k"), lower["normalizations"]):
        original = source.get(name+"_normalization")
        v.require(set(norm) == set(original) | {"integration"}
                  and original == {k:value for k,value in norm.items() if k != "integration"}
                  and norm["status"] == "resolved" and norm["luminosity_applied"] is False
                  and norm["correction_applications"] == 1 and norm["basis"] == "unmerged_lo_lhe", "Normalization source differs")
        generations.append({"id":name,"sigma_pb":norm["cross_section_pb"],"K":norm["kfactor"],
                            "integration_error_pb":norm["integration"]["standard_error_pb"],
                            "integration_log_source":name+"_integration_log",
                            "N":norm["generation"]["n_events"]})
        v.require(norm["integration"]["source"]["sha256"] == source.sha(name+"_integration_log"),
                  "Generator integration-log pin differs")
        v.close(float(norm["integration"]["standard_error_pb_printed"]), norm["integration"]["standard_error_pb"])
    finalization = source.get("failed_pool_finalization")
    v.require(finalization["status"] == "failed" and finalization["exit_code"] == 124
              and finalization["numerical_result_exists"] is False, "Original pooled failure differs")
    failure_rows = [{"id":"pooled_first_attempt","status":"failed","accepted_result":False,
                     "source":"failed_pool_finalization","exit_code":124,"wall_cap_seconds":3600,
                     "elapsed_seconds":None,"reason":"wall-clock timeout followed by a supervision cleanup exception",
                     "cleanup_interpretation":finalization["observation"]["interpretation"],
                     "final_attempt_sha256":finalization["final_attempt_sha256"],
                     "replaced_by":"pooled_60k"}]
    for name in ("v1","v2"):
        failed = source.get("failed_reader_"+name)
        v.require(failed["status"] == "failed_diagnostic", "Original reader failure differs")
        failure_rows.append({"id":"lower_reader_"+name,"status":"failed","accepted_result":False,
                             "source":"failed_reader_"+name,"source_status":failed["status"],"error":failed["error"],
                             "replaced_by":"completed_lower_reader_v3"})
    model_channels = sorted(row["channel"] for row in source.get("nominal_20k_signal_model")["channels"])
    selected_lower = {k:lower[k] for k in ("policy","recipe","rows","primary_endpoints","six_individual_CR_channels","physics_certified","new_generated_events","scope_notes")}
    data = {"schema_version":1,
        "catalog":{"point_id":"m150_m140","m_parent_GeV":150,"m_lsp_GeV":140,"delta_m_GeV":10,
                   "unique_mass_points":1,"independent_selected_event_streams":3,"original_selected_stream_exposure":80000,
                   "native_fits":4,"official_fits":3,"pool_additional_events":0,"physics_certified":False,
                   "coverage_validated":False,"global_contour_closed":False,"native_official_mu_directly_comparable":False},
        "reference":table["reference"], "model_channels":model_channels,
        "normalization":{"inclusive_LO_pb":table["inclusive_LO_pb"],"inclusive_integration_error_pb":table["inclusive_integration_error_pb"],
                         "K":table["K"],"nominal_inclusive_fb":table["nominal_inclusive_fb"],"luminosity_applied":False,
                         "generation":generations,"inclusive_scope":inclusive["scope"],
                         "inclusive_process":inclusive["process"],"inclusive_original_events":inclusive["events"],
                         "uncertainty_scope":table["uncertainty_scope"]},
        "native":native,"official":{"arms":arms,"rows":official["rows"],"model_channels":38,
             "compiled":official_protocol["compiled"],"modifier_settings":official_protocol["modifier_settings"],
             "model_input_sources":{name:"official_input_"+name for name in ("background",*v.OFFICIAL_IDS)},
             "supplied_signal_samples":27,"supplied_signal_CR_channels":official["supplied_signal_CR_channels"],
             "native_uncertainty_transfer":False,"sigma_conversion":False,"limitations":official["limitations"]},
        "lower":selected_lower,"figure_data":source.get("figure_data"),
        "lineage":{"runs":lineage,"pool":{"parents":parents,"parent_exposures":[r["original_generated_events"] for r in pool["replicas"]],
                   "parent_plan_sha256":[r["plan"]["sha256"] for r in pool["replicas"]],"alpha":[1/3,2/3],
                   "new_events":0,"independent_of_parents":False,"K":pool["physics"]["kfactor"],"luminosity_applied":pool["luminosity_applied"]}},
        "producer":{"numerical_engine_sha256":v.ENGINE,
                    "runtime_manifest_sha256":{x:source.sha("runtime_"+x) for x in ("v4","v5")},
                    "fit_dependencies":official["producer"]["dependencies_recorded_at_preparation"],
                    "current_public_source_is_not_retroactive_execution":True},
        "failures":failure_rows,
        "failure_inventory_scope":"Three selected failed attempts and retained fit diagnostic counts; not an exhaustive campaign or runtime-warning inventory",
        "provenance_scope":"Deterministic selected-field projections. Original source/receipt hashes commit to private originals; offline checks cannot authenticate unshipped event payloads or reconstruct full private receipts."}
    # Every public value comes from an explicit projection; arbitrary absolute-path
    # replacement is deliberately absent, so unexpected private text fails later.
    v.validate_data(data, source.mapping)
    generated = {"data/evidence.json":v.encode(data), "tables/native-limits.csv":v.native_csv(data),
                 "tables/official-limits.csv":v.official_csv(data),
                 "tables/lower-rates.csv":v.lower_csv(data), "README.md":readme(data).encode()}
    for kind in ("ratios","decomposition"):
        for extension in ("png","pdf"):
            generated[f"figures/lower-{kind}.{extension}"] = source.contents[f"figure_{kind}_{extension}"]
    return generated


def readme(data):
    lines = ["# RRR one-point cut dependence and likelihood controls", "",
        "These completed 150/140 GeV results show numerical agreement at one mass point alongside substantial sensitivity to the leading-parton generation cut. They do not establish acceptance calibration, statistical coverage or a reproduced contour.", "",
        "The nominal 50 GeV leading-parton cut matches the pinned RRR template. The 20 GeV control tests the robustness of that approximation. It does not demonstrate an incorrect implementation of the authors’ recipe or establish the lower cut as a calibrated replacement.", "",
        "| Native sample | Original events | Observed limit (fb) | Median expected (fb) | Observed residual | Median residual |",
        "|---|---:|---:|---:|---:|---:|"]
    for fit in data["native"]:
        lines.append(f"| {fit['id']} | {fit['original_events']:,} | {fit['sigma95_fb']['observed']:.4f} | {fit['sigma95_fb']['expected_median']:.4f} | {100*fit['observed_residual_fraction']:+.3f}% | {100*fit['median_expected_residual_fraction']:+.3f}% |")
    lines += ["", "The quoted reference is 46.633 fb observed and 56.526 fb median expected. All 24 native μ values, statuses and converted values are in [the CSV](tables/native-limits.csv) and [the evidence JSON](data/evidence.json). The three independent event streams contain 80,000 original events; the 60,000-event pool reuses the nominal parents and adds no events or independent mass point.", "",
        "Displayed native limits use μ × 1.18 × 0.1350625 pb × 1000. The four-state inclusive LO control has a reported integration error of 0.0003703 pb. K=1.18 is a declared common operand. No independent uncertainty for K is invented; the inclusive integration uncertainty is shared by the four rows. Expected bands are likelihood quantiles, not simulation-error bars. Native and official μ refer to different nominal signal templates and are not directly interchangeable.", "",
        "## Measured cut dependence", "",
        "The lower cut increases the generated one-parton rate by a factor 2.22978, while reducing the rate-weighted selected fraction. The resulting high-region selected-rate ratio is 1.41171 with conditional-plus-integration 95% interval [1.14552, 1.67790]; the low-region ratio is 1.26369 with [0.98279, 1.54458]. Neither establishes the predeclared ±10% equivalence criterion. Across all 40 categories, 13 selected-rate comparisons are not established and 27 are precision-unresolved.", "",
        "![Selected fractions and rates](figures/lower-ratios.png)", "",
        "![Rate decomposition](figures/lower-decomposition.png)", "",
        "[Ratio PDF](figures/lower-ratios.pdf) · [Decomposition PDF](figures/lower-decomposition.pdf) · [All 38 model channels and two high/low aggregates](tables/lower-rates.csv)", "",
        "The figures show the two primary SR aggregates and six individual CRs. Intervals use independent-stream fixed-N delta-method sampling variance; the broader intervals additionally assume independent generator integrations and independence from selected fractions. That covariance is not supplied. Gaussian intervals require at least ten selected and ten unselected events in every contributing stream. Sparse and zero cells keep unresolved intervals. The retained-histogram 5% precision floor is a separate Poissonized sumw2 diagnostic. No familywise or coverage claim follows from these per-category intervals.", "",
        "## Matched official-model nuisance controls", "",
        "All three arms retain the same supplied nominal signal, signal in six CRs, background content and observed data. Full retains the supplied signal modifiers; signal-MC-only retains normfactor plus staterror/shapesys; nominal-only retains normfactor. These are dimensionless same-model interventions, with 196/191/191 fitted parameters.", "",
        "| Quantile | Full μ | Signal MC only μ | Nominal only μ | MC only / full | Nominal only / full |",
        "|---|---:|---:|---:|---:|---:|"]
    for row in data["official"]["rows"]:
        lines.append(f"| {row['quantile']} | {row['full_mu']:.8f} | {row['signal_mc_only_mu']:.8f} | {row['signal_nominal_only_mu']:.8f} | {row['signal_mc_only_over_full']:.6f} | {row['signal_nominal_only_over_full']:.6f} |")
    lines += ["", "[All 18 roots and ratios](tables/official-limits.csv). Removing all supplied signal nuisance modifiers changes observed/median μ by −6.35994%/−6.51502%, and the +2 expected band by −18.36617%. Equal parameter counts do not make the two reduced models equivalent: removing a signal staterror contribution can change a shared constraint. These effects are not a global correction and are not transferred to native signal nuisances.", "",
        "## Numerical evidence and retained failures", "",
        "All seven fits report six resolved roots and 16 final fresh evaluations each. Native result files retain root/scan CLs values and a profile-consistency summary, but not the complete final evaluation records or conditional parameter vectors. The official controls also retain their 48 final root/bound evaluation records. The verifier checks the evidence actually present; this is not an independent optimizer or global-minimum proof.", "",
        "The first pooled fit reached its 3600-second cap, encountered a cleanup exception, and was finalized failed with exit 124 after later quiescence was observed. Its elapsed time is unknown and no exclusion result is accepted. Neither successful SIGKILL nor the exact earlier process state is inferred. A new complete four-stage derivative produced the accepted pool. Lower-reader v1 failed on its metadata pin schema; v2 failed on stale derivative artifact custody. Both failures remain source-bound and were replaced by the completed v3 reader. These selected failures and retained optimizer diagnostic counts are not an exhaustive campaign-warning inventory.", "",
        "## Verify or reproduce the projection", "",
        "From this directory, with Python 3.10 or later and no installed Ravel package:", "",
        "```sh", "python -B verify.py", "```", "",
        "This offline standard-library check validates the exact bundle inventory, finite arithmetic, all six quantiles, pool lineage, sparse missingness, 120 ratio/interval calculations, CSVs and copied figure hashes. It does not read raw events or fit a model.", "",
        "With the retained source workspace, an additional read-only check validates the selected original hashes and rebuilds the projections in memory:", "",
        "```sh", "python -B verify.py --source-root /path/to/source-checkout", "```", "",
        "The [source map](source-map.json) uses repository-relative original paths. It identifies selected small records, not an exhaustive raw-event custody replay. Private environment values, operator process/session identities, authorization quotes and raw LHE/HepMC/ROOT products are not shipped. Original receipt and plan hashes are commitments to originals; an offline reader cannot reconstruct or independently authenticate the complete unshipped receipts. Projected JSON is not byte-identical to the originals. The four figures are byte-identical copies; deterministic CSVs and JSON are projections. A hash manifest detects drift relative to this revision, not a coherent rewrite of the bundle and verifier together.", "",
        "The producer source/runtime commitments distinguish native v4/v5 execution from the current public source. Later fixes are not attributed retrospectively to pinned binaries. The existing [earlier waypoint](../2026-09-06-rrr-waypoint/README.md) remains unchanged.", "",
        "Primary references: [RRR, arXiv:2306.11055v2](https://arxiv.org/abs/2306.11055v2) and [ATLAS, arXiv:1911.12606](https://arxiv.org/abs/1911.12606). The exact published point and supplied-model identities are retained in the evidence and source map.", "",
        "Cut robustness, detector/acceptance calibration, missing native detector/theory systematics, merging-scale behavior and statistical coverage remain open. This bundle contains one mass point and no new contour. Passing software CI does not establish those physics claims.", ""]
    return "\n".join(lines)


def write_manifest(bundle=HERE):
    bundle = Path(bundle)
    files = {}
    for path in sorted(bundle.rglob("*")):
        v.require(not path.is_symlink(), "Symlink artifact")
        if path.is_file() and path.name != "manifest.json":
            v.require("__pycache__" not in path.parts and path.suffix != ".pyc", "Bytecode in bundle")
            content = path.read_bytes()
            files[path.relative_to(bundle).as_posix()] = {"sha256":v.digest(content),"bytes":len(content)}
    (bundle/"manifest.json").write_bytes(v.encode({"schema_version":1,
        "scope":"offline arithmetic and shipped-byte integrity","files":files}))


def check(root, bundle=HERE):
    for name, content in build(root, bundle).items():
        v.require(v.path_under(bundle,name).read_bytes() == content, "Deterministic projection differs: "+name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.write:
        generated = build(args.source_root)
        for name, content in generated.items():
            path = v.path_under(HERE,name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        write_manifest()
    else:
        check(args.source_root)
    print(json.dumps(v.verify_bundle(), indent=2))


if __name__ == "__main__":
    main()
