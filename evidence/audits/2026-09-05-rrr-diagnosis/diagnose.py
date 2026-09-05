#!/usr/bin/env python3
"""Audit retained scans without changing or refitting their scientific results.

Default operation replays the shipped, hash-provenanced extracted input snapshot.
--capture reads development archives and requires the source checkout. No event
generation, fitting, interpolation correction, or baseline rewriting occurs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
import sys
import tomllib


HERE = Path(__file__).resolve().parent
CAMPAIGNS = {
    "original": "trial-runs/sleptonscan_fig3_SCAN",
    "pdf_rescan": "trial-runs/CR004rescan_SCAN",
    "fresh_cteq6l1": "trial-runs/2026-08-28_SUSY-2018-16_slepton-fig3-fresh/fig3_SCAN",
}
KINDS = ("observed", "expected")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def quantile(values, p):
    """Linear sample quantile; descriptive, not a confidence interval."""
    vals = sorted(values)
    if not vals:
        return None
    at = p * (len(vals) - 1)
    i = int(at)
    return vals[i] + (vals[min(i + 1, len(vals) - 1)] - vals[i]) * (at - i)


def distribution(values):
    vals = [float(x) for x in values]
    if any(not math.isfinite(x) for x in vals):
        raise ValueError("nonfinite distribution input")
    return {
        "n": len(vals), "negative": sum(x < 0 for x in vals),
        "positive": sum(x > 0 for x in vals), "zero": sum(x == 0 for x in vals),
        "signed_median": quantile(vals, .5),
        "median_absolute": quantile([abs(x) for x in vals], .5),
        "mean": statistics.mean(vals) if vals else None,
        "quantiles": {str(p): quantile(vals, p) for p in (0, .1, .25, .5, .75, .9, 1)},
        "within_15_percent": sum(abs(x) <= .15 for x in vals),
        "within_25_percent": sum(abs(x) <= .25 for x in vals),
    }


def crossing_diagnostic(x, y, reported, level=.05):
    """Inspect sampled CLs only. A bracket is not a certified numerical root.

    Log interpolation is a sensitivity diagnostic, never a replacement result.
    Near-duplicate floating point coordinates are retained as historical evidence.
    Nonmonotonic or invalid samples cannot be made valid by sorting on CLs.
    """
    if (len(x) != len(y) or len(x) < 2 or not math.isfinite(reported)
            or reported <= 0 or any(not math.isfinite(t) for t in x + y)
            or any(t < 0 for t in x) or any(not 0 <= t <= 1 for t in y)
            or any(a >= b for a, b in zip(x, x[1:]))):
        return {"status": "invalid_samples"}
    increases = [i for i, (a, b) in enumerate(zip(y, y[1:])) if b - a > 1e-6]
    hits = [i for i in range(len(x) - 1) if y[i] >= level >= y[i + 1]
            and y[i] != y[i + 1]]
    if not hits:
        return {"status": "all_below" if max(y) < level else
                "all_above" if min(y) > level else "no_downward_crossing",
                "material_increases": increases}
    if len(hits) != 1:
        return {"status": "ambiguous_samples", "downward_crossings": len(hits),
                "material_increases": increases}
    i = hits[0]
    fraction = (level - y[i]) / (y[i + 1] - y[i])
    linear = x[i] + fraction * (x[i + 1] - x[i])
    log = None
    if min(y[i], y[i + 1]) > 0:
        fraction_log = (math.log(level) - math.log(y[i])) / (math.log(y[i + 1]) - math.log(y[i]))
        log = x[i] + fraction_log * (x[i + 1] - x[i])
    return {
        "status": "ambiguous_samples" if increases else "sampled_bracket", "interval_index": i,
        "material_increases": increases,
        "mu_bracket": [x[i], x[i + 1]], "cls_bracket": [y[i], y[i + 1]],
        "reported_mu": reported, "width_over_reported": (x[i + 1] - x[i]) / reported,
        "linear_interpolation_mu": linear,
        "reported_matches_linear": math.isclose(linear, reported, rel_tol=1e-10, abs_tol=1e-12),
        "log_interpolation_mu_diagnostic_only": log,
        "log_vs_reported_fraction_diagnostic_only": log / reported - 1 if log else None,
        "cls_evaluated_at_reported": any(math.isclose(t, reported, rel_tol=1e-10, abs_tol=1e-12) for t in x),
    }


def capture(root):
    root = root.resolve()
    sys.path.insert(0, str(root / "src"))
    from ravel.plotting.scan_contour import comparison_data, read_limit_grid

    sources = {}

    def read(relative, optional=False):
        p = root / relative
        if not p.is_file():
            if optional:
                return None
            raise FileNotFoundError(p)
        sources[str(relative)] = {"sha256": sha(p), "bytes": p.stat().st_size}
        return p.read_text()

    reference = "evidence/audits/2026-09-05-scan-fidelity/atlas-limit-grid.yaml"
    read(reference)
    grids = {kind: read_limit_grid(root / reference, kind) for kind in KINDS}
    background = "stages/01-event-generation/build/tools/miniforge3/envs/pipeline/share/mapyde/likelihoods/Slepton_bkgonly.json"
    background_doc = json.loads(read(background))
    background_channels = [c["name"] for c in background_doc["channels"]]
    campaigns = {}
    for name, directory in CAMPAIGNS.items():
        scan = json.loads(read(directory + "/scan.json"))
        manifest = json.loads(read(directory + "/scan_manifest.json"))
        mpoints = {p["tag"]: p for p in manifest["points"]}
        comparisons = {kind: comparison_data(scan, grids[kind], kind) for kind in KINDS}
        evidence = {}
        for point in scan["points"]:
            tag = point["tag"]
            run = mpoints[tag]["run_dir"]
            exclusion = json.loads(read(run + "/output/exclusion.json"))
            config_path = run + "/" + mpoints[tag]["config"]
            config = tomllib.loads(read(config_path))
            table = list(csv.DictReader(io.StringIO(read(run + "/output/EwkCompressed2018.txt"))))
            table = {r["SR"]: {k: float(v) for k, v in r.items() if k != "SR"} for r in table}
            patch = json.loads(read(run + "/output/EwkCompressed2018_patch.json"))
            samples = []
            for op in patch:
                if op.get("op") != "add" or not re.fullmatch(r"/channels/\d+/samples/\d+", op.get("path", "")):
                    raise ValueError(f"unexpected retained patch operation: {run}")
                channel = background_channels[int(op["path"].split("/")[2])]
                samples.append({"channel": channel, "data": op["value"]["data"],
                                "modifiers": op["value"]["modifiers"]})
            logs = {}
            for log in ("madgraph", "pythia", "delphes", "analysis", "simpleanalysis", "orchestrator_launch"):
                value = read(run + "/logs/" + log + ".log", optional=True)
                if value is None:
                    logs[log] = {"available": False}
                    continue
                if log == "madgraph":
                    logs[log] = {"available": True,
                        "cross_sections_pb": [float(v) for v in re.findall(r"Cross-section\s*:\s*([\d.eE+\-]+)", value)],
                        "seed_commands": re.findall(r"^set iseed (\d+)", value, re.M),
                        "seed_offsets": re.findall(r"Using random number seed offset = (\d+)", value)}
                elif log == "pythia":
                    logs[log] = {"available": True,
                        "events_written": [int(v) for v in re.findall(r"pythia_shower: wrote (\d+) events", value)]}
                elif log == "delphes":
                    logs[log] = {"available": True,
                        "reading_hepmc": "** Reading " in value,
                        "exiting_message": "** Exiting..." in value}
                elif log == "analysis":
                    logs[log] = {"available": True,
                        "applied_cross_sections_pb": [float(v) for v in re.findall(r"Using cross section ([\d.eE+\-]+)", value)],
                        "events_written": [int(v) for v in re.findall(r"wrote (\d+) entries", value)]}
                elif log == "simpleanalysis":
                    logs[log] = {"available": True,
                        "events_read_rjr": [list(map(int, m)) for m in re.findall(r"(\d+) events read, (\d+) reach", value)],
                        "overlapping_sr_count": [int(v) for v in re.findall(r"total SR-accept count \(sum over SRs\): (\d+)", value)]}
                else:
                    logs[log] = {"available": True,
                        "pipeline_starts": re.findall(r"pipeline start ([\d\- :]+)\s+config", value),
                        "failure_stages": re.findall(r"STOPPED at stage: (\w+)", value),
                        "completion_times": re.findall(r"ALL_STAGES_COMPLETE ([\d\- :]+)", value)}
            cards = []
            for path in sorted((root / run).rglob("run_card.dat")):
                relative = str(path.relative_to(root))
                card = read(relative)
                settings = {}
                for line in card.splitlines():
                    line = line.split("#", 1)[0].split("!", 1)[0].strip()
                    match = re.fullmatch(r"(.*?)\s*=\s*(pdlabel|iseed|ptj1min|ptj|lhaid|nevents)", line)
                    if match:
                        settings[match[2]] = match[1].strip()
                cards.append({"path": relative, "settings": settings})
            evidence[tag] = {"source_run_directory": run, "exclusion": exclusion,
                "config": {"madgraph": config["madgraph"], "analysis": config["analysis"],
                           "pyhf": config["pyhf"], "delphes": config["delphes"]},
                "selection": table, "signal_samples": samples, "logs": logs,
                "retained_effective_run_cards": cards}
        campaigns[name] = {"scan": scan, "comparisons": comparisons, "point_evidence": evidence}
    extra_paths = ["docs/development/change-registry.md", "trial-runs/sleptonscan_fig3_SCAN/RESULT.md",
        "trial-runs/CR004rescan_SCAN/CR004-FULL-RESULT.md",
        "trial-runs/2026-08-28_SUSY-2018-16_slepton-fig3-fresh/RESULT.md",
        "src/ravel/physics/prepare_native_slepton.py", "src/ravel/workflow/scan_orchestrator.py",
        "src/ravel/limits.py", "src/ravel/plotting/scan_contour.py"]
    for p in extra_paths:
        read(p)
    waypoint_path = "trial-runs/2026-08-28_SUSY-2018-16_slepton-fig3-fresh/outputs/acceff_cert_m150_dm20_incl4.json"
    waypoint = json.loads(read(waypoint_path))
    for path in sorted((root / "src/ravel/data/cross_sections").glob("slepton*.json")):
        read(str(path.relative_to(root)))
    revision = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], text=True, capture_output=True, check=True).stdout.strip()
    return {"schema_version": 1, "scope": "retained historical archive diagnosis; no new event generation or refit",
        "source_commit": revision, "sources": sources, "reference": reference,
        "background": {"path": background, "channels": background_channels},
        "campaigns": campaigns, "waypoint_acceptance_certificate": waypoint}


def analyse(snapshot):
    rows = []
    summaries = {}
    for name, campaign in snapshot["campaigns"].items():
        scan = campaign["scan"]
        points = {r["tag"]: r for r in scan["points"]}
        if len(points) != len(scan["points"]):
            raise ValueError("duplicate retained tag")
        summary = {"planned": scan["n_planned"], "recorded": len(points), "kinds": {}}
        for kind in KINDS:
            comparison = campaign["comparisons"][kind]
            seen = set()
            for r in comparison["records"]:
                if r["tag"] in seen:
                    raise ValueError("duplicate comparison tag")
                seen.add(r["tag"])
                point = points[r["tag"]]
                evidence = campaign["point_evidence"][r["tag"]]
                ex = evidence["exclusion"]
                raw_mu = ex["obs_limit"] if kind == "observed" else ex["exp_limits"][2]
                y = ex["scan_cls_obs"] if kind == "observed" else [v[2] for v in ex["scan_cls_exp"]]
                numerical = crossing_diagnostic(ex["scan_mu"], y, raw_mu)
                table = evidence["selection"]
                n_gen = table["All"]["events"]
                applied_xs = table["All"]["acceptance"]  # This historical All row stores pb, not acceptance.
                luminosity = evidence["config"]["analysis"]["lumi"]
                weight = applied_xs * luminosity / n_gen
                signals = evidence["signal_samples"]
                counts = [sum(s["data"]) / weight for s in signals]
                detector_counts = evidence["logs"]["analysis"].get("events_written", [])
                detector_n = detector_counts[-1] if detector_counts else None
                exposure_complete = detector_n == n_gen
                detector_counts_proxy = [c * detector_n / n_gen for c in counts] if detector_n else None
                modifiers = sorted({m["type"] for s in signals for m in s["modifiers"]})
                model_mu = point["mu95_obs" if kind == "observed" else "mu95_exp"]
                by_mass = scan["model_basis"]["by_mass"][str(int(point["m_parent"]))]
                incl4 = by_mass["sigma_incl4_lo_fb"]
                direct_no_k = raw_mu * scan["nlo_renorm"]["flat_k_replaced"] * incl4
                ul = model_mu * point["sigma_ref_fb"]
                row = {"campaign": name, "kind": kind, "tag": r["tag"],
                    "m_parent": point["m_parent"], "dm": point["dm"],
                    "comparison_status": r["status"], "limit_status": r["limit_status"],
                    "historical_only": r["historical_only"],
                    "reference_fb": r.get("reference_fb"), "limit_fb": r.get("limit_fb"),
                    "residual": r.get("residual"), "reported_raw_mu": raw_mu,
                    "reported_model_mu": model_mu, "numerical": numerical,
                    "normalization": {"all_row_applied_cross_section_pb": applied_xs,
                        "scan_tagged_lo_cross_section_pb": point["sigma_ref_fb_lo"] / (1000 * scan["nlo_renorm"]["flat_k_replaced"]),
                        "model_cross_section_fb": point["sigma_ref_fb"],
                        "inclusive4_lo_fb": incl4, "ul_without_k_or_model_sigma_fb": direct_no_k,
                        "rounding_cancellation_fraction": ul / direct_no_k - 1,
                        "generator_log_cross_sections_pb": evidence["logs"]["madgraph"].get("cross_sections_pb", []),
                        "analysis_log_applied_cross_sections_pb": evidence["logs"]["analysis"].get("applied_cross_sections_pb", [])},
                    "mc": {"n_generated": n_gen, "n_detector_events": detector_n,
                        "detector_exposure_complete": exposure_complete,
                        "detector_fraction_of_generated": detector_n / n_gen if detector_n is not None else None,
                        "signal_channels": len(signals),
                        "signal_modifier_types": modifiers, "signal_stat_nuisance_present": any(t in modifiers for t in ["staterror", "shapesys"]),
                        "channel_effective_count_proxy": counts,
                        "channel_count_proxy_using_detector_exposure": detector_counts_proxy,
                        "nonzero_channels_with_proxy_below_10": sum(0 < x < 10 for x in counts),
                        "zero_signal_channels": sum(x == 0 for x in counts),
                        "selected_exclusive_count_proxy": sum(counts),
                        "count_proxy_max_integer_distance": max(abs(x - round(x)) for x in counts),
                        "sr_s_imt2h_events": table.get("SR_S_iMT2h", {}).get("events"),
                        "sr_s_imt2h_relative_count_error": 1 / math.sqrt(table["SR_S_iMT2h"]["events"]) if table.get("SR_S_iMT2h", {}).get("events", 0) > 0 else None},
                    "provenance_flags": {"effective_run_card_retained": bool(evidence["retained_effective_run_cards"]),
                        "generator_log_missing_final_cross_section": not evidence["logs"]["madgraph"].get("cross_sections_pb"),
                        "retry_failure_stages": evidence["logs"]["orchestrator_launch"].get("failure_stages", []),
                        "pipeline_completion_count": len(evidence["logs"]["orchestrator_launch"].get("completion_times", []))}}
                if r["status"] == "matched":
                    expected = ul / r["reference_fb"] - 1
                    if not math.isclose(expected, r["residual"], rel_tol=1e-12, abs_tol=1e-12):
                        raise ValueError("snapshot comparison arithmetic mismatch")
                rows.append(row)
            if seen != set(points):
                raise ValueError("comparison must retain all scan points")
            selected = [r for r in rows if r["campaign"] == name and r["kind"] == kind and r["comparison_status"] == "matched"]
            widths = [r["numerical"]["width_over_reported"] for r in selected if r["numerical"]["status"] == "sampled_bracket"]
            summary["kinds"][kind] = {"counts": comparison["counts"],
                "signed_residual_distribution": distribution([r["residual"] for r in selected]),
                "sampled_bracket_width_over_reported": distribution(widths),
                "plain_linear_interpolation_matches": sum(r["numerical"].get("reported_matches_linear", False) for r in selected),
                "first_interval_tags": [r["tag"] for r in selected if r["numerical"].get("interval_index") == 0],
                "nonmonotonic_tags": [r["tag"] for r in selected if r["numerical"].get("material_increases")],
                "incomplete_detector_exposure_tags": [r["tag"] for r in rows if r["campaign"] == name and r["kind"] == kind and not r["mc"]["detector_exposure_complete"]],
                "complete_exposure_sensitivity_not_replacement": distribution([r["residual"] for r in selected if r["mc"]["detector_exposure_complete"]]),
                "positive_residuals": [{"tag": r["tag"], "residual": r["residual"]} for r in selected if r["residual"] > 0],
                "worst_negative_residuals": [{"tag": r["tag"], "residual": r["residual"]} for r in sorted(selected, key=lambda r: r["residual"])[:8]]}
        summaries[name] = summary
    pairs = {}
    for a, b in [("original", "pdf_rescan"), ("original", "fresh_cteq6l1"), ("pdf_rescan", "fresh_cteq6l1")]:
        pairs[a + "_to_" + b] = {}
        for kind in KINDS:
            ar = {r["tag"]: r for r in rows if r["campaign"] == a and r["kind"] == kind}
            br = {r["tag"]: r for r in rows if r["campaign"] == b and r["kind"] == kind}
            matched = []
            held = []
            for tag in sorted(set(ar) | set(br)):
                if tag not in ar or tag not in br or any(r["comparison_status"] != "matched" for r in [ar.get(tag, {}), br.get(tag, {})]):
                    held.append(tag)
                    continue
                first, second = ar[tag], br[tag]
                matched.append({"tag": tag, "m_parent": first["m_parent"], "dm": first["dm"],
                    "limit_ratio_minus_one": second["limit_fb"] / first["limit_fb"] - 1,
                    "residual_difference": second["residual"] - first["residual"],
                    "first_residual": first["residual"], "second_residual": second["residual"],
                    "selected_sr_s_count_ratio": second["mc"]["sr_s_imt2h_events"] / first["mc"]["sr_s_imt2h_events"] if first["mc"]["sr_s_imt2h_events"] else None})
                matched[-1]["both_detector_exposures_complete"] = first["mc"]["detector_exposure_complete"] and second["mc"]["detector_exposure_complete"]
            pairs[a + "_to_" + b][kind] = {"planned_union": len(set(ar) | set(br)), "matched": len(matched),
                "ineligible_tags": held, "ratio_distribution": distribution([r["limit_ratio_minus_one"] for r in matched]),
                "residual_difference_distribution": distribution([r["residual_difference"] for r in matched]),
                "complete_exposure_ratio_sensitivity_not_replacement": distribution([r["limit_ratio_minus_one"] for r in matched if r["both_detector_exposures_complete"]]),
                "by_parent_mass": {str(m): distribution([r["limit_ratio_minus_one"] for r in matched if r["m_parent"] == m]) for m in sorted({r["m_parent"] for r in matched})},
                "by_splitting": {str(m): distribution([r["limit_ratio_minus_one"] for r in matched if r["dm"] == m]) for m in sorted({r["dm"] for r in matched})},
                "points": matched}
    return {"schema_version": 1, "scope": "descriptive historical audit; no causal PDF estimate, refit, or new certification",
        "source_commit_at_capture": snapshot["source_commit"], "summary": summaries, "pairs": pairs, "points": rows}


def render(report, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = {"original": "Original (cteq6l1, old prep)", "pdf_rescan": "PDF rescan (nn23nlo, later prep)", "fresh_cteq6l1": "Fresh (cteq6l1, later prep)"}
    colors = {"original": "#2166ac", "pdf_rescan": "#b2182b", "fresh_cteq6l1": "#238b45"}
    fig, axes = plt.subplots(1, 2, figsize=(11.8, 4.7), sharey=True)
    for ax, kind in zip(axes, KINDS):
        for i, name in enumerate(labels):
            rows = [r for r in report["points"] if r["campaign"] == name and r["kind"] == kind and r["comparison_status"] == "matched"]
            ys = sorted(r["residual"] for r in rows)
            ax.plot([(j+.5)/len(ys) for j in range(len(ys))], ys, marker=".", color=colors[name], label=f"{labels[name]} ({len(ys)}/52)")
        ax.axhline(0, color="black", linewidth=.8)
        ax.axhspan(-.15, .15, color="gray", alpha=.12)
        ax.set_title(kind.capitalize()); ax.set_xlabel("Fraction of eligible retained points (ordered)")
        ax.grid(alpha=.15)
    axes[0].set_ylabel("(Retained limit − ATLAS limit) / ATLAS limit")
    axes[1].legend(fontsize=7.6, loc="lower right")
    fig.text(.5, .015, "Exact reference cells; historical interpolation estimates, not new numerical roots. Shading: ±15%, not a confidence band.", ha="center", fontsize=8)
    fig.tight_layout(rect=(0,.05,1,1)); fig.savefig(out/"signed-residuals.png", dpi=170); plt.close(fig)
    fig, axes = plt.subplots(1,2,figsize=(11.8,4.8))
    for ax, kind in zip(axes,KINDS):
        pair = report["pairs"]["original_to_pdf_rescan"][kind]
        for row in pair["points"]:
            ax.scatter(row["m_parent"], row["limit_ratio_minus_one"], c=row["dm"], cmap="viridis", vmin=2,vmax=40,s=32)
            if not row["both_detector_exposures_complete"]:
                ax.scatter(row["m_parent"], row["limit_ratio_minus_one"], marker="x", color="black", s=64)
        ax.axhline(0,color="black",lw=.8); ax.set_title(f"{kind.capitalize()}: {pair['matched']}/52 paired points")
        ax.set_xlabel("Slepton mass [GeV]"); ax.grid(alpha=.15)
    axes[0].set_ylabel("Rescan / original retained limit − 1")
    from matplotlib.cm import ScalarMappable
    fig.subplots_adjust(bottom=.19,right=.83,wspace=.25)
    color_axis = fig.add_axes([.87, .2, .022, .65])
    bar=fig.colorbar(ScalarMappable(norm=plt.Normalize(2,40),cmap="viridis"),cax=color_axis);bar.set_label("Mass splitting [GeV]")
    fig.text(.48,.055,"PDF, generation cut, numerical sampler, and event realization changed; this is not an isolated PDF response.",ha="center",fontsize=8)
    fig.text(.48,.018,"Black ×: incomplete detector exposure, retained in this historical comparison (2 of 48 pairs).",ha="center",fontsize=8)
    fig.savefig(out/"paired-changes.png",dpi=170);plt.close(fig)


def write_report(snapshot, out):
    if out.exists():
        raise FileExistsError(f"refusing to overwrite audit directory: {out}")
    out.mkdir(parents=True)
    report = analyse(snapshot)
    # Preserve the complete population while keeping the public extraction below
    # the distribution's per-file size limit. JSON viewers can format it on demand.
    (out / "retained-inputs.json").write_text(json.dumps(snapshot, separators=(",", ":"), allow_nan=False) + "\n")
    (out / "diagnosis.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    columns = ["campaign", "kind", "tag", "m_parent", "dm", "comparison_status", "limit_status", "historical_only", "reference_fb", "limit_fb", "residual", "reported_raw_mu", "reported_model_mu"]
    with (out / "points.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns + ["sample_status", "bracket_width_over_reported", "linear_interpolation_match", "first_interval", "sr_s_imt2h_events", "n_detector_events", "detector_exposure_complete", "signal_stat_nuisance_present"], lineterminator="\n")
        writer.writeheader()
        for row in report["points"]:
            writer.writerow({**{k: row[k] for k in columns}, "sample_status": row["numerical"]["status"],
                "bracket_width_over_reported": row["numerical"].get("width_over_reported"),
                "linear_interpolation_match": row["numerical"].get("reported_matches_linear"),
                "first_interval": row["numerical"].get("interval_index") == 0,
                "sr_s_imt2h_events": row["mc"]["sr_s_imt2h_events"],
                "n_detector_events": row["mc"]["n_detector_events"],
                "detector_exposure_complete": row["mc"]["detector_exposure_complete"],
                "signal_stat_nuisance_present": row["mc"]["signal_stat_nuisance_present"]})
    render(report, out)
    provenance = {"schema_version": 1, "script_sha256": sha(__file__),
        "source_snapshot_sha256": sha(out / "retained-inputs.json"),
        "source_commit_at_capture": snapshot["source_commit"],
        "outputs": {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()},
        "python": sys.version.split()[0], "original_sources_count": len(snapshot["sources"])}
    (out / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--inputs", type=Path, default=HERE / "retained-inputs.json")
    p.add_argument("--capture", action="store_true")
    p.add_argument("--root", type=Path, default=HERE.parents[2])
    args = p.parse_args()
    snapshot = capture(args.root) if args.capture else json.loads(args.inputs.read_text())
    report = write_report(snapshot, args.out)
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
