#!/usr/bin/env python3
"""Offline arithmetic and inventory checks for one dated evidence bundle.

Standard library only. This does not reconstruct private receipts, read events,
fit a likelihood, or certify detector acceptance or statistical coverage.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import re

HERE = Path(__file__).resolve().parent
QUANTILES = ("observed", "expected_minus2", "expected_minus1", "expected_median",
             "expected_plus1", "expected_plus2")
NATIVE_IDS = ("nominal_20k", "nominal_40k", "pooled_60k", "lower_20k")
OFFICIAL_IDS = ("full", "signal_mc_only", "signal_nominal_only")
NATIVE_STAGES = ("prepare", "madgraph", "unpack_lhe", "lhe_check", "pythia",
                 "normalization", "delphes", "analysis", "simpleanalysis",
                 "sa2json", "pyhf", "native_report")
POOL_STAGES = ("pool", "patch", "pyhf", "exclusion")
ENGINE = "a85206eee4c40c18e893d1ea93c4ede9c741a782c3b0d367a53fa7011bc0e466"
FRESH_CONTEXT = "frozen start portfolio, descending then ascending root/bound checks"
SHA = re.compile(r"[0-9a-f]{64}\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, *, positive=False, nonnegative=False):
    require(type(value) in (int, float) and math.isfinite(value), "Nonfinite/non-numeric operand")
    require(not positive or value > 0, "Expected positive operand")
    require(not nonnegative or value >= 0, "Expected nonnegative operand")
    return value


def integer(value, *, minimum=0):
    require(type(value) is int and value >= minimum, "Invalid integer denominator")
    return value


def close(actual, expected):
    if expected is None or type(expected) in (str, bool):
        require(type(actual) is type(expected) and actual == expected, "Status/missingness differs")
    elif type(expected) is int:
        require(type(actual) is int and actual == expected, "Integer value differs")
    else:
        number(actual)
        require(math.isclose(actual, expected, rel_tol=2e-12, abs_tol=1e-22),
                "Arithmetic differs from retained operands")


def finite_tree(value):
    if type(value) is float:
        number(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            require(type(key) is str, "Non-string JSON key")
            finite_tree(item)
    elif isinstance(value, list):
        for item in value:
            finite_tree(item)
    else:
        require(value is None or type(value) in (str, int, bool), "Unsupported JSON type")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key")
        result[key] = value
    return result


def read_json(path):
    value = json.loads(Path(path).read_text(), object_pairs_hook=_pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    finite_tree(value)
    return value


def encode(value):
    finite_tree(value)
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def path_under(root, name):
    require(type(name) is str and "\\" not in name, "Invalid relative path")
    path = PurePosixPath(name)
    require(not path.is_absolute() and path.parts and all(p not in (".", "..") for p in path.parts)
            and str(path) == name, "Noncanonical relative path")
    current = Path(root)
    require(not current.is_symlink(), "Symlink root")
    for part in path.parts:
        current /= part
        require(not current.is_symlink(), "Symlink artifact")
    require(current.resolve().is_relative_to(Path(root).resolve()), "Escaping artifact")
    return current


def validate_sources(source_map):
    close(source_map["schema_version"], 1)
    sources = source_map["sources"]
    require(isinstance(sources, dict) and len(sources) >= 98, "Source inventory narrowed")
    paths = []
    for key, value in sources.items():
        require(re.fullmatch(r"[a-z0-9_]+", key) is not None, "Invalid source ID")
        require(set(value) == {"path", "sha256", "bytes", "role"}, "Source schema differs")
        path_under(Path("."), value["path"])
        require(SHA.fullmatch(value["sha256"]) is not None, "Invalid source SHA")
        integer(value["bytes"], minimum=1)
        require(value["bytes"] < 5_000_000, "Oversized source entry")
        require(value["role"] in {"projection_input", "receipt_projection_input",
                                 "byte_identical_copy", "preserved_predecessor"}, "Unknown source role")
        paths.append(value["path"])
    require(len(set(paths)) == len(paths), "Duplicate source path")
    return sources


def check_profile(profile):
    require(profile["passed"] is True and profile["issues"] == []
            and profile["global_optimum_proven"] is False, "Unresolved profile consistency")
    tol = number(profile["absolute_tolerance"], positive=True)
    require(tol == 1e-5, "Profile tolerance changed")
    nll = profile["twice_nll"]
    for value in nll.values():
        number(value)
    for a, b in (("free_data", "fixed_data"), ("free_data", "mu0_data"),
                 ("free_asimov", "fixed_asimov"), ("free_asimov", "generating_asimov")):
        require(nll[a] <= nll[b] + tol, "Nested objective ordering fails")


def check_fit(fit):
    require(fit["engine_sha256"] == ENGINE, "Producer engine differs")
    inf = fit["inference"]
    for key, value in {"backend": "jax", "precision": "64b", "fit_tolerance": 1e-9,
                       "method": "asymptotic CLs", "test_stat": "qtilde", "level": .05,
                       "root_solver": "scipy.brentq", "root_rtol": .0001,
                       "root_atol": 1e-10, "root_cls_atol": .0005,
                       "fresh_check_evaluations": 16, "fresh_check_context": FRESH_CONTEXT,
                       "coverage_validated": False}.items():
        close(inf[key], value)
    integer(inf["profile_passes"], minimum=1)
    require(fit["limit_status"] == {"observed": "resolved", "expected": ["resolved"] * 5},
            "A censored root was promoted")
    require(set(fit["mu"]) == set(QUANTILES), "Six-quantile population differs")
    values = [number(fit["mu"][q], positive=True) for q in QUANTILES]
    require(values[1:] == sorted(values[1:]), "Expected bands reordered")
    for key in ("at_poi_cap", "median_at_cap", "at_mu_floor", "band_degenerate"):
        require(fit["flags"][key] is False, "Censored/degenerate result")
    require(fit["flags"]["cls_monotonic"] is True, "Nonmonotonic result")
    roots = fit["roots"]
    require([row["quantile"] for row in roots] == list(QUANTILES), "Root row population differs")
    errors = []
    for q, mu, row in zip(QUANTILES, values, roots):
        close(row["mu"], mu)
        require(row["status"] == "resolved", "Root status differs")
        bracket = row["bracket"]
        require(len(bracket) == 2 and 0 <= number(bracket[0]) <= mu <= number(bracket[1]),
                "Root outside source bracket")
        cls = number(row["scan_cls"], nonnegative=True)
        require(cls <= 1 and abs(cls - .05) <= .0005, "Root misses CLs target")
        close(row["absolute_cls_residual"], abs(cls - .05))
        errors.append(abs(cls - .05))
    close(inf["root_cls_max_error"], max(errors))
    check_profile(fit["profile_consistency"])
    diagnostics = fit["final_evaluations"]
    if diagnostics is None:
        require(fit["evaluation_record_scope"] == "Native result stores root scan and reported count; full final evaluation vectors are not retained here",
                "Native diagnostic availability overclaimed")
    else:
        require(len(diagnostics) == 16, "Official final evaluation population differs")
        for item in diagnostics:
            require(item["status"] == "evaluated" and len(item["cls"]) == 6, "Unresolved fresh evaluation")
            number(item["mu"], nonnegative=True)
            require(all(0 <= number(x) <= 1 for x in item["cls"]), "Invalid fresh CLs")
            check_profile(item["profile_consistency"])
        for index, row in enumerate(roots):
            hits = [x for x in diagnostics if x["mu"] == row["mu"]]
            require(len(hits) == 2, "Missing descending/ascending official check")
            for hit in hits:
                close(hit["cls"][index], row["scan_cls"])
    return values


def derive_streams(record):
    streams = record["streams"]
    N = sum(integer(s["N"], minimum=1) for s in streams)
    for s in streams:
        require(integer(s["selected"]) <= s["N"], "Selected denominator overflow")
        number(s["sigma_pb"], positive=True)
        number(s["K"], positive=True)
        number(s["integration_error_pb"], nonnegative=True)
        number(s["retained_sumw_pb"], nonnegative=True)
        number(s["retained_sumw2_pb2"], nonnegative=True)
    alpha = [s["N"] / N for s in streams]
    f = [s["selected"] / s["N"] for s in streams]
    q = [s["K"] * s["sigma_pb"] for s in streams]
    e = [s["K"] * s["integration_error_pb"] for s in streams]
    Q = math.fsum(a * x for a, x in zip(alpha, q))
    R = math.fsum(a * x * y for a, x, y in zip(alpha, q, f))
    F = R / Q
    sampling = math.fsum((a*x)**2*y*(1-y)/s["N"] for a, x, y, s in zip(alpha, q, f, streams))
    vr_int = math.fsum((a*y*z)**2 for a, y, z in zip(alpha, f, e))
    vf_int = math.fsum((a*(y-F)*z/Q)**2 for a, y, z in zip(alpha, f, e))
    vq_int = math.fsum((a*z)**2 for a, z in zip(alpha, e))
    H = math.fsum(a*a*s["retained_sumw2_pb2"] for a, s in zip(alpha, streams))
    exact_R = math.fsum(a*s["retained_sumw_pb"] for a, s in zip(alpha, streams))
    supported = all(min(s["selected"], s["N"]-s["selected"]) >= 10 for s in streams)
    expected = {
        "original_generated_events": N, "selected_events": sum(s["selected"] for s in streams),
        "sigma_times_K_pb": Q, "selected_rate_pb": R, "rate_weighted_selected_fraction": F,
        "raw_selected_fraction": sum(s["selected"] for s in streams)/N,
        "fixed_N_conditional_rate_variance_pb2": sampling,
        "fixed_N_conditional_fraction_variance": sampling/Q**2,
        "integration_rate_variance_pb2": vr_int, "integration_fraction_variance": vf_int,
        "integration_sigma_variance_pb2": vq_int, "histogram_sumw2_pb2": H,
        "retained_histogram_selected_rate_pb": exact_R,
        "analytic_uniform_weight_histogram_sumw2_pb2": math.fsum((a*x)**2*y/s["N"] for a,x,y,s in zip(alpha,q,f,streams)),
        "histogram_mc_error_pb": math.sqrt(H) if R > 0 else None,
        "histogram_relative_mc_error": math.sqrt(H)/exact_R if exact_R > 0 else None,
        "histogram_5pct_floor_passed": exact_R > 0 and math.sqrt(H)/exact_R <= .05,
        "fixed_N_conditional_mc_error_pb": math.sqrt(sampling) if supported else None,
        "integration_error_pb_at_recorded_selection": math.sqrt(vr_int) if supported else None,
        "precision_status": "supported_plugin_Gaussian_diagnostic" if supported else "precision_unresolved_sparse_or_boundary",
    }
    for key, value in expected.items():
        close(record[key], value)
    return dict(R=R, F=F, Q=Q, VR=sampling, VF=sampling/Q**2,
                IR=vr_int, IF=vf_int, IQ=vq_int, supported=supported)


def check_ratio(stored, a, b, field, variance, integration, selection=True):
    A, B = a[field], b[field]
    ratio = A/B if B else None
    close(stored["ratio"], ratio)
    valid = A > 0 and B > 0 and (not selection or a["supported"] and b["supported"])
    if not valid:
        for key in ("conditional_95pct_interval", "conditional_plus_integration_95pct_interval"):
            close(stored[key], None)
        close(stored["equivalence"], "unresolved")
        return
    V = a.get(variance, 0)/B**2 + A*A*b.get(variance, 0)/B**4
    I = a[integration]/B**2 + A*A*b[integration]/B**4
    close(stored["conditional_standard_error"], math.sqrt(V))
    close(stored["integration_standard_error"], math.sqrt(I))
    intervals = []
    for key, var in (("conditional_95pct_interval", V), ("conditional_plus_integration_95pct_interval", V+I)):
        bounds = [ratio-1.959963984540054*math.sqrt(var), ratio+1.959963984540054*math.sqrt(var)]
        require(type(stored[key]) is list and len(stored[key]) == 2, "Interval missing")
        for actual, expected in zip(stored[key], bounds):
            close(actual, expected)
        intervals.append(bounds)
    expected = "supported_within_prespecified_interval" if all(.9 <= lo <= hi <= 1.1 for lo, hi in intervals) else "not_established"
    close(stored["equivalence"], expected)


def csv_bytes(rows):
    require(bool(rows), "Empty CSV population")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode()


def native_csv(data):
    rows = []
    for fit in data["native"]:
        row = {"sample": fit["id"], "original_events": fit["original_events"]}
        row.update({q+"_mu": fit["mu"][q] for q in QUANTILES})
        row.update({q+"_sigma95_fb": fit["sigma95_fb"][q] for q in QUANTILES})
        row.update(observed_residual_fraction=fit["observed_residual_fraction"],
                   median_expected_residual_fraction=fit["median_expected_residual_fraction"])
        rows.append(row)
    return csv_bytes(rows)


def official_csv(data):
    keys = ("quantile", "full_mu", "signal_mc_only_mu", "signal_nominal_only_mu",
            "signal_mc_only_over_full", "signal_nominal_only_over_full",
            "signal_nominal_only_over_signal_mc_only", "signal_mc_only_change_percent",
            "signal_nominal_only_change_percent")
    return csv_bytes([{key: row[key] for key in keys} for row in data["official"]["rows"]])


def lower_csv(data):
    rows = []
    for row in data["lower"]["rows"]:
        n, l, q = row["nominal_60k"], row["lower_20k"], row["lower_over_nominal"]["selected_rate"]
        rows.append({"category": row["category"], "nominal_N": n["original_generated_events"],
            "nominal_selected": n["selected_events"], "nominal_sigmaK_pb": n["sigma_times_K_pb"],
            "nominal_raw_fraction": n["raw_selected_fraction"], "nominal_weighted_fraction": n["rate_weighted_selected_fraction"],
            "nominal_rate_pb": n["selected_rate_pb"], "lower_N": l["original_generated_events"],
            "lower_selected": l["selected_events"], "lower_sigmaK_pb": l["sigma_times_K_pb"],
            "lower_fraction": l["rate_weighted_selected_fraction"], "lower_rate_pb": l["selected_rate_pb"],
            "rate_ratio": q["ratio"], "conditional_95_low": (q["conditional_95pct_interval"] or [None,None])[0],
            "conditional_95_high": (q["conditional_95pct_interval"] or [None,None])[1],
            "with_integration_95_low": (q["conditional_plus_integration_95pct_interval"] or [None,None])[0],
            "with_integration_95_high": (q["conditional_plus_integration_95pct_interval"] or [None,None])[1],
            "equivalence": q["equivalence"]})
    return csv_bytes(rows)


def validate_data(data, source_map):
    finite_tree(data)
    sources = validate_sources(source_map)
    require(data["schema_version"] == 1 and type(data["schema_version"]) is int, "Unsupported schema")
    catalog = data["catalog"]
    expected_catalog = {"point_id": "m150_m140", "m_parent_GeV": 150, "m_lsp_GeV": 140,
        "delta_m_GeV": 10, "unique_mass_points": 1, "independent_selected_event_streams": 3,
        "original_selected_stream_exposure": 80000, "native_fits": 4, "official_fits": 3,
        "pool_additional_events": 0, "physics_certified": False, "coverage_validated": False,
        "global_contour_closed": False, "native_official_mu_directly_comparable": False}
    require(set(catalog) == set(expected_catalog), "Catalog schema differs")
    for key, value in expected_catalog.items():
        close(catalog[key], value)
    ref = data["reference"]
    require(ref["point_id"] == "m150_m140" and ref["m_parent_GeV"] == 150 and ref["m_lsp_GeV"] == 140
            and ref["delta_m_GeV"] == 10, "Reference identity differs")
    close(ref["observed_sigma95_fb"], 46.633)
    close(ref["median_expected_sigma95_fb"], 56.526)
    require(ref["expected_bands"] is None, "Invented reference bands")
    norm = data["normalization"]
    close(norm["inclusive_LO_pb"], .1350625)
    close(norm["inclusive_integration_error_pb"], .0003703)
    close(norm["K"], 1.18)
    require(norm["luminosity_applied"] is False, "Luminosity applied twice")
    factor = 1000 * norm["K"] * norm["inclusive_LO_pb"]
    close(norm["nominal_inclusive_fb"], factor)
    require([x["id"] for x in data["native"]] == list(NATIVE_IDS), "Native fit population differs")
    aliases = ("nominal_20k","nominal_40k","nominal_pool_60k","leading_parton_20GeV_20k")
    for fit, exposure, alias in zip(data["native"], (20000,40000,60000,20000), aliases):
        require(fit["source_sample_id"] == alias, "Source/native alias differs")
        close(fit["original_events"], exposure)
        values = check_fit(fit)
        require(fit["final_evaluations"] is None, "Native saved-vector scope differs")
        for q, value in zip(QUANTILES, values):
            close(fit["sigma95_fb"][q], value*factor)
        close(fit["observed_residual_fraction"], fit["sigma95_fb"]["observed"]/ref["observed_sigma95_fb"]-1)
        close(fit["median_expected_residual_fraction"], fit["sigma95_fb"]["expected_median"]/ref["median_expected_sigma95_fb"]-1)
        require(fit["result_source"] == fit["id"]+"_result", "Native result source join differs")
    official = data["official"]
    require([x["id"] for x in official["arms"]] == list(OFFICIAL_IDS), "Official arm population differs")
    require(official["model_channels"] == 38 and official["supplied_signal_samples"] == 27,
            "Official likelihood population differs")
    require(official["native_uncertainty_transfer"] is False and official["sigma_conversion"] is False,
            "Official/native scope conflated")
    for fit, count in zip(official["arms"], (196,191,191)):
        check_fit(fit)
        close(fit["n_parameters"], count)
        require(fit["final_evaluations"] is not None, "Official recorded evaluations missing")
        compiled = official["compiled"][fit["id"]]
        require(compiled["n_parameters"] == count and compiled["channels"] == data["model_channels"],
                "Compiled official identity differs")
        for key in ("initial", "bounds", "fixed"):
            require(len(compiled[key]) == count, "Compiled parameter denominator differs")
        for initial, bounds, fixed in zip(compiled["initial"], compiled["bounds"], compiled["fixed"]):
            require(type(fixed) is bool and len(bounds) == 2
                    and number(bounds[0]) <= number(initial) <= number(bounds[1]), "Compiled parameter bounds differ")
        require(compiled["nominal_expected_main"] == official["compiled"]["full"]["nominal_expected_main"]
                and compiled["observed_main"] == official["compiled"]["full"]["observed_main"],
                "Official same-nominal intervention differs")
        require(compiled["patch_sha256"] == sources["official_input_"+fit["id"]]["sha256"],
                "Official signal input binding differs")
    require(official["modifier_settings"] == {"normsys":{"interpcode":"code4"},"histosys":{"interpcode":"code4p"}},
            "Official modifier interpolation differs")
    require(official["model_input_sources"] == {name:"official_input_"+name for name in ("background",*OFFICIAL_IDS)},
            "Official model source mapping differs")
    require([x["quantile"] for x in official["rows"]] == list(QUANTILES), "Official ratio population differs")
    for q, row in zip(QUANTILES, official["rows"]):
        a,b,c = [x["mu"][q] for x in official["arms"]]
        expected = {"full_mu":a, "signal_mc_only_mu":b, "signal_nominal_only_mu":c,
                    "signal_mc_only_over_full":b/a, "signal_nominal_only_over_full":c/a,
                    "signal_nominal_only_over_signal_mc_only":c/b,
                    "signal_mc_only_change_percent":100*(b/a-1),
                    "signal_nominal_only_change_percent":100*(c/a-1)}
        for key, value in expected.items():
            close(row[key], value)
    lower = data["lower"]
    require(lower["physics_certified"] is False and lower["new_generated_events"] == 0, "Comparison scope differs")
    policy = lower["policy"]
    require(policy["confidence"] == .95 and policy["normal_quantile"] == 1.959963984540054
            and policy["equivalence_interval"] == [.9,1.1]
            and type(policy["minimum_selected_and_unselected_per_stream"]) is int
            and policy["minimum_selected_and_unselected_per_stream"] == 10
            and policy["existing_histogram_relative_mc_floor"] == .05, "Prospective thresholds differ")
    require(lower["recipe"]["ptj1min_GeV"] == [50.,50.,20.]
            and lower["recipe"]["original_exposure"] == [20000,40000,20000], "Recipe/exposure differs")
    require([s["mg_seed"] for s in lower["recipe"]["seeds"]] == [1731,1733,1737]
            and [s["shower_seed"] for s in lower["recipe"]["seeds"]] == [74107,74111,74117]
            and [s["detector_seed"] for s in lower["recipe"]["seeds"]] == [74107,74111,74117], "Independent stream identities differ")
    rows = lower["rows"]
    require(len(rows) == 40 and len({r["category"] for r in rows}) == 40, "40-category denominator differs")
    channels = data["model_channels"]
    require(len(channels) == 38 and len(set(channels)) == 38 and channels == sorted(channels), "Model channel inventory differs")
    require([r["category"] for r in rows] == channels+["SR_high","SR_low"], "Comparison channel order differs")
    by_name = {r["category"]:r for r in rows}
    crs = [c for c in channels if c.startswith("CR")]
    require(len(crs) == 6 and crs == lower["six_individual_CR_channels"]
            and crs == official["supplied_signal_CR_channels"], "Six CR identities differ")
    dispositions = {}
    for row in rows:
        members = row["member_channels"]
        expected_members = [row["category"]] if row["category"] in channels else [c for c in channels if c.startswith("SR") and ("hghmet" if row["category"] == "SR_high" else "lowmet") in c]
        require(members == expected_members and bool(members), "Aggregate membership differs")
        streams = row["nominal_60k"]["streams"]+row["lower_20k"]["streams"]
        require(len(streams) == 3, "Stream denominator differs")
        for i, s in enumerate(streams):
            close(s["N"], (20000,40000,20000)[i])
            for key in ("sigma_pb", "K", "integration_error_pb"):
                close(s[key], norm["generation"][i][key])
            if row["category"] not in channels:
                parts = [(by_name[c]["nominal_60k"]["streams"]+by_name[c]["lower_20k"]["streams"])[i] for c in members]
                close(s["selected"], sum(t["selected"] for t in parts))
                for key in ("retained_sumw_pb", "retained_sumw2_pb2"):
                    close(s[key], math.fsum(t[key] for t in parts))
        nominal, control = derive_streams(row["nominal_60k"]), derive_streams(row["lower_20k"])
        for key, field, variance, integration, selection in (("selected_rate","R","VR","IR",True),
            ("rate_weighted_fraction","F","VF","IF",True), ("sigma_times_K","Q","zero","IQ",False)):
            check_ratio(row["lower_over_nominal"][key], control, nominal, field, variance, integration, selection)
        label = row["lower_over_nominal"]["selected_rate"]["equivalence"]
        dispositions[label] = dispositions.get(label,0)+1
    require(dispositions == {"not_established":13,"unresolved":27}, "Dated outcome population differs")
    pool = data["lineage"]["pool"]
    require(pool["parents"] == ["nominal_20k","nominal_40k"] and pool["parent_exposures"] == [20000,40000]
            and pool["alpha"] == [1/3,2/3] and pool["new_events"] == 0
            and pool["independent_of_parents"] is False and pool["luminosity_applied"] is False,
            "Pool lineage/exposure differs")
    close(pool["K"], norm["K"])
    for parent, hashed in zip(pool["parents"], pool["parent_plan_sha256"]):
        require(hashed == sources[parent+"_plan"]["sha256"], "Pool source parent changed")
    require([run["id"] for run in data["lineage"]["runs"]] == list(NATIVE_IDS), "Run lineage population differs")
    for run in data["lineage"]["runs"]:
        required = POOL_STAGES if run["id"] == "pooled_60k" else NATIVE_STAGES
        require(set(run["stages"]) == set(required), "Incomplete native/derivative stage inventory")
        for stage, receipt in run["stages"].items():
            require(receipt["status"] == "succeeded" and type(receipt["exit_code"]) is int
                    and receipt["exit_code"] == 0, "Failed receipt promoted")
            require(receipt["record_source"] == run["id"]+"_receipt_"+stage, "Receipt source differs")
            for key in ("receipt_sha256","fingerprint","input_snapshot_sha256","output_snapshot_sha256"):
                require(SHA.fullmatch(receipt[key]) is not None, "Malformed receipt commitment")
            require(receipt["stage"] == stage and receipt["record_source"] in sources, "Receipt stage/source differs")
            for parent, hashed in receipt["parents"].items():
                if parent in run["stages"]:
                    require(hashed == run["stages"][parent]["receipt_sha256"], "Receipt parent lineage differs")
    failures = data["failures"]
    require([f["id"] for f in failures] == ["pooled_first_attempt","lower_reader_v1","lower_reader_v2"],
            "Original failures removed")
    require(all(f["status"] == "failed" and f["accepted_result"] is False for f in failures), "Failed attempt promoted")
    require(failures[0]["exit_code"] == 124 and failures[0]["wall_cap_seconds"] == 3600
            and failures[0]["elapsed_seconds"] is None, "Timeout evidence altered")
    require([f["source_status"] for f in failures[1:]] == ["failed_diagnostic"]*2,
            "Original diagnostic status differs")
    require(data["figure_data"]["all_rows"] == rows and data["figure_data"]["policy"] == policy
            and data["figure_data"]["plotted_categories"] == ["SR_high","SR_low"]+crs, "Figure/table operands differ")
    return {"native_roots":24, "official_roots":18, "lower_rows":40,
            "lower_ratio_checks":120, "selected_rate_dispositions":dispositions,
            "raw_event_replay":False, "new_fits":0, "physics_certified":False}


def verify_bundle(directory=HERE):
    directory = Path(directory)
    manifest = read_json(directory/"manifest.json")
    require(manifest["schema_version"] == 1 and manifest["scope"] == "offline arithmetic and shipped-byte integrity", "Manifest scope differs")
    actual = set()
    for path in directory.rglob("*"):
        require(not path.is_symlink(), "Symlink in bundle")
        if path.is_file():
            name = path.relative_to(directory).as_posix()
            require("__pycache__" not in path.parts and path.suffix != ".pyc", "Unmanifested bytecode")
            if name != "manifest.json":
                actual.add(name)
    require(actual == set(manifest["files"]), "Manifest inventory differs")
    required_files = {"README.md", "curate.py", "verify.py", "source-map.json", "data/evidence.json",
                      "tables/native-limits.csv", "tables/official-limits.csv", "tables/lower-rates.csv"}
    required_files |= {f"figures/lower-{kind}.{extension}" for kind in ("ratios","decomposition")
                       for extension in ("png","pdf")}
    require(actual in (required_files, required_files | {"verification.json"}), "Dated bundle file population differs")
    for name, row in manifest["files"].items():
        content = path_under(directory, name).read_bytes()
        require(len(content) < 5_000_000 and len(content) == integer(row["bytes"], minimum=1)
                and digest(content) == row["sha256"], "Artifact bytes differ")
        if name.endswith((".json",".csv",".md",".py")):
            require(not re.search(rb"/(?:Users|home|private/tmp)/|[A-Za-z]:\\\\", content), "Private host path in bundle")
    sources = read_json(directory/"source-map.json")
    data = read_json(directory/"data/evidence.json")
    result = validate_data(data, sources)
    require((directory/"tables/native-limits.csv").read_bytes() == native_csv(data), "Native CSV differs")
    require((directory/"tables/official-limits.csv").read_bytes() == official_csv(data), "Official CSV differs")
    require((directory/"tables/lower-rates.csv").read_bytes() == lower_csv(data), "Lower CSV differs")
    for kind in ("ratios","decomposition"):
        for extension in ("png","pdf"):
            name = f"figures/lower-{kind}.{extension}"
            require(manifest["files"][name]["sha256"] == sources["sources"][f"figure_{kind}_{extension}"]["sha256"],
                    "Source figure bytes differ")
    result.update(status="verified", source_artifacts=len(sources["sources"]), shipped_files=len(actual)+1)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, help="Also verify selected originals and deterministic projections; no raw replay")
    args = parser.parse_args()
    result = verify_bundle()
    if args.source_root:
        import curate
        curate.check(args.source_root, HERE)
        result["selected_original_sources_and_projection"] = "verified"
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
