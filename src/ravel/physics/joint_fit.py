"""Bounded source-conditioned published/finite-MC profile study.

The MC experiment is supplied explicitly. It is never inferred from source
sumw2. Every signal-response coordinate is conditioned at the source initial
value; only declared signal-absent background normfactors may vary. This
adapter is separate from a full source-response nuisance profiling backend.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time

from ravel.physics import finite_mc_model as fm
from ravel.physics.joint_likelihood import JointPublishedFiniteMC, compact, response_identity
from ravel.physics.joint_profile import JointProfiler, WorkBudget
from ravel.physics.mc_auxiliary import MCAuxiliaryBlock, _read, MAX_TOTAL_BYTES
from ravel.physics.published_background import BackgroundAuxBlock, inspect_workspace
from ravel.physics.quantities import _keys, _number, _text
from ravel.workflow.state_io import atomic_json


def validate(task):
    fm.validate(task)


def _pin(pin, base, captured):
    _keys(pin, ("path", "sha256"), label="joined study source pin")
    path = fm._regular(pin["path"], base)
    raw = _read(path)
    if hashlib.sha256(raw).hexdigest() != pin["sha256"]:
        raise ValueError("joined study input hash differs")
    if str(path) in captured and captured[str(path)] != raw:
        raise ValueError("joined study source changed during capture")
    captured[str(path)] = raw
    if sum(map(len, captured.values())) > MAX_TOTAL_BYTES:
        raise ValueError("joined study aggregate inputs exceed 32 MiB")
    return path, fm._load_bytes(raw)


def _capture(task, base):
    validate(task)
    path = fm._regular(task["input"], base)
    raw = _read(path)
    doc = fm._load_bytes(raw)
    captured = {str(path): raw}
    _keys(doc, ("schema_version", "model_id", "background_source", "measurement", "assumptions",
                "limits", "mu_domain", "cases"), label="joined study")
    if type(doc["schema_version"]) is not int or doc["schema_version"] != 1:
        raise ValueError("unsupported joined study schema")
    for key in ("model_id", "measurement"):
        _text(doc[key], key)
    if not isinstance(doc["assumptions"], list) or len(doc["assumptions"]) < 2:
        raise ValueError("explicit source conditioning and MC sampling assumptions required")
    for value in doc["assumptions"]:
        _text(value, "assumption")
    _keys(doc["limits"], ("execution_seconds", "fit_budget"), label="joined study limits")
    seconds = doc["limits"]["execution_seconds"]
    if type(seconds) is not int or not 1 <= seconds <= 300:
        raise ValueError("joined study needs at most 300 seconds")
    WorkBudget(doc["limits"]["fit_budget"])
    _keys(doc["mu_domain"], ("initial", "upper"), label="joined study strength search")
    if not 0 < _number(doc["mu_domain"]["initial"], "initial mu") < _number(doc["mu_domain"]["upper"], "mu cap") <= 1000:
        raise ValueError("positive initial strength and explicit numerical upper required")
    if not isinstance(doc["cases"], list) or not 1 <= len(doc["cases"]) <= 2:
        raise ValueError("one or two explicit source points required")
    background_path, background = _pin(doc["background_source"], path.parent, captured)
    points, bound = [], []
    for case in doc["cases"]:
        _keys(case, ("point_id", "workspace", "signal_samples", "free_source", "fixed_source", "profile_points", "mc_models"), label="joined source case")
        _text(case["point_id"], "point identity")
        points.append(case["point_id"])
        fm._ids(case["free_source"], "free source coordinates")
        if len(case["free_source"]) > 2 or not isinstance(case["fixed_source"], dict):
            raise ValueError("at most two free background coordinates and explicit conditional map required")
        for key, value in case["fixed_source"].items():
            _text(key, "conditional coordinate")
            _number(value, "conditional value")
        strengths = case["profile_points"]
        if not isinstance(strengths, list) or not 1 <= len(strengths) <= 3:
            raise ValueError("one to three fixed strengths required")
        strengths = [_number(mu, "fixed strength") for mu in strengths]
        if len(set(strengths)) != len(strengths) or any(not 0 <= mu <= doc["mu_domain"]["upper"] for mu in strengths):
            raise ValueError("fixed strength grid must be unique and within numerical search")
        workspace_path, workspace = _pin(case["workspace"], path.parent, captured)
        census = inspect_workspace(workspace, case["signal_samples"])
        if compact(census["background_projection"]) != compact(background):
            raise ValueError("exact background-only source differs from signal-stripped workspace")
        if not isinstance(case["mc_models"], list) or not 1 <= len(case["mc_models"]) <= 2:
            raise ValueError("one or two explicit MC exposures required")
        models = []
        for item in case["mc_models"]:
            _keys(item, ("id", "input"), label="MC study case")
            _text(item["id"], "MC case identity")
            model_path, _ = _pin(item["input"], path.parent, captured)
            mc = MCAuxiliaryBlock({"input": str(model_path)}, path.parent)
            for source in mc.contract()["inputs"]:
                _pin(source, path.parent, captured)
            if mc.document()["mc_design"]["kind"] != "fixed_n_categories":
                raise ValueError("conditioned exposure study requires an explicit complete fixed-N law")
            models.append((item, mc))
        if len({item["id"] for item, _ in models}) != len(models):
            raise ValueError("duplicate MC case identity")
        bound.append((case, workspace_path, workspace, models))
    if len(set(points)) != len(points):
        raise ValueError("duplicate source point identity")
    for name, value in captured.items():
        if _read(fm._regular(name, path.parent)) != value:
            raise ValueError("joined study input changed during capture")
    return path, doc, captured, background, bound


def inputs(task, base, *, _session=None):
    return [Path(path) for path in _capture(task, base)[2]]


def resource_bounds(task, base):
    _, doc, _, _, _ = _capture(task, base)
    fits = sum((1 + len(c["mc_models"])) * (1 + len(c["profile_points"])) for c in doc["cases"])
    budget = doc["limits"]["fit_budget"]
    return {"execution_seconds": doc["limits"]["execution_seconds"], "processes": 1,
            "threads": 1, "maximum_fit_calls": fits, "maximum_optimizer_attempts": 3 * fits,
            **{"maximum_" + key: fits * budget[key] for key in
               ("objective_calls", "gradient_calls", "feasibility_lp_calls", "stationarity_lp_calls")},
            "maximum_iterations_per_attempt": budget["maxiter"], "generated_events": 0,
            "calibration_trials": 0, "maximum_free_coordinates": 8,
            "enforcement": "Charged per-fit work and wall hook plus external scientific-stage supervisor; environment thread limits do not certify a native active-thread count."}


def execution_seconds(task, base):
    return resource_bounds(task, base)["execution_seconds"]


def conditioned_source_response(latent, nominal, source_point, configuration, source_data):
    """Source nominal response only at the explicitly conditioned coordinates."""
    if any(source_point.get(name) != value for name, value in configuration["fixed_source"].items()):
        raise ValueError("conditioned source response cannot transport changed nuisance coordinates")
    return nominal


def construct(doc, case, workspace_path, workspace, background_source, mc):
    """Compile a source-conditioned model without fitting or generating data."""
    background = BackgroundAuxBlock(workspace, case["signal_samples"], measurement=doc["measurement"],
        policy="rebuild_background_mc_from_source", model_id=doc["model_id"] + ":" + case["point_id"], background_source=background_source)
    contract = background.contract()
    domains = contract["active_parameter_domains"]
    if set(case["free_source"]) & set(case["fixed_source"]) or set(case["free_source"]) | set(case["fixed_source"]) != set(domains):
        raise ValueError("free and conditioned source maps must partition every retained source coordinate")
    census = inspect_workspace(workspace, case["signal_samples"])
    for name in case["free_source"]:
        rows = census["occurrences"].get(name, [])
        if not rows or any(r["signal"] or r["type"] != "normfactor" for r in rows) or domains[name]["fixed"]:
            raise ValueError("free source coordinate must be an unfixed signal-absent background normfactor")
    initial = background.initial_point()
    if any(value != initial[name] for name, value in case["fixed_source"].items()):
        raise ValueError("conditioned response requires exact published source initial values")
    channels = contract["channel_order"]
    if set(channels) != set(mc.bin_ids) or any(stop - start != 1 for start, stop in contract["channel_slices"].values()):
        raise ValueError("this source-conditioned adapter requires one MC target per complete source channel")
    nominal = {}
    poi = next(m["config"]["poi"] for m in workspace["measurements"] if m["name"] == doc["measurement"])
    response_names = set()
    for channel in workspace["channels"]:
        samples = [s for s in channel["samples"] if s["name"] in case["signal_samples"][channel["name"]]]
        nominal[channel["name"]] = math.fsum(s["data"][0] for s in samples)
        response_names.update(m["name"] for s in samples for m in s["modifiers"] if m["name"] != poi and m["type"] not in {"staterror", "shapesys"})
        for sample in samples:
            for modifier in sample["modifiers"]:
                if modifier["name"] == poi or modifier["type"] in {"staterror", "shapesys"}:
                    continue
                if modifier["type"] not in {"normsys", "histosys", "normfactor", "lumi", "shapefactor"}:
                    raise ValueError("unsupported source nominal-response modifier")
                value = 0. if modifier["type"] in {"normsys", "histosys"} else 1.
                coords = [name for name in domains if name == modifier["name"] or name.startswith(modifier["name"] + "[")]
                if not coords or any(initial[name] != value for name in coords):
                    raise ValueError("source response initial point differs from literal nominal template")
    dependencies = [name for name in domains if any(name == r or name.startswith(r + "[") for r in response_names)]
    if not set(dependencies) <= set(case["fixed_source"]):
        raise ValueError("every signal response coordinate must be explicitly conditioned")
    latent = {c["id"]: c["initial"] for c in mc.document()["classes"]}
    mc_nominal = mc.nominal(latent)["signal_expectation"]
    if any(not math.isclose(v, nominal[name], rel_tol=1e-12, abs_tol=1e-12) for name, v in zip(mc.bin_ids, mc_nominal)):
        raise ValueError("controlled MC initial signal differs from exact source nominal yields")
    configuration = {"fixed_source": case["fixed_source"]}
    source = Path(__file__).resolve()
    response_contract = {"background_contract_sha256": background.contract_sha256,
        "source_workspace_sha256": contract["source_workspace_sha256"], "coordinate_dependencies": dependencies,
        "implementation_pin": {"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
        "callable_identity": response_identity(conditioned_source_response), "configuration": configuration,
        "configuration_sha256": hashlib.sha256(compact(configuration)).hexdigest(),
        "source_data_pins": [{"id": "workspace", "path": str(workspace_path), "sha256": hashlib.sha256(workspace_path.read_bytes()).hexdigest(), "encoding": "json"}],
        "source_workspace_data_id": "workspace", "environment_requirements": "reviewed_frozen_transitive_globals_and_dependencies",
        "independence": "supplied_source_and_new_MC_auxiliaries_independent",
        "provenance": "Exact source nominal signal at explicitly conditioned source initial coordinates. Supplied controlled MC law has a new identity; no native generator or detector claim."}
    joint = JointPublishedFiniteMC(background, mc, source_workspace=workspace, signal_samples=case["signal_samples"],
        source_bin_map=[{"channel": name, "bin": 0, "mc_bin_id": name} for name in channels],
        response=conditioned_source_response, response_contract=response_contract,
        model_id=doc["model_id"] + ":" + case["point_id"] + ":" + mc.document()["model_id"],
        main_disposition="replace_conditional_control_with_bound_published_source")
    semantics = {name: {"lower": "physical" if name in case["free_source"] and row["bounds"][0] == 0 else "numerical", "upper": "numerical"} for name, row in domains.items()}
    profiler = JointProfiler(joint, background, mc, mu_domain=doc["mu_domain"], source_bound_semantics=semantics, rate_caps={})
    return joint, background, mc, profiler, latent


def run(task, base, output_dir):
    started = time.monotonic()
    output = Path(output_dir)
    if output.is_symlink() or output.exists() and any(output.iterdir()):
        raise ValueError("fresh joined-study output directory required")
    output.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": 1, "status": "failed", "physics_validated": False, "models": [],
              "fit_calls": 0, "generated_events": 0, "calibration_trials": 0,
              "scope": "Source-conditioned all-bin numerical finite-MC sensitivity; no full-source profile, native MC qualification, calibration, CLs or exclusion."}
    def save():
        report["elapsed_seconds"] = time.monotonic() - started
        atomic_json(output / "joint_fit.json", report)
    save()
    try:
        path, doc, captured, background, cases = _capture(task, base)
        report["input_sha256"] = hashlib.sha256(captured[str(path)]).hexdigest()
        report["resources"] = resource_bounds(task, base)
        report["assumptions"] = doc["assumptions"]
        deadline = started + doc["limits"]["execution_seconds"]
        for case, workspace_path, workspace, models in cases:
            baseline_done = False
            for item, mc in models:
                joint, bg, _, profiler, latent = construct(doc, case, workspace_path, workspace, background, mc)
                modes = ["fixed_latent", "finite_mc"] if not baseline_done else ["finite_mc"]
                baseline_done = True
                for mode in modes:
                    row = {"point_id": case["point_id"], "mc_id": item["id"], "mode": mode,
                           "joint_contract": joint.contract(), "fits": [], "verified": False,
                           "initial_latent": latent,
                           "MC_logpdf_at_initial": mc.auxiliary_logpdf(latent),
                           "normalization_note": "Add MC_logpdf_at_initial to each NLL to remove this model's MC factor constant. This permits exposure comparisons for the same controlled marks/probabilities; recentered likelihood-ratio curves need not be ordered."}
                    report["models"].append(row)
                    save()
                    for mu in [None, *case["profile_points"]]:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("joined study wall hook exhausted; remaining fits unattempted")
                        report["fit_calls"] += 1
                        fit_row = {"fixed_mu": mu, "status": "running", "result": None,
                            "twice_delta_nll": None, "MC_constant_removed_nll": None}
                        row["fits"].append(fit_row)
                        save()
                        try:
                            result = profiler.fit(fixed_mu=mu, budget=doc["limits"]["fit_budget"],
                                fixed_source=case["fixed_source"], fixed_latent=latent if mode == "fixed_latent" else None,
                                wall_hook=lambda: time.monotonic() >= deadline)
                        except Exception as error:
                            fit_row.update(status="failed", error={"type": type(error).__name__, "message": str(error)})
                            save()
                            raise
                        fit_row.update(status="returned", result=result,
                            MC_constant_removed_nll=result["nll"] + row["MC_logpdf_at_initial"] if result.get("nll") is not None else None)
                        save()
                    best = row["fits"][0]["result"]
                    for result_row in row["fits"][1:]:
                        result = result_row["result"]
                        if best["verified"] and result["verified"]:
                            delta = 2 * (result["nll"] - best["nll"])
                            if delta >= -1e-5:
                                result_row["twice_delta_nll"] = max(0., delta)
                            else:
                                result["verified"] = False
                                result["failure"] = "conditional result improves free fit"
                    row["verified"] = bool(best["verified"] and all(r["result"]["verified"] and r["twice_delta_nll"] is not None for r in row["fits"][1:]))
                    save()
        for name, raw in captured.items():
            if _read(fm._regular(name, path.parent)) != raw:
                raise ValueError("joined study source changed during execution")
        report["input_custody_after_passed"] = True
        report["all_fits_verified"] = all(row["verified"] for row in report["models"])
        report["diagnostic_delivery_complete"] = report["fit_calls"] == report["resources"]["maximum_fit_calls"]
        report["status"] = "passed" if report["all_fits_verified"] and report["diagnostic_delivery_complete"] and time.monotonic() < deadline else "failed"
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    save()
    return report
