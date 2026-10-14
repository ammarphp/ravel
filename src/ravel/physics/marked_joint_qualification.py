"""Prospective fixed-vector joined-law qualification; no dispatch on import.

Use only through a separately admitted ordinary scientific worker. This
adapter performs zero fits, draws, LPs or physical event operations.
"""
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import time

from ravel.physics import finite_mc_model as fm
from ravel.physics import marked_response
from ravel.physics.mc_auxiliary import MCAuxiliaryBlock, compact, _read
from ravel.physics.published_background import BackgroundAuxBlock
from ravel.physics.joint_analytic import AnalyticPublishedJoint
from ravel.physics.joint_likelihood import JointPublishedFiniteMC, response_identity
from ravel.physics.marked_response_provider import MarkedResponseProvider
from ravel.workflow.state_io import atomic_json


def validate(task):
    if type(task) is not dict or set(task) != {"input"} or type(task["input"]) is not str:
        raise ValueError("one exact source-bound qualification input required")
    return deepcopy(task)


def _capture(task, base_dir):
    validate(task); path = fm._regular(task["input"], base_dir); raw = _read(path)
    document = json.loads(raw); captured = {str(path): raw}
    if type(document) is not dict or set(document) != {"schema_version", "cases", "scope"} or type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("closed marked qualification schema1 required")
    if document["scope"] != "artificial_complete_marked_joint_law_and_derivatives" or len(document["cases"]) != 2:
        raise ValueError("exact two-case artificial qualification required")
    ids = []
    for case in document["cases"]:
        if set(case) != {"id", "workspace", "MC", "response", "signal_samples", "source_bin_map", "configuration", "points", "derivative_points", "expected_free_coordinates"}:
            raise ValueError("complete case declaration required")
        ids.append(case["id"])
        for key in ("workspace", "MC", "response"):
            pin = case[key]
            if set(pin) != {"path", "sha256"}: raise ValueError("exact case file pin required")
            child = fm._regular(pin["path"], path.parent); data = _read(child)
            if hashlib.sha256(data).hexdigest() != pin["sha256"]: raise ValueError("changed qualification input")
            captured[str(child)] = data
        mc_path = fm._regular(case["MC"]["path"], path.parent)
        mc_document = json.loads(captured[str(mc_path)])
        for pin in mc_document["sources"]:
            child = fm._regular(pin["path"], mc_path.parent); data = _read(child)
            if hashlib.sha256(data).hexdigest() != pin["sha256"]: raise ValueError("changed MC source input")
            captured[str(child)] = data
        if len(case["points"]) != 5 or case["derivative_points"] != [1, 2] or case["expected_free_coordinates"] not in (6, 13):
            raise ValueError("exact five anchors/two derivative vectors/complete dimension required")
    if len(set(ids)) != 2 or sorted(c["expected_free_coordinates"] for c in document["cases"]) != [6, 13]:
        raise ValueError("complete two-case dimension census required")
    if sum(map(len, captured.values())) > 4*1024**2: raise ValueError("4 MiB qualification input ceiling")
    return document, path.parent, captured


def inputs(task, base_dir):
    return [Path(p) for p in _capture(task, base_dir)[2]]


def resource_bounds(task, base_dir):
    _capture(task, base_dir)
    return {"processes": 2, "mathematical_workers": 1, "native_children": 0, "model_compilations": 2,
            "density_wrapper_calls": 172, "constraint_calls": 10, "analytic_calls": 10, "scalar_calls": 162, "fits": 0, "LPs": 0,
            "generated_events": 0, "mathematical_seconds": 60, "recommended_outer_seconds": 180,
            "capture_bytes": 4*1024**2, "journal_bytes": 8*1024**2, "result_bytes": 8*1024**2}


def execution_seconds(task, base_dir):
    resource_bounds(task, base_dir)
    return 60


def _axes(background, mc):
    source = background.contract()
    return (["mu"]+["source:"+n for n in source["active_parameter_names"] if not source["active_parameter_domains"][n]["fixed"]]
            +["MC:"+n for n in mc.class_ids[:-1]])


def _shift(point, name, delta, last):
    point = deepcopy(point)
    if name == "mu": point["mu"] += delta
    elif name.startswith("source:"): point["source"][name[7:]] += delta
    else:
        point["latent"][name[3:]] += delta; point["latent"][last] -= delta
    return point


def _tangent_columns(result, axes, last):
    order = result["coordinate_order"]; gradient = result["gradient"]
    jacobian = result["distribution_mean_jacobian"]
    last_index = order.index("MC:"+last)
    return [gradient[order.index(a)]-(gradient[last_index] if a.startswith("MC:") else 0) for a in axes], [
        [row[order.index(a)]-(row[last_index] if a.startswith("MC:") else 0) for a in axes] for row in jacobian]


def _close(left, right, atol=1e-6, rtol=1e-7):
    return abs(left-right) <= atol+rtol*max(abs(left), abs(right))


def _complete_scalar_means(result, point, source, mc_document, class_ids):
    """Derive declared auxiliary means after the caller saves the raw NLL."""
    result = deepcopy(result)
    aux = [point["source"][r["coordinate"]]*(r["factor"] if r["pdf"] == "poisson" else 1.)
           for r in source["retained_auxiliaries"]]
    population = [mc_document["mc_design"]["total_groups"]*point["latent"][n] for n in class_ids]
    result["complete_distribution_means"] = result["source"]["main_means"]+aux+population
    result["physical_constraints"] = result["source"]["background_means"]+result["source"]["signal_means"]
    return result


def run(task, base_dir, output_dir):
    """Actual numerical operation: only call after independent source admission."""
    started = time.monotonic(); out = Path(output_dir)
    # Ordinary worker creates its output root. Existing content is never reused.
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()): raise ValueError("fresh qualification output root required")
    document, base, captured = _capture(task, base_dir)
    report = {"schema_version": 1, "scope": document["scope"], "status": "running", "cases": [],
              "counts": {"model_compilations": 0, "analytic_calls": 0, "scalar_calls": 0, "constraint_calls": 0},
              "physics_validated": False, "fit_qualified": False, "coverage_qualified": False}
    journal = out/"marked-progress.jsonl"; sequence = 0; previous = None; written = 0

    def save():
        raw = compact(report)
        if len(raw) > 8*1024**2: raise ValueError("marked result ceiling")
        atomic_json(out/"marked-qualification.json", report)

    def record(state, identity, **fields):
        nonlocal sequence, previous, written
        row = {"sequence": sequence, "previous_sha256": previous, "state": state, "identity": identity, **fields}
        raw = compact(row); written += len(raw)+1
        if written > 8*1024**2: raise ValueError("marked journal ceiling")
        with journal.open("ab") as stream: stream.write(raw+b"\n"); stream.flush()
        previous = hashlib.sha256(raw).hexdigest(); sequence += 1

    def check():
        if time.monotonic()-started >= 60: raise TimeoutError("60s complete mathematical stage exhausted")

    def call(kind, identity, point, function):
        check()
        ceiling = {"model_compilations": 2, "analytic_calls": 10, "scalar_calls": 162, "constraint_calls": 10}[kind]
        if report["counts"][kind] >= ceiling: raise ValueError("complete call budget exhausted")
        report["counts"][kind] += 1
        record("running", identity, kind=kind, point=point); save()
        try: result = function()
        except Exception as error:
            record("failed", identity, error_type=type(error).__name__, error=str(error)); raise
        # Returned mathematical data are durable before any check/comparison.
        if kind != "model_compilations": record("returned", identity, point=point, result=result)
        else: record("returned", identity, compiled_contract=result.contract())
        check()
        return result

    save()
    try:
        for case in document["cases"]:
            check(); row = {"id": case["id"], "points": [], "derivatives": [], "passed": False}; report["cases"].append(row); save()
            workspace_path = fm._regular(case["workspace"]["path"], base)
            workspace = json.loads(captured[str(workspace_path)])
            mc_path = fm._regular(case["MC"]["path"], base); mc = MCAuxiliaryBlock({"input": str(mc_path)})
            bg = call("model_compilations", case["id"]+"/compile", None, lambda: BackgroundAuxBlock(workspace, case["signal_samples"], measurement="measurement", policy="separable_signal_mc", model_id=case["id"]+"/background"))
            response_path = fm._regular(case["response"]["path"], base)
            provider = MarkedResponseProvider(path=response_path, sha256=case["response"]["sha256"], configuration=case["configuration"])
            joint = AnalyticPublishedJoint(bg, mc, source_workspace=workspace, signal_samples=case["signal_samples"], source_bin_map=case["source_bin_map"], model_id=case["id"]+"/analytic", response_assumptions=["Supplied artificial joint-anchor response; original source signal morph replaced.", "Independent source and complete MC auxiliary experiments."], response_provider=provider)
            configuration = {"data_id": "response", "axis_to_source": case["configuration"]["axis_to_source"]}
            implementation = Path(inspect.getsourcefile(marked_response.response))
            response_contract = {"background_contract_sha256": bg.contract_sha256, "source_workspace_sha256": bg.contract()["source_workspace_sha256"],
                "coordinate_dependencies": list(configuration["axis_to_source"].values()), "implementation_pin": {"path": str(implementation), "sha256": hashlib.sha256(_read(implementation)).hexdigest()},
                "callable_identity": response_identity(marked_response.response), "configuration": configuration, "configuration_sha256": hashlib.sha256(compact(configuration)).hexdigest(),
                "source_data_pins": [{"id": key, "path": str(path), "sha256": hashlib.sha256(captured[str(path)]).hexdigest(), "encoding": "json"} for key, path in (("response", response_path), ("workspace", workspace_path))],
                "source_workspace_data_id": "workspace", "environment_requirements": "reviewed_frozen_transitive_globals_and_dependencies", "independence": "supplied_source_and_new_MC_auxiliaries_independent", "provenance": "Exact supplied artificial categorical law and complete joint corners; no detector calibration."}
            scalar = JointPublishedFiniteMC(bg, mc, source_workspace=workspace, signal_samples=case["signal_samples"], source_bin_map=case["source_bin_map"], response=marked_response.response, response_contract=response_contract, model_id=case["id"]+"/scalar", main_disposition="replace_conditional_control_with_bound_published_source")
            axes = _axes(bg, mc)
            if len(axes) != case["expected_free_coordinates"]: raise ValueError("compiled tangent census differs")
            row.update(joint_contract=joint.contract(), tangent_order=axes); save()
            def scalar_call(point, identity):
                # Persist the actual oracle return BEFORE any derived-moment
                # metadata construction or dependent comparison can fail.
                result = call("scalar_calls", identity, point,
                              lambda: scalar.evaluate(point["source"], point["latent"], mu=point["mu"]))
                value = _complete_scalar_means(result, point, bg.contract(), mc.document(), mc.class_ids)
                record("derived_scalar_means", identity, result=value)
                check()
                return value
            for index, point in enumerate(case["points"]):
                identity = case["id"]+"/point/"+str(index)
                analytic = call("analytic_calls", identity+"/analytic", point, lambda: joint.evaluate_with_gradient(point["source"], point["latent"], mu=point["mu"]))
                def constraints():
                    values, jac = joint.physical_constraints_at(point["source"], point["latent"])
                    return {"values": values.tolist(), "jacobian": jac.tolist()}
                constraint = call("constraint_calls", identity+"/constraints", point, constraints)
                value = scalar_call(point, identity+"/scalar")
                passed = value["finite"] and _close(analytic["joint_logpdf"], value["joint_logpdf"], 1e-8, 1e-10)
                passed = passed and len(analytic["distribution_mean_vector"]) == len(value["complete_distribution_means"])
                passed = passed and all(_close(a,b,1e-9,1e-10) for a,b in zip(analytic["distribution_mean_vector"],value["complete_distribution_means"]))
                passed = passed and len(constraint["values"]) == len(value["physical_constraints"]) and all(_close(a,b,1e-9,1e-10) for a,b in zip(constraint["values"],value["physical_constraints"]))
                row["points"].append({"index": index, "passed": bool(passed), "analytic": analytic, "scalar": value, "constraints": constraint}); save()
                if index in case["derivative_points"]:
                    gradient, mean_jac = _tangent_columns(analytic, axes, mc.class_ids[-1])
                    for column, axis in enumerate(axes):
                        h = 1e-5; differences = []
                        for step in (h,h/2):
                            plus = scalar_call(_shift(point,axis,step,mc.class_ids[-1]),identity+"/"+axis+"/+"+str(step))
                            minus = scalar_call(_shift(point,axis,-step,mc.class_ids[-1]),identity+"/"+axis+"/-"+str(step))
                            if not plus["finite"] or not minus["finite"]: raise ValueError("derivative probe has zero probability")
                            differences.append({"nll": -(plus["joint_logpdf"]-minus["joint_logpdf"])/(2*step), "distribution_means": [(a-b)/(2*step) for a,b in zip(plus["complete_distribution_means"],minus["complete_distribution_means"])],
                                                "physical_constraints": [(a-b)/(2*step) for a,b in zip(plus["physical_constraints"],minus["physical_constraints"])]})
                        passed = all(_close(gradient[column],v["nll"]) for v in differences) and _close(differences[0]["nll"],differences[1]["nll"])
                        passed = passed and all(_close(mean_jac[b][column], v["distribution_means"][b]) for b in range(len(mean_jac)) for v in differences)
                        full_order = analytic["coordinate_order"][1:]
                        constraint_gradient = ([0.]*len(constraint["values"]) if axis == "mu" else [
                            r[full_order.index(axis)]-(r[full_order.index("MC:"+mc.class_ids[-1])] if axis.startswith("MC:") else 0.) for r in constraint["jacobian"]])
                        passed = passed and all(_close(a,v["physical_constraints"][i]) for i,a in enumerate(constraint_gradient) for v in differences)
                        row["derivatives"].append({"point_index": index, "axis": axis, "passed": bool(passed), "analytic_score": gradient[column], "differences": differences}); save()
            row["passed"] = all(v["passed"] for v in row["points"]+row["derivatives"]); save()
        expected = {"model_compilations":2,"analytic_calls":10,"scalar_calls":162,"constraint_calls":10}
        report["status"] = "passed" if report["counts"] == expected and all(c["passed"] for c in report["cases"]) else "failed"
    except Exception as error:
        report.update(status="failed", error_type=type(error).__name__, error=str(error))
    finally:
        report["input_custody_errors"] = []
        for path, raw in captured.items():
            try:
                if _read(fm._regular(path, Path.cwd())) != raw: raise ValueError("input bytes changed")
            except Exception as error:
                report["input_custody_errors"].append({"path": path, "error_type": type(error).__name__, "error": str(error)})
        if report["input_custody_errors"]: report["status"] = "failed"
        report["elapsed_seconds"] = time.monotonic()-started
        if report["elapsed_seconds"] >= 60: report["status"] = "failed"
        save()
    return report
