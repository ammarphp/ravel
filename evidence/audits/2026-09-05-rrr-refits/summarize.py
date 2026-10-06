#!/usr/bin/env python3
"""Summarize retained likelihood outputs; never run inference or simulation.

Use --write to regenerate summary.json and refit-comparison.png. Use --seal only
when intentionally recording a reviewed snapshot, then --check to verify hashes
and reproduce the numerical summary. Default behavior is --check.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
TAGS = ("m50_dm5", "m100_dm2", "m150_dm20", "m200_dm20")
VARIANTS = ("full", "no_signal_nuisances", "nominal_sr_only")
ATLAS_FILES = (
    "atlas-m150_dm20-jax-refit.json",
    "atlas-m150_dm20-no-signal-nuisances-refit.json",
    "atlas-m150_dm20-nominal-sr-only-refit.json",
)
CL_TARGET = 0.05
CL_TOLERANCE = 5e-4
FAILURE = "CLs observed or expected curve is not monotonically decreasing"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(root, relative):
    return json.loads((root / relative).read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def close(left, right):
    return math.isclose(left, right, rel_tol=1e-11, abs_tol=1e-12)


def equivalent_numbers(left, right, path=""):
    """Permit only equal int/float spellings, never changed values or bool/number substitution."""
    if type(left) in (int, float) and type(right) in (int, float):
        require(math.isfinite(left) and math.isfinite(right) and left == right,
                f"background numeric value differs at {path}")
        return ([{"path": path, "retained_type": type(left).__name__,
                  "official_type": type(right).__name__, "retained_value": left,
                  "official_value": right}] if type(left) is not type(right) else [])
    require(type(left) is type(right), f"background type differs at {path}")
    if isinstance(left, dict):
        require(left.keys() == right.keys(), f"background keys differ at {path}")
        return [item for key in sorted(left) for item in
                equivalent_numbers(left[key], right[key], path + "/" + key)]
    if isinstance(left, list):
        require(len(left) == len(right), f"background list length differs at {path}")
        return [item for index, (a, b) in enumerate(zip(left, right))
                for item in equivalent_numbers(a, b, path + f"/{index}")]
    require(left == right, f"background value differs at {path}")
    return []


def source(root, relative):
    return {"path": relative, "sha256": digest(root / relative)}


def checked_result(root, relative, patch):
    """Check embedded input identities and each root against retained evaluations."""
    document = read(root, relative)
    hashes = {"background": digest(root / "inputs/background.json"),
              "patch": digest(root / "inputs" / patch)}
    if "inputs" in document:
        for key, name in (("background", "background.json"), ("patch", patch)):
            require(document["inputs"][key] == {"name": name, "sha256": hashes[key]},
                    f"{relative}: {key} input identity mismatch")
        provenance = "embedded_input_hashes_and_execution_versions"
        driver = document["engine"]["evidence/audits/2026-09-05-rrr-refits/refit.py"]
        require(driver in {digest(root / "refit.py"),
                           digest(root / "inputs/initial-driver-source.txt")},
                f"{relative}: recorded driver not retained")
    else:
        for key, value in hashes.items():
            require(document[key + "_sha256"] == value,
                    f"{relative}: {key} input identity mismatch")
        provenance = "embedded_input_hashes_only_execution_versions_not_recorded"
    result = document["result"]
    roots = [result["obs_limit"], *result["exp_limits"]]
    canonical = result["limits"]
    curves = [canonical["observed"], *canonical["expected"]]
    statuses = [result["limit_status"]["observed"], *result["limit_status"]["expected"]]
    brackets = [result["limit_brackets"]["observed"], *result["limit_brackets"]["expected"]]
    require(len(roots) == len(curves) == len(statuses) == len(brackets) == 6,
            f"{relative}: six curves required")
    require(result["cls_monotonic"] is True, f"{relative}: monotonicity not declared")
    scan = result["scan_mu"]
    observed, expected = result["scan_cls_obs"], result["scan_cls_exp"]
    require(len(scan) == len(observed) == len(expected) == result["n_fits"],
            f"{relative}: scan dimensions disagree")
    require(all(math.isfinite(x) and x >= 0 for x in scan) and
            all(a < b for a, b in zip(scan, scan[1:])), f"{relative}: invalid scan axis")
    require(all(len(row) == 5 for row in expected), f"{relative}: expected scan shape")
    residuals = []
    for index, (value, curve, status, bracket) in enumerate(zip(roots, curves, statuses, brackets)):
        require(math.isfinite(value) and value > 0 and status == curve["status"] == "resolved",
                f"{relative}: unresolved or invalid root")
        require(value == curve["value"] and bracket == curve["bracket"],
                f"{relative}: canonical root disagreement")
        require(len(bracket) == 2 and bracket[0] < value < bracket[1],
                f"{relative}: root outside bracket")
        values = observed if index == 0 else [row[index - 1] for row in expected]
        require(all(math.isfinite(x) and 0 <= x <= 1 for x in values),
                f"{relative}: invalid CLs")
        require(all(b - a <= CL_TOLERANCE for a, b in zip(values, values[1:])),
                f"{relative}: retained curve not monotonic within numerical tolerance")
        require(value in scan and all(x in scan for x in bracket),
                f"{relative}: root or bracket not evaluated")
        require(values[scan.index(bracket[0])] >= CL_TARGET - CL_TOLERANCE and
                values[scan.index(bracket[1])] <= CL_TARGET + CL_TOLERANCE,
                f"{relative}: bracket does not cross target")
        residuals.append(abs(values[scan.index(value)] - CL_TARGET))
    require(max(residuals) < CL_TOLERANCE, f"{relative}: evaluated root misses CLs target")
    require(roots[1:] == sorted(roots[1:]), f"{relative}: expected quantiles unordered")
    return {"source": source(root, relative), "input_binding": provenance,
            "background_sha256": hashes["background"], "patch_sha256": hashes["patch"],
            "observed": roots[0], "expected": roots[3], "expected_quantiles": roots[1:],
            "limit_status": "resolved", "all_six_roots_resolved": True,
            "retained_root_cls_max_absolute_error": max(residuals),
            "retained_scan_evaluations": result["n_fits"],
            "inference": result["inference"],
            "execution_versions": {k: document[k] for k in
                ("python", "backend", "optimizer", "fit_tolerance", "dependencies", "engine")
                if k in document}}


def patch_checks(root):
    full = read(root, "inputs/atlas-m150_dm20-patch.json")
    nominal = read(root, "inputs/atlas-m150_dm20-no-signal-nuisances-patch.json")
    sr_only = read(root, "inputs/atlas-m150_dm20-nominal-sr-only-patch.json")
    background = read(root, "inputs/background.json")
    stripped = copy.deepcopy(full)
    for op in stripped:
        require(op["op"] == "add" and re.fullmatch(r"/channels/\d+/samples/\d+", op["path"]),
                "ATLAS control contains an unexpected workspace operation")
        op["value"]["modifiers"] = [m for m in op["value"]["modifiers"]
                                      if m["name"] == "mu_SIG" and m["type"] == "normfactor"]
        require(len(op["value"]["modifiers"]) == 1, "POI modifier absent or duplicated")
    require(stripped == nominal, "no-nuisance control changes more than signal modifiers")
    def channel(op):
        return background["channels"][int(op["path"].split("/")[2])]["name"]
    sr = [op for op in nominal if channel(op).startswith("SR")]
    cr = [op for op in nominal if channel(op).startswith("CR")]
    require(len(sr) + len(cr) == len(nominal) and sr == sr_only,
            "SR-only control changes more than CR signal additions")
    modifiers = [m for op in full for m in op["value"]["modifiers"]]
    for tag in TAGS:
        native = read(root, f"inputs/{tag}-patch.json")
        require(all(channel(op).startswith("SR") and op["op"] == "add" and
                    op["value"]["modifiers"] == [{"data": None, "name": "mu_SIG", "type": "normfactor"}]
                    for op in native), f"{tag}: native signal-modifier claim does not hold")
    return {"nominal_signal_values_identical_after_modifier_removal": True,
            "sr_signal_values_identical_after_cr_signal_removal": True,
            "background_workspace_identical_all_controls": True,
            "control_regions_still_in_likelihood": True,
            "full_signal_channels": len(full), "sr_signal_channels": len(sr),
            "cr_signal_channels": len(cr), "cr_channels": [channel(op) for op in cr],
            "nominal_cr_signal_sum_at_mu_1": sum(sum(op["value"]["data"]) for op in cr),
            "nominal_sr_signal_sum_at_mu_1": sum(sum(op["value"]["data"]) for op in sr),
            "removed_signal_modifier_instances": len(modifiers) - len(nominal),
            "removed_modifier_types": sorted({m["type"] for m in modifiers if m["type"] != "normfactor"}),
            "native_signal_modifiers": "mu_SIG normfactor only; no signal MC-statistical nuisance"}


def build_summary(root=HERE):
    expected_results = {*ATLAS_FILES, "m50_dm5-jax.json", "m50_dm5-numpy-check.json",
                        "m100_dm2-numpy-check.json",
                        *(f"{tag}-jax-refit.json" for tag in TAGS if tag != "m150_dm20")}
    require({p.name for p in (root / "results").iterdir() if p.is_file()} == expected_results,
            "retained result population differs from the reviewed census")
    context = read(root, "inputs/comparison-context.json")
    points = {row["tag"]: row for row in context["points"]}
    require(set(points) == set(TAGS) and len(context["points"]) == 4, "four distinct anchors required")
    comparisons = {kind: {row["tag"]: row for row in context["comparisons"][kind]}
                   for kind in ("observed", "expected")}
    native = []
    for tag in TAGS:
        old = read(root, f"inputs/{tag}-legacy.json")
        point = points[tag]
        require(close(old["obs_limit"], point["mu95_obs_lo"]), f"{tag}: raw legacy identity mismatch")
        old_roots = {"observed": old["obs_limit"], "expected": old["exp_limits"][2]}
        factor = point["mu95_obs"] / old["obs_limit"] * point["sigma_ref_fb"]
        require(close(point["mu95_exp"] / old_roots["expected"] * point["sigma_ref_fb"], factor),
                f"{tag}: observed/expected normalization factors differ")
        entry = {"tag": tag, "mass_GeV": point["m_parent"], "lsp_mass_GeV": point["m_lsp"],
                 "splitting_GeV": point["dm"], "historical_normalization_fb_per_raw_mu": factor,
                 "normalization_scope": "historical mapping held fixed, not independently physics-certified",
                 "legacy_source": source(root, f"inputs/{tag}-legacy.json"),
                 "legacy_status": "legacy_reported_uncertified", "legacy_raw": old_roots}
        for kind in old_roots:
            require(close(old_roots[kind] * factor, comparisons[kind][tag]["limit_fb"]),
                    f"{tag}: context cross-section inconsistency")
        if tag == "m150_dm20":
            logs = ["logs/m150_dm20-jax-refit.log", "logs/m150_dm20-tight-refit.log"]
            require(not (root / f"results/{tag}-jax-refit.json").exists(), "failed anchor unexpectedly has result")
            for log in logs:
                require("RuntimeError: " + FAILURE in (root / log).read_text(), "failure evidence absent")
            entry.update(status="failed_nonmonotonic", refit=None, comparisons=None,
                         attempts=[{"status": "failed_nonmonotonic", "log": source(root, log),
                                    "declared_fit_tolerance": tolerance,
                                    "execution_input_binding": "not embedded in failure log; retrospective association"}
                                   for log, tolerance in zip(logs, (1e-7, 1e-9))])
        else:
            result = checked_result(root, f"results/{tag}-jax-refit.json", f"{tag}-patch.json")
            entry.update(status="resolved_fixed_template", refit=result)
            entry["comparisons"] = {}
            for kind, old_value in old_roots.items():
                new_value = result[kind]
                reference = comparisons[kind][tag]["reference_fb"]
                entry["comparisons"][kind] = {
                    "legacy_raw_mu": old_value, "refit_raw_mu": new_value,
                    "refit_over_legacy": new_value / old_value,
                    "fractional_change": new_value / old_value - 1,
                    "legacy_sigma_limit_fb": old_value * factor,
                    "refit_sigma_limit_fb_with_historical_normalization": new_value * factor,
                    "published_reference_fb": reference,
                    "legacy_fractional_residual_to_reference": old_value * factor / reference - 1,
                    "refit_fractional_residual_to_reference": new_value * factor / reference - 1}
        native.append(entry)
    numerical_checks = []
    for tag in ("m50_dm5", "m100_dm2"):
        relative = f"results/{tag}-numpy-check.json"
        document = read(root, relative)
        result = next(row["refit"] for row in native if row["tag"] == tag)
        require(document["tag"] == tag and document["mu"] == result["observed"], "NumPy root identity mismatch")
        error = abs(document["cls"] - CL_TARGET)
        require(math.isfinite(error) and error < CL_TOLERANCE, "NumPy observed check misses target")
        numerical_checks.append({"tag": tag, "source": source(root, relative),
                                 "mu": document["mu"], "observed_cls": document["cls"],
                                 "absolute_error_from_0_05": error, "backend": document["backend"],
                                 "fallback_count": document["n_fallback"], "scope": "observed root only",
                                 "execution_input_binding": "not embedded; retrospective tag/root/source association",
                                 "expected_quantile_roots_independently_checked": False})
    probe = read(root, "results/m50_dm5-jax.json")
    require(probe["mu"] == native[0]["legacy_raw"]["observed"], "old-m50 probe root mismatch")
    atlas = []
    sigma_reference = points["m150_dm20"]["sigma_ref_fb"]
    references = {kind: comparisons[kind]["m150_dm20"]["reference_fb"] for kind in comparisons}
    for variant, filename in zip(VARIANTS, ATLAS_FILES):
        patch = filename.replace("-jax-refit.json", "-patch.json").replace("-refit.json", "-patch.json")
        result = checked_result(root, "results/" + filename, patch)
        rows = {}
        for kind in references:
            published_mu = references[kind] / sigma_reference
            full_value = result[kind] if not atlas else atlas[0][kind]["raw_mu"]
            previous = result[kind] if not atlas else atlas[-1][kind]["raw_mu"]
            rows[kind] = {"raw_mu": result[kind], "sigma_limit_fb": result[kind] * sigma_reference,
                          "published_reference_fb": references[kind], "published_reference_mu": published_mu,
                          "fractional_residual_to_reference": result[kind] / published_mu - 1,
                          "fractional_change_from_full": result[kind] / full_value - 1,
                          "fractional_change_from_previous": result[kind] / previous - 1}
        atlas.append({"variant": variant, "fit": result, **rows})
    metadata = read(root, "inputs/atlas-m150_dm20-metadata.json")
    require(metadata["patch_metadata"]["values"] == ["degenerate", 150.0, 130.0], "ATLAS anchor mismatch")
    # pyhf.utils.digest uses sorted-key json.dumps with its default separators.
    # This is intentionally different from hashing the raw indented file bytes.
    background_digest = hashlib.sha256(json.dumps(read(root, "inputs/background.json"),
                                                  sort_keys=True).encode("utf8")).hexdigest()
    declared_digest = metadata["patchset_metadata"]["digests"]["sha256"]
    official_background = read(root, "inputs/background-official.json")
    official_digest = hashlib.sha256(json.dumps(official_background, sort_keys=True).encode("utf8")).hexdigest()
    require(official_digest == declared_digest, "official background fails published patchset digest")
    representation_differences = equivalent_numbers(read(root, "inputs/background.json"), official_background)
    equivalence_record = read(root, "inputs/background-equivalence.json")
    for key, value in {
        "official_raw_sha256": digest(root / "inputs/background-official.json"),
        "retained_raw_sha256": digest(root / "inputs/background.json"),
        "patchset_canonical_sha256": declared_digest,
        "retained_canonical_sha256": background_digest,
        "exhaustive_type_differences": representation_differences,
        "json_numeric_value_and_structure_equal": True,
    }.items():
        require(equivalence_record[key] == value, f"background equivalence record disagrees: {key}")
    return {"schema_version": 1, "scope": "retained fixed-template numerical diagnosis; no global physics closure",
            "inference_or_simulation_performed_by_summarizer": False,
            "alpha": CL_TARGET, "retained_root_check_absolute_tolerance": CL_TOLERANCE,
            "native_anchor_count": 4, "native_resolved_count": 3, "native_failed_count": 1,
            "native_anchors": native, "independent_backend_observed_checks": numerical_checks,
            "legacy_m50_observed_probe": {"source": source(root, "results/m50_dm5-jax.json"),
                "raw_mu": probe["mu"], "cls_at_legacy_limit": probe["cls_at_legacy_limit"],
                "absolute_error_from_0_05": abs(probe["cls_at_legacy_limit"] - CL_TARGET),
                "execution_input_binding": "not embedded; retrospective tag/root/source association"},
            "incomplete_attempts": [{"tag": tag, "status": "incomplete_log_no_completed_result",
                "log": source(root, f"logs/{tag}-refit.log"),
                "reason": "retained log stops after four scan evaluations; no failure diagnosis inferred"}
                for tag in ("m50_dm5", "m100_dm2")],
            "atlas_anchor": {"parent_mass_GeV": 150, "lsp_mass_GeV": 130,
                "model": "degenerate selectron/smuon left and right chiralities",
                "reference_sigma_fb": sigma_reference, "metadata": metadata,
                "variants": atlas, "control_integrity": patch_checks(root),
                "published_background_identity": {
                    "digest_method": "pyhf.utils.digest: SHA256 of json.dumps(workspace, sort_keys=True)",
                    "patchset_declared_sha256": declared_digest,
                    "retained_background_canonical_sha256": background_digest,
                    "matches_patchset_declared_background": background_digest == declared_digest,
                    "official_background": source(root, "inputs/background-official.json"),
                    "official_background_canonical_sha256": official_digest,
                    "official_matches_patchset_declared_background": True,
                    "retained_and_official_numeric_structure_equal": True,
                    "representation_difference_count": len(representation_differences),
                    "representation_differences": representation_differences,
                    "equivalence_evidence": source(root, "inputs/background-equivalence.json"),
                    "scope": "published signal patch on a numerically identical background; raw/canonical byte spellings differ"},
                "scope": "one official-template counterfactual, not a global correction or permission to borrow nuisances"},
            "context_source": source(root, "inputs/comparison-context.json"),
            "limitations": [
                "Native refits keep historical event samples, signal templates and normalization unchanged.",
                "Resolved numerical roots do not certify acceptance, normalization, MC precision, systematic completeness or coverage.",
                "Native signal samples have only a POI normfactor, no signal MC-statistical nuisance.",
                "NumPy checks re-evaluate two observed roots; they are not independent six-curve refits or physics validation.",
                "Native m150_dm20 remains unresolved after two nonmonotonic attempts.",
                "Background serialization differs from the published digest only through equal integer/float spellings; explicit numerical-structure equivalence is checked.",
                "The official anchor and native m150 use different signal templates; omission effects are not a native correction.",
                "Native/check records have weaker execution provenance than the versioned ATLAS results; the manifest binds retained bytes only."]}


def plot(summary, target):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(12.6, 5.3), gridspec_kw={"width_ratios": [1.1, 1]})
    colors = {"observed": "#1864ab", "expected": "#bf5b16"}
    markers = {"observed": "o", "expected": "s"}
    for kind, offset in (("observed", -.13), ("expected", .13)):
        for index, row in enumerate(summary["native_anchors"]):
            if row["comparisons"]:
                value = 100 * row["comparisons"][kind]["fractional_change"]
                axes[0].scatter(value, index + offset, marker=markers[kind], color=colors[kind], s=48,
                                label=("Observed" if kind == "observed" else "Expected median") if index == 0 else None)
                axes[0].annotate(f"{value:+.2f}%", (value, index + offset), xytext=(-6, 0),
                                 textcoords="offset points", ha="right", va="center", fontsize=9)
        for index, row in enumerate(summary["atlas_anchor"]["variants"]):
            value = 100 * row[kind]["fractional_residual_to_reference"]
            axes[1].scatter(value, index + offset, marker=markers[kind], color=colors[kind], s=48)
            axes[1].annotate(f"{value:+.2f}%", (value, index + offset), xytext=(-6, 0),
                             textcoords="offset points", ha="right", va="center", fontsize=9)
    axes[0].text(-28, 2, "Failed twice: nonmonotonic\nNo refit limit reported", ha="center", va="center",
                 fontsize=10, color="#9f3030", bbox={"facecolor": "#fff4f2", "edgecolor": "none", "pad": 5})
    axes[0].set_yticks(range(4), ["50 / 45", "100 / 98", "150 / 130", "200 / 180"])
    axes[0].set_ylim(3.6, -.6); axes[0].set_xlim(-66, 5)
    axes[0].set_ylabel("Native anchor: parent / LSP mass [GeV]")
    axes[0].set_xlabel("Refit / legacy raw limit − 1 [%]")
    axes[0].set_title("Fixed native templates: 3 resolved, 1 failed", loc="left", fontsize=12)
    axes[1].set_yticks(range(3), ["Full ATLAS patch", "Signal nuisances\nremoved", "Then CR signal\nremoved"])
    axes[1].set_ylim(2.6, -.6); axes[1].set_xlim(-20, 3)
    axes[1].set_xlabel("Limit / matching published reference − 1 [%]")
    axes[1].set_title("ATLAS signal patch: 150 / 130 GeV", loc="left", fontsize=12)
    for ax in axes:
        ax.axvline(0, color="0.4", lw=1, linestyle="--", zorder=0)
        ax.grid(axis="x", alpha=.18); ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False, bbox_to_anchor=(.5, .09))
    fig.text(.5, .035, "Numerically equivalent published background. Fixed native normalization. No global physics closure or uncertainty transfer.",
             ha="center", fontsize=10)
    fig.subplots_adjust(left=.10, right=.985, top=.88, bottom=.26, wspace=.54)
    fig.savefig(target, dpi=170, metadata={"Software": "Ravel retained-refit audit"})
    plt.close(fig)


def files(root):
    return sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts
                  and p.name != "manifest.json" and not p.name.endswith(".pyc"))


def seal(root=HERE):
    build_summary(root)
    records = []
    for path in files(root):
        require(path.stat().st_size <= 5_000_000, f"artifact exceeds 5 MB: {path.name}")
        if path.suffix in (".json", ".py", ".md", ".txt", ".log"):
            require(not re.search(r"/(?:Users|home)/[^/\s]+/", path.read_text()),
                    f"personal absolute path in {path.name}")
        records.append({"path": str(path.relative_to(root)), "sha256": digest(path),
                        "bytes": path.stat().st_size})
    manifest = {"schema_version": 1, "scope": "retained byte integrity; not execution attestation or physics certification",
                "algorithm": "sha256", "files": records}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")


def check(root=HERE):
    manifest = read(root, "manifest.json")
    actual = {str(p.relative_to(root)): p for p in files(root)}
    records = manifest["files"]
    require(len(records) == len({r["path"] for r in records}), "duplicate manifest entries")
    require(set(actual) == {r["path"] for r in records}, "manifest inventory mismatch")
    for row in records:
        path = actual[row["path"]]
        require(row["bytes"] == path.stat().st_size and row["sha256"] == digest(path),
                f"manifest mismatch: {row['path']}")
    calculated = build_summary(root)
    require(calculated == read(root, "summary.json"), "summary differs from retained evidence")
    return {"pass": True, "files_verified": len(records), "native_resolved": 3,
            "native_failed": 1, "atlas_variants": 3, "expensive_inference_performed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--seal", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.write:
        summary = build_summary()
        (HERE / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
        plot(summary, HERE / "refit-comparison.png")
    if args.seal:
        seal()
    if args.check or not (args.write or args.seal):
        print(json.dumps(check(), indent=2))


if __name__ == "__main__":
    main()
